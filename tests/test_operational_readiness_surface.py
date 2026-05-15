from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.operational_readiness_surface import (
    DUAL_REPO_INTEGRATED_SYSTEM_CONTRACT_ROUTE,
    _MINIMAL_HAPPY_PATH_CONTRACT_VERSION,
    SurfaceStatus,
    build_operational_readiness_report,
)
from core.operational_registration_path import (
    OnboardingValidation,
    OperationalRegistrationPath,
    ValidationStatus,
    get_operational_registration_path,
)
from core.routes.operational_readiness import create_router


def _make_path(status: ValidationStatus) -> OperationalRegistrationPath:
    base = get_operational_registration_path()
    validation = OnboardingValidation(
        checks=[],
        overall_status=status,
        summary=f"validation={status.value}",
    )
    return OperationalRegistrationPath(
        registration_kinds=list(base.registration_kinds),
        onboarding_steps=list(base.onboarding_steps),
        validation=validation,
        main_chain_kinds=list(base.main_chain_kinds),
        cross_device_kinds=list(base.cross_device_kinds),
        compat_kinds=list(base.compat_kinds),
        system_identity=base.system_identity,
        contract_version=base.contract_version,
        authority=base.authority,
    )


def _required_route_paths() -> set[str]:
    return {
        "/api/v1/health",
        "/api/v1/chat",
        "/api/v1/projection/runtime",
        "/api/v1/projection/operational-readiness",
        "/api/v1/projection/clone-to-use-acceptance",
        "/api/v1/projection/operability-contract",
        "/api/v1/operator/board/operable-truth",
        "/api/v1/operator/actions/android-directed",
    }


def test_build_operational_readiness_report_canonical_cross_device_success_quality():
    from core.v2_android_truth_ssot import V2AndroidTruthBlock

    with (
        patch(
            "core.operational_readiness_surface.get_operational_registration_path",
            return_value=_make_path(ValidationStatus.PASS),
        ),
        patch(
            "core.operational_readiness_surface._module_available",
            return_value=True,
        ),
        patch(
            "core.operational_readiness_surface._collect_device_evidence",
            return_value={
                "known_device_count": 1,
                "android_device_count": 1,
                "android_device_ids": ["android-1"],
                "cross_device_ready_device_ids": ["android-1"],
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_android_evidence",
            return_value={
                "snapshot_count": 1,
                "snapshot_device_ids": ["android-1"],
                "capability_semantics_count": 1,
                "capability_visible_count": 1,
                "degraded_capability_device_count": 0,
                "execution_event_count": 2,
                "terminal_execution_event_count": 1,
                "ecosystem_summary": {"total_devices_with_snapshot": 1},
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_session_evidence",
            return_value={
                "active_session_count": 1,
                "total_session_count": 1,
                "replaced_session_count": 0,
                "detached_session_count": 0,
                "invalidated_session_count": 0,
                "participant_total_count": 1,
                "participant_active_count": 0,
                "participant_terminal_count": 1,
                "participant_terminal_success_count": 1,
                "task_initiated": True,
                "result_closure_established": True,
                "recovery_active": False,
                "participant_phases": ["terminal_success"],
            },
        ),
        patch(
            "core.operational_readiness_surface._load_runtime_readiness",
            return_value={
                "available": True,
                "verdict": "ready",
                "blocking": False,
                "summary": "ready",
                "matrix": {},
            },
        ),
        patch(
            "core.operational_readiness_surface._load_system_acceptance",
            return_value={
                "available": True,
                "verdict": "fully_operational",
                "summary": "ok",
                "report": {},
            },
        ),
        patch(
            "core.v2_android_truth_ssot.build_v2_android_truth_block",
            return_value=V2AndroidTruthBlock(
                device_id="android-1",
                participation_tier="dispatch_eligible",
                dispatch_eligible=True,
                device_mode="cross_device",
                local_inference_available=True,
            ),
        ),
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.chain_state.main_chain_available is True
    assert report.chain_state.cross_device_available is True
    assert report.chain_state.success_quality == "canonical_cross_device"
    assert report.clone_to_use_acceptance["canonical_success"] is True
    assert report.clone_to_use_acceptance["ready_for_use"] is True
    assert report.android_v2_minimum_standard["minimum_viable_chain_ready"] is True
    assert report.state_contract["derived_state"]["registration_state"]["state"] == "ready"
    assert report.state_contract["derived_state"]["capability_visibility"]["state"] == "visible"
    assert report.state_contract["eligibility_state"]["task_initiation"]["state"] == "eligible"
    assert report.state_contract["closure_quality_state"]["result_closure"]["state"] == "complete"
    assert report.state_contract["closure_quality_state"]["verdict_quality"]["state"] == "canonical"
    assert report.runtime_decision_reasoning["participation_tier"] == "dispatch_eligible"
    assert report.unified_mode_model["execution_location"] == "android_delegated"
    assert report.unified_mode_model["participation_layer"] == "dispatch_eligible"
    assert (
        report.runtime_decision_reasoning["readiness_basis"]["android_truth_basis"]["source_of_truth_ref"]
        == "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )
    assert (
        report.state_contract["derived_state"]["unified_mode_model"]["evidence"]["execution_location"]
        == "android_delegated"
    )
    minimal_contract = report.minimal_happy_path_contract
    assert minimal_contract["contract_version"] == _MINIMAL_HAPPY_PATH_CONTRACT_VERSION
    assert len(minimal_contract["steps"]) == 10
    step_map = {item["step_id"]: item for item in minimal_contract["steps"]}
    assert step_map["7_operator_board_routes_work"]["status"] == SurfaceStatus.ready.value
    assert step_map["9_delegated_task_sendable"]["status"] == SurfaceStatus.ready.value
    android_candidates = [item for item in report.registration_kinds if item.kind == "device_android_admission"]
    assert android_candidates, "expected device_android_admission registration kind"
    android_admission = android_candidates[0]
    assert android_admission.status == SurfaceStatus.ready


def test_build_operational_readiness_report_recovery_with_degraded_success():
    with (
        patch(
            "core.operational_readiness_surface.get_operational_registration_path",
            return_value=_make_path(ValidationStatus.WARN),
        ),
        patch(
            "core.operational_readiness_surface._module_available",
            return_value=True,
        ),
        patch(
            "core.operational_readiness_surface._collect_device_evidence",
            return_value={
                "known_device_count": 1,
                "android_device_count": 1,
                "android_device_ids": ["android-1"],
                "cross_device_ready_device_ids": [],
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_android_evidence",
            return_value={
                "snapshot_count": 1,
                "snapshot_device_ids": ["android-1"],
                "capability_semantics_count": 1,
                "capability_visible_count": 1,
                "degraded_capability_device_count": 1,
                "execution_event_count": 1,
                "terminal_execution_event_count": 0,
                "ecosystem_summary": {"total_devices_with_snapshot": 1},
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_session_evidence",
            return_value={
                "active_session_count": 1,
                "total_session_count": 1,
                "replaced_session_count": 1,
                "detached_session_count": 0,
                "invalidated_session_count": 0,
                "participant_total_count": 1,
                "participant_active_count": 1,
                "participant_terminal_count": 0,
                "participant_terminal_success_count": 0,
                "task_initiated": True,
                "result_closure_established": False,
                "recovery_active": True,
                "participant_phases": ["reconciling"],
            },
        ),
        patch(
            "core.operational_readiness_surface._load_runtime_readiness",
            return_value={
                "available": True,
                "verdict": "degraded",
                "blocking": False,
                "summary": "degraded",
                "matrix": {},
            },
        ),
        patch(
            "core.operational_readiness_surface._load_system_acceptance",
            return_value={
                "available": True,
                "verdict": "not_fully_operational_pending_dimensions",
                "summary": "pending",
                "report": {},
            },
        ),
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.chain_state.recovery_active is True
    assert report.chain_state.active_path == "recovery"
    assert report.chain_state.success_quality == "recovery"
    assert report.clone_to_use_acceptance["canonical_success"] is False
    assert report.clone_to_use_acceptance["degraded_success"] is True
    assert report.state_contract["derived_state"]["active_path"]["state"] == "recovery"
    assert report.state_contract["derived_state"]["recovery_active_state"]["state"] == "active"
    assert report.state_contract["closure_quality_state"]["result_closure"]["state"] == "incomplete"
    assert report.runtime_decision_reasoning["selected_runtime"] == "v2_local"
    assert report.state_contract["closure_quality_state"]["incomplete_state"]["state"] == "present"
    assert report.state_contract["closure_quality_state"]["verdict_quality"]["state"] == "recovery"
    result_closure_candidates = [
        item for item in report.clone_to_use_acceptance["checkpoints"] if item["checkpoint_id"] == "result_closure"
    ]
    assert result_closure_candidates, "expected result_closure checkpoint"
    result_closure = result_closure_candidates[0]
    assert result_closure["status"] == SurfaceStatus.degraded.value


def test_task_not_initiated_is_not_waiting_dependency_when_eligible():
    with (
        patch(
            "core.operational_readiness_surface.get_operational_registration_path",
            return_value=_make_path(ValidationStatus.PASS),
        ),
        patch(
            "core.operational_readiness_surface._module_available",
            return_value=True,
        ),
        patch(
            "core.operational_readiness_surface._collect_device_evidence",
            return_value={
                "known_device_count": 1,
                "android_device_count": 1,
                "android_device_ids": ["android-1"],
                "cross_device_ready_device_ids": ["android-1"],
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_android_evidence",
            return_value={
                "snapshot_count": 1,
                "snapshot_device_ids": ["android-1"],
                "capability_semantics_count": 1,
                "capability_visible_count": 1,
                "degraded_capability_device_count": 0,
                "execution_event_count": 0,
                "terminal_execution_event_count": 0,
                "ecosystem_summary": {"total_devices_with_snapshot": 1},
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_session_evidence",
            return_value={
                "active_session_count": 1,
                "total_session_count": 1,
                "replaced_session_count": 0,
                "detached_session_count": 0,
                "invalidated_session_count": 0,
                "participant_total_count": 1,
                "participant_active_count": 1,
                "participant_terminal_count": 0,
                "participant_terminal_success_count": 0,
                "task_initiated": False,
                "result_closure_established": False,
                "recovery_active": False,
                "participant_phases": ["active"],
            },
        ),
        patch(
            "core.operational_readiness_surface._load_runtime_readiness",
            return_value={
                "available": True,
                "verdict": "ready",
                "blocking": False,
                "summary": "ready",
                "matrix": {},
            },
        ),
        patch(
            "core.operational_readiness_surface._load_system_acceptance",
            return_value={
                "available": True,
                "verdict": "fully_operational",
                "summary": "ok",
                "report": {},
            },
        ),
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.state_contract["derived_state"]["cross_device_availability"]["state"] == "available"
    assert report.state_contract["eligibility_state"]["task_initiation"]["state"] == "eligible"
    assert report.state_contract["eligibility_state"]["task_initiation"]["active"] is False
    assert report.state_contract["closure_quality_state"]["waiting_dependency_state"]["state"] == "clear"


def test_operational_readiness_routes_expose_expected_paths():
    router = create_router()
    paths = {route.path for route in router.routes}
    assert "/api/v1/projection/operational-readiness" in paths
    assert "/api/v1/projection/clone-to-use-acceptance" in paths
    assert "/api/v1/projection/operability-contract" in paths
    assert DUAL_REPO_INTEGRATED_SYSTEM_CONTRACT_ROUTE in paths


def test_build_operational_readiness_report_exposes_compat_blocked_contract():
    with (
        patch(
            "core.operational_readiness_surface.get_operational_registration_path",
            return_value=_make_path(ValidationStatus.PASS),
        ),
        patch(
            "core.operational_readiness_surface._module_available",
            return_value=True,
        ),
        patch(
            "core.operational_readiness_surface._collect_device_evidence",
            return_value={
                "known_device_count": 0,
                "android_device_count": 0,
                "android_device_ids": [],
                "cross_device_ready_device_ids": [],
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_android_evidence",
            return_value={
                "snapshot_count": 0,
                "snapshot_device_ids": [],
                "capability_semantics_count": 0,
                "capability_visible_count": 0,
                "degraded_capability_device_count": 0,
                "execution_event_count": 0,
                "terminal_execution_event_count": 0,
                "ecosystem_summary": {"total_devices_with_snapshot": 0},
            },
        ),
        patch(
            "core.operational_readiness_surface._collect_session_evidence",
            return_value={
                "active_session_count": 0,
                "total_session_count": 0,
                "replaced_session_count": 0,
                "detached_session_count": 0,
                "invalidated_session_count": 0,
                "participant_total_count": 0,
                "participant_active_count": 0,
                "participant_terminal_count": 0,
                "participant_terminal_success_count": 0,
                "task_initiated": False,
                "result_closure_established": False,
                "recovery_active": False,
                "participant_phases": [],
            },
        ),
        patch(
            "core.operational_readiness_surface._load_runtime_readiness",
            return_value={
                "available": True,
                "verdict": "blocked",
                "blocking": True,
                "summary": "blocked",
                "matrix": {},
            },
        ),
        patch(
            "core.operational_readiness_surface._load_system_acceptance",
            return_value={
                "available": True,
                "verdict": "acceptance_unknown_insufficient_evidence",
                "summary": "blocked",
                "report": {},
            },
        ),
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.chain_state.active_path == "compat"
    assert report.chain_state.success_quality == "compat"
    assert report.state_contract["derived_state"]["active_path"]["state"] == "compat"
    assert report.state_contract["derived_state"]["compat_only_path"]["state"] == "active"
    assert report.state_contract["acceptance_state"]["operational_acceptance"]["state"] == "blocked"
    assert report.state_contract["closure_quality_state"]["blocked_state"]["state"] == "present"
    assert report.state_contract["closure_quality_state"]["result_closure"]["state"] == "not_applicable"


def test_operational_readiness_endpoint_returns_report_and_route_context():
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app, raise_server_exceptions=False)
    fake_report = SimpleNamespace(
        to_dict=lambda: {
            "authority": "test-authority",
            "contract_version": "test-contract",
            "validation": {},
            "registration_progress": {},
            "registration_kinds": [],
            "registration_domains": [],
            "chain_state": {"active_path": "main_chain"},
            "clone_to_use_acceptance": {},
            "android_v2_minimum_standard": {},
            "runtime_readiness": {},
            "system_acceptance": {},
            "state_contract": {"authority": "test-state-contract"},
            "minimal_happy_path_contract": {"overall_ready": True},
        },
        contract_version="test-contract",
        validation={},
        chain_state=SimpleNamespace(to_dict=lambda: {"active_path": "main_chain"}),
        clone_to_use_acceptance={},
        android_v2_minimum_standard={},
        state_contract={"authority": "test-state-contract"},
        minimal_happy_path_contract={"overall_ready": True},
    )
    with patch(
        "core.routes.operational_readiness.build_operational_readiness_report",
        return_value=fake_report,
    ) as builder:
        response = client.get("/api/v1/projection/operational-readiness")

    assert response.status_code == 200
    payload = response.json()
    assert payload["authority"] == "test-authority"
    assert payload["route_surface_authority"]
    assert payload["state_contract"]["authority"] == "test-state-contract"
    passed_paths = builder.call_args.kwargs["route_paths"]
    assert "/api/v1/projection/operational-readiness" in passed_paths
    assert "/api/v1/projection/clone-to-use-acceptance" in passed_paths


def test_clone_to_use_acceptance_endpoint_returns_acceptance_subset():
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app, raise_server_exceptions=False)
    fake_report = SimpleNamespace(
        contract_version="test-contract",
        validation={"passed": True},
        chain_state=SimpleNamespace(to_dict=lambda: {"active_path": "cross_device"}),
        clone_to_use_acceptance={"ready_for_use": True},
        android_v2_minimum_standard={"minimum_viable_chain_ready": True},
        state_contract={"authority": "test-state-contract"},
        minimal_happy_path_contract={"overall_ready": True},
    )
    with patch(
        "core.routes.operational_readiness.build_operational_readiness_report",
        return_value=fake_report,
    ):
        response = client.get("/api/v1/projection/clone-to-use-acceptance")

    assert response.status_code == 200
    payload = response.json()
    assert payload["clone_to_use_acceptance"]["ready_for_use"] is True
    assert payload["android_v2_minimum_standard"]["minimum_viable_chain_ready"] is True
    assert payload["state_contract"]["authority"] == "test-state-contract"
    assert payload["minimal_happy_path_contract"]["overall_ready"] is True


def test_operability_contract_endpoint_returns_minimal_happy_path_contract():
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app, raise_server_exceptions=False)
    fake_report = SimpleNamespace(
        contract_version="test-contract",
        minimal_happy_path_contract={"overall_ready": False, "blocking_steps": ["x"]},
        chain_state=SimpleNamespace(to_dict=lambda: {"active_path": "compat"}),
        runtime_decision_reasoning={"selected_runtime": "v2_local"},
        state_contract={"authority": "test-state-contract"},
    )
    with patch(
        "core.routes.operational_readiness.build_operational_readiness_report",
        return_value=fake_report,
    ):
        response = client.get("/api/v1/projection/operability-contract")

    assert response.status_code == 200
    payload = response.json()
    assert payload["minimal_happy_path_contract"]["overall_ready"] is False
    assert payload["minimal_happy_path_contract"]["blocking_steps"] == ["x"]
    assert payload["state_contract_authority"] == "test-state-contract"


def test_dual_repo_integrated_system_contract_endpoint_returns_integrated_contract():
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app, raise_server_exceptions=False)
    endpoint = DUAL_REPO_INTEGRATED_SYSTEM_CONTRACT_ROUTE
    fake_report = SimpleNamespace(
        state_contract={
            "authority": "test-state-contract",
            "raw_signals": {"runtime_readiness_verdict": "ready"},
            "derived_state": {"registration_state": {"state": "ready"}},
        },
        runtime_decision_reasoning={"selected_runtime": "android_delegated"},
        unified_mode_model={"execution_location": "android_delegated"},
        chain_state=SimpleNamespace(active_path="cross_device", success_quality="canonical_cross_device"),
        android_v2_minimum_standard={"minimum_viable_chain_ready": True},
        minimal_happy_path_contract={"overall_ready": True},
        clone_to_use_acceptance={"ready_for_use": True},
    )
    with (
        patch(
            "core.routes.operational_readiness.build_operational_readiness_report",
            return_value=fake_report,
        ),
        patch(
            "core.current_state_backbone_audit.build_system_backbone_snapshot",
            return_value={
                "authority": "backbone-authority",
                "contract_version": "1.0.0",
                "chain_closure_summary": {"request_chain": "established"},
                "mode_closure_summary": {
                    "local_mode": "established",
                    "distributed_participant": "partial",
                    "delegated_execution": "established",
                    "takeover": "partial",
                },
                "control_plane_layering": {"operator": {"role": "governance"}},
                "field_typing_schema": {"runtime_truth": "truth"},
                "established_count": 9,
                "partial_count": 2,
                "open_count": 1,
                "top_open_items": [{"label": "x", "detail_zh": "y"}],
                "honesty_note_zh": "note",
            },
        ),
    ):
        response = client.get(endpoint)

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_type"] == "dual_repo_current_state_integrated_system_contract"
    assert payload["entrypoint_model"]["central_entrypoint"] == endpoint
    assert payload["responsibility_layering"]["distributed_android_side"]["first_class_execution_participant"] is True
    assert payload["mode_participation_governance_layering"]["active_path"] == "cross_device"
    assert payload["minimal_operability_path"]["overall_ready"] is True
    assert payload["contract_version"] == "1.4.0"
    assert payload["android_repo_real_code_scope"]["repo"] == "DannyFish-11/ufo-galaxy-android"
    assert payload["android_repo_real_code_scope"]["android_audited_ref"] == ""
    assert "审计提交锚点" in payload["android_repo_real_code_scope"]["android_audited_ref_note_zh"]
    assert payload["completion_and_maturity_assessment"]["operability_ready_for_non_author"] is True
    assert payload["completion_and_maturity_assessment"]["completion_posture"] == "partially_integrated_transitional"
    assert payload["integrated_judgement_zh"]["complete_verdict"]["status"] == "partial"
    assert payload["integrated_judgement_zh"]["maturity_verdict"]["status"] == "partial"
    assert payload["integrated_judgement_zh"]["end_to_end_usability_verdict"]["status"] == "established"
    assert payload["integrated_judgement_zh"]["ecosystem_coherence_verdict"]["status"] == "partial"
    assert len(payload["integrated_judgement_zh"]["next_phase_key_work_zh"]) >= 3
    assert "不得用于宣称不存在的成熟度" in payload["integrated_judgement_zh"]["honesty_guardrail_zh"]
    dual_repo_cognition = payload["dual_repo_ecosystem_cognition_zh"]
    assert dual_repo_cognition["real_code_investigation_scope"]["android_repo"] == "DannyFish-11/ufo-galaxy-android"
    assert (
        "core/operational_readiness_surface.py"
        in dual_repo_cognition["real_code_investigation_scope"]["v2_real_code_anchors"]
    )
    assert (
        "app/src/main/java/com/ufo/galaxy/runtime/CanonicalDispatchChain.kt"
        in dual_repo_cognition["real_code_investigation_scope"]["android_real_code_anchors"]
    )
    assert dual_repo_cognition["local_chain_path_across_dual_repo"]["status"] == "partial"
    assert dual_repo_cognition["cross_device_chain_path_across_dual_repo"]["status"] == "partial"
    assert dual_repo_cognition["shared_state_ecosystem_judgement"]["status"] == "partial"
    assert dual_repo_cognition["remaining_gaps_to_full_maturity"]["status"] == "open"
    assert len(dual_repo_cognition["next_stage_priorities_zh"]["items"]) >= 3
    assert "不用于粉饰为已完全集成" in dual_repo_cognition["honesty_guardrail_zh"]
    trace_evidence = payload["dual_repo_trace_evidence_layer_zh"]
    assert trace_evidence["status"] == "established"
    assert trace_evidence["trace_nodes"]["local_chain_trace"]["status"] == "partial"
    assert trace_evidence["trace_nodes"]["cross_device_chain_trace"]["status"] == "partial"
    assert trace_evidence["trace_nodes"]["registration_connection_participation_trace"]["status"] == "partial"
    assert trace_evidence["trace_nodes"]["mode_execution_truth_acceptance_trace"]["status"] == "partial"
    assert trace_evidence["trace_nodes"]["result_uplink_and_closure_acceptance_trace"]["status"] == "partial"
    assert trace_evidence["trace_nodes"]["shared_protocol_and_state_semantics_trace"]["status"] == "partial"
    assert (
        trace_evidence["surface_truth_mapping"]["mobile_surface"]["mapping_type"] == "direct_truth_participant"
    )
    assert (
        trace_evidence["surface_truth_mapping"]["desktop_surface"]["mapping_type"] == "derived_projection_surface"
    )
    assert trace_evidence["source_of_truth_vs_projection_surfaces"]["status"] == "established"
    assert trace_evidence["trace_gaps_to_maturity"]["status"] == "open"
    assert len(trace_evidence["next_trace_closing_priorities_zh"]["items"]) >= 3
    assert "不得伪造全链路闭合" in trace_evidence["honesty_guardrail_zh"]
    assert len(payload["core_questions_assessment_zh"]) == 12
    question_ids = [entry["question_id"] for entry in payload["core_questions_assessment_zh"]]
    duplicates = sorted([qid for qid, count in Counter(question_ids).items() if count > 1])
    assert len(question_ids) == len(set(question_ids)), f"Duplicate question IDs found: {duplicates}"
    assert all(
        entry["status"] in {"established", "partial", "open"} for entry in payload["core_questions_assessment_zh"]
    )
    question_by_id = {entry["question_id"]: entry for entry in payload["core_questions_assessment_zh"]}
    assert sorted(question_by_id.keys()) == list(range(1, 13))
    assert question_by_id[1]["status"] == "established"
    assert question_by_id[2]["status"] == "partial"
    assert question_by_id[3]["status"] == "partial"
    assert question_by_id[4]["status"] == "partial"
    assert question_by_id[5]["status"] == "established"
    assert question_by_id[6]["status"] == "partial"
    assert question_by_id[7]["status"] == "partial"
    assert question_by_id[8]["status"] == "established"
    assert question_by_id[9]["status"] == "established"
    assert question_by_id[10]["status"] == "partial"
    assert question_by_id[11]["status"] == "partial"
    assert question_by_id[12]["status"] == "open"
