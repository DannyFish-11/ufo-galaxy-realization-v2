"""
tests/test_device_communication_control_plane_msgs.py
=======================================================
Unit tests for the DEVICE_STATE_SNAPSHOT and DEVICE_EXECUTION_EVENT
message routing added to core.device_communication.handle_message.

These tests verify that:
1. handle_message routes "device_state_snapshot" to AndroidDeviceStateStore
2. handle_message routes "device_execution_event" to AndroidDeviceStateStore
3. Both message types return an ACK DeviceMessage
4. Malformed payloads do not crash the handler
5. The store reflects the absorbed data after routing
"""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.android_device_state_store import (
    get_device_state_snapshot,
    reset_android_device_state_store,
)
from core.device_communication import DeviceCommunication, DeviceConnection, MessageType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_comm() -> DeviceCommunication:
    """Return a fresh DeviceCommunication instance (not the singleton)."""
    comm = DeviceCommunication.__new__(DeviceCommunication)
    DeviceCommunication.__init__(comm)
    return comm


def _make_connection(device_id: str) -> DeviceConnection:
    ws = MagicMock()
    ws.send_text = AsyncMock(return_value=None)
    return DeviceConnection(device_id=device_id, websocket=ws)


def _msg(msg_type: str, payload: dict) -> str:
    return json.dumps({"type": msg_type, "message_id": "msg_test_001", "payload": payload})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store():
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


# ---------------------------------------------------------------------------
# device_state_snapshot routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_state_snapshot_is_routed():
    """handle_message with type=device_state_snapshot must absorb into store."""
    comm = _make_comm()
    device_id = "snap_test_dev"
    comm.connections[device_id] = _make_connection(device_id)

    payload = {
        "model_ready": True,
        "local_loop_ready": True,
        "llama_cpp_available": True,
        "model_id": "mobilevlm_v2_7b",
    }
    raw = json.dumps({
        "type": "device_state_snapshot",
        "message_id": "snap_001",
        "payload": payload,
    })

    result = await comm.handle_message(device_id, raw)
    snap = get_device_state_snapshot(device_id)
    assert snap is not None, "Snapshot was not stored after handle_message"
    assert snap.model_ready is True
    assert snap.model_id == "mobilevlm_v2_7b"


@pytest.mark.asyncio
async def test_device_state_snapshot_returns_ack():
    """handle_message with type=device_state_snapshot must return ACK."""
    comm = _make_comm()
    device_id = "snap_ack_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_state_snapshot",
        "message_id": "snap_002",
        "payload": {"model_ready": False},
    })
    result = await comm.handle_message(device_id, raw)
    assert result is not None, "Expected ACK DeviceMessage, got None"
    assert result.type == MessageType.ACK
    assert result.action == "device_state_snapshot"


@pytest.mark.asyncio
async def test_device_state_snapshot_ack_has_correlation_id():
    """ACK must carry correlation_id matching the incoming message_id."""
    comm = _make_comm()
    device_id = "snap_corr_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_state_snapshot",
        "message_id": "corr_msg_123",
        "payload": {},
    })
    result = await comm.handle_message(device_id, raw)
    assert result is not None
    assert result.correlation_id == "corr_msg_123"


@pytest.mark.asyncio
async def test_device_state_snapshot_with_camelcase_payload():
    """Parser must accept camelCase keys from Android JSON serialisation."""
    comm = _make_comm()
    device_id = "camel_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_state_snapshot",
        "message_id": "camel_001",
        "payload": {
            "llamaCppAvailable": True,
            "modelReady": True,
            "localLoopReady": False,
        },
    })
    result = await comm.handle_message(device_id, raw)
    snap = get_device_state_snapshot(device_id)
    assert snap is not None
    assert snap.llama_cpp_available is True
    assert snap.model_ready is True


@pytest.mark.asyncio
async def test_device_state_snapshot_malformed_does_not_crash():
    """Malformed payload must not raise; handler should return ACK anyway."""
    comm = _make_comm()
    device_id = "malform_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_state_snapshot",
        "message_id": "bad_001",
        "payload": "not_a_dict",   # intentionally wrong type
    })
    # Must not raise
    result = await comm.handle_message(device_id, raw)
    assert result is not None
    assert result.type == MessageType.ACK


# ---------------------------------------------------------------------------
# device_execution_event routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_execution_event_is_routed():
    """handle_message with type=device_execution_event must absorb into store."""
    from core.android_device_state_store import get_android_device_state_store
    comm = _make_comm()
    device_id = "exec_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_execution_event",
        "message_id": "exec_001",
        "payload": {
            "flow_id": "flow_test_abc",
            "task_id": "task_xyz",
            "phase": "grounding",
            "step_index": 5,
            "is_blocking": False,
        },
    })
    await comm.handle_message(device_id, raw)

    store = get_android_device_state_store()
    events = store.list_recent_execution_events(device_id=device_id)
    assert len(events) >= 1
    evt = events[0]
    assert evt.flow_id == "flow_test_abc"
    assert evt.phase == "grounding"
    assert evt.step_index == 5


@pytest.mark.asyncio
async def test_device_execution_event_returns_ack():
    """handle_message with type=device_execution_event must return ACK."""
    comm = _make_comm()
    device_id = "exec_ack_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_execution_event",
        "message_id": "exec_002",
        "payload": {"flow_id": "f1", "phase": "planning"},
    })
    result = await comm.handle_message(device_id, raw)
    assert result is not None
    assert result.type == MessageType.ACK
    assert result.action == "device_execution_event"


@pytest.mark.asyncio
async def test_device_execution_event_ack_has_correlation_id():
    """ACK must carry correlation_id matching the incoming message_id."""
    comm = _make_comm()
    device_id = "exec_corr_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_execution_event",
        "message_id": "corr_exec_999",
        "payload": {},
    })
    result = await comm.handle_message(device_id, raw)
    assert result is not None
    assert result.correlation_id == "corr_exec_999"


@pytest.mark.asyncio
async def test_device_execution_event_blocking_event():
    """Blocking execution events must be stored with is_blocking=True."""
    from core.android_device_state_store import get_android_device_state_store
    comm = _make_comm()
    device_id = "blocking_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_execution_event",
        "message_id": "block_001",
        "payload": {
            "flow_id": "flow_blocked",
            "phase": "gate_decision",
            "is_blocking": True,
            "blocking_reason": "policy_gate_triggered",
            "stagnation_detected": False,
        },
    })
    await comm.handle_message(device_id, raw)

    store = get_android_device_state_store()
    events = store.list_recent_execution_events(flow_id="flow_blocked")
    assert len(events) >= 1
    evt = events[0]
    assert evt.is_blocking is True
    assert evt.blocking_reason == "policy_gate_triggered"


@pytest.mark.asyncio
async def test_device_execution_event_stagnation():
    """Stagnation events must be stored with stagnation_detected=True."""
    from core.android_device_state_store import get_android_device_state_store
    comm = _make_comm()
    device_id = "stag_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "device_execution_event",
        "message_id": "stag_001",
        "payload": {
            "flow_id": "flow_stagnant",
            "phase": "stagnation",
            "stagnation_detected": True,
        },
    })
    await comm.handle_message(device_id, raw)

    store = get_android_device_state_store()
    events = store.list_recent_execution_events(flow_id="flow_stagnant")
    assert len(events) >= 1
    assert events[0].stagnation_detected is True


# ---------------------------------------------------------------------------
# No interference with existing message types
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_still_works_after_new_msg_types():
    """Adding new message handlers must not break the existing heartbeat path."""
    comm = _make_comm()
    device_id = "hb_dev"
    comm.connections[device_id] = _make_connection(device_id)

    raw = json.dumps({
        "type": "heartbeat",
        "message_id": "hb_001",
    })
    result = await comm.handle_message(device_id, raw)
    assert result is not None
    assert result.type == MessageType.ACK
    assert result.action == "heartbeat"
