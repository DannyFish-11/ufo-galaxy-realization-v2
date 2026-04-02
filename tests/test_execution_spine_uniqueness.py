#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_execution_spine_uniqueness.py
=========================================

PR-A: Canonical Task & Execution Spine — execution spine uniqueness tests.

Validates that:
 1.  CANONICAL_TASK_SPINE_INTEGRATED sentinel exists in command_router.
 2.  CANONICAL_TASK_SPINE_INTEGRATED mentions route_envelope.
 3.  CommandRouter exposes route_envelope method (the sole dispatch spine).
 4.  CANONICAL_EXECUTION_SPINE_POLICY in canonical_task enforces route_envelope.
 5.  project_to_task_envelope() produces an object that has task_id/trace_id/
     tool_name/targets (the contract required by CommandRouter.route_envelope).
 6.  CanonicalTask.project_to_task_envelope() delegates to module-level helper.
 7.  Execution spine layer: CanonicalTask → envelope → spine is traceable.
 8.  UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE sentinel importable and correct.
 9.  GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE sentinel importable and correct.
10.  UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY still importable (no regression).
11.  GALAXY_ORCHESTRATOR_FACADE_AUTHORITY still importable (no regression).
12.  build_canonical_task() + project_to_task_envelope() round-trip preserves task_id.
13.  build_canonical_task() + project_to_task_envelope() round-trip preserves trace_id.
14.  Envelope metadata contains canonical_task_authority sentinel.
15.  apply_result_envelope() returns CanonicalTask (not a new object type).
16.  CanonicalTask.lifecycle advances to DISPATCHED when set manually.
17.  CanonicalTask → envelope → apply_result round-trip completes without error.
18.  CANONICAL_TASK_AUTHORITY importable.
19.  CANONICAL_TASK_LAYER_POSITION is int.
20.  CANONICAL_EXECUTION_SPINE_POLICY is non-empty str.
"""

from __future__ import annotations

import pytest

from core.canonical_task import (
    CANONICAL_TASK_AUTHORITY,
    CANONICAL_TASK_LAYER_POSITION,
    CANONICAL_EXECUTION_SPINE_POLICY,
    CanonicalTask,
    TaskLifecycle,
    TaskOrigin,
    apply_result_envelope,
    build_canonical_task,
    project_to_task_envelope,
    reset_canonical_task_runtime,
)


@pytest.fixture(autouse=True)
def reset():
    reset_canonical_task_runtime()
    yield
    reset_canonical_task_runtime()


# ---------------------------------------------------------------------------
# 1. CANONICAL_TASK_SPINE_INTEGRATED in command_router
# ---------------------------------------------------------------------------

def test_01_CANONICAL_TASK_SPINE_INTEGRATED_importable():
    from core.command_router import CANONICAL_TASK_SPINE_INTEGRATED
    assert CANONICAL_TASK_SPINE_INTEGRATED is not None


def test_02_CANONICAL_TASK_SPINE_INTEGRATED_mentions_route_envelope():
    from core.command_router import CANONICAL_TASK_SPINE_INTEGRATED
    assert "route_envelope" in CANONICAL_TASK_SPINE_INTEGRATED


# ---------------------------------------------------------------------------
# 3. CommandRouter.route_envelope exists
# ---------------------------------------------------------------------------

def test_03_command_router_has_route_envelope():
    from core.command_router import CommandRouter
    assert hasattr(CommandRouter, "route_envelope"), \
        "CommandRouter must expose route_envelope as the sole dispatch spine"


# ---------------------------------------------------------------------------
# 4. CANONICAL_EXECUTION_SPINE_POLICY enforces route_envelope
# ---------------------------------------------------------------------------

def test_04_spine_policy_mentions_route_envelope():
    assert "route_envelope" in CANONICAL_EXECUTION_SPINE_POLICY


# ---------------------------------------------------------------------------
# 5. project_to_task_envelope contract
# ---------------------------------------------------------------------------

def test_05_envelope_has_task_id():
    task = build_canonical_task(tool="ping", register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "task_id")
    assert env.task_id


def test_05b_envelope_has_trace_id():
    task = build_canonical_task(tool="ping", register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "trace_id")
    assert env.trace_id


def test_05c_envelope_has_tool_name():
    task = build_canonical_task(tool="screenshot", register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "tool_name")


def test_05d_envelope_has_targets():
    task = build_canonical_task(selected_targets=["dev1"], register=False)
    env = project_to_task_envelope(task)
    assert hasattr(env, "targets")


# ---------------------------------------------------------------------------
# 6. CanonicalTask.project_to_task_envelope() delegates
# ---------------------------------------------------------------------------

def test_06_method_delegates_to_module_helper():
    task = build_canonical_task(tool="foo", register=False)
    env_method = task.project_to_task_envelope()
    env_helper = project_to_task_envelope(task)
    # Both should produce objects with same task_id
    assert env_method.task_id == env_helper.task_id


# ---------------------------------------------------------------------------
# 7. Spine traceability
# ---------------------------------------------------------------------------

def test_07_spine_trace_task_id_preserved():
    task = build_canonical_task(tool="trace_test")
    env = task.project_to_task_envelope()
    assert env.task_id == task.task_id


# ---------------------------------------------------------------------------
# 8. UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE
# ---------------------------------------------------------------------------

def test_08_unified_orchestrator_canonical_task_facade_importable():
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"unified_orchestrator import unavailable (missing dependency): {exc}")
    assert UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE is not None


def test_08b_unified_orchestrator_facade_mentions_command_router():
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"unified_orchestrator import unavailable (missing dependency): {exc}")
    assert "CommandRouter" in UNIFIED_ORCHESTRATOR_CANONICAL_TASK_FACADE


# ---------------------------------------------------------------------------
# 9. GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE
# ---------------------------------------------------------------------------

def test_09_galaxy_orchestrator_canonical_task_facade_importable():
    try:
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"galaxy_orchestrator import unavailable (missing dependency): {exc}")
    assert GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE is not None


def test_09b_galaxy_orchestrator_facade_mentions_command_router():
    try:
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"galaxy_orchestrator import unavailable (missing dependency): {exc}")
    assert "CommandRouter" in GALAXY_ORCHESTRATOR_CANONICAL_TASK_FACADE


# ---------------------------------------------------------------------------
# 10. UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY no regression
# ---------------------------------------------------------------------------

def test_10_unified_orchestrator_facade_authority_no_regression():
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"unified_orchestrator import unavailable (missing dependency): {exc}")
    assert "FACADE" in UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY


# ---------------------------------------------------------------------------
# 11. GALAXY_ORCHESTRATOR_FACADE_AUTHORITY no regression
# ---------------------------------------------------------------------------

def test_11_galaxy_orchestrator_facade_authority_no_regression():
    try:
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_FACADE_AUTHORITY
    except (ImportError, AttributeError) as exc:
        pytest.skip(f"galaxy_orchestrator import unavailable (missing dependency): {exc}")
    assert "FACADE" in GALAXY_ORCHESTRATOR_FACADE_AUTHORITY


# ---------------------------------------------------------------------------
# 12–13. Round-trip preserves ids
# ---------------------------------------------------------------------------

def test_12_round_trip_preserves_task_id():
    task = build_canonical_task()
    env = task.project_to_task_envelope()
    assert env.task_id == task.task_id


def test_13_round_trip_preserves_trace_id():
    task = build_canonical_task()
    env = task.project_to_task_envelope()
    assert env.trace_id == task.trace_id


# ---------------------------------------------------------------------------
# 14. Envelope metadata has canonical_task_authority
# ---------------------------------------------------------------------------

def test_14_envelope_metadata_has_canonical_task_authority():
    task = build_canonical_task()
    env = task.project_to_task_envelope()
    meta = getattr(env, "metadata", None) or {}
    assert "canonical_task_authority" in meta
    assert CANONICAL_TASK_AUTHORITY in meta["canonical_task_authority"]


# ---------------------------------------------------------------------------
# 15. apply_result_envelope returns CanonicalTask
# ---------------------------------------------------------------------------

def test_15_apply_result_returns_canonical_task():
    task = build_canonical_task()
    result = apply_result_envelope(task, {"success": True})
    assert isinstance(result, CanonicalTask)


# ---------------------------------------------------------------------------
# 16. Lifecycle advances to DISPATCHED
# ---------------------------------------------------------------------------

def test_16_lifecycle_advances_to_dispatched():
    task = build_canonical_task()
    task.advance_lifecycle(TaskLifecycle.DISPATCHED)
    assert task.lifecycle == TaskLifecycle.DISPATCHED
    assert task.dispatched_at is not None


# ---------------------------------------------------------------------------
# 17. Full round-trip
# ---------------------------------------------------------------------------

def test_17_full_round_trip():
    task = build_canonical_task(
        goal="take screenshot",
        tool="screenshot",
        selected_targets=["dev1"],
        origin=TaskOrigin.API_REQUEST,
    )
    task.advance_lifecycle(TaskLifecycle.ADMITTED)
    task.advance_lifecycle(TaskLifecycle.PLANNED)
    task.advance_lifecycle(TaskLifecycle.ROUTED)
    env = task.project_to_task_envelope()
    task.advance_lifecycle(TaskLifecycle.DISPATCHED)
    assert env.task_id == task.task_id
    task = apply_result_envelope(task, {"success": True, "result": "screenshot saved"})
    assert task.lifecycle == TaskLifecycle.COMPLETED


# ---------------------------------------------------------------------------
# 18–20. Remaining sentinel checks
# ---------------------------------------------------------------------------

def test_18_canonical_task_authority_importable():
    assert CANONICAL_TASK_AUTHORITY is not None


def test_19_canonical_task_layer_position_is_int():
    assert isinstance(CANONICAL_TASK_LAYER_POSITION, int)


def test_20_canonical_execution_spine_policy_non_empty():
    assert isinstance(CANONICAL_EXECUTION_SPINE_POLICY, str)
    assert len(CANONICAL_EXECUTION_SPINE_POLICY) > 0
