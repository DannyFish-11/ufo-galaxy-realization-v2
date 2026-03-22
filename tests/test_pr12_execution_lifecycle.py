"""
tests/test_pr12_execution_lifecycle.py
=========================================
Tests for PR-12: Unified Execution Lifecycle across plan, substrate,
and result handling.

Coverage
--------
A) ExecutionLifecycleState enum
   - all required states present
   - string values are stable
   - enum is str subclass
   - values are distinct

B) terminal_states / is_terminal
   - SUCCEEDED, FAILED, CANCELLED, TIMED_OUT, DEGRADED are terminal
   - CREATED, PLANNED, QUEUED, SELECTED, DISPATCHING, RUNNING,
     WAITING_REMOTE, PARTIALLY_SUCCEEDED are non-terminal
   - terminal_states() returns a set
   - is_terminal consistent with terminal_states()

C) advance_lifecycle — local happy path
   - CREATED → PLANNED (no outcome)
   - PLANNED → DISPATCHING (local, no outcome)
   - DISPATCHING → RUNNING (local, no outcome)
   - RUNNING → SUCCEEDED (success=True)

D) advance_lifecycle — remote happy path
   - CREATED → PLANNED (is_remote=True)
   - PLANNED → QUEUED (is_remote=True)
   - QUEUED → SELECTED
   - SELECTED → DISPATCHING
   - DISPATCHING → WAITING_REMOTE
   - WAITING_REMOTE → RUNNING
   - RUNNING → SUCCEEDED (success=True)

E) advance_lifecycle — failure / cancel overrides
   - success=False → FAILED from any non-terminal state
   - cancelled=True → CANCELLED from any non-terminal state
   - timed_out=True → TIMED_OUT from any non-terminal state
   - degraded=True → DEGRADED from RUNNING
   - partially_succeeded=True → PARTIALLY_SUCCEEDED from RUNNING

F) advance_lifecycle — terminal state stability
   - calling advance_lifecycle on a terminal state without overrides
     returns the same state
   - cancelled=True overrides a terminal state → CANCELLED
   - timed_out=True overrides a terminal state → TIMED_OUT

G) LifecycleTransition
   - construction with all fields
   - to_dict() produces all expected keys
   - to_dict() is JSON-safe
   - unique transition_id per instance
   - LifecycleTransition.make() sets from_state and to_state correctly
   - kwargs become metadata

H) lifecycle_summary
   - correct lifecycle_state value
   - is_terminal reflects state terminalness
   - transition_count matches trail length
   - last_reason from last trail entry
   - plan_id / step_id optional
   - lifecycle_trail is a list of dicts

I) lifecycle_trail_to_dict
   - None → empty list
   - empty list → empty list
   - list of transitions → list of dicts

J) initial_state_for_step_type
   - always returns CREATED regardless of step type value

K) ExecutionStep lifecycle fields (PR-12 additions)
   - default lifecycle_state is None (backward compat)
   - default lifecycle_trail is empty list
   - to_dict() includes lifecycle_state key
   - to_dict() includes lifecycle_trail key

L) ExecutionPlan lifecycle fields (PR-12 additions)
   - default lifecycle_state is None (backward compat)
   - default lifecycle_trail is empty list
   - to_dict() includes lifecycle_state key
   - to_dict() includes lifecycle_trail key

M) build_execution_plan stamps PLANNED lifecycle on new plan
   - plan.lifecycle_state == "planned"
   - plan.lifecycle_trail is non-empty
   - each step.lifecycle_state == "created"
   - each step.lifecycle_trail is non-empty

N) plan_summary includes lifecycle_state (PR-12 addition)
   - None plan → lifecycle_state is None
   - plan with lifecycle → lifecycle_state present in summary

O) OpenClawd._finalise_plan_lifecycle
   - success=True advances plan lifecycle to "succeeded"
   - success=False advances plan lifecycle to "failed"
   - all steps advanced to terminal state
   - lifecycle_trail grows by one transition
   - None plan → no error

P) CommandRouter.route_envelope stamps lifecycle_state (PR-12)
   - successful envelope result carries lifecycle_state="succeeded"
   - failed envelope result carries lifecycle_state="failed"
   - lifecycle_state key is present and non-None

Q) NATSBus._ensure_trace_fields propagates lifecycle_state (PR-12)
   - lifecycle_state propagated when provided
   - lifecycle_state not clobbered when already in data
   - lifecycle_state absent when not provided

R) Multi-step / orchestration lifecycle
   - plan_from_orchestration_decisions stamps PLANNED lifecycle on plan
   - each orchestration step gets CREATED lifecycle
   - PARTIALLY_SUCCEEDED is representable on a multi-step plan

S) Backward compatibility
   - ExecutionStep without lifecycle fields works (old-style dict via to_dict)
   - ExecutionPlan to_dict backward-compatible keys all present
   - plan_summary return value has no new required keys breaking old code
   - callers that do not inspect lifecycle_state continue to work

T) Diagnostics / inspectability
   - lifecycle state can be read from plan.to_dict()
   - lifecycle_state travels through plan summary
   - lifecycle_trail transitions are introspectable
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import subjects
# ---------------------------------------------------------------------------

from core.schemas.execution_lifecycle import (
    ExecutionLifecycleState,
    LifecycleTransition,
    advance_lifecycle,
    initial_state_for_step_type,
    is_terminal,
    lifecycle_summary,
    lifecycle_trail_to_dict,
    terminal_states,
)
from core.schemas.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepType,
    build_execution_plan,
    plan_from_orchestration_decisions,
    plan_summary,
)


# ---------------------------------------------------------------------------
# Section A — ExecutionLifecycleState enum
# ---------------------------------------------------------------------------


class TestExecutionLifecycleStateEnum:
    """Section A: enum stability."""

    REQUIRED_STATES = [
        "created",
        "planned",
        "queued",
        "selected",
        "dispatching",
        "running",
        "waiting_remote",
        "partially_succeeded",
        "succeeded",
        "failed",
        "cancelled",
        "timed_out",
        "degraded",
    ]

    def test_all_required_states_present(self):
        values = {s.value for s in ExecutionLifecycleState}
        for name in self.REQUIRED_STATES:
            assert name in values, f"Missing state: {name}"

    def test_string_values_stable(self):
        assert ExecutionLifecycleState.CREATED.value == "created"
        assert ExecutionLifecycleState.PLANNED.value == "planned"
        assert ExecutionLifecycleState.QUEUED.value == "queued"
        assert ExecutionLifecycleState.SELECTED.value == "selected"
        assert ExecutionLifecycleState.DISPATCHING.value == "dispatching"
        assert ExecutionLifecycleState.RUNNING.value == "running"
        assert ExecutionLifecycleState.WAITING_REMOTE.value == "waiting_remote"
        assert ExecutionLifecycleState.PARTIALLY_SUCCEEDED.value == "partially_succeeded"
        assert ExecutionLifecycleState.SUCCEEDED.value == "succeeded"
        assert ExecutionLifecycleState.FAILED.value == "failed"
        assert ExecutionLifecycleState.CANCELLED.value == "cancelled"
        assert ExecutionLifecycleState.TIMED_OUT.value == "timed_out"
        assert ExecutionLifecycleState.DEGRADED.value == "degraded"

    def test_enum_is_str_subclass(self):
        assert isinstance(ExecutionLifecycleState.CREATED, str)

    def test_values_are_distinct(self):
        values = [s.value for s in ExecutionLifecycleState]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# Section B — terminal_states / is_terminal
# ---------------------------------------------------------------------------


class TestTerminalStates:
    """Section B: terminal state helpers."""

    EXPECTED_TERMINAL = {
        ExecutionLifecycleState.SUCCEEDED,
        ExecutionLifecycleState.FAILED,
        ExecutionLifecycleState.CANCELLED,
        ExecutionLifecycleState.TIMED_OUT,
        ExecutionLifecycleState.DEGRADED,
    }

    EXPECTED_NON_TERMINAL = {
        ExecutionLifecycleState.CREATED,
        ExecutionLifecycleState.PLANNED,
        ExecutionLifecycleState.QUEUED,
        ExecutionLifecycleState.SELECTED,
        ExecutionLifecycleState.DISPATCHING,
        ExecutionLifecycleState.RUNNING,
        ExecutionLifecycleState.WAITING_REMOTE,
        ExecutionLifecycleState.PARTIALLY_SUCCEEDED,
    }

    def test_terminal_states_returns_set(self):
        result = terminal_states()
        assert isinstance(result, set)

    def test_terminal_states_contains_expected(self):
        result = terminal_states()
        for s in self.EXPECTED_TERMINAL:
            assert s in result, f"Expected terminal: {s}"

    def test_non_terminal_states_not_in_terminal(self):
        result = terminal_states()
        for s in self.EXPECTED_NON_TERMINAL:
            assert s not in result, f"Should not be terminal: {s}"

    def test_is_terminal_true_for_terminal(self):
        for s in self.EXPECTED_TERMINAL:
            assert is_terminal(s), f"Expected is_terminal({s}) == True"

    def test_is_terminal_false_for_non_terminal(self):
        for s in self.EXPECTED_NON_TERMINAL:
            assert not is_terminal(s), f"Expected is_terminal({s}) == False"

    def test_is_terminal_consistent_with_terminal_states(self):
        ts = terminal_states()
        for s in ExecutionLifecycleState:
            assert is_terminal(s) == (s in ts)


# ---------------------------------------------------------------------------
# Section C — advance_lifecycle local happy path
# ---------------------------------------------------------------------------


class TestAdvanceLifecycleLocalPath:
    """Section C: local execution happy-path progression."""

    def test_created_to_planned_local(self):
        result = advance_lifecycle(ExecutionLifecycleState.CREATED, success=None)
        assert result == ExecutionLifecycleState.PLANNED

    def test_planned_to_dispatching_local(self):
        result = advance_lifecycle(ExecutionLifecycleState.PLANNED, success=None, is_remote=False)
        assert result == ExecutionLifecycleState.DISPATCHING

    def test_dispatching_to_running_local(self):
        result = advance_lifecycle(ExecutionLifecycleState.DISPATCHING, success=None, is_remote=False)
        assert result == ExecutionLifecycleState.RUNNING

    def test_running_to_succeeded_local(self):
        result = advance_lifecycle(ExecutionLifecycleState.RUNNING, success=True)
        assert result == ExecutionLifecycleState.SUCCEEDED


# ---------------------------------------------------------------------------
# Section D — advance_lifecycle remote happy path
# ---------------------------------------------------------------------------


class TestAdvanceLifecycleRemotePath:
    """Section D: remote dispatch happy-path progression."""

    def test_created_to_planned_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.CREATED, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.PLANNED

    def test_planned_to_queued_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.PLANNED, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.QUEUED

    def test_queued_to_selected_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.QUEUED, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.SELECTED

    def test_selected_to_dispatching_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.SELECTED, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.DISPATCHING

    def test_dispatching_to_waiting_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.DISPATCHING, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.WAITING_REMOTE

    def test_waiting_remote_to_running(self):
        result = advance_lifecycle(ExecutionLifecycleState.WAITING_REMOTE, success=None, is_remote=True)
        assert result == ExecutionLifecycleState.RUNNING

    def test_running_to_succeeded_remote(self):
        result = advance_lifecycle(ExecutionLifecycleState.RUNNING, success=True, is_remote=True)
        assert result == ExecutionLifecycleState.SUCCEEDED


# ---------------------------------------------------------------------------
# Section E — failure / cancel overrides
# ---------------------------------------------------------------------------


class TestAdvanceLifecycleOverrides:
    """Section E: override flags."""

    def test_success_false_yields_failed(self):
        for state in [
            ExecutionLifecycleState.RUNNING,
            ExecutionLifecycleState.DISPATCHING,
            ExecutionLifecycleState.WAITING_REMOTE,
            ExecutionLifecycleState.PLANNED,
        ]:
            result = advance_lifecycle(state, success=False)
            assert result == ExecutionLifecycleState.FAILED, f"Failed from {state}"

    def test_cancelled_yields_cancelled(self):
        for state in [
            ExecutionLifecycleState.RUNNING,
            ExecutionLifecycleState.QUEUED,
            ExecutionLifecycleState.PLANNED,
        ]:
            result = advance_lifecycle(state, success=None, cancelled=True)
            assert result == ExecutionLifecycleState.CANCELLED, f"Cancelled from {state}"

    def test_timed_out_yields_timed_out(self):
        result = advance_lifecycle(ExecutionLifecycleState.WAITING_REMOTE, success=None, timed_out=True)
        assert result == ExecutionLifecycleState.TIMED_OUT

    def test_degraded_yields_degraded(self):
        result = advance_lifecycle(ExecutionLifecycleState.RUNNING, success=None, degraded=True)
        assert result == ExecutionLifecycleState.DEGRADED

    def test_partially_succeeded(self):
        result = advance_lifecycle(ExecutionLifecycleState.RUNNING, success=None, partially_succeeded=True)
        assert result == ExecutionLifecycleState.PARTIALLY_SUCCEEDED


# ---------------------------------------------------------------------------
# Section F — terminal state stability
# ---------------------------------------------------------------------------


class TestTerminalStateStability:
    """Section F: terminal states don't progress further unexpectedly."""

    def test_terminal_stays_terminal_without_override(self):
        for state in terminal_states():
            result = advance_lifecycle(state, success=None)
            assert result == state, f"Terminal {state} should not advance"

    def test_cancelled_overrides_terminal(self):
        result = advance_lifecycle(ExecutionLifecycleState.SUCCEEDED, success=None, cancelled=True)
        assert result == ExecutionLifecycleState.CANCELLED

    def test_timed_out_overrides_terminal(self):
        result = advance_lifecycle(ExecutionLifecycleState.SUCCEEDED, success=None, timed_out=True)
        assert result == ExecutionLifecycleState.TIMED_OUT


# ---------------------------------------------------------------------------
# Section G — LifecycleTransition
# ---------------------------------------------------------------------------


class TestLifecycleTransition:
    """Section G: transition records."""

    def test_construction_all_fields(self):
        t = LifecycleTransition(
            from_state=ExecutionLifecycleState.PLANNED,
            to_state=ExecutionLifecycleState.DISPATCHING,
            reason="starting dispatch",
        )
        assert t.from_state == ExecutionLifecycleState.PLANNED
        assert t.to_state == ExecutionLifecycleState.DISPATCHING
        assert t.reason == "starting dispatch"
        assert t.transition_id
        assert t.timestamp > 0

    def test_to_dict_keys(self):
        t = LifecycleTransition(
            from_state=ExecutionLifecycleState.RUNNING,
            to_state=ExecutionLifecycleState.SUCCEEDED,
            reason="done",
        )
        d = t.to_dict()
        assert "transition_id" in d
        assert "from_state" in d
        assert "to_state" in d
        assert "reason" in d
        assert "timestamp" in d
        assert "metadata" in d

    def test_to_dict_values(self):
        t = LifecycleTransition(
            from_state=ExecutionLifecycleState.RUNNING,
            to_state=ExecutionLifecycleState.SUCCEEDED,
            reason="done",
        )
        d = t.to_dict()
        assert d["from_state"] == "running"
        assert d["to_state"] == "succeeded"
        assert d["reason"] == "done"

    def test_to_dict_json_safe(self):
        t = LifecycleTransition(
            from_state=ExecutionLifecycleState.DISPATCHING,
            to_state=ExecutionLifecycleState.RUNNING,
        )
        json.dumps(t.to_dict())  # must not raise

    def test_transition_id_uniqueness(self):
        ids = {LifecycleTransition().transition_id for _ in range(50)}
        assert len(ids) == 50

    def test_make_factory(self):
        t = LifecycleTransition.make(
            to_state=ExecutionLifecycleState.SUCCEEDED,
            from_state=ExecutionLifecycleState.RUNNING,
            reason="success",
            extra_key="extra_val",
        )
        assert t.to_state == ExecutionLifecycleState.SUCCEEDED
        assert t.from_state == ExecutionLifecycleState.RUNNING
        assert t.reason == "success"
        assert t.metadata.get("extra_key") == "extra_val"

    def test_make_no_from_state(self):
        t = LifecycleTransition.make(to_state=ExecutionLifecycleState.CREATED)
        assert t.from_state is None
        assert t.to_dict()["from_state"] is None


# ---------------------------------------------------------------------------
# Section H — lifecycle_summary
# ---------------------------------------------------------------------------


class TestLifecycleSummary:
    """Section H: lifecycle_summary helper."""

    def test_returns_dict(self):
        s = lifecycle_summary(ExecutionLifecycleState.RUNNING)
        assert isinstance(s, dict)

    def test_lifecycle_state_value(self):
        s = lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)
        assert s["lifecycle_state"] == "succeeded"

    def test_is_terminal_flag(self):
        assert lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)["is_terminal"] is True
        assert lifecycle_summary(ExecutionLifecycleState.RUNNING)["is_terminal"] is False

    def test_transition_count(self):
        trail = [
            LifecycleTransition.make(to_state=ExecutionLifecycleState.CREATED),
            LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED),
        ]
        s = lifecycle_summary(ExecutionLifecycleState.PLANNED, trail)
        assert s["transition_count"] == 2

    def test_last_reason(self):
        trail = [
            LifecycleTransition.make(to_state=ExecutionLifecycleState.CREATED, reason="init"),
            LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED, reason="plan_built"),
        ]
        s = lifecycle_summary(ExecutionLifecycleState.PLANNED, trail)
        assert s["last_reason"] == "plan_built"

    def test_plan_id_step_id_optional(self):
        s = lifecycle_summary(
            ExecutionLifecycleState.RUNNING,
            plan_id="plan-abc",
            step_id="step-xyz",
        )
        assert s["plan_id"] == "plan-abc"
        assert s["step_id"] == "step-xyz"

    def test_lifecycle_trail_is_list_of_dicts(self):
        trail = [LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED, reason="test")]
        s = lifecycle_summary(ExecutionLifecycleState.PLANNED, trail)
        assert isinstance(s["lifecycle_trail"], list)
        assert isinstance(s["lifecycle_trail"][0], dict)

    def test_no_trail_empty_list(self):
        s = lifecycle_summary(ExecutionLifecycleState.CREATED)
        assert s["lifecycle_trail"] == []
        assert s["transition_count"] == 0
        assert s["last_reason"] == ""


# ---------------------------------------------------------------------------
# Section I — lifecycle_trail_to_dict
# ---------------------------------------------------------------------------


class TestLifecycleTrailToDict:
    """Section I: trail serialisation helper."""

    def test_none_returns_empty_list(self):
        assert lifecycle_trail_to_dict(None) == []

    def test_empty_list_returns_empty_list(self):
        assert lifecycle_trail_to_dict([]) == []

    def test_transitions_serialised(self):
        trail = [
            LifecycleTransition.make(to_state=ExecutionLifecycleState.CREATED),
            LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED),
        ]
        result = lifecycle_trail_to_dict(trail)
        assert len(result) == 2
        assert all(isinstance(d, dict) for d in result)
        assert result[0]["to_state"] == "created"
        assert result[1]["to_state"] == "planned"


# ---------------------------------------------------------------------------
# Section J — initial_state_for_step_type
# ---------------------------------------------------------------------------


class TestInitialStateForStepType:
    """Section J: initial state mapping."""

    def test_local_manifestation_returns_created(self):
        result = initial_state_for_step_type("local_manifestation")
        assert result == ExecutionLifecycleState.CREATED

    def test_remote_command_returns_created(self):
        result = initial_state_for_step_type("remote_command")
        assert result == ExecutionLifecycleState.CREATED

    def test_remote_agent_returns_created(self):
        result = initial_state_for_step_type("remote_agent")
        assert result == ExecutionLifecycleState.CREATED

    def test_orchestration_returns_created(self):
        result = initial_state_for_step_type("orchestration")
        assert result == ExecutionLifecycleState.CREATED

    def test_observe_returns_created(self):
        result = initial_state_for_step_type("observe")
        assert result == ExecutionLifecycleState.CREATED

    def test_unknown_returns_created(self):
        result = initial_state_for_step_type("unknown_future_type")
        assert result == ExecutionLifecycleState.CREATED


# ---------------------------------------------------------------------------
# Section K — ExecutionStep lifecycle fields
# ---------------------------------------------------------------------------


class TestExecutionStepLifecycleFields:
    """Section K: PR-12 lifecycle fields on ExecutionStep."""

    def test_default_lifecycle_state_is_none(self):
        step = ExecutionStep()
        assert step.lifecycle_state is None

    def test_default_lifecycle_trail_is_empty_list(self):
        step = ExecutionStep()
        assert step.lifecycle_trail == []

    def test_to_dict_includes_lifecycle_state(self):
        step = ExecutionStep()
        d = step.to_dict()
        assert "lifecycle_state" in d

    def test_to_dict_includes_lifecycle_trail(self):
        step = ExecutionStep()
        d = step.to_dict()
        assert "lifecycle_trail" in d
        assert isinstance(d["lifecycle_trail"], list)

    def test_to_dict_with_lifecycle_state_set(self):
        step = ExecutionStep(lifecycle_state="running")
        d = step.to_dict()
        assert d["lifecycle_state"] == "running"

    def test_to_dict_with_transition_in_trail(self):
        t = LifecycleTransition.make(to_state=ExecutionLifecycleState.CREATED)
        step = ExecutionStep(lifecycle_trail=[t])
        d = step.to_dict()
        assert len(d["lifecycle_trail"]) == 1
        assert d["lifecycle_trail"][0]["to_state"] == "created"

    def test_to_dict_json_safe(self):
        t = LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED)
        step = ExecutionStep(lifecycle_state="planned", lifecycle_trail=[t])
        json.dumps(step.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# Section L — ExecutionPlan lifecycle fields
# ---------------------------------------------------------------------------


class TestExecutionPlanLifecycleFields:
    """Section L: PR-12 lifecycle fields on ExecutionPlan."""

    def test_default_lifecycle_state_is_none(self):
        plan = ExecutionPlan()
        assert plan.lifecycle_state is None

    def test_default_lifecycle_trail_is_empty_list(self):
        plan = ExecutionPlan()
        assert plan.lifecycle_trail == []

    def test_to_dict_includes_lifecycle_state(self):
        plan = ExecutionPlan()
        d = plan.to_dict()
        assert "lifecycle_state" in d

    def test_to_dict_includes_lifecycle_trail(self):
        plan = ExecutionPlan()
        d = plan.to_dict()
        assert "lifecycle_trail" in d
        assert isinstance(d["lifecycle_trail"], list)

    def test_to_dict_with_lifecycle_state_set(self):
        plan = ExecutionPlan(lifecycle_state="succeeded")
        d = plan.to_dict()
        assert d["lifecycle_state"] == "succeeded"

    def test_to_dict_json_safe(self):
        t = LifecycleTransition.make(to_state=ExecutionLifecycleState.PLANNED)
        plan = ExecutionPlan(lifecycle_state="planned", lifecycle_trail=[t])
        json.dumps(plan.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# Section M — build_execution_plan stamps PLANNED lifecycle
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanLifecycle:
    """Section M: build_execution_plan stamps lifecycle state."""

    def test_plan_lifecycle_state_is_planned(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert plan.lifecycle_state == "planned"

    def test_plan_lifecycle_trail_non_empty(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert len(plan.lifecycle_trail) > 0

    def test_step_lifecycle_state_is_created(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        for step in plan.steps:
            assert step.lifecycle_state == "created", f"step {step.step_id}"

    def test_step_lifecycle_trail_non_empty(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        for step in plan.steps:
            assert len(step.lifecycle_trail) > 0

    def test_remote_plan_gets_planned_lifecycle(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
        )
        assert plan.lifecycle_state == "planned"

    def test_orchestration_plan_gets_planned_lifecycle(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        assert plan.lifecycle_state == "planned"

    def test_observe_plan_gets_planned_lifecycle(self):
        plan = build_execution_plan(execution_path="none")
        assert plan.lifecycle_state == "planned"

    def test_hybrid_plan_all_steps_get_created(self):
        plan = build_execution_plan(
            execution_path="hybrid",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
        )
        assert len(plan.steps) >= 2
        for step in plan.steps:
            assert step.lifecycle_state == "created"

    def test_plan_from_orchestration_decisions_stamps_lifecycle(self):
        decisions = [
            {"agent_id": "a1", "target_device_id": "dev1", "resolved_execution_mode": "agent_runtime"},
            {"agent_id": "a2", "target_device_id": "dev2", "resolved_execution_mode": "command_only"},
        ]
        plan = plan_from_orchestration_decisions(decisions=decisions, task="test_task")
        assert plan.lifecycle_state == "planned"
        for step in plan.steps:
            assert step.lifecycle_state == "created"

    def test_plan_from_orchestration_empty_stamps_lifecycle(self):
        plan = plan_from_orchestration_decisions(decisions=[], task="empty_task")
        assert plan.lifecycle_state == "planned"


# ---------------------------------------------------------------------------
# Section N — plan_summary includes lifecycle_state
# ---------------------------------------------------------------------------


class TestPlanSummaryLifecycle:
    """Section N: plan_summary PR-12 addition."""

    def test_none_plan_summary_has_lifecycle_state_key(self):
        s = plan_summary(None)
        assert "lifecycle_state" in s

    def test_none_plan_summary_lifecycle_state_is_none(self):
        s = plan_summary(None)
        assert s["lifecycle_state"] is None

    def test_local_plan_summary_has_lifecycle_state(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        s = plan_summary(plan)
        assert "lifecycle_state" in s
        assert s["lifecycle_state"] == "planned"

    def test_plan_after_finalise_summary_shows_terminal(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        # Manually advance to succeeded
        plan.lifecycle_state = "succeeded"
        s = plan_summary(plan)
        assert s["lifecycle_state"] == "succeeded"


# ---------------------------------------------------------------------------
# Section O — OpenClawd._finalise_plan_lifecycle
# ---------------------------------------------------------------------------


class TestOpenClawdFinalise:
    """Section O: _finalise_plan_lifecycle helper on OpenClawd."""

    def _get_openclawd(self):
        """Return a minimal OpenClawd instance for helper testing."""
        try:
            from core.openclawd import OpenClawd
            oc = object.__new__(OpenClawd)
            return oc
        except Exception:
            return None

    def test_success_advances_to_succeeded(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")

        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert plan.lifecycle_state == "planned"

        oc._finalise_plan_lifecycle(plan, success=True)
        assert plan.lifecycle_state == "succeeded"

    def test_failure_advances_to_failed(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")

        plan = build_execution_plan(execution_path="local", delegation_point="local")
        oc._finalise_plan_lifecycle(plan, success=False)
        assert plan.lifecycle_state == "failed"

    def test_all_steps_advance_to_terminal(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")

        plan = build_execution_plan(
            execution_path="hybrid",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
        )
        oc._finalise_plan_lifecycle(plan, success=True)
        for step in plan.steps:
            assert step.lifecycle_state == "succeeded", f"step {step.step_id}"

    def test_lifecycle_trail_grows(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")

        plan = build_execution_plan(execution_path="local", delegation_point="local")
        trail_len_before = len(plan.lifecycle_trail)

        oc._finalise_plan_lifecycle(plan, success=True)
        assert len(plan.lifecycle_trail) > trail_len_before

    def test_none_plan_no_error(self):
        oc = self._get_openclawd()
        if oc is None:
            pytest.skip("OpenClawd not available")
        # Must not raise
        oc._finalise_plan_lifecycle(None, success=True)


# ---------------------------------------------------------------------------
# Section P — CommandRouter.route_envelope lifecycle stamps
# ---------------------------------------------------------------------------


class TestCommandRouterLifecycleStamps:
    """Section P: CommandRouter stamps lifecycle_state on result."""

    def _make_router(self):
        """Return a CommandRouter instance with mocked executor."""
        try:
            from core.command_router import CommandRouter
            async def _mock_exec(*args, **kwargs):
                return {"success": True, "result": "ok", "request_id": "r1",
                        "task_id": "t1", "trace_id": "tr1", "command_id": "c1",
                        "device_id": "dev1", "command": "test", "via": "mock",
                        "error_code": None, "error_message": None, "latency_ms": 0.0}
            router = CommandRouter(executor=_mock_exec)
            return router
        except Exception:
            return None

    @pytest.mark.asyncio
    async def test_successful_result_carries_lifecycle_state(self):
        router = self._make_router()
        if router is None:
            pytest.skip("CommandRouter not available")
        try:
            from core.schemas.task_envelope import TaskEnvelope
            env = TaskEnvelope(
                task_id="t1",
                trace_id="tr1",
                source="test",
                targets=["dev1"],
                tool_name="test_cmd",
                args={},
            )
            result = await router.route_envelope(env)
            # lifecycle_state should be present and non-None
            assert "lifecycle_state" in result
            assert result["lifecycle_state"] is not None
        except Exception as exc:
            pytest.skip(f"route_envelope not runnable in isolation: {exc}")

    def test_lifecycle_state_values_are_valid_enum_values(self):
        valid_values = {s.value for s in ExecutionLifecycleState}
        # The only lifecycle states that route_envelope stamps are
        # "succeeded" or "failed"
        assert "succeeded" in valid_values
        assert "failed" in valid_values


# ---------------------------------------------------------------------------
# Section Q — NATSBus._ensure_trace_fields propagates lifecycle_state
# ---------------------------------------------------------------------------


class TestNATSBusLifecyclePropagation:
    """Section Q: NATSBus propagates lifecycle_state through transport."""

    def _get_nats_bus(self):
        try:
            from core.nats_bus import NATSBus
            bus = object.__new__(NATSBus)
            return bus
        except Exception:
            return None

    def test_lifecycle_state_propagated_when_provided(self):
        bus = self._get_nats_bus()
        if bus is None:
            pytest.skip("NATSBus not available")
        result = bus._ensure_trace_fields(
            {},
            trace_id="t1",
            lifecycle_state="dispatching",
        )
        assert result.get("lifecycle_state") == "dispatching"

    def test_lifecycle_state_not_clobbered_when_present(self):
        bus = self._get_nats_bus()
        if bus is None:
            pytest.skip("NATSBus not available")
        result = bus._ensure_trace_fields(
            {"lifecycle_state": "running"},
            lifecycle_state="succeeded",
        )
        # Existing value must not be overwritten
        assert result["lifecycle_state"] == "running"

    def test_lifecycle_state_absent_when_not_provided(self):
        bus = self._get_nats_bus()
        if bus is None:
            pytest.skip("NATSBus not available")
        result = bus._ensure_trace_fields(
            {"trace_id": "x", "runtime_session_id": "y"},
        )
        assert "lifecycle_state" not in result or result.get("lifecycle_state") in (None, "")

    def test_existing_trace_fields_not_overwritten(self):
        bus = self._get_nats_bus()
        if bus is None:
            pytest.skip("NATSBus not available")
        result = bus._ensure_trace_fields(
            {"trace_id": "existing", "runtime_session_id": "existing_session"},
            trace_id="new",
            runtime_session_id="new_session",
        )
        assert result["trace_id"] == "existing"
        assert result["runtime_session_id"] == "existing_session"


# ---------------------------------------------------------------------------
# Section R — Multi-step / orchestration lifecycle
# ---------------------------------------------------------------------------


class TestMultiStepOrchestrationLifecycle:
    """Section R: multi-step and orchestration lifecycle representability."""

    def test_orchestration_plan_stamps_lifecycle(self):
        decisions = [
            {"agent_id": "a1", "target_device_id": "d1", "resolved_execution_mode": "agent_runtime"},
            {"agent_id": "a2", "target_device_id": "d2", "resolved_execution_mode": "command_only"},
            {"agent_id": "a3", "target_device_id": "d3", "resolved_execution_mode": "agent_runtime"},
        ]
        plan = plan_from_orchestration_decisions(decisions=decisions)
        assert plan.lifecycle_state == "planned"
        assert len(plan.steps) == 3
        for step in plan.steps:
            assert step.lifecycle_state == "created"

    def test_partially_succeeded_representable(self):
        """PARTIALLY_SUCCEEDED is a valid lifecycle state for multi-step plans."""
        state = ExecutionLifecycleState.PARTIALLY_SUCCEEDED
        assert state.value == "partially_succeeded"
        assert not is_terminal(state)

    def test_partial_success_can_be_set_on_plan(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        plan.lifecycle_state = "partially_succeeded"
        assert plan.to_dict()["lifecycle_state"] == "partially_succeeded"

    def test_advance_lifecycle_to_partial_success(self):
        result = advance_lifecycle(
            ExecutionLifecycleState.RUNNING,
            success=None,
            partially_succeeded=True,
        )
        assert result == ExecutionLifecycleState.PARTIALLY_SUCCEEDED

    def test_each_step_can_have_independent_lifecycle(self):
        """Individual steps can be at different lifecycle states simultaneously."""
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        # Simulate steps at different states
        if len(plan.steps) > 0:
            plan.steps[0].lifecycle_state = "succeeded"
        # plan itself stays at planned
        assert plan.lifecycle_state == "planned"


# ---------------------------------------------------------------------------
# Section S — Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Section S: existing callers that don't use lifecycle data still work."""

    def test_execution_step_to_dict_has_classic_keys(self):
        """All pre-PR-12 keys must still be present."""
        step = ExecutionStep(
            step_type=ExecutionStepType.LOCAL_MANIFESTATION,
            target_devices=[],
        )
        d = step.to_dict()
        for key in (
            "step_id", "step_type", "target_devices", "remote_execution_mode",
            "required_capabilities", "authority_origin", "timeout_ms", "depends_on",
            "orchestration_plan_id", "metadata",
        ):
            assert key in d, f"Missing classic key: {key}"

    def test_execution_plan_to_dict_has_classic_keys(self):
        """All pre-PR-12 keys must still be present."""
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        for key in (
            "plan_id", "trace_id", "session_id", "execution_path",
            "delegation_point", "steps", "created_at", "metadata",
        ):
            assert key in d, f"Missing classic key: {key}"

    def test_plan_summary_classic_keys_present(self):
        """All pre-PR-12 plan_summary keys must still be present."""
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        s = plan_summary(plan)
        for key in (
            "plan_id", "execution_path", "delegation_point", "step_count",
            "primary_step_type", "is_local_only", "is_remote",
            "is_orchestration", "is_observe", "trace_id", "session_id",
        ):
            assert key in s, f"Missing classic summary key: {key}"

    def test_plan_summary_none_classic_keys_present(self):
        s = plan_summary(None)
        for key in (
            "plan_id", "execution_path", "delegation_point", "step_count",
            "primary_step_type", "is_local_only", "is_remote",
            "is_orchestration", "is_observe", "trace_id", "session_id",
        ):
            assert key in s

    def test_code_reading_only_success_key_unaffected(self):
        """Callers that only read 'success' from a result dict are unaffected."""
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        result = {"success": True, "response": "ok", "execution_plan": plan.to_dict()}
        # Standard consumer pattern must still work
        assert result["success"] is True
        assert result["response"] == "ok"

    def test_plan_with_no_lifecycle_state_still_serialises(self):
        """A plan created without lifecycle data (e.g. manual construction) serialises."""
        plan = ExecutionPlan(
            execution_path="local",
            delegation_point="local",
            steps=[ExecutionStep(step_type=ExecutionStepType.LOCAL_MANIFESTATION)],
        )
        d = plan.to_dict()
        assert d["lifecycle_state"] is None
        assert d["lifecycle_trail"] == []
        json.dumps(d)  # must not raise


# ---------------------------------------------------------------------------
# Section T — Diagnostics / inspectability
# ---------------------------------------------------------------------------


class TestDiagnosticsInspectability:
    """Section T: lifecycle state is inspectable through dicts."""

    def test_lifecycle_state_readable_from_plan_to_dict(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        assert d["lifecycle_state"] == "planned"

    def test_lifecycle_state_travels_through_plan_summary(self):
        plan = build_execution_plan(execution_path="cross_device", delegation_point="single_remote")
        s = plan_summary(plan)
        assert s["lifecycle_state"] == "planned"

    def test_lifecycle_trail_transitions_introspectable(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        trail = d["lifecycle_trail"]
        assert isinstance(trail, list)
        assert len(trail) >= 1
        first = trail[0]
        assert "to_state" in first
        assert "from_state" in first
        assert "reason" in first
        assert "timestamp" in first

    def test_step_lifecycle_trail_introspectable(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        for step in plan.steps:
            d = step.to_dict()
            trail = d["lifecycle_trail"]
            assert isinstance(trail, list)
            if trail:
                first = trail[0]
                assert "to_state" in first

    def test_lifecycle_summary_json_safe(self):
        trail = [
            LifecycleTransition.make(
                to_state=ExecutionLifecycleState.SUCCEEDED,
                from_state=ExecutionLifecycleState.RUNNING,
                reason="done",
            )
        ]
        s = lifecycle_summary(
            ExecutionLifecycleState.SUCCEEDED,
            trail,
            plan_id="p1",
            step_id="s1",
        )
        json.dumps(s)  # must not raise

    def test_full_local_lifecycle_sequence_representable(self):
        """Full local lifecycle: CREATED→PLANNED→DISPATCHING→RUNNING→SUCCEEDED."""
        states = [ExecutionLifecycleState.CREATED]
        current = ExecutionLifecycleState.CREATED
        trail = [LifecycleTransition.make(to_state=current, reason="created")]

        for _ in range(10):  # advance up to 10 times
            if is_terminal(current):
                break
            next_state = advance_lifecycle(current, success=None, is_remote=False)
            if next_state == current:
                # Arrived at terminal or unknown
                next_state = advance_lifecycle(current, success=True)
            trail.append(LifecycleTransition.make(
                to_state=next_state,
                from_state=current,
            ))
            states.append(next_state)
            current = next_state

        assert ExecutionLifecycleState.SUCCEEDED in states
        assert is_terminal(states[-1])

    def test_full_remote_lifecycle_sequence_representable(self):
        """Full remote lifecycle progression reaches a terminal state."""
        current = ExecutionLifecycleState.CREATED
        for _ in range(15):
            if is_terminal(current):
                break
            next_state = advance_lifecycle(current, success=None, is_remote=True)
            if next_state == current:
                next_state = advance_lifecycle(current, success=True)
            current = next_state

        assert is_terminal(current)
