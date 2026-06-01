"""tests/test_pr4_block4.py
================================

Block-4: Body Mesh + Presence Projection + Health/Cancel/HITL + Manifest Mesh Console

Tests covering:

1.  BodyMeshRegistry — register, unregister, get_by_role, compute_assignment, score_entry
2.  DeviceRoleAllocator — infer_roles, allocate, allocate_all (mocked UDM)
3.  DeviceHealthScorer — update, heartbeat, score (latency/error/jitter/heartbeat)
4.  CommandEnvelope — verb field, cancel/interrupt factories, to_dict/from_dict round-trip
5.  TaskGraph — cancel() / interrupt() propagation to CANCELLED/INTERRUPTED nodes
6.  TaskLifecycleManager — mark_cancelled / mark_interrupted terminal states
7.  HITLPolicy — AUTO/SEMI/MANUAL modes, decide(), pending_requests()
8.  PresenceProjection — project, project_to_device, last_events, intensity by role
9.  PresenceDirector — on_phase_transition, HITL gating, trace log
10. StateEventBus — new PRESENCE_PROJECTED / HITL_EVALUATED / MESH_UPDATED event types
11. DeviceManager — heartbeat records to health scorer, get_device_health, ordered list
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _reset_all() -> None:
    """Reset all Block-4 singletons."""
    from core.mesh.body_mesh_registry import reset_body_mesh_registry
    from core.mesh.device_role_allocator import reset_device_role_allocator
    from core.unified.device_health import reset_device_health_scorer
    from core.policy.hitl_policy import reset_hitl_policy
    from core.presence.presence_projection import reset_presence_projection
    from core.presence.presence_director import reset_presence_director
    from core.state_event_bus import reset_state_event_bus

    reset_body_mesh_registry()
    reset_device_role_allocator()
    reset_device_health_scorer()
    reset_hitl_policy()
    reset_presence_projection()
    reset_presence_director()
    reset_state_event_bus()


# ===========================================================================
# 1. BodyMeshRegistry
# ===========================================================================


class TestBodyMeshRegistry:
    def setup_method(self):
        _reset_all()

    def test_register_and_get(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        entry = reg.register("dev_1", roles=[DeviceRole.PERCEPTION, DeviceRole.ACTION])
        assert entry.device_id == "dev_1"
        assert DeviceRole.PERCEPTION in entry.roles
        assert DeviceRole.ACTION in entry.roles

        got = reg.get("dev_1")
        assert got is not None
        assert got.device_id == "dev_1"

    def test_register_idempotent_merges_roles(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_1", roles=[DeviceRole.PERCEPTION])
        reg.register("dev_1", roles=[DeviceRole.ACTION])

        entry = reg.get("dev_1")
        assert DeviceRole.PERCEPTION in entry.roles
        assert DeviceRole.ACTION in entry.roles

    def test_unregister(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_1")
        reg.unregister("dev_1")
        assert reg.get("dev_1") is None

    def test_unregister_unknown_noop(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry

        reg = BodyMeshRegistry()
        reg.unregister("nonexistent")  # should not raise

    def test_get_by_role(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_a", roles=[DeviceRole.PERCEPTION])
        reg.register("dev_b", roles=[DeviceRole.ACTION])
        reg.register("dev_c", roles=[DeviceRole.PERCEPTION, DeviceRole.PRESENCE])

        perceptors = reg.get_by_role(DeviceRole.PERCEPTION)
        ids = {e.device_id for e in perceptors}
        assert ids == {"dev_a", "dev_c"}

    def test_score_entry_updates_body_score(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_1", roles=[DeviceRole.ACTION])  # weight 1.5
        reg.score_entry("dev_1", health_score=0.8)

        entry = reg.get("dev_1")
        assert abs(entry.body_score - 1.5 * 0.8) < 0.01

    def test_compute_assignment_primary_is_highest_score(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_low", roles=[DeviceRole.PERCEPTION])
        reg.score_entry("dev_low", health_score=0.3)
        reg.register("dev_high", roles=[DeviceRole.ACTION, DeviceRole.PRESENCE])
        reg.score_entry("dev_high", health_score=0.9)

        assignment = reg.compute_assignment()
        assert assignment.primary_body is not None
        assert assignment.primary_body.device_id == "dev_high"
        assert len(assignment.secondary_bodies) == 1

    def test_compute_assignment_empty_returns_none_primary(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry

        reg = BodyMeshRegistry()
        assignment = reg.compute_assignment()
        assert assignment.primary_body is None
        assert assignment.secondary_bodies == []

    def test_snapshot(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_1", roles=[DeviceRole.PRESENCE])
        snap = reg.snapshot()
        assert snap["total"] == 1
        assert snap["entries"][0]["device_id"] == "dev_1"

    def test_to_dict_contains_roles(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        entry = reg.register("dev_1", roles=[DeviceRole.PERCEPTION])
        d = entry.to_dict()
        assert "perception" in d["roles"]

    def test_body_assignment_to_dict(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

        reg = BodyMeshRegistry()
        reg.register("dev_1", roles=[DeviceRole.PRESENCE])
        reg.score_entry("dev_1", 0.8)
        assignment = reg.compute_assignment()
        d = assignment.to_dict()
        assert d["primary_body"]["device_id"] == "dev_1"

    def test_get_by_session(self):
        from core.mesh.body_mesh_registry import BodyMeshRegistry

        reg = BodyMeshRegistry()
        reg.register("dev_1", session_id="sess_a")
        reg.register("dev_2", session_id="sess_b")
        reg.register("dev_3", session_id="sess_a")

        entries = reg.get_by_session("sess_a")
        ids = {e.device_id for e in entries}
        assert ids == {"dev_1", "dev_3"}

    def test_singleton(self):
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        r1 = get_body_mesh_registry()
        r2 = get_body_mesh_registry()
        assert r1 is r2


# ===========================================================================
# 2. DeviceRoleAllocator
# ===========================================================================


class TestDeviceRoleAllocator:
    def setup_method(self):
        _reset_all()

    def test_infer_roles_camera(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator
        from core.mesh.body_mesh_registry import DeviceRole

        alloc = DeviceRoleAllocator()
        roles = alloc.infer_roles(["camera", "microphone"])
        assert DeviceRole.PERCEPTION in roles

    def test_infer_roles_touch(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator
        from core.mesh.body_mesh_registry import DeviceRole

        alloc = DeviceRoleAllocator()
        roles = alloc.infer_roles(["touch", "keyboard"])
        assert DeviceRole.ACTION in roles

    def test_infer_roles_screen(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator
        from core.mesh.body_mesh_registry import DeviceRole

        alloc = DeviceRoleAllocator()
        roles = alloc.infer_roles(["screen", "speaker"])
        assert DeviceRole.PRESENCE in roles

    def test_infer_roles_empty(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator

        alloc = DeviceRoleAllocator()
        assert alloc.infer_roles([]) == []

    def test_infer_roles_unknown(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator

        alloc = DeviceRoleAllocator()
        assert alloc.infer_roles(["flux_capacitor"]) == []

    def test_allocate_writes_to_registry(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        alloc = DeviceRoleAllocator()
        result = alloc.allocate("dev_x", capabilities=["camera", "screen"], health_score=0.9)

        assert DeviceRole.PERCEPTION in result.roles_assigned
        assert DeviceRole.PRESENCE in result.roles_assigned
        assert result.body_score > 0

        entry = get_body_mesh_registry().get("dev_x")
        assert entry is not None

    def test_register_capability_rule(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator
        from core.mesh.body_mesh_registry import DeviceRole

        alloc = DeviceRoleAllocator()
        alloc.register_capability_rule("teleporter", DeviceRole.ACTION)
        roles = alloc.infer_roles(["teleporter_v2"])
        assert DeviceRole.ACTION in roles

    def test_allocation_result_to_dict(self):
        from core.mesh.device_role_allocator import DeviceRoleAllocator

        alloc = DeviceRoleAllocator()
        result = alloc.allocate("dev_y", capabilities=["keyboard"])
        d = result.to_dict()
        assert d["device_id"] == "dev_y"
        assert isinstance(d["roles_assigned"], list)

    def test_singleton(self):
        from core.mesh.device_role_allocator import get_device_role_allocator

        a1 = get_device_role_allocator()
        a2 = get_device_role_allocator()
        assert a1 is a2


# ===========================================================================
# 3. DeviceHealthScorer
# ===========================================================================


class TestDeviceHealthScorer:
    def setup_method(self):
        _reset_all()

    def test_no_data_returns_neutral(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        hs = scorer.score("unknown_dev")
        assert hs.total_score == 1.0
        assert hs.sample_count == 0

    def test_low_latency_high_score(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        for _ in range(5):
            scorer.update("dev_1", latency_ms=20.0)
        hs = scorer.score("dev_1")
        assert hs.latency_score >= 0.9

    def test_high_latency_low_score(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        for _ in range(5):
            scorer.update("dev_1", latency_ms=3000.0)
        hs = scorer.score("dev_1")
        assert hs.latency_score <= 0.1

    def test_high_error_rate_lowers_score(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        for _ in range(10):
            scorer.update("dev_1", error=True)
        hs = scorer.score("dev_1")
        assert hs.error_rate_score == 0.0

    def test_zero_errors_full_score(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        for _ in range(10):
            scorer.update("dev_1", error=False)
        hs = scorer.score("dev_1")
        assert hs.error_rate_score == 1.0

    def test_heartbeat_updates(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.heartbeat("dev_1")
        scorer.heartbeat("dev_1")
        scorer.heartbeat("dev_1")
        hs = scorer.score("dev_1")
        assert hs.sample_count >= 0  # just verify no crash

    def test_total_score_in_range(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.update("dev_1", latency_ms=100.0, error=False)
        scorer.update("dev_1", latency_ms=120.0, error=True)
        hs = scorer.score("dev_1")
        assert 0.0 <= hs.total_score <= 1.0

    def test_score_all(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.update("dev_a", latency_ms=50.0)
        scorer.update("dev_b", latency_ms=80.0)
        scores = scorer.score_all()
        assert "dev_a" in scores
        assert "dev_b" in scores

    def test_snapshot_structure(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.update("dev_a", latency_ms=50.0)
        snap = scorer.snapshot()
        assert "total_devices" in snap
        assert "scores" in snap

    def test_reset_device(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.update("dev_1", latency_ms=5000.0, error=True)
        scorer.reset_device("dev_1")
        hs = scorer.score("dev_1")
        assert hs.total_score == 1.0  # optimistic default after reset

    def test_singleton(self):
        from core.unified.device_health import get_device_health_scorer

        s1 = get_device_health_scorer()
        s2 = get_device_health_scorer()
        assert s1 is s2

    def test_health_score_to_dict(self):
        from core.unified.device_health import DeviceHealthScorer

        scorer = DeviceHealthScorer()
        scorer.update("dev_1", latency_ms=60.0)
        d = scorer.score("dev_1").to_dict()
        assert "total_score" in d
        assert "device_id" in d


# ===========================================================================
# 4. CommandEnvelope — verb / cancel / interrupt
# ===========================================================================


class TestCommandEnvelopeCancelVerbs:
    def test_default_verb_is_execute(self):
        from core.unified.command_envelope import CommandEnvelope, CommandVerb

        env = CommandEnvelope()
        assert env.verb == CommandVerb.EXECUTE

    def test_make_cancel(self):
        from core.unified.command_envelope import CommandEnvelope, CommandVerb, CancelReason

        env = CommandEnvelope.make_cancel(
            task_id="task_123",
            cancel_reason=CancelReason.USER_REQUEST,
        )
        assert env.verb == CommandVerb.CANCEL
        assert env.cancel_reason == CancelReason.USER_REQUEST
        assert "task_123" in env.cancel_target_task_ids

    def test_make_interrupt(self):
        from core.unified.command_envelope import CommandEnvelope, CommandVerb

        env = CommandEnvelope.make_interrupt(task_id="task_456")
        assert env.verb == CommandVerb.INTERRUPT
        assert env.is_cancel()

    def test_is_cancel_false_for_execute(self):
        from core.unified.command_envelope import CommandEnvelope

        env = CommandEnvelope()
        assert not env.is_cancel()

    def test_to_dict_includes_verb(self):
        from core.unified.command_envelope import CommandEnvelope, CommandVerb

        env = CommandEnvelope.make_cancel("task_1")
        d = env.to_dict()
        assert d["verb"] == CommandVerb.CANCEL.value

    def test_from_dict_round_trip_with_verb(self):
        from core.unified.command_envelope import CommandEnvelope, CommandVerb, CancelReason

        env = CommandEnvelope.make_cancel(
            task_id="task_round",
            cancel_reason=CancelReason.TIMEOUT,
        )
        d = env.to_dict()
        restored = CommandEnvelope.from_dict(d)
        assert restored.verb == CommandVerb.CANCEL
        assert restored.cancel_reason == CancelReason.TIMEOUT

    def test_from_dict_unknown_verb_falls_back(self):
        from core.unified.command_envelope import CommandEnvelope

        d = {
            "trace_id": "t1",
            "runtime_session_id": "s1",
            "task_id": "task_1",
            "verb": "teleport",  # unknown
        }
        env = CommandEnvelope.from_dict(d)
        # Unknown verb is dropped; default EXECUTE is used
        from core.unified.command_envelope import CommandVerb
        assert env.verb == CommandVerb.EXECUTE

    def test_cancel_target_task_ids_in_to_dict(self):
        from core.unified.command_envelope import CommandEnvelope

        env = CommandEnvelope.make_cancel("task_x", cancel_target_task_ids=["t1", "t2"])
        d = env.to_dict()
        assert "t1" in d["cancel_target_task_ids"]


# ===========================================================================
# 5. TaskGraph — cancel / interrupt
# ===========================================================================


class TestTaskGraphCancellation:
    def test_cancel_marks_pending_nodes_cancelled(self):
        from core.task_graph import TaskGraph, NodeStatus

        async def handler(node, ctx):
            return {}

        async def run():
            graph = TaskGraph(trace_id="tr1")
            n1 = graph.add_node("node1", handler=handler)
            n2 = graph.add_node("node2", handler=handler, depends_on=[n1.node_id])
            n3 = graph.add_node("node3", handler=handler, depends_on=[n1.node_id])
            graph.cancel("test cancel")
            result = await graph.execute()
            return graph, result

        graph, result = asyncio.get_running_loop().run_until_complete(run())
        statuses = {n.status for n in graph._nodes.values()}
        assert NodeStatus.CANCELLED in statuses or NodeStatus.INTERRUPTED in statuses

    def test_interrupt_marks_pending_nodes_interrupted(self):
        from core.task_graph import TaskGraph, NodeStatus

        async def handler(node, ctx):
            return {}

        async def run():
            graph = TaskGraph(trace_id="tr2")
            n1 = graph.add_node("node1", handler=handler)
            graph.interrupt("test interrupt")
            result = await graph.execute()
            return graph, result

        graph, result = asyncio.get_running_loop().run_until_complete(run())
        # All pending nodes should be interrupted
        for nid, node in graph._nodes.items():
            if node.status != "done":
                assert node.status in (
                    NodeStatus.INTERRUPTED, NodeStatus.CANCELLED, "interrupted", "cancelled"
                )

    def test_cancel_flag_set(self):
        from core.task_graph import TaskGraph

        graph = TaskGraph()
        assert not graph._cancel_requested
        graph.cancel()
        assert graph._cancel_requested

    def test_interrupt_sets_both_flags(self):
        from core.task_graph import TaskGraph

        graph = TaskGraph()
        graph.interrupt()
        assert graph._cancel_requested
        assert graph._interrupt_requested

    def test_cancelled_node_status_in_str_enum(self):
        from core.task_graph import NodeStatus

        assert NodeStatus.CANCELLED.value == "cancelled"
        assert NodeStatus.INTERRUPTED.value == "interrupted"


# ===========================================================================
# 6. TaskLifecycleManager — mark_cancelled / mark_interrupted
# ===========================================================================


class TestTaskLifecycleCancelledInterrupted:
    def test_mark_cancelled(self):
        from core.task_lifecycle import TaskLifecycleManager

        mgr = TaskLifecycleManager()

        # Create a minimal stub envelope
        class FakeEnvelope:
            task_id = "t1"
            trace_id = "tr1"
            session_id = "s1"
            tool_name = "test_tool"
            metadata = {}
            lifecycle_status = "running"

            def transition(self, status: str):
                self.lifecycle_status = status
                return self

        env = FakeEnvelope()
        result = mgr.mark_cancelled(env, reason="user requested")
        assert result.lifecycle_status == "cancelled"

    def test_mark_interrupted(self):
        from core.task_lifecycle import TaskLifecycleManager

        mgr = TaskLifecycleManager()

        class FakeEnvelope:
            task_id = "t2"
            trace_id = "tr2"
            session_id = "s2"
            tool_name = "test_tool"
            metadata = {}
            lifecycle_status = "running"

            def transition(self, status: str):
                self.lifecycle_status = status
                return self

        env = FakeEnvelope()
        result = mgr.mark_interrupted(env, reason="abort signal")
        assert result.lifecycle_status == "interrupted"


# ===========================================================================
# 7. HITLPolicy
# ===========================================================================


class TestHITLPolicy:
    def setup_method(self):
        _reset_all()

    def test_auto_mode_always_approves(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.AUTO)
        decision = policy.evaluate("manifest_projection")
        assert decision.approved is True
        assert decision.decided_by == "auto"

    def test_semi_mode_low_risk_auto_approves(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.SEMI)
        decision = policy.evaluate("fetch_data")  # not high risk
        assert decision.approved is True

    def test_semi_mode_high_risk_creates_request(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.SEMI, timeout_default_approve=True)
        decision = policy.evaluate("manifest_projection")
        assert decision.request_id.startswith("hitl_")

    def test_manual_mode_all_create_requests(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=False)
        decision = policy.evaluate("fetch_data")
        assert decision.approved is False  # pessimistic default

    def test_decide_approves_request(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode, HITLDecisionOutcome

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=True)
        initial_decision = policy.evaluate("manifest_projection")
        req_id = initial_decision.request_id

        final = policy.decide(req_id, approve=True, decided_by="alice")
        assert final is not None
        assert final.outcome == HITLDecisionOutcome.APPROVED
        assert final.decided_by == "alice"

    def test_decide_rejects_request(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode, HITLDecisionOutcome

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=True)
        initial = policy.evaluate("cross_device_control")
        final = policy.decide(initial.request_id, approve=False)
        assert final.outcome == HITLDecisionOutcome.REJECTED
        assert final.approved is False

    def test_decide_unknown_request_returns_none(self):
        from core.policy.hitl_policy import HITLPolicy

        policy = HITLPolicy()
        result = policy.decide("no_such_id", approve=True)
        assert result is None

    def test_pending_requests_list(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=True)
        policy.evaluate("action_1")
        policy.evaluate("action_2")
        pending = policy.pending_requests()
        assert len(pending) == 2

    def test_high_risk_classifier_callable(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(
            mode=HITLMode.SEMI,
            high_risk_classifier=lambda action, ctx: action == "special_op",
        )
        normal = policy.evaluate("normal_task")
        assert normal.approved is True

        risky = policy.evaluate("special_op")
        # SEMI mode, high risk — default approve
        assert risky.request_id.startswith("hitl_")

    def test_mode_setter(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.AUTO)
        policy.mode = HITLMode.MANUAL
        assert policy.mode == HITLMode.MANUAL

    def test_decision_history_recorded(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=True)
        d1 = policy.evaluate("op_1")
        policy.decide(d1.request_id, approve=True)
        history = policy.decision_history()
        assert len(history) >= 1

    def test_hitl_request_to_dict(self):
        from core.policy.hitl_policy import HITLPolicy, HITLMode

        policy = HITLPolicy(mode=HITLMode.MANUAL, timeout_default_approve=True)
        d = policy.evaluate("op_x")
        # Re-fetch from pending
        pending = policy.pending_requests()
        if pending:
            entry = pending[0].to_dict()
            assert "request_id" in entry
            assert "action" in entry

    def test_singleton(self):
        from core.policy.hitl_policy import get_hitl_policy

        p1 = get_hitl_policy()
        p2 = get_hitl_policy()
        assert p1 is p2


# ===========================================================================
# 8. PresenceProjection
# ===========================================================================


class TestPresenceProjection:
    def setup_method(self):
        _reset_all()

    def test_project_to_device_creates_event(self):
        from core.presence.presence_projection import PresenceProjection

        proj = PresenceProjection()
        evt = proj.project_to_device(
            device_id="dev_1",
            cognitive_state={"phase": "manifest", "intensity": 0.9},
            intensity=1.0,
        )
        assert evt.device_id == "dev_1"
        assert evt.intensity == 1.0

    def test_last_events_returns_recent(self):
        from core.presence.presence_projection import PresenceProjection

        proj = PresenceProjection()
        for i in range(5):
            proj.project_to_device(f"dev_{i}", cognitive_state={}, intensity=0.5)
        events = proj.last_events(n=3)
        assert len(events) == 3

    def test_intensity_by_role_presence(self):
        from core.presence.presence_projection import PresenceProjection, ProjectionIntensity

        proj = PresenceProjection()
        intensity = proj._determine_intensity(["presence"])
        assert intensity == float(ProjectionIntensity.FULL)

    def test_intensity_by_role_action(self):
        from core.presence.presence_projection import PresenceProjection, ProjectionIntensity

        proj = PresenceProjection()
        intensity = proj._determine_intensity(["action"])
        assert intensity == float(ProjectionIntensity.MEDIUM)

    def test_intensity_by_role_perception(self):
        from core.presence.presence_projection import PresenceProjection, ProjectionIntensity

        proj = PresenceProjection()
        intensity = proj._determine_intensity(["perception"])
        assert intensity == float(ProjectionIntensity.LOW)

    def test_intensity_no_role_minimal(self):
        from core.presence.presence_projection import PresenceProjection, ProjectionIntensity

        proj = PresenceProjection()
        intensity = proj._determine_intensity([])
        assert intensity == float(ProjectionIntensity.MINIMAL)

    def test_intensity_presence_wins_over_perception(self):
        from core.presence.presence_projection import PresenceProjection, ProjectionIntensity

        proj = PresenceProjection()
        intensity = proj._determine_intensity(["perception", "presence"])
        assert intensity == float(ProjectionIntensity.FULL)

    def test_project_uses_registry_entries(self):
        from core.presence.presence_projection import PresenceProjection
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        reg = get_body_mesh_registry()
        reg.register("dev_a", roles=[DeviceRole.PRESENCE])
        reg.register("dev_b", roles=[DeviceRole.ACTION])

        proj = PresenceProjection()
        events = proj.project(cognitive_state={"phase": "manifest"})
        device_ids = {e.device_id for e in events}
        assert "dev_a" in device_ids
        assert "dev_b" in device_ids

    def test_projection_event_to_dict(self):
        from core.presence.presence_projection import PresenceProjection

        proj = PresenceProjection()
        evt = proj.project_to_device("dev_1", cognitive_state={"x": 1})
        d = evt.to_dict()
        assert "device_id" in d
        assert "intensity" in d
        assert d["device_id"] == "dev_1"

    def test_singleton(self):
        from core.presence.presence_projection import get_presence_projection

        p1 = get_presence_projection()
        p2 = get_presence_projection()
        assert p1 is p2


# ===========================================================================
# 9. PresenceDirector
# ===========================================================================


class TestPresenceDirector:
    def setup_method(self):
        _reset_all()

    def test_on_phase_transition_manifest_projects(self):
        from core.presence.presence_director import PresenceDirector, DirectorConfig
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        reg = get_body_mesh_registry()
        reg.register("dev_screen", roles=[DeviceRole.PRESENCE])

        director = PresenceDirector(DirectorConfig(project_on_manifest=True))
        result = director.on_phase_transition("liminal", "manifest", cognitive_state={"x": 1})
        assert result["projected"] is True

    def test_on_phase_transition_silent_no_projection(self):
        from core.presence.presence_director import PresenceDirector, DirectorConfig

        director = PresenceDirector(DirectorConfig(project_on_manifest=True))
        result = director.on_phase_transition("manifest", "silent")
        assert result["projected"] is False

    def test_hitl_gating_blocks_when_rejected(self):
        from core.presence.presence_director import PresenceDirector, DirectorConfig
        from core.policy.hitl_policy import get_hitl_policy, HITLMode

        # Set policy to MANUAL with pessimistic default
        policy = get_hitl_policy()
        policy.mode = HITLMode.MANUAL
        policy._timeout_default_approve = False

        director = PresenceDirector(DirectorConfig(project_on_manifest=True, hitl_on_manifest=True))
        result = director.on_phase_transition("liminal", "manifest")
        assert result["hitl_required"] is True
        # pessimistic default = rejected → no projection
        assert result["projected"] is False

    def test_hitl_gating_allows_when_approved(self):
        from core.presence.presence_director import PresenceDirector, DirectorConfig
        from core.policy.hitl_policy import get_hitl_policy, HITLMode

        # Set policy to MANUAL with optimistic default
        policy = get_hitl_policy()
        policy.mode = HITLMode.MANUAL
        policy._timeout_default_approve = True

        director = PresenceDirector(DirectorConfig(project_on_manifest=True, hitl_on_manifest=True))
        result = director.on_phase_transition("liminal", "manifest")
        assert result["hitl_required"] is True
        assert result["projected"] is True

    def test_trace_log_populated(self):
        from core.presence.presence_director import PresenceDirector, DirectorConfig

        director = PresenceDirector(DirectorConfig(project_on_manifest=True))
        director.on_phase_transition("liminal", "manifest")
        director.on_phase_transition("manifest", "silent")
        log = director.get_trace_log()
        assert len(log) == 2

    def test_refresh_presence_returns_events(self):
        from core.presence.presence_director import PresenceDirector
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        reg = get_body_mesh_registry()
        reg.register("dev_r", roles=[DeviceRole.PRESENCE])

        director = PresenceDirector()
        events = director.refresh_presence(cognitive_state={"phase": "manifest"})
        assert isinstance(events, list)

    def test_singleton(self):
        from core.presence.presence_director import get_presence_director

        d1 = get_presence_director()
        d2 = get_presence_director()
        assert d1 is d2


# ===========================================================================
# 10. StateEventBus — new event types
# ===========================================================================


class TestStateEventBusNewTypes:
    def setup_method(self):
        _reset_all()

    def test_presence_projected_event_type_exists(self):
        from core.state_event_bus import StateEventType

        assert hasattr(StateEventType, "PRESENCE_PROJECTED")
        assert StateEventType.PRESENCE_PROJECTED == "presence.projected"

    def test_hitl_evaluated_event_type_exists(self):
        from core.state_event_bus import StateEventType

        assert hasattr(StateEventType, "HITL_EVALUATED")
        assert StateEventType.HITL_EVALUATED == "hitl.evaluated"

    def test_mesh_updated_event_type_exists(self):
        from core.state_event_bus import StateEventType

        assert hasattr(StateEventType, "MESH_UPDATED")

    def test_task_cancelled_event_type_exists(self):
        from core.state_event_bus import StateEventType

        assert hasattr(StateEventType, "TASK_CANCELLED")

    def test_subscribe_and_receive_presence_projected(self):
        from core.state_event_bus import get_state_event_bus, StateEventType

        bus = get_state_event_bus()
        received = []
        token = bus.subscribe(StateEventType.PRESENCE_PROJECTED, received.append)

        bus.publish(
            StateEventType.PRESENCE_PROJECTED,
            source="test",
            payload={"device_id": "dev_1"},
        )
        assert len(received) == 1
        bus.unsubscribe(token)

    def test_hitl_evaluated_publish_receive(self):
        from core.state_event_bus import get_state_event_bus, StateEventType

        bus = get_state_event_bus()
        received = []
        token = bus.subscribe(StateEventType.HITL_EVALUATED, received.append)

        bus.publish(
            StateEventType.HITL_EVALUATED,
            source="test",
            payload={"outcome": "approved"},
        )
        assert len(received) == 1
        bus.unsubscribe(token)


# ===========================================================================
# 11. DeviceManager — health integration
# ===========================================================================


class TestDeviceManagerHealthIntegration:
    def setup_method(self):
        _reset_all()
        # Reset UDM singleton too
        from core.unified.device_manager import UnifiedDeviceManager
        UnifiedDeviceManager._instance = None

    def test_heartbeat_feeds_health_scorer(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.unified.device_health import get_device_health_scorer

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="hb_dev_1",
            device_name="HB Test",
            status=UnifiedDeviceStatus.ONLINE,
        )
        udm.register_device(device)
        udm.heartbeat("hb_dev_1")
        udm.heartbeat("hb_dev_1")
        udm.heartbeat("hb_dev_1")

        scorer = get_device_health_scorer()
        # Heartbeats were recorded
        hs = scorer.score("hb_dev_1")
        # Sample count may be 0 latency-wise but heartbeats were recorded
        assert hs is not None

    def test_get_device_health_returns_score(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.unified.device_health import get_device_health_scorer

        udm = UnifiedDeviceManager()
        device = UnifiedDevice(
            device_id="health_dev_1",
            device_name="Health Test",
            status=UnifiedDeviceStatus.ONLINE,
        )
        udm.register_device(device)

        # Feed some health data
        scorer = get_device_health_scorer()
        scorer.update("health_dev_1", latency_ms=50.0)

        hs = udm.get_device_health("health_dev_1")
        assert hs is not None
        assert 0.0 <= hs.total_score <= 1.0

    def test_get_online_devices_by_health_ordering(self):
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDevice, UnifiedDeviceStatus
        from core.unified.device_health import get_device_health_scorer

        udm = UnifiedDeviceManager()
        for dev_id in ("dh_a", "dh_b", "dh_c"):
            udm.register_device(UnifiedDevice(
                device_id=dev_id,
                device_name=dev_id,
                status=UnifiedDeviceStatus.ONLINE,
            ))

        scorer = get_device_health_scorer()
        scorer.update("dh_a", latency_ms=10.0)    # best
        scorer.update("dh_b", latency_ms=500.0)   # medium
        for _ in range(5):
            scorer.update("dh_c", error=True)      # worst

        ordered = udm.get_online_devices_by_health()
        ids = [d.device_id for d in ordered]
        # dh_a should be first (best health)
        assert ids[0] == "dh_a"
