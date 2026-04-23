#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_recovered_lifecycle_dispatch.py
==========================================
Tests for the conversion of recovered lifecycle state into operational runtime
execution behaviour (RECOVERED_LIFECYCLE_DISPATCH_POLICY).

Coverage
--------
A  — RECOVERED_LIFECYCLE_DISPATCH_POLICY sentinel is importable and non-empty.
B  — RuntimeRecoveryReport has inflight_tasks_dispatch_actions_taken field.
C  — Coordinator: RESUMABLE task → DEVICE_DISPATCH ownership in registry.
D  — Coordinator: REPLAY_ONLY task → ROUTING ownership in registry.
E  — Coordinator: REISSUABLE task → GATEWAY_INGRESS ownership in registry.
F  — Coordinator: TERMINAL_ON_INTERRUPT task → NOT added to pending registry.
G  — Coordinator: duplicate guard — already-pending task is not overwritten.
H  — Coordinator: dispatch_actions_taken count matches non-terminal records.
I  — Coordinator: recovered metadata is stamped on dispatched record.
J  — Registry restore_from_snapshot: TERMINAL records excluded.
K  — Registry restore_from_snapshot: RESUMABLE → DEVICE_DISPATCH.
L  — Registry restore_from_snapshot: REPLAY_ONLY → ROUTING.
M  — Registry restore_from_snapshot: REISSUABLE → GATEWAY_INGRESS.
N  — Registry restore_from_snapshot: already-pending record not overwritten.
O  — to_dict includes inflight_tasks_dispatch_actions_taken key.
P  — Mixed dispositions: counts and ownership all correct.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mesh_session_store(tmp_dir: str):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir)


def _make_body_mesh_store(tmp_dir: str):
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    path = os.path.join(tmp_dir, "bm_snap.json")
    return BodyMeshPersistenceStore(store_path=path)


def _make_task_lifecycle_store(tmp_dir: str):
    from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
    path = os.path.join(tmp_dir, "tl.json")
    return TaskLifecyclePersistenceStore(store_path=path)


def _save_snapshot(store, records: List[Dict[str, Any]]) -> None:
    from core.task_lifecycle_persistence import save_task_lifecycle_snapshot
    save_task_lifecycle_snapshot(records, store=store)


def _record(
    task_id: str,
    owner: str,
    tool_name: str = "test_tool",
    target_device_id: str = "dev_01",
    trace_id: str = "",
) -> Dict[str, Any]:
    """Build a minimal serialised PendingEnvelopeRecord dict."""
    return {
        "task_id": task_id,
        "trace_id": trace_id or f"trace_{task_id}",
        "target_device_id": target_device_id,
        "tool_name": tool_name,
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time() - 10.0,
        "metadata": {},
    }


class FakeBodyMeshRegistry:
    def __init__(self):
        self._entries: List[Dict] = []

    def register(self, device_id, roles=None, session_id=None, metadata=None):
        self._entries.append({"device_id": device_id})
        return self._entries[-1]

    def list_entries(self):
        return []


# ---------------------------------------------------------------------------
# A — Sentinel
# ---------------------------------------------------------------------------

class TestSentinel:
    def test_policy_sentinel_importable(self):
        from core.runtime_restart_recovery import RECOVERED_LIFECYCLE_DISPATCH_POLICY
        assert isinstance(RECOVERED_LIFECYCLE_DISPATCH_POLICY, str)
        assert RECOVERED_LIFECYCLE_DISPATCH_POLICY

    def test_policy_mentions_resumable(self):
        from core.runtime_restart_recovery import RECOVERED_LIFECYCLE_DISPATCH_POLICY
        assert "RESUMABLE" in RECOVERED_LIFECYCLE_DISPATCH_POLICY or \
               "resumable" in RECOVERED_LIFECYCLE_DISPATCH_POLICY.lower()

    def test_policy_mentions_terminal(self):
        from core.runtime_restart_recovery import RECOVERED_LIFECYCLE_DISPATCH_POLICY
        assert "TERMINAL" in RECOVERED_LIFECYCLE_DISPATCH_POLICY or \
               "terminal" in RECOVERED_LIFECYCLE_DISPATCH_POLICY.lower()

    def test_policy_mentions_not_registered(self):
        from core.runtime_restart_recovery import RECOVERED_LIFECYCLE_DISPATCH_POLICY
        lower = RECOVERED_LIFECYCLE_DISPATCH_POLICY.lower()
        assert "not registered" in lower or "NOT registered" in RECOVERED_LIFECYCLE_DISPATCH_POLICY


# ---------------------------------------------------------------------------
# B — RuntimeRecoveryReport field
# ---------------------------------------------------------------------------

class TestReportField:
    def test_dispatch_actions_field_exists(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "inflight_tasks_dispatch_actions_taken")
        assert r.inflight_tasks_dispatch_actions_taken == 0

    def test_to_dict_includes_dispatch_actions(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        d = r.to_dict()
        assert "inflight_tasks_dispatch_actions_taken" in d


# ---------------------------------------------------------------------------
# C–H — Coordinator dispatch behaviour
# ---------------------------------------------------------------------------

class TestCoordinatorDispatch:
    """Tests C through H: coordinator correctly registers recovered tasks."""

    def _coord(self, tmp_dir: str, records: List[Dict[str, Any]]):
        ms_store = _make_mesh_session_store(tmp_dir)
        bm_store = _make_body_mesh_store(tmp_dir)
        tl_store = _make_task_lifecycle_store(tmp_dir)
        _save_snapshot(tl_store, records)
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
        return RuntimeRestartRecoveryCoordinator(
            mesh_session_store=ms_store,
            body_mesh_store=bm_store,
            body_mesh_registry=FakeBodyMeshRegistry(),
            task_lifecycle_store=tl_store,
        )

    def test_C_resumable_task_gets_device_dispatch_ownership(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            coord = self._coord(
                str(tmp_path),
                [_record("task-resumable-1", "device_dispatch")],
            )
            coord.run_recovery()
            registry = get_lifecycle_registry()
            rec = registry.get_record("task-resumable-1")
            assert rec is not None, "RESUMABLE task must be added to registry"
            assert rec.owner == LifecycleOwner.DEVICE_DISPATCH
        finally:
            reset_lifecycle_registry()

    def test_D_replay_only_task_gets_routing_ownership(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            coord = self._coord(
                str(tmp_path),
                [_record("task-replay-1", "routing")],
            )
            coord.run_recovery()
            registry = get_lifecycle_registry()
            rec = registry.get_record("task-replay-1")
            assert rec is not None, "REPLAY_ONLY task must be added to registry"
            assert rec.owner == LifecycleOwner.ROUTING
        finally:
            reset_lifecycle_registry()

    def test_E_reissuable_task_gets_gateway_ingress_ownership(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            coord = self._coord(
                str(tmp_path),
                [_record("task-reissuable-1", "gateway_ingress")],
            )
            coord.run_recovery()
            registry = get_lifecycle_registry()
            rec = registry.get_record("task-reissuable-1")
            assert rec is not None, "REISSUABLE task must be added to registry"
            assert rec.owner == LifecycleOwner.GATEWAY_INGRESS
        finally:
            reset_lifecycle_registry()

    def test_F_terminal_task_not_added_to_registry(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )
        reset_lifecycle_registry()
        try:
            coord = self._coord(
                str(tmp_path),
                [_record("task-terminal-1", "result_completion")],
            )
            coord.run_recovery()
            registry = get_lifecycle_registry()
            assert not registry.is_pending("task-terminal-1"), \
                "TERMINAL_ON_INTERRUPT task must NOT be added to pending registry"
        finally:
            reset_lifecycle_registry()

    def test_G_duplicate_guard_does_not_overwrite_live_record(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            registry = get_lifecycle_registry()
            # Pre-populate the registry with the same task_id
            import dataclasses as _dc
            from core.task_envelope_lifecycle_registry import PendingEnvelopeRecord
            live_record = PendingEnvelopeRecord(
                task_id="task-dup-1",
                trace_id="live-trace",
                target_device_id="dev_live",
                tool_name="live_tool",
                owner=LifecycleOwner.RESULT_COMPLETION,
                timeout=60.0,
                registered_at=time.time(),
                future=None,
                metadata={"source": "live"},
            )
            registry._pending["task-dup-1"] = live_record

            coord = self._coord(
                str(tmp_path),
                [_record("task-dup-1", "routing")],
            )
            coord.run_recovery()

            # The live record must not be overwritten
            rec = registry.get_record("task-dup-1")
            assert rec is not None
            assert rec.owner == LifecycleOwner.RESULT_COMPLETION
            assert rec.metadata.get("source") == "live"
        finally:
            reset_lifecycle_registry()

    def test_H_dispatch_actions_count_excludes_terminal(self, tmp_path):
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        reset_lifecycle_registry()
        try:
            records = [
                _record("t-res", "device_dispatch"),   # RESUMABLE
                _record("t-rep", "routing"),            # REPLAY_ONLY
                _record("t-rei", "gateway_ingress"),    # REISSUABLE
                _record("t-ter", "result_completion"),  # TERMINAL
            ]
            coord = self._coord(str(tmp_path), records)
            report = coord.run_recovery()
            # 3 non-terminal actions should have been taken
            assert report.inflight_tasks_dispatch_actions_taken == 3
            assert report.inflight_tasks_terminal == 1
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# I — Recovered metadata stamping
# ---------------------------------------------------------------------------

class TestRecoveredMetadata:
    def test_I_recovered_metadata_stamped(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
        )
        reset_lifecycle_registry()
        try:
            ms_store = _make_mesh_session_store(str(tmp_path))
            bm_store = _make_body_mesh_store(str(tmp_path))
            tl_store = _make_task_lifecycle_store(str(tmp_path))
            _save_snapshot(tl_store, [_record("task-meta-1", "device_dispatch")])
            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            coord = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            coord.run_recovery()
            registry = get_lifecycle_registry()
            rec = registry.get_record("task-meta-1")
            assert rec is not None
            meta = rec.metadata
            assert "recovered_at" in meta
            assert meta.get("recovered_disposition") == "resumable"
            assert meta.get("recovery_action") == "dispatched_by_coordinator"
        finally:
            reset_lifecycle_registry()


# ---------------------------------------------------------------------------
# J–N — Registry restore_from_snapshot disposition-aware behaviour
# ---------------------------------------------------------------------------

class TestRegistryRestoreFromSnapshot:
    """Tests J through N: registry restore is disposition-aware."""

    def _make_snapshot_store(self, tmp_dir: str, records: List[Dict[str, Any]]):
        from core.task_lifecycle_persistence import TaskLifecyclePersistenceStore
        store = TaskLifecyclePersistenceStore(
            store_path=os.path.join(tmp_dir, "reg_tl.json")
        )
        from core.task_lifecycle_persistence import save_task_lifecycle_snapshot
        save_task_lifecycle_snapshot(records, store=store)
        return store

    def test_J_terminal_records_excluded(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
        )
        store = self._make_snapshot_store(
            str(tmp_path),
            [_record("treg-terminal", "result_completion")],
        )
        reg = TaskEnvelopeLifecycleRegistry()
        added = reg.restore_from_snapshot(store=store)
        assert added == 0, "TERMINAL records must not be added"
        assert not reg.is_pending("treg-terminal")

    def test_K_resumable_gets_device_dispatch(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
            LifecycleOwner,
        )
        store = self._make_snapshot_store(
            str(tmp_path),
            [_record("treg-res", "device_dispatch")],
        )
        reg = TaskEnvelopeLifecycleRegistry()
        reg.restore_from_snapshot(store=store)
        rec = reg.get_record("treg-res")
        assert rec is not None
        assert rec.owner == LifecycleOwner.DEVICE_DISPATCH

    def test_L_replay_only_gets_routing(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
            LifecycleOwner,
        )
        store = self._make_snapshot_store(
            str(tmp_path),
            [_record("treg-rep", "routing")],
        )
        reg = TaskEnvelopeLifecycleRegistry()
        reg.restore_from_snapshot(store=store)
        rec = reg.get_record("treg-rep")
        assert rec is not None
        assert rec.owner == LifecycleOwner.ROUTING

    def test_M_reissuable_gets_gateway_ingress(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
            LifecycleOwner,
        )
        store = self._make_snapshot_store(
            str(tmp_path),
            [_record("treg-rei", "gateway_ingress")],
        )
        reg = TaskEnvelopeLifecycleRegistry()
        reg.restore_from_snapshot(store=store)
        rec = reg.get_record("treg-rei")
        assert rec is not None
        assert rec.owner == LifecycleOwner.GATEWAY_INGRESS

    def test_N_already_pending_not_overwritten(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
            LifecycleOwner,
            PendingEnvelopeRecord,
        )
        store = self._make_snapshot_store(
            str(tmp_path),
            [_record("treg-dup", "routing")],
        )
        reg = TaskEnvelopeLifecycleRegistry()
        # Pre-populate with a live record
        live = PendingEnvelopeRecord(
            task_id="treg-dup",
            trace_id="live",
            target_device_id="",
            tool_name="live_tool",
            owner=LifecycleOwner.RESULT_COMPLETION,
            timeout=30.0,
            registered_at=time.time(),
            future=None,
            metadata={"live": True},
        )
        reg._pending["treg-dup"] = live
        added = reg.restore_from_snapshot(store=store)
        assert added == 0, "Existing record must not be overwritten"
        rec = reg.get_record("treg-dup")
        assert rec.owner == LifecycleOwner.RESULT_COMPLETION


# ---------------------------------------------------------------------------
# O — to_dict includes new field
# ---------------------------------------------------------------------------

class TestToDict:
    def test_O_to_dict_includes_dispatch_actions_taken(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        r.inflight_tasks_dispatch_actions_taken = 3
        d = r.to_dict()
        assert d["inflight_tasks_dispatch_actions_taken"] == 3


# ---------------------------------------------------------------------------
# P — Mixed dispositions end-to-end
# ---------------------------------------------------------------------------

class TestMixedDispositions:
    def test_P_mixed_dispositions_all_correct(self, tmp_path):
        from core.task_envelope_lifecycle_registry import (
            get_lifecycle_registry,
            reset_lifecycle_registry,
            LifecycleOwner,
        )
        reset_lifecycle_registry()
        try:
            ms_store = _make_mesh_session_store(str(tmp_path))
            bm_store = _make_body_mesh_store(str(tmp_path))
            tl_store = _make_task_lifecycle_store(str(tmp_path))
            records = [
                _record("mix-resumable", "device_dispatch"),
                _record("mix-cross-device", "cross_device"),
                _record("mix-replay", "routing"),
                _record("mix-reissue", "gateway_ingress"),
                _record("mix-terminal", "result_completion"),
            ]
            _save_snapshot(tl_store, records)

            from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator
            coord = RuntimeRestartRecoveryCoordinator(
                mesh_session_store=ms_store,
                body_mesh_store=bm_store,
                body_mesh_registry=FakeBodyMeshRegistry(),
                task_lifecycle_store=tl_store,
            )
            report = coord.run_recovery()

            # Counts
            assert report.inflight_tasks_recovered == 5
            assert report.inflight_tasks_resumable == 2   # device_dispatch + cross_device
            assert report.inflight_tasks_replay_only == 1
            assert report.inflight_tasks_reissuable == 1
            assert report.inflight_tasks_terminal == 1
            assert report.inflight_tasks_dispatch_actions_taken == 4  # all non-terminal

            registry = get_lifecycle_registry()

            # Ownership checks
            assert registry.get_record("mix-resumable").owner == LifecycleOwner.DEVICE_DISPATCH
            assert registry.get_record("mix-cross-device").owner == LifecycleOwner.DEVICE_DISPATCH
            assert registry.get_record("mix-replay").owner == LifecycleOwner.ROUTING
            assert registry.get_record("mix-reissue").owner == LifecycleOwner.GATEWAY_INGRESS
            assert not registry.is_pending("mix-terminal")
        finally:
            reset_lifecycle_registry()
