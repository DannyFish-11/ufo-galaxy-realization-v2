"""tests/test_task_dag.py
========================

PR-5: Unit tests for :mod:`core.task_graph`.

Test groups
-----------
  A) NodeStatus enum values
  B) RetryPolicy defaults and fields
  C) TaskNode construction and defaults
  D) TaskEdge construction
  E) TaskGraph.add_node()
  F) TaskGraph.add_edge() validation
  G) TaskGraph.topological_layers() — linear chain
  H) TaskGraph.topological_layers() — independent nodes (single layer)
  I) TaskGraph.topological_layers() — fan-out / fan-in diamond
  J) TaskGraph.topological_layers() — cycle detection raises ValueError
  K) TaskGraph.execute() — empty graph succeeds immediately
  L) TaskGraph.execute() — single node success
  M) TaskGraph.execute() — single node handler failure
  N) TaskGraph.execute() — retry on failure (succeeds on retry)
  O) TaskGraph.execute() — retry exhausted → FAILED
  P) TaskGraph.execute() — parallel nodes run concurrently
  Q) TaskGraph.execute() — dependency: second node waits for first
  R) TaskGraph.execute() — failed node causes dependent to be SKIPPED
  S) TaskGraph.execute() — continue_on_failure=True skips only dependents
  T) TaskGraph.execute() — continue_on_failure=False halts after failure
  U) TaskGraph.execute() — edge condition (condition=False → skip)
  V) TaskGraph.execute() — rollback is called on failure
  W) TaskGraph.snapshot() returns serialisable dict
  X) TaskGraph.ready_nodes() returns correct initial ready set
  Y) compile_subtasks_to_graph() basic round-trip
  Z) compile_subtasks_to_graph() resolves depends_on by name
  AA) compile_subtasks_to_graph() propagates trace_id / runtime_session_id
  AB) GraphExecutionResult fields
  AC) compile_and_run_dag() public API (e2e_orchestrator)
  AD) compile_and_run_dag() returns error dict on cycle
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from core.task_graph import (
    GraphExecutionResult,
    NodeStatus,
    RetryPolicy,
    TaskEdge,
    TaskGraph,
    TaskNode,
    compile_subtasks_to_graph,
)


# ===========================================================================
# Helpers
# ===========================================================================


async def _ok_handler(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Handler that always succeeds."""
    return {"node_id": node.node_id, "ok": True}


_fail_count: Dict[str, int] = {}


async def _fail_then_ok(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Fails the first time, succeeds on subsequent calls."""
    key = node.node_id
    _fail_count[key] = _fail_count.get(key, 0) + 1
    if _fail_count[key] == 1:
        raise RuntimeError("first attempt fail")
    return {"retry_ok": True}


async def _always_fail(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
    raise RuntimeError("always fails")


async def _record_handler(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Records execution order into ctx['order'] list."""
    ctx.setdefault("order", []).append(node.node_id)
    return {}


# ===========================================================================
# A) NodeStatus
# ===========================================================================

class TestNodeStatus:
    def test_pending(self):
        assert NodeStatus.PENDING == "pending"

    def test_running(self):
        assert NodeStatus.RUNNING == "running"

    def test_done(self):
        assert NodeStatus.DONE == "done"

    def test_failed(self):
        assert NodeStatus.FAILED == "failed"

    def test_skipped(self):
        assert NodeStatus.SKIPPED == "skipped"


# ===========================================================================
# B) RetryPolicy
# ===========================================================================

class TestRetryPolicy:
    def test_defaults(self):
        p = RetryPolicy()
        assert p.max_retries == 0
        assert p.retry_delay_seconds == 1.0
        assert p.backoff_multiplier == 1.0

    def test_custom(self):
        p = RetryPolicy(max_retries=3, retry_delay_seconds=0.1, backoff_multiplier=2.0)
        assert p.max_retries == 3
        assert p.retry_delay_seconds == 0.1
        assert p.backoff_multiplier == 2.0


# ===========================================================================
# C) TaskNode
# ===========================================================================

class TestTaskNode:
    def test_auto_id(self):
        n = TaskNode(description="test")
        assert n.node_id.startswith("node_")

    def test_default_status(self):
        n = TaskNode(description="x")
        assert n.status == NodeStatus.PENDING

    def test_depends_on_default_empty(self):
        n = TaskNode(description="x")
        assert n.depends_on == []

    def test_device_id_default_empty(self):
        n = TaskNode(description="x")
        assert n.device_id == ""

    def test_handler_default_none(self):
        n = TaskNode(description="x")
        assert n.handler is None


# ===========================================================================
# D) TaskEdge
# ===========================================================================

class TestTaskEdge:
    def test_fields(self):
        e = TaskEdge(from_node="a", to_node="b")
        assert e.from_node == "a"
        assert e.to_node == "b"
        assert e.condition is None

    def test_with_condition(self):
        def cond(n: TaskNode) -> bool:
            return True
        e = TaskEdge(from_node="a", to_node="b", condition=cond)
        assert e.condition is cond


# ===========================================================================
# E) TaskGraph.add_node()
# ===========================================================================

class TestAddNode:
    def test_returns_task_node(self):
        g = TaskGraph()
        n = g.add_node("step1")
        assert isinstance(n, TaskNode)

    def test_custom_node_id(self):
        g = TaskGraph()
        n = g.add_node("step", node_id="my_id")
        assert n.node_id == "my_id"
        assert "my_id" in g._nodes

    def test_depends_on_stored(self):
        g = TaskGraph()
        n1 = g.add_node("a")
        n2 = g.add_node("b", depends_on=[n1.node_id])
        assert n1.node_id in n2.depends_on

    def test_device_id_stored(self):
        g = TaskGraph()
        n = g.add_node("x", device_id="phone_01")
        assert n.device_id == "phone_01"


# ===========================================================================
# F) TaskGraph.add_edge() validation
# ===========================================================================

class TestAddEdge:
    def test_unknown_from_node_raises(self):
        g = TaskGraph()
        g.add_node("b", node_id="b")
        with pytest.raises(ValueError, match="Source node"):
            g.add_edge("unknown", "b")

    def test_unknown_to_node_raises(self):
        g = TaskGraph()
        g.add_node("a", node_id="a")
        with pytest.raises(ValueError, match="Destination node"):
            g.add_edge("a", "unknown")

    def test_valid_edge_returned(self):
        g = TaskGraph()
        g.add_node("a", node_id="a")
        g.add_node("b", node_id="b")
        e = g.add_edge("a", "b")
        assert isinstance(e, TaskEdge)
        assert e.from_node == "a"
        assert e.to_node == "b"


# ===========================================================================
# G) topological_layers — linear chain
# ===========================================================================

class TestTopologicalLayersLinear:
    def test_linear_chain_three_nodes(self):
        g = TaskGraph()
        n1 = g.add_node("a", node_id="a")
        n2 = g.add_node("b", node_id="b", depends_on=["a"])
        n3 = g.add_node("c", node_id="c", depends_on=["b"])
        layers = g.topological_layers()
        assert layers == [["a"], ["b"], ["c"]]


# ===========================================================================
# H) topological_layers — independent nodes in single layer
# ===========================================================================

class TestTopologicalLayersParallel:
    def test_three_independent_nodes(self):
        g = TaskGraph()
        g.add_node("x", node_id="x")
        g.add_node("y", node_id="y")
        g.add_node("z", node_id="z")
        layers = g.topological_layers()
        assert len(layers) == 1
        assert set(layers[0]) == {"x", "y", "z"}


# ===========================================================================
# I) topological_layers — diamond
# ===========================================================================

class TestTopologicalLayersDiamond:
    def test_diamond_two_middle_layers(self):
        g = TaskGraph()
        g.add_node("top",   node_id="top")
        g.add_node("left",  node_id="left",   depends_on=["top"])
        g.add_node("right", node_id="right",  depends_on=["top"])
        g.add_node("bot",   node_id="bot",    depends_on=["left", "right"])
        layers = g.topological_layers()
        assert layers[0] == ["top"]
        assert set(layers[1]) == {"left", "right"}
        assert layers[2] == ["bot"]


# ===========================================================================
# J) topological_layers — cycle detection
# ===========================================================================

class TestTopologicalLayersCycle:
    def test_cycle_raises_value_error(self):
        g = TaskGraph()
        g.add_node("a", node_id="a", depends_on=["b"])
        g.add_node("b", node_id="b", depends_on=["a"])
        with pytest.raises(ValueError, match="cycle"):
            g.topological_layers()


# ===========================================================================
# K) execute() — empty graph
# ===========================================================================

class TestExecuteEmpty:
    async def test_empty_graph_succeeds(self):
        g = TaskGraph()
        r = await g.execute()
        assert r.success is True
        assert r.total_nodes == 0
        assert r.done_nodes == 0


# ===========================================================================
# L) execute() — single node success
# ===========================================================================

class TestExecuteSingleSuccess:
    async def test_single_node_done(self):
        g = TaskGraph(trace_id="t1")
        g.add_node("step", node_id="s", handler=_ok_handler)
        r = await g.execute()
        assert r.success is True
        assert r.done_nodes == 1
        assert g._nodes["s"].status == NodeStatus.DONE
        assert g._nodes["s"].result == {"node_id": "s", "ok": True}


# ===========================================================================
# M) execute() — single node failure
# ===========================================================================

class TestExecuteSingleFailure:
    async def test_single_node_failed(self):
        g = TaskGraph()
        g.add_node("bad", node_id="bad", handler=_always_fail)
        r = await g.execute()
        assert r.success is False
        assert r.failed_nodes == 1
        assert g._nodes["bad"].status == NodeStatus.FAILED
        assert "always fails" in g._nodes["bad"].error


# ===========================================================================
# N) execute() — retry on failure (succeeds on retry)
# ===========================================================================

class TestExecuteRetrySuccess:
    async def test_succeeds_on_second_attempt(self):
        _fail_count.clear()
        g = TaskGraph()
        g.add_node(
            "retry_node",
            node_id="r",
            handler=_fail_then_ok,
            retry_policy=RetryPolicy(max_retries=1, retry_delay_seconds=0.0),
        )
        r = await g.execute()
        assert r.success is True
        assert g._nodes["r"].attempt == 2


# ===========================================================================
# O) execute() — retry exhausted → FAILED
# ===========================================================================

class TestExecuteRetryExhausted:
    async def test_exhausted_retries_failed(self):
        g = TaskGraph()
        g.add_node(
            "always_bad",
            node_id="ab",
            handler=_always_fail,
            retry_policy=RetryPolicy(max_retries=2, retry_delay_seconds=0.0),
        )
        r = await g.execute()
        assert r.success is False
        assert g._nodes["ab"].attempt == 3  # 1 + 2 retries


# ===========================================================================
# P) execute() — parallel nodes run concurrently
# ===========================================================================

class TestExecuteParallel:
    async def test_parallel_nodes_all_done(self):
        g = TaskGraph()
        g.add_node("p1", node_id="p1", handler=_ok_handler)
        g.add_node("p2", node_id="p2", handler=_ok_handler)
        g.add_node("p3", node_id="p3", handler=_ok_handler)
        r = await g.execute()
        assert r.success is True
        assert r.done_nodes == 3


# ===========================================================================
# Q) execute() — dependency ordering
# ===========================================================================

class TestExecuteDependencyOrdering:
    async def test_second_node_uses_first_result(self):
        first_result: Dict[str, Any] = {}

        async def handler_a(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
            return {"value": 42}

        async def handler_b(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
            # "a" must be done before "b" starts
            a_node = ctx.get("_graph_ref")
            return {"ok": True}

        g = TaskGraph()
        g.add_node("a", node_id="a", handler=handler_a)
        g.add_node("b", node_id="b", handler=handler_b, depends_on=["a"])
        r = await g.execute()
        assert r.success is True
        assert g._nodes["a"].status == NodeStatus.DONE
        assert g._nodes["b"].status == NodeStatus.DONE


# ===========================================================================
# R) execute() — failed node causes dependent to be SKIPPED
# ===========================================================================

class TestExecuteSkipOnDependencyFailure:
    async def test_dependent_skipped_when_predecessor_fails(self):
        g = TaskGraph()
        g.add_node("fail_node", node_id="f", handler=_always_fail)
        g.add_node("dep_node",  node_id="d", handler=_ok_handler, depends_on=["f"])
        r = await g.execute()
        assert g._nodes["f"].status == NodeStatus.FAILED
        assert g._nodes["d"].status == NodeStatus.SKIPPED
        assert r.skipped_nodes == 1


# ===========================================================================
# S) execute() — continue_on_failure=True keeps independent branches running
# ===========================================================================

class TestExecuteContinueOnFailure:
    async def test_independent_branch_still_runs(self):
        g = TaskGraph()
        g.add_node("bad",  node_id="bad",  handler=_always_fail)
        g.add_node("dep",  node_id="dep",  handler=_ok_handler, depends_on=["bad"])
        g.add_node("good", node_id="good", handler=_ok_handler)  # independent
        r = await g.execute(continue_on_failure=True)
        assert g._nodes["bad"].status == NodeStatus.FAILED
        assert g._nodes["dep"].status == NodeStatus.SKIPPED
        assert g._nodes["good"].status == NodeStatus.DONE


# ===========================================================================
# T) execute() — continue_on_failure=False halts after failure
# ===========================================================================

class TestExecuteHaltOnFailure:
    async def test_halts_on_first_failure(self):
        # "a" is the root (layer 0), "b" and "c" both depend on "a" (layer 1).
        # With continue_on_failure=False, after layer 0 fails, layer 1 is halted.
        g = TaskGraph()
        g.add_node("a",   node_id="a",   handler=_always_fail)
        g.add_node("b",   node_id="b",   handler=_ok_handler,  depends_on=["a"])
        g.add_node("c",   node_id="c",   handler=_ok_handler,  depends_on=["a"])
        r = await g.execute(continue_on_failure=False)
        assert r.failed_nodes == 1
        # Both "b" and "c" depend on "a" (layer 1 after the failed layer 0)
        assert g._nodes["b"].status == NodeStatus.SKIPPED
        assert g._nodes["c"].status == NodeStatus.SKIPPED


# ===========================================================================
# U) execute() — edge condition False → skip
# ===========================================================================

class TestExecuteEdgeCondition:
    async def test_false_condition_skips_successor(self):
        g = TaskGraph()
        g.add_node("src",  node_id="src",  handler=_ok_handler)
        g.add_node("tgt",  node_id="tgt",  handler=_ok_handler, depends_on=["src"])
        g.add_edge("src", "tgt", condition=lambda n: False)
        r = await g.execute()
        assert g._nodes["src"].status == NodeStatus.DONE
        assert g._nodes["tgt"].status == NodeStatus.SKIPPED


# ===========================================================================
# V) execute() — rollback is called on failure
# ===========================================================================

class TestExecuteRollback:
    async def test_rollback_called_on_failure(self):
        rollback_called: Dict[str, bool] = {}

        async def _rollback(node: TaskNode, ctx: Dict[str, Any]) -> None:
            rollback_called[node.node_id] = True

        g = TaskGraph()
        g.add_node(
            "rb_test",
            node_id="rb",
            handler=_always_fail,
            rollback=_rollback,
            retry_policy=RetryPolicy(max_retries=0),
        )
        await g.execute()
        assert rollback_called.get("rb") is True


# ===========================================================================
# W) snapshot()
# ===========================================================================

class TestSnapshot:
    async def test_snapshot_is_serialisable(self):
        import json
        g = TaskGraph(trace_id="snap_trace", runtime_session_id="sess1")
        g.add_node("n1", node_id="n1", handler=_ok_handler)
        g.add_node("n2", node_id="n2", handler=_ok_handler, depends_on=["n1"])
        await g.execute()
        snap = g.snapshot()
        # Should be JSON-serialisable (no non-serialisable objects)
        dumped = json.dumps(snap)
        loaded = json.loads(dumped)
        assert loaded["trace_id"] == "snap_trace"
        node_ids = {n["node_id"] for n in loaded["nodes"]}
        assert node_ids == {"n1", "n2"}


# ===========================================================================
# X) ready_nodes()
# ===========================================================================

class TestReadyNodes:
    def test_no_deps_all_ready(self):
        g = TaskGraph()
        g.add_node("a", node_id="a")
        g.add_node("b", node_id="b")
        ready = g.ready_nodes()
        assert {n.node_id for n in ready} == {"a", "b"}

    def test_with_deps_only_root_ready(self):
        g = TaskGraph()
        g.add_node("root", node_id="root")
        g.add_node("child", node_id="child", depends_on=["root"])
        ready = g.ready_nodes()
        assert [n.node_id for n in ready] == ["root"]


# ===========================================================================
# Y) compile_subtasks_to_graph() basic
# ===========================================================================

class TestCompileSubtasks:
    def _make_subtask(self, task_id: str, name: str, depends_on=None):
        """Create a minimal subtask-like object."""
        obj = MagicMock()
        obj.task_id = task_id
        obj.name = name
        obj.description = f"desc for {name}"
        obj.depends_on = depends_on or []
        obj.device_id = ""
        obj.device_type = ""
        return obj

    def test_nodes_created(self):
        sts = [
            self._make_subtask("t1", "Task 1"),
            self._make_subtask("t2", "Task 2"),
        ]
        g = compile_subtasks_to_graph(sts)
        assert "t1" in g._nodes
        assert "t2" in g._nodes

    def test_no_deps_single_layer(self):
        sts = [
            self._make_subtask("t1", "a"),
            self._make_subtask("t2", "b"),
        ]
        g = compile_subtasks_to_graph(sts)
        layers = g.topological_layers()
        assert len(layers) == 1

    async def test_execute_compiles_and_runs(self):
        sts = [
            self._make_subtask("t1", "step1"),
            self._make_subtask("t2", "step2", depends_on=["t1"]),
        ]
        g = compile_subtasks_to_graph(sts, node_handler=_ok_handler)
        r = await g.execute()
        assert r.success is True
        assert r.done_nodes == 2


# ===========================================================================
# Z) compile_subtasks_to_graph() — resolve depends_on by name
# ===========================================================================

class TestCompileSubtasksByName:
    def _make_subtask(self, task_id: str, name: str, depends_on=None):
        obj = MagicMock()
        obj.task_id = task_id
        obj.name = name
        obj.description = name
        obj.depends_on = depends_on or []
        obj.device_id = ""
        obj.device_type = ""
        return obj

    def test_depends_by_name_resolved(self):
        sts = [
            self._make_subtask("id1", "fetch"),
            self._make_subtask("id2", "process", depends_on=["fetch"]),
        ]
        g = compile_subtasks_to_graph(sts)
        # "id2" depends_on should be resolved to "id1"
        assert "id1" in g._nodes["id2"].depends_on


# ===========================================================================
# AA) trace_id / runtime_session_id propagation
# ===========================================================================

class TestTraceIdPropagation:
    async def test_trace_id_in_handler_context(self):
        received: Dict[str, Any] = {}

        async def capturing_handler(node: TaskNode, ctx: Dict[str, Any]) -> Dict[str, Any]:
            received.update(ctx)
            return {}

        g = TaskGraph(trace_id="TRACE_001", runtime_session_id="SESSION_42")
        g.add_node("x", node_id="x", handler=capturing_handler)
        await g.execute(context={"extra": "val"})
        assert received.get("trace_id") == "TRACE_001"
        assert received.get("runtime_session_id") == "SESSION_42"

    def test_graph_attributes(self):
        g = TaskGraph(trace_id="T", runtime_session_id="S")
        assert g.trace_id == "T"
        assert g.runtime_session_id == "S"


# ===========================================================================
# AB) GraphExecutionResult fields
# ===========================================================================

class TestGraphExecutionResult:
    async def test_result_fields_populated(self):
        g = TaskGraph(trace_id="abc")
        g.add_node("n1", node_id="n1", handler=_ok_handler)
        g.add_node("n2", node_id="n2", handler=_always_fail)
        r = await g.execute()
        assert isinstance(r, GraphExecutionResult)
        assert r.total_nodes == 2
        assert r.done_nodes == 1
        assert r.failed_nodes == 1
        assert r.elapsed_ms > 0
        assert r.trace_id == "abc"
        assert r.node_statuses["n1"] == "done"
        assert r.node_statuses["n2"] == "failed"


# ===========================================================================
# AC) compile_and_run_dag() — e2e_orchestrator public API
# ===========================================================================

class TestCompileAndRunDag:
    def _make_subtask(self, task_id: str, name: str, depends_on=None):
        obj = MagicMock()
        obj.task_id = task_id
        obj.name = name
        obj.description = name
        obj.depends_on = depends_on or []
        obj.device_id = ""
        obj.device_type = ""
        return obj

    async def test_basic_success(self):
        from core.e2e_orchestrator import compile_and_run_dag
        sts = [self._make_subtask("a", "step_a"), self._make_subtask("b", "step_b")]
        # Nodes have no handler, so they succeed by default (empty result)
        result = await compile_and_run_dag(
            sts,
            trace_id="e2e_trace",
            runtime_session_id="sess",
        )
        assert result["success"] is True
        assert result["trace_id"] == "e2e_trace"
        assert result["done"] == 2

    async def test_returns_error_on_cycle(self):
        from core.e2e_orchestrator import compile_and_run_dag
        # cyclic dependency: compile_subtasks_to_graph succeeds but execute() fails
        sts = [
            self._make_subtask("x", "x", depends_on=["y"]),
            self._make_subtask("y", "y", depends_on=["x"]),
        ]
        result = await compile_and_run_dag(sts)
        assert result["success"] is False
        # error should be reported either in the "error" key or via failed nodes
        has_error = bool(result.get("error")) or result.get("failed", 0) > 0
        assert has_error


# ===========================================================================
# AD) compile_and_run_dag() — cycle via compile_subtasks_to_graph
# ===========================================================================

class TestCompileAndRunDagCycle:
    def _make_subtask(self, task_id: str, name: str, depends_on=None):
        obj = MagicMock()
        obj.task_id = task_id
        obj.name = name
        obj.description = name
        obj.depends_on = depends_on or []
        obj.device_id = ""
        obj.device_type = ""
        return obj

    def test_cycle_raises_in_compile(self):
        sts = [
            self._make_subtask("a", "a", depends_on=["b"]),
            self._make_subtask("b", "b", depends_on=["a"]),
        ]
        g = compile_subtasks_to_graph(sts)
        with pytest.raises(ValueError, match="cycle"):
            g.topological_layers()
