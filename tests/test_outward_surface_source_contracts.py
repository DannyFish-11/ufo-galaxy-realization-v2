from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import absorb_device_state_snapshot, reset_android_device_state_store
from core.outward_surface_source_contract import (
    OUTWARD_SURFACE_SOURCE_CONTRACTS,
    assert_outward_surface_source_contract,
)
from core.routes.operator import create_router
from core.unified_panel_aggregation import build_unified_panel_payload


def test_inventory_covers_required_high_value_surfaces():
    assert "panel_unified" in OUTWARD_SURFACE_SOURCE_CONTRACTS
    assert "desktop_status_board_projection" in OUTWARD_SURFACE_SOURCE_CONTRACTS
    assert "operator_devices_ecosystem" in OUTWARD_SURFACE_SOURCE_CONTRACTS


def test_panel_prefers_compiled_outward_truth_primary_path(monkeypatch):
    class _FakeOutwardSnapshot:
        def to_dict(self):
            return {
                "compiled_at": 123.0,
                "surfacing_complete": True,
                "unavailable_source_count": 0,
                "operator_snapshot": {
                    "active_task_count": 5,
                    "recent_failure_count": 2,
                    "reachable_executor_count": 4,
                },
            }

    monkeypatch.setattr("core.outward_runtime_truth.compile_outward_truth", lambda: _FakeOutwardSnapshot())

    payload = build_unified_panel_payload().to_dict()
    evidence = payload.get("truth_compilation_evidence")
    assert evidence.get("assembly_mode") == "compiled_outward_truth_primary"
    assert payload.get("task_truth", {}).get("source") == "outward_truth.operator_snapshot"

    assert_outward_surface_source_contract(
        "panel_unified",
        truth_compilation_evidence=evidence,
        authority_source_fingerprint=payload.get("authority_source_fingerprint"),
    )


def test_board_projection_mixed_source_fallback_requires_explicit_evidence(monkeypatch):
    import core.routes.projection as routes_mod

    monkeypatch.setattr(
        routes_mod,
        "_compile_outward_truth",
        lambda: (_ for _ in ()).throw(RuntimeError("outward unavailable")),
    )

    payload = routes_mod._assemble_desktop_status_board_payload(route_paths={"/api/v1/projection/runtime"})
    evidence = payload.get("truth_compilation_evidence")
    assert evidence.get("assembly_mode") == "mixed_source_fallback"
    assert evidence.get("fallback_used") is True
    assert evidence.get("mixed_source") is True
    assert "outward unavailable" in str(evidence.get("fallback_reason"))

    assert_outward_surface_source_contract(
        "desktop_status_board_projection",
        truth_compilation_evidence=evidence,
        authority_source_fingerprint=payload.get("authority_source_fingerprint"),
    )


def test_operator_ecosystem_source_classification_is_runtime_visible():
    reset_android_device_state_store()
    absorb_device_state_snapshot("eco_contract_01", {"model_ready": True})

    app = FastAPI()
    app.include_router(create_router())
    with TestClient(app, raise_server_exceptions=False) as client:
        payload = client.get("/api/v1/operator/devices/ecosystem").json()

    fingerprint = payload.get("authority_source_fingerprint")
    assert fingerprint.get("primary_source_kind") == "runtime_visible_state"

    assert_outward_surface_source_contract(
        "operator_devices_ecosystem",
        authority_source_fingerprint=fingerprint,
    )
