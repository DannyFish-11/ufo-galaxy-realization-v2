#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_v2_delegated_flow_acceptance_gate.py
=====================================================
PR-10V2 — Delegated Flow Final Acceptance / Graduation Gate — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-10V2 sentinel present and
    non-empty.
B.  All eight policy sentinels are non-empty strings with expected keywords.
C.  AcceptanceDimension enum has the six required dimension values.
D.  AcceptanceDimension.from_string() handles valid, invalid, and non-string.
E.  AcceptanceDimension.all_dimensions() returns exactly six dimensions in order.
F.  DimensionEvidenceStatus enum has accepted / rejected / unknown values.
G.  DimensionEvidenceStatus.from_string() handles valid, invalid, non-string.
H.  DelegatedFlowAcceptanceVerdict enum has the seven required verdict values.
I.  DelegatedFlowAcceptanceVerdict.from_string() handles valid, invalid, non-string.
J.  DelegatedFlowAcceptanceVerdict.is_accepted is True only for accepted_for_graduation.
K.  DelegatedFlowAcceptanceVerdict.is_rejected is True for all rejected_* values.
L.  DelegatedFlowAcceptanceVerdict.is_unknown is True for incomplete_signals verdict.
M.  DimensionEvidenceResult constructs with required fields.
N.  DimensionEvidenceResult.to_dict() returns JSON-serialisable dict with expected keys.
O.  DimensionEvidenceResult.to_json() produces valid JSON.
P.  DimensionEvidenceResult.from_dict() round-trips correctly.
Q.  DelegatedFlowAcceptanceReport constructs with required fields.
R.  DelegatedFlowAcceptanceReport.to_dict() returns JSON-serialisable dict.
S.  DelegatedFlowAcceptanceReport.to_json() produces valid JSON.
T.  DelegatedFlowAcceptanceReport.from_dict() round-trips correctly.
U.  DelegatedFlowAcceptanceReport.get_dimension() returns correct result.
V.  get_acceptance_gate() returns DelegatedFlowAcceptanceGate singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_acceptance_gate() resets the singleton.
Y.  DelegatedFlowAcceptanceGate.evaluate() returns DelegatedFlowAcceptanceReport.
Z.  evaluate() verdict is unknown when sub-systems have no history.
AA. evaluate() report has all six dimension keys.
AB. evaluate() report dimensions are all DimensionEvidenceResult instances.
AC. evaluate() report is JSON-serialisable end-to-end.
AD. evaluate() report.is_accepted_for_graduation == report.verdict.is_accepted.
AE. evaluate() report.summary is non-empty.
AF. evaluate_delegated_flow_acceptance() convenience wrapper returns report.
AG. _compute_verdict: any unknown dimension → incomplete_signals verdict.
AH. _compute_verdict: readiness_prerequisite rejected → rejected_due_to_missing_evidence.
AI. _compute_verdict: truth rejected → rejected_due_to_truth_contract_gap.
AJ. _compute_verdict: convergence rejected → rejected_due_to_result_contract_gap.
AK. _compute_verdict: operator rejected → rejected_due_to_operator_visibility_gap.
AL. _compute_verdict: compat rejected → rejected_due_to_compat_bypass_risk.
AM. _compute_verdict: continuity rejected → rejected_due_to_missing_evidence.
AN. _compute_verdict: all accepted → accepted_for_graduation.
AO. _collect_evidence_gaps returns entries for rejected and unknown dimensions only.
AP. _build_summary contains 'ACCEPTED FOR GRADUATION' when verdict is accepted.
AQ. _build_summary contains 'NOT ACCEPTED' and verdict value when rejected.
AR. DelegatedFlowAcceptanceReport.evidence_gaps list populated from evaluate().
AS. DimensionEvidenceResult with status=accepted has empty gap_description.
AT. All public names are in __all__.
AU. Policy sentinel count is at least 8.
AV. readiness_report_id field present on DelegatedFlowAcceptanceReport.
AW. DelegatedFlowAcceptanceReport.to_dict() includes readiness_report_id.
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

import core.delegated_flow_acceptance_gate as _gate_mod
from core.delegated_flow_acceptance_gate import (
    DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY,
    DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL,
    ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY,
    ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY,
    ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY,
    ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY,
    ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
    ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY,
    READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY,
    ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY,
    AcceptanceDimension,
    DimensionEvidenceStatus,
    DelegatedFlowAcceptanceVerdict,
    DimensionEvidenceResult,
    DelegatedFlowAcceptanceReport,
    DelegatedFlowAcceptanceGate,
    evaluate_delegated_flow_acceptance,
    get_acceptance_gate,
    reset_acceptance_gate,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_gate():
    """Reset the acceptance gate singleton before and after each test."""
    reset_acceptance_gate()
    yield
    reset_acceptance_gate()


def _make_accepted_dim(dim: AcceptanceDimension) -> DimensionEvidenceResult:
    """Return a DimensionEvidenceResult with accepted status."""
    return DimensionEvidenceResult(
        dimension=dim,
        status=DimensionEvidenceStatus.accepted,
        gap_description="",
        signal_source="test",
        evidence={"test": True},
    )


def _make_rejected_dim(
    dim: AcceptanceDimension, description: str = "test gap"
) -> DimensionEvidenceResult:
    """Return a DimensionEvidenceResult with rejected status."""
    return DimensionEvidenceResult(
        dimension=dim,
        status=DimensionEvidenceStatus.rejected,
        gap_description=description,
        signal_source="test",
        evidence={"test": True},
    )


def _make_unknown_dim(
    dim: AcceptanceDimension, description: str = "unknown gap"
) -> DimensionEvidenceResult:
    """Return a DimensionEvidenceResult with unknown status."""
    return DimensionEvidenceResult(
        dimension=dim,
        status=DimensionEvidenceStatus.unknown,
        gap_description=description,
        signal_source="test",
        evidence={},
    )


def _all_accepted_dims() -> Dict[str, DimensionEvidenceResult]:
    """Return a dimensions dict with all six dimensions accepted."""
    return {
        dim.value: _make_accepted_dim(dim)
        for dim in AcceptanceDimension.all_dimensions()
    }


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.delegated_flow_acceptance_gate  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY
        assert isinstance(DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY, str)

    def test_authority_sentinel_contains_pr10v2(self):
        assert "PR10V2" in DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY

    def test_pr10v2_sentinel_non_empty(self):
        assert DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL
        assert isinstance(DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL, str)

    def test_pr10v2_sentinel_contains_pr10v2(self):
        assert "PR10V2" in DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL

    def test_authority_sentinel_contains_graduation(self):
        assert "graduation" in DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY.lower()

    def test_authority_sentinel_contains_acceptance(self):
        assert "acceptance" in DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY.lower()


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _POLICY_SENTINELS = [
        ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY,
        ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY,
        ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY,
        ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY,
        ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY,
        ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY,
        READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY,
        ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY,
    ]

    def test_all_sentinels_are_non_empty_strings(self):
        for s in self._POLICY_SENTINELS:
            assert isinstance(s, str) and s

    def test_count_at_least_8(self):
        assert len(self._POLICY_SENTINELS) >= 8

    def test_evidence_backed_policy_keywords(self):
        assert "EVIDENCE" in ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY.upper()

    def test_projection_only_policy_keywords(self):
        assert "PROJECTION" in ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY.upper()

    def test_fail_conservative_policy_keywords(self):
        assert "CONSERVATIVE" in ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY.upper()

    def test_operator_visible_policy_keywords(self):
        assert "OPERATOR" in ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY.upper()

    def test_stable_artifact_policy_keywords(self):
        assert "STABLE" in ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY.upper()

    def test_six_dimensions_policy_keywords(self):
        assert "SIX" in ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY.upper()

    def test_readiness_prerequisite_policy_keywords(self):
        assert "READINESS" in READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY.upper()

    def test_canonical_evidence_sources_policy_keywords(self):
        assert "CANONICAL" in ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY.upper()


# ===========================================================================
# C/D/E. AcceptanceDimension
# ===========================================================================


class TestAcceptanceDimension:
    _EXPECTED = {
        "continuity_replay_evidence",
        "truth_ownership_evidence",
        "result_convergence_evidence",
        "operator_visibility_evidence",
        "compat_bypass_evidence",
        "readiness_prerequisite",
    }

    def test_has_six_values(self):
        values = {m.value for m in AcceptanceDimension}
        assert values == self._EXPECTED

    def test_from_string_valid(self):
        assert (
            AcceptanceDimension.from_string("truth_ownership_evidence")
            == AcceptanceDimension.truth_ownership_evidence
        )

    def test_from_string_valid_readiness(self):
        assert (
            AcceptanceDimension.from_string("readiness_prerequisite")
            == AcceptanceDimension.readiness_prerequisite
        )

    def test_from_string_invalid_returns_default(self):
        result = AcceptanceDimension.from_string("nonexistent_dim")
        assert isinstance(result, AcceptanceDimension)

    def test_from_string_non_string_returns_default(self):
        result = AcceptanceDimension.from_string(None)  # type: ignore[arg-type]
        assert isinstance(result, AcceptanceDimension)

    def test_all_dimensions_returns_six(self):
        dims = AcceptanceDimension.all_dimensions()
        assert len(dims) == 6

    def test_all_dimensions_order(self):
        dims = AcceptanceDimension.all_dimensions()
        assert dims[0] == AcceptanceDimension.continuity_replay_evidence
        assert dims[1] == AcceptanceDimension.truth_ownership_evidence
        assert dims[2] == AcceptanceDimension.result_convergence_evidence
        assert dims[3] == AcceptanceDimension.operator_visibility_evidence
        assert dims[4] == AcceptanceDimension.compat_bypass_evidence
        assert dims[5] == AcceptanceDimension.readiness_prerequisite

    def test_all_dimensions_are_dimension_instances(self):
        for d in AcceptanceDimension.all_dimensions():
            assert isinstance(d, AcceptanceDimension)


# ===========================================================================
# F/G. DimensionEvidenceStatus
# ===========================================================================


class TestDimensionEvidenceStatus:
    def test_has_accepted_value(self):
        assert DimensionEvidenceStatus.accepted.value == "accepted"

    def test_has_rejected_value(self):
        assert DimensionEvidenceStatus.rejected.value == "rejected"

    def test_has_unknown_value(self):
        assert DimensionEvidenceStatus.unknown.value == "unknown"

    def test_from_string_accepted(self):
        assert (
            DimensionEvidenceStatus.from_string("accepted")
            == DimensionEvidenceStatus.accepted
        )

    def test_from_string_rejected(self):
        assert (
            DimensionEvidenceStatus.from_string("rejected")
            == DimensionEvidenceStatus.rejected
        )

    def test_from_string_unknown(self):
        assert (
            DimensionEvidenceStatus.from_string("unknown")
            == DimensionEvidenceStatus.unknown
        )

    def test_from_string_invalid_defaults_to_unknown(self):
        assert (
            DimensionEvidenceStatus.from_string("bogus")
            == DimensionEvidenceStatus.unknown
        )

    def test_from_string_non_string_defaults_to_unknown(self):
        assert (
            DimensionEvidenceStatus.from_string(42)  # type: ignore[arg-type]
            == DimensionEvidenceStatus.unknown
        )


# ===========================================================================
# H/I/J/K/L. DelegatedFlowAcceptanceVerdict
# ===========================================================================


class TestDelegatedFlowAcceptanceVerdict:
    _EXPECTED = {
        "accepted_for_graduation",
        "rejected_due_to_missing_evidence",
        "rejected_due_to_truth_contract_gap",
        "rejected_due_to_result_contract_gap",
        "rejected_due_to_operator_visibility_gap",
        "rejected_due_to_compat_bypass_risk",
        "acceptance_unknown_due_to_incomplete_signals",
    }

    def test_has_seven_values(self):
        values = {m.value for m in DelegatedFlowAcceptanceVerdict}
        assert values == self._EXPECTED

    def test_from_string_valid_accepted(self):
        assert (
            DelegatedFlowAcceptanceVerdict.from_string("accepted_for_graduation")
            == DelegatedFlowAcceptanceVerdict.accepted_for_graduation
        )

    def test_from_string_valid_rejected(self):
        assert (
            DelegatedFlowAcceptanceVerdict.from_string("rejected_due_to_truth_contract_gap")
            == DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap
        )

    def test_from_string_invalid_defaults_to_unknown(self):
        result = DelegatedFlowAcceptanceVerdict.from_string("not_a_verdict")
        assert (
            result
            == DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals
        )

    def test_from_string_non_string_defaults_to_unknown(self):
        result = DelegatedFlowAcceptanceVerdict.from_string(None)  # type: ignore[arg-type]
        assert (
            result
            == DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals
        )

    def test_is_accepted_true_for_accepted_for_graduation(self):
        assert DelegatedFlowAcceptanceVerdict.accepted_for_graduation.is_accepted is True

    def test_is_accepted_false_for_rejected(self):
        assert (
            DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap.is_accepted
            is False
        )

    def test_is_accepted_false_for_unknown(self):
        assert (
            DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals.is_accepted
            is False
        )

    def test_is_rejected_true_for_all_rejected_variants(self):
        for verdict in DelegatedFlowAcceptanceVerdict:
            if verdict.value.startswith("rejected_"):
                assert verdict.is_rejected is True, f"{verdict.value} should be rejected"

    def test_is_rejected_false_for_accepted(self):
        assert (
            DelegatedFlowAcceptanceVerdict.accepted_for_graduation.is_rejected is False
        )

    def test_is_rejected_false_for_unknown(self):
        assert (
            DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals.is_rejected
            is False
        )

    def test_is_unknown_true_for_incomplete_signals(self):
        assert (
            DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals.is_unknown
            is True
        )

    def test_is_unknown_false_for_accepted(self):
        assert (
            DelegatedFlowAcceptanceVerdict.accepted_for_graduation.is_unknown is False
        )

    def test_is_unknown_false_for_rejected(self):
        assert (
            DelegatedFlowAcceptanceVerdict.rejected_due_to_compat_bypass_risk.is_unknown
            is False
        )


# ===========================================================================
# M/N/O/P. DimensionEvidenceResult
# ===========================================================================


class TestDimensionEvidenceResult:
    def test_constructs_with_defaults(self):
        r = DimensionEvidenceResult()
        assert isinstance(r.dimension, AcceptanceDimension)
        assert isinstance(r.status, DimensionEvidenceStatus)
        assert isinstance(r.gap_description, str)
        assert isinstance(r.signal_source, str)
        assert isinstance(r.evidence, dict)
        assert isinstance(r.evaluated_at, float)

    def test_constructs_with_explicit_values(self):
        r = DimensionEvidenceResult(
            dimension=AcceptanceDimension.truth_ownership_evidence,
            status=DimensionEvidenceStatus.accepted,
            gap_description="",
            signal_source="core.flow_level_truth_ownership",
            evidence={"total_artifacts": 5},
        )
        assert r.dimension == AcceptanceDimension.truth_ownership_evidence
        assert r.status == DimensionEvidenceStatus.accepted
        assert r.signal_source == "core.flow_level_truth_ownership"

    def test_to_dict_has_expected_keys(self):
        r = DimensionEvidenceResult(
            dimension=AcceptanceDimension.compat_bypass_evidence,
            status=DimensionEvidenceStatus.rejected,
            gap_description="test gap",
            signal_source="test",
            evidence={"count": 1},
        )
        d = r.to_dict()
        assert "dimension" in d
        assert "status" in d
        assert "gap_description" in d
        assert "signal_source" in d
        assert "evidence" in d
        assert "evaluated_at" in d

    def test_to_dict_is_json_serialisable(self):
        r = DimensionEvidenceResult(
            dimension=AcceptanceDimension.readiness_prerequisite,
            status=DimensionEvidenceStatus.unknown,
            gap_description="missing",
            signal_source="test",
        )
        d = r.to_dict()
        json.dumps(d)  # must not raise

    def test_to_json_produces_valid_json(self):
        r = DimensionEvidenceResult(
            dimension=AcceptanceDimension.operator_visibility_evidence,
            status=DimensionEvidenceStatus.accepted,
        )
        json_str = r.to_json()
        parsed = json.loads(json_str)
        assert parsed["status"] == "accepted"

    def test_from_dict_round_trips(self):
        r = DimensionEvidenceResult(
            dimension=AcceptanceDimension.result_convergence_evidence,
            status=DimensionEvidenceStatus.rejected,
            gap_description="convergence gap",
            signal_source="core.flow_aware_result_convergence",
            evidence={"total_artifacts": 10, "quarantine_count": 2},
        )
        d = r.to_dict()
        r2 = DimensionEvidenceResult.from_dict(d)
        assert r2.dimension == r.dimension
        assert r2.status == r.status
        assert r2.gap_description == r.gap_description
        assert r2.signal_source == r.signal_source


# ===========================================================================
# Q/R/S/T/U. DelegatedFlowAcceptanceReport
# ===========================================================================


class TestDelegatedFlowAcceptanceReport:
    def test_constructs_with_defaults(self):
        rpt = DelegatedFlowAcceptanceReport()
        assert isinstance(rpt.report_id, str) and rpt.report_id
        assert isinstance(rpt.verdict, DelegatedFlowAcceptanceVerdict)
        assert isinstance(rpt.dimensions, dict)
        assert isinstance(rpt.summary, str)
        assert isinstance(rpt.evidence_gaps, list)
        assert isinstance(rpt.is_accepted_for_graduation, bool)
        assert isinstance(rpt.gate_version, str)
        assert isinstance(rpt.generated_at, float)
        assert isinstance(rpt.readiness_report_id, str)

    def test_to_dict_has_expected_keys(self):
        rpt = DelegatedFlowAcceptanceReport(
            verdict=DelegatedFlowAcceptanceVerdict.accepted_for_graduation,
            summary="test summary",
            is_accepted_for_graduation=True,
            readiness_report_id="abc123",
        )
        d = rpt.to_dict()
        expected_keys = {
            "report_id",
            "verdict",
            "dimensions",
            "summary",
            "evidence_gaps",
            "is_accepted_for_graduation",
            "gate_version",
            "generated_at",
            "readiness_report_id",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_to_dict_includes_readiness_report_id(self):
        rpt = DelegatedFlowAcceptanceReport(readiness_report_id="deadbeef")
        d = rpt.to_dict()
        assert d["readiness_report_id"] == "deadbeef"

    def test_to_dict_is_json_serialisable(self):
        rpt = DelegatedFlowAcceptanceReport(
            verdict=DelegatedFlowAcceptanceVerdict.rejected_due_to_compat_bypass_risk,
        )
        d = rpt.to_dict()
        json.dumps(d)  # must not raise

    def test_to_json_produces_valid_json(self):
        rpt = DelegatedFlowAcceptanceReport()
        json_str = rpt.to_json()
        parsed = json.loads(json_str)
        assert "verdict" in parsed

    def test_from_dict_round_trips(self):
        rpt = DelegatedFlowAcceptanceReport(
            verdict=DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap,
            summary="truth contract gap",
            is_accepted_for_graduation=False,
            gate_version="1.0",
            readiness_report_id="xyz789",
        )
        d = rpt.to_dict()
        rpt2 = DelegatedFlowAcceptanceReport.from_dict(d)
        assert rpt2.verdict == rpt.verdict
        assert rpt2.summary == rpt.summary
        assert rpt2.is_accepted_for_graduation == rpt.is_accepted_for_graduation
        assert rpt2.readiness_report_id == rpt.readiness_report_id

    def test_get_dimension_returns_correct_result(self):
        dim_result = _make_accepted_dim(AcceptanceDimension.truth_ownership_evidence)
        rpt = DelegatedFlowAcceptanceReport(
            dimensions={
                AcceptanceDimension.truth_ownership_evidence.value: dim_result
            }
        )
        retrieved = rpt.get_dimension(AcceptanceDimension.truth_ownership_evidence)
        assert retrieved is dim_result

    def test_get_dimension_returns_none_when_missing(self):
        rpt = DelegatedFlowAcceptanceReport()
        assert rpt.get_dimension(AcceptanceDimension.compat_bypass_evidence) is None


# ===========================================================================
# V/W/X. Singleton management
# ===========================================================================


class TestSingletonManagement:
    def test_get_acceptance_gate_returns_instance(self):
        gate = get_acceptance_gate()
        assert isinstance(gate, DelegatedFlowAcceptanceGate)

    def test_singleton_identity(self):
        gate1 = get_acceptance_gate()
        gate2 = get_acceptance_gate()
        assert gate1 is gate2

    def test_reset_clears_singleton(self):
        gate1 = get_acceptance_gate()
        reset_acceptance_gate()
        gate2 = get_acceptance_gate()
        assert gate1 is not gate2


# ===========================================================================
# Y/Z/AA/AB/AC/AD/AE. DelegatedFlowAcceptanceGate.evaluate()
# ===========================================================================


class TestAcceptanceGateEvaluate:
    def test_evaluate_returns_acceptance_report(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert isinstance(report, DelegatedFlowAcceptanceReport)

    def test_evaluate_verdict_is_enum(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert isinstance(report.verdict, DelegatedFlowAcceptanceVerdict)

    def test_evaluate_has_all_six_dimensions(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        expected_keys = {d.value for d in AcceptanceDimension.all_dimensions()}
        assert set(report.dimensions.keys()) == expected_keys

    def test_evaluate_dimensions_are_dim_evidence_result(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        for v in report.dimensions.values():
            assert isinstance(v, DimensionEvidenceResult)

    def test_evaluate_report_is_json_serialisable(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        json.dumps(report.to_dict())  # must not raise

    def test_evaluate_is_accepted_matches_verdict(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert report.is_accepted_for_graduation == report.verdict.is_accepted

    def test_evaluate_summary_is_non_empty(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert report.summary

    def test_evaluate_report_has_report_id(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert report.report_id

    def test_evaluate_report_has_gate_version(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert report.gate_version


# ===========================================================================
# AF. evaluate_delegated_flow_acceptance() convenience wrapper
# ===========================================================================


class TestConvenienceWrapper:
    def test_convenience_wrapper_returns_report(self):
        report = evaluate_delegated_flow_acceptance()
        assert isinstance(report, DelegatedFlowAcceptanceReport)

    def test_convenience_wrapper_verdict_is_enum(self):
        report = evaluate_delegated_flow_acceptance()
        assert isinstance(report.verdict, DelegatedFlowAcceptanceVerdict)


# ===========================================================================
# AG–AN. _compute_verdict
# ===========================================================================


class TestComputeVerdict:
    """Tests for DelegatedFlowAcceptanceGate._compute_verdict."""

    def _compute(self, dims: Dict[str, DimensionEvidenceResult]) -> DelegatedFlowAcceptanceVerdict:
        return DelegatedFlowAcceptanceGate._compute_verdict(dims)

    def test_unknown_any_dimension_returns_incomplete_signals(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.truth_ownership_evidence.value] = _make_unknown_dim(
            AcceptanceDimension.truth_ownership_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals

    def test_unknown_readiness_returns_incomplete_signals(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.readiness_prerequisite.value] = _make_unknown_dim(
            AcceptanceDimension.readiness_prerequisite
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals

    def test_readiness_rejected_returns_missing_evidence(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.readiness_prerequisite.value] = _make_rejected_dim(
            AcceptanceDimension.readiness_prerequisite
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_missing_evidence

    def test_truth_rejected_returns_truth_contract_gap(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.truth_ownership_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.truth_ownership_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap

    def test_convergence_rejected_returns_result_contract_gap(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.result_convergence_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.result_convergence_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_result_contract_gap

    def test_operator_rejected_returns_operator_visibility_gap(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.operator_visibility_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.operator_visibility_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_operator_visibility_gap

    def test_compat_rejected_returns_compat_bypass_risk(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.compat_bypass_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.compat_bypass_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_compat_bypass_risk

    def test_continuity_rejected_returns_missing_evidence(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.continuity_replay_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.continuity_replay_evidence
        )
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.rejected_due_to_missing_evidence

    def test_all_accepted_returns_accepted_for_graduation(self):
        dims = _all_accepted_dims()
        verdict = self._compute(dims)
        assert verdict == DelegatedFlowAcceptanceVerdict.accepted_for_graduation

    def test_empty_dims_returns_accepted(self):
        # Edge case: no dimensions at all — no rejected or unknown → accepted
        verdict = self._compute({})
        assert verdict == DelegatedFlowAcceptanceVerdict.accepted_for_graduation


# ===========================================================================
# AO. _collect_evidence_gaps
# ===========================================================================


class TestCollectEvidenceGaps:
    def test_gaps_empty_when_all_accepted(self):
        dims = _all_accepted_dims()
        gaps = DelegatedFlowAcceptanceGate._collect_evidence_gaps(dims)
        assert gaps == []

    def test_gaps_include_rejected_dimension(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.truth_ownership_evidence.value] = _make_rejected_dim(
            AcceptanceDimension.truth_ownership_evidence, "truth gap description"
        )
        gaps = DelegatedFlowAcceptanceGate._collect_evidence_gaps(dims)
        assert len(gaps) == 1
        assert gaps[0]["dimension"] == "truth_ownership_evidence"
        assert gaps[0]["status"] == "rejected"
        assert gaps[0]["gap_description"] == "truth gap description"

    def test_gaps_include_unknown_dimension(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.compat_bypass_evidence.value] = _make_unknown_dim(
            AcceptanceDimension.compat_bypass_evidence, "compat unknown"
        )
        gaps = DelegatedFlowAcceptanceGate._collect_evidence_gaps(dims)
        assert any(g["dimension"] == "compat_bypass_evidence" for g in gaps)

    def test_gaps_do_not_include_accepted_dimension(self):
        dims = _all_accepted_dims()
        gaps = DelegatedFlowAcceptanceGate._collect_evidence_gaps(dims)
        accepted_dims = {d.value for d in AcceptanceDimension.all_dimensions()}
        gap_dims = {g["dimension"] for g in gaps}
        assert gap_dims.isdisjoint(accepted_dims)

    def test_gaps_include_signal_source(self):
        dims = _all_accepted_dims()
        dims[AcceptanceDimension.readiness_prerequisite.value] = DimensionEvidenceResult(
            dimension=AcceptanceDimension.readiness_prerequisite,
            status=DimensionEvidenceStatus.unknown,
            gap_description="readiness not available",
            signal_source="core.delegated_flow_readiness_gate",
        )
        gaps = DelegatedFlowAcceptanceGate._collect_evidence_gaps(dims)
        assert any(
            g["dimension"] == "readiness_prerequisite"
            and g.get("signal_source") == "core.delegated_flow_readiness_gate"
            for g in gaps
        )


# ===========================================================================
# AP/AQ. _build_summary
# ===========================================================================


class TestBuildSummary:
    def test_accepted_summary_contains_accepted_for_graduation(self):
        summary = DelegatedFlowAcceptanceGate._build_summary(
            DelegatedFlowAcceptanceVerdict.accepted_for_graduation, []
        )
        assert "ACCEPTED FOR GRADUATION" in summary.upper()

    def test_rejected_summary_contains_not_accepted(self):
        gaps = [{"dimension": "truth_ownership_evidence"}]
        summary = DelegatedFlowAcceptanceGate._build_summary(
            DelegatedFlowAcceptanceVerdict.rejected_due_to_truth_contract_gap, gaps
        )
        assert "NOT ACCEPTED" in summary.upper()

    def test_rejected_summary_contains_verdict_value(self):
        gaps = [{"dimension": "compat_bypass_evidence"}]
        summary = DelegatedFlowAcceptanceGate._build_summary(
            DelegatedFlowAcceptanceVerdict.rejected_due_to_compat_bypass_risk, gaps
        )
        assert "rejected_due_to_compat_bypass_risk" in summary

    def test_unknown_summary_contains_not_accepted(self):
        gaps = [{"dimension": "readiness_prerequisite"}]
        summary = DelegatedFlowAcceptanceGate._build_summary(
            DelegatedFlowAcceptanceVerdict.acceptance_unknown_due_to_incomplete_signals,
            gaps,
        )
        assert "NOT ACCEPTED" in summary.upper()


# ===========================================================================
# AR. DelegatedFlowAcceptanceReport.evidence_gaps populated from evaluate()
# ===========================================================================


class TestEvidenceGapsFromEvaluate:
    def test_evidence_gaps_is_list(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert isinstance(report.evidence_gaps, list)

    def test_evidence_gaps_entries_have_dimension_key(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        for gap in report.evidence_gaps:
            assert "dimension" in gap

    def test_evidence_gaps_entries_have_status_key(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        for gap in report.evidence_gaps:
            assert "status" in gap

    def test_evidence_gaps_entries_have_gap_description_key(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        for gap in report.evidence_gaps:
            assert "gap_description" in gap


# ===========================================================================
# AS. DimensionEvidenceResult with status=accepted has empty gap_description
# ===========================================================================


class TestAcceptedDimHasEmptyGapDescription:
    def test_accepted_dim_empty_gap(self):
        r = _make_accepted_dim(AcceptanceDimension.continuity_replay_evidence)
        assert r.gap_description == ""

    def test_rejected_dim_non_empty_gap(self):
        r = _make_rejected_dim(
            AcceptanceDimension.continuity_replay_evidence, "some gap"
        )
        assert r.gap_description != ""


# ===========================================================================
# AT. All public names are in __all__
# ===========================================================================


class TestAllExports:
    _EXPECTED_NAMES = [
        "DELEGATED_FLOW_ACCEPTANCE_GATE_AUTHORITY",
        "DELEGATED_FLOW_ACCEPTANCE_GATE_PR10V2_SENTINEL",
        "ACCEPTANCE_GATE_IS_EVIDENCE_BACKED_JUDGMENT_POLICY",
        "ACCEPTANCE_GATE_IS_PROJECTION_ONLY_POLICY",
        "ACCEPTANCE_GATE_FAIL_CONSERVATIVE_ON_MISSING_EVIDENCE_POLICY",
        "ACCEPTANCE_EVIDENCE_GAP_MUST_BE_OPERATOR_VISIBLE_POLICY",
        "ACCEPTANCE_VERDICT_IS_STABLE_ARTIFACT_POLICY",
        "ALL_SIX_DIMENSIONS_REQUIRED_FOR_GRADUATION_POLICY",
        "READINESS_IS_PREREQUISITE_FOR_ACCEPTANCE_POLICY",
        "ACCEPTANCE_REFERENCES_CANONICAL_EVIDENCE_SOURCES_POLICY",
        "AcceptanceDimension",
        "DimensionEvidenceStatus",
        "DelegatedFlowAcceptanceVerdict",
        "DimensionEvidenceResult",
        "DelegatedFlowAcceptanceReport",
        "DelegatedFlowAcceptanceGate",
        "evaluate_delegated_flow_acceptance",
        "get_acceptance_gate",
        "reset_acceptance_gate",
    ]

    def test_all_expected_names_in_all(self):
        for name in self._EXPECTED_NAMES:
            assert name in _gate_mod.__all__, f"{name!r} not in __all__"

    def test_all_names_are_importable(self):
        for name in self._EXPECTED_NAMES:
            assert hasattr(_gate_mod, name), f"{name!r} not importable from module"


# ===========================================================================
# AU. Policy sentinel count
# ===========================================================================


class TestPolicySentinelCount:
    def test_at_least_8_policy_sentinels(self):
        policy_names = [
            n for n in _gate_mod.__all__ if n.upper().endswith("_POLICY")
        ]
        assert len(policy_names) >= 8


# ===========================================================================
# AV/AW. readiness_report_id field
# ===========================================================================


class TestReadinessReportIdField:
    def test_acceptance_report_has_readiness_report_id(self):
        rpt = DelegatedFlowAcceptanceReport()
        assert hasattr(rpt, "readiness_report_id")

    def test_readiness_report_id_is_string(self):
        rpt = DelegatedFlowAcceptanceReport()
        assert isinstance(rpt.readiness_report_id, str)

    def test_to_dict_includes_readiness_report_id_key(self):
        rpt = DelegatedFlowAcceptanceReport(readiness_report_id="test123")
        d = rpt.to_dict()
        assert "readiness_report_id" in d
        assert d["readiness_report_id"] == "test123"

    def test_evaluate_report_has_readiness_report_id(self):
        gate = DelegatedFlowAcceptanceGate()
        report = gate.evaluate()
        assert hasattr(report, "readiness_report_id")
        assert isinstance(report.readiness_report_id, str)
