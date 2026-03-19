"""
tests/test_pr5_legacy_deprecation.py
=====================================

PR-5: Deprecate Legacy Orchestrator Entry Points — deprecation warnings and
guardrail behaviour tests.

Covers:
  A) Node_110 — startup deprecation log, ``served_by`` response field,
     ``legacy_override`` guardrail warning.
  B) Node_81  — startup deprecation log, ``legacy_override`` field on
     WorkflowRequest, guardrail log on fallback.
  C) Node_50  — ``DeprecationWarning`` raised when TaskOrchestrator is
     instantiated directly.
  D) core/constellation_runtime — ``warn_legacy_path()`` helper emits a
     structured warning, ``LEGACY_ORCHESTRATOR_PATHS`` constant exists.
  E) core/e2e_orchestrator — structured warning logged when
     ``use_constellation=False``.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import importlib
import logging
import warnings
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# Shared helpers
# ===========================================================================

_CR_SUCCESS: Dict[str, Any] = {
    "success": True,
    "reply": "CR replied",
    "trace_id": "tr-pr5-001",
    "session_id": "sess-pr5-001",
    "mode": "dag",
    "data": {"steps": 1},
    "elapsed_ms": 10.0,
}


# ===========================================================================
# A) Node_110 — startup warning + served_by + legacy_override guardrail
# ===========================================================================

class TestNode110DeprecationWarnings:
    """Node_110 server.py must emit deprecation log at module init."""

    def test_startup_deprecation_warning_in_logs(self, caplog):
        """Module-level logger.warning must fire DEPRECATION [Node_110…] on load."""
        # Force a fresh import so the module-level warning fires.
        import sys
        sys.modules.pop("nodes.Node_110_SmartOrchestrator.server", None)

        with caplog.at_level(logging.WARNING, logger="nodes.Node_110_SmartOrchestrator.server"):
            importlib.import_module("nodes.Node_110_SmartOrchestrator.server")

        deprecation_msgs = [r.message for r in caplog.records if "DEPRECATION" in r.message]
        assert deprecation_msgs, (
            "Node_110_SmartOrchestrator.server must log a DEPRECATION warning at startup"
        )
        assert any("Node_110" in m for m in deprecation_msgs)

    @pytest.mark.asyncio
    async def test_served_by_field_is_constellationruntime_on_success(self):
        """OrchestrationResponse.served_by must equal 'ConstellationRuntime' on CR success."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            from nodes.Node_110_SmartOrchestrator.server import (
                orchestrate_task,
                OrchestrationRequest,
            )

            req = OrchestrationRequest(task_description="pr5 test task")
            response = await orchestrate_task(req)

        assert response.served_by == "ConstellationRuntime"

    @pytest.mark.asyncio
    async def test_served_by_field_is_legacy_on_fallback(self):
        """OrchestrationResponse.served_by must equal 'legacy' when CR fails and fallback is used."""
        fallback_result = {
            "task_id": "legacy-task-1",
            "status": "completed",
            "execution_plan": {"mode": "legacy"},
            "result": {"reply": "legacy ok"},
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
                from nodes.Node_110_SmartOrchestrator.server import (
                    orchestrate_task,
                    OrchestrationRequest,
                )

                req = OrchestrationRequest(
                    task_description="fallback task",
                    legacy_override=True,
                )
                response = await orchestrate_task(req)

        assert response.served_by == "legacy"

    @pytest.mark.asyncio
    async def test_legacy_override_true_logs_guardrail_warning(self, caplog):
        """Setting legacy_override=True must log a DEPRECATION GUARDRAIL warning."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            with caplog.at_level(
                logging.WARNING,
                logger="nodes.Node_110_SmartOrchestrator.server",
            ):
                from nodes.Node_110_SmartOrchestrator.server import (
                    orchestrate_task,
                    OrchestrationRequest,
                )

                req = OrchestrationRequest(
                    task_description="override test",
                    legacy_override=True,
                )
                await orchestrate_task(req)

        guardrail_msgs = [
            r.message for r in caplog.records if "DEPRECATION GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "A DEPRECATION GUARDRAIL warning must be logged when legacy_override=True"
        )

    @pytest.mark.asyncio
    async def test_fallback_without_override_logs_guardrail_warning(self, caplog):
        """Even without legacy_override, a DEPRECATION GUARDRAIL must be logged on CR failure."""
        fallback_result = {
            "task_id": "noop-task",
            "status": "completed",
            "execution_plan": {"mode": "legacy"},
            "result": {"reply": "ok"},
        }
        mock_fallback = MagicMock()
        mock_fallback.orchestrate_task = AsyncMock(return_value=fallback_result)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            side_effect=RuntimeError("CR down"),
        ):
            with patch(
                "nodes.Node_110_SmartOrchestrator.server._fallback_orchestrator",
                mock_fallback,
            ):
                with caplog.at_level(
                    logging.WARNING,
                    logger="nodes.Node_110_SmartOrchestrator.server",
                ):
                    from nodes.Node_110_SmartOrchestrator.server import (
                        orchestrate_task,
                        OrchestrationRequest,
                    )

                    req = OrchestrationRequest(task_description="no override test")
                    await orchestrate_task(req)

        guardrail_msgs = [
            r.message for r in caplog.records if "DEPRECATION GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "A DEPRECATION GUARDRAIL warning must be logged on legacy fallback even without override"
        )

    def test_orchestration_request_has_legacy_override_field(self):
        """OrchestrationRequest must accept legacy_override (default False)."""
        from nodes.Node_110_SmartOrchestrator.server import OrchestrationRequest

        req = OrchestrationRequest(task_description="check field")
        assert req.legacy_override is False

        req_override = OrchestrationRequest(
            task_description="check field", legacy_override=True
        )
        assert req_override.legacy_override is True

    def test_orchestration_response_has_served_by_field(self):
        """OrchestrationResponse must include served_by with default 'ConstellationRuntime'."""
        from nodes.Node_110_SmartOrchestrator.server import OrchestrationResponse

        resp = OrchestrationResponse(
            task_id="t1",
            status="completed",
            execution_plan={"mode": "dag"},
            result={"reply": "ok"},
        )
        assert resp.served_by == "ConstellationRuntime"


# ===========================================================================
# B) Node_81 — startup warning + legacy_override field + guardrail log
# ===========================================================================

class TestNode81DeprecationWarnings:
    """Node_81 main.py must emit deprecation log at startup and guard fallback."""

    def test_workflow_request_has_legacy_override_field(self):
        """WorkflowRequest must accept legacy_override (default False)."""
        from nodes.Node_81_Orchestrator.main import WorkflowRequest

        req = WorkflowRequest(
            description="check field",
            tasks=[],
        )
        assert req.legacy_override is False

        req_override = WorkflowRequest(
            description="check field",
            tasks=[],
            legacy_override=True,
        )
        assert req_override.legacy_override is True

    @pytest.mark.asyncio
    async def test_legacy_override_true_logs_guardrail_warning(self, caplog):
        """Setting legacy_override=True must log a DEPRECATION GUARDRAIL warning."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            with caplog.at_level(
                logging.WARNING,
                logger="nodes.Node_81_Orchestrator.main",
            ):
                from nodes.Node_81_Orchestrator.main import (
                    execute_workflow,
                    WorkflowRequest,
                    Task,
                    TaskType,
                    NodeCall,
                )

                req = WorkflowRequest(
                    description="override workflow",
                    tasks=[
                        Task(
                            task_id="t1",
                            task_type=TaskType.SIMPLE,
                            description="step1",
                            calls=[NodeCall(node_id="01", endpoint="/run", method="POST")],
                        )
                    ],
                    legacy_override=True,
                )
                await execute_workflow(req, background_tasks=MagicMock())

        guardrail_msgs = [
            r.message for r in caplog.records if "DEPRECATION GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "A DEPRECATION GUARDRAIL warning must be logged when legacy_override=True on Node_81"
        )

    @pytest.mark.asyncio
    async def test_fallback_without_override_logs_guardrail_warning(self, caplog):
        """Fallback to local engine without legacy_override must log DEPRECATION GUARDRAIL."""
        from nodes.Node_81_Orchestrator.main import (
            WorkflowRequest,
            WorkflowResult,
            TaskStatus,
            Task,
            TaskType,
            NodeCall,
        )

        fallback_result = WorkflowResult(
            workflow_id="wf-guardrail",
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
                with caplog.at_level(
                    logging.WARNING,
                    logger="nodes.Node_81_Orchestrator.main",
                ):
                    from nodes.Node_81_Orchestrator.main import execute_workflow

                    req = WorkflowRequest(
                        description="guardrail workflow",
                        tasks=[
                            Task(
                                task_id="t1",
                                task_type=TaskType.SIMPLE,
                                description="step1",
                                calls=[NodeCall(node_id="01", endpoint="/run", method="POST")],
                            )
                        ],
                    )
                    await execute_workflow(req, background_tasks=MagicMock())

        guardrail_msgs = [
            r.message for r in caplog.records if "DEPRECATION GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "A DEPRECATION GUARDRAIL warning must be logged on Node_81 fallback"
        )


# ===========================================================================
# C) Node_50 — DeprecationWarning on instantiation
# ===========================================================================

class TestNode50DeprecationWarning:
    """TaskOrchestrator must emit a DeprecationWarning when instantiated directly."""

    def test_task_orchestrator_emits_deprecation_warning(self):
        """Instantiating TaskOrchestrator must raise DeprecationWarning."""
        import sys

        # Stub out the dependency that TaskOrchestrator imports at module level.
        # enhanced_nlu_engine is not always installed in test environment.
        stub_nlu = MagicMock()
        stub_nlu.TaskStep = object
        stub_nlu.TargetDevice = object
        sys.modules.setdefault("enhanced_nlu_engine", stub_nlu)

        from nodes.Node_50_Transformer.task_orchestrator import TaskOrchestrator

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            TaskOrchestrator()

        deprecations = [
            w for w in caught if issubclass(w.category, DeprecationWarning)
        ]
        assert deprecations, (
            "TaskOrchestrator.__init__ must emit a DeprecationWarning"
        )
        msg = str(deprecations[0].message)
        assert "legacy" in msg.lower() or "subordinate" in msg.lower() or "ConstellationRuntime" in msg

    def test_task_orchestrator_docstring_marks_legacy(self):
        """task_orchestrator.py module docstring must mention legacy/subordinate."""
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
        doc = ast.get_docstring(tree) or ""
        doc_lower = doc.lower()
        assert "legacy" in doc_lower or "从属" in doc or "subordinate" in doc_lower, (
            "task_orchestrator.py docstring must mark this module as legacy/subordinate"
        )


# ===========================================================================
# D) core/constellation_runtime — warn_legacy_path() + LEGACY_ORCHESTRATOR_PATHS
# ===========================================================================

class TestConstellationRuntimeGuardrails:
    """ConstellationRuntime must expose the warn_legacy_path() guardrail helper."""

    def test_warn_legacy_path_is_exported(self):
        """warn_legacy_path must be importable from core.constellation_runtime."""
        from core.constellation_runtime import warn_legacy_path

        assert callable(warn_legacy_path)

    def test_legacy_orchestrator_paths_constant_exists(self):
        """LEGACY_ORCHESTRATOR_PATHS must be a non-empty frozenset."""
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS

        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)
        assert len(LEGACY_ORCHESTRATOR_PATHS) > 0

    def test_legacy_orchestrator_paths_contains_known_nodes(self):
        """LEGACY_ORCHESTRATOR_PATHS must include Node_81, Node_110, and Node_50."""
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS

        known = {
            "nodes.Node_110_SmartOrchestrator.server",
            "nodes.Node_81_Orchestrator.main",
            "nodes.Node_50_Transformer.task_orchestrator",
        }
        assert known.issubset(LEGACY_ORCHESTRATOR_PATHS), (
            f"LEGACY_ORCHESTRATOR_PATHS must contain {known}, got {LEGACY_ORCHESTRATOR_PATHS}"
        )

    def test_warn_legacy_path_logs_structured_warning(self, caplog):
        """warn_legacy_path() must log a WARNING containing caller and trace_id."""
        from core.constellation_runtime import warn_legacy_path

        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            warn_legacy_path(
                caller="nodes.Node_110_SmartOrchestrator.server",
                trace_id="trace-pr5-test",
            )

        msgs = [r.message for r in caplog.records]
        assert any("LEGACY PATH GUARDRAIL" in m for m in msgs), (
            "warn_legacy_path() must log a message containing 'LEGACY PATH GUARDRAIL'"
        )
        assert any("trace-pr5-test" in m for m in msgs), (
            "warn_legacy_path() must include the trace_id in the log message"
        )
        assert any("nodes.Node_110_SmartOrchestrator.server" in m for m in msgs), (
            "warn_legacy_path() must include the caller in the log message"
        )

    def test_warn_legacy_path_without_trace_id(self, caplog):
        """warn_legacy_path() must still log when trace_id is omitted."""
        from core.constellation_runtime import warn_legacy_path

        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            warn_legacy_path(caller="nodes.Node_81_Orchestrator.main")

        msgs = [r.message for r in caplog.records]
        assert any("LEGACY PATH GUARDRAIL" in m for m in msgs)


# ===========================================================================
# E) core/e2e_orchestrator — structured warning on use_constellation=False
# ===========================================================================

class TestE2EOrchestratorGuardrails:
    """process_user_input must log a structured warning when use_constellation=False."""

    @pytest.mark.asyncio
    async def test_use_constellation_false_logs_guardrail_warning(self, caplog):
        """Passing use_constellation=False must log a LEGACY PATH GUARDRAIL warning."""
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(
            return_value={
                "success": True,
                "reply": "pipeline reply",
                "session_id": "sess-e2e",
                "mode": "chat",
                "data": {},
                "devices_notified": [],
            }
        )

        with patch("core.e2e_pipeline.get_pipeline", return_value=mock_pipeline):
            with caplog.at_level(
                logging.WARNING, logger="Galaxy.E2EOrchestrator"
            ):
                from core.e2e_orchestrator import process_user_input

                await process_user_input(
                    message="legacy path test",
                    use_constellation=False,
                )

        guardrail_msgs = [
            r.message for r in caplog.records if "LEGACY PATH GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "process_user_input must log LEGACY PATH GUARDRAIL warning when use_constellation=False"
        )
        assert any("use_constellation=False" in m for m in guardrail_msgs), (
            "The guardrail warning must mention use_constellation=False"
        )

    @pytest.mark.asyncio
    async def test_use_constellation_true_does_not_log_guardrail_warning(self, caplog):
        """Default path (use_constellation=True) must NOT log a guardrail warning."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value=_CR_SUCCESS)

        with patch(
            "core.constellation_runtime.get_constellation_runtime",
            return_value=mock_runtime,
        ):
            with caplog.at_level(
                logging.WARNING, logger="Galaxy.E2EOrchestrator"
            ):
                from core.e2e_orchestrator import process_user_input

                await process_user_input(
                    message="normal path test",
                    use_constellation=True,
                )

        guardrail_msgs = [
            r.message for r in caplog.records if "LEGACY PATH GUARDRAIL" in r.message
        ]
        assert not guardrail_msgs, (
            "No LEGACY PATH GUARDRAIL warning should be logged on the normal use_constellation=True path"
        )
