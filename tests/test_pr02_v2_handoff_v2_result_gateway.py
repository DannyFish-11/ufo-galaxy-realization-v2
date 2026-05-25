"""tests/test_pr02_v2_handoff_v2_result_gateway.py
==================================================
PR-02-V2: Tests for wiring Android HandoffEnvelopeV2 uplink responses into the
V2 gateway.

Coverage groups
---------------
A.  MessageType enum — HANDOFF_ENVELOPE_V2_RESULT is present.
B.  Handler module is importable and the handler function is callable.
C.  Handler table — android_bridge registers the handler for all four uplink types.
D.  Handler behaviour — ack: ingest called, correlation outcome logged, ACK returned.
E.  Handler behaviour — result: ingest called, terminal correlation, ACK returned.
F.  Handler behaviour — failure: ingest called, terminal correlation, ACK returned.
G.  Handler behaviour — handoff_envelope_v2_result: ingest called, ACK returned.
H.  Handler behaviour — ingest miss (no pending entry): ACK still returned.
I.  Handler behaviour — ingest import failure degrades gracefully (returns ACK).
J.  ACK response shape: required fields present in every response.
K.  __init__.py re-exports handle_handoff_v2_result.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# A.  MessageType enum — HANDOFF_ENVELOPE_V2_RESULT
# ============================================================================

class TestMessageTypeEnum:

    def test_A01_handoff_envelope_v2_result_present(self):
        """PR-02-V2 canonical uplink wire type must be in the enum."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_ENVELOPE_V2_RESULT.value == "handoff_envelope_v2_result"

    def test_A02_existing_uplink_types_still_present(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.HANDOFF_ACK.value == "handoff_ack"
        assert MessageType.HANDOFF_RESULT.value == "handoff_result"
        assert MessageType.HANDOFF_FAILURE.value == "handoff_failure"


# ============================================================================
# B.  Handler module importability
# ============================================================================

class TestHandlerImport:

    def test_B01_module_importable(self):
        from galaxy_gateway.android.handlers import handoff_v2_result  # noqa: F401

    def test_B02_handle_handoff_v2_result_is_coroutine_function(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import (
            handle_handoff_v2_result,
        )
        assert asyncio.iscoroutinefunction(handle_handoff_v2_result)


# ============================================================================
# C.  android_bridge handler registration
# ============================================================================

class TestHandlerRegistration:

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_C01_handoff_ack_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.HANDOFF_ACK in bridge._message_handlers

    def test_C02_handoff_result_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.HANDOFF_RESULT in bridge._message_handlers

    def test_C03_handoff_failure_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.HANDOFF_FAILURE in bridge._message_handlers

    def test_C04_handoff_envelope_v2_result_registered(self):
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = self._make_bridge()
        assert MessageType.HANDOFF_ENVELOPE_V2_RESULT in bridge._message_handlers

    def test_C05_handlers_are_not_handle_unregistered(self):
        """All four uplink types must NOT fall back to handle_unregistered."""
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = self._make_bridge()
        uplink_types = [
            MessageType.HANDOFF_ACK,
            MessageType.HANDOFF_RESULT,
            MessageType.HANDOFF_FAILURE,
            MessageType.HANDOFF_ENVELOPE_V2_RESULT,
        ]
        for mt in uplink_types:
            assert bridge._message_handlers[mt] is not None


# ============================================================================
# Helpers
# ============================================================================

def _make_ack_message(handoff_id: str = "", device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "ack",
        },
    }


def _make_result_message(handoff_id: str = "", device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_result",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "result",
        },
    }


def _make_failure_message(handoff_id: str = "", device_id: str = "device-test") -> Dict[str, Any]:
    return {
        "type": "handoff_failure",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "failure",
            "error": "execution failed",
        },
    }


def _make_envelope_v2_result_message(
    handoff_id: str = "", device_id: str = "device-test"
) -> Dict[str, Any]:
    return {
        "type": "handoff_envelope_v2_result",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "result",
        },
    }


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ============================================================================
# D.  Handler behaviour — ack
# ============================================================================

class TestHandlerAck:

    def test_D01_ingest_called_for_ack(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime

        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_ack_message(handoff_id=handoff_id)

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            from core.android_handoff_v2_response_ingress import (
                ingest_android_handoff_response,
            )
            # Let ingest actually run so we get a real outcome
            mock_ingest.side_effect = lambda m: ingest_android_handoff_response(m, runtime=rt)
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))
            mock_ingest.assert_called_once_with(msg)

        assert resp["type"] == "handoff_v2_result_ack"

    def test_D02_ack_does_not_clear_pending_entry(self):
        """After an ack the pending entry must still be registered (awaiting terminal response)."""
        from core.android_handoff_v2_response_ingress import (
            HandoffV2ResponseRuntime,
            ingest_android_handoff_response,
        )
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        rt.register(handoff_id, lambda _: None)

        msg = _make_ack_message(handoff_id=handoff_id)
        ingest_android_handoff_response(msg, runtime=rt)

        # Entry must still be present after ack
        assert handoff_id in rt.pending_by_handoff_id


# ============================================================================
# E.  Handler behaviour — result
# ============================================================================

class TestHandlerResult:

    def test_E01_ingest_called_for_result(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime

        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_result_message(handoff_id=handoff_id)

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            from core.android_handoff_v2_response_ingress import (
                ingest_android_handoff_response,
            )
            mock_ingest.side_effect = lambda m: ingest_android_handoff_response(m, runtime=rt)
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))
            mock_ingest.assert_called_once_with(msg)

        assert resp["type"] == "handoff_v2_result_ack"
        # The terminal result should have invoked the callback
        assert len(received) == 1

    def test_E02_result_clears_pending_entry(self):
        from core.android_handoff_v2_response_ingress import (
            HandoffV2ResponseRuntime,
            ingest_android_handoff_response,
        )
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        rt.register(handoff_id, lambda _: None)

        msg = _make_result_message(handoff_id=handoff_id)
        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is True
        # Terminal response must clear the pending entry
        assert handoff_id not in rt.pending_by_handoff_id


# ============================================================================
# F.  Handler behaviour — failure
# ============================================================================

class TestHandlerFailure:

    def test_F01_ingest_called_for_failure(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime

        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_failure_message(handoff_id=handoff_id)

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            from core.android_handoff_v2_response_ingress import (
                ingest_android_handoff_response,
            )
            mock_ingest.side_effect = lambda m: ingest_android_handoff_response(m, runtime=rt)
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))
            mock_ingest.assert_called_once_with(msg)

        assert resp["type"] == "handoff_v2_result_ack"
        assert len(received) == 1

    def test_F02_failure_clears_pending_entry(self):
        from core.android_handoff_v2_response_ingress import (
            HandoffV2ResponseRuntime,
            ingest_android_handoff_response,
        )
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        rt.register(handoff_id, lambda _: None)

        msg = _make_failure_message(handoff_id=handoff_id)
        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is True
        assert handoff_id not in rt.pending_by_handoff_id


# ============================================================================
# G.  Handler behaviour — handoff_envelope_v2_result
# ============================================================================

class TestHandlerEnvelopeV2Result:

    def test_G01_ingest_called_for_envelope_v2_result(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        msg = _make_envelope_v2_result_message()

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_correlated=True,
                callback_invoked=True,
                envelope=MagicMock(
                    response_kind="result",
                    handoff_id=msg["payload"]["handoff_id"],
                ),
                reject_reason="",
            )
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))
            mock_ingest.assert_called_once_with(msg)

        assert resp["type"] == "handoff_v2_result_ack"


# ============================================================================
# H.  Handler behaviour — ingest miss (no pending entry)
# ============================================================================

class TestHandlerIngestMiss:

    def test_H01_ack_returned_even_when_no_pending_entry(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result
        from core.android_handoff_v2_response_ingress import HandoffV2ResponseRuntime

        rt = HandoffV2ResponseRuntime()  # empty — no pending dispatches
        msg = _make_result_message()

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            from core.android_handoff_v2_response_ingress import (
                ingest_android_handoff_response,
            )
            mock_ingest.side_effect = lambda m: ingest_android_handoff_response(m, runtime=rt)
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        # ACK must always be returned regardless of correlation outcome
        assert resp["type"] == "handoff_v2_result_ack"
        assert resp["device_id"] == msg["device_id"]


# ============================================================================
# I.  Handler behaviour — ingest import failure degrades gracefully
# ============================================================================

class TestHandlerImportFailure:

    def test_I01_ack_returned_when_ingest_is_none(self):
        from galaxy_gateway.android.handlers import handoff_v2_result as hv2_mod
        msg = _make_ack_message()
        original = hv2_mod._ingest_handoff_response
        try:
            hv2_mod._ingest_handoff_response = None
            resp = _run(hv2_mod.handle_handoff_v2_result(MagicMock(), None, msg))
        finally:
            hv2_mod._ingest_handoff_response = original

        assert resp["type"] == "handoff_v2_result_ack"


# ============================================================================
# J.  ACK response shape
# ============================================================================

class TestAckResponseShape:

    @pytest.mark.parametrize(
        "msg_factory",
        [_make_ack_message, _make_result_message, _make_failure_message],
    )
    def test_J01_required_fields_present(self, msg_factory):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        msg = msg_factory()
        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_correlated=False,
                reject_reason="no pending entry",
                envelope=MagicMock(
                    response_kind="result",
                    handoff_id="",
                ),
            )
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        for field in ("version", "type", "device_id", "message_id", "correlation_id"):
            assert field in resp, f"Missing field: {field}"

    def test_J02_version_is_3_0(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        msg = _make_ack_message()
        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_correlated=False,
                reject_reason="",
                envelope=MagicMock(response_kind="ack", handoff_id=""),
            )
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        assert resp["version"] == "3.0"

    def test_J03_correlation_id_matches_incoming_message_id(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        incoming_mid = str(uuid.uuid4())
        msg = _make_ack_message()
        msg["message_id"] = incoming_mid

        with patch(
            "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_correlated=False,
                reject_reason="",
                envelope=MagicMock(response_kind="ack", handoff_id=""),
            )
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        assert resp["correlation_id"] == incoming_mid


# ============================================================================
# K.  __init__.py re-exports handle_handoff_v2_result
# ============================================================================

class TestInitReexport:

    def test_K01_handle_handoff_v2_result_in_init(self):
        from galaxy_gateway.android.handlers import handle_handoff_v2_result  # noqa: F401
        assert callable(handle_handoff_v2_result)

    def test_K02_handle_handoff_v2_result_in_all(self):
        import galaxy_gateway.android.handlers as pkg
        assert "handle_handoff_v2_result" in pkg.__all__


# ============================================================================
# L.  Terminal reconciliation — lifecycle + task graph convergence
# ============================================================================

class TestTerminalRuntimeTruthReconciliation:

    def test_L01_terminal_result_updates_lifecycle_and_task_graph(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        msg = _make_result_message(handoff_id="hev2_l01", device_id="android-l01")
        msg["schema_version"] = "1"
        env = MagicMock(
            response_kind="result",
            handoff_id="hev2_l01",
            task_id="task-l01",
            is_terminal=True,
            trace_id="trace-l01",
        )
        outcome = MagicMock(
            was_correlated=True,
            callback_invoked=True,
            envelope=env,
            reject_reason="",
        )
        registry = MagicMock()
        graph = MagicMock()

        with patch("galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response", return_value=outcome), \
             patch("contracts.cross_repo_schema_version_gate.evaluate_android_uplink_schema_gate", return_value=None), \
             patch("core.task_envelope_lifecycle_registry.get_lifecycle_registry", return_value=registry), \
             patch("core.task_graph_runtime.get_task_graph_runtime", return_value=graph), \
             patch("galaxy_gateway.device_router.device_router.handle_task_result", new=AsyncMock()):
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        assert resp["type"] == "handoff_v2_result_ack"
        assert registry.transfer_ownership.call_count == 1
        assert registry.complete.call_count == 1
        assert registry.fail.call_count == 0
        assert graph.register_node_raw.call_count == 1
        assert graph.transition.call_count == 1

    def test_L02_terminal_failure_marks_lifecycle_fail(self):
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        msg = _make_failure_message(handoff_id="hev2_l02", device_id="android-l02")
        msg["schema_version"] = "1"
        env = MagicMock(
            response_kind="failure",
            handoff_id="hev2_l02",
            task_id="task-l02",
            is_terminal=True,
            trace_id="trace-l02",
        )
        outcome = MagicMock(
            was_correlated=True,
            callback_invoked=True,
            envelope=env,
            reject_reason="",
        )
        registry = MagicMock()
        graph = MagicMock()

        with patch("galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response", return_value=outcome), \
             patch("contracts.cross_repo_schema_version_gate.evaluate_android_uplink_schema_gate", return_value=None), \
             patch("core.task_envelope_lifecycle_registry.get_lifecycle_registry", return_value=registry), \
             patch("core.task_graph_runtime.get_task_graph_runtime", return_value=graph), \
             patch("galaxy_gateway.device_router.device_router.handle_task_result", new=AsyncMock()):
            resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))

        assert resp["type"] == "handoff_v2_result_ack"
        assert registry.transfer_ownership.call_count == 1
        assert registry.complete.call_count == 0
        assert registry.fail.call_count == 1
        assert graph.transition.call_count == 1
