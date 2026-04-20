"""tests/test_prd_goal_execution_result_canonical.py
======================================================

PR-D: Unified Android goal result and task result canonical server-side handling.

Coverage groups
---------------
A  — store_goal_execution_result: writes success result to TaskMemory.
B  — store_goal_execution_result: writes failed result to TaskMemory.
C  — store_goal_execution_result: skips silently when get_task_memory unavailable.
D  — store_goal_execution_result: includes group_id/subtask_index in extra.
E  — store_goal_execution_result: tags include goal_execution_result label.
F  — store_goal_execution_result: extra_payload is stored (non-fatal on exception).
G  — handle_goal_execution_result: calls canonical _store_goal_result.
H  — handle_goal_execution_result: calls on_goal_execution_result on runtime.
I  — handle_goal_execution_result: reconciler called.
J  — handle_goal_execution_result: group aggregation records to parallel tracker.
K  — handle_goal_execution_result: group completion triggers group summary write.
L  — handle_goal_execution_result: missing group_id skips aggregation.
M  — on_goal_execution_result: writes to TaskMemory.
N  — on_goal_execution_result: injects result into matching active session.
O  — on_goal_execution_result: non-fatal on TaskMemory error.
P  — on_goal_execution_result: no crash when _active_sessions is empty.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.new_event_loop().run_until_complete(coro)


def _make_goal_result_message(
    task_id: str = "task-abc",
    device_id: str = "dev-1",
    status: str = "completed",
    result: str = "all done",
    group_id: str | None = None,
    subtask_index: int | None = None,
    trace_id: str = "trace-123",
    latency_ms: int = 100,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "result": result,
        "trace_id": trace_id,
        "latency_ms": latency_ms,
        "route_mode": "cross_device",
    }
    if group_id is not None:
        payload["group_id"] = group_id
    if subtask_index is not None:
        payload["subtask_index"] = subtask_index
    return {
        "type": "GOAL_EXECUTION_RESULT",
        "device_id": device_id,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# A — store_goal_execution_result: writes success result to TaskMemory
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultSuccess:
    def test_success_status_records_to_task_memory(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t1",
                device_id="d1",
                status="completed",
                result="done",
            ))

        assert mock_mem.record_task.called
        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["success"] is True
        assert "goal_execution_result" in call_kwargs["task_type"]

    def test_success_via_string_success(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t2",
                device_id="d1",
                status="success",
                result="ok",
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["success"] is True


# ---------------------------------------------------------------------------
# B — store_goal_execution_result: writes failed result to TaskMemory
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultFailed:
    def test_failed_status_records_success_false(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t3",
                device_id="d1",
                status="failed",
                result="error occurred",
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["success"] is False


# ---------------------------------------------------------------------------
# C — store_goal_execution_result: skips when get_task_memory unavailable
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultNoMemory:
    def test_no_exception_when_get_task_memory_is_none(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        with patch("core.openclawd_memory_backflow.get_task_memory", None):
            # Should not raise
            run(store_goal_execution_result(
                task_id="t4",
                device_id="d1",
                status="completed",
                result="ok",
            ))


# ---------------------------------------------------------------------------
# D — store_goal_execution_result: group_id and subtask_index in extra
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultGroupFields:
    def test_group_id_and_subtask_index_in_extra(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t5",
                device_id="d2",
                status="completed",
                result="sub done",
                group_id="grp-1",
                subtask_index=2,
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["extra"]["group_id"] == "grp-1"
        assert call_kwargs["extra"]["subtask_index"] == 2

    def test_task_description_includes_group_info(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t5b",
                device_id="d2",
                status="completed",
                result="sub done",
                group_id="grp-2",
                subtask_index=0,
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert "grp-2" in call_kwargs["task"]


# ---------------------------------------------------------------------------
# E — store_goal_execution_result: tags include goal_execution_result
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultTags:
    def test_tags_include_goal_execution_result(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t6",
                device_id="d1",
                status="completed",
                result="ok",
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert "goal_execution_result" in call_kwargs["tags"]

    def test_tags_include_group_when_present(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            run(store_goal_execution_result(
                task_id="t6b",
                device_id="d1",
                status="completed",
                result="ok",
                group_id="grp-x",
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert any("group:grp-x" in t for t in call_kwargs["tags"])


# ---------------------------------------------------------------------------
# F — store_goal_execution_result: non-fatal on TaskMemory exception
# ---------------------------------------------------------------------------

class TestStoreGoalExecutionResultNonFatal:
    def test_does_not_raise_on_task_memory_error(self):
        from core.openclawd_memory_backflow import store_goal_execution_result

        mock_mem = MagicMock()
        mock_mem.record_task.side_effect = RuntimeError("DB error")
        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=mock_mem):
            # Should not raise
            run(store_goal_execution_result(
                task_id="t7",
                device_id="d1",
                status="completed",
                result="ok",
            ))


# ---------------------------------------------------------------------------
# G — handle_goal_execution_result: calls canonical _store_goal_result
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultBackflow:
    def test_store_goal_result_called(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_store = AsyncMock()
        msg = _make_goal_result_message()

        with patch.object(goal_execution, "_store_goal_result", mock_store), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", None), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_store.assert_awaited_once()
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["task_id"] == "task-abc"
        assert call_kwargs["device_id"] == "dev-1"
        assert call_kwargs["status"] == "completed"

    def test_falls_back_to_store_task_result_when_store_goal_result_unavailable(self):
        """When _store_goal_result is None, falls back to store_task_result."""
        from galaxy_gateway.android.handlers import goal_execution

        mock_store = AsyncMock()
        msg = _make_goal_result_message()

        with patch.object(goal_execution, "_store_goal_result", None), \
             patch.object(goal_execution, "store_task_result", mock_store), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", None), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_store.assert_awaited_once()
        # Verify fallback uses correct positional params (route_mode is 3rd)
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["task_id"] == "task-abc"
        assert call_kwargs["route_mode"] == "cross_device"
        assert isinstance(call_kwargs["result"], dict)


# ---------------------------------------------------------------------------
# H — handle_goal_execution_result: calls on_goal_execution_result on runtime
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultRuntimeCallback:
    def test_on_goal_execution_result_called(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_rt_cb = AsyncMock()
        mock_runtime = MagicMock()
        mock_runtime.on_goal_execution_result = mock_rt_cb
        msg = _make_goal_result_message(
            task_id="t-cb",
            status="completed",
            result="done",
            trace_id="tr-99",
        )

        with patch.object(goal_execution, "_store_goal_result", AsyncMock()), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", None), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=mock_runtime):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_rt_cb.assert_awaited_once()
        call_kwargs = mock_rt_cb.call_args[1]
        assert call_kwargs["task_id"] == "t-cb"
        assert call_kwargs["trace_id"] == "tr-99"


# ---------------------------------------------------------------------------
# I — handle_goal_execution_result: reconciler called
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultReconciler:
    def test_reconciler_called_when_available(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_reconciler = MagicMock()
        outcome = MagicMock()
        outcome.was_updated = False
        mock_reconciler.return_value = outcome
        msg = _make_goal_result_message()

        with patch.object(goal_execution, "_store_goal_result", AsyncMock()), \
             patch.object(goal_execution, "_reconcile_goal_result", mock_reconciler), \
             patch.object(goal_execution, "_get_parallel_tracker", None), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_reconciler.assert_called_once_with(msg)


# ---------------------------------------------------------------------------
# J — handle_goal_execution_result: group aggregation records to tracker
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultGroupAggregation:
    def test_records_subtask_result_when_group_id_present(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_tracker = MagicMock()
        mock_tracker.record_result = AsyncMock()
        mock_tracker.finalize_if_complete = AsyncMock(return_value=None)
        mock_get_tracker = MagicMock(return_value=mock_tracker)

        msg = _make_goal_result_message(group_id="grp-a", subtask_index=1, status="completed")

        with patch.object(goal_execution, "_store_goal_result", AsyncMock()), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", mock_get_tracker), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_tracker.record_result.assert_awaited_once()
        rec_kwargs = mock_tracker.record_result.call_args[1]
        assert rec_kwargs["group_id"] == "grp-a"
        assert rec_kwargs["subtask_index"] == 1
        assert rec_kwargs["status"] == "success"

    def test_failed_status_maps_to_failed_subtask_status(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_tracker = MagicMock()
        mock_tracker.record_result = AsyncMock()
        mock_tracker.finalize_if_complete = AsyncMock(return_value=None)
        mock_get_tracker = MagicMock(return_value=mock_tracker)

        msg = _make_goal_result_message(group_id="grp-b", subtask_index=0, status="failed")

        with patch.object(goal_execution, "_store_goal_result", AsyncMock()), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", mock_get_tracker), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        rec_kwargs = mock_tracker.record_result.call_args[1]
        assert rec_kwargs["status"] == "failed"


# ---------------------------------------------------------------------------
# K — handle_goal_execution_result: group completion triggers summary write
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultGroupCompletion:
    def test_group_completion_writes_summary_to_task_memory(self):
        from galaxy_gateway.android.handlers import goal_execution
        from galaxy_gateway.orchestrator.parallel_tracker import (
            ParallelGroupStatus,
            ParallelSubtaskResult,
        )
        import time

        finalized_status = ParallelGroupStatus(
            group_id="grp-c",
            status="success",
            results=[
                ParallelSubtaskResult(
                    group_id="grp-c",
                    subtask_index=0,
                    status="success",
                    latency_ms=50,
                ),
            ],
            started_at=time.time() - 1.0,
            finished_at=time.time(),
        )

        mock_tracker = MagicMock()
        mock_tracker.record_result = AsyncMock()
        mock_tracker.finalize_if_complete = AsyncMock(return_value=finalized_status)
        mock_get_tracker = MagicMock(return_value=mock_tracker)

        mock_store = AsyncMock()
        msg = _make_goal_result_message(group_id="grp-c", subtask_index=0, status="completed")

        with patch.object(goal_execution, "_store_goal_result", mock_store), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", mock_get_tracker), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        # Should be called twice: once for individual subtask, once for group summary
        assert mock_store.await_count == 2
        # The second call should be for the group summary
        summary_call_kwargs = mock_store.call_args_list[1][1]
        assert "group_summary" in summary_call_kwargs["task_id"]
        assert summary_call_kwargs["group_id"] == "grp-c"


# ---------------------------------------------------------------------------
# L — handle_goal_execution_result: missing group_id skips aggregation
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultNoGroup:
    def test_no_aggregation_when_group_id_absent(self):
        from galaxy_gateway.android.handlers import goal_execution

        mock_tracker = MagicMock()
        mock_tracker.record_result = AsyncMock()
        mock_get_tracker = MagicMock(return_value=mock_tracker)

        msg = _make_goal_result_message()  # no group_id

        with patch.object(goal_execution, "_store_goal_result", AsyncMock()), \
             patch.object(goal_execution, "_reconcile_goal_result", None), \
             patch.object(goal_execution, "_get_parallel_tracker", mock_get_tracker), \
             patch("core.desktop_presence_runtime.get_desktop_presence_runtime",
                   return_value=MagicMock(on_goal_execution_result=AsyncMock())):
            run(goal_execution.handle_goal_execution_result(
                bridge=MagicMock(),
                websocket=MagicMock(),
                message=msg,
            ))

        mock_tracker.record_result.assert_not_awaited()


# ---------------------------------------------------------------------------
# M — on_goal_execution_result: writes to TaskMemory
# ---------------------------------------------------------------------------

class TestOnGoalExecutionResultTaskMemory:
    def test_writes_to_task_memory_on_success(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        mock_mem = MagicMock()
        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-1",
                device_id="dev-1",
                status="completed",
                result="all good",
                trace_id="tr-abc",
            ))

        assert mock_mem.record_task.called
        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["success"] is True
        assert call_kwargs["task_type"] == "goal_execution_result"

    def test_writes_failure_to_task_memory(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        mock_mem = MagicMock()
        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-2",
                device_id="dev-1",
                status="failed",
                result="error",
                trace_id="tr-def",
            ))

        call_kwargs = mock_mem.record_task.call_args[1]
        assert call_kwargs["success"] is False


# ---------------------------------------------------------------------------
# N — on_goal_execution_result: injects result into matching active session
# ---------------------------------------------------------------------------

class TestOnGoalExecutionResultSessionInjection:
    def test_injects_into_matching_session(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        trace_id = "tr-match-99"

        class _FakeSession:
            runtime_session_id = "tr-match-99"
            trace_id = "tr-match-99"

        fake_session = _FakeSession()

        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {trace_id: fake_session}

        mock_mem = MagicMock()
        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-3",
                device_id="dev-2",
                status="completed",
                result="session-result",
                trace_id=trace_id,
            ))

        # The session should have goal_execution_results injected
        assert hasattr(fake_session, "goal_execution_results")
        assert len(fake_session.goal_execution_results) == 1
        assert fake_session.goal_execution_results[0]["task_id"] == "tid-3"

    def test_no_injection_for_non_matching_session(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        class _FakeSession:
            runtime_session_id = "other-trace"
            trace_id = "other-trace"

        fake_session = _FakeSession()

        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {"other-trace": fake_session}

        mock_mem = MagicMock()
        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-4",
                device_id="dev-2",
                status="completed",
                result="no match",
                trace_id="different-trace",
            ))

        # Session should not have been modified
        assert not hasattr(fake_session, "goal_execution_results")


# ---------------------------------------------------------------------------
# O — on_goal_execution_result: non-fatal on TaskMemory error
# ---------------------------------------------------------------------------

class TestOnGoalExecutionResultNonFatal:
    def test_no_raise_on_task_memory_error(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        mock_mem = MagicMock()
        mock_mem.record_task.side_effect = RuntimeError("DB crash")
        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            # Should not raise
            run(runtime.on_goal_execution_result(
                task_id="tid-5",
                device_id="dev-1",
                status="completed",
                result="ok",
                trace_id="tr-err",
            ))


# ---------------------------------------------------------------------------
# P — on_goal_execution_result: no crash when _active_sessions is empty
# ---------------------------------------------------------------------------

class TestOnGoalExecutionResultEmptySessions:
    def test_no_crash_empty_sessions(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = object.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        mock_mem = MagicMock()
        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-6",
                device_id="dev-1",
                status="completed",
                result="ok",
                trace_id="tr-empty",
            ))

    def test_no_crash_when_no_active_sessions_attr(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = object.__new__(DesktopPresenceRuntime)
        # No _active_sessions attribute at all

        mock_mem = MagicMock()
        with patch("core.task_memory.get_task_memory", return_value=mock_mem):
            run(runtime.on_goal_execution_result(
                task_id="tid-7",
                device_id="dev-1",
                status="completed",
                result="ok",
                trace_id="tr-noattr",
            ))
