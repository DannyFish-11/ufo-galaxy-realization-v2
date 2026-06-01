"""
PR-S4: MessageType 统一 & 路由 — 路由行为测试
=============================================

验证以下不变量:

1. compat 层在路由之前将 legacy 类型转换为 v3 类型字符串。
2. handle_message 路由层只接受 v3 MessageType 名称。
3. Legacy 类型字符串（handshake、response、status、TEXT、event）
   经 compat 规范化后才到达路由层；不能直接在路由中出现。
4. 五个核心 v3 类型（device_register、heartbeat、capability_report、
   task_assign、command_result）分别路由到正确的处理逻辑。
"""

import asyncio
import json
import time
import pytest
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

from galaxy_gateway.protocol.compat import (
    _LEGACY_TYPE_MAP,
    normalise_to_v3_dict,
    parse_message_compat,
)
from galaxy_gateway.protocol.aip_v3 import MessageType as V3MessageType


# ---------------------------------------------------------------------------
# Helper — build a minimal v3 JSON string
# ---------------------------------------------------------------------------

def _msg(msg_type: str, device_id: str = "dev-test", **extra) -> str:
    data = {"type": msg_type, "device_id": device_id}
    data.update(extra)
    return json.dumps(data)


# ---------------------------------------------------------------------------
# 1. compat._LEGACY_TYPE_MAP covers all v2-transport aliases
# ---------------------------------------------------------------------------

class TestLegacyTypeMapCoverage:
    """All v2-specific type aliases used by device_communication must be mapped."""

    @pytest.mark.parametrize("legacy_type, expected_v3_value", [
        ("handshake",  "device_register"),
        ("text",       "command"),
        ("response",   "command_result"),
        ("status",     "device_status"),
        ("event",      "wake_event"),
        # Original aliases already present before PR-S4
        ("register",   "device_register"),
        ("heartbeat",  "heartbeat"),
        # NOTE: v1 "command_result" was the legacy way to report task completion;
        # compat deliberately maps it to "task_result" (NOT "command_result").
        # v3 sends "command_result" at the wire level → passes through compat unchanged.
        ("command_result", "task_result"),   # v1 legacy: command_result → task_result
        ("status_update",  "device_status"),
    ])
    def test_legacy_alias_in_map(self, legacy_type: str, expected_v3_value: str):
        assert legacy_type in _LEGACY_TYPE_MAP, (
            f"_LEGACY_TYPE_MAP is missing entry for legacy type '{legacy_type}'"
        )
        assert _LEGACY_TYPE_MAP[legacy_type].value == expected_v3_value, (
            f"Expected '{legacy_type}' → '{expected_v3_value}', "
            f"got '{_LEGACY_TYPE_MAP[legacy_type].value}'"
        )


# ---------------------------------------------------------------------------
# 2. normalise_to_v3_dict maps legacy types before routing
# ---------------------------------------------------------------------------

class TestNormaliseToV3Dict:
    """normalise_to_v3_dict must convert legacy types to v3 canonical names."""

    @pytest.mark.parametrize("legacy_type, expected_v3", [
        ("handshake",  "device_register"),
        ("text",       "command"),
        ("TEXT",       "command"),        # uppercase is lowercased in _normalise_v1
        ("response",   "command_result"),
        ("status",     "device_status"),
        ("event",      "wake_event"),
        ("register",   "device_register"),
        ("heartbeat",  "heartbeat"),
    ])
    def test_v1_legacy_types_normalised(self, legacy_type: str, expected_v3: str):
        """AIP/1.0 messages with legacy type strings are mapped to v3."""
        raw = {"type": legacy_type, "device_id": "dev-001"}
        result = normalise_to_v3_dict(raw)
        assert result["type"] == expected_v3, (
            f"Legacy '{legacy_type}' expected to normalise to '{expected_v3}', "
            f"got '{result['type']}'"
        )
        assert result["version"] == "3.0"

    def test_v3_type_passthrough(self):
        """AIP/3.0 messages are not modified by normalise_to_v3_dict."""
        raw = {"version": "3.0", "type": "heartbeat", "device_id": "dev-002"}
        result = normalise_to_v3_dict(raw)
        assert result["type"] == "heartbeat"
        assert result["version"] == "3.0"

    def test_v2_type_passthrough_with_version_bump(self):
        """AIP/2.0 messages get version bumped to 3.0; type is unchanged."""
        raw = {"version": "2.0", "type": "device_register", "device_id": "dev-003"}
        result = normalise_to_v3_dict(raw)
        assert result["type"] == "device_register"
        assert result["version"] == "3.0"


# ---------------------------------------------------------------------------
# 3. handle_message routes the 5 core v3 types correctly
# ---------------------------------------------------------------------------

# Minimal stub for DeviceConnection (avoids importing FastAPI WebSocket)
@dataclass
class _FakeConn:
    device_id: str
    messages_received: int = 0
    messages_sent: int = 0
    errors: int = 0
    last_heartbeat: float = field(default_factory=time.time)
    last_message: float = field(default_factory=time.time)
    status: str = "connected"
    pending_requests: Dict[str, Any] = field(default_factory=dict)

    def is_alive(self, timeout: float = 60.0) -> bool:
        return True


@pytest.fixture()
def comm():
    """DeviceCommunication instance with a pre-seeded fake connection."""
    from core.device_communication import DeviceCommunication
    dc = DeviceCommunication()
    dc.connections["dev-r"] = _FakeConn(device_id="dev-r")
    return dc


DEVICE_ID = "dev-r"


class TestV3TypeRouting:
    """handle_message must route each of the 5 core v3 types correctly."""

    @pytest.mark.asyncio
    async def test_device_register_returns_ack(self, comm):
        """v3 'device_register' message returns an ACK."""
        with patch("core.device_registry.device_registry") as mock_reg:
            mock_reg.get.return_value = None
            mock_reg.register = AsyncMock()
            resp = await comm.handle_message(DEVICE_ID, _msg("device_register"))
        assert resp is not None
        assert resp.action == "device_register"
        assert resp.payload.get("status") == "registered"

    @pytest.mark.asyncio
    async def test_heartbeat_updates_timestamp_and_returns_ack(self, comm):
        """v3 'heartbeat' message updates conn.last_heartbeat and returns ACK."""
        before = comm.connections[DEVICE_ID].last_heartbeat
        await asyncio.sleep(0.01)
        resp = await comm.handle_message(DEVICE_ID, _msg("heartbeat"))
        after = comm.connections[DEVICE_ID].last_heartbeat
        assert resp is not None
        assert resp.action == "heartbeat"
        assert after >= before

    @pytest.mark.asyncio
    async def test_command_result_resolves_pending_future(self, comm):
        """v3 'command_result' resolves the matching pending_requests future."""
        fut = asyncio.get_running_loop().create_future()
        correlation_id = "corr-xyz"
        comm.connections[DEVICE_ID].pending_requests[correlation_id] = fut

        # Use explicit version="3.0" so compat passes the type through unchanged.
        data = json.dumps({
            "version": "3.0",
            "type": "command_result",
            "device_id": DEVICE_ID,
            "correlation_id": correlation_id,
            "payload": {"success": True, "output": "done"},
        })
        resp = await comm.handle_message(DEVICE_ID, data)
        assert resp is None
        assert fut.done()
        assert fut.result()["success"] is True

    @pytest.mark.asyncio
    async def test_task_assign_dispatches_to_registered_handler(self, comm):
        """v3 'task_assign' forwards to the registered action handler."""
        handler_called_with = {}

        async def fake_handler(dev_id, message):
            handler_called_with["dev_id"] = dev_id
            handler_called_with["action"] = message.action
            return {"status": "queued"}

        comm.register_handler("click", fake_handler)
        data = json.dumps({
            "type": "task_assign",
            "device_id": DEVICE_ID,
            "action": "click",
            "payload": {"x": 10, "y": 20},
        })
        resp = await comm.handle_message(DEVICE_ID, data)
        assert handler_called_with.get("action") == "click"
        assert resp is not None
        assert resp.payload["status"] == "queued"

    @pytest.mark.asyncio
    async def test_capability_report_returns_ack(self, comm):
        """v3 'capability_report' message returns an ACK."""
        with patch.object(
            comm, "_handle_capability_report", new=AsyncMock()
        ) as mock_cap:
            resp = await comm.handle_message(DEVICE_ID, _msg("capability_report"))
        mock_cap.assert_awaited_once()
        assert resp is not None
        assert resp.action == "capability_report"


# ---------------------------------------------------------------------------
# 4. Legacy types are normalised before routing (not passed raw to router)
# ---------------------------------------------------------------------------

class TestLegacyTypesNormalisedBeforeRouting:
    """Legacy type strings must be converted by compat; routing sees v3 names."""

    @pytest.mark.asyncio
    async def test_handshake_normalised_to_device_register(self, comm):
        """'handshake' (v2) is normalised to 'device_register' by compat."""
        with patch("core.device_registry.device_registry") as mock_reg:
            mock_reg.get.return_value = None
            mock_reg.register = AsyncMock()
            resp = await comm.handle_message(DEVICE_ID, _msg("handshake"))
        # Normalised to device_register → returns a registration ACK
        assert resp is not None
        assert resp.action == "device_register"

    @pytest.mark.asyncio
    async def test_response_normalised_to_command_result(self, comm):
        """'response' (v2) is normalised to 'command_result'; resolves future."""
        fut = asyncio.get_running_loop().create_future()
        correlation_id = "corr-abc"
        comm.connections[DEVICE_ID].pending_requests[correlation_id] = fut

        data = json.dumps({
            "type": "response",
            "device_id": DEVICE_ID,
            "correlation_id": correlation_id,
            "payload": {"value": 42},
        })
        resp = await comm.handle_message(DEVICE_ID, data)
        assert resp is None
        assert fut.done()
        assert fut.result()["value"] == 42

    @pytest.mark.asyncio
    async def test_status_normalised_to_device_status(self, comm):
        """'status' (v2) is normalised to 'device_status' → returns ACK."""
        with patch.object(comm, "_handle_status", new=AsyncMock()):
            resp = await comm.handle_message(DEVICE_ID, _msg("status"))
        assert resp is not None
        assert resp.action == "device_status"

    @pytest.mark.asyncio
    async def test_text_normalised_to_command(self, comm):
        """Uppercase 'TEXT' (v2 wire format) is normalised to 'command' by compat."""
        # After normalisation, msg_type == "command"; no specific handler →
        # falls through to action-based dispatch or event emission (no crash).
        resp = await comm.handle_message(
            DEVICE_ID,
            json.dumps({"type": "TEXT", "device_id": DEVICE_ID, "payload": {}}),
        )
        # No crash; returns None (no handler registered for "command")
        assert resp is None

    @pytest.mark.asyncio
    async def test_event_normalised_to_wake_event(self, comm):
        """'event' (v2) is normalised to 'wake_event' → _handle_event invoked."""
        with patch.object(comm, "_handle_event", new_callable=AsyncMock) as mock_handle_event:
            resp = await comm.handle_message(DEVICE_ID, _msg("event"))
        mock_handle_event.assert_awaited_once()
        assert resp is None


# ---------------------------------------------------------------------------
# 5. Routing rejects unknown types gracefully (no exception raised)
# ---------------------------------------------------------------------------

class TestUnknownTypeHandling:
    """Unknown v3 type strings must not crash the handler; logged as debug."""

    @pytest.mark.asyncio
    async def test_unknown_v3_type_returns_none(self, comm):
        """An unknown v3 type (not in compat map) is handled without exception."""
        data = json.dumps({
            "version": "3.0",
            "type": "some_future_type",
            "device_id": DEVICE_ID,
        })
        resp = await comm.handle_message(DEVICE_ID, data)
        assert resp is None

    @pytest.mark.asyncio
    async def test_unknown_v3_type_with_action_handler(self, comm):
        """Unknown type with a matching action falls through to action handler."""
        called = {}

        async def act_handler(dev_id, message):
            called["ok"] = True
            return {"done": True}

        comm.register_handler("my_action", act_handler)
        data = json.dumps({
            "version": "3.0",
            "type": "unknown_type_xyz",
            "action": "my_action",
            "device_id": DEVICE_ID,
        })
        resp = await comm.handle_message(DEVICE_ID, data)
        assert called.get("ok") is True
        assert resp is not None
        assert resp.payload["done"] is True
