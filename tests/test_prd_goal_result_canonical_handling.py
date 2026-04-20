"""
tests/test_prd_goal_result_canonical_handling.py
=================================================

PR-D: Tests for unified Android goal result and task result canonical
server-side result handling.

Covers:
1. GoalResultAggregator — register/record/completion semantics
2. GoalResultAggregator — idempotency and thread safety
3. GoalResultAggregator — on-the-fly group creation (no prior register)
4. on_goal_execution_result — CanonicalTaskRuntime update (existing task)
5. on_goal_execution_result — CanonicalTaskRuntime update (result-first)
6. on_goal_execution_result — TaskMemory backflow
7. on_goal_execution_result — group_id/group_summary accepted without error
8. handle_goal_execution_result — store_task_result called with correct signature
9. handle_goal_execution_result — aggregator called for grouped results
10. handle_goal_execution_result — non-grouped path: aggregator skipped
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.goal_result_aggregator import (
    GoalResultAggregator,
    GroupResultState,
    SubtaskResultEntry,
    get_goal_result_aggregator,
    reset_goal_result_aggregator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def fresh_aggregator() -> GoalResultAggregator:
    """Return a brand-new aggregator (not the singleton)."""
    return GoalResultAggregator()


def _make_mock_runtime() -> MagicMock:
    """Return a mock DesktopPresenceRuntime with on_goal_execution_result wired."""
    rt = MagicMock()
    rt.on_goal_execution_result = AsyncMock()
    rt._active_sessions = {}
    return rt


# ---------------------------------------------------------------------------
# 1. GoalResultAggregator — basic register/record/completion
# ---------------------------------------------------------------------------


class TestGoalResultAggregatorBasic:
    def test_register_group_returns_state(self):
        agg = fresh_aggregator()
        state = agg.register_group("g1", expected_count=2)
        assert isinstance(state, GroupResultState)
        assert state.group_id == "g1"
        assert state.expected_count == 2
        assert not state.all_done

    def test_register_group_idempotent(self):
        agg = fresh_aggregator()
        s1 = agg.register_group("g2", expected_count=3, session_id="sess1")
        s2 = agg.register_group("g2", expected_count=99)  # second call should be ignored
        assert s1 is s2
        assert s2.expected_count == 3  # original value retained

    def test_record_single_result_not_done(self):
        agg = fresh_aggregator()
        agg.register_group("g3", expected_count=2)
        state = agg.record_subtask_result("g3", "task-a", "completed", "ok", "dev1", 0)
        assert state is not None
        assert state.completed_count == 1
        assert not state.all_done

    def test_record_all_results_triggers_completion(self):
        agg = fresh_aggregator()
        agg.register_group("g4", expected_count=2)
        agg.record_subtask_result("g4", "task-a", "completed", "result-a", "dev1", 0)
        state = agg.record_subtask_result("g4", "task-b", "completed", "result-b", "dev2", 1)
        assert state is not None
        assert state.all_done
        assert state.completed_at is not None
        assert state.summary is not None
        assert state.summary["overall_success"] is True
        assert state.summary["completed_count"] == 2

    def test_group_completion_with_partial_failure(self):
        agg = fresh_aggregator()
        agg.register_group("g5", expected_count=2)
        agg.record_subtask_result("g5", "task-a", "completed", "ok", "dev1", 0)
        state = agg.record_subtask_result("g5", "task-b", "failed", "oops", "dev2", 1)
        assert state is not None
        assert state.all_done
        assert state.summary is not None
        assert state.summary["overall_success"] is False
        assert state.success_count == 1
        assert state.failure_count == 1

    def test_get_group_state_returns_none_for_unknown(self):
        agg = fresh_aggregator()
        assert agg.get_group_state("nonexistent") is None

    def test_get_group_state_returns_existing(self):
        agg = fresh_aggregator()
        agg.register_group("g6", expected_count=1)
        state = agg.get_group_state("g6")
        assert state is not None
        assert state.group_id == "g6"


# ---------------------------------------------------------------------------
# 2. GoalResultAggregator — idempotency
# ---------------------------------------------------------------------------


class TestGoalResultAggregatorIdempotency:
    def test_duplicate_task_id_is_ignored(self):
        agg = fresh_aggregator()
        agg.register_group("g7", expected_count=2)
        agg.record_subtask_result("g7", "task-dup", "completed", "first", "dev1", 0)
        state = agg.record_subtask_result("g7", "task-dup", "failed", "second", "dev1", 0)
        # Second write should be silently ignored; first value wins.
        assert state is not None
        assert state.completed_count == 1
        entry = state.results["task-dup"]
        assert entry.status == "completed"  # first write wins
        assert entry.success is True

    def test_group_does_not_complete_twice(self):
        agg = fresh_aggregator()
        agg.register_group("g8", expected_count=1)
        state = agg.record_subtask_result("g8", "task-x", "completed", "r", "dev1", 0)
        assert state is not None
        assert state.all_done
        first_completed_at = state.completed_at
        # Try to record an extra result that should be ignored
        agg.record_subtask_result("g8", "task-y", "completed", "r2", "dev2", 1)
        state2 = agg.get_group_state("g8")
        assert state2 is not None
        assert state2.completed_at == first_completed_at  # timestamp unchanged


# ---------------------------------------------------------------------------
# 3. GoalResultAggregator — on-the-fly group creation
# ---------------------------------------------------------------------------


class TestGoalResultAggregatorOnTheFly:
    def test_result_without_prior_register_creates_group(self):
        agg = fresh_aggregator()
        state = agg.record_subtask_result("g-otf", "task-a", "completed", "r", "dev1", 0)
        assert state is not None
        assert state.group_id == "g-otf"
        assert state.expected_count is None
        # With unknown expected count, all_done should NOT be set
        assert not state.all_done

    def test_empty_group_id_returns_none(self):
        agg = fresh_aggregator()
        state = agg.record_subtask_result("", "task-a", "completed", "r", "dev1", 0)
        assert state is None


# ---------------------------------------------------------------------------
# Helpers for testing on_goal_execution_result without importing the full
# runtime (which requires numpy, OpenCV, etc.).
# We instantiate DesktopPresenceRuntime via dependency injection.
# ---------------------------------------------------------------------------


def _build_minimal_runtime():
    """
    Build a minimal DesktopPresenceRuntime-like object that has
    on_goal_execution_result but bypasses the heavyweight __init__.
    We do this by importing the class and calling __new__ then manually
    setting required attributes.
    """
    # Stub heavy transitive dependencies before importing the class
    for mod_name in [
        "core.multimodal",
        "core.multimodal.perception_frame",
        "core.multimodal.audio_features",
        "core.multimodal.perception_source_registry",
    ]:
        if mod_name not in sys.modules:
            stub = types.ModuleType(mod_name)
            sys.modules[mod_name] = stub

    # Provide numpy stub if not available
    if "numpy" not in sys.modules:
        np_stub = types.ModuleType("numpy")
        sys.modules["numpy"] = np_stub

    from core.desktop_presence_runtime import DesktopPresenceRuntime, TriState

    obj = object.__new__(DesktopPresenceRuntime)
    obj._active_sessions = {}
    obj._tristate = TriState.SILENT
    return obj


# ---------------------------------------------------------------------------
# 4. on_goal_execution_result — CanonicalTaskRuntime update (existing task)
# ---------------------------------------------------------------------------


class TestOnGoalExecutionResultCanonicalTaskUpdate:
    def test_existing_task_updated_to_completed(self):
        from core.canonical_task import (
            get_canonical_task_runtime,
            build_canonical_task,
            TaskLifecycle,
            reset_canonical_task_runtime,
        )

        reset_canonical_task_runtime()
        build_canonical_task(task_id="ctr-task-1", goal="test goal")
        ctr = get_canonical_task_runtime()
        ctr.update_lifecycle("ctr-task-1", TaskLifecycle.RUNNING)

        runtime = _build_minimal_runtime()

        async def _run():
            await runtime.on_goal_execution_result(
                task_id="ctr-task-1",
                device_id="android_test",
                status="completed",
                result="all done",
                trace_id="trace-abc",
            )

        asyncio.run(_run())

        updated = ctr.get_by_task_id("ctr-task-1")
        assert updated is not None
        assert updated.lifecycle == TaskLifecycle.COMPLETED
        assert updated.result.success is True

        reset_canonical_task_runtime()

    def test_existing_task_updated_to_failed_on_error(self):
        from core.canonical_task import (
            get_canonical_task_runtime,
            build_canonical_task,
            TaskLifecycle,
            reset_canonical_task_runtime,
        )

        reset_canonical_task_runtime()
        build_canonical_task(task_id="ctr-task-2", goal="test goal 2")
        ctr = get_canonical_task_runtime()

        runtime = _build_minimal_runtime()

        async def _run():
            await runtime.on_goal_execution_result(
                task_id="ctr-task-2",
                device_id="android_test",
                status="failed",
                result="something went wrong",
                trace_id="trace-xyz",
            )

        asyncio.run(_run())

        updated = ctr.get_by_task_id("ctr-task-2")
        assert updated is not None
        assert updated.lifecycle == TaskLifecycle.FAILED
        assert updated.result.success is False

        reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# 5. on_goal_execution_result — result-first task registration
# ---------------------------------------------------------------------------


class TestOnGoalExecutionResultResultFirst:
    def test_unknown_task_id_creates_canonical_task_record(self):
        from core.canonical_task import (
            get_canonical_task_runtime,
            TaskLifecycle,
            reset_canonical_task_runtime,
        )

        reset_canonical_task_runtime()
        ctr = get_canonical_task_runtime()
        task_id = "brand-new-task-999"
        assert ctr.get_by_task_id(task_id) is None

        runtime = _build_minimal_runtime()

        async def _run():
            await runtime.on_goal_execution_result(
                task_id=task_id,
                device_id="android_test",
                status="success",
                result="result text",
                trace_id="trace-new",
            )

        asyncio.run(_run())

        created = ctr.get_by_task_id(task_id)
        assert created is not None
        assert created.lifecycle == TaskLifecycle.COMPLETED
        assert created.result.success is True

        reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# 6. on_goal_execution_result — TaskMemory backflow
# ---------------------------------------------------------------------------


class TestOnGoalExecutionResultTaskMemory:
    def test_task_memory_backflow_called(self):
        from core.canonical_task import reset_canonical_task_runtime

        reset_canonical_task_runtime()
        runtime = _build_minimal_runtime()

        async def _run():
            with patch("core.openclawd_memory_backflow.get_task_memory") as mock_gtm:
                mock_mem = MagicMock()
                mock_gtm.return_value = mock_mem
                await runtime.on_goal_execution_result(
                    task_id="mem-task-1",
                    device_id="dev1",
                    status="completed",
                    result="mem result",
                    trace_id="trace-mem",
                )
                mock_mem.record_task.assert_called_once()

        asyncio.run(_run())
        reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# 7. on_goal_execution_result — group_id / group_summary accepted gracefully
# ---------------------------------------------------------------------------


class TestOnGoalExecutionResultGroupArgs:
    def test_group_args_accepted_without_error(self):
        from core.canonical_task import reset_canonical_task_runtime

        reset_canonical_task_runtime()
        runtime = _build_minimal_runtime()

        async def _run():
            # Should not raise even when group_id and group_summary are provided
            await runtime.on_goal_execution_result(
                task_id="grp-task-1",
                device_id="dev1",
                status="completed",
                result="group result",
                trace_id="trace-grp",
                group_id="grp-abc",
                group_summary={"overall_success": True, "completed_count": 2},
            )

        asyncio.run(_run())
        reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# 8. handle_goal_execution_result — store_task_result called with correct sig
# ---------------------------------------------------------------------------


class TestHandleGoalExecutionResultStoreSignature:
    def test_store_task_result_called_with_dict(self):
        """store_task_result must be called with (task_id, device_id, route_mode, result={...})."""
        import galaxy_gateway.android.handlers.goal_execution as ge_mod

        captured_calls = []

        async def mock_store(task_id, device_id, route_mode, result, session_id=None):
            captured_calls.append({
                "task_id": task_id,
                "device_id": device_id,
                "route_mode": route_mode,
                "result": result,
                "session_id": session_id,
            })

        message = {
            "device_id": "android_dev1",
            "payload": {
                "task_id": "store-task-1",
                "status": "completed",
                "result": "nice result",
                "trace_id": "trace-store",
                "latency_ms": 120,
                "route_mode": "cross_device",
            },
        }

        mock_runtime = _make_mock_runtime()

        async def _run():
            with patch.object(ge_mod, "store_task_result", new=mock_store):
                with patch.object(ge_mod, "_reconcile_goal_result", new=None):
                    with patch.object(ge_mod, "_get_goal_result_aggregator", new=None):
                        with patch(
                            "core.desktop_presence_runtime.get_desktop_presence_runtime",
                            return_value=mock_runtime,
                        ):
                            await ge_mod.handle_goal_execution_result(None, None, message)

        asyncio.run(_run())
        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert call["task_id"] == "store-task-1"
        assert call["device_id"] == "android_dev1"
        assert call["route_mode"] == "cross_device"
        # result must be a dict, not a plain string
        assert isinstance(call["result"], dict)
        assert call["result"]["status"] == "completed"
        assert call["result"]["task_type"] == "goal_execution_result"


# ---------------------------------------------------------------------------
# 9. handle_goal_execution_result — aggregator called for grouped results
# ---------------------------------------------------------------------------


class TestHandleGoalExecutionResultAggregator:
    def test_aggregator_called_for_group_result(self):
        import galaxy_gateway.android.handlers.goal_execution as ge_mod

        mock_agg = MagicMock()
        mock_group_state = MagicMock()
        mock_group_state.all_done = False
        mock_agg.record_subtask_result.return_value = mock_group_state

        mock_runtime = _make_mock_runtime()

        message = {
            "device_id": "dev-grp",
            "payload": {
                "task_id": "grp-task-x",
                "status": "completed",
                "result": "sub result",
                "group_id": "group-123",
                "subtask_index": 0,
            },
        }

        async def _run():
            with patch.object(ge_mod, "store_task_result", new=AsyncMock()):
                with patch.object(ge_mod, "_reconcile_goal_result", new=None):
                    with patch.object(
                        ge_mod, "_get_goal_result_aggregator", return_value=mock_agg
                    ):
                        with patch(
                            "core.desktop_presence_runtime.get_desktop_presence_runtime",
                            return_value=mock_runtime,
                        ):
                            await ge_mod.handle_goal_execution_result(None, None, message)

        asyncio.run(_run())
        mock_agg.record_subtask_result.assert_called_once_with(
            group_id="group-123",
            task_id="grp-task-x",
            status="completed",
            result_text="sub result",
            device_id="dev-grp",
            subtask_index=0,
        )

    def test_aggregator_group_complete_notifies_runtime(self):
        import galaxy_gateway.android.handlers.goal_execution as ge_mod

        mock_agg = MagicMock()
        mock_group_state = MagicMock()
        mock_group_state.all_done = True
        mock_group_state.completed_count = 2
        mock_group_state.expected_count = 2
        mock_group_state.success_count = 2
        mock_group_state.failure_count = 0
        mock_group_state.summary = {"overall_success": True}
        mock_agg.record_subtask_result.return_value = mock_group_state

        mock_runtime = _make_mock_runtime()

        message = {
            "device_id": "dev-grp2",
            "payload": {
                "task_id": "grp-final-task",
                "status": "completed",
                "result": "last sub result",
                "group_id": "group-done",
                "subtask_index": 1,
            },
        }

        async def _run():
            with patch.object(ge_mod, "store_task_result", new=AsyncMock()):
                with patch.object(ge_mod, "_reconcile_goal_result", new=None):
                    with patch.object(
                        ge_mod, "_get_goal_result_aggregator", return_value=mock_agg
                    ):
                        with patch(
                            "core.desktop_presence_runtime.get_desktop_presence_runtime",
                            return_value=mock_runtime,
                        ):
                            await ge_mod.handle_goal_execution_result(None, None, message)

        asyncio.run(_run())
        # on_goal_execution_result is called at least once for the group-complete
        # notification with group_id and group_summary kwargs.
        group_complete_calls = [
            c for c in mock_runtime.on_goal_execution_result.call_args_list
            if c.kwargs.get("group_id") == "group-done"
        ]
        assert len(group_complete_calls) == 1
        assert group_complete_calls[0].kwargs.get("group_summary") == {"overall_success": True}


# ---------------------------------------------------------------------------
# 10. handle_goal_execution_result — non-grouped: aggregator skipped
# ---------------------------------------------------------------------------


class TestHandleGoalExecutionResultNonGrouped:
    def test_no_group_id_skips_aggregator(self):
        import galaxy_gateway.android.handlers.goal_execution as ge_mod

        mock_agg = MagicMock()
        mock_runtime = _make_mock_runtime()

        message = {
            "device_id": "dev-solo",
            "payload": {
                "task_id": "solo-task",
                "status": "completed",
                "result": "done",
                # No group_id
            },
        }

        async def _run():
            with patch.object(ge_mod, "store_task_result", new=AsyncMock()):
                with patch.object(ge_mod, "_reconcile_goal_result", new=None):
                    with patch.object(
                        ge_mod, "_get_goal_result_aggregator", return_value=mock_agg
                    ):
                        with patch(
                            "core.desktop_presence_runtime.get_desktop_presence_runtime",
                            return_value=mock_runtime,
                        ):
                            await ge_mod.handle_goal_execution_result(None, None, message)

        asyncio.run(_run())
        mock_agg.record_subtask_result.assert_not_called()


# ---------------------------------------------------------------------------
# 11. Singleton management
# ---------------------------------------------------------------------------


class TestGoalResultAggregatorSingleton:
    def test_get_goal_result_aggregator_returns_same_instance(self):
        reset_goal_result_aggregator()
        a1 = get_goal_result_aggregator()
        a2 = get_goal_result_aggregator()
        assert a1 is a2
        reset_goal_result_aggregator()

    def test_reset_clears_singleton(self):
        reset_goal_result_aggregator()
        a1 = get_goal_result_aggregator()
        reset_goal_result_aggregator()
        a2 = get_goal_result_aggregator()
        assert a1 is not a2
        reset_goal_result_aggregator()


# ---------------------------------------------------------------------------
# 12. SubtaskResultEntry serialisation
# ---------------------------------------------------------------------------


class TestSubtaskResultEntrySerialization:
    def test_to_dict_round_trip(self):
        entry = SubtaskResultEntry(
            task_id="t1",
            device_id="d1",
            status="completed",
            result_text="ok",
            subtask_index=0,
            success=True,
        )
        d = entry.to_dict()
        assert d["task_id"] == "t1"
        assert d["device_id"] == "d1"
        assert d["status"] == "completed"
        assert d["success"] is True


# ---------------------------------------------------------------------------
# 13. GroupResultState serialisation
# ---------------------------------------------------------------------------


class TestGroupResultStateSerialization:
    def test_to_dict_complete_group(self):
        agg = fresh_aggregator()
        agg.register_group("g-ser", expected_count=1, session_id="s1", trace_id="t1")
        state = agg.record_subtask_result("g-ser", "task-ser", "completed", "r", "dev1", 0)
        assert state is not None
        d = state.to_dict()
        assert d["group_id"] == "g-ser"
        assert d["all_done"] is True
        assert d["expected_count"] == 1
        assert d["completed_count"] == 1
        assert d["success_count"] == 1
        assert d["failure_count"] == 0
        assert "results" in d
        assert "summary" in d

