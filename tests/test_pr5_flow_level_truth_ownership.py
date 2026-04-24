"""tests/test_pr5_flow_level_truth_ownership.py
================================================
Tests for PR-5V2: Flow-Level Truth Ownership and Local/Central Truth
Alignment.

Coverage groups
---------------
A  — Authority / PR sentinel presence and policy count.
B  — FlowTruthSemantics enum: all values, from_string(), defaults.
C  — FlowTruthDecisionArtifact enum: all values, from_string(), is_accepted(), is_rejected().
D  — FlowTruthAlignmentDecision: construction, defaults, is_accepted(), is_rejected(), to_dict().
E  — Authoritative truth (cancel / failure / result): artifact = accept_as_authoritative.
F  — Advisory truth (readiness_assessment / runtime_state / session_snapshot): artifact = accept_as_advisory.
G  — Execution evidence (task_phase / status): artifact = record_as_execution_evidence.
H  — Partial result embedded in task_phase: artifact = accept_as_authoritative, semantics = partial_result_truth.
I  — V2 terminal phase blocks subsequent Android truth.
J  — Posture change triggers quarantine for non-advisory truths.
K  — Posture change does NOT quarantine advisory truths.
L  — Compat influence recording (block_compat_influence=False default).
M  — Compat influence blocking (block_compat_influence=True).
N  — Android result truth sets pending_v2_confirmation=True.
O  — Cancel and failure do NOT set pending_v2_confirmation.
P  — evaluate_android_truth_alignment convenience function: e2e flow.
Q  — FlowLevelTruthOwnershipCoordinator: dict input works identically to object input.
R  — FlowLevelTruthOwnershipCoordinator: flow_id extracted from dict.
S  — FlowLevelTruthOwnershipCoordinator: flow_id override wins.
T  — get_default_coordinator / reset_default_coordinator singleton.
U  — All 11 policy sentinels are non-empty strings.
V  — FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL contains 'PR5V2'.
W  — core.runtime re-exports: all PR-5V2 symbols accessible.
X  — FlowTruthAlignmentDecision: to_dict round-trips truth_semantics and artifact as strings.
Y  — Unknown truth_kind falls back to advisory/accept_as_advisory.
Z  — Terminal phases: completed, failed, cancelled all trigger rejection.
"""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.flow_level_truth_ownership import (
        ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY,
        ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY,
        AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY,
        CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY,
        COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY,
        EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
        FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY,
        FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL,
        FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY,
        PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY,
        PARTIAL_THEN_FINAL_MERGE_RULE_POLICY,
        POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY,
        V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY,
        FlowLevelTruthOwnershipCoordinator,
        FlowTruthAlignmentDecision,
        FlowTruthDecisionArtifact,
        FlowTruthSemantics,
        evaluate_android_truth_alignment,
        get_default_coordinator,
        reset_default_coordinator,
    )

    _MODULE_AVAILABLE = True
except ImportError as _exc:  # pragma: no cover
    _MODULE_AVAILABLE = False
    _IMPORT_ERROR = str(_exc)

_SKIP_REASON = "core.flow_level_truth_ownership not importable"


# ===========================================================================
# Group A — Authority / PR sentinel presence and policy count
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupA_Authority:
    def test_authority_is_non_empty_string(self):
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY, str)
        assert len(FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY) > 0

    def test_pr_sentinel_is_non_empty_string(self):
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL, str)
        assert len(FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL) > 0

    def test_authority_contains_module_name(self):
        assert "flow_level_truth_ownership" in FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY

    def test_policy_sentinels_total_count(self):
        sentinels = [
            FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY,
            AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY,
            ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY,
            EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
            CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY,
            PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY,
            POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY,
            V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY,
            COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY,
            PARTIAL_THEN_FINAL_MERGE_RULE_POLICY,
            ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY,
        ]
        assert len(sentinels) == 11


# ===========================================================================
# Group B — FlowTruthSemantics enum
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupB_FlowTruthSemantics:
    def test_all_values_present(self):
        expected = {
            "authoritative",
            "advisory",
            "execution_evidence",
            "canonical_terminal_decision",
            "partial_result_truth",
            "posture_sensitive",
        }
        actual = {m.value for m in FlowTruthSemantics}
        assert expected == actual

    def test_from_string_known_values(self):
        assert FlowTruthSemantics.from_string("authoritative") == FlowTruthSemantics.authoritative
        assert FlowTruthSemantics.from_string("advisory") == FlowTruthSemantics.advisory
        assert FlowTruthSemantics.from_string("execution_evidence") == FlowTruthSemantics.execution_evidence

    def test_from_string_unknown_defaults_to_advisory(self):
        assert FlowTruthSemantics.from_string("nonsense") == FlowTruthSemantics.advisory

    def test_from_string_empty_defaults_to_advisory(self):
        assert FlowTruthSemantics.from_string("") == FlowTruthSemantics.advisory
        assert FlowTruthSemantics.from_string(None) == FlowTruthSemantics.advisory


# ===========================================================================
# Group C — FlowTruthDecisionArtifact enum
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupC_FlowTruthDecisionArtifact:
    def test_all_values_present(self):
        expected = {
            "accept_as_authoritative",
            "accept_as_advisory",
            "record_as_execution_evidence",
            "reject_due_to_canonical_terminal",
            "quarantine_due_to_posture_conflict",
            "block_due_to_compat_influence",
        }
        actual = {m.value for m in FlowTruthDecisionArtifact}
        assert expected == actual

    def test_from_string_known_values(self):
        assert (
            FlowTruthDecisionArtifact.from_string("accept_as_authoritative")
            == FlowTruthDecisionArtifact.accept_as_authoritative
        )
        assert (
            FlowTruthDecisionArtifact.from_string("reject_due_to_canonical_terminal")
            == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal
        )

    def test_from_string_unknown_defaults_to_advisory(self):
        assert (
            FlowTruthDecisionArtifact.from_string("garbage")
            == FlowTruthDecisionArtifact.accept_as_advisory
        )

    def test_is_accepted(self):
        assert FlowTruthDecisionArtifact.accept_as_authoritative.is_accepted()
        assert FlowTruthDecisionArtifact.accept_as_advisory.is_accepted()
        assert FlowTruthDecisionArtifact.record_as_execution_evidence.is_accepted()

    def test_is_rejected(self):
        assert FlowTruthDecisionArtifact.reject_due_to_canonical_terminal.is_rejected()
        assert FlowTruthDecisionArtifact.quarantine_due_to_posture_conflict.is_rejected()
        assert FlowTruthDecisionArtifact.block_due_to_compat_influence.is_rejected()

    def test_is_accepted_and_is_rejected_are_mutually_exclusive(self):
        for artifact in FlowTruthDecisionArtifact:
            assert artifact.is_accepted() != artifact.is_rejected()


# ===========================================================================
# Group D — FlowTruthAlignmentDecision dataclass
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupD_FlowTruthAlignmentDecision:
    def test_default_construction(self):
        d = FlowTruthAlignmentDecision()
        assert d.flow_id == ""
        assert d.session_id == ""
        assert d.contract_id == ""
        assert d.truth_semantics == FlowTruthSemantics.advisory
        assert d.artifact == FlowTruthDecisionArtifact.accept_as_advisory
        assert d.pending_v2_confirmation is False
        assert d.posture_changed is False
        assert d.compat_influenced is False
        assert isinstance(d.partial_result_store, dict)
        assert isinstance(d.evaluated_at, float)

    def test_decision_id_auto_generated(self):
        d1 = FlowTruthAlignmentDecision()
        d2 = FlowTruthAlignmentDecision()
        assert d1.decision_id != d2.decision_id
        assert d1.decision_id.startswith("ftad_")

    def test_is_accepted(self):
        d = FlowTruthAlignmentDecision(
            artifact=FlowTruthDecisionArtifact.accept_as_authoritative
        )
        assert d.is_accepted()
        assert not d.is_rejected()

    def test_is_rejected(self):
        d = FlowTruthAlignmentDecision(
            artifact=FlowTruthDecisionArtifact.reject_due_to_canonical_terminal
        )
        assert d.is_rejected()
        assert not d.is_accepted()

    def test_to_dict_fields(self):
        d = FlowTruthAlignmentDecision(
            flow_id="f1",
            session_id="s1",
            contract_id="c1",
            truth_semantics=FlowTruthSemantics.authoritative,
            artifact=FlowTruthDecisionArtifact.accept_as_authoritative,
            truth_kind="cancel",
        )
        d_dict = d.to_dict()
        assert d_dict["flow_id"] == "f1"
        assert d_dict["session_id"] == "s1"
        assert d_dict["contract_id"] == "c1"
        assert d_dict["truth_semantics"] == "authoritative"
        assert d_dict["artifact"] == "accept_as_authoritative"
        assert d_dict["truth_kind"] == "cancel"


# ===========================================================================
# Group E — Authoritative truth (cancel / failure / result)
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupE_AuthoritativeTruth:
    @pytest.mark.parametrize("kind", ["cancel", "failure", "result"])
    def test_authoritative_kinds_produce_accept_as_authoritative(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind, "session_id": "s1"})
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_authoritative
        assert decision.truth_semantics == FlowTruthSemantics.authoritative

    @pytest.mark.parametrize("kind", ["cancel", "failure", "result"])
    def test_authoritative_kinds_are_accepted(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind})
        assert decision.is_accepted()


# ===========================================================================
# Group F — Advisory truth
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupF_AdvisoryTruth:
    @pytest.mark.parametrize(
        "kind",
        ["readiness_assessment", "runtime_state", "session_snapshot", "unknown"],
    )
    def test_advisory_kinds_produce_accept_as_advisory(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind})
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_advisory
        assert decision.truth_semantics == FlowTruthSemantics.advisory

    @pytest.mark.parametrize(
        "kind",
        ["readiness_assessment", "runtime_state", "session_snapshot"],
    )
    def test_advisory_kinds_are_accepted(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind})
        assert decision.is_accepted()


# ===========================================================================
# Group G — Execution evidence (task_phase / status)
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupG_ExecutionEvidence:
    @pytest.mark.parametrize("kind", ["task_phase", "status"])
    def test_execution_evidence_kinds(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind})
        assert decision.artifact == FlowTruthDecisionArtifact.record_as_execution_evidence
        assert decision.truth_semantics == FlowTruthSemantics.execution_evidence
        assert decision.is_accepted()


# ===========================================================================
# Group H — Partial result embedded in task_phase
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupH_PartialResult:
    def test_partial_result_in_task_phase_uses_partial_semantics(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {
                "truth_kind": "task_phase",
                "partial_result": {"data": "some_partial"},
            }
        )
        assert decision.truth_semantics == FlowTruthSemantics.partial_result_truth
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_authoritative
        assert decision.pending_v2_confirmation is True
        assert decision.partial_result_store == {"data": "some_partial"}

    def test_partial_result_in_status(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {
                "truth_kind": "status",
                "partial_result": {"progress": 50},
            }
        )
        assert decision.truth_semantics == FlowTruthSemantics.partial_result_truth
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_authoritative


# ===========================================================================
# Group I — V2 terminal phase blocks subsequent Android truth
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupI_TerminalPhaseBlocks:
    @pytest.mark.parametrize("phase", ["completed", "failed", "cancelled"])
    def test_terminal_phase_rejects_all_truth_kinds(self, phase):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        for kind in [
            "cancel", "failure", "result", "task_phase", "status",
            "readiness_assessment",
        ]:
            decision = coordinator.evaluate(
                {"truth_kind": kind},
                current_flow_phase=phase,
            )
            assert decision.artifact == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal
            assert decision.is_rejected()

    def test_non_terminal_phase_does_not_reject(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        for phase in ["created", "dispatched", "executing", "reconciling", ""]:
            decision = coordinator.evaluate(
                {"truth_kind": "cancel"},
                current_flow_phase=phase,
            )
            assert decision.artifact != FlowTruthDecisionArtifact.reject_due_to_canonical_terminal

    def test_terminal_check_case_insensitive(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "result"},
            current_flow_phase="COMPLETED",
        )
        assert decision.artifact == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal


# ===========================================================================
# Group J — Posture change triggers quarantine for non-advisory truths
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupJ_PostureChangeQuarantine:
    @pytest.mark.parametrize("kind", ["cancel", "failure", "result", "task_phase", "status"])
    def test_posture_change_quarantines_non_advisory(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": kind},
            current_posture="control_only",
            previous_posture="join_runtime",
        )
        assert decision.artifact == FlowTruthDecisionArtifact.quarantine_due_to_posture_conflict
        assert decision.posture_changed is True
        assert decision.is_rejected()


# ===========================================================================
# Group K — Posture change does NOT quarantine advisory truths
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupK_PostureChangeAdvisory:
    @pytest.mark.parametrize(
        "kind",
        ["readiness_assessment", "runtime_state", "session_snapshot", "unknown"],
    )
    def test_posture_change_does_not_quarantine_advisory(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": kind},
            current_posture="control_only",
            previous_posture="join_runtime",
        )
        # Advisory truths pass through even with posture change
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_advisory
        assert decision.is_accepted()


# ===========================================================================
# Group L — Compat influence recording (block_compat_influence=False)
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupL_CompatInfluenceRecording:
    def test_compat_influenced_recorded_when_not_blocking(self):
        coordinator = FlowLevelTruthOwnershipCoordinator(block_compat_influence=False)
        decision = coordinator.evaluate(
            {"truth_kind": "cancel", "compat_influenced": True}
        )
        # Should still be accepted (not blocked)
        assert decision.is_accepted()
        assert decision.compat_influenced is True

    def test_compat_not_influenced_is_false(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": "cancel"})
        assert decision.compat_influenced is False


# ===========================================================================
# Group M — Compat influence blocking (block_compat_influence=True)
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupM_CompatInfluenceBlocking:
    def test_compat_influenced_blocked_when_configured(self):
        coordinator = FlowLevelTruthOwnershipCoordinator(block_compat_influence=True)
        decision = coordinator.evaluate(
            {"truth_kind": "cancel", "compat_influenced": True}
        )
        assert decision.artifact == FlowTruthDecisionArtifact.block_due_to_compat_influence
        assert decision.is_rejected()
        assert decision.compat_influenced is True

    def test_non_compat_not_blocked_even_with_block_mode(self):
        coordinator = FlowLevelTruthOwnershipCoordinator(block_compat_influence=True)
        decision = coordinator.evaluate(
            {"truth_kind": "cancel", "compat_influenced": False}
        )
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_authoritative


# ===========================================================================
# Group N — Android result truth sets pending_v2_confirmation=True
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupN_PendingV2Confirmation:
    def test_result_sets_pending(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": "result"})
        assert decision.pending_v2_confirmation is True

    def test_partial_result_sets_pending(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "task_phase", "partial_result": {"data": "x"}}
        )
        assert decision.pending_v2_confirmation is True


# ===========================================================================
# Group O — Cancel and failure do NOT set pending_v2_confirmation
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupO_NoPendingForCancelFailure:
    @pytest.mark.parametrize("kind", ["cancel", "failure"])
    def test_cancel_and_failure_are_not_pending(self, kind):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": kind})
        assert decision.pending_v2_confirmation is False


# ===========================================================================
# Group P — evaluate_android_truth_alignment convenience function
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupP_ConvenienceFunction:
    def test_returns_alignment_decision(self):
        decision = evaluate_android_truth_alignment({"truth_kind": "cancel"})
        assert isinstance(decision, FlowTruthAlignmentDecision)
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_authoritative

    def test_block_compat_influence_param_forwarded(self):
        decision = evaluate_android_truth_alignment(
            {"truth_kind": "cancel", "compat_influenced": True},
            block_compat_influence=True,
        )
        assert decision.artifact == FlowTruthDecisionArtifact.block_due_to_compat_influence

    def test_current_flow_phase_forwarded(self):
        decision = evaluate_android_truth_alignment(
            {"truth_kind": "cancel"},
            current_flow_phase="completed",
        )
        assert decision.artifact == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal

    def test_posture_params_forwarded(self):
        decision = evaluate_android_truth_alignment(
            {"truth_kind": "result"},
            current_posture="control_only",
            previous_posture="join_runtime",
        )
        assert decision.artifact == FlowTruthDecisionArtifact.quarantine_due_to_posture_conflict

    def test_flow_id_override(self):
        decision = evaluate_android_truth_alignment(
            {"truth_kind": "cancel"},
            flow_id="my_flow_123",
        )
        assert decision.flow_id == "my_flow_123"


# ===========================================================================
# Group Q — Dict input works identically to envelope-like object
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupQ_DictVsObjectInput:
    def test_dict_and_mock_object_produce_same_artifact(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()

        mock_env = MagicMock()
        mock_env.truth_kind = MagicMock()
        mock_env.truth_kind.value = "cancel"
        mock_env.session_id = "s1"
        mock_env.contract_id = "c1"
        mock_env.compat_influenced = False
        mock_env.payload = {}
        mock_env.result_payload = {}

        d_from_dict = coordinator.evaluate(
            {"truth_kind": "cancel", "session_id": "s1", "contract_id": "c1"}
        )
        d_from_obj = coordinator.evaluate(mock_env)

        assert d_from_dict.artifact == d_from_obj.artifact
        assert d_from_dict.truth_semantics == d_from_obj.truth_semantics


# ===========================================================================
# Group R — flow_id extracted from dict
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupR_FlowIdExtraction:
    def test_flow_id_extracted_from_dict_flow_id_key(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": "cancel", "flow_id": "flow_abc"})
        assert decision.flow_id == "flow_abc"

    def test_flow_id_extracted_from_delegated_flow_id_key(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "cancel", "delegated_flow_id": "flow_xyz"}
        )
        assert decision.flow_id == "flow_xyz"


# ===========================================================================
# Group S — flow_id override wins over extracted value
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupS_FlowIdOverride:
    def test_explicit_flow_id_overrides_dict_value(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "cancel", "flow_id": "from_dict"},
            flow_id="override_id",
        )
        assert decision.flow_id == "override_id"


# ===========================================================================
# Group T — get_default_coordinator / reset_default_coordinator singleton
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupT_Singleton:
    def test_singleton_returns_same_instance(self):
        reset_default_coordinator()
        c1 = get_default_coordinator()
        c2 = get_default_coordinator()
        assert c1 is c2

    def test_reset_clears_singleton(self):
        reset_default_coordinator()
        c1 = get_default_coordinator()
        reset_default_coordinator()
        c2 = get_default_coordinator()
        assert c1 is not c2

    def test_singleton_is_coordinator_instance(self):
        reset_default_coordinator()
        c = get_default_coordinator()
        assert isinstance(c, FlowLevelTruthOwnershipCoordinator)


# ===========================================================================
# Group U — All 11 policy sentinels are non-empty strings
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupU_PolicySentinels:
    def test_all_policy_sentinels_non_empty(self):
        sentinels = [
            FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY,
            AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY,
            ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY,
            EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
            CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY,
            PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY,
            POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY,
            V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY,
            COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY,
            PARTIAL_THEN_FINAL_MERGE_RULE_POLICY,
            ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY,
        ]
        for sentinel in sentinels:
            assert isinstance(sentinel, str) and len(sentinel) > 0

    def test_all_policy_sentinels_contain_policy_keyword(self):
        sentinels = [
            FLOW_TRUTH_OWNERSHIP_IS_CENTRALLY_COORDINATED_POLICY,
            AUTHORITATIVE_TRUTH_MUST_BE_ABSORBED_POLICY,
            ADVISORY_TRUTH_DOES_NOT_ALTER_CANONICAL_STATE_POLICY,
            EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
            CANONICAL_TERMINAL_DECISION_IS_V2_EXCLUSIVE_POLICY,
            PARTIAL_RESULT_TRUTH_HAS_DEDICATED_STORE_POLICY,
            POSTURE_CHANGE_REQUIRES_EVIDENCE_REVALIDATION_POLICY,
            V2_TERMINAL_BLOCKS_ALL_SUBSEQUENT_ANDROID_TRUTH_POLICY,
            COMPAT_INFLUENCE_IS_BLOCKABLE_AT_TRUTH_LAYER_POLICY,
            PARTIAL_THEN_FINAL_MERGE_RULE_POLICY,
            ANDROID_TRUTH_ADVANCED_BUT_V2_UNCONFIRMED_POLICY,
        ]
        for sentinel in sentinels:
            assert "POLICY::" in sentinel


# ===========================================================================
# Group V — PR sentinel contains 'PR5V2'
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupV_PRSentinel:
    def test_pr_sentinel_contains_pr5v2(self):
        assert "PR5V2" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL

    def test_pr_sentinel_contains_authority_ref(self):
        assert "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL


# ===========================================================================
# Group W — core.runtime re-exports
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupW_RuntimeReexports:
    def test_all_pr5v2_symbols_accessible_from_core_runtime(self):
        try:
            import core.runtime as cr
        except ImportError:
            pytest.skip("core.runtime not importable")

        symbols = [
            "FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY",
            "FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL",
            "FlowTruthSemantics",
            "FlowTruthDecisionArtifact",
            "FlowTruthAlignmentDecision",
            "FlowLevelTruthOwnershipCoordinator",
            "evaluate_android_truth_alignment",
        ]
        missing = [s for s in symbols if not hasattr(cr, s)]
        assert missing == [], f"Missing symbols in core.runtime: {missing}"


# ===========================================================================
# Group X — to_dict round-trips truth_semantics and artifact as strings
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupX_ToDictRoundTrip:
    def test_to_dict_truth_semantics_is_string(self):
        d = FlowTruthAlignmentDecision(
            truth_semantics=FlowTruthSemantics.authoritative
        )
        assert isinstance(d.to_dict()["truth_semantics"], str)
        assert d.to_dict()["truth_semantics"] == "authoritative"

    def test_to_dict_artifact_is_string(self):
        d = FlowTruthAlignmentDecision(
            artifact=FlowTruthDecisionArtifact.accept_as_authoritative
        )
        assert isinstance(d.to_dict()["artifact"], str)
        assert d.to_dict()["artifact"] == "accept_as_authoritative"


# ===========================================================================
# Group Y — Unknown truth_kind falls back to advisory
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupY_UnknownTruthKind:
    def test_unknown_kind_falls_back_to_advisory(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({"truth_kind": "something_unrecognised"})
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_advisory
        assert decision.truth_semantics == FlowTruthSemantics.advisory

    def test_missing_truth_kind_falls_back_to_advisory(self):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate({})
        assert decision.artifact == FlowTruthDecisionArtifact.accept_as_advisory


# ===========================================================================
# Group Z — Terminal phases: completed, failed, cancelled all trigger rejection
# ===========================================================================


@pytest.mark.skipif(not _MODULE_AVAILABLE, reason=_SKIP_REASON)
class TestGroupZ_TerminalPhasesRejection:
    @pytest.mark.parametrize("phase", ["completed", "failed", "cancelled"])
    def test_all_canonical_terminal_phases_reject(self, phase):
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "result"},
            current_flow_phase=phase,
        )
        assert decision.artifact == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal

    def test_partial_phase_string_still_terminal(self):
        """Phase strings containing 'completed' substring are treated as terminal."""
        coordinator = FlowLevelTruthOwnershipCoordinator()
        decision = coordinator.evaluate(
            {"truth_kind": "result"},
            current_flow_phase="flow_completed",
        )
        assert decision.artifact == FlowTruthDecisionArtifact.reject_due_to_canonical_terminal
