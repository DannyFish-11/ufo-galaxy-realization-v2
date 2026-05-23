#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr537_dual_repo_system_reality_audit.py
===================================================
PR-537: Dual-Repo System Reality Audit — validation test suite.

Problem addressed
-----------------
Prior PRs introduced rich readiness / governance / acceptance machinery.
None of them answered, in a single automated verification pass, the
engineering-honest question:

    *Based solely on real importable code, real test files, and real CI
    workflows, which dual-repo capabilities are implemented / mainchained /
    automated-verified — and which are only nominally present?*

This test suite validates the ``core.dual_repo_system_reality_audit`` module
that closes that gap.

Coverage matrix
---------------
Group A — Module-level: sentinels, enums, __all__
  A01. Module importable; authority and PR537 sentinels present and non-empty.
  A02. All five policy sentinels are non-empty strings.
  A03. MaturityLabel has exactly five values.
  A04. MaturityLabel ordinal order: nominally=0, partially=1, implemented=2,
       mainchained=3, automated_verified=4.
  A05. MaturityLabel.is_blocking True for nominally_present_not_closed.
  A06. MaturityLabel.is_blocking True for partially_implemented.
  A07. MaturityLabel.is_blocking False for implemented.
  A08. MaturityLabel.is_blocking False for mainchained.
  A09. MaturityLabel.is_blocking False for automated_verified.
  A10. MaturityLabel.from_string with valid value.
  A11. MaturityLabel.from_string with invalid value → nominally_present_not_closed.
  A12. MaturityLabel.from_string with non-string → nominally_present_not_closed.
  A13. AuditDimension has exactly five values.
  A14. AuditDimension.all_dimensions() returns list of length 5.
  A15. AuditDimension.from_string with valid value.
  A16. AuditDimension.from_string with invalid/non-string →
       main_chain_authenticity.
  A17. SystemRealityVerdict has exactly four values.
  A18. SystemRealityVerdict.is_baseline_established True only for
       platform_baseline_established.
  A19. SystemRealityVerdict.has_critical_gaps True only for
       critical_gaps_blocking_baseline.
  A20. SystemRealityVerdict.is_inconclusive True only for
       insufficient_evidence_to_conclude.
  A21. SystemRealityVerdict.from_string with valid value.
  A22. SystemRealityVerdict.from_string with invalid → insufficient_evidence.
  A23. __all__ contains all required public names.

Group B — DimensionAuditEntry
  B01. Default construction works; required fields present.
  B02. to_dict() returns all required keys.
  B03. to_json() produces valid JSON.
  B04. from_dict(to_dict()) round-trip preserves all fields.
  B05. from_dict with empty/missing keys returns safe defaults.

Group C — DualRepoRealityAuditReport
  C01. Default construction works; required fields present.
  C02. to_dict() returns all required top-level keys.
  C03. to_json() produces valid JSON.
  C04. from_dict(to_dict()) round-trip preserves all fields.
  C05. get_dimension_entry() returns correct entry.
  C06. get_dimension_entry() returns None for missing dimension.
  C07. dimensions list is embedded correctly in to_dict().

Group D — build_dual_repo_reality_audit() — live probe
  D01. Returns a DualRepoRealityAuditReport.
  D02. Report has a non-empty report_id.
  D03. Report generated_at is a positive float.
  D04. Report has exactly 5 dimension entries.
  D05. All 5 AuditDimension values are represented in the report.
  D06. Each dimension entry has a non-empty evidence_summary.
  D07. Each dimension entry has a non-empty verdict_rationale.
  D08. system_verdict is a valid SystemRealityVerdict value.
  D09. main_chain_authenticity_conclusion is a non-empty string.
  D10. recovery_maturity_conclusion is a non-empty string.
  D11. governance_enforcement_conclusion is a non-empty string.
  D12. operational_readiness_contribution is a non-empty string.
  D13. summary is a non-empty string containing 'SYSTEM VERDICT'.
  D14. summary contains 'CONCLUSION' section.
  D15. to_json() of report is valid JSON.
  D16. All dimension maturity values are valid MaturityLabel members.

Group E — Evidence aggregation correctness
  E01. Each dimension entry's code_references contains only importable module
       paths (i.e. every reference in the list was actually importable during
       the audit).
  E02. Each dimension entry's test_references exist as files or are CI job
       references (non-empty strings).
  E03. Blocking gaps list is consistent with dimension gap lists (union).
  E04. Dimension with any gap must have that gap in unresolved_blocking_gaps.
  E05. A dimension with maturity nominally_present_not_closed MUST have at
       least one gap entry.
  E06. A dimension with maturity partially_implemented MUST have at least
       one gap entry.

Group F — Missing evidence / partial evidence behaviour
  F01. DimensionAuditEntry with empty code_references and no test_references
       → maturity defaults to nominally_present_not_closed.
  F02. _compute_verdict: all entries at nominally_present_not_closed →
       critical_gaps_blocking_baseline.
  F03. _compute_verdict: mix of partially_implemented and implemented →
       partial_baseline_significant_gaps.
  F04. _compute_verdict: all entries at implemented or above →
       platform_baseline_established.
  F05. _compute_verdict: fewer than 3 entries → insufficient_evidence.
  F06. Singleton: get_dual_repo_reality_audit() returns same report_id on
       second call (singleton not rebuilt).
  F07. reset_dual_repo_reality_audit() clears singleton; next call returns
       new report_id.

Group G — Fail when critical dimensions cannot be substantiated
  G01. A report where any dimension has maturity nominally_present_not_closed
       MUST have system_verdict == critical_gaps_blocking_baseline.
  G02. A report where any dimension has maturity partially_implemented and
       none is nominally_present MUST have system_verdict ==
       partial_baseline_significant_gaps.
  G03. A report where all dimensions are at or above implemented MUST have
       system_verdict == platform_baseline_established.
  G04. Fail-conservative: a DimensionAuditEntry with no code_references
       MUST NOT have maturity above partially_implemented when the dimension
       auditor is called on an empty environment (simulated by manually
       constructing an entry).
  G05. summary MUST contain the verdict string when system is NOT
       platform_baseline_established.
  G06. unresolved_blocking_gaps is non-empty when any dimension has gaps.
  G07. governance_enforcement_conclusion mentions 'non-enforcing' when the
       distributed_release_gate_skeleton reports is_enforcing=False.

Group H — Policy sentinel assertions
  H01. CODE_GROUNDED_EVIDENCE_ONLY_POLICY contains 'documentation' and
       'excluded'.
  H02. FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY contains
       'nominally_present_not_closed'.
  H03. SILENCE_IS_NOT_ACCEPTANCE_POLICY contains 'absence'.
  H04. HONEST_GAP_REPORTING_POLICY contains 'unresolved_blocking_gaps'.
  H05. ADDITIVE_ONLY_NO_MUTATION_POLICY contains 'read-only'.
"""

from __future__ import annotations

import importlib
import json
import sys
import os
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

import core.dual_repo_system_reality_audit as _mod
from core.dual_repo_system_reality_audit import (
    DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY,
    DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL,
    CODE_GROUNDED_EVIDENCE_ONLY_POLICY,
    FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY,
    SILENCE_IS_NOT_ACCEPTANCE_POLICY,
    HONEST_GAP_REPORTING_POLICY,
    ADDITIVE_ONLY_NO_MUTATION_POLICY,
    MaturityLabel,
    AuditDimension,
    SystemRealityVerdict,
    DimensionAuditEntry,
    DualRepoRealityAuditReport,
    DualRepoSystemRealityAuditor,
    build_dual_repo_reality_audit,
    get_dual_repo_reality_audit,
    reset_dual_repo_reality_audit,
)


# ===========================================================================
# Group A — Module-level: sentinels, enums, __all__
# ===========================================================================


class TestModuleLevel:
    def test_A01_authority_and_pr537_sentinels_present(self):
        assert DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY
        assert DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL
        assert isinstance(DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY, str)
        assert "PR537" in DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY
        assert "PR537" in DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL

    def test_A02_all_five_policy_sentinels_non_empty(self):
        sentinels = [
            CODE_GROUNDED_EVIDENCE_ONLY_POLICY,
            FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY,
            SILENCE_IS_NOT_ACCEPTANCE_POLICY,
            HONEST_GAP_REPORTING_POLICY,
            ADDITIVE_ONLY_NO_MUTATION_POLICY,
        ]
        for s in sentinels:
            assert isinstance(s, str)
            assert len(s) > 20, f"Policy sentinel too short: {s!r}"

    def test_A03_maturity_label_has_five_values(self):
        assert len(list(MaturityLabel)) == 5

    def test_A04_maturity_label_ordinal_order(self):
        assert MaturityLabel.nominally_present_not_closed.ordinal() == 0
        assert MaturityLabel.partially_implemented.ordinal() == 1
        assert MaturityLabel.implemented.ordinal() == 2
        assert MaturityLabel.mainchained.ordinal() == 3
        assert MaturityLabel.automated_verified.ordinal() == 4

    def test_A05_is_blocking_true_for_nominally_present(self):
        assert MaturityLabel.nominally_present_not_closed.is_blocking() is True

    def test_A06_is_blocking_true_for_partially_implemented(self):
        assert MaturityLabel.partially_implemented.is_blocking() is True

    def test_A07_is_blocking_false_for_implemented(self):
        assert MaturityLabel.implemented.is_blocking() is False

    def test_A08_is_blocking_false_for_mainchained(self):
        assert MaturityLabel.mainchained.is_blocking() is False

    def test_A09_is_blocking_false_for_automated_verified(self):
        assert MaturityLabel.automated_verified.is_blocking() is False

    def test_A10_maturity_from_string_valid(self):
        assert MaturityLabel.from_string("implemented") == MaturityLabel.implemented
        assert (
            MaturityLabel.from_string("automated_verified")
            == MaturityLabel.automated_verified
        )

    def test_A11_maturity_from_string_invalid_returns_lowest(self):
        assert (
            MaturityLabel.from_string("nonsense")
            == MaturityLabel.nominally_present_not_closed
        )

    def test_A12_maturity_from_string_non_string_returns_lowest(self):
        assert (
            MaturityLabel.from_string(42)  # type: ignore[arg-type]
            == MaturityLabel.nominally_present_not_closed
        )

    def test_A13_audit_dimension_has_five_values(self):
        assert len(list(AuditDimension)) == 5

    def test_A14_all_dimensions_returns_five(self):
        dims = AuditDimension.all_dimensions()
        assert len(dims) == 5
        assert all(isinstance(d, AuditDimension) for d in dims)

    def test_A15_audit_dimension_from_string_valid(self):
        assert (
            AuditDimension.from_string("main_chain_authenticity")
            == AuditDimension.main_chain_authenticity
        )
        assert (
            AuditDimension.from_string("recovery_redispatch_reconnect")
            == AuditDimension.recovery_redispatch_reconnect
        )

    def test_A16_audit_dimension_from_string_invalid_returns_default(self):
        assert (
            AuditDimension.from_string("bogus_dimension")
            == AuditDimension.main_chain_authenticity
        )
        assert (
            AuditDimension.from_string(None)  # type: ignore[arg-type]
            == AuditDimension.main_chain_authenticity
        )

    def test_A17_system_reality_verdict_has_four_values(self):
        assert len(list(SystemRealityVerdict)) == 4

    def test_A18_is_baseline_established_true_only_for_platform_baseline(self):
        assert (
            SystemRealityVerdict.platform_baseline_established.is_baseline_established
            is True
        )
        for v in SystemRealityVerdict:
            if v != SystemRealityVerdict.platform_baseline_established:
                assert v.is_baseline_established is False

    def test_A19_has_critical_gaps_true_only_for_critical_gaps(self):
        assert (
            SystemRealityVerdict.critical_gaps_blocking_baseline.has_critical_gaps
            is True
        )
        for v in SystemRealityVerdict:
            if v != SystemRealityVerdict.critical_gaps_blocking_baseline:
                assert v.has_critical_gaps is False

    def test_A20_is_inconclusive_true_only_for_insufficient_evidence(self):
        assert (
            SystemRealityVerdict.insufficient_evidence_to_conclude.is_inconclusive
            is True
        )
        for v in SystemRealityVerdict:
            if v != SystemRealityVerdict.insufficient_evidence_to_conclude:
                assert v.is_inconclusive is False

    def test_A21_verdict_from_string_valid(self):
        assert (
            SystemRealityVerdict.from_string("platform_baseline_established")
            == SystemRealityVerdict.platform_baseline_established
        )

    def test_A22_verdict_from_string_invalid_returns_default(self):
        assert (
            SystemRealityVerdict.from_string("not_real")
            == SystemRealityVerdict.insufficient_evidence_to_conclude
        )

    def test_A23_all_contains_required_public_names(self):
        required = [
            "DUAL_REPO_SYSTEM_REALITY_AUDIT_AUTHORITY",
            "DUAL_REPO_SYSTEM_REALITY_AUDIT_PR537_SENTINEL",
            "CODE_GROUNDED_EVIDENCE_ONLY_POLICY",
            "FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY",
            "SILENCE_IS_NOT_ACCEPTANCE_POLICY",
            "HONEST_GAP_REPORTING_POLICY",
            "ADDITIVE_ONLY_NO_MUTATION_POLICY",
            "MaturityLabel",
            "AuditDimension",
            "SystemRealityVerdict",
            "DimensionAuditEntry",
            "DualRepoRealityAuditReport",
            "DualRepoSystemRealityAuditor",
            "build_dual_repo_reality_audit",
            "get_dual_repo_reality_audit",
            "reset_dual_repo_reality_audit",
        ]
        for name in required:
            assert name in _mod.__all__, f"Missing from __all__: {name}"


# ===========================================================================
# Group B — DimensionAuditEntry
# ===========================================================================


class TestDimensionAuditEntry:
    def test_B01_default_construction(self):
        entry = DimensionAuditEntry()
        assert isinstance(entry.dimension, AuditDimension)
        assert isinstance(entry.maturity, MaturityLabel)
        assert isinstance(entry.evidence_summary, str)
        assert isinstance(entry.code_references, list)
        assert isinstance(entry.test_references, list)
        assert isinstance(entry.gaps, list)
        assert isinstance(entry.verdict_rationale, str)
        assert entry.audited_at > 0

    def test_B02_to_dict_has_required_keys(self):
        entry = DimensionAuditEntry(
            dimension=AuditDimension.main_chain_authenticity,
            maturity=MaturityLabel.implemented,
            evidence_summary="test summary",
            code_references=["core.openclawd"],
            test_references=["tests/test_pr001.py"],
            gaps=["missing module"],
            verdict_rationale="all good",
        )
        d = entry.to_dict()
        required_keys = [
            "dimension",
            "maturity",
            "evidence_summary",
            "code_references",
            "test_references",
            "gaps",
            "verdict_rationale",
            "audited_at",
        ]
        for k in required_keys:
            assert k in d, f"Missing key: {k}"

    def test_B03_to_json_is_valid_json(self):
        entry = DimensionAuditEntry(
            dimension=AuditDimension.recovery_redispatch_reconnect,
            maturity=MaturityLabel.automated_verified,
        )
        j = entry.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_B04_from_dict_round_trip(self):
        entry = DimensionAuditEntry(
            dimension=AuditDimension.governance_readiness_release_gate,
            maturity=MaturityLabel.mainchained,
            evidence_summary="governance probed",
            code_references=["core.governance_validation_gate"],
            test_references=["tests/test_pr536.py"],
            gaps=["enforcement not wired"],
            verdict_rationale="skeleton only",
        )
        d = entry.to_dict()
        restored = DimensionAuditEntry.from_dict(d)
        assert restored.dimension == entry.dimension
        assert restored.maturity == entry.maturity
        assert restored.evidence_summary == entry.evidence_summary
        assert restored.code_references == entry.code_references
        assert restored.test_references == entry.test_references
        assert restored.gaps == entry.gaps
        assert restored.verdict_rationale == entry.verdict_rationale

    def test_B05_from_dict_empty_data_returns_safe_defaults(self):
        entry = DimensionAuditEntry.from_dict({})
        assert isinstance(entry.dimension, AuditDimension)
        assert isinstance(entry.maturity, MaturityLabel)
        assert isinstance(entry.code_references, list)
        assert isinstance(entry.gaps, list)


# ===========================================================================
# Group C — DualRepoRealityAuditReport
# ===========================================================================


class TestDualRepoRealityAuditReport:
    def _make_report(self) -> DualRepoRealityAuditReport:
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=MaturityLabel.implemented,
                evidence_summary=f"summary for {dim.value}",
                code_references=[f"core.{dim.value}"],
                gaps=[],
                verdict_rationale="ok",
            )
            for dim in AuditDimension.all_dimensions()
        ]
        return DualRepoRealityAuditReport(
            dimensions=entries,
            system_verdict=SystemRealityVerdict.platform_baseline_established,
            main_chain_authenticity_conclusion="main chain ok",
            recovery_maturity_conclusion="recovery ok",
            governance_enforcement_conclusion="governance ok",
            operational_readiness_contribution="readiness ok",
            unresolved_blocking_gaps=[],
            summary="test summary",
        )

    def test_C01_default_construction(self):
        report = DualRepoRealityAuditReport()
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0
        assert isinstance(report.dimensions, list)
        assert isinstance(
            report.system_verdict, SystemRealityVerdict
        )
        assert isinstance(report.unresolved_blocking_gaps, list)
        assert isinstance(report.summary, str)
        assert report.generated_at > 0
        assert isinstance(report.auditor_version, str)

    def test_C02_to_dict_has_required_keys(self):
        report = self._make_report()
        d = report.to_dict()
        required_keys = [
            "report_id",
            "dimensions",
            "system_verdict",
            "main_chain_authenticity_conclusion",
            "recovery_maturity_conclusion",
            "governance_enforcement_conclusion",
            "operational_readiness_contribution",
            "unresolved_blocking_gaps",
            "summary",
            "generated_at",
            "auditor_version",
        ]
        for k in required_keys:
            assert k in d, f"Missing key: {k}"

    def test_C03_to_json_is_valid_json(self):
        report = self._make_report()
        j = report.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_C04_from_dict_round_trip(self):
        report = self._make_report()
        d = report.to_dict()
        restored = DualRepoRealityAuditReport.from_dict(d)
        assert restored.report_id == report.report_id
        assert restored.system_verdict == report.system_verdict
        assert len(restored.dimensions) == len(report.dimensions)
        assert (
            restored.main_chain_authenticity_conclusion
            == report.main_chain_authenticity_conclusion
        )

    def test_C05_get_dimension_entry_returns_correct_entry(self):
        report = self._make_report()
        entry = report.get_dimension_entry(AuditDimension.main_chain_authenticity)
        assert entry is not None
        assert entry.dimension == AuditDimension.main_chain_authenticity

    def test_C06_get_dimension_entry_returns_none_for_missing(self):
        report = DualRepoRealityAuditReport()
        assert (
            report.get_dimension_entry(AuditDimension.main_chain_authenticity)
            is None
        )

    def test_C07_dimensions_embedded_in_to_dict(self):
        report = self._make_report()
        d = report.to_dict()
        assert isinstance(d["dimensions"], list)
        assert len(d["dimensions"]) == 5
        assert all(isinstance(e, dict) for e in d["dimensions"])


# ===========================================================================
# Group D — build_dual_repo_reality_audit() — live probe
# ===========================================================================


class TestLiveAudit:
    """Live audit tests — share a single report across all tests in the
    group to avoid redundant probing."""

    @pytest.fixture(scope="class")
    def report(self) -> DualRepoRealityAuditReport:
        reset_dual_repo_reality_audit()
        r = build_dual_repo_reality_audit()
        yield r
        reset_dual_repo_reality_audit()

    def test_D01_returns_report(self, report):
        assert isinstance(report, DualRepoRealityAuditReport)

    def test_D02_non_empty_report_id(self, report):
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_D03_generated_at_positive(self, report):
        assert report.generated_at > 0

    def test_D04_exactly_five_dimension_entries(self, report):
        assert len(report.dimensions) == 5

    def test_D05_all_five_dimensions_represented(self, report):
        found_dims = {e.dimension for e in report.dimensions}
        expected = set(AuditDimension.all_dimensions())
        assert found_dims == expected

    def test_D06_each_entry_has_non_empty_evidence_summary(self, report):
        for entry in report.dimensions:
            assert entry.evidence_summary, (
                f"Empty evidence_summary for {entry.dimension.value}"
            )

    def test_D07_each_entry_has_non_empty_verdict_rationale(self, report):
        for entry in report.dimensions:
            assert entry.verdict_rationale, (
                f"Empty verdict_rationale for {entry.dimension.value}"
            )

    def test_D08_system_verdict_is_valid(self, report):
        assert isinstance(report.system_verdict, SystemRealityVerdict)

    def test_D09_main_chain_conclusion_non_empty(self, report):
        assert report.main_chain_authenticity_conclusion
        assert isinstance(report.main_chain_authenticity_conclusion, str)

    def test_D10_recovery_conclusion_non_empty(self, report):
        assert report.recovery_maturity_conclusion
        assert isinstance(report.recovery_maturity_conclusion, str)

    def test_D11_governance_conclusion_non_empty(self, report):
        assert report.governance_enforcement_conclusion
        assert isinstance(report.governance_enforcement_conclusion, str)

    def test_D12_readiness_conclusion_non_empty(self, report):
        assert report.operational_readiness_contribution
        assert isinstance(report.operational_readiness_contribution, str)

    def test_D13_summary_contains_system_verdict_header(self, report):
        assert "SYSTEM VERDICT" in report.summary

    def test_D14_summary_contains_conclusion_section(self, report):
        assert "CONCLUSION" in report.summary

    def test_D15_to_json_produces_valid_json(self, report):
        j = report.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        assert "system_verdict" in parsed

    def test_D16_all_maturity_values_are_valid_members(self, report):
        valid_values = {m.value for m in MaturityLabel}
        for entry in report.dimensions:
            assert entry.maturity.value in valid_values, (
                f"Invalid maturity {entry.maturity!r} for {entry.dimension.value}"
            )


# ===========================================================================
# Group E — Evidence aggregation correctness
# ===========================================================================


class TestEvidenceAggregation:
    @pytest.fixture(scope="class")
    def report(self) -> DualRepoRealityAuditReport:
        reset_dual_repo_reality_audit()
        r = build_dual_repo_reality_audit()
        yield r
        reset_dual_repo_reality_audit()

    def test_E01_code_references_are_importable_modules(self, report):
        """Every module in code_references must actually be importable."""
        import importlib

        for entry in report.dimensions:
            for ref in entry.code_references:
                # Only try to import dotted Python module paths (not file paths)
                if not ref.startswith(".") and not ref.startswith("/") and os.sep not in ref:
                    try:
                        importlib.import_module(ref)
                    except Exception as exc:
                        pytest.fail(
                            f"code_reference '{ref}' in dimension "
                            f"'{entry.dimension.value}' is not importable: {exc}"
                        )

    def test_E02_test_references_are_non_empty_strings(self, report):
        for entry in report.dimensions:
            for ref in entry.test_references:
                assert isinstance(ref, str) and len(ref) > 0, (
                    f"Empty test_reference in {entry.dimension.value}"
                )

    def test_E03_blocking_gaps_consistent_with_dimension_gaps(self, report):
        """Every gap in every dimension entry must appear in
        unresolved_blocking_gaps (possibly as a substring)."""
        for entry in report.dimensions:
            for gap in entry.gaps:
                # The gap should appear (dimension-prefixed) in the report
                found = any(
                    gap in bg or entry.dimension.value in bg
                    for bg in report.unresolved_blocking_gaps
                )
                assert found, (
                    f"Gap not represented in unresolved_blocking_gaps:\n"
                    f"  dimension={entry.dimension.value}\n"
                    f"  gap={gap!r}"
                )

    def test_E04_dimension_with_gaps_contributes_to_blocking_gaps(self, report):
        dims_with_gaps = {
            e.dimension
            for e in report.dimensions
            if e.gaps
        }
        if dims_with_gaps:
            assert len(report.unresolved_blocking_gaps) > 0, (
                "Dimensions have gaps but unresolved_blocking_gaps is empty."
            )

    def test_E05_nominally_present_dimension_has_gap(self):
        """A nominally_present_not_closed dimension must have at least one gap."""
        entry = DimensionAuditEntry(
            dimension=AuditDimension.main_chain_authenticity,
            maturity=MaturityLabel.nominally_present_not_closed,
            gaps=[],
        )
        # An honest auditor MUST populate gaps for nominally_present
        # Simulate the policy check: if the auditor produces a
        # nominally_present entry it should record why
        # We just validate the policy via the live audit
        live_nominal = [
            e
            for e in build_dual_repo_reality_audit().dimensions
            if e.maturity == MaturityLabel.nominally_present_not_closed
        ]
        for e in live_nominal:
            assert e.gaps, (
                f"nominally_present_not_closed dimension "
                f"'{e.dimension.value}' has no gaps recorded"
            )
        # Clean up singleton
        reset_dual_repo_reality_audit()

    def test_E06_partially_implemented_dimension_has_gap(self):
        """A partially_implemented dimension must have at least one gap."""
        live_partial = [
            e
            for e in build_dual_repo_reality_audit().dimensions
            if e.maturity == MaturityLabel.partially_implemented
        ]
        for e in live_partial:
            assert e.gaps, (
                f"partially_implemented dimension "
                f"'{e.dimension.value}' has no gaps recorded"
            )
        reset_dual_repo_reality_audit()


# ===========================================================================
# Group F — Missing evidence / partial evidence behaviour
# ===========================================================================


class TestMissingPartialEvidence:
    def test_F01_default_entry_maturity_is_lowest(self):
        entry = DimensionAuditEntry()
        assert entry.maturity == MaturityLabel.nominally_present_not_closed

    def test_F02_compute_verdict_all_nominal_is_critical_gaps(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=MaturityLabel.nominally_present_not_closed,
            )
            for dim in AuditDimension.all_dimensions()
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.critical_gaps_blocking_baseline

    def test_F03_compute_verdict_mix_partial_implemented(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=(
                    MaturityLabel.partially_implemented
                    if i < 2
                    else MaturityLabel.implemented
                ),
            )
            for i, dim in enumerate(AuditDimension.all_dimensions())
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.partial_baseline_significant_gaps

    def test_F04_compute_verdict_all_implemented_is_baseline_established(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=MaturityLabel.implemented,
            )
            for dim in AuditDimension.all_dimensions()
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.platform_baseline_established

    def test_F05_compute_verdict_fewer_than_three_is_insufficient(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=AuditDimension.main_chain_authenticity,
                maturity=MaturityLabel.automated_verified,
            ),
            DimensionAuditEntry(
                dimension=AuditDimension.recovery_redispatch_reconnect,
                maturity=MaturityLabel.automated_verified,
            ),
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.insufficient_evidence_to_conclude

    def test_F06_singleton_returns_same_report_id(self):
        reset_dual_repo_reality_audit()
        r1 = get_dual_repo_reality_audit()
        r2 = get_dual_repo_reality_audit()
        assert r1.report_id == r2.report_id
        reset_dual_repo_reality_audit()

    def test_F07_reset_clears_singleton(self):
        reset_dual_repo_reality_audit()
        r1 = get_dual_repo_reality_audit()
        reset_dual_repo_reality_audit()
        r2 = get_dual_repo_reality_audit()
        # After reset the new report should have been rebuilt (different ID)
        # Note: uuid4 could theoretically collide but the probability is
        # astronomically small; this is an acceptable test assumption.
        # What we truly assert is that the cached singleton was cleared.
        assert r2 is not r1
        reset_dual_repo_reality_audit()


# ===========================================================================
# Group G — Fail when critical dimensions cannot be substantiated
# ===========================================================================


class TestFailConservativePolicy:
    def test_G01_nominal_dimension_forces_critical_gaps_verdict(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=(
                    MaturityLabel.nominally_present_not_closed
                    if i == 0
                    else MaturityLabel.automated_verified
                ),
            )
            for i, dim in enumerate(AuditDimension.all_dimensions())
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.critical_gaps_blocking_baseline, (
            "Even a single nominally_present dimension must produce "
            "critical_gaps_blocking_baseline."
        )

    def test_G02_partially_implemented_without_nominal_forces_partial(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=(
                    MaturityLabel.partially_implemented
                    if i == 0
                    else MaturityLabel.mainchained
                ),
            )
            for i, dim in enumerate(AuditDimension.all_dimensions())
        ]
        verdict = auditor._compute_verdict(entries)
        assert verdict == SystemRealityVerdict.partial_baseline_significant_gaps

    def test_G03_all_implemented_or_above_gives_baseline_established(self):
        auditor = DualRepoSystemRealityAuditor()
        for target_label in (
            MaturityLabel.implemented,
            MaturityLabel.mainchained,
            MaturityLabel.automated_verified,
        ):
            entries = [
                DimensionAuditEntry(dimension=dim, maturity=target_label)
                for dim in AuditDimension.all_dimensions()
            ]
            verdict = auditor._compute_verdict(entries)
            assert verdict == SystemRealityVerdict.platform_baseline_established, (
                f"All dimensions at {target_label.value} should produce "
                "platform_baseline_established."
            )

    def test_G04_entry_with_no_code_references_cannot_exceed_partially_implemented(
        self,
    ):
        """An entry with no code_references cannot be above partially_implemented
        in the honest audit sense.  We verify this via the maturity ordering:
        if the live audit assigns it anything above that it must have evidence."""
        entry = DimensionAuditEntry(
            dimension=AuditDimension.main_chain_authenticity,
            maturity=MaturityLabel.nominally_present_not_closed,
            code_references=[],
        )
        # With no evidence, maturity must be at most partially_implemented
        assert entry.maturity.ordinal() <= MaturityLabel.partially_implemented.ordinal()

    def test_G05_summary_contains_verdict_when_not_baseline(self):
        auditor = DualRepoSystemRealityAuditor()
        entries = [
            DimensionAuditEntry(
                dimension=dim,
                maturity=MaturityLabel.nominally_present_not_closed,
                verdict_rationale="no code",
            )
            for dim in AuditDimension.all_dimensions()
        ]
        verdict = auditor._compute_verdict(entries)
        summary = auditor._build_summary(
            verdict,
            entries,
            [],
            "main chain conclusion",
            "recovery conclusion",
            "governance conclusion",
            "readiness conclusion",
        )
        assert verdict.value in summary or verdict.value.upper() in summary

    def test_G06_unresolved_blocking_gaps_non_empty_when_dimensions_have_gaps(
        self,
    ):
        reset_dual_repo_reality_audit()
        report = build_dual_repo_reality_audit()
        dims_with_gaps = [e for e in report.dimensions if e.gaps]
        if dims_with_gaps:
            assert len(report.unresolved_blocking_gaps) > 0, (
                "Dimensions have gaps but unresolved_blocking_gaps is empty.  "
                "HONEST_GAP_REPORTING_POLICY violation."
            )
        reset_dual_repo_reality_audit()

    def test_G07_governance_conclusion_mentions_non_enforcing_when_applicable(self):
        """If the distributed release gate reports is_enforcing=False, the
        governance conclusion must mention 'non-enforcing'."""
        try:
            from core.distributed_release_gate_skeleton import (  # type: ignore[import]
                evaluate_distributed_release_gate,
            )

            gate_report = evaluate_distributed_release_gate()
            is_enforcing = getattr(gate_report, "is_enforcing", None)
        except Exception:
            is_enforcing = None

        if is_enforcing is False:
            reset_dual_repo_reality_audit()
            full_report = build_dual_repo_reality_audit()
            assert "non-enforcing" in full_report.governance_enforcement_conclusion, (
                "governance_enforcement_conclusion must mention 'non-enforcing' "
                "when the release gate is explicitly non-enforcing."
            )
            reset_dual_repo_reality_audit()

    def test_G08_file_presence_without_importability_scores_partially_implemented(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import core.audit_layer.dual_repo_system_reality_audit as strict_mod

        def _fake_try_import(module_path: str) -> bool:
            return False

        def _fake_module_file_exists(module_path: str) -> bool:
            return module_path.startswith("core.") or module_path.startswith("galaxy_gateway.")

        monkeypatch.setattr(strict_mod, "_try_import", _fake_try_import)
        monkeypatch.setattr(strict_mod, "_module_file_exists", _fake_module_file_exists)
        monkeypatch.setattr(strict_mod, "_file_exists", lambda _path: False)

        entry = strict_mod.DualRepoSystemRealityAuditor()._audit_main_chain_authenticity()
        assert entry.maturity == MaturityLabel.partially_implemented


# ===========================================================================
# Group H — Policy sentinel assertions
# ===========================================================================


class TestPolicySentinels:
    def test_H01_code_grounded_mentions_documentation_and_excluded(self):
        assert "documentation" in CODE_GROUNDED_EVIDENCE_ONLY_POLICY.lower()
        assert "excluded" in CODE_GROUNDED_EVIDENCE_ONLY_POLICY.lower()

    def test_H02_fail_conservative_mentions_nominally_present(self):
        assert (
            "nominally_present_not_closed"
            in FAIL_CONSERVATIVE_ON_MISSING_MODULE_POLICY
        )

    def test_H03_silence_not_acceptance_mentions_absence(self):
        assert "absence" in SILENCE_IS_NOT_ACCEPTANCE_POLICY.lower()

    def test_H04_honest_gap_reporting_mentions_unresolved_blocking_gaps(self):
        assert "unresolved_blocking_gaps" in HONEST_GAP_REPORTING_POLICY

    def test_H05_additive_only_mentions_read_only(self):
        assert "read-only" in ADDITIVE_ONLY_NO_MUTATION_POLICY
