"""
tests/test_pr1_orchestration_delegation.py
===========================================

PR-1: Orchestration Entry Unification — delegation tests

Confirms that:
1. Node_110 ``/api/v1/orchestrate`` delegates to ConstellationRuntime by default.
2. Node_110 falls back to SmartOrchestrator when ConstellationRuntime raises.
3. Node_81 ``/workflow`` delegates to ConstellationRuntime by default.
4. Node_81 falls back to local engine when ConstellationRuntime raises.
5. ``wrap_as_orchestration_response`` shapes CR results correctly.
6. Node_50 task_orchestrator module docstring marks it as a legacy subordinate.
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ===========================================================================
# Helper — shared CR mock result
# ===========================================================================

_CR_SUCCESS = {
    "success": True,
    "reply": "CR replied",
    "trace_id": "tr-cr-001",
    "session_id": "sess-cr-001",
    "mode": "dag",
    "data": {"steps": 2},
    "elapsed_ms": 42.0,
}

_CR_FAILURE = {
    "success": False,
    "reply": "failed",
    "trace_id": "tr-cr-fail",
    "session_id": "sess-cr-fail",
    "mode": "fallback",
    "data": {},
    "elapsed_ms": 5.0,
}


# ===========================================================================
# D) wrap_as_orchestration_response helper
# ===========================================================================

class TestWrapAsOrchestrationResponse:
    def test_success_shapes_correctly(self):
        from core.constellation_runtime import wrap_as_orchestration_response

        shaped = wrap_as_orchestration_response(_CR_SUCCESS, task_id="task-wrap-1")
        assert shaped["task_id"] == "task-wrap-1"
        assert shaped["status"] == "completed"
        assert shaped["execution_plan"]["mode"] == "dag"
        assert shaped["result"]["reply"] == "CR replied"
        assert shaped["result"]["success"] is True
        assert shaped["trace_id"] == "tr-cr-001"
        assert shaped["session_id"] == "sess-cr-001"

    def test_failure_shapes_correctly(self):
        from core.constellation_runtime import wrap_as_orchestration_response

        shaped = wrap_as_orchestration_response(_CR_FAILURE)
        assert shaped["status"] == "failed"
        assert shaped["result"]["success"] is False

    def test_auto_task_id_from_trace(self):
        from core.constellation_runtime import wrap_as_orchestration_response

        shaped = wrap_as_orchestration_response(_CR_SUCCESS)
        # task_id should fall back to trace_id when not provided
        assert shaped["task_id"] == "tr-cr-001"


# ===========================================================================
# A) Node_110 — delegates to ConstellationRuntime
# ===========================================================================

class TestNode110Delegation:
    @pytest.mark.asyncio
    async def test_orchestrate_delegates_to_cr_by_default(self):
        """POST /api/v1/orchestrate must call ConstellationRuntime.run()."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from nodes.Node_110_SmartOrchestrator.server import orchestrate_task
            from nodes.Node_110_SmartOrchestrator.server import OrchestrationRequest

            req = OrchestrationRequest(task_description="take a screenshot")
            response = await orchestrate_task(req)

        mock_runtime.run.assert_called_once()
        _, call_kwargs = mock_runtime.run.call_args
        assert call_kwargs.get("task_description") == "take a screenshot"

        assert response.task_id == "tr-cr-001"
        assert response.status == "completed"

    @pytest.mark.asyncio
    async def test_orchestrate_falls_back_when_cr_raises(self):
        """When ConstellationRuntime.run() raises, Node_110 uses fallback orchestrator."""
        from nodes.Node_110_SmartOrchestrator.server import OrchestrationRequest

        fallback_result = {
            "task_id": "fallback-task-1",
            "status": "completed",
            "execution_plan": {"mode": "legacy"},
            "result": {"reply": "fallback ok"},
        }
        mock_fallback = MagicMock()
        mock_fallback.orchestrate_task = AsyncMock(return_value=fallback_result)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            side_effect=RuntimeError("CR unavailable"),
        ):
            with patch(
                "nodes.Node_110_SmartOrchestrator.server._fallback_orchestrator",
                mock_fallback,
            ):
                from nodes.Node_110_SmartOrchestrator.server import orchestrate_task

                req = OrchestrationRequest(task_description="fallback test")
                response = await orchestrate_task(req)

        mock_fallback.orchestrate_task.assert_called_once()
        assert response.task_id == "fallback-task-1"
        assert response.status == "completed"


# ===========================================================================
# B) Node_81 — delegates to ConstellationRuntime
# ===========================================================================

class TestNode81Delegation:
    @pytest.mark.asyncio
    async def test_workflow_delegates_to_cr_by_default(self):
        """POST /workflow must call ConstellationRuntime.run()."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from nodes.Node_81_Orchestrator.main import execute_workflow
            from nodes.Node_81_Orchestrator.main import WorkflowRequest, Task, TaskType, NodeCall

            req = WorkflowRequest(
                description="coordinate screenshot and analysis",
                tasks=[
                    Task(
                        task_id="t1",
                        task_type=TaskType.SIMPLE,
                        description="step1",
                        calls=[NodeCall(node_id="01", endpoint="/run", method="POST")],
                    )
                ],
            )
            result = await execute_workflow(req, background_tasks=MagicMock())

        mock_runtime.run.assert_called_once()
        # response must conform to WorkflowResult schema
        assert result.workflow_id is not None
        assert result.status.value in ("completed", "failed")

    @pytest.mark.asyncio
    async def test_workflow_falls_back_when_cr_raises(self):
        """When ConstellationRuntime raises, Node_81 uses its own engine."""
        from nodes.Node_81_Orchestrator.main import (
            WorkflowRequest,
            WorkflowResult,
            TaskStatus,
            Task,
            TaskType,
            NodeCall,
        )

        fallback_result = WorkflowResult(
            workflow_id="wf-fallback-1",
            status=TaskStatus.COMPLETED,
            tasks=[],
            started_at="2025-01-01T00:00:00",
        )

        mock_local = MagicMock()
        mock_local.execute_workflow = AsyncMock(return_value=fallback_result)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            side_effect=RuntimeError("CR unavailable"),
        ):
            with patch(
                "nodes.Node_81_Orchestrator.main.orchestrator",
                mock_local,
            ):
                from nodes.Node_81_Orchestrator.main import execute_workflow

                req = WorkflowRequest(
                    description="fallback workflow",
                    tasks=[
                        Task(
                            task_id="t1",
                            task_type=TaskType.SIMPLE,
                            description="step1",
                            calls=[NodeCall(node_id="01", endpoint="/run", method="POST")],
                        )
                    ],
                )
                result = await execute_workflow(req, background_tasks=MagicMock())

        mock_local.execute_workflow.assert_called_once()
        assert result.workflow_id == "wf-fallback-1"


# ===========================================================================
# C) Node_50 — marked as subordinate/legacy
# ===========================================================================

class TestNode50LegacyMarker:
    def test_task_orchestrator_docstring_marks_subordinate(self):
        """task_orchestrator module docstring must contain legacy/subordinate marker."""
        import ast
        import pathlib

        src_path = (
            pathlib.Path(__file__).parent.parent
            / "nodes"
            / "Node_50_Transformer"
            / "task_orchestrator.py"
        )
        source = src_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # The first statement of the module should be the docstring
        doc = ast.get_docstring(tree) or ""
        doc_lower = doc.lower()
        assert "legacy" in doc_lower or "从属" in doc or "subordinate" in doc_lower, (
            "task_orchestrator.py docstring must mark this as a legacy/subordinate component"
        )
