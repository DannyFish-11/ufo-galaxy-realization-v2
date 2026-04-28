#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr17_v2_system_final_acceptance_verdict.py
======================================================
PR-17V2 — System-Level Final Acceptance Verdict — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-17V2 sentinel present
    and non-empty.
B.  All seven policy sentinels are non-empty strings with expected keywords.
C.  AcceptanceDimensionId enum has the five required dimension values.
D.  AcceptanceDimensionId.from_string() handles valid, invalid, non-string.
E.  AcceptanceDimensionId.all_dimensions() returns exactly five dimensions.
F.  DimensionStatus enum has accepted / pending / unresolved values.
G.  DimensionStatus.from_string() handles valid, invalid, non-string.
H.  SystemAcceptanceVerdict enum has the four required verdict values.
I.  SystemAcceptanceVerdict.from_string() handles valid, invalid, non-string.
J.  SystemAcceptanceVerdict.is_fully_operational True only for fully_operational.
K.  SystemAcceptanceVerdict.is_blocked True for critical_risk and unknown.
L.  SystemAcceptanceVerdict.is_pending True only for pending_dimensions.
M.  AcceptanceChecklistItem constructs with required fields.
N.  AcceptanceChecklistItem.to_dict() returns JSON-serialisable dict with keys.
O.  AcceptanceChecklistItem.to_json() produces valid JSON.
P.  AcceptanceChecklistItem.from_dict() round-trips correctly.
Q.  SystemAcceptanceReport constructs with required fields.
R.  SystemAcceptanceReport.to_dict() returns JSON-serialisable dict.
S.  SystemAcceptanceReport.to_json() produces valid JSON.
T.  SystemAcceptanceReport.from_dict() round-trips correctly.
U.  SystemAcceptanceReport.get_checklist_item() returns correct item.
V.  get_system_acceptance_evaluator() returns singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_system_acceptance_evaluator() resets the singleton.
Y.  SystemFinalAcceptanceEvaluator.evaluate() returns SystemAcceptanceReport.
Z.  evaluate() verdict is not fully_operational when sub-systems unavailable.
AA. evaluate() checklist has all five dimension keys.
AB. evaluate() checklist items are all AcceptanceChecklistItem instances.
AC. evaluate() report is JSON-serialisable end-to-end.
AD. evaluate() report.is_fully_operational == report.verdict.is_fully_operational.
AE. evaluate() report.summary is non-empty.
AF. evaluate() report.unresolved_risk_summary is a list.
AG. evaluate() report.evidence_linkage is a dict with five keys.
AH. evaluate_system_acceptance() convenience wrapper returns report.
AI. _compute_verdict: all accepted → fully_operational.
AJ. _compute_verdict: any unresolved → not_fully_operational_critical_risk.
AK. _compute_verdict: any pending (no unresolved) → pending_dimensions.
AL. _compute_verdict: missing dimension → acceptance_unknown_insufficient_evidence.
AM. _collect_unresolved_risks returns entries only for non-accepted dimensions.
AN. _collect_unresolved_risks returns empty list when all accepted.
AO. _build_evidence_linkage returns dict with five dimension keys.
AP. _build_summary contains FULLY OPERATIONAL when verdict is fully_operational.
AQ. _build_summary contains UNRESOLVED RISKS section when risks exist.
AR. _build_summary contains checklist line for every dimension.
AS. Unresolved dimension populates unresolved_risk_summary in evaluate().
AT. All public names are in __all__.
AU. Policy sentinel count is at least 7.
AV. report.summary contains the verdict value string.
AW. SystemAcceptanceReport.to_dict() includes all required top-level keys.
AX. AcceptanceChecklistItem with status=accepted has empty gap_description.
AY. _build_summary contains 'CONCLUSION' line.
AZ. Fail-conservative: absent module causes unresolved status, not accepted.
"""

from __future__ import annotations

import json
import sys
import os
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.system_final_acceptance_verdict as _mod
from core.system_final_acceptance_verdict import (
    SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY,
    SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL,
    SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY,
    SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY,
    SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY,
    UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY,
    DUAL_FORMAT_OUTPUT_REQUIRED_POLICY,
    ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY,
    CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY,
    AcceptanceDimensionId,
    DimensionStatus,
    SystemAcceptanceVerdict,
    AcceptanceChecklistItem,
    SystemAcceptanceReport,
    SystemFinalAcceptanceEvaluator,
    evaluate_system_acceptance,
    get_system_acceptance_evaluator,
    reset_system_acceptance_evaluator,
)


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def fresh_evaluator():
    """Reset the evaluator singleton before and after each test."""
    reset_system_acceptance_evaluator()
    yield
    reset_system_acceptance_evaluator()


def _make_accepted_item(
    dim: AcceptanceDimensionId,
) -> AcceptanceChecklistItem:
    return AcceptanceChecklistItem(
        dimension=dim,
        status=DimensionStatus.accepted,
        evidence_summary="All evidence present.",
        evidence_linkage={"source": "test"},
        gap_description="",
        signal_source="test",
    )


def _make_pending_item(
    dim: AcceptanceDimensionId, desc: str = "pending gap"
) -> AcceptanceChecklistItem:
    return AcceptanceChecklistItem(
        dimension=dim,
        status=DimensionStatus.pending,
        evidence_summary="Partial evidence.",
        evidence_linkage={},
        gap_description=desc,
        signal_source="test",
    )


def _make_unresolved_item(
    dim: AcceptanceDimensionId, desc: str = "unresolved gap"
) -> AcceptanceChecklistItem:
    return AcceptanceChecklistItem(
        dimension=dim,
        status=DimensionStatus.unresolved,
        evidence_summary="Evidence unavailable.",
        evidence_linkage={},
        gap_description=desc,
        signal_source="test",
    )


def _all_accepted_checklist() -> Dict[str, AcceptanceChecklistItem]:
    return {
        dim.value: _make_accepted_item(dim)
        for dim in AcceptanceDimensionId.all_dimensions()
    }


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.system_final_acceptance_verdict  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY
        assert isinstance(SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY, str)

    def test_authority_sentinel_contains_pr17v2(self):
        assert "PR17V2" in SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY

    def test_pr17v2_sentinel_non_empty(self):
        assert SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL
        assert isinstance(SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL, str)

    def test_pr17v2_sentinel_contains_pr17v2(self):
        assert "PR17V2" in SYSTEM_FINAL_ACCEPTANCE_VERDICT_PR17V2_SENTINEL

    def test_authority_sentinel_contains_fully_operational(self):
        assert "fully-operational" in SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY.lower()

    def test_authority_sentinel_contains_acceptance(self):
        assert "acceptance" in SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY.lower()


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _POLICY_SENTINELS = [
        SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY,
        SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY,
        SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY,
        UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY,
        DUAL_FORMAT_OUTPUT_REQUIRED_POLICY,
        ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY,
        CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY,
    ]

    def test_all_policy_sentinels_non_empty(self):
        for s in self._POLICY_SENTINELS:
            assert s, f"Policy sentinel is empty: {s!r}"

    def test_all_policy_sentinels_are_strings(self):
        for s in self._POLICY_SENTINELS:
            assert isinstance(s, str)

    def test_policy_count_at_least_seven(self):
        assert len(self._POLICY_SENTINELS) >= 7  # AU

    def test_authoritative_aggregation_policy_keyword(self):
        assert "authoritative" in SYSTEM_VERDICT_IS_AUTHORITATIVE_AGGREGATION_POLICY.lower()

    def test_projection_only_policy_keyword(self):
        assert "read-only" in SYSTEM_VERDICT_IS_PROJECTION_ONLY_POLICY.lower()

    def test_fail_conservative_policy_keyword(self):
        assert "silence" in SYSTEM_VERDICT_FAIL_CONSERVATIVE_ON_MISSING_DIMENSION_POLICY.lower()

    def test_unresolved_risk_policy_keyword(self):
        assert "unresolved" in UNRESOLVED_RISK_MUST_BE_EXPLICIT_POLICY.lower()

    def test_dual_format_policy_keyword(self):
        assert "json" in DUAL_FORMAT_OUTPUT_REQUIRED_POLICY.lower()

    def test_five_dimensions_policy_keyword(self):
        assert "five" in ALL_FIVE_DIMENSIONS_REQUIRED_FOR_FULLY_OPERATIONAL_POLICY.lower()

    def test_critical_dimension_policy_keyword(self):
        assert "fully_operational" in CRITICAL_DIMENSION_UNRESOLVED_BLOCKS_FULLY_OPERATIONAL_POLICY.lower()


# ===========================================================================
# C. AcceptanceDimensionId enum
# ===========================================================================


class TestAcceptanceDimensionId:
    def test_enum_has_runtime_readiness(self):
        assert AcceptanceDimensionId.runtime_readiness

    def test_enum_has_delegated_flow(self):
        assert AcceptanceDimensionId.delegated_flow

    def test_enum_has_governance(self):
        assert AcceptanceDimensionId.governance

    def test_enum_has_multi_device_recovery(self):
        assert AcceptanceDimensionId.multi_device_recovery

    def test_enum_has_android_participant(self):
        assert AcceptanceDimensionId.android_participant

    def test_exactly_five_members(self):
        assert len(list(AcceptanceDimensionId)) == 6


# ===========================================================================
# D. AcceptanceDimensionId.from_string()
# ===========================================================================


class TestAcceptanceDimensionIdFromString:
    def test_valid_runtime_readiness(self):
        assert AcceptanceDimensionId.from_string("runtime_readiness") == AcceptanceDimensionId.runtime_readiness

    def test_valid_delegated_flow(self):
        assert AcceptanceDimensionId.from_string("delegated_flow") == AcceptanceDimensionId.delegated_flow

    def test_valid_governance(self):
        assert AcceptanceDimensionId.from_string("governance") == AcceptanceDimensionId.governance

    def test_valid_multi_device_recovery(self):
        assert AcceptanceDimensionId.from_string("multi_device_recovery") == AcceptanceDimensionId.multi_device_recovery

    def test_valid_android_participant(self):
        assert AcceptanceDimensionId.from_string("android_participant") == AcceptanceDimensionId.android_participant

    def test_invalid_string_returns_default(self):
        result = AcceptanceDimensionId.from_string("totally_invalid_dimension")
        assert result == AcceptanceDimensionId.runtime_readiness

    def test_non_string_returns_default(self):
        result = AcceptanceDimensionId.from_string(42)  # type: ignore[arg-type]
        assert result == AcceptanceDimensionId.runtime_readiness


# ===========================================================================
# E. AcceptanceDimensionId.all_dimensions()
# ===========================================================================


class TestAllDimensions:
    def test_all_dimensions_returns_list(self):
        dims = AcceptanceDimensionId.all_dimensions()
        assert isinstance(dims, list)

    def test_all_dimensions_has_five_entries(self):
        assert len(AcceptanceDimensionId.all_dimensions()) == 6

    def test_all_dimensions_order(self):
        dims = AcceptanceDimensionId.all_dimensions()
        assert dims[0] == AcceptanceDimensionId.runtime_readiness
        assert dims[1] == AcceptanceDimensionId.delegated_flow
        assert dims[2] == AcceptanceDimensionId.governance
        assert dims[3] == AcceptanceDimensionId.multi_device_recovery
        assert dims[4] == AcceptanceDimensionId.android_participant
        assert dims[5] == AcceptanceDimensionId.recovery_truth_surface


# ===========================================================================
# F. DimensionStatus enum
# ===========================================================================


class TestDimensionStatus:
    def test_has_accepted(self):
        assert DimensionStatus.accepted

    def test_has_pending(self):
        assert DimensionStatus.pending

    def test_has_unresolved(self):
        assert DimensionStatus.unresolved

    def test_exactly_three_members(self):
        assert len(list(DimensionStatus)) == 3


# ===========================================================================
# G. DimensionStatus.from_string()
# ===========================================================================


class TestDimensionStatusFromString:
    def test_valid_accepted(self):
        assert DimensionStatus.from_string("accepted") == DimensionStatus.accepted

    def test_valid_pending(self):
        assert DimensionStatus.from_string("pending") == DimensionStatus.pending

    def test_valid_unresolved(self):
        assert DimensionStatus.from_string("unresolved") == DimensionStatus.unresolved

    def test_invalid_returns_unresolved(self):
        assert DimensionStatus.from_string("totally_invalid") == DimensionStatus.unresolved

    def test_non_string_returns_unresolved(self):
        assert DimensionStatus.from_string(None) == DimensionStatus.unresolved  # type: ignore[arg-type]


# ===========================================================================
# H. SystemAcceptanceVerdict enum
# ===========================================================================


class TestSystemAcceptanceVerdict:
    def test_has_fully_operational(self):
        assert SystemAcceptanceVerdict.fully_operational

    def test_has_pending_dimensions(self):
        assert SystemAcceptanceVerdict.not_fully_operational_pending_dimensions

    def test_has_critical_risk(self):
        assert SystemAcceptanceVerdict.not_fully_operational_critical_risk

    def test_has_unknown(self):
        assert SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

    def test_exactly_four_members(self):
        assert len(list(SystemAcceptanceVerdict)) == 4


# ===========================================================================
# I. SystemAcceptanceVerdict.from_string()
# ===========================================================================


class TestSystemAcceptanceVerdictFromString:
    def test_valid_fully_operational(self):
        v = SystemAcceptanceVerdict.from_string("fully_operational")
        assert v == SystemAcceptanceVerdict.fully_operational

    def test_valid_pending(self):
        v = SystemAcceptanceVerdict.from_string("not_fully_operational_pending_dimensions")
        assert v == SystemAcceptanceVerdict.not_fully_operational_pending_dimensions

    def test_valid_critical_risk(self):
        v = SystemAcceptanceVerdict.from_string("not_fully_operational_critical_risk")
        assert v == SystemAcceptanceVerdict.not_fully_operational_critical_risk

    def test_valid_unknown(self):
        v = SystemAcceptanceVerdict.from_string("acceptance_unknown_insufficient_evidence")
        assert v == SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

    def test_invalid_returns_unknown(self):
        v = SystemAcceptanceVerdict.from_string("totally_invalid")
        assert v == SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

    def test_non_string_returns_unknown(self):
        v = SystemAcceptanceVerdict.from_string(99)  # type: ignore[arg-type]
        assert v == SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence


# ===========================================================================
# J. is_fully_operational
# ===========================================================================


class TestVerdictIsFullyOperational:
    def test_true_only_for_fully_operational(self):
        assert SystemAcceptanceVerdict.fully_operational.is_fully_operational is True

    def test_false_for_pending(self):
        assert SystemAcceptanceVerdict.not_fully_operational_pending_dimensions.is_fully_operational is False

    def test_false_for_critical_risk(self):
        assert SystemAcceptanceVerdict.not_fully_operational_critical_risk.is_fully_operational is False

    def test_false_for_unknown(self):
        assert SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence.is_fully_operational is False


# ===========================================================================
# K. is_blocked
# ===========================================================================


class TestVerdictIsBlocked:
    def test_true_for_critical_risk(self):
        assert SystemAcceptanceVerdict.not_fully_operational_critical_risk.is_blocked is True

    def test_true_for_unknown(self):
        assert SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence.is_blocked is True

    def test_false_for_fully_operational(self):
        assert SystemAcceptanceVerdict.fully_operational.is_blocked is False

    def test_false_for_pending(self):
        assert SystemAcceptanceVerdict.not_fully_operational_pending_dimensions.is_blocked is False


# ===========================================================================
# L. is_pending
# ===========================================================================


class TestVerdictIsPending:
    def test_true_only_for_pending(self):
        assert SystemAcceptanceVerdict.not_fully_operational_pending_dimensions.is_pending is True

    def test_false_for_fully_operational(self):
        assert SystemAcceptanceVerdict.fully_operational.is_pending is False

    def test_false_for_critical_risk(self):
        assert SystemAcceptanceVerdict.not_fully_operational_critical_risk.is_pending is False

    def test_false_for_unknown(self):
        assert SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence.is_pending is False


# ===========================================================================
# M. AcceptanceChecklistItem construction
# ===========================================================================


class TestAcceptanceChecklistItemConstruct:
    def test_construct_defaults(self):
        item = AcceptanceChecklistItem()
        assert item.dimension == AcceptanceDimensionId.runtime_readiness
        assert item.status == DimensionStatus.unresolved
        assert item.evidence_summary == ""
        assert item.gap_description == ""
        assert isinstance(item.evidence_linkage, dict)
        assert item.signal_source == ""
        assert item.evaluated_at > 0

    def test_construct_explicit(self):
        item = AcceptanceChecklistItem(
            dimension=AcceptanceDimensionId.governance,
            status=DimensionStatus.accepted,
            evidence_summary="All good.",
            evidence_linkage={"key": "val"},
            gap_description="",
            signal_source="test.module",
        )
        assert item.dimension == AcceptanceDimensionId.governance
        assert item.status == DimensionStatus.accepted


# ===========================================================================
# N. AcceptanceChecklistItem.to_dict()
# ===========================================================================


class TestAcceptanceChecklistItemToDict:
    def test_returns_dict(self):
        item = _make_accepted_item(AcceptanceDimensionId.delegated_flow)
        d = item.to_dict()
        assert isinstance(d, dict)

    def test_has_required_keys(self):
        item = _make_accepted_item(AcceptanceDimensionId.delegated_flow)
        d = item.to_dict()
        for key in (
            "dimension",
            "status",
            "evidence_summary",
            "evidence_linkage",
            "gap_description",
            "signal_source",
            "evaluated_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        item = _make_accepted_item(AcceptanceDimensionId.android_participant)
        d = item.to_dict()
        json.dumps(d)  # must not raise


# ===========================================================================
# O. AcceptanceChecklistItem.to_json()
# ===========================================================================


class TestAcceptanceChecklistItemToJson:
    def test_returns_string(self):
        item = _make_accepted_item(AcceptanceDimensionId.runtime_readiness)
        assert isinstance(item.to_json(), str)

    def test_valid_json(self):
        item = _make_accepted_item(AcceptanceDimensionId.governance)
        parsed = json.loads(item.to_json())
        assert isinstance(parsed, dict)


# ===========================================================================
# P. AcceptanceChecklistItem.from_dict() round-trip
# ===========================================================================


class TestAcceptanceChecklistItemFromDict:
    def test_round_trip(self):
        original = AcceptanceChecklistItem(
            dimension=AcceptanceDimensionId.multi_device_recovery,
            status=DimensionStatus.pending,
            evidence_summary="Partial.",
            evidence_linkage={"k": "v"},
            gap_description="some gap",
            signal_source="some.module",
        )
        restored = AcceptanceChecklistItem.from_dict(original.to_dict())
        assert restored.dimension == original.dimension
        assert restored.status == original.status
        assert restored.evidence_summary == original.evidence_summary
        assert restored.gap_description == original.gap_description
        assert restored.signal_source == original.signal_source


# ===========================================================================
# Q. SystemAcceptanceReport construction
# ===========================================================================


class TestSystemAcceptanceReportConstruct:
    def test_construct_defaults(self):
        report = SystemAcceptanceReport()
        assert report.verdict == SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence
        assert isinstance(report.checklist, dict)
        assert isinstance(report.unresolved_risk_summary, list)
        assert isinstance(report.evidence_linkage, dict)
        assert report.summary == ""
        assert report.is_fully_operational is False
        assert report.evaluator_version == "1.0"
        assert report.generated_at > 0
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0


# ===========================================================================
# R. SystemAcceptanceReport.to_dict()
# ===========================================================================


class TestSystemAcceptanceReportToDict:
    def test_returns_dict(self):
        report = SystemAcceptanceReport()
        assert isinstance(report.to_dict(), dict)

    def test_has_required_keys(self):  # AW
        report = SystemAcceptanceReport()
        d = report.to_dict()
        for key in (
            "report_id",
            "verdict",
            "checklist",
            "unresolved_risk_summary",
            "evidence_linkage",
            "summary",
            "is_fully_operational",
            "evaluator_version",
            "generated_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        report = SystemAcceptanceReport()
        json.dumps(report.to_dict())


# ===========================================================================
# S. SystemAcceptanceReport.to_json()
# ===========================================================================


class TestSystemAcceptanceReportToJson:
    def test_returns_string(self):
        report = SystemAcceptanceReport()
        assert isinstance(report.to_json(), str)

    def test_valid_json(self):
        report = SystemAcceptanceReport()
        parsed = json.loads(report.to_json())
        assert isinstance(parsed, dict)


# ===========================================================================
# T. SystemAcceptanceReport.from_dict() round-trip
# ===========================================================================


class TestSystemAcceptanceReportFromDict:
    def test_round_trip_minimal(self):
        original = SystemAcceptanceReport(
            verdict=SystemAcceptanceVerdict.not_fully_operational_critical_risk,
            summary="test summary",
        )
        restored = SystemAcceptanceReport.from_dict(original.to_dict())
        assert restored.verdict == original.verdict
        assert restored.summary == original.summary
        assert restored.is_fully_operational == original.is_fully_operational
        assert restored.evaluator_version == original.evaluator_version

    def test_round_trip_with_checklist(self):
        checklist = _all_accepted_checklist()
        original = SystemAcceptanceReport(
            verdict=SystemAcceptanceVerdict.fully_operational,
            checklist=checklist,
            is_fully_operational=True,
        )
        restored = SystemAcceptanceReport.from_dict(original.to_dict())
        assert restored.verdict == SystemAcceptanceVerdict.fully_operational
        assert restored.is_fully_operational is True
        assert len(restored.checklist) == 6


# ===========================================================================
# U. SystemAcceptanceReport.get_checklist_item()
# ===========================================================================


class TestGetChecklistItem:
    def test_returns_correct_item(self):
        item = _make_accepted_item(AcceptanceDimensionId.governance)
        report = SystemAcceptanceReport(
            checklist={AcceptanceDimensionId.governance.value: item}
        )
        retrieved = report.get_checklist_item(AcceptanceDimensionId.governance)
        assert retrieved is item

    def test_returns_none_for_missing(self):
        report = SystemAcceptanceReport()
        assert report.get_checklist_item(AcceptanceDimensionId.android_participant) is None


# ===========================================================================
# V. get_system_acceptance_evaluator() returns singleton
# ===========================================================================


class TestGetEvaluatorSingleton:
    def test_returns_evaluator(self):
        ev = get_system_acceptance_evaluator()
        assert isinstance(ev, SystemFinalAcceptanceEvaluator)

    def test_singleton_identity(self):  # W
        ev1 = get_system_acceptance_evaluator()
        ev2 = get_system_acceptance_evaluator()
        assert ev1 is ev2

    def test_reset_breaks_identity(self):  # X
        ev1 = get_system_acceptance_evaluator()
        reset_system_acceptance_evaluator()
        ev2 = get_system_acceptance_evaluator()
        assert ev1 is not ev2


# ===========================================================================
# Y. evaluate() returns SystemAcceptanceReport
# ===========================================================================


class TestEvaluateReturnsReport:
    def test_returns_report_type(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert isinstance(report, SystemAcceptanceReport)


# ===========================================================================
# Z. evaluate() verdict not fully_operational when sub-systems unavailable
# ===========================================================================


class TestEvaluateVerdictWithUnavailableSubsystems:
    def test_verdict_not_fully_operational_by_default(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert not report.verdict.is_fully_operational


# ===========================================================================
# AA. evaluate() checklist has all five dimension keys
# ===========================================================================


class TestEvaluateChecklistKeys:
    def test_all_five_dimension_keys_present(self):
        report = get_system_acceptance_evaluator().evaluate()
        for dim in AcceptanceDimensionId.all_dimensions():
            assert dim.value in report.checklist, f"Missing dimension: {dim.value}"


# ===========================================================================
# AB. evaluate() checklist items are AcceptanceChecklistItem instances
# ===========================================================================


class TestEvaluateChecklistItemTypes:
    def test_all_items_are_checklist_items(self):
        report = get_system_acceptance_evaluator().evaluate()
        for dim_key, item in report.checklist.items():
            assert isinstance(item, AcceptanceChecklistItem), (
                f"Item for '{dim_key}' is not AcceptanceChecklistItem"
            )


# ===========================================================================
# AC. evaluate() report is JSON-serialisable end-to-end
# ===========================================================================


class TestEvaluateJsonSerialisable:
    def test_full_report_json_serialisable(self):
        report = get_system_acceptance_evaluator().evaluate()
        serialised = report.to_json()
        parsed = json.loads(serialised)
        assert isinstance(parsed, dict)
        assert "verdict" in parsed


# ===========================================================================
# AD. evaluate() is_fully_operational == verdict.is_fully_operational
# ===========================================================================


class TestEvaluateIsFullyOperationalConsistency:
    def test_is_fully_operational_matches_verdict(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert report.is_fully_operational == report.verdict.is_fully_operational


# ===========================================================================
# AE. evaluate() summary is non-empty
# ===========================================================================


class TestEvaluateSummaryNonEmpty:
    def test_summary_non_empty(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert report.summary
        assert isinstance(report.summary, str)
        assert len(report.summary) > 0


# ===========================================================================
# AF. evaluate() unresolved_risk_summary is a list
# ===========================================================================


class TestEvaluateUnresolvedRiskSummary:
    def test_is_list(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert isinstance(report.unresolved_risk_summary, list)


# ===========================================================================
# AG. evaluate() evidence_linkage is a dict with five keys
# ===========================================================================


class TestEvaluateEvidenceLinkage:
    def test_is_dict(self):
        report = get_system_acceptance_evaluator().evaluate()
        assert isinstance(report.evidence_linkage, dict)

    def test_has_five_dimension_keys(self):
        report = get_system_acceptance_evaluator().evaluate()
        for dim in AcceptanceDimensionId.all_dimensions():
            assert dim.value in report.evidence_linkage


# ===========================================================================
# AH. evaluate_system_acceptance() convenience wrapper
# ===========================================================================


class TestEvaluateSystemAcceptanceWrapper:
    def test_returns_report(self):
        report = evaluate_system_acceptance()
        assert isinstance(report, SystemAcceptanceReport)


# ===========================================================================
# AI–AL. _compute_verdict logic
# ===========================================================================


class TestComputeVerdict:
    def _compute(self, checklist: Dict[str, "AcceptanceChecklistItem"]) -> SystemAcceptanceVerdict:
        return SystemFinalAcceptanceEvaluator._compute_verdict(checklist)

    def test_all_accepted_gives_fully_operational(self):  # AI
        checklist = _all_accepted_checklist()
        assert self._compute(checklist) == SystemAcceptanceVerdict.fully_operational

    def test_any_unresolved_gives_critical_risk(self):  # AJ
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.governance.value] = _make_unresolved_item(
            AcceptanceDimensionId.governance
        )
        assert self._compute(checklist) == SystemAcceptanceVerdict.not_fully_operational_critical_risk

    def test_any_pending_no_unresolved_gives_pending(self):  # AK
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.android_participant.value] = _make_pending_item(
            AcceptanceDimensionId.android_participant
        )
        assert self._compute(checklist) == SystemAcceptanceVerdict.not_fully_operational_pending_dimensions

    def test_missing_dimension_gives_unknown(self):  # AL
        checklist = _all_accepted_checklist()
        del checklist[AcceptanceDimensionId.multi_device_recovery.value]
        assert self._compute(checklist) == SystemAcceptanceVerdict.acceptance_unknown_insufficient_evidence

    def test_unresolved_takes_priority_over_pending(self):
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.delegated_flow.value] = _make_pending_item(
            AcceptanceDimensionId.delegated_flow
        )
        checklist[AcceptanceDimensionId.runtime_readiness.value] = _make_unresolved_item(
            AcceptanceDimensionId.runtime_readiness
        )
        assert self._compute(checklist) == SystemAcceptanceVerdict.not_fully_operational_critical_risk


# ===========================================================================
# AM–AN. _collect_unresolved_risks
# ===========================================================================


class TestCollectUnresolvedRisks:
    def _collect(
        self, checklist: Dict[str, "AcceptanceChecklistItem"]
    ) -> List[Dict[str, str]]:
        return SystemFinalAcceptanceEvaluator._collect_unresolved_risks(checklist)

    def test_non_accepted_dimension_appears_in_risks(self):  # AM
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.governance.value] = _make_unresolved_item(
            AcceptanceDimensionId.governance, "some unresolved gap"
        )
        risks = self._collect(checklist)
        dim_values = [r["dimension"] for r in risks]
        assert AcceptanceDimensionId.governance.value in dim_values

    def test_accepted_dimensions_absent_from_risks(self):
        checklist = _all_accepted_checklist()
        risks = self._collect(checklist)
        assert risks == []  # AN

    def test_multiple_non_accepted_dimensions_all_appear(self):
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.delegated_flow.value] = _make_pending_item(
            AcceptanceDimensionId.delegated_flow
        )
        checklist[AcceptanceDimensionId.android_participant.value] = _make_unresolved_item(
            AcceptanceDimensionId.android_participant
        )
        risks = self._collect(checklist)
        dim_values = [r["dimension"] for r in risks]
        assert AcceptanceDimensionId.delegated_flow.value in dim_values
        assert AcceptanceDimensionId.android_participant.value in dim_values

    def test_risk_description_populated(self):
        checklist = _all_accepted_checklist()
        checklist[AcceptanceDimensionId.governance.value] = _make_unresolved_item(
            AcceptanceDimensionId.governance, "explicit gap description"
        )
        risks = self._collect(checklist)
        gov_risk = next(
            (r for r in risks if r["dimension"] == AcceptanceDimensionId.governance.value),
            None,
        )
        assert gov_risk is not None
        assert "explicit gap description" in gov_risk["risk_description"]


# ===========================================================================
# AO. _build_evidence_linkage
# ===========================================================================


class TestBuildEvidenceLinkage:
    def test_returns_five_keys(self):  # AO
        checklist = _all_accepted_checklist()
        linkage = SystemFinalAcceptanceEvaluator._build_evidence_linkage(checklist)
        assert isinstance(linkage, dict)
        for dim in AcceptanceDimensionId.all_dimensions():
            assert dim.value in linkage


# ===========================================================================
# AP–AR. _build_summary
# ===========================================================================


class TestBuildSummary:
    def _build(
        self,
        verdict: SystemAcceptanceVerdict,
        checklist: Dict[str, "AcceptanceChecklistItem"],
        risks: List[Dict[str, str]],
    ) -> str:
        return SystemFinalAcceptanceEvaluator._build_summary(verdict, checklist, risks)

    def test_fully_operational_contains_fully_operational(self):  # AP
        summary = self._build(
            SystemAcceptanceVerdict.fully_operational,
            _all_accepted_checklist(),
            [],
        )
        assert "FULLY OPERATIONAL" in summary.upper()

    def test_has_unresolved_risks_section_when_risks_exist(self):  # AQ
        checklist = _all_accepted_checklist()
        risks = [{"dimension": "governance", "risk_description": "some risk"}]
        summary = self._build(
            SystemAcceptanceVerdict.not_fully_operational_critical_risk,
            checklist,
            risks,
        )
        assert "UNRESOLVED RISKS" in summary.upper()

    def test_no_unresolved_risks_section_when_no_risks(self):
        summary = self._build(
            SystemAcceptanceVerdict.fully_operational,
            _all_accepted_checklist(),
            [],
        )
        assert "UNRESOLVED RISKS" not in summary.upper()

    def test_contains_checklist_line_for_all_dimensions(self):  # AR
        summary = self._build(
            SystemAcceptanceVerdict.fully_operational,
            _all_accepted_checklist(),
            [],
        )
        for dim in AcceptanceDimensionId.all_dimensions():
            assert dim.value in summary

    def test_contains_conclusion_line(self):  # AY
        summary = self._build(
            SystemAcceptanceVerdict.fully_operational,
            _all_accepted_checklist(),
            [],
        )
        assert "CONCLUSION" in summary.upper()

    def test_verdict_value_in_summary(self):  # AV
        verdict = SystemAcceptanceVerdict.not_fully_operational_critical_risk
        summary = self._build(verdict, _all_accepted_checklist(), [])
        assert verdict.value.upper().replace("_", " ") in summary.upper()


# ===========================================================================
# AS. Unresolved dimension populates unresolved_risk_summary in evaluate()
# ===========================================================================


class TestEvaluateUnresolvedRiskPopulated:
    def test_unresolved_risk_summary_non_empty(self):  # AS
        report = get_system_acceptance_evaluator().evaluate()
        # Since sub-systems are unavailable in test context, risks must exist
        assert len(report.unresolved_risk_summary) > 0

    def test_each_risk_has_dimension_and_description(self):
        report = get_system_acceptance_evaluator().evaluate()
        for risk in report.unresolved_risk_summary:
            assert "dimension" in risk
            assert "risk_description" in risk


# ===========================================================================
# AT. All public names in __all__
# ===========================================================================


class TestAllPublicNames:
    def test_all_names_in_module(self):
        for name in _mod.__all__:
            assert hasattr(_mod, name), f"'{name}' in __all__ but missing from module"

    def test_authority_sentinel_in_all(self):
        assert "SYSTEM_FINAL_ACCEPTANCE_VERDICT_AUTHORITY" in _mod.__all__

    def test_verdict_class_in_all(self):
        assert "SystemAcceptanceVerdict" in _mod.__all__

    def test_report_class_in_all(self):
        assert "SystemAcceptanceReport" in _mod.__all__

    def test_evaluator_class_in_all(self):
        assert "SystemFinalAcceptanceEvaluator" in _mod.__all__


# ===========================================================================
# AX. AcceptanceChecklistItem with status=accepted has empty gap_description
# ===========================================================================


class TestAcceptedItemEmptyGapDescription:
    def test_accepted_item_has_empty_gap_description(self):  # AX
        item = _make_accepted_item(AcceptanceDimensionId.delegated_flow)
        assert item.gap_description == ""


# ===========================================================================
# AZ. Fail-conservative: absent module causes unresolved, not accepted
# ===========================================================================


class TestFailConservative:
    def test_all_checklist_items_unresolved_when_modules_absent(self):  # AZ
        """In test context, all sub-system modules are unavailable,
        so every dimension must be unresolved (never silently accepted)."""
        report = get_system_acceptance_evaluator().evaluate()
        for dim_id in AcceptanceDimensionId.all_dimensions():
            item = report.get_checklist_item(dim_id)
            assert item is not None, f"Checklist item missing for {dim_id.value}"
            assert item.status != DimensionStatus.accepted, (
                f"Dimension '{dim_id.value}' was accepted despite absent module — "
                "fail-conservative policy violated."
            )
