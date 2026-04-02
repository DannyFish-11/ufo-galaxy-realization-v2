#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_multi_target_graph_edges.py
========================================

PR-C: Multi-target fanout / fanin edge tests.

Test groups
-----------
  A)  register_fanout() creates fanout_edges from parent to each child
  B)  register_fanout() returns a FanoutRecord with direction='fanout'
  C)  register_fanout() handles absent parent node gracefully
  D)  register_fanout() handles absent child nodes gracefully
  E)  register_fanin() creates fanin_edges from each child to aggregator
  F)  register_fanin() returns a FanoutRecord with direction='fanin'
  G)  register_fanin() handles absent aggregator gracefully
  H)  get_fanout_children() returns correct child task_ids
  I)  get_fanin_parents() returns correct child task_ids
  J)  get_fanout_children() empty for unknown parent
  K)  get_fanin_parents() empty for unknown aggregator
  L)  FanoutRecord.to_dict() serialisation (fanout)
  M)  FanoutRecord.to_dict() serialisation (fanin)
  N)  GraphEdgeKind.FANOUT and FANIN exported
  O)  FanoutRecord in __all__
  P)  get_fanout_log() ring-buffer accumulates fanout + fanin records
  Q)  snapshot() includes total_fanout_records count
  R)  Full fanout + fanin round-trip: parent → 3 children → aggregator
"""

from __future__ import annotations

import pytest

from core.task_graph_runtime import (
    FanoutRecord,
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeState,
    GraphRuntimeSnapshot,
    TaskGraphRuntime,
    WorkflowContributorKind,
    get_task_graph_runtime,
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
    node = GraphNode(task_id=task_id, trace_id="trace_fanout_test")
    return rt.register_node(node)


# ===========================================================================
# A) register_fanout() creates fanout_edges
# ===========================================================================


def test_A01_register_fanout_creates_correct_edge_count() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    for i in range(3):
        _add_node(rt, f"child_{i}")
    rt.register_fanout("parent", ["child_0", "child_1", "child_2"])
    fanout_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT]
    assert len(fanout_edges) == 3


def test_A02_fanout_edge_source_is_parent_node_id() -> None:
    rt = _fresh()
    parent = _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rt.register_fanout("parent", ["child_0"])
    fanout_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT)
    assert fanout_edge.source_node_id == parent.node_id


def test_A03_fanout_edge_target_is_child_node_id() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    child = _add_node(rt, "child_0")
    rt.register_fanout("parent", ["child_0"])
    fanout_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT)
    assert fanout_edge.target_node_id == child.node_id


def test_A04_fanout_edge_metadata_contains_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rt.register_fanout("parent", ["child_0"])
    fanout_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT)
    assert fanout_edge.metadata.get("parent_task_id") == "parent"
    assert fanout_edge.metadata.get("child_task_id") == "child_0"


def test_A05_register_fanout_empty_children_no_edges() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    rt.register_fanout("parent", [])
    fanout_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT]
    assert len(fanout_edges) == 0


# ===========================================================================
# B) register_fanout() returns FanoutRecord with direction='fanout'
# ===========================================================================


def test_B01_register_fanout_returns_fanout_record() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rec = rt.register_fanout("parent", ["child_0"])
    assert isinstance(rec, FanoutRecord)


def test_B02_fanout_record_direction_is_fanout() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rec = rt.register_fanout("parent", ["child_0"])
    assert rec.direction == "fanout"


def test_B03_fanout_record_parent_task_id() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rec = rt.register_fanout("parent", ["child_0"])
    assert rec.parent_task_id == "parent"


def test_B04_fanout_record_child_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    _add_node(rt, "child_1")
    rec = rt.register_fanout("parent", ["child_0", "child_1"])
    assert set(rec.child_task_ids) == {"child_0", "child_1"}


def test_B05_fanout_record_edge_ids_count_matches_children() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    for i in range(4):
        _add_node(rt, f"child_{i}")
    rec = rt.register_fanout("parent", [f"child_{i}" for i in range(4)])
    assert len(rec.edge_ids) == 4


# ===========================================================================
# C) register_fanout() handles absent parent gracefully
# ===========================================================================


def test_C01_fanout_absent_parent_still_creates_edges(caplog) -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        rec = rt.register_fanout("missing_parent", ["child_0"])
    fanout_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT]
    assert len(fanout_edges) == 1


# ===========================================================================
# D) register_fanout() handles absent child nodes gracefully
# ===========================================================================


def test_D01_fanout_absent_children_still_creates_edges() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    # children are not registered
    rec = rt.register_fanout("parent", ["missing_child_0", "missing_child_1"])
    fanout_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT]
    assert len(fanout_edges) == 2


# ===========================================================================
# E) register_fanin() creates fanin_edges
# ===========================================================================


def test_E01_register_fanin_creates_correct_edge_count() -> None:
    rt = _fresh()
    for i in range(3):
        _add_node(rt, f"child_{i}")
    _add_node(rt, "aggregator")
    rt.register_fanin(["child_0", "child_1", "child_2"], "aggregator")
    fanin_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN]
    assert len(fanin_edges) == 3


def test_E02_fanin_edge_source_is_child_node_id() -> None:
    rt = _fresh()
    child = _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rt.register_fanin(["child_0"], "aggregator")
    fanin_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN)
    assert fanin_edge.source_node_id == child.node_id


def test_E03_fanin_edge_target_is_aggregator_node_id() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    agg = _add_node(rt, "aggregator")
    rt.register_fanin(["child_0"], "aggregator")
    fanin_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN)
    assert fanin_edge.target_node_id == agg.node_id


def test_E04_fanin_edge_metadata_contains_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rt.register_fanin(["child_0"], "aggregator")
    fanin_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN)
    assert fanin_edge.metadata.get("aggregator_task_id") == "aggregator"
    assert fanin_edge.metadata.get("child_task_id") == "child_0"


# ===========================================================================
# F) register_fanin() returns FanoutRecord with direction='fanin'
# ===========================================================================


def test_F01_register_fanin_returns_fanout_record() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rec = rt.register_fanin(["child_0"], "aggregator")
    assert isinstance(rec, FanoutRecord)


def test_F02_fanin_record_direction_is_fanin() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rec = rt.register_fanin(["child_0"], "aggregator")
    assert rec.direction == "fanin"


def test_F03_fanin_record_parent_task_id_is_aggregator() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rec = rt.register_fanin(["child_0"], "aggregator")
    assert rec.parent_task_id == "aggregator"


def test_F04_fanin_record_child_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "child_1")
    _add_node(rt, "aggregator")
    rec = rt.register_fanin(["child_0", "child_1"], "aggregator")
    assert set(rec.child_task_ids) == {"child_0", "child_1"}


# ===========================================================================
# G) register_fanin() handles absent aggregator gracefully
# ===========================================================================


def test_G01_fanin_absent_aggregator_still_creates_edges(caplog) -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        rec = rt.register_fanin(["child_0"], "missing_agg")
    fanin_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN]
    assert len(fanin_edges) == 1


# ===========================================================================
# H) get_fanout_children()
# ===========================================================================


def test_H01_get_fanout_children_returns_children() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    for i in range(3):
        _add_node(rt, f"child_{i}")
    rt.register_fanout("parent", ["child_0", "child_1", "child_2"])
    children = rt.get_fanout_children("parent")
    assert set(children) == {"child_0", "child_1", "child_2"}


def test_H02_get_fanout_children_multiple_fanout_calls() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    for i in range(4):
        _add_node(rt, f"child_{i}")
    rt.register_fanout("parent", ["child_0", "child_1"])
    rt.register_fanout("parent", ["child_2", "child_3"])
    children = rt.get_fanout_children("parent")
    assert set(children) == {"child_0", "child_1", "child_2", "child_3"}


# ===========================================================================
# I) get_fanin_parents()
# ===========================================================================


def test_I01_get_fanin_parents_returns_children() -> None:
    rt = _fresh()
    for i in range(3):
        _add_node(rt, f"child_{i}")
    _add_node(rt, "aggregator")
    rt.register_fanin(["child_0", "child_1", "child_2"], "aggregator")
    parents = rt.get_fanin_parents("aggregator")
    assert set(parents) == {"child_0", "child_1", "child_2"}


# ===========================================================================
# J) get_fanout_children() empty for unknown
# ===========================================================================


def test_J01_get_fanout_children_empty_for_unknown() -> None:
    rt = _fresh()
    assert rt.get_fanout_children("nonexistent") == []


# ===========================================================================
# K) get_fanin_parents() empty for unknown
# ===========================================================================


def test_K01_get_fanin_parents_empty_for_unknown() -> None:
    rt = _fresh()
    assert rt.get_fanin_parents("nonexistent") == []


# ===========================================================================
# L) FanoutRecord.to_dict() (fanout)
# ===========================================================================


def test_L01_fanout_record_to_dict_keys() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rec = rt.register_fanout("parent", ["child_0"])
    d = rec.to_dict()
    assert "record_id" in d
    assert "parent_task_id" in d
    assert "child_task_ids" in d
    assert "edge_ids" in d
    assert "direction" in d
    assert "ts" in d


def test_L02_fanout_record_to_dict_direction() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rec = rt.register_fanout("parent", ["child_0"])
    assert rec.to_dict()["direction"] == "fanout"


# ===========================================================================
# M) FanoutRecord.to_dict() (fanin)
# ===========================================================================


def test_M01_fanin_record_to_dict_direction() -> None:
    rt = _fresh()
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rec = rt.register_fanin(["child_0"], "aggregator")
    assert rec.to_dict()["direction"] == "fanin"


# ===========================================================================
# N) GraphEdgeKind.FANOUT and FANIN exported
# ===========================================================================


def test_N01_fanout_edge_kind_value() -> None:
    assert _mod.GraphEdgeKind.FANOUT.value == "fanout_edge"


def test_N02_fanin_edge_kind_value() -> None:
    assert _mod.GraphEdgeKind.FANIN.value == "fanin_edge"


# ===========================================================================
# O) FanoutRecord in __all__
# ===========================================================================


def test_O01_fanout_record_in_all() -> None:
    assert "FanoutRecord" in _mod.__all__


# ===========================================================================
# P) get_fanout_log() ring-buffer
# ===========================================================================


def test_P01_fanout_log_accumulates_fanout_and_fanin() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rt.register_fanout("parent", ["child_0"])
    rt.register_fanin(["child_0"], "aggregator")
    log = rt.get_fanout_log()
    assert len(log) == 2
    directions = [r.direction for r in log]
    assert "fanout" in directions
    assert "fanin" in directions


# ===========================================================================
# Q) snapshot() total_fanout_records count
# ===========================================================================


def test_Q01_snapshot_total_fanout_records() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    _add_node(rt, "child_1")
    rt.register_fanout("parent", ["child_0", "child_1"])
    snap = rt.snapshot()
    assert snap.total_fanout_records == 1


def test_Q02_snapshot_total_fanout_records_includes_fanin() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    _add_node(rt, "aggregator")
    rt.register_fanout("parent", ["child_0"])
    rt.register_fanin(["child_0"], "aggregator")
    snap = rt.snapshot()
    assert snap.total_fanout_records == 2


def test_Q03_snapshot_to_dict_contains_fanout_count() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    _add_node(rt, "child_0")
    rt.register_fanout("parent", ["child_0"])
    d = rt.snapshot().to_dict()
    assert "total_fanout_records" in d
    assert d["total_fanout_records"] == 1


# ===========================================================================
# R) Full fanout + fanin round-trip
# ===========================================================================


def test_R01_full_fanout_fanin_round_trip() -> None:
    """parent → fanout → 3 children → fanin → aggregator."""
    rt = _fresh()
    _add_node(rt, "parent")
    children = [f"child_{i}" for i in range(3)]
    for cid in children:
        _add_node(rt, cid)
    _add_node(rt, "aggregator")

    rt.register_fanout("parent", children)
    rt.register_fanin(children, "aggregator")

    fanout_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANOUT]
    fanin_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FANIN]
    assert len(fanout_edges) == 3
    assert len(fanin_edges) == 3

    assert set(rt.get_fanout_children("parent")) == set(children)
    assert set(rt.get_fanin_parents("aggregator")) == set(children)


def test_R02_snapshot_after_round_trip_counts() -> None:
    rt = _fresh()
    _add_node(rt, "parent")
    for i in range(2):
        _add_node(rt, f"child_{i}")
    _add_node(rt, "agg")
    rt.register_fanout("parent", ["child_0", "child_1"])
    rt.register_fanin(["child_0", "child_1"], "agg")

    snap = rt.snapshot()
    assert snap.total_fanout_records == 2
    fanout_edges = [e for e in snap.edges if e.get("kind") == "fanout_edge"]
    fanin_edges = [e for e in snap.edges if e.get("kind") == "fanin_edge"]
    assert len(fanout_edges) == 2
    assert len(fanin_edges) == 2
