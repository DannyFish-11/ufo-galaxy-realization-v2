#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_operator_task_route_failure_inspection.py
=====================================================
PR-E — Operator Surface + Replay Foundation

Validates the operator inspection API end-to-end: task, route, executor,
failure domain, and lineage inspection with realistic canonical task data.

Coverage:
  1.  inspect_task() for a COMPLETED task has success=True.
  2.  inspect_task() for a FAILED task has success=False.
  3.  inspect_task() for a FAILED task has non-empty failure_domain.
  4.  inspect_task() error_code populated on failure.
  5.  inspect_route() for a task with targets has non-empty selected_targets.
  6.  inspect_route() effective_path reflects routing data.
  7.  inspect_failure_domain() for failed task has correct failure_domain.
  8.  inspect_failure_domain() for completed task still returns data.
  9.  inspect_lineage() for task with graph children includes them.
  10. inspect_lineage() timeline starts with "created" event.
  11. operator_snapshot() active_task_count reflects registered tasks.
  12. operator_snapshot() recent_tasks list is non-empty after registration.
  13. inspect_task() to_dict() is JSON-serialisable.
  14. inspect_route() to_dict() is JSON-serialisable.
  15. inspect_failure_domain() to_dict() is JSON-serialisable.
  16. inspect_lineage() to_dict() is JSON-serialisable.
  17. Two tasks with same trace_id share trace_id in inspection.
  18. Replay foundation integrated: record_task_execution for completed task.
  19. Replay foundation: route decision stored and queryable.
  20. Audit event semantics: accepted + completed for a task are both recorded.
  21. Audit event semantics: failed task produces TASK_FAILED audit record.
  22. Audit semantics: get_by_task returns all audit events for task.
  23. inspect_task origin field is a known TaskOrigin value.
  24. TaskInspection fields match underlying CanonicalTask.
  25. RouteInspection fields match underlying CanonicalTask routing.
"""

from __future__ import annotations

import json
import sys
import os
import time

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.operator_surface import (
    get_operator_surface,
    reset_operator_surface,
    TaskInspection,
    RouteInspection,
    FailureDomainInspection,
    LineageInspection,
)
from core.replay_foundation import (
    get_replay_foundation,
    reset_replay_foundation,
    record_task_execution,
    record_route_decision,
)
from core.audit_event_semantics import (
    get_audit_event_semantics,
    reset_audit_event_semantics,
    audit_task_accepted,
    audit_task_completed,
    audit_task_failed,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_all():
    reset_operator_surface()
    reset_replay_foundation()
    reset_audit_event_semantics()
    from core.canonical_task import reset_canonical_task_runtime
    from core.source_runtime_posture import reset_source_runtime_posture_runtime

    reset_canonical_task_runtime()
    reset_source_runtime_posture_runtime()
    yield
    reset_operator_surface()
    reset_replay_foundation()
    reset_audit_event_semantics()
    reset_canonical_task_runtime()
    reset_source_runtime_posture_runtime()


def _make_completed_task(goal: str = "do work", targets=None):
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskLifecycle,
        TaskOrigin,
    )

    task = build_canonical_task(
        goal=goal,
        origin=TaskOrigin.API_REQUEST,
        requested_action="exec_action",
        selected_targets=targets or ["device_A"],
    )
    task.lifecycle = TaskLifecycle.COMPLETED
    task.result.success = True
    task.completed_at = time.time()
    get_canonical_task_runtime().register(task)
    return task


def _make_failed_task(goal: str = "failed task", failure_domain: str = "routing"):
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskLifecycle,
        TaskOrigin,
        FailureDomain,
    )

    task = build_canonical_task(
        goal=goal,
        origin=TaskOrigin.AI_INTENT,
        requested_action="fail_action",
        selected_targets=["device_B"],
    )
    task.lifecycle = TaskLifecycle.FAILED
    task.result.success = False
    task.result.error_code = "ROUTE_FAILED"
    task.result.failure_domain = FailureDomain(failure_domain)
    get_canonical_task_runtime().register(task)
    return task


# ===========================================================================
# 1-4: Task inspection
# ===========================================================================


class TestTaskInspection:
    def test_01_completed_task_success_true(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.success is True

    def test_02_failed_task_success_false(self):
        task = _make_failed_task()
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.success is False

    def test_03_failed_task_failure_domain_populated(self):
        task = _make_failed_task(failure_domain="routing")
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.failure_domain == "routing"

    def test_04_failed_task_error_code_populated(self):
        task = _make_failed_task()
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.error_code == "ROUTE_FAILED"


# ===========================================================================
# 5-6: Route inspection
# ===========================================================================


class TestRouteInspection:
    def test_05_route_inspection_has_targets(self):
        task = _make_completed_task(targets=["dev_X", "dev_Y"])
        surface = get_operator_surface()
        route = surface.inspect_route(task.identity.task_id)
        assert route is not None
        assert "dev_X" in route.selected_targets

    def test_06_route_inspection_effective_path(self):
        from core.canonical_task import (
            build_canonical_task,
            get_canonical_task_runtime,
            TaskLifecycle,
            TaskOrigin,
        )

        task = build_canonical_task(goal="route test", origin=TaskOrigin.API_REQUEST)
        task.routing.effective_path = "relay_path_01"
        task.lifecycle = TaskLifecycle.ROUTED
        get_canonical_task_runtime().register(task)
        surface = get_operator_surface()
        route = surface.inspect_route(task.identity.task_id)
        assert route is not None
        assert route.effective_path == "relay_path_01"


# ===========================================================================
# 7-8: Failure domain inspection
# ===========================================================================


class TestFailureDomainInspection:
    def test_07_failed_task_correct_failure_domain(self):
        task = _make_failed_task(failure_domain="transport")
        surface = get_operator_surface()
        fd = surface.inspect_failure_domain(task.identity.task_id)
        assert fd is not None
        assert fd.failure_domain == "transport"

    def test_08_completed_task_failure_domain_inspection_returns_data(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        fd = surface.inspect_failure_domain(task.identity.task_id)
        # Should return an inspection even for completed tasks (not None)
        assert fd is not None


# ===========================================================================
# 9-10: Lineage inspection
# ===========================================================================


class TestLineageInspection:
    def test_09_lineage_includes_children(self):
        from core.canonical_task import (
            build_canonical_task,
            get_canonical_task_runtime,
            TaskLifecycle,
            TaskOrigin,
        )

        parent = build_canonical_task(goal="parent", origin=TaskOrigin.API_REQUEST)
        child = build_canonical_task(goal="child", origin=TaskOrigin.ORCHESTRATOR_TASK)
        parent.graph.children.append(child.identity.task_id)
        parent.lifecycle = TaskLifecycle.COMPLETED
        get_canonical_task_runtime().register(parent)
        get_canonical_task_runtime().register(child)
        surface = get_operator_surface()
        lineage = surface.inspect_lineage(parent.identity.task_id)
        assert lineage is not None
        assert child.identity.task_id in lineage.children

    def test_10_lineage_timeline_starts_with_created(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        lineage = surface.inspect_lineage(task.identity.task_id)
        assert lineage is not None
        assert lineage.timeline  # non-empty
        first_event = lineage.timeline[0]
        assert first_event["event"] == "created"


# ===========================================================================
# 11-12: Operator snapshot
# ===========================================================================


class TestOperatorSnapshot:
    def test_11_snapshot_active_count_reflects_registered(self):
        _make_completed_task("task_one")
        _make_completed_task("task_two")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert snap.active_task_count == 2

    def test_11b_snapshot_includes_source_runtime_posture_summary(self):
        from core.source_runtime_posture import (
            SourceRuntimePosture,
            record_source_runtime_posture,
        )

        record_source_runtime_posture(
            task_id="task-posture",
            trace_id="trace-posture",
            source_device_id="phone_01",
            posture=SourceRuntimePosture.JOIN_RUNTIME,
            target_device_ids=["desktop_01"],
            reason="test",
        )

        surface = get_operator_surface()
        snap = surface.operator_snapshot().to_dict()
        assert snap["source_runtime_posture_counts"]["join_runtime"] >= 1
        assert snap["recent_source_runtime_postures"]

    def test_12_snapshot_recent_tasks_non_empty(self):
        _make_completed_task("snap_task")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert len(snap.recent_tasks) >= 1


# ===========================================================================
# 13-16: Serialisation
# ===========================================================================


class TestSerialisation:
    def test_13_inspect_task_json_serialisable(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        json.dumps(insp.to_dict())

    def test_14_inspect_route_json_serialisable(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        route = surface.inspect_route(task.identity.task_id)
        assert route is not None
        json.dumps(route.to_dict())

    def test_15_inspect_failure_domain_json_serialisable(self):
        task = _make_failed_task()
        surface = get_operator_surface()
        fd = surface.inspect_failure_domain(task.identity.task_id)
        assert fd is not None
        json.dumps(fd.to_dict())

    def test_16_inspect_lineage_json_serialisable(self):
        task = _make_completed_task()
        surface = get_operator_surface()
        lineage = surface.inspect_lineage(task.identity.task_id)
        assert lineage is not None
        json.dumps(lineage.to_dict())


# ===========================================================================
# 17-22: Replay and audit integration
# ===========================================================================


class TestReplayAuditIntegration:
    def test_17_two_tasks_same_trace_share_trace_id(self):
        from core.canonical_task import (
            build_canonical_task,
            get_canonical_task_runtime,
            TaskOrigin,
            TaskLifecycle,
        )

        trace = "trace_shared_001"
        t1 = build_canonical_task(goal="t1", origin=TaskOrigin.API_REQUEST)
        t1.identity.trace_id = trace
        t1.lifecycle = TaskLifecycle.COMPLETED
        t2 = build_canonical_task(goal="t2", origin=TaskOrigin.WORKFLOW_STEP)
        t2.identity.trace_id = trace
        t2.lifecycle = TaskLifecycle.COMPLETED
        rt = get_canonical_task_runtime()
        rt.register(t1)
        rt.register(t2)
        surface = get_operator_surface()
        i1 = surface.inspect_task(t1.identity.task_id)
        i2 = surface.inspect_task(t2.identity.task_id)
        assert i1 is not None and i2 is not None
        assert i1.trace_id == trace
        assert i2.trace_id == trace

    def test_18_record_task_execution_replay(self):
        task = _make_completed_task("replay task")
        rec = record_task_execution(task)
        assert rec.task_id == task.identity.task_id
        stored = get_replay_foundation().get_execution_record(task.identity.task_id)
        assert stored is not None

    def test_19_route_decision_stored_and_queryable(self):
        task = _make_completed_task("route task")
        record_route_decision(
            task.identity.task_id,
            task.identity.trace_id,
            selected_targets=["device_A"],
            effective_path="direct",
            transport_strategy="websocket",
        )
        decisions = get_replay_foundation().get_route_decisions(task.identity.task_id)
        assert len(decisions) == 1
        assert decisions[0].effective_path == "direct"

    def test_20_audit_accepted_and_completed_recorded(self):
        task = _make_completed_task("audit task")
        audit_task_accepted(task.identity.task_id, goal="audit task")
        audit_task_completed(task.identity.task_id, success=True)
        records = get_audit_event_semantics().get_by_task(task.identity.task_id)
        kinds = {r.kind for r in records}
        assert "task_accepted" in kinds
        assert "task_completed" in kinds

    def test_21_failed_task_produces_audit_failed(self):
        task = _make_failed_task()
        audit_task_failed(task.identity.task_id, error_code="ROUTE_FAILED")
        records = get_audit_event_semantics().get_by_task(task.identity.task_id)
        assert any(r.kind == "task_failed" for r in records)

    def test_22_get_by_task_returns_all_audit_events(self):
        task = _make_completed_task("multi audit")
        audit_task_accepted(task.identity.task_id)
        audit_task_completed(task.identity.task_id)
        records = get_audit_event_semantics().get_by_task(task.identity.task_id)
        assert len(records) >= 2


# ===========================================================================
# 23-25: Field alignment
# ===========================================================================


class TestFieldAlignment:
    def test_23_inspect_task_origin_is_known(self):
        from core.canonical_task import TaskOrigin

        task = _make_completed_task()
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        known_origins = {o.value for o in TaskOrigin}
        assert insp.origin in known_origins

    def test_24_task_inspection_task_id_matches(self):
        task = _make_completed_task("field alignment")
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.task_id == task.identity.task_id
        assert insp.trace_id == task.identity.trace_id
        assert insp.goal == "field alignment"

    def test_25_route_inspection_targets_match(self):
        task = _make_completed_task(targets=["dev_alpha"])
        surface = get_operator_surface()
        route = surface.inspect_route(task.identity.task_id)
        assert route is not None
        assert "dev_alpha" in route.selected_targets
