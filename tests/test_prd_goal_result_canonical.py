"""
tests/test_prd_goal_result_canonical.py
=========================================

PR-D: Unified Android goal result and task result — canonical server-side
result handling.

Covers:
1. handle_goal_execution_result uses correct store_task_result signature
2. on_goal_execution_result writes to TaskMemory and injects into session
3. Parallel group aggregation when group_id / subtask_index present
4. Reconciler still maps goal_execution_result → final_result
"""

from __future__ import annotations

import importlib.util
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loader helpers — bypass the pydantic-dependent package __init__.py
# ---------------------------------------------------------------------------

def _load_goal_execution_handler():
    """Load galaxy_gateway.android.handlers.goal_execution directly.

    The package ``galaxy_gateway.android.__init__`` has a hard transitive
    dependency on ``pydantic`` via ``models.py → device_types.py → aip_v3.py``.
    In the CI environment pydantic may not be installed, so we bypass the
    package init by loading the handler file directly while keeping the real
    top-level ``galaxy_gateway`` package intact.
    """
    mod_key = "galaxy_gateway.android.handlers.goal_execution"
    if mod_key in sys.modules:
        return sys.modules[mod_key]

    # Import the real top-level galaxy_gateway package first (avoids replacing it).
    import galaxy_gateway as _gw  # noqa: F401

    # Stub only galaxy_gateway.android (the sub-package that pulls in pydantic).
    if "galaxy_gateway.android" not in sys.modules:
        ga_android = types.ModuleType("galaxy_gateway.android")
        ga_android.__path__ = []  # mark as package
        sys.modules["galaxy_gateway.android"] = ga_android

    # Stub galaxy_gateway.android.handlers (to avoid handlers/__init__ chain).
    if "galaxy_gateway.android.handlers" not in sys.modules:
        ga_handlers = types.ModuleType("galaxy_gateway.android.handlers")
        ga_handlers.__path__ = []
        sys.modules["galaxy_gateway.android.handlers"] = ga_handlers

    # Stub MessageBuilder (only needs the class name; tests mock it away).
    if "galaxy_gateway.android.message_builder" not in sys.modules:
        mb = types.ModuleType("galaxy_gateway.android.message_builder")
        mb.MessageBuilder = type("MessageBuilder", (), {})
        sys.modules["galaxy_gateway.android.message_builder"] = mb

    spec = importlib.util.spec_from_file_location(
        mod_key,
        "galaxy_gateway/android/handlers/goal_execution.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_goal_result_message(
    task_id: str = "t1",
    device_id: str = "dev1",
    status: str = "completed",
    result: str = "done",
    trace_id: str = "trace1",
    group_id: str = None,
    subtask_index: int = None,
    route_mode: str = "cross_device",
    session_id: str = "sess1",
) -> dict:
    payload: dict = {
        "task_id": task_id,
        "device_id": device_id,
        "status": status,
        "result": result,
        "trace_id": trace_id,
        "route_mode": route_mode,
        "session_id": session_id,
    }
    if group_id is not None:
        payload["group_id"] = group_id
    if subtask_index is not None:
        payload["subtask_index"] = subtask_index
    return {
        "type": "goal_execution_result",
        "device_id": device_id,
        "payload": payload,
    }


# ---------------------------------------------------------------------------
# 1. handle_goal_execution_result — correct store_task_result call signature
# ---------------------------------------------------------------------------

class TestHandleGoalExecutionResultMemoryWrite:
    """store_task_result must be called with (task_id, device_id, route_mode, result: dict)."""

    @pytest.mark.asyncio
    async def test_store_task_result_called_with_dict(self):
        mod = _load_goal_execution_handler()

        captured: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            captured.append({
                "task_id": task_id,
                "device_id": device_id,
                "route_mode": route_mode,
                "result": result,
                "session_id": session_id,
            })

        bridge = MagicMock()
        ws = MagicMock()
        msg = _make_goal_result_message(task_id="task123", status="completed")

        with patch.object(mod, "store_task_result", _fake_store):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert len(captured) == 1
        call = captured[0]
        assert call["task_id"] == "task123"
        assert call["device_id"] == "dev1"
        # result must be a dict, not a string
        assert isinstance(call["result"], dict), "result must be a dict"
        assert call["result"]["status"] == "completed"
        assert call["result"]["task_type"] == "goal_execution_result"

    @pytest.mark.asyncio
    async def test_store_task_result_route_mode_forwarded(self):
        mod = _load_goal_execution_handler()

        captured: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            captured.append(route_mode)

        msg = _make_goal_result_message(route_mode="local")
        bridge = MagicMock()
        ws = MagicMock()

        with patch.object(mod, "store_task_result", _fake_store):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert captured[0] == "local"

    @pytest.mark.asyncio
    async def test_store_task_result_unavailable_does_not_raise(self):
        """When store_task_result is None the handler should not raise."""
        mod = _load_goal_execution_handler()

        msg = _make_goal_result_message()
        bridge = MagicMock()
        ws = MagicMock()

        with patch.object(mod, "store_task_result", None):
            # Should complete without exception
            await mod.handle_goal_execution_result(bridge, ws, msg)

    @pytest.mark.asyncio
    async def test_result_dict_contains_result_summary(self):
        """The result dict must carry the result text from the payload."""
        mod = _load_goal_execution_handler()

        captured: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            captured.append(result)

        msg = _make_goal_result_message(result="screen captured successfully")
        bridge = MagicMock()
        ws = MagicMock()

        with patch.object(mod, "store_task_result", _fake_store):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert captured[0]["result_summary"] == "screen captured successfully"


# ---------------------------------------------------------------------------
# 2. on_goal_execution_result — TaskMemory write and session injection
# ---------------------------------------------------------------------------

class TestOnGoalExecutionResult:
    """DesktopPresenceRuntime.on_goal_execution_result must write to TaskMemory
    and inject result into matching RuntimeSession."""

    @pytest.mark.asyncio
    async def test_writes_to_task_memory(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        mem_writes: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            mem_writes.append({"task_id": task_id, "result": result})

        import core.openclawd_memory_backflow as backflow_mod
        orig = backflow_mod.store_task_result
        backflow_mod.store_task_result = _fake_store
        try:
            await runtime.on_goal_execution_result(
                task_id="t99",
                device_id="dev_x",
                status="completed",
                result="execution finished",
                trace_id="trace_abc",
            )
        finally:
            backflow_mod.store_task_result = orig

        assert len(mem_writes) == 1
        assert mem_writes[0]["task_id"] == "t99"
        assert isinstance(mem_writes[0]["result"], dict)
        assert mem_writes[0]["result"]["status"] == "completed"
        assert mem_writes[0]["result"]["task_type"] == "goal_execution_result"

    @pytest.mark.asyncio
    async def test_caches_result_in_goal_results(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        import core.openclawd_memory_backflow as backflow_mod
        orig = backflow_mod.store_task_result
        backflow_mod.store_task_result = AsyncMock()
        try:
            await runtime.on_goal_execution_result(
                task_id="task_cache_1",
                device_id="dev1",
                status="success",
                result="result text",
                trace_id="tr1",
            )
        finally:
            backflow_mod.store_task_result = orig

        assert hasattr(runtime, "_goal_results")
        assert "task_cache_1" in runtime._goal_results
        cached = runtime._goal_results["task_cache_1"]
        assert cached["status"] == "success"
        assert cached["device_id"] == "dev1"

    @pytest.mark.asyncio
    async def test_injects_into_matching_session(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime, RuntimeSession

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)

        session = RuntimeSession.__new__(RuntimeSession)
        session.runtime_session_id = "session_trace_abc"
        session.trace_id = "session_trace_abc"

        runtime._active_sessions = {"session_trace_abc": session}

        import core.openclawd_memory_backflow as backflow_mod
        orig = backflow_mod.store_task_result
        backflow_mod.store_task_result = AsyncMock()
        try:
            await runtime.on_goal_execution_result(
                task_id="t_inject",
                device_id="dev_inject",
                status="completed",
                result="injection result",
                trace_id="session_trace_abc",
            )
        finally:
            backflow_mod.store_task_result = orig

        assert hasattr(session, "goal_execution_results")
        assert "t_inject" in session.goal_execution_results
        injected = session.goal_execution_results["t_inject"]
        assert injected["status"] == "completed"
        assert injected["device_id"] == "dev_inject"

    @pytest.mark.asyncio
    async def test_no_session_match_does_not_raise(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime, RuntimeSession

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)

        other_session = RuntimeSession.__new__(RuntimeSession)
        other_session.runtime_session_id = "other_session"
        other_session.trace_id = "other_session"

        runtime._active_sessions = {"other_session": other_session}

        import core.openclawd_memory_backflow as backflow_mod
        orig = backflow_mod.store_task_result
        backflow_mod.store_task_result = AsyncMock()
        try:
            # trace_id doesn't match any session — should not raise
            await runtime.on_goal_execution_result(
                task_id="t_no_match",
                device_id="dev1",
                status="completed",
                result="ok",
                trace_id="nonexistent_trace",
            )
        finally:
            backflow_mod.store_task_result = orig

        # other_session should not be modified
        assert not hasattr(other_session, "goal_execution_results")

    @pytest.mark.asyncio
    async def test_multiple_results_cached_independently(self):
        """Multiple calls accumulate in _goal_results keyed by task_id."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}

        import core.openclawd_memory_backflow as backflow_mod
        orig = backflow_mod.store_task_result
        backflow_mod.store_task_result = AsyncMock()
        try:
            await runtime.on_goal_execution_result(
                task_id="task_a", device_id="d1",
                status="completed", result="r1", trace_id="tr1",
            )
            await runtime.on_goal_execution_result(
                task_id="task_b", device_id="d2",
                status="failed", result="r2", trace_id="tr2",
            )
        finally:
            backflow_mod.store_task_result = orig

        assert "task_a" in runtime._goal_results
        assert "task_b" in runtime._goal_results
        assert runtime._goal_results["task_a"]["status"] == "completed"
        assert runtime._goal_results["task_b"]["status"] == "failed"


# ---------------------------------------------------------------------------
# 3. Parallel group aggregation
# ---------------------------------------------------------------------------

class TestParallelGroupAggregation:
    """handle_goal_execution_result should record into parallel tracker and
    trigger aggregated TaskMemory write when group is complete."""

    @pytest.mark.asyncio
    async def test_records_into_parallel_tracker(self):
        mod = _load_goal_execution_handler()

        recorded: list = []

        async def _fake_record(payload):
            recorded.append(dict(payload))

        msg = _make_goal_result_message(
            task_id="t_par",
            status="completed",
            group_id="grp_1",
            subtask_index=0,
        )
        bridge = MagicMock()
        ws = MagicMock()

        with (
            patch.object(mod, "store_task_result", AsyncMock()),
            patch.object(mod, "record_parallel_fields", _fake_record),
            patch.object(mod, "_get_parallel_tracker", None),
        ):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert len(recorded) == 1
        assert recorded[0]["group_id"] == "grp_1"
        assert recorded[0]["subtask_index"] == 0
        assert recorded[0]["status"] == "success"

    @pytest.mark.asyncio
    async def test_failed_status_mapped_to_failed(self):
        mod = _load_goal_execution_handler()

        recorded: list = []

        async def _fake_record(payload):
            recorded.append(dict(payload))

        msg = _make_goal_result_message(
            task_id="t_fail",
            status="failed",
            group_id="grp_fail",
            subtask_index=1,
        )
        bridge = MagicMock()
        ws = MagicMock()

        with (
            patch.object(mod, "store_task_result", AsyncMock()),
            patch.object(mod, "record_parallel_fields", _fake_record),
            patch.object(mod, "_get_parallel_tracker", None),
        ):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert recorded[0]["status"] == "failed"

    @pytest.mark.asyncio
    async def test_group_complete_writes_aggregated_memory(self):
        mod = _load_goal_execution_handler()
        from galaxy_gateway.orchestrator.parallel_tracker import (
            ParallelGroupStatus,
            ParallelSubtaskResult,
        )
        import time as _time

        mem_writes: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            mem_writes.append({"task_id": task_id, "result": result})

        # Finalized group status returned by tracker
        finalized = ParallelGroupStatus(
            group_id="grp_complete",
            status="success",
            results=[
                ParallelSubtaskResult(
                    group_id="grp_complete",
                    subtask_index=0,
                    status="success",
                    latency_ms=100,
                )
            ],
            started_at=_time.time() - 1.0,
            finished_at=_time.time(),
        )

        fake_tracker = MagicMock()
        fake_tracker.finalize_if_complete = AsyncMock(return_value=finalized)

        async def _fake_record_parallel(payload):
            pass

        def _fake_get_tracker():
            return fake_tracker

        msg = _make_goal_result_message(
            task_id="t_complete",
            status="completed",
            group_id="grp_complete",
            subtask_index=0,
        )
        bridge = MagicMock()
        ws = MagicMock()

        with (
            patch.object(mod, "store_task_result", _fake_store),
            patch.object(mod, "record_parallel_fields", _fake_record_parallel),
            patch.object(mod, "_get_parallel_tracker", _fake_get_tracker),
        ):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        # Individual result write + aggregated group write
        assert len(mem_writes) >= 2
        task_types = [w["result"]["task_type"] for w in mem_writes]
        assert "parallel_group_result" in task_types

        agg = next(w for w in mem_writes if w["result"]["task_type"] == "parallel_group_result")
        assert agg["result"]["group_id"] == "grp_complete"
        assert agg["result"]["status"] == "success"

    @pytest.mark.asyncio
    async def test_group_not_yet_complete_no_aggregated_write(self):
        """When finalize_if_complete returns None, no aggregated write happens."""
        mod = _load_goal_execution_handler()

        mem_writes: list = []

        async def _fake_store(task_id, device_id, route_mode, result, session_id=None):
            mem_writes.append(result)

        fake_tracker = MagicMock()
        fake_tracker.finalize_if_complete = AsyncMock(return_value=None)

        async def _fake_record_parallel(payload):
            pass

        def _fake_get_tracker():
            return fake_tracker

        msg = _make_goal_result_message(
            task_id="t_partial",
            status="completed",
            group_id="grp_partial",
            subtask_index=0,
        )
        bridge = MagicMock()
        ws = MagicMock()

        with (
            patch.object(mod, "store_task_result", _fake_store),
            patch.object(mod, "record_parallel_fields", _fake_record_parallel),
            patch.object(mod, "_get_parallel_tracker", _fake_get_tracker),
        ):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        # Only the individual subtask write, no aggregate
        task_types = [r.get("task_type") for r in mem_writes]
        assert "parallel_group_result" not in task_types

    @pytest.mark.asyncio
    async def test_no_group_id_skips_parallel_tracker(self):
        """When group_id is absent, parallel tracker should not be called."""
        mod = _load_goal_execution_handler()

        recorded: list = []

        async def _fake_record(payload):
            recorded.append(payload)

        msg = _make_goal_result_message(task_id="t_no_group")
        bridge = MagicMock()
        ws = MagicMock()

        with (
            patch.object(mod, "store_task_result", AsyncMock()),
            patch.object(mod, "record_parallel_fields", _fake_record),
        ):
            await mod.handle_goal_execution_result(bridge, ws, msg)

        assert len(recorded) == 0


# ---------------------------------------------------------------------------
# 4. Reconciler maps goal_execution_result → final_result
# ---------------------------------------------------------------------------

class TestReconcilerGoalResultMapping:
    """goal_execution_result with 'completed' status must map to final_result."""

    def test_completed_maps_to_final_result(self):
        from core.android_execution_signal_reconciler import (
            normalize_android_message_to_signal_kind,
            AndroidSignalKind,
        )
        kind = normalize_android_message_to_signal_kind(
            "goal_execution_result", "completed"
        )
        assert kind == AndroidSignalKind.final_result

    def test_success_maps_to_final_result(self):
        from core.android_execution_signal_reconciler import (
            normalize_android_message_to_signal_kind,
            AndroidSignalKind,
        )
        kind = normalize_android_message_to_signal_kind(
            "goal_execution_result", "success"
        )
        assert kind == AndroidSignalKind.final_result

    def test_failed_maps_to_error(self):
        from core.android_execution_signal_reconciler import (
            normalize_android_message_to_signal_kind,
            AndroidSignalKind,
        )
        kind = normalize_android_message_to_signal_kind(
            "goal_execution_result", "failed"
        )
        assert kind == AndroidSignalKind.error

    def test_cancelled_maps_to_cancelled(self):
        from core.android_execution_signal_reconciler import (
            normalize_android_message_to_signal_kind,
            AndroidSignalKind,
        )
        kind = normalize_android_message_to_signal_kind(
            "goal_execution_result", "cancelled"
        )
        assert kind == AndroidSignalKind.cancelled

    def test_task_result_and_goal_execution_result_both_canonical_final(self):
        """Both task_result and goal_execution_result without status → final_result."""
        from core.android_execution_signal_reconciler import (
            normalize_android_message_to_signal_kind,
            AndroidSignalKind,
        )
        task_result_kind = normalize_android_message_to_signal_kind("task_result", "")
        goal_kind = normalize_android_message_to_signal_kind("goal_execution_result", "")
        assert task_result_kind == AndroidSignalKind.final_result
        assert goal_kind == AndroidSignalKind.final_result
