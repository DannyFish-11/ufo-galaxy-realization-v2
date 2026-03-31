"""tests/test_batch_pr7_openclawd_orchestration_decomposition.py

Comprehensive test suite for PR-7: Decomposition of core/openclawd.py into
core/orchestration/ submodules.

Covers:
- Authority sentinels
- Package import hygiene
- LifecycleManager behaviour
- ParallelGroupTracker (extraction verification)
- _SubtaskStatus enum preservation
- _is_local_device function
- SessionMemoryManager
- OpenClawd composition attributes
- All submodule class imports via core.orchestration
- Startup path: get_openclawd()
- ParallelResult.to_dict()
- Backward-compat: OpenClawd._cancel_registry not broken
- _SubtaskEntry dataclass
- ParallelGroupTracker.aggregate() scenarios
- LifecycleManager idempotency
- Submodule __init__.py re-exports
"""

from __future__ import annotations

import asyncio
import pytest

# ---------------------------------------------------------------------------
# 1. Authority sentinels
# ---------------------------------------------------------------------------


def test_openclawd_orchestration_authority_exists():
    from core.orchestration import OPENCLAWD_ORCHESTRATION_AUTHORITY
    assert isinstance(OPENCLAWD_ORCHESTRATION_AUTHORITY, str)
    assert OPENCLAWD_ORCHESTRATION_AUTHORITY


def test_lifecycle_manager_authority_sentinel():
    from core.orchestration.lifecycle import LIFECYCLE_MANAGER_AUTHORITY
    assert LIFECYCLE_MANAGER_AUTHORITY == "LIFECYCLE_MANAGER_AUTHORITY"


def test_state_manager_authority_sentinel():
    from core.orchestration.state import STATE_MANAGER_AUTHORITY
    assert STATE_MANAGER_AUTHORITY == "STATE_MANAGER_AUTHORITY"


def test_perception_pipeline_authority_sentinel():
    from core.orchestration.perception import PERCEPTION_PIPELINE_AUTHORITY
    assert PERCEPTION_PIPELINE_AUTHORITY == "PERCEPTION_PIPELINE_AUTHORITY"


def test_planning_pipeline_authority_sentinel():
    from core.orchestration.planning import PLANNING_PIPELINE_AUTHORITY
    assert PLANNING_PIPELINE_AUTHORITY == "PLANNING_PIPELINE_AUTHORITY"


def test_execution_pipeline_authority_sentinel():
    from core.orchestration.execution import EXECUTION_PIPELINE_AUTHORITY
    assert EXECUTION_PIPELINE_AUTHORITY == "EXECUTION_PIPELINE_AUTHORITY"


def test_reflection_pipeline_authority_sentinel():
    from core.orchestration.reflection import REFLECTION_PIPELINE_AUTHORITY
    assert REFLECTION_PIPELINE_AUTHORITY == "REFLECTION_PIPELINE_AUTHORITY"


def test_orchestration_helpers_authority_sentinel():
    from core.orchestration.helpers import ORCHESTRATION_HELPERS_AUTHORITY
    assert ORCHESTRATION_HELPERS_AUTHORITY == "ORCHESTRATION_HELPERS_AUTHORITY"


# ---------------------------------------------------------------------------
# 2. Package import hygiene
# ---------------------------------------------------------------------------


def test_core_orchestration_package_imports_cleanly():
    import core.orchestration as pkg
    assert hasattr(pkg, "OPENCLAWD_ORCHESTRATION_AUTHORITY")


def test_lifecycle_submodule_importable():
    import core.orchestration.lifecycle as m
    assert m is not None


def test_state_submodule_importable():
    import core.orchestration.state as m
    assert m is not None


def test_perception_submodule_importable():
    import core.orchestration.perception as m
    assert m is not None


def test_planning_submodule_importable():
    import core.orchestration.planning as m
    assert m is not None


def test_execution_submodule_importable():
    import core.orchestration.execution as m
    assert m is not None


def test_reflection_submodule_importable():
    import core.orchestration.reflection as m
    assert m is not None


def test_helpers_submodule_importable():
    import core.orchestration.helpers as m
    assert m is not None


# ---------------------------------------------------------------------------
# 3. LifecycleManager behaviour
# ---------------------------------------------------------------------------


def test_lifecycle_manager_instantiates():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    assert lm is not None


def test_lifecycle_manager_cancel_task_returns_true_first_time():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    assert lm.cancel_task("task_abc123") is True


def test_lifecycle_manager_cancel_task_idempotent():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    lm.cancel_task("task_abc123")
    assert lm.cancel_task("task_abc123") is False


def test_lifecycle_manager_cancel_group_returns_true_first_time():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    assert lm.cancel_group("grp_deadbeef") is True


def test_lifecycle_manager_cancel_group_idempotent():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    lm.cancel_group("grp_deadbeef")
    assert lm.cancel_group("grp_deadbeef") is False


def test_lifecycle_manager_is_cancelled_task():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    lm.cancel_task("task_x")
    assert lm.is_cancelled("task_x") is True


def test_lifecycle_manager_is_cancelled_group():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    lm.cancel_group("grp_y")
    assert lm.is_cancelled("other_task", group_id="grp_y") is True


def test_lifecycle_manager_is_cancelled_neither():
    from core.orchestration.lifecycle import LifecycleManager
    lm = LifecycleManager()
    assert lm.is_cancelled("task_not_cancelled") is False


def test_lifecycle_manager_authority_class_attr():
    from core.orchestration.lifecycle import LifecycleManager, LIFECYCLE_MANAGER_AUTHORITY
    assert LifecycleManager.LIFECYCLE_MANAGER_AUTHORITY == LIFECYCLE_MANAGER_AUTHORITY


def test_lifecycle_manager_finalise_plan_success():
    from core.orchestration.lifecycle import LifecycleManager

    class FakePlan:
        status = "running"

    plan = FakePlan()
    LifecycleManager.finalise_plan(plan, success=True)
    assert plan.status == "completed"


def test_lifecycle_manager_finalise_plan_failure():
    from core.orchestration.lifecycle import LifecycleManager

    class FakePlan:
        status = "running"

    plan = FakePlan()
    LifecycleManager.finalise_plan(plan, success=False)
    assert plan.status == "failed"


# ---------------------------------------------------------------------------
# 4. ParallelGroupTracker (post-extraction)
# ---------------------------------------------------------------------------


def _make_entry(group_id, task_id, idx, device="local"):
    from core.orchestration.lifecycle import _SubtaskEntry
    return _SubtaskEntry(
        task_id=task_id,
        group_id=group_id,
        subtask_index=idx,
        device_id=device,
        subtask="do something",
    )


def test_parallel_group_tracker_register():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    e = _make_entry("g1", "t1", 0)
    tracker.register_group("g1", [e])
    assert tracker._get_entry("g1", "t1") is not None


def test_parallel_group_tracker_mark_running():
    from core.orchestration.lifecycle import ParallelGroupTracker, _SubtaskStatus
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_running("g1", "t1")
    entry = tracker._get_entry("g1", "t1")
    assert entry.status == _SubtaskStatus.RUNNING
    assert entry.started_at is not None


def test_parallel_group_tracker_mark_done_success():
    from core.orchestration.lifecycle import ParallelGroupTracker, _SubtaskStatus
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_running("g1", "t1")
    tracker.mark_done("g1", "t1", {"response": "ok"}, success=True)
    entry = tracker._get_entry("g1", "t1")
    assert entry.status == _SubtaskStatus.SUCCESS
    assert entry.result == {"response": "ok"}


def test_parallel_group_tracker_mark_done_failure():
    from core.orchestration.lifecycle import ParallelGroupTracker, _SubtaskStatus
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_done("g1", "t1", {"error": "boom"}, success=False)
    entry = tracker._get_entry("g1", "t1")
    assert entry.status == _SubtaskStatus.FAILED
    assert entry.error == "boom"


def test_parallel_group_tracker_mark_cancelled_idempotent():
    from core.orchestration.lifecycle import ParallelGroupTracker, _SubtaskStatus
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_cancelled("g1", "t1")
    tracker.mark_cancelled("g1", "t1")
    entry = tracker._get_entry("g1", "t1")
    assert entry.status == _SubtaskStatus.CANCELLED


def test_parallel_group_tracker_aggregate_all_success():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    entries = [_make_entry("g1", f"t{i}", i) for i in range(3)]
    tracker.register_group("g1", entries)
    for e in entries:
        tracker.mark_running("g1", e.task_id)
        tracker.mark_done("g1", e.task_id, {"ok": True}, success=True)
    result = tracker.aggregate("g1")
    assert result.summary_status == "success"
    assert result.succeeded == 3
    assert result.failed == 0
    assert result.cancelled == 0
    assert result.total == 3


def test_parallel_group_tracker_aggregate_partial():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    entries = [_make_entry("g1", f"t{i}", i) for i in range(3)]
    tracker.register_group("g1", entries)
    tracker.mark_done("g1", "t0", {"ok": True}, success=True)
    tracker.mark_done("g1", "t1", {"error": "x"}, success=False)
    tracker.mark_done("g1", "t2", {"ok": True}, success=True)
    result = tracker.aggregate("g1")
    assert result.summary_status == "partial"
    assert result.succeeded == 2


def test_parallel_group_tracker_aggregate_failed():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    entries = [_make_entry("g1", f"t{i}", i) for i in range(2)]
    tracker.register_group("g1", entries)
    for e in entries:
        tracker.mark_done("g1", e.task_id, {"error": "err"}, success=False)
    result = tracker.aggregate("g1")
    assert result.summary_status == "failed"


def test_parallel_group_tracker_aggregate_cancelled():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    entries = [_make_entry("g1", f"t{i}", i) for i in range(2)]
    tracker.register_group("g1", entries)
    for e in entries:
        tracker.mark_cancelled("g1", e.task_id)
    result = tracker.aggregate("g1")
    assert result.summary_status == "cancelled"
    assert result.cancelled == 2


# ---------------------------------------------------------------------------
# 5. _SubtaskStatus enum values preserved
# ---------------------------------------------------------------------------


def test_subtask_status_values():
    from core.orchestration.lifecycle import _SubtaskStatus
    assert _SubtaskStatus.PENDING == "pending"
    assert _SubtaskStatus.RUNNING == "running"
    assert _SubtaskStatus.SUCCESS == "success"
    assert _SubtaskStatus.FAILED == "failed"
    assert _SubtaskStatus.TIMEOUT == "timeout"
    assert _SubtaskStatus.CANCELLED == "cancelled"


# ---------------------------------------------------------------------------
# 6. _is_local_device
# ---------------------------------------------------------------------------


def test_is_local_device_empty():
    from core.orchestration.lifecycle import _is_local_device
    assert _is_local_device("") is True
    assert _is_local_device(None) is True  # type: ignore


def test_is_local_device_prefix_local():
    from core.orchestration.lifecycle import _is_local_device
    assert _is_local_device("local_device") is True


def test_is_local_device_prefix_openclawd():
    from core.orchestration.lifecycle import _is_local_device
    assert _is_local_device("openclawd") is True


def test_is_local_device_prefix_server():
    from core.orchestration.lifecycle import _is_local_device
    assert _is_local_device("server_main") is True


def test_is_local_device_remote():
    from core.orchestration.lifecycle import _is_local_device, _LOCAL_HOSTNAME
    # A device ID that doesn't match any prefix and doesn't contain hostname
    remote_id = "remote_android_device_zzz"
    if _LOCAL_HOSTNAME and _LOCAL_HOSTNAME in remote_id.lower():
        pytest.skip("hostname collides with test device ID")
    assert _is_local_device(remote_id) is False


# ---------------------------------------------------------------------------
# 7. SessionMemoryManager
# ---------------------------------------------------------------------------


def test_session_memory_manager_instantiates():
    from core.orchestration.state import SessionMemoryManager
    smm = SessionMemoryManager()
    assert smm is not None


def test_session_memory_manager_record_and_get():
    from core.orchestration.state import SessionMemoryManager
    smm = SessionMemoryManager()
    asyncio.run(smm.record_turn("sess1", "user", "hello"))
    history = smm.get_history("sess1")
    assert len(history) == 1
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "hello"


def test_session_memory_manager_clear_session():
    from core.orchestration.state import SessionMemoryManager
    smm = SessionMemoryManager()
    asyncio.run(smm.record_turn("sess1", "user", "hi"))
    asyncio.run(smm.clear_session("sess1"))
    assert smm.get_history("sess1") == []


def test_session_memory_manager_list_sessions():
    from core.orchestration.state import SessionMemoryManager
    smm = SessionMemoryManager()
    asyncio.run(smm.record_turn("s1", "user", "hi"))
    asyncio.run(smm.record_turn("s2", "assistant", "hello"))
    sessions = smm.list_sessions()
    session_ids = {s["session_id"] for s in sessions}
    assert "s1" in session_ids
    assert "s2" in session_ids


def test_session_memory_manager_rolling_window():
    from core.orchestration.state import SessionMemoryManager

    async def _fill():
        smm = SessionMemoryManager()
        for i in range(45):
            await smm.record_turn("sess", "user", f"msg {i}")
        return smm

    smm = asyncio.run(_fill())
    history = smm.get_history("sess")
    # After 45 inserts, rolling window keeps last 20 after trimming at 40
    assert len(history) <= 20


def test_session_memory_manager_get_history_max_turns():
    from core.orchestration.state import SessionMemoryManager

    async def _fill():
        smm = SessionMemoryManager()
        for i in range(10):
            await smm.record_turn("sess", "user", f"msg {i}")
        return smm

    smm = asyncio.run(_fill())
    history = smm.get_history("sess", max_turns=3)
    assert len(history) == 3


# ---------------------------------------------------------------------------
# 8. OpenClawd composition attributes
# ---------------------------------------------------------------------------


def test_openclawd_has_lifecycle_manager():
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    assert hasattr(oc, "_lifecycle_manager")
    from core.orchestration.lifecycle import LifecycleManager
    assert isinstance(oc._lifecycle_manager, LifecycleManager)


def test_openclawd_has_session_manager():
    from core.openclawd import OpenClawd
    from core.orchestration.state import SessionMemoryManager
    oc = OpenClawd()
    assert hasattr(oc, "_session_manager")
    assert isinstance(oc._session_manager, SessionMemoryManager)


def test_openclawd_still_has_cancel_registry():
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    assert hasattr(oc, "_cancel_registry")
    assert isinstance(oc._cancel_registry, set)


# ---------------------------------------------------------------------------
# 9. All submodule classes importable from core.orchestration
# ---------------------------------------------------------------------------


def test_import_lifecycle_manager_from_package():
    from core.orchestration import LifecycleManager
    assert LifecycleManager is not None


def test_import_parallel_group_tracker_from_package():
    from core.orchestration import ParallelGroupTracker
    assert ParallelGroupTracker is not None


def test_import_parallel_result_from_package():
    from core.orchestration import ParallelResult
    assert ParallelResult is not None


def test_import_session_memory_manager_from_package():
    from core.orchestration import SessionMemoryManager
    assert SessionMemoryManager is not None


def test_import_continuum_state_adapter_from_package():
    from core.orchestration import ContinuumStateAdapter
    assert ContinuumStateAdapter is not None


def test_import_perception_pipeline_from_package():
    from core.orchestration import PerceptionPipeline
    assert PerceptionPipeline is not None


def test_import_planning_pipeline_from_package():
    from core.orchestration import PlanningPipeline
    assert PlanningPipeline is not None


def test_import_execution_pipeline_from_package():
    from core.orchestration import ExecutionPipeline
    assert ExecutionPipeline is not None


def test_import_reflection_pipeline_from_package():
    from core.orchestration import ReflectionPipeline
    assert ReflectionPipeline is not None


def test_import_orchestration_helpers_from_package():
    from core.orchestration import OrchestrationHelpers
    assert OrchestrationHelpers is not None


# ---------------------------------------------------------------------------
# 10. Startup path: get_openclawd still works
# ---------------------------------------------------------------------------


def test_get_openclawd_importable():
    from core.openclawd import get_openclawd
    assert callable(get_openclawd)


def test_get_openclawd_returns_instance():
    from core.openclawd import get_openclawd, OpenClawd
    # Reset the singleton so we get a fresh instance
    import core.openclawd as _m
    _m._openclawd_instance = None
    instance = get_openclawd()
    assert isinstance(instance, OpenClawd)


# ---------------------------------------------------------------------------
# 11. ParallelResult.to_dict()
# ---------------------------------------------------------------------------


def test_parallel_result_to_dict():
    from core.orchestration.lifecycle import ParallelResult
    pr = ParallelResult(
        group_id="g1",
        device_results=[{"task_id": "t1", "status": "success"}],
        summary_status="success",
        succeeded=1,
        failed=0,
        cancelled=0,
        total=1,
    )
    d = pr.to_dict()
    assert d["group_id"] == "g1"
    assert d["summary_status"] == "success"
    assert d["succeeded"] == 1
    assert isinstance(d["device_results"], list)


# ---------------------------------------------------------------------------
# 12. Backward compat: OpenClawd._cancel_registry not broken
# ---------------------------------------------------------------------------


def test_openclawd_cancel_registry_is_independent_set():
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    # Manually add to the instance's cancel_registry (legacy path)
    oc._cancel_registry.add("legacy_task_id")
    assert "legacy_task_id" in oc._cancel_registry
    # lifecycle_manager has its own registry
    assert "legacy_task_id" not in oc._lifecycle_manager._cancel_registry


# ---------------------------------------------------------------------------
# 13. _SubtaskEntry dataclass creation
# ---------------------------------------------------------------------------


def test_subtask_entry_default_status():
    from core.orchestration.lifecycle import _SubtaskEntry, _SubtaskStatus
    e = _SubtaskEntry(
        task_id="t1",
        group_id="g1",
        subtask_index=0,
        device_id="local",
        subtask="run something",
    )
    assert e.status == _SubtaskStatus.PENDING
    assert e.started_at is None
    assert e.retry_count == 0


def test_subtask_entry_fields():
    from core.orchestration.lifecycle import _SubtaskEntry
    e = _SubtaskEntry(
        task_id="t_abc",
        group_id="g_abc",
        subtask_index=2,
        device_id="device_123",
        subtask="write file",
    )
    assert e.task_id == "t_abc"
    assert e.group_id == "g_abc"
    assert e.subtask_index == 2
    assert e.device_id == "device_123"
    assert e.subtask == "write file"


# ---------------------------------------------------------------------------
# 14. Retry helpers
# ---------------------------------------------------------------------------


def test_needs_retry_failed():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_done("g1", "t1", {"error": "x"}, success=False)
    assert tracker.needs_retry("g1", "t1") is True


def test_needs_retry_exhausted():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    tracker.mark_done("g1", "t1", {"error": "x"}, success=False)
    tracker.increment_retry("g1", "t1")
    tracker.mark_done("g1", "t1", {"error": "x"}, success=False)
    assert tracker.needs_retry("g1", "t1") is False


def test_backoff_delay():
    from core.orchestration.lifecycle import ParallelGroupTracker
    tracker = ParallelGroupTracker()
    tracker.register_group("g1", [_make_entry("g1", "t1", 0)])
    delay = tracker.backoff_delay("g1", "t1")
    assert delay == 2.0  # 2.0^1 = 2.0


# ---------------------------------------------------------------------------
# 15. Submodule package __init__.py re-exports sentinel check
# ---------------------------------------------------------------------------


def test_all_authority_sentinels_via_package():
    from core.orchestration import (
        OPENCLAWD_ORCHESTRATION_AUTHORITY,
        LIFECYCLE_MANAGER_AUTHORITY,
        STATE_MANAGER_AUTHORITY,
        PERCEPTION_PIPELINE_AUTHORITY,
        PLANNING_PIPELINE_AUTHORITY,
        EXECUTION_PIPELINE_AUTHORITY,
        REFLECTION_PIPELINE_AUTHORITY,
        ORCHESTRATION_HELPERS_AUTHORITY,
    )
    sentinels = [
        OPENCLAWD_ORCHESTRATION_AUTHORITY,
        LIFECYCLE_MANAGER_AUTHORITY,
        STATE_MANAGER_AUTHORITY,
        PERCEPTION_PIPELINE_AUTHORITY,
        PLANNING_PIPELINE_AUTHORITY,
        EXECUTION_PIPELINE_AUTHORITY,
        REFLECTION_PIPELINE_AUTHORITY,
        ORCHESTRATION_HELPERS_AUTHORITY,
    ]
    for s in sentinels:
        assert isinstance(s, str) and s, f"Sentinel must be non-empty string, got: {s!r}"


# ---------------------------------------------------------------------------
# 16. openclawd.py re-exports lifecycle symbols (backward compat)
# ---------------------------------------------------------------------------


def test_openclawd_module_reexports_parallel_group_tracker():
    from core.openclawd import ParallelGroupTracker
    assert ParallelGroupTracker is not None


def test_openclawd_module_reexports_parallel_result():
    from core.openclawd import ParallelResult
    assert ParallelResult is not None


def test_openclawd_module_reexports_subtask_status():
    from core.openclawd import _SubtaskStatus
    assert _SubtaskStatus is not None


def test_openclawd_module_reexports_is_local_device():
    from core.openclawd import _is_local_device
    assert callable(_is_local_device)


def test_openclawd_module_reexports_lifecycle_manager():
    from core.openclawd import LifecycleManager
    assert LifecycleManager is not None


# ---------------------------------------------------------------------------
# 17. PerceptionPipeline delegates gracefully on missing method
# ---------------------------------------------------------------------------


def test_perception_pipeline_missing_method():
    from core.orchestration.perception import PerceptionPipeline

    class FakeOC:
        pass

    result = PerceptionPipeline.build_canonical_perception_state(FakeOC())
    assert result is None


def test_perception_pipeline_delegates_to_method():
    from core.orchestration.perception import PerceptionPipeline

    class FakeOC:
        def _build_canonical_perception_state(self, multimodal_context=None):
            return {"perception": "state", "context": multimodal_context}

    result = PerceptionPipeline.build_canonical_perception_state(
        FakeOC(), multimodal_context={"image": "data"}
    )
    assert result == {"perception": "state", "context": {"image": "data"}}


# ---------------------------------------------------------------------------
# 18. PlanningPipeline delegates gracefully
# ---------------------------------------------------------------------------


def test_planning_pipeline_determine_path_missing():
    from core.orchestration.planning import PlanningPipeline

    class FakeOC:
        pass

    result = PlanningPipeline.determine_execution_path(FakeOC(), None, "device_1")
    assert result == "none"


# ---------------------------------------------------------------------------
# 19. OrchestrationHelpers delegates gracefully
# ---------------------------------------------------------------------------


def test_orchestration_helpers_emit_audit_missing():
    from core.orchestration.helpers import OrchestrationHelpers

    class FakeOC:
        pass

    result = OrchestrationHelpers.emit_audit(FakeOC(), "test_event")
    assert result is None


# ---------------------------------------------------------------------------
# 20. OpenClawd import and get_openclawd path (integration)
# ---------------------------------------------------------------------------


def test_openclawd_instantiates_without_error():
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    assert oc is not None


def test_openclawd_initialized_flag():
    from core.openclawd import OpenClawd
    oc = OpenClawd()
    # _initialized starts False (lazy init)
    assert hasattr(oc, "_initialized")
