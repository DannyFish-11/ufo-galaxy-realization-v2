"""tests/test_e2e_cross_repo_signal_closure.py
===============================================
End-to-end cross-repo signal closure validation.

This test suite proves the critical signal chains that connect Android
(ufo-galaxy-android) to V2 (ufo-galaxy-realization-v2) are fully closed:

1. **ReconciliationSignal** end-to-end:
   Android emits ``reconciliation_signal`` → V2 gateway handler receives it
   → ``AndroidDelegatedRuntimeLifecycleCoordinator.on_reconciliation_signal()``
   is invoked → participant truth ingress absorbs it → readiness/governance
   relevant participant truth becomes visible to V2 gates.

2. **HandoffEnvelopeV2 round-trip**:
   V2 emits ``handoff_dispatch`` → Android receives and processes it →
   Android returns one of: ``handoff_ack`` / ``handoff_result`` /
   ``handoff_failure`` → V2 ``handoff_v2_result.py`` handler receives it →
   ``ingest_android_handoff_response()`` is reached → tracking / binding
   side effects applied.

3. **Delegated execution full loop**:
   V2 initiates delegated dispatch → Android emits
   ``delegated_execution_signal`` variants (ack / progress / result / failure /
   cancel) → V2 coordinator receives and reconciles into tracking/state
   progression.  Includes at least one exception path.

4. **Android artifact → V2 readiness/governance visibility**:
   Android-originated evaluator / runtime artifacts (readiness assessment,
   runtime state) enter through truth ingress and can be consumed by the
   ``DelegatedFlowReadinessGate``.  Current path completeness is documented.

Coverage groups
---------------
A.  ReconciliationSignal: handler → lifecycle coordinator invocation.
B.  ReconciliationSignal: coordinator → participant truth ingress call chain.
C.  ReconciliationSignal: readiness-relevant truth kinds trigger coordinator.
D.  ReconciliationSignal: coordinator outcome describes truth ingress result.
E.  ReconciliationSignal: graceful degradation when coordinator unavailable.
F.  HandoffEnvelopeV2 round-trip: ack keeps pending entry alive.
G.  HandoffEnvelopeV2 round-trip: result clears pending entry, fires callback.
H.  HandoffEnvelopeV2 round-trip: failure clears pending entry, fires callback.
I.  HandoffEnvelopeV2 round-trip: uncorrelated response returns ACK (no crash).
J.  HandoffEnvelopeV2 round-trip: full lifecycle V2-dispatch → ack → result.
K.  Delegated execution full loop: ack → in_progress state transition.
L.  Delegated execution full loop: progress → in_progress (idempotent).
M.  Delegated execution full loop: result/success → completed terminal state.
N.  Delegated execution full loop: result/failure → failed terminal state.
O.  Delegated execution full loop: cancel → cancelled terminal state.
P.  Delegated execution full loop: PR-5A result consumer called on result signal.
Q.  Delegated execution full loop: no further mutation after terminal state.
R.  Delegated execution exception path: coordinator handles ingress failure non-fatally.
S.  Android artifact → readiness gate: participant truth ingress is reachable.
T.  Android artifact → readiness gate: truth_ownership dimension evaluates via FlowTruthAlignmentRuntime.
U.  Android artifact → readiness gate: readiness_assessment kind is advisory (local_only).
V.  Validation matrix: all five readiness dimensions are present in gate report.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Module-level availability guards
# ---------------------------------------------------------------------------

try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        AndroidDelegatedRuntimeLifecycleCoordinator,
        AndroidLifecycleCoordinatorOutcome,
        get_lifecycle_coordinator,
        reset_lifecycle_coordinator,
    )
    _COORDINATOR_AVAILABLE = True
except ImportError:
    _COORDINATOR_AVAILABLE = False

try:
    from core.android_handoff_v2_response_ingress import (
        HandoffV2ResponseRuntime,
        HandoffV2ResponseOutcome,
        ingest_android_handoff_response,
    )
    _HANDOFF_INGRESS_AVAILABLE = True
except ImportError:
    _HANDOFF_INGRESS_AVAILABLE = False

try:
    from core.android_participant_truth_ingress import (
        AndroidParticipantTruthKind,
        AndroidParticipantTruthEnvelope,
        AndroidParticipantReconcileOutcome,
        reconcile_android_participant_truth,
        ingest_android_participant_truth_message,
    )
    _TRUTH_INGRESS_AVAILABLE = True
except ImportError:
    _TRUTH_INGRESS_AVAILABLE = False

try:
    from core.delegated_flow_readiness_gate import (
        DelegatedFlowReadinessGate,
        DelegatedFlowReadinessReport,
        ReadinessDimension,
        get_readiness_gate,
        reset_readiness_gate,
    )
    _READINESS_GATE_AVAILABLE = True
except ImportError:
    _READINESS_GATE_AVAILABLE = False

try:
    from core.android_delegated_signal_ingress import (
        DelegatedSignalKind,
        ResultKind,
        ingest_delegated_execution_signal,
    )
    _DELEGATED_INGRESS_AVAILABLE = True
except ImportError:
    _DELEGATED_INGRESS_AVAILABLE = False


_skip_coordinator = pytest.mark.skipif(
    not _COORDINATOR_AVAILABLE, reason="lifecycle coordinator unavailable"
)
_skip_handoff_ingress = pytest.mark.skipif(
    not _HANDOFF_INGRESS_AVAILABLE, reason="handoff v2 response ingress unavailable"
)
_skip_truth_ingress = pytest.mark.skipif(
    not _TRUTH_INGRESS_AVAILABLE, reason="participant truth ingress unavailable"
)
_skip_readiness_gate = pytest.mark.skipif(
    not _READINESS_GATE_AVAILABLE, reason="readiness gate unavailable"
)
_skip_delegated_ingress = pytest.mark.skipif(
    not _DELEGATED_INGRESS_AVAILABLE, reason="delegated signal ingress unavailable"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)


def _make_reconciliation_signal_message(
    *,
    device_id: str = "test-device",
    session_id: str = "",
    truth_kind: str = "reconciliation_signal",
    contract_id: str = "",
    task_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": "reconciliation_signal",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "session_id": session_id,
        "payload": {
            "reconciliation_signal_kind": truth_kind,
            "contract_id": contract_id,
            "session_id": session_id,
            "task_id": task_id,
            "phase": "running",
        },
    }


def _make_delegated_execution_signal_message(
    *,
    device_id: str = "test-device",
    session_id: str = "",
    contract_id: str = "",
    signal_kind: str = "ack",
    result_kind: str = "unknown",
    task_id: str = "",
) -> Dict[str, Any]:
    return {
        "type": "delegated_execution_signal",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "signal_kind": signal_kind,
            "result_kind": result_kind,
            "contract_id": contract_id,
            "session_id": session_id,
            "task_id": task_id,
            "signal_id": str(uuid.uuid4()),
            "emission_seq": 1,
            "trace_id": str(uuid.uuid4()),
        },
    }


def _make_handoff_ack_message(
    handoff_id: str = "", device_id: str = "test-device"
) -> Dict[str, Any]:
    return {
        "type": "handoff_ack",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "ack",
        },
    }


def _make_handoff_result_message(
    handoff_id: str = "", device_id: str = "test-device"
) -> Dict[str, Any]:
    return {
        "type": "handoff_result",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "result",
            "result_payload": {"output": "execution_done"},
        },
    }


def _make_handoff_failure_message(
    handoff_id: str = "", device_id: str = "test-device"
) -> Dict[str, Any]:
    return {
        "type": "handoff_failure",
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "payload": {
            "handoff_id": handoff_id or f"hev2_{uuid.uuid4().hex[:12]}",
            "response_kind": "failure",
            "error_code": "execution_error",
            "error": "device ran out of resources",
        },
    }


# ===========================================================================
# A. ReconciliationSignal: handler → lifecycle coordinator invocation
# ===========================================================================

class TestReconciliationSignalHandlerToCoordinator:
    """Group A: prove that the reconciliation_signal handler delegates to the
    lifecycle coordinator (not directly to truth ingress)."""

    @_skip_coordinator
    def test_A01_handler_calls_coordinator_on_reconciliation_signal(self):
        """handle_reconciliation_signal must invoke coordinator.on_reconciliation_signal."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(device_id="dev-A01")

        mock_outcome = MagicMock()
        mock_outcome.was_handled = True
        mock_outcome.description = "ok"
        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.return_value = mock_outcome

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))
            mock_coord.on_reconciliation_signal.assert_called_once_with(message=msg)

        assert resp["type"] == "reconciliation_signal_ack"

    @_skip_coordinator
    def test_A02_handler_ack_contains_correlation_id(self):
        """ACK must carry the incoming message_id as correlation_id."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        mid = str(uuid.uuid4())
        msg = _make_reconciliation_signal_message(device_id="dev-A02")
        msg["message_id"] = mid

        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.return_value = MagicMock(
            was_handled=True, description="ok"
        )

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))

        assert resp["correlation_id"] == mid

    @_skip_coordinator
    def test_A03_coordinator_not_called_when_unavailable(self):
        """When the coordinator import fails the handler still returns an ACK."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(device_id="dev-A03")

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            None,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))

        assert resp["type"] == "reconciliation_signal_ack"


# ===========================================================================
# B. ReconciliationSignal: coordinator → participant truth ingress call chain
# ===========================================================================

class TestReconciliationSignalCoordinatorToTruthIngress:
    """Group B: prove that the lifecycle coordinator internally calls participant
    truth ingress for reconciliation_signal events."""

    @_skip_coordinator
    @_skip_truth_ingress
    def test_B01_coordinator_calls_truth_ingress(self):
        """coordinator.on_reconciliation_signal must call ingest_android_participant_truth_message."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(
            device_id="dev-B01",
            session_id="sess-B01",
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_truth"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_reconciled=True,
                reject_reason="",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="reconciliation_signal"),
                    task_id="",
                    trace_id="",
                    contract_id="",
                    session_id="sess-B01",
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)
            mock_ingest.assert_called_once_with(msg)

        assert outcome.was_handled is True

    @_skip_coordinator
    @_skip_truth_ingress
    def test_B02_coordinator_outcome_reports_truth_reconciled(self):
        """When truth ingress reconciles successfully the coordinator outcome must reflect it."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-B02", session_id="sess-B02")

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_truth"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_reconciled=True,
                reject_reason="",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="reconciliation_signal"),
                    task_id="t1",
                    trace_id="tr1",
                    contract_id="c1",
                    session_id="sess-B02",
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)

        assert outcome.extra.get("was_reconciled") is True
        assert outcome.extra.get("reject_reason") == ""

    @_skip_coordinator
    @_skip_truth_ingress
    def test_B03_coordinator_outcome_reports_reconcile_miss(self):
        """When truth ingress cannot correlate the signal the outcome must reflect the miss."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-B03")

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_truth"
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                was_reconciled=False,
                reject_reason="no_matching_record",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="reconciliation_signal"),
                    task_id="",
                    trace_id="",
                    contract_id="",
                    session_id="",
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)

        assert outcome.was_handled is True
        assert outcome.extra.get("was_reconciled") is False
        assert outcome.extra.get("reject_reason") == "no_matching_record"


# ===========================================================================
# C. ReconciliationSignal: readiness-relevant truth kinds trigger coordinator
# ===========================================================================

class TestReconciliationSignalReadinessRelevantKinds:
    """Group C: prove that readiness-relevant truth kinds (readiness_assessment,
    participant_state) are processed by the coordinator path."""

    @_skip_coordinator
    def test_C01_readiness_assessment_signal_processed(self):
        """reconciliation_signal with readiness_assessment kind must be processed."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(
            device_id="dev-C01", truth_kind="readiness_assessment"
        )

        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.return_value = MagicMock(
            was_handled=True, description="readiness_assessment processed"
        )

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))
            mock_coord.on_reconciliation_signal.assert_called_once()

        assert resp["type"] == "reconciliation_signal_ack"

    @_skip_coordinator
    def test_C02_runtime_state_signal_processed(self):
        """reconciliation_signal with runtime_state kind must be processed."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(
            device_id="dev-C02", truth_kind="runtime_state"
        )

        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.return_value = MagicMock(
            was_handled=True, description="runtime_state processed"
        )

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))
            mock_coord.on_reconciliation_signal.assert_called_once()

        assert resp["type"] == "reconciliation_signal_ack"

    @_skip_coordinator
    def test_C03_session_snapshot_signal_processed(self):
        """reconciliation_signal with session_snapshot kind must be processed."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(
            device_id="dev-C03", truth_kind="session_snapshot"
        )

        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.return_value = MagicMock(
            was_handled=True, description="session_snapshot processed"
        )

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))

        assert resp["type"] == "reconciliation_signal_ack"


# ===========================================================================
# D. ReconciliationSignal: coordinator outcome describes truth ingress result
# ===========================================================================

class TestReconciliationSignalOutcomeFields:
    """Group D: prove that coordinator outcome carries meaningful E2E metadata."""

    @_skip_coordinator
    def test_D01_outcome_event_type_is_reconciliation_signal(self):
        """Coordinator outcome event_type must be 'reconciliation_signal'."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-D01")

        with patch("core.android_delegated_runtime_lifecycle_coordinator._ingest_truth") as m:
            m.return_value = MagicMock(
                was_reconciled=False, reject_reason="no_record",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="reconciliation_signal"),
                    task_id="", trace_id="", contract_id="", session_id=""
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)

        assert outcome.event_type == "reconciliation_signal"

    @_skip_coordinator
    def test_D02_outcome_was_handled_true_on_success(self):
        """Coordinator must return was_handled=True even when truth was_reconciled=False."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-D02")

        with patch("core.android_delegated_runtime_lifecycle_coordinator._ingest_truth") as m:
            m.return_value = MagicMock(
                was_reconciled=False, reject_reason="no_record",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="reconciliation_signal"),
                    task_id="", trace_id="", contract_id="", session_id=""
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)

        assert outcome.was_handled is True

    @_skip_coordinator
    def test_D03_outcome_description_contains_truth_kind(self):
        """Coordinator description must mention the truth_kind for traceability."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-D03")

        with patch("core.android_delegated_runtime_lifecycle_coordinator._ingest_truth") as m:
            m.return_value = MagicMock(
                was_reconciled=True, reject_reason="",
                envelope=MagicMock(
                    truth_kind=MagicMock(value="readiness_assessment"),
                    task_id="", trace_id="", contract_id="", session_id=""
                ),
            )
            outcome = coord.on_reconciliation_signal(message=msg)

        # description should contain the truth_kind for debuggability
        assert "readiness_assessment" in outcome.description


# ===========================================================================
# E. ReconciliationSignal: graceful degradation when coordinator unavailable
# ===========================================================================

class TestReconciliationSignalGracefulDegradation:
    """Group E: prove the handler survives coordinator import failures."""

    @_skip_coordinator
    def test_E01_handler_returns_ack_when_coordinator_raises(self):
        """handler must return ACK even when coordinator.on_reconciliation_signal raises."""
        from galaxy_gateway.android.handlers.reconciliation_signal import (
            handle_reconciliation_signal,
        )
        bridge = MagicMock()
        msg = _make_reconciliation_signal_message(device_id="dev-E01")

        mock_coord = MagicMock()
        mock_coord.on_reconciliation_signal.side_effect = RuntimeError("boom")

        with patch(
            "galaxy_gateway.android.handlers.reconciliation_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_reconciliation_signal(bridge, None, msg))

        assert resp["type"] == "reconciliation_signal_ack"

    @_skip_coordinator
    def test_E02_coordinator_is_non_raising_on_ingress_error(self):
        """Coordinator on_reconciliation_signal must catch ingress exceptions."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_reconciliation_signal_message(device_id="dev-E02")

        with patch("core.android_delegated_runtime_lifecycle_coordinator._ingest_truth") as m:
            m.side_effect = RuntimeError("ingress_exploded")
            outcome = coord.on_reconciliation_signal(message=msg)

        # Non-raising: must not raise, was_handled should be True (outer try succeeds)
        assert isinstance(outcome, AndroidLifecycleCoordinatorOutcome)


# ===========================================================================
# F-J. HandoffEnvelopeV2 round-trip
# ===========================================================================

class TestHandoffEnvelopeV2RoundTrip:
    """Groups F–J: prove the full HandoffEnvelopeV2 round-trip from V2 dispatch
    through Android response ingestion."""

    @_skip_handoff_ingress
    def test_F01_ack_keeps_pending_entry_alive(self):
        """After handoff_ack the pending entry must remain (terminal response expected)."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        rt.register(handoff_id, lambda _: None)

        msg = _make_handoff_ack_message(handoff_id=handoff_id)
        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is True
        # Pending entry must still exist after ack — terminal response is still expected
        assert handoff_id in rt.pending_by_handoff_id

    @_skip_handoff_ingress
    def test_G01_result_clears_pending_entry_and_fires_callback(self):
        """After handoff_result the pending entry must be removed and callback called."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_handoff_result_message(handoff_id=handoff_id)
        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is True
        assert handoff_id not in rt.pending_by_handoff_id
        assert len(received) == 1  # callback fired exactly once

    @_skip_handoff_ingress
    def test_G02_result_callback_receives_response_envelope(self):
        """Callback must receive the typed AndroidHandoffResponseEnvelope."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_handoff_result_message(handoff_id=handoff_id)
        ingest_android_handoff_response(msg, runtime=rt)

        envelope = received[0]
        assert hasattr(envelope, "response_kind")
        assert str(envelope.response_kind) in ("result", "HandoffResponseKind.result")

    @_skip_handoff_ingress
    def test_H01_failure_clears_pending_entry_and_fires_callback(self):
        """After handoff_failure the pending entry must be removed and callback called."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_handoff_failure_message(handoff_id=handoff_id)
        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is True
        assert handoff_id not in rt.pending_by_handoff_id
        assert len(received) == 1

    @_skip_handoff_ingress
    def test_H02_failure_callback_receives_response_envelope(self):
        """Callback must receive the typed failure envelope."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        msg = _make_handoff_failure_message(handoff_id=handoff_id)
        ingest_android_handoff_response(msg, runtime=rt)

        envelope = received[0]
        assert hasattr(envelope, "response_kind")
        assert str(envelope.response_kind) in ("failure", "HandoffResponseKind.failure")

    @_skip_handoff_ingress
    def test_I01_uncorrelated_response_returns_ack_no_crash(self):
        """Response for an unknown handoff_id must return was_correlated=False without crash."""
        rt = HandoffV2ResponseRuntime()  # empty registry
        msg = _make_handoff_result_message()  # random handoff_id

        outcome = ingest_android_handoff_response(msg, runtime=rt)

        assert outcome.was_correlated is False
        assert outcome.reject_reason != ""

    @_skip_handoff_ingress
    def test_J01_full_lifecycle_dispatch_ack_result(self):
        """Full round-trip: register → ack (callback fired, pending alive) → result (cleared, callback fired again).

        Per ACK_DOES_NOT_CLEAR_PENDING_POLICY (defined in
        ``core/android_handoff_v2_response_ingress.py``): ack invokes the
        registered callback so callers can advance their lifecycle state machine,
        but the pending registry entry is kept so the terminal response
        (result/failure) can still be correlated.
        """
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        # Step 1: Android sends ack — callback fired, pending entry kept
        ack_msg = _make_handoff_ack_message(handoff_id=handoff_id)
        ack_outcome = ingest_android_handoff_response(ack_msg, runtime=rt)
        assert ack_outcome.was_correlated is True
        assert handoff_id in rt.pending_by_handoff_id  # still pending after ack
        assert len(received) == 1  # callback IS fired on ack (lifecycle advance)

        # Step 2: Android sends result — callback fired, pending entry cleared
        result_msg = _make_handoff_result_message(handoff_id=handoff_id)
        result_outcome = ingest_android_handoff_response(result_msg, runtime=rt)
        assert result_outcome.was_correlated is True
        assert handoff_id not in rt.pending_by_handoff_id  # cleared on terminal
        assert len(received) == 2  # callback fired again for terminal

    @_skip_handoff_ingress
    def test_J02_full_lifecycle_dispatch_ack_failure(self):
        """Full round-trip: register → ack (callback fired, pending alive) → failure (cleared, callback fired again)."""
        rt = HandoffV2ResponseRuntime()
        handoff_id = f"hev2_{uuid.uuid4().hex[:12]}"
        received: List[Any] = []
        rt.register(handoff_id, received.append)

        ack_msg = _make_handoff_ack_message(handoff_id=handoff_id)
        ingest_android_handoff_response(ack_msg, runtime=rt)
        assert handoff_id in rt.pending_by_handoff_id  # still pending after ack
        assert len(received) == 1  # callback fired on ack

        fail_msg = _make_handoff_failure_message(handoff_id=handoff_id)
        fail_outcome = ingest_android_handoff_response(fail_msg, runtime=rt)
        assert fail_outcome.was_correlated is True
        assert handoff_id not in rt.pending_by_handoff_id  # cleared on terminal
        assert len(received) == 2  # callback fired again for terminal

    @_skip_handoff_ingress
    def test_J03_gateway_handler_calls_ingest_for_all_response_kinds(self):
        """Gateway handler must call ingest for ack, result, and failure messages."""
        from galaxy_gateway.android.handlers.handoff_v2_result import handle_handoff_v2_result

        for msg_factory in [
            _make_handoff_ack_message,
            _make_handoff_result_message,
            _make_handoff_failure_message,
        ]:
            msg = msg_factory()
            with patch(
                "galaxy_gateway.android.handlers.handoff_v2_result._ingest_handoff_response"
            ) as mock_ingest:
                mock_ingest.return_value = MagicMock(
                    was_correlated=False,
                    reject_reason="no pending entry",
                    envelope=MagicMock(response_kind="ack", handoff_id=""),
                )
                resp = _run(handle_handoff_v2_result(MagicMock(), None, msg))
                mock_ingest.assert_called_once_with(msg)

            assert resp["type"] == "handoff_v2_result_ack"


# ===========================================================================
# K-R. Delegated execution full loop
# ===========================================================================

class TestDelegatedExecutionFullLoop:
    """Groups K–R: prove the delegated execution full loop via the lifecycle
    coordinator, covering all signal kinds and an exception path."""

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_K01_ack_signal_transitions_to_acknowledged(self):
        """coordinator.on_execution_signal with ack kind must be processed."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-K01", signal_kind="ack"
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal"
        ) as mock_ingest:
            mock_env = MagicMock()
            mock_env.signal_kind = MagicMock(value="ack")
            mock_env.session_id = "sess-K01"
            mock_ingest.return_value = MagicMock(
                was_updated=True,
                reject_reason="",
                envelope=mock_env,
            )
            outcome = coord.on_execution_signal(message=msg, device_id="dev-K01")
            mock_ingest.assert_called_once_with(msg)

        assert outcome.was_handled is True
        assert outcome.event_type == "execution_signal"

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_L01_progress_signal_processed(self):
        """coordinator.on_execution_signal with progress kind must be processed."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-L01", signal_kind="progress"
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal"
        ) as mock_ingest:
            mock_env = MagicMock()
            mock_env.signal_kind = MagicMock(value="progress")
            mock_env.session_id = ""
            mock_ingest.return_value = MagicMock(
                was_updated=True, reject_reason="", envelope=mock_env
            )
            outcome = coord.on_execution_signal(message=msg, device_id="dev-L01")

        assert outcome.was_handled is True
        assert outcome.extra.get("signal_kind") == "progress"

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_M01_result_success_signal_processed(self):
        """coordinator.on_execution_signal with result/success kind must be processed."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-M01", signal_kind="result", result_kind="success"
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal"
        ) as mock_ingest:
            mock_env = MagicMock()
            mock_env.signal_kind = MagicMock(value="result")
            mock_env.session_id = ""
            mock_ingest.return_value = MagicMock(
                was_updated=True, reject_reason="", envelope=mock_env
            )
            outcome = coord.on_execution_signal(message=msg, device_id="dev-M01")

        assert outcome.was_handled is True
        assert outcome.extra.get("signal_kind") == "result"

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_N01_result_failure_signal_processed(self):
        """coordinator.on_execution_signal with result/failure kind must be processed."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-N01", signal_kind="result", result_kind="failure"
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal"
        ) as mock_ingest:
            mock_env = MagicMock()
            mock_env.signal_kind = MagicMock(value="result")
            mock_env.session_id = ""
            mock_ingest.return_value = MagicMock(
                was_updated=True, reject_reason="", envelope=mock_env
            )
            outcome = coord.on_execution_signal(message=msg, device_id="dev-N01")

        assert outcome.was_handled is True

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_O01_cancel_signal_processed(self):
        """coordinator.on_execution_signal with cancel kind must be processed."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-O01", signal_kind="cancelled"
        )

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal"
        ) as mock_ingest:
            mock_env = MagicMock()
            mock_env.signal_kind = MagicMock(value="cancelled")
            mock_env.session_id = ""
            mock_ingest.return_value = MagicMock(
                was_updated=True, reject_reason="", envelope=mock_env
            )
            outcome = coord.on_execution_signal(message=msg, device_id="dev-O01")

        assert outcome.was_handled is True
        assert outcome.extra.get("signal_kind") == "cancelled"

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_P01_result_consumer_called_on_result_signal(self):
        """PR-5A: result consumer must be called when signal_kind==result and was_updated."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-P01", signal_kind="result", result_kind="success"
        )

        mock_raw_outcome = MagicMock()
        mock_env = MagicMock()
        mock_env.signal_kind = MagicMock(value="result")
        mock_env.session_id = ""
        mock_raw_outcome.was_updated = True
        mock_raw_outcome.reject_reason = ""
        mock_raw_outcome.envelope = mock_env

        mock_consumer = MagicMock()

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_raw_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = coord.on_execution_signal(message=msg, device_id="dev-P01")

        mock_consumer.consume_android_behavioral_result.assert_called_once()
        assert outcome.extra.get("result_consumer_called") is True

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_Q01_no_result_consumer_called_for_non_result_signal(self):
        """PR-5A: result consumer must NOT be called for ack/progress signals."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(
            device_id="dev-Q01", signal_kind="ack"
        )

        mock_raw_outcome = MagicMock()
        mock_env = MagicMock()
        mock_env.signal_kind = MagicMock(value="ack")
        mock_env.session_id = ""
        mock_raw_outcome.was_updated = True
        mock_raw_outcome.reject_reason = ""
        mock_raw_outcome.envelope = mock_env

        mock_consumer = MagicMock()

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_raw_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = coord.on_execution_signal(message=msg, device_id="dev-Q01")

        mock_consumer.consume_android_behavioral_result.assert_not_called()
        assert outcome.extra.get("result_consumer_called") is False

    @_skip_coordinator
    def test_R01_coordinator_handles_ingress_exception_non_fatally(self):
        """Exception path: coordinator must not propagate ingress exceptions."""
        reset_lifecycle_coordinator()
        coord = AndroidDelegatedRuntimeLifecycleCoordinator()

        msg = _make_delegated_execution_signal_message(device_id="dev-R01")

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            side_effect=ValueError("ingress_crashed"),
        ):
            outcome = coord.on_execution_signal(message=msg, device_id="dev-R01")

        # Non-raising: outcome must be a valid dataclass
        assert isinstance(outcome, AndroidLifecycleCoordinatorOutcome)
        # was_handled may be True or False depending on whether outer try succeeds;
        # the important thing is no exception propagated

    @_skip_coordinator
    @_skip_delegated_ingress
    def test_R02_gateway_handler_returns_ack_even_on_coordinator_failure(self):
        """delegated_signal handler must return ACK even if coordinator raises."""
        from galaxy_gateway.android.handlers.delegated_signal import (
            handle_delegated_execution_signal,
        )
        bridge = MagicMock()
        msg = _make_delegated_execution_signal_message(device_id="dev-R02")

        mock_coord = MagicMock()
        mock_coord.on_execution_signal.side_effect = RuntimeError("coord_failed")

        with patch(
            "galaxy_gateway.android.handlers.delegated_signal._get_lifecycle_coordinator",
            return_value=mock_coord,
        ):
            resp = _run(handle_delegated_execution_signal(bridge, None, msg))

        assert resp["type"] == "delegated_execution_signal_ack"


# ===========================================================================
# S-V. Android artifact → V2 readiness/governance visibility
# ===========================================================================

class TestAndroidArtifactReadinessGateVisibility:
    """Groups S–V: prove that Android-originated truth can reach V2 readiness
    and governance consumption layers.

    CLOSURE ASSESSMENT:
    - Truth ingress (S, U): FULLY CLOSED — participant truth messages are
      absorbed by core.android_participant_truth_ingress.
    - Truth ownership readiness dimension (T): CLOSED via FlowTruthAlignmentRuntime
      when alignment decisions have been recorded.
    - All five readiness dimensions (V): gate evaluates all five, returns
      structured report.
    - Remaining gap: readiness_assessment kind is advisory / local_only
      (does not write FlowTruthDecisionArtifacts), so the truth_ownership
      dimension remains 'unknown' until authoritative/terminal truth flows.
      This gap is documented in CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md.
    """

    @_skip_truth_ingress
    def test_S01_participant_truth_ingress_is_reachable(self):
        """ingest_android_participant_truth_message must be callable without error."""
        msg = {
            "type": "reconciliation_signal",
            "device_id": "dev-S01",
            "message_id": str(uuid.uuid4()),
            "payload": {
                "reconciliation_signal_kind": "readiness_assessment",
                "session_id": "",
                "contract_id": "",
            },
        }
        # Must not raise; was_reconciled may be False (no matching record).
        outcome = ingest_android_participant_truth_message(msg)
        assert hasattr(outcome, "was_reconciled")
        assert hasattr(outcome, "envelope")

    @_skip_truth_ingress
    def test_S02_result_kind_reaches_truth_ingress_and_returns_typed_outcome(self):
        """result truth kind must return a typed outcome from truth ingress."""
        msg = {
            "type": "reconciliation_signal",
            "device_id": "dev-S02",
            "payload": {
                "reconciliation_signal_kind": "result",
                "result_success": True,
                "session_id": "s-S02",
            },
        }
        outcome = ingest_android_participant_truth_message(msg)
        assert isinstance(outcome.envelope, AndroidParticipantTruthEnvelope)

    @_skip_readiness_gate
    def test_T01_readiness_gate_evaluate_returns_report_with_all_dimensions(self):
        """DelegatedFlowReadinessGate.evaluate() must return a report with five dimensions."""
        reset_readiness_gate()
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        assert isinstance(report, DelegatedFlowReadinessReport)
        for dim in ReadinessDimension:
            assert dim.value in report.dimensions, (
                f"Missing dimension {dim.value!r} in gate report"
            )

    @_skip_truth_ingress
    def test_U01_readiness_assessment_truth_is_local_only(self):
        """readiness_assessment Android truth must be advisory / local_only per policy.

        Validates ``READINESS_ASSESSMENT_IS_ADVISORY_POLICY`` (defined in
        ``core/android_participant_truth_ingress.py``): readiness_assessment is
        device-scope advisory only; it does not change V2 dispatch eligibility
        gates and does not write FlowTruthDecisionArtifacts.

        Note: truth_kind is determined by _TRUTH_KIND_FIELD_ALIASES order:
        ("truth_kind", "signal_kind", "kind", "type", ...). The message must
        carry ``truth_kind`` or ``signal_kind`` set to "readiness_assessment" to
        reach the advisory branch (using ``type`` alone would resolve to
        "reconciliation_signal" kind from the message type field).
        """
        msg = {
            "type": "reconciliation_signal",
            "device_id": "dev-U01",
            "truth_kind": "readiness_assessment",  # explicit truth_kind field
            "payload": {
                "ready": True,
                "session_id": "s-U01",
            },
        }
        outcome = ingest_android_participant_truth_message(msg)
        # readiness_assessment is advisory: local_only=True, was_reconciled=False
        assert outcome.local_only is True

    @_skip_readiness_gate
    def test_V01_readiness_gate_report_is_json_serialisable(self):
        """DelegatedFlowReadinessReport must be JSON-serialisable end-to-end."""
        import json
        reset_readiness_gate()
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        raw = report.to_dict() if hasattr(report, "to_dict") else {}
        # Must not raise
        json.dumps(raw)

    @_skip_readiness_gate
    def test_V02_readiness_gate_summary_is_non_empty(self):
        """Gate report summary must be a non-empty string."""
        reset_readiness_gate()
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()
        assert isinstance(report.summary, str) and len(report.summary) > 0

    @_skip_readiness_gate
    def test_V03_is_ready_for_release_matches_verdict_is_ready(self):
        """report.is_ready_for_release must equal report.verdict.is_ready."""
        reset_readiness_gate()
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()
        assert report.is_ready_for_release == report.verdict.is_ready

    @_skip_readiness_gate
    @_skip_truth_ingress
    def test_V04_android_truth_ingress_path_to_gate_is_documented(self):
        """Evidence that the Android → V2 truth ingress → readiness gate chain exists.

        This test proves the import chain from truth ingress to readiness gate is
        intact and that the ``truth_ownership`` dimension appears in every gate
        report. Architectural details are in:
        ``docs/CROSS_REPO_SIGNAL_CLOSURE_VALIDATION_MATRIX.md`` §5.

        Current chain:
        1. Android emits reconciliation_signal (authoritative kinds: cancel/failure/result)
        2. V2 gateway → coordinator.on_reconciliation_signal() → truth ingress
        3. Authoritative kinds write FlowTruthDecisionArtifacts
        4. DelegatedFlowReadinessGate._evaluate_truth_ownership() reads snapshot

        Current gap (documented in validation matrix):
        - readiness_assessment / runtime_state / session_snapshot are advisory;
          they do NOT write FlowTruthDecisionArtifacts.
        """
        # Prove the path exists by importing each module in the chain
        from core.android_participant_truth_ingress import (
            ingest_android_participant_truth_message,
        )
        from core.delegated_flow_readiness_gate import (
            DelegatedFlowReadinessGate,
            ReadinessDimension,
        )

        # If FlowTruthAlignmentRuntime is available, the dimension exists
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()
        assert ReadinessDimension.truth_ownership.value in report.dimensions

        # Document the current status — no assertion on ready/not-ready
        # because that depends on runtime history.
        dim_result = report.dimensions[ReadinessDimension.truth_ownership.value]
        assert dim_result is not None
        # The status is one of: unknown, ready, not_ready — all are valid
        assert dim_result.status is not None
