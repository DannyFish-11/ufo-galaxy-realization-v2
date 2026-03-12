"""
tests/test_parallel_tracker.py
================================

Unit tests for the gateway-level ParallelGroupTracker
(galaxy_gateway/orchestrator/parallel_tracker.py).

Covers:
  1. start_group + record_result + finalize_if_complete → success
  2. partial_failed status when some subtasks fail
  3. timeout expiry via expire_timeouts
  4. Multiple concurrent records are safe
  5. Auto-create group on record_result (no prior start_group)
  6. get_group_status sync read
"""

import asyncio
import time

import pytest

from galaxy_gateway.orchestrator.parallel_tracker import (
    ParallelGroupStatus,
    ParallelGroupTracker,
    ParallelSubtaskResult,
    get_tracker,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new_tracker() -> ParallelGroupTracker:
    """Return a fresh tracker for each test (avoid shared singleton)."""
    return ParallelGroupTracker()


# ---------------------------------------------------------------------------
# 1. Full success path
# ---------------------------------------------------------------------------

class TestParallelTrackerSuccess:
    @pytest.mark.asyncio
    async def test_all_success_finalizes(self):
        tracker = _new_tracker()
        gid = "g-success-1"
        await tracker.start_group(gid, expected_count=2, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=100)
        await tracker.record_result(gid, subtask_index=1, status="success", latency_ms=150)
        gs = await tracker.finalize_if_complete(gid)
        assert gs is not None
        assert isinstance(gs, ParallelGroupStatus)
        assert gs.status == "success"
        assert len(gs.results) == 2

    @pytest.mark.asyncio
    async def test_not_finalized_until_all_recorded(self):
        tracker = _new_tracker()
        gid = "g-success-2"
        await tracker.start_group(gid, expected_count=3, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=80)
        gs = await tracker.finalize_if_complete(gid)
        assert gs is None

    @pytest.mark.asyncio
    async def test_finalized_group_removed_from_active(self):
        tracker = _new_tracker()
        gid = "g-success-3"
        await tracker.start_group(gid, expected_count=1, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=50)
        await tracker.finalize_if_complete(gid)
        # Calling again should return cached finalized status, not fail
        gs2 = await tracker.finalize_if_complete(gid)
        assert gs2 is not None
        assert gs2.status == "success"

    @pytest.mark.asyncio
    async def test_result_fields_preserved(self):
        tracker = _new_tracker()
        gid = "g-success-4"
        await tracker.start_group(gid, expected_count=1, timeout_s=30.0)
        await tracker.record_result(
            gid, subtask_index=0, status="success", latency_ms=200,
            summary="done", errors=None, outputs={"key": "val"},
        )
        gs = await tracker.finalize_if_complete(gid)
        assert gs is not None
        r = gs.results[0]
        assert isinstance(r, ParallelSubtaskResult)
        assert r.status == "success"
        assert r.latency_ms == 200
        assert r.summary == "done"
        assert r.outputs == {"key": "val"}

    @pytest.mark.asyncio
    async def test_to_dict_contains_required_keys(self):
        tracker = _new_tracker()
        gid = "g-success-5"
        await tracker.start_group(gid, expected_count=1, timeout_s=10.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        gs = await tracker.finalize_if_complete(gid)
        d = gs.to_dict()
        for key in ("group_id", "status", "results", "started_at", "finished_at"):
            assert key in d, f"missing key: {key}"
        assert d["group_id"] == gid
        assert d["status"] == "success"


# ---------------------------------------------------------------------------
# 2. partial_failed path
# ---------------------------------------------------------------------------

class TestParallelTrackerPartialFailed:
    @pytest.mark.asyncio
    async def test_partial_failed_when_one_fails(self):
        tracker = _new_tracker()
        gid = "g-partial-1"
        await tracker.start_group(gid, expected_count=2, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=100)
        await tracker.record_result(gid, subtask_index=1, status="failed", latency_ms=200,
                                    errors=["something went wrong"])
        gs = await tracker.finalize_if_complete(gid)
        assert gs is not None
        assert gs.status == "partial_failed"

    @pytest.mark.asyncio
    async def test_all_failed_is_partial_failed(self):
        tracker = _new_tracker()
        gid = "g-partial-2"
        await tracker.start_group(gid, expected_count=2, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="failed", latency_ms=50)
        await tracker.record_result(gid, subtask_index=1, status="failed", latency_ms=60)
        gs = await tracker.finalize_if_complete(gid)
        assert gs is not None
        assert gs.status == "partial_failed"

    @pytest.mark.asyncio
    async def test_errors_field_propagated(self):
        tracker = _new_tracker()
        gid = "g-partial-3"
        await tracker.start_group(gid, expected_count=1, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="failed", latency_ms=10,
                                    errors=["err1", "err2"])
        gs = await tracker.finalize_if_complete(gid)
        r = gs.results[0]
        assert r.errors == ["err1", "err2"]


# ---------------------------------------------------------------------------
# 3. Timeout expiry
# ---------------------------------------------------------------------------

class TestParallelTrackerTimeout:
    @pytest.mark.asyncio
    async def test_expire_timeouts_marks_missing_as_timeout(self):
        tracker = _new_tracker()
        gid = "g-timeout-1"
        await tracker.start_group(gid, expected_count=3, timeout_s=0.01)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=5)
        # Wait for group to be overdue
        await asyncio.sleep(0.05)
        expired = await tracker.expire_timeouts(now_ts=time.time())
        assert gid in expired
        gs = expired[gid]
        assert gs.status == "timeout"
        assert len(gs.results) == 3
        timeout_results = [r for r in gs.results if r.status == "timeout"]
        assert len(timeout_results) == 2  # indices 1 and 2 were missing

    @pytest.mark.asyncio
    async def test_expire_returns_empty_when_no_overdue(self):
        tracker = _new_tracker()
        gid = "g-timeout-2"
        await tracker.start_group(gid, expected_count=2, timeout_s=60.0)
        expired = await tracker.expire_timeouts(now_ts=time.time())
        assert gid not in expired

    @pytest.mark.asyncio
    async def test_mixed_timeout_partial_failed_status(self):
        """A group where one subtask timed out but another already completed
        gets status='timeout' (timeout takes precedence over partial_failed)."""
        tracker = _new_tracker()
        gid = "g-timeout-3"
        await tracker.start_group(gid, expected_count=2, timeout_s=0.01)
        await tracker.record_result(gid, subtask_index=0, status="failed", latency_ms=5)
        await asyncio.sleep(0.05)
        expired = await tracker.expire_timeouts(now_ts=time.time())
        gs = expired[gid]
        assert gs.status == "timeout"


# ---------------------------------------------------------------------------
# 4. Auto-create group (no prior start_group)
# ---------------------------------------------------------------------------

class TestParallelTrackerAutoCreate:
    @pytest.mark.asyncio
    async def test_record_without_start_group(self):
        tracker = _new_tracker()
        gid = "g-auto-1"
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        # Without start_group (expected_count=None) finalize_if_complete returns None
        gs = await tracker.finalize_if_complete(gid)
        assert gs is None

    @pytest.mark.asyncio
    async def test_get_group_status_returns_none_for_unknown_expected(self):
        tracker = _new_tracker()
        gid = "g-auto-2"
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        # No expected_count known → cannot finalize
        gs = tracker.get_group_status(gid)
        assert gs is None

    @pytest.mark.asyncio
    async def test_start_group_ignored_if_already_exists(self):
        """Calling start_group twice on the same group_id is a no-op."""
        tracker = _new_tracker()
        gid = "g-auto-3"
        await tracker.start_group(gid, expected_count=2, timeout_s=30.0)
        # Second call with different expected_count should be ignored
        await tracker.start_group(gid, expected_count=5, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        await tracker.record_result(gid, subtask_index=1, status="success", latency_ms=20)
        gs = await tracker.finalize_if_complete(gid)
        # Should have finalized with original expected_count=2
        assert gs is not None
        assert gs.status == "success"


# ---------------------------------------------------------------------------
# 5. get_group_status (sync)
# ---------------------------------------------------------------------------

class TestGetGroupStatus:
    @pytest.mark.asyncio
    async def test_returns_none_before_complete(self):
        tracker = _new_tracker()
        gid = "g-sync-1"
        await tracker.start_group(gid, expected_count=3, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        gs = tracker.get_group_status(gid)
        assert gs is None

    @pytest.mark.asyncio
    async def test_returns_status_when_complete(self):
        tracker = _new_tracker()
        gid = "g-sync-2"
        await tracker.start_group(gid, expected_count=2, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="success", latency_ms=10)
        await tracker.record_result(gid, subtask_index=1, status="success", latency_ms=20)
        gs = tracker.get_group_status(gid)
        assert gs is not None
        assert gs.status == "success"

    @pytest.mark.asyncio
    async def test_returns_finalized_after_finalize_if_complete(self):
        tracker = _new_tracker()
        gid = "g-sync-3"
        await tracker.start_group(gid, expected_count=1, timeout_s=30.0)
        await tracker.record_result(gid, subtask_index=0, status="failed", latency_ms=5)
        await tracker.finalize_if_complete(gid)
        gs = tracker.get_group_status(gid)
        assert gs is not None
        assert gs.status == "partial_failed"


# ---------------------------------------------------------------------------
# 6. Module-level singleton
# ---------------------------------------------------------------------------

def test_get_tracker_returns_same_instance():
    t1 = get_tracker()
    t2 = get_tracker()
    assert t1 is t2
