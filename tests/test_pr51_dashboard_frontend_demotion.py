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
import sys
import unittest
from pathlib import Path

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

    def test_01_dashboard_package_deleted(self):
        self.assertFalse(_exists("dashboard"), "dashboard/ must be deleted")

    def test_02_dashboard_legacy_surface_md_deleted(self):
        self.assertFalse(_exists("dashboard/LEGACY_SURFACE.md"))

    def test_03_dashboard_backend_deleted(self):
        self.assertFalse(_exists("dashboard/backend/main.py"))

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
        content = _read("launcher/services.py")
        self.assertNotIn(
            "统一 Dashboard 启动",
            content,
            "unified_launcher.py must not frame dashboard as the primary startup target",
        )

    def test_08_no_control_panel_message(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "控制面板:",
            content,
            "unified_launcher.py must not use '控制面板:' (implies dashboard is primary)",
        )

    def test_09_fallback_html_no_galaxy_dashboard(self):
        content = _read("launcher/services.py")
        # Find FALLBACK_HTML assignment and check it doesn't promote Dashboard
        self.assertNotIn(
            "Galaxy Dashboard",
            content,
            "FALLBACK_HTML must not present 'Galaxy Dashboard' as primary surface",
        )

    def test_10_fallback_html_no_dashboard_is_served_at(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "Dashboard is served at",
            content,
        )

    def test_11_launcher_still_surfaces_api_docs(self):
        """网关仍要把 /docs 指出来。

        原意是"FALLBACK_HTML 应指向 API 文档"。FALLBACK_HTML 已随 legacy
        dashboard 一并删除(它只被那个零调用方的方法引用),但"启动后要让人知道
        API 文档在哪"这条意图仍然成立——现在由启动日志承担。
        """
        content = _read("launcher/services.py")
        self.assertIn(
            "/docs",
            content,
            "启动器必须在某处指出 API 文档地址 (/docs)",
        )

    # ------------------------------------------------------------------
    # Group 3: method renaming
    # ------------------------------------------------------------------

    def test_12_no_register_node_with_dashboard_method(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "_register_node_with_dashboard",
            content,
            "The old _register_node_with_dashboard method must be renamed",
        )

    def test_13_register_node_with_dashboard_absent(self):
        content = _read("launcher/services.py")
        self.assertNotIn("_register_node_with_dashboard", content)

    # ------------------------------------------------------------------
    # Group 4: frontend static asset warning demoted
    # ------------------------------------------------------------------

    def test_14_no_dashboard_static_resource_warning(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "Dashboard 静态资源未找到",
            content,
            "unified_launcher.py must not warn about missing dashboard static assets "
            "(legacy surface absence is not a runtime warning)",
        )

    # ------------------------------------------------------------------
    # Group 5: start_galaxy.py — fully removed
    # ------------------------------------------------------------------

    def test_15_start_galaxy_fully_removed(self):
        """start_galaxy.py has been fully removed from the repository."""
        self.assertFalse(
            (PROJECT_ROOT / "start_galaxy.py").exists(),
            "start_galaxy.py must not exist — it has been permanently removed. " "Use 'python main.py' instead.",
        )

    def test_16_main_py_is_the_sole_startup_entry(self):
        """main.py 是唯一入口；四个旧启动器本体已删除。

        这条原本断言 ``unified_launcher.py`` **必须存在**（当时它是"唯一的非 main
        启动入口"）。启动器统一（docs/LAUNCHER_UNIFICATION_PLAN.md 第 8 步）之后
        "唯一入口"的字面含义变成了：main.py 之外一个都没有。
        """
        self.assertTrue((PROJECT_ROOT / "main.py").exists(), "main.py must exist")
        self.assertTrue(
            (PROJECT_ROOT / "launcher" / "services.py").exists(),
            "服务编排实现体 launcher/services.py must exist",
        )
        for name in ("unified_launcher.py", "launch_desktop.py", "system_manager.py", "install.py"):
            self.assertFalse((PROJECT_ROOT / name).exists(), f"{name} 已退役，请用 python main.py")

    # ------------------------------------------------------------------
    # Group 6: PR-8 markers preserved (regression guard)
    # ------------------------------------------------------------------

    def test_17_dashboard_init_deleted(self):
        self.assertFalse(_exists("dashboard/__init__.py"))

    def test_18_dashboard_backend_main_deleted(self):
        self.assertFalse(_exists("dashboard/backend/main.py"))

    # ------------------------------------------------------------------
    # Group 7: docstring updates
    # ------------------------------------------------------------------

    def test_19_unified_web_ui_start_docstring_no_dashboard_base_app(self):
        content = _read("launcher/services.py")
        # The old docstring said: "以 dashboard.backend.main.app 为基础应用"
        self.assertNotIn(
            "以 dashboard.backend.main.app 为基础应用",
            content,
            "UnifiedWebUI.start() docstring must not frame dashboard as the primary base app",
        )

    def test_20_no_get_dashboard_html_method(self):
        content = _read("launcher/services.py")
        # Old method name must be gone
        self.assertNotIn(
            "def _get_dashboard_html",
            content,
            "_get_dashboard_html must be renamed to _get_legacy_dashboard_html",
        )

    def test_21_get_legacy_dashboard_html_is_gone(self):
        """再降一级：从"已改名的遗留方法"降为"已删除"。

        PR-51 当时把 ``_get_dashboard_html`` 改名为 ``_get_legacy_dashboard_html``
        以示降级,这条测试钉的是改名成功。现在面板表层收敛,它连同 FALLBACK_HTML
        一起删除——理由不是"改名不够",而是它**零调用方**,且它要读的
        ``dashboard/frontend/public/index.html`` 在仓库里根本不存在。
        断言相应地从"必须存在"翻成"必须不存在"。
        """
        content = _read("launcher/services.py")
        self.assertNotIn(
            "def _get_legacy_dashboard_html",
            content,
            "遗留 dashboard 方法已删除,不应重新出现",
        )
        self.assertNotIn(
            "FALLBACK_HTML = ",
            content,
            "FALLBACK_HTML 已随该方法删除,不应重新出现",
        )

    # ------------------------------------------------------------------
    # Group 8: section heading updates
    # ------------------------------------------------------------------

    def test_22_api_service_section_exists(self):
        content = _read("launcher/services.py")
        self.assertIn(
            "API 服务",
            content,
            "unified_launcher.py should use 'API 服务' instead of 'Web UI' as section heading",
        )

    def test_23_no_web_ui_qidong_phrase(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "Web UI 启动中",
            content,
            "The startup message 'Web UI 启动中' should be replaced with API 服务 messaging",
        )

    # ------------------------------------------------------------------
    # Group 9: step-1 comment
    # ------------------------------------------------------------------

    def test_24_step1_no_dashboard_base_framing(self):
        content = _read("launcher/services.py")
        self.assertNotIn(
            "以 dashboard/backend/main.py 的完整 app 为基础",
            content,
            "Step-1 comment must not frame dashboard as the primary base",
        )

    # ------------------------------------------------------------------
    # Group 10: ui_surface_authority regression guard
    # ------------------------------------------------------------------

    def test_25_ui_surface_authority_registers_dashboard_as_deleted(self):
        m = _import_ui_surface_authority()
        role = m.get_ui_surface_role("dashboard")
        self.assertIsNotNone(role, "dashboard must still be registered in UISurfaceAuthorityRegistry")
        self.assertEqual(
            role,
            m.UISurfaceRole.DELETED,
            "dashboard must be registered as DELETED",
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

    def test_27_dashboard_legacy_md_deleted(self):
        self.assertFalse(_exists("dashboard/LEGACY_SURFACE.md"))

    # ------------------------------------------------------------------
    # Group 12: start_galaxy.py — removed (direction now in MAINTAINER_RUNBOOK)
    # ------------------------------------------------------------------

    def test_28_maintainer_runbook_mentions_tristate(self):
        """MAINTAINER_RUNBOOK.md documents the tri-state runtime (replaces start_galaxy.py note)."""
        content = _read("docs/MAINTAINER_RUNBOOK.md")
        self.assertIn(
            "tri-state",
            content,
            "MAINTAINER_RUNBOOK.md must mention the desktop tri-state runtime direction",
        )

    # ------------------------------------------------------------------
    # Group 13: argparse help text demotions
    # ------------------------------------------------------------------

    def test_29_no_ui_argparse_help_not_web_ui(self):
        # argparse 搬家了：CLI 统一到 main.py（unified_launcher.py 已删除）。
        # ``--no-ui`` 本身也没有收编——它只写 SystemConfig 字段、start() 从不读，
        # 是个从未生效的开关。这条断言仍然成立且仍有意义：唯一的 CLI 上不许
        # 再出现"Web UI"那套把 dashboard 当主表层的说法。
        content = _read("main.py")
        # The old help was "不启动 Web UI" — it should now reference API service
        self.assertNotIn(
            "不启动 Web UI",
            content,
            "--no-ui argparse help must be updated to reflect API service, not Web UI",
        )

    def test_30_port_argparse_help_not_web_ui_port(self):
        content = _read("main.py")  # argparse 已统一到 main.py
        self.assertNotIn(
            '"Web UI 端口"',
            content,
            "--port argparse help must not say 'Web UI 端口'",
        )


if __name__ == "__main__":
    unittest.main()
