"""core/delegated_runtime_execution_tracker.py
==============================================
PR package 10 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Delegated-Runtime Execution-Tracking and Acknowledgment Basis.

This module is the **canonical authority** for the host-side representation
of delegated-runtime execution state after a handoff contract has been
dispatched.  It provides stable, typed data structures and functions for
tracking whether delegated work was acknowledged by the remote surface, how
progress and partial results are represented, and how the final result is
reconciled back into the host session.

Background
----------
After PR-9 established the concept of a canonical handoff contract and the
``HandoffContractStatus.dispatched`` terminal state, the host-side
orchestration layer has no single canonical structure for tracking what happens
*after* dispatch: whether the Android surface acknowledged the work, what
progress signals were received, and how the final result is surfaced.  Without
this layer, the host cannot distinguish between a stale dispatch, an in-flight
execution, a successful delegated result, or a failed remote attempt.

PR-10 closes this gap on the MAIN-repo side by providing:

1. :class:`DelegatedExecutionPhase` — canonical enum for the phase of
   delegated-work execution as observed from the host side
   (``pending_ack`` / ``acknowledged`` / ``in_progress`` / ``completed`` /
   ``failed`` / ``timed_out`` / ``cancelled``).
2. :class:`AcknowledgmentSignal` — canonical enum for the type of signal
   received from the remote runtime surface
   (``ack`` / ``progress`` / ``partial_result`` / ``final_result`` /
   ``error`` / ``timeout`` / ``cancelled``).
3. :class:`DelegatedExecutionIdentity` — stable, serialisable record carrying
   the canonical identifiers for an execution-tracking entry: tracker_id,
   session_id, contract_id, device_id, trace_id.
4. :class:`DelegatedExecutionAcknowledgment` — typed record for a single
   acknowledgment or progress signal received from the remote surface,
   carrying the signal type, sequence number, timestamp, and opaque payload.
5. :class:`DelegatedExecutionResult` — typed record for the result
   reconciliation data once delegated execution completes or fails, carrying
   success flag, result payload, error detail, and completion timestamp.
6. :class:`DelegatedExecutionTrackingRecord` — canonical, immutable top-level
   execution-tracking record aggregating identity, current phase,
   acknowledgment history, pending result, linkage to the PR-9 handoff
   contract, and lifecycle timestamps.
7. :class:`DelegatedExecutionTrackingSnapshot` — point-in-time snapshot of
   all recent execution-tracking records for audit and projection.
8. :class:`DelegatedExecutionTrackingRuntime` — in-process ring-buffer
   singleton (128 entries) accumulating execution-tracking records across
   the process lifetime.
9. :func:`create_execution_tracking_record` — creates a canonical
   :class:`DelegatedExecutionTrackingRecord` from a handoff contract identity,
   defaulting to phase ``pending_ack``.
10. :func:`apply_acknowledgment_signal` — returns a new record with the
    given acknowledgment/progress signal appended and phase advanced
    accordingly.
11. :func:`apply_result` — returns a new record reflecting a final result
    (completed or failed), storing the :class:`DelegatedExecutionResult`.
12. :func:`record_execution_tracking` — persists a tracking record to the
    ring-buffer singleton.
13. :func:`get_execution_tracking_record` — retrieves the most recent
    tracking record for a given session_id from the ring-buffer.
14. :func:`list_active_execution_tracking_records` — returns all tracking
    records whose phase is not terminal.
15. :func:`build_execution_tracking_snapshot` — assembles a
    :class:`DelegatedExecutionTrackingSnapshot` from the ring-buffer state.
16. :func:`get_execution_tracking_runtime` / :func:`reset_execution_tracking_runtime`
    — singleton accessor and test-isolation helper.
17. Ten policy sentinels documenting canonical execution-tracking rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Contract-anchored** — every tracking record references a PR-9
  handoff contract id (``contract_id``) and an attached-session id
  (``session_id``); orphaned tracking records are rejected at creation time.
- **Phase-monotonic** — :class:`DelegatedExecutionPhase` advances
  monotonically from ``pending_ack`` toward a terminal phase; regression is
  disallowed.
- **Acknowledgment-sequence-preserving** — each acknowledgment entry carries
  a monotonically increasing sequence number; receivers must not re-order or
  deduplicate entries.
- **Result-immutable** — once a :class:`DelegatedExecutionResult` is recorded,
  it must not be replaced.  A second result signal on an already-completed
  record is silently ignored.
- **Posture-propagating** — the ``source_runtime_posture`` field flows from
  the handoff contract meta into the tracking record unchanged.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  and ``from_dict()`` for stable, round-trippable wire representations.
- **Graceful degradation** — unknown or missing fields default to safe
  outcomes (``DelegatedExecutionPhase.pending_ack``,
  ``AcknowledgmentSignal.ack``).

Relationship to other PR packages
----------------------------------
* PR-7  (``core.attached_runtime_session``) — every tracking record is
  anchored to an attached-runtime session id.
* PR-8  (``core.delegated_runtime_dispatch_intent``) — the dispatch record
  produces the session_id and device_id forwarded here.
* PR-9  (``core.delegated_runtime_handoff_contract``) — the handoff contract
  identity (contract_id, session_id, device_id, trace_id) is the primary
  anchor for each tracking record.
* PR-3  (``core.canonical_handoff_path``) — the downstream handoff path
  triggers the ``pending_ack`` phase that this module tracks.
* PR-4  (``core.canonical_session_truth``) — when execution completes the
  reconciled result feeds into session-truth merging via the result payload.
* PR-538 (``core.multi_device_coordination_authority``) — coordination_role
  is propagated into the tracking record for audit completeness.

Public API
----------
Sentinels::

    DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY
    EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY
    EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY
    EXECUTION_PHASE_IS_MONOTONIC_POLICY
    ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY
    RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY
    EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY
    TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY
    TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY
    PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY
    DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL

Enums::

    DelegatedExecutionPhase
    AcknowledgmentSignal

Dataclasses::

    DelegatedExecutionIdentity
    DelegatedExecutionAcknowledgment
    DelegatedExecutionResult
    DelegatedExecutionTrackingRecord
    DelegatedExecutionTrackingSnapshot

Classes::

    DelegatedExecutionTrackingRuntime

Functions::

    create_execution_tracking_record(...) -> DelegatedExecutionTrackingRecord
    apply_acknowledgment_signal(...) -> DelegatedExecutionTrackingRecord
    apply_result(...) -> DelegatedExecutionTrackingRecord
    record_execution_tracking(record, ...) -> None
    get_execution_tracking_record(session_id, ...) -> DelegatedExecutionTrackingRecord | None
    list_active_execution_tracking_records(...) -> list[DelegatedExecutionTrackingRecord]
    build_execution_tracking_snapshot(...) -> DelegatedExecutionTrackingSnapshot
    get_execution_tracking_runtime() -> DelegatedExecutionTrackingRuntime
    reset_execution_tracking_runtime() -> None
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY: str = (
    "DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY::"
    "core.delegated_runtime_execution_tracker is the canonical authority for "
    "host-side delegated-runtime execution-tracking and acknowledgment basis "
    "on the main-repo side (PR package 10, post-533 dual-repo runtime "
    "unification)."
)

EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY: str = (
    "POLICY::EXECUTION_TRACKING_REQUIRES_CONTRACT_ID: every "
    "DelegatedExecutionTrackingRecord must be linked to a PR-9 handoff "
    "contract via a non-empty contract_id.  Tracking records without a "
    "contract anchor must not be persisted or used for result reconciliation."
)

EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY: str = (
    "POLICY::EXECUTION_TRACKING_REQUIRES_SESSION_ID: every "
    "DelegatedExecutionTrackingRecord must carry a non-empty session_id from "
    "the PR-7 attached-runtime session.  Orphaned (session-less) tracking "
    "records are rejected at creation time and must not advance to any phase "
    "beyond pending_ack."
)

EXECUTION_PHASE_IS_MONOTONIC_POLICY: str = (
    "POLICY::EXECUTION_PHASE_IS_MONOTONIC: DelegatedExecutionPhase advances "
    "monotonically from pending_ack → acknowledged → in_progress → completed "
    "or failed or timed_out or cancelled.  Regression to an earlier phase is "
    "disallowed; terminal phases (completed/failed/timed_out/cancelled) must "
    "not transition to any other phase."
)

ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY: str = (
    "POLICY::ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING: each "
    "DelegatedExecutionAcknowledgment appended to a tracking record must carry "
    "a sequence number strictly greater than the sequence number of the "
    "previous entry.  Out-of-order or duplicate acknowledgments must be "
    "rejected."
)

RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY: str = (
    "POLICY::RESULT_IS_IMMUTABLE_ONCE_RECORDED: once a "
    "DelegatedExecutionResult is applied to a tracking record and the record "
    "transitions to completed or failed, no further result signals may overwrite "
    "it.  apply_result() on an already-terminal record returns the record "
    "unchanged."
)

EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY: str = (
    "POLICY::EXECUTION_TRACKING_POSTURE_IS_PROPAGATED: the "
    "source_runtime_posture field in a DelegatedExecutionTrackingRecord must "
    "flow unchanged from the PR-9 handoff contract meta and must not be "
    "normalised, coerced, or defaulted to a different value by the tracking "
    "layer."
)

TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY: str = (
    "POLICY::TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS: once a tracking record "
    "reaches a terminal phase (completed/failed/timed_out/cancelled), "
    "apply_acknowledgment_signal() and apply_result() must return the record "
    "unchanged.  Callers must not attempt to advance a terminal record."
)

TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY: str = (
    "POLICY::TRACKING_RECORD_IS_CONTRACT_ANCHORED: the contract_id in a "
    "DelegatedExecutionTrackingRecord must match the contract_id of the PR-9 "
    "DelegatedHandoffContractRecord that initiated the dispatch.  There is a "
    "one-to-one relationship between a dispatched handoff contract and its "
    "execution-tracking record."
)

PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY: str = (
    "POLICY::PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING: receiving an "
    "AcknowledgmentSignal.partial_result signal must advance the phase to "
    "in_progress but must not transition the tracking record to a terminal "
    "phase.  Only AcknowledgmentSignal.final_result or "
    "AcknowledgmentSignal.error transitions the record to completed or failed."
)

DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL: str = (
    "DELEGATED_RUNTIME_EXECUTION_TRACKER_PR10_SENTINEL::package=10 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.delegated_runtime_execution_tracker"
)

# Convenience tuple for iteration / projection
_ALL_POLICY_SENTINELS = (
    DELEGATED_RUNTIME_EXECUTION_TRACKER_AUTHORITY,
    EXECUTION_TRACKING_REQUIRES_CONTRACT_ID_POLICY,
    EXECUTION_TRACKING_REQUIRES_SESSION_ID_POLICY,
    EXECUTION_PHASE_IS_MONOTONIC_POLICY,
    ACK_SEQUENCE_IS_MONOTONICALLY_INCREASING_POLICY,
    RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY,
    EXECUTION_TRACKING_POSTURE_IS_PROPAGATED_POLICY,
    TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY,
    TRACKING_RECORD_IS_CONTRACT_ANCHORED_POLICY,
    PARTIAL_RESULT_DOES_NOT_CLOSE_TRACKING_POLICY,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"
_RING_BUFFER_CAPACITY: int = 128

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DelegatedExecutionPhase(str, Enum):
    """Canonical enum for the phase of delegated-work execution (host view).

    Values
    ------
    pending_ack
        The handoff contract has been dispatched but no acknowledgment has
        been received from the remote runtime surface yet.
    acknowledged
        The remote surface has confirmed receipt of the delegated task.
    in_progress
        The remote surface has reported that execution is underway; at least
        one progress or partial_result signal has been received.
    completed
        The remote surface has reported successful completion and a final
        result has been reconciled.  Terminal phase.
    failed
        The remote surface reported an error or the host detected a failure
        during execution.  Terminal phase.
    timed_out
        No acknowledgment or progress was received within the allowed window.
        Terminal phase.
    cancelled
        The delegated execution was explicitly cancelled by the host or by
        the remote surface.  Terminal phase.
    """

    pending_ack = "pending_ack"
    acknowledged = "acknowledged"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    timed_out = "timed_out"
    cancelled = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedExecutionPhase":
        """Return the enum member matching *value*, defaulting to ``pending_ack``."""
        if not isinstance(value, str):
            return cls.pending_ack
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.pending_ack

    def is_terminal(self) -> bool:
        """Return True if this phase is terminal."""
        return self in (
            DelegatedExecutionPhase.completed,
            DelegatedExecutionPhase.failed,
            DelegatedExecutionPhase.timed_out,
            DelegatedExecutionPhase.cancelled,
        )

    def is_active(self) -> bool:
        """Return True if the tracking record is actively tracked (non-terminal)."""
        return not self.is_terminal()

    def can_advance_to(self, next_phase: "DelegatedExecutionPhase") -> bool:
        """Return True if monotonic advancement to *next_phase* is permitted.

        Advancement order (numeric): pending_ack(0) → acknowledged(1) →
        in_progress(2) → completed/failed/timed_out/cancelled(3).
        Terminal phases block all further transitions.
        """
        if self.is_terminal():
            return False
        _order: Dict[DelegatedExecutionPhase, int] = {
            DelegatedExecutionPhase.pending_ack: 0,
            DelegatedExecutionPhase.acknowledged: 1,
            DelegatedExecutionPhase.in_progress: 2,
            DelegatedExecutionPhase.completed: 3,
            DelegatedExecutionPhase.failed: 3,
            DelegatedExecutionPhase.timed_out: 3,
            DelegatedExecutionPhase.cancelled: 3,
        }
        return _order.get(next_phase, -1) > _order.get(self, -1)


class AcknowledgmentSignal(str, Enum):
    """Canonical enum for acknowledgment/progress signals from the remote surface.

    Values
    ------
    ack
        Simple receipt acknowledgment; advances phase to ``acknowledged``.
    progress
        Generic in-progress heartbeat; advances to ``in_progress``.
    partial_result
        Intermediate result available; advances to ``in_progress`` but does
        not close the tracking record.
    final_result
        Execution has completed successfully; advances to ``completed``.
    error
        The remote surface reported an error; advances to ``failed``.
    timeout
        The host detected an acknowledgment timeout; advances to ``timed_out``.
    cancelled
        Execution was cancelled; advances to ``cancelled``.
    """

    ack = "ack"
    progress = "progress"
    partial_result = "partial_result"
    final_result = "final_result"
    error = "error"
    timeout = "timeout"
    cancelled = "cancelled"

    @classmethod
    def from_string(cls, value: str) -> "AcknowledgmentSignal":
        """Return the enum member matching *value*, defaulting to ``ack``."""
        if not isinstance(value, str):
            return cls.ack
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.ack

    def target_phase(self) -> DelegatedExecutionPhase:
        """Return the :class:`DelegatedExecutionPhase` this signal advances to."""
        _mapping: Dict[AcknowledgmentSignal, DelegatedExecutionPhase] = {
            AcknowledgmentSignal.ack: DelegatedExecutionPhase.acknowledged,
            AcknowledgmentSignal.progress: DelegatedExecutionPhase.in_progress,
            AcknowledgmentSignal.partial_result: DelegatedExecutionPhase.in_progress,
            AcknowledgmentSignal.final_result: DelegatedExecutionPhase.completed,
            AcknowledgmentSignal.error: DelegatedExecutionPhase.failed,
            AcknowledgmentSignal.timeout: DelegatedExecutionPhase.timed_out,
            AcknowledgmentSignal.cancelled: DelegatedExecutionPhase.cancelled,
        }
        return _mapping[self]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DelegatedExecutionIdentity:
    """Canonical identifiers for a delegated-runtime execution-tracking entry.

    Attributes
    ----------
    tracker_id
        Stable UUID for this tracking entry.
    session_id
        Attached-runtime session id from PR-7.  Must be non-empty.
    contract_id
        ID of the PR-9 DelegatedHandoffContractRecord that initiated dispatch.
        Must be non-empty.
    device_id
        Identity of the remote device/runtime surface.
    trace_id
        Distributed trace identifier propagated from the originating request.
    """

    tracker_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    contract_id: str = ""
    device_id: str = ""
    trace_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tracker_id": self.tracker_id,
            "session_id": self.session_id,
            "contract_id": self.contract_id,
            "device_id": self.device_id,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedExecutionIdentity":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedExecutionIdentity.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        return cls(
            tracker_id=str(data.get("tracker_id", "") or str(uuid.uuid4())),
            session_id=str(data.get("session_id", "")),
            contract_id=str(data.get("contract_id", "")),
            device_id=str(data.get("device_id", "")),
            trace_id=str(data.get("trace_id", "")),
        )


@dataclass(frozen=True)
class DelegatedExecutionAcknowledgment:
    """A single acknowledgment or progress signal from the remote surface.

    Attributes
    ----------
    signal
        The type of signal received.
    sequence
        Monotonically increasing sequence number within this tracking entry.
    received_at
        Unix timestamp when the signal was received by the host.
    payload
        Opaque signal payload dict (may contain partial result data).
    """

    signal: AcknowledgmentSignal = AcknowledgmentSignal.ack
    sequence: int = 0
    received_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal.value,
            "sequence": self.sequence,
            "received_at": self.received_at,
            "payload": dict(self.payload),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedExecutionAcknowledgment":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedExecutionAcknowledgment.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        return cls(
            signal=AcknowledgmentSignal.from_string(str(data.get("signal", "ack"))),
            sequence=int(data.get("sequence", 0)),
            received_at=float(data.get("received_at", time.time())),
            payload=dict(data.get("payload", {})),
        )


@dataclass(frozen=True)
class DelegatedExecutionResult:
    """Result reconciliation data for a completed or failed delegated execution.

    Attributes
    ----------
    success
        True if the remote surface reported successful completion.
    result_payload
        The result data returned by the remote surface.  Empty dict if none.
    error_detail
        Human-readable error description when ``success`` is False.
    completed_at
        Unix timestamp when the result was reconciled.
    metadata
        Additional opaque key/value pairs.
    """

    success: bool = False
    result_payload: Dict[str, Any] = field(default_factory=dict)
    error_detail: str = ""
    completed_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "result_payload": dict(self.result_payload),
            "error_detail": self.error_detail,
            "completed_at": self.completed_at,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedExecutionResult":
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedExecutionResult.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        return cls(
            success=bool(data.get("success", False)),
            result_payload=dict(data.get("result_payload", {})),
            error_detail=str(data.get("error_detail", "")),
            completed_at=float(data.get("completed_at", time.time())),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class DelegatedExecutionTrackingRecord:
    """Canonical, immutable host-side execution-tracking record.

    This is the primary value type produced by
    :func:`create_execution_tracking_record`.  It aggregates identity, current
    phase, acknowledgment history, optional result, handoff contract linkage,
    posture/role context, and lifecycle timestamps.

    Attributes
    ----------
    identity
        Canonical identifiers for this tracking entry.
    phase
        Current execution phase as observed from the host side.
    acknowledgments
        Ordered list of acknowledgment/progress signals received, oldest-first.
    result
        Final result record, or None if not yet reconciled.
    source_runtime_posture
        Posture propagated from the PR-9 handoff contract meta.
    coordination_role
        Coordination role at the time of delegation (informational).
    created_at
        Unix timestamp when the tracking record was created.
    updated_at
        Unix timestamp of the last state change.
    reject_reason
        Non-empty string when the tracking record was rejected at creation.
    """

    identity: DelegatedExecutionIdentity = field(
        default_factory=DelegatedExecutionIdentity
    )
    phase: DelegatedExecutionPhase = DelegatedExecutionPhase.pending_ack
    acknowledgments: List[DelegatedExecutionAcknowledgment] = field(
        default_factory=list
    )
    result: Optional[DelegatedExecutionResult] = None
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    reject_reason: str = ""

    # Convenience accessors -------------------------------------------------

    def is_accepted(self) -> bool:
        """Return True iff the record was accepted (not rejected, contract-anchored)."""
        return (
            not self.reject_reason
            and bool(self.identity.session_id)
            and bool(self.identity.contract_id)
        )

    def is_rejected(self) -> bool:
        """Return True iff the record was rejected at creation time."""
        return bool(self.reject_reason)

    def is_active(self) -> bool:
        """Return True iff the tracking record is in a non-terminal phase."""
        return self.phase.is_active()

    def is_terminal(self) -> bool:
        """Return True iff the tracking record has reached a terminal phase."""
        return self.phase.is_terminal()

    def next_sequence(self) -> int:
        """Return the next expected acknowledgment sequence number."""
        if not self.acknowledgments:
            return 0
        return self.acknowledgments[-1].sequence + 1

    # Serialisation ---------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": self.identity.to_dict(),
            "phase": self.phase.value,
            "acknowledgments": [a.to_dict() for a in self.acknowledgments],
            "result": self.result.to_dict() if self.result is not None else None,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "reject_reason": self.reject_reason,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedExecutionTrackingRecord":
        """Reconstruct a tracking record from a serialised dict.

        Unknown or malformed fields fall back to safe defaults.
        """
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedExecutionTrackingRecord.from_dict: expected dict, "
                f"got {type(data).__name__!r}"
            )
        raw_identity = data.get("identity", {})
        raw_acks = data.get("acknowledgments", [])
        raw_result = data.get("result")

        identity = (
            DelegatedExecutionIdentity.from_dict(raw_identity)
            if isinstance(raw_identity, dict)
            else DelegatedExecutionIdentity()
        )
        acknowledgments = [
            DelegatedExecutionAcknowledgment.from_dict(a)
            for a in raw_acks
            if isinstance(a, dict)
        ]
        result: Optional[DelegatedExecutionResult] = None
        if isinstance(raw_result, dict):
            result = DelegatedExecutionResult.from_dict(raw_result)

        return cls(
            identity=identity,
            phase=DelegatedExecutionPhase.from_string(
                str(data.get("phase", DelegatedExecutionPhase.pending_ack.value))
            ),
            acknowledgments=acknowledgments,
            result=result,
            source_runtime_posture=str(
                data.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
            ),
            coordination_role=str(data.get("coordination_role", "")),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            reject_reason=str(data.get("reject_reason", "")),
        )


@dataclass(frozen=True)
class DelegatedExecutionTrackingSnapshot:
    """Point-in-time snapshot of all recent delegated-runtime execution-tracking records.

    Attributes
    ----------
    snapshot_id
        Stable UUID for this snapshot.
    records
        All tracking records in the snapshot, newest-first.
    active_count
        Number of records in a non-terminal phase.
    total_count
        Total number of records in the snapshot.
    snapshotted_at
        Unix timestamp when the snapshot was assembled.
    policy_sentinels
        List of all policy sentinel strings for audit/projection.
    """

    snapshot_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    records: List[DelegatedExecutionTrackingRecord] = field(default_factory=list)
    active_count: int = 0
    total_count: int = 0
    snapshotted_at: float = field(default_factory=time.time)
    policy_sentinels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "records": [r.to_dict() for r in self.records],
            "active_count": self.active_count,
            "total_count": self.total_count,
            "snapshotted_at": self.snapshotted_at,
            "policy_sentinels": list(self.policy_sentinels),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# Ring-buffer runtime
# ---------------------------------------------------------------------------


class DelegatedExecutionTrackingRuntime:
    """In-process ring-buffer singleton accumulating execution-tracking records.

    Capacity: 128 entries.  Oldest entry is evicted when the buffer is full.
    Thread-safety: this class is deliberately not thread-safe; callers that
    need concurrency guarantees must apply external locking.
    """

    _CAPACITY: int = _RING_BUFFER_CAPACITY

    def __init__(self) -> None:
        self._buf: Deque[DelegatedExecutionTrackingRecord] = deque(
            maxlen=self._CAPACITY
        )

    @property
    def capacity(self) -> int:
        return self._CAPACITY

    @property
    def size(self) -> int:
        return len(self._buf)

    def push(self, record: DelegatedExecutionTrackingRecord) -> None:
        """Append *record* to the ring buffer, evicting the oldest if full."""
        self._buf.append(record)

    def list_all(self) -> List[DelegatedExecutionTrackingRecord]:
        """Return all records, newest-first."""
        return list(reversed(self._buf))

    def list_active(self) -> List[DelegatedExecutionTrackingRecord]:
        """Return records in a non-terminal phase, newest-first."""
        return [r for r in reversed(self._buf) if r.phase.is_active()]

    def get_latest_for_session(
        self, session_id: str
    ) -> Optional[DelegatedExecutionTrackingRecord]:
        """Return the most recent record for *session_id*, or None."""
        for record in reversed(self._buf):
            if record.identity.session_id == session_id:
                return record
        return None

    def get_latest_for_contract(
        self, contract_id: str
    ) -> Optional[DelegatedExecutionTrackingRecord]:
        """Return the most recent record for *contract_id*, or None."""
        for record in reversed(self._buf):
            if record.identity.contract_id == contract_id:
                return record
        return None

    def clear(self) -> None:
        """Remove all records from the buffer."""
        self._buf.clear()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_SINGLETON_RUNTIME: Optional[DelegatedExecutionTrackingRuntime] = None


def get_execution_tracking_runtime() -> DelegatedExecutionTrackingRuntime:
    """Return the process-singleton :class:`DelegatedExecutionTrackingRuntime`."""
    global _SINGLETON_RUNTIME  # noqa: PLW0603
    if _SINGLETON_RUNTIME is None:
        _SINGLETON_RUNTIME = DelegatedExecutionTrackingRuntime()
    return _SINGLETON_RUNTIME


def reset_execution_tracking_runtime() -> None:
    """Replace the singleton with a fresh instance (test isolation helper)."""
    global _SINGLETON_RUNTIME  # noqa: PLW0603
    _SINGLETON_RUNTIME = DelegatedExecutionTrackingRuntime()


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def create_execution_tracking_record(
    *,
    session_id: str,
    contract_id: str,
    device_id: str = "",
    trace_id: str = "",
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
    coordination_role: str = "",
    tracker_id: Optional[str] = None,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> DelegatedExecutionTrackingRecord:
    """Create a canonical :class:`DelegatedExecutionTrackingRecord`.

    The new record starts in phase ``pending_ack``.  If *session_id* or
    *contract_id* is empty the record is immediately rejected (phase set to
    ``cancelled``, ``reject_reason`` populated).

    Parameters
    ----------
    session_id:
        PR-7 attached-runtime session id.  Must be non-empty.
    contract_id:
        PR-9 handoff contract id.  Must be non-empty.
    device_id:
        Remote device / runtime surface identity.
    trace_id:
        Distributed trace identifier.  Auto-generated if empty.
    source_runtime_posture:
        Posture propagated from the handoff contract meta.
    coordination_role:
        Coordination role at the time of delegation.
    tracker_id:
        Override the auto-generated tracker UUID (for testing / idempotency).
    runtime:
        Ring-buffer to persist to.  Uses singleton if None.

    Returns
    -------
    DelegatedExecutionTrackingRecord
        The newly created (and persisted) tracking record.
    """
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()

    # Validate required anchors
    if not session_id:
        record = DelegatedExecutionTrackingRecord(
            identity=DelegatedExecutionIdentity(
                tracker_id=tracker_id or str(uuid.uuid4()),
                session_id="",
                contract_id=contract_id,
                device_id=device_id,
                trace_id=trace_id or str(uuid.uuid4()),
            ),
            phase=DelegatedExecutionPhase.cancelled,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            reject_reason=(
                "EXECUTION_TRACKING_REQUIRES_SESSION_ID: session_id is empty"
            ),
        )
        _runtime.push(record)
        return record

    if not contract_id:
        record = DelegatedExecutionTrackingRecord(
            identity=DelegatedExecutionIdentity(
                tracker_id=tracker_id or str(uuid.uuid4()),
                session_id=session_id,
                contract_id="",
                device_id=device_id,
                trace_id=trace_id or str(uuid.uuid4()),
            ),
            phase=DelegatedExecutionPhase.cancelled,
            source_runtime_posture=source_runtime_posture,
            coordination_role=coordination_role,
            reject_reason=(
                "EXECUTION_TRACKING_REQUIRES_CONTRACT_ID: contract_id is empty"
            ),
        )
        _runtime.push(record)
        return record

    now = time.time()
    record = DelegatedExecutionTrackingRecord(
        identity=DelegatedExecutionIdentity(
            tracker_id=tracker_id or str(uuid.uuid4()),
            session_id=session_id,
            contract_id=contract_id,
            device_id=device_id,
            trace_id=trace_id or str(uuid.uuid4()),
        ),
        phase=DelegatedExecutionPhase.pending_ack,
        acknowledgments=[],
        result=None,
        source_runtime_posture=source_runtime_posture,
        coordination_role=coordination_role,
        created_at=now,
        updated_at=now,
        reject_reason="",
    )
    _runtime.push(record)
    return record


def apply_acknowledgment_signal(
    record: DelegatedExecutionTrackingRecord,
    signal: AcknowledgmentSignal,
    *,
    payload: Optional[Dict[str, Any]] = None,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> DelegatedExecutionTrackingRecord:
    """Apply an acknowledgment/progress signal to *record*, returning a new record.

    If the record is already in a terminal phase the original record is
    returned unchanged (per TERMINAL_PHASE_BLOCKS_FURTHER_SIGNALS_POLICY).

    The new acknowledgment entry is appended with a sequence number equal to
    ``record.next_sequence()``.  The phase is advanced to
    ``signal.target_phase()`` if the transition is permitted; otherwise the
    current phase is preserved and only the acknowledgment entry is added.

    Parameters
    ----------
    record:
        The existing tracking record to update.
    signal:
        The acknowledgment/progress signal to apply.
    payload:
        Optional signal payload dict.
    runtime:
        Ring-buffer to persist the updated record to.  Uses singleton if None.

    Returns
    -------
    DelegatedExecutionTrackingRecord
        Updated tracking record (or *record* unchanged if terminal).
    """
    if record.phase.is_terminal():
        return record

    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()

    ack = DelegatedExecutionAcknowledgment(
        signal=signal,
        sequence=record.next_sequence(),
        received_at=time.time(),
        payload=dict(payload) if payload else {},
    )

    target = signal.target_phase()
    new_phase = target if record.phase.can_advance_to(target) else record.phase

    new_acks = list(record.acknowledgments) + [ack]
    updated = DelegatedExecutionTrackingRecord(
        identity=record.identity,
        phase=new_phase,
        acknowledgments=new_acks,
        result=record.result,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        created_at=record.created_at,
        updated_at=time.time(),
        reject_reason=record.reject_reason,
    )
    _runtime.push(updated)
    return updated


def apply_result(
    record: DelegatedExecutionTrackingRecord,
    result: DelegatedExecutionResult,
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> DelegatedExecutionTrackingRecord:
    """Apply a final result to *record*, returning a new record.

    If the record is already terminal the original record is returned
    unchanged (per RESULT_IS_IMMUTABLE_ONCE_RECORDED_POLICY).

    Successful results advance the phase to ``completed``; unsuccessful
    results advance to ``failed``.

    Parameters
    ----------
    record:
        The existing tracking record to update.
    result:
        The :class:`DelegatedExecutionResult` to apply.
    runtime:
        Ring-buffer to persist the updated record to.  Uses singleton if None.

    Returns
    -------
    DelegatedExecutionTrackingRecord
        Updated tracking record (or *record* unchanged if terminal).
    """
    if record.phase.is_terminal():
        return record

    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()

    new_phase = (
        DelegatedExecutionPhase.completed
        if result.success
        else DelegatedExecutionPhase.failed
    )
    updated = DelegatedExecutionTrackingRecord(
        identity=record.identity,
        phase=new_phase,
        acknowledgments=list(record.acknowledgments),
        result=result,
        source_runtime_posture=record.source_runtime_posture,
        coordination_role=record.coordination_role,
        created_at=record.created_at,
        updated_at=time.time(),
        reject_reason=record.reject_reason,
    )
    _runtime.push(updated)
    return updated


def record_execution_tracking(
    record: DelegatedExecutionTrackingRecord,
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> None:
    """Persist *record* to the ring-buffer singleton (or *runtime* if provided)."""
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()
    _runtime.push(record)


def get_execution_tracking_record(
    session_id: str,
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> Optional[DelegatedExecutionTrackingRecord]:
    """Return the most recent tracking record for *session_id*, or None."""
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()
    return _runtime.get_latest_for_session(session_id)


def list_active_execution_tracking_records(
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> List[DelegatedExecutionTrackingRecord]:
    """Return all tracking records in a non-terminal phase, newest-first."""
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()
    return _runtime.list_active()


def build_execution_tracking_snapshot(
    *,
    runtime: Optional[DelegatedExecutionTrackingRuntime] = None,
) -> DelegatedExecutionTrackingSnapshot:
    """Assemble a :class:`DelegatedExecutionTrackingSnapshot` from the ring-buffer.

    Parameters
    ----------
    runtime:
        Ring-buffer to snapshot.  Uses singleton if None.
    """
    _runtime = runtime if runtime is not None else get_execution_tracking_runtime()
    all_records = _runtime.list_all()
    active = [r for r in all_records if r.phase.is_active()]
    return DelegatedExecutionTrackingSnapshot(
        records=all_records,
        active_count=len(active),
        total_count=len(all_records),
        policy_sentinels=list(_ALL_POLICY_SENTINELS),
    )
