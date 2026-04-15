#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UGCP shared schema family (realization-v2 side).

This module introduces an incremental canonical schema layer for shared
identity/control/runtime/coordination/truth objects. It does not replace all
existing contracts yet; it provides stable canonical objects and lightweight
mapping shims from current key contracts.

Canonical naming note (cross-repo baseline):
- ``participant``: real runtime/system participant identity.
- ``graph_node``: topology/task-model node identity (non-participant).
- ``conversation_session``: conversation/history continuity semantics.
- ``runtime_attachment_session``: runtime attach/reconnect identity semantics.
- ``delegation_transfer_session``: transfer/delegation lifecycle semantics.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY: str = (
    "UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY::core.schemas.ugcp.shared is the canonical "
    "shared schema family for identity/control/runtime/coordination/truth objects "
    "on the realization-v2 side."
)

UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL: str = (
    "UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL::namespace=core.schemas.ugcp "
    "module=core.schemas.ugcp.shared"
)

UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL: str = (
    "UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL::"
    "participant_device_runtime_capability_and_session_strata_are_explicit"
)

UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL: str = (
    "UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL::"
    "participant_identity_runtime_tier_autonomy_coordination_readiness_support_surfaces"
)

UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL: str = (
    "UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL::"
    "full_runtime_host_partial_runtime_node_command_endpoint_observer_endpoint"
)

# Canonical terminal states accepted by the incremental UGCP truth model.
_VALID_TERMINAL_STATES = {"completed", "failed", "partial", "interrupted"}


def _pick(obj: Any, *names: str, default: Any = None) -> Any:
    """Return the first non-None value from a dict/object across candidate names."""
    if isinstance(obj, dict):
        for name in names:
            value = obj.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        value = getattr(obj, name, None)
        if value is not None:
            return value
    return default


def _to_json_dict(instance: Any) -> Dict[str, Any]:
    return dataclasses.asdict(instance)


def _first_target(obj: Any) -> Optional[str]:
    """Return the first target id when a ``targets`` list is present."""
    targets = _pick(obj, "targets", default=[])
    if isinstance(targets, list) and targets:
        first = targets[0]
        return first if isinstance(first, str) else None
    return None


def normalize_runtime_participant_id(obj: Any) -> Optional[str]:
    """Resolve runtime participant identity from canonical/compat keys."""
    value = _pick(obj, "participant_id", "runtime_participant_id")
    return str(value) if value is not None else None


def normalize_graph_node_id(obj: Any) -> Optional[str]:
    """Resolve graph/topology node identity from canonical/compat keys."""
    value = _pick(obj, "graph_node_id", "node_id")
    return str(value) if value is not None else None


def normalize_conversation_session_id(obj: Any) -> Optional[str]:
    """Resolve conversation/history continuity session identity."""
    value = _pick(obj, "conversation_session_id", "control_session_id", "session_id")
    return str(value) if value is not None else None


def normalize_runtime_attachment_session_id(obj: Any) -> Optional[str]:
    """Resolve runtime attachment/reconnect session identity."""
    value = _pick(obj, "runtime_attachment_session_id", "runtime_session_id", "attached_session_id")
    return str(value) if value is not None else None


def normalize_delegation_transfer_session_id(obj: Any) -> Optional[str]:
    """Resolve delegation/transfer session identity."""
    value = _pick(obj, "delegation_transfer_session_id", "transfer_session_id", "handoff_session_id")
    return str(value) if value is not None else None


# ---------------------------------------------------------------------------
# Identity objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskId:
    value: str


@dataclass(frozen=True)
class TraceId:
    value: str


@dataclass(frozen=True)
class ParticipantId:
    value: str


@dataclass(frozen=True)
class DeviceId:
    value: str


@dataclass(frozen=True)
class RuntimeId:
    value: str


@dataclass(frozen=True)
class CapabilityId:
    value: str


@dataclass(frozen=True)
class ConversationSessionId:
    value: str


@dataclass(frozen=True)
class RuntimeAttachmentSessionId:
    value: str


@dataclass(frozen=True)
class DelegationTransferSessionId:
    value: str


@dataclass(frozen=True)
class ControlSessionId:
    """Compatibility alias for conversation/control continuity session identity."""
    value: str


@dataclass(frozen=True)
class RuntimeSessionId:
    """Compatibility alias for runtime attachment session identity."""
    value: str


@dataclass(frozen=True)
class MeshSessionId:
    value: str


@dataclass(frozen=True)
class NodeId:
    """Compatibility node identifier.

    Use :class:`ParticipantId` for runtime/system participants and
    :class:`GraphNodeId` for topology/task-model nodes when introducing new
    schema surfaces.
    """
    value: str


@dataclass(frozen=True)
class GraphNodeId:
    value: str


@dataclass(frozen=True)
class ExecutionInstanceId:
    value: str


# ---------------------------------------------------------------------------
# Control objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskEnvelope:
    task_id: str
    trace_id: str
    control_session_id: Optional[str] = None
    source_node_id: Optional[str] = None
    target_node_id: Optional[str] = None
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class DispatchDecision:
    execution_instance_id: Optional[str] = None
    dispatch_mode: str = ""
    effective_mode: str = ""
    decision_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class Assignment:
    task_id: str
    runtime_session_id: Optional[str] = None
    source_node_id: Optional[str] = None
    target_node_id: Optional[str] = None
    dispatch_decision: Optional[DispatchDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class ExecutionLease:
    task_id: str
    owner_node_id: Optional[str] = None
    lease_status: str = "active"
    lease_expires_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class HandoffRequest:
    task_id: Optional[str] = None
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    source_node_id: Optional[str] = None
    target_node_id: Optional[str] = None
    handoff_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class TakeoverDecision:
    task_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    accepted: bool = False
    takeover_reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


# ---------------------------------------------------------------------------
# Runtime objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RuntimeTarget:
    node_id: Optional[str] = None
    device_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    runtime_type: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class CapabilityProfile:
    runtime_session_id: Optional[str] = None
    capability_tier: str = "unknown"
    capabilities: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class ReadinessProfile:
    runtime_session_id: Optional[str] = None
    readiness_verdict: str = "unknown"
    readiness_reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class RuntimePosture:
    runtime_session_id: Optional[str] = None
    source_runtime_posture: str = "control_only"
    coordination_role: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class DiagnosticsReport:
    runtime_session_id: Optional[str] = None
    report_kind: str = "runtime"
    summary: str = ""
    diagnostics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


class ParticipantKind(str, Enum):
    DEVICE_RUNTIME_HOST = "device_runtime_host"
    SPECIALIZED_NODE = "specialized_node"
    SERVICE_NODE = "service_node"
    TOOL_ENDPOINT = "tool_endpoint"
    OBSERVER = "observer"


class ParticipantRuntimeTier(str, Enum):
    FULL_RUNTIME = "full_runtime"
    PARTIAL_RUNTIME = "partial_runtime"
    COMMAND_ONLY = "command_only"
    OBSERVER_ONLY = "observer_only"


class ParticipantTier(str, Enum):
    FULL_RUNTIME_HOST = "full_runtime_host"
    PARTIAL_RUNTIME_NODE = "partial_runtime_node"
    COMMAND_ENDPOINT = "command_endpoint"
    OBSERVER_ENDPOINT = "observer_endpoint"


class ParticipantAutonomyLevel(str, Enum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    SUPERVISED = "supervised"
    AUTONOMOUS = "autonomous"


class ParticipantState(str, Enum):
    UNKNOWN = "unknown"
    REGISTERED = "registered"
    READY = "ready"
    ACTIVE = "active"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class ParticipantModel:
    """Canonical system participant abstraction (additive/compat-safe)."""

    participant_id: str
    participant_kind: ParticipantKind = ParticipantKind.SPECIALIZED_NODE
    runtime_tier: ParticipantRuntimeTier = ParticipantRuntimeTier.PARTIAL_RUNTIME
    participant_tier: ParticipantTier = ParticipantTier.PARTIAL_RUNTIME_NODE
    autonomy_level: ParticipantAutonomyLevel = ParticipantAutonomyLevel.SUPERVISED
    coordination_role: str = ""
    participation_state: ParticipantState = ParticipantState.UNKNOWN
    supports_local_execution: bool = False
    supports_delegation: bool = False
    supports_attached_session: bool = False
    supports_capability_linkage: bool = False
    supports_device_linkage: bool = False
    node_class: str = ""
    device_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    capability_refs: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "participant_kind": self.participant_kind.value,
            "runtime_tier": self.runtime_tier.value,
            "participant_tier": self.participant_tier.value,
            "autonomy_level": self.autonomy_level.value,
            "coordination_role": self.coordination_role,
            "participation_state": self.participation_state.value,
            "supports_local_execution": self.supports_local_execution,
            "supports_delegation": self.supports_delegation,
            "supports_attached_session": self.supports_attached_session,
            "supports_capability_linkage": self.supports_capability_linkage,
            "supports_device_linkage": self.supports_device_linkage,
            "node_class": self.node_class,
            "device_id": self.device_id,
            "runtime_session_id": self.runtime_session_id,
            "capability_refs": list(self.capability_refs),
            "metadata": dict(self.metadata),
        }


def _participant_state_from_node_status(status: str) -> ParticipantState:
    normalized = (status or "").lower().strip()
    if normalized == "healthy":
        return ParticipantState.READY
    if normalized in {"starting"}:
        return ParticipantState.REGISTERED
    if normalized in {"degraded", "draining"}:
        return ParticipantState.DEGRADED
    if normalized in {"offline", "unhealthy"}:
        return ParticipantState.OFFLINE
    return ParticipantState.UNKNOWN


def map_runtime_tier_to_participant_tier(runtime_tier: ParticipantRuntimeTier) -> ParticipantTier:
    """Map legacy runtime tiers into explicit PR-3 participant tiers.

    ``OBSERVER_ENDPOINT`` is the conservative fallback for unknown/future tiers
    to avoid accidentally promoting unclassified participants into executors.
    """
    if runtime_tier == ParticipantRuntimeTier.FULL_RUNTIME:
        return ParticipantTier.FULL_RUNTIME_HOST
    if runtime_tier == ParticipantRuntimeTier.PARTIAL_RUNTIME:
        return ParticipantTier.PARTIAL_RUNTIME_NODE
    if runtime_tier == ParticipantRuntimeTier.COMMAND_ONLY:
        return ParticipantTier.COMMAND_ENDPOINT
    return ParticipantTier.OBSERVER_ENDPOINT


def derive_participant_tier(
    *,
    runtime_present: bool,
    orchestration_eligible: bool,
    registered: bool,
    observer_role: bool = False,
    has_runtime_session: bool = False,
) -> ParticipantTier:
    """Derive canonical participant tier from participation/readiness signals.

    Decision priority:
    1) observer role -> OBSERVER_ENDPOINT
    2) runtime present + orchestration eligible -> FULL_RUNTIME_HOST
    3) runtime present or attached runtime session -> PARTIAL_RUNTIME_NODE
    4) registered only -> COMMAND_ENDPOINT
    5) fallback -> OBSERVER_ENDPOINT
    """
    if observer_role:
        return ParticipantTier.OBSERVER_ENDPOINT
    if runtime_present and orchestration_eligible:
        return ParticipantTier.FULL_RUNTIME_HOST
    if runtime_present or has_runtime_session:
        return ParticipantTier.PARTIAL_RUNTIME_NODE
    if registered:
        return ParticipantTier.COMMAND_ENDPOINT
    return ParticipantTier.OBSERVER_ENDPOINT


def map_from_node_participant_record(record: Any) -> ParticipantModel:
    """Map node-fabric style records into the canonical participant model."""
    data = record if isinstance(record, dict) else getattr(record, "to_dict", lambda: {})()
    participant_id = str(
        _pick(data, "participant_id", "runtime_participant_id", "node_id", default="unknown_participant")
    )
    node_class = str(_pick(data, "architectural_class", default="") or "")
    role = str(_pick(data, "role", default="") or "")
    raw_caps = _pick(data, "capabilities", default=[]) or []
    capability_refs = [str(c) for c in raw_caps if isinstance(c, str)]

    class_key = node_class.lower().strip()
    kind = ParticipantKind.SPECIALIZED_NODE
    tier = ParticipantRuntimeTier.PARTIAL_RUNTIME
    if class_key == "service_node":
        kind = ParticipantKind.SERVICE_NODE
        tier = ParticipantRuntimeTier.COMMAND_ONLY
    elif class_key == "archived_node":
        kind = ParticipantKind.OBSERVER
        tier = ParticipantRuntimeTier.OBSERVER_ONLY

    supports_local_execution = tier in {
        ParticipantRuntimeTier.FULL_RUNTIME,
        ParticipantRuntimeTier.PARTIAL_RUNTIME,
    }
    supports_delegation = supports_local_execution and role != "monitor"
    participant_tier = map_runtime_tier_to_participant_tier(tier)

    return ParticipantModel(
        participant_id=participant_id,
        participant_kind=kind,
        runtime_tier=tier,
        participant_tier=participant_tier,
        autonomy_level=ParticipantAutonomyLevel.SUPERVISED,
        coordination_role=role,
        participation_state=_participant_state_from_node_status(str(_pick(data, "status", default=""))),
        supports_local_execution=supports_local_execution,
        supports_delegation=supports_delegation,
        supports_attached_session=tier == ParticipantRuntimeTier.FULL_RUNTIME,
        supports_capability_linkage=bool(capability_refs),
        supports_device_linkage=bool(_pick(data, "device_id")),
        node_class=node_class,
        device_id=_pick(data, "device_id"),
        capability_refs=capability_refs,
        metadata={"mapped_from": "node_participant_record"},
    )


def map_from_device_participation_summary(summary: Any) -> ParticipantModel:
    """Map device-participation style records into the canonical participant model."""
    data = summary if isinstance(summary, dict) else getattr(summary, "to_dict", lambda: {})()
    device_id = str(_pick(data, "device_id", default="unknown_device"))
    participant_id = str(_pick(data, "participant_id", "runtime_participant_id", default=device_id))
    runtime_present = bool(_pick(data, "runtime_present", default=False))
    orchestration_eligible = bool(_pick(data, "orchestration_eligible", default=False))
    session_id = normalize_runtime_attachment_session_id(data) or _pick(data, "session_id")
    roles = _pick(data, "roles", default=[]) or []
    coordination_role = str(roles[0]) if isinstance(roles, list) and roles else str(
        _pick(data, "coordination_role", default="")
    )

    registered = bool(_pick(data, "registered", default=False))
    observer_role = coordination_role == "observer_only" or bool(_pick(data, "is_support", default=False))
    participant_tier = derive_participant_tier(
        runtime_present=runtime_present,
        orchestration_eligible=orchestration_eligible,
        registered=registered,
        observer_role=observer_role,
        has_runtime_session=bool(session_id),
    )
    if participant_tier == ParticipantTier.FULL_RUNTIME_HOST:
        tier = ParticipantRuntimeTier.FULL_RUNTIME
    elif participant_tier == ParticipantTier.PARTIAL_RUNTIME_NODE:
        tier = ParticipantRuntimeTier.PARTIAL_RUNTIME
    elif participant_tier == ParticipantTier.COMMAND_ENDPOINT:
        tier = ParticipantRuntimeTier.COMMAND_ONLY
    else:
        tier = ParticipantRuntimeTier.OBSERVER_ONLY

    if tier == ParticipantRuntimeTier.OBSERVER_ONLY:
        kind = ParticipantKind.OBSERVER
    elif tier == ParticipantRuntimeTier.COMMAND_ONLY:
        kind = ParticipantKind.TOOL_ENDPOINT
    else:
        kind = ParticipantKind.DEVICE_RUNTIME_HOST

    if runtime_present and bool(_pick(data, "routable", default=False)):
        state = ParticipantState.ACTIVE if session_id else ParticipantState.READY
    elif registered:
        state = ParticipantState.REGISTERED
    else:
        state = ParticipantState.UNKNOWN

    supports_local_execution = tier == ParticipantRuntimeTier.FULL_RUNTIME
    supports_delegation = supports_local_execution and not observer_role

    caps = _pick(data, "capabilities", default=[]) or []
    capability_refs = [str(c) for c in caps if isinstance(c, str)]
    return ParticipantModel(
        participant_id=participant_id,
        participant_kind=kind,
        runtime_tier=tier,
        participant_tier=participant_tier,
        autonomy_level=ParticipantAutonomyLevel.ASSISTED,
        coordination_role=coordination_role,
        participation_state=state,
        supports_local_execution=supports_local_execution,
        supports_delegation=supports_delegation,
        supports_attached_session=bool(session_id) or tier == ParticipantRuntimeTier.FULL_RUNTIME,
        supports_capability_linkage=bool(capability_refs),
        supports_device_linkage=True,
        device_id=device_id,
        runtime_session_id=str(session_id) if session_id else None,
        capability_refs=capability_refs,
        metadata={"mapped_from": "device_participation_summary"},
    )


def map_from_runtime_participant_surface(payload: Dict[str, Any]) -> ParticipantModel:
    """Map runtime dispatch/session posture payloads into canonical participant form."""
    participant_id = str(
        _pick(payload, "participant_id", "runtime_participant_id", "source_device_id", "device_id", default="runtime")
    )
    posture = str(_pick(payload, "source_runtime_posture", default="control_only") or "control_only").lower().strip()
    coordination_role = str(_pick(payload, "coordination_role", default="") or "")
    runtime_session_id = normalize_runtime_attachment_session_id(payload)
    device_id = _pick(payload, "source_device_id", "device_id", "target_device_id")
    capability_refs = []
    raw_caps = _pick(payload, "capabilities", default=[]) or []
    if isinstance(raw_caps, list):
        capability_refs = [str(c) for c in raw_caps if isinstance(c, str)]

    if coordination_role == "observer_only":
        tier = ParticipantRuntimeTier.OBSERVER_ONLY
        kind = ParticipantKind.OBSERVER
    elif posture == "join_runtime":
        tier = ParticipantRuntimeTier.FULL_RUNTIME
        kind = ParticipantKind.DEVICE_RUNTIME_HOST
    else:
        tier = ParticipantRuntimeTier.COMMAND_ONLY
        kind = ParticipantKind.TOOL_ENDPOINT

    supports_local_execution = posture == "join_runtime" and tier != ParticipantRuntimeTier.OBSERVER_ONLY
    supports_delegation = supports_local_execution and coordination_role not in {
        "observer_only",
        "target_only_executor",
    }
    participant_tier = map_runtime_tier_to_participant_tier(tier)

    return ParticipantModel(
        participant_id=participant_id,
        participant_kind=kind,
        runtime_tier=tier,
        participant_tier=participant_tier,
        autonomy_level=ParticipantAutonomyLevel.ASSISTED,
        coordination_role=coordination_role,
        participation_state=ParticipantState.ACTIVE if runtime_session_id else ParticipantState.READY,
        supports_local_execution=supports_local_execution,
        supports_delegation=supports_delegation,
        supports_attached_session=bool(runtime_session_id) or posture == "join_runtime",
        supports_capability_linkage=bool(capability_refs),
        supports_device_linkage=bool(device_id),
        device_id=str(device_id) if device_id else None,
        runtime_session_id=str(runtime_session_id) if runtime_session_id else None,
        capability_refs=capability_refs,
        metadata={"mapped_from": "runtime_participant_surface"},
    )


# ---------------------------------------------------------------------------
# Coordination objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MeshParticipant:
    node_id: str
    role: str = "participant"
    status: str = "active"

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class MeshSession:
    mesh_session_id: str
    status: str = "pending"
    participants: List[MeshParticipant] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class CoordinationRole:
    node_id: Optional[str] = None
    role: str = "participant"

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class BarrierState:
    mesh_session_id: Optional[str] = None
    barrier_name: str = ""
    reached_participant_ids: List[str] = field(default_factory=list)
    expected_participant_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


@dataclass(frozen=True)
class AggregationPlan:
    mesh_session_id: Optional[str] = None
    aggregation_mode: str = "first_success"
    expected_result_count: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


# ---------------------------------------------------------------------------
# Truth objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TerminalState:
    value: str = "unknown"

    def __post_init__(self) -> None:
        if self.value not in _VALID_TERMINAL_STATES and self.value != "unknown":
            raise ValueError(f"Unsupported terminal state: {self.value!r}")


@dataclass(frozen=True)
class TerminalReason:
    value: str = ""


@dataclass(frozen=True)
class SessionTruth:
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    terminal_state: TerminalState = field(default_factory=TerminalState)
    terminal_reason: TerminalReason = field(default_factory=TerminalReason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "control_session_id": self.control_session_id,
            "runtime_session_id": self.runtime_session_id,
            "terminal_state": self.terminal_state.value,
            "terminal_reason": self.terminal_reason.value,
        }


@dataclass(frozen=True)
class TaskTruth:
    task_id: Optional[str] = None
    terminal_state: TerminalState = field(default_factory=TerminalState)
    terminal_reason: TerminalReason = field(default_factory=TerminalReason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "terminal_state": self.terminal_state.value,
            "terminal_reason": self.terminal_reason.value,
        }


@dataclass(frozen=True)
class RuntimeTruth:
    runtime_session_id: Optional[str] = None
    runtime_status: str = "unknown"
    terminal_state: TerminalState = field(default_factory=TerminalState)
    terminal_reason: TerminalReason = field(default_factory=TerminalReason)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_session_id": self.runtime_session_id,
            "runtime_status": self.runtime_status,
            "terminal_state": self.terminal_state.value,
            "terminal_reason": self.terminal_reason.value,
        }


@dataclass(frozen=True)
class TruthEvent:
    event_type: str
    trace_id: Optional[str] = None
    task_id: Optional[str] = None
    control_session_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return _to_json_dict(self)


# ---------------------------------------------------------------------------
# Mapping notes and compatibility shims
# ---------------------------------------------------------------------------


def map_from_task_envelope(envelope: Any) -> TaskEnvelope:
    """Map existing core.schemas.task_envelope.TaskEnvelope into UGCP TaskEnvelope."""
    return TaskEnvelope(
        task_id=str(_pick(envelope, "task_id", default="")),
        trace_id=str(_pick(envelope, "trace_id", default="")),
        control_session_id=normalize_conversation_session_id(envelope),
        source_node_id=_pick(envelope, "source_node_id", "source"),
        target_node_id=_pick(envelope, "target_node_id", default=_first_target(envelope)),
        tool_name=str(_pick(envelope, "tool_name", default="")),
        args=dict(_pick(envelope, "args", default={}) or {}),
        metadata=dict(_pick(envelope, "metadata", default={}) or {}),
    )


def map_from_delegated_dispatch_record(record: Any) -> DispatchDecision:
    """Map PR-8 delegated runtime dispatch record into a canonical dispatch decision."""
    return DispatchDecision(
        execution_instance_id=_pick(record, "execution_instance_id", "dispatch_record_id", "dispatch_id"),
        dispatch_mode=str(_pick(record, "dispatch_mode", "delegation_intent", default="")),
        effective_mode=str(_pick(record, "effective_mode", "delegation_intent", default="")),
        decision_reason=str(_pick(record, "reason", "decision_reason", default="")),
        metadata=dict(_pick(record, "metadata", default={}) or {}),
    )


def map_from_delegated_handoff_contract(contract: Any) -> HandoffRequest:
    """Map PR-9 delegated handoff contract into canonical handoff request shape."""
    identity = _pick(contract, "identity", default={}) or {}
    payload = _pick(contract, "payload", default={}) or {}
    meta = _pick(contract, "meta", default={}) or {}
    return HandoffRequest(
        task_id=_pick(payload, "task_id"),
        control_session_id=normalize_conversation_session_id(identity),
        runtime_session_id=normalize_runtime_attachment_session_id(identity) or _pick(identity, "session_id"),
        source_node_id=_pick(meta, "source_node_id", "source_device_id"),
        target_node_id=_pick(identity, "device_id", "target_device_id"),
        handoff_reason=str(_pick(contract, "reason", default="")),
        metadata=dict(_pick(contract, "metadata", default={}) or {}),
    )


def map_from_runtime_session_snapshot(snapshot: Any) -> RuntimeTruth:
    """Map runtime session snapshot contract into canonical runtime truth shape."""
    identity = _pick(snapshot, "identity", default={}) or {}
    raw_status = _pick(snapshot, "status", default="unknown")
    normalized_status = (
        raw_status
        if isinstance(raw_status, str) and raw_status in _VALID_TERMINAL_STATES
        else "unknown"
    )
    reason = _pick(snapshot, "reason", default="")
    runtime_session_id = (
        normalize_runtime_attachment_session_id(identity)
        or _pick(identity, "session_id")
        or normalize_runtime_attachment_session_id(snapshot)
        or _pick(snapshot, "session_id")
    )
    return RuntimeTruth(
        runtime_session_id=runtime_session_id,
        runtime_status=normalized_status,
        terminal_state=TerminalState(value=normalized_status),
        terminal_reason=TerminalReason(value=str(reason or "")),
    )


def map_from_message_interop_payload(payload: Dict[str, Any]) -> TaskEnvelope:
    """Map interop payload into UGCP task envelope.

    Notes
    -----
    Existing message-interop payloads may carry tool arguments in either
    ``args`` or ``payload``. Canonical UGCP ``TaskEnvelope`` stores both
    variants in ``args`` to keep one control-surface field.
    """
    corr_task_id = _pick(payload, "task_id", "request_id", default="")
    corr_trace_id = _pick(payload, "trace_id", default="")
    ctx = _pick(payload, "context", default={}) or {}
    control_session_id = normalize_conversation_session_id(payload) or normalize_conversation_session_id(ctx)
    return TaskEnvelope(
        task_id=str(corr_task_id),
        trace_id=str(corr_trace_id),
        control_session_id=control_session_id,
        source_node_id=_pick(payload, "source", "source_node_id"),
        target_node_id=_pick(payload, "target", "target_node_id"),
        tool_name=str(_pick(payload, "tool_name", "action", default="")),
        args=dict(_pick(payload, "args", "payload", default={}) or {}),
        metadata={"interop_source": "message_interop"},
    )


def to_json(instance: Any, **kwargs: Any) -> str:
    """Serialize any UGCP shared object to a JSON string."""
    if hasattr(instance, "to_dict"):
        return json.dumps(instance.to_dict(), **kwargs)
    return json.dumps(instance, **kwargs)


__all__ = [
    "UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY",
    "UGCP_SHARED_SCHEMA_FAMILY_PR2_SENTINEL",
    "UGCP_CANONICAL_CONCEPT_VOCABULARY_ALIGNMENT_PR51_SENTINEL",
    "UGCP_CANONICAL_PARTICIPANT_MODEL_PR52_SENTINEL",
    "UGCP_CANONICAL_PARTICIPANT_TIERS_PR3_SENTINEL",
    # identity
    "TaskId",
    "TraceId",
    "ParticipantId",
    "DeviceId",
    "RuntimeId",
    "CapabilityId",
    "ConversationSessionId",
    "RuntimeAttachmentSessionId",
    "DelegationTransferSessionId",
    "ControlSessionId",
    "RuntimeSessionId",
    "MeshSessionId",
    "NodeId",
    "GraphNodeId",
    "ExecutionInstanceId",
    # control
    "TaskEnvelope",
    "DispatchDecision",
    "Assignment",
    "ExecutionLease",
    "HandoffRequest",
    "TakeoverDecision",
    # runtime
    "RuntimeTarget",
    "CapabilityProfile",
    "ReadinessProfile",
    "RuntimePosture",
    "DiagnosticsReport",
    "ParticipantKind",
    "ParticipantRuntimeTier",
    "ParticipantTier",
    "ParticipantAutonomyLevel",
    "ParticipantState",
    "ParticipantModel",
    # coordination
    "MeshSession",
    "MeshParticipant",
    "CoordinationRole",
    "BarrierState",
    "AggregationPlan",
    # truth
    "SessionTruth",
    "TaskTruth",
    "RuntimeTruth",
    "TruthEvent",
    "TerminalState",
    "TerminalReason",
    # mappings
    "map_from_task_envelope",
    "map_from_delegated_dispatch_record",
    "map_from_delegated_handoff_contract",
    "map_from_runtime_session_snapshot",
    "map_from_message_interop_payload",
    "normalize_runtime_participant_id",
    "normalize_graph_node_id",
    "normalize_conversation_session_id",
    "normalize_runtime_attachment_session_id",
    "normalize_delegation_transfer_session_id",
    "map_from_node_participant_record",
    "map_from_device_participation_summary",
    "map_from_runtime_participant_surface",
    "map_runtime_tier_to_participant_tier",
    "derive_participant_tier",
    "to_json",
]
