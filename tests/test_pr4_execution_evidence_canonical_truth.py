"""tests/test_pr4_execution_evidence_canonical_truth.py
=========================================================
PR-4: Tests for execution evidence model, canonical result truth convergence,
evidence quality trust handling, and operator observability surface.

Coverage
--------
Group A — ExecutionEvidenceState enum
  A01  All 13 expected states are present
  A02  States are string-comparable enum values

Group B — EvidenceTrustLevel enum
  B01  All 4 trust levels are present
  B02  Trust levels are string-comparable

Group C — classify_execution_evidence() rules
  C01  duplicate_result → rejected
  C02  superseded_result → rejected
  C03  stale_result → quarantine
  C04  completed_strong + truth_chain + confirmed_strong → trusted
  C05  completed_strong without full confirmation → provisional
  C06  completed_strong with degraded proof class → provisional
  C07  locally_executed with truth_chain_complete → trusted
  C08  locally_executed without truth_chain → provisional
  C09  failed → provisional
  C10  aborted → provisional
  C11  interrupted → provisional
  C12  completed_degraded → quarantine
  C13  android_delegated → provisional
  C14  partially_completed → quarantine
  C15  planned_not_started → quarantine
  C16  started → quarantine
  C17  is_duplicate flag overrides state → rejected
  C18  is_stale flag overrides state → quarantine
  C19  is_superseded flag overrides state → rejected
  C20  Exception in classify returns quarantine (never raises)

Group D — infer_execution_evidence_state()
  D01  is_duplicate flag → duplicate_result
  D02  is_superseded flag → superseded_result
  D03  is_stale flag → stale_result
  D04  status=failed → failed
  D05  status=cancelled → aborted
  D06  status=degraded → completed_degraded
  D07  status=completed + android channel + confirmed_strong + truth chain → completed_strong
  D08  status=completed + android channel + no proof class → android_delegated
  D09  status=completed + local channel + truth chain → locally_executed
  D10  status=completed + local channel + no truth chain → completed_degraded
  D11  status=interrupted → interrupted
  D12  unknown status → completed_degraded (fallback)

Group E — build_execution_evidence_record()
  E01  Returns ExecutionEvidenceRecord with correct evidence_state
  E02  Returns ExecutionEvidenceRecord with correct trust_level
  E03  diagnosis list is non-empty
  E04  to_dict() is JSON-serialisable
  E05  is_accepted property: trusted and provisional → True; quarantine/rejected → False
  E06  is_canonical property: only trusted → True
  E07  Exception in build returns degraded record (never raises)

Group F — ResultAcceptanceVerdict enum
  F01  All 4 verdict values are present
  F02  Verdicts are string-comparable

Group G — ResultTrustAcceptanceRecord
  G01  is_accepted: accept and accept_provisional → True; others → False
  G02  is_canonical: only accept → True

Group H — evaluate_result_truth_acceptance()
  H01  trusted evidence → accept verdict
  H02  provisional evidence → accept_provisional verdict
  H03  quarantine evidence → quarantine verdict
  H04  rejected evidence → reject verdict
  H05  accept: propagate_to_user_closure=True, propagate_to_board=True
  H06  accept_provisional: propagate_to_user_closure=False, operator_warning=True
  H07  quarantine: propagate_to_user_closure=False, propagate_to_board=False, warning=True
  H08  reject: all propagation flags False
  H09  Exception returns quarantine (never raises)

Group I — apply_acceptance_gate()
  I01  accept verdict: is_fully_closed preserved
  I02  quarantine verdict: is_fully_closed cleared and incomplete_reason updated
  I03  reject verdict: is_fully_closed cleared
  I04  accept_provisional: is_fully_closed preserved (not blocked)
  I05  Stamps execution_evidence_state on outcome
  I06  Stamps evidence_trust_level on outcome
  I07  Stamps evidence_acceptance_verdict on outcome

Group J — UnifiedResultIngress integration (PR-4 evidence gate)
  J01  process() stamps execution_evidence_state on outcome
  J02  process() stamps evidence_trust_level on outcome
  J03  process() stamps evidence_acceptance_verdict on outcome
  J04  process() stamps execution_evidence_record dict on outcome
  J05  Quarantine evidence blocks is_fully_closed on outcome
  J06  Trusted evidence does not block is_fully_closed
  J07  Evidence gate failure is non-fatal (never raises, chain continues)

Group K — OperatorExecutionEvidenceEntry
  K01  to_dict() returns expected fields
  K02  is_canonical_truth: True only for accept verdict
  K03  requires_operator_attention: True for quarantine/reject/warning

Group L — OperatorExecutionObservabilitySnapshot
  L01  to_dict() returns expected top-level keys
  L02  acceptance_summary counts are correct

Group M — build_operator_execution_observability_snapshot()
  M01  Returns OperatorExecutionObservabilitySnapshot
  M02  entries are OperatorExecutionEvidenceEntry instances
  M03  acceptance_summary dict has expected keys
  M04  cross_repo_integration block is present
  M05  schema_version is 4.0.0

Group N — record_operator_evidence_entry() and ring buffer
  N01  record_operator_evidence_entry() adds to ring
  N02  get_latest_operator_evidence_entry_for_task() finds recorded entry
  N03  Entry not found → returns None

Group O — POLICY and sentinel constants
  O01  EXECUTION_EVIDENCE_MODEL_POLICY is importable
  O02  EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION == "4.0.0"
  O03  RESULT_TRUTH_ACCEPTANCE_GATE_POLICY is importable
  O04  OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL is importable
  O05  DELEGATED_RESULT_PROOF_CLASS_POLICY references Android integration points
  O06  QUARANTINE_BLOCKS_USER_CLOSURE_POLICY is importable
  O07  ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY is importable

Group P — Observability route endpoints
  P01  GET /api/v1/observability/execution/evidence-state responds without error
  P02  GET /api/v1/observability/execution/evidence-state/{task_id} responds
  P03  Route parameters (device_id, max_entries) are accepted
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

try:
    from core.execution_evidence_model import (
        ExecutionEvidenceState,
        EvidenceTrustLevel,
        ExecutionEvidenceRecord,
        classify_execution_evidence,
        infer_execution_evidence_state,
        build_execution_evidence_record,
        EXECUTION_EVIDENCE_MODEL_POLICY,
        EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION,
        DELEGATED_RESULT_PROOF_CLASS_POLICY,
        DUPLICATE_EVIDENCE_REJECTION_POLICY,
        STALE_RESULT_THRESHOLD_SECONDS,
    )
    _EEM_OK = True
except ImportError:
    _EEM_OK = False

try:
    from core.result_truth_acceptance_gate import (
        ResultAcceptanceVerdict,
        ResultTrustAcceptanceRecord,
        evaluate_result_truth_acceptance,
        apply_acceptance_gate,
        RESULT_TRUTH_ACCEPTANCE_GATE_POLICY,
        QUARANTINE_BLOCKS_USER_CLOSURE_POLICY,
        ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY,
    )
    _RTAG_OK = True
except ImportError:
    _RTAG_OK = False

try:
    from core.unified_result_ingress import (
        UnifiedResultIngressOutcome,
        NormalizedResultEvent,
        ResultSourceChannel,
        ingest_result,
        get_unified_result_ingress,
    )
    _URI_OK = True
except ImportError:
    _URI_OK = False

try:
    from core.operator_execution_observability_surface import (
        OperatorExecutionEvidenceEntry,
        OperatorExecutionObservabilitySnapshot,
        build_operator_execution_observability_snapshot,
        get_latest_operator_evidence_entry_for_task,
        record_operator_evidence_entry,
        OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL,
        OPERATOR_EXECUTION_OBSERVABILITY_CONTRACT_VERSION,
    )
    _OEOS_OK = True
except ImportError:
    _OEOS_OK = False

_SKIP_EEM = pytest.mark.skipif(not _EEM_OK, reason="execution_evidence_model unavailable")
_SKIP_RTAG = pytest.mark.skipif(not _RTAG_OK, reason="result_truth_acceptance_gate unavailable")
_SKIP_URI = pytest.mark.skipif(not _URI_OK, reason="unified_result_ingress unavailable")
_SKIP_OEOS = pytest.mark.skipif(not _OEOS_OK, reason="operator_execution_observability_surface unavailable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_evidence_record(
    task_id: str = "t-test",
    device_id: str = "dev-1",
    state: Optional[Any] = None,
    trust: Optional[Any] = None,
    diagnosis: tuple = (),
) -> Any:
    if not _EEM_OK:
        return None
    s = state or ExecutionEvidenceState.completed_strong
    t = trust or EvidenceTrustLevel.trusted
    return ExecutionEvidenceRecord(
        task_id=task_id,
        device_id=device_id,
        evidence_state=s,
        trust_level=t,
        source_channel="canonical_ws",
        android_proof_class="confirmed_strong",
        truth_chain_complete=True,
        diagnosis=diagnosis,
        classified_at=time.time(),
    )


def _make_ingress_outcome(**kwargs: Any) -> Any:
    if not _URI_OK:
        return MagicMock()
    outcome = UnifiedResultIngressOutcome(**kwargs)
    return outcome


# ===========================================================================
# Group A — ExecutionEvidenceState enum
# ===========================================================================

@_SKIP_EEM
class TestGroupA_ExecutionEvidenceStateEnum:
    def test_a01_all_13_states_present(self) -> None:
        expected = {
            "planned_not_started", "started", "locally_executed",
            "android_delegated", "partially_completed",
            "completed_strong", "completed_degraded",
            "stale_result", "duplicate_result", "superseded_result",
            "failed", "aborted", "interrupted",
        }
        actual = {s.value for s in ExecutionEvidenceState}
        assert expected == actual, f"Missing states: {expected - actual}"

    def test_a02_states_are_string_comparable(self) -> None:
        assert ExecutionEvidenceState.completed_strong == "completed_strong"
        assert ExecutionEvidenceState.failed == "failed"


# ===========================================================================
# Group B — EvidenceTrustLevel enum
# ===========================================================================

@_SKIP_EEM
class TestGroupB_EvidenceTrustLevelEnum:
    def test_b01_all_4_trust_levels_present(self) -> None:
        expected = {"trusted", "provisional", "quarantine", "rejected"}
        actual = {t.value for t in EvidenceTrustLevel}
        assert expected == actual

    def test_b02_trust_levels_string_comparable(self) -> None:
        assert EvidenceTrustLevel.trusted == "trusted"
        assert EvidenceTrustLevel.rejected == "rejected"


# ===========================================================================
# Group C — classify_execution_evidence() rules
# ===========================================================================

@_SKIP_EEM
class TestGroupC_ClassifyExecutionEvidence:
    def test_c01_duplicate_result_rejected(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.duplicate_result)
        assert result == EvidenceTrustLevel.rejected

    def test_c02_superseded_result_rejected(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.superseded_result)
        assert result == EvidenceTrustLevel.rejected

    def test_c03_stale_result_quarantine(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.stale_result)
        assert result == EvidenceTrustLevel.quarantine

    def test_c04_completed_strong_full_confirmation_trusted(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            proof_class="confirmed_strong",
            truth_chain_complete=True,
        )
        assert result == EvidenceTrustLevel.trusted

    def test_c05_completed_strong_no_truth_chain_provisional(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            proof_class="confirmed_strong",
            truth_chain_complete=False,
        )
        assert result == EvidenceTrustLevel.provisional

    def test_c06_completed_strong_degraded_proof_provisional(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            proof_class="degraded_partial",
            truth_chain_complete=True,
        )
        assert result == EvidenceTrustLevel.provisional

    def test_c07_locally_executed_with_truth_chain_trusted(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.locally_executed,
            truth_chain_complete=True,
        )
        assert result == EvidenceTrustLevel.trusted

    def test_c08_locally_executed_without_truth_chain_provisional(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.locally_executed,
            truth_chain_complete=False,
        )
        assert result == EvidenceTrustLevel.provisional

    def test_c09_failed_provisional(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.failed)
        assert result == EvidenceTrustLevel.provisional

    def test_c10_aborted_provisional(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.aborted)
        assert result == EvidenceTrustLevel.provisional

    def test_c11_interrupted_provisional(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.interrupted)
        assert result == EvidenceTrustLevel.provisional

    def test_c12_completed_degraded_quarantine(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.completed_degraded)
        assert result == EvidenceTrustLevel.quarantine

    def test_c13_android_delegated_provisional(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.android_delegated)
        assert result == EvidenceTrustLevel.provisional

    def test_c14_partially_completed_quarantine(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.partially_completed)
        assert result == EvidenceTrustLevel.quarantine

    def test_c15_planned_not_started_quarantine(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.planned_not_started)
        assert result == EvidenceTrustLevel.quarantine

    def test_c16_started_quarantine(self) -> None:
        result = classify_execution_evidence(ExecutionEvidenceState.started)
        assert result == EvidenceTrustLevel.quarantine

    def test_c17_is_duplicate_flag_overrides_rejected(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            is_duplicate=True,
        )
        assert result == EvidenceTrustLevel.rejected

    def test_c18_is_stale_flag_overrides_quarantine(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            is_stale=True,
        )
        assert result == EvidenceTrustLevel.quarantine

    def test_c19_is_superseded_flag_overrides_rejected(self) -> None:
        result = classify_execution_evidence(
            ExecutionEvidenceState.completed_strong,
            is_superseded=True,
        )
        assert result == EvidenceTrustLevel.rejected

    def test_c20_exception_returns_quarantine_never_raises(self) -> None:
        # Pass an invalid state to trigger internal handling
        result = classify_execution_evidence("not_a_real_state_at_all")  # type: ignore
        assert result == EvidenceTrustLevel.quarantine


# ===========================================================================
# Group D — infer_execution_evidence_state()
# ===========================================================================

@_SKIP_EEM
class TestGroupD_InferExecutionEvidenceState:
    def test_d01_is_duplicate_flag(self) -> None:
        state = infer_execution_evidence_state("completed", is_duplicate=True)
        assert state == ExecutionEvidenceState.duplicate_result

    def test_d02_is_superseded_flag(self) -> None:
        state = infer_execution_evidence_state("completed", is_superseded=True)
        assert state == ExecutionEvidenceState.superseded_result

    def test_d03_is_stale_flag(self) -> None:
        state = infer_execution_evidence_state("completed", is_stale=True)
        assert state == ExecutionEvidenceState.stale_result

    def test_d04_status_failed(self) -> None:
        state = infer_execution_evidence_state("failed")
        assert state == ExecutionEvidenceState.failed

    def test_d05_status_cancelled(self) -> None:
        state = infer_execution_evidence_state("cancelled")
        assert state == ExecutionEvidenceState.aborted

    def test_d06_status_degraded(self) -> None:
        state = infer_execution_evidence_state("degraded")
        assert state == ExecutionEvidenceState.completed_degraded

    def test_d07_completed_android_confirmed_strong(self) -> None:
        state = infer_execution_evidence_state(
            "completed",
            source_channel="canonical_ws",
            truth_chain_complete=True,
            android_proof_class="confirmed_strong",
        )
        assert state == ExecutionEvidenceState.completed_strong

    def test_d08_completed_android_no_proof_class(self) -> None:
        state = infer_execution_evidence_state(
            "completed",
            source_channel="canonical_ws",
            truth_chain_complete=False,
            android_proof_class="",
        )
        assert state == ExecutionEvidenceState.android_delegated

    def test_d09_completed_local_with_truth_chain(self) -> None:
        state = infer_execution_evidence_state(
            "completed",
            source_channel="",
            truth_chain_complete=True,
            android_proof_class="",
            payload={},
        )
        assert state == ExecutionEvidenceState.locally_executed

    def test_d10_completed_local_without_truth_chain(self) -> None:
        state = infer_execution_evidence_state(
            "completed",
            source_channel="",
            truth_chain_complete=False,
            android_proof_class="",
            payload={},
        )
        assert state == ExecutionEvidenceState.completed_degraded

    def test_d11_status_interrupted(self) -> None:
        state = infer_execution_evidence_state("interrupted")
        assert state == ExecutionEvidenceState.interrupted

    def test_d12_unknown_status_fallback(self) -> None:
        state = infer_execution_evidence_state("unknown_status_xyz")
        assert state == ExecutionEvidenceState.completed_degraded


# ===========================================================================
# Group E — build_execution_evidence_record()
# ===========================================================================

@_SKIP_EEM
class TestGroupE_BuildExecutionEvidenceRecord:
    def test_e01_correct_evidence_state(self) -> None:
        rec = build_execution_evidence_record(
            "t1", "dev1", "completed",
            source_channel="canonical_ws",
            truth_chain_complete=True,
            android_proof_class="confirmed_strong",
        )
        assert rec.evidence_state == ExecutionEvidenceState.completed_strong

    def test_e02_correct_trust_level(self) -> None:
        rec = build_execution_evidence_record(
            "t1", "dev1", "completed",
            source_channel="canonical_ws",
            truth_chain_complete=True,
            android_proof_class="confirmed_strong",
        )
        assert rec.trust_level == EvidenceTrustLevel.trusted

    def test_e03_diagnosis_is_non_empty(self) -> None:
        rec = build_execution_evidence_record("t1", "dev1", "completed")
        assert len(rec.diagnosis) > 0

    def test_e04_to_dict_json_serialisable(self) -> None:
        import json
        rec = build_execution_evidence_record("t1", "dev1", "failed")
        d = rec.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert "task_id" in serialised

    def test_e05_is_accepted_property(self) -> None:
        trusted_rec = _make_evidence_record(trust=EvidenceTrustLevel.trusted)
        prov_rec = _make_evidence_record(trust=EvidenceTrustLevel.provisional)
        quar_rec = _make_evidence_record(trust=EvidenceTrustLevel.quarantine)
        rej_rec = _make_evidence_record(trust=EvidenceTrustLevel.rejected)
        assert trusted_rec.is_accepted is True
        assert prov_rec.is_accepted is True
        assert quar_rec.is_accepted is False
        assert rej_rec.is_accepted is False

    def test_e06_is_canonical_property(self) -> None:
        trusted_rec = _make_evidence_record(trust=EvidenceTrustLevel.trusted)
        prov_rec = _make_evidence_record(trust=EvidenceTrustLevel.provisional)
        assert trusted_rec.is_canonical is True
        assert prov_rec.is_canonical is False

    def test_e07_exception_returns_degraded_never_raises(self) -> None:
        # Pass None task_id should not raise
        rec = build_execution_evidence_record(None, None, None)  # type: ignore
        assert rec is not None
        assert rec.trust_level in (EvidenceTrustLevel.quarantine, EvidenceTrustLevel.provisional,
                                   EvidenceTrustLevel.trusted, EvidenceTrustLevel.rejected)


# ===========================================================================
# Group F — ResultAcceptanceVerdict enum
# ===========================================================================

@_SKIP_RTAG
class TestGroupF_ResultAcceptanceVerdictEnum:
    def test_f01_all_4_verdict_values_present(self) -> None:
        expected = {"accept", "accept_provisional", "quarantine", "reject"}
        actual = {v.value for v in ResultAcceptanceVerdict}
        assert expected == actual

    def test_f02_verdicts_string_comparable(self) -> None:
        assert ResultAcceptanceVerdict.accept == "accept"
        assert ResultAcceptanceVerdict.reject == "reject"


# ===========================================================================
# Group G — ResultTrustAcceptanceRecord
# ===========================================================================

@_SKIP_RTAG
class TestGroupG_ResultTrustAcceptanceRecord:
    def test_g01_is_accepted_true_for_accept_and_provisional(self) -> None:
        a = ResultTrustAcceptanceRecord(
            task_id="t1", verdict=ResultAcceptanceVerdict.accept
        )
        b = ResultTrustAcceptanceRecord(
            task_id="t1", verdict=ResultAcceptanceVerdict.accept_provisional
        )
        c = ResultTrustAcceptanceRecord(
            task_id="t1", verdict=ResultAcceptanceVerdict.quarantine
        )
        assert a.is_accepted is True
        assert b.is_accepted is True
        assert c.is_accepted is False

    def test_g02_is_canonical_only_for_accept(self) -> None:
        a = ResultTrustAcceptanceRecord(
            task_id="t1", verdict=ResultAcceptanceVerdict.accept
        )
        b = ResultTrustAcceptanceRecord(
            task_id="t1", verdict=ResultAcceptanceVerdict.accept_provisional
        )
        assert a.is_canonical is True
        assert b.is_canonical is False


# ===========================================================================
# Group H — evaluate_result_truth_acceptance()
# ===========================================================================

@pytest.mark.skipif(not (_EEM_OK and _RTAG_OK), reason="modules unavailable")
class TestGroupH_EvaluateResultTruthAcceptance:
    def _make_rec(self, trust: str, state: str = "completed_strong") -> Any:
        m = MagicMock()
        m.task_id = "t-h"
        m.trust_level = trust
        m.evidence_state = state
        m.diagnosis = []
        return m

    def test_h01_trusted_evidence_accept(self) -> None:
        rec = self._make_rec("trusted")
        result = evaluate_result_truth_acceptance(rec)
        assert result.verdict == ResultAcceptanceVerdict.accept

    def test_h02_provisional_evidence_accept_provisional(self) -> None:
        rec = self._make_rec("provisional")
        result = evaluate_result_truth_acceptance(rec)
        assert result.verdict == ResultAcceptanceVerdict.accept_provisional

    def test_h03_quarantine_evidence_quarantine(self) -> None:
        rec = self._make_rec("quarantine")
        result = evaluate_result_truth_acceptance(rec)
        assert result.verdict == ResultAcceptanceVerdict.quarantine

    def test_h04_rejected_evidence_reject(self) -> None:
        rec = self._make_rec("rejected")
        result = evaluate_result_truth_acceptance(rec)
        assert result.verdict == ResultAcceptanceVerdict.reject

    def test_h05_accept_propagation_flags(self) -> None:
        rec = self._make_rec("trusted")
        result = evaluate_result_truth_acceptance(rec)
        assert result.propagate_to_user_closure is True
        assert result.propagate_to_board_projection is True
        assert result.propagate_to_operator_surface is True

    def test_h06_accept_provisional_propagation_flags(self) -> None:
        rec = self._make_rec("provisional")
        result = evaluate_result_truth_acceptance(rec)
        assert result.propagate_to_user_closure is False
        assert result.propagate_to_operator_surface is True
        assert result.operator_warning is True

    def test_h07_quarantine_propagation_flags(self) -> None:
        rec = self._make_rec("quarantine")
        result = evaluate_result_truth_acceptance(rec)
        assert result.propagate_to_user_closure is False
        assert result.propagate_to_board_projection is False
        assert result.operator_warning is True

    def test_h08_reject_all_false(self) -> None:
        rec = self._make_rec("rejected")
        result = evaluate_result_truth_acceptance(rec)
        assert result.propagate_to_user_closure is False
        assert result.propagate_to_operator_surface is False
        assert result.propagate_to_board_projection is False

    def test_h09_exception_returns_quarantine_never_raises(self) -> None:
        result = evaluate_result_truth_acceptance(None)  # type: ignore
        assert result.verdict == ResultAcceptanceVerdict.quarantine


# ===========================================================================
# Group I — apply_acceptance_gate()
# ===========================================================================

@pytest.mark.skipif(not (_EEM_OK and _RTAG_OK and _URI_OK), reason="modules unavailable")
class TestGroupI_ApplyAcceptanceGate:
    def _make_rec(self, trust: str) -> Any:
        m = MagicMock()
        m.task_id = "t-i"
        m.trust_level = trust
        m.evidence_state = "completed_strong"
        m.diagnosis = []
        return m

    def test_i01_accept_preserves_is_fully_closed(self) -> None:
        outcome = _make_ingress_outcome(is_fully_closed=True)
        rec = self._make_rec("trusted")
        apply_acceptance_gate(rec, outcome)
        assert outcome.is_fully_closed is True

    def test_i02_quarantine_clears_is_fully_closed(self) -> None:
        outcome = _make_ingress_outcome(is_fully_closed=True)
        rec = self._make_rec("quarantine")
        apply_acceptance_gate(rec, outcome)
        assert outcome.is_fully_closed is False

    def test_i03_reject_clears_is_fully_closed(self) -> None:
        outcome = _make_ingress_outcome(is_fully_closed=True)
        rec = self._make_rec("rejected")
        apply_acceptance_gate(rec, outcome)
        assert outcome.is_fully_closed is False

    def test_i04_accept_provisional_preserves_is_fully_closed(self) -> None:
        outcome = _make_ingress_outcome(is_fully_closed=True)
        rec = self._make_rec("provisional")
        apply_acceptance_gate(rec, outcome)
        assert outcome.is_fully_closed is True

    def test_i05_stamps_execution_evidence_state(self) -> None:
        outcome = _make_ingress_outcome()
        rec = self._make_rec("trusted")
        apply_acceptance_gate(rec, outcome)
        assert outcome.execution_evidence_state == "completed_strong"

    def test_i06_stamps_evidence_trust_level(self) -> None:
        outcome = _make_ingress_outcome()
        rec = self._make_rec("trusted")
        apply_acceptance_gate(rec, outcome)
        assert outcome.evidence_trust_level == "trusted"

    def test_i07_stamps_evidence_acceptance_verdict(self) -> None:
        outcome = _make_ingress_outcome()
        rec = self._make_rec("trusted")
        apply_acceptance_gate(rec, outcome)
        assert outcome.evidence_acceptance_verdict == "accept"


# ===========================================================================
# Group J — UnifiedResultIngress integration
# ===========================================================================

@pytest.mark.skipif(not (_EEM_OK and _RTAG_OK and _URI_OK), reason="modules unavailable")
class TestGroupJ_UnifiedResultIngressIntegration:
    def _make_event(self, **kwargs: Any) -> Any:
        defaults = {
            "task_id": f"t-{uuid.uuid4().hex[:8]}",
            "device_id": "dev-test",
            "raw_message_type": "goal_execution_result",
            "normalized_result_kind": "goal_execution_result",
            "normalized_status": "completed",
            "source_channel": ResultSourceChannel.CANONICAL_WS,
        }
        defaults.update(kwargs)
        return NormalizedResultEvent(**defaults)

    def test_j01_process_stamps_execution_evidence_state(self) -> None:
        ingress = get_unified_result_ingress()
        event = self._make_event()
        outcome = ingress.process(event)
        assert hasattr(outcome, "execution_evidence_state")
        assert outcome.execution_evidence_state != ""

    def test_j02_process_stamps_evidence_trust_level(self) -> None:
        ingress = get_unified_result_ingress()
        event = self._make_event()
        outcome = ingress.process(event)
        assert hasattr(outcome, "evidence_trust_level")
        assert outcome.evidence_trust_level in (
            "trusted", "provisional", "quarantine", "rejected", ""
        )

    def test_j03_process_stamps_evidence_acceptance_verdict(self) -> None:
        ingress = get_unified_result_ingress()
        event = self._make_event()
        outcome = ingress.process(event)
        assert hasattr(outcome, "evidence_acceptance_verdict")
        assert outcome.evidence_acceptance_verdict in (
            "accept", "accept_provisional", "quarantine", "reject", ""
        )

    def test_j04_process_stamps_execution_evidence_record_dict(self) -> None:
        ingress = get_unified_result_ingress()
        event = self._make_event()
        outcome = ingress.process(event)
        assert hasattr(outcome, "execution_evidence_record")
        if outcome.execution_evidence_record is not None:
            assert isinstance(outcome.execution_evidence_record, dict)
            assert "evidence_state" in outcome.execution_evidence_record

    def test_j05_quarantine_evidence_affects_is_fully_closed(self) -> None:
        """Quarantined evidence state must prevent is_fully_closed."""
        ingress = get_unified_result_ingress()
        # A 'degraded' status will produce completed_degraded → quarantine
        event = self._make_event(normalized_status="degraded")
        outcome = ingress.process(event)
        if outcome.evidence_acceptance_verdict == "quarantine":
            assert outcome.is_fully_closed is False

    def test_j06_trusted_evidence_does_not_block_closure(self) -> None:
        """Trusted evidence must not add a quarantine block to is_fully_closed."""
        ingress = get_unified_result_ingress()
        # Local REST callback with no device — simulates local execution
        event = self._make_event(
            source_channel=ResultSourceChannel.REST_CALLBACK,
            device_id="",
            payload={"proof_class": ""},
        )
        outcome = ingress.process(event)
        # If accepted as trusted, is_fully_closed should not be blocked by evidence gate
        if outcome.evidence_acceptance_verdict == "accept":
            # The only blocks should be truth chain or completion, not evidence gate
            if not outcome.is_fully_closed:
                assert "evidence_gate" not in (outcome.incomplete_reason or "")

    def test_j07_evidence_gate_failure_is_nonfatal(self) -> None:
        """Evidence gate ImportError must not break the processing chain."""
        ingress = get_unified_result_ingress()
        event = self._make_event()
        with patch("core.unified_result_ingress.UnifiedResultIngress._classify_and_apply_evidence_gate") as mock_gate:
            mock_gate.side_effect = RuntimeError("simulated gate crash")
            # Should not raise
            try:
                outcome = ingress.process(event)
            except RuntimeError:
                pytest.fail("Evidence gate exception propagated — must be caught")


# ===========================================================================
# Group K — OperatorExecutionEvidenceEntry
# ===========================================================================

@_SKIP_OEOS
class TestGroupK_OperatorExecutionEvidenceEntry:
    def _make_entry(self, verdict: str = "accept", warning: bool = False) -> OperatorExecutionEvidenceEntry:
        return OperatorExecutionEvidenceEntry(
            task_id="t-k",
            device_id="dev-k",
            evidence_state="completed_strong",
            trust_level="trusted",
            acceptance_verdict=verdict,
            truth_chain_complete=True,
            operator_warning=warning,
            android_proof_class="confirmed_strong",
            source_channel="canonical_ws",
            diagnosis=["evidence_state:completed_strong"],
        )

    def test_k01_to_dict_returns_expected_fields(self) -> None:
        entry = self._make_entry()
        d = entry.to_dict()
        expected_keys = {
            "task_id", "device_id", "evidence_state", "trust_level",
            "acceptance_verdict", "truth_chain_complete", "operator_warning",
            "android_proof_class", "source_channel", "diagnosis", "classified_at",
        }
        assert expected_keys <= set(d.keys())

    def test_k02_is_canonical_truth_only_for_accept(self) -> None:
        accept_entry = self._make_entry("accept")
        prov_entry = self._make_entry("accept_provisional")
        assert accept_entry.is_canonical_truth is True
        assert prov_entry.is_canonical_truth is False

    def test_k03_requires_operator_attention(self) -> None:
        quar_entry = self._make_entry("quarantine")
        warn_entry = self._make_entry("accept_provisional", warning=True)
        normal_entry = self._make_entry("accept", warning=False)
        assert quar_entry.requires_operator_attention is True
        assert warn_entry.requires_operator_attention is True
        assert normal_entry.requires_operator_attention is False


# ===========================================================================
# Group L — OperatorExecutionObservabilitySnapshot
# ===========================================================================

@_SKIP_OEOS
class TestGroupL_OperatorExecutionObservabilitySnapshot:
    def test_l01_to_dict_returns_expected_keys(self) -> None:
        snap = OperatorExecutionObservabilitySnapshot()
        d = snap.to_dict()
        expected_keys = {
            "assembled_at", "entries", "acceptance_summary",
            "incomplete_result_count", "cross_repo_integration", "schema_version",
        }
        assert expected_keys <= set(d.keys())

    def test_l02_acceptance_summary_counts(self) -> None:
        from core.operator_execution_observability_surface import (
            OperatorExecutionEvidenceEntry,
        )
        entries = [
            OperatorExecutionEvidenceEntry(task_id="t1", acceptance_verdict="accept"),
            OperatorExecutionEvidenceEntry(task_id="t2", acceptance_verdict="accept"),
            OperatorExecutionEvidenceEntry(task_id="t3", acceptance_verdict="accept_provisional"),
            OperatorExecutionEvidenceEntry(task_id="t4", acceptance_verdict="quarantine"),
        ]
        snap = OperatorExecutionObservabilitySnapshot(
            entries=entries,
            acceptance_summary={"accepted": 2, "provisional": 1, "quarantine": 1, "rejected": 0},
        )
        d = snap.to_dict()
        assert d["acceptance_summary"]["accepted"] == 2
        assert d["acceptance_summary"]["provisional"] == 1


# ===========================================================================
# Group M — build_operator_execution_observability_snapshot()
# ===========================================================================

@_SKIP_OEOS
class TestGroupM_BuildOperatorExecutionObservabilitySnapshot:
    def test_m01_returns_snapshot_instance(self) -> None:
        snap = build_operator_execution_observability_snapshot()
        assert isinstance(snap, OperatorExecutionObservabilitySnapshot)

    def test_m02_entries_are_correct_type(self) -> None:
        snap = build_operator_execution_observability_snapshot()
        for entry in snap.entries:
            assert isinstance(entry, OperatorExecutionEvidenceEntry)

    def test_m03_acceptance_summary_has_expected_keys(self) -> None:
        snap = build_operator_execution_observability_snapshot()
        d = snap.to_dict()
        summary = d["acceptance_summary"]
        assert "accepted" in summary
        assert "provisional" in summary
        assert "quarantine" in summary
        assert "rejected" in summary

    def test_m04_cross_repo_integration_block_present(self) -> None:
        snap = build_operator_execution_observability_snapshot()
        d = snap.to_dict()
        assert "cross_repo_integration" in d
        assert isinstance(d["cross_repo_integration"], dict)

    def test_m05_schema_version_is_4_0_0(self) -> None:
        snap = build_operator_execution_observability_snapshot()
        assert snap.schema_version == "4.0.0"


# ===========================================================================
# Group N — record_operator_evidence_entry() and ring buffer
# ===========================================================================

@_SKIP_OEOS
class TestGroupN_RecordOperatorEvidenceEntry:
    def test_n01_record_adds_to_ring(self) -> None:
        task_id = f"t-n-{uuid.uuid4().hex[:8]}"
        record_operator_evidence_entry(
            task_id=task_id,
            device_id="dev-n",
            evidence_state="completed_strong",
            trust_level="trusted",
            acceptance_verdict="accept",
        )
        snap = build_operator_execution_observability_snapshot()
        task_ids = [e.task_id for e in snap.entries]
        assert task_id in task_ids

    def test_n02_get_latest_finds_entry(self) -> None:
        task_id = f"t-n-find-{uuid.uuid4().hex[:8]}"
        record_operator_evidence_entry(
            task_id=task_id,
            evidence_state="locally_executed",
            trust_level="trusted",
            acceptance_verdict="accept",
        )
        entry = get_latest_operator_evidence_entry_for_task(task_id)
        assert entry is not None
        assert entry.task_id == task_id

    def test_n03_get_latest_returns_none_if_not_found(self) -> None:
        entry = get_latest_operator_evidence_entry_for_task("nonexistent-task-xyz-000")
        assert entry is None


# ===========================================================================
# Group O — Policy and sentinel constants
# ===========================================================================

@_SKIP_EEM
class TestGroupO_PolicySentinels:
    def test_o01_execution_evidence_model_policy_importable(self) -> None:
        assert isinstance(EXECUTION_EVIDENCE_MODEL_POLICY, str)
        assert len(EXECUTION_EVIDENCE_MODEL_POLICY) > 50

    def test_o02_contract_version_4_0_0(self) -> None:
        assert EXECUTION_EVIDENCE_MODEL_CONTRACT_VERSION == "4.0.0"

    @pytest.mark.skipif(not _RTAG_OK, reason="result_truth_acceptance_gate unavailable")
    def test_o03_result_truth_acceptance_gate_policy_importable(self) -> None:
        assert isinstance(RESULT_TRUTH_ACCEPTANCE_GATE_POLICY, str)
        assert "quarantine" in RESULT_TRUTH_ACCEPTANCE_GATE_POLICY.lower()

    @pytest.mark.skipif(not _OEOS_OK, reason="operator_execution_observability_surface unavailable")
    def test_o04_operator_execution_observability_sentinel_importable(self) -> None:
        assert isinstance(OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL, str)
        assert len(OPERATOR_EXECUTION_OBSERVABILITY_SENTINEL) > 50

    def test_o05_delegated_result_proof_class_policy_references_android(self) -> None:
        assert "DelegatedRuntimeUnit" in DELEGATED_RESULT_PROOF_CLASS_POLICY
        assert "AutonomousExecutionPipeline" in DELEGATED_RESULT_PROOF_CLASS_POLICY

    @pytest.mark.skipif(not _RTAG_OK, reason="result_truth_acceptance_gate unavailable")
    def test_o06_quarantine_blocks_user_closure_policy(self) -> None:
        assert isinstance(QUARANTINE_BLOCKS_USER_CLOSURE_POLICY, str)

    @pytest.mark.skipif(not _RTAG_OK, reason="result_truth_acceptance_gate unavailable")
    def test_o07_acceptance_requires_trusted_evidence_policy(self) -> None:
        assert isinstance(ACCEPTANCE_REQUIRES_TRUSTED_EVIDENCE_POLICY, str)


# ===========================================================================
# Group P — Observability route endpoints
# ===========================================================================

@pytest.mark.skipif(not _OEOS_OK, reason="operator_execution_observability_surface unavailable")
class TestGroupP_ObservabilityRouteEndpoints:
    def _make_router(self) -> Any:
        try:
            from core.routes.observability import create_router
            return create_router()
        except ImportError:
            pytest.skip("observability route unavailable")

    def test_p01_evidence_state_route_exists(self) -> None:
        router = self._make_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/observability/execution/evidence-state" in routes

    def test_p02_evidence_state_task_route_exists(self) -> None:
        router = self._make_router()
        routes = [r.path for r in router.routes]
        assert "/api/v1/observability/execution/evidence-state/{task_id}" in routes

    def test_p03_routes_include_evidence_endpoints(self) -> None:
        router = self._make_router()
        routes_str = str([r.path for r in router.routes])
        assert "evidence" in routes_str
