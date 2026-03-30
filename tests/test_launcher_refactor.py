"""
Tests for the refactored launcher sub-modules.

Validates that:
- launcher.bootstrap exports the expected types and functions
- launcher.service_manager provides correct lifecycle semantics
- launcher.core_services, node_startup, health_checks, shutdown are importable
- launcher.__init__ re-exports all public symbols
- unified_launcher.py remains importable and exposes its public API
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
            "INITIALIZING", "LOADING_CONFIG", "STARTING_CORE",
            "STARTING_NODES", "STARTING_L4", "STARTING_UI",
            "RUNNING", "STOPPING", "STOPPED", "ERROR",
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
        from launcher.service_manager import ServiceManager
        from launcher.core_services import CoreServiceLauncher
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
        from launcher.service_manager import ServiceManager
        from launcher.node_startup import NodeSystemLauncher
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = NodeSystemLauncher(mgr, cfg)
        assert launcher.config is cfg
        assert launcher.service_manager is mgr

    def test_get_all_nodes_returns_list(self):
        from launcher.bootstrap import SystemConfig
        from launcher.service_manager import ServiceManager
        from launcher.node_startup import NodeSystemLauncher
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        launcher = NodeSystemLauncher(mgr, cfg)
        nodes = launcher.get_all_nodes()
        assert isinstance(nodes, list)

    def test_get_core_nodes_returns_list(self):
        from launcher.bootstrap import SystemConfig
        from launcher.service_manager import ServiceManager
        from launcher.node_startup import NodeSystemLauncher
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
            "ConfigManager", "DependencyResolver",
            "PROJECT_ROOT",
            "SystemState", "ServiceType", "SystemConfig", "_write_entrypoint",
            "print_status", "print_section",
            "ServiceInfo", "ServiceManager",
            "CoreServiceLauncher", "NodeSystemLauncher",
            "run_startup_health_check", "async_shutdown",
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
    """unified_launcher.py must remain importable with its full public API intact."""

    def test_import(self):
        import unified_launcher  # noqa: F401

    def test_main_callable(self):
        from unified_launcher import main
        assert callable(main)

    def test_galaxy_unified_class(self):
        from unified_launcher import GalaxyUnified
        assert isinstance(GalaxyUnified, type)

    def test_system_state_importable(self):
        from unified_launcher import SystemState
        assert SystemState.RUNNING.name == "RUNNING"

    def test_service_type_importable(self):
        from unified_launcher import ServiceType
        assert ServiceType.CORE.value == "core"

    def test_system_config_importable(self):
        from unified_launcher import SystemConfig
        cfg = SystemConfig()
        assert hasattr(cfg, "web_ui_port")

    def test_service_manager_importable(self):
        from unified_launcher import ServiceManager, SystemConfig
        mgr = ServiceManager(SystemConfig())
        assert mgr is not None

    def test_core_service_launcher_importable(self):
        from unified_launcher import CoreServiceLauncher, ServiceManager, SystemConfig
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        csl = CoreServiceLauncher(mgr, cfg)
        assert csl is not None

    def test_node_system_launcher_importable(self):
        from unified_launcher import NodeSystemLauncher, ServiceManager, SystemConfig
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        nsl = NodeSystemLauncher(mgr, cfg)
        assert nsl is not None

    def test_l4_launcher_importable(self):
        from unified_launcher import L4EnhancementLauncher, ServiceManager, SystemConfig
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        l4 = L4EnhancementLauncher(mgr, cfg)
        assert l4 is not None

    def test_unified_web_ui_importable(self):
        from unified_launcher import UnifiedWebUI, ServiceManager, SystemConfig
        cfg = SystemConfig()
        mgr = ServiceManager(cfg)
        wui = UnifiedWebUI(mgr, cfg)
        assert wui is not None


# =============================================================================
# main.py — authoritative startup entry
# =============================================================================

class TestAuthoritativeEntryPoint:
    """main.py must delegate to unified_launcher.main without error."""

    def test_main_py_exists(self):
        assert (PROJECT_ROOT / "main.py").exists()

    def test_main_py_imports_successfully(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_entry", str(PROJECT_ROOT / "main.py")
        )
        mod = importlib.util.module_from_spec(spec)
        # Loading the module should not raise
        spec.loader.exec_module(mod)
        assert callable(getattr(mod, "main", None))

    def test_unified_launcher_py_exists(self):
        assert (PROJECT_ROOT / "unified_launcher.py").exists()

    def test_start_galaxy_not_present(self):
        """start_galaxy.py has been removed — only main.py / unified_launcher.py are valid."""
        assert not (PROJECT_ROOT / "start_galaxy.py").exists(), (
            "start_galaxy.py must not exist; use main.py or unified_launcher.py instead"
        )

    def test_start_l4_not_present(self):
        """start_l4.py has been removed — only main.py / unified_launcher.py are valid."""
        assert not (PROJECT_ROOT / "start_l4.py").exists(), (
            "start_l4.py must not exist; use main.py or unified_launcher.py instead"
        )
