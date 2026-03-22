"""contracts/runtime_recovery_reconciliation.py
================================================
Runtime Recovery and Reconciliation Contract — PR-39.

This module defines the **canonical Runtime Recovery and Reconciliation
Contract**: a unified, fully serialisable, advisory read-model that describes
how interrupted, partial, failed, or divergent multi-device runtime activity
is represented, assessed, and reconciled across source runtime, target runtime,
mesh session, coordinator state, and merged results.

It answers the architectural question:

    *"When multi-device runtime activity is interrupted, partially completed,
    or diverges across devices/runtimes, what canonical contract describes
    recovery posture and reconciliation state?"*

This module formalises:
- the recovery incident type enum (``RecoveryIncidentType``);
- the recovery status enum (``RecoveryStatus``);
- the recovery action type enum (``RecoveryActionType``);
- per-participant recovery state (``RecoveryParticipantState``);
- recommended advisory recovery actions (``RecoveryActionRecommendation``);
- barrier state from a recovery perspective (``RecoveryBarrierState``);
- the top-level recovery incident (``RuntimeRecoveryIncident``);
- the reconciliation state across participants/results (``RuntimeReconciliationState``);
- a lightweight read-only summary (``RecoverySummary``);
- builder and adapter functions for all contracts.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond the primary identifier are optional;
  callers with partial context always produce a valid contract.
- **Stable field names** — downstream consumers can rely on all field names.
- **Read-only / advisory semantics** — this PR introduces no write/command
  endpoints and no automated recovery engine.
- **Tolerant of partial/missing data** — all adapters handle ``None`` inputs
  gracefully.
- **No UI-specific semantics** — purely runtime/projection use.

Contract chain consumed
-----------------------
- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`)
  — target-side takeover result.
- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchResult`)
  — source-side dispatch result.
- **PR-36** (:class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`)
  — cross-runtime merged results.
- **PR-37** (:class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`)
  — mesh coordinator state.
- **PR-38** (:class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`)
  — unified multi-device runtime projection.

Usage::

    from contracts.runtime_recovery_reconciliation import (
        RuntimeRecoveryIncident,
        build_runtime_recovery_incident,
        from_source_dispatch_result,
        from_target_takeover_result,
        build_runtime_reconciliation_state,
    )

    incident = build_runtime_recovery_incident(
        incident_type="dispatch_failure",
        source_device_id="phone_001",
        affected_devices=["phone_001", "tablet_002"],
        reason="Dispatch timed out after 30s",
    )
    print(incident.to_json(indent=2))

See ``docs/RUNTIME_RECOVERY_RECONCILIATION.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class RecoveryIncidentType(str, Enum):
    """Describes the nature of a runtime recovery incident.

    dispatch_failure
        Source dispatch failed or was not acknowledged by a target runtime.
    handoff_interrupted
        A handoff envelope was sent but the target did not complete adoption.
    takeover_failed
        Target runtime attempted local takeover but encountered a fatal error.
    merge_conflict
        Cross-runtime result merge detected conflicting or incompatible results.
    coordinator_lost
        Mesh session coordinator became unreachable or entered an error state.
    session_diverged
        Mesh session participants reported inconsistent states, indicating
        divergence across runtimes.
    result_stale
        One or more result units are stale (superseded or not confirmed as
        authoritative).
    partial_completion
        Multi-device task partially completed; some participants succeeded while
        others failed or are pending.
    unknown
        Incident type could not be determined from available context.
    """

    dispatch_failure = "dispatch_failure"
    handoff_interrupted = "handoff_interrupted"
    takeover_failed = "takeover_failed"
    merge_conflict = "merge_conflict"
    coordinator_lost = "coordinator_lost"
    session_diverged = "session_diverged"
    result_stale = "result_stale"
    partial_completion = "partial_completion"
    unknown = "unknown"


class RecoveryStatus(str, Enum):
    """Lifecycle status of a recovery or reconciliation contract.

    pending
        Incident has been detected; no recovery action has started.
    in_progress
        Recovery actions are underway (e.g. retry, local resume).
    resolved
        Incident has been resolved; system is back to normal operation.
    needs_intervention
        Automated recovery cannot proceed; manual intervention is required.
    stale
        Incident record is stale — superseded by a newer incident or a
        confirmed resolution from a later runtime cycle.
    """

    pending = "pending"
    in_progress = "in_progress"
    resolved = "resolved"
    needs_intervention = "needs_intervention"
    stale = "stale"


class RecoveryActionType(str, Enum):
    """Advisory action types emitted as recommendations.

    retry_handoff
        Re-attempt the handoff from source to target.
    resume_local
        Allow the source or target to resume execution locally.
    request_merge_confirmation
        Request explicit confirmation before completing a cross-runtime merge.
    repair_mesh_session
        Attempt to repair or re-establish the mesh session.
    mark_stale
        Mark identified result units or participant states as stale.
    fallback_local
        Fall back to fully local execution on the source device.
    replay_assignment
        Replay one or more subtask assignments to affected participants.
    wait_for_participant
        Pause reconciliation while awaiting a participant response.
    escalate
        Escalate the incident for manual review.
    """

    retry_handoff = "retry_handoff"
    resume_local = "resume_local"
    request_merge_confirmation = "request_merge_confirmation"
    repair_mesh_session = "repair_mesh_session"
    mark_stale = "mark_stale"
    fallback_local = "fallback_local"
    replay_assignment = "replay_assignment"
    wait_for_participant = "wait_for_participant"
    escalate = "escalate"


# ---------------------------------------------------------------------------
# Sub-contracts
# ---------------------------------------------------------------------------


class RecoveryParticipantState(BaseModel):
    """Per-participant recovery posture within a recovery incident.

    Fields
    ------
    device_id
        Identifier of the participant device.
    runtime_id
        Optional identifier of the runtime session on this device.
    status
        Current recovery status for this participant.
    authoritative
        Whether this participant holds the authoritative copy of results.
        ``None`` means unknown.
    replay_required
        Whether this participant must replay its assigned work.
        ``None`` means unknown.
    resume_allowed
        Whether local resume is permissible for this participant.
        ``None`` means unknown.
    last_known_assignment_ids
        IDs of the last known subtask assignments for this participant.
    last_known_result_unit_ids
        IDs of the last known result units produced by this participant.
    metadata
        Arbitrary extensibility bag.
    """

    device_id: str = Field(description="Identifier of the participant device.")
    runtime_id: Optional[str] = Field(
        default=None,
        description="Optional identifier of the runtime session on this device.",
    )
    status: str = Field(
        default=RecoveryStatus.pending.value,
        description="Current recovery status for this participant.",
    )
    authoritative: Optional[bool] = Field(
        default=None,
        description=(
            "Whether this participant holds the authoritative copy of results.  "
            "None means unknown."
        ),
    )
    replay_required: Optional[bool] = Field(
        default=None,
        description=(
            "Whether this participant must replay its assigned work.  "
            "None means unknown."
        ),
    )
    resume_allowed: Optional[bool] = Field(
        default=None,
        description=(
            "Whether local resume is permissible for this participant.  "
            "None means unknown."
        ),
    )
    last_known_assignment_ids: List[str] = Field(
        default_factory=list,
        description="IDs of the last known subtask assignments for this participant.",
    )
    last_known_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of the last known result units produced by this participant.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryParticipantState":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)


class RecoveryActionRecommendation(BaseModel):
    """An advisory recommended action for resolving a recovery incident.

    Fields
    ------
    action_type
        The type of recovery action recommended.
    target_device_id
        Optional device to which this action recommendation is directed.
    result_unit_id
        Optional result unit this action relates to.
    reason
        Human-readable rationale for the recommendation.
    metadata
        Arbitrary extensibility bag.
    """

    action_type: str = Field(
        description="The type of recovery action recommended.",
    )
    target_device_id: Optional[str] = Field(
        default=None,
        description="Optional device to which this action recommendation is directed.",
    )
    result_unit_id: Optional[str] = Field(
        default=None,
        description="Optional result unit this action relates to.",
    )
    reason: str = Field(
        default="",
        description="Human-readable rationale for the recommendation.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryActionRecommendation":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)


class RecoveryBarrierState(BaseModel):
    """Recovery-perspective view of a runtime barrier.

    Captures whether a barrier is blocking reconciliation, what is pending,
    and whether it can be cleared automatically.

    Fields
    ------
    barrier_id
        Stable unique identifier for this barrier state.
    blocking
        Whether this barrier is currently blocking recovery progress.
    pending_device_ids
        Devices that have not yet cleared this barrier.
    clearable
        Whether the barrier can be cleared automatically without intervention.
    description
        Human-readable description of the barrier.
    metadata
        Arbitrary extensibility bag.
    """

    barrier_id: str = Field(
        default_factory=lambda: f"rbar_{uuid.uuid4().hex[:8]}",
        description="Stable unique identifier for this barrier state.",
    )
    blocking: bool = Field(
        default=False,
        description="Whether this barrier is currently blocking recovery progress.",
    )
    pending_device_ids: List[str] = Field(
        default_factory=list,
        description="Devices that have not yet cleared this barrier.",
    )
    clearable: bool = Field(
        default=True,
        description=(
            "Whether the barrier can be cleared automatically without intervention."
        ),
    )
    description: str = Field(
        default="",
        description="Human-readable description of the barrier.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryBarrierState":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Top-level contracts
# ---------------------------------------------------------------------------


class RuntimeRecoveryIncident(BaseModel):
    """Canonical representation of a runtime recovery incident.

    A recovery incident captures all relevant context about an interruption,
    failure, or divergence in multi-device runtime activity.  It is the
    primary advisory read-model for downstream recovery orchestration.

    Fields
    ------
    recovery_id
        Stable, globally-unique identifier for this recovery incident.
    generated_at
        Unix epoch seconds when this incident was first recorded.
    trace_id
        Optional execution trace identifier linking this incident to a trace.
    task_id
        Optional task identifier linking this incident to a specific task.
    session_id
        Optional runtime session identifier.
    mesh_session_id
        Optional mesh session identifier for cross-device incidents.
    source_device_id
        Optional identifier of the device that initiated the operation.
    primary_device_id
        Optional identifier of the device designated as primary for merge/authority.
    incident_type
        Categorical description of what caused or characterises this incident.
    status
        Current lifecycle status of this recovery incident.
    affected_devices
        List of device IDs affected by this incident.
    affected_runtime_ids
        List of runtime session IDs affected by this incident.
    participant_states
        Per-participant recovery posture entries.
    stale_result_unit_ids
        IDs of result units that are stale and may need re-evaluation.
    authoritative_result_unit_ids
        IDs of result units that are confirmed authoritative.
    pending_result_unit_ids
        IDs of result units that are pending confirmation or completion.
    replay_required
        Whether any participant must replay work to resolve this incident.
    resume_allowed
        Whether local resume is a valid resolution path.
    merge_confirmation_required
        Whether explicit merge confirmation is required before proceeding.
    barrier_state
        Optional barrier state blocking recovery progress.
    recommended_actions
        Advisory list of recommended recovery actions.
    reason
        Human-readable description of why this incident was raised.
    metadata
        Arbitrary extensibility bag.
    """

    recovery_id: str = Field(
        default_factory=lambda: f"rrinc_{uuid.uuid4().hex[:12]}",
        description="Stable, globally-unique identifier for this recovery incident.",
    )
    generated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this incident was first recorded.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional execution trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional runtime session identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Optional mesh session identifier.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Optional identifier of the device that initiated the operation.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional identifier of the device designated as primary for "
            "merge/authority decisions."
        ),
    )
    incident_type: str = Field(
        default=RecoveryIncidentType.unknown.value,
        description="Categorical description of this incident.",
    )
    status: str = Field(
        default=RecoveryStatus.pending.value,
        description="Current lifecycle status of this recovery incident.",
    )
    affected_devices: List[str] = Field(
        default_factory=list,
        description="List of device IDs affected by this incident.",
    )
    affected_runtime_ids: List[str] = Field(
        default_factory=list,
        description="List of runtime session IDs affected by this incident.",
    )
    participant_states: List[RecoveryParticipantState] = Field(
        default_factory=list,
        description="Per-participant recovery posture entries.",
    )
    stale_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units that are stale.",
    )
    authoritative_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units that are confirmed authoritative.",
    )
    pending_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units that are pending confirmation.",
    )
    replay_required: bool = Field(
        default=False,
        description="Whether any participant must replay work.",
    )
    resume_allowed: bool = Field(
        default=False,
        description="Whether local resume is a valid resolution path.",
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description="Whether explicit merge confirmation is required.",
    )
    barrier_state: Optional[RecoveryBarrierState] = Field(
        default=None,
        description="Optional barrier state blocking recovery progress.",
    )
    recommended_actions: List[RecoveryActionRecommendation] = Field(
        default_factory=list,
        description="Advisory list of recommended recovery actions.",
    )
    reason: str = Field(
        default="",
        description="Human-readable description of why this incident was raised.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeRecoveryIncident":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a lightweight summary dict for embedding in projections."""
        return {
            "recovery_id": self.recovery_id,
            "incident_type": self.incident_type,
            "status": self.status,
            "affected_device_count": len(self.affected_devices),
            "participant_count": len(self.participant_states),
            "replay_required": self.replay_required,
            "resume_allowed": self.resume_allowed,
            "merge_confirmation_required": self.merge_confirmation_required,
            "has_barrier": self.barrier_state is not None,
            "recommended_action_count": len(self.recommended_actions),
            "reason": self.reason,
            "generated_at": self.generated_at,
        }

    def __repr__(self) -> str:
        return (
            f"RuntimeRecoveryIncident("
            f"recovery_id={self.recovery_id!r}, "
            f"incident_type={self.incident_type!r}, "
            f"status={self.status!r})"
        )


class RuntimeReconciliationState(BaseModel):
    """Canonical reconciliation state across source/target/coordinator/result layers.

    Captures the authoritative view of which participants and result units are
    consistent, stale, or pending, along with the overall reconciliation posture.

    Fields
    ------
    reconciliation_id
        Stable, globally-unique identifier for this reconciliation state.
    generated_at
        Unix epoch seconds when this state was assembled.
    recovery_id
        Optional link to the associated :class:`RuntimeRecoveryIncident`.
    trace_id
        Optional execution trace identifier.
    task_id
        Optional task identifier.
    session_id
        Optional runtime session identifier.
    mesh_session_id
        Optional mesh session identifier.
    source_device_id
        Optional source device identifier.
    primary_device_id
        Optional primary device identifier.
    status
        Overall reconciliation status.
    participant_states
        Per-participant reconciliation posture entries.
    authoritative_result_unit_ids
        IDs of result units confirmed as authoritative after reconciliation.
    stale_result_unit_ids
        IDs of result units that are stale and require re-evaluation.
    pending_result_unit_ids
        IDs of result units that are pending confirmation.
    replay_required
        Whether replay of any work is required to reach a consistent state.
    resume_allowed
        Whether local resume is a valid path to reconciliation.
    merge_confirmation_required
        Whether merge confirmation is required to complete reconciliation.
    barrier_state
        Optional barrier state blocking reconciliation.
    recommended_actions
        Advisory list of recommended reconciliation actions.
    incidents
        Related recovery incidents contributing to this reconciliation state.
    reason
        Human-readable summary of the reconciliation posture.
    metadata
        Arbitrary extensibility bag.
    """

    reconciliation_id: str = Field(
        default_factory=lambda: f"rrec_{uuid.uuid4().hex[:12]}",
        description="Stable, globally-unique identifier for this reconciliation state.",
    )
    generated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this state was assembled.",
    )
    recovery_id: Optional[str] = Field(
        default=None,
        description="Optional link to the associated RuntimeRecoveryIncident.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional execution trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Optional runtime session identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Optional mesh session identifier.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Optional source device identifier.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description="Optional primary device identifier.",
    )
    status: str = Field(
        default=RecoveryStatus.pending.value,
        description="Overall reconciliation status.",
    )
    participant_states: List[RecoveryParticipantState] = Field(
        default_factory=list,
        description="Per-participant reconciliation posture entries.",
    )
    authoritative_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units confirmed as authoritative.",
    )
    stale_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units that are stale.",
    )
    pending_result_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units pending confirmation.",
    )
    replay_required: bool = Field(
        default=False,
        description="Whether replay of any work is required.",
    )
    resume_allowed: bool = Field(
        default=False,
        description="Whether local resume is a valid reconciliation path.",
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description="Whether merge confirmation is required.",
    )
    barrier_state: Optional[RecoveryBarrierState] = Field(
        default=None,
        description="Optional barrier state blocking reconciliation.",
    )
    recommended_actions: List[RecoveryActionRecommendation] = Field(
        default_factory=list,
        description="Advisory list of recommended reconciliation actions.",
    )
    incidents: List[RuntimeRecoveryIncident] = Field(
        default_factory=list,
        description="Related recovery incidents contributing to this state.",
    )
    reason: str = Field(
        default="",
        description="Human-readable summary of the reconciliation posture.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeReconciliationState":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a lightweight summary dict for embedding in projections."""
        return {
            "reconciliation_id": self.reconciliation_id,
            "status": self.status,
            "participant_count": len(self.participant_states),
            "authoritative_result_count": len(self.authoritative_result_unit_ids),
            "stale_result_count": len(self.stale_result_unit_ids),
            "pending_result_count": len(self.pending_result_unit_ids),
            "replay_required": self.replay_required,
            "resume_allowed": self.resume_allowed,
            "merge_confirmation_required": self.merge_confirmation_required,
            "incident_count": len(self.incidents),
            "reason": self.reason,
            "generated_at": self.generated_at,
        }

    def __repr__(self) -> str:
        return (
            f"RuntimeReconciliationState("
            f"reconciliation_id={self.reconciliation_id!r}, "
            f"status={self.status!r})"
        )


class RecoverySummary(BaseModel):
    """Lightweight read-only summary of recovery/reconciliation posture.

    This is the primary embedding type for use in unified projections and
    route payloads.  It is intentionally compact — downstream consumers
    needing full detail should use :class:`RuntimeRecoveryIncident` or
    :class:`RuntimeReconciliationState`.

    Fields
    ------
    summary_id
        Stable unique identifier for this summary.
    generated_at
        Unix epoch seconds when this summary was assembled.
    overall_status
        Overall recovery/reconciliation status.
    incident_count
        Total number of recovery incidents detected.
    resolved_incident_count
        Number of incidents that have been resolved.
    pending_incident_count
        Number of incidents that are still pending.
    needs_intervention_count
        Number of incidents requiring manual intervention.
    replay_required
        Whether any incident requires replay.
    resume_allowed
        Whether resume is allowed for any participant.
    merge_confirmation_required
        Whether any merge requires explicit confirmation.
    has_barrier
        Whether any active barrier is blocking recovery progress.
    recommended_action_types
        Deduplicated list of advisory action types across all incidents.
    most_recent_incident_type
        Incident type from the most recently created incident.
    most_recent_recovery_id
        Recovery ID of the most recently created incident.
    reason
        Human-readable summary of overall recovery posture.
    metadata
        Arbitrary extensibility bag.
    """

    summary_id: str = Field(
        default_factory=lambda: f"rrsum_{uuid.uuid4().hex[:10]}",
        description="Stable unique identifier for this summary.",
    )
    generated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this summary was assembled.",
    )
    overall_status: str = Field(
        default=RecoveryStatus.pending.value,
        description="Overall recovery/reconciliation status.",
    )
    incident_count: int = Field(
        default=0,
        description="Total number of recovery incidents detected.",
    )
    resolved_incident_count: int = Field(
        default=0,
        description="Number of incidents that have been resolved.",
    )
    pending_incident_count: int = Field(
        default=0,
        description="Number of incidents that are still pending.",
    )
    needs_intervention_count: int = Field(
        default=0,
        description="Number of incidents requiring manual intervention.",
    )
    replay_required: bool = Field(
        default=False,
        description="Whether any incident requires replay.",
    )
    resume_allowed: bool = Field(
        default=False,
        description="Whether resume is allowed for any participant.",
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description="Whether any merge requires explicit confirmation.",
    )
    has_barrier: bool = Field(
        default=False,
        description="Whether any active barrier is blocking recovery progress.",
    )
    recommended_action_types: List[str] = Field(
        default_factory=list,
        description="Deduplicated list of advisory action types across all incidents.",
    )
    most_recent_incident_type: Optional[str] = Field(
        default=None,
        description="Incident type from the most recently created incident.",
    )
    most_recent_recovery_id: Optional[str] = Field(
        default=None,
        description="Recovery ID of the most recently created incident.",
    )
    reason: str = Field(
        default="",
        description="Human-readable summary of overall recovery posture.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoverySummary":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)

    def __repr__(self) -> str:
        return (
            f"RecoverySummary("
            f"summary_id={self.summary_id!r}, "
            f"overall_status={self.overall_status!r}, "
            f"incident_count={self.incident_count})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    try:
        return list(value)
    except (TypeError, ValueError):
        return []


def _safe_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump()
        except Exception:
            pass
    if hasattr(value, "__dict__"):
        try:
            return dict(value.__dict__)
        except Exception:
            pass
    return {}


def _safe_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return bool(value)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_runtime_recovery_incident(
    *,
    recovery_id: Optional[str] = None,
    incident_type: str = RecoveryIncidentType.unknown.value,
    status: str = RecoveryStatus.pending.value,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    primary_device_id: Optional[str] = None,
    affected_devices: Optional[List[str]] = None,
    affected_runtime_ids: Optional[List[str]] = None,
    participant_states: Optional[List[Any]] = None,
    stale_result_unit_ids: Optional[List[str]] = None,
    authoritative_result_unit_ids: Optional[List[str]] = None,
    pending_result_unit_ids: Optional[List[str]] = None,
    replay_required: bool = False,
    resume_allowed: bool = False,
    merge_confirmation_required: bool = False,
    barrier_state: Optional[Any] = None,
    recommended_actions: Optional[List[Any]] = None,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeRecoveryIncident:
    """Construct a :class:`RuntimeRecoveryIncident` from keyword arguments.

    All parameters are optional (except the implicit factory defaults).  This
    allows callers with partial context to always produce a valid incident.

    Parameters
    ----------
    recovery_id:
        Explicit ID; auto-generated when omitted.
    incident_type:
        Categorical incident type; defaults to ``"unknown"``.
    status:
        Lifecycle status; defaults to ``"pending"``.
    trace_id, task_id, session_id, mesh_session_id:
        Optional context identifiers.
    source_device_id, primary_device_id:
        Optional device identifiers.
    affected_devices, affected_runtime_ids:
        Lists of affected device/runtime IDs.
    participant_states:
        List of :class:`RecoveryParticipantState` objects or dicts.
    stale_result_unit_ids, authoritative_result_unit_ids, pending_result_unit_ids:
        Result unit ID lists.
    replay_required, resume_allowed, merge_confirmation_required:
        Advisory booleans.
    barrier_state:
        Optional :class:`RecoveryBarrierState` or dict.
    recommended_actions:
        List of :class:`RecoveryActionRecommendation` objects or dicts.
    reason:
        Human-readable rationale.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeRecoveryIncident
        A fully valid incident contract.
    """
    parsed_participants: List[RecoveryParticipantState] = []
    for p in _safe_list(participant_states):
        try:
            if isinstance(p, RecoveryParticipantState):
                parsed_participants.append(p)
            else:
                parsed_participants.append(RecoveryParticipantState.from_dict(_safe_dict(p)))
        except Exception as exc:
            _logger.debug("build_runtime_recovery_incident: skipping bad participant: %s", exc)

    parsed_actions: List[RecoveryActionRecommendation] = []
    for a in _safe_list(recommended_actions):
        try:
            if isinstance(a, RecoveryActionRecommendation):
                parsed_actions.append(a)
            else:
                parsed_actions.append(RecoveryActionRecommendation.from_dict(_safe_dict(a)))
        except Exception as exc:
            _logger.debug("build_runtime_recovery_incident: skipping bad action: %s", exc)

    parsed_barrier: Optional[RecoveryBarrierState] = None
    if barrier_state is not None:
        try:
            if isinstance(barrier_state, RecoveryBarrierState):
                parsed_barrier = barrier_state
            else:
                parsed_barrier = RecoveryBarrierState.from_dict(_safe_dict(barrier_state))
        except Exception as exc:
            _logger.debug("build_runtime_recovery_incident: skipping bad barrier: %s", exc)

    kwargs: Dict[str, Any] = {}
    if recovery_id is not None:
        kwargs["recovery_id"] = recovery_id

    return RuntimeRecoveryIncident(
        incident_type=incident_type,
        status=status,
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        mesh_session_id=mesh_session_id,
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        affected_devices=_safe_list(affected_devices),
        affected_runtime_ids=_safe_list(affected_runtime_ids),
        participant_states=parsed_participants,
        stale_result_unit_ids=_safe_list(stale_result_unit_ids),
        authoritative_result_unit_ids=_safe_list(authoritative_result_unit_ids),
        pending_result_unit_ids=_safe_list(pending_result_unit_ids),
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        merge_confirmation_required=merge_confirmation_required,
        barrier_state=parsed_barrier,
        recommended_actions=parsed_actions,
        reason=reason,
        metadata=metadata or {},
        **kwargs,
    )


def build_runtime_reconciliation_state(
    *,
    reconciliation_id: Optional[str] = None,
    recovery_id: Optional[str] = None,
    status: str = RecoveryStatus.pending.value,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    primary_device_id: Optional[str] = None,
    participant_states: Optional[List[Any]] = None,
    authoritative_result_unit_ids: Optional[List[str]] = None,
    stale_result_unit_ids: Optional[List[str]] = None,
    pending_result_unit_ids: Optional[List[str]] = None,
    replay_required: bool = False,
    resume_allowed: bool = False,
    merge_confirmation_required: bool = False,
    barrier_state: Optional[Any] = None,
    recommended_actions: Optional[List[Any]] = None,
    incidents: Optional[List[Any]] = None,
    reason: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeReconciliationState:
    """Construct a :class:`RuntimeReconciliationState` from keyword arguments.

    All parameters are optional.  Callers with partial context always produce
    a valid reconciliation state.

    Returns
    -------
    RuntimeReconciliationState
        A fully valid reconciliation state contract.
    """
    parsed_participants: List[RecoveryParticipantState] = []
    for p in _safe_list(participant_states):
        try:
            if isinstance(p, RecoveryParticipantState):
                parsed_participants.append(p)
            else:
                parsed_participants.append(RecoveryParticipantState.from_dict(_safe_dict(p)))
        except Exception as exc:
            _logger.debug("build_runtime_reconciliation_state: skipping bad participant: %s", exc)

    parsed_actions: List[RecoveryActionRecommendation] = []
    for a in _safe_list(recommended_actions):
        try:
            if isinstance(a, RecoveryActionRecommendation):
                parsed_actions.append(a)
            else:
                parsed_actions.append(RecoveryActionRecommendation.from_dict(_safe_dict(a)))
        except Exception as exc:
            _logger.debug("build_runtime_reconciliation_state: skipping bad action: %s", exc)

    parsed_incidents: List[RuntimeRecoveryIncident] = []
    for i in _safe_list(incidents):
        try:
            if isinstance(i, RuntimeRecoveryIncident):
                parsed_incidents.append(i)
            else:
                parsed_incidents.append(RuntimeRecoveryIncident.from_dict(_safe_dict(i)))
        except Exception as exc:
            _logger.debug("build_runtime_reconciliation_state: skipping bad incident: %s", exc)

    parsed_barrier: Optional[RecoveryBarrierState] = None
    if barrier_state is not None:
        try:
            if isinstance(barrier_state, RecoveryBarrierState):
                parsed_barrier = barrier_state
            else:
                parsed_barrier = RecoveryBarrierState.from_dict(_safe_dict(barrier_state))
        except Exception as exc:
            _logger.debug("build_runtime_reconciliation_state: skipping bad barrier: %s", exc)

    kwargs: Dict[str, Any] = {}
    if reconciliation_id is not None:
        kwargs["reconciliation_id"] = reconciliation_id

    return RuntimeReconciliationState(
        recovery_id=recovery_id,
        status=status,
        trace_id=trace_id,
        task_id=task_id,
        session_id=session_id,
        mesh_session_id=mesh_session_id,
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        participant_states=parsed_participants,
        authoritative_result_unit_ids=_safe_list(authoritative_result_unit_ids),
        stale_result_unit_ids=_safe_list(stale_result_unit_ids),
        pending_result_unit_ids=_safe_list(pending_result_unit_ids),
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        merge_confirmation_required=merge_confirmation_required,
        barrier_state=parsed_barrier,
        recommended_actions=parsed_actions,
        incidents=parsed_incidents,
        reason=reason,
        metadata=metadata or {},
        **kwargs,
    )


def build_recovery_summary(
    incidents: Optional[List[RuntimeRecoveryIncident]] = None,
    reconciliation: Optional[RuntimeReconciliationState] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RecoverySummary:
    """Build a :class:`RecoverySummary` from a list of incidents and/or reconciliation state.

    Parameters
    ----------
    incidents:
        List of :class:`RuntimeRecoveryIncident` objects.  If ``None`` the
        incidents from ``reconciliation`` are used when available.
    reconciliation:
        Optional :class:`RuntimeReconciliationState` to derive summary from.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RecoverySummary
        A compact read-only summary.
    """
    all_incidents: List[RuntimeRecoveryIncident] = list(_safe_list(incidents))
    if reconciliation is not None and not all_incidents:
        all_incidents = list(reconciliation.incidents)

    incident_count = len(all_incidents)
    resolved_count = sum(1 for i in all_incidents if i.status == RecoveryStatus.resolved.value)
    pending_count = sum(1 for i in all_incidents if i.status == RecoveryStatus.pending.value)
    intervention_count = sum(
        1 for i in all_incidents if i.status == RecoveryStatus.needs_intervention.value
    )
    replay_required = any(i.replay_required for i in all_incidents)
    resume_allowed = any(i.resume_allowed for i in all_incidents)
    merge_confirmation_required = any(i.merge_confirmation_required for i in all_incidents)
    has_barrier = any(i.barrier_state is not None for i in all_incidents)

    action_types: List[str] = []
    for i in all_incidents:
        for a in i.recommended_actions:
            if a.action_type not in action_types:
                action_types.append(a.action_type)

    most_recent: Optional[RuntimeRecoveryIncident] = None
    if all_incidents:
        most_recent = max(all_incidents, key=lambda x: x.generated_at)

    # Derive overall status
    if incident_count == 0:
        overall_status = RecoveryStatus.resolved.value
    elif intervention_count > 0:
        overall_status = RecoveryStatus.needs_intervention.value
    elif pending_count > 0:
        overall_status = RecoveryStatus.pending.value
    elif resolved_count == incident_count:
        overall_status = RecoveryStatus.resolved.value
    else:
        overall_status = RecoveryStatus.in_progress.value

    # Override from reconciliation status if available
    if reconciliation is not None:
        rec_status = reconciliation.status
        if rec_status in (
            RecoveryStatus.needs_intervention.value,
            RecoveryStatus.in_progress.value,
        ):
            overall_status = rec_status

    reason_parts: List[str] = []
    if incident_count > 0:
        reason_parts.append(f"{incident_count} incident(s) detected")
    if resolved_count:
        reason_parts.append(f"{resolved_count} resolved")
    if pending_count:
        reason_parts.append(f"{pending_count} pending")
    if intervention_count:
        reason_parts.append(f"{intervention_count} need intervention")
    reason = "; ".join(reason_parts) if reason_parts else "no incidents"

    return RecoverySummary(
        overall_status=overall_status,
        incident_count=incident_count,
        resolved_incident_count=resolved_count,
        pending_incident_count=pending_count,
        needs_intervention_count=intervention_count,
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        merge_confirmation_required=merge_confirmation_required,
        has_barrier=has_barrier,
        recommended_action_types=action_types,
        most_recent_incident_type=(
            most_recent.incident_type if most_recent is not None else None
        ),
        most_recent_recovery_id=(
            most_recent.recovery_id if most_recent is not None else None
        ),
        reason=reason,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Adapters — derive recovery/reconciliation state from existing contracts
# ---------------------------------------------------------------------------


def from_source_dispatch_result(
    dispatch_result: Any,
    *,
    mesh_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeRecoveryIncident:
    """Derive a :class:`RuntimeRecoveryIncident` from a source dispatch result.

    Inspects the dispatch result for failure/partial indicators and produces
    an advisory recovery incident.

    Parameters
    ----------
    dispatch_result:
        A :class:`~contracts.source_dispatch.SourceDispatchResult` instance or
        compatible dict.
    mesh_session_id:
        Optional mesh session ID to associate with the incident.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeRecoveryIncident
        Advisory incident derived from the dispatch result.
    """
    d = _safe_dict(dispatch_result)
    status_val = _safe_str(d.get("status") or d.get("dispatch_status"))
    source_device = _safe_str(d.get("source_device_id") or d.get("source_device"))
    trace_id = d.get("trace_id") or d.get("execution_trace_id")
    task_id = d.get("task_id")
    session_id = d.get("session_id") or d.get("runtime_session_id")

    # Determine incident type and recovery posture from dispatch status
    failed_statuses = {"failed", "timeout", "error", "rejected"}
    partial_statuses = {"partial", "partially_dispatched"}

    if status_val in failed_statuses:
        incident_type = RecoveryIncidentType.dispatch_failure.value
        replay_required = True
        resume_allowed = True
        reason = f"Source dispatch failed with status={status_val!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.retry_handoff.value,
                target_device_id=source_device or None,
                reason=f"Dispatch failed (status={status_val!r}); retry handoff",
            ),
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.fallback_local.value,
                target_device_id=source_device or None,
                reason="Fall back to local execution if retry fails",
            ),
        ]
        rec_status = RecoveryStatus.pending.value
    elif status_val in partial_statuses:
        incident_type = RecoveryIncidentType.partial_completion.value
        replay_required = False
        resume_allowed = True
        reason = f"Source dispatch partially completed (status={status_val!r})"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.resume_local.value,
                target_device_id=source_device or None,
                reason="Partial dispatch; attempt local resume for remaining work",
            ),
        ]
        rec_status = RecoveryStatus.in_progress.value
    else:
        incident_type = RecoveryIncidentType.unknown.value
        replay_required = False
        resume_allowed = False
        reason = f"Dispatch result status={status_val!r}; no recovery needed"
        actions = []
        rec_status = RecoveryStatus.resolved.value

    # Build participant state for source device
    participants: List[RecoveryParticipantState] = []
    if source_device:
        participants.append(
            RecoveryParticipantState(
                device_id=source_device,
                status=rec_status,
                replay_required=replay_required,
                resume_allowed=resume_allowed,
            )
        )

    return build_runtime_recovery_incident(
        incident_type=incident_type,
        status=rec_status,
        trace_id=_safe_str(trace_id) if trace_id else None,
        task_id=_safe_str(task_id) if task_id else None,
        session_id=_safe_str(session_id) if session_id else None,
        mesh_session_id=mesh_session_id,
        source_device_id=source_device or None,
        affected_devices=[source_device] if source_device else [],
        participant_states=participants,
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        recommended_actions=actions,
        reason=reason,
        metadata=metadata or {},
    )


def from_target_takeover_result(
    takeover_result: Any,
    *,
    mesh_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeRecoveryIncident:
    """Derive a :class:`RuntimeRecoveryIncident` from a target takeover result.

    Parameters
    ----------
    takeover_result:
        A :class:`~contracts.local_takeover_result.LocalTakeoverResult` instance
        or compatible dict.
    mesh_session_id:
        Optional mesh session ID.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeRecoveryIncident
        Advisory incident derived from the takeover result.
    """
    d = _safe_dict(takeover_result)
    status_val = _safe_str(d.get("status") or d.get("takeover_status"))
    device_id = _safe_str(d.get("device_id") or d.get("target_device_id"))
    session_ctx = _safe_dict(d.get("session_context") or {})
    session_id = _safe_str(session_ctx.get("session_id") or d.get("session_id"))
    trace_id = d.get("trace_id")
    task_id = d.get("task_id")

    failed_statuses = {"failed", "error", "rejected", "timeout"}
    interrupted_statuses = {"interrupted", "partial", "handoff_interrupted"}

    if status_val in failed_statuses:
        incident_type = RecoveryIncidentType.takeover_failed.value
        replay_required = True
        resume_allowed = False
        rec_status = RecoveryStatus.pending.value
        reason = f"Target takeover failed with status={status_val!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.retry_handoff.value,
                target_device_id=device_id or None,
                reason=f"Takeover failed (status={status_val!r}); retry handoff",
            ),
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.fallback_local.value,
                reason="Fall back to source device local execution",
            ),
        ]
    elif status_val in interrupted_statuses:
        incident_type = RecoveryIncidentType.handoff_interrupted.value
        replay_required = False
        resume_allowed = True
        rec_status = RecoveryStatus.in_progress.value
        reason = f"Target takeover interrupted (status={status_val!r})"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.resume_local.value,
                target_device_id=device_id or None,
                reason="Interrupted takeover; attempt resume on target",
            ),
        ]
    else:
        incident_type = RecoveryIncidentType.unknown.value
        replay_required = False
        resume_allowed = False
        rec_status = RecoveryStatus.resolved.value
        reason = f"Takeover result status={status_val!r}; no recovery needed"
        actions = []

    participants: List[RecoveryParticipantState] = []
    if device_id:
        participants.append(
            RecoveryParticipantState(
                device_id=device_id,
                status=rec_status,
                replay_required=replay_required,
                resume_allowed=resume_allowed,
            )
        )

    return build_runtime_recovery_incident(
        incident_type=incident_type,
        status=rec_status,
        trace_id=_safe_str(trace_id) if trace_id else None,
        task_id=_safe_str(task_id) if task_id else None,
        session_id=session_id or None,
        mesh_session_id=mesh_session_id,
        affected_devices=[device_id] if device_id else [],
        participant_states=participants,
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        recommended_actions=actions,
        reason=reason,
        metadata=metadata or {},
    )


def from_mesh_session_coordinator(
    coordinator: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeRecoveryIncident:
    """Derive a :class:`RuntimeRecoveryIncident` from a mesh session coordinator state.

    Parameters
    ----------
    coordinator:
        A :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        instance or compatible dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeRecoveryIncident
        Advisory incident derived from coordinator state.
    """
    d = _safe_dict(coordinator)
    coord_status = _safe_str(d.get("status") or d.get("coordinator_status"))
    mesh_session_id = _safe_str(d.get("mesh_session_id") or d.get("session_id"))
    source_device_id = d.get("source_device_id")
    primary_device_id = d.get("primary_device_id")
    coordinator_id = d.get("coordinator_id")

    # Collect affected devices from participants
    affected_devices: List[str] = []
    participants_raw = _safe_list(d.get("participants") or [])
    participant_states: List[RecoveryParticipantState] = []
    for p in participants_raw:
        pd = _safe_dict(p)
        dev_id = _safe_str(pd.get("device_id"))
        p_status = _safe_str(pd.get("status") or "unknown")
        if dev_id:
            affected_devices.append(dev_id)
            participant_states.append(
                RecoveryParticipantState(
                    device_id=dev_id,
                    status=(
                        RecoveryStatus.needs_intervention.value
                        if p_status in ("failed", "error", "lost")
                        else RecoveryStatus.pending.value
                    ),
                    replay_required=p_status in ("failed", "error"),
                    resume_allowed=p_status in ("pending", "partial"),
                )
            )

    error_statuses = {"error", "failed", "coordinator_lost", "terminated"}
    degraded_statuses = {"degraded", "barrier_blocked", "stale"}

    if coord_status in error_statuses:
        incident_type = RecoveryIncidentType.coordinator_lost.value
        rec_status = RecoveryStatus.needs_intervention.value
        replay_required = True
        reason = f"Mesh coordinator entered error state: status={coord_status!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.repair_mesh_session.value,
                reason=f"Coordinator status={coord_status!r}; repair mesh session",
            ),
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.escalate.value,
                reason="Coordinator lost; escalate for manual intervention",
            ),
        ]
    elif coord_status in degraded_statuses:
        incident_type = RecoveryIncidentType.session_diverged.value
        rec_status = RecoveryStatus.in_progress.value
        replay_required = False
        reason = f"Mesh coordinator degraded: status={coord_status!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.repair_mesh_session.value,
                reason=f"Coordinator degraded (status={coord_status!r}); attempt repair",
            ),
        ]
    else:
        incident_type = RecoveryIncidentType.unknown.value
        rec_status = RecoveryStatus.resolved.value
        replay_required = False
        reason = f"Coordinator status={coord_status!r}; no recovery needed"
        actions = []

    return build_runtime_recovery_incident(
        incident_type=incident_type,
        status=rec_status,
        mesh_session_id=mesh_session_id or None,
        source_device_id=_safe_str(source_device_id) if source_device_id else None,
        primary_device_id=_safe_str(primary_device_id) if primary_device_id else None,
        affected_devices=affected_devices,
        participant_states=participant_states,
        replay_required=replay_required,
        recommended_actions=actions,
        reason=reason,
        metadata=dict(metadata or {}, coordinator_id=_safe_str(coordinator_id)),
    )


def from_merged_runtime_result(
    merged_result: Any,
    *,
    mesh_session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeRecoveryIncident:
    """Derive a :class:`RuntimeRecoveryIncident` from a merged runtime result.

    Parameters
    ----------
    merged_result:
        A :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`
        instance or compatible dict.
    mesh_session_id:
        Optional mesh session ID.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeRecoveryIncident
        Advisory incident derived from the merged result.
    """
    d = _safe_dict(merged_result)
    merge_status = _safe_str(d.get("status") or d.get("merge_status"))
    source_device_id = d.get("source_device_id")
    primary_device_id = d.get("primary_device_id")
    result_units_raw = _safe_list(d.get("result_units") or [])

    stale_ids: List[str] = []
    authoritative_ids: List[str] = []
    pending_ids: List[str] = []

    for unit in result_units_raw:
        ud = _safe_dict(unit)
        uid = _safe_str(ud.get("unit_id") or ud.get("result_unit_id"))
        unit_status = _safe_str(ud.get("status") or "unknown")
        if not uid:
            continue
        if unit_status in ("stale", "superseded", "rejected"):
            stale_ids.append(uid)
        elif unit_status in ("authoritative", "confirmed", "merged"):
            authoritative_ids.append(uid)
        elif unit_status in ("pending", "partial", "in_progress"):
            pending_ids.append(uid)

    conflict_statuses = {"conflict", "merge_conflict", "diverged"}
    failed_statuses = {"failed", "error"}
    incomplete_statuses = {"partial", "incomplete", "pending"}

    if merge_status in conflict_statuses:
        incident_type = RecoveryIncidentType.merge_conflict.value
        rec_status = RecoveryStatus.needs_intervention.value
        merge_confirmation_required = True
        replay_required = False
        reason = f"Cross-runtime result merge detected conflict: status={merge_status!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.request_merge_confirmation.value,
                reason="Merge conflict detected; request explicit confirmation",
            ),
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.mark_stale.value,
                reason="Mark conflicting result units as stale pending resolution",
            ),
        ]
    elif merge_status in failed_statuses:
        incident_type = RecoveryIncidentType.partial_completion.value
        rec_status = RecoveryStatus.pending.value
        merge_confirmation_required = False
        replay_required = True
        reason = f"Cross-runtime result merge failed: status={merge_status!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.replay_assignment.value,
                reason="Merge failed; replay assignments for failed units",
            ),
        ]
    elif merge_status in incomplete_statuses:
        incident_type = RecoveryIncidentType.partial_completion.value
        rec_status = RecoveryStatus.in_progress.value
        merge_confirmation_required = False
        replay_required = False
        reason = f"Cross-runtime result merge incomplete: status={merge_status!r}"
        actions = [
            RecoveryActionRecommendation(
                action_type=RecoveryActionType.wait_for_participant.value,
                reason="Merge pending; wait for outstanding participants",
            ),
        ]
    else:
        incident_type = RecoveryIncidentType.unknown.value
        rec_status = RecoveryStatus.resolved.value
        merge_confirmation_required = False
        replay_required = False
        reason = f"Merge result status={merge_status!r}; no recovery needed"
        actions = []

    return build_runtime_recovery_incident(
        incident_type=incident_type,
        status=rec_status,
        mesh_session_id=mesh_session_id,
        source_device_id=_safe_str(source_device_id) if source_device_id else None,
        primary_device_id=_safe_str(primary_device_id) if primary_device_id else None,
        stale_result_unit_ids=stale_ids,
        authoritative_result_unit_ids=authoritative_ids,
        pending_result_unit_ids=pending_ids,
        replay_required=replay_required,
        merge_confirmation_required=merge_confirmation_required,
        recommended_actions=actions,
        reason=reason,
        metadata=metadata or {},
    )


def from_multi_device_projection(
    projection: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeReconciliationState:
    """Derive a :class:`RuntimeReconciliationState` from a unified multi-device projection.

    Inspects all embedded contract blocks (dispatch, takeover, coordinator,
    merged results) to construct a holistic reconciliation view.

    Parameters
    ----------
    projection:
        A :class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`
        instance or compatible dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeReconciliationState
        Advisory reconciliation state derived from the full projection.
    """
    d = _safe_dict(projection)
    incidents: List[RuntimeRecoveryIncident] = []

    # Inspect source dispatches
    for dispatch in _safe_list(d.get("source_dispatches") or []):
        try:
            incident = from_source_dispatch_result(dispatch)
            if incident.status != RecoveryStatus.resolved.value:
                incidents.append(incident)
        except Exception as exc:
            _logger.debug("from_multi_device_projection: dispatch incident error: %s", exc)

    # Inspect takeover summaries
    for takeover in _safe_list(d.get("takeover_summaries") or []):
        try:
            incident = from_target_takeover_result(takeover)
            if incident.status != RecoveryStatus.resolved.value:
                incidents.append(incident)
        except Exception as exc:
            _logger.debug("from_multi_device_projection: takeover incident error: %s", exc)

    # Inspect coordinator summaries
    for coordinator in _safe_list(d.get("coordinator_summaries") or []):
        try:
            incident = from_mesh_session_coordinator(coordinator)
            if incident.status != RecoveryStatus.resolved.value:
                incidents.append(incident)
        except Exception as exc:
            _logger.debug("from_multi_device_projection: coordinator incident error: %s", exc)

    # Inspect merged results
    for merged in _safe_list(d.get("merged_results") or []):
        try:
            incident = from_merged_runtime_result(merged)
            if incident.status != RecoveryStatus.resolved.value:
                incidents.append(incident)
        except Exception as exc:
            _logger.debug("from_multi_device_projection: merge incident error: %s", exc)

    # Determine overall reconciliation status
    if not incidents:
        overall_status = RecoveryStatus.resolved.value
        reason = "All projection blocks healthy; no incidents detected"
    elif any(i.status == RecoveryStatus.needs_intervention.value for i in incidents):
        overall_status = RecoveryStatus.needs_intervention.value
        reason = f"{len(incidents)} incident(s) detected; manual intervention required"
    elif any(i.status == RecoveryStatus.in_progress.value for i in incidents):
        overall_status = RecoveryStatus.in_progress.value
        reason = f"{len(incidents)} incident(s) in recovery"
    else:
        overall_status = RecoveryStatus.pending.value
        reason = f"{len(incidents)} pending incident(s) detected in projection"

    replay_required = any(i.replay_required for i in incidents)
    resume_allowed = any(i.resume_allowed for i in incidents)
    merge_confirmation_required = any(i.merge_confirmation_required for i in incidents)

    all_actions: List[RecoveryActionRecommendation] = []
    for i in incidents:
        all_actions.extend(i.recommended_actions)

    return build_runtime_reconciliation_state(
        status=overall_status,
        replay_required=replay_required,
        resume_allowed=resume_allowed,
        merge_confirmation_required=merge_confirmation_required,
        recommended_actions=all_actions,
        incidents=incidents,
        reason=reason,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "RecoveryIncidentType",
    "RecoveryStatus",
    "RecoveryActionType",
    # Sub-contracts
    "RecoveryParticipantState",
    "RecoveryActionRecommendation",
    "RecoveryBarrierState",
    # Top-level contracts
    "RuntimeRecoveryIncident",
    "RuntimeReconciliationState",
    "RecoverySummary",
    # Builders
    "build_runtime_recovery_incident",
    "build_runtime_reconciliation_state",
    "build_recovery_summary",
    # Adapters
    "from_source_dispatch_result",
    "from_target_takeover_result",
    "from_mesh_session_coordinator",
    "from_merged_runtime_result",
    "from_multi_device_projection",
]
