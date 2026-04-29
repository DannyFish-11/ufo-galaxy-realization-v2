#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_inflight_task_continuity_taxonomy.py
================================================
PR-06: In-Flight Task Continuity Taxonomy — test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings with correct content.
B  — InFlightTaskContinuityClass enum has all five expected values.
C  — InFlightTaskContinuityClass ordering helpers (rank, is_at_least, flags).
D  — InFlightTaskContinuityEvidence: construction, defaults, computed props.
E  — InFlightTaskContinuityEvidence: to_dict / from_dict round-trip.
F  — InFlightTaskContinuityVerdict: construction and property flags.
G  — InFlightTaskContinuityVerdict: to_dict / from_dict round-trip.
H  — Contract: authoritative_task_continuity_restored when all tasks resumed.
I  — Contract: authoritative requires ALL tasks resumed (no gap allowed).
J  — Contract: partial_recovery_only blocks authoritative.
K  — Contract: process_death_observed without execution_context_rebuilt blocks
     authoritative.
L  — Contract: process_death_observed WITH execution_context_rebuilt still
     permits authoritative when all other conditions met.
M  — Contract: resumable_with_replay_or_reconcile when recoverable_count > 0.
N  — Contract: state_restored_not_resumed when only needs_reconcile tasks.
O  — Contract: state_restored_not_resumed for resumed+non-recoverable mix.
P  — Contract: history_or_evidence_only when result/history visible, no live state.
Q  — Contract: task_continuity_lost for empty snapshot with no history.
R  — Contract: task_continuity_lost for all terminal/ambiguous, no history.
S  — Contract: snapshot-only (no resumed, no recoverable) → NOT authoritative.
T  — Contract: result_or_history_visible does NOT elevate above history_or_evidence_only.
U  — Contract: replay/reconcile evidence alone → NOT authoritative (boundary test).
V  — build_task_continuity_verdict convenience wrapper works.
W  — build_task_continuity_verdict_from_report extracts counts correctly.
X  — build_task_continuity_verdict_from_report: stubs missing attrs gracefully.
Y  — Baseline probe (no evidence) → task_continuity_lost (not authoritative).
Z  — SystemFinalAcceptanceEvaluator includes task_continuity dimension.
AA — SystemFinalAcceptanceEvaluator task_continuity probe: not optimistic with
     zero-evidence (must be pending, not unresolved due to misconfiguration).
AB — AcceptanceDimensionId.all_dimensions includes task_continuity.
AC — Full scenario: all resumed tasks → authoritative_task_continuity_restored.
AD — Full scenario: recoverable tasks → resumable_with_replay_or_reconcile.
AE — Full scenario: needs_reconcile tasks → state_restored_not_resumed.
AF — Full scenario: interrupted + history → history_or_evidence_only.
AG — Full scenario: abandoned only, no history → task_continuity_lost.
AH — Downgrade: recoverable + partial_recovery → still resumable (not authoritative).
AI — Downgrade: all resumed but partial_recovery_only=True → not authoritative.
AJ — Downgrade reason is included in verdict for non-authoritative classes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    total: int = 0,
    resumed: int = 0,
    recoverable: int = 0,
    interrupted: int = 0,
    abandoned: int = 0,
    needs_reconcile: int = 0,
    ambiguous: int = 0,
    result_or_history_visible: bool = False,
    execution_context_rebuilt: bool = False,
    process_death_observed: bool = False,
    partial_recovery_only: bool = False,
) -> Any:
    from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
    return InFlightTaskContinuityEvidence(
        total_evaluated=total,
        resumed_count=resumed,
        recoverable_count=recoverable,
        interrupted_count=interrupted,
        abandoned_count=abandoned,
        needs_reconcile_count=needs_reconcile,
        ambiguous_count=ambiguous,
        result_or_history_visible=result_or_history_visible,
        execution_context_rebuilt=execution_context_rebuilt,
        process_death_observed=process_death_observed,
        partial_recovery_only=partial_recovery_only,
    )


def _evaluate(evidence: Any) -> Any:
    from core.inflight_task_continuity_taxonomy import (
        InFlightTaskContinuityTaxonomyContract,
    )
    return InFlightTaskContinuityTaxonomyContract().evaluate(evidence)


# ---------------------------------------------------------------------------
# A: sentinel importability
# ---------------------------------------------------------------------------

class TestGroupA_Sentinels:
    def test_A01_authority_sentinel(self):
        from core.inflight_task_continuity_taxonomy import (
            INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY,
        )
        assert isinstance(INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY, str)
        assert len(INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY) > 30
        assert "task" in INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY.lower()

    def test_A02_pr06_sentinel(self):
        from core.inflight_task_continuity_taxonomy import (
            INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL,
        )
        assert "PR-06" in INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL

    def test_A03_snapshot_not_continuity_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY,
        )
        s = SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY
        assert "snapshot" in s.lower()
        assert "authoritative" in s.lower()

    def test_A04_replay_not_continuity_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY,
        )
        s = REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY
        assert "replay" in s.lower()
        assert "continuity" in s.lower()

    def test_A05_reconcile_not_continuity_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY,
        )
        s = RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY
        assert "reconcile" in s.lower()

    def test_A06_result_ingestion_not_continuity_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY,
        )
        s = RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY
        assert "result" in s.lower()
        assert "continuity" in s.lower()

    def test_A07_partial_recovery_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY,
        )
        s = PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY
        assert "partial" in s.lower()
        assert "authoritative" in s.lower()

    def test_A08_evidence_absent_policy(self):
        from core.inflight_task_continuity_taxonomy import (
            EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY,
        )
        s = EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY
        assert "absent" in s.lower()
        assert "continuity_lost" in s.lower()


# ---------------------------------------------------------------------------
# B: InFlightTaskContinuityClass enum values
# ---------------------------------------------------------------------------

class TestGroupB_InFlightTaskContinuityClassEnum:
    def test_B01_all_five_values_present(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        expected = {
            "authoritative_task_continuity_restored",
            "resumable_with_replay_or_reconcile",
            "state_restored_not_resumed",
            "history_or_evidence_only",
            "task_continuity_lost",
        }
        actual = {c.value for c in InFlightTaskContinuityClass}
        assert expected == actual

    def test_B02_from_string_valid(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        c = InFlightTaskContinuityClass.from_string("authoritative_task_continuity_restored")
        assert c == InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_B03_from_string_unknown_defaults_to_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        c = InFlightTaskContinuityClass.from_string("nonexistent_value")
        assert c == InFlightTaskContinuityClass.task_continuity_lost

    def test_B04_from_string_non_string_defaults_to_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        c = InFlightTaskContinuityClass.from_string(None)  # type: ignore[arg-type]
        assert c == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# C: ordering helpers
# ---------------------------------------------------------------------------

class TestGroupC_OrderingHelpers:
    def test_C01_authoritative_has_highest_rank(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        auth = InFlightTaskContinuityClass.authoritative_task_continuity_restored
        for other in InFlightTaskContinuityClass:
            if other != auth:
                assert auth.rank > other.rank

    def test_C02_task_continuity_lost_has_lowest_rank(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        lost = InFlightTaskContinuityClass.task_continuity_lost
        for other in InFlightTaskContinuityClass:
            if other != lost:
                assert lost.rank < other.rank

    def test_C03_is_at_least_self(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        for c in InFlightTaskContinuityClass:
            assert c.is_at_least(c)

    def test_C04_is_authoritative_flag(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        assert InFlightTaskContinuityClass.authoritative_task_continuity_restored.is_authoritative
        for c in InFlightTaskContinuityClass:
            if c != InFlightTaskContinuityClass.authoritative_task_continuity_restored:
                assert not c.is_authoritative

    def test_C05_is_lost_flag(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        assert InFlightTaskContinuityClass.task_continuity_lost.is_lost
        assert not InFlightTaskContinuityClass.authoritative_task_continuity_restored.is_lost

    def test_C06_requires_replay_flag(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        assert InFlightTaskContinuityClass.resumable_with_replay_or_reconcile.requires_replay_or_reconcile
        assert not InFlightTaskContinuityClass.authoritative_task_continuity_restored.requires_replay_or_reconcile

    def test_C07_is_state_only_flag(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        assert InFlightTaskContinuityClass.state_restored_not_resumed.is_state_only
        assert not InFlightTaskContinuityClass.resumable_with_replay_or_reconcile.is_state_only

    def test_C08_is_evidence_only_flag(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        assert InFlightTaskContinuityClass.history_or_evidence_only.is_evidence_only
        assert not InFlightTaskContinuityClass.state_restored_not_resumed.is_evidence_only


# ---------------------------------------------------------------------------
# D: InFlightTaskContinuityEvidence construction
# ---------------------------------------------------------------------------

class TestGroupD_EvidenceConstruction:
    def test_D01_default_construction(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        e = InFlightTaskContinuityEvidence()
        assert e.total_evaluated == 0
        assert e.resumed_count == 0
        assert e.recoverable_count == 0
        assert e.result_or_history_visible is False
        assert e.process_death_observed is False
        assert e.partial_recovery_only is False

    def test_D02_state_restored_count_property(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        e = InFlightTaskContinuityEvidence(resumed_count=2, recoverable_count=3)
        # state_restored = resumed + recoverable
        assert e.state_restored_count == 5

    def test_D03_non_terminal_count_property(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        e = InFlightTaskContinuityEvidence(
            resumed_count=1, recoverable_count=2, needs_reconcile_count=1
        )
        # non_terminal = resumed + recoverable + needs_reconcile
        assert e.non_terminal_count == 4

    def test_D04_non_terminal_excludes_terminal_types(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        e = InFlightTaskContinuityEvidence(
            interrupted_count=2, abandoned_count=3, ambiguous_count=1
        )
        # interrupted/abandoned/ambiguous do NOT count as non_terminal
        assert e.non_terminal_count == 0


# ---------------------------------------------------------------------------
# E: InFlightTaskContinuityEvidence round-trip
# ---------------------------------------------------------------------------

class TestGroupE_EvidenceRoundTrip:
    def test_E01_to_dict_keys(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        e = InFlightTaskContinuityEvidence(
            total_evaluated=5,
            resumed_count=3,
            recoverable_count=2,
            process_death_observed=True,
        )
        d = e.to_dict()
        expected_keys = {
            "total_evaluated", "resumed_count", "recoverable_count",
            "interrupted_count", "abandoned_count", "needs_reconcile_count",
            "ambiguous_count", "state_restored_count",
            "result_or_history_visible", "execution_context_rebuilt",
            "process_death_observed", "partial_recovery_only", "evaluated_context",
        }
        assert expected_keys.issubset(d.keys())
        assert d["total_evaluated"] == 5
        assert d["state_restored_count"] == 5

    def test_E02_from_dict_round_trip(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityEvidence
        original = InFlightTaskContinuityEvidence(
            total_evaluated=4,
            resumed_count=2,
            recoverable_count=1,
            interrupted_count=1,
            result_or_history_visible=True,
            partial_recovery_only=True,
        )
        restored = InFlightTaskContinuityEvidence.from_dict(original.to_dict())
        assert restored.total_evaluated == 4
        assert restored.resumed_count == 2
        assert restored.recoverable_count == 1
        assert restored.result_or_history_visible is True
        assert restored.partial_recovery_only is True


# ---------------------------------------------------------------------------
# F: InFlightTaskContinuityVerdict construction and flags
# ---------------------------------------------------------------------------

class TestGroupF_VerdictConstruction:
    def test_F01_default_is_task_continuity_lost(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict()
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost
        assert v.continuity_lost is True
        assert v.is_authoritative is False

    def test_F02_is_authoritative_flag_for_authoritative_class(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.authoritative_task_continuity_restored
        )
        assert v.is_authoritative is True
        assert v.continuity_lost is False
        assert v.requires_replay_or_reconcile is False

    def test_F03_requires_replay_flag(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.resumable_with_replay_or_reconcile
        )
        assert v.requires_replay_or_reconcile is True
        assert v.is_authoritative is False

    def test_F04_state_present_not_resumed_flag(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.state_restored_not_resumed
        )
        assert v.state_present_not_resumed is True

    def test_F05_history_only_flag(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.history_or_evidence_only
        )
        assert v.history_only is True


# ---------------------------------------------------------------------------
# G: InFlightTaskContinuityVerdict round-trip
# ---------------------------------------------------------------------------

class TestGroupG_VerdictRoundTrip:
    def test_G01_to_dict_includes_class_value(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.resumable_with_replay_or_reconcile,
            reason="test reason",
            downgrade_reason="some gap",
        )
        d = v.to_dict()
        assert d["continuity_class"] == "resumable_with_replay_or_reconcile"
        assert d["is_authoritative"] is False
        assert d["requires_replay_or_reconcile"] is True
        assert d["reason"] == "test reason"
        assert d["downgrade_reason"] == "some gap"

    def test_G02_from_dict_round_trip(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v1 = InFlightTaskContinuityVerdict(
            continuity_class=InFlightTaskContinuityClass.state_restored_not_resumed,
            reason="needs reconcile",
        )
        d = v1.to_dict()
        v2 = InFlightTaskContinuityVerdict.from_dict(d)
        assert v2.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed
        assert v2.reason == "needs reconcile"

    def test_G03_from_dict_unknown_class_defaults_to_lost(self):
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityVerdict,
            InFlightTaskContinuityClass,
        )
        v = InFlightTaskContinuityVerdict.from_dict({"continuity_class": "unknown_xyz"})
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# H: authoritative_task_continuity_restored
# ---------------------------------------------------------------------------

class TestGroupH_AuthoritativeContinuityRestored:
    def test_H01_all_resumed_is_authoritative(self):
        """P0: all tasks resumed → authoritative_task_continuity_restored."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=3, resumed=3)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.authoritative_task_continuity_restored
        assert v.is_authoritative is True
        assert v.continuity_lost is False

    def test_H02_single_resumed_is_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=1, resumed=1)
        v = _evaluate(e)
        assert v.is_authoritative is True

    def test_H03_authoritative_has_empty_downgrade_reason(self):
        e = _make_evidence(total=2, resumed=2)
        v = _evaluate(e)
        assert v.downgrade_reason == ""


# ---------------------------------------------------------------------------
# I: authoritative requires ALL tasks resumed
# ---------------------------------------------------------------------------

class TestGroupI_AuthoritativeRequiresAllResumed:
    def test_I01_one_recoverable_blocks_authoritative(self):
        """Key invariant: recoverable task ≠ authoritative continuity."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, recoverable=1)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored
        # Should be resumable_with_replay_or_reconcile (recoverable > 0)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_I02_one_interrupted_blocks_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, interrupted=1)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_I03_one_ambiguous_blocks_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, ambiguous=1)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_I04_needs_reconcile_blocks_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, needs_reconcile=1)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_I05_zero_total_is_not_authoritative(self):
        """P0: empty snapshot → NOT authoritative."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=0)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_I06_snapshot_only_not_authoritative(self):
        """P0: snapshot-only (state in registry, not resumed) → NOT authoritative.

        Critical enforcement of SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY.
        """
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Only recoverable tasks (state in registry, dispatch taken, not yet resumed)
        e = _make_evidence(total=3, resumed=0, recoverable=3)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile


# ---------------------------------------------------------------------------
# J: partial_recovery_only blocks authoritative
# ---------------------------------------------------------------------------

class TestGroupJ_PartialRecoveryBlocksAuthoritative:
    def test_J01_partial_recovery_blocks_authoritative(self):
        """PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # All tasks resumed but partial recovery flag set
        e = _make_evidence(total=3, resumed=3, partial_recovery_only=True)
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_J02_partial_recovery_with_recoverable_still_resumable(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, recoverable=1, partial_recovery_only=True)
        v = _evaluate(e)
        # resumable because recoverable > 0
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_J03_partial_recovery_downgrade_reason_populated(self):
        e = _make_evidence(total=2, resumed=2, partial_recovery_only=True)
        v = _evaluate(e)
        assert "partial" in v.downgrade_reason.lower()


# ---------------------------------------------------------------------------
# K: process_death_observed without context_rebuilt blocks authoritative
# ---------------------------------------------------------------------------

class TestGroupK_ProcessDeathBlocksAuthoritative:
    def test_K01_process_death_without_context_rebuilt_blocks_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(
            total=2, resumed=2,
            process_death_observed=True,
            execution_context_rebuilt=False,
        )
        v = _evaluate(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored

    def test_K02_process_death_downgrade_reason_populated(self):
        e = _make_evidence(
            total=2, resumed=2,
            process_death_observed=True,
            execution_context_rebuilt=False,
        )
        v = _evaluate(e)
        assert v.downgrade_reason != ""
        assert "process_death" in v.downgrade_reason.lower()


# ---------------------------------------------------------------------------
# L: process_death + context_rebuilt still permits authoritative
# ---------------------------------------------------------------------------

class TestGroupL_ProcessDeathWithContextRebuilt:
    def test_L01_process_death_with_context_rebuilt_permits_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(
            total=2, resumed=2,
            process_death_observed=True,
            execution_context_rebuilt=True,  # context was rebuilt
        )
        v = _evaluate(e)
        assert v.is_authoritative is True


# ---------------------------------------------------------------------------
# M: resumable_with_replay_or_reconcile
# ---------------------------------------------------------------------------

class TestGroupM_ResumableWithReplayOrReconcile:
    def test_M01_recoverable_count_yields_resumable(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=0, recoverable=2)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_M02_mixed_resumed_and_recoverable_yields_resumable(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=3, resumed=1, recoverable=2)
        v = _evaluate(e)
        # recoverable > 0 → resumable_with_replay_or_reconcile (not authoritative)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_M03_resumable_is_not_authoritative(self):
        """State present + replay needed ≠ authoritative continuity."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=1, recoverable=1)
        v = _evaluate(e)
        assert v.is_authoritative is False
        assert v.requires_replay_or_reconcile is True

    def test_M04_partial_recovery_with_recoverable_still_resumable(self):
        """partial_recovery_only caps authoritative but not resumable."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, recoverable=2, partial_recovery_only=True)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile


# ---------------------------------------------------------------------------
# N: state_restored_not_resumed — needs_reconcile only
# ---------------------------------------------------------------------------

class TestGroupN_StateRestoredNotResumedNeedsReconcile:
    def test_N01_only_needs_reconcile_tasks(self):
        """Reconcile triggered ≠ continuity. RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, needs_reconcile=2)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed
        assert v.state_present_not_resumed is True
        assert v.is_authoritative is False

    def test_N02_state_restored_not_resumed_includes_reason(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=1, needs_reconcile=1)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed
        assert len(v.reason) > 0


# ---------------------------------------------------------------------------
# O: state_restored_not_resumed — resumed + non-recoverable mix
# ---------------------------------------------------------------------------

class TestGroupO_StateRestoredNotResumedMix:
    def test_O01_resumed_plus_interrupted_is_state_not_resumed(self):
        """Some resumed but some interrupted and no recoverable path → state_restored."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # 1 resumed + 1 interrupted, no recoverable
        e = _make_evidence(total=2, resumed=1, interrupted=1)
        v = _evaluate(e)
        # non_terminal_count = resumed(1) + recoverable(0) + needs_reconcile(0) = 1 > 0
        # recoverable_count == 0 → state_restored_not_resumed
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed

    def test_O02_state_restored_not_resumed_is_not_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, resumed=1, interrupted=1)
        v = _evaluate(e)
        assert v.is_authoritative is False
        assert v.requires_replay_or_reconcile is False


# ---------------------------------------------------------------------------
# P: history_or_evidence_only
# ---------------------------------------------------------------------------

class TestGroupP_HistoryOrEvidenceOnly:
    def test_P01_history_visible_no_live_state(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(
            total=2, interrupted=1, abandoned=1,
            result_or_history_visible=True,
        )
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.history_or_evidence_only
        assert v.history_only is True

    def test_P02_empty_snapshot_with_history_is_history_only(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=0, result_or_history_visible=True)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.history_or_evidence_only

    def test_P03_history_only_is_not_authoritative(self):
        """RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY: result/history ≠ authoritative continuity."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(result_or_history_visible=True)
        v = _evaluate(e)
        assert v.is_authoritative is False


# ---------------------------------------------------------------------------
# Q: task_continuity_lost — empty snapshot, no history
# ---------------------------------------------------------------------------

class TestGroupQ_TaskContinuityLostEmpty:
    def test_Q01_empty_snapshot_no_history_is_lost(self):
        """P0: empty snapshot → task_continuity_lost (EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY)."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=0, result_or_history_visible=False)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost
        assert v.continuity_lost is True

    def test_Q02_default_evidence_is_lost(self):
        """Baseline probe (all zeros/False) → task_continuity_lost."""
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityEvidence,
            InFlightTaskContinuityClass,
        )
        e = InFlightTaskContinuityEvidence()
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# R: task_continuity_lost — all terminal, no history
# ---------------------------------------------------------------------------

class TestGroupR_TaskContinuityLostAllTerminal:
    def test_R01_all_abandoned_no_history_is_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=3, abandoned=3, result_or_history_visible=False)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost

    def test_R02_all_interrupted_no_history_is_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, interrupted=2, result_or_history_visible=False)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost

    def test_R03_all_ambiguous_no_history_is_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, ambiguous=2, result_or_history_visible=False)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# S: snapshot-only is NOT authoritative (PR-06 core invariant)
# ---------------------------------------------------------------------------

class TestGroupS_SnapshotOnlyNotAuthoritative:
    def test_S01_recoverable_not_authoritative(self):
        """
        P0: snapshot restored + dispatch taken (recoverable) ≠ authoritative.
        STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED (from core contract) and
        SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY (taxonomy).
        """
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Three recoverable tasks (state in registry, replay/reconnect pending)
        e = _make_evidence(total=3, recoverable=3)
        v = _evaluate(e)
        assert v.is_authoritative is False
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_S02_state_in_registry_without_resumed_not_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # needs_reconcile = state visible, reconcile pending
        e = _make_evidence(total=2, needs_reconcile=2)
        v = _evaluate(e)
        assert v.is_authoritative is False
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed


# ---------------------------------------------------------------------------
# T: result/history alone does NOT elevate above history_or_evidence_only
# ---------------------------------------------------------------------------

class TestGroupT_ResultHistoryBoundary:
    def test_T01_result_visible_no_live_state_is_history_only(self):
        """RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=0, result_or_history_visible=True)
        v = _evaluate(e)
        # Must not be higher than history_or_evidence_only
        assert v.continuity_class.rank <= InFlightTaskContinuityClass.history_or_evidence_only.rank

    def test_T02_result_visible_with_live_state_gets_higher_class(self):
        """When live state exists AND result visible, class is determined by live state."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=1, recoverable=1, result_or_history_visible=True)
        v = _evaluate(e)
        # recoverable > 0 → resumable (higher than history_or_evidence_only)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile


# ---------------------------------------------------------------------------
# U: replay/reconcile evidence alone → NOT authoritative
# ---------------------------------------------------------------------------

class TestGroupU_ReplayReconcileBoundary:
    def test_U01_replay_needed_tasks_not_authoritative(self):
        """REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # execution_context_rebuilt=True simulates replay setup, but tasks are
        # still recoverable (not resumed), so NOT authoritative.
        e = _make_evidence(
            total=2, recoverable=2,
            execution_context_rebuilt=True,
        )
        v = _evaluate(e)
        assert v.is_authoritative is False
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_U02_needs_reconcile_not_authoritative(self):
        """RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, needs_reconcile=2)
        v = _evaluate(e)
        assert v.is_authoritative is False


# ---------------------------------------------------------------------------
# V: build_task_continuity_verdict convenience wrapper
# ---------------------------------------------------------------------------

class TestGroupV_BuildTaskContinuityVerdictWrapper:
    def test_V01_wrapper_works_for_all_resumed(self):
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict,
            InFlightTaskContinuityEvidence,
            InFlightTaskContinuityClass,
        )
        e = InFlightTaskContinuityEvidence(total_evaluated=2, resumed_count=2)
        v = build_task_continuity_verdict(e)
        assert v.is_authoritative is True

    def test_V02_wrapper_produces_lost_for_empty(self):
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict,
            InFlightTaskContinuityEvidence,
            InFlightTaskContinuityClass,
        )
        v = build_task_continuity_verdict(InFlightTaskContinuityEvidence())
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# W: build_task_continuity_verdict_from_report
# ---------------------------------------------------------------------------

class TestGroupW_BuildFromReport:
    def test_W01_extracts_counts_from_report(self):
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict_from_report,
            InFlightTaskContinuityClass,
        )

        @dataclass
        class FakeReport:
            total_evaluated: int = 3
            resumed_count: int = 3
            recoverable_count: int = 0
            interrupted_count: int = 0
            abandoned_count: int = 0
            needs_reconcile_count: int = 0
            ambiguous_count: int = 0

        report = FakeReport()
        v = build_task_continuity_verdict_from_report(report)
        assert v.is_authoritative is True

    def test_W02_recoverable_report_yields_resumable(self):
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict_from_report,
            InFlightTaskContinuityClass,
        )

        @dataclass
        class FakeReport:
            total_evaluated: int = 2
            resumed_count: int = 0
            recoverable_count: int = 2
            interrupted_count: int = 0
            abandoned_count: int = 0
            needs_reconcile_count: int = 0
            ambiguous_count: int = 0

        v = build_task_continuity_verdict_from_report(FakeReport())
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    def test_W03_passes_extra_flags(self):
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict_from_report,
            InFlightTaskContinuityClass,
        )

        @dataclass
        class FakeReport:
            total_evaluated: int = 2
            resumed_count: int = 2
            recoverable_count: int = 0
            interrupted_count: int = 0
            abandoned_count: int = 0
            needs_reconcile_count: int = 0
            ambiguous_count: int = 0

        # partial_recovery_only should block authoritative
        v = build_task_continuity_verdict_from_report(
            FakeReport(), partial_recovery_only=True
        )
        assert not v.is_authoritative

    def test_W04_stubs_missing_attrs_gracefully(self):
        """build_task_continuity_verdict_from_report handles objects without all attrs."""
        from core.inflight_task_continuity_taxonomy import (
            build_task_continuity_verdict_from_report,
        )

        class MinimalReport:
            total_evaluated = 0

        # Should not raise; defaults to 0 for missing attrs
        v = build_task_continuity_verdict_from_report(MinimalReport())
        assert v.continuity_lost is True


# ---------------------------------------------------------------------------
# X: (now part of W above)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Y: baseline probe conservatism
# ---------------------------------------------------------------------------

class TestGroupY_BaselineProbeConservatism:
    def test_Y01_default_evidence_is_not_authoritative(self):
        """Y: baseline probe MUST NOT produce authoritative_task_continuity_restored."""
        from core.inflight_task_continuity_taxonomy import (
            InFlightTaskContinuityEvidence,
            InFlightTaskContinuityClass,
            build_task_continuity_verdict,
        )
        e = InFlightTaskContinuityEvidence()  # all zeros
        v = build_task_continuity_verdict(e)
        assert v.continuity_class != InFlightTaskContinuityClass.authoritative_task_continuity_restored
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# Z: SystemFinalAcceptanceEvaluator includes task_continuity
# ---------------------------------------------------------------------------

class TestGroupZ_SystemFinalAcceptanceVerdictIntegration:
    def test_Z01_task_continuity_in_all_dimensions(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        dims = AcceptanceDimensionId.all_dimensions()
        dim_values = [d.value for d in dims]
        assert "task_continuity" in dim_values

    def test_Z02_task_continuity_dimension_id_exists(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        assert AcceptanceDimensionId.task_continuity.value == "task_continuity"

    def test_Z03_evaluator_produces_task_continuity_item(self):
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            AcceptanceDimensionId,
        )
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        assert "task_continuity" in report.checklist


# ---------------------------------------------------------------------------
# AA: SystemFinalAcceptanceEvaluator task_continuity probe is not optimistic
# ---------------------------------------------------------------------------

class TestGroupAA_TaskContinuityProbeNotOptimistic:
    def test_AA01_task_continuity_probe_is_pending_not_unresolved_due_to_misconfiguration(self):
        """Taxonomy wired → probe returns pending (not unresolved from misconfiguration)."""
        from core.system_final_acceptance_verdict import (
            SystemFinalAcceptanceEvaluator,
            DimensionStatus,
        )
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("task_continuity")
        assert item is not None
        # If taxonomy module is available: status should be pending (conservative)
        # not unresolved due to optimistic misconfiguration
        # The baseline probe must return task_continuity_lost, not authoritative
        if item.status == DimensionStatus.unresolved:
            # Acceptable only if module unavailable, not due to optimistic classification
            assert "authoritative_task_continuity_restored" not in (
                item.evidence_summary or ""
            )
        else:
            assert item.status == DimensionStatus.pending


# ---------------------------------------------------------------------------
# AB: all_dimensions count
# ---------------------------------------------------------------------------

class TestGroupAB_AllDimensions:
    def test_AB01_all_dimensions_has_ten_entries(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        dims = AcceptanceDimensionId.all_dimensions()
        assert len(dims) == 10

    def test_AB02_all_dimensions_no_duplicates(self):
        from core.system_final_acceptance_verdict import AcceptanceDimensionId
        dims = AcceptanceDimensionId.all_dimensions()
        values = [d.value for d in dims]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# AC–AG: Full scenarios
# ---------------------------------------------------------------------------

class TestGroupAC_FullScenarioAllResumed:
    def test_AC01_all_resumed_authoritative(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=5, resumed=5)
        v = _evaluate(e)
        assert v.is_authoritative is True
        assert "formally confirmed" in v.reason.lower()


class TestGroupAD_FullScenarioRecoverable:
    def test_AD01_recoverable_yields_resumable_with_replay(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Restart: 3 tasks dispatched, waiting for device reconnect
        e = _make_evidence(total=3, resumed=0, recoverable=3)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile
        assert v.requires_replay_or_reconcile is True


class TestGroupAE_FullScenarioNeedsReconcile:
    def test_AE01_needs_reconcile_yields_state_restored_not_resumed(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Stale/duplicate snapshot — state visible, reconcile needed
        e = _make_evidence(total=2, needs_reconcile=2)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed
        assert v.state_present_not_resumed is True


class TestGroupAF_FullScenarioInterruptedWithHistory:
    def test_AF01_interrupted_with_history_is_history_only(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Interrupted tasks (need re-issuance) but completed results visible
        e = _make_evidence(
            total=2, interrupted=2,
            result_or_history_visible=True,
        )
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.history_or_evidence_only


class TestGroupAG_FullScenarioAbandonedNoHistory:
    def test_AG01_abandoned_no_history_is_lost(self):
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        # Terminal tasks, no historical evidence
        e = _make_evidence(total=3, abandoned=3, result_or_history_visible=False)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.task_continuity_lost


# ---------------------------------------------------------------------------
# AH: Downgrade scenarios
# ---------------------------------------------------------------------------

class TestGroupAH_DowngradeRecoverableWithPartialRecovery:
    def test_AH01_recoverable_plus_partial_recovery_still_resumable(self):
        """partial_recovery_only affects authoritative only; recoverable → resumable."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=2, recoverable=2, partial_recovery_only=True)
        v = _evaluate(e)
        assert v.continuity_class == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile


class TestGroupAI_DowngradeAllResumedButPartialRecovery:
    def test_AI01_all_resumed_partial_recovery_not_authoritative(self):
        """P0: state present but partial recovery → not authoritative."""
        from core.inflight_task_continuity_taxonomy import InFlightTaskContinuityClass
        e = _make_evidence(total=3, resumed=3, partial_recovery_only=True)
        v = _evaluate(e)
        assert not v.is_authoritative
        # With all resumed and partial_recovery=True:
        # Rule 1 fails (partial_recovery_only=True)
        # Rule 2 fails (recoverable=0)
        # Rule 3: non_terminal_count = resumed=3 > 0 AND recoverable=0 → state_restored_not_resumed
        assert v.continuity_class == InFlightTaskContinuityClass.state_restored_not_resumed


class TestGroupAJ_DowngradeReasonPopulated:
    def test_AJ01_downgrade_reason_nonempty_for_blocked_authoritative(self):
        """Downgrade reason is populated when authoritative was blocked."""
        e = _make_evidence(total=2, resumed=1, recoverable=1)
        v = _evaluate(e)
        # Not authoritative; downgrade reason should say why
        assert v.downgrade_reason != ""

    def test_AJ02_downgrade_reason_empty_for_authoritative(self):
        """No downgrade reason for successful authoritative classification."""
        e = _make_evidence(total=3, resumed=3)
        v = _evaluate(e)
        assert v.is_authoritative is True
        assert v.downgrade_reason == ""
