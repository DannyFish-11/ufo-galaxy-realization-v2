#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_workflow_projection.py
===================================

PR-6: Task Graph Runtime — workflow → graph projection tests.

Validates that legacy orchestrator execution records can be projected onto
the task graph runtime via the projection adapter without code removal.

Test groups
-----------
  A)  project_workflow_to_graph() with empty node_statuses
  B)  project_workflow_to_graph() with single node status
  C)  project_workflow_to_graph() maps legacy NodeStatus values correctly
  D)  project_workflow_to_graph() uses trace_id / session_id from record
  E)  project_workflow_to_graph() uses contributor from record
  F)  project_workflow_to_graph() unknown contributor defaults to UNKNOWN
  G)  project_workflow_to_graph() returns WorkflowProjectionRecord
  H)  project_workflow_to_graph() projection record lists registered node_ids
  I)  TaskGraphRuntime.project_workflow() registers all provided nodes
  J)  TaskGraphRuntime.project_workflow() registers all provided edges
  K)  TaskGraphRuntime.project_workflow() is idempotent for same nodes
  L)  TaskGraphRuntime.project_workflow() returns WorkflowProjectionRecord
  M)  TaskGraphRuntime.project_workflow() appends to projection log
  N)  Multiple projections from different contributors coexist
  O)  GALAXY_ORCHESTRATOR_GRAPH_CONTRIBUTOR sentinel importable
  P)  UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR sentinel importable
  Q)  project_workflow nodes with terminal states reflected in snapshot
  R)  project_workflow with dispatch nodes creates correct count
  S)  WorkflowContributorKind covers all expected contributor names
  T)  envelope_to_graph_node maps targets list to device_id
  U)  envelope_to_graph_node device_id override respected
  V)  result_envelope_to_node_update success path
  W)  result_envelope_to_node_update failure path
  X)  project_workflow_to_graph handles missing node_statuses key
  Y)  project_workflow_to_graph handles unknown status strings gracefully
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core.task_graph_runtime import (
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeState,
    TaskGraphRuntime,
    WorkflowContributorKind,
    WorkflowProjectionRecord,
    envelope_to_graph_node,
    get_task_graph_runtime,
    project_workflow_to_graph,
    reset_task_graph_runtime,
    result_envelope_to_node_update,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _fresh() -> TaskGraphRuntime:
    reset_task_graph_runtime()
    return get_task_graph_runtime()


def _workflow_record(
    trace_id: str = "tr1",
    session_id: str = "s1",
    graph_id: str = "g1",
    contributor: str = "task_graph_engine",
    node_statuses: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return {
        "trace_id": trace_id,
        "session_id": session_id,
        "graph_id": graph_id,
        "contributor": contributor,
        "node_statuses": node_statuses or {},
    }


# ===========================================================================
# A) Empty node_statuses
# ===========================================================================


def test_A01_empty_node_statuses_returns_projection() -> None:
    rt = _fresh()
    rec = _workflow_record(node_statuses={})
    proj = project_workflow_to_graph(rec, rt)
    assert isinstance(proj, WorkflowProjectionRecord)


def test_A02_empty_node_statuses_zero_nodes() -> None:
    rt = _fresh()
    rec = _workflow_record(node_statuses={})
    proj = project_workflow_to_graph(rec, rt)
    assert len(proj.node_ids_registered) == 0


# ===========================================================================
# B) Single node status
# ===========================================================================


def test_B01_single_node_registered() -> None:
    rt = _fresh()
    rec = _workflow_record(node_statuses={"task_001": "done"})
    proj = project_workflow_to_graph(rec, rt)
    assert len(proj.node_ids_registered) == 1


def test_B02_node_retrievable_after_projection() -> None:
    rt = _fresh()
    rec = _workflow_record(node_statuses={"task_xyz": "running"})
    project_workflow_to_graph(rec, rt)
    found = rt.get_node_by_task_id("task_xyz")
    assert found is not None


# ===========================================================================
# C) Legacy NodeStatus value mapping
# ===========================================================================


def test_C01_pending_maps_to_queued() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n1": "pending"}), rt)
    assert rt.get_node_by_task_id("n1").state == GraphNodeState.QUEUED


def test_C02_running_maps_to_running() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n2": "running"}), rt)
    assert rt.get_node_by_task_id("n2").state == GraphNodeState.RUNNING


def test_C03_done_maps_to_completed() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n3": "done"}), rt)
    assert rt.get_node_by_task_id("n3").state == GraphNodeState.COMPLETED


def test_C04_failed_maps_to_failed() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n4": "failed"}), rt)
    assert rt.get_node_by_task_id("n4").state == GraphNodeState.FAILED


def test_C05_skipped_maps_to_failed() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n5": "skipped"}), rt)
    assert rt.get_node_by_task_id("n5").state == GraphNodeState.FAILED


def test_C06_cancelled_maps_to_cancelled() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n6": "cancelled"}), rt)
    assert rt.get_node_by_task_id("n6").state == GraphNodeState.CANCELLED


def test_C07_completed_maps_to_completed() -> None:
    rt = _fresh()
    project_workflow_to_graph(_workflow_record(node_statuses={"n7": "completed"}), rt)
    assert rt.get_node_by_task_id("n7").state == GraphNodeState.COMPLETED


# ===========================================================================
# D) trace_id / session_id propagation
# ===========================================================================


def test_D01_trace_id_propagated_to_nodes() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(trace_id="trace_abc", node_statuses={"tnode": "done"}), rt
    )
    node = rt.get_node_by_task_id("tnode")
    assert node.trace_id == "trace_abc"


def test_D02_session_id_propagated_to_nodes() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(session_id="sess_99", node_statuses={"snode": "done"}), rt
    )
    node = rt.get_node_by_task_id("snode")
    assert node.session_id == "sess_99"


# ===========================================================================
# E) Contributor from record
# ===========================================================================


def test_E01_contributor_task_graph_engine() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(contributor="task_graph_engine", node_statuses={"cn1": "done"}), rt
    )
    node = rt.get_node_by_task_id("cn1")
    assert node.contributor == WorkflowContributorKind.TASK_GRAPH_ENGINE


def test_E02_contributor_galaxy_orchestrator() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(contributor="galaxy_orchestrator", node_statuses={"cn2": "done"}), rt
    )
    node = rt.get_node_by_task_id("cn2")
    assert node.contributor == WorkflowContributorKind.GALAXY_ORCHESTRATOR


# ===========================================================================
# F) Unknown contributor defaults to UNKNOWN
# ===========================================================================


def test_F01_unknown_contributor_defaults() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(contributor="some_future_engine", node_statuses={"un1": "done"}), rt
    )
    node = rt.get_node_by_task_id("un1")
    assert node.contributor == WorkflowContributorKind.UNKNOWN


# ===========================================================================
# G) Returns WorkflowProjectionRecord
# ===========================================================================


def test_G01_returns_projection_record_type() -> None:
    rt = _fresh()
    proj = project_workflow_to_graph(_workflow_record(node_statuses={"x": "done"}), rt)
    assert isinstance(proj, WorkflowProjectionRecord)


# ===========================================================================
# H) node_ids_registered in projection record
# ===========================================================================


def test_H01_node_ids_in_projection() -> None:
    rt = _fresh()
    proj = project_workflow_to_graph(
        _workflow_record(node_statuses={"h1": "done", "h2": "running"}), rt
    )
    assert len(proj.node_ids_registered) == 2


# ===========================================================================
# I) project_workflow registers all nodes
# ===========================================================================


def test_I01_all_nodes_registered() -> None:
    rt = _fresh()
    nodes = [
        GraphNode(task_id="pw1", state=GraphNodeState.QUEUED),
        GraphNode(task_id="pw2", state=GraphNodeState.RUNNING),
    ]
    rt.project_workflow(contributor=WorkflowContributorKind.SCHEDULER, nodes=nodes)
    assert rt.get_node_by_task_id("pw1") is not None
    assert rt.get_node_by_task_id("pw2") is not None


# ===========================================================================
# J) project_workflow registers provided edges
# ===========================================================================


def test_J01_edges_registered() -> None:
    rt = _fresh()
    n1 = GraphNode(task_id="je1")
    n2 = GraphNode(task_id="je2")
    rt.register_node(n1)
    rt.register_node(n2)
    edge = GraphEdge(kind=GraphEdgeKind.DEPENDENCY, source_node_id=n1.node_id, target_node_id=n2.node_id)
    rt.project_workflow(
        contributor=WorkflowContributorKind.E2E_ORCHESTRATOR,
        nodes=[n1, n2],
        edges=[edge],
    )
    assert len(rt.all_edges()) >= 1


# ===========================================================================
# K) project_workflow idempotent for same nodes
# ===========================================================================


def test_K01_double_projection_idempotent() -> None:
    rt = _fresh()
    nodes = [GraphNode(task_id="idem1")]
    rt.project_workflow(contributor=WorkflowContributorKind.SCHEDULER, nodes=nodes)
    rt.project_workflow(contributor=WorkflowContributorKind.SCHEDULER, nodes=nodes)
    all_nodes = rt.all_nodes()
    task_ids = [n.task_id for n in all_nodes]
    assert task_ids.count("idem1") == 1


# ===========================================================================
# L) project_workflow returns WorkflowProjectionRecord
# ===========================================================================


def test_L01_project_workflow_returns_projection_record() -> None:
    rt = _fresh()
    proj = rt.project_workflow(
        contributor=WorkflowContributorKind.COMMAND_ROUTER,
        nodes=[GraphNode(task_id="lr1")],
    )
    assert isinstance(proj, WorkflowProjectionRecord)


# ===========================================================================
# M) project_workflow appends to projection log
# ===========================================================================


def test_M01_projection_log_grows() -> None:
    rt = _fresh()
    before = len(rt.get_projection_log())
    rt.project_workflow(
        contributor=WorkflowContributorKind.OPENCLAWD,
        nodes=[GraphNode(task_id="ml1")],
    )
    assert len(rt.get_projection_log()) == before + 1


# ===========================================================================
# N) Multiple contributors coexist
# ===========================================================================


def test_N01_multiple_contributors() -> None:
    rt = _fresh()
    rt.project_workflow(
        contributor=WorkflowContributorKind.GALAXY_ORCHESTRATOR,
        nodes=[GraphNode(task_id="mc1")],
    )
    rt.project_workflow(
        contributor=WorkflowContributorKind.UNIFIED_ORCHESTRATOR,
        nodes=[GraphNode(task_id="mc2")],
    )
    snap = rt.snapshot()
    assert snap.total_nodes == 2


# ===========================================================================
# O) GALAXY_ORCHESTRATOR_GRAPH_CONTRIBUTOR sentinel
# ===========================================================================


def test_O01_galaxy_orchestrator_graph_contributor_importable() -> None:
    """Verify the sentinel is present in the galaxy_orchestrator source file."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "galaxy_gateway", "orchestrator", "galaxy_orchestrator.py",
    )
    with open(path) as f:
        source = f.read()
    assert "GALAXY_ORCHESTRATOR_GRAPH_CONTRIBUTOR" in source


def test_O02_galaxy_orchestrator_graph_contributor_value() -> None:
    """Verify the sentinel value contains the expected substring."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "galaxy_gateway", "orchestrator", "galaxy_orchestrator.py",
    )
    with open(path) as f:
        source = f.read()
    assert '"GALAXY_ORCHESTRATOR' in source or "'GALAXY_ORCHESTRATOR" in source


# ===========================================================================
# P) UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR sentinel
# ===========================================================================


def test_P01_unified_orchestrator_graph_contributor_importable() -> None:
    """Verify the sentinel is present in the unified_orchestrator source file."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "fusion", "unified_orchestrator.py",
    )
    with open(path) as f:
        source = f.read()
    assert "UNIFIED_ORCHESTRATOR_GRAPH_CONTRIBUTOR" in source


def test_P02_unified_orchestrator_graph_contributor_value() -> None:
    """Verify the sentinel value contains the expected substring."""
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..",
        "fusion", "unified_orchestrator.py",
    )
    with open(path) as f:
        source = f.read()
    assert '"UNIFIED_ORCHESTRATOR' in source or "'UNIFIED_ORCHESTRATOR" in source


# ===========================================================================
# Q) Terminal state nodes reflected in snapshot
# ===========================================================================


def test_Q01_terminal_nodes_in_snapshot() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(node_statuses={"q1": "done", "q2": "failed", "q3": "running"}), rt
    )
    snap = rt.snapshot()
    assert snap.nodes_by_state.get("completed", 0) >= 1
    assert snap.nodes_by_state.get("failed", 0) >= 1
    assert snap.nodes_by_state.get("running", 0) >= 1


# ===========================================================================
# R) Multiple nodes total count
# ===========================================================================


def test_R01_multiple_nodes_total() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(node_statuses={f"n{i}": "done" for i in range(5)}), rt
    )
    snap = rt.snapshot()
    assert snap.total_nodes == 5


# ===========================================================================
# S) WorkflowContributorKind covers expected names
# ===========================================================================


def test_S01_contributor_kinds_include_expected() -> None:
    expected = {
        "galaxy_orchestrator", "unified_orchestrator", "e2e_orchestrator",
        "task_graph_engine", "openclawd", "scheduler", "command_router", "unknown",
    }
    actual = {c.value for c in WorkflowContributorKind}
    assert expected.issubset(actual)


# ===========================================================================
# T) envelope_to_graph_node maps targets to device_id
# ===========================================================================


def test_T01_targets_mapped_to_device_id() -> None:
    env = SimpleNamespace(
        task_id="tg1", trace_id="tr", session_id="s", tool_name="t",
        targets=["device_phone"],
    )
    node = envelope_to_graph_node(env)
    assert node.device_id == "device_phone"


def test_T02_empty_targets_gives_empty_device_id() -> None:
    env = SimpleNamespace(
        task_id="tg2", trace_id="tr", session_id="s", tool_name="t",
        targets=[],
    )
    node = envelope_to_graph_node(env)
    assert node.device_id == ""


# ===========================================================================
# U) device_id override
# ===========================================================================


def test_U01_device_id_override_wins() -> None:
    env = SimpleNamespace(
        task_id="ov1", trace_id="tr", session_id="s", tool_name="t",
        targets=["device_phone"],
    )
    node = envelope_to_graph_node(env, device_id="override_device")
    assert node.device_id == "override_device"


# ===========================================================================
# V) result_envelope_to_node_update success
# ===========================================================================


def test_V01_success_result_sets_completed() -> None:
    node = GraphNode(task_id="rv1")
    re = SimpleNamespace(task_id="rv1", success=True, result={"ok": 1}, error="")
    updated = result_envelope_to_node_update(re, node)
    assert updated.state == GraphNodeState.COMPLETED


def test_V02_success_result_summary_populated() -> None:
    node = GraphNode(task_id="rv2")
    re = SimpleNamespace(task_id="rv2", success=True, result={"k": "v"}, error="")
    updated = result_envelope_to_node_update(re, node)
    assert updated.result_summary != ""


# ===========================================================================
# W) result_envelope_to_node_update failure
# ===========================================================================


def test_W01_failure_result_sets_failed() -> None:
    node = GraphNode(task_id="rw1")
    re = SimpleNamespace(task_id="rw1", success=False, result=None, error="boom")
    updated = result_envelope_to_node_update(re, node)
    assert updated.state == GraphNodeState.FAILED


def test_W02_error_populated() -> None:
    node = GraphNode(task_id="rw2")
    re = SimpleNamespace(task_id="rw2", success=False, result=None, error="conn_refused")
    updated = result_envelope_to_node_update(re, node)
    assert "conn_refused" in updated.error


# ===========================================================================
# X) Missing node_statuses key
# ===========================================================================


def test_X01_missing_node_statuses_handled() -> None:
    rt = _fresh()
    rec: Dict[str, Any] = {"trace_id": "tr", "session_id": "s"}  # no node_statuses key
    proj = project_workflow_to_graph(rec, rt)
    assert isinstance(proj, WorkflowProjectionRecord)
    assert len(proj.node_ids_registered) == 0


# ===========================================================================
# Y) Unknown status strings handled
# ===========================================================================


def test_Y01_unknown_status_defaults_to_queued() -> None:
    rt = _fresh()
    project_workflow_to_graph(
        _workflow_record(node_statuses={"unknown_node": "zap_mode"}), rt
    )
    node = rt.get_node_by_task_id("unknown_node")
    assert node is not None
    assert node.state == GraphNodeState.QUEUED  # default fallback
