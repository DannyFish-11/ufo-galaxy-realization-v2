"""core/ugcp_coordination_profile.py
======================================
UGCP Coordination Profile v1 (realization-v2 side, PR-6 scope).

This module freezes a canonical coordination vocabulary for mesh/session
coordination semantics while preserving existing behavior in current contracts.
It provides mapping and normalization helpers so mesh/coordinator surfaces can
be interpreted under one authority/lifecycle model and bridged into truth and
durable state views.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Set

from core.schemas.ugcp.shared import TruthEvent

UGCP_COORDINATION_PROFILE_AUTHORITY: str = (
    "UGCP_COORDINATION_PROFILE_AUTHORITY::"
    "core.ugcp_coordination_profile is the canonical mapping authority for "
    "mesh/coordinator coordination semantics in realization-v2."
)

COORDINATION_VOCABULARY_IS_FROZEN_POLICY: str = (
    "COORDINATION_PROFILE_POLICY::COORDINATION_VOCABULARY_IS_FROZEN: "
    "Coordination terminology must use the canonical enums in this module "
    "for lifecycle, participant role, authority scope, and terminal outcomes."
)

COORDINATION_AUTHORITY_MODEL_IS_CANONICAL_POLICY: str = (
    "COORDINATION_PROFILE_POLICY::COORDINATION_AUTHORITY_MODEL_IS_CANONICAL: "
    "Mesh/coordinator authority must be normalized through CoordinationAuthorityScope."
)

COORDINATION_STATE_GRAPH_IS_CANONICAL_POLICY: str = (
    "COORDINATION_PROFILE_POLICY::COORDINATION_STATE_GRAPH_IS_CANONICAL: "
    "Allowed coordination transitions must follow COORDINATION_ALLOWED_TRANSITIONS."
)

COORDINATION_TRUTH_AND_DURABLE_MAPPING_POLICY: str = (
    "COORDINATION_PROFILE_POLICY::COORDINATION_TRUTH_AND_DURABLE_MAPPING: "
    "Coordination transitions should be emitted via build_coordination_truth_event() "
    "and represented durably via build_coordination_durable_snapshot()."
)

UGCP_COORDINATION_PROFILE_PR6_SENTINEL: str = (
    "UGCP_COORDINATION_PROFILE_PR6_SENTINEL::package=6::"
    "profile=ugcp-coordination-v1::module=core.ugcp_coordination_profile"
)


class CoordinationLifecycleState(str, Enum):
    pending = "pending"
    active = "active"
    awaiting_barrier = "awaiting_barrier"
    merging = "merging"
    completed = "completed"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"
    unknown = "unknown"

    def is_terminal(self) -> bool:
        return self in {
            CoordinationLifecycleState.completed,
            CoordinationLifecycleState.partial,
            CoordinationLifecycleState.failed,
            CoordinationLifecycleState.cancelled,
            CoordinationLifecycleState.timed_out,
        }


class CoordinationParticipantRole(str, Enum):
    primary = "primary"
    source = "source"
    support = "support"
    merge_owner = "merge_owner"
    fallback = "fallback"
    relay = "relay"
    observer = "observer"
    participant = "participant"
    unknown = "unknown"


class CoordinationAuthorityScope(str, Enum):
    mesh_authority = "mesh_authority"
    execution_authority = "execution_authority"
    merge_authority = "merge_authority"
    barrier_authority = "barrier_authority"
    observation_only = "observation_only"
    shared = "shared"
    unknown = "unknown"


class CoordinationBarrierSemantics(str, Enum):
    not_required = "not_required"
    open = "open"
    waiting = "waiting"
    released = "released"
    failed = "failed"
    unknown = "unknown"


class CoordinationAggregationSemantics(str, Enum):
    no_merge = "no_merge"
    sequential = "sequential"
    parallel = "parallel"
    barrier = "barrier"
    owner_decides = "owner_decides"
    unknown = "unknown"


class CoordinationTerminalOutcome(str, Enum):
    none = ""
    completed = "completed"
    partial = "partial"
    failed = "failed"
    cancelled = "cancelled"
    timed_out = "timed_out"
    barrier_failed = "barrier_failed"
    merge_failed = "merge_failed"
    quorum_not_met = "quorum_not_met"
    participant_unavailable = "participant_unavailable"
    unknown = "unknown"


_COORDINATION_TERMINAL_REASON_VALUES = {item.value for item in CoordinationTerminalOutcome}
_COORDINATION_STATE_ALIASES: Dict[str, str] = {
    "waiting": CoordinationLifecycleState.awaiting_barrier.value,
    "cancelled_by_policy": CoordinationLifecycleState.cancelled.value,
}


COORDINATION_ALLOWED_TRANSITIONS: Dict[CoordinationLifecycleState, Set[CoordinationLifecycleState]] = {
    CoordinationLifecycleState.pending: {
        CoordinationLifecycleState.active,
        CoordinationLifecycleState.cancelled,
        CoordinationLifecycleState.failed,
    },
    CoordinationLifecycleState.active: {
        CoordinationLifecycleState.awaiting_barrier,
        CoordinationLifecycleState.merging,
        CoordinationLifecycleState.completed,
        CoordinationLifecycleState.partial,
        CoordinationLifecycleState.failed,
        CoordinationLifecycleState.cancelled,
        CoordinationLifecycleState.timed_out,
    },
    CoordinationLifecycleState.awaiting_barrier: {
        CoordinationLifecycleState.active,
        CoordinationLifecycleState.merging,
        CoordinationLifecycleState.completed,
        CoordinationLifecycleState.partial,
        CoordinationLifecycleState.failed,
        CoordinationLifecycleState.cancelled,
        CoordinationLifecycleState.timed_out,
    },
    CoordinationLifecycleState.merging: {
        CoordinationLifecycleState.completed,
        CoordinationLifecycleState.partial,
        CoordinationLifecycleState.failed,
        CoordinationLifecycleState.cancelled,
        CoordinationLifecycleState.timed_out,
    },
    CoordinationLifecycleState.completed: set(),
    CoordinationLifecycleState.partial: set(),
    CoordinationLifecycleState.failed: set(),
    CoordinationLifecycleState.cancelled: set(),
    CoordinationLifecycleState.timed_out: set(),
    CoordinationLifecycleState.unknown: set(),
}


@dataclass(frozen=True)
class CoordinationTransition:
    from_state: CoordinationLifecycleState
    to_state: CoordinationLifecycleState
    authority_scope: CoordinationAuthorityScope = CoordinationAuthorityScope.unknown
    role: CoordinationParticipantRole = CoordinationParticipantRole.participant
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    mesh_session_id: Optional[str] = None
    coordinator_id: Optional[str] = None
    barrier: CoordinationBarrierSemantics = CoordinationBarrierSemantics.unknown
    aggregation: CoordinationAggregationSemantics = CoordinationAggregationSemantics.unknown
    quorum_reached: Optional[bool] = None
    terminal_outcome: CoordinationTerminalOutcome = CoordinationTerminalOutcome.none
    source_contract: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_truth_event(self) -> TruthEvent:
        return build_coordination_truth_event(
            current_state=self.to_state,
            previous_state=self.from_state,
            authority_scope=self.authority_scope,
            role=self.role,
            trace_id=self.trace_id,
            task_id=self.task_id,
            control_session_id=self.control_session_id,
            runtime_session_id=self.runtime_session_id,
            mesh_session_id=self.mesh_session_id,
            coordinator_id=self.coordinator_id,
            barrier=self.barrier,
            aggregation=self.aggregation,
            quorum_reached=self.quorum_reached,
            terminal_outcome=self.terminal_outcome,
            source_contract=self.source_contract,
            metadata={**self.metadata, "transition_timestamp": self.timestamp},
        )


def _normalize_state(raw: Any) -> CoordinationLifecycleState:
    if isinstance(raw, CoordinationLifecycleState):
        return raw
    if not isinstance(raw, str):
        return CoordinationLifecycleState.unknown
    normalized = raw.strip().lower()
    normalized = _COORDINATION_STATE_ALIASES.get(normalized, normalized)
    try:
        return CoordinationLifecycleState(normalized)
    except ValueError:
        return CoordinationLifecycleState.unknown


def _normalize_enum(raw: Any, enum_type: Any, *, alias: Optional[Mapping[str, str]] = None) -> Any:
    if isinstance(raw, enum_type):
        return raw
    if not isinstance(raw, str):
        return enum_type.unknown
    normalized = raw.strip().lower()
    if alias:
        normalized = alias.get(normalized, normalized)
    try:
        return enum_type(normalized)
    except ValueError:
        return enum_type.unknown


def can_transition(from_state: Any, to_state: Any) -> bool:
    source = _normalize_state(from_state)
    target = _normalize_state(to_state)
    return target in COORDINATION_ALLOWED_TRANSITIONS.get(source, set())


def map_from_mesh_session_status(status: Any) -> CoordinationLifecycleState:
    return _normalize_state(status)


def map_from_coordinator_status(status: Any) -> CoordinationLifecycleState:
    return _normalize_state(status)


def map_from_participant_role(role: Any) -> CoordinationParticipantRole:
    return _normalize_enum(role, CoordinationParticipantRole, alias={"merge-owner": "merge_owner"})


def map_from_authority_scope(scope: Any) -> CoordinationAuthorityScope:
    return _normalize_enum(
        scope,
        CoordinationAuthorityScope,
        alias={
            "observer": "observation_only",
            "observer_only": "observation_only",
        },
    )


def map_from_barrier_status(status: Any) -> CoordinationBarrierSemantics:
    return _normalize_enum(
        status,
        CoordinationBarrierSemantics,
        alias={"none": "not_required"},
    )


def map_from_aggregation_mode(mode: Any) -> CoordinationAggregationSemantics:
    return _normalize_enum(mode, CoordinationAggregationSemantics)


def infer_terminal_outcome(state: Any, raw_reason: Optional[str] = None) -> CoordinationTerminalOutcome:
    if isinstance(raw_reason, str):
        normalized_reason = raw_reason.strip().lower()
        if normalized_reason in _COORDINATION_TERMINAL_REASON_VALUES:
            return CoordinationTerminalOutcome(normalized_reason)
        reason_alias = {
            "barrier_timeout": CoordinationTerminalOutcome.timed_out,
            "participant_offline": CoordinationTerminalOutcome.participant_unavailable,
            "merge_error": CoordinationTerminalOutcome.merge_failed,
        }
        if normalized_reason in reason_alias:
            return reason_alias[normalized_reason]

    lifecycle = _normalize_state(state)
    fallback = {
        CoordinationLifecycleState.completed: CoordinationTerminalOutcome.completed,
        CoordinationLifecycleState.partial: CoordinationTerminalOutcome.partial,
        CoordinationLifecycleState.failed: CoordinationTerminalOutcome.failed,
        CoordinationLifecycleState.cancelled: CoordinationTerminalOutcome.cancelled,
        CoordinationLifecycleState.timed_out: CoordinationTerminalOutcome.timed_out,
    }
    return fallback.get(lifecycle, CoordinationTerminalOutcome.none)


def build_coordination_truth_event(
    *,
    current_state: CoordinationLifecycleState,
    previous_state: Optional[CoordinationLifecycleState] = None,
    authority_scope: CoordinationAuthorityScope = CoordinationAuthorityScope.unknown,
    role: CoordinationParticipantRole = CoordinationParticipantRole.participant,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    control_session_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    coordinator_id: Optional[str] = None,
    barrier: CoordinationBarrierSemantics = CoordinationBarrierSemantics.unknown,
    aggregation: CoordinationAggregationSemantics = CoordinationAggregationSemantics.unknown,
    quorum_reached: Optional[bool] = None,
    terminal_outcome: CoordinationTerminalOutcome = CoordinationTerminalOutcome.none,
    source_contract: str = "",
    metadata: Optional[Mapping[str, Any]] = None,
) -> TruthEvent:
    return TruthEvent(
        event_type="ugcp.coordination.transition.v1",
        trace_id=trace_id,
        task_id=task_id,
        control_session_id=control_session_id,
        runtime_session_id=runtime_session_id,
        payload={
            "profile": "ugcp_coordination_v1",
            "mesh_session_id": mesh_session_id,
            "coordinator_id": coordinator_id,
            "current_state": current_state.value,
            "previous_state": previous_state.value if previous_state else None,
            "is_terminal": current_state.is_terminal(),
            "role": role.value,
            "authority_scope": authority_scope.value,
            "barrier": barrier.value,
            "aggregation": aggregation.value,
            "quorum_reached": quorum_reached,
            "terminal_outcome": terminal_outcome.value,
            "source_contract": source_contract,
            "metadata": dict(metadata or {}),
        },
    )


def build_coordination_durable_snapshot(
    *,
    mesh_session_id: Optional[str],
    coordinator_id: Optional[str],
    state: CoordinationLifecycleState,
    authority_scope: CoordinationAuthorityScope = CoordinationAuthorityScope.unknown,
    barrier: CoordinationBarrierSemantics = CoordinationBarrierSemantics.unknown,
    aggregation: CoordinationAggregationSemantics = CoordinationAggregationSemantics.unknown,
    quorum_reached: Optional[bool] = None,
    terminal_outcome: CoordinationTerminalOutcome = CoordinationTerminalOutcome.none,
    metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "profile": "ugcp_coordination_v1",
        "mesh_session_id": mesh_session_id,
        "coordinator_id": coordinator_id,
        "coordination_state": state.value,
        "is_terminal": state.is_terminal(),
        "authority_scope": authority_scope.value,
        "barrier": barrier.value,
        "aggregation": aggregation.value,
        "quorum_reached": quorum_reached,
        "terminal_outcome": terminal_outcome.value,
        "timestamp": time.time(),
        "metadata": dict(metadata or {}),
    }


def build_coordination_merge_reason(
    state: CoordinationLifecycleState,
    terminal_outcome: CoordinationTerminalOutcome = CoordinationTerminalOutcome.none,
) -> str:
    if terminal_outcome.value:
        return f"ugcp_coordination_v1:{state.value}:{terminal_outcome.value}"
    return f"ugcp_coordination_v1:{state.value}"


__all__ = [
    "UGCP_COORDINATION_PROFILE_AUTHORITY",
    "COORDINATION_VOCABULARY_IS_FROZEN_POLICY",
    "COORDINATION_AUTHORITY_MODEL_IS_CANONICAL_POLICY",
    "COORDINATION_STATE_GRAPH_IS_CANONICAL_POLICY",
    "COORDINATION_TRUTH_AND_DURABLE_MAPPING_POLICY",
    "UGCP_COORDINATION_PROFILE_PR6_SENTINEL",
    "CoordinationLifecycleState",
    "CoordinationParticipantRole",
    "CoordinationAuthorityScope",
    "CoordinationBarrierSemantics",
    "CoordinationAggregationSemantics",
    "CoordinationTerminalOutcome",
    "COORDINATION_ALLOWED_TRANSITIONS",
    "CoordinationTransition",
    "can_transition",
    "map_from_mesh_session_status",
    "map_from_coordinator_status",
    "map_from_participant_role",
    "map_from_authority_scope",
    "map_from_barrier_status",
    "map_from_aggregation_mode",
    "infer_terminal_outcome",
    "build_coordination_truth_event",
    "build_coordination_durable_snapshot",
    "build_coordination_merge_reason",
]
