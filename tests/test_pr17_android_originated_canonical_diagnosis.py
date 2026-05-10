"""PR-17 regression: Android-originated diagnostics reconciliation into canonical paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


def _runtime_snapshot_for_pr17(device_id: str) -> dict:
    return {
        "devices": [
            {
                "device_id": device_id,
                "active_execution_count": 0,
                "active_executions": [],
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 1,
                "execution_busy": False,
                "local_inference_available": False,
                "android_semantics_contract_state": "downgraded",
                "android_semantics_contract_complete": False,
                "android_semantics_missing_keys": [],
                "android_semantics_malformed_keys": [],
                "android_semantics_unknown_keys": [],
                "android_semantics_conflicts": [],
                "android_semantics_downgraded_reasons": [
                    "local_intelligence_status_disabled",
                ],
                "android_semantics_freshness_state": "fresh",
                "android_semantics_freshness_reason": "android_semantics_age_within_threshold",
                "android_runtime_truth_authority": "android_reported",
                "android_runtime_truth_usable": True,
                "android_lifecycle_truth_quality": "stale_remote",
                "android_lifecycle_truth_reason": "android_runtime_event_stale",
                "snapshot_reconciliation_reason": "same_sequence_older_timestamp",
                "runtime_health_status": "degraded",
                "current_fallback_tier": "center_delegated",
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }


def test_pr17_policy_and_contract_are_stable() -> None:
    from core.unified_governance_semantics import (
        ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_CONTRACT_VERSION,
        ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_POLICY,
    )

    assert ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_CONTRACT_VERSION == "17.0.0"
    assert ANDROID_ORIGINATED_CANONICAL_DIAGNOSIS_POLICY.startswith("POLICY::")


def test_pr17_android_originated_causes_surface_in_canonical_diagnosis_paths() -> None:
    from core.unified_governance_semantics import build_unified_governance_state

    device_id = "dev_pr17"
    active_sessions = [SimpleNamespace(device_id=device_id)]
    mode_state = SimpleNamespace(mode=SimpleNamespace(value="cross_device"))
    readiness = SimpleNamespace(
        is_dispatch_eligible=True,
        is_takeover_eligible=True,
        is_cross_device_ready=True,
    )
    runtime_snapshot = _runtime_snapshot_for_pr17(device_id)
    integration = {
        "device_id": device_id,
        "execution_id": "exec_pr17",
        "integration_decision": "conditionally_allow",
        "integration_allowed": True,
        "overall_grade": "adequate",
        "dimension_results": [],
        "degradation_causes": ["recovery_truth:adequate:partial evidence"],
        "recovery_truth_quality": "adequate",
        "recovery_truth_degraded": False,
        "recovery_truth_gap_types": ["partial", "duplicated"],
        "recovery_truth_diagnosis": "android_recovery_partial_closure",
    }
    ownership_quality = SimpleNamespace(
        proof_class=SimpleNamespace(value="degraded_partial"),
        is_sufficient_for_closure=False,
        degraded=True,
        diagnosis=["android_takeover_completion_missing"],
    )
    mesh_state = {
        "status": "partial",
        "proof_quality": "stale",
        "proof_quality_reason": "android_mesh_reconnect_fragmented",
        "governance_readiness_impact": "degraded_stale_proof",
        "runtime_proof_count": 1,
    }

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        return_value=mode_state,
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        return_value=readiness,
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        return_value=False,
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value=runtime_snapshot,
    ), patch(
        "core.android_evidence_integration_pipeline.get_android_evidence_integration_summary",
        return_value=integration,
    ), patch(
        "core.unified_governance_semantics._OWNERSHIP_TRANSFER_PROOF_QUALITY_AVAILABLE",
        True,
    ), patch(
        "core.unified_governance_semantics.get_latest_ownership_transfer_proof_quality_for_device",
        return_value=ownership_quality,
    ), patch(
        "core.unified_governance_semantics.build_mesh_runtime_state",
        return_value=mesh_state,
    ):
        state = build_unified_governance_state()

    delegated = state["devices"][0]["governance_precedence"]["delegated_execution"]
    diagnosis = delegated["decision_causality"]["android_originated_canonical_diagnosis"]

    assert diagnosis["runtime"]["canonical_class"] == "stale_remote"
    assert diagnosis["capability"]["canonical_class"] == "downgraded"
    assert diagnosis["recovery"]["canonical_class"] == "adequate"
    assert diagnosis["takeover"]["canonical_class"] == "degraded_partial"
    assert diagnosis["mesh"]["canonical_class"] == "stale"

    assert "android_runtime_event_stale" in diagnosis["runtime"]["android_local_reasons"]
    assert "local_intelligence_status_disabled" in diagnosis["capability"]["android_local_reasons"]
    assert "partial" in diagnosis["recovery"]["android_local_reasons"]
    assert "android_takeover_completion_missing" in diagnosis["takeover"]["android_local_reasons"]
    assert "android_mesh_reconnect_fragmented" in diagnosis["mesh"]["android_local_reasons"]

    device_diag = state["devices"][0]["android_originated_canonical_diagnosis"]
    assert device_diag["capability"]["canonical_class"] == "downgraded"
