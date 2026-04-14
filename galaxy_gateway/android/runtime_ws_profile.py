"""
galaxy_gateway/android/runtime_ws_profile.py

UGCP Runtime WS Profile mapping for Android AIP/WS ingress (PR-4B).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from galaxy_gateway.protocol.aip_v3 import MessageType

ANDROID_RUNTIME_WS_PROFILE_AUTHORITY = (
    "ANDROID_RUNTIME_WS_PROFILE_AUTHORITY::galaxy_gateway.android.runtime_ws_profile"
)
ANDROID_RUNTIME_WS_PROFILE_PR4B_SENTINEL = (
    "ANDROID_RUNTIME_WS_PROFILE_PR4B_SENTINEL::android-aip-ws-ingress-aligned"
)

ANDROID_RUNTIME_WS_SESSION_CONTINUITY_EXPECTATION = (
    "session continuity is preserved via reconnect+heartbeat on canonical WS ingress"
)
ANDROID_RUNTIME_WS_READINESS_POSTURE_EXPECTATION = (
    "capability/reporting and status signals are readiness/posture evidence (not parallel authority)"
)
ANDROID_RUNTIME_WS_TRANSFER_EXPECTATION = (
    "delegated execution and transfer-family signals must enter canonical control semantics"
)
ANDROID_RUNTIME_WS_MESH_EXPECTATION = (
    "mesh participation signals are accepted at ingress and routed as transport coordination inputs"
)


@dataclass(frozen=True)
class AndroidRuntimeWSMapping:
    message_type: str
    semantic_family: str
    normalization_kind: str
    routing_path: str
    truth_path: str
    handling_level: str


_MAPPINGS: Dict[str, AndroidRuntimeWSMapping] = {
    MessageType.DEVICE_REGISTER.value: AndroidRuntimeWSMapping(
        message_type=MessageType.DEVICE_REGISTER.value,
        semantic_family="registration",
        normalization_kind="device_register",
        routing_path="android_bridge.registration",
        truth_path="udm.register_device",
        handling_level="canonical",
    ),
    MessageType.DEVICE_HEARTBEAT.value: AndroidRuntimeWSMapping(
        message_type=MessageType.DEVICE_HEARTBEAT.value,
        semantic_family="session_continuity",
        normalization_kind="heartbeat",
        routing_path="android_bridge.heartbeat",
        truth_path="udm.heartbeat",
        handling_level="canonical",
    ),
    MessageType.DEVICE_STATUS.value: AndroidRuntimeWSMapping(
        message_type=MessageType.DEVICE_STATUS.value,
        semantic_family="readiness_capability_posture",
        normalization_kind="device_status",
        routing_path="android_bridge.device_status",
        truth_path="udm.upsert_device_state",
        handling_level="canonical",
    ),
    MessageType.AGENT_STATUS.value: AndroidRuntimeWSMapping(
        message_type=MessageType.AGENT_STATUS.value,
        semantic_family="readiness_capability_posture",
        normalization_kind="agent_status",
        routing_path="android_bridge.agent_status",
        truth_path="udm.upsert_device_state",
        handling_level="canonical",
    ),
    MessageType.CAPABILITY_REPORT.value: AndroidRuntimeWSMapping(
        message_type=MessageType.CAPABILITY_REPORT.value,
        semantic_family="readiness_capability_posture",
        normalization_kind="capability_report",
        routing_path="android_bridge.capability_report",
        truth_path="gateway+capability_registry",
        handling_level="canonical",
    ),
    MessageType.DELEGATED_EXECUTION_SIGNAL.value: AndroidRuntimeWSMapping(
        message_type=MessageType.DELEGATED_EXECUTION_SIGNAL.value,
        semantic_family="transfer_delegated_execution",
        normalization_kind="delegated_execution_signal",
        routing_path="android_bridge.delegated_signal_ingress",
        truth_path="core.android_delegated_signal_ingress",
        handling_level="canonical",
    ),
    MessageType.FILE_TRANSFER.value: AndroidRuntimeWSMapping(
        message_type=MessageType.FILE_TRANSFER.value,
        semantic_family="transfer_signal",
        normalization_kind="file_transfer",
        routing_path="android_bridge.generic_forward",
        truth_path="compat_ingress_record",
        handling_level="compat-forwarded",
    ),
    MessageType.PEER_ANNOUNCE.value: AndroidRuntimeWSMapping(
        message_type=MessageType.PEER_ANNOUNCE.value,
        semantic_family="mesh_participation",
        normalization_kind="peer_announce",
        routing_path="android_bridge.generic_forward",
        truth_path="transport_coordination_input",
        handling_level="compat-forwarded",
    ),
    MessageType.PEER_EXCHANGE.value: AndroidRuntimeWSMapping(
        message_type=MessageType.PEER_EXCHANGE.value,
        semantic_family="mesh_participation",
        normalization_kind="peer_exchange",
        routing_path="android_bridge.generic_forward",
        truth_path="transport_coordination_input",
        handling_level="compat-forwarded",
    ),
    MessageType.MESH_TOPOLOGY.value: AndroidRuntimeWSMapping(
        message_type=MessageType.MESH_TOPOLOGY.value,
        semantic_family="mesh_participation",
        normalization_kind="mesh_topology",
        routing_path="android_bridge.generic_forward",
        truth_path="transport_coordination_input",
        handling_level="compat-forwarded",
    ),
}


def classify_android_runtime_ws_mapping(message_type: str) -> AndroidRuntimeWSMapping:
    kind = (message_type or "").strip().lower()
    default = AndroidRuntimeWSMapping(
        message_type=kind or "unknown",
        semantic_family="runtime_execution_or_compat",
        normalization_kind=kind or "unknown",
        routing_path="android_bridge.handler_dispatch",
        truth_path="runtime_router_or_compat_path",
        handling_level="bounded",
    )
    return _MAPPINGS.get(kind, default)
