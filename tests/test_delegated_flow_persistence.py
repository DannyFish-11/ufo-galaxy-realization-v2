#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_delegated_flow_persistence.py
=========================================
PR-2 (post-533 dual-repo runtime unification master plan, MAIN repo side):
Durable Persistence Foundation for Session / Contract / Binding /
Flow Metadata — test suite.

Coverage groups
---------------
A  — Module sentinels are importable, non-empty strings.
B  — DurableSnapshotEnvelope: construction and defaults.
C  — DurableSnapshotEnvelope: compute_and_set_digest / verify_digest.
D  — DurableSnapshotEnvelope: to_dict / from_dict round-trip.
E  — DurableSnapshotEnvelope: verify_digest fails on tampered records.
F  — DurableSnapshotEnvelope: verify_digest fails when digest is empty string.
G  — SessionDurableStore: save → load round-trip (AttachedSessionRegistryEntry).
H  — SessionDurableStore: load returns empty list when no file.
I  — SessionDurableStore: load returns empty list when file is corrupt JSON.
J  — SessionDurableStore: load returns empty list when digest mismatch.
K  — SessionDurableStore: clear removes snapshot file.
L  — SessionDurableStore: clear is safe when no file exists.
M  — SessionDurableStore: atomic write (no partial file after successful save).
N  — ContractDurableStore: save → load round-trip (DelegatedHandoffContractRecord).
O  — ContractDurableStore: load returns empty list when no file.
P  — ContractDurableStore: load returns empty list on digest mismatch.
Q  — BindingDurableStore: save → load round-trip (AndroidRuntimeDispatchBindingRecord).
R  — BindingDurableStore: load returns empty list when no file.
S  — BindingDurableStore: load returns empty list on digest mismatch.
T  — FlowEntityDurableStore: save → load round-trip (DelegatedFlowEntity).
U  — FlowEntityDurableStore: load returns empty list when no file.
V  — FlowEntityDurableStore: load returns empty list on digest mismatch.
W  — Singleton: get_session_durable_store returns same instance.
X  — Singleton: reset_session_durable_store resets singleton.
Y  — Singleton: get_contract_durable_store / reset_contract_durable_store.
Z  — Singleton: get_binding_durable_store / reset_binding_durable_store.
AA — Singleton: get_flow_entity_durable_store / reset_flow_entity_durable_store.
AB — Singleton: get_delegated_flow_persistence_bundle / reset.
AC — Convenience: persist_session_snapshot / restore_sessions round-trip.
AD — Convenience: persist_contract_snapshot / restore_contracts round-trip.
AE — Convenience: persist_binding_snapshot / restore_bindings round-trip.
AF — Convenience: persist_flow_entity_snapshot / restore_flow_entities round-trip.
AG — DelegatedFlowPersistenceBundle: persist_all writes all four stores.
AH — DelegatedFlowPersistenceBundle: restore_all reads all four stores.
AI — DelegatedFlowPersistenceBundle: restore_all returns empty lists when no files.
AJ — Policy sentinel strings are present and non-empty.
AK — SessionDurableStore: malformed record in snapshot is skipped gracefully.
AL — FlowEntityDurableStore: multiple entities with different flow_ids round-trip.
AM — ContractDurableStore: only pending contracts are preserved across round-trip.
AN — BindingDurableStore: store_path property returns correct path.
AO — DurableSnapshotEnvelope: schema_kind is preserved in round-trip.
AP — DelegatedFlowPersistenceBundle.persist_all returns dict with all four keys.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List

import pytest

from core.delegated_flow_persistence import (
    # Sentinels
    DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY,
    DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL,
    SESSION_DURABLE_STORE_AUTHORITY,
    CONTRACT_DURABLE_STORE_AUTHORITY,
    BINDING_DURABLE_STORE_AUTHORITY,
    FLOW_ENTITY_DURABLE_STORE_AUTHORITY,
    RING_BUFFER_IS_RUNTIME_VIEW_POLICY,
    DURABLE_STORE_ATOMIC_WRITE_POLICY,
    DURABLE_STORE_INTEGRITY_CHECK_POLICY,
    # Data class
    DurableSnapshotEnvelope,
    # Stores
    SessionDurableStore,
    ContractDurableStore,
    BindingDurableStore,
    FlowEntityDurableStore,
    # Bundle
    DelegatedFlowPersistenceBundle,
    # Convenience
    persist_session_snapshot,
    restore_sessions,
    persist_contract_snapshot,
    restore_contracts,
    persist_binding_snapshot,
    restore_bindings,
    persist_flow_entity_snapshot,
    restore_flow_entities,
    # Singletons
    get_session_durable_store,
    reset_session_durable_store,
    get_contract_durable_store,
    reset_contract_durable_store,
    get_binding_durable_store,
    reset_binding_durable_store,
    get_flow_entity_durable_store,
    reset_flow_entity_durable_store,
    get_delegated_flow_persistence_bundle,
    reset_delegated_flow_persistence_bundle,
)


# ---------------------------------------------------------------------------
# Helpers: fixture factories
# ---------------------------------------------------------------------------

def _make_session_store(tmp_path) -> SessionDurableStore:
    return SessionDurableStore(
        store_path=os.path.join(str(tmp_path), "session.json")
    )


def _make_contract_store(tmp_path) -> ContractDurableStore:
    return ContractDurableStore(
        store_path=os.path.join(str(tmp_path), "contract.json")
    )


def _make_binding_store(tmp_path) -> BindingDurableStore:
    return BindingDurableStore(
        store_path=os.path.join(str(tmp_path), "binding.json")
    )


def _make_flow_entity_store(tmp_path) -> FlowEntityDurableStore:
    return FlowEntityDurableStore(
        store_path=os.path.join(str(tmp_path), "flow_entity.json")
    )


# ---------------------------------------------------------------------------
# Helpers: domain object factories
# ---------------------------------------------------------------------------

def _make_session_entry(device_id: str = "dev-1"):
    from core.attached_runtime_session_registry import AttachedSessionRegistryEntry
    return AttachedSessionRegistryEntry(device_id=device_id)


def _make_contract_record(session_id: str = "sess-1"):
    from core.delegated_runtime_handoff_contract import (
        build_delegated_handoff_contract,
        seal_handoff_contract,
    )
    rec = build_delegated_handoff_contract(
        session_id=session_id,
        device_id="dev-1",
        dispatch_record_id="dr-1",
        trace_id="trace-1",
        task_body={"tool": "test_tool"},
        task_id="task-1",
        source_runtime_posture="join_runtime",
    )
    return seal_handoff_contract(rec)


def _make_binding_record(session_id: str = "sess-1"):
    from core.android_runtime_dispatch_binding import AndroidRuntimeDispatchBindingRecord
    from core.android_runtime_dispatch_binding import (
        AndroidRuntimeDispatchBindingIdentity,
        AndroidRuntimeBindingState,
    )
    identity = AndroidRuntimeDispatchBindingIdentity(
        session_id=session_id,
        device_id="dev-1",
        contract_id="ctr-1",
        tracker_id="trk-1",
        trace_id="trace-1",
    )
    return AndroidRuntimeDispatchBindingRecord(
        identity=identity,
        binding_state=AndroidRuntimeBindingState.bound,
    )


def _make_flow_entity(flow_id: str = ""):
    from core.delegated_flow_entity import create_delegated_flow_entity, DelegatedFlowEntityRuntime
    runtime = DelegatedFlowEntityRuntime()
    entity = create_delegated_flow_entity(
        session_id="sess-1",
        device_id="dev-1",
        delegated_flow_id=flow_id or None,
        runtime=runtime,
    )
    return entity


# ---------------------------------------------------------------------------
# A — Sentinel presence
# ---------------------------------------------------------------------------

def test_A_sentinels_non_empty():
    for s in [
        DELEGATED_FLOW_PERSISTENCE_IS_AUTHORITY,
        DELEGATED_FLOW_PERSISTENCE_GAP_CLOSURE_SENTINEL,
        SESSION_DURABLE_STORE_AUTHORITY,
        CONTRACT_DURABLE_STORE_AUTHORITY,
        BINDING_DURABLE_STORE_AUTHORITY,
        FLOW_ENTITY_DURABLE_STORE_AUTHORITY,
        RING_BUFFER_IS_RUNTIME_VIEW_POLICY,
        DURABLE_STORE_ATOMIC_WRITE_POLICY,
        DURABLE_STORE_INTEGRITY_CHECK_POLICY,
    ]:
        assert isinstance(s, str) and len(s) > 10, f"Sentinel too short: {s!r}"


# ---------------------------------------------------------------------------
# B — DurableSnapshotEnvelope construction
# ---------------------------------------------------------------------------

def test_B_envelope_defaults():
    env = DurableSnapshotEnvelope()
    assert env.snapshot_id.startswith("dfp_")
    assert env.schema_version == "1"
    assert env.records == []
    assert env.records_digest == ""


def test_B_envelope_with_records():
    records = [{"key": "value"}, {"num": 42}]
    env = DurableSnapshotEnvelope(schema_kind="test", records=records)
    assert env.records == records
    assert env.schema_kind == "test"


# ---------------------------------------------------------------------------
# C — DurableSnapshotEnvelope digest
# ---------------------------------------------------------------------------

def test_C_compute_and_set_digest():
    env = DurableSnapshotEnvelope(records=[{"a": 1}])
    assert env.records_digest == ""
    env.compute_and_set_digest()
    assert len(env.records_digest) == 64  # SHA-256 hex


def test_C_verify_digest_correct():
    env = DurableSnapshotEnvelope(records=[{"x": 99}])
    env.compute_and_set_digest()
    assert env.verify_digest() is True


# ---------------------------------------------------------------------------
# D — DurableSnapshotEnvelope round-trip
# ---------------------------------------------------------------------------

def test_D_envelope_round_trip():
    records = [{"foo": "bar"}]
    env = DurableSnapshotEnvelope(
        schema_kind="session",
        records=records,
    )
    env.compute_and_set_digest()
    d = env.to_dict()
    restored = DurableSnapshotEnvelope.from_dict(d)
    assert restored.snapshot_id == env.snapshot_id
    assert restored.schema_kind == "session"
    assert restored.records == records
    assert restored.records_digest == env.records_digest
    assert restored.verify_digest() is True


# ---------------------------------------------------------------------------
# E — Tampered records fail digest
# ---------------------------------------------------------------------------

def test_E_digest_fails_on_tamper():
    env = DurableSnapshotEnvelope(records=[{"a": 1}])
    env.compute_and_set_digest()
    env.records.append({"malicious": True})
    assert env.verify_digest() is False


# ---------------------------------------------------------------------------
# F — Empty digest fails verify
# ---------------------------------------------------------------------------

def test_F_empty_digest_fails_verify():
    env = DurableSnapshotEnvelope(records=[{"a": 1}])
    assert env.verify_digest() is False


# ---------------------------------------------------------------------------
# G — SessionDurableStore save → load round-trip
# ---------------------------------------------------------------------------

def test_G_session_store_round_trip(tmp_path):
    store = _make_session_store(tmp_path)
    entry = _make_session_entry("dev-42")
    ok = store.save([entry])
    assert ok is True
    _, restored = store.load()
    assert len(restored) == 1
    assert restored[0].device_id == "dev-42"


# ---------------------------------------------------------------------------
# H — SessionDurableStore returns empty list when no file
# ---------------------------------------------------------------------------

def test_H_session_store_no_file(tmp_path):
    store = _make_session_store(tmp_path)
    envelope, objects = store.load()
    assert envelope is None
    assert objects == []


# ---------------------------------------------------------------------------
# I — SessionDurableStore returns empty list on corrupt JSON
# ---------------------------------------------------------------------------

def test_I_session_store_corrupt_json(tmp_path):
    store = _make_session_store(tmp_path)
    with open(store.store_path, "w") as f:
        f.write("not valid json {{{")
    envelope, objects = store.load()
    assert envelope is None
    assert objects == []


# ---------------------------------------------------------------------------
# J — SessionDurableStore returns empty list on digest mismatch
# ---------------------------------------------------------------------------

def test_J_session_store_digest_mismatch(tmp_path):
    store = _make_session_store(tmp_path)
    entry = _make_session_entry("dev-1")
    store.save([entry])
    # Tamper with the file
    with open(store.store_path, "r") as f:
        data = json.load(f)
    data["records_digest"] = "deadbeef" * 8  # 64 chars, wrong value
    with open(store.store_path, "w") as f:
        json.dump(data, f)
    envelope, objects = store.load()
    assert envelope is not None
    assert objects == []


# ---------------------------------------------------------------------------
# K — SessionDurableStore clear removes file
# ---------------------------------------------------------------------------

def test_K_session_store_clear(tmp_path):
    store = _make_session_store(tmp_path)
    store.save([_make_session_entry()])
    assert os.path.exists(store.store_path)
    assert store.clear() is True
    assert not os.path.exists(store.store_path)


# ---------------------------------------------------------------------------
# L — SessionDurableStore clear is safe when no file
# ---------------------------------------------------------------------------

def test_L_session_store_clear_no_file(tmp_path):
    store = _make_session_store(tmp_path)
    assert store.clear() is True


# ---------------------------------------------------------------------------
# M — SessionDurableStore atomic write (no partial file after save)
# ---------------------------------------------------------------------------

def test_M_session_store_atomic_write(tmp_path):
    store = _make_session_store(tmp_path)
    entry = _make_session_entry("dev-m")
    assert store.save([entry]) is True
    # Verify no stray .tmp files exist
    tmp_files = [f for f in os.listdir(str(tmp_path)) if f.endswith(".tmp")]
    assert tmp_files == []


# ---------------------------------------------------------------------------
# N — ContractDurableStore save → load round-trip
# ---------------------------------------------------------------------------

def test_N_contract_store_round_trip(tmp_path):
    store = _make_contract_store(tmp_path)
    record = _make_contract_record("sess-n")
    ok = store.save([record])
    assert ok is True
    _, restored = store.load()
    assert len(restored) == 1
    assert restored[0].identity.session_id == "sess-n"


# ---------------------------------------------------------------------------
# O — ContractDurableStore load returns empty list when no file
# ---------------------------------------------------------------------------

def test_O_contract_store_no_file(tmp_path):
    store = _make_contract_store(tmp_path)
    envelope, objects = store.load()
    assert envelope is None
    assert objects == []


# ---------------------------------------------------------------------------
# P — ContractDurableStore load returns empty list on digest mismatch
# ---------------------------------------------------------------------------

def test_P_contract_store_digest_mismatch(tmp_path):
    store = _make_contract_store(tmp_path)
    store.save([_make_contract_record()])
    with open(store.store_path, "r") as f:
        data = json.load(f)
    data["records_digest"] = "0" * 64
    with open(store.store_path, "w") as f:
        json.dump(data, f)
    _, objects = store.load()
    assert objects == []


# ---------------------------------------------------------------------------
# Q — BindingDurableStore save → load round-trip
# ---------------------------------------------------------------------------

def test_Q_binding_store_round_trip(tmp_path):
    store = _make_binding_store(tmp_path)
    record = _make_binding_record("sess-q")
    ok = store.save([record])
    assert ok is True
    _, restored = store.load()
    assert len(restored) == 1
    assert restored[0].identity.session_id == "sess-q"


# ---------------------------------------------------------------------------
# R — BindingDurableStore load returns empty list when no file
# ---------------------------------------------------------------------------

def test_R_binding_store_no_file(tmp_path):
    store = _make_binding_store(tmp_path)
    envelope, objects = store.load()
    assert envelope is None
    assert objects == []


# ---------------------------------------------------------------------------
# S — BindingDurableStore load returns empty list on digest mismatch
# ---------------------------------------------------------------------------

def test_S_binding_store_digest_mismatch(tmp_path):
    store = _make_binding_store(tmp_path)
    store.save([_make_binding_record()])
    with open(store.store_path, "r") as f:
        data = json.load(f)
    data["records_digest"] = "a" * 64
    with open(store.store_path, "w") as f:
        json.dump(data, f)
    _, objects = store.load()
    assert objects == []


# ---------------------------------------------------------------------------
# T — FlowEntityDurableStore save → load round-trip
# ---------------------------------------------------------------------------

def test_T_flow_entity_store_round_trip(tmp_path):
    store = _make_flow_entity_store(tmp_path)
    entity = _make_flow_entity()
    ok = store.save([entity])
    assert ok is True
    _, restored = store.load()
    assert len(restored) == 1
    assert restored[0].delegated_flow_id == entity.delegated_flow_id


# ---------------------------------------------------------------------------
# U — FlowEntityDurableStore load returns empty list when no file
# ---------------------------------------------------------------------------

def test_U_flow_entity_store_no_file(tmp_path):
    store = _make_flow_entity_store(tmp_path)
    envelope, objects = store.load()
    assert envelope is None
    assert objects == []


# ---------------------------------------------------------------------------
# V — FlowEntityDurableStore load returns empty list on digest mismatch
# ---------------------------------------------------------------------------

def test_V_flow_entity_store_digest_mismatch(tmp_path):
    store = _make_flow_entity_store(tmp_path)
    store.save([_make_flow_entity()])
    with open(store.store_path, "r") as f:
        data = json.load(f)
    data["records_digest"] = "b" * 64
    with open(store.store_path, "w") as f:
        json.dump(data, f)
    _, objects = store.load()
    assert objects == []


# ---------------------------------------------------------------------------
# W — get_session_durable_store returns same singleton
# ---------------------------------------------------------------------------

def test_W_session_singleton(tmp_path):
    reset_session_durable_store()
    s1 = get_session_durable_store()
    s2 = get_session_durable_store()
    assert s1 is s2
    reset_session_durable_store()


# ---------------------------------------------------------------------------
# X — reset_session_durable_store resets singleton
# ---------------------------------------------------------------------------

def test_X_session_singleton_reset():
    reset_session_durable_store()
    s1 = get_session_durable_store()
    reset_session_durable_store()
    s2 = get_session_durable_store()
    assert s1 is not s2
    reset_session_durable_store()


# ---------------------------------------------------------------------------
# Y — ContractDurableStore singleton
# ---------------------------------------------------------------------------

def test_Y_contract_singleton():
    reset_contract_durable_store()
    c1 = get_contract_durable_store()
    c2 = get_contract_durable_store()
    assert c1 is c2
    reset_contract_durable_store()
    c3 = get_contract_durable_store()
    assert c1 is not c3
    reset_contract_durable_store()


# ---------------------------------------------------------------------------
# Z — BindingDurableStore singleton
# ---------------------------------------------------------------------------

def test_Z_binding_singleton():
    reset_binding_durable_store()
    b1 = get_binding_durable_store()
    b2 = get_binding_durable_store()
    assert b1 is b2
    reset_binding_durable_store()
    b3 = get_binding_durable_store()
    assert b1 is not b3
    reset_binding_durable_store()


# ---------------------------------------------------------------------------
# AA — FlowEntityDurableStore singleton
# ---------------------------------------------------------------------------

def test_AA_flow_entity_singleton():
    reset_flow_entity_durable_store()
    f1 = get_flow_entity_durable_store()
    f2 = get_flow_entity_durable_store()
    assert f1 is f2
    reset_flow_entity_durable_store()
    f3 = get_flow_entity_durable_store()
    assert f1 is not f3
    reset_flow_entity_durable_store()


# ---------------------------------------------------------------------------
# AB — DelegatedFlowPersistenceBundle singleton
# ---------------------------------------------------------------------------

def test_AB_bundle_singleton():
    reset_delegated_flow_persistence_bundle()
    b1 = get_delegated_flow_persistence_bundle()
    b2 = get_delegated_flow_persistence_bundle()
    assert b1 is b2
    reset_delegated_flow_persistence_bundle()
    b3 = get_delegated_flow_persistence_bundle()
    assert b1 is not b3
    reset_delegated_flow_persistence_bundle()


# ---------------------------------------------------------------------------
# AC — persist_session_snapshot / restore_sessions round-trip
# ---------------------------------------------------------------------------

def test_AC_persist_restore_sessions(tmp_path):
    store = _make_session_store(tmp_path)
    entry = _make_session_entry("dev-ac")
    ok = persist_session_snapshot([entry], store=store)
    assert ok is True
    restored = restore_sessions(store=store)
    assert len(restored) == 1
    assert restored[0].device_id == "dev-ac"


# ---------------------------------------------------------------------------
# AD — persist_contract_snapshot / restore_contracts round-trip
# ---------------------------------------------------------------------------

def test_AD_persist_restore_contracts(tmp_path):
    store = _make_contract_store(tmp_path)
    record = _make_contract_record("sess-ad")
    ok = persist_contract_snapshot([record], store=store)
    assert ok is True
    restored = restore_contracts(store=store)
    assert len(restored) == 1
    assert restored[0].identity.session_id == "sess-ad"


# ---------------------------------------------------------------------------
# AE — persist_binding_snapshot / restore_bindings round-trip
# ---------------------------------------------------------------------------

def test_AE_persist_restore_bindings(tmp_path):
    store = _make_binding_store(tmp_path)
    record = _make_binding_record("sess-ae")
    ok = persist_binding_snapshot([record], store=store)
    assert ok is True
    restored = restore_bindings(store=store)
    assert len(restored) == 1
    assert restored[0].identity.session_id == "sess-ae"


# ---------------------------------------------------------------------------
# AF — persist_flow_entity_snapshot / restore_flow_entities round-trip
# ---------------------------------------------------------------------------

def test_AF_persist_restore_flow_entities(tmp_path):
    store = _make_flow_entity_store(tmp_path)
    entity = _make_flow_entity()
    ok = persist_flow_entity_snapshot([entity], store=store)
    assert ok is True
    restored = restore_flow_entities(store=store)
    assert len(restored) == 1
    assert restored[0].delegated_flow_id == entity.delegated_flow_id


# ---------------------------------------------------------------------------
# AG — DelegatedFlowPersistenceBundle.persist_all writes all four stores
# ---------------------------------------------------------------------------

def test_AG_bundle_persist_all(tmp_path):
    bundle = DelegatedFlowPersistenceBundle(
        session_store=_make_session_store(tmp_path),
        contract_store=_make_contract_store(tmp_path),
        binding_store=_make_binding_store(tmp_path),
        flow_entity_store=_make_flow_entity_store(tmp_path),
    )
    results = bundle.persist_all(
        sessions=[_make_session_entry()],
        contracts=[_make_contract_record()],
        bindings=[_make_binding_record()],
        flow_entities=[_make_flow_entity()],
    )
    assert results == {
        "session": True,
        "contract": True,
        "binding": True,
        "flow_entity": True,
    }


# ---------------------------------------------------------------------------
# AH — DelegatedFlowPersistenceBundle.restore_all reads all four stores
# ---------------------------------------------------------------------------

def test_AH_bundle_restore_all(tmp_path):
    bundle = DelegatedFlowPersistenceBundle(
        session_store=_make_session_store(tmp_path),
        contract_store=_make_contract_store(tmp_path),
        binding_store=_make_binding_store(tmp_path),
        flow_entity_store=_make_flow_entity_store(tmp_path),
    )
    bundle.persist_all(
        sessions=[_make_session_entry("dev-ah")],
        contracts=[_make_contract_record("sess-ah")],
        bindings=[_make_binding_record("sess-ah")],
        flow_entities=[_make_flow_entity()],
    )
    restored = bundle.restore_all()
    assert len(restored["session"]) == 1
    assert restored["session"][0].device_id == "dev-ah"
    assert len(restored["contract"]) == 1
    assert restored["contract"][0].identity.session_id == "sess-ah"
    assert len(restored["binding"]) == 1
    assert restored["binding"][0].identity.session_id == "sess-ah"
    assert len(restored["flow_entity"]) == 1


# ---------------------------------------------------------------------------
# AI — DelegatedFlowPersistenceBundle.restore_all returns empty lists when no files
# ---------------------------------------------------------------------------

def test_AI_bundle_restore_all_empty(tmp_path):
    bundle = DelegatedFlowPersistenceBundle(
        session_store=_make_session_store(tmp_path),
        contract_store=_make_contract_store(tmp_path),
        binding_store=_make_binding_store(tmp_path),
        flow_entity_store=_make_flow_entity_store(tmp_path),
    )
    restored = bundle.restore_all()
    assert restored == {
        "session": [],
        "contract": [],
        "binding": [],
        "flow_entity": [],
    }


# ---------------------------------------------------------------------------
# AJ — Policy sentinel strings
# ---------------------------------------------------------------------------

def test_AJ_policy_sentinels():
    assert "RING_BUFFER_IS_RUNTIME_VIEW" in RING_BUFFER_IS_RUNTIME_VIEW_POLICY
    assert "ATOMIC_WRITE" in DURABLE_STORE_ATOMIC_WRITE_POLICY
    assert "INTEGRITY_CHECK" in DURABLE_STORE_INTEGRITY_CHECK_POLICY


# ---------------------------------------------------------------------------
# AK — Malformed record is skipped gracefully
# ---------------------------------------------------------------------------

def test_AK_session_store_malformed_record_skipped(tmp_path):
    store = _make_session_store(tmp_path)
    # Write a snapshot with one valid and one invalid record
    entry = _make_session_entry("dev-ak")
    store.save([entry])
    with open(store.store_path, "r") as f:
        data = json.load(f)
    # Append a malformed record (not a dict)
    data["records"].append("not-a-dict")
    # Recompute digest
    from core.delegated_flow_persistence import DurableSnapshotEnvelope
    env = DurableSnapshotEnvelope.from_dict(data)
    env.compute_and_set_digest()
    with open(store.store_path, "w") as f:
        json.dump(env.to_dict(), f)
    _, objects = store.load()
    # The valid entry should still be restored (the invalid one skipped)
    assert len(objects) == 1
    assert objects[0].device_id == "dev-ak"


# ---------------------------------------------------------------------------
# AL — Multiple flow entities round-trip
# ---------------------------------------------------------------------------

def test_AL_flow_entity_multiple_round_trip(tmp_path):
    store = _make_flow_entity_store(tmp_path)
    e1 = _make_flow_entity()
    e2 = _make_flow_entity()
    store.save([e1, e2])
    _, restored = store.load()
    assert len(restored) == 2
    ids = {r.delegated_flow_id for r in restored}
    assert e1.delegated_flow_id in ids
    assert e2.delegated_flow_id in ids


# ---------------------------------------------------------------------------
# AM — Contract round-trip preserves sealed status
# ---------------------------------------------------------------------------

def test_AM_contract_sealed_status_preserved(tmp_path):
    store = _make_contract_store(tmp_path)
    record = _make_contract_record("sess-am")
    from core.delegated_runtime_handoff_contract import HandoffContractStatus
    assert record.status == HandoffContractStatus.sealed
    store.save([record])
    _, restored = store.load()
    assert len(restored) == 1
    assert restored[0].status == HandoffContractStatus.sealed


# ---------------------------------------------------------------------------
# AN — BindingDurableStore.store_path returns correct path
# ---------------------------------------------------------------------------

def test_AN_binding_store_path(tmp_path):
    path = os.path.join(str(tmp_path), "binding_test.json")
    store = BindingDurableStore(store_path=path)
    assert store.store_path == path


# ---------------------------------------------------------------------------
# AO — DurableSnapshotEnvelope schema_kind preserved in round-trip
# ---------------------------------------------------------------------------

def test_AO_envelope_schema_kind_round_trip():
    env = DurableSnapshotEnvelope(schema_kind="flow_entity")
    env.compute_and_set_digest()
    restored = DurableSnapshotEnvelope.from_dict(env.to_dict())
    assert restored.schema_kind == "flow_entity"


# ---------------------------------------------------------------------------
# AP — DelegatedFlowPersistenceBundle.persist_all returns dict with four keys
# ---------------------------------------------------------------------------

def test_AP_bundle_persist_all_keys(tmp_path):
    bundle = DelegatedFlowPersistenceBundle(
        session_store=_make_session_store(tmp_path),
        contract_store=_make_contract_store(tmp_path),
        binding_store=_make_binding_store(tmp_path),
        flow_entity_store=_make_flow_entity_store(tmp_path),
    )
    results = bundle.persist_all(
        sessions=[],
        contracts=[],
        bindings=[],
        flow_entities=[],
    )
    assert set(results.keys()) == {"session", "contract", "binding", "flow_entity"}
    for v in results.values():
        assert v is True
