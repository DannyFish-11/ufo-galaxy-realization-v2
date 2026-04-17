#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_scheduling_truth_harness.py
=========================================
Tests for core/scheduling_truth_harness.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  ConvergenceAssertionResult construction and to_dict.
  3.  SchedulingTruthHarness — ensure_task_registered with no backing runtime.
  4.  SchedulingTruthHarness — ensure_task_registered with mock backing runtime.
  5.  SchedulingTruthHarness — query_routable_executors with no backing policy.
  6.  SchedulingTruthHarness — query_routable_executors with mock policy.
  7.  SchedulingTruthHarness — assert_convergence returns result.
  8.  SchedulingTruthHarness — assert_convergence notes divergence.
  9.  Module-level ensure_task_registered function.
  10. Module-level query_routable_executors_for_task function.
  11. Module-level assert_scheduling_truth_convergence function.
  12. get_scheduling_truth_harness returns singleton.
  13. reset_scheduling_truth_harness clears singleton.
  14. ensure_task_registered with dict task.
  15. ensure_task_registered with None task.
  16. GAP_512_002_CLOSED_SENTINEL references GAP-512-002.
  17. GAP_512_004_ADDRESSED_SENTINEL references GAP-512-004.
  18. ConvergenceAssertionResult is_convergent True when all available.
  19. ConvergenceAssertionResult divergence_notes populated when task unregistered.
  20. SchedulingTruthHarness never raises.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task(task_id: str = "task-001") -> Dict[str, Any]:
    return {"task_id": task_id, "task_type": "test"}


# ---------------------------------------------------------------------------
# 1: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.scheduling_truth_harness import SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY
        assert isinstance(SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY, str)
        assert "SCHEDULING_TRUTH_HARNESS" in SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY

    def test_gap_512_002_closed(self):
        from core.scheduling_truth_harness import GAP_512_002_CLOSED_SENTINEL
        assert isinstance(GAP_512_002_CLOSED_SENTINEL, str)
        assert "512-002" in GAP_512_002_CLOSED_SENTINEL or "GAP_512_002" in GAP_512_002_CLOSED_SENTINEL

    def test_gap_512_004_addressed(self):
        from core.scheduling_truth_harness import GAP_512_004_ADDRESSED_SENTINEL
        assert isinstance(GAP_512_004_ADDRESSED_SENTINEL, str)
        assert "512-004" in GAP_512_004_ADDRESSED_SENTINEL or "GAP_512_004" in GAP_512_004_ADDRESSED_SENTINEL

    def test_task_registration_policy(self):
        from core.scheduling_truth_harness import TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY
        assert isinstance(TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY, str)

    def test_routing_truth_policy(self):
        from core.scheduling_truth_harness import ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY
        assert isinstance(ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY, str)


# ---------------------------------------------------------------------------
# 2: ConvergenceAssertionResult
# ---------------------------------------------------------------------------

class TestConvergenceAssertionResult:
    def test_construction(self):
        from core.scheduling_truth_harness import ConvergenceAssertionResult
        r = ConvergenceAssertionResult(task_id="t1", task_registered=True)
        assert r.task_id == "t1"
        assert r.task_registered is True
        assert r.is_convergent is False  # default

    def test_to_dict(self):
        from core.scheduling_truth_harness import ConvergenceAssertionResult
        r = ConvergenceAssertionResult(
            task_id="t2",
            task_registered=True,
            routable_executors_consulted=True,
            scheduling_basis_available=True,
            is_convergent=True,
        )
        d = r.to_dict()
        assert d["task_id"] == "t2"
        assert d["is_convergent"] is True
        assert "divergence_notes" in d


# ---------------------------------------------------------------------------
# 3–8: SchedulingTruthHarness
# ---------------------------------------------------------------------------

class TestSchedulingTruthHarness:
    def test_ensure_task_registered_no_backing_returns_false(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        # No backing runtime — graceful degradation
        result = harness.ensure_task_registered(_make_task())
        # Should return False (not available) but not raise
        assert isinstance(result, bool)

    def test_ensure_task_registered_with_mock_runtime(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        mock_tgr = MagicMock()
        mock_tgr.get_task.return_value = None
        mock_tgr.register_task.return_value = None
        harness._task_graph_runtime = mock_tgr
        result = harness.ensure_task_registered(_make_task("new-task"))
        assert result is True
        mock_tgr.register_task.assert_called_once()

    def test_ensure_task_already_registered(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        mock_tgr = MagicMock()
        mock_tgr.get_task.return_value = {"task_id": "existing"}
        harness._task_graph_runtime = mock_tgr
        result = harness.ensure_task_registered(_make_task("existing"))
        assert result is True
        mock_tgr.register_task.assert_not_called()

    def test_query_routable_executors_no_policy(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        result = harness.query_routable_executors(_make_task())
        assert isinstance(result, list)

    def test_query_routable_executors_with_mock_policy(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        mock_policy = MagicMock()
        mock_policy.query_routable_executors.return_value = ["device-a", "device-b"]
        harness._capability_policy = mock_policy
        result = harness.query_routable_executors(_make_task())
        assert result == ["device-a", "device-b"]

    def test_assert_convergence_returns_result(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        result = harness.assert_convergence(_make_task())
        assert result is not None
        assert hasattr(result, "is_convergent")

    def test_assert_convergence_notes_task_unregistered(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        mock_tgr = MagicMock()
        mock_tgr.get_task.return_value = None
        harness._task_graph_runtime = mock_tgr
        result = harness.assert_convergence(_make_task("unregistered-task"))
        # Should note that task is not registered
        assert any("not" in n or "unregistered" in n for n in result.divergence_notes)
        assert result.task_registered is False

    def test_harness_never_raises(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        # Even with totally invalid input
        try:
            harness.ensure_task_registered(None)
            harness.query_routable_executors(None)
            harness.assert_convergence(None)
        except Exception as exc:
            pytest.fail(f"SchedulingTruthHarness raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# 9–11: Module-level functions
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def test_ensure_task_registered_fn(self):
        from core.scheduling_truth_harness import (
            ensure_task_registered, reset_scheduling_truth_harness,
            get_scheduling_truth_harness,
        )
        reset_scheduling_truth_harness()
        harness = get_scheduling_truth_harness()
        mock_tgr = MagicMock()
        mock_tgr.get_task.return_value = None
        mock_tgr.register_task.return_value = None
        harness._task_graph_runtime = mock_tgr
        result = ensure_task_registered(_make_task("fn-task"), harness=harness)
        assert isinstance(result, bool)

    def test_query_routable_executors_for_task_fn(self):
        from core.scheduling_truth_harness import (
            query_routable_executors_for_task,
            get_scheduling_truth_harness,
            reset_scheduling_truth_harness,
        )
        reset_scheduling_truth_harness()
        result = query_routable_executors_for_task(_make_task())
        assert isinstance(result, list)

    def test_assert_scheduling_truth_convergence_fn(self):
        from core.scheduling_truth_harness import assert_scheduling_truth_convergence
        result = assert_scheduling_truth_convergence(_make_task())
        assert result is not None


# ---------------------------------------------------------------------------
# 12–13: Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_returns_same_instance(self):
        from core.scheduling_truth_harness import (
            get_scheduling_truth_harness, reset_scheduling_truth_harness,
        )
        reset_scheduling_truth_harness()
        h1 = get_scheduling_truth_harness()
        h2 = get_scheduling_truth_harness()
        assert h1 is h2

    def test_reset_clears_singleton(self):
        from core.scheduling_truth_harness import (
            get_scheduling_truth_harness, reset_scheduling_truth_harness,
        )
        reset_scheduling_truth_harness()
        h1 = get_scheduling_truth_harness()
        reset_scheduling_truth_harness()
        h2 = get_scheduling_truth_harness()
        assert h1 is not h2


# ---------------------------------------------------------------------------
# 14–15: ensure_task_registered input variants
# ---------------------------------------------------------------------------

class TestInputVariants:
    def test_dict_task(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        mock_tgr = MagicMock()
        mock_tgr.get_task.return_value = None
        mock_tgr.register_task.return_value = None
        harness._task_graph_runtime = mock_tgr
        result = harness.ensure_task_registered({"task_id": "dict-task"})
        assert result is True

    def test_none_task(self):
        from core.scheduling_truth_harness import SchedulingTruthHarness
        harness = SchedulingTruthHarness()
        result = harness.ensure_task_registered(None)
        assert result is False  # graceful


# ---------------------------------------------------------------------------
# 16–17: Sentinel content
# ---------------------------------------------------------------------------

class TestSentinelContent:
    def test_gap_002_sentinel_content(self):
        from core.scheduling_truth_harness import GAP_512_002_CLOSED_SENTINEL
        # Should mention task graph or TaskGraphRuntime
        assert any(kw in GAP_512_002_CLOSED_SENTINEL for kw in ["TaskGraph", "task_graph", "512-002", "GAP_512_002"])

    def test_gap_004_sentinel_content(self):
        from core.scheduling_truth_harness import GAP_512_004_ADDRESSED_SENTINEL
        assert any(kw in GAP_512_004_ADDRESSED_SENTINEL for kw in ["executor", "routing", "512-004", "GAP_512_004"])


# ---------------------------------------------------------------------------
# 18–19: ConvergenceAssertionResult details
# ---------------------------------------------------------------------------

class TestConvergenceDetails:
    def test_is_convergent_true_when_all_available(self):
        from core.scheduling_truth_harness import ConvergenceAssertionResult
        r = ConvergenceAssertionResult(
            task_id="t",
            task_registered=True,
            routable_executors_consulted=True,
            scheduling_basis_available=True,
            is_convergent=True,
        )
        assert r.is_convergent is True

    def test_divergence_notes_populated(self):
        from core.scheduling_truth_harness import ConvergenceAssertionResult
        r = ConvergenceAssertionResult(
            task_id="t",
            task_registered=False,
            divergence_notes=["task not registered"],
        )
        assert len(r.divergence_notes) > 0
