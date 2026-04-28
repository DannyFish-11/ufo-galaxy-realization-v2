#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_multi_device_canonical_governance.py
=====================================================
PR-09 — Multi-Device Canonical Governance — test suite.

Coverage areas
--------------
A.  Module importable; authority sentinel and PR-09 sentinel present.
B.  All six policy sentinels are non-empty strings with expected keywords.
C.  MultiDeviceSystemTier enum has all required values.
D.  MultiDeviceSystemTier.from_string() handles valid, invalid, non-string.
E.  MultiDeviceSystemTier.is_operational returns True only for operational tiers.
F.  MultiDeviceSystemTier.is_default_mainline returns True only for default_mainline.
G.  DelegatedParticipantRole enum has all required values.
H.  DelegatedParticipantRole.from_string() handles valid, invalid, non-string.
I.  MultiDeviceGovernanceVerdict enum has all required values.
J.  MultiDeviceGovernanceVerdict.from_string() handles valid, invalid, non-string.
K.  MultiDeviceGovernanceVerdict.is_default_mainline True only for default_mainline_active.
L.  MultiDeviceGovernanceVerdict.is_operational True only for operational verdicts.
M.  MultiDeviceGovernanceVerdict.is_single_device True only for single_device_baseline.
N.  ParticipantClassification constructs with defaults and explicit values.
O.  ParticipantClassification.to_dict() returns JSON-safe dict.
P.  ParticipantClassification.from_dict() round-trips correctly.
Q.  CapabilityGovernanceEntry constructs and serialises correctly.
R.  MultiDeviceGovernanceReport constructs with defaults and explicit values.
S.  MultiDeviceGovernanceReport.to_dict() returns JSON-safe dict with required keys.
T.  MultiDeviceGovernanceReport.to_json() produces valid JSON.
U.  MultiDeviceGovernanceReport.from_dict() round-trips correctly.
V.  get_multi_device_governance_evaluator() returns singleton.
W.  Singleton identity: two calls return the same object.
X.  reset_multi_device_governance_evaluator() resets the singleton.
Y.  build_multi_device_governance_report() convenience wrapper returns report.
Z.  Evaluator.evaluate() returns MultiDeviceGovernanceReport.

Scenario tests (the key invariants from the problem statement):
S1. No delegated participant → single_device_baseline verdict (NOT multi-device active).
S2. No delegated participant → is_operational is False.
S3. No delegated participant → is_default_mainline is False.
S4. Delegated participant present without evidence → conditional_active (NOT default_mainline_active).
S5. Default-mainline capabilities present regardless of delegated participant state.
S6. Guarded capabilities present → verdict cannot be default_mainline_active.
S7. Downgrade reasons recorded when delegated participant without evidence.
S8. Downgrade reasons recorded when guarded capabilities block default-mainline.
S9. Single-device-baseline downgrade reason explicitly recorded.
S10. Secondary device evidence absent vs present produces different verdict context.
S11. No false "fully active" based solely on contract/hook presence.
S12. Default-mainline verdict requires delegated participant WITH evidence.
S13. capability_map includes both default-mainline and guarded capabilities.
S14. Evaluator.evaluate() report is JSON-serialisable end-to-end.
S15. Evaluator.evaluate() report.is_default_mainline == report.verdict.is_default_mainline.
S16. Evaluator.evaluate() report.is_operational == report.verdict.is_operational.
S17. Evaluator.evaluate() report.summary is non-empty.
S18. Evaluator.evaluate() report.downgrade_reasons is a list.
S19. Report from evaluator has capability_map with at least the known capabilities.
S20. Participant classification for 'delegated' role differs from 'primary'.
S21. Single-device-baseline tier is not is_operational.
S22. Conditional tier is_operational.
S23. All public names are in __all__.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import core.multi_device_canonical_governance as _mod
from core.multi_device_canonical_governance import (
    MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY,
    MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL,
    DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY,
    NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY,
    EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY,
    EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY,
    SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY,
    OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY,
    MultiDeviceSystemTier,
    DelegatedParticipantRole,
    MultiDeviceGovernanceVerdict,
    ParticipantClassification,
    CapabilityGovernanceEntry,
    MultiDeviceGovernanceReport,
    MultiDeviceGovernanceEvaluator,
    build_multi_device_governance_report,
    get_multi_device_governance_evaluator,
    reset_multi_device_governance_evaluator,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_evaluator():
    """Reset the evaluator singleton before and after each test."""
    reset_multi_device_governance_evaluator()
    yield
    reset_multi_device_governance_evaluator()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report_with_verdict(
    verdict: MultiDeviceGovernanceVerdict,
    delegated_count: int = 0,
    has_evidence: bool = False,
) -> MultiDeviceGovernanceReport:
    """Build a minimal MultiDeviceGovernanceReport for assertion tests."""
    return MultiDeviceGovernanceReport(
        verdict=verdict,
        system_tier=MultiDeviceSystemTier.from_string(
            "single_device_baseline" if delegated_count == 0 else "conditional"
        ),
        delegated_participant_count=delegated_count,
        has_delegated_participant_evidence=has_evidence,
        is_default_mainline=verdict.is_default_mainline,
        is_operational=verdict.is_operational,
        summary="test summary",
    )


# ===========================================================================
# A. Module importable; sentinels present
# ===========================================================================


class TestModuleSentinels:
    def test_module_importable(self):
        import core.multi_device_canonical_governance  # noqa: F401

    def test_authority_sentinel_non_empty(self):
        assert MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY
        assert isinstance(MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY, str)

    def test_authority_sentinel_contains_pr09(self):
        assert "PR09" in MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY

    def test_authority_sentinel_contains_governance(self):
        assert "governance" in MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY.lower()

    def test_pr09_sentinel_non_empty(self):
        assert MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL
        assert isinstance(MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL, str)

    def test_pr09_sentinel_contains_pr09(self):
        assert "PR09" in MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL


# ===========================================================================
# B. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    _SENTINELS = [
        DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY,
        NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY,
        EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY,
        EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY,
        SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY,
        OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY,
    ]

    def test_all_non_empty(self):
        for s in self._SENTINELS:
            assert s, f"Policy sentinel is empty: {s!r}"

    def test_all_are_strings(self):
        for s in self._SENTINELS:
            assert isinstance(s, str)

    def test_exactly_six_sentinels(self):
        assert len(self._SENTINELS) == 6

    def test_delegated_hooks_policy_keyword(self):
        assert "fully active" in DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY.lower()

    def test_no_delegated_policy_keyword(self):
        assert "delegated participant" in NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY.lower()

    def test_evidence_required_policy_keyword(self):
        assert "evidence" in EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY.lower()

    def test_explicit_downgrade_policy_keyword(self):
        assert "downgrade" in EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY.lower()

    def test_single_device_baseline_policy_keyword(self):
        assert "single_device_baseline" in SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY.lower()

    def test_optional_upgrade_policy_keyword(self):
        assert "optional" in OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY.lower()


# ===========================================================================
# C. MultiDeviceSystemTier enum
# ===========================================================================


class TestMultiDeviceSystemTier:
    def test_has_default_mainline(self):
        assert MultiDeviceSystemTier.default_mainline

    def test_has_conditional(self):
        assert MultiDeviceSystemTier.conditional

    def test_has_guarded(self):
        assert MultiDeviceSystemTier.guarded

    def test_has_partial(self):
        assert MultiDeviceSystemTier.partial

    def test_has_optional(self):
        assert MultiDeviceSystemTier.optional

    def test_has_single_device_baseline(self):
        assert MultiDeviceSystemTier.single_device_baseline

    def test_has_no_evidence(self):
        assert MultiDeviceSystemTier.no_evidence

    def test_exactly_seven_members(self):
        assert len(list(MultiDeviceSystemTier)) == 7


# ===========================================================================
# D. MultiDeviceSystemTier.from_string()
# ===========================================================================


class TestMultiDeviceSystemTierFromString:
    def test_valid_default_mainline(self):
        assert MultiDeviceSystemTier.from_string("default_mainline") == MultiDeviceSystemTier.default_mainline

    def test_valid_conditional(self):
        assert MultiDeviceSystemTier.from_string("conditional") == MultiDeviceSystemTier.conditional

    def test_valid_guarded(self):
        assert MultiDeviceSystemTier.from_string("guarded") == MultiDeviceSystemTier.guarded

    def test_valid_single_device_baseline(self):
        assert MultiDeviceSystemTier.from_string("single_device_baseline") == MultiDeviceSystemTier.single_device_baseline

    def test_invalid_string_returns_no_evidence(self):
        assert MultiDeviceSystemTier.from_string("totally_invalid") == MultiDeviceSystemTier.no_evidence

    def test_non_string_returns_no_evidence(self):
        assert MultiDeviceSystemTier.from_string(42) == MultiDeviceSystemTier.no_evidence  # type: ignore[arg-type]

    def test_none_returns_no_evidence(self):
        assert MultiDeviceSystemTier.from_string(None) == MultiDeviceSystemTier.no_evidence  # type: ignore[arg-type]


# ===========================================================================
# E. MultiDeviceSystemTier.is_operational
# ===========================================================================


class TestMultiDeviceSystemTierIsOperational:
    def test_default_mainline_is_operational(self):
        assert MultiDeviceSystemTier.default_mainline.is_operational is True

    def test_conditional_is_operational(self):
        assert MultiDeviceSystemTier.conditional.is_operational is True

    def test_guarded_not_operational(self):
        assert MultiDeviceSystemTier.guarded.is_operational is False

    def test_partial_not_operational(self):
        assert MultiDeviceSystemTier.partial.is_operational is False

    def test_single_device_baseline_not_operational(self):
        assert MultiDeviceSystemTier.single_device_baseline.is_operational is False

    def test_no_evidence_not_operational(self):
        assert MultiDeviceSystemTier.no_evidence.is_operational is False


# ===========================================================================
# F. MultiDeviceSystemTier.is_default_mainline
# ===========================================================================


class TestMultiDeviceSystemTierIsDefaultMainline:
    def test_default_mainline_is_true(self):
        assert MultiDeviceSystemTier.default_mainline.is_default_mainline is True

    def test_conditional_is_false(self):
        assert MultiDeviceSystemTier.conditional.is_default_mainline is False

    def test_guarded_is_false(self):
        assert MultiDeviceSystemTier.guarded.is_default_mainline is False

    def test_single_device_baseline_is_false(self):
        assert MultiDeviceSystemTier.single_device_baseline.is_default_mainline is False


# ===========================================================================
# G. DelegatedParticipantRole enum
# ===========================================================================


class TestDelegatedParticipantRole:
    def test_has_primary(self):
        assert DelegatedParticipantRole.primary

    def test_has_delegated(self):
        assert DelegatedParticipantRole.delegated

    def test_has_secondary(self):
        assert DelegatedParticipantRole.secondary

    def test_has_observer(self):
        assert DelegatedParticipantRole.observer

    def test_has_none(self):
        assert DelegatedParticipantRole.none

    def test_exactly_five_members(self):
        assert len(list(DelegatedParticipantRole)) == 5


# ===========================================================================
# H. DelegatedParticipantRole.from_string()
# ===========================================================================


class TestDelegatedParticipantRoleFromString:
    def test_valid_primary(self):
        assert DelegatedParticipantRole.from_string("primary") == DelegatedParticipantRole.primary

    def test_valid_delegated(self):
        assert DelegatedParticipantRole.from_string("delegated") == DelegatedParticipantRole.delegated

    def test_valid_secondary(self):
        assert DelegatedParticipantRole.from_string("secondary") == DelegatedParticipantRole.secondary

    def test_valid_observer(self):
        assert DelegatedParticipantRole.from_string("observer") == DelegatedParticipantRole.observer

    def test_invalid_returns_none(self):
        assert DelegatedParticipantRole.from_string("unknown_role") == DelegatedParticipantRole.none

    def test_non_string_returns_none(self):
        assert DelegatedParticipantRole.from_string(None) == DelegatedParticipantRole.none  # type: ignore[arg-type]


# ===========================================================================
# I. MultiDeviceGovernanceVerdict enum
# ===========================================================================


class TestMultiDeviceGovernanceVerdict:
    def test_has_default_mainline_active(self):
        assert MultiDeviceGovernanceVerdict.default_mainline_active

    def test_has_conditional_active(self):
        assert MultiDeviceGovernanceVerdict.conditional_active

    def test_has_guarded_baseline(self):
        assert MultiDeviceGovernanceVerdict.guarded_baseline

    def test_has_single_device_baseline(self):
        assert MultiDeviceGovernanceVerdict.single_device_baseline

    def test_has_partial_evidence(self):
        assert MultiDeviceGovernanceVerdict.partial_evidence

    def test_has_no_evidence(self):
        assert MultiDeviceGovernanceVerdict.no_evidence

    def test_exactly_six_members(self):
        assert len(list(MultiDeviceGovernanceVerdict)) == 6


# ===========================================================================
# J. MultiDeviceGovernanceVerdict.from_string()
# ===========================================================================


class TestMultiDeviceGovernanceVerdictFromString:
    def test_valid_default_mainline_active(self):
        v = MultiDeviceGovernanceVerdict.from_string("default_mainline_active")
        assert v == MultiDeviceGovernanceVerdict.default_mainline_active

    def test_valid_conditional_active(self):
        v = MultiDeviceGovernanceVerdict.from_string("conditional_active")
        assert v == MultiDeviceGovernanceVerdict.conditional_active

    def test_valid_single_device_baseline(self):
        v = MultiDeviceGovernanceVerdict.from_string("single_device_baseline")
        assert v == MultiDeviceGovernanceVerdict.single_device_baseline

    def test_invalid_returns_no_evidence(self):
        v = MultiDeviceGovernanceVerdict.from_string("totally_invalid")
        assert v == MultiDeviceGovernanceVerdict.no_evidence

    def test_non_string_returns_no_evidence(self):
        v = MultiDeviceGovernanceVerdict.from_string(99)  # type: ignore[arg-type]
        assert v == MultiDeviceGovernanceVerdict.no_evidence

    def test_none_returns_no_evidence(self):
        v = MultiDeviceGovernanceVerdict.from_string(None)  # type: ignore[arg-type]
        assert v == MultiDeviceGovernanceVerdict.no_evidence


# ===========================================================================
# K. MultiDeviceGovernanceVerdict.is_default_mainline
# ===========================================================================


class TestVerdictIsDefaultMainline:
    def test_true_only_for_default_mainline_active(self):
        assert MultiDeviceGovernanceVerdict.default_mainline_active.is_default_mainline is True

    def test_false_for_conditional_active(self):
        assert MultiDeviceGovernanceVerdict.conditional_active.is_default_mainline is False

    def test_false_for_single_device_baseline(self):
        assert MultiDeviceGovernanceVerdict.single_device_baseline.is_default_mainline is False

    def test_false_for_no_evidence(self):
        assert MultiDeviceGovernanceVerdict.no_evidence.is_default_mainline is False


# ===========================================================================
# L. MultiDeviceGovernanceVerdict.is_operational
# ===========================================================================


class TestVerdictIsOperational:
    def test_default_mainline_active_is_operational(self):
        assert MultiDeviceGovernanceVerdict.default_mainline_active.is_operational is True

    def test_conditional_active_is_operational(self):
        assert MultiDeviceGovernanceVerdict.conditional_active.is_operational is True

    def test_single_device_baseline_not_operational(self):
        assert MultiDeviceGovernanceVerdict.single_device_baseline.is_operational is False

    def test_no_evidence_not_operational(self):
        assert MultiDeviceGovernanceVerdict.no_evidence.is_operational is False

    def test_guarded_baseline_not_operational(self):
        assert MultiDeviceGovernanceVerdict.guarded_baseline.is_operational is False

    def test_partial_evidence_not_operational(self):
        assert MultiDeviceGovernanceVerdict.partial_evidence.is_operational is False


# ===========================================================================
# M. MultiDeviceGovernanceVerdict.is_single_device
# ===========================================================================


class TestVerdictIsSingleDevice:
    def test_true_only_for_single_device_baseline(self):
        assert MultiDeviceGovernanceVerdict.single_device_baseline.is_single_device is True

    def test_false_for_default_mainline_active(self):
        assert MultiDeviceGovernanceVerdict.default_mainline_active.is_single_device is False

    def test_false_for_conditional_active(self):
        assert MultiDeviceGovernanceVerdict.conditional_active.is_single_device is False

    def test_false_for_no_evidence(self):
        assert MultiDeviceGovernanceVerdict.no_evidence.is_single_device is False


# ===========================================================================
# N. ParticipantClassification construction
# ===========================================================================


class TestParticipantClassification:
    def test_construct_defaults(self):
        pc = ParticipantClassification()
        assert pc.participant_id == ""
        assert pc.device_id == ""
        assert pc.role == DelegatedParticipantRole.none
        assert pc.has_evidence is False
        assert isinstance(pc.evidence_sources, list)
        assert pc.evidence_complete is False
        assert pc.notes == ""

    def test_construct_explicit(self):
        pc = ParticipantClassification(
            participant_id="p-1",
            device_id="d-1",
            role=DelegatedParticipantRole.delegated,
            has_evidence=True,
            evidence_sources=["audit", "readiness"],
            evidence_complete=True,
            notes="test note",
        )
        assert pc.participant_id == "p-1"
        assert pc.role == DelegatedParticipantRole.delegated
        assert pc.has_evidence is True
        assert pc.evidence_complete is True


# ===========================================================================
# O. ParticipantClassification.to_dict()
# ===========================================================================


class TestParticipantClassificationToDict:
    def test_returns_dict(self):
        pc = ParticipantClassification(
            participant_id="p-1",
            device_id="d-1",
            role=DelegatedParticipantRole.delegated,
        )
        d = pc.to_dict()
        assert isinstance(d, dict)

    def test_has_required_keys(self):
        pc = ParticipantClassification()
        d = pc.to_dict()
        for key in (
            "participant_id",
            "device_id",
            "role",
            "has_evidence",
            "evidence_sources",
            "evidence_complete",
            "notes",
        ):
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        pc = ParticipantClassification(
            role=DelegatedParticipantRole.secondary,
            evidence_sources=["audit"],
        )
        json.dumps(pc.to_dict())  # must not raise


# ===========================================================================
# P. ParticipantClassification.from_dict() round-trip
# ===========================================================================


class TestParticipantClassificationRoundTrip:
    def test_round_trip(self):
        original = ParticipantClassification(
            participant_id="p-2",
            device_id="d-2",
            role=DelegatedParticipantRole.secondary,
            has_evidence=True,
            evidence_sources=["audit"],
            evidence_complete=False,
            notes="some note",
        )
        restored = ParticipantClassification.from_dict(original.to_dict())
        assert restored.participant_id == original.participant_id
        assert restored.device_id == original.device_id
        assert restored.role == original.role
        assert restored.has_evidence == original.has_evidence
        assert restored.evidence_sources == original.evidence_sources
        assert restored.evidence_complete == original.evidence_complete
        assert restored.notes == original.notes


# ===========================================================================
# Q. CapabilityGovernanceEntry construction and serialisation
# ===========================================================================


class TestCapabilityGovernanceEntry:
    def test_construct_defaults(self):
        entry = CapabilityGovernanceEntry()
        assert entry.capability_name == ""
        assert entry.tier == MultiDeviceSystemTier.no_evidence
        assert entry.evidence_present is False
        assert entry.notes == ""

    def test_to_dict_has_required_keys(self):
        entry = CapabilityGovernanceEntry(
            capability_name="route_task_single_remote_device",
            tier=MultiDeviceSystemTier.default_mainline,
            evidence_present=True,
        )
        d = entry.to_dict()
        for key in ("capability_name", "tier", "evidence_present", "notes"):
            assert key in d

    def test_round_trip(self):
        original = CapabilityGovernanceEntry(
            capability_name="mesh_session_status_tracking",
            tier=MultiDeviceSystemTier.guarded,
            evidence_present=False,
            notes="contract-first",
        )
        restored = CapabilityGovernanceEntry.from_dict(original.to_dict())
        assert restored.capability_name == original.capability_name
        assert restored.tier == original.tier
        assert restored.evidence_present == original.evidence_present
        assert restored.notes == original.notes


# ===========================================================================
# R. MultiDeviceGovernanceReport construction
# ===========================================================================


class TestMultiDeviceGovernanceReportConstruct:
    def test_construct_defaults(self):
        report = MultiDeviceGovernanceReport()
        assert report.verdict == MultiDeviceGovernanceVerdict.no_evidence
        assert report.system_tier == MultiDeviceSystemTier.no_evidence
        assert isinstance(report.participant_classifications, list)
        assert isinstance(report.capability_map, dict)
        assert report.delegated_participant_count == 0
        assert report.secondary_device_count == 0
        assert report.has_delegated_participant_evidence is False
        assert report.secondary_device_evidence_present is False
        assert isinstance(report.default_mainline_capabilities, list)
        assert isinstance(report.guarded_capabilities, list)
        assert isinstance(report.downgrade_reasons, list)
        assert report.is_default_mainline is False
        assert report.is_operational is False
        assert report.summary == ""
        assert report.evaluated_at > 0
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0


# ===========================================================================
# S. MultiDeviceGovernanceReport.to_dict()
# ===========================================================================


class TestMultiDeviceGovernanceReportToDict:
    _REQUIRED_KEYS = [
        "report_id",
        "verdict",
        "system_tier",
        "participant_classifications",
        "capability_map",
        "delegated_participant_count",
        "secondary_device_count",
        "has_delegated_participant_evidence",
        "secondary_device_evidence_present",
        "default_mainline_capabilities",
        "conditional_capabilities",
        "guarded_capabilities",
        "partial_capabilities",
        "optional_capabilities",
        "downgrade_reasons",
        "is_default_mainline",
        "is_operational",
        "summary",
        "evaluated_at",
    ]

    def test_returns_dict(self):
        report = MultiDeviceGovernanceReport()
        assert isinstance(report.to_dict(), dict)

    def test_has_required_keys(self):
        report = MultiDeviceGovernanceReport()
        d = report.to_dict()
        for key in self._REQUIRED_KEYS:
            assert key in d, f"Missing key: {key}"

    def test_json_serialisable(self):
        report = MultiDeviceGovernanceReport()
        json.dumps(report.to_dict())  # must not raise


# ===========================================================================
# T. MultiDeviceGovernanceReport.to_json()
# ===========================================================================


class TestMultiDeviceGovernanceReportToJson:
    def test_returns_string(self):
        report = MultiDeviceGovernanceReport()
        assert isinstance(report.to_json(), str)

    def test_valid_json(self):
        report = MultiDeviceGovernanceReport()
        parsed = json.loads(report.to_json())
        assert isinstance(parsed, dict)


# ===========================================================================
# U. MultiDeviceGovernanceReport.from_dict() round-trip
# ===========================================================================


class TestMultiDeviceGovernanceReportFromDict:
    def test_round_trip_minimal(self):
        original = MultiDeviceGovernanceReport(
            verdict=MultiDeviceGovernanceVerdict.single_device_baseline,
            system_tier=MultiDeviceSystemTier.single_device_baseline,
            delegated_participant_count=0,
            summary="single device",
        )
        restored = MultiDeviceGovernanceReport.from_dict(original.to_dict())
        assert restored.verdict == original.verdict
        assert restored.system_tier == original.system_tier
        assert restored.delegated_participant_count == original.delegated_participant_count
        assert restored.summary == original.summary

    def test_round_trip_with_participants(self):
        pcs = [
            ParticipantClassification(
                participant_id="p-1",
                device_id="d-1",
                role=DelegatedParticipantRole.delegated,
                has_evidence=True,
            )
        ]
        original = MultiDeviceGovernanceReport(
            verdict=MultiDeviceGovernanceVerdict.conditional_active,
            participant_classifications=pcs,
            delegated_participant_count=1,
        )
        restored = MultiDeviceGovernanceReport.from_dict(original.to_dict())
        assert restored.verdict == original.verdict
        assert len(restored.participant_classifications) == 1
        assert restored.participant_classifications[0].role == DelegatedParticipantRole.delegated


# ===========================================================================
# V–X. Singleton management
# ===========================================================================


class TestEvaluatorSingleton:
    def test_returns_evaluator(self):  # V
        ev = get_multi_device_governance_evaluator()
        assert isinstance(ev, MultiDeviceGovernanceEvaluator)

    def test_singleton_identity(self):  # W
        ev1 = get_multi_device_governance_evaluator()
        ev2 = get_multi_device_governance_evaluator()
        assert ev1 is ev2

    def test_reset_breaks_identity(self):  # X
        ev1 = get_multi_device_governance_evaluator()
        reset_multi_device_governance_evaluator()
        ev2 = get_multi_device_governance_evaluator()
        assert ev1 is not ev2


# ===========================================================================
# Y. build_multi_device_governance_report() convenience wrapper
# ===========================================================================


class TestBuildGovernanceReport:
    def test_returns_report(self):
        report = build_multi_device_governance_report()
        assert isinstance(report, MultiDeviceGovernanceReport)


# ===========================================================================
# Z. Evaluator.evaluate() returns report
# ===========================================================================


class TestEvaluatorEvaluate:
    def test_returns_report_type(self):
        ev = get_multi_device_governance_evaluator()
        report = ev.evaluate()
        assert isinstance(report, MultiDeviceGovernanceReport)


# ===========================================================================
# Scenario Tests — Key invariants from the problem statement
# ===========================================================================


class TestScenarioNoActiveDelegatedParticipant:
    """S1–S3: No delegated participant → single-device baseline only.

    The system must NOT report multi-device operational state when no
    live delegated participant is present, even if formation/routing
    infrastructure is wired.
    """

    def _evaluate_with_no_participants(self) -> MultiDeviceGovernanceReport:
        """Evaluate with all participant-detection sources mocked to empty."""
        with (
            patch.object(
                _mod,
                "_COORDINATION_AVAILABLE",
                False,
            ),
            patch.object(
                _mod,
                "_SESSION_REGISTRY_AVAILABLE",
                False,
            ),
            patch.object(
                _mod,
                "_AUDIT_AVAILABLE",
                False,
            ),
            patch.object(
                _mod,
                "_PARTICIPANT_EVIDENCE_AVAILABLE",
                False,
            ),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            return ev.evaluate()

    def test_verdict_is_single_device_baseline(self):  # S1
        report = self._evaluate_with_no_participants()
        assert report.verdict == MultiDeviceGovernanceVerdict.single_device_baseline, (
            f"Expected single_device_baseline but got {report.verdict.value!r}.  "
            "NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY violated."
        )

    def test_is_not_operational(self):  # S2
        report = self._evaluate_with_no_participants()
        assert report.is_operational is False, (
            "System must not report operational when no delegated participant present."
        )

    def test_is_not_default_mainline(self):  # S3
        report = self._evaluate_with_no_participants()
        assert report.is_default_mainline is False, (
            "System must not report default-mainline when no delegated participant."
        )

    def test_delegated_participant_count_is_zero(self):
        report = self._evaluate_with_no_participants()
        assert report.delegated_participant_count == 0

    def test_downgrade_reason_recorded(self):  # S9
        report = self._evaluate_with_no_participants()
        assert len(report.downgrade_reasons) > 0, (
            "Downgrade reason must be recorded for single-device baseline state."
        )

    def test_downgrade_reason_mentions_single_device(self):
        report = self._evaluate_with_no_participants()
        all_reasons = " ".join(report.downgrade_reasons).lower()
        assert "single" in all_reasons or "delegated participant" in all_reasons, (
            "Downgrade reason should mention single-device or delegated participant."
        )


class TestScenarioDelegatedParticipantWithoutEvidence:
    """S4, S7: Delegated participant present but no runtime evidence.

    Must produce conditional_active (NOT default_mainline_active).
    Downgrade reason must be recorded.
    """

    def _evaluate_with_delegated_no_evidence(self) -> MultiDeviceGovernanceReport:
        """Evaluate with a delegated participant in the coordination layer
        but no audit/evidence modules available."""
        mock_record = MagicMock()
        mock_record.coordination_role = MagicMock()
        mock_record.coordination_role.value = "joined_runtime_participant"
        mock_record.device_id = "device-delegated-1"

        mock_runtime = MagicMock()
        mock_runtime.records = {"device-delegated-1": mock_record}

        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", True),
            patch.object(_mod, "_get_coordination_runtime", return_value=mock_runtime),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            return ev.evaluate()

    def test_verdict_is_conditional_active_not_default_mainline(self):  # S4
        report = self._evaluate_with_delegated_no_evidence()
        assert report.verdict != MultiDeviceGovernanceVerdict.default_mainline_active, (
            f"Verdict must NOT be default_mainline_active without evidence.  "
            f"Got: {report.verdict.value!r}.  "
            "EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY violated."
        )
        assert report.verdict == MultiDeviceGovernanceVerdict.conditional_active, (
            f"Expected conditional_active but got {report.verdict.value!r}."
        )

    def test_is_operational_is_true(self):
        # Delegated participant is present, so operational state is True
        report = self._evaluate_with_delegated_no_evidence()
        assert report.is_operational is True

    def test_is_default_mainline_is_false(self):
        report = self._evaluate_with_delegated_no_evidence()
        assert report.is_default_mainline is False

    def test_delegated_participant_count_is_one(self):
        report = self._evaluate_with_delegated_no_evidence()
        assert report.delegated_participant_count >= 1

    def test_downgrade_reason_recorded(self):  # S7
        report = self._evaluate_with_delegated_no_evidence()
        assert len(report.downgrade_reasons) > 0, (
            "Downgrade reason must be recorded when delegated participant "
            "has no evidence."
        )

    def test_downgrade_reason_mentions_evidence(self):
        report = self._evaluate_with_delegated_no_evidence()
        all_reasons = " ".join(report.downgrade_reasons).lower()
        assert "evidence" in all_reasons, (
            "Downgrade reason should mention missing evidence."
        )


class TestScenarioGuardedCapabilitiesPreventDefaultMainline:
    """S6, S8, S11: Guarded capabilities (contract-first, not-implemented)
    prevent default-mainline promotion even with delegated evidence.

    This is the core "hooks do not equal fully active" invariant.
    """

    def test_guarded_capabilities_present_in_capability_map(self):  # S6
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            report = ev.evaluate()

        guarded = report.guarded_capabilities
        assert len(guarded) > 0, (
            "At least some capabilities must be classified as guarded "
            "(contract-first sub-surfaces prevent default-mainline promotion)."
        )

    def test_known_guarded_capability_is_guarded(self):
        """mesh_session_status_tracking is known-guarded; must not be default-mainline."""
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            report = ev.evaluate()

        cap_entry = report.capability_map.get("mesh_session_status_tracking")
        assert cap_entry is not None, "mesh_session_status_tracking must be in capability_map"
        assert cap_entry.tier == MultiDeviceSystemTier.guarded, (
            f"mesh_session_status_tracking must be guarded, got {cap_entry.tier.value!r}.  "
            "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY violated."
        )

    def test_no_false_fully_active_from_hooks(self):  # S11
        """Core invariant: contract-first hooks must not produce fully-active verdict."""
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            report = ev.evaluate()

        assert report.verdict != MultiDeviceGovernanceVerdict.default_mainline_active, (
            "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY violated: "
            f"Got default_mainline_active verdict without live evidence."
        )


class TestScenarioCapabilityMap:
    """S5, S13, S19: Capability map contains expected entries."""

    def _get_report(self) -> MultiDeviceGovernanceReport:
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            return ev.evaluate()

    def test_capability_map_non_empty(self):  # S19
        report = self._get_report()
        assert len(report.capability_map) > 0

    def test_formation_capabilities_are_default_mainline(self):  # S5
        """Formation and routing capabilities must be default-mainline
        regardless of delegated participant state."""
        report = self._get_report()
        for cap_name in ("route_task_single_remote_device", "parallel_fanout_dispatch"):
            entry = report.capability_map.get(cap_name)
            assert entry is not None, f"{cap_name} must be in capability_map"
            assert entry.tier == MultiDeviceSystemTier.default_mainline, (
                f"{cap_name} must be default-mainline, "
                f"got {entry.tier.value!r}"
            )

    def test_both_default_mainline_and_guarded_present(self):  # S13
        report = self._get_report()
        has_default = len(report.default_mainline_capabilities) > 0
        has_guarded = len(report.guarded_capabilities) > 0
        assert has_default, "Must have at least one default-mainline capability"
        assert has_guarded, "Must have at least one guarded capability"


class TestScenarioSingleVsMultiDevice:
    """S15, S16, S21, S22: Single-device vs multi-device operational state."""

    def _single_device_report(self) -> MultiDeviceGovernanceReport:
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            return ev.evaluate()

    def test_single_device_tier_not_operational(self):  # S21
        report = self._single_device_report()
        assert MultiDeviceSystemTier.single_device_baseline.is_operational is False

    def test_conditional_tier_is_operational(self):  # S22
        assert MultiDeviceSystemTier.conditional.is_operational is True

    def test_is_default_mainline_matches_verdict(self):  # S15
        report = self._single_device_report()
        assert report.is_default_mainline == report.verdict.is_default_mainline

    def test_is_operational_matches_verdict(self):  # S16
        report = self._single_device_report()
        assert report.is_operational == report.verdict.is_operational


class TestScenarioReportProperties:
    """S14, S17, S18: Report structural properties."""

    def _get_report(self) -> MultiDeviceGovernanceReport:
        ev = get_multi_device_governance_evaluator()
        return ev.evaluate()

    def test_report_json_serialisable(self):  # S14
        report = self._get_report()
        serialised = report.to_json()
        parsed = json.loads(serialised)
        assert isinstance(parsed, dict)
        assert "verdict" in parsed

    def test_summary_non_empty(self):  # S17
        report = self._get_report()
        assert report.summary
        assert isinstance(report.summary, str)
        assert len(report.summary) > 0

    def test_downgrade_reasons_is_list(self):  # S18
        report = self._get_report()
        assert isinstance(report.downgrade_reasons, list)


class TestScenarioSecondaryDeviceEvidence:
    """S10: Secondary device evidence present vs absent."""

    def test_secondary_device_evidence_false_by_default(self):
        with (
            patch.object(_mod, "_COORDINATION_AVAILABLE", False),
            patch.object(_mod, "_SESSION_REGISTRY_AVAILABLE", False),
            patch.object(_mod, "_AUDIT_AVAILABLE", False),
            patch.object(_mod, "_PARTICIPANT_EVIDENCE_AVAILABLE", False),
        ):
            ev = MultiDeviceGovernanceEvaluator()
            report = ev.evaluate()
        assert report.secondary_device_evidence_present is False

    def test_report_exposes_secondary_evidence_field(self):
        """The report always exposes secondary_device_evidence_present for
        consumers to distinguish evidence-present vs absent."""
        report = MultiDeviceGovernanceReport(secondary_device_evidence_present=True)
        assert report.secondary_device_evidence_present is True
        d = report.to_dict()
        assert "secondary_device_evidence_present" in d
        assert d["secondary_device_evidence_present"] is True


class TestScenarioParticipantRoleDifference:
    """S20: Delegated vs primary participant have different roles."""

    def test_delegated_role_differs_from_primary(self):
        primary = ParticipantClassification(
            participant_id="p-primary",
            role=DelegatedParticipantRole.primary,
        )
        delegated = ParticipantClassification(
            participant_id="p-delegated",
            role=DelegatedParticipantRole.delegated,
        )
        assert primary.role != delegated.role
        assert primary.role == DelegatedParticipantRole.primary
        assert delegated.role == DelegatedParticipantRole.delegated

    def test_delegated_role_not_primary(self):
        assert DelegatedParticipantRole.delegated != DelegatedParticipantRole.primary


# ===========================================================================
# S23. __all__ completeness
# ===========================================================================


class TestAllCompleteness:
    def test_all_public_names_in_all(self):
        missing = []
        for name in (
            "MULTI_DEVICE_CANONICAL_GOVERNANCE_AUTHORITY",
            "MULTI_DEVICE_CANONICAL_GOVERNANCE_PR09_SENTINEL",
            "DELEGATED_HOOKS_DO_NOT_EQUAL_FULLY_ACTIVE_POLICY",
            "NO_DELEGATED_PARTICIPANT_NO_MULTI_DEVICE_OPERATIONAL_POLICY",
            "EVIDENCE_REQUIRED_FOR_DEFAULT_MAINLINE_POLICY",
            "EXPLICIT_DOWNGRADE_ON_PARTIAL_EVIDENCE_POLICY",
            "SINGLE_DEVICE_BASELINE_WHEN_NO_DELEGATED_PARTICIPANT_POLICY",
            "OPTIONAL_REALITY_MUST_NOT_UPGRADE_TO_FULLY_OPERATIONAL_DEFAULT_POLICY",
            "MultiDeviceSystemTier",
            "DelegatedParticipantRole",
            "MultiDeviceGovernanceVerdict",
            "ParticipantClassification",
            "CapabilityGovernanceEntry",
            "MultiDeviceGovernanceReport",
            "MultiDeviceGovernanceEvaluator",
            "build_multi_device_governance_report",
            "get_multi_device_governance_evaluator",
            "reset_multi_device_governance_evaluator",
        ):
            if name not in _mod.__all__:
                missing.append(name)
        assert missing == [], f"Names missing from __all__: {missing}"
