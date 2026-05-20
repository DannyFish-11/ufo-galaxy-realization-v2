from __future__ import annotations

import pytest
from unittest.mock import MagicMock

try:
    from galaxy_gateway.android.handlers.generic import (
        get_generic_forward_compat_allowlist,
        handle_generic_forward,
        is_generic_forward_compat_message_type,
        is_generic_forward_blocked_message_type,
    )
    from galaxy_gateway.android.runtime_ws_profile import classify_android_runtime_ws_mapping
    from galaxy_gateway.android_bridge import AndroidBridge
    from galaxy_gateway.protocol.aip_v3 import MessageType

    _AVAILABLE = True
except Exception:  # pragma: no cover
    _AVAILABLE = False


_skip_if_unavailable = pytest.mark.skipif(
    not _AVAILABLE, reason="transport bridge boundary dependencies unavailable"
)


@pytest.mark.asyncio
@_skip_if_unavailable
@pytest.mark.parametrize(
    ("msg_type", "handler_name"),
    [
        ("device_readiness_report", "android_evaluator_artifact_ingress"),
        ("device_governance_report", "android_evaluator_artifact_ingress"),
        ("device_strategy_report", "android_evaluator_artifact_ingress"),
        ("device_acceptance_report", "android_acceptance_report_ingress"),
        ("device_state_snapshot", "android_device_state_snapshot_ingress"),
        ("device_execution_event", "android_device_execution_event_ingress"),
    ],
)
async def test_generic_forward_rejects_canonical_ingress_message_types(
    msg_type: str, handler_name: str
) -> None:
    bridge = AndroidBridge()
    websocket = MagicMock()
    resp = await handle_generic_forward(
        bridge,
        websocket,
        {"type": msg_type, "device_id": "dev-transport", "message_id": f"msg-{msg_type}"},
    )

    assert is_generic_forward_blocked_message_type(msg_type)
    assert resp["type"] == "error"
    assert resp["status"] == "rejected"
    assert resp["error_code"] == "CANONICAL_INGRESS_REQUIRED"
    assert resp["canonical_ingress_required"] is True
    assert resp["original_type"] == msg_type
    assert resp["canonical_ingress_handler"] == handler_name


@pytest.mark.asyncio
@_skip_if_unavailable
@pytest.mark.parametrize(
    "msg_type",
    [
        "agent_config_update",
        "agent_restart",
        "ui_tree_request",
        "action_execute",
        "action_sequence_execute",
        "app_start",
        "app_stop",
        "system_command",
        "cancel_result",
    ],
)
async def test_generic_forward_accepts_whitelisted_types(msg_type: str) -> None:
    bridge = AndroidBridge()
    websocket = MagicMock()
    resp = await handle_generic_forward(
        bridge,
        websocket,
        {"type": msg_type, "device_id": "dev-transport", "message_id": f"msg-{msg_type}"},
    )

    assert is_generic_forward_compat_message_type(msg_type)
    assert resp["status"] == "received"
    assert resp["type"] == f"{msg_type}_ack"


@pytest.mark.asyncio
@_skip_if_unavailable
async def test_generic_forward_rejects_non_whitelisted_type() -> None:
    bridge = AndroidBridge()
    websocket = MagicMock()
    resp = await handle_generic_forward(
        bridge,
        websocket,
        {"type": "unclassified_compat_probe", "device_id": "dev-transport", "message_id": "msg-x"},
    )

    assert not is_generic_forward_compat_message_type("unclassified_compat_probe")
    assert resp["type"] == "error"
    assert resp["status"] == "rejected"
    assert resp["error_code"] == "GENERIC_FORWARD_TYPE_NOT_ALLOWED"
    assert resp["allowed_compat_types"] == list(get_generic_forward_compat_allowlist())


@_skip_if_unavailable
def test_android_bridge_routes_canonical_reports_away_from_generic_forward() -> None:
    bridge = AndroidBridge()
    assert MessageType.AGENT_CONFIG_UPDATE in bridge._message_handlers
    generic_handler = bridge._message_handlers[MessageType.AGENT_CONFIG_UPDATE]

    for msg_type in (
        MessageType.DEVICE_READINESS_REPORT,
        MessageType.DEVICE_GOVERNANCE_REPORT,
        MessageType.DEVICE_STRATEGY_REPORT,
        MessageType.DEVICE_ACCEPTANCE_REPORT,
        MessageType.DEVICE_STATE_SNAPSHOT,
        MessageType.DEVICE_EXECUTION_EVENT,
    ):
        assert bridge._message_handlers[msg_type] is not generic_handler


@_skip_if_unavailable
def test_generic_forward_allowlist_is_explicit_and_stable() -> None:
    expected = {
        "agent_config_update",
        "agent_restart",
        "ui_tree_request",
        "action_execute",
        "action_sequence_execute",
        "app_start",
        "app_stop",
        "system_command",
        "cancel_result",
    }
    assert set(get_generic_forward_compat_allowlist()) == expected


@_skip_if_unavailable
def test_runtime_ws_profile_keeps_governance_truth_and_transport_off_generic_forward() -> None:
    expected_paths = {
        MessageType.FILE_TRANSFER: "galaxy_gateway.android.handlers.file_transfer.handle_file_transfer",
        MessageType.PEER_ANNOUNCE: "galaxy_gateway.android.handlers.peer_exchange.handle_peer_announce",
        MessageType.PEER_EXCHANGE: "galaxy_gateway.android.handlers.peer_exchange.handle_peer_exchange",
        MessageType.MESH_TOPOLOGY: "galaxy_gateway.android.handlers.mesh_topology.handle_mesh_topology",
    }
    for msg_type in (
        MessageType.DEVICE_READINESS_REPORT,
        MessageType.DEVICE_GOVERNANCE_REPORT,
        MessageType.DEVICE_STRATEGY_REPORT,
        MessageType.DEVICE_ACCEPTANCE_REPORT,
        MessageType.DEVICE_STATE_SNAPSHOT,
        MessageType.DEVICE_EXECUTION_EVENT,
        *expected_paths.keys(),
    ):
        mapping = classify_android_runtime_ws_mapping(msg_type.value)
        assert "generic_forward" not in mapping.routing_path
        if msg_type in expected_paths:
            assert mapping.routing_path == expected_paths[msg_type]
