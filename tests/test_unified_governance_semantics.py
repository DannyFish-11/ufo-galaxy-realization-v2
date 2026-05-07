from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from core.unified_governance_semantics import (
    GovernancePath,
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

    with patch("core.attached_runtime_session_registry.list_active_sessions", return_value=active_sessions), patch(
        "core.android_mode_gate_policy.build_mode_state_for_device",
        side_effect=lambda device_id: mode_map[device_id],
    ), patch(
        "core.android_mode_gate_policy.evaluate_android_mode_readiness",
        side_effect=lambda device_id: readiness_map[device_id],
    ), patch(
        "core.unified_execution_governance.is_takeover_active",
        side_effect=lambda device_id: device_id == "dev_cross",
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
