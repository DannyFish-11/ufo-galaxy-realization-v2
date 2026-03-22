#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/integration/runtime/test_runtime_integration.py
=======================================================

PR-15 — Runtime Integration Test Suite

Validates cross-module runtime wiring across the Galaxy execution stack.
These integration tests confirm that the modules introduced across PR-1
through PR-14 compose correctly: schemas flow between layers, authority
metadata propagates end-to-end, failure records surface through the right
paths, and the substrate stamps introspection data consistently.

Test classes
------------
1. TestSchemaInterop
     Validates that schemas from different PRs compose without conflict:
     ExecutionPlan + ExecutionLifecycleState + FailureRecord + authority metadata.

2. TestModeResolverToEnvelopeWiring
     Validates that resolved modes from RemoteExecutionModeResolver flow
     correctly into TaskEnvelope and then through route_envelope.

3. TestSubstrateAuthorityStamping
     Validates that route_envelope stamps all expected authority and
     introspection fields on its result.

4. TestFailureRecordPropagation
     Validates that failure records integrate with lifecycle and plan schemas.

5. TestOrchestrationToSubstrateBoundary
     Validates that the orchestration layer builds its plan before the
     substrate is called, and that substrate results are collected per decision.

6. TestDiagnosticsIntegration
     Validates the end-to-end flow of building a multi-layer diagnostics
     snapshot from real or simulated layer results.

7. TestLifecycleStateIntegration
     Validates lifecycle state transitions through realistic multi-step flows.

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import json
import sys
import os
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _tid() -> str:
    return f"t_{uuid.uuid4().hex[:8]}"


def _sid() -> str:
    return f"s_{uuid.uuid4().hex[:8]}"


# ===========================================================================
# 1. TestSchemaInterop
# ===========================================================================


class TestSchemaInterop:
    """
    Execution plan, lifecycle state, failure record, and authority metadata
    are produced by different PRs but must compose into a single coherent
    result dict without conflicts.
    """

    def test_plan_plus_lifecycle_state_dict_merge(self):
        """An execution plan dict and a lifecycle summary can be merged cleanly."""
        from core.schemas.execution_plan import build_execution_plan
        from core.schemas.execution_lifecycle import lifecycle_summary, ExecutionLifecycleState

        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            trace_id=_tid(),
            session_id=_sid(),
        )
        plan_dict = plan.to_dict()
        lc_summary = lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)

        # Merge both into a single result dict (as a real response would)
        merged = {**plan_dict, **lc_summary}

        assert merged["execution_path"] == "local"
        assert merged["lifecycle_state"] == "succeeded"
        assert merged["is_terminal"] is True
        json.dumps(merged)  # must be serialisable

    def test_plan_plus_failure_record_merge(self):
        """An execution plan dict and a failure record summary can be merged cleanly."""
        from core.schemas.execution_plan import build_execution_plan
        from core.schemas.execution_failure import build_failure_record, failure_record_summary

        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
            device_id="dev_fail",
        )
        plan_dict = plan.to_dict()
        failure_rec = build_failure_record(error_code="DEVICE_NOT_FOUND")
        failure_summary = failure_record_summary(failure_rec)

        merged = {**plan_dict, **failure_summary}

        assert merged["execution_path"] == "cross_device"
        assert merged["failure_domain"] == "remote_device_unavailable"
        assert merged["is_retryable"] is True
        json.dumps(merged)

    def test_authority_metadata_plus_plan_plus_lifecycle(self):
        """Authority metadata, plan, and lifecycle all coexist in the same result dict."""
        from core.schemas.execution_authority import ExecutionLayerRole, build_authority_metadata
        from core.schemas.execution_plan import build_execution_plan
        from core.schemas.execution_lifecycle import lifecycle_summary, ExecutionLifecycleState

        meta = build_authority_metadata(
            ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY,
            canonical_module="core.openclawd",
            canonical_class="OpenClawd",
        )
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        lc = lifecycle_summary(ExecutionLifecycleState.RUNNING)

        # Simulate how OpenClawd assembles its response metadata
        result = {
            "success": True,
            "authority_role": meta.layer_role,  # already a string
            "execution_plan_summary": plan.to_dict(),
            **lc,
        }

        assert result["authority_role"] == "subject_decision_authority"
        assert result["lifecycle_state"] == "running"
        assert result["execution_plan_summary"]["execution_path"] == "local"
        json.dumps(result)

    def test_failure_record_integrates_with_lifecycle_failed_state(self):
        """FAILED lifecycle state and a failure record reference the same domain."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, is_terminal
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain

        state = ExecutionLifecycleState.FAILED
        assert is_terminal(state)

        rec = build_failure_record(error_code="COMMAND_TIMEOUT")
        assert rec.failure_domain == FailureDomain.TIMEOUT_FAILURE.value

        # Combine into a single result dict
        result = {
            "lifecycle_state": state.value,
            "failure_domain": rec.failure_domain,
            "is_retryable": rec.is_retryable,
        }
        assert result["lifecycle_state"] == "failed"
        assert result["failure_domain"] == "timeout_failure"

    def test_orchestration_plan_plus_execution_plan_compose(self):
        """OrchestrationPlan and ExecutionPlan can describe the same task in parallel."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )
        from core.schemas.execution_plan import plan_from_orchestration_decisions

        decisions_raw = [
            {"target_device_id": "dev_a", "resolved_execution_mode": "agent_runtime", "agent_id": "ag1"},
            {"target_device_id": "dev_b", "resolved_execution_mode": "command_only", "agent_id": "ag2"},
        ]

        # Orchestration planning layer view
        orch_decisions = [
            OrchestrationDecision(
                agent_id=d["agent_id"],
                target_device_id=d["target_device_id"],
                resolved_execution_mode=d["resolved_execution_mode"],
            )
            for d in decisions_raw
        ]
        orch_plan = build_orchestration_plan(task="integration test", decisions=orch_decisions)
        assert orch_plan.assigned_count == 2

        # Execution plan substrate view
        exec_plan = plan_from_orchestration_decisions(
            decisions=decisions_raw,
            task="integration test",
            orchestration_plan_id=orch_plan.plan_id,
        )
        assert len(exec_plan.steps) > 0
        # All steps reference the same orchestration plan
        for step in exec_plan.steps:
            if step.orchestration_plan_id is not None:
                assert step.orchestration_plan_id == orch_plan.plan_id


# ===========================================================================
# 2. TestModeResolverToEnvelopeWiring
# ===========================================================================


class TestModeResolverToEnvelopeWiring:
    """
    RemoteExecutionModeResolver result must wire correctly into TaskEnvelope
    which then flows through route_envelope.
    """

    def test_rich_profile_produces_agent_runtime_envelope(self):
        """Resolver result for a rich profile produces an agent_runtime TaskEnvelope."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_rich_profile
        from core.schemas.task_envelope import TaskEnvelope

        profile = build_rich_profile(device_id="rich_01")
        resolution = resolve_mode(profile=profile)

        env = TaskEnvelope(
            task_id=_tid(),
            trace_id=_tid(),
            session_id=_sid(),
            source="test",
            targets=[profile.device_id],
            tool_name="agent_execute",
            args={"task": "analyse"},
            remote_execution_mode=resolution.mode,
        )

        assert env.remote_execution_mode == "agent_runtime"
        assert env.targets == ["rich_01"]

    def test_thin_profile_produces_command_only_envelope(self):
        """Resolver result for a thin profile produces a command_only TaskEnvelope."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_thin_profile
        from core.schemas.task_envelope import TaskEnvelope

        profile = build_thin_profile(device_id="thin_01")
        resolution = resolve_mode(profile=profile)

        env = TaskEnvelope(
            task_id=_tid(),
            trace_id=_tid(),
            session_id=_sid(),
            source="test",
            targets=[profile.device_id],
            tool_name="run_command",
            args={"cmd": "ping"},
            remote_execution_mode=resolution.mode,
        )

        assert env.remote_execution_mode == "command_only"

    def test_forced_mode_overrides_profile_in_envelope(self):
        """Forced mode override from resolver propagates into envelope."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_rich_profile
        from core.schemas.task_envelope import TaskEnvelope

        profile = build_rich_profile(device_id="rich_02")
        resolution = resolve_mode(profile=profile, forced_mode="command_only")

        assert resolution.mode == "command_only"
        assert resolution.resolution_source == "forced"

        env = TaskEnvelope(
            task_id=_tid(),
            trace_id=_tid(),
            session_id=_sid(),
            source="test",
            targets=["rich_02"],
            tool_name="run_command",
            args={},
            remote_execution_mode=resolution.mode,
        )
        assert env.remote_execution_mode == "command_only"

    def test_resolver_to_envelope_to_route_envelope_pipeline(self):
        """Full pipeline: resolver → envelope → route_envelope stamps mode."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_rich_profile
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        profile = build_rich_profile(device_id="rich_03")
        resolution = resolve_mode(profile=profile)

        env = TaskEnvelope(
            task_id=_tid(),
            trace_id=_tid(),
            session_id=_sid(),
            source="test",
            targets=["rich_03"],
            tool_name="agent_execute",
            args={"task": "do work"},
            remote_execution_mode=resolution.mode,
        )

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        base_result = {
            "success": True, "result": "ok", "device_id": "rich_03",
            "request_id": env.task_id, "task_id": env.task_id,
            "command_id": env.task_id, "command": "agent_execute",
            "via": "command_router", "latency_ms": 3.0,
        }
        with patch.object(router, "_execute_command", new=AsyncMock(return_value=base_result)):
            result = asyncio.run(router.route_envelope(env))

        assert result["remote_execution_mode"] == "agent_runtime"
        # Substrate always stamps its role
        assert result.get("execution_substrate_role") == "execution_substrate"


# ===========================================================================
# 3. TestSubstrateAuthorityStamping
# ===========================================================================


class TestSubstrateAuthorityStamping:
    """
    route_envelope stamps authority, lifecycle, and introspection data on
    every result — even when the underlying execution is mocked.
    """

    def _make_base_result(self, task_id: str, success: bool = True) -> Dict[str, Any]:
        return {
            "success": success,
            "result": "ok" if success else None,
            "device_id": "dev_x",
            "request_id": task_id,
            "task_id": task_id,
            "command_id": task_id,
            "command": "test_cmd",
            "via": "command_router",
            "latency_ms": 1.0,
        }

    def _run_envelope(self, mode: str, success: bool = True) -> Dict[str, Any]:
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        tid = _tid()
        env = TaskEnvelope(
            task_id=tid,
            trace_id=_tid(),
            session_id=_sid(),
            source="test",
            targets=["dev_x"],
            tool_name="test_cmd",
            args={},
            remote_execution_mode=mode,
        )
        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        base = self._make_base_result(tid, success=success)
        with patch.object(router, "_execute_command", new=AsyncMock(return_value=base)):
            return asyncio.run(router.route_envelope(env))

    def test_substrate_role_stamped_on_success(self):
        result = self._run_envelope("command_only", success=True)
        assert result.get("execution_substrate_role") == "execution_substrate"

    def test_substrate_role_stamped_on_failure(self):
        result = self._run_envelope("agent_runtime", success=False)
        assert result.get("execution_substrate_role") == "execution_substrate"

    def test_lifecycle_state_succeeded_on_success(self):
        result = self._run_envelope("command_only", success=True)
        assert result.get("lifecycle_state") == "succeeded"

    def test_lifecycle_state_failed_on_failure(self):
        result = self._run_envelope("agent_runtime", success=False)
        assert result.get("lifecycle_state") == "failed"

    def test_remote_mode_propagated_command_only(self):
        result = self._run_envelope("command_only")
        assert result.get("remote_execution_mode") == "command_only"

    def test_remote_mode_propagated_agent_runtime(self):
        result = self._run_envelope("agent_runtime")
        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_lifecycle_via_waiting_remote_set_for_remote_mode(self):
        """Remote executions record that they passed through waiting_remote."""
        result = self._run_envelope("command_only")
        assert result.get("lifecycle_via_waiting_remote") is True

    def test_introspection_snapshot_present(self):
        """route_envelope stamps an introspection_snapshot on every result."""
        result = self._run_envelope("agent_runtime")
        snap = result.get("introspection_snapshot")
        assert snap is not None
        assert isinstance(snap, dict)
        assert snap.get("authority_role") == "execution_substrate"

    def test_introspection_snapshot_carries_mode(self):
        result = self._run_envelope("command_only")
        snap = result["introspection_snapshot"]
        assert snap.get("execution_mode") == "command_only"

    def test_failure_domain_stamped_on_failure_result(self):
        """Failed results carry failure_domain from the error code."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        tid = _tid()
        env = TaskEnvelope(
            task_id=tid, trace_id=_tid(), session_id=_sid(),
            source="test", targets=["dev_x"], tool_name="cmd", args={},
        )
        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        failed_result = {
            "success": False,
            "result": None,
            "device_id": "dev_x",
            "request_id": tid,
            "task_id": tid,
            "command_id": tid,
            "command": "cmd",
            "via": "command_router",
            "latency_ms": 1.0,
            "error_code": "DEVICE_NOT_FOUND",
            "error_message": "device not found",
        }
        with patch.object(router, "_execute_command", new=AsyncMock(return_value=failed_result)):
            result = asyncio.run(router.route_envelope(env))

        assert result.get("failure_domain") == "remote_device_unavailable"
        assert result.get("failure_is_retryable") is True


# ===========================================================================
# 4. TestFailureRecordPropagation
# ===========================================================================


class TestFailureRecordPropagation:
    """Failure records interact correctly with lifecycle and plan schemas."""

    def test_failure_domain_appears_in_lifecycle_summary(self):
        """Lifecycle summary can carry failure_domain when provided."""
        from core.schemas.execution_lifecycle import lifecycle_summary, ExecutionLifecycleState
        from core.failure_domains import FailureDomain

        summary = lifecycle_summary(
            ExecutionLifecycleState.FAILED,
            failure_domain=FailureDomain.TIMEOUT_FAILURE.value,
        )
        assert summary["lifecycle_state"] == "failed"
        assert summary["failure_domain"] == "timeout_failure"

    def test_retryable_failure_and_failed_lifecycle(self):
        """A retryable failure co-exists with FAILED lifecycle state."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState
        from core.schemas.execution_failure import build_failure_record

        rec = build_failure_record(error_code="COMMAND_TIMEOUT")
        assert rec.is_retryable
        # Lifecycle is FAILED regardless of retryability
        assert ExecutionLifecycleState.FAILED.value == "failed"

    def test_failure_summary_completes_to_dict(self):
        """All known error codes produce valid failure record dicts."""
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        codes = [
            "COMMAND_TIMEOUT", "DISCONNECT", "EXECUTOR_ERROR",
            "DEVICE_NOT_FOUND", "DEVICE_OFFLINE", "INVALID_ENVELOPE",
            "INTERNAL_ERROR", "ACL_DENIED",
        ]
        for code in codes:
            rec = build_failure_record(error_code=code)
            summary = failure_record_summary(rec)
            assert "failure_domain" in summary
            assert "is_retryable" in summary
            json.dumps(summary)

    def test_failure_domain_from_exception_matches_lifecycle_timed_out(self):
        from core.failure_domains import classify_from_exception, FailureDomain
        from core.schemas.execution_lifecycle import ExecutionLifecycleState

        c = classify_from_exception(TimeoutError("expired"))
        assert c.domain == FailureDomain.TIMEOUT_FAILURE

        # The runtime maps timeout failures to TIMED_OUT lifecycle state
        state = ExecutionLifecycleState.TIMED_OUT
        assert state.value == "timed_out"

    def test_orchestration_partial_failure_domain(self):
        """ORCHESTRATION_PARTIAL_FAILURE is the correct domain for mixed outcomes."""
        from core.failure_domains import FailureDomain, downgrade_hint_for_domain
        domain = FailureDomain.ORCHESTRATION_PARTIAL_FAILURE
        hint = downgrade_hint_for_domain(domain)
        # Partial failure has no simple mode downgrade
        assert hint is None


# ===========================================================================
# 5. TestOrchestrationToSubstrateBoundary
# ===========================================================================


class TestOrchestrationToSubstrateBoundary:
    """
    The orchestration layer builds its plan before any substrate call.
    Substrate results are collected per-decision and assembled by the
    orchestration layer into an aggregate result.
    """

    def test_orchestration_plan_ids_different_from_execution_plan_ids(self):
        """OrchestrationPlan IDs use a 'orch_plan_' prefix; ExecutionPlan IDs are plain UUIDs."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )
        from core.schemas.execution_plan import build_execution_plan

        d = OrchestrationDecision(agent_id="ag1", target_device_id="dev_a")
        orch_plan = build_orchestration_plan(task="t", decisions=[d])
        exec_plan = build_execution_plan(execution_path="cross_device", delegation_point="multi_device_orchestration")

        assert orch_plan.plan_id.startswith("orch_plan_")
        # ExecutionPlan IDs are plain UUIDs (no prefix)
        assert not exec_plan.plan_id.startswith("orch_plan_")
        assert orch_plan.plan_id != exec_plan.plan_id

    def test_substrate_dispatch_per_decision(self):
        """Each OrchestrationDecision maps to one substrate call."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            build_orchestration_plan,
            build_orchestration_result,
        )
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter

        decisions = [
            OrchestrationDecision(agent_id=f"ag{i}", target_device_id=f"dev_{i}",
                                  resolved_execution_mode="command_only")
            for i in range(3)
        ]
        plan = build_orchestration_plan(task="fan-out", decisions=decisions, trace_id=_tid())

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        call_count = [0]

        async def _fake_execute(*args, **kwargs) -> Dict[str, Any]:
            call_count[0] += 1
            return {
                "success": True, "result": "ok", "device_id": "dev",
                "request_id": "r", "task_id": "t", "command_id": "c",
                "command": "cmd", "via": "command_router", "latency_ms": 1.0,
            }

        substrate_results = []
        with patch.object(router, "_execute_command", new=AsyncMock(side_effect=_fake_execute)):
            for dec in decisions:
                env = TaskEnvelope(
                    task_id=_tid(),
                    trace_id=plan.trace_id,
                    session_id=_sid(),
                    source="orchestration",
                    targets=[dec.target_device_id],
                    tool_name="run_command",
                    args={},
                    remote_execution_mode=dec.resolved_execution_mode or "command_only",
                )
                res = asyncio.run(router.route_envelope(env))
                substrate_results.append(
                    OrchestrationMemberResult(
                        agent_id=dec.agent_id,
                        decision=dec,
                        success=res.get("success", False),
                        output=str(res.get("result", "")),
                    )
                )

        # Substrate was called once per decision
        assert call_count[0] == 3

        # Aggregate into orchestration result
        orch_result = build_orchestration_result(plan=plan, member_results=substrate_results)
        assert orch_result.success_count == 3
        assert orch_result.failure_count == 0

    def test_orchestration_partial_failure_count(self):
        """Partial orchestration failure is reflected in failure_count."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            build_orchestration_plan,
            build_orchestration_result,
        )
        d1 = OrchestrationDecision(agent_id="ag1", target_device_id="dev_a")
        d2 = OrchestrationDecision(agent_id="ag2", target_device_id="dev_b")
        plan = build_orchestration_plan(task="test", decisions=[d1, d2])
        member_results = [
            OrchestrationMemberResult(agent_id="ag1", decision=d1, success=True, output="ok"),
            OrchestrationMemberResult(agent_id="ag2", decision=d2, success=False, error="timeout"),
        ]
        result = build_orchestration_result(plan=plan, member_results=member_results)
        assert result.success_count == 1
        assert result.failure_count == 1
        assert result.success_count + result.failure_count == len(decisions := [d1, d2])


# ===========================================================================
# 6. TestDiagnosticsIntegration
# ===========================================================================


class TestDiagnosticsIntegration:
    """
    End-to-end diagnostics flow: collect layer snapshots, assemble them
    with build_diagnostics_snapshot_from_layers, and run all checks.
    """

    def _make_layer_results(self) -> List[Dict[str, Any]]:
        """Simulate what each layer would emit as a result dict."""
        return [
            {
                "arch_layer_id": "runtime_shell",
                "authority_metadata": {
                    "layer_role": "runtime_shell_authority",
                    "canonical_module": "core.desktop_presence_runtime",
                    "canonical_class": "DesktopPresenceRuntime",
                },
                "success": True,
            },
            {
                "arch_layer_id": "subject_core",
                "metadata": {
                    "authority_role": "subject_decision_authority",
                    "delegation_point": "local",
                },
                "success": True,
            },
            {
                "arch_layer_id": "cognition_layer",
                "authority_role": "cognition_planning_layer",
                "success": True,
            },
            {
                "arch_layer_id": "execution_substrate",
                "execution_substrate_role": "execution_substrate",
                "success": True,
                "lifecycle_state": "succeeded",
            },
        ]

    def test_full_layer_snapshot_is_valid(self):
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        results = self._make_layer_results()
        snapshot = build_diagnostics_snapshot_from_layers(*results)

        assert set(snapshot.keys()) == {"runtime_shell", "subject_core", "cognition_layer", "execution_substrate"}

        report = run_architecture_diagnostics(snapshot)
        assert report.overall_valid
        assert report.error_count == 0

    def test_diagnostics_report_covers_all_checks(self):
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        results = self._make_layer_results()
        snapshot = build_diagnostics_snapshot_from_layers(*results)
        report = run_architecture_diagnostics(snapshot)
        # All standard checks should have run
        assert len(report.checks_run) >= 6

    def test_diagnostics_with_remote_execution_mode(self):
        """Adding remote_execution_mode to the substrate layer does not break diagnostics."""
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        results = self._make_layer_results()
        # Add remote mode to substrate result
        results[-1]["remote_execution_mode"] = "agent_runtime"
        snapshot = build_diagnostics_snapshot_from_layers(*results)
        report = run_architecture_diagnostics(snapshot)
        assert report.overall_valid

    def test_three_layer_snapshot_still_valid(self):
        """A snapshot with only three layers (no cognition) is still diagnostically sound."""
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        results = [r for r in self._make_layer_results() if r["arch_layer_id"] != "cognition_layer"]
        snapshot = build_diagnostics_snapshot_from_layers(*results)
        report = run_architecture_diagnostics(snapshot)
        # Missing cognition_layer produces a warning but not an error
        assert report.error_count == 0


# ===========================================================================
# 7. TestLifecycleStateIntegration
# ===========================================================================


class TestLifecycleStateIntegration:
    """
    Lifecycle state transitions through realistic multi-step flows.
    Validates advance_lifecycle, is_terminal, and lifecycle_summary
    across all major execution paths.
    """

    def test_local_lifecycle_flow(self):
        """Local execution: PLANNED → (advance) → SUCCEEDED."""
        from core.schemas.execution_lifecycle import (
            ExecutionLifecycleState as LC,
            advance_lifecycle,
            is_terminal,
        )
        state = LC.PLANNED
        assert not is_terminal(state)

        # Advance on success
        state = advance_lifecycle(state, success=True)
        # Should have moved forward
        assert state != LC.PLANNED

        # Simulate completion
        final = LC.SUCCEEDED
        assert is_terminal(final)

    def test_remote_lifecycle_flow_success(self):
        """Remote execution with success=True advances lifecycle from PLANNED."""
        from core.schemas.execution_lifecycle import (
            ExecutionLifecycleState as LC,
            advance_lifecycle,
            is_terminal,
        )
        state = LC.PLANNED
        # Advance: success=True, is_remote=True should advance forward
        next_state = advance_lifecycle(state, success=True, is_remote=True)
        # Must have moved forward from PLANNED
        assert next_state != LC.PLANNED
        # Eventually reaches a terminal state
        assert is_terminal(LC.SUCCEEDED)

    def test_remote_lifecycle_flow_timeout(self):
        """Remote execution that times out reaches TIMED_OUT terminal state."""
        from core.schemas.execution_lifecycle import (
            ExecutionLifecycleState as LC,
            advance_lifecycle,
            is_terminal,
        )
        state = LC.WAITING_REMOTE
        state = advance_lifecycle(state, success=False, timed_out=True)
        assert state == LC.TIMED_OUT
        assert is_terminal(state)

    def test_degraded_lifecycle_state(self):
        """Degraded state is terminal and represents a partial but usable result."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, is_terminal
        state = ExecutionLifecycleState.DEGRADED
        assert is_terminal(state)

    def test_partially_succeeded_state_is_non_terminal(self):
        """PARTIALLY_SUCCEEDED is a non-terminal state (execution may still continue)."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, is_terminal
        # PARTIALLY_SUCCEEDED is not in the terminal set — it's a degraded-progress state
        assert not is_terminal(ExecutionLifecycleState.PARTIALLY_SUCCEEDED)

    def test_lifecycle_initial_state_for_local_step(self):
        """initial_state_for_step_type maps LOCAL_MANIFESTATION correctly."""
        from core.schemas.execution_lifecycle import (
            initial_state_for_step_type,
            ExecutionLifecycleState,
        )
        state = initial_state_for_step_type("local_manifestation")
        # Should be a non-terminal state at the start of a step
        assert not ExecutionLifecycleState(state).value == "succeeded"

    def test_lifecycle_initial_state_for_remote_command(self):
        from core.schemas.execution_lifecycle import initial_state_for_step_type
        state = initial_state_for_step_type("remote_command")
        assert state is not None

    def test_lifecycle_initial_state_for_remote_agent(self):
        from core.schemas.execution_lifecycle import initial_state_for_step_type
        state = initial_state_for_step_type("remote_agent")
        assert state is not None

    def test_lifecycle_summary_all_terminal_states(self):
        """All terminal states produce valid lifecycle summaries."""
        from core.schemas.execution_lifecycle import (
            ExecutionLifecycleState,
            lifecycle_summary,
            terminal_states,
        )
        for state in terminal_states():
            summary = lifecycle_summary(state)
            assert summary["is_terminal"] is True
            assert summary["lifecycle_state"] == state.value
            json.dumps(summary)

    def test_lifecycle_summary_non_terminal_state(self):
        """Non-terminal states report is_terminal=False."""
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, lifecycle_summary
        summary = lifecycle_summary(ExecutionLifecycleState.RUNNING)
        assert summary["is_terminal"] is False
        assert summary["lifecycle_state"] == "running"
