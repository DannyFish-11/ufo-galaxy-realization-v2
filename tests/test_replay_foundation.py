#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_replay_foundation.py
================================
PR-E — Operator Surface + Replay Foundation

Validates the ReplayFoundation data structures, ring-buffer behaviour,
record serialisation, lineage reconstruction, and replay timeline ordering.

Coverage:
  1.  REPLAY_FOUNDATION_AUTHORITY sentinel is importable and non-empty string.
  2.  REPLAY_FOUNDATION_LAYER_POSITION is 10.
  3.  REPLAY_FOUNDATION_CONTRACT_VERSION is a non-empty string.
  4.  REPLAY_ONLY_PRINCIPLE is a non-empty string.
  5.  All names appear in __all__.
  6.  ReplayEventKind: TASK_CREATED is present.
  7.  ReplayEventKind: ROUTE_DECISION is present.
  8.  ReplayEventKind: FALLBACK_TRIGGERED is present.
  9.  ReplayEventKind: RETRY_TRIGGERED is present.
  10. ReplayEventKind: FAILURE_DOMAIN_IDENTIFIED is present.
  11. TaskExecutionRecord: construction and to_dict/from_dict round-trip.
  12. TaskExecutionRecord: record_id auto-generated.
  13. TaskExecutionRecord: to_json() returns valid JSON.
  14. RuntimeEventRecord: construction and to_dict/from_dict round-trip.
  15. RuntimeEventRecord: event_id auto-generated.
  16. RuntimeEventRecord: parent_event_ids linkage preserved.
  17. RouteDecisionRecord: construction and to_dict/from_dict round-trip.
  18. ReplayFallbackRecord: construction and to_dict/from_dict round-trip.
  19. ReplayRetryRecord: construction and to_dict/from_dict round-trip.
  20. TaskLineage: to_dict() is JSON-serialisable.
  21. ReplayFoundationSnapshot: to_dict() is JSON-serialisable.
  22. ReplayFoundation: record_execution stores the record.
  23. ReplayFoundation: get_execution_record retrieves by task_id.
  24. ReplayFoundation: emit_event stores in ring.
  25. ReplayFoundation: get_events_for_task returns task-indexed events.
  26. ReplayFoundation: record_route stores route decision.
  27. ReplayFoundation: get_route_decisions retrieves by task_id.
  28. ReplayFoundation: record_fallback stores fallback record.
  29. ReplayFoundation: get_fallback_history retrieves by primary_task_id.
  30. ReplayFoundation: record_retry stores retry record.
  31. ReplayFoundation: get_retry_history retrieves by original_task_id.
  32. ReplayFoundation: get_task_lineage returns TaskLineage.
  33. ReplayFoundation: lineage execution_record matches stored record.
  34. ReplayFoundation: replay_task_timeline returns ordered dicts.
  35. ReplayFoundation: get_result_lineage returns correct retry_count.
  36. ReplayFoundation: snapshot() returns ReplayFoundationSnapshot.
  37. ReplayFoundation: snapshot counts match recorded data.
  38. get_replay_foundation() returns singleton.
  39. reset_replay_foundation() resets singleton.
  40. record_task_execution() helper works with CanonicalTask.
  41. record_route_decision() helper creates and stores RouteDecisionRecord.
  42. record_fallback() helper creates and stores ReplayFallbackRecord.
  43. record_retry() helper creates and stores ReplayRetryRecord.
  44. emit_runtime_event() helper stores RuntimeEventRecord.
  45. replay_task_timeline events sorted by recorded_at.
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import Any

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.replay_foundation import (
    REPLAY_FOUNDATION_AUTHORITY,
    REPLAY_FOUNDATION_LAYER_POSITION,
    REPLAY_FOUNDATION_CONTRACT_VERSION,
    REPLAY_ONLY_PRINCIPLE,
    ReplayEventKind,
    TaskExecutionRecord,
    RuntimeEventRecord,
    RouteDecisionRecord,
    ReplayFallbackRecord,
    ReplayRetryRecord,
    TaskLineage,
    ReplayFoundationSnapshot,
    ReplayFoundation,
    record_task_execution,
    record_route_decision,
    record_fallback,
    record_retry,
    emit_runtime_event,
    get_replay_foundation,
    reset_replay_foundation,
)
import core.replay_foundation as _mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset():
    reset_replay_foundation()
    yield
    reset_replay_foundation()


# ===========================================================================
# 1-5: Authority sentinels
# ===========================================================================

class TestAuthoritySentinels:
    def test_01_authority_importable(self):
        assert REPLAY_FOUNDATION_AUTHORITY
        assert isinstance(REPLAY_FOUNDATION_AUTHORITY, str)

    def test_02_layer_position(self):
        assert REPLAY_FOUNDATION_LAYER_POSITION == 10

    def test_03_contract_version(self):
        assert REPLAY_FOUNDATION_CONTRACT_VERSION
        assert isinstance(REPLAY_FOUNDATION_CONTRACT_VERSION, str)

    def test_04_principle_string(self):
        assert REPLAY_ONLY_PRINCIPLE
        assert isinstance(REPLAY_ONLY_PRINCIPLE, str)

    def test_05_all_exports(self):
        expected = [
            "REPLAY_FOUNDATION_AUTHORITY",
            "REPLAY_FOUNDATION_LAYER_POSITION",
            "REPLAY_FOUNDATION_CONTRACT_VERSION",
            "REPLAY_ONLY_PRINCIPLE",
            "ReplayEventKind",
            "TaskExecutionRecord",
            "RuntimeEventRecord",
            "RouteDecisionRecord",
            "ReplayFallbackRecord",
            "ReplayRetryRecord",
            "TaskLineage",
            "ReplayFoundationSnapshot",
            "ReplayFoundation",
            "record_task_execution",
            "record_route_decision",
            "record_fallback",
            "record_retry",
            "emit_runtime_event",
            "get_replay_foundation",
            "reset_replay_foundation",
        ]
        for name in expected:
            assert name in _mod.__all__, f"{name!r} missing from __all__"


# ===========================================================================
# 6-10: ReplayEventKind
# ===========================================================================

class TestReplayEventKind:
    def test_06_task_created(self):
        assert ReplayEventKind.TASK_CREATED == "task_created"

    def test_07_route_decision(self):
        assert ReplayEventKind.ROUTE_DECISION == "route_decision"

    def test_08_fallback_triggered(self):
        assert ReplayEventKind.FALLBACK_TRIGGERED == "fallback_triggered"

    def test_09_retry_triggered(self):
        assert ReplayEventKind.RETRY_TRIGGERED == "retry_triggered"

    def test_10_failure_domain_identified(self):
        assert ReplayEventKind.FAILURE_DOMAIN_IDENTIFIED == "failure_domain_identified"


# ===========================================================================
# 11-21: Record serialisation
# ===========================================================================

class TestRecordSerialisation:
    def test_11_task_execution_record_roundtrip(self):
        rec = TaskExecutionRecord(
            task_id="t1", trace_id="tr1", goal="do thing",
            final_lifecycle="completed", success=True,
        )
        d = rec.to_dict()
        restored = TaskExecutionRecord.from_dict(d)
        assert restored.task_id == "t1"
        assert restored.success is True

    def test_12_task_execution_record_id_auto(self):
        r1 = TaskExecutionRecord()
        r2 = TaskExecutionRecord()
        assert r1.record_id != r2.record_id
        assert r1.record_id.startswith("exec_")

    def test_13_task_execution_record_to_json(self):
        rec = TaskExecutionRecord(task_id="t1", goal="json test")
        raw = rec.to_json()
        parsed = json.loads(raw)
        assert parsed["task_id"] == "t1"

    def test_14_runtime_event_record_roundtrip(self):
        ev = RuntimeEventRecord(
            kind=ReplayEventKind.ROUTE_DECISION,
            task_id="t2",
            message="route selected",
        )
        d = ev.to_dict()
        restored = RuntimeEventRecord.from_dict(d)
        assert restored.task_id == "t2"
        assert restored.kind == ReplayEventKind.ROUTE_DECISION

    def test_15_runtime_event_id_auto(self):
        e1 = RuntimeEventRecord()
        e2 = RuntimeEventRecord()
        assert e1.event_id != e2.event_id
        assert e1.event_id.startswith("ev_")

    def test_16_runtime_event_parent_ids_preserved(self):
        e1 = RuntimeEventRecord(kind=ReplayEventKind.TASK_CREATED)
        e2 = RuntimeEventRecord(
            kind=ReplayEventKind.TASK_DISPATCHED,
            parent_event_ids=[e1.event_id],
        )
        assert e2.to_dict()["parent_event_ids"] == [e1.event_id]

    def test_17_route_decision_record_roundtrip(self):
        rec = RouteDecisionRecord(
            task_id="t1", transport_strategy="nats",
            effective_path="direct", capability_fit=True,
        )
        d = rec.to_dict()
        restored = RouteDecisionRecord.from_dict(d)
        assert restored.capability_fit is True
        assert restored.effective_path == "direct"

    def test_18_fallback_record_roundtrip(self):
        rec = ReplayFallbackRecord(
            primary_task_id="t1", fallback_task_id="t2", reason="timeout"
        )
        d = rec.to_dict()
        restored = ReplayFallbackRecord.from_dict(d)
        assert restored.primary_task_id == "t1"
        assert restored.reason == "timeout"

    def test_19_retry_record_roundtrip(self):
        rec = ReplayRetryRecord(
            original_task_id="t1", retry_task_id="t2",
            attempt_number=2, reason="transient_error",
        )
        d = rec.to_dict()
        restored = ReplayRetryRecord.from_dict(d)
        assert restored.attempt_number == 2

    def test_20_task_lineage_json_serialisable(self):
        lineage = TaskLineage(
            task_id="t1", trace_id="tr1",
            execution_record=TaskExecutionRecord(task_id="t1"),
            route_decisions=[RouteDecisionRecord(task_id="t1")],
        )
        json.dumps(lineage.to_dict())  # should not raise

    def test_21_replay_foundation_snapshot_json_serialisable(self):
        snap = ReplayFoundationSnapshot()
        json.dumps(snap.to_dict())  # should not raise


# ===========================================================================
# 22-37: ReplayFoundation operations
# ===========================================================================

class TestReplayFoundationOperations:
    def test_22_record_execution_stores(self):
        foundation = ReplayFoundation()
        rec = TaskExecutionRecord(task_id="t1")
        foundation.record_execution(rec)
        assert foundation.get_execution_record("t1") is rec

    def test_23_get_execution_record_by_task_id(self):
        foundation = ReplayFoundation()
        rec = TaskExecutionRecord(task_id="t99")
        foundation.record_execution(rec)
        assert foundation.get_execution_record("t99").task_id == "t99"

    def test_24_emit_event_stores_in_ring(self):
        foundation = ReplayFoundation()
        ev = RuntimeEventRecord(kind=ReplayEventKind.TASK_CREATED, task_id="t1")
        foundation.emit_event(ev)
        events = foundation.get_events_for_task("t1")
        assert len(events) == 1

    def test_25_get_events_for_task(self):
        foundation = ReplayFoundation()
        foundation.emit_event(RuntimeEventRecord(
            kind=ReplayEventKind.TASK_CREATED, task_id="t_a"
        ))
        foundation.emit_event(RuntimeEventRecord(
            kind=ReplayEventKind.TASK_DISPATCHED, task_id="t_a"
        ))
        foundation.emit_event(RuntimeEventRecord(
            kind=ReplayEventKind.TASK_COMPLETED, task_id="t_b"
        ))
        assert len(foundation.get_events_for_task("t_a")) == 2
        assert len(foundation.get_events_for_task("t_b")) == 1

    def test_26_record_route_stores(self):
        foundation = ReplayFoundation()
        rec = RouteDecisionRecord(task_id="t1", transport_strategy="relay")
        foundation.record_route(rec)
        decisions = foundation.get_route_decisions("t1")
        assert len(decisions) == 1

    def test_27_get_route_decisions_by_task_id(self):
        foundation = ReplayFoundation()
        foundation.record_route(RouteDecisionRecord(task_id="t2", effective_path="mesh"))
        assert foundation.get_route_decisions("t2")[0].effective_path == "mesh"

    def test_28_record_fallback_stores(self):
        foundation = ReplayFoundation()
        rec = ReplayFallbackRecord(primary_task_id="t1", fallback_task_id="t2")
        foundation.record_fallback(rec)
        assert len(foundation.get_fallback_history("t1")) == 1

    def test_29_get_fallback_history(self):
        foundation = ReplayFoundation()
        foundation.record_fallback(
            ReplayFallbackRecord(primary_task_id="t1", fallback_task_id="t2", reason="err")
        )
        history = foundation.get_fallback_history("t1")
        assert history[0].reason == "err"

    def test_30_record_retry_stores(self):
        foundation = ReplayFoundation()
        rec = ReplayRetryRecord(original_task_id="t1", retry_task_id="t2")
        foundation.record_retry(rec)
        assert len(foundation.get_retry_history("t1")) == 1

    def test_31_get_retry_history(self):
        foundation = ReplayFoundation()
        foundation.record_retry(ReplayRetryRecord(
            original_task_id="t1", retry_task_id="t2", attempt_number=1
        ))
        foundation.record_retry(ReplayRetryRecord(
            original_task_id="t1", retry_task_id="t3", attempt_number=2
        ))
        history = foundation.get_retry_history("t1")
        assert len(history) == 2

    def test_32_get_task_lineage_returns_lineage(self):
        foundation = ReplayFoundation()
        foundation.record_execution(TaskExecutionRecord(task_id="t1", trace_id="tr1"))
        lineage = foundation.get_task_lineage("t1")
        assert isinstance(lineage, TaskLineage)
        assert lineage.task_id == "t1"

    def test_33_lineage_execution_record_matches(self):
        foundation = ReplayFoundation()
        rec = TaskExecutionRecord(task_id="t1", goal="my goal")
        foundation.record_execution(rec)
        lineage = foundation.get_task_lineage("t1")
        assert lineage.execution_record.goal == "my goal"

    def test_34_replay_task_timeline_returns_dicts(self):
        foundation = ReplayFoundation()
        foundation.emit_event(RuntimeEventRecord(
            kind=ReplayEventKind.TASK_CREATED, task_id="t1",
            recorded_at=1.0,
        ))
        foundation.emit_event(RuntimeEventRecord(
            kind=ReplayEventKind.TASK_COMPLETED, task_id="t1",
            recorded_at=2.0,
        ))
        timeline = foundation.replay_task_timeline("t1")
        assert len(timeline) == 2
        assert all(isinstance(e, dict) for e in timeline)

    def test_35_get_result_lineage_retry_count(self):
        foundation = ReplayFoundation()
        foundation.record_execution(TaskExecutionRecord(task_id="t1", final_lifecycle="failed"))
        foundation.record_retry(ReplayRetryRecord(original_task_id="t1", retry_task_id="t2"))
        foundation.record_retry(ReplayRetryRecord(original_task_id="t1", retry_task_id="t3"))
        lineage = foundation.get_result_lineage("t1")
        assert lineage["retry_count"] == 2

    def test_36_snapshot_returns_correct_type(self):
        foundation = ReplayFoundation()
        snap = foundation.snapshot()
        assert isinstance(snap, ReplayFoundationSnapshot)

    def test_37_snapshot_counts_match(self):
        foundation = ReplayFoundation()
        foundation.record_execution(TaskExecutionRecord(task_id="t1"))
        foundation.record_execution(TaskExecutionRecord(task_id="t2"))
        foundation.emit_event(RuntimeEventRecord(task_id="t1"))
        snap = foundation.snapshot()
        assert snap.execution_record_count == 2
        assert snap.runtime_event_count == 1


# ===========================================================================
# 38-45: Singleton and helpers
# ===========================================================================

class TestSingletonAndHelpers:
    def test_38_get_replay_foundation_singleton(self):
        f1 = get_replay_foundation()
        f2 = get_replay_foundation()
        assert f1 is f2

    def test_39_reset_replay_foundation(self):
        f1 = get_replay_foundation()
        reset_replay_foundation()
        f2 = get_replay_foundation()
        assert f1 is not f2

    def test_40_record_task_execution_with_canonical_task(self):
        from core.canonical_task import build_canonical_task, TaskOrigin, TaskLifecycle
        task = build_canonical_task(goal="do thing", origin=TaskOrigin.API_REQUEST)
        task.lifecycle = TaskLifecycle.COMPLETED
        task.result.success = True
        rec = record_task_execution(task)
        assert rec.task_id == task.identity.task_id
        assert rec.success is True

    def test_41_record_route_decision_helper(self):
        rec = record_route_decision(
            "t1", "tr1",
            selected_targets=["device_a"],
            transport_strategy="websocket",
            effective_path="direct",
        )
        assert rec.task_id == "t1"
        stored = get_replay_foundation().get_route_decisions("t1")
        assert len(stored) == 1

    def test_42_record_fallback_helper(self):
        rec = record_fallback("t1", "t2", "transport_error", trace_id="tr1")
        assert rec.primary_task_id == "t1"
        assert rec.fallback_task_id == "t2"
        stored = get_replay_foundation().get_fallback_history("t1")
        assert len(stored) == 1

    def test_43_record_retry_helper(self):
        rec = record_retry("t1", "t2", "transient", attempt_number=1, trace_id="tr1")
        assert rec.original_task_id == "t1"
        assert rec.attempt_number == 1
        stored = get_replay_foundation().get_retry_history("t1")
        assert len(stored) == 1

    def test_44_emit_runtime_event_helper(self):
        ev = emit_runtime_event(
            ReplayEventKind.ROUTE_DECISION,
            task_id="t1",
            source="test_source",
            message="route resolved",
        )
        assert ev.source == "test_source"
        events = get_replay_foundation().get_events_for_task("t1")
        assert len(events) == 1

    def test_45_replay_timeline_sorted_by_recorded_at(self):
        foundation = get_replay_foundation()
        t = time.time()
        # Add events out of order
        ev2 = RuntimeEventRecord(
            kind=ReplayEventKind.TASK_DISPATCHED,
            task_id="t1",
            recorded_at=t + 0.1,
        )
        ev1 = RuntimeEventRecord(
            kind=ReplayEventKind.TASK_CREATED,
            task_id="t1",
            recorded_at=t,
        )
        foundation.emit_event(ev2)
        foundation.emit_event(ev1)
        timeline = foundation.replay_task_timeline("t1")
        ts_list = [e["recorded_at"] for e in timeline]
        assert ts_list == sorted(ts_list)
