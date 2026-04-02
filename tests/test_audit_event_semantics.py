#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_audit_event_semantics.py
=====================================
PR-E — Operator Surface + Replay Foundation

Validates the AuditEventSemantics authority, unified vocabulary,
AuditEventRecord serialisation, and all helper factory functions.

Coverage:
  1.  AUDIT_EVENT_SEMANTICS_AUTHORITY sentinel importable and non-empty.
  2.  AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION is a non-empty string.
  3.  AUDIT_UNIFIED_VOCABULARY_POLICY is a non-empty string.
  4.  All names appear in __all__.
  5.  AuditEventKind: TASK_ACCEPTED is "task_accepted".
  6.  AuditEventKind: TASK_ADMITTED is "task_admitted".
  7.  AuditEventKind: TASK_DISPATCHED is "task_dispatched".
  8.  AuditEventKind: TASK_COMPLETED is "task_completed".
  9.  AuditEventKind: TASK_FAILED is "task_failed".
  10. AuditEventKind: ROUTE_DECISION is "route_decision".
  11. AuditEventKind: POLICY_DECISION is "policy_decision".
  12. AuditEventKind: FALLBACK_TRIGGERED is "fallback_triggered".
  13. AuditEventKind: RETRY_TRIGGERED is "retry_triggered".
  14. AuditEventKind: FAILURE_DOMAIN_IDENTIFIED is "failure_domain_identified".
  15. AUDIT_EVENT_DESCRIPTIONS has an entry for every AuditEventKind.
  16. Every AUDIT_EVENT_DESCRIPTIONS value is a non-empty string.
  17. AuditEventRecord: auto-generates audit_id with "aud_" prefix.
  18. AuditEventRecord: to_dict()/from_dict() round-trip.
  19. AuditEventRecord: to_json() returns valid JSON.
  20. AuditEventRecord.description() returns the canonical description.
  21. AuditEventRecord.description() for unknown kind returns message field.
  22. AuditSemanticSnapshot: to_dict() is JSON-serialisable.
  23. AuditEventSemantics: record() appends to ring.
  24. AuditEventSemantics: get_by_task() returns task-indexed records.
  25. AuditEventSemantics: get_by_kind() filters by kind.
  26. AuditEventSemantics: get_by_trace() filters by trace_id.
  27. AuditEventSemantics: all_events() returns all ring entries.
  28. AuditEventSemantics: snapshot() returns AuditSemanticSnapshot.
  29. AuditEventSemantics: snapshot event_count matches ring.
  30. get_audit_event_semantics() returns singleton.
  31. reset_audit_event_semantics() resets singleton.
  32. audit_task_accepted() emits TASK_ACCEPTED record.
  33. audit_task_admitted() emits TASK_ADMITTED record.
  34. audit_task_dispatched() emits TASK_DISPATCHED with targets.
  35. audit_task_completed() emits TASK_COMPLETED with success flag.
  36. audit_task_failed() emits TASK_FAILED with error_code.
  37. audit_route_decision() emits ROUTE_DECISION with path fields.
  38. audit_policy_decision() emits POLICY_DECISION with verdict.
  39. audit_fallback_triggered() emits FALLBACK_TRIGGERED.
  40. audit_retry_triggered() emits RETRY_TRIGGERED with attempt_number.
  41. audit_failure_domain() emits FAILURE_DOMAIN_IDENTIFIED.
  42. Parent audit_id linkage is preserved across helper calls.
  43. Multiple helpers for same task_id all appear in get_by_task().
  44. audit_task_failed() payload includes failure_domain.
  45. All helper emitted records are JSON-serialisable.
"""

from __future__ import annotations

import json
import sys
import os

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from core.audit_event_semantics import (
    AUDIT_EVENT_SEMANTICS_AUTHORITY,
    AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION,
    AUDIT_UNIFIED_VOCABULARY_POLICY,
    AuditEventKind,
    AUDIT_EVENT_DESCRIPTIONS,
    AuditEventRecord,
    AuditSemanticSnapshot,
    AuditEventSemantics,
    audit_task_accepted,
    audit_task_admitted,
    audit_task_dispatched,
    audit_task_completed,
    audit_task_failed,
    audit_route_decision,
    audit_policy_decision,
    audit_fallback_triggered,
    audit_retry_triggered,
    audit_failure_domain,
    get_audit_event_semantics,
    reset_audit_event_semantics,
)
import core.audit_event_semantics as _mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset():
    reset_audit_event_semantics()
    yield
    reset_audit_event_semantics()


# ===========================================================================
# 1-4: Authority sentinels
# ===========================================================================

class TestAuthoritySentinels:
    def test_01_authority_importable(self):
        assert AUDIT_EVENT_SEMANTICS_AUTHORITY
        assert isinstance(AUDIT_EVENT_SEMANTICS_AUTHORITY, str)

    def test_02_contract_version(self):
        assert AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION
        assert isinstance(AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION, str)

    def test_03_unified_vocabulary_policy(self):
        assert AUDIT_UNIFIED_VOCABULARY_POLICY
        assert isinstance(AUDIT_UNIFIED_VOCABULARY_POLICY, str)

    def test_04_all_exports(self):
        expected = [
            "AUDIT_EVENT_SEMANTICS_AUTHORITY",
            "AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION",
            "AUDIT_UNIFIED_VOCABULARY_POLICY",
            "AuditEventKind",
            "AUDIT_EVENT_DESCRIPTIONS",
            "AuditEventRecord",
            "AuditSemanticSnapshot",
            "AuditEventSemantics",
            "audit_task_accepted",
            "audit_task_admitted",
            "audit_task_dispatched",
            "audit_task_completed",
            "audit_task_failed",
            "audit_route_decision",
            "audit_policy_decision",
            "audit_fallback_triggered",
            "audit_retry_triggered",
            "audit_failure_domain",
            "get_audit_event_semantics",
            "reset_audit_event_semantics",
        ]
        for name in expected:
            assert name in _mod.__all__, f"{name!r} missing from __all__"


# ===========================================================================
# 5-16: AuditEventKind and descriptions
# ===========================================================================

class TestAuditEventKind:
    def test_05_task_accepted(self):
        assert AuditEventKind.TASK_ACCEPTED == "task_accepted"

    def test_06_task_admitted(self):
        assert AuditEventKind.TASK_ADMITTED == "task_admitted"

    def test_07_task_dispatched(self):
        assert AuditEventKind.TASK_DISPATCHED == "task_dispatched"

    def test_08_task_completed(self):
        assert AuditEventKind.TASK_COMPLETED == "task_completed"

    def test_09_task_failed(self):
        assert AuditEventKind.TASK_FAILED == "task_failed"

    def test_10_route_decision(self):
        assert AuditEventKind.ROUTE_DECISION == "route_decision"

    def test_11_policy_decision(self):
        assert AuditEventKind.POLICY_DECISION == "policy_decision"

    def test_12_fallback_triggered(self):
        assert AuditEventKind.FALLBACK_TRIGGERED == "fallback_triggered"

    def test_13_retry_triggered(self):
        assert AuditEventKind.RETRY_TRIGGERED == "retry_triggered"

    def test_14_failure_domain_identified(self):
        assert AuditEventKind.FAILURE_DOMAIN_IDENTIFIED == "failure_domain_identified"

    def test_15_descriptions_covers_all_kinds(self):
        for kind in AuditEventKind:
            assert kind in AUDIT_EVENT_DESCRIPTIONS, f"{kind!r} missing description"

    def test_16_all_descriptions_non_empty(self):
        for kind, desc in AUDIT_EVENT_DESCRIPTIONS.items():
            assert isinstance(desc, str) and desc, f"{kind!r} has empty description"


# ===========================================================================
# 17-22: AuditEventRecord
# ===========================================================================

class TestAuditEventRecord:
    def test_17_audit_id_auto_generated(self):
        r1 = AuditEventRecord()
        r2 = AuditEventRecord()
        assert r1.audit_id != r2.audit_id
        assert r1.audit_id.startswith("aud_")

    def test_18_roundtrip(self):
        rec = AuditEventRecord(
            kind=AuditEventKind.TASK_COMPLETED,
            task_id="t1",
            trace_id="tr1",
            source="scheduler",
            message="done",
            payload={"success": True},
        )
        d = rec.to_dict()
        restored = AuditEventRecord.from_dict(d)
        assert restored.task_id == "t1"
        assert restored.kind == AuditEventKind.TASK_COMPLETED

    def test_19_to_json(self):
        rec = AuditEventRecord(kind=AuditEventKind.TASK_FAILED, task_id="t1")
        raw = rec.to_json()
        parsed = json.loads(raw)
        assert parsed["task_id"] == "t1"

    def test_20_description_returns_canonical(self):
        rec = AuditEventRecord(kind=AuditEventKind.TASK_COMPLETED)
        desc = rec.description()
        expected = AUDIT_EVENT_DESCRIPTIONS[AuditEventKind.TASK_COMPLETED]
        assert desc == expected

    def test_21_description_unknown_kind_returns_message(self):
        rec = AuditEventRecord(kind="custom_kind", message="custom message")
        assert rec.description() == "custom message"

    def test_22_snapshot_json_serialisable(self):
        snap = AuditSemanticSnapshot()
        json.dumps(snap.to_dict())  # should not raise


# ===========================================================================
# 23-31: AuditEventSemantics operations
# ===========================================================================

class TestAuditEventSemanticsOperations:
    def test_23_record_appends_to_ring(self):
        semantics = AuditEventSemantics()
        rec = AuditEventRecord(kind=AuditEventKind.TASK_ACCEPTED, task_id="t1")
        semantics.record(rec)
        assert len(semantics.all_events()) == 1

    def test_24_get_by_task(self):
        semantics = AuditEventSemantics()
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_ACCEPTED, task_id="t_a"))
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_COMPLETED, task_id="t_a"))
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_FAILED, task_id="t_b"))
        assert len(semantics.get_by_task("t_a")) == 2

    def test_25_get_by_kind(self):
        semantics = AuditEventSemantics()
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_COMPLETED))
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_FAILED))
        semantics.record(AuditEventRecord(kind=AuditEventKind.TASK_COMPLETED))
        assert len(semantics.get_by_kind(AuditEventKind.TASK_COMPLETED)) == 2

    def test_26_get_by_trace(self):
        semantics = AuditEventSemantics()
        semantics.record(AuditEventRecord(trace_id="tr1", kind=AuditEventKind.TASK_ACCEPTED))
        semantics.record(AuditEventRecord(trace_id="tr2", kind=AuditEventKind.TASK_ACCEPTED))
        assert len(semantics.get_by_trace("tr1")) == 1

    def test_27_all_events(self):
        semantics = AuditEventSemantics()
        for _ in range(5):
            semantics.record(AuditEventRecord(kind=AuditEventKind.RUNTIME_EVENT))
        assert len(semantics.all_events()) == 5

    def test_28_snapshot_returns_correct_type(self):
        semantics = AuditEventSemantics()
        snap = semantics.snapshot()
        assert isinstance(snap, AuditSemanticSnapshot)

    def test_29_snapshot_event_count_matches(self):
        semantics = AuditEventSemantics()
        for _ in range(7):
            semantics.record(AuditEventRecord(kind=AuditEventKind.DEVICE_HEARTBEAT))
        snap = semantics.snapshot()
        assert snap.event_count == 7

    def test_30_singleton(self):
        s1 = get_audit_event_semantics()
        s2 = get_audit_event_semantics()
        assert s1 is s2

    def test_31_reset_singleton(self):
        s1 = get_audit_event_semantics()
        reset_audit_event_semantics()
        s2 = get_audit_event_semantics()
        assert s1 is not s2


# ===========================================================================
# 32-45: Helper factory functions
# ===========================================================================

class TestHelperFactories:
    def test_32_audit_task_accepted(self):
        rec = audit_task_accepted("t1", trace_id="tr1", origin="api", goal="do x")
        assert rec.kind == AuditEventKind.TASK_ACCEPTED
        assert rec.task_id == "t1"
        assert rec.payload["goal"] == "do x"

    def test_33_audit_task_admitted(self):
        rec = audit_task_admitted("t1", trace_id="tr1")
        assert rec.kind == AuditEventKind.TASK_ADMITTED

    def test_34_audit_task_dispatched(self):
        rec = audit_task_dispatched("t1", targets=["dev_a"], transport="websocket")
        assert rec.kind == AuditEventKind.TASK_DISPATCHED
        assert rec.payload["targets"] == ["dev_a"]

    def test_35_audit_task_completed(self):
        rec = audit_task_completed("t1", success=True)
        assert rec.kind == AuditEventKind.TASK_COMPLETED
        assert rec.payload["success"] is True

    def test_36_audit_task_failed(self):
        rec = audit_task_failed("t1", error_code="TIMEOUT", failure_domain="transport")
        assert rec.kind == AuditEventKind.TASK_FAILED

    def test_37_audit_route_decision(self):
        rec = audit_route_decision(
            "t1",
            selected_targets=["dev_x"],
            effective_path="relay",
            route_explanation="relay chosen due to mesh unavailable",
        )
        assert rec.kind == AuditEventKind.ROUTE_DECISION
        assert rec.payload["effective_path"] == "relay"

    def test_38_audit_policy_decision(self):
        rec = audit_policy_decision("t1", verdict="admit", policy_score=0.9)
        assert rec.kind == AuditEventKind.POLICY_DECISION
        assert rec.payload["verdict"] == "admit"

    def test_39_audit_fallback_triggered(self):
        rec = audit_fallback_triggered(
            "t1", fallback_task_id="t2", reason="primary failed"
        )
        assert rec.kind == AuditEventKind.FALLBACK_TRIGGERED
        assert rec.payload["fallback_task_id"] == "t2"

    def test_40_audit_retry_triggered(self):
        rec = audit_retry_triggered("t1", retry_task_id="t2", attempt_number=2)
        assert rec.kind == AuditEventKind.RETRY_TRIGGERED
        assert rec.payload["attempt_number"] == 2

    def test_41_audit_failure_domain(self):
        rec = audit_failure_domain("t1", failure_domain="routing", error_code="NO_ROUTE")
        assert rec.kind == AuditEventKind.FAILURE_DOMAIN_IDENTIFIED
        assert rec.payload["failure_domain"] == "routing"

    def test_42_parent_audit_id_linkage(self):
        r1 = audit_task_accepted("t1")
        r2 = audit_task_admitted("t1", parent_audit_ids=[r1.audit_id])
        assert r2.parent_audit_ids == [r1.audit_id]

    def test_43_multiple_helpers_same_task(self):
        audit_task_accepted("t_multi")
        audit_task_admitted("t_multi")
        audit_task_dispatched("t_multi")
        records = get_audit_event_semantics().get_by_task("t_multi")
        assert len(records) == 3

    def test_44_failed_payload_includes_failure_domain(self):
        rec = audit_task_failed(
            "t_fail", error_code="EXEC_ERR", failure_domain="execution"
        )
        assert rec.payload.get("failure_domain") == "execution"
        assert rec.payload.get("error_code") == "EXEC_ERR"

    def test_45_all_helpers_json_serialisable(self):
        helpers = [
            audit_task_accepted("t1"),
            audit_task_admitted("t1"),
            audit_task_dispatched("t1"),
            audit_task_completed("t1"),
            audit_task_failed("t1"),
            audit_route_decision("t1"),
            audit_policy_decision("t1"),
            audit_fallback_triggered("t1"),
            audit_retry_triggered("t1"),
            audit_failure_domain("t1"),
        ]
        for rec in helpers:
            json.dumps(rec.to_dict())  # should not raise
