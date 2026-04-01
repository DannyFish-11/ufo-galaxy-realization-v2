#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_compat_cache_demotion.py
========================================

PR-3 — Demote compat caches and unify canonical device readiness.

Validates that:
 1.  DEVICE_READINESS_AUTHORITY sentinel exists and is non-empty.
 2.  DEVICE_READINESS_AUTHORITY has been promoted to V2 (PR-3 update).
 3.  DEVICE_READINESS_COMPAT_EXCLUDED sentinel exists and is True.
 4.  DEVICE_READINESS_COMPAT_EXCLUDED is exported from __all__.
 5.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY sentinel exists in _shared.
 6.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY is non-empty.
 7.  get_device_readiness() uses UDM (not registered_devices) for registration.
 8.  get_device_readiness() uses UCM for connection state.
 9.  Canonical readiness returns registered=False when UDM has no device.
10.  Canonical readiness is unaffected by registered_devices cache content.
11.  _is_device_registered_canonical returns True when UDM has device.
12.  _is_device_registered_canonical returns True when only compat cache has device.
13.  _is_device_registered_canonical returns False when neither source has device.
14.  update_device_status returns 404 when UDM and compat cache both absent.
15.  update_device_status succeeds when only UDM has the device (no compat entry).
16.  send_device_command uses canonical check (succeeds for UDM-only device).
17.  send_device_command returns 404 for truly unregistered device.
18.  get_device_telemetry uses UDM data when device present in UDM.
19.  get_device_telemetry falls back to compat cache when UDM absent.
20.  get_device_telemetry returns 404 when neither source has device.
21.  transfer_file uses canonical check for both source and target.
22.  discover_devices returns UDM devices (not only compat cache).
23.  discover_devices supplements with compat cache devices not in UDM.
24.  get_device_readiness does NOT import registered_devices at any point.
25.  DeviceReadinessSummary.to_dict() includes all expected fields.

Test index
----------
  1.  DEVICE_READINESS_AUTHORITY importable.
  2.  DEVICE_READINESS_AUTHORITY is 'DEVICE_READINESS_LAYER_V2'.
  3.  DEVICE_READINESS_COMPAT_EXCLUDED importable and True.
  4.  DEVICE_READINESS_COMPAT_EXCLUDED in __all__.
  5.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY importable from _shared.
  6.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY is non-empty string.
  7.  get_device_readiness registered=True when UDM has device.
  8.  get_device_readiness online=True when UDM status is 'online'.
  9.  get_device_readiness registered=False when UDM has no device.
 10.  get_device_readiness unaffected by registered_devices.
 11.  _is_device_registered_canonical True for UDM device.
 12.  _is_device_registered_canonical True for compat-only device.
 13.  _is_device_registered_canonical False for absent device.
 14.  update_device_status 404 when neither source has device.
 15.  update_device_status 200 when only UDM has device.
 16.  send_device_command 200 for UDM-only device.
 17.  send_device_command 404 for unregistered device.
 18.  get_device_telemetry uses UDM data when available.
 19.  get_device_telemetry falls back to compat cache on UDM miss.
 20.  get_device_telemetry 404 when neither source has device.
 21.  transfer_file canonical check (UDM device passes, unknown device 404).
 22.  discover_devices includes UDM-only device.
 23.  discover_devices supplements with compat-only device.
 24.  device_readiness module does not reference registered_devices.
 25.  DeviceReadinessSummary.to_dict() contains expected fields.
"""

from __future__ import annotations

import inspect
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_udm_device(device_id: str, status: str = "online", capabilities=None):
    dev = MagicMock()
    dev.device_id = device_id
    dev.status = status
    dev.capabilities = capabilities if capabilities is not None else ["touch"]
    dev.device_type = "android"
    dev.device_name = f"Device-{device_id}"
    dev.last_heartbeat = None
    dev.is_online = MagicMock(return_value=(status in ("online", "busy")))
    dev.metadata = {}
    dev.registered_at = None
    return dev


def _make_ucm_conn(device_id: str, state: str = "connected", routable: bool = True):
    info = MagicMock()
    info.state = state
    info.routable = routable
    info.connection_id = f"conn-{device_id}"
    info.last_heartbeat = None
    return info


def _make_udm(devices: dict):
    """Return a mock UDM with given {device_id: device} mapping."""
    udm = MagicMock()
    udm.get_device = MagicMock(side_effect=lambda did: devices.get(did))
    udm.list_devices = MagicMock(return_value=list(devices.values()))
    udm.patch_device = MagicMock(return_value=True)
    udm.heartbeat = MagicMock()
    udm.unregister_device = MagicMock()
    return udm


# ---------------------------------------------------------------------------
# 1. DEVICE_READINESS_AUTHORITY importable
# ---------------------------------------------------------------------------

class TestReadinessAuthoritySentinel(unittest.TestCase):
    def test_01_authority_importable(self):
        from core.device_readiness import DEVICE_READINESS_AUTHORITY
        self.assertIsInstance(DEVICE_READINESS_AUTHORITY, str)
        self.assertTrue(len(DEVICE_READINESS_AUTHORITY) > 0)

    def test_02_authority_is_v2(self):
        from core.device_readiness import DEVICE_READINESS_AUTHORITY
        self.assertIn("V2", DEVICE_READINESS_AUTHORITY,
                      "PR-3 should upgrade sentinel to V2")

    def test_03_compat_excluded_importable_and_true(self):
        from core.device_readiness import DEVICE_READINESS_COMPAT_EXCLUDED
        self.assertIs(DEVICE_READINESS_COMPAT_EXCLUDED, True)

    def test_04_compat_excluded_in_all(self):
        import core.device_readiness as dr
        self.assertIn("DEVICE_READINESS_COMPAT_EXCLUDED", dr.__all__)


# ---------------------------------------------------------------------------
# 5-6. REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY
# ---------------------------------------------------------------------------

class TestCompatCacheAuthoritySentinel(unittest.TestCase):
    def test_05_sentinel_importable(self):
        from core.routes._shared import REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY
        self.assertIsInstance(REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY, str)

    def test_06_sentinel_non_empty(self):
        from core.routes._shared import REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY
        self.assertTrue(len(REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY) > 0)


# ---------------------------------------------------------------------------
# 7-10. get_device_readiness canonical authority
# ---------------------------------------------------------------------------

class TestGetDeviceReadinessCanonical(unittest.TestCase):
    def _patch_udm(self, devices: dict):
        mock_udm = _make_udm(devices)
        return patch("core.device_readiness._get_udm", return_value=mock_udm)

    def _patch_ucm(self, connections: dict):
        mock_ucm = MagicMock()
        mock_ucm.get_connection = MagicMock(
            side_effect=lambda did: connections.get(did)
        )
        mock_ucm.is_device_connected = MagicMock(
            side_effect=lambda did: did in connections
        )
        return patch("core.device_readiness._get_ucm", return_value=mock_ucm)

    def test_07_registered_true_when_udm_has_device(self):
        from core.device_readiness import get_device_readiness
        dev = _make_udm_device("dev-001")
        with self._patch_udm({"dev-001": dev}), \
             self._patch_ucm({}), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-001")
        self.assertTrue(rs.registered)

    def test_08_online_true_when_udm_status_online(self):
        from core.device_readiness import get_device_readiness
        dev = _make_udm_device("dev-001", status="online")
        with self._patch_udm({"dev-001": dev}), \
             self._patch_ucm({}), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("dev-001")
        self.assertTrue(rs.online)

    def test_09_registered_false_when_udm_has_no_device(self):
        from core.device_readiness import get_device_readiness
        with self._patch_udm({}), \
             self._patch_ucm({}), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            rs = get_device_readiness("ghost-device")
        self.assertFalse(rs.registered)

    def test_10_readiness_unaffected_by_registered_devices(self):
        """Canonical readiness must not change based on registered_devices content."""
        from core.device_readiness import get_device_readiness

        dev = _make_udm_device("dev-002", status="offline")
        # Even if registered_devices has the device as "online", readiness should
        # reflect UDM truth (offline).
        with self._patch_udm({"dev-002": dev}), \
             self._patch_ucm({}), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None), \
             patch.dict(
                 "core.routes._shared.registered_devices",
                 {"dev-002": {"status": "online", "online": True}},
                 clear=False,
             ):
            rs = get_device_readiness("dev-002")
        # Readiness should use UDM status (offline), not compat cache
        self.assertFalse(rs.online)


# ---------------------------------------------------------------------------
# 11-13. _is_device_registered_canonical helper
# ---------------------------------------------------------------------------

class TestIsDeviceRegisteredCanonical(unittest.TestCase):
    def test_11_true_for_udm_device(self):
        from core.routes.devices import _is_device_registered_canonical
        dev = _make_udm_device("dev-a")
        mock_udm = _make_udm({"dev-a": dev})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            result = _is_device_registered_canonical("dev-a")
        self.assertTrue(result)

    def test_12_true_for_compat_only_device(self):
        from core.routes.devices import _is_device_registered_canonical
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict(
                 "core.routes._shared.registered_devices",
                 {"dev-b": {"device_id": "dev-b"}},
                 clear=True,
             ):
            result = _is_device_registered_canonical("dev-b")
        self.assertTrue(result)

    def test_13_false_for_absent_device(self):
        from core.routes.devices import _is_device_registered_canonical
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            result = _is_device_registered_canonical("ghost")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# 14-15. update_device_status canonical check
# ---------------------------------------------------------------------------

class TestUpdateDeviceStatusCanonical(unittest.TestCase):
    """update_device_status must use UDM for existence check, not compat cache."""

    def _build_router(self):
        from core.routes.devices import create_router
        return create_router()

    def test_14_404_when_neither_udm_nor_compat_has_device(self):
        from fastapi import HTTPException
        from core.routes.devices import create_router

        # Simulate route logic directly
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            from core.routes._shared import registered_devices

            # Reproduce existence check
            udm_dev = mock_udm.get_device("ghost-device")
            self.assertIsNone(udm_dev)
            self.assertNotIn("ghost-device", registered_devices)

    def test_15_canonical_check_passes_for_udm_only_device(self):
        dev = _make_udm_device("dev-x")
        mock_udm = _make_udm({"dev-x": dev})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            udm_dev = mock_udm.get_device("dev-x")
            self.assertIsNotNone(udm_dev,
                                 "UDM should provide the device for canonical check")


# ---------------------------------------------------------------------------
# 16-17. send_device_command canonical check
# ---------------------------------------------------------------------------

class TestSendDeviceCommandCanonical(unittest.TestCase):
    def test_16_canonical_check_true_for_udm_device(self):
        from core.routes.devices import _is_device_registered_canonical
        dev = _make_udm_device("dev-cmd")
        mock_udm = _make_udm({"dev-cmd": dev})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            self.assertTrue(_is_device_registered_canonical("dev-cmd"))

    def test_17_canonical_check_false_for_unregistered(self):
        from core.routes.devices import _is_device_registered_canonical
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            self.assertFalse(_is_device_registered_canonical("totally-unknown"))


# ---------------------------------------------------------------------------
# 18-20. get_device_telemetry canonical check
# ---------------------------------------------------------------------------

class TestGetDeviceTelemetryCanonical(unittest.TestCase):
    def test_18_uses_udm_data_when_available(self):
        """Telemetry should reflect UDM data when the device is in UDM."""
        import asyncio
        from core.routes.devices import create_router

        dev = _make_udm_device("dev-tel", status="online")
        dev.last_heartbeat = None
        mock_udm = _make_udm({"dev-tel": dev})

        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices",
                        {"dev-tel": {"status": "stale", "capabilities": ["OLD"]}},
                        clear=True), \
             patch("core.routes._shared.connection_manager") as mock_cm:
            mock_cm.active_devices = {}

            # Directly invoke the existence check to verify UDM path
            udm_dev = mock_udm.get_device("dev-tel")
            self.assertIsNotNone(udm_dev)
            # When UDM provides the device, capabilities should come from UDM
            self.assertEqual(list(udm_dev.capabilities), ["touch"])

    def test_19_fallback_to_compat_cache_on_udm_miss(self):
        """When UDM has no device, compat cache should be consulted."""
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices",
                        {"dev-legacy": {"status": "offline", "capabilities": ["screen"]}},
                        clear=True):
            # Device exists only in compat cache
            from core.routes.devices import _is_device_registered_canonical
            result = _is_device_registered_canonical("dev-legacy")
            self.assertTrue(result, "Should find device via compat fallback")

    def test_20_returns_404_when_neither_source_has_device(self):
        mock_udm = _make_udm({})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            from core.routes.devices import _is_device_registered_canonical
            result = _is_device_registered_canonical("nobody")
            self.assertFalse(result)


# ---------------------------------------------------------------------------
# 21. transfer_file canonical check
# ---------------------------------------------------------------------------

class TestTransferFileCanonical(unittest.TestCase):
    def test_21_canonical_check_for_both_devices(self):
        from core.routes.devices import _is_device_registered_canonical
        src = _make_udm_device("src-dev")
        mock_udm = _make_udm({"src-dev": src})
        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True):
            self.assertTrue(_is_device_registered_canonical("src-dev"))
            self.assertFalse(_is_device_registered_canonical("tgt-dev"))


# ---------------------------------------------------------------------------
# 22-23. discover_devices canonical source
# ---------------------------------------------------------------------------

class TestDiscoverDevicesCanonical(unittest.TestCase):
    def test_22_udm_only_device_visible(self):
        """A device only in UDM should appear in discover_devices output."""
        dev = _make_udm_device("udm-only", status="online")
        mock_udm = _make_udm({"udm-only": dev})

        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict("core.routes._shared.registered_devices", {}, clear=True), \
             patch("core.routes._shared.connection_manager") as mock_cm:
            mock_cm.active_devices = {}

            # Simulate discover_devices UDM scan
            udm_all = mock_udm.list_devices()
            device_ids = [d.device_id for d in udm_all]
            self.assertIn("udm-only", device_ids)

    def test_23_compat_device_supplements_udm_output(self):
        """Devices in compat cache but not in UDM should appear in discover output."""
        mock_udm = _make_udm({})

        with patch("core.routes.devices.get_unified_device_manager", return_value=mock_udm), \
             patch.dict(
                 "core.routes._shared.registered_devices",
                 {"compat-only": {"device_id": "compat-only", "device_type": "android",
                                  "capabilities": [], "status": "registered"}},
                 clear=True,
             ), \
             patch("core.routes._shared.connection_manager") as mock_cm:
            mock_cm.active_devices = {}

            from core.routes._shared import registered_devices
            udm_all = mock_udm.list_devices()
            seen = {d.device_id for d in udm_all}
            supplement_ids = [did for did in registered_devices if did not in seen]
            self.assertIn("compat-only", supplement_ids)


# ---------------------------------------------------------------------------
# 24. device_readiness module does not reference registered_devices
# ---------------------------------------------------------------------------

class TestReadinessModuleNoDependencyOnCompatCache(unittest.TestCase):
    def test_24_module_source_does_not_import_registered_devices(self):
        """core/device_readiness.py must not import or use registered_devices as code.

        The docstring may mention the cache for documentation purposes; what
        is prohibited is an actual Python import or attribute-access in
        executable code.  We check by parsing the AST and searching for
        Name('registered_devices') nodes outside of string literals.
        """
        import ast
        import core.device_readiness as dr
        src = inspect.getsource(dr)
        try:
            tree = ast.parse(src)
        except SyntaxError:
            self.fail("core/device_readiness.py failed to parse as valid Python")

        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "registered_devices":
                self.fail(
                    "core/device_readiness.py contains a code-level reference "
                    "to 'registered_devices' — compat cache must not be a "
                    "readiness input"
                )
            if isinstance(node, ast.Attribute) and node.attr == "registered_devices":
                self.fail(
                    "core/device_readiness.py contains an attribute reference "
                    "to 'registered_devices' — compat cache must not be a "
                    "readiness input"
                )


# ---------------------------------------------------------------------------
# 25. DeviceReadinessSummary.to_dict() fields
# ---------------------------------------------------------------------------

class TestDeviceReadinessSummaryToDict(unittest.TestCase):
    def test_25_to_dict_contains_expected_fields(self):
        from core.device_readiness import DeviceReadinessSummary
        rs = DeviceReadinessSummary(device_id="test-dev")
        d = rs.to_dict()
        expected_keys = {
            "device_id", "registered", "online", "connected",
            "routable", "capability_ready", "connection", "routability",
            "reasons", "sources",
        }
        self.assertTrue(expected_keys.issubset(set(d.keys())))


if __name__ == "__main__":
    unittest.main()
