#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_operator_surface_review.py
=======================================
PR-K — Operator Review Surface and End-to-End Recovery/Audit Inspection.

Validates the new inspection dimensions added to OperatorSurface:
  RecoveryInspection        — recovery disposition per task
  PartialResultInspection   — partial-result outcome per hybrid execution
  AuditEvidenceInspection   — durable audit evidence coverage per task
  EndToEndReviewSummary     — unified postmortem review combining all dimensions

Coverage:
  1.  RecoveryInspection is a dataclass with required fields.
  2.  RecoveryInspection.to_dict() is JSON-serialisable and contains all keys.
  3.  PartialResultInspection is a dataclass with required fields.
  4.  PartialResultInspection.to_dict() is JSON-serialisable and contains all keys.
  5.  AuditEvidenceInspection is a dataclass with required fields.
  6.  AuditEvidenceInspection.to_dict() is JSON-serialisable and contains all keys.
  7.  EndToEndReviewSummary is a dataclass with required fields.
  8.  EndToEndReviewSummary.to_dict() is JSON-serialisable and nested dicts present.
  9.  RecoveryInspection / PartialResultInspection / AuditEvidenceInspection are in __all__.
  10. EndToEndReviewSummary is in __all__.
  11. inspect_recovery() returns None for unknown task_id.
  12. inspect_partial_result() returns None for unknown task_id.
  13. inspect_audit_evidence() always returns AuditEvidenceInspection (never None).
  14. inspect_audit_evidence() returns empty counts for unknown task_id.
  15. end_to_end_review() always returns EndToEndReviewSummary (never None).
  16. end_to_end_review() is JSON-serialisable for unknown task_id.
  17. end_to_end_review() marks reviewable=False for unknown task_id.
  18. end_to_end_review() for unknown task includes a review_note about insufficient evidence.
  19. inspect_recovery() returns RecoveryInspection when task is in lifecycle registry.
  20. RecoveryInspection.current_owner reflects the registry owner.
  21. end_to_end_review() for registered task: task field is populated.
  22. end_to_end_review() for registered task: route field is populated.
  23. end_to_end_review() for registered task: reviewable=True.
  24. inspect_partial_result() returns PartialResultInspection for a hybrid record.
  25. PartialResultInspection.has_partial_result=True when snapshot is set.
  26. PartialResultInspection.partial_result_disposition matches the record.
  27. inspect_audit_evidence() counts records by kind for matching task_id.
  28. inspect_audit_evidence().has_evidence=True when records exist.
  29. end_to_end_review() partial_result field populated when hybrid record exists.
  30. end_to_end_review() audit_evidence field is always populated.
  31. end_to_end_review() recovery note appended when task is recovered.
  32. AuditEvidenceInspection.audit_kinds_present is sorted.
  33. AuditEvidenceInspection.earliest_record_at and latest_record_at set correctly.
  34. inspect_recovery() recovery_action_taken=False for terminal_on_interrupt.
  35. inspect_recovery() recovery_action_taken=True for resumable disposition.
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import Any, Dict

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.operator_surface as _mod
from core.operator_surface import (
    RecoveryInspection,
    PartialResultInspection,
    AuditEvidenceInspection,
    EndToEndReviewSummary,
    OperatorSurface,
    get_operator_surface,
    reset_operator_surface,
    OPERATOR_SURFACE_AUTHORITY,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_all():
    """Reset all relevant singletons before and after each test."""
    _do_reset()
    yield
    _do_reset()


def _do_reset():
    reset_operator_surface()
    try:
        from core.canonical_task import reset_canonical_task_runtime
        reset_canonical_task_runtime()
    except Exception:
        pass  # module may not be loaded in all test environments
    try:
        from core.hybrid_orchestration_continuity import reset_continuity_registry
        reset_continuity_registry()
    except Exception:
        pass  # module may not be loaded in all test environments
    try:
        from core.task_envelope_lifecycle_registry import reset_lifecycle_registry
        reset_lifecycle_registry()
    except Exception:
        pass  # module may not be loaded in all test environments
    try:
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()
    except Exception:
        pass  # module may not be loaded in all test environments
    try:
        from core.replay_audit_persistence import reset_replay_audit_store
        reset_replay_audit_store()
    except Exception:
        pass  # module may not be loaded in all test environments


def _build_canonical_task(goal: str = "test goal", lifecycle: str = "completed"):
    from core.canonical_task import (
        build_canonical_task,
        get_canonical_task_runtime,
        TaskLifecycle,
        TaskOrigin,
    )
    task = build_canonical_task(
        goal=goal,
        origin=TaskOrigin.API_REQUEST,
        requested_action="test_action",
        selected_targets=["device_001"],
    )
    task.lifecycle = TaskLifecycle(lifecycle)
    task.result.success = (lifecycle == "completed")
    rt = get_canonical_task_runtime()
    rt.register(task)
    return task


def _register_lifecycle_envelope(task_id: str, owner_str: str = "device_dispatch"):
    """Register a minimal envelope in the lifecycle registry under the given owner."""
    from core.task_envelope_lifecycle_registry import (
        get_lifecycle_registry,
        LifecycleOwner,
    )
    registry = get_lifecycle_registry()
    # Build a minimal stub envelope object
    class _Env:
        pass
    env = _Env()
    env.task_id = task_id
    env.trace_id = f"trace_{task_id}"
    env.target = "device_001"
    env.tool_name = "test_tool"
    env.timeout = 30.0
    owner = LifecycleOwner(owner_str)
    registry.register(env, owner=owner)


def _register_hybrid_record(task_id: str, **kwargs):
    """Register a HybridOrchestrationRecord with the given task_id."""
    from core.hybrid_orchestration_continuity import (
        get_continuity_registry,
        HybridOrchestrationRecord,
        HybridOrchestrationLifecycleState,
    )
    rec = HybridOrchestrationRecord(task_id=task_id, **kwargs)
    get_continuity_registry().register(rec)
    return rec


# ---------------------------------------------------------------------------
# 1-10: Dataclass structure and __all__
# ---------------------------------------------------------------------------

class TestDataclassStructure:
    def test_01_recovery_inspection_fields(self):
        ri = RecoveryInspection(task_id="t1", recovery_disposition="resumable")
        assert ri.task_id == "t1"
        assert ri.recovery_disposition == "resumable"
        assert ri.is_recovered is False
        assert ri.recovery_action_taken is False

    def test_02_recovery_inspection_to_dict_serialisable(self):
        ri = RecoveryInspection(
            task_id="t1",
            is_recovered=True,
            recovery_disposition="replay_only",
            current_owner="routing",
            snapshot_id="snap_abc",
            recovery_action_taken=True,
            recovery_note="Recovered from snapshot.",
        )
        d = ri.to_dict()
        json.dumps(d)  # must not raise
        for key in (
            "task_id", "is_recovered", "recovery_disposition",
            "current_owner", "snapshot_id", "interrupted_at",
            "recovery_action_taken", "recovery_note", "_source",
        ):
            assert key in d, f"Missing key: {key!r}"

    def test_03_partial_result_inspection_fields(self):
        pi = PartialResultInspection(
            task_id="t2", partial_result_disposition="preserved", resume_count=3
        )
        assert pi.task_id == "t2"
        assert pi.partial_result_disposition == "preserved"
        assert pi.resume_count == 3

    def test_04_partial_result_inspection_to_dict_serialisable(self):
        pi = PartialResultInspection(
            task_id="t2",
            execution_id="hexec_123",
            lifecycle_state="interrupted",
            partial_result_disposition="invalidated",
            partial_result_origin="remote",
            resume_count=1,
            has_partial_result=True,
            interruption_reason="process_restart",
        )
        d = pi.to_dict()
        json.dumps(d)
        for key in (
            "task_id", "execution_id", "lifecycle_state",
            "partial_result_disposition", "partial_result_origin",
            "resume_count", "has_partial_result", "interruption_reason", "_source",
        ):
            assert key in d, f"Missing key: {key!r}"

    def test_05_audit_evidence_inspection_fields(self):
        ae = AuditEvidenceInspection(
            task_id="t3", has_evidence=True, evidence_count=5
        )
        assert ae.task_id == "t3"
        assert ae.has_evidence is True
        assert ae.evidence_count == 5

    def test_06_audit_evidence_inspection_to_dict_serialisable(self):
        ae = AuditEvidenceInspection(
            task_id="t3",
            has_evidence=True,
            evidence_count=2,
            by_kind={"task_execution": 1, "route_decision": 1},
            earliest_record_at=1000.0,
            latest_record_at=2000.0,
            audit_kinds_present=["route_decision", "task_execution"],
        )
        d = ae.to_dict()
        json.dumps(d)
        for key in (
            "task_id", "has_evidence", "evidence_count", "by_kind",
            "earliest_record_at", "latest_record_at", "audit_kinds_present", "_source",
        ):
            assert key in d, f"Missing key: {key!r}"

    def test_07_end_to_end_review_summary_fields(self):
        s = EndToEndReviewSummary(task_id="t4", trace_id="tr1")
        assert s.task_id == "t4"
        assert s.trace_id == "tr1"
        assert s.reviewable is False
        assert s.review_notes == []
        assert s.authority == OPERATOR_SURFACE_AUTHORITY

    def test_08_end_to_end_review_summary_to_dict_serialisable(self):
        from core.operator_surface import TaskInspection, RouteInspection
        ti = TaskInspection(task_id="t4", lifecycle="completed")
        ri = RouteInspection(task_id="t4")
        summary = EndToEndReviewSummary(
            task_id="t4",
            trace_id="tr1",
            task=ti,
            route=ri,
            reviewable=True,
            review_notes=["note1"],
        )
        d = summary.to_dict()
        json.dumps(d)
        for key in (
            "task_id", "trace_id", "generated_at", "task", "route",
            "recovery", "partial_result", "audit_evidence", "lineage",
            "reviewable", "review_notes", "authority",
        ):
            assert key in d, f"Missing key: {key!r}"
        assert d["task"] is not None
        assert d["route"] is not None
        assert d["recovery"] is None
        assert d["partial_result"] is None

    def test_09_new_types_in_all(self):
        for name in ("RecoveryInspection", "PartialResultInspection",
                     "AuditEvidenceInspection"):
            assert name in _mod.__all__, f"{name!r} missing from __all__"

    def test_10_end_to_end_review_summary_in_all(self):
        assert "EndToEndReviewSummary" in _mod.__all__


# ---------------------------------------------------------------------------
# 11-18: Graceful degradation for unknown task
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_11_inspect_recovery_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_recovery("nonexistent") is None

    def test_12_inspect_partial_result_unknown_returns_none(self):
        surface = get_operator_surface()
        assert surface.inspect_partial_result("nonexistent") is None

    def test_13_inspect_audit_evidence_never_returns_none(self):
        surface = get_operator_surface()
        result = surface.inspect_audit_evidence("nonexistent")
        assert result is not None
        assert isinstance(result, AuditEvidenceInspection)

    def test_14_inspect_audit_evidence_unknown_zero_counts(self):
        surface = get_operator_surface()
        result = surface.inspect_audit_evidence("nonexistent")
        assert result.has_evidence is False
        assert result.evidence_count == 0
        assert result.by_kind == {}
        assert result.task_id == "nonexistent"

    def test_15_end_to_end_review_never_returns_none(self):
        surface = get_operator_surface()
        result = surface.end_to_end_review("nonexistent")
        assert result is not None
        assert isinstance(result, EndToEndReviewSummary)

    def test_16_end_to_end_review_unknown_json_serialisable(self):
        surface = get_operator_surface()
        result = surface.end_to_end_review("nonexistent")
        json.dumps(result.to_dict())  # must not raise

    def test_17_end_to_end_review_unknown_not_reviewable(self):
        surface = get_operator_surface()
        result = surface.end_to_end_review("nonexistent")
        assert result.reviewable is False

    def test_18_end_to_end_review_unknown_has_review_note(self):
        surface = get_operator_surface()
        result = surface.end_to_end_review("nonexistent")
        combined = " ".join(result.review_notes)
        assert "not found" in combined.lower() or "insufficient" in combined.lower()


# ---------------------------------------------------------------------------
# 19-23: Live lifecycle registry integration
# ---------------------------------------------------------------------------

class TestRecoveryInspection:
    def test_19_inspect_recovery_pending_task_returns_inspection(self):
        _register_lifecycle_envelope("task-live-001", "device_dispatch")
        surface = get_operator_surface()
        result = surface.inspect_recovery("task-live-001")
        assert result is not None
        assert isinstance(result, RecoveryInspection)

    def test_20_recovery_current_owner_reflects_registry(self):
        _register_lifecycle_envelope("task-live-002", "routing")
        surface = get_operator_surface()
        result = surface.inspect_recovery("task-live-002")
        assert result is not None
        assert result.current_owner == "routing"

    def test_21_end_to_end_task_field_populated_for_registered(self):
        task = _build_canonical_task("e2e goal", "completed")
        surface = get_operator_surface()
        result = surface.end_to_end_review(task.identity.task_id)
        assert result.task is not None
        assert result.task.task_id == task.identity.task_id
        assert result.task.goal == "e2e goal"

    def test_22_end_to_end_route_field_populated_for_registered(self):
        task = _build_canonical_task("route goal", "dispatched")
        surface = get_operator_surface()
        result = surface.end_to_end_review(task.identity.task_id)
        assert result.route is not None

    def test_23_end_to_end_reviewable_true_for_registered(self):
        task = _build_canonical_task("reviewable goal", "completed")
        surface = get_operator_surface()
        result = surface.end_to_end_review(task.identity.task_id)
        assert result.reviewable is True


# ---------------------------------------------------------------------------
# 24-29: Partial result inspection
# ---------------------------------------------------------------------------

class TestPartialResultInspection:
    def test_24_inspect_partial_result_returns_inspection(self):
        from core.hybrid_orchestration_continuity import HybridOrchestrationRecord
        rec = _register_hybrid_record("pr-task-001")
        surface = get_operator_surface()
        result = surface.inspect_partial_result("pr-task-001")
        assert result is not None
        assert isinstance(result, PartialResultInspection)
        assert result.task_id == "pr-task-001"
        assert result.execution_id == rec.execution_id

    def test_25_partial_has_partial_result_true_when_snapshot_set(self):
        rec = _register_hybrid_record("pr-task-002")
        rec.partial_result_snapshot = {"data": "some_value"}
        rec.partial_result_origin = "local"
        rec.partial_result_disposition = "preserved"
        surface = get_operator_surface()
        result = surface.inspect_partial_result("pr-task-002")
        assert result is not None
        assert result.has_partial_result is True

    def test_26_partial_disposition_reflects_record(self):
        rec = _register_hybrid_record("pr-task-003")
        rec.partial_result_snapshot = {"x": 1}
        rec.partial_result_disposition = "invalidated"
        surface = get_operator_surface()
        result = surface.inspect_partial_result("pr-task-003")
        assert result is not None
        assert result.partial_result_disposition == "invalidated"

    def test_29_end_to_end_partial_result_populated_when_hybrid_record(self):
        task = _build_canonical_task("hybrid goal", "completed")
        tid = task.identity.task_id
        rec = _register_hybrid_record(tid)
        rec.partial_result_snapshot = {"data": "partial"}
        rec.partial_result_disposition = "merged"
        surface = get_operator_surface()
        result = surface.end_to_end_review(tid)
        assert result.partial_result is not None
        assert result.partial_result.task_id == tid


# ---------------------------------------------------------------------------
# 27-33: Audit evidence inspection
# ---------------------------------------------------------------------------

class TestAuditEvidenceInspection:
    def _make_store(self, tmp_path):
        from core.replay_audit_persistence import (
            DurableAuditStore,
            reset_replay_audit_store,
        )
        reset_replay_audit_store()
        return DurableAuditStore(store_path=str(tmp_path / "audit.jsonl"))

    def test_27_audit_evidence_counts_by_kind(self, tmp_path):
        store = self._make_store(tmp_path)
        from core.replay_audit_persistence import (
            append_replay_audit_record,
            AuditRecordKind,
            reset_replay_audit_store,
            get_replay_audit_store,
        )
        reset_replay_audit_store()
        # Patch the singleton to use our tmp store
        import core.replay_audit_persistence as _rap
        _rap._store_instance = store
        try:
            append_replay_audit_record(
                {"task_id": "ae-task-001", "info": "x"}, AuditRecordKind.TASK_EXECUTION.value
            )
            append_replay_audit_record(
                {"task_id": "ae-task-001", "route": "dev"}, AuditRecordKind.ROUTE_DECISION.value
            )
            append_replay_audit_record(
                {"task_id": "other-task"}, AuditRecordKind.TASK_EXECUTION.value
            )
            surface = get_operator_surface()
            result = surface.inspect_audit_evidence("ae-task-001")
            assert result.evidence_count == 2
            assert result.by_kind.get("task_execution") == 1
            assert result.by_kind.get("route_decision") == 1
            assert "other-task" not in str(result.by_kind)
        finally:
            _rap._store_instance = None

    def test_28_audit_has_evidence_true_when_records_exist(self, tmp_path):
        store = self._make_store(tmp_path)
        from core.replay_audit_persistence import (
            append_replay_audit_record,
            AuditRecordKind,
        )
        import core.replay_audit_persistence as _rap
        _rap._store_instance = store
        try:
            append_replay_audit_record(
                {"task_id": "ae-task-002"}, AuditRecordKind.RUNTIME_EVENT.value
            )
            surface = get_operator_surface()
            result = surface.inspect_audit_evidence("ae-task-002")
            assert result.has_evidence is True
        finally:
            _rap._store_instance = None

    def test_30_end_to_end_audit_evidence_always_populated(self):
        surface = get_operator_surface()
        result = surface.end_to_end_review("some-task")
        assert result.audit_evidence is not None
        assert isinstance(result.audit_evidence, AuditEvidenceInspection)

    def test_32_audit_kinds_present_sorted(self, tmp_path):
        store = self._make_store(tmp_path)
        from core.replay_audit_persistence import (
            append_replay_audit_record,
            AuditRecordKind,
        )
        import core.replay_audit_persistence as _rap
        _rap._store_instance = store
        try:
            append_replay_audit_record(
                {"task_id": "ae-sort-001"}, AuditRecordKind.ROUTE_DECISION.value
            )
            append_replay_audit_record(
                {"task_id": "ae-sort-001"}, AuditRecordKind.TASK_EXECUTION.value
            )
            append_replay_audit_record(
                {"task_id": "ae-sort-001"}, AuditRecordKind.FALLBACK.value
            )
            surface = get_operator_surface()
            result = surface.inspect_audit_evidence("ae-sort-001")
            assert result.audit_kinds_present == sorted(result.audit_kinds_present)
        finally:
            _rap._store_instance = None

    def test_33_audit_timestamps_set_correctly(self, tmp_path):
        store = self._make_store(tmp_path)
        from core.replay_audit_persistence import (
            ReplayAuditRecord,
            AuditRecordKind,
        )
        import core.replay_audit_persistence as _rap
        _rap._store_instance = store
        try:
            rec1 = ReplayAuditRecord(
                kind=AuditRecordKind.TASK_EXECUTION.value,
                recorded_at=1000.0,
                payload={"task_id": "ts-task-001"},
            )
            rec2 = ReplayAuditRecord(
                kind=AuditRecordKind.ROUTE_DECISION.value,
                recorded_at=2000.0,
                payload={"task_id": "ts-task-001"},
            )
            store.append(rec1)
            store.append(rec2)
            surface = get_operator_surface()
            result = surface.inspect_audit_evidence("ts-task-001")
            assert result.earliest_record_at == 1000.0
            assert result.latest_record_at == 2000.0
        finally:
            _rap._store_instance = None


# ---------------------------------------------------------------------------
# 31, 34-35: Recovery disposition edge cases
# ---------------------------------------------------------------------------

class TestRecoveryDispositionEdgeCases:
    def test_31_end_to_end_review_note_when_task_in_registry(self):
        _register_lifecycle_envelope("note-task-001", "device_dispatch")
        surface = get_operator_surface()
        result = surface.end_to_end_review("note-task-001")
        # recovery note should mention current_owner or some useful info
        assert result.recovery is not None

    def test_34_recovery_action_taken_false_for_terminal(self, tmp_path):
        """terminal_on_interrupt → recovery_action_taken=False."""
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            TaskLifecycleSnapshotRecord,
        )
        import core.task_lifecycle_persistence as _tlp
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tls.json")
        )
        snap = TaskLifecycleSnapshotRecord(
            records=[{"task_id": "term-task", "owner": "result_completion"}]
        )
        store.save(snap)
        old = _tlp._store_instance
        _tlp._store_instance = store
        try:
            surface = get_operator_surface()
            result = surface.inspect_recovery("term-task")
            assert result is not None
            assert result.recovery_disposition == "terminal_on_interrupt"
            assert result.recovery_action_taken is False
        finally:
            _tlp._store_instance = old

    def test_35_recovery_action_taken_true_for_resumable(self, tmp_path):
        """device_dispatch → resumable → recovery_action_taken=True."""
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            TaskLifecycleSnapshotRecord,
        )
        import core.task_lifecycle_persistence as _tlp
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tls2.json")
        )
        snap = TaskLifecycleSnapshotRecord(
            records=[{"task_id": "resumable-task", "owner": "device_dispatch"}]
        )
        store.save(snap)
        old = _tlp._store_instance
        _tlp._store_instance = store
        try:
            surface = get_operator_surface()
            result = surface.inspect_recovery("resumable-task")
            assert result is not None
            assert result.recovery_disposition == "resumable"
            assert result.recovery_action_taken is True
        finally:
            _tlp._store_instance = old
