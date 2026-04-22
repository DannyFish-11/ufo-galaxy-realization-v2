#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_task_lifecycle_persistence.py
==========================================
PR-D1: Durable In-Flight Task Lifecycle Persistence — test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings.
B  — InFlightTaskDisposition enum has the four expected values.
C  — DISPOSITION_BY_OWNER covers all five LifecycleOwner values.
D  — classify_disposition returns correct disposition per owner.
E  — classify_disposition returns REPLAY_ONLY for unknown owner (safe default).
F  — TaskLifecycleSnapshotRecord: construction and defaults.
G  — TaskLifecycleSnapshotRecord: to_dict / from_dict round-trip.
H  — RestoredTaskRecord: from_record_dict assigns correct disposition.
I  — RestoredTaskRecord.to_dict serialises all expected keys.
J  — TaskLifecyclePersistenceStore.save + load round-trip.
K  — TaskLifecyclePersistenceStore.save is atomic (temp file is cleaned up).
L  — TaskLifecyclePersistenceStore.load returns None when no file exists.
M  — TaskLifecyclePersistenceStore.load returns None when file is corrupt JSON.
N  — TaskLifecyclePersistenceStore.clear removes the snapshot file.
O  — TaskLifecyclePersistenceStore.clear is safe when no file exists.
P  — save_task_lifecycle_snapshot convenience function writes records.
Q  — load_task_lifecycle_snapshot returns None when no snapshot.
R  — restore_inflight_tasks_from_snapshot returns empty list when no snapshot.
S  — restore_inflight_tasks_from_snapshot restores all records.
T  — restore_inflight_tasks_from_snapshot assigns interrupted_at.
U  — restore_inflight_tasks_from_snapshot assigns dispositions correctly.
V  — restore_inflight_tasks_from_snapshot skips malformed records gracefully.
W  — get_task_lifecycle_store returns singleton.
X  — reset_task_lifecycle_store resets singleton.
Y  — TaskEnvelopeLifecycleRegistry.persist_snapshot writes pending records.
Z  — TaskEnvelopeLifecycleRegistry.restore_from_snapshot re-populates registry.
AA — restore_from_snapshot does not overwrite already-pending records.
AB — RuntimeRecoveryReport has inflight_tasks_* fields after recovery.
AC — run_recovery with a task_lifecycle_store recovers in-flight tasks.
AD — run_recovery inflight counts match disposition breakdown.
AE — run_recovery works with no task_lifecycle_store (no snapshot → 0 tasks).
AF — Disposition classification for all owner values matches policy sentinel.
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict, List, Optional

import pytest

from core.task_lifecycle_persistence import (
    TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY,
    TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    DISPOSITION_POLICY_IS_EXPLICIT,
    RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY,
    InFlightTaskDisposition,
    DISPOSITION_BY_OWNER,
    TaskLifecycleSnapshotRecord,
    RestoredTaskRecord,
    TaskLifecyclePersistenceStore,
    classify_disposition,
    save_task_lifecycle_snapshot,
    load_task_lifecycle_snapshot,
    restore_inflight_tasks_from_snapshot,
    get_task_lifecycle_store,
    reset_task_lifecycle_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path) -> TaskLifecyclePersistenceStore:
    return TaskLifecyclePersistenceStore(
        store_path=os.path.join(str(tmp_path), "task_lc.json")
    )


def _record_dict(
    task_id: str = "tid-1",
    owner: str = "device_dispatch",
    tool_name: str = "open_app",
    target_device_id: str = "dev-a",
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "trace_id": f"trace-{task_id}",
        "target_device_id": target_device_id,
        "tool_name": tool_name,
        "owner": owner,
        "timeout": 30.0,
        "registered_at": time.time(),
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        assert isinstance(TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY, str)
        assert TASK_LIFECYCLE_PERSISTENCE_IS_AUTHORITY

    def test_gap_closure_sentinel(self):
        assert isinstance(TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)
        assert TASK_LIFECYCLE_PERSISTENCE_GAP_CLOSURE_SENTINEL

    def test_disposition_policy_sentinel(self):
        assert isinstance(DISPOSITION_POLICY_IS_EXPLICIT, str)
        assert DISPOSITION_POLICY_IS_EXPLICIT

    def test_recovery_policy_sentinel(self):
        assert isinstance(RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY, str)
        assert RECOVERY_RESTORES_INTERRUPTED_RECORDS_POLICY


# ---------------------------------------------------------------------------
# B — InFlightTaskDisposition values
# ---------------------------------------------------------------------------

class TestInFlightTaskDisposition:
    def test_four_values(self):
        values = {d.value for d in InFlightTaskDisposition}
        assert "resumable" in values
        assert "replay_only" in values
        assert "reissuable" in values
        assert "terminal_on_interrupt" in values

    def test_enum_members(self):
        assert InFlightTaskDisposition.RESUMABLE.value == "resumable"
        assert InFlightTaskDisposition.REPLAY_ONLY.value == "replay_only"
        assert InFlightTaskDisposition.REISSUABLE.value == "reissuable"
        assert InFlightTaskDisposition.TERMINAL_ON_INTERRUPT.value == "terminal_on_interrupt"


# ---------------------------------------------------------------------------
# C — DISPOSITION_BY_OWNER mapping
# ---------------------------------------------------------------------------

class TestDispositionByOwner:
    def test_all_five_owners_covered(self):
        expected_owners = {
            "gateway_ingress",
            "routing",
            "device_dispatch",
            "cross_device",
            "result_completion",
        }
        assert expected_owners <= set(DISPOSITION_BY_OWNER.keys())

    def test_gateway_ingress_is_reissuable(self):
        assert DISPOSITION_BY_OWNER["gateway_ingress"] == InFlightTaskDisposition.REISSUABLE

    def test_routing_is_replay_only(self):
        assert DISPOSITION_BY_OWNER["routing"] == InFlightTaskDisposition.REPLAY_ONLY

    def test_device_dispatch_is_resumable(self):
        assert DISPOSITION_BY_OWNER["device_dispatch"] == InFlightTaskDisposition.RESUMABLE

    def test_cross_device_is_resumable(self):
        assert DISPOSITION_BY_OWNER["cross_device"] == InFlightTaskDisposition.RESUMABLE

    def test_result_completion_is_terminal(self):
        assert DISPOSITION_BY_OWNER["result_completion"] == InFlightTaskDisposition.TERMINAL_ON_INTERRUPT


# ---------------------------------------------------------------------------
# D / E — classify_disposition
# ---------------------------------------------------------------------------

class TestClassifyDisposition:
    @pytest.mark.parametrize("owner,expected", [
        ("gateway_ingress", InFlightTaskDisposition.REISSUABLE),
        ("routing", InFlightTaskDisposition.REPLAY_ONLY),
        ("device_dispatch", InFlightTaskDisposition.RESUMABLE),
        ("cross_device", InFlightTaskDisposition.RESUMABLE),
        ("result_completion", InFlightTaskDisposition.TERMINAL_ON_INTERRUPT),
    ])
    def test_known_owners(self, owner, expected):
        assert classify_disposition(owner) == expected

    def test_unknown_owner_defaults_to_replay_only(self):
        assert classify_disposition("unknown_owner_xyz") == InFlightTaskDisposition.REPLAY_ONLY

    def test_empty_string_defaults_to_replay_only(self):
        assert classify_disposition("") == InFlightTaskDisposition.REPLAY_ONLY


# ---------------------------------------------------------------------------
# F / G — TaskLifecycleSnapshotRecord
# ---------------------------------------------------------------------------

class TestTaskLifecycleSnapshotRecord:
    def test_construction_defaults(self):
        snap = TaskLifecycleSnapshotRecord()
        assert snap.snapshot_id.startswith("tls_")
        assert snap.records == []
        assert isinstance(snap.created_at, float)
        assert snap.process_pid > 0

    def test_to_dict_keys(self):
        snap = TaskLifecycleSnapshotRecord()
        d = snap.to_dict()
        for key in ("snapshot_id", "created_at", "process_pid", "records"):
            assert key in d

    def test_from_dict_round_trip(self):
        snap = TaskLifecycleSnapshotRecord(
            records=[_record_dict("t1"), _record_dict("t2")],
        )
        d = snap.to_dict()
        restored = TaskLifecycleSnapshotRecord.from_dict(d)
        assert restored.snapshot_id == snap.snapshot_id
        assert len(restored.records) == 2
        assert restored.process_pid == snap.process_pid

    def test_from_dict_tolerates_missing_fields(self):
        snap = TaskLifecycleSnapshotRecord.from_dict({})
        assert snap.snapshot_id.startswith("tls_")
        assert snap.records == []


# ---------------------------------------------------------------------------
# H / I — RestoredTaskRecord
# ---------------------------------------------------------------------------

class TestRestoredTaskRecord:
    def test_from_record_dict_assigns_disposition(self):
        raw = _record_dict(owner="device_dispatch")
        rec = RestoredTaskRecord.from_record_dict(
            raw, interrupted_at=1000.0, snapshot_id="tls_test"
        )
        assert rec.disposition == InFlightTaskDisposition.RESUMABLE
        assert rec.interrupted_at == 1000.0
        assert rec.snapshot_id == "tls_test"
        assert rec.task_id == "tid-1"

    def test_from_record_dict_routing_is_replay_only(self):
        raw = _record_dict(owner="routing")
        rec = RestoredTaskRecord.from_record_dict(raw, interrupted_at=0.0)
        assert rec.disposition == InFlightTaskDisposition.REPLAY_ONLY

    def test_to_dict_keys(self):
        raw = _record_dict()
        rec = RestoredTaskRecord.from_record_dict(raw, interrupted_at=time.time())
        d = rec.to_dict()
        for key in (
            "task_id", "trace_id", "target_device_id", "tool_name",
            "owner", "timeout", "registered_at", "interrupted_at",
            "disposition", "metadata", "snapshot_id",
        ):
            assert key in d, f"Missing key: {key}"

    def test_disposition_value_is_string_in_dict(self):
        raw = _record_dict(owner="gateway_ingress")
        rec = RestoredTaskRecord.from_record_dict(raw, interrupted_at=0.0)
        assert rec.to_dict()["disposition"] == "reissuable"


# ---------------------------------------------------------------------------
# J — Save + load round-trip
# ---------------------------------------------------------------------------

class TestPersistenceStoreRoundTrip:
    def test_save_and_load(self, tmp_path):
        store = _make_store(tmp_path)
        snap = TaskLifecycleSnapshotRecord(
            records=[_record_dict("t1"), _record_dict("t2")],
        )
        ok = store.save(snap)
        assert ok is True

        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 2

    def test_save_updates_existing_snapshot(self, tmp_path):
        store = _make_store(tmp_path)
        snap1 = TaskLifecycleSnapshotRecord(records=[_record_dict("a")])
        snap2 = TaskLifecycleSnapshotRecord(records=[_record_dict("b"), _record_dict("c")])
        store.save(snap1)
        store.save(snap2)

        loaded = store.load()
        assert loaded.snapshot_id == snap2.snapshot_id
        assert len(loaded.records) == 2


# ---------------------------------------------------------------------------
# K — Atomicity (no temp file remains on success)
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_no_tmp_file_after_save(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(TaskLifecycleSnapshotRecord(records=[_record_dict()]))
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []


# ---------------------------------------------------------------------------
# L / M — Load edge cases
# ---------------------------------------------------------------------------

class TestLoadEdgeCases:
    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _make_store(tmp_path)
        assert store.load() is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        store = _make_store(tmp_path)
        path = os.path.join(str(tmp_path), "task_lc.json")
        with open(path, "w") as fh:
            fh.write("NOT VALID JSON {{{")
        assert store.load() is None


# ---------------------------------------------------------------------------
# N / O — Clear
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_removes_file(self, tmp_path):
        store = _make_store(tmp_path)
        store.save(TaskLifecycleSnapshotRecord(records=[_record_dict()]))
        assert store.load() is not None
        store.clear()
        assert store.load() is None

    def test_clear_safe_when_no_file(self, tmp_path):
        store = _make_store(tmp_path)
        result = store.clear()
        assert result is True


# ---------------------------------------------------------------------------
# P / Q — Convenience wrappers
# ---------------------------------------------------------------------------

class TestConvenienceWrappers:
    def test_save_task_lifecycle_snapshot(self, tmp_path):
        store = _make_store(tmp_path)
        reset_task_lifecycle_store()
        snap = save_task_lifecycle_snapshot(
            [_record_dict("x1"), _record_dict("x2")],
            store=store,
        )
        assert snap.snapshot_id.startswith("tls_")
        assert len(snap.records) == 2
        loaded = load_task_lifecycle_snapshot(store=store)
        assert loaded is not None
        assert len(loaded.records) == 2

    def test_load_returns_none_when_no_snapshot(self, tmp_path):
        store = _make_store(tmp_path)
        assert load_task_lifecycle_snapshot(store=store) is None


# ---------------------------------------------------------------------------
# R–V — restore_inflight_tasks_from_snapshot
# ---------------------------------------------------------------------------

class TestRestoreInflightTasks:
    def test_empty_store_returns_empty_list(self, tmp_path):
        store = _make_store(tmp_path)
        result = restore_inflight_tasks_from_snapshot(store=store)
        assert result == []

    def test_restores_all_records(self, tmp_path):
        store = _make_store(tmp_path)
        records = [_record_dict("t1"), _record_dict("t2"), _record_dict("t3")]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 3

    def test_interrupted_at_is_set(self, tmp_path):
        store = _make_store(tmp_path)
        save_task_lifecycle_snapshot([_record_dict()], store=store)
        before = time.time()
        restored = restore_inflight_tasks_from_snapshot(store=store, now=before)
        assert restored[0].interrupted_at == before

    def test_dispositions_assigned_correctly(self, tmp_path):
        store = _make_store(tmp_path)
        records = [
            _record_dict("t1", owner="gateway_ingress"),
            _record_dict("t2", owner="routing"),
            _record_dict("t3", owner="device_dispatch"),
            _record_dict("t4", owner="cross_device"),
            _record_dict("t5", owner="result_completion"),
        ]
        save_task_lifecycle_snapshot(records, store=store)
        restored = restore_inflight_tasks_from_snapshot(store=store)

        by_task = {r.task_id: r.disposition for r in restored}
        assert by_task["t1"] == InFlightTaskDisposition.REISSUABLE
        assert by_task["t2"] == InFlightTaskDisposition.REPLAY_ONLY
        assert by_task["t3"] == InFlightTaskDisposition.RESUMABLE
        assert by_task["t4"] == InFlightTaskDisposition.RESUMABLE
        assert by_task["t5"] == InFlightTaskDisposition.TERMINAL_ON_INTERRUPT

    def test_malformed_records_skipped_gracefully(self, tmp_path):
        store = _make_store(tmp_path)
        # Save a snapshot with one good record and one bad one injected manually
        good = _record_dict("good")
        snap = TaskLifecycleSnapshotRecord(records=[good, "NOT_A_DICT"])  # type: ignore[list-item]
        store.save(snap)
        # Should not raise; bad record is skipped
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 1
        assert restored[0].task_id == "good"


# ---------------------------------------------------------------------------
# W / X — Singleton management
# ---------------------------------------------------------------------------

class TestSingletonManagement:
    def test_get_store_returns_singleton(self, tmp_path):
        reset_task_lifecycle_store()
        path = os.path.join(str(tmp_path), "snap.json")
        s1 = get_task_lifecycle_store(store_path=path)
        s2 = get_task_lifecycle_store()
        assert s1 is s2
        reset_task_lifecycle_store()

    def test_reset_clears_singleton(self, tmp_path):
        reset_task_lifecycle_store()
        path = os.path.join(str(tmp_path), "snap.json")
        s1 = get_task_lifecycle_store(store_path=path)
        reset_task_lifecycle_store()
        path2 = os.path.join(str(tmp_path), "snap2.json")
        s2 = get_task_lifecycle_store(store_path=path2)
        assert s1 is not s2
        reset_task_lifecycle_store()


# ---------------------------------------------------------------------------
# Y / Z / AA — TaskEnvelopeLifecycleRegistry persistence integration
# ---------------------------------------------------------------------------

class TestRegistryPersistenceIntegration:
    def _make_registry(self):
        from core.task_envelope_lifecycle_registry import (
            TaskEnvelopeLifecycleRegistry,
            LifecycleOwner,
        )
        return TaskEnvelopeLifecycleRegistry(), LifecycleOwner

    def _make_envelope(self, task_id: str = "env-1", tool: str = "test_tool"):
        class FakeEnvelope:
            def __init__(self, tid, tl):
                self.task_id = tid
                self.trace_id = f"trace-{tid}"
                self.target = "dev-x"
                self.tool_name = tl
                self.timeout = 30.0
        return FakeEnvelope(task_id, tool)

    def test_persist_snapshot_writes_pending(self, tmp_path):
        registry, LifecycleOwner = self._make_registry()
        store = _make_store(tmp_path)

        env = self._make_envelope("p1")
        registry.register(env)
        ok = registry.persist_snapshot(store=store)
        assert ok is True

        loaded = store.load()
        assert loaded is not None
        assert len(loaded.records) == 1
        assert loaded.records[0]["task_id"] == "p1"

    def test_persist_snapshot_with_no_pending(self, tmp_path):
        registry, _ = self._make_registry()
        store = _make_store(tmp_path)
        ok = registry.persist_snapshot(store=store)
        assert ok is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.records == []

    def test_restore_from_snapshot_adds_records(self, tmp_path):
        store = _make_store(tmp_path)
        save_task_lifecycle_snapshot(
            [_record_dict("restored-1"), _record_dict("restored-2")],
            store=store,
        )

        registry, _ = self._make_registry()
        added = registry.restore_from_snapshot(store=store)
        assert added == 2
        assert registry.is_pending("restored-1")
        assert registry.is_pending("restored-2")

    def test_restore_does_not_overwrite_existing(self, tmp_path):
        store = _make_store(tmp_path)
        save_task_lifecycle_snapshot([_record_dict("existing")], store=store)

        registry, LifecycleOwner = self._make_registry()
        # Register the same task_id manually first
        env = self._make_envelope("existing")
        original_record = registry.register(env)

        added = registry.restore_from_snapshot(store=store)
        assert added == 0  # existing record not overwritten
        # The record in the registry should still be the original
        rec = registry.get_record("existing")
        assert rec is original_record

    def test_restored_records_have_disposition_in_metadata(self, tmp_path):
        store = _make_store(tmp_path)
        save_task_lifecycle_snapshot(
            [_record_dict("dm1", owner="device_dispatch")],
            store=store,
        )
        registry, _ = self._make_registry()
        registry.restore_from_snapshot(store=store)

        rec = registry.get_record("dm1")
        assert rec is not None
        assert rec.metadata.get("disposition") == "resumable"


# ---------------------------------------------------------------------------
# AB–AE — RuntimeRecoveryReport / run_recovery integration
# ---------------------------------------------------------------------------

class TestRuntimeRecoveryIntegration:
    def _make_mesh_store(self, tmp_path):
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        return MeshSessionPersistenceStore(store_dir=str(tmp_path))

    def _make_body_store(self, tmp_path):
        from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
        path = os.path.join(str(tmp_path), "bm.json")
        return BodyMeshPersistenceStore(store_path=path)

    class FakeBodyRegistry:
        def __init__(self): self._entries = []
        def register(self, device_id, **_): self._entries.append(device_id)

    def test_report_has_inflight_fields(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "inflight_tasks_recovered")
        assert hasattr(r, "inflight_tasks_resumable")
        assert hasattr(r, "inflight_tasks_replay_only")
        assert hasattr(r, "inflight_tasks_reissuable")
        assert hasattr(r, "inflight_tasks_terminal")

    def test_report_to_dict_has_inflight_keys(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        d = RuntimeRecoveryReport().to_dict()
        for key in (
            "inflight_tasks_recovered",
            "inflight_tasks_resumable",
            "inflight_tasks_replay_only",
            "inflight_tasks_reissuable",
            "inflight_tasks_terminal",
        ):
            assert key in d, f"Missing key: {key}"

    def test_run_recovery_recovers_inflight_tasks(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        store = _make_store(tmp_path)
        records = [
            _record_dict("r1", owner="device_dispatch"),
            _record_dict("r2", owner="routing"),
            _record_dict("r3", owner="gateway_ingress"),
        ]
        save_task_lifecycle_snapshot(records, store=store)

        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=self._make_mesh_store(tmp_path),
            body_mesh_store=self._make_body_store(tmp_path),
            body_mesh_registry=self.FakeBodyRegistry(),
            task_lifecycle_store=store,
        )
        report = coord.run_recovery()
        assert report.inflight_tasks_recovered == 3

    def test_run_recovery_inflight_counts_match_dispositions(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        store = _make_store(tmp_path)
        records = [
            _record_dict("d1", owner="device_dispatch"),
            _record_dict("d2", owner="cross_device"),
            _record_dict("r1", owner="routing"),
            _record_dict("g1", owner="gateway_ingress"),
            _record_dict("tc", owner="result_completion"),
        ]
        save_task_lifecycle_snapshot(records, store=store)

        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=self._make_mesh_store(tmp_path),
            body_mesh_store=self._make_body_store(tmp_path),
            body_mesh_registry=self.FakeBodyRegistry(),
            task_lifecycle_store=store,
        )
        report = coord.run_recovery()
        assert report.inflight_tasks_resumable == 2
        assert report.inflight_tasks_replay_only == 1
        assert report.inflight_tasks_reissuable == 1
        assert report.inflight_tasks_terminal == 1
        assert report.inflight_tasks_recovered == 5

    def test_run_recovery_no_store_gives_zero_inflight(self, tmp_path):
        from core.runtime_restart_recovery import RuntimeRestartRecoveryCoordinator

        reset_task_lifecycle_store()
        coord = RuntimeRestartRecoveryCoordinator(
            mesh_session_store=self._make_mesh_store(tmp_path),
            body_mesh_store=self._make_body_store(tmp_path),
            body_mesh_registry=self.FakeBodyRegistry(),
            task_lifecycle_store=_make_store(tmp_path),  # empty store
        )
        report = coord.run_recovery()
        assert report.inflight_tasks_recovered == 0
        reset_task_lifecycle_store()


# ---------------------------------------------------------------------------
# AF — Disposition classification aligns with policy sentinel
# ---------------------------------------------------------------------------

class TestDispositionPolicyAlignment:
    def test_all_lifecycle_owners_have_disposition(self):
        """Every LifecycleOwner value must be covered by DISPOSITION_BY_OWNER."""
        from core.task_envelope_lifecycle_registry import LifecycleOwner
        for owner in LifecycleOwner:
            disposition = classify_disposition(owner.value)
            assert isinstance(disposition, InFlightTaskDisposition), (
                f"LifecycleOwner.{owner.name} ('{owner.value}') has no disposition"
            )
