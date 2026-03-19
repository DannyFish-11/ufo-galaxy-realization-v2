"""
tests/test_constellation_entry_default.py
==========================================

PR-6 Goal 1: Tests demonstrate ConstellationRuntime is the default entry path.

Covers:
  A) GalaxyOrchestrator.process_request() defaults use_constellation=True
  B) process_user_input() (e2e_orchestrator) defaults use_constellation=True
  C) get_constellation_runtime() returns a ConstellationRuntime singleton
  D) ConstellationRuntime.run() is actually invoked on the default path
  E) Explicit use_constellation=False still works (backward-compat)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Shared mock return values
# ---------------------------------------------------------------------------

_CR_RESPONSE: Dict[str, Any] = {
    "success": True,
    "reply": "handled by ConstellationRuntime",
    "trace_id": "tr-entry-001",
    "session_id": "sess-entry-001",
    "mode": "dag",
    "data": {},
    "elapsed_ms": 5.0,
}


# ===========================================================================
# A) GalaxyOrchestrator defaults to ConstellationRuntime
# ===========================================================================

class TestGalaxyOrchestratorDefaultEntry:
    """GalaxyOrchestrator.process_request() must route via ConstellationRuntime by default."""

    @pytest.mark.asyncio
    async def test_default_context_uses_constellation(self):
        """No context → use_constellation defaults to True → CR is called."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_RESPONSE)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
            orch = GalaxyOrchestrator({})
            result = await orch.process_request("default entry test")

        mock_runtime.run.assert_called_once()
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_explicit_true_uses_constellation(self):
        """context={'use_constellation': True} → CR is called."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_RESPONSE)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
            orch = GalaxyOrchestrator({})
            result = await orch.process_request(
                "explicit true",
                context={"use_constellation": True},
            )

        mock_runtime.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_explicit_false_skips_constellation(self):
        """context={'use_constellation': False} → CR is NOT called."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_RESPONSE)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
            orch = GalaxyOrchestrator({})
            await orch.process_request(
                "explicit false",
                context={"use_constellation": False},
            )

        mock_runtime.run.assert_not_called()


# ===========================================================================
# B) process_user_input() defaults to ConstellationRuntime
# ===========================================================================

class TestE2EOrchestratorDefaultEntry:
    """process_user_input() must route via ConstellationRuntime by default."""

    @pytest.mark.asyncio
    async def test_default_uses_constellation(self):
        """Omitting use_constellation → True → CR is called."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_RESPONSE)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from core.e2e_orchestrator import process_user_input
            result = await process_user_input("default entry e2e")

        mock_runtime.run.assert_called_once()
        assert result["mode"] == "dag"

    @pytest.mark.asyncio
    async def test_explicit_false_skips_constellation(self):
        """use_constellation=False → CR is NOT called (fallback pipeline used)."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_RESPONSE)

        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value={
            "success": True, "reply": "pipeline", "session_id": "s1",
            "mode": "chat", "data": {}, "devices_notified": [],
        })

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ), patch("core.e2e_pipeline.get_pipeline", return_value=mock_pipeline):
            from core.e2e_orchestrator import process_user_input
            result = await process_user_input(
                "bypass cr", use_constellation=False
            )

        mock_runtime.run.assert_not_called()
        mock_pipeline.execute.assert_called_once()


# ===========================================================================
# C) get_constellation_runtime() returns a singleton ConstellationRuntime
# ===========================================================================

class TestConstellationRuntimeSingleton:
    """Singleton factory must return identical instances across calls."""

    def test_same_instance_returned_on_repeated_calls(self):
        from core.constellation_runtime import get_constellation_runtime, ConstellationRuntime
        import core.constellation_runtime as _mod

        _mod._runtime_instance = None
        try:
            r1 = get_constellation_runtime()
            r2 = get_constellation_runtime()
            assert r1 is r2
            assert isinstance(r1, ConstellationRuntime)
        finally:
            _mod._runtime_instance = None

    def test_singleton_type_is_constellation_runtime(self):
        from core.constellation_runtime import get_constellation_runtime, ConstellationRuntime
        import core.constellation_runtime as _mod

        _mod._runtime_instance = None
        try:
            runtime = get_constellation_runtime()
            assert isinstance(runtime, ConstellationRuntime)
        finally:
            _mod._runtime_instance = None


# ===========================================================================
# D) ConstellationRuntime.run() is actually invoked on the default path
# ===========================================================================

class TestConstellationRuntimeInvoked:
    """End-to-end: verify ConstellationRuntime.run() is called, not skipped."""

    @pytest.mark.asyncio
    async def test_run_called_via_galaxy_orchestrator(self):
        """Spy on ConstellationRuntime.run() to confirm it fires through GalaxyOrchestrator."""
        from core.constellation_runtime import ConstellationRuntime
        import core.constellation_runtime as _mod

        _mod._runtime_instance = None
        try:
            real_runtime = ConstellationRuntime(enable_dag_evolution=False)
            real_runtime.run = AsyncMock(return_value=_CR_RESPONSE)
            _mod._runtime_instance = real_runtime

            from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator
            orch = GalaxyOrchestrator({})
            await orch.process_request("spy on run")

            real_runtime.run.assert_called_once()
        finally:
            _mod._runtime_instance = None

    @pytest.mark.asyncio
    async def test_run_called_via_e2e_orchestrator(self):
        """Spy on ConstellationRuntime.run() to confirm it fires through e2e_orchestrator."""
        from core.constellation_runtime import ConstellationRuntime
        import core.constellation_runtime as _mod

        _mod._runtime_instance = None
        try:
            real_runtime = ConstellationRuntime(enable_dag_evolution=False)
            real_runtime.run = AsyncMock(return_value=_CR_RESPONSE)
            _mod._runtime_instance = real_runtime

            from core.e2e_orchestrator import process_user_input
            await process_user_input("spy on e2e run")

            real_runtime.run.assert_called_once()
        finally:
            _mod._runtime_instance = None


# ===========================================================================
# E) ConstellationRuntime.run() returns the expected dict shape
# ===========================================================================

class TestConstellationRuntimeResponseShape:
    """ConstellationRuntime.run() must return a dict with required keys."""

    @pytest.mark.asyncio
    async def test_run_returns_required_keys(self):
        """run() must return success, reply, trace_id, session_id, mode."""
        from core.constellation_runtime import ConstellationRuntime
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus

        rt = ConstellationRuntime(enable_dag_evolution=False)

        mock_orch = MagicMock()
        subtask = SubTask(task_id="t1", name="step1", description="step", status=SubTaskStatus.PENDING)
        decomp = TaskDecomposition(goal="test", subtasks=[subtask])
        mock_orch._decompose_task = AsyncMock(return_value=decomp)
        mock_orch._execute_subtask = AsyncMock(return_value={
            "success": True, "result": "done", "tool": "noop",
        })
        rt._smart_orchestrator = mock_orch

        result = await rt.run("test task description")

        assert "success" in result
        assert "reply" in result
        assert "trace_id" in result
        assert "mode" in result
