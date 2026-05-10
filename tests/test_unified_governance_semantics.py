from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.unified_governance_semantics import (
    GovernancePath,
    MESH_RUNTIME_STATUS_PARTIAL,
    MESH_RUNTIME_STATUS_RUNTIME_PROVEN,
    build_mesh_runtime_state,
    build_unified_governance_state,
    resolve_governance_path_decision,
)


def test_local_mode_scope_blocks_delegated_and_takeover() -> None:
    delegated = resolve_governance_path_decision(
        mode="local",
        path=GovernancePath.delegated_execution,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=False,
    )
    takeover = resolve_governance_path_decision(
        mode="local",
        path=GovernancePath.takeover,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=False,
    )

    assert delegated.eligible is False
    assert delegated.blocked_by == "local_mode_boundary"
    assert takeover.eligible is False
    assert takeover.blocked_by == "local_mode_boundary"


def test_cross_device_mode_delegated_and_takeover_use_v2_authority() -> None:
    delegated = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.delegated_execution,
        dispatch_eligible=True,
        takeover_eligible=False,
        takeover_active=False,
    )
    takeover = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.takeover,
        dispatch_eligible=False,
        takeover_eligible=True,
        takeover_active=False,
    )

    assert delegated.eligible is True
    assert delegated.authority_owner == "v2_authority"
    assert takeover.eligible is True
    assert takeover.authority_owner == "v2_authority"


def test_cross_device_mode_delegated_blocked_by_execution_runtime_conflict() -> None:
    delegated = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.delegated_execution,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=False,
        blocked_execution_types=["goal_execution"],
    )
    assert delegated.eligible is False
    assert delegated.blocked_by == "execution_runtime_blocked:goal_execution"


def test_cross_device_mode_delegated_deferred_by_canonical_gate() -> None:
    delegated = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.delegated_execution,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=False,
        canonical_execution_gate_decision="defer",
    )
    assert delegated.eligible is False
    assert delegated.blocked_by == "canonical_execution_gate:defer"


def test_cross_device_mode_delegated_denied_by_canonical_gate() -> None:
    delegated = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.delegated_execution,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=False,
        canonical_execution_gate_decision="deny",
    )
    assert delegated.eligible is False
    assert delegated.blocked_by == "canonical_execution_gate:deny"


def test_takeover_active_blocks_lower_precedence_paths() -> None:
    decision = resolve_governance_path_decision(
        mode="cross_device",
        path=GovernancePath.local_execution,
        dispatch_eligible=True,
        takeover_eligible=True,
        takeover_active=True,
    )
    assert decision.eligible is False
    assert decision.blocked_by == "takeover"


def test_build_unified_governance_state_projects_mode_scope_and_precedence() -> None:
    active_sessions = [SimpleNamespace(device_id="dev_local"), SimpleNamespace(device_id="dev_cross")]
    mode_map = {
        "dev_local": SimpleNamespace(mode=SimpleNamespace(value="local")),
        "dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device")),
    }
    readiness_map = {
        "dev_local": SimpleNamespace(is_dispatch_eligible=False, is_takeover_eligible=False),
        "dev_cross": SimpleNamespace(is_dispatch_eligible=True, is_takeover_eligible=True),
    }

    runtime_snapshot = {
        "devices": [
            {
                "device_id": "dev_local",
                "active_execution_count": 0,
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 0,
                "execution_busy": False,
                "local_inference_available": False,
                "runtime_health_status": "healthy",
                "current_fallback_tier": "planner_local",
                "snapshot_reconciliation_status": "accepted",
                "snapshot_reconciliation_reason": "newer_snapshot_timestamp",
                "snapshot_conflict": False,
                "snapshot_ordering_basis": "snapshot_ts",
                "snapshot_last_updated_at": 123.0,
                "snapshot_reconciliation_applied": True,
                "latest_execution_event_phase": "completed",
                "latest_execution_event_absorbed_at": 100.0,
                "latest_execution_event_age_s": 2.0,
                "execution_busy_window_seconds": 60.0,
            },
            {
                "device_id": "dev_cross",
                "active_execution_count": 1,
                "active_executions": [
                    {
                        "execution_type": "takeover_request",
                        "execution_id": "exec_cross_1",
                        "started_at": 450.0,
                        "priority": 0,
                        "blocks_lower_priority": True,
                    }
                ],
                "highest_priority_execution_type": "takeover_request",
                "blocked_execution_types": ["goal_execution", "parallel_subtask"],
                "offline_queue_depth": 3,
                "execution_busy": True,
                "local_inference_available": True,
                "android_reported_mode": "local",
                "android_reported_mode_state": "local_only",
                "android_reported_mode_readiness_state": "degraded",
                "android_reported_cross_device_eligibility": False,
                "android_reported_goal_execution_eligibility": False,
                "android_reported_parallel_execution_eligibility": False,
                "android_reported_local_intelligence_status": "disabled",
                "android_reported_local_inference_ready": False,
                "android_reported_local_inference_available": True,
                "android_semantics_absorbed_at": 451.0,
                "android_semantics_reported_at": 449.0,
                "android_semantics_age_s": 2.0,
                "runtime_health_status": "degraded",
                "current_fallback_tier": "center_delegated",
                "snapshot_reconciliation_status": "conflict_center_truth_retained",
                "snapshot_reconciliation_reason": "same_timestamp_conflicting_payload",
                "snapshot_conflict": True,
                "snapshot_ordering_basis": "snapshot_ts+payload_hash",
                "snapshot_last_updated_at": 456.0,
                "snapshot_reconciliation_applied": False,
                "latest_execution_event_phase": "execution",
                "latest_execution_event_absorbed_at": 450.0,
                "latest_execution_event_age_s": 6.0,
                "execution_busy_window_seconds": 60.0,
            },
        ],
        "active_device_count": 1,
        "active_execution_total_count": 1,
    }

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        side_effect=lambda device_id: device_id == "dev_cross",
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value=runtime_snapshot,
    ):
        state = build_unified_governance_state()

    assert state["local_mode_count"] == 1
    assert state["cross_device_mode_count"] == 1
    assert state["takeover_active_count"] == 1
    assert len(state["devices"]) == 2

    local = next(d for d in state["devices"] if d["device_id"] == "dev_local")
    assert local["android_autonomy_scope"] == "local_autonomy"
    assert local["governance_precedence"]["delegated_execution"]["eligible"] is False
    cross = next(d for d in state["devices"] if d["device_id"] == "dev_cross")
    assert cross["android_autonomy_scope"] == "subordinate_participation"
    assert cross["governance_precedence"]["takeover"]["eligible"] is True
    assert cross["runtime_execution_state"]["highest_priority_execution_type"] == "takeover_request"
    causality = cross["governance_precedence"]["delegated_execution"]["decision_causality"]
    assert causality["active_execution_count"] == 1
    assert causality["execution_busy"] is True
    assert causality["offline_queue_depth"] == 3
    assert causality["local_inference_available"] is True
    assert causality["android_reported_mode"] == "local"
    assert causality["android_reported_mode_state"] == "local_only"
    assert causality["android_reported_mode_readiness_state"] == "degraded"
    assert causality["android_reported_cross_device_eligibility"] is False
    assert causality["android_reported_local_inference_available"] is True
    assert causality["android_semantics_absorbed_at"] == 451.0
    assert causality["android_semantics_reported_at"] == 449.0
    assert causality["android_semantics_age_s"] == 2.0
    assert causality["runtime_health_status"] == "degraded"
    assert causality["current_fallback_tier"] == "center_delegated"
    assert causality["snapshot_reconciliation_status"] == "conflict_center_truth_retained"
    assert causality["snapshot_reconciliation_reason"] == "same_timestamp_conflicting_payload"
    assert causality["snapshot_conflict"] is True
    assert causality["snapshot_ordering_basis"] == "snapshot_ts+payload_hash"
    assert causality["snapshot_last_updated_at"] == 456.0
    assert causality["snapshot_reconciliation_applied"] is False
    assert causality["snapshot_continuity_state"] == "conflict_retained"
    assert causality["latest_execution_event_phase"] == "execution"
    assert causality["latest_execution_event_absorbed_at"] == 450.0
    assert causality["latest_execution_event_age_s"] == 6.0
    assert causality["execution_busy_window_seconds"] == 60.0
    assert causality["android_evidence_integration_execution_id"] == "exec_cross_1"
    assert "android_evidence_integration_decision" in causality
    assert "android_evidence_integration_allowed" in causality
    assert "android_evidence_integration_grade" in causality
    assert "android_evidence_integration_degradation_causes" in causality
    assert "android_evidence_recovery_truth_quality" in causality
    assert "android_evidence_recovery_truth_degraded" in causality
    assert "android_evidence_recovery_truth_gap_types" in causality
    assert "android_evidence_recovery_truth_diagnosis" in causality
    assert cross["android_evidence_integration"]["execution_id"] == "exec_cross_1"
    assert state["execution_runtime_state"]["active_execution_total_count"] == 1
    assert "mesh_runtime_state" in state
    assert state["mesh_runtime_state"]["status"] == MESH_RUNTIME_STATUS_PARTIAL
    relationship_links = {
        link["link"] for link in state["mesh_runtime_state"]["runtime_relationships"]
    }
    assert "parallel_subtask_to_local_collaboration_agent" in relationship_links


def test_build_unified_governance_state_local_inference_changes_canonical_gate_decision() -> None:
    active_sessions = [SimpleNamespace(device_id="dev_cross")]
    mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
    readiness_map = {
        "dev_cross": SimpleNamespace(is_dispatch_eligible=True, is_takeover_eligible=True, is_cross_device_ready=True)
    }

    runtime_snapshot_base = {
        "devices": [
            {
                "device_id": "dev_cross",
                "active_execution_count": 0,
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 0,
                "execution_busy": False,
                "local_inference_available": False,
                "runtime_health_status": "healthy",
                "current_fallback_tier": None,
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        return_value=False,
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value=runtime_snapshot_base,
    ):
        denied_state = build_unified_governance_state()

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        return_value=False,
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value={
            **runtime_snapshot_base,
            "devices": [{**runtime_snapshot_base["devices"][0], "local_inference_available": True}],
        },
    ):
        allowed_state = build_unified_governance_state()

    denied_device = denied_state["devices"][0]
    denied_decision = denied_device["governance_precedence"]["delegated_execution"]
    assert denied_decision["eligible"] is False
    assert denied_decision["blocked_by"] == "canonical_execution_gate:deny"
    denied_causality = denied_decision["decision_causality"]
    assert denied_causality["canonical_execution_gate_decision"] == "deny"

    # PR-7A hardening: without Android capability truth in the runtime snapshot,
    # proof_input_class is "missing", which degrades the gate to "deny" regardless
    # of local_inference_available.  Absent Android truth is NOT positive evidence.
    allowed_device = allowed_state["devices"][0]
    allowed_decision = allowed_device["governance_precedence"]["delegated_execution"]
    allowed_causality = allowed_decision["decision_causality"]
    # With missing Android truth, even local_inference_available=True cannot
    # promote the gate to "allow".  The gate must remain "deny".
    assert allowed_causality["canonical_execution_gate_decision"] == "deny"
    assert allowed_decision["eligible"] is False
    assert allowed_decision["blocked_by"] == "canonical_execution_gate:deny"
    # The degradation reason must be present in the causality.
    assert allowed_causality.get("android_capability_truth_degraded") is True
    assert allowed_causality["snapshot_continuity_state"] == "unavailable"


def test_build_unified_governance_state_stale_android_truth_downgrades_canonical_gate() -> None:
    active_sessions = [SimpleNamespace(device_id="dev_cross")]
    mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
    readiness_map = {
        "dev_cross": SimpleNamespace(is_dispatch_eligible=True, is_takeover_eligible=True, is_cross_device_ready=True)
    }
    runtime_snapshot = {
        "devices": [
            {
                "device_id": "dev_cross",
                "active_execution_count": 0,
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 0,
                "execution_busy": False,
                "local_inference_available": False,
                "android_reported_mode": None,
                "android_reported_mode_state": None,
                "android_reported_local_inference_available": None,
                "android_semantics_age_s": 121.0,
                "android_semantics_freshness_threshold_s": 120.0,
                "android_semantics_freshness_state": "stale",
                "android_semantics_freshness_reason": "android_semantics_age_exceeds_threshold",
                "android_runtime_truth_authority": "downgraded_to_unknown",
                "android_runtime_truth_usable": False,
                "runtime_health_status": "healthy",
                "current_fallback_tier": None,
                "snapshot_reconciliation_status": "accepted",
                "snapshot_reconciliation_reason": "newer_snapshot_timestamp",
                "snapshot_conflict": False,
                "snapshot_ordering_basis": "snapshot_ts",
                "snapshot_last_updated_at": 123.0,
                "snapshot_reconciliation_applied": True,
                "latest_execution_event_phase": None,
                "latest_execution_event_absorbed_at": 0.0,
                "latest_execution_event_age_s": None,
                "execution_busy_window_seconds": 60.0,
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        return_value=False,
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value=runtime_snapshot,
    ):
        state = build_unified_governance_state()

    delegated = state["devices"][0]["governance_precedence"]["delegated_execution"]
    assert delegated["eligible"] is False
    assert delegated["blocked_by"] == "canonical_execution_gate:deny"
    causality = delegated["decision_causality"]
    assert causality["canonical_execution_gate_decision"] == "deny"
    # PR-7A hardening: stale Android truth triggers android_capability_truth_degraded
    # reason, not capability_unavailable — the gate is denied by truth quality, not
    # by capability check.
    assert "android_capability_truth_degraded:stale" in causality["canonical_execution_gate_reasons"]
    assert causality.get("android_capability_truth_degraded") is True
    assert causality["android_semantics_age_s"] == 121.0
    assert causality["android_semantics_freshness_threshold_s"] == 120.0
    assert causality["android_semantics_freshness_state"] == "stale"
    assert causality["android_semantics_freshness_reason"] == "android_semantics_age_exceeds_threshold"
    assert causality["android_runtime_truth_authority"] == "downgraded_to_unknown"
    assert causality["android_runtime_truth_usable"] is False
    assert causality["android_reported_mode"] is None


def test_build_unified_governance_state_surfaces_recovery_truth_diagnostics() -> None:
    active_sessions = [SimpleNamespace(device_id="dev_cross")]
    mode_map = {"dev_cross": SimpleNamespace(mode=SimpleNamespace(value="cross_device"))}
    readiness_map = {
        "dev_cross": SimpleNamespace(
            is_dispatch_eligible=True,
            is_takeover_eligible=True,
            is_cross_device_ready=True,
        )
    }
    runtime_snapshot = {
        "devices": [
            {
                "device_id": "dev_cross",
                "active_execution_count": 0,
                "highest_priority_execution_type": None,
                "blocked_execution_types": [],
                "offline_queue_depth": 0,
                "execution_busy": False,
                "local_inference_available": True,
                "runtime_health_status": "healthy",
                "current_fallback_tier": None,
            }
        ],
        "active_device_count": 0,
        "active_execution_total_count": 0,
    }
    recovery_integration = {
        "device_id": "dev_cross",
        "execution_id": "exec_recovery",
        "integration_decision": "conditionally_allow",
        "integration_allowed": True,
        "overall_grade": "adequate",
        "dimension_results": [],
        "degradation_causes": ["recovery_truth:adequate:partial evidence"],
        "recovery_truth_quality": "adequate",
        "recovery_truth_degraded": False,
        "recovery_truth_gap_types": ["partial", "duplicated"],
        "recovery_truth_diagnosis": "recovery_truth_quality_assessed",
    }

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        return_value=False,
    ), patch(
        "core.unified_execution_governance.get_execution_runtime_snapshot",
        return_value=runtime_snapshot,
    ), patch(
        "core.android_evidence_integration_pipeline.get_android_evidence_integration_summary",
        return_value=recovery_integration,
    ):
        state = build_unified_governance_state()

    causality = state["devices"][0]["governance_precedence"]["delegated_execution"][
        "decision_causality"
    ]
    assert causality["android_evidence_recovery_truth_quality"] == "adequate"
    assert causality["android_evidence_recovery_truth_degraded"] is False
    assert causality["android_evidence_recovery_truth_gap_types"] == [
        "partial",
        "duplicated",
    ]
    assert causality["android_evidence_recovery_truth_diagnosis"] == "recovery_truth_quality_assessed"


def test_build_mesh_runtime_state_stays_partial_without_live_runtime_execution_proof() -> None:
    from core.runtime.source_dispatch_orchestrator import reset_live_mesh_runtime_proof_snapshot

    reset_live_mesh_runtime_proof_snapshot()

    state = build_mesh_runtime_state()

    assert state["status"] == MESH_RUNTIME_STATUS_PARTIAL
    assert state["runtime_proofs"]["live_mesh_runtime_path_execution"] is False
    assert state["runtime_observability"]["live_mesh_runtime_proof"]["live_mesh_run_count"] == 0


def test_build_mesh_runtime_state_is_runtime_proven_after_staged_mesh_live_run() -> None:
    from contracts.source_dispatch import SourceDispatchMode
    from core.runtime.source_dispatch_orchestrator import (
        orchestrate_source_runtime_dispatch,
        reset_live_mesh_runtime_proof_snapshot,
    )

    reset_live_mesh_runtime_proof_snapshot()
    mesh_session = {
        "session_id": "mesh_runtime_proof_session",
        "mesh_id": "mesh_runtime_proof",
        "source_device_id": "source_runtime_proof",
        "primary_device_id": "primary_runtime_proof",
        "participants": [
            {"device_id": "source_runtime_proof", "roles": ["source"], "status": "active"},
            {"device_id": "primary_runtime_proof", "roles": ["primary"], "status": "active"},
        ],
        "multi_device_required": True,
        "barrier_posture": "soft_barrier",
        "merge_owner_device_id": "primary_runtime_proof",
    }
    result = orchestrate_source_runtime_dispatch(
        trace_id="trace_mesh_runtime_proven",
        mesh_session=mesh_session,
        policy_alignment=None,
        governance_snapshot=None,
        mesh_memberships=None,
    )
    assert result.mode == SourceDispatchMode.staged_mesh

    state = build_mesh_runtime_state()
    assert state["status"] == MESH_RUNTIME_STATUS_RUNTIME_PROVEN
    assert state["runtime_proofs"]["live_mesh_runtime_path_execution"] is True
    live_proof = state["runtime_observability"]["live_mesh_runtime_proof"]
    assert live_proof["staged_mesh_dispatch_count"] == 1
    assert live_proof["live_mesh_run_count"] == 1
    assert live_proof["last_mesh_session_id"] == "mesh_runtime_proof_session"
