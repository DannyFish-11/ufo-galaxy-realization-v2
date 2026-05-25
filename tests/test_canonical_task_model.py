#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_canonical_task_model.py
====================================

PR-A: Canonical Task & Execution Spine — CanonicalTask model tests.

Test groups
-----------
  A)  Authority sentinels importable and correct values
  B)  TaskLifecycle enum values
  C)  TaskOrigin enum values
  D)  RemoteExecutionStyle enum values
  E)  FailureDomain enum values
  F)  TaskIdentity construction and defaults
  G)  TaskIdentity.to_dict() serialisation
  H)  TaskIntent construction and defaults
  I)  TaskIntent.to_dict() serialisation
  J)  TaskPlanning construction and defaults
  K)  TaskPlanning.to_dict() serialisation
  L)  TaskRouting construction and defaults
  M)  TaskRouting.to_dict() serialisation
  N)  TaskExecution construction and defaults
  O)  TaskExecution.to_dict() serialisation
  P)  TaskGraphRelations construction and defaults
  Q)  TaskGraphRelations.to_dict() serialisation
  R)  TaskResultSummary construction and defaults
  S)  TaskResultSummary truncates long result_summary
  T)  CanonicalTask construction and defaults
  U)  CanonicalTask.to_dict() contains all field groups
  V)  CanonicalTask.task_id / trace_id / session_id properties
  W)  CanonicalTask.advance_lifecycle() transitions
  X)  CanonicalTask.advance_lifecycle() timestamps
  Y)  build_canonical_task() helper constructs task
  Z)  build_canonical_task() generates unique IDs
  AA) build_canonical_task() registers in runtime by default
  AB) build_canonical_task(register=False) skips registration
  AC) CanonicalTaskRuntime.register() idempotent upsert
  AD) CanonicalTaskRuntime.register() empty task_id raises ValueError
  AE) CanonicalTaskRuntime.get_by_task_id() found and not-found
  AF) CanonicalTaskRuntime.get_by_trace_id() found and not-found
  AG) CanonicalTaskRuntime.update_lifecycle() transitions
  AH) CanonicalTaskRuntime.update_lifecycle() unknown task_id returns None
  AI) CanonicalTaskRuntime.get_observability_log() ring-buffer
  AJ) CanonicalTaskRuntime.snapshot() structure
  AK) get_canonical_task_runtime() returns singleton
  AL) reset_canonical_task_runtime() resets singleton
  AM) project_to_task_envelope() produces object with task_id
  AN) project_to_task_envelope() produces object with trace_id
  AO) project_to_task_envelope() tool_name maps from execution.tool
  AP) project_to_task_envelope() targets mapped from routing.selected_targets
  AQ) apply_result_envelope() success path → COMPLETED lifecycle
  AR) apply_result_envelope() failure path → FAILED lifecycle
  AS) apply_result_envelope() dict input works
  AT) apply_result_envelope() unknown success stays unchanged
  AU) CanonicalTaskRecord construction and to_dict()
  AV) CanonicalTaskSnapshot construction and to_dict()
  AW) All public names appear in __all__
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from core.canonical_task import (
    CANONICAL_TASK_AUTHORITY,
    CANONICAL_TASK_LAYER_POSITION,
    CANONICAL_TASK_ONTOLOGY_VERSION,
    CANONICAL_EXECUTION_SPINE_POLICY,
    TASK_ALLOCATION_TRUTH_AUTHORITY,
    CanonicalTask,
    CanonicalTaskRecord,
    CanonicalTaskRuntime,
    CanonicalTaskSnapshot,
    FailureDomain,
    RemoteExecutionStyle,
    TaskExecution,
    TaskGraphRelations,
    TaskIdentity,
    TaskIntent,
    TaskLifecycle,
    TaskOrigin,
    TaskPlanning,
    TaskResultSummary,
    TaskRouting,
    apply_result_envelope,
    build_canonical_task,
    get_canonical_task_runtime,
    project_to_task_envelope,
    reset_canonical_task_runtime,
)
import core.canonical_task as _mod


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset the singleton before every test."""
    reset_canonical_task_runtime()
    yield
    reset_canonical_task_runtime()


# ===========================================================================
# A) Authority sentinels
# ===========================================================================

def test_A1_CANONICAL_TASK_AUTHORITY_importable():
    assert CANONICAL_TASK_AUTHORITY is not None


def test_A2_CANONICAL_TASK_AUTHORITY_value():
    assert "CANONICAL_TASK" in CANONICAL_TASK_AUTHORITY


def test_A3_CANONICAL_TASK_LAYER_POSITION():
    assert isinstance(CANONICAL_TASK_LAYER_POSITION, int)
    assert CANONICAL_TASK_LAYER_POSITION > 0


def test_A4_CANONICAL_TASK_ONTOLOGY_VERSION():
    assert isinstance(CANONICAL_TASK_ONTOLOGY_VERSION, str)
    assert CANONICAL_TASK_ONTOLOGY_VERSION


def test_A5_CANONICAL_EXECUTION_SPINE_POLICY():
    assert "CommandRouter" in CANONICAL_EXECUTION_SPINE_POLICY
    assert "route_envelope" in CANONICAL_EXECUTION_SPINE_POLICY


# ===========================================================================
# B) TaskLifecycle enum
# ===========================================================================

def test_B1_lifecycle_created():
    assert TaskLifecycle.CREATED.value == "created"


def test_B2_lifecycle_admitted():
    assert TaskLifecycle.ADMITTED.value == "admitted"


def test_B3_lifecycle_planned():
    assert TaskLifecycle.PLANNED.value == "planned"


def test_B4_lifecycle_routed():
    assert TaskLifecycle.ROUTED.value == "routed"


def test_B5_lifecycle_dispatched():
    assert TaskLifecycle.DISPATCHED.value == "dispatched"


def test_B6_lifecycle_running():
    assert TaskLifecycle.RUNNING.value == "running"


def test_B7_lifecycle_completed():
    assert TaskLifecycle.COMPLETED.value == "completed"


def test_B8_lifecycle_failed():
    assert TaskLifecycle.FAILED.value == "failed"


def test_B9_lifecycle_cancelled():
    assert TaskLifecycle.CANCELLED.value == "cancelled"


def test_B10_lifecycle_degraded():
    assert TaskLifecycle.DEGRADED.value == "degraded"


# ===========================================================================
# C) TaskOrigin enum
# ===========================================================================

def test_C1_origin_api_request():
    assert TaskOrigin.API_REQUEST.value == "api_request"


def test_C2_origin_ai_intent():
    assert TaskOrigin.AI_INTENT.value == "ai_intent"


def test_C3_origin_workflow_step():
    assert TaskOrigin.WORKFLOW_STEP.value == "workflow_step"


def test_C4_origin_orchestrator_task():
    assert TaskOrigin.ORCHESTRATOR_TASK.value == "orchestrator_task"


def test_C5_origin_device_command():
    assert TaskOrigin.DEVICE_COMMAND.value == "device_command"


def test_C6_origin_mcp_tool_call():
    assert TaskOrigin.MCP_TOOL_CALL.value == "mcp_tool_call"


def test_C7_origin_skill_invocation():
    assert TaskOrigin.SKILL_INVOCATION.value == "skill_invocation"


def test_C8_origin_scheduler():
    assert TaskOrigin.SCHEDULER.value == "scheduler"


def test_C9_origin_unknown():
    assert TaskOrigin.UNKNOWN.value == "unknown"


# ===========================================================================
# D) RemoteExecutionStyle enum
# ===========================================================================

def test_D1_remote_command_only():
    assert RemoteExecutionStyle.COMMAND_ONLY.value == "command_only"


def test_D2_remote_agent_runtime():
    assert RemoteExecutionStyle.AGENT_RUNTIME.value == "agent_runtime"


def test_D3_remote_local():
    assert RemoteExecutionStyle.LOCAL.value == "local"


def test_D4_remote_none():
    assert RemoteExecutionStyle.NONE.value == "none"


# ===========================================================================
# E) FailureDomain enum
# ===========================================================================

def test_E1_failure_routing():
    assert FailureDomain.ROUTING.value == "routing"


def test_E2_failure_transport():
    assert FailureDomain.TRANSPORT.value == "transport"


def test_E3_failure_execution():
    assert FailureDomain.EXECUTION.value == "execution"


def test_E4_failure_policy():
    assert FailureDomain.POLICY.value == "policy"


def test_E5_failure_timeout():
    assert FailureDomain.TIMEOUT.value == "timeout"


def test_E6_failure_internal():
    assert FailureDomain.INTERNAL.value == "internal"


def test_E7_failure_unknown():
    assert FailureDomain.UNKNOWN.value == "unknown"


# ===========================================================================
# F) TaskIdentity
# ===========================================================================

def test_F1_task_identity_defaults():
    ti = TaskIdentity()
    assert ti.task_id.startswith("task_")
    assert ti.trace_id.startswith("trace_")
    assert ti.session_id == ""
    assert ti.root_task_id == ""
    assert ti.parent_task_id == ""


def test_F2_task_identity_custom():
    ti = TaskIdentity(task_id="t1", trace_id="tr1", session_id="s1", root_task_id="r1", parent_task_id="p1")
    assert ti.task_id == "t1"
    assert ti.trace_id == "tr1"
    assert ti.session_id == "s1"
    assert ti.root_task_id == "r1"
    assert ti.parent_task_id == "p1"


# ===========================================================================
# G) TaskIdentity.to_dict()
# ===========================================================================

def test_G1_task_identity_to_dict_keys():
    d = TaskIdentity().to_dict()
    for k in ("task_id", "trace_id", "session_id", "root_task_id", "parent_task_id"):
        assert k in d


# ===========================================================================
# H) TaskIntent
# ===========================================================================

def test_H1_task_intent_defaults():
    ti = TaskIntent()
    assert ti.goal == ""
    assert ti.origin == TaskOrigin.UNKNOWN
    assert ti.reason == ""
    assert ti.requested_action == ""


# ===========================================================================
# I) TaskIntent.to_dict()
# ===========================================================================

def test_I1_task_intent_to_dict_keys():
    d = TaskIntent().to_dict()
    for k in ("goal", "origin", "reason", "requested_action"):
        assert k in d


def test_I2_task_intent_origin_serialized_as_value():
    ti = TaskIntent(origin=TaskOrigin.API_REQUEST)
    d = ti.to_dict()
    assert d["origin"] == "api_request"


# ===========================================================================
# J) TaskPlanning
# ===========================================================================

def test_J1_task_planning_defaults():
    tp = TaskPlanning()
    assert tp.priority == 5
    assert isinstance(tp.constraints, dict)
    assert isinstance(tp.required_capabilities, list)
    assert tp.fallback_policy == ""
    assert tp.remote_execution_mode == RemoteExecutionStyle.NONE


# ===========================================================================
# K) TaskPlanning.to_dict()
# ===========================================================================

def test_K1_task_planning_to_dict_keys():
    d = TaskPlanning().to_dict()
    for k in ("priority", "constraints", "required_capabilities", "fallback_policy", "remote_execution_mode"):
        assert k in d


# ===========================================================================
# L) TaskRouting
# ===========================================================================

def test_L1_task_routing_defaults():
    tr = TaskRouting()
    assert tr.selected_targets == []
    assert tr.route_preference == ""
    assert tr.transport_preference == ""
    assert tr.effective_path == ""


# ===========================================================================
# M) TaskRouting.to_dict()
# ===========================================================================

def test_M1_task_routing_to_dict_keys():
    d = TaskRouting().to_dict()
    for k in ("selected_targets", "route_preference", "transport_preference", "effective_path"):
        assert k in d


# ===========================================================================
# N) TaskExecution
# ===========================================================================

def test_N1_task_execution_defaults():
    te = TaskExecution()
    assert te.tool == ""
    assert te.skill == ""
    assert te.command == ""
    assert isinstance(te.args, dict)
    assert te.timeout_seconds == 30.0
    assert te.retry_policy == ""
    assert te.permission_level == 0


# ===========================================================================
# O) TaskExecution.to_dict()
# ===========================================================================

def test_O1_task_execution_to_dict_keys():
    d = TaskExecution().to_dict()
    for k in ("tool", "skill", "command", "args", "timeout_seconds", "retry_policy", "permission_level"):
        assert k in d


# ===========================================================================
# P) TaskGraphRelations
# ===========================================================================

def test_P1_task_graph_relations_defaults():
    tg = TaskGraphRelations()
    assert tg.dependencies == []
    assert tg.retry_of == ""
    assert tg.fallback_of == ""
    assert tg.children == []


# ===========================================================================
# Q) TaskGraphRelations.to_dict()
# ===========================================================================

def test_Q1_task_graph_relations_to_dict_keys():
    d = TaskGraphRelations().to_dict()
    for k in ("dependencies", "retry_of", "fallback_of", "children"):
        assert k in d


# ===========================================================================
# R) TaskResultSummary
# ===========================================================================

def test_R1_task_result_summary_defaults():
    tr = TaskResultSummary()
    assert tr.success is None
    assert tr.error_code == ""
    assert tr.failure_domain == FailureDomain.UNKNOWN
    assert tr.result_summary == ""


def test_R2_task_result_summary_to_dict_keys():
    d = TaskResultSummary().to_dict()
    for k in ("success", "error_code", "failure_domain", "result_summary"):
        assert k in d


# ===========================================================================
# S) TaskResultSummary truncation
# ===========================================================================

def test_S1_result_summary_truncated():
    long_str = "x" * 500
    tr = TaskResultSummary(result_summary=long_str)
    assert len(tr.result_summary) <= 400


def test_S2_result_summary_not_truncated_when_short():
    short_str = "ok"
    tr = TaskResultSummary(result_summary=short_str)
    assert tr.result_summary == "ok"


# ===========================================================================
# T) CanonicalTask construction
# ===========================================================================

def test_T1_canonical_task_defaults(reset_runtime):
    task = CanonicalTask()
    assert task.lifecycle == TaskLifecycle.CREATED
    assert isinstance(task.identity, TaskIdentity)
    assert isinstance(task.intent, TaskIntent)
    assert isinstance(task.planning, TaskPlanning)
    assert isinstance(task.routing, TaskRouting)
    assert isinstance(task.execution, TaskExecution)
    assert isinstance(task.graph, TaskGraphRelations)
    assert isinstance(task.result, TaskResultSummary)


# ===========================================================================
# U) CanonicalTask.to_dict()
# ===========================================================================

def test_U1_to_dict_contains_all_groups(reset_runtime):
    task = CanonicalTask()
    d = task.to_dict()
    for k in ("identity", "intent", "planning", "routing", "execution", "graph", "result", "lifecycle"):
        assert k in d


# ===========================================================================
# V) Property accessors
# ===========================================================================

def test_V1_task_id_property(reset_runtime):
    task = CanonicalTask(identity=TaskIdentity(task_id="my_task"))
    assert task.task_id == "my_task"


def test_V2_trace_id_property(reset_runtime):
    task = CanonicalTask(identity=TaskIdentity(trace_id="my_trace"))
    assert task.trace_id == "my_trace"


def test_V3_session_id_property(reset_runtime):
    task = CanonicalTask(identity=TaskIdentity(session_id="sess1"))
    assert task.session_id == "sess1"


# ===========================================================================
# W) advance_lifecycle()
# ===========================================================================

def test_W1_advance_lifecycle_basic(reset_runtime):
    task = CanonicalTask()
    task.advance_lifecycle(TaskLifecycle.ADMITTED)
    assert task.lifecycle == TaskLifecycle.ADMITTED


def test_W2_advance_lifecycle_to_completed(reset_runtime):
    task = CanonicalTask()
    task.advance_lifecycle(TaskLifecycle.COMPLETED)
    assert task.lifecycle == TaskLifecycle.COMPLETED


def test_W3_advance_lifecycle_returns_self(reset_runtime):
    task = CanonicalTask()
    result = task.advance_lifecycle(TaskLifecycle.RUNNING)
    assert result is task


# ===========================================================================
# X) advance_lifecycle() timestamps
# ===========================================================================

def test_X1_advance_lifecycle_stamps_admitted_at(reset_runtime):
    task = CanonicalTask()
    assert task.admitted_at is None
    task.advance_lifecycle(TaskLifecycle.ADMITTED)
    assert task.admitted_at is not None


def test_X2_advance_lifecycle_stamps_completed_at(reset_runtime):
    task = CanonicalTask()
    task.advance_lifecycle(TaskLifecycle.COMPLETED)
    assert task.completed_at is not None


def test_X3_advance_lifecycle_does_not_overwrite_existing_ts(reset_runtime):
    task = CanonicalTask()
    task.advance_lifecycle(TaskLifecycle.ADMITTED)
    first_ts = task.admitted_at
    task.advance_lifecycle(TaskLifecycle.ADMITTED)  # second call
    assert task.admitted_at == first_ts


# ===========================================================================
# Y) build_canonical_task()
# ===========================================================================

def test_Y1_build_canonical_task_basic(reset_runtime):
    task = build_canonical_task(goal="test", register=False)
    assert isinstance(task, CanonicalTask)
    assert task.intent.goal == "test"


def test_Y2_build_canonical_task_with_origin(reset_runtime):
    task = build_canonical_task(origin=TaskOrigin.API_REQUEST, register=False)
    assert task.intent.origin == TaskOrigin.API_REQUEST


def test_Y3_build_canonical_task_sets_tool(reset_runtime):
    task = build_canonical_task(tool="screenshot", register=False)
    assert task.execution.tool == "screenshot"


def test_Y4_build_canonical_task_targets(reset_runtime):
    task = build_canonical_task(selected_targets=["dev1", "dev2"], register=False)
    assert "dev1" in task.routing.selected_targets


# ===========================================================================
# Z) build_canonical_task() unique IDs
# ===========================================================================

def test_Z1_unique_task_ids(reset_runtime):
    t1 = build_canonical_task(register=False)
    t2 = build_canonical_task(register=False)
    assert t1.task_id != t2.task_id


def test_Z2_unique_trace_ids(reset_runtime):
    t1 = build_canonical_task(register=False)
    t2 = build_canonical_task(register=False)
    assert t1.trace_id != t2.trace_id


# ===========================================================================
# AA) build_canonical_task registers by default
# ===========================================================================

def test_AA1_registers_by_default(reset_runtime):
    task = build_canonical_task()
    rt = get_canonical_task_runtime()
    assert rt.get_by_task_id(task.task_id) is task


# ===========================================================================
# AB) build_canonical_task(register=False) skips registration
# ===========================================================================

def test_AB1_register_false_skips(reset_runtime):
    task = build_canonical_task(register=False)
    rt = get_canonical_task_runtime()
    assert rt.get_by_task_id(task.task_id) is None


# ===========================================================================
# AC) CanonicalTaskRuntime.register() idempotent upsert
# ===========================================================================

def test_AC1_register_idempotent(reset_runtime):
    rt = get_canonical_task_runtime()
    task = build_canonical_task(register=False)
    rt.register(task)
    rt.register(task)  # second call
    assert rt.get_by_task_id(task.task_id) is task


# ===========================================================================
# AD) CanonicalTaskRuntime.register() empty task_id raises ValueError
# ===========================================================================

def test_AD1_empty_task_id_raises(reset_runtime):
    rt = get_canonical_task_runtime()
    task = CanonicalTask(identity=TaskIdentity(task_id=""))
    with pytest.raises(ValueError):
        rt.register(task)


# ===========================================================================
# AE) get_by_task_id()
# ===========================================================================

def test_AE1_get_by_task_id_found(reset_runtime):
    rt = get_canonical_task_runtime()
    task = build_canonical_task()
    assert rt.get_by_task_id(task.task_id) is task


def test_AE2_get_by_task_id_not_found(reset_runtime):
    rt = get_canonical_task_runtime()
    assert rt.get_by_task_id("nonexistent") is None


# ===========================================================================
# AF) get_by_trace_id()
# ===========================================================================

def test_AF1_get_by_trace_id_found(reset_runtime):
    rt = get_canonical_task_runtime()
    task = build_canonical_task()
    results = rt.get_by_trace_id(task.trace_id)
    assert task in results


def test_AF2_get_by_trace_id_not_found(reset_runtime):
    rt = get_canonical_task_runtime()
    assert rt.get_by_trace_id("nonexistent_trace") == []


# ===========================================================================
# AG) update_lifecycle()
# ===========================================================================

def test_AG1_update_lifecycle_success(reset_runtime):
    rt = get_canonical_task_runtime()
    task = build_canonical_task()
    updated = rt.update_lifecycle(task.task_id, TaskLifecycle.RUNNING)
    assert updated is not None
    assert updated.lifecycle == TaskLifecycle.RUNNING


# ===========================================================================
# AH) update_lifecycle() unknown task_id
# ===========================================================================

def test_AH1_update_lifecycle_unknown_returns_none(reset_runtime):
    rt = get_canonical_task_runtime()
    result = rt.update_lifecycle("ghost_task", TaskLifecycle.RUNNING)
    assert result is None


# ===========================================================================
# AI) get_observability_log()
# ===========================================================================

def test_AI1_observability_log_is_list(reset_runtime):
    rt = get_canonical_task_runtime()
    assert isinstance(rt.get_observability_log(), list)


def test_AI2_observability_log_contains_record(reset_runtime):
    rt = get_canonical_task_runtime()
    build_canonical_task()
    log = rt.get_observability_log()
    assert len(log) >= 1
    assert isinstance(log[0], CanonicalTaskRecord)


# ===========================================================================
# AJ) snapshot()
# ===========================================================================

def test_AJ1_snapshot_structure(reset_runtime):
    rt = get_canonical_task_runtime()
    build_canonical_task()
    snap = rt.snapshot()
    assert snap.total_tasks >= 1
    assert isinstance(snap.tasks_by_lifecycle, dict)
    assert isinstance(snap.tasks_by_origin, dict)
    assert isinstance(snap.recent_records, list)


def test_AJ2_snapshot_to_dict(reset_runtime):
    rt = get_canonical_task_runtime()
    snap = rt.snapshot()
    d = snap.to_dict()
    for k in ("total_tasks", "tasks_by_lifecycle", "tasks_by_origin", "recent_records", "snapshot_ts"):
        assert k in d


# ===========================================================================
# AK) get_canonical_task_runtime() singleton
# ===========================================================================

def test_AK1_singleton(reset_runtime):
    rt1 = get_canonical_task_runtime()
    rt2 = get_canonical_task_runtime()
    assert rt1 is rt2


# ===========================================================================
# AL) reset_canonical_task_runtime()
# ===========================================================================

def test_AL1_reset_changes_singleton(reset_runtime):
    rt1 = get_canonical_task_runtime()
    reset_canonical_task_runtime()
    rt2 = get_canonical_task_runtime()
    assert rt1 is not rt2


# ===========================================================================
# AM–AP) project_to_task_envelope()
# ===========================================================================

def test_AM1_project_has_task_id(reset_runtime):
    task = build_canonical_task()
    env = project_to_task_envelope(task)
    assert hasattr(env, "task_id")
    assert env.task_id == task.task_id


def test_AN1_project_has_trace_id(reset_runtime):
    task = build_canonical_task()
    env = project_to_task_envelope(task)
    assert hasattr(env, "trace_id")
    assert env.trace_id == task.trace_id


def test_AO1_project_tool_name_from_execution_tool(reset_runtime):
    task = build_canonical_task(tool="screenshot", register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "tool_name")
    assert env.tool_name == "screenshot"


def test_AP1_project_targets_mapped(reset_runtime):
    task = build_canonical_task(selected_targets=["dev1"], register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "targets")
    assert "dev1" in env.targets


# ===========================================================================
# AQ–AT) apply_result_envelope()
# ===========================================================================

def test_AQ1_apply_result_success_lifecycle(reset_runtime):
    task = build_canonical_task()
    task = apply_result_envelope(task, {"success": True})
    assert task.lifecycle == TaskLifecycle.COMPLETED
    assert task.result.success is True


def test_AR1_apply_result_failure_lifecycle(reset_runtime):
    task = build_canonical_task()
    task = apply_result_envelope(task, {"success": False, "error_code": "ERR_123"})
    assert task.lifecycle == TaskLifecycle.FAILED
    assert task.result.success is False
    assert task.result.error_code == "ERR_123"


def test_AS1_apply_result_dict_input(reset_runtime):
    task = build_canonical_task()
    task = apply_result_envelope(task, {"success": True, "result": "done"})
    assert task.result.success is True


def test_AT1_apply_result_none_success_no_lifecycle_change(reset_runtime):
    task = build_canonical_task()
    initial_lc = task.lifecycle
    task = apply_result_envelope(task, {"success": None})
    assert task.lifecycle == initial_lc


# ===========================================================================
# AU) CanonicalTaskRecord
# ===========================================================================

def test_AU1_record_to_dict_keys():
    rec = CanonicalTaskRecord(task_id="t1", trace_id="tr1")
    d = rec.to_dict()
    for k in ("record_id", "task_id", "trace_id", "lifecycle", "origin", "tool", "targets", "ts"):
        assert k in d


# ===========================================================================
# AV) CanonicalTaskSnapshot
# ===========================================================================

def test_AV1_snapshot_to_dict_keys():
    snap = CanonicalTaskSnapshot()
    d = snap.to_dict()
    for k in ("total_tasks", "tasks_by_lifecycle", "tasks_by_origin", "recent_records", "snapshot_ts"):
        assert k in d


# ===========================================================================
# AW) __all__ completeness
# ===========================================================================

def test_AW1_all_exports_importable():
    for name in _mod.__all__:
        assert hasattr(_mod, name), f"{name} missing from module"


# ===========================================================================
# AX) allocation truth substrate
# ===========================================================================

def test_AX1_allocation_truth_contains_transition_history(reset_runtime):
    rt = get_canonical_task_runtime()
    task = build_canonical_task(
        selected_targets=["android-01"],
        route_preference="cross_device",
        transport_preference="websocket",
    )
    rt.update_lifecycle(task.task_id, TaskLifecycle.RUNNING)
    rt.update_lifecycle(task.task_id, TaskLifecycle.COMPLETED)
    records = rt.list_allocation_records(limit=8)
    assert records
    rec = records[0]
    assert rec.selected_executor == "android-01"
    assert rec.accepted_allocation == "accepted"
    assert rec.canonical_closed is True
    assert isinstance(rec.allocation_history, list) and rec.allocation_history


def test_AX2_allocation_truth_persists_and_recovers(tmp_path, monkeypatch):
    state_path = tmp_path / "allocation_state.json"
    monkeypatch.setenv("GALAXY_TASK_ALLOCATION_STATE_PATH", str(state_path))
    reset_canonical_task_runtime()
    rt = get_canonical_task_runtime()
    task = build_canonical_task(
        task_id="persist-task",
        selected_targets=["android-02"],
        route_preference="cross_device",
    )
    rt.update_lifecycle(task.task_id, TaskLifecycle.COMPLETED)
    assert state_path.exists()
    reset_canonical_task_runtime()
    rt2 = get_canonical_task_runtime()
    records = [r for r in rt2.list_allocation_records(limit=16) if r.task_id == "persist-task"]
    assert len(records) == 1
    assert records[0].execution_location == "android-02"
    assert TASK_ALLOCATION_TRUTH_AUTHORITY.startswith("CANONICAL_TASK_ALLOCATION_TRUTH")
