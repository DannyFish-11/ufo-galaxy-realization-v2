"""
tests/test_pr5_v2_operator_observability.py
============================================
PR-5 V2: Operator-facing observability / diagnosability improvements.

Validates the new fields and behaviours added to improve Android→V2
control-plane diagnosis without introducing a parallel observability system.

Sections
--------
A.  DeviceStateSnapshot.to_dict() now includes ``snapshot_age_seconds``.
B.  get_ecosystem_summary() now includes ``snapshot_truth_received`` and
    ``last_snapshot_absorbed_at``, plus per-device ``snapshot_age_seconds``.
C.  OperatorSnapshot includes ``android_snapshot_truth_received`` and
    android_ecosystem carries the new freshness keys.
D.  GET /api/v1/operator/devices/execution-events includes ``last_event_at``.
E.  FlowOperatorProjection includes ``last_execution_event_at``.
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import (
    absorb_device_state_snapshot,
    absorb_device_execution_event,
    get_device_state_snapshot,
    get_device_ecosystem_summary,
    reset_android_device_state_store,
)
from core.routes.operator import create_router


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    _app = FastAPI()
    _app.include_router(create_router())
    return _app


@pytest.fixture(scope="module")
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset():
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


# ---------------------------------------------------------------------------
# A. DeviceStateSnapshot.to_dict() — snapshot_age_seconds
# ---------------------------------------------------------------------------


class TestDeviceStateSnapshotAgeSeconds:
    def test_A01_to_dict_contains_snapshot_age_seconds(self):
        absorb_device_state_snapshot("age_dev_01", {"model_ready": True})
        snap = get_device_state_snapshot("age_dev_01")
        assert snap is not None
        d = snap.to_dict()
        assert "snapshot_age_seconds" in d

    def test_A02_snapshot_age_seconds_is_non_negative(self):
        absorb_device_state_snapshot("age_dev_02", {"model_ready": True})
        snap = get_device_state_snapshot("age_dev_02")
        d = snap.to_dict()
        assert d["snapshot_age_seconds"] >= 0.0

    def test_A03_snapshot_age_seconds_is_numeric(self):
        absorb_device_state_snapshot("age_dev_03", {})
        snap = get_device_state_snapshot("age_dev_03")
        d = snap.to_dict()
        assert isinstance(d["snapshot_age_seconds"], (int, float))

    def test_A04_snapshot_age_seconds_increases_over_time(self):
        absorb_device_state_snapshot("age_dev_04", {})
        snap = get_device_state_snapshot("age_dev_04")
        age_first = snap.to_dict()["snapshot_age_seconds"]
        time.sleep(0.05)
        age_second = snap.to_dict()["snapshot_age_seconds"]
        assert age_second >= age_first

    def test_A05_source_field_still_present(self):
        absorb_device_state_snapshot("age_dev_05", {})
        snap = get_device_state_snapshot("age_dev_05")
        d = snap.to_dict()
        assert d.get("_source") == "android_device_state_store"


# ---------------------------------------------------------------------------
# B. get_ecosystem_summary() — freshness fields
# ---------------------------------------------------------------------------


class TestEcosystemSummaryFreshnessFields:
    def test_B01_snapshot_truth_received_false_when_empty(self):
        eco = get_device_ecosystem_summary()
        assert eco["snapshot_truth_received"] is False

    def test_B02_last_snapshot_absorbed_at_none_when_empty(self):
        eco = get_device_ecosystem_summary()
        assert eco["last_snapshot_absorbed_at"] is None

    def test_B03_snapshot_truth_received_true_after_absorb(self):
        absorb_device_state_snapshot("eco_fresh_01", {"model_ready": True})
        eco = get_device_ecosystem_summary()
        assert eco["snapshot_truth_received"] is True

    def test_B04_last_snapshot_absorbed_at_is_float_after_absorb(self):
        absorb_device_state_snapshot("eco_fresh_02", {})
        eco = get_device_ecosystem_summary()
        assert isinstance(eco["last_snapshot_absorbed_at"], float)

    def test_B05_last_snapshot_absorbed_at_is_recent(self):
        absorb_device_state_snapshot("eco_fresh_03", {})
        before = time.time()
        eco = get_device_ecosystem_summary()
        assert eco["last_snapshot_absorbed_at"] <= before + 1.0

    def test_B06_last_snapshot_absorbed_at_reflects_most_recent_device(self):
        absorb_device_state_snapshot("eco_fresh_04a", {})
        time.sleep(0.02)
        absorb_device_state_snapshot("eco_fresh_04b", {})
        eco = get_device_ecosystem_summary()
        snap_a = get_device_state_snapshot("eco_fresh_04a")
        snap_b = get_device_state_snapshot("eco_fresh_04b")
        assert eco["last_snapshot_absorbed_at"] >= snap_a.absorbed_at
        assert eco["last_snapshot_absorbed_at"] == snap_b.absorbed_at

    def test_B07_per_device_entry_has_snapshot_age_seconds(self):
        absorb_device_state_snapshot("eco_fresh_05", {"model_ready": True})
        eco = get_device_ecosystem_summary()
        device = eco["devices"][0]
        assert "snapshot_age_seconds" in device

    def test_B08_per_device_snapshot_age_seconds_is_non_negative(self):
        absorb_device_state_snapshot("eco_fresh_06", {})
        eco = get_device_ecosystem_summary()
        for dev in eco["devices"]:
            assert dev["snapshot_age_seconds"] >= 0.0

    def test_B09_devices_key_still_present(self):
        eco = get_device_ecosystem_summary()
        assert "devices" in eco

    def test_B10_existing_count_keys_still_present(self):
        absorb_device_state_snapshot("eco_fresh_07", {"model_ready": True})
        eco = get_device_ecosystem_summary()
        for key in (
            "total_devices_with_snapshot",
            "local_ai_ready_count",
            "model_ready_count",
            "accessibility_ready_count",
            "overlay_ready_count",
            "local_loop_ready_count",
            "pending_first_download_count",
        ):
            assert key in eco, f"missing key: {key}"


# ---------------------------------------------------------------------------
# C. OperatorSnapshot — android_snapshot_truth_received + freshness in ecosystem
# ---------------------------------------------------------------------------


class TestOperatorSnapshotFreshnessFields:
    def test_C01_android_snapshot_truth_received_false_when_no_snapshots(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        assert snap.android_snapshot_truth_received is False

    def test_C02_android_snapshot_truth_received_true_after_absorb(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        absorb_device_state_snapshot("ops_fresh_01", {"model_ready": True})
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        assert snap.android_snapshot_truth_received is True

    def test_C03_to_dict_includes_android_snapshot_truth_received(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        d = get_operator_surface().operator_snapshot().to_dict()
        assert "android_snapshot_truth_received" in d

    def test_C04_android_ecosystem_has_snapshot_truth_received_key(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        absorb_device_state_snapshot("ops_fresh_02", {})
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        assert "snapshot_truth_received" in snap.android_ecosystem

    def test_C05_android_ecosystem_has_last_snapshot_absorbed_at_key(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        absorb_device_state_snapshot("ops_fresh_03", {})
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        assert "last_snapshot_absorbed_at" in snap.android_ecosystem

    def test_C06_android_ecosystem_last_snapshot_absorbed_at_is_none_when_empty(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        assert snap.android_ecosystem.get("last_snapshot_absorbed_at") is None

    def test_C07_android_ecosystem_last_snapshot_absorbed_at_is_float_after_absorb(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        absorb_device_state_snapshot("ops_fresh_04", {})
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        val = snap.android_ecosystem.get("last_snapshot_absorbed_at")
        assert isinstance(val, float)

    def test_C08_to_dict_android_snapshot_truth_received_consistent_with_field(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface
        absorb_device_state_snapshot("ops_fresh_05", {"model_ready": True})
        reset_operator_surface()
        snap = get_operator_surface().operator_snapshot()
        d = snap.to_dict()
        assert d["android_snapshot_truth_received"] == snap.android_snapshot_truth_received

    def test_C09_existing_android_ecosystem_count_keys_still_whitelisted(self):
        from core.operator_surface import get_operator_surface, reset_operator_surface, ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        existing_keys = {
            "total_devices_with_snapshot",
            "local_ai_ready_count",
            "model_ready_count",
            "accessibility_ready_count",
            "overlay_ready_count",
            "local_loop_ready_count",
            "pending_first_download_count",
        }
        assert existing_keys <= ANDROID_ECOSYSTEM_SNAPSHOT_KEYS


# ---------------------------------------------------------------------------
# D. GET /api/v1/operator/devices/execution-events — last_event_at
# ---------------------------------------------------------------------------


class TestExecutionEventsRouteLastEventAt:
    def test_D01_execution_events_response_has_last_event_at_key(self, client):
        resp = client.get("/api/v1/operator/devices/execution-events")
        assert resp.status_code == 200
        assert "last_event_at" in resp.json()

    def test_D02_last_event_at_is_none_when_no_events(self, client):
        data = client.get("/api/v1/operator/devices/execution-events").json()
        assert data["last_event_at"] is None

    def test_D03_last_event_at_is_float_after_absorb(self, client):
        absorb_device_execution_event("exec_dev_01", {
            "flow_id": "flow_exec_01",
            "phase": "planning",
        })
        data = client.get("/api/v1/operator/devices/execution-events").json()
        assert isinstance(data["last_event_at"], float)

    def test_D04_last_event_at_matches_most_recent_event_absorbed_at(self, client):
        absorb_device_execution_event("exec_dev_02", {
            "flow_id": "flow_exec_02",
            "phase": "grounding",
        })
        data = client.get("/api/v1/operator/devices/execution-events").json()
        events = data["events"]
        assert events, "expected at least one event"
        # events are returned newest-first; first element is most recent
        assert data["last_event_at"] == events[0]["absorbed_at"]

    def test_D05_existing_total_events_key_still_present(self, client):
        data = client.get("/api/v1/operator/devices/execution-events").json()
        assert "total_events" in data

    def test_D06_existing_events_list_still_present(self, client):
        data = client.get("/api/v1/operator/devices/execution-events").json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_D07_last_event_at_is_none_when_filter_matches_nothing(self, client):
        absorb_device_execution_event("exec_dev_03", {
            "flow_id": "flow_exec_03",
            "phase": "execution",
        })
        data = client.get(
            "/api/v1/operator/devices/execution-events",
            params={"flow_id": "nonexistent_flow_id"},
        ).json()
        assert data["last_event_at"] is None
        assert data["total_events"] == 0

    def test_D08_ecosystem_route_device_entry_has_snapshot_age_seconds(self, client):
        absorb_device_state_snapshot("eco_route_01", {"model_ready": True})
        data = client.get("/api/v1/operator/devices/ecosystem").json()
        assert data["devices"]
        for dev in data["devices"]:
            assert "snapshot_age_seconds" in dev

    def test_D09_ecosystem_route_has_snapshot_truth_received(self, client):
        absorb_device_state_snapshot("eco_route_02", {})
        data = client.get("/api/v1/operator/devices/ecosystem").json()
        assert "snapshot_truth_received" in data

    def test_D10_ecosystem_route_has_last_snapshot_absorbed_at(self, client):
        absorb_device_state_snapshot("eco_route_03", {})
        data = client.get("/api/v1/operator/devices/ecosystem").json()
        assert "last_snapshot_absorbed_at" in data

    def test_D11_single_device_route_has_snapshot_age_seconds(self, client):
        absorb_device_state_snapshot("eco_single_01", {"model_ready": True})
        data = client.get("/api/v1/operator/devices/ecosystem/eco_single_01").json()
        assert "snapshot_age_seconds" in data


# ---------------------------------------------------------------------------
# E. FlowOperatorProjection — last_execution_event_at
# ---------------------------------------------------------------------------


class TestFlowOperatorProjectionLastExecutionEventAt:
    def test_E01_projection_to_dict_has_last_execution_event_at_key(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        proj = FlowOperatorProjection(flow_id="test_flow")
        d = proj.to_dict()
        assert "last_execution_event_at" in d

    def test_E02_last_execution_event_at_is_none_when_no_event(self):
        from core.flow_level_operator_surface import FlowOperatorProjection
        proj = FlowOperatorProjection(flow_id="test_flow_no_event")
        assert proj.last_execution_event_at is None
        assert proj.to_dict()["last_execution_event_at"] is None

    def test_E03_last_execution_event_at_populated_when_event_present(self):
        from core.flow_level_operator_surface import (
            FlowOperatorProjection,
            AndroidCanonicalExecutionEvent,
            AndroidExecutionPhase,
        )
        ts = time.time()
        event = AndroidCanonicalExecutionEvent(
            flow_id="test_flow_ev",
            phase=AndroidExecutionPhase.planning,
            absorbed_at=ts,
        )
        proj = FlowOperatorProjection(
            flow_id="test_flow_ev",
            last_android_execution_event=event,
            last_execution_event_at=ts,
        )
        assert proj.last_execution_event_at == ts
        assert proj.to_dict()["last_execution_event_at"] == ts

    def test_E04_inspect_flow_returns_last_execution_event_at_from_event(self):
        """inspect_flow() sets last_execution_event_at when an execution event exists."""
        from core.flow_level_operator_surface import (
            get_flow_level_operator_surface,
            reset_flow_level_operator_surface,
        )
        from unittest.mock import MagicMock, patch

        flow_id = "pr5_test_flow_ev_at"
        reset_flow_level_operator_surface()

        ts = time.time() - 5.0

        # Build a minimal mock entity that the surface can load
        mock_identity = MagicMock()
        mock_identity.delegated_flow_id = flow_id
        mock_identity.flow_lineage_id = ""
        mock_identity.flow_segment_id = ""
        mock_identity.trace_id = ""
        mock_identity.flow_kind = MagicMock(value="task_assign")

        mock_phase = MagicMock()
        mock_phase.value = "active"
        mock_phase.is_active.return_value = True

        mock_object_mapping = MagicMock()
        mock_object_mapping.canonical_task_id = ""
        mock_object_mapping.dispatch_record_id = ""
        mock_object_mapping.contract_id = ""
        mock_object_mapping.binding_id = ""
        mock_object_mapping.device_id = "pr5_dev"
        mock_object_mapping.android_flow_id = ""

        mock_entity = MagicMock()
        mock_entity.identity = mock_identity
        mock_entity.phase = mock_phase
        mock_entity.object_mapping = mock_object_mapping
        mock_entity.created_at = ts - 10.0
        mock_entity.last_updated_at = ts - 2.0
        mock_entity.metadata = {
            "_last_android_execution_event": {
                "event_id": "ace_test_pr5",
                "flow_id": flow_id,
                "phase": "planning",
                "step_index": 0,
                "detail": "test",
                "is_blocking": False,
                "blocking_reason": "",
                "policy_gate": "",
                "absorbed_at": ts,
                "android_ts": None,
                "evidence": {},
            },
            "_last_android_phase": "planning",
            "_last_android_event_absorbed_at": ts,
        }

        mock_runtime = MagicMock()
        mock_runtime.get.return_value = mock_entity

        with (
            patch(
                "core.flow_level_operator_surface.FlowLevelOperatorSurface._load_flow_entity",
                return_value=mock_entity,
            ),
            patch(
                "core.delegated_flow_entity.get_delegated_flow_entity_runtime",
                return_value=mock_runtime,
            ),
        ):
            surface = get_flow_level_operator_surface()
            proj = surface.inspect_flow(flow_id)

        assert proj is not None
        assert proj.last_execution_event_at is not None
        assert abs(proj.last_execution_event_at - ts) < 0.5
        # Confirm it is also present in to_dict()
        d = proj.to_dict()
        assert d["last_execution_event_at"] is not None
        assert abs(d["last_execution_event_at"] - ts) < 0.5

    def test_E05_inspect_flow_last_execution_event_at_none_when_no_events(self):
        """inspect_flow() leaves last_execution_event_at as None when no event exists."""
        from core.flow_level_operator_surface import (
            get_flow_level_operator_surface,
            reset_flow_level_operator_surface,
        )
        from unittest.mock import MagicMock, patch

        flow_id = "pr5_test_flow_no_ev"
        reset_flow_level_operator_surface()

        mock_identity = MagicMock()
        mock_identity.delegated_flow_id = flow_id
        mock_identity.flow_lineage_id = ""
        mock_identity.flow_segment_id = ""
        mock_identity.trace_id = ""
        mock_identity.flow_kind = MagicMock(value="task_assign")

        mock_phase = MagicMock()
        mock_phase.value = "active"

        mock_object_mapping = MagicMock()
        mock_object_mapping.canonical_task_id = ""
        mock_object_mapping.dispatch_record_id = ""
        mock_object_mapping.contract_id = ""
        mock_object_mapping.binding_id = ""
        mock_object_mapping.device_id = "pr5_dev_noev"
        mock_object_mapping.android_flow_id = ""

        mock_entity = MagicMock()
        mock_entity.identity = mock_identity
        mock_entity.phase = mock_phase
        mock_entity.object_mapping = mock_object_mapping
        mock_entity.created_at = time.time() - 20.0
        mock_entity.last_updated_at = time.time() - 5.0
        # No execution event in metadata
        mock_entity.metadata = {}

        with patch(
            "core.flow_level_operator_surface.FlowLevelOperatorSurface._load_flow_entity",
            return_value=mock_entity,
        ):
            surface = get_flow_level_operator_surface()
            proj = surface.inspect_flow(flow_id)

        assert proj is not None
        assert proj.last_execution_event_at is None
        assert proj.to_dict()["last_execution_event_at"] is None
