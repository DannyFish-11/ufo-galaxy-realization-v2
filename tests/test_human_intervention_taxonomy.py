#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_human_intervention_taxonomy.py
==========================================
PR-08: Human Intervention Taxonomy — test suite.

Coverage
--------
A  — Module sentinels are importable, non-empty strings with correct content.
B  — HumanInterventionClass enum has all five expected values.
C  — HumanInterventionClass ordering helpers (rank, is_at_least, flags).
D  — HumanInterventionEvidence: construction, defaults, computed round-trip.
E  — HumanInterventionEvidence: to_dict / from_dict round-trip.
F  — HumanInterventionVerdict: construction and property flags.
G  — HumanInterventionVerdict: to_dict / from_dict round-trip.
H  — Contract: autonomous_closure when only autonomous_evidence_present.
I  — Contract: autonomous_closure requires NO human-action signals.
J  — Contract: operator_action_observed → operator_assisted_closure.
K  — Contract: human_confirmation_observed alone → operator_assisted_closure.
L  — Contract: human_confirmation + system_incomplete → human_confirmed_system_incomplete.
M  — Contract: manual_override_observed → manual_override (highest priority).
N  — Contract: manual_override dominates even when autonomous_evidence also True.
O  — Contract: escalation_triggered + not resolved → escalation_required.
P  — Contract: escalation_triggered + resolved → does NOT yield escalation_required.
Q  — Contract: no evidence → escalation_required (fail-conservative).
R  — Downgrade reason is included for non-autonomous classes.
S  — No downgrade reasons for autonomous_closure.
T  — build_human_intervention_verdict: None evidence uses zero-evidence default.
U  — build_human_intervention_verdict: is_autonomous=True only for autonomous_closure.
V  — build_human_intervention_verdict: is_positive_closure=False for escalation_required.
W  — build_human_intervention_verdict: is_positive_closure=True for closure classes.
X  — Operator-assisted is not reported as autonomous even if system evidence present.
Y  — Human-confirmed-incomplete is not promoted to operator-assisted.
Z  — Manual override is not promoted to human_confirmed_system_incomplete.
AA — Baseline probe (no evidence) → NOT autonomous_closure.
AB — AcceptanceDimensionId.all_dimensions includes human_intervention.
AC — SystemFinalAcceptanceEvaluator includes human_intervention dimension.
AD — SystemFinalAcceptanceEvaluator human_intervention probe: not autonomous with
     zero evidence (must be pending, not unresolved due to misconfiguration).
AE — Full scenario: autonomous closure with explicit evidence.
AF — Full scenario: operator action → operator_assisted_closure.
AG — Full scenario: human confirmation + system incomplete → human_confirmed_system_incomplete.
AH — Full scenario: manual override → manual_override.
AI — Full scenario: open escalation → escalation_required.
AJ — Downgrade: manual_override_observed overrides all other signals.
AK — Downgrade: open escalation overrides human confirmation.
AL — from_string: unknown value → escalation_required (fail-conservative).
AM — classify_autonomy_level is consistent with build_human_intervention_verdict.
"""

from __future__ import annotations

import json

import pytest

# ---------------------------------------------------------------------------
# Availability guard — skip the whole module gracefully if taxonomy not present
# ---------------------------------------------------------------------------

_TAXONOMY_AVAILABLE = False
_ACCEPTANCE_AVAILABLE = False

try:
    from core.human_intervention_taxonomy import (
        HUMAN_INTERVENTION_TAXONOMY_AUTHORITY,
        HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL,
        AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY,
        OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY,
        HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY,
        MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY,
        ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY,
        EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY,
        HumanInterventionClass,
        HumanInterventionEvidence,
        HumanInterventionVerdict,
        build_human_intervention_verdict,
        classify_autonomy_level,
    )
    _TAXONOMY_AVAILABLE = True
except ImportError:
    pass

try:
    from core.system_final_acceptance_verdict import (
        AcceptanceDimensionId,
        SystemFinalAcceptanceEvaluator,
        reset_system_acceptance_evaluator,
    )
    _ACCEPTANCE_AVAILABLE = True
except ImportError:
    pass

_skip_taxonomy = pytest.mark.skipif(
    not _TAXONOMY_AVAILABLE,
    reason="core.human_intervention_taxonomy not available",
)
_skip_acceptance = pytest.mark.skipif(
    not _ACCEPTANCE_AVAILABLE,
    reason="core.system_final_acceptance_verdict not available",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
    operator_action_observed: bool = False,
    manual_override_observed: bool = False,
    human_confirmation_observed: bool = False,
    system_incomplete_without_human: bool = False,
    escalation_triggered: bool = False,
    escalation_resolved: bool = False,
    autonomous_evidence_present: bool = False,
) -> "HumanInterventionEvidence":
    return HumanInterventionEvidence(
        operator_action_observed=operator_action_observed,
        manual_override_observed=manual_override_observed,
        human_confirmation_observed=human_confirmation_observed,
        system_incomplete_without_human=system_incomplete_without_human,
        escalation_triggered=escalation_triggered,
        escalation_resolved=escalation_resolved,
        autonomous_evidence_present=autonomous_evidence_present,
    )


# ===========================================================================
# A — Module sentinels
# ===========================================================================


class TestSentinels:
    @_skip_taxonomy
    def test_A01_authority_sentinel_importable(self):
        assert isinstance(HUMAN_INTERVENTION_TAXONOMY_AUTHORITY, str)
        assert len(HUMAN_INTERVENTION_TAXONOMY_AUTHORITY) > 0
        assert "HUMAN_INTERVENTION_TAXONOMY_AUTHORITY" in HUMAN_INTERVENTION_TAXONOMY_AUTHORITY

    @_skip_taxonomy
    def test_A02_pr08_sentinel_importable(self):
        assert isinstance(HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL, str)
        assert "PR08" in HUMAN_INTERVENTION_TAXONOMY_PR08_SENTINEL

    @_skip_taxonomy
    def test_A03_policy_sentinels_non_empty(self):
        for sentinel in [
            AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY,
            OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY,
            HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY,
            MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY,
            ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY,
            EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY,
        ]:
            assert isinstance(sentinel, str)
            assert len(sentinel) > 20, f"Sentinel too short: {sentinel!r}"

    @_skip_taxonomy
    def test_A04_policy_sentinels_contain_policy_prefix(self):
        for sentinel in [
            AUTONOMOUS_CLOSURE_REQUIRES_NO_HUMAN_ACTION_POLICY,
            OPERATOR_ASSISTED_IS_NOT_AUTONOMOUS_CLOSURE_POLICY,
            HUMAN_CONFIRMATION_DOES_NOT_IMPLY_SYSTEM_COMPLETE_POLICY,
            MANUAL_OVERRIDE_MUST_NOT_BE_OPTIMISTICALLY_RECLASSIFIED_POLICY,
            ESCALATION_REQUIRED_BLOCKS_CLOSURE_VERDICT_POLICY,
            EVIDENCE_ABSENT_DEFAULTS_TO_ESCALATION_REQUIRED_POLICY,
        ]:
            assert sentinel.startswith("POLICY::"), (
                f"Expected POLICY:: prefix: {sentinel!r}"
            )


# ===========================================================================
# B — HumanInterventionClass enum values
# ===========================================================================


class TestHumanInterventionClassEnum:
    @_skip_taxonomy
    def test_B01_all_five_values_present(self):
        values = {c.value for c in HumanInterventionClass}
        assert "autonomous_closure" in values
        assert "operator_assisted_closure" in values
        assert "human_confirmed_system_incomplete" in values
        assert "manual_override" in values
        assert "escalation_required" in values

    @_skip_taxonomy
    def test_B02_exactly_five_values(self):
        assert len(HumanInterventionClass) == 5

    @_skip_taxonomy
    def test_B03_from_string_known_values(self):
        for val in [
            "autonomous_closure",
            "operator_assisted_closure",
            "human_confirmed_system_incomplete",
            "manual_override",
            "escalation_required",
        ]:
            assert HumanInterventionClass.from_string(val).value == val


# ===========================================================================
# C — HumanInterventionClass ordering helpers
# ===========================================================================


class TestHumanInterventionClassOrdering:
    @_skip_taxonomy
    def test_C01_rank_ordering_highest_to_lowest(self):
        # autonomous_closure has highest rank
        assert (
            HumanInterventionClass.autonomous_closure.rank
            > HumanInterventionClass.operator_assisted_closure.rank
        )
        assert (
            HumanInterventionClass.operator_assisted_closure.rank
            > HumanInterventionClass.human_confirmed_system_incomplete.rank
        )
        assert (
            HumanInterventionClass.human_confirmed_system_incomplete.rank
            > HumanInterventionClass.manual_override.rank
        )
        assert (
            HumanInterventionClass.manual_override.rank
            > HumanInterventionClass.escalation_required.rank
        )

    @_skip_taxonomy
    def test_C02_is_at_least_self(self):
        for cls in HumanInterventionClass:
            assert cls.is_at_least(cls), f"{cls.value} should be at_least itself"

    @_skip_taxonomy
    def test_C03_is_autonomous_only_for_autonomous_closure(self):
        assert HumanInterventionClass.autonomous_closure.is_autonomous is True
        for cls in HumanInterventionClass:
            if cls != HumanInterventionClass.autonomous_closure:
                assert cls.is_autonomous is False

    @_skip_taxonomy
    def test_C04_involves_human_action_all_except_autonomous(self):
        assert HumanInterventionClass.autonomous_closure.involves_human_action is False
        for cls in HumanInterventionClass:
            if cls != HumanInterventionClass.autonomous_closure:
                assert cls.involves_human_action is True

    @_skip_taxonomy
    def test_C05_is_positive_closure_false_for_escalation_required(self):
        assert (
            HumanInterventionClass.escalation_required.is_positive_closure is False
        )

    @_skip_taxonomy
    def test_C06_is_positive_closure_true_for_closure_classes(self):
        for cls in HumanInterventionClass:
            if cls != HumanInterventionClass.escalation_required:
                assert cls.is_positive_closure is True, (
                    f"{cls.value} should be positive_closure"
                )


# ===========================================================================
# D — HumanInterventionEvidence defaults
# ===========================================================================


class TestHumanInterventionEvidenceDefaults:
    @_skip_taxonomy
    def test_D01_all_defaults_false(self):
        ev = HumanInterventionEvidence()
        assert ev.operator_action_observed is False
        assert ev.manual_override_observed is False
        assert ev.human_confirmation_observed is False
        assert ev.system_incomplete_without_human is False
        assert ev.escalation_triggered is False
        assert ev.escalation_resolved is False
        assert ev.autonomous_evidence_present is False

    @_skip_taxonomy
    def test_D02_context_defaults_empty_dict(self):
        ev = HumanInterventionEvidence()
        assert isinstance(ev.context, dict)
        assert len(ev.context) == 0

    @_skip_taxonomy
    def test_D03_field_assignment(self):
        ev = _make_evidence(
            operator_action_observed=True,
            autonomous_evidence_present=True,
        )
        assert ev.operator_action_observed is True
        assert ev.autonomous_evidence_present is True
        assert ev.manual_override_observed is False


# ===========================================================================
# E — HumanInterventionEvidence round-trip
# ===========================================================================


class TestHumanInterventionEvidenceRoundTrip:
    @_skip_taxonomy
    def test_E01_to_dict_has_all_fields(self):
        ev = _make_evidence(operator_action_observed=True)
        d = ev.to_dict()
        assert "operator_action_observed" in d
        assert "manual_override_observed" in d
        assert "human_confirmation_observed" in d
        assert "system_incomplete_without_human" in d
        assert "escalation_triggered" in d
        assert "escalation_resolved" in d
        assert "autonomous_evidence_present" in d
        assert "context" in d

    @_skip_taxonomy
    def test_E02_from_dict_round_trip(self):
        ev = _make_evidence(
            manual_override_observed=True,
            escalation_triggered=True,
            escalation_resolved=False,
        )
        d = ev.to_dict()
        ev2 = HumanInterventionEvidence.from_dict(d)
        assert ev2.manual_override_observed is True
        assert ev2.escalation_triggered is True
        assert ev2.escalation_resolved is False

    @_skip_taxonomy
    def test_E03_from_dict_defaults_for_missing_keys(self):
        ev = HumanInterventionEvidence.from_dict({})
        assert ev.operator_action_observed is False
        assert ev.autonomous_evidence_present is False


# ===========================================================================
# F — HumanInterventionVerdict construction
# ===========================================================================


class TestHumanInterventionVerdictConstruction:
    @_skip_taxonomy
    def test_F01_default_class_is_escalation_required(self):
        v = HumanInterventionVerdict()
        assert v.intervention_class == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_F02_verdict_id_is_non_empty_string(self):
        v = HumanInterventionVerdict()
        assert isinstance(v.verdict_id, str)
        assert len(v.verdict_id) > 0

    @_skip_taxonomy
    def test_F03_evaluated_at_is_float(self):
        v = HumanInterventionVerdict()
        assert isinstance(v.evaluated_at, float)
        assert v.evaluated_at > 0


# ===========================================================================
# G — HumanInterventionVerdict round-trip
# ===========================================================================


class TestHumanInterventionVerdictRoundTrip:
    @_skip_taxonomy
    def test_G01_to_dict_has_required_keys(self):
        v = build_human_intervention_verdict()
        d = v.to_dict()
        assert "intervention_class" in d
        assert "is_autonomous" in d
        assert "involves_human_action" in d
        assert "is_positive_closure" in d
        assert "downgrade_reasons" in d
        assert "evidence_summary" in d

    @_skip_taxonomy
    def test_G02_to_json_is_valid_json(self):
        v = build_human_intervention_verdict()
        raw = v.to_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)
        assert "intervention_class" in parsed

    @_skip_taxonomy
    def test_G03_from_dict_round_trip(self):
        ev = _make_evidence(operator_action_observed=True)
        v = build_human_intervention_verdict(ev)
        d = v.to_dict()
        v2 = HumanInterventionVerdict.from_dict(d)
        assert v2.intervention_class == v.intervention_class
        assert v2.is_autonomous == v.is_autonomous


# ===========================================================================
# H–Q — Contract classification rules
# ===========================================================================


class TestContractClassification:
    # H: autonomous_closure when only autonomous_evidence_present
    @_skip_taxonomy
    def test_H01_autonomous_closure_with_only_autonomous_evidence(self):
        ev = _make_evidence(autonomous_evidence_present=True)
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.autonomous_closure

    # I: autonomous_closure requires no human-action signals
    @_skip_taxonomy
    def test_I01_operator_action_prevents_autonomous_closure(self):
        ev = _make_evidence(
            autonomous_evidence_present=True,
            operator_action_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.autonomous_closure

    @_skip_taxonomy
    def test_I02_human_confirmation_prevents_autonomous_closure(self):
        ev = _make_evidence(
            autonomous_evidence_present=True,
            human_confirmation_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.autonomous_closure

    @_skip_taxonomy
    def test_I03_manual_override_prevents_autonomous_closure(self):
        ev = _make_evidence(
            autonomous_evidence_present=True,
            manual_override_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.autonomous_closure

    # J: operator_action_observed → operator_assisted_closure
    @_skip_taxonomy
    def test_J01_operator_action_yields_operator_assisted(self):
        ev = _make_evidence(operator_action_observed=True)
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.operator_assisted_closure

    @_skip_taxonomy
    def test_J02_operator_action_with_autonomous_evidence_yields_operator_assisted(self):
        ev = _make_evidence(
            operator_action_observed=True,
            autonomous_evidence_present=True,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.operator_assisted_closure

    # K: human_confirmation alone → operator_assisted_closure
    @_skip_taxonomy
    def test_K01_human_confirmation_alone_yields_operator_assisted(self):
        ev = _make_evidence(human_confirmation_observed=True)
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.operator_assisted_closure

    # L: human_confirmation + system_incomplete → human_confirmed_system_incomplete
    @_skip_taxonomy
    def test_L01_human_confirmation_plus_system_incomplete_yields_hcsi(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.human_confirmed_system_incomplete

    @_skip_taxonomy
    def test_L02_hcsi_not_promoted_to_operator_assisted(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.operator_assisted_closure

    @_skip_taxonomy
    def test_L03_hcsi_not_promoted_to_autonomous_closure(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
            autonomous_evidence_present=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.autonomous_closure

    # M: manual_override_observed → manual_override (highest priority)
    @_skip_taxonomy
    def test_M01_manual_override_observed_yields_manual_override(self):
        ev = _make_evidence(manual_override_observed=True)
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.manual_override

    @_skip_taxonomy
    def test_M02_manual_override_not_promoted_to_operator_assisted(self):
        ev = _make_evidence(
            manual_override_observed=True,
            operator_action_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.manual_override

    # N: manual_override dominates even when autonomous_evidence also True
    @_skip_taxonomy
    def test_N01_manual_override_dominates_autonomous_evidence(self):
        ev = _make_evidence(
            manual_override_observed=True,
            autonomous_evidence_present=True,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.manual_override

    # O: escalation_triggered + not resolved → escalation_required
    @_skip_taxonomy
    def test_O01_open_escalation_yields_escalation_required(self):
        ev = _make_evidence(
            escalation_triggered=True,
            escalation_resolved=False,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_O02_open_escalation_blocks_even_with_human_confirmation(self):
        ev = _make_evidence(
            escalation_triggered=True,
            escalation_resolved=False,
            human_confirmation_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.escalation_required

    # P: escalation_triggered + resolved → does NOT yield escalation_required
    @_skip_taxonomy
    def test_P01_resolved_escalation_does_not_yield_escalation_required(self):
        ev = _make_evidence(
            escalation_triggered=True,
            escalation_resolved=True,
            human_confirmation_observed=True,
        )
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.escalation_required

    # Q: no evidence → escalation_required
    @_skip_taxonomy
    def test_Q01_no_evidence_yields_escalation_required(self):
        ev = HumanInterventionEvidence()
        result = classify_autonomy_level(ev)
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_Q02_no_evidence_not_autonomous(self):
        ev = HumanInterventionEvidence()
        result = classify_autonomy_level(ev)
        assert result != HumanInterventionClass.autonomous_closure


# ===========================================================================
# R–S — Downgrade reasons
# ===========================================================================


class TestDowngradeReasons:
    @_skip_taxonomy
    def test_R01_downgrade_reason_present_for_manual_override(self):
        ev = _make_evidence(manual_override_observed=True)
        v = build_human_intervention_verdict(ev)
        assert len(v.downgrade_reasons) > 0

    @_skip_taxonomy
    def test_R02_downgrade_reason_present_for_operator_assisted(self):
        ev = _make_evidence(operator_action_observed=True)
        v = build_human_intervention_verdict(ev)
        assert len(v.downgrade_reasons) > 0

    @_skip_taxonomy
    def test_R03_downgrade_reason_present_for_escalation_required(self):
        ev = HumanInterventionEvidence()
        v = build_human_intervention_verdict(ev)
        assert len(v.downgrade_reasons) > 0

    @_skip_taxonomy
    def test_R04_downgrade_reason_present_for_hcsi(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        v = build_human_intervention_verdict(ev)
        assert len(v.downgrade_reasons) > 0

    @_skip_taxonomy
    def test_S01_no_downgrade_reasons_for_autonomous_closure(self):
        ev = _make_evidence(autonomous_evidence_present=True)
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.autonomous_closure
        assert v.downgrade_reasons == []


# ===========================================================================
# T–W — build_human_intervention_verdict helpers
# ===========================================================================


class TestBuildHumanInterventionVerdict:
    @_skip_taxonomy
    def test_T01_none_evidence_yields_escalation_required(self):
        v = build_human_intervention_verdict(None)
        assert v.intervention_class == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_T02_no_args_yields_escalation_required(self):
        v = build_human_intervention_verdict()
        assert v.intervention_class == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_U01_is_autonomous_true_only_for_autonomous_closure(self):
        ev = _make_evidence(autonomous_evidence_present=True)
        v = build_human_intervention_verdict(ev)
        assert v.is_autonomous is True

    @_skip_taxonomy
    def test_U02_is_autonomous_false_for_operator_assisted(self):
        ev = _make_evidence(operator_action_observed=True)
        v = build_human_intervention_verdict(ev)
        assert v.is_autonomous is False

    @_skip_taxonomy
    def test_V01_is_positive_closure_false_for_escalation_required(self):
        v = build_human_intervention_verdict()
        assert v.is_positive_closure is False

    @_skip_taxonomy
    def test_W01_is_positive_closure_true_for_autonomous_closure(self):
        ev = _make_evidence(autonomous_evidence_present=True)
        v = build_human_intervention_verdict(ev)
        assert v.is_positive_closure is True

    @_skip_taxonomy
    def test_W02_is_positive_closure_true_for_operator_assisted(self):
        ev = _make_evidence(operator_action_observed=True)
        v = build_human_intervention_verdict(ev)
        assert v.is_positive_closure is True

    @_skip_taxonomy
    def test_W03_is_positive_closure_true_for_manual_override(self):
        ev = _make_evidence(manual_override_observed=True)
        v = build_human_intervention_verdict(ev)
        assert v.is_positive_closure is True


# ===========================================================================
# X–Z — Key boundary tests
# ===========================================================================


class TestKeyBoundaries:
    @_skip_taxonomy
    def test_X01_operator_assisted_not_autonomous_even_with_autonomous_evidence(self):
        ev = _make_evidence(
            operator_action_observed=True,
            autonomous_evidence_present=True,
        )
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class != HumanInterventionClass.autonomous_closure
        assert v.is_autonomous is False

    @_skip_taxonomy
    def test_Y01_hcsi_not_promoted_to_operator_assisted(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        v = build_human_intervention_verdict(ev)
        assert (
            v.intervention_class
            == HumanInterventionClass.human_confirmed_system_incomplete
        )
        assert v.intervention_class != HumanInterventionClass.operator_assisted_closure

    @_skip_taxonomy
    def test_Z01_manual_override_not_promoted_to_hcsi(self):
        ev = _make_evidence(
            manual_override_observed=True,
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.manual_override
        assert (
            v.intervention_class
            != HumanInterventionClass.human_confirmed_system_incomplete
        )


# ===========================================================================
# AA — Baseline probe
# ===========================================================================


class TestBaselineProbe:
    @_skip_taxonomy
    def test_AA01_zero_evidence_not_autonomous(self):
        ev = HumanInterventionEvidence()
        v = build_human_intervention_verdict(ev)
        assert v.is_autonomous is False
        assert v.intervention_class != HumanInterventionClass.autonomous_closure

    @_skip_taxonomy
    def test_AA02_zero_evidence_is_escalation_required(self):
        ev = HumanInterventionEvidence()
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.escalation_required


# ===========================================================================
# AB–AD — Acceptance dimension integration
# ===========================================================================


class TestAcceptanceDimensionIntegration:
    @_skip_acceptance
    def test_AB01_all_dimensions_includes_human_intervention(self):
        dims = AcceptanceDimensionId.all_dimensions()
        dim_values = [d.value for d in dims]
        assert "human_intervention" in dim_values

    @_skip_acceptance
    def test_AB02_human_intervention_dimension_exists_in_enum(self):
        assert hasattr(AcceptanceDimensionId, "human_intervention")
        assert AcceptanceDimensionId.human_intervention.value == "human_intervention"

    @_skip_acceptance
    def test_AC01_evaluator_includes_human_intervention_dimension(self):
        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        assert "human_intervention" in report.checklist

    @_skip_acceptance
    def test_AD01_human_intervention_probe_not_autonomous_with_zero_evidence(self):
        """Zero-evidence probe must yield pending (not unresolved due to misconfiguration)."""
        reset_system_acceptance_evaluator()
        evaluator = SystemFinalAcceptanceEvaluator()
        report = evaluator.evaluate()
        item = report.checklist.get("human_intervention")
        assert item is not None, "human_intervention dimension missing from checklist"
        # Must not be unresolved due to misconfiguration (that would mean
        # zero-evidence returned autonomous_closure, which violates the policy).
        # It should be pending (module present, contract wired, no live evidence).
        from core.system_final_acceptance_verdict import DimensionStatus
        assert item.status != DimensionStatus.unresolved, (
            "human_intervention dimension is unresolved — this likely means the "
            "zero-evidence probe returned autonomous_closure (contract "
            "misconfiguration) or the module is unavailable.  "
            f"gap_description: {item.gap_description}"
        )


# ===========================================================================
# AE–AI — Full scenario tests
# ===========================================================================


class TestFullScenarios:
    @_skip_taxonomy
    def test_AE01_full_scenario_autonomous_closure(self):
        ev = _make_evidence(autonomous_evidence_present=True)
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.autonomous_closure
        assert v.is_autonomous is True
        assert v.is_positive_closure is True
        assert v.involves_human_action is False
        assert v.downgrade_reasons == []

    @_skip_taxonomy
    def test_AF01_full_scenario_operator_assisted(self):
        ev = _make_evidence(operator_action_observed=True)
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.operator_assisted_closure
        assert v.is_autonomous is False
        assert v.is_positive_closure is True
        assert v.involves_human_action is True

    @_skip_taxonomy
    def test_AG01_full_scenario_human_confirmed_system_incomplete(self):
        ev = _make_evidence(
            human_confirmation_observed=True,
            system_incomplete_without_human=True,
        )
        v = build_human_intervention_verdict(ev)
        assert (
            v.intervention_class
            == HumanInterventionClass.human_confirmed_system_incomplete
        )
        assert v.is_autonomous is False
        assert v.is_positive_closure is True

    @_skip_taxonomy
    def test_AH01_full_scenario_manual_override(self):
        ev = _make_evidence(manual_override_observed=True)
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.manual_override
        assert v.is_autonomous is False
        assert v.is_positive_closure is True

    @_skip_taxonomy
    def test_AI01_full_scenario_open_escalation(self):
        ev = _make_evidence(escalation_triggered=True, escalation_resolved=False)
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.escalation_required
        assert v.is_autonomous is False
        assert v.is_positive_closure is False


# ===========================================================================
# AJ–AK — Downgrade dominance tests
# ===========================================================================


class TestDowngradeDominance:
    @_skip_taxonomy
    def test_AJ01_manual_override_dominates_all_other_signals(self):
        ev = _make_evidence(
            manual_override_observed=True,
            operator_action_observed=True,
            human_confirmation_observed=True,
            autonomous_evidence_present=True,
            escalation_triggered=True,
            escalation_resolved=True,
        )
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.manual_override

    @_skip_taxonomy
    def test_AK01_open_escalation_dominates_human_confirmation(self):
        ev = _make_evidence(
            escalation_triggered=True,
            escalation_resolved=False,
            human_confirmation_observed=True,
            operator_action_observed=True,
        )
        v = build_human_intervention_verdict(ev)
        assert v.intervention_class == HumanInterventionClass.escalation_required


# ===========================================================================
# AL — from_string fail-conservative
# ===========================================================================


class TestFromString:
    @_skip_taxonomy
    def test_AL01_unknown_string_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string("totally_unknown_value")
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_AL02_empty_string_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string("")
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_AL03_non_string_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string(None)  # type: ignore[arg-type]
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_AL04_integer_input_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string(42)  # type: ignore[arg-type]
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_AL05_list_input_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string(["autonomous_closure"])  # type: ignore[arg-type]
        assert result == HumanInterventionClass.escalation_required

    @_skip_taxonomy
    def test_AL06_dict_input_defaults_to_escalation_required(self):
        result = HumanInterventionClass.from_string({"value": "autonomous_closure"})  # type: ignore[arg-type]
        assert result == HumanInterventionClass.escalation_required


# ===========================================================================
# AM — classify_autonomy_level consistency
# ===========================================================================


class TestClassifyConsistency:
    @_skip_taxonomy
    def test_AM01_classify_consistent_with_build_verdict(self):
        """classify_autonomy_level result must match the intervention_class in verdict."""
        test_cases = [
            HumanInterventionEvidence(),
            _make_evidence(autonomous_evidence_present=True),
            _make_evidence(operator_action_observed=True),
            _make_evidence(manual_override_observed=True),
            _make_evidence(
                human_confirmation_observed=True,
                system_incomplete_without_human=True,
            ),
            _make_evidence(escalation_triggered=True, escalation_resolved=False),
        ]
        for ev in test_cases:
            direct = classify_autonomy_level(ev)
            via_verdict = build_human_intervention_verdict(ev).intervention_class
            assert direct == via_verdict, (
                f"classify_autonomy_level={direct.value!r} but "
                f"build_human_intervention_verdict.intervention_class="
                f"{via_verdict.value!r} for evidence={ev.to_dict()}"
            )
