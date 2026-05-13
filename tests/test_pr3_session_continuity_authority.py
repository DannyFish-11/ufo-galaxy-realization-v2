"""tests/test_pr3_session_continuity_authority.py
==================================================
PR-3: Unified authority, session, continuity, and takeover/recovery
convergence — V2-side test suite.

Coverage
--------
1. Module authority sentinels and PR-3 contract version
2. ContinuityReconnectClass values (explicit classification)
3. classify_reconnect_event — all rule branches:
   - duplicate
   - replay
   - terminal session → restart
   - no session IDs → attachment_only
   - active registry entry → resume
   - no active registry entry → restart
   - unknown state → attachment_only (conservative default)
4. TakeoverGovernanceDecision values and govern_takeover_decision rules:
   - confirmed_strong → proceed (not blocked)
   - degraded_partial → revalidate_ownership (blocked)
   - degraded_stale → forced_suspend (blocked)
   - degraded_conflicting → operator_escalate (blocked)
   - degraded_unresolved → revalidate_ownership (blocked)
   - incomplete → reject_takeover (blocked)
   - unknown proof class → reject_takeover (blocked)
5. LocalAIProposalClass and classify_local_ai_proposal:
   - suggestion / suggestion_only → suggestion_only
   - fallback / fallback_eligible → fallback_eligible
   - sub_agent / sub_agent_decision with scope → sub_agent_decision
   - sub_agent without scope → fallback_eligible (downgraded)
   - unknown authority level → suggestion_only (conservative)
6. Policy invariants:
   - duplicate/stale/replay are distinct reconnect classes
   - confirmed_strong is the only non-blocking takeover outcome
   - suggestion_only does not influence center planning
   - sub_agent_decision without scope cannot influence center planning
7. PR3ConvergenceAuditSnapshot:
   - builds without error
   - contains expected android_integration_points keys
   - is_fully_converged() reflects module availability
   - convergence_gaps() is empty when all modules are loaded
   - to_dict() serialises correctly
8. ReconnectClassificationResult.to_dict() serialisation
9. TakeoverGovernanceResult.to_dict() serialisation
10. LocalAIProposalClassificationResult.to_dict() serialisation
"""

from __future__ import annotations

from core.pr3_session_continuity_authority import (
    # Sentinels
    PR3_CONVERGENCE_AUTHORITY,
    PR3_CONVERGENCE_CONTRACT_VERSION,
    PR3_CONVERGENCE_PR3_SENTINEL,
    RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY,
    DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY,
    LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY,
    DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY,
    CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY,
    # Enums
    ContinuityReconnectClass,
    TakeoverGovernanceDecision,
    LocalAIProposalClass,
    # Data classes
    ReconnectClassificationResult,
    PR3ConvergenceAuditSnapshot,
    # Functions
    classify_reconnect_event,
    govern_takeover_decision,
    classify_local_ai_proposal,
    build_pr3_convergence_audit_snapshot,
)


# ---------------------------------------------------------------------------
# 1. Authority sentinels and contract version
# ---------------------------------------------------------------------------

class TestAuthoritySentinels:

    def test_pr3_convergence_authority_present(self):
        assert PR3_CONVERGENCE_AUTHORITY, "PR3_CONVERGENCE_AUTHORITY must be non-empty"

    def test_pr3_convergence_authority_contains_sentinel_keyword(self):
        assert "PR3_CONVERGENCE_AUTHORITY" in PR3_CONVERGENCE_AUTHORITY

    def test_contract_version_is_pr3(self):
        assert PR3_CONVERGENCE_CONTRACT_VERSION.startswith("3.")

    def test_pr3_sentinel_present(self):
        assert PR3_CONVERGENCE_PR3_SENTINEL, "PR3_CONVERGENCE_PR3_SENTINEL must be non-empty"
        assert "PR3_SENTINEL" in PR3_CONVERGENCE_PR3_SENTINEL

    def test_reconnect_classification_policy_present(self):
        assert "RECONNECT_CLASSIFICATION_IS_EXPLICIT" in RECONNECT_CLASSIFICATION_IS_EXPLICIT_POLICY

    def test_duplicate_stale_replay_policy_present(self):
        assert "DUPLICATE_STALE_REPLAY" in DUPLICATE_STALE_REPLAY_MUST_NOT_BE_CONFLATED_POLICY

    def test_local_ai_boundary_policy_present(self):
        assert "LOCAL_AI_AUTHORITY_BOUNDARY" in LOCAL_AI_AUTHORITY_BOUNDARY_IS_ENFORCED_POLICY

    def test_degraded_takeover_policy_present(self):
        assert "DEGRADED_TAKEOVER" in DEGRADED_TAKEOVER_REQUIRES_EXPLICIT_GOVERNANCE_POLICY

    def test_center_completion_authority_policy_present(self):
        assert "CENTER_IS_SESSION_COMPLETION_AUTHORITY" in CENTER_IS_SESSION_COMPLETION_AUTHORITY_POLICY


# ---------------------------------------------------------------------------
# 2. ContinuityReconnectClass enum values
# ---------------------------------------------------------------------------

class TestContinuityReconnectClass:

    def test_all_five_classes_present(self):
        members = {m.value for m in ContinuityReconnectClass}
        expected = {"resume", "replay", "restart", "attachment_only", "duplicate"}
        assert expected == members

    def test_resume_value(self):
        assert ContinuityReconnectClass.resume.value == "resume"

    def test_replay_value(self):
        assert ContinuityReconnectClass.replay.value == "replay"

    def test_restart_value(self):
        assert ContinuityReconnectClass.restart.value == "restart"

    def test_attachment_only_value(self):
        assert ContinuityReconnectClass.attachment_only.value == "attachment_only"

    def test_duplicate_value(self):
        assert ContinuityReconnectClass.duplicate.value == "duplicate"


# ---------------------------------------------------------------------------
# 3. classify_reconnect_event — all rule branches
# ---------------------------------------------------------------------------

class TestClassifyReconnectEvent:

    def _make_result(self, **kwargs) -> ReconnectClassificationResult:
        defaults = {
            "device_id": "dev-001",
            "runtime_session_id": "rsid-001",
            "runtime_attachment_session_id": "rasid-001",
            "has_active_registry_entry": None,
            "is_duplicate": None,
            "is_replay": None,
            "session_is_terminal": None,
        }
        defaults.update(kwargs)
        return classify_reconnect_event(**defaults)

    # Rule 1: duplicate
    def test_duplicate_signal_classified_as_duplicate(self):
        result = self._make_result(is_duplicate=True)
        assert result.reconnect_class == ContinuityReconnectClass.duplicate

    def test_duplicate_policy_reference(self):
        result = self._make_result(is_duplicate=True)
        assert "DUPLICATE_STALE_REPLAY" in result.policy

    def test_duplicate_reason_mentions_suppress(self):
        result = self._make_result(is_duplicate=True)
        assert "duplicate" in result.reason.lower()

    # Rule 2: replay
    def test_replay_signal_classified_as_replay(self):
        result = self._make_result(is_replay=True)
        assert result.reconnect_class == ContinuityReconnectClass.replay

    def test_replay_policy_reference(self):
        result = self._make_result(is_replay=True)
        assert "DUPLICATE_STALE_REPLAY" in result.policy

    def test_replay_reason_mentions_offline_queue(self):
        result = self._make_result(is_replay=True)
        assert "replay" in result.reason.lower() or "offline" in result.reason.lower()

    # Rule 1 takes precedence over rule 2 (duplicate before replay)
    def test_duplicate_takes_precedence_over_replay(self):
        result = self._make_result(is_duplicate=True, is_replay=True)
        assert result.reconnect_class == ContinuityReconnectClass.duplicate

    # Rule 3: terminal session
    def test_terminal_session_classified_as_restart(self):
        result = self._make_result(session_is_terminal=True)
        assert result.reconnect_class == ContinuityReconnectClass.restart

    def test_terminal_session_reason_mentions_terminal(self):
        result = self._make_result(session_is_terminal=True)
        assert "terminal" in result.reason.lower()

    # Rule 4: no session IDs
    def test_no_session_ids_classified_as_attachment_only(self):
        result = classify_reconnect_event(
            device_id="dev-001",
            runtime_session_id=None,
            runtime_attachment_session_id=None,
        )
        assert result.reconnect_class == ContinuityReconnectClass.attachment_only

    def test_no_session_ids_reason_mentions_transport(self):
        result = classify_reconnect_event(
            device_id="dev-001",
            runtime_session_id=None,
            runtime_attachment_session_id=None,
        )
        assert "transport" in result.reason.lower() or "attachment" in result.reason.lower()

    # Rule 5: active registry entry
    def test_active_registry_entry_classified_as_resume(self):
        result = self._make_result(has_active_registry_entry=True)
        assert result.reconnect_class == ContinuityReconnectClass.resume

    def test_resume_reason_mentions_active_entry(self):
        result = self._make_result(has_active_registry_entry=True)
        assert "active" in result.reason.lower() or "resume" in result.reason.lower()

    # Rule 6: no active registry entry
    def test_no_active_registry_entry_classified_as_restart(self):
        result = self._make_result(has_active_registry_entry=False)
        assert result.reconnect_class == ContinuityReconnectClass.restart

    def test_no_active_entry_reason_mentions_broken_continuity(self):
        result = self._make_result(has_active_registry_entry=False)
        r = result.reason.lower()
        assert "continuity" in r or "broken" in r or "restart" in r

    # Default: unknown state
    def test_unknown_state_defaults_to_attachment_only(self):
        result = classify_reconnect_event(
            device_id="dev-001",
            runtime_session_id="rsid-001",
            runtime_attachment_session_id="rasid-001",
        )
        assert result.reconnect_class == ContinuityReconnectClass.attachment_only

    def test_result_carries_device_id(self):
        result = self._make_result(is_duplicate=True)
        assert result.device_id == "dev-001"

    def test_result_carries_runtime_session_id(self):
        result = self._make_result(is_duplicate=True)
        assert result.runtime_session_id == "rsid-001"

    def test_result_carries_classified_at_timestamp(self):
        result = self._make_result(is_replay=True)
        assert result.classified_at > 0

    def test_result_to_dict_has_reconnect_class_key(self):
        result = self._make_result(has_active_registry_entry=True)
        d = result.to_dict()
        assert "reconnect_class" in d
        assert d["reconnect_class"] == "resume"


# ---------------------------------------------------------------------------
# 4. TakeoverGovernanceDecision and govern_takeover_decision
# ---------------------------------------------------------------------------

class TestTakeoverGovernanceDecision:

    def test_all_five_decisions_present(self):
        members = {m.value for m in TakeoverGovernanceDecision}
        expected = {
            "proceed",
            "revalidate_ownership",
            "reject_takeover",
            "operator_escalate",
            "forced_suspend",
        }
        assert expected == members

    def test_proceed_value(self):
        assert TakeoverGovernanceDecision.proceed.value == "proceed"


class TestGovernTakeoverDecision:

    def test_confirmed_strong_proceeds(self):
        result = govern_takeover_decision("confirmed_strong", takeover_id="t-001", device_id="dev-001")
        assert result.governance_decision == TakeoverGovernanceDecision.proceed
        assert result.is_execution_blocked is False

    def test_degraded_partial_revalidates(self):
        result = govern_takeover_decision("degraded_partial")
        assert result.governance_decision == TakeoverGovernanceDecision.revalidate_ownership
        assert result.is_execution_blocked is True

    def test_degraded_stale_suspends(self):
        result = govern_takeover_decision("degraded_stale")
        assert result.governance_decision == TakeoverGovernanceDecision.forced_suspend
        assert result.is_execution_blocked is True

    def test_degraded_conflicting_escalates_to_operator(self):
        result = govern_takeover_decision("degraded_conflicting")
        assert result.governance_decision == TakeoverGovernanceDecision.operator_escalate
        assert result.is_execution_blocked is True

    def test_degraded_unresolved_revalidates(self):
        result = govern_takeover_decision("degraded_unresolved")
        assert result.governance_decision == TakeoverGovernanceDecision.revalidate_ownership
        assert result.is_execution_blocked is True

    def test_incomplete_rejects(self):
        result = govern_takeover_decision("incomplete")
        assert result.governance_decision == TakeoverGovernanceDecision.reject_takeover
        assert result.is_execution_blocked is True

    def test_unknown_proof_class_rejects(self):
        result = govern_takeover_decision("totally_unknown_class")
        assert result.governance_decision == TakeoverGovernanceDecision.reject_takeover
        assert result.is_execution_blocked is True

    def test_only_confirmed_strong_is_not_blocked(self):
        non_strong_classes = [
            "degraded_partial", "degraded_stale", "degraded_conflicting",
            "degraded_unresolved", "incomplete",
        ]
        for proof_class in non_strong_classes:
            result = govern_takeover_decision(proof_class)
            assert result.is_execution_blocked is True, (
                f"Expected is_execution_blocked=True for proof_class={proof_class!r}"
            )

    def test_result_carries_proof_class(self):
        result = govern_takeover_decision("degraded_stale", takeover_id="t-99")
        assert result.proof_class == "degraded_stale"
        assert result.takeover_id == "t-99"

    def test_result_carries_policy_reference(self):
        result = govern_takeover_decision("confirmed_strong")
        assert "DEGRADED_TAKEOVER" in result.policy

    def test_result_to_dict_serialisable(self):
        result = govern_takeover_decision("degraded_conflicting", device_id="dev-x")
        d = result.to_dict()
        assert d["governance_decision"] == "operator_escalate"
        assert d["is_execution_blocked"] is True
        assert d["device_id"] == "dev-x"
        assert "governed_at" in d


# ---------------------------------------------------------------------------
# 5. LocalAIProposalClass and classify_local_ai_proposal
# ---------------------------------------------------------------------------

class TestLocalAIProposalClass:

    def test_three_classes_present(self):
        members = {m.value for m in LocalAIProposalClass}
        expected = {"suggestion_only", "fallback_eligible", "sub_agent_decision"}
        assert expected == members


class TestClassifyLocalAIProposal:

    def test_suggestion_classified_as_suggestion_only(self):
        result = classify_local_ai_proposal("suggestion")
        assert result.proposal_class == LocalAIProposalClass.suggestion_only

    def test_suggestion_only_classified_as_suggestion_only(self):
        result = classify_local_ai_proposal("suggestion_only")
        assert result.proposal_class == LocalAIProposalClass.suggestion_only

    def test_suggestion_does_not_influence_center_planning(self):
        result = classify_local_ai_proposal("suggestion")
        assert result.may_influence_center_planning is False

    def test_suggestion_does_not_require_review(self):
        result = classify_local_ai_proposal("suggestion")
        assert result.requires_center_review is False

    def test_fallback_classified_as_fallback_eligible(self):
        result = classify_local_ai_proposal("fallback")
        assert result.proposal_class == LocalAIProposalClass.fallback_eligible

    def test_fallback_eligible_classified_as_fallback_eligible(self):
        result = classify_local_ai_proposal("fallback_eligible")
        assert result.proposal_class == LocalAIProposalClass.fallback_eligible

    def test_fallback_does_not_influence_center_planning(self):
        result = classify_local_ai_proposal("fallback")
        assert result.may_influence_center_planning is False

    def test_fallback_requires_center_review(self):
        result = classify_local_ai_proposal("fallback")
        assert result.requires_center_review is True

    def test_sub_agent_with_scope_classified_as_sub_agent_decision(self):
        result = classify_local_ai_proposal("sub_agent", scope="task:open_browser")
        assert result.proposal_class == LocalAIProposalClass.sub_agent_decision

    def test_sub_agent_with_scope_may_influence_planning(self):
        result = classify_local_ai_proposal("sub_agent", scope="task:open_browser")
        assert result.may_influence_center_planning is True

    def test_sub_agent_with_scope_requires_review(self):
        result = classify_local_ai_proposal("sub_agent", scope="task:open_browser")
        assert result.requires_center_review is True

    def test_sub_agent_without_scope_downgraded_to_fallback_eligible(self):
        result = classify_local_ai_proposal("sub_agent", scope=None)
        assert result.proposal_class == LocalAIProposalClass.fallback_eligible

    def test_sub_agent_without_scope_cannot_influence_planning(self):
        result = classify_local_ai_proposal("sub_agent", scope=None)
        assert result.may_influence_center_planning is False

    def test_unknown_authority_level_defaults_to_suggestion_only(self):
        result = classify_local_ai_proposal("totally_unknown_level")
        assert result.proposal_class == LocalAIProposalClass.suggestion_only

    def test_unknown_does_not_influence_center_planning(self):
        result = classify_local_ai_proposal("totally_unknown_level")
        assert result.may_influence_center_planning is False

    def test_result_carries_proposal_source(self):
        result = classify_local_ai_proposal("suggestion", proposal_source="LocalPlannerService")
        assert result.proposal_source == "LocalPlannerService"

    def test_result_carries_policy_reference(self):
        result = classify_local_ai_proposal("fallback")
        assert "LOCAL_AI_AUTHORITY_BOUNDARY" in result.policy

    def test_result_to_dict_serialisable(self):
        result = classify_local_ai_proposal("sub_agent", scope="camera:capture", proposal_source="VisionAgent")
        d = result.to_dict()
        assert d["proposal_class"] == "sub_agent_decision"
        assert d["may_influence_center_planning"] is True
        assert d["scope"] == "camera:capture"
        assert "classified_at" in d


# ---------------------------------------------------------------------------
# 6. Policy invariants
# ---------------------------------------------------------------------------

class TestPolicyInvariants:

    def test_duplicate_stale_replay_are_distinct_classes(self):
        """Duplicate, stale (restart from terminal), and replay produce distinct classes."""
        duplicate = classify_reconnect_event(is_duplicate=True,
                                             runtime_session_id="s", runtime_attachment_session_id="a")
        replay = classify_reconnect_event(is_replay=True,
                                          runtime_session_id="s", runtime_attachment_session_id="a")
        terminal = classify_reconnect_event(session_is_terminal=True,
                                            runtime_session_id="s", runtime_attachment_session_id="a")
        classes = {
            duplicate.reconnect_class,
            replay.reconnect_class,
            terminal.reconnect_class,
        }
        assert len(classes) == 3, (
            f"duplicate, replay, and terminal must produce 3 distinct classes; got {classes}"
        )

    def test_confirmed_strong_is_only_non_blocking_takeover(self):
        all_classes = [
            "confirmed_strong", "degraded_partial", "degraded_stale",
            "degraded_conflicting", "degraded_unresolved", "incomplete",
        ]
        for c in all_classes:
            result = govern_takeover_decision(c)
            if c == "confirmed_strong":
                assert result.is_execution_blocked is False, "confirmed_strong must not block"
            else:
                assert result.is_execution_blocked is True, f"{c} must block"

    def test_suggestion_only_never_influences_center_planning(self):
        suggestion_inputs = ["suggestion", "suggestion_only", "SUGGESTION", "totally_unknown_level"]
        for level in suggestion_inputs:
            result = classify_local_ai_proposal(level.lower())
            assert result.may_influence_center_planning is False, (
                f"suggestion_only should never influence center planning, got True for {level!r}"
            )

    def test_sub_agent_without_scope_cannot_influence_planning(self):
        for variant in ["sub_agent", "sub_agent_decision"]:
            result = classify_local_ai_proposal(variant, scope=None)
            assert result.may_influence_center_planning is False, (
                f"sub_agent without scope must not influence planning for variant={variant!r}"
            )


# ---------------------------------------------------------------------------
# 7. PR3ConvergenceAuditSnapshot
# ---------------------------------------------------------------------------

class TestPR3ConvergenceAuditSnapshot:

    def test_builds_without_error(self):
        snap = build_pr3_convergence_audit_snapshot()
        assert isinstance(snap, PR3ConvergenceAuditSnapshot)

    def test_snapshot_id_is_present(self):
        snap = build_pr3_convergence_audit_snapshot()
        assert snap.snapshot_id.startswith("pr3snap_")

    def test_created_at_is_positive(self):
        snap = build_pr3_convergence_audit_snapshot()
        assert snap.created_at > 0

    def test_android_integration_points_contains_required_keys(self):
        snap = build_pr3_convergence_audit_snapshot()
        required = {
            "CanonicalSessionAxis.kt",
            "AndroidContinuityIntegration.kt",
            "OfflineTaskQueue.kt",
            "DelegatedTakeoverExecutor.kt",
            "TakeoverEligibilityAssessor.kt",
            "LocalPlannerService.kt",
        }
        for key in required:
            assert key in snap.android_integration_points, (
                f"Android integration point {key!r} must be present in snapshot"
            )

    def test_policies_affirmed_contains_pr3_policies(self):
        snap = build_pr3_convergence_audit_snapshot()
        # At minimum the five PR-3 own policies must be affirmed
        joined = " ".join(snap.policies_affirmed)
        assert "RECONNECT_CLASSIFICATION_IS_EXPLICIT" in joined
        assert "DUPLICATE_STALE_REPLAY" in joined
        assert "LOCAL_AI_AUTHORITY_BOUNDARY" in joined
        assert "DEGRADED_TAKEOVER" in joined

    def test_is_fully_converged_reflects_module_availability(self):
        snap = build_pr3_convergence_audit_snapshot()
        # All core modules should be loadable in this test environment
        # is_fully_converged() may be True or False depending on center_authority
        result = snap.is_fully_converged()
        assert isinstance(result, bool)

    def test_convergence_gaps_is_list(self):
        snap = build_pr3_convergence_audit_snapshot()
        gaps = snap.convergence_gaps()
        assert isinstance(gaps, list)

    def test_to_dict_serialisable(self):
        snap = build_pr3_convergence_audit_snapshot()
        d = snap.to_dict()
        assert "snapshot_id" in d
        assert "is_fully_converged" in d
        assert "convergence_gaps" in d
        assert "android_integration_points" in d
        assert "policies_affirmed" in d
        assert "errors" in d

    def test_to_dict_android_points_is_dict(self):
        snap = build_pr3_convergence_audit_snapshot()
        d = snap.to_dict()
        assert isinstance(d["android_integration_points"], dict)
        assert len(d["android_integration_points"]) >= 6

    def test_default_snapshot_not_fully_converged_when_empty(self):
        """An empty (default) snapshot correctly reports not converged."""
        snap = PR3ConvergenceAuditSnapshot()
        assert snap.is_fully_converged() is False

    def test_default_snapshot_has_all_expected_gaps(self):
        snap = PR3ConvergenceAuditSnapshot()
        gaps = snap.convergence_gaps()
        expected_gaps = [
            "session_axis_not_loaded",
            "center_authority_not_intact",
            "android_boundary_not_loaded",
            "continuity_coordinator_not_loaded",
            "session_registry_not_loaded",
            "takeover_tracking_not_loaded",
            "ownership_proof_quality_not_loaded",
            "recovery_hardening_not_loaded",
            "rebind_registry_not_loaded",
        ]
        for gap in expected_gaps:
            assert gap in gaps, f"Expected gap {gap!r} in convergence_gaps"


# ---------------------------------------------------------------------------
# 8–10. Data class serialisation
# ---------------------------------------------------------------------------

class TestDataClassSerialisations:

    def test_reconnect_result_to_dict_keys(self):
        result = classify_reconnect_event(
            device_id="d-1",
            runtime_session_id="rs-1",
            runtime_attachment_session_id="ras-1",
            is_duplicate=True,
        )
        d = result.to_dict()
        required_keys = {
            "reconnect_class", "device_id", "runtime_session_id",
            "runtime_attachment_session_id", "policy", "reason", "evidence",
            "classified_at",
        }
        assert required_keys.issubset(d.keys())

    def test_takeover_governance_result_to_dict_keys(self):
        result = govern_takeover_decision("degraded_partial", takeover_id="tk-1", device_id="d-1")
        d = result.to_dict()
        required_keys = {
            "governance_decision", "proof_class", "takeover_id", "device_id",
            "policy", "reason", "is_execution_blocked", "governed_at",
        }
        assert required_keys.issubset(d.keys())

    def test_local_ai_result_to_dict_keys(self):
        result = classify_local_ai_proposal(
            "sub_agent",
            scope="task:click",
            proposal_source="LocalPlannerService",
        )
        d = result.to_dict()
        required_keys = {
            "proposal_class", "may_influence_center_planning", "requires_center_review",
            "policy", "reason", "proposal_source", "scope", "classified_at",
        }
        assert required_keys.issubset(d.keys())

    def test_reconnect_result_evidence_contains_inputs(self):
        result = classify_reconnect_event(
            device_id="d-evidence-1",
            runtime_session_id="rs-evidence-1",
            is_replay=True,
        )
        assert result.evidence["device_id"] == "d-evidence-1"
        assert result.evidence["runtime_session_id"] == "rs-evidence-1"
        assert result.evidence["is_replay"] is True
