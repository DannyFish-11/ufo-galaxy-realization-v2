"""
tests/test_pr_device_readiness_routes.py
=========================================
Focused tests for the read-only device readiness and participation
inspection endpoints added in ``core/routes/device_readiness.py``.

Coverage
--------
- Authority sentinel is importable and non-empty.
- ``create_router()`` returns an ``APIRouter`` with the expected routes.
- ``GET /api/v1/devices/readiness``        — list with filters.
- ``GET /api/v1/devices/{id}/readiness``   — single device.
- ``GET /api/v1/devices/participation``    — list with ``only_ready`` filter.
- ``GET /api/v1/devices/{id}/participation`` — single device.
- Graceful degradation when subsystems are unavailable.
- Unknown device returns partial (not 500).
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.routes.device_readiness import (
    create_router,
    DEVICE_READINESS_ROUTES_AUTHORITY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_udm_device(device_id: str, status: str = "online"):
    d = MagicMock()
    d.device_id = device_id
    d.status = status
    d.capabilities = ["touch", "screen"]
    d.device_type = "android"
    d.autonomy = None
    return d


def _make_readiness_summary(device_id: str, registered=True, online=True,
                             connected=True, routable=True):
    from core.device_readiness import (
        DeviceReadinessSummary,
        ConnectionSummary,
        RoutabilitySummary,
    )
    rs = DeviceReadinessSummary(device_id=device_id)
    rs.registered = registered
    rs.online = online
    rs.connected = connected
    rs.routable = routable
    rs.connection = ConnectionSummary(device_id=device_id)
    rs.routability = RoutabilitySummary(device_id=device_id)
    return rs


def _build_app() -> FastAPI:
    app = FastAPI()
    app.include_router(create_router())
    return app


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------


class TestAuthoritySentinel(unittest.TestCase):
    def test_sentinel_importable_and_nonempty(self):
        self.assertIsInstance(DEVICE_READINESS_ROUTES_AUTHORITY, str)
        self.assertTrue(len(DEVICE_READINESS_ROUTES_AUTHORITY) > 0)

    def test_sentinel_value(self):
        self.assertEqual(DEVICE_READINESS_ROUTES_AUTHORITY, "DEVICE_READINESS_ROUTES_V1")


# ---------------------------------------------------------------------------
# Router structure
# ---------------------------------------------------------------------------


class TestRouterStructure(unittest.TestCase):
    def test_create_router_returns_apirouter(self):
        from fastapi import APIRouter
        r = create_router()
        self.assertIsInstance(r, APIRouter)

    def test_expected_routes_present(self):
        r = create_router()
        paths = {route.path for route in r.routes}
        self.assertIn("/api/v1/devices/readiness", paths)
        self.assertIn("/api/v1/devices/{device_id}/readiness", paths)
        self.assertIn("/api/v1/devices/participation", paths)
        self.assertIn("/api/v1/devices/{device_id}/participation", paths)

    def test_routes_are_get(self):
        r = create_router()
        for route in r.routes:
            if hasattr(route, "methods"):
                self.assertIn("GET", route.methods, f"route {route.path} should be GET")


# ---------------------------------------------------------------------------
# GET /api/v1/devices/readiness  (list)
# ---------------------------------------------------------------------------


class TestListDeviceReadiness(unittest.TestCase):
    def setUp(self):
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_returns_200(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/readiness")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_summaries_and_authority(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/readiness")
        data = resp.json()
        self.assertIn("summaries", data)
        self.assertIn("authority", data)
        self.assertEqual(data["authority"], DEVICE_READINESS_ROUTES_AUTHORITY)

    def test_empty_device_list(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/readiness")
        data = resp.json()
        self.assertEqual(data["summaries"], [])
        self.assertEqual(data["total"], 0)

    def test_returns_summaries_for_known_devices(self):
        rs1 = _make_readiness_summary("dev-01")
        rs2 = _make_readiness_summary("dev-02")
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-01", "dev-02"]):
            with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
                mod = MagicMock()
                mod.get_device_readiness.side_effect = lambda did: (
                    rs1 if did == "dev-01" else rs2
                )
                mock_mod.return_value = mod
                resp = self.client.get("/api/v1/devices/readiness")
        data = resp.json()
        self.assertEqual(data["total"], 2)
        ids = {s["device_id"] for s in data["summaries"]}
        self.assertEqual(ids, {"dev-01", "dev-02"})

    def test_only_ready_filter(self):
        rs_ready = _make_readiness_summary("dev-ready", registered=True, online=True,
                                            connected=True, routable=True)
        rs_not = _make_readiness_summary("dev-not", registered=True, online=False,
                                          connected=False, routable=False)
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-ready", "dev-not"]):
            with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
                mod = MagicMock()
                mod.get_device_readiness.side_effect = lambda did: (
                    rs_ready if did == "dev-ready" else rs_not
                )
                mock_mod.return_value = mod
                resp = self.client.get("/api/v1/devices/readiness?only_ready=true")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["device_id"], "dev-ready")

    def test_only_connected_filter(self):
        rs_conn = _make_readiness_summary("dev-conn", connected=True)
        rs_disc = _make_readiness_summary("dev-disc", connected=False, routable=False)
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-conn", "dev-disc"]):
            with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
                mod = MagicMock()
                mod.get_device_readiness.side_effect = lambda did: (
                    rs_conn if did == "dev-conn" else rs_disc
                )
                mock_mod.return_value = mod
                resp = self.client.get("/api/v1/devices/readiness?only_connected=true")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["device_id"], "dev-conn")

    def test_only_routable_filter(self):
        rs_route = _make_readiness_summary("dev-r", routable=True)
        rs_no = _make_readiness_summary("dev-no", routable=False)
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-r", "dev-no"]):
            with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
                mod = MagicMock()
                mod.get_device_readiness.side_effect = lambda did: (
                    rs_route if did == "dev-r" else rs_no
                )
                mock_mod.return_value = mod
                resp = self.client.get("/api/v1/devices/readiness?only_routable=true")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["device_id"], "dev-r")

    def test_readiness_module_unavailable(self):
        with patch("core.routes.device_readiness._get_readiness_module", return_value=None):
            resp = self.client.get("/api/v1/devices/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("error", data)
        self.assertEqual(data["summaries"], [])

    def test_per_device_exception_returns_partial(self):
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["bad-dev"]):
            with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
                mod = MagicMock()
                mod.get_device_readiness.side_effect = RuntimeError("boom")
                mock_mod.return_value = mod
                resp = self.client.get("/api/v1/devices/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertIn("error", data["summaries"][0])
        self.assertIn("boom", data["summaries"][0]["error"])


# ---------------------------------------------------------------------------
# GET /api/v1/devices/{device_id}/readiness  (single)
# ---------------------------------------------------------------------------


class TestGetDeviceReadiness(unittest.TestCase):
    def setUp(self):
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_returns_200(self):
        rs = _make_readiness_summary("dev-01")
        with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
            mod = MagicMock()
            mod.get_device_readiness.return_value = rs
            mock_mod.return_value = mod
            resp = self.client.get("/api/v1/devices/dev-01/readiness")
        self.assertEqual(resp.status_code, 200)

    def test_payload_contains_expected_fields(self):
        rs = _make_readiness_summary("dev-01")
        with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
            mod = MagicMock()
            mod.get_device_readiness.return_value = rs
            mock_mod.return_value = mod
            resp = self.client.get("/api/v1/devices/dev-01/readiness")
        data = resp.json()
        self.assertEqual(data["device_id"], "dev-01")
        self.assertIn("registered", data)
        self.assertIn("online", data)
        self.assertIn("connected", data)
        self.assertIn("routable", data)
        self.assertEqual(data["authority"], DEVICE_READINESS_ROUTES_AUTHORITY)

    def test_unknown_device_registered_false(self):
        rs = _make_readiness_summary("unknown", registered=False, online=False,
                                      connected=False, routable=False)
        with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
            mod = MagicMock()
            mod.get_device_readiness.return_value = rs
            mock_mod.return_value = mod
            resp = self.client.get("/api/v1/devices/unknown/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["registered"])

    def test_readiness_module_unavailable_returns_partial(self):
        with patch("core.routes.device_readiness._get_readiness_module", return_value=None):
            resp = self.client.get("/api/v1/devices/dev-01/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("error", data)
        self.assertEqual(data["device_id"], "dev-01")

    def test_subsystem_exception_returns_partial(self):
        with patch("core.routes.device_readiness._get_readiness_module") as mock_mod:
            mod = MagicMock()
            mod.get_device_readiness.side_effect = RuntimeError("subsystem down")
            mock_mod.return_value = mod
            resp = self.client.get("/api/v1/devices/dev-01/readiness")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("error", data)
        self.assertFalse(data["registered"])


# ---------------------------------------------------------------------------
# GET /api/v1/devices/participation  (list)
# ---------------------------------------------------------------------------


class TestListDeviceParticipation(unittest.TestCase):
    def setUp(self):
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_returns_200(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/participation")
        self.assertEqual(resp.status_code, 200)

    def test_response_has_summaries_and_authority(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/participation")
        data = resp.json()
        self.assertIn("summaries", data)
        self.assertIn("authority", data)
        self.assertEqual(data["authority"], DEVICE_READINESS_ROUTES_AUTHORITY)

    def test_empty_device_list(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=[]):
            resp = self.client.get("/api/v1/devices/participation")
        data = resp.json()
        self.assertEqual(data["summaries"], [])
        self.assertEqual(data["total"], 0)

    def test_returns_participation_for_known_devices(self):
        dev1 = _make_udm_device("dev-01")
        dev2 = _make_udm_device("dev-02")

        mock_udm = MagicMock()
        mock_udm.get_device.side_effect = lambda did: (
            dev1 if did == "dev-01" else dev2
        )
        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-01", "dev-02"]):
            with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
                from core.device_selection import DeviceParticipationStatus
                mock_status = DeviceParticipationStatus(
                    registered=True,
                    runtime_present=True,
                    routable=True,
                    cross_device_eligible=True,
                    orchestration_eligible=True,
                    participation_reason="all-eligible",
                )
                with patch("core.routes.device_readiness.assess_device_participation",
                           return_value=mock_status, create=True):
                    # Use _get_participation_for_device directly via route
                    resp = self.client.get("/api/v1/devices/participation")
        data = resp.json()
        self.assertEqual(data["total"], 2)

    def test_only_ready_filter(self):
        """only_ready=true should exclude non-orchestration-eligible devices."""
        def mock_participation(device_id: str):
            if device_id == "dev-ready":
                return {
                    "device_id": device_id,
                    "orchestration_eligible": True,
                    "cross_device_eligible": True,
                    "registered": True,
                    "participation_reason": "all-eligible",
                    "sources": [],
                }
            return {
                "device_id": device_id,
                "orchestration_eligible": False,
                "cross_device_eligible": False,
                "registered": False,
                "participation_reason": "device_not_found",
                "sources": [],
            }

        with patch("core.routes.device_readiness._list_all_device_ids",
                   return_value=["dev-ready", "dev-not"]):
            with patch("core.routes.device_readiness._get_participation_for_device",
                       side_effect=mock_participation):
                resp = self.client.get("/api/v1/devices/participation?only_ready=true")
        data = resp.json()
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["device_id"], "dev-ready")

    def test_udm_unavailable_returns_empty(self):
        with patch("core.routes.device_readiness._list_all_device_ids", return_value=["x"]):
            with patch("core.routes.device_readiness._get_udm", return_value=None):
                resp = self.client.get("/api/v1/devices/participation")
        data = resp.json()
        # Should return a partial summary with udm_unavailable reason, not crash
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["summaries"][0]["participation_reason"], "udm_unavailable")


# ---------------------------------------------------------------------------
# GET /api/v1/devices/{device_id}/participation  (single)
# ---------------------------------------------------------------------------


class TestGetDeviceParticipation(unittest.TestCase):
    def setUp(self):
        self.app = _build_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_returns_200(self):
        dev = _make_udm_device("dev-01")
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = dev
        with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
            from core.device_selection import DeviceParticipationStatus
            mock_status = DeviceParticipationStatus(
                registered=True,
                runtime_present=True,
                routable=True,
                cross_device_eligible=True,
                orchestration_eligible=True,
                participation_reason="all-eligible",
            )
            with patch("core.device_selection.assess_device_participation",
                       return_value=mock_status):
                resp = self.client.get("/api/v1/devices/dev-01/participation")
        self.assertEqual(resp.status_code, 200)

    def test_payload_has_expected_fields(self):
        dev = _make_udm_device("dev-01")
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = dev
        with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
            from core.device_selection import DeviceParticipationStatus
            mock_status = DeviceParticipationStatus(
                registered=True,
                runtime_present=True,
                routable=True,
                cross_device_eligible=True,
                orchestration_eligible=True,
                participation_reason="all-eligible",
            )
            with patch("core.device_selection.assess_device_participation",
                       return_value=mock_status):
                resp = self.client.get("/api/v1/devices/dev-01/participation")
        data = resp.json()
        self.assertEqual(data["device_id"], "dev-01")
        self.assertIn("registered", data)
        self.assertIn("cross_device_eligible", data)
        self.assertIn("orchestration_eligible", data)
        self.assertIn("participation_reason", data)
        self.assertEqual(data["authority"], DEVICE_READINESS_ROUTES_AUTHORITY)

    def test_unknown_device_returns_partial_not_error(self):
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = None
        with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
            resp = self.client.get("/api/v1/devices/unknown-device/participation")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["device_id"], "unknown-device")
        self.assertFalse(data["registered"])
        self.assertEqual(data["participation_reason"], "device_not_found")

    def test_udm_unavailable_returns_partial(self):
        with patch("core.routes.device_readiness._get_udm", return_value=None):
            resp = self.client.get("/api/v1/devices/dev-01/participation")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["registered"])
        self.assertIn("udm_unavailable", data["participation_reason"])

    def test_assess_exception_returns_partial(self):
        dev = _make_udm_device("dev-01")
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = dev
        with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
            with patch("core.device_selection.assess_device_participation",
                       side_effect=RuntimeError("assess failed")):
                resp = self.client.get("/api/v1/devices/dev-01/participation")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("assessment_error", data["participation_reason"])

    def test_all_participation_flags_present(self):
        dev = _make_udm_device("dev-01")
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = dev
        with patch("core.routes.device_readiness._get_udm", return_value=mock_udm):
            from core.device_selection import DeviceParticipationStatus
            mock_status = DeviceParticipationStatus(
                registered=True,
                runtime_present=False,
                routable=False,
                cross_device_eligible=False,
                orchestration_eligible=False,
                participation_reason="not-runtime-present; not-routable(canonical-connection)",
            )
            with patch("core.device_selection.assess_device_participation",
                       return_value=mock_status):
                resp = self.client.get("/api/v1/devices/dev-01/participation")
        data = resp.json()
        self.assertTrue(data["registered"])
        self.assertFalse(data["runtime_present"])
        self.assertFalse(data["routable"])
        self.assertFalse(data["cross_device_eligible"])
        self.assertFalse(data["orchestration_eligible"])
        self.assertIn("not-runtime-present", data["participation_reason"])


if __name__ == "__main__":
    unittest.main()
