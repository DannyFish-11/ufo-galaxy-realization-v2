"""
tests/test_pr_windows_legacy_retirement.py
==========================================

Tests that verify the Windows legacy client stack has been properly retired
from the active runtime surface.

PR: Remove legacy Windows client stack / retire-windows-legacy-client-stack

Test groups
-----------
  A) Hard-disabled stubs: verify legacy modules raise RuntimeError on import
     and emit DeprecationWarning.
  B) Active Windows direction: verify status_board_v2 and windows_aip_client
     remain importable (not hard-disabled).
  C) __init__.py: verify active direction is documented.
  D) _legacy directory: verify legacy assets have been moved there.
  E) Legacy launchers: verify they are no longer present in the active path.
  F) enhancements run_ui: verify it is hard-disabled.
"""

from __future__ import annotations

import importlib
import pathlib
import sys
import warnings

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_WC = _ROOT / "windows_client"


# ===========================================================================
# Helpers
# ===========================================================================


def _reload_capture_warnings(module_name: str):
    """Force-reload a module and capture DeprecationWarnings."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        try:
            importlib.import_module(module_name)
        except Exception:
            pass
    return [x for x in w if issubclass(x.category, DeprecationWarning)]


def _import_raises_runtime_error(module_name: str) -> bool:
    """Return True if importing the module raises RuntimeError."""
    if module_name in sys.modules:
        del sys.modules[module_name]
    try:
        importlib.import_module(module_name)
        return False
    except RuntimeError:
        return True
    except Exception:
        # Other errors (ImportError for missing deps) are not RuntimeError
        return False


# ===========================================================================
# A) Hard-disabled stubs
# ===========================================================================


class TestHardDisabledLegacyModules:
    """Legacy modules must raise RuntimeError on import (hard-disabled stubs)."""

    @pytest.mark.parametrize("module_name", [
        "windows_client.client",
        "windows_client.ui_sidebar",
        "windows_client.desktop_automation",
        "windows_client.windows_mcp_server",
        "windows_client.main",
        "windows_client.windows_client_integrated",
        "windows_client.key_listener",
    ])
    def test_module_raises_runtime_error(self, module_name):
        assert _import_raises_runtime_error(module_name), (
            f"{module_name} must raise RuntimeError on import (hard-disabled stub)"
        )

    @pytest.mark.parametrize("module_name", [
        "windows_client.client",
        "windows_client.ui_sidebar",
        "windows_client.desktop_automation",
        "windows_client.windows_mcp_server",
        "windows_client.main",
        "windows_client.windows_client_integrated",
        "windows_client.key_listener",
    ])
    def test_module_emits_deprecation_warning(self, module_name):
        warns = _reload_capture_warnings(module_name)
        assert len(warns) >= 1, (
            f"{module_name} must emit DeprecationWarning before raising RuntimeError"
        )

    def test_main_stub_references_active_direction(self):
        """windows_client/main.py stub must mention the active Windows direction."""
        content = (_WC / "main.py").read_text()
        assert "DesktopPresenceRuntime" in content or "status_board_v2" in content, (
            "main.py stub must reference the active Windows direction"
        )

    def test_main_stub_mentions_tristate(self):
        """windows_client/main.py stub must mention tri-state."""
        content = (_WC / "main.py").read_text()
        assert "tri-state" in content.lower() or "tristate" in content.lower() or "silent" in content.lower()

    def test_integrated_stub_references_active_direction(self):
        """windows_client_integrated.py stub must mention the active direction."""
        content = (_WC / "windows_client_integrated.py").read_text()
        assert "DesktopPresenceRuntime" in content or "status_board_v2" in content

    def test_key_listener_stub_is_minimal(self):
        """key_listener.py must be a stub (not the old keyboard listener)."""
        content = (_WC / "key_listener.py").read_text()
        # Must NOT contain the active F12 keyboard listener code
        assert "keyboard.add_hotkey" not in content
        assert "keyboard.wait" not in content


# ===========================================================================
# B) Active Windows direction modules remain importable
# ===========================================================================


class TestActiveWindowsDirectionModules:
    """Active Windows direction modules must not be hard-disabled."""

    def test_status_board_v2_importable(self):
        """windows_client.status_board_v2 must be importable (active surface)."""
        try:
            import windows_client.status_board_v2 as sb
            assert sb is not None
        except ImportError as e:
            pytest.skip(f"status_board_v2 has optional deps: {e}")

    def test_windows_aip_client_importable(self):
        """windows_client.windows_aip_client must be importable (active ingress)."""
        try:
            import windows_client.windows_aip_client as aip
            assert aip is not None
        except ImportError as e:
            pytest.skip(f"windows_aip_client has optional deps: {e}")

    def test_autonomy_package_importable(self):
        """windows_client.autonomy must be importable (active execution layer)."""
        try:
            import windows_client.autonomy as aut
            assert aut is not None
        except ImportError as e:
            pytest.skip(f"autonomy package has optional deps: {e}")

    def test_status_board_v2_does_not_raise_runtime_error(self):
        """status_board_v2 must NOT raise RuntimeError on import."""
        assert not _import_raises_runtime_error("windows_client.status_board_v2"), (
            "status_board_v2 is the active desktop status surface and must not be disabled"
        )


# ===========================================================================
# C) __init__.py documents the active direction
# ===========================================================================


class TestWindowsClientInitDocumentsActiveDirection:
    def test_init_mentions_host_specific_legacy_shell(self):
        """__init__.py must retain the HOST-SPECIFIC LEGACY SHELL marker (PR-8 compat)."""
        content = (_WC / "__init__.py").read_text()
        assert "HOST-SPECIFIC LEGACY SHELL" in content

    def test_init_mentions_desktop_presence_runtime(self):
        """__init__.py must mention DesktopPresenceRuntime as active direction."""
        content = (_WC / "__init__.py").read_text()
        assert "DesktopPresenceRuntime" in content

    def test_init_mentions_status_board_v2(self):
        """__init__.py must name status_board_v2 as the canonical status surface."""
        content = (_WC / "__init__.py").read_text()
        assert "status_board_v2" in content

    def test_init_mentions_tristate(self):
        """__init__.py must reference the tri-state lifecycle model."""
        content = (_WC / "__init__.py").read_text()
        assert "tri-state" in content.lower() or "silent" in content.lower()

    def test_init_mentions_legacy_retirement(self):
        """__init__.py must acknowledge retired legacy surfaces."""
        content = (_WC / "__init__.py").read_text()
        assert "retired" in content.lower() or "hard-disabled" in content.lower()


# ===========================================================================
# D) _legacy directory contains moved assets
# ===========================================================================


class TestLegacyDirectoryContainsMoved:
    """Legacy assets should have been moved to windows_client/_legacy/."""

    _LEGACY = _WC / "_legacy"

    def test_legacy_dir_exists(self):
        assert self._LEGACY.is_dir(), "windows_client/_legacy/ directory must exist"

    def test_start_client_bat_in_legacy(self):
        assert (self._LEGACY / "START_CLIENT.bat").exists(), (
            "START_CLIENT.bat must be in _legacy/ (retired launcher)"
        )

    def test_start_galaxy_client_bat_in_legacy(self):
        assert (self._LEGACY / "start_galaxy_client.bat").exists(), (
            "start_galaxy_client.bat must be in _legacy/ (retired launcher)"
        )

    def test_ui_dir_in_legacy(self):
        assert (self._LEGACY / "ui").is_dir(), (
            "windows_client/ui/ (legacy chat UI) must be moved to _legacy/"
        )

    def test_legacy_init_exists(self):
        assert (self._LEGACY / "__init__.py").exists(), (
            "_legacy/__init__.py must exist to mark the archive package"
        )

    def test_start_client_bat_no_longer_in_active_root(self):
        """START_CLIENT.bat must NOT appear in the active windows_client/ root."""
        assert not (_WC / "START_CLIENT.bat").exists(), (
            "START_CLIENT.bat must be moved to _legacy/, not in active root"
        )

    def test_start_galaxy_client_bat_no_longer_in_active_root(self):
        """start_galaxy_client.bat must NOT appear in the active windows_client/ root."""
        assert not (_WC / "start_galaxy_client.bat").exists(), (
            "start_galaxy_client.bat must be moved to _legacy/, not in active root"
        )

    def test_ui_dir_no_longer_in_active_root(self):
        """windows_client/ui/ must NOT appear in the active root."""
        assert not (_WC / "ui").is_dir(), (
            "windows_client/ui/ must be moved to _legacy/"
        )


# ===========================================================================
# E) Hard-disabled stubs reference WINDOWS_EXECUTION_PIPELINE doc
# ===========================================================================


class TestStubsReferenceDocumentation:
    @pytest.mark.parametrize("filename", [
        "client.py",
        "ui_sidebar.py",
        "desktop_automation.py",
        "windows_mcp_server.py",
        "main.py",
        "windows_client_integrated.py",
        "key_listener.py",
    ])
    def test_stub_mentions_pipeline_doc(self, filename):
        """Each hard-disabled stub must reference the pipeline docs or active direction."""
        content = (_WC / filename).read_text()
        has_doc_ref = (
            "WINDOWS_EXECUTION_PIPELINE" in content
            or "DesktopPresenceRuntime" in content
            or "status_board_v2" in content
        )
        assert has_doc_ref, (
            f"{filename} stub must reference WINDOWS_EXECUTION_PIPELINE.md "
            f"or the active Windows direction"
        )


# ===========================================================================
# F) enhancements run_ui is hard-disabled
# ===========================================================================


class TestEnhancementsRunUiHardDisabled:
    _RUN_UI = _ROOT / "enhancements" / "clients" / "windows_client" / "run_ui.py"

    def test_run_ui_file_exists(self):
        assert self._RUN_UI.exists(), "run_ui.py must still exist as a hard-disabled stub"

    def test_run_ui_raises_runtime_error(self):
        assert _import_raises_runtime_error(
            "enhancements.clients.windows_client.run_ui"
        ), "run_ui.py must raise RuntimeError (hard-disabled)"

    def test_run_ui_no_longer_calls_windows_client_main(self):
        """run_ui.py must not call windows_client.main (which is retired)."""
        content = self._RUN_UI.read_text()
        assert "from windows_client.main import" not in content
        assert "windows_client.main" not in content or "retired" in content.lower()

    def test_run_ui_mentions_active_direction(self):
        """run_ui.py stub must mention the active Windows direction."""
        content = self._RUN_UI.read_text()
        assert (
            "DesktopPresenceRuntime" in content
            or "status_board_v2" in content
            or "unified_launcher" in content
        )
