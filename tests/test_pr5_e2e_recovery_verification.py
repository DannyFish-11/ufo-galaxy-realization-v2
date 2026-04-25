#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_e2e_recovery_verification.py
=============================================
PR-5: End-to-End Recovery Verification Suite.

This suite validates the complete V2 continuity/recovery/offline-durability
story across the interaction between all relevant modules:

  - FlowContinuityCoordinator (PR-3)
  - DelegatedFlowRecoveryCoordinator (PR-4)
  - RuntimeRestartRecoveryCoordinator (PR-5)
  - ContinuityRecoveryClosure (PR-5)
  - OfflineQueueRecoveryBoundary (PR-5)

Coverage
--------
A  — ContinuityRecoveryClosure + FlowContinuityCoordinator integration:
     reconnect decision is exercised end-to-end without exception.
B  — ContinuityRecoveryClosure + DelegatedFlowRecoveryCoordinator integration:
     checkpoint replay decision exercised end-to-end without exception.
C  — ContinuityRecoveryClosure + DelegatedFlowRecoveryCoordinator integration:
     partial result decision exercised end-to-end without exception.
D  — ContinuityRecoveryClosure + FlowContinuityCoordinator integration:
     stale identity rejection exercised end-to-end without exception.
E  — ContinuityRecoveryClosure + FlowContinuityCoordinator integration:
     duplicate signal suppression exercised end-to-end without exception.
F  — OfflineQueueRecoveryBoundary: replay ordering preserved across a realistic
     out-of-order batch (simulating offline queue drain on reconnect).
G  — OfflineQueueRecoveryBoundary: duplicate suppression prevents double-apply
     when Android sends the same signal twice after reconnect.
H  — OfflineQueueRecoveryBoundary: terminal-state guard prevents stale results
     from reopening a completed flow.
I  — Full recovery closure report: generated_at is recent (within 60 seconds).
J  — Full recovery closure report: outcomes list matches RECOVERY_DECISION_MATRIX.
K  — Full recovery closure report: policy_sentinels dict is non-empty.
L  — FlowContinuityCoordinator + DelegatedFlowRecoveryCoordinator: V2 restart
     recovery decision exercised end-to-end without exception.
M  — Canonical recovery decision matrix: all entries serialise to JSON correctly.
N  — Canonical recovery decision matrix: no entry has deferred=True (all closed in PR-5).
O  — Recovery closure report: scenarios_advisory count is non-negative integer.
P  — Offline queue + terminal guard: accepted entries from pre-terminal batch are
     not present after a terminal-guarded replay.
Q  — ContinuityRecoveryClosure validate_all: produces a complete report with no
     failed scenarios.
R  — OfflineQueueRecoveryBoundary snapshot: to_json() output is valid JSON.
S  — Recovery decision matrix: v2_process_restart entry has 'RuntimeRestartRecovery'
     in owning_coordinator.
T  — Recovery decision matrix: partial_result_after_terminal entry references the
     stale suppression policy.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import List

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_boundary():
    from core.offline_durability_closure import OfflineQueueRecoveryBoundary
    return OfflineQueueRecoveryBoundary(capacity=64)


def _entry(key: str, seq: int, payload: dict = None):
    from core.offline_durability_closure import OfflineQueueEntry
    return OfflineQueueEntry(
        idempotency_key=key,
        sequence=seq,
        payload=payload or {},
    )


def _fresh_closure():
    from core.continuity_recovery_closure import ContinuityRecoveryClosure
    return ContinuityRecoveryClosure()


# ---------------------------------------------------------------------------
# A — FlowContinuityCoordinator reconnect decision end-to-end
# ---------------------------------------------------------------------------


class TestE2EReconnect:
    def test_reconnect_decision_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.android_transport_reconnect
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0
        # Verdict is either passed or advisory (depending on coordinator availability)
        outcome = report.outcomes[0]
        assert outcome.verdict in (
            RecoveryClosureVerdict.passed,
            RecoveryClosureVerdict.advisory,
        )


# ---------------------------------------------------------------------------
# B — DelegatedFlowRecoveryCoordinator checkpoint replay end-to-end
# ---------------------------------------------------------------------------


class TestE2ECheckpointReplay:
    def test_checkpoint_replay_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.delegated_flow_checkpoint_replay
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0
        outcome = report.outcomes[0]
        assert outcome.verdict in (
            RecoveryClosureVerdict.passed,
            RecoveryClosureVerdict.advisory,
        )


# ---------------------------------------------------------------------------
# C — DelegatedFlowRecoveryCoordinator partial result end-to-end
# ---------------------------------------------------------------------------


class TestE2EPartialResult:
    def test_partial_result_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.delegated_flow_partial_result
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# D — FlowContinuityCoordinator stale identity end-to-end
# ---------------------------------------------------------------------------


class TestE2EStaleIdentity:
    def test_stale_identity_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.stale_identity_signal
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# E — FlowContinuityCoordinator duplicate signal end-to-end
# ---------------------------------------------------------------------------


class TestE2EDuplicateSignal:
    def test_duplicate_signal_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.duplicate_signal_after_reconnect
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# F — OfflineQueueRecoveryBoundary: replay ordering preserved
# ---------------------------------------------------------------------------


class TestOfflineReplayOrdering:
    def test_realistic_out_of_order_batch(self):
        b = _fresh_boundary()
        # Simulate 8 out-of-order entries (Android queued them, drain is unordered)
        batch = [
            _entry("sig_008", 8, payload={"event": "result_final"}),
            _entry("sig_003", 3, payload={"event": "step_complete"}),
            _entry("sig_001", 1, payload={"event": "task_started"}),
            _entry("sig_005", 5, payload={"event": "partial_result"}),
            _entry("sig_002", 2, payload={"event": "dispatch_ack"}),
            _entry("sig_007", 7, payload={"event": "execution_complete"}),
            _entry("sig_004", 4, payload={"event": "step_started"}),
            _entry("sig_006", 6, payload={"event": "intermediate_result"}),
        ]
        result = list(b.replay_ordered(batch))
        # All 8 are unique → all accepted
        assert len(result) == 8
        # Must be in ascending sequence order
        seqs = [e.sequence for e in result]
        assert seqs == sorted(seqs)
        assert seqs == [1, 2, 3, 4, 5, 6, 7, 8]


# ---------------------------------------------------------------------------
# G — OfflineQueueRecoveryBoundary: duplicate suppression
# ---------------------------------------------------------------------------


class TestOfflineDuplicateSuppression:
    def test_android_sends_same_signal_twice(self):
        b = _fresh_boundary()
        # Android sends the same "dispatch_ack" twice (e.g. retry after partial delivery)
        batch = [
            _entry("dispatch_ack_flow_42", 1),
            _entry("execution_complete_flow_42", 2),
            _entry("dispatch_ack_flow_42", 3),  # duplicate — must be suppressed
        ]
        result = list(b.replay_ordered(batch))
        assert len(result) == 2
        assert [e.idempotency_key for e in result] == [
            "dispatch_ack_flow_42",
            "execution_complete_flow_42",
        ]
        snap = b.build_snapshot()
        assert snap.total_rejected_duplicate == 1


# ---------------------------------------------------------------------------
# H — OfflineQueueRecoveryBoundary: terminal-state guard
# ---------------------------------------------------------------------------


class TestOfflineTerminalGuard:
    def test_stale_results_rejected_after_terminal_state(self):
        b = _fresh_boundary()
        # The flow already completed (canonical_is_terminal=True)
        stale_batch = [
            _entry("result_delayed_1", 1),
            _entry("result_delayed_2", 2),
        ]
        result = list(b.replay_ordered(stale_batch, canonical_is_terminal=True))
        assert result == []
        snap = b.build_snapshot()
        assert snap.total_rejected_stale_terminal == 2
        assert snap.total_accepted == 0


# ---------------------------------------------------------------------------
# I — Full closure report: generated_at is recent
# ---------------------------------------------------------------------------


class TestClosureReportRecency:
    def test_generated_at_is_recent(self):
        report = _fresh_closure().validate_all()
        now = time.time()
        assert now - report.generated_at < 60.0


# ---------------------------------------------------------------------------
# J — Full closure report: outcomes match matrix
# ---------------------------------------------------------------------------


class TestClosureReportOutcomes:
    def test_outcomes_match_matrix_length(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        report = _fresh_closure().validate_all()
        assert len(report.outcomes) == len(RECOVERY_DECISION_MATRIX)


# ---------------------------------------------------------------------------
# K — Full closure report: policy_sentinels is non-empty
# ---------------------------------------------------------------------------


class TestClosureReportPolicySentinels:
    def test_policy_sentinels_non_empty(self):
        report = _fresh_closure().validate_all()
        assert len(report.policy_sentinels) > 0
        for key, value in report.policy_sentinels.items():
            assert isinstance(key, str) and len(key) > 0
            assert isinstance(value, str) and len(value) > 0


# ---------------------------------------------------------------------------
# L — FlowContinuityCoordinator + DelegatedFlowRecoveryCoordinator: V2 restart
# ---------------------------------------------------------------------------


class TestE2EV2RestartRecovery:
    def test_v2_restart_recovery_exercised_end_to_end(self):
        from core.continuity_recovery_closure import (
            ContinuityRecoveryClosure,
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
            RecoveryClosureVerdict,
        )
        matrix = [
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.v2_process_restart
        ]
        report = ContinuityRecoveryClosure(matrix=matrix).validate_all()
        assert report.scenarios_total == 1
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# M — Matrix entries serialise to JSON correctly
# ---------------------------------------------------------------------------


class TestMatrixSerialisation:
    def test_all_entries_serialise_to_json(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        for entry in RECOVERY_DECISION_MATRIX:
            parsed = json.loads(entry.to_json())
            assert "scenario" in parsed
            assert "owning_coordinator" in parsed
            assert "canonical_decision" in parsed


# ---------------------------------------------------------------------------
# N — No entry has deferred=True (all closed in PR-5)
# ---------------------------------------------------------------------------


class TestNoEntriesDeferred:
    def test_all_entries_closed(self):
        from core.continuity_recovery_closure import RECOVERY_DECISION_MATRIX
        deferred = [e for e in RECOVERY_DECISION_MATRIX if e.deferred]
        assert len(deferred) == 0, (
            f"Expected no deferred entries but found: {[e.scenario.value for e in deferred]}"
        )


# ---------------------------------------------------------------------------
# O — Recovery closure report: scenarios_advisory is non-negative
# ---------------------------------------------------------------------------


class TestClosureReportAdvisory:
    def test_scenarios_advisory_is_non_negative(self):
        report = _fresh_closure().validate_all()
        assert report.scenarios_advisory >= 0


# ---------------------------------------------------------------------------
# P — Offline queue: pre-terminal batch accepted, then terminal rejects new batch
# ---------------------------------------------------------------------------


class TestOfflineTerminalAfterSuccess:
    def test_pre_terminal_accepted_terminal_rejects_subsequent(self):
        b = _fresh_boundary()
        # Pre-terminal batch (accepted normally)
        pre = [_entry("step1", 1), _entry("step2", 2)]
        result_pre = list(b.replay_ordered(pre))
        assert len(result_pre) == 2

        # Now canonical state is terminal; new batch must be rejected
        post = [_entry("late_result", 3)]
        result_post = list(b.replay_ordered(post, canonical_is_terminal=True))
        assert result_post == []

        snap = b.build_snapshot()
        assert snap.total_accepted == 2
        assert snap.total_rejected_stale_terminal == 1


# ---------------------------------------------------------------------------
# Q — ContinuityRecoveryClosure validate_all: no failed scenarios
# ---------------------------------------------------------------------------


class TestFullClosureNoFailed:
    def test_validate_all_no_failed_scenarios(self):
        report = _fresh_closure().validate_all()
        assert report.scenarios_failed == 0


# ---------------------------------------------------------------------------
# R — OfflineQueueRecoveryBoundary snapshot: to_json() is valid JSON
# ---------------------------------------------------------------------------


class TestSnapshotJson:
    def test_snapshot_to_json_is_valid(self):
        b = _fresh_boundary()
        list(b.replay_ordered([_entry("k1", 1), _entry("k1", 2)]))
        snap = b.build_snapshot()
        data = json.loads(snap.to_json())
        assert data["total_entries_processed"] == 2
        assert data["total_accepted"] == 1
        assert data["total_rejected_duplicate"] == 1


# ---------------------------------------------------------------------------
# S — Matrix: v2_process_restart entry references RuntimeRestartRecovery
# ---------------------------------------------------------------------------


class TestMatrixV2RestartEntry:
    def test_v2_process_restart_references_runtime_restart(self):
        from core.continuity_recovery_closure import (
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
        )
        entry = next(
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.v2_process_restart
        )
        assert "RuntimeRestartRecovery" in entry.owning_coordinator


# ---------------------------------------------------------------------------
# T — Matrix: partial_result_after_terminal references stale suppression policy
# ---------------------------------------------------------------------------


class TestMatrixPartialAfterTerminalEntry:
    def test_partial_result_after_terminal_references_suppression_policy(self):
        from core.continuity_recovery_closure import (
            RECOVERY_DECISION_MATRIX,
            RecoveryScenario,
        )
        entry = next(
            e for e in RECOVERY_DECISION_MATRIX
            if e.scenario == RecoveryScenario.partial_result_after_terminal
        )
        # Should reference stale replay suppression
        assert (
            "STALE" in entry.policy_reference.upper()
            or "SUPPRESSION" in entry.policy_reference.upper()
            or "stale" in entry.notes.lower()
        )
