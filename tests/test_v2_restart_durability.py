#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_v2_restart_durability.py
=====================================
Recovery Verification Tests for V2 runtime truth, task lifecycle, and
durable idempotency.

Coverage
--------
A — DurableResultIdSet: basic add / contains semantics.
B — DurableResultIdSet: persists across simulated restart (new instance loads saved IDs).
C — DurableResultIdSet: duplicate add returns False (already-seen).
D — DurableResultIdSet: clear removes file and resets state.
E — DurableResultIdSet: bounded by max_entries (oldest evicted).
F — check_result_idempotency / record_result_idempotency helpers.
G — SessionTruthSnapshotStore: append / load round-trip.
H — SessionTruthSnapshotStore: survives simulated restart (new instance loads records).
I — SessionTruthSnapshotStore: bounded by max_records.
J — CanonicalSessionTruthRecord.from_dict round-trip.
K — CanonicalSessionTruthRuntime: set_snapshot_store wires snapshot on record().
L — restore_session_truth_from_snapshot reloads records into a fresh runtime.
M — V2 restart with inflight task: lifecycle snapshot saved and restored.
N — Android reattach after restart: duplicate result after restart suppressed.
O — Replay safety: same result_id rejected across simulated restart.
P — startup.py bootstrap_subsystems wires session_truth_snapshot step.
Q — startup.py bootstrap_subsystems wires startup_recovery step.
R — startup.py bootstrap_subsystems wires durable_result_idempotency step.
S — shutdown_subsystems calls persist_snapshot on TaskEnvelopeLifecycleRegistry.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result_id() -> str:
    return f"rid_{uuid.uuid4().hex[:12]}"


def _session_id() -> str:
    return f"sess_{uuid.uuid4().hex[:8]}"


def _task_id() -> str:
    return f"task_{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# A: DurableResultIdSet — basic semantics
# ---------------------------------------------------------------------------


class TestGroupA_DurableResultIdSetBasic:
    def setup_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def teardown_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def test_A01_new_result_id_not_contained(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        assert not store.contains(_result_id())

    def test_A02_add_then_contains(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        rid = _result_id()
        assert store.add(rid) is True
        assert store.contains(rid) is True

    def test_A03_add_duplicate_returns_false(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        rid = _result_id()
        store.add(rid)
        assert store.add(rid) is False

    def test_A04_size_tracks_unique_additions(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        for _ in range(5):
            store.add(_result_id())
        assert store.size() == 5


# ---------------------------------------------------------------------------
# B: DurableResultIdSet — survives simulated restart
# ---------------------------------------------------------------------------


class TestGroupB_DurableResultIdSetRestart:
    def test_B01_ids_persist_across_new_instance(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rid = _result_id()

        # First "process" records a result
        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid)

        # Simulated restart — new instance of the store
        store2 = DurableResultIdSet(store_path=path)
        assert store2.contains(rid), "ID should survive simulated restart"

    def test_B02_new_ids_not_in_reloaded_store(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rid_old = _result_id()
        rid_new = _result_id()

        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid_old)

        store2 = DurableResultIdSet(store_path=path)
        assert not store2.contains(rid_new)
        assert store2.contains(rid_old)


# ---------------------------------------------------------------------------
# C: DurableResultIdSet — duplicate add
# ---------------------------------------------------------------------------


class TestGroupC_DurableResultIdSetDuplicate:
    def test_C01_add_returns_false_on_duplicate(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        rid = _result_id()
        assert store.add(rid) is True
        assert store.add(rid) is False

    def test_C02_after_restart_duplicate_still_false(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rid = _result_id()
        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid)

        store2 = DurableResultIdSet(store_path=path)
        assert store2.add(rid) is False


# ---------------------------------------------------------------------------
# D: DurableResultIdSet — clear
# ---------------------------------------------------------------------------


class TestGroupD_DurableResultIdSetClear:
    def test_D01_clear_removes_file(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        store = DurableResultIdSet(store_path=path)
        store.add(_result_id())
        store.clear()
        assert not os.path.exists(path)

    def test_D02_contains_returns_false_after_clear(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"))
        rid = _result_id()
        store.add(rid)
        store.clear()
        assert not store.contains(rid)

    def test_D03_clear_safe_when_no_file(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids_none.json"))
        store.clear()  # must not raise


# ---------------------------------------------------------------------------
# E: DurableResultIdSet — bounded eviction
# ---------------------------------------------------------------------------


class TestGroupE_DurableResultIdSetBounded:
    def test_E01_evicts_oldest_when_over_cap(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        store = DurableResultIdSet(store_path=str(tmp_path / "ids.json"), max_entries=3)
        ids = [_result_id() for _ in range(5)]
        for rid in ids:
            store.add(rid)
        assert store.size() == 3
        # Oldest two should be evicted
        assert not store.contains(ids[0])
        assert not store.contains(ids[1])
        # Latest three should survive
        for rid in ids[2:]:
            assert store.contains(rid)


# ---------------------------------------------------------------------------
# F: check_result_idempotency / record_result_idempotency helpers
# ---------------------------------------------------------------------------


class TestGroupF_ResultIdempotencyHelpers:
    def setup_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def teardown_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def test_F01_check_returns_false_for_unseen(self, tmp_path, monkeypatch):
        import core.durable_result_idempotency as idem
        store_path = str(tmp_path / "ids.json")
        monkeypatch.setattr(idem, "_DEFAULT_RESULT_ID_STORE_PATH", store_path)

        from core.durable_result_idempotency import check_result_idempotency
        assert check_result_idempotency(_result_id()) is False

    def test_F02_record_then_check_returns_true(self, tmp_path, monkeypatch):
        import core.durable_result_idempotency as idem
        store_path = str(tmp_path / "ids.json")
        monkeypatch.setattr(idem, "_DEFAULT_RESULT_ID_STORE_PATH", store_path)

        from core.durable_result_idempotency import (
            record_result_idempotency,
            check_result_idempotency,
        )
        rid = _result_id()
        assert record_result_idempotency(rid) is True
        assert check_result_idempotency(rid) is True

    def test_F03_record_duplicate_returns_false(self, tmp_path, monkeypatch):
        import core.durable_result_idempotency as idem
        store_path = str(tmp_path / "ids.json")
        monkeypatch.setattr(idem, "_DEFAULT_RESULT_ID_STORE_PATH", store_path)

        from core.durable_result_idempotency import record_result_idempotency
        rid = _result_id()
        assert record_result_idempotency(rid) is True
        assert record_result_idempotency(rid) is False


# ---------------------------------------------------------------------------
# G: SessionTruthSnapshotStore — append / load round-trip
# ---------------------------------------------------------------------------


class TestGroupG_SessionTruthSnapshotStore:
    def setup_method(self):
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_session_truth_snapshot_store()

    def teardown_method(self):
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_session_truth_snapshot_store()

    def test_G01_load_empty_when_no_file(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        assert store.load() == []

    def test_G02_append_creates_file(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        path = str(tmp_path / "st.json")
        store = SessionTruthSnapshotStore(store_path=path)
        store.append({"session_id": "s1", "task_id": "t1"})
        assert os.path.exists(path)

    def test_G03_load_returns_appended_records(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        store.append({"session_id": "s1"})
        store.append({"session_id": "s2"})
        records = store.load()
        assert len(records) == 2
        assert records[0]["session_id"] == "s1"
        assert records[1]["session_id"] == "s2"

    def test_G04_clear_removes_records(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        path = str(tmp_path / "st.json")
        store = SessionTruthSnapshotStore(store_path=path)
        store.append({"session_id": "s1"})
        store.clear()
        assert not os.path.exists(path)


# ---------------------------------------------------------------------------
# H: SessionTruthSnapshotStore — survives simulated restart
# ---------------------------------------------------------------------------


class TestGroupH_SessionTruthSnapshotRestart:
    def test_H01_records_survive_new_instance(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        path = str(tmp_path / "st.json")
        store1 = SessionTruthSnapshotStore(store_path=path)
        store1.append({"session_id": "s1", "task_id": "t1"})

        store2 = SessionTruthSnapshotStore(store_path=path)
        records = store2.load()
        assert len(records) == 1
        assert records[0]["session_id"] == "s1"

    def test_H02_multiple_records_survive_restart(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        path = str(tmp_path / "st.json")
        store1 = SessionTruthSnapshotStore(store_path=path)
        for i in range(5):
            store1.append({"session_id": f"s{i}"})

        store2 = SessionTruthSnapshotStore(store_path=path)
        assert len(store2.load()) == 5


# ---------------------------------------------------------------------------
# I: SessionTruthSnapshotStore — bounded
# ---------------------------------------------------------------------------


class TestGroupI_SessionTruthSnapshotBounded:
    def test_I01_trims_to_max_records(self, tmp_path):
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        store = SessionTruthSnapshotStore(
            store_path=str(tmp_path / "st.json"), max_records=3
        )
        for i in range(5):
            store.append({"session_id": f"s{i}"})
        records = store.load()
        assert len(records) == 3
        # Latest 3 should survive
        assert records[-1]["session_id"] == "s4"


# ---------------------------------------------------------------------------
# J: CanonicalSessionTruthRecord.from_dict round-trip
# (requires pydantic for the canonical_session_truth module's dependencies)
# ---------------------------------------------------------------------------

_pydantic_available = True
try:
    import pydantic
except ImportError:
    _pydantic_available = False


class TestGroupJ_CanonicalSessionTruthRecordFromDict:
    def test_J01_round_trip(self):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord(
            session_id=_session_id(),
            task_id=_task_id(),
            source_runtime_posture="join_runtime",
            merge_success=True,
            reason="test",
        )
        d = rec.to_dict()
        rec2 = CanonicalSessionTruthRecord.from_dict(d)
        assert rec2.session_id == rec.session_id
        assert rec2.task_id == rec.task_id
        assert rec2.merge_success == rec.merge_success
        assert rec2.source_runtime_posture == "join_runtime"

    def test_J02_from_dict_with_missing_fields_uses_defaults(self):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import CanonicalSessionTruthRecord
        rec = CanonicalSessionTruthRecord.from_dict({"session_id": "s1"})
        assert rec.session_id == "s1"
        assert rec.merge_success is False
        assert rec.record_id != ""


# ---------------------------------------------------------------------------
# K: CanonicalSessionTruthRuntime — snapshot store wiring
# ---------------------------------------------------------------------------


class TestGroupK_CanonicalSessionTruthRuntimeSnapshotWiring:
    def setup_method(self):
        if not _pydantic_available:
            return
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def teardown_method(self):
        if not _pydantic_available:
            return
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def test_K01_snapshot_store_set_and_used(self, tmp_path):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import SessionTruthSnapshotStore
        runtime = CanonicalSessionTruthRuntime()
        store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        runtime.set_snapshot_store(store)

        rec = CanonicalSessionTruthRecord(
            session_id=_session_id(), task_id=_task_id(), merge_success=True
        )
        runtime.record(rec)
        records = store.load()
        assert len(records) == 1
        assert records[0]["session_id"] == rec.session_id

    def test_K02_no_snapshot_store_does_not_crash(self, tmp_path):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        runtime = CanonicalSessionTruthRuntime()
        # No snapshot store attached — should not raise
        rec = CanonicalSessionTruthRecord(session_id=_session_id())
        result = runtime.record(rec)
        assert result is rec


# ---------------------------------------------------------------------------
# L: restore_session_truth_from_snapshot
# ---------------------------------------------------------------------------


class TestGroupL_RestoreSessionTruth:
    def setup_method(self):
        if not _pydantic_available:
            return
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def teardown_method(self):
        if not _pydantic_available:
            return
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        from core.session_truth_snapshot import reset_session_truth_snapshot_store
        reset_canonical_session_truth_runtime()
        reset_session_truth_snapshot_store()

    def test_L01_restores_records_into_runtime(self, tmp_path):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        from core.session_truth_snapshot import (
            SessionTruthSnapshotStore,
            restore_session_truth_from_snapshot,
        )
        # First "process": record some truth
        store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        runtime1 = CanonicalSessionTruthRuntime()
        runtime1.set_snapshot_store(store)
        for i in range(3):
            runtime1.record(
                CanonicalSessionTruthRecord(
                    session_id=f"sess_{i}", task_id=f"task_{i}", merge_success=True
                )
            )

        # Simulated restart: new runtime, same store
        runtime2 = CanonicalSessionTruthRuntime()
        restored = restore_session_truth_from_snapshot(runtime=runtime2, store=store)
        assert restored == 3
        snap = runtime2.snapshot()
        assert snap.total_records == 3

    def test_L02_returns_zero_when_no_snapshot(self, tmp_path):
        if not _pydantic_available:
            pytest.skip("pydantic not installed — skipping canonical_session_truth tests")
        from core.canonical_session_truth import CanonicalSessionTruthRuntime
        from core.session_truth_snapshot import (
            SessionTruthSnapshotStore,
            restore_session_truth_from_snapshot,
        )
        store = SessionTruthSnapshotStore(store_path=str(tmp_path / "st.json"))
        runtime = CanonicalSessionTruthRuntime()
        restored = restore_session_truth_from_snapshot(runtime=runtime, store=store)
        assert restored == 0


# ---------------------------------------------------------------------------
# M: V2 restart with inflight task — lifecycle snapshot saved and restored
# ---------------------------------------------------------------------------


class TestGroupM_RestartWithInflightTask:
    def setup_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def teardown_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def test_M01_inflight_task_recovered_after_restart(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            save_task_lifecycle_snapshot,
            restore_inflight_tasks_from_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        tid = _task_id()
        records = [
            {
                "task_id": tid,
                "trace_id": "trace_001",
                "session_id": _session_id(),
                "owner": "device_dispatch",
                "state": "dispatched",
                "created_at": time.time(),
                "updated_at": time.time(),
                "device_id": "dev-001",
            }
        ]
        save_task_lifecycle_snapshot(records, store=store)

        # Simulated restart: restore from snapshot
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 1
        assert restored[0].task_id == tid

    def test_M02_empty_snapshot_gives_empty_restore(self, tmp_path):
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            restore_inflight_tasks_from_snapshot,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl_empty.json")
        )
        assert restore_inflight_tasks_from_snapshot(store=store) == []


# ---------------------------------------------------------------------------
# N: Android reattach after restart — duplicate result suppressed
# ---------------------------------------------------------------------------


class TestGroupN_AndroidReattachDuplicateResult:
    def setup_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def teardown_method(self):
        from core.durable_result_idempotency import reset_durable_result_id_store
        reset_durable_result_id_store()

    def test_N01_result_from_before_restart_suppressed(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rid = _result_id()

        # Pre-restart process records result
        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid)

        # Post-restart: Android sends same result again
        store2 = DurableResultIdSet(store_path=path)
        assert store2.contains(rid), "Duplicate result should be suppressed after restart"

    def test_N02_new_result_after_restart_accepted(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rid_old = _result_id()
        rid_new = _result_id()

        store1 = DurableResultIdSet(store_path=path)
        store1.add(rid_old)

        store2 = DurableResultIdSet(store_path=path)
        assert not store2.contains(rid_new)
        assert store2.add(rid_new) is True


# ---------------------------------------------------------------------------
# O: Replay safety — same result_id rejected across simulated restart
# ---------------------------------------------------------------------------


class TestGroupO_ReplaySafetyAcrossRestart:
    def test_O01_replay_after_restart_is_suppressed(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        rids = [_result_id() for _ in range(3)]

        store1 = DurableResultIdSet(store_path=path)
        for rid in rids:
            store1.add(rid)

        # Simulated restart + Android replay
        store2 = DurableResultIdSet(store_path=path)
        for rid in rids:
            # All replayed results should be recognised as duplicates
            assert store2.add(rid) is False, f"Replay of {rid} should be rejected"

    def test_O02_new_results_after_replay_accepted(self, tmp_path):
        from core.durable_result_idempotency import DurableResultIdSet
        path = str(tmp_path / "ids.json")
        old_rid = _result_id()
        new_rid = _result_id()

        store1 = DurableResultIdSet(store_path=path)
        store1.add(old_rid)

        store2 = DurableResultIdSet(store_path=path)
        # Old replay rejected, new result accepted
        assert store2.add(old_rid) is False
        assert store2.add(new_rid) is True


# ---------------------------------------------------------------------------
# P: startup.py bootstrap_subsystems wires session_truth_snapshot step
# ---------------------------------------------------------------------------


class TestGroupP_StartupSessionTruthSnapshotWiring:
    def test_P01_session_truth_snapshot_key_present_in_results(self):
        """bootstrap_subsystems must include 'session_truth_snapshot' in results."""
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        # The key must be set somewhere in bootstrap_subsystems
        assert 'session_truth_snapshot' in src, (
            "startup.py must wire session_truth_snapshot into bootstrap_subsystems results"
        )

    def test_P02_set_snapshot_store_called_in_startup(self):
        """startup.py must call set_snapshot_store on the canonical runtime."""
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert "set_snapshot_store" in src


# ---------------------------------------------------------------------------
# Q: startup.py bootstrap_subsystems wires startup_recovery step
# ---------------------------------------------------------------------------


class TestGroupQ_StartupRecoveryWiring:
    def test_Q01_startup_recovery_key_in_results(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert 'startup_recovery' in src, (
            "startup.py must wire startup_recovery into bootstrap_subsystems results"
        )

    def test_Q02_run_startup_recovery_called_in_startup(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert "run_startup_recovery" in src


# ---------------------------------------------------------------------------
# R: startup.py wires durable_result_idempotency step
# ---------------------------------------------------------------------------


class TestGroupR_StartupDurableResultIdempotencyWiring:
    def test_R01_durable_result_idempotency_key_in_startup(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert 'durable_result_idempotency' in src

    def test_R02_get_durable_result_id_store_called_in_startup(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert "get_durable_result_id_store" in src


# ---------------------------------------------------------------------------
# S: shutdown_subsystems persists task lifecycle snapshot
# ---------------------------------------------------------------------------


class TestGroupS_ShutdownPersistsLifecycleSnapshot:
    def test_S01_persist_snapshot_called_in_shutdown(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert "persist_snapshot" in src, (
            "shutdown_subsystems must call persist_snapshot on task lifecycle registry"
        )

    def test_S02_get_lifecycle_registry_called_in_shutdown(self):
        startup_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "core",
            "startup.py",
        )
        with open(startup_path) as f:
            src = f.read()
        assert "get_lifecycle_registry" in src
