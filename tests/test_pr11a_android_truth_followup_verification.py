"""PR-11A follow-up verification for Android-truth hardening regressions."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.android_evidence_integration_pipeline import (
    AndroidEvidenceDimension,
    AndroidEvidenceGrade,
    IntegrationDecision,
    evaluate_android_evidence_integration,
)
from core.unified_governance_semantics import build_unified_governance_state


def _strong_lifecycle_binding() -> MagicMock:
    binding = MagicMock()
    binding.android_lifecycle_truth_quality.value = "android_remote_confirmed"
    binding.android_lifecycle_truth_degraded = False
    binding.android_lifecycle_truth_reason = "android_confirms_active"
    binding.active_execution_count = 1
    binding.android_lifecycle_truth_governance_impact = "none"
    return binding


def _strong_audit_evidence() -> MagicMock:
    evidence = MagicMock()
    terminal_entry = MagicMock()
    terminal_entry.reached = True
    terminal_entry.stage.value = "terminal"
    evidence.audit_entries = [terminal_entry]
    return evidence


def _strong_closed_loop_view() -> MagicMock:
    view = MagicMock()
    view.stage.value = "completion"
    return view


def test_protocol_only_optimism_never_passes_without_capability_truth() -> None:
    runtime_state = {
        "android_reported_mode": "cross_device",
        "android_reported_mode_state": "ready",
        "android_reported_mode_readiness_state": "ready",
        "android_reported_cross_device_eligibility": True,
        "android_reported_goal_execution_eligibility": True,
        "android_reported_parallel_execution_eligibility": True,
        "android_reported_local_inference_ready": True,
        "android_reported_local_inference_available": True,
        # Intentionally no android_semantics_* contract metadata.
    }

    with (
        patch(
            "core.android_evidence_integration_pipeline.get_execution_lifecycle_truth_binding",
            return_value=_strong_lifecycle_binding(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.build_governance_authority_evidence",
            return_value=_strong_audit_evidence(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.verify_governance_authority_integrity",
            return_value=[],
        ),
        patch(
            "core.android_evidence_integration_pipeline.query_closed_loop_governance_state",
            return_value=_strong_closed_loop_view(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.assert_closed_loop_invariants",
            return_value=[],
        ),
    ):
        verdict = evaluate_android_evidence_integration(
            "dev_protocol_only",
            "exec_protocol_only",
            runtime_state=runtime_state,
        )

    assert verdict.integration_decision == IntegrationDecision.deny
    assert verdict.integration_allowed is False
    capability = next(
        r for r in verdict.dimension_results if r.dimension == AndroidEvidenceDimension.capability_truth
    )
    assert capability.passed is False
    assert capability.grade == AndroidEvidenceGrade.absent
    assert any(c.startswith("capability_truth:") for c in verdict.degradation_causes)


def test_unrecognized_capability_truth_class_is_explicitly_non_passing() -> None:
    with (
        patch(
            "core.android_evidence_integration_pipeline.classify_canonical_proof_input_diagnosis",
            return_value={
                "proof_input_class": "future_contract_variant",
                "proof_input_degradation_causes": [],
                "proof_input_conflicts": [],
            },
        ),
        patch(
            "core.android_evidence_integration_pipeline.get_execution_lifecycle_truth_binding",
            return_value=_strong_lifecycle_binding(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.build_governance_authority_evidence",
            return_value=_strong_audit_evidence(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.verify_governance_authority_integrity",
            return_value=[],
        ),
        patch(
            "core.android_evidence_integration_pipeline.query_closed_loop_governance_state",
            return_value=_strong_closed_loop_view(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.assert_closed_loop_invariants",
            return_value=[],
        ),
    ):
        verdict = evaluate_android_evidence_integration("dev_future_proof", "exec_future_proof")

    capability = next(
        r for r in verdict.dimension_results if r.dimension == AndroidEvidenceDimension.capability_truth
    )
    assert verdict.integration_allowed is False
    assert capability.passed is False
    assert capability.grade == AndroidEvidenceGrade.degraded
    assert "unrecognized_proof_input_class:future_contract_variant" in str(
        capability.detail.get("degradation_causes")
    )


def test_missing_remote_lifecycle_quality_is_non_passing_even_if_flag_is_false() -> None:
    binding = MagicMock()
    binding.android_lifecycle_truth_quality.value = "missing_remote"
    binding.android_lifecycle_truth_degraded = False
    binding.android_lifecycle_truth_reason = "v2_active_no_android_truth"
    binding.active_execution_count = 1
    binding.android_lifecycle_truth_governance_impact = "blocks_execution"

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
            return_value=binding,
        ),
        patch(
            "core.android_evidence_integration_pipeline.build_governance_authority_evidence",
            return_value=_strong_audit_evidence(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.verify_governance_authority_integrity",
            return_value=[],
        ),
        patch(
            "core.android_evidence_integration_pipeline.query_closed_loop_governance_state",
            return_value=_strong_closed_loop_view(),
        ),
        patch(
            "core.android_evidence_integration_pipeline.assert_closed_loop_invariants",
            return_value=[],
        ),
    ):
        verdict = evaluate_android_evidence_integration("dev_missing_remote", "exec_missing_remote")

    lifecycle = next(
        r for r in verdict.dimension_results if r.dimension == AndroidEvidenceDimension.lifecycle_truth
    )
    assert verdict.integration_allowed is False
    assert lifecycle.passed is False
    assert lifecycle.grade == AndroidEvidenceGrade.degraded


def test_unified_governance_state_invalid_integration_shape_fails_closed() -> None:
    active_sessions = [SimpleNamespace(device_id="dev_followup")]
    mode_state = SimpleNamespace(mode=SimpleNamespace(value="cross_device"))
    readiness = SimpleNamespace(
        is_dispatch_eligible=True,
        is_takeover_eligible=True,
        is_cross_device_ready=True,
    )
    runtime_snapshot = {
        "devices": [
            {
                "device_id": "dev_followup",
                "active_execution_count": 0,
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 0,
                "execution_busy": False,
                "local_inference_available": False,
                "runtime_health_status": "healthy",
                "current_fallback_tier": None,
                "android_semantics_governance_readiness_impact": "ambiguous",
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }

    with (
        patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions),
        patch("core.android_mode_gate_policy.build_mode_state_for_device", return_value=mode_state),
        patch("core.android_mode_gate_policy.evaluate_android_mode_readiness", return_value=readiness),
        patch("core.unified_execution_governance.is_takeover_active", return_value=False),
        patch("core.unified_execution_governance.get_execution_runtime_snapshot", return_value=runtime_snapshot),
        patch(
            "core.android_evidence_integration_pipeline.get_android_evidence_integration_summary",
            return_value="invalid-shape",
        ),
    ):
        state = build_unified_governance_state()

    device = state["devices"][0]
    integration = device["android_evidence_integration"]
    assert integration["integration_allowed"] is False
    assert integration["integration_decision"] == "deny"
    assert "android_evidence_integration_summary_invalid_shape" in integration["degradation_causes"]

    causality = device["governance_precedence"]["delegated_execution"]["decision_causality"]
    assert causality["android_evidence_integration_allowed"] is False
    assert causality["android_evidence_integration_decision"] == "deny"
    assert causality["android_semantics_governance_readiness_impact"] == "ambiguous"
