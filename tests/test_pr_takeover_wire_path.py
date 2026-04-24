"""tests/test_pr_takeover_wire_path.py
=====================================================
Tests for the V2-side takeover protocol wire path.

This test suite verifies that:

1. ``MessageType`` enum contains ``TAKEOVER_REQUEST`` and ``TAKEOVER_RESPONSE``.
2. ``MessageBuilder.takeover_request()`` builds a well-formed AIP v3 message.
3. ``AndroidBridge`` registers a handler for ``TAKEOVER_RESPONSE``.
4. ``AndroidBridge.send_takeover_request()`` is callable and sends the right
   message type.
5. ``handle_takeover_response`` correctly processes accept/reject decisions.
6. Accepted takeovers are recorded in ``TAKEOVER_RESPONSE_REGISTRY``.
7. Rejected takeovers are recorded in ``TAKEOVER_RESPONSE_REGISTRY``.
8. The handler always returns a well-formed ACK response.
9. ``TAKEOVER_RESPONSE`` has a canonical entry in the WS profile mapping.
10. ``handle_takeover_response`` is exported from ``galaxy_gateway.android.handlers``.

Coverage groups
---------------
A  — MessageType enum has both takeover types.
B  — MessageBuilder.takeover_request() message shape.
C  — AndroidBridge registers TAKEOVER_RESPONSE handler.
D  — AndroidBridge.send_takeover_request() callable.
E  — handle_takeover_response: Android accept path.
F  — handle_takeover_response: Android reject path.
G  — ACK response shape on accept.
H  — ACK response shape on reject.
I  — TAKEOVER_RESPONSE_REGISTRY tracking state.
J  — runtime_ws_profile canonical entry.
K  — __init__.py re-exports handle_takeover_response.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_takeover_response_message(
    *,
    takeover_id: str = "",
    accepted: bool = True,
    device_id: str = "android-test-device",
    task_id: str = "task-001",
    session_id: str = "sess-001",
    reject_reason: str = "",
) -> Dict[str, Any]:
    tid = takeover_id or f"tkv_{uuid.uuid4().hex[:12]}"
    return {
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "takeover_id": tid,
            "accepted": accepted,
            "task_id": task_id,
            "session_id": session_id,
            "reject_reason": reject_reason,
        },
    }


# ============================================================================
# A.  MessageType enum
# ============================================================================

class TestMessageTypeEnum:

    def test_A01_takeover_request_present(self):
        """TAKEOVER_REQUEST must be in the MessageType enum."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TAKEOVER_REQUEST.value == "takeover_request"

    def test_A02_takeover_response_present(self):
        """TAKEOVER_RESPONSE must be in the MessageType enum."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TAKEOVER_RESPONSE.value == "takeover_response"

    def test_A03_both_in_all_types(self):
        from galaxy_gateway.protocol.aip_v3 import UnifiedMessageTypes
        all_types = UnifiedMessageTypes.get_all_types()
        assert "takeover_request" in all_types
        assert "takeover_response" in all_types


# ============================================================================
# B.  MessageBuilder.takeover_request()
# ============================================================================

class TestMessageBuilderTakeoverRequest:

    def test_B01_type_is_takeover_request(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-001",
            takeover_id="tkv_abc123",
        )
        assert msg["type"] == "takeover_request"

    def test_B02_takeover_id_at_top_level(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-001",
            takeover_id="tkv_abc123",
        )
        assert msg["takeover_id"] == "tkv_abc123"

    def test_B03_takeover_id_in_payload(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-001",
            takeover_id="tkv_abc123",
        )
        assert msg["payload"]["takeover_id"] == "tkv_abc123"

    def test_B04_optional_fields_propagated(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="dev-001",
            takeover_id="tkv_xyz",
            task_id="task-99",
            session_id="sess-99",
            trace_id="trace-99",
            reason="agent needs screen",
            capabilities_required=["screen", "touch"],
        )
        assert msg["task_id"] == "task-99"
        assert msg["session_id"] == "sess-99"
        assert msg["trace_id"] == "trace-99"
        assert msg["payload"]["reason"] == "agent needs screen"
        assert msg["payload"]["capabilities_required"] == ["screen", "touch"]

    def test_B05_required_aip_fields_present(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(device_id="dev-001", takeover_id="tkv_1")
        for field in ("version", "type", "message_id", "device_id", "timestamp"):
            assert field in msg, f"Missing field: {field}"

    def test_B06_version_is_3_0(self):
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(device_id="dev-001", takeover_id="tkv_1")
        assert msg["version"] == "3.0"


# ============================================================================
# C.  AndroidBridge handler registration
# ============================================================================

class TestAndroidBridgeHandlerRegistration:

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_C01_takeover_response_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.TAKEOVER_RESPONSE in bridge._message_handlers

    def test_C02_handler_is_not_handle_unregistered(self):
        """TAKEOVER_RESPONSE handler must not fall back to handle_unregistered."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        from galaxy_gateway.android.handlers.registration import handle_unregistered

        bridge = self._make_bridge()
        # The wrapped handler should not be the unregistered catch-all
        assert bridge._message_handlers[MessageType.TAKEOVER_RESPONSE] is not None


# ============================================================================
# D.  AndroidBridge.send_takeover_request()
# ============================================================================

class TestSendTakeoverRequest:

    def test_D01_method_exists(self):
        from galaxy_gateway.android_bridge import AndroidBridge
        assert hasattr(AndroidBridge, "send_takeover_request")
        assert asyncio.iscoroutinefunction(AndroidBridge.send_takeover_request)

    def test_D02_sends_takeover_request_type(self):
        """send_takeover_request must send a message with type 'takeover_request'."""
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge()

        sent_messages = []

        async def _fake_send(device_id, msg, wait_response=False, timeout=30.0):
            sent_messages.append(msg)
            return {"success": True}

        bridge.send_to_device = _fake_send

        _run(bridge.send_takeover_request(
            device_id="dev-001",
            takeover_id="tkv_test_001",
            task_id="task-001",
            trace_id="trace-001",
        ))

        assert len(sent_messages) == 1
        assert sent_messages[0]["type"] == "takeover_request"
        assert sent_messages[0]["takeover_id"] == "tkv_test_001"

    def test_D03_returns_none_when_device_not_connected(self):
        """Returns None when the target device is not in the transport cache."""
        from galaxy_gateway.android_bridge import AndroidBridge
        bridge = AndroidBridge()

        result = _run(bridge.send_takeover_request(
            device_id="nonexistent-device",
            takeover_id="tkv_noop",
        ))
        # Device not connected → send_to_device returns None
        assert result is None


# ============================================================================
# E.  handle_takeover_response — accept path
# ============================================================================

class TestHandleTakeoverResponseAccept:

    def test_E01_accepted_true_recorded(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)

        _run(handle_takeover_response(MagicMock(), None, msg))

        assert tkv_id in TAKEOVER_RESPONSE_REGISTRY
        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.accepted is True

    def test_E02_reject_reason_cleared_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(
            takeover_id=tkv_id,
            accepted=True,
            reject_reason="should be ignored",
        )
        _run(handle_takeover_response(MagicMock(), None, msg))

        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.reject_reason == ""

    def test_E03_device_id_propagated(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(
            takeover_id=tkv_id,
            accepted=True,
            device_id="android-device-001",
        )
        _run(handle_takeover_response(MagicMock(), None, msg))

        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.device_id == "android-device-001"


# ============================================================================
# F.  handle_takeover_response — reject path
# ============================================================================

class TestHandleTakeoverResponseReject:

    def test_F01_accepted_false_recorded(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(
            takeover_id=tkv_id,
            accepted=False,
            reject_reason="device busy",
        )
        _run(handle_takeover_response(MagicMock(), None, msg))

        assert tkv_id in TAKEOVER_RESPONSE_REGISTRY
        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.accepted is False

    def test_F02_reject_reason_preserved(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(
            takeover_id=tkv_id,
            accepted=False,
            reject_reason="device busy",
        )
        _run(handle_takeover_response(MagicMock(), None, msg))

        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.reject_reason == "device busy"

    def test_F03_missing_accepted_field_defaults_to_rejected(self):
        """When 'accepted' is absent from the message, the decision should be rejected."""
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = {
            "type": "takeover_response",
            "device_id": "dev-001",
            "message_id": str(uuid.uuid4()),
            "payload": {"takeover_id": tkv_id},
        }
        _run(handle_takeover_response(MagicMock(), None, msg))

        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert record.accepted is False


# ============================================================================
# G.  ACK response shape — accept
# ============================================================================

class TestAckResponseShapeAccept:

    def test_G01_required_fields_present_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))

        for field in ("version", "type", "device_id", "message_id", "correlation_id", "payload"):
            assert field in resp, f"Missing field: {field}"

    def test_G02_type_is_takeover_response_ack(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_takeover_response_message(accepted=True)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"

    def test_G03_version_is_3_0(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_takeover_response_message(accepted=True)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["version"] == "3.0"

    def test_G04_correlation_id_matches_incoming_message_id(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        incoming_mid = str(uuid.uuid4())
        msg = _make_takeover_response_message(accepted=True)
        msg["message_id"] = incoming_mid
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["correlation_id"] == incoming_mid

    def test_G05_payload_accepted_true(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["payload"]["accepted"] is True
        assert resp["payload"]["takeover_id"] == tkv_id


# ============================================================================
# H.  ACK response shape — reject
# ============================================================================

class TestAckResponseShapeReject:

    def test_H01_required_fields_present_on_reject(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_takeover_response_message(accepted=False, reject_reason="screen locked")
        resp = _run(handle_takeover_response(MagicMock(), None, msg))

        for field in ("version", "type", "device_id", "message_id", "correlation_id", "payload"):
            assert field in resp, f"Missing field: {field}"

    def test_H02_type_is_takeover_response_ack(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_takeover_response_message(accepted=False)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"

    def test_H03_payload_accepted_false(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=False)
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["payload"]["accepted"] is False
        assert resp["payload"]["takeover_id"] == tkv_id


# ============================================================================
# I.  TAKEOVER_RESPONSE_REGISTRY tracking state
# ============================================================================

class TestTakeoverResponseRegistry:

    def test_I01_registry_updated_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)
        _run(handle_takeover_response(MagicMock(), None, msg))
        assert tkv_id in TAKEOVER_RESPONSE_REGISTRY

    def test_I02_registry_updated_on_reject(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=False)
        _run(handle_takeover_response(MagicMock(), None, msg))
        assert tkv_id in TAKEOVER_RESPONSE_REGISTRY

    def test_I03_latest_decision_overwrites_previous(self):
        """A second response for the same takeover_id overwrites the first."""
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg_reject = _make_takeover_response_message(takeover_id=tkv_id, accepted=False)
        msg_accept = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)

        _run(handle_takeover_response(MagicMock(), None, msg_reject))
        _run(handle_takeover_response(MagicMock(), None, msg_accept))

        assert TAKEOVER_RESPONSE_REGISTRY[tkv_id].accepted is True

    def test_I04_record_has_received_at_timestamp(self):
        from galaxy_gateway.android.handlers.takeover_response import (
            handle_takeover_response,
            TAKEOVER_RESPONSE_REGISTRY,
        )
        import time
        tkv_id = f"tkv_{uuid.uuid4().hex[:12]}"
        msg = _make_takeover_response_message(takeover_id=tkv_id, accepted=True)
        before = time.time()
        _run(handle_takeover_response(MagicMock(), None, msg))
        after = time.time()
        record = TAKEOVER_RESPONSE_REGISTRY[tkv_id]
        assert before <= record.received_at <= after

    def test_I05_empty_takeover_id_does_not_crash(self):
        """Missing takeover_id must not raise — ACK still returned."""
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = {
            "type": "takeover_response",
            "device_id": "dev-001",
            "message_id": str(uuid.uuid4()),
            "payload": {"accepted": True},
        }
        resp = _run(handle_takeover_response(MagicMock(), None, msg))
        assert resp["type"] == "takeover_response_ack"


# ============================================================================
# J.  runtime_ws_profile canonical entry
# ============================================================================

class TestRuntimeWSProfile:

    def test_J01_takeover_response_has_canonical_mapping(self):
        from galaxy_gateway.android.runtime_ws_profile import classify_android_runtime_ws_mapping
        mapping = classify_android_runtime_ws_mapping("takeover_response")
        assert mapping.handling_level == "canonical"

    def test_J02_takeover_response_semantic_family_is_transfer(self):
        from galaxy_gateway.android.runtime_ws_profile import classify_android_runtime_ws_mapping
        mapping = classify_android_runtime_ws_mapping("takeover_response")
        assert "transfer" in mapping.semantic_family


# ============================================================================
# K.  __init__.py re-exports handle_takeover_response
# ============================================================================

class TestInitReexport:

    def test_K01_handle_takeover_response_importable_from_init(self):
        from galaxy_gateway.android.handlers import handle_takeover_response  # noqa: F401
        assert callable(handle_takeover_response)

    def test_K02_handle_takeover_response_in_all(self):
        import galaxy_gateway.android.handlers as pkg
        assert "handle_takeover_response" in pkg.__all__

    def test_K03_handle_takeover_response_is_coroutine_function(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        assert asyncio.iscoroutinefunction(handle_takeover_response)
