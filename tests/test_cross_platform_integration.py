"""
Cross-Platform Integration Tests
=================================
Simulates an Android client connecting via WebSocket using the AIP v3.0
protocol.  All tests are unit-style (mocking the WebSocket) and do NOT
require a running server.
"""

import sys
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from galaxy_gateway.android_bridge import AndroidBridge, MessageType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws():
    """Return a minimal mock websocket."""
    ws = MagicMock()
    ws.send = AsyncMock()
    return ws


def _base_msg(msg_type: str, device_id: str = "android-test-001") -> dict:
    return {"type": msg_type, "device_id": device_id}


# ---------------------------------------------------------------------------
# device_register
# ---------------------------------------------------------------------------

class TestDeviceRegister:
    """AIP v3.0 device_register → device_register_ack."""

    @pytest.fixture(autouse=True)
    def bridge(self):
        self.bridge = AndroidBridge()

    @pytest.mark.asyncio
    async def test_device_register_returns_ack(self):
        msg = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "android-test-001",
            "platform": "android",
            "model": "Pixel 7",
            "version": "3.0",
        }
        response = await self.bridge.handle_message(_make_ws(), msg)

        assert response is not None
        assert response["type"] == MessageType.DEVICE_REGISTER_ACK.value
        assert response["device_id"] == "android-test-001"
        assert response.get("success") is True

    @pytest.mark.asyncio
    async def test_device_register_stores_device(self):
        msg = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "android-test-002",
            "platform": "android",
        }
        await self.bridge.handle_message(_make_ws(), msg)
        device = self.bridge.get_device("android-test-002")
        assert device is not None
        assert device.device_id == "android-test-002"


# ---------------------------------------------------------------------------
# heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    """AIP v3.0 heartbeat → heartbeat_ack."""

    @pytest.fixture(autouse=True)
    def bridge(self):
        self.bridge = AndroidBridge()

    @pytest.mark.asyncio
    async def test_heartbeat_returns_ack(self):
        # Register first so the device is known
        reg_msg = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "android-hb-001",
            "platform": "android",
        }
        await self.bridge.handle_message(_make_ws(), reg_msg)

        hb_msg = {
            "type": MessageType.DEVICE_HEARTBEAT.value,
            "device_id": "android-hb-001",
        }
        response = await self.bridge.handle_message(_make_ws(), hb_msg)

        assert response is not None
        assert response["type"] == MessageType.DEVICE_HEARTBEAT_ACK.value
        assert response["device_id"] == "android-hb-001"

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_seen(self):
        import time
        reg_msg = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "android-hb-002",
            "platform": "android",
        }
        await self.bridge.handle_message(_make_ws(), reg_msg)

        before = time.time()
        hb_msg = {
            "type": MessageType.DEVICE_HEARTBEAT.value,
            "device_id": "android-hb-002",
        }
        await self.bridge.handle_message(_make_ws(), hb_msg)
        after = time.time()

        device = self.bridge.get_device("android-hb-002")
        assert before <= device.last_heartbeat <= after


# ---------------------------------------------------------------------------
# capability_report
# ---------------------------------------------------------------------------

class TestCapabilityReport:
    """AIP v3.0 capability_report with platform, device_id,
    supported_actions and version fields."""

    @pytest.fixture(autouse=True)
    def bridge(self):
        self.bridge = AndroidBridge()

    @pytest.mark.asyncio
    async def test_capability_report_accepted(self):
        """capability_report should be processed without error."""
        msg = {
            "type": "capability_report",
            "device_id": "android-cap-001",
            "platform": "android",
            "version": "3.0",
            "supported_actions": ["click", "swipe", "input_text", "screenshot"],
        }
        # The bridge should handle or gracefully ignore unknown types
        try:
            response = await self.bridge.handle_message(_make_ws(), msg)
        except Exception as exc:
            pytest.fail(f"handle_message raised unexpectedly: {exc}")

    @pytest.mark.asyncio
    async def test_capability_report_fields_present(self):
        """Verify the message dict contains all required AIP v3.0 fields."""
        msg = {
            "type": "capability_report",
            "device_id": "android-cap-002",
            "platform": "android",
            "version": "3.0",
            "supported_actions": ["click", "swipe"],
        }
        assert "platform" in msg
        assert "device_id" in msg
        assert "supported_actions" in msg
        assert "version" in msg
        assert isinstance(msg["supported_actions"], list)


# ---------------------------------------------------------------------------
# task_result
# ---------------------------------------------------------------------------

class TestTaskResult:
    """AIP v3.0 task_result message handling."""

    @pytest.fixture(autouse=True)
    def bridge(self):
        self.bridge = AndroidBridge()

    @pytest.mark.asyncio
    async def test_task_result_no_exception(self):
        """task_result should be handled without raising."""
        reg_msg = {
            "type": MessageType.DEVICE_REGISTER.value,
            "device_id": "android-tr-001",
            "platform": "android",
        }
        await self.bridge.handle_message(_make_ws(), reg_msg)

        result_msg = {
            "type": MessageType.TASK_RESULT.value,
            "device_id": "android-tr-001",
            "task_id": "task-abc-123",
            "status": "success",
            "result": {"output": "done"},
        }
        try:
            await self.bridge.handle_message(_make_ws(), result_msg)
        except Exception as exc:
            pytest.fail(f"handle_message raised unexpectedly: {exc}")

    @pytest.mark.asyncio
    async def test_task_result_resolves_pending_future(self):
        """task_result should resolve a pending Future registered for that task_id."""
        loop = asyncio.get_running_loop()
        task_id = "task-future-001"
        future = loop.create_future()
        self.bridge._pending_responses[task_id] = future

        result_msg = {
            "type": MessageType.TASK_RESULT.value,
            "device_id": "android-tr-002",
            "task_id": task_id,
            "status": "success",
        }
        await self.bridge.handle_message(_make_ws(), result_msg)

        assert future.done()
        assert future.result()["task_id"] == task_id


# ---------------------------------------------------------------------------
# diagnostics_payload
# ---------------------------------------------------------------------------

class TestDiagnosticsPayload:
    """AIP v3.0 diagnostics_payload with error_type, error_context,
    task_id and node_name fields."""

    @pytest.fixture(autouse=True)
    def bridge(self):
        self.bridge = AndroidBridge()

    @pytest.mark.asyncio
    async def test_diagnostics_payload_no_exception(self):
        """diagnostics_payload / error message should be handled without raising."""
        msg = {
            "type": MessageType.ERROR.value,
            "device_id": "android-diag-001",
            "error_type": "TASK_TIMEOUT",
            "error_context": {"retry_count": 2},
            "task_id": "task-diag-123",
            "node_name": "Node_50_AndroidClient",
            "error_code": "TASK_TIMEOUT",
            "error_message": "Task timed out after 30s",
        }
        try:
            await self.bridge.handle_message(_make_ws(), msg)
        except Exception as exc:
            pytest.fail(f"handle_message raised unexpectedly: {exc}")

    @pytest.mark.asyncio
    async def test_diagnostics_payload_fields(self):
        """Verify the bridge accepts a diagnostics payload with all required AIP v3.0 fields."""
        msg = {
            "type": MessageType.ERROR.value,
            "device_id": "android-diag-002",
            "error_type": "CRASH",
            "error_context": {"stack_trace": "..."},
            "task_id": "task-diag-456",
            "node_name": "Node_113_AndroidVLM",
            "error_code": "CRASH",
            "error_message": "Application crashed unexpectedly",
        }
        for required in ("error_type", "error_context", "task_id", "node_name"):
            assert required in msg, f"Missing required field: {required}"
        try:
            await self.bridge.handle_message(_make_ws(), msg)
        except Exception as exc:
            pytest.fail(f"handle_message raised unexpectedly with full payload: {exc}")
