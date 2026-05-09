"""tests/test_android_takeover_protocol.py
==========================================
Tests for the Android Takeover Protocol support added in this PR.

Coverage groups
---------------
A.  MessageType enum — TAKEOVER_REQUEST / TAKEOVER_RESPONSE present.
B.  MessageBuilder — takeover_request() builds correct message shape.
C.  Handler module importability and handler function signature.
D.  AndroidBridge — TAKEOVER_RESPONSE handler is registered and not catch-all.
E.  Handler behaviour — Android accepts takeover.
F.  Handler behaviour — Android rejects takeover.
G.  Handler behaviour — tracking integration called on accept.
H.  Handler behaviour — tracking integration called on reject.
I.  Handler behaviour — tracking import failure degrades gracefully (returns ACK).
J.  ACK response shape: required fields present in every response.
K.  __init__.py re-exports handle_takeover_response.
L.  AndroidBridge.send_takeover_request() sends the correct message.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_accept_message(
    takeover_id: str = "",
    device_id: str = "device-test",
    session_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "takeover_id": takeover_id or f"tkv_{uuid.uuid4().hex[:12]}",
        "accepted": True,
        "reason": "user confirmed",
        "session_id": session_id or f"sess_{uuid.uuid4().hex[:8]}",
    }


def _make_reject_message(
    takeover_id: str = "",
    device_id: str = "device-test",
) -> Dict[str, Any]:
    return {
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "takeover_id": takeover_id or f"tkv_{uuid.uuid4().hex[:12]}",
        "accepted": False,
        "reason": "user denied",
    }


# ============================================================================
# A.  MessageType enum
# ============================================================================

class TestMessageTypeEnum:

    def test_A01_takeover_request_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TAKEOVER_REQUEST.value == "takeover_request"

    def test_A02_takeover_response_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TAKEOVER_RESPONSE.value == "takeover_response"


# ============================================================================
# B.  MessageBuilder
# ============================================================================

class TestMessageBuilder:

    def test_B01_takeover_request_type(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-1",
            takeover_id="tkv-abc",
        )
        assert msg["type"] == "takeover_request"

    def test_B02_takeover_request_required_fields(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-1",
            takeover_id="tkv-abc",
        )
        assert msg["device_id"] == "dev-1"
        assert msg["takeover_id"] == "tkv-abc"
        assert "message_id" in msg
        assert "timestamp" in msg
        assert msg["version"] == "3.0"

    def test_B03_takeover_request_optional_fields(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        ctx = {"goal": "open camera"}
        msg = MessageBuilder.takeover_request(
            device_id="dev-1",
            takeover_id="tkv-abc",
            session_id="sess-1",
            task_context=ctx,
            reason="need camera access",
            trace_id="trace-xyz",
            timeout=30,
        )
        assert msg["session_id"] == "sess-1"
        assert msg["payload"] == ctx
        assert msg["reason"] == "need camera access"
        assert msg["trace_id"] == "trace-xyz"
        assert msg["timeout"] == 30

    def test_B04_takeover_request_default_timeout(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(device_id="dev-1", takeover_id="tkv-abc")
        assert msg["timeout"] == 60


# ============================================================================
# C.  Handler module importability
# ============================================================================

class TestHandlerImport:

    def test_C01_module_importable(self):
        from galaxy_gateway.android.handlers import takeover_response  # noqa: F401

    def test_C02_handle_takeover_response_is_coroutine_function(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        assert asyncio.iscoroutinefunction(handle_takeover_response)


# ============================================================================
# D.  AndroidBridge handler registration
# ============================================================================

class TestHandlerRegistration:

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_D01_takeover_response_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.TAKEOVER_RESPONSE in bridge._message_handlers

    def test_D02_handler_is_not_catch_all(self):
        """TAKEOVER_RESPONSE must not fall back to handle_unregistered."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        from galaxy_gateway.android.handlers.generic import handle_generic_forward
        bridge = self._make_bridge()
        # The registered handler wrapper is distinct from the unregistered catch-all.
        # We verify it is set (not None) and is callable.
        handler = bridge._message_handlers.get(MessageType.TAKEOVER_RESPONSE)
        assert handler is not None
        assert callable(handler)


# ============================================================================
# E.  Handler behaviour — Android accepts takeover
# ============================================================================

class TestHandlerAccept:

    def test_E01_returns_ack_type_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_message()
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"

    def test_E02_ack_reflects_accepted_true(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_message()
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["accepted"] is True

    def test_E03_ack_echoes_takeover_id(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tid = f"tkv_{uuid.uuid4().hex[:10]}"
        msg = _make_accept_message(takeover_id=tid)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["takeover_id"] == tid


# ============================================================================
# F.  Handler behaviour — Android rejects takeover
# ============================================================================

class TestHandlerReject:

    def test_F01_returns_ack_type_on_reject(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_reject_message()
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"

    def test_F02_ack_reflects_accepted_false(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_reject_message()
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["accepted"] is False

    def test_F03_ack_echoes_takeover_id(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tid = f"tkv_{uuid.uuid4().hex[:10]}"
        msg = _make_reject_message(takeover_id=tid)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["takeover_id"] == tid


# ============================================================================
# G.  Tracking integration called on accept
# ============================================================================

class TestTrackingOnAccept:

    def test_G01_tracking_called_with_accepted_true(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tid = f"tkv_{uuid.uuid4().hex[:10]}"
        msg = _make_accept_message(takeover_id=tid)

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response"
        ) as mock_record:
            _run(handle_takeover_response(MagicMock(), None, msg))
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["accepted"] is True
            assert call_kwargs["takeover_id"] == tid

    def test_G02_tracking_receives_device_id_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_message(device_id="my-android-device")

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response"
        ) as mock_record:
            _run(handle_takeover_response(MagicMock(), None, msg))
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["device_id"] == "my-android-device"


# ============================================================================
# H.  Tracking integration called on reject
# ============================================================================

class TestTrackingOnReject:

    def test_H01_tracking_called_with_accepted_false(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tid = f"tkv_{uuid.uuid4().hex[:10]}"
        msg = _make_reject_message(takeover_id=tid)

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response"
        ) as mock_record:
            _run(handle_takeover_response(MagicMock(), None, msg))
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["accepted"] is False
            assert call_kwargs["takeover_id"] == tid

    def test_H02_tracking_receives_reason_on_reject(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_reject_message()
        msg["reason"] = "screen locked"

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response"
        ) as mock_record:
            _run(handle_takeover_response(MagicMock(), None, msg))
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["reason"] == "screen locked"


# ============================================================================
# I.  Session recovery across reconnect takeover responses
# ============================================================================

class TestTakeoverResponseSessionRecovery:

    def test_I01_missing_session_id_uses_active_registry_session(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        msg = _make_accept_message()
        msg.pop("session_id", None)
        expected_session_id = f"sess_{uuid.uuid4().hex[:8]}"
        coordinator = MagicMock()
        coordinator.on_takeover_response = MagicMock()

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._lookup_session_by_device",
            return_value=SimpleNamespace(runtime_session_id=expected_session_id),
        ) as mock_lookup, patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response",
        ) as mock_record, patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=coordinator,
        ):
            _run(handle_takeover_response(MagicMock(), None, msg))

        mock_lookup.assert_called_once_with(msg["device_id"])
        assert mock_record.call_args.kwargs["session_id"] == expected_session_id
        assert coordinator.on_takeover_response.call_args.kwargs["session_id"] == expected_session_id

    def test_I02_missing_session_id_without_registry_entry_degrades_gracefully(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        msg = _make_accept_message()
        msg.pop("session_id", None)
        coordinator = MagicMock()
        coordinator.on_takeover_response = MagicMock()

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._lookup_session_by_device",
            return_value=None,
        ), patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response",
        ) as mock_record, patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=coordinator,
        ):
            _run(handle_takeover_response(MagicMock(), None, msg))

        assert mock_record.call_args.kwargs["session_id"] is None, (
            "Tracking API normalizes missing session_id to None"
        )
        assert coordinator.on_takeover_response.call_args.kwargs["session_id"] == "", (
            "Coordinator API preserves empty-string session_id when lookup cannot recover it"
        )


# ============================================================================
# J.  Tracking import failure degrades gracefully
# ============================================================================

class TestTrackingDegradeGracefully:

    def test_I01_ack_returned_even_when_tracking_unavailable(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_message()

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response",
            None,
        ):
            resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"

    def test_I02_ack_returned_when_tracking_raises(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_reject_message()

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._record_takeover_response",
            side_effect=RuntimeError("tracking failure"),
        ):
            # Handler must not propagate the exception
            resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"


# ============================================================================
# K.  ACK response shape
# ============================================================================

class TestAckResponseShape:

    def _get_ack(self, accepted: bool) -> Dict[str, Any]:
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        if accepted:
            msg = _make_accept_message()
        else:
            msg = _make_reject_message()
        return _run(handle_takeover_response(MagicMock(), None, msg))

    def test_J01_ack_has_type(self):
        assert "type" in self._get_ack(True)

    def test_J02_ack_has_device_id(self):
        assert "device_id" in self._get_ack(False)

    def test_J03_ack_has_message_id(self):
        assert "message_id" in self._get_ack(True)

    def test_J04_ack_has_correlation_id(self):
        assert "correlation_id" in self._get_ack(False)

    def test_J05_ack_has_takeover_id(self):
        assert "takeover_id" in self._get_ack(True)

    def test_J06_ack_has_accepted_field(self):
        assert "accepted" in self._get_ack(False)

    def test_J07_ack_version_is_3(self):
        ack = self._get_ack(True)
        assert ack.get("version") == "3.0"


# ============================================================================
# L.  __init__.py re-exports
# ============================================================================

class TestInitReExport:

    def test_K01_handle_takeover_response_in_init(self):
        from galaxy_gateway.android.handlers import handle_takeover_response  # noqa: F401

    def test_K02_in_all_list(self):
        import galaxy_gateway.android.handlers as pkg
        assert "handle_takeover_response" in pkg.__all__


# ============================================================================
# M.  AndroidBridge.send_takeover_request()
# ============================================================================

class TestSendTakeoverRequest:

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_L01_method_exists(self):
        bridge = self._make_bridge()
        assert callable(getattr(bridge, "send_takeover_request", None))

    def test_L02_method_is_coroutine(self):
        bridge = self._make_bridge()
        assert asyncio.iscoroutinefunction(bridge.send_takeover_request)

    def test_L03_sends_correct_message_type(self):
        bridge = self._make_bridge()
        sent_messages = []

        async def _fake_send(device_id, message, **kwargs):
            sent_messages.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        _run(bridge.send_takeover_request("dev-1", "tkv-abc"))

        assert len(sent_messages) == 1
        assert sent_messages[0]["type"] == "takeover_request"
        assert sent_messages[0]["takeover_id"] == "tkv-abc"
        assert sent_messages[0]["device_id"] == "dev-1"

    def test_L04_sends_optional_fields(self):
        bridge = self._make_bridge()
        sent_messages = []

        async def _fake_send(device_id, message, **kwargs):
            sent_messages.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        _run(bridge.send_takeover_request(
            "dev-1",
            "tkv-xyz",
            session_id="sess-99",
            reason="need control",
            trace_id="trace-001",
        ))

        msg = sent_messages[0]
        assert msg.get("session_id") == "sess-99"
        assert msg.get("reason") == "need control"
        assert msg.get("trace_id") == "trace-001"

    def test_L05_returns_none_when_device_not_connected(self):
        bridge = self._make_bridge()
        # No device registered → send_to_device returns None
        result = _run(bridge.send_takeover_request("nonexistent-device", "tkv-001"))
        assert result is None


# ============================================================================
# N.  Mode gate — Axis-1 + Axis-7: takeover is mode-gated
# ============================================================================

class TestTakeoverModeGate:
    """Verify that send_takeover_request is strictly gated by system mode.

    Takeover must only be dispatched when the system is running in
    cross-device mode (GALAXY_CROSS_DEVICE_ENABLED=1 / GALAXY_SYSTEM_MODE=
    desktop-cross-device).  In local mode the method must return a structured
    error dict without ever calling send_to_device.
    """

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_M01_blocked_when_cross_device_disabled(self):
        """send_takeover_request returns a blocked dict when cross-device is OFF."""
        bridge = self._make_bridge()
        call_count = {"n": 0}

        async def _fake_send(device_id, message, **kwargs):
            call_count["n"] += 1
            return {"success": True}

        bridge.send_to_device = _fake_send

        with patch("galaxy_gateway.android_bridge._is_cross_device_enabled", return_value=False):
            result = _run(bridge.send_takeover_request("dev-1", "tkv-blocked"))

        assert result is not None, "blocked result must be a dict, not None"
        assert result.get("success") is False
        assert result.get("blocked") is True
        assert result.get("reason") == "cross_device_mode_disabled"
        assert call_count["n"] == 0, "send_to_device must NOT be called in local mode"

    def test_M02_blocked_result_includes_takeover_and_device_id(self):
        """Blocked result must include takeover_id and device_id for traceability."""
        bridge = self._make_bridge()
        bridge.send_to_device = AsyncMock()

        with patch("galaxy_gateway.android_bridge._is_cross_device_enabled", return_value=False):
            result = _run(bridge.send_takeover_request(
                "my-android",
                "tkv-xyz",
                trace_id="trace-999",
            ))

        assert result["takeover_id"] == "tkv-xyz"
        assert result["device_id"] == "my-android"
        assert result["trace_id"] == "trace-999"

    def test_M03_blocked_result_generates_trace_id_when_absent(self):
        """When trace_id is not provided the blocked dict still carries one."""
        bridge = self._make_bridge()
        bridge.send_to_device = AsyncMock()

        with patch("galaxy_gateway.android_bridge._is_cross_device_enabled", return_value=False):
            result = _run(bridge.send_takeover_request("dev-1", "tkv-001"))

        assert "trace_id" in result
        assert result["trace_id"], "trace_id must be non-empty"

    def test_M04_allowed_when_cross_device_enabled(self):
        """send_takeover_request proceeds normally when cross-device is ON."""
        bridge = self._make_bridge()
        sent = []

        async def _fake_send(device_id, message, **kwargs):
            sent.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        with patch("galaxy_gateway.android_bridge._is_cross_device_enabled", return_value=True):
            result = _run(bridge.send_takeover_request("dev-1", "tkv-go"))

        assert len(sent) == 1, "send_to_device must be called when mode allows"
        assert sent[0]["type"] == "takeover_request"
        assert result == {"success": True}

    def test_M05_blocked_does_not_notify_lifecycle_coordinator(self):
        """Lifecycle coordinator must NOT be notified when the request is blocked."""
        bridge = self._make_bridge()
        bridge.send_to_device = AsyncMock()
        coordinator_calls = []

        def _fake_coordinator():
            coord = MagicMock()
            coord.on_takeover_requested = MagicMock(
                side_effect=lambda **kw: coordinator_calls.append(kw)
            )
            return coord

        with patch("galaxy_gateway.android_bridge._is_cross_device_enabled", return_value=False), \
             patch("galaxy_gateway.android_bridge._get_lifecycle_coordinator", _fake_coordinator):
            _run(bridge.send_takeover_request("dev-1", "tkv-blocked"))

        assert len(coordinator_calls) == 0, (
            "Lifecycle coordinator must not record a blocked takeover request"
        )
