"""tests/test_takeover_executor_integration.py
=============================================
End-to-end integration tests for V2-side takeover executor integration.

These tests prove that takeover is not merely a protocol event, but an
end-to-end orchestrated capability with canonical tracking, lifecycle
state management, and audit integration.

Coverage groups
---------------
M.  send_takeover_request — lifecycle coordinator notified (request path).
N.  handle_takeover_response — lifecycle coordinator called (response path).
O.  Tracking ring-buffer — records stored and queryable after response.
P.  Snapshot visibility — takeover decisions appear in operator snapshot.
Q.  Both accept and reject paths store correct tracking fields.
R.  Coordinator integration — on_takeover_response outcome fields.
S.  send_takeover_request — coordinator failure does not break send.
T.  TakeoverTrackingRecord — canonical shape and queryability.
U.  Validation note — V2 closed items vs Android PR #247 dependencies.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_running_loop().run_until_complete(coro)


def _make_accept_msg(
    takeover_id: str = "",
    device_id: str = "device-test",
    session_id: str = "",
    task_id: str = "",
    trace_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "takeover_id": takeover_id or f"tkv_{uuid.uuid4().hex[:12]}",
        "accepted": True,
        "reason": "user confirmed",
        "session_id": session_id or f"sess_{uuid.uuid4().hex[:8]}",
        "task_id": task_id,
        "trace_id": trace_id,
    }


def _make_reject_msg(
    takeover_id: str = "",
    device_id: str = "device-test",
    reason: str = "user denied",
) -> Dict[str, Any]:
    return {
        "type": "takeover_response",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "takeover_id": takeover_id or f"tkv_{uuid.uuid4().hex[:12]}",
        "accepted": False,
        "reason": reason,
    }


# ============================================================================
# M.  send_takeover_request — lifecycle coordinator notified on send
# ============================================================================

class TestSendTakeoverRequestCoordinatorIntegration:
    """Verify send_takeover_request notifies the lifecycle coordinator so
    the outbound request is recorded as a canonical orchestrated lifecycle
    event (session state transition + audit), not a bare message send."""

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_M01_coordinator_on_takeover_requested_called_after_send(self):
        bridge = self._make_bridge()
        sent = []

        async def _fake_send(device_id, message, **kwargs):
            sent.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_requested.return_value = MagicMock(
            was_handled=True, phase_before="", phase_after="", was_transitioned=False
        )

        with patch(
            "galaxy_gateway.android_bridge._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(bridge.send_takeover_request(
                "dev-1",
                "tkv-abc",
                session_id="sess-123",
                trace_id="trace-xyz",
            ))

        mock_coordinator.on_takeover_requested.assert_called_once()
        call_kwargs = mock_coordinator.on_takeover_requested.call_args[1]
        assert call_kwargs["takeover_id"] == "tkv-abc"
        assert call_kwargs["device_id"] == "dev-1"
        assert call_kwargs["session_id"] == "sess-123"
        assert call_kwargs["trace_id"] == "trace-xyz"

    def test_M02_message_still_sent_when_coordinator_called(self):
        bridge = self._make_bridge()
        sent = []

        async def _fake_send(device_id, message, **kwargs):
            sent.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_requested.return_value = MagicMock(was_handled=True)

        with patch(
            "galaxy_gateway.android_bridge._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(bridge.send_takeover_request("dev-1", "tkv-coord-test"))

        assert len(sent) == 1
        assert sent[0]["type"] == "takeover_request"
        assert sent[0]["takeover_id"] == "tkv-coord-test"

    def test_M03_task_id_extracted_from_task_context(self):
        bridge = self._make_bridge()

        async def _fake_send(device_id, message, **kwargs):
            return {"success": True}

        bridge.send_to_device = _fake_send

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_requested.return_value = MagicMock(was_handled=True)

        with patch(
            "galaxy_gateway.android_bridge._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(bridge.send_takeover_request(
                "dev-1",
                "tkv-tc",
                task_context={"task_id": "task-999", "goal": "open camera"},
            ))

        call_kwargs = mock_coordinator.on_takeover_requested.call_args[1]
        assert call_kwargs["task_id"] == "task-999"


# ============================================================================
# N.  handle_takeover_response — lifecycle coordinator called (response path)
# ============================================================================

class TestHandleResponseCoordinatorIntegration:
    """Verify the response handler calls the lifecycle coordinator in addition
    to the direct tracking call, so session state reduction and audit are
    performed."""

    def test_N01_coordinator_on_takeover_response_called_on_accept(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_msg(takeover_id="tkv-n01", session_id="sess-n01")

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = MagicMock(
            was_handled=True, phase_before="dispatched", phase_after="takeover_accepted",
            was_transitioned=True
        )

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(handle_takeover_response(MagicMock(), None, msg))

        mock_coordinator.on_takeover_response.assert_called_once()
        call_kwargs = mock_coordinator.on_takeover_response.call_args[1]
        assert call_kwargs["takeover_id"] == "tkv-n01"
        assert call_kwargs["accepted"] is True
        assert call_kwargs["session_id"] == "sess-n01"

    def test_N02_coordinator_on_takeover_response_called_on_reject(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_reject_msg(takeover_id="tkv-n02", reason="screen locked")

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = MagicMock(
            was_handled=True, phase_before="takeover_pending", phase_after="takeover_rejected",
            was_transitioned=True
        )

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(handle_takeover_response(MagicMock(), None, msg))

        call_kwargs = mock_coordinator.on_takeover_response.call_args[1]
        assert call_kwargs["accepted"] is False
        assert call_kwargs["reason"] == "screen locked"

    def test_N03_ack_returned_even_when_coordinator_raises(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_msg()

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.side_effect = RuntimeError("coord failure")

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            ack = _run(handle_takeover_response(MagicMock(), None, msg))

        assert ack["type"] == "takeover_response_ack"

    def test_N04_coordinator_receives_task_id_and_trace_id(self):
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        msg = _make_accept_msg(
            takeover_id="tkv-n04",
            task_id="task-abc",
            trace_id="trace-xyz",
        )

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = MagicMock(was_handled=True)

        with patch(
            "galaxy_gateway.android.handlers.takeover_response._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            _run(handle_takeover_response(MagicMock(), None, msg))

        call_kwargs = mock_coordinator.on_takeover_response.call_args[1]
        assert call_kwargs["task_id"] == "task-abc"
        assert call_kwargs["trace_id"] == "trace-xyz"


# ============================================================================
# O.  Tracking ring-buffer — records stored and queryable after response
# ============================================================================

class TestTrackingRingBuffer:
    """Verify that after handle_takeover_response, the decision is stored
    in the canonical tracking ring buffer and queryable by takeover_id."""

    def test_O01_accept_record_stored_in_ring_buffer(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            get_takeover_record,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        tid = f"tkv_o01_{uuid.uuid4().hex[:8]}"
        msg = _make_accept_msg(takeover_id=tid, device_id="dev-o01")

        _run(handle_takeover_response(MagicMock(), None, msg))

        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.takeover_id == tid
        assert rec.device_id == "dev-o01"
        assert rec.was_accepted is True

    def test_O02_reject_record_stored_with_reason(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            get_takeover_record,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        tid = f"tkv_o02_{uuid.uuid4().hex[:8]}"
        msg = _make_reject_msg(takeover_id=tid, reason="battery low")

        _run(handle_takeover_response(MagicMock(), None, msg))

        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.was_rejected is True
        assert rec.reason == "battery low"

    def test_O03_record_captures_session_id(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            get_takeover_record,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        tid = f"tkv_o03_{uuid.uuid4().hex[:8]}"
        sid = f"sess_o03_{uuid.uuid4().hex[:6]}"
        msg = _make_accept_msg(takeover_id=tid, session_id=sid)

        _run(handle_takeover_response(MagicMock(), None, msg))

        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.session_id == sid

    def test_O04_record_queryable_by_session_id(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            list_takeover_records_for_session,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        sid = f"sess_o04_{uuid.uuid4().hex[:6]}"
        tid = f"tkv_o04_{uuid.uuid4().hex[:8]}"
        msg = _make_accept_msg(takeover_id=tid, session_id=sid)

        _run(handle_takeover_response(MagicMock(), None, msg))

        records = list_takeover_records_for_session(sid)
        assert len(records) >= 1
        assert any(r.takeover_id == tid for r in records)


# ============================================================================
# P.  Snapshot visibility — takeover decisions in operator snapshot
# ============================================================================

class TestSnapshotVisibility:
    """Verify that after a response is processed, the takeover decision
    appears in the operator-facing tracking snapshot."""

    def test_P01_snapshot_contains_accepted_record(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            takeover_tracking_snapshot,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        tid = f"tkv_p01_{uuid.uuid4().hex[:8]}"
        msg = _make_accept_msg(takeover_id=tid)

        _run(handle_takeover_response(MagicMock(), None, msg))

        snap = takeover_tracking_snapshot()
        assert snap.total_count >= 1
        assert any(r.takeover_id == tid for r in snap.records)

    def test_P02_snapshot_contains_rejected_record(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            takeover_tracking_snapshot,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response

        reset_takeover_tracking_runtime()
        tid = f"tkv_p02_{uuid.uuid4().hex[:8]}"
        msg = _make_reject_msg(takeover_id=tid)

        _run(handle_takeover_response(MagicMock(), None, msg))

        snap = takeover_tracking_snapshot()
        matching = [r for r in snap.records if r.takeover_id == tid]
        assert len(matching) >= 1
        assert matching[0].was_rejected is True

    def test_P03_snapshot_to_dict_is_serialisable(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            takeover_tracking_snapshot,
        )
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        import json

        reset_takeover_tracking_runtime()
        msg = _make_accept_msg()

        _run(handle_takeover_response(MagicMock(), None, msg))

        snap = takeover_tracking_snapshot()
        snap_dict = snap.to_dict()
        # Must be JSON-serialisable — this is the operator surface contract
        json_str = json.dumps(snap_dict)
        assert isinstance(json_str, str)
        assert "records" in snap_dict


# ============================================================================
# Q.  Both accept and reject paths store correct canonical fields
# ============================================================================

class TestCanonicalFieldsOnBothPaths:
    """Prove that both the accept and reject paths write a complete
    TakeoverTrackingRecord with all canonical identity fields."""

    def _process(self, msg: Dict[str, Any]) -> Any:
        from galaxy_gateway.android.handlers.takeover_response import handle_takeover_response
        _run(handle_takeover_response(MagicMock(), None, msg))

    def test_Q01_accept_record_has_record_id(self):
        from core.takeover_tracking import reset_takeover_tracking_runtime, get_takeover_record
        reset_takeover_tracking_runtime()
        tid = f"tkv_q01_{uuid.uuid4().hex[:8]}"
        self._process(_make_accept_msg(takeover_id=tid))
        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.record_id != ""

    def test_Q02_reject_record_has_record_id(self):
        from core.takeover_tracking import reset_takeover_tracking_runtime, get_takeover_record
        reset_takeover_tracking_runtime()
        tid = f"tkv_q02_{uuid.uuid4().hex[:8]}"
        self._process(_make_reject_msg(takeover_id=tid))
        rec = get_takeover_record(tid)
        assert rec is not None
        assert rec.record_id != ""

    def test_Q03_accept_record_decision_is_accepted(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            get_takeover_record,
            TakeoverDecision,
        )
        reset_takeover_tracking_runtime()
        tid = f"tkv_q03_{uuid.uuid4().hex[:8]}"
        self._process(_make_accept_msg(takeover_id=tid))
        rec = get_takeover_record(tid)
        assert rec.decision == TakeoverDecision.accepted

    def test_Q04_reject_record_decision_is_rejected(self):
        from core.takeover_tracking import (
            reset_takeover_tracking_runtime,
            get_takeover_record,
            TakeoverDecision,
        )
        reset_takeover_tracking_runtime()
        tid = f"tkv_q04_{uuid.uuid4().hex[:8]}"
        self._process(_make_reject_msg(takeover_id=tid, reason="offline"))
        rec = get_takeover_record(tid)
        assert rec.decision == TakeoverDecision.rejected

    def test_Q05_record_to_dict_contains_all_required_keys(self):
        from core.takeover_tracking import reset_takeover_tracking_runtime, get_takeover_record
        reset_takeover_tracking_runtime()
        tid = f"tkv_q05_{uuid.uuid4().hex[:8]}"
        self._process(_make_accept_msg(takeover_id=tid))
        rec = get_takeover_record(tid)
        d = rec.to_dict()
        for key in ("record_id", "takeover_id", "device_id", "decision",
                    "session_id", "task_id", "trace_id", "reason", "recorded_at"):
            assert key in d, f"Missing key: {key}"


# ============================================================================
# R.  Coordinator integration — outcome fields from on_takeover_response
# ============================================================================

class TestCoordinatorOutcomeFields:
    """Verify that the lifecycle coordinator returns a structured outcome
    with the correct event_type and was_handled fields."""

    def test_R01_coordinator_outcome_event_type_is_takeover_response(self):
        from core.android_delegated_runtime_lifecycle_coordinator import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        reset_lifecycle_coordinator()
        coordinator = get_lifecycle_coordinator()
        outcome = coordinator.on_takeover_response(
            session_id="sess-r01",
            takeover_id="tkv-r01",
            device_id="dev-r01",
            accepted=True,
            reason="",
        )
        assert outcome.event_type == "takeover_response"

    def test_R02_coordinator_outcome_was_handled_is_true(self):
        from core.android_delegated_runtime_lifecycle_coordinator import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        reset_lifecycle_coordinator()
        coordinator = get_lifecycle_coordinator()
        outcome = coordinator.on_takeover_response(
            session_id="sess-r02",
            takeover_id="tkv-r02",
            device_id="dev-r02",
            accepted=False,
            reason="rejected",
        )
        assert outcome.was_handled is True

    def test_R03_coordinator_on_takeover_requested_event_type(self):
        from core.android_delegated_runtime_lifecycle_coordinator import (
            get_lifecycle_coordinator,
            reset_lifecycle_coordinator,
        )
        reset_lifecycle_coordinator()
        coordinator = get_lifecycle_coordinator()
        outcome = coordinator.on_takeover_requested(
            session_id="sess-r03",
            takeover_id="tkv-r03",
            device_id="dev-r03",
        )
        assert outcome.event_type == "takeover_requested"
        assert outcome.was_handled is True


# ============================================================================
# S.  send_takeover_request — coordinator failure does not break send
# ============================================================================

class TestSendResilientToCoordinatorFailure:
    """Verify that send_takeover_request returns the send result even when
    the lifecycle coordinator call raises an exception."""

    def _make_bridge(self) -> Any:
        from galaxy_gateway.android_bridge import AndroidBridge
        return AndroidBridge()

    def test_S01_coordinator_exception_does_not_prevent_message_send(self):
        bridge = self._make_bridge()
        sent = []

        async def _fake_send(device_id, message, **kwargs):
            sent.append(message)
            return {"success": True}

        bridge.send_to_device = _fake_send

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_requested.side_effect = RuntimeError("coord exploded")

        with patch(
            "galaxy_gateway.android_bridge._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            result = _run(bridge.send_takeover_request("dev-1", "tkv-s01"))

        assert result == {"success": True}
        assert len(sent) == 1

    def test_S02_send_result_propagated_when_coordinator_ok(self):
        bridge = self._make_bridge()

        async def _fake_send(device_id, message, **kwargs):
            return {"success": True, "custom": "value"}

        bridge.send_to_device = _fake_send

        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_requested.return_value = MagicMock(was_handled=True)

        with patch(
            "galaxy_gateway.android_bridge._get_lifecycle_coordinator",
            return_value=mock_coordinator,
        ):
            result = _run(bridge.send_takeover_request("dev-1", "tkv-s02"))

        assert result == {"success": True, "custom": "value"}


# ============================================================================
# T.  TakeoverTrackingRecord — canonical shape and to_json
# ============================================================================

class TestTakeoverTrackingRecordShape:
    """Verify the canonical shape of TakeoverTrackingRecord and its
    serialisation to JSON (operator surface contract)."""

    def test_T01_record_to_json_is_valid_json(self):
        from core.takeover_tracking import TakeoverTrackingRecord, TakeoverDecision
        import json
        rec = TakeoverTrackingRecord(
            takeover_id="tkv-t01",
            device_id="dev-t01",
            decision=TakeoverDecision.accepted,
            session_id="sess-t01",
            task_id="task-t01",
            trace_id="trace-t01",
            reason="",
        )
        json_str = rec.to_json()
        data = json.loads(json_str)
        assert data["takeover_id"] == "tkv-t01"
        assert data["decision"] == "accepted"

    def test_T02_was_accepted_and_was_rejected_are_mutually_exclusive(self):
        from core.takeover_tracking import TakeoverTrackingRecord, TakeoverDecision
        accepted_rec = TakeoverTrackingRecord(
            takeover_id="tkv-t02a", device_id="d", decision=TakeoverDecision.accepted
        )
        rejected_rec = TakeoverTrackingRecord(
            takeover_id="tkv-t02r", device_id="d", decision=TakeoverDecision.rejected
        )
        assert accepted_rec.was_accepted is True
        assert accepted_rec.was_rejected is False
        assert rejected_rec.was_accepted is False
        assert rejected_rec.was_rejected is True

    def test_T03_from_bool_maps_correctly(self):
        from core.takeover_tracking import TakeoverDecision
        assert TakeoverDecision.from_bool(True) == TakeoverDecision.accepted
        assert TakeoverDecision.from_bool(False) == TakeoverDecision.rejected


# ============================================================================
# U.  Validation note — V2 closed items vs Android PR #247 dependencies
# ============================================================================

class TestValidationNote:
    """Structured evidence of what is fully closed on the V2 side and what
    still depends on the Android companion PR #247.

    This is a documentation-as-test group: all assertions are about V2-side
    contracts that are now provably closed.
    """

    def test_U01_takeover_tracking_module_importable(self):
        """core.takeover_tracking is importable — canonical tracking store is present."""
        from core.takeover_tracking import (  # noqa: F401
            TakeoverDecision,
            TakeoverTrackingRecord,
            TakeoverTrackingRuntime,
            record_takeover_response,
            get_takeover_record,
            list_takeover_records_for_session,
            takeover_tracking_snapshot,
        )

    def test_U02_takeover_response_handler_has_direct_tracking_hook(self):
        """Handler exposes _record_takeover_response for testability."""
        import galaxy_gateway.android.handlers.takeover_response as mod
        assert hasattr(mod, "_record_takeover_response")

    def test_U03_lifecycle_coordinator_has_on_takeover_requested_and_on_takeover_response(self):
        """Coordinator exposes both request and response lifecycle methods."""
        from core.android_delegated_runtime_lifecycle_coordinator import (
            AndroidDelegatedRuntimeLifecycleCoordinator,
        )
        assert callable(
            getattr(AndroidDelegatedRuntimeLifecycleCoordinator, "on_takeover_requested", None)
        )
        assert callable(
            getattr(AndroidDelegatedRuntimeLifecycleCoordinator, "on_takeover_response", None)
        )

    def test_U04_android_bridge_send_takeover_request_exists_and_is_coroutine(self):
        """AndroidBridge.send_takeover_request is present and async."""
        import asyncio
        from galaxy_gateway.android_bridge import AndroidBridge
        assert asyncio.iscoroutinefunction(AndroidBridge.send_takeover_request)

    def test_U05_android_bridge_has_lifecycle_coordinator_import(self):
        """android_bridge exposes _get_lifecycle_coordinator at module level."""
        import galaxy_gateway.android_bridge as mod
        assert hasattr(mod, "_get_lifecycle_coordinator")

    def test_U06_message_builder_has_takeover_request(self):
        """MessageBuilder.takeover_request() builds the canonical downlink message."""
        from galaxy_gateway.android.message_builder import MessageBuilder
        msg = MessageBuilder.takeover_request(
            device_id="v2-closed",
            takeover_id="tkv-u06",
        )
        assert msg["type"] == "takeover_request"
        assert msg["version"] == "3.0"

    def test_U07_aip_v3_has_takeover_message_types(self):
        """AIP v3 protocol layer has TAKEOVER_REQUEST and TAKEOVER_RESPONSE."""
        from galaxy_gateway.protocol.aip_v3 import MessageType
        assert MessageType.TAKEOVER_REQUEST.value == "takeover_request"
        assert MessageType.TAKEOVER_RESPONSE.value == "takeover_response"

    def test_U08_takeover_response_handler_registered_in_bridge(self):
        """AndroidBridge registers a dedicated handler for TAKEOVER_RESPONSE."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType
        bridge = AndroidBridge()
        assert MessageType.TAKEOVER_RESPONSE in bridge._message_handlers

    # Validation note (as inline docstring):
    # ------------------------------------------------------------------
    # V2-CLOSED (proven by tests in this file and test_android_takeover_protocol.py):
    #   1. TAKEOVER_REQUEST wire type and MessageBuilder ✓
    #   2. TAKEOVER_RESPONSE handler with direct tracking call ✓
    #   3. send_takeover_request notifies lifecycle coordinator (audit + state) ✓
    #   4. takeover_response handler calls lifecycle coordinator (state + audit) ✓
    #   5. TakeoverTrackingRecord stored in ring buffer, queryable by takeover_id ✓
    #   6. operator-facing snapshot lists all tracking records ✓
    #   7. Both accept and reject paths produce canonical records ✓
    #
    # STILL DEPENDS ON ANDROID PR #247:
    #   - DelegatedTakeoverExecutor full execution lifecycle on Android side
    #   - Android ReconciliationSignal emission after takeover execution
    #   - Android participant truth ingestion into V2 readiness gate
    #   - End-to-end E2E testing requiring a live Android runtime
    # ------------------------------------------------------------------
