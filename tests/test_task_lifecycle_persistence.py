#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_task_lifecycle_persistence.py
=========================================
Tests for the durable in-flight task lifecycle persistence store and
resume-aware recovery semantics.

Coverage
--------
A — Module sentinels are importable non-empty strings.
B — TaskLifecyclePersistenceStore: save and load_all round-trip.
C — save: idempotent; latest write wins.
D — delete: removes a persisted record; returns True.
E — delete: returns False when task_id not present.
F — clear: removes all records; returns count.
G — record_count: reflects current number of persisted records.
H — load_all: returns empty list when no file exists.
I — TaskEnvelopeLifecycleRegistry: register persists when store provided.
J — TaskEnvelopeLifecycleRegistry: complete removes from store.
K — TaskEnvelopeLifecycleRegistry: fail removes from store.
L — TaskEnvelopeLifecycleRegistry: cancel_timed_out removes from store.
M — restore_from_store: re-inserts non-timed-out records into registry.
N — restore_from_store: skips records that have timed out.
O — restore_from_store: skips duplicate task_ids already in pending.
P — restore_from_store: annotates recovered records with recovery_classification.
Q — restore_from_store: returns correct bucket counts.
R — RuntimeRecoveryReport: has in_flight_tasks_recovered and timed_out fields.
S — RuntimeRestartRecoveryCoordinator: step 5 sets in_flight_tasks_recovered.
T — RuntimeRestartRecoveryCoordinator: step 5 sets in_flight_tasks_timed_out.
U — run_startup_recovery: accepts lifecycle_registry and lifecycle_persistence_store.
V — TASK_STATE_RECOVERY_CLASSIFICATION: contains expected keys.
W — Full round-trip: persist → simulate restart → recover → verify classification.
X — get/reset singleton functions.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import pytest

from core.task_lifecycle_persistence import (
    IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY,
    TASK_STATE_RECOVERY_CLASSIFICATION,
    TASK_RECOVERY_POLICY,
    TaskLifecyclePersistenceStore,
    get_task_lifecycle_persistence_store,
    reset_task_lifecycle_persistence_store,
)
from core.task_envelope_lifecycle_registry import (
    TaskEnvelopeLifecycleRegistry,
    LifecycleOwner,
    PendingEnvelopeRecord,
    reset_lifecycle_registry,
    LIFECYCLE_REGISTRY_DURABILITY_POLICY,
)
from core.runtime_restart_recovery import (
    RuntimeRecoveryReport,
    RuntimeRestartRecoveryCoordinator,
    run_startup_recovery,
    IN_FLIGHT_TASK_RECOVERY_POLICY,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_dir: str) -> TaskLifecyclePersistenceStore:
    return TaskLifecyclePersistenceStore(store_dir=tmp_dir)


def _make_record_dict(
    task_id: str,
    owner: str = "device_dispatch",
    timeout: float = 60.0,
    registered_at: Optional[float] = None,
    tool_name: str = "test_tool",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "trace_id": f"trace-{task_id}",
        "target_device_id": "dev-test",
        "tool_name": tool_name,
        "owner": owner,
        "timeout": timeout,
        "registered_at": registered_at if registered_at is not None else time.time(),
        "metadata": {},
    }


class _FakeEnvelope:
    """Minimal TaskEnvelope-like object for testing."""

    def __init__(
        self,
        task_id: str,
        tool_name: str = "test_tool",
        target: str = "dev-test",
        timeout: float = 60.0,
        trace_id: str = "",
    ) -> None:
        self.task_id = task_id
        self.tool_name = tool_name
        self.target = target
        self.timeout = timeout
        self.trace_id = trace_id


def _make_mesh_session_store(tmp_dir: str):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir)


def _make_body_mesh_store(tmp_dir: str):
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    path = os.path.join(tmp_dir, "bm_snap.json")
    return BodyMeshPersistenceStore(store_path=path)


class _FakeBodyMeshRegistry:
    def register(self, device_id, roles=None, session_id=None, metadata=None):
        pass

    def list_entries(self):
        return []


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_durability_policy(self):
        assert isinstance(IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY, str)
        assert IN_FLIGHT_TASK_LIFECYCLE_IS_DURABLE_POLICY

    def test_recovery_classification(self):
        assert isinstance(TASK_STATE_RECOVERY_CLASSIFICATION, dict)
        assert "device_dispatch" in TASK_STATE_RECOVERY_CLASSIFICATION
        assert "gateway_ingress" in TASK_STATE_RECOVERY_CLASSIFICATION
        assert "_unknown" in TASK_STATE_RECOVERY_CLASSIFICATION

    def test_recovery_policy(self):
        assert isinstance(TASK_RECOVERY_POLICY, str)
        assert TASK_RECOVERY_POLICY

    def test_lifecycle_registry_durability_policy(self):
        assert isinstance(LIFECYCLE_REGISTRY_DURABILITY_POLICY, str)
        assert LIFECYCLE_REGISTRY_DURABILITY_POLICY

    def test_in_flight_task_recovery_policy(self):
        assert isinstance(IN_FLIGHT_TASK_RECOVERY_POLICY, str)
        assert IN_FLIGHT_TASK_RECOVERY_POLICY


# ---------------------------------------------------------------------------
# B–H — TaskLifecyclePersistenceStore
# ---------------------------------------------------------------------------

class TestPersistenceStore:
    def test_save_and_load_round_trip(self, tmp_path):
        store = _make_store(str(tmp_path))
        rec = _make_record_dict("task-1")
        store.save(rec)
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0]["task_id"] == "task-1"

    def test_save_idempotent_latest_wins(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("task-1"))
        store.save({**_make_record_dict("task-1"), "tool_name": "new_tool"})
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0]["tool_name"] == "new_tool"

    def test_delete_existing(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("task-del"))
        assert store.delete("task-del") is True
        assert store.load_all() == []

    def test_delete_nonexistent(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.delete("not-here") is False

    def test_clear(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("task-a"))
        store.save(_make_record_dict("task-b"))
        count = store.clear()
        assert count == 2
        assert store.load_all() == []

    def test_record_count(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.record_count() == 0
        store.save(_make_record_dict("task-x"))
        assert store.record_count() == 1

    def test_load_all_empty_when_no_file(self, tmp_path):
        store = _make_store(str(tmp_path / "no_such_dir"))
        # No file exists yet; should return []
        result = store.load_all()
        assert result == []

    def test_save_multiple(self, tmp_path):
        store = _make_store(str(tmp_path))
        for i in range(5):
            store.save(_make_record_dict(f"task-{i}"))
        loaded = store.load_all()
        assert len(loaded) == 5


# ---------------------------------------------------------------------------
# I–L — Registry persistence integration
# ---------------------------------------------------------------------------

class TestRegistryPersistence:
    def test_register_persists_to_store(self, tmp_path):
        store = _make_store(str(tmp_path))
        registry = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        env = _FakeEnvelope("t1")
        registry.register(env, owner=LifecycleOwner.DEVICE_DISPATCH)
        assert store.record_count() == 1
        loaded = store.load_all()
        assert loaded[0]["task_id"] == "t1"

    def test_complete_removes_from_store(self, tmp_path):
        store = _make_store(str(tmp_path))
        registry = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        env = _FakeEnvelope("t2")
        registry.register(env)
        assert store.record_count() == 1
        registry.complete("t2", {"ok": True})
        assert store.record_count() == 0

    def test_fail_removes_from_store(self, tmp_path):
        store = _make_store(str(tmp_path))
        registry = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        env = _FakeEnvelope("t3")
        registry.register(env)
        assert store.record_count() == 1
        registry.fail("t3", "error!")
        assert store.record_count() == 0

    def test_cancel_timed_out_removes_from_store(self, tmp_path):
        store = _make_store(str(tmp_path))
        registry = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        # Register with very short timeout so it expires immediately
        env = _FakeEnvelope("t4", timeout=0.001)
        registry.register(env)
        assert store.record_count() == 1
        time.sleep(0.05)
        cancelled = registry.cancel_timed_out()
        assert "t4" in cancelled
        assert store.record_count() == 0


# ---------------------------------------------------------------------------
# M–Q — restore_from_store
# ---------------------------------------------------------------------------

class TestRestoreFromStore:
    def test_restore_non_timed_out_records(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("r1", owner="device_dispatch", timeout=60.0))
        store.save(_make_record_dict("r2", owner="routing", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        result = registry.restore_from_store(store=store)
        assert "r1" in result["recovered"]
        assert "r2" in result["recovered"]
        assert registry.pending_count() == 2

    def test_restore_skips_timed_out_records(self, tmp_path):
        store = _make_store(str(tmp_path))
        # registered 120 seconds ago with 30 s timeout → timed out
        old_ts = time.time() - 120.0
        store.save(_make_record_dict("old1", timeout=30.0, registered_at=old_ts))
        registry = TaskEnvelopeLifecycleRegistry()
        result = registry.restore_from_store(store=store)
        assert "old1" in result["timed_out"]
        assert registry.pending_count() == 0
        # Timed-out records should be removed from the store
        assert store.record_count() == 0

    def test_restore_skips_duplicates(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("dup1", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        # Pre-populate with same task_id
        env = _FakeEnvelope("dup1")
        registry.register(env)
        assert registry.pending_count() == 1
        result = registry.restore_from_store(store=store)
        assert "dup1" in result["skipped"]
        # Count should still be 1 (not doubled)
        assert registry.pending_count() == 1

    def test_restore_annotates_recovery_classification(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("cls1", owner="device_dispatch", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        result = registry.restore_from_store(store=store)
        assert "cls1" in result["recovered"]
        record = registry.get_record("cls1")
        assert record is not None
        classification = record.metadata.get("recovery_classification", "")
        assert classification == "resumable_if_device_reconnects"

    def test_restore_classification_replay_required(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("cls2", owner="gateway_ingress", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        registry.restore_from_store(store=store)
        record = registry.get_record("cls2")
        assert record is not None
        assert record.metadata.get("recovery_classification") == "replay_required"

    def test_restore_returns_bucket_counts(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("live1", timeout=60.0))
        old_ts = time.time() - 120.0
        store.save(_make_record_dict("dead1", timeout=30.0, registered_at=old_ts))
        registry = TaskEnvelopeLifecycleRegistry()
        result = registry.restore_from_store(store=store)
        assert len(result["recovered"]) == 1
        assert len(result["timed_out"]) == 1
        assert isinstance(result["skipped"], list)


# ---------------------------------------------------------------------------
# R–U — RuntimeRecoveryReport and Coordinator integration
# ---------------------------------------------------------------------------

class TestCoordinatorInFlightRecovery:
    def _make_coord(self, tmp_path, lifecycle_registry=None, lifecycle_store=None):
        ms = _make_mesh_session_store(str(tmp_path))
        bm = _make_body_mesh_store(str(tmp_path))
        return RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms,
            body_mesh_store=bm,
            body_mesh_registry=_FakeBodyMeshRegistry(),
            lifecycle_registry=lifecycle_registry,
            lifecycle_persistence_store=lifecycle_store,
        )

    def test_report_has_in_flight_fields(self, tmp_path):
        coord = self._make_coord(tmp_path)
        report = coord.run_recovery()
        assert hasattr(report, "in_flight_tasks_recovered")
        assert hasattr(report, "in_flight_tasks_timed_out")

    def test_to_dict_has_in_flight_keys(self, tmp_path):
        coord = self._make_coord(tmp_path)
        report = coord.run_recovery()
        d = report.to_dict()
        assert "in_flight_tasks_recovered" in d
        assert "in_flight_tasks_timed_out" in d

    def test_step5_sets_recovered_count(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("live-a", timeout=60.0))
        store.save(_make_record_dict("live-b", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        coord = self._make_coord(tmp_path, lifecycle_registry=registry, lifecycle_store=store)
        report = coord.run_recovery()
        assert report.in_flight_tasks_recovered == 2

    def test_step5_sets_timed_out_count(self, tmp_path):
        store = _make_store(str(tmp_path))
        old_ts = time.time() - 120.0
        store.save(_make_record_dict("old-a", timeout=30.0, registered_at=old_ts))
        registry = TaskEnvelopeLifecycleRegistry()
        coord = self._make_coord(tmp_path, lifecycle_registry=registry, lifecycle_store=store)
        report = coord.run_recovery()
        assert report.in_flight_tasks_timed_out == 1
        assert report.in_flight_tasks_recovered == 0

    def test_run_startup_recovery_accepts_lifecycle_params(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_record_dict("su-1", timeout=60.0))
        registry = TaskEnvelopeLifecycleRegistry()
        report = run_startup_recovery(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=_FakeBodyMeshRegistry(),
            lifecycle_registry=registry,
            lifecycle_persistence_store=store,
        )
        assert isinstance(report, RuntimeRecoveryReport)
        assert report.in_flight_tasks_recovered == 1

    def test_empty_store_gives_zero_counts(self, tmp_path):
        store = _make_store(str(tmp_path))
        registry = TaskEnvelopeLifecycleRegistry()
        coord = self._make_coord(tmp_path, lifecycle_registry=registry, lifecycle_store=store)
        report = coord.run_recovery()
        assert report.in_flight_tasks_recovered == 0
        assert report.in_flight_tasks_timed_out == 0


# ---------------------------------------------------------------------------
# V — TASK_STATE_RECOVERY_CLASSIFICATION keys
# ---------------------------------------------------------------------------

class TestRecoveryClassification:
    def test_expected_keys_present(self):
        expected = {
            "gateway_ingress",
            "routing",
            "device_dispatch",
            "cross_device",
            "result_completion",
            "_unknown",
        }
        assert expected.issubset(set(TASK_STATE_RECOVERY_CLASSIFICATION.keys()))

    def test_device_dispatch_is_resumable(self):
        assert "resumable" in TASK_STATE_RECOVERY_CLASSIFICATION["device_dispatch"]

    def test_gateway_ingress_is_replay(self):
        assert "replay" in TASK_STATE_RECOVERY_CLASSIFICATION["gateway_ingress"]

    def test_result_completion_is_terminal(self):
        assert "terminal" in TASK_STATE_RECOVERY_CLASSIFICATION["result_completion"]


# ---------------------------------------------------------------------------
# W — Full round-trip: persist → simulate restart → recover
# ---------------------------------------------------------------------------

class TestFullRoundTrip:
    def test_persist_then_recover_after_simulated_restart(self, tmp_path):
        """
        Simulate a process restart by:
        1. Creating a registry + store and registering tasks.
        2. Discarding the registry (simulates process death).
        3. Creating a new registry and running the recovery coordinator.
        4. Verifying the in-flight tasks are present in the new registry.
        """
        store = _make_store(str(tmp_path))

        # Step 1: "process A" — register two tasks
        registry_a = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        env1 = _FakeEnvelope("rt-task-1", timeout=120.0)
        env2 = _FakeEnvelope("rt-task-2", timeout=120.0)
        registry_a.register(env1, owner=LifecycleOwner.DEVICE_DISPATCH)
        registry_a.register(env2, owner=LifecycleOwner.ROUTING)
        assert store.record_count() == 2

        # Step 2: discard registry_a (simulates crash / restart)
        del registry_a

        # Step 3: "process B" — new registry, run recovery
        registry_b = TaskEnvelopeLifecycleRegistry()
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=_make_mesh_session_store(str(tmp_path)),
            body_mesh_store=_make_body_mesh_store(str(tmp_path)),
            body_mesh_registry=_FakeBodyMeshRegistry(),
            lifecycle_registry=registry_b,
            lifecycle_persistence_store=store,
        )
        report = coord.run_recovery()

        # Step 4: verify
        assert report.in_flight_tasks_recovered == 2
        assert registry_b.is_pending("rt-task-1")
        assert registry_b.is_pending("rt-task-2")

        rec1 = registry_b.get_record("rt-task-1")
        assert rec1 is not None
        assert rec1.metadata.get("recovery_classification") == "resumable_if_device_reconnects"

        rec2 = registry_b.get_record("rt-task-2")
        assert rec2 is not None
        assert rec2.metadata.get("recovery_classification") == "replay_required"

    def test_completed_task_not_recovered(self, tmp_path):
        """
        A task that was completed before the restart should not appear
        in the recovered registry (store entry was deleted on complete).
        """
        store = _make_store(str(tmp_path))
        registry_a = TaskEnvelopeLifecycleRegistry(persistence_store=store)
        env = _FakeEnvelope("done-task", timeout=120.0)
        registry_a.register(env, owner=LifecycleOwner.DEVICE_DISPATCH)
        registry_a.complete("done-task", {"ok": True})
        assert store.record_count() == 0

        registry_b = TaskEnvelopeLifecycleRegistry()
        result = registry_b.restore_from_store(store=store)
        assert "done-task" not in result["recovered"]
        assert registry_b.pending_count() == 0


# ---------------------------------------------------------------------------
# X — get/reset singleton functions
# ---------------------------------------------------------------------------

class TestSingletonManagement:
    def test_get_singleton(self, tmp_path):
        reset_task_lifecycle_persistence_store()
        s1 = get_task_lifecycle_persistence_store(store_dir=str(tmp_path))
        s2 = get_task_lifecycle_persistence_store()
        assert s1 is s2
        reset_task_lifecycle_persistence_store()

    def test_reset_clears_singleton(self, tmp_path):
        reset_task_lifecycle_persistence_store()
        s1 = get_task_lifecycle_persistence_store(store_dir=str(tmp_path))
        reset_task_lifecycle_persistence_store()
        s2 = get_task_lifecycle_persistence_store(store_dir=str(tmp_path))
        assert s1 is not s2
        reset_task_lifecycle_persistence_store()
