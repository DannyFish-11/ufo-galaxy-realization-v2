"""core/attached_runtime_recovery_readiness.py
==============================================
PR package 15 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Attached-Runtime Recovery Readiness and Inbound Signal Guard.

Background
----------
After PR-13 established host-side Android execution signal reconciliation and
PR-14 established persistent reuse binding, the host can track delegated
execution through its lifecycle and reuse stable attached-runtime surfaces.
However, inbound signals arriving from Android may be:

* **Duplicates** — the exact same signal (same ``signal_id``) received more
  than once due to retransmission or network quirks.
* **Replays** — a signal re-emitted at the same ``emission_seq`` position as a
  previously reconciled signal but with a different ``signal_id`` (re-emission
  after an acknowledged loss).
* **Stale** — a signal with an ``emission_seq`` far behind the maximum already
  seen for the same execution context (contract/session), indicating a delayed
  delivery from a long-ago emission point.
* **Out-of-order** — a signal with an ``emission_seq`` slightly behind the
  maximum already seen, indicating mild reordering during transit.

Without a guard layer these signals reach
:func:`~core.android_execution_signal_reconciler.reconcile_android_execution_signal`
and can pollute the host-side execution-tracking record with spurious phase
transitions, corrupt ``ack_count``, or reset already-terminal records.

This module provides the **canonical guard layer** that MUST be consulted
before reconciliation for every inbound Android delegated execution signal.
It:

1. Derives an :class:`IdempotencyKey` from the signal envelope's identity
   fields (``signal_id``, ``contract_id``, ``session_id``).
2. Checks the key against a 128-entry ring-buffer of recently seen signals
   (:class:`RecoveryReadinessRuntime`) to detect duplicate, replay, stale,
   and out-of-order arrivals.
3. Returns a :class:`SignalGuardOutcome` carrying the guard
   :class:`SignalGuardDecision` and enough context for callers to log,
   project, or debug each rejected signal.
4. Records newly accepted signals into the ring buffer so subsequent signals
   can be evaluated against the updated history.

Guard decision table
--------------------
+--------------+-----------------------------------------------------------+
| Decision     | Condition                                                 |
+==============+===========================================================+
| accept       | signal_id not seen before AND emission_seq >= max_seen    |
|              | (or no prior context exists for this contract/session).   |
+--------------+-----------------------------------------------------------+
| duplicate    | Exact signal_id match already present in the ring buffer. |
+--------------+-----------------------------------------------------------+
| replay       | emission_seq == max_seen for this context but a different |
|              | signal_id (same seq position re-emitted with new id).     |
+--------------+-----------------------------------------------------------+
| stale        | emission_seq < (max_seen − STALE_THRESHOLD).  Far behind  |
|              | the leading edge; considered unreliable for reconcile.    |
+--------------+-----------------------------------------------------------+
| out_of_order | emission_seq < max_seen but not stale (mild reordering).  |
+--------------+-----------------------------------------------------------+

Public API summary
------------------
Enums::

    SignalGuardDecision   — accept / duplicate / replay / stale / out_of_order
    RecoveryReadinessStatus — ready / recovering / degraded

Dataclasses::

    IdempotencyKey           — (signal_id, contract_id, session_id)
    SeenSignalRecord         — ring-buffer entry for a seen signal
    SignalGuardOutcome       — result of guard_inbound_signal()
    RecoveryReadinessSnapshot — point-in-time view of the runtime state

Class::

    RecoveryReadinessRuntime — 128-entry ring buffer with key and seq indices

Functions::

    build_idempotency_key(signal_id, contract_id, session_id) -> IdempotencyKey
    check_signal_guard(key, emission_seq, *, runtime=None) -> SignalGuardDecision
    record_seen_signal(key, emission_seq, *, runtime=None) -> SeenSignalRecord
    guard_inbound_signal(envelope, *, runtime=None) -> SignalGuardOutcome
    build_recovery_readiness_snapshot(*, runtime=None) -> RecoveryReadinessSnapshot
    get_recovery_readiness_runtime() -> RecoveryReadinessRuntime
    reset_recovery_readiness_runtime() -> RecoveryReadinessRuntime

Eleven policy sentinels documenting canonical guard rules.

One PR sentinel (``ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL``).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Guard before reconcile** — callers MUST consult guard_inbound_signal()
  before calling reconcile_android_execution_signal().
- **Non-destructive on reject** — rejected signals are never forwarded to the
  reconciler; the host-side tracker is never mutated for rejected signals.
- **Ring-buffer bounded** — the seen-signal store is capped at 128 entries
  (FIFO eviction) so memory usage is deterministic.
- **Observable** — every SignalGuardOutcome carries the guard decision, reason,
  and idempotency key so callers can log or project any decision.
- **Isolated per runtime** — all functions accept an optional ``runtime``
  parameter for test isolation; the process singleton is used when None.

PR package numbering
--------------------
Package 15 of the post-533 dual-repo runtime unification master plan.
MAIN-repo side only.  Android-repo side signal generation is unchanged.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Module authority marker
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY: str = (
    "core.attached_runtime_recovery_readiness::PR15::recovery-readiness-"
    "and-inbound-signal-guard"
)

# ---------------------------------------------------------------------------
# Policy sentinels — document canonical guard rules
# ---------------------------------------------------------------------------

GUARD_MUST_PRECEDE_RECONCILE_POLICY: str = (
    "RECOVERY_READINESS_POLICY::GUARD_MUST_PRECEDE_RECONCILE: "
    "guard_inbound_signal() MUST be called and must return SignalGuardDecision.accept "
    "before reconcile_android_execution_signal() is invoked.  Signals with any "
    "other decision MUST NOT reach the reconciler."
)

DUPLICATE_SIGNAL_ID_IS_REJECTED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::DUPLICATE_SIGNAL_ID_IS_REJECTED: "
    "A signal whose signal_id exactly matches any signal_id already present in "
    "the RecoveryReadinessRuntime ring buffer MUST be classified as 'duplicate' "
    "and silently dropped.  The tracker MUST NOT be updated."
)

REPLAY_AT_SAME_SEQ_IS_REJECTED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::REPLAY_AT_SAME_SEQ_IS_REJECTED: "
    "A signal whose emission_seq equals the maximum emission_seq already seen "
    "for the same contract/session context but carries a different signal_id MUST "
    "be classified as 'replay' and silently dropped.  The tracker MUST NOT be "
    "updated."
)

STALE_EMISSION_SEQ_IS_REJECTED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::STALE_EMISSION_SEQ_IS_REJECTED: "
    "A signal whose emission_seq is more than STALE_EMISSION_SEQ_THRESHOLD "
    "positions behind the maximum emission_seq already seen for the same "
    "contract/session context MUST be classified as 'stale' and silently "
    "dropped.  The tracker MUST NOT be updated."
)

OUT_OF_ORDER_EMISSION_SEQ_IS_REJECTED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::OUT_OF_ORDER_EMISSION_SEQ_IS_REJECTED: "
    "A signal whose emission_seq is less than the maximum emission_seq already "
    "seen for the same contract/session context (but not stale) MUST be "
    "classified as 'out_of_order' and silently dropped.  The tracker MUST NOT "
    "be updated."
)

ACCEPTED_SIGNAL_IS_RECORDED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::ACCEPTED_SIGNAL_IS_RECORDED: "
    "After guard_inbound_signal() returns SignalGuardDecision.accept the caller "
    "MUST treat the signal as the new maximum emission_seq for the "
    "contract/session context.  The guard internally records the signal into "
    "the ring buffer before returning the outcome."
)

GUARD_DECISION_IS_OBSERVABLE_POLICY: str = (
    "RECOVERY_READINESS_POLICY::GUARD_DECISION_IS_OBSERVABLE: "
    "Every SignalGuardOutcome carries the guard decision, idempotency_key, "
    "reject_reason, and a timestamp so callers can log, project, or surface "
    "the decision in a debug/operator view."
)

RING_BUFFER_IS_BOUNDED_POLICY: str = (
    "RECOVERY_READINESS_POLICY::RING_BUFFER_IS_BOUNDED: "
    "The RecoveryReadinessRuntime ring buffer MUST be capped at "
    "RECOVERY_READINESS_RING_BUFFER_SIZE (128) entries.  FIFO eviction applies "
    "when the buffer is full.  The key index and seq index are pruned on eviction."
)

IDEMPOTENCY_KEY_USES_SIGNAL_ID_AND_CONTEXT_POLICY: str = (
    "RECOVERY_READINESS_POLICY::IDEMPOTENCY_KEY_USES_SIGNAL_ID_AND_CONTEXT: "
    "An IdempotencyKey is derived from (signal_id, contract_id, session_id).  "
    "Both contract_id and session_id may be empty; at least one non-empty "
    "context field is preferred but not required."
)

SEQ_INDEX_TRACKS_MAX_PER_CONTEXT_POLICY: str = (
    "RECOVERY_READINESS_POLICY::SEQ_INDEX_TRACKS_MAX_PER_CONTEXT: "
    "The RecoveryReadinessRuntime maintains a mapping from context_key "
    "(contract_id or session_id) to the maximum emission_seq seen so that "
    "out-of-order and stale detection do not require scanning the full ring buffer."
)

REJECTED_SIGNAL_MUST_NOT_REACH_TRACKER_POLICY: str = (
    "RECOVERY_READINESS_POLICY::REJECTED_SIGNAL_MUST_NOT_REACH_TRACKER: "
    "A signal classified as duplicate, replay, stale, or out_of_order by "
    "guard_inbound_signal() MUST NOT be forwarded to the delegated-runtime "
    "execution tracker.  Callers are responsible for returning a no-update "
    "outcome rather than calling reconcile_android_execution_signal()."
)

_ALL_RECOVERY_READINESS_POLICIES = (
    GUARD_MUST_PRECEDE_RECONCILE_POLICY,
    DUPLICATE_SIGNAL_ID_IS_REJECTED_POLICY,
    REPLAY_AT_SAME_SEQ_IS_REJECTED_POLICY,
    STALE_EMISSION_SEQ_IS_REJECTED_POLICY,
    OUT_OF_ORDER_EMISSION_SEQ_IS_REJECTED_POLICY,
    ACCEPTED_SIGNAL_IS_RECORDED_POLICY,
    GUARD_DECISION_IS_OBSERVABLE_POLICY,
    RING_BUFFER_IS_BOUNDED_POLICY,
    IDEMPOTENCY_KEY_USES_SIGNAL_ID_AND_CONTEXT_POLICY,
    SEQ_INDEX_TRACKS_MAX_PER_CONTEXT_POLICY,
    REJECTED_SIGNAL_MUST_NOT_REACH_TRACKER_POLICY,
)

# ---------------------------------------------------------------------------
# PR sentinel
# ---------------------------------------------------------------------------

ATTACHED_RUNTIME_RECOVERY_READINESS_PR15_SENTINEL: str = (
    "attached_runtime_recovery_readiness::package=15::pr=post533-pr15-main::"
    "recovery-readiness-and-inbound-signal-guard::"
    "authority=ATTACHED_RUNTIME_RECOVERY_READINESS_AUTHORITY"
)

# ---------------------------------------------------------------------------
# PR-33: Reconnect and Recovery Consistency sentinel
# ---------------------------------------------------------------------------

RECOVERY_READINESS_RECONNECT_CONSISTENCY_PR33_SENTINEL: str = (
    "attached_runtime_recovery_readiness::package=33::pr=post533-pr33-main::"
    "reconnect-recovery-consistency-hardening::"
    "clear-seq-context-for-reconnect::post-reconnect-signals-accepted"
)

RECOVERY_GUARD_CLEARS_SEQ_ON_RECONNECT_PR33_POLICY: str = (
    "RECOVERY_READINESS_POLICY::RECOVERY_GUARD_CLEARS_SEQ_ON_RECONNECT_PR33: "
    "When a session or contract context reconnects, the seq_index entry for that "
    "context MUST be cleared via clear_seq_context_for_reconnect() before the first "
    "post-reconnect signal is processed.  This prevents post-reconnect signals from "
    "being misclassified as stale or out-of-order relative to pre-disconnect signals.  "
    "The ring buffer of seen signal_ids is NOT cleared; duplicate protection remains "
    "active across reconnects."
)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

RECOVERY_READINESS_RING_BUFFER_SIZE: int = 128
"""Maximum number of seen-signal entries retained in the ring buffer."""

STALE_EMISSION_SEQ_THRESHOLD: int = 10
"""An ``emission_seq`` more than this many positions behind the context
maximum is classified as ``stale`` rather than ``out_of_order``."""

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SignalGuardDecision(str, Enum):
    """Canonical decision returned by :func:`guard_inbound_signal`.

    Values
    ------
    accept
        Signal is new and in sequence; forward to reconciliation.
    duplicate
        ``signal_id`` already seen; drop silently.
    replay
        ``emission_seq`` matches the context maximum but ``signal_id``
        differs; treat as a re-emission at the same seq position and drop.
    stale
        ``emission_seq`` is far behind the context maximum; drop silently.
    out_of_order
        ``emission_seq`` is slightly behind the context maximum; drop silently.
    """

    accept = "accept"
    duplicate = "duplicate"
    replay = "replay"
    stale = "stale"
    out_of_order = "out_of_order"

    @classmethod
    def from_string(cls, value: Any, *, default: "SignalGuardDecision" = None) -> "SignalGuardDecision":
        """Parse a ``SignalGuardDecision`` from a string (case-insensitive).

        Returns *default* when the value cannot be parsed.  If *default* is
        None, returns :attr:`accept`.
        """
        if default is None:
            default = cls.accept
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower())
        except ValueError:
            return default

    def is_rejected(self) -> bool:
        """Return True iff this decision means the signal should be dropped."""
        return self is not SignalGuardDecision.accept


class RecoveryReadinessStatus(str, Enum):
    """Overall recovery readiness status of the runtime.

    Values
    ------
    ready
        Guard layer is active and no anomalies detected.
    recovering
        Some signals were rejected; recovery in progress.
    degraded
        High rejection rate or significant anomalies detected.
    """

    ready = "ready"
    recovering = "recovering"
    degraded = "degraded"

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyKey:
    """Canonical idempotency key derived from an inbound signal envelope.

    Attributes
    ----------
    signal_id
        The UUID assigned by Android to this specific emission.  May be empty
        when Android omits the field.
    contract_id
        Handoff contract identifier.  May be empty.
    session_id
        Attached runtime session identifier.  May be empty.
    context_key
        Derived canonical key for seq-index lookups, computed from
        ``contract_id`` if non-empty, else ``session_id``.  Empty when both
        are absent.
    """

    signal_id: str = ""
    contract_id: str = ""
    session_id: str = ""
    context_key: str = field(default="", init=False)

    def __post_init__(self) -> None:
        # Compute context_key deterministically without mutating the frozen
        # dataclass — use object.__setattr__ since the class is frozen.
        ck = self.contract_id if self.contract_id else self.session_id
        object.__setattr__(self, "context_key", ck)

    def has_context(self) -> bool:
        """Return True iff at least one of contract_id or session_id is set."""
        return bool(self.contract_id or self.session_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "contract_id": self.contract_id,
            "session_id": self.session_id,
            "context_key": self.context_key,
        }


@dataclass
class SeenSignalRecord:
    """Ring-buffer entry representing a previously seen (accepted) signal.

    Attributes
    ----------
    idempotency_key
        The :class:`IdempotencyKey` for the recorded signal.
    emission_seq
        The ``emission_seq`` of the recorded signal.
    seen_at
        Unix timestamp (float) when the signal was recorded.
    record_id
        Auto-generated UUID for this record (audit / correlation).
    """

    idempotency_key: IdempotencyKey
    emission_seq: int = 0
    seen_at: float = field(default_factory=time.time)
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "idempotency_key": self.idempotency_key.to_dict(),
            "emission_seq": self.emission_seq,
            "seen_at": self.seen_at,
        }


@dataclass(frozen=True)
class SignalGuardOutcome:
    """Result of a single :func:`guard_inbound_signal` call.

    Attributes
    ----------
    decision
        The :class:`SignalGuardDecision` for this signal.
    idempotency_key
        The :class:`IdempotencyKey` evaluated by the guard.
    emission_seq
        The ``emission_seq`` of the evaluated signal.
    reject_reason
        Human-readable reason when ``decision != accept``.  Empty for accepted
        signals.
    max_seen_seq
        The maximum ``emission_seq`` already seen for this signal's context
        at the time of evaluation.  -1 when no prior context exists.
    evaluated_at
        Unix timestamp when the guard evaluation was performed.
    outcome_id
        Auto-generated UUID for this outcome (audit / correlation).
    """

    decision: SignalGuardDecision = SignalGuardDecision.accept
    idempotency_key: IdempotencyKey = field(default_factory=IdempotencyKey)
    emission_seq: int = 0
    reject_reason: str = ""
    max_seen_seq: int = -1
    evaluated_at: float = field(default_factory=time.time)
    outcome_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def is_accepted(self) -> bool:
        """Return True iff the decision is :attr:`~SignalGuardDecision.accept`."""
        return self.decision is SignalGuardDecision.accept

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome_id": self.outcome_id,
            "decision": self.decision.value,
            "idempotency_key": self.idempotency_key.to_dict(),
            "emission_seq": self.emission_seq,
            "reject_reason": self.reject_reason,
            "max_seen_seq": self.max_seen_seq,
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class RecoveryReadinessSnapshot:
    """Point-in-time view of the :class:`RecoveryReadinessRuntime` state.

    Attributes
    ----------
    status
        Overall :class:`RecoveryReadinessStatus`.
    ring_buffer_size
        Current number of entries in the ring buffer.
    total_accepted
        Total signals accepted since last reset.
    total_rejected
        Total signals rejected (any non-accept decision) since last reset.
    reject_counts
        Per-decision rejection counts.
    snapshot_id
        Auto-generated UUID for this snapshot.
    taken_at
        Unix timestamp when the snapshot was taken.
    """

    status: RecoveryReadinessStatus = RecoveryReadinessStatus.ready
    ring_buffer_size: int = 0
    total_accepted: int = 0
    total_rejected: int = 0
    reject_counts: Dict[str, int] = field(default_factory=dict)
    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    taken_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "status": self.status.value,
            "ring_buffer_size": self.ring_buffer_size,
            "total_accepted": self.total_accepted,
            "total_rejected": self.total_rejected,
            "reject_counts": dict(self.reject_counts),
            "taken_at": self.taken_at,
        }


# ---------------------------------------------------------------------------
# RecoveryReadinessRuntime (ring buffer)
# ---------------------------------------------------------------------------


class RecoveryReadinessRuntime:
    """In-memory ring-buffer runtime for inbound signal guard state.

    Maintains:
    * A FIFO ring buffer of up to
      :data:`RECOVERY_READINESS_RING_BUFFER_SIZE` (128) recently accepted
      :class:`SeenSignalRecord` entries.
    * A ``signal_id`` index for O(1) duplicate detection.
    * A ``context_key → max_emission_seq`` index for O(1) seq comparisons.
    * Rejection counters for observability.
    """

    def __init__(self, max_size: int = RECOVERY_READINESS_RING_BUFFER_SIZE) -> None:
        self._max_size = max_size
        self._ring: List[SeenSignalRecord] = []
        # signal_id → ring index (logical, not physical; we store the record itself)
        self._signal_id_index: Dict[str, SeenSignalRecord] = {}
        # context_key → (max_emission_seq, signal_id at max)
        self._seq_index: Dict[str, Tuple[int, str]] = {}
        # counters
        self._total_accepted: int = 0
        self._total_rejected: int = 0
        self._reject_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evict_oldest(self) -> None:
        """Remove the oldest entry from the ring buffer and clean up indices."""
        if not self._ring:
            return
        oldest = self._ring.pop(0)
        # Remove from signal_id index if still referencing this record
        sid = oldest.idempotency_key.signal_id
        if sid and self._signal_id_index.get(sid) is oldest:
            del self._signal_id_index[sid]
        # Note: we do NOT remove from _seq_index because the max_seq value
        # may still be valid (we don't want to lose the max on eviction).

    # ------------------------------------------------------------------
    # Lookup methods
    # ------------------------------------------------------------------

    def has_signal_id(self, signal_id: str) -> bool:
        """Return True iff *signal_id* is in the current ring buffer."""
        if not signal_id:
            return False
        return signal_id in self._signal_id_index

    def get_max_seq(self, context_key: str) -> int:
        """Return the maximum ``emission_seq`` seen for *context_key*, or -1."""
        if not context_key:
            return -1
        entry = self._seq_index.get(context_key)
        if entry is None:
            return -1
        return entry[0]

    def get_max_seq_signal_id(self, context_key: str) -> str:
        """Return the ``signal_id`` associated with the max seq for *context_key*."""
        entry = self._seq_index.get(context_key)
        if entry is None:
            return ""
        return entry[1]

    # ------------------------------------------------------------------
    # Mutation methods
    # ------------------------------------------------------------------

    def record(self, seen: SeenSignalRecord) -> None:
        """Add a :class:`SeenSignalRecord` to the ring buffer.

        Evicts the oldest entry when the buffer is full.  Updates the
        ``signal_id`` index and the ``context_key → max_seq`` index.
        """
        if len(self._ring) >= self._max_size:
            self._evict_oldest()

        self._ring.append(seen)
        sid = seen.idempotency_key.signal_id
        if sid:
            self._signal_id_index[sid] = seen

        ck = seen.idempotency_key.context_key
        if ck:
            current = self._seq_index.get(ck)
            if current is None or seen.emission_seq >= current[0]:
                self._seq_index[ck] = (seen.emission_seq, sid)

        self._total_accepted += 1

    def record_rejection(self, decision: SignalGuardDecision) -> None:
        """Increment rejection counters for *decision*."""
        self._total_rejected += 1
        self._reject_counts[decision.value] = (
            self._reject_counts.get(decision.value, 0) + 1
        )

    def clear_seq_context(self, context_key: str) -> None:
        """Remove the seq_index entry for *context_key*.

        MUST be called after a session reconnect so that the first
        post-reconnect signal is not misclassified as stale or out-of-order
        relative to pre-disconnect signals.  The ``signal_id`` ring buffer
        is intentionally preserved to maintain duplicate protection.

        Parameters
        ----------
        context_key:
            The context key whose maximum-sequence entry should be cleared.
            Typically derived from ``contract_id`` or ``session_id``.
        """
        self._seq_index.pop(context_key, None)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def build_snapshot(self) -> RecoveryReadinessSnapshot:
        """Return a :class:`RecoveryReadinessSnapshot` of the current state."""
        total = self._total_accepted + self._total_rejected
        if total == 0:
            status = RecoveryReadinessStatus.ready
        elif self._total_rejected == 0:
            status = RecoveryReadinessStatus.ready
        elif self._total_rejected / max(total, 1) > 0.5:
            status = RecoveryReadinessStatus.degraded
        else:
            status = RecoveryReadinessStatus.recovering

        return RecoveryReadinessSnapshot(
            status=status,
            ring_buffer_size=len(self._ring),
            total_accepted=self._total_accepted,
            total_rejected=self._total_rejected,
            reject_counts=dict(self._reject_counts),
        )

    def reset(self) -> None:
        """Clear all state (used for testing)."""
        self._ring.clear()
        self._signal_id_index.clear()
        self._seq_index.clear()
        self._total_accepted = 0
        self._total_rejected = 0
        self._reject_counts.clear()


# ---------------------------------------------------------------------------
# Process singleton
# ---------------------------------------------------------------------------

_RECOVERY_READINESS_RUNTIME: Optional[RecoveryReadinessRuntime] = None


def get_recovery_readiness_runtime() -> RecoveryReadinessRuntime:
    """Return the process-level :class:`RecoveryReadinessRuntime` singleton."""
    global _RECOVERY_READINESS_RUNTIME
    if _RECOVERY_READINESS_RUNTIME is None:
        _RECOVERY_READINESS_RUNTIME = RecoveryReadinessRuntime()
    return _RECOVERY_READINESS_RUNTIME


def reset_recovery_readiness_runtime() -> RecoveryReadinessRuntime:
    """Reset and return the process-level :class:`RecoveryReadinessRuntime`.

    Use in tests to ensure a clean state between test cases.
    """
    global _RECOVERY_READINESS_RUNTIME
    _RECOVERY_READINESS_RUNTIME = RecoveryReadinessRuntime()
    return _RECOVERY_READINESS_RUNTIME


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def build_idempotency_key(
    signal_id: str = "",
    contract_id: str = "",
    session_id: str = "",
) -> IdempotencyKey:
    """Construct an :class:`IdempotencyKey` from raw string fields.

    Parameters
    ----------
    signal_id:
        The ``signal_id`` from the inbound signal envelope.  May be empty.
    contract_id:
        The ``contract_id`` from the inbound signal envelope.  May be empty.
    session_id:
        The ``session_id`` from the inbound signal envelope.  May be empty.

    Returns
    -------
    IdempotencyKey
    """
    return IdempotencyKey(
        signal_id=str(signal_id) if signal_id else "",
        contract_id=str(contract_id) if contract_id else "",
        session_id=str(session_id) if session_id else "",
    )


def check_signal_guard(
    key: IdempotencyKey,
    emission_seq: int,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SignalGuardDecision:
    """Evaluate the guard decision for an inbound signal WITHOUT recording it.

    This is the pure evaluation path.  It does not mutate the runtime.
    Callers that want to both evaluate AND record (i.e. the normal path)
    should use :func:`guard_inbound_signal` instead.

    Guard decision logic (in priority order):

    1. ``duplicate`` — ``signal_id`` already present in the ring buffer.
    2. ``replay``    — ``emission_seq == max_seen`` for this context AND
                       the signal_id differs from the one at max_seen.
    3. ``stale``     — ``emission_seq < (max_seen − STALE_EMISSION_SEQ_THRESHOLD)``.
    4. ``out_of_order`` — ``emission_seq < max_seen`` (but not stale).
    5. ``accept``    — all other cases.

    Parameters
    ----------
    key:
        The :class:`IdempotencyKey` for the candidate signal.
    emission_seq:
        The ``emission_seq`` of the candidate signal.
    runtime:
        Optional :class:`RecoveryReadinessRuntime` for test isolation.

    Returns
    -------
    SignalGuardDecision
    """
    rt = runtime if runtime is not None else get_recovery_readiness_runtime()

    # 1. Duplicate: exact signal_id match
    if key.signal_id and rt.has_signal_id(key.signal_id):
        return SignalGuardDecision.duplicate

    # 2–4: sequence-based checks require a valid context key
    if key.has_context():
        max_seq = rt.get_max_seq(key.context_key)
        if max_seq >= 0:  # prior context exists
            max_seq_signal_id = rt.get_max_seq_signal_id(key.context_key)

            # 2. Replay: same seq position, different signal_id
            if emission_seq == max_seq and key.signal_id != max_seq_signal_id:
                return SignalGuardDecision.replay

            # 3. Stale: far behind the leading edge
            if emission_seq < max_seq - STALE_EMISSION_SEQ_THRESHOLD:
                return SignalGuardDecision.stale

            # 4. Out-of-order: slightly behind
            if emission_seq < max_seq:
                return SignalGuardDecision.out_of_order

    # 5. Accept
    return SignalGuardDecision.accept


def record_seen_signal(
    key: IdempotencyKey,
    emission_seq: int,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SeenSignalRecord:
    """Record an accepted signal into the ring buffer and return the entry.

    This function MUST only be called when the guard decision is ``accept``.
    Calling it for rejected signals would corrupt the seq index.

    Parameters
    ----------
    key:
        The :class:`IdempotencyKey` for the accepted signal.
    emission_seq:
        The ``emission_seq`` of the accepted signal.
    runtime:
        Optional :class:`RecoveryReadinessRuntime` for test isolation.

    Returns
    -------
    SeenSignalRecord
    """
    rt = runtime if runtime is not None else get_recovery_readiness_runtime()
    seen = SeenSignalRecord(idempotency_key=key, emission_seq=emission_seq)
    rt.record(seen)
    return seen


def guard_inbound_signal(
    envelope: Any,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> SignalGuardOutcome:
    """Evaluate and record the guard decision for an inbound signal envelope.

    This is the **canonical entry-point** that callers MUST invoke before
    calling :func:`~core.android_execution_signal_reconciler.reconcile_android_execution_signal`.

    It:

    1. Extracts ``signal_id``, ``contract_id``, ``session_id``, and
       ``emission_seq`` from *envelope* (supports both
       :class:`~core.android_delegated_signal_ingress.DelegatedExecutionSignalEnvelope`
       and plain dicts).
    2. Builds an :class:`IdempotencyKey`.
    3. Calls :func:`check_signal_guard` to determine the decision.
    4. For ``accept``: calls :func:`record_seen_signal` to update the ring
       buffer, then returns a :class:`SignalGuardOutcome` with
       ``decision=accept``.
    5. For all other decisions: increments the rejection counter and returns
       a :class:`SignalGuardOutcome` with the appropriate decision and a
       human-readable ``reject_reason``.

    Parameters
    ----------
    envelope:
        The inbound signal envelope.  Accepts:

        * :class:`~core.android_delegated_signal_ingress.DelegatedExecutionSignalEnvelope`
          — reads ``signal_id``, ``contract_id``, ``session_id``,
          ``emission_seq`` as attributes.
        * A plain ``dict`` — reads the same fields as dict keys.

    runtime:
        Optional :class:`RecoveryReadinessRuntime` for test isolation.
        Uses the process singleton when None.

    Returns
    -------
    SignalGuardOutcome
        The guard evaluation result.  The caller MUST check
        ``outcome.is_accepted()`` (or ``outcome.decision``) and MUST NOT
        forward the signal to the reconciler unless the decision is ``accept``.
    """
    rt = runtime if runtime is not None else get_recovery_readiness_runtime()

    # Extract fields — support both dataclass envelopes and plain dicts.
    if isinstance(envelope, dict):
        signal_id = str(envelope.get("signal_id") or "")
        contract_id = str(envelope.get("contract_id") or "")
        session_id = str(envelope.get("session_id") or "")
        emission_seq_raw = envelope.get("emission_seq", 0)
    else:
        signal_id = str(getattr(envelope, "signal_id", "") or "")
        contract_id = str(getattr(envelope, "contract_id", "") or "")
        session_id = str(getattr(envelope, "session_id", "") or "")
        emission_seq_raw = getattr(envelope, "emission_seq", 0)

    try:
        emission_seq = int(emission_seq_raw)
    except (TypeError, ValueError):
        emission_seq = 0

    key = build_idempotency_key(
        signal_id=signal_id,
        contract_id=contract_id,
        session_id=session_id,
    )

    max_seen_seq = rt.get_max_seq(key.context_key)
    decision = check_signal_guard(key, emission_seq, runtime=rt)

    if decision is SignalGuardDecision.accept:
        record_seen_signal(key, emission_seq, runtime=rt)
        return SignalGuardOutcome(
            decision=decision,
            idempotency_key=key,
            emission_seq=emission_seq,
            reject_reason="",
            max_seen_seq=max_seen_seq,
        )

    # Rejected — build human-readable reason and record rejection
    rt.record_rejection(decision)

    if decision is SignalGuardDecision.duplicate:
        reason = (
            f"guard:duplicate signal_id={key.signal_id!r} already seen "
            f"(context_key={key.context_key!r})"
        )
    elif decision is SignalGuardDecision.replay:
        reason = (
            f"guard:replay emission_seq={emission_seq} == max_seen={max_seen_seq} "
            f"but different signal_id={key.signal_id!r} "
            f"(context_key={key.context_key!r})"
        )
    elif decision is SignalGuardDecision.stale:
        reason = (
            f"guard:stale emission_seq={emission_seq} is more than "
            f"{STALE_EMISSION_SEQ_THRESHOLD} behind max_seen={max_seen_seq} "
            f"(context_key={key.context_key!r})"
        )
    else:  # out_of_order
        reason = (
            f"guard:out_of_order emission_seq={emission_seq} < "
            f"max_seen={max_seen_seq} "
            f"(context_key={key.context_key!r})"
        )

    return SignalGuardOutcome(
        decision=decision,
        idempotency_key=key,
        emission_seq=emission_seq,
        reject_reason=reason,
        max_seen_seq=max_seen_seq,
    )


def build_recovery_readiness_snapshot(
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> RecoveryReadinessSnapshot:
    """Return a :class:`RecoveryReadinessSnapshot` of the current guard state.

    Parameters
    ----------
    runtime:
        Optional :class:`RecoveryReadinessRuntime` for test isolation.
        Uses the process singleton when None.

    Returns
    -------
    RecoveryReadinessSnapshot
    """
    rt = runtime if runtime is not None else get_recovery_readiness_runtime()
    return rt.build_snapshot()


def clear_seq_context_for_reconnect(
    context_key: str,
    *,
    runtime: Optional[RecoveryReadinessRuntime] = None,
) -> None:
    """Clear the sequence-index entry for *context_key* after a reconnect.

    This MUST be called when a session or contract context reconnects so
    that the first post-reconnect signal is accepted rather than being
    misclassified as ``stale`` or ``out_of_order`` relative to signals
    that were seen before the disconnect.

    The ``signal_id`` ring buffer is intentionally preserved so that
    duplicate-signal protection remains active across the reconnect.

    Parameters
    ----------
    context_key:
        The context key whose maximum-sequence entry should be cleared.
        Use ``contract_id`` when available, otherwise ``session_id``.
        Typically derived from :attr:`IdempotencyKey.context_key`.
    runtime:
        Optional :class:`RecoveryReadinessRuntime` for test isolation.
        Uses the process singleton when None.
    """
    rt = runtime if runtime is not None else get_recovery_readiness_runtime()
    rt.clear_seq_context(context_key)
