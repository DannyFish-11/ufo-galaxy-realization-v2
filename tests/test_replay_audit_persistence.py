#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_replay_audit_persistence.py
=======================================
PR-B2: Canonical Truth / Replay / Conflict Audit Durability — test suite.

Coverage
--------
A  — Module sentinels are importable and non-empty strings.
B  — AuditRecordKind enum has all expected values.
C  — ReplayAuditRecord: construction with defaults.
D  — ReplayAuditRecord: to_dict / from_dict round-trip.
E  — ReplayAuditRecord: audit_id is auto-generated and unique per instance.
F  — ConflictAuditRecord: construction with defaults.
G  — ConflictAuditRecord: to_dict / from_dict round-trip.
H  — ConflictAuditRecord.from_authority_conflict_entry: dataclass-like object.
I  — ConflictAuditRecord.from_authority_conflict_entry: dict input.
J  — ConflictAuditRecord: is_resolved=True → to_dict shows resolved.
K  — DurableAuditStore: append single record succeeds.
L  — DurableAuditStore: load_all returns appended records in order.
M  — DurableAuditStore: load_all returns empty list when no file.
N  — DurableAuditStore: load_all with kind_filter returns only matching records.
O  — DurableAuditStore: count returns correct record count.
P  — DurableAuditStore: count with kind_filter returns filtered count.
Q  — DurableAuditStore: clear removes the JSONL file.
R  — DurableAuditStore: clear is safe when no file exists.
S  — DurableAuditStore: append multiple records; all retrievable.
T  — DurableAuditStore: load_all tolerates malformed lines (skips them).
U  — DurableAuditStore: store_path property returns correct path.
V  — get_replay_audit_store: returns singleton.
W  — reset_replay_audit_store: resets singleton.
X  — append_replay_audit_record helper: appends to default store.
Y  — append_conflict_audit_record helper: appends resolved conflict.
Z  — append_conflict_audit_record helper: appends unresolved conflict.
AA — load_audit_records helper: returns all records from default store.
AB — load_audit_records helper: kind_filter works.
AC — ReplayFoundation.set_audit_store: attaches store.
AD — ReplayFoundation: record_execution writes to durable store when attached.
AE — ReplayFoundation: emit_event writes to durable store when attached.
AF — ReplayFoundation: record_route writes to durable store when attached.
AG — ReplayFoundation: record_fallback writes to durable store when attached.
AH — ReplayFoundation: record_retry writes to durable store when attached.
AI — ReplayFoundation: no durable write when no store is attached.
AJ — REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL is importable and non-empty.
AK — CanonicalSessionTruthRuntime.set_audit_store: attaches store.
AL — CanonicalSessionTruthRuntime.record: writes to durable store when attached.
AM — CanonicalSessionTruthRuntime: no durable write when no store is attached.
AN — CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL is importable and non-empty.
AO — persist_conflict_artifacts: persists all conflict records to store.
AP — persist_conflict_artifacts: uses detect_parallel_truth_paths when conflicts=None.
AQ — persist_conflict_artifacts: returns count of persisted records.
AR — persist_conflict_artifacts: CONFLICT_ARTIFACTS_PERSISTED_POLICY is a non-empty string.
AS — DurableAuditStore: records written from different sessions are readable.
AT — DurableAuditStore: empty directory is created if it does not exist.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import pytest

from core.replay_audit_persistence import (
    REPLAY_AUDIT_PERSISTENCE_AUTHORITY,
    REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL,
    AUDIT_STORE_IS_OBSERVATIONAL_POLICY,
    CONFLICT_ARTIFACTS_DURABLE_POLICY,
    AuditRecordKind,
    ReplayAuditRecord,
    ConflictAuditRecord,
    DurableAuditStore,
    append_replay_audit_record,
    append_conflict_audit_record,
    load_audit_records,
    get_replay_audit_store,
    reset_replay_audit_store,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_path: str) -> DurableAuditStore:
    return DurableAuditStore(
        store_path=os.path.join(tmp_path, "audit.jsonl")
    )


@dataclass
class _FakeConflictEntry:
    """Minimal stand-in for AuthorityConflictEntry."""
    conflict_id: str = "CONFLICT-TEST"
    runtime_fact: str = "test fact"
    layer_a: str = "layer_a"
    layer_b: str = "layer_b"
    description: str = "test description"
    is_resolved: bool = False
    resolution_note: str = ""


# ---------------------------------------------------------------------------
# A — Sentinels
# ---------------------------------------------------------------------------

class TestA_Sentinels:
    def test_A01_authority_non_empty(self):
        assert isinstance(REPLAY_AUDIT_PERSISTENCE_AUTHORITY, str)
        assert len(REPLAY_AUDIT_PERSISTENCE_AUTHORITY) > 0

    def test_A02_durability_sentinel_non_empty(self):
        assert isinstance(REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL, str)
        assert len(REPLAY_AUDIT_PERSISTENCE_DURABILITY_SENTINEL) > 0

    def test_A03_observational_policy_non_empty(self):
        assert isinstance(AUDIT_STORE_IS_OBSERVATIONAL_POLICY, str)
        assert len(AUDIT_STORE_IS_OBSERVATIONAL_POLICY) > 0

    def test_A04_conflict_durable_policy_non_empty(self):
        assert isinstance(CONFLICT_ARTIFACTS_DURABLE_POLICY, str)
        assert len(CONFLICT_ARTIFACTS_DURABLE_POLICY) > 0


# ---------------------------------------------------------------------------
# B — AuditRecordKind
# ---------------------------------------------------------------------------

class TestB_AuditRecordKind:
    def test_B01_task_execution(self):
        assert AuditRecordKind.TASK_EXECUTION.value == "task_execution"

    def test_B02_runtime_event(self):
        assert AuditRecordKind.RUNTIME_EVENT.value == "runtime_event"

    def test_B03_route_decision(self):
        assert AuditRecordKind.ROUTE_DECISION.value == "route_decision"

    def test_B04_fallback(self):
        assert AuditRecordKind.FALLBACK.value == "fallback"

    def test_B05_retry(self):
        assert AuditRecordKind.RETRY.value == "retry"

    def test_B06_canonical_truth_merge(self):
        assert AuditRecordKind.CANONICAL_TRUTH_MERGE.value == "canonical_truth_merge"

    def test_B07_conflict_detected(self):
        assert AuditRecordKind.CONFLICT_DETECTED.value == "conflict_detected"

    def test_B08_conflict_resolved(self):
        assert AuditRecordKind.CONFLICT_RESOLVED.value == "conflict_resolved"


# ---------------------------------------------------------------------------
# C/D/E — ReplayAuditRecord
# ---------------------------------------------------------------------------

class TestCDE_ReplayAuditRecord:
    def test_C01_default_construction(self):
        r = ReplayAuditRecord()
        assert r.audit_id.startswith("aud_")
        assert r.kind == AuditRecordKind.RUNTIME_EVENT.value
        assert isinstance(r.recorded_at, float)
        assert isinstance(r.payload, dict)
        assert isinstance(r.process_pid, int)

    def test_D01_to_dict_from_dict_round_trip(self):
        r = ReplayAuditRecord(
            kind=AuditRecordKind.TASK_EXECUTION.value,
            payload={"task_id": "t1", "success": True},
        )
        d = r.to_dict()
        r2 = ReplayAuditRecord.from_dict(d)
        assert r2.audit_id == r.audit_id
        assert r2.kind == r.kind
        assert r2.payload == r.payload
        assert r2.process_pid == r.process_pid

    def test_D02_from_dict_missing_fields_use_defaults(self):
        r = ReplayAuditRecord.from_dict({})
        assert r.audit_id.startswith("aud_")
        assert isinstance(r.recorded_at, float)

    def test_E01_audit_id_unique_per_instance(self):
        r1 = ReplayAuditRecord()
        r2 = ReplayAuditRecord()
        assert r1.audit_id != r2.audit_id


# ---------------------------------------------------------------------------
# F/G/H/I/J — ConflictAuditRecord
# ---------------------------------------------------------------------------

class TestFGHIJ_ConflictAuditRecord:
    def test_F01_default_construction(self):
        c = ConflictAuditRecord()
        assert c.conflict_id == ""
        assert c.is_resolved is False
        assert isinstance(c.detected_at, float)

    def test_G01_to_dict_from_dict_round_trip(self):
        c = ConflictAuditRecord(
            conflict_id="CONFLICT-001",
            runtime_fact="task routing",
            layer_a="LayerA",
            layer_b="LayerB",
            description="desc",
            is_resolved=True,
            resolution_note="resolved via PR-x",
            audit_run_id="run-123",
        )
        d = c.to_dict()
        c2 = ConflictAuditRecord.from_dict(d)
        assert c2.conflict_id == "CONFLICT-001"
        assert c2.is_resolved is True
        assert c2.resolution_note == "resolved via PR-x"
        assert c2.audit_run_id == "run-123"

    def test_H01_from_authority_conflict_entry_dataclass(self):
        entry = _FakeConflictEntry(conflict_id="CONFLICT-X", is_resolved=False)
        c = ConflictAuditRecord.from_authority_conflict_entry(entry, audit_run_id="run-1")
        assert c.conflict_id == "CONFLICT-X"
        assert c.is_resolved is False
        assert c.audit_run_id == "run-1"
        assert c.layer_a == "layer_a"

    def test_I01_from_authority_conflict_entry_dict(self):
        d = {
            "conflict_id": "CONFLICT-Y",
            "runtime_fact": "fact y",
            "layer_a": "la",
            "layer_b": "lb",
            "description": "desc y",
            "is_resolved": True,
            "resolution_note": "note y",
        }
        c = ConflictAuditRecord.from_authority_conflict_entry(d, audit_run_id="run-2")
        assert c.conflict_id == "CONFLICT-Y"
        assert c.is_resolved is True
        assert c.audit_run_id == "run-2"

    def test_J01_resolved_conflict_in_dict(self):
        c = ConflictAuditRecord(conflict_id="C1", is_resolved=True, resolution_note="done")
        d = c.to_dict()
        assert d["is_resolved"] is True
        assert d["resolution_note"] == "done"


# ---------------------------------------------------------------------------
# K–U — DurableAuditStore
# ---------------------------------------------------------------------------

class TestKU_DurableAuditStore:
    def test_K01_append_single_record(self, tmp_path):
        store = _make_store(str(tmp_path))
        r = ReplayAuditRecord(kind=AuditRecordKind.TASK_EXECUTION.value, payload={"t": "1"})
        ok = store.append(r)
        assert ok is True
        assert os.path.exists(store.store_path)

    def test_L01_load_all_returns_records_in_order(self, tmp_path):
        store = _make_store(str(tmp_path))
        for i in range(3):
            store.append(ReplayAuditRecord(
                kind=AuditRecordKind.RUNTIME_EVENT.value,
                payload={"i": i},
            ))
        records = store.load_all()
        assert len(records) == 3
        assert [r.payload["i"] for r in records] == [0, 1, 2]

    def test_M01_load_all_empty_when_no_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        assert store.load_all() == []

    def test_N01_kind_filter_returns_only_matching(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.TASK_EXECUTION.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.RUNTIME_EVENT.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.TASK_EXECUTION.value))
        results = store.load_all(kind_filter=AuditRecordKind.TASK_EXECUTION.value)
        assert len(results) == 2
        assert all(r.kind == AuditRecordKind.TASK_EXECUTION.value for r in results)

    def test_O01_count_correct(self, tmp_path):
        store = _make_store(str(tmp_path))
        for _ in range(5):
            store.append(ReplayAuditRecord())
        assert store.count() == 5

    def test_P01_count_kind_filter(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.CONFLICT_DETECTED.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.CONFLICT_RESOLVED.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.CONFLICT_DETECTED.value))
        assert store.count(kind_filter=AuditRecordKind.CONFLICT_DETECTED.value) == 2
        assert store.count(kind_filter=AuditRecordKind.CONFLICT_RESOLVED.value) == 1

    def test_Q01_clear_removes_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.append(ReplayAuditRecord())
        assert os.path.exists(store.store_path)
        ok = store.clear()
        assert ok is True
        assert not os.path.exists(store.store_path)

    def test_R01_clear_safe_when_no_file(self, tmp_path):
        store = _make_store(str(tmp_path))
        ok = store.clear()
        assert ok is True

    def test_S01_append_many_all_retrievable(self, tmp_path):
        store = _make_store(str(tmp_path))
        for i in range(20):
            store.append(ReplayAuditRecord(payload={"idx": i}))
        records = store.load_all()
        assert len(records) == 20

    def test_T01_malformed_lines_skipped(self, tmp_path):
        store = _make_store(str(tmp_path))
        # Write a good record, then a malformed line, then another good record
        store.append(ReplayAuditRecord(payload={"good": 1}))
        with open(store.store_path, "a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        store.append(ReplayAuditRecord(payload={"good": 2}))
        records = store.load_all()
        # Only the two valid records should be returned
        assert len(records) == 2
        assert records[0].payload["good"] == 1
        assert records[1].payload["good"] == 2

    def test_U01_store_path_property(self, tmp_path):
        path = os.path.join(str(tmp_path), "test.jsonl")
        store = DurableAuditStore(store_path=path)
        assert store.store_path == path


# ---------------------------------------------------------------------------
# V/W — Singleton management
# ---------------------------------------------------------------------------

class TestVW_Singleton:
    def setup_method(self):
        reset_replay_audit_store()

    def teardown_method(self):
        reset_replay_audit_store()

    def test_V01_get_replay_audit_store_returns_singleton(self):
        s1 = get_replay_audit_store()
        s2 = get_replay_audit_store()
        assert s1 is s2

    def test_W01_reset_creates_new_instance(self):
        s1 = get_replay_audit_store()
        reset_replay_audit_store()
        s2 = get_replay_audit_store()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# X/Y/Z/AA/AB — Convenience helpers
# ---------------------------------------------------------------------------

class TestXYZAAB_Helpers:
    def test_X01_append_replay_audit_record_helper(self, tmp_path):
        store = _make_store(str(tmp_path))
        ok = append_replay_audit_record(
            {"task_id": "t1"}, AuditRecordKind.TASK_EXECUTION.value, store=store
        )
        assert ok is True
        records = store.load_all()
        assert len(records) == 1
        assert records[0].kind == AuditRecordKind.TASK_EXECUTION.value
        assert records[0].payload["task_id"] == "t1"

    def test_Y01_append_conflict_audit_resolved(self, tmp_path):
        store = _make_store(str(tmp_path))
        entry = _FakeConflictEntry(conflict_id="C-RES", is_resolved=True)
        ok = append_conflict_audit_record(entry, store=store)
        assert ok is True
        records = store.load_all(kind_filter=AuditRecordKind.CONFLICT_RESOLVED.value)
        assert len(records) == 1
        assert records[0].payload["conflict_id"] == "C-RES"

    def test_Z01_append_conflict_audit_unresolved(self, tmp_path):
        store = _make_store(str(tmp_path))
        entry = _FakeConflictEntry(conflict_id="C-OPEN", is_resolved=False)
        ok = append_conflict_audit_record(entry, store=store)
        assert ok is True
        records = store.load_all(kind_filter=AuditRecordKind.CONFLICT_DETECTED.value)
        assert len(records) == 1
        assert records[0].payload["conflict_id"] == "C-OPEN"
        assert records[0].payload["is_resolved"] is False

    def test_AA01_load_audit_records_all(self, tmp_path):
        store = _make_store(str(tmp_path))
        for i in range(4):
            store.append(ReplayAuditRecord(payload={"n": i}))
        records = load_audit_records(store=store)
        assert len(records) == 4

    def test_AB01_load_audit_records_kind_filter(self, tmp_path):
        store = _make_store(str(tmp_path))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.FALLBACK.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.RETRY.value))
        store.append(ReplayAuditRecord(kind=AuditRecordKind.FALLBACK.value))
        results = load_audit_records(
            store=store, kind_filter=AuditRecordKind.FALLBACK.value
        )
        assert len(results) == 2


# ---------------------------------------------------------------------------
# AC–AJ — ReplayFoundation durable audit sink
# ---------------------------------------------------------------------------

class TestACJ_ReplayFoundationDurableAudit:
    def test_AJ01_sentinel_importable(self):
        from core.replay_foundation import REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL
        assert isinstance(REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL, str)
        assert len(REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL) > 0

    def test_AC01_set_audit_store_attaches(self, tmp_path):
        from core.replay_foundation import ReplayFoundation
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        assert f._audit_store is store

    def test_AD01_record_execution_writes_to_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, TaskExecutionRecord
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        rec = TaskExecutionRecord(task_id="t-exec", goal="do something")
        f.record_execution(rec)
        records = store.load_all(kind_filter=AuditRecordKind.TASK_EXECUTION.value)
        assert len(records) == 1
        assert records[0].payload["task_id"] == "t-exec"

    def test_AE01_emit_event_writes_to_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, RuntimeEventRecord, ReplayEventKind
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        evt = RuntimeEventRecord(kind=ReplayEventKind.TASK_COMPLETED.value, task_id="t-ev")
        f.emit_event(evt)
        records = store.load_all(kind_filter=AuditRecordKind.RUNTIME_EVENT.value)
        assert len(records) == 1
        assert records[0].payload["task_id"] == "t-ev"

    def test_AF01_record_route_writes_to_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, RouteDecisionRecord
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        route = RouteDecisionRecord(task_id="t-route", selected_targets=["device-1"])
        f.record_route(route)
        records = store.load_all(kind_filter=AuditRecordKind.ROUTE_DECISION.value)
        assert len(records) == 1
        assert records[0].payload["task_id"] == "t-route"

    def test_AG01_record_fallback_writes_to_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, ReplayFallbackRecord
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        fb = ReplayFallbackRecord(primary_task_id="t-fb", fallback_task_id="t-fb2")
        f.record_fallback(fb)
        records = store.load_all(kind_filter=AuditRecordKind.FALLBACK.value)
        assert len(records) == 1
        assert records[0].payload["primary_task_id"] == "t-fb"

    def test_AH01_record_retry_writes_to_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, ReplayRetryRecord
        store = _make_store(str(tmp_path))
        f = ReplayFoundation()
        f.set_audit_store(store)
        retry = ReplayRetryRecord(original_task_id="t-orig", retry_task_id="t-retry")
        f.record_retry(retry)
        records = store.load_all(kind_filter=AuditRecordKind.RETRY.value)
        assert len(records) == 1
        assert records[0].payload["original_task_id"] == "t-orig"

    def test_AI01_no_durable_write_without_store(self, tmp_path):
        from core.replay_foundation import ReplayFoundation, TaskExecutionRecord
        f = ReplayFoundation()
        # No store attached — should not raise
        rec = TaskExecutionRecord(task_id="t-no-store")
        f.record_execution(rec)  # Must not raise
        # Confirm in-memory still works
        result = f.get_execution_record("t-no-store")
        assert result is not None
        assert result.task_id == "t-no-store"


# ---------------------------------------------------------------------------
# AK–AN — CanonicalSessionTruthRuntime durable audit sink
# ---------------------------------------------------------------------------

class TestAKAN_CanonicalSessionTruthRuntimeDurableAudit:
    def setup_method(self):
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        reset_canonical_session_truth_runtime()

    def teardown_method(self):
        from core.canonical_session_truth import reset_canonical_session_truth_runtime
        reset_canonical_session_truth_runtime()

    def test_AN01_sentinel_importable(self):
        from core.canonical_session_truth import CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL
        assert isinstance(CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL, str)
        assert len(CANONICAL_TRUTH_DURABLE_AUDIT_SENTINEL) > 0

    def test_AK01_set_audit_store_attaches(self, tmp_path):
        from core.canonical_session_truth import CanonicalSessionTruthRuntime
        store = _make_store(str(tmp_path))
        rt = CanonicalSessionTruthRuntime()
        rt.set_audit_store(store)
        assert rt._audit_store is store

    def test_AL01_record_writes_to_durable_store(self, tmp_path):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        store = _make_store(str(tmp_path))
        rt = CanonicalSessionTruthRuntime()
        rt.set_audit_store(store)
        rec = CanonicalSessionTruthRecord(
            session_id="sess-1",
            task_id="t-truth",
            merge_success=True,
            truth_source="local",
        )
        rt.record(rec)
        records = store.load_all(kind_filter=AuditRecordKind.CANONICAL_TRUTH_MERGE.value)
        assert len(records) == 1
        assert records[0].payload["session_id"] == "sess-1"
        assert records[0].payload["merge_success"] is True

    def test_AL02_record_multiple_truth_decisions(self, tmp_path):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        store = _make_store(str(tmp_path))
        rt = CanonicalSessionTruthRuntime()
        rt.set_audit_store(store)
        for i in range(5):
            rt.record(CanonicalSessionTruthRecord(
                session_id=f"sess-{i}",
                task_id=f"t-{i}",
            ))
        records = store.load_all(kind_filter=AuditRecordKind.CANONICAL_TRUTH_MERGE.value)
        assert len(records) == 5

    def test_AM01_no_durable_write_without_store(self):
        from core.canonical_session_truth import (
            CanonicalSessionTruthRuntime,
            CanonicalSessionTruthRecord,
        )
        rt = CanonicalSessionTruthRuntime()
        # No store attached — must not raise
        rec = CanonicalSessionTruthRecord(session_id="s-no-store")
        rt.record(rec)
        snap = rt.snapshot()
        assert snap.total_records == 1


# ---------------------------------------------------------------------------
# AO–AR — persist_conflict_artifacts
# ---------------------------------------------------------------------------

class TestAOAR_PersistConflictArtifacts:
    def test_AR01_policy_sentinel_importable(self):
        from core.runtime_closure_audit import CONFLICT_ARTIFACTS_PERSISTED_POLICY
        assert isinstance(CONFLICT_ARTIFACTS_PERSISTED_POLICY, str)
        assert len(CONFLICT_ARTIFACTS_PERSISTED_POLICY) > 0

    def test_AO01_persists_all_conflict_records(self, tmp_path):
        from core.runtime_closure_audit import persist_conflict_artifacts
        store = _make_store(str(tmp_path))
        conflicts = [
            _FakeConflictEntry(conflict_id=f"C-{i}", is_resolved=(i % 2 == 0))
            for i in range(4)
        ]
        count = persist_conflict_artifacts(conflicts, store=store)
        assert count == 4
        all_records = store.load_all()
        assert len(all_records) == 4

    def test_AP01_uses_detect_when_conflicts_none(self, tmp_path):
        from core.runtime_closure_audit import persist_conflict_artifacts
        store = _make_store(str(tmp_path))
        # Pass conflicts=None to trigger detect_parallel_truth_paths()
        count = persist_conflict_artifacts(None, store=store)
        # The canonical audit has many known conflicts; just verify >0
        assert count > 0
        all_records = store.load_all()
        assert len(all_records) == count

    def test_AQ01_returns_persisted_count(self, tmp_path):
        from core.runtime_closure_audit import persist_conflict_artifacts
        store = _make_store(str(tmp_path))
        conflicts = [_FakeConflictEntry(conflict_id=f"CX-{i}") for i in range(6)]
        count = persist_conflict_artifacts(conflicts, store=store)
        assert count == 6

    def test_AO02_resolved_conflicts_use_correct_kind(self, tmp_path):
        from core.runtime_closure_audit import persist_conflict_artifacts
        store = _make_store(str(tmp_path))
        resolved = _FakeConflictEntry(conflict_id="C-DONE", is_resolved=True)
        unresolved = _FakeConflictEntry(conflict_id="C-OPEN", is_resolved=False)
        persist_conflict_artifacts([resolved, unresolved], store=store)
        resolved_records = store.load_all(kind_filter=AuditRecordKind.CONFLICT_RESOLVED.value)
        detected_records = store.load_all(kind_filter=AuditRecordKind.CONFLICT_DETECTED.value)
        assert len(resolved_records) == 1
        assert resolved_records[0].payload["conflict_id"] == "C-DONE"
        assert len(detected_records) == 1
        assert detected_records[0].payload["conflict_id"] == "C-OPEN"


# ---------------------------------------------------------------------------
# AS/AT — Additional edge cases
# ---------------------------------------------------------------------------

class TestASAT_EdgeCases:
    def test_AS01_records_readable_by_new_store_instance(self, tmp_path):
        """Records written by one store instance are readable by another."""
        path = os.path.join(str(tmp_path), "shared.jsonl")
        store1 = DurableAuditStore(store_path=path)
        store2 = DurableAuditStore(store_path=path)
        for i in range(3):
            store1.append(ReplayAuditRecord(payload={"written_by": 1, "i": i}))
        records = store2.load_all()
        assert len(records) == 3
        assert all(r.payload["written_by"] == 1 for r in records)

    def test_AT01_directory_created_if_missing(self, tmp_path):
        nested = os.path.join(str(tmp_path), "nested", "deep", "audit.jsonl")
        store = DurableAuditStore(store_path=nested)
        store.append(ReplayAuditRecord())
        assert os.path.exists(nested)
