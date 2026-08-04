"""
Tests for the refactored launcher sub-modules.

Validates that:
- launcher.bootstrap exports the expected types and functions
- launcher.service_manager provides correct lifecycle semantics
- launcher.core_services, node_startup, health_checks, shutdown are importable
- launcher.__init__ re-exports all public symbols
- launcher/services.py exposes the public API that unified_launcher.py used to（后者已删除）
- The authoritative startup path (main.py -> unified_launcher.py) is intact
"""

import asyncio
import os
import sys
from pathlib import Path

import pytest

# ── Shared project root fixture ───────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent


# =============================================================================
# launcher.bootstrap
# =============================================================================


class TestBootstrapModule:
    """launcher.bootstrap — enums, config, write_entrypoint, display helpers."""

    def test_project_root_is_repo_root(self):
        from launcher.bootstrap import PROJECT_ROOT as bs_root

        # launcher/bootstrap.py is at <repo>/launcher/bootstrap.py
        # so PROJECT_ROOT must equal <repo>
        assert bs_root == PROJECT_ROOT

    def test_system_state_members(self):
        from launcher.bootstrap import SystemState

        expected = {
            "INITIALIZING",
            "LOADING_CONFIG",
            "STARTING_CORE",
            "STARTING_NODES",
            "STARTING_L4",
            "STARTING_UI",
            "RUNNING",
            "STOPPING",
            "STOPPED",
            "ERROR",
        }
        assert {s.name for s in SystemState} == expected

    def test_service_type_values(self):
        from launcher.bootstrap import ServiceType

        assert ServiceType.CORE.value == "core"
        assert ServiceType.NODE.value == "node"
        assert ServiceType.L4.value == "l4"
        assert ServiceType.API.value == "api"
        assert ServiceType.UI.value == "ui"

    def test_system_config_defaults(self):
        from launcher.bootstrap import SystemConfig

        cfg = SystemConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.web_ui_port > 0
        assert cfg.device_api_port > 0
        assert cfg.enable_l4 is True
        assert cfg.enable_nodes is True
        assert cfg.enable_web_ui is True

    def test_system_config_has_llm_api_false_by_default(self):
        from launcher.bootstrap import SystemConfig

        cfg = SystemConfig()
        assert cfg.has_llm_api() is False

    def test_system_config_has_llm_api_true_when_key_set(self):
        from launcher.bootstrap import SystemConfig

        cfg = SystemConfig(openai_api_key="sk-test")
        assert cfg.has_llm_api() is True

    def test_system_config_get_status_dict_structure(self):
        from launcher.bootstrap import SystemConfig

        cfg = SystemConfig()
        d = cfg.get_status_dict()
        assert "llm_apis" in d
        assert "database" in d
        assert "services" in d
        assert "network" in d
        assert "openai" in d["llm_apis"]

    def test_write_entrypoint_creates_file(self, tmp_path, monkeypatch):
        """_write_entrypoint writes a valid JSON file under runtime/."""
        import json

        from launcher import bootstrap as bs_mod

        # Redirect PROJECT_ROOT to tmp_path so no real file is written
        monkeypatch.setattr(bs_mod, "PROJECT_ROOT", tmp_path)
        bs_mod._write_entrypoint("0.0.0.0", 9999)
        ep = tmp_path / "runtime" / "entrypoint.json"
        assert ep.exists()
        data = json.loads(ep.read_text())
        assert data["api_base"] == "http://localhost:9999"
        assert "written_at" in data

    def test_write_entrypoint_custom_host(self, tmp_path, monkeypatch):
        import json

        from launcher import bootstrap as bs_mod

        monkeypatch.setattr(bs_mod, "PROJECT_ROOT", tmp_path)
        bs_mod._write_entrypoint("192.168.1.50", 8080)
        data = json.loads((tmp_path / "runtime" / "entrypoint.json").read_text())
        assert data["api_base"] == "http://192.168.1.50:8080"

    def test_print_status_callable(self):
        from launcher.bootstrap import print_status

        # Should not raise
        print_status("test message", "info")

    def test_print_section_callable(self):
        from launcher.bootstrap import print_section

        print_section("Test Section")


# =============================================================================
# launcher.service_manager
# =============================================================================


class TestServiceManager:
    """launcher.service_manager — ServiceInfo, ServiceManager."""

    def _make_manager(self):
        from launcher.bootstrap import SystemConfig
        from launcher.service_manager import ServiceManager

        return ServiceManager(SystemConfig())

    def test_initial_state(self):
        from launcher.bootstrap import SystemState

        mgr = self._make_manager()
        assert mgr.state == SystemState.INITIALIZING
        assert mgr.services == {}

    def test_register_service(self):
        from launcher.bootstrap import ServiceType

        mgr = self._make_manager()
        mgr.register_service("test_svc", ServiceType.CORE, port=9000)
        assert "test_svc" in mgr.services
        svc = mgr.services["test_svc"]
        assert svc.name == "test_svc"
        assert svc.port == 9000
        assert svc.status == "stopped"

    def test_get_status_empty(self):
        mgr = self._make_manager()
        assert mgr.get_status() == {}

    def test_get_status_after_register(self):
        from launcher.bootstrap import ServiceType

        mgr = self._make_manager()
        mgr.register_service("svc_a", ServiceType.API, port=8001)
        status = mgr.get_status()
        assert "svc_a" in status
        assert status["svc_a"]["port"] == 8001
        assert status["svc_a"]["status"] == "stopped"
        assert status["svc_a"]["type"] == "api"

    def test_stop_unknown_service_returns_false(self):
        mgr = self._make_manager()
        assert mgr.stop_service("nonexistent") is False

    def test_stop_all_on_empty_manager(self):
        mgr = self._make_manager()
        mgr.stop_all()  # Should not raise


# =============================================================================
# launcher.core_services
# =============================================================================


class TestCoreServicesModule:
    def test_import(self):
        from launcher.core_services import CoreServiceLauncher  # noqa: F401

    def test_instantiation(self):
        from launcher.bootstrap import SystemConfig
        from launcher.core_services import CoreServiceLauncher
        from launcher.service_manager import ServiceManager

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = CoreServiceLauncher(mgr, cfg)
        assert launcher.config is cfg
        assert launcher.service_manager is mgr


# =============================================================================
# launcher.node_startup
# =============================================================================


class TestNodeStartupModule:
    def test_import(self):
        from launcher.node_startup import NodeSystemLauncher  # noqa: F401

    def test_instantiation(self):
        from launcher.bootstrap import SystemConfig
        from launcher.node_startup import NodeSystemLauncher
        from launcher.service_manager import ServiceManager

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = NodeSystemLauncher(mgr, cfg)
        assert launcher.config is cfg
        assert launcher.service_manager is mgr

    def test_get_all_nodes_returns_list(self):
        from launcher.bootstrap import SystemConfig
        from launcher.node_startup import NodeSystemLauncher
        from launcher.service_manager import ServiceManager

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = NodeSystemLauncher(mgr, cfg)
        nodes = launcher.get_all_nodes()
        assert isinstance(nodes, list)

    def test_get_core_nodes_returns_list(self):
        from launcher.bootstrap import SystemConfig
        from launcher.node_startup import NodeSystemLauncher
        from launcher.service_manager import ServiceManager

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = NodeSystemLauncher(mgr, cfg)
        core = launcher.get_core_nodes()
        assert isinstance(core, list)


# =============================================================================
# launcher.health_checks
# =============================================================================


class TestHealthChecksModule:
    def test_import(self):
        from launcher.health_checks import run_startup_health_check  # noqa: F401

    def test_is_coroutine_function(self):
        import inspect

        from launcher.health_checks import run_startup_health_check

        assert inspect.iscoroutinefunction(run_startup_health_check)


# =============================================================================
# launcher.shutdown
# =============================================================================


class TestShutdownModule:
    def test_import(self):
        from launcher.shutdown import async_shutdown  # noqa: F401

    def test_is_coroutine_function(self):
        import inspect

        from launcher.shutdown import async_shutdown

        assert inspect.iscoroutinefunction(async_shutdown)

    def test_shutdown_does_not_raise_without_running_services(self):
        """async_shutdown should swallow ImportError/ConnectionError gracefully."""
        from launcher.shutdown import async_shutdown

        asyncio.run(async_shutdown())  # Should not raise


# =============================================================================
# launcher.__init__ (package re-exports)
# =============================================================================


class TestLauncherPackageExports:
    def test_all_public_symbols_present(self):
        import launcher

        expected = [
            # 融合(域7):HARD_DEPRECATED 的 ConfigManager/DependencyResolver 不再
            # 由包导入期再导出(每次启动触发 DeprecationWarning;无生产 importer)。
            "PROJECT_ROOT",
            "SystemState",
            "ServiceType",
            "SystemConfig",
            "_write_entrypoint",
            "print_status",
            "print_section",
            "ServiceInfo",
            "ServiceManager",
            "CoreServiceLauncher",
            "NodeSystemLauncher",
            "run_startup_health_check",
            "async_shutdown",
        ]
        for sym in expected:
            assert hasattr(launcher, sym), f"launcher.{sym} not found"

    def test_system_state_via_package(self):
        from launcher import SystemState

        assert SystemState.RUNNING.name == "RUNNING"

    def test_service_type_via_package(self):
        from launcher import ServiceType

        assert ServiceType.NODE.value == "node"


# =============================================================================
# unified_launcher.py backward compatibility
# =============================================================================


class TestUnifiedLauncherFacade:
    """服务编排的公开 API 必须完整 —— 检查对象从 unified_launcher.py 换成 launcher/services.py。

    unified_launcher.py 已在启动器统一的最后一步删除；它当初只是这些 API 的宿主文件。
    这条测试要保证的"公开面没缩水"完全没变，只是指向了新家。
    """

    def test_import(self):
        import launcher.services  # noqa: F401

    def test_cli_entry_is_main_py_not_a_second_main(self):
        """CLI 只有一个 —— ``main.py``。

        这条原本断言 ``launcher.services.main`` 可调用。那个 ``main()`` 是
        ``unified_launcher.py`` 的 CLI 外壳，它连同本体一起删了：留着就等于
        统一完还剩两个 CLI，正是这次要消掉的东西。

        它真正有效的三个开关已经收编进 ``main.py``（``--status`` /
        ``--check-only`` / ``--docker-full``），实现仍在 ``launcher/services.py``，
        所以这里改成钉住"实现还在、且第二个 CLI 没有复活"。
        """
        import launcher.services as svc

        assert hasattr(svc.GalaxyUnified, "show_status")
        assert callable(svc._run_check_only)
        assert not hasattr(svc, "main"), "launcher/services.py 不该再有自己的 CLI 入口"

    def test_galaxy_unified_class(self):
        from launcher.services import GalaxyUnified

        assert isinstance(GalaxyUnified, type)

    def test_system_state_importable(self):
        from launcher.services import SystemState

        assert SystemState.RUNNING.name == "RUNNING"

    def test_service_type_importable(self):
        from launcher.services import ServiceType

        assert ServiceType.CORE.value == "core"

    def test_system_config_importable(self):
        from launcher.services import SystemConfig

        cfg = SystemConfig()
        assert hasattr(cfg, "web_ui_port")

    def test_service_manager_importable(self):
        from launcher.services import ServiceManager, SystemConfig

        mgr = ServiceManager(SystemConfig())
        assert mgr is not None

    def test_core_service_launcher_importable(self):
        from launcher.services import CoreServiceLauncher, ServiceManager, SystemConfig

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        csl = CoreServiceLauncher(mgr, cfg)
        assert csl is not None

    def test_node_system_launcher_importable(self):
        from launcher.services import NodeSystemLauncher, ServiceManager, SystemConfig

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        nsl = NodeSystemLauncher(mgr, cfg)
        assert nsl is not None

    def test_l4_launcher_importable(self):
        from launcher.services import L4EnhancementLauncher, ServiceManager, SystemConfig

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        l4 = L4EnhancementLauncher(mgr, cfg)
        assert l4 is not None

    def test_unified_web_ui_importable(self):
        from launcher.services import ServiceManager, SystemConfig, UnifiedWebUI

        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        wui = UnifiedWebUI(mgr, cfg)
        assert wui is not None


# =============================================================================
# main.py — authoritative startup entry
# =============================================================================


class TestAuthoritativeEntryPoint:
    """main.py 是唯一入口 —— 启动器统一之后，它不再委派给任何"下级启动器本体"。"""

    def test_main_py_exists(self):
        assert (PROJECT_ROOT / "main.py").exists()

    def test_main_py_imports_successfully(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("main_entry", str(PROJECT_ROOT / "main.py"))
        mod = importlib.util.module_from_spec(spec)
        # Loading the module should not raise
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "main", None))

    def test_backend_flag_actually_skips_the_desktop_shell(self):
        """``--backend`` 不是空承诺：``GALAXY_SKIP_ELECTRON=1`` 真的会挡住桌面壳。

        ``flags.py`` 把 ``galaxy_skip_electron`` 登记为 ``status="stable"``、
        purpose 写着 "skip starting the Electron three-state GUI" —— 但接线之前
        **全仓零个读取点**，设了它没有任何效果。删 ``launch_desktop.py`` 时
        ``--backend``（只起网关、不拉壳）需要一个等价新命令，正好把这个本来就该
        生效的开关接上，而不是为它另造一套判断。

        闸设在 ``start_desktop_shell()`` —— 全仓唯一的桌面壳入口，
        ``start_tauri`` / ``start_electron`` 都只从这里进。
        """
        import asyncio

        from launcher.services import GalaxyUnified

        lumiv = GalaxyUnified()
        called = []

        async def _boom():  # pragma: no cover - 被调用即失败
            called.append("tauri")
            return True

        lumiv.start_tauri = _boom
        lumiv.start_electron = _boom

        prev = os.environ.get("GALAXY_SKIP_ELECTRON")
        os.environ["GALAXY_SKIP_ELECTRON"] = "1"
        try:
            assert asyncio.run(lumiv.start_desktop_shell()) is False
            assert not called, "GALAXY_SKIP_ELECTRON=1 时不该碰任何一种桌面壳"
        finally:
            if prev is None:
                os.environ.pop("GALAXY_SKIP_ELECTRON", None)
            else:
                os.environ["GALAXY_SKIP_ELECTRON"] = prev

    def test_the_three_effective_flags_survived_the_deletion(self):
        """``--status`` / ``--check-only`` / ``--docker-full`` 必须还在 main.py 上。

        它们是 ``unified_launcher.py`` 的 argparse 里**唯三真的有效**的开关，
        实现（``show_status`` / ``_run_check_only`` / compose 调用）没有第二份。
        删本体时如果只删不搬，用户敲下去只会得到 ``unrecognized arguments``，
        而"少了个开关"不会让任何别的测试变红 —— 所以在这里钉住。
        """
        import ast

        tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
        flags = {
            arg.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        }
        for flag in ("--status", "--check-only", "--docker-full"):
            assert flag in flags, f"{flag} 随 unified_launcher.py 一起丢了"

    def test_the_four_inert_flags_were_deliberately_not_carried_over(self):
        """``--minimal`` / ``--no-ui`` / ``--no-l4`` / ``--no-nodes`` **不该**在 main.py 上。

        它们在旧启动器里只写进 ``SystemConfig`` 的字段，而 ``GalaxyUnified.start()``
        一个都不读 —— 也就是从来没真的关掉过任何东西。照搬过来等于把
        "我关了 UI 却还是起来了"这种假承诺一起搬家。哪天真把它们接上了，
        这条测试会红，那时删掉它并说明接线在哪 —— 这正是它存在的意义。
        """
        import ast

        tree = ast.parse((PROJECT_ROOT / "main.py").read_text(encoding="utf-8"))
        flags = {
            arg.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add_argument"
            for arg in node.args
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        }
        for flag in ("--minimal", "--no-ui", "--no-l4", "--no-nodes"):
            assert flag not in flags, f"{flag} 只有在真的接上 start() 之后才该出现"

    def test_the_four_retired_launcher_bodies_are_gone(self):
        """四个启动器本体已随统一删除（docs/LAUNCHER_UNIFICATION_PLAN.md 第 8 步）。

        这条原本是 ``test_unified_launcher_py_exists``（断言它**存在**）。要素没有
        丢：编排搬到 ``launcher/services.py``、节点生命周期搬到 ``launcher/nodes.py``、
        桌面壳自愈搬到 ``launcher/shell.py``、依赖安装搬到 ``launcher/deps.py``。
        逐条对照见 ``launcher/doctor.py`` 的 PRESERVED_ELEMENTS。
        """
        for name in ("unified_launcher.py", "launch_desktop.py", "system_manager.py", "install.py"):
            assert not (PROJECT_ROOT / name).exists(), f"{name} 应已删除，改用 python main.py"

    def test_start_galaxy_not_present(self):
        """start_galaxy.py has been removed — only main.py is valid."""
        assert not (PROJECT_ROOT / "start_galaxy.py").exists(), "start_galaxy.py must not exist; use main.py instead"

    def test_start_l4_not_present(self):
        """start_l4.py has been removed — only main.py is valid."""
        assert not (PROJECT_ROOT / "start_l4.py").exists(), "start_l4.py must not exist; use main.py instead"
