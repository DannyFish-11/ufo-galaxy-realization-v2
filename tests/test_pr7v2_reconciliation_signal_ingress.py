"""tests/test_pr7v2_reconciliation_signal_ingress.py
======================================================
Tests for PR-7-V2: Android Reconciliation Signal Ingress.

Validates that V2 can receive ``reconciliation_signal`` messages from Android,
route them through the participant truth ingress, and advance the V2 canonical
tracking record state.

Coverage groups
---------------
Group A — Protocol: RECONCILIATION_SIGNAL present in MessageType enum.
Group B — TruthKind: reconciliation_signal in AndroidParticipantTruthKind.
Group C — Policy: RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY present.
Group D — Handler: handle_reconciliation_signal returns ACK.
Group E — Bridge registration: bridge registers RECONCILIATION_SIGNAL handler.
Group F — Ingress: reconciliation_signal advances V2 tracking record (phase-based).
Group G — Ingress: reconciliation_signal with result_success advances tracking record.
Group H — Ingress: terminal V2 state wins — reconciliation_signal rejected.
Group I — Ingress: missing lookup key → was_reconciled=False.
Group J — Ingress: no matching tracking record → was_reconciled=False.
Group K — Ingress: ingest_android_participant_truth_message end-to-end.
Group L — affects_canonical_state / is_terminal_signal guard for reconciliation_signal.
"""

from __future__ import annotations

import uuid
from typing import Any
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
    from core.android_participant_truth_ingress import (
        RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY,
        AndroidParticipantTruthEnvelope,
        AndroidParticipantTruthKind,
        extract_participant_truth_envelope,
        ingest_android_participant_truth_message,
        reconcile_android_participant_truth,
    )

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

try:
    from galaxy_gateway.android.handlers.reconciliation_signal import (
        handle_reconciliation_signal,
    )

    _HANDLER_AVAILABLE = True
except ImportError:
    _HANDLER_AVAILABLE = False

try:
    from core.delegated_runtime_execution_tracker import (
        AcknowledgmentSignal,
        DelegatedExecutionTrackingRuntime,
        apply_acknowledgment_signal,
        create_execution_tracking_record,
    )

    _TRACKER_AVAILABLE = True
except ImportError:
    _TRACKER_AVAILABLE = False

_SKIP_AIP = pytest.mark.skipif(not _AIP_AVAILABLE, reason="aip_v3 unavailable")
_SKIP_MODULE = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="android_participant_truth_ingress unavailable"
)
_SKIP_HANDLER = pytest.mark.skipif(
    not _HANDLER_AVAILABLE, reason="reconciliation_signal handler unavailable"
)
_SKIP_TRACKER = pytest.mark.skipif(
    not _TRACKER_AVAILABLE, reason="delegated_runtime_execution_tracker unavailable"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runtime(
    contract_id: str = "",
    session_id: str = "",
    initial_phase: str = "acknowledged",
) -> Any:
    """Build an isolated DelegatedExecutionTrackingRuntime with one record."""
    if not _TRACKER_AVAILABLE:
        return None, None
    rt = DelegatedExecutionTrackingRuntime()
    cid = contract_id or str(uuid.uuid4())
    sid = session_id or str(uuid.uuid4())
    record = create_execution_tracking_record(
        contract_id=cid,
        session_id=sid,
        device_id="device_test",
        trace_id="trace_test",
        runtime=rt,
    )
    if initial_phase in ("in_progress", "completed", "failed", "timed_out", "cancelled"):
        record = apply_acknowledgment_signal(record, AcknowledgmentSignal.progress, runtime=rt)
        if initial_phase == "completed":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.final_result, runtime=rt)
        elif initial_phase == "failed":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.error, runtime=rt)
        elif initial_phase == "timed_out":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.timeout, runtime=rt)
        elif initial_phase == "cancelled":
            record = apply_acknowledgment_signal(record, AcknowledgmentSignal.cancelled, runtime=rt)
    return rt, record


# ---------------------------------------------------------------------------
# Group A — Protocol enum
# ---------------------------------------------------------------------------


@_SKIP_AIP
class TestGroupA_Protocol:
    def test_a1_reconciliation_signal_in_message_type(self) -> None:
        """RECONCILIATION_SIGNAL must be present in MessageType enum."""
        assert hasattr(MessageType, "RECONCILIATION_SIGNAL")
        assert MessageType.RECONCILIATION_SIGNAL.value == "reconciliation_signal"

    def test_a2_delegated_execution_signal_still_present(self) -> None:
        """DELEGATED_EXECUTION_SIGNAL must still be present (no regression)."""
        assert hasattr(MessageType, "DELEGATED_EXECUTION_SIGNAL")
        assert MessageType.DELEGATED_EXECUTION_SIGNAL.value == "delegated_execution_signal"


# ---------------------------------------------------------------------------
# Group B — TruthKind enum
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupB_TruthKind:
    def test_b1_reconciliation_signal_in_truth_kind(self) -> None:
        """reconciliation_signal must be a valid AndroidParticipantTruthKind."""
        assert hasattr(AndroidParticipantTruthKind, "reconciliation_signal")
        assert AndroidParticipantTruthKind.reconciliation_signal.value == "reconciliation_signal"

    def test_b2_from_string_reconciliation_signal(self) -> None:
        """from_string must parse 'reconciliation_signal'."""
        kind = AndroidParticipantTruthKind.from_string("reconciliation_signal")
        assert kind == AndroidParticipantTruthKind.reconciliation_signal

    def test_b3_from_string_case_insensitive(self) -> None:
        """from_string must be case-insensitive for reconciliation_signal."""
        result = AndroidParticipantTruthKind.from_string("RECONCILIATION_SIGNAL")
        assert result == AndroidParticipantTruthKind.reconciliation_signal

    def test_b4_all_original_kinds_still_present(self) -> None:
        """All original truth kinds must still be present (no regression)."""
        for name in (
            "session_snapshot", "readiness_assessment", "task_phase",
            "runtime_state", "cancel", "status", "failure", "result", "unknown",
        ):
            assert hasattr(AndroidParticipantTruthKind, name), f"Missing: {name}"


# ---------------------------------------------------------------------------
# Group C — Policy sentinel
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupC_Policy:
    def test_c1_reconciliation_signal_distinct_from_delegated_policy_present(self) -> None:
        """RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY must be present."""
        assert RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY
        assert "reconciliation_signal" in RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY
        assert "delegated" in RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY.lower()

    def test_c2_policy_mentions_terminal_wins(self) -> None:
        """Policy must document that V2 terminal state still wins."""
        assert "terminal" in RECONCILIATION_SIGNAL_DISTINCT_FROM_DELEGATED_POLICY.lower()


# ---------------------------------------------------------------------------
# Group D — Handler: ACK response
# ---------------------------------------------------------------------------


@_SKIP_HANDLER
class TestGroupD_Handler:
    @pytest.mark.asyncio
    async def test_d1_returns_ack_type(self) -> None:
        """handle_reconciliation_signal must return reconciliation_signal_ack type."""
        bridge = MagicMock()
        websocket = MagicMock()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_abc",
            "message_id": str(uuid.uuid4()),
            "payload": {"phase": "running", "contract_id": "c1", "session_id": "s1"},
        }
        response = await handle_reconciliation_signal(bridge, websocket, message)
        assert response["type"] == "reconciliation_signal_ack"
        assert response["device_id"] == "dev_abc"

    @pytest.mark.asyncio
    async def test_d2_returns_ack_with_correlation_id(self) -> None:
        """Response must include correlation_id matching the inbound message_id."""
        bridge = MagicMock()
        websocket = MagicMock()
        mid = str(uuid.uuid4())
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_xyz",
            "message_id": mid,
            "payload": {},
        }
        response = await handle_reconciliation_signal(bridge, websocket, message)
        assert response["correlation_id"] == mid

    @pytest.mark.asyncio
    async def test_d3_handles_missing_message_id(self) -> None:
        """Handler must not crash if message_id is absent."""
        bridge = MagicMock()
        websocket = MagicMock()
        message = {"type": "reconciliation_signal", "device_id": "dev_no_id", "payload": {}}
        response = await handle_reconciliation_signal(bridge, websocket, message)
        assert response["type"] == "reconciliation_signal_ack"

    @pytest.mark.asyncio
    async def test_d4_calls_participant_truth_ingress(self) -> None:
        """Handler must call ingest_android_participant_truth_message."""
        bridge = MagicMock()
        websocket = MagicMock()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_ingest",
            "payload": {"phase": "completed", "contract_id": "cx", "session_id": "sx"},
        }
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = True
        mock_env = MagicMock()
        mock_env.truth_kind = MagicMock()
        mock_env.truth_kind.value = "reconciliation_signal"
        mock_env.contract_id = "cx"
        mock_env.session_id = "sx"
        mock_outcome.envelope = mock_env
        mock_outcome.canonical_update = "test_update"
        mock_outcome.tracking_record_phase = "completed"
        mock_outcome.reject_reason = ""

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._ingest_participant_truth",
            return_value=mock_outcome,
        ) as mock_ingest:
            response = await handle_reconciliation_signal(bridge, websocket, message)
            mock_ingest.assert_called_once_with(message)
        assert response["type"] == "reconciliation_signal_ack"


# ---------------------------------------------------------------------------
# Group E — Bridge registration
# ---------------------------------------------------------------------------


@_SKIP_AIP
class TestGroupE_BridgeRegistration:
    def test_e1_bridge_registers_reconciliation_signal_handler(self) -> None:
        """android_bridge must register a handler for RECONCILIATION_SIGNAL."""
        try:
            from galaxy_gateway.android_bridge import AndroidBridge
        except ImportError:
            pytest.skip("android_bridge unavailable")

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._message_handlers = {}
        bridge._register_default_handlers()
        assert MessageType.RECONCILIATION_SIGNAL in bridge._message_handlers, (
            "RECONCILIATION_SIGNAL handler not registered in AndroidBridge"
        )

    def test_e2_handler_is_not_unregistered_fallback(self) -> None:
        """The RECONCILIATION_SIGNAL handler must not be the generic unregistered handler."""
        try:
            from galaxy_gateway.android_bridge import AndroidBridge
            from galaxy_gateway.android.handlers.registration import handle_unregistered
        except ImportError:
            pytest.skip("android_bridge or registration unavailable")

        bridge = AndroidBridge.__new__(AndroidBridge)
        bridge._message_handlers = {}
        bridge._register_default_handlers()

        handler = bridge._message_handlers.get(MessageType.RECONCILIATION_SIGNAL)
        assert handler is not None
        # The wrapped handler's __closure__ should not reference handle_unregistered directly
        # (we check it is a distinct callable — not the raw unregistered function)
        assert handler is not handle_unregistered


# ---------------------------------------------------------------------------
# Group F — Ingress: phase-based truth reconciliation
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@_SKIP_TRACKER
class TestGroupF_IngressPhaseBased:
    def test_f1_reconciliation_signal_running_advances_record(self) -> None:
        """reconciliation_signal with phase=running must apply progress signal."""
        cid, sid = "cid-rf1", "sid-rf1"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_f1",
            task_phase_value="running",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled
        assert "reconciliation_signal_applied" in outcome.canonical_update

    def test_f2_reconciliation_signal_completed_advances_record(self) -> None:
        """reconciliation_signal with phase=completed must apply final_result signal."""
        cid, sid = "cid-rf2", "sid-rf2"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_f2",
            task_phase_value="completed",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled
        assert outcome.tracking_record_phase != ""

    def test_f3_reconciliation_signal_failed_advances_record(self) -> None:
        """reconciliation_signal with phase=failed must apply error signal."""
        cid, sid = "cid-rf3", "sid-rf3"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_f3",
            task_phase_value="failed",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled

    def test_f4_reconciliation_signal_cancelled_advances_record(self) -> None:
        """reconciliation_signal with phase=cancelled must apply cancelled signal."""
        cid, sid = "cid-rf4", "sid-rf4"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_f4",
            task_phase_value="cancelled",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled


# ---------------------------------------------------------------------------
# Group G — Ingress: result_success inference
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@_SKIP_TRACKER
class TestGroupG_ResultSuccessInference:
    def test_g1_result_success_true_without_phase(self) -> None:
        """reconciliation_signal with result_success=True must apply final_result."""
        cid, sid = "cid-rg1", "sid-rg1"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_g1",
            task_phase_value="",
            result_success=True,
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled

    def test_g2_result_success_false_without_phase(self) -> None:
        """reconciliation_signal with result_success=False must apply error signal."""
        cid, sid = "cid-rg2", "sid-rg2"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_g2",
            task_phase_value="",
            result_success=False,
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert outcome.was_reconciled


# ---------------------------------------------------------------------------
# Group H — Ingress: terminal V2 state wins
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@_SKIP_TRACKER
class TestGroupH_TerminalV2StateWins:
    def test_h1_reconciliation_signal_rejected_when_record_already_completed(self) -> None:
        """reconciliation_signal must be rejected when V2 record is already completed."""
        cid, sid = "cid-rh1", "sid-rh1"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid, initial_phase="completed")

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_h1",
            task_phase_value="running",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert not outcome.was_reconciled
        assert "v2_terminal_state_wins" in outcome.reject_reason

    def test_h2_reconciliation_signal_rejected_when_record_already_failed(self) -> None:
        """reconciliation_signal must be rejected when V2 record is already failed."""
        cid, sid = "cid-rh2", "sid-rh2"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid, initial_phase="failed")

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id=cid,
            session_id=sid,
            device_id="dev_h2",
            task_phase_value="completed",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert not outcome.was_reconciled
        assert "v2_terminal_state_wins" in outcome.reject_reason


# ---------------------------------------------------------------------------
# Group I — Ingress: missing lookup key
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupI_MissingLookupKey:
    def test_i1_missing_lookup_key_returns_not_reconciled(self) -> None:
        """reconciliation_signal without contract_id or session_id returns was_reconciled=False."""
        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id="",
            session_id="",
            device_id="dev_i1",
            task_phase_value="running",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=None)
        assert not outcome.was_reconciled
        assert outcome.reject_reason


# ---------------------------------------------------------------------------
# Group J — Ingress: no matching tracking record
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@_SKIP_TRACKER
class TestGroupJ_NoMatchingRecord:
    def test_j1_no_matching_record_returns_not_reconciled(self) -> None:
        """reconciliation_signal with unknown contract_id returns was_reconciled=False."""
        rt = DelegatedExecutionTrackingRuntime()  # empty runtime

        envelope = AndroidParticipantTruthEnvelope(
            truth_kind=AndroidParticipantTruthKind.reconciliation_signal,
            contract_id="nonexistent_contract_" + str(uuid.uuid4()),
            session_id="nonexistent_session_" + str(uuid.uuid4()),
            device_id="dev_j1",
            task_phase_value="running",
        )
        outcome = reconcile_android_participant_truth(envelope, runtime=rt)
        assert not outcome.was_reconciled
        assert "no_matching_tracking_record" in outcome.reject_reason


# ---------------------------------------------------------------------------
# Group K — ingest_android_participant_truth_message end-to-end
# ---------------------------------------------------------------------------


@_SKIP_MODULE
@_SKIP_TRACKER
class TestGroupK_IngestEndToEnd:
    def test_k1_ingest_message_with_reconciliation_signal_type(self) -> None:
        """ingest_android_participant_truth_message must handle reconciliation_signal type."""
        cid, sid = "cid-rk1", "sid-rk1"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_k1",
            "payload": {
                "phase": "running",
                "contract_id": cid,
                "session_id": sid,
            },
        }
        outcome = ingest_android_participant_truth_message(message, runtime=rt)
        assert outcome.was_reconciled

    def test_k2_ingest_message_with_explicit_truth_kind(self) -> None:
        """ingest_android_participant_truth_message must handle truth_kind='reconciliation_signal'."""
        cid, sid = "cid-rk2", "sid-rk2"
        rt, _ = _make_runtime(contract_id=cid, session_id=sid)

        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_k2",
            "payload": {
                "truth_kind": "reconciliation_signal",
                "phase": "completed",
                "contract_id": cid,
                "session_id": sid,
            },
        }
        outcome = ingest_android_participant_truth_message(message, runtime=rt)
        assert outcome.was_reconciled

    def test_k3_ingest_extracts_reconciliation_signal_kind(self) -> None:
        """extract_participant_truth_envelope must extract reconciliation_signal kind."""
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev_k3",
            "payload": {"truth_kind": "reconciliation_signal", "phase": "running"},
        }
        envelope = extract_participant_truth_envelope(message)
        assert envelope.truth_kind == AndroidParticipantTruthKind.reconciliation_signal


# ---------------------------------------------------------------------------
# Group L — affects_canonical_state / is_terminal_signal guards
# ---------------------------------------------------------------------------


@_SKIP_MODULE
class TestGroupL_TruthKindGuards:
    def test_l1_reconciliation_signal_affects_canonical_state(self) -> None:
        """reconciliation_signal.affects_canonical_state() must return True."""
        assert AndroidParticipantTruthKind.reconciliation_signal.affects_canonical_state()

    def test_l2_reconciliation_signal_is_terminal_signal(self) -> None:
        """reconciliation_signal.is_terminal_signal() must return True."""
        assert AndroidParticipantTruthKind.reconciliation_signal.is_terminal_signal()

    def test_l3_original_kinds_is_terminal_unchanged(self) -> None:
        """Original is_terminal_signal values must be unchanged."""
        assert AndroidParticipantTruthKind.cancel.is_terminal_signal()
        assert AndroidParticipantTruthKind.failure.is_terminal_signal()
        assert AndroidParticipantTruthKind.result.is_terminal_signal()
        assert not AndroidParticipantTruthKind.status.is_terminal_signal()
        assert not AndroidParticipantTruthKind.session_snapshot.is_terminal_signal()

    def test_l4_original_affects_canonical_state_unchanged(self) -> None:
        """Original affects_canonical_state values must be unchanged."""
        assert AndroidParticipantTruthKind.cancel.affects_canonical_state()
        assert AndroidParticipantTruthKind.status.affects_canonical_state()
        assert not AndroidParticipantTruthKind.readiness_assessment.affects_canonical_state()
        assert not AndroidParticipantTruthKind.runtime_state.affects_canonical_state()
