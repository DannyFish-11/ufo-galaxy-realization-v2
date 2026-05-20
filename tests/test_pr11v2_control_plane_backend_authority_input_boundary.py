from __future__ import annotations

import inspect


def test_pr4_board_consumes_canonical_backend_authority_input():
    import core.pr4_operator_action_governance as pr4

    source = inspect.getsource(pr4.build_operator_board_projection)
    assert "build_control_plane_backend_authority_input" in source
    assert "core.routes.projection" not in source


def test_control_plane_backend_authority_input_surface_is_available():
    from core.control_plane_authority_input import (
        CONTROL_PLANE_BACKEND_AUTHORITY_INPUT_POLICY,
        build_control_plane_backend_authority_input,
    )

    payload = build_control_plane_backend_authority_input(
        runtime_decision_reasoning={"selected_device": "android-1", "participation_tier": "dispatch_eligible"},
    )
    assert "control-plane backend authority input" in CONTROL_PLANE_BACKEND_AUTHORITY_INPUT_POLICY.lower()
    assert "operational_state_board" in payload
    assert "participation_truth_consumption" in payload
    assert "foundational_system_truth" in payload
