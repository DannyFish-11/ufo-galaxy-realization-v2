#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_session_contract_binding_persistence.py
===================================================
PR-D2: Durable Session / Contract / Binding / Flow Persistence — test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings.
B  — AttachedSessionSnapshotRecord: construction and defaults.
C  — AttachedSessionSnapshotRecord: to_dict / from_dict round-trip.
D  — HandoffContractSnapshotRecord: to_dict / from_dict round-trip.
E  — DispatchBindingSnapshotRecord: to_dict / from_dict round-trip.
F  — DelegatedFlowSnapshotRecord: to_dict / from_dict round-trip.
G  — AttachedSessionPersistenceStore.save + load round-trip.
H  — AttachedSessionPersistenceStore.save is atomic (no tmp files remain).
I  — AttachedSessionPersistenceStore.load returns None when no file.
J  — AttachedSessionPersistenceStore.load returns None on corrupt JSON.
K  — AttachedSessionPersistenceStore.clear removes the snapshot file.
L  — AttachedSessionPersistenceStore.clear is safe when no file exists.
M  — HandoffContractPersistenceStore.save + load round-trip.
N  — HandoffContractPersistenceStore.load returns None when no file.
O  — HandoffContractPersistenceStore.clear removes the snapshot file.
P  — DispatchBindingPersistenceStore.save + load round-trip.
Q  — DispatchBindingPersistenceStore.load returns None when no file.
R  — DispatchBindingPersistenceStore.clear removes the snapshot file.
S  — DelegatedFlowPersistenceStore.save + load round-trip.
T  — DelegatedFlowPersistenceStore.load returns None when no file.
U  — DelegatedFlowPersistenceStore.clear removes the snapshot file.
V  — get_attached_session_store returns singleton.
W  — reset_attached_session_store resets singleton.
X  — get_handoff_contract_store / reset_handoff_contract_store.
Y  — get_dispatch_binding_store / reset_dispatch_binding_store.
Z  — get_delegated_flow_store / reset_delegated_flow_store.
AA — save_attached_session_snapshot / load_attached_session_snapshot round-trip.
AB — load_attached_session_snapshot returns None when no snapshot.
AC — save_handoff_contract_snapshot / load_handoff_contract_snapshot round-trip.
AD — save_dispatch_binding_snapshot / load_dispatch_binding_snapshot round-trip.
AE — save_delegated_flow_snapshot / load_delegated_flow_snapshot round-trip.
AF — restore_attached_sessions_from_snapshot restores records to ring-buffer.
AG — restore_attached_sessions_from_snapshot returns 0 when no snapshot.
AH — restore_handoff_contracts_from_snapshot restores records to ring-buffer.
AI — restore_handoff_contracts_from_snapshot returns 0 when no snapshot.
AJ — restore_dispatch_bindings_from_snapshot restores records to ring-buffer.
AK — restore_dispatch_bindings_from_snapshot returns 0 when no snapshot.
AL — restore_delegated_flows_from_snapshot restores entities to ring-buffer.
AM — restore_delegated_flows_from_snapshot returns 0 when no snapshot.
AN — restore functions skip malformed records gracefully.
AO — snapshot records list preserves ordering.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict

import pytest

from core.session_contract_binding_persistence import (
    SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY,
    SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY,
    RING_BUFFER_REMAINS_FAST_ACCESS_POLICY,
    AttachedSessionSnapshotRecord,
    HandoffContractSnapshotRecord,
    DispatchBindingSnapshotRecord,
    DelegatedFlowSnapshotRecord,
    AttachedSessionPersistenceStore,
    HandoffContractPersistenceStore,
    DispatchBindingPersistenceStore,
    DelegatedFlowPersistenceStore,
    get_attached_session_store,
    reset_attached_session_store,
    get_handoff_contract_store,
    reset_handoff_contract_store,
    get_dispatch_binding_store,
    reset_dispatch_binding_store,
    get_delegated_flow_store,
    reset_delegated_flow_store,
    save_attached_session_snapshot,
    load_attached_session_snapshot,
    restore_attached_sessions_from_snapshot,
    save_handoff_contract_snapshot,
    load_handoff_contract_snapshot,
    restore_handoff_contracts_from_snapshot,
    save_dispatch_binding_snapshot,
    load_dispatch_binding_snapshot,
    restore_dispatch_bindings_from_snapshot,
    save_delegated_flow_snapshot,
    load_delegated_flow_snapshot,
    restore_delegated_flows_from_snapshot,
)


# ---------------------------------------------------------------------------
# Store factory helpers (isolated to tmp_path for each test)
# ---------------------------------------------------------------------------


def _make_session_store(tmp_path) -> AttachedSessionPersistenceStore:
    return AttachedSessionPersistenceStore(
        store_path=os.path.join(str(tmp_path), "session_snap.json")
    )


def _make_contract_store(tmp_path) -> HandoffContractPersistenceStore:
    return HandoffContractPersistenceStore(
        store_path=os.path.join(str(tmp_path), "contract_snap.json")
    )


def _make_binding_store(tmp_path) -> DispatchBindingPersistenceStore:
    return DispatchBindingPersistenceStore(
        store_path=os.path.join(str(tmp_path), "binding_snap.json")
    )


def _make_flow_store(tmp_path) -> DelegatedFlowPersistenceStore:
    return DelegatedFlowPersistenceStore(
        store_path=os.path.join(str(tmp_path), "flow_snap.json")
    )


# ---------------------------------------------------------------------------
# Sample record builders
# ---------------------------------------------------------------------------


def _session_record_dict(device_id: str = "dev-a", state: str = "attached") -> Dict[str, Any]:
    return {
        "record_id": f"rec-{device_id}",
        "device_id": device_id,
        "session_id": f"sess-{device_id}",
        "runtime_attachment_session_id": f"sess-{device_id}",
        "source_runtime_posture": "join_runtime",
        "coordination_role": "primary",
        "android_host_role": "",
        "capability_tier": "standard",
        "attachment_state": state,
        "previous_state": None,
        "attach_reason": "test",
        "last_signal": None,
        "attached_at": time.time(),
        "last_transition_at": time.time(),
        "metadata": {},
    }


def _contract_record_dict(contract_id: str = "ctr-1", session_id: str = "sess-1") -> Dict[str, Any]:
    return {
        "identity": {
            "contract_id": contract_id,
            "session_id": session_id,
            "device_id": "dev-a",
            "trace_id": "trace-1",
            "dispatch_record_id": "dr-1",
        },
        "meta": {
            "source_runtime_posture": "join_runtime",
            "coordination_role": "primary",
            "android_host_role": "",
            "capability_tier": "standard",
            "delegation_intent": "execute",
            "continuation_hint": "",
            "contract_version": "v2",
            "metadata": {},
        },
        "payload": {
            "task_body": {"goal": "test"},
            "task_id": "tid-1",
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


def _binding_record_dict(
    binding_id: str = "bind-1",
    session_id: str = "sess-1",
    device_id: str = "dev-a",
) -> Dict[str, Any]:
    return {
        "identity": {
            "binding_id": binding_id,
            "session_id": session_id,
            "device_id": device_id,
            "contract_id": "ctr-1",
            "tracker_id": "trk-1",
            "trace_id": "trace-1",
        },
        "binding_state": "bound",
        "source_runtime_posture": "join_runtime",
        "coordination_role": "primary",
        "android_host_role": "",
        "capability_tier": "standard",
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
            "flow_lineage_id": "lineage-1",
            "flow_segment_id": "",
            "trace_id": "trace-1",
            "flow_kind": "task_assign",
        },
        "phase": "created",
        "ownership": {
            "canonical_owner": "v2_canonical",
            "execution_owner": "none",
            "canonical_owner_rationale": "V2 holds flow truth",
            "execution_owner_rationale": "not dispatched yet",
        },
        "object_mapping": {
            "canonical_task_id": "task-1",
            "dispatch_record_id": "",
            "contract_id": "",
            "binding_id": "",
            "tracker_id": "",
            "session_id": "sess-1",
            "device_id": "dev-a",
            "android_flow_id": "",
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


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------


class TestSentinels:
    def test_authority_sentinel(self):
        assert SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY
        assert isinstance(SESSION_CONTRACT_BINDING_PERSISTENCE_AUTHORITY, str)

    def test_session_gap_sentinel(self):
        assert SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL
        assert isinstance(SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)

    def test_contract_gap_sentinel(self):
        assert CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL
        assert isinstance(CONTRACT_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)

    def test_binding_gap_sentinel(self):
        assert BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL
        assert isinstance(BINDING_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)

    def test_flow_gap_sentinel(self):
        assert FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL
        assert isinstance(FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL, str)

    def test_durable_store_policy_sentinel(self):
        assert DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY
        assert isinstance(DURABLE_STORE_IS_RECOVERY_FOUNDATION_POLICY, str)

    def test_ring_buffer_policy_sentinel(self):
        assert RING_BUFFER_REMAINS_FAST_ACCESS_POLICY
        assert isinstance(RING_BUFFER_REMAINS_FAST_ACCESS_POLICY, str)


# ---------------------------------------------------------------------------
# B-F — Snapshot record data classes
# ---------------------------------------------------------------------------


class TestSnapshotRecords:
    def test_attached_session_snapshot_defaults(self):
        snap = AttachedSessionSnapshotRecord()
        assert snap.snapshot_id.startswith("ass_")
        assert snap.records == []
        assert snap.created_at > 0

    def test_attached_session_snapshot_round_trip(self):
        original = AttachedSessionSnapshotRecord(records=[_session_record_dict()])
        restored = AttachedSessionSnapshotRecord.from_dict(original.to_dict())
        assert restored.snapshot_id == original.snapshot_id
        assert len(restored.records) == 1
        assert restored.records[0]["device_id"] == "dev-a"

    def test_handoff_contract_snapshot_defaults(self):
        snap = HandoffContractSnapshotRecord()
        assert snap.snapshot_id.startswith("hcs_")
        assert snap.records == []

    def test_handoff_contract_snapshot_round_trip(self):
        original = HandoffContractSnapshotRecord(records=[_contract_record_dict()])
        restored = HandoffContractSnapshotRecord.from_dict(original.to_dict())
        assert restored.snapshot_id == original.snapshot_id
        assert len(restored.records) == 1

    def test_dispatch_binding_snapshot_defaults(self):
        snap = DispatchBindingSnapshotRecord()
        assert snap.snapshot_id.startswith("dbs_")
        assert snap.records == []

    def test_dispatch_binding_snapshot_round_trip(self):
        original = DispatchBindingSnapshotRecord(records=[_binding_record_dict()])
        restored = DispatchBindingSnapshotRecord.from_dict(original.to_dict())
        assert restored.snapshot_id == original.snapshot_id
        assert len(restored.records) == 1

    def test_delegated_flow_snapshot_defaults(self):
        snap = DelegatedFlowSnapshotRecord()
        assert snap.snapshot_id.startswith("dfs_")
        assert snap.records == []

    def test_delegated_flow_snapshot_round_trip(self):
        original = DelegatedFlowSnapshotRecord(records=[_flow_entity_dict()])
        restored = DelegatedFlowSnapshotRecord.from_dict(original.to_dict())
        assert restored.snapshot_id == original.snapshot_id
        assert len(restored.records) == 1


# ---------------------------------------------------------------------------
# G-L — AttachedSessionPersistenceStore
# ---------------------------------------------------------------------------


class TestAttachedSessionPersistenceStore:
    def test_save_and_load_round_trip(self, tmp_path):
        store = _make_session_store(tmp_path)
        snap = AttachedSessionSnapshotRecord(records=[_session_record_dict("dev-a")])
        ok = store.save(snap)
        assert ok is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 1
        assert loaded.records[0]["device_id"] == "dev-a"

    def test_save_is_atomic_no_tmp_files(self, tmp_path):
        store = _make_session_store(tmp_path)
        store.save(AttachedSessionSnapshotRecord(records=[_session_record_dict()]))
        tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
        assert tmp_files == []

    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _make_session_store(tmp_path)
        assert store.load() is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        path = os.path.join(str(tmp_path), "session_snap.json")
        with open(path, "w") as fh:
            fh.write("NOT VALID JSON {{{")
        store = AttachedSessionPersistenceStore(store_path=path)
        assert store.load() is None

    def test_clear_removes_file(self, tmp_path):
        store = _make_session_store(tmp_path)
        store.save(AttachedSessionSnapshotRecord(records=[]))
        assert os.path.exists(store.store_path)
        ok = store.clear()
        assert ok is True
        assert not os.path.exists(store.store_path)

    def test_clear_safe_when_no_file(self, tmp_path):
        store = _make_session_store(tmp_path)
        ok = store.clear()
        assert ok is True

    def test_multiple_records_preserved(self, tmp_path):
        store = _make_session_store(tmp_path)
        records = [_session_record_dict(f"dev-{i}") for i in range(5)]
        store.save(AttachedSessionSnapshotRecord(records=records))
        loaded = store.load()
        assert loaded is not None
        assert len(loaded.records) == 5


# ---------------------------------------------------------------------------
# M-O — HandoffContractPersistenceStore
# ---------------------------------------------------------------------------


class TestHandoffContractPersistenceStore:
    def test_save_and_load_round_trip(self, tmp_path):
        store = _make_contract_store(tmp_path)
        snap = HandoffContractSnapshotRecord(records=[_contract_record_dict("ctr-1")])
        ok = store.save(snap)
        assert ok is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert loaded.records[0]["identity"]["contract_id"] == "ctr-1"

    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _make_contract_store(tmp_path)
        assert store.load() is None

    def test_clear_removes_file(self, tmp_path):
        store = _make_contract_store(tmp_path)
        store.save(HandoffContractSnapshotRecord(records=[]))
        ok = store.clear()
        assert ok is True
        assert not os.path.exists(store.store_path)


# ---------------------------------------------------------------------------
# P-R — DispatchBindingPersistenceStore
# ---------------------------------------------------------------------------


class TestDispatchBindingPersistenceStore:
    def test_save_and_load_round_trip(self, tmp_path):
        store = _make_binding_store(tmp_path)
        snap = DispatchBindingSnapshotRecord(records=[_binding_record_dict("bind-1")])
        ok = store.save(snap)
        assert ok is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert loaded.records[0]["identity"]["binding_id"] == "bind-1"

    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _make_binding_store(tmp_path)
        assert store.load() is None

    def test_clear_removes_file(self, tmp_path):
        store = _make_binding_store(tmp_path)
        store.save(DispatchBindingSnapshotRecord(records=[]))
        ok = store.clear()
        assert ok is True
        assert not os.path.exists(store.store_path)


# ---------------------------------------------------------------------------
# S-U — DelegatedFlowPersistenceStore
# ---------------------------------------------------------------------------


class TestDelegatedFlowPersistenceStore:
    def test_save_and_load_round_trip(self, tmp_path):
        store = _make_flow_store(tmp_path)
        snap = DelegatedFlowSnapshotRecord(records=[_flow_entity_dict("flow-1")])
        ok = store.save(snap)
        assert ok is True
        loaded = store.load()
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert loaded.records[0]["identity"]["delegated_flow_id"] == "flow-1"

    def test_load_returns_none_when_no_file(self, tmp_path):
        store = _make_flow_store(tmp_path)
        assert store.load() is None

    def test_clear_removes_file(self, tmp_path):
        store = _make_flow_store(tmp_path)
        store.save(DelegatedFlowSnapshotRecord(records=[]))
        ok = store.clear()
        assert ok is True
        assert not os.path.exists(store.store_path)


# ---------------------------------------------------------------------------
# V-Z — Singleton management
# ---------------------------------------------------------------------------


class TestSingletonManagement:
    def test_get_attached_session_store_returns_singleton(self, tmp_path):
        reset_attached_session_store()
        path = os.path.join(str(tmp_path), "as.json")
        s1 = get_attached_session_store(store_path=path)
        s2 = get_attached_session_store(store_path=path)
        assert s1 is s2
        reset_attached_session_store()

    def test_reset_attached_session_store(self, tmp_path):
        reset_attached_session_store()
        path = os.path.join(str(tmp_path), "as.json")
        s1 = get_attached_session_store(store_path=path)
        reset_attached_session_store()
        s2 = get_attached_session_store(store_path=path)
        assert s1 is not s2
        reset_attached_session_store()

    def test_get_handoff_contract_store_returns_singleton(self, tmp_path):
        reset_handoff_contract_store()
        path = os.path.join(str(tmp_path), "hc.json")
        s1 = get_handoff_contract_store(store_path=path)
        s2 = get_handoff_contract_store(store_path=path)
        assert s1 is s2
        reset_handoff_contract_store()

    def test_reset_handoff_contract_store(self, tmp_path):
        reset_handoff_contract_store()
        path = os.path.join(str(tmp_path), "hc.json")
        s1 = get_handoff_contract_store(store_path=path)
        reset_handoff_contract_store()
        s2 = get_handoff_contract_store(store_path=path)
        assert s1 is not s2
        reset_handoff_contract_store()

    def test_get_dispatch_binding_store_returns_singleton(self, tmp_path):
        reset_dispatch_binding_store()
        path = os.path.join(str(tmp_path), "db.json")
        s1 = get_dispatch_binding_store(store_path=path)
        s2 = get_dispatch_binding_store(store_path=path)
        assert s1 is s2
        reset_dispatch_binding_store()

    def test_reset_dispatch_binding_store(self, tmp_path):
        reset_dispatch_binding_store()
        path = os.path.join(str(tmp_path), "db.json")
        s1 = get_dispatch_binding_store(store_path=path)
        reset_dispatch_binding_store()
        s2 = get_dispatch_binding_store(store_path=path)
        assert s1 is not s2
        reset_dispatch_binding_store()

    def test_get_delegated_flow_store_returns_singleton(self, tmp_path):
        reset_delegated_flow_store()
        path = os.path.join(str(tmp_path), "df.json")
        s1 = get_delegated_flow_store(store_path=path)
        s2 = get_delegated_flow_store(store_path=path)
        assert s1 is s2
        reset_delegated_flow_store()

    def test_reset_delegated_flow_store(self, tmp_path):
        reset_delegated_flow_store()
        path = os.path.join(str(tmp_path), "df.json")
        s1 = get_delegated_flow_store(store_path=path)
        reset_delegated_flow_store()
        s2 = get_delegated_flow_store(store_path=path)
        assert s1 is not s2
        reset_delegated_flow_store()


# ---------------------------------------------------------------------------
# AA-AE — Convenience save/load functions
# ---------------------------------------------------------------------------


class TestConvenienceFunctions:
    def test_save_and_load_attached_session_snapshot(self, tmp_path):
        store = _make_session_store(tmp_path)
        records = [_session_record_dict("dev-a"), _session_record_dict("dev-b")]
        snap = save_attached_session_snapshot(records, store=store)
        assert len(snap.records) == 2
        loaded = load_attached_session_snapshot(store=store)
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 2

    def test_load_attached_session_snapshot_returns_none_when_no_snapshot(self, tmp_path):
        store = _make_session_store(tmp_path)
        assert load_attached_session_snapshot(store=store) is None

    def test_save_and_load_handoff_contract_snapshot(self, tmp_path):
        store = _make_contract_store(tmp_path)
        records = [_contract_record_dict("ctr-1"), _contract_record_dict("ctr-2")]
        snap = save_handoff_contract_snapshot(records, store=store)
        loaded = load_handoff_contract_snapshot(store=store)
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 2

    def test_save_and_load_dispatch_binding_snapshot(self, tmp_path):
        store = _make_binding_store(tmp_path)
        records = [_binding_record_dict("bind-1"), _binding_record_dict("bind-2")]
        snap = save_dispatch_binding_snapshot(records, store=store)
        loaded = load_dispatch_binding_snapshot(store=store)
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 2

    def test_save_and_load_delegated_flow_snapshot(self, tmp_path):
        store = _make_flow_store(tmp_path)
        records = [_flow_entity_dict("flow-1"), _flow_entity_dict("flow-2")]
        snap = save_delegated_flow_snapshot(records, store=store)
        loaded = load_delegated_flow_snapshot(store=store)
        assert loaded is not None
        assert loaded.snapshot_id == snap.snapshot_id
        assert len(loaded.records) == 2


# ---------------------------------------------------------------------------
# AF-AM — Recovery functions
# ---------------------------------------------------------------------------


class TestRestoreFunctions:
    def test_restore_attached_sessions_from_snapshot(self, tmp_path):
        from core.attached_runtime_session import (
            AttachedRuntimeSessionRuntime,
            AttachedRuntimeSessionRecord,
        )
        store = _make_session_store(tmp_path)
        records = [_session_record_dict("dev-a"), _session_record_dict("dev-b")]
        save_attached_session_snapshot(records, store=store)

        runtime = AttachedRuntimeSessionRuntime()
        count = restore_attached_sessions_from_snapshot(store=store, runtime=runtime)
        assert count == 2
        all_records = runtime.list_all()
        assert len(all_records) == 2
        device_ids = {r.device_id for r in all_records}
        assert "dev-a" in device_ids
        assert "dev-b" in device_ids

    def test_restore_attached_sessions_returns_0_when_no_snapshot(self, tmp_path):
        from core.attached_runtime_session import AttachedRuntimeSessionRuntime
        store = _make_session_store(tmp_path)
        runtime = AttachedRuntimeSessionRuntime()
        count = restore_attached_sessions_from_snapshot(store=store, runtime=runtime)
        assert count == 0
        assert runtime.size() == 0

    def test_restore_handoff_contracts_from_snapshot(self, tmp_path):
        from core.delegated_runtime_handoff_contract import DelegatedHandoffContractRuntime
        store = _make_contract_store(tmp_path)
        records = [_contract_record_dict("ctr-1"), _contract_record_dict("ctr-2")]
        save_handoff_contract_snapshot(records, store=store)

        runtime = DelegatedHandoffContractRuntime()
        count = restore_handoff_contracts_from_snapshot(store=store, runtime=runtime)
        assert count == 2
        all_records = runtime.list_all()
        assert len(all_records) == 2
        contract_ids = {r.identity.contract_id for r in all_records}
        assert "ctr-1" in contract_ids
        assert "ctr-2" in contract_ids

    def test_restore_handoff_contracts_returns_0_when_no_snapshot(self, tmp_path):
        from core.delegated_runtime_handoff_contract import DelegatedHandoffContractRuntime
        store = _make_contract_store(tmp_path)
        runtime = DelegatedHandoffContractRuntime()
        count = restore_handoff_contracts_from_snapshot(store=store, runtime=runtime)
        assert count == 0
        assert runtime.size == 0

    def test_restore_dispatch_bindings_from_snapshot(self, tmp_path):
        from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRuntime
        store = _make_binding_store(tmp_path)
        records = [_binding_record_dict("bind-1"), _binding_record_dict("bind-2")]
        save_dispatch_binding_snapshot(records, store=store)

        runtime = AndroidRuntimeDispatchBindingRuntime()
        count = restore_dispatch_bindings_from_snapshot(store=store, runtime=runtime)
        assert count == 2
        all_records = runtime.list_all()
        assert len(all_records) == 2
        binding_ids = {r.identity.binding_id for r in all_records}
        assert "bind-1" in binding_ids
        assert "bind-2" in binding_ids

    def test_restore_dispatch_bindings_returns_0_when_no_snapshot(self, tmp_path):
        from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRuntime
        store = _make_binding_store(tmp_path)
        runtime = AndroidRuntimeDispatchBindingRuntime()
        count = restore_dispatch_bindings_from_snapshot(store=store, runtime=runtime)
        assert count == 0
        assert runtime.size() == 0

    def test_restore_delegated_flows_from_snapshot(self, tmp_path):
        from core.delegated_flow_entity import DelegatedFlowEntityRuntime
        store = _make_flow_store(tmp_path)
        records = [_flow_entity_dict("flow-1"), _flow_entity_dict("flow-2")]
        save_delegated_flow_snapshot(records, store=store)

        runtime = DelegatedFlowEntityRuntime()
        count = restore_delegated_flows_from_snapshot(store=store, runtime=runtime)
        assert count == 2
        all_flows = runtime.list_all()
        assert len(all_flows) == 2
        flow_ids = {f.delegated_flow_id for f in all_flows}
        assert "flow-1" in flow_ids
        assert "flow-2" in flow_ids

    def test_restore_delegated_flows_returns_0_when_no_snapshot(self, tmp_path):
        from core.delegated_flow_entity import DelegatedFlowEntityRuntime
        store = _make_flow_store(tmp_path)
        runtime = DelegatedFlowEntityRuntime()
        count = restore_delegated_flows_from_snapshot(store=store, runtime=runtime)
        assert count == 0
        assert runtime.list_all() == []


# ---------------------------------------------------------------------------
# AN — Malformed record handling
# ---------------------------------------------------------------------------


class TestMalformedRecordHandling:
    def test_restore_sessions_skips_non_dict_records(self, tmp_path):
        from core.attached_runtime_session import AttachedRuntimeSessionRuntime
        store = _make_session_store(tmp_path)
        # Include one valid and one invalid (non-dict) entry
        snap = AttachedSessionSnapshotRecord(
            records=[_session_record_dict("dev-a"), "not-a-dict"]  # type: ignore[list-item]
        )
        store.save(snap)
        runtime = AttachedRuntimeSessionRuntime()
        count = restore_attached_sessions_from_snapshot(store=store, runtime=runtime)
        # Only the valid one is restored
        assert count == 1

    def test_restore_contracts_skips_invalid_records(self, tmp_path):
        from core.delegated_runtime_handoff_contract import DelegatedHandoffContractRuntime
        store = _make_contract_store(tmp_path)
        snap = HandoffContractSnapshotRecord(
            records=["bad_entry", _contract_record_dict("ctr-ok")]  # type: ignore[list-item]
        )
        store.save(snap)
        runtime = DelegatedHandoffContractRuntime()
        count = restore_handoff_contracts_from_snapshot(store=store, runtime=runtime)
        assert count == 1

    def test_restore_bindings_skips_invalid_records(self, tmp_path):
        from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRuntime
        store = _make_binding_store(tmp_path)
        snap = DispatchBindingSnapshotRecord(
            records=[_binding_record_dict("bind-ok"), 42]  # type: ignore[list-item]
        )
        store.save(snap)
        runtime = AndroidRuntimeDispatchBindingRuntime()
        count = restore_dispatch_bindings_from_snapshot(store=store, runtime=runtime)
        assert count == 1

    def test_restore_flows_skips_invalid_records(self, tmp_path):
        from core.delegated_flow_entity import DelegatedFlowEntityRuntime
        store = _make_flow_store(tmp_path)
        snap = DelegatedFlowSnapshotRecord(
            records=[None, _flow_entity_dict("flow-ok")]  # type: ignore[list-item]
        )
        store.save(snap)
        runtime = DelegatedFlowEntityRuntime()
        count = restore_delegated_flows_from_snapshot(store=store, runtime=runtime)
        assert count == 1


# ---------------------------------------------------------------------------
# AO — Record ordering preserved
# ---------------------------------------------------------------------------


class TestRecordOrdering:
    def test_session_snapshot_preserves_record_order(self, tmp_path):
        store = _make_session_store(tmp_path)
        device_ids = [f"dev-{i}" for i in range(10)]
        records = [_session_record_dict(did) for did in device_ids]
        save_attached_session_snapshot(records, store=store)
        loaded = load_attached_session_snapshot(store=store)
        assert loaded is not None
        loaded_ids = [r["device_id"] for r in loaded.records]
        assert loaded_ids == device_ids

    def test_binding_snapshot_preserves_record_order(self, tmp_path):
        store = _make_binding_store(tmp_path)
        binding_ids = [f"bind-{i}" for i in range(8)]
        records = [_binding_record_dict(bid) for bid in binding_ids]
        save_dispatch_binding_snapshot(records, store=store)
        loaded = load_dispatch_binding_snapshot(store=store)
        assert loaded is not None
        loaded_ids = [r["identity"]["binding_id"] for r in loaded.records]
        assert loaded_ids == binding_ids
