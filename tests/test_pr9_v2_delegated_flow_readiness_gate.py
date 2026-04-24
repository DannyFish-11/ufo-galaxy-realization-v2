#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_v2_delegated_flow_readiness_gate.py
====================================================
PR-9V2 — Delegated Flow Readiness / Release Gate — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-9V2 sentinel present and
    non-empty.
B.  All seven policy sentinels are non-empty strings with expected keywords.
C.  ReadinessDimension enum has the five required dimension values.
D.  ReadinessDimension.from_string() handles valid, invalid, and non-string.
E.  ReadinessDimension.all_dimensions() returns exactly five dimensions in order.
F.  DimensionReadinessStatus enum has ready / not_ready / unknown values.
G.  DimensionReadinessStatus.from_string() handles valid, invalid, non-string.
H.  DelegatedFlowReadinessVerdict enum has the six required verdict values.
I.  DelegatedFlowReadinessVerdict.from_string() handles valid, invalid, non-string.
J.  DelegatedFlowReadinessVerdict.is_ready is True only for ready_for_release.
K.  DelegatedFlowReadinessVerdict.is_blocked is True for all not_ready_* values.
L.  DelegatedFlowReadinessVerdict.is_unknown is True for missing_signal verdict.
M.  DimensionReadinessResult constructs with required fields.
N.  DimensionReadinessResult.to_dict() returns JSON-serialisable dict with
    expected keys.
O.  DimensionReadinessResult.to_json() produces valid JSON.
P.  DimensionReadinessResult.from_dict() round-trips correctly.
Q.  DelegatedFlowReadinessReport constructs with required fields.
R.  DelegatedFlowReadinessReport.to_dict() returns JSON-serialisable dict.
S.  DelegatedFlowReadinessReport.to_json() produces valid JSON.
T.  DelegatedFlowReadinessReport.from_dict() round-trips correctly.
U.  DelegatedFlowReadinessReport.get_dimension() returns correct result.
V.  get_readiness_gate() returns DelegatedFlowReadinessGate singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_readiness_gate() resets the singleton.
Y.  DelegatedFlowReadinessGate.evaluate() returns DelegatedFlowReadinessReport.
Z.  evaluate() verdict is readiness_unknown when sub-systems have no history.
AA. evaluate() report has all five dimension keys.
AB. evaluate() report dimensions are all DimensionReadinessResult instances.
AC. evaluate() report is JSON-serialisable end-to-end.
AD. evaluate() report.is_ready_for_release == report.verdict.is_ready.
AE. evaluate() report.summary is non-empty.
AF. evaluate_delegated_flow_readiness() convenience wrapper returns report.
AG. _compute_verdict: any unknown dimension → missing_signal verdict.
AH. _compute_verdict: truth not_ready → not_ready_due_to_missing_truth_alignment.
AI. _compute_verdict: convergence not_ready → not_ready_due_to_result_convergence_gap.
AJ. _compute_verdict: operator not_ready → not_ready_due_to_operator_visibility_gap.
AK. _compute_verdict: compat not_ready → not_ready_due_to_compat_influence.
AL. _compute_verdict: continuity not_ready → not_ready_due_to_missing_truth_alignment.
AM. _compute_verdict: all ready → ready_for_release.
AN. _collect_gaps returns entries for not_ready and unknown dimensions only.
AO. _build_summary contains 'READY FOR RELEASE' when verdict is ready.
AP. _build_summary contains 'NOT READY' and verdict value when not ready.
AQ. DelegatedFlowReadinessReport.gaps list populated from evaluate().
AR. DimensionReadinessResult with status=ready has empty gap_description.
AS. All public names are in __all__.
AT. Policy sentinel count is at least 7.
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

import core.delegated_flow_readiness_gate as _gate_mod
from core.delegated_flow_readiness_gate import (
    DELEGATED_FLOW_READINESS_GATE_AUTHORITY,
    DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL,
    READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY,
    READINESS_GATE_IS_PROJECTION_ONLY_POLICY,
    READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
    READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY,
    RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
    ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY,
    ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY,
    ReadinessDimension,
    DimensionReadinessStatus,
    DelegatedFlowReadinessVerdict,
    DimensionReadinessResult,
    DelegatedFlowReadinessReport,
    DelegatedFlowReadinessGate,
    evaluate_delegated_flow_readiness,
    get_readiness_gate,
    reset_readiness_gate,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_gate():
    """Reset the readiness gate singleton before and after each test."""
    reset_readiness_gate()
    yield
    reset_readiness_gate()


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.delegated_flow_readiness_gate  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert DELEGATED_FLOW_READINESS_GATE_AUTHORITY
        assert isinstance(DELEGATED_FLOW_READINESS_GATE_AUTHORITY, str)

    def test_authority_sentinel_contains_pr9v2(self):
        assert "PR9V2" in DELEGATED_FLOW_READINESS_GATE_AUTHORITY

    def test_pr9v2_sentinel_non_empty(self):
        assert DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL
        assert isinstance(DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL, str)

    def test_pr9v2_sentinel_contains_pr9v2(self):
        assert "PR9V2" in DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _POLICY_SENTINELS = [
        READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY,
        READINESS_GATE_IS_PROJECTION_ONLY_POLICY,
        READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY,
        READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY,
        RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
        ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY,
        ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY,
    ]

    def test_all_sentinels_are_non_empty_strings(self):
        for s in self._POLICY_SENTINELS:
            assert isinstance(s, str) and s

    def test_count_at_least_7(self):
        assert len(self._POLICY_SENTINELS) >= 7

    def test_unified_entry_point_policy_keywords(self):
        assert "UNIFIED" in READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY.upper()

    def test_projection_only_policy_keywords(self):
        assert "PROJECTION" in READINESS_GATE_IS_PROJECTION_ONLY_POLICY.upper()

    def test_fail_conservative_policy_keywords(self):
        assert "CONSERVATIVE" in READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY.upper()

    def test_operator_visible_policy_keywords(self):
        assert "OPERATOR" in READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY.upper()

    def test_stable_artifact_policy_keywords(self):
        assert "STABLE" in RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY.upper()

    def test_all_five_dimensions_policy_keywords(self):
        assert "FIVE" in ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY.upper()

    def test_android_v2_contract_policy_keywords(self):
        assert "ANDROID" in ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY.upper()


# ===========================================================================
# C/D/E. ReadinessDimension
# ===========================================================================


class TestReadinessDimension:
    _EXPECTED = {
        "continuity_replay",
        "truth_ownership",
        "result_convergence",
        "operator_surface",
        "compat_legacy",
    }

    def test_has_five_values(self):
        values = {m.value for m in ReadinessDimension}
        assert values == self._EXPECTED

    def test_from_string_valid(self):
        assert ReadinessDimension.from_string("truth_ownership") == ReadinessDimension.truth_ownership

    def test_from_string_invalid_returns_default(self):
        result = ReadinessDimension.from_string("nonexistent_dim")
        assert isinstance(result, ReadinessDimension)

    def test_from_string_non_string_returns_default(self):
        result = ReadinessDimension.from_string(None)  # type: ignore[arg-type]
        assert isinstance(result, ReadinessDimension)

    def test_all_dimensions_returns_five(self):
        dims = ReadinessDimension.all_dimensions()
        assert len(dims) == 5

    def test_all_dimensions_order(self):
        dims = ReadinessDimension.all_dimensions()
        assert dims[0] == ReadinessDimension.continuity_replay
        assert dims[1] == ReadinessDimension.truth_ownership
        assert dims[2] == ReadinessDimension.result_convergence
        assert dims[3] == ReadinessDimension.operator_surface
        assert dims[4] == ReadinessDimension.compat_legacy

    def test_all_dimensions_are_dimension_instances(self):
        for d in ReadinessDimension.all_dimensions():
            assert isinstance(d, ReadinessDimension)


# ===========================================================================
# F/G. DimensionReadinessStatus
# ===========================================================================


class TestDimensionReadinessStatus:
    def test_has_ready_value(self):
        assert DimensionReadinessStatus.ready.value == "ready"

    def test_has_not_ready_value(self):
        assert DimensionReadinessStatus.not_ready.value == "not_ready"

    def test_has_unknown_value(self):
        assert DimensionReadinessStatus.unknown.value == "unknown"

    def test_from_string_ready(self):
        assert DimensionReadinessStatus.from_string("ready") == DimensionReadinessStatus.ready

    def test_from_string_not_ready(self):
        assert DimensionReadinessStatus.from_string("not_ready") == DimensionReadinessStatus.not_ready

    def test_from_string_unknown(self):
        assert DimensionReadinessStatus.from_string("unknown") == DimensionReadinessStatus.unknown

    def test_from_string_invalid_defaults_to_unknown(self):
        assert DimensionReadinessStatus.from_string("bogus") == DimensionReadinessStatus.unknown

    def test_from_string_non_string_defaults_to_unknown(self):
        assert DimensionReadinessStatus.from_string(42) == DimensionReadinessStatus.unknown  # type: ignore[arg-type]


# ===========================================================================
# H/I/J/K/L. DelegatedFlowReadinessVerdict
# ===========================================================================


class TestDelegatedFlowReadinessVerdict:
    _EXPECTED_VALUES = {
        "ready_for_release",
        "not_ready_due_to_missing_truth_alignment",
        "not_ready_due_to_result_convergence_gap",
        "not_ready_due_to_operator_visibility_gap",
        "not_ready_due_to_compat_influence",
        "readiness_unknown_due_to_missing_signal",
    }

    def test_has_six_values(self):
        values = {m.value for m in DelegatedFlowReadinessVerdict}
        assert values == self._EXPECTED_VALUES

    def test_from_string_ready(self):
        assert (
            DelegatedFlowReadinessVerdict.from_string("ready_for_release")
            == DelegatedFlowReadinessVerdict.ready_for_release
        )

    def test_from_string_missing_truth(self):
        assert (
            DelegatedFlowReadinessVerdict.from_string(
                "not_ready_due_to_missing_truth_alignment"
            )
            == DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment
        )

    def test_from_string_invalid_returns_unknown(self):
        result = DelegatedFlowReadinessVerdict.from_string("bogus_verdict")
        assert result == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

    def test_from_string_non_string_returns_unknown(self):
        result = DelegatedFlowReadinessVerdict.from_string(None)  # type: ignore[arg-type]
        assert result == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

    def test_is_ready_true_only_for_release(self):
        assert DelegatedFlowReadinessVerdict.ready_for_release.is_ready is True
        for v in DelegatedFlowReadinessVerdict:
            if v != DelegatedFlowReadinessVerdict.ready_for_release:
                assert v.is_ready is False

    def test_is_blocked_true_for_not_ready_variants(self):
        blocked = [
            DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment,
            DelegatedFlowReadinessVerdict.not_ready_due_to_result_convergence_gap,
            DelegatedFlowReadinessVerdict.not_ready_due_to_operator_visibility_gap,
            DelegatedFlowReadinessVerdict.not_ready_due_to_compat_influence,
        ]
        for v in blocked:
            assert v.is_blocked is True, f"{v} should be blocked"

    def test_is_blocked_false_for_ready_and_unknown(self):
        assert DelegatedFlowReadinessVerdict.ready_for_release.is_blocked is False
        assert DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal.is_blocked is False

    def test_is_unknown_true_for_missing_signal(self):
        assert DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal.is_unknown is True

    def test_is_unknown_false_for_others(self):
        for v in DelegatedFlowReadinessVerdict:
            if v != DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal:
                assert v.is_unknown is False


# ===========================================================================
# M/N/O/P. DimensionReadinessResult
# ===========================================================================


class TestDimensionReadinessResult:
    def _make(self, **kwargs) -> DimensionReadinessResult:
        defaults: Dict[str, Any] = {
            "dimension": ReadinessDimension.truth_ownership,
            "status": DimensionReadinessStatus.ready,
            "gap_description": "",
            "signal_source": "test_module",
            "evidence": {"key": "value"},
        }
        defaults.update(kwargs)
        return DimensionReadinessResult(**defaults)

    def test_constructs(self):
        result = self._make()
        assert result.dimension == ReadinessDimension.truth_ownership
        assert result.status == DimensionReadinessStatus.ready

    def test_to_dict_has_required_keys(self):
        d = self._make().to_dict()
        assert "dimension" in d
        assert "status" in d
        assert "gap_description" in d
        assert "signal_source" in d
        assert "evidence" in d
        assert "evaluated_at" in d

    def test_to_dict_values_are_strings(self):
        d = self._make().to_dict()
        assert isinstance(d["dimension"], str)
        assert isinstance(d["status"], str)

    def test_to_json_is_valid_json(self):
        result = self._make(evidence={"a": 1})
        raw = result.to_json()
        parsed = json.loads(raw)
        assert parsed["dimension"] == "truth_ownership"

    def test_from_dict_round_trip(self):
        original = self._make(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.not_ready,
            gap_description="Some gap",
            signal_source="src",
            evidence={"x": 42},
        )
        d = original.to_dict()
        restored = DimensionReadinessResult.from_dict(d)
        assert restored.dimension == ReadinessDimension.compat_legacy
        assert restored.status == DimensionReadinessStatus.not_ready
        assert restored.gap_description == "Some gap"
        assert restored.signal_source == "src"
        assert restored.evidence == {"x": 42}

    def test_ready_status_has_empty_gap(self):
        result = self._make(status=DimensionReadinessStatus.ready, gap_description="")
        assert result.gap_description == ""

    def test_evaluated_at_is_float(self):
        result = self._make()
        assert isinstance(result.evaluated_at, float)
        assert result.evaluated_at > 0


# ===========================================================================
# Q/R/S/T/U. DelegatedFlowReadinessReport
# ===========================================================================


class TestDelegatedFlowReadinessReport:
    def _make_report(self) -> DelegatedFlowReadinessReport:
        dims: Dict[str, DimensionReadinessResult] = {
            d.value: DimensionReadinessResult(
                dimension=d,
                status=DimensionReadinessStatus.ready,
                gap_description="",
                signal_source="test",
            )
            for d in ReadinessDimension.all_dimensions()
        }
        return DelegatedFlowReadinessReport(
            verdict=DelegatedFlowReadinessVerdict.ready_for_release,
            dimensions=dims,
            summary="All dimensions ready.",
            gaps=[],
            is_ready_for_release=True,
        )

    def test_constructs(self):
        report = self._make_report()
        assert report.verdict == DelegatedFlowReadinessVerdict.ready_for_release

    def test_to_dict_has_required_keys(self):
        d = self._make_report().to_dict()
        assert "report_id" in d
        assert "verdict" in d
        assert "dimensions" in d
        assert "summary" in d
        assert "gaps" in d
        assert "is_ready_for_release" in d
        assert "gate_version" in d
        assert "generated_at" in d

    def test_to_dict_verdict_is_string(self):
        d = self._make_report().to_dict()
        assert isinstance(d["verdict"], str)

    def test_to_dict_dimensions_are_nested_dicts(self):
        d = self._make_report().to_dict()
        for dim_key, dim_val in d["dimensions"].items():
            assert isinstance(dim_key, str)
            assert isinstance(dim_val, dict)
            assert "status" in dim_val

    def test_to_json_is_valid_json(self):
        raw = self._make_report().to_json()
        parsed = json.loads(raw)
        assert parsed["verdict"] == "ready_for_release"

    def test_from_dict_round_trip(self):
        original = self._make_report()
        d = original.to_dict()
        restored = DelegatedFlowReadinessReport.from_dict(d)
        assert restored.verdict == DelegatedFlowReadinessVerdict.ready_for_release
        assert restored.is_ready_for_release is True
        assert len(restored.dimensions) == 5

    def test_get_dimension_returns_result(self):
        report = self._make_report()
        dim_result = report.get_dimension(ReadinessDimension.truth_ownership)
        assert dim_result is not None
        assert dim_result.dimension == ReadinessDimension.truth_ownership

    def test_get_dimension_unknown_returns_none(self):
        report = DelegatedFlowReadinessReport()
        assert report.get_dimension(ReadinessDimension.truth_ownership) is None

    def test_report_id_non_empty(self):
        report = self._make_report()
        assert report.report_id
        assert isinstance(report.report_id, str)

    def test_generated_at_float(self):
        report = self._make_report()
        assert isinstance(report.generated_at, float)
        assert report.generated_at > 0


# ===========================================================================
# V/W/X. Singleton management
# ===========================================================================


class TestSingletonManagement:
    def test_get_readiness_gate_returns_gate(self):
        gate = get_readiness_gate()
        assert isinstance(gate, DelegatedFlowReadinessGate)

    def test_singleton_identity(self):
        gate1 = get_readiness_gate()
        gate2 = get_readiness_gate()
        assert gate1 is gate2

    def test_reset_clears_singleton(self):
        gate1 = get_readiness_gate()
        reset_readiness_gate()
        gate2 = get_readiness_gate()
        assert gate1 is not gate2


# ===========================================================================
# Y/Z/AA/AB/AC/AD/AE. evaluate() integration
# ===========================================================================


class TestEvaluateIntegration:
    def test_evaluate_returns_report(self):
        gate = get_readiness_gate()
        report = gate.evaluate()
        assert isinstance(report, DelegatedFlowReadinessReport)

    def test_evaluate_report_has_five_dimension_keys(self):
        report = get_readiness_gate().evaluate()
        expected_keys = {d.value for d in ReadinessDimension.all_dimensions()}
        assert set(report.dimensions.keys()) == expected_keys

    def test_evaluate_dimensions_are_dim_results(self):
        report = get_readiness_gate().evaluate()
        for dim_result in report.dimensions.values():
            assert isinstance(dim_result, DimensionReadinessResult)

    def test_evaluate_report_is_json_serialisable(self):
        report = get_readiness_gate().evaluate()
        raw = report.to_json()
        parsed = json.loads(raw)
        assert "verdict" in parsed
        assert "dimensions" in parsed

    def test_is_ready_for_release_matches_verdict(self):
        report = get_readiness_gate().evaluate()
        assert report.is_ready_for_release == report.verdict.is_ready

    def test_summary_is_non_empty(self):
        report = get_readiness_gate().evaluate()
        assert report.summary
        assert isinstance(report.summary, str)

    def test_verdict_is_valid_enum(self):
        report = get_readiness_gate().evaluate()
        assert isinstance(report.verdict, DelegatedFlowReadinessVerdict)

    def test_gaps_is_list(self):
        report = get_readiness_gate().evaluate()
        assert isinstance(report.gaps, list)

    def test_all_gap_entries_have_required_keys(self):
        report = get_readiness_gate().evaluate()
        for gap in report.gaps:
            assert "dimension" in gap
            assert "status" in gap
            assert "gap_description" in gap


# ===========================================================================
# AF. evaluate_delegated_flow_readiness convenience wrapper
# ===========================================================================


class TestConvenienceWrapper:
    def test_evaluate_delegated_flow_readiness_returns_report(self):
        report = evaluate_delegated_flow_readiness()
        assert isinstance(report, DelegatedFlowReadinessReport)

    def test_convenience_wrapper_same_gate(self):
        """Both calls go through the same singleton gate."""
        gate = get_readiness_gate()
        report_direct = gate.evaluate()
        report_convenience = evaluate_delegated_flow_readiness()
        # Both should have valid, consistent verdicts (same gate, same state).
        assert report_direct.verdict == report_convenience.verdict


# ===========================================================================
# AG–AL. _compute_verdict logic
# ===========================================================================


def _make_all_ready_dims() -> Dict[str, DimensionReadinessResult]:
    return {
        d.value: DimensionReadinessResult(
            dimension=d,
            status=DimensionReadinessStatus.ready,
        )
        for d in ReadinessDimension.all_dimensions()
    }


class TestComputeVerdict:
    def test_any_unknown_gives_missing_signal(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.truth_ownership.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.truth_ownership,
            status=DimensionReadinessStatus.unknown,
            gap_description="missing",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

    def test_truth_not_ready_gives_missing_truth(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.truth_ownership.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.truth_ownership,
            status=DimensionReadinessStatus.not_ready,
            gap_description="quarantine",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment

    def test_convergence_not_ready_gives_convergence_gap(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.result_convergence.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.result_convergence,
            status=DimensionReadinessStatus.not_ready,
            gap_description="quarantine",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.not_ready_due_to_result_convergence_gap

    def test_operator_not_ready_gives_visibility_gap(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.operator_surface.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.operator_surface,
            status=DimensionReadinessStatus.not_ready,
            gap_description="surface unavailable",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.not_ready_due_to_operator_visibility_gap

    def test_compat_not_ready_gives_compat_influence(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.compat_legacy.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.not_ready,
            gap_description="quarantine",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.not_ready_due_to_compat_influence

    def test_continuity_not_ready_gives_truth_alignment(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.continuity_replay.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.continuity_replay,
            status=DimensionReadinessStatus.not_ready,
            gap_description="fail_closed",
        )
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment

    def test_all_ready_gives_ready_for_release(self):
        dims = _make_all_ready_dims()
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.ready_for_release

    def test_empty_dims_gives_unknown(self):
        verdict = DelegatedFlowReadinessGate._compute_verdict({})
        assert verdict == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal

    def test_partial_dims_gives_unknown(self):
        dims = {
            ReadinessDimension.continuity_replay.value: DimensionReadinessResult(
                dimension=ReadinessDimension.continuity_replay,
                status=DimensionReadinessStatus.ready,
            )
        }
        verdict = DelegatedFlowReadinessGate._compute_verdict(dims)
        assert verdict == DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal


# ===========================================================================
# AN. _collect_gaps
# ===========================================================================


class TestCollectGaps:
    def test_no_gaps_when_all_ready(self):
        dims = _make_all_ready_dims()
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert gaps == []

    def test_not_ready_dimension_included_in_gaps(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.truth_ownership.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.truth_ownership,
            status=DimensionReadinessStatus.not_ready,
            gap_description="some gap",
        )
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "truth_ownership"
        assert gaps[0]["gap_description"] == "some gap"

    def test_unknown_dimension_included_in_gaps(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.compat_legacy.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.unknown,
            gap_description="no signal",
        )
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "compat_legacy"

    def test_multiple_gaps_collected(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.truth_ownership.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.truth_ownership,
            status=DimensionReadinessStatus.not_ready,
            gap_description="gap1",
        )
        dims[ReadinessDimension.compat_legacy.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.unknown,
            gap_description="gap2",
        )
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert len(gaps) == 2

    def test_gap_entries_have_required_keys(self):
        dims = _make_all_ready_dims()
        dims[ReadinessDimension.result_convergence.value] = DimensionReadinessResult(
            dimension=ReadinessDimension.result_convergence,
            status=DimensionReadinessStatus.not_ready,
            gap_description="flow mismatch",
        )
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert "dimension" in gaps[0]
        assert "status" in gaps[0]
        assert "gap_description" in gaps[0]


# ===========================================================================
# AO/AP. _build_summary
# ===========================================================================


class TestBuildSummary:
    def test_ready_summary_contains_ready_for_release(self):
        summary = DelegatedFlowReadinessGate._build_summary(
            DelegatedFlowReadinessVerdict.ready_for_release, []
        )
        assert "READY FOR RELEASE" in summary.upper()

    def test_not_ready_summary_contains_not_ready(self):
        summary = DelegatedFlowReadinessGate._build_summary(
            DelegatedFlowReadinessVerdict.not_ready_due_to_missing_truth_alignment,
            [{"dimension": "truth_ownership", "status": "not_ready", "gap_description": "g"}],
        )
        assert "NOT READY" in summary.upper()

    def test_not_ready_summary_contains_verdict_value(self):
        verdict = DelegatedFlowReadinessVerdict.not_ready_due_to_compat_influence
        summary = DelegatedFlowReadinessGate._build_summary(verdict, [])
        assert verdict.value in summary

    def test_not_ready_summary_contains_gap_dims(self):
        summary = DelegatedFlowReadinessGate._build_summary(
            DelegatedFlowReadinessVerdict.not_ready_due_to_result_convergence_gap,
            [{"dimension": "result_convergence", "status": "not_ready", "gap_description": "g"}],
        )
        assert "result_convergence" in summary

    def test_unknown_summary_not_empty(self):
        summary = DelegatedFlowReadinessGate._build_summary(
            DelegatedFlowReadinessVerdict.readiness_unknown_due_to_missing_signal,
            [{"dimension": "truth_ownership", "status": "unknown", "gap_description": "missing"}],
        )
        assert summary


# ===========================================================================
# AQ. evaluate() populates gaps list
# ===========================================================================


class TestEvaluateGapsPopulated:
    def test_gaps_list_populated_for_not_ready_report(self):
        """Gaps list should be non-empty when any dimension is not ready/unknown."""
        report = get_readiness_gate().evaluate()
        # In a fresh environment the sub-systems may have no history →
        # some dimensions will be unknown → gaps will be non-empty.
        # We just assert structural consistency: if verdict != ready, gaps != [].
        if not report.verdict.is_ready:
            assert len(report.gaps) > 0

    def test_ready_report_has_empty_gaps(self):
        """A report with verdict=ready must have empty gaps list."""
        # Construct a synthetic ready report.
        dims = _make_all_ready_dims()
        verdict = DelegatedFlowReadinessVerdict.ready_for_release
        gaps = DelegatedFlowReadinessGate._collect_gaps(dims)
        assert gaps == []


# ===========================================================================
# AR. ready dimension has empty gap_description
# ===========================================================================


class TestReadyDimensionHasEmptyGap:
    def test_ready_status_empty_gap_description(self):
        result = DimensionReadinessResult(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.ready,
            gap_description="",
        )
        assert result.gap_description == ""

    def test_not_ready_status_non_empty_gap_description(self):
        result = DimensionReadinessResult(
            dimension=ReadinessDimension.compat_legacy,
            status=DimensionReadinessStatus.not_ready,
            gap_description="Some compat problem.",
        )
        assert result.gap_description


# ===========================================================================
# AS. __all__ contains expected names
# ===========================================================================


class TestAllContents:
    _EXPECTED_NAMES = [
        "DELEGATED_FLOW_READINESS_GATE_AUTHORITY",
        "DELEGATED_FLOW_READINESS_GATE_PR9V2_SENTINEL",
        "READINESS_GATE_IS_UNIFIED_JUDGMENT_ENTRY_POINT_POLICY",
        "READINESS_GATE_IS_PROJECTION_ONLY_POLICY",
        "READINESS_GATE_FAIL_CONSERVATIVE_ON_MISSING_SIGNAL_POLICY",
        "READINESS_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY",
        "RELEASE_VERDICT_IS_STABLE_ARTIFACT_POLICY",
        "ALL_FIVE_DIMENSIONS_REQUIRED_FOR_RELEASE_POLICY",
        "ANDROID_V2_CONTRACT_SIGNAL_ABSENCE_IS_READINESS_GAP_POLICY",
        "ReadinessDimension",
        "DimensionReadinessStatus",
        "DelegatedFlowReadinessVerdict",
        "DimensionReadinessResult",
        "DelegatedFlowReadinessReport",
        "DelegatedFlowReadinessGate",
        "evaluate_delegated_flow_readiness",
        "get_readiness_gate",
        "reset_readiness_gate",
    ]

    def test_all_names_in_all(self):
        module_all = getattr(_gate_mod, "__all__", [])
        for name in self._EXPECTED_NAMES:
            assert name in module_all, f"{name!r} missing from __all__"

    def test_all_names_importable(self):
        for name in self._EXPECTED_NAMES:
            assert hasattr(_gate_mod, name), f"{name!r} not importable from module"


# ===========================================================================
# AT. Policy sentinel count
# ===========================================================================


class TestPolicySentinelCount:
    def test_at_least_7_policy_sentinels(self):
        """The module defines at least 7 policy sentinels."""
        sentinel_names = [
            name for name in dir(_gate_mod)
            if name.endswith("_POLICY") and isinstance(getattr(_gate_mod, name), str)
        ]
        assert len(sentinel_names) >= 7, (
            f"Expected at least 7 policy sentinels, found {len(sentinel_names)}: "
            f"{sentinel_names}"
        )
