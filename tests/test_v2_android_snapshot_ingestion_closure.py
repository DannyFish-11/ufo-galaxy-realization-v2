"""tests/test_v2_android_snapshot_ingestion_closure.py
=======================================================
PR-1 V2 companion: Android runtime snapshot ingestion closure — regression tests.

Proves the V2 receive/store/expose path for realistic current Android
snapshot payloads, aligned with the current AIP v3 wire format that
GalaxyWebSocketClient.kt emits (camelCase JSON keys).

Test sections
-------------
L.  Full realistic camelCase Android snapshot payload is absorbed and all
    high-value fields are stored correctly.

M.  Handler returns ``"status": "error"`` (not ``"absorbed"``) when the
    store import is patched to raise, so the Android side receives an
    accurate ACK.

N.  Ecosystem per-device entry exposes ``snapshot_ts``,
    ``planner_fallback_tier``, and ``grounding_fallback_tier`` — fields
    present in the store but previously absent from the ecosystem summary.

O.  Ecosystem aggregate counts include ``local_loop_ready_count``.

P.  GET /api/v1/operator/devices/ecosystem returns correct structure via
    FastAPI TestClient after a snapshot is absorbed.

Q.  GET /api/v1/operator/devices/ecosystem/{device_id} returns 404 for
    an unknown device and the correct snapshot dict for a known device.

R.  Full end-to-end bridge dispatch → store → HTTP path for a realistic
    Android snapshot message.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.android_device_state_store import (
    absorb_device_state_snapshot,
    get_device_ecosystem_summary,
    get_device_state_snapshot,
    reset_android_device_state_store,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_store():
    """Reset the store singleton before and after each test."""
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
# L. Full realistic Android camelCase snapshot payload
# ---------------------------------------------------------------------------


class TestRealisticAndroidPayloadAbsorption:
    """L-series: realistic full Android camelCase payload → store."""

    # Represents the realistic payload that GalaxyWebSocketClient.kt would
    # send once Android-side emission is implemented (companion PR).
    _REALISTIC_ANDROID_PAYLOAD: Dict[str, Any] = {
        "llamaCppAvailable": True,
        "ncnnAvailable": False,
        "activeRuntimeType": "LLAMA_CPP",
        "modelReady": True,
        "accessibilityReady": True,
        "overlayReady": True,
        "localLoopReady": True,
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
        "offlineQueueDepth": 0,
        "currentFallbackTier": "local_planner",
        "plannerFallbackTier": "local",
        "groundingFallbackTier": "center",
        "warmupResult": "ok",
        "degradedReasons": [],
        "snapshot_ts": 1700000000.0,
    }

    def test_L01_camelcase_runtime_fields_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.llama_cpp_available is True
        assert snap.ncnn_available is False
        assert snap.active_runtime_type == "LLAMA_CPP"

    def test_L02_camelcase_readiness_fields_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.model_ready is True
        assert snap.accessibility_ready is True
        assert snap.overlay_ready is True
        assert snap.local_loop_ready is True

    def test_L03_camelcase_model_identity_fields_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.model_id == "mobilevlm_v2_7b"
        assert snap.runtime_type == "LLAMA_CPP"
        assert snap.checksum_ok is True
        assert snap.compatibility_ok is True
        assert snap.quantization == "q4_k_m"
        assert snap.model_version == "v2.0"

    def test_L04_camelcase_model_presence_flags_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.mobilevlm_present is True
        assert snap.mobilevlm_checksum_ok is True
        assert snap.seeclick_present is False
        assert snap.pending_first_download is False

    def test_L05_queue_and_fallback_fields_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.offline_queue_depth == 0
        assert snap.current_fallback_tier == "local_planner"
        assert snap.planner_fallback_tier == "local"
        assert snap.grounding_fallback_tier == "center"
        assert snap.warmup_result == "ok"

    def test_L06_snapshot_ts_stored(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.snapshot_ts == 1700000000.0

    def test_L07_is_local_ai_ready_true_for_realistic_payload(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.is_local_ai_ready() is True

    def test_L08_raw_payload_preserved(self):
        snap = absorb_device_state_snapshot("android_rt_01", self._REALISTIC_ANDROID_PAYLOAD)
        assert snap.raw_payload.get("llamaCppAvailable") is True

    def test_L09_partial_snapshot_no_exception(self):
        """Partial payload (only readiness flags) must be absorbed without error."""
        partial = {
            "modelReady": True,
            "accessibilityReady": False,
        }
        snap = absorb_device_state_snapshot("android_partial_01", partial)
        assert snap.model_ready is True
        assert snap.accessibility_ready is False
        assert snap.llama_cpp_available is None  # absent → None

    def test_L10_empty_payload_absorbed_with_none_fields(self):
        snap = absorb_device_state_snapshot("android_empty_01", {})
        assert snap.model_ready is None
        assert snap.llama_cpp_available is None
        assert snap.degraded_reasons == []
        assert snap.offline_queue_depth is None


# ---------------------------------------------------------------------------
# M. Handler ACK status on exception path
# ---------------------------------------------------------------------------


class TestHandlerAckStatusOnException:
    """M-series: handler returns "error" status when absorption fails."""

    def test_M01_snapshot_handler_returns_error_on_import_failure(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        message = {
            "type": "device_state_snapshot",
            "device_id": "error_device_01",
            "message_id": "msg_err_01",
            "payload": {"model_ready": True},
        }
        bridge = MagicMock()
        websocket = MagicMock()

        with patch(
            "core.android_device_state_store.absorb_device_state_snapshot",
            side_effect=ImportError("store not available"),
        ):
            response = asyncio.run(
                handle_device_state_snapshot(bridge, websocket, message)
            )

        assert response["type"] == "device_state_snapshot_ack"
        assert response["status"] == "error"
        assert response["device_id"] == "error_device_01"
        assert response["correlation_id"] == "msg_err_01"

    def test_M02_snapshot_handler_returns_error_on_runtime_exception(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        message = {
            "type": "device_state_snapshot",
            "device_id": "error_device_02",
            "message_id": "msg_err_02",
            "payload": {"model_ready": True},
        }
        bridge = MagicMock()
        websocket = MagicMock()

        with patch(
            "core.android_device_state_store.absorb_device_state_snapshot",
            side_effect=RuntimeError("store write failed"),
        ):
            response = asyncio.run(
                handle_device_state_snapshot(bridge, websocket, message)
            )

        assert response["status"] == "error"

    def test_M03_execution_event_handler_returns_error_on_import_failure(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )

        message = {
            "type": "device_execution_event",
            "device_id": "error_device_03",
            "message_id": "msg_evt_err_01",
            "payload": {"flow_id": "f1", "phase": "planning"},
        }
        bridge = MagicMock()
        websocket = MagicMock()

        with patch(
            "core.android_device_state_store.absorb_device_execution_event",
            side_effect=ImportError("store not available"),
        ):
            response = asyncio.run(
                handle_device_execution_event(bridge, websocket, message)
            )

        assert response["type"] == "device_execution_event_ack"
        assert response["status"] == "error"

    def test_M04_execution_event_handler_returns_error_on_runtime_exception(self):
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_execution_event,
        )

        message = {
            "type": "device_execution_event",
            "device_id": "error_device_04",
            "message_id": "msg_evt_err_02",
            "payload": {"flow_id": "f2", "phase": "grounding"},
        }
        bridge = MagicMock()
        websocket = MagicMock()

        with patch(
            "core.android_device_state_store.absorb_device_execution_event",
            side_effect=RuntimeError("event write failed"),
        ):
            response = asyncio.run(
                handle_device_execution_event(bridge, websocket, message)
            )

        assert response["status"] == "error"

    def test_M05_snapshot_handler_returns_absorbed_on_success(self):
        """Confirm status is still 'absorbed' on the success path."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        message = {
            "type": "device_state_snapshot",
            "device_id": "success_device_01",
            "message_id": "msg_ok_01",
            "payload": {"model_ready": True, "llamaCppAvailable": True},
        }
        bridge = MagicMock()
        websocket = MagicMock()

        response = asyncio.run(handle_device_state_snapshot(bridge, websocket, message))
        assert response["status"] == "absorbed"


# ---------------------------------------------------------------------------
# N. Ecosystem per-device entry exposes high-value fallback fields
# ---------------------------------------------------------------------------


class TestEcosystemPerDeviceHighValueFields:
    """N-series: per-device entry in ecosystem summary exposes enriched fields."""

    def test_N01_snapshot_ts_in_per_device_entry(self):
        absorb_device_state_snapshot("n_dev_01", {
            "model_ready": True,
            "snapshot_ts": 1700000001.0,
        })
        summary = get_device_ecosystem_summary()
        device = next(
            (d for d in summary["devices"] if d["device_id"] == "n_dev_01"), None
        )
        assert device is not None, "device n_dev_01 not found in ecosystem devices"
        assert "snapshot_ts" in device
        assert device["snapshot_ts"] == 1700000001.0

    def test_N02_planner_fallback_tier_in_per_device_entry(self):
        absorb_device_state_snapshot("n_dev_02", {
            "planner_fallback_tier": "local",
            "grounding_fallback_tier": "center",
        })
        summary = get_device_ecosystem_summary()
        device = next(
            (d for d in summary["devices"] if d["device_id"] == "n_dev_02"), None
        )
        assert device is not None, "device n_dev_02 not found in ecosystem devices"
        assert "planner_fallback_tier" in device
        assert device["planner_fallback_tier"] == "local"

    def test_N03_grounding_fallback_tier_in_per_device_entry(self):
        absorb_device_state_snapshot("n_dev_03", {
            "planner_fallback_tier": "local",
            "grounding_fallback_tier": "center_delegated",
        })
        summary = get_device_ecosystem_summary()
        device = next(
            (d for d in summary["devices"] if d["device_id"] == "n_dev_03"), None
        )
        assert device is not None, "device n_dev_03 not found in ecosystem devices"
        assert "grounding_fallback_tier" in device
        assert device["grounding_fallback_tier"] == "center_delegated"

    def test_N04_snapshot_ts_none_when_not_provided(self):
        absorb_device_state_snapshot("n_dev_04", {"model_ready": True})
        summary = get_device_ecosystem_summary()
        device = next(
            (d for d in summary["devices"] if d["device_id"] == "n_dev_04"), None
        )
        assert device is not None, "device n_dev_04 not found in ecosystem devices"
        assert "snapshot_ts" in device
        assert device["snapshot_ts"] is None

    def test_N05_camelcase_fallback_tiers_in_per_device_entry(self):
        absorb_device_state_snapshot("n_dev_05", {
            "snapshot_ts": 1700000002.0,
            "plannerFallbackTier": "local",
            "groundingFallbackTier": "center",
        })
        summary = get_device_ecosystem_summary()
        device = next(
            (d for d in summary["devices"] if d["device_id"] == "n_dev_05"), None
        )
        assert device is not None, "device n_dev_05 not found in ecosystem devices"
        assert device["snapshot_ts"] == 1700000002.0
        assert device["planner_fallback_tier"] == "local"
        assert device["grounding_fallback_tier"] == "center"


# ---------------------------------------------------------------------------
# O. Ecosystem aggregate includes local_loop_ready_count
# ---------------------------------------------------------------------------


class TestEcosystemAggregateLocalLoopReadyCount:
    """O-series: ecosystem aggregate counts include local_loop_ready_count."""

    def test_O01_local_loop_ready_count_present_in_empty_summary(self):
        summary = get_device_ecosystem_summary()
        assert "local_loop_ready_count" in summary
        assert summary["local_loop_ready_count"] == 0

    def test_O02_local_loop_ready_count_counts_correctly(self):
        absorb_device_state_snapshot("o_dev_01", {"local_loop_ready": True})
        absorb_device_state_snapshot("o_dev_02", {"local_loop_ready": True})
        absorb_device_state_snapshot("o_dev_03", {"local_loop_ready": False})
        absorb_device_state_snapshot("o_dev_04", {})  # None / absent
        summary = get_device_ecosystem_summary()
        assert summary["total_devices_with_snapshot"] == 4
        assert summary["local_loop_ready_count"] == 2

    def test_O03_local_loop_ready_count_zero_when_none_ready(self):
        absorb_device_state_snapshot("o_dev_05", {"local_loop_ready": False})
        absorb_device_state_snapshot("o_dev_06", {"local_loop_ready": False})
        summary = get_device_ecosystem_summary()
        assert summary["local_loop_ready_count"] == 0

    def test_O04_local_loop_ready_count_independent_of_model_ready(self):
        # Device with model_ready=True but local_loop_ready=False
        absorb_device_state_snapshot("o_dev_07", {
            "model_ready": True,
            "local_loop_ready": False,
        })
        # Device with model_ready=False but local_loop_ready=True
        absorb_device_state_snapshot("o_dev_08", {
            "model_ready": False,
            "local_loop_ready": True,
        })
        summary = get_device_ecosystem_summary()
        assert summary["model_ready_count"] == 1
        assert summary["local_loop_ready_count"] == 1


# ---------------------------------------------------------------------------
# P. HTTP route returns correct structure
# ---------------------------------------------------------------------------


class TestEcosystemHTTPRouteStructure:
    """P-series: GET /api/v1/operator/devices/ecosystem returns correct shape."""

    def test_P01_ecosystem_route_returns_200(self):
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem")
        assert resp.status_code == 200

    def test_P02_ecosystem_route_returns_required_aggregate_keys(self):
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        required = [
            "total_devices_with_snapshot",
            "local_ai_ready_count",
            "model_ready_count",
            "accessibility_ready_count",
            "overlay_ready_count",
            "local_loop_ready_count",
            "pending_first_download_count",
            "devices",
        ]
        for key in required:
            assert key in data, f"Missing key: {key}"

    def test_P03_ecosystem_route_returns_device_with_new_fields_after_absorb(self):
        absorb_device_state_snapshot("p_dev_01", {
            "model_ready": True,
            "llamaCppAvailable": True,
            "localLoopReady": True,
            "plannerFallbackTier": "local",
            "groundingFallbackTier": "center",
            "snapshot_ts": 1700000003.0,
        })
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        assert data["total_devices_with_snapshot"] >= 1
        assert data["local_loop_ready_count"] >= 1
        device = next(
            (d for d in data["devices"] if d["device_id"] == "p_dev_01"), None
        )
        assert device is not None, "device p_dev_01 not found in ecosystem devices"
        assert device["snapshot_ts"] == 1700000003.0
        assert device["planner_fallback_tier"] == "local"
        assert device["grounding_fallback_tier"] == "center"

    def test_P04_ecosystem_route_has_authority_key(self):
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        assert "authority" in data


# ---------------------------------------------------------------------------
# Q. Per-device snapshot HTTP route
# ---------------------------------------------------------------------------


class TestPerDeviceSnapshotHTTPRoute:
    """Q-series: GET /api/v1/operator/devices/ecosystem/{device_id}."""

    def test_Q01_returns_404_for_unknown_device(self):
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem/unknown_xyz")
        assert resp.status_code == 404

    def test_Q02_returns_200_with_full_snapshot_for_known_device(self):
        absorb_device_state_snapshot("q_dev_01", {
            "modelReady": True,
            "llamaCppAvailable": True,
            "localLoopReady": True,
            "offlineQueueDepth": 3,
            "plannerFallbackTier": "local",
            "groundingFallbackTier": "center",
        })
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem/q_dev_01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "q_dev_01"
        assert data["model_ready"] is True
        assert data["llama_cpp_available"] is True
        assert data["local_loop_ready"] is True
        assert data["offline_queue_depth"] == 3
        assert data["planner_fallback_tier"] == "local"
        assert data["grounding_fallback_tier"] == "center"

    def test_Q03_per_device_route_snapshot_ts_is_exposed(self):
        absorb_device_state_snapshot("q_dev_02", {
            "snapshot_ts": 1700000004.0,
            "model_ready": True,
        })
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem/q_dev_02")
        data = resp.json()
        assert data["snapshot_ts"] == 1700000004.0


# ---------------------------------------------------------------------------
# R. End-to-end bridge dispatch → store → HTTP path
# ---------------------------------------------------------------------------


class TestEndToEndBridgeToHTTP:
    """R-series: bridge dispatch → store absorption → HTTP route exposure."""

    def test_R01_bridge_dispatch_snapshot_then_http_route_exposes_it(self):
        """Simulate the full path: Android bridge dispatch → store → HTTP read."""
        from galaxy_gateway.android.handlers.device_state_snapshot import (
            handle_device_state_snapshot,
        )

        # Step 1: simulate bridge receiving a realistic Android message
        message = {
            "type": "device_state_snapshot",
            "device_id": "e2e_device_01",
            "message_id": "e2e_msg_01",
            "payload": {
                "llamaCppAvailable": True,
                "modelReady": True,
                "localLoopReady": True,
                "activeRuntimeType": "LLAMA_CPP",
                "currentFallbackTier": "local_planner",
                "plannerFallbackTier": "local",
                "groundingFallbackTier": "center",
                "offlineQueueDepth": 0,
                "snapshot_ts": 1700000005.0,
            },
        }
        bridge = MagicMock()
        websocket = MagicMock()
        ack = asyncio.run(handle_device_state_snapshot(bridge, websocket, message))
        assert ack["status"] == "absorbed"

        # Step 2: verify store absorbed correctly
        snap = get_device_state_snapshot("e2e_device_01")
        assert snap is not None
        assert snap.llama_cpp_available is True
        assert snap.model_ready is True
        assert snap.planner_fallback_tier == "local"
        assert snap.grounding_fallback_tier == "center"
        assert snap.snapshot_ts == 1700000005.0

        # Step 3: verify HTTP ecosystem route exposes it
        app = _make_router_app()
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem")
        data = resp.json()
        assert data["total_devices_with_snapshot"] >= 1
        assert data["local_loop_ready_count"] >= 1
        device = next(
            (d for d in data["devices"] if d["device_id"] == "e2e_device_01"), None
        )
        assert device is not None, "device e2e_device_01 not found in ecosystem devices"
        assert device["snapshot_ts"] == 1700000005.0
        assert device["planner_fallback_tier"] == "local"
        assert device["grounding_fallback_tier"] == "center"

        # Step 4: verify per-device HTTP route
        with TestClient(app) as client:
            resp = client.get("/api/v1/operator/devices/ecosystem/e2e_device_01")
        assert resp.status_code == 200
        pdata = resp.json()
        assert pdata["model_ready"] is True
        assert pdata["grounding_fallback_tier"] == "center"

    def test_R02_operator_snapshot_android_ecosystem_reflects_absorbed_data(self):
        """operator_snapshot() android_ecosystem must reflect absorbed snapshot data."""
        from core.operator_surface import get_operator_surface

        absorb_device_state_snapshot("r_dev_02", {
            "model_ready": True,
            "llama_cpp_available": True,
            "local_loop_ready": True,
            "planner_fallback_tier": "local",
            "grounding_fallback_tier": "center",
            "offline_queue_depth": 2,
        })

        surface = get_operator_surface()
        op_snap = surface.operator_snapshot()
        eco = op_snap.android_ecosystem
        assert isinstance(eco, dict)
        assert eco.get("total_devices_with_snapshot", 0) >= 1
        assert "local_loop_ready_count" in eco
        assert eco["local_loop_ready_count"] >= 1
        device = next(
            (d for d in eco.get("devices", []) if d["device_id"] == "r_dev_02"),
            None,
        )
        assert device is not None
        assert device["planner_fallback_tier"] == "local"
        assert device["grounding_fallback_tier"] == "center"
        assert device["offline_queue_depth"] == 2
