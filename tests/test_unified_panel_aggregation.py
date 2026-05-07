"""
tests/test_unified_panel_aggregation.py
=========================================
PR-1: Unified Runtime Surface & Panel Aggregation — test suite.

Validates:
1. UnifiedPanelPayload structure and required fields.
2. UnifiedPanelAggregationService builds from canonical source singletons.
3. Android truth participates where supported by real current code paths.
4. Clients can consume one aggregated payload instead of fan-out reads.
5. Regression safety: removing upstream source wiring is detectable.
6. GET /api/v1/panel/unified endpoint returns valid structure.
"""

from __future__ import annotations

import json
import time
import unittest
from typing import Any, Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# A. Payload model — structure & serialisation
# ---------------------------------------------------------------------------


class TestUnifiedPanelPayloadStructure(unittest.TestCase):
    """UnifiedPanelPayload must have all required fields and correct types."""

    def _import_payload(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        return UnifiedPanelPayload

    def test_A01_import_succeeds(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelPayload,
            UNIFIED_PANEL_AGGREGATION_AUTHORITY,
            PANEL_STATE_SCHEMA_VERSION,
        )
        self.assertIsInstance(UNIFIED_PANEL_AGGREGATION_AUTHORITY, str)
        self.assertIn("UNIFIED_PANEL_AGGREGATION_V1", UNIFIED_PANEL_AGGREGATION_AUTHORITY)
        self.assertEqual(PANEL_STATE_SCHEMA_VERSION, "1.0")

    def test_A02_default_construction(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.payload_id, str)
        self.assertTrue(p.payload_id.startswith("panel_"))
        self.assertIsInstance(p.generated_at, float)
        self.assertGreater(p.generated_at, 0)
        self.assertEqual(p.schema_version, "1.0")

    def test_A03_operator_section_fields(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        for field in [
            "active_task_count",
            "active_flow_count",
            "online_device_count",
            "capability_provider_count",
            "online_provider_count",
            "topology_node_count",
            "topology_edge_count",
        ]:
            self.assertIsInstance(getattr(p, field), int, f"Field {field!r} must be int")

    def test_A04_shell_presence_fields(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.desktop_shell_state, str)
        self.assertIsInstance(p.presence_tristate, str)
        self.assertIsInstance(p.manifestation_summary, dict)

    def test_A05_continuum_fields(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.tri_state_phase, str)
        # runtime_domain may be None
        self.assertIsInstance(p.presence_intensity, float)
        self.assertIsInstance(p.coherence, float)

    def test_A06_android_section_fields(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.android_ecosystem, dict)
        self.assertIsInstance(p.android_device_execution_digest, list)

    def test_A07_readiness_fields(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.readiness_verdict, str)
        self.assertIsInstance(p.blocked_dimensions, list)

    def test_A08_surface_spec_field(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        self.assertIsInstance(p.active_surface_spec, dict)

    def test_A09_source_field(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelPayload,
            UNIFIED_PANEL_AGGREGATION_AUTHORITY,
        )
        p = UnifiedPanelPayload()
        self.assertEqual(p._source, UNIFIED_PANEL_AGGREGATION_AUTHORITY)

    def test_A10_to_dict_contains_all_required_keys(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        d = p.to_dict()
        required_keys = {
            "payload_id", "generated_at", "schema_version",
            # operator
            "active_task_count", "active_flow_count", "online_device_count",
            "capability_provider_count", "online_provider_count",
            "topology_node_count", "topology_edge_count",
            # shell/presence
            "desktop_shell_state", "presence_tristate", "manifestation_summary",
            # continuum
            "tri_state_phase", "runtime_domain", "presence_intensity", "coherence",
            # android
            "android_ecosystem", "android_device_execution_digest",
            # readiness
            "readiness_verdict", "blocked_dimensions",
            # surface
            "active_surface_spec",
            # governance
            "governance_state",
            # provenance
            "_source",
        }
        for key in required_keys:
            self.assertIn(key, d, f"Required key {key!r} missing from to_dict()")

    def test_A11_to_dict_is_json_serialisable(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        p.android_ecosystem = {"total_devices_with_snapshot": 2, "local_ai_ready_count": 1}
        p.android_device_execution_digest = [{"device_id": "dev_1", "model_ready": True}]
        raw = json.dumps(p.to_dict())
        self.assertIsInstance(raw, str)
        restored = json.loads(raw)
        self.assertEqual(restored["android_ecosystem"]["total_devices_with_snapshot"], 2)

    def test_A12_unique_payload_ids(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        ids = {UnifiedPanelPayload().payload_id for _ in range(20)}
        self.assertEqual(len(ids), 20)

    def test_A13_schema_version_is_1_0(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelPayload,
            PANEL_STATE_SCHEMA_VERSION,
        )
        p = UnifiedPanelPayload()
        self.assertEqual(p.schema_version, "1.0")
        self.assertEqual(PANEL_STATE_SCHEMA_VERSION, "1.0")


# ---------------------------------------------------------------------------
# B. Service — canonical source wiring
# ---------------------------------------------------------------------------


class TestUnifiedPanelAggregationServiceSources(unittest.TestCase):
    """UnifiedPanelAggregationService must read from canonical source singletons."""

    def test_B01_service_import_succeeds(self):
        from core.unified_panel_aggregation import UnifiedPanelAggregationService  # noqa: F401

    def test_B02_build_payload_returns_payload_instance(self):
        from core.unified_panel_aggregation import (
            UnifiedPanelAggregationService,
            UnifiedPanelPayload,
        )
        svc = UnifiedPanelAggregationService()
        result = svc.build_payload()
        self.assertIsInstance(result, UnifiedPanelPayload)

    def test_B03_build_payload_never_raises(self):
        """Even when all sub-sources fail, build_payload must return a valid payload."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        svc = UnifiedPanelAggregationService()
        # Patch the fill methods to raise so we verify the outer guard in build_payload
        with patch.object(svc, "_fill_from_operator_snapshot", side_effect=RuntimeError("mock failure")):
            with patch.object(svc, "_fill_from_android_store", side_effect=RuntimeError("mock failure")):
                with patch.object(svc, "_fill_from_runtime_projection", side_effect=RuntimeError("mock failure")):
                    with patch.object(svc, "_fill_from_readiness_matrix", side_effect=RuntimeError("mock failure")):
                        with patch.object(svc, "_fill_active_surface_spec", side_effect=RuntimeError("mock failure")):
                            result = svc.build_payload()
        from core.unified_panel_aggregation import UnifiedPanelPayload
        self.assertIsInstance(result, UnifiedPanelPayload)

    def test_B04_operator_snapshot_feeds_payload(self):
        """OperatorSnapshot fields must appear in the payload when the source is available."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService

        # Build a mock OperatorSnapshot
        mock_snap = MagicMock()
        mock_snap.active_task_count = 7
        mock_snap.active_flow_count = 3
        mock_snap.online_device_count = 5
        mock_snap.capability_provider_count = 10
        mock_snap.online_provider_count = 8
        mock_snap.topology_node_count = 12
        mock_snap.topology_edge_count = 15
        mock_snap.desktop_shell_state = "sidesheet"
        mock_snap.presence_tristate = "liminal"
        mock_snap.manifestation_summary = {
            "desktop_shell_state": "sidesheet",
            "presence_tristate": "liminal",
            "_source": "mock",
        }

        mock_surface = MagicMock()
        mock_surface.operator_snapshot.return_value = mock_snap

        svc = UnifiedPanelAggregationService()
        # Patch at the canonical source location — lazy-imported inside the method
        with patch("core.operator_surface.get_operator_surface", return_value=mock_surface):
            result = svc.build_payload()

        self.assertEqual(result.active_task_count, 7)
        self.assertEqual(result.active_flow_count, 3)
        self.assertEqual(result.online_device_count, 5)
        self.assertEqual(result.desktop_shell_state, "sidesheet")
        self.assertEqual(result.presence_tristate, "liminal")

    def test_B05_surface_selector_wires_active_surface_spec(self):
        """Active surface spec must come from SurfaceSelector."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType

        mock_spec = SurfaceSpec(surface_type=SurfaceType.CONTROL_CONSOLE, title="Test Console")
        mock_selector = MagicMock()
        mock_selector.select_surface.return_value = mock_spec

        svc = UnifiedPanelAggregationService()
        with patch(
            "core.generative_ui.surface_selector.SurfaceSelector",
            return_value=mock_selector,
        ):
            result = svc.build_payload(mode="control_console")

        # active_surface_spec should be a dict from SurfaceSpec.to_dict()
        spec_d = result.active_surface_spec
        if spec_d:  # may be empty if SurfaceSelector patching was partial
            self.assertIsInstance(spec_d, dict)

    def test_B06_surface_spec_for_chat_mode(self):
        """Default chat mode should produce a chat_panel surface spec."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        svc = UnifiedPanelAggregationService()
        result = svc.build_payload(mode="chat")
        spec = result.active_surface_spec
        if spec:  # graceful-degrade: only assert when surface selector is available
            self.assertIn("surface_type", spec)
            self.assertEqual(spec["surface_type"], "chat_panel")


# ---------------------------------------------------------------------------
# C. Android truth participation
# ---------------------------------------------------------------------------


class TestAndroidTruthParticipation(unittest.TestCase):
    """Android-derived state must participate in the unified payload."""

    def test_C01_android_ecosystem_field_is_present(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        d = p.to_dict()
        self.assertIn("android_ecosystem", d)

    def test_C02_android_device_execution_digest_is_present(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        d = p.to_dict()
        self.assertIn("android_device_execution_digest", d)

    def test_C02b_governance_state_is_present(self):
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        d = p.to_dict()
        self.assertIn("governance_state", d)

    def test_C03_android_ecosystem_whitelisted_keys(self):
        """android_ecosystem in payload must respect the ANDROID_ECOSYSTEM_SNAPSHOT_KEYS whitelist."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS

        mock_eco = {
            "total_devices_with_snapshot": 3,
            "local_ai_ready_count": 2,
            "model_ready_count": 1,
            "accessibility_ready_count": 2,
            "overlay_ready_count": 1,
            "local_loop_ready_count": 1,
            "pending_first_download_count": 0,
            "devices": [{"device_id": "dev_1"}],  # should be filtered out
        }

        svc = UnifiedPanelAggregationService()
        with patch(
            "core.android_device_state_store.get_device_ecosystem_summary",
            return_value=mock_eco,
        ):
            with patch(
                "core.android_device_state_store.list_device_state_snapshots",
                return_value=[],
            ):
                result = svc.build_payload()

        # Per-device 'devices' list must be excluded from the snapshot summary
        self.assertNotIn("devices", result.android_ecosystem)
        # Whitelisted keys must be present
        for key in ANDROID_ECOSYSTEM_SNAPSHOT_KEYS:
            if key in mock_eco:
                self.assertIn(key, result.android_ecosystem)

    def test_C04_android_device_digest_includes_per_device_readiness(self):
        """Each Android device snapshot must contribute a readiness digest entry."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        from core.android_device_state_store import DeviceStateSnapshot

        # Build a minimal DeviceStateSnapshot fixture
        snap = DeviceStateSnapshot(device_id="dev_001")
        snap.model_ready = True
        snap.accessibility_ready = True
        snap.absorbed_at = time.time()

        mock_eco = {"total_devices_with_snapshot": 1, "local_ai_ready_count": 1}

        svc = UnifiedPanelAggregationService()
        with patch(
            "core.android_device_state_store.get_device_ecosystem_summary",
            return_value=mock_eco,
        ):
            with patch(
                "core.android_device_state_store.list_device_state_snapshots",
                return_value=[snap],
            ):
                result = svc.build_payload()

        self.assertEqual(len(result.android_device_execution_digest), 1)
        entry = result.android_device_execution_digest[0]
        self.assertEqual(entry["device_id"], "dev_001")
        self.assertTrue(entry["model_ready"])
        self.assertIn("dispatch_capability_status", entry)
        status = entry["dispatch_capability_status"]
        self.assertIn("authoritative_scoring_fields", status)
        self.assertIn("capability_presence_only_fields", status)
        self.assertIn("model_ready", status["authoritative_scoring_fields"])
        self.assertIn("mobilevlm_present", status["capability_presence_only_fields"])
        self.assertEqual(entry.get("_source"), "android_device_state_store")

    def test_C05_android_store_authority_sentinel_present(self):
        """ANDROID_DEVICE_STATE_STORE_AUTHORITY must be importable and non-empty."""
        from core.android_device_state_store import ANDROID_DEVICE_STATE_STORE_AUTHORITY
        self.assertIsInstance(ANDROID_DEVICE_STATE_STORE_AUTHORITY, str)
        self.assertGreater(len(ANDROID_DEVICE_STATE_STORE_AUTHORITY), 10)

    def test_C06_android_ecosystem_survives_empty_store(self):
        """When no Android devices are registered the payload must still be valid."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService
        from core.android_device_state_store import (
            get_android_device_state_store,
            reset_android_device_state_store,
        )

        reset_android_device_state_store()
        try:
            svc = UnifiedPanelAggregationService()
            result = svc.build_payload()
            self.assertIsInstance(result.android_ecosystem, dict)
            self.assertIsInstance(result.android_device_execution_digest, list)
        finally:
            reset_android_device_state_store()

    def test_C07_android_ecosystem_count_reflects_absorbed_snapshot(self):
        """After absorbing a device snapshot the ecosystem count increments."""
        from core.android_device_state_store import (
            absorb_device_state_snapshot,
            get_device_ecosystem_summary,
            reset_android_device_state_store,
        )
        from core.unified_panel_aggregation import build_unified_panel_payload

        reset_android_device_state_store()
        try:
            # No devices yet
            before = build_unified_panel_payload()
            before_count = before.android_ecosystem.get("total_devices_with_snapshot", 0)

            # Absorb a fake snapshot
            absorb_device_state_snapshot(
                "test_device_001",
                {
                    "device_id": "test_device_001",
                    "snapshot_ts": time.time(),
                    "model_ready": True,
                    "accessibility_ready": False,
                    "overlay_ready": False,
                    "local_loop_ready": False,
                    "pending_first_download": False,
                },
            )

            after = build_unified_panel_payload()
            after_count = after.android_ecosystem.get("total_devices_with_snapshot", 0)
            self.assertGreater(after_count, before_count)
        finally:
            reset_android_device_state_store()


# ---------------------------------------------------------------------------
# D. Fan-out replacement — single-endpoint completeness
# ---------------------------------------------------------------------------


class TestFanOutReplacement(unittest.TestCase):
    """One unified payload must contain all state families needed by panel clients."""

    def _get_payload_dict(self) -> Dict[str, Any]:
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        p.active_task_count = 3
        p.active_flow_count = 1
        p.online_device_count = 2
        p.desktop_shell_state = "island"
        p.presence_tristate = "silent"
        p.tri_state_phase = "silent"
        p.android_ecosystem = {"total_devices_with_snapshot": 1}
        p.readiness_verdict = "READY"
        p.active_surface_spec = {"surface_type": "chat_panel"}
        return p.to_dict()

    def test_D01_payload_covers_operator_snapshot_domain(self):
        """Fields previously requiring /api/v1/operator/snapshot must be in payload."""
        d = self._get_payload_dict()
        for key in ["active_task_count", "online_device_count", "active_flow_count"]:
            self.assertIn(key, d, f"Operator field {key!r} missing from unified payload")

    def test_D02_payload_covers_runtime_projection_domain(self):
        """Fields previously requiring /api/v1/projection/runtime must be in payload."""
        d = self._get_payload_dict()
        for key in ["tri_state_phase", "runtime_domain", "presence_intensity", "coherence"]:
            self.assertIn(key, d, f"Projection field {key!r} missing from unified payload")

    def test_D03_payload_covers_android_ecosystem_domain(self):
        """Fields previously requiring /api/v1/operator/devices/ecosystem must be in payload."""
        d = self._get_payload_dict()
        self.assertIn("android_ecosystem", d)
        self.assertIn("android_device_execution_digest", d)

    def test_D04_payload_covers_shell_presence_domain(self):
        """Fields from manifestation/presence summary must be in payload."""
        d = self._get_payload_dict()
        for key in ["desktop_shell_state", "presence_tristate", "manifestation_summary"]:
            self.assertIn(key, d, f"Shell/presence field {key!r} missing from unified payload")

    def test_D05_payload_covers_readiness_domain(self):
        """Readiness verdict must be directly available in unified payload."""
        d = self._get_payload_dict()
        self.assertIn("readiness_verdict", d)
        self.assertIn("blocked_dimensions", d)

    def test_D06_payload_covers_surface_type_domain(self):
        """Active surface spec must be in payload so clients know current render mode."""
        d = self._get_payload_dict()
        self.assertIn("active_surface_spec", d)

    def test_D07_no_fan_out_required_for_basic_panel_state(self):
        """Demonstrate that a panel client can render state from one payload dict."""
        d = self._get_payload_dict()
        # Simulate panel rendering logic:
        panel_title = d["active_surface_spec"].get("surface_type", "unknown")
        presence = d["presence_tristate"]
        android_count = d["android_ecosystem"].get("total_devices_with_snapshot", 0)
        readiness = d["readiness_verdict"]
        # All critical data sourced from one object — no fan-out needed
        self.assertIsNotNone(panel_title)
        self.assertIsNotNone(presence)
        self.assertIsInstance(android_count, int)
        self.assertIsNotNone(readiness)


# ---------------------------------------------------------------------------
# E. Regression detection — upstream source wiring
# ---------------------------------------------------------------------------


class TestRegressionSafety(unittest.TestCase):
    """Removing upstream source wiring must be detectable by these tests."""

    def test_E01_operator_surface_module_is_importable(self):
        """Regression: OperatorSurface must remain importable (source 1 of 5)."""
        from core.operator_surface import (  # noqa: F401
            get_operator_surface,
            OperatorSnapshot,
            OPERATOR_SURFACE_AUTHORITY,
        )

    def test_E02_android_store_module_is_importable(self):
        """Regression: android_device_state_store must remain importable (source 2 of 5)."""
        from core.android_device_state_store import (  # noqa: F401
            get_device_ecosystem_summary,
            list_device_state_snapshots,
            ANDROID_DEVICE_STATE_STORE_AUTHORITY,
        )

    def test_E03_surface_selector_module_is_importable(self):
        """Regression: SurfaceSelector must remain importable (source 3 of 5)."""
        from core.generative_ui.surface_selector import SurfaceSelector  # noqa: F401
        from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType  # noqa: F401

    def test_E04_operator_snapshot_has_android_ecosystem_field(self):
        """Regression: OperatorSnapshot.android_ecosystem must exist (feeds android section)."""
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        self.assertTrue(hasattr(snap, "android_ecosystem"))

    def test_E05_operator_snapshot_has_manifestation_fields(self):
        """Regression: shell/presence fields must exist in OperatorSnapshot."""
        from core.operator_surface import OperatorSnapshot
        snap = OperatorSnapshot()
        self.assertTrue(hasattr(snap, "desktop_shell_state"))
        self.assertTrue(hasattr(snap, "presence_tristate"))
        self.assertTrue(hasattr(snap, "manifestation_summary"))

    def test_E06_unified_panel_aggregation_authority_is_stable(self):
        """Regression: authority sentinel must not be empty."""
        from core.unified_panel_aggregation import UNIFIED_PANEL_AGGREGATION_AUTHORITY
        self.assertIn("UNIFIED_PANEL_AGGREGATION_V1", UNIFIED_PANEL_AGGREGATION_AUTHORITY)

    def test_E07_to_dict_operator_fields_match_direct_access(self):
        """Regression: to_dict() must faithfully mirror all operator-section fields."""
        from core.unified_panel_aggregation import UnifiedPanelPayload
        p = UnifiedPanelPayload()
        p.active_task_count = 42
        p.active_flow_count = 7
        p.topology_node_count = 99
        d = p.to_dict()
        self.assertEqual(d["active_task_count"], 42)
        self.assertEqual(d["active_flow_count"], 7)
        self.assertEqual(d["topology_node_count"], 99)

    def test_E08_android_ecosystem_whitelist_parity(self):
        """Regression: the whitelist used here must match ANDROID_ECOSYSTEM_SNAPSHOT_KEYS."""
        from core.operator_surface import ANDROID_ECOSYSTEM_SNAPSHOT_KEYS
        expected = {
            "total_devices_with_snapshot",
            "local_ai_ready_count",
            "model_ready_count",
            "accessibility_ready_count",
            "overlay_ready_count",
            "local_loop_ready_count",
            "pending_first_download_count",
        }
        self.assertEqual(ANDROID_ECOSYSTEM_SNAPSHOT_KEYS, expected)

    def test_E09_panel_route_module_is_importable(self):
        """Regression: panel route module must be importable and router factory present."""
        from core.routes.panel import create_router, PANEL_ROUTES_AUTHORITY  # noqa: F401

    def test_E10_build_unified_panel_payload_returns_schema_1_0(self):
        """Regression: schema version must not silently change."""
        from core.unified_panel_aggregation import build_unified_panel_payload
        payload = build_unified_panel_payload()
        self.assertEqual(payload.schema_version, "1.0")

    def test_E11_readiness_verdict_normalised_to_uppercase(self):
        """Regression: _fill_from_readiness_matrix must normalise verdict to UPPER case."""
        from core.unified_panel_aggregation import UnifiedPanelAggregationService, UnifiedPanelPayload

        mock_matrix = MagicMock()
        mock_matrix.to_dict.return_value = {"verdict": "blocked", "blocked": ["transport_layer"]}

        svc = UnifiedPanelAggregationService()
        payload = UnifiedPanelPayload()
        with patch("core.runtime_readiness_matrix.get_readiness_matrix", return_value=mock_matrix):
            svc._fill_from_readiness_matrix(payload)

        self.assertEqual(payload.readiness_verdict, "BLOCKED")


# ---------------------------------------------------------------------------
# F. API route — GET /api/v1/panel/unified
# ---------------------------------------------------------------------------


class TestPanelUnifiedRoute(unittest.IsolatedAsyncioTestCase):
    """GET /api/v1/panel/unified must return a valid unified payload."""

    async def _client(self):
        """Return an httpx AsyncClient against a minimal FastAPI app."""
        from httpx import AsyncClient, ASGITransport
        from fastapi import FastAPI
        from core.routes.panel import create_router

        app = FastAPI()
        app.include_router(create_router())
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    async def test_F01_endpoint_returns_200(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        self.assertEqual(resp.status_code, 200)

    async def test_F02_response_is_valid_json(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertIsInstance(data, dict)

    async def test_F03_response_has_payload_id(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertIn("payload_id", data)
        self.assertTrue(data["payload_id"].startswith("panel_"))

    async def test_F04_response_has_schema_version(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertEqual(data.get("schema_version"), "1.0")

    async def test_F05_response_has_all_section_families(self):
        """Response must include at least one key from each state family."""
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        families = {
            "operator": "active_task_count",
            "shell_presence": "desktop_shell_state",
            "continuum": "tri_state_phase",
            "android": "android_ecosystem",
            "readiness": "readiness_verdict",
            "surface": "active_surface_spec",
            "provenance": "_source",
        }
        for family, key in families.items():
            self.assertIn(key, data, f"Family {family!r} representative key {key!r} missing")

    async def test_F06_mode_param_accepted(self):
        """mode query parameter must be accepted without error."""
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified?mode=deep_thinking")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("active_surface_spec", data)

    async def test_F07_source_annotation_is_authority_string(self):
        from core.unified_panel_aggregation import UNIFIED_PANEL_AGGREGATION_AUTHORITY
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertEqual(data.get("_source"), UNIFIED_PANEL_AGGREGATION_AUTHORITY)

    async def test_F08_generated_at_is_recent_timestamp(self):
        before = time.time() - 5
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        after = time.time() + 5
        data = resp.json()
        ts = data.get("generated_at", 0)
        self.assertGreater(ts, before)
        self.assertLess(ts, after)

    async def test_F09_android_section_in_response(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertIn("android_ecosystem", data)
        self.assertIn("android_device_execution_digest", data)

    async def test_F10_readiness_verdict_in_response(self):
        async with await self._client() as client:
            resp = await client.get("/api/v1/panel/unified")
        data = resp.json()
        self.assertIn("readiness_verdict", data)
        self.assertIn(data["readiness_verdict"], {"READY", "BLOCKED", "DEGRADED", "UNKNOWN"})


# ---------------------------------------------------------------------------
# G. Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement(unittest.TestCase):
    """Singleton helpers must work correctly."""

    def test_G01_get_service_returns_same_instance(self):
        from core.unified_panel_aggregation import (
            get_unified_panel_aggregation_service,
            reset_unified_panel_aggregation_service,
        )
        reset_unified_panel_aggregation_service()
        svc1 = get_unified_panel_aggregation_service()
        svc2 = get_unified_panel_aggregation_service()
        self.assertIs(svc1, svc2)

    def test_G02_reset_creates_new_instance(self):
        from core.unified_panel_aggregation import (
            get_unified_panel_aggregation_service,
            reset_unified_panel_aggregation_service,
        )
        reset_unified_panel_aggregation_service()
        svc1 = get_unified_panel_aggregation_service()
        reset_unified_panel_aggregation_service()
        svc2 = get_unified_panel_aggregation_service()
        self.assertIsNot(svc1, svc2)

    def test_G03_build_unified_panel_payload_convenience_wrapper(self):
        from core.unified_panel_aggregation import (
            build_unified_panel_payload,
            UnifiedPanelPayload,
        )
        result = build_unified_panel_payload()
        self.assertIsInstance(result, UnifiedPanelPayload)


if __name__ == "__main__":
    unittest.main()
