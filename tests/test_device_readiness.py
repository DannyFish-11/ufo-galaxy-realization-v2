"""
tests/test_device_readiness.py
==============================
Focused tests for ``core.device_readiness`` — the canonical device
readiness aggregation layer (PR-1).

Coverage:
  - Models serialise correctly via ``to_dict()``.
  - ``get_device_readiness`` returns registered=True/online=True for a
    known, online device.
  - ``get_device_readiness`` returns registered=False for an unknown device.
  - Connection/routing sub-summaries degrade gracefully when subsystems
    are unavailable (ImportError / RuntimeError).
  - ``get_cross_device_ready_devices()`` filters by all four readiness
    fields consistently.
  - ``is_device_cross_device_ready()`` mirrors the filter correctly.
  - Authority sentinel is importable and non-empty.
"""

from __future__ import annotations

import sys
import os
import unittest
from dataclasses import asdict
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.device_readiness import (
    ConnectionSummary,
    RoutabilitySummary,
    DeviceReadinessSummary,
    DEVICE_READINESS_AUTHORITY,
    get_connection_summary,
    get_routability_summary,
    get_device_readiness,
    get_cross_device_ready_devices,
    is_device_cross_device_ready,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_udm_device(device_id: str, status: str = "online", capabilities=None):
    """Return a minimal mock UnifiedDevice-like object."""
    device = MagicMock()
    device.device_id = device_id
    device.status = status
    device.capabilities = capabilities if capabilities is not None else ["touch", "screen"]
    device.device_type = "android"
    return device


def _make_conn_info(device_id: str, state: str = "connected", routable: bool = True):
    """Return a minimal mock UnifiedConnectionInfo-like object."""
    info = MagicMock()
    info.state = state
    info.routable = routable
    info.connection_id = f"conn-{device_id}"
    info.last_heartbeat = None
    return info


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestConnectionSummaryModel(unittest.TestCase):
    def test_to_dict_contains_expected_keys(self):
        cs = ConnectionSummary(device_id="dev1")
        d = cs.to_dict()
        for key in (
            "device_id", "websocket_connected", "ucm_connected",
            "router_present", "connection_state", "local_connection_id",
            "last_heartbeat_at", "reasons", "sources",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_device_id(self):
        cs = ConnectionSummary(device_id="my-device")
        self.assertEqual(cs.to_dict()["device_id"], "my-device")

    def test_to_dict_default_values(self):
        cs = ConnectionSummary(device_id="d")
        d = cs.to_dict()
        self.assertFalse(d["websocket_connected"])
        self.assertFalse(d["ucm_connected"])
        self.assertEqual(d["connection_state"], "disconnected")
        self.assertIsNone(d["local_connection_id"])
        self.assertEqual(d["reasons"], [])
        self.assertEqual(d["sources"], {})


class TestRoutabilitySummaryModel(unittest.TestCase):
    def test_to_dict_contains_expected_keys(self):
        rs = RoutabilitySummary(device_id="dev1")
        d = rs.to_dict()
        for key in (
            "device_id", "direct_ws_available", "ucm_send_available",
            "relay_available", "mesh_direct_available", "mesh_relay_available",
            "effective_routable", "preferred_path", "reasons", "sources",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_to_dict_defaults_false(self):
        rs = RoutabilitySummary(device_id="d")
        d = rs.to_dict()
        self.assertFalse(d["direct_ws_available"])
        self.assertFalse(d["effective_routable"])
        self.assertEqual(d["preferred_path"], "none")


class TestDeviceReadinessSummaryModel(unittest.TestCase):
    def test_to_dict_contains_expected_keys(self):
        drs = DeviceReadinessSummary(device_id="dev1")
        drs.connection = ConnectionSummary(device_id="dev1")
        drs.routability = RoutabilitySummary(device_id="dev1")
        d = drs.to_dict()
        for key in (
            "device_id", "registered", "online", "connected", "routable",
            "capability_ready", "connection", "routability", "reasons", "sources",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_nested_to_dict(self):
        drs = DeviceReadinessSummary(device_id="dev1")
        drs.connection = ConnectionSummary(device_id="dev1")
        drs.routability = RoutabilitySummary(device_id="dev1")
        d = drs.to_dict()
        self.assertIsInstance(d["connection"], dict)
        self.assertIsInstance(d["routability"], dict)

    def test_authority_sentinel(self):
        self.assertIsInstance(DEVICE_READINESS_AUTHORITY, str)
        self.assertTrue(len(DEVICE_READINESS_AUTHORITY) > 0)


# ---------------------------------------------------------------------------
# get_device_readiness — registered+online device
# ---------------------------------------------------------------------------


class TestGetDeviceReadinessRegisteredOnline(unittest.TestCase):
    """Registered+online device produces correct readiness summary."""

    def _run(self, status: str, expect_online: bool, caps=None):
        device = _make_udm_device("dev-online", status=status, capabilities=caps)
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = device

        conn_info = _make_conn_info("dev-online", state="connected", routable=True)
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = conn_info
        mock_ucm.is_device_connected.return_value = True

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-online")

        self.assertTrue(rs.registered, "Should be registered")
        self.assertEqual(rs.online, expect_online, f"online mismatch for status={status}")
        self.assertTrue(rs.connected, "Should be connected")

    def test_online_status(self):
        self._run("online", True)

    def test_busy_status(self):
        self._run("busy", True)

    def test_offline_status(self):
        self._run("offline", False)

    def test_capability_ready_when_caps_present(self):
        device = _make_udm_device("dev-caps", status="online", capabilities=["touch"])
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = device
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = None
        mock_ucm.is_device_connected.return_value = False

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-caps")

        self.assertTrue(rs.capability_ready)

    def test_capability_not_ready_when_no_caps(self):
        device = _make_udm_device("dev-nocaps", status="online", capabilities=[])
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = device
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = None
        mock_ucm.is_device_connected.return_value = False

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-nocaps")

        self.assertFalse(rs.capability_ready)

    def test_sources_contain_udm_entry(self):
        device = _make_udm_device("dev-src", status="online")
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = device
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = None
        mock_ucm.is_device_connected.return_value = False

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-src")

        self.assertIn("udm", rs.sources)


# ---------------------------------------------------------------------------
# get_device_readiness — missing device
# ---------------------------------------------------------------------------


class TestGetDeviceReadinessMissingDevice(unittest.TestCase):
    """Missing device returns registered=False."""

    def test_missing_device_not_registered(self):
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = None

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("nonexistent-device")

        self.assertFalse(rs.registered)
        self.assertFalse(rs.online)
        self.assertIn("device_not_registered", rs.reasons)

    def test_missing_device_not_connected(self):
        mock_udm = MagicMock()
        mock_udm.get_device.return_value = None
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = None
        mock_ucm.is_device_connected.return_value = False

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("ghost-device")

        self.assertFalse(rs.connected)

    def test_udm_unavailable_returns_not_registered(self):
        with patch("core.device_readiness._get_udm", return_value=None), \
             patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("any-device")

        self.assertFalse(rs.registered)
        self.assertIn("udm_unavailable", rs.reasons)


# ---------------------------------------------------------------------------
# Graceful degradation tests
# ---------------------------------------------------------------------------


class TestConnectionSummaryDegradation(unittest.TestCase):
    """Connection sub-summary degrades gracefully when subsystems unavailable."""

    def test_ucm_unavailable_records_reason(self):
        with patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            cs = get_connection_summary("dev-x")

        self.assertFalse(cs.ucm_connected)
        self.assertIn("ucm_unavailable", cs.reasons)

    def test_ucm_query_raises_records_reason(self):
        mock_ucm = MagicMock()
        mock_ucm.get_connection.side_effect = RuntimeError("db error")

        with patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            cs = get_connection_summary("dev-err")

        self.assertFalse(cs.ucm_connected)
        self.assertTrue(any("ucm_query_error" in r for r in cs.reasons))

    def test_no_ucm_no_crash(self):
        """Full get_device_readiness must not raise even when all subsystems absent."""
        with patch("core.device_readiness._get_udm", return_value=None), \
             patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("isolated-device")

        self.assertIsInstance(rs, DeviceReadinessSummary)

    def test_gateway_ws_raises_no_crash(self):
        mock_gw = MagicMock()
        mock_gw.get_connected_devices.side_effect = RuntimeError("gw crash")

        with patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=mock_gw), \
             patch("core.device_readiness._get_device_router", return_value=None):
            cs = get_connection_summary("gw-err-device")

        self.assertIsInstance(cs, ConnectionSummary)


class TestRoutabilitySummaryDegradation(unittest.TestCase):
    """Routability sub-summary degrades gracefully."""

    def test_ucm_unavailable_records_reason(self):
        with patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None):
            rs = get_routability_summary("dev-r")

        self.assertIn("ucm_unavailable", rs.reasons)

    def test_relay_present_makes_routable(self):
        """When proxy_relay module is importable, relay path is available."""
        with patch("core.device_readiness._get_ucm", return_value=None), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None):
            rs = get_routability_summary("dev-relay")

        # proxy_relay exists in this codebase
        if rs.relay_available:
            self.assertTrue(rs.effective_routable)
            self.assertIn(rs.preferred_path, ("relay", "mesh_direct", "direct_ws", "ucm"))

    def test_no_paths_not_routable(self):
        """When no transport modules are available the device is not routable."""
        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = None

        with patch("core.device_readiness._get_ucm", return_value=mock_ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch.dict("sys.modules", {
                 "core.proxy_relay": None,
                 "core.mesh_coordinator": None,
             }):
            rs = get_routability_summary("dev-no-path")

        self.assertFalse(rs.direct_ws_available)
        self.assertFalse(rs.relay_available)
        self.assertFalse(rs.mesh_direct_available)
        self.assertFalse(rs.effective_routable)
        self.assertEqual(rs.preferred_path, "none")


# ---------------------------------------------------------------------------
# get_cross_device_ready_devices
# ---------------------------------------------------------------------------


class TestGetCrossDeviceReadyDevices(unittest.TestCase):
    """get_cross_device_ready_devices() filters by all readiness fields."""

    def _build_ready_rs(self, device_id: str) -> DeviceReadinessSummary:
        rs = DeviceReadinessSummary(device_id=device_id)
        rs.registered = True
        rs.online = True
        rs.connected = True
        rs.routable = True
        rs.connection = ConnectionSummary(device_id=device_id)
        rs.routability = RoutabilitySummary(device_id=device_id)
        return rs

    def _build_not_ready_rs(self, device_id: str, **flags) -> DeviceReadinessSummary:
        rs = self._build_ready_rs(device_id)
        for k, v in flags.items():
            setattr(rs, k, v)
        return rs

    def test_all_fields_required(self):
        """Each of registered/online/connected/routable must be True."""
        for missing_flag in ("registered", "online", "connected", "routable"):
            dev_id = f"dev-missing-{missing_flag}"
            device = _make_udm_device(dev_id, status="online")
            mock_udm = MagicMock()
            mock_udm.list_devices.return_value = [device]

            not_ready_rs = self._build_not_ready_rs(dev_id, **{missing_flag: False})
            with patch("core.device_readiness._get_udm", return_value=mock_udm), \
                 patch("core.device_readiness.get_device_readiness", return_value=not_ready_rs):
                result = get_cross_device_ready_devices()
            self.assertEqual(result, [], f"Should be empty when {missing_flag}=False")

    def test_returns_only_ready_devices(self):
        dev_a = _make_udm_device("dev-a", status="online")
        dev_b = _make_udm_device("dev-b", status="online")
        mock_udm = MagicMock()
        mock_udm.list_devices.return_value = [dev_a, dev_b]

        ready_a = self._build_ready_rs("dev-a")
        not_ready_b = self._build_not_ready_rs("dev-b", connected=False)

        def _fake_readiness(device_id):
            return ready_a if device_id == "dev-a" else not_ready_b

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness.get_device_readiness", side_effect=_fake_readiness):
            result = get_cross_device_ready_devices()

        device_ids = [rs.device_id for rs in result]
        self.assertIn("dev-a", device_ids)
        self.assertNotIn("dev-b", device_ids)

    def test_udm_unavailable_returns_empty(self):
        with patch("core.device_readiness._get_udm", return_value=None):
            result = get_cross_device_ready_devices()
        self.assertEqual(result, [])

    def test_list_devices_fails_returns_empty(self):
        mock_udm = MagicMock()
        mock_udm.list_devices.side_effect = RuntimeError("db crash")
        with patch("core.device_readiness._get_udm", return_value=mock_udm):
            result = get_cross_device_ready_devices()
        self.assertEqual(result, [])

    def test_single_device_eval_failure_skipped(self):
        """One device failing evaluation should not abort the whole list."""
        dev_a = _make_udm_device("dev-a", status="online")
        dev_b = _make_udm_device("dev-b", status="online")
        mock_udm = MagicMock()
        mock_udm.list_devices.return_value = [dev_a, dev_b]

        ready_a = self._build_ready_rs("dev-a")

        def _fake_readiness(device_id):
            if device_id == "dev-b":
                raise RuntimeError("per-device crash")
            return ready_a

        with patch("core.device_readiness._get_udm", return_value=mock_udm), \
             patch("core.device_readiness.get_device_readiness", side_effect=_fake_readiness):
            result = get_cross_device_ready_devices()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].device_id, "dev-a")

    def test_empty_registry_returns_empty(self):
        mock_udm = MagicMock()
        mock_udm.list_devices.return_value = []
        with patch("core.device_readiness._get_udm", return_value=mock_udm):
            result = get_cross_device_ready_devices()
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# is_device_cross_device_ready
# ---------------------------------------------------------------------------


class TestIsDeviceCrossDeviceReady(unittest.TestCase):
    """is_device_cross_device_ready mirrors filter logic from get_cross_device_ready_devices."""

    def _ready_rs(self) -> DeviceReadinessSummary:
        rs = DeviceReadinessSummary(device_id="d1")
        rs.registered = True
        rs.online = True
        rs.connected = True
        rs.routable = True
        rs.connection = ConnectionSummary(device_id="d1")
        rs.routability = RoutabilitySummary(device_id="d1")
        return rs

    def test_all_true_returns_true(self):
        with patch("core.device_readiness.get_device_readiness", return_value=self._ready_rs()):
            self.assertTrue(is_device_cross_device_ready("d1"))

    def test_any_false_returns_false(self):
        for flag in ("registered", "online", "connected", "routable"):
            rs = self._ready_rs()
            setattr(rs, flag, False)
            with patch("core.device_readiness.get_device_readiness", return_value=rs):
                result = is_device_cross_device_ready("d1")
            self.assertFalse(result, f"Should be False when {flag}=False")

    def test_exception_returns_false(self):
        with patch(
            "core.device_readiness.get_device_readiness",
            side_effect=RuntimeError("crash"),
        ):
            self.assertFalse(is_device_cross_device_ready("d1"))


if __name__ == "__main__":
    unittest.main()
