#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_multi_device_runtime_harness.py
===========================================
Tests for core/multi_device_runtime_harness.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  DeviceHealthEvent construction and to_dict.
  3.  RuntimeHarnessResult construction and to_dict.
  4.  MultiDeviceRuntimeHarness — on_coordinator_state_updated persists snapshot.
  5.  MultiDeviceRuntimeHarness — on_coordinator_state_updated with no persistence.
  6.  MultiDeviceRuntimeHarness — on_device_health_changed with formation rebalance.
  7.  MultiDeviceRuntimeHarness — on_device_health_changed healthy device — no rebalance.
  8.  MultiDeviceRuntimeHarness — on_device_health_changed without formation.
  9.  MultiDeviceRuntimeHarness — on_task_admitted_for_dispatch returns result.
  10. MultiDeviceRuntimeHarness — on_task_admitted_for_dispatch never blocks dispatch.
  11. MultiDeviceRuntimeHarness — recover_sessions returns list.
  12. Module-level on_coordinator_state_updated function.
  13. Module-level on_device_health_changed function.
  14. Module-level on_task_admitted_for_dispatch function.
  15. get_multi_device_runtime_harness returns singleton.
  16. reset_multi_device_runtime_harness clears singleton.
  17. RuntimeHarnessResult default success True.
  18. DeviceHealthEvent session_id propagates.
  19. on_coordinator_state_updated graceful with None.
  20. Harness never raises.
"""

from __future__ import annotations

import tempfile
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_group_with_fallback():
    from core.device_formation.formation_group import DeviceFormationGroup
    from core.device_formation.formation_role import FormationMember, FormationRole
    members = [
        FormationMember(device_id="source-dev", role=FormationRole.SOURCE, reason="s"),
        FormationMember(device_id="primary-dev", role=FormationRole.PRIMARY_EXECUTION, reason="p"),
        FormationMember(device_id="fallback-dev", role=FormationRole.FALLBACK, reason="f"),
    ]
    return DeviceFormationGroup(
        source_device_id="source-dev",
        members=members,
        runtime_domain_intent="cross_device",
    )


# ---------------------------------------------------------------------------
# 1: Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.multi_device_runtime_harness import MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY
        assert isinstance(MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY, str)

    def test_gap_closure_sentinel(self):
        from core.multi_device_runtime_harness import MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL
        assert isinstance(MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL, str)
        assert "GAP_CLOSURE" in MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL

    def test_wires_policy(self):
        from core.multi_device_runtime_harness import HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY
        assert isinstance(HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY, str)
        assert "persistence" in HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY.lower()
        assert "rebalance" in HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY.lower()


# ---------------------------------------------------------------------------
# 2–3: Data classes
# ---------------------------------------------------------------------------

class TestDeviceHealthEvent:
    def test_construction(self):
        from core.multi_device_runtime_harness import DeviceHealthEvent
        e = DeviceHealthEvent(device_id="d1", health_score=0.5, event_type="disconnect")
        assert e.device_id == "d1"
        assert e.health_score == 0.5

    def test_to_dict(self):
        from core.multi_device_runtime_harness import DeviceHealthEvent
        e = DeviceHealthEvent(device_id="d2", health_score=0.9, session_id="s1")
        d = e.to_dict()
        assert d["device_id"] == "d2"
        assert d["session_id"] == "s1"


class TestRuntimeHarnessResult:
    def test_default_success_true(self):
        from core.multi_device_runtime_harness import RuntimeHarnessResult
        r = RuntimeHarnessResult(operation="test")
        assert r.success is True

    def test_to_dict(self):
        from core.multi_device_runtime_harness import RuntimeHarnessResult
        r = RuntimeHarnessResult(
            operation="test",
            rebalance_triggered=True,
            snapshot_saved=False,
        )
        d = r.to_dict()
        assert d["operation"] == "test"
        assert d["rebalance_triggered"] is True


# ---------------------------------------------------------------------------
# 4–11: MultiDeviceRuntimeHarness
# ---------------------------------------------------------------------------

class TestMultiDeviceRuntimeHarness:
    def test_on_coordinator_state_updated_persists_snapshot(self, tmp_path):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        harness = MultiDeviceRuntimeHarness()
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        harness._persistence_store = store
        result = harness.on_coordinator_state_updated({
            "session_id": "coord-session",
            "coordinator_id": "c-1",
            "overall_status": "coordinating",
        })
        assert result.snapshot_saved is True

    def test_on_coordinator_state_updated_no_persistence(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        # No backing persistence store
        result = harness.on_coordinator_state_updated({
            "session_id": "orphan-session",
            "coordinator_id": "c-2",
            "overall_status": "coordinating",
        })
        # Graceful — may not save but should not raise
        assert result is not None
        assert hasattr(result, "snapshot_saved")

    def test_on_device_health_changed_triggers_rebalance(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness, DeviceHealthEvent
        harness = MultiDeviceRuntimeHarness()
        group = _make_group_with_fallback()
        event = DeviceHealthEvent(
            device_id="primary-dev",
            health_score=0.0,
            is_reachable=False,
            event_type="disconnect",
        )
        result = harness.on_device_health_changed(event, formation=group)
        assert result is not None
        assert result.rebalance_triggered is True

    def test_on_device_health_changed_healthy_no_rebalance(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness, DeviceHealthEvent
        harness = MultiDeviceRuntimeHarness()
        group = _make_group_with_fallback()
        event = DeviceHealthEvent(
            device_id="primary-dev",
            health_score=0.95,
            is_reachable=True,
            event_type="health_update",
        )
        result = harness.on_device_health_changed(event, formation=group)
        assert result is not None
        assert result.rebalance_triggered is False

    def test_on_device_health_changed_without_formation(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness, DeviceHealthEvent
        harness = MultiDeviceRuntimeHarness()
        event = DeviceHealthEvent(
            device_id="some-dev", health_score=0.0, is_reachable=False,
        )
        result = harness.on_device_health_changed(event, formation=None)
        assert result is not None
        assert result.rebalance_triggered is False

    def test_on_task_admitted_for_dispatch_returns_result(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        result = harness.on_task_admitted_for_dispatch(
            {"task_id": "test-task", "task_type": "relay"}
        )
        assert result is not None
        assert hasattr(result, "task_registered")
        assert hasattr(result, "routable_executor_ids")

    def test_on_task_admitted_never_blocks_dispatch(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        # Even with None task — dispatch must not be blocked
        result = harness.on_task_admitted_for_dispatch(None)
        assert result.success is True  # graceful degradation

    def test_recover_sessions_returns_list(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        result = harness.recover_sessions()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 12–14: Module-level functions
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def test_on_coordinator_state_updated_fn(self):
        from core.multi_device_runtime_harness import (
            on_coordinator_state_updated,
            get_multi_device_runtime_harness,
        )
        result = on_coordinator_state_updated({"session_id": "", "overall_status": "unknown"})
        assert result is not None

    def test_on_device_health_changed_fn(self):
        from core.multi_device_runtime_harness import on_device_health_changed, DeviceHealthEvent
        event = DeviceHealthEvent(device_id="d", health_score=0.0, is_reachable=False)
        result = on_device_health_changed(event)
        assert result is not None

    def test_on_task_admitted_for_dispatch_fn(self):
        from core.multi_device_runtime_harness import on_task_admitted_for_dispatch
        result = on_task_admitted_for_dispatch({"task_id": "fn-task"})
        assert result is not None


# ---------------------------------------------------------------------------
# 15–16: Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_returns_same_instance(self):
        from core.multi_device_runtime_harness import (
            get_multi_device_runtime_harness, reset_multi_device_runtime_harness,
        )
        reset_multi_device_runtime_harness()
        h1 = get_multi_device_runtime_harness()
        h2 = get_multi_device_runtime_harness()
        assert h1 is h2

    def test_reset_clears_singleton(self):
        from core.multi_device_runtime_harness import (
            get_multi_device_runtime_harness, reset_multi_device_runtime_harness,
        )
        reset_multi_device_runtime_harness()
        h1 = get_multi_device_runtime_harness()
        reset_multi_device_runtime_harness()
        h2 = get_multi_device_runtime_harness()
        assert h1 is not h2


# ---------------------------------------------------------------------------
# 18–20: Edge cases and never-raises
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_health_event_session_id_propagates(self):
        from core.multi_device_runtime_harness import DeviceHealthEvent
        e = DeviceHealthEvent(
            device_id="d", health_score=0.0, is_reachable=False,
            session_id="session-abc",
        )
        assert e.session_id == "session-abc"

    def test_on_coordinator_state_updated_none_graceful(self):
        from core.multi_device_runtime_harness import MultiDeviceRuntimeHarness
        harness = MultiDeviceRuntimeHarness()
        result = harness.on_coordinator_state_updated(None)
        assert result is not None
        assert result.snapshot_saved is False

    def test_harness_never_raises(self):
        from core.multi_device_runtime_harness import (
            MultiDeviceRuntimeHarness, DeviceHealthEvent,
        )
        harness = MultiDeviceRuntimeHarness()
        try:
            harness.on_coordinator_state_updated(None)
            harness.on_coordinator_state_updated({})
            harness.on_device_health_changed(
                DeviceHealthEvent(device_id="x", health_score=0.0, is_reachable=False)
            )
            harness.on_task_admitted_for_dispatch(None)
            harness.recover_sessions()
        except Exception as exc:
            pytest.fail(f"MultiDeviceRuntimeHarness raised unexpectedly: {exc}")
