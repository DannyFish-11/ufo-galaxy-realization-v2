#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr04_v2_control_plane_coherence.py
==============================================
PR-4 V2 — Unified Control-Plane Truth Surface coherence regression tests.

Validates that the three primary operator surfaces maintain clear,
non-overlapping responsibilities and internally consistent state:

  operator snapshot  = global system overview (count-level summaries only)
  ecosystem          = device/runtime-state truth (full per-device detail)
  flow projections   = execution/process truth (per-flow canonical state)

Coverage
--------
  1.  Snapshot android_ecosystem does NOT include per-device ``devices`` list.
  2.  Snapshot android_ecosystem count keys match ANDROID_ECOSYSTEM_SNAPSHOT_KEYS.
  3.  Ecosystem route returns full per-device ``devices`` list.
  4.  Snapshot count totals agree with ecosystem route totals after absorption.
  5.  Snapshot has ``active_flow_count`` field in to_dict() output.
  6.  Snapshot active_flow_count is 0 when no flows registered.
  7.  FlowOperatorProjection.to_dict() carries ``_authority`` key.
  8.  FlowOperatorProjection ``_authority`` equals FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY.
  9.  GET /api/v1/operator/flows response carries ``authority`` key.
  10. Snapshot to_dict() is fully JSON-serialisable after device absorption.
  11. Ecosystem route has ``authority`` key.
  12. Snapshot android_ecosystem key set equals ANDROID_ECOSYSTEM_SNAPSHOT_KEYS.
  13. Execution-events route has ``authority`` key.
  14. Single-device ecosystem route response has ``_source`` field from store.
  15. Snapshot active_flow_count is an integer.
  16. Snapshot active_flow_count reflects actual active delegated flows.
"""

from __future__ import annotations

import json
import sys
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.android_device_state_store import (
    absorb_device_state_snapshot,
    reset_android_device_state_store,
)
from core.flow_level_operator_surface import (
    FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY,
    FlowOperatorProjection,
)
from core.operator_surface import (
    ANDROID_ECOSYSTEM_SNAPSHOT_KEYS,
    get_operator_surface,
    reset_operator_surface,
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
def _reset():
    reset_android_device_state_store()
    reset_operator_surface()
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass
    yield
    reset_android_device_state_store()
    reset_operator_surface()
    try:
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _absorb_two_devices():
    absorb_device_state_snapshot("dev_alpha", {
        "model_ready": True,
        "local_loop_ready": True,
        "llama_cpp_available": True,
        "accessibility_ready": True,
        "overlay_ready": True,
        "model_id": "mobilevlm_v2_7b",
        "offline_queue_depth": 3,
    })
    absorb_device_state_snapshot("dev_beta", {
        "model_ready": False,
        "local_loop_ready": False,
        "llama_cpp_available": False,
        "model_id": "mobilevlm_lite",
        "offline_queue_depth": 0,
    })


# ===========================================================================
# 1-4: Snapshot android_ecosystem is compact (no devices list)
# ===========================================================================


def test_01_snapshot_android_ecosystem_no_devices_key():
    """Snapshot android_ecosystem must NOT contain the per-device 'devices' list.

    The snapshot is the global overview surface — per-device detail is owned
    by GET /api/v1/operator/devices/ecosystem.
    """
    _absorb_two_devices()
    snap = get_operator_surface().operator_snapshot()
    assert "devices" not in snap.android_ecosystem, (
        "android_ecosystem on snapshot must not include per-device 'devices' list; "
        "that detail belongs to the ecosystem route."
    )


def test_02_snapshot_android_ecosystem_has_count_keys():
    """Snapshot android_ecosystem carries exactly the ANDROID_ECOSYSTEM_SNAPSHOT_KEYS."""
    _absorb_two_devices()
    snap = get_operator_surface().operator_snapshot()
    eco = snap.android_ecosystem
    for key in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS:
        assert key in eco, f"Expected count key '{key}' missing from snapshot android_ecosystem"


def test_03_ecosystem_route_has_devices_list(client):
    """Ecosystem route must return the full per-device 'devices' list."""
    _absorb_two_devices()
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    assert "devices" in data, "Ecosystem route must include 'devices' per-device list"
    assert isinstance(data["devices"], list)
    assert len(data["devices"]) == 2


def test_04_snapshot_ecosystem_counts_agree_with_ecosystem_route(client):
    """Snapshot android_ecosystem count totals must agree with the ecosystem route.

    Both surfaces read from the same android_device_state_store; their
    aggregate numbers must be identical.
    """
    _absorb_two_devices()
    snap_data = client.get("/api/v1/operator/snapshot").json()
    eco_data = client.get("/api/v1/operator/devices/ecosystem").json()

    snap_eco = snap_data.get("android_ecosystem", {})

    assert snap_eco.get("total_devices_with_snapshot") == eco_data.get("total_devices_with_snapshot"), (
        "total_devices_with_snapshot must agree between snapshot and ecosystem route"
    )
    assert snap_eco.get("model_ready_count") == eco_data.get("model_ready_count"), (
        "model_ready_count must agree between snapshot and ecosystem route"
    )
    assert snap_eco.get("local_ai_ready_count") == eco_data.get("local_ai_ready_count"), (
        "local_ai_ready_count must agree between snapshot and ecosystem route"
    )


# ===========================================================================
# 5-6: Snapshot has active_flow_count
# ===========================================================================


def test_05_snapshot_to_dict_has_active_flow_count():
    """Snapshot to_dict() output must include the 'active_flow_count' key."""
    snap = get_operator_surface().operator_snapshot()
    d = snap.to_dict()
    assert "active_flow_count" in d, (
        "OperatorSnapshot.to_dict() must include 'active_flow_count'"
    )


def test_06_snapshot_active_flow_count_zero_when_no_flows():
    """Snapshot active_flow_count must be 0 when no delegated flows registered."""
    snap = get_operator_surface().operator_snapshot()
    assert snap.active_flow_count == 0


# ===========================================================================
# 7-8: FlowOperatorProjection carries _authority
# ===========================================================================


def test_07_flow_projection_to_dict_has_authority_key():
    """FlowOperatorProjection.to_dict() must carry '_authority' key."""
    proj = FlowOperatorProjection(flow_id="test_flow_01")
    d = proj.to_dict()
    assert "_authority" in d, (
        "FlowOperatorProjection.to_dict() must include '_authority' provenance key"
    )


def test_08_flow_projection_authority_matches_sentinel():
    """FlowOperatorProjection '_authority' must equal FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY."""
    proj = FlowOperatorProjection(flow_id="test_flow_02")
    d = proj.to_dict()
    assert d["_authority"] == FLOW_LEVEL_OPERATOR_SURFACE_AUTHORITY


# ===========================================================================
# 9: list_flows route carries authority
# ===========================================================================


def test_09_list_flows_response_has_authority(client):
    """GET /api/v1/operator/flows response must include 'authority' key."""
    data = client.get("/api/v1/operator/flows").json()
    assert "authority" in data, (
        "GET /api/v1/operator/flows must include 'authority' key in response"
    )
    assert data["authority"] == "OPERATOR_ROUTES_V1"


# ===========================================================================
# 10: Snapshot is fully JSON-serialisable after device absorption
# ===========================================================================


def test_10_snapshot_json_serialisable_with_devices(client):
    """Snapshot endpoint must return JSON-serialisable output after device absorption."""
    _absorb_two_devices()
    resp = client.get("/api/v1/operator/snapshot")
    assert resp.status_code == 200
    data = resp.json()
    # Re-serialise to confirm the response is fully clean
    json.dumps(data)  # must not raise
    assert "android_ecosystem" in data
    assert "devices" not in data.get("android_ecosystem", {}), (
        "Snapshot android_ecosystem must not include 'devices' list"
    )


# ===========================================================================
# 11-12: Ecosystem route has authority; snapshot keys align
# ===========================================================================


def test_11_ecosystem_route_has_authority_key(client):
    """GET /api/v1/operator/devices/ecosystem must include 'authority' key."""
    data = client.get("/api/v1/operator/devices/ecosystem").json()
    assert "authority" in data


def test_12_snapshot_android_ecosystem_key_set_equals_whitelist(client):
    """Snapshot android_ecosystem key set must equal ANDROID_ECOSYSTEM_SNAPSHOT_KEYS.

    The whitelist in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS defines exactly which
    count-level keys the snapshot carries — no more, no less.
    """
    _absorb_two_devices()
    snap_data = client.get("/api/v1/operator/snapshot").json()
    snap_eco_keys = set(snap_data.get("android_ecosystem", {}).keys())

    assert snap_eco_keys == ANDROID_ECOSYSTEM_SNAPSHOT_KEYS, (
        f"Snapshot android_ecosystem keys {snap_eco_keys} must equal "
        f"ANDROID_ECOSYSTEM_SNAPSHOT_KEYS {ANDROID_ECOSYSTEM_SNAPSHOT_KEYS}"
    )
    assert "devices" not in snap_eco_keys


# ===========================================================================
# 13: Execution-events route has authority
# ===========================================================================


def test_13_execution_events_route_has_authority(client):
    """GET /api/v1/operator/devices/execution-events must include 'authority' key."""
    data = client.get("/api/v1/operator/devices/execution-events").json()
    assert "authority" in data


# ===========================================================================
# 14: Single-device ecosystem route has _source from store
# ===========================================================================


def test_14_single_device_ecosystem_has_source_field(client):
    """GET /api/v1/operator/devices/ecosystem/{device_id} must include '_source' from store."""
    absorb_device_state_snapshot("coherence_dev", {"model_ready": True})
    data = client.get("/api/v1/operator/devices/ecosystem/coherence_dev").json()
    assert "_source" in data, (
        "Single-device ecosystem response must include '_source' provenance from DeviceStateSnapshot"
    )
    assert data["_source"] == "android_device_state_store"


# ===========================================================================
# 15: Snapshot active_flow_count type check
# ===========================================================================


def test_15_snapshot_active_flow_count_is_int():
    """Snapshot active_flow_count must be an integer (not None or other type)."""
    snap = get_operator_surface().operator_snapshot()
    assert isinstance(snap.active_flow_count, int), (
        "OperatorSnapshot.active_flow_count must be an int"
    )
    assert isinstance(snap.to_dict()["active_flow_count"], int)


# ===========================================================================
# 16: Snapshot active_flow_count reflects actual active flows
# ===========================================================================


def test_16_snapshot_active_flow_count_reflects_registered_flows():
    """Snapshot active_flow_count must reflect the count of active delegated flows.

    Registers two fresh delegated flows (both start in 'created' phase,
    which is_active()), then asserts the snapshot count increases to 2.
    """
    from core.delegated_flow_entity import (
        create_delegated_flow_entity,
        record_delegated_flow,
        DelegatedFlowKind,
    )

    before = get_operator_surface().operator_snapshot()
    assert before.active_flow_count == 0

    entity_a = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.task_assign,
        canonical_task_id="snap_flow_test_a",
    )
    record_delegated_flow(entity_a)

    entity_b = create_delegated_flow_entity(
        flow_kind=DelegatedFlowKind.task_assign,
        canonical_task_id="snap_flow_test_b",
    )
    record_delegated_flow(entity_b)

    after = get_operator_surface().operator_snapshot()
    assert after.active_flow_count == 2, (
        f"Expected active_flow_count=2 after registering 2 flows, got {after.active_flow_count}"
    )
