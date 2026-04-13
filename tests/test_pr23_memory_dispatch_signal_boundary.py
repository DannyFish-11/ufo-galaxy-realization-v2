"""PR-23: explicit memory/dispatch signal-boundary coverage."""

from __future__ import annotations


def test_memory_bias_active_scope_diagnostics_are_truthful():
    from core.cognitive.memory_bias_layer import build_memory_bias_active_scope_diagnostics

    diag = build_memory_bias_active_scope_diagnostics()
    scope = diag["memory_bias_behavioral_scope"]

    assert scope["planner_strategy_selection"] is True
    assert scope["kernel_runtime_diagnostics"] is True
    assert scope["source_dispatch_mode_selection"] is False
    assert scope["source_dispatch_target_selection"] is False
    assert scope["multimodal_route_selection"] is False


def test_source_dispatch_plan_surfaces_runtime_signal_boundary():
    from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan

    plan = build_source_dispatch_plan(
        force_local=True,
        task_hint="analysis",
        activation_budget={"breadth_mode": "narrow"},
        memory_bias={"posture": "continuity"},
        cognitive_execution_hint={"execution_path_preference": "planning"},
    )

    boundary = plan.metadata.get("runtime_signal_boundary", {})
    received = boundary.get("received_runtime_signals", {})
    dispatch_semantics = boundary.get("dispatch_semantics", {})
    execution_obs = boundary.get("execution_path_observability", {})
    truth_model = boundary.get("truth_model", {})

    assert boundary.get("dispatch_mode_selection_consumes_runtime_signals") is False
    assert boundary.get("dispatch_target_selection_consumes_runtime_signals") is False
    assert received == {
        "task_hint": True,
        "activation_budget": True,
        "memory_bias": True,
        "cognitive_execution_hint": True,
    }
    assert dispatch_semantics.get("mode_selection_consumes_runtime_signals") is False
    assert dispatch_semantics.get("target_selection_consumes_runtime_signals") is False
    assert execution_obs.get("received_runtime_signals") == received
    assert truth_model.get("runtime_truth_scope") == "dispatch_semantics_only"


def test_source_dispatch_result_preserves_runtime_signal_boundary():
    from core.runtime.source_dispatch_orchestrator import orchestrate_source_runtime_dispatch

    result = orchestrate_source_runtime_dispatch(
        force_local=True,
        task_hint="analysis",
        activation_budget={"breadth_mode": "narrow"},
        memory_bias={"posture": "continuity"},
        cognitive_execution_hint={"execution_path_preference": "planning"},
    )

    boundary = result.metadata.get("runtime_signal_boundary", {})
    assert boundary.get("memory_bias_behavioral_scope") == "planner_strategy_and_runtime_diagnostics"
    assert "dispatch_semantics" in boundary
    assert "execution_path_observability" in boundary
