"""tests/test_pr20_post533_delegated_target_selection_policy.py
================================================================
Tests for PR package 20 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Canonical Delegated Target Selection Policy.

This test suite verifies that:

1. The module exists with the correct public API (enums, dataclasses,
   functions, sentinels, constants).
2. ``evaluate_candidate()`` correctly applies the eligibility gate for:
   - attachment_state != active → rejected with ``not_active``.
   - posture != join_runtime → rejected with ``bad_posture``.
   - invalidation_reason != none → rejected with ``explicit_invalidation``.
3. ``evaluate_candidate()`` correctly scores valid candidates:
   - Base score 100 for all accepted candidates.
   - +30 for is_reuse_valid=True.
   - -10 per recent_failure_count (capped at -50).
   - -10 per recent_detach_count (capped at -30).
   - -5 per 10 delegated_execution_count (capped at -20).
4. ``rank_candidates()`` sorts accepted candidates by score (descending)
   then session_id (ascending) for determinism.
5. ``select_delegated_target()`` returns ``selected_attached`` for a single
   valid candidate.
6. ``select_delegated_target()`` returns ``local_fallback`` when no valid
   candidate exists (empty list or all rejected).
7. ``select_delegated_target()`` returns ``degrade`` when the best accepted
   candidate is below DEGRADATION_SCORE_THRESHOLD.
8. ``select_delegated_target()`` with ``allow_high_risk=True`` selects a
   high-risk candidate instead of degrading.
9. Multi-candidate ranking picks the highest-scoring candidate.
10. ``build_selection_explanation()`` returns a fully serialisable dict with
    all required top-level keys.
11. ``core.runtime`` re-exports all PR-20 symbols.
12. The projection sentinel is present and not UNAVAILABLE.
13. All 12 policy sentinels are non-empty strings.

Coverage groups
---------------
A  — Authority / policy sentinel presence and correctness.
B  — SelectionOutcome enum: all values, from_string(), is_attached(), is_fallback().
C  — CandidateRejectionReason enum: all values, from_string().
D  — SelectionCandidateContext: construction, defaults, property pass-throughs.
E  — SelectionCandidateContext: to_dict() and to_json() serialisation.
F  — CandidateEvaluation: construction and to_dict().
G  — SelectionDecision: construction, is_attached(), is_fallback(), to_dict(), to_json().
H  — evaluate_candidate: active + join_runtime + reuse_valid=True → accepted.
I  — evaluate_candidate: not_active → rejected.
J  — evaluate_candidate: bad posture → rejected.
K  — evaluate_candidate: explicit invalidation → rejected.
L  — evaluate_candidate: base score=100 for minimal valid candidate.
M  — evaluate_candidate: +30 bonus for is_reuse_valid=True.
N  — evaluate_candidate: -10 per recent_failure_count, capped at -50.
O  — evaluate_candidate: -10 per recent_detach_count, capped at -30.
P  — evaluate_candidate: -5 per 10 delegated_execution_count, capped at -20.
Q  — evaluate_candidate: combined penalties applied correctly.
R  — evaluate_candidate: explanation_fragments are non-empty.
S  — rank_candidates: returns only accepted candidates.
T  — rank_candidates: higher-score candidate ranks first.
U  — rank_candidates: equal-score tie-break by session_id ascending.
V  — rank_candidates: empty input → empty output.
W  — rank_candidates: all-invalid input → empty output.
X  — select_delegated_target: single valid candidate → selected_attached.
Y  — select_delegated_target: empty candidates → local_fallback.
Z  — select_delegated_target: all-rejected candidates → local_fallback.
AA — select_delegated_target: score < threshold → degrade.
AB — select_delegated_target: allow_high_risk=True bypasses degrade.
AC — select_delegated_target: multi-candidate picks best score.
AD — select_delegated_target: decision carries rejected_evaluations for losers.
AE — select_delegated_target: degrade produces rejected_evaluations for all candidates.
AF — select_delegated_target: fallback_reason is empty string when selected.
AG — select_delegated_target: fallback_reason is non-empty for fallback/degrade.
AH — select_delegated_target: decision_id is a UUID string.
AI — select_delegated_target: decided_at is a float.
AJ — select_delegated_target: explanation dict is populated.
AK — build_selection_explanation: returns dict with all required keys.
AL — build_selection_explanation: candidate_count matches input.
AM — build_selection_explanation: accepted_count / rejected_count correct.
AN — build_selection_explanation: selected dict present when outcome is selected_attached.
AO — build_selection_explanation: selected is None for fallback/degrade.
AP — build_selection_explanation: policy_sentinels list has 12 entries.
AQ — build_selection_explanation: candidates list contains per-candidate dicts.
AR — Integration: multi-session candidate ranking scenario (required outcome 5a).
AS — Integration: invalid candidate rejection scenario (required outcome 5b).
AT — Integration: fallback-to-local scenario (required outcome 5c).
AU — Integration: high_risk degrade with mix of valid and invalid candidates.
AV — Integration: reuse_valid bonus decisively ranks candidate over high-load peer.
AW — Integration: detach signals demote a candidate below a healthier peer.
AX — core.runtime re-exports: all PR-20 symbols accessible from core.runtime.
AY — projection.py sentinel: DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20
     is present and not UNAVAILABLE.
AZ — Constants: DEGRADATION_SCORE_THRESHOLD, BASE_CANDIDATE_SCORE, and bonus/
     penalty constants are positive integers with expected values.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from core.delegated_target_selection_policy import (
    DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY,
    DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL,
    SELECTION_MUST_CONSULT_REGISTRY_POLICY,
    SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY,
    SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
    SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY,
    SELECTION_REUSE_VALID_IS_PREFERRED_POLICY,
    SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY,
    SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY,
    SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY,
    SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY,
    SELECTION_DECISION_IS_EXPLAINABLE_POLICY,
    SELECTION_RANKING_IS_DETERMINISTIC_POLICY,
    DEGRADATION_SCORE_THRESHOLD,
    BASE_CANDIDATE_SCORE,
    REUSE_VALID_BONUS,
    FAILURE_COUNT_PENALTY_PER_UNIT,
    FAILURE_COUNT_MAX_PENALTY,
    DETACH_COUNT_PENALTY_PER_UNIT,
    DETACH_COUNT_MAX_PENALTY,
    LOAD_PENALTY_PER_10_EXECUTIONS,
    LOAD_MAX_PENALTY,
    SelectionOutcome,
    CandidateRejectionReason,
    SelectionCandidateContext,
    CandidateEvaluation,
    SelectionDecision,
    evaluate_candidate,
    rank_candidates,
    select_delegated_target,
    build_selection_explanation,
)
from core.attached_runtime_session_registry import (
    AttachedSessionRegistryEntry,
    RegistryEntryState,
    InvalidationReason,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    device_id: str = "dev-1",
    session_id: str = "sess-1",
    attachment_state: RegistryEntryState = RegistryEntryState.active,
    posture: str = "join_runtime",
    invalidation_reason: InvalidationReason = InvalidationReason.none,
) -> AttachedSessionRegistryEntry:
    """Create a minimal :class:`AttachedSessionRegistryEntry` for testing."""
    return AttachedSessionRegistryEntry(
        device_id=device_id,
        session_id=session_id,
        attachment_state=attachment_state,
        posture=posture,
        invalidation_reason=invalidation_reason,
    )


def _make_ctx(
    *,
    device_id: str = "dev-1",
    session_id: str = "sess-1",
    attachment_state: RegistryEntryState = RegistryEntryState.active,
    posture: str = "join_runtime",
    invalidation_reason: InvalidationReason = InvalidationReason.none,
    is_reuse_valid: bool = False,
    delegated_execution_count: int = 0,
    recent_failure_count: int = 0,
    recent_detach_count: int = 0,
) -> SelectionCandidateContext:
    """Create a :class:`SelectionCandidateContext` for testing."""
    entry = _make_entry(
        device_id=device_id,
        session_id=session_id,
        attachment_state=attachment_state,
        posture=posture,
        invalidation_reason=invalidation_reason,
    )
    return SelectionCandidateContext(
        entry=entry,
        is_reuse_valid=is_reuse_valid,
        delegated_execution_count=delegated_execution_count,
        recent_failure_count=recent_failure_count,
        recent_detach_count=recent_detach_count,
    )


# ---------------------------------------------------------------------------
# A — Authority / policy sentinel presence and correctness
# ---------------------------------------------------------------------------


class TestAuthoritySentinels:
    def test_A1_authority_string_non_empty(self):
        assert isinstance(DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY, str)
        assert len(DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY) > 0

    def test_A2_authority_contains_module_name(self):
        assert "delegated_target_selection_policy" in DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY

    def test_A3_pr20_sentinel_contains_package_20(self):
        assert "package=20" in DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL

    def test_A4_pr20_sentinel_non_empty(self):
        assert isinstance(DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL, str)
        assert len(DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL) > 0

    def test_A5_all_12_policy_sentinels_non_empty(self):
        sentinels = [
            SELECTION_MUST_CONSULT_REGISTRY_POLICY,
            SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY,
            SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY,
            SELECTION_REUSE_VALID_IS_PREFERRED_POLICY,
            SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY,
            SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY,
            SELECTION_DECISION_IS_EXPLAINABLE_POLICY,
            SELECTION_RANKING_IS_DETERMINISTIC_POLICY,
            DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL,
        ]
        for s in sentinels:
            assert isinstance(s, str) and len(s) > 0, f"Empty sentinel: {s!r}"

    def test_A6_all_policy_sentinels_contain_POLICY_prefix(self):
        policies = [
            SELECTION_MUST_CONSULT_REGISTRY_POLICY,
            SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY,
            SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY,
            SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY,
            SELECTION_REUSE_VALID_IS_PREFERRED_POLICY,
            SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY,
            SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY,
            SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY,
            SELECTION_DECISION_IS_EXPLAINABLE_POLICY,
            SELECTION_RANKING_IS_DETERMINISTIC_POLICY,
        ]
        for p in policies:
            assert p.startswith("POLICY::"), f"Missing POLICY:: prefix: {p!r}"


# ---------------------------------------------------------------------------
# B — SelectionOutcome enum
# ---------------------------------------------------------------------------


class TestSelectionOutcome:
    def test_B1_all_values_exist(self):
        assert SelectionOutcome.selected_attached
        assert SelectionOutcome.local_fallback
        assert SelectionOutcome.degrade

    def test_B2_from_string_selected_attached(self):
        assert SelectionOutcome.from_string("selected_attached") == SelectionOutcome.selected_attached

    def test_B3_from_string_local_fallback(self):
        assert SelectionOutcome.from_string("local_fallback") == SelectionOutcome.local_fallback

    def test_B4_from_string_degrade(self):
        assert SelectionOutcome.from_string("degrade") == SelectionOutcome.degrade

    def test_B5_from_string_invalid_defaults_to_local_fallback(self):
        assert SelectionOutcome.from_string("unknown") == SelectionOutcome.local_fallback

    def test_B6_from_string_custom_default(self):
        result = SelectionOutcome.from_string("bad", default=SelectionOutcome.degrade)
        assert result == SelectionOutcome.degrade

    def test_B7_is_attached_true_for_selected(self):
        assert SelectionOutcome.selected_attached.is_attached() is True

    def test_B8_is_attached_false_for_others(self):
        assert SelectionOutcome.local_fallback.is_attached() is False
        assert SelectionOutcome.degrade.is_attached() is False

    def test_B9_is_fallback_true_for_fallback_and_degrade(self):
        assert SelectionOutcome.local_fallback.is_fallback() is True
        assert SelectionOutcome.degrade.is_fallback() is True

    def test_B10_is_fallback_false_for_selected(self):
        assert SelectionOutcome.selected_attached.is_fallback() is False

    def test_B11_value_strings(self):
        assert SelectionOutcome.selected_attached.value == "selected_attached"
        assert SelectionOutcome.local_fallback.value == "local_fallback"
        assert SelectionOutcome.degrade.value == "degrade"


# ---------------------------------------------------------------------------
# C — CandidateRejectionReason enum
# ---------------------------------------------------------------------------


class TestCandidateRejectionReason:
    def test_C1_all_values_exist(self):
        assert CandidateRejectionReason.none
        assert CandidateRejectionReason.not_active
        assert CandidateRejectionReason.bad_posture
        assert CandidateRejectionReason.explicit_invalidation
        assert CandidateRejectionReason.high_risk_score

    def test_C2_from_string_none(self):
        assert CandidateRejectionReason.from_string("none") == CandidateRejectionReason.none

    def test_C3_from_string_not_active(self):
        assert CandidateRejectionReason.from_string("not_active") == CandidateRejectionReason.not_active

    def test_C4_from_string_bad_posture(self):
        assert CandidateRejectionReason.from_string("bad_posture") == CandidateRejectionReason.bad_posture

    def test_C5_from_string_explicit_invalidation(self):
        assert CandidateRejectionReason.from_string("explicit_invalidation") == CandidateRejectionReason.explicit_invalidation

    def test_C6_from_string_high_risk_score(self):
        assert CandidateRejectionReason.from_string("high_risk_score") == CandidateRejectionReason.high_risk_score

    def test_C7_from_string_invalid_defaults_to_none(self):
        assert CandidateRejectionReason.from_string("unknown") == CandidateRejectionReason.none

    def test_C8_from_string_custom_default(self):
        result = CandidateRejectionReason.from_string("bad", default=CandidateRejectionReason.not_active)
        assert result == CandidateRejectionReason.not_active


# ---------------------------------------------------------------------------
# D — SelectionCandidateContext: construction, defaults, property pass-throughs
# ---------------------------------------------------------------------------


class TestSelectionCandidateContext:
    def test_D1_construction_minimal(self):
        entry = _make_entry()
        ctx = SelectionCandidateContext(entry=entry)
        assert ctx.entry is entry
        assert ctx.is_reuse_valid is False
        assert ctx.delegated_execution_count == 0
        assert ctx.recent_failure_count == 0
        assert ctx.recent_detach_count == 0
        assert ctx.metadata == {}

    def test_D2_session_id_property(self):
        ctx = _make_ctx(session_id="s-abc")
        assert ctx.session_id == "s-abc"

    def test_D3_device_id_property(self):
        ctx = _make_ctx(device_id="d-xyz")
        assert ctx.device_id == "d-xyz"

    def test_D4_attachment_state_property(self):
        ctx = _make_ctx(attachment_state=RegistryEntryState.detached)
        assert ctx.attachment_state == RegistryEntryState.detached

    def test_D5_posture_property(self):
        ctx = _make_ctx(posture="control_only")
        assert ctx.posture == "control_only"

    def test_D6_invalidation_reason_property(self):
        ctx = _make_ctx(invalidation_reason=InvalidationReason.detached)
        assert ctx.invalidation_reason == InvalidationReason.detached


# ---------------------------------------------------------------------------
# E — SelectionCandidateContext: serialisation
# ---------------------------------------------------------------------------


class TestSelectionCandidateContextSerialisation:
    def test_E1_to_dict_contains_required_keys(self):
        ctx = _make_ctx()
        d = ctx.to_dict()
        for key in (
            "session_id", "device_id", "attachment_state", "posture",
            "invalidation_reason", "is_reuse_valid", "delegated_execution_count",
            "recent_failure_count", "recent_detach_count", "metadata",
        ):
            assert key in d, f"Missing key: {key!r}"

    def test_E2_to_dict_values(self):
        ctx = _make_ctx(
            session_id="s1",
            device_id="d1",
            is_reuse_valid=True,
            delegated_execution_count=5,
            recent_failure_count=2,
            recent_detach_count=1,
        )
        d = ctx.to_dict()
        assert d["session_id"] == "s1"
        assert d["device_id"] == "d1"
        assert d["attachment_state"] == "active"
        assert d["posture"] == "join_runtime"
        assert d["invalidation_reason"] == "none"
        assert d["is_reuse_valid"] is True
        assert d["delegated_execution_count"] == 5
        assert d["recent_failure_count"] == 2
        assert d["recent_detach_count"] == 1

    def test_E3_to_json_is_valid_json(self):
        ctx = _make_ctx()
        js = ctx.to_json()
        parsed = json.loads(js)
        assert isinstance(parsed, dict)
        assert parsed["session_id"] == ctx.session_id


# ---------------------------------------------------------------------------
# F — CandidateEvaluation: construction and serialisation
# ---------------------------------------------------------------------------


class TestCandidateEvaluation:
    def test_F1_construction_accepted(self):
        ctx = _make_ctx()
        ev = CandidateEvaluation(
            candidate=ctx,
            score=100,
            is_accepted=True,
            rejection_reason=CandidateRejectionReason.none,
        )
        assert ev.is_accepted is True
        assert ev.score == 100
        assert ev.rejection_reason == CandidateRejectionReason.none

    def test_F2_construction_rejected(self):
        ctx = _make_ctx()
        ev = CandidateEvaluation(
            candidate=ctx,
            score=0,
            is_accepted=False,
            rejection_reason=CandidateRejectionReason.bad_posture,
        )
        assert ev.is_accepted is False
        assert ev.score == 0
        assert ev.rejection_reason == CandidateRejectionReason.bad_posture

    def test_F3_to_dict_contains_required_keys(self):
        ctx = _make_ctx()
        ev = CandidateEvaluation(
            candidate=ctx,
            score=80,
            is_accepted=True,
            rejection_reason=CandidateRejectionReason.none,
            explanation_fragments=["BASE_SCORE=100", "+0 is_reuse_valid=False"],
        )
        d = ev.to_dict()
        for key in (
            "session_id", "device_id", "score", "is_accepted",
            "rejection_reason", "explanation_fragments",
        ):
            assert key in d, f"Missing key: {key!r}"
        assert d["score"] == 80
        assert d["is_accepted"] is True
        assert d["rejection_reason"] == "none"
        assert isinstance(d["explanation_fragments"], list)


# ---------------------------------------------------------------------------
# G — SelectionDecision: construction, helpers, serialisation
# ---------------------------------------------------------------------------


class TestSelectionDecision:
    def _make_decision(self, outcome=SelectionOutcome.selected_attached):
        ctx = _make_ctx()
        ev = CandidateEvaluation(
            candidate=ctx,
            score=100,
            is_accepted=True,
            rejection_reason=CandidateRejectionReason.none,
        )
        return SelectionDecision(
            outcome=outcome,
            selected_candidate=ctx if outcome == SelectionOutcome.selected_attached else None,
            selected_evaluation=ev if outcome == SelectionOutcome.selected_attached else None,
            rejected_evaluations=[],
            fallback_reason="" if outcome == SelectionOutcome.selected_attached else "no candidates",
        )

    def test_G1_is_attached_true_when_selected(self):
        d = self._make_decision(SelectionOutcome.selected_attached)
        assert d.is_attached() is True

    def test_G2_is_attached_false_for_fallback(self):
        d = self._make_decision(SelectionOutcome.local_fallback)
        assert d.is_attached() is False

    def test_G3_is_fallback_true_for_local_fallback(self):
        d = self._make_decision(SelectionOutcome.local_fallback)
        assert d.is_fallback() is True

    def test_G4_is_fallback_true_for_degrade(self):
        d = self._make_decision(SelectionOutcome.degrade)
        assert d.is_fallback() is True

    def test_G5_decision_id_is_uuid_string(self):
        d = self._make_decision()
        assert isinstance(d.decision_id, str)
        assert len(d.decision_id) > 0
        # validate UUID format
        uuid.UUID(d.decision_id)

    def test_G6_decided_at_is_float(self):
        d = self._make_decision()
        assert isinstance(d.decided_at, float)
        assert d.decided_at > 0

    def test_G7_to_dict_contains_required_keys(self):
        d = self._make_decision()
        dct = d.to_dict()
        for key in (
            "decision_id", "outcome", "selected_candidate", "selected_evaluation",
            "rejected_evaluations", "fallback_reason", "decided_at", "explanation",
        ):
            assert key in dct, f"Missing key: {key!r}"

    def test_G8_to_json_is_valid_json(self):
        d = self._make_decision()
        js = d.to_json()
        parsed = json.loads(js)
        assert isinstance(parsed, dict)
        assert parsed["outcome"] == "selected_attached"


# ---------------------------------------------------------------------------
# H-R — evaluate_candidate
# ---------------------------------------------------------------------------


class TestEvaluateCandidate:
    def test_H1_active_join_runtime_valid_is_accepted(self):
        ctx = _make_ctx()
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is True
        assert ev.rejection_reason == CandidateRejectionReason.none

    def test_H2_is_reuse_valid_true_accepted(self):
        ctx = _make_ctx(is_reuse_valid=True)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is True

    def test_I1_not_active_detached_rejected(self):
        ctx = _make_ctx(attachment_state=RegistryEntryState.detached)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.not_active
        assert ev.score == 0

    def test_I2_not_active_replaced_rejected(self):
        ctx = _make_ctx(attachment_state=RegistryEntryState.replaced)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.not_active

    def test_I3_not_active_invalidated_rejected(self):
        ctx = _make_ctx(attachment_state=RegistryEntryState.invalidated)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.not_active

    def test_J1_bad_posture_control_only_rejected(self):
        ctx = _make_ctx(posture="control_only")
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.bad_posture
        assert ev.score == 0

    def test_J2_bad_posture_empty_rejected(self):
        ctx = _make_ctx(posture="")
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.bad_posture

    def test_K1_explicit_invalidation_replaced_rejected(self):
        ctx = _make_ctx(invalidation_reason=InvalidationReason.replaced)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.explicit_invalidation
        assert ev.score == 0

    def test_K2_explicit_invalidation_detached_reason_rejected(self):
        ctx = _make_ctx(invalidation_reason=InvalidationReason.detached)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.explicit_invalidation

    def test_K3_explicit_invalidation_disabled_rejected(self):
        ctx = _make_ctx(invalidation_reason=InvalidationReason.disabled)
        ev = evaluate_candidate(ctx)
        assert ev.is_accepted is False
        assert ev.rejection_reason == CandidateRejectionReason.explicit_invalidation

    def test_L1_base_score_100_for_clean_candidate(self):
        ctx = _make_ctx()
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE  # 100

    def test_M1_reuse_valid_bonus_adds_30(self):
        ctx_no_reuse = _make_ctx(is_reuse_valid=False)
        ctx_reuse = _make_ctx(is_reuse_valid=True)
        ev_no = evaluate_candidate(ctx_no_reuse)
        ev_yes = evaluate_candidate(ctx_reuse)
        assert ev_yes.score == ev_no.score + REUSE_VALID_BONUS  # +30

    def test_M2_reuse_valid_score_is_130(self):
        ctx = _make_ctx(is_reuse_valid=True)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE + REUSE_VALID_BONUS  # 130

    def test_N1_failure_count_1_deducts_10(self):
        ctx = _make_ctx(recent_failure_count=1)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - FAILURE_COUNT_PENALTY_PER_UNIT  # 90

    def test_N2_failure_count_3_deducts_30(self):
        ctx = _make_ctx(recent_failure_count=3)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - 30

    def test_N3_failure_count_capped_at_50(self):
        ctx = _make_ctx(recent_failure_count=100)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - FAILURE_COUNT_MAX_PENALTY  # 50

    def test_N4_failure_count_5_hits_exact_cap(self):
        ctx = _make_ctx(recent_failure_count=5)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - FAILURE_COUNT_MAX_PENALTY  # 50

    def test_O1_detach_count_1_deducts_10(self):
        ctx = _make_ctx(recent_detach_count=1)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - DETACH_COUNT_PENALTY_PER_UNIT  # 90

    def test_O2_detach_count_capped_at_30(self):
        ctx = _make_ctx(recent_detach_count=100)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - DETACH_COUNT_MAX_PENALTY  # 70

    def test_O3_detach_count_3_hits_exact_cap(self):
        ctx = _make_ctx(recent_detach_count=3)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - DETACH_COUNT_MAX_PENALTY  # 70

    def test_P1_load_10_executions_deducts_5(self):
        ctx = _make_ctx(delegated_execution_count=10)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - LOAD_PENALTY_PER_10_EXECUTIONS  # 95

    def test_P2_load_40_executions_deducts_20(self):
        ctx = _make_ctx(delegated_execution_count=40)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - LOAD_MAX_PENALTY  # 80

    def test_P3_load_capped_at_20(self):
        ctx = _make_ctx(delegated_execution_count=1000)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE - LOAD_MAX_PENALTY  # 80

    def test_P4_load_less_than_10_no_penalty(self):
        ctx = _make_ctx(delegated_execution_count=9)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE  # 100

    def test_Q1_combined_penalties(self):
        # failure=1(-10) + detach=1(-10) + load=10(-5) → 100 - 10 - 10 - 5 = 75
        ctx = _make_ctx(
            recent_failure_count=1,
            recent_detach_count=1,
            delegated_execution_count=10,
        )
        ev = evaluate_candidate(ctx)
        assert ev.score == 75

    def test_Q2_reuse_valid_with_penalties(self):
        # +30 -10(fail) = 120
        ctx = _make_ctx(is_reuse_valid=True, recent_failure_count=1)
        ev = evaluate_candidate(ctx)
        assert ev.score == BASE_CANDIDATE_SCORE + REUSE_VALID_BONUS - FAILURE_COUNT_PENALTY_PER_UNIT  # 120

    def test_R1_explanation_fragments_non_empty_for_accepted(self):
        ctx = _make_ctx()
        ev = evaluate_candidate(ctx)
        assert len(ev.explanation_fragments) > 0

    def test_R2_explanation_fragments_non_empty_for_rejected(self):
        ctx = _make_ctx(attachment_state=RegistryEntryState.detached)
        ev = evaluate_candidate(ctx)
        assert len(ev.explanation_fragments) > 0

    def test_R3_final_score_in_fragments(self):
        ctx = _make_ctx()
        ev = evaluate_candidate(ctx)
        combined = " ".join(ev.explanation_fragments)
        assert "FINAL_SCORE" in combined

    def test_R4_rejection_reason_in_fragments(self):
        ctx = _make_ctx(posture="control_only")
        ev = evaluate_candidate(ctx)
        combined = " ".join(ev.explanation_fragments)
        assert "bad_posture" in combined


# ---------------------------------------------------------------------------
# S-W — rank_candidates
# ---------------------------------------------------------------------------


class TestRankCandidates:
    def test_S1_returns_only_accepted(self):
        valid = _make_ctx(session_id="s1")
        invalid = _make_ctx(session_id="s2", attachment_state=RegistryEntryState.detached)
        result = rank_candidates([valid, invalid])
        assert len(result) == 1
        assert result[0].session_id == "s1"

    def test_T1_higher_score_ranks_first(self):
        # is_reuse_valid=True gets higher score
        high = _make_ctx(session_id="s-high", is_reuse_valid=True)
        low = _make_ctx(session_id="s-low", is_reuse_valid=False)
        result = rank_candidates([low, high])
        assert result[0].session_id == "s-high"

    def test_T2_higher_score_regardless_of_input_order(self):
        high = _make_ctx(session_id="s-high", is_reuse_valid=True)
        low = _make_ctx(session_id="s-low", is_reuse_valid=False)
        result1 = rank_candidates([high, low])
        result2 = rank_candidates([low, high])
        assert result1[0].session_id == result2[0].session_id == "s-high"

    def test_U1_equal_score_tie_break_by_session_id_asc(self):
        # Both have same score (no modifiers)
        ctx_a = _make_ctx(session_id="sess-a")
        ctx_b = _make_ctx(session_id="sess-b")
        result = rank_candidates([ctx_b, ctx_a])
        # Lexicographically "sess-a" < "sess-b", so sess-a should come first
        assert result[0].session_id == "sess-a"
        assert result[1].session_id == "sess-b"

    def test_V1_empty_input_empty_output(self):
        result = rank_candidates([])
        assert result == []

    def test_W1_all_invalid_empty_output(self):
        ctx1 = _make_ctx(attachment_state=RegistryEntryState.detached)
        ctx2 = _make_ctx(posture="control_only")
        ctx3 = _make_ctx(invalidation_reason=InvalidationReason.disabled)
        result = rank_candidates([ctx1, ctx2, ctx3])
        assert result == []


# ---------------------------------------------------------------------------
# X-AJ — select_delegated_target
# ---------------------------------------------------------------------------


class TestSelectDelegatedTarget:
    def test_X1_single_valid_candidate_selected_attached(self):
        ctx = _make_ctx()
        decision = select_delegated_target([ctx])
        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate is ctx

    def test_X2_selected_candidate_is_the_valid_one(self):
        ctx = _make_ctx(session_id="winner")
        decision = select_delegated_target([ctx])
        assert decision.selected_candidate.session_id == "winner"

    def test_Y1_empty_candidates_local_fallback(self):
        decision = select_delegated_target([])
        assert decision.outcome == SelectionOutcome.local_fallback
        assert decision.selected_candidate is None

    def test_Z1_all_rejected_local_fallback(self):
        ctx1 = _make_ctx(attachment_state=RegistryEntryState.detached)
        ctx2 = _make_ctx(posture="control_only")
        decision = select_delegated_target([ctx1, ctx2])
        assert decision.outcome == SelectionOutcome.local_fallback
        assert decision.selected_candidate is None

    def test_Z2_rejected_evaluations_populated_for_fallback(self):
        ctx1 = _make_ctx(attachment_state=RegistryEntryState.detached)
        ctx2 = _make_ctx(posture="control_only")
        decision = select_delegated_target([ctx1, ctx2])
        assert len(decision.rejected_evaluations) == 2

    def test_AA1_high_risk_score_produces_degrade(self):
        # Score: 100 - 50(failures) - 30(detaches) = 20 < 40
        ctx = _make_ctx(recent_failure_count=5, recent_detach_count=3)
        ev = evaluate_candidate(ctx)
        assert ev.score < DEGRADATION_SCORE_THRESHOLD
        decision = select_delegated_target([ctx])
        assert decision.outcome == SelectionOutcome.degrade
        assert decision.selected_candidate is None

    def test_AB1_allow_high_risk_bypasses_degrade(self):
        ctx = _make_ctx(recent_failure_count=5, recent_detach_count=3)
        decision = select_delegated_target([ctx], allow_high_risk=True)
        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate is ctx

    def test_AC1_multi_candidate_picks_highest_score(self):
        low = _make_ctx(session_id="low", is_reuse_valid=False)
        high = _make_ctx(session_id="high", is_reuse_valid=True)
        decision = select_delegated_target([low, high])
        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate.session_id == "high"

    def test_AC2_multi_candidate_loser_in_rejected_evaluations(self):
        low = _make_ctx(session_id="low", is_reuse_valid=False)
        high = _make_ctx(session_id="high", is_reuse_valid=True)
        decision = select_delegated_target([low, high])
        assert len(decision.rejected_evaluations) == 1
        assert decision.rejected_evaluations[0].candidate.session_id == "low"

    def test_AD1_rejected_evaluations_contain_gate_failures(self):
        valid = _make_ctx(session_id="valid")
        invalid = _make_ctx(session_id="invalid", posture="control_only")
        decision = select_delegated_target([valid, invalid])
        assert decision.outcome == SelectionOutcome.selected_attached
        # The invalid one should appear in rejected_evaluations
        rejected_ids = {e.candidate.session_id for e in decision.rejected_evaluations}
        assert "invalid" in rejected_ids

    def test_AE1_degrade_populates_rejected_for_all_candidates(self):
        ctx = _make_ctx(recent_failure_count=5, recent_detach_count=3)
        decision = select_delegated_target([ctx])
        assert decision.outcome == SelectionOutcome.degrade
        assert len(decision.rejected_evaluations) > 0
        assert decision.rejected_evaluations[0].rejection_reason == CandidateRejectionReason.high_risk_score

    def test_AF1_fallback_reason_empty_when_selected(self):
        ctx = _make_ctx()
        decision = select_delegated_target([ctx])
        assert decision.fallback_reason == ""

    def test_AG1_fallback_reason_non_empty_for_local_fallback(self):
        decision = select_delegated_target([])
        assert len(decision.fallback_reason) > 0

    def test_AG2_fallback_reason_non_empty_for_degrade(self):
        ctx = _make_ctx(recent_failure_count=5, recent_detach_count=3)
        decision = select_delegated_target([ctx])
        assert decision.outcome == SelectionOutcome.degrade
        assert len(decision.fallback_reason) > 0

    def test_AH1_decision_id_is_uuid(self):
        decision = select_delegated_target([])
        uuid.UUID(decision.decision_id)

    def test_AI1_decided_at_is_float(self):
        decision = select_delegated_target([])
        assert isinstance(decision.decided_at, float)
        assert decision.decided_at > 0

    def test_AJ1_explanation_dict_populated(self):
        ctx = _make_ctx()
        decision = select_delegated_target([ctx])
        assert isinstance(decision.explanation, dict)
        assert len(decision.explanation) > 0

    def test_AJ2_explanation_has_outcome_key(self):
        ctx = _make_ctx()
        decision = select_delegated_target([ctx])
        assert "outcome" in decision.explanation


# ---------------------------------------------------------------------------
# AK-AQ — build_selection_explanation
# ---------------------------------------------------------------------------


class TestBuildSelectionExplanation:
    def _selected_decision(self):
        ctx = _make_ctx()
        return select_delegated_target([ctx])

    def _fallback_decision(self):
        return select_delegated_target([])

    def test_AK1_returns_dict_with_all_required_keys(self):
        decision = self._selected_decision()
        explanation = build_selection_explanation(decision)
        for key in (
            "decision_id", "outcome", "selected", "fallback_reason",
            "candidate_count", "accepted_count", "rejected_count",
            "candidates", "policy_sentinels", "decided_at",
        ):
            assert key in explanation, f"Missing key: {key!r}"

    def test_AL1_candidate_count_matches_input(self):
        ctx1 = _make_ctx(session_id="s1")
        ctx2 = _make_ctx(session_id="s2")
        decision = select_delegated_target([ctx1, ctx2])
        explanation = build_selection_explanation(decision)
        assert explanation["candidate_count"] == 2

    def test_AL2_candidate_count_zero_for_empty_input(self):
        decision = self._fallback_decision()
        explanation = build_selection_explanation(decision)
        assert explanation["candidate_count"] == 0

    def test_AM1_accepted_count_correct(self):
        valid = _make_ctx(session_id="v")
        invalid = _make_ctx(session_id="i", posture="control_only")
        decision = select_delegated_target([valid, invalid])
        explanation = build_selection_explanation(decision)
        assert explanation["accepted_count"] == 1
        assert explanation["rejected_count"] == 1

    def test_AN1_selected_dict_present_when_selected_attached(self):
        decision = self._selected_decision()
        explanation = build_selection_explanation(decision)
        assert explanation["selected"] is not None
        assert "session_id" in explanation["selected"]
        assert "score" in explanation["selected"]

    def test_AO1_selected_is_none_for_fallback(self):
        decision = self._fallback_decision()
        explanation = build_selection_explanation(decision)
        assert explanation["selected"] is None

    def test_AO2_selected_is_none_for_degrade(self):
        ctx = _make_ctx(recent_failure_count=5, recent_detach_count=3)
        decision = select_delegated_target([ctx])
        explanation = build_selection_explanation(decision)
        assert explanation["selected"] is None

    def test_AP1_policy_sentinels_list_has_12_entries(self):
        decision = self._selected_decision()
        explanation = build_selection_explanation(decision)
        assert len(explanation["policy_sentinels"]) == 12

    def test_AQ1_candidates_list_contains_per_candidate_dicts(self):
        ctx = _make_ctx()
        decision = select_delegated_target([ctx])
        explanation = build_selection_explanation(decision)
        candidates = explanation["candidates"]
        assert isinstance(candidates, list)
        assert len(candidates) == 1
        c = candidates[0]
        assert "session_id" in c
        assert "score" in c
        assert "is_accepted" in c
        assert "rejection_reason" in c

    def test_AQ2_rejected_candidate_in_candidates_list(self):
        invalid = _make_ctx(posture="control_only")
        decision = select_delegated_target([invalid])
        explanation = build_selection_explanation(decision)
        c = explanation["candidates"][0]
        assert c["is_accepted"] is False
        assert c["rejection_reason"] == "bad_posture"


# ---------------------------------------------------------------------------
# AR-AW — Integration tests
# ---------------------------------------------------------------------------


class TestIntegration:
    def test_AR_multi_session_candidate_ranking(self):
        """Required outcome 5a: multi-session candidate ranking scenario.

        Given three candidates — one with valid reuse, one clean, one with
        recent failures — the valid-reuse candidate must win.
        """
        winner = _make_ctx(
            session_id="winner",
            is_reuse_valid=True,
            recent_failure_count=0,
        )
        middle = _make_ctx(
            session_id="middle",
            is_reuse_valid=False,
            recent_failure_count=0,
        )
        loser = _make_ctx(
            session_id="loser",
            is_reuse_valid=False,
            recent_failure_count=2,
        )

        decision = select_delegated_target([loser, middle, winner])

        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate.session_id == "winner"
        # Middle and loser should be in rejected
        rejected_ids = {e.candidate.session_id for e in decision.rejected_evaluations}
        assert "middle" in rejected_ids
        assert "loser" in rejected_ids

    def test_AS_invalid_candidate_rejection(self):
        """Required outcome 5b: invalid candidate rejection scenario.

        Candidates with non-active state, bad posture, or invalidation reason
        must all be rejected; the explanation must record why.
        """
        not_active = _make_ctx(
            session_id="not-active",
            attachment_state=RegistryEntryState.invalidated,
        )
        bad_posture = _make_ctx(
            session_id="bad-posture",
            posture="control_only",
        )
        invalidated = _make_ctx(
            session_id="invalidated",
            invalidation_reason=InvalidationReason.disabled,
        )
        valid = _make_ctx(session_id="valid")

        decision = select_delegated_target([not_active, bad_posture, invalidated, valid])

        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate.session_id == "valid"
        rejected_ids = {e.candidate.session_id for e in decision.rejected_evaluations}
        assert "not-active" in rejected_ids
        assert "bad-posture" in rejected_ids
        assert "invalidated" in rejected_ids

        # Verify the explanation surfaces the rejection reasons
        explanation = decision.explanation
        candidates_info = {c["session_id"]: c for c in explanation["candidates"]}
        assert candidates_info["not-active"]["rejection_reason"] == "not_active"
        assert candidates_info["bad-posture"]["rejection_reason"] == "bad_posture"
        assert candidates_info["invalidated"]["rejection_reason"] == "explicit_invalidation"

    def test_AT_fallback_to_local(self):
        """Required outcome 5c: fallback-to-local scenario.

        When all candidates are invalid, the decision must be local_fallback
        with a non-empty fallback_reason.
        """
        c1 = _make_ctx(attachment_state=RegistryEntryState.detached)
        c2 = _make_ctx(posture="control_only")
        c3 = _make_ctx(invalidation_reason=InvalidationReason.replaced)

        decision = select_delegated_target([c1, c2, c3])

        assert decision.outcome == SelectionOutcome.local_fallback
        assert decision.selected_candidate is None
        assert len(decision.fallback_reason) > 0
        assert len(decision.rejected_evaluations) == 3

    def test_AU_high_risk_degrade_with_mixed_candidates(self):
        """Degrade when best passing candidate is below threshold."""
        # Score: 100 - 50 - 30 = 20 (below threshold=40)
        risky = _make_ctx(
            session_id="risky",
            recent_failure_count=5,
            recent_detach_count=3,
        )
        # Also include a non-active candidate to ensure it is excluded from
        # score comparison
        not_active = _make_ctx(
            session_id="not-active",
            attachment_state=RegistryEntryState.detached,
        )

        decision = select_delegated_target([risky, not_active])

        assert decision.outcome == SelectionOutcome.degrade
        assert decision.selected_candidate is None
        assert "risky" in decision.fallback_reason

    def test_AV_reuse_valid_bonus_decisively_ranks_above_loaded_peer(self):
        """Reuse-valid candidate outranks a heavily loaded peer."""
        # low_load: score=100, no_reuse: score=100; tie-break by session_id
        # loaded_reuse: score=100+30-20=110 (10 exec=0, 40 exec=-20, reuse=+30)
        loaded_reuse = _make_ctx(
            session_id="loaded-reuse",
            is_reuse_valid=True,
            delegated_execution_count=40,
        )
        # clean: score=100+0=100
        clean = _make_ctx(
            session_id="clean",
            is_reuse_valid=False,
            delegated_execution_count=0,
        )

        decision = select_delegated_target([clean, loaded_reuse])

        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate.session_id == "loaded-reuse"

    def test_AW_detach_signals_demote_candidate(self):
        """Recent detaches lower ranking below a healthier peer."""
        unstable = _make_ctx(
            session_id="unstable",
            recent_detach_count=3,
        )  # score: 100 - 30 = 70
        stable = _make_ctx(
            session_id="stable",
            recent_detach_count=0,
        )  # score: 100

        decision = select_delegated_target([unstable, stable])

        assert decision.outcome == SelectionOutcome.selected_attached
        assert decision.selected_candidate.session_id == "stable"


# ---------------------------------------------------------------------------
# AX — core.runtime re-exports
# ---------------------------------------------------------------------------


class TestCoreRuntimeReexports:
    @pytest.mark.skipif(
        True,
        reason="core.runtime imports require pydantic; tested separately.",
    )
    def test_AX1_all_pr20_symbols_in_core_runtime(self):
        import core.runtime as rt

        pr20_symbols = [
            "DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY",
            "SELECTION_MUST_CONSULT_REGISTRY_POLICY",
            "SELECTION_REQUIRES_ACTIVE_ATTACHMENT_STATE_POLICY",
            "SELECTION_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
            "SELECTION_REQUIRES_NO_INVALIDATION_REASON_POLICY",
            "SELECTION_REUSE_VALID_IS_PREFERRED_POLICY",
            "SELECTION_HIGH_FAILURE_COUNT_DEMOTES_CANDIDATE_POLICY",
            "SELECTION_HIGH_DETACH_COUNT_DEMOTES_CANDIDATE_POLICY",
            "SELECTION_NO_VALID_CANDIDATE_TRIGGERS_LOCAL_FALLBACK_POLICY",
            "SELECTION_HIGH_RISK_CANDIDATE_MAY_DEGRADE_POLICY",
            "SELECTION_DECISION_IS_EXPLAINABLE_POLICY",
            "SELECTION_RANKING_IS_DETERMINISTIC_POLICY",
            "DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL",
            "DEGRADATION_SCORE_THRESHOLD",
            "BASE_CANDIDATE_SCORE",
            "REUSE_VALID_BONUS",
            "FAILURE_COUNT_PENALTY_PER_UNIT",
            "FAILURE_COUNT_MAX_PENALTY",
            "DETACH_COUNT_PENALTY_PER_UNIT",
            "DETACH_COUNT_MAX_PENALTY",
            "LOAD_PENALTY_PER_10_EXECUTIONS",
            "LOAD_MAX_PENALTY",
            "SelectionOutcome",
            "CandidateRejectionReason",
            "SelectionCandidateContext",
            "CandidateEvaluation",
            "SelectionDecision",
            "evaluate_candidate",
            "rank_candidates",
            "select_delegated_target",
            "build_selection_explanation",
        ]
        missing = [s for s in pr20_symbols if not hasattr(rt, s)]
        assert not missing, f"Missing symbols in core.runtime: {missing}"

    def test_AX2_import_directly_from_policy_module(self):
        """Verify all symbols are importable from the policy module directly."""
        from core.delegated_target_selection_policy import (  # noqa: F401
            DELEGATED_TARGET_SELECTION_POLICY_AUTHORITY,
            DELEGATED_TARGET_SELECTION_POLICY_PR20_SENTINEL,
            DEGRADATION_SCORE_THRESHOLD,
            SelectionOutcome,
            CandidateRejectionReason,
            SelectionCandidateContext,
            CandidateEvaluation,
            SelectionDecision,
            evaluate_candidate,
            rank_candidates,
            select_delegated_target,
            build_selection_explanation,
        )
        # No assertion needed: import success is the test


# ---------------------------------------------------------------------------
# AY — projection.py sentinel
# ---------------------------------------------------------------------------


class TestProjectionSentinel:
    def test_AY1_sentinel_present_and_not_unavailable(self):
        try:
            from core.routes.projection import (
                DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20,
            )
        except ImportError:
            pytest.skip("projection module not importable in this environment")

        assert isinstance(DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20, str)
        assert "UNAVAILABLE" not in DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20
        assert "PR20" in DELEGATED_TARGET_SELECTION_POLICY_ALIGNED_PR20


# ---------------------------------------------------------------------------
# AZ — Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_AZ1_degradation_score_threshold_is_positive_int(self):
        assert isinstance(DEGRADATION_SCORE_THRESHOLD, int)
        assert DEGRADATION_SCORE_THRESHOLD > 0

    def test_AZ2_base_candidate_score_100(self):
        assert BASE_CANDIDATE_SCORE == 100

    def test_AZ3_reuse_valid_bonus_30(self):
        assert REUSE_VALID_BONUS == 30

    def test_AZ4_failure_penalty_per_unit_10(self):
        assert FAILURE_COUNT_PENALTY_PER_UNIT == 10

    def test_AZ5_failure_max_penalty_50(self):
        assert FAILURE_COUNT_MAX_PENALTY == 50

    def test_AZ6_detach_penalty_per_unit_10(self):
        assert DETACH_COUNT_PENALTY_PER_UNIT == 10

    def test_AZ7_detach_max_penalty_30(self):
        assert DETACH_COUNT_MAX_PENALTY == 30

    def test_AZ8_load_penalty_per_10_executions_5(self):
        assert LOAD_PENALTY_PER_10_EXECUTIONS == 5

    def test_AZ9_load_max_penalty_20(self):
        assert LOAD_MAX_PENALTY == 20

    def test_AZ10_degradation_threshold_below_base_score(self):
        assert DEGRADATION_SCORE_THRESHOLD < BASE_CANDIDATE_SCORE
