#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UGCP shared schema family (realization-v2 side).

This module introduces an incremental canonical schema layer for shared
identity/control/runtime/coordination/truth objects. It does not replace all
existing contracts yet; it provides stable canonical objects and lightweight
mapping shims from current key contracts.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
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
class ControlSessionId:
    value: str


@dataclass(frozen=True)
class RuntimeSessionId:
    value: str


@dataclass(frozen=True)
class MeshSessionId:
    value: str


@dataclass(frozen=True)
class NodeId:
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
        control_session_id=_pick(envelope, "control_session_id", "session_id"),
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
        control_session_id=_pick(identity, "session_id"),
        runtime_session_id=_pick(identity, "runtime_session_id", "session_id"),
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
    runtime_session_id = _pick(identity, "session_id") or _pick(snapshot, "session_id")
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
    control_session_id = _pick(payload, "control_session_id", "session_id") or _pick(ctx, "session_id")
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
    # identity
    "TaskId",
    "TraceId",
    "ControlSessionId",
    "RuntimeSessionId",
    "MeshSessionId",
    "NodeId",
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
    "to_json",
]
