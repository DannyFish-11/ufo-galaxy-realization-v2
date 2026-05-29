"""
core/schemas/aip_v3.py
=====================
PR-AIPV3-UNIFIED: Canonical AIP v3 Protocol Models

Single unified Pydantic model layer for ALL inter-device communication in Galaxy.
Based on the mature Android AIP v3 implementation (AipModels.kt) and extended
to cover NATS, Mesh, DAG, and local node invocation.

Design principles:
  - ONE model file for all device-facing messages
  - Every message carries: type, device_id, timestamp, trace_id
  - Pydantic v2 validation, JSON serialization, backward-compatible defaults
  - Used directly by NATS Bus, Mesh Engine, DAG Scheduler, CommandRouter

Usage::
    from core.schemas.aip_v3 import (
        DeviceRegisterMsg, TaskAssignMsg, TaskResultMsg,
        MeshJoinMsg, MeshResultMsg, CapabilityReportMsg,
        AIPMessage, MsgType,
    )
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# MsgType enum — mirrors AipModels.kt MsgType exactly
# ---------------------------------------------------------------------------


class MsgType(str, Enum):
    """Canonical AIP v3 message type identifiers.

    Mirrors Android AipModels.kt MsgType enum exactly.
    All message types used across the unified device protocol.
    """

    # ── Device lifecycle ──
    DEVICE_REGISTER = "device_register"
    DEVICE_UNREGISTER = "device_unregister"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    CAPABILITY_REPORT = "capability_report"

    # ── Task / execution ──
    TASK_SUBMIT = "task_submit"
    TASK_ASSIGN = "task_assign"
    TASK_RESULT = "task_result"
    TASK_CANCEL = "task_cancel"
    CANCEL_RESULT = "cancel_result"
    COMMAND_RESULT = "command_result"
    GOAL_EXECUTION = "goal_execution"
    GOAL_RESULT = "goal_result"
    GOAL_EXECUTION_RESULT = "goal_execution_result"
    PARALLEL_SUBTASK = "parallel_subtask"

    # ── Mesh coordination ──
    MESH_JOIN = "mesh_join"
    MESH_LEAVE = "mesh_leave"
    MESH_RESULT = "mesh_result"
    MESH_TOPOLOGY = "mesh_topology"
    COORD_SYNC = "coord_sync"

    # ── Peer / takeover ──
    PEER_ANNOUNCE = "peer_announce"
    PEER_EXCHANGE = "peer_exchange"
    TAKEOVER_REQUEST = "takeover_request"
    TAKEOVER_RESPONSE = "takeover_response"

    # ── Signals ──
    DELEGATED_EXECUTION_SIGNAL = "delegated_execution_signal"
    RECONCILIATION_SIGNAL = "reconciliation_signal"
    OPERATOR_ACTION_REQUEST = "operator_action_request"
    OPERATOR_ACTION_RESULT = "operator_action_result"

    # ── Ack / generic ──
    ACK = "ack"
    BROADCAST = "broadcast"

    # ── Extended: state events (unified from StateEventBus) ──
    STATE_EVENT = "state_event"

    # ── Extended: capability query ──
    CAPABILITY_QUERY = "capability_query"

    # ── Extended: WebRTC control ──
    WEBRTC_BIND = "webrtc_bind"
    WEBRTC_UNBIND = "webrtc_unbind"
    WEBRTC_TRANSPORT_STATE = "webrtc_transport_state"


# ---------------------------------------------------------------------------
# Base model — every AIP v3 message extends this
# ---------------------------------------------------------------------------


class AIPMessage(BaseModel):
    """Base class for ALL AIP v3 messages.

    Every message on every transport (WebSocket, NATS, Mesh, Local)
    carries these fields so that consumers can always identify:
    - what type of message it is (type)
    - which device it concerns (device_id)
    - when it was sent (timestamp)
    - how to correlate it (trace_id, task_id, session_id)
    """

    type: MsgType = Field(..., description="AIP v3 message type discriminator")
    device_id: str = Field(default="", description="Primary device identifier")
    timestamp: int = Field(
        default_factory=lambda: int(time.time() * 1000),
        description="Unix timestamp in milliseconds",
    )
    trace_id: str = Field(default="", description="End-to-end trace identifier")
    task_id: str = Field(default="", description="Associated task identifier")
    session_id: str = Field(default="", description="Session-level identifier")
    correlation_id: str = Field(
        default_factory=lambda: f"corr_{uuid.uuid4().hex[:8]}",
        description="Message-level correlation ID for request/response pairing",
    )
    _aip_version: str = Field(default="3.0", description="AIP protocol version")

    class Config:
        populate_by_name = True
        use_enum_values = True


# ---------------------------------------------------------------------------
# Device lifecycle messages
# ---------------------------------------------------------------------------


class DeviceRegisterMsg(AIPMessage):
    """DEVICE_REGISTER — device announces itself to the system.

    Used by: Android WebSocket, NATS Worker registration, Mesh auto-enrollment
    """

    type: MsgType = Field(default=MsgType.DEVICE_REGISTER)
    device_name: str = Field(default="", description="Human-readable device name")
    device_type: str = Field(default="", description="Device type: android_phone, worker, ble, mqtt, ...")
    transport: str = Field(default="", description="Transport: websocket, nats, mesh, local, ble, mqtt, serial")
    ip_address: str = Field(default="", description="Device IP address if available")
    port: int = Field(default=0, description="Service port if applicable")
    capabilities: List[str] = Field(default_factory=list, description="Device capability list")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional device metadata")
    status: str = Field(default="online", description="Device status: online, offline, busy, error")


class DeviceUnregisterMsg(AIPMessage):
    """DEVICE_UNREGISTER — device leaves the system."""

    type: MsgType = Field(default=MsgType.DEVICE_UNREGISTER)
    reason: str = Field(default="", description="Unregister reason: shutdown, disconnect, error, ...")


class HeartbeatMsg(AIPMessage):
    """HEARTBEAT — periodic liveness signal from device.

    Used by: Android WebSocket heartbeat, NATS Worker heartbeat, Mesh keepalive
    """

    type: MsgType = Field(default=MsgType.HEARTBEAT)
    status: str = Field(default="online", description="Current device status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Runtime metadata: load, memory, battery, ...")


class HeartbeatAckMsg(AIPMessage):
    """HEARTBEAT_ACK — server acknowledges device heartbeat."""

    type: MsgType = Field(default=MsgType.HEARTBEAT_ACK)
    server_timestamp: int = Field(default=0, description="Server timestamp for latency calculation")


class CapabilityReportMsg(AIPMessage):
    """CAPABILITY_REPORT — device reports its capabilities.

    Used by: Android capability_report, NATS Worker capability announcement,
    Mesh peer_exchange, local node capability declaration
    """

    type: MsgType = Field(default=MsgType.CAPABILITY_REPORT)
    capabilities: List[str] = Field(default_factory=list, description="List of supported capability/action names")
    actions: List[str] = Field(default_factory=list, description="Detailed action list with parameters")
    version: str = Field(default="1.0.0", description="Capability schema version")


class CapabilityQueryMsg(AIPMessage):
    """CAPABILITY_QUERY — query available capabilities in the system."""

    type: MsgType = Field(default=MsgType.CAPABILITY_QUERY)
    query_filter: str = Field(default="", description="Optional filter: device_type, capability_name, ...")


# ---------------------------------------------------------------------------
# Task / execution messages
# ---------------------------------------------------------------------------


class TaskAssignMsg(AIPMessage):
    """TASK_ASSIGN — assign a task to a device for execution.

    Used by: Android goal_execution, NATS task dispatch, Mesh subtask assignment,
    DAG node execution, local node invocation
    """

    type: MsgType = Field(default=MsgType.TASK_ASSIGN)
    action: str = Field(default="", description="Action/command to execute")
    params: Dict[str, Any] = Field(default_factory=dict, description="Action parameters")
    priority: str = Field(default="normal", description="Task priority: critical, high, normal, low")
    timeout_ms: int = Field(default=30000, description="Execution timeout in milliseconds")
    goal: str = Field(default="", description="Natural-language goal description")
    constraints: List[str] = Field(default_factory=list, description="Execution constraints")
    context: Dict[str, Any] = Field(default_factory=dict, description="Execution context: previous results, state, ...")


class TaskResultMsg(AIPMessage):
    """TASK_RESULT — device reports task execution result.

    Used by: Android goal_execution_result, NATS task result, Mesh result,
    DAG node completion, local node return
    """

    type: MsgType = Field(default=MsgType.TASK_RESULT)
    status: str = Field(default="", description="Result status: completed, failed, timeout, cancelled, partial")
    result: Any = Field(default=None, description="Execution result (any JSON-serializable value)")
    error: str = Field(default="", description="Error message if status is failed/timeout/cancelled")
    duration_ms: int = Field(default=0, description="Execution duration in milliseconds")
    partial_results: List[Dict[str, Any]] = Field(default_factory=list, description="Partial results from multi-step execution")


class TaskCancelMsg(AIPMessage):
    """TASK_CANCEL — request cancellation of a running task."""

    type: MsgType = Field(default=MsgType.TASK_CANCEL)
    force: bool = Field(default=False, description="Force cancel even if cleanup fails")
    reason: str = Field(default="", description="Cancellation reason")


class CancelResultMsg(AIPMessage):
    """CANCEL_RESULT — device acknowledges task cancellation."""

    type: MsgType = Field(default=MsgType.CANCEL_RESULT)
    cancelled: bool = Field(default=False, description="Whether cancellation succeeded")
    cleanup_status: str = Field(default="", description="Cleanup result: clean, partial, failed")


class GoalExecutionMsg(AIPMessage):
    """GOAL_EXECUTION — high-level goal execution request (Android-specific)."""

    type: MsgType = Field(default=MsgType.GOAL_EXECUTION)
    goal: str = Field(default="", description="Natural-language goal")
    params: Dict[str, Any] = Field(default_factory=dict, description="Goal parameters")
    parallel_subtasks: List[Dict[str, Any]] = Field(default_factory=list, description="Parallel subtask definitions")
    source_device_id: str = Field(default="", description="Device that initiated the goal")


class GoalExecutionResultMsg(AIPMessage):
    """GOAL_EXECUTION_RESULT — result of a goal execution."""

    type: MsgType = Field(default=MsgType.GOAL_EXECUTION_RESULT)
    status: str = Field(default="", description="completed, failed, timeout, cancelled")
    result_summary: str = Field(default="", description="Human-readable result summary")
    result: Any = Field(default=None, description="Structured result data")
    error: str = Field(default="", description="Error message if failed")
    duration_ms: int = Field(default=0, description="Total execution duration")


# ---------------------------------------------------------------------------
# Mesh coordination messages
# ---------------------------------------------------------------------------


class MeshJoinMsg(AIPMessage):
    """MESH_JOIN — device requests to join a mesh session.

    Used by: Android mesh_join handler, Mesh auto-enrollment, NATS mesh coordination
    """

    type: MsgType = Field(default=MsgType.MESH_JOIN)
    mesh_id: str = Field(default="", description="Mesh session identifier")
    role: str = Field(default="participant", description="Role: coordinator, participant, observer")
    capabilities: List[str] = Field(default_factory=list, description="Capabilities offered to mesh")
    formation_role: str = Field(default="", description="Formation-specific role")


class MeshLeaveMsg(AIPMessage):
    """MESH_LEAVE — device leaves a mesh session."""

    type: MsgType = Field(default=MsgType.MESH_LEAVE)
    mesh_id: str = Field(default="", description="Mesh session identifier")
    reason: str = Field(default="", description="Leave reason: completed, error, timeout, disconnected")


class MeshResultMsg(AIPMessage):
    """MESH_RESULT — device reports aggregated parallel-subtask results.

    Used by: Android mesh_result handler, Mesh barrier result aggregation
    """

    type: MsgType = Field(default=MsgType.MESH_RESULT)
    mesh_id: str = Field(default="", description="Mesh session identifier")
    subtask_results: List[Dict[str, Any]] = Field(default_factory=list, description="Per-subtask results")
    aggregated_result: Any = Field(default=None, description="Aggregated result across all subtasks")
    participant_count: int = Field(default=0, description="Number of participants contributed")


class MeshTopologyMsg(AIPMessage):
    """MESH_TOPOLOGY — mesh topology query or update.

    Used by: Android mesh_topology handler, MeshCoordinator topology sync
    """

    type: MsgType = Field(default=MsgType.MESH_TOPOLOGY)
    mesh_id: str = Field(default="", description="Mesh session identifier")
    topology: Dict[str, Any] = Field(default_factory=dict, description="Topology data: peers, connections, roles")
    peer_count: int = Field(default=0, description="Number of known peers")
    request_type: str = Field(default="query", description="query | update | full_sync")


class CoordSyncMsg(AIPMessage):
    """COORD_SYNC — coordination synchronization tick between coordinator and participants.

    Used by: Mesh barrier coordination, barrier state synchronization
    """

    type: MsgType = Field(default=MsgType.COORD_SYNC)
    mesh_id: str = Field(default="", description="Mesh session identifier")
    sync_type: str = Field(default="tick", description="tick | barrier_request | barrier_release | status_query")
    barrier_status: str = Field(default="", description="waiting | released | failed | not_required")
    participant_statuses: Dict[str, str] = Field(default_factory=dict, description="device_id → status mapping")
    tick_sequence: int = Field(default=0, description="Monotonic sync tick counter")


# ---------------------------------------------------------------------------
# Peer / takeover messages
# ---------------------------------------------------------------------------


class PeerAnnounceMsg(AIPMessage):
    """PEER_ANNOUNCE — announce a new peer device joining the session."""

    type: MsgType = Field(default=MsgType.PEER_ANNOUNCE)
    peer_device_id: str = Field(default="", description="Announced peer device ID")
    peer_device_type: str = Field(default="", description="Peer device type")
    peer_capabilities: List[str] = Field(default_factory=list, description="Peer capabilities")
    mesh_id: str = Field(default="", description="Associated mesh/session")


class PeerExchangeMsg(AIPMessage):
    """PEER_EXCHANGE — capability exchange between peer devices."""

    type: MsgType = Field(default=MsgType.PEER_EXCHANGE)
    peer_device_id: str = Field(default="", description="Target peer device ID")
    offered_capabilities: List[str] = Field(default_factory=list, description="Capabilities this device offers")
    requested_capabilities: List[str] = Field(default_factory=list, description="Capabilities this device needs")


class TakeoverRequestMsg(AIPMessage):
    """TAKEOVER_REQUEST — request another device to take over execution.

    Used by: Android takeover_request, cross-device handoff
    """

    type: MsgType = Field(default=MsgType.TAKEOVER_REQUEST)
    target_device_id: str = Field(default="", description="Device being asked to take over")
    source_device_id: str = Field(default="", description="Device initiating the takeover")
    task_context: Dict[str, Any] = Field(default_factory=dict, description="Task state to transfer")
    urgency: str = Field(default="normal", description="normal, high, critical")
    constraints: List[str] = Field(default_factory=list, description="Takeover constraints")


class TakeoverResponseMsg(AIPMessage):
    """TAKEOVER_RESPONSE — device responds to a takeover request."""

    type: MsgType = Field(default=MsgType.TAKEOVER_RESPONSE)
    request_correlation_id: str = Field(default="", description="Correlation ID from the takeover request")
    accepted: bool = Field(default=False, description="Whether takeover was accepted")
    rejection_reason: str = Field(default="", description="Reason if rejected: ineligible, busy, error, ...")
    runtime_host_id: str = Field(default="", description="ID of the accepting runtime host")


# ---------------------------------------------------------------------------
# Signal messages
# ---------------------------------------------------------------------------


class DelegatedExecutionSignalMsg(AIPMessage):
    """DELEGATED_EXECUTION_SIGNAL — lifecycle signal during delegated execution.

    Signals: ACK, PROGRESS, RESULT, TIMEOUT, CANCELLED
    """

    type: MsgType = Field(default=MsgType.DELEGATED_EXECUTION_SIGNAL)
    signal_kind: str = Field(default="", description="ACK | PROGRESS | RESULT | TIMEOUT | CANCELLED")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Signal-specific payload")
    progress_pct: int = Field(default=0, description="Progress percentage (0-100) for PROGRESS signals")


class ReconciliationSignalMsg(AIPMessage):
    """RECONCILIATION_SIGNAL — state reconciliation between devices.

    Used by: Android reconciliation_signal, cross-device state sync
    """

    type: MsgType = Field(default=MsgType.RECONCILIATION_SIGNAL)
    signal_kind: str = Field(default="", description="TASK_RESULT | TASK_CANCELLED | TASK_FAILED | PARTICIPANT_STATE | RUNTIME_TRUTH_SNAPSHOT")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Signal payload")
    source_runtime_truth: Dict[str, Any] = Field(default_factory=dict, description="Source device's runtime truth snapshot")


# ---------------------------------------------------------------------------
# State event message (unified from StateEventBus)
# ---------------------------------------------------------------------------


class StateEventMsg(AIPMessage):
    """STATE_EVENT — unified state event for observability.

    Consolidates: phase transitions, task lifecycle, skill invocation,
    executor actions, device state, mesh updates, HITL evaluations.
    """

    type: MsgType = Field(default=MsgType.STATE_EVENT)
    event_category: str = Field(default="", description="phase | task | skill | executor | device | mesh | hitl")
    event_action: str = Field(default="", description="started | done | failed | updated | evaluated | ...")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Event-specific data")


# ---------------------------------------------------------------------------
# WebRTC control messages
# ---------------------------------------------------------------------------


class WebRTCBindMsg(AIPMessage):
    """WEBRTC_BIND — bind a WebRTC session to a task/device."""

    type: MsgType = Field(default=MsgType.WEBRTC_BIND)
    webrtc_session_id: str = Field(default="", description="WebRTC session identifier")
    bind_target: str = Field(default="task", description="task | device | stream")
    offer_sdp: str = Field(default="", description="SDP offer for WebRTC negotiation")


class WebRTCUnbindMsg(AIPMessage):
    """WEBRTC_UNBIND — unbind a WebRTC session."""

    type: MsgType = Field(default=MsgType.WEBRTC_UNBIND)
    webrtc_session_id: str = Field(default="", description="WebRTC session identifier")
    reason: str = Field(default="", description="Unbind reason")


class WebRTCTransportStateMsg(AIPMessage):
    """WEBRTC_TRANSPORT_STATE — WebRTC transport state change notification."""

    type: MsgType = Field(default=MsgType.WEBRTC_TRANSPORT_STATE)
    webrtc_session_id: str = Field(default="", description="WebRTC session identifier")
    transport_state: str = Field(default="", description="connecting | connected | degraded | disconnected | failed")
    previous_state: str = Field(default="", description="Previous transport state")


# ---------------------------------------------------------------------------
# ACK / generic
# ---------------------------------------------------------------------------


class AckMsg(AIPMessage):
    """ACK — generic acknowledgement message."""

    type: MsgType = Field(default=MsgType.ACK)
    ack_for_type: str = Field(default="", description="Type of message being acknowledged")
    ack_for_correlation_id: str = Field(default="", description="Correlation ID of message being acknowledged")
    status: str = Field(default="ok", description="ok | error | retry")


# ---------------------------------------------------------------------------
# Message factory / dispatcher
# ---------------------------------------------------------------------------

# Mapping from MsgType → message class
_MSG_TYPE_TO_CLASS: Dict[MsgType, type] = {
    MsgType.DEVICE_REGISTER: DeviceRegisterMsg,
    MsgType.DEVICE_UNREGISTER: DeviceUnregisterMsg,
    MsgType.HEARTBEAT: HeartbeatMsg,
    MsgType.HEARTBEAT_ACK: HeartbeatAckMsg,
    MsgType.CAPABILITY_REPORT: CapabilityReportMsg,
    MsgType.CAPABILITY_QUERY: CapabilityQueryMsg,
    MsgType.TASK_ASSIGN: TaskAssignMsg,
    MsgType.TASK_RESULT: TaskResultMsg,
    MsgType.TASK_CANCEL: TaskCancelMsg,
    MsgType.CANCEL_RESULT: CancelResultMsg,
    MsgType.GOAL_EXECUTION: GoalExecutionMsg,
    MsgType.GOAL_RESULT: GoalResultMsg,
    MsgType.GOAL_EXECUTION_RESULT: GoalExecutionResultMsg,
    MsgType.MESH_JOIN: MeshJoinMsg,
    MsgType.MESH_LEAVE: MeshLeaveMsg,
    MsgType.MESH_RESULT: MeshResultMsg,
    MsgType.MESH_TOPOLOGY: MeshTopologyMsg,
    MsgType.COORD_SYNC: CoordSyncMsg,
    MsgType.PEER_ANNOUNCE: PeerAnnounceMsg,
    MsgType.PEER_EXCHANGE: PeerExchangeMsg,
    MsgType.TAKEOVER_REQUEST: TakeoverRequestMsg,
    MsgType.TAKEOVER_RESPONSE: TakeoverResponseMsg,
    MsgType.DELEGATED_EXECUTION_SIGNAL: DelegatedExecutionSignalMsg,
    MsgType.RECONCILIATION_SIGNAL: ReconciliationSignalMsg,
    MsgType.STATE_EVENT: StateEventMsg,
    MsgType.WEBRTC_BIND: WebRTCBindMsg,
    MsgType.WEBRTC_UNBIND: WebRTCUnbindMsg,
    MsgType.WEBRTC_TRANSPORT_STATE: WebRTCTransportStateMsg,
    MsgType.ACK: AckMsg,
}


def parse_aip_message(data: Dict[str, Any]) -> AIPMessage:
    """Parse a raw dict into the correct AIP v3 message subclass.

    Usage::
        raw = json.loads(nats_msg)
        msg = parse_aip_message(raw)
        if msg.type == MsgType.TASK_ASSIGN:
            assert isinstance(msg, TaskAssignMsg)
            print(msg.action, msg.params)
    """
    if not isinstance(data, dict):
        raise ValueError(f"AIP v3 message must be a dict, got {type(data).__name__}")

    msg_type_str = data.get("type", "")
    # Handle string type
    try:
        msg_type = MsgType(msg_type_str) if isinstance(msg_type_str, str) else msg_type_str
    except ValueError:
        # Unknown type — parse as base AIPMessage
        return AIPMessage(**data)

    msg_class = _MSG_TYPE_TO_CLASS.get(msg_type, AIPMessage)
    return msg_class(**data)


def create_aip_message(
    msg_type: MsgType,
    device_id: str = "",
    **kwargs: Any,
) -> AIPMessage:
    """Factory: create an AIP v3 message of the given type.

    Usage::
        msg = create_aip_message(
            MsgType.TASK_ASSIGN,
            device_id="phone_01",
            action="screenshot",
            params={"quality": "high"},
            trace_id="trace_abc123",
        )
        # Returns TaskAssignMsg instance
    """
    msg_class = _MSG_TYPE_TO_CLASS.get(msg_type, AIPMessage)
    return msg_class(type=msg_type, device_id=device_id, **kwargs)
