"""
tests/test_orchestrator_guardrails.py
=======================================

PR-6 Goal 5: Tests demonstrate guardrails (legacy orchestrator deprecations)
fire as expected.

Covers:
  A) LEGACY_ORCHESTRATOR_PATHS constant exists and includes all known legacy paths
  B) warn_legacy_path() emits a structured WARNING log
  C) warn_legacy_path() includes the caller name in the log record
  D) warn_legacy_path() includes trace_id in the log record
  E) E2EOrchestrator emits a guardrail warning when use_constellation=False
  F) ConstellationRuntime singleton warn_legacy_path is accessible for external callers
  G) All paths in LEGACY_ORCHESTRATOR_PATHS trigger warn_legacy_path without error
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ===========================================================================
# A) LEGACY_ORCHESTRATOR_PATHS constant
# ===========================================================================

class TestLegacyOrchestratorPathsConstant:
    """LEGACY_ORCHESTRATOR_PATHS must exist and cover all known legacy entries."""

    def test_constant_exists(self):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert LEGACY_ORCHESTRATOR_PATHS is not None
        assert len(LEGACY_ORCHESTRATOR_PATHS) > 0

    def test_contains_node_110(self):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert any("Node_110" in p for p in LEGACY_ORCHESTRATOR_PATHS)

    def test_contains_node_81(self):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert any("Node_81" in p for p in LEGACY_ORCHESTRATOR_PATHS)

    def test_contains_node_50(self):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert any("Node_50" in p for p in LEGACY_ORCHESTRATOR_PATHS)

    def test_contains_gateway_task_orchestrator(self):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert any("task_orchestrator" in p for p in LEGACY_ORCHESTRATOR_PATHS)

    def test_is_frozenset(self):
        """The constant must be immutable (frozenset) to prevent accidental mutation."""
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS
        assert isinstance(LEGACY_ORCHESTRATOR_PATHS, frozenset)


# ===========================================================================
# B) warn_legacy_path() emits a structured WARNING log
# ===========================================================================

class TestWarnLegacyPathEmitsWarning:
    """warn_legacy_path() must emit at WARNING level."""

    def test_emits_warning_level(self, caplog):
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            from core.constellation_runtime import warn_legacy_path
            warn_legacy_path(caller="nodes.Node_110_SmartOrchestrator.server")

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, "warn_legacy_path() must emit at least one WARNING record"

    def test_emits_guardrail_keyword(self, caplog):
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            from core.constellation_runtime import warn_legacy_path
            warn_legacy_path(caller="nodes.Node_81_Orchestrator.main")

        messages = [r.message for r in caplog.records]
        assert any("LEGACY PATH GUARDRAIL" in m for m in messages), (
            "warn_legacy_path() message must contain 'LEGACY PATH GUARDRAIL'"
        )


# ===========================================================================
# C) warn_legacy_path() includes caller in the log record
# ===========================================================================

class TestWarnLegacyPathIncludesCaller:
    """warn_legacy_path() must include the caller name in the log output."""

    @pytest.mark.parametrize("caller", [
        "nodes.Node_110_SmartOrchestrator.server",
        "nodes.Node_81_Orchestrator.main",
        "nodes.Node_50_Transformer.task_orchestrator",
        "galaxy_gateway.orchestrator.task_orchestrator",
    ])
    def test_caller_appears_in_log(self, caller: str, caplog):
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            from core.constellation_runtime import warn_legacy_path
            warn_legacy_path(caller=caller)

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert caller in messages, (
            f"warn_legacy_path() must include caller={caller!r} in log output"
        )


# ===========================================================================
# D) warn_legacy_path() includes trace_id in the log record
# ===========================================================================

class TestWarnLegacyPathIncludesTraceId:
    """warn_legacy_path() must include the trace_id when provided."""

    def test_trace_id_in_log(self, caplog):
        trace = "test-trace-abc123"
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            from core.constellation_runtime import warn_legacy_path
            warn_legacy_path(
                caller="nodes.Node_110_SmartOrchestrator.server",
                trace_id=trace,
            )

        messages = " ".join(r.getMessage() for r in caplog.records)
        assert trace in messages, (
            "warn_legacy_path() must include the trace_id in the log output"
        )

    def test_no_trace_id_still_logs(self, caplog):
        """When trace_id is None, warn_legacy_path() must still log without raising."""
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConstellationRuntime"):
            from core.constellation_runtime import warn_legacy_path
            warn_legacy_path(caller="nodes.Node_81_Orchestrator.main", trace_id=None)

        assert caplog.records, "warn_legacy_path() must log even when trace_id is None"


# ===========================================================================
# E) E2EOrchestrator emits a guardrail warning when use_constellation=False
# ===========================================================================

class TestE2EOrchestratorGuardrail:
    """process_user_input(use_constellation=False) must emit a guardrail warning."""

    @pytest.mark.asyncio
    async def test_guardrail_fires_on_bypass(self, caplog):
        mock_pipeline = MagicMock()
        mock_pipeline.execute = AsyncMock(return_value={
            "success": True, "reply": "pipeline", "session_id": "s1",
            "mode": "chat", "data": {}, "devices_notified": [],
        })

        with caplog.at_level(logging.WARNING, logger="Galaxy.E2EOrchestrator"), \
             patch("core.e2e_pipeline.get_pipeline", return_value=mock_pipeline):
            from core.e2e_orchestrator import process_user_input
            await process_user_input("bypass message", use_constellation=False)

        guardrail_msgs = [
            r.message for r in caplog.records
            if "LEGACY PATH GUARDRAIL" in r.message
        ]
        assert guardrail_msgs, (
            "process_user_input(use_constellation=False) must emit a LEGACY PATH GUARDRAIL warning"
        )

    @pytest.mark.asyncio
    async def test_guardrail_not_fired_on_default(self, caplog):
        """No guardrail warning must be emitted when use_constellation is not bypassed."""
        mock_runtime = MagicMock()
        mock_runtime.run = AsyncMock(return_value={
            "success": True, "reply": "cr", "trace_id": "t1",
            "session_id": "s1", "mode": "dag", "data": {},
        })

        with caplog.at_level(logging.WARNING, logger="Galaxy.E2EOrchestrator"), \
             patch(
                 "core.constellation_runtime.get_constellation_runtime",
                 return_value=mock_runtime,
             ):
            from core.e2e_orchestrator import process_user_input
            await process_user_input("normal message")

        guardrail_msgs = [
            r.message for r in caplog.records
            if "LEGACY PATH GUARDRAIL" in r.message
        ]
        assert not guardrail_msgs, (
            "No guardrail warning should fire when use_constellation=True (default)"
        )


# ===========================================================================
# F) warn_legacy_path is importable and callable by external callers
# ===========================================================================

class TestWarnLegacyPathPublicAPI:
    """warn_legacy_path must be importable from core.constellation_runtime."""

    def test_importable(self):
        from core.constellation_runtime import warn_legacy_path
        assert callable(warn_legacy_path)

    def test_accepts_caller_only(self, caplog):
        """Minimum usage: warn_legacy_path(caller=...) must not raise."""
        from core.constellation_runtime import warn_legacy_path
        with caplog.at_level(logging.WARNING):
            warn_legacy_path(caller="test.legacy.caller")
        # No exception means success

    def test_accepts_custom_recommendation(self, caplog):
        from core.constellation_runtime import warn_legacy_path
        with caplog.at_level(logging.WARNING):
            warn_legacy_path(
                caller="test.legacy.caller",
                recommendation="Migrate to new_module.do_thing()",
            )
        messages = " ".join(r.getMessage() for r in caplog.records)
        assert "Migrate to new_module.do_thing()" in messages


# ===========================================================================
# G) All LEGACY_ORCHESTRATOR_PATHS entries fire warn_legacy_path without error
# ===========================================================================

class TestAllLegacyPathsTriggerGuardrail:
    """Every path in LEGACY_ORCHESTRATOR_PATHS must successfully fire warn_legacy_path."""

    def test_all_paths_log_without_raising(self, caplog):
        from core.constellation_runtime import LEGACY_ORCHESTRATOR_PATHS, warn_legacy_path

        with caplog.at_level(logging.WARNING):
            for path in LEGACY_ORCHESTRATOR_PATHS:
                warn_legacy_path(caller=path, trace_id="bulk-test")

        # One warning per path
        guardrail_records = [
            r for r in caplog.records if "LEGACY PATH GUARDRAIL" in r.getMessage()
        ]
        assert len(guardrail_records) >= len(LEGACY_ORCHESTRATOR_PATHS), (
            f"Expected at least {len(LEGACY_ORCHESTRATOR_PATHS)} guardrail records, "
            f"got {len(guardrail_records)}"
        )
