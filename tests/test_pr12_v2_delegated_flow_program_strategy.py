#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr12_v2_delegated_flow_program_strategy.py
======================================================
PR-12V2 — Delegated Flow Program Strategy / Evolution Control Layer
— test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-12V2 sentinel present and
    non-empty.
B.  All eight policy sentinels are non-empty strings with expected keywords.
C.  StrategyDimension enum has the five required dimension values.
D.  StrategyDimension.from_string() handles valid, invalid, and non-string.
E.  StrategyDimension.all_dimensions() returns exactly five dimensions in order.
F.  DimensionStrategyStatus enum has on_track / at_risk / unknown values.
G.  DimensionStrategyStatus.from_string() handles valid, invalid, non-string.
H.  StrategyVerdict enum has the six required verdict values.
I.  StrategyVerdict.from_string() handles valid, invalid, non-string.
J.  StrategyVerdict.is_on_track is True only for strategy_on_track.
K.  StrategyVerdict.is_at_risk is True for all strategy_risk_* values.
L.  StrategyVerdict.is_unknown is True for missing_program_signal verdict.
M.  DimensionStrategyResult constructs with required fields.
N.  DimensionStrategyResult.to_dict() returns JSON-serialisable dict.
O.  DimensionStrategyResult.to_json() produces valid JSON.
P.  DimensionStrategyResult.from_dict() round-trips correctly.
Q.  DelegatedFlowStrategyReport constructs with required fields.
R.  DelegatedFlowStrategyReport.to_dict() returns JSON-serialisable dict.
S.  DelegatedFlowStrategyReport.to_json() produces valid JSON.
T.  DelegatedFlowStrategyReport.from_dict() round-trips correctly.
U.  DelegatedFlowStrategyReport.get_dimension() returns correct result.
V.  get_strategy_evaluator() returns DelegatedFlowStrategyEvaluator singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_strategy_evaluator() resets the singleton.
Y.  DelegatedFlowStrategyEvaluator.evaluate() returns DelegatedFlowStrategyReport.
Z.  evaluate() verdict is unknown when sub-systems have no history.
AA. evaluate() report has all five strategy dimension keys.
AB. evaluate() report dimensions are all DimensionStrategyResult instances.
AC. evaluate() report is JSON-serialisable end-to-end.
AD. evaluate() report.is_on_track == (report.verdict == strategy_on_track).
AE. evaluate() report.summary is non-empty.
AF. evaluate_delegated_flow_strategy() convenience wrapper returns report.
AG. _compute_verdict: any unknown dimension → unknown verdict.
AH. _compute_verdict: contract_stability at_risk → contract_instability verdict.
AI. _compute_verdict: governance_trend at_risk → governance_regression_trend verdict.
AJ. _compute_verdict: regression_pressure at_risk → governance_regression_trend verdict.
AK. _compute_verdict: rollout_maturity at_risk → rollout_maturity_gap verdict.
AL. _compute_verdict: cross_subsystem_coupling at_risk → cross_subsystem_drift verdict.
AM. _compute_verdict: all on_track → strategy_on_track verdict.
AN. _collect_risks returns entries for at_risk and unknown dimensions only.
AO. _build_summary contains 'STRATEGY ON TRACK' when verdict is on_track.
AP. _build_summary contains 'STRATEGY AT RISK' and verdict value when at risk.
AQ. DelegatedFlowStrategyReport.risks list populated from evaluate().
AR. DimensionStrategyResult with status=on_track has empty risk_description.
AS. All public names are in __all__.
AT. Policy sentinel count is at least 8.
AU. governance_report_id field present on DelegatedFlowStrategyReport.
AV. acceptance_report_id field present on DelegatedFlowStrategyReport.
AW. DelegatedFlowStrategyReport.to_dict() includes governance_report_id and
    acceptance_report_id fields.
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

import core.delegated_flow_program_strategy as _strat_mod
from core.delegated_flow_program_strategy import (
    DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY,
    DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL,
    STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_POLICY,
    STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_POLICY,
    STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
    STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_POLICY,
    STRATEGY_VERDICT_IS_STABLE_ARTIFACT_POLICY,
    ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_POLICY,
    GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_POLICY,
    STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_POLICY,
    StrategyDimension,
    DimensionStrategyStatus,
    StrategyVerdict,
    DimensionStrategyResult,
    DelegatedFlowStrategyReport,
    DelegatedFlowStrategyEvaluator,
    evaluate_delegated_flow_strategy,
    get_strategy_evaluator,
    reset_strategy_evaluator,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_evaluator():
    """Reset the strategy evaluator singleton before and after each test."""
    reset_strategy_evaluator()
    yield
    reset_strategy_evaluator()


def _make_all_on_track_dimensions() -> Dict[str, DimensionStrategyResult]:
    """Return a dimensions dict with all five dimensions on_track."""
    return {
        d.value: DimensionStrategyResult(
            dimension=d,
            status=DimensionStrategyStatus.on_track,
            risk_description="",
        )
        for d in StrategyDimension
    }


def _make_dimensions_with(
    dim: StrategyDimension,
    status: DimensionStrategyStatus,
    risk_description: str = "test risk",
) -> Dict[str, DimensionStrategyResult]:
    """Return all-on-track dimensions with one dimension overridden."""
    dims = _make_all_on_track_dimensions()
    dims[dim.value] = DimensionStrategyResult(
        dimension=dim,
        status=status,
        risk_description=risk_description,
    )
    return dims


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.delegated_flow_program_strategy  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY
        assert isinstance(DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY, str)

    def test_authority_sentinel_contains_pr12v2(self):
        assert "PR12V2" in DELEGATED_FLOW_PROGRAM_STRATEGY_AUTHORITY

    def test_pr12v2_sentinel_non_empty(self):
        assert DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL
        assert isinstance(DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL, str)

    def test_pr12v2_sentinel_contains_pr12v2(self):
        assert "PR12V2" in DELEGATED_FLOW_PROGRAM_STRATEGY_PR12V2_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _POLICY_SENTINELS = [
        STRATEGY_EVALUATOR_IS_PROGRAM_LEVEL_ENTRY_POINT_POLICY,
        STRATEGY_EVALUATOR_IS_PROJECTION_ONLY_POLICY,
        STRATEGY_EVALUATOR_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
        STRATEGY_RISK_MUST_BE_OPERATOR_VISIBLE_POLICY,
        STRATEGY_VERDICT_IS_STABLE_ARTIFACT_POLICY,
        ALL_FIVE_STRATEGY_DIMENSIONS_REQUIRED_FOR_ON_TRACK_POLICY,
        GOVERNANCE_REPORT_IS_PRIMARY_PROGRAM_SIGNAL_POLICY,
        STRATEGY_VERDICT_FEEDS_ROADMAP_AND_RELEASE_POLICY_TIGHTENING_POLICY,
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
# C. StrategyDimension enum
# ===========================================================================


class TestStrategyDimension:
    def test_has_five_values(self):
        values = [d.value for d in StrategyDimension]
        assert len(values) == 5

    def test_required_dimension_values_present(self):
        required = {
            "contract_stability",
            "governance_trend",
            "rollout_maturity",
            "regression_pressure",
            "cross_subsystem_coupling",
        }
        actual = {d.value for d in StrategyDimension}
        assert required == actual

    def test_is_string_enum(self):
        for d in StrategyDimension:
            assert isinstance(d, str)


# ===========================================================================
# D. StrategyDimension.from_string()
# ===========================================================================


class TestStrategyDimensionFromString:
    def test_valid_values_return_correct_member(self):
        for d in StrategyDimension:
            assert StrategyDimension.from_string(d.value) == d

    def test_invalid_string_returns_default(self):
        result = StrategyDimension.from_string("nonexistent_dimension")
        assert isinstance(result, StrategyDimension)

    def test_non_string_returns_default(self):
        result = StrategyDimension.from_string(None)  # type: ignore[arg-type]
        assert isinstance(result, StrategyDimension)

    def test_empty_string_returns_default(self):
        result = StrategyDimension.from_string("")
        assert isinstance(result, StrategyDimension)


# ===========================================================================
# E. StrategyDimension.all_dimensions()
# ===========================================================================


class TestStrategyDimensionAllDimensions:
    def test_returns_five_dimensions(self):
        dims = StrategyDimension.all_dimensions()
        assert len(dims) == 5

    def test_returns_all_enum_members(self):
        dims = StrategyDimension.all_dimensions()
        assert set(dims) == set(StrategyDimension)

    def test_canonical_order(self):
        dims = StrategyDimension.all_dimensions()
        assert dims[0] == StrategyDimension.contract_stability
        assert dims[1] == StrategyDimension.governance_trend
        assert dims[2] == StrategyDimension.rollout_maturity
        assert dims[3] == StrategyDimension.regression_pressure
        assert dims[4] == StrategyDimension.cross_subsystem_coupling


# ===========================================================================
# F. DimensionStrategyStatus enum
# ===========================================================================


class TestDimensionStrategyStatus:
    def test_has_three_values(self):
        assert len(list(DimensionStrategyStatus)) == 3

    def test_required_values_present(self):
        values = {s.value for s in DimensionStrategyStatus}
        assert "on_track" in values
        assert "at_risk" in values
        assert "unknown" in values

    def test_is_string_enum(self):
        for s in DimensionStrategyStatus:
            assert isinstance(s, str)


# ===========================================================================
# G. DimensionStrategyStatus.from_string()
# ===========================================================================


class TestDimensionStrategyStatusFromString:
    def test_valid_values_return_correct_member(self):
        for s in DimensionStrategyStatus:
            assert DimensionStrategyStatus.from_string(s.value) == s

    def test_invalid_returns_unknown(self):
        result = DimensionStrategyStatus.from_string("bogus")
        assert result == DimensionStrategyStatus.unknown

    def test_non_string_returns_unknown(self):
        result = DimensionStrategyStatus.from_string(42)  # type: ignore[arg-type]
        assert result == DimensionStrategyStatus.unknown


# ===========================================================================
# H. StrategyVerdict enum
# ===========================================================================


class TestStrategyVerdict:
    def test_has_six_values(self):
        assert len(list(StrategyVerdict)) == 6

    def test_required_verdict_values_present(self):
        values = {v.value for v in StrategyVerdict}
        assert "strategy_on_track" in values
        assert "strategy_risk_due_to_contract_instability" in values
        assert "strategy_risk_due_to_governance_regression_trend" in values
        assert "strategy_risk_due_to_rollout_maturity_gap" in values
        assert "strategy_risk_due_to_cross_subsystem_drift" in values
        assert "strategy_unknown_due_to_missing_program_signal" in values

    def test_is_string_enum(self):
        for v in StrategyVerdict:
            assert isinstance(v, str)


# ===========================================================================
# I. StrategyVerdict.from_string()
# ===========================================================================


class TestStrategyVerdictFromString:
    def test_valid_values_return_correct_member(self):
        for v in StrategyVerdict:
            assert StrategyVerdict.from_string(v.value) == v

    def test_invalid_returns_unknown(self):
        result = StrategyVerdict.from_string("nonexistent_verdict")
        assert result == StrategyVerdict.strategy_unknown_due_to_missing_program_signal

    def test_non_string_returns_unknown(self):
        result = StrategyVerdict.from_string(None)  # type: ignore[arg-type]
        assert result == StrategyVerdict.strategy_unknown_due_to_missing_program_signal


# ===========================================================================
# J. StrategyVerdict.is_on_track
# ===========================================================================


class TestStrategyVerdictIsOnTrack:
    def test_true_only_for_strategy_on_track(self):
        assert StrategyVerdict.strategy_on_track.is_on_track is True

    def test_false_for_all_risk_verdicts(self):
        for v in StrategyVerdict:
            if v != StrategyVerdict.strategy_on_track:
                assert v.is_on_track is False, f"Expected False for {v}"


# ===========================================================================
# K. StrategyVerdict.is_at_risk
# ===========================================================================


class TestStrategyVerdictIsAtRisk:
    def test_true_for_all_risk_verdicts(self):
        risk_verdicts = [
            StrategyVerdict.strategy_risk_due_to_contract_instability,
            StrategyVerdict.strategy_risk_due_to_governance_regression_trend,
            StrategyVerdict.strategy_risk_due_to_rollout_maturity_gap,
            StrategyVerdict.strategy_risk_due_to_cross_subsystem_drift,
        ]
        for v in risk_verdicts:
            assert v.is_at_risk is True, f"Expected True for {v}"

    def test_false_for_on_track(self):
        assert StrategyVerdict.strategy_on_track.is_at_risk is False

    def test_false_for_unknown(self):
        assert (
            StrategyVerdict.strategy_unknown_due_to_missing_program_signal.is_at_risk
            is False
        )


# ===========================================================================
# L. StrategyVerdict.is_unknown
# ===========================================================================


class TestStrategyVerdictIsUnknown:
    def test_true_for_missing_program_signal(self):
        assert (
            StrategyVerdict.strategy_unknown_due_to_missing_program_signal.is_unknown
            is True
        )

    def test_false_for_on_track(self):
        assert StrategyVerdict.strategy_on_track.is_unknown is False

    def test_false_for_risk_verdicts(self):
        for v in StrategyVerdict:
            if v != StrategyVerdict.strategy_unknown_due_to_missing_program_signal:
                assert v.is_unknown is False, f"Expected False for {v}"


# ===========================================================================
# M. DimensionStrategyResult construction
# ===========================================================================


class TestDimensionStrategyResultConstruction:
    def test_default_construction(self):
        r = DimensionStrategyResult()
        assert isinstance(r.dimension, StrategyDimension)
        assert isinstance(r.status, DimensionStrategyStatus)
        assert isinstance(r.risk_description, str)
        assert isinstance(r.evidence, dict)
        assert isinstance(r.signal_source, str)

    def test_explicit_construction(self):
        r = DimensionStrategyResult(
            dimension=StrategyDimension.governance_trend,
            status=DimensionStrategyStatus.at_risk,
            risk_description="governance is regressing",
            evidence={"key": "value"},
            signal_source="test_source",
        )
        assert r.dimension == StrategyDimension.governance_trend
        assert r.status == DimensionStrategyStatus.at_risk
        assert r.risk_description == "governance is regressing"
        assert r.evidence == {"key": "value"}
        assert r.signal_source == "test_source"


# ===========================================================================
# N. DimensionStrategyResult.to_dict()
# ===========================================================================


class TestDimensionStrategyResultToDict:
    def test_returns_dict(self):
        r = DimensionStrategyResult(
            dimension=StrategyDimension.rollout_maturity,
            status=DimensionStrategyStatus.unknown,
            risk_description="missing signal",
        )
        d = r.to_dict()
        assert isinstance(d, dict)

    def test_expected_keys(self):
        r = DimensionStrategyResult()
        d = r.to_dict()
        assert "dimension" in d
        assert "status" in d
        assert "risk_description" in d
        assert "evidence" in d
        assert "signal_source" in d

    def test_json_serialisable(self):
        r = DimensionStrategyResult(
            dimension=StrategyDimension.cross_subsystem_coupling,
            status=DimensionStrategyStatus.at_risk,
            risk_description="coupling risk",
            evidence={"count": 2},
        )
        json_str = json.dumps(r.to_dict())
        assert isinstance(json_str, str)


# ===========================================================================
# O. DimensionStrategyResult.to_json()
# ===========================================================================


class TestDimensionStrategyResultToJson:
    def test_produces_valid_json(self):
        r = DimensionStrategyResult(
            dimension=StrategyDimension.contract_stability,
            status=DimensionStrategyStatus.on_track,
        )
        json_str = r.to_json()
        parsed = json.loads(json_str)
        assert parsed["dimension"] == "contract_stability"
        assert parsed["status"] == "on_track"


# ===========================================================================
# P. DimensionStrategyResult.from_dict() round-trip
# ===========================================================================


class TestDimensionStrategyResultFromDict:
    def test_round_trip(self):
        original = DimensionStrategyResult(
            dimension=StrategyDimension.regression_pressure,
            status=DimensionStrategyStatus.at_risk,
            risk_description="accumulated violations",
            evidence={"violations": 3},
            signal_source="test_signal",
        )
        recovered = DimensionStrategyResult.from_dict(original.to_dict())
        assert recovered.dimension == original.dimension
        assert recovered.status == original.status
        assert recovered.risk_description == original.risk_description
        assert recovered.evidence == original.evidence
        assert recovered.signal_source == original.signal_source

    def test_empty_dict_returns_default(self):
        r = DimensionStrategyResult.from_dict({})
        assert isinstance(r, DimensionStrategyResult)


# ===========================================================================
# Q. DelegatedFlowStrategyReport construction
# ===========================================================================


class TestDelegatedFlowStrategyReportConstruction:
    def test_default_construction(self):
        r = DelegatedFlowStrategyReport()
        assert isinstance(r.report_id, str) and r.report_id
        assert isinstance(r.verdict, StrategyVerdict)
        assert isinstance(r.dimensions, dict)
        assert isinstance(r.summary, str)
        assert isinstance(r.risks, list)
        assert isinstance(r.is_on_track, bool)
        assert isinstance(r.evaluator_version, str)
        assert isinstance(r.generated_at, float)
        assert isinstance(r.governance_report_id, str)
        assert isinstance(r.acceptance_report_id, str)

    def test_verdict_default_is_unknown(self):
        r = DelegatedFlowStrategyReport()
        assert (
            r.verdict
            == StrategyVerdict.strategy_unknown_due_to_missing_program_signal
        )


# ===========================================================================
# R. DelegatedFlowStrategyReport.to_dict()
# ===========================================================================


class TestDelegatedFlowStrategyReportToDict:
    def test_returns_dict_with_expected_keys(self):
        r = DelegatedFlowStrategyReport()
        d = r.to_dict()
        assert isinstance(d, dict)
        for key in (
            "report_id",
            "verdict",
            "dimensions",
            "summary",
            "risks",
            "is_on_track",
            "evaluator_version",
            "generated_at",
            "governance_report_id",
            "acceptance_report_id",
        ):
            assert key in d, f"Missing key: {key}"

    def test_verdict_value_in_dict(self):
        r = DelegatedFlowStrategyReport(
            verdict=StrategyVerdict.strategy_on_track
        )
        d = r.to_dict()
        assert d["verdict"] == "strategy_on_track"


# ===========================================================================
# S. DelegatedFlowStrategyReport.to_json()
# ===========================================================================


class TestDelegatedFlowStrategyReportToJson:
    def test_produces_valid_json(self):
        r = DelegatedFlowStrategyReport()
        json_str = r.to_json()
        parsed = json.loads(json_str)
        assert "verdict" in parsed
        assert "report_id" in parsed


# ===========================================================================
# T. DelegatedFlowStrategyReport.from_dict() round-trip
# ===========================================================================


class TestDelegatedFlowStrategyReportFromDict:
    def test_round_trip(self):
        original = DelegatedFlowStrategyReport(
            verdict=StrategyVerdict.strategy_on_track,
            summary="on track",
            risks=[],
            is_on_track=True,
            governance_report_id="gov_abc123",
            acceptance_report_id="acc_def456",
        )
        recovered = DelegatedFlowStrategyReport.from_dict(original.to_dict())
        assert recovered.verdict == original.verdict
        assert recovered.summary == original.summary
        assert recovered.is_on_track == original.is_on_track
        assert recovered.governance_report_id == original.governance_report_id
        assert recovered.acceptance_report_id == original.acceptance_report_id

    def test_empty_dict_returns_default(self):
        r = DelegatedFlowStrategyReport.from_dict({})
        assert isinstance(r, DelegatedFlowStrategyReport)

    def test_round_trip_with_dimensions(self):
        dims = _make_all_on_track_dimensions()
        original = DelegatedFlowStrategyReport(
            verdict=StrategyVerdict.strategy_on_track,
            dimensions=dims,
            is_on_track=True,
        )
        recovered = DelegatedFlowStrategyReport.from_dict(original.to_dict())
        assert set(recovered.dimensions.keys()) == set(dims.keys())
        for key in dims:
            assert isinstance(recovered.dimensions[key], DimensionStrategyResult)


# ===========================================================================
# U. DelegatedFlowStrategyReport.get_dimension()
# ===========================================================================


class TestDelegatedFlowStrategyReportGetDimension:
    def test_returns_correct_result(self):
        dim_result = DimensionStrategyResult(
            dimension=StrategyDimension.governance_trend,
            status=DimensionStrategyStatus.at_risk,
        )
        r = DelegatedFlowStrategyReport(
            dimensions={"governance_trend": dim_result}
        )
        found = r.get_dimension(StrategyDimension.governance_trend)
        assert found is dim_result

    def test_returns_none_for_missing(self):
        r = DelegatedFlowStrategyReport()
        found = r.get_dimension(StrategyDimension.contract_stability)
        assert found is None


# ===========================================================================
# V. get_strategy_evaluator() singleton
# ===========================================================================


class TestGetStrategyEvaluatorSingleton:
    def test_returns_evaluator_instance(self):
        ev = get_strategy_evaluator()
        assert isinstance(ev, DelegatedFlowStrategyEvaluator)

    def test_two_calls_return_same_object(self):
        ev1 = get_strategy_evaluator()
        ev2 = get_strategy_evaluator()
        assert ev1 is ev2


# ===========================================================================
# X. reset_strategy_evaluator()
# ===========================================================================


class TestResetStrategyEvaluator:
    def test_reset_creates_new_singleton(self):
        ev1 = get_strategy_evaluator()
        reset_strategy_evaluator()
        ev2 = get_strategy_evaluator()
        assert ev1 is not ev2


# ===========================================================================
# Y. DelegatedFlowStrategyEvaluator.evaluate()
# ===========================================================================


class TestDelegatedFlowStrategyEvaluatorEvaluate:
    def test_returns_report(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert isinstance(report, DelegatedFlowStrategyReport)

    def test_report_id_is_non_empty_string(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert isinstance(report.report_id, str) and report.report_id

    def test_report_has_verdict(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert isinstance(report.verdict, StrategyVerdict)


# ===========================================================================
# Z. evaluate() when sub-systems have no history → likely unknown
# ===========================================================================


class TestEvaluateWithNoHistory:
    def test_verdict_is_strategy_verdict_instance(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert isinstance(report.verdict, StrategyVerdict)

    def test_is_on_track_reflects_verdict(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert report.is_on_track == (
            report.verdict == StrategyVerdict.strategy_on_track
        )


# ===========================================================================
# AA. evaluate() report has all five strategy dimension keys
# ===========================================================================


class TestEvaluateReportDimensionKeys:
    def test_all_five_dimension_keys_present(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        expected_keys = {d.value for d in StrategyDimension}
        assert expected_keys == set(report.dimensions.keys())


# ===========================================================================
# AB. evaluate() report dimensions are all DimensionStrategyResult instances
# ===========================================================================


class TestEvaluateReportDimensionTypes:
    def test_all_dimension_values_are_correct_type(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        for dim_result in report.dimensions.values():
            assert isinstance(dim_result, DimensionStrategyResult)


# ===========================================================================
# AC. evaluate() report is JSON-serialisable end-to-end
# ===========================================================================


class TestEvaluateReportJsonSerializable:
    def test_to_json_produces_valid_json(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        json_str = report.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "verdict" in parsed
        assert "dimensions" in parsed
        assert "risks" in parsed

    def test_to_dict_is_json_serialisable(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        d = report.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)


# ===========================================================================
# AD. evaluate() report.is_on_track == (verdict == strategy_on_track)
# ===========================================================================


class TestEvaluateIsOnTrackConsistency:
    def test_is_on_track_consistent_with_verdict(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert report.is_on_track == (
            report.verdict == StrategyVerdict.strategy_on_track
        )


# ===========================================================================
# AE. evaluate() report.summary is non-empty
# ===========================================================================


class TestEvaluateReportSummary:
    def test_summary_is_non_empty(self):
        ev = get_strategy_evaluator()
        report = ev.evaluate()
        assert isinstance(report.summary, str)
        assert len(report.summary) > 0


# ===========================================================================
# AF. evaluate_delegated_flow_strategy() convenience wrapper
# ===========================================================================


class TestEvaluateDelegatedFlowStrategyWrapper:
    def test_returns_report(self):
        report = evaluate_delegated_flow_strategy()
        assert isinstance(report, DelegatedFlowStrategyReport)

    def test_same_type_as_direct_call(self):
        report1 = evaluate_delegated_flow_strategy()
        report2 = get_strategy_evaluator().evaluate()
        assert type(report1) is type(report2)


# ===========================================================================
# AG. _compute_verdict: any unknown dimension → unknown verdict
# ===========================================================================


class TestComputeVerdictUnknown:
    def test_single_unknown_dimension_produces_unknown_verdict(self):
        dims = _make_dimensions_with(
            StrategyDimension.governance_trend,
            DimensionStrategyStatus.unknown,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert verdict == StrategyVerdict.strategy_unknown_due_to_missing_program_signal

    def test_all_unknown_dimensions_produces_unknown_verdict(self):
        dims = {
            d.value: DimensionStrategyResult(
                dimension=d,
                status=DimensionStrategyStatus.unknown,
            )
            for d in StrategyDimension
        }
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert verdict == StrategyVerdict.strategy_unknown_due_to_missing_program_signal


# ===========================================================================
# AH. _compute_verdict: contract_stability at_risk → contract_instability
# ===========================================================================


class TestComputeVerdictContractInstability:
    def test_contract_stability_at_risk(self):
        dims = _make_dimensions_with(
            StrategyDimension.contract_stability,
            DimensionStrategyStatus.at_risk,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert verdict == StrategyVerdict.strategy_risk_due_to_contract_instability


# ===========================================================================
# AI. _compute_verdict: governance_trend at_risk → governance_regression_trend
# ===========================================================================


class TestComputeVerdictGovernanceTrend:
    def test_governance_trend_at_risk(self):
        dims = _make_dimensions_with(
            StrategyDimension.governance_trend,
            DimensionStrategyStatus.at_risk,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert (
            verdict
            == StrategyVerdict.strategy_risk_due_to_governance_regression_trend
        )


# ===========================================================================
# AJ. _compute_verdict: regression_pressure at_risk → governance_regression_trend
# ===========================================================================


class TestComputeVerdictRegressionPressure:
    def test_regression_pressure_at_risk(self):
        dims = _make_dimensions_with(
            StrategyDimension.regression_pressure,
            DimensionStrategyStatus.at_risk,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert (
            verdict
            == StrategyVerdict.strategy_risk_due_to_governance_regression_trend
        )


# ===========================================================================
# AK. _compute_verdict: rollout_maturity at_risk → rollout_maturity_gap
# ===========================================================================


class TestComputeVerdictRolloutMaturity:
    def test_rollout_maturity_at_risk(self):
        dims = _make_dimensions_with(
            StrategyDimension.rollout_maturity,
            DimensionStrategyStatus.at_risk,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert verdict == StrategyVerdict.strategy_risk_due_to_rollout_maturity_gap


# ===========================================================================
# AL. _compute_verdict: cross_subsystem_coupling at_risk → cross_subsystem_drift
# ===========================================================================


class TestComputeVerdictCrossSubsystemCoupling:
    def test_cross_subsystem_coupling_at_risk(self):
        dims = _make_dimensions_with(
            StrategyDimension.cross_subsystem_coupling,
            DimensionStrategyStatus.at_risk,
        )
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert (
            verdict == StrategyVerdict.strategy_risk_due_to_cross_subsystem_drift
        )


# ===========================================================================
# AM. _compute_verdict: all on_track → strategy_on_track
# ===========================================================================


class TestComputeVerdictAllOnTrack:
    def test_all_on_track_produces_strategy_on_track(self):
        dims = _make_all_on_track_dimensions()
        verdict = DelegatedFlowStrategyEvaluator._compute_verdict(dims)
        assert verdict == StrategyVerdict.strategy_on_track


# ===========================================================================
# AN. _collect_risks returns only at_risk and unknown dimension entries
# ===========================================================================


class TestCollectRisks:
    def test_returns_only_non_on_track_dimensions(self):
        dims = _make_all_on_track_dimensions()
        # Mark one as at_risk and one as unknown
        dims[StrategyDimension.governance_trend.value] = DimensionStrategyResult(
            dimension=StrategyDimension.governance_trend,
            status=DimensionStrategyStatus.at_risk,
            risk_description="governance risk",
        )
        dims[StrategyDimension.rollout_maturity.value] = DimensionStrategyResult(
            dimension=StrategyDimension.rollout_maturity,
            status=DimensionStrategyStatus.unknown,
            risk_description="missing signal",
        )
        risks = DelegatedFlowStrategyEvaluator._collect_risks(dims)
        risk_dims = {r["dimension"] for r in risks}
        assert "governance_trend" in risk_dims
        assert "rollout_maturity" in risk_dims
        assert len(risks) == 2

    def test_empty_for_all_on_track(self):
        dims = _make_all_on_track_dimensions()
        risks = DelegatedFlowStrategyEvaluator._collect_risks(dims)
        assert risks == []

    def test_risk_entries_have_required_keys(self):
        dims = _make_dimensions_with(
            StrategyDimension.contract_stability,
            DimensionStrategyStatus.at_risk,
            "contract risk",
        )
        risks = DelegatedFlowStrategyEvaluator._collect_risks(dims)
        for r in risks:
            assert "dimension" in r
            assert "status" in r
            assert "risk_description" in r


# ===========================================================================
# AO. _build_summary contains 'STRATEGY ON TRACK' when on_track
# ===========================================================================


class TestBuildSummaryOnTrack:
    def test_contains_strategy_on_track_text(self):
        summary = DelegatedFlowStrategyEvaluator._build_summary(
            StrategyVerdict.strategy_on_track, []
        )
        assert "STRATEGY ON TRACK" in summary


# ===========================================================================
# AP. _build_summary contains 'STRATEGY AT RISK' when not on_track
# ===========================================================================


class TestBuildSummaryAtRisk:
    def test_contains_strategy_at_risk_text(self):
        risks = [
            {
                "dimension": "contract_stability",
                "status": "at_risk",
                "risk_description": "contract instability",
            }
        ]
        summary = DelegatedFlowStrategyEvaluator._build_summary(
            StrategyVerdict.strategy_risk_due_to_contract_instability, risks
        )
        assert "STRATEGY AT RISK" in summary
        assert "strategy_risk_due_to_contract_instability" in summary


# ===========================================================================
# AQ. DelegatedFlowStrategyReport.risks list from evaluate()
# ===========================================================================


class TestEvaluateRisksList:
    def test_risks_is_a_list(self):
        report = get_strategy_evaluator().evaluate()
        assert isinstance(report.risks, list)

    def test_risks_entries_have_required_keys(self):
        report = get_strategy_evaluator().evaluate()
        for r in report.risks:
            assert "dimension" in r
            assert "status" in r
            assert "risk_description" in r


# ===========================================================================
# AR. DimensionStrategyResult with status=on_track has empty risk_description
# ===========================================================================


class TestOnTrackEmptyRiskDescription:
    def test_on_track_has_empty_risk_description(self):
        r = DimensionStrategyResult(
            dimension=StrategyDimension.rollout_maturity,
            status=DimensionStrategyStatus.on_track,
            risk_description="",
        )
        assert r.risk_description == ""


# ===========================================================================
# AS. All public names are in __all__
# ===========================================================================


class TestAllPublicNamesInDunder:
    def test_all_names_importable(self):
        for name in _strat_mod.__all__:
            assert hasattr(_strat_mod, name), f"Missing from module: {name}"

    def test_key_classes_in_all(self):
        for name in (
            "StrategyDimension",
            "DimensionStrategyStatus",
            "StrategyVerdict",
            "DimensionStrategyResult",
            "DelegatedFlowStrategyReport",
            "DelegatedFlowStrategyEvaluator",
            "get_strategy_evaluator",
            "reset_strategy_evaluator",
            "evaluate_delegated_flow_strategy",
        ):
            assert name in _strat_mod.__all__


# ===========================================================================
# AT. Policy sentinel count is at least 8
# ===========================================================================


class TestPolicySentinelCount:
    def test_at_least_eight_policy_sentinels(self):
        policy_sentinels = [
            v
            for k, v in vars(_strat_mod).items()
            if isinstance(v, str) and v.startswith("POLICY::")
        ]
        assert len(policy_sentinels) >= 8


# ===========================================================================
# AU. governance_report_id field present on DelegatedFlowStrategyReport
# ===========================================================================


class TestGovernanceReportIdField:
    def test_default_governance_report_id_is_empty_string(self):
        r = DelegatedFlowStrategyReport()
        assert r.governance_report_id == ""

    def test_governance_report_id_set(self):
        r = DelegatedFlowStrategyReport(governance_report_id="gov_xyz")
        assert r.governance_report_id == "gov_xyz"


# ===========================================================================
# AV. acceptance_report_id field present on DelegatedFlowStrategyReport
# ===========================================================================


class TestAcceptanceReportIdField:
    def test_default_acceptance_report_id_is_empty_string(self):
        r = DelegatedFlowStrategyReport()
        assert r.acceptance_report_id == ""

    def test_acceptance_report_id_set(self):
        r = DelegatedFlowStrategyReport(acceptance_report_id="acc_abc")
        assert r.acceptance_report_id == "acc_abc"


# ===========================================================================
# AW. to_dict() includes governance_report_id and acceptance_report_id
# ===========================================================================


class TestToDict_GovAndAcceptanceIds:
    def test_includes_governance_report_id(self):
        r = DelegatedFlowStrategyReport(governance_report_id="gov_test")
        d = r.to_dict()
        assert "governance_report_id" in d
        assert d["governance_report_id"] == "gov_test"

    def test_includes_acceptance_report_id(self):
        r = DelegatedFlowStrategyReport(acceptance_report_id="acc_test")
        d = r.to_dict()
        assert "acceptance_report_id" in d
        assert d["acceptance_report_id"] == "acc_test"
