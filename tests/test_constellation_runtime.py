"""
tests/test_constellation_runtime.py
=====================================

Tests for :class:`core.constellation_runtime.ConstellationRuntime`.

Covers:
  A) get_constellation_runtime() factory returns singleton
  B) run() returns expected structure (mocked SmartOrchestrator)
  C) DAG evolution is called on failure
  D) DevicePoolManager is consulted for device selection
  E) Audit ledger receives DAG lifecycle events
  F) Backward-compat: e2e_orchestrator.process_user_input(use_constellation=False)
     still routes to legacy pipeline
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# A) Singleton factory
# ===========================================================================

class TestFactory:
    def test_get_constellation_runtime_returns_same_instance(self):
        from core.constellation_runtime import get_constellation_runtime, ConstellationRuntime
        # Reset singleton for isolation
        import core.constellation_runtime as _mod
        _mod._runtime_instance = None
        r1 = get_constellation_runtime()
        r2 = get_constellation_runtime()
        assert r1 is r2
        assert isinstance(r1, ConstellationRuntime)
        # Cleanup
        _mod._runtime_instance = None

    def test_constructor_sets_dag_evolution_flag(self):
        from core.constellation_runtime import ConstellationRuntime
        rt = ConstellationRuntime(enable_dag_evolution=False)
        assert rt.enable_dag_evolution is False


# ===========================================================================
# B) run() with mocked SmartOrchestrator
# ===========================================================================

class TestRunBasic:
    @pytest.mark.asyncio
    async def test_run_returns_success_structure(self):
        from core.constellation_runtime import ConstellationRuntime
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus

        rt = ConstellationRuntime(enable_dag_evolution=False)

        # Patch SmartOrchestrator to return a simple decomposition
        mock_orchestrator = MagicMock()

        async def _decompose(desc, ctx):
            st = SubTask(task_id="t1", name="step1", status=SubTaskStatus.PENDING)
            return TaskDecomposition(goal=desc, subtasks=[st])

        mock_orchestrator._decompose_task = _decompose

        async def _exec_subtask(task, req):
            task.status = SubTaskStatus.SUCCESS
            task.result = {"reply": "done"}

        mock_orchestrator._execute_subtask = _exec_subtask

        rt._smart_orchestrator = mock_orchestrator

        with patch("core.constellation_runtime.ConstellationRuntime._try_node71",
                   new_callable=AsyncMock, return_value=None):
            result = await rt.run(task_description="test task")

        assert "success" in result
        assert "trace_id" in result
        assert "session_id" in result
        assert "mode" in result

    @pytest.mark.asyncio
    async def test_run_returns_fallback_when_orchestrator_unavailable(self):
        from core.constellation_runtime import ConstellationRuntime

        rt = ConstellationRuntime(enable_dag_evolution=False)
        rt._smart_orchestrator = None  # force unavailable

        with patch("core.constellation_runtime.ConstellationRuntime._try_node71",
                   new_callable=AsyncMock, return_value=None):
            with patch.object(rt, "_get_smart_orchestrator", return_value=None):
                result = await rt.run(task_description="test task")

        assert result["success"] is False


# ===========================================================================
# C) DAG evolution is called on failure
# ===========================================================================

class TestDAGEvolution:
    @pytest.mark.asyncio
    async def test_evolver_called_on_subtask_failure(self):
        from core.constellation_runtime import ConstellationRuntime
        from core.schemas.orchestration import (
            TaskDecomposition, SubTask, SubTaskStatus,
        )
        from core.dag_evolver import DAGEvolver

        rt = ConstellationRuntime(enable_dag_evolution=True)

        evolver_calls = []

        original_on_failed = DAGEvolver.on_task_failed

        def _spy_on_failed(self, decomp, failed_task_id, **kw):
            evolver_calls.append(failed_task_id)
            return decomp  # no actual replan

        mock_orchestrator = MagicMock()

        async def _decompose(desc, ctx):
            st = SubTask(task_id="t1", name="step1", status=SubTaskStatus.PENDING)
            return TaskDecomposition(goal=desc, subtasks=[st])

        async def _exec_subtask(task, req):
            task.status = SubTaskStatus.FAILED
            task.error = "simulated failure"

        mock_orchestrator._decompose_task = _decompose
        mock_orchestrator._execute_subtask = _exec_subtask
        rt._smart_orchestrator = mock_orchestrator

        with patch.object(DAGEvolver, "on_task_failed", _spy_on_failed):
            with patch("core.constellation_runtime.ConstellationRuntime._try_node71",
                       new_callable=AsyncMock, return_value=None):
                await rt.run(task_description="fail test")

        assert len(evolver_calls) > 0


# ===========================================================================
# D) DevicePoolManager consulted for device selection
# ===========================================================================

class TestDevicePoolIntegration:
    @pytest.mark.asyncio
    async def test_device_pool_select_device_called(self):
        from core.constellation_runtime import ConstellationRuntime
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus

        rt = ConstellationRuntime(enable_dag_evolution=False)

        mock_orchestrator = MagicMock()
        select_calls = []

        async def _decompose(desc, ctx):
            st = SubTask(
                task_id="t1", name="step1", device_type="android",
                status=SubTaskStatus.PENDING
            )
            return TaskDecomposition(goal=desc, subtasks=[st])

        async def _exec_subtask(task, req):
            task.status = SubTaskStatus.SUCCESS
            task.result = {}

        mock_orchestrator._decompose_task = _decompose
        mock_orchestrator._execute_subtask = _exec_subtask
        rt._smart_orchestrator = mock_orchestrator

        mock_pool = MagicMock()
        mock_pool.select_device.return_value = "dev_android_1"
        mock_pool.mark_success = MagicMock()

        with patch.object(rt, "_get_device_pool", return_value=mock_pool):
            with patch("core.constellation_runtime.ConstellationRuntime._try_node71",
                       new_callable=AsyncMock, return_value=None):
                await rt.run(task_description="device test")

        mock_pool.select_device.assert_called()


# ===========================================================================
# E) Audit ledger lifecycle events
# ===========================================================================

class TestAuditLedgerEvents:
    @pytest.mark.asyncio
    async def test_dag_planned_event_appended(self):
        from core.constellation_runtime import ConstellationRuntime
        from core.schemas.orchestration import TaskDecomposition, SubTask, SubTaskStatus
        from core.control_plane.audit_ledger import AuditLedger, EventType

        # Use a fresh ledger so we don't inherit global state
        fresh_ledger = AuditLedger()

        rt = ConstellationRuntime(enable_dag_evolution=False)
        mock_orchestrator = MagicMock()

        async def _decompose(desc, ctx):
            st = SubTask(task_id="t1", name="step1", status=SubTaskStatus.PENDING)
            return TaskDecomposition(goal=desc, subtasks=[st])

        async def _exec_subtask(task, req):
            task.status = SubTaskStatus.SUCCESS
            task.result = {}

        mock_orchestrator._decompose_task = _decompose
        mock_orchestrator._execute_subtask = _exec_subtask
        rt._smart_orchestrator = mock_orchestrator

        with patch.object(rt, "_get_audit_ledger", return_value=fresh_ledger):
            with patch("core.constellation_runtime.ConstellationRuntime._try_node71",
                       new_callable=AsyncMock, return_value=None):
                await rt.run(task_description="audit test")

        event_types = [ev.event_type for ev in fresh_ledger.all_events]
        assert EventType.TASK_CREATED in event_types
        assert EventType.DAG_PLANNED in event_types
        assert EventType.DAG_COMPLETED in event_types


# ===========================================================================
# F) Backward-compat: e2e_orchestrator legacy path + default routing
# ===========================================================================

class TestE2EOrchestratorBackwardCompat:
    @pytest.mark.asyncio
    async def test_legacy_path_when_constellation_disabled(self):
        """process_user_input with use_constellation=False should hit pipeline."""
        pipeline_called = []

        class _FakePipeline:
            async def execute(self, **kw):
                pipeline_called.append(kw)
                return {
                    "success": True, "reply": "ok", "session_id": "s1",
                    "mode": "chat", "data": {}, "devices_notified": [],
                }

        with patch("core.e2e_pipeline.get_pipeline", return_value=_FakePipeline()):
            from core.e2e_orchestrator import process_user_input
            result = await process_user_input(
                message="hello", use_constellation=False
            )

        assert result["success"] is True
        assert len(pipeline_called) == 1

    @pytest.mark.asyncio
    async def test_default_prefers_constellation_runtime(self):
        """process_user_input with no use_constellation arg should default to ConstellationRuntime."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value={
            "success": True,
            "reply": "dag reply",
            "session_id": "sess-cr",
            "mode": "dag",
            "data": {},
            "trace_id": "tr-abc",
        })

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from core.e2e_orchestrator import process_user_input
            result = await process_user_input(message="test default")

        assert result["success"] is True
        assert result["mode"] == "dag"
        mock_runtime.run.assert_called_once()
