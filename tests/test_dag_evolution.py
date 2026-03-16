"""
tests/test_dag_evolution.py
============================

Tests for :class:`core.dag_evolver.DAGEvolver`.

Covers:
  A) on_task_failed — replan sub-graph reset and cascade failure
  B) on_timeout — reassign timed-out task to a different device
  C) on_missing_capability — insert capability-gap node
  D) Repeated failure exhausts replan limit
"""

from __future__ import annotations

import pytest
from core.schemas.orchestration import SubTask, SubTaskStatus, TaskDecomposition


# ===========================================================================
# Helpers
# ===========================================================================

def _make_evolver(max_replan_attempts: int = 3):
    from core.dag_evolver import DAGEvolver
    return DAGEvolver(max_replan_attempts=max_replan_attempts)


def _make_decomposition(*subtasks: SubTask) -> TaskDecomposition:
    return TaskDecomposition(goal="test goal", subtasks=list(subtasks))


def _make_subtask(name: str, task_id: str = "", depends_on=None, status=SubTaskStatus.PENDING):
    return SubTask(
        task_id=task_id or f"sub_{name}",
        name=name,
        depends_on=depends_on or [],
        status=status,
    )


# ===========================================================================
# A) on_task_failed — replan sub-graph
# ===========================================================================

class TestOnTaskFailed:
    def test_resets_failed_task_to_pending(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.FAILED)
        d = _make_decomposition(task_a)
        result = evolver.on_task_failed(d, failed_task_id="ta", error="boom")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].status == SubTaskStatus.PENDING

    def test_resets_downstream_dependents(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.FAILED)
        task_b = _make_subtask("B", task_id="tb", depends_on=["ta"], status=SubTaskStatus.FAILED)
        task_c = _make_subtask("C", task_id="tc", depends_on=["tb"], status=SubTaskStatus.FAILED)
        d = _make_decomposition(task_a, task_b, task_c)
        result = evolver.on_task_failed(d, failed_task_id="ta", error="boom")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].status == SubTaskStatus.PENDING
        assert task_map["tb"].status == SubTaskStatus.PENDING
        assert task_map["tc"].status == SubTaskStatus.PENDING

    def test_clears_result_and_error_on_reset(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.FAILED)
        task_a.result = {"data": "stale"}
        task_a.error = "old error"
        d = _make_decomposition(task_a)
        result = evolver.on_task_failed(d, failed_task_id="ta")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].result is None
        assert task_map["ta"].error == ""

    def test_does_not_reset_unrelated_task(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.FAILED)
        task_b = _make_subtask("B", task_id="tb", status=SubTaskStatus.SUCCESS)
        d = _make_decomposition(task_a, task_b)
        result = evolver.on_task_failed(d, failed_task_id="ta")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["tb"].status == SubTaskStatus.SUCCESS

    def test_unknown_task_id_returns_decomposition_unchanged(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.SUCCESS)
        d = _make_decomposition(task_a)
        result = evolver.on_task_failed(d, failed_task_id="ghost")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].status == SubTaskStatus.SUCCESS


# ===========================================================================
# B) Replan limit exhausted
# ===========================================================================

class TestReplanLimit:
    def test_cascade_failed_after_limit(self):
        evolver = _make_evolver(max_replan_attempts=2)
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.FAILED)
        task_b = _make_subtask("B", task_id="tb", depends_on=["ta"])
        d = _make_decomposition(task_a, task_b)

        # First two attempts should reset
        for _ in range(2):
            d = evolver.on_task_failed(d, failed_task_id="ta", error="err")
            # Mark failed again for the next iteration
            task_map = {st.task_id: st for st in d.subtasks}
            task_map["ta"].status = SubTaskStatus.FAILED

        # Third attempt should cascade failure
        d = evolver.on_task_failed(d, failed_task_id="ta", error="err")
        task_map = {st.task_id: st for st in d.subtasks}
        assert task_map["ta"].status == SubTaskStatus.FAILED
        assert "replan exhausted" in task_map["ta"].error


# ===========================================================================
# C) on_timeout — reassign
# ===========================================================================

class TestOnTimeout:
    def test_resets_timed_out_task_to_pending(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta", status=SubTaskStatus.RUNNING)
        task_a.device_id = "old_device"
        d = _make_decomposition(task_a)
        result = evolver.on_timeout(d, timed_out_task_id="ta")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].status == SubTaskStatus.PENDING

    def test_clears_device_on_timeout(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        task_a.device_id = "old_device"
        d = _make_decomposition(task_a)
        result = evolver.on_timeout(d, timed_out_task_id="ta")
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].device_id == ""

    def test_assigns_preferred_device_on_timeout(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        task_a.device_id = "old_device"
        d = _make_decomposition(task_a)
        result = evolver.on_timeout(
            d, timed_out_task_id="ta", preferred_device_id="new_device"
        )
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].device_id == "new_device"

    def test_timeout_unknown_task_is_no_op(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        d = _make_decomposition(task_a)
        result = evolver.on_timeout(d, timed_out_task_id="ghost")
        # No change expected
        task_map = {st.task_id: st for st in result.subtasks}
        assert task_map["ta"].status == SubTaskStatus.PENDING


# ===========================================================================
# D) on_missing_capability — insert gap node
# ===========================================================================

class TestOnMissingCapability:
    def test_inserts_gap_node_into_subtasks(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        d = _make_decomposition(task_a)
        result = evolver.on_missing_capability(
            d, requesting_task_id="ta", missing_capability="gpu"
        )
        assert len(result.subtasks) == 2

    def test_gap_node_has_correct_action(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        d = _make_decomposition(task_a)
        result = evolver.on_missing_capability(
            d, requesting_task_id="ta", missing_capability="camera"
        )
        gap = next(st for st in result.subtasks if st.action == "acquire_capability")
        assert gap.params.get("capability") == "camera"

    def test_requesting_task_depends_on_gap_node(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        d = _make_decomposition(task_a)
        result = evolver.on_missing_capability(
            d, requesting_task_id="ta", missing_capability="screen"
        )
        gap_id = next(st.task_id for st in result.subtasks if st.action == "acquire_capability")
        task_map = {st.task_id: st for st in result.subtasks}
        assert gap_id in task_map["ta"].depends_on

    def test_gap_node_status_is_pending(self):
        evolver = _make_evolver()
        task_a = _make_subtask("A", task_id="ta")
        d = _make_decomposition(task_a)
        result = evolver.on_missing_capability(
            d, requesting_task_id="ta", missing_capability="touch"
        )
        gap = next(st for st in result.subtasks if st.action == "acquire_capability")
        assert gap.status == SubTaskStatus.PENDING
