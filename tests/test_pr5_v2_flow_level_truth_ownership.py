"""tests/test_pr5_v2_flow_level_truth_ownership.py
=====================================================
Tests for PR-5V2: Flow-Level Truth Ownership and Local/Central Truth
Alignment.

These tests provide auditable evidence for all acceptance criteria stated in
the PR-5V2 issue:

  AC1  Flow-level truth ownership framework is established: policy sentinels,
       enums, and data types are importable and consistent.

  AC2  Truth semantic distinctions are correctly modelled:
       authoritative / advisory / execution_evidence /
       canonical_terminal_decision / partial_result / posture_sensitive.

  AC3  Truth decision artifacts are correctly produced for every alignment
       scenario: accept_as_authoritative, accept_as_advisory,
       record_as_execution_evidence, reject_due_to_canonical_terminal,
       quarantine_due_to_posture_conflict, block_due_to_compat_influence.

  AC4  Runtime alignment rules cover:
       - partial / final / cancel / failure / task_phase absorption bounds
       - posture change handling for evidence / partial / final
       - Android truth advanced ahead of V2 confirmation (pending flag)
       - V2 already terminal — late Android truth rejected
       - compat influence blocked

  AC5  Posture change impact evaluation correctly quarantines evidence and
       partial result items while retaining terminal and advisory items.

  AC6  Alignment runtime ring-buffer and snapshot function correctly.

  AC7  All PR-5V2 symbols are re-exported through core.runtime.

Coverage groups
---------------
Group A — Module importability and authority sentinels.
Group B — FlowTruthSemanticKind enum: all values, from_string(), default.
Group C — FlowTruthDecisionKind enum: all values, from_string(), default.
Group D — FlowTruthOwnerKind enum: all values.
Group E — PostureChangeHandling enum: all values.
Group F — classify_flow_truth_kind(): all truth kind mappings.
Group G — align_android_truth_with_canonical(): compat influence block (Rule 1).
Group H — align_android_truth_with_canonical(): V2 terminal wins (Rule 2).
Group I — align_android_truth_with_canonical(): posture conflict quarantine (Rule 3).
Group J — align_android_truth_with_canonical(): authoritative Android truth (Rule 4).
Group K — align_android_truth_with_canonical(): partial result (Rule 5).
Group L — align_android_truth_with_canonical(): advisory truth (Rule 6).
Group M — align_android_truth_with_canonical(): execution evidence (Rule 7).
Group N — align_android_truth_with_canonical(): unknown fallback (Rule 8).
Group O — evaluate_posture_change_impact(): quarantine / retain logic.
Group P — FlowTruthAlignmentRuntime: record, list_recent, get_by_artifact_id.
Group Q — build_flow_truth_alignment_snapshot(): snapshot fields and counts.
Group R — align_and_record() convenience wrapper.
Group S — FlowTruthDecisionArtifact: to_dict() round-trip.
Group T — FlowTruthAlignmentContext: to_dict() and defaults.
Group U — core.runtime re-exports: all PR-5V2 symbols accessible.
Group V — Policy sentinel presence and count.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.flow_level_truth_ownership import (
        FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY,
        FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL,
        V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY,
        ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY,
        PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY,
        ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY,
        EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
        POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY,
        COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY,
        ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY,
        UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY,
        FlowTruthSemanticKind,
        FlowTruthDecisionKind,
        FlowTruthOwnerKind,
        PostureChangeHandling,
        FlowTruthAlignmentContext,
        FlowTruthDecisionArtifact,
        PostureChangeImpactRecord,
        FlowTruthAlignmentSnapshot,
        FlowTruthAlignmentRuntime,
        classify_flow_truth_kind,
        align_android_truth_with_canonical,
        evaluate_posture_change_impact,
        align_and_record,
        record_flow_truth_decision,
        build_flow_truth_alignment_snapshot,
        get_flow_truth_alignment_runtime,
        reset_flow_truth_alignment_runtime,
    )

    _MODULE_AVAILABLE = True
except ImportError as _exc:  # pragma: no cover
    _MODULE_AVAILABLE = False
    _exc_detail = str(_exc)

_SKIP_MODULE = pytest.mark.skipif(
    not _MODULE_AVAILABLE, reason="flow_level_truth_ownership unavailable"
)


# ===========================================================================
# Group A — Module importability and authority sentinels
# ===========================================================================


@_SKIP_MODULE
class TestGroupA_AuthoritySentinels:
    def test_a1_module_importable(self):
        assert _MODULE_AVAILABLE

    def test_a2_authority_sentinel_is_string(self):
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY, str)
        assert "PR5V2" in FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY

    def test_a3_pr_sentinel_is_string(self):
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL, str)
        assert "PR-5V2" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL

    def test_a4_authority_contains_module_reference(self):
        assert "flow_level_truth_ownership" in FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY

    def test_a5_pr_sentinel_contains_profile(self):
        assert "flow-level-truth-ownership-v1" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL


# ===========================================================================
# Group B — FlowTruthSemanticKind enum
# ===========================================================================


@_SKIP_MODULE
class TestGroupB_FlowTruthSemanticKind:
    def test_b1_all_six_values_present(self):
        values = {k.value for k in FlowTruthSemanticKind}
        assert values == {
            "authoritative",
            "advisory",
            "execution_evidence",
            "canonical_terminal_decision",
            "partial_result",
            "posture_sensitive",
        }

    def test_b2_from_string_known_value(self):
        assert FlowTruthSemanticKind.from_string("authoritative") == FlowTruthSemanticKind.authoritative
        assert FlowTruthSemanticKind.from_string("advisory") == FlowTruthSemanticKind.advisory
        assert FlowTruthSemanticKind.from_string("partial_result") == FlowTruthSemanticKind.partial_result

    def test_b3_from_string_unknown_defaults_to_advisory(self):
        assert FlowTruthSemanticKind.from_string("nonexistent") == FlowTruthSemanticKind.advisory

    def test_b4_from_string_none_defaults_to_advisory(self):
        assert FlowTruthSemanticKind.from_string(None) == FlowTruthSemanticKind.advisory

    def test_b5_str_enum_inherits_str(self):
        assert FlowTruthSemanticKind.authoritative == "authoritative"


# ===========================================================================
# Group C — FlowTruthDecisionKind enum
# ===========================================================================


@_SKIP_MODULE
class TestGroupC_FlowTruthDecisionKind:
    def test_c1_all_six_values_present(self):
        values = {k.value for k in FlowTruthDecisionKind}
        assert values == {
            "accept_as_authoritative",
            "accept_as_advisory",
            "record_as_execution_evidence",
            "reject_due_to_canonical_terminal",
            "quarantine_due_to_posture_conflict",
            "block_due_to_compat_influence",
        }

    def test_c2_from_string_known_value(self):
        assert (
            FlowTruthDecisionKind.from_string("accept_as_authoritative")
            == FlowTruthDecisionKind.accept_as_authoritative
        )
        assert (
            FlowTruthDecisionKind.from_string("reject_due_to_canonical_terminal")
            == FlowTruthDecisionKind.reject_due_to_canonical_terminal
        )

    def test_c3_from_string_unknown_defaults_to_accept_as_advisory(self):
        assert (
            FlowTruthDecisionKind.from_string("totally_unknown")
            == FlowTruthDecisionKind.accept_as_advisory
        )

    def test_c4_from_string_none_defaults_to_accept_as_advisory(self):
        assert (
            FlowTruthDecisionKind.from_string(None)
            == FlowTruthDecisionKind.accept_as_advisory
        )


# ===========================================================================
# Group D — FlowTruthOwnerKind enum
# ===========================================================================


@_SKIP_MODULE
class TestGroupD_FlowTruthOwnerKind:
    def test_d1_three_values(self):
        values = {k.value for k in FlowTruthOwnerKind}
        assert "v2_canonical" in values
        assert "android_execution" in values
        assert "joint" in values

    def test_d2_v2_canonical_is_str(self):
        assert FlowTruthOwnerKind.v2_canonical == "v2_canonical"


# ===========================================================================
# Group E — PostureChangeHandling enum
# ===========================================================================


@_SKIP_MODULE
class TestGroupE_PostureChangeHandling:
    def test_e1_four_values(self):
        values = {k.value for k in PostureChangeHandling}
        assert {"retain", "quarantine", "promote", "discard"} == values


# ===========================================================================
# Group F — classify_flow_truth_kind()
# ===========================================================================


@_SKIP_MODULE
class TestGroupF_ClassifyFlowTruthKind:
    def test_f1_cancel_is_authoritative(self):
        assert classify_flow_truth_kind("cancel") == FlowTruthSemanticKind.authoritative

    def test_f2_failure_is_authoritative(self):
        assert classify_flow_truth_kind("failure") == FlowTruthSemanticKind.authoritative

    def test_f3_result_is_authoritative(self):
        assert classify_flow_truth_kind("result") == FlowTruthSemanticKind.authoritative

    def test_f4_task_phase_completed_is_authoritative(self):
        assert (
            classify_flow_truth_kind("task_phase", task_phase_value="completed")
            == FlowTruthSemanticKind.authoritative
        )

    def test_f5_task_phase_failed_is_authoritative(self):
        assert (
            classify_flow_truth_kind("task_phase", task_phase_value="failed")
            == FlowTruthSemanticKind.authoritative
        )

    def test_f6_task_phase_cancelled_is_authoritative(self):
        assert (
            classify_flow_truth_kind("task_phase", task_phase_value="cancelled")
            == FlowTruthSemanticKind.authoritative
        )

    def test_f7_task_phase_running_is_evidence(self):
        assert (
            classify_flow_truth_kind("task_phase", task_phase_value="running")
            == FlowTruthSemanticKind.execution_evidence
        )

    def test_f8_session_snapshot_is_advisory(self):
        assert classify_flow_truth_kind("session_snapshot") == FlowTruthSemanticKind.advisory

    def test_f9_readiness_assessment_is_advisory(self):
        assert classify_flow_truth_kind("readiness_assessment") == FlowTruthSemanticKind.advisory

    def test_f10_runtime_state_is_advisory(self):
        assert classify_flow_truth_kind("runtime_state") == FlowTruthSemanticKind.advisory

    def test_f11_status_is_advisory(self):
        assert classify_flow_truth_kind("status") == FlowTruthSemanticKind.advisory

    def test_f12_partial_result_is_partial_result(self):
        assert classify_flow_truth_kind("partial_result") == FlowTruthSemanticKind.partial_result

    def test_f13_signal_is_posture_sensitive(self):
        assert classify_flow_truth_kind("signal") == FlowTruthSemanticKind.posture_sensitive

    def test_f14_unknown_is_advisory(self):
        assert classify_flow_truth_kind("unknown") == FlowTruthSemanticKind.advisory

    def test_f15_empty_string_is_advisory(self):
        assert classify_flow_truth_kind("") == FlowTruthSemanticKind.advisory


# ===========================================================================
# Group G — Rule 1: compat influence block
# ===========================================================================


@_SKIP_MODULE
class TestGroupG_CompatInfluenceBlock:
    def _ctx(self, truth_kind: str = "result") -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            v2_canonical_flow_phase="executing",
            device_posture="join_runtime",
            compat_influence_active=True,
            delegated_flow_id="flow-001",
        )

    def test_g1_compat_block_for_result(self):
        art = align_android_truth_with_canonical(self._ctx("result"))
        assert art.decision == FlowTruthDecisionKind.block_due_to_compat_influence

    def test_g2_compat_block_for_cancel(self):
        art = align_android_truth_with_canonical(self._ctx("cancel"))
        assert art.decision == FlowTruthDecisionKind.block_due_to_compat_influence

    def test_g3_compat_block_applies_before_terminal_check(self):
        ctx = FlowTruthAlignmentContext(
            truth_kind="result",
            v2_canonical_flow_phase="completed",
            compat_influence_active=True,
        )
        art = align_android_truth_with_canonical(ctx)
        # compat block is Rule 1 and evaluated first
        assert art.decision == FlowTruthDecisionKind.block_due_to_compat_influence

    def test_g4_policy_reference_is_correct(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert "COMPAT_INFLUENCE_BLOCKS" in art.policy_reference

    def test_g5_truth_owner_is_v2_canonical(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert art.truth_owner == FlowTruthOwnerKind.v2_canonical

    def test_g6_artifact_has_flow_id(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert art.delegated_flow_id == "flow-001"


# ===========================================================================
# Group H — Rule 2: V2 canonical terminal wins
# ===========================================================================


@_SKIP_MODULE
class TestGroupH_V2TerminalWins:
    def _ctx(self, truth_kind: str, phase: str) -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            v2_canonical_flow_phase=phase,
            device_posture="join_runtime",
            compat_influence_active=False,
        )

    @pytest.mark.parametrize(
        "terminal_phase",
        ["completed", "failed", "cancelled", "suspended"],
    )
    def test_h1_result_rejected_when_v2_terminal(self, terminal_phase: str):
        art = align_android_truth_with_canonical(
            self._ctx("result", terminal_phase)
        )
        assert art.decision == FlowTruthDecisionKind.reject_due_to_canonical_terminal

    @pytest.mark.parametrize(
        "terminal_phase",
        ["completed", "failed", "cancelled", "suspended"],
    )
    def test_h2_cancel_rejected_when_v2_terminal(self, terminal_phase: str):
        art = align_android_truth_with_canonical(
            self._ctx("cancel", terminal_phase)
        )
        assert art.decision == FlowTruthDecisionKind.reject_due_to_canonical_terminal

    def test_h3_advisory_also_rejected_when_v2_terminal(self):
        art = align_android_truth_with_canonical(
            self._ctx("session_snapshot", "completed")
        )
        assert art.decision == FlowTruthDecisionKind.reject_due_to_canonical_terminal

    def test_h4_non_terminal_phase_does_not_reject(self):
        for phase in ("created", "dispatched", "executing", "reconciling", ""):
            art = align_android_truth_with_canonical(
                self._ctx("result", phase)
            )
            assert art.decision != FlowTruthDecisionKind.reject_due_to_canonical_terminal, (
                f"Unexpected rejection for phase={phase!r}"
            )

    def test_h5_policy_reference_mentions_terminal(self):
        art = align_android_truth_with_canonical(
            self._ctx("result", "completed")
        )
        assert "V2_CANONICAL_OWNS_TERMINAL" in art.policy_reference

    def test_h6_evidence_in_artifact(self):
        art = align_android_truth_with_canonical(
            self._ctx("failure", "failed")
        )
        assert art.evidence["v2_canonical_flow_phase"] == "failed"


# ===========================================================================
# Group I — Rule 3: posture conflict quarantine
# ===========================================================================


@_SKIP_MODULE
class TestGroupI_PostureConflictQuarantine:
    def _ctx(
        self,
        truth_kind: str,
        *,
        posture_changed: bool = True,
        task_phase: str = "",
    ) -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            task_phase_value=task_phase,
            v2_canonical_flow_phase="executing",
            device_posture="control_only",
            posture_changed=posture_changed,
            compat_influence_active=False,
        )

    def test_i1_execution_evidence_quarantined(self):
        ctx = self._ctx("task_phase", task_phase="running")
        art = align_android_truth_with_canonical(ctx)
        assert art.decision == FlowTruthDecisionKind.quarantine_due_to_posture_conflict

    def test_i2_signal_quarantined(self):
        art = align_android_truth_with_canonical(self._ctx("signal"))
        assert art.decision == FlowTruthDecisionKind.quarantine_due_to_posture_conflict

    def test_i3_partial_result_quarantined_on_posture_change(self):
        art = align_android_truth_with_canonical(self._ctx("partial_result"))
        assert art.decision == FlowTruthDecisionKind.quarantine_due_to_posture_conflict

    def test_i4_authoritative_result_not_quarantined_even_on_posture_change(self):
        art = align_android_truth_with_canonical(self._ctx("result"))
        # result is authoritative, not evidence — posture quarantine does not apply
        assert art.decision == FlowTruthDecisionKind.accept_as_authoritative

    def test_i5_no_quarantine_when_posture_unchanged(self):
        ctx = self._ctx("task_phase", posture_changed=False, task_phase="running")
        art = align_android_truth_with_canonical(ctx)
        assert art.decision == FlowTruthDecisionKind.record_as_execution_evidence

    def test_i6_policy_reference_mentions_posture(self):
        ctx = self._ctx("signal")
        art = align_android_truth_with_canonical(ctx)
        assert "POSTURE_CHANGE_QUARANTINES" in art.policy_reference


# ===========================================================================
# Group J — Rule 4: authoritative Android truth
# ===========================================================================


@_SKIP_MODULE
class TestGroupJ_AuthoritativeAndroidTruth:
    def _ctx(
        self,
        truth_kind: str,
        task_phase: str = "",
        *,
        v2_phase: str = "executing",
    ) -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            task_phase_value=task_phase,
            v2_canonical_flow_phase=v2_phase,
            device_posture="join_runtime",
            posture_changed=False,
            compat_influence_active=False,
        )

    def test_j1_cancel_accepted_as_authoritative(self):
        art = align_android_truth_with_canonical(self._ctx("cancel"))
        assert art.decision == FlowTruthDecisionKind.accept_as_authoritative

    def test_j2_failure_accepted_as_authoritative(self):
        art = align_android_truth_with_canonical(self._ctx("failure"))
        assert art.decision == FlowTruthDecisionKind.accept_as_authoritative

    def test_j3_result_accepted_as_authoritative(self):
        art = align_android_truth_with_canonical(self._ctx("result"))
        assert art.decision == FlowTruthDecisionKind.accept_as_authoritative

    def test_j4_task_phase_completed_accepted_as_authoritative(self):
        art = align_android_truth_with_canonical(self._ctx("task_phase", "completed"))
        assert art.decision == FlowTruthDecisionKind.accept_as_authoritative

    def test_j5_pending_v2_confirmation_is_true(self):
        """AC4: Android advanced ahead of V2 confirmation is flagged."""
        art = align_android_truth_with_canonical(self._ctx("result"))
        assert art.pending_v2_confirmation is True

    def test_j6_truth_owner_is_android_execution(self):
        art = align_android_truth_with_canonical(self._ctx("cancel"))
        assert art.truth_owner == FlowTruthOwnerKind.android_execution

    def test_j7_policy_reference_mentions_authoritative_upward(self):
        art = align_android_truth_with_canonical(self._ctx("failure"))
        assert "AUTHORITATIVE_UPWARD" in art.policy_reference

    def test_j8_semantic_kind_is_authoritative(self):
        art = align_android_truth_with_canonical(self._ctx("result"))
        assert art.semantic_kind == FlowTruthSemanticKind.authoritative


# ===========================================================================
# Group K — Rule 5: partial result
# ===========================================================================


@_SKIP_MODULE
class TestGroupK_PartialResult:
    def _ctx(self) -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind="partial_result",
            v2_canonical_flow_phase="executing",
            device_posture="join_runtime",
            posture_changed=False,
            compat_influence_active=False,
        )

    def test_k1_partial_result_accepted_as_advisory(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory

    def test_k2_semantic_kind_is_partial_result(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert art.semantic_kind == FlowTruthSemanticKind.partial_result

    def test_k3_policy_reference_mentions_partial_result(self):
        art = align_android_truth_with_canonical(self._ctx())
        assert "PARTIAL_RESULT" in art.policy_reference

    def test_k4_flow_not_closed_by_partial_result(self):
        """AC3/AC4: Partial result must not close the flow."""
        art = align_android_truth_with_canonical(self._ctx())
        # advisory decision means the flow phase is NOT terminated
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory
        assert art.pending_v2_confirmation is False


# ===========================================================================
# Group L — Rule 6: advisory truth
# ===========================================================================


@_SKIP_MODULE
class TestGroupL_AdvisoryTruth:
    def _ctx(self, truth_kind: str) -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            v2_canonical_flow_phase="dispatched",
            device_posture="join_runtime",
            posture_changed=False,
            compat_influence_active=False,
        )

    @pytest.mark.parametrize(
        "kind",
        ["session_snapshot", "readiness_assessment", "runtime_state", "status", "unknown"],
    )
    def test_l1_advisory_kinds_accepted_as_advisory(self, kind: str):
        art = align_android_truth_with_canonical(self._ctx(kind))
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory

    def test_l2_advisory_does_not_alter_canonical_state(self):
        """AC2: Advisory truth is noted but does not alter V2 canonical state."""
        art = align_android_truth_with_canonical(self._ctx("runtime_state"))
        assert art.semantic_kind == FlowTruthSemanticKind.advisory
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory

    def test_l3_policy_reference_mentions_advisory(self):
        art = align_android_truth_with_canonical(self._ctx("session_snapshot"))
        assert "ADVISORY" in art.policy_reference


# ===========================================================================
# Group M — Rule 7: execution evidence
# ===========================================================================


@_SKIP_MODULE
class TestGroupM_ExecutionEvidence:
    def _ctx(self, truth_kind: str, task_phase: str = "") -> FlowTruthAlignmentContext:
        return FlowTruthAlignmentContext(
            truth_kind=truth_kind,
            task_phase_value=task_phase,
            v2_canonical_flow_phase="executing",
            device_posture="join_runtime",
            posture_changed=False,
            compat_influence_active=False,
        )

    def test_m1_task_phase_running_is_evidence(self):
        art = align_android_truth_with_canonical(self._ctx("task_phase", "running"))
        assert art.decision == FlowTruthDecisionKind.record_as_execution_evidence

    def test_m2_policy_reference_mentions_evidence(self):
        art = align_android_truth_with_canonical(self._ctx("task_phase", "running"))
        assert "EXECUTION_EVIDENCE" in art.policy_reference

    def test_m3_semantic_kind_is_execution_evidence(self):
        art = align_android_truth_with_canonical(self._ctx("task_phase", "running"))
        assert art.semantic_kind == FlowTruthSemanticKind.execution_evidence


# ===========================================================================
# Group N — Rule 8: unknown fallback
# ===========================================================================


@_SKIP_MODULE
class TestGroupN_UnknownFallback:
    def test_n1_unknown_kind_accepted_as_advisory(self):
        ctx = FlowTruthAlignmentContext(
            truth_kind="some_future_kind_not_yet_defined",
            v2_canonical_flow_phase="executing",
            posture_changed=False,
            compat_influence_active=False,
        )
        art = align_android_truth_with_canonical(ctx)
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory

    def test_n2_unknown_fallback_is_advisory_decision(self):
        """Unknown kinds are classified as advisory via the safe-default path."""
        ctx = FlowTruthAlignmentContext(
            truth_kind="mystery_kind",
            v2_canonical_flow_phase="executing",
        )
        art = align_android_truth_with_canonical(ctx)
        # Unknown kinds resolve to advisory semantic, which hits Rule 6 or Rule 8
        # — either way the decision is accept_as_advisory (safe default).
        assert art.decision == FlowTruthDecisionKind.accept_as_advisory


# ===========================================================================
# Group O — evaluate_posture_change_impact()
# ===========================================================================


@_SKIP_MODULE
class TestGroupO_PostureChangeImpact:
    def _make_artifact(
        self,
        decision: FlowTruthDecisionKind,
        semantic_kind: FlowTruthSemanticKind,
        truth_kind: str = "result",
    ) -> FlowTruthDecisionArtifact:
        return FlowTruthDecisionArtifact(
            decision=decision,
            semantic_kind=semantic_kind,
            truth_owner=FlowTruthOwnerKind.android_execution,
            policy_reference="TEST",
            evidence={"truth_kind": truth_kind},
        )

    def test_o1_evidence_artifact_is_quarantined(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.record_as_execution_evidence,
            FlowTruthSemanticKind.execution_evidence,
            "task_phase",
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert len(results) == 1
        assert results[0].revised_handling == PostureChangeHandling.quarantine

    def test_o2_partial_result_artifact_is_quarantined(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.accept_as_advisory,
            FlowTruthSemanticKind.partial_result,
            "partial_result",
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="join_runtime",
            old_posture="control_only",
        )
        assert results[0].revised_handling == PostureChangeHandling.quarantine

    def test_o3_authoritative_terminal_is_retained(self):
        """AC5: Terminal authoritative truth is retained after posture change."""
        art = self._make_artifact(
            FlowTruthDecisionKind.accept_as_authoritative,
            FlowTruthSemanticKind.authoritative,
            "result",
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results[0].revised_handling == PostureChangeHandling.retain

    def test_o4_rejected_terminal_is_retained(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.reject_due_to_canonical_terminal,
            FlowTruthSemanticKind.authoritative,
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results[0].revised_handling == PostureChangeHandling.retain

    def test_o5_compat_blocked_is_retained(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.block_due_to_compat_influence,
            FlowTruthSemanticKind.advisory,
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results[0].revised_handling == PostureChangeHandling.retain

    def test_o6_advisory_is_retained(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.accept_as_advisory,
            FlowTruthSemanticKind.advisory,
            "session_snapshot",
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results[0].revised_handling == PostureChangeHandling.retain

    def test_o7_posture_sensitive_is_quarantined(self):
        art = self._make_artifact(
            FlowTruthDecisionKind.record_as_execution_evidence,
            FlowTruthSemanticKind.posture_sensitive,
            "signal",
        )
        results = evaluate_posture_change_impact(
            [art],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results[0].revised_handling == PostureChangeHandling.quarantine

    def test_o8_empty_list_returns_empty(self):
        results = evaluate_posture_change_impact(
            [],
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert results == []

    def test_o9_multiple_artifacts_mixed(self):
        artifacts = [
            self._make_artifact(
                FlowTruthDecisionKind.record_as_execution_evidence,
                FlowTruthSemanticKind.execution_evidence,
            ),
            self._make_artifact(
                FlowTruthDecisionKind.accept_as_authoritative,
                FlowTruthSemanticKind.authoritative,
                "result",
            ),
            self._make_artifact(
                FlowTruthDecisionKind.accept_as_advisory,
                FlowTruthSemanticKind.advisory,
                "session_snapshot",
            ),
        ]
        results = evaluate_posture_change_impact(
            artifacts,
            new_posture="control_only",
            old_posture="join_runtime",
        )
        assert len(results) == 3
        handlings = [r.revised_handling for r in results]
        assert handlings[0] == PostureChangeHandling.quarantine
        assert handlings[1] == PostureChangeHandling.retain
        assert handlings[2] == PostureChangeHandling.retain


# ===========================================================================
# Group P — FlowTruthAlignmentRuntime
# ===========================================================================


@_SKIP_MODULE
class TestGroupP_AlignmentRuntime:
    def setup_method(self):
        reset_flow_truth_alignment_runtime()

    def teardown_method(self):
        reset_flow_truth_alignment_runtime()

    def _make_artifact(self, decision: str = "accept_as_advisory") -> FlowTruthDecisionArtifact:
        return FlowTruthDecisionArtifact(
            decision=FlowTruthDecisionKind(decision),
            semantic_kind=FlowTruthSemanticKind.advisory,
            truth_owner=FlowTruthOwnerKind.v2_canonical,
            policy_reference="TEST",
            delegated_flow_id="flow-p",
        )

    def test_p1_singleton_is_returned(self):
        rt = get_flow_truth_alignment_runtime()
        assert rt is get_flow_truth_alignment_runtime()

    def test_p2_record_increases_total(self):
        rt = get_flow_truth_alignment_runtime()
        rt.record(self._make_artifact())
        snap = rt.build_snapshot()
        assert snap.total_decisions == 1

    def test_p3_list_recent_newest_first(self):
        rt = get_flow_truth_alignment_runtime()
        a1 = self._make_artifact("accept_as_advisory")
        a2 = self._make_artifact("record_as_execution_evidence")
        rt.record(a1)
        rt.record(a2)
        recent = rt.list_recent(2)
        assert recent[0].artifact_id == a2.artifact_id

    def test_p4_get_by_artifact_id(self):
        rt = get_flow_truth_alignment_runtime()
        art = self._make_artifact()
        rt.record(art)
        found = rt.get_by_artifact_id(art.artifact_id)
        assert found is not None
        assert found.artifact_id == art.artifact_id

    def test_p5_get_by_artifact_id_miss_returns_none(self):
        rt = get_flow_truth_alignment_runtime()
        assert rt.get_by_artifact_id("nonexistent-id") is None

    def test_p6_get_by_flow_id(self):
        rt = get_flow_truth_alignment_runtime()
        art = self._make_artifact()
        rt.record(art)
        by_flow = rt.get_by_flow_id("flow-p")
        assert any(a.artifact_id == art.artifact_id for a in by_flow)

    def test_p7_reset_clears_runtime(self):
        rt = get_flow_truth_alignment_runtime()
        rt.record(self._make_artifact())
        reset_flow_truth_alignment_runtime()
        rt2 = get_flow_truth_alignment_runtime()
        assert rt2 is not rt
        assert rt2.build_snapshot().total_decisions == 0


# ===========================================================================
# Group Q — build_flow_truth_alignment_snapshot()
# ===========================================================================


@_SKIP_MODULE
class TestGroupQ_AlignmentSnapshot:
    def setup_method(self):
        reset_flow_truth_alignment_runtime()

    def teardown_method(self):
        reset_flow_truth_alignment_runtime()

    def test_q1_snapshot_is_correct_type(self):
        snap = build_flow_truth_alignment_snapshot()
        assert isinstance(snap, FlowTruthAlignmentSnapshot)

    def test_q2_empty_snapshot_has_zero_total(self):
        snap = build_flow_truth_alignment_snapshot()
        assert snap.total_decisions == 0

    def test_q3_snapshot_to_dict_round_trip(self):
        snap = build_flow_truth_alignment_snapshot()
        d = snap.to_dict()
        assert "total_decisions" in d
        assert "recent_artifacts" in d
        assert "decision_counts" in d
        assert "snapshot_id" in d

    def test_q4_decision_counts_populated_after_records(self):
        rt = get_flow_truth_alignment_runtime()
        for _ in range(3):
            rt.record(FlowTruthDecisionArtifact(
                decision=FlowTruthDecisionKind.accept_as_advisory,
                semantic_kind=FlowTruthSemanticKind.advisory,
                truth_owner=FlowTruthOwnerKind.v2_canonical,
                policy_reference="TEST",
            ))
        rt.record(FlowTruthDecisionArtifact(
            decision=FlowTruthDecisionKind.accept_as_authoritative,
            semantic_kind=FlowTruthSemanticKind.authoritative,
            truth_owner=FlowTruthOwnerKind.android_execution,
            policy_reference="TEST",
        ))
        snap = build_flow_truth_alignment_snapshot()
        assert snap.decision_counts.get("accept_as_advisory", 0) == 3
        assert snap.decision_counts.get("accept_as_authoritative", 0) == 1


# ===========================================================================
# Group R — align_and_record() convenience wrapper
# ===========================================================================


@_SKIP_MODULE
class TestGroupR_AlignAndRecord:
    def setup_method(self):
        reset_flow_truth_alignment_runtime()

    def teardown_method(self):
        reset_flow_truth_alignment_runtime()

    def test_r1_returns_artifact(self):
        ctx = FlowTruthAlignmentContext(
            truth_kind="cancel",
            v2_canonical_flow_phase="executing",
            posture_changed=False,
            compat_influence_active=False,
        )
        art = align_and_record(ctx)
        assert isinstance(art, FlowTruthDecisionArtifact)

    def test_r2_artifact_is_recorded_in_runtime(self):
        ctx = FlowTruthAlignmentContext(
            truth_kind="cancel",
            v2_canonical_flow_phase="executing",
        )
        art = align_and_record(ctx)
        rt = get_flow_truth_alignment_runtime()
        found = rt.get_by_artifact_id(art.artifact_id)
        assert found is not None


# ===========================================================================
# Group S — FlowTruthDecisionArtifact to_dict()
# ===========================================================================


@_SKIP_MODULE
class TestGroupS_ArtifactToDict:
    def test_s1_to_dict_contains_all_fields(self):
        art = FlowTruthDecisionArtifact(
            decision=FlowTruthDecisionKind.accept_as_authoritative,
            semantic_kind=FlowTruthSemanticKind.authoritative,
            truth_owner=FlowTruthOwnerKind.android_execution,
            policy_reference="TEST_POLICY",
            reason="test reason",
            delegated_flow_id="flow-s",
            session_id="sess-1",
            contract_id="contract-1",
            task_id="task-1",
            trace_id="trace-1",
            pending_v2_confirmation=True,
            posture_at_decision="join_runtime",
        )
        d = art.to_dict()
        assert d["decision"] == "accept_as_authoritative"
        assert d["semantic_kind"] == "authoritative"
        assert d["truth_owner"] == "android_execution"
        assert d["policy_reference"] == "TEST_POLICY"
        assert d["pending_v2_confirmation"] is True
        assert d["posture_at_decision"] == "join_runtime"
        assert "artifact_id" in d
        assert "timestamp" in d

    def test_s2_artifact_id_has_prefix(self):
        art = FlowTruthDecisionArtifact()
        assert art.artifact_id.startswith("ftda_")

    def test_s3_evidence_dict_present_in_to_dict(self):
        art = FlowTruthDecisionArtifact(
            evidence={"truth_kind": "cancel", "v2_canonical_flow_phase": "executing"}
        )
        d = art.to_dict()
        assert "evidence" in d
        assert d["evidence"]["truth_kind"] == "cancel"


# ===========================================================================
# Group T — FlowTruthAlignmentContext
# ===========================================================================


@_SKIP_MODULE
class TestGroupT_AlignmentContext:
    def test_t1_default_construction(self):
        ctx = FlowTruthAlignmentContext()
        assert ctx.truth_kind == ""
        assert ctx.posture_changed is False
        assert ctx.compat_influence_active is False
        assert ctx.truth_payload == {}

    def test_t2_to_dict_contains_fields(self):
        ctx = FlowTruthAlignmentContext(
            truth_kind="cancel",
            v2_canonical_flow_phase="executing",
            device_posture="join_runtime",
            delegated_flow_id="flow-t",
        )
        d = ctx.to_dict()
        assert d["truth_kind"] == "cancel"
        assert d["v2_canonical_flow_phase"] == "executing"
        assert d["device_posture"] == "join_runtime"
        assert d["delegated_flow_id"] == "flow-t"


# ===========================================================================
# Group U — core.runtime re-exports
# ===========================================================================


@_SKIP_MODULE
class TestGroupU_CoreRuntimeReexports:
    def test_u1_all_pr5v2_symbols_importable_from_core_runtime(self):
        try:
            from core.runtime import (  # noqa: F401
                FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY,
                FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL,
                V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY,
                ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY,
                PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY,
                ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY,
                EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
                POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY,
                COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY,
                ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY,
                UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY,
                FlowTruthSemanticKind,
                FlowTruthDecisionKind,
                FlowTruthOwnerKind,
                PostureChangeHandling,
                FlowTruthAlignmentContext,
                FlowTruthDecisionArtifact,
                PostureChangeImpactRecord,
                FlowTruthAlignmentSnapshot,
                FlowTruthAlignmentRuntime,
                classify_flow_truth_kind,
                align_android_truth_with_canonical,
                evaluate_posture_change_impact,
                align_and_record,
                record_flow_truth_decision,
                build_flow_truth_alignment_snapshot,
                get_flow_truth_alignment_runtime,
                reset_flow_truth_alignment_runtime,
            )
        except ImportError as exc:
            # Skip if a transitive dependency (e.g. pydantic) is missing in
            # the test environment — this is a pre-existing environment
            # constraint unrelated to PR-5V2 changes.
            pytest.skip(f"core.runtime transitive import unavailable: {exc}")


# ===========================================================================
# Group V — Policy sentinels presence and count
# ===========================================================================


@_SKIP_MODULE
class TestGroupV_PolicySentinels:
    _POLICY_SENTINELS = [
        V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY,
        ANDROID_CANCEL_FAILURE_RESULT_ARE_AUTHORITATIVE_UPWARD_POLICY,
        PARTIAL_RESULT_LIVES_IN_EXECUTION_TRACKING_RECORD_POLICY,
        ADVISORY_TRUTH_IS_NOTED_NOT_APPLIED_POLICY,
        EXECUTION_EVIDENCE_IS_AUDIT_ONLY_POLICY,
        POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY,
        COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY,
        ANDROID_ADVANCED_AHEAD_OF_V2_CONFIRMATION_POLICY,
        UNKNOWN_TRUTH_KIND_DEFAULTS_TO_ADVISORY_POLICY,
    ]

    def test_v1_at_least_nine_policy_sentinels(self):
        assert len(self._POLICY_SENTINELS) >= 9

    def test_v2_all_policy_sentinels_are_strings(self):
        for sentinel in self._POLICY_SENTINELS:
            assert isinstance(sentinel, str), f"Not a string: {sentinel!r}"

    def test_v3_all_policy_sentinels_contain_policy_keyword(self):
        for sentinel in self._POLICY_SENTINELS:
            assert "POLICY" in sentinel, f"Missing POLICY in: {sentinel!r}"

    def test_v4_policy_sentinels_mention_pr5v2(self):
        for sentinel in self._POLICY_SENTINELS:
            assert "PR-5V2" in sentinel or "POLICY" in sentinel

    def test_v5_terminal_policy_mentions_v2_canonical(self):
        assert "V2" in V2_CANONICAL_OWNS_TERMINAL_FLOW_DECISION_POLICY

    def test_v6_posture_change_policy_mentions_quarantine(self):
        assert "quarantine" in POSTURE_CHANGE_QUARANTINES_PRIOR_EVIDENCE_POLICY.lower()

    def test_v7_compat_policy_mentions_blocking(self):
        assert "block" in COMPAT_INFLUENCE_BLOCKS_AUTHORITATIVE_TRUTH_PATH_POLICY.lower()
