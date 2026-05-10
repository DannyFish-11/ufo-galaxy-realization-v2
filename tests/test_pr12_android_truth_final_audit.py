"""tests/test_pr12_android_truth_final_audit.py
===============================================
PR-12 — Android-Truth Hardening Series: Final Audit & Polish.

Purpose
-------
This suite is the long-term stability anchor for the Android-truth hardening
initiative.  It does not test individual features (those are covered by the
per-PR suites listed in docs/V2_ANDROID_TRUTH_CONTRACT.md).  Instead it
verifies the cross-cutting properties that must remain true across the whole
series so that future maintainers have a single, cheap canary to detect
contract drift:

1. All authority sentinels from every hardening PR can be imported and are
   non-empty strings.
2. All contract version strings are present, non-empty, and stable.
3. All policy constants follow the ``POLICY::`` naming convention that the
   series established.
4. The complete set of eight proof-input classes is recognised by the
   integration pipeline (``complete`` passes; the other seven are
   non-passing).
5. The ``decision_causality`` dict produced by ``build_unified_governance_state``
   contains all Android-truth fields introduced by the series.

All tests are self-contained: no live servers, no real devices, no network.

Coverage groups
---------------
A. Sentinel accessibility — all series sentinels are importable and
   well-formed strings.
B. Contract version stability — all series contract versions are present
   non-empty strings.
C. Policy naming convention — all series policy constants start with
   ``POLICY::``.
D. Proof-input class completeness — every expected class is handled by the
   capability-truth dimension evaluator; only ``complete`` passes.
E. Decision causality field stability — the expected Android-truth fields
   exist in a governance-state causality dict.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Group A — Sentinel accessibility
# ---------------------------------------------------------------------------


class TestGroupA_SentinelAccessibility:
    """A01–A05: All series sentinels can be imported and are well-formed."""

    def test_A01_execution_lifecycle_truth_binding_sentinel(self) -> None:
        """A01: PR-5 lifecycle truth sentinel is present and well-formed."""
        from core.unified_execution_governance import (
            EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL,
        )
        assert isinstance(EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL, str)
        assert len(EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL) > 20
        assert "PR5_V2" in EXECUTION_LIFECYCLE_TRUTH_BINDING_SENTINEL

    def test_A02_android_evidence_integration_sentinel(self) -> None:
        """A02: PR-8 integration pipeline sentinel is present and well-formed."""
        from core.android_evidence_integration_pipeline import (
            ANDROID_EVIDENCE_INTEGRATION_SENTINEL,
        )
        assert isinstance(ANDROID_EVIDENCE_INTEGRATION_SENTINEL, str)
        assert len(ANDROID_EVIDENCE_INTEGRATION_SENTINEL) > 50
        assert "PR8_V2" in ANDROID_EVIDENCE_INTEGRATION_SENTINEL

    def test_A03_closed_loop_governance_consolidation_sentinel(self) -> None:
        """A03: PR-13 closed-loop sentinel is present and well-formed."""
        from core.closed_loop_governance_consolidation import (
            CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
        )
        assert isinstance(CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL, str)
        assert len(CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL) > 50
        assert "PR13_V2" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL

    def test_A04_governance_audit_authority_sentinel(self) -> None:
        """A04: PR-14 audit authority sentinel is present and well-formed."""
        from core.execution_governance_audit_authority import (
            GOVERNANCE_AUDIT_AUTHORITY_SENTINEL,
        )
        assert isinstance(GOVERNANCE_AUDIT_AUTHORITY_SENTINEL, str)
        assert len(GOVERNANCE_AUDIT_AUTHORITY_SENTINEL) > 50
        assert "PR14_V2" in GOVERNANCE_AUDIT_AUTHORITY_SENTINEL

    def test_A05_android_mode_gate_policy_sentinel(self) -> None:
        """A05: PR-7A mode-gate policy sentinel is present and non-empty."""
        from core.android_mode_gate_policy import (
            ANDROID_MODE_GATE_POLICY_PR_SENTINEL,
        )
        assert isinstance(ANDROID_MODE_GATE_POLICY_PR_SENTINEL, str)
        assert len(ANDROID_MODE_GATE_POLICY_PR_SENTINEL) > 0


# ---------------------------------------------------------------------------
# Group B — Contract version stability
# ---------------------------------------------------------------------------


class TestGroupB_ContractVersionStability:
    """B01–B05: All series contract versions are non-empty strings."""

    def test_B01_execution_lifecycle_truth_binding_version(self) -> None:
        """B01: PR-5 contract version is '5.0.0'."""
        from core.unified_execution_governance import (
            EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION,
        )
        assert isinstance(EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION, str)
        assert EXECUTION_LIFECYCLE_TRUTH_BINDING_CONTRACT_VERSION == "5.0.0"

    def test_B02_android_evidence_integration_version(self) -> None:
        """B02: PR-8 contract version is '8.0.0'."""
        from core.android_evidence_integration_pipeline import (
            ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION,
        )
        assert isinstance(ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION, str)
        assert ANDROID_EVIDENCE_INTEGRATION_CONTRACT_VERSION == "8.0.0"

    def test_B03_closed_loop_governance_version(self) -> None:
        """B03: PR-13 contract version is '13.0.0'."""
        from core.closed_loop_governance_consolidation import (
            CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION,
        )
        assert isinstance(CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION, str)
        assert CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION == "13.0.0"

    def test_B04_governance_audit_contract_version(self) -> None:
        """B04: PR-14 contract version is '14.0.0'."""
        from core.execution_governance_audit_authority import (
            GOVERNANCE_AUDIT_CONTRACT_VERSION,
        )
        assert isinstance(GOVERNANCE_AUDIT_CONTRACT_VERSION, str)
        assert GOVERNANCE_AUDIT_CONTRACT_VERSION == "14.0.0"

    def test_B05_unified_governance_semantics_version_is_non_empty(self) -> None:
        """B05: Unified governance semantics contract version is a non-empty string."""
        from core.unified_governance_semantics import (
            UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION,
        )
        assert isinstance(UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION, str)
        assert len(UNIFIED_GOVERNANCE_SEMANTICS_CONTRACT_VERSION) > 0


# ---------------------------------------------------------------------------
# Group C — Policy naming convention
# ---------------------------------------------------------------------------


class TestGroupC_PolicyNamingConvention:
    """C01–C05: All series policy constants start with 'POLICY::'."""

    def test_C01_canonical_proof_input_diagnosis_policy(self) -> None:
        """C01: CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY starts with 'POLICY::'."""
        from core.unified_execution_governance import (
            CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        )
        assert CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY.startswith("POLICY::")

    def test_C01_proof_input_policy_enumerates_all_eight_classes(self) -> None:
        """C01b: CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY names all 8 classes."""
        from core.unified_execution_governance import (
            CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY,
        )
        for cls in ("complete", "stale", "conflicting", "malformed", "unknown",
                    "downgraded", "partial", "missing"):
            assert cls in CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY, (
                f"proof class '{cls}' missing from CANONICAL_PROOF_INPUT_DIAGNOSIS_POLICY"
            )

    def test_C02_android_execution_lifecycle_truth_policy(self) -> None:
        """C02: ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY starts with 'POLICY::'."""
        from core.unified_execution_governance import (
            ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY,
        )
        assert ANDROID_EXECUTION_LIFECYCLE_TRUTH_POLICY.startswith("POLICY::")

    def test_C03_android_capability_truth_absent_degrades_readiness_policy(self) -> None:
        """C03: ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY starts with 'POLICY::'."""
        from core.android_mode_gate_policy import (
            ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY,
        )
        assert ANDROID_CAPABILITY_TRUTH_ABSENT_DEGRADES_READINESS_POLICY.startswith("POLICY::")

    def test_C04_end_to_end_android_evidence_gate_policy(self) -> None:
        """C04: END_TO_END_ANDROID_EVIDENCE_GATE_POLICY starts with 'POLICY::'."""
        from core.android_evidence_integration_pipeline import (
            END_TO_END_ANDROID_EVIDENCE_GATE_POLICY,
        )
        assert END_TO_END_ANDROID_EVIDENCE_GATE_POLICY.startswith("POLICY::")

    def test_C05_optimistic_android_fallback_elimination_policy(self) -> None:
        """C05: OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY starts with 'POLICY::'."""
        from core.android_evidence_integration_pipeline import (
            OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY,
        )
        assert OPTIMISTIC_ANDROID_FALLBACK_ELIMINATION_POLICY.startswith("POLICY::")


# ---------------------------------------------------------------------------
# Group D — Proof-input class completeness
# ---------------------------------------------------------------------------


def _make_runtime_state(**overrides: object) -> dict:
    """Return a minimal Android runtime state dict with optional overrides."""
    base: dict = {
        "android_semantics_contract_state": "complete",
        "android_semantics_contract_complete": True,
        "android_semantics_missing_keys": [],
        "android_semantics_malformed_keys": [],
        "android_semantics_unknown_keys": [],
        "android_semantics_conflicts": [],
        "android_semantics_downgraded_reasons": [],
        "android_semantics_freshness_state": "fresh",
        "android_semantics_freshness_reason": "android_semantics_age_within_threshold",
        "android_runtime_truth_authority": "authoritative",
        "android_runtime_truth_usable": True,
        "android_reported_mode": "cross_device",
        "android_reported_cross_device_eligibility": True,
        "android_reported_goal_execution_eligibility": True,
        "android_reported_local_inference_available": False,
        "android_reported_local_inference_ready": False,
        "android_reported_local_intelligence_status": "unavailable",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("proof_class", [
    "missing",
    "stale",
    "conflicting",
    "malformed",
    "unknown",
    "downgraded",
    "partial",
])
def test_D01_non_complete_proof_class_fails_integration(proof_class: str) -> None:
    """D01: Every non-complete proof class causes integration to deny."""
    from core.android_evidence_integration_pipeline import (
        AndroidEvidenceDimension,
        IntegrationDecision,
        evaluate_android_evidence_integration,
    )

    lifecycle_binding = MagicMock()
    lifecycle_binding.android_lifecycle_truth_quality.value = "android_remote_confirmed"
    lifecycle_binding.android_lifecycle_truth_degraded = False
    lifecycle_binding.android_lifecycle_truth_reason = "confirmed"
    lifecycle_binding.active_execution_count = 1
    lifecycle_binding.android_lifecycle_truth_governance_impact = "none"

    audit_evidence = MagicMock()
    terminal_entry = MagicMock()
    terminal_entry.reached = True
    terminal_entry.stage.value = "terminal"
    audit_evidence.audit_entries = [terminal_entry]

    closed_loop_view = MagicMock()
    closed_loop_view.stage.value = "completion"

    with (
        patch(
            "core.android_evidence_integration_pipeline.classify_canonical_proof_input_diagnosis",
            return_value={
                "proof_input_class": proof_class,
                "proof_input_degradation_causes": [f"simulated_{proof_class}_class"],
                "proof_input_conflicts": [],
            },
        ),
        patch(
            "core.android_evidence_integration_pipeline.get_execution_lifecycle_truth_binding",
            return_value=lifecycle_binding,
        ),
        patch(
            "core.android_evidence_integration_pipeline.build_governance_authority_evidence",
            return_value=audit_evidence,
        ),
        patch(
            "core.android_evidence_integration_pipeline.verify_governance_authority_integrity",
            return_value=[],
        ),
        patch(
            "core.android_evidence_integration_pipeline.query_closed_loop_governance_state",
            return_value=closed_loop_view,
        ),
        patch(
            "core.android_evidence_integration_pipeline.assert_closed_loop_invariants",
            return_value=[],
        ),
    ):
        verdict = evaluate_android_evidence_integration(
            f"dev_D01_{proof_class}", f"exec_D01_{proof_class}"
        )

    assert verdict.integration_decision == IntegrationDecision.deny, (
        f"proof_class={proof_class!r} should produce deny but got {verdict.integration_decision}"
    )
    assert verdict.integration_allowed is False
    capability = next(
        r for r in verdict.dimension_results
        if r.dimension == AndroidEvidenceDimension.capability_truth
    )
    assert capability.passed is False, (
        f"proof_class={proof_class!r}: capability dimension should not pass"
    )


def test_D02_complete_proof_class_passes_capability_dimension() -> None:
    """D02: Only 'complete' allows the capability-truth dimension to pass."""
    from core.android_evidence_integration_pipeline import (
        AndroidEvidenceDimension,
        AndroidEvidenceGrade,
        IntegrationDecision,
        evaluate_android_evidence_integration,
    )

    lifecycle_binding = MagicMock()
    lifecycle_binding.android_lifecycle_truth_quality.value = "android_remote_confirmed"
    lifecycle_binding.android_lifecycle_truth_degraded = False
    lifecycle_binding.android_lifecycle_truth_reason = "confirmed"
    lifecycle_binding.active_execution_count = 1
    lifecycle_binding.android_lifecycle_truth_governance_impact = "none"

    audit_evidence = MagicMock()
    terminal_entry = MagicMock()
    terminal_entry.reached = True
    terminal_entry.stage.value = "terminal"
    audit_evidence.audit_entries = [terminal_entry]

    closed_loop_view = MagicMock()
    closed_loop_view.stage.value = "completion"

    with (
        patch(
            "core.android_evidence_integration_pipeline.classify_canonical_proof_input_diagnosis",
            return_value={
                "proof_input_class": "complete",
                "proof_input_degradation_causes": [],
                "proof_input_conflicts": [],
            },
        ),
        patch(
            "core.android_evidence_integration_pipeline.get_execution_lifecycle_truth_binding",
            return_value=lifecycle_binding,
        ),
        patch(
            "core.android_evidence_integration_pipeline.build_governance_authority_evidence",
            return_value=audit_evidence,
        ),
        patch(
            "core.android_evidence_integration_pipeline.verify_governance_authority_integrity",
            return_value=[],
        ),
        patch(
            "core.android_evidence_integration_pipeline.query_closed_loop_governance_state",
            return_value=closed_loop_view,
        ),
        patch(
            "core.android_evidence_integration_pipeline.assert_closed_loop_invariants",
            return_value=[],
        ),
    ):
        verdict = evaluate_android_evidence_integration("dev_D02_complete", "exec_D02_complete")

    assert verdict.integration_decision == IntegrationDecision.allow
    assert verdict.integration_allowed is True
    capability = next(
        r for r in verdict.dimension_results
        if r.dimension == AndroidEvidenceDimension.capability_truth
    )
    assert capability.passed is True
    assert capability.grade == AndroidEvidenceGrade.strong


# ---------------------------------------------------------------------------
# Group E — Decision causality field stability
# ---------------------------------------------------------------------------


class TestGroupE_DecisionCausalityFieldStability:
    """E01–E03: The expected Android-truth fields exist in decision_causality."""

    def _build_governance_state_with_mocks(self) -> dict:
        """Return a governance state produced with minimal valid mocks."""
        active_sessions = [SimpleNamespace(device_id="dev_audit")]
        mode_state = SimpleNamespace(mode=SimpleNamespace(value="cross_device"))
        readiness = SimpleNamespace(
            is_dispatch_eligible=True,
            is_takeover_eligible=True,
            is_cross_device_ready=True,
        )
        runtime_snapshot = {
            "devices": [
                {
                    "device_id": "dev_audit",
                    "active_execution_count": 0,
                    "highest_priority_execution_type": None,
                    "blocked_execution_types": [],
                    "offline_queue_depth": 0,
                    "execution_busy": False,
                    "local_inference_available": False,
                    "runtime_health_status": "healthy",
                    "current_fallback_tier": None,
                    "android_semantics_governance_readiness_impact": "none",
                    "android_lifecycle_truth_quality": "android_remote_confirmed",
                    "android_lifecycle_truth_reason": "confirmed",
                    "android_lifecycle_truth_degraded": False,
                    "android_lifecycle_truth_governance_impact": "none",
                }
            ],
            "active_device_count": 0,
            "active_execution_total_count": 0,
        }
        integration_summary = {
            "device_id": "dev_audit",
            "execution_id": "exec-audit",
            "integration_decision": "allow",
            "integration_allowed": True,
            "overall_grade": "strong",
            "dimension_results": [],
            "degradation_causes": [],
        }

        from core.unified_governance_semantics import build_unified_governance_state

        with (
            patch("core.attached_runtime_session_registry.list_active_sessions",
                  MagicMock(return_value=active_sessions)),
            patch("core.android_mode_gate_policy.build_mode_state_for_device",
                  MagicMock(return_value=mode_state)),
            patch("core.android_mode_gate_policy.evaluate_android_mode_readiness",
                  MagicMock(return_value=readiness)),
            patch("core.unified_execution_governance.is_takeover_active",
                  MagicMock(return_value=False)),
            patch("core.unified_execution_governance.get_execution_runtime_snapshot",
                  MagicMock(return_value=runtime_snapshot)),
            patch("core.android_evidence_integration_pipeline.get_android_evidence_integration_summary",
                  MagicMock(return_value=integration_summary)),
        ):
            state = build_unified_governance_state()
        return state

    def test_E01_pr7a_fields_in_decision_causality(self) -> None:
        """E01: PR-7A capability truth fields are present in decision_causality."""
        state = self._build_governance_state_with_mocks()
        causality = (
            state["devices"][0]["governance_precedence"]["delegated_execution"]["decision_causality"]
        )
        assert "android_capability_truth_quality" in causality
        assert "android_capability_truth_degraded" in causality

    def test_E02_pr5_fields_in_decision_causality(self) -> None:
        """E02: PR-5 lifecycle truth fields are present in decision_causality."""
        state = self._build_governance_state_with_mocks()
        causality = (
            state["devices"][0]["governance_precedence"]["delegated_execution"]["decision_causality"]
        )
        assert "android_lifecycle_truth_quality" in causality
        assert "android_lifecycle_truth_reason" in causality
        assert "android_lifecycle_truth_degraded" in causality
        assert "android_lifecycle_truth_governance_impact" in causality

    def test_E03_pr8_integration_fields_in_decision_causality(self) -> None:
        """E03: PR-8 integration fields are present in decision_causality."""
        state = self._build_governance_state_with_mocks()
        causality = (
            state["devices"][0]["governance_precedence"]["delegated_execution"]["decision_causality"]
        )
        assert "android_evidence_integration_execution_id" in causality
        assert "android_evidence_integration_decision" in causality
        assert "android_evidence_integration_allowed" in causality
        assert "android_evidence_integration_grade" in causality
        assert "android_evidence_integration_degradation_causes" in causality
