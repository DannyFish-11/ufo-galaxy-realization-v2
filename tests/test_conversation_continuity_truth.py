#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_conversation_continuity_truth.py
=============================================
PR-CCT: Automated validation for the Conversation Continuity Truth Contract.

Coverage
--------
- Taxonomy (five-tier ConversationContinuityStatus)
- Policy sentinels present and non-empty
- Downgrade semantics (each negative signal triggers correct downgrade)
- No optimistic upgrade when evidence is absent or ambiguous
- restart → history only visible → NOT authoritative continuity
- task restored but no conversation rebind → state_restored_rebind_required
- partial recovery ceiling → at most partial_continuity
- process death → history_only_restored or state_restored_rebind_required
- continuity_lost vs state_restored_rebind_required distinction
- ConversationContinuityEvidence / Verdict / TruthReport serialization
- build_conversation_continuity_verdict convenience function
- evaluate_session_continuity_after_restart (probe-based, no live modules)
- Singleton (reset / get)
"""

from __future__ import annotations

import time
from typing import Optional

import pytest

from core.conversation_continuity_truth import (
    # Sentinels
    CONVERSATION_CONTINUITY_TRUTH_AUTHORITY,
    CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL,
    HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY,
    TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY,
    STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY,
    REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY,
    EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY,
    PROCESS_DEATH_REQUIRES_FULL_REBIND_POLICY,
    PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY_POLICY,
    # Enumerations
    ConversationContinuityStatus,
    # Dataclasses
    ConversationContinuityEvidence,
    ConversationContinuityVerdict,
    ConversationContinuityTruthReport,
    # Classes
    ConversationContinuityTruthContract,
    # Functions
    build_conversation_continuity_verdict,
    evaluate_session_continuity_after_restart,
    get_conversation_continuity_truth_report,
    reset_conversation_continuity_truth_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _full_evidence(
    session_id: str = "sess-test-001",
    session_identity_stable: Optional[bool] = True,
    history_accessible: Optional[bool] = True,
    context_consistent: Optional[bool] = True,
    live_rebind_completed: Optional[bool] = True,
    task_continuity_confirmed: Optional[bool] = None,
    is_post_crash: bool = False,
    is_partial_recovery: bool = False,
) -> ConversationContinuityEvidence:
    """Return an evidence bundle with overridable defaults."""
    return ConversationContinuityEvidence(
        session_id=session_id,
        session_identity_stable=session_identity_stable,
        history_accessible=history_accessible,
        context_consistent=context_consistent,
        live_rebind_completed=live_rebind_completed,
        task_continuity_confirmed=task_continuity_confirmed,
        is_post_crash=is_post_crash,
        is_partial_recovery=is_partial_recovery,
    )


def _contract() -> ConversationContinuityTruthContract:
    return ConversationContinuityTruthContract()


# ===========================================================================
# Group A: Policy sentinel smoke tests
# ===========================================================================

class TestGroupA_PolicySentinels:

    def test_A01_authority_sentinel_present(self):
        assert isinstance(CONVERSATION_CONTINUITY_TRUTH_AUTHORITY, str)
        assert len(CONVERSATION_CONTINUITY_TRUTH_AUTHORITY) > 0

    def test_A02_pr_cct_sentinel_present(self):
        assert isinstance(CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL, str)
        assert "PR-CCT" in CONVERSATION_CONTINUITY_TRUTH_PR_CCT_SENTINEL

    def test_A03_history_not_continuity_sentinel(self):
        assert "HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY" in (
            HISTORY_VISIBLE_IS_NOT_CONVERSATION_CONTINUITY_POLICY
        )

    def test_A04_task_not_conversation_continuity_sentinel(self):
        assert "TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY" in (
            TASK_CONTINUITY_IS_NOT_CONVERSATION_CONTINUITY_POLICY
        )

    def test_A05_state_restored_not_continuity_sentinel(self):
        assert "STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY" in (
            STATE_RESTORED_IS_NOT_CONVERSATION_CONTINUITY_POLICY
        )

    def test_A06_rebind_incomplete_blocks_authoritative_sentinel(self):
        assert "REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY" in (
            REBIND_INCOMPLETE_BLOCKS_AUTHORITATIVE_CONTINUITY_POLICY
        )

    def test_A07_evidence_absent_must_not_upgrade_sentinel(self):
        assert "EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT" in (
            EVIDENCE_ABSENT_MUST_NOT_UPGRADE_VERDICT_POLICY
        )

    def test_A08_process_death_sentinel(self):
        assert "PROCESS_DEATH_REQUIRES_FULL_REBIND" in (
            PROCESS_DEATH_REQUIRES_FULL_REBIND_POLICY
        )

    def test_A09_partial_recovery_sentinel(self):
        assert "PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY" in (
            PARTIAL_RECOVERY_MUST_NOT_CLAIM_FULL_CONTINUITY_POLICY
        )


# ===========================================================================
# Group B: ConversationContinuityStatus taxonomy
# ===========================================================================

class TestGroupB_StatusTaxonomy:

    def test_B01_five_tiers_exist(self):
        statuses = [s.value for s in ConversationContinuityStatus]
        assert "authoritative_continuity_restored" in statuses
        assert "partial_continuity" in statuses
        assert "history_only_restored" in statuses
        assert "state_restored_rebind_required" in statuses
        assert "continuity_lost" in statuses

    def test_B02_is_authoritative_only_for_authoritative(self):
        assert ConversationContinuityStatus.authoritative_continuity_restored.is_authoritative
        for s in ConversationContinuityStatus:
            if s != ConversationContinuityStatus.authoritative_continuity_restored:
                assert not s.is_authoritative

    def test_B03_is_usable_for_authoritative_and_partial(self):
        assert ConversationContinuityStatus.authoritative_continuity_restored.is_usable
        assert ConversationContinuityStatus.partial_continuity.is_usable
        assert not ConversationContinuityStatus.history_only_restored.is_usable
        assert not ConversationContinuityStatus.state_restored_rebind_required.is_usable
        assert not ConversationContinuityStatus.continuity_lost.is_usable

    def test_B04_requires_rebind_for_rebind_tiers(self):
        assert ConversationContinuityStatus.history_only_restored.requires_rebind
        assert ConversationContinuityStatus.state_restored_rebind_required.requires_rebind
        assert not ConversationContinuityStatus.authoritative_continuity_restored.requires_rebind
        assert not ConversationContinuityStatus.partial_continuity.requires_rebind
        assert not ConversationContinuityStatus.continuity_lost.requires_rebind

    def test_B05_is_lost_only_for_continuity_lost(self):
        assert ConversationContinuityStatus.continuity_lost.is_lost
        for s in ConversationContinuityStatus:
            if s != ConversationContinuityStatus.continuity_lost:
                assert not s.is_lost


# ===========================================================================
# Group C: ConversationContinuityEvidence
# ===========================================================================

class TestGroupC_Evidence:

    def test_C01_default_evidence_has_none_fields(self):
        ev = ConversationContinuityEvidence()
        assert ev.session_identity_stable is None
        assert ev.history_accessible is None
        assert ev.context_consistent is None
        assert ev.live_rebind_completed is None
        assert ev.task_continuity_confirmed is None
        assert ev.is_post_crash is False
        assert ev.is_partial_recovery is False

    def test_C02_to_dict_serializes_all_fields(self):
        ev = _full_evidence()
        d = ev.to_dict()
        assert "session_id" in d
        assert "session_identity_stable" in d
        assert "history_accessible" in d
        assert "context_consistent" in d
        assert "live_rebind_completed" in d
        assert "task_continuity_confirmed" in d
        assert "is_post_crash" in d
        assert "is_partial_recovery" in d
        assert "recovery_strategy" in d
        assert "supporting_modules" in d
        assert "evidence_timestamp" in d

    def test_C03_evidence_timestamp_is_recent(self):
        before = time.time()
        ev = ConversationContinuityEvidence()
        after = time.time()
        assert before <= ev.evidence_timestamp <= after


# ===========================================================================
# Group D: Downgrade semantics — authoritative_continuity_restored
# ===========================================================================

class TestGroupD_AuthoritativeContinuity:

    def test_D01_all_positive_yields_authoritative(self):
        verdict = _contract().evaluate(_full_evidence())
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_D02_authoritative_is_not_downgraded_by_task_continuity_true(self):
        ev = _full_evidence(task_continuity_confirmed=True)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_D03_authoritative_status_properties(self):
        verdict = _contract().evaluate(_full_evidence())
        assert verdict.status.is_authoritative
        assert verdict.status.is_usable
        assert not verdict.status.requires_rebind
        assert not verdict.status.is_lost

    def test_D04_authoritative_verdict_has_no_downgrade_reasons(self):
        verdict = _contract().evaluate(_full_evidence())
        assert len(verdict.downgrade_reasons) == 0


# ===========================================================================
# Group E: Downgrade — no session identity → continuity_lost
# ===========================================================================

class TestGroupE_NoSessionIdentity:

    def test_E01_no_identity_yields_continuity_lost(self):
        ev = _full_evidence(session_identity_stable=False)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost

    def test_E02_none_identity_yields_continuity_lost(self):
        ev = _full_evidence(session_identity_stable=None)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost

    def test_E03_no_identity_has_downgrade_reason(self):
        ev = _full_evidence(session_identity_stable=False)
        verdict = _contract().evaluate(ev)
        assert any("session_identity_stable" in r for r in verdict.downgrade_reasons)

    def test_E04_no_identity_even_with_history_accessible_yields_lost(self):
        """History accessible does NOT rescue a missing identity."""
        ev = _full_evidence(
            session_identity_stable=False,
            history_accessible=True,
            live_rebind_completed=True,
            context_consistent=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost


# ===========================================================================
# Group F: Downgrade — rebind not completed
# ===========================================================================

class TestGroupF_RebindNotCompleted:

    def test_F01_rebind_false_with_history_yields_history_only(self):
        """
        Restart scenario: history visible but no live rebind.
        MUST NOT be reported as authoritative continuity.
        """
        ev = _full_evidence(
            live_rebind_completed=False,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored

    def test_F02_rebind_none_with_history_yields_history_only(self):
        """None rebind (unobserved) is treated as not completed."""
        ev = _full_evidence(
            live_rebind_completed=None,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored

    def test_F03_rebind_false_no_history_yields_state_restored_rebind_required(self):
        ev = _full_evidence(
            live_rebind_completed=False,
            history_accessible=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required

    def test_F04_rebind_false_history_none_yields_state_restored_rebind_required(self):
        ev = _full_evidence(
            live_rebind_completed=False,
            history_accessible=None,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required

    def test_F05_rebind_not_completed_blocks_authoritative_with_all_other_positive(self):
        """Even with task continuity confirmed, no rebind → not authoritative."""
        ev = _full_evidence(
            live_rebind_completed=False,
            history_accessible=True,
            context_consistent=True,
            task_continuity_confirmed=True,
        )
        verdict = _contract().evaluate(ev)
        # Must be history_only_restored, NOT authoritative
        assert verdict.status != ConversationContinuityStatus.authoritative_continuity_restored
        assert verdict.status == ConversationContinuityStatus.history_only_restored

    def test_F06_rebind_downgrade_reason_present(self):
        ev = _full_evidence(live_rebind_completed=False, history_accessible=True)
        verdict = _contract().evaluate(ev)
        assert any("live_rebind_completed" in r for r in verdict.downgrade_reasons)


# ===========================================================================
# Group G: Downgrade — history not accessible
# ===========================================================================

class TestGroupG_HistoryNotAccessible:

    def test_G01_rebind_done_no_history_yields_state_restored_rebind_required(self):
        """
        Task restored but conversation history inaccessible after rebind.
        """
        ev = _full_evidence(
            live_rebind_completed=True,
            history_accessible=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required

    def test_G02_rebind_done_history_none_yields_state_restored_rebind_required(self):
        ev = _full_evidence(
            live_rebind_completed=True,
            history_accessible=None,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required

    def test_G03_history_not_accessible_with_task_continuity_still_not_authoritative(self):
        """
        Task continuity confirmed + rebind done but history inaccessible.
        MUST NOT claim authoritative conversation continuity.
        """
        ev = _full_evidence(
            live_rebind_completed=True,
            history_accessible=False,
            task_continuity_confirmed=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status != ConversationContinuityStatus.authoritative_continuity_restored

    def test_G04_history_downgrade_reason_present(self):
        ev = _full_evidence(live_rebind_completed=True, history_accessible=False)
        verdict = _contract().evaluate(ev)
        assert any("history_accessible" in r for r in verdict.downgrade_reasons)


# ===========================================================================
# Group H: Downgrade — context not consistent → partial_continuity
# ===========================================================================

class TestGroupH_ContextInconsistent:

    def test_H01_context_inconsistent_yields_partial_continuity(self):
        ev = _full_evidence(context_consistent=False)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.partial_continuity

    def test_H02_context_none_yields_partial_continuity(self):
        ev = _full_evidence(context_consistent=None)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.partial_continuity

    def test_H03_partial_continuity_is_usable(self):
        ev = _full_evidence(context_consistent=False)
        verdict = _contract().evaluate(ev)
        assert verdict.status.is_usable
        assert not verdict.status.is_authoritative

    def test_H04_context_downgrade_reason_present(self):
        ev = _full_evidence(context_consistent=False)
        verdict = _contract().evaluate(ev)
        assert any("context_consistent" in r for r in verdict.downgrade_reasons)


# ===========================================================================
# Group I: Partial recovery ceiling
# ===========================================================================

class TestGroupI_PartialRecovery:

    def test_I01_partial_recovery_prevents_authoritative(self):
        """
        All other signals positive but is_partial_recovery=True:
        MUST be at most partial_continuity.
        """
        ev = _full_evidence(is_partial_recovery=True)
        verdict = _contract().evaluate(ev)
        assert verdict.status != ConversationContinuityStatus.authoritative_continuity_restored
        assert verdict.status == ConversationContinuityStatus.partial_continuity

    def test_I02_partial_recovery_with_no_history_yields_rebind_required(self):
        ev = _full_evidence(
            is_partial_recovery=True,
            live_rebind_completed=False,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored

    def test_I03_partial_recovery_downgrade_reason_present(self):
        ev = _full_evidence(is_partial_recovery=True)
        verdict = _contract().evaluate(ev)
        assert any("is_partial_recovery" in r for r in verdict.downgrade_reasons)

    def test_I04_partial_recovery_ceiling_applies_even_with_task_continuity(self):
        ev = _full_evidence(
            is_partial_recovery=True,
            task_continuity_confirmed=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.partial_continuity


# ===========================================================================
# Group J: Process death semantics
# ===========================================================================

class TestGroupJ_ProcessDeath:

    def test_J01_process_death_no_rebind_with_history_yields_history_only(self):
        """
        Crash (process death) + history accessible + no rebind
        → history_only_restored (not authoritative).
        """
        ev = _full_evidence(
            is_post_crash=True,
            live_rebind_completed=False,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored
        assert not verdict.status.is_authoritative

    def test_J02_process_death_no_rebind_no_history_yields_state_restored_rebind_required(self):
        ev = _full_evidence(
            is_post_crash=True,
            live_rebind_completed=False,
            history_accessible=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required

    def test_J03_process_death_with_rebind_can_be_authoritative(self):
        """After process death, IF rebind is completed, authoritative is possible."""
        ev = _full_evidence(
            is_post_crash=True,
            live_rebind_completed=True,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_J04_process_death_downgrade_reason_present(self):
        ev = _full_evidence(
            is_post_crash=True,
            live_rebind_completed=False,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        assert any("is_post_crash" in r or "process_death" in r.lower()
                   for r in verdict.downgrade_reasons)

    def test_J05_process_death_no_identity_yields_continuity_lost(self):
        """Process death + no identity = continuity_lost."""
        ev = _full_evidence(
            is_post_crash=True,
            session_identity_stable=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost


# ===========================================================================
# Group K: Task continuity ≠ conversation continuity
# ===========================================================================

class TestGroupK_TaskContinuityIsNotConversationContinuity:

    def test_K01_task_resumed_but_no_rebind_is_not_authoritative(self):
        """
        In-flight task restored/resumed but conversation rebind missing:
        MUST NOT claim authoritative conversation continuity.
        """
        ev = _full_evidence(
            task_continuity_confirmed=True,
            live_rebind_completed=False,
            history_accessible=True,
        )
        verdict = _contract().evaluate(ev)
        # task continuity confirmed does NOT override rebind requirement
        assert verdict.status == ConversationContinuityStatus.history_only_restored
        assert not verdict.status.is_authoritative

    def test_K02_task_confirmed_with_all_positive_yields_authoritative(self):
        """task_continuity_confirmed=True should not downgrade when all else positive."""
        ev = _full_evidence(task_continuity_confirmed=True)
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_K03_task_not_confirmed_with_all_positive_still_authoritative(self):
        """task_continuity_confirmed is contributing, not required."""
        ev = _full_evidence(task_continuity_confirmed=False)
        verdict = _contract().evaluate(ev)
        # task_continuity_confirmed is NOT a blocking requirement
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_K04_task_not_confirmed_with_none_rebind_yields_rebind_required(self):
        ev = _full_evidence(
            task_continuity_confirmed=True,
            live_rebind_completed=None,
            history_accessible=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.state_restored_rebind_required


# ===========================================================================
# Group L: State restored vs continuity restored distinction
# ===========================================================================

class TestGroupL_StateRestoredVsContinuityRestored:

    def test_L01_state_restored_no_rebind_is_not_authoritative(self):
        """
        State restored from durable store after restart (session_id present,
        history accessible) but rebind NOT completed:
        MUST yield history_only_restored, not authoritative.
        """
        ev = ConversationContinuityEvidence(
            session_id="restored-sess",
            session_identity_stable=True,   # found in durable store
            history_accessible=True,         # history loaded
            context_consistent=True,         # metadata looks ok
            live_rebind_completed=False,     # rebind NOT done
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored
        assert not verdict.status.is_authoritative

    def test_L02_state_restored_and_rebind_done_is_authoritative(self):
        ev = ConversationContinuityEvidence(
            session_id="restored-sess-2",
            session_identity_stable=True,
            history_accessible=True,
            context_consistent=True,
            live_rebind_completed=True,     # rebind DONE
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_L03_state_not_found_yields_continuity_lost(self):
        """No state in durable store → no identity → continuity_lost."""
        ev = ConversationContinuityEvidence(
            session_id="missing-sess",
            session_identity_stable=False,  # not found in store
            history_accessible=False,
            context_consistent=False,
            live_rebind_completed=False,
        )
        verdict = _contract().evaluate(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost
        assert verdict.status.is_lost

    def test_L04_continuity_lost_vs_state_restored_rebind_required_distinction(self):
        """
        continuity_lost = no identity; no recovery path at all.
        state_restored_rebind_required = identity present, state present, rebind missing.
        """
        lost_ev = ConversationContinuityEvidence(
            session_identity_stable=False,
        )
        rebind_ev = ConversationContinuityEvidence(
            session_identity_stable=True,
            history_accessible=False,
            live_rebind_completed=False,
        )
        lost_verdict = _contract().evaluate(lost_ev)
        rebind_verdict = _contract().evaluate(rebind_ev)

        assert lost_verdict.status == ConversationContinuityStatus.continuity_lost
        assert rebind_verdict.status == ConversationContinuityStatus.state_restored_rebind_required
        assert lost_verdict.status != rebind_verdict.status


# ===========================================================================
# Group M: ConversationContinuityVerdict serialization
# ===========================================================================

class TestGroupM_VerdictSerialization:

    def test_M01_verdict_to_dict_contains_expected_keys(self):
        ev = _full_evidence()
        verdict = _contract().evaluate(ev)
        d = verdict.to_dict()
        assert "verdict_id" in d
        assert "session_id" in d
        assert "status" in d
        assert "is_authoritative" in d
        assert "is_usable" in d
        assert "requires_rebind" in d
        assert "is_lost" in d
        assert "rationale" in d
        assert "downgrade_reasons" in d
        assert "policy_references" in d
        assert "evidence_summary" in d
        assert "evidence" in d
        assert "evaluated_at" in d

    def test_M02_verdict_id_is_unique(self):
        ev = _full_evidence()
        v1 = _contract().evaluate(ev)
        v2 = _contract().evaluate(ev)
        assert v1.verdict_id != v2.verdict_id

    def test_M03_verdict_status_value_is_string_in_dict(self):
        ev = _full_evidence()
        verdict = _contract().evaluate(ev)
        d = verdict.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "authoritative_continuity_restored"

    def test_M04_verdict_booleans_correct_for_authoritative(self):
        ev = _full_evidence()
        verdict = _contract().evaluate(ev)
        d = verdict.to_dict()
        assert d["is_authoritative"] is True
        assert d["is_usable"] is True
        assert d["requires_rebind"] is False
        assert d["is_lost"] is False

    def test_M05_verdict_booleans_correct_for_continuity_lost(self):
        ev = _full_evidence(session_identity_stable=False)
        verdict = _contract().evaluate(ev)
        d = verdict.to_dict()
        assert d["is_authoritative"] is False
        assert d["is_usable"] is False
        assert d["requires_rebind"] is False
        assert d["is_lost"] is True

    def test_M06_verdict_booleans_correct_for_history_only(self):
        ev = _full_evidence(live_rebind_completed=False, history_accessible=True)
        verdict = _contract().evaluate(ev)
        d = verdict.to_dict()
        assert d["is_authoritative"] is False
        assert d["is_usable"] is False
        assert d["requires_rebind"] is True
        assert d["is_lost"] is False


# ===========================================================================
# Group N: ConversationContinuityTruthReport
# ===========================================================================

class TestGroupN_TruthReport:

    def test_N01_report_to_dict_contains_expected_keys(self):
        report = ConversationContinuityTruthReport()
        d = report.to_dict()
        assert "report_id" in d
        assert "verdicts" in d
        assert "authoritative_count" in d
        assert "partial_count" in d
        assert "history_only_count" in d
        assert "rebind_required_count" in d
        assert "lost_count" in d
        assert "has_any_authoritative" in d
        assert "has_any_lost" in d
        assert "authority_sentinel" in d
        assert "generated_at" in d

    def test_N02_report_counts_correct(self):
        ev_auth = _full_evidence()
        ev_lost = _full_evidence(session_identity_stable=False)
        ev_hist = _full_evidence(live_rebind_completed=False, history_accessible=True)
        ev_part = _full_evidence(is_partial_recovery=True)
        ev_rebind = _full_evidence(live_rebind_completed=False, history_accessible=False)

        contract = _contract()
        verdicts = [
            contract.evaluate(ev_auth),
            contract.evaluate(ev_lost),
            contract.evaluate(ev_hist),
            contract.evaluate(ev_part),
            contract.evaluate(ev_rebind),
        ]
        report = ConversationContinuityTruthReport(
            verdicts=verdicts,
            authoritative_count=sum(
                1 for v in verdicts
                if v.status == ConversationContinuityStatus.authoritative_continuity_restored
            ),
            partial_count=sum(
                1 for v in verdicts
                if v.status == ConversationContinuityStatus.partial_continuity
            ),
            history_only_count=sum(
                1 for v in verdicts
                if v.status == ConversationContinuityStatus.history_only_restored
            ),
            rebind_required_count=sum(
                1 for v in verdicts
                if v.status == ConversationContinuityStatus.state_restored_rebind_required
            ),
            lost_count=sum(
                1 for v in verdicts
                if v.status == ConversationContinuityStatus.continuity_lost
            ),
            has_any_authoritative=any(
                v.status == ConversationContinuityStatus.authoritative_continuity_restored
                for v in verdicts
            ),
            has_any_lost=any(
                v.status == ConversationContinuityStatus.continuity_lost
                for v in verdicts
            ),
        )

        assert report.authoritative_count == 1
        assert report.partial_count == 1
        assert report.history_only_count == 1
        assert report.rebind_required_count == 1
        assert report.lost_count == 1
        assert report.has_any_authoritative is True
        assert report.has_any_lost is True

    def test_N03_report_id_is_unique(self):
        r1 = ConversationContinuityTruthReport()
        r2 = ConversationContinuityTruthReport()
        assert r1.report_id != r2.report_id


# ===========================================================================
# Group O: build_conversation_continuity_verdict convenience function
# ===========================================================================

class TestGroupO_BuildConvenienceFunction:

    def test_O01_build_verdict_returns_verdict_object(self):
        ev = _full_evidence()
        verdict = build_conversation_continuity_verdict(ev)
        assert isinstance(verdict, ConversationContinuityVerdict)

    def test_O02_build_verdict_authoritative_when_all_positive(self):
        ev = _full_evidence()
        verdict = build_conversation_continuity_verdict(ev)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_O03_build_verdict_lost_when_no_identity(self):
        ev = _full_evidence(session_identity_stable=False)
        verdict = build_conversation_continuity_verdict(ev)
        assert verdict.status == ConversationContinuityStatus.continuity_lost

    def test_O04_build_verdict_history_only_when_no_rebind_with_history(self):
        ev = _full_evidence(live_rebind_completed=False, history_accessible=True)
        verdict = build_conversation_continuity_verdict(ev)
        assert verdict.status == ConversationContinuityStatus.history_only_restored

    def test_O05_build_verdict_partial_when_context_inconsistent(self):
        ev = _full_evidence(context_consistent=False)
        verdict = build_conversation_continuity_verdict(ev)
        assert verdict.status == ConversationContinuityStatus.partial_continuity


# ===========================================================================
# Group P: evaluate_session_continuity_after_restart (probe-based)
# ===========================================================================

class TestGroupP_ProbeBasedEvaluation:

    def test_P01_returns_truth_report(self):
        report = evaluate_session_continuity_after_restart()
        assert isinstance(report, ConversationContinuityTruthReport)

    def test_P02_report_has_verdicts_list(self):
        report = evaluate_session_continuity_after_restart()
        assert isinstance(report.verdicts, list)

    def test_P03_report_to_dict_is_serializable(self):
        import json
        report = evaluate_session_continuity_after_restart()
        d = report.to_dict()
        # Should not raise
        json.dumps(d)

    def test_P04_report_has_authority_sentinel(self):
        report = evaluate_session_continuity_after_restart()
        assert CONVERSATION_CONTINUITY_TRUTH_AUTHORITY in report.authority_sentinel

    def test_P05_probe_without_live_modules_does_not_crash(self):
        """Even with no live V2 modules, the probe must not raise."""
        try:
            report = evaluate_session_continuity_after_restart(session_id="unknown-sess")
            assert isinstance(report, ConversationContinuityTruthReport)
        except Exception as exc:
            pytest.fail(
                f"evaluate_session_continuity_after_restart raised unexpectedly: {exc}"
            )

    def test_P06_absent_evidence_does_not_yield_authoritative(self):
        """
        When V2 modules are absent (all evidence None), the probe MUST NOT
        report authoritative_continuity_restored.
        """
        report = evaluate_session_continuity_after_restart()
        # All verdicts should be non-authoritative when evidence is missing
        for v in report.verdicts:
            assert not v.status.is_authoritative, (
                f"Probe produced authoritative verdict despite missing evidence: {v.to_dict()}"
            )


# ===========================================================================
# Group Q: Singleton helpers
# ===========================================================================

class TestGroupQ_Singleton:

    def setup_method(self):
        reset_conversation_continuity_truth_report()

    def teardown_method(self):
        reset_conversation_continuity_truth_report()

    def test_Q01_reset_clears_cache(self):
        r1 = get_conversation_continuity_truth_report()
        reset_conversation_continuity_truth_report()
        r2 = get_conversation_continuity_truth_report()
        # Different report IDs after reset (fresh evaluation)
        assert r1.report_id != r2.report_id

    def test_Q02_get_returns_same_cached_report(self):
        r1 = get_conversation_continuity_truth_report()
        r2 = get_conversation_continuity_truth_report()
        assert r1.report_id == r2.report_id

    def test_Q03_reset_allows_fresh_evaluation(self):
        _ = get_conversation_continuity_truth_report()
        reset_conversation_continuity_truth_report()
        r2 = get_conversation_continuity_truth_report()
        assert isinstance(r2, ConversationContinuityTruthReport)


# ===========================================================================
# Group R: Full restart scenario simulation
# ===========================================================================

class TestGroupR_RestartScenarios:

    def test_R01_restart_history_only_scenario(self):
        """
        Scenario: System restarts.  Session history loaded from disk.
        Live runtime not yet rebound.  MUST be history_only_restored.
        """
        post_restart_evidence = ConversationContinuityEvidence(
            session_id="session-post-restart",
            session_identity_stable=True,   # found in persistence
            history_accessible=True,         # history loaded from disk
            context_consistent=True,         # metadata intact
            live_rebind_completed=False,     # runtime NOT rebound yet
            task_continuity_confirmed=False, # no tasks running
            is_post_crash=False,
            is_partial_recovery=False,
            recovery_strategy="durable_store_restore",
        )
        verdict = build_conversation_continuity_verdict(post_restart_evidence)
        assert verdict.status == ConversationContinuityStatus.history_only_restored
        assert not verdict.status.is_authoritative, (
            "After restart with only history loaded (no rebind), "
            "system MUST NOT claim authoritative conversation continuity"
        )

    def test_R02_crash_no_rebind_scenario(self):
        """
        Scenario: Process crash.  State restored from backup.
        Rebind not yet done.  MUST NOT claim authoritative.
        """
        post_crash_evidence = ConversationContinuityEvidence(
            session_id="session-post-crash",
            session_identity_stable=True,
            history_accessible=True,
            context_consistent=False,       # crash may leave context inconsistent
            live_rebind_completed=False,
            is_post_crash=True,
        )
        verdict = build_conversation_continuity_verdict(post_crash_evidence)
        # Process death + no rebind → at most history_only_restored
        assert verdict.status in (
            ConversationContinuityStatus.history_only_restored,
            ConversationContinuityStatus.state_restored_rebind_required,
        )
        assert not verdict.status.is_authoritative

    def test_R03_partial_recovery_scenario(self):
        """
        Scenario: Partial recovery.  Some sessions restored, some lost.
        Even for restored sessions, MUST be at most partial_continuity.
        """
        partial_recovery_evidence = ConversationContinuityEvidence(
            session_id="session-partial",
            session_identity_stable=True,
            history_accessible=True,
            context_consistent=True,
            live_rebind_completed=True,
            is_partial_recovery=True,       # overall recovery was partial
        )
        verdict = build_conversation_continuity_verdict(partial_recovery_evidence)
        assert verdict.status == ConversationContinuityStatus.partial_continuity
        assert not verdict.status.is_authoritative

    def test_R04_process_death_no_recovery_yields_continuity_lost(self):
        """
        Scenario: Process death with no recovery possible.
        No session identity found after restart.
        """
        irrecoverable_evidence = ConversationContinuityEvidence(
            session_id=None,
            session_identity_stable=False,  # lost entirely
            history_accessible=False,
            context_consistent=False,
            live_rebind_completed=False,
            is_post_crash=True,
        )
        verdict = build_conversation_continuity_verdict(irrecoverable_evidence)
        assert verdict.status == ConversationContinuityStatus.continuity_lost
        assert verdict.status.is_lost

    def test_R05_full_recovery_after_restart_yields_authoritative(self):
        """
        Scenario: Clean restart with full recovery.
        All evidence signals positive.  SHOULD yield authoritative.
        """
        full_recovery_evidence = ConversationContinuityEvidence(
            session_id="session-full-recovery",
            session_identity_stable=True,
            history_accessible=True,
            context_consistent=True,
            live_rebind_completed=True,     # rebind completed
            is_post_crash=False,
            is_partial_recovery=False,
            recovery_strategy="durable_store_restore",
        )
        verdict = build_conversation_continuity_verdict(full_recovery_evidence)
        assert verdict.status == ConversationContinuityStatus.authoritative_continuity_restored

    def test_R06_state_residue_alone_is_not_continuity(self):
        """
        Core PR-CCT requirement: seeing 'state residue' after restart
        (session records visible, history present) MUST NOT be reported
        as authoritative conversation continuity when rebind is missing.
        """
        state_residue_evidence = ConversationContinuityEvidence(
            session_id="state-residue-session",
            session_identity_stable=True,   # state IS visible (residue)
            history_accessible=True,         # history IS visible (residue)
            context_consistent=True,         # context IS present (residue)
            live_rebind_completed=False,     # but NO live rebind
        )
        verdict = build_conversation_continuity_verdict(state_residue_evidence)
        assert verdict.status != ConversationContinuityStatus.authoritative_continuity_restored, (
            "PR-CCT P0 violation: state residue (history visible, state present) "
            "MUST NOT be reported as authoritative conversation continuity restored. "
            "live_rebind_completed=False must prevent authoritative verdict."
        )
        # Should be history_only_restored (best possible without rebind)
        assert verdict.status == ConversationContinuityStatus.history_only_restored
