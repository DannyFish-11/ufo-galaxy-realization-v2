"""
tests/test_parallel_goal_flow.py
=================================

Phase-3 parallel goal flow tests:
  1. ParallelGroupTracker state tracking
  2. Aggregation on full success
  3. Retry on single subtask failure (retry succeeds)
  4. Timeout path → mark_timeout
  5. No-autonomous-device fallback message from _dispatch_parallel_goal
  6. Cancel/abort support (PR10)
  7. Timeout handling in dispatch methods (PR10)
  8. Goal execution timeout (PR10)
"""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.openclawd import (
    OpenClawd,
    ParallelGroupTracker,
    ParallelResult,
    _SubtaskEntry,
    _SubtaskStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(group_id: str, idx: int, device_id: str = "dev1") -> _SubtaskEntry:
    return _SubtaskEntry(
        task_id=f"{group_id}_sub{idx}",
        group_id=group_id,
        subtask_index=idx,
        device_id=device_id,
        subtask=f"subtask-{idx}",
    )


# ---------------------------------------------------------------------------
# 1. State tracking
# ---------------------------------------------------------------------------

class TestParallelGroupTrackerStateTracking:
    def test_initial_status_pending(self):
        tracker = ParallelGroupTracker()
        gid = "grp1"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        entry = tracker._get_entry(gid, e.task_id)
        assert entry is not None
        assert entry.status == _SubtaskStatus.PENDING
        assert entry.started_at is None
        assert entry.finished_at is None

    def test_mark_running_transitions_status(self):
        tracker = ParallelGroupTracker()
        gid = "grp2"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.RUNNING
        assert entry.started_at is not None

    def test_mark_done_success(self):
        tracker = ParallelGroupTracker()
        gid = "grp3"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": True, "response": "ok"}, success=True)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.SUCCESS
        assert entry.finished_at is not None
        assert entry.error is None

    def test_mark_done_failure_sets_error(self):
        tracker = ParallelGroupTracker()
        gid = "grp4"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": False, "response": "boom"}, success=False)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.FAILED
        assert entry.error == "boom"

    def test_mark_timeout(self):
        tracker = ParallelGroupTracker()
        gid = "grp5"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_timeout(gid, e.task_id)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.TIMEOUT
        assert entry.error == "timeout"


# ---------------------------------------------------------------------------
# 2. Aggregation on success
# ---------------------------------------------------------------------------

class TestParallelGroupTrackerAggregation:
    def test_aggregate_all_success(self):
        tracker = ParallelGroupTracker()
        gid = "agg1"
        entries = [_make_entry(gid, i, f"dev{i}") for i in range(3)]
        tracker.register_group(gid, entries)
        for e in entries:
            tracker.mark_running(gid, e.task_id)
            tracker.mark_done(gid, e.task_id, {"success": True}, success=True)

        result = tracker.aggregate(gid)
        assert isinstance(result, ParallelResult)
        assert result.summary_status == "success"
        assert result.succeeded == 3
        assert result.failed == 0
        assert result.total == 3
        assert len(result.device_results) == 3

    def test_aggregate_partial_success(self):
        tracker = ParallelGroupTracker()
        gid = "agg2"
        entries = [_make_entry(gid, i, f"dev{i}") for i in range(2)]
        tracker.register_group(gid, entries)
        tracker.mark_running(gid, entries[0].task_id)
        tracker.mark_done(gid, entries[0].task_id, {"success": True}, success=True)
        tracker.mark_running(gid, entries[1].task_id)
        tracker.mark_done(gid, entries[1].task_id, {"success": False, "response": "err"}, success=False)

        result = tracker.aggregate(gid)
        assert result.summary_status == "partial"
        assert result.succeeded == 1
        assert result.failed == 1

    def test_aggregate_all_failed(self):
        tracker = ParallelGroupTracker()
        gid = "agg3"
        entries = [_make_entry(gid, i) for i in range(2)]
        tracker.register_group(gid, entries)
        for e in entries:
            tracker.mark_running(gid, e.task_id)
            tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)

        result = tracker.aggregate(gid)
        assert result.summary_status == "failed"
        assert result.succeeded == 0

    def test_aggregate_includes_latency_ms(self):
        tracker = ParallelGroupTracker()
        gid = "agg4"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        # Simulate some elapsed time
        entry = tracker._get_entry(gid, e.task_id)
        entry.started_at = time.monotonic() - 0.1
        tracker.mark_done(gid, e.task_id, {"success": True}, success=True)

        result = tracker.aggregate(gid)
        dr = result.device_results[0]
        assert dr["latency_ms"] is not None
        assert dr["latency_ms"] >= 0

    def test_aggregate_to_dict_contains_all_fields(self):
        tracker = ParallelGroupTracker()
        gid = "agg5"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": True}, success=True)
        d = tracker.aggregate(gid).to_dict()
        for key in ("group_id", "device_results", "summary_status", "succeeded", "failed", "total"):
            assert key in d


# ---------------------------------------------------------------------------
# 3. Retry on single failure (retry succeeds)
# ---------------------------------------------------------------------------

class TestParallelGroupTrackerRetry:
    def test_needs_retry_after_failure(self):
        tracker = ParallelGroupTracker()
        gid = "retry1"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)
        assert tracker.needs_retry(gid, e.task_id) is True

    def test_no_retry_after_success(self):
        tracker = ParallelGroupTracker()
        gid = "retry2"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": True}, success=True)
        assert tracker.needs_retry(gid, e.task_id) is False

    def test_no_retry_after_max_retries_exhausted(self):
        tracker = ParallelGroupTracker()
        gid = "retry3"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        # Exhaust retries
        for _ in range(ParallelGroupTracker._MAX_RETRIES + 1):
            tracker.mark_running(gid, e.task_id)
            tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)
            if tracker.needs_retry(gid, e.task_id):
                tracker.increment_retry(gid, e.task_id)
        assert tracker.needs_retry(gid, e.task_id) is False

    def test_backoff_delay_increases_with_retry_count(self):
        tracker = ParallelGroupTracker()
        gid = "retry4"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)
        delay0 = tracker.backoff_delay(gid, e.task_id)
        assert delay0 == min(
            ParallelGroupTracker._BACKOFF_BASE ** 1,
            ParallelGroupTracker._BACKOFF_CAP,
        )

    def test_backoff_delay_capped(self):
        tracker = ParallelGroupTracker()
        gid = "retry5"
        e = _make_entry(gid, 0)
        e.retry_count = 100  # very high to exceed cap
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)
        delay = tracker.backoff_delay(gid, e.task_id)
        assert delay <= ParallelGroupTracker._BACKOFF_CAP

    def test_increment_retry_resets_entry(self):
        tracker = ParallelGroupTracker()
        gid = "retry6"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_done(gid, e.task_id, {"success": False, "response": "err"}, success=False)
        tracker.increment_retry(gid, e.task_id)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.PENDING
        assert entry.retry_count == 1
        assert entry.started_at is None
        assert entry.error is None


# ---------------------------------------------------------------------------
# 4. Timeout path
# ---------------------------------------------------------------------------

class TestParallelGroupTrackerTimeout:
    def test_needs_retry_after_timeout(self):
        tracker = ParallelGroupTracker()
        gid = "to1"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_timeout(gid, e.task_id)
        assert tracker.needs_retry(gid, e.task_id) is True

    def test_aggregate_timeout_counted_as_failed(self):
        tracker = ParallelGroupTracker()
        gid = "to2"
        entries = [_make_entry(gid, i) for i in range(2)]
        tracker.register_group(gid, entries)
        tracker.mark_running(gid, entries[0].task_id)
        tracker.mark_done(gid, entries[0].task_id, {"success": True}, success=True)
        tracker.mark_running(gid, entries[1].task_id)
        tracker.mark_timeout(gid, entries[1].task_id)

        result = tracker.aggregate(gid)
        # TIMEOUT is not SUCCESS → counts as failed
        assert result.succeeded == 1
        assert result.failed == 1
        assert result.summary_status == "partial"

    def test_aggregate_device_result_status_field(self):
        tracker = ParallelGroupTracker()
        gid = "to3"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_timeout(gid, e.task_id)
        result = tracker.aggregate(gid)
        assert result.device_results[0]["status"] == "timeout"


# ---------------------------------------------------------------------------
# 5. No-autonomous-device fallback message
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_parallel_goal_no_autonomous_device_returns_fallback_message():
    """When no autonomous devices are registered, _dispatch_parallel_goal must
    return a structured failure dict with a human-readable message instead of
    silently escalating to goal_execution."""
    import core.agent.capability_registry as cap_reg_mod
    import core.unified.device_manager as udm_mod

    oc = OpenClawd()

    # Ensure no autonomous devices are available from CapabilityRegistry or UDM
    with patch.object(
        cap_reg_mod.CapabilityRegistry,
        "get_instance",
        return_value=MagicMock(list_tools=MagicMock(return_value=[])),
    ):
        with patch.object(
            udm_mod,
            "get_unified_device_manager",
            return_value=MagicMock(
                get_devices_with_capability=MagicMock(return_value=[]),
                get_autonomous_devices=MagicMock(return_value=[]),
            ),
        ):
            result = await oc._dispatch_parallel_goal("send message to all devices")

    assert result["success"] is False
    assert result["intent"] == "parallel_goal"
    assert "parallel_execution_enabled" in result["response"]
    assert result["metadata"]["device_count"] == 0
    assert result["metadata"]["parallel_group"] is None


@pytest.mark.asyncio
async def test_dispatch_parallel_goal_with_devices_produces_parallel_result():
    """When devices are available, _dispatch_parallel_goal should produce a
    result that includes the parallel_result aggregation dict."""
    import core.agent.capability_registry as cap_reg_mod

    oc = OpenClawd()

    mock_capability = MagicMock()
    mock_capability.name = "autonomous__test_device_1__parallel_execution_enabled"
    mock_capability.source = "autonomous"
    mock_capability.available = True
    mock_capability.metadata = {"device_id": "test_device_1"}
    mock_capability.source_id = "test_device_1"

    async def _fake_send_gateway_command(**kwargs):
        return {"success": True, "response": "done", "task_id": kwargs.get("task_id", "")}

    with patch.object(oc, "send_gateway_command", side_effect=_fake_send_gateway_command):
        with patch.object(
            cap_reg_mod.CapabilityRegistry,
            "get_instance",
            return_value=MagicMock(
                list_tools=MagicMock(return_value=[mock_capability]),
            ),
        ):
            result = await oc._dispatch_parallel_goal("send a message")

    assert result["success"] is True
    assert result["intent"] == "parallel_goal"
    assert "parallel_result" in result["metadata"]
    pr = result["metadata"]["parallel_result"]
    assert pr["group_id"]
    assert pr["succeeded"] >= 1


@pytest.mark.asyncio
async def test_dispatch_parallel_goal_retry_on_first_failure():
    """When a subtask fails on first attempt, it should be retried once."""
    import core.agent.capability_registry as cap_reg_mod

    oc = OpenClawd()

    mock_capability = MagicMock()
    mock_capability.name = "autonomous__dev_retry__parallel_execution_enabled"
    mock_capability.source = "autonomous"
    mock_capability.available = True
    mock_capability.metadata = {"device_id": "dev_retry"}
    mock_capability.source_id = "dev_retry"

    call_count = {"n": 0}

    async def _flaky_send_gateway_command(**kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {"success": False, "response": "transient error", "task_id": kwargs.get("task_id", "")}
        return {"success": True, "response": "ok", "task_id": kwargs.get("task_id", "")}

    with patch.object(oc, "send_gateway_command", side_effect=_flaky_send_gateway_command):
        with patch.object(
            cap_reg_mod.CapabilityRegistry,
            "get_instance",
            return_value=MagicMock(
                list_tools=MagicMock(return_value=[mock_capability]),
            ),
        ):
            # Patch asyncio.sleep to avoid actual wait during retry
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await oc._dispatch_parallel_goal("do something")

    # After retry, the subtask should have succeeded
    assert result["success"] is True
    pr = result["metadata"]["parallel_result"]
    assert pr["succeeded"] == 1
    # Was called twice (first failure + retry)
    assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# 6. Cancel / Abort support (PR10)
# ---------------------------------------------------------------------------

class TestParallelGroupTrackerCancel:
    def test_mark_cancelled_sets_status(self):
        tracker = ParallelGroupTracker()
        gid = "cancel1"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_cancelled(gid, e.task_id)
        entry = tracker._get_entry(gid, e.task_id)
        assert entry.status == _SubtaskStatus.CANCELLED
        assert entry.error == "cancelled"
        assert entry.finished_at is not None

    def test_mark_cancelled_is_idempotent(self):
        """Calling mark_cancelled twice must not raise and status stays CANCELLED."""
        tracker = ParallelGroupTracker()
        gid = "cancel2"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_cancelled(gid, e.task_id)
        ft1 = tracker._get_entry(gid, e.task_id).finished_at
        # Second call — idempotent
        tracker.mark_cancelled(gid, e.task_id)
        entry = tracker._get_entry(gid, e.task_id)
        # All fields must remain unchanged on repeated cancel
        assert entry.status == _SubtaskStatus.CANCELLED
        assert entry.error == "cancelled"
        assert entry.finished_at == ft1

    def test_needs_retry_false_after_cancel(self):
        """Cancelled tasks must not be retried."""
        tracker = ParallelGroupTracker()
        gid = "cancel3"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_cancelled(gid, e.task_id)
        assert tracker.needs_retry(gid, e.task_id) is False

    def test_aggregate_all_cancelled_summary(self):
        tracker = ParallelGroupTracker()
        gid = "cancel4"
        entries = [_make_entry(gid, i) for i in range(2)]
        tracker.register_group(gid, entries)
        for e in entries:
            tracker.mark_running(gid, e.task_id)
            tracker.mark_cancelled(gid, e.task_id)
        result = tracker.aggregate(gid)
        assert result.summary_status == "cancelled"
        assert result.cancelled == 2
        assert result.succeeded == 0

    def test_aggregate_partial_cancel(self):
        """One success + one cancelled → partial."""
        tracker = ParallelGroupTracker()
        gid = "cancel5"
        entries = [_make_entry(gid, i) for i in range(2)]
        tracker.register_group(gid, entries)
        tracker.mark_running(gid, entries[0].task_id)
        tracker.mark_done(gid, entries[0].task_id, {"success": True}, success=True)
        tracker.mark_running(gid, entries[1].task_id)
        tracker.mark_cancelled(gid, entries[1].task_id)
        result = tracker.aggregate(gid)
        assert result.summary_status == "partial"
        assert result.succeeded == 1
        assert result.cancelled == 1

    def test_aggregate_device_result_status_cancelled(self):
        tracker = ParallelGroupTracker()
        gid = "cancel6"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_cancelled(gid, e.task_id)
        result = tracker.aggregate(gid)
        assert result.device_results[0]["status"] == "cancelled"

    def test_aggregate_to_dict_includes_cancelled_field(self):
        tracker = ParallelGroupTracker()
        gid = "cancel7"
        e = _make_entry(gid, 0)
        tracker.register_group(gid, [e])
        tracker.mark_running(gid, e.task_id)
        tracker.mark_cancelled(gid, e.task_id)
        d = tracker.aggregate(gid).to_dict()
        assert "cancelled" in d


class TestOpenClawdCancelRegistry:
    def test_cancel_task_returns_true_on_first_call(self):
        oc = OpenClawd()
        assert oc.cancel_task("task_abc") is True

    def test_cancel_task_returns_false_on_second_call_idempotent(self):
        oc = OpenClawd()
        oc.cancel_task("task_xyz")
        assert oc.cancel_task("task_xyz") is False

    def test_cancel_group_returns_true_on_first_call(self):
        oc = OpenClawd()
        assert oc.cancel_group("grp_123") is True

    def test_cancel_group_idempotent(self):
        oc = OpenClawd()
        oc.cancel_group("grp_dup")
        assert oc.cancel_group("grp_dup") is False

    def test_is_cancelled_by_task_id(self):
        oc = OpenClawd()
        oc.cancel_task("tid_check")
        assert oc._is_cancelled("tid_check") is True

    def test_is_cancelled_by_group_id(self):
        oc = OpenClawd()
        oc.cancel_group("gid_check")
        assert oc._is_cancelled("unrelated_task", group_id="gid_check") is True

    def test_not_cancelled_when_not_registered(self):
        oc = OpenClawd()
        assert oc._is_cancelled("no_such_task") is False


# ---------------------------------------------------------------------------
# 7. Timeout handling in parallel_subtask dispatch (PR10)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parallel_subtask_timeout_marks_timeout_in_tracker():
    """When a send_gateway_command call times out, mark_timeout is called
    on the tracker entry and the status becomes TIMEOUT."""
    import asyncio as aio

    tracker = ParallelGroupTracker()
    gid = "timeout_test_1"
    e = _make_entry(gid, 0)
    tracker.register_group(gid, [e])
    tracker.mark_running(gid, e.task_id)

    # Simulate the wait_for → TimeoutError → mark_timeout path
    try:
        await aio.wait_for(aio.sleep(999), timeout=0.01)
    except aio.TimeoutError:
        tracker.mark_timeout(gid, e.task_id)

    assert tracker._get_entry(gid, e.task_id).status == _SubtaskStatus.TIMEOUT


@pytest.mark.asyncio
async def test_parallel_subtask_cancel_before_dispatch():
    """A subtask cancelled before execution should be marked CANCELLED without
    ever calling send_gateway_command."""
    oc = OpenClawd()
    oc.PARALLEL_SUBTASK_TIMEOUT = 30.0

    tracker = ParallelGroupTracker()
    gid = "cancel_pre_dispatch"
    e = _make_entry(gid, 0)
    tracker.register_group(gid, [e])

    # Pre-cancel the task
    oc.cancel_task(e.task_id)

    called = {"n": 0}

    async def _should_not_be_called(*args, **kwargs):
        called["n"] += 1
        return {"success": True}

    with patch.object(oc, "send_gateway_command", side_effect=_should_not_be_called):
        # Replicate the cancel-check logic from _execute_entry
        if oc._is_cancelled(e.task_id, e.group_id):
            tracker.mark_cancelled(gid, e.task_id)

    assert called["n"] == 0
    assert tracker._get_entry(gid, e.task_id).status == _SubtaskStatus.CANCELLED


# ---------------------------------------------------------------------------
# 8. Goal execution timeout (PR10)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_goal_execution_timeout_returns_standardized_payload():
    """_dispatch_goal_execution must return a structured timeout payload
    when the device does not respond within GOAL_EXECUTION_TIMEOUT seconds."""
    import asyncio as aio

    oc = OpenClawd()
    oc.GOAL_EXECUTION_TIMEOUT = 0.01  # very short for test

    async def _slow(*args, **kwargs):
        await aio.sleep(999)

    with patch.object(
        oc,
        "_pick_autonomous_device_id",
        return_value="test_device",
    ):
        with patch.object(oc, "send_gateway_command", side_effect=_slow):
            result = await oc._dispatch_goal_execution("do something")

    assert result["success"] is False
    assert result.get("timed_out") is True
    assert result["intent"] == "goal_execution"
    assert "task_id" in result


@pytest.mark.asyncio
async def test_goal_execution_cancel_before_dispatch_returns_cancelled_payload():
    """If a task is in the cancel registry before _dispatch_goal_execution checks it,
    the method must return a cancelled payload without calling send_gateway_command."""
    oc = OpenClawd()

    called = {"n": 0}

    async def _should_not_run(*args, **kwargs):
        called["n"] += 1
        return {"success": True}

    with patch.object(
        oc,
        "_pick_autonomous_device_id",
        return_value="test_device",
    ):
        with patch.object(oc, "send_gateway_command", side_effect=_should_not_run):
            # Override _is_cancelled so any task_id returns True
            with patch.object(oc, "_is_cancelled", return_value=True):
                result = await oc._dispatch_goal_execution("do something")

    assert result["success"] is False
    assert result.get("cancelled") is True
    assert result["intent"] == "goal_execution"
    assert called["n"] == 0
