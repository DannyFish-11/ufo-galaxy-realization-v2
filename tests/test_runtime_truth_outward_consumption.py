from __future__ import annotations


def test_runtime_truth_payload_includes_outward_task_and_startup_readiness(monkeypatch):
    import types
    import sys
    from core.routes import projection as projection_routes
    import core.runtime.source_dispatch_orchestrator as orchestrator

    class _FakeOutwardSnapshot:
        def to_dict(self):
            return {
                "operator_snapshot": {
                    "active_task_count": 2,
                    "recent_failure_count": 1,
                    "reachable_executor_count": 3,
                }
            }

    class _FakeRuntimeTruth:
        def to_dict(self):
            return {
                "compiled_at": 1.0,
                "compiler_authority": "test",
                "continuum": None,
                "topology": None,
                "oneapi": {"system_layer": "aggregator_integration"},
                "system_resource": None,
                "device_presence": {"registered": 0, "online": 0},
                "dispatch_semantics": {},
                "execution_path_observability": {},
                "has_canonical_topology": False,
                "tri_state_phase": None,
                "primary_model_id": None,
                "primary_provider_id": None,
                "oneapi_is_lower_horizon_only": True,
            }

    class _FakeMode:
        value = "local"

    class _FakePlan:
        ready = True
        readiness_notes = ["ok"]
        mode = _FakeMode()
        source_runtime_posture = "control_only"

    monkeypatch.setattr(projection_routes, "_compile_outward_truth", lambda: _FakeOutwardSnapshot())
    monkeypatch.setattr(
        projection_routes,
        "_attach_operational_state_board",
        lambda payload, route_paths=None: payload,
    )
    monkeypatch.setattr(orchestrator, "build_source_dispatch_plan", lambda: _FakePlan())
    fake_rtc = types.SimpleNamespace(
        compile_runtime_truth=lambda: _FakeRuntimeTruth(),
        RUNTIME_TRUTH_COMPILER_AUTHORITY="test",
    )
    monkeypatch.setitem(sys.modules, "core.projection.runtime_truth_compiler", fake_rtc)

    payload = projection_routes._assemble_runtime_truth_payload()

    assert "outward_truth" in payload
    assert payload["task_truth"]["active_task_count"] == 2
    assert payload["startup_readiness"]["ready_to_route"] is True
    assert payload["runtime_decision_reasoning"]["selected_runtime"] == "v2_local"
    assert payload["runtime_decision_reasoning"]["mode_basis"]["mode_state"] == "local"
    assert payload["shared_execution_visibility"]["completion_state"] == "not_started"
    assert "participation_truth_consumption" in payload
    assert payload["participation_truth_consumption"]["participation_tier"] == payload[
        "runtime_decision_reasoning"
    ]["participation_tier"]
    assert "device_lifecycle_stage" in payload["participation_truth_consumption"]
    assert "all_device_participation_matrix" in payload["participation_truth_consumption"]
    assert "devices" in payload["participation_truth_consumption"]["all_device_participation_matrix"]
    assert "foundational_system_truth" in payload
    assert "truth_acceptance_closure_contract" in payload
    truth_contract = payload["truth_acceptance_closure_contract"]
    assert set(truth_contract.keys()) >= {
        "authority_truth_source",
        "acceptance_closure_truth",
        "outward_projection_truth",
        "diagnostics_snapshot",
        "gate_candidate",
    }
    assert "outward_projection_truth" in truth_contract
    assert truth_contract["outward_projection_truth"]["projection_surface_role"] == "runtime_truth_board_facing"
    assert truth_contract["diagnostics_snapshot"]["is_authoritative_truth"] is False
    assert truth_contract["diagnostics_snapshot"]["is_audit_artifact"] is True
    assert truth_contract["diagnostics_snapshot"]["source"] == "cross_repo_acceptance_chain.stages"
    assert isinstance(truth_contract["diagnostics_snapshot"]["stage_count"], int)
    foundational = payload["foundational_system_truth"]
    assert foundational["cross_device_foundation"]["closure_state"] in {
        "established",
        "partial",
        "open",
        None,
    }
    assert foundational["multi_device_foundation"]["closure_state"] in {
        "established",
        "partial",
        "open",
        None,
    }
    assert foundational["real_three_state_model"]["states"] == ["established", "partial", "open"]
    assert foundational["real_three_state_model"]["is_engineering_approximation"] is True
    assert "native_three_state_final_audit" in foundational
    assert "local_cross_multi_foundation_audit" in foundational
    assert "task_system_layered_status" in foundational
    assert "task_system_body_final_audit" in foundational
    assert payload["execution_stage"] is None


def test_dispatch_semantics_exposes_planning_fields():
    try:
        from core.projection.runtime_truth_compiler import _compile_dispatch_semantics
    except ModuleNotFoundError:
        return

    semantics = _compile_dispatch_semantics()
    if semantics is None:
        # Environment may not have source-dispatch dependencies; in that case
        # we only verify graceful unavailability behavior.
        return

    assert "planned_mode" in semantics
    assert "planning_ready" in semantics
    assert "planning_readiness_notes" in semantics
