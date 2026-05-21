"""
tests/test_operator_control_plane_routes.py
============================================
Tests for the new V2 control-plane operator endpoints added in this PR:

  GET /api/v1/readiness
  GET /api/v1/operator/flows
  GET /api/v1/operator/flows/{flow_id}
  GET /api/v1/operator/llm
  GET /api/v1/operator/nats
  GET /api/v1/operator/heartbeat
  GET /api/v1/ports
  GET /api/v1/operator/devices/ecosystem
  GET /api/v1/operator/devices/ecosystem/{device_id}

Each test uses the FastAPI TestClient against the operator router directly,
isolating from the full application startup.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import (
    absorb_device_state_snapshot,
    reset_android_device_state_store,
)
from core.routes.operator import create_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """FastAPI app wired with the operator router only."""
    _app = FastAPI()
    _app.include_router(create_router())
    return _app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_store():
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


# ---------------------------------------------------------------------------
# GET /api/v1/readiness
# ---------------------------------------------------------------------------


def test_readiness_returns_200(client):
    resp = client.get("/api/v1/readiness")
    assert resp.status_code == 200


def test_readiness_has_verdict(client):
    data = client.get("/api/v1/readiness").json()
    assert "verdict" in data


def test_readiness_has_dimensions(client):
    data = client.get("/api/v1/readiness").json()
    assert "dimensions" in data
    assert isinstance(data["dimensions"], list)


def test_readiness_has_matrix_id(client):
    data = client.get("/api/v1/readiness").json()
    assert "matrix_id" in data


def test_readiness_verdict_is_valid_string(client):
    data = client.get("/api/v1/readiness").json()
    verdict = data.get("verdict", "")
    assert verdict in ("ready", "blocked", "degraded", "unknown"), (
        f"Unexpected verdict: {verdict!r}"
    )


# ---------------------------------------------------------------------------
# GET /api/v1/operator/flows
# ---------------------------------------------------------------------------


def test_operator_flows_returns_200(client):
    resp = client.get("/api/v1/operator/flows")
    assert resp.status_code == 200


def test_operator_flows_has_flows_key(client):
    data = client.get("/api/v1/operator/flows").json()
    assert "flows" in data
    assert isinstance(data["flows"], list)


def test_operator_flows_has_total(client):
    data = client.get("/api/v1/operator/flows").json()
    assert "total" in data
    assert isinstance(data["total"], int)


# ---------------------------------------------------------------------------
# GET /api/v1/operator/flows/{flow_id} — 404 case
# ---------------------------------------------------------------------------


def test_get_flow_unknown_returns_404(client):
    resp = client.get("/api/v1/operator/flows/nonexistent_flow_id")
    assert resp.status_code == 404


def test_get_flow_unknown_has_detail(client):
    data = client.get("/api/v1/operator/flows/nonexistent_flow_id").json()
    assert "detail" in data


# ---------------------------------------------------------------------------
# GET /api/v1/operator/llm
# ---------------------------------------------------------------------------


def test_operator_llm_returns_200(client):
    resp = client.get("/api/v1/operator/llm")
    assert resp.status_code == 200


def test_operator_llm_has_available_field(client):
    data = client.get("/api/v1/operator/llm").json()
    assert "available" in data


# ---------------------------------------------------------------------------
# GET /api/v1/operator/nats
# ---------------------------------------------------------------------------


def test_operator_nats_returns_200(client):
    resp = client.get("/api/v1/operator/nats")
    assert resp.status_code == 200


def test_operator_nats_has_connected_field(client):
    data = client.get("/api/v1/operator/nats").json()
    assert "connected" in data


def test_operator_nats_has_noop_mode(client):
    data = client.get("/api/v1/operator/nats").json()
    assert "noop_mode" in data


def test_operator_nats_has_stats(client):
    data = client.get("/api/v1/operator/nats").json()
    assert "stats" in data


def test_operator_nats_exposes_posture_fields(client):
    data = client.get("/api/v1/operator/nats").json()
    assert "posture" in data
    assert "required" in data
    assert "assertion_ok" in data


# ---------------------------------------------------------------------------
# GET /api/v1/operator/heartbeat
# ---------------------------------------------------------------------------


def test_operator_heartbeat_returns_200(client):
    resp = client.get("/api/v1/operator/heartbeat")
    assert resp.status_code == 200


def test_operator_heartbeat_has_enabled(client):
    data = client.get("/api/v1/operator/heartbeat").json()
    assert "enabled" in data


def test_operator_heartbeat_has_running(client):
    data = client.get("/api/v1/operator/heartbeat").json()
    assert "running" in data


# ---------------------------------------------------------------------------
# GET /api/v1/ports
# ---------------------------------------------------------------------------


def test_ports_returns_200(client):
    resp = client.get("/api/v1/ports")
    assert resp.status_code == 200


def test_ports_has_node_ports(client):
    data = client.get("/api/v1/ports").json()
    assert "node_ports" in data
    assert isinstance(data["node_ports"], dict)


def test_ports_has_service_ports(client):
    data = client.get("/api/v1/ports").json()
    assert "service_ports" in data
    assert isinstance(data["service_ports"], dict)


def test_ports_service_includes_gateway(client):
    data = client.get("/api/v1/ports").json()
    # gateway port should always be in the defaults
    service_ports = data.get("service_ports", {})
    assert "gateway" in service_ports or "api_gateway" in service_ports


# ---------------------------------------------------------------------------
# GET /api/v1/operator/devices/ecosystem
# ---------------------------------------------------------------------------


def test_devices_ecosystem_returns_200(client):
    resp = client.get("/api/v1/operator/devices/ecosystem")
    assert resp.status_code == 200


def test_devices_ecosystem_empty_when_no_snapshots(client):
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    assert data["total_devices_with_snapshot"] == 0
    assert data["devices"] == []


def test_devices_ecosystem_reflects_absorbed_snapshot(client):
    absorb_device_state_snapshot("route_test_dev", {
        "model_ready": True,
        "local_loop_ready": True,
        "llama_cpp_available": True,
        "model_id": "mobilevlm_v2_7b",
    })
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    assert data["total_devices_with_snapshot"] == 1
    assert data["local_ai_ready_count"] == 1
    device = data["devices"][0]
    assert device["device_id"] == "route_test_dev"
    assert device["model"]["model_id"] == "mobilevlm_v2_7b"


def test_devices_ecosystem_has_counts(client):
    absorb_device_state_snapshot("eco_r1", {"model_ready": True, "accessibility_ready": True})
    absorb_device_state_snapshot("eco_r2", {"model_ready": False, "accessibility_ready": False})
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    assert data["model_ready_count"] == 1
    assert data["accessibility_ready_count"] == 1


def test_devices_ecosystem_has_runtime_visible_authority_source_fingerprint(client):
    absorb_device_state_snapshot("eco_fp_01", {"model_ready": True})
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    fingerprint = data.get("authority_source_fingerprint")
    assert isinstance(fingerprint, dict)
    assert fingerprint.get("surface_path") == "/api/v1/operator/devices/ecosystem"
    assert fingerprint.get("primary_source_kind") == "runtime_visible_state"
    assert fingerprint.get("primary_source_kind") != "canonical_truth"
    assert fingerprint.get("consumption_only") is True
    assert fingerprint.get("acts_as_authority_layer") is False


# ---------------------------------------------------------------------------
# GET /api/v1/operator/devices/ecosystem/{device_id}
# ---------------------------------------------------------------------------


def test_device_ecosystem_single_404_when_missing(client):
    resp = client.get("/api/v1/operator/devices/ecosystem/no_such_device")
    assert resp.status_code == 404


def test_device_ecosystem_single_200_when_present(client):
    absorb_device_state_snapshot("single_dev", {"model_ready": True})
    resp = client.get("/api/v1/operator/devices/ecosystem/single_dev")
    assert resp.status_code == 200


def test_device_ecosystem_single_has_snapshot_fields(client):
    absorb_device_state_snapshot("field_dev", {
        "model_ready": True,
        "llama_cpp_available": True,
        "model_id": "mobilevlm_v2",
        "offline_queue_depth": 2,
    })
    data = client.get("/api/v1/operator/devices/ecosystem/field_dev").json()
    assert data["device_id"] == "field_dev"
    assert data["model_ready"] is True
    assert data["llama_cpp_available"] is True
    assert data["model_id"] == "mobilevlm_v2"
    assert data["offline_queue_depth"] == 2


def test_device_ecosystem_single_has_runtime_visible_authority_source_fingerprint(client):
    absorb_device_state_snapshot("field_fp_dev", {"model_ready": True})
    data = client.get("/api/v1/operator/devices/ecosystem/field_fp_dev").json()
    fingerprint = data.get("authority_source_fingerprint")
    assert isinstance(fingerprint, dict)
    assert fingerprint.get("surface_path") == "/api/v1/operator/devices/ecosystem/{device_id}"
    assert fingerprint.get("primary_source_kind") == "runtime_visible_state"
    assert fingerprint.get("primary_source_kind") != "canonical_truth"
    freshness = fingerprint.get("source_freshness")
    assert isinstance(freshness, dict)
    assert freshness.get("device_id") == "field_fp_dev"


# ---------------------------------------------------------------------------
# Existing snapshot endpoint still works
# ---------------------------------------------------------------------------


def test_operator_snapshot_still_works(client):
    resp = client.get("/api/v1/operator/snapshot")
    assert resp.status_code == 200
    assert "governance_state" in resp.json()
    assert "mesh_runtime_state" in resp.json()


# ---------------------------------------------------------------------------
# Existing inspect/flow still works
# ---------------------------------------------------------------------------


def test_inspect_flow_unknown_returns_404(client):
    resp = client.get("/api/v1/operator/inspect/flow/nonexistent_id")
    assert resp.status_code == 404
