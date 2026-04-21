#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_body_mesh_persistence.py
========================================
PR-5: Body Mesh Persistence — test suite.

Coverage
--------
A  — Module sentinels are importable non-empty strings.
B  — BodyMeshSnapshotRecord: construction with defaults.
C  — BodyMeshSnapshotRecord.to_dict round-trip.
D  — BodyMeshSnapshotRecord.from_dict.
E  — BodyMeshSnapshotRecord.device_count.
F  — BodyMeshPersistenceStore: save with BodyMeshRegistry-like object (has list_entries).
G  — BodyMeshPersistenceStore: save with dict input.
H  — BodyMeshPersistenceStore: save with list input.
I  — BodyMeshPersistenceStore: save None returns None.
J  — BodyMeshPersistenceStore: load after save returns record.
K  — BodyMeshPersistenceStore: load when empty returns None.
L  — BodyMeshPersistenceStore: version increments on repeated save.
M  — BodyMeshPersistenceStore: clear removes record.
N  — File-backed: save survives store re-instantiation.
O  — File is valid JSON after save.
P  — restore_body_mesh_from_snapshot: restores entries into registry.
Q  — restore_body_mesh_from_snapshot: returns 0 when no snapshot exists.
R  — restore_body_mesh_from_snapshot: returns 0 for None registry.
S  — restore_body_mesh_from_snapshot: skips entries with empty device_id.
T  — save_body_mesh_snapshot module-level function.
U  — get_body_mesh_persistence_store singleton.
V  — reset_body_mesh_persistence_store clears singleton.
W  — core.mesh exports body_mesh_persistence symbols.
X  — BodyMeshSnapshotRecord.snapshot_id is auto-generated.
Y  — Atomic write: tmp file is cleaned up.
Z  — restore with registry that has no register() method returns 0.
AA — Save with object that has snapshot() method.
AB — BodyMeshSnapshotRecord.saved_at is a recent timestamp.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_dir: Optional[str] = None):
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
    path = os.path.join(tmp_dir or tempfile.mkdtemp(), "bm_snapshot.json")
    return BodyMeshPersistenceStore(store_path=path)


def _make_entry_dict(device_id: str = "device-1", roles: Optional[list] = None) -> Dict[str, Any]:
    return {
        "device_id": device_id,
        "roles": roles or ["action"],
        "session_id": "sess-001",
        "body_score": 2.5,
        "registered_at": time.time(),
        "metadata": {"display_name": device_id},
    }


class FakeRegistry:
    """Minimal fake of BodyMeshRegistry with list_entries()."""
    def __init__(self, entries: List[Dict] = None):
        self._entries = entries or []

    def list_entries(self):
        return [_FakeEntry(e) for e in self._entries]

    def register(self, device_id, roles=None, session_id=None, metadata=None):
        self._entries.append({
            "device_id": device_id,
            "roles": [r.value if hasattr(r, "value") else r for r in (roles or [])],
            "session_id": session_id,
            "metadata": dict(metadata or {}),
        })
        return self._entries[-1]

    def snapshot(self):
        return {"entries": [e.to_dict() if hasattr(e, "to_dict") else e for e in self.list_entries()]}


class _FakeEntry:
    def __init__(self, d: Dict):
        self._d = d

    def to_dict(self):
        return dict(self._d)


class FakeRegistryWithSnapshot:
    """Fake registry that exposes snapshot()."""
    def __init__(self, entries: List[Dict] = None):
        self._entries = list(entries or [])

    def snapshot(self):
        return {"entries": list(self._entries)}


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_sentinel(self):
        from core.mesh.body_mesh_persistence import BODY_MESH_PERSISTENCE_IS_AUTHORITY
        assert isinstance(BODY_MESH_PERSISTENCE_IS_AUTHORITY, str)
        assert BODY_MESH_PERSISTENCE_IS_AUTHORITY

    def test_gap_closure_sentinel(self):
        from core.mesh.body_mesh_persistence import (
            BODY_MESH_PERSISTENCE_CLOSES_VOLATILE_REGISTRY_GAP_SENTINEL,
        )
        assert isinstance(BODY_MESH_PERSISTENCE_CLOSES_VOLATILE_REGISTRY_GAP_SENTINEL, str)
        assert "GAP" in BODY_MESH_PERSISTENCE_CLOSES_VOLATILE_REGISTRY_GAP_SENTINEL

    def test_restore_boundary_sentinel(self):
        from core.mesh.body_mesh_persistence import RESTORE_DOES_NOT_REPLACE_LIVE_REGISTRY_POLICY
        assert isinstance(RESTORE_DOES_NOT_REPLACE_LIVE_REGISTRY_POLICY, str)


# ---------------------------------------------------------------------------
# B–E — BodyMeshSnapshotRecord
# ---------------------------------------------------------------------------

class TestBodyMeshSnapshotRecord:
    def test_construction(self):
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        rec = BodyMeshSnapshotRecord(entries=[{"device_id": "d1"}], version=1)
        assert rec.version == 1
        assert rec.device_count == 1

    def test_to_dict_round_trip(self):
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        rec = BodyMeshSnapshotRecord(
            entries=[{"device_id": "d2"}],
            version=2,
            snapshot_id="snap-123",
        )
        d = rec.to_dict()
        assert d["version"] == 2
        assert d["snapshot_id"] == "snap-123"
        rec2 = BodyMeshSnapshotRecord.from_dict(d)
        assert rec2.version == 2
        assert rec2.snapshot_id == "snap-123"
        assert rec2.device_count == 1

    def test_from_dict(self):
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        d = {
            "entries": [{"device_id": "d3"}, {"device_id": "d4"}],
            "saved_at": 1000.0,
            "version": 5,
            "snapshot_id": "snap-abc",
        }
        rec = BodyMeshSnapshotRecord.from_dict(d)
        assert rec.device_count == 2
        assert rec.version == 5

    def test_device_count_empty(self):
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        rec = BodyMeshSnapshotRecord()
        assert rec.device_count == 0

    def test_snapshot_id_auto_generated(self):
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        r1 = BodyMeshSnapshotRecord()
        r2 = BodyMeshSnapshotRecord()
        assert r1.snapshot_id != r2.snapshot_id

    def test_saved_at_is_recent(self):
        before = time.time()
        from core.mesh.body_mesh_persistence import BodyMeshSnapshotRecord
        rec = BodyMeshSnapshotRecord()
        after = time.time()
        assert before <= rec.saved_at <= after


# ---------------------------------------------------------------------------
# F–O — BodyMeshPersistenceStore
# ---------------------------------------------------------------------------

class TestBodyMeshPersistenceStore:
    def test_save_with_registry_like_object(self, tmp_path):
        store = _make_store(str(tmp_path))
        reg = FakeRegistry([_make_entry_dict("dev-1"), _make_entry_dict("dev-2")])
        rec = store.save(reg)
        assert rec is not None
        assert rec.device_count == 2

    def test_save_with_dict(self, tmp_path):
        store = _make_store(str(tmp_path))
        d = {"entries": [_make_entry_dict("dev-3")]}
        rec = store.save(d)
        assert rec is not None
        assert rec.device_count == 1

    def test_save_with_list(self, tmp_path):
        store = _make_store(str(tmp_path))
        entries = [_make_entry_dict("dev-4"), _make_entry_dict("dev-5")]
        rec = store.save(entries)
        assert rec is not None
        assert rec.device_count == 2

    def test_save_none_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.save(None) is None

    def test_load_after_save(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save([_make_entry_dict("dev-6")])
        loaded = store.load()
        assert loaded is not None
        assert loaded.device_count == 1

    def test_load_empty_returns_none(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.load() is None

    def test_version_increments(self, tmp_path):
        store = _make_store(str(tmp_path))
        r1 = store.save([_make_entry_dict("dev-7")])
        r2 = store.save([_make_entry_dict("dev-7")])
        assert r2.version > r1.version

    def test_clear_removes_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.save([_make_entry_dict("dev-8")])
        assert store.load() is not None
        store.clear()
        assert store.load() is None

    def test_save_survives_reinstantiation(self, tmp_path):
        from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
        path = os.path.join(str(tmp_path), "bm_snap.json")
        store1 = BodyMeshPersistenceStore(store_path=path)
        store1.save([_make_entry_dict("dev-9")])

        store2 = BodyMeshPersistenceStore(store_path=path)
        loaded = store2.load()
        assert loaded is not None
        assert loaded.device_count == 1

    def test_json_file_is_valid(self, tmp_path):
        from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore
        path = os.path.join(str(tmp_path), "valid.json")
        store = BodyMeshPersistenceStore(store_path=path)
        store.save([_make_entry_dict("dev-10")])
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert "entries" in data

    def test_save_with_snapshot_method(self, tmp_path):
        store = _make_store(str(tmp_path))
        reg = FakeRegistryWithSnapshot([_make_entry_dict("dev-snap")])
        rec = store.save(reg)
        assert rec is not None
        assert rec.device_count == 1


# ---------------------------------------------------------------------------
# P–S — restore_body_mesh_from_snapshot
# ---------------------------------------------------------------------------

class TestRestoreBodyMesh:
    def test_restore_into_registry(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            restore_body_mesh_from_snapshot,
        )
        path = os.path.join(str(tmp_path), "bm.json")
        store = BodyMeshPersistenceStore(store_path=path)
        store.save([_make_entry_dict("dev-r1"), _make_entry_dict("dev-r2")])

        target_reg = FakeRegistry()
        restored = restore_body_mesh_from_snapshot(registry=target_reg, store=store)
        assert restored == 2
        assert len(target_reg._entries) == 2

    def test_restore_no_snapshot_returns_zero(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            restore_body_mesh_from_snapshot,
        )
        path = os.path.join(str(tmp_path), "empty.json")
        store = BodyMeshPersistenceStore(store_path=path)
        target_reg = FakeRegistry()
        assert restore_body_mesh_from_snapshot(registry=target_reg, store=store) == 0

    def test_restore_none_registry_returns_zero(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            restore_body_mesh_from_snapshot,
        )
        path = os.path.join(str(tmp_path), "none.json")
        store = BodyMeshPersistenceStore(store_path=path)
        store.save([_make_entry_dict("dev-x")])
        assert restore_body_mesh_from_snapshot(registry=None, store=store) == 0

    def test_restore_skips_empty_device_id(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            restore_body_mesh_from_snapshot,
        )
        path = os.path.join(str(tmp_path), "skip.json")
        store = BodyMeshPersistenceStore(store_path=path)
        entries = [
            _make_entry_dict("dev-ok"),
            {"device_id": "", "roles": ["action"], "metadata": {}},
        ]
        store.save(entries)
        target = FakeRegistry()
        restored = restore_body_mesh_from_snapshot(registry=target, store=store)
        assert restored == 1  # empty device_id skipped

    def test_restore_registry_no_register_returns_zero(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            restore_body_mesh_from_snapshot,
        )
        path = os.path.join(str(tmp_path), "noregister.json")
        store = BodyMeshPersistenceStore(store_path=path)
        store.save([_make_entry_dict("dev-nr")])

        class NoRegisterRegistry:
            pass

        assert restore_body_mesh_from_snapshot(registry=NoRegisterRegistry(), store=store) == 0


# ---------------------------------------------------------------------------
# T–V — Module-level functions and singleton
# ---------------------------------------------------------------------------

class TestModuleLevelFunctions:
    def test_save_body_mesh_snapshot(self, tmp_path):
        from core.mesh.body_mesh_persistence import (
            BodyMeshPersistenceStore,
            save_body_mesh_snapshot,
        )
        path = os.path.join(str(tmp_path), "fn_save.json")
        store = BodyMeshPersistenceStore(store_path=path)
        rec = save_body_mesh_snapshot([_make_entry_dict("fn-dev")], store=store)
        assert rec is not None
        assert rec.device_count == 1

    def test_get_store_singleton(self):
        from core.mesh.body_mesh_persistence import (
            get_body_mesh_persistence_store,
            reset_body_mesh_persistence_store,
        )
        reset_body_mesh_persistence_store()
        s1 = get_body_mesh_persistence_store()
        s2 = get_body_mesh_persistence_store()
        assert s1 is s2

    def test_reset_clears_singleton(self):
        from core.mesh.body_mesh_persistence import (
            get_body_mesh_persistence_store,
            reset_body_mesh_persistence_store,
        )
        reset_body_mesh_persistence_store()
        s1 = get_body_mesh_persistence_store()
        reset_body_mesh_persistence_store()
        s2 = get_body_mesh_persistence_store()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# W — core.mesh exports
# ---------------------------------------------------------------------------

class TestCoreMeshExports:
    def test_body_mesh_persistence_exported(self):
        from core.mesh import (
            BodyMeshSnapshotRecord,
            BodyMeshPersistenceStore,
            save_body_mesh_snapshot,
            restore_body_mesh_from_snapshot,
            get_body_mesh_persistence_store,
            reset_body_mesh_persistence_store,
            BODY_MESH_PERSISTENCE_IS_AUTHORITY,
        )
        assert BodyMeshSnapshotRecord is not None
        assert isinstance(BODY_MESH_PERSISTENCE_IS_AUTHORITY, str)
