#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_constellation_scheduling_gate.py
================================================
PR-9 — Constellation scheduling gate on canonical orchestration readiness.

Verifies that :class:`core.constellation_runtime.ConstellationRuntime` gates
multi-device scheduling on the canonical orchestration-ready candidate set
provided by :mod:`core.device_participation`, failing early with structured
reasons rather than failing late during execution.

Coverage
--------
A) ``_get_orchestration_candidate_set()`` helper

   1. Returns the list from ``get_orchestration_ready_devices`` when available.
   2. Returns ``None`` (graceful degradation) when the participation module
      is unavailable / raises.

B) ``_check_scheduling_gate()`` helper

   3. All subtasks pre-assigned → gate is a no-op (returns ``None``).
   4. Participation layer unavailable → gate passes (returns ``None``).
   5. No orchestration-ready devices → returns ``no_orchestration_ready_devices``.
   6. Single-device task with ≥1 ready device → gate passes.
   7. Multi-device task, enough ready devices → gate passes.
   8. Multi-device task, too few ready devices → returns
      ``insufficient_orchestration_ready_devices``.
   9. One unassigned subtask with zero ready devices → returns
      ``no_orchestration_ready_devices``.

C) ``_run_dag_loop`` end-to-end gate integration

  10. Zero orchestration-ready devices → early structured failure with
      ``success=False`` and ``mode=scheduling_gate``.
  11. Too few orchestration-ready devices (multi-device task) → early
      structured failure with ``insufficient_orchestration_ready_devices``.
  12. Sufficient orchestration-ready devices → scheduling path proceeds to
      execution (no gate rejection).
  13. Participation layer unavailable during ``_run_dag_loop`` → graceful
      degradation, scheduling continues normally.

D) ``ConstellationRuntime.run()`` top-level integration

  14. ``run()`` propagates the scheduling-gate failure at the top level.
  15. Gate failure result includes structured ``data.reason`` field.
"""

from __future__ import annotations

import sys
import os
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runtime(dag_evolution: bool = False):
    from core.constellation_runtime import ConstellationRuntime
    return ConstellationRuntime(enable_dag_evolution=dag_evolution)


def _make_subtask(task_id: str = "t1", device_id: str = "", device_type: str = ""):
    from core.schemas.orchestration import SubTask, SubTaskStatus
    return SubTask(
        task_id=task_id,
        name=f"task_{task_id}",
        device_id=device_id,
        device_type=device_type,
        status=SubTaskStatus.PENDING,
    )


def _make_participation_summary(device_id: str, eligible: bool = True):
    from core.device_participation import ParticipationSummary
    return ParticipationSummary(
        device_id=device_id,
        assessed=True,
        registered=True,
        runtime_present=True,
        routable=eligible,
        orchestration_eligible=eligible,
    )


# ===========================================================================
# A) _get_orchestration_candidate_set
# ===========================================================================


class TestGetOrchestrationCandidateSet:
    def test_returns_list_when_available(self):
        """Returns the list from get_orchestration_ready_devices when module is present."""
        rt = _make_runtime()
        summaries = [_make_participation_summary("dev_a"), _make_participation_summary("dev_b")]
        mock_udm = MagicMock()
        with patch("core.device_participation._get_udm", return_value=mock_udm):
            with patch(
                "core.device_participation.get_orchestration_ready_devices",
                return_value=summaries,
            ):
                result = rt._get_orchestration_candidate_set()
        assert result == summaries

    def test_returns_none_when_udm_unavailable(self):
        """Returns None (degrade gracefully) when the device registry (UDM) is absent."""
        rt = _make_runtime()
        with patch("core.device_participation._get_udm", return_value=None):
            result = rt._get_orchestration_candidate_set()
        assert result is None

    def test_returns_none_on_import_error(self):
        """Returns None (graceful degradation) when the participation module raises."""
        rt = _make_runtime()
        with patch(
            "core.device_participation.get_orchestration_ready_devices",
            side_effect=ImportError("simulated missing module"),
        ):
            result = rt._get_orchestration_candidate_set()
        assert result is None

    def test_returns_none_on_runtime_exception(self):
        """Returns None when get_orchestration_ready_devices raises any exception."""
        rt = _make_runtime()
        with patch(
            "core.device_participation.get_orchestration_ready_devices",
            side_effect=RuntimeError("db unavailable"),
        ):
            result = rt._get_orchestration_candidate_set()
        assert result is None


# ===========================================================================
# B) _check_scheduling_gate
# ===========================================================================


class TestCheckSchedulingGate:
    def test_all_subtasks_pre_assigned_is_noop(self):
        """When all subtasks already carry a device_id the gate is a no-op."""
        rt = _make_runtime()
        subtasks = [
            _make_subtask("t1", device_id="dev_1"),
            _make_subtask("t2", device_id="dev_2"),
        ]
        with patch.object(rt, "_get_orchestration_candidate_set") as mock_cset:
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-001")
        # Gate should not have queried the participation layer at all
        mock_cset.assert_not_called()
        assert result is None

    def test_participation_layer_unavailable_passes(self):
        """When candidate set returns None the gate passes (graceful degradation)."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1")]  # unassigned
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=None):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-002")
        assert result is None

    def test_no_ready_devices_returns_reason(self):
        """Zero orchestration-ready devices → no_orchestration_ready_devices."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1")]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=[]):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-003")
        assert result == "no_orchestration_ready_devices"

    def test_single_task_one_ready_device_passes(self):
        """One unassigned subtask with ≥1 ready device → gate passes."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1")]
        candidates = [_make_participation_summary("dev_a")]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-004")
        assert result is None

    def test_multi_device_task_enough_ready_passes(self):
        """Multi-device task with enough ready devices → gate passes."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1"), _make_subtask("t2"), _make_subtask("t3")]
        candidates = [
            _make_participation_summary("dev_a"),
            _make_participation_summary("dev_b"),
            _make_participation_summary("dev_c"),
        ]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-005")
        assert result is None

    def test_multi_device_task_too_few_ready_returns_reason(self):
        """Multi-device task with too few ready devices → insufficient_orchestration_ready_devices."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1"), _make_subtask("t2"), _make_subtask("t3")]
        candidates = [_make_participation_summary("dev_a")]  # only 1 ready but 3 needed
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-006")
        assert result == "insufficient_orchestration_ready_devices"

    def test_multi_device_task_boundary_exact_count_passes(self):
        """Multi-device task with exactly enough ready devices passes."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1"), _make_subtask("t2")]
        candidates = [
            _make_participation_summary("dev_a"),
            _make_participation_summary("dev_b"),
        ]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-007")
        assert result is None

    def test_single_unassigned_zero_ready(self):
        """One unassigned subtask with zero ready devices → no_orchestration_ready_devices."""
        rt = _make_runtime()
        subtasks = [_make_subtask("t1")]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=[]):
            result = rt._check_scheduling_gate(subtasks, trace_id="tr-008")
        assert result == "no_orchestration_ready_devices"


# ===========================================================================
# C) _run_dag_loop end-to-end gate integration
# ===========================================================================


def _build_mock_orchestrator():
    """Return a mock SmartOrchestrator that decomposes into two subtasks."""
    from core.schemas.orchestration import TaskDecomposition, SubTaskStatus

    mock = MagicMock()

    async def _decompose(desc, ctx):
        st1 = _make_subtask("t1")
        st2 = _make_subtask("t2")
        return TaskDecomposition(goal=desc, subtasks=[st1, st2])

    async def _exec_subtask(task, req):
        task.status = SubTaskStatus.SUCCESS
        task.result = {"reply": "done"}

    mock._decompose_task = _decompose
    mock._execute_subtask = _exec_subtask
    return mock


class TestRunDagLoopGateIntegration:
    @pytest.mark.asyncio
    async def test_zero_ready_devices_causes_early_failure(self):
        """Zero orchestration-ready devices → early structured failure from gate."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()

        with patch.object(rt, "_get_orchestration_candidate_set", return_value=[]):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="multi-device task")

        assert result["success"] is False
        assert result["mode"] == "scheduling_gate"
        assert result["data"]["reason"] == "no_orchestration_ready_devices"

    @pytest.mark.asyncio
    async def test_too_few_ready_devices_causes_early_failure(self):
        """Too few orchestration-ready devices for multi-device task → gate rejection."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()  # returns 2 unassigned subtasks

        # Only 1 ready device but 2 subtasks need devices
        candidates = [_make_participation_summary("dev_a")]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="multi-device task")

        assert result["success"] is False
        assert result["mode"] == "scheduling_gate"
        assert result["data"]["reason"] == "insufficient_orchestration_ready_devices"

    @pytest.mark.asyncio
    async def test_sufficient_ready_devices_proceeds_to_execution(self):
        """Enough orchestration-ready devices → scheduling proceeds past the gate."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()  # 2 unassigned subtasks

        candidates = [
            _make_participation_summary("dev_a"),
            _make_participation_summary("dev_b"),
        ]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="two-device task")

        # Gate passed — mode should be "dag" not "scheduling_gate"
        assert result["mode"] != "scheduling_gate"

    @pytest.mark.asyncio
    async def test_participation_layer_unavailable_does_not_crash(self):
        """Missing participation layer → graceful degradation, scheduling continues."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()

        # Simulate participation layer unavailable (returns None)
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=None):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="graceful degradation task")

        # No crash and no gate rejection
        assert result["mode"] != "scheduling_gate"
        assert "success" in result


# ===========================================================================
# D) run() top-level integration
# ===========================================================================


class TestRunTopLevelGateIntegration:
    @pytest.mark.asyncio
    async def test_run_propagates_gate_failure(self):
        """run() surfaces the scheduling-gate failure dict at the top level."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()

        with patch.object(rt, "_get_orchestration_candidate_set", return_value=[]):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="blocked task", session_id="sess-gate")

        assert result["success"] is False
        assert result["session_id"] == "sess-gate"
        assert result["mode"] == "scheduling_gate"
        assert "trace_id" in result
        assert "elapsed_ms" in result

    @pytest.mark.asyncio
    async def test_gate_failure_result_has_structured_data(self):
        """Gate failure result carries data.reason and data.failure_type."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()

        with patch.object(rt, "_get_orchestration_candidate_set", return_value=[]):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="structured failure test")

        data = result.get("data", {})
        assert data.get("reason") == "no_orchestration_ready_devices"
        assert data.get("failure_type") == "scheduling_gate"

    @pytest.mark.asyncio
    async def test_run_succeeds_when_gate_passes(self):
        """run() completes successfully when the gate is satisfied."""
        rt = _make_runtime()
        rt._smart_orchestrator = _build_mock_orchestrator()

        candidates = [
            _make_participation_summary("dev_a"),
            _make_participation_summary("dev_b"),
        ]
        with patch.object(rt, "_get_orchestration_candidate_set", return_value=candidates):
            with patch(
                "core.constellation_runtime.ConstellationRuntime._try_node71",
                new_callable=AsyncMock,
                return_value=None,
            ):
                result = await rt.run(task_description="passing task")

        # Gate passed — result must not be a gate rejection
        assert result.get("mode") != "scheduling_gate"
        assert "success" in result
