#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr11_v2_delegated_flow_post_graduation_governance.py
===============================================================
PR-11V2 — Delegated Flow Post-Graduation Governance / Enforcement Layer
— test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-11V2 sentinel present and
    non-empty.
B.  All eight policy sentinels are non-empty strings with expected keywords.
C.  GovernanceDimension enum has the five required dimension values.
D.  GovernanceDimension.from_string() handles valid, invalid, and non-string.
E.  GovernanceDimension.all_dimensions() returns exactly five dimensions in order.
F.  DimensionGovernanceStatus enum has compliant / violation / unknown values.
G.  DimensionGovernanceStatus.from_string() handles valid, invalid, non-string.
H.  GovernanceVerdict enum has the six required verdict values.
I.  GovernanceVerdict.from_string() handles valid, invalid, non-string.
J.  GovernanceVerdict.is_compliant is True only for governance_compliant.
K.  GovernanceVerdict.is_violation is True for all governance_violation_* values.
L.  GovernanceVerdict.is_unknown is True for missing_monitoring_signal verdict.
M.  DimensionGovernanceResult constructs with required fields.
N.  DimensionGovernanceResult.to_dict() returns JSON-serialisable dict with expected keys.
O.  DimensionGovernanceResult.to_json() produces valid JSON.
P.  DimensionGovernanceResult.from_dict() round-trips correctly.
Q.  DelegatedFlowGovernanceReport constructs with required fields.
R.  DelegatedFlowGovernanceReport.to_dict() returns JSON-serialisable dict.
S.  DelegatedFlowGovernanceReport.to_json() produces valid JSON.
T.  DelegatedFlowGovernanceReport.from_dict() round-trips correctly.
U.  DelegatedFlowGovernanceReport.get_dimension() returns correct result.
V.  get_governance_evaluator() returns DelegatedFlowGovernanceEvaluator singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_governance_evaluator() resets the singleton.
Y.  DelegatedFlowGovernanceEvaluator.evaluate() returns DelegatedFlowGovernanceReport.
Z.  evaluate() verdict is unknown when sub-systems have no history.
AA. evaluate() report has all five governance dimension keys (when baseline is available).
AB. evaluate() report dimensions are all DimensionGovernanceResult instances.
AC. evaluate() report is JSON-serialisable end-to-end.
AD. evaluate() report.is_compliant == report.verdict.is_compliant.
AE. evaluate() report.summary is non-empty.
AF. evaluate_delegated_flow_governance() convenience wrapper returns report.
AG. _compute_verdict: any unknown dimension → unknown verdict.
AH. _compute_verdict: truth_alignment violation → truth_regression verdict.
AI. _compute_verdict: result_convergence violation → result_regression verdict.
AJ. _compute_verdict: operator_visibility violation → operator_visibility_regression verdict.
AK. _compute_verdict: compat_bypass violation → compat_bypass verdict.
AL. _compute_verdict: continuity_replay violation → truth_regression verdict (truth-adjacent).
AM. _compute_verdict: all compliant → governance_compliant verdict.
AN. _collect_violations returns entries for violation and unknown dimensions only.
AO. _build_summary contains 'GOVERNANCE COMPLIANT' when verdict is compliant.
AP. _build_summary contains 'GOVERNANCE NON-COMPLIANT' and verdict value when violated.
AQ. DelegatedFlowGovernanceReport.violations list populated from evaluate().
AR. DimensionGovernanceResult with status=compliant has empty violation_description.
AS. All public names are in __all__.
AT. Policy sentinel count is at least 8.
AU. acceptance_report_id field present on DelegatedFlowGovernanceReport.
AV. DelegatedFlowGovernanceReport.to_dict() includes acceptance_report_id.
"""

from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.delegated_flow_post_graduation_governance as _gov_mod
from core.delegated_flow_post_graduation_governance import (
    DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY,
    DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL,
    GOVERNANCE_EVALUATOR_IS_UNIFIED_COMPLIANCE_ENTRY_POINT_POLICY,
    GOVERNANCE_EVALUATOR_IS_PROJECTION_ONLY_POLICY,
    GOVERNANCE_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
    GOVERNANCE_VIOLATION_MUST_BE_OPERATOR_VISIBLE_POLICY,
    GOVERNANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
    ALL_FIVE_DIMENSIONS_REQUIRED_FOR_COMPLIANCE_POLICY,
    ACCEPTANCE_GRADUATION_IS_PREREQUISITE_FOR_GOVERNANCE_POLICY,
    GOVERNANCE_VERDICT_FEEDS_ENFORCEMENT_AND_RELEASE_TIGHTENING_POLICY,
    GovernanceDimension,
    DimensionGovernanceStatus,
    GovernanceVerdict,
    DimensionGovernanceResult,
    DelegatedFlowGovernanceReport,
    DelegatedFlowGovernanceEvaluator,
    evaluate_delegated_flow_governance,
    get_governance_evaluator,
    reset_governance_evaluator,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_evaluator():
    """Reset the governance evaluator singleton before and after each test."""
    reset_governance_evaluator()
    yield
    reset_governance_evaluator()


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.delegated_flow_post_graduation_governance  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY
        assert isinstance(
            DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY, str
        )

    def test_authority_sentinel_contains_pr11v2(self):
        assert "PR11V2" in DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_AUTHORITY

    def test_pr11v2_sentinel_non_empty(self):
        assert DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL
        assert isinstance(
            DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL, str
        )

    def test_pr11v2_sentinel_contains_pr11v2(self):
        assert (
            "PR11V2"
            in DELEGATED_FLOW_POST_GRADUATION_GOVERNANCE_PR11V2_SENTINEL
        )


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _POLICY_SENTINELS = [
        GOVERNANCE_EVALUATOR_IS_UNIFIED_COMPLIANCE_ENTRY_POINT_POLICY,
        GOVERNANCE_EVALUATOR_IS_PROJECTION_ONLY_POLICY,
        GOVERNANCE_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
        GOVERNANCE_VIOLATION_MUST_BE_OPERATOR_VISIBLE_POLICY,
        GOVERNANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
        ALL_FIVE_DIMENSIONS_REQUIRED_FOR_COMPLIANCE_POLICY,
        ACCEPTANCE_GRADUATION_IS_PREREQUISITE_FOR_GOVERNANCE_POLICY,
        GOVERNANCE_VERDICT_FEEDS_ENFORCEMENT_AND_RELEASE_TIGHTENING_POLICY,
    ]

    def test_all_sentinels_are_non_empty_strings(self):
        for s in self._POLICY_SENTINELS:
            assert isinstance(s, str) and s, f"Sentinel is empty: {s!r}"

    def test_sentinels_contain_policy_keyword(self):
        for s in self._POLICY_SENTINELS:
            assert "POLICY" in s, f"Expected POLICY keyword in: {s!r}"

    def test_sentinel_count_at_least_eight(self):
        assert len(self._POLICY_SENTINELS) >= 8


# ===========================================================================
# C. GovernanceDimension enum
# ===========================================================================


class TestGovernanceDimension:
    def test_has_five_values(self):
        values = [d.value for d in GovernanceDimension]
        assert len(values) == 5

    def test_required_dimension_values_present(self):
        required = {
            "truth_alignment",
            "result_convergence",
            "operator_visibility",
            "compat_bypass",
            "continuity_replay",
        }
        actual = {d.value for d in GovernanceDimension}
        assert required == actual

    def test_is_string_enum(self):
        for d in GovernanceDimension:
            assert isinstance(d, str)


# ===========================================================================
# D. GovernanceDimension.from_string()
# ===========================================================================


class TestGovernanceDimensionFromString:
    def test_valid_values_return_correct_member(self):
        for d in GovernanceDimension:
            assert GovernanceDimension.from_string(d.value) == d

    def test_invalid_string_returns_default(self):
        result = GovernanceDimension.from_string("nonexistent_dimension")
        assert isinstance(result, GovernanceDimension)

    def test_non_string_returns_default(self):
        result = GovernanceDimension.from_string(None)  # type: ignore[arg-type]
        assert isinstance(result, GovernanceDimension)

    def test_empty_string_returns_default(self):
        result = GovernanceDimension.from_string("")
        assert isinstance(result, GovernanceDimension)


# ===========================================================================
# E. GovernanceDimension.all_dimensions()
# ===========================================================================


class TestGovernanceDimensionAllDimensions:
    def test_returns_five_dimensions(self):
        dims = GovernanceDimension.all_dimensions()
        assert len(dims) == 5

    def test_returns_all_enum_members(self):
        dims = GovernanceDimension.all_dimensions()
        assert set(dims) == set(GovernanceDimension)

    def test_canonical_order(self):
        dims = GovernanceDimension.all_dimensions()
        assert dims[0] == GovernanceDimension.truth_alignment
        assert dims[1] == GovernanceDimension.result_convergence
        assert dims[2] == GovernanceDimension.operator_visibility
        assert dims[3] == GovernanceDimension.compat_bypass
        assert dims[4] == GovernanceDimension.continuity_replay


# ===========================================================================
# F. DimensionGovernanceStatus enum
# ===========================================================================


class TestDimensionGovernanceStatus:
    def test_has_three_values(self):
        assert len(list(DimensionGovernanceStatus)) == 3

    def test_required_values_present(self):
        values = {s.value for s in DimensionGovernanceStatus}
        assert "compliant" in values
        assert "violation" in values
        assert "unknown" in values

    def test_is_string_enum(self):
        for s in DimensionGovernanceStatus:
            assert isinstance(s, str)


# ===========================================================================
# G. DimensionGovernanceStatus.from_string()
# ===========================================================================


class TestDimensionGovernanceStatusFromString:
    def test_valid_values_return_correct_member(self):
        for s in DimensionGovernanceStatus:
            assert DimensionGovernanceStatus.from_string(s.value) == s

    def test_invalid_returns_unknown(self):
        result = DimensionGovernanceStatus.from_string("bogus")
        assert result == DimensionGovernanceStatus.unknown

    def test_non_string_returns_unknown(self):
        result = DimensionGovernanceStatus.from_string(42)  # type: ignore[arg-type]
        assert result == DimensionGovernanceStatus.unknown


# ===========================================================================
# H. GovernanceVerdict enum
# ===========================================================================


class TestGovernanceVerdict:
    def test_has_six_values(self):
        assert len(list(GovernanceVerdict)) == 6

    def test_required_verdict_values_present(self):
        values = {v.value for v in GovernanceVerdict}
        assert "governance_compliant" in values
        assert "governance_violation_due_to_truth_regression" in values
        assert "governance_violation_due_to_result_regression" in values
        assert (
            "governance_violation_due_to_operator_visibility_regression" in values
        )
        assert "governance_violation_due_to_compat_bypass" in values
        assert "governance_unknown_due_to_missing_monitoring_signal" in values

    def test_is_string_enum(self):
        for v in GovernanceVerdict:
            assert isinstance(v, str)


# ===========================================================================
# I. GovernanceVerdict.from_string()
# ===========================================================================


class TestGovernanceVerdictFromString:
    def test_valid_values_return_correct_member(self):
        for v in GovernanceVerdict:
            assert GovernanceVerdict.from_string(v.value) == v

    def test_invalid_returns_unknown(self):
        result = GovernanceVerdict.from_string("not_a_verdict")
        assert result == GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal

    def test_non_string_returns_unknown(self):
        result = GovernanceVerdict.from_string(None)  # type: ignore[arg-type]
        assert result == GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal


# ===========================================================================
# J. GovernanceVerdict.is_compliant
# ===========================================================================


class TestGovernanceVerdictIsCompliant:
    def test_true_only_for_governance_compliant(self):
        assert GovernanceVerdict.governance_compliant.is_compliant is True

    def test_false_for_all_violation_verdicts(self):
        for v in GovernanceVerdict:
            if v != GovernanceVerdict.governance_compliant:
                assert v.is_compliant is False, f"Expected False for {v}"


# ===========================================================================
# K. GovernanceVerdict.is_violation
# ===========================================================================


class TestGovernanceVerdictIsViolation:
    def test_true_for_all_violation_verdicts(self):
        violation_verdicts = [
            GovernanceVerdict.governance_violation_due_to_truth_regression,
            GovernanceVerdict.governance_violation_due_to_result_regression,
            GovernanceVerdict.governance_violation_due_to_operator_visibility_regression,
            GovernanceVerdict.governance_violation_due_to_compat_bypass,
        ]
        for v in violation_verdicts:
            assert v.is_violation is True, f"Expected True for {v}"

    def test_false_for_compliant(self):
        assert GovernanceVerdict.governance_compliant.is_violation is False

    def test_false_for_unknown(self):
        assert (
            GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal.is_violation
            is False
        )


# ===========================================================================
# L. GovernanceVerdict.is_unknown
# ===========================================================================


class TestGovernanceVerdictIsUnknown:
    def test_true_only_for_missing_monitoring_signal(self):
        assert (
            GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal.is_unknown
            is True
        )

    def test_false_for_compliant(self):
        assert GovernanceVerdict.governance_compliant.is_unknown is False

    def test_false_for_violation_verdicts(self):
        for v in GovernanceVerdict:
            if v != GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal:
                assert v.is_unknown is False, f"Expected False for {v}"


# ===========================================================================
# M. DimensionGovernanceResult construction
# ===========================================================================


class TestDimensionGovernanceResultConstruction:
    def test_default_construction(self):
        r = DimensionGovernanceResult()
        assert isinstance(r.dimension, GovernanceDimension)
        assert isinstance(r.status, DimensionGovernanceStatus)
        assert isinstance(r.violation_description, str)
        assert isinstance(r.evidence, dict)
        assert isinstance(r.signal_source, str)

    def test_explicit_construction(self):
        r = DimensionGovernanceResult(
            dimension=GovernanceDimension.compat_bypass,
            status=DimensionGovernanceStatus.violation,
            violation_description="compat bypass detected",
            evidence={"key": "val"},
            signal_source="test.source",
        )
        assert r.dimension == GovernanceDimension.compat_bypass
        assert r.status == DimensionGovernanceStatus.violation
        assert r.violation_description == "compat bypass detected"
        assert r.evidence == {"key": "val"}
        assert r.signal_source == "test.source"


# ===========================================================================
# N. DimensionGovernanceResult.to_dict()
# ===========================================================================


class TestDimensionGovernanceResultToDict:
    def test_returns_dict(self):
        r = DimensionGovernanceResult(
            dimension=GovernanceDimension.truth_alignment,
            status=DimensionGovernanceStatus.compliant,
        )
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_expected_keys_present(self):
        r = DimensionGovernanceResult()
        d = r.to_dict()
        for key in ("dimension", "status", "violation_description", "evidence", "signal_source"):
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        r = DimensionGovernanceResult(
            dimension=GovernanceDimension.result_convergence,
            status=DimensionGovernanceStatus.unknown,
            evidence={"foo": 1},
        )
        json.dumps(r.to_dict())  # must not raise


# ===========================================================================
# O. DimensionGovernanceResult.to_json()
# ===========================================================================


class TestDimensionGovernanceResultToJson:
    def test_produces_valid_json(self):
        r = DimensionGovernanceResult()
        parsed = json.loads(r.to_json())
        assert isinstance(parsed, dict)

    def test_json_matches_to_dict(self):
        r = DimensionGovernanceResult(
            dimension=GovernanceDimension.continuity_replay,
            status=DimensionGovernanceStatus.compliant,
        )
        assert json.loads(r.to_json()) == r.to_dict()


# ===========================================================================
# P. DimensionGovernanceResult.from_dict() round-trip
# ===========================================================================


class TestDimensionGovernanceResultFromDict:
    def test_round_trip(self):
        original = DimensionGovernanceResult(
            dimension=GovernanceDimension.operator_visibility,
            status=DimensionGovernanceStatus.violation,
            violation_description="visibility gap",
            evidence={"k": "v"},
            signal_source="src.module",
        )
        recovered = DimensionGovernanceResult.from_dict(original.to_dict())
        assert recovered.dimension == original.dimension
        assert recovered.status == original.status
        assert recovered.violation_description == original.violation_description
        assert recovered.evidence == original.evidence
        assert recovered.signal_source == original.signal_source

    def test_empty_dict_does_not_raise(self):
        r = DimensionGovernanceResult.from_dict({})
        assert isinstance(r, DimensionGovernanceResult)


# ===========================================================================
# Q. DelegatedFlowGovernanceReport construction
# ===========================================================================


class TestDelegatedFlowGovernanceReportConstruction:
    def test_default_construction(self):
        rpt = DelegatedFlowGovernanceReport()
        assert isinstance(rpt.report_id, str) and rpt.report_id
        assert isinstance(rpt.verdict, GovernanceVerdict)
        assert isinstance(rpt.dimensions, dict)
        assert isinstance(rpt.summary, str)
        assert isinstance(rpt.violations, list)
        assert isinstance(rpt.is_compliant, bool)
        assert isinstance(rpt.evaluator_version, str)
        assert isinstance(rpt.generated_at, float)
        assert isinstance(rpt.acceptance_report_id, str)

    def test_unique_report_ids(self):
        r1 = DelegatedFlowGovernanceReport()
        r2 = DelegatedFlowGovernanceReport()
        assert r1.report_id != r2.report_id


# ===========================================================================
# R. DelegatedFlowGovernanceReport.to_dict()
# ===========================================================================


class TestDelegatedFlowGovernanceReportToDict:
    def test_returns_dict(self):
        rpt = DelegatedFlowGovernanceReport()
        assert isinstance(rpt.to_dict(), dict)

    def test_expected_keys_present(self):
        rpt = DelegatedFlowGovernanceReport()
        d = rpt.to_dict()
        for key in (
            "report_id",
            "verdict",
            "dimensions",
            "summary",
            "violations",
            "is_compliant",
            "evaluator_version",
            "generated_at",
            "acceptance_report_id",
        ):
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        rpt = DelegatedFlowGovernanceReport()
        json.dumps(rpt.to_dict())


# ===========================================================================
# S. DelegatedFlowGovernanceReport.to_json()
# ===========================================================================


class TestDelegatedFlowGovernanceReportToJson:
    def test_produces_valid_json(self):
        rpt = DelegatedFlowGovernanceReport()
        parsed = json.loads(rpt.to_json())
        assert isinstance(parsed, dict)

    def test_json_matches_to_dict(self):
        rpt = DelegatedFlowGovernanceReport()
        assert json.loads(rpt.to_json()) == rpt.to_dict()


# ===========================================================================
# T. DelegatedFlowGovernanceReport.from_dict() round-trip
# ===========================================================================


class TestDelegatedFlowGovernanceReportFromDict:
    def test_round_trip(self):
        original = DelegatedFlowGovernanceReport(
            verdict=GovernanceVerdict.governance_compliant,
            summary="all good",
            violations=[],
            is_compliant=True,
            acceptance_report_id="abc123",
        )
        recovered = DelegatedFlowGovernanceReport.from_dict(original.to_dict())
        assert recovered.verdict == original.verdict
        assert recovered.summary == original.summary
        assert recovered.violations == original.violations
        assert recovered.is_compliant == original.is_compliant
        assert recovered.acceptance_report_id == original.acceptance_report_id

    def test_empty_dict_does_not_raise(self):
        rpt = DelegatedFlowGovernanceReport.from_dict({})
        assert isinstance(rpt, DelegatedFlowGovernanceReport)


# ===========================================================================
# U. DelegatedFlowGovernanceReport.get_dimension()
# ===========================================================================


class TestDelegatedFlowGovernanceReportGetDimension:
    def test_returns_correct_result(self):
        dim_result = DimensionGovernanceResult(
            dimension=GovernanceDimension.compat_bypass,
            status=DimensionGovernanceStatus.compliant,
        )
        rpt = DelegatedFlowGovernanceReport(
            dimensions={GovernanceDimension.compat_bypass.value: dim_result}
        )
        assert rpt.get_dimension(GovernanceDimension.compat_bypass) is dim_result

    def test_returns_none_for_missing_dimension(self):
        rpt = DelegatedFlowGovernanceReport(dimensions={})
        assert rpt.get_dimension(GovernanceDimension.truth_alignment) is None


# ===========================================================================
# V. get_governance_evaluator() singleton
# ===========================================================================


class TestGetGovernanceEvaluator:
    def test_returns_evaluator_instance(self):
        ev = get_governance_evaluator()
        assert isinstance(ev, DelegatedFlowGovernanceEvaluator)

    def test_singleton_identity(self):
        ev1 = get_governance_evaluator()
        ev2 = get_governance_evaluator()
        assert ev1 is ev2


# ===========================================================================
# X. reset_governance_evaluator()
# ===========================================================================


class TestResetGovernanceEvaluator:
    def test_reset_creates_new_instance(self):
        ev1 = get_governance_evaluator()
        reset_governance_evaluator()
        ev2 = get_governance_evaluator()
        assert ev1 is not ev2


# ===========================================================================
# Y. DelegatedFlowGovernanceEvaluator.evaluate()
# ===========================================================================


class TestEvaluateReturnsReport:
    def test_returns_governance_report(self):
        ev = get_governance_evaluator()
        report = ev.evaluate()
        assert isinstance(report, DelegatedFlowGovernanceReport)


# ===========================================================================
# Z. evaluate() verdict is unknown when no history
# ===========================================================================


class TestEvaluateDefaultVerdict:
    def test_verdict_is_unknown_without_history(self):
        ev = get_governance_evaluator()
        report = ev.evaluate()
        # Without real sub-system state the evaluator must fail-conservative.
        assert isinstance(report.verdict, GovernanceVerdict)
        # The verdict must not be arbitrarily "compliant" without evidence.
        assert report.verdict in (
            GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal,
            GovernanceVerdict.governance_compliant,
            GovernanceVerdict.governance_violation_due_to_truth_regression,
            GovernanceVerdict.governance_violation_due_to_result_regression,
            GovernanceVerdict.governance_violation_due_to_operator_visibility_regression,
            GovernanceVerdict.governance_violation_due_to_compat_bypass,
        )


# ===========================================================================
# AA. evaluate() report has all five dimension keys (or baseline-unknown subset)
# ===========================================================================


class TestEvaluateReportDimensionKeys:
    def test_report_has_at_least_one_dimension(self):
        report = get_governance_evaluator().evaluate()
        assert len(report.dimensions) >= 1

    def test_dimension_values_are_governance_dimension_keys(self):
        valid_keys = {d.value for d in GovernanceDimension}
        report = get_governance_evaluator().evaluate()
        for key in report.dimensions:
            assert key in valid_keys, f"Unexpected dimension key: {key}"


# ===========================================================================
# AB. evaluate() report dimensions are all DimensionGovernanceResult instances
# ===========================================================================


class TestEvaluateReportDimensionInstances:
    def test_all_dimensions_are_result_instances(self):
        report = get_governance_evaluator().evaluate()
        for dim_result in report.dimensions.values():
            assert isinstance(dim_result, DimensionGovernanceResult)


# ===========================================================================
# AC. evaluate() report is JSON-serialisable end-to-end
# ===========================================================================


class TestEvaluateReportJsonSerializable:
    def test_to_json_does_not_raise(self):
        report = get_governance_evaluator().evaluate()
        serialised = report.to_json()
        assert isinstance(serialised, str)
        parsed = json.loads(serialised)
        assert isinstance(parsed, dict)


# ===========================================================================
# AD. evaluate() report.is_compliant == report.verdict.is_compliant
# ===========================================================================


class TestEvaluateIsCompliantConsistency:
    def test_is_compliant_matches_verdict(self):
        report = get_governance_evaluator().evaluate()
        assert report.is_compliant == report.verdict.is_compliant


# ===========================================================================
# AE. evaluate() report.summary is non-empty
# ===========================================================================


class TestEvaluateSummaryNonEmpty:
    def test_summary_is_non_empty_string(self):
        report = get_governance_evaluator().evaluate()
        assert isinstance(report.summary, str)
        assert report.summary


# ===========================================================================
# AF. evaluate_delegated_flow_governance() convenience wrapper
# ===========================================================================


class TestEvaluateConvenienceWrapper:
    def test_returns_governance_report(self):
        report = evaluate_delegated_flow_governance()
        assert isinstance(report, DelegatedFlowGovernanceReport)


# ===========================================================================
# AG–AL. _compute_verdict logic
# ===========================================================================


def _make_dims_all_compliant() -> Dict[str, DimensionGovernanceResult]:
    return {
        dim.value: DimensionGovernanceResult(
            dimension=dim, status=DimensionGovernanceStatus.compliant
        )
        for dim in GovernanceDimension
    }


class TestComputeVerdictLogic:
    def test_unknown_dimension_yields_unknown_verdict(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.result_convergence.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.result_convergence,
                status=DimensionGovernanceStatus.unknown,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_unknown_due_to_missing_monitoring_signal

    def test_truth_violation_yields_truth_regression(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.truth_alignment.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.truth_alignment,
                status=DimensionGovernanceStatus.violation,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_violation_due_to_truth_regression

    def test_result_convergence_violation_yields_result_regression(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.result_convergence.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.result_convergence,
                status=DimensionGovernanceStatus.violation,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_violation_due_to_result_regression

    def test_operator_visibility_violation_yields_visibility_regression(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.operator_visibility.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.operator_visibility,
                status=DimensionGovernanceStatus.violation,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert (
            verdict
            == GovernanceVerdict.governance_violation_due_to_operator_visibility_regression
        )

    def test_compat_bypass_violation_yields_compat_bypass_verdict(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.compat_bypass.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.compat_bypass,
                status=DimensionGovernanceStatus.violation,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_violation_due_to_compat_bypass

    def test_continuity_replay_violation_yields_truth_regression(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.continuity_replay.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.continuity_replay,
                status=DimensionGovernanceStatus.violation,
            )
        )
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_violation_due_to_truth_regression

    def test_all_compliant_yields_governance_compliant(self):
        dims = _make_dims_all_compliant()
        verdict = DelegatedFlowGovernanceEvaluator._compute_verdict(dims)
        assert verdict == GovernanceVerdict.governance_compliant


# ===========================================================================
# AN. _collect_violations returns only non-compliant entries
# ===========================================================================


class TestCollectViolations:
    def test_returns_empty_when_all_compliant(self):
        dims = _make_dims_all_compliant()
        violations = DelegatedFlowGovernanceEvaluator._collect_violations(dims)
        assert violations == []

    def test_returns_entry_for_violation_dimension(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.compat_bypass.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.compat_bypass,
                status=DimensionGovernanceStatus.violation,
                violation_description="bypass found",
            )
        )
        violations = DelegatedFlowGovernanceEvaluator._collect_violations(dims)
        assert len(violations) == 1
        assert violations[0]["dimension"] == GovernanceDimension.compat_bypass.value
        assert violations[0]["violation_description"] == "bypass found"

    def test_returns_entry_for_unknown_dimension(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.result_convergence.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.result_convergence,
                status=DimensionGovernanceStatus.unknown,
                violation_description="signal absent",
            )
        )
        violations = DelegatedFlowGovernanceEvaluator._collect_violations(dims)
        assert len(violations) == 1
        assert violations[0]["status"] == DimensionGovernanceStatus.unknown.value

    def test_does_not_include_compliant_dimensions(self):
        dims = _make_dims_all_compliant()
        dims[GovernanceDimension.truth_alignment.value] = (
            DimensionGovernanceResult(
                dimension=GovernanceDimension.truth_alignment,
                status=DimensionGovernanceStatus.violation,
            )
        )
        violations = DelegatedFlowGovernanceEvaluator._collect_violations(dims)
        dim_names = [v["dimension"] for v in violations]
        assert GovernanceDimension.result_convergence.value not in dim_names
        assert GovernanceDimension.operator_visibility.value not in dim_names


# ===========================================================================
# AO. _build_summary
# ===========================================================================


class TestBuildSummary:
    def test_compliant_summary_contains_governance_compliant(self):
        summary = DelegatedFlowGovernanceEvaluator._build_summary(
            GovernanceVerdict.governance_compliant, []
        )
        assert "GOVERNANCE COMPLIANT" in summary

    def test_violation_summary_contains_governance_non_compliant(self):
        summary = DelegatedFlowGovernanceEvaluator._build_summary(
            GovernanceVerdict.governance_violation_due_to_truth_regression,
            [{"dimension": "truth_alignment", "status": "violation",
              "violation_description": "drift"}],
        )
        assert "GOVERNANCE NON-COMPLIANT" in summary

    def test_violation_summary_contains_verdict_value(self):
        verdict = GovernanceVerdict.governance_violation_due_to_compat_bypass
        summary = DelegatedFlowGovernanceEvaluator._build_summary(verdict, [])
        assert verdict.value in summary


# ===========================================================================
# AQ. DelegatedFlowGovernanceReport.violations populated from evaluate()
# ===========================================================================


class TestEvaluateViolationsPopulated:
    def test_violations_is_list(self):
        report = get_governance_evaluator().evaluate()
        assert isinstance(report.violations, list)


# ===========================================================================
# AR. DimensionGovernanceResult with status=compliant has empty description
# ===========================================================================


class TestCompliantResultHasEmptyDescription:
    def test_compliant_result_empty_violation_description(self):
        r = DimensionGovernanceResult(
            dimension=GovernanceDimension.continuity_replay,
            status=DimensionGovernanceStatus.compliant,
            violation_description="",
        )
        assert r.violation_description == ""


# ===========================================================================
# AS. All public names are in __all__
# ===========================================================================


class TestAllPublicNames:
    def test_all_entries_importable(self):
        for name in _gov_mod.__all__:
            assert hasattr(_gov_mod, name), f"Missing from module: {name}"

    def test_all_contains_key_names(self):
        all_names = set(_gov_mod.__all__)
        assert "GovernanceDimension" in all_names
        assert "DimensionGovernanceStatus" in all_names
        assert "GovernanceVerdict" in all_names
        assert "DimensionGovernanceResult" in all_names
        assert "DelegatedFlowGovernanceReport" in all_names
        assert "DelegatedFlowGovernanceEvaluator" in all_names
        assert "get_governance_evaluator" in all_names
        assert "reset_governance_evaluator" in all_names
        assert "evaluate_delegated_flow_governance" in all_names


# ===========================================================================
# AT. Policy sentinel count at least 8
# ===========================================================================


class TestPolicySentinelCount:
    def test_policy_sentinel_count(self):
        sentinels = [
            v
            for k, v in vars(_gov_mod).items()
            if isinstance(v, str)
            and ("POLICY" in v or "SENTINEL" in v)
            and k.isupper()
        ]
        assert len(sentinels) >= 8


# ===========================================================================
# AU. acceptance_report_id field present on DelegatedFlowGovernanceReport
# ===========================================================================


class TestAcceptanceReportIdField:
    def test_field_exists(self):
        rpt = DelegatedFlowGovernanceReport()
        assert hasattr(rpt, "acceptance_report_id")

    def test_field_is_string(self):
        rpt = DelegatedFlowGovernanceReport()
        assert isinstance(rpt.acceptance_report_id, str)


# ===========================================================================
# AV. to_dict() includes acceptance_report_id
# ===========================================================================


class TestToDict_AcceptanceReportId:
    def test_acceptance_report_id_in_to_dict(self):
        rpt = DelegatedFlowGovernanceReport(acceptance_report_id="test_id_xyz")
        d = rpt.to_dict()
        assert "acceptance_report_id" in d
        assert d["acceptance_report_id"] == "test_id_xyz"
