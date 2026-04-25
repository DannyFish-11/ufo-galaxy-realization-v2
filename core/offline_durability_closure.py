#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/offline_durability_closure.py
=====================================
PR-5 (close continuity recovery and offline durability loops — V2 side):
OfflineQueueRecoveryBoundary — Bounded-Authority Offline Queue Replay Ordering.

Problem addressed
-----------------
After a reconnect, Android may deliver a batch of offline-queued signals that
accumulated while the transport was down.  Without a bounded-authority ordering
model those signals can be replayed in undefined order, triggering canonical
state drift, duplicate application, or stale recovery effects.

Specifically, the system previously lacked a single module that answered:

* In what order should offline-queued signals be replayed against V2 state?
* How are duplicates (same idempotency key) suppressed before application?
* How are stale entries (arriving after terminal canonical state) rejected?
* Who is the bounded authority that decides acceptance vs rejection for each
  queued entry?

This module closes those gaps by providing:

1. :class:`OfflineQueueEntry` — a serialisable unit-of-work representing a
   single queued signal, carrying an ``idempotency_key``, a ``sequence``
   number for ordering, and an optional ``canonical_terminal_guard`` flag.

2. :class:`OfflineQueueDisposition` — canonical outcome for a single entry:
   ``accepted``, ``rejected_duplicate``, ``rejected_stale_terminal``,
   ``rejected_out_of_authority``, or ``held_for_review``.

3. :class:`OfflineQueueEntryRecord` — the result of processing a single entry,
   combining the entry with its disposition, evidence, and timestamp.

4. :class:`OfflineQueueRecoveryBoundary` — the bounded-authority arbiter that:
   - Accepts a list of :class:`OfflineQueueEntry` objects.
   - Sorts them by ``sequence`` number (deterministic ordering).
   - Deduplicates by ``idempotency_key`` (first occurrence wins).
   - Rejects entries arriving after canonical terminal state when
     ``canonical_is_terminal=True`` is passed to :meth:`replay_ordered`.
   - Returns an ordered generator of accepted
     :class:`OfflineQueueEntry` objects.

5. :class:`OfflineQueueBoundarySnapshot` — a serialisable summary of the
   boundary's processing history, suitable for operator inspection.

Design invariants
-----------------
1. **Additive only** — does not modify any existing module.
2. **Sequence-ordered** — entries are replayed in ascending ``sequence`` order,
   not arrival-time order.
3. **Idempotency-key deduplication** — within a replay batch, only the first
   occurrence of each ``idempotency_key`` is accepted.
4. **Terminal-state guard** — when ``canonical_is_terminal=True`` all entries
   in the batch are rejected as ``rejected_stale_terminal``.
5. **V2 is arbiter** — the :class:`OfflineQueueRecoveryBoundary` runs in the
   V2 process; Android has no veto over the acceptance decision.
6. **Fully serialisable** — all data classes produce stable JSON via
   ``to_dict()`` / ``to_json()``.

Public surface
--------------
Sentinels::

    OFFLINE_DURABILITY_CLOSURE_AUTHORITY
    OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL
    OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY
    OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY
    OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY
    V2_IS_OFFLINE_QUEUE_ARBITER_POLICY
    OFFLINE_QUEUE_ORDERING_AUDIT_POLICY

Enumerations::

    OfflineQueueDisposition

Data classes::

    OfflineQueueEntry
    OfflineQueueEntryRecord
    OfflineQueueBoundarySnapshot

Class::

    OfflineQueueRecoveryBoundary

Functions::

    get_offline_queue_recovery_boundary
    reset_offline_queue_recovery_boundary
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Generator, List, Optional, Sequence

logger = logging.getLogger("Galaxy.OfflineDurabilityClosure")

__all__ = [
    # Authority sentinels
    "OFFLINE_DURABILITY_CLOSURE_AUTHORITY",
    "OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL",
    "OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY",
    "OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY",
    "OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY",
    "V2_IS_OFFLINE_QUEUE_ARBITER_POLICY",
    "OFFLINE_QUEUE_ORDERING_AUDIT_POLICY",
    # Enumerations
    "OfflineQueueDisposition",
    # Data classes
    "OfflineQueueEntry",
    "OfflineQueueEntryRecord",
    "OfflineQueueBoundarySnapshot",
    # Class
    "OfflineQueueRecoveryBoundary",
    # Functions
    "get_offline_queue_recovery_boundary",
    "reset_offline_queue_recovery_boundary",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

OFFLINE_DURABILITY_CLOSURE_AUTHORITY: str = (
    "OFFLINE_DURABILITY_CLOSURE_AUTHORITY::core.offline_durability_closure "
    "is the canonical authority for V2-side offline queue replay ordering and "
    "bounded-authority deduplication.  It owns the OfflineQueueRecoveryBoundary "
    "and the associated ordering, dedup, and terminal-state-guard policies.  PR-5."
)

OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL: str = (
    "OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL::"
    "close-continuity-recovery-and-offline-durability-loops::"
    "PR-5::package=5::post-533-dual-repo-runtime-unification::"
    "offline-queue-bounded-authority-replay-ordering"
)

OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_SEQUENCE_ORDER_IS_CANONICAL_PR-5: "
    "Offline-queued signals MUST be replayed in ascending sequence number order. "
    "Arrival time is NOT a valid ordering key: Android may deliver queued entries "
    "in non-deterministic order after reconnect.  V2 must sort by sequence before "
    "applying any entry to canonical state.  PR-5."
)

OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_PR-5: "
    "Within a replay batch, only the first occurrence of each idempotency_key is "
    "accepted.  Subsequent entries with the same key are rejected as "
    "rejected_duplicate.  This prevents double-application of the same signal "
    "during recovery replay.  PR-5."
)

OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_PR-5: "
    "When the canonical state for the target session/flow has already reached a "
    "terminal phase, ALL queued entries in the replay batch are rejected as "
    "rejected_stale_terminal regardless of their content.  A terminal canonical "
    "state must not be reopened by a replayed offline signal.  PR-5."
)

V2_IS_OFFLINE_QUEUE_ARBITER_POLICY: str = (
    "POLICY::V2_IS_OFFLINE_QUEUE_ARBITER_PR-5: "
    "OfflineQueueRecoveryBoundary runs in the V2 process and is the single "
    "arbiter of whether an offline-queued entry is accepted, rejected, or held "
    "for review.  Android has no veto over the acceptance decision.  The boundary "
    "does not delegate acceptance authority to Android-side state.  PR-5."
)

OFFLINE_QUEUE_ORDERING_AUDIT_POLICY: str = (
    "POLICY::OFFLINE_QUEUE_ORDERING_AUDIT_PR-5: "
    "Every OfflineQueueEntry processed by OfflineQueueRecoveryBoundary produces "
    "a corresponding OfflineQueueEntryRecord with its disposition and evidence. "
    "These records are retained in a ring buffer and are accessible via "
    "OfflineQueueRecoveryBoundary.build_snapshot() for operator inspection "
    "and audit.  PR-5."
)

# ---------------------------------------------------------------------------
# Ring-buffer capacity
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 256

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class OfflineQueueDisposition(str, Enum):
    """Canonical outcome for a single offline queue entry.

    Values
    ------
    accepted
        Entry was accepted; it should be forwarded to the reconciler / canonical
        state update path.
    rejected_duplicate
        Entry has an idempotency_key that was already seen in this replay batch;
        it is suppressed without applying to canonical state.
    rejected_stale_terminal
        Canonical state has already reached a terminal phase; this entry is
        rejected without alteration to canonical state.
    rejected_out_of_authority
        Entry lacks required fields (e.g. empty idempotency_key) or violates
        the authority boundary; it is rejected and held for review.
    held_for_review
        Entry could not be classified definitively; it is held for operator
        review without being applied.
    """

    accepted = "accepted"
    rejected_duplicate = "rejected_duplicate"
    rejected_stale_terminal = "rejected_stale_terminal"
    rejected_out_of_authority = "rejected_out_of_authority"
    held_for_review = "held_for_review"

    @classmethod
    def from_string(cls, value: str) -> "OfflineQueueDisposition":
        try:
            return cls(value)
        except ValueError:
            return cls.held_for_review


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OfflineQueueEntry:
    """A single offline-queued signal awaiting replay.

    Attributes
    ----------
    idempotency_key
        Unique identifier for this signal emission.  Used for deduplication.
        Must be non-empty for acceptance; empty keys are rejected as
        ``rejected_out_of_authority``.
    sequence
        Monotonically increasing integer used to order replay within a batch.
        Lower sequence numbers are replayed first.
    payload
        Arbitrary signal payload.  Opaque to the boundary; passed through
        to the caller for downstream processing.
    device_id
        Originating device identifier.  Used for audit only.
    session_id
        Session or flow identifier.  Used for audit only.
    entry_id
        Auto-generated unique identifier for this entry.
    queued_at
        Unix timestamp when the entry was originally queued on Android.
        May be None when not available.
    metadata
        Arbitrary extension metadata.
    """

    idempotency_key: str
    sequence: int
    payload: Dict[str, Any] = field(default_factory=dict)
    device_id: str = ""
    session_id: str = ""
    entry_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    queued_at: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "sequence": self.sequence,
            "payload": self.payload,
            "device_id": self.device_id,
            "session_id": self.session_id,
            "entry_id": self.entry_id,
            "queued_at": self.queued_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineQueueEntry":
        return cls(
            idempotency_key=data.get("idempotency_key", ""),
            sequence=int(data.get("sequence", 0)),
            payload=data.get("payload", {}),
            device_id=data.get("device_id", ""),
            session_id=data.get("session_id", ""),
            entry_id=data.get("entry_id", str(uuid.uuid4())),
            queued_at=data.get("queued_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class OfflineQueueEntryRecord:
    """Result of processing a single :class:`OfflineQueueEntry`.

    Attributes
    ----------
    entry_id
        The ``entry_id`` of the processed :class:`OfflineQueueEntry`.
    idempotency_key
        The ``idempotency_key`` of the processed entry.
    sequence
        The ``sequence`` of the processed entry.
    disposition
        The :class:`OfflineQueueDisposition` assigned by the boundary.
    evidence
        Key-value pairs explaining the disposition decision.
    record_id
        Auto-generated unique identifier for this record.
    processed_at
        Unix timestamp when this record was created.
    """

    entry_id: str
    idempotency_key: str
    sequence: int
    disposition: OfflineQueueDisposition
    evidence: Dict[str, Any] = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    processed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "idempotency_key": self.idempotency_key,
            "sequence": self.sequence,
            "disposition": self.disposition.value,
            "evidence": self.evidence,
            "record_id": self.record_id,
            "processed_at": self.processed_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OfflineQueueEntryRecord":
        return cls(
            entry_id=data.get("entry_id", ""),
            idempotency_key=data.get("idempotency_key", ""),
            sequence=int(data.get("sequence", 0)),
            disposition=OfflineQueueDisposition.from_string(
                data.get("disposition", "")
            ),
            evidence=data.get("evidence", {}),
            record_id=data.get("record_id", str(uuid.uuid4())),
            processed_at=data.get("processed_at", time.time()),
        )


@dataclass
class OfflineQueueBoundarySnapshot:
    """Serialisable snapshot of the :class:`OfflineQueueRecoveryBoundary` state.

    Attributes
    ----------
    total_entries_processed
        Cumulative count of all entries processed since boundary creation.
    total_accepted
        Cumulative count of accepted entries.
    total_rejected_duplicate
        Cumulative count of entries rejected as duplicate.
    total_rejected_stale_terminal
        Cumulative count of entries rejected as stale_terminal.
    total_rejected_out_of_authority
        Cumulative count of entries rejected as out_of_authority.
    total_held_for_review
        Cumulative count of entries held for review.
    recent_records
        Most-recent processed records (up to ring-buffer capacity).
    pr5_sentinel
        Module authority sentinel string.
    snapshot_id
        Auto-generated unique identifier.
    generated_at
        Unix timestamp when this snapshot was generated.
    """

    total_entries_processed: int = 0
    total_accepted: int = 0
    total_rejected_duplicate: int = 0
    total_rejected_stale_terminal: int = 0
    total_rejected_out_of_authority: int = 0
    total_held_for_review: int = 0
    recent_records: List[Dict[str, Any]] = field(default_factory=list)
    pr5_sentinel: str = OFFLINE_DURABILITY_CLOSURE_PR5_SENTINEL
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    generated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_entries_processed": self.total_entries_processed,
            "total_accepted": self.total_accepted,
            "total_rejected_duplicate": self.total_rejected_duplicate,
            "total_rejected_stale_terminal": self.total_rejected_stale_terminal,
            "total_rejected_out_of_authority": self.total_rejected_out_of_authority,
            "total_held_for_review": self.total_held_for_review,
            "recent_records": self.recent_records,
            "pr5_sentinel": self.pr5_sentinel,
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


# ---------------------------------------------------------------------------
# OfflineQueueRecoveryBoundary
# ---------------------------------------------------------------------------


class OfflineQueueRecoveryBoundary:
    """Bounded-authority offline queue replay ordering arbiter.

    This class accepts a batch of :class:`OfflineQueueEntry` objects,
    sorts them by ascending ``sequence``, deduplicates by ``idempotency_key``
    (first-wins), and yields accepted entries via :meth:`replay_ordered`.

    Thread safety
    -------------
    The ring buffer and counters are protected by an internal
    :class:`threading.Lock` and are safe for concurrent use.

    Parameters
    ----------
    capacity
        Ring-buffer capacity for :class:`OfflineQueueEntryRecord` history.
        Defaults to 256.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity = capacity
        self._buffer: Deque[OfflineQueueEntryRecord] = deque(maxlen=capacity)
        self._lock = threading.Lock()

        # Counters
        self._total_processed = 0
        self._total_accepted = 0
        self._total_rejected_duplicate = 0
        self._total_rejected_stale_terminal = 0
        self._total_rejected_out_of_authority = 0
        self._total_held_for_review = 0

    def _record(self, rec: OfflineQueueEntryRecord) -> None:
        with self._lock:
            self._buffer.append(rec)
            self._total_processed += 1
            if rec.disposition == OfflineQueueDisposition.accepted:
                self._total_accepted += 1
            elif rec.disposition == OfflineQueueDisposition.rejected_duplicate:
                self._total_rejected_duplicate += 1
            elif rec.disposition == OfflineQueueDisposition.rejected_stale_terminal:
                self._total_rejected_stale_terminal += 1
            elif rec.disposition == OfflineQueueDisposition.rejected_out_of_authority:
                self._total_rejected_out_of_authority += 1
            elif rec.disposition == OfflineQueueDisposition.held_for_review:
                self._total_held_for_review += 1

    def replay_ordered(
        self,
        entries: Sequence[OfflineQueueEntry],
        *,
        canonical_is_terminal: bool = False,
    ) -> Generator[OfflineQueueEntry, None, None]:
        """Replay *entries* in bounded-authority sequence order.

        Processing rules (applied in this order):

        1. **Terminal guard**: if ``canonical_is_terminal=True``, all entries
           are rejected as ``rejected_stale_terminal`` without further processing.
        2. **Authority check**: entries with an empty ``idempotency_key`` are
           rejected as ``rejected_out_of_authority``.
        3. **Sequence sort**: entries are sorted by ascending ``sequence``.
        4. **Deduplication**: the first occurrence of each ``idempotency_key``
           is accepted; subsequent occurrences are rejected as ``rejected_duplicate``.

        Accepted entries are yielded in sequence order.  Rejected entries are
        only recorded in the ring buffer (they are not yielded).

        Parameters
        ----------
        entries
            Offline-queued entries to replay.
        canonical_is_terminal
            When ``True``, all entries are rejected as stale terminal.

        Yields
        ------
        OfflineQueueEntry
            Accepted entries in ascending sequence order.
        """
        # 1. Terminal guard — reject all if canonical state is terminal
        if canonical_is_terminal:
            for entry in entries:
                rec = OfflineQueueEntryRecord(
                    entry_id=entry.entry_id,
                    idempotency_key=entry.idempotency_key,
                    sequence=entry.sequence,
                    disposition=OfflineQueueDisposition.rejected_stale_terminal,
                    evidence={
                        "reason": "canonical_is_terminal=True",
                        "policy": OFFLINE_QUEUE_TERMINAL_STATE_REJECTS_ALL_ENTRIES_POLICY[:80],
                    },
                )
                self._record(rec)
                logger.debug(
                    "OfflineQueueRecoveryBoundary: rejected_stale_terminal "
                    "entry_id=%s key=%s seq=%d",
                    entry.entry_id,
                    entry.idempotency_key,
                    entry.sequence,
                )
            return

        # 2. Authority check + 3. Sequence sort
        valid_entries: List[OfflineQueueEntry] = []
        for entry in entries:
            if not entry.idempotency_key:
                rec = OfflineQueueEntryRecord(
                    entry_id=entry.entry_id,
                    idempotency_key=entry.idempotency_key,
                    sequence=entry.sequence,
                    disposition=OfflineQueueDisposition.rejected_out_of_authority,
                    evidence={"reason": "empty_idempotency_key"},
                )
                self._record(rec)
                logger.debug(
                    "OfflineQueueRecoveryBoundary: rejected_out_of_authority "
                    "entry_id=%s seq=%d (empty idempotency_key)",
                    entry.entry_id,
                    entry.sequence,
                )
            else:
                valid_entries.append(entry)

        # Sort by ascending sequence number
        sorted_entries = sorted(valid_entries, key=lambda e: e.sequence)

        # 4. Deduplication by idempotency_key (first-wins)
        seen_keys: set = set()
        for entry in sorted_entries:
            if entry.idempotency_key in seen_keys:
                rec = OfflineQueueEntryRecord(
                    entry_id=entry.entry_id,
                    idempotency_key=entry.idempotency_key,
                    sequence=entry.sequence,
                    disposition=OfflineQueueDisposition.rejected_duplicate,
                    evidence={
                        "reason": "idempotency_key_already_seen",
                        "key": entry.idempotency_key,
                        "policy": OFFLINE_QUEUE_IDEMPOTENCY_KEY_DEDUP_IS_FIRST_WINS_POLICY[:80],
                    },
                )
                self._record(rec)
                logger.debug(
                    "OfflineQueueRecoveryBoundary: rejected_duplicate "
                    "entry_id=%s key=%s seq=%d",
                    entry.entry_id,
                    entry.idempotency_key,
                    entry.sequence,
                )
                continue

            seen_keys.add(entry.idempotency_key)
            rec = OfflineQueueEntryRecord(
                entry_id=entry.entry_id,
                idempotency_key=entry.idempotency_key,
                sequence=entry.sequence,
                disposition=OfflineQueueDisposition.accepted,
                evidence={
                    "reason": "novel_idempotency_key",
                    "key": entry.idempotency_key,
                },
            )
            self._record(rec)
            logger.debug(
                "OfflineQueueRecoveryBoundary: accepted "
                "entry_id=%s key=%s seq=%d",
                entry.entry_id,
                entry.idempotency_key,
                entry.sequence,
            )
            yield entry

    def build_snapshot(self) -> OfflineQueueBoundarySnapshot:
        """Return a serialisable snapshot of current boundary state."""
        with self._lock:
            recent = [r.to_dict() for r in self._buffer]
        return OfflineQueueBoundarySnapshot(
            total_entries_processed=self._total_processed,
            total_accepted=self._total_accepted,
            total_rejected_duplicate=self._total_rejected_duplicate,
            total_rejected_stale_terminal=self._total_rejected_stale_terminal,
            total_rejected_out_of_authority=self._total_rejected_out_of_authority,
            total_held_for_review=self._total_held_for_review,
            recent_records=recent,
        )

    def list_recent(self, n: int = 10) -> List[OfflineQueueEntryRecord]:
        """Return the *n* most recently processed records (newest first)."""
        with self._lock:
            all_records = list(self._buffer)
        return list(reversed(all_records))[:n]


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON: Optional[OfflineQueueRecoveryBoundary] = None
_SINGLETON_LOCK = threading.Lock()


def get_offline_queue_recovery_boundary(
    capacity: int = _RING_BUFFER_CAPACITY,
) -> OfflineQueueRecoveryBoundary:
    """Return the process-level :class:`OfflineQueueRecoveryBoundary` singleton."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        if _SINGLETON is None:
            _SINGLETON = OfflineQueueRecoveryBoundary(capacity=capacity)
        return _SINGLETON


def reset_offline_queue_recovery_boundary() -> None:
    """Reset the singleton (test isolation helper)."""
    global _SINGLETON
    with _SINGLETON_LOCK:
        _SINGLETON = None
