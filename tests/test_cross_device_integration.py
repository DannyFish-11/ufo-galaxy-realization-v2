"""
Galaxy Cross-Device Integration Tests
Simulates the full Android <-> Server handshake sequence over AIP v3.0.

Tests call android_bridge.AndroidBridge.handle_message() directly with a
mocked WebSocket; no running server is required.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from galaxy_gateway.android_bridge import AndroidBridge, MessageType


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bridge():
    return AndroidBridge()


@pytest.fixture
def mock_ws():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


DEVICE_ID = "test-android-device-001"


# ---------------------------------------------------------------------------
# 1. device_register -> device_register_ack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_device_register_ack(bridge, mock_ws):
    """Sending device_register (version 3.0) must return device_register_ack."""
    message = {
        "type": "device_register",
        "version": "3.0",
        "device_id": DEVICE_ID,
        "device_type": "android_phone",
        "platform": "android",
        "model": "Pixel 7",
    }

    response = await bridge.handle_message(mock_ws, message)

    assert response is not None, "Expected a response for device_register"
    assert response["type"] == MessageType.DEVICE_REGISTER_ACK.value
    assert response["success"] is True
    assert response["device_id"] == DEVICE_ID


# ---------------------------------------------------------------------------
# 2. capability_report -> accepted and persisted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capability_report_accepted(bridge, mock_ws):
    """Sending capability_report must be accepted and supported_actions persisted."""
    # Register the device first so the bridge knows about it
    await bridge.handle_message(mock_ws, {
        "type": "device_register",
        "version": "3.0",
        "device_id": DEVICE_ID,
        "platform": "android",
    })

    message = {
        "type": "capability_report",
        "device_id": DEVICE_ID,
        "platform": "android",
        "supported_actions": ["tap", "swipe", "screenshot", "input_text"],
        "version": "3.0",
    }

    response = await bridge.handle_message(mock_ws, message)

    assert response is not None, "Expected a response for capability_report"
    assert response.get("accepted") is True
    assert response["type"] == MessageType.CAPABILITY_REPORT_ACK.value

    # Verify supported_actions were persisted on the device
    device = bridge.get_device(DEVICE_ID)
    assert device is not None
    assert device.supported_actions == ["tap", "swipe", "screenshot", "input_text"]


# ---------------------------------------------------------------------------
# 3. heartbeat -> heartbeat_ack
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_heartbeat_ack(bridge, mock_ws):
    """Sending heartbeat must return heartbeat_ack."""
    # Register first
    await bridge.handle_message(mock_ws, {
        "type": "device_register",
        "version": "3.0",
        "device_id": DEVICE_ID,
        "platform": "android",
    })

    message = {
        "type": "heartbeat",
        "device_id": DEVICE_ID,
        "version": "3.0",
    }

    response = await bridge.handle_message(mock_ws, message)

    assert response is not None, "Expected a response for heartbeat"
    assert response["type"] == MessageType.DEVICE_HEARTBEAT_ACK.value
    assert response["device_id"] == DEVICE_ID


# ---------------------------------------------------------------------------
# 4. task_result -> processed (fire-and-forget, returns None)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_task_result_processed(bridge, mock_ws):
    """Sending task_result must be processed without raising an exception."""
    message = {
        "type": "task_result",
        "device_id": DEVICE_ID,
        "task_id": "task-42",
        "status": "completed",
        "result": {"output": "ok"},
        "version": "3.0",
    }

    # Verify the documented fire-and-forget behavior: handler must return None
    response = await bridge.handle_message(mock_ws, message)
    assert response is None


# ---------------------------------------------------------------------------
# 5. diagnostics_payload -> accepted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_diagnostics_payload_processed(bridge, mock_ws):
    """Sending diagnostics_payload must be processed and accepted."""
    message = {
        "type": "diagnostics_payload",
        "device_id": DEVICE_ID,
        "error_type": "NullPointerException",
        "error_context": "During task execution in MainActivity",
        "task_id": "task-99",
        "node_name": "node_101_executor",
        "version": "3.0",
    }

    response = await bridge.handle_message(mock_ws, message)

    assert response is not None, "Expected a response for diagnostics_payload"
    assert response.get("accepted") is True
    assert response["type"] == MessageType.DIAGNOSTICS_PAYLOAD_ACK.value
