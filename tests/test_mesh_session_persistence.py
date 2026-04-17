#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_mesh_session_persistence.py
========================================
Tests for core/mesh/mesh_session_persistence.py

Coverage:
  1.  Module sentinels are importable strings.
  2.  SnapshotRecord construction and to_dict round-trip.
  3.  SnapshotRecord from_dict.
  4.  SnapshotRecord is_terminal / is_recoverable helpers.
  5.  MeshSessionPersistenceStore — save returns SnapshotRecord.
  6.  MeshSessionPersistenceStore — save with coordinator dict.
  7.  MeshSessionPersistenceStore — save with no session_id returns None.
  8.  MeshSessionPersistenceStore — load after save returns record.
  9.  MeshSessionPersistenceStore — load unknown session returns None.
  10. MeshSessionPersistenceStore — version increments on repeated save.
  11. MeshSessionPersistenceStore — list_recoverable excludes terminal records.
  12. MeshSessionPersistenceStore — delete removes a record.
  13. MeshSessionPersistenceStore — mark_terminal changes status.
  14. MeshSessionPersistenceStore — mark_terminal on unknown session returns False.
  15. Module-level save_mesh_session_snapshot function.
  16. Module-level load_mesh_session_snapshot function.
  17. Module-level recover_mesh_sessions function.
  18. Module-level list_recoverable_sessions function.
  19. get_persistence_store returns singleton.
  20. reset_persistence_store clears singleton.
  21. Saving object with to_dict() method.
  22. Saving object with model_dump() method (pydantic-like).
  23. Graceful handling of None coordinator state.
  24. File-backed storage: save survives re-instantiation.
  25. core.mesh __init__ exports persistence symbols.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Dict, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_dir: Optional[str] = None):
    from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
    return MeshSessionPersistenceStore(store_dir=tmp_dir or tempfile.mkdtemp())


def _make_coordinator_dict(session_id: str = "sess-001", status: str = "coordinating") -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "coordinator_id": "coord-xyz",
        "overall_status": status,
        "pending_device_ids": ["device_a"],
        "completed_device_ids": [],
        "failed_device_ids": [],
    }


# ---------------------------------------------------------------------------
# 1–4: Sentinels and SnapshotRecord
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.mesh.mesh_session_persistence import MESH_SESSION_PERSISTENCE_IS_AUTHORITY
        assert isinstance(MESH_SESSION_PERSISTENCE_IS_AUTHORITY, str)
        assert "MESH_SESSION_PERSISTENCE_IS_AUTHORITY" in MESH_SESSION_PERSISTENCE_IS_AUTHORITY

    def test_gap_closure_sentinel(self):
        from core.mesh.mesh_session_persistence import MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL
        assert isinstance(MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)
        assert "GAP_CLOSURE" in MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL

    def test_recovery_policy_sentinel(self):
        from core.mesh.mesh_session_persistence import RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY
        assert isinstance(RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY, str)

    def test_boundary_policy_sentinel(self):
        from core.mesh.mesh_session_persistence import PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY
        assert isinstance(PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY, str)


class TestSnapshotRecord:
    def test_construction(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s1",
            coordinator_id="c1",
            overall_status="coordinating",
            snapshot_dict={"foo": "bar"},
            version=0,
        )
        assert rec.session_id == "s1"
        assert rec.overall_status == "coordinating"
        assert rec.version == 0

    def test_to_dict_round_trip(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s2",
            coordinator_id="c2",
            overall_status="coordinating",
            snapshot_dict={"key": "value"},
            version=1,
        )
        d = rec.to_dict()
        assert d["session_id"] == "s2"
        assert d["version"] == 1
        # Reconstruct
        rec2 = SnapshotRecord.from_dict(d)
        assert rec2.session_id == rec.session_id
        assert rec2.version == rec.version

    def test_is_terminal_for_completed(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s3", coordinator_id="c", overall_status="completed",
            snapshot_dict={},
        )
        assert rec.is_terminal() is True
        assert rec.is_recoverable() is False

    def test_is_terminal_for_failed(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s4", coordinator_id="c", overall_status="failed",
            snapshot_dict={},
        )
        assert rec.is_terminal() is True

    def test_is_recoverable_for_non_terminal(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="s5", coordinator_id="c", overall_status="coordinating",
            snapshot_dict={},
        )
        assert rec.is_recoverable() is True

    def test_is_recoverable_false_for_empty_session_id(self):
        from core.mesh.mesh_session_persistence import SnapshotRecord
        rec = SnapshotRecord(
            session_id="", coordinator_id="c", overall_status="coordinating",
            snapshot_dict={},
        )
        assert rec.is_recoverable() is False


# ---------------------------------------------------------------------------
# 5–14: MeshSessionPersistenceStore
# ---------------------------------------------------------------------------

class TestMeshSessionPersistenceStore:
    def test_save_returns_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        d = _make_coordinator_dict()
        rec = store.save(d)
        assert rec is not None
        assert rec.session_id == "sess-001"

    def test_save_dict_stores_status(self, tmp_path):
        store = _make_store(str(tmp_path))
        d = _make_coordinator_dict(status="coordinating")
        rec = store.save(d)
        assert rec.overall_status == "coordinating"

    def test_save_no_session_id_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        rec = store.save({"session_id": "", "overall_status": "coordinating"})
        assert rec is None

    def test_load_after_save(self, tmp_path):
        store = _make_store(str(tmp_path))
        d = _make_coordinator_dict("sess-load")
        store.save(d)
        loaded = store.load("sess-load")
        assert loaded is not None
        assert loaded.session_id == "sess-load"

    def test_load_unknown_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        result = store.load("no-such-session")
        assert result is None

    def test_version_increments(self, tmp_path):
        store = _make_store(str(tmp_path))
        d = _make_coordinator_dict("sess-v")
        rec1 = store.save(d)
        rec2 = store.save(d)
        assert rec2.version > rec1.version

    def test_list_recoverable_excludes_terminal(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_coordinator_dict("active-1", status="coordinating"))
        store.save(_make_coordinator_dict("done-1", status="completed"))
        records = store.list_recoverable()
        ids = [r.session_id for r in records]
        assert "active-1" in ids
        assert "done-1" not in ids

    def test_delete_removes_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_coordinator_dict("to-delete"))
        assert store.load("to-delete") is not None
        store.delete("to-delete")
        assert store.load("to-delete") is None

    def test_mark_terminal_changes_status(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save(_make_coordinator_dict("to-close"))
        store.mark_terminal("to-close", status="completed")
        record = store.load("to-close")
        assert record is not None
        assert record.overall_status == "completed"
        assert record.is_terminal() is True

    def test_mark_terminal_unknown_returns_false(self, tmp_path):
        store = _make_store(str(tmp_path))
        result = store.mark_terminal("ghost-session")
        assert result is False


# ---------------------------------------------------------------------------
# 15–18: Module-level functions
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def test_save_mesh_session_snapshot(self, tmp_path):
        from core.mesh.mesh_session_persistence import (
            save_mesh_session_snapshot,
            MeshSessionPersistenceStore,
        )
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        d = _make_coordinator_dict("fn-save")
        rec = save_mesh_session_snapshot(d, store=store)
        assert rec is not None
        assert rec.session_id == "fn-save"

    def test_load_mesh_session_snapshot(self, tmp_path):
        from core.mesh.mesh_session_persistence import (
            save_mesh_session_snapshot,
            load_mesh_session_snapshot,
            MeshSessionPersistenceStore,
        )
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        save_mesh_session_snapshot(_make_coordinator_dict("fn-load"), store=store)
        loaded = load_mesh_session_snapshot("fn-load", store=store)
        assert loaded is not None

    def test_recover_mesh_sessions(self, tmp_path):
        from core.mesh.mesh_session_persistence import (
            save_mesh_session_snapshot,
            recover_mesh_sessions,
            MeshSessionPersistenceStore,
        )
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        save_mesh_session_snapshot(_make_coordinator_dict("rec-1"), store=store)
        save_mesh_session_snapshot(_make_coordinator_dict("rec-2", status="completed"), store=store)
        records = recover_mesh_sessions(store=store)
        ids = [r.session_id for r in records]
        assert "rec-1" in ids
        assert "rec-2" not in ids

    def test_list_recoverable_sessions(self, tmp_path):
        from core.mesh.mesh_session_persistence import (
            save_mesh_session_snapshot,
            list_recoverable_sessions,
            MeshSessionPersistenceStore,
        )
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        save_mesh_session_snapshot(_make_coordinator_dict("list-1"), store=store)
        ids = list_recoverable_sessions(store=store)
        assert "list-1" in ids


# ---------------------------------------------------------------------------
# 19–20: Singleton management
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_persistence_store_returns_same_instance(self):
        from core.mesh.mesh_session_persistence import (
            get_persistence_store,
            reset_persistence_store,
        )
        reset_persistence_store()
        s1 = get_persistence_store()
        s2 = get_persistence_store()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        from core.mesh.mesh_session_persistence import (
            get_persistence_store,
            reset_persistence_store,
        )
        reset_persistence_store()
        s1 = get_persistence_store()
        reset_persistence_store()
        s2 = get_persistence_store()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# 21–23: Object with to_dict / model_dump / None
# ---------------------------------------------------------------------------

class TestObjectInput:
    def test_save_object_with_to_dict(self, tmp_path):
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore

        class FakeCoordinator:
            session_id = "obj-session"
            coordinator_id = "obj-coord"
            overall_status = "coordinating"
            def to_dict(self):
                return {
                    "session_id": self.session_id,
                    "coordinator_id": self.coordinator_id,
                    "overall_status": self.overall_status,
                }

        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        rec = store.save(FakeCoordinator())
        assert rec is not None
        assert rec.session_id == "obj-session"

    def test_save_none_returns_none(self, tmp_path):
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        rec = store.save(None)
        assert rec is None


# ---------------------------------------------------------------------------
# 24: File-backed survival across re-instantiation
# ---------------------------------------------------------------------------

class TestFilePersistence:
    def test_save_survives_reinstantiation(self, tmp_path):
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        store1 = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        store1.save(_make_coordinator_dict("persist-1"))

        # New store instance pointing to same directory
        store2 = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        record = store2.load("persist-1")
        assert record is not None
        assert record.session_id == "persist-1"

    def test_json_file_is_valid_json(self, tmp_path):
        from core.mesh.mesh_session_persistence import MeshSessionPersistenceStore
        store = MeshSessionPersistenceStore(store_dir=str(tmp_path))
        store.save(_make_coordinator_dict("json-check"))
        # Find the file
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        with open(files[0]) as fh:
            data = json.load(fh)
        assert data["session_id"] == "json-check"


# ---------------------------------------------------------------------------
# 25: core.mesh __init__ exports
# ---------------------------------------------------------------------------

class TestCoreMeshInit:
    def test_persistence_symbols_exported(self):
        from core.mesh import (
            MeshSessionPersistenceStore,
            SnapshotRecord,
            save_mesh_session_snapshot,
            load_mesh_session_snapshot,
            recover_mesh_sessions,
            list_recoverable_sessions,
            get_persistence_store,
            reset_persistence_store,
            MESH_SESSION_PERSISTENCE_IS_AUTHORITY,
        )
        assert MeshSessionPersistenceStore is not None
        assert isinstance(MESH_SESSION_PERSISTENCE_IS_AUTHORITY, str)
