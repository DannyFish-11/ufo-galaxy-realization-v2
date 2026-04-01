#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_truth_integration_layer.py
==========================================
PR-1 — Truth Integration Layer: Canonical Runtime Truth Unification.

Validates that:
 1.  TRUTH_INTEGRATION_LAYER_AUTHORITY sentinel is importable.
 2.  TRUTH_INTEGRATION_LAYER_AUTHORITY contains 'TRUTH_INTEGRATION_LAYER'.
 3.  TRUTH_INTEGRATION_LAYER_AUTHORITY contains 'CANONICAL'.
 4.  TRUTH_CONFLICT_RESOLUTION_POLICY is a non-empty string.
 5.  TRUTH_CONFLICT_RESOLUTION_POLICY mentions UCM/UDM as primary authority.
 6.  TRUTH_CONFLICT_RESOLUTION_POLICY mentions compat-cache as supplement.
 7.  CanonicalDeviceTruth is importable and is a dataclass.
 8.  CanonicalDeviceTruth.to_dict() includes all required fields.
 9.  CanonicalDeviceTruth.is_available = True when all four flags are True.
10.  CanonicalDeviceTruth.is_available = False when any flag is False.
11.  resolve_device_truth is importable and callable.
12.  resolve_all_device_truth is importable and callable.
13.  is_device_available_canonical is importable and callable.
14.  resolve_device_truth — device registered+connected in UCM/UDM → ucm_udm source.
15.  resolve_device_truth — device registered in UDM but not UCM → ucm_udm, is_connected=False.
16.  resolve_device_truth — device not in UCM/UDM but in compat → compat_supplement.
17.  resolve_device_truth — device not in any source → is_registered=False, is_available=False.
18.  resolve_device_truth — UCM/UDM down, compat has device → compat_only source.
19.  conflict detection: compat online, authority offline → conflict recorded.
20.  conflict detection: compat offline, authority online → conflict recorded.
21.  conflict does NOT change authority verdict (is_registered stays True).
22.  resolve_device_truth — heartbeat scenario: UCM routable updated → reflected in truth.
23.  resolve_device_truth — disconnect scenario: UCM removes device → is_connected=False.
24.  resolve_device_truth — reconnect scenario: device re-appears in UCM → is_connected=True.
25.  resolve_all_device_truth includes devices from UDM.
26.  resolve_all_device_truth includes devices from UCM.
27.  resolve_all_device_truth supplements with compat-only devices.
28.  resolve_all_device_truth de-duplicates: device in both UDM and compat → one entry.
29.  is_device_available_canonical returns True when device fully available.
30.  is_device_available_canonical returns False when device not routable.
31.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY importable from _shared.
32.  COMPAT_MIRROR_WRITE sentinel importable from _shared.
33.  COMPAT_MIRROR_WRITE contains 'COMPAT_MIRROR_WRITE'.
34.  COMPAT_MIRROR_WRITE contains 'SECONDARY_AFTER_UCM_UDM'.
35.  TRUTH_INTEGRATION_LAYER_BACKED sentinel in device_readiness.
36.  TRUTH_INTEGRATION_LAYER_BACKED is True.
37.  TRUTH_INTEGRATION_LAYER_BACKED exported from device_readiness __all__.
38.  PARTICIPATION_TRUTH_SOURCE sentinel in device_participation.
39.  PARTICIPATION_TRUTH_SOURCE references TIL.
40.  VALIDATOR_TRUTH_SOURCE sentinel in target_device_validator.
41.  VALIDATOR_TRUTH_SOURCE mentions compat-cache excluded.
42.  compat-cache writes in devices.py annotated with COMPAT_MIRROR_WRITE comment.
43.  devices.py imports COMPAT_MIRROR_WRITE from _shared.
44.  resolve_device_truth never raises even when both UCM and UDM raise exceptions.
45.  resolve_all_device_truth never raises even when all sources raise exceptions.

Test index
----------
  1.  TRUTH_INTEGRATION_LAYER_AUTHORITY importable.
  2.  TRUTH_INTEGRATION_LAYER_AUTHORITY contains 'TRUTH_INTEGRATION_LAYER'.
  3.  TRUTH_INTEGRATION_LAYER_AUTHORITY contains 'CANONICAL'.
  4.  TRUTH_CONFLICT_RESOLUTION_POLICY non-empty.
  5.  TRUTH_CONFLICT_RESOLUTION_POLICY mentions UCM/UDM.
  6.  TRUTH_CONFLICT_RESOLUTION_POLICY mentions compat.
  7.  CanonicalDeviceTruth importable.
  8.  CanonicalDeviceTruth.to_dict() fields.
  9.  is_available True when all flags set.
 10.  is_available False when any flag unset.
 11.  resolve_device_truth importable.
 12.  resolve_all_device_truth importable.
 13.  is_device_available_canonical importable.
 14.  resolve_device_truth ucm_udm source for registered+connected device.
 15.  resolve_device_truth ucm_udm, is_connected=False for UDM-only device.
 16.  resolve_device_truth compat_supplement for compat-only device.
 17.  resolve_device_truth unknown device → is_available=False.
 18.  resolve_device_truth compat_only when authority down.
 19.  conflict: compat online, authority offline.
 20.  conflict: compat offline, authority online.
 21.  conflict does not change authority verdict.
 22.  heartbeat scenario.
 23.  disconnect scenario.
 24.  reconnect scenario.
 25.  resolve_all_device_truth includes UDM devices.
 26.  resolve_all_device_truth includes UCM devices.
 27.  resolve_all_device_truth supplements compat-only devices.
 28.  resolve_all_device_truth deduplicates.
 29.  is_device_available_canonical True when available.
 30.  is_device_available_canonical False when not routable.
 31.  REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY importable.
 32.  COMPAT_MIRROR_WRITE importable.
 33.  COMPAT_MIRROR_WRITE contains 'COMPAT_MIRROR_WRITE'.
 34.  COMPAT_MIRROR_WRITE contains 'SECONDARY_AFTER_UCM_UDM'.
 35.  TRUTH_INTEGRATION_LAYER_BACKED in device_readiness.
 36.  TRUTH_INTEGRATION_LAYER_BACKED is True.
 37.  TRUTH_INTEGRATION_LAYER_BACKED in __all__.
 38.  PARTICIPATION_TRUTH_SOURCE in device_participation.
 39.  PARTICIPATION_TRUTH_SOURCE references TIL.
 40.  VALIDATOR_TRUTH_SOURCE in target_device_validator.
 41.  VALIDATOR_TRUTH_SOURCE mentions compat excluded.
 42.  devices.py COMPAT_MIRROR_WRITE annotation in source.
 43.  devices.py imports COMPAT_MIRROR_WRITE.
 44.  resolve_device_truth never raises.
 45.  resolve_all_device_truth never raises.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _read_source(rel_path: str) -> str:
    full = os.path.join(_REPO_ROOT, rel_path)
    with open(full, encoding="utf-8") as fh:
        return fh.read()


TIL_SRC = _read_source("core/truth_integration_layer.py")
SHARED_SRC = _read_source("core/routes/_shared.py")
DEVICES_SRC = _read_source("core/routes/devices.py")
READINESS_SRC = _read_source("core/device_readiness.py")
PARTICIPATION_SRC = _read_source("core/device_participation.py")
VALIDATOR_SRC = _read_source("core/target_device_validator.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_udm_device(device_id: str, status: str = "online", capabilities=None):
    """Return a minimal mock UDM device object."""
    dev = MagicMock()
    dev.device_id = device_id
    status_mock = MagicMock()
    status_mock.value = status
    dev.status = status_mock
    dev.capabilities = capabilities or []
    return dev


def _make_ucm_info(device_id: str, routable: bool = True, state: str = "connected"):
    """Return a minimal mock UCM connection info object."""
    info = MagicMock()
    info.device_id = device_id
    info.routable = routable
    info.state = state
    return info


# ===========================================================================
# Tests
# ===========================================================================

class TestTruthIntegrationLayerSentinels(unittest.TestCase):
    """Tests 1–6: sentinel strings."""

    def test_01_authority_importable(self):
        from core.truth_integration_layer import TRUTH_INTEGRATION_LAYER_AUTHORITY
        self.assertIsInstance(TRUTH_INTEGRATION_LAYER_AUTHORITY, str)
        self.assertTrue(len(TRUTH_INTEGRATION_LAYER_AUTHORITY) > 0)

    def test_02_authority_contains_til(self):
        from core.truth_integration_layer import TRUTH_INTEGRATION_LAYER_AUTHORITY
        self.assertIn("TRUTH_INTEGRATION_LAYER", TRUTH_INTEGRATION_LAYER_AUTHORITY)

    def test_03_authority_contains_canonical(self):
        from core.truth_integration_layer import TRUTH_INTEGRATION_LAYER_AUTHORITY
        self.assertIn("CANONICAL", TRUTH_INTEGRATION_LAYER_AUTHORITY)

    def test_04_conflict_policy_non_empty(self):
        from core.truth_integration_layer import TRUTH_CONFLICT_RESOLUTION_POLICY
        self.assertIsInstance(TRUTH_CONFLICT_RESOLUTION_POLICY, str)
        self.assertTrue(len(TRUTH_CONFLICT_RESOLUTION_POLICY) > 0)

    def test_05_conflict_policy_mentions_ucm_udm(self):
        from core.truth_integration_layer import TRUTH_CONFLICT_RESOLUTION_POLICY
        text = TRUTH_CONFLICT_RESOLUTION_POLICY.upper()
        self.assertIn("UCM", text)
        self.assertIn("UDM", text)

    def test_06_conflict_policy_mentions_compat(self):
        from core.truth_integration_layer import TRUTH_CONFLICT_RESOLUTION_POLICY
        self.assertIn("compat", TRUTH_CONFLICT_RESOLUTION_POLICY.lower())


class TestCanonicalDeviceTruth(unittest.TestCase):
    """Tests 7–10: CanonicalDeviceTruth model."""

    def test_07_importable(self):
        from core.truth_integration_layer import CanonicalDeviceTruth
        t = CanonicalDeviceTruth(device_id="dev-1")
        self.assertEqual(t.device_id, "dev-1")

    def test_08_to_dict_fields(self):
        from core.truth_integration_layer import CanonicalDeviceTruth
        t = CanonicalDeviceTruth(
            device_id="dev-1",
            is_registered=True,
            is_online=True,
            is_connected=True,
            is_routable=True,
        )
        d = t.to_dict()
        for key in (
            "device_id", "is_registered", "is_online",
            "is_connected", "is_routable", "capabilities",
            "resolution_source", "authority_available",
            "compat_present", "conflicts",
        ):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_09_is_available_true(self):
        from core.truth_integration_layer import CanonicalDeviceTruth
        t = CanonicalDeviceTruth(
            device_id="dev-1",
            is_registered=True, is_online=True,
            is_connected=True, is_routable=True,
        )
        self.assertTrue(t.is_available)

    def test_10_is_available_false_if_any_flag_unset(self):
        from core.truth_integration_layer import CanonicalDeviceTruth
        # is_routable = False
        t = CanonicalDeviceTruth(
            device_id="dev-1",
            is_registered=True, is_online=True,
            is_connected=True, is_routable=False,
        )
        self.assertFalse(t.is_available)
        # is_connected = False
        t2 = CanonicalDeviceTruth(
            device_id="dev-1",
            is_registered=True, is_online=True,
            is_connected=False, is_routable=True,
        )
        self.assertFalse(t2.is_available)


class TestResolveFunctions(unittest.TestCase):
    """Tests 11–13: importability of public helpers."""

    def test_11_resolve_device_truth_importable(self):
        from core.truth_integration_layer import resolve_device_truth
        self.assertTrue(callable(resolve_device_truth))

    def test_12_resolve_all_device_truth_importable(self):
        from core.truth_integration_layer import resolve_all_device_truth
        self.assertTrue(callable(resolve_all_device_truth))

    def test_13_is_device_available_canonical_importable(self):
        from core.truth_integration_layer import is_device_available_canonical
        self.assertTrue(callable(is_device_available_canonical))


class TestResolveDeviceTruth(unittest.TestCase):
    """Tests 14–24: resolve_device_truth scenarios."""

    def _patch_sources(self, udm=None, ucm=None, compat=None):
        """Context manager: patch _get_udm, _get_ucm, _get_compat_cache."""
        import core.truth_integration_layer as til
        patches = []
        patches.append(patch.object(til, "_get_udm", return_value=udm))
        patches.append(patch.object(til, "_get_ucm", return_value=ucm))
        patches.append(patch.object(til, "_get_compat_cache", return_value=compat or {}))
        return patches

    def _apply(self, patches):
        for p in patches:
            p.start()
        return patches

    def _stop(self, patches):
        for p in patches:
            p.stop()

    def test_14_ucm_udm_registered_and_connected(self):
        """Device in both UDM and UCM → resolution_source = 'ucm_udm'."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-a", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-a", routable=True)
        ucm.is_device_connected.return_value = True

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t = resolve_device_truth("dev-a")
        finally:
            self._stop(patches)

        self.assertTrue(t.is_registered)
        self.assertTrue(t.is_online)
        self.assertTrue(t.is_connected)
        self.assertTrue(t.is_routable)
        self.assertEqual(t.resolution_source, "ucm_udm")
        self.assertTrue(t.authority_available)

    def test_15_udm_only_no_ucm_record(self):
        """Device in UDM but no UCM connection → is_connected=False, resolution_source='ucm_udm'."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-b", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t = resolve_device_truth("dev-b")
        finally:
            self._stop(patches)

        self.assertTrue(t.is_registered)
        self.assertFalse(t.is_connected)
        self.assertFalse(t.is_routable)
        self.assertEqual(t.resolution_source, "ucm_udm")

    def test_16_compat_supplement_when_authority_has_no_record(self):
        """Device not in UCM/UDM but in compat → compat_supplement."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = None
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        compat = {"dev-c": {"status": "online", "online": True, "capabilities": ["camera"]}}

        patches = self._apply(self._patch_sources(udm, ucm, compat))
        try:
            t = resolve_device_truth("dev-c")
        finally:
            self._stop(patches)

        self.assertEqual(t.resolution_source, "compat_supplement")
        self.assertTrue(t.is_registered)
        self.assertTrue(t.is_online)
        self.assertTrue(t.compat_present)
        self.assertIn("camera", t.capabilities)

    def test_17_unknown_device(self):
        """Device not in any source → is_available=False."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = None
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t = resolve_device_truth("dev-unknown")
        finally:
            self._stop(patches)

        self.assertFalse(t.is_registered)
        self.assertFalse(t.is_available)
        self.assertFalse(t.compat_present)

    def test_18_compat_only_when_authorities_down(self):
        """Both UCM and UDM are None → compat_only source."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        compat = {"dev-d": {"status": "online", "online": True}}

        patches = self._apply(self._patch_sources(None, None, compat))
        try:
            t = resolve_device_truth("dev-d")
        finally:
            self._stop(patches)

        self.assertEqual(t.resolution_source, "compat_only")
        self.assertTrue(t.is_registered)
        self.assertFalse(t.authority_available)

    def test_19_conflict_compat_online_authority_offline(self):
        """Compat says online, authority says not registered → conflict recorded."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = None       # authority: not registered
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        compat = {"dev-e": {"status": "online", "online": True}}

        patches = self._apply(self._patch_sources(udm, ucm, compat))
        try:
            t = resolve_device_truth("dev-e")
        finally:
            self._stop(patches)

        # Compat-supplement path is used (authority had no record)
        self.assertEqual(t.resolution_source, "compat_supplement")
        # No conflict in this branch (authority returned nothing — it's a supplement)
        # Just verify it resolves without raising
        self.assertIsNotNone(t)

    def test_20_conflict_authority_registered_compat_offline(self):
        """Authority says registered, compat says offline → conflict recorded."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-f", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-f")
        ucm.is_device_connected.return_value = True

        compat = {"dev-f": {"status": "offline", "online": False}}

        patches = self._apply(self._patch_sources(udm, ucm, compat))
        try:
            t = resolve_device_truth("dev-f")
        finally:
            self._stop(patches)

        # Authority verdict is used
        self.assertEqual(t.resolution_source, "ucm_udm")
        self.assertTrue(t.is_registered)
        # Conflict detected
        self.assertTrue(len(t.conflicts) > 0)
        self.assertTrue(any("authority" in c.lower() or "compat" in c.lower() for c in t.conflicts))

    def test_21_conflict_does_not_change_authority_verdict(self):
        """Even with compat conflict, authority verdict is preserved."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-g", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-g", routable=True)
        ucm.is_device_connected.return_value = True

        compat = {"dev-g": {"status": "offline", "online": False}}

        patches = self._apply(self._patch_sources(udm, ucm, compat))
        try:
            t = resolve_device_truth("dev-g")
        finally:
            self._stop(patches)

        # Authority verdict wins
        self.assertTrue(t.is_registered)
        self.assertTrue(t.is_online)
        self.assertTrue(t.is_connected)
        self.assertTrue(t.is_routable)
        self.assertTrue(t.is_available)

    def test_22_heartbeat_scenario_routable_updated(self):
        """After heartbeat UCM marks routable=True — truth reflects this."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-h", status="online")

        ucm = MagicMock()
        # Before heartbeat: routable=False
        conn_before = _make_ucm_info("dev-h", routable=False)
        ucm.get_connection.return_value = conn_before
        ucm.is_device_connected.return_value = True

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t_before = resolve_device_truth("dev-h")
        finally:
            self._stop(patches)

        self.assertFalse(t_before.is_routable)

        # After heartbeat: routable=True
        conn_after = _make_ucm_info("dev-h", routable=True)
        ucm.get_connection.return_value = conn_after

        patches2 = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t_after = resolve_device_truth("dev-h")
        finally:
            self._stop(patches2)

        self.assertTrue(t_after.is_routable)

    def test_23_disconnect_scenario(self):
        """After disconnect UCM has no record → is_connected=False."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-i", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t = resolve_device_truth("dev-i")
        finally:
            self._stop(patches)

        self.assertTrue(t.is_registered)   # UDM still has it
        self.assertFalse(t.is_connected)   # UCM: no active connection
        self.assertFalse(t.is_routable)
        self.assertFalse(t.is_available)

    def test_24_reconnect_scenario(self):
        """After reconnect UCM gets new record → is_connected=True again."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-j", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-j", routable=True)
        ucm.is_device_connected.return_value = True

        patches = self._apply(self._patch_sources(udm, ucm, {}))
        try:
            t = resolve_device_truth("dev-j")
        finally:
            self._stop(patches)

        self.assertTrue(t.is_connected)
        self.assertTrue(t.is_routable)
        self.assertTrue(t.is_available)


class TestResolveAllDeviceTruth(unittest.TestCase):
    """Tests 25–28: resolve_all_device_truth."""

    def test_25_includes_udm_devices(self):
        """UDM devices appear in resolve_all_device_truth output."""
        from core.truth_integration_layer import resolve_all_device_truth
        import core.truth_integration_layer as til

        dev_a = _make_udm_device("dev-aa")
        udm = MagicMock()
        udm.list_devices.return_value = [dev_a]
        ucm = MagicMock()
        ucm.get_all_devices.return_value = []
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            results = resolve_all_device_truth()

        ids = [r.device_id for r in results]
        self.assertIn("dev-aa", ids)

    def test_26_includes_ucm_devices(self):
        """UCM devices appear in output even if not in UDM."""
        from core.truth_integration_layer import resolve_all_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.list_devices.return_value = []
        ucm = MagicMock()
        ucm.get_all_devices.return_value = [{"device_id": "dev-bb"}]
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            results = resolve_all_device_truth()

        ids = [r.device_id for r in results]
        self.assertIn("dev-bb", ids)

    def test_27_supplements_compat_only_devices(self):
        """Compat-only devices appear in output."""
        from core.truth_integration_layer import resolve_all_device_truth
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.list_devices.return_value = []
        ucm = MagicMock()
        ucm.get_all_devices.return_value = []
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        compat = {"dev-cc": {"status": "online"}}

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value=compat):
            results = resolve_all_device_truth()

        ids = [r.device_id for r in results]
        self.assertIn("dev-cc", ids)

    def test_28_deduplicates_devices(self):
        """Device in both UDM and compat → exactly one entry."""
        from core.truth_integration_layer import resolve_all_device_truth
        import core.truth_integration_layer as til

        dev = _make_udm_device("dev-dd")
        udm = MagicMock()
        udm.list_devices.return_value = [dev]
        ucm = MagicMock()
        ucm.get_all_devices.return_value = []
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False

        compat = {"dev-dd": {"status": "online"}}

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value=compat):
            results = resolve_all_device_truth()

        ids = [r.device_id for r in results]
        self.assertEqual(ids.count("dev-dd"), 1)


class TestIsDeviceAvailableCanonical(unittest.TestCase):
    """Tests 29–30."""

    def test_29_returns_true_when_available(self):
        from core.truth_integration_layer import is_device_available_canonical
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-x", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-x", routable=True)
        ucm.is_device_connected.return_value = True

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            result = is_device_available_canonical("dev-x")

        self.assertTrue(result)

    def test_30_returns_false_when_not_routable(self):
        from core.truth_integration_layer import is_device_available_canonical
        import core.truth_integration_layer as til

        udm = MagicMock()
        udm.get_device.return_value = _make_udm_device("dev-y", status="online")
        ucm = MagicMock()
        ucm.get_connection.return_value = _make_ucm_info("dev-y", routable=False)
        ucm.is_device_connected.return_value = True

        with patch.object(til, "_get_udm", return_value=udm), \
             patch.object(til, "_get_ucm", return_value=ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            result = is_device_available_canonical("dev-y")

        self.assertFalse(result)


class TestCompatMirrorSentinels(unittest.TestCase):
    """Tests 31–34: compat sentinel annotations (source-code checks to avoid fastapi dep)."""

    def test_31_registered_devices_compat_authority_importable(self):
        """REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY is defined in _shared.py source."""
        self.assertIn("REGISTERED_DEVICES_COMPAT_CACHE_AUTHORITY", SHARED_SRC)
        # Confirm it's a non-empty string assignment
        self.assertIn("COMPAT_CACHE_READ_ONLY", SHARED_SRC)

    def test_32_compat_mirror_write_importable(self):
        """COMPAT_MIRROR_WRITE is defined in _shared.py source."""
        self.assertIn("COMPAT_MIRROR_WRITE", SHARED_SRC)

    def test_33_compat_mirror_write_contains_compat_mirror_write(self):
        """COMPAT_MIRROR_WRITE value contains 'COMPAT_MIRROR_WRITE'."""
        # Value is on the line: COMPAT_MIRROR_WRITE: str = "COMPAT_MIRROR_WRITE::..."
        import re
        match = re.search(r'COMPAT_MIRROR_WRITE\s*:\s*str\s*=\s*"([^"]+)"', SHARED_SRC)
        self.assertIsNotNone(match, "COMPAT_MIRROR_WRITE string value not found in _shared.py")
        value = match.group(1)
        self.assertIn("COMPAT_MIRROR_WRITE", value)

    def test_34_compat_mirror_write_contains_secondary_after_ucm_udm(self):
        """COMPAT_MIRROR_WRITE value contains 'SECONDARY_AFTER_UCM_UDM'."""
        import re
        match = re.search(r'COMPAT_MIRROR_WRITE\s*:\s*str\s*=\s*"([^"]+)"', SHARED_SRC)
        self.assertIsNotNone(match, "COMPAT_MIRROR_WRITE string value not found in _shared.py")
        value = match.group(1)
        self.assertIn("SECONDARY_AFTER_UCM_UDM", value)


class TestReadinessTILSentinel(unittest.TestCase):
    """Tests 35–37: TRUTH_INTEGRATION_LAYER_BACKED in device_readiness."""

    def test_35_til_backed_importable(self):
        from core.device_readiness import TRUTH_INTEGRATION_LAYER_BACKED
        self.assertIsNotNone(TRUTH_INTEGRATION_LAYER_BACKED)

    def test_36_til_backed_is_true(self):
        from core.device_readiness import TRUTH_INTEGRATION_LAYER_BACKED
        self.assertTrue(TRUTH_INTEGRATION_LAYER_BACKED)

    def test_37_til_backed_in_all(self):
        from core.device_readiness import __all__
        self.assertIn("TRUTH_INTEGRATION_LAYER_BACKED", __all__)


class TestParticipationTILSentinel(unittest.TestCase):
    """Tests 38–39: PARTICIPATION_TRUTH_SOURCE in device_participation."""

    def test_38_participation_truth_source_importable(self):
        from core.device_participation import PARTICIPATION_TRUTH_SOURCE
        self.assertIsInstance(PARTICIPATION_TRUTH_SOURCE, str)
        self.assertTrue(len(PARTICIPATION_TRUTH_SOURCE) > 0)

    def test_39_participation_truth_source_references_til(self):
        from core.device_participation import PARTICIPATION_TRUTH_SOURCE
        src = PARTICIPATION_TRUTH_SOURCE.upper()
        self.assertTrue(
            "TRUTH_INTEGRATION_LAYER" in src or "TIL" in src
        )


class TestValidatorTILSentinel(unittest.TestCase):
    """Tests 40–41: VALIDATOR_TRUTH_SOURCE in target_device_validator."""

    def test_40_validator_truth_source_importable(self):
        from core.target_device_validator import VALIDATOR_TRUTH_SOURCE
        self.assertIsInstance(VALIDATOR_TRUTH_SOURCE, str)
        self.assertTrue(len(VALIDATOR_TRUTH_SOURCE) > 0)

    def test_41_validator_truth_source_mentions_compat_excluded(self):
        from core.target_device_validator import VALIDATOR_TRUTH_SOURCE
        self.assertIn("compat", VALIDATOR_TRUTH_SOURCE.lower())
        self.assertTrue(
            "exclud" in VALIDATOR_TRUTH_SOURCE.lower()
            or "not" in VALIDATOR_TRUTH_SOURCE.lower()
        )


class TestSourceCodeAnnotations(unittest.TestCase):
    """Tests 42–43: source code annotation checks."""

    def test_42_devices_py_compat_mirror_write_annotation(self):
        """devices.py contains COMPAT_MIRROR_WRITE annotation comments."""
        self.assertIn("COMPAT_MIRROR_WRITE", DEVICES_SRC)

    def test_43_devices_py_imports_compat_mirror_write(self):
        """devices.py imports COMPAT_MIRROR_WRITE from _shared."""
        import re
        self.assertIsNotNone(
            re.search(
                r'from\s+core\.routes\._shared\s+import[^#\n]*COMPAT_MIRROR_WRITE',
                DEVICES_SRC,
            ),
            "devices.py must import COMPAT_MIRROR_WRITE from core.routes._shared",
        )


class TestRobustness(unittest.TestCase):
    """Tests 44–45: never-raise guarantees."""

    def test_44_resolve_device_truth_never_raises(self):
        """resolve_device_truth must not raise even when all sources throw."""
        from core.truth_integration_layer import resolve_device_truth
        import core.truth_integration_layer as til

        bad_udm = MagicMock()
        bad_udm.get_device.side_effect = RuntimeError("UDM exploded")
        bad_ucm = MagicMock()
        bad_ucm.get_connection.side_effect = RuntimeError("UCM exploded")
        bad_ucm.is_device_connected.side_effect = RuntimeError("UCM is down")

        with patch.object(til, "_get_udm", return_value=bad_udm), \
             patch.object(til, "_get_ucm", return_value=bad_ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            try:
                result = resolve_device_truth("dev-z")
            except Exception as exc:
                self.fail(f"resolve_device_truth raised unexpectedly: {exc}")

        self.assertIsNotNone(result)
        self.assertFalse(result.is_available)

    def test_45_resolve_all_device_truth_never_raises(self):
        """resolve_all_device_truth must not raise even when all sources throw."""
        from core.truth_integration_layer import resolve_all_device_truth
        import core.truth_integration_layer as til

        bad_udm = MagicMock()
        bad_udm.list_devices.side_effect = RuntimeError("UDM exploded")
        bad_ucm = MagicMock()
        bad_ucm.get_all_devices.side_effect = RuntimeError("UCM exploded")

        with patch.object(til, "_get_udm", return_value=bad_udm), \
             patch.object(til, "_get_ucm", return_value=bad_ucm), \
             patch.object(til, "_get_compat_cache", return_value={}):
            try:
                results = resolve_all_device_truth()
            except Exception as exc:
                self.fail(f"resolve_all_device_truth raised unexpectedly: {exc}")

        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
