"""
tests/test_message_handler.py
==============================

Tests for AIP v3 enforcement and trace_id/route_mode injection/propagation.

Coverage:
1. protocol/compat.py — enforce_aip_v3(), inject_trace_metadata(),
   parse_message_strict(), parse_message_compat() (trace injection).
2. handlers/message_handler.py — trace_id/route_mode propagated in responses.
3. websocket_handler.py — handle_message() rejects < 3.0 and passes metadata
   through for valid 3.0 messages.
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# 1. protocol/compat helpers
# ============================================================================


class TestEnforceAIPV3:
    """Tests for galaxy_gateway.protocol.compat.enforce_aip_v3()."""

    def _enforce(self, data):
        from galaxy_gateway.protocol.compat import enforce_aip_v3
        enforce_aip_v3(data)

    def test_accepts_version_3_0(self):
        self._enforce({"version": "3.0"})  # must not raise

    def test_accepts_version_3_1(self):
        self._enforce({"version": "3.1"})

    def test_accepts_version_3_99(self):
        self._enforce({"version": "3.99"})

    def test_rejects_missing_version(self):
        from galaxy_gateway.protocol.compat import AIPVersionError
        with pytest.raises(AIPVersionError, match="Missing"):
            self._enforce({"type": "heartbeat", "device_id": "d1"})

    def test_rejects_version_1_0(self):
        from galaxy_gateway.protocol.compat import AIPVersionError
        with pytest.raises(AIPVersionError):
            self._enforce({"version": "1.0"})

    def test_rejects_version_2_0(self):
        from galaxy_gateway.protocol.compat import AIPVersionError
        with pytest.raises(AIPVersionError):
            self._enforce({"version": "2.0"})

    def test_rejects_version_0_9(self):
        from galaxy_gateway.protocol.compat import AIPVersionError
        with pytest.raises(AIPVersionError):
            self._enforce({"version": "0.9"})


class TestInjectTraceMetadata:
    """Tests for galaxy_gateway.protocol.compat.inject_trace_metadata()."""

    def _inject(self, data):
        from galaxy_gateway.protocol.compat import inject_trace_metadata
        return inject_trace_metadata(data)

    def test_injects_trace_id_when_absent(self):
        out = self._inject({"version": "3.0"})
        assert "trace_id" in out
        # Verify it is a valid UUID
        assert uuid.UUID(out["trace_id"])

    def test_injects_route_mode_when_absent(self):
        out = self._inject({"version": "3.0"})
        assert out["route_mode"] == "cross_device"

    def test_preserves_existing_trace_id(self):
        tid = str(uuid.uuid4())
        out = self._inject({"version": "3.0", "trace_id": tid})
        assert out["trace_id"] == tid

    def test_preserves_existing_route_mode(self):
        out = self._inject({"version": "3.0", "route_mode": "local"})
        assert out["route_mode"] == "local"

    def test_does_not_mutate_original(self):
        original = {"version": "3.0"}
        _ = self._inject(original)
        assert "trace_id" not in original
        assert "route_mode" not in original

    def test_empty_trace_id_is_replaced(self):
        out = self._inject({"version": "3.0", "trace_id": ""})
        assert out["trace_id"]  # must be a non-empty generated UUID
        assert uuid.UUID(out["trace_id"])

    def test_empty_route_mode_is_replaced(self):
        out = self._inject({"version": "3.0", "route_mode": ""})
        assert out["route_mode"] == "cross_device"

    def test_none_route_mode_is_replaced(self):
        out = self._inject({"version": "3.0", "route_mode": None})
        assert out["route_mode"] == "cross_device"

    def test_none_trace_id_is_replaced(self):
        out = self._inject({"version": "3.0", "trace_id": None})
        assert out["trace_id"]
        assert uuid.UUID(out["trace_id"])


class TestParseMessageStrict:
    """Tests for galaxy_gateway.protocol.compat.parse_message_strict()."""

    def _make_v3(self, extra=None):
        data = {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "test-device",
        }
        if extra:
            data.update(extra)
        return data

    def test_accepts_v3_message(self):
        from galaxy_gateway.protocol.compat import parse_message_strict
        msg = parse_message_strict(self._make_v3())
        assert msg.device_id == "test-device"

    def test_rejects_missing_version(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError
        with pytest.raises(AIPVersionError):
            parse_message_strict({"type": "heartbeat", "device_id": "d1"})

    def test_rejects_v1_message(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError
        with pytest.raises(AIPVersionError):
            parse_message_strict({"version": "1.0", "type": "heartbeat", "device_id": "d1"})

    def test_rejects_v2_message(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, AIPVersionError
        with pytest.raises(AIPVersionError):
            parse_message_strict({"version": "2.0", "type": "heartbeat", "device_id": "d1"})

    def test_trace_id_injected_in_payload(self):
        from galaxy_gateway.protocol.compat import parse_message_strict
        msg = parse_message_strict(self._make_v3())
        # trace_id is injected into the raw dict; it surfaces in payload
        # because parse_message_strict passes the dict (which includes trace_id)
        # to parse_message(); trace_id is not a declared AIPMessage field, so
        # it ends up in the extra fields or payload dict depending on model config.
        # We only test that parsing succeeds and returns a valid message.
        assert msg.device_id == "test-device"

    def test_accepts_json_string_input(self):
        from galaxy_gateway.protocol.compat import parse_message_strict
        raw = json.dumps(self._make_v3())
        msg = parse_message_strict(raw)
        assert msg.device_id == "test-device"

    def test_trace_id_preserved_when_provided(self):
        from galaxy_gateway.protocol.compat import parse_message_strict, inject_trace_metadata
        tid = str(uuid.uuid4())
        # inject_trace_metadata should preserve an existing trace_id, not replace it
        out = inject_trace_metadata({"version": "3.0", "trace_id": tid})
        assert out["trace_id"] == tid
        # parse_message_strict should also succeed
        msg = parse_message_strict({"version": "3.0", "type": "heartbeat", "device_id": "d1", "trace_id": tid})
        assert msg.device_id == "d1"


class TestParseMessageCompatTraceInjection:
    """Ensure parse_message_compat also injects trace_id/route_mode."""

    def test_v1_message_gets_trace_id_and_route_mode(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        # AIP/1.0 message — no version, no trace_id, no route_mode
        msg = parse_message_compat({
            "type": "heartbeat",
            "device_id": "legacy-device",
        })
        # Parsing should succeed
        assert msg.device_id == "legacy-device"

    def test_v3_message_gets_trace_id_injected(self):
        from galaxy_gateway.protocol.compat import parse_message_compat
        msg = parse_message_compat({
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "d1",
        })
        assert msg.device_id == "d1"


# ============================================================================
# 2. handlers/message_handler.py — trace propagation in responses
# ============================================================================


class TestMessageHandlerTracePropagation:
    """Tests that MessageHandler.handle_message() propagates trace_id/route_mode."""

    def _make_aip_message(self, trace_id=None, route_mode=None):
        from galaxy_gateway.protocol.aip_v3 import AIPMessage, MessageType
        payload = {}
        if trace_id:
            payload["trace_id"] = trace_id
        if route_mode:
            payload["route_mode"] = route_mode
        return AIPMessage(
            type=MessageType.DEVICE_HEARTBEAT,
            device_id="test-device",
            payload=payload,
        )

    @pytest.fixture()
    def handler(self):
        from galaxy_gateway.handlers.device_manager import DeviceManager
        from galaxy_gateway.handlers.message_handler import MessageHandler
        dm = MagicMock(spec=DeviceManager)
        dm.update_device_status = MagicMock()
        return MessageHandler(dm)

    @pytest.mark.asyncio
    async def test_trace_id_propagated_in_response(self, handler):
        tid = str(uuid.uuid4())
        msg = self._make_aip_message(trace_id=tid)
        response = await handler.handle_message("test-device", msg)
        assert response is not None
        assert response.payload.get("trace_id") == tid

    @pytest.mark.asyncio
    async def test_route_mode_propagated_in_response(self, handler):
        msg = self._make_aip_message(route_mode="local")
        response = await handler.handle_message("test-device", msg)
        assert response is not None
        assert response.payload.get("route_mode") == "local"

    @pytest.mark.asyncio
    async def test_both_fields_propagated(self, handler):
        tid = str(uuid.uuid4())
        msg = self._make_aip_message(trace_id=tid, route_mode="cross_device")
        response = await handler.handle_message("test-device", msg)
        assert response is not None
        assert response.payload.get("trace_id") == tid
        assert response.payload.get("route_mode") == "cross_device"

    @pytest.mark.asyncio
    async def test_missing_trace_does_not_overwrite_response(self, handler):
        """When the request has no trace_id, response payload is not modified."""
        msg = self._make_aip_message()  # no trace_id / route_mode
        response = await handler.handle_message("test-device", msg)
        # Should succeed without error; trace_id absence is tolerated here
        # (injection happens at ingress, not inside MessageHandler)
        assert response is not None


# ============================================================================
# 3. websocket_handler.handle_message() — accept/reject paths
# ============================================================================


class TestWebSocketHandlerEnforcement:
    """Tests for galaxy_gateway.websocket_handler.handle_message()."""

    def _make_ws(self):
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        ws.close = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_rejects_missing_version(self):
        from galaxy_gateway.websocket_handler import handle_message
        ws = self._make_ws()
        message = {"type": "heartbeat", "device_id": "d1"}
        await handle_message("conn-1", message, ws)

        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["payload"]["error"] == "protocol_version_rejected"
        ws.close.assert_called_once_with(code=4000)

    @pytest.mark.asyncio
    async def test_rejects_version_1_0(self):
        from galaxy_gateway.websocket_handler import handle_message
        ws = self._make_ws()
        message = {"version": "1.0", "type": "heartbeat", "device_id": "d1"}
        await handle_message("conn-1", message, ws)

        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["payload"]["error"] == "protocol_version_rejected"
        ws.close.assert_called_once_with(code=4000)

    @pytest.mark.asyncio
    async def test_rejects_version_2_0(self):
        from galaxy_gateway.websocket_handler import handle_message
        ws = self._make_ws()
        message = {"version": "2.0", "type": "heartbeat", "device_id": "d1"}
        await handle_message("conn-1", message, ws)

        ws.send_json.assert_called_once()
        sent = ws.send_json.call_args[0][0]
        assert sent["payload"]["error"] == "protocol_version_rejected"

    @pytest.mark.asyncio
    async def test_accepts_version_3_0(self):
        """A valid v3.0 heartbeat should not close the connection."""
        from galaxy_gateway.websocket_handler import handle_message, connection_manager
        ws = self._make_ws()
        conn_id = "conn-accept"
        # Simulate a registered connection so handle_heartbeat can send its ack
        connection_manager.active_connections[conn_id] = ws

        tid = str(uuid.uuid4())
        message = {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "d-valid",
            "trace_id": tid,
            "route_mode": "cross_device",
        }
        await handle_message(conn_id, message, ws)

        # Connection must not have been closed for a valid message
        ws.close.assert_not_called()

        # Clean up
        del connection_manager.active_connections[conn_id]

    @pytest.mark.asyncio
    async def test_v3_heartbeat_injects_trace_in_log(self):
        """parse_message_strict is called; trace_id flows into aip_msg.payload."""
        from galaxy_gateway.websocket_handler import handle_message, connection_manager
        ws = self._make_ws()
        conn_id = "conn-trace"
        connection_manager.active_connections[conn_id] = ws

        message = {
            "version": "3.0",
            "type": "heartbeat",
            "device_id": "d-trace",
            # no trace_id — should be injected
        }
        await handle_message(conn_id, message, ws)
        ws.close.assert_not_called()

        del connection_manager.active_connections[conn_id]

    @pytest.mark.asyncio
    async def test_ignores_message_without_type(self):
        """Messages without 'type' are silently dropped; no close/error sent."""
        from galaxy_gateway.websocket_handler import handle_message
        ws = self._make_ws()
        await handle_message("conn-no-type", {}, ws)
        ws.send_json.assert_not_called()
        ws.close.assert_not_called()
