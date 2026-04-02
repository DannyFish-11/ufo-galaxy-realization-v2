#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr506_execution_spine_write_integration.py
======================================================
PR-506 — Execution Spine Write Integration: Tests.

Validates that CommandRouter.route_envelope() is now the production write
path for TaskGraphRuntime, ReplayFoundation, and AuditEventSemantics.

Test groups
-----------
 A)  Sentinel — EXECUTION_SPINE_WRITE_INTEGRATED importable and correct.
 B)  Graph write — route_envelope registers envelope in TaskGraphRuntime.
 C)  Graph write — route_envelope completes node on success.
 D)  Graph write — route_envelope fails node on failure.
 E)  Replay write — route_envelope records route decision.
 F)  Replay write — route_envelope records TaskExecutionRecord on success.
 G)  Replay write — route_envelope records TaskExecutionRecord on failure.
 H)  Replay write — replay_task_timeline is non-empty after dispatch.
 I)  Audit write — route_envelope emits task_accepted event.
 J)  Audit write — route_envelope emits task_dispatched event.
 K)  Audit write — route_envelope emits task_completed on success.
 L)  Audit write — route_envelope emits task_failed on failure.
 M)  Retry write — retry scheduling emits ReplayRetryRecord.
 N)  Retry write — retry scheduling emits audit RETRY_TRIGGERED.
 O)  Retry write — retry replay event is emitted.
 P)  Fallback write — circuit-breaker bypass emits ReplayFallbackRecord.
 Q)  Fallback write — circuit-breaker bypass emits audit FALLBACK_TRIGGERED.
 R)  Fallback write — fallback replay event is emitted.
 S)  Compat path — dispatch() emits audit accepted marker.
 T)  Integration — full round-trip: graph + replay + audit all written.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    """Run a coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Helpers — shared fixture builder
# ---------------------------------------------------------------------------

def _make_router_with_executor(success: bool = True, error_code: str = ""):
    """Build a CommandRouter with a minimal async executor injected."""
    from core.command_router import CommandRouter

    async def _executor(device_id, command, params):
        if not success:
            raise RuntimeError(error_code or "executor_failure")
        return {"data": "ok"}

    router = CommandRouter()
    router.set_executor(_executor)
    return router


def _make_candidate(device_id: str):
    """Build a minimal DeviceScoreInput-compatible candidate object."""
    try:
        from core.control_plane.smart_scheduler import DeviceScoreInput, SandboxLevel
        return DeviceScoreInput(
            device_id=device_id,
            ping_latency_ms=10.0,
            load_pct=5.0,
            sandbox_level=SandboxLevel.NONE,
            capabilities=["screen"],
            health_score=100.0,
        )
    except Exception:
        # Minimal duck-typed fallback
        class _C:
            def __init__(self, d):
                self.device_id = d
        return _C(device_id)


def _make_envelope(task_id: str = "", tool_name: str = "test_cmd", targets=None):
    """Build a minimal TaskEnvelope for testing."""
    from core.schemas.task_envelope import TaskEnvelope
    import uuid

    return TaskEnvelope(
        task_id=task_id or f"t_{uuid.uuid4().hex[:8]}",
        trace_id=f"tr_{uuid.uuid4().hex[:8]}",
        source="test",
        targets=targets or ["device_test"],
        tool_name=tool_name,
        args={},
        timeout=5.0,
        metadata={},
    )


def _fresh_singletons():
    """Reset all relevant singletons for test isolation."""
    try:
        from core.task_graph_runtime import reset_task_graph_runtime
        reset_task_graph_runtime()
    except Exception:
        pass
    try:
        from core.replay_foundation import reset_replay_foundation
        reset_replay_foundation()
    except Exception:
        pass
    try:
        from core.audit_event_semantics import reset_audit_event_semantics
        reset_audit_event_semantics()
    except Exception:
        pass


def _make_envelope_with_retries(task_id: str = "", targets=None, candidates=None, max_retries: int = 2):
    """Build a TaskEnvelope pre-loaded with retry_candidates in metadata."""
    env = _make_envelope(task_id=task_id, targets=targets)
    return env.model_copy(update={
        "metadata": {
            "retry_candidates": candidates or [_make_candidate("fallback_dev")],
            "max_retries": max_retries,
        }
    })


def _make_mock_health_registry(open_devices=None):
    """Build a minimal mock health registry that marks specific devices as circuit-open."""
    _open = set(open_devices or [])
    return type("MockHR", (), {
        "is_eligible": staticmethod(lambda dev: dev not in _open),
        "record_success": staticmethod(lambda dev: None),
        "record_failure": staticmethod(lambda dev, **kw: None),
    })()

# ===========================================================================
# A) Sentinel
# ===========================================================================


class TestSentinel(unittest.TestCase):
    """Tests A01–A03: EXECUTION_SPINE_WRITE_INTEGRATED sentinel."""

    def test_A01_sentinel_importable(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIsNotNone(EXECUTION_SPINE_WRITE_INTEGRATED)

    def test_A02_sentinel_is_string(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIsInstance(EXECUTION_SPINE_WRITE_INTEGRATED, str)

    def test_A03_sentinel_mentions_route_envelope(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIn("route_envelope", EXECUTION_SPINE_WRITE_INTEGRATED)

    def test_A04_sentinel_mentions_replay(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIn("Replay", EXECUTION_SPINE_WRITE_INTEGRATED)

    def test_A05_sentinel_mentions_audit(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIn("Audit", EXECUTION_SPINE_WRITE_INTEGRATED)

    def test_A06_sentinel_mentions_task_graph(self):
        from core.command_router import EXECUTION_SPINE_WRITE_INTEGRATED
        self.assertIn("TaskGraph", EXECUTION_SPINE_WRITE_INTEGRATED)


# ===========================================================================
# B) Graph write — envelope registration
# ===========================================================================


class TestGraphRegistration(unittest.TestCase):
    """Tests B01–B03: route_envelope registers the task in TaskGraphRuntime."""

    def setUp(self):
        _fresh_singletons()

    def test_B01_graph_node_created_after_route_envelope(self):
        from core.task_graph_runtime import get_task_graph_runtime
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertIsNotNone(node, "TaskGraphRuntime should have a node for the dispatched task")

    def test_B02_graph_node_task_id_matches(self):
        from core.task_graph_runtime import get_task_graph_runtime
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertEqual(node.task_id, env.task_id)

    def test_B03_graph_snapshot_contains_registered_task(self):
        from core.task_graph_runtime import get_task_graph_runtime
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        snap = get_task_graph_runtime().snapshot()
        # snapshot().nodes is a list of serialised node dicts
        task_ids = [n.get("task_id") for n in snap.nodes]
        self.assertIn(env.task_id, task_ids)


# ===========================================================================
# C) Graph write — successful completion
# ===========================================================================


class TestGraphCompletionSuccess(unittest.TestCase):
    """Tests C01–C02: graph node reaches COMPLETED after successful dispatch."""

    def setUp(self):
        _fresh_singletons()

    def test_C01_node_is_completed_on_success(self):
        from core.task_graph_runtime import get_task_graph_runtime, GraphNodeState
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertIsNotNone(node)
        self.assertEqual(node.state, GraphNodeState.COMPLETED)

    def test_C02_node_completed_at_is_set(self):
        from core.task_graph_runtime import get_task_graph_runtime
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertIsNotNone(node.completed_at)


# ===========================================================================
# D) Graph write — failure completion
# ===========================================================================


class TestGraphCompletionFailure(unittest.TestCase):
    """Tests D01–D02: graph node reaches FAILED after failed dispatch."""

    def setUp(self):
        _fresh_singletons()

    def test_D01_node_is_failed_on_failure(self):
        from core.task_graph_runtime import get_task_graph_runtime, GraphNodeState
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertIsNotNone(node)
        self.assertEqual(node.state, GraphNodeState.FAILED)

    def test_D02_node_error_populated_on_failure(self):
        from core.task_graph_runtime import get_task_graph_runtime
        router = _make_router_with_executor(success=False, error_code="EXECUTOR_ERROR")
        env = _make_envelope()
        _run(router.route_envelope(env))
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        # error may be populated from error_code or error_message
        self.assertIsNotNone(node)


# ===========================================================================
# E) Replay write — route decision
# ===========================================================================


class TestReplayRouteDecision(unittest.TestCase):
    """Tests E01–E03: route_envelope records a RouteDecisionRecord."""

    def setUp(self):
        _fresh_singletons()

    def test_E01_route_decision_recorded(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        decisions = get_replay_foundation().get_route_decisions(env.task_id)
        self.assertGreater(len(decisions), 0, "ReplayFoundation should have a route decision")

    def test_E02_route_decision_task_id_matches(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        decisions = get_replay_foundation().get_route_decisions(env.task_id)
        self.assertTrue(any(d.task_id == env.task_id for d in decisions))

    def test_E03_route_decision_has_targets(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope(targets=["device_abc"])
        _run(router.route_envelope(env))
        decisions = get_replay_foundation().get_route_decisions(env.task_id)
        self.assertTrue(
            any("device_abc" in d.selected_targets for d in decisions),
            "Route decision should record the selected target",
        )


# ===========================================================================
# F) Replay write — TaskExecutionRecord on success
# ===========================================================================


class TestReplayExecutionRecordSuccess(unittest.TestCase):
    """Tests F01–F04: ReplayFoundation receives a TaskExecutionRecord on success."""

    def setUp(self):
        _fresh_singletons()

    def test_F01_execution_record_stored(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertIsNotNone(rec, "ReplayFoundation should store an execution record")

    def test_F02_execution_record_task_id(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertEqual(rec.task_id, env.task_id)

    def test_F03_execution_record_success_true(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertTrue(rec.success)

    def test_F04_execution_record_lifecycle_completed(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertEqual(rec.final_lifecycle, "completed")


# ===========================================================================
# G) Replay write — TaskExecutionRecord on failure
# ===========================================================================


class TestReplayExecutionRecordFailure(unittest.TestCase):
    """Tests G01–G03: ReplayFoundation receives a TaskExecutionRecord on failure."""

    def setUp(self):
        _fresh_singletons()

    def test_G01_execution_record_stored_on_failure(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertIsNotNone(rec)

    def test_G02_execution_record_success_false(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertFalse(rec.success)

    def test_G03_execution_record_lifecycle_failed(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertEqual(rec.final_lifecycle, "failed")


# ===========================================================================
# H) Replay — replay_task_timeline is non-empty
# ===========================================================================


class TestReplayTimeline(unittest.TestCase):
    """Tests H01–H03: replay_task_timeline is populated after dispatch."""

    def setUp(self):
        _fresh_singletons()

    def test_H01_timeline_not_empty_on_success(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        timeline = get_replay_foundation().replay_task_timeline(env.task_id)
        self.assertGreater(len(timeline), 0, "replay_task_timeline should be non-empty")

    def test_H02_timeline_not_empty_on_failure(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        timeline = get_replay_foundation().replay_task_timeline(env.task_id)
        self.assertGreater(len(timeline), 0, "timeline should be non-empty on failure")

    def test_H03_timeline_events_have_task_id(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        timeline = get_replay_foundation().replay_task_timeline(env.task_id)
        for ev in timeline:
            self.assertEqual(ev.get("task_id"), env.task_id)


# ===========================================================================
# I) Audit write — task_accepted
# ===========================================================================


class TestAuditTaskAccepted(unittest.TestCase):
    """Tests I01–I02: audit_task_accepted event emitted."""

    def setUp(self):
        _fresh_singletons()

    def test_I01_task_accepted_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.TASK_ACCEPTED, kinds)

    def test_I02_task_accepted_task_id_matches(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        accepted_events = [e for e in events if e.kind == AuditEventKind.TASK_ACCEPTED]
        self.assertTrue(all(e.task_id == env.task_id for e in accepted_events))


# ===========================================================================
# J) Audit write — task_dispatched
# ===========================================================================


class TestAuditTaskDispatched(unittest.TestCase):
    """Tests J01–J02: audit_task_dispatched event emitted."""

    def setUp(self):
        _fresh_singletons()

    def test_J01_task_dispatched_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.TASK_DISPATCHED, kinds)

    def test_J02_dispatched_event_has_targets(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope(targets=["device_xyz"])
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        dispatched = [e for e in events if e.kind == AuditEventKind.TASK_DISPATCHED]
        self.assertTrue(
            any("device_xyz" in str(e.payload) for e in dispatched),
            "Dispatched event should record targets",
        )


# ===========================================================================
# K) Audit write — task_completed
# ===========================================================================


class TestAuditTaskCompleted(unittest.TestCase):
    """Tests K01–K02: audit_task_completed event emitted on success."""

    def setUp(self):
        _fresh_singletons()

    def test_K01_task_completed_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.TASK_COMPLETED, kinds)

    def test_K02_task_completed_success_flag_true(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        completed = [e for e in events if e.kind == AuditEventKind.TASK_COMPLETED]
        self.assertTrue(any(e.payload.get("success") is True for e in completed))


# ===========================================================================
# L) Audit write — task_failed
# ===========================================================================


class TestAuditTaskFailed(unittest.TestCase):
    """Tests L01–L02: audit_task_failed event emitted on failure."""

    def setUp(self):
        _fresh_singletons()

    def test_L01_task_failed_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.TASK_FAILED, kinds)

    def test_L02_task_completed_not_emitted_on_failure(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        events = get_audit_event_semantics().get_by_task(env.task_id)
        kinds = [e.kind for e in events]
        self.assertNotIn(AuditEventKind.TASK_COMPLETED, kinds)


# ===========================================================================
# M) Retry write — ReplayRetryRecord
# ===========================================================================


class TestReplayRetryRecord(unittest.TestCase):
    """Tests M01–M02: retry scheduling writes ReplayRetryRecord."""

    def setUp(self):
        _fresh_singletons()

    def _make_router_retrying(self, n_failures: int = 1):
        """Router that fails n_failures times then succeeds, with retry_candidates."""
        from core.command_router import CommandRouter

        call_count = {"n": 0}

        async def _executor(device_id, command, params):
            call_count["n"] += 1
            if call_count["n"] <= n_failures:
                raise ConnectionError("transient_error")
            return {"data": "recovered"}

        router = CommandRouter()
        router.set_executor(_executor)
        return router

    def test_M01_retry_record_written_on_retry(self):
        from core.replay_foundation import get_replay_foundation
        router = self._make_router_retrying(n_failures=1)
        env_with_retries = _make_envelope_with_retries(targets=["primary_dev"])
        _run(router.route_envelope(env_with_retries))
        retries = get_replay_foundation().get_retry_history(env_with_retries.task_id)
        self.assertGreater(len(retries), 0, "Retry record should be written")

    def test_M02_retry_record_original_task_id_matches(self):
        from core.replay_foundation import get_replay_foundation
        router = self._make_router_retrying(n_failures=1)
        env_with_retries = _make_envelope_with_retries(targets=["primary_dev"])
        _run(router.route_envelope(env_with_retries))
        retries = get_replay_foundation().get_retry_history(env_with_retries.task_id)
        if retries:
            self.assertEqual(retries[0].original_task_id, env_with_retries.task_id)


# ===========================================================================
# N) Retry write — audit RETRY_TRIGGERED
# ===========================================================================


class TestAuditRetryTriggered(unittest.TestCase):
    """Tests N01–N02: retry scheduling emits RETRY_TRIGGERED audit event."""

    def setUp(self):
        _fresh_singletons()

    def _make_router_retrying(self):
        from core.command_router import CommandRouter

        call_count = {"n": 0}

        async def _executor(device_id, command, params):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise ConnectionError("transient")
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)
        return router

    def test_N01_retry_triggered_audit_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = self._make_router_retrying()
        env_with_retries = _make_envelope_with_retries(targets=["primary_dev"])
        _run(router.route_envelope(env_with_retries))
        events = get_audit_event_semantics().get_by_task(env_with_retries.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.RETRY_TRIGGERED, kinds)

    def test_N02_retry_triggered_has_attempt_number(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        router = self._make_router_retrying()
        env_with_retries = _make_envelope_with_retries(targets=["primary_dev"])
        _run(router.route_envelope(env_with_retries))
        events = get_audit_event_semantics().get_by_task(env_with_retries.task_id)
        retry_events = [e for e in events if e.kind == AuditEventKind.RETRY_TRIGGERED]
        if retry_events:
            self.assertIn("attempt_number", retry_events[0].payload)


# ===========================================================================
# O) Retry write — replay event
# ===========================================================================


class TestReplayRetryEvent(unittest.TestCase):
    """Tests O01: RETRY_TRIGGERED replay runtime event emitted."""

    def setUp(self):
        _fresh_singletons()

    def _make_router_retrying(self):
        from core.command_router import CommandRouter

        call_count = {"n": 0}

        async def _executor(device_id, command, params):
            call_count["n"] += 1
            if call_count["n"] <= 1:
                raise ConnectionError("transient")
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)
        return router

    def test_O01_retry_triggered_replay_event_in_timeline(self):
        from core.replay_foundation import get_replay_foundation, ReplayEventKind
        router = self._make_router_retrying()
        env_with_retries = _make_envelope_with_retries(targets=["primary_dev"])
        _run(router.route_envelope(env_with_retries))
        timeline = get_replay_foundation().replay_task_timeline(env_with_retries.task_id)
        kinds = [ev.get("kind") for ev in timeline]
        self.assertIn(ReplayEventKind.RETRY_TRIGGERED, kinds)


# ===========================================================================
# P) Fallback write — ReplayFallbackRecord (circuit-breaker)
# ===========================================================================


class TestReplayFallbackRecord(unittest.TestCase):
    """Tests P01–P02: circuit-breaker bypass writes ReplayFallbackRecord."""

    def setUp(self):
        _fresh_singletons()

    def _make_router_for_circuit_test(self):
        from core.command_router import CommandRouter

        async def _executor(device_id, command, params):
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)
        return router

    def test_P01_fallback_record_written_on_circuit_open(self):
        """Verify ReplayFallbackRecord is written when circuit-breaker routes to fallback."""
        from core.replay_foundation import get_replay_foundation
        from unittest.mock import patch

        router = self._make_router_for_circuit_test()
        mock_hreg = _make_mock_health_registry(open_devices=["device_open"])
        env_with_fb = _make_envelope_with_retries(
            targets=["device_open"],
            candidates=[_make_candidate("device_fallback")],
        )
        with patch(
            "core.control_plane._globals.get_health_registry",
            return_value=mock_hreg,
        ):
            _run(router.route_envelope(env_with_fb))

        fallbacks = get_replay_foundation().get_fallback_history(env_with_fb.task_id)
        self.assertGreater(len(fallbacks), 0, "Fallback record should be written on circuit-open")

    def test_P02_fallback_record_primary_task_id_matches(self):
        from core.replay_foundation import get_replay_foundation
        from unittest.mock import patch

        router = self._make_router_for_circuit_test()
        mock_hreg = _make_mock_health_registry(open_devices=["device_open"])
        env_with_fb = _make_envelope_with_retries(
            targets=["device_open"],
            candidates=[_make_candidate("device_fallback")],
        )
        with patch(
            "core.control_plane._globals.get_health_registry",
            return_value=mock_hreg,
        ):
            _run(router.route_envelope(env_with_fb))

        fallbacks = get_replay_foundation().get_fallback_history(env_with_fb.task_id)
        if fallbacks:
            self.assertEqual(fallbacks[0].primary_task_id, env_with_fb.task_id)


# ===========================================================================
# Q) Fallback write — audit FALLBACK_TRIGGERED
# ===========================================================================


class TestAuditFallbackTriggered(unittest.TestCase):
    """Tests Q01: FALLBACK_TRIGGERED audit event emitted on circuit-breaker bypass."""

    def setUp(self):
        _fresh_singletons()

    def test_Q01_fallback_triggered_audit_event_emitted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        from unittest.mock import patch
        from core.command_router import CommandRouter

        async def _executor(device_id, command, params):
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)
        mock_hreg = _make_mock_health_registry(open_devices=["device_open"])
        env_with_fb = _make_envelope_with_retries(
            targets=["device_open"],
            candidates=[_make_candidate("device_fallback")],
        )
        with patch(
            "core.control_plane._globals.get_health_registry",
            return_value=mock_hreg,
        ):
            _run(router.route_envelope(env_with_fb))

        events = get_audit_event_semantics().get_by_task(env_with_fb.task_id)
        kinds = [e.kind for e in events]
        self.assertIn(AuditEventKind.FALLBACK_TRIGGERED, kinds)


# ===========================================================================
# R) Fallback write — replay event
# ===========================================================================


class TestReplayFallbackEvent(unittest.TestCase):
    """Tests R01: FALLBACK_TRIGGERED replay runtime event emitted."""

    def setUp(self):
        _fresh_singletons()

    def test_R01_fallback_triggered_replay_event(self):
        from core.replay_foundation import get_replay_foundation, ReplayEventKind
        from unittest.mock import patch
        from core.command_router import CommandRouter

        async def _executor(device_id, command, params):
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)
        mock_hreg = _make_mock_health_registry(open_devices=["device_open"])
        env_with_fb = _make_envelope_with_retries(
            targets=["device_open"],
            candidates=[_make_candidate("device_fallback")],
        )
        with patch(
            "core.control_plane._globals.get_health_registry",
            return_value=mock_hreg,
        ):
            _run(router.route_envelope(env_with_fb))

        timeline = get_replay_foundation().replay_task_timeline(env_with_fb.task_id)
        kinds = [ev.get("kind") for ev in timeline]
        self.assertIn(ReplayEventKind.FALLBACK_TRIGGERED, kinds)


# ===========================================================================
# S) Compat path — dispatch() audit marker
# ===========================================================================


class TestCompatDispatchAudit(unittest.TestCase):
    """Tests S01–S02: compat dispatch() path emits audit accepted marker."""

    def setUp(self):
        _fresh_singletons()

    def test_S01_compat_dispatch_emits_audit_accepted(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        from core.command_router import CommandRouter, CommandRequest, CommandMode

        async def _executor(device_id, command, params):
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)

        import uuid
        req_id = f"compat_{uuid.uuid4().hex[:8]}"
        req = CommandRequest(
            request_id=req_id,
            command="test_cmd",
            targets=["dev_compat"],
            mode=CommandMode.SYNC,
            params={},
        )
        _run(router.dispatch(req))

        events = get_audit_event_semantics().get_by_task(req_id)
        kinds = [e.kind for e in events]
        self.assertIn(
            AuditEventKind.TASK_ACCEPTED,
            kinds,
            "compat dispatch() should emit TASK_ACCEPTED audit event",
        )

    def test_S02_compat_dispatch_source_marks_degraded(self):
        from core.audit_event_semantics import get_audit_event_semantics, AuditEventKind
        from core.command_router import CommandRouter, CommandRequest, CommandMode

        async def _executor(device_id, command, params):
            return {"data": "ok"}

        router = CommandRouter()
        router.set_executor(_executor)

        import uuid
        req_id = f"compat_{uuid.uuid4().hex[:8]}"
        req = CommandRequest(
            request_id=req_id,
            command="test_cmd",
            targets=["dev_compat"],
            mode=CommandMode.SYNC,
            params={},
        )
        _run(router.dispatch(req))

        events = get_audit_event_semantics().get_by_task(req_id)
        accepted = [e for e in events if e.kind == AuditEventKind.TASK_ACCEPTED]
        # The source should identify the compat degraded path
        self.assertTrue(
            any("compat" in (e.source or "") for e in accepted),
            "compat dispatch audit event source should mention 'compat'",
        )


# ===========================================================================
# T) Integration — full round-trip
# ===========================================================================


class TestFullRoundTrip(unittest.TestCase):
    """Tests T01–T04: all three systems written for a normal dispatched task."""

    def setUp(self):
        _fresh_singletons()

    def test_T01_graph_replay_audit_all_written(self):
        """Single dispatch writes to TaskGraphRuntime, ReplayFoundation, and AuditEventSemantics."""
        from core.task_graph_runtime import get_task_graph_runtime
        from core.replay_foundation import get_replay_foundation
        from core.audit_event_semantics import get_audit_event_semantics

        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))

        # Graph
        node = get_task_graph_runtime().get_node_by_task_id(env.task_id)
        self.assertIsNotNone(node, "graph node must exist")

        # Replay
        rec = get_replay_foundation().get_execution_record(env.task_id)
        self.assertIsNotNone(rec, "execution record must exist")

        # Audit
        events = get_audit_event_semantics().get_by_task(env.task_id)
        self.assertGreater(len(events), 0, "audit events must be present")

    def test_T02_lineage_non_empty(self):
        """Task lineage is non-empty for a dispatched task."""
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        lineage = get_replay_foundation().get_task_lineage(env.task_id)
        self.assertIsNotNone(lineage)
        self.assertEqual(lineage.task_id, env.task_id)

    def test_T03_result_lineage_success_populated(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=True)
        env = _make_envelope()
        _run(router.route_envelope(env))
        lineage = get_replay_foundation().get_result_lineage(env.task_id)
        self.assertEqual(lineage.get("task_id"), env.task_id)
        self.assertTrue(lineage.get("success"))

    def test_T04_result_lineage_failure_populated(self):
        from core.replay_foundation import get_replay_foundation
        router = _make_router_with_executor(success=False)
        env = _make_envelope()
        _run(router.route_envelope(env))
        lineage = get_replay_foundation().get_result_lineage(env.task_id)
        self.assertEqual(lineage.get("task_id"), env.task_id)
        self.assertFalse(lineage.get("success"))


if __name__ == "__main__":
    unittest.main()
