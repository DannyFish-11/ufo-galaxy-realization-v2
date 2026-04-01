#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_transport_hierarchy.py
======================================

PR-4 — Establish canonical transport hierarchy for direct WS, relay, and mesh.

Validates that:
 1.  TRANSPORT_HIERARCHY_AUTHORITY sentinel exists and has correct value.
 2.  TRANSPORT_ROLE_DIRECT_WS = "primary".
 3.  TRANSPORT_ROLE_RELAY = "fallback".
 4.  TRANSPORT_ROLE_MESH = "overlay".
 5.  MESH_ORCHESTRATION_AUTHORITY_EXCLUDED = True.
 6.  transport_role_for_path("direct_ws") = "primary".
 7.  transport_role_for_path("ucm") = "primary".
 8.  transport_role_for_path("relay") = "fallback".
 9.  transport_role_for_path("mesh_direct") = "overlay".
10.  transport_role_for_path("mesh_relay") = "overlay".
11.  transport_role_for_path("none") = "none".
12.  transport_role_for_path unknown returns "unknown".
13.  RELAY_TRANSPORT_ROLE sentinel exists in proxy_relay.
14.  RELAY_TRANSPORT_ROLE starts with "RELAY::".
15.  MESH_TRANSPORT_ROLE sentinel exists in mesh_coordinator.
16.  MESH_TRANSPORT_ROLE starts with "MESH::".
17.  MESH_ORCHESTRATION_EXCLUDED = True in mesh_coordinator.
18.  TRANSPORT_HIERARCHY_ENFORCED in device_readiness.__all__.
19.  TRANSPORT_HIERARCHY_ENFORCED = True in device_readiness.
20.  RoutabilitySummary has primary_transport field.
21.  RoutabilitySummary has fallback_available field.
22.  RoutabilitySummary has mesh_overlay_available field.
23.  RoutabilitySummary has transport_role_note field.
24.  RoutabilitySummary.to_dict() includes all PR-4 hierarchy fields.
25.  When only direct_ws available: effective_routable True, preferred_path "direct_ws".
26.  When only relay available: effective_routable True, preferred_path "relay".
27.  When only mesh available: effective_routable False (mesh is overlay only).
28.  When mesh only: mesh_overlay_available True, effective_routable False.
29.  When mesh only: reasons includes mesh_overlay_present_but_not_canonical_route.
30.  When direct_ws available: primary_transport = "direct_ws".
31.  When relay only: primary_transport = "relay".
32.  When nothing: primary_transport = "none".
33.  fallback_available mirrors relay_available.
34.  mesh_overlay_available = mesh_direct_available OR mesh_relay_available.
35.  When direct_ws available: transport_role_note contains "primary".
36.  When relay only: transport_role_note contains "fallback_transport".
37.  When mesh only: transport_role_note contains "overlay_only".
38.  get_routability_summary: preferred_path is never "mesh_direct".
39.  get_routability_summary: preferred_path is never "mesh_relay".
40.  RoutabilitySummary default: all bool fields False, strings "none"/"".

Test index
----------
  1.  TRANSPORT_HIERARCHY_AUTHORITY importable.
  2.  TRANSPORT_ROLE_DIRECT_WS = "primary".
  3.  TRANSPORT_ROLE_RELAY = "fallback".
  4.  TRANSPORT_ROLE_MESH = "overlay".
  5.  MESH_ORCHESTRATION_AUTHORITY_EXCLUDED = True.
  6.  transport_role_for_path direct_ws → primary.
  7.  transport_role_for_path ucm → primary.
  8.  transport_role_for_path relay → fallback.
  9.  transport_role_for_path mesh_direct → overlay.
 10.  transport_role_for_path mesh_relay → overlay.
 11.  transport_role_for_path none → none.
 12.  transport_role_for_path unknown → unknown.
 13.  RELAY_TRANSPORT_ROLE importable from proxy_relay.
 14.  RELAY_TRANSPORT_ROLE starts with "RELAY::".
 15.  MESH_TRANSPORT_ROLE importable from mesh_coordinator.
 16.  MESH_TRANSPORT_ROLE starts with "MESH::".
 17.  MESH_ORCHESTRATION_EXCLUDED = True in mesh_coordinator.
 18.  TRANSPORT_HIERARCHY_ENFORCED in device_readiness.__all__.
 19.  TRANSPORT_HIERARCHY_ENFORCED = True in device_readiness.
 20.  RoutabilitySummary has primary_transport.
 21.  RoutabilitySummary has fallback_available.
 22.  RoutabilitySummary has mesh_overlay_available.
 23.  RoutabilitySummary has transport_role_note.
 24.  to_dict() includes all PR-4 fields.
 25.  direct_ws only → effective_routable True, preferred_path "direct_ws".
 26.  relay only → effective_routable True, preferred_path "relay".
 27.  mesh only → effective_routable False.
 28.  mesh only → mesh_overlay_available True.
 29.  mesh only → reasons include mesh_overlay_present_but_not_canonical_route.
 30.  direct_ws → primary_transport "direct_ws".
 31.  relay only → primary_transport "relay".
 32.  nothing → primary_transport "none".
 33.  fallback_available mirrors relay_available.
 34.  mesh_overlay_available = mesh_direct or mesh_relay.
 35.  direct_ws note contains "primary".
 36.  relay only note contains "fallback_transport".
 37.  mesh only note contains "overlay_only".
 38.  get_routability_summary preferred_path never "mesh_direct".
 39.  get_routability_summary preferred_path never "mesh_relay".
 40.  RoutabilitySummary defaults correct.
"""

import sys
import unittest
from unittest.mock import MagicMock, patch


class TestTransportHierarchyModule(unittest.TestCase):
    """Tests 1–12: core/transport_hierarchy.py sentinels and helpers."""

    def test_01_authority_importable(self):
        from core.transport_hierarchy import TRANSPORT_HIERARCHY_AUTHORITY
        self.assertIsInstance(TRANSPORT_HIERARCHY_AUTHORITY, str)
        self.assertIn("TRANSPORT_HIERARCHY", TRANSPORT_HIERARCHY_AUTHORITY)

    def test_02_role_direct_ws_is_primary(self):
        from core.transport_hierarchy import TRANSPORT_ROLE_DIRECT_WS
        self.assertEqual(TRANSPORT_ROLE_DIRECT_WS, "primary")

    def test_03_role_relay_is_fallback(self):
        from core.transport_hierarchy import TRANSPORT_ROLE_RELAY
        self.assertEqual(TRANSPORT_ROLE_RELAY, "fallback")

    def test_04_role_mesh_is_overlay(self):
        from core.transport_hierarchy import TRANSPORT_ROLE_MESH
        self.assertEqual(TRANSPORT_ROLE_MESH, "overlay")

    def test_05_mesh_orchestration_excluded(self):
        from core.transport_hierarchy import MESH_ORCHESTRATION_AUTHORITY_EXCLUDED
        self.assertIs(MESH_ORCHESTRATION_AUTHORITY_EXCLUDED, True)

    def test_06_role_for_path_direct_ws(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("direct_ws"), "primary")

    def test_07_role_for_path_ucm(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("ucm"), "primary")

    def test_08_role_for_path_relay(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("relay"), "fallback")

    def test_09_role_for_path_mesh_direct(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("mesh_direct"), "overlay")

    def test_10_role_for_path_mesh_relay(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("mesh_relay"), "overlay")

    def test_11_role_for_path_none(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("none"), "none")

    def test_12_role_for_path_unknown(self):
        from core.transport_hierarchy import transport_role_for_path
        self.assertEqual(transport_role_for_path("totally_unknown_path"), "unknown")


class TestProxyRelaySentinel(unittest.TestCase):
    """Tests 13–14: core/proxy_relay.py transport role sentinel."""

    def test_13_relay_transport_role_importable(self):
        from core.proxy_relay import RELAY_TRANSPORT_ROLE
        self.assertIsInstance(RELAY_TRANSPORT_ROLE, str)
        self.assertTrue(len(RELAY_TRANSPORT_ROLE) > 0)

    def test_14_relay_transport_role_prefix(self):
        from core.proxy_relay import RELAY_TRANSPORT_ROLE
        self.assertTrue(
            RELAY_TRANSPORT_ROLE.startswith("RELAY::"),
            f"Expected RELAY:: prefix, got: {RELAY_TRANSPORT_ROLE!r}",
        )


class TestMeshCoordinatorSentinels(unittest.TestCase):
    """Tests 15–17: core/mesh_coordinator.py transport role sentinels."""

    def test_15_mesh_transport_role_importable(self):
        from core.mesh_coordinator import MESH_TRANSPORT_ROLE
        self.assertIsInstance(MESH_TRANSPORT_ROLE, str)
        self.assertTrue(len(MESH_TRANSPORT_ROLE) > 0)

    def test_16_mesh_transport_role_prefix(self):
        from core.mesh_coordinator import MESH_TRANSPORT_ROLE
        self.assertTrue(
            MESH_TRANSPORT_ROLE.startswith("MESH::"),
            f"Expected MESH:: prefix, got: {MESH_TRANSPORT_ROLE!r}",
        )

    def test_17_mesh_orchestration_excluded(self):
        from core.mesh_coordinator import MESH_ORCHESTRATION_EXCLUDED
        self.assertIs(MESH_ORCHESTRATION_EXCLUDED, True)


class TestDeviceReadinessHierarchySentinel(unittest.TestCase):
    """Tests 18–19: TRANSPORT_HIERARCHY_ENFORCED in device_readiness."""

    def test_18_transport_hierarchy_enforced_in_all(self):
        import core.device_readiness as dr
        self.assertIn("TRANSPORT_HIERARCHY_ENFORCED", dr.__all__)

    def test_19_transport_hierarchy_enforced_is_true(self):
        from core.device_readiness import TRANSPORT_HIERARCHY_ENFORCED
        self.assertIs(TRANSPORT_HIERARCHY_ENFORCED, True)


class TestRoutabilitySummaryFields(unittest.TestCase):
    """Tests 20–24: RoutabilitySummary dataclass fields."""

    def setUp(self):
        from core.device_readiness import RoutabilitySummary
        self.RS = RoutabilitySummary

    def test_20_has_primary_transport(self):
        rs = self.RS(device_id="d1")
        self.assertTrue(hasattr(rs, "primary_transport"))

    def test_21_has_fallback_available(self):
        rs = self.RS(device_id="d1")
        self.assertTrue(hasattr(rs, "fallback_available"))

    def test_22_has_mesh_overlay_available(self):
        rs = self.RS(device_id="d1")
        self.assertTrue(hasattr(rs, "mesh_overlay_available"))

    def test_23_has_transport_role_note(self):
        rs = self.RS(device_id="d1")
        self.assertTrue(hasattr(rs, "transport_role_note"))

    def test_24_to_dict_includes_hierarchy_fields(self):
        rs = self.RS(device_id="d1")
        d = rs.to_dict()
        for field in (
            "primary_transport",
            "fallback_available",
            "mesh_overlay_available",
            "transport_role_note",
        ):
            self.assertIn(field, d, f"Missing PR-4 field: {field!r}")


class TestRoutabilitySummaryHierarchyLogic(unittest.TestCase):
    """Tests 25–40: Transport hierarchy logic in get_routability_summary."""

    def _make_summary(
        self,
        *,
        ucm_routable: bool = False,
        gw_ws_connected: bool = False,
        relay_present: bool = False,
        mesh_present: bool = False,
    ):
        """Helper: build a RoutabilitySummary with controlled subsystem mocks."""
        from core.device_readiness import get_routability_summary

        mock_conn_info = MagicMock()
        mock_conn_info.routable = ucm_routable

        mock_ucm = MagicMock()
        mock_ucm.get_connection.return_value = mock_conn_info if ucm_routable else None

        mock_gw = MagicMock()
        mock_gw.get_connected_devices.return_value = ["dev1"] if gw_ws_connected else []

        # Build patch targets
        patches = [
            patch(
                "core.device_readiness._get_ucm",
                return_value=mock_ucm,
            ),
            patch(
                "core.device_readiness._get_gateway_ws_manager",
                return_value=mock_gw,
            ),
        ]

        if relay_present:
            # Make relay module importable
            fake_relay = MagicMock()
            patches.append(
                patch.dict(sys.modules, {"core.proxy_relay": fake_relay})
            )
        else:
            # Make relay module absent
            patches.append(
                patch.dict(sys.modules, {"core.proxy_relay": None})
            )

        if mesh_present:
            fake_mesh = MagicMock()
            patches.append(
                patch.dict(sys.modules, {"core.mesh_coordinator": fake_mesh})
            )
        else:
            patches.append(
                patch.dict(sys.modules, {"core.mesh_coordinator": None})
            )

        with patches[0], patches[1], patches[2], patches[3]:
            return get_routability_summary("dev1")

    def test_25_direct_ws_effective_routable(self):
        s = self._make_summary(gw_ws_connected=True)
        self.assertTrue(s.effective_routable)
        self.assertEqual(s.preferred_path, "direct_ws")

    def test_26_relay_only_effective_routable(self):
        s = self._make_summary(relay_present=True)
        self.assertTrue(s.effective_routable)
        self.assertEqual(s.preferred_path, "relay")

    def test_27_mesh_only_not_effective_routable(self):
        s = self._make_summary(mesh_present=True)
        self.assertFalse(
            s.effective_routable,
            "Mesh overlay must NOT set effective_routable (PR-4 hierarchy)",
        )

    def test_28_mesh_only_overlay_available(self):
        s = self._make_summary(mesh_present=True)
        self.assertTrue(s.mesh_overlay_available)

    def test_29_mesh_only_reason_appended(self):
        s = self._make_summary(mesh_present=True)
        self.assertIn("mesh_overlay_present_but_not_canonical_route", s.reasons)

    def test_30_direct_ws_primary_transport(self):
        s = self._make_summary(gw_ws_connected=True)
        self.assertEqual(s.primary_transport, "direct_ws")

    def test_31_relay_only_primary_transport(self):
        s = self._make_summary(relay_present=True)
        self.assertEqual(s.primary_transport, "relay")

    def test_32_nothing_primary_transport_none(self):
        s = self._make_summary()
        self.assertEqual(s.primary_transport, "none")

    def test_33_fallback_available_mirrors_relay(self):
        s_with_relay = self._make_summary(relay_present=True)
        self.assertEqual(s_with_relay.fallback_available, s_with_relay.relay_available)
        self.assertTrue(s_with_relay.fallback_available)

        s_no_relay = self._make_summary()
        self.assertEqual(s_no_relay.fallback_available, s_no_relay.relay_available)
        self.assertFalse(s_no_relay.fallback_available)

    def test_34_mesh_overlay_consolidates_mesh_fields(self):
        s = self._make_summary(mesh_present=True)
        self.assertEqual(
            s.mesh_overlay_available,
            s.mesh_direct_available or s.mesh_relay_available,
        )

    def test_35_direct_ws_note_contains_primary(self):
        s = self._make_summary(gw_ws_connected=True)
        self.assertIn("primary", s.transport_role_note)

    def test_36_relay_note_contains_fallback_transport(self):
        s = self._make_summary(relay_present=True)
        self.assertIn("fallback_transport", s.transport_role_note)

    def test_37_mesh_only_note_contains_overlay_only(self):
        s = self._make_summary(mesh_present=True)
        self.assertIn("overlay_only", s.transport_role_note)

    def test_38_preferred_path_never_mesh_direct(self):
        # Even if mesh is present, preferred_path must not be "mesh_direct"
        s = self._make_summary(mesh_present=True)
        self.assertNotEqual(
            s.preferred_path,
            "mesh_direct",
            "PR-4: preferred_path must never be 'mesh_direct'",
        )

    def test_39_preferred_path_never_mesh_relay(self):
        s = self._make_summary(mesh_present=True)
        self.assertNotEqual(
            s.preferred_path,
            "mesh_relay",
            "PR-4: preferred_path must never be 'mesh_relay'",
        )

    def test_40_default_summary_fields(self):
        from core.device_readiness import RoutabilitySummary
        rs = RoutabilitySummary(device_id="default_test")
        self.assertFalse(rs.direct_ws_available)
        self.assertFalse(rs.ucm_send_available)
        self.assertFalse(rs.relay_available)
        self.assertFalse(rs.fallback_available)
        self.assertFalse(rs.mesh_direct_available)
        self.assertFalse(rs.mesh_relay_available)
        self.assertFalse(rs.mesh_overlay_available)
        self.assertFalse(rs.effective_routable)
        self.assertEqual(rs.preferred_path, "none")
        self.assertEqual(rs.primary_transport, "none")
        self.assertEqual(rs.transport_role_note, "")


if __name__ == "__main__":
    unittest.main()
