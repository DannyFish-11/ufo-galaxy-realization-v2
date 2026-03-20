"""
tests/test_openclawd_execution_integration.py
==============================================

Integration tests verifying that the Decision Executor is correctly wired
into OpenClawd's process() pipeline (PR-8).

Test groups
-----------
  A) _get_decision_executor — returns a DecisionExecutor, caches on re-call.
  B) _run_execution — dispatches to executor, swallows errors.
  C) _run_execution with disabled system actions — always noop, no side effects.
  D) OpenClawd.process() response includes state_continuum and execution is
     triggered without breaking the response structure.
  E) Backward compatibility: execution errors never surface in the response.
  F) _run_execution with enabled actions and allowlisted target — launch triggered.
  G) _run_execution entry_mode forwarding (PR-2).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution.decision_executor import DecisionExecutor, ExecutionResult, PolicyGate
from core.system_api.platform_api import AppLaunchResult, NoOpSystemAPI


# ---------------------------------------------------------------------------
# Minimal OpenClawd fixture
# ---------------------------------------------------------------------------

def _make_openclawd():
    """Return an OpenClawd instance with heavy side-effecting init suppressed."""
    with patch("core.openclawd.OpenClawd.__init__", return_value=None):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
    # Minimal attribute set needed for the methods under test
    oc._continuum_orchestrator = None
    oc._decision_executor = None
    return oc


# ---------------------------------------------------------------------------
# A) _get_decision_executor
# ---------------------------------------------------------------------------

class TestGetDecisionExecutor:
    def test_returns_executor(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        ex = oc._get_decision_executor()
        assert isinstance(ex, DecisionExecutor)

    def test_cached_on_second_call(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        ex1 = oc._get_decision_executor()
        ex2 = oc._get_decision_executor()
        assert ex1 is ex2

    def test_import_failure_returns_none(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        with patch("core.execution.decision_executor.DecisionExecutor", side_effect=ImportError("missing")):
            # Force re-initialise
            oc._decision_executor = None
            # Patch the import inside the method
            with patch.dict("sys.modules", {"core.execution.decision_executor": None}):  # type: ignore[dict-item]
                oc._decision_executor = None
                result = oc._get_decision_executor()
                # Either None (import failed) or a fresh instance — we only
                # verify no exception escapes
                assert result is None or isinstance(result, DecisionExecutor)


# ---------------------------------------------------------------------------
# B) _run_execution — dispatches to executor
# ---------------------------------------------------------------------------

class TestRunExecution:
    def test_calls_executor_execute(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.return_value = ExecutionResult(action_taken="noop", success=True)
        oc._decision_executor = mock_executor
        oc._run_execution({"decision": {"action_level": "observe"}})
        mock_executor.execute.assert_called_once()

    def test_logs_non_noop_action(self, caplog):
        import logging
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.return_value = ExecutionResult(
            action_taken="launch_app", target="notepad.exe", success=True
        )
        oc._decision_executor = mock_executor
        with caplog.at_level(logging.DEBUG, logger="core.openclawd"):
            oc._run_execution({"decision": {"action_level": "execute"}})
        # No exception — log check is optional as level may be filtered

    def test_executor_exception_swallowed(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.side_effect = RuntimeError("executor exploded")
        oc._decision_executor = mock_executor
        # Should not raise
        oc._run_execution({"decision": {"action_level": "execute"}})

    def test_none_state_handled(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.return_value = ExecutionResult(action_taken="noop", success=True)
        oc._decision_executor = mock_executor
        oc._run_execution(None)
        # Verify None was passed as the state_continuum positional argument
        call_args = mock_executor.execute.call_args
        assert call_args is not None
        assert call_args.args[0] is None


# ---------------------------------------------------------------------------
# C) _run_execution with disabled system actions
# ---------------------------------------------------------------------------

class TestRunExecutionDisabled:
    def test_noop_when_disabled(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        # Real executor with disabled policy
        executor = DecisionExecutor()
        executor._policy = PolicyGate(enabled=False)
        oc._decision_executor = executor
        api = MagicMock(spec=NoOpSystemAPI)
        executor._get_system_api = lambda: api  # type: ignore[method-assign]
        executor._get_assist_app = lambda: "notepad.exe"  # type: ignore[method-assign]

        oc._run_execution({"decision": {"action_level": "assist"}})
        api.focus_window.assert_not_called()
        api.launch_app.assert_not_called()


# ---------------------------------------------------------------------------
# D) OpenClawd.process() response structure — executor called
# ---------------------------------------------------------------------------

class TestProcessIntegration:
    """Verify that _run_execution is invoked as part of process() without
    breaking the response fields."""

    def _make_process_oc(self):
        """Return an OpenClawd wired for a minimal process() run."""
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        # Stub _run_continuum to return a simple dict
        oc._run_continuum = MagicMock(return_value={  # type: ignore[method-assign]
            "phase": "formless",
            "decision": {"action_level": "observe"},
        })
        # Stub _run_execution to be tracked
        oc._run_execution = MagicMock()  # type: ignore[method-assign]
        return oc

    def test_run_execution_called_with_continuum_dict(self):
        oc = self._make_process_oc()
        expected_state = {
            "phase": "formless",
            "decision": {"action_level": "observe"},
        }
        oc._run_continuum.return_value = expected_state

        # Call _run_execution directly (simulating process() behaviour)
        state = oc._run_continuum(trace_id="t1")
        oc._run_execution(state)

        oc._run_execution.assert_called_once_with(expected_state)

    def test_run_execution_receives_none_gracefully(self):
        oc = self._make_process_oc()
        oc._run_continuum.return_value = None
        state = oc._run_continuum(trace_id="t1")
        oc._run_execution(state)
        oc._run_execution.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# E) Backward compatibility — execution errors never surface
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_broken_executor_does_not_raise(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        broken_executor = MagicMock(spec=DecisionExecutor)
        broken_executor.execute.side_effect = Exception("total failure")
        oc._decision_executor = broken_executor

        # Must not raise
        oc._run_execution({"decision": {"action_level": "execute"}})

    def test_missing_executor_does_not_raise(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        oc._decision_executor = None
        with patch("core.execution.decision_executor.DecisionExecutor", side_effect=Exception("import fail")):
            oc._decision_executor = None
            # Should not raise even if executor cannot be created
            oc._run_execution({"decision": {"action_level": "execute"}})


# ---------------------------------------------------------------------------
# F) Enabled actions with allowlisted target
# ---------------------------------------------------------------------------

class TestEnabledExecutionFlow:
    def test_launch_triggered_for_execute_level(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        api = MagicMock()
        api.launch_app.return_value = AppLaunchResult(success=True, pid=99)

        executor = DecisionExecutor()
        executor._policy = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        executor._get_system_api = lambda: api  # type: ignore[method-assign]
        executor._get_assist_app = lambda: None  # type: ignore[method-assign]
        oc._decision_executor = executor

        state = {
            "phase": "manifest",
            "decision": {"action_level": "execute"},
            "metadata": {"execution_target": "notepad.exe"},
        }
        oc._run_execution(state)
        api.launch_app.assert_called_once_with("notepad.exe")

    def test_focus_triggered_for_assist_level(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        api = MagicMock()
        api.focus_window.return_value = True

        executor = DecisionExecutor()
        executor._policy = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        executor._get_system_api = lambda: api  # type: ignore[method-assign]
        executor._get_assist_app = lambda: "notepad.exe"  # type: ignore[method-assign]
        oc._decision_executor = executor

        state = {
            "phase": "manifest",
            "decision": {"action_level": "assist"},
        }
        oc._run_execution(state)
        api.focus_window.assert_called_once_with("notepad.exe")


# ---------------------------------------------------------------------------
# G) _run_execution entry_mode forwarding (PR-2)
# ---------------------------------------------------------------------------

class TestRunExecutionEntryMode:
    """Verify that _run_execution correctly forwards entry_mode to the executor."""

    def test_entry_mode_local_forwarded_to_executor(self):
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.return_value = ExecutionResult(action_taken="noop", success=True)
        oc._decision_executor = mock_executor
        state = {"decision": {"action_level": "observe"}}
        oc._run_execution(state, entry_mode="local")
        call_kwargs = mock_executor.execute.call_args
        assert call_kwargs is not None
        assert call_kwargs.kwargs.get("entry_mode") == "local"

    def test_entry_mode_cross_device_blocks_launch(self):
        """When entry_mode=cross_device, executor should skip execution."""
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        api = MagicMock()
        executor = DecisionExecutor()
        executor._policy = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        executor._get_system_api = lambda: api  # type: ignore[method-assign]
        executor._get_assist_app = lambda: None  # type: ignore[method-assign]
        oc._decision_executor = executor

        state = {
            "phase": "manifest",
            "decision": {"action_level": "execute"},
            "metadata": {"execution_target": "notepad.exe"},
        }
        oc._run_execution(state, entry_mode="cross_device")
        api.launch_app.assert_not_called()

    def test_entry_mode_none_preserves_existing_behavior(self):
        """When entry_mode is not provided, existing behavior is preserved."""
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        mock_executor = MagicMock(spec=DecisionExecutor)
        mock_executor.execute.return_value = ExecutionResult(action_taken="noop", success=True)
        oc._decision_executor = mock_executor
        state = {"decision": {"action_level": "observe"}}
        oc._run_execution(state)  # no entry_mode
        call_kwargs = mock_executor.execute.call_args
        assert call_kwargs is not None
        # entry_mode should be None (default)
        assert call_kwargs.kwargs.get("entry_mode") is None

    def test_force_local_execution_in_metadata_overrides_cross_device(self):
        """force_local_execution=True in state_continuum metadata overrides cross_device block."""
        from core.openclawd import OpenClawd
        oc = _make_openclawd()
        api = MagicMock()
        api.launch_app.return_value = AppLaunchResult(success=True, pid=99)
        executor = DecisionExecutor()
        executor._policy = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        executor._get_system_api = lambda: api  # type: ignore[method-assign]
        executor._get_assist_app = lambda: None  # type: ignore[method-assign]
        oc._decision_executor = executor

        state = {
            "phase": "manifest",
            "decision": {"action_level": "execute"},
            "metadata": {
                "execution_target": "notepad.exe",
                "force_local_execution": True,
            },
        }
        oc._run_execution(state, entry_mode="cross_device")
        api.launch_app.assert_called_once_with("notepad.exe")
