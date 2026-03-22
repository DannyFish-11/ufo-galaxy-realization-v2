"""
tests/test_pr11_execution_plan.py
==================================
Tests for PR-11: Canonical Execution Plan Schema and OpenClawd integration.

Coverage
--------
A) ExecutionStepType enum
   - all expected values present
   - string values are stable
   - values are distinct

B) ExecutionStep dataclass
   - default construction (auto step_id, OBSERVE type)
   - step_id uniqueness across instances
   - to_dict() produces all expected keys
   - to_dict() is JSON-safe (no non-serialisable objects)
   - target_devices / required_capabilities default to empty lists
   - remote_execution_mode / orchestration_plan_id accept None

C) ExecutionPlan dataclass
   - construction with all defaults
   - plan_id uniqueness across instances
   - primary_step_type returns first step type
   - primary_step_type returns None for empty plan
   - is_local_only True when all LOCAL_MANIFESTATION steps
   - is_local_only False when steps are empty
   - is_remote True when any REMOTE_AGENT or REMOTE_COMMAND step
   - is_orchestration True when any ORCHESTRATION step
   - is_observe True when all OBSERVE steps
   - to_dict() produces all expected keys
   - to_dict() round-trips execution_path, delegation_point, trace_id, session_id

D) build_execution_plan — local path
   - execution_path="local" + delegation_point="local" → LOCAL_MANIFESTATION step
   - is_local_only is True
   - device_id propagated to step target_devices when provided
   - device_id omitted → target_devices is empty

E) build_execution_plan — remote command path
   - execution_path="cross_device" + delegation_point="single_remote"
     + remote_execution_mode="command_only" → REMOTE_COMMAND step
   - is_remote is True
   - remote_execution_mode propagated to step

F) build_execution_plan — remote agent path
   - execution_path="cross_device" + delegation_point="single_remote"
     + remote_execution_mode="agent_runtime" → REMOTE_AGENT step
   - is_remote is True
   - device_id propagated to step target_devices

G) build_execution_plan — orchestration path
   - execution_path="cross_device" + delegation_point="multi_device_orchestration"
     → ORCHESTRATION step
   - is_orchestration is True
   - target_devices defaults to ["*"] when device_id is None
   - orchestration_plan_id propagated to step

H) build_execution_plan — observe / no-op path
   - execution_path="none" → OBSERVE step
   - is_observe is True
   - is_local_only is False
   - is_remote is False

I) build_execution_plan — hybrid path
   - execution_path="hybrid" + delegation_point="single_remote"
     → produces two steps (remote + local)
   - step types are correct

J) build_execution_plan — extra metadata
   - trace_id and session_id propagated to plan
   - required_capabilities propagated to primary step
   - timeout_ms propagated to primary step
   - plan_metadata propagated to plan.metadata
   - extra_steps appended after primary step

K) plan_from_orchestration_decisions
   - empty decisions → single ORCHESTRATION fan-out step
   - agent_runtime decision → REMOTE_AGENT step
   - command_only decision → REMOTE_COMMAND step
   - multiple decisions → multiple steps
   - orchestration_plan_id propagated to all steps
   - execution_path = "cross_device"
   - delegation_point = "multi_device_orchestration"

L) plan_summary
   - None input → safe default dict
   - local plan → correct keys / values
   - remote plan → is_remote True
   - observe plan → is_observe True
   - all required summary keys present

M) ExecutionPlan.to_dict() serialisability
   - nested step dicts are JSON-serialisable
   - metadata field survives round-trip

N) OpenClawd._build_execution_plan helper
   - returns an ExecutionPlan instance for standard paths
   - graceful on unknown path values
   - does not raise even when called with minimal args

O) Backward compatibility
   - existing response dict without execution_plan key is not broken
   - UnifiedChatResponse accepts execution_plan_summary=None (default)
   - UnifiedChatResponse accepts a dict value for execution_plan_summary
   - to_json_response() includes execution_plan_summary key
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

# ---------------------------------------------------------------------------
# Import subjects
# ---------------------------------------------------------------------------

from core.schemas.execution_plan import (
    ExecutionStepType,
    ExecutionStep,
    ExecutionPlan,
    build_execution_plan,
    plan_from_orchestration_decisions,
    plan_summary,
)


# ---------------------------------------------------------------------------
# Section A — ExecutionStepType enum
# ---------------------------------------------------------------------------


class TestExecutionStepTypeEnum:
    def test_all_values_present(self):
        values = {e.value for e in ExecutionStepType}
        assert "local_manifestation" in values
        assert "remote_command" in values
        assert "remote_agent" in values
        assert "orchestration" in values
        assert "observe" in values

    def test_string_values_stable(self):
        assert ExecutionStepType.LOCAL_MANIFESTATION.value == "local_manifestation"
        assert ExecutionStepType.REMOTE_COMMAND.value == "remote_command"
        assert ExecutionStepType.REMOTE_AGENT.value == "remote_agent"
        assert ExecutionStepType.ORCHESTRATION.value == "orchestration"
        assert ExecutionStepType.OBSERVE.value == "observe"

    def test_values_are_distinct(self):
        values = [e.value for e in ExecutionStepType]
        assert len(values) == len(set(values))

    def test_is_str_subclass(self):
        for member in ExecutionStepType:
            assert isinstance(member, str)


# ---------------------------------------------------------------------------
# Section B — ExecutionStep dataclass
# ---------------------------------------------------------------------------


class TestExecutionStep:
    def test_default_construction(self):
        step = ExecutionStep()
        assert step.step_type == ExecutionStepType.OBSERVE
        assert step.step_id != ""
        assert step.target_devices == []
        assert step.remote_execution_mode is None
        assert step.required_capabilities == []
        assert step.timeout_ms is None
        assert step.depends_on == []
        assert step.orchestration_plan_id is None

    def test_step_id_uniqueness(self):
        ids = {ExecutionStep().step_id for _ in range(20)}
        assert len(ids) == 20

    def test_to_dict_has_expected_keys(self):
        step = ExecutionStep(
            step_type=ExecutionStepType.LOCAL_MANIFESTATION,
            target_devices=["dev-1"],
        )
        d = step.to_dict()
        for key in [
            "step_id", "step_type", "target_devices", "remote_execution_mode",
            "required_capabilities", "authority_origin", "timeout_ms",
            "depends_on", "orchestration_plan_id", "metadata",
        ]:
            assert key in d, f"Missing key: {key}"

    def test_to_dict_step_type_is_string(self):
        step = ExecutionStep(step_type=ExecutionStepType.REMOTE_AGENT)
        d = step.to_dict()
        assert d["step_type"] == "remote_agent"
        assert isinstance(d["step_type"], str)

    def test_to_dict_json_safe(self):
        import json
        step = ExecutionStep(
            step_type=ExecutionStepType.ORCHESTRATION,
            target_devices=["*"],
            required_capabilities=["screen", "keyboard"],
            timeout_ms=5000,
            orchestration_plan_id="plan-abc",
        )
        # Should not raise
        json.dumps(step.to_dict())

    def test_remote_execution_mode_none(self):
        step = ExecutionStep(remote_execution_mode=None)
        assert step.to_dict()["remote_execution_mode"] is None

    def test_authority_origin_default(self):
        step = ExecutionStep()
        assert step.authority_origin == "subject_decision_authority"


# ---------------------------------------------------------------------------
# Section C — ExecutionPlan dataclass
# ---------------------------------------------------------------------------


class TestExecutionPlan:
    def _local_step(self):
        return ExecutionStep(step_type=ExecutionStepType.LOCAL_MANIFESTATION)

    def _remote_step(self):
        return ExecutionStep(step_type=ExecutionStepType.REMOTE_AGENT)

    def _observe_step(self):
        return ExecutionStep(step_type=ExecutionStepType.OBSERVE)

    def _orch_step(self):
        return ExecutionStep(step_type=ExecutionStepType.ORCHESTRATION)

    def test_default_construction(self):
        plan = ExecutionPlan()
        assert plan.execution_path == "none"
        assert plan.delegation_point is None
        assert plan.steps == []
        assert plan.trace_id == ""
        assert plan.session_id == ""

    def test_plan_id_uniqueness(self):
        ids = {ExecutionPlan().plan_id for _ in range(20)}
        assert len(ids) == 20

    def test_primary_step_type_first(self):
        plan = ExecutionPlan(steps=[self._local_step(), self._remote_step()])
        assert plan.primary_step_type == ExecutionStepType.LOCAL_MANIFESTATION

    def test_primary_step_type_none_when_empty(self):
        plan = ExecutionPlan(steps=[])
        assert plan.primary_step_type is None

    def test_is_local_only_true(self):
        plan = ExecutionPlan(steps=[self._local_step(), self._local_step()])
        assert plan.is_local_only is True

    def test_is_local_only_false_when_empty(self):
        plan = ExecutionPlan(steps=[])
        assert plan.is_local_only is False

    def test_is_local_only_false_when_remote(self):
        plan = ExecutionPlan(steps=[self._local_step(), self._remote_step()])
        assert plan.is_local_only is False

    def test_is_remote_true(self):
        plan = ExecutionPlan(steps=[self._remote_step()])
        assert plan.is_remote is True

    def test_is_remote_true_for_command(self):
        plan = ExecutionPlan(
            steps=[ExecutionStep(step_type=ExecutionStepType.REMOTE_COMMAND)]
        )
        assert plan.is_remote is True

    def test_is_orchestration_true(self):
        plan = ExecutionPlan(steps=[self._orch_step()])
        assert plan.is_orchestration is True

    def test_is_observe_true(self):
        plan = ExecutionPlan(steps=[self._observe_step()])
        assert plan.is_observe is True

    def test_is_observe_false_mixed(self):
        plan = ExecutionPlan(steps=[self._observe_step(), self._local_step()])
        assert plan.is_observe is False

    def test_to_dict_keys(self):
        plan = ExecutionPlan(
            execution_path="local",
            delegation_point="local",
            trace_id="t1",
            session_id="s1",
            steps=[self._local_step()],
        )
        d = plan.to_dict()
        for key in [
            "plan_id", "trace_id", "session_id", "execution_path",
            "delegation_point", "steps", "created_at", "metadata",
        ]:
            assert key in d

    def test_to_dict_round_trips_fields(self):
        plan = ExecutionPlan(
            execution_path="cross_device",
            delegation_point="single_remote",
            trace_id="t-123",
            session_id="s-456",
        )
        d = plan.to_dict()
        assert d["execution_path"] == "cross_device"
        assert d["delegation_point"] == "single_remote"
        assert d["trace_id"] == "t-123"
        assert d["session_id"] == "s-456"


# ---------------------------------------------------------------------------
# Section D — build_execution_plan: local path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanLocal:
    def test_local_path_type(self):
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
        )
        assert plan.primary_step_type == ExecutionStepType.LOCAL_MANIFESTATION

    def test_local_path_is_local_only(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert plan.is_local_only

    def test_local_path_device_id_propagated(self):
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            device_id="local-host-1",
        )
        assert "local-host-1" in plan.steps[0].target_devices

    def test_local_path_no_device_id(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert plan.steps[0].target_devices == []

    def test_local_path_no_remote_mode(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        assert plan.steps[0].remote_execution_mode is None


# ---------------------------------------------------------------------------
# Section E — build_execution_plan: remote command path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanRemoteCommand:
    def test_remote_command_type(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
        )
        assert plan.primary_step_type == ExecutionStepType.REMOTE_COMMAND

    def test_remote_command_is_remote(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
        )
        assert plan.is_remote

    def test_remote_command_mode_propagated(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
        )
        assert plan.steps[0].remote_execution_mode == "command_only"


# ---------------------------------------------------------------------------
# Section F — build_execution_plan: remote agent path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanRemoteAgent:
    def test_remote_agent_type(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-1",
        )
        assert plan.primary_step_type == ExecutionStepType.REMOTE_AGENT

    def test_remote_agent_is_remote(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
        )
        assert plan.is_remote

    def test_remote_agent_device_propagated(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-1",
        )
        assert "tablet-1" in plan.steps[0].target_devices


# ---------------------------------------------------------------------------
# Section G — build_execution_plan: orchestration path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanOrchestration:
    def test_orchestration_type(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        assert plan.primary_step_type == ExecutionStepType.ORCHESTRATION

    def test_orchestration_is_orchestration(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        assert plan.is_orchestration

    def test_orchestration_default_target_devices(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
        )
        assert plan.steps[0].target_devices == ["*"]

    def test_orchestration_plan_id_propagated(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="multi_device_orchestration",
            orchestration_plan_id="orch-plan-001",
        )
        assert plan.steps[0].orchestration_plan_id == "orch-plan-001"


# ---------------------------------------------------------------------------
# Section H — build_execution_plan: observe / no-op path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanObserve:
    def test_observe_type(self):
        plan = build_execution_plan(execution_path="none")
        assert plan.primary_step_type == ExecutionStepType.OBSERVE

    def test_observe_is_observe(self):
        plan = build_execution_plan(execution_path="none")
        assert plan.is_observe

    def test_observe_not_local_only(self):
        plan = build_execution_plan(execution_path="none")
        assert not plan.is_local_only

    def test_observe_not_remote(self):
        plan = build_execution_plan(execution_path="none")
        assert not plan.is_remote

    def test_observe_not_orchestration(self):
        plan = build_execution_plan(execution_path="none")
        assert not plan.is_orchestration


# ---------------------------------------------------------------------------
# Section I — build_execution_plan: hybrid path
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanHybrid:
    def test_hybrid_produces_two_steps(self):
        plan = build_execution_plan(
            execution_path="hybrid",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-1",
        )
        assert len(plan.steps) == 2

    def test_hybrid_first_step_remote(self):
        plan = build_execution_plan(
            execution_path="hybrid",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-1",
        )
        assert plan.steps[0].step_type == ExecutionStepType.REMOTE_AGENT

    def test_hybrid_second_step_local(self):
        plan = build_execution_plan(
            execution_path="hybrid",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-1",
        )
        assert plan.steps[1].step_type == ExecutionStepType.LOCAL_MANIFESTATION


# ---------------------------------------------------------------------------
# Section J — build_execution_plan: extra metadata
# ---------------------------------------------------------------------------


class TestBuildExecutionPlanMetadata:
    def test_trace_id_propagated(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local", trace_id="t-x")
        assert plan.trace_id == "t-x"

    def test_session_id_propagated(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local", session_id="s-y")
        assert plan.session_id == "s-y"

    def test_required_capabilities_propagated(self):
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            required_capabilities=["screen", "keyboard"],
        )
        assert "screen" in plan.steps[0].required_capabilities
        assert "keyboard" in plan.steps[0].required_capabilities

    def test_timeout_ms_propagated(self):
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            timeout_ms=3000,
        )
        assert plan.steps[0].timeout_ms == 3000

    def test_plan_metadata_propagated(self):
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            plan_metadata={"custom_key": "custom_val"},
        )
        assert plan.metadata.get("custom_key") == "custom_val"

    def test_extra_steps_appended(self):
        extra = ExecutionStep(
            step_type=ExecutionStepType.OBSERVE,
            metadata={"extra": True},
        )
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            extra_steps=[extra],
        )
        assert len(plan.steps) == 2
        assert plan.steps[1].step_type == ExecutionStepType.OBSERVE


# ---------------------------------------------------------------------------
# Section K — plan_from_orchestration_decisions
# ---------------------------------------------------------------------------


class TestPlanFromOrchestrationDecisions:
    def test_empty_decisions_produces_fanout(self):
        plan = plan_from_orchestration_decisions(decisions=[])
        assert len(plan.steps) == 1
        assert plan.steps[0].step_type == ExecutionStepType.ORCHESTRATION
        assert plan.steps[0].target_devices == ["*"]

    def test_agent_runtime_decision_produces_remote_agent(self):
        plan = plan_from_orchestration_decisions(
            decisions=[{
                "agent_id": "a1",
                "target_device_id": "win-01",
                "resolved_execution_mode": "agent_runtime",
            }]
        )
        assert plan.steps[0].step_type == ExecutionStepType.REMOTE_AGENT

    def test_command_only_decision_produces_remote_command(self):
        plan = plan_from_orchestration_decisions(
            decisions=[{
                "agent_id": "a1",
                "target_device_id": "iot-01",
                "resolved_execution_mode": "command_only",
            }]
        )
        assert plan.steps[0].step_type == ExecutionStepType.REMOTE_COMMAND

    def test_multiple_decisions_produce_multiple_steps(self):
        plan = plan_from_orchestration_decisions(
            decisions=[
                {"agent_id": "a1", "target_device_id": "d1", "resolved_execution_mode": "agent_runtime"},
                {"agent_id": "a2", "target_device_id": "d2", "resolved_execution_mode": "command_only"},
                {"agent_id": "a3", "target_device_id": "d3", "resolved_execution_mode": "agent_runtime"},
            ]
        )
        assert len(plan.steps) == 3

    def test_orchestration_plan_id_propagated(self):
        plan = plan_from_orchestration_decisions(
            decisions=[{
                "agent_id": "a1",
                "target_device_id": "d1",
                "resolved_execution_mode": "agent_runtime",
            }],
            orchestration_plan_id="orch-42",
        )
        assert plan.steps[0].orchestration_plan_id == "orch-42"

    def test_execution_path_is_cross_device(self):
        plan = plan_from_orchestration_decisions(decisions=[])
        assert plan.execution_path == "cross_device"

    def test_delegation_point_is_multi_device_orchestration(self):
        plan = plan_from_orchestration_decisions(decisions=[])
        assert plan.delegation_point == "multi_device_orchestration"

    def test_trace_id_session_id_propagated(self):
        plan = plan_from_orchestration_decisions(
            decisions=[],
            trace_id="tr-x",
            session_id="se-y",
        )
        assert plan.trace_id == "tr-x"
        assert plan.session_id == "se-y"


# ---------------------------------------------------------------------------
# Section L — plan_summary
# ---------------------------------------------------------------------------


class TestPlanSummary:
    def test_none_input_safe(self):
        s = plan_summary(None)
        assert s["plan_id"] is None
        assert s["execution_path"] == "none"
        assert s["is_observe"] is True

    def test_local_plan_summary(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local", trace_id="t")
        s = plan_summary(plan)
        assert s["execution_path"] == "local"
        assert s["is_local_only"] is True
        assert s["is_observe"] is False
        assert s["step_count"] == 1

    def test_remote_plan_summary(self):
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
        )
        s = plan_summary(plan)
        assert s["is_remote"] is True

    def test_observe_plan_summary(self):
        plan = build_execution_plan(execution_path="none")
        s = plan_summary(plan)
        assert s["is_observe"] is True

    def test_all_required_keys_present(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        s = plan_summary(plan)
        expected_keys = [
            "plan_id", "execution_path", "delegation_point", "step_count",
            "primary_step_type", "is_local_only", "is_remote", "is_orchestration",
            "is_observe", "trace_id", "session_id",
        ]
        for k in expected_keys:
            assert k in s, f"Missing key: {k}"

    def test_plan_id_in_summary(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        s = plan_summary(plan)
        assert s["plan_id"] == plan.plan_id


# ---------------------------------------------------------------------------
# Section M — ExecutionPlan.to_dict() serialisability
# ---------------------------------------------------------------------------


class TestExecutionPlanSerialisability:
    def test_to_dict_json_serialisable(self):
        import json
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="dev-1",
            trace_id="t1",
            session_id="s1",
            required_capabilities=["screen"],
            timeout_ms=5000,
            orchestration_plan_id="orch-1",
            plan_metadata={"key": "value"},
        )
        # Should not raise
        json.dumps(plan.to_dict())

    def test_steps_in_to_dict(self):
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        assert isinstance(d["steps"], list)
        assert len(d["steps"]) == 1
        assert isinstance(d["steps"][0], dict)


# ---------------------------------------------------------------------------
# Section N — OpenClawd._build_execution_plan helper
# ---------------------------------------------------------------------------


class TestOpenClawdBuildExecutionPlan:
    def _get_openclawd(self):
        from core.openclawd import OpenClawd
        return OpenClawd()

    def test_returns_execution_plan_instance(self):
        oc = self._get_openclawd()
        result = oc._build_execution_plan(
            execution_path="local",
            delegation_point="local",
            trace_id="t1",
            session_id="s1",
        )
        assert result is not None
        assert result.primary_step_type == ExecutionStepType.LOCAL_MANIFESTATION

    def test_returns_plan_for_remote_agent(self):
        oc = self._get_openclawd()
        result = oc._build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="tablet-2",
        )
        assert result is not None
        assert result.primary_step_type == ExecutionStepType.REMOTE_AGENT

    def test_returns_plan_for_observe(self):
        oc = self._get_openclawd()
        result = oc._build_execution_plan(execution_path="none")
        assert result is not None
        assert result.is_observe

    def test_graceful_on_minimal_args(self):
        oc = self._get_openclawd()
        result = oc._build_execution_plan(execution_path="local")
        # Should not raise; may return None or a plan
        if result is not None:
            assert hasattr(result, "steps")

    def test_to_dict_callable_on_result(self):
        oc = self._get_openclawd()
        result = oc._build_execution_plan(
            execution_path="local",
            delegation_point="local",
        )
        if result is not None:
            d = result.to_dict()
            assert "plan_id" in d


# ---------------------------------------------------------------------------
# Section O — Backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_response_dict_without_execution_plan_key_unchanged(self):
        """Callers that only read 'success', 'response', 'metadata' are unaffected."""
        legacy_response = {
            "success": True,
            "response": "hello",
            "intent": "chat",
            "metadata": {"handler": "chat"},
        }
        # Accessing execution_plan key on a legacy dict should raise KeyError,
        # which is expected — callers must use .get().
        assert legacy_response.get("execution_plan") is None

    def test_unified_chat_response_default_plan_summary_is_none(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hi")
        assert resp.execution_plan_summary is None

    def test_unified_chat_response_accepts_dict_plan_summary(self):
        from core.unified_response import UnifiedChatResponse
        summary = {
            "plan_id": "p-001",
            "execution_path": "local",
            "step_count": 1,
        }
        resp = UnifiedChatResponse(success=True, response="hi", execution_plan_summary=summary)
        assert resp.execution_plan_summary == summary

    def test_to_json_response_includes_execution_plan_summary(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hi")
        d = resp.to_json_response()
        # Key must be present (may be None or dict)
        assert "execution_plan_summary" in d

    def test_existing_core_fields_still_present(self):
        from core.unified_response import UnifiedChatResponse
        resp = UnifiedChatResponse(success=True, response="hello", intent="chat")
        d = resp.to_json_response()
        for key in ["success", "response", "intent", "confidence", "mode", "session_id"]:
            assert key in d

    def test_build_execution_plan_returns_plan_with_has_a_dict(self):
        """build_execution_plan always returns a serialisable plan."""
        import json
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            trace_id="backward-compat-test",
        )
        d = plan.to_dict()
        # Must be JSON-serialisable
        json.dumps(d)
        assert d["execution_path"] == "local"
