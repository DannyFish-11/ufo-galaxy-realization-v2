#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_session_contract_binding_persistence.py
=====================================================
PR-B2-V2: Session / Contract / Binding / Flow-Metadata Durable Persistence —
test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings.
B  — AttachedSessionSnapshotRecord: construction, defaults, to_dict/from_dict round-trip.
C  — AttachedRuntimeSessionPersistenceStore: save + load round-trip.
D  — AttachedRuntimeSessionPersistenceStore: save is atomic (no tmp file after save).
E  — AttachedRuntimeSessionPersistenceStore: load returns None when no file.
F  — AttachedRuntimeSessionPersistenceStore: load returns None on corrupt JSON.
G  — AttachedRuntimeSessionPersistenceStore: clear removes snapshot file.
H  — AttachedRuntimeSessionPersistenceStore: clear is safe when no file.
I  — save_attached_session_snapshot writes records.
J  — load_attached_session_snapshot returns None when no snapshot.
K  — restore_sessions_from_snapshot returns empty list when no snapshot.
L  — restore_sessions_from_snapshot restores all records.
M  — restore_sessions_from_snapshot populates ring buffer when populate_runtime=True.
N  — restore_sessions_from_snapshot skips malformed records gracefully.
O  — get_attached_session_store returns singleton.
P  — reset_attached_session_store resets singleton.

Q  — HandoffContractSnapshotRecord: round-trip.
R  — HandoffContractPersistenceStore: save + load round-trip.
S  — HandoffContractPersistenceStore: atomic write, no tmp file.
T  — HandoffContractPersistenceStore: load returns None when no file.
U  — restore_contracts_from_snapshot: empty when no snapshot.
V  — restore_contracts_from_snapshot: restores all records.
W  — restore_contracts_from_snapshot: populates ring buffer.

X  — DispatchBindingSnapshotRecord: round-trip.
Y  — DispatchBindingPersistenceStore: save + load round-trip.
Z  — DispatchBindingPersistenceStore: atomic write, no tmp file.
AA — DispatchBindingPersistenceStore: load returns None when no file.
AB — restore_bindings_from_snapshot: empty when no snapshot.
AC — restore_bindings_from_snapshot: restores all records.
AD — restore_bindings_from_snapshot: populates ring buffer.

AE — DelegatedFlowEntitySnapshotRecord: round-trip.
AF — DelegatedFlowEntityPersistenceStore: save + load round-trip.
AG — DelegatedFlowEntityPersistenceStore: atomic write, no tmp file.
AH — DelegatedFlowEntityPersistenceStore: load returns None when no file.
AI — restore_flows_from_snapshot: empty when no snapshot.
AJ — restore_flows_from_snapshot: restores all entities.
AK — restore_flows_from_snapshot: populates ring buffer.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

import pytest

from core.session_contract_binding_persistence import (
    # Sentinels
    SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY,
    SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL,
    RING_BUFFER_REMAINS_FAST_PATH_POLICY,
    RESTORE_POPULATES_RING_BUFFER_POLICY,
    # Session
    AttachedSessionSnapshotRecord,
    AttachedRuntimeSessionPersistenceStore,
    save_attached_session_snapshot,
    load_attached_session_snapshot,
    restore_sessions_from_snapshot,
    get_attached_session_store,
    reset_attached_session_store,
    # Contract
    HandoffContractSnapshotRecord,
    HandoffContractPersistenceStore,
    save_handoff_contract_snapshot,
    load_handoff_contract_snapshot,
    restore_contracts_from_snapshot,
    get_handoff_contract_store,
    reset_handoff_contract_store,
    # Binding
    DispatchBindingSnapshotRecord,
    DispatchBindingPersistenceStore,
    save_dispatch_binding_snapshot,
    load_dispatch_binding_snapshot,
    restore_bindings_from_snapshot,
    get_dispatch_binding_store,
    reset_dispatch_binding_store,
    # Flow
    DelegatedFlowEntitySnapshotRecord,
    DelegatedFlowEntityPersistenceStore,
    save_delegated_flow_snapshot,
    load_delegated_flow_snapshot,
    restore_flows_from_snapshot,
    get_delegated_flow_store,
    reset_delegated_flow_store,
)


# ---------------------------------------------------------------------------
# Helper: store factories
# ---------------------------------------------------------------------------

def _session_store(tmp_path) -> AttachedRuntimeSessionPersistenceStore:
    return AttachedRuntimeSessionPersistenceStore(
        store_path=os.path.join(str(tmp_path), "sess.json")
    )


def _contract_store(tmp_path) -> HandoffContractPersistenceStore:
    return HandoffContractPersistenceStore(
        store_path=os.path.join(str(tmp_path), "hc.json")
    )


def _binding_store(tmp_path) -> DispatchBindingPersistenceStore:
    return DispatchBindingPersistenceStore(
        store_path=os.path.join(str(tmp_path), "db.json")
    )


def _flow_store(tmp_path) -> DelegatedFlowEntityPersistenceStore:
    return DelegatedFlowEntityPersistenceStore(
        store_path=os.path.join(str(tmp_path), "dfe.json")
    )


# ---------------------------------------------------------------------------
# Helper: minimal record dicts
# ---------------------------------------------------------------------------

def _session_record_dict(device_id: str = "dev-1") -> Dict[str, Any]:
    return {
        "record_id": f"rec-{device_id}",
        "device_id": device_id,
        "session_id": f"sess-{device_id}",
        "runtime_attachment_session_id": f"sess-{device_id}",
        "source_runtime_posture": "join_runtime",
        "coordination_role": "primary",
        "android_host_role": "",
        "capability_tier": "",
        "attachment_state": "attached",
        "previous_state": None,
        "attach_reason": "test",
        "last_signal": None,
        "attached_at": time.time(),
        "last_transition_at": time.time(),
        "metadata": {},
    }


def _contract_record_dict(session_id: str = "sess-1") -> Dict[str, Any]:
    return {
        "identity": {
            "contract_id": f"cid-{session_id}",
            "session_id": session_id,
            "device_id": "dev-1",
            "dispatch_record_id": f"drid-{session_id}",
            "trace_id": "trace-1",
        },
        "meta": {
            "source_runtime_posture": "join_runtime",
            "coordination_role": "",
            "android_host_role": "",
            "capability_tier": "unknown",
            "delegation_intent": "none",
            "continuation_hint": "",
            "contract_version": "v2",
            "metadata": {},
        },
        "payload": {
            "task_body": {"cmd": "open_app"},
            "task_id": f"tid-{session_id}",
            "capability": "screen_control",
            "exec_mode": "remote",
            "raw_payload": {},
            "metadata": {},
        },
        "status": "draft",
        "created_at": time.time(),
        "sealed_at": 0.0,
        "reject_reason": "",
    }


def _binding_record_dict(session_id: str = "sess-1") -> Dict[str, Any]:
    return {
        "identity": {
            "binding_id": f"bid-{session_id}",
            "session_id": session_id,
            "device_id": "dev-1",
            "contract_id": f"cid-{session_id}",
            "tracker_id": "",
            "trace_id": "trace-1",
        },
        "binding_state": "bound",
        "source_runtime_posture": "join_runtime",
        "coordination_role": "",
        "android_host_role": "",
        "capability_tier": "",
        "is_session_anchored": True,
        "is_device_bound": True,
        "reject_reason": "",
        "created_at": time.time(),
        "updated_at": time.time(),
        "metadata": {},
    }


def _flow_entity_dict(flow_id: str = "flow-1") -> Dict[str, Any]:
    return {
        "identity": {
            "delegated_flow_id": flow_id,
            "flow_lineage_id": f"lin-{flow_id}",
            "flow_segment_id": "",
            "trace_id": "trace-1",
            "flow_kind": "task_assign",
        },
        "phase": "created",
        "ownership": {
            "canonical_flow_owner": "v2_canonical",
            "execution_owner": "v2_canonical",
            "ownership_rationale": "",
        },
        "object_mapping": {
            "canonical_task_id": "",
            "dispatch_record_id": "",
            "contract_id": "",
            "binding_id": "",
            "tracker_id": "",
            "session_id": "",
            "device_id": "",
        },
        "extension_points": {
            "continuity_token": None,
            "replay_anchor_id": None,
            "result_convergence_key": None,
            "operator_visibility_tag": None,
        },
        "created_at": time.time(),
        "last_updated_at": time.time(),
        "metadata": {},
    }


# ===========================================================================
# A — Sentinels
# ===========================================================================


class TestSentinels:
    def test_authority_sentinel_is_non_empty_string(self):
        assert isinstance(SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY, str)
        assert len(SESSION_CONTRACT_BINDING_PERSISTENCE_IS_AUTHORITY) > 20

    def test_gap_closure_sentinel_is_non_empty_string(self):
        assert isinstance(SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL, str)
        assert len(SESSION_CONTRACT_BINDING_GAP_CLOSURE_SENTINEL) > 20

    def test_ring_buffer_policy_is_non_empty_string(self):
        assert isinstance(RING_BUFFER_REMAINS_FAST_PATH_POLICY, str)
        assert len(RING_BUFFER_REMAINS_FAST_PATH_POLICY) > 20

    def test_restore_policy_is_non_empty_string(self):
        assert isinstance(RESTORE_POPULATES_RING_BUFFER_POLICY, str)
        assert len(RESTORE_POPULATES_RING_BUFFER_POLICY) > 20


# ===========================================================================
# B — AttachedSessionSnapshotRecord
# ===========================================================================


class TestAttachedSessionSnapshotRecord:
    def test_defaults(self):
        rec = AttachedSessionSnapshotRecord()
        assert rec.snapshot_id.startswith("sess_")
        assert rec.records == []
        assert rec.process_pid > 0

    def test_round_trip(self):
        rec = AttachedSessionSnapshotRecord(
            records=[_session_record_dict()]
        )
        d = rec.to_dict()
        rec2 = AttachedSessionSnapshotRecord.from_dict(d)
        assert rec2.snapshot_id == rec.snapshot_id
        assert rec2.records == rec.records
        assert rec2.process_pid == rec.process_pid


# ===========================================================================
# C, D, E, F, G, H — AttachedRuntimeSessionPersistenceStore
# ===========================================================================


class TestAttachedRuntimeSessionPersistenceStore:
    def test_save_load_round_trip(self, tmp_path):
        store = _session_store(tmp_path)
        snap = AttachedSessionSnapshotRecord(records=[_session_record_dict()])
        assert store.save(snap) is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 1
        assert loaded.records[0]["device_id"] == "dev-1"

    def test_save_is_atomic_no_tmp_file(self, tmp_path):
        store = _session_store(tmp_path)
        snap = AttachedSessionSnapshotRecord(records=[_session_record_dict()])
        store.save(snap)
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []

    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _session_store(tmp_path)
        assert store.load() is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        store = _session_store(tmp_path)
        path = os.path.join(str(tmp_path), "sess.json")
        with open(path, "w") as fh:
            fh.write("NOT VALID JSON {{{")
        assert store.load() is None

    def test_clear_removes_file(self, tmp_path):
        store = _session_store(tmp_path)
        snap = AttachedSessionSnapshotRecord(records=[_session_record_dict()])
        store.save(snap)
        assert os.path.exists(store.store_path)
        assert store.clear() is True
        assert not os.path.exists(store.store_path)

    def test_clear_safe_when_no_file(self, tmp_path):
        store = _session_store(tmp_path)
        assert store.clear() is True


# ===========================================================================
# I, J — save_attached_session_snapshot / load_attached_session_snapshot
# ===========================================================================


class TestAttachedSessionConvenienceFunctions:
    def test_save_attached_session_snapshot_writes_records(self, tmp_path):
        store = _session_store(tmp_path)
        snap = save_attached_session_snapshot(
            [_session_record_dict("dev-A")], store=store
        )
        assert len(snap.records) == 1
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id

    def test_load_attached_session_snapshot_returns_none_when_no_snapshot(self, tmp_path):
        store = _session_store(tmp_path)
        assert load_attached_session_snapshot(store=store) is None


# ===========================================================================
# K, L, M, N — restore_sessions_from_snapshot
# ===========================================================================


class TestRestoreSessionsFromSnapshot:
    def test_returns_empty_when_no_snapshot(self, tmp_path):
        store = _session_store(tmp_path)
        result = restore_sessions_from_snapshot(store=store, populate_runtime=False)
        assert result == []

    def test_restores_all_records(self, tmp_path):
        store = _session_store(tmp_path)
        records = [_session_record_dict("dev-1"), _session_record_dict("dev-2")]
        save_attached_session_snapshot(records, store=store)

        from core.attached_runtime_session import reset_attached_runtime_session_runtime
        reset_attached_runtime_session_runtime()

        restored = restore_sessions_from_snapshot(store=store, populate_runtime=False)
        assert len(restored) == 2
        device_ids = {r.device_id for r in restored}
        assert device_ids == {"dev-1", "dev-2"}

    def test_populates_ring_buffer(self, tmp_path):
        from core.attached_runtime_session import (
            get_attached_runtime_session_runtime,
            reset_attached_runtime_session_runtime,
        )
        reset_attached_runtime_session_runtime()

        store = _session_store(tmp_path)
        save_attached_session_snapshot([_session_record_dict("dev-X")], store=store)

        runtime = get_attached_runtime_session_runtime()
        assert runtime.size() == 0

        restore_sessions_from_snapshot(store=store, populate_runtime=True)
        assert runtime.size() == 1
        assert runtime.get_latest_for_device("dev-X") is not None

    def test_skips_malformed_records(self, tmp_path):
        store = _session_store(tmp_path)
        good = _session_record_dict("dev-good")
        bad = "this is not a dict"  # type: ignore[assignment]
        snap = AttachedSessionSnapshotRecord(records=[bad, good])  # type: ignore[list-item]
        store.save(snap)

        from core.attached_runtime_session import reset_attached_runtime_session_runtime
        reset_attached_runtime_session_runtime()

        restored = restore_sessions_from_snapshot(store=store, populate_runtime=False)
        assert len(restored) == 1
        assert restored[0].device_id == "dev-good"


# ===========================================================================
# O, P — get_attached_session_store / reset_attached_session_store
# ===========================================================================


class TestAttachedSessionStoreSingleton:
    def test_returns_singleton(self, tmp_path):
        reset_attached_session_store()
        store1 = get_attached_session_store()
        store2 = get_attached_session_store()
        assert store1 is store2

    def test_reset_clears_singleton(self, tmp_path):
        reset_attached_session_store()
        store1 = get_attached_session_store()
        reset_attached_session_store()
        store2 = get_attached_session_store()
        assert store1 is not store2


# ===========================================================================
# Q — HandoffContractSnapshotRecord
# ===========================================================================


class TestHandoffContractSnapshotRecord:
    def test_defaults(self):
        rec = HandoffContractSnapshotRecord()
        assert rec.snapshot_id.startswith("hc_")
        assert rec.records == []

    def test_round_trip(self):
        rec = HandoffContractSnapshotRecord(
            records=[_contract_record_dict()]
        )
        rec2 = HandoffContractSnapshotRecord.from_dict(rec.to_dict())
        assert rec2.snapshot_id == rec.snapshot_id
        assert rec2.records == rec.records


# ===========================================================================
# R, S, T — HandoffContractPersistenceStore
# ===========================================================================


class TestHandoffContractPersistenceStore:
    def test_save_load_round_trip(self, tmp_path):
        store = _contract_store(tmp_path)
        snap = HandoffContractSnapshotRecord(records=[_contract_record_dict()])
        assert store.save(snap) is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 1

    def test_save_is_atomic_no_tmp_file(self, tmp_path):
        store = _contract_store(tmp_path)
        store.save(HandoffContractSnapshotRecord(records=[_contract_record_dict()]))
        assert [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")] == []

    def test_load_returns_none_when_no_file(self, tmp_path):
        assert _contract_store(tmp_path).load() is None


# ===========================================================================
# U, V, W — restore_contracts_from_snapshot
# ===========================================================================


class TestRestoreContractsFromSnapshot:
    def test_returns_empty_when_no_snapshot(self, tmp_path):
        store = _contract_store(tmp_path)
        assert restore_contracts_from_snapshot(store=store, populate_runtime=False) == []

    def test_restores_all_records(self, tmp_path):
        from core.delegated_runtime_handoff_contract import reset_handoff_contract_runtime
        reset_handoff_contract_runtime()

        store = _contract_store(tmp_path)
        records = [_contract_record_dict("s1"), _contract_record_dict("s2")]
        save_handoff_contract_snapshot(records, store=store)

        restored = restore_contracts_from_snapshot(store=store, populate_runtime=False)
        assert len(restored) == 2

    def test_populates_ring_buffer(self, tmp_path):
        from core.delegated_runtime_handoff_contract import (
            get_handoff_contract_runtime,
            reset_handoff_contract_runtime,
        )
        reset_handoff_contract_runtime()

        store = _contract_store(tmp_path)
        save_handoff_contract_snapshot([_contract_record_dict("s-X")], store=store)

        runtime = get_handoff_contract_runtime()
        assert runtime.size == 0

        restore_contracts_from_snapshot(store=store, populate_runtime=True)
        assert runtime.size == 1


# ===========================================================================
# X — DispatchBindingSnapshotRecord
# ===========================================================================


class TestDispatchBindingSnapshotRecord:
    def test_defaults(self):
        rec = DispatchBindingSnapshotRecord()
        assert rec.snapshot_id.startswith("db_")
        assert rec.records == []

    def test_round_trip(self):
        rec = DispatchBindingSnapshotRecord(records=[_binding_record_dict()])
        rec2 = DispatchBindingSnapshotRecord.from_dict(rec.to_dict())
        assert rec2.snapshot_id == rec.snapshot_id
        assert rec2.records == rec.records


# ===========================================================================
# Y, Z, AA — DispatchBindingPersistenceStore
# ===========================================================================


class TestDispatchBindingPersistenceStore:
    def test_save_load_round_trip(self, tmp_path):
        store = _binding_store(tmp_path)
        snap = DispatchBindingSnapshotRecord(records=[_binding_record_dict()])
        assert store.save(snap) is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 1

    def test_save_is_atomic_no_tmp_file(self, tmp_path):
        store = _binding_store(tmp_path)
        store.save(DispatchBindingSnapshotRecord(records=[_binding_record_dict()]))
        assert [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")] == []

    def test_load_returns_none_when_no_file(self, tmp_path):
        assert _binding_store(tmp_path).load() is None


# ===========================================================================
# AB, AC, AD — restore_bindings_from_snapshot
# ===========================================================================


class TestRestoreBindingsFromSnapshot:
    def test_returns_empty_when_no_snapshot(self, tmp_path):
        store = _binding_store(tmp_path)
        assert restore_bindings_from_snapshot(store=store, populate_runtime=False) == []

    def test_restores_all_records(self, tmp_path):
        from core.android_runtime_dispatch_binding import reset_dispatch_binding_runtime
        reset_dispatch_binding_runtime()

        store = _binding_store(tmp_path)
        records = [_binding_record_dict("s1"), _binding_record_dict("s2")]
        save_dispatch_binding_snapshot(records, store=store)

        restored = restore_bindings_from_snapshot(store=store, populate_runtime=False)
        assert len(restored) == 2

    def test_populates_ring_buffer(self, tmp_path):
        from core.android_runtime_dispatch_binding import (
            get_dispatch_binding_runtime,
            reset_dispatch_binding_runtime,
        )
        reset_dispatch_binding_runtime()

        store = _binding_store(tmp_path)
        save_dispatch_binding_snapshot([_binding_record_dict("s-Y")], store=store)

        runtime = get_dispatch_binding_runtime()
        assert runtime.size() == 0

        restore_bindings_from_snapshot(store=store, populate_runtime=True)
        assert runtime.size() == 1


# ===========================================================================
# AE — DelegatedFlowEntitySnapshotRecord
# ===========================================================================


class TestDelegatedFlowEntitySnapshotRecord:
    def test_defaults(self):
        rec = DelegatedFlowEntitySnapshotRecord()
        assert rec.snapshot_id.startswith("dfe_")
        assert rec.records == []

    def test_round_trip(self):
        rec = DelegatedFlowEntitySnapshotRecord(records=[_flow_entity_dict()])
        rec2 = DelegatedFlowEntitySnapshotRecord.from_dict(rec.to_dict())
        assert rec2.snapshot_id == rec.snapshot_id
        assert rec2.records == rec.records


# ===========================================================================
# AF, AG, AH — DelegatedFlowEntityPersistenceStore
# ===========================================================================


class TestDelegatedFlowEntityPersistenceStore:
    def test_save_load_round_trip(self, tmp_path):
        store = _flow_store(tmp_path)
        snap = DelegatedFlowEntitySnapshotRecord(records=[_flow_entity_dict()])
        assert store.save(snap) is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 1

    def test_save_is_atomic_no_tmp_file(self, tmp_path):
        store = _flow_store(tmp_path)
        store.save(DelegatedFlowEntitySnapshotRecord(records=[_flow_entity_dict()]))
        assert [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")] == []

    def test_load_returns_none_when_no_file(self, tmp_path):
        assert _flow_store(tmp_path).load() is None


# ===========================================================================
# AI, AJ, AK — restore_flows_from_snapshot
# ===========================================================================


class TestRestoreFlowsFromSnapshot:
    def test_returns_empty_when_no_snapshot(self, tmp_path):
        store = _flow_store(tmp_path)
        assert restore_flows_from_snapshot(store=store, populate_runtime=False) == []

    def test_restores_all_entities(self, tmp_path):
        from core.delegated_flow_entity import reset_delegated_flow_entity_runtime
        reset_delegated_flow_entity_runtime()

        store = _flow_store(tmp_path)
        entities = [_flow_entity_dict("f1"), _flow_entity_dict("f2")]
        save_delegated_flow_snapshot(entities, store=store)

        restored = restore_flows_from_snapshot(store=store, populate_runtime=False)
        assert len(restored) == 2
        flow_ids = {e.identity.delegated_flow_id for e in restored}
        assert flow_ids == {"f1", "f2"}

    def test_populates_ring_buffer(self, tmp_path):
        from core.delegated_flow_entity import (
            get_delegated_flow_entity_runtime,
            reset_delegated_flow_entity_runtime,
        )
        reset_delegated_flow_entity_runtime()

        store = _flow_store(tmp_path)
        save_delegated_flow_snapshot([_flow_entity_dict("f-Z")], store=store)

        runtime = get_delegated_flow_entity_runtime()
        assert runtime.total_seen == 0

        restore_flows_from_snapshot(store=store, populate_runtime=True)
        assert runtime.get_by_flow_id("f-Z") is not None
