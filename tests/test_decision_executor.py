"""
tests/test_decision_executor.py
================================

Unit tests for core.execution.decision_executor.

Test groups
-----------
  A) _extract_action_level helper — handles None, malformed, and valid dicts.
  B) _extract_execution_target helper — handles None, malformed, and valid dicts.
  C) PolicyGate construction and is_enabled property.
  D) PolicyGate.allows — empty allowlist, case-insensitive, prefix match.
  E) PolicyGate.check_action_level.
  F) ExecutionResult defaults.
  G) DecisionExecutor.execute — observe / hint → noop (fast path).
  H) DecisionExecutor.execute — disabled (enable_system_actions=false).
  I) DecisionExecutor.execute — assist: no target configured.
  J) DecisionExecutor.execute — assist: target configured, focus succeeds.
  K) DecisionExecutor.execute — assist: focus fails, launch triggered.
  L) DecisionExecutor.execute — execute: no target → noop.
  M) DecisionExecutor.execute — execute: target not in allowlist → blocked.
  N) DecisionExecutor.execute — execute: allowlisted target → launched.
  O) DecisionExecutor.execute — internal error is swallowed, returns ExecutionResult.
  P) DecisionExecutor._get_policy caches the PolicyGate.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

from core.execution.decision_executor import (
    DecisionExecutor,
    ExecutionResult,
    PolicyGate,
    _extract_action_level,
    _extract_execution_target,
)
from core.system_api.platform_api import AppLaunchResult, NoOpSystemAPI


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_continuum(action_level: str = "observe", execution_target: Optional[str] = None) -> Dict[str, Any]:
    state: Dict[str, Any] = {
        "phase": "formless",
        "decision": {"action_level": action_level, "should_act_score": 0.5},
        "metadata": {},
    }
    if execution_target is not None:
        state["metadata"]["execution_target"] = execution_target
    return state


def _make_executor(
    enabled: bool = False,
    allowlist: Optional[list] = None,
    assist_app: Optional[str] = None,
    system_api=None,
) -> DecisionExecutor:
    executor = DecisionExecutor()
    executor._policy = PolicyGate(enabled=enabled, allowlist=allowlist or [])

    if system_api is not None:
        executor._get_system_api = lambda: system_api  # type: ignore[method-assign]

    if assist_app is not None:
        executor._get_assist_app = lambda: assist_app  # type: ignore[method-assign]
    else:
        executor._get_assist_app = lambda: None  # type: ignore[method-assign]

    return executor


# ---------------------------------------------------------------------------
# A) _extract_action_level
# ---------------------------------------------------------------------------

class TestExtractActionLevel:
    def test_none_returns_observe(self):
        assert _extract_action_level(None) == "observe"

    def test_empty_dict_returns_observe(self):
        assert _extract_action_level({}) == "observe"

    def test_missing_decision_returns_observe(self):
        assert _extract_action_level({"phase": "formless"}) == "observe"

    def test_decision_with_action_level(self):
        state = {"decision": {"action_level": "execute"}}
        assert _extract_action_level(state) == "execute"

    def test_all_valid_levels(self):
        for level in ("observe", "hint", "assist", "execute"):
            state = {"decision": {"action_level": level}}
            assert _extract_action_level(state) == level

    def test_non_dict_returns_observe(self):
        assert _extract_action_level("not a dict") == "observe"  # type: ignore[arg-type]

    def test_missing_action_level_key_returns_observe(self):
        assert _extract_action_level({"decision": {}}) == "observe"


# ---------------------------------------------------------------------------
# B) _extract_execution_target
# ---------------------------------------------------------------------------

class TestExtractExecutionTarget:
    def test_none_returns_none(self):
        assert _extract_execution_target(None) is None

    def test_missing_metadata_returns_none(self):
        assert _extract_execution_target({"phase": "formless"}) is None

    def test_target_present(self):
        state = {"metadata": {"execution_target": "notepad.exe"}}
        assert _extract_execution_target(state) == "notepad.exe"

    def test_empty_target_returns_none(self):
        state = {"metadata": {"execution_target": ""}}
        assert _extract_execution_target(state) is None

    def test_null_target_returns_none(self):
        state = {"metadata": {"execution_target": None}}
        assert _extract_execution_target(state) is None


# ---------------------------------------------------------------------------
# C) PolicyGate construction and is_enabled
# ---------------------------------------------------------------------------

class TestPolicyGateConstruction:
    def test_default_disabled(self):
        pg = PolicyGate()
        assert not pg.is_enabled

    def test_enabled_true(self):
        pg = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        assert pg.is_enabled

    def test_allowlist_none_defaults_to_empty(self):
        pg = PolicyGate(enabled=True, allowlist=None)
        assert not pg.allows("notepad.exe")


# ---------------------------------------------------------------------------
# D) PolicyGate.allows
# ---------------------------------------------------------------------------

class TestPolicyGateAllows:
    def test_disabled_always_denies(self):
        pg = PolicyGate(enabled=False, allowlist=["notepad.exe"])
        assert not pg.allows("notepad.exe")

    def test_empty_allowlist_denies(self):
        pg = PolicyGate(enabled=True, allowlist=[])
        assert not pg.allows("notepad.exe")

    def test_exact_match(self):
        pg = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        assert pg.allows("notepad.exe")

    def test_case_insensitive(self):
        pg = PolicyGate(enabled=True, allowlist=["NOTEPAD.EXE"])
        assert pg.allows("notepad.exe")

    def test_prefix_match(self):
        pg = PolicyGate(enabled=True, allowlist=["https://"])
        assert pg.allows("https://example.com")

    def test_no_prefix_match(self):
        pg = PolicyGate(enabled=True, allowlist=["notepad.exe"])
        assert not pg.allows("calc.exe")


# ---------------------------------------------------------------------------
# E) PolicyGate.check_action_level
# ---------------------------------------------------------------------------

class TestPolicyGateCheckActionLevel:
    def test_observe_false(self):
        pg = PolicyGate()
        assert not pg.check_action_level("observe")

    def test_hint_false(self):
        assert not PolicyGate().check_action_level("hint")

    def test_assist_true(self):
        assert PolicyGate().check_action_level("assist")

    def test_execute_true(self):
        assert PolicyGate().check_action_level("execute")


# ---------------------------------------------------------------------------
# F) ExecutionResult defaults
# ---------------------------------------------------------------------------

class TestExecutionResultDefaults:
    def test_defaults(self):
        r = ExecutionResult()
        assert r.action_taken == "none"
        assert r.target is None
        assert not r.success
        assert r.skipped_reason is None
        assert r.metadata == {}


# ---------------------------------------------------------------------------
# G) observe / hint → noop fast path
# ---------------------------------------------------------------------------

class TestNoopFastPath:
    @pytest.mark.parametrize("level", ["observe", "hint"])
    def test_noop(self, level):
        executor = DecisionExecutor()
        result = executor.execute(_make_continuum(action_level=level))
        assert result.action_taken == "noop"
        assert result.success

    def test_none_state_returns_noop(self):
        executor = DecisionExecutor()
        result = executor.execute(None)
        assert result.action_taken == "noop"
        assert result.success


# ---------------------------------------------------------------------------
# H) Disabled (enable_system_actions=false)
# ---------------------------------------------------------------------------

class TestDisabledExecution:
    def test_assist_disabled(self):
        executor = _make_executor(enabled=False)
        result = executor.execute(_make_continuum(action_level="assist"))
        assert result.action_taken == "noop"
        assert result.skipped_reason == "enable_system_actions=false"

    def test_execute_disabled(self):
        executor = _make_executor(enabled=False)
        result = executor.execute(_make_continuum(action_level="execute"))
        assert result.action_taken == "noop"
        assert result.skipped_reason == "enable_system_actions=false"


# ---------------------------------------------------------------------------
# I) assist: no target configured → noop
# ---------------------------------------------------------------------------

class TestAssistNoTarget:
    def test_no_assist_app_configured(self):
        api = NoOpSystemAPI()
        executor = _make_executor(enabled=True, allowlist=["anything"], system_api=api)
        result = executor.execute(_make_continuum(action_level="assist"))
        assert result.action_taken == "noop"
        assert result.skipped_reason == "no_assist_target_configured"


# ---------------------------------------------------------------------------
# J) assist: target configured, focus succeeds
# ---------------------------------------------------------------------------

class TestAssistFocusSucceeds:
    def test_focus_window_called(self):
        api = MagicMock()
        api.focus_window.return_value = True
        executor = _make_executor(
            enabled=True,
            allowlist=["notepad.exe"],
            assist_app="notepad.exe",
            system_api=api,
        )
        result = executor.execute(_make_continuum(action_level="assist"))
        assert result.action_taken == "focus_window"
        assert result.target == "notepad.exe"
        assert result.success
        api.focus_window.assert_called_once_with("notepad.exe")


# ---------------------------------------------------------------------------
# K) assist: focus fails, launch triggered
# ---------------------------------------------------------------------------

class TestAssistFocusFallbackToLaunch:
    def test_launch_called_when_focus_fails(self):
        api = MagicMock()
        api.focus_window.return_value = False
        api.launch_app.return_value = AppLaunchResult(success=True, pid=1234)
        executor = _make_executor(
            enabled=True,
            allowlist=["notepad.exe"],
            assist_app="notepad.exe",
            system_api=api,
        )
        result = executor.execute(_make_continuum(action_level="assist"))
        assert result.action_taken == "launch_app"
        assert result.success
        api.launch_app.assert_called_once_with("notepad.exe")


# ---------------------------------------------------------------------------
# L) execute: no target → noop
# ---------------------------------------------------------------------------

class TestExecuteNoTarget:
    def test_no_target_noop(self):
        api = MagicMock()
        executor = _make_executor(
            enabled=True,
            allowlist=["notepad.exe"],
            system_api=api,
        )
        result = executor.execute(_make_continuum(action_level="execute"))
        assert result.action_taken == "noop"
        assert result.skipped_reason == "no_execution_target"
        api.launch_app.assert_not_called()


# ---------------------------------------------------------------------------
# M) execute: target not in allowlist → blocked
# ---------------------------------------------------------------------------

class TestExecuteNotAllowlisted:
    def test_blocked(self):
        api = MagicMock()
        executor = _make_executor(
            enabled=True,
            allowlist=["calc.exe"],
            system_api=api,
        )
        result = executor.execute(_make_continuum(action_level="execute", execution_target="notepad.exe"))
        assert result.action_taken == "noop"
        assert not result.success
        assert "notepad.exe" in (result.skipped_reason or "")
        api.launch_app.assert_not_called()


# ---------------------------------------------------------------------------
# N) execute: allowlisted target → launched
# ---------------------------------------------------------------------------

class TestExecuteAllowlisted:
    def test_launched(self):
        api = MagicMock()
        api.launch_app.return_value = AppLaunchResult(success=True, pid=42)
        executor = _make_executor(
            enabled=True,
            allowlist=["notepad.exe"],
            system_api=api,
        )
        result = executor.execute(_make_continuum(action_level="execute", execution_target="notepad.exe"))
        assert result.action_taken == "launch_app"
        assert result.target == "notepad.exe"
        assert result.success
        api.launch_app.assert_called_once_with("notepad.exe")


# ---------------------------------------------------------------------------
# O) Internal error is swallowed
# ---------------------------------------------------------------------------

class TestErrorIsolation:
    def test_exception_swallowed(self):
        executor = DecisionExecutor()
        executor._execute_inner = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
        result = executor.execute(_make_continuum(action_level="execute"))
        assert result.action_taken == "error"
        assert not result.success
        assert "boom" in (result.skipped_reason or "")


# ---------------------------------------------------------------------------
# P) _get_policy caches the PolicyGate
# ---------------------------------------------------------------------------

class TestPolicyCache:
    def test_same_instance_returned(self):
        executor = DecisionExecutor()
        # Call _get_policy twice; the returned object should be the same instance
        with patch("core.unified_config.config", {"enable_system_actions": False, "execution_app_allowlist": []}):
            pg1 = executor._get_policy()
            pg2 = executor._get_policy()
            assert pg1 is pg2

    def test_policy_cached_after_first_call(self):
        executor = DecisionExecutor()
        with patch("core.unified_config.config", {"enable_system_actions": False, "execution_app_allowlist": []}):
            pg1 = executor._get_policy()
            pg2 = executor._get_policy()
            assert pg1 is pg2
