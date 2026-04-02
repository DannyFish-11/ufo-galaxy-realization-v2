#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_operator_surface_contracts.py
=========================================
PR-E — Operator Surface + Replay Foundation

Validates the OperatorSurface authority contracts, projection-only principle,
and the role boundary sentinels.

Coverage:
  1.  OPERATOR_SURFACE_AUTHORITY sentinel is importable and non-empty string.
  2.  OPERATOR_SURFACE_LAYER_POSITION is 10.
  3.  OPERATOR_SURFACE_CONTRACT_VERSION is a non-empty string.
  4.  OPERATOR_SURFACE_PROJECTION_POLICY is a non-empty string.
  5.  OPERATOR_CONSOLE_ROLE / STATUS_BOARD_ROLE / TOPOLOGY_VIEWER_ROLE are distinct strings.
  6.  All names appear in __all__.
  7.  TaskInspection is a dataclass with task_id, lifecycle, origin, etc.
  8.  TaskInspection.to_dict() returns a dict with all required keys.
  9.  RouteInspection is a dataclass with task_id, selected_targets, etc.
  10. RouteInspection.to_dict() contains _source key.
  11. ExecutorInspection is a dataclass with node_id, presence_state, etc.
  12. ExecutorInspection.to_dict() contains all required keys.
  13. FailureDomainInspection is a dataclass with failure_domain, error_code, etc.
  14. FailureDomainInspection.to_dict() is serialisable.
  15. LineageInspection is a dataclass with retry_chain, fallback_chain, timeline.
  16. LineageInspection.to_dict() is serialisable.
  17. DevicePresenceSummary is a dataclass with device_id, is_ready, etc.
  18. OperatorSnapshot has authority and contract_version fields.
  19. OperatorSnapshot.to_dict() includes authority sentinel.
  20. get_operator_surface() returns an OperatorSurface instance.
  21. reset_operator_surface() resets the singleton.
  22. Two calls to get_operator_surface() return the same object.
  23. OperatorSurface.inspect_task() returns None for unknown task_id.
  24. OperatorSurface.inspect_route() returns None for unknown task_id.
  25. OperatorSurface.inspect_executor() returns None for unknown node_id.
  26. OperatorSurface.inspect_failure_domain() returns None for unknown task_id.
  27. OperatorSurface.inspect_lineage() returns None for unknown task_id.
  28. OperatorSurface.operator_snapshot() always returns an OperatorSnapshot.
  29. operator_snapshot().to_dict() is JSON-serialisable.
  30. OperatorSurface.inspect_task() returns TaskInspection for a registered task.
  31. inspect_task result has correct task_id, lifecycle, goal.
  32. inspect_route() returns RouteInspection for a registered task.
  33. inspect_lineage() returns LineageInspection for a registered task.
  34. LineageInspection timeline entries are ordered by ts.
  35. OperatorSnapshot authority matches OPERATOR_SURFACE_AUTHORITY.
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import Any, Dict

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.operator_surface import (
    OPERATOR_SURFACE_AUTHORITY,
    OPERATOR_SURFACE_LAYER_POSITION,
    OPERATOR_SURFACE_CONTRACT_VERSION,
    OPERATOR_SURFACE_PROJECTION_POLICY,
    OPERATOR_CONSOLE_ROLE,
    STATUS_BOARD_ROLE,
    TOPOLOGY_VIEWER_ROLE,
    TaskInspection,
    RouteInspection,
    ExecutorInspection,
    FailureDomainInspection,
    LineageInspection,
    DevicePresenceSummary,
    OperatorSnapshot,
    OperatorSurface,
    get_operator_surface,
    reset_operator_surface,
)
import core.operator_surface as _mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_surface():
    reset_operator_surface()
    from core.canonical_task import reset_canonical_task_runtime
    reset_canonical_task_runtime()
    yield
    reset_operator_surface()
    reset_canonical_task_runtime()


def _build_task(goal: str = "test goal", lifecycle: str = "completed"):
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskLifecycle,
        TaskOrigin,
    )
    task = build_canonical_task(
        goal=goal,
        origin=TaskOrigin.API_REQUEST,
        requested_action="test_action",
        selected_targets=["device_001"],
    )
    task.lifecycle = TaskLifecycle(lifecycle)
    task.result.success = (lifecycle == "completed")
    rt = get_canonical_task_runtime()
    rt.register(task)
    return task


# ===========================================================================
# 1-6: Authority sentinels
# ===========================================================================

class TestAuthoritySentinels:
    def test_01_authority_importable(self):
        assert OPERATOR_SURFACE_AUTHORITY
        assert isinstance(OPERATOR_SURFACE_AUTHORITY, str)

    def test_02_layer_position(self):
        assert OPERATOR_SURFACE_LAYER_POSITION == 10

    def test_03_contract_version(self):
        assert OPERATOR_SURFACE_CONTRACT_VERSION
        assert isinstance(OPERATOR_SURFACE_CONTRACT_VERSION, str)

    def test_04_projection_policy(self):
        assert OPERATOR_SURFACE_PROJECTION_POLICY
        assert isinstance(OPERATOR_SURFACE_PROJECTION_POLICY, str)

    def test_05_role_sentinels_distinct(self):
        roles = {OPERATOR_CONSOLE_ROLE, STATUS_BOARD_ROLE, TOPOLOGY_VIEWER_ROLE}
        assert len(roles) == 3

    def test_06_all_exports(self):
        expected = [
            "OPERATOR_SURFACE_AUTHORITY",
            "OPERATOR_SURFACE_LAYER_POSITION",
            "OPERATOR_SURFACE_CONTRACT_VERSION",
            "OPERATOR_SURFACE_PROJECTION_POLICY",
            "OPERATOR_CONSOLE_ROLE",
            "STATUS_BOARD_ROLE",
            "TOPOLOGY_VIEWER_ROLE",
            "TaskInspection",
            "RouteInspection",
            "ExecutorInspection",
            "FailureDomainInspection",
            "LineageInspection",
            "DevicePresenceSummary",
            "OperatorSnapshot",
            "OperatorSurface",
            "get_operator_surface",
            "reset_operator_surface",
        ]
        for name in expected:
            assert name in _mod.__all__, f"{name!r} missing from __all__"


# ===========================================================================
# 7-19: Dataclass structure
# ===========================================================================

class TestDataclassStructure:
    def test_07_task_inspection_fields(self):
        ti = TaskInspection(task_id="t1", lifecycle="completed")
        assert ti.task_id == "t1"
        assert ti.lifecycle == "completed"

    def test_08_task_inspection_to_dict(self):
        ti = TaskInspection(task_id="t1", lifecycle="routed", goal="do_x")
        d = ti.to_dict()
        for key in ("task_id", "lifecycle", "goal", "origin", "_source"):
            assert key in d, f"{key!r} missing from to_dict"

    def test_09_route_inspection_fields(self):
        ri = RouteInspection(task_id="t1", selected_targets=["dev_a"])
        assert ri.task_id == "t1"
        assert ri.selected_targets == ["dev_a"]

    def test_10_route_inspection_source_key(self):
        ri = RouteInspection()
        d = ri.to_dict()
        assert "_source" in d

    def test_11_executor_inspection_fields(self):
        ei = ExecutorInspection(node_id="node_1", presence_state="online")
        assert ei.node_id == "node_1"
        assert ei.presence_state == "online"

    def test_12_executor_inspection_to_dict(self):
        ei = ExecutorInspection(node_id="n1", is_online=True)
        d = ei.to_dict()
        assert "node_id" in d
        assert "is_online" in d
        assert "_source" in d

    def test_13_failure_domain_inspection_fields(self):
        fd = FailureDomainInspection(
            task_id="t1", failure_domain="routing", error_code="TIMEOUT"
        )
        assert fd.failure_domain == "routing"
        assert fd.error_code == "TIMEOUT"

    def test_14_failure_domain_inspection_serialisable(self):
        fd = FailureDomainInspection(task_id="t1", failure_domain="transport")
        json.dumps(fd.to_dict())  # should not raise

    def test_15_lineage_inspection_fields(self):
        li = LineageInspection(
            task_id="t1", retry_chain=["t2"], fallback_chain=["t3"]
        )
        assert li.retry_chain == ["t2"]
        assert li.fallback_chain == ["t3"]

    def test_16_lineage_inspection_serialisable(self):
        li = LineageInspection(task_id="t1", timeline=[{"event": "created", "ts": 1.0}])
        json.dumps(li.to_dict())  # should not raise

    def test_17_device_presence_summary_fields(self):
        dp = DevicePresenceSummary(device_id="dev1", is_ready=True)
        assert dp.device_id == "dev1"
        assert dp.is_ready is True

    def test_18_operator_snapshot_authority_fields(self):
        snap = OperatorSnapshot()
        assert snap.authority == OPERATOR_SURFACE_AUTHORITY
        assert snap.contract_version == OPERATOR_SURFACE_CONTRACT_VERSION

    def test_19_operator_snapshot_to_dict_has_authority(self):
        snap = OperatorSnapshot()
        d = snap.to_dict()
        assert d["authority"] == OPERATOR_SURFACE_AUTHORITY


# ===========================================================================
# 20-29: Singleton and graceful degradation
# ===========================================================================

class TestSingletonAndGraceful:
    def test_20_get_operator_surface_returns_instance(self):
        surface = get_operator_surface()
        assert isinstance(surface, OperatorSurface)

    def test_21_reset_operator_surface(self):
        s1 = get_operator_surface()
        reset_operator_surface()
        s2 = get_operator_surface()
        assert s1 is not s2

    def test_22_singleton_identity(self):
        s1 = get_operator_surface()
        s2 = get_operator_surface()
        assert s1 is s2

    def test_23_inspect_task_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_task("nonexistent_task") is None

    def test_24_inspect_route_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_route("nonexistent_task") is None

    def test_25_inspect_executor_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_executor("nonexistent_node") is None

    def test_26_inspect_failure_domain_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_failure_domain("nonexistent_task") is None

    def test_27_inspect_lineage_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_lineage("nonexistent_task") is None

    def test_28_operator_snapshot_always_returns(self):
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert isinstance(snap, OperatorSnapshot)

    def test_29_operator_snapshot_json_serialisable(self):
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        json.dumps(snap.to_dict())  # should not raise


# ===========================================================================
# 30-35: Live task inspection
# ===========================================================================

class TestLiveTaskInspection:
    def test_30_inspect_task_registered_returns_inspection(self):
        task = _build_task("screenshot goal", "completed")
        surface = get_operator_surface()
        result = surface.inspect_task(task.identity.task_id)
        assert result is not None
        assert isinstance(result, TaskInspection)

    def test_31_inspect_task_correct_fields(self):
        task = _build_task("my goal", "routed")
        surface = get_operator_surface()
        insp = surface.inspect_task(task.identity.task_id)
        assert insp is not None
        assert insp.task_id == task.identity.task_id
        assert insp.goal == "my goal"
        assert insp.lifecycle == "routed"

    def test_32_inspect_route_registered_task(self):
        task = _build_task("route test", "dispatched")
        surface = get_operator_surface()
        route = surface.inspect_route(task.identity.task_id)
        assert route is not None
        assert isinstance(route, RouteInspection)
        assert route.task_id == task.identity.task_id

    def test_33_inspect_lineage_registered_task(self):
        task = _build_task("lineage test", "completed")
        surface = get_operator_surface()
        lineage = surface.inspect_lineage(task.identity.task_id)
        assert lineage is not None
        assert isinstance(lineage, LineageInspection)
        assert lineage.task_id == task.identity.task_id

    def test_34_lineage_timeline_ordered(self):
        from core.canonical_task import (
            build_canonical_task,
            get_canonical_task_runtime,
            TaskLifecycle,
            TaskOrigin,
        )
        task = build_canonical_task(goal="timeline task", origin=TaskOrigin.API_REQUEST)
        task.admitted_at = time.time() + 0.001
        task.routed_at = time.time() + 0.002
        task.dispatched_at = time.time() + 0.003
        task.lifecycle = TaskLifecycle.DISPATCHED
        get_canonical_task_runtime().register(task)
        surface = get_operator_surface()
        lineage = surface.inspect_lineage(task.identity.task_id)
        assert lineage is not None
        ts_list = [e["ts"] for e in lineage.timeline]
        assert ts_list == sorted(ts_list)

    def test_35_operator_snapshot_authority_matches_sentinel(self):
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert snap.authority == OPERATOR_SURFACE_AUTHORITY
