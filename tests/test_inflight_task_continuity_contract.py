#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_inflight_task_continuity_contract.py
=================================================
PR-P1-1: In-Flight Task Continuity Contract — test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings.
B  — TaskContinuityStatus enum has all six expected values.
C  — InFlightTaskContinuityRecord: construction and defaults.
D  — InFlightTaskContinuityRecord: to_dict / from_dict round-trip.
E  — TaskContinuityReport: computed properties (state_restored,
     continuity_restored, continuity_gap, has_unrecovered, has_ambiguous).
F  — TaskContinuityReport: to_dict / from_dict round-trip.
G  — Contract: resumed status when task_id already in live registry.
H  — Contract: recoverable status for RESUMABLE task with dispatch taken.
I  — Contract: recoverable status for REPLAY_ONLY task with dispatch taken.
J  — Contract: interrupted status for REISSUABLE task.
K  — Contract: abandoned status for TERMINAL_ON_INTERRUPT task.
L  — Contract: ambiguous status for empty task_id.
M  — Contract: needs_reconcile for duplicate task_id in snapshot.
N  — Contract: needs_reconcile for stale snapshot record.
O  — Contract: state_restored ≠ continuity_restored gap is explicit.
P  — Contract: ambiguous MUST NOT be upgraded (no positive status).
Q  — Contract: REISSUABLE is interrupted even if dispatch was taken.
R  — Contract: unknown disposition yields ambiguous (safe fallback).
S  — build_continuity_report convenience wrapper works.
T  — RuntimeRecoveryReport has continuity_report field.
U  — RuntimeRecoveryReport.to_dict includes continuity_report.
V  — RecoveryTruthSurface in_flight_continuity probe returns observed
     when InFlightTaskContinuityContract is available.
W  — Full restart simulation: RESUMABLE task dispatch → recoverable report.
X  — Full restart simulation: already-live task → resumed report.
Y  — Mixed scenario: multiple tasks across all status types.
Z  — Empty snapshot produces well-formed empty report.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _trace_id() -> str:
    return f"trace_{uuid.uuid4().hex[:8]}"


def _make_restored_record(
    task_id: str = "",
    disposition: str = "resumable",
    owner: str = "device_dispatch",
    device_id: str = "dev-001",
    registered_at: Optional[float] = None,
    snapshot_id: str = "snap-001",
    *,
    auto_task_id: bool = True,
) -> Any:
    """Build a minimal RestoredTaskRecord-compatible object.

    Parameters
    ----------
    task_id
        Explicit task_id.  When empty and ``auto_task_id=True`` (default),
        a random id is generated.  Pass ``auto_task_id=False`` to keep the
        empty string (for testing ambiguous status).
    """
    @dataclass
    class _FakeRestoredTaskRecord:
        task_id: str = ""
        trace_id: str = ""
        target_device_id: str = ""
        tool_name: str = "test_tool"
        owner: str = "device_dispatch"
        timeout: float = 30.0
        registered_at: float = field(default_factory=time.time)
        interrupted_at: float = field(default_factory=time.time)
        snapshot_id: str = ""
        metadata: Dict[str, Any] = field(default_factory=dict)

        # disposition as a simple string attribute (no enum wrapping needed
        # because the contract reads .value if it exists, otherwise str())
        disposition: Any = "resumable"

    actual_task_id = task_id
    if not actual_task_id and auto_task_id:
        actual_task_id = _task_id()

    rec = _FakeRestoredTaskRecord(
        task_id=actual_task_id,
        trace_id=_trace_id(),
        target_device_id=device_id,
        owner=owner,
        snapshot_id=snapshot_id,
        registered_at=registered_at or time.time(),
        interrupted_at=time.time(),
        disposition=disposition,
    )
    return rec


# ---------------------------------------------------------------------------
# A: sentinel importability
# ---------------------------------------------------------------------------

class TestGroupA_Sentinels:
    def test_A01_authority_sentinel(self):
        from core.inflight_task_continuity_contract import (
            INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY,
        )
        assert isinstance(INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY, str)
        assert len(INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY) > 20

    def test_A02_pr_p1_1_sentinel(self):
        from core.inflight_task_continuity_contract import (
            INFLIGHT_TASK_CONTINUITY_CONTRACT_PR_P1_1_SENTINEL,
        )
        assert "PR-P1-1" in INFLIGHT_TASK_CONTINUITY_CONTRACT_PR_P1_1_SENTINEL

    def test_A03_state_not_continuity_policy(self):
        from core.inflight_task_continuity_contract import (
            STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY,
        )
        assert "state" in STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY.lower()
        assert "continuity" in STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY.lower()

    def test_A04_ambiguous_no_upgrade_policy(self):
        from core.inflight_task_continuity_contract import (
            AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY,
        )
        assert "ambiguous" in AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY.lower()

    def test_A05_interrupted_downgrade_policy(self):
        from core.inflight_task_continuity_contract import (
            INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY,
        )
        assert "interrupted" in INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY.lower()

    def test_A06_duplicate_reconcile_policy(self):
        from core.inflight_task_continuity_contract import (
            DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY,
        )
        assert "duplicate" in DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY.lower()
        assert "needs_reconcile" in DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY.lower()

    def test_A07_stale_reconcile_policy(self):
        from core.inflight_task_continuity_contract import (
            STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY,
        )
        assert "stale" in STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY.lower()

    def test_A08_consumable_by_acceptance_policy(self):
        from core.inflight_task_continuity_contract import (
            CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY,
        )
        assert "acceptance" in CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY.lower()
        assert "continuity_gap_count" in CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY


# ---------------------------------------------------------------------------
# B: TaskContinuityStatus enum
# ---------------------------------------------------------------------------

class TestGroupB_TaskContinuityStatusEnum:
    def test_B01_all_six_values_present(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        expected = {"resumed", "recoverable", "interrupted", "abandoned",
                    "needs_reconcile", "ambiguous"}
        actual = {s.value for s in TaskContinuityStatus}
        assert expected == actual

    def test_B02_is_positive_flags(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        assert TaskContinuityStatus.resumed.is_positive is True
        assert TaskContinuityStatus.recoverable.is_positive is True
        assert TaskContinuityStatus.interrupted.is_positive is False
        assert TaskContinuityStatus.abandoned.is_positive is False
        assert TaskContinuityStatus.needs_reconcile.is_positive is False
        assert TaskContinuityStatus.ambiguous.is_positive is False

    def test_B03_requires_action_flags(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        assert TaskContinuityStatus.interrupted.requires_action is True
        assert TaskContinuityStatus.needs_reconcile.requires_action is True
        assert TaskContinuityStatus.resumed.requires_action is False
        assert TaskContinuityStatus.recoverable.requires_action is False
        assert TaskContinuityStatus.abandoned.requires_action is False
        assert TaskContinuityStatus.ambiguous.requires_action is False

    def test_B04_is_terminal_flags(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        assert TaskContinuityStatus.abandoned.is_terminal is True
        assert TaskContinuityStatus.ambiguous.is_terminal is True
        assert TaskContinuityStatus.resumed.is_terminal is False
        assert TaskContinuityStatus.recoverable.is_terminal is False


# ---------------------------------------------------------------------------
# C: InFlightTaskContinuityRecord construction
# ---------------------------------------------------------------------------

class TestGroupC_InFlightTaskContinuityRecord:
    def test_C01_default_construction(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityRecord,
            TaskContinuityStatus,
        )
        rec = InFlightTaskContinuityRecord()
        assert rec.task_id == ""
        assert rec.continuity_status == TaskContinuityStatus.ambiguous
        assert rec.snapshot_age_seconds == 0.0

    def test_C02_full_construction(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityRecord,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = InFlightTaskContinuityRecord(
            task_id=tid,
            trace_id="trace-abc",
            disposition="resumable",
            continuity_status=TaskContinuityStatus.recoverable,
            reason="dispatch taken",
            device_id="dev-001",
            snapshot_age_seconds=15.5,
            snapshot_id="snap-xyz",
        )
        assert rec.task_id == tid
        assert rec.continuity_status == TaskContinuityStatus.recoverable
        assert rec.snapshot_age_seconds == 15.5


# ---------------------------------------------------------------------------
# D: InFlightTaskContinuityRecord round-trip
# ---------------------------------------------------------------------------

class TestGroupD_InFlightTaskContinuityRecordRoundTrip:
    def test_D01_to_dict_keys(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityRecord,
            TaskContinuityStatus,
        )
        rec = InFlightTaskContinuityRecord(
            task_id="tid1",
            continuity_status=TaskContinuityStatus.resumed,
            reason="already live",
        )
        d = rec.to_dict()
        for key in ("task_id", "trace_id", "disposition", "continuity_status",
                    "reason", "device_id", "snapshot_age_seconds", "snapshot_id",
                    "evaluated_at"):
            assert key in d, f"Missing key: {key}"
        assert d["continuity_status"] == "resumed"

    def test_D02_from_dict_round_trip(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityRecord,
            TaskContinuityStatus,
        )
        original = InFlightTaskContinuityRecord(
            task_id="tid2",
            disposition="replay_only",
            continuity_status=TaskContinuityStatus.recoverable,
            reason="routing pending",
            snapshot_age_seconds=5.0,
        )
        restored = InFlightTaskContinuityRecord.from_dict(original.to_dict())
        assert restored.task_id == "tid2"
        assert restored.continuity_status == TaskContinuityStatus.recoverable
        assert restored.snapshot_age_seconds == 5.0

    def test_D03_from_dict_unknown_status_defaults_to_ambiguous(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityRecord,
            TaskContinuityStatus,
        )
        rec = InFlightTaskContinuityRecord.from_dict({"continuity_status": "unknown_value"})
        assert rec.continuity_status == TaskContinuityStatus.ambiguous


# ---------------------------------------------------------------------------
# E: TaskContinuityReport computed properties
# ---------------------------------------------------------------------------

class TestGroupE_TaskContinuityReportProperties:
    def test_E01_state_restored_is_resumed_plus_recoverable(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=2, recoverable_count=3)
        assert r.state_restored_count == 5

    def test_E02_continuity_restored_is_resumed_only(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=2, recoverable_count=3)
        assert r.continuity_restored_count == 2

    def test_E03_continuity_gap_is_recoverable_count(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=2, recoverable_count=3)
        assert r.continuity_gap_count == 3

    def test_E04_has_unrecovered_when_recoverable(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(recoverable_count=1)
        assert r.has_unrecovered_tasks is True

    def test_E05_has_unrecovered_when_interrupted(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(interrupted_count=1)
        assert r.has_unrecovered_tasks is True

    def test_E06_no_unrecovered_when_all_resumed_or_abandoned(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=2, abandoned_count=1)
        assert r.has_unrecovered_tasks is False

    def test_E07_has_ambiguous_when_ambiguous(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(ambiguous_count=1)
        assert r.has_ambiguous_tasks is True

    def test_E08_has_ambiguous_when_needs_reconcile(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(needs_reconcile_count=1)
        assert r.has_ambiguous_tasks is True

    def test_E09_zero_gap_when_only_resumed(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=3)
        assert r.continuity_gap_count == 0


# ---------------------------------------------------------------------------
# F: TaskContinuityReport round-trip
# ---------------------------------------------------------------------------

class TestGroupF_TaskContinuityReportRoundTrip:
    def test_F01_to_dict_includes_computed_props(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = TaskContinuityReport(resumed_count=1, recoverable_count=2)
        d = r.to_dict()
        assert d["state_restored_count"] == 3
        assert d["continuity_restored_count"] == 1
        assert d["continuity_gap_count"] == 2
        assert d["has_unrecovered_tasks"] is True
        assert d["has_ambiguous_tasks"] is False

    def test_F02_from_dict_round_trip(self):
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r1 = TaskContinuityReport(
            resumed_count=2,
            recoverable_count=1,
            interrupted_count=1,
            abandoned_count=1,
            needs_reconcile_count=0,
            ambiguous_count=0,
            total_evaluated=5,
        )
        d = r1.to_dict()
        r2 = TaskContinuityReport.from_dict(d)
        assert r2.resumed_count == 2
        assert r2.recoverable_count == 1
        assert r2.total_evaluated == 5


# ---------------------------------------------------------------------------
# G: resumed status (task already in live registry)
# ---------------------------------------------------------------------------

class TestGroupG_ResumedStatus:
    def test_G01_task_in_live_registry_gets_resumed(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        contract = InFlightTaskContinuityContract()
        report = contract.evaluate(
            [rec],
            already_pending_ids={tid},
            dispatched_ids=set(),
        )
        assert report.resumed_count == 1
        assert report.continuity_restored_count == 1
        assert report.continuity_gap_count == 0
        assert report.records[0].continuity_status == TaskContinuityStatus.resumed

    def test_G02_resumed_task_has_zero_continuity_gap(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        tids = [_task_id() for _ in range(3)]
        records = [_make_restored_record(task_id=t) for t in tids]
        report = InFlightTaskContinuityContract().evaluate(
            records,
            already_pending_ids=set(tids),
        )
        assert report.continuity_gap_count == 0
        assert report.has_unrecovered_tasks is False


# ---------------------------------------------------------------------------
# H: recoverable status (RESUMABLE with dispatch taken)
# ---------------------------------------------------------------------------

class TestGroupH_RecoverableStatusResumable:
    def test_H01_resumable_with_dispatch_taken_is_recoverable(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids=set(),
            dispatched_ids={tid},
        )
        assert report.recoverable_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.recoverable

    def test_H02_state_restored_but_continuity_gap_is_positive(self):
        """Critical: state restored ≠ continuity restored."""
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids=set(),
            dispatched_ids={tid},
        )
        # State is restored (task in registry) but continuity is NOT confirmed
        assert report.state_restored_count == 1
        assert report.continuity_restored_count == 0
        assert report.continuity_gap_count == 1

    def test_H03_resumable_without_dispatch_still_recoverable_not_resumed(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids=set(),
            dispatched_ids=set(),  # dispatch NOT taken
        )
        # Still recoverable but dispatch not confirmed
        assert report.records[0].continuity_status == TaskContinuityStatus.recoverable
        assert report.continuity_gap_count == 1


# ---------------------------------------------------------------------------
# I: recoverable status (REPLAY_ONLY with dispatch taken)
# ---------------------------------------------------------------------------

class TestGroupI_RecoverableStatusReplayOnly:
    def test_I01_replay_only_with_dispatch_is_recoverable(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(
            task_id=tid, disposition="replay_only", owner="routing"
        )
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            dispatched_ids={tid},
        )
        assert report.records[0].continuity_status == TaskContinuityStatus.recoverable
        assert report.continuity_gap_count == 1


# ---------------------------------------------------------------------------
# J: interrupted status (REISSUABLE)
# ---------------------------------------------------------------------------

class TestGroupJ_InterruptedStatusReissuable:
    def test_J01_reissuable_task_is_interrupted(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(
            task_id=tid, disposition="reissuable", owner="gateway_ingress"
        )
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.interrupted_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.interrupted

    def test_J02_reissuable_is_not_positive(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        assert TaskContinuityStatus.interrupted.is_positive is False


# ---------------------------------------------------------------------------
# K: abandoned status (TERMINAL_ON_INTERRUPT)
# ---------------------------------------------------------------------------

class TestGroupK_AbandonedStatusTerminal:
    def test_K01_terminal_on_interrupt_is_abandoned(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(
            task_id=tid,
            disposition="terminal_on_interrupt",
            owner="result_completion",
        )
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.abandoned_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.abandoned

    def test_K02_abandoned_has_zero_state_restored(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        rec = _make_restored_record(
            disposition="terminal_on_interrupt", owner="result_completion"
        )
        report = InFlightTaskContinuityContract().evaluate([rec])
        # abandoned tasks are not in state_restored
        assert report.state_restored_count == 0


# ---------------------------------------------------------------------------
# L: ambiguous status (empty task_id)
# ---------------------------------------------------------------------------

class TestGroupL_AmbiguousEmptyTaskId:
    def test_L01_empty_task_id_is_ambiguous(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        rec = _make_restored_record(task_id="", disposition="resumable", auto_task_id=False)
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.ambiguous_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.ambiguous

    def test_L02_ambiguous_not_included_in_state_restored(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        rec = _make_restored_record(task_id="", disposition="resumable", auto_task_id=False)
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.state_restored_count == 0


# ---------------------------------------------------------------------------
# M: needs_reconcile for duplicate task_id
# ---------------------------------------------------------------------------

class TestGroupM_NeedsReconcileDuplicate:
    def test_M01_duplicate_task_id_yields_needs_reconcile(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec1 = _make_restored_record(task_id=tid, disposition="resumable")
        rec2 = _make_restored_record(task_id=tid, disposition="replay_only")
        report = InFlightTaskContinuityContract().evaluate([rec1, rec2])
        assert report.needs_reconcile_count == 2
        for entry in report.records:
            assert entry.continuity_status == TaskContinuityStatus.needs_reconcile

    def test_M02_duplicate_not_in_state_restored(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        tid = _task_id()
        recs = [_make_restored_record(task_id=tid) for _ in range(2)]
        report = InFlightTaskContinuityContract().evaluate(recs)
        assert report.state_restored_count == 0

    def test_M03_already_pending_does_not_override_duplicate_reconcile(self):
        """Duplicate task_id in snapshot → needs_reconcile even if live-pending.

        See DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY.
        """
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        recs = [_make_restored_record(task_id=tid) for _ in range(2)]
        report = InFlightTaskContinuityContract().evaluate(
            recs, already_pending_ids={tid}
        )
        # Despite being in live registry, duplicates must be needs_reconcile
        for entry in report.records:
            assert entry.continuity_status == TaskContinuityStatus.needs_reconcile


# ---------------------------------------------------------------------------
# N: needs_reconcile for stale record
# ---------------------------------------------------------------------------

class TestGroupN_NeedsReconcileStale:
    def test_N01_stale_record_yields_needs_reconcile(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
            STALE_SNAPSHOT_THRESHOLD_SECONDS,
        )
        tid = _task_id()
        # Create record older than threshold
        stale_ts = time.time() - STALE_SNAPSHOT_THRESHOLD_SECONDS - 10
        rec = _make_restored_record(
            task_id=tid, disposition="resumable", registered_at=stale_ts
        )
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids=set(),
            dispatched_ids={tid},
            snapshot_timestamp=stale_ts,
        )
        assert report.needs_reconcile_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.needs_reconcile

    def test_N02_non_stale_record_is_not_needs_reconcile(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            dispatched_ids={tid},
            snapshot_timestamp=time.time(),
        )
        assert report.records[0].continuity_status == TaskContinuityStatus.recoverable

    def test_N03_custom_stale_threshold(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        # Record 5s old with 3s threshold → stale
        old_ts = time.time() - 5.0
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = InFlightTaskContinuityContract(
            stale_threshold_seconds=3.0
        ).evaluate(
            [rec],
            snapshot_timestamp=old_ts,
        )
        assert report.records[0].continuity_status == TaskContinuityStatus.needs_reconcile


# ---------------------------------------------------------------------------
# O: state_restored ≠ continuity_restored gap
# ---------------------------------------------------------------------------

class TestGroupO_ContinuityGap:
    def test_O01_gap_equals_recoverable_count(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        tids = [_task_id() for _ in range(3)]
        # 1 resumed (already live), 2 recoverable (dispatch taken, not live)
        already_pending = {tids[0]}
        dispatched = {tids[1], tids[2]}
        records = [
            _make_restored_record(task_id=tids[0], disposition="resumable"),
            _make_restored_record(task_id=tids[1], disposition="resumable"),
            _make_restored_record(task_id=tids[2], disposition="replay_only"),
        ]
        report = InFlightTaskContinuityContract().evaluate(
            records,
            already_pending_ids=already_pending,
            dispatched_ids=dispatched,
        )
        assert report.resumed_count == 1
        assert report.recoverable_count == 2
        assert report.continuity_gap_count == 2
        assert report.state_restored_count == 3
        assert report.continuity_restored_count == 1

    def test_O02_all_resumed_gives_zero_gap(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        tids = [_task_id() for _ in range(3)]
        records = [_make_restored_record(task_id=t) for t in tids]
        report = InFlightTaskContinuityContract().evaluate(
            records, already_pending_ids=set(tids)
        )
        assert report.continuity_gap_count == 0
        assert report.has_unrecovered_tasks is False


# ---------------------------------------------------------------------------
# P: ambiguous MUST NOT be upgraded
# ---------------------------------------------------------------------------

class TestGroupP_AmbiguousMustNotBeUpgraded:
    def test_P01_ambiguous_record_cannot_be_resumable(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        # Empty task_id → ambiguous, even if in already_pending and dispatched
        rec = _make_restored_record(task_id="", disposition="resumable", auto_task_id=False)
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids={""},   # even if somehow "" was pending
            dispatched_ids={""},
        )
        # Still ambiguous — policy MUST NOT be overridden
        assert report.records[0].continuity_status == TaskContinuityStatus.ambiguous

    def test_P02_has_ambiguous_tasks_true(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        rec = _make_restored_record(task_id="", disposition="resumable", auto_task_id=False)
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.has_ambiguous_tasks is True


# ---------------------------------------------------------------------------
# Q: REISSUABLE is interrupted even when dispatch was taken
# ---------------------------------------------------------------------------

class TestGroupQ_ReissuableAlwaysInterrupted:
    def test_Q01_reissuable_is_interrupted_not_recoverable(self):
        """INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY enforcement."""
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(
            task_id=tid, disposition="reissuable", owner="gateway_ingress"
        )
        # Even if dispatch was taken and task was already pending
        report = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids={tid},  # in live registry
            dispatched_ids={tid},        # dispatch action taken
        )
        # REISSUABLE with live pending → first hit is `resumed` rule?
        # NO — the already_pending check comes BEFORE the disposition check,
        # but we still need to verify the rule. Let's check: since
        # already_pending_ids contains the tid, it should get `resumed`.
        # The intent of INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY is that
        # REISSUABLE tasks that are NOT already live should be interrupted.
        # If a task is already live (in already_pending), it doesn't matter
        # what its disposition is — live state wins.
        # This test verifies the policy for the more common case: not already live.
        report2 = InFlightTaskContinuityContract().evaluate(
            [rec],
            already_pending_ids=set(),  # not in live registry
            dispatched_ids={tid},
        )
        assert report2.records[0].continuity_status == TaskContinuityStatus.interrupted

    def test_Q02_reissuable_requires_external_action(self):
        from core.inflight_task_continuity_contract import TaskContinuityStatus
        assert TaskContinuityStatus.interrupted.requires_action is True


# ---------------------------------------------------------------------------
# R: unknown disposition yields ambiguous
# ---------------------------------------------------------------------------

class TestGroupR_UnknownDispositionAmbiguous:
    def test_R01_unknown_disposition_string_is_ambiguous(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="future_unknown_value")
        report = InFlightTaskContinuityContract().evaluate([rec])
        assert report.records[0].continuity_status == TaskContinuityStatus.ambiguous
        assert report.ambiguous_count == 1


# ---------------------------------------------------------------------------
# S: build_continuity_report convenience function
# ---------------------------------------------------------------------------

class TestGroupS_BuildContinuityReportFunction:
    def test_S01_returns_task_continuity_report(self):
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityReport,
        )
        result = build_continuity_report([])
        assert isinstance(result, TaskContinuityReport)

    def test_S02_passes_through_parameters(self):
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityStatus,
        )
        tid = _task_id()
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = build_continuity_report(
            [rec], already_pending_ids={tid}
        )
        assert report.records[0].continuity_status == TaskContinuityStatus.resumed

    def test_S03_stale_threshold_override(self):
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityStatus,
        )
        tid = _task_id()
        old_ts = time.time() - 10.0
        rec = _make_restored_record(task_id=tid, disposition="resumable")
        report = build_continuity_report(
            [rec],
            snapshot_timestamp=old_ts,
            stale_threshold_seconds=5.0,
        )
        assert report.records[0].continuity_status == TaskContinuityStatus.needs_reconcile


# ---------------------------------------------------------------------------
# T: RuntimeRecoveryReport has continuity_report field
# ---------------------------------------------------------------------------

class TestGroupT_RuntimeRecoveryReportHasContinuityReport:
    def test_T01_continuity_report_field_exists(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        assert hasattr(r, "continuity_report")
        assert r.continuity_report is None

    def test_T02_continuity_report_can_be_set(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = RuntimeRecoveryReport()
        cr = TaskContinuityReport(resumed_count=1)
        r.continuity_report = cr
        assert r.continuity_report is cr


# ---------------------------------------------------------------------------
# U: RuntimeRecoveryReport.to_dict includes continuity_report
# ---------------------------------------------------------------------------

class TestGroupU_RuntimeRecoveryReportToDict:
    def test_U01_to_dict_has_continuity_report_key(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        r = RuntimeRecoveryReport()
        d = r.to_dict()
        assert "continuity_report" in d
        assert d["continuity_report"] is None

    def test_U02_to_dict_serialises_continuity_report(self):
        from core.runtime_restart_recovery import RuntimeRecoveryReport
        from core.inflight_task_continuity_contract import TaskContinuityReport
        r = RuntimeRecoveryReport()
        r.continuity_report = TaskContinuityReport(resumed_count=2, total_evaluated=2)
        d = r.to_dict()
        assert d["continuity_report"] is not None
        assert d["continuity_report"]["resumed_count"] == 2


# ---------------------------------------------------------------------------
# V: RecoveryTruthSurface in_flight_continuity returns observed
# ---------------------------------------------------------------------------

class TestGroupV_RecoveryTruthSurface:
    def test_V01_in_flight_continuity_entry_is_observed_with_contract(self):
        from core.recovery_truth_surface import (
            build_recovery_truth_report,
            RecoveryTruthDimension,
            RecoveryTruthStatus,
        )
        report = build_recovery_truth_report()
        entry = report.get_entry(
            RecoveryTruthDimension.in_flight_task_continuity_preserved
        )
        assert entry is not None
        # With InFlightTaskContinuityContract present, status should be observed
        assert entry.status == RecoveryTruthStatus.observed

    def test_V02_inflight_contract_in_supporting_modules(self):
        from core.recovery_truth_surface import (
            build_recovery_truth_report,
            RecoveryTruthDimension,
        )
        report = build_recovery_truth_report()
        entry = report.get_entry(
            RecoveryTruthDimension.in_flight_task_continuity_preserved
        )
        assert entry is not None
        assert "core.inflight_task_continuity_contract" in entry.supporting_modules


# ---------------------------------------------------------------------------
# W: Full restart simulation — RESUMABLE task → recoverable
# ---------------------------------------------------------------------------

class TestGroupW_RestartSimulationResumable:
    def setup_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def teardown_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def test_W01_resumable_task_yields_continuity_gap_after_restart(self, tmp_path):
        """After restart, RESUMABLE task is recoverable (not resumed).

        This test validates that the system does NOT claim continuity restored
        for a task that was interrupted — the continuity_gap_count > 0.
        """
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            save_task_lifecycle_snapshot,
            restore_inflight_tasks_from_snapshot,
        )
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityStatus,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        tid = _task_id()
        records = [
            {
                "task_id": tid,
                "trace_id": _trace_id(),
                "session_id": "sess-001",
                "owner": "device_dispatch",
                "state": "dispatched",
                "created_at": time.time(),
                "updated_at": time.time(),
                "device_id": "dev-001",
            }
        ]
        save_task_lifecycle_snapshot(records, store=store)

        # Simulated restart: restore records
        restored = restore_inflight_tasks_from_snapshot(store=store)
        assert len(restored) == 1

        # Build continuity report: dispatch taken, not already live
        report = build_continuity_report(
            restored,
            already_pending_ids=set(),
            dispatched_ids={tid},
        )
        # CRITICAL: state_restored=1, continuity_restored=0, gap=1
        assert report.state_restored_count == 1
        assert report.continuity_restored_count == 0
        assert report.continuity_gap_count == 1
        assert report.records[0].continuity_status == TaskContinuityStatus.recoverable
        assert report.has_unrecovered_tasks is True


# ---------------------------------------------------------------------------
# X: Full restart simulation — already-live task → resumed
# ---------------------------------------------------------------------------

class TestGroupX_RestartSimulationAlreadyLive:
    def setup_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def teardown_method(self):
        from core.task_lifecycle_persistence import reset_task_lifecycle_store
        reset_task_lifecycle_store()

    def test_X01_already_live_task_gets_resumed(self, tmp_path):
        """Task already in live registry at recovery time → resumed."""
        from core.task_lifecycle_persistence import (
            TaskLifecyclePersistenceStore,
            save_task_lifecycle_snapshot,
            restore_inflight_tasks_from_snapshot,
        )
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityStatus,
        )
        store = TaskLifecyclePersistenceStore(
            store_path=str(tmp_path / "tl.json")
        )
        tid = _task_id()
        save_task_lifecycle_snapshot(
            [{"task_id": tid, "owner": "device_dispatch",
              "trace_id": _trace_id(), "created_at": time.time(),
              "updated_at": time.time()}],
            store=store,
        )
        restored = restore_inflight_tasks_from_snapshot(store=store)

        # Simulate: task was already live when recovery ran
        report = build_continuity_report(
            restored,
            already_pending_ids={tid},
            dispatched_ids=set(),
        )
        assert report.resumed_count == 1
        assert report.continuity_gap_count == 0
        entry = report.records[0]
        assert entry.continuity_status == TaskContinuityStatus.resumed
        assert report.has_unrecovered_tasks is False


# ---------------------------------------------------------------------------
# Y: Mixed scenario — multiple tasks across all status types
# ---------------------------------------------------------------------------

class TestGroupY_MixedScenario:
    def test_Y01_mixed_statuses_all_classified(self):
        from core.inflight_task_continuity_contract import (
            InFlightTaskContinuityContract,
            TaskContinuityStatus,
        )
        t_resumed = _task_id()
        t_recoverable = _task_id()
        t_interrupted = _task_id()
        t_abandoned = _task_id()
        t_ambiguous = ""  # empty
        t_dup = _task_id()

        records = [
            _make_restored_record(task_id=t_resumed, disposition="resumable"),
            _make_restored_record(task_id=t_recoverable, disposition="resumable"),
            _make_restored_record(task_id=t_interrupted, disposition="reissuable"),
            _make_restored_record(task_id=t_abandoned, disposition="terminal_on_interrupt"),
            _make_restored_record(task_id=t_ambiguous, disposition="resumable", auto_task_id=False),
            _make_restored_record(task_id=t_dup, disposition="resumable"),
            _make_restored_record(task_id=t_dup, disposition="replay_only"),
        ]
        report = InFlightTaskContinuityContract().evaluate(
            records,
            already_pending_ids={t_resumed},
            dispatched_ids={t_recoverable, t_interrupted},
        )

        assert report.resumed_count == 1
        assert report.recoverable_count == 1
        assert report.interrupted_count == 1
        assert report.abandoned_count == 1
        assert report.ambiguous_count == 1
        assert report.needs_reconcile_count == 2  # two duplicate entries
        assert report.total_evaluated == 7

        # Verify continuity gap
        assert report.continuity_gap_count == 1  # 1 recoverable
        assert report.has_unrecovered_tasks is True
        assert report.has_ambiguous_tasks is True

    def test_Y02_mixed_to_dict_is_consistent(self):
        from core.inflight_task_continuity_contract import InFlightTaskContinuityContract
        records = [
            _make_restored_record(disposition="resumable"),
            _make_restored_record(disposition="terminal_on_interrupt"),
        ]
        report = InFlightTaskContinuityContract().evaluate(records)
        d = report.to_dict()
        # All computed props should be in dict
        assert "continuity_gap_count" in d
        assert "has_unrecovered_tasks" in d
        assert "has_ambiguous_tasks" in d
        assert isinstance(d["records"], list)
        assert len(d["records"]) == 2


# ---------------------------------------------------------------------------
# Z: Empty snapshot
# ---------------------------------------------------------------------------

class TestGroupZ_EmptySnapshot:
    def test_Z01_empty_snapshot_produces_valid_report(self):
        from core.inflight_task_continuity_contract import (
            build_continuity_report,
            TaskContinuityReport,
        )
        report = build_continuity_report([])
        assert isinstance(report, TaskContinuityReport)
        assert report.total_evaluated == 0
        assert report.resumed_count == 0
        assert report.recoverable_count == 0
        assert report.continuity_gap_count == 0
        assert report.has_unrecovered_tasks is False
        assert report.has_ambiguous_tasks is False
        assert report.records == []

    def test_Z02_empty_report_to_dict_is_serialisable(self):
        import json
        from core.inflight_task_continuity_contract import build_continuity_report
        report = build_continuity_report([])
        # Should not raise
        serialised = json.dumps(report.to_dict())
        assert len(serialised) > 0
