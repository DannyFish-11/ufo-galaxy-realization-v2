#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_retry_fallback_edges.py
====================================

PR-C: Retry / Fallback Edge tests.

Test groups
-----------
  A)  register_retry() creates a retry_edge between two registered nodes
  B)  register_retry() creates a RetryRecord with correct fields
  C)  register_retry() warns but succeeds when nodes are absent
  D)  register_retry() ring-buffer (get_retry_log)
  E)  get_retry_lineage() returns records by original_task_id
  F)  get_retry_lineage() returns records by retry_task_id
  G)  get_retry_lineage() returns empty list for unknown task_id
  H)  register_fallback() creates a fallback_edge between two registered nodes
  I)  register_fallback() creates a FallbackRecord with correct fields
  J)  register_fallback() warns but succeeds when nodes are absent
  K)  register_fallback() ring-buffer (get_fallback_log)
  L)  get_fallback_lineage() returns records by primary_task_id
  M)  get_fallback_lineage() returns records by fallback_task_id
  N)  get_fallback_lineage() returns empty list for unknown task_id
  O)  RetryRecord.to_dict() serialisation
  P)  FallbackRecord.to_dict() serialisation
  Q)  GraphEdgeKind.RETRY and FALLBACK are exported in __all__
  R)  Multiple retry attempts accumulate separate records and edges
  S)  Retry after fallback: both records present for same original task
"""

from __future__ import annotations

import pytest

from core.task_graph_runtime import (
    GRAPH_RUNTIME_CONVERGENCE_AUTHORITY,
    FallbackRecord,
    GraphEdge,
    GraphEdgeKind,
    GraphNode,
    GraphNodeState,
    RetryRecord,
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
    node = GraphNode(task_id=task_id, trace_id="trace_test")
    return rt.register_node(node)


# ===========================================================================
# A) register_retry() creates a retry_edge
# ===========================================================================


def test_A01_register_retry_creates_retry_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_orig")
    _add_node(rt, "task_retry1")
    rt.register_retry("task_orig", "task_retry1", attempt_number=1, reason="transient_error")
    retry_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY]
    assert len(retry_edges) == 1


def test_A02_retry_edge_source_is_original_node_id() -> None:
    rt = _fresh()
    orig_node = _add_node(rt, "task_orig")
    _add_node(rt, "task_retry1")
    rt.register_retry("task_orig", "task_retry1")
    retry_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY)
    assert retry_edge.source_node_id == orig_node.node_id


def test_A03_retry_edge_target_is_retry_node_id() -> None:
    rt = _fresh()
    _add_node(rt, "task_orig")
    retry_node = _add_node(rt, "task_retry1")
    rt.register_retry("task_orig", "task_retry1")
    retry_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY)
    assert retry_edge.target_node_id == retry_node.node_id


def test_A04_retry_edge_metadata_contains_attempt_number() -> None:
    rt = _fresh()
    _add_node(rt, "task_orig")
    _add_node(rt, "task_retry2")
    rt.register_retry("task_orig", "task_retry2", attempt_number=2)
    retry_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY)
    assert retry_edge.metadata.get("attempt_number") == 2


# ===========================================================================
# B) register_retry() creates a RetryRecord
# ===========================================================================


def test_B01_register_retry_returns_retry_record() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b", attempt_number=1, reason="timeout")
    assert isinstance(rec, RetryRecord)


def test_B02_retry_record_has_correct_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b")
    assert rec.original_task_id == "task_a"
    assert rec.retry_task_id == "task_b"


def test_B03_retry_record_has_correct_attempt_number() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b", attempt_number=3)
    assert rec.attempt_number == 3


def test_B04_retry_record_edge_id_matches_created_edge() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b")
    retry_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY)
    assert rec.edge_id == retry_edge.edge_id


# ===========================================================================
# C) register_retry() warns but succeeds when nodes are absent
# ===========================================================================


def test_C01_register_retry_absent_original_still_creates_record(caplog) -> None:
    rt = _fresh()
    _add_node(rt, "task_b")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        rec = rt.register_retry("task_missing", "task_b")
    assert rec.original_task_id == "task_missing"


def test_C02_register_retry_absent_retry_still_creates_edge(caplog) -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        rt.register_retry("task_a", "task_missing")
    retry_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY]
    assert len(retry_edges) == 1


# ===========================================================================
# D) register_retry() ring-buffer
# ===========================================================================


def test_D01_get_retry_log_returns_deque() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rt.register_retry("task_a", "task_b")
    log = rt.get_retry_log()
    assert len(log) == 1


def test_D02_get_retry_log_accumulates_multiple_records() -> None:
    rt = _fresh()
    for i in range(5):
        _add_node(rt, f"task_orig_{i}")
        _add_node(rt, f"task_retry_{i}")
        rt.register_retry(f"task_orig_{i}", f"task_retry_{i}")
    assert len(rt.get_retry_log()) == 5


# ===========================================================================
# E) get_retry_lineage() by original_task_id
# ===========================================================================


def test_E01_get_retry_lineage_by_original() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    _add_node(rt, "retry1")
    rt.register_retry("orig", "retry1")
    lineage = rt.get_retry_lineage("orig")
    assert len(lineage) == 1
    assert lineage[0].original_task_id == "orig"


def test_E02_get_retry_lineage_multiple_retries() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    _add_node(rt, "retry1")
    _add_node(rt, "retry2")
    rt.register_retry("orig", "retry1", attempt_number=1)
    rt.register_retry("orig", "retry2", attempt_number=2)
    lineage = rt.get_retry_lineage("orig")
    assert len(lineage) == 2


# ===========================================================================
# F) get_retry_lineage() by retry_task_id
# ===========================================================================


def test_F01_get_retry_lineage_by_retry_id() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    _add_node(rt, "retry1")
    rt.register_retry("orig", "retry1")
    lineage = rt.get_retry_lineage("retry1")
    assert len(lineage) == 1
    assert lineage[0].retry_task_id == "retry1"


# ===========================================================================
# G) get_retry_lineage() empty for unknown
# ===========================================================================


def test_G01_get_retry_lineage_empty_for_unknown() -> None:
    rt = _fresh()
    assert rt.get_retry_lineage("nonexistent") == []


# ===========================================================================
# H) register_fallback() creates a fallback_edge
# ===========================================================================


def test_H01_register_fallback_creates_fallback_edge() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rt.register_fallback("primary", "fallback", reason="device_unavailable")
    fallback_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FALLBACK]
    assert len(fallback_edges) == 1


def test_H02_fallback_edge_source_is_primary_node_id() -> None:
    rt = _fresh()
    primary_node = _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rt.register_fallback("primary", "fallback")
    fb_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FALLBACK)
    assert fb_edge.source_node_id == primary_node.node_id


def test_H03_fallback_edge_target_is_fallback_node_id() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    fb_node = _add_node(rt, "fallback")
    rt.register_fallback("primary", "fallback")
    fb_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FALLBACK)
    assert fb_edge.target_node_id == fb_node.node_id


# ===========================================================================
# I) register_fallback() creates a FallbackRecord
# ===========================================================================


def test_I01_register_fallback_returns_fallback_record() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rec = rt.register_fallback("primary", "fallback", reason="timeout")
    assert isinstance(rec, FallbackRecord)


def test_I02_fallback_record_has_correct_task_ids() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rec = rt.register_fallback("primary", "fallback")
    assert rec.primary_task_id == "primary"
    assert rec.fallback_task_id == "fallback"


def test_I03_fallback_record_reason_propagated() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rec = rt.register_fallback("primary", "fallback", reason="capability_mismatch")
    assert rec.reason == "capability_mismatch"


def test_I04_fallback_record_edge_id_matches_created_edge() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rec = rt.register_fallback("primary", "fallback")
    fb_edge = next(e for e in rt.all_edges() if e.kind == GraphEdgeKind.FALLBACK)
    assert rec.edge_id == fb_edge.edge_id


# ===========================================================================
# J) register_fallback() warns when nodes absent
# ===========================================================================


def test_J01_register_fallback_absent_primary_still_creates_record(caplog) -> None:
    rt = _fresh()
    _add_node(rt, "fallback")
    import logging
    with caplog.at_level(logging.WARNING, logger="Galaxy.TaskGraphRuntime"):
        rec = rt.register_fallback("missing_primary", "fallback")
    assert rec.primary_task_id == "missing_primary"


# ===========================================================================
# K) register_fallback() ring-buffer
# ===========================================================================


def test_K01_get_fallback_log_accumulates() -> None:
    rt = _fresh()
    for i in range(3):
        _add_node(rt, f"p{i}")
        _add_node(rt, f"f{i}")
        rt.register_fallback(f"p{i}", f"f{i}")
    assert len(rt.get_fallback_log()) == 3


# ===========================================================================
# L) get_fallback_lineage() by primary_task_id
# ===========================================================================


def test_L01_get_fallback_lineage_by_primary() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rt.register_fallback("primary", "fallback")
    lineage = rt.get_fallback_lineage("primary")
    assert len(lineage) == 1


# ===========================================================================
# M) get_fallback_lineage() by fallback_task_id
# ===========================================================================


def test_M01_get_fallback_lineage_by_fallback_id() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rt.register_fallback("primary", "fallback")
    lineage = rt.get_fallback_lineage("fallback")
    assert len(lineage) == 1


# ===========================================================================
# N) get_fallback_lineage() empty for unknown
# ===========================================================================


def test_N01_get_fallback_lineage_empty_for_unknown() -> None:
    rt = _fresh()
    assert rt.get_fallback_lineage("nonexistent") == []


# ===========================================================================
# O) RetryRecord.to_dict() serialisation
# ===========================================================================


def test_O01_retry_record_to_dict_keys() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b", attempt_number=1, reason="flaky")
    d = rec.to_dict()
    assert "record_id" in d
    assert "original_task_id" in d
    assert "retry_task_id" in d
    assert "edge_id" in d
    assert "attempt_number" in d
    assert "reason" in d
    assert "ts" in d


def test_O02_retry_record_to_dict_values() -> None:
    rt = _fresh()
    _add_node(rt, "task_a")
    _add_node(rt, "task_b")
    rec = rt.register_retry("task_a", "task_b", attempt_number=2, reason="timeout")
    d = rec.to_dict()
    assert d["original_task_id"] == "task_a"
    assert d["retry_task_id"] == "task_b"
    assert d["attempt_number"] == 2
    assert d["reason"] == "timeout"


# ===========================================================================
# P) FallbackRecord.to_dict() serialisation
# ===========================================================================


def test_P01_fallback_record_to_dict_keys() -> None:
    rt = _fresh()
    _add_node(rt, "primary")
    _add_node(rt, "fallback")
    rec = rt.register_fallback("primary", "fallback", reason="route_failed")
    d = rec.to_dict()
    assert "record_id" in d
    assert "primary_task_id" in d
    assert "fallback_task_id" in d
    assert "edge_id" in d
    assert "reason" in d
    assert "ts" in d


# ===========================================================================
# Q) GraphEdgeKind.RETRY and FALLBACK are exported in __all__
# ===========================================================================


def test_Q01_graph_edge_kind_retry_in_module() -> None:
    assert hasattr(_mod.GraphEdgeKind, "RETRY")
    assert _mod.GraphEdgeKind.RETRY.value == "retry_edge"


def test_Q02_graph_edge_kind_fallback_in_module() -> None:
    assert hasattr(_mod.GraphEdgeKind, "FALLBACK")
    assert _mod.GraphEdgeKind.FALLBACK.value == "fallback_edge"


def test_Q03_retry_record_in_all() -> None:
    assert "RetryRecord" in _mod.__all__


def test_Q04_fallback_record_in_all() -> None:
    assert "FallbackRecord" in _mod.__all__


# ===========================================================================
# R) Multiple retry attempts accumulate separate records and edges
# ===========================================================================


def test_R01_three_retry_attempts_create_three_edges() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    _add_node(rt, "retry1")
    _add_node(rt, "retry2")
    _add_node(rt, "retry3")
    rt.register_retry("orig", "retry1", attempt_number=1)
    rt.register_retry("orig", "retry2", attempt_number=2)
    rt.register_retry("orig", "retry3", attempt_number=3)
    retry_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY]
    assert len(retry_edges) == 3


def test_R02_three_retry_attempts_create_three_records() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    for i in range(1, 4):
        _add_node(rt, f"retry{i}")
        rt.register_retry("orig", f"retry{i}", attempt_number=i)
    assert len(rt.get_retry_log()) == 3
    lineage = rt.get_retry_lineage("orig")
    assert len(lineage) == 3
    attempts = [r.attempt_number for r in lineage]
    assert sorted(attempts) == [1, 2, 3]


# ===========================================================================
# S) Retry after fallback: both records present for same original task
# ===========================================================================


def test_S01_retry_and_fallback_coexist_for_same_task() -> None:
    rt = _fresh()
    _add_node(rt, "orig")
    _add_node(rt, "retry1")
    _add_node(rt, "fallback1")
    rt.register_retry("orig", "retry1", attempt_number=1)
    rt.register_fallback("orig", "fallback1", reason="retry_exhausted")
    assert len(rt.get_retry_lineage("orig")) == 1
    assert len(rt.get_fallback_lineage("orig")) == 1
    retry_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.RETRY]
    fb_edges = [e for e in rt.all_edges() if e.kind == GraphEdgeKind.FALLBACK]
    assert len(retry_edges) == 1
    assert len(fb_edges) == 1
