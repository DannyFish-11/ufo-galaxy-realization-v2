#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_graph_lifecycle_state_machine.py
=============================================

PR-C: Graph Lifecycle State Machine tests.

Test groups
-----------
  A)  New GraphNodeState enum values present and correct
  B)  transition() accepted for each new state
  C)  transition() for ADMITTED / PLANNED / ROUTED don't create extra edges
  D)  transition() for PARTIAL_RESULT sets result_at timestamp
  E)  transition() for CANCELLED sets completed_at + result_edge
  F)  transition() for DEGRADED sets completed_at + result_edge
  G)  transition() for REPLAYED accepted (no extra edge)
  H)  snapshot() nodes_by_state includes all new state keys
  I)  snapshot() to_dict includes convergence_authority
  J)  register_canonical_task() — basic CanonicalTask-like object
  K)  register_canonical_task() lifecycle mapping
  L)  register_canonical_task() idempotent (same task_id)
  M)  register_canonical_task() missing task_id auto-generates id
  N)  project_workflow_to_graph status_map handles new states
  O)  GRAPH_RUNTIME_CONVERGENCE_AUTHORITY exported and correct
  P)  snapshot() total_retry_records / total_fallback_records fields
  Q)  Full lifecycle walk: admitted → planned → routed → dispatch → running → completed
  R)  Cancelled lifecycle walk: admitted → running → cancelled (gets result edge)
  S)  Degraded lifecycle walk: admitted → running → degraded (gets result edge)
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from core.task_graph_runtime import (
    GRAPH_RUNTIME_CONVERGENCE_AUTHORITY,
    TASK_GRAPH_RUNTIME_AUTHORITY,
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeState,
    GraphRuntimeSnapshot,
    TaskGraphRuntime,
    WorkflowContributorKind,
    envelope_to_graph_node,
    get_task_graph_runtime,
    project_workflow_to_graph,
    reset_task_graph_runtime,
)
import core.task_graph_runtime as _mod


# ===========================================================================
# Helpers
# ===========================================================================


def _fresh() -> TaskGraphRuntime:
    reset_task_graph_runtime()
    return get_task_graph_runtime()


def _add_node(rt: TaskGraphRuntime, task_id: str) -> GraphNode:
    node = GraphNode(task_id=task_id)
    return rt.register_node(node)


def _make_canonical_task(
    task_id: str = "ct_001",
    lifecycle: str = "created",
    tool_name: str = "test_tool",
    device_id: str = "dev_01",
    trace_id: str = "trace_ct",
    session_id: str = "sess_ct",
) -> Any:
    intent = SimpleNamespace(tool_name=tool_name)
    routing = SimpleNamespace(selected_device_id=device_id)
    lc = SimpleNamespace(value=lifecycle)
    return SimpleNamespace(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        lifecycle=lc,
        intent=intent,
        routing=routing,
    )


# ===========================================================================
# A) New GraphNodeState values present
# ===========================================================================


def test_A01_admitted_state_value() -> None:
    assert GraphNodeState.ADMITTED.value == "admitted"


def test_A02_planned_state_value() -> None:
    assert GraphNodeState.PLANNED.value == "planned"


def test_A03_routed_state_value() -> None:
    assert GraphNodeState.ROUTED.value == "routed"


def test_A04_partial_result_state_value() -> None:
    assert GraphNodeState.PARTIAL_RESULT.value == "partial_result"


def test_A05_cancelled_state_value() -> None:
    assert GraphNodeState.CANCELLED.value == "cancelled"


def test_A06_degraded_state_value() -> None:
    assert GraphNodeState.DEGRADED.value == "degraded"


def test_A07_replayed_state_value() -> None:
    assert GraphNodeState.REPLAYED.value == "replayed"


def test_A08_all_new_states_in_enum() -> None:
    values = {s.value for s in GraphNodeState}
    for expected in ("admitted", "planned", "routed", "partial_result",
                     "cancelled", "degraded", "replayed"):
        assert expected in values


def test_A09_original_states_preserved() -> None:
    for expected in ("queued", "dispatch", "running", "result", "completed", "failed"):
        assert expected in {s.value for s in GraphNodeState}


# ===========================================================================
# B) transition() accepted for each new state
# ===========================================================================


def test_B01_transition_to_admitted() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.ADMITTED)
    assert node is not None
    assert node.state == GraphNodeState.ADMITTED


def test_B02_transition_to_planned() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.PLANNED)
    assert node.state == GraphNodeState.PLANNED


def test_B03_transition_to_routed() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.ROUTED)
    assert node.state == GraphNodeState.ROUTED


def test_B04_transition_to_partial_result() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.PARTIAL_RESULT)
    assert node.state == GraphNodeState.PARTIAL_RESULT


def test_B05_transition_to_cancelled() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.CANCELLED)
    assert node.state == GraphNodeState.CANCELLED


def test_B06_transition_to_degraded() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.DEGRADED)
    assert node.state == GraphNodeState.DEGRADED


def test_B07_transition_to_replayed() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    node = rt.transition("task_1", GraphNodeState.REPLAYED)
    assert node.state == GraphNodeState.REPLAYED


# ===========================================================================
# C) ADMITTED / PLANNED / ROUTED don't create extra edges
# ===========================================================================


def test_C01_admitted_creates_no_extra_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.ADMITTED)
    # No dispatch or result edges should exist
    assert len(rt.all_edges()) == 0


def test_C02_planned_creates_no_extra_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.PLANNED)
    assert len(rt.all_edges()) == 0


def test_C03_routed_creates_no_extra_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.ROUTED)
    assert len(rt.all_edges()) == 0


def test_C04_replayed_creates_no_extra_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.REPLAYED)
    assert len(rt.all_edges()) == 0


# ===========================================================================
# D) PARTIAL_RESULT sets result_at
# ===========================================================================


def test_D01_partial_result_sets_result_at() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    before = time.time()
    rt.transition("task_1", GraphNodeState.PARTIAL_RESULT)
    node = rt.get_node_by_task_id("task_1")
    assert node.result_at is not None
    assert node.result_at >= before


def test_D02_partial_result_does_not_set_completed_at() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.PARTIAL_RESULT)
    node = rt.get_node_by_task_id("task_1")
    assert node.completed_at is None


# ===========================================================================
# E) CANCELLED sets completed_at + result_edge
# ===========================================================================


def test_E01_cancelled_sets_completed_at() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    before = time.time()
    rt.transition("task_1", GraphNodeState.CANCELLED, reason="user_cancel")
    node = rt.get_node_by_task_id("task_1")
    assert node.completed_at is not None
    assert node.completed_at >= before


def test_E02_cancelled_creates_result_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.CANCELLED)
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) == 1


# ===========================================================================
# F) DEGRADED sets completed_at + result_edge
# ===========================================================================


def test_F01_degraded_sets_completed_at() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    before = time.time()
    rt.transition("task_1", GraphNodeState.DEGRADED)
    node = rt.get_node_by_task_id("task_1")
    assert node.completed_at is not None
    assert node.completed_at >= before


def test_F02_degraded_creates_result_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.DEGRADED)
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) == 1


# ===========================================================================
# G) REPLAYED doesn't create extra edge
# ===========================================================================


def test_G01_replayed_creates_no_result_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.REPLAYED)
    assert len(rt.all_edges()) == 0


# ===========================================================================
# H) snapshot() nodes_by_state includes all new state keys
# ===========================================================================


def test_H01_snapshot_nodes_by_state_has_admitted_key() -> None:
    rt = _fresh()
    snap = rt.snapshot()
    assert "admitted" in snap.nodes_by_state


def test_H02_snapshot_nodes_by_state_has_all_new_states() -> None:
    rt = _fresh()
    snap = rt.snapshot()
    for state in ("admitted", "planned", "routed", "partial_result",
                  "cancelled", "degraded", "replayed"):
        assert state in snap.nodes_by_state


def test_H03_snapshot_counts_admitted_nodes() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    _add_node(rt, "task_2")
    rt.transition("task_1", GraphNodeState.ADMITTED)
    rt.transition("task_2", GraphNodeState.ADMITTED)
    snap = rt.snapshot()
    assert snap.nodes_by_state["admitted"] == 2


def test_H04_snapshot_counts_cancelled_nodes() -> None:
    rt = _fresh()
    _add_node(rt, "task_1")
    rt.transition("task_1", GraphNodeState.CANCELLED)
    snap = rt.snapshot()
    assert snap.nodes_by_state["cancelled"] == 1


# ===========================================================================
# I) snapshot() convergence_authority field
# ===========================================================================


def test_I01_snapshot_has_convergence_authority_field() -> None:
    rt = _fresh()
    snap = rt.snapshot()
    assert snap.convergence_authority == GRAPH_RUNTIME_CONVERGENCE_AUTHORITY


def test_I02_snapshot_to_dict_has_convergence_authority() -> None:
    rt = _fresh()
    d = rt.snapshot().to_dict()
    assert "convergence_authority" in d
    assert d["convergence_authority"] == GRAPH_RUNTIME_CONVERGENCE_AUTHORITY


# ===========================================================================
# J) register_canonical_task() basic
# ===========================================================================


def test_J01_register_canonical_task_returns_graph_node() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001")
    node = rt.register_canonical_task(ct)
    assert isinstance(node, GraphNode)


def test_J02_register_canonical_task_task_id() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001")
    node = rt.register_canonical_task(ct)
    assert node.task_id == "ct_001"


def test_J03_register_canonical_task_trace_id() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001", trace_id="trace_xyz")
    node = rt.register_canonical_task(ct)
    assert node.trace_id == "trace_xyz"


def test_J04_register_canonical_task_tool_name_from_intent() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001", tool_name="my_tool")
    node = rt.register_canonical_task(ct)
    assert node.tool_name == "my_tool"


def test_J05_register_canonical_task_device_id_from_routing() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001", device_id="device_99")
    node = rt.register_canonical_task(ct)
    assert node.device_id == "device_99"


def test_J06_register_canonical_task_registers_in_runtime() -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="ct_001")
    rt.register_canonical_task(ct)
    assert rt.get_node_by_task_id("ct_001") is not None


# ===========================================================================
# K) register_canonical_task() lifecycle mapping
# ===========================================================================


def test_K01_lifecycle_created_maps_to_queued() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k01", lifecycle="created")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.QUEUED


def test_K02_lifecycle_admitted_maps_to_admitted() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k02", lifecycle="admitted")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.ADMITTED


def test_K03_lifecycle_planned_maps_to_planned() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k03", lifecycle="planned")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.PLANNED


def test_K04_lifecycle_routed_maps_to_routed() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k04", lifecycle="routed")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.ROUTED


def test_K05_lifecycle_dispatched_maps_to_dispatch() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k05", lifecycle="dispatched")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.DISPATCH


def test_K06_lifecycle_running_maps_to_running() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k06", lifecycle="running")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.RUNNING


def test_K07_lifecycle_completed_maps_to_completed() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k07", lifecycle="completed")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.COMPLETED


def test_K08_lifecycle_failed_maps_to_failed() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k08", lifecycle="failed")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.FAILED


def test_K09_lifecycle_cancelled_maps_to_cancelled() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k09", lifecycle="cancelled")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.CANCELLED


def test_K10_lifecycle_degraded_maps_to_degraded() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_k10", lifecycle="degraded")
    node = rt.register_canonical_task(ct)
    assert node.state == GraphNodeState.DEGRADED


# ===========================================================================
# L) register_canonical_task() idempotent
# ===========================================================================


def test_L01_register_canonical_task_idempotent() -> None:
    rt = _fresh()
    ct = _make_canonical_task("ct_001")
    node1 = rt.register_canonical_task(ct)
    node2 = rt.register_canonical_task(ct)
    assert node1.node_id == node2.node_id
    assert len(rt.all_nodes()) == 1


# ===========================================================================
# M) register_canonical_task() missing task_id auto-generates
# ===========================================================================


def test_M01_register_canonical_task_no_task_id_auto_generates(caplog) -> None:
    rt = _fresh()
    ct = _make_canonical_task(task_id="")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        node = rt.register_canonical_task(ct)
    assert node.task_id.startswith("ctask_")
    assert len(rt.all_nodes()) == 1


# ===========================================================================
# N) project_workflow_to_graph new state mappings
# ===========================================================================


def test_N01_project_workflow_admitted_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "admitted"}}, rt)
    node = rt.get_node_by_task_id("n1")
    assert node.state == GraphNodeState.ADMITTED


def test_N02_project_workflow_planned_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "planned"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.PLANNED


def test_N03_project_workflow_routed_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "routed"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.ROUTED


def test_N04_project_workflow_partial_result_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "partial_result"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.PARTIAL_RESULT


def test_N05_project_workflow_degraded_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "degraded"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.DEGRADED


def test_N06_project_workflow_cancelled_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "cancelled"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.CANCELLED


def test_N07_project_workflow_replayed_maps() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "replayed"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.REPLAYED


def test_N08_project_workflow_dispatched_maps_to_dispatch() -> None:
    rt = _fresh()
    project_workflow_to_graph({"node_statuses": {"n1": "dispatched"}}, rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.DISPATCH


# ===========================================================================
# O) GRAPH_RUNTIME_CONVERGENCE_AUTHORITY exported
# ===========================================================================


def test_O01_convergence_authority_exported_in_all() -> None:
    assert "GRAPH_RUNTIME_CONVERGENCE_AUTHORITY" in _mod.__all__


def test_O02_convergence_authority_value() -> None:
    assert GRAPH_RUNTIME_CONVERGENCE_AUTHORITY == "GRAPH_RUNTIME_CONVERGENCE_V1"


# ===========================================================================
# P) snapshot() retry/fallback counts
# ===========================================================================


def test_P01_snapshot_total_retry_records_zero_initially() -> None:
    rt = _fresh()
    snap = rt.snapshot()
    assert snap.total_retry_records == 0


def test_P02_snapshot_total_fallback_records_zero_initially() -> None:
    rt = _fresh()
    snap = rt.snapshot()
    assert snap.total_fallback_records == 0


def test_P03_snapshot_total_retry_records_after_register() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rt.register_retry("task_a", "task_b")
    snap = rt.snapshot()
    assert snap.total_retry_records == 1


def test_P04_snapshot_to_dict_has_all_pr_c_fields() -> None:
    rt = _fresh()
    d = rt.snapshot().to_dict()
    assert "total_retry_records" in d
    assert "total_fallback_records" in d
    assert "total_fanout_records" in d
    assert "convergence_authority" in d


# ===========================================================================
# Q) Full lifecycle walk (admitted → ... → completed)
# ===========================================================================


def test_Q01_full_lifecycle_walk_admitted_to_completed() -> None:
    rt = _fresh()
    _add_node(rt, "task_walk")
    for state in (
        GraphNodeState.ADMITTED,
        GraphNodeState.PLANNED,
        GraphNodeState.ROUTED,
        GraphNodeState.DISPATCH,
        GraphNodeState.RUNNING,
        GraphNodeState.RESULT,
        GraphNodeState.COMPLETED,
    ):
        rt.transition("task_walk", state)
    node = rt.get_node_by_task_id("task_walk")
    assert node.state == GraphNodeState.COMPLETED
    assert node.completed_at is not None


def test_Q02_full_lifecycle_records_are_emitted() -> None:
    rt = _fresh()
    _add_node(rt, "task_walk")
    states = [
        GraphNodeState.ADMITTED,
        GraphNodeState.PLANNED,
        GraphNodeState.ROUTED,
        GraphNodeState.DISPATCH,
        GraphNodeState.RUNNING,
        GraphNodeState.COMPLETED,
    ]
    for state in states:
        rt.transition("task_walk", state)
    # +1 for initial registration record
    assert len(rt.get_observability_log()) >= len(states) + 1


# ===========================================================================
# R) Cancelled lifecycle walk
# ===========================================================================


def test_R01_cancelled_walk_gets_result_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_cancel")
    for state in (
        GraphNodeState.ADMITTED,
        GraphNodeState.RUNNING,
        GraphNodeState.CANCELLED,
    ):
        rt.transition("task_cancel", state)
    node = rt.get_node_by_task_id("task_cancel")
    assert node.state == GraphNodeState.CANCELLED
    assert node.completed_at is not None
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) == 1


# ===========================================================================
# S) Degraded lifecycle walk
# ===========================================================================


def test_S01_degraded_walk_gets_result_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_degrade")
    for state in (
        GraphNodeState.ADMITTED,
        GraphNodeState.RUNNING,
        GraphNodeState.DEGRADED,
    ):
        rt.transition("task_degrade", state)
    node = rt.get_node_by_task_id("task_degrade")
    assert node.state == GraphNodeState.DEGRADED
    assert node.completed_at is not None
    result_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RESULT]
    assert len(result_edges) == 1
