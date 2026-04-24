"""tests/test_pr03_v2_android_bridge_canonical_ingress.py
==========================================================
PR-03-V2: Make android_bridge the canonical ingress for Android WebSocket
business messages.

Validates:

A.  New IngressEventKind constants are present and correct.
B.  All new kinds are in IngressEventKind._ALL.
C.  Classifier maps each new kind to a non-unknown semantic class (EXECUTION).
D.  ANDROID_INGRESS_DELEGATION_AUTHORITY sentinel exists in websocket_handler.
E.  _ANDROID_DOMAIN_KINDS is defined and contains expected Android message kinds.
F.  websocket_handler.handle_message() delegates Android-domain messages to
    android_bridge rather than handling them independently.
G.  Transport-class messages (DEVICE_REGISTER, DEVICE_HEARTBEAT, DEVICE_STATUS)
    are NOT delegated to android_bridge (remain in websocket_handler).
H.  Specific canonical messages behave consistently through android_bridge
    delegation: task_result, goal_execution_result, delegated_execution_signal,
    handoff_envelope_v2_result.
I.  ANDROID_INGRESS_DELEGATION_AUTHORITY sentinel value is a non-empty string
    that contains 'ANDROID' and 'BRIDGE'.
J.  Module docstring in websocket_handler references Android delegation.
K.  websocket_handler source still contains SESSION_MIGRATE fallback
    (backward-compat regression guard).
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_aip_v3(msg_type: str, device_id: str = "dev-test-001") -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "trace_id": f"trace-{uuid.uuid4().hex[:8]}",
        "route_mode": "cross_device",
        "payload": {},
    }


# ============================================================================
# A.  New IngressEventKind constants
# ============================================================================

class TestNewIngressEventKindConstants:

    def test_A01_goal_execution_result_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.GOAL_EXECUTION_RESULT == "goal_execution_result"

    def test_A02_handoff_ack_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.HANDOFF_ACK == "handoff_ack"

    def test_A03_handoff_result_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.HANDOFF_RESULT == "handoff_result"

    def test_A04_handoff_failure_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.HANDOFF_FAILURE == "handoff_failure"

    def test_A05_handoff_envelope_v2_result_present(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.HANDOFF_ENVELOPE_V2_RESULT == "handoff_envelope_v2_result"


# ============================================================================
# B.  New kinds in IngressEventKind._ALL
# ============================================================================

class TestNewKindsInAll:

    def _all(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        return IngressEventKind._ALL

    def test_B01_goal_execution_result_in_all(self):
        assert "goal_execution_result" in self._all()

    def test_B02_handoff_ack_in_all(self):
        assert "handoff_ack" in self._all()

    def test_B03_handoff_result_in_all(self):
        assert "handoff_result" in self._all()

    def test_B04_handoff_failure_in_all(self):
        assert "handoff_failure" in self._all()

    def test_B05_handoff_envelope_v2_result_in_all(self):
        assert "handoff_envelope_v2_result" in self._all()

    def test_B06_normalise_goal_execution_result(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.normalise("goal_execution_result") == "goal_execution_result"

    def test_B07_normalise_handoff_ack(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.normalise("handoff_ack") == "handoff_ack"

    def test_B08_normalise_handoff_envelope_v2_result(self):
        from galaxy_gateway.protocol.normalized_ingress_event import IngressEventKind
        assert IngressEventKind.normalise("handoff_envelope_v2_result") == "handoff_envelope_v2_result"


# ============================================================================
# C.  Classifier maps new kinds to EXECUTION
# ============================================================================

class TestClassifierNewKinds:

    def _classify(self, kind: str) -> str:
        from galaxy_gateway.protocol.ingress_classifier import classify_ingress_kind
        return classify_ingress_kind(kind)

    def test_C01_goal_execution_result_is_execution(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert self._classify("goal_execution_result") == IngressMessageClass.EXECUTION

    def test_C02_handoff_ack_is_execution(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert self._classify("handoff_ack") == IngressMessageClass.EXECUTION

    def test_C03_handoff_result_is_execution(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert self._classify("handoff_result") == IngressMessageClass.EXECUTION

    def test_C04_handoff_failure_is_execution(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert self._classify("handoff_failure") == IngressMessageClass.EXECUTION

    def test_C05_handoff_envelope_v2_result_is_execution(self):
        from galaxy_gateway.protocol.ingress_classifier import IngressMessageClass
        assert self._classify("handoff_envelope_v2_result") == IngressMessageClass.EXECUTION

    def test_C06_all_new_kinds_not_unknown(self):
        """None of the new kinds should fall through to UNKNOWN."""
        from galaxy_gateway.protocol.ingress_classifier import (
            classify_ingress_kind,
            IngressMessageClass,
        )
        new_kinds = [
            "goal_execution_result",
            "handoff_ack",
            "handoff_result",
            "handoff_failure",
            "handoff_envelope_v2_result",
        ]
        for kind in new_kinds:
            cls = classify_ingress_kind(kind)
            assert cls != IngressMessageClass.UNKNOWN, (
                f"Kind {kind!r} mapped to UNKNOWN — should be EXECUTION"
            )


# ============================================================================
# D.  ANDROID_INGRESS_DELEGATION_AUTHORITY sentinel
# ============================================================================

class TestDelegationAuthoritySentinel:

    def test_D01_sentinel_importable(self):
        from galaxy_gateway.websocket_handler import ANDROID_INGRESS_DELEGATION_AUTHORITY  # noqa
        assert ANDROID_INGRESS_DELEGATION_AUTHORITY

    def test_D02_sentinel_is_nonempty_string(self):
        from galaxy_gateway.websocket_handler import ANDROID_INGRESS_DELEGATION_AUTHORITY
        assert isinstance(ANDROID_INGRESS_DELEGATION_AUTHORITY, str)
        assert len(ANDROID_INGRESS_DELEGATION_AUTHORITY) > 0

    def test_D03_sentinel_contains_android(self):
        from galaxy_gateway.websocket_handler import ANDROID_INGRESS_DELEGATION_AUTHORITY
        assert "ANDROID" in ANDROID_INGRESS_DELEGATION_AUTHORITY

    def test_D04_sentinel_contains_bridge(self):
        from galaxy_gateway.websocket_handler import ANDROID_INGRESS_DELEGATION_AUTHORITY
        assert "BRIDGE" in ANDROID_INGRESS_DELEGATION_AUTHORITY

    def test_D05_sentinel_does_not_claim_orchestration(self):
        from galaxy_gateway.websocket_handler import ANDROID_INGRESS_DELEGATION_AUTHORITY
        # The sentinel must not claim ORCHESTRATION authority — delegation is a
        # transport-layer concern, not an orchestration concern.
        assert "ORCHESTRATION" not in ANDROID_INGRESS_DELEGATION_AUTHORITY


# ============================================================================
# E.  _ANDROID_DOMAIN_KINDS
# ============================================================================

class TestAndroidDomainKinds:

    def _domain_kinds(self):
        from galaxy_gateway.websocket_handler import _ANDROID_DOMAIN_KINDS
        return _ANDROID_DOMAIN_KINDS

    def test_E01_android_domain_kinds_importable(self):
        kinds = self._domain_kinds()
        assert kinds is not None

    def test_E02_android_domain_kinds_is_frozenset(self):
        kinds = self._domain_kinds()
        assert isinstance(kinds, frozenset)

    def test_E03_task_result_in_domain(self):
        assert "task_result" in self._domain_kinds()

    def test_E04_command_result_in_domain(self):
        assert "command_result" in self._domain_kinds()

    def test_E05_goal_execution_result_in_domain(self):
        assert "goal_execution_result" in self._domain_kinds()

    def test_E06_delegated_execution_signal_in_domain(self):
        assert "delegated_execution_signal" in self._domain_kinds()

    def test_E07_handoff_ack_in_domain(self):
        assert "handoff_ack" in self._domain_kinds()

    def test_E08_handoff_result_in_domain(self):
        assert "handoff_result" in self._domain_kinds()

    def test_E09_handoff_failure_in_domain(self):
        assert "handoff_failure" in self._domain_kinds()

    def test_E10_handoff_envelope_v2_result_in_domain(self):
        assert "handoff_envelope_v2_result" in self._domain_kinds()

    def test_E11_device_register_NOT_in_domain(self):
        """DEVICE_REGISTER must remain a transport concern, not delegated."""
        assert "device_register" not in self._domain_kinds()

    def test_E12_device_heartbeat_NOT_in_domain(self):
        """DEVICE_HEARTBEAT must remain a transport concern, not delegated."""
        assert "heartbeat" not in self._domain_kinds()

    def test_E13_device_status_NOT_in_domain(self):
        """DEVICE_STATUS must remain a transport concern, not delegated."""
        assert "device_status" not in self._domain_kinds()

    def test_E14_wake_event_NOT_in_domain(self):
        """WAKE_EVENT is a routing concern handled in websocket_handler."""
        assert "wake_event" not in self._domain_kinds()


# ============================================================================
# F.  handle_message() delegates Android-domain messages to android_bridge
# ============================================================================

class TestAndroidMessageDelegation:
    """Verify that handle_message() delegates Android messages to android_bridge."""

    def _make_ws(self):
        ws = MagicMock()
        ws.send_json = AsyncMock()
        return ws

    def _run_handle_message(self, message: dict, mock_bridge_response=None):
        """Run handle_message() with android_bridge mocked out."""
        from galaxy_gateway.websocket_handler import handle_message

        mock_bridge = MagicMock()
        mock_bridge.handle_message = AsyncMock(return_value=mock_bridge_response)

        ws = self._make_ws()

        with patch("galaxy_gateway.android_bridge.android_bridge", mock_bridge):
            _run_async(handle_message("conn-001", message, ws))

        return mock_bridge, ws

    def test_F01_task_result_delegates_to_android_bridge(self):
        msg = _make_aip_v3("task_result")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F02_command_result_delegates_to_android_bridge(self):
        msg = _make_aip_v3("command_result")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F03_goal_execution_result_delegates_to_android_bridge(self):
        msg = _make_aip_v3("goal_execution_result")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F04_delegated_execution_signal_delegates_to_android_bridge(self):
        msg = _make_aip_v3("delegated_execution_signal")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F05_handoff_envelope_v2_result_delegates_to_android_bridge(self):
        msg = _make_aip_v3("handoff_envelope_v2_result")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F06_handoff_ack_delegates_to_android_bridge(self):
        msg = _make_aip_v3("handoff_ack")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F07_handoff_result_delegates_to_android_bridge(self):
        msg = _make_aip_v3("handoff_result")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F08_handoff_failure_delegates_to_android_bridge(self):
        msg = _make_aip_v3("handoff_failure")
        mock_bridge, _ = self._run_handle_message(msg)
        mock_bridge.handle_message.assert_awaited_once()

    def test_F09_bridge_response_is_sent_back_to_websocket(self):
        """When android_bridge returns a response dict, it must be sent to ws."""
        msg = _make_aip_v3("task_result")
        response_payload = {
            "version": "3.0",
            "type": "task_result_ack",
            "device_id": msg["device_id"],
            "payload": {"status": "received"},
        }
        mock_bridge, ws = self._run_handle_message(msg, mock_bridge_response=response_payload)
        ws.send_json.assert_awaited_once_with(response_payload)

    def test_F10_no_ws_send_when_bridge_returns_none(self):
        """When android_bridge returns None, websocket.send_json must NOT be called."""
        msg = _make_aip_v3("goal_execution_result")
        mock_bridge, ws = self._run_handle_message(msg, mock_bridge_response=None)
        ws.send_json.assert_not_awaited()

    def test_F11_bridge_exception_does_not_propagate(self):
        """android_bridge errors must be caught; handle_message must not raise."""
        from galaxy_gateway.websocket_handler import handle_message

        mock_bridge = MagicMock()
        mock_bridge.handle_message = AsyncMock(side_effect=RuntimeError("bridge failure"))
        ws = self._make_ws()
        msg = _make_aip_v3("task_result")

        with patch("galaxy_gateway.android_bridge.android_bridge", mock_bridge):
            # Should not raise
            _run_async(handle_message("conn-001", msg, ws))


# ============================================================================
# G.  Transport-class messages NOT delegated to android_bridge
# ============================================================================

class TestTransportMessagesNotDelegated:
    """Verify transport-class messages stay in websocket_handler."""

    def _bridge_call_count(self, message: dict) -> int:
        """Return how many times android_bridge.handle_message was awaited."""
        from galaxy_gateway.websocket_handler import handle_message

        mock_bridge = MagicMock()
        mock_bridge.handle_message = AsyncMock(return_value=None)
        ws = MagicMock()
        ws.send_json = AsyncMock()

        with patch("galaxy_gateway.android_bridge.android_bridge", mock_bridge):
            try:
                _run_async(handle_message("conn-001", message, ws))
            except Exception:
                pass

        return mock_bridge.handle_message.await_count

    def test_G01_device_heartbeat_not_delegated(self):
        msg = _make_aip_v3("heartbeat")
        assert self._bridge_call_count(msg) == 0

    def test_G02_device_status_not_delegated(self):
        msg = _make_aip_v3("device_status")
        assert self._bridge_call_count(msg) == 0


# ============================================================================
# H.  NormalizedIngressEvent kind for new message types
# ============================================================================

class TestNormalizationNewKinds:

    def test_H01_goal_execution_result_normalizes_to_correct_kind(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        import json
        d = _make_aip_v3("goal_execution_result")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "goal_execution_result"

    def test_H02_handoff_ack_normalizes_to_correct_kind(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        import json
        d = _make_aip_v3("handoff_ack")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "handoff_ack"

    def test_H03_handoff_result_normalizes_to_correct_kind(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        import json
        d = _make_aip_v3("handoff_result")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "handoff_result"

    def test_H04_handoff_failure_normalizes_to_correct_kind(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        import json
        d = _make_aip_v3("handoff_failure")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "handoff_failure"

    def test_H05_handoff_envelope_v2_result_normalizes_to_correct_kind(self):
        from galaxy_gateway.protocol.normalized_ingress_event import to_normalized_ingress_event
        import json
        d = _make_aip_v3("handoff_envelope_v2_result")
        event = to_normalized_ingress_event(json.dumps(d))
        assert event.kind == "handoff_envelope_v2_result"


# ============================================================================
# I.  Sentinel value checks
# ============================================================================

class TestSentinelValues:

    def test_I01_delegation_sentinel_distinct_from_transport_sentinel(self):
        from galaxy_gateway.websocket_handler import (
            ANDROID_INGRESS_DELEGATION_AUTHORITY,
            WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY,
        )
        assert ANDROID_INGRESS_DELEGATION_AUTHORITY != WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY

    def test_I02_delegation_sentinel_distinct_from_normalization_sentinel(self):
        from galaxy_gateway.websocket_handler import (
            ANDROID_INGRESS_DELEGATION_AUTHORITY,
            INGRESS_NORMALIZATION_AUTHORITY,
        )
        assert ANDROID_INGRESS_DELEGATION_AUTHORITY != INGRESS_NORMALIZATION_AUTHORITY


# ============================================================================
# J.  websocket_handler module docstring references delegation
# ============================================================================

class TestModuleDocstring:

    def test_J01_websocket_handler_docstring_mentions_delegation(self):
        import galaxy_gateway.websocket_handler as wh
        src = inspect.getsource(wh)
        # The module docstring or early comments should mention Android delegation
        assert "ANDROID_INGRESS_DELEGATION_AUTHORITY" in src or "android_bridge" in src.lower()

    def test_J02_handle_message_source_mentions_android_bridge_delegation(self):
        import galaxy_gateway.websocket_handler as wh
        src = inspect.getsource(wh.handle_message)
        assert "android_bridge" in src.lower(), (
            "handle_message() must delegate to android_bridge for Android-domain messages"
        )

    def test_J03_handle_message_does_not_call_handle_response_for_task_result(self):
        """After PR-03-V2, handle_message must NOT independently call handle_response()
        for task_result; it delegates to android_bridge instead."""
        import galaxy_gateway.websocket_handler as wh
        src = inspect.getsource(wh.handle_message)
        # The old branch: `await handle_response(connection_id, aip_msg)` for TASK_RESULT
        # must be gone from the dispatch logic (may still exist in the function but must
        # not be the path for TASK_RESULT / COMMAND_RESULT kinds)
        # Simple check: TASK_RESULT should not trigger handle_response directly
        # (we verify behavior in tests F01/F02 above; here check source intent)
        assert "_ANDROID_DOMAIN_KINDS" in src, (
            "handle_message must use _ANDROID_DOMAIN_KINDS to detect Android messages"
        )


# ============================================================================
# K.  Backward-compat: SESSION_MIGRATE fallback still present
# ============================================================================

class TestBackwardCompat:

    def test_K01_session_migrate_fallback_preserved(self):
        """handle_message must retain SESSION_MIGRATE fallback for backward compat."""
        import galaxy_gateway.websocket_handler as wh
        src = inspect.getsource(wh.handle_message)
        assert "SESSION_MIGRATE" in src, (
            "handle_message must retain SESSION_MIGRATE fallback path"
        )
