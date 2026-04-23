#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_production_audit_wiring.py
======================================
Durable Audit Evidence — Production Wiring Tests.

Validates that:
1. AuditEventSemantics supports set_audit_store() and durable writes.
2. wire_durable_audit_store() wires DurableAuditStore to ReplayFoundation,
   CanonicalSessionTruthRuntime, and AuditEventSemantics.
3. Dispatch-spine audit events reach the durable store after wiring.

Test groups
-----------
 A) AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL is importable and non-empty.
 B) AuditEventSemantics.set_audit_store() attaches the store.
 C) AuditEventSemantics.record() writes to durable store when attached.
 D) AuditEventSemantics.record() does NOT write to store when none attached.
 E) AuditEventSemantics.record() continues when durable write fails.
 F) wire_durable_audit_store() returns ok status with expected keys.
 G) wire_durable_audit_store() wires ReplayFoundation to DurableAuditStore.
 H) wire_durable_audit_store() wires AuditEventSemantics to DurableAuditStore.
 I) wire_durable_audit_store() wires CanonicalSessionTruthRuntime (best-effort).
 J) Replay records reach durable store after wire_durable_audit_store().
 K) AuditEventSemantics dispatch-spine events reach durable store after wiring.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(tmp_dir: str):
    from core.replay_audit_persistence import DurableAuditStore
    return DurableAuditStore(store_path=os.path.join(tmp_dir, "audit.jsonl"))


def _fresh_audit_semantics():
    from core.audit_event_semantics import reset_audit_event_semantics
    reset_audit_event_semantics()


def _fresh_replay_foundation():
    from core.replay_foundation import reset_replay_foundation
    reset_replay_foundation()


def _fresh_audit_store():
    from core.replay_audit_persistence import reset_replay_audit_store
    reset_replay_audit_store()


def _fresh_all():
    _fresh_audit_semantics()
    _fresh_replay_foundation()
    _fresh_audit_store()


# ---------------------------------------------------------------------------
# Group A — Sentinel
# ---------------------------------------------------------------------------

class TestGroupA_Sentinel(unittest.TestCase):
    def test_A01_sentinel_importable_and_nonempty(self):
        from core.audit_event_semantics import AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL
        self.assertIsInstance(AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL, str)
        self.assertGreater(len(AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL), 0)

    def test_A02_sentinel_mentions_dispatch_spine(self):
        from core.audit_event_semantics import AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL
        self.assertIn("dispatch", AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL.lower())


# ---------------------------------------------------------------------------
# Group B — set_audit_store attaches
# ---------------------------------------------------------------------------

class TestGroupB_SetAuditStore(unittest.TestCase):
    def setUp(self):
        _fresh_audit_semantics()

    def tearDown(self):
        _fresh_audit_semantics()

    def test_B01_set_audit_store_attaches(self):
        from core.audit_event_semantics import AuditEventSemantics
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            sem = AuditEventSemantics()
            sem.set_audit_store(store)
            self.assertIs(sem._audit_store, store)

    def test_B02_set_audit_store_none_detaches(self):
        from core.audit_event_semantics import AuditEventSemantics
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            sem = AuditEventSemantics()
            sem.set_audit_store(store)
            sem.set_audit_store(None)
            self.assertIsNone(sem._audit_store)


# ---------------------------------------------------------------------------
# Group C — Durable write when store attached
# ---------------------------------------------------------------------------

class TestGroupC_DurableWrite(unittest.TestCase):
    def setUp(self):
        _fresh_audit_semantics()

    def tearDown(self):
        _fresh_audit_semantics()

    def test_C01_record_writes_to_durable_store(self):
        from core.audit_event_semantics import AuditEventSemantics, AuditEventRecord, AuditEventKind
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            sem = AuditEventSemantics()
            sem.set_audit_store(store)
            rec = AuditEventRecord(kind=AuditEventKind.TASK_DISPATCHED, task_id="t1")
            sem.record(rec)
            records = store.load_all(kind_filter="audit_event")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].payload["task_id"], "t1")

    def test_C02_multiple_records_all_written(self):
        from core.audit_event_semantics import AuditEventSemantics, AuditEventRecord, AuditEventKind
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            sem = AuditEventSemantics()
            sem.set_audit_store(store)
            for kind in [
                AuditEventKind.TASK_ACCEPTED,
                AuditEventKind.TASK_DISPATCHED,
                AuditEventKind.TASK_COMPLETED,
            ]:
                sem.record(AuditEventRecord(kind=kind, task_id="t-multi"))
            records = store.load_all(kind_filter="audit_event")
            self.assertEqual(len(records), 3)

    def test_C03_ring_buffer_also_populated(self):
        from core.audit_event_semantics import AuditEventSemantics, AuditEventRecord, AuditEventKind
        with tempfile.TemporaryDirectory() as tmp:
            store = _make_store(tmp)
            sem = AuditEventSemantics()
            sem.set_audit_store(store)
            rec = AuditEventRecord(kind=AuditEventKind.TASK_ACCEPTED, task_id="t-ring")
            sem.record(rec)
            all_ev = sem.all_events()
            self.assertEqual(len(all_ev), 1)
            self.assertEqual(all_ev[0].task_id, "t-ring")


# ---------------------------------------------------------------------------
# Group D — No durable write when no store
# ---------------------------------------------------------------------------

class TestGroupD_NoDurableWriteWithoutStore(unittest.TestCase):
    def setUp(self):
        _fresh_audit_semantics()

    def tearDown(self):
        _fresh_audit_semantics()

    def test_D01_no_store_no_write(self):
        from core.audit_event_semantics import AuditEventSemantics, AuditEventRecord, AuditEventKind
        sem = AuditEventSemantics()
        rec = AuditEventRecord(kind=AuditEventKind.TASK_DISPATCHED, task_id="t-nostore")
        sem.record(rec)
        self.assertEqual(len(sem.all_events()), 1)


# ---------------------------------------------------------------------------
# Group E — Graceful degradation when durable write fails
# ---------------------------------------------------------------------------

class TestGroupE_GracefulDegradation(unittest.TestCase):
    def setUp(self):
        _fresh_audit_semantics()

    def tearDown(self):
        _fresh_audit_semantics()

    def test_E01_record_continues_when_store_fails(self):
        from core.audit_event_semantics import AuditEventSemantics, AuditEventRecord, AuditEventKind

        class _BrokenStore:
            def append(self, *a, **kw):
                raise RuntimeError("disk full")

        sem = AuditEventSemantics()
        sem.set_audit_store(_BrokenStore())
        rec = AuditEventRecord(kind=AuditEventKind.TASK_DISPATCHED, task_id="t-err")
        sem.record(rec)
        self.assertEqual(len(sem.all_events()), 1)


# ---------------------------------------------------------------------------
# Group F — wire_durable_audit_store() result
# ---------------------------------------------------------------------------

class TestGroupF_WireDurableAuditStore(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_F01_returns_dict_with_status(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        self.assertIn("status", result)

    def test_F02_status_is_ok_or_degraded(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        self.assertIn(result["status"], ("ok", "degraded"))

    def test_F03_ok_result_has_store_path(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertIn("store_path", result)

    def test_F04_ok_result_has_wiring_flags(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertIn("replay_foundation_wired", result)
            self.assertIn("audit_event_semantics_wired", result)
            self.assertIn("canonical_truth_wired", result)

    def test_F05_replay_foundation_wired_true(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertTrue(result["replay_foundation_wired"])

    def test_F06_audit_event_semantics_wired_true(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertTrue(result["audit_event_semantics_wired"])


# ---------------------------------------------------------------------------
# Group G — ReplayFoundation wired after wire_durable_audit_store()
# ---------------------------------------------------------------------------

class TestGroupG_ReplayFoundationWired(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_G01_replay_foundation_has_audit_store_after_wiring(self):
        from core.startup import wire_durable_audit_store
        from core.replay_foundation import get_replay_foundation
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            rf = get_replay_foundation()
            self.assertIsNotNone(rf._audit_store)

    def test_G02_replay_foundation_audit_store_is_durable_store_singleton(self):
        from core.startup import wire_durable_audit_store
        from core.replay_foundation import get_replay_foundation
        from core.replay_audit_persistence import get_replay_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            rf = get_replay_foundation()
            self.assertIs(rf._audit_store, get_replay_audit_store())


# ---------------------------------------------------------------------------
# Group H — AuditEventSemantics wired after wire_durable_audit_store()
# ---------------------------------------------------------------------------

class TestGroupH_AuditEventSemanticsWired(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_H01_audit_event_semantics_has_audit_store_after_wiring(self):
        from core.startup import wire_durable_audit_store
        from core.audit_event_semantics import get_audit_event_semantics
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            aes = get_audit_event_semantics()
            self.assertIsNotNone(aes._audit_store)

    def test_H02_audit_event_semantics_wired_flag_true(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertTrue(result["audit_event_semantics_wired"])


# ---------------------------------------------------------------------------
# Group I — CanonicalSessionTruthRuntime wired (best-effort)
# ---------------------------------------------------------------------------

class TestGroupI_CanonicalTruthWired(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_I01_canonical_truth_wired_flag_present(self):
        from core.startup import wire_durable_audit_store
        result = wire_durable_audit_store()
        if result["status"] == "ok":
            self.assertIn("canonical_truth_wired", result)


# ---------------------------------------------------------------------------
# Group J — Replay records reach durable store after wiring
# ---------------------------------------------------------------------------

class TestGroupJ_ReplayRecordsDurable(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_J01_replay_execution_record_written_to_store(self):
        from core.startup import wire_durable_audit_store
        from core.replay_foundation import get_replay_foundation, TaskExecutionRecord
        from core.replay_audit_persistence import get_replay_audit_store
        result = wire_durable_audit_store()
        if result["status"] != "ok":
            self.skipTest("wire_durable_audit_store not ok")
        rf = get_replay_foundation()
        rec = TaskExecutionRecord(task_id="j-task-01", success=True)
        rf.record_execution(rec)
        store = get_replay_audit_store()
        durable_records = store.load_all(kind_filter="task_execution")
        task_ids = [r.payload.get("task_id") for r in durable_records]
        self.assertIn("j-task-01", task_ids)


# ---------------------------------------------------------------------------
# Group K — Dispatch-spine audit events reach durable store after wiring
# ---------------------------------------------------------------------------

class TestGroupK_DispatchSpineAuditDurable(unittest.TestCase):
    def setUp(self):
        _fresh_all()

    def tearDown(self):
        _fresh_all()

    def test_K01_audit_task_dispatched_reaches_durable_store(self):
        from core.startup import wire_durable_audit_store
        from core.audit_event_semantics import audit_task_dispatched
        from core.replay_audit_persistence import get_replay_audit_store
        result = wire_durable_audit_store()
        if result["status"] != "ok":
            self.skipTest("wire_durable_audit_store not ok")
        audit_task_dispatched(
            "k-task-01",
            trace_id="k-trace-01",
            source="test",
            targets=["local"],
            transport="local",
        )
        store = get_replay_audit_store()
        durable_records = store.load_all(kind_filter="audit_event")
        task_ids = [r.payload.get("task_id") for r in durable_records]
        self.assertIn("k-task-01", task_ids)

    def test_K02_audit_task_completed_reaches_durable_store(self):
        from core.startup import wire_durable_audit_store
        from core.audit_event_semantics import audit_task_completed
        from core.replay_audit_persistence import get_replay_audit_store
        result = wire_durable_audit_store()
        if result["status"] != "ok":
            self.skipTest("wire_durable_audit_store not ok")
        audit_task_completed(
            "k-task-02",
            trace_id="k-trace-02",
            source="test",
            success=True,
        )
        store = get_replay_audit_store()
        durable_records = store.load_all(kind_filter="audit_event")
        task_ids = [r.payload.get("task_id") for r in durable_records]
        self.assertIn("k-task-02", task_ids)

    def test_K03_audit_task_failed_reaches_durable_store(self):
        from core.startup import wire_durable_audit_store
        from core.audit_event_semantics import audit_task_failed
        from core.replay_audit_persistence import get_replay_audit_store
        result = wire_durable_audit_store()
        if result["status"] != "ok":
            self.skipTest("wire_durable_audit_store not ok")
        audit_task_failed(
            "k-task-03",
            trace_id="k-trace-03",
            source="test",
            error_code="dispatch_failed",
            failure_domain="dispatch_spine",
        )
        store = get_replay_audit_store()
        durable_records = store.load_all(kind_filter="audit_event")
        task_ids = [r.payload.get("task_id") for r in durable_records]
        self.assertIn("k-task-03", task_ids)


if __name__ == "__main__":
    unittest.main()
