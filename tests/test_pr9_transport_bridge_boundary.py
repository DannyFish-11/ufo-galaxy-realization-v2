from __future__ import annotations

import pytest

try:
    from galaxy_gateway.android.handlers.generic import (
        handle_generic_forward,
        is_generic_forward_blocked_message_type,
    )
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
    ("msg_type", "handler_suffix"),
    [
        ("device_readiness_report", "handle_evaluator_artifact_report"),
        ("device_governance_report", "handle_evaluator_artifact_report"),
        ("device_strategy_report", "handle_evaluator_artifact_report"),
        ("device_acceptance_report", "handle_device_acceptance_report"),
        ("device_state_snapshot", "handle_device_state_snapshot"),
        ("device_execution_event", "handle_device_execution_event"),
    ],
)
async def test_generic_forward_rejects_canonical_ingress_message_types(
    msg_type: str, handler_suffix: str
) -> None:
    bridge = AndroidBridge()
    resp = await handle_generic_forward(
        bridge,
        None,
        {"type": msg_type, "device_id": "dev-transport", "message_id": f"msg-{msg_type}"},
    )

    assert is_generic_forward_blocked_message_type(msg_type) is True
    assert resp["type"] == "error"
    assert resp["status"] == "rejected"
    assert resp["error_code"] == "CANONICAL_INGRESS_REQUIRED"
    assert resp["canonical_ingress_required"] is True
    assert resp["original_type"] == msg_type
    assert resp["canonical_ingress_handler"].endswith(handler_suffix)


@_skip_if_unavailable
def test_android_bridge_routes_canonical_reports_away_from_generic_forward() -> None:
    bridge = AndroidBridge()
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
