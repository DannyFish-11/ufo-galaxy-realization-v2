from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.operational_readiness_surface import (
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
        },
        contract_version="test-contract",
        validation={},
        chain_state=SimpleNamespace(to_dict=lambda: {"active_path": "main_chain"}),
        clone_to_use_acceptance={},
        android_v2_minimum_standard={},
        state_contract={"authority": "test-state-contract"},
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
