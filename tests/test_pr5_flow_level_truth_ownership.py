#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr5_flow_level_truth_ownership.py
=============================================
PR-5V2: Flow-Level Truth Ownership and Local/Central Truth Alignment
— focused test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-5V2 sentinel present and
    contain expected keywords.
B.  All seven policy sentinels are non-empty strings with expected keywords.
C.  FlowTruthSemanticKind enum has all six expected values.
D.  FlowTruthAlignmentVerdict enum has all seven expected verdict values.
E.  FlowOwnershipRole enum has owner, coordinator, policy values.
F.  FlowTruthOwnershipContext dataclass: is_flow_terminal() correct for
    terminal and non-terminal phases; has_posture_changed() correct.
G.  classify_android_truth_semantic — result/failure/cancel → authoritative_upward.
H.  classify_android_truth_semantic — partial_result → partial_result.
I.  classify_android_truth_semantic — task_phase → execution_evidence.
J.  classify_android_truth_semantic — advisory kinds → advisory.
K.  classify_android_truth_semantic — evidence kinds → execution_evidence.
L.  classify_android_truth_semantic — posture change → posture_sensitive for
    non-advisory kinds.
M.  decide_flow_truth_alignment — compat influence → block_due_to_compat_influence.
N.  decide_flow_truth_alignment — posture change (non-advisory) →
    quarantine_due_to_posture_conflict.
O.  decide_flow_truth_alignment — terminal flow + result kind →
    reject_due_to_canonical_terminal.
P.  decide_flow_truth_alignment — terminal flow + advisory kind →
    reject_due_to_canonical_terminal.
Q.  decide_flow_truth_alignment — non-terminal flow + result →
    accept_as_authoritative.
R.  decide_flow_truth_alignment — non-terminal flow + partial_result →
    record_as_partial_result.
S.  decide_flow_truth_alignment — non-terminal flow + task_phase →
    record_as_execution_evidence.
T.  decide_flow_truth_alignment — non-terminal flow + advisory kind →
    accept_as_advisory.
U.  decide_flow_truth_alignment — is_intermediate_pending True when Android
    signals result but flow is still executing.
V.  decide_flow_truth_alignment — is_intermediate_pending False when flow is
    not executing.
W.  decide_flow_truth_alignment — strict=True raises RuntimeError for
    block_due_to_compat_influence.
X.  decide_flow_truth_alignment — strict=True raises RuntimeError for
    reject_due_to_canonical_terminal.
Y.  decide_flow_truth_alignment — decision.to_dict() contains all expected keys.
Z.  record_flow_truth_alignment persists record into ring-buffer runtime.
AA. record_flow_truth_alignment — records_for_flow filters by flow_id.
BB. FlowTruthAlignmentRecord.to_dict() contains expected keys.
CC. build_flow_truth_ownership_snapshot returns dict with expected top-level keys.
DD. build_flow_truth_ownership_snapshot policy_sentinels contains all seven
    policy strings.
EE. build_flow_truth_ownership_snapshot ownership_roles has owner, coordinator,
    policy entries.
FF. build_flow_truth_ownership_snapshot filtered by flow_id returns only
    records for that flow.
GG. reset_flow_truth_alignment_runtime clears the ring-buffer singleton.
HH. Multiple records with different verdicts accumulate in the runtime.
II. classify_android_truth_semantic — unknown kind → advisory (safe default).
JJ. decide_flow_truth_alignment — failure kind + non-terminal flow →
    accept_as_authoritative.
KK. decide_flow_truth_alignment — cancel kind + non-terminal flow →
    accept_as_authoritative.
LL. decide_flow_truth_alignment — all four terminal phases each produce
    reject_due_to_canonical_terminal for result kind.
"""

from __future__ import annotations

import pytest


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_is_importable(self):
        import core.flow_level_truth_ownership  # noqa: F401

    def test_authority_sentinel_is_non_empty_string(self):
        from core.flow_level_truth_ownership import (
            FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY,
        )
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY, str)
        assert len(FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY) > 0
        assert "PR-5V2" in FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY
        assert "flow_level_truth_ownership" in FLOW_LEVEL_TRUTH_OWNERSHIP_AUTHORITY.lower()

    def test_pr5v2_sentinel_is_non_empty_string(self):
        from core.flow_level_truth_ownership import (
            FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL,
        )
        assert isinstance(FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL, str)
        assert "PR5V2" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL
        assert "truth-ownership" in FLOW_LEVEL_TRUTH_OWNERSHIP_PR5V2_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    def test_v2_owns_canonical_terminal_truth_policy(self):
        from core.flow_level_truth_ownership import V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY
        assert isinstance(V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY, str)
        assert "terminal" in V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY.lower()
        assert "V2" in V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY

    def test_android_truth_absorbed_by_semantic_category_policy(self):
        from core.flow_level_truth_ownership import (
            ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY,
        )
        assert isinstance(ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY, str)
        assert "semantic" in ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY.lower()

    def test_partial_result_stored_in_tracking_record_policy(self):
        from core.flow_level_truth_ownership import (
            PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY,
        )
        assert isinstance(PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY, str)
        assert "partial" in PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY.lower()

    def test_posture_change_quarantines_posture_sensitive_truth_policy(self):
        from core.flow_level_truth_ownership import (
            POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY,
        )
        assert isinstance(POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY, str)
        assert "posture" in POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY.lower()
        assert "quarantine" in POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY.lower()

    def test_compat_influence_blocks_truth_alignment_path_policy(self):
        from core.flow_level_truth_ownership import (
            COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY,
        )
        assert isinstance(COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY, str)
        assert "compat" in COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY.lower()
        assert "block" in COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY.lower()

    def test_terminal_flow_rejects_all_android_updates_policy(self):
        from core.flow_level_truth_ownership import (
            TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY,
        )
        assert isinstance(TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY, str)
        assert "terminal" in TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY.lower()
        assert "reject" in TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY.lower()

    def test_android_in_flight_truth_is_intermediate_pending_policy(self):
        from core.flow_level_truth_ownership import (
            ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY,
        )
        assert isinstance(ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY, str)
        assert "intermediate" in ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY.lower()


# ===========================================================================
# C. FlowTruthSemanticKind
# ===========================================================================


class TestFlowTruthSemanticKind:
    def test_has_authoritative_upward(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.authoritative_upward.value == "authoritative_upward"

    def test_has_advisory(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.advisory.value == "advisory"

    def test_has_execution_evidence(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.execution_evidence.value == "execution_evidence"

    def test_has_canonical_terminal_decision(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.canonical_terminal_decision.value == "canonical_terminal_decision"

    def test_has_partial_result(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.partial_result.value == "partial_result"

    def test_has_posture_sensitive(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert FlowTruthSemanticKind.posture_sensitive.value == "posture_sensitive"

    def test_has_exactly_six_values(self):
        from core.flow_level_truth_ownership import FlowTruthSemanticKind
        assert len(list(FlowTruthSemanticKind)) == 6


# ===========================================================================
# D. FlowTruthAlignmentVerdict
# ===========================================================================


class TestFlowTruthAlignmentVerdict:
    def test_has_accept_as_authoritative(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.accept_as_authoritative.value == "accept_as_authoritative"

    def test_has_accept_as_advisory(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.accept_as_advisory.value == "accept_as_advisory"

    def test_has_record_as_execution_evidence(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.record_as_execution_evidence.value == "record_as_execution_evidence"

    def test_has_record_as_partial_result(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.record_as_partial_result.value == "record_as_partial_result"

    def test_has_reject_due_to_canonical_terminal(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal.value == "reject_due_to_canonical_terminal"

    def test_has_quarantine_due_to_posture_conflict(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.quarantine_due_to_posture_conflict.value == "quarantine_due_to_posture_conflict"

    def test_has_block_due_to_compat_influence(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert FlowTruthAlignmentVerdict.block_due_to_compat_influence.value == "block_due_to_compat_influence"

    def test_has_exactly_seven_values(self):
        from core.flow_level_truth_ownership import FlowTruthAlignmentVerdict
        assert len(list(FlowTruthAlignmentVerdict)) == 7


# ===========================================================================
# E. FlowOwnershipRole
# ===========================================================================


class TestFlowOwnershipRole:
    def test_has_owner(self):
        from core.flow_level_truth_ownership import FlowOwnershipRole
        assert FlowOwnershipRole.owner.value == "owner"

    def test_has_coordinator(self):
        from core.flow_level_truth_ownership import FlowOwnershipRole
        assert FlowOwnershipRole.coordinator.value == "coordinator"

    def test_has_policy(self):
        from core.flow_level_truth_ownership import FlowOwnershipRole
        assert FlowOwnershipRole.policy.value == "policy"

    def test_has_exactly_three_values(self):
        from core.flow_level_truth_ownership import FlowOwnershipRole
        assert len(list(FlowOwnershipRole)) == 3


# ===========================================================================
# F. FlowTruthOwnershipContext helpers
# ===========================================================================


class TestFlowTruthOwnershipContext:
    def test_is_flow_terminal_true_for_completed(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="completed")
        assert ctx.is_flow_terminal() is True

    def test_is_flow_terminal_true_for_failed(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="failed")
        assert ctx.is_flow_terminal() is True

    def test_is_flow_terminal_true_for_cancelled(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="cancelled")
        assert ctx.is_flow_terminal() is True

    def test_is_flow_terminal_true_for_timed_out(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="timed_out")
        assert ctx.is_flow_terminal() is True

    def test_is_flow_terminal_false_for_executing(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="executing")
        assert ctx.is_flow_terminal() is False

    def test_is_flow_terminal_false_for_empty(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(flow_phase="")
        assert ctx.is_flow_terminal() is False

    def test_has_posture_changed_false_when_no_prior(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(
            source_runtime_posture="join_runtime", prior_posture=None
        )
        assert ctx.has_posture_changed() is False

    def test_has_posture_changed_false_when_same(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(
            source_runtime_posture="join_runtime", prior_posture="join_runtime"
        )
        assert ctx.has_posture_changed() is False

    def test_has_posture_changed_true_when_different(self):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        ctx = FlowTruthOwnershipContext(
            source_runtime_posture="control_only", prior_posture="join_runtime"
        )
        assert ctx.has_posture_changed() is True


# ===========================================================================
# G–L. classify_android_truth_semantic
# ===========================================================================


class TestClassifyAndroidTruthSemantic:
    def test_result_is_authoritative_upward(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("result")
        assert result == FlowTruthSemanticKind.authoritative_upward

    def test_failure_is_authoritative_upward(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("failure")
        assert result == FlowTruthSemanticKind.authoritative_upward

    def test_cancel_is_authoritative_upward(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("cancel")
        assert result == FlowTruthSemanticKind.authoritative_upward

    def test_partial_result_semantic_kind(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("partial_result")
        assert result == FlowTruthSemanticKind.partial_result

    def test_task_phase_is_execution_evidence(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("task_phase")
        assert result == FlowTruthSemanticKind.execution_evidence

    def test_session_snapshot_is_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("session_snapshot")
        assert result == FlowTruthSemanticKind.advisory

    def test_readiness_assessment_is_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("readiness_assessment")
        assert result == FlowTruthSemanticKind.advisory

    def test_runtime_state_is_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("runtime_state")
        assert result == FlowTruthSemanticKind.advisory

    def test_status_is_execution_evidence(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("status")
        assert result == FlowTruthSemanticKind.execution_evidence

    def test_signal_is_execution_evidence(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("signal")
        assert result == FlowTruthSemanticKind.execution_evidence

    def test_unknown_kind_is_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("unknown")
        assert result == FlowTruthSemanticKind.advisory

    def test_unrecognised_kind_defaults_to_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic("some_future_kind_xyz")
        assert result == FlowTruthSemanticKind.advisory

    def test_posture_change_makes_result_posture_sensitive(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic(
            "result", has_posture_changed=True
        )
        assert result == FlowTruthSemanticKind.posture_sensitive

    def test_posture_change_makes_partial_result_posture_sensitive(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic(
            "partial_result", has_posture_changed=True
        )
        assert result == FlowTruthSemanticKind.posture_sensitive

    def test_posture_change_does_not_affect_advisory(self):
        from core.flow_level_truth_ownership import (
            classify_android_truth_semantic,
            FlowTruthSemanticKind,
        )
        result = classify_android_truth_semantic(
            "session_snapshot", has_posture_changed=True
        )
        assert result == FlowTruthSemanticKind.advisory


# ===========================================================================
# M–X. decide_flow_truth_alignment
# ===========================================================================


class TestDecideFlowTruthAlignment:
    """Tests for the primary alignment decision function."""

    def _make_ctx(self, **kwargs):
        from core.flow_level_truth_ownership import FlowTruthOwnershipContext
        return FlowTruthOwnershipContext(flow_id="flow-test-001", **kwargs)

    def test_compat_influence_produces_block_verdict(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
            compat_influence_detected=True,
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.block_due_to_compat_influence

    def test_posture_change_non_advisory_produces_quarantine(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
            source_runtime_posture="control_only",
            prior_posture="join_runtime",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.quarantine_due_to_posture_conflict

    def test_posture_change_advisory_passes_through_quarantine_block(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="session_snapshot",
            flow_phase="executing",
            source_runtime_posture="control_only",
            prior_posture="join_runtime",
        )
        # advisory kinds skip posture quarantine
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.accept_as_advisory

    def test_terminal_flow_result_is_rejected(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="completed",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal

    def test_terminal_flow_advisory_is_also_rejected(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="session_snapshot",
            flow_phase="failed",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal

    def test_non_terminal_flow_result_is_authoritative(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.accept_as_authoritative

    def test_non_terminal_flow_failure_is_authoritative(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="failure",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.accept_as_authoritative

    def test_non_terminal_flow_cancel_is_authoritative(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="cancel",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.accept_as_authoritative

    def test_non_terminal_flow_partial_result_is_recorded(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="partial_result",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.record_as_partial_result

    def test_non_terminal_flow_task_phase_is_execution_evidence(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="task_phase",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.record_as_execution_evidence

    def test_non_terminal_flow_advisory_is_advisory(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        ctx = self._make_ctx(
            android_truth_kind="readiness_assessment",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.verdict == FlowTruthAlignmentVerdict.accept_as_advisory

    def test_intermediate_pending_true_when_executing(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.is_intermediate_pending is True

    def test_intermediate_pending_true_when_reconciling(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="reconciling",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.is_intermediate_pending is True

    def test_intermediate_pending_false_for_advisory(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="session_snapshot",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.is_intermediate_pending is False

    def test_strict_mode_raises_for_compat_block(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
            compat_influence_detected=True,
        )
        with pytest.raises(RuntimeError):
            decide_flow_truth_alignment(ctx, strict=True)

    def test_strict_mode_raises_for_terminal_reject(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="completed",
        )
        with pytest.raises(RuntimeError):
            decide_flow_truth_alignment(ctx, strict=True)

    def test_decision_to_dict_contains_all_keys(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        d = decision.to_dict()
        expected_keys = {
            "verdict", "semantic_kind", "flow_id", "android_truth_kind",
            "flow_phase_at_decision", "posture_at_decision",
            "is_intermediate_pending", "policy_reference", "reason",
            "timestamp", "metadata",
        }
        assert expected_keys.issubset(d.keys())

    def test_decision_carries_correct_flow_id(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="result",
            flow_phase="executing",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.flow_id == "flow-test-001"

    def test_decision_carries_correct_phase(self):
        from core.flow_level_truth_ownership import decide_flow_truth_alignment
        ctx = self._make_ctx(
            android_truth_kind="task_phase",
            flow_phase="dispatched",
        )
        decision = decide_flow_truth_alignment(ctx)
        assert decision.flow_phase_at_decision == "dispatched"

    def test_all_four_terminal_phases_reject(self):
        from core.flow_level_truth_ownership import (
            decide_flow_truth_alignment,
            FlowTruthAlignmentVerdict,
        )
        for phase in ("completed", "failed", "cancelled", "timed_out"):
            ctx = self._make_ctx(android_truth_kind="result", flow_phase=phase)
            decision = decide_flow_truth_alignment(ctx)
            assert decision.verdict == FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal, (
                f"Phase {phase!r} should produce reject_due_to_canonical_terminal"
            )


# ===========================================================================
# Z–BB. record_flow_truth_alignment + FlowTruthAlignmentRecord
# ===========================================================================


class TestRecordFlowTruthAlignment:
    def setup_method(self):
        from core.flow_level_truth_ownership import reset_flow_truth_alignment_runtime
        reset_flow_truth_alignment_runtime()

    def test_record_persisted_in_runtime(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            get_flow_truth_alignment_runtime,
        )
        ctx = FlowTruthOwnershipContext(
            flow_id="flow-rec-001",
            android_truth_kind="result",
            flow_phase="executing",
        )
        record_flow_truth_alignment(ctx)
        runtime = get_flow_truth_alignment_runtime()
        assert runtime.count() == 1

    def test_records_for_flow_filters_correctly(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            get_flow_truth_alignment_runtime,
        )
        ctx_a = FlowTruthOwnershipContext(
            flow_id="flow-A", android_truth_kind="result", flow_phase="executing"
        )
        ctx_b = FlowTruthOwnershipContext(
            flow_id="flow-B", android_truth_kind="task_phase", flow_phase="executing"
        )
        record_flow_truth_alignment(ctx_a)
        record_flow_truth_alignment(ctx_b)
        runtime = get_flow_truth_alignment_runtime()
        records_a = runtime.records_for_flow("flow-A")
        records_b = runtime.records_for_flow("flow-B")
        assert len(records_a) == 1
        assert len(records_b) == 1
        assert records_a[0].flow_id == "flow-A"
        assert records_b[0].flow_id == "flow-B"

    def test_record_to_dict_contains_expected_keys(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
        )
        ctx = FlowTruthOwnershipContext(
            flow_id="flow-dict-001",
            android_truth_kind="result",
            flow_phase="executing",
            task_id="task-001",
            session_id="session-001",
            device_id="device-001",
        )
        record = record_flow_truth_alignment(ctx)
        d = record.to_dict()
        expected_keys = {
            "record_id", "decision", "flow_id", "task_id",
            "session_id", "device_id", "timestamp", "metadata",
        }
        assert expected_keys.issubset(d.keys())
        assert d["flow_id"] == "flow-dict-001"
        assert d["task_id"] == "task-001"

    def test_record_id_starts_with_fta_prefix(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
        )
        ctx = FlowTruthOwnershipContext(
            flow_id="flow-id-001", android_truth_kind="cancel", flow_phase="executing"
        )
        record = record_flow_truth_alignment(ctx)
        assert record.record_id.startswith("fta_")


# ===========================================================================
# CC–FF. build_flow_truth_ownership_snapshot
# ===========================================================================


class TestBuildFlowTruthOwnershipSnapshot:
    def setup_method(self):
        from core.flow_level_truth_ownership import reset_flow_truth_alignment_runtime
        reset_flow_truth_alignment_runtime()

    def test_snapshot_has_expected_top_level_keys(self):
        from core.flow_level_truth_ownership import build_flow_truth_ownership_snapshot
        snapshot = build_flow_truth_ownership_snapshot()
        expected_keys = {
            "authority", "pr_sentinel", "policy_sentinels",
            "ownership_roles", "total_records", "records", "timestamp",
        }
        assert expected_keys.issubset(snapshot.keys())

    def test_snapshot_policy_sentinels_contains_all_seven(self):
        from core.flow_level_truth_ownership import (
            build_flow_truth_ownership_snapshot,
            V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY,
            ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY,
            PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY,
            POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY,
            COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY,
            TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY,
            ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY,
        )
        snapshot = build_flow_truth_ownership_snapshot()
        policy_list = snapshot["policy_sentinels"]
        for sentinel in (
            V2_OWNS_CANONICAL_TERMINAL_TRUTH_POLICY,
            ANDROID_TRUTH_ABSORBED_BY_SEMANTIC_CATEGORY_POLICY,
            PARTIAL_RESULT_STORED_IN_TRACKING_RECORD_POLICY,
            POSTURE_CHANGE_QUARANTINES_POSTURE_SENSITIVE_TRUTH_POLICY,
            COMPAT_INFLUENCE_BLOCKS_TRUTH_ALIGNMENT_PATH_POLICY,
            TERMINAL_FLOW_REJECTS_ALL_ANDROID_UPDATES_POLICY,
            ANDROID_IN_FLIGHT_TRUTH_IS_INTERMEDIATE_PENDING_POLICY,
        ):
            assert sentinel in policy_list

    def test_snapshot_ownership_roles_has_three_entries(self):
        from core.flow_level_truth_ownership import build_flow_truth_ownership_snapshot
        snapshot = build_flow_truth_ownership_snapshot()
        roles = snapshot["ownership_roles"]
        role_names = {r["role"] for r in roles}
        assert role_names == {"owner", "coordinator", "policy"}

    def test_snapshot_filtered_by_flow_id(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            build_flow_truth_ownership_snapshot,
        )
        ctx_x = FlowTruthOwnershipContext(
            flow_id="snap-flow-X", android_truth_kind="result", flow_phase="executing"
        )
        ctx_y = FlowTruthOwnershipContext(
            flow_id="snap-flow-Y", android_truth_kind="task_phase", flow_phase="executing"
        )
        record_flow_truth_alignment(ctx_x)
        record_flow_truth_alignment(ctx_y)
        snapshot_x = build_flow_truth_ownership_snapshot(flow_id="snap-flow-X")
        assert all(r["flow_id"] == "snap-flow-X" for r in snapshot_x["records"])
        assert len(snapshot_x["records"]) == 1

    def test_snapshot_total_records_reflects_count(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            build_flow_truth_ownership_snapshot,
        )
        for i in range(3):
            ctx = FlowTruthOwnershipContext(
                flow_id=f"flow-count-{i}",
                android_truth_kind="task_phase",
                flow_phase="executing",
            )
            record_flow_truth_alignment(ctx)
        snapshot = build_flow_truth_ownership_snapshot()
        assert snapshot["total_records"] == 3


# ===========================================================================
# GG. reset_flow_truth_alignment_runtime
# ===========================================================================


class TestReset:
    def test_reset_clears_runtime(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            get_flow_truth_alignment_runtime,
            reset_flow_truth_alignment_runtime,
        )
        reset_flow_truth_alignment_runtime()
        ctx = FlowTruthOwnershipContext(
            flow_id="flow-reset-001",
            android_truth_kind="result",
            flow_phase="executing",
        )
        record_flow_truth_alignment(ctx)
        assert get_flow_truth_alignment_runtime().count() == 1
        reset_flow_truth_alignment_runtime()
        assert get_flow_truth_alignment_runtime().count() == 0

    def test_reset_returns_fresh_runtime_singleton(self):
        from core.flow_level_truth_ownership import (
            get_flow_truth_alignment_runtime,
            reset_flow_truth_alignment_runtime,
        )
        reset_flow_truth_alignment_runtime()
        runtime_1 = get_flow_truth_alignment_runtime()
        reset_flow_truth_alignment_runtime()
        runtime_2 = get_flow_truth_alignment_runtime()
        assert runtime_1 is not runtime_2


# ===========================================================================
# HH. Multiple records accumulate correctly
# ===========================================================================


class TestRingBufferAccumulation:
    def setup_method(self):
        from core.flow_level_truth_ownership import reset_flow_truth_alignment_runtime
        reset_flow_truth_alignment_runtime()

    def test_multiple_verdict_types_accumulate(self):
        from core.flow_level_truth_ownership import (
            FlowTruthOwnershipContext,
            record_flow_truth_alignment,
            get_flow_truth_alignment_runtime,
            FlowTruthAlignmentVerdict,
        )
        scenarios = [
            ("result", "executing", False, False),  # accept_as_authoritative
            ("readiness_assessment", "executing", False, False),  # accept_as_advisory
            ("result", "completed", False, False),  # reject_due_to_canonical_terminal
            ("result", "executing", False, True),   # block_due_to_compat_influence
        ]
        for truth_kind, flow_phase, _, compat in scenarios:
            ctx = FlowTruthOwnershipContext(
                flow_id="flow-multi-001",
                android_truth_kind=truth_kind,
                flow_phase=flow_phase,
                compat_influence_detected=compat,
            )
            record_flow_truth_alignment(ctx)

        runtime = get_flow_truth_alignment_runtime()
        assert runtime.count() == 4

        verdicts = {r.decision.verdict for r in runtime.snapshot()}
        assert FlowTruthAlignmentVerdict.accept_as_authoritative in verdicts
        assert FlowTruthAlignmentVerdict.accept_as_advisory in verdicts
        assert FlowTruthAlignmentVerdict.reject_due_to_canonical_terminal in verdicts
        assert FlowTruthAlignmentVerdict.block_due_to_compat_influence in verdicts
