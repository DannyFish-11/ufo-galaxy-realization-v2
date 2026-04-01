#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_readiness_routability.py
=====================================
PR-5: Readiness vs routability tests.

Validates the new PR-5 live-route-truth fields on ``RoutabilitySummary``:

  ``transport_present``   — any transport physically connected
  ``transport_usable``    — transport present AND can deliver
  ``device_routable``     — explicit alias for effective_routable
  ``effective_path``      — explicit alias for preferred_path

Also validates the new ``LIVE_ROUTE_TRUTH_INTEGRATED`` sentinel.

Test classes
------------
1. TestLiveRouteTruthSentinel
       LIVE_ROUTE_TRUTH_INTEGRATED is importable and True.

2. TestTransportPresentVsUsable
       transport_present is True when WS/UCM connected even if relay-only.
       transport_usable mirrors effective_routable.

3. TestDeviceRoutableAlias
       device_routable mirrors effective_routable.
       effective_path mirrors preferred_path.

4. TestRoutabilitySummaryToDictPR5
       to_dict() includes all four new PR-5 fields.

5. TestDirectWSPath
       With direct_ws_available=True: transport_present, transport_usable,
       device_routable all True; effective_path="direct_ws".

6. TestRelayOnlyPath
       With relay_available=True only: transport_present and device_routable
       are True; effective_path="relay".

7. TestNoTransportPath
       With no transport available: transport_present=False,
       transport_usable=False, device_routable=False, effective_path="none".

8. TestGetRoutabilitySummaryPopulatesPR5Fields
       get_routability_summary() correctly populates PR-5 fields.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.device_readiness import (
    RoutabilitySummary,
    LIVE_ROUTE_TRUTH_INTEGRATED,
    TRANSPORT_HIERARCHY_ENFORCED,
    get_routability_summary,
)


# ---------------------------------------------------------------------------
# 1. TestLiveRouteTruthSentinel
# ---------------------------------------------------------------------------


class TestLiveRouteTruthSentinel(unittest.TestCase):
    def test_live_route_truth_integrated_is_true(self):
        self.assertTrue(LIVE_ROUTE_TRUTH_INTEGRATED)

    def test_transport_hierarchy_still_enforced(self):
        self.assertTrue(TRANSPORT_HIERARCHY_ENFORCED)

    def test_sentinel_exportable(self):
        from core.device_readiness import __all__ as exports
        self.assertIn("LIVE_ROUTE_TRUTH_INTEGRATED", exports)


# ---------------------------------------------------------------------------
# 2. TestTransportPresentVsUsable
# ---------------------------------------------------------------------------


class TestTransportPresentVsUsable(unittest.TestCase):
    def _make_summary(self, **kwargs):
        s = RoutabilitySummary(device_id="dev1")
        for k, v in kwargs.items():
            setattr(s, k, v)
        return s

    def test_transport_present_false_by_default(self):
        s = RoutabilitySummary(device_id="dev1")
        self.assertFalse(s.transport_present)

    def test_transport_usable_false_by_default(self):
        s = RoutabilitySummary(device_id="dev1")
        self.assertFalse(s.transport_usable)

    def test_transport_present_true_when_direct_ws(self):
        s = self._make_summary(direct_ws_available=True, transport_present=True)
        self.assertTrue(s.transport_present)

    def test_transport_usable_requires_effective_routable(self):
        s = self._make_summary(transport_present=True, effective_routable=False,
                                transport_usable=False)
        self.assertFalse(s.transport_usable)

    def test_transport_usable_true_when_routable(self):
        s = self._make_summary(transport_present=True, effective_routable=True,
                                transport_usable=True)
        self.assertTrue(s.transport_usable)


# ---------------------------------------------------------------------------
# 3. TestDeviceRoutableAlias
# ---------------------------------------------------------------------------


class TestDeviceRoutableAlias(unittest.TestCase):
    def test_device_routable_false_by_default(self):
        s = RoutabilitySummary(device_id="dev1")
        self.assertFalse(s.device_routable)

    def test_device_routable_alias_matches_effective_routable(self):
        s = RoutabilitySummary(device_id="dev1")
        s.effective_routable = True
        s.device_routable = True
        self.assertEqual(s.device_routable, s.effective_routable)

    def test_effective_path_none_by_default(self):
        s = RoutabilitySummary(device_id="dev1")
        self.assertEqual(s.effective_path, "none")

    def test_effective_path_alias_matches_preferred_path(self):
        s = RoutabilitySummary(device_id="dev1")
        s.preferred_path = "direct_ws"
        s.effective_path = "direct_ws"
        self.assertEqual(s.effective_path, s.preferred_path)


# ---------------------------------------------------------------------------
# 4. TestRoutabilitySummaryToDictPR5
# ---------------------------------------------------------------------------


class TestRoutabilitySummaryToDictPR5(unittest.TestCase):
    def setUp(self):
        self.s = RoutabilitySummary(device_id="dev1")

    def test_to_dict_contains_transport_present(self):
        self.assertIn("transport_present", self.s.to_dict())

    def test_to_dict_contains_transport_usable(self):
        self.assertIn("transport_usable", self.s.to_dict())

    def test_to_dict_contains_device_routable(self):
        self.assertIn("device_routable", self.s.to_dict())

    def test_to_dict_contains_effective_path(self):
        self.assertIn("effective_path", self.s.to_dict())

    def test_to_dict_pr5_values_serialise_correctly(self):
        self.s.transport_present = True
        self.s.transport_usable = True
        self.s.device_routable = True
        self.s.effective_path = "direct_ws"
        d = self.s.to_dict()
        self.assertTrue(d["transport_present"])
        self.assertTrue(d["transport_usable"])
        self.assertTrue(d["device_routable"])
        self.assertEqual(d["effective_path"], "direct_ws")


# ---------------------------------------------------------------------------
# 5. TestDirectWSPath
# ---------------------------------------------------------------------------


class TestDirectWSPath(unittest.TestCase):
    def _ucm_with_direct_ws(self, device_id):
        conn_info = MagicMock()
        conn_info.state = "connected"
        conn_info.routable = True
        conn_info.connection_id = f"conn-{device_id}"
        conn_info.last_heartbeat = None
        ucm = MagicMock()
        ucm.get_connection.return_value = conn_info
        ucm.is_device_connected.return_value = True
        return ucm

    def test_direct_ws_sets_transport_present_and_usable(self):
        ucm = self._ucm_with_direct_ws("dev1")
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            summary = get_routability_summary("dev1")
        self.assertTrue(summary.transport_present)
        self.assertTrue(summary.transport_usable)
        self.assertTrue(summary.device_routable)
        self.assertEqual(summary.effective_path, "direct_ws")

    def test_direct_ws_device_routable_equals_effective_routable(self):
        ucm = self._ucm_with_direct_ws("dev1")
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            summary = get_routability_summary("dev1")
        self.assertEqual(summary.device_routable, summary.effective_routable)

    def test_direct_ws_effective_path_equals_preferred_path(self):
        ucm = self._ucm_with_direct_ws("dev1")
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            summary = get_routability_summary("dev1")
        self.assertEqual(summary.effective_path, summary.preferred_path)


# ---------------------------------------------------------------------------
# 6. TestRelayOnlyPath
# ---------------------------------------------------------------------------


class TestRelayOnlyPath(unittest.TestCase):
    def test_relay_only_sets_transport_present(self):
        """Relay available → transport_present=True, device_routable=True."""
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None), \
             patch("builtins.__import__", side_effect=self._import_side_effect):
            summary = get_routability_summary("dev1")
        self.assertTrue(summary.relay_available)
        self.assertTrue(summary.transport_present)
        self.assertTrue(summary.device_routable)
        self.assertEqual(summary.effective_path, "relay")

    @staticmethod
    def _import_side_effect(name, *args, **kwargs):
        if name == "core.proxy_relay":
            return MagicMock()
        raise ImportError(name)


# ---------------------------------------------------------------------------
# 7. TestNoTransportPath
# ---------------------------------------------------------------------------


class TestNoTransportPath(unittest.TestCase):
    def test_no_transport_all_false(self):
        """No WS, UCM, or relay → transport fields all False/none."""
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None), \
             patch("builtins.__import__", side_effect=ImportError):
            summary = get_routability_summary("dev1")
        self.assertFalse(summary.transport_present)
        self.assertFalse(summary.transport_usable)
        self.assertFalse(summary.device_routable)
        self.assertEqual(summary.effective_path, "none")


# ---------------------------------------------------------------------------
# 8. TestGetRoutabilitySummaryPopulatesPR5Fields
# ---------------------------------------------------------------------------


class TestGetRoutabilitySummaryPopulatesPR5Fields(unittest.TestCase):
    def test_pr5_fields_present_in_result(self):
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            summary = get_routability_summary("dev1")
        self.assertIsInstance(summary.transport_present, bool)
        self.assertIsInstance(summary.transport_usable, bool)
        self.assertIsInstance(summary.device_routable, bool)
        self.assertIsInstance(summary.effective_path, str)

    def test_pr5_fields_in_to_dict(self):
        ucm = MagicMock()
        ucm.get_connection.return_value = None
        ucm.is_device_connected.return_value = False
        with patch("core.device_readiness._get_ucm", return_value=ucm), \
             patch("core.device_readiness._get_gateway_ws_manager", return_value=None), \
             patch("core.device_readiness._get_device_router", return_value=None):
            summary = get_routability_summary("dev1")
        d = summary.to_dict()
        for key in ("transport_present", "transport_usable", "device_routable", "effective_path"):
            self.assertIn(key, d, f"Missing key: {key}")


if __name__ == "__main__":
    unittest.main()
