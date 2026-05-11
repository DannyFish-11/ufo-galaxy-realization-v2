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


def test_build_operational_readiness_report_canonical_cross_device():
    with patch(
        "core.operational_readiness_surface.get_operational_registration_path",
        return_value=_make_path(ValidationStatus.PASS),
    ), patch(
        "core.operational_readiness_surface._module_available",
        return_value=True,
    ), patch(
        "core.operational_readiness_surface._collect_device_evidence",
        return_value={
            "known_device_count": 1,
            "android_device_count": 1,
            "android_device_ids": ["android-1"],
            "cross_device_ready_device_ids": ["android-1"],
        },
    ), patch(
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
    ), patch(
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
    ), patch(
        "core.operational_readiness_surface._load_runtime_readiness",
        return_value={
            "available": True,
            "verdict": "ready",
            "blocking": False,
            "summary": "ready",
            "matrix": {},
        },
    ), patch(
        "core.operational_readiness_surface._load_system_acceptance",
        return_value={
            "available": True,
            "verdict": "fully_operational",
            "summary": "ok",
            "report": {},
        },
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.chain_state.main_chain_available is True
    assert report.chain_state.cross_device_available is True
    assert report.chain_state.success_quality == "canonical_cross_device"
    assert report.clone_to_use_acceptance["canonical_success"] is True
    assert report.clone_to_use_acceptance["ready_for_use"] is True
    assert report.android_v2_minimum_standard["minimum_viable_chain_ready"] is True
    android_admission = next(
        item for item in report.registration_kinds if item.kind == "device_android_admission"
    )
    assert android_admission.status == SurfaceStatus.ready


def test_build_operational_readiness_report_recovery_and_degraded():
    with patch(
        "core.operational_readiness_surface.get_operational_registration_path",
        return_value=_make_path(ValidationStatus.WARN),
    ), patch(
        "core.operational_readiness_surface._module_available",
        return_value=True,
    ), patch(
        "core.operational_readiness_surface._collect_device_evidence",
        return_value={
            "known_device_count": 1,
            "android_device_count": 1,
            "android_device_ids": ["android-1"],
            "cross_device_ready_device_ids": [],
        },
    ), patch(
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
    ), patch(
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
    ), patch(
        "core.operational_readiness_surface._load_runtime_readiness",
        return_value={
            "available": True,
            "verdict": "degraded",
            "blocking": False,
            "summary": "degraded",
            "matrix": {},
        },
    ), patch(
        "core.operational_readiness_surface._load_system_acceptance",
        return_value={
            "available": True,
            "verdict": "not_fully_operational_pending_dimensions",
            "summary": "pending",
            "report": {},
        },
    ):
        report = build_operational_readiness_report(route_paths=_required_route_paths())

    assert report.chain_state.recovery_active is True
    assert report.chain_state.active_path == "recovery"
    assert report.chain_state.success_quality == "recovery"
    assert report.clone_to_use_acceptance["canonical_success"] is False
    assert report.clone_to_use_acceptance["degraded_success"] is True
    result_closure = next(
        item
        for item in report.clone_to_use_acceptance["checkpoints"]
        if item["checkpoint_id"] == "result_closure"
    )
    assert result_closure["status"] == SurfaceStatus.degraded.value


def test_operational_readiness_routes_expose_expected_paths():
    router = create_router()
    paths = {route.path for route in router.routes}
    assert "/api/v1/projection/operational-readiness" in paths
    assert "/api/v1/projection/clone-to-use-acceptance" in paths


def test_operational_readiness_endpoint_returns_report_and_route_context():
    app = FastAPI()
    app.include_router(create_router())
    client = TestClient(app, raise_server_exceptions=False)
    fake_report = SimpleNamespace(
        to_dict=lambda: {"authority": "test-authority", "clone_to_use_acceptance": {}},
        contract_version="test-contract",
        validation={},
        chain_state=SimpleNamespace(to_dict=lambda: {"active_path": "main_chain"}),
        clone_to_use_acceptance={},
        android_v2_minimum_standard={},
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
