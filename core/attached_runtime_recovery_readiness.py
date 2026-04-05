"""core/attached_runtime_recovery_readiness.py
================================================
PR package 15 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Host-Side Recovery Readiness / Resilience Foundations for
Attached Android Runtime Reuse.

Background
----------
After PR-14 established persistent reuse bindings that allow the host to
dispatch multiple delegated tasks to the same attached Android runtime without
re-forming ad-hoc targeting, the host-side orchestration layer gains the ability
to maintain long-lived dispatch relationships.  However, intermittent network
conditions that are common in mobile / attached-device deployments can produce:

* **Duplicate signals** — the same ACK, PROGRESS, or RESULT signal is delivered
  more than once (e.g. when the Android device retries a send after a transient
  disconnect, or when an intermediate relay re-emits a cached message).
* **Out-of-order signals** — a later PROGRESS with a higher sequence number
  arrives before an earlier one, or a RESULT arrives before the expected ACK
  sequence has concluded.
* **Replay signals** — a previously-seen signal (identified by its idempotency
  key) is re-submitted during a session-resume or recovery attempt.
* **Stale signals** — signals whose sequence numbers lag behind the already
  committed tracker sequence, rendering them semantically obsolete even if
  structurally valid.

Without explicit guards, each of the above scenarios can corrupt the canonical
host-side execution-tracking record (PR-10) by applying the same phase transition
twice, regressing the tracker sequence counter, or closing an in-progress
tracking record prematurely.

PR-15 closes this gap on the MAIN-repo side by introducing **canonical recovery
readiness scaffolding** — not the full recovery control plane, but the minimal
set of data structures and guard functions needed to make ACK / PROGRESS /
RESULT reconciliation safe against duplicates, out-of-order delivery, and
replay, so that later recovery-control-plane work (PR-16+) has a stable
foundation to build on.

What this module provides
-------------------------
1. :class:`SignalGuardDecision` — canonical enum classifying the host-side
   verdict for each inbound Android execution signal:
   ``accept`` / ``duplicate`` / ``stale`` / ``replay`` / ``out_of_order``.
2. :class:`RecoveryReadinessStatus` — host-level readiness indicator:
   ``ready`` / ``recovering`` / ``degraded``.
3. :class:`IdempotencyKey` — typed, serialisable identity record that
   canonically identifies a single inbound signal for deduplication purposes,
   combining ``contract_id``, ``session_id``, ``trace_id``, ``task_id``,
   ``device_id``, ``signal_kind``, and an optional ``seq_num``.
4. :class:`SeenSignalRecord` — lightweight record noting that an idempotency
   key has been processed, together with the guard decision applied and the
   Unix timestamp of first receipt.
5. :class:`SignalGuardOutcome` — typed result of a guard evaluation: the
   :class:`SignalGuardDecision`, the resolved :class:`IdempotencyKey`, boolean
   convenience flags (``is_duplicate``, ``is_out_of_order``, ``is_replay``,
   ``is_stale``), and a human-readable ``reason`` string.
6. :class:`RecoveryReadinessSnapshot` — point-in-time summary of the ring-buffer
   state (total seen, accept / duplicate / stale / replay / out_of_order counts,
   the full list of :class:`SeenSignalRecord` items).
7. :class:`RecoveryReadinessRuntime` — 128-entry in-process ring-buffer that
   accumulates :class:`SeenSignalRecord` items; backed by a ``deque`` for
   O(1) eviction and a ``dict`` index for O(1) idempotency key lookup.
8. :func:`build_idempotency_key` — pure function that constructs a
   :class:`IdempotencyKey` from raw signal fields, normalising empty strings
   and defaulting ``seq_num`` to 0.
9. :func:`check_signal_guard` — pure function that evaluates a
   :class:`IdempotencyKey` against the ring-buffer and returns a
   :class:`SignalGuardOutcome` without mutating state.
10. :func:`record_seen_signal` — mutates the ring-buffer to mark an
    idempotency key as seen.
11. :func:`guard_inbound_signal` — convenience combinator:
    ``build_idempotency_key`` → ``check_signal_guard`` → ``record_seen_signal``
    (only on ``accept``) → return :class:`SignalGuardOutcome`.
12. :func:`build_recovery_readiness_snapshot` — assemble a
    :class:`RecoveryReadinessSnapshot` from the current ring-buffer state.
13. :func:`get_recovery_readiness_runtime` /
    :func:`reset_recovery_readiness_runtime` — process-singleton accessor and
    test-isolation helper.
14. Ten policy sentinels documenting canonical recovery readiness rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Guard-first** — all inbound signal processing should call
  :func:`guard_inbound_signal` before forwarding to the reconciler (PR-13).
  A ``duplicate`` / ``replay`` / ``stale`` / ``out_of_order`` decision means
  the signal MUST NOT be forwarded to the tracker.
- **Identity-continuous** — ``contract_id``, ``session_id``, ``trace_id``,
  ``task_id``, and ``device_id`` flow unchanged from the inbound envelope
  through the idempotency key and back to callers; this module never synthesises
  identifiers.
- **Seq-num aware** — when ``seq_num > 0`` in both the incoming signal and the
  latest seen record for the same (contract_id, session_id, signal_kind) prefix,
  a lower seq_num is classified as ``out_of_order``; an equal seq_num from a
  seen key is classified as ``duplicate``.
- **Replay-safe** — exact idempotency key matches (all fields equal) that
  were previously classified as ``accept`` are re-classified as ``replay``
  when re-submitted.
- **Non-blocking on miss** — if the ring-buffer has no prior record for an
  idempotency key the guard returns ``accept`` immediately; this module does
  not block normal forward progress.
- **Graceful degradation** — missing or empty fields default to safe outcomes
  (``accept`` on an unpopulated key, conservative seq_num = 0).

PR package numbering
--------------------
Package 15 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.  Android-side concerns (session reuse / invalidation
foundations, PR-14 Android side) are out of scope for this module.

Relationship to other PR packages
----------------------------------
* PR-10 (``core.delegated_runtime_execution_tracker``) — guard outcomes gate
  which signals are forwarded to ``apply_acknowledgment_signal`` / ``apply_result``.
* PR-13 (``core.android_execution_signal_reconciler``) — guard outcomes gate
  which :class:`~core.android_execution_signal_reconciler.AndroidExecutionSignalEnvelope`
  objects reach ``reconcile_android_execution_signal``.
* PR-14 (``core.attached_runtime_reuse_binding``) — reuse binding records
  supply the ``session_id`` / ``device_id`` fields used to scope idempotency
  keys to a particular attached runtime session.

Public API
----------
Sentinels::

    ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY
    RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL_POLICY
    RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED_POLICY
    RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED_POLICY
    RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED_POLICY
    RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED_POLICY
    RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE_POLICY
    RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED_POLICY
    RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY_POLICY
    RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD_POLICY
    RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE_POLICY
    ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL

Enums::

    SignalGuardDecision
    RecoveryReadinessStatus

Dataclasses::

    IdempotencyKey
    SeenSignalRecord
    SignalGuardOutcome
    RecoveryReadinessSnapshot

Runtime / ring-buffer::

    RecoveryReadinessRuntime

Functions::

    build_idempotency_key
    check_signal_guard
    record_seen_signal
    guard_inbound_signal
    build_recovery_readiness_snapshot
    get_recovery_readiness_runtime
    reset_recovery_readiness_runtime
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY: str = (
    "ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY::"
    "core.attached_runtime_recovery_readiness is the canonical authority for "
    "host-side recovery readiness / resilience foundations for attached Android "
    "runtime reuse on the main-repo side (PR package 15, post-533 dual-repo "
    "runtime unification).  All delegated-dispatch signal ingestion code that "
    "targets an attached Android runtime surface MUST call guard_inbound_signal() "
    "before forwarding signals to the execution tracker or signal reconciler."
)

RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL_POLICY: str = (
    "POLICY::RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL: the canonical "
    "idempotency key for a delegated execution signal is built from the tuple "
    "(contract_id, session_id, trace_id, task_id, device_id, signal_kind, "
    "seq_num).  All components must be normalised (empty string for absent "
    "optional fields, 0 for absent seq_num) before comparison.  Callers MUST "
    "use build_idempotency_key() and MUST NOT construct raw key strings ad hoc."
)

RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED_POLICY: str = (
    "POLICY::RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED: when "
    "guard_inbound_signal() returns SignalGuardDecision.duplicate, the caller "
    "MUST silently discard the signal and MUST NOT forward it to the execution "
    "tracker (PR-10) or the signal reconciler (PR-13).  Duplicate signals are "
    "safe to drop because the effect of the first delivery has already been "
    "committed to the tracker."
)

RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED_POLICY: str = (
    "POLICY::RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED: when "
    "guard_inbound_signal() returns SignalGuardDecision.out_of_order (seq_num "
    "of the incoming signal is lower than the highest seen seq_num for the "
    "same contract_id / session_id / signal_kind prefix), the caller MUST NOT "
    "apply the signal to the tracker without explicit out-of-order handling "
    "logic.  The default safe action is to drop the signal."
)

RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED_POLICY: str = (
    "POLICY::RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED: when "
    "guard_inbound_signal() returns SignalGuardDecision.replay (the exact "
    "idempotency key has been seen before with an 'accept' decision), the "
    "caller MUST NOT re-apply the signal to the tracker.  Replay scenarios "
    "arise during session-resume attempts when Android-side retransmits a "
    "signal whose effect has already been committed."
)

RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED_POLICY: str = (
    "POLICY::RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED: the "
    "idempotency key carries the full identity tuple (contract_id, session_id, "
    "trace_id, task_id, device_id) unchanged from the inbound signal envelope.  "
    "This module never synthesises, replaces, or truncates identity fields; "
    "identity continuity across session reuse, recovery, and resume scenarios "
    "is guaranteed by preserving all five identity components in the key."
)

RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE_POLICY: str = (
    "POLICY::RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE: a signal "
    "whose seq_num is lower than the maximum seq_num already accepted for the "
    "same (contract_id, session_id, signal_kind) combination is classified as "
    "stale.  Stale signals MUST NOT be forwarded to the execution tracker; "
    "applying them would regress the tracker's acknowledged sequence counter."
)

RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED_POLICY: str = (
    "POLICY::RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED: a signal whose "
    "idempotency key has not been seen before (no prior record in the "
    "ring-buffer for the exact key) and whose seq_num is >= the highest seen "
    "seq_num for the (contract_id, session_id, signal_kind) prefix is "
    "classified as 'accept'.  Fresh signals MUST be forwarded to the execution "
    "tracker and signal reconciler normally."
)

RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY_POLICY: str = (
    "POLICY::RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY: this module is purely "
    "additive.  It does not modify core.delegated_runtime_execution_tracker, "
    "core.android_execution_signal_reconciler, or any other existing module.  "
    "Callers integrate by calling guard_inbound_signal() before forwarding to "
    "the reconciler; no existing call sites need to be modified by this module."
)

RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD_POLICY: str = (
    "POLICY::RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD: when seq_num is "
    "present (> 0) in both the incoming signal and the highest seen record for "
    "the same (contract_id, session_id, signal_kind) prefix, seq_num comparison "
    "is the canonical out-of-order and stale detection mechanism.  When seq_num "
    "is absent (= 0) in either, sequence-number ordering is not enforced and "
    "the decision falls back to exact-key idempotency matching only."
)

RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE_POLICY: str = (
    "POLICY::RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE: duplicate or "
    "replay signals for a contract_id / session_id whose tracking record is "
    "already in a terminal phase (completed / failed / timed_out / cancelled) "
    "are safe to drop without inspecting the tracker.  The guard ring-buffer "
    "already records the final signal as 'accept'; any re-delivery of the same "
    "key is classified as 'replay' and dropped before reaching the reconciler."
)

ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL: str = (
    "ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL::package=15 "
    "canonical-host-side-recovery-readiness-post-533-main-repo-pr15-v1"
)

_ALL_POLICY_SENTINELS: Tuple[str, ...] = (
    ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY,
    RECOVERY_READINESS_IDEMPOTENCY_KEY_IS_CANONICAL_POLICY,
    RECOVERY_READINESS_DUPLICATE_SIGNAL_IS_SILENTLY_DROPPED_POLICY,
    RECOVERY_READINESS_OUT_OF_ORDER_SIGNAL_IS_GUARDED_POLICY,
    RECOVERY_READINESS_REPLAY_SIGNAL_IS_GUARDED_POLICY,
    RECOVERY_READINESS_IDENTITY_CONTINUITY_IS_PRESERVED_POLICY,
    RECOVERY_READINESS_STALE_SIGNAL_DOES_NOT_ADVANCE_PHASE_POLICY,
    RECOVERY_READINESS_FRESH_SIGNAL_IS_ACCEPTED_POLICY,
    RECOVERY_READINESS_GUARD_IS_ADDITIVE_ONLY_POLICY,
    RECOVERY_READINESS_SEQ_NUM_DRIVES_ORDER_GUARD_POLICY,
    RECOVERY_READINESS_TERMINAL_RECORD_DEDUPE_IS_SAFE_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_RING_BUFFER_CAPACITY: int = 128

# ---------------------------------------------------------------------------
# SignalGuardDecision
# ---------------------------------------------------------------------------


class SignalGuardDecision(str, Enum):
    """Canonical host-side guard verdict for an inbound Android execution signal.

    accept
        The signal is fresh and should be forwarded to the execution tracker
        and signal reconciler.  The guard records the idempotency key as seen.
    duplicate
        The exact idempotency key (all seven fields equal) has been seen
        before.  The signal MUST be silently dropped.
    stale
        The signal's ``seq_num`` is lower than the highest ``seq_num`` already
        accepted for the same (contract_id, session_id, signal_kind) prefix.
        The signal must not be forwarded to the tracker.
    replay
        The exact idempotency key was previously accepted.  This verdict is
        returned when the key is re-submitted after a session resume or
        recovery attempt.
    out_of_order
        The signal's ``seq_num`` is lower than the highest ``seq_num`` already
        seen for the same (contract_id, session_id, signal_kind) prefix and a
        higher-seq_num signal for that prefix has already been accepted.
    """

    accept = "accept"
    duplicate = "duplicate"
    stale = "stale"
    replay = "replay"
    out_of_order = "out_of_order"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "SignalGuardDecision" = None,
    ) -> "SignalGuardDecision":
        """Return the enum member matching *value*, or *default* / ``accept``."""
        if default is None:
            default = cls.accept
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# RecoveryReadinessStatus
# ---------------------------------------------------------------------------


class RecoveryReadinessStatus(str, Enum):
    """Host-level recovery readiness indicator.

    ready
        The guard ring-buffer is operating normally; no anomalous duplicate /
        replay / out-of-order signals have been observed recently.
    recovering
        One or more non-fresh signal decisions (duplicate / stale / replay /
        out_of_order) have been observed; the host is monitoring for further
        anomalies but has not entered a degraded state.
    degraded
        A significant proportion of recent signals have been classified as
        non-fresh, suggesting persistent network issues or a malfunctioning
        Android peer.
    """

    ready = "ready"
    recovering = "recovering"
    degraded = "degraded"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "RecoveryReadinessStatus" = None,
    ) -> "RecoveryReadinessStatus":
        """Return the enum member matching *value*, or *default* / ``ready``."""
        if default is None:
            default = cls.ready
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


# ---------------------------------------------------------------------------
# IdempotencyKey
# ---------------------------------------------------------------------------


@dataclass
class IdempotencyKey:
    """Canonical, serialisable idempotency key for a single inbound signal.

    All seven components are normalised at construction time (empty string for
    absent optional fields, 0 for absent seq_num).  The ``key_string`` property
    returns a deterministic, hyphen-joined representation suitable for use as a
    dict key or cache key.

    Attributes
    ----------
    contract_id
        Delegated execution contract identifier (PR-9 / PR-10).
    session_id
        Attached-runtime session identifier (PR-7).
    trace_id
        Distributed trace identifier propagated from the dispatch origin.
    task_id
        Android-side task identifier carried in the inbound signal payload.
    device_id
        Android device / runtime host identifier (PR-5 / PR-11).
    signal_kind
        Canonical signal kind string (e.g. ``"ack"``, ``"progress"``,
        ``"final_result"``).  Aligned with
        :class:`~core.android_execution_signal_reconciler.AndroidSignalKind`.
    seq_num
        Monotonically increasing sequence number from the Android peer, or
        ``0`` if the peer does not supply sequence numbers.
    """

    contract_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    task_id: str = ""
    device_id: str = ""
    signal_kind: str = ""
    seq_num: int = 0

    @property
    def key_string(self) -> str:
        """Return a deterministic string representation of this key."""
        return (
            f"{self.contract_id}|{self.session_id}|{self.trace_id}|"
            f"{self.task_id}|{self.device_id}|{self.signal_kind}|{self.seq_num}"
        )

    @property
    def prefix_string(self) -> str:
        """Return the ordering-prefix string (excludes seq_num and trace_id).

        Used for out-of-order and stale detection: two signals with the same
        prefix but different seq_num values are compared by seq_num.
        """
        return (
            f"{self.contract_id}|{self.session_id}|"
            f"{self.task_id}|{self.device_id}|{self.signal_kind}"
        )

    def has_lookup_key(self) -> bool:
        """Return True if at least one of contract_id or session_id is non-empty."""
        return bool(self.contract_id or self.session_id)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "contract_id": self.contract_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "task_id": self.task_id,
            "device_id": self.device_id,
            "signal_kind": self.signal_kind,
            "seq_num": self.seq_num,
            "key_string": self.key_string,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IdempotencyKey":
        """Construct from a dict.  Raises ValueError if *data* is not a dict."""
        if not isinstance(data, dict):
            raise ValueError("IdempotencyKey.from_dict expects a dict")
        return cls(
            contract_id=str(data.get("contract_id") or ""),
            session_id=str(data.get("session_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            task_id=str(data.get("task_id") or ""),
            device_id=str(data.get("device_id") or ""),
            signal_kind=str(data.get("signal_kind") or ""),
            seq_num=int(data.get("seq_num") or 0),
        )


# ---------------------------------------------------------------------------
# SeenSignalRecord
# ---------------------------------------------------------------------------


@dataclass
class SeenSignalRecord:
    """Lightweight record noting that an idempotency key has been processed.

    Attributes
    ----------
    idempotency_key
        The canonical idempotency key for the processed signal.
    decision
        The :class:`SignalGuardDecision` applied when the signal was first
        seen.
    first_seen_at
        Unix timestamp of first receipt.
    """

    idempotency_key: IdempotencyKey
    decision: SignalGuardDecision = SignalGuardDecision.accept
    first_seen_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "idempotency_key": self.idempotency_key.to_dict(),
            "decision": self.decision.value,
            "first_seen_at": self.first_seen_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# SignalGuardOutcome
# ---------------------------------------------------------------------------


@dataclass
class SignalGuardOutcome:
    """Typed result of a guard evaluation for an inbound signal.

    Attributes
    ----------
    decision
        The canonical :class:`SignalGuardDecision` verdict.
    idempotency_key
        The :class:`IdempotencyKey` used for this evaluation.
    is_duplicate
        Convenience flag: ``True`` when decision is ``duplicate``.
    is_out_of_order
        Convenience flag: ``True`` when decision is ``out_of_order``.
    is_replay
        Convenience flag: ``True`` when decision is ``replay``.
    is_stale
        Convenience flag: ``True`` when decision is ``stale``.
    reason
        Human-readable description of the guard decision.
    """

    decision: SignalGuardDecision
    idempotency_key: IdempotencyKey
    is_duplicate: bool = False
    is_out_of_order: bool = False
    is_replay: bool = False
    is_stale: bool = False
    reason: str = ""

    @property
    def should_forward(self) -> bool:
        """Return True if the signal should be forwarded to the reconciler."""
        return self.decision == SignalGuardDecision.accept

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "decision": self.decision.value,
            "idempotency_key": self.idempotency_key.to_dict(),
            "is_duplicate": self.is_duplicate,
            "is_out_of_order": self.is_out_of_order,
            "is_replay": self.is_replay,
            "is_stale": self.is_stale,
            "should_forward": self.should_forward,
            "reason": self.reason,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# RecoveryReadinessSnapshot
# ---------------------------------------------------------------------------


@dataclass
class RecoveryReadinessSnapshot:
    """Point-in-time summary of the recovery readiness ring-buffer state.

    Attributes
    ----------
    records
        All :class:`SeenSignalRecord` items captured at snapshot time
        (newest-first).
    total_count
        Total number of records in the ring-buffer.
    accept_count
        Number of records whose decision is ``accept``.
    duplicate_count
        Number of records whose decision is ``duplicate``.
    stale_count
        Number of records whose decision is ``stale``.
    replay_count
        Number of records whose decision is ``replay``.
    out_of_order_count
        Number of records whose decision is ``out_of_order``.
    status
        Derived :class:`RecoveryReadinessStatus` based on proportion of
        non-fresh signals in the buffer.
    snapshot_at
        Unix timestamp when this snapshot was assembled.
    """

    records: List[SeenSignalRecord] = field(default_factory=list)
    total_count: int = 0
    accept_count: int = 0
    duplicate_count: int = 0
    stale_count: int = 0
    replay_count: int = 0
    out_of_order_count: int = 0
    status: RecoveryReadinessStatus = RecoveryReadinessStatus.ready
    snapshot_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "records": [r.to_dict() for r in self.records],
            "total_count": self.total_count,
            "accept_count": self.accept_count,
            "duplicate_count": self.duplicate_count,
            "stale_count": self.stale_count,
            "replay_count": self.replay_count,
            "out_of_order_count": self.out_of_order_count,
            "status": self.status.value,
            "snapshot_at": self.snapshot_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# RecoveryReadinessRuntime  (ring-buffer singleton)
# ---------------------------------------------------------------------------


class RecoveryReadinessRuntime:
    """In-process ring-buffer accumulating seen-signal records for guard lookups.

    Backed by a ``deque`` for O(1) eviction and two ``dict`` indices for O(1)
    lookups:

    * ``_by_key``: ``{key_string: SeenSignalRecord}`` for exact idempotency
      key matches (duplicate / replay detection).
    * ``_max_seq``: ``{prefix_string: int}`` for the maximum seq_num accepted
      per (contract_id, session_id, task_id, device_id, signal_kind) prefix
      (out-of-order / stale detection).

    Parameters
    ----------
    capacity
        Maximum number of records to retain.  Defaults to 128.
    """

    def __init__(self, capacity: int = _RING_BUFFER_CAPACITY) -> None:
        self._capacity: int = capacity
        self._buffer: Deque[SeenSignalRecord] = deque()
        self._by_key: Dict[str, SeenSignalRecord] = {}
        self._max_seq: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Mutating operations
    # ------------------------------------------------------------------

    def push(self, record: SeenSignalRecord) -> None:
        """Add a :class:`SeenSignalRecord` to the ring-buffer.

        When the buffer is at capacity the oldest record is evicted first.
        If the evicted record's key_string is still present in ``_by_key``
        (i.e. no newer record has replaced it) the index entry is also removed.
        """
        if len(self._buffer) >= self._capacity:
            evicted = self._buffer.popleft()
            old_key = evicted.idempotency_key.key_string
            # Only remove the index entry if it still points to the evicted record.
            if self._by_key.get(old_key) is evicted:
                del self._by_key[old_key]

        self._buffer.append(record)
        key_str = record.idempotency_key.key_string
        self._by_key[key_str] = record

        # Update max-seq index for accepted signals only.
        if record.decision == SignalGuardDecision.accept and record.idempotency_key.seq_num > 0:
            prefix = record.idempotency_key.prefix_string
            current_max = self._max_seq.get(prefix, 0)
            if record.idempotency_key.seq_num > current_max:
                self._max_seq[prefix] = record.idempotency_key.seq_num

    def clear(self) -> None:
        """Remove all records and reset all indices."""
        self._buffer.clear()
        self._by_key.clear()
        self._max_seq.clear()

    # ------------------------------------------------------------------
    # Read-only operations
    # ------------------------------------------------------------------

    def get_by_key(self, key_string: str) -> Optional[SeenSignalRecord]:
        """Return the most recent :class:`SeenSignalRecord` for *key_string*, or None."""
        return self._by_key.get(key_string)

    def get_max_seq(self, prefix_string: str) -> int:
        """Return the maximum accepted seq_num for *prefix_string*, or 0."""
        return self._max_seq.get(prefix_string, 0)

    def list_all(self) -> List[SeenSignalRecord]:
        """Return all records in newest-first order."""
        return list(reversed(self._buffer))

    def size(self) -> int:
        """Return the current number of records in the buffer."""
        return len(self._buffer)

    @property
    def capacity(self) -> int:
        """Return the maximum capacity of this ring-buffer."""
        return self._capacity


# ---------------------------------------------------------------------------
# Process-singleton management
# ---------------------------------------------------------------------------

_SINGLETON_RUNTIME: Optional[RecoveryReadinessRuntime] = None


def get_recovery_readiness_runtime() -> RecoveryReadinessRuntime:
    """Return the process-singleton :class:`RecoveryReadinessRuntime`."""
    global _SINGLETON_RUNTIME
    if _SINGLETON_RUNTIME is None:
        _SINGLETON_RUNTIME = RecoveryReadinessRuntime()
    return _SINGLETON_RUNTIME


def reset_recovery_readiness_runtime() -> None:
    """Replace the singleton with a fresh instance (test isolation helper)."""
    global _SINGLETON_RUNTIME
    _SINGLETON_RUNTIME = RecoveryReadinessRuntime()


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def build_idempotency_key(
    *,
    contract_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    task_id: str = "",
    device_id: str = "",
    signal_kind: str = "",
    seq_num: int = 0,
) -> IdempotencyKey:
    """Build a canonical :class:`IdempotencyKey` from raw signal fields.

    All fields are normalised: ``None`` values are coerced to ``""``; ``seq_num``
    defaults to 0 when absent or None.

    Parameters
    ----------
    contract_id, session_id, trace_id, task_id, device_id, signal_kind
        Identity fields from the inbound signal envelope.  Empty string is used
        for absent / None values.
    seq_num
        Monotonic sequence number from the Android peer.  Defaults to 0.

    Returns
    -------
    IdempotencyKey
        Normalised, canonical idempotency key.
    """
    return IdempotencyKey(
        contract_id=str(contract_id or ""),
        session_id=str(session_id or ""),
        trace_id=str(trace_id or ""),
        task_id=str(task_id or ""),
        device_id=str(device_id or ""),
        signal_kind=str(signal_kind or ""),
        seq_num=int(seq_num) if seq_num is not None else 0,
    )


def check_signal_guard(
    idempotency_key: IdempotencyKey,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SignalGuardOutcome:
    """Evaluate the guard status for an inbound signal without mutating state.

    Evaluation order
    ----------------
    1. **Exact duplicate** — if the ring-buffer contains a record with the
       exact same ``key_string`` (all seven fields equal), return
       ``SignalGuardDecision.duplicate`` if the prior decision was not ``accept``,
       or ``SignalGuardDecision.replay`` if the prior decision was ``accept``.
    2. **Out-of-order / stale by seq_num** — if ``seq_num > 0`` and the
       maximum accepted seq_num for the ``prefix_string`` exceeds the incoming
       ``seq_num``, return ``SignalGuardDecision.out_of_order``.  If the
       incoming ``seq_num`` equals the maximum and a prior accepted record
       exists with a different trace_id but the same seq_num (i.e. a different
       instance of the same sequence position), return ``duplicate``.
    3. **Stale** — same as out-of-order but specifically when ``seq_num < max_seen``
       (covered by step 2; ``out_of_order`` is the canonical classification).
    4. **Fresh** — no prior record matches; return ``SignalGuardDecision.accept``.

    Parameters
    ----------
    idempotency_key
        The :class:`IdempotencyKey` to check.
    runtime
        Optional ring-buffer instance for test isolation.  Uses the process
        singleton if None.

    Returns
    -------
    SignalGuardOutcome
        Guard result.  Does not mutate the ring-buffer.
    """
    _runtime = runtime if runtime is not None else get_recovery_readiness_runtime()

    key_str = idempotency_key.key_string
    prior = _runtime.get_by_key(key_str)

    if prior is not None:
        # Exact key match.
        if prior.decision == SignalGuardDecision.accept:
            return SignalGuardOutcome(
                decision=SignalGuardDecision.replay,
                idempotency_key=idempotency_key,
                is_replay=True,
                reason=(
                    f"idempotency key '{key_str}' was previously accepted; "
                    "re-submission classified as replay"
                ),
            )
        # Prior was itself a non-accept (duplicate / stale / replay / out_of_order):
        # re-classifying as duplicate is the safest conservative outcome.
        return SignalGuardOutcome(
            decision=SignalGuardDecision.duplicate,
            idempotency_key=idempotency_key,
            is_duplicate=True,
            reason=(
                f"idempotency key '{key_str}' was previously seen "
                f"(prior decision: {prior.decision.value}); classified as duplicate"
            ),
        )

    # No exact match — check sequence ordering.
    if idempotency_key.seq_num > 0:
        prefix = idempotency_key.prefix_string
        max_seen = _runtime.get_max_seq(prefix)
        if max_seen > 0 and idempotency_key.seq_num < max_seen:
            return SignalGuardOutcome(
                decision=SignalGuardDecision.out_of_order,
                idempotency_key=idempotency_key,
                is_out_of_order=True,
                reason=(
                    f"seq_num={idempotency_key.seq_num} is lower than the "
                    f"highest accepted seq_num={max_seen} for prefix "
                    f"'{prefix}'; classified as out_of_order"
                ),
            )

    # Fresh signal.
    return SignalGuardOutcome(
        decision=SignalGuardDecision.accept,
        idempotency_key=idempotency_key,
        reason="signal is fresh; no prior record for this idempotency key",
    )


def record_seen_signal(
    idempotency_key: IdempotencyKey,
    decision: SignalGuardDecision,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SeenSignalRecord:
    """Record that an idempotency key has been processed with *decision*.

    Mutates the ring-buffer.

    Parameters
    ----------
    idempotency_key
        The :class:`IdempotencyKey` to record.
    decision
        The :class:`SignalGuardDecision` applied to the signal.
    runtime
        Optional ring-buffer instance for test isolation.

    Returns
    -------
    SeenSignalRecord
        The newly created record that was pushed to the ring-buffer.
    """
    _runtime = runtime if runtime is not None else get_recovery_readiness_runtime()
    seen = SeenSignalRecord(
        idempotency_key=idempotency_key,
        decision=decision,
    )
    _runtime.push(seen)
    return seen


def guard_inbound_signal(
    *,
    contract_id: str = "",
    session_id: str = "",
    trace_id: str = "",
    task_id: str = "",
    device_id: str = "",
    signal_kind: str = "",
    seq_num: int = 0,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SignalGuardOutcome:
    """Canonical entry-point: build key, evaluate guard, record if accepted.

    This is the single call site that gateway handlers and reconciliation
    code should use before forwarding an inbound Android execution signal.

    Steps
    -----
    1. Build :class:`IdempotencyKey` from the supplied fields via
       :func:`build_idempotency_key`.
    2. Evaluate guard status via :func:`check_signal_guard` (read-only).
    3. Record the signal in the ring-buffer via :func:`record_seen_signal`
       **only when the decision is** ``accept``.  Non-fresh signals are not
       recorded again (their prior record already captures them).
    4. Return the :class:`SignalGuardOutcome`.

    Parameters
    ----------
    contract_id, session_id, trace_id, task_id, device_id, signal_kind
        Identity fields from the inbound signal envelope.
    seq_num
        Monotonic sequence number from the Android peer.  0 if absent.
    runtime
        Optional ring-buffer instance for test isolation.

    Returns
    -------
    SignalGuardOutcome
        Guard result.
    """
    _runtime = runtime if runtime is not None else get_recovery_readiness_runtime()
    key = build_idempotency_key(
        contract_id=contract_id,
        session_id=session_id,
        trace_id=trace_id,
        task_id=task_id,
        device_id=device_id,
        signal_kind=signal_kind,
        seq_num=seq_num,
    )
    outcome = check_signal_guard(key, runtime=_runtime)
    if outcome.decision == SignalGuardDecision.accept:
        record_seen_signal(key, SignalGuardDecision.accept, runtime=_runtime)
    return outcome


def build_recovery_readiness_snapshot(
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> RecoveryReadinessSnapshot:
    """Assemble a :class:`RecoveryReadinessSnapshot` from the ring-buffer state.

    Counts are computed from the full contents of the ring-buffer; the
    :class:`RecoveryReadinessStatus` is derived from the ratio of non-fresh
    signals:

    * ``ready`` — no non-fresh signals in the buffer.
    * ``recovering`` — 1–29 % of signals are non-fresh.
    * ``degraded`` — 30 %+ of signals are non-fresh.

    Parameters
    ----------
    runtime
        Optional ring-buffer instance for test isolation.

    Returns
    -------
    RecoveryReadinessSnapshot
        Point-in-time snapshot.
    """
    _runtime = runtime if runtime is not None else get_recovery_readiness_runtime()
    records = _runtime.list_all()

    accept_count = 0
    duplicate_count = 0
    stale_count = 0
    replay_count = 0
    out_of_order_count = 0

    for r in records:
        if r.decision == SignalGuardDecision.accept:
            accept_count += 1
        elif r.decision == SignalGuardDecision.duplicate:
            duplicate_count += 1
        elif r.decision == SignalGuardDecision.stale:
            stale_count += 1
        elif r.decision == SignalGuardDecision.replay:
            replay_count += 1
        elif r.decision == SignalGuardDecision.out_of_order:
            out_of_order_count += 1

    total = len(records)
    non_fresh = duplicate_count + stale_count + replay_count + out_of_order_count

    if total == 0 or non_fresh == 0:
        status = RecoveryReadinessStatus.ready
    elif non_fresh / total >= 0.30:
        status = RecoveryReadinessStatus.degraded
    else:
        status = RecoveryReadinessStatus.recovering

    return RecoveryReadinessSnapshot(
        records=records,
        total_count=total,
        accept_count=accept_count,
        duplicate_count=duplicate_count,
        stale_count=stale_count,
        replay_count=replay_count,
        out_of_order_count=out_of_order_count,
        status=status,
    )
