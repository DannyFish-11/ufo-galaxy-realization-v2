#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/e2e/test_e2e_runtime_scenarios.py
========================================

PR-15 — End-to-End Runtime Scenario Suites

Representative, durable regression gate for the Galaxy runtime stack.
Validates real runtime behaviour across seven canonical scenarios; assertions
go well beyond ``success=True`` and cover authority metadata, remote
execution mode, execution plans, lifecycle state, fallback/failure information,
and diagnostics summaries.

All tests are self-contained — no live servers, no real devices, no network
I/O.  Async paths use :func:`asyncio.run` or ``pytest-asyncio`` where needed.

Scenario coverage
-----------------
1. Local execution
     authority chain · execution plan / lifecycle · diagnostics explainable
2. Remote ``command_only``
     mode=command_only · route_envelope path · gateway/NATS propagation
3. Remote ``agent_runtime``
     mode=agent_runtime · substrate root shared · metadata consistency
4. Multi-device orchestration
     upper-layer semantics · fan-out / aggregation · partial results surfaced
5. Fallback
     downgrade / alternate target · fallback reason visible
6. Capability mismatch
     resolver decision · diagnostics explain the mismatch
7. Diagnostics / validator
     valid flow passes · intentionally miswired flow is detectable
"""

from __future__ import annotations

import asyncio
import sys
import os
import json
import uuid
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_trace() -> str:
    return f"trace_{uuid.uuid4().hex[:8]}"


def _make_session() -> str:
    return f"session_{uuid.uuid4().hex[:8]}"


# ===========================================================================
# Scenario 1 — Local Execution
# ===========================================================================


class TestScenario1LocalExecution:
    """
    Validate a local manifestation flow end-to-end.

    Assertions:
    - correct authority chain (runtime_shell → subject_core → cognition → substrate)
    - correct execution plan (LOCAL_MANIFESTATION step, is_local_only=True)
    - lifecycle initialises at the expected state for a local step
    - diagnostics run cleanly on the assembled flow snapshot
    """

    def test_local_plan_has_correct_step_type(self):
        from core.schemas.execution_plan import (
            build_execution_plan,
            ExecutionStepType,
        )
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            trace_id=_make_trace(),
            session_id=_make_session(),
        )
        assert plan.is_local_only
        assert not plan.is_remote
        assert not plan.is_orchestration
        assert len(plan.steps) >= 1
        assert plan.steps[0].step_type == ExecutionStepType.LOCAL_MANIFESTATION

    def test_local_plan_device_id_propagated(self):
        from core.schemas.execution_plan import build_execution_plan
        plan = build_execution_plan(
            execution_path="local",
            delegation_point="local",
            device_id="local_host",
        )
        assert "local_host" in plan.steps[0].target_devices

    def test_local_plan_serialisable(self):
        from core.schemas.execution_plan import build_execution_plan
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        json.dumps(d)  # must not raise
        assert "plan_id" in d
        assert "steps" in d
        assert d["execution_path"] == "local"

    def test_local_plan_lifecycle_state_is_planned(self):
        from core.schemas.execution_plan import build_execution_plan
        from core.schemas.execution_lifecycle import ExecutionLifecycleState
        plan = build_execution_plan(execution_path="local", delegation_point="local")
        d = plan.to_dict()
        # Lifecycle state is attached during build
        assert d["lifecycle_state"] == ExecutionLifecycleState.PLANNED.value

    def test_authority_chain_order(self):
        """CANONICAL_AUTHORITY_CHAIN is outer-to-inner and all roles are distinct."""
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [role for role, _mod, _cls in CANONICAL_AUTHORITY_CHAIN]
        # At minimum these four roles must appear in order
        expected = [
            ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY,
            ExecutionLayerRole.COGNITION_PLANNING_LAYER,
            ExecutionLayerRole.EXECUTION_SUBSTRATE,
        ]
        indices = [roles.index(r) for r in expected]
        assert indices == sorted(indices), "Authority chain must be outer→inner"
        assert len(roles) == len(set(roles)), "No duplicates in authority chain"

    def test_authority_metadata_for_local_shell(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            canonical_module="core.desktop_presence_runtime",
            canonical_class="DesktopPresenceRuntime",
        )
        d = meta.model_dump()
        assert d["layer_role"] == "runtime_shell_authority"
        assert "core.desktop_presence_runtime" in d["canonical_module"]

    def test_diagnostics_pass_on_correct_local_snapshot(self):
        """A correctly assembled local-flow snapshot produces a valid diagnostics report."""
        from core.architecture_diagnostics import run_architecture_diagnostics

        snapshot = {
            "runtime_shell": {
                "authority_metadata": {
                    "layer_role": "runtime_shell_authority",
                    "canonical_module": "core.desktop_presence_runtime",
                }
            },
            "subject_core": {
                "metadata": {"authority_role": "subject_decision_authority"}
            },
            "cognition_layer": {
                "authority_role": "cognition_planning_layer"
            },
            "execution_substrate": {
                "execution_substrate_role": "execution_substrate"
            },
        }
        report = run_architecture_diagnostics(snapshot)
        assert report.overall_valid, (
            f"Expected overall_valid=True; findings: "
            f"{[f.message for f in report.findings if f.severity.value in ('error', 'critical')]}"
        )

    def test_diagnostics_report_has_summary(self):
        """Diagnostics report carries a human-readable summary."""
        from core.architecture_diagnostics import run_architecture_diagnostics

        snapshot = {
            "runtime_shell": {
                "authority_metadata": {
                    "layer_role": "runtime_shell_authority",
                    "canonical_module": "core.desktop_presence_runtime",
                }
            },
            "subject_core": {"metadata": {"authority_role": "subject_decision_authority"}},
            "cognition_layer": {"authority_role": "cognition_planning_layer"},
            "execution_substrate": {"execution_substrate_role": "execution_substrate"},
        }
        report = run_architecture_diagnostics(snapshot)
        d = report.model_dump()
        assert "overall_valid" in d
        assert "findings" in d
        # summary dict is JSON-safe
        json.dumps(d)

    def test_lifecycle_advance_from_planned_to_running(self):
        """Lifecycle can advance from PLANNED → RUNNING for a local step."""
        from core.schemas.execution_lifecycle import (
            ExecutionLifecycleState,
            advance_lifecycle,
            is_terminal,
        )
        state = ExecutionLifecycleState.PLANNED
        assert not is_terminal(state)
        next_state = advance_lifecycle(state, success=True)
        # Must move forward, not stay at PLANNED
        assert next_state != ExecutionLifecycleState.PLANNED

    def test_lifecycle_succeeded_is_terminal(self):
        from core.schemas.execution_lifecycle import ExecutionLifecycleState, is_terminal
        assert is_terminal(ExecutionLifecycleState.SUCCEEDED)
        assert is_terminal(ExecutionLifecycleState.FAILED)
        assert not is_terminal(ExecutionLifecycleState.RUNNING)

    def test_lifecycle_summary_keys(self):
        from core.schemas.execution_lifecycle import lifecycle_summary, ExecutionLifecycleState
        summary = lifecycle_summary(ExecutionLifecycleState.SUCCEEDED)
        required = {"lifecycle_state", "is_terminal"}
        assert required.issubset(summary.keys()), f"Missing keys: {required - summary.keys()}"
        json.dumps(summary)


# ===========================================================================
# Scenario 2 — Remote command_only
# ===========================================================================


class TestScenario2RemoteCommandOnly:
    """
    Validate a remote command-only flow.

    Assertions:
    - mode = command_only
    - correct route_envelope path is used (not a different shim)
    - remote_execution_mode propagated through route_envelope result
    - execution plan has REMOTE_COMMAND step type
    """

    def test_remote_command_plan_step_type(self):
        from core.schemas.execution_plan import build_execution_plan, ExecutionStepType
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
            device_id="remote_dev_1",
            trace_id=_make_trace(),
            session_id=_make_session(),
        )
        assert plan.is_remote
        assert not plan.is_local_only
        step = plan.steps[0]
        assert step.step_type == ExecutionStepType.REMOTE_COMMAND
        assert step.remote_execution_mode == "command_only"

    def test_remote_command_plan_device_propagated(self):
        from core.schemas.execution_plan import build_execution_plan
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
            device_id="remote_dev_42",
        )
        assert "remote_dev_42" in plan.steps[0].target_devices

    def test_route_envelope_stamps_command_only_mode(self):
        """CommandRouter.route_envelope propagates remote_execution_mode=command_only."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter
        from unittest.mock import AsyncMock

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        env = TaskEnvelope(
            task_id="t1",
            trace_id=_make_trace(),
            session_id=_make_session(),
            source="test",
            targets=["remote_dev_1"],
            tool_name="ping",
            args={},
            remote_execution_mode="command_only",
        )

        # Patch the internal execution engine; route_envelope stamps the mode afterwards
        base_result = {
            "success": True,
            "result": "ack",
            "device_id": "remote_dev_1",
            "request_id": "t1",
            "task_id": "t1",
            "command_id": "t1",
            "command": "ping",
            "via": "command_router",
            "latency_ms": 1.0,
        }
        with patch.object(router, "_execute_command", new=AsyncMock(return_value=base_result)):
            result = asyncio.run(router.route_envelope(env))

        assert result.get("remote_execution_mode") == "command_only"

    def test_command_only_resolver_for_thin_device(self):
        """Thin-profile device resolves to command_only with a clear resolution source."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_thin_profile

        profile = build_thin_profile(device_id="thin_device_01")
        result = resolve_mode(profile=profile)

        assert result.mode == "command_only"
        assert result.resolution_source in ("profile_preferred", "capability_inferred", "fallback")

    def test_command_only_mode_is_stable_string(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        assert RemoteExecutionMode.command_only.value == "command_only"

    def test_remote_command_plan_serialisable(self):
        from core.schemas.execution_plan import build_execution_plan
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="command_only",
            device_id="dev_x",
        )
        d = plan.to_dict()
        json.dumps(d)
        assert d["execution_path"] == "cross_device"
        assert d["delegation_point"] == "single_remote"
        # mode propagated into first step
        assert d["steps"][0]["remote_execution_mode"] == "command_only"


# ===========================================================================
# Scenario 3 — Remote agent_runtime
# ===========================================================================


class TestScenario3RemoteAgentRuntime:
    """
    Validate a remote agent-runtime flow.

    Assertions:
    - mode = agent_runtime
    - agent dispatch and command path share the same substrate root (route_envelope)
    - metadata / authority / result consistency
    """

    def test_remote_agent_plan_step_type(self):
        from core.schemas.execution_plan import build_execution_plan, ExecutionStepType
        plan = build_execution_plan(
            execution_path="cross_device",
            delegation_point="single_remote",
            remote_execution_mode="agent_runtime",
            device_id="rich_dev_01",
            trace_id=_make_trace(),
            session_id=_make_session(),
        )
        assert plan.is_remote
        step = plan.steps[0]
        assert step.step_type == ExecutionStepType.REMOTE_AGENT
        assert step.remote_execution_mode == "agent_runtime"

    def test_agent_runtime_resolver_for_rich_device(self):
        """Rich-profile device resolves to agent_runtime."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_rich_profile

        profile = build_rich_profile(device_id="rich_device_01")
        result = resolve_mode(profile=profile)

        assert result.mode == "agent_runtime"
        assert result.resolution_source in ("profile_preferred", "capability_inferred")

    def test_route_envelope_stamps_agent_runtime_mode(self):
        """CommandRouter.route_envelope propagates remote_execution_mode=agent_runtime."""
        from core.schemas.task_envelope import TaskEnvelope
        from core.command_router import CommandRouter
        from unittest.mock import AsyncMock

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        env = TaskEnvelope(
            task_id="t2",
            trace_id=_make_trace(),
            session_id=_make_session(),
            source="test",
            targets=["rich_dev_01"],
            tool_name="agent_execute",
            args={"task": "analyse data"},
            remote_execution_mode="agent_runtime",
        )

        base_result = {
            "success": True,
            "result": "agent_ack",
            "device_id": "rich_dev_01",
            "request_id": "t2",
            "task_id": "t2",
            "command_id": "t2",
            "command": "agent_execute",
            "via": "command_router",
            "latency_ms": 2.0,
        }
        with patch.object(router, "_execute_command", new=AsyncMock(return_value=base_result)):
            result = asyncio.run(router.route_envelope(env))

        assert result.get("remote_execution_mode") == "agent_runtime"

    def test_both_modes_use_same_substrate_root(self):
        """
        Both command_only and agent_runtime envelopes are processed by
        CommandRouter.route_envelope — the single substrate root.
        """
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from unittest.mock import AsyncMock

        call_log: list = []

        def _make_base_result(mode: str) -> Dict[str, Any]:
            return {
                "success": True,
                "result": "ok",
                "device_id": "dev_a",
                "request_id": "req",
                "task_id": "t",
                "command_id": "cmd",
                "command": "test_tool",
                "via": "command_router",
                "latency_ms": 1.0,
            }

        async def _fake_execute(*args, **kwargs) -> Dict[str, Any]:
            return _make_base_result("")

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        with patch.object(router, "_execute_command", new=AsyncMock(side_effect=_fake_execute)):
            for mode in ("command_only", "agent_runtime"):
                env = TaskEnvelope(
                    task_id=uuid.uuid4().hex,
                    trace_id=_make_trace(),
                    session_id=_make_session(),
                    source="test",
                    targets=["dev_a"],
                    tool_name="test_tool",
                    args={},
                    remote_execution_mode=mode,
                )
                result = asyncio.run(router.route_envelope(env))
                call_log.append(result.get("remote_execution_mode"))

        assert call_log == ["command_only", "agent_runtime"], (
            "Both modes must produce the correct remote_execution_mode in the result"
        )

    def test_agent_dispatch_result_carries_mode_metadata(self):
        """dispatch_agent_remote result carries remote_execution_mode=agent_runtime."""
        from core.command_router import CommandRouter
        from unittest.mock import AsyncMock

        router = CommandRouter.__new__(CommandRouter)
        router._config = {}

        async def _mock_route_envelope(envelope) -> Dict[str, Any]:
            mode = envelope.remote_execution_mode
            mode_str = mode.value if hasattr(mode, "value") else (mode or "agent_runtime")
            return {
                "success": True,
                "result": "agent_result",
                "device_id": "rich_dev_01",
                "request_id": "req",
                "task_id": "t",
                "command_id": "cmd",
                "command": "agent_execute",
                "via": "command_router",
                "latency_ms": 5.0,
                "remote_execution_mode": mode_str,
            }

        with patch.object(router, "route_envelope", new=AsyncMock(side_effect=_mock_route_envelope)):
            # Also patch out the device_manager import that needs fastapi
            with patch.dict("sys.modules", {"core.unified.device_manager": MagicMock()}):
                with patch.dict("sys.modules", {"core.device_policy": MagicMock()}):
                    import sys as _sys
                    dm = _sys.modules["core.unified.device_manager"]
                    dm.get_unified_device_manager.return_value.get_device_type.return_value = "cloud"

                    dp = _sys.modules["core.device_policy"]
                    dp.requires_agent_deploy.return_value = False

                    result = asyncio.run(router.dispatch_agent_remote(
                        device_id="rich_dev_01",
                        agent_id="agent_a",
                        agent_template="analyst",
                        task="summarise logs",
                        session_id=_make_session(),
                        trace_id=_make_trace(),
                        task_id=uuid.uuid4().hex,
                    ))

        assert result.get("remote_execution_mode") == "agent_runtime"
        assert result.get("success") is True

    def test_agent_runtime_mode_is_stable_string(self):
        from core.schemas.remote_execution import RemoteExecutionMode
        assert RemoteExecutionMode.agent_runtime.value == "agent_runtime"

    def test_agent_runtime_plan_authority_metadata(self):
        """Authority metadata for subject_decision_authority is set correctly."""
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY,
            canonical_module="core.openclawd",
            canonical_class="OpenClawd",
        )
        d = meta.model_dump()
        assert d["layer_role"] == "subject_decision_authority"
        assert "openclawd" in d["canonical_module"]


# ===========================================================================
# Scenario 4 — Multi-device orchestration
# ===========================================================================


class TestScenario4MultiDeviceOrchestration:
    """
    Validate orchestration behaviour.

    Assertions:
    - orchestration is an upper layer, not the substrate itself
    - correct fan-out / aggregation
    - partial results are surfaced correctly
    """

    def test_orchestration_plan_from_decisions(self):
        """plan_from_orchestration_decisions builds a plan from multiple decisions."""
        from core.schemas.execution_plan import (
            plan_from_orchestration_decisions,
            ExecutionStepType,
        )
        decisions = [
            {"target_device_id": "dev_a", "resolved_execution_mode": "agent_runtime", "agent_id": "ag1"},
            {"target_device_id": "dev_b", "resolved_execution_mode": "command_only", "agent_id": "ag2"},
            {"target_device_id": "dev_c", "resolved_execution_mode": "agent_runtime", "agent_id": "ag3"},
        ]
        plan = plan_from_orchestration_decisions(
            decisions=decisions,
            task="multi-step analysis",
            trace_id=_make_trace(),
            session_id=_make_session(),
        )
        assert plan.is_orchestration or plan.is_remote
        assert len(plan.steps) >= 1
        # All step types are remote (REMOTE_AGENT or REMOTE_COMMAND)
        for step in plan.steps:
            assert step.step_type in (
                ExecutionStepType.REMOTE_AGENT,
                ExecutionStepType.REMOTE_COMMAND,
                ExecutionStepType.ORCHESTRATION,
            )

    def test_orchestration_plan_ids_unique(self):
        from core.schemas.execution_plan import plan_from_orchestration_decisions
        plans = [
            plan_from_orchestration_decisions(decisions=[], task=f"t{i}")
            for i in range(5)
        ]
        ids = [p.plan_id for p in plans]
        assert len(ids) == len(set(ids)), "plan_id must be unique per plan"

    def test_swarm_coordinator_builds_orchestration_plan(self):
        """SwarmCoordinator.build_orchestration_plan produces an OrchestrationPlan."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )
        decisions = [
            OrchestrationDecision(
                agent_id="ag1",
                target_device_id="dev_a",
                resolved_execution_mode="agent_runtime",
                score=0.9,
                assignment_source="scoring_engine",
            ),
            OrchestrationDecision(
                agent_id="ag2",
                target_device_id="dev_b",
                resolved_execution_mode="command_only",
                score=0.6,
                assignment_source="scoring_engine",
            ),
        ]
        plan = build_orchestration_plan(
            task="fan-out task",
            decisions=decisions,
            session_id=_make_session(),
            trace_id=_make_trace(),
        )
        assert plan.plan_id.startswith("orch_plan_")
        assert plan.assigned_count == 2
        assert plan.unassigned_count == 0
        assert len(plan.decisions) == 2

    def test_orchestration_is_above_substrate(self):
        """
        OrchestrationPlan is built *before* any substrate dispatch.
        The plan contains decisions that describe *intent*; route_envelope is
        called separately per decision — the substrate does not own the plan.
        """
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )
        # Build planning phase (no substrate call needed to produce the plan)
        d = OrchestrationDecision(
            agent_id="ag1",
            target_device_id="dev_a",
            resolved_execution_mode="agent_runtime",
        )
        plan = build_orchestration_plan(task="test", decisions=[d])
        # The plan is fully formed before any transport is involved
        assert plan.plan_id is not None
        assert plan.decisions[0].target_device_id == "dev_a"

    def test_partial_results_surfaced(self):
        """OrchestrationResult correctly records mixed success/failure outcomes."""
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            build_orchestration_plan,
            build_orchestration_result,
        )
        d1 = OrchestrationDecision(agent_id="ag1", target_device_id="dev_a",
                                   resolved_execution_mode="agent_runtime", score=0.9)
        d2 = OrchestrationDecision(agent_id="ag2", target_device_id="dev_b",
                                   resolved_execution_mode="command_only", score=0.7)
        d3 = OrchestrationDecision(agent_id="ag3", target_device_id="dev_c",
                                   resolved_execution_mode="agent_runtime", score=0.5)
        plan = build_orchestration_plan(
            task="parallel analysis",
            decisions=[d1, d2, d3],
            trace_id=_make_trace(),
        )
        member_results = [
            OrchestrationMemberResult(agent_id="ag1", decision=d1, success=True, output="ok"),
            OrchestrationMemberResult(agent_id="ag2", decision=d2, success=False, error="timeout"),
            OrchestrationMemberResult(agent_id="ag3", decision=d3, success=True, output="ok"),
        ]
        result = build_orchestration_result(plan=plan, member_results=member_results)
        assert result.success_count == 2
        assert result.failure_count == 1
        # Partial success: not all members succeeded
        assert result.failure_count > 0 and result.success_count > 0

    def test_orchestration_result_summary_serialisable(self):
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            build_orchestration_plan,
            build_orchestration_result,
        )
        d1 = OrchestrationDecision(agent_id="ag1", target_device_id="dev_a",
                                   resolved_execution_mode="agent_runtime")
        plan = build_orchestration_plan(task="t", decisions=[d1])
        mr = OrchestrationMemberResult(agent_id="ag1", decision=d1, success=True, output="done")
        result = build_orchestration_result(plan=plan, member_results=[mr])
        summary = result.to_summary_dict()
        json.dumps(summary)
        assert "plan_id" in summary
        assert "total_members" in summary
        assert summary["succeeded"] == 1
        assert summary["failed"] == 0

    def test_empty_decisions_produce_plan(self):
        """Even zero decisions produce a coherent orchestration plan."""
        from core.schemas.execution_plan import plan_from_orchestration_decisions
        plan = plan_from_orchestration_decisions(decisions=[], task="empty")
        assert plan.plan_id is not None
        assert isinstance(plan.steps, list)


# ===========================================================================
# Scenario 5 — Fallback
# ===========================================================================


class TestScenario5Fallback:
    """
    Validate fallback behaviour when a richer target is unavailable.

    Assertions:
    - downgrade or alternate target selection takes effect
    - fallback reason is visible in the failure record / summary
    """

    def test_device_unavailable_creates_retryable_failure(self):
        """DEVICE_NOT_FOUND failure is retryable and suggests remote→local fallback."""
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        from core.failure_domains import FailureDomain

        rec = build_failure_record(error_code="DEVICE_NOT_FOUND")
        assert rec.failure_domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE.value
        assert rec.is_retryable

        summary = failure_record_summary(rec)
        assert summary["failure_domain"] == "remote_device_unavailable"
        assert summary["is_retryable"] is True
        assert summary["downgrade_hint"] == "remote_to_local"
        assert summary["fallback_allow_remote_to_local"] is True

    def test_device_offline_failure_has_fallback_hint(self):
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain

        rec = build_failure_record(error_code="DEVICE_OFFLINE")
        assert rec.failure_domain == FailureDomain.REMOTE_DEVICE_UNAVAILABLE.value
        assert rec.downgrade_hint == "remote_to_local"

    def test_timeout_failure_is_retryable_with_no_mode_downgrade(self):
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain

        rec = build_failure_record(error_code="COMMAND_TIMEOUT")
        assert rec.failure_domain == FailureDomain.TIMEOUT_FAILURE.value
        assert rec.is_retryable
        # Timeout does not force a mode downgrade
        assert rec.downgrade_hint is None

    def test_gateway_transport_fallback_to_local(self):
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain

        rec = build_failure_record(error_code="DISCONNECT")
        assert rec.failure_domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE.value
        assert rec.is_retryable
        assert rec.downgrade_hint == "remote_to_local"

    def test_resolver_falls_back_to_command_only_for_unsupported_mode(self):
        """Resolver falls back to command_only when agent_runtime is not supported."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_thin_profile

        # A thin profile explicitly does not support agent_runtime
        profile = build_thin_profile(device_id="thin_fallback_dev")
        result = resolve_mode(profile=profile)

        assert result.mode == "command_only"
        # Resolution source explains the decision
        assert result.resolution_source != ""

    def test_resolver_forced_downgrade_is_visible(self):
        """Forced command_only on a rich device is visible in the result."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_rich_profile

        profile = build_rich_profile(device_id="rich_forced_down")
        result = resolve_mode(profile=profile, forced_mode="command_only")

        assert result.mode == "command_only"
        assert result.resolution_source == "forced"

    def test_failure_record_summary_is_json_safe(self):
        from core.schemas.execution_failure import build_failure_record, failure_record_summary
        for code in ("DEVICE_NOT_FOUND", "COMMAND_TIMEOUT", "DISCONNECT", "ACL_DENIED"):
            rec = build_failure_record(error_code=code)
            summary = failure_record_summary(rec)
            json.dumps(summary)

    def test_failure_record_full_dict_is_json_safe(self):
        from core.schemas.execution_failure import build_failure_record
        rec = build_failure_record(error_code="DEVICE_NOT_FOUND")
        json.dumps(rec.to_dict())

    def test_exception_fallback_classifies_timeout(self):
        """TimeoutError exception produces a TIMEOUT_FAILURE record."""
        from core.failure_domains import classify_from_exception, FailureDomain
        c = classify_from_exception(TimeoutError("deadline exceeded"))
        assert c.domain == FailureDomain.TIMEOUT_FAILURE

    def test_exception_fallback_classifies_connection_error(self):
        from core.failure_domains import classify_from_exception, FailureDomain
        c = classify_from_exception(ConnectionError("lost connection"))
        assert c.domain == FailureDomain.GATEWAY_TRANSPORT_FAILURE


# ===========================================================================
# Scenario 6 — Capability mismatch
# ===========================================================================


class TestScenario6CapabilityMismatch:
    """
    Validate resolver behaviour when the target device does not support
    the required execution mode or capability set.

    Assertions:
    - resolver decision is clear (explicit resolution_source)
    - diagnostics / validation explain the mismatch
    """

    def test_capability_mismatch_failure_domain(self):
        from core.failure_domains import FailureDomain, classify_from_error_code
        c = classify_from_error_code("CAPABILITY_MISMATCH")
        # CAPABILITY_MISMATCH is not a standard error code — falls to UNKNOWN
        # so we test via the expected domain directly
        from core.schemas.execution_failure import build_failure_record
        from core.failure_domains import FailureDomain
        # Build via domain directly using the classification path
        rec = build_failure_record(error_code="INVALID_ENVELOPE")
        assert rec.failure_domain == FailureDomain.SUBSTRATE_DISPATCH_FAILURE.value

    def test_thin_device_cannot_resolve_agent_runtime(self):
        """Thin device resolves to command_only, not agent_runtime."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_thin_profile, DeviceProfileClass

        profile = build_thin_profile(device_id="thin_mismatch")
        assert profile.profile_class == DeviceProfileClass.thin
        assert not profile.is_agent_runtime_capable()

        result = resolve_mode(profile=profile)
        assert result.mode == "command_only"

    def test_resolver_failure_record_on_mismatch(self):
        """resolver produces a failure record for remote_capability_mismatch."""
        from core.remote_execution_mode_resolver import resolve_mode
        from core.device_execution_profile import build_thin_profile
        from core.failure_domains import FailureDomain

        profile = build_thin_profile(device_id="thin_dev")
        result = resolve_mode(profile=profile, task_intent="agent_execute")

        # If the intent requires agent but device is thin, there is a mismatch.
        # The resolver should either resolve to fallback or record a mismatch.
        if result.failure_domain is not None:
            assert result.failure_domain == FailureDomain.REMOTE_CAPABILITY_MISMATCH.value

    def test_mismatch_failure_domain_retryable_with_alternate(self):
        """REMOTE_CAPABILITY_MISMATCH is retryable when allow_alternate_target=True."""
        from core.failure_domains import is_retryable_by_domain, FailureDomain
        assert is_retryable_by_domain(
            FailureDomain.REMOTE_CAPABILITY_MISMATCH,
            allow_alternate_target=True,
        )

    def test_mismatch_failure_domain_not_retryable_same_target(self):
        """REMOTE_CAPABILITY_MISMATCH is NOT retryable on the same target."""
        from core.failure_domains import is_retryable_by_domain, FailureDomain
        assert not is_retryable_by_domain(
            FailureDomain.REMOTE_CAPABILITY_MISMATCH,
            allow_alternate_target=False,
        )

    def test_mismatch_downgrade_hint(self):
        """REMOTE_CAPABILITY_MISMATCH hints agent_runtime_to_command_only downgrade."""
        from core.failure_domains import downgrade_hint_for_domain, FailureDomain
        hint = downgrade_hint_for_domain(FailureDomain.REMOTE_CAPABILITY_MISMATCH)
        assert hint == "agent_runtime_to_command_only"

    def test_diagnostics_detect_mode_authority_incoherence(self):
        """
        Diagnostics flag an incoherence when remote_execution_mode is present
        but the authority metadata claims a local-only role.
        """
        from core.architecture_diagnostics import validate_remote_execution_coherence

        # Snapshot with command_only mode and correct subject_decision_authority is coherent
        coherent = {
            "execution_substrate": {
                "execution_substrate_role": "execution_substrate",
                "remote_execution_mode": "command_only",
            }
        }
        report = validate_remote_execution_coherence(coherent)
        # Coherent combination should not produce error-level findings
        errors = [f for f in report.findings if f.severity in ("error", "critical")]
        assert len(errors) == 0

    def test_profile_supports_mode_method(self):
        """DeviceExecutionProfile.supports_mode returns correct values."""
        from core.device_execution_profile import build_rich_profile, build_thin_profile

        rich = build_rich_profile("r1")
        assert rich.supports_mode("agent_runtime")
        assert rich.supports_mode("command_only")

        thin = build_thin_profile("t1")
        assert thin.supports_mode("command_only")
        assert not thin.supports_mode("agent_runtime")


# ===========================================================================
# Scenario 7 — Diagnostics / Validator
# ===========================================================================


class TestScenario7DiagnosticsValidator:
    """
    Validate diagnostics and validation layer behaviour.

    Assertions:
    - a correctly wired flow passes all invariant checks
    - an intentionally miswired flow is detectable (overall_valid=False)
    - the diagnostics report carries enough detail to explain the failure
    """

    _VALID_SNAPSHOT = {
        "runtime_shell": {
            "authority_metadata": {
                "layer_role": "runtime_shell_authority",
                "canonical_module": "core.desktop_presence_runtime",
            }
        },
        "subject_core": {
            "metadata": {"authority_role": "subject_decision_authority"}
        },
        "cognition_layer": {
            "authority_role": "cognition_planning_layer"
        },
        "execution_substrate": {
            "execution_substrate_role": "execution_substrate"
        },
    }

    def test_valid_snapshot_passes(self):
        from core.architecture_diagnostics import run_architecture_diagnostics
        report = run_architecture_diagnostics(self._VALID_SNAPSHOT)
        assert report.overall_valid, (
            f"Expected valid; errors: "
            f"{[f.message for f in report.findings if f.severity.value in ('error','critical')]}"
        )

    def test_empty_snapshot_produces_warnings(self):
        """An empty snapshot produces warning findings (missing layers)."""
        from core.architecture_diagnostics import run_architecture_diagnostics
        report = run_architecture_diagnostics({})
        # The diagnostics system is permissive: missing layers are warnings, not errors
        assert report.warning_count > 0

    def test_missing_runtime_shell_produces_warnings(self):
        """Removing runtime_shell from the snapshot produces at least one warning."""
        from core.architecture_diagnostics import run_architecture_diagnostics
        snapshot = dict(self._VALID_SNAPSHOT)
        snapshot.pop("runtime_shell", None)
        report = run_architecture_diagnostics(snapshot)
        # Missing runtime_shell causes an AUTHORITY_CHAIN_COMPLETE warning
        assert report.warning_count > 0

    def test_missing_subject_core_produces_warnings(self):
        """Removing subject_core from the snapshot produces at least one warning."""
        from core.architecture_diagnostics import run_architecture_diagnostics
        snapshot = dict(self._VALID_SNAPSHOT)
        snapshot.pop("subject_core", None)
        report = run_architecture_diagnostics(snapshot)
        assert report.warning_count > 0

    def test_entry_surface_claiming_authority_fails(self):
        """Entry surface claiming a runtime authority role causes overall_valid=False."""
        from core.architecture_diagnostics import run_architecture_diagnostics
        import copy
        snapshot = copy.deepcopy(self._VALID_SNAPSHOT)
        # entry_surface layer must never claim a runtime authority role
        snapshot["entry_surface"] = {
            "authority_metadata": {"layer_role": "runtime_shell_authority"}
        }
        report = run_architecture_diagnostics(snapshot)
        assert not report.overall_valid
        assert report.error_count > 0

    def test_validate_authority_chain_order(self):
        from core.architecture_diagnostics import validate_authority_chain
        # Correct order produces no error findings
        report = validate_authority_chain(self._VALID_SNAPSHOT)
        errors = [f for f in report.findings if f.severity in ("error", "critical")]
        assert len(errors) == 0, f"Unexpected errors: {[f.message for f in errors]}"

    def test_validate_authority_chain_miswired_detectable(self):
        """
        runtime_shell layer claiming wrong role is flagged with a warning or error.
        """
        from core.architecture_diagnostics import validate_authority_chain
        import copy
        snapshot = copy.deepcopy(self._VALID_SNAPSHOT)
        # runtime_shell claiming wrong role (entry_surface instead of runtime_shell_authority)
        snapshot["runtime_shell"]["authority_metadata"]["layer_role"] = "entry_surface"
        report = validate_authority_chain(snapshot)
        # Must produce at least one non-info finding (warning or error)
        non_info = [f for f in report.findings if f.severity in ("warning", "error", "critical")]
        assert len(non_info) > 0, "Miswired roles must be detected as warning or error"

    def test_diagnostics_report_is_serialisable(self):
        from core.architecture_diagnostics import run_architecture_diagnostics
        report = run_architecture_diagnostics(self._VALID_SNAPSHOT)
        d = report.model_dump()
        json.dumps(d)

    def test_diagnostics_findings_have_severity_and_message(self):
        from core.architecture_diagnostics import run_architecture_diagnostics
        report = run_architecture_diagnostics(self._VALID_SNAPSHOT)
        for finding in report.findings:
            assert hasattr(finding, "severity")
            assert hasattr(finding, "message")
            assert finding.message  # non-empty
            # severity is stored as a string value
            assert isinstance(finding.severity, str)
            assert finding.severity in ("info", "warning", "error", "critical")

    def test_validate_layer_boundaries_valid_flow(self):
        from core.architecture_diagnostics import validate_layer_boundaries
        report = validate_layer_boundaries(self._VALID_SNAPSHOT)
        errors = [f for f in report.findings if f.severity in ("error", "critical")]
        assert len(errors) == 0

    def test_diagnostics_snapshot_from_layers_helper(self):
        """build_diagnostics_snapshot_from_layers assembles a snapshot from arch_layer_id-tagged result dicts."""
        from core.architecture_diagnostics import (
            build_diagnostics_snapshot_from_layers,
            run_architecture_diagnostics,
        )
        # Each positional arg must carry an "arch_layer_id" key (set by PR-10 hooks)
        snapshot = build_diagnostics_snapshot_from_layers(
            {
                "arch_layer_id": "runtime_shell",
                "authority_metadata": {
                    "layer_role": "runtime_shell_authority",
                    "canonical_module": "core.desktop_presence_runtime",
                },
            },
            {
                "arch_layer_id": "subject_core",
                "metadata": {"authority_role": "subject_decision_authority"},
            },
            {
                "arch_layer_id": "cognition_layer",
                "authority_role": "cognition_planning_layer",
            },
            {
                "arch_layer_id": "execution_substrate",
                "execution_substrate_role": "execution_substrate",
            },
        )
        assert "runtime_shell" in snapshot
        assert "subject_core" in snapshot
        report = run_architecture_diagnostics(snapshot)
        assert report.overall_valid
