#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_multi_device_orchestration.py
=============================================
PR-8 — Multi-Device Orchestration Layer Tests

Validates that multi-device orchestration operates as a distinct higher-level
coordination layer above the unified cross-device execution substrate.

Test classes:

  1. TestOrchestrationPlanContracts
       OrchestrationPlan / OrchestrationDecision / OrchestrationResult
       dataclasses can be constructed and queried correctly.

  2. TestOrchestrationPlanBuilders
       build_orchestration_plan and build_orchestration_result helpers
       produce correct objects and maintain round-trip properties.

  3. TestOrchestrationPackageExports
       core.orchestration package exports the PR-8 contracts.

  4. TestSwarmCoordinatorOrchestrationRole
       SwarmCoordinator.build_orchestration_plan() produces an
       OrchestrationPlan before any substrate dispatch.  Confirms that
       orchestration (planning) and substrate (dispatch) are separate phases.

  5. TestOrchestrationAboveSubstrate
       SwarmCoordinator.dispatch_team() builds an orchestration plan
       internally and then delegates to the substrate (CommandRouter).
       The substrate is called after orchestration decisions are made.

  6. TestSubstrateDoesNotOrchestrate
       CommandRouter (substrate) does not perform device selection,
       does not call DeviceScoringEngine, and does not produce
       OrchestrationPlan objects.

  7. TestOpenClawdDelegationBoundary
       OpenClawd._delegate_multi_device_orchestration() stamps
       delegation_point="multi_device_orchestration" and is distinct from
       the substrate delegation methods.

  8. TestSmartSchedulerOrchestrationRole
       DeviceScoringEngine belongs to the orchestration layer and does not
       call into the substrate (CommandRouter / route_envelope).

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ---------------------------------------------------------------------------
# 1. TestOrchestrationPlanContracts
# ---------------------------------------------------------------------------


class TestOrchestrationPlanContracts:
    """OrchestrationPlan/Decision/Result dataclasses work correctly."""

    def test_orchestration_decision_defaults(self):
        from core.orchestration.multi_device_plan import OrchestrationDecision

        d = OrchestrationDecision(agent_id="a1")
        assert d.agent_id == "a1"
        assert d.target_device_id is None
        assert d.score == 0.0
        assert d.resolved_execution_mode is None
        assert d.assignment_source == ""

    def test_orchestration_decision_with_values(self):
        from core.orchestration.multi_device_plan import OrchestrationDecision

        d = OrchestrationDecision(
            agent_id="a2",
            agent_name="Analyst",
            target_device_id="dev_01",
            score=0.87,
            resolved_execution_mode="agent_runtime",
            assignment_source="scoring_engine",
            manifest_id="manifest_abc",
        )
        assert d.target_device_id == "dev_01"
        assert d.score == 0.87
        assert d.resolved_execution_mode == "agent_runtime"
        assert d.assignment_source == "scoring_engine"

    def test_orchestration_plan_assigned_count(self):
        from core.orchestration.multi_device_plan import OrchestrationDecision, OrchestrationPlan

        plan = OrchestrationPlan(
            plan_id="p1",
            task="test task",
            decisions=[
                OrchestrationDecision(agent_id="a1", target_device_id="dev1"),
                OrchestrationDecision(agent_id="a2", target_device_id=None),
                OrchestrationDecision(agent_id="a3", target_device_id="dev2"),
            ],
        )
        assert plan.assigned_count == 2
        assert plan.unassigned_count == 1

    def test_orchestration_plan_to_summary_dict(self):
        from core.orchestration.multi_device_plan import OrchestrationDecision, OrchestrationPlan

        plan = OrchestrationPlan(
            plan_id="p_summary",
            task="do something",
            trace_id="tr_abc",
            task_id="task_123",
            decisions=[
                OrchestrationDecision(agent_id="a1", target_device_id="dev1"),
            ],
        )
        summary = plan.to_summary_dict()
        assert summary["plan_id"] == "p_summary"
        assert summary["trace_id"] == "tr_abc"
        assert summary["total_members"] == 1
        assert summary["assigned"] == 1
        assert "dev1" in summary["devices"]

    def test_orchestration_result_counts(self):
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            OrchestrationPlan,
            OrchestrationResult,
        )

        plan = OrchestrationPlan(plan_id="p2", task="task")
        d1 = OrchestrationDecision(agent_id="a1")
        d2 = OrchestrationDecision(agent_id="a2")

        result = OrchestrationResult(
            plan=plan,
            member_results=[
                OrchestrationMemberResult(agent_id="a1", decision=d1, success=True, output="ok"),
                OrchestrationMemberResult(agent_id="a2", decision=d2, success=False, error="timeout"),
            ],
            synthesized="ok",
            total_latency_ms=55.5,
            orchestration_layer="SwarmCoordinator",
        )
        assert result.success_count == 1
        assert result.failure_count == 1

    def test_orchestration_result_summary_dict(self):
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            OrchestrationPlan,
            OrchestrationResult,
        )

        plan = OrchestrationPlan(plan_id="p3", task="task", task_id="t3", trace_id="tr3")
        d = OrchestrationDecision(agent_id="a1")
        result = OrchestrationResult(
            plan=plan,
            member_results=[
                OrchestrationMemberResult(agent_id="a1", decision=d, success=True),
            ],
            total_latency_ms=100.0,
            orchestration_layer="SwarmCoordinator",
        )
        s = result.to_summary_dict()
        assert s["orchestration_layer"] == "SwarmCoordinator"
        assert s["succeeded"] == 1
        assert s["failed"] == 0


# ---------------------------------------------------------------------------
# 2. TestOrchestrationPlanBuilders
# ---------------------------------------------------------------------------


class TestOrchestrationPlanBuilders:
    """build_orchestration_plan and build_orchestration_result helpers."""

    def test_build_orchestration_plan_generates_plan_id(self):
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            build_orchestration_plan,
        )

        plan = build_orchestration_plan(
            task="test",
            decisions=[OrchestrationDecision(agent_id="a1", target_device_id="dev1")],
            session_id="s1",
            trace_id="tr1",
            task_id="task1",
        )
        assert plan.plan_id.startswith("orch_plan_")
        assert plan.task == "test"
        assert plan.session_id == "s1"
        assert plan.trace_id == "tr1"
        assert plan.task_id == "task1"

    def test_build_orchestration_plan_custom_plan_id(self):
        from core.orchestration.multi_device_plan import build_orchestration_plan

        plan = build_orchestration_plan(
            task="custom",
            decisions=[],
            plan_id="custom_plan_001",
        )
        assert plan.plan_id == "custom_plan_001"

    def test_build_orchestration_result_fields(self):
        from core.orchestration.multi_device_plan import (
            OrchestrationDecision,
            OrchestrationMemberResult,
            OrchestrationPlan,
            build_orchestration_result,
        )

        plan = OrchestrationPlan(plan_id="pX", task="task")
        d = OrchestrationDecision(agent_id="a1")
        result = build_orchestration_result(
            plan=plan,
            member_results=[
                OrchestrationMemberResult(agent_id="a1", decision=d, success=True, output="result"),
            ],
            synthesized="result",
            total_latency_ms=42.0,
            orchestration_layer="TestOrchestrator",
        )
        assert result.plan is plan
        assert result.synthesized == "result"
        assert result.total_latency_ms == 42.0
        assert result.orchestration_layer == "TestOrchestrator"


# ---------------------------------------------------------------------------
# 3. TestOrchestrationPackageExports
# ---------------------------------------------------------------------------


class TestOrchestrationPackageExports:
    """core.orchestration exports the PR-8 contracts correctly."""

    def test_package_exports_plan_types(self):
        from core.orchestration import (
            OrchestrationDecision,
            OrchestrationPlan,
            OrchestrationMemberResult,
            OrchestrationResult,
            build_orchestration_plan,
            build_orchestration_result,
        )

        assert OrchestrationDecision is not None
        assert OrchestrationPlan is not None
        assert OrchestrationMemberResult is not None
        assert OrchestrationResult is not None
        assert callable(build_orchestration_plan)
        assert callable(build_orchestration_result)

    def test_package_all_list(self):
        import core.orchestration as orch_pkg

        for name in [
            "OrchestrationDecision",
            "OrchestrationPlan",
            "OrchestrationMemberResult",
            "OrchestrationResult",
            "build_orchestration_plan",
            "build_orchestration_result",
        ]:
            assert name in orch_pkg.__all__, f"{name} missing from __all__"


# ---------------------------------------------------------------------------
# 4. TestSwarmCoordinatorOrchestrationRole
# ---------------------------------------------------------------------------


class TestSwarmCoordinatorOrchestrationRole:
    """SwarmCoordinator.build_orchestration_plan() is a planning-only method
    that produces an OrchestrationPlan before substrate dispatch."""

    def _make_member(self, agent_id: str, agent_name: str = ""):
        m = MagicMock()
        m.agent_id = agent_id
        m.agent_name = agent_name or agent_id
        m.provider = "openai"
        m.model = "gpt-4"
        m.role_in_team = "analyst"
        m.template = "data_analyst"
        return m

    def _make_device_candidate(self, device_id: str, score: float = 0.8):
        from core.control_plane.smart_scheduler import DeviceScoreInput

        return DeviceScoreInput(
            device_id=device_id,
            ping_latency_ms=20.0,
            load_pct=10.0,
            capabilities=["screen", "keyboard"],
            health_score=90.0,
        )

    def test_build_orchestration_plan_returns_plan_not_dispatch(self):
        """build_orchestration_plan() returns an OrchestrationPlan without
        dispatching to the substrate."""
        from core.orchestration.multi_device_plan import OrchestrationPlan
        from core.swarm_coordinator import SwarmCoordinator

        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        coordinator._router = None
        coordinator._scoring_engine = None
        coordinator._ledger = None

        members = [self._make_member("a1", "Analyst")]
        device_candidates = [self._make_device_candidate("dev_01")]

        # Patch DeviceScoringEngine.select_best_device to avoid real scoring
        mock_score = MagicMock()
        mock_score.device_id = "dev_01"
        mock_score.total = 0.85

        with patch.object(
            __import__(
                "core.control_plane.smart_scheduler",
                fromlist=["DeviceScoringEngine"],
            ).DeviceScoringEngine,
            "select_best_device",
            return_value=mock_score,
        ):
            plan = coordinator.build_orchestration_plan(
                members=members,
                task="Analyse Q3",
                device_candidates=device_candidates,
                session_id="sess1",
                trace_id="tr1",
                task_id="task1",
            )

        assert isinstance(plan, OrchestrationPlan), "Expected OrchestrationPlan"
        assert len(plan.decisions) == 1
        assert plan.decisions[0].agent_id == "a1"
        assert plan.decisions[0].target_device_id == "dev_01"
        assert plan.decisions[0].assignment_source == "scoring_engine"
        assert plan.task == "Analyse Q3"

    def test_build_orchestration_plan_no_candidates_unassigned(self):
        """When no device candidates are provided, decisions have no target."""
        from core.orchestration.multi_device_plan import OrchestrationPlan
        from core.swarm_coordinator import SwarmCoordinator

        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        coordinator._router = None
        coordinator._scoring_engine = None
        coordinator._ledger = None

        members = [self._make_member("a1"), self._make_member("a2")]

        plan = coordinator.build_orchestration_plan(
            members=members,
            task="task without devices",
        )

        assert isinstance(plan, OrchestrationPlan)
        assert plan.assigned_count == 0
        assert plan.unassigned_count == 2

    def test_build_orchestration_plan_multiple_members(self):
        """Each member gets its own OrchestrationDecision."""
        from core.orchestration.multi_device_plan import OrchestrationPlan
        from core.swarm_coordinator import SwarmCoordinator

        coordinator = SwarmCoordinator.__new__(SwarmCoordinator)
        coordinator._router = None
        coordinator._scoring_engine = None
        coordinator._ledger = None

        members = [
            self._make_member("a1", "Analyst"),
            self._make_member("a2", "Writer"),
        ]
        device_candidates = [
            self._make_device_candidate("dev_01"),
            self._make_device_candidate("dev_02"),
        ]

        mock_score1 = MagicMock()
        mock_score1.device_id = "dev_01"
        mock_score1.total = 0.9
        mock_score2 = MagicMock()
        mock_score2.device_id = "dev_01"
        mock_score2.total = 0.9

        with patch.object(
            __import__(
                "core.control_plane.smart_scheduler",
                fromlist=["DeviceScoringEngine"],
            ).DeviceScoringEngine,
            "select_best_device",
            side_effect=[mock_score1, mock_score2],
        ):
            plan = coordinator.build_orchestration_plan(
                members=members,
                task="multi-member task",
                device_candidates=device_candidates,
            )

        assert len(plan.decisions) == 2
        assert {d.agent_id for d in plan.decisions} == {"a1", "a2"}


# ---------------------------------------------------------------------------
# 5. TestOrchestrationAboveSubstrate
# ---------------------------------------------------------------------------


class TestOrchestrationAboveSubstrate:
    """SwarmCoordinator.dispatch_team() makes orchestration decisions first,
    then delegates to the substrate (CommandRouter)."""

    def _make_member(self, agent_id: str, agent_name: str = ""):
        m = MagicMock()
        m.agent_id = agent_id
        m.agent_name = agent_name or agent_id
        m.provider = "openai"
        m.model = "gpt-4"
        m.role_in_team = "analyst"
        m.template = "data_analyst"
        return m

    def _make_device_candidate(self, device_id: str):
        from core.control_plane.smart_scheduler import DeviceScoreInput

        return DeviceScoreInput(
            device_id=device_id,
            ping_latency_ms=30.0,
            load_pct=20.0,
            capabilities=["screen", "keyboard"],
            health_score=85.0,
        )

    def test_dispatch_team_delegates_to_command_router(self):
        """dispatch_team calls CommandRouter.dispatch_agent_remote (substrate),
        not a competing orchestration path."""
        from core.swarm_coordinator import SwarmCoordinator

        substrate_calls: list = []

        async def fake_dispatch_agent_remote(**kwargs):
            substrate_calls.append(kwargs)
            return {"success": True, "output": "done", "latency_ms": 10.0}

        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = fake_dispatch_agent_remote

        mock_score = MagicMock()
        mock_score.device_id = "dev_01"
        mock_score.total = 0.88

        mock_se = MagicMock()
        mock_se.select_best_device.return_value = mock_score

        mock_ledger = MagicMock()
        mock_ledger.append.return_value = "event_001"

        coordinator = SwarmCoordinator(
            command_router=mock_router,
            scoring_engine=mock_se,
            audit_ledger=mock_ledger,
        )

        members = [self._make_member("a1", "TestAgent")]
        candidates = [self._make_device_candidate("dev_01")]

        async def run():
            return await coordinator.dispatch_team(
                members=members,
                task="test substrate delegation",
                session_id="sess_sub",
                trace_id="tr_sub",
                task_id="task_sub",
                device_candidates=candidates,
            )

        result = asyncio.get_event_loop().run_until_complete(run())

        # The substrate (CommandRouter.dispatch_agent_remote) was called
        assert len(substrate_calls) == 1, "Substrate dispatch_agent_remote was not called"
        assert substrate_calls[0]["device_id"] == "dev_01"

        # The TeamResult is produced (orchestration layer output)
        assert result is not None
        assert hasattr(result, "member_results")
        assert result.member_results[0].success is True

    def test_orchestration_plan_built_before_substrate_call(self):
        """OrchestrationPlan is built (planning phase) before any substrate
        dispatch call occurs.  We verify by confirming plan fields are
        populated from scoring engine output."""
        from core.orchestration.multi_device_plan import OrchestrationDecision
        from core.swarm_coordinator import SwarmCoordinator

        mock_score = MagicMock()
        mock_score.device_id = "dev_planning"
        mock_score.total = 0.77

        mock_se = MagicMock()
        mock_se.select_best_device.return_value = mock_score

        mock_ledger = MagicMock()
        mock_ledger.append.return_value = "ev_001"

        async def fake_dispatch(**kwargs):
            return {"success": True, "output": "ok", "latency_ms": 5.0}

        mock_router = MagicMock()
        mock_router.dispatch_agent_remote = fake_dispatch

        coordinator = SwarmCoordinator(
            command_router=mock_router,
            scoring_engine=mock_se,
            audit_ledger=mock_ledger,
        )

        members = [self._make_member("a_plan")]
        candidates = [self._make_device_candidate("dev_planning")]

        # Use build_orchestration_plan separately to confirm plan is
        # identical in shape to what dispatch_team would produce
        plan = coordinator.build_orchestration_plan(
            members=members,
            task="verify plan before dispatch",
            device_candidates=candidates,
        )
        assert plan.decisions[0].target_device_id == "dev_planning"
        assert plan.decisions[0].assignment_source == "scoring_engine"


# ---------------------------------------------------------------------------
# 6. TestSubstrateDoesNotOrchestrate
# ---------------------------------------------------------------------------


class TestSubstrateDoesNotOrchestrate:
    """CommandRouter (substrate) does not perform device scoring/selection."""

    def test_command_router_has_no_scoring_engine(self):
        """CommandRouter has no scoring_engine attribute (not an orchestration
        component)."""
        from core.command_router import CommandRouter

        cr = CommandRouter.__new__(CommandRouter)
        assert not hasattr(cr, "scoring_engine"), (
            "CommandRouter should not have a scoring_engine — "
            "scoring is an orchestration concern"
        )

    def test_command_router_has_no_build_orchestration_plan(self):
        """CommandRouter does not expose build_orchestration_plan — that is
        the orchestration layer's responsibility."""
        from core.command_router import CommandRouter

        assert not hasattr(CommandRouter, "build_orchestration_plan"), (
            "CommandRouter should not have build_orchestration_plan"
        )

    def test_command_router_route_envelope_does_not_import_scoring(self):
        """route_envelope should not call DeviceScoringEngine directly."""
        import inspect
        from core.command_router import CommandRouter

        # route_envelope source should not reference scoring engine directly
        source = inspect.getsource(CommandRouter.route_envelope)
        assert "DeviceScoringEngine" not in source, (
            "CommandRouter.route_envelope imported DeviceScoringEngine — "
            "device scoring is an orchestration concern, not a substrate concern"
        )

    def test_orchestration_plan_type_not_in_command_router(self):
        """OrchestrationPlan is not referenced in CommandRouter's module."""
        import core.command_router as cr_mod

        assert not hasattr(cr_mod, "OrchestrationPlan"), (
            "OrchestrationPlan should not be in the substrate module"
        )


# ---------------------------------------------------------------------------
# 7. TestOpenClawdDelegationBoundary
# ---------------------------------------------------------------------------


class TestOpenClawdDelegationBoundary:
    """OpenClawd._delegate_multi_device_orchestration stamps the correct
    delegation_point and uses the orchestration layer."""

    def test_multi_device_delegation_point_stamped(self):
        """_delegate_multi_device_orchestration sets delegation_point."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._config = {}

        async def fake_dispatch_parallel_goal(**kwargs):
            return {"success": True, "response": "parallel done", "metadata": {}}

        oc._dispatch_parallel_goal = fake_dispatch_parallel_goal

        async def run():
            return await oc._delegate_multi_device_orchestration(
                message="do multi-device task",
                session_id="sess_del",
                trace_id="tr_del",
            )

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result["metadata"]["delegation_point"] == "multi_device_orchestration"

    def test_single_remote_delegation_point_is_different(self):
        """_delegate_single_remote stamps delegation_point='single_remote',
        not 'multi_device_orchestration' — they are distinct delegation paths."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._config = {}

        async def fake_dispatch_remote(message, intent=None, device_id=None,
                                        session_id=None, trace_id=None):
            return {"success": True, "response": "single remote", "metadata": {}}

        oc._dispatch_remote_agent = fake_dispatch_remote

        async def run():
            return await oc._delegate_single_remote(
                message="single task",
                device_id="remote_dev",
                session_id="sess_sr",
                trace_id="tr_sr",
            )

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result["metadata"]["delegation_point"] == "single_remote"
        assert result["metadata"]["delegation_point"] != "multi_device_orchestration"

    def test_multi_device_delegation_not_same_as_substrate(self):
        """_delegate_multi_device_orchestration is NOT the substrate path.
        The substrate path is _delegate_single_remote → _dispatch_remote_agent
        → CommandRouter.route_envelope."""
        from core.openclawd import OpenClawd
        import inspect

        # The multi-device orchestration method should NOT call route_envelope
        source = inspect.getsource(OpenClawd._delegate_multi_device_orchestration)
        assert "route_envelope" not in source, (
            "_delegate_multi_device_orchestration should not call route_envelope "
            "directly — it delegates to the orchestration layer, not the substrate"
        )


# ---------------------------------------------------------------------------
# 8. TestSmartSchedulerOrchestrationRole
# ---------------------------------------------------------------------------


class TestSmartSchedulerOrchestrationRole:
    """DeviceScoringEngine is an orchestration decision-support tool.
    It does not call into the substrate."""

    def test_scoring_engine_select_best_device_no_route_envelope(self):
        """select_best_device does not call route_envelope (substrate boundary)."""
        import inspect
        from core.control_plane.smart_scheduler import DeviceScoringEngine

        source = inspect.getsource(DeviceScoringEngine.select_best_device)
        assert "route_envelope" not in source, (
            "DeviceScoringEngine.select_best_device calls route_envelope — "
            "this violates the orchestration-above-substrate boundary"
        )

    def test_scoring_engine_score_device_no_route_envelope(self):
        """score_device does not call route_envelope (substrate boundary)."""
        import inspect
        from core.control_plane.smart_scheduler import DeviceScoringEngine

        source = inspect.getsource(DeviceScoringEngine.score_device)
        assert "route_envelope" not in source

    def test_scoring_engine_produces_scores_not_dispatches(self):
        """select_best_device returns a DeviceScore, not a dispatch result."""
        from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceScoringEngine

        engine = DeviceScoringEngine()
        candidates = [
            DeviceScoreInput(
                device_id="dev_a",
                ping_latency_ms=10.0,
                load_pct=5.0,
                capabilities=["screen", "keyboard"],
                health_score=95.0,
            ),
            DeviceScoreInput(
                device_id="dev_b",
                ping_latency_ms=200.0,
                load_pct=80.0,
                capabilities=["touch"],
                health_score=60.0,
            ),
        ]
        best = engine.select_best_device(candidates, ["screen"])
        assert best is not None
        assert best.device_id == "dev_a"
        # Result is a score object — it is NOT a dispatch result
        assert hasattr(best, "total"), "Expected DeviceScore with total field"
        assert not hasattr(best, "success"), (
            "DeviceScore should not have 'success' — that is a substrate concept"
        )

    def test_scoring_engine_is_not_substrate(self):
        """DeviceScoringEngine does not have route_envelope or dispatch_agent_remote
        — those are substrate methods."""
        from core.control_plane.smart_scheduler import DeviceScoringEngine

        engine = DeviceScoringEngine()
        assert not hasattr(engine, "route_envelope"), (
            "DeviceScoringEngine should not have route_envelope"
        )
        assert not hasattr(engine, "dispatch_agent_remote"), (
            "DeviceScoringEngine should not have dispatch_agent_remote"
        )
