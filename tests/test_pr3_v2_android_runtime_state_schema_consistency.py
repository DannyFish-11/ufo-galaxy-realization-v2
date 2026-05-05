"""tests/test_pr3_v2_android_runtime_state_schema_consistency.py
================================================================
PR-3 V2 companion: Canonical Android runtime-state schema consistency
regression tests.

Proves schema consistency across the V2 receive/store/expose path for
realistic Android-originated data.

All assertions are grounded strictly in the current real implementation of:
  - ``core.android_device_state_store``
  - ``core.routes.operator``
  - ``core.operator_surface``

Test sections
-------------
A.  ``snapshot_ts`` parser accepts camelCase ``snapshotTs`` key in addition
    to ``snapshot_ts`` and ``timestamp``.

B.  ``DeviceStateSnapshot.to_dict()`` exposes ``_source`` provenance field
    consistent with operator-projection convention.

C.  ``get_ecosystem_summary()`` per-device ``model`` sub-dict exposes
    ``mobilevlm_present``, ``mobilevlm_checksum_ok``, ``seeclick_present``
    — fields present in ``to_dict()`` but previously absent from the
    ecosystem model view.

D.  ``get_ecosystem_summary()`` per-device entry exposes
    ``runtime_health_snapshot`` — field present in store and ``to_dict()``
    but previously absent from the ecosystem per-device view.

E.  Cross-path consistency: fields set in snapshot are visible in
    ``to_dict()``, in ecosystem per-device entry, and (for readiness
    fields) in ``readiness_summary()``.

F.  Module-level ``list_recent_execution_events()`` convenience wrapper
    exists and is functionally equivalent to the store method.

G.  ``GET /api/v1/operator/devices/ecosystem/{device_id}`` response
    includes ``authority`` annotation consistent with the multi-device
    and execution-events endpoints.

H.  ``GET /api/v1/operator/devices/ecosystem`` and
    ``GET /api/v1/operator/devices/ecosystem/{device_id}`` expose
    consistent ``model`` sub-dict fields for the same device.

I.  Realistic full Android camelCase snapshot payload (including
    ``snapshotTs``) is absorbed and all schema-consistency fields are
    visible through both ``to_dict()`` and ``get_ecosystem_summary()``.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import (
    absorb_device_state_snapshot,
    absorb_device_execution_event,
    get_device_ecosystem_summary,
    get_device_state_snapshot,
    list_recent_execution_events,
    reset_android_device_state_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the singleton before and after each test."""
    reset_android_device_state_store()
    yield
    reset_android_device_state_store()


def _make_router_app() -> FastAPI:
    """Build a minimal FastAPI app mounting only the operator router."""
    from core.routes.operator import create_router
    app = FastAPI()
    app.include_router(create_router())
    return app


# ---------------------------------------------------------------------------
# A. snapshot_ts camelCase alias
# ---------------------------------------------------------------------------


class TestSnapshotTsCamelCaseAlias:
    def test_A01_snapshotTs_key_is_absorbed(self):
        """snapshotTs (camelCase) must be accepted as snapshot_ts."""
        snap = absorb_device_state_snapshot("ts_dev_01", {"snapshotTs": 1_700_000_000.0})
        assert snap.snapshot_ts == 1_700_000_000.0

    def test_A02_snapshot_ts_snake_case_still_works(self):
        snap = absorb_device_state_snapshot("ts_dev_02", {"snapshot_ts": 1_700_111_111.0})
        assert snap.snapshot_ts == 1_700_111_111.0

    def test_A03_timestamp_fallback_still_works(self):
        snap = absorb_device_state_snapshot("ts_dev_03", {"timestamp": 1_700_222_222.0})
        assert snap.snapshot_ts == 1_700_222_222.0

    def test_A04_snapshotTs_visible_in_to_dict(self):
        snap = absorb_device_state_snapshot("ts_dev_04", {"snapshotTs": 1_700_333_333.0})
        assert snap.to_dict()["snapshot_ts"] == 1_700_333_333.0

    def test_A05_snapshotTs_visible_in_ecosystem_per_device(self):
        absorb_device_state_snapshot("ts_dev_05", {"snapshotTs": 1_700_444_444.0})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "ts_dev_05")
        assert dev["snapshot_ts"] == 1_700_444_444.0

    def test_A06_snake_takes_priority_over_camelCase(self):
        """When both snake_case and camelCase are present, snake_case wins."""
        snap = absorb_device_state_snapshot(
            "ts_dev_06",
            {"snapshot_ts": 1_111_000.0, "snapshotTs": 2_222_000.0},
        )
        assert snap.snapshot_ts == 1_111_000.0

    def test_A07_snapshotTs_absent_yields_none(self):
        snap = absorb_device_state_snapshot("ts_dev_07", {})
        assert snap.snapshot_ts is None


# ---------------------------------------------------------------------------
# B. _source in DeviceStateSnapshot.to_dict()
# ---------------------------------------------------------------------------


class TestDeviceStateSnapshotSourceProvenance:
    def test_B01_to_dict_contains_source_field(self):
        snap = absorb_device_state_snapshot("src_dev_01", {})
        d = snap.to_dict()
        assert "_source" in d

    def test_B02_source_identifies_store(self):
        snap = absorb_device_state_snapshot("src_dev_02", {})
        d = snap.to_dict()
        assert d["_source"] == "android_device_state_store"

    def test_B03_source_stable_across_payloads(self):
        snap1 = absorb_device_state_snapshot("src_dev_03a", {"model_ready": True})
        snap2 = absorb_device_state_snapshot("src_dev_03b", {"model_ready": False})
        assert snap1.to_dict()["_source"] == snap2.to_dict()["_source"]


# ---------------------------------------------------------------------------
# C. mobilevlm/seeclick presence fields in ecosystem model sub-dict
# ---------------------------------------------------------------------------


class TestEcosystemModelSubdictPresenceFields:
    def test_C01_mobilevlm_present_in_model_subdict(self):
        absorb_device_state_snapshot("mp_dev_01", {"mobilevlm_present": True})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_01")
        assert "mobilevlm_present" in dev["model"]
        assert dev["model"]["mobilevlm_present"] is True

    def test_C02_mobilevlm_checksum_ok_in_model_subdict(self):
        absorb_device_state_snapshot("mp_dev_02", {"mobilevlm_checksum_ok": True})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_02")
        assert "mobilevlm_checksum_ok" in dev["model"]
        assert dev["model"]["mobilevlm_checksum_ok"] is True

    def test_C03_seeclick_present_in_model_subdict(self):
        absorb_device_state_snapshot("mp_dev_03", {"seeclick_present": False})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_03")
        assert "seeclick_present" in dev["model"]
        assert dev["model"]["seeclick_present"] is False

    def test_C04_camelCase_mobilevlm_fields_surface_in_model_subdict(self):
        absorb_device_state_snapshot(
            "mp_dev_04",
            {"mobilevlmPresent": True, "mobilevlmChecksumOk": False, "seeclickPresent": True},
        )
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_04")
        assert dev["model"]["mobilevlm_present"] is True
        assert dev["model"]["mobilevlm_checksum_ok"] is False
        assert dev["model"]["seeclick_present"] is True

    def test_C05_model_subdict_still_has_existing_fields(self):
        absorb_device_state_snapshot(
            "mp_dev_05",
            {
                "model_id": "mbvlm_7b",
                "runtime_type": "LLAMA_CPP",
                "checksum_ok": True,
                "compatibility_ok": True,
                "quantization": "q4_k_m",
                "model_version": "v2.0",
                "mobilevlm_present": True,
                "mobilevlm_checksum_ok": False,
                "seeclick_present": True,
            },
        )
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_05")
        m = dev["model"]
        expected = {
            "model_id": "mbvlm_7b",
            "runtime_type": "LLAMA_CPP",
            "checksum_ok": True,
            "compatibility_ok": True,
            "quantization": "q4_k_m",
            "model_version": "v2.0",
            "mobilevlm_present": True,
            "mobilevlm_checksum_ok": False,
            "seeclick_present": True,
        }
        for key, expected_value in expected.items():
            assert key in m, f"Missing key in model sub-dict: {key}"
            assert m[key] == expected_value, (
                f"Value mismatch for model sub-dict key {key!r}: "
                f"expected {expected_value!r}, got {m[key]!r}"
            )

    def test_C06_none_values_for_unset_presence_fields(self):
        """Unset presence fields appear as None (not absent) in model sub-dict."""
        absorb_device_state_snapshot("mp_dev_06", {})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "mp_dev_06")
        assert dev["model"]["mobilevlm_present"] is None
        assert dev["model"]["mobilevlm_checksum_ok"] is None
        assert dev["model"]["seeclick_present"] is None


# ---------------------------------------------------------------------------
# D. runtime_health_snapshot in ecosystem per-device entry
# ---------------------------------------------------------------------------


class TestEcosystemRuntimeHealthSnapshot:
    def test_D01_runtime_health_snapshot_key_present_in_ecosystem_entry(self):
        absorb_device_state_snapshot("rh_dev_01", {})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "rh_dev_01")
        assert "runtime_health_snapshot" in dev

    def test_D02_runtime_health_snapshot_none_when_not_provided(self):
        absorb_device_state_snapshot("rh_dev_02", {})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "rh_dev_02")
        assert dev["runtime_health_snapshot"] is None

    def test_D03_runtime_health_snapshot_dict_when_provided(self):
        rhs = {"score": 0.92, "warmup_ok": True, "inference_latency_ms": 320}
        absorb_device_state_snapshot("rh_dev_03", {"runtime_health_snapshot": rhs})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "rh_dev_03")
        assert dev["runtime_health_snapshot"] == rhs

    def test_D04_camelCase_rhs_key_absorbed_and_surfaced(self):
        rhs = {"score": 0.85, "latency_ok": False}
        absorb_device_state_snapshot("rh_dev_04", {"runtimeHealthSnapshot": rhs})
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "rh_dev_04")
        assert dev["runtime_health_snapshot"] == rhs

    def test_D05_runtime_health_consistent_between_to_dict_and_ecosystem(self):
        """runtime_health_snapshot in to_dict() must equal that in ecosystem per-device."""
        rhs = {"score": 0.99}
        absorb_device_state_snapshot("rh_dev_05", {"runtime_health_snapshot": rhs})
        snap = get_device_state_snapshot("rh_dev_05")
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "rh_dev_05")
        assert snap.to_dict()["runtime_health_snapshot"] == dev["runtime_health_snapshot"]


# ---------------------------------------------------------------------------
# E. Cross-path schema consistency
# ---------------------------------------------------------------------------


class TestCrossPathSchemaConsistency:
    """Verify fields set in snapshot are consistently visible across all surfaces."""

    _FULL_PAYLOAD: Dict[str, Any] = {
        "llama_cpp_available": True,
        "ncnn_available": False,
        "active_runtime_type": "LLAMA_CPP",
        "model_ready": True,
        "accessibility_ready": True,
        "overlay_ready": True,
        "local_loop_ready": True,
        "model_id": "mobilevlm_v2_7b",
        "runtime_type": "LLAMA_CPP",
        "checksum_ok": True,
        "compatibility_ok": True,
        "quantization": "q4_k_m",
        "model_version": "v2.0",
        "mobilevlm_present": True,
        "mobilevlm_checksum_ok": True,
        "seeclick_present": False,
        "pending_first_download": False,
        "offline_queue_depth": 1,
        "current_fallback_tier": "local_planner",
        "planner_fallback_tier": "local",
        "grounding_fallback_tier": "center",
        "warmup_result": "ok",
        "degraded_reasons": [],
        "runtime_health_snapshot": {"score": 0.95},
        "snapshotTs": 1_700_500_000.0,
    }

    # Fields that must appear identically in both to_dict() and readiness_summary()
    _READINESS_FIELDS = (
        "model_ready",
        "accessibility_ready",
        "overlay_ready",
        "local_loop_ready",
        "llama_cpp_available",
        "pending_first_download",
    )

    def test_E01_all_high_value_fields_in_to_dict(self):
        snap = absorb_device_state_snapshot("cp_dev_01", self._FULL_PAYLOAD)
        d = snap.to_dict()
        for key in (
            "_source", "device_id", "absorbed_at", "snapshot_ts",
            "llama_cpp_available", "ncnn_available", "active_runtime_type",
            "model_ready", "accessibility_ready", "overlay_ready", "local_loop_ready",
            "model_id", "runtime_type", "checksum_ok", "compatibility_ok",
            "quantization", "model_version",
            "mobilevlm_present", "mobilevlm_checksum_ok", "seeclick_present",
            "pending_first_download",
            "offline_queue_depth", "current_fallback_tier",
            "planner_fallback_tier", "grounding_fallback_tier",
            "warmup_result", "degraded_reasons",
            "runtime_health_snapshot",
        ):
            assert key in d, f"to_dict() missing key: {key}"

    def test_E02_readiness_fields_consistent_to_dict_vs_readiness_summary(self):
        snap = absorb_device_state_snapshot("cp_dev_02", self._FULL_PAYLOAD)
        d = snap.to_dict()
        rs = snap.readiness_summary()
        for key in self._READINESS_FIELDS:
            assert d[key] == rs[key], f"Mismatch for {key}: to_dict={d[key]} readiness_summary={rs[key]}"

    def test_E03_model_fields_consistent_to_dict_vs_ecosystem_model_subdict(self):
        absorb_device_state_snapshot("cp_dev_03", self._FULL_PAYLOAD)
        snap = get_device_state_snapshot("cp_dev_03")
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "cp_dev_03")

        d = snap.to_dict()
        m = dev["model"]
        for key in ("model_id", "runtime_type", "checksum_ok", "compatibility_ok",
                    "quantization", "model_version",
                    "mobilevlm_present", "mobilevlm_checksum_ok", "seeclick_present"):
            assert d[key] == m[key], (
                f"Model field mismatch for {key}: "
                f"to_dict={d[key]} ecosystem_model={m[key]}"
            )

    def test_E04_snapshot_ts_consistent_across_surfaces(self):
        absorb_device_state_snapshot("cp_dev_04", self._FULL_PAYLOAD)
        snap = get_device_state_snapshot("cp_dev_04")
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "cp_dev_04")

        assert snap.to_dict()["snapshot_ts"] == dev["snapshot_ts"]
        assert snap.snapshot_ts == 1_700_500_000.0

    def test_E05_runtime_health_consistent_across_surfaces(self):
        absorb_device_state_snapshot("cp_dev_05", self._FULL_PAYLOAD)
        snap = get_device_state_snapshot("cp_dev_05")
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "cp_dev_05")

        assert snap.to_dict()["runtime_health_snapshot"] == dev["runtime_health_snapshot"]

    def test_E06_fallback_tier_fields_consistent_across_surfaces(self):
        absorb_device_state_snapshot("cp_dev_06", self._FULL_PAYLOAD)
        snap = get_device_state_snapshot("cp_dev_06")
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "cp_dev_06")

        for key in ("current_fallback_tier", "planner_fallback_tier", "grounding_fallback_tier"):
            assert snap.to_dict()[key] == dev[key], (
                f"Fallback tier mismatch for {key}: "
                f"to_dict={snap.to_dict()[key]} ecosystem={dev[key]}"
            )


# ---------------------------------------------------------------------------
# F. Module-level list_recent_execution_events wrapper
# ---------------------------------------------------------------------------


class TestListRecentExecutionEventsModuleWrapper:
    def test_F01_module_level_function_exists(self):
        """list_recent_execution_events must be importable from the module."""
        from core.android_device_state_store import list_recent_execution_events  # noqa: F401

    def test_F02_wrapper_returns_list(self):
        result = list_recent_execution_events()
        assert isinstance(result, list)

    def test_F03_wrapper_returns_absorbed_events(self):
        absorb_device_execution_event("fw_dev_01", {"flow_id": "f1", "phase": "planning"})
        absorb_device_execution_event("fw_dev_01", {"flow_id": "f2", "phase": "grounding"})
        events = list_recent_execution_events()
        assert len(events) >= 2

    def test_F04_wrapper_filter_by_flow_id(self):
        absorb_device_execution_event("fw_dev_02", {"flow_id": "flow_alpha", "phase": "planning"})
        absorb_device_execution_event("fw_dev_02", {"flow_id": "flow_beta", "phase": "execution"})
        events = list_recent_execution_events(flow_id="flow_alpha")
        assert all(e.flow_id == "flow_alpha" for e in events)

    def test_F05_wrapper_filter_by_device_id(self):
        absorb_device_execution_event("fw_dev_03a", {"flow_id": "fx", "phase": "planning"})
        absorb_device_execution_event("fw_dev_03b", {"flow_id": "fy", "phase": "execution"})
        events = list_recent_execution_events(device_id="fw_dev_03a")
        assert all(e.device_id == "fw_dev_03a" for e in events)

    def test_F06_wrapper_respects_limit(self):
        for i in range(10):
            absorb_device_execution_event("fw_dev_04", {"flow_id": f"f{i}", "phase": "planning"})
        events = list_recent_execution_events(limit=3)
        assert len(events) <= 3

    def test_F07_wrapper_equivalent_to_store_method(self):
        """Results from module wrapper must equal results from store method."""
        from core.android_device_state_store import get_android_device_state_store
        absorb_device_execution_event("fw_dev_05", {"flow_id": "f_equiv", "phase": "completed"})
        store_result = get_android_device_state_store().list_recent_execution_events()
        wrapper_result = list_recent_execution_events()
        assert [e.flow_id for e in store_result] == [e.flow_id for e in wrapper_result]


# ---------------------------------------------------------------------------
# G. Authority annotation in per-device route response
# ---------------------------------------------------------------------------


class TestPerDeviceRouteAuthorityAnnotation:
    def test_G01_per_device_route_includes_authority(self):
        absorb_device_state_snapshot("auth_dev_01", {"model_ready": True})
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/auth_dev_01")
        assert resp.status_code == 200
        data = resp.json()
        assert "authority" in data, "Per-device route must include 'authority' annotation"

    def test_G02_per_device_authority_matches_convention(self):
        absorb_device_state_snapshot("auth_dev_02", {"model_ready": False})
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/auth_dev_02")
        assert resp.json()["authority"] == "OPERATOR_ROUTES_V1"

    def test_G03_404_response_still_has_no_authority_collision(self):
        """404 for unknown device does not include authority (consistent non-data response)."""
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/no_such_device_xyzzy")
        assert resp.status_code == 404

    def test_G04_authority_annotation_consistent_with_multi_device_endpoint(self):
        """Both /ecosystem and /ecosystem/{device_id} must use the same authority string."""
        absorb_device_state_snapshot("auth_dev_04", {"model_ready": True})
        app = _make_router_app()
        client = TestClient(app)
        multi = client.get("/api/v1/operator/devices/ecosystem")
        per_dev = client.get("/api/v1/operator/devices/ecosystem/auth_dev_04")
        assert multi.json()["authority"] == per_dev.json()["authority"] == "OPERATOR_ROUTES_V1"


# ---------------------------------------------------------------------------
# H. Schema consistency between /ecosystem and /ecosystem/{device_id}
# ---------------------------------------------------------------------------


class TestEcosystemRouteSchemaConsistency:
    _DEVICE_PAYLOAD: Dict[str, Any] = {
        "model_id": "mbvlm_7b",
        "runtime_type": "LLAMA_CPP",
        "checksum_ok": True,
        "compatibility_ok": True,
        "mobilevlm_present": True,
        "mobilevlm_checksum_ok": True,
        "seeclick_present": False,
        "runtime_health_snapshot": {"score": 0.88},
        "snapshotTs": 1_700_700_000.0,
        "model_ready": True,
        "llama_cpp_available": True,
        "local_loop_ready": True,
    }

    def test_H01_model_presence_fields_visible_via_per_device_route(self):
        absorb_device_state_snapshot("schema_dev_01", self._DEVICE_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/schema_dev_01")
        data = resp.json()
        assert data["mobilevlm_present"] is True
        assert data["mobilevlm_checksum_ok"] is True
        assert data["seeclick_present"] is False

    def test_H02_runtime_health_visible_via_per_device_route(self):
        absorb_device_state_snapshot("schema_dev_02", self._DEVICE_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/schema_dev_02")
        data = resp.json()
        assert data["runtime_health_snapshot"] == {"score": 0.88}

    def test_H03_snapshot_ts_camelCase_visible_via_per_device_route(self):
        absorb_device_state_snapshot("schema_dev_03", self._DEVICE_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/schema_dev_03")
        data = resp.json()
        assert data["snapshot_ts"] == 1_700_700_000.0

    def test_H04_model_presence_fields_in_multi_device_ecosystem_model_subdict(self):
        absorb_device_state_snapshot("schema_dev_04", self._DEVICE_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        dev = next(d for d in data["devices"] if d["device_id"] == "schema_dev_04")
        assert dev["model"]["mobilevlm_present"] is True
        assert dev["model"]["mobilevlm_checksum_ok"] is True
        assert dev["model"]["seeclick_present"] is False

    def test_H05_runtime_health_in_multi_device_ecosystem(self):
        absorb_device_state_snapshot("schema_dev_05", self._DEVICE_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        dev = next(d for d in data["devices"] if d["device_id"] == "schema_dev_05")
        assert dev["runtime_health_snapshot"] == {"score": 0.88}


# ---------------------------------------------------------------------------
# I. Realistic full camelCase Android payload end-to-end
# ---------------------------------------------------------------------------


class TestRealisticCamelCasePayloadEndToEnd:
    """I-series: full realistic Android camelCase payload → store → surfaces."""

    _CAMEL_PAYLOAD: Dict[str, Any] = {
        # Timestamp (camelCase)
        "snapshotTs": 1_701_000_000.0,
        # Native runtime
        "llamaCppAvailable": True,
        "ncnnAvailable": False,
        "activeRuntimeType": "LLAMA_CPP",
        # Readiness
        "modelReady": True,
        "accessibilityReady": True,
        "overlayReady": True,
        "localLoopReady": True,
        "degradedReasons": [],
        # Model identity
        "modelId": "mobilevlm_v2_7b",
        "runtimeType": "LLAMA_CPP",
        "checksumOk": True,
        "compatibilityOk": True,
        "quantization": "q4_k_m",
        "modelVersion": "v2.0",
        "mobilevlmPresent": True,
        "mobilevlmChecksumOk": True,
        "seeclickPresent": False,
        "pendingFirstDownload": False,
        # Queue / fallback
        "offlineQueueDepth": 0,
        "currentFallbackTier": "local_planner",
        "plannerFallbackTier": "local",
        "groundingFallbackTier": "center",
        # Health
        "warmupResult": "ok",
        "runtimeHealthSnapshot": {"score": 0.97, "warmup_ok": True},
    }

    def test_I01_all_fields_absorbed_correctly(self):
        snap = absorb_device_state_snapshot("real_dev_01", self._CAMEL_PAYLOAD)
        assert snap.snapshot_ts == 1_701_000_000.0
        assert snap.llama_cpp_available is True
        assert snap.ncnn_available is False
        assert snap.active_runtime_type == "LLAMA_CPP"
        assert snap.model_ready is True
        assert snap.accessibility_ready is True
        assert snap.overlay_ready is True
        assert snap.local_loop_ready is True
        assert snap.model_id == "mobilevlm_v2_7b"
        assert snap.runtime_type == "LLAMA_CPP"
        assert snap.checksum_ok is True
        assert snap.compatibility_ok is True
        assert snap.quantization == "q4_k_m"
        assert snap.model_version == "v2.0"
        assert snap.mobilevlm_present is True
        assert snap.mobilevlm_checksum_ok is True
        assert snap.seeclick_present is False
        assert snap.pending_first_download is False
        assert snap.offline_queue_depth == 0
        assert snap.current_fallback_tier == "local_planner"
        assert snap.planner_fallback_tier == "local"
        assert snap.grounding_fallback_tier == "center"
        assert snap.warmup_result == "ok"
        assert snap.runtime_health_snapshot == {"score": 0.97, "warmup_ok": True}

    def test_I02_to_dict_schema_complete(self):
        snap = absorb_device_state_snapshot("real_dev_02", self._CAMEL_PAYLOAD)
        d = snap.to_dict()
        # Authority provenance
        assert d["_source"] == "android_device_state_store"
        # Timestamp
        assert d["snapshot_ts"] == 1_701_000_000.0
        # Model presence fields
        assert d["mobilevlm_present"] is True
        assert d["mobilevlm_checksum_ok"] is True
        assert d["seeclick_present"] is False
        # Runtime health
        assert d["runtime_health_snapshot"]["score"] == 0.97

    def test_I03_ecosystem_summary_schema_complete(self):
        absorb_device_state_snapshot("real_dev_03", self._CAMEL_PAYLOAD)
        summary = get_device_ecosystem_summary()
        dev = next(d for d in summary["devices"] if d["device_id"] == "real_dev_03")
        # Snapshot timestamp
        assert dev["snapshot_ts"] == 1_701_000_000.0
        # Runtime health
        assert dev["runtime_health_snapshot"]["score"] == 0.97
        # Model presence in model sub-dict
        assert dev["model"]["mobilevlm_present"] is True
        assert dev["model"]["mobilevlm_checksum_ok"] is True
        assert dev["model"]["seeclick_present"] is False

    def test_I04_per_device_route_schema_complete(self):
        absorb_device_state_snapshot("real_dev_04", self._CAMEL_PAYLOAD)
        app = _make_router_app()
        client = TestClient(app)
        resp = client.get("/api/v1/operator/devices/ecosystem/real_dev_04")
        assert resp.status_code == 200
        data = resp.json()
        # Authority annotation
        assert data["authority"] == "OPERATOR_ROUTES_V1"
        # Source provenance
        assert data["_source"] == "android_device_state_store"
        # Snapshot timestamp
        assert data["snapshot_ts"] == 1_701_000_000.0
        # Model presence
        assert data["mobilevlm_present"] is True
        assert data["seeclick_present"] is False
        # Runtime health
        assert data["runtime_health_snapshot"]["score"] == 0.97

    def test_I05_is_local_ai_ready_true_for_full_ready_payload(self):
        snap = absorb_device_state_snapshot("real_dev_05", self._CAMEL_PAYLOAD)
        assert snap.is_local_ai_ready() is True
        assert snap.readiness_summary()["local_ai_ready"] is True
