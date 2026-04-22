#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/replay_audit_persistence.py
=================================
PR-B2: Canonical Truth / Replay / Conflict Audit Durability.

Provides a **durable, append-only audit store** for:

- :class:`~core.replay_foundation.ReplayFoundation` records (task execution
  snapshots, runtime events, route decisions, fallback records, retry records)
- :class:`~core.canonical_session_truth.CanonicalSessionTruthRuntime` records
  (canonical merge decisions and their truth-source evidence)
- Conflict detection / resolution artifacts emitted by
  :class:`~core.runtime_closure_audit.RuntimeClosureAudit`

These records are written to an append-only JSONL file (one JSON object per
line) so they **survive process lifetime** and are available for:

- Postmortem review and incident forensics
- Replay history reconstruction after restart
- Auditable evidence of how truth was merged and how conflicts were resolved

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  DURABLE AUDIT LAYER  (this module, PR-B2)                         │
    │                                                                     │
    │  Writes (append-only):                                             │
    │    ReplayAuditRecord  — wraps any replay/truth/conflict record     │
    │    ConflictAuditRecord — structured conflict artifact              │
    │                                                                     │
    │  Used by:                                                          │
    │    • ReplayFoundation         (record_execution / emit_event / …)  │
    │    • CanonicalSessionTruthRuntime  (record)                        │
    │    • RuntimeClosureAudit      (detect_parallel_truth_paths)        │
    │                                                                     │
    │  Downstream consumers:                                             │
    │    • Postmortem / incident forensics (file-based)                  │
    │    • Future: query API / replay viewer                             │
    └─────────────────────────────────────────────────────────────────────┘

Design invariants
-----------------
1. **Append-only.** Existing records are never modified or deleted by the store.
2. **Observational only.** The durable store is audit evidence; it is NOT a
   runtime truth source.  In-memory ring buffers in :class:`ReplayFoundation`
   and :class:`CanonicalSessionTruthRuntime` remain the authoritative runtime
   read surfaces.
3. **Graceful degradation.** If the store is unavailable (no disk, permission
   error, corrupt file), each write logs a warning but never raises.  The
   caller's in-memory record still succeeds.
4. **Thread-safe.** A per-store :class:`threading.Lock` guards all appends.
5. **JSONL format.** One JSON object per line for easy streaming and forensic
   inspection with standard tools.

Public API
----------
Sentinels::

    REPLAY_AUDIT_PERSISTENCE_AUTHORITY
    REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL
    AUDIT_STORE_IS_OBSERVATIONAL_POLICY
    CONFLICT_ARTIFACTS_DURABLE_POLICY

Data types::

    AuditRecordKind
    ReplayAuditRecord
    ConflictAuditRecord

Class::

    DurableAuditStore

Helpers::

    append_replay_audit_record(record_dict, kind, *, store)
    append_conflict_audit_record(conflict, *, store)
    load_audit_records(*, store, kind_filter) -> List[ReplayAuditRecord]
    get_replay_audit_store() -> DurableAuditStore
    reset_replay_audit_store() -> None
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    # Sentinels
    "REPLAY_AUDIT_PERSISTENCE_AUTHORITY",
    "REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL",
    "AUDIT_STORE_IS_OBSERVATIONAL_POLICY",
    "CONFLICT_ARTIFACTS_DURABLE_POLICY",
    # Enumerations
    "AuditRecordKind",
    # Data types
    "ReplayAuditRecord",
    "ConflictAuditRecord",
    # Class
    "DurableAuditStore",
    # Helpers
    "append_replay_audit_record",
    "append_conflict_audit_record",
    "load_audit_records",
    "get_replay_audit_store",
    "reset_replay_audit_store",
]

logger = logging.getLogger("Galaxy.ReplayAuditPersistence")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

REPLAY_AUDIT_PERSISTENCE_AUTHORITY: str = (
    "REPLAY_AUDIT_PERSISTENCE::PR_B2_AUTHORITY_V1: "
    "core.replay_audit_persistence is the canonical durable audit store for "
    "replay/event history, canonical truth merge decisions, and conflict "
    "detection/resolution artifacts.  It is an observational layer only — "
    "the in-memory ring buffers in ReplayFoundation and "
    "CanonicalSessionTruthRuntime remain the authoritative runtime read "
    "surfaces.  (PR-B2, canonical truth / replay / conflict audit durability.)"
)
"""Module-level authority sentinel (PR-B2)."""

REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL: str = (
    "REPLAY_AUDIT_PERSISTENCE_DURABILITY::PR_B2_CLOSED_V1: "
    "This module directly closes the replay / truth / conflict audit "
    "durability gap: replay history, canonical truth merge evidence, and "
    "conflict-detection artifacts now survive process lifetime via an "
    "append-only JSONL store that is readable for postmortem and incident "
    "forensics without relying solely on the 256-entry in-memory ring buffer."
)
"""Sentinel confirming the PR-B2 durability gap is closed."""

AUDIT_STORE_IS_OBSERVATIONAL_POLICY: str = (
    "POLICY::AUDIT_STORE_IS_OBSERVATIONAL_V1: "
    "DurableAuditStore is a write-ahead audit sink.  It MUST NOT be used as "
    "a primary runtime state source for routing, dispatch, or canonical truth "
    "determination.  Reads from the JSONL file are for forensic and replay "
    "review only.  In-memory structures (ReplayFoundation ring buffers, "
    "CanonicalSessionTruthRuntime ring buffer) remain authoritative for "
    "live runtime consumption."
)
"""Policy: the durable store is observational, not authoritative."""

CONFLICT_ARTIFACTS_DURABLE_POLICY: str = (
    "POLICY::CONFLICT_ARTIFACTS_DURABLE_V1: "
    "All AuthorityConflictEntry objects emitted by RuntimeClosureAudit "
    ".detect_parallel_truth_paths() MUST be appended to the DurableAuditStore "
    "so that conflict detection outcomes (both resolved and unresolved) are "
    "reviewable after process restart.  Callers must not silently discard "
    "conflict artifacts."
)
"""Policy: conflict detection artifacts must be durably recorded."""

# ---------------------------------------------------------------------------
# Default store paths
# ---------------------------------------------------------------------------

_DATA_DIR = os.environ.get("GALAXY_DATA_DIR", "data")

_DEFAULT_REPLAY_STORE_PATH = os.path.join(_DATA_DIR, "replay_audit.jsonl")

# ---------------------------------------------------------------------------
# AuditRecordKind
# ---------------------------------------------------------------------------


class AuditRecordKind(str, Enum):
    """Classification of a durable audit record.

    Values
    ------
    TASK_EXECUTION
        A :class:`~core.replay_foundation.TaskExecutionRecord` snapshot.
    RUNTIME_EVENT
        A :class:`~core.replay_foundation.RuntimeEventRecord`.
    ROUTE_DECISION
        A :class:`~core.replay_foundation.RouteDecisionRecord`.
    FALLBACK
        A :class:`~core.replay_foundation.ReplayFallbackRecord`.
    RETRY
        A :class:`~core.replay_foundation.ReplayRetryRecord`.
    CANONICAL_TRUTH_MERGE
        A :class:`~core.canonical_session_truth.CanonicalSessionTruthRecord`
        describing a truth merge outcome.
    CONFLICT_DETECTED
        A :class:`ConflictAuditRecord` for an unresolved authority conflict.
    CONFLICT_RESOLVED
        A :class:`ConflictAuditRecord` for a conflict that has been resolved.
    """

    TASK_EXECUTION = "task_execution"
    RUNTIME_EVENT = "runtime_event"
    ROUTE_DECISION = "route_decision"
    FALLBACK = "fallback"
    RETRY = "retry"
    CANONICAL_TRUTH_MERGE = "canonical_truth_merge"
    CONFLICT_DETECTED = "conflict_detected"
    CONFLICT_RESOLVED = "conflict_resolved"


# ---------------------------------------------------------------------------
# ReplayAuditRecord — envelope written to the JSONL store
# ---------------------------------------------------------------------------


@dataclass
class ReplayAuditRecord:
    """Envelope that wraps any audit payload written to the JSONL store.

    Parameters
    ----------
    audit_id:
        Unique identifier for this audit envelope.
    kind:
        :class:`AuditRecordKind` classifying the payload.
    recorded_at:
        Unix epoch seconds when this envelope was created.
    payload:
        The serialisable dict of the underlying record.
    process_pid:
        PID of the process that wrote this record (informational).
    authority:
        Module authority sentinel for provenance.
    """

    audit_id: str = field(
        default_factory=lambda: f"aud_{uuid.uuid4().hex[:16]}"
    )
    kind: str = AuditRecordKind.RUNTIME_EVENT.value
    recorded_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)
    process_pid: int = field(default_factory=os.getpid)
    authority: str = REPLAY_AUDIT_PERSISTENCE_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "audit_id": self.audit_id,
            "kind": self.kind,
            "recorded_at": self.recorded_at,
            "payload": self.payload,
            "process_pid": self.process_pid,
            "authority": self.authority,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReplayAuditRecord":
        """Reconstruct from a deserialised dict."""
        return cls(
            audit_id=d.get("audit_id", f"aud_{uuid.uuid4().hex[:16]}"),
            kind=d.get("kind", AuditRecordKind.RUNTIME_EVENT.value),
            recorded_at=float(d.get("recorded_at", time.time())),
            payload=dict(d.get("payload", {})),
            process_pid=int(d.get("process_pid", 0)),
            authority=d.get("authority", REPLAY_AUDIT_PERSISTENCE_AUTHORITY),
        )


# ---------------------------------------------------------------------------
# ConflictAuditRecord — structured record for conflict artifacts
# ---------------------------------------------------------------------------


@dataclass
class ConflictAuditRecord:
    """Structured record capturing a conflict detection / resolution artifact.

    Wraps an :class:`~core.runtime_closure_audit.AuthorityConflictEntry` with
    the additional context needed for durable audit reviewability.

    Parameters
    ----------
    conflict_id:
        Stable identifier for the conflict (e.g. ``"CONFLICT-005"``).
    runtime_fact:
        Human-readable name of the runtime fact subject to competing authority.
    layer_a / layer_b:
        The two competing layers or modules.
    description:
        Concise description of the conflict.
    is_resolved:
        ``True`` when the conflict has been closed.
    resolution_note:
        Human-readable description of how the conflict was resolved.
    detected_at:
        Unix epoch seconds when the conflict was recorded.
    audit_run_id:
        Optional identifier linking this record to a specific audit run.
    """

    conflict_id: str = ""
    runtime_fact: str = ""
    layer_a: str = ""
    layer_b: str = ""
    description: str = ""
    is_resolved: bool = False
    resolution_note: str = ""
    detected_at: float = field(default_factory=time.time)
    audit_run_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "conflict_id": self.conflict_id,
            "runtime_fact": self.runtime_fact,
            "layer_a": self.layer_a,
            "layer_b": self.layer_b,
            "description": self.description,
            "is_resolved": self.is_resolved,
            "resolution_note": self.resolution_note,
            "detected_at": self.detected_at,
            "audit_run_id": self.audit_run_id,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ConflictAuditRecord":
        """Reconstruct from a deserialised dict."""
        return cls(
            conflict_id=d.get("conflict_id", ""),
            runtime_fact=d.get("runtime_fact", ""),
            layer_a=d.get("layer_a", ""),
            layer_b=d.get("layer_b", ""),
            description=d.get("description", ""),
            is_resolved=bool(d.get("is_resolved", False)),
            resolution_note=d.get("resolution_note", ""),
            detected_at=float(d.get("detected_at", time.time())),
            audit_run_id=d.get("audit_run_id", ""),
        )

    @classmethod
    def from_authority_conflict_entry(
        cls,
        entry: Any,
        *,
        audit_run_id: str = "",
    ) -> "ConflictAuditRecord":
        """Build from an :class:`~core.runtime_closure_audit.AuthorityConflictEntry`.

        Accepts both dataclass and dict representations for forward-compat.
        """
        if isinstance(entry, dict):
            return cls(
                conflict_id=entry.get("conflict_id", ""),
                runtime_fact=entry.get("runtime_fact", ""),
                layer_a=entry.get("layer_a", ""),
                layer_b=entry.get("layer_b", ""),
                description=entry.get("description", ""),
                is_resolved=bool(entry.get("is_resolved", False)),
                resolution_note=entry.get("resolution_note", ""),
                audit_run_id=audit_run_id,
            )
        return cls(
            conflict_id=getattr(entry, "conflict_id", ""),
            runtime_fact=getattr(entry, "runtime_fact", ""),
            layer_a=getattr(entry, "layer_a", ""),
            layer_b=getattr(entry, "layer_b", ""),
            description=getattr(entry, "description", ""),
            is_resolved=bool(getattr(entry, "is_resolved", False)),
            resolution_note=getattr(entry, "resolution_note", ""),
            audit_run_id=audit_run_id,
        )


# ---------------------------------------------------------------------------
# DurableAuditStore — append-only JSONL file store
# ---------------------------------------------------------------------------


class DurableAuditStore:
    """Append-only, thread-safe JSONL file store for durable audit records.

    Each :meth:`append` call writes exactly one line of JSON to the backing
    file.  Existing lines are never modified or deleted, ensuring a permanent
    audit trail.

    The file can be inspected with any JSONL-aware tool::

        # Show all conflict records:
        grep '"kind": "conflict' data/replay_audit.jsonl | python -m json.tool

        # Load full history in Python:
        from core.replay_audit_persistence import load_audit_records
        records = load_audit_records()

    Parameters
    ----------
    store_path:
        Absolute or relative path to the JSONL audit file.  Defaults to
        ``data/replay_audit.jsonl`` (or ``$GALAXY_DATA_DIR/replay_audit.jsonl``).
    """

    def __init__(self, store_path: Optional[str] = None) -> None:
        self._store_path = store_path or _DEFAULT_REPLAY_STORE_PATH
        self._lock = threading.Lock()
        # Eagerly ensure the parent directory exists.
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(self._store_path)),
                exist_ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DurableAuditStore: could not create store directory: %s", exc
            )

    # ── Write ─────────────────────────────────────────────────────────────

    def append(self, record: ReplayAuditRecord) -> bool:
        """Append *record* as a single JSON line to the audit file.

        Parameters
        ----------
        record:
            The :class:`ReplayAuditRecord` envelope to persist.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed (error logged).
        """
        try:
            line = json.dumps(record.to_dict(), ensure_ascii=False) + "\n"
            with self._lock:
                with open(self._store_path, "a", encoding="utf-8") as fh:
                    fh.write(line)
            logger.debug(
                "DurableAuditStore: appended %s record %s",
                record.kind,
                record.audit_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "DurableAuditStore: failed to append record (kind=%s): %s",
                record.kind,
                exc,
            )
            return False

    # ── Read ──────────────────────────────────────────────────────────────

    def load_all(
        self,
        *,
        kind_filter: Optional[str] = None,
    ) -> List[ReplayAuditRecord]:
        """Load all records from the JSONL file.

        Parameters
        ----------
        kind_filter:
            When supplied, only records whose ``kind`` matches this string are
            returned.  Use :class:`AuditRecordKind` values.

        Returns
        -------
        List[ReplayAuditRecord]
            Records in file order (oldest first).  Empty list when the file
            does not exist or cannot be read.
        """
        results: List[ReplayAuditRecord] = []
        with self._lock:
            if not os.path.exists(self._store_path):
                return results
            try:
                with open(self._store_path, "r", encoding="utf-8") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                            rec = ReplayAuditRecord.from_dict(d)
                            if kind_filter is None or rec.kind == kind_filter:
                                results.append(rec)
                        except Exception as parse_exc:  # noqa: BLE001
                            logger.debug(
                                "DurableAuditStore: skipping malformed line: %s",
                                parse_exc,
                            )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DurableAuditStore: failed to load records: %s", exc
                )
        return results

    # ── Inspect ───────────────────────────────────────────────────────────

    def count(self, *, kind_filter: Optional[str] = None) -> int:
        """Return the number of records (optionally filtered by *kind*)."""
        return len(self.load_all(kind_filter=kind_filter))

    # ── Clear (test isolation only) ────────────────────────────────────────

    def clear(self) -> bool:
        """Remove the JSONL file.  Safe when file does not exist.

        .. warning::
            This permanently destroys the audit history.  Use only in tests.

        Returns
        -------
        bool
            ``True`` if the file was deleted or did not exist; ``False`` on error.
        """
        with self._lock:
            if not os.path.exists(self._store_path):
                return True
            try:
                os.unlink(self._store_path)
                logger.debug("DurableAuditStore: audit file cleared")
                return True
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "DurableAuditStore: failed to clear store: %s", exc
                )
                return False

    @property
    def store_path(self) -> str:
        """Absolute path to the JSONL audit file."""
        return self._store_path


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_store_instance: Optional[DurableAuditStore] = None
_store_lock = threading.Lock()


def get_replay_audit_store(
    store_path: Optional[str] = None,
) -> DurableAuditStore:
    """Return (or lazily create) the process-level :class:`DurableAuditStore`.

    Parameters
    ----------
    store_path:
        Optional path override.  Respected only on first call before the
        singleton is initialised.

    Returns
    -------
    DurableAuditStore
    """
    global _store_instance
    with _store_lock:
        if _store_instance is None:
            _store_instance = DurableAuditStore(store_path=store_path)
    return _store_instance


def reset_replay_audit_store() -> None:
    """Reset the process-level singleton.  For test isolation only."""
    global _store_instance
    with _store_lock:
        _store_instance = None


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


def append_replay_audit_record(
    record_dict: Dict[str, Any],
    kind: str,
    *,
    store: Optional[DurableAuditStore] = None,
) -> bool:
    """Wrap *record_dict* in a :class:`ReplayAuditRecord` and append to *store*.

    Parameters
    ----------
    record_dict:
        The serialisable dict of the underlying record (e.g. from
        ``TaskExecutionRecord.to_dict()``).
    kind:
        :class:`AuditRecordKind` value string classifying the record.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    bool
        ``True`` on success; ``False`` on write failure.
    """
    _store = store or get_replay_audit_store()
    envelope = ReplayAuditRecord(
        kind=kind,
        payload=dict(record_dict),
    )
    return _store.append(envelope)


def append_conflict_audit_record(
    conflict: Any,
    *,
    audit_run_id: str = "",
    store: Optional[DurableAuditStore] = None,
) -> bool:
    """Build a :class:`ConflictAuditRecord` from *conflict* and append to *store*.

    Parameters
    ----------
    conflict:
        An :class:`~core.runtime_closure_audit.AuthorityConflictEntry`
        instance (or compatible dict).
    audit_run_id:
        Optional identifier linking this record to a specific audit run.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    bool
        ``True`` on success; ``False`` on write failure.
    """
    _store = store or get_replay_audit_store()
    artifact = ConflictAuditRecord.from_authority_conflict_entry(
        conflict, audit_run_id=audit_run_id
    )
    kind = (
        AuditRecordKind.CONFLICT_RESOLVED.value
        if artifact.is_resolved
        else AuditRecordKind.CONFLICT_DETECTED.value
    )
    envelope = ReplayAuditRecord(kind=kind, payload=artifact.to_dict())
    return _store.append(envelope)


def load_audit_records(
    *,
    store: Optional[DurableAuditStore] = None,
    kind_filter: Optional[str] = None,
) -> List[ReplayAuditRecord]:
    """Load audit records from the durable store.

    Parameters
    ----------
    store:
        Optional explicit store.  Defaults to the process-level singleton.
    kind_filter:
        When supplied, only records whose ``kind`` matches are returned.

    Returns
    -------
    List[ReplayAuditRecord]
        Records in file order (oldest first).
    """
    _store = store or get_replay_audit_store()
    return _store.load_all(kind_filter=kind_filter)
