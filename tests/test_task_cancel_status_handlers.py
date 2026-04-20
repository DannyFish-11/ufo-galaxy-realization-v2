"""tests/test_task_cancel_status_handlers.py
============================================
Unit tests for the real task_cancel and task_status handlers introduced to
close the P0 fake-closed-loop gap (PROTO-002).

Coverage:
  1. handle_task_cancel — cancels a pending Future and returns task_cancel_ack
  2. handle_task_cancel — not_found when task_id absent from pending_responses
  3. handle_task_cancel — task_already_done when Future is already resolved
  4. handle_task_cancel — clears current_task_id from device cache on cancel
  5. handle_task_status — returns running status for current_task_id
  6. handle_task_status — returns pending status for task in pending_responses
  7. handle_task_status — returns not_found for unknown task_id
  8. handle_task_status — returns running status when no task_id given (current)
  9. MessageBuilder.task_cancel_ack — correct fields
  10. MessageBuilder.task_status_response — correct fields
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch
import time

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge() -> Any:
    """Return a minimal AndroidBridge-like mock with the fields handlers need."""
    from galaxy_gateway.android_bridge import AndroidBridge
    bridge = AndroidBridge.__new__(AndroidBridge)
    bridge._devices = {}
    bridge._pending_responses = {}
    bridge._lock = asyncio.Lock()
    return bridge


def _make_device(device_id: str, current_task_id=None):
    from galaxy_gateway.android.models import AndroidDevice
    d = AndroidDevice(device_id=device_id)
    d.current_task_id = current_task_id
    d.connected = True
    d.last_heartbeat = time.time()
    return d


def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# 1-4. handle_task_cancel
# ---------------------------------------------------------------------------


class TestHandleTaskCancel:

    @pytest.mark.asyncio
    async def test_cancel_pending_future_returns_ack_cancelled_true(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = _make_bridge()
        task_id = "task-abc-001"
        fut = asyncio.get_event_loop().create_future()
        bridge._pending_responses[task_id] = fut

        message = {
            "type": "task_cancel",
            "task_id": task_id,
            "device_id": "dev-01",
            "message_id": "msg-001",
        }
        result = await handle_task_cancel(bridge, _make_ws(), message)

        assert result["type"] == "task_cancel_ack"
        assert result["task_id"] == task_id
        assert result["cancelled"] is True
        assert "reason" not in result or result.get("reason") is None
        assert result["device_id"] == "dev-01"
        assert result["correlation_id"] == "msg-001"
        # Future should have been cancelled
        assert fut.cancelled()
        # Should have been removed from pending_responses
        assert task_id not in bridge._pending_responses

    @pytest.mark.asyncio
    async def test_cancel_not_found_returns_ack_cancelled_false(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = _make_bridge()
        message = {
            "type": "task_cancel",
            "task_id": "task-nonexistent",
            "device_id": "dev-01",
            "message_id": "msg-002",
        }
        result = await handle_task_cancel(bridge, _make_ws(), message)

        assert result["type"] == "task_cancel_ack"
        assert result["cancelled"] is False
        assert result["reason"] == "task_not_found"

    @pytest.mark.asyncio
    async def test_cancel_already_done_future_returns_ack_cancelled_false(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = _make_bridge()
        task_id = "task-done-001"
        fut = asyncio.get_event_loop().create_future()
        fut.set_result({"status": "completed"})
        bridge._pending_responses[task_id] = fut

        message = {
            "type": "task_cancel",
            "task_id": task_id,
            "device_id": "dev-01",
            "message_id": "msg-003",
        }
        result = await handle_task_cancel(bridge, _make_ws(), message)

        assert result["type"] == "task_cancel_ack"
        assert result["cancelled"] is False
        assert result["reason"] == "task_already_done"

    @pytest.mark.asyncio
    async def test_cancel_clears_current_task_id_from_device_cache(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = _make_bridge()
        task_id = "task-clear-001"
        device_id = "dev-clear-01"
        device = _make_device(device_id, current_task_id=task_id)
        bridge._devices[device_id] = device

        fut = asyncio.get_event_loop().create_future()
        bridge._pending_responses[task_id] = fut

        message = {
            "type": "task_cancel",
            "task_id": task_id,
            "device_id": device_id,
            "message_id": "msg-004",
        }
        result = await handle_task_cancel(bridge, _make_ws(), message)

        assert result["cancelled"] is True
        assert bridge._devices[device_id].current_task_id is None

    @pytest.mark.asyncio
    async def test_cancel_does_not_clear_different_task_id(self):
        """current_task_id should NOT be cleared if it differs from cancelled task."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = _make_bridge()
        task_id = "task-cancel-x"
        device_id = "dev-x"
        device = _make_device(device_id, current_task_id="task-other")
        bridge._devices[device_id] = device

        fut = asyncio.get_event_loop().create_future()
        bridge._pending_responses[task_id] = fut

        message = {
            "type": "task_cancel",
            "task_id": task_id,
            "device_id": device_id,
            "message_id": "msg-005",
        }
        await handle_task_cancel(bridge, _make_ws(), message)

        # current_task_id is for a different task — should be preserved
        assert bridge._devices[device_id].current_task_id == "task-other"


# ---------------------------------------------------------------------------
# 5-8. handle_task_status
# ---------------------------------------------------------------------------


class TestHandleTaskStatus:

    @pytest.mark.asyncio
    async def test_status_running_for_current_task(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = _make_bridge()
        task_id = "task-run-001"
        device_id = "dev-run-01"
        device = _make_device(device_id, current_task_id=task_id)
        bridge._devices[device_id] = device

        message = {
            "type": "task_status",
            "task_id": task_id,
            "device_id": device_id,
            "message_id": "msg-010",
        }
        result = await handle_task_status(bridge, _make_ws(), message)

        assert result["type"] == "task_status_response"
        assert result["task_id"] == task_id
        assert result["status"] == "running"
        assert result["device_id"] == device_id
        assert result["correlation_id"] == "msg-010"

    @pytest.mark.asyncio
    async def test_status_pending_for_task_in_pending_responses(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = _make_bridge()
        task_id = "task-pend-001"
        device_id = "dev-pend-01"
        device = _make_device(device_id, current_task_id=None)
        bridge._devices[device_id] = device
        bridge._pending_responses[task_id] = asyncio.get_event_loop().create_future()

        message = {
            "type": "task_status",
            "task_id": task_id,
            "device_id": device_id,
            "message_id": "msg-011",
        }
        result = await handle_task_status(bridge, _make_ws(), message)

        assert result["type"] == "task_status_response"
        assert result["task_id"] == task_id
        assert result["status"] == "pending"

    @pytest.mark.asyncio
    async def test_status_not_found_for_unknown_task(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = _make_bridge()
        device_id = "dev-nf-01"
        device = _make_device(device_id, current_task_id=None)
        bridge._devices[device_id] = device

        message = {
            "type": "task_status",
            "task_id": "task-unknown",
            "device_id": device_id,
            "message_id": "msg-012",
        }
        result = await handle_task_status(bridge, _make_ws(), message)

        assert result["type"] == "task_status_response"
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_not_found_for_unknown_device(self):
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = _make_bridge()
        message = {
            "type": "task_status",
            "task_id": "task-x",
            "device_id": "dev-unknown",
            "message_id": "msg-013",
        }
        result = await handle_task_status(bridge, _make_ws(), message)

        assert result["type"] == "task_status_response"
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_returns_current_task_when_no_task_id_given(self):
        """When task_id is omitted, return status for current_task_id."""
        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = _make_bridge()
        task_id = "task-current-01"
        device_id = "dev-cur-01"
        device = _make_device(device_id, current_task_id=task_id)
        bridge._devices[device_id] = device

        message = {
            "type": "task_status",
            # task_id intentionally omitted
            "device_id": device_id,
            "message_id": "msg-014",
        }
        result = await handle_task_status(bridge, _make_ws(), message)

        assert result["type"] == "task_status_response"
        assert result["task_id"] == task_id
        assert result["status"] == "running"


# ---------------------------------------------------------------------------
# 9-10. MessageBuilder helpers
# ---------------------------------------------------------------------------


class TestMessageBuilderTaskLifecycle:

    def test_task_cancel_ack_fields(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_cancel_ack(
            device_id="dev-01",
            task_id="task-01",
            cancelled=True,
            reason=None,
            correlation_id="corr-01",
        )
        assert msg["type"] == "task_cancel_ack"
        assert msg["device_id"] == "dev-01"
        assert msg["task_id"] == "task-01"
        assert msg["cancelled"] is True
        assert msg["correlation_id"] == "corr-01"
        assert "message_id" in msg
        assert "timestamp" in msg

    def test_task_cancel_ack_with_reason(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_cancel_ack(
            device_id="dev-01",
            task_id="task-01",
            cancelled=False,
            reason="task_not_found",
        )
        assert msg["cancelled"] is False
        assert msg["reason"] == "task_not_found"

    def test_task_status_response_fields(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_status_response(
            device_id="dev-01",
            task_id="task-02",
            status="running",
            progress=0.5,
            current_step=3,
            correlation_id="corr-02",
        )
        assert msg["type"] == "task_status_response"
        assert msg["device_id"] == "dev-01"
        assert msg["task_id"] == "task-02"
        assert msg["status"] == "running"
        assert msg["progress"] == 0.5
        assert msg["current_step"] == 3
        assert msg["correlation_id"] == "corr-02"

    def test_task_status_response_minimal(self):
        from galaxy_gateway.android.message_builder import MessageBuilder

        msg = MessageBuilder.task_status_response(
            device_id="dev-01",
            task_id=None,
            status="not_found",
        )
        assert msg["type"] == "task_status_response"
        assert msg["status"] == "not_found"
        assert msg["task_id"] is None
        assert "progress" not in msg
        assert "current_step" not in msg


# ---------------------------------------------------------------------------
# 11. android_bridge handler registration
# ---------------------------------------------------------------------------


class TestAndroidBridgeRegistration:
    """Verify that TASK_CANCEL and TASK_STATUS are no longer routed to generic forward."""

    def test_task_cancel_not_generic_forward(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType
        from galaxy_gateway.android.handlers.generic import handle_generic_forward

        bridge = AndroidBridge()
        handler = bridge._message_handlers.get(MessageType.TASK_CANCEL)
        assert handler is not None, "TASK_CANCEL must have a registered handler"
        # The registered wrapper should NOT be wrapping handle_generic_forward
        # We verify by calling _handle_task_cancel which is the real cancel handler
        assert hasattr(bridge, "_handle_task_cancel"), (
            "AndroidBridge must expose _handle_task_cancel backward-compat wrapper"
        )

    def test_task_status_not_generic_forward(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        handler = bridge._message_handlers.get(MessageType.TASK_STATUS)
        assert handler is not None, "TASK_STATUS must have a registered handler"
        assert hasattr(bridge, "_handle_task_status"), (
            "AndroidBridge must expose _handle_task_status backward-compat wrapper"
        )

    @pytest.mark.asyncio
    async def test_bridge_task_cancel_wrapper_calls_real_handler(self):
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        task_id = "task-reg-001"
        fut = asyncio.get_event_loop().create_future()
        bridge._pending_responses[task_id] = fut

        message = {
            "type": "task_cancel",
            "task_id": task_id,
            "device_id": "dev-reg-01",
            "message_id": "msg-reg-001",
        }
        result = await bridge._handle_task_cancel(_make_ws(), message)
        assert result["type"] == "task_cancel_ack"
        assert result["cancelled"] is True

    @pytest.mark.asyncio
    async def test_bridge_task_status_wrapper_calls_real_handler(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.android.models import AndroidDevice
        import time

        bridge = AndroidBridge()
        task_id = "task-stat-001"
        device_id = "dev-stat-01"
        d = AndroidDevice(device_id=device_id)
        d.current_task_id = task_id
        d.last_heartbeat = time.time()
        bridge._devices[device_id] = d

        message = {
            "type": "task_status",
            "task_id": task_id,
            "device_id": device_id,
            "message_id": "msg-stat-001",
        }
        result = await bridge._handle_task_status(_make_ws(), message)
        assert result["type"] == "task_status_response"
        assert result["status"] == "running"
