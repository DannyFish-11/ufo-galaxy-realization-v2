"""
Android Bridge Integration Tests
=================================
Tests that the /ws/android and /ws/device/{device_id} WebSocket endpoints
are wired to the AIP v3.0 android_bridge and that message flows work correctly.

Covers:
  - AIP v3.0 message schema (version="3.0", type, device_id, message_id, timestamp)
  - device_register → device_register_ack flow
  - heartbeat → heartbeat_ack flow
  - task_execute → task_assign flow
  - agent_ping → heartbeat_ack flow
  - /ws/android endpoint exists in the gateway app
  - /ws/device/{device_id} endpoint exists in the gateway app
"""

import asyncio
import json
import sys
import os
import time
import uuid

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Timestamp used as a representative AIP v3.0 epoch-ms value in test messages
_TEST_TIMESTAMP_MS = int(time.time() * 1000)


# ---------------------------------------------------------------------------
# Helper: lightweight mock WebSocket for unit tests
# ---------------------------------------------------------------------------

class _MockWebSocket:
    """Minimal mock that satisfies android_bridge.handle_message() signature."""

    def __init__(self):
        self.sent: list = []

    async def send_json(self, data):
        self.sent.append(data)


def _make_msg(msg_type: str, device_id: str = "test_device_001", **extra):
    msg = {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": _TEST_TIMESTAMP_MS,
    }
    msg.update(extra)
    return msg


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Protocol schema tests
# ---------------------------------------------------------------------------

def test_aip_v3_message_schema():
    """AIP v3.0 server messages must carry version, type, device_id, message_id, timestamp."""
    from galaxy_gateway.android_bridge import MessageBuilder

    for builder_fn, kwargs in [
        (MessageBuilder.device_register_ack, {"device_id": "d1", "success": True}),
        (MessageBuilder.heartbeat_ack, {"device_id": "d1"}),
        (MessageBuilder.task_assign, {
            "device_id": "d1", "task_id": "t1", "task_type": "gui",
            "payload": {}, "priority": 5, "timeout": 30
        }),
    ]:
        msg = builder_fn(**kwargs)
        assert msg.get("version") == "3.0", f"Missing version in {msg}"
        assert "type" in msg
        assert "device_id" in msg
        assert "message_id" in msg
        assert "timestamp" in msg


# ---------------------------------------------------------------------------
# 2. device_register flow
# ---------------------------------------------------------------------------

def test_device_register_flow():
    """device_register message → device_register_ack with success=True."""
    from galaxy_gateway.android_bridge import AndroidBridge

    bridge = AndroidBridge()
    ws = _MockWebSocket()

    register_msg = _make_msg(
        "device_register",
        device_id="device_reg_test",
        device_type="android_phone",
        platform="android",
        model="Pixel 8",
        os_version="14",
        capabilities=0,
    )

    response = _run(bridge.handle_message(ws, register_msg))

    assert response is not None, "Expected a response to device_register"
    assert response["type"] == "device_register_ack"
    assert response["success"] is True
    assert response["version"] == "3.0"
    assert response["device_id"] == "device_reg_test"
    assert "session_id" in response


# ---------------------------------------------------------------------------
# 3. heartbeat flow
# ---------------------------------------------------------------------------

def test_heartbeat_flow():
    """heartbeat message → heartbeat_ack."""
    from galaxy_gateway.android_bridge import AndroidBridge

    bridge = AndroidBridge()
    ws = _MockWebSocket()

    heartbeat_msg = _make_msg("heartbeat", device_id="hb_device")
    response = _run(bridge.handle_message(ws, heartbeat_msg))

    assert response is not None, "Expected heartbeat_ack"
    assert response["type"] == "heartbeat_ack"
    assert response["version"] == "3.0"


# ---------------------------------------------------------------------------
# 4. task_execute flow
# ---------------------------------------------------------------------------

def test_task_execute_flow():
    """task_execute message → task_assign response."""
    from galaxy_gateway.android_bridge import AndroidBridge

    bridge = AndroidBridge()
    ws = _MockWebSocket()

    # Register device first
    _run(bridge.handle_message(ws, _make_msg("device_register", device_id="te_device")))

    execute_msg = _make_msg(
        "task_execute",
        device_id="te_device",
        task_id="task_execute_001",
        task_type="gui_automation",
        payload={"action": "open_app", "package": "com.example.app"},
    )
    response = _run(bridge.handle_message(ws, execute_msg))

    assert response is not None, "Expected task_assign response to task_execute"
    assert response["type"] == "task_assign"
    assert response["task_id"] == "task_execute_001"
    assert response["version"] == "3.0"


# ---------------------------------------------------------------------------
# 5. agent_ping flow
# ---------------------------------------------------------------------------

def test_agent_ping_flow():
    """agent_ping → heartbeat_ack."""
    from galaxy_gateway.android_bridge import AndroidBridge

    bridge = AndroidBridge()
    ws = _MockWebSocket()

    ping_msg = _make_msg("agent_ping", device_id="ping_device")
    response = _run(bridge.handle_message(ws, ping_msg))

    assert response is not None, "Expected heartbeat_ack for agent_ping"
    assert response["type"] == "heartbeat_ack"


# ---------------------------------------------------------------------------
# 6. /ws/android endpoint exists in gateway app
# ---------------------------------------------------------------------------

def test_ws_android_endpoint_registered():
    """The gateway FastAPI app must expose /ws/android."""
    from galaxy_gateway.main import app

    routes = {r.path for r in app.routes}
    assert "/ws/android" in routes, (
        f"/ws/android not found in routes: {sorted(routes)}"
    )


# ---------------------------------------------------------------------------
# 7. /ws/device/{device_id} endpoint exists in gateway app
# ---------------------------------------------------------------------------

def test_ws_device_endpoint_registered():
    """The gateway FastAPI app must expose /ws/device/{device_id}."""
    from galaxy_gateway.main import app

    routes = {r.path for r in app.routes}
    assert "/ws/device/{device_id}" in routes, (
        f"/ws/device/{{device_id}} not found in routes: {sorted(routes)}"
    )


# ---------------------------------------------------------------------------
# 8. Capability reporting — Android defaults include expected capabilities
# ---------------------------------------------------------------------------

def test_android_default_capabilities():
    """Android default capabilities must include GUI, touch and sensor flags."""
    from galaxy_gateway.android_bridge import DeviceCapability

    caps = DeviceCapability.get_android_default()
    caps_list = DeviceCapability.to_list(caps)

    expected = {"network", "gui_read", "gui_write", "gui_screenshot",
                "input_touch", "sensor_camera", "sensor_gps"}
    missing = expected - set(caps_list)
    assert not missing, f"Default capabilities missing: {missing}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
