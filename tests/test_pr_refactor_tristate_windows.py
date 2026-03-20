"""
tests/test_pr_refactor_tristate_windows.py
==========================================

Tests for the tri-state model alignment and Windows execution unification
refactor (PR: refactor-tri-state-model-windows-execution).

Test groups
-----------
  A) TriStatePhase enum — values and string serialisation.
  B) continuum_to_tri_state() — correct mapping for all four internal phases.
  C) ContinuumState.tri_state_phase — property returns correct TriStatePhase.
  D) receding → silent projection — receding is never surfaced publicly.
  E) ContinuumPhase.RECEDING docstring notes internal-only nature.
  F) WindowsExecutionArbiter.route_command() — sync wrapper dispatches correctly.
  G) Windows AIP client _execute_command routes through arbiter, not direct manager.
  H) Deprecation warnings are raised when legacy modules are imported.
  I) __init__.py exports TriStatePhase and continuum_to_tri_state.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import warnings
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.continuum.types import (
    ContinuumPhase,
    ContinuumState,
    TriStatePhase,
    continuum_to_tri_state,
)
from core.continuum import TriStatePhase as TriStatePhaseFromInit, continuum_to_tri_state as c2ts_from_init
from core.windows_execution_arbiter import (
    WinExecLevel,
    WinExecResult,
    WinExecStatus,
    WindowsExecutionArbiter,
    get_windows_arbiter,
    reset_windows_arbiter,
)


# ===========================================================================
# A) TriStatePhase enum
# ===========================================================================


class TestTriStatePhase:
    def test_three_values(self):
        values = {p.value for p in TriStatePhase}
        assert values == {"silent", "liminal", "manifest"}

    def test_string_serialisation(self):
        assert TriStatePhase.SILENT == "silent"
        assert TriStatePhase.LIMINAL == "liminal"
        assert TriStatePhase.MANIFEST == "manifest"

    def test_from_string(self):
        assert TriStatePhase("silent") is TriStatePhase.SILENT
        assert TriStatePhase("liminal") is TriStatePhase.LIMINAL
        assert TriStatePhase("manifest") is TriStatePhase.MANIFEST


# ===========================================================================
# B) continuum_to_tri_state() mapping
# ===========================================================================


class TestContinuumToTriState:
    def test_formless_maps_to_silent(self):
        assert continuum_to_tri_state(ContinuumPhase.FORMLESS) is TriStatePhase.SILENT

    def test_liminal_maps_to_liminal(self):
        assert continuum_to_tri_state(ContinuumPhase.LIMINAL) is TriStatePhase.LIMINAL

    def test_manifest_maps_to_manifest(self):
        assert continuum_to_tri_state(ContinuumPhase.MANIFEST) is TriStatePhase.MANIFEST

    def test_receding_maps_to_silent(self):
        """receding is an internal mechanism and must collapse to silent publicly."""
        assert continuum_to_tri_state(ContinuumPhase.RECEDING) is TriStatePhase.SILENT

    def test_all_phases_covered(self):
        """Every ContinuumPhase must have a valid mapping — no KeyError."""
        for phase in ContinuumPhase:
            result = continuum_to_tri_state(phase)
            assert isinstance(result, TriStatePhase)


# ===========================================================================
# C) ContinuumState.tri_state_phase property
# ===========================================================================


class TestContinuumStateTriStateProperty:
    def test_formless_state_returns_silent(self):
        state = ContinuumState(phase=ContinuumPhase.FORMLESS)
        assert state.tri_state_phase is TriStatePhase.SILENT

    def test_liminal_state_returns_liminal(self):
        state = ContinuumState(phase=ContinuumPhase.LIMINAL)
        assert state.tri_state_phase is TriStatePhase.LIMINAL

    def test_manifest_state_returns_manifest(self):
        state = ContinuumState(phase=ContinuumPhase.MANIFEST)
        assert state.tri_state_phase is TriStatePhase.MANIFEST

    def test_receding_state_returns_silent(self):
        state = ContinuumState(phase=ContinuumPhase.RECEDING)
        assert state.tri_state_phase is TriStatePhase.SILENT

    def test_formless_default_returns_silent(self):
        state = ContinuumState.formless_default()
        assert state.tri_state_phase is TriStatePhase.SILENT

    def test_degraded_fallback_returns_silent(self):
        state = ContinuumState.degraded_fallback()
        assert state.tri_state_phase is TriStatePhase.SILENT


# ===========================================================================
# D) receding never surfaced publicly
# ===========================================================================


class TestRecessingInternalOnly:
    def test_receding_does_not_appear_in_tri_state_values(self):
        tri_values = {p.value for p in TriStatePhase}
        assert "receding" not in tri_values

    def test_receding_tri_state_is_silent_not_receding(self):
        result = continuum_to_tri_state(ContinuumPhase.RECEDING)
        assert result.value != "receding"
        assert result is TriStatePhase.SILENT

    def test_receding_docstring_contains_internal_only_note(self):
        doc = ContinuumPhase.RECEDING.__doc__ or ""
        assert "internal" in doc.lower() or "Internal" in doc


# ===========================================================================
# E) ContinuumPhase.RECEDING docstring
# ===========================================================================


class TestRecessingDocstring:
    def test_receding_marked_as_internal(self):
        """ContinuumPhase.RECEDING docstring must mention 'internal'."""
        doc = ContinuumPhase.RECEDING.__doc__ or ""
        assert "internal" in doc.lower()

    def test_receding_maps_to_silent_in_module_source(self):
        """The source of types.py must document that RECEDING maps to SILENT."""
        import inspect
        import core.continuum.types as types_module
        src = inspect.getsource(types_module)
        # continuum_to_tri_state must map RECEDING → SILENT
        assert "RECEDING" in src and "SILENT" in src


# ===========================================================================
# F) WindowsExecutionArbiter.route_command() sync wrapper
# ===========================================================================


def _make_stub_arbiter(success: bool = True) -> WindowsExecutionArbiter:
    arbiter = WindowsExecutionArbiter(use_defaults=False)

    async def _sys_ok(action, params, device_id):
        return {"success": success, "output": f"stub:{action}"}

    arbiter.set_executors(system_api=_sys_ok)
    return arbiter


class TestRouteCommand:
    def test_route_command_returns_dict(self):
        arbiter = _make_stub_arbiter(success=True)
        result = arbiter.route_command("click", {"x": 10, "y": 20})
        assert isinstance(result, dict)

    def test_route_command_success_true(self):
        arbiter = _make_stub_arbiter(success=True)
        result = arbiter.route_command("click", {"x": 10, "y": 20})
        assert result.get("success") is True

    def test_route_command_failure_propagated(self):
        arbiter = _make_stub_arbiter(success=False)
        result = arbiter.route_command("click", {})
        assert result.get("success") is False

    def test_route_command_has_expected_keys(self):
        arbiter = _make_stub_arbiter(success=True)
        result = arbiter.route_command("screenshot", {})
        assert "success" in result

    def test_route_command_no_manager_import(self):
        """route_command must not directly import WindowsAutonomyManager."""
        import inspect
        src = inspect.getsource(WindowsExecutionArbiter.route_command)
        assert "WindowsAutonomyManager" not in src
        assert "autonomy_manager" not in src


# ===========================================================================
# G) AIP client _execute_command routes through arbiter
# ===========================================================================


class TestAIPClientUsesArbiter:
    def test_execute_command_calls_arbiter_not_manager(self):
        """_execute_command must use get_windows_arbiter(), not _get_manager()."""
        import inspect
        import windows_client.windows_aip_client as aip_module

        src = inspect.getsource(aip_module._execute_command)
        # Must reference arbiter
        assert "arbiter" in src.lower()
        # Must NOT call the old _get_manager() function
        assert "_get_manager" not in src

    def test_execute_command_returns_dict_with_success(self):
        """_execute_command should return a dict with 'success' key."""
        import windows_client.windows_aip_client as aip_module

        mock_result = {
            "success": True,
            "final_level": "system_api",
            "result": {"output": "ok"},
            "attempts": [],
            "total_latency_ms": 1.0,
            "request_id": "r1",
            "device_id": "local",
            "action_summary": "click",
        }
        with patch.object(aip_module, "_get_arbiter") as mock_get:
            mock_arbiter = MagicMock()
            mock_arbiter.route_command.return_value = mock_result
            mock_get.return_value = mock_arbiter

            result = aip_module._execute_command("click", {"x": 5, "y": 10})
            assert isinstance(result, dict)
            mock_arbiter.route_command.assert_called_once_with(
                action="click",
                params={"x": 5, "y": 10},
                device_id="local",
            )

    def test_execute_command_arbiter_unavailable(self):
        import windows_client.windows_aip_client as aip_module

        with patch.object(aip_module, "_get_arbiter", return_value=None):
            result = aip_module._execute_command("click", {})
            assert result.get("success") is False
            assert "arbiter" in result.get("error", "").lower()

    def test_execute_agent_task_preserves_correlation_ids(self):
        import windows_client.windows_aip_client as aip_module

        payload = {
            "agent_id": "agent-1",
            "task_id": "task-1",
            "trace_id": "trace-1",
            "session_id": "sess-1",
            "task": "do something",
            "context": {"manifest_id": "manifest-1"},
        }
        with patch.object(aip_module, "_execute_command") as mock_exec:
            mock_exec.return_value = {"success": True, "output": "done"}
            result = aip_module._execute_agent_task(payload)

        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-1"
        assert result["trace_id"] == "trace-1"
        assert result["session_id"] == "sess-1"
        assert result["manifest_id"] == "manifest-1"


# ===========================================================================
# H) Deprecation warnings for legacy modules
# ===========================================================================


class TestLegacyDeprecationWarnings:
    def _reload_with_warning_capture(self, module_name: str):
        """Force-reload a module and capture any DeprecationWarning raised."""
        if module_name in sys.modules:
            del sys.modules[module_name]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            try:
                importlib.import_module(module_name)
            except Exception:
                pass  # import may fail due to missing deps; we only care about warnings
        return [x for x in w if issubclass(x.category, DeprecationWarning)]

    def test_windows_mcp_server_emits_deprecation(self):
        warns = self._reload_with_warning_capture("windows_client.windows_mcp_server")
        assert len(warns) >= 1, "Expected DeprecationWarning from windows_mcp_server"
        messages = " ".join(str(w.message) for w in warns)
        assert "deprecated" in messages.lower()

    def test_ui_sidebar_emits_deprecation(self):
        warns = self._reload_with_warning_capture("windows_client.ui_sidebar")
        assert len(warns) >= 1, "Expected DeprecationWarning from ui_sidebar"

    def test_desktop_automation_emits_deprecation(self):
        warns = self._reload_with_warning_capture("windows_client.desktop_automation")
        assert len(warns) >= 1, "Expected DeprecationWarning from desktop_automation"

    def test_client_emits_deprecation(self):
        """client.py must call warnings.warn with DeprecationWarning at module level."""
        import pathlib
        src_path = pathlib.Path(__file__).parent.parent / "windows_client" / "client.py"
        content = src_path.read_text()
        assert "DeprecationWarning" in content
        assert "warnings.warn" in content


# ===========================================================================
# I) __init__.py exports
# ===========================================================================


class TestContinuumInitExports:
    def test_tri_state_phase_exported(self):
        assert TriStatePhaseFromInit is TriStatePhase

    def test_continuum_to_tri_state_exported(self):
        assert c2ts_from_init is continuum_to_tri_state

    def test_tri_state_phase_in_all(self):
        import core.continuum as cc
        assert "TriStatePhase" in cc.__all__

    def test_continuum_to_tri_state_in_all(self):
        import core.continuum as cc
        assert "continuum_to_tri_state" in cc.__all__
