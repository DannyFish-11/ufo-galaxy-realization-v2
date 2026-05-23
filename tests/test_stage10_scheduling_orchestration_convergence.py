#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_stage10_scheduling_orchestration_convergence.py
============================================================
Stage 10 — Scheduling and Orchestration Main-Path Convergence

Validates the implementation hardening delivered by Stage 10:

1.  WakeRouter uses DeviceScoringEngine (canonical scoring authority) as its
    primary device selection engine (not purely local heuristics).
2.  WakeRouter registers routing decisions in TaskGraphRuntime so that
    wake-initiated execution paths participate in task-graph tracking.
3.  Scheduler _exec_broadcast registers in TaskGraphRuntime (parity with
    _exec_relay and _exec_mesh_send).
4.  Stage 10 sentinel constants are importable and carry expected content.
5.  TaskGraphRuntime.register_node_raw convenience method works correctly.
"""

from __future__ import annotations

import asyncio
import sys
import os
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Group A: Stage 10 sentinel constants
# ---------------------------------------------------------------------------


class TestStage10Sentinels(unittest.TestCase):
    """Sentinel constants are importable and have expected content."""

    def test_wake_router_canonical_scoring_sentinel_importable(self):
        try:
            from galaxy_gateway.wake_router import WAKE_ROUTER_USES_CANONICAL_SCORING
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")
        self.assertIn("CANONICAL_SCORING", WAKE_ROUTER_USES_CANONICAL_SCORING)

    def test_wake_router_task_graph_sentinel_importable(self):
        try:
            from galaxy_gateway.wake_router import WAKE_ROUTER_TASK_GRAPH_REGISTERED
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")
        self.assertIn("TASK_GRAPH", WAKE_ROUTER_TASK_GRAPH_REGISTERED)

    def test_scheduler_broadcast_task_graph_sentinel_importable(self):
        try:
            from core.scheduler import SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable: {e}")
        self.assertIn("BROADCAST", SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED)
        self.assertIn("TaskGraphRuntime", SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED)


# ---------------------------------------------------------------------------
# Group B: TaskGraphRuntime.register_node_raw
# ---------------------------------------------------------------------------


class TestTaskGraphRuntimeRegisterNodeRaw(unittest.TestCase):
    """TaskGraphRuntime.register_node_raw convenience method."""

    def _get_runtime(self):
        try:
            from core.task_graph_runtime import TaskGraphRuntime
        except ImportError as e:
            self.skipTest(f"task_graph_runtime unavailable: {e}")
        return TaskGraphRuntime()

    def test_register_node_raw_returns_graph_node(self):
        rt = self._get_runtime()
        node = rt.register_node_raw(
            task_id="test_raw_001",
            tool_name="wake_route",
            trace_id="trace_abc",
            device_id="dev_x",
        )
        self.assertIsNotNone(node)
        self.assertEqual(node.task_id, "test_raw_001")
        self.assertEqual(node.tool_name, "wake_route")
        self.assertEqual(node.device_id, "dev_x")
        self.assertEqual(node.trace_id, "trace_abc")

    def test_register_node_raw_is_idempotent(self):
        rt = self._get_runtime()
        node1 = rt.register_node_raw(task_id="test_raw_idem", tool_name="tool_a")
        node2 = rt.register_node_raw(task_id="test_raw_idem", tool_name="tool_b")
        # Should return the same node (first registration wins)
        self.assertEqual(node1.task_id, node2.task_id)
        # Second call should not overwrite the first registration
        self.assertEqual(node1.tool_name, "tool_a")

    def test_register_node_raw_node_tracked_in_runtime(self):
        rt = self._get_runtime()
        rt.register_node_raw(task_id="test_raw_track_999", device_id="dev_tracked")
        found = rt.get_node_by_task_id("test_raw_track_999")
        self.assertIsNotNone(found)
        self.assertEqual(found.device_id, "dev_tracked")

    def test_register_node_raw_accepts_metadata(self):
        rt = self._get_runtime()
        node = rt.register_node_raw(
            task_id="test_raw_meta",
            metadata={"source": "wake_router", "score": 0.87},
        )
        self.assertEqual(node.metadata.get("source"), "wake_router")


# ---------------------------------------------------------------------------
# Group C: WakeRouter uses DeviceScoringEngine as primary scoring authority
# ---------------------------------------------------------------------------


class TestWakeRouterCanonicalScoring(unittest.TestCase):
    """WakeRouter delegates to DeviceScoringEngine when available."""

    def _make_wake_router(self):
        try:
            from galaxy_gateway.wake_router import WakeRouter
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")
        return WakeRouter()

    def _make_wake_event(self, task_type=None):
        try:
            from galaxy_gateway.wake_router import WakeEvent, WakeTaskType
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")
        import uuid
        return WakeEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            source_device_id="dev_source",
            wake_word="galaxy",
            task_type=task_type or WakeTaskType.GENERAL,
        )

    def test_wake_router_uses_scoring_engine_when_available(self):
        """When DeviceScoringEngine is available, WakeRouter should use it."""
        router = self._make_wake_router()
        event = self._make_wake_event()

        # Inject two devices: dev_a is more active, dev_b is stale
        now = time.time()
        router.inject_device_info("dev_a", {
            "capabilities": ["screen", "speaker"],
            "last_heartbeat": now - 1,
            "last_message": now - 1,
            "screen_on": True,
            "last_interaction": now - 2,
        })
        router.inject_device_info("dev_b", {
            "capabilities": ["touch"],
            "last_heartbeat": now - 120,
            "last_message": now - 120,
            "screen_on": False,
            "last_interaction": 0,
        })

        # Track whether DeviceScoringEngine.select_best_device was called
        _called = {}
        try:
            from core.control_plane.smart_scheduler import DeviceScoringEngine as _Engine
            original_select = _Engine.select_best_device

            def _patched_select(self_inner, candidates, required_caps=None):
                _called["invoked"] = True
                return original_select(self_inner, candidates, required_caps)

            with patch.object(_Engine, "select_best_device", _patched_select):
                decision = _run(router.route(event))
        except ImportError:
            self.skipTest("DeviceScoringEngine not available")

        # The routing decision should prefer dev_a (more active, more capabilities)
        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_device_id, "dev_a")
        self.assertTrue(_called.get("invoked"), "DeviceScoringEngine.select_best_device was not called")

    def test_wake_router_falls_back_to_local_scoring_on_engine_failure(self):
        """WakeRouter falls back gracefully when DeviceScoringEngine is unavailable."""
        router = self._make_wake_router()
        event = self._make_wake_event()

        now = time.time()
        router.inject_device_info("dev_fallback", {
            "capabilities": ["screen"],
            "last_heartbeat": now - 5,
            "last_message": now - 5,
            "screen_on": True,
            "last_interaction": now - 3,
        })

        # Simulate engine import failure
        with patch.dict("sys.modules", {"core.control_plane.smart_scheduler": None}):
            decision = _run(router.route(event))

        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_device_id, "dev_fallback")

    def test_wake_router_visual_task_prefers_screen_device(self):
        """WakeRouter routes VISUAL task to device with screen capability."""
        try:
            from galaxy_gateway.wake_router import WakeTaskType
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")

        router = self._make_wake_router()
        event = self._make_wake_event(task_type=WakeTaskType.VISUAL)

        now = time.time()
        router.inject_device_info("dev_screen", {
            "capabilities": ["screen", "keyboard"],
            "last_heartbeat": now - 5,
            "last_message": now - 5,
            "screen_on": True,
            "last_interaction": now - 3,
        })
        router.inject_device_info("dev_no_screen", {
            "capabilities": ["touch"],
            "last_heartbeat": now - 5,
            "last_message": now - 5,
            "screen_on": False,
            "last_interaction": now - 3,
        })

        decision = _run(router.route(event))
        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_device_id, "dev_screen")


# ---------------------------------------------------------------------------
# Group D: WakeRouter registers routing decisions in TaskGraphRuntime
# ---------------------------------------------------------------------------


class TestWakeRouterTaskGraphRegistration(unittest.TestCase):
    """WakeRouter.route() registers decisions in TaskGraphRuntime."""

    def test_wake_route_registers_in_task_graph_runtime(self):
        """After route(), TaskGraphRuntime should contain a wake_route node."""
        try:
            from galaxy_gateway.wake_router import WakeRouter, WakeEvent, WakeTaskType
            from core.task_graph_runtime import TaskGraphRuntime
        except ImportError as e:
            self.skipTest(f"dependency unavailable: {e}")

        import uuid

        # Use a fresh isolated TaskGraphRuntime instance to avoid test pollution
        fresh_rt = TaskGraphRuntime()
        router = WakeRouter()
        now = time.time()
        router.inject_device_info("dev_tgr", {
            "capabilities": ["screen"],
            "last_heartbeat": now - 1,
            "last_message": now - 1,
            "screen_on": True,
            "last_interaction": now - 1,
        })

        event = WakeEvent(
            event_id=f"evt_tgr_{uuid.uuid4().hex[:8]}",
            source_device_id="dev_src",
            wake_word="galaxy",
        )

        with patch("core.task_graph_runtime.get_task_graph_runtime", return_value=fresh_rt):
            _run(router.route(event))

        # Runtime should have at least one node with tool_name == "wake_route"
        wake_nodes = [
            n for n in fresh_rt.all_nodes() if n.tool_name == "wake_route"
        ]
        self.assertTrue(len(wake_nodes) >= 1, "No wake_route node found in TaskGraphRuntime")
        wake_node = wake_nodes[0]
        self.assertEqual(wake_node.trace_id, event.event_id)
        self.assertEqual(wake_node.device_id, "dev_tgr")

    def test_wake_route_task_graph_failure_is_non_fatal(self):
        """TaskGraphRuntime registration failure must not block routing."""
        try:
            from galaxy_gateway.wake_router import WakeRouter, WakeEvent
        except ImportError as e:
            self.skipTest(f"wake_router unavailable: {e}")
        import uuid

        router = WakeRouter()
        now = time.time()
        router.inject_device_info("dev_safe", {
            "capabilities": ["screen"],
            "last_heartbeat": now - 1,
            "last_message": now - 1,
            "screen_on": True,
            "last_interaction": now - 1,
        })
        event = WakeEvent(
            event_id=f"evt_safe_{uuid.uuid4().hex[:8]}",
            source_device_id="dev_src",
            wake_word="galaxy2",
        )

        # Force TaskGraphRuntime to raise
        with patch("core.task_graph_runtime.get_task_graph_runtime", side_effect=Exception("tgr_broken")):
            decision = _run(router.route(event))

        # Routing should still succeed despite the TaskGraphRuntime error
        self.assertIsNotNone(decision)
        self.assertEqual(decision.selected_device_id, "dev_safe")


# ---------------------------------------------------------------------------
# Group E: Scheduler broadcast registers in TaskGraphRuntime
# ---------------------------------------------------------------------------


class TestSchedulerBroadcastTaskGraph(unittest.TestCase):
    """_exec_broadcast registers in TaskGraphRuntime (parity with relay/mesh)."""

    def _make_scheduler(self):
        try:
            from core.scheduler import AutonomousScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable: {e}")
        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        sched.nodes_dir = "/tmp"
        sched.tools_cache = []
        return sched

    def test_broadcast_registers_in_task_graph_runtime(self):
        """_exec_broadcast should register CanonicalTask in TaskGraphRuntime."""
        try:
            from core.task_graph_runtime import TaskGraphRuntime
        except ImportError as e:
            self.skipTest(f"task_graph_runtime unavailable: {e}")

        sched = self._make_scheduler()
        fresh_rt = TaskGraphRuntime()

        context = {"devices": {"dev_broadcast_1": {}, "dev_broadcast_2": {}}}

        _send_results = {}

        async def _fake_send(args, ctx):
            return json.dumps({"status": "queued", "device_id": args.get("device_id")})

        with patch.object(sched, "_exec_send_to_device", side_effect=_fake_send), \
             patch("core.task_graph_runtime.get_task_graph_runtime", return_value=fresh_rt):
            result_str = _run(sched._exec_broadcast(
                {"task_type": "screenshot", "task_id": "bc_test_001"},
                context,
            ))

        result = json.loads(result_str)
        self.assertIn("broadcast_results", result)
        self.assertIn("broadcast_task_id", result)

        # TaskGraphRuntime should have a node for the broadcast task
        all_nodes = fresh_rt.all_nodes()
        broadcast_nodes = [n for n in all_nodes if "broadcast" in n.task_id or n.tool_name in ("screenshot", "broadcast")]
        self.assertTrue(len(broadcast_nodes) >= 1, "No broadcast task node in TaskGraphRuntime")

    def test_broadcast_sentinel_present(self):
        """SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED sentinel is importable."""
        try:
            from core.scheduler import SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable: {e}")
        self.assertIsInstance(SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED, str)
        self.assertGreater(len(SCHEDULER_BROADCAST_TASK_GRAPH_INTEGRATED), 10)

    def test_broadcast_records_spine_ingress(self):
        """_exec_broadcast records ingress in execution spine log."""
        try:
            from core.execution_spine import get_ingress_log, reset_ingress_log
        except ImportError as e:
            self.skipTest(f"execution_spine unavailable: {e}")

        reset_ingress_log()
        sched = self._make_scheduler()
        context = {"devices": {"dev_bc": {}}}

        async def _fake_send(args, ctx):
            return json.dumps({"status": "queued"})

        with patch.object(sched, "_exec_send_to_device", side_effect=_fake_send):
            _run(sched._exec_broadcast(
                {"task_type": "screenshot"},
                context,
            ))

        log = get_ingress_log()
        self.assertGreater(len(log), 0)


if __name__ == "__main__":
    unittest.main()
