from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.unified_governance_semantics import (
    GovernancePath,
    MESH_RUNTIME_STATUS_PARTIAL,
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
            },
            {
                "device_id": "dev_cross",
                "active_execution_count": 1,
                "highest_priority_execution_type": "takeover_request",
                "blocked_execution_types": ["goal_execution", "parallel_subtask"],
                "offline_queue_depth": 3,
                "execution_busy": True,
                "local_inference_available": True,
                "runtime_health_status": "degraded",
                "current_fallback_tier": "center_delegated",
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
    assert causality["runtime_health_status"] == "degraded"
    assert causality["current_fallback_tier"] == "center_delegated"
    assert state["execution_runtime_state"]["active_execution_total_count"] == 1
    assert "mesh_runtime_state" in state
    assert state["mesh_runtime_state"]["status"] == MESH_RUNTIME_STATUS_PARTIAL
    relationship_links = {
        link["link"] for link in state["mesh_runtime_state"]["runtime_relationships"]
    }
    assert "parallel_subtask_to_local_collaboration_agent" in relationship_links
