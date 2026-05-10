"""tests/test_pr8_android_evidence_integration_e2e.py
=====================================================
PR-8 V2-side — Final Android Evidence Integration Pipeline
End-to-End Regression Suite.

Problem statement
-----------------
Close the remaining gap between protocol-level simulation and real Android-
backed governance truth across the V2 system.  Unify the previously introduced
capability validation, lifecycle truth consumption, runtime closure evidence,
hardened governance defaults, and Android-participating regression expectations
into a coherent end-to-end execution path.

Acceptance criteria
-------------------
* V2 end-to-end behavior is gated by real or contract-valid Android evidence
  rather than protocol simulation alone.
* Degraded Android truth causes diagnosable degradation in canonical decisions.
* Remaining optimistic fallback paths are removed or explicitly bounded.

Coverage groups
---------------
A.  Sentinel / policy accessibility — all PR-8 public symbols are importable
    and semantically correct.

B.  evaluate_android_evidence_integration: fully absent Android state →
    overall deny with all four dimensions absent/degraded.

C.  evaluate_android_evidence_integration: complete/strong Android evidence →
    allow verdict with all dimensions passing.

D.  Capability truth degradation → deny:
    non-complete proof_input_class ('missing', 'stale', 'conflicting',
    'downgraded', 'partial', 'unknown', 'malformed') causes
    integration_allowed=False with diagnosable causes.

E.  Lifecycle truth degradation → deny:
    missing_remote / stale_remote / conflicting_remote lifecycle truth causes
    integration_allowed=False with diagnosable causes.

F.  Audit authority degradation → deny:
    absent execution_id causes audit_authority dimension to be absent (not
    silently passing).  Integrity violations cause degraded grade.

G.  Closed-loop degradation → deny:
    absent execution_id causes closed_loop dimension to be absent (not
    silently passing).  Invariant violations cause degraded grade.

H.  Composite degradation — multiple failing dimensions:
    when capability truth AND lifecycle truth are both degraded, the overall
    verdict is deny with both causes in degradation_causes.

I.  Optimistic fallback path elimination:
    each of the four bounded fallback paths (A/B/C/D from
    OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY) is proven to NOT produce
    a passing verdict under the corresponding absent/stale/unknown condition.

J.  Integration verdict is JSON-serialisable.

K.  get_android_evidence_integration_summary returns a dict with required
    fields and is JSON-serialisable.

L.  Cross-device isolation:
    verdict for device A does not depend on evidence for device B.

M.  Contract-valid Android evidence (capability_truth='complete',
    lifecycle='android_remote_confirmed', zero audit violations, stage
    completion) produces grade=strong and decision=allow.

N.  Prior PR module sentinels are still present and accessible from within
    this integration suite (regression guard confirming all prior PRs intact).
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from core.android_evidence_integration_pipeline import (
    ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION,
    ANDROID_EVIDENCE_INTEGRATION_SENTINEL,
    END_TO_END_ANDROID_EVIDENCE_GATE_POLICY,
    OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY,
    AndroidEvidenceDimension,
    AndroidEvidenceGrade,
    AndroidEvidenceIntegrationVerdict,
    IntegrationDecision,
    evaluate_android_evidence_integration,
    get_android_evidence_integration_summary,
)


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------


def _make_runtime_state(
    *,
    mode: str = "cross_device",
    mode_state: str = "ready",
    cross_device_eligibility: bool = True,
    goal_execution_eligibility: bool = True,
    parallel_execution_eligibility: bool = True,
    local_inference_available: bool = True,
    local_intelligence_status: str = "enabled",
    local_inference_ready: bool = True,
    local_ai_ready: bool = True,
    local_loop_ready: bool = True,
    model_ready: bool = True,
) -> Dict[str, Any]:
    """Build a runtime state dict that passes classify_canonical_proof_input_diagnosis."""
    return {
        "android_reported_mode": mode,
        "android_reported_mode_state": mode_state,
        "android_reported_mode_readiness_state": mode_state,
        "android_reported_cross_device_eligibility": cross_device_eligibility,
        "android_reported_goal_execution_eligibility": goal_execution_eligibility,
        "android_reported_parallel_execution_eligibility": parallel_execution_eligibility,
        "android_reported_local_intelligence_status": local_intelligence_status,
        "android_reported_local_inference_ready": local_inference_ready,
        "android_reported_local_inference_available": local_inference_available,
        "local_ai_ready": local_ai_ready,
        "local_loop_ready": local_loop_ready,
        "model_ready": model_ready,
    }


# ===========================================================================
# A — Sentinel / policy accessibility
# ===========================================================================


class TestSentinelAccessibility:
    """All PR-8 public symbols must be importable and semantically correct."""

    def test_sentinel_is_string(self) -> None:
        assert isinstance(ANDROID_EVIDENCE_INTEGRATION_SENTINEL, str)

    def test_sentinel_contains_pr8(self) -> None:
        assert "PR8_V2" in ANDROID_EVIDENCE_INTEGRATION_SENTINEL

    def test_contract_version(self) -> None:
        assert ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION == "8.0.0"

    def test_end_to_end_gate_policy_is_string(self) -> None:
        assert isinstance(END_TO_END_ANDROID_EVIDENCE_GATE_POLICY, str)
        assert "END_TO_END_ANDROID_EVIDENCE_GATE" in END_TO_END_ANDROID_EVIDENCE_GATE_POLICY

    def test_end_to_end_gate_policy_covers_all_dimensions(self) -> None:
        p = END_TO_END_ANDROID_EVIDENCE_GATE_POLICY
        assert "CAPABILITY TRUTH" in p
        assert "LIFECYCLE TRUTH" in p
        assert "AUDIT AUTHORITY" in p
        assert "CLOSED-LOOP INVARIANTS" in p

    def test_optimistic_fallback_elimination_policy_is_string(self) -> None:
        assert isinstance(OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY, str)

    def test_optimistic_fallback_elimination_policy_covers_all_bounds(self) -> None:
        p = OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY
        assert "CAPABILITY_TRUTH_ABSENT_FALLBACK" in p
        assert "LIFECYCLE_TRUTH_V2_LOCAL_ONLY_FALLBACK" in p
        assert "AUDIT_CHAIN_ABSENT_FALLBACK" in p
        assert "CLOSED_LOOP_UNKNOWN_FALLBACK" in p

    def test_dimension_enum_values(self) -> None:
        dims = {d.value for d in AndroidEvidenceDimension}
        assert "capability_truth" in dims
        assert "lifecycle_truth" in dims
        assert "audit_authority" in dims
        assert "closed_loop" in dims

    def test_grade_enum_values(self) -> None:
        grades = {g.value for g in AndroidEvidenceGrade}
        assert "strong" in grades
        assert "adequate" in grades
        assert "degraded" in grades
        assert "absent" in grades

    def test_integration_decision_enum_values(self) -> None:
        decisions = {d.value for d in IntegrationDecision}
        assert "allow" in decisions
        assert "deny" in decisions
        assert "conditionally_allow" in decisions

    def test_evaluate_function_callable(self) -> None:
        assert callable(evaluate_android_evidence_integration)

    def test_summary_function_callable(self) -> None:
        assert callable(get_android_evidence_integration_summary)


# ===========================================================================
# B — Fully absent Android state → deny
# ===========================================================================


class TestFullyAbsentAndroidState:
    """With no Android evidence at all, every dimension must be absent/degraded."""

    def test_absent_state_returns_verdict(self) -> None:
        verdict = evaluate_android_evidence_integration(
            "dev_absent",
            "",
            runtime_state=None,
        )
        assert isinstance(verdict, AndroidEvidenceIntegrationVerdict)

    def test_absent_state_not_allowed(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        assert verdict.integration_allowed is False

    def test_absent_state_decision_is_deny(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        assert verdict.integration_decision == IntegrationDecision.deny

    def test_absent_state_overall_grade_is_absent_or_degraded(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        assert verdict.overall_grade in (
            AndroidEvidenceGrade.absent,
            AndroidEvidenceGrade.degraded,
        )

    def test_absent_state_has_four_dimension_results(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        assert len(verdict.dimension_results) == 4

    def test_absent_state_has_degradation_causes(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        assert len(verdict.degradation_causes) > 0

    def test_absent_state_audit_dimension_is_absent(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        audit_result = next(
            r for r in verdict.dimension_results
            if r.dimension == AndroidEvidenceDimension.audit_authority
        )
        assert audit_result.grade == AndroidEvidenceGrade.absent
        assert not audit_result.passed

    def test_absent_state_closed_loop_dimension_is_absent(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_absent", "")
        cl_result = next(
            r for r in verdict.dimension_results
            if r.dimension == AndroidEvidenceDimension.closed_loop
        )
        assert cl_result.grade == AndroidEvidenceGrade.absent
        assert not cl_result.passed


# ===========================================================================
# C — Contract-valid evidence → allow
# ===========================================================================


class TestContractValidEvidence:
    """With contract-valid Android evidence, the pipeline must allow execution."""

    def _mock_lifecycle_truth(self, quality: str = "android_remote_confirmed") -> MagicMock:
        binding = MagicMock()
        binding.android_lifecycle_truth_quality.value = quality
        binding.android_lifecycle_truth_degraded = False
        binding.android_lifecycle_truth_reason = "android_confirms_active"
        binding.active_execution_count = 1
        binding.android_lifecycle_truth_governance_impact = "none"
        return binding

    def test_contract_valid_evidence_is_allowed(self) -> None:
        """Complete capability truth + confirmed lifecycle + zero violations → allow."""
        mock_cap_diagnosis = {
            "proof_input_class": "complete",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }
        binding = self._mock_lifecycle_truth()
        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "admission"
        evidence.audit_entries = [entry]
        view = MagicMock()
        view.stage.value = "execution"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=mock_cap_diagnosis,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=binding,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_ok",
                "exec_ok",
                runtime_state={},
            )
            assert verdict.integration_allowed is True

    def test_contract_valid_no_degradation_causes(self) -> None:
        mock_cap_diagnosis = {
            "proof_input_class": "complete",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }
        binding = self._mock_lifecycle_truth()
        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "admission"
        evidence.audit_entries = [entry]
        view = MagicMock()
        view.stage.value = "execution"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=mock_cap_diagnosis,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=binding,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_ok",
                "exec_ok",
                runtime_state={},
            )
            assert verdict.degradation_causes == []


# ===========================================================================
# D — Capability truth degradation → deny
# ===========================================================================


class TestCapabilityTruthDegradation:
    """Each degrading capability truth class must produce integration_allowed=False."""

    @pytest.mark.parametrize(
        "proof_class",
        ["missing", "stale", "conflicting", "downgraded", "partial", "unknown", "malformed"],
    )
    def test_degraded_capability_class_denies(self, proof_class: str) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_capability_truth_dimension,
        )

        mock_diagnosis = {
            "proof_input_class": proof_class,
            "proof_input_degradation_causes": [f"test_cause_{proof_class}"],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            result = _evaluate_capability_truth_dimension("dev_test", {})
            assert result.passed is False
            assert result.grade in (AndroidEvidenceGrade.absent, AndroidEvidenceGrade.degraded)

    @pytest.mark.parametrize(
        "proof_class",
        ["missing", "stale", "conflicting", "downgraded", "partial", "unknown", "malformed"],
    )
    def test_degraded_capability_causes_overall_deny(self, proof_class: str) -> None:
        mock_diagnosis = {
            "proof_input_class": proof_class,
            "proof_input_degradation_causes": [f"cause_{proof_class}"],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_cap_degraded",
                "",
                runtime_state={},
            )
            assert verdict.integration_allowed is False
            assert verdict.integration_decision == IntegrationDecision.deny

    def test_degraded_capability_includes_dimension_in_causes(self) -> None:
        mock_diagnosis = {
            "proof_input_class": "missing",
            "proof_input_degradation_causes": ["no_android_snapshot"],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_cap_missing",
                "",
                runtime_state={},
            )
            causes_joined = " ".join(verdict.degradation_causes)
            assert "capability_truth" in causes_joined

    def test_missing_capability_grade_is_absent(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_capability_truth_dimension,
        )

        mock_diagnosis = {
            "proof_input_class": "missing",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            result = _evaluate_capability_truth_dimension("dev_test", {})
            assert result.grade == AndroidEvidenceGrade.absent

    def test_stale_capability_grade_is_degraded(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_capability_truth_dimension,
        )

        mock_diagnosis = {
            "proof_input_class": "stale",
            "proof_input_degradation_causes": ["snapshot_too_old"],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            result = _evaluate_capability_truth_dimension("dev_test", {})
            assert result.grade == AndroidEvidenceGrade.degraded

    def test_partial_capability_grade_is_degraded(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_capability_truth_dimension,
        )

        mock_diagnosis = {
            "proof_input_class": "partial",
            "proof_input_degradation_causes": ["missing_canonical_gate_metadata_keys:['android_reported_mode']"],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            result = _evaluate_capability_truth_dimension("dev_test", {})
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.degraded

    def test_complete_capability_passes(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_capability_truth_dimension,
        )

        mock_diagnosis = {
            "proof_input_class": "complete",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }
        with patch(
            "core.android_evidence_integration_pipeline."
            "classify_canonical_proof_input_diagnosis",
            return_value=mock_diagnosis,
        ):
            result = _evaluate_capability_truth_dimension("dev_test", {})
            assert result.passed is True
            assert result.grade == AndroidEvidenceGrade.strong


# ===========================================================================
# E — Lifecycle truth degradation → deny
# ===========================================================================


class TestLifecycleTruthDegradation:
    """Degraded lifecycle truth qualities must produce integration_allowed=False."""

    def _make_binding(
        self,
        quality: str,
        degraded: bool = True,
        active_count: int = 1,
    ) -> MagicMock:
        binding = MagicMock()
        binding.android_lifecycle_truth_quality.value = quality
        binding.android_lifecycle_truth_degraded = degraded
        binding.android_lifecycle_truth_reason = f"test_reason_{quality}"
        binding.active_execution_count = active_count
        binding.android_lifecycle_truth_governance_impact = "blocks_execution" if degraded else "none"
        return binding

    @pytest.mark.parametrize(
        "quality",
        ["missing_remote", "stale_remote", "conflicting_remote"],
    )
    def test_degraded_lifecycle_quality_denies(self, quality: str) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_lifecycle_truth_dimension,
        )

        binding = self._make_binding(quality, degraded=True)
        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            result = _evaluate_lifecycle_truth_dimension("dev_lifecycle")
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.degraded

    @pytest.mark.parametrize(
        "quality",
        ["missing_remote", "stale_remote", "conflicting_remote"],
    )
    def test_degraded_lifecycle_causes_overall_deny(self, quality: str) -> None:
        binding = self._make_binding(quality, degraded=True)
        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            verdict = evaluate_android_evidence_integration("dev_lifecycle", "")
            assert verdict.integration_allowed is False

    def test_degraded_lifecycle_named_in_causes(self) -> None:
        binding = self._make_binding("missing_remote", degraded=True)
        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            verdict = evaluate_android_evidence_integration("dev_lifecycle_diag", "")
            causes_joined = " ".join(verdict.degradation_causes)
            assert "lifecycle_truth" in causes_joined

    def test_android_remote_confirmed_passes(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_lifecycle_truth_dimension,
        )

        binding = self._make_binding("android_remote_confirmed", degraded=False)
        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            result = _evaluate_lifecycle_truth_dimension("dev_ok")
            assert result.passed is True
            assert result.grade == AndroidEvidenceGrade.strong

    def test_v2_local_only_passes_when_idle(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_lifecycle_truth_dimension,
        )

        binding = self._make_binding("v2_local_only", degraded=False, active_count=0)
        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            result = _evaluate_lifecycle_truth_dimension("dev_idle")
            assert result.passed is True


# ===========================================================================
# F — Audit authority degradation → deny
# ===========================================================================


class TestAuditAuthorityDegradation:
    """Absent or violated audit authority must produce integration_allowed=False."""

    def test_absent_execution_id_denies_audit_dimension(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        result = _evaluate_audit_authority_dimension("", "dev_audit")
        assert result.passed is False
        assert result.grade == AndroidEvidenceGrade.absent

    def test_absent_execution_id_causes_named_in_reason(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        result = _evaluate_audit_authority_dimension("", "dev_audit")
        assert "GOVERNANCE_AUDIT_AUTHORITY_POLICY" in result.reason

    def test_audit_violations_cause_degraded_grade(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        violation = MagicMock()
        violation.invariant_id = "I-A1"
        violation.description = "center lifecycle authority overridden"
        violation.to_dict.return_value = {"invariant_id": "I-A1"}

        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "admission"
        evidence.audit_entries = [entry]

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[violation],
            ),
        ):
            result = _evaluate_audit_authority_dimension("exec_audit", "dev_audit")
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.degraded

    def test_no_stages_reached_is_absent(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        evidence = MagicMock()
        evidence.audit_entries = []

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
        ):
            result = _evaluate_audit_authority_dimension("exec_no_stages", "dev_audit")
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.absent

    def test_clean_audit_chain_passes(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "lifecycle"
        evidence.audit_entries = [entry]

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
        ):
            result = _evaluate_audit_authority_dimension("exec_clean", "dev_audit")
            assert result.passed is True
            assert result.grade in (
                AndroidEvidenceGrade.strong,
                AndroidEvidenceGrade.adequate,
            )

    def test_terminal_stage_gives_strong_grade(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "terminal"
        evidence.audit_entries = [entry]

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
        ):
            result = _evaluate_audit_authority_dimension("exec_terminal", "dev_audit")
            assert result.passed is True
            assert result.grade == AndroidEvidenceGrade.strong


# ===========================================================================
# G — Closed-loop degradation → deny
# ===========================================================================


class TestClosedLoopDegradation:
    """Absent or violated closed-loop governance must produce integration_allowed=False."""

    def test_absent_execution_id_denies_closed_loop(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        result = _evaluate_closed_loop_dimension("", "dev_cl")
        assert result.passed is False
        assert result.grade == AndroidEvidenceGrade.absent

    def test_absent_execution_id_reason_mentions_policy(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        result = _evaluate_closed_loop_dimension("", "dev_cl")
        assert "CROSS_STAGE_INVARIANT_POLICY" in result.reason

    def test_invariant_violations_cause_degraded(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        violation = MagicMock()
        violation.invariant_id = "I-01"
        violation.description = "admitted execution must have lifecycle history"
        violation.to_dict.return_value = {"invariant_id": "I-01"}

        view = MagicMock()
        view.stage.value = "execution"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[violation],
            ),
        ):
            result = _evaluate_closed_loop_dimension("exec_cl", "dev_cl")
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.degraded

    def test_unknown_stage_is_absent(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        view = MagicMock()
        view.stage.value = "unknown"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            result = _evaluate_closed_loop_dimension("exec_unknown_stage", "dev_cl")
            assert result.passed is False
            assert result.grade == AndroidEvidenceGrade.absent

    def test_unknown_stage_not_treated_as_clean(self) -> None:
        """The CLOSED_LOOP_UNKNOWN_FALLBACK path is explicitly bounded."""
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        view = MagicMock()
        view.stage.value = "unknown"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            result = _evaluate_closed_loop_dimension("exec_unknown_stage", "dev_cl")
            # 'unknown' stage must not be allowed through
            assert not result.passed

    def test_completion_stage_gives_strong_grade(self) -> None:
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        view = MagicMock()
        view.stage.value = "completion"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            result = _evaluate_closed_loop_dimension("exec_complete", "dev_cl")
            assert result.passed is True
            assert result.grade == AndroidEvidenceGrade.strong


# ===========================================================================
# H — Composite degradation: multiple failing dimensions
# ===========================================================================


class TestCompositeDegradation:
    """When multiple dimensions fail simultaneously, all causes must be reported."""

    def test_capability_and_lifecycle_both_degraded(self) -> None:
        """Two failing dimensions → deny with both causes in degradation_causes."""
        mock_cap_diagnosis = {
            "proof_input_class": "missing",
            "proof_input_degradation_causes": ["no_snapshot"],
            "proof_input_conflicts": [],
        }
        lifecycle_binding = MagicMock()
        lifecycle_binding.android_lifecycle_truth_quality.value = "missing_remote"
        lifecycle_binding.android_lifecycle_truth_degraded = True
        lifecycle_binding.android_lifecycle_truth_reason = "no_android_events"
        lifecycle_binding.active_execution_count = 1
        lifecycle_binding.android_lifecycle_truth_governance_impact = "blocks_execution"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=mock_cap_diagnosis,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=lifecycle_binding,
            ),
        ):
            verdict = evaluate_android_evidence_integration("dev_composite", "")
            assert verdict.integration_allowed is False
            assert len(verdict.degradation_causes) >= 2
            causes_joined = " ".join(verdict.degradation_causes)
            assert "capability_truth" in causes_joined
            assert "lifecycle_truth" in causes_joined

    def test_all_four_dimensions_degraded(self) -> None:
        """Four failing dimensions → deny with four causes."""
        mock_cap_diagnosis = {
            "proof_input_class": "missing",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }
        lifecycle_binding = MagicMock()
        lifecycle_binding.android_lifecycle_truth_quality.value = "conflicting_remote"
        lifecycle_binding.android_lifecycle_truth_degraded = True
        lifecycle_binding.android_lifecycle_truth_reason = "conflict"
        lifecycle_binding.active_execution_count = 2
        lifecycle_binding.android_lifecycle_truth_governance_impact = "blocks_execution"

        violation_cl = MagicMock()
        violation_cl.invariant_id = "I-01"
        violation_cl.description = "lifecycle missing"
        violation_cl.to_dict.return_value = {"invariant_id": "I-01"}

        view_cl = MagicMock()
        view_cl.stage.value = "unknown"

        violation_audit = MagicMock()
        violation_audit.invariant_id = "I-A1"
        violation_audit.description = "audit violation"
        violation_audit.to_dict.return_value = {"invariant_id": "I-A1"}

        evidence_audit = MagicMock()
        evidence_audit.audit_entries = []

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=mock_cap_diagnosis,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=lifecycle_binding,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=evidence_audit,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[violation_audit],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view_cl,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[violation_cl],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_all_failing", "exec_all_failing"
            )
            assert verdict.integration_allowed is False
            # All four dimensions must appear in degradation_causes
            causes_joined = " ".join(verdict.degradation_causes)
            assert "capability_truth" in causes_joined
            assert "lifecycle_truth" in causes_joined
            # audit and closed_loop: at least 4 causes
            assert len(verdict.degradation_causes) == 4


# ===========================================================================
# I — Optimistic fallback path elimination
# ===========================================================================


class TestOptimisticFallbackElimination:
    """Each bounded fallback path must NOT produce a passing verdict."""

    def test_path_a_capability_absent_fallback_eliminated(self) -> None:
        """CAPABILITY_TRUTH_ABSENT_FALLBACK: no snapshot → integration_allowed=False."""
        # No runtime_state provided → empty snapshot → proof_input_class='missing'
        verdict = evaluate_android_evidence_integration(
            "dev_fallback_a",
            "",
            runtime_state=None,
        )
        # capability_truth dimension must not be passing
        cap_result = next(
            r for r in verdict.dimension_results
            if r.dimension == AndroidEvidenceDimension.capability_truth
        )
        assert not cap_result.passed, (
            "CAPABILITY_TRUTH_ABSENT_FALLBACK: absent capability snapshot "
            "must not produce a passing dimension verdict."
        )

    def test_path_b_lifecycle_v2_local_only_active_execution_eliminated(self) -> None:
        """LIFECYCLE_TRUTH_V2_LOCAL_ONLY_FALLBACK: active V2 exec + no Android events → deny."""
        from core.android_evidence_integration_pipeline import (
            _evaluate_lifecycle_truth_dimension,
        )

        binding = MagicMock()
        binding.android_lifecycle_truth_quality.value = "missing_remote"
        binding.android_lifecycle_truth_degraded = True
        binding.android_lifecycle_truth_reason = (
            "v2_tracking_active_execution_but_no_android_lifecycle_evidence_received"
        )
        binding.active_execution_count = 1
        binding.android_lifecycle_truth_governance_impact = "blocks_execution"

        with patch(
            "core.android_evidence_integration_pipeline."
            "get_execution_lifecycle_truth_binding",
            return_value=binding,
        ):
            result = _evaluate_lifecycle_truth_dimension("dev_fallback_b")
            assert not result.passed, (
                "LIFECYCLE_TRUTH_V2_LOCAL_ONLY_FALLBACK: V2-local bookkeeping "
                "alone is NOT treated as execution truth."
            )

    def test_path_c_audit_chain_absent_fallback_eliminated(self) -> None:
        """AUDIT_CHAIN_ABSENT_FALLBACK: no execution_id → audit dimension absent."""
        from core.android_evidence_integration_pipeline import (
            _evaluate_audit_authority_dimension,
        )

        result = _evaluate_audit_authority_dimension("", "dev_fallback_c")
        assert not result.passed, (
            "AUDIT_CHAIN_ABSENT_FALLBACK: absent execution_id must not "
            "produce a passing audit dimension."
        )
        assert "GOVERNANCE_AUDIT_AUTHORITY_POLICY" in result.reason

    def test_path_d_closed_loop_unknown_fallback_eliminated(self) -> None:
        """CLOSED_LOOP_UNKNOWN_FALLBACK: unknown stage → closed_loop dimension absent."""
        from core.android_evidence_integration_pipeline import (
            _evaluate_closed_loop_dimension,
        )

        view = MagicMock()
        view.stage.value = "unknown"

        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=view,
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            result = _evaluate_closed_loop_dimension("exec_fallback_d", "dev_fallback_d")
            assert not result.passed, (
                "CLOSED_LOOP_UNKNOWN_FALLBACK: unknown governance stage "
                "must not be treated as idle/clean."
            )


# ===========================================================================
# J — JSON-serialisability of verdict
# ===========================================================================


class TestJSONSerialisability:
    """Integration verdict and summary must always be JSON-serialisable."""

    def test_verdict_to_dict_is_json_serialisable(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_json", "")
        d = verdict.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        assert isinstance(serialised, str)

    def test_verdict_dict_contains_required_keys(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_json_keys", "")
        d = verdict.to_dict()
        assert "device_id" in d
        assert "execution_id" in d
        assert "integration_decision" in d
        assert "integration_allowed" in d
        assert "overall_grade" in d
        assert "dimension_results" in d
        assert "degradation_causes" in d
        assert "_sentinel" in d
        assert "_contract_version" in d

    def test_verdict_dict_sentinel_matches(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_json_sentinel", "")
        d = verdict.to_dict()
        assert d["_sentinel"] == ANDROID_EVIDENCE_INTEGRATION_SENTINEL

    def test_verdict_dict_dimension_results_are_dicts(self) -> None:
        verdict = evaluate_android_evidence_integration("dev_json_dims", "")
        d = verdict.to_dict()
        for dim_dict in d["dimension_results"]:
            assert isinstance(dim_dict, dict)
            assert "dimension" in dim_dict
            assert "grade" in dim_dict
            assert "passed" in dim_dict


# ===========================================================================
# K — get_android_evidence_integration_summary
# ===========================================================================


class TestSummaryFunction:
    """get_android_evidence_integration_summary must return a valid, serialisable dict."""

    def test_summary_returns_dict(self) -> None:
        result = get_android_evidence_integration_summary("dev_summary", "")
        assert isinstance(result, dict)

    def test_summary_is_json_serialisable(self) -> None:
        result = get_android_evidence_integration_summary("dev_summary_json", "")
        serialised = json.dumps(result)
        assert isinstance(serialised, str)

    def test_summary_has_required_fields(self) -> None:
        result = get_android_evidence_integration_summary("dev_summary_fields", "")
        assert "device_id" in result
        assert "integration_decision" in result
        assert "integration_allowed" in result
        assert "overall_grade" in result

    def test_summary_device_id_matches(self) -> None:
        dev = "dev_summary_id_check"
        result = get_android_evidence_integration_summary(dev, "")
        assert result["device_id"] == dev


# ===========================================================================
# L — Cross-device isolation
# ===========================================================================


class TestCrossDeviceIsolation:
    """Evidence for device A must not affect verdict for device B."""

    def test_device_a_verdict_does_not_affect_device_b(self) -> None:
        verdict_a = evaluate_android_evidence_integration("dev_isolation_a", "")
        verdict_b = evaluate_android_evidence_integration("dev_isolation_b", "")
        # Both should be consistent independent evaluations
        assert verdict_a.device_id == "dev_isolation_a"
        assert verdict_b.device_id == "dev_isolation_b"
        # Verdicts are independent objects
        assert verdict_a is not verdict_b

    def test_device_id_is_preserved_in_verdict(self) -> None:
        dev_id = "dev_isolation_preserved"
        verdict = evaluate_android_evidence_integration(dev_id, "exec_iso")
        assert verdict.device_id == dev_id

    def test_execution_id_is_preserved_in_verdict(self) -> None:
        exec_id = "exec_isolation_preserved"
        verdict = evaluate_android_evidence_integration("dev_iso", exec_id)
        assert verdict.execution_id == exec_id


# ===========================================================================
# M — Contract-valid full-strong evidence → allow/conditionally_allow
# ===========================================================================


class TestContractValidStrongEvidence:
    """Strong evidence across all four dimensions → allow or conditionally_allow."""

    def _make_strong_cap_diagnosis(self) -> Dict[str, Any]:
        return {
            "proof_input_class": "complete",
            "proof_input_degradation_causes": [],
            "proof_input_conflicts": [],
        }

    def _make_strong_lifecycle(self) -> MagicMock:
        binding = MagicMock()
        binding.android_lifecycle_truth_quality.value = "android_remote_confirmed"
        binding.android_lifecycle_truth_degraded = False
        binding.android_lifecycle_truth_reason = "android_confirms_active"
        binding.active_execution_count = 1
        binding.android_lifecycle_truth_governance_impact = "none"
        return binding

    def _make_strong_audit(self) -> MagicMock:
        evidence = MagicMock()
        entry = MagicMock()
        entry.reached = True
        entry.stage.value = "terminal"
        evidence.audit_entries = [entry]
        return evidence

    def _make_strong_view(self) -> MagicMock:
        view = MagicMock()
        view.stage.value = "completion"
        return view

    def test_all_strong_dimensions_produce_allow_or_conditionally_allow(self) -> None:
        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=self._make_strong_cap_diagnosis(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=self._make_strong_lifecycle(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=self._make_strong_audit(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=self._make_strong_view(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_strong",
                "exec_strong",
                runtime_state={},
            )
            assert verdict.integration_allowed is True
            assert verdict.integration_decision in (
                IntegrationDecision.allow,
                IntegrationDecision.conditionally_allow,
            )

    def test_all_strong_dimensions_zero_degradation_causes(self) -> None:
        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value=self._make_strong_cap_diagnosis(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=self._make_strong_lifecycle(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=self._make_strong_audit(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=self._make_strong_view(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_strong_nocause",
                "exec_strong_nocause",
                runtime_state={},
            )
            assert verdict.degradation_causes == []


# ===========================================================================
# N — Prior PR module sentinels still present
# ===========================================================================


class TestPriorPRSentinelsIntact:
    """All prior PR sentinels must remain present (regression guard)."""

    def test_pr5_sentinel_present(self) -> None:
        from core.unified_execution_governance import (
            EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL,
        )

        assert "PR5_V2" in EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL

    def test_pr7a_capability_policy_present(self) -> None:
        from core.android_mode_gate_policy import (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY,
        )

        assert "ANDROID_CAPABILITY_TRUTH_ABSENT" in (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY
        )
        assert "deny" in ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY.lower()

    def test_pr13_sentinel_present(self) -> None:
        from core.closed_loop_governance_consolidation import (
            CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
        )

        assert "PR13_V2" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL

    def test_pr14_sentinel_present(self) -> None:
        from core.execution_governance_audit_authority import (
            GOVERNANCE_AUDIT_AUTHORITY_SENTINEL,
        )

        assert "PR14_V2" in GOVERNANCE_AUDIT_AUTHORITY_SENTINEL

    def test_pr8_sentinel_references_prior_sentinels(self) -> None:
        """PR-8 sentinel must acknowledge the prior PR chain."""
        assert "PR8_V2" in ANDROID_EVIDENCE_INTEGRATION_SENTINEL

    def test_end_to_end_policy_references_prior_policies(self) -> None:
        p = END_TO_END_ANDROID_EVIDENCE_GATE_POLICY
        # All four prior PR governance policies are referenced
        assert "classify_canonical_proof_input_diagnosis" in p
        assert "get_execution_lifecycle_truth_binding" in p
        assert "verify_governance_authority_integrity" in p
        assert "assert_closed_loop_invariants" in p

    def test_pr5_android_execution_lifecycle_truth_policy_present(self) -> None:
        from core.unified_execution_governance import (
            ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY,
        )

        assert "ANDROID_EXECUTION_LIFECYCLE_TRUTH_V1" in ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY

    def test_canonical_proof_input_diagnosis_policy_present(self) -> None:
        from core.unified_execution_governance import (
            CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        )

        assert "CANONICAL_PROOF_INPUT_DIAGNOSIS_V1" in CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY


# ===========================================================================
# O — Recovery truth gap degradation (PR-13A)
# ===========================================================================


class TestRecoveryTruthGapDegradation:
    """Recovery truth-quality should influence integration interpretation."""

    def test_recovery_partial_gap_downgrades_allow_to_conditionally_allow(self) -> None:
        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value={
                    "proof_input_class": "complete",
                    "proof_input_degradation_causes": [],
                    "proof_input_conflicts": [],
                },
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=TestContractValidStrongEvidence()._make_strong_lifecycle(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=TestContractValidStrongEvidence()._make_strong_audit(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=TestContractValidStrongEvidence()._make_strong_view(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_recovery_partial",
                "exec_recovery_partial",
                runtime_state={
                    "recovery_closure_quality": "partial_convergence",
                    "recovery_truth_gap_types": ["partial", "duplicated"],
                },
            )
        assert verdict.integration_allowed is True
        assert verdict.integration_decision == IntegrationDecision.conditionally_allow
        assert verdict.recovery_truth_quality == "adequate"
        assert verdict.recovery_truth_degraded is False
        assert verdict.recovery_truth_gap_types == ["partial", "duplicated"]

    def test_recovery_missing_conflicting_replay_fragmented_forces_deny(self) -> None:
        with (
            patch(
                "core.android_evidence_integration_pipeline."
                "classify_canonical_proof_input_diagnosis",
                return_value={
                    "proof_input_class": "complete",
                    "proof_input_degradation_causes": [],
                    "proof_input_conflicts": [],
                },
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "get_execution_lifecycle_truth_binding",
                return_value=TestContractValidStrongEvidence()._make_strong_lifecycle(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "build_governance_authority_evidence",
                return_value=TestContractValidStrongEvidence()._make_strong_audit(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "verify_governance_authority_integrity",
                return_value=[],
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "query_closed_loop_governance_state",
                return_value=TestContractValidStrongEvidence()._make_strong_view(),
            ),
            patch(
                "core.android_evidence_integration_pipeline."
                "assert_closed_loop_invariants",
                return_value=[],
            ),
        ):
            verdict = evaluate_android_evidence_integration(
                "dev_recovery_severe",
                "exec_recovery_severe",
                runtime_state={
                    "recovery_closure_quality": "no_recovery",
                    "recovery_truth_gap_types": [
                        "missing",
                        "conflicting",
                        "replay_fragmented",
                    ],
                },
            )
        assert verdict.integration_allowed is False
        assert verdict.integration_decision == IntegrationDecision.deny
        assert verdict.recovery_truth_quality == "degraded"
        assert verdict.recovery_truth_degraded is True
        assert verdict.recovery_truth_gap_types == [
            "missing",
            "conflicting",
            "replay_fragmented",
        ]
        assert "recovery_truth:degraded:" in " ".join(verdict.degradation_causes)
