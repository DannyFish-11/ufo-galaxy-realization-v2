#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_task_graph_runtime.py
==================================

PR-6: Task Graph Runtime — authority sentinel, data model, and runtime tests.

Test groups
-----------
  A)  Authority sentinels importable and correct values
  B)  GraphNodeState enum values
  C)  GraphEdgeKind enum values
  D)  WorkflowContributorKind enum values
  E)  GraphNode construction and defaults
  F)  GraphNode.to_dict() serialisation
  G)  GraphEdge construction and defaults
  H)  GraphEdge.to_dict() serialisation
  I)  GraphRuntimeRecord construction and to_dict()
  J)  GraphRuntimeSnapshot construction and to_dict()
  K)  WorkflowProjectionRecord construction and to_dict()
  L)  TaskGraphRuntime.register_node() — happy path
  M)  TaskGraphRuntime.register_node() — idempotent (same task_id)
  N)  TaskGraphRuntime.register_node() — empty task_id raises ValueError
  O)  TaskGraphRuntime.get_node_by_task_id() — found and not-found
  P)  TaskGraphRuntime.get_node_by_node_id() — found and not-found
  Q)  TaskGraphRuntime.transition() — happy path queued → dispatch
  R)  TaskGraphRuntime.transition() — dispatch creates dispatch_edge
  S)  TaskGraphRuntime.transition() — running state timestamp
  T)  TaskGraphRuntime.transition() — completed creates result_edge
  U)  TaskGraphRuntime.transition() — failed creates result_edge
  V)  TaskGraphRuntime.transition() — unknown task_id returns None
  W)  TaskGraphRuntime.add_dependency_edge()
  X)  TaskGraphRuntime.register_edge() — idempotent
  Y)  TaskGraphRuntime.register_envelope() — basic
  Z)  TaskGraphRuntime.register_envelope() — depends_on wires dependency edges
  AA) TaskGraphRuntime.complete_from_result_envelope() — success path
  AB) TaskGraphRuntime.complete_from_result_envelope() — failure path
  AC) TaskGraphRuntime.complete_from_result_envelope() — unknown task_id
  AD) TaskGraphRuntime.snapshot() structure and field counts
  AE) TaskGraphRuntime.snapshot() nodes_by_state aggregation
  AF) TaskGraphRuntime.get_observability_log() ring-buffer
  AG) TaskGraphRuntime.get_projection_log() ring-buffer
  AH) get_task_graph_runtime() returns singleton
  AI) reset_task_graph_runtime() resets singleton
  AJ) All public names appear in __all__
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any, Dict

import pytest

from core.task_graph_runtime import (
    TASK_GRAPH_RUNTIME_AUTHORITY,
    TASK_GRAPH_RUNTIME_LAYER_POSITION,
    TASK_GRAPH_NODE_CONTRACT_VERSION,
    WORKFLOW_GRAPH_PROJECTION_POLICY,
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeState,
    GraphRuntimeRecord,
    GraphRuntimeSnapshot,
    TaskGraphRuntime,
    WorkflowContributorKind,
    WorkflowProjectionRecord,
    envelope_to_graph_node,
    get_task_graph_runtime,
    reset_task_graph_runtime,
    result_envelope_to_node_update,
)
import core.task_graph_runtime as _mod


# ===========================================================================
# Helpers
# ===========================================================================


def _make_envelope(
    task_id: str = "task_abc",
    trace_id: str = "trace_xyz",
    session_id: str = "sess_1",
    tool_name: str = "test_tool",
    targets: list | None = None,
) -> Any:
    return SimpleNamespace(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        tool_name=tool_name,
        targets=targets or [],
    )


def _make_result_envelope(
    task_id: str = "task_abc",
    success: bool = True,
    result: Any = {"ok": True},
    error: str = "",
) -> Any:
    return SimpleNamespace(
        task_id=task_id,
        success=success,
        result=result,
        error=error,
    )


def _fresh_runtime() -> TaskGraphRuntime:
    reset_task_graph_runtime()
    return get_task_graph_runtime()


# ===========================================================================
# A) Authority sentinels
# ===========================================================================


def test_A01_task_graph_runtime_authority_importable() -> None:
    assert isinstance(TASK_GRAPH_RUNTIME_AUTHORITY, str)


def test_A02_task_graph_runtime_authority_value() -> None:
    assert "TASK_GRAPH_RUNTIME" in TASK_GRAPH_RUNTIME_AUTHORITY


def test_A03_layer_position_is_6() -> None:
    assert TASK_GRAPH_RUNTIME_LAYER_POSITION == 6


def test_A04_node_contract_version() -> None:
    assert "GRAPH_NODE_CONTRACT" in TASK_GRAPH_NODE_CONTRACT_VERSION


def test_A05_workflow_projection_policy() -> None:
    assert "WORKFLOW" in WORKFLOW_GRAPH_PROJECTION_POLICY
    assert "PROJECTED" in WORKFLOW_GRAPH_PROJECTION_POLICY


# ===========================================================================
# B) GraphNodeState enum
# ===========================================================================


def test_B01_queued_value() -> None:
    assert GraphNodeState.QUEUED.value == "queued"


def test_B02_dispatch_value() -> None:
    assert GraphNodeState.DISPATCH.value == "dispatch"


def test_B03_running_value() -> None:
    assert GraphNodeState.RUNNING.value == "running"


def test_B04_result_value() -> None:
    assert GraphNodeState.RESULT.value == "result"


def test_B05_completed_value() -> None:
    assert GraphNodeState.COMPLETED.value == "completed"


def test_B06_failed_value() -> None:
    assert GraphNodeState.FAILED.value == "failed"


def test_B07_all_states_distinct() -> None:
    vals = [s.value for s in GraphNodeState]
    assert len(vals) == len(set(vals))


# ===========================================================================
# C) GraphEdgeKind enum
# ===========================================================================


def test_C01_dependency_value() -> None:
    assert GraphEdgeKind.DEPENDENCY.value == "dependency_edge"


def test_C02_dispatch_value() -> None:
    assert GraphEdgeKind.DISPATCH.value == "dispatch_edge"


def test_C03_result_value() -> None:
    assert GraphEdgeKind.RESULT.value == "result_edge"


def test_C04_all_kinds_distinct() -> None:
    vals = [k.value for k in GraphEdgeKind]
    assert len(vals) == len(set(vals))


# ===========================================================================
# D) WorkflowContributorKind enum
# ===========================================================================


def test_D01_galaxy_orchestrator_value() -> None:
    assert WorkflowContributorKind.GALAXY_ORCHESTRATOR.value == "galaxy_orchestrator"


def test_D02_unified_orchestrator_value() -> None:
    assert WorkflowContributorKind.UNIFIED_ORCHESTRATOR.value == "unified_orchestrator"


def test_D03_unknown_value() -> None:
    assert WorkflowContributorKind.UNKNOWN.value == "unknown"


def test_D04_all_contributors_distinct() -> None:
    vals = [c.value for c in WorkflowContributorKind]
    assert len(vals) == len(set(vals))


# ===========================================================================
# E) GraphNode construction
# ===========================================================================


def test_E01_default_state_is_queued() -> None:
    n = GraphNode(task_id="t1")
    assert n.state == GraphNodeState.QUEUED


def test_E02_node_id_auto_generated() -> None:
    n = GraphNode(task_id="t1")
    assert n.node_id.startswith("gn_")


def test_E03_fields_set() -> None:
    n = GraphNode(task_id="t1", trace_id="tr1", tool_name="foo", device_id="dev1")
    assert n.task_id == "t1"
    assert n.trace_id == "tr1"
    assert n.tool_name == "foo"
    assert n.device_id == "dev1"


def test_E04_depends_on_defaults_empty() -> None:
    n = GraphNode(task_id="t1")
    assert n.depends_on == []


def test_E05_queued_at_is_recent() -> None:
    before = time.time()
    n = GraphNode(task_id="t1")
    after = time.time()
    assert before <= n.queued_at <= after


# ===========================================================================
# F) GraphNode.to_dict()
# ===========================================================================


def test_F01_to_dict_has_required_keys() -> None:
    n = GraphNode(task_id="t1", trace_id="tr1", tool_name="foo")
    d = n.to_dict()
    for key in ("node_id", "task_id", "trace_id", "state", "contributor",
                "depends_on", "queued_at", "tool_name"):
        assert key in d, f"missing key: {key}"


def test_F02_to_dict_state_is_string() -> None:
    n = GraphNode(task_id="t1")
    assert n.to_dict()["state"] == "queued"


def test_F03_to_dict_contributor_is_string() -> None:
    n = GraphNode(task_id="t1", contributor=WorkflowContributorKind.SCHEDULER)
    assert n.to_dict()["contributor"] == "scheduler"


# ===========================================================================
# G) GraphEdge construction
# ===========================================================================


def test_G01_edge_id_auto_generated() -> None:
    e = GraphEdge()
    assert e.edge_id.startswith("ge_")


def test_G02_default_kind_is_dependency() -> None:
    e = GraphEdge()
    assert e.kind == GraphEdgeKind.DEPENDENCY


def test_G03_fields_set() -> None:
    e = GraphEdge(
        kind=GraphEdgeKind.DISPATCH,
        source_node_id="n1",
        target_node_id="n2",
        transport_path="direct_ws",
    )
    assert e.source_node_id == "n1"
    assert e.target_node_id == "n2"
    assert e.transport_path == "direct_ws"


# ===========================================================================
# H) GraphEdge.to_dict()
# ===========================================================================


def test_H01_to_dict_has_required_keys() -> None:
    e = GraphEdge(kind=GraphEdgeKind.RESULT, source_node_id="s", target_node_id="t")
    d = e.to_dict()
    for key in ("edge_id", "kind", "source_node_id", "target_node_id", "created_at"):
        assert key in d, f"missing key: {key}"


def test_H02_to_dict_kind_is_string() -> None:
    e = GraphEdge(kind=GraphEdgeKind.DISPATCH)
    assert e.to_dict()["kind"] == "dispatch_edge"


# ===========================================================================
# I) GraphRuntimeRecord
# ===========================================================================


def test_I01_record_fields() -> None:
    r = GraphRuntimeRecord(
        node_id="n1", task_id="t1", trace_id="tr1",
        previous_state="queued", new_state="running",
        transition_reason="test", contributor="scheduler",
    )
    d = r.to_dict()
    assert d["node_id"] == "n1"
    assert d["previous_state"] == "queued"
    assert d["new_state"] == "running"
    assert d["transition_reason"] == "test"


# ===========================================================================
# J) GraphRuntimeSnapshot
# ===========================================================================


def test_J01_snapshot_fields() -> None:
    snap = GraphRuntimeSnapshot(total_nodes=3, total_edges=2)
    d = snap.to_dict()
    assert d["total_nodes"] == 3
    assert d["total_edges"] == 2
    assert "authority" in d
    assert "TASK_GRAPH_RUNTIME" in d["authority"]


# ===========================================================================
# K) WorkflowProjectionRecord
# ===========================================================================


def test_K01_projection_record_fields() -> None:
    r = WorkflowProjectionRecord(
        contributor=WorkflowContributorKind.E2E_ORCHESTRATOR,
        trace_id="tr1",
        session_id="s1",
        node_ids_registered=["n1", "n2"],
        edge_ids_registered=["e1"],
    )
    d = r.to_dict()
    assert d["contributor"] == "e2e_orchestrator"
    assert d["trace_id"] == "tr1"
    assert d["node_ids_registered"] == ["n1", "n2"]
    assert d["edge_ids_registered"] == ["e1"]


# ===========================================================================
# L) TaskGraphRuntime.register_node() — happy path
# ===========================================================================


def test_L01_register_node_returns_node() -> None:
    rt = _fresh_runtime()
    node = GraphNode(task_id="t1")
    returned = rt.register_node(node)
    assert returned.task_id == "t1"


def test_L02_node_retrievable_by_task_id() -> None:
    rt = _fresh_runtime()
    node = GraphNode(task_id="t2")
    rt.register_node(node)
    assert rt.get_node_by_task_id("t2") is not None


def test_L03_node_retrievable_by_node_id() -> None:
    rt = _fresh_runtime()
    node = GraphNode(task_id="t3")
    rt.register_node(node)
    found = rt.get_node_by_node_id(node.node_id)
    assert found is not None and found.task_id == "t3"


# ===========================================================================
# M) Idempotent registration
# ===========================================================================


def test_M01_double_register_returns_first_node() -> None:
    rt = _fresh_runtime()
    n1 = GraphNode(task_id="tid_dup")
    n2 = GraphNode(task_id="tid_dup")
    r1 = rt.register_node(n1)
    r2 = rt.register_node(n2)
    assert r1.node_id == r2.node_id


# ===========================================================================
# N) Empty task_id raises ValueError
# ===========================================================================


def test_N01_empty_task_id_raises() -> None:
    rt = _fresh_runtime()
    with pytest.raises(ValueError):
        rt.register_node(GraphNode(task_id=""))


# ===========================================================================
# O) get_node_by_task_id
# ===========================================================================


def test_O01_missing_task_id_returns_none() -> None:
    rt = _fresh_runtime()
    assert rt.get_node_by_task_id("nonexistent") is None


def test_O02_existing_task_id_returns_node() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="found_me"))
    assert rt.get_node_by_task_id("found_me") is not None


# ===========================================================================
# P) get_node_by_node_id
# ===========================================================================


def test_P01_missing_node_id_returns_none() -> None:
    rt = _fresh_runtime()
    assert rt.get_node_by_node_id("gn_nonexistent") is None


# ===========================================================================
# Q) transition() — queued → dispatch
# ===========================================================================


def test_Q01_transition_to_dispatch() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tq1"))
    updated = rt.transition("tq1", GraphNodeState.DISPATCH)
    assert updated is not None
    assert updated.state == GraphNodeState.DISPATCH


def test_Q02_transition_sets_dispatch_at() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tq2"))
    before = time.time()
    rt.transition("tq2", GraphNodeState.DISPATCH)
    node = rt.get_node_by_task_id("tq2")
    assert node.dispatch_at is not None
    assert node.dispatch_at >= before


# ===========================================================================
# R) dispatch_edge created on DISPATCH transition
# ===========================================================================


def test_R01_dispatch_creates_edge() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tr1", device_id="dev1"))
    rt.transition("tr1", GraphNodeState.DISPATCH, transport_path="direct_ws")
    dispatch_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.DISPATCH]
    assert len(dispatch_edges) >= 1


def test_R02_dispatch_edge_transport_path() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tr2"))
    rt.transition("tr2", GraphNodeState.DISPATCH, transport_path="nats")
    dispatch_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.DISPATCH]
    assert any(e.transport_path == "nats" for e in dispatch_edges)


# ===========================================================================
# S) running state timestamp
# ===========================================================================


def test_S01_running_sets_running_at() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="ts1"))
    before = time.time()
    rt.transition("ts1", GraphNodeState.RUNNING)
    node = rt.get_node_by_task_id("ts1")
    assert node.running_at is not None and node.running_at >= before


# ===========================================================================
# T) completed creates result_edge
# ===========================================================================


def test_T01_completed_creates_result_edge() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tt1"))
    rt.transition("tt1", GraphNodeState.COMPLETED, result_summary="done")
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) >= 1


def test_T02_completed_sets_result_summary() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tt2"))
    rt.transition("tt2", GraphNodeState.COMPLETED, result_summary="all_ok")
    node = rt.get_node_by_task_id("tt2")
    assert node.result_summary == "all_ok"


# ===========================================================================
# U) failed creates result_edge
# ===========================================================================


def test_U01_failed_creates_result_edge() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tu1"))
    rt.transition("tu1", GraphNodeState.FAILED, error="boom")
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) >= 1


def test_U02_failed_sets_error() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="tu2"))
    rt.transition("tu2", GraphNodeState.FAILED, error="timeout")
    node = rt.get_node_by_task_id("tu2")
    assert node.error == "timeout"


# ===========================================================================
# V) transition — unknown task_id returns None
# ===========================================================================


def test_V01_transition_unknown_task_id_returns_none() -> None:
    rt = _fresh_runtime()
    result = rt.transition("no_such_task", GraphNodeState.RUNNING)
    assert result is None


# ===========================================================================
# W) add_dependency_edge
# ===========================================================================


def test_W01_dependency_edge_created() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="n_src", node_id="gn_src"))
    rt.register_node(GraphNode(task_id="n_tgt", node_id="gn_tgt"))
    edge = rt.add_dependency_edge("gn_src", "gn_tgt")
    assert edge.kind == GraphEdgeKind.DEPENDENCY
    assert edge.source_node_id == "gn_src"
    assert edge.target_node_id == "gn_tgt"


# ===========================================================================
# X) register_edge idempotent
# ===========================================================================


def test_X01_register_edge_idempotent() -> None:
    rt = _fresh_runtime()
    e = GraphEdge(edge_id="fixed_edge_id", kind=GraphEdgeKind.DEPENDENCY)
    r1 = rt.register_edge(e)
    r2 = rt.register_edge(e)
    assert r1.edge_id == r2.edge_id
    assert len([ed for ed in rt.all_edges() if ed.edge_id == "fixed_edge_id"]) == 1


# ===========================================================================
# Y) register_envelope
# ===========================================================================


def test_Y01_register_envelope_creates_node() -> None:
    rt = _fresh_runtime()
    env = _make_envelope(task_id="env_task_1", tool_name="search")
    node = rt.register_envelope(env)
    assert node.task_id == "env_task_1"
    assert node.tool_name == "search"


def test_Y02_register_envelope_idempotent() -> None:
    rt = _fresh_runtime()
    env = _make_envelope(task_id="env_dup")
    n1 = rt.register_envelope(env)
    n2 = rt.register_envelope(env)
    assert n1.node_id == n2.node_id


# ===========================================================================
# Z) register_envelope with depends_on
# ===========================================================================


def test_Z01_depends_on_creates_dependency_edges() -> None:
    rt = _fresh_runtime()
    env1 = _make_envelope(task_id="dep_parent")
    parent = rt.register_envelope(env1)

    env2 = _make_envelope(task_id="dep_child")
    rt.register_envelope(env2, depends_on=["dep_parent"])

    dep_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.DEPENDENCY]
    assert any(e.source_node_id == parent.node_id for e in dep_edges)


# ===========================================================================
# AA) complete_from_result_envelope — success
# ===========================================================================


def test_AA01_success_result_completes_node() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="res_ok"))
    re = _make_result_envelope(task_id="res_ok", success=True, result={"data": 42})
    node = rt.complete_from_result_envelope(re)
    assert node is not None
    assert node.state == GraphNodeState.COMPLETED


def test_AA02_result_summary_populated() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="res_ok2"))
    re = _make_result_envelope(task_id="res_ok2", result={"answer": "yes"})
    node = rt.complete_from_result_envelope(re)
    assert "answer" in node.result_summary or "yes" in node.result_summary


# ===========================================================================
# AB) complete_from_result_envelope — failure
# ===========================================================================


def test_AB01_failure_result_fails_node() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="res_fail"))
    re = _make_result_envelope(task_id="res_fail", success=False, error="network_error")
    node = rt.complete_from_result_envelope(re)
    assert node is not None
    assert node.state == GraphNodeState.FAILED


def test_AB02_error_populated_on_failure() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="res_fail2"))
    re = _make_result_envelope(task_id="res_fail2", success=False, error="timeout")
    node = rt.complete_from_result_envelope(re)
    assert "timeout" in node.error


# ===========================================================================
# AC) complete_from_result_envelope — unknown task_id
# ===========================================================================


def test_AC01_unknown_task_id_returns_none() -> None:
    rt = _fresh_runtime()
    re = _make_result_envelope(task_id="ghost_task")
    result = rt.complete_from_result_envelope(re)
    assert result is None


# ===========================================================================
# AD) snapshot() structure
# ===========================================================================


def test_AD01_snapshot_has_required_keys() -> None:
    rt = _fresh_runtime()
    snap = rt.snapshot()
    d = snap.to_dict()
    for key in ("snapshot_id", "ts", "total_nodes", "total_edges",
                "nodes_by_state", "nodes", "edges", "recent_records", "authority"):
        assert key in d, f"missing key: {key}"


def test_AD02_snapshot_total_nodes_matches() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="snap_n1"))
    rt.register_node(GraphNode(task_id="snap_n2"))
    snap = rt.snapshot()
    assert snap.total_nodes == 2


# ===========================================================================
# AE) snapshot nodes_by_state aggregation
# ===========================================================================


def test_AE01_nodes_by_state_counts() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="st1", state=GraphNodeState.QUEUED))
    rt.register_node(GraphNode(task_id="st2", state=GraphNodeState.QUEUED))
    rt.register_node(GraphNode(task_id="st3", state=GraphNodeState.RUNNING))
    snap = rt.snapshot()
    assert snap.nodes_by_state.get("queued", 0) == 2
    assert snap.nodes_by_state.get("running", 0) == 1


# ===========================================================================
# AF) observability ring buffer
# ===========================================================================


def test_AF01_observability_log_is_deque() -> None:
    rt = _fresh_runtime()
    log = rt.get_observability_log()
    from collections import deque
    assert isinstance(log, deque)


def test_AF02_transitions_append_to_log() -> None:
    rt = _fresh_runtime()
    rt.register_node(GraphNode(task_id="obs1"))
    initial_len = len(rt.get_observability_log())
    rt.transition("obs1", GraphNodeState.RUNNING)
    assert len(rt.get_observability_log()) > initial_len


def test_AF03_ring_buffer_max_256() -> None:
    rt = _fresh_runtime()
    log = rt.get_observability_log()
    assert log.maxlen == 256


# ===========================================================================
# AG) projection log ring buffer
# ===========================================================================


def test_AG01_projection_log_is_deque() -> None:
    rt = _fresh_runtime()
    plog = rt.get_projection_log()
    from collections import deque
    assert isinstance(plog, deque)


def test_AG02_projection_log_max_256() -> None:
    rt = _fresh_runtime()
    assert rt.get_projection_log().maxlen == 256


# ===========================================================================
# AH) get_task_graph_runtime singleton
# ===========================================================================


def test_AH01_singleton_returned() -> None:
    reset_task_graph_runtime()
    rt1 = get_task_graph_runtime()
    rt2 = get_task_graph_runtime()
    assert rt1 is rt2


# ===========================================================================
# AI) reset_task_graph_runtime
# ===========================================================================


def test_AI01_reset_gives_fresh_runtime() -> None:
    reset_task_graph_runtime()
    rt1 = get_task_graph_runtime()
    rt1.register_node(GraphNode(task_id="before_reset"))
    reset_task_graph_runtime()
    rt2 = get_task_graph_runtime()
    assert rt1 is not rt2
    assert rt2.get_node_by_task_id("before_reset") is None


# ===========================================================================
# AJ) __all__ completeness
# ===========================================================================


def test_AJ01_all_contains_authority_sentinels() -> None:
    for name in (
        "TASK_GRAPH_RUNTIME_AUTHORITY",
        "TASK_GRAPH_RUNTIME_LAYER_POSITION",
        "TASK_GRAPH_NODE_CONTRACT_VERSION",
        "WORKFLOW_GRAPH_PROJECTION_POLICY",
    ):
        assert name in _mod.__all__, f"{name} missing from __all__"


def test_AJ02_all_contains_enums() -> None:
    for name in ("GraphNodeState", "GraphEdgeKind", "WorkflowContributorKind"):
        assert name in _mod.__all__, f"{name} missing from __all__"


def test_AJ03_all_contains_dataclasses() -> None:
    for name in ("GraphNode", "GraphEdge", "GraphRuntimeRecord",
                 "GraphRuntimeSnapshot", "WorkflowProjectionRecord"):
        assert name in _mod.__all__, f"{name} missing from __all__"


def test_AJ04_all_contains_helpers() -> None:
    for name in ("envelope_to_graph_node", "result_envelope_to_node_update",
                 "project_workflow_to_graph", "get_task_graph_runtime",
                 "reset_task_graph_runtime"):
        assert name in _mod.__all__, f"{name} missing from __all__"
