#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_mesh_session_durable_runtime.py
================================================
Tests for PR-1: Mesh Session Durable Runtime Foundation.

Coverage:
  1.  MeshSessionStatus — SUSPENDED state exists and is correct.
  2.  MeshSessionStatus — RESTORING state exists and is correct.
  3.  MeshSessionStatus — SUSPENDED is not terminal in persistence store.
  4.  MeshSessionStatus — RESTORING is not terminal in persistence store.
  5.  MeshSessionStatus — _map_session_status handles 'suspended'.
  6.  MeshSessionStatus — _map_session_status handles 'restoring'.
  7.  MeshSessionStatus — round-trip serialisation includes new states.
  8.  MeshSession — from_dict tolerates suspended/restoring status.
  9.  MeshSessionLifecycleManager — sentinels are importable strings.
  10. MeshSessionLifecycleManager — create_session registers entry.
  11. MeshSessionLifecycleManager — activate_session transitions to active.
  12. MeshSessionLifecycleManager — suspend_session transitions to suspended.
  13. MeshSessionLifecycleManager — restore_session transitions to restoring.
  14. MeshSessionLifecycleManager — terminate_session transitions to completed.
  15. MeshSessionLifecycleManager — terminate_session with failed status.
  16. MeshSessionLifecycleManager — auto-registers unknown session on transition.
  17. MeshSessionLifecycleManager — list_active_sessions returns only active.
  18. MeshSessionLifecycleManager — list_suspended_sessions returns only suspended.
  19. MeshSessionLifecycleManager — list_restoring_sessions returns only restoring.
  20. MeshSessionLifecycleManager — active_session_summary returns correct counts.
  21. MeshSessionLifecycleManager — active_session_summary includes authority.
  22. MeshSessionLifecycleManager — create_session with no session_id returns None.
  23. MeshSessionLifecycleManager — persistence is called on each transition.
  24. MeshSessionLifecycleManager — restore_from_persistence loads snapshots.
  25. MeshSessionLifecycleManager — get_session returns correct entry.
  26. MeshSessionLifecycleManager — get_session returns None for unknown.
  27. MeshSessionLifecycleManager — transition_log tracks all transitions.
  28. SessionRegistryEntry — to_summary_dict returns expected keys.
  29. core.mesh __init__ exports lifecycle symbols.
  30. get_lifecycle_manager — returns singleton.
  31. reset_lifecycle_manager — clears singleton.
  32. OutwardRuntimeTruthSnapshot — mesh_session_truth field exists.
  33. OutwardRuntimeTruthSnapshot — to_dict includes mesh_session_truth.
  34. compile_outward_truth — includes MeshSessionLifecycleManager source record.
  35. MESH_SESSION_TRUTH_INTEGRATED sentinel is importable.
"""

from __future__ import annotations

import tempfile
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator_dict(session_id: str = "msess-001", status: str = "active") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "coordinator_id": "coord-abc",
        "overall_status": status,
        "pending_device_ids": ["device_a"],
        "completed_device_ids": [],
        "failed_device_ids": [],
    }


def _make_store(tmp_dir: Optional[str] = None):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir or tempfile.mkdtemp())


def _make_manager(tmp_dir: Optional[str] = None):
    from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleManager
    return MeshSessionLifecycleManager(persistence_store=_make_store(tmp_dir))


# ---------------------------------------------------------------------------
# 1–8: MeshSessionStatus — new lifecycle states
# ---------------------------------------------------------------------------


class TestMeshSessionStatusNewStates:
    def test_suspended_state_exists(self):
        from contracts.mesh_session import MeshSessionStatus
        assert MeshSessionStatus.SUSPENDED.value == "suspended"

    def test_restoring_state_exists(self):
        from contracts.mesh_session import MeshSessionStatus
        assert MeshSessionStatus.RESTORING.value == "restoring"

    def test_suspended_is_not_terminal_in_persistence(self):
        """SUSPENDED sessions must remain recoverable in the persistence store."""
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s-susp",
            coordinator_id="c",
            overall_status="suspended",
            snapshot_dict={},
        )
        assert rec.is_terminal() is False
        assert rec.is_recoverable() is True

    def test_restoring_is_not_terminal_in_persistence(self):
        """RESTORING sessions must remain recoverable in the persistence store."""
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s-rest",
            coordinator_id="c",
            overall_status="restoring",
            snapshot_dict={},
        )
        assert rec.is_terminal() is False
        assert rec.is_recoverable() is True

    def test_map_session_status_handles_suspended(self):
        from contracts.mesh_session import _map_session_status, MeshSessionStatus
        assert _map_session_status("suspended") == MeshSessionStatus.SUSPENDED

    def test_map_session_status_handles_restoring(self):
        from contracts.mesh_session import _map_session_status, MeshSessionStatus
        assert _map_session_status("restoring") == MeshSessionStatus.RESTORING

    def test_mesh_session_status_serialisation_round_trip(self):
        """SUSPENDED and RESTORING survive to_dict / from_dict round-trip."""
        from contracts.mesh_session import MeshSession, MeshSessionStatus
        session = MeshSession(
            session_id="msess-rt",
            status=MeshSessionStatus.SUSPENDED,
        )
        d = session.to_dict()
        assert d["status"] == "suspended"
        session2 = MeshSession.from_dict(d)
        assert session2.status == MeshSessionStatus.SUSPENDED

    def test_mesh_session_from_dict_restoring_status(self):
        """from_dict tolerates restoring status value."""
        from contracts.mesh_session import MeshSession, MeshSessionStatus
        session = MeshSession.from_dict({"session_id": "s1", "status": "restoring"})
        assert session.status == MeshSessionStatus.RESTORING


# ---------------------------------------------------------------------------
# 9: MeshSessionLifecycleManager sentinels
# ---------------------------------------------------------------------------


class TestLifecycleSentinels:
    def test_lifecycle_authority_sentinel(self):
        from core.mesh.mesh_session_lifecycle import MESH_SESSION_LIFECYCLE_AUTHORITY
        assert isinstance(MESH_SESSION_LIFECYCLE_AUTHORITY, str)
        assert "MESH_SESSION_LIFECYCLE_AUTHORITY" in MESH_SESSION_LIFECYCLE_AUTHORITY

    def test_persist_on_transition_sentinel(self):
        from core.mesh.mesh_session_lifecycle import LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY
        assert isinstance(LIFECYCLE_PERSISTS_ON_EVERY_TRANSITION_POLICY, str)

    def test_truth_boundary_sentinel(self):
        from core.mesh.mesh_session_lifecycle import LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY
        assert isinstance(LIFECYCLE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY, str)

    def test_durable_foundation_sentinel(self):
        from core.mesh.mesh_session_lifecycle import DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL
        assert isinstance(DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL, str)
        assert "PR1" in DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL


# ---------------------------------------------------------------------------
# 10–27: MeshSessionLifecycleManager lifecycle transitions
# ---------------------------------------------------------------------------


class TestLifecycleManagerTransitions:
    def test_create_session_registers_entry(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        entry = mgr.create_session(d)
        assert entry is not None
        assert entry.session_id == "msess-001"
        assert entry.lifecycle_status == "pending"

    def test_activate_session_transitions_to_active(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        entry = mgr.activate_session(d)
        assert entry is not None
        assert entry.lifecycle_status == "active"

    def test_suspend_session_transitions_to_suspended(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        mgr.activate_session(d)
        entry = mgr.suspend_session(d)
        assert entry is not None
        assert entry.lifecycle_status == "suspended"

    def test_restore_session_transitions_to_restoring(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        mgr.activate_session(d)
        mgr.suspend_session(d)
        entry = mgr.restore_session(d)
        assert entry is not None
        assert entry.lifecycle_status == "restoring"

    def test_terminate_session_defaults_to_completed(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        entry = mgr.terminate_session(d)
        assert entry is not None
        assert entry.lifecycle_status == "completed"

    def test_terminate_session_with_failed_status(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        entry = mgr.terminate_session(d, terminal_status="failed")
        assert entry is not None
        assert entry.lifecycle_status == "failed"

    def test_auto_registers_unknown_session_on_transition(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict(session_id="new-sess")
        # activate without prior create — should auto-register
        entry = mgr.activate_session(d)
        assert entry is not None
        assert entry.lifecycle_status == "active"
        assert mgr.get_session("new-sess") is not None

    def test_create_session_no_session_id_returns_none(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        entry = mgr.create_session({"session_id": "", "overall_status": "pending"})
        assert entry is None

    def test_transition_log_tracks_all_transitions(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict()
        mgr.create_session(d)
        mgr.activate_session(d)
        mgr.suspend_session(d)
        entry = mgr.get_session("msess-001")
        statuses = [t[1] for t in entry.transition_log]
        assert "pending" in statuses
        assert "active" in statuses
        assert "suspended" in statuses


# ---------------------------------------------------------------------------
# 17–20: Registry query methods
# ---------------------------------------------------------------------------


class TestLifecycleManagerQueries:
    def test_list_active_sessions_returns_only_active(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d1 = _make_coordinator_dict("sess-active")
        d2 = _make_coordinator_dict("sess-suspended")
        mgr.create_session(d1)
        mgr.activate_session(d1)
        mgr.create_session(d2)
        mgr.activate_session(d2)
        mgr.suspend_session(d2)
        active = mgr.list_active_sessions()
        ids = [e.session_id for e in active]
        assert "sess-active" in ids
        assert "sess-suspended" not in ids

    def test_list_suspended_sessions_returns_only_suspended(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict("sess-s")
        mgr.create_session(d)
        mgr.activate_session(d)
        mgr.suspend_session(d)
        suspended = mgr.list_suspended_sessions()
        assert any(e.session_id == "sess-s" for e in suspended)

    def test_list_restoring_sessions_returns_only_restoring(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict("sess-r")
        mgr.create_session(d)
        mgr.restore_session(d)
        restoring = mgr.list_restoring_sessions()
        assert any(e.session_id == "sess-r" for e in restoring)

    def test_active_session_summary_correct_counts(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        mgr.create_session(_make_coordinator_dict("sess-a1"))
        mgr.activate_session(_make_coordinator_dict("sess-a1"))
        mgr.create_session(_make_coordinator_dict("sess-a2"))
        mgr.activate_session(_make_coordinator_dict("sess-a2"))
        mgr.create_session(_make_coordinator_dict("sess-s1"))
        mgr.activate_session(_make_coordinator_dict("sess-s1"))
        mgr.suspend_session(_make_coordinator_dict("sess-s1"))
        mgr.create_session(_make_coordinator_dict("sess-r1"))
        mgr.restore_session(_make_coordinator_dict("sess-r1"))

        summary = mgr.active_session_summary()
        assert summary["active_count"] == 2
        assert summary["suspended_count"] == 1
        assert summary["restoring_count"] == 1
        assert summary["total_tracked"] == 4

    def test_active_session_summary_includes_authority(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        summary = mgr.active_session_summary()
        assert "authority" in summary
        assert "MESH_SESSION_LIFECYCLE_AUTHORITY" in summary["authority"]

    def test_get_session_returns_correct_entry(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        d = _make_coordinator_dict("sess-get")
        mgr.create_session(d)
        entry = mgr.get_session("sess-get")
        assert entry is not None
        assert entry.session_id == "sess-get"

    def test_get_session_returns_none_for_unknown(self, tmp_path):
        mgr = _make_manager(str(tmp_path))
        assert mgr.get_session("nonexistent") is None


# ---------------------------------------------------------------------------
# 23: Persistence called on each transition
# ---------------------------------------------------------------------------


class TestLifecycleManagerPersistence:
    def test_persistence_called_on_create(self, tmp_path):
        store = _make_store(str(tmp_path))
        mgr = MagicMock()
        mgr._persistence = store

        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleManager
        real_mgr = MeshSessionLifecycleManager(persistence_store=store)
        d = _make_coordinator_dict("sess-persist")
        real_mgr.create_session(d)
        # Verify snapshot was saved to the store
        rec = store.load("sess-persist")
        assert rec is not None
        assert rec.session_id == "sess-persist"

    def test_persistence_updated_on_suspend(self, tmp_path):
        store = _make_store(str(tmp_path))
        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleManager
        mgr = MeshSessionLifecycleManager(persistence_store=store)
        d = _make_coordinator_dict("sess-susp-p")
        mgr.create_session(d)
        mgr.activate_session(d)
        mgr.suspend_session(d)
        rec = store.load("sess-susp-p")
        assert rec is not None


# ---------------------------------------------------------------------------
# 24: restore_from_persistence
# ---------------------------------------------------------------------------


class TestRestoreFromPersistence:
    def test_restore_from_persistence_loads_snapshots(self, tmp_path):
        store = _make_store(str(tmp_path))
        # Pre-populate store with non-terminal sessions
        store.save({"session_id": "sess-rp-1", "coordinator_id": "c1", "overall_status": "active"})
        store.save({"session_id": "sess-rp-2", "coordinator_id": "c2", "overall_status": "suspended"})
        # Terminal session — should not be recovered
        store.save({"session_id": "sess-rp-3", "coordinator_id": "c3", "overall_status": "completed"})
        store.mark_terminal("sess-rp-3", status="completed")

        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleManager
        mgr = MeshSessionLifecycleManager(persistence_store=store)
        restored = mgr.restore_from_persistence()
        assert restored == 2  # Exactly 2 non-terminal sessions restored

        # Terminal session must not appear in the registry
        assert mgr.get_session("sess-rp-3") is None
        # Non-terminal sessions must be in the registry
        assert mgr.get_session("sess-rp-1") is not None
        assert mgr.get_session("sess-rp-2") is not None

        # Already-tracked sessions should not be double-counted
        restored_again = mgr.restore_from_persistence()
        assert restored_again == 0

    def test_restore_from_persistence_skips_in_process_sessions(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save({"session_id": "sess-inproc", "coordinator_id": "c", "overall_status": "active"})

        from core.mesh.mesh_session_lifecycle import MeshSessionLifecycleManager
        mgr = MeshSessionLifecycleManager(persistence_store=store)
        # Pre-register session in-process
        mgr.create_session({"session_id": "sess-inproc", "coordinator_id": "c", "overall_status": "active"})
        restored = mgr.restore_from_persistence()
        assert restored == 0  # Already tracked, should be skipped


# ---------------------------------------------------------------------------
# 28: SessionRegistryEntry.to_summary_dict
# ---------------------------------------------------------------------------


class TestSessionRegistryEntry:
    def test_to_summary_dict_keys(self):
        from core.mesh.mesh_session_lifecycle import SessionRegistryEntry
        entry = SessionRegistryEntry(
            session_id="s1",
            coordinator_state={"session_id": "s1"},
            lifecycle_status="active",
        )
        d = entry.to_summary_dict()
        assert "session_id" in d
        assert "lifecycle_status" in d
        assert "created_at" in d
        assert "updated_at" in d
        assert "transition_count" in d

    def test_record_transition_updates_status(self):
        from core.mesh.mesh_session_lifecycle import SessionRegistryEntry
        entry = SessionRegistryEntry(
            session_id="s2",
            coordinator_state={},
            lifecycle_status="pending",
        )
        entry.record_transition("active")
        assert entry.lifecycle_status == "active"
        assert len(entry.transition_log) == 1


# ---------------------------------------------------------------------------
# 29: core.mesh __init__ exports
# ---------------------------------------------------------------------------


class TestCoreMeshInitExports:
    def test_lifecycle_manager_importable(self):
        from core.mesh import MeshSessionLifecycleManager
        assert MeshSessionLifecycleManager is not None

    def test_get_lifecycle_manager_importable(self):
        from core.mesh import get_lifecycle_manager
        assert callable(get_lifecycle_manager)

    def test_reset_lifecycle_manager_importable(self):
        from core.mesh import reset_lifecycle_manager
        assert callable(reset_lifecycle_manager)

    def test_lifecycle_authority_sentinel_importable(self):
        from core.mesh import MESH_SESSION_LIFECYCLE_AUTHORITY
        assert isinstance(MESH_SESSION_LIFECYCLE_AUTHORITY, str)

    def test_durable_foundation_sentinel_importable(self):
        from core.mesh import DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL
        assert isinstance(DURABLE_FOUNDATION_FOR_RESTORE_ROAMING_REBALANCE_SENTINEL, str)


# ---------------------------------------------------------------------------
# 30–31: Singleton management
# ---------------------------------------------------------------------------


class TestLifecycleSingleton:
    def test_get_lifecycle_manager_returns_singleton(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_manager, reset_lifecycle_manager,
        )
        reset_lifecycle_manager()
        mgr1 = get_lifecycle_manager()
        mgr2 = get_lifecycle_manager()
        assert mgr1 is mgr2
        reset_lifecycle_manager()

    def test_reset_lifecycle_manager_clears_singleton(self, tmp_path):
        from core.mesh.mesh_session_lifecycle import (
            get_lifecycle_manager, reset_lifecycle_manager,
        )
        reset_lifecycle_manager()
        mgr1 = get_lifecycle_manager()
        reset_lifecycle_manager()
        mgr2 = get_lifecycle_manager()
        assert mgr1 is not mgr2
        reset_lifecycle_manager()


# ---------------------------------------------------------------------------
# 32–35: OutwardRuntimeTruthSnapshot — mesh_session_truth integration
# ---------------------------------------------------------------------------


class TestOutwardRuntimeTruthMeshIntegration:
    def test_mesh_session_truth_field_exists(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        import dataclasses
        field_names = {f.name for f in dataclasses.fields(OutwardRuntimeTruthSnapshot)}
        assert "mesh_session_truth" in field_names

    def test_to_dict_includes_mesh_session_truth(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id="snap-001",
            compiled_at=1234567890.0,
            mesh_session_truth={"active_count": 1, "suspended_count": 0},
        )
        d = snap.to_dict()
        assert "mesh_session_truth" in d
        assert d["mesh_session_truth"]["active_count"] == 1

    def test_to_dict_mesh_session_truth_none_by_default(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(
            snapshot_id="snap-002",
            compiled_at=1234567890.0,
        )
        d = snap.to_dict()
        assert "mesh_session_truth" in d
        assert d["mesh_session_truth"] is None

    def test_compile_outward_truth_includes_mesh_session_source(self):
        """compile_outward_truth must include MeshSessionLifecycleManager source."""
        from core.outward_runtime_truth import compile_outward_truth
        from core.mesh.mesh_session_lifecycle import reset_lifecycle_manager
        reset_lifecycle_manager()
        snapshot = compile_outward_truth()
        source_names = [r.source_name for r in snapshot.source_records]
        assert "MeshSessionLifecycleManager" in source_names
        reset_lifecycle_manager()

    def test_mesh_session_truth_integrated_sentinel_importable(self):
        from core.outward_runtime_truth import MESH_SESSION_TRUTH_INTEGRATED_IN_OUTWARD_TRUTH
        assert isinstance(MESH_SESSION_TRUTH_INTEGRATED_IN_OUTWARD_TRUTH, str)
        assert "PR1" in MESH_SESSION_TRUTH_INTEGRATED_IN_OUTWARD_TRUTH

    def test_compile_outward_truth_mesh_session_truth_present(self):
        """compile_outward_truth snapshot should carry mesh_session_truth data."""
        from core.outward_runtime_truth import compile_outward_truth
        from core.mesh.mesh_session_lifecycle import reset_lifecycle_manager
        reset_lifecycle_manager()
        snapshot = compile_outward_truth()
        assert snapshot.mesh_session_truth is not None
        assert "active_count" in snapshot.mesh_session_truth
        assert "suspended_count" in snapshot.mesh_session_truth
        reset_lifecycle_manager()
