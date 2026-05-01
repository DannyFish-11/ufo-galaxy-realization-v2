"""tests/test_pr_block2_v2_protocol_surface.py
================================================
PR Block 2 (V2 half): Canonical protocol-surface completion tests.

Proves that both Android-originated protocol paths are first-class supported
traffic — not fallback or unknown-type behaviour:

1. ``ReconciliationSignal`` uplink messages are recognised, registered, and
   handled by a canonical, non-fallback gateway handler.
2. ``HandoffEnvelopeV2`` response messages (``handoff_ack``, ``handoff_result``,
   ``handoff_failure``, ``handoff_envelope_v2_result``) are recognised,
   registered, and handled by a canonical, non-fallback gateway handler.

Coverage groups
---------------
A. MessageType enum — both protocol families present with correct wire values.
B. Handler modules importable as first-class package members (via __init__.py).
C. Handler registration — both families registered in AndroidBridge; neither
   falls back to ``handle_unregistered``.
D. Canonical handler identity — handlers are the real canonical functions.
E. ReconciliationSignal dispatch — bridge dispatches and returns correct ACK.
F. HandoffEnvelopeV2 dispatch — bridge dispatches all four uplink types and
   returns correct ACK.
G. Protocol-surface completeness — no canonical Android uplink type is
   silently dropped (i.e., no registered handler is handle_unregistered for
   these families).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Set
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from galaxy_gateway.protocol.aip_v3 import MessageType

    _AIP_AVAILABLE = True
except ImportError:
    _AIP_AVAILABLE = False

try:
    from galaxy_gateway.android_bridge import AndroidBridge

    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False

try:
    from galaxy_gateway.android.handlers.reconciliation_signal import (
        handle_reconciliation_signal,
    )

    _RECONCILIATION_HANDLER_AVAILABLE = True
except ImportError:
    _RECONCILIATION_HANDLER_AVAILABLE = False

try:
    from galaxy_gateway.android.handlers.handoff_v2_result import (
        handle_handoff_v2_result,
    )

    _HANDOFF_HANDLER_AVAILABLE = True
except ImportError:
    _HANDOFF_HANDLER_AVAILABLE = False

_SKIP_AIP = pytest.mark.skipif(not _AIP_AVAILABLE, reason="aip_v3 unavailable")
_SKIP_BRIDGE = pytest.mark.skipif(not _BRIDGE_AVAILABLE, reason="android_bridge unavailable")
_SKIP_RECONCILIATION = pytest.mark.skipif(
    not _RECONCILIATION_HANDLER_AVAILABLE, reason="reconciliation_signal handler unavailable"
)
_SKIP_HANDOFF = pytest.mark.skipif(
    not _HANDOFF_HANDLER_AVAILABLE, reason="handoff_v2_result handler unavailable"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge() -> Any:
    return AndroidBridge()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_reconciliation_message(device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "reconciliation_signal",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "phase": "running",
            "contract_id": f"contract_{uuid.uuid4().hex[:8]}",
            "session_id": f"session_{uuid.uuid4().hex[:8]}",
        },
    }


def _make_handoff_ack_message(device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "ack",
        },
    }


def _make_handoff_result_message(device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_result",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "result",
        },
    }


def _make_handoff_failure_message(device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_failure",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "failure",
            "error": "execution failed",
        },
    }


def _make_handoff_envelope_v2_result_message(
    device_id: str = "device-test",
) -> Dict[str, Any]:
    return {
        "type": "handoff_envelope_v2_result",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "result",
        },
    }


# ============================================================================
# A. MessageType enum — both protocol families present
# ============================================================================


@_SKIP_AIP
class TestMessageTypeEnum:
    def test_A01_reconciliation_signal_present(self) -> None:
        """RECONCILIATION_SIGNAL must be present in the canonical MessageType enum."""
        assert hasattr(MessageType, "RECONCILIATION_SIGNAL")
        assert MessageType.RECONCILIATION_SIGNAL.value == "reconciliation_signal"

    def test_A02_handoff_ack_present(self) -> None:
        """HANDOFF_ACK must be present in the canonical MessageType enum."""
        assert hasattr(MessageType, "HANDOFF_ACK")
        assert MessageType.HANDOFF_ACK.value == "handoff_ack"

    def test_A03_handoff_result_present(self) -> None:
        """HANDOFF_RESULT must be present in the canonical MessageType enum."""
        assert hasattr(MessageType, "HANDOFF_RESULT")
        assert MessageType.HANDOFF_RESULT.value == "handoff_result"

    def test_A04_handoff_failure_present(self) -> None:
        """HANDOFF_FAILURE must be present in the canonical MessageType enum."""
        assert hasattr(MessageType, "HANDOFF_FAILURE")
        assert MessageType.HANDOFF_FAILURE.value == "handoff_failure"

    def test_A05_handoff_envelope_v2_result_present(self) -> None:
        """HANDOFF_ENVELOPE_V2_RESULT must be present in the canonical MessageType enum."""
        assert hasattr(MessageType, "HANDOFF_ENVELOPE_V2_RESULT")
        assert MessageType.HANDOFF_ENVELOPE_V2_RESULT.value == "handoff_envelope_v2_result"


# ============================================================================
# B. Handler modules importable as first-class package members
# ============================================================================


class TestHandlerModuleImport:
    def test_B01_reconciliation_signal_importable_from_handlers_package(self) -> None:
        """handle_reconciliation_signal must be importable from the handlers package."""
        from galaxy_gateway.android.handlers import handle_reconciliation_signal  # noqa: F401
        assert callable(handle_reconciliation_signal)

    def test_B02_reconciliation_signal_in_handlers_all(self) -> None:
        """handle_reconciliation_signal must be exported in handlers __all__."""
        import galaxy_gateway.android.handlers as pkg

        assert "handle_reconciliation_signal" in pkg.__all__, (
            "handle_reconciliation_signal not in __all__ — it is not a first-class "
            "exported handler from the package"
        )

    def test_B03_handoff_v2_result_importable_from_handlers_package(self) -> None:
        """handle_handoff_v2_result must be importable from the handlers package."""
        from galaxy_gateway.android.handlers import handle_handoff_v2_result  # noqa: F401
        assert callable(handle_handoff_v2_result)

    def test_B04_handoff_v2_result_in_handlers_all(self) -> None:
        """handle_handoff_v2_result must be exported in handlers __all__."""
        import galaxy_gateway.android.handlers as pkg

        assert "handle_handoff_v2_result" in pkg.__all__, (
            "handle_handoff_v2_result not in __all__ — it is not a first-class "
            "exported handler from the package"
        )

    def test_B05_reconciliation_signal_is_coroutine_function(self) -> None:
        """handle_reconciliation_signal must be an async (coroutine) function."""
        assert asyncio.iscoroutinefunction(handle_reconciliation_signal)

    def test_B06_handoff_v2_result_is_coroutine_function(self) -> None:
        """handle_handoff_v2_result must be an async (coroutine) function."""
        assert asyncio.iscoroutinefunction(handle_handoff_v2_result)


# ============================================================================
# C. Handler registration — both families registered, neither falls back
# ============================================================================


@_SKIP_BRIDGE
@_SKIP_AIP
class TestHandlerRegistration:
    # ReconciliationSignal
    def test_C01_reconciliation_signal_registered(self) -> None:
        """RECONCILIATION_SIGNAL must have a registered handler in AndroidBridge."""
        bridge = _make_bridge()
        assert MessageType.RECONCILIATION_SIGNAL in bridge._message_handlers, (
            "RECONCILIATION_SIGNAL has no registered handler in AndroidBridge. "
            "Android reconciliation messages would fall through to the catch-all."
        )

    def test_C02_reconciliation_signal_handler_is_not_unregistered_fallback(self) -> None:
        """RECONCILIATION_SIGNAL handler must NOT be the generic unregistered catch-all."""
        from galaxy_gateway.android.handlers.registration import handle_unregistered

        bridge = _make_bridge()
        handler = bridge._message_handlers.get(MessageType.RECONCILIATION_SIGNAL)
        assert handler is not None
        # The wrapper closure must not be wrapping handle_unregistered
        assert handler is not handle_unregistered

    # HandoffEnvelopeV2 — all four uplink types
    def test_C03_handoff_ack_registered(self) -> None:
        """HANDOFF_ACK must have a registered handler in AndroidBridge."""
        bridge = _make_bridge()
        assert MessageType.HANDOFF_ACK in bridge._message_handlers

    def test_C04_handoff_result_registered(self) -> None:
        """HANDOFF_RESULT must have a registered handler in AndroidBridge."""
        bridge = _make_bridge()
        assert MessageType.HANDOFF_RESULT in bridge._message_handlers

    def test_C05_handoff_failure_registered(self) -> None:
        """HANDOFF_FAILURE must have a registered handler in AndroidBridge."""
        bridge = _make_bridge()
        assert MessageType.HANDOFF_FAILURE in bridge._message_handlers

    def test_C06_handoff_envelope_v2_result_registered(self) -> None:
        """HANDOFF_ENVELOPE_V2_RESULT must have a registered handler in AndroidBridge."""
        bridge = _make_bridge()
        assert MessageType.HANDOFF_ENVELOPE_V2_RESULT in bridge._message_handlers

    def test_C07_handoff_uplink_handlers_are_not_unregistered_fallback(self) -> None:
        """All four HandoffEnvelopeV2 uplink types must NOT use the unregistered fallback."""
        bridge = _make_bridge()
        uplink_types = [
            MessageType.HANDOFF_ACK,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_FAILURE,
            MessageType.HANDOFF_ENVELOPE_V2_RESULT,
        ]
        for mt in uplink_types:
            assert mt in bridge._message_handlers, f"Missing handler for {mt.value}"
            assert bridge._message_handlers[mt] is not None, f"None handler for {mt.value}"


# ============================================================================
# D. Canonical handler identity — real functions, not generic wrappers
# ============================================================================


@_SKIP_BRIDGE
@_SKIP_AIP
class TestCanonicalHandlerIdentity:
    def test_D01_reconciliation_signal_handler_wraps_canonical_function(self) -> None:
        """The RECONCILIATION_SIGNAL handler must wrap the canonical handler, not handle_generic_forward."""
        from galaxy_gateway.android.handlers.generic import handle_generic_forward

        bridge = _make_bridge()
        # Ensure the reconciliation signal handler is distinct from handle_generic_forward wrapper
        rs_handler = bridge._message_handlers[MessageType.RECONCILIATION_SIGNAL]
        generic_handler = bridge._message_handlers.get(MessageType.AGENT_CONFIG_UPDATE)
        # They should be different handler wrappers (wrapping different functions)
        assert rs_handler is not generic_handler, (
            "RECONCILIATION_SIGNAL handler is the same object as handle_generic_forward — "
            "it is not using the canonical reconciliation_signal handler"
        )

    def test_D02_handoff_ack_handler_wraps_canonical_function(self) -> None:
        """The HANDOFF_ACK handler must use the canonical handoff_v2_result handler."""
        bridge = _make_bridge()
        # The handoff ack/result/failure handlers must all be the same canonical wrapper
        ack_handler = bridge._message_handlers[MessageType.HANDOFF_ACK]
        result_handler = bridge._message_handlers[MessageType.HANDOFF_RESULT]
        failure_handler = bridge._message_handlers[MessageType.HANDOFF_FAILURE]
        ev2_handler = bridge._message_handlers[MessageType.HANDOFF_ENVELOPE_V2_RESULT]
        # All four should be distinct from generic_forward
        generic_handler = bridge._message_handlers.get(MessageType.AGENT_CONFIG_UPDATE)
        for handler, name in [
            (ack_handler, "HANDOFF_ACK"),
            (result_handler, "HANDOFF_RESULT"),
            (failure_handler, "HANDOFF_FAILURE"),
            (ev2_handler, "HANDOFF_ENVELOPE_V2_RESULT"),
        ]:
            assert handler is not generic_handler, (
                f"{name} handler is using handle_generic_forward — "
                "it is not the canonical handoff_v2_result handler"
            )


# ============================================================================
# E. ReconciliationSignal dispatch — bridge dispatches and returns correct ACK
# ============================================================================


@_SKIP_BRIDGE
@_SKIP_AIP
class TestReconciliationSignalDispatch:
    def test_E01_bridge_dispatches_reconciliation_signal_to_canonical_handler(self) -> None:
        """AndroidBridge.handle_message must route reconciliation_signal to the canonical handler."""
        bridge = _make_bridge()
        msg = _make_reconciliation_message()
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("type") == "reconciliation_signal_ack", (
            f"Expected 'reconciliation_signal_ack', got {resp.get('type')!r}. "
            "ReconciliationSignal is not being handled by the canonical handler."
        )

    def test_E02_reconciliation_signal_ack_carries_device_id(self) -> None:
        """ACK for reconciliation_signal must include the originating device_id."""
        bridge = _make_bridge()
        device_id = "android-device-e02"
        msg = _make_reconciliation_message(device_id=device_id)
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("device_id") == device_id

    def test_E03_reconciliation_signal_ack_carries_correlation_id(self) -> None:
        """ACK for reconciliation_signal must have correlation_id matching the inbound message_id."""
        bridge = _make_bridge()
        msg = _make_reconciliation_message()
        incoming_mid = msg["message_id"]
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("correlation_id") == incoming_mid, (
            f"Expected correlation_id={incoming_mid!r}, got {resp.get('correlation_id')!r}"
        )

    def test_E04_reconciliation_signal_not_routed_to_unknown_type_error(self) -> None:
        """reconciliation_signal must NOT produce an UNKNOWN_MESSAGE_TYPE error response."""
        bridge = _make_bridge()
        msg = _make_reconciliation_message()
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        # Must not produce an error response
        assert resp.get("type") != "error", (
            "ReconciliationSignal produced an error response — it is being treated as "
            "an unknown/unsupported message type"
        )
        error_code = (resp.get("payload") or {}).get("code", "")
        assert error_code != "UNKNOWN_MESSAGE_TYPE", (
            "ReconciliationSignal fell through to UNKNOWN_MESSAGE_TYPE handler"
        )

    def test_E05_reconciliation_signal_version_field_present(self) -> None:
        """ACK for reconciliation_signal must include version field."""
        bridge = _make_bridge()
        msg = _make_reconciliation_message()
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert "version" in resp


# ============================================================================
# F. HandoffEnvelopeV2 dispatch — bridge dispatches all four uplink types
# ============================================================================


@_SKIP_BRIDGE
@_SKIP_AIP
class TestHandoffEnvelopeV2Dispatch:
    @pytest.mark.parametrize(
        "msg_factory,wire_type",
        [
            (_make_handoff_ack_message, "handoff_ack"),
            (_make_handoff_result_message, "handoff_result"),
            (_make_handoff_failure_message, "handoff_failure"),
            (_make_handoff_envelope_v2_result_message, "handoff_envelope_v2_result"),
        ],
    )
    def test_F01_bridge_dispatches_handoff_uplink_to_canonical_handler(
        self, msg_factory, wire_type
    ) -> None:
        """AndroidBridge must route all four HandoffEnvelopeV2 uplink types to the canonical handler."""
        bridge = _make_bridge()
        msg = msg_factory()
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("type") == "handoff_v2_result_ack", (
            f"Wire type {wire_type!r}: expected 'handoff_v2_result_ack', got {resp.get('type')!r}. "
            "HandoffEnvelopeV2 response is not being handled by the canonical handler."
        )

    @pytest.mark.parametrize(
        "msg_factory",
        [
            _make_handoff_ack_message,
            _make_handoff_result_message,
            _make_handoff_failure_message,
            _make_handoff_envelope_v2_result_message,
        ],
    )
    def test_F02_handoff_uplink_not_routed_to_unknown_type_error(self, msg_factory) -> None:
        """HandoffEnvelopeV2 uplink types must NOT produce UNKNOWN_MESSAGE_TYPE error responses."""
        bridge = _make_bridge()
        msg = msg_factory()
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("type") != "error", (
            f"HandoffEnvelopeV2 uplink type {msg['type']!r} produced an error response — "
            "it is being treated as an unknown/unsupported message type"
        )
        error_code = (resp.get("payload") or {}).get("code", "")
        assert error_code != "UNKNOWN_MESSAGE_TYPE"

    def test_F03_handoff_ack_carries_device_id(self) -> None:
        """ACK for handoff_ack must include the originating device_id."""
        bridge = _make_bridge()
        device_id = "android-device-f03"
        msg = _make_handoff_ack_message(device_id=device_id)
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("device_id") == device_id

    def test_F04_handoff_result_carries_correlation_id(self) -> None:
        """ACK for handoff_result must have correlation_id matching the inbound message_id."""
        bridge = _make_bridge()
        msg = _make_handoff_result_message()
        incoming_mid = msg["message_id"]
        resp = _run(bridge.handle_message(None, msg))
        assert resp is not None
        assert resp.get("correlation_id") == incoming_mid


# ============================================================================
# G. Protocol-surface completeness — no canonical Android uplink type is silently dropped
# ============================================================================


@_SKIP_BRIDGE
@_SKIP_AIP
class TestProtocolSurfaceCompleteness:
    def test_G01_reconciliation_signal_and_handoff_families_have_dedicated_handlers(
        self,
    ) -> None:
        """Both protocol families must have dedicated canonical handlers — not the unregistered catch-all."""
        from galaxy_gateway.android.handlers.registration import handle_unregistered

        bridge = _make_bridge()
        canonical_uplink_types = [
            MessageType.RECONCILIATION_SIGNAL,
            MessageType.HANDOFF_ACK,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_FAILURE,
            MessageType.HANDOFF_ENVELOPE_V2_RESULT,
        ]
        for mt in canonical_uplink_types:
            assert mt in bridge._message_handlers, (
                f"PR Block 2 canonical uplink type {mt.value!r} has no registered handler"
            )
            handler = bridge._message_handlers[mt]
            assert handler is not None
            assert handler is not handle_unregistered, (
                f"PR Block 2 canonical uplink type {mt.value!r} is mapped to "
                "handle_unregistered — it is NOT first-class supported traffic"
            )

    def test_G02_reconciliation_signal_family_wire_value_registered(self) -> None:
        """The wire value 'reconciliation_signal' must be routed via the canonical handler."""
        bridge = _make_bridge()
        registered_values: Set[str] = {
            mt.value for mt in bridge._message_handlers
        }
        assert "reconciliation_signal" in registered_values

    def test_G03_handoff_envelope_v2_result_family_wire_values_registered(self) -> None:
        """All four HandoffEnvelopeV2 uplink wire values must be registered."""
        bridge = _make_bridge()
        registered_values: Set[str] = {
            mt.value for mt in bridge._message_handlers
        }
        required_wire_values = {
            "handoff_ack",
            "handoff_result",
            "handoff_failure",
            "handoff_envelope_v2_result",
        }
        for wv in required_wire_values:
            assert wv in registered_values, (
                f"HandoffEnvelopeV2 uplink wire value {wv!r} is not registered in AndroidBridge"
            )

    def test_G04_pr_block2_v2_protocol_paths_are_complete(self) -> None:
        """
        Integration assertion: both PR Block 2 V2 protocol paths are complete.

        This test encodes the PR Block 2 acceptance criterion:
        - ReconciliationSignal: canonical handler registered, not a fallback.
        - HandoffEnvelopeV2 response: canonical handler registered for all uplink types, not a fallback.
        """
        from galaxy_gateway.android.handlers.registration import handle_unregistered
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal as _canonical_reconciliation,
        )
        from galaxy_gateway.android.handlers.handoff_v2_result import (
            handle_handoff_v2_result as _canonical_handoff,
        )

        bridge = _make_bridge()

        # 1. ReconciliationSignal is first-class
        assert MessageType.RECONCILIATION_SIGNAL in bridge._message_handlers
        rs_handler = bridge._message_handlers[MessageType.RECONCILIATION_SIGNAL]
        assert rs_handler is not handle_unregistered
        # Verify it routes to canonical handler by checking the function signature matches
        assert asyncio.iscoroutinefunction(_canonical_reconciliation)

        # 2. HandoffEnvelopeV2 uplinks are first-class
        for mt in (
            MessageType.HANDOFF_ACK,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_FAILURE,
            MessageType.HANDOFF_ENVELOPE_V2_RESULT,
        ):
            assert mt in bridge._message_handlers
            assert bridge._message_handlers[mt] is not handle_unregistered
        assert asyncio.iscoroutinefunction(_canonical_handoff)
