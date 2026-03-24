#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr52_repo_layout.py
================================

PR-8 (repo-layout) — Repository layout organisation: separate active runtime
assets, desktop-status assets, and legacy/transitional assets.

Validates:
  1.  core/repo_layout_registry.py exists.
  2.  DirectoryRole is importable from core.repo_layout_registry.
  3.  DirectoryRole has ACTIVE_RUNTIME constant.
  4.  DirectoryRole has ACTIVE_DESKTOP_STATUS constant.
  5.  DirectoryRole has ACTIVE_DESKTOP_SHELL constant.
  6.  DirectoryRole has LEGACY_SURFACE constant.
  7.  DirectoryRole has LEGACY_SHELL constant.
  8.  DirectoryRole has TRANSITIONAL constant.
  9.  DirectoryRole has INFRASTRUCTURE constant.
 10.  LayoutZone is importable from core.repo_layout_registry.
 11.  LayoutZone has CORE_RUNTIME constant.
 12.  LayoutZone has DESKTOP_STATUS constant.
 13.  LayoutZone has LEGACY constant.
 14.  LayoutZone has INFRASTRUCTURE constant.
 15.  RepoLayoutEntry is importable and instantiable.
 16.  RepoLayoutEntry.is_active() returns True for ACTIVE_RUNTIME role.
 17.  RepoLayoutEntry.is_active() returns True for ACTIVE_DESKTOP_STATUS role.
 18.  RepoLayoutEntry.is_legacy() returns True for LEGACY_SURFACE role.
 19.  RepoLayoutEntry.is_legacy() returns True for LEGACY_SHELL role.
 20.  RepoLayoutEntry.is_legacy() returns True for TRANSITIONAL role.
 21.  RepoLayoutEntry.to_dict() returns a dict with 'path' key.
 22.  RepoLayoutEntry.to_dict() contains 'role' key.
 23.  RepoLayoutEntry.to_dict() contains 'zone' key.
 24.  RepoLayoutEntry.to_dict() contains 'is_active' key.
 25.  RepoLayoutEntry.to_dict() contains 'is_legacy' key.
 26.  is_active_runtime_directory("core") returns True.
 27.  is_active_runtime_directory("launcher") returns True.
 28.  is_active_runtime_directory("nodes") returns True.
 29.  is_active_runtime_directory("contracts") returns True.
 30.  is_active_runtime_directory("galaxy_gateway") returns True.
 31.  is_active_runtime_directory("desktop_projection") returns True.
 32.  is_active_runtime_directory("windows_client/status_board_v2") returns True.
 33.  is_active_runtime_directory("windows_client/autonomy") returns True.
 34.  is_legacy_directory("dashboard") returns True.
 35.  is_legacy_directory("windows_client") returns True.
 36.  is_legacy_directory("enhancements") returns True.
 37.  is_active_desktop_status_directory("windows_client/status_board_v2") returns True.
 38.  is_active_desktop_status_directory("dashboard") returns False.
 39.  get_layout_zone("core") returns LayoutZone.CORE_RUNTIME.
 40.  get_layout_zone("windows_client/status_board_v2") returns LayoutZone.DESKTOP_STATUS.
 41.  get_layout_zone("dashboard") returns LayoutZone.LEGACY.
 42.  get_layout_zone("docs") returns LayoutZone.INFRASTRUCTURE.
 43.  build_repo_layout_summary() returns a dict.
 44.  build_repo_layout_summary() has 'active_count' key.
 45.  build_repo_layout_summary() has 'legacy_count' key.
 46.  build_repo_layout_summary() active_count >= 5.
 47.  build_repo_layout_summary() legacy_count >= 2.
 48.  build_repo_layout_summary() core_runtime_count >= 5.
 49.  build_repo_layout_summary() desktop_status_count >= 1.
 50.  get_repo_layout_registry() returns singleton RepoLayoutRegistry.
 51.  REPO_LAYOUT_REGISTRY is a dict (public immutable view).
 52.  REPO_LAYOUT_REGISTRY contains 'core' key.
 53.  REPO_LAYOUT_REGISTRY contains 'launcher' key.
 54.  REPO_LAYOUT_REGISTRY contains 'dashboard' key.
 55.  REPO_LAYOUT_REGISTRY contains 'windows_client/status_board_v2' key.
 56.  REPO_LAYOUT_REGISTRY contains 'enhancements' key.
 57.  docs/REPO_LAYOUT.md exists.
 58.  docs/REPO_LAYOUT.md contains 'active' (case-insensitive).
 59.  docs/REPO_LAYOUT.md contains 'legacy' (case-insensitive).
 60.  docs/REPO_LAYOUT.md references core/.
 61.  docs/REPO_LAYOUT.md references launcher/.
 62.  docs/REPO_LAYOUT.md references nodes/.
 63.  docs/REPO_LAYOUT.md references status_board_v2.
 64.  docs/REPO_LAYOUT.md references DesktopPresenceRuntime.
 65.  windows_client/status_board_v2/ACTIVE_SURFACE.md exists.
 66.  windows_client/status_board_v2/ACTIVE_SURFACE.md contains 'ACTIVE'.
 67.  windows_client/status_board_v2/ACTIVE_SURFACE.md contains 'canonical'.
 68.  windows_client/status_board_v2/ACTIVE_SURFACE.md references projection endpoint.
 69.  enhancements/LEGACY_TRANSITION.md exists.
 70.  enhancements/LEGACY_TRANSITION.md contains 'TRANSITIONAL'.
 71.  enhancements/LEGACY_TRANSITION.md contains 'LEGACY'.
 72.  enhancements/LEGACY_TRANSITION.md references hard-disabled path.
 73.  legacy_paths.py contains PR-8-layout guardrail entries.
 74.  legacy_paths.py registers enhancements.clients.windows_client.run_ui.
 75.  core.repo_layout_registry is JSON-serialisable via build_repo_layout_summary().
"""

from __future__ import annotations

import importlib
import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


# ── helpers ───────────────────────────────────────────────────────────────────


def _read(rel: str) -> str:
    return (PROJECT_ROOT / rel).read_text(encoding="utf-8")


def _exists(rel: str) -> bool:
    return (PROJECT_ROOT / rel).exists()


def _import_registry():
    mod_name = "core.repo_layout_registry"
    if mod_name in sys.modules:
        del sys.modules[mod_name]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return importlib.import_module(mod_name)


# ── test class ────────────────────────────────────────────────────────────────


class TestRepoLayoutRegistryModule(unittest.TestCase):
    """Group A — Module and enum presence."""

    def test_01_module_file_exists(self):
        self.assertTrue(_exists("core/repo_layout_registry.py"))

    def test_02_directory_role_importable(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod, "DirectoryRole"))

    def test_03_directory_role_active_runtime(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "ACTIVE_RUNTIME"))

    def test_04_directory_role_active_desktop_status(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "ACTIVE_DESKTOP_STATUS"))

    def test_05_directory_role_active_desktop_shell(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "ACTIVE_DESKTOP_SHELL"))

    def test_06_directory_role_legacy_surface(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "LEGACY_SURFACE"))

    def test_07_directory_role_legacy_shell(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "LEGACY_SHELL"))

    def test_08_directory_role_transitional(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "TRANSITIONAL"))

    def test_09_directory_role_infrastructure(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.DirectoryRole, "INFRASTRUCTURE"))

    def test_10_layout_zone_importable(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod, "LayoutZone"))

    def test_11_layout_zone_core_runtime(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.LayoutZone, "CORE_RUNTIME"))

    def test_12_layout_zone_desktop_status(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.LayoutZone, "DESKTOP_STATUS"))

    def test_13_layout_zone_legacy(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.LayoutZone, "LEGACY"))

    def test_14_layout_zone_infrastructure(self):
        mod = _import_registry()
        self.assertTrue(hasattr(mod.LayoutZone, "INFRASTRUCTURE"))


class TestRepoLayoutEntry(unittest.TestCase):
    """Group B — RepoLayoutEntry dataclass behaviour."""

    def _make_entry(self, role, zone="core_runtime"):
        mod = _import_registry()
        LayoutZone = mod.LayoutZone
        zone_val = getattr(LayoutZone, zone.upper()) if isinstance(zone, str) else zone
        return mod.RepoLayoutEntry(
            path="test/path",
            role=role,
            zone=zone_val,
            description="test",
        )

    def test_15_repo_layout_entry_instantiable(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="test",
        )
        self.assertEqual(entry.path, "core")

    def test_16_is_active_true_for_active_runtime(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="x",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        self.assertTrue(entry.is_active())

    def test_17_is_active_true_for_active_desktop_status(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="x",
            role=mod.DirectoryRole.ACTIVE_DESKTOP_STATUS,
            zone=mod.LayoutZone.DESKTOP_STATUS,
            description="x",
        )
        self.assertTrue(entry.is_active())

    def test_18_is_legacy_true_for_legacy_surface(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="x",
            role=mod.DirectoryRole.LEGACY_SURFACE,
            zone=mod.LayoutZone.LEGACY,
            description="x",
        )
        self.assertTrue(entry.is_legacy())

    def test_19_is_legacy_true_for_legacy_shell(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="x",
            role=mod.DirectoryRole.LEGACY_SHELL,
            zone=mod.LayoutZone.LEGACY,
            description="x",
        )
        self.assertTrue(entry.is_legacy())

    def test_20_is_legacy_true_for_transitional(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="x",
            role=mod.DirectoryRole.TRANSITIONAL,
            zone=mod.LayoutZone.LEGACY,
            description="x",
        )
        self.assertTrue(entry.is_legacy())

    def test_21_to_dict_has_path(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        d = entry.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("path", d)

    def test_22_to_dict_has_role(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        self.assertIn("role", entry.to_dict())

    def test_23_to_dict_has_zone(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        self.assertIn("zone", entry.to_dict())

    def test_24_to_dict_has_is_active(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        self.assertIn("is_active", entry.to_dict())

    def test_25_to_dict_has_is_legacy(self):
        mod = _import_registry()
        entry = mod.RepoLayoutEntry(
            path="core",
            role=mod.DirectoryRole.ACTIVE_RUNTIME,
            zone=mod.LayoutZone.CORE_RUNTIME,
            description="x",
        )
        self.assertIn("is_legacy", entry.to_dict())


class TestActiveRuntimeDirectories(unittest.TestCase):
    """Group C — Active runtime directory classification."""

    def _is_active(self, path):
        mod = _import_registry()
        return mod.is_active_runtime_directory(path)

    def test_26_core_is_active(self):
        self.assertTrue(self._is_active("core"))

    def test_27_launcher_is_active(self):
        self.assertTrue(self._is_active("launcher"))

    def test_28_nodes_is_active(self):
        self.assertTrue(self._is_active("nodes"))

    def test_29_contracts_is_active(self):
        self.assertTrue(self._is_active("contracts"))

    def test_30_galaxy_gateway_is_active(self):
        self.assertTrue(self._is_active("galaxy_gateway"))

    def test_31_desktop_projection_is_active(self):
        self.assertTrue(self._is_active("desktop_projection"))

    def test_32_status_board_v2_is_active(self):
        self.assertTrue(self._is_active("windows_client/status_board_v2"))

    def test_33_autonomy_is_active(self):
        self.assertTrue(self._is_active("windows_client/autonomy"))


class TestLegacyDirectories(unittest.TestCase):
    """Group D — Legacy directory classification."""

    def _is_legacy(self, path):
        mod = _import_registry()
        return mod.is_legacy_directory(path)

    def test_34_dashboard_is_legacy(self):
        self.assertTrue(self._is_legacy("dashboard"))

    def test_35_windows_client_is_legacy(self):
        self.assertTrue(self._is_legacy("windows_client"))

    def test_36_enhancements_is_legacy(self):
        self.assertTrue(self._is_legacy("enhancements"))

    def test_37_status_board_v2_is_active_desktop_status(self):
        mod = _import_registry()
        self.assertTrue(mod.is_active_desktop_status_directory("windows_client/status_board_v2"))

    def test_38_dashboard_is_not_active_desktop_status(self):
        mod = _import_registry()
        self.assertFalse(mod.is_active_desktop_status_directory("dashboard"))


class TestGetLayoutZone(unittest.TestCase):
    """Group E — Layout zone queries."""

    def test_39_core_zone_is_core_runtime(self):
        mod = _import_registry()
        self.assertEqual(mod.get_layout_zone("core"), mod.LayoutZone.CORE_RUNTIME)

    def test_40_status_board_v2_zone_is_desktop_status(self):
        mod = _import_registry()
        self.assertEqual(
            mod.get_layout_zone("windows_client/status_board_v2"),
            mod.LayoutZone.DESKTOP_STATUS,
        )

    def test_41_dashboard_zone_is_legacy(self):
        mod = _import_registry()
        self.assertEqual(mod.get_layout_zone("dashboard"), mod.LayoutZone.LEGACY)

    def test_42_docs_zone_is_infrastructure(self):
        mod = _import_registry()
        self.assertEqual(mod.get_layout_zone("docs"), mod.LayoutZone.INFRASTRUCTURE)


class TestSummaryAndRegistry(unittest.TestCase):
    """Group F — Summary builder and public registry."""

    def test_43_build_summary_returns_dict(self):
        mod = _import_registry()
        summary = mod.build_repo_layout_summary()
        self.assertIsInstance(summary, dict)

    def test_44_summary_has_active_count(self):
        mod = _import_registry()
        self.assertIn("active_count", mod.build_repo_layout_summary())

    def test_45_summary_has_legacy_count(self):
        mod = _import_registry()
        self.assertIn("legacy_count", mod.build_repo_layout_summary())

    def test_46_summary_active_count_ge_5(self):
        mod = _import_registry()
        self.assertGreaterEqual(mod.build_repo_layout_summary()["active_count"], 5)

    def test_47_summary_legacy_count_ge_2(self):
        mod = _import_registry()
        self.assertGreaterEqual(mod.build_repo_layout_summary()["legacy_count"], 2)

    def test_48_summary_core_runtime_count_ge_5(self):
        mod = _import_registry()
        self.assertGreaterEqual(mod.build_repo_layout_summary()["core_runtime_count"], 5)

    def test_49_summary_desktop_status_count_ge_1(self):
        mod = _import_registry()
        self.assertGreaterEqual(mod.build_repo_layout_summary()["desktop_status_count"], 1)

    def test_50_get_registry_returns_singleton(self):
        mod = _import_registry()
        reg1 = mod.get_repo_layout_registry()
        reg2 = mod.get_repo_layout_registry()
        self.assertIs(reg1, reg2)

    def test_51_repo_layout_registry_is_dict(self):
        mod = _import_registry()
        self.assertIsInstance(mod.REPO_LAYOUT_REGISTRY, dict)

    def test_52_registry_contains_core(self):
        mod = _import_registry()
        self.assertIn("core", mod.REPO_LAYOUT_REGISTRY)

    def test_53_registry_contains_launcher(self):
        mod = _import_registry()
        self.assertIn("launcher", mod.REPO_LAYOUT_REGISTRY)

    def test_54_registry_contains_dashboard(self):
        mod = _import_registry()
        self.assertIn("dashboard", mod.REPO_LAYOUT_REGISTRY)

    def test_55_registry_contains_status_board_v2(self):
        mod = _import_registry()
        self.assertIn("windows_client/status_board_v2", mod.REPO_LAYOUT_REGISTRY)

    def test_56_registry_contains_enhancements(self):
        mod = _import_registry()
        self.assertIn("enhancements", mod.REPO_LAYOUT_REGISTRY)


class TestRepoLayoutMd(unittest.TestCase):
    """Group G — docs/REPO_LAYOUT.md marker file."""

    def test_57_repo_layout_md_exists(self):
        self.assertTrue(_exists("docs/REPO_LAYOUT.md"))

    def test_58_repo_layout_md_contains_active(self):
        self.assertIn("active", _read("docs/REPO_LAYOUT.md").lower())

    def test_59_repo_layout_md_contains_legacy(self):
        self.assertIn("legacy", _read("docs/REPO_LAYOUT.md").lower())

    def test_60_repo_layout_md_references_core(self):
        self.assertIn("core/", _read("docs/REPO_LAYOUT.md"))

    def test_61_repo_layout_md_references_launcher(self):
        self.assertIn("launcher/", _read("docs/REPO_LAYOUT.md"))

    def test_62_repo_layout_md_references_nodes(self):
        self.assertIn("nodes/", _read("docs/REPO_LAYOUT.md"))

    def test_63_repo_layout_md_references_status_board_v2(self):
        self.assertIn("status_board_v2", _read("docs/REPO_LAYOUT.md"))

    def test_64_repo_layout_md_references_desktop_presence_runtime(self):
        self.assertIn("DesktopPresenceRuntime", _read("docs/REPO_LAYOUT.md"))


class TestActiveSurfaceMd(unittest.TestCase):
    """Group H — windows_client/status_board_v2/ACTIVE_SURFACE.md marker."""

    def test_65_active_surface_md_exists(self):
        self.assertTrue(_exists("windows_client/status_board_v2/ACTIVE_SURFACE.md"))

    def test_66_active_surface_md_contains_active(self):
        self.assertIn("ACTIVE", _read("windows_client/status_board_v2/ACTIVE_SURFACE.md"))

    def test_67_active_surface_md_contains_canonical(self):
        self.assertIn("canonical", _read("windows_client/status_board_v2/ACTIVE_SURFACE.md").lower())

    def test_68_active_surface_md_references_projection_endpoint(self):
        content = _read("windows_client/status_board_v2/ACTIVE_SURFACE.md")
        self.assertIn("projection/runtime", content)


class TestLegacyTransitionMd(unittest.TestCase):
    """Group I — enhancements/LEGACY_TRANSITION.md marker."""

    def test_69_legacy_transition_md_exists(self):
        self.assertTrue(_exists("enhancements/LEGACY_TRANSITION.md"))

    def test_70_legacy_transition_md_contains_transitional(self):
        self.assertIn("TRANSITIONAL", _read("enhancements/LEGACY_TRANSITION.md"))

    def test_71_legacy_transition_md_contains_legacy(self):
        self.assertIn("LEGACY", _read("enhancements/LEGACY_TRANSITION.md"))

    def test_72_legacy_transition_md_references_hard_disabled(self):
        content = _read("enhancements/LEGACY_TRANSITION.md").lower()
        self.assertIn("hard-disabled", content)


class TestLegacyPathsRegistration(unittest.TestCase):
    """Group J — legacy_paths.py PR-8-layout registrations."""

    def _get_registry(self):
        mod_name = "core.orchestration_authority.legacy_paths"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        return importlib.import_module(mod_name)

    def test_73_legacy_paths_has_pr8_layout_entries(self):
        content = _read("core/orchestration_authority/legacy_paths.py")
        self.assertIn("PR-8-layout", content)

    def test_74_legacy_paths_registers_enhancements_run_ui(self):
        mod = self._get_registry()
        self.assertIn(
            "enhancements.clients.windows_client.run_ui",
            mod.LEGACY_PATH_REGISTRY,
        )

    def test_75_summary_is_json_serialisable(self):
        mod = _import_registry()
        summary = mod.build_repo_layout_summary()
        serialised = json.dumps(summary)
        roundtrip = json.loads(serialised)
        self.assertEqual(roundtrip["active_count"], summary["active_count"])


if __name__ == "__main__":
    unittest.main()
