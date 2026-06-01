"""
tests/test_cross_device_hardening.py
=====================================

Server-side cross-device collaboration hardening tests.

Covers all requirements from the AIP v3 / Android client runtime alignment:

1. Protocol SSOT — aip_v3.py MessageType is the canonical source;
   android_bridge imports from it (not a local copy).
2. AIP v3 serialization — key message types round-trip correctly.
3. Android WebSocket routing — /ws/android/{device_id} and /ws/android
   route messages through android_bridge (not the generic WebSocketManager).
4. Device registration — ack returned; structured error on failure.
5. Heartbeat handling — ack returned for registered and unregistered devices.
6. Task lifecycle — task_submit → task_assign → task_progress →
   task_result → task_end.
7. Results routed back to originating device.
8. OpenClawd memory backflow — completed tasks stored with route_mode / device_id.
9. WebRTC gateway — /api/v1/webrtc/endpoint and /ws/webrtc/{device_id} health.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ws() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _msg(msg_type: str, device_id: str, **extra) -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "message_id": str(uuid.uuid4()),
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        **extra,
    }


# ===========================================================================
# 1. Protocol SSOT
# ===========================================================================

class TestProtocolSSOT:
    """android_bridge must import MessageType from aip_v3.py, not redefine it."""

    def test_android_bridge_uses_aip_v3_message_type(self):
        """The MessageType class used inside android_bridge IS the aip_v3 class."""
        from galaxy_gateway.android_bridge import MessageType as BridgeMT
        from galaxy_gateway.protocol.aip_v3 import MessageType as V3MT

        assert BridgeMT is V3MT, (
            "android_bridge.MessageType must be imported from aip_v3, not a separate copy"
        )

    def test_android_bridge_uses_aip_v3_task_status(self):
        from galaxy_gateway.android_bridge import TaskStatus as BridgeTS
        from galaxy_gateway.protocol.aip_v3 import TaskStatus as V3TS

        assert BridgeTS is V3TS

    def test_android_bridge_uses_aip_v3_result_status(self):
        from galaxy_gateway.android_bridge import ResultStatus as BridgeRS
        from galaxy_gateway.protocol.aip_v3 import ResultStatus as V3RS

        assert BridgeRS is V3RS

    def test_task_execute_present_in_aip_v3(self):
        """TASK_EXECUTE must be present in aip_v3.py MessageType (used by android_bridge)."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TASK_EXECUTE == "task_execute"

    def test_task_end_present_in_aip_v3(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TASK_END == "task_end"

    def test_device_status_present_in_aip_v3(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.DEVICE_STATUS == "device_status"


# ===========================================================================
# 2. AIP v3 Protocol Serialization
# ===========================================================================

class TestAIPv3Serialization:
    """Key AIP v3 message types must serialize / deserialize correctly."""

    def test_aip_message_round_trip_heartbeat(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType, parse_message
        msg = AIPMessage(type=MessageType.DEVICE_HEARTBEAT, device_id="dev-001")
        raw = msg.model_dump_json()
        restored = parse_message(raw)
        assert restored.type == MessageType.DEVICE_HEARTBEAT
        assert restored.device_id == "dev-001"
        assert restored.version == "3.0"

    def test_aip_message_round_trip_task_assign(self):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType, Command, parse_message
        cmd = Command(tool_name="screenshot", tool_type="data_collection", parameters={})
        msg = AIPMessage(
            type=MessageType.TASK_ASSIGN,
            device_id="dev-002",
            task_id="task-xyz",
            commands=[cmd],
        )
        raw = msg.model_dump_json()
        restored = parse_message(raw)
        assert restored.type == MessageType.TASK_ASSIGN
        assert restored.task_id == "task-xyz"
        assert len(restored.commands) == 1
        assert restored.commands[0].tool_name == "screenshot"

    def test_message_type_values_stable(self):
        """Wire-format values must not change — clients depend on them."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.DEVICE_REGISTER.value == "device_register"
        assert MessageType.DEVICE_HEARTBEAT.value == "heartbeat"
        assert MessageType.DEVICE_HEARTBEAT_ACK.value == "heartbeat_ack"
        assert MessageType.TASK_SUBMIT.value == "task_submit"
        assert MessageType.TASK_ASSIGN.value == "task_assign"
        assert MessageType.TASK_PROGRESS.value == "task_progress"
        assert MessageType.TASK_RESULT.value == "task_result"
        assert MessageType.TASK_END.value == "task_end"
        assert MessageType.TASK_EXECUTE.value == "task_execute"
        assert MessageType.ERROR.value == "error"

    def test_task_status_values_stable(self):
        from galaxy_gateway.protocol.aip_v3 import TaskStatus
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.RUNNING.value == "running"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"

    def test_result_status_values_stable(self):
        from galaxy_gateway.protocol.aip_v3 import ResultStatus
        assert ResultStatus.SUCCESS.value == "success"
        assert ResultStatus.FAILURE.value == "failure"
        assert ResultStatus.TIMEOUT.value == "timeout"

    def test_aip_message_defaults(self):
        """AIPMessage must auto-generate message_id and default version to '3.0'."""
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        msg = AIPMessage(type=MessageType.DEVICE_HEARTBEAT, device_id="dev")
        assert msg.version == "3.0"
        assert len(msg.message_id) > 0


# ===========================================================================
# 3. Android WebSocket routing through android_bridge
# ===========================================================================

class TestAndroidWSRouting:
    """
    /ws/android/{device_id} and /ws/android must route through android_bridge.
    Test using the gateway FastAPI app TestClient.
    """

    @pytest.fixture(scope="class")
    def gw_client(self):
        from galaxy_gateway.app import app as gateway_app
        from fastapi.testclient import TestClient
        with TestClient(gateway_app) as c:
            yield c

    def _register_and_heartbeat(self, client, path: str) -> Dict[str, Any]:
        device_id = f"hb-{uuid.uuid4().hex[:8]}"
        url = path.format(device_id=device_id)

        with client.websocket_connect(url) as ws:
            # register first
            ws.send_text(json.dumps(_msg("device_register", device_id,
                                        platform="android", model="TestPhone")))
            reg_resp = ws.receive_json()
            # then heartbeat
            ws.send_text(json.dumps(_msg("heartbeat", device_id)))
            hb_resp = ws.receive_json()

        return {"register": reg_resp, "heartbeat": hb_resp, "device_id": device_id}

    def test_android_primary_path_returns_register_ack(self, gw_client):
        """/ws/android/{device_id} returns device_register_ack."""
        r = self._register_and_heartbeat(gw_client, "/ws/android/{device_id}")
        assert r["register"]["type"] == "device_register_ack"
        assert r["register"]["success"] is True

    def test_android_primary_path_returns_heartbeat_ack(self, gw_client):
        """/ws/android/{device_id} returns heartbeat_ack."""
        r = self._register_and_heartbeat(gw_client, "/ws/android/{device_id}")
        assert r["heartbeat"]["type"] == "heartbeat_ack"

    def test_android_fallback_path_returns_register_ack(self, gw_client):
        """/ws/android?device_id=... returns device_register_ack."""
        device_id = f"fb-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/android?device_id={device_id}") as ws:
            ws.send_text(json.dumps(_msg("device_register", device_id, platform="android")))
            resp = ws.receive_json()
        assert resp["type"] == "device_register_ack"
        assert resp["success"] is True

    def test_android_fallback_path_heartbeat_ack(self, gw_client):
        """/ws/android?device_id=... returns heartbeat_ack."""
        device_id = f"fb2-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/android?device_id={device_id}") as ws:
            ws.send_text(json.dumps(_msg("heartbeat", device_id)))
            resp = ws.receive_json()
        assert resp["type"] == "heartbeat_ack"

    def test_android_auto_device_id_heartbeat_ack(self, gw_client):
        """/ws/android without device_id returns heartbeat_ack."""
        with gw_client.websocket_connect("/ws/android") as ws:
            ws.send_text(json.dumps({
                "version": "3.0",
                "type": "heartbeat",
                "device_id": "auto-dev",
            }))
            resp = ws.receive_json()
        assert resp["type"] == "heartbeat_ack"

    def test_android_path_rejects_unknown_type(self, gw_client):
        """/ws/android/{device_id} returns error for unknown message type."""
        device_id = f"err-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/android/{device_id}") as ws:
            ws.send_text(json.dumps(_msg("not_a_real_type", device_id)))
            resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp.get("error_code") == "UNKNOWN_MESSAGE_TYPE"

    def test_android_path_rejects_missing_device_id(self, gw_client):
        """/ws/android/{device_id} returns error when device_id absent from payload."""
        device_id = f"noid-{uuid.uuid4().hex[:8]}"
        with gw_client.websocket_connect(f"/ws/android/{device_id}") as ws:
            ws.send_text(json.dumps({
                "version": "3.0",
                "type": "heartbeat",
                # intentionally missing device_id
            }))
            resp = ws.receive_json()
        assert resp["type"] == "error"
        assert resp.get("error_code") == "MISSING_REQUIRED_FIELDS"


# ===========================================================================
# 4. Device registration and heartbeat handling (unit tests)
# ===========================================================================

class TestDeviceRegistrationAndHeartbeat:
    """Device registration ack, failure handling, and heartbeat edge-cases."""

    @pytest.fixture()
    def bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_register_success(self, bridge):
        ws = _ws()
        resp = await bridge.handle_message(ws, _msg(
            "device_register", "dev-001", platform="android", model="Pixel"
        ))
        assert resp["type"] == "device_register_ack"
        assert resp["success"] is True
        assert "session_id" in resp
        assert bridge.get_device("dev-001") is not None

    @pytest.mark.asyncio
    async def test_register_ack_contains_device_id(self, bridge):
        ws = _ws()
        resp = await bridge.handle_message(ws, _msg(
            "device_register", "dev-ack", platform="android"
        ))
        assert resp["device_id"] == "dev-ack"

    @pytest.mark.asyncio
    async def test_heartbeat_known_device_updates_timestamp(self, bridge):
        ws = _ws()
        # register first
        await bridge.handle_message(ws, _msg("device_register", "dev-hb"))
        device = bridge.get_device("dev-hb")
        old_ts = device.last_heartbeat

        await asyncio.sleep(0.01)
        resp = await bridge.handle_message(ws, _msg("heartbeat", "dev-hb"))

        assert resp["type"] == "heartbeat_ack"
        assert device.last_heartbeat >= old_ts

    @pytest.mark.asyncio
    async def test_heartbeat_unknown_device_still_returns_ack(self, bridge):
        """Heartbeat from an unregistered device must still get heartbeat_ack."""
        ws = _ws()
        resp = await bridge.handle_message(ws, _msg("heartbeat", "unknown-dev-999"))
        assert resp is not None
        assert resp["type"] == "heartbeat_ack"

    @pytest.mark.asyncio
    async def test_register_missing_device_id_returns_error(self, bridge):
        ws = _ws()
        resp = await bridge.handle_message(ws, {
            "version": "3.0",
            "type": "device_register",
            "message_id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
        })
        assert resp["type"] == "error"
        assert resp["error_code"] == "MISSING_REQUIRED_FIELDS"

    @pytest.mark.asyncio
    async def test_device_status_update_returns_ack(self, bridge):
        """device_status messages get a device_status_ack response."""
        ws = _ws()
        await bridge.handle_message(ws, _msg("device_register", "dev-st"))
        resp = await bridge.handle_message(ws, _msg(
            "device_status", "dev-st",
            status={"battery": 85, "cpu": 32},
        ))
        assert resp is not None
        assert resp["type"] == "device_status_ack"


# ===========================================================================
# 5. Task lifecycle
# ===========================================================================

class TestTaskLifecycle:
    """
    Full task lifecycle: task_submit → task_assign → task_progress →
    task_result → task_end.
    """

    @pytest.fixture()
    def bridge(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    @pytest.mark.asyncio
    async def test_task_assign_sends_to_device(self, bridge):
        """assign_task() sends a task_assign message to the registered device."""
        ws = _ws()
        device_id = "lc-dev-001"
        task_id = str(uuid.uuid4())

        # Register device; suppress DeviceRouter session sync so the device is
        # only in bridge._devices (not in DeviceRouter).  This ensures
        # assign_task takes the bridge.send_to_device fallback path, which is
        # what this test exercises.
        with patch.object(bridge, "_sync_device_router_session"):
            await bridge.handle_message(ws, _msg("device_register", device_id))

        # Wire the device's websocket so assign_task can send
        device = bridge.get_device(device_id)
        device.websocket = ws

        sent: Dict[str, Any] = {}

        async def _capture_send(d_id, msg, **kwargs):
            sent.update(msg)
            return {"success": True}

        bridge.send_to_device = _capture_send

        await bridge.assign_task(
            device_id=device_id,
            task_id=task_id,
            task_type="screenshot",
            payload={"quality": 90},
        )

        assert sent.get("type") == "task_assign"
        assert sent.get("task_id") == task_id
        assert sent.get("device_id") == device_id
        assert sent.get("task_type") == "screenshot"

    @pytest.mark.asyncio
    async def test_task_progress_logged(self, bridge):
        """task_progress message is handled without error."""
        ws = _ws()
        device_id = "prog-dev"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))
        resp = await bridge.handle_message(ws, _msg(
            "task_progress", device_id, task_id=task_id, progress=50
        ))
        # task_progress handler returns None (no ack required by spec)
        assert resp is None

    @pytest.mark.asyncio
    async def test_task_result_completes_future(self, bridge):
        """task_result resolves the pending Future registered by assign_task."""
        ws = _ws()
        device_id = "res-dev-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))

        # Manually insert a pending future as assign_task would
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        result_msg = _msg(
            "task_result", device_id,
            task_id=task_id,
            status="completed",
            route_mode="cross_device",
        )
        await bridge.handle_message(ws, result_msg)

        assert future.done()
        resolved = future.result()
        assert resolved["task_id"] == task_id
        assert resolved["status"] == "completed"

    @pytest.mark.asyncio
    async def test_task_result_clears_current_task_id(self, bridge):
        """After task_result, device.current_task_id is cleared."""
        ws = _ws()
        device_id = "clr-dev-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))
        device = bridge.get_device(device_id)
        device.current_task_id = task_id

        await bridge.handle_message(ws, _msg(
            "task_result", device_id, task_id=task_id, status="completed"
        ))

        assert device.current_task_id is None

    @pytest.mark.asyncio
    async def test_task_end_returns_ack(self, bridge):
        """task_end message returns task_end_ack."""
        ws = _ws()
        device_id = "end-dev-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))
        resp = await bridge.handle_message(ws, _msg(
            "task_end", device_id, task_id=task_id, status="completed"
        ))

        assert resp is not None
        assert resp["type"] == "task_end_ack"
        assert resp["task_id"] == task_id
        assert resp["device_id"] == device_id

    @pytest.mark.asyncio
    async def test_task_end_clears_current_task_id(self, bridge):
        """task_end clears device.current_task_id."""
        ws = _ws()
        device_id = "end-clr-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))
        device = bridge.get_device(device_id)
        device.current_task_id = task_id

        await bridge.handle_message(ws, _msg(
            "task_end", device_id, task_id=task_id, status="completed"
        ))

        assert device.current_task_id is None

    @pytest.mark.asyncio
    async def test_task_end_resolves_pending_future_when_no_prior_result(self, bridge):
        """task_end resolves the pending Future if task_result was not received."""
        ws = _ws()
        device_id = "end-fut-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        bridge._pending_responses[task_id] = future

        await bridge.handle_message(ws, _msg(
            "task_end", device_id, task_id=task_id, status="completed"
        ))

        assert future.done()


# ===========================================================================
# 6. OpenClawd memory backflow
# ===========================================================================

class TestOpenClawdMemoryBackflow:
    """Completed tasks are stored in memory DB with device_id and route_mode."""

    @pytest.mark.asyncio
    async def test_store_task_result_calls_task_memory(self):
        """store_task_result() calls TaskMemory.record_task with correct metadata."""
        from core.openclawd_memory_backflow import store_task_result

        recorded = []

        class MockTaskMemory:
            def record_task(self, task, result_summary="", success=True,
                            strategy="", session_id="", tags=None, extra=None):
                recorded.append({
                    "task": task,
                    "result_summary": result_summary,
                    "success": success,
                    "strategy": strategy,
                    "tags": tags or [],
                    "extra": extra or {},
                })

        with patch("core.openclawd_memory_backflow.get_task_memory",
                   return_value=MockTaskMemory()):
            await store_task_result(
                task_id="t-001",
                device_id="dev-bf-001",
                route_mode="cross_device",
                result={"status": "completed", "task_type": "screenshot"},
            )

        assert len(recorded) == 1
        rec = recorded[0]
        assert rec["extra"]["task_id"] == "t-001"
        assert rec["extra"]["device_id"] == "dev-bf-001"
        assert rec["extra"]["route_mode"] == "cross_device"
        assert rec["success"] is True
        assert "cross_device" in rec["tags"]
        assert "dev-bf-001" in rec["tags"]

    @pytest.mark.asyncio
    async def test_store_task_result_handles_failure_status(self):
        """store_task_result() stores success=False for failed tasks."""
        from core.openclawd_memory_backflow import store_task_result

        recorded = []

        class MockTaskMemory:
            def record_task(self, task, result_summary="", success=True,
                            strategy="", session_id="", tags=None, extra=None):
                recorded.append({"success": success})

        with patch("core.openclawd_memory_backflow.get_task_memory",
                   return_value=MockTaskMemory()):
            await store_task_result(
                task_id="t-002",
                device_id="dev-002",
                route_mode="cross_device",
                result={"status": "failed"},
            )

        assert recorded[0]["success"] is False

    @pytest.mark.asyncio
    async def test_task_result_triggers_backflow_in_bridge(self):
        """
        When android_bridge processes a task_result, it invokes the memory
        backflow module.  If the module is unavailable the bridge must not
        raise.
        """
        from core.durable_result_idempotency import reset_durable_result_id_store
        from galaxy_gateway.android_bridge import AndroidBridge

        # Reset durable idempotency singleton so a fresh uuid task_id is never
        # seen as a duplicate (the store is file-backed and persists across runs).
        reset_durable_result_id_store()

        bridge = AndroidBridge()
        ws = _ws()
        device_id = "bf-bridge-001"
        task_id = str(uuid.uuid4())

        await bridge.handle_message(ws, _msg("device_register", device_id))

        backflow_called = []

        async def _mock_store(task_id, device_id, route_mode, result, **kw):
            backflow_called.append({"task_id": task_id, "device_id": device_id,
                                    "route_mode": route_mode})

        # store_task_result is imported and called inside task_lifecycle.py;
        # patch the reference there (not the android_bridge module-level alias).
        with patch("galaxy_gateway.android.handlers.task_lifecycle.store_task_result",
                   _mock_store):
            await bridge.handle_message(ws, _msg(
                "task_result", device_id,
                task_id=task_id,
                status="completed",
                route_mode="cross_device",
            ))

        # Verify backflow was called with correct params
        assert len(backflow_called) == 1
        assert backflow_called[0]["task_id"] == task_id
        assert backflow_called[0]["device_id"] == device_id
        assert backflow_called[0]["route_mode"] == "cross_device"

    @pytest.mark.asyncio
    async def test_backflow_is_resilient_to_missing_module(self):
        """store_task_result() must not raise when task_memory raises an exception."""
        from core.openclawd_memory_backflow import store_task_result

        class _BrokenMemory:
            def record_task(self, *a, **kw):
                raise RuntimeError("DB unavailable")

        # Simulate record_task raising
        with patch("core.openclawd_memory_backflow.get_task_memory",
                   return_value=_BrokenMemory()):
            # Should not raise
            await store_task_result(
                task_id="safe-task",
                device_id="safe-dev",
                route_mode="local",
                result={"status": "completed"},
            )


# ===========================================================================
# 7. WebRTC gateway health checks
# ===========================================================================

class TestWebRTCGatewayHealth:
    """
    Verify /api/v1/webrtc/endpoint is wired and Node_95 signaling passthrough
    health can be detected.
    """

    @pytest.mark.asyncio
    async def test_check_node95_reachable_returns_bool(self):
        """check_node95_reachable() returns a boolean regardless of state."""
        from galaxy_gateway.webrtc_proxy import check_node95_reachable
        result = await check_node95_reachable()
        assert isinstance(result, bool)

    def test_webrtc_endpoint_info_structure(self):
        """get_webrtc_endpoint_info() returns required keys."""
        from galaxy_gateway.webrtc_proxy import get_webrtc_endpoint_info
        info = get_webrtc_endpoint_info()
        assert "node95_url" in info
        assert "gateway_ws_url" in info
        assert "gateway_ws_path" in info
        assert "ws_signaling_path" in info
        assert "{device_id}" in info["gateway_ws_path"]

    def test_webrtc_endpoint_rest_route_exists(self):
        """GET /api/v1/webrtc/endpoint route must exist in the gateway app."""
        from galaxy_gateway.app import app as gateway_app
        routes = [r.path for r in gateway_app.routes]  # type: ignore[attr-defined]
        assert "/api/v1/webrtc/endpoint" in routes

    def test_webrtc_ws_route_exists(self):
        """WebSocket /ws/webrtc/{device_id} route must exist in the gateway app."""
        from galaxy_gateway.app import app as gateway_app
        routes = [r.path for r in gateway_app.routes]  # type: ignore[attr-defined]
        assert "/ws/webrtc/{device_id}" in routes


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
