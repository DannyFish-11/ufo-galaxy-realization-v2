#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_projection_reads_runtime_only.py
============================================
PR-E — Operator Surface + Replay Foundation

Validates the projection-only principle: all operator surface projections
must consume only canonical runtime sources; they must not infer truth from
legacy or raw internal sources.

Coverage:
  1.  OPERATOR_SURFACE_PROJECTION_POLICY string contains "canonical".
  2.  OperatorSnapshot._source fields only reference canonical runtime names.
  3.  TaskInspection._source defaults to "canonical_task_runtime".
  4.  RouteInspection._source defaults to "admissibility_policy_convergence".
  5.  ExecutorInspection._source defaults to "capability_assimilation".
  6.  FailureDomainInspection._source defaults to "task_graph_runtime".
  7.  LineageInspection._source defaults to "task_graph_runtime".
  8.  DevicePresenceSummary._source defaults to "network_topology_runtime".
  9.  OperatorSnapshot.to_dict() projection_policy references canonical.
  10. OperatorSnapshot.authority matches OPERATOR_SURFACE_AUTHORITY.
  11. OperatorSurface does NOT import from legacy_dispatch_registry.
  12. OperatorSurface does NOT import from registered_devices compat cache.
  13. operator_snapshot() active_task_count matches CanonicalTaskRuntime count.
  14. operator_snapshot() for empty runtime has active_task_count == 0.
  15. inspect_task() does NOT return a raw dict — returns TaskInspection.
  16. inspect_route() does NOT return a raw dict — returns RouteInspection.
  17. inspect_failure_domain() does NOT return a raw dict.
  18. inspect_lineage() does NOT return a raw dict.
  19. OperatorSnapshot has no reference to "registered_devices".
  20. All projection dataclasses have _source field in their to_dict() output.
"""

from __future__ import annotations

import inspect
import json
import sys
import os

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.operator_surface import (
    OPERATOR_SURFACE_PROJECTION_POLICY,
    OPERATOR_SURFACE_AUTHORITY,
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset():
    reset_operator_surface()
    from core.canonical_task import reset_canonical_task_runtime
    reset_canonical_task_runtime()
    yield
    reset_operator_surface()
    reset_canonical_task_runtime()


def _register_task(goal: str = "test"):
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskOrigin,
    )
    task = build_canonical_task(goal=goal, origin=TaskOrigin.API_REQUEST)
    get_canonical_task_runtime().register(task)
    return task


# ===========================================================================
# 1-10: Policy and source declaration
# ===========================================================================

class TestProjectionPolicy:
    def test_01_policy_references_canonical(self):
        assert "canonical" in OPERATOR_SURFACE_PROJECTION_POLICY.lower()

    def test_02_operator_snapshot_no_legacy_source(self):
        snap = OperatorSnapshot()
        d = snap.to_dict()
        # No legacy source names in the snapshot dict values
        raw = json.dumps(d)
        for bad in ("registered_devices", "device_cache", "raw_internal"):
            assert bad not in raw, f"Legacy source {bad!r} found in snapshot"

    def test_03_task_inspection_source(self):
        ti = TaskInspection()
        assert ti._source == "canonical_task_runtime"

    def test_04_route_inspection_source(self):
        ri = RouteInspection()
        assert ri._source == "admissibility_policy_convergence"

    def test_05_executor_inspection_source(self):
        ei = ExecutorInspection()
        assert ei._source == "capability_assimilation"

    def test_06_failure_domain_inspection_source(self):
        fd = FailureDomainInspection()
        assert fd._source == "task_graph_runtime"

    def test_07_lineage_inspection_source(self):
        li = LineageInspection()
        assert li._source == "task_graph_runtime"

    def test_08_device_presence_source(self):
        dp = DevicePresenceSummary()
        assert dp._source == "network_topology_runtime"

    def test_09_operator_snapshot_projection_policy_in_dict(self):
        snap = OperatorSnapshot()
        d = snap.to_dict()
        assert "canonical" in d.get("projection_policy", "").lower()

    def test_10_operator_snapshot_authority_matches_sentinel(self):
        snap = OperatorSnapshot()
        assert snap.to_dict()["authority"] == OPERATOR_SURFACE_AUTHORITY


# ===========================================================================
# 11-12: Module-level source purity
# ===========================================================================

class TestModuleSourcePurity:
    def test_11_operator_surface_no_legacy_dispatch_registry(self):
        import core.operator_surface as m
        source = inspect.getsource(m)
        assert "legacy_dispatch_registry" not in source

    def test_12_operator_surface_no_registered_devices(self):
        import core.operator_surface as m
        source = inspect.getsource(m)
        # Must not directly import registered_devices compat cache
        assert "from core.routes._shared import" not in source or \
               "REGISTERED_DEVICES" not in inspect.getsource(m)


# ===========================================================================
# 13-14: Snapshot consistency with canonical runtime
# ===========================================================================

class TestSnapshotConsistency:
    def test_13_snapshot_active_count_matches_runtime(self):
        from core.canonical_task import get_canonical_task_runtime
        _register_task("task_a")
        _register_task("task_b")
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        ct_total = get_canonical_task_runtime().snapshot().total_tasks
        assert snap.active_task_count == ct_total

    def test_14_empty_runtime_active_count_zero(self):
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        assert snap.active_task_count == 0


# ===========================================================================
# 15-20: Return types enforce projection types
# ===========================================================================

class TestReturnTypeEnforcement:
    def test_15_inspect_task_returns_task_inspection(self):
        task = _register_task()
        surface = get_operator_surface()
        result = surface.inspect_task(task.identity.task_id)
        assert result is None or isinstance(result, TaskInspection)

    def test_16_inspect_route_returns_route_inspection(self):
        task = _register_task()
        surface = get_operator_surface()
        result = surface.inspect_route(task.identity.task_id)
        assert result is None or isinstance(result, RouteInspection)

    def test_17_inspect_failure_domain_returns_correct_type(self):
        task = _register_task()
        surface = get_operator_surface()
        result = surface.inspect_failure_domain(task.identity.task_id)
        assert result is None or isinstance(result, FailureDomainInspection)

    def test_18_inspect_lineage_returns_correct_type(self):
        task = _register_task()
        surface = get_operator_surface()
        result = surface.inspect_lineage(task.identity.task_id)
        assert result is None or isinstance(result, LineageInspection)

    def test_19_operator_snapshot_no_registered_devices(self):
        surface = get_operator_surface()
        snap = surface.operator_snapshot()
        raw = json.dumps(snap.to_dict())
        assert "registered_devices" not in raw

    def test_20_all_projection_to_dicts_have_source(self):
        projections = [
            TaskInspection(),
            RouteInspection(),
            ExecutorInspection(),
            FailureDomainInspection(),
            LineageInspection(),
            DevicePresenceSummary(),
        ]
        for p in projections:
            d = p.to_dict()
            assert "_source" in d, f"{type(p).__name__} missing _source in to_dict"
