#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr51_dashboard_frontend_demotion.py
===============================================
PR-4 (repo sequence PR-51) — Demote dashboard/frontend from active primary
system surface.

Validates:
  1.  dashboard/LEGACY_SURFACE.md exists.
  2.  dashboard/LEGACY_SURFACE.md contains 'LEGACY' marker.
  3.  dashboard/LEGACY_SURFACE.md contains 'NON-PRIMARY' marker.
  4.  dashboard/frontend/LEGACY_SURFACE.md exists.
  5.  dashboard/frontend/LEGACY_SURFACE.md contains 'LEGACY' marker.
  6.  dashboard/frontend/LEGACY_SURFACE.md contains 'NON-PRIMARY' marker.
  7.  unified_launcher.py does NOT contain the phrase '统一 Dashboard 启动'.
  8.  unified_launcher.py does NOT contain the phrase '控制面板:'.
  9.  unified_launcher.py does NOT contain 'Galaxy Dashboard' in FALLBACK_HTML.
 10.  unified_launcher.py does NOT contain 'Dashboard is served at' in FALLBACK_HTML.
 11.  UnifiedWebUI.FALLBACK_HTML references /docs (API docs).
 12.  unified_launcher.py does NOT define _register_node_with_dashboard.
 13.  unified_launcher.py DOES define _register_node_with_runtime_registry.
 14.  unified_launcher.py does NOT contain 'Dashboard 静态资源未找到' as a warning.
 15.  start_galaxy.py does NOT contain 'Both dashboards have been merged'.
 16.  start_galaxy.py deprecation message mentions 'demoted' or 'non-primary' or 'legacy'.
 17.  dashboard/__init__.py docstring contains 'LEGACY UI SURFACE' (PR-8 preserved).
 18.  dashboard/backend/main.py docstring contains 'LEGACY UI SURFACE' (PR-8 preserved).
 19.  UnifiedWebUI.start() docstring no longer says dashboard is the primary base app.
 20.  UnifiedWebUI class no longer has _get_dashboard_html (renamed to _get_legacy_dashboard_html).
 21.  UnifiedWebUI._get_legacy_dashboard_html exists and is the renamed method.
 22.  unified_launcher.py 'Web UI' section → 'API 服务' section in startup output.
 23.  unified_launcher.py 'Web UI 启动中' phrase removed from startup output.
 24.  unified_launcher.py step-1 comment no longer frames dashboard as base app.
 25.  core.ui_surface_authority still registers dashboard as LEGACY_UI (regression guard).
 26.  dashboard/frontend/LEGACY_SURFACE.md mentions 'tri-state'.
 27.  dashboard/LEGACY_SURFACE.md mentions 'tri-state'.
 28.  start_galaxy.py deprecation message mentions 'tri-state runtime'.
 29.  unified_launcher.py --no-ui argparse help no longer says 'Web UI'.
 30.  unified_launcher.py --port argparse help no longer says 'Web UI 端口'.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
import unittest

# ── project root ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent


# ── helpers ──────────────────────────────────────────────────────────────────

def _read(rel_path: str) -> str:
    return (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")


def _exists(rel_path: str) -> bool:
    return (PROJECT_ROOT / rel_path).exists()


def _import_ui_surface_authority():
    if "core.ui_surface_authority" in sys.modules:
        del sys.modules["core.ui_surface_authority"]
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    return importlib.import_module("core.ui_surface_authority")


# ── test class ───────────────────────────────────────────────────────────────


class TestDashboardFrontendDemotion(unittest.TestCase):
    """PR-4 — dashboard/frontend demotion from active primary surface."""

    # ------------------------------------------------------------------
    # Group 1: legacy marker files
    # ------------------------------------------------------------------

    def test_01_dashboard_legacy_surface_md_exists(self):
        self.assertTrue(
            _exists("dashboard/LEGACY_SURFACE.md"),
            "dashboard/LEGACY_SURFACE.md must exist as a demotion marker",
        )

    def test_02_dashboard_legacy_surface_md_contains_legacy(self):
        content = _read("dashboard/LEGACY_SURFACE.md")
        self.assertIn("LEGACY", content)

    def test_03_dashboard_legacy_surface_md_contains_non_primary(self):
        content = _read("dashboard/LEGACY_SURFACE.md")
        self.assertIn("NON-PRIMARY", content)

    def test_04_dashboard_frontend_directory_fully_deleted(self):
        """PR-1 — dashboard/frontend/ must be fully deleted (not just demoted)."""
        self.assertFalse(
            _exists("dashboard/frontend"),
            "dashboard/frontend/ must not exist — it was fully deleted in PR-1",
        )

    def test_05_dashboard_frontend_legacy_surface_md_does_not_exist(self):
        """PR-1 — dashboard/frontend/LEGACY_SURFACE.md should not exist (directory deleted)."""
        self.assertFalse(
            _exists("dashboard/frontend/LEGACY_SURFACE.md"),
            "dashboard/frontend/LEGACY_SURFACE.md must not exist — directory deleted in PR-1",
        )

    def test_06_dashboard_frontend_public_index_html_does_not_exist(self):
        """PR-1 — dashboard/frontend/public/index.html must not exist."""
        self.assertFalse(
            _exists("dashboard/frontend/public/index.html"),
            "dashboard/frontend/public/index.html must not exist — frontend deleted in PR-1",
        )

    # ------------------------------------------------------------------
    # Group 2: unified_launcher.py messaging demotions
    # ------------------------------------------------------------------

    def test_07_no_unified_dashboard_startup_message(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "统一 Dashboard 启动",
            content,
            "unified_launcher.py must not frame dashboard as the primary startup target",
        )

    def test_08_no_control_panel_message(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "控制面板:",
            content,
            "unified_launcher.py must not use '控制面板:' (implies dashboard is primary)",
        )

    def test_09_fallback_html_no_galaxy_dashboard(self):
        content = _read("unified_launcher.py")
        # Find FALLBACK_HTML assignment and check it doesn't promote Dashboard
        self.assertNotIn(
            "Galaxy Dashboard",
            content,
            "FALLBACK_HTML must not present 'Galaxy Dashboard' as primary surface",
        )

    def test_10_fallback_html_no_dashboard_is_served_at(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "Dashboard is served at",
            content,
        )

    def test_11_fallback_html_references_api_docs(self):
        content = _read("unified_launcher.py")
        self.assertIn(
            "/docs",
            content,
            "FALLBACK_HTML should point to API docs (/docs)",
        )

    # ------------------------------------------------------------------
    # Group 3: method renaming
    # ------------------------------------------------------------------

    def test_12_no_register_node_with_dashboard_method(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "_register_node_with_dashboard",
            content,
            "The old _register_node_with_dashboard method must be renamed",
        )

    def test_13_register_node_with_runtime_registry_exists(self):
        content = _read("unified_launcher.py")
        self.assertIn(
            "_register_node_with_runtime_registry",
            content,
            "The renamed _register_node_with_runtime_registry must be present",
        )

    # ------------------------------------------------------------------
    # Group 4: frontend static asset warning demoted
    # ------------------------------------------------------------------

    def test_14_no_dashboard_static_resource_warning(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "Dashboard 静态资源未找到",
            content,
            "unified_launcher.py must not warn about missing dashboard static assets "
            "(legacy surface absence is not a runtime warning)",
        )

    # ------------------------------------------------------------------
    # Group 5: start_galaxy.py compatibility wrapper
    # ------------------------------------------------------------------

    def test_15_start_galaxy_no_both_dashboards_merged(self):
        content = _read("start_galaxy.py")
        self.assertNotIn(
            "Both dashboards have been merged",
            content,
        )

    def test_16_start_galaxy_deprecation_mentions_legacy_surface(self):
        content = _read("start_galaxy.py")
        lowered = content.lower()
        self.assertTrue(
            "demoted" in lowered or "non-primary" in lowered or "legacy surface" in lowered,
            "start_galaxy.py deprecation messaging should reference demotion/legacy surface status",
        )

    # ------------------------------------------------------------------
    # Group 6: PR-8 markers preserved (regression guard)
    # ------------------------------------------------------------------

    def test_17_dashboard_init_preserves_legacy_ui_surface_marker(self):
        """PR-1 retains the 'LEGACY UI SURFACE' marker from PR-8 for compatibility."""
        content = _read("dashboard/__init__.py")
        self.assertIn(
            "LEGACY UI SURFACE",
            content,
            "dashboard/__init__.py must retain the 'LEGACY UI SURFACE' marker "
            "(PR-8 compatibility; PR-1 additionally marks frontend as deleted)",
        )

    def test_18_dashboard_backend_main_preserves_legacy_ui_surface_marker(self):
        content = _read("dashboard/backend/main.py")
        self.assertIn(
            "LEGACY UI SURFACE",
            content,
            "dashboard/backend/main.py must retain the PR-8 LEGACY UI SURFACE marker",
        )

    # ------------------------------------------------------------------
    # Group 7: docstring updates
    # ------------------------------------------------------------------

    def test_19_unified_web_ui_start_docstring_no_dashboard_base_app(self):
        content = _read("unified_launcher.py")
        # The old docstring said: "以 dashboard.backend.main.app 为基础应用"
        self.assertNotIn(
            "以 dashboard.backend.main.app 为基础应用",
            content,
            "UnifiedWebUI.start() docstring must not frame dashboard as the primary base app",
        )

    def test_20_no_get_dashboard_html_method(self):
        content = _read("unified_launcher.py")
        # Old method name must be gone
        self.assertNotIn(
            "def _get_dashboard_html",
            content,
            "_get_dashboard_html must be renamed to _get_legacy_dashboard_html",
        )

    def test_21_get_legacy_dashboard_html_exists(self):
        content = _read("unified_launcher.py")
        self.assertIn(
            "def _get_legacy_dashboard_html",
            content,
        )

    # ------------------------------------------------------------------
    # Group 8: section heading updates
    # ------------------------------------------------------------------

    def test_22_api_service_section_exists(self):
        content = _read("unified_launcher.py")
        self.assertIn(
            "API 服务",
            content,
            "unified_launcher.py should use 'API 服务' instead of 'Web UI' as section heading",
        )

    def test_23_no_web_ui_qidong_phrase(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "Web UI 启动中",
            content,
            "The startup message 'Web UI 启动中' should be replaced with API 服务 messaging",
        )

    # ------------------------------------------------------------------
    # Group 9: step-1 comment
    # ------------------------------------------------------------------

    def test_24_step1_no_dashboard_base_framing(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            "以 dashboard/backend/main.py 的完整 app 为基础",
            content,
            "Step-1 comment must not frame dashboard as the primary base",
        )

    # ------------------------------------------------------------------
    # Group 10: ui_surface_authority regression guard
    # ------------------------------------------------------------------

    def test_25_ui_surface_authority_still_registers_dashboard_as_legacy(self):
        m = _import_ui_surface_authority()
        role = m.get_ui_surface_role("dashboard")
        self.assertIsNotNone(role, "dashboard must still be registered in UISurfaceAuthorityRegistry")
        self.assertEqual(
            role,
            m.UISurfaceRole.LEGACY_UI,
            "dashboard must be registered as LEGACY_UI (PR-8 regression guard)",
        )

    # ------------------------------------------------------------------
    # Group 11: legacy marker files direction content
    # ------------------------------------------------------------------

    def test_26_dashboard_frontend_directory_deleted_not_just_demoted(self):
        """PR-1 — dashboard/frontend/ must be fully deleted."""
        self.assertFalse(
            _exists("dashboard/frontend"),
            "dashboard/frontend/ directory must be fully deleted in PR-1 (not just demoted)",
        )

    def test_27_dashboard_legacy_md_mentions_tristate(self):
        content = _read("dashboard/LEGACY_SURFACE.md")
        self.assertIn(
            "tri-state",
            content,
        )

    # ------------------------------------------------------------------
    # Group 12: start_galaxy.py direction
    # ------------------------------------------------------------------

    def test_28_start_galaxy_mentions_tristate_runtime(self):
        content = _read("start_galaxy.py")
        self.assertIn(
            "tri-state",
            content,
            "start_galaxy.py deprecation message should mention the current direction "
            "(desktop tri-state runtime)",
        )

    # ------------------------------------------------------------------
    # Group 13: argparse help text demotions
    # ------------------------------------------------------------------

    def test_29_no_ui_argparse_help_not_web_ui(self):
        content = _read("unified_launcher.py")
        # The old help was "不启动 Web UI" — it should now reference API service
        self.assertNotIn(
            "不启动 Web UI",
            content,
            "--no-ui argparse help must be updated to reflect API service, not Web UI",
        )

    def test_30_port_argparse_help_not_web_ui_port(self):
        content = _read("unified_launcher.py")
        self.assertNotIn(
            '"Web UI 端口"',
            content,
            "--port argparse help must not say 'Web UI 端口'",
        )


if __name__ == "__main__":
    unittest.main()
