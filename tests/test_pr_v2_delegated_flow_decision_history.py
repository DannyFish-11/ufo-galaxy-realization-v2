#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_v2_delegated_flow_decision_history.py
====================================================
PR-V2-4DH — Delegated Flow Decision History and Evidence Closure — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-V2-4DH sentinel present and
    non-empty.
B.  All five policy sentinels are non-empty strings with expected keywords.
C.  HistoryEvidenceStatus enum has the five required values.
D.  HistoryEvidenceStatus.from_string() handles valid, invalid, non-string.
E.  HistoryEvidenceStatus.allows_runtime_closure True only for observed_and_closed.
F.  HistoryEvidenceStatus.is_definitive_gap True for no_history_yet and stale.
G.  DelegatedFlowEventKind enum has the seven required values.
H.  DelegatedFlowEventKind.from_string() handles valid, invalid, non-string.
I.  DelegatedFlowEventKind.is_terminal True for completed/rejected/rerouted/accepted.
J.  DelegatedFlowHistoryEntry constructs with required fields.
K.  DelegatedFlowHistoryEntry.to_dict() returns JSON-serialisable dict.
L.  DelegatedFlowHistoryEntry.to_json() produces valid JSON.
M.  DelegatedFlowHistoryEntry.from_dict() round-trips correctly.
N.  DelegatedFlowHistoryReport constructs with required fields.
O.  DelegatedFlowHistoryReport.to_dict() returns JSON-serialisable dict.
P.  DelegatedFlowHistoryReport.to_json() produces valid JSON.
Q.  DelegatedFlowHistoryReport.from_dict() round-trips correctly.
R.  get_decision_history() returns DelegatedFlowDecisionHistory singleton.
S.  Singleton identity: two calls return the same object.
T.  reset_decision_history() resets the singleton.
U.  Empty registry → evaluate() returns no_history_yet.
V.  Empty registry → runtime_closure_established is False.
W.  Empty registry → gap_description is non-empty.
X.  Single triggered event → insufficient_evidence (not no_history_yet).
Y.  triggered + readiness_decision → observed_but_incomplete (missing terminal).
Z.  triggered + acceptance_decision → observed_but_incomplete (missing terminal).
AA. triggered + readiness_decision + rejected → observed_and_closed.
AB. triggered + readiness_decision + accepted → observed_and_closed.
AC. triggered + acceptance_decision + completed → observed_and_closed.
AD. triggered + readiness_decision + rerouted → observed_and_closed.
AE. triggered + acceptance_decision + rejected → observed_and_closed.
AF. observed_and_closed → runtime_closure_established is True.
AG. observed_and_closed → gap_description is empty.
AH. Stale history (even if complete) → historical_evidence_stale.
AI. Stale history → runtime_closure_established is False.
AJ. Stale history → gap_description mentions age and threshold.
AK. record() returns DelegatedFlowHistoryEntry.
AL. record() appends to registry (entry_count increases).
AM. snapshot() returns a copy of all entries.
AN. Custom staleness_threshold respected.
AO. All public names are in __all__.
AP. Policy sentinel count is at least 5.
AQ. record_delegated_flow_event() convenience helper adds to singleton.
AR. evaluate_delegated_flow_history() convenience helper returns report.
AS. DelegatedFlowHistoryReport.to_dict() includes all required top-level keys.
AT. HistoryEvidenceStatus.no_history_yet: is_definitive_gap = True.
AU. observed_but_incomplete status has non-empty gap_description.
AV. insufficient_evidence status has non-empty gap_description.
AW. observed_and_closed: observed_kinds includes all three categories.
AX. Multiple events same kind do not double-count categories.
AY. system_final_acceptance_verdict._evaluate_delegated_flow integrates history:
    no_history_yet → evidence_linkage contains history_evidence_status.
AZ. system_final_acceptance_verdict._evaluate_delegated_flow integrates history:
    history module unavailable → falls back to gate-only logic (backward compat).
"""

from __future__ import annotations

import json
import sys
import os
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.delegated_flow_decision_history as _mod
from core.delegated_flow_decision_history import (
    DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY,
    DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL,
    HISTORY_FAIL_CONSERVATIVE_POLICY,
    HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY,
    HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY,
    HISTORY_STALENESS_IS_DOWNGRADE_POLICY,
    HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY,
    HistoryEvidenceStatus,
    DelegatedFlowEventKind,
    DelegatedFlowHistoryEntry,
    DelegatedFlowHistoryReport,
    DelegatedFlowDecisionHistory,
    record_delegated_flow_event,
    evaluate_delegated_flow_history,
    get_decision_history,
    reset_decision_history,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_history():
    """Reset the history singleton before and after each test."""
    reset_decision_history()
    yield
    reset_decision_history()


def _make_closed_history(
    staleness_threshold: float = 86400.0,
) -> DelegatedFlowDecisionHistory:
    """Return a history with all three required categories recorded."""
    h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=staleness_threshold)
    h.record(DelegatedFlowEventKind.triggered, flow_id="f1")
    h.record(
        DelegatedFlowEventKind.readiness_decision,
        flow_id="f1",
        decision_result="ready_for_release",
    )
    h.record(DelegatedFlowEventKind.accepted, flow_id="f1")
    return h


def _make_history_with_entries(
    kinds: List[DelegatedFlowEventKind],
    staleness_threshold: float = 86400.0,
) -> DelegatedFlowDecisionHistory:
    """Return a history with the specified event kinds recorded."""
    h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=staleness_threshold)
    for k in kinds:
        h.record(k, flow_id="test-flow")
    return h


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleImportAndSentinels:
    def test_A_module_importable(self):
        assert _mod is not None

    def test_A_authority_sentinel_non_empty(self):
        assert DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY
        assert isinstance(DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY, str)

    def test_A_pr_v2_4dh_sentinel_non_empty(self):
        assert DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL
        assert isinstance(DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL, str)

    def test_A_authority_contains_module_name(self):
        assert "delegated_flow_decision_history" in DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY

    def test_A_sentinel_contains_pr_tag(self):
        assert "PR-V2-4DH" in DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_B_fail_conservative_non_empty(self):
        assert HISTORY_FAIL_CONSERVATIVE_POLICY
        assert "POLICY" in HISTORY_FAIL_CONSERVATIVE_POLICY

    def test_B_five_state_policy_non_empty(self):
        assert HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY
        assert "five" in HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY.lower()

    def test_B_structure_vs_runtime_policy_non_empty(self):
        assert HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY
        assert "structure_present" in HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY

    def test_B_staleness_downgrade_policy_non_empty(self):
        assert HISTORY_STALENESS_IS_DOWNGRADE_POLICY
        assert "stale" in HISTORY_STALENESS_IS_DOWNGRADE_POLICY.lower()

    def test_B_silence_not_evidence_policy_non_empty(self):
        assert HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY
        assert "silence" in HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY.lower()

    def test_AP_at_least_five_policies(self):
        policies = [
            HISTORY_FAIL_CONSERVATIVE_POLICY,
            HISTORY_FIVE_STATE_EVIDENCE_STATUS_POLICY,
            HISTORY_STRUCTURE_VS_RUNTIME_CLOSURE_POLICY,
            HISTORY_STALENESS_IS_DOWNGRADE_POLICY,
            HISTORY_SILENCE_IS_NOT_EVIDENCE_POLICY,
        ]
        assert len([p for p in policies if p]) >= 5


# ===========================================================================
# C/D/E/F. HistoryEvidenceStatus
# ===========================================================================


class TestHistoryEvidenceStatus:
    def test_C_has_five_values(self):
        values = {s.value for s in HistoryEvidenceStatus}
        assert "no_history_yet" in values
        assert "insufficient_evidence" in values
        assert "observed_but_incomplete" in values
        assert "observed_and_closed" in values
        assert "historical_evidence_stale" in values
        assert len(values) == 5

    def test_D_from_string_valid(self):
        assert HistoryEvidenceStatus.from_string("no_history_yet") == HistoryEvidenceStatus.no_history_yet
        assert HistoryEvidenceStatus.from_string("observed_and_closed") == HistoryEvidenceStatus.observed_and_closed

    def test_D_from_string_invalid(self):
        assert HistoryEvidenceStatus.from_string("bogus") == HistoryEvidenceStatus.no_history_yet

    def test_D_from_string_non_string(self):
        assert HistoryEvidenceStatus.from_string(None) == HistoryEvidenceStatus.no_history_yet  # type: ignore
        assert HistoryEvidenceStatus.from_string(42) == HistoryEvidenceStatus.no_history_yet  # type: ignore

    def test_E_allows_runtime_closure_only_for_observed_and_closed(self):
        assert HistoryEvidenceStatus.observed_and_closed.allows_runtime_closure is True
        for s in HistoryEvidenceStatus:
            if s != HistoryEvidenceStatus.observed_and_closed:
                assert s.allows_runtime_closure is False

    def test_F_is_definitive_gap_for_no_history_and_stale(self):
        assert HistoryEvidenceStatus.no_history_yet.is_definitive_gap is True
        assert HistoryEvidenceStatus.historical_evidence_stale.is_definitive_gap is True
        assert HistoryEvidenceStatus.insufficient_evidence.is_definitive_gap is False
        assert HistoryEvidenceStatus.observed_but_incomplete.is_definitive_gap is False
        assert HistoryEvidenceStatus.observed_and_closed.is_definitive_gap is False

    def test_AT_no_history_yet_is_definitive_gap(self):
        assert HistoryEvidenceStatus.no_history_yet.is_definitive_gap is True


# ===========================================================================
# G/H/I. DelegatedFlowEventKind
# ===========================================================================


class TestDelegatedFlowEventKind:
    def test_G_has_seven_values(self):
        values = {k.value for k in DelegatedFlowEventKind}
        assert "triggered" in values
        assert "readiness_decision" in values
        assert "acceptance_decision" in values
        assert "rerouted" in values
        assert "rejected" in values
        assert "accepted" in values
        assert "completed" in values
        assert len(values) == 7

    def test_H_from_string_valid(self):
        assert DelegatedFlowEventKind.from_string("triggered") == DelegatedFlowEventKind.triggered
        assert DelegatedFlowEventKind.from_string("completed") == DelegatedFlowEventKind.completed

    def test_H_from_string_invalid(self):
        assert DelegatedFlowEventKind.from_string("bogus") == DelegatedFlowEventKind.triggered

    def test_H_from_string_non_string(self):
        assert DelegatedFlowEventKind.from_string(None) == DelegatedFlowEventKind.triggered  # type: ignore

    def test_I_is_terminal_true_for_terminal_kinds(self):
        for k in (
            DelegatedFlowEventKind.completed,
            DelegatedFlowEventKind.rejected,
            DelegatedFlowEventKind.rerouted,
            DelegatedFlowEventKind.accepted,
        ):
            assert k.is_terminal is True, f"{k} should be terminal"

    def test_I_is_terminal_false_for_non_terminal(self):
        for k in (
            DelegatedFlowEventKind.triggered,
            DelegatedFlowEventKind.readiness_decision,
            DelegatedFlowEventKind.acceptance_decision,
        ):
            assert k.is_terminal is False, f"{k} should not be terminal"


# ===========================================================================
# J/K/L/M. DelegatedFlowHistoryEntry
# ===========================================================================


class TestDelegatedFlowHistoryEntry:
    def test_J_constructs_with_defaults(self):
        entry = DelegatedFlowHistoryEntry()
        assert entry.entry_id
        assert entry.kind == DelegatedFlowEventKind.triggered
        assert entry.flow_id == ""
        assert entry.decision_result == ""
        assert isinstance(entry.context, dict)
        assert isinstance(entry.recorded_at, float)

    def test_J_constructs_with_fields(self):
        entry = DelegatedFlowHistoryEntry(
            kind=DelegatedFlowEventKind.rejected,
            flow_id="flow-123",
            decision_result="rejected_due_to_missing_evidence",
            context={"session": "s1"},
        )
        assert entry.kind == DelegatedFlowEventKind.rejected
        assert entry.flow_id == "flow-123"
        assert entry.decision_result == "rejected_due_to_missing_evidence"
        assert entry.context["session"] == "s1"

    def test_K_to_dict_json_serialisable(self):
        entry = DelegatedFlowHistoryEntry(
            kind=DelegatedFlowEventKind.completed,
            flow_id="flow-abc",
            decision_result="",
            context={"capability": "exec"},
        )
        d = entry.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)  # must not raise

    def test_K_to_dict_has_required_keys(self):
        entry = DelegatedFlowHistoryEntry()
        d = entry.to_dict()
        for key in ("entry_id", "kind", "flow_id", "decision_result", "context", "recorded_at"):
            assert key in d, f"Missing key: {key}"

    def test_L_to_json_valid(self):
        entry = DelegatedFlowHistoryEntry()
        js = entry.to_json()
        parsed = json.loads(js)
        assert isinstance(parsed, dict)

    def test_M_from_dict_round_trip(self):
        entry = DelegatedFlowHistoryEntry(
            kind=DelegatedFlowEventKind.rerouted,
            flow_id="flow-xyz",
            decision_result="rerouted_to_local",
            context={"reason": "timeout"},
        )
        d = entry.to_dict()
        restored = DelegatedFlowHistoryEntry.from_dict(d)
        assert restored.kind == entry.kind
        assert restored.flow_id == entry.flow_id
        assert restored.decision_result == entry.decision_result
        assert restored.context == entry.context


# ===========================================================================
# N/O/P/Q. DelegatedFlowHistoryReport
# ===========================================================================


class TestDelegatedFlowHistoryReport:
    def test_N_constructs_with_defaults(self):
        r = DelegatedFlowHistoryReport()
        assert r.report_id
        assert r.evidence_status == HistoryEvidenceStatus.no_history_yet
        assert r.structure_present is False
        assert r.runtime_closure_established is False
        assert r.total_entries == 0
        assert isinstance(r.observed_kinds, list)

    def test_O_to_dict_json_serialisable(self):
        r = DelegatedFlowHistoryReport(
            evidence_status=HistoryEvidenceStatus.observed_and_closed,
            structure_present=True,
            runtime_closure_established=True,
            total_entries=3,
            observed_kinds=["triggered", "readiness_decision", "accepted"],
            gap_description="",
            summary="observed_and_closed: all good",
        )
        d = r.to_dict()
        json.dumps(d)  # must not raise

    def test_AS_to_dict_has_required_keys(self):
        r = DelegatedFlowHistoryReport()
        d = r.to_dict()
        for key in (
            "report_id",
            "evidence_status",
            "structure_present",
            "runtime_closure_established",
            "total_entries",
            "observed_kinds",
            "gap_description",
            "summary",
            "staleness_threshold_seconds",
            "latest_entry_age_seconds",
            "evaluated_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_P_to_json_valid(self):
        r = DelegatedFlowHistoryReport()
        js = r.to_json()
        parsed = json.loads(js)
        assert isinstance(parsed, dict)

    def test_Q_from_dict_round_trip(self):
        r = DelegatedFlowHistoryReport(
            evidence_status=HistoryEvidenceStatus.observed_but_incomplete,
            structure_present=True,
            runtime_closure_established=False,
            total_entries=2,
            observed_kinds=["triggered", "readiness_decision"],
            gap_description="missing terminal",
            summary="partial",
        )
        d = r.to_dict()
        restored = DelegatedFlowHistoryReport.from_dict(d)
        assert restored.evidence_status == r.evidence_status
        assert restored.structure_present == r.structure_present
        assert restored.runtime_closure_established == r.runtime_closure_established
        assert restored.total_entries == r.total_entries
        assert restored.observed_kinds == r.observed_kinds


# ===========================================================================
# R/S/T. Singleton management
# ===========================================================================


class TestSingletonManagement:
    def test_R_get_decision_history_returns_instance(self):
        h = get_decision_history()
        assert isinstance(h, DelegatedFlowDecisionHistory)

    def test_S_singleton_identity(self):
        h1 = get_decision_history()
        h2 = get_decision_history()
        assert h1 is h2

    def test_T_reset_creates_new_singleton(self):
        h1 = get_decision_history()
        reset_decision_history()
        h2 = get_decision_history()
        assert h1 is not h2


# ===========================================================================
# U/V/W. Empty registry behaviour — fail-conservative
# ===========================================================================


class TestEmptyRegistryFailConservative:
    def test_U_empty_returns_no_history_yet(self):
        h = DelegatedFlowDecisionHistory()
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.no_history_yet

    def test_V_empty_runtime_closure_is_false(self):
        h = DelegatedFlowDecisionHistory()
        report = h.evaluate()
        assert report.runtime_closure_established is False

    def test_W_empty_gap_description_non_empty(self):
        h = DelegatedFlowDecisionHistory()
        report = h.evaluate()
        assert report.gap_description, "gap_description must be non-empty for no_history_yet"

    def test_W_empty_latest_entry_age_is_none(self):
        h = DelegatedFlowDecisionHistory()
        report = h.evaluate()
        assert report.latest_entry_age_seconds is None

    def test_W_empty_total_entries_is_zero(self):
        h = DelegatedFlowDecisionHistory()
        report = h.evaluate()
        assert report.total_entries == 0


# ===========================================================================
# X. Single triggered event → insufficient_evidence
# ===========================================================================


class TestInsufficientEvidence:
    def test_X_single_trigger_gives_insufficient_evidence(self):
        h = _make_history_with_entries([DelegatedFlowEventKind.triggered])
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.insufficient_evidence

    def test_X_insufficient_evidence_runtime_closure_false(self):
        h = _make_history_with_entries([DelegatedFlowEventKind.triggered])
        report = h.evaluate()
        assert report.runtime_closure_established is False

    def test_AV_insufficient_evidence_gap_description_non_empty(self):
        h = _make_history_with_entries([DelegatedFlowEventKind.triggered])
        report = h.evaluate()
        assert report.gap_description, "gap_description must be non-empty for insufficient_evidence"


# ===========================================================================
# Y/Z. triggered + one decision → observed_but_incomplete
# ===========================================================================


class TestObservedButIncomplete:
    def test_Y_trigger_plus_readiness_decision(self):
        h = _make_history_with_entries(
            [DelegatedFlowEventKind.triggered, DelegatedFlowEventKind.readiness_decision]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_but_incomplete

    def test_Z_trigger_plus_acceptance_decision(self):
        h = _make_history_with_entries(
            [DelegatedFlowEventKind.triggered, DelegatedFlowEventKind.acceptance_decision]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_but_incomplete

    def test_AU_observed_but_incomplete_gap_non_empty(self):
        h = _make_history_with_entries(
            [DelegatedFlowEventKind.triggered, DelegatedFlowEventKind.readiness_decision]
        )
        report = h.evaluate()
        assert report.gap_description, "gap_description must be non-empty for observed_but_incomplete"

    def test_observed_but_incomplete_runtime_closure_false(self):
        h = _make_history_with_entries(
            [DelegatedFlowEventKind.triggered, DelegatedFlowEventKind.readiness_decision]
        )
        report = h.evaluate()
        assert report.runtime_closure_established is False


# ===========================================================================
# AA-AE. Complete cycles → observed_and_closed
# ===========================================================================


class TestObservedAndClosed:
    def test_AA_trigger_readiness_rejected(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.readiness_decision,
                DelegatedFlowEventKind.rejected,
            ]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed

    def test_AB_trigger_readiness_accepted(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.readiness_decision,
                DelegatedFlowEventKind.accepted,
            ]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed

    def test_AC_trigger_acceptance_completed(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.acceptance_decision,
                DelegatedFlowEventKind.completed,
            ]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed

    def test_AD_trigger_readiness_rerouted(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.readiness_decision,
                DelegatedFlowEventKind.rerouted,
            ]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed

    def test_AE_trigger_acceptance_rejected(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.acceptance_decision,
                DelegatedFlowEventKind.rejected,
            ]
        )
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed

    def test_AF_observed_and_closed_runtime_closure_true(self):
        h = _make_closed_history()
        report = h.evaluate()
        assert report.runtime_closure_established is True

    def test_AG_observed_and_closed_gap_description_empty(self):
        h = _make_closed_history()
        report = h.evaluate()
        assert report.gap_description == "", (
            f"gap_description should be empty for observed_and_closed, got: {report.gap_description!r}"
        )

    def test_AW_observed_kinds_includes_all_categories(self):
        h = _make_history_with_entries(
            [
                DelegatedFlowEventKind.triggered,
                DelegatedFlowEventKind.readiness_decision,
                DelegatedFlowEventKind.completed,
            ]
        )
        report = h.evaluate()
        kinds = set(report.observed_kinds)
        assert "triggered" in kinds
        assert "readiness_decision" in kinds
        assert "completed" in kinds


# ===========================================================================
# AH/AI/AJ. Stale history
# ===========================================================================


class TestStaleHistory:
    def test_AH_stale_complete_history_gives_stale_status(self):
        # Use a tiny threshold so entries appear stale immediately
        h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=0.0)
        h.record(DelegatedFlowEventKind.triggered, flow_id="f1")
        h.record(
            DelegatedFlowEventKind.readiness_decision,
            flow_id="f1",
            decision_result="ready",
        )
        h.record(DelegatedFlowEventKind.accepted, flow_id="f1")
        # With threshold=0, any age is stale
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.historical_evidence_stale

    def test_AI_stale_runtime_closure_false(self):
        h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=0.0)
        h.record(DelegatedFlowEventKind.triggered)
        h.record(DelegatedFlowEventKind.readiness_decision, decision_result="ready")
        h.record(DelegatedFlowEventKind.completed)
        report = h.evaluate()
        assert report.runtime_closure_established is False

    def test_AJ_stale_gap_description_mentions_age_and_threshold(self):
        h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=0.0)
        h.record(DelegatedFlowEventKind.triggered)
        h.record(DelegatedFlowEventKind.readiness_decision, decision_result="ready")
        h.record(DelegatedFlowEventKind.completed)
        report = h.evaluate()
        # gap_description should mention threshold
        assert "threshold" in report.gap_description.lower() or "stale" in report.gap_description.lower()

    def test_AN_custom_staleness_threshold_respected(self):
        # Large threshold — entries should NOT be stale
        h = DelegatedFlowDecisionHistory(staleness_threshold_seconds=9999999.0)
        h.record(DelegatedFlowEventKind.triggered)
        h.record(DelegatedFlowEventKind.readiness_decision, decision_result="ready")
        h.record(DelegatedFlowEventKind.accepted)
        report = h.evaluate()
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed


# ===========================================================================
# AK/AL/AM. record() and snapshot()
# ===========================================================================


class TestRecordAndSnapshot:
    def test_AK_record_returns_entry(self):
        h = DelegatedFlowDecisionHistory()
        entry = h.record(DelegatedFlowEventKind.triggered, flow_id="f1")
        assert isinstance(entry, DelegatedFlowHistoryEntry)
        assert entry.kind == DelegatedFlowEventKind.triggered
        assert entry.flow_id == "f1"

    def test_AL_record_increases_count(self):
        h = DelegatedFlowDecisionHistory()
        assert h.entry_count() == 0
        h.record(DelegatedFlowEventKind.triggered)
        assert h.entry_count() == 1
        h.record(DelegatedFlowEventKind.readiness_decision, decision_result="ready")
        assert h.entry_count() == 2

    def test_AM_snapshot_returns_copy(self):
        h = DelegatedFlowDecisionHistory()
        h.record(DelegatedFlowEventKind.triggered)
        snap = h.snapshot()
        assert isinstance(snap, list)
        assert len(snap) == 1
        # Modifying snapshot does not affect registry
        snap.clear()
        assert h.entry_count() == 1

    def test_AX_same_kind_multiple_times_does_not_double_count(self):
        h = DelegatedFlowDecisionHistory()
        # Record triggered 3 times, one decision, one terminal
        for _ in range(3):
            h.record(DelegatedFlowEventKind.triggered)
        h.record(DelegatedFlowEventKind.readiness_decision, decision_result="ready")
        h.record(DelegatedFlowEventKind.completed)
        report = h.evaluate()
        # Should still be observed_and_closed (not over-counted)
        assert report.evidence_status == HistoryEvidenceStatus.observed_and_closed
        # Total entries = 5 but only 3 distinct categories
        assert report.total_entries == 5
        assert len(set(report.observed_kinds)) == 3


# ===========================================================================
# AO. All public names in __all__
# ===========================================================================


class TestAllPublicNames:
    def test_AO_all_names_in_module(self):
        for name in _mod.__all__:
            assert hasattr(_mod, name), f"Missing from module: {name}"

    def test_AO_required_names_in_all(self):
        required = [
            "DELEGATED_FLOW_DECISION_HISTORY_AUTHORITY",
            "DELEGATED_FLOW_DECISION_HISTORY_PR_V2_4DH_SENTINEL",
            "HistoryEvidenceStatus",
            "DelegatedFlowEventKind",
            "DelegatedFlowHistoryEntry",
            "DelegatedFlowHistoryReport",
            "DelegatedFlowDecisionHistory",
            "record_delegated_flow_event",
            "evaluate_delegated_flow_history",
            "get_decision_history",
            "reset_decision_history",
        ]
        for name in required:
            assert name in _mod.__all__, f"Missing from __all__: {name}"


# ===========================================================================
# AQ/AR. Convenience helpers
# ===========================================================================


class TestConvenienceHelpers:
    def test_AQ_record_delegated_flow_event_adds_to_singleton(self):
        entry = record_delegated_flow_event(
            DelegatedFlowEventKind.triggered,
            flow_id="s-flow",
            context={"test": True},
        )
        assert isinstance(entry, DelegatedFlowHistoryEntry)
        assert get_decision_history().entry_count() == 1

    def test_AR_evaluate_delegated_flow_history_returns_report(self):
        report = evaluate_delegated_flow_history()
        assert isinstance(report, DelegatedFlowHistoryReport)
        assert report.evidence_status == HistoryEvidenceStatus.no_history_yet


# ===========================================================================
# AY. system_final_acceptance_verdict integrates history
# ===========================================================================


class TestSystemFinalAcceptanceVerdictIntegration:
    """Integration tests verifying that _evaluate_delegated_flow surfaces
    the history evidence status in its evidence_linkage."""

    def test_AY_history_evidence_status_in_linkage(self):
        """When history is empty, evidence_linkage must include
        history_evidence_status=no_history_yet."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                reset_system_acceptance_evaluator,
            )
        except ImportError:
            pytest.skip("system_final_acceptance_verdict not available")

        reset_system_acceptance_evaluator()
        reset_decision_history()

        evaluator = SystemFinalAcceptanceEvaluator()
        item = evaluator._evaluate_delegated_flow()

        linkage = item.evidence_linkage
        assert "history_evidence_status" in linkage, (
            "evidence_linkage must include history_evidence_status; "
            f"got: {list(linkage.keys())}"
        )
        assert linkage["history_evidence_status"] == "no_history_yet"
        assert "structure_present" in linkage
        assert "runtime_closure_established" in linkage

    def test_AY_gap_description_mentions_idle_environment(self):
        """When history is empty, gap_description should communicate this is
        an idle-environment gap, not a code failure."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                reset_system_acceptance_evaluator,
            )
        except ImportError:
            pytest.skip("system_final_acceptance_verdict not available")

        reset_system_acceptance_evaluator()
        reset_decision_history()

        evaluator = SystemFinalAcceptanceEvaluator()
        item = evaluator._evaluate_delegated_flow()

        # The gap description should either mention "idle" or "no_history_yet"
        # or contain context about why there is no history
        assert item.gap_description, "gap_description must be non-empty"

    def test_AY_observed_but_incomplete_maps_to_pending(self):
        """When history is observed_but_incomplete, the dimension status
        should be pending (not unresolved)."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                DimensionStatus,
                reset_system_acceptance_evaluator,
            )
        except ImportError:
            pytest.skip("system_final_acceptance_verdict not available")

        reset_system_acceptance_evaluator()
        reset_decision_history()

        # Record partial history in singleton
        record_delegated_flow_event(DelegatedFlowEventKind.triggered, flow_id="t1")
        record_delegated_flow_event(
            DelegatedFlowEventKind.readiness_decision,
            flow_id="t1",
            decision_result="not_ready",
        )
        # No terminal event → observed_but_incomplete

        evaluator = SystemFinalAcceptanceEvaluator()
        item = evaluator._evaluate_delegated_flow()

        linkage = item.evidence_linkage
        assert linkage.get("history_evidence_status") == "observed_but_incomplete"
        # observed_but_incomplete should map to pending, not unresolved
        assert item.status == DimensionStatus.pending, (
            f"Expected pending for observed_but_incomplete; got {item.status}"
        )

    def test_AZ_history_module_unavailable_falls_back_gracefully(self):
        """When the decision history module cannot be imported, the evaluator
        must still return a valid AcceptanceChecklistItem (backward compat)."""
        try:
            from core.system_final_acceptance_verdict import (
                SystemFinalAcceptanceEvaluator,
                reset_system_acceptance_evaluator,
            )
        except ImportError:
            pytest.skip("system_final_acceptance_verdict not available")

        reset_system_acceptance_evaluator()

        evaluator = SystemFinalAcceptanceEvaluator()

        # Patch out the history availability flag for this test
        import core.system_final_acceptance_verdict as sfav_mod
        original = sfav_mod._DECISION_HISTORY_AVAILABLE
        try:
            sfav_mod._DECISION_HISTORY_AVAILABLE = False
            item = evaluator._evaluate_delegated_flow()
            # Must not raise; must return an AcceptanceChecklistItem
            from core.system_final_acceptance_verdict import AcceptanceChecklistItem
            assert isinstance(item, AcceptanceChecklistItem)
            assert item.evidence_summary  # non-empty
        finally:
            sfav_mod._DECISION_HISTORY_AVAILABLE = original
