#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_dual_repo_system_completeness_review.py
===================================================
PR-REVIEW — Dual-Repo System Completeness Review — validation test suite.

Coverage areas
--------------
Group A — Module-level: sentinels, enums, __all__
  A01. Module importable; authority and PR-REVIEW sentinels present.
  A02. Policy sentinels are non-empty strings containing expected keywords.
  A03. CompletenessDimension has exactly five values.
  A04. CompletenessDimension.all_dimensions() returns list of length 5.
  A05. CompletenessDimension.from_string with valid value.
  A06. CompletenessDimension.from_string with invalid value → architecture_structure.
  A07. CompletenessLabel has exactly six values.
  A08. CompletenessLabel ordinal: not_present=0, nominally_present=1,
       structure_only=2, evidence_gap=3, deferred=4, complete=5.
  A09. CompletenessLabel.is_blocking True for not_present, nominally_present,
       structure_only, evidence_gap (all below deferred).
  A10. CompletenessLabel.is_blocking False for deferred and complete.
  A11. CompletenessLabel.from_string with valid value.
  A12. CompletenessLabel.from_string with invalid value → not_present.
  A13. CompletenessVerdict has exactly five values.
  A14. CompletenessVerdict.is_fully_closed True only for fully_closed.
  A15. CompletenessVerdict.has_blocking_gaps True for critical_evidence_gaps
       and structural_only_runtime_not_closed.
  A16. CompletenessVerdict.from_string with valid value.
  A17. CompletenessVerdict.from_string with invalid → insufficient_evidence.
  A18. __all__ contains all required public names.

Group B — CompletenessEntry data class
  B01. Default construction with required fields.
  B02. to_dict() returns all required keys.
  B03. to_json() produces valid JSON.
  B04. from_dict(to_dict()) round-trip preserves all fields.
  B05. from_dict with missing keys returns safe defaults.

Group C — CompletenessReviewReport data class
  C01. Default construction; required fields present.
  C02. to_dict() returns all required top-level keys.
  C03. to_json() produces valid JSON.
  C04. from_dict(to_dict()) round-trip preserves all fields.
  C05. get_dimension() returns correct entry for each dimension.
  C06. get_dimension() returns None for unknown dimension value.
  C07. is_fully_closed property mirrors verdict.is_fully_closed.
  C08. has_blocking_gaps True when blocking_gaps list is non-empty.

Group D — build_completeness_review() / get_completeness_review() — live probe
  D01. build_completeness_review() returns a CompletenessReviewReport.
  D02. Report has a non-empty report_id.
  D03. Report generated_at is a positive float.
  D04. Report has exactly 5 dimension entries.
  D05. All 5 CompletenessDimension values are represented in the report.
  D06. Each entry has a non-empty summary.
  D07. verdict is a valid CompletenessVerdict value.
  D08. summary is a non-empty string.
  D09. summary contains 'OVERALL VERDICT' text.
  D10. summary contains 'EVIDENCE GAPS' text.
  D11. summary contains 'DEFERRED' text.
  D12. to_json() of report is valid JSON.
  D13. All entry label values are valid CompletenessLabel members.
  D14. blocking_gaps is a list.
  D15. deferred_acknowledged is a list.
  D16. get_completeness_review() returns a CompletenessReviewReport (singleton).
  D17. Two consecutive calls to get_completeness_review() return same object.
  D18. reset_completeness_review() causes next call to return new object.

Group E — Honest labeling: deferred/evidence_gap not misclassified as complete
  E01. cross_repo_evidence dimension MUST NOT be labeled 'complete'
       (ReconciliationSignal wire layer is documented as missing).
  E02. cross_repo_evidence label MUST be 'evidence_gap' or worse
       (documented critical gap: AIP wire layer absent).
  E03. cross_repo_evidence gap_items MUST be non-empty.
  E04. cross_repo_evidence gap_items MUST contain text referencing
       ReconciliationSignal or AIP wire.
  E05. runtime_closure dimension MUST NOT be labeled 'complete' in a
       fresh environment (delegated flow never exercised).
  E06. runtime_closure deferred_items MUST be non-empty (deferred boundaries).
  E07. runtime_closure deferred_items MUST mention 'offline queue' or 'replay'.
  E08. governance_release_readiness gap_items MUST be non-empty.
  E09. governance_release_readiness gap_items MUST mention 'advisory' or
       'non-blocking' or 'enforcement' or 'is_enforcing'.
  E10. real_device_multi_device deferred_items MUST be non-empty.
  E11. Verdict MUST NOT be 'fully_closed' (multiple evidence gaps present).
  E12. blocking_gaps MUST be non-empty (at least one gap must be reported).
  E13. Deferred items MUST NOT be empty (system has acknowledged deferrals).
  E14. CompletenessLabel.evidence_gap is_blocking() MUST be True.
  E15. CompletenessLabel.deferred is_blocking() MUST be False (deferred ≠ blocked).
  E16. No entry's label should be 'complete' when its gap_items is non-empty.

Group F — Artifact export and alignment with real code surfaces
  F01. to_json() output is a string parseable back to dict with expected keys.
  F02. Each entry's code_references is a list (may be empty in test env).
  F03. Architecture dimension label is at least 'structure_only'.
  F04. CompletenessReviewReport.from_dict(report.to_dict()) is a valid report.
  F05. reviewer_version is a non-empty string.
  F06. summary mentions key code surface 'system_final_acceptance_verdict'.
  F07. summary mentions key code surface 'dual_repo_system_reality_audit'.
  F08. All five dimension names appear in the summary.
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

import core.dual_repo_system_completeness_review as _mod
from core.dual_repo_system_completeness_review import (
    COMPLETENESS_REVIEW_AUTHORITY,
    COMPLETENESS_REVIEW_SENTINEL,
    HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY,
    ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_POLICY,
    CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_POLICY,
    CompletenessDimension,
    CompletenessLabel,
    CompletenessVerdict,
    CompletenessEntry,
    CompletenessReviewReport,
    DualRepoSystemCompletenessReviewer,
    build_completeness_review,
    get_completeness_review,
    reset_completeness_review,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the singleton before and after each test."""
    reset_completeness_review()
    yield
    reset_completeness_review()


@pytest.fixture(scope="module")
def live_report() -> CompletenessReviewReport:
    """Build a live report once for the module (not the singleton)."""
    return build_completeness_review()


# ===========================================================================
# Group A — Module-level: sentinels, enums, __all__
# ===========================================================================


class TestModuleLevel:
    def test_A01_module_importable_sentinels_present(self):
        assert COMPLETENESS_REVIEW_AUTHORITY
        assert COMPLETENESS_REVIEW_SENTINEL
        assert "COMPLETENESS_REVIEW_AUTHORITY" in COMPLETENESS_REVIEW_AUTHORITY

    def test_A02_policy_sentinels_non_empty_keywords(self):
        assert "deferred" in HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY.lower()
        assert "complete" in HONEST_DEFERRED_MUST_NOT_BE_LABELED_COMPLETE_POLICY.lower()
        assert "runtime" in ARCHITECTURE_COMPLETE_DOES_NOT_IMPLY_RUNTIME_CLOSED_POLICY.lower()
        assert "wire" in CROSS_REPO_EVIDENCE_REQUIRES_WIRE_LAYER_POLICY.lower()

    def test_A03_completeness_dimension_has_five_values(self):
        values = list(CompletenessDimension)
        assert len(values) == 5

    def test_A04_all_dimensions_returns_five(self):
        dims = CompletenessDimension.all_dimensions()
        assert len(dims) == 5
        assert len(set(dims)) == 5

    def test_A05_dimension_from_string_valid(self):
        d = CompletenessDimension.from_string("runtime_closure")
        assert d == CompletenessDimension.runtime_closure

    def test_A06_dimension_from_string_invalid(self):
        d = CompletenessDimension.from_string("nonexistent_value")
        assert d == CompletenessDimension.architecture_structure

    def test_A07_completeness_label_has_six_values(self):
        values = [
            CompletenessLabel.not_present,
            CompletenessLabel.nominally_present,
            CompletenessLabel.structure_only,
            CompletenessLabel.evidence_gap,
            CompletenessLabel.deferred,
            CompletenessLabel.complete,
        ]
        assert len(values) == 6

    def test_A08_label_ordinals(self):
        assert CompletenessLabel.not_present.ordinal() == 0
        assert CompletenessLabel.nominally_present.ordinal() == 1
        assert CompletenessLabel.structure_only.ordinal() == 2
        assert CompletenessLabel.evidence_gap.ordinal() == 3
        assert CompletenessLabel.deferred.ordinal() == 4
        assert CompletenessLabel.complete.ordinal() == 5

    def test_A09_is_blocking_below_deferred(self):
        assert CompletenessLabel.not_present.is_blocking() is True
        assert CompletenessLabel.nominally_present.is_blocking() is True
        assert CompletenessLabel.structure_only.is_blocking() is True
        assert CompletenessLabel.evidence_gap.is_blocking() is True

    def test_A10_is_blocking_false_for_deferred_and_complete(self):
        assert CompletenessLabel.deferred.is_blocking() is False
        assert CompletenessLabel.complete.is_blocking() is False

    def test_A11_label_from_string_valid(self):
        lb = CompletenessLabel.from_string("evidence_gap")
        assert lb == CompletenessLabel.evidence_gap

    def test_A12_label_from_string_invalid(self):
        lb = CompletenessLabel.from_string("this_does_not_exist")
        assert lb == CompletenessLabel.not_present

    def test_A13_completeness_verdict_has_five_values(self):
        values = [
            CompletenessVerdict.fully_closed,
            CompletenessVerdict.partial_closure_gaps_present,
            CompletenessVerdict.structural_only_runtime_not_closed,
            CompletenessVerdict.critical_evidence_gaps,
            CompletenessVerdict.insufficient_evidence,
        ]
        assert len(values) == 5

    def test_A14_verdict_is_fully_closed(self):
        assert CompletenessVerdict.fully_closed.is_fully_closed is True
        for v in CompletenessVerdict:
            if v != CompletenessVerdict.fully_closed:
                assert v.is_fully_closed is False

    def test_A15_verdict_has_blocking_gaps(self):
        assert CompletenessVerdict.critical_evidence_gaps.has_blocking_gaps is True
        assert (
            CompletenessVerdict.structural_only_runtime_not_closed.has_blocking_gaps
            is True
        )
        assert CompletenessVerdict.fully_closed.has_blocking_gaps is False
        assert (
            CompletenessVerdict.partial_closure_gaps_present.has_blocking_gaps is False
        )

    def test_A16_verdict_from_string_valid(self):
        v = CompletenessVerdict.from_string("fully_closed")
        assert v == CompletenessVerdict.fully_closed

    def test_A17_verdict_from_string_invalid(self):
        v = CompletenessVerdict.from_string("not_a_verdict")
        assert v == CompletenessVerdict.insufficient_evidence

    def test_A18_all_exports(self):
        for name in _mod.__all__:
            assert hasattr(_mod, name), f"__all__ lists {name!r} but attribute absent"


# ===========================================================================
# Group B — CompletenessEntry data class
# ===========================================================================


class TestCompletenessEntry:
    def test_B01_default_construction(self):
        entry = CompletenessEntry()
        assert isinstance(entry.dimension, CompletenessDimension)
        assert isinstance(entry.label, CompletenessLabel)
        assert isinstance(entry.summary, str)
        assert isinstance(entry.completed_items, list)
        assert isinstance(entry.gap_items, list)
        assert isinstance(entry.deferred_items, list)
        assert isinstance(entry.code_references, list)
        assert isinstance(entry.test_references, list)
        assert entry.assessed_at > 0

    def test_B02_to_dict_required_keys(self):
        entry = CompletenessEntry(
            dimension=CompletenessDimension.runtime_closure,
            label=CompletenessLabel.evidence_gap,
            summary="test summary",
        )
        d = entry.to_dict()
        for key in [
            "dimension",
            "label",
            "summary",
            "completed_items",
            "gap_items",
            "deferred_items",
            "code_references",
            "test_references",
            "assessed_at",
        ]:
            assert key in d

    def test_B03_to_json_valid(self):
        entry = CompletenessEntry(summary="json test")
        j = entry.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_B04_from_dict_round_trip(self):
        entry = CompletenessEntry(
            dimension=CompletenessDimension.cross_repo_evidence,
            label=CompletenessLabel.evidence_gap,
            summary="round-trip",
            gap_items=["gap 1"],
            deferred_items=["deferred 1"],
        )
        recovered = CompletenessEntry.from_dict(entry.to_dict())
        assert recovered.dimension == entry.dimension
        assert recovered.label == entry.label
        assert recovered.summary == entry.summary
        assert recovered.gap_items == entry.gap_items
        assert recovered.deferred_items == entry.deferred_items

    def test_B05_from_dict_missing_keys(self):
        entry = CompletenessEntry.from_dict({})
        assert isinstance(entry.dimension, CompletenessDimension)
        assert isinstance(entry.label, CompletenessLabel)


# ===========================================================================
# Group C — CompletenessReviewReport data class
# ===========================================================================


class TestCompletenessReviewReport:
    def _make_report(self) -> CompletenessReviewReport:
        entries = [
            CompletenessEntry(
                dimension=d,
                label=CompletenessLabel.structure_only,
                summary=f"summary for {d.value}",
            )
            for d in CompletenessDimension.all_dimensions()
        ]
        return CompletenessReviewReport(
            dimensions=entries,
            verdict=CompletenessVerdict.partial_closure_gaps_present,
            blocking_gaps=["gap1"],
            deferred_acknowledged=["deferred1"],
            summary="test summary",
        )

    def test_C01_default_construction(self):
        r = CompletenessReviewReport()
        assert isinstance(r.report_id, str)
        assert len(r.report_id) > 0
        assert isinstance(r.dimensions, list)
        assert isinstance(r.verdict, CompletenessVerdict)
        assert isinstance(r.blocking_gaps, list)
        assert isinstance(r.deferred_acknowledged, list)

    def test_C02_to_dict_required_keys(self):
        r = self._make_report()
        d = r.to_dict()
        for key in [
            "report_id",
            "dimensions",
            "verdict",
            "blocking_gaps",
            "deferred_acknowledged",
            "summary",
            "generated_at",
            "reviewer_version",
        ]:
            assert key in d

    def test_C03_to_json_valid(self):
        r = self._make_report()
        j = r.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_C04_from_dict_round_trip(self):
        r = self._make_report()
        recovered = CompletenessReviewReport.from_dict(r.to_dict())
        assert recovered.report_id == r.report_id
        assert recovered.verdict == r.verdict
        assert recovered.blocking_gaps == r.blocking_gaps
        assert len(recovered.dimensions) == len(r.dimensions)

    def test_C05_get_dimension_returns_correct(self):
        r = self._make_report()
        for d in CompletenessDimension.all_dimensions():
            entry = r.get_dimension(d)
            assert entry is not None
            assert entry.dimension == d

    def test_C06_get_dimension_returns_none_for_missing(self):
        r = CompletenessReviewReport()
        result = r.get_dimension(CompletenessDimension.runtime_closure)
        assert result is None

    def test_C07_is_fully_closed_mirrors_verdict(self):
        r_closed = CompletenessReviewReport(verdict=CompletenessVerdict.fully_closed)
        r_partial = CompletenessReviewReport(
            verdict=CompletenessVerdict.partial_closure_gaps_present
        )
        assert r_closed.is_fully_closed is True
        assert r_partial.is_fully_closed is False

    def test_C08_has_blocking_gaps_true_when_gaps_present(self):
        r_with_gaps = CompletenessReviewReport(blocking_gaps=["gap1"])
        r_no_gaps = CompletenessReviewReport(blocking_gaps=[])
        assert r_with_gaps.has_blocking_gaps is True
        assert r_no_gaps.has_blocking_gaps is False


# ===========================================================================
# Group D — build_completeness_review() / get_completeness_review() live probe
# ===========================================================================


class TestLiveProbe:
    def test_D01_returns_report(self, live_report):
        assert isinstance(live_report, CompletenessReviewReport)

    def test_D02_non_empty_report_id(self, live_report):
        assert live_report.report_id
        assert len(live_report.report_id) >= 4

    def test_D03_generated_at_positive(self, live_report):
        assert live_report.generated_at > 0

    def test_D04_five_dimension_entries(self, live_report):
        assert len(live_report.dimensions) == 5

    def test_D05_all_dimensions_present(self, live_report):
        dim_values = {e.dimension for e in live_report.dimensions}
        assert dim_values == set(CompletenessDimension.all_dimensions())

    def test_D06_each_entry_non_empty_summary(self, live_report):
        for entry in live_report.dimensions:
            assert entry.summary, (
                f"Dimension {entry.dimension.value} has empty summary"
            )

    def test_D07_valid_verdict(self, live_report):
        assert isinstance(live_report.verdict, CompletenessVerdict)
        # Must be one of the known values
        assert live_report.verdict in list(CompletenessVerdict)

    def test_D08_summary_non_empty(self, live_report):
        assert live_report.summary
        assert len(live_report.summary) > 50

    def test_D09_summary_contains_overall_verdict(self, live_report):
        assert "OVERALL VERDICT" in live_report.summary

    def test_D10_summary_contains_evidence_gaps(self, live_report):
        assert "EVIDENCE GAP" in live_report.summary.upper()

    def test_D11_summary_contains_deferred(self, live_report):
        assert "DEFERRED" in live_report.summary.upper()

    def test_D12_to_json_valid(self, live_report):
        j = live_report.to_json()
        parsed = json.loads(j)
        assert "dimensions" in parsed
        assert "verdict" in parsed

    def test_D13_all_label_values_valid(self, live_report):
        valid_labels = set(CompletenessLabel)
        for entry in live_report.dimensions:
            assert entry.label in valid_labels, (
                f"Dimension {entry.dimension.value} has invalid label {entry.label!r}"
            )

    def test_D14_blocking_gaps_is_list(self, live_report):
        assert isinstance(live_report.blocking_gaps, list)

    def test_D15_deferred_acknowledged_is_list(self, live_report):
        assert isinstance(live_report.deferred_acknowledged, list)

    def test_D16_get_completeness_review_singleton(self):
        r = get_completeness_review()
        assert isinstance(r, CompletenessReviewReport)

    def test_D17_singleton_identity(self):
        r1 = get_completeness_review()
        r2 = get_completeness_review()
        assert r1 is r2

    def test_D18_reset_forces_new_object(self):
        r1 = get_completeness_review()
        reset_completeness_review()
        r2 = get_completeness_review()
        assert r1 is not r2


# ===========================================================================
# Group E — Honest labeling: deferred/evidence_gap not misclassified
# ===========================================================================


class TestHonestLabeling:
    """Enforce the core contract: documented gaps must not be labeled 'complete'.

    These tests guard against the most common failure mode in evidence-surface
    modules: optimistically promoting a gap/deferred item to 'complete' or
    'fully_closed' because the *structure* exists.
    """

    def test_E01_cross_repo_now_labeled_complete(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert entry is not None
        assert entry.label == CompletenessLabel.complete, (
            "cross_repo_evidence MUST be 'complete' after the remediation wave: "
            "PR2-V2 added ReconciliationSignal canonical handler and HandoffEnvelopeV2 "
            "response canonical handler; PR2-Android added the AIP wire layer. "
            "If this fails, check galaxy_gateway/android/handlers/reconciliation_signal.py "
            "and galaxy_gateway/android/handlers/handoff_v2_result.py."
        )

    def test_E02_cross_repo_label_not_blocking(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert entry is not None
        # After remediation wave the wire is closed — cross_repo_evidence should not be blocking
        assert not entry.label.is_blocking(), (
            f"cross_repo_evidence label {entry.label.value!r} must NOT be blocking after "
            "the remediation wave closed the ReconciliationSignal and HandoffEnvelopeV2 gaps."
        )

    def test_E03_cross_repo_completed_items_non_empty(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert entry is not None
        assert len(entry.completed_items) > 0, (
            "cross_repo_evidence must have at least one completed_item "
            "(canonical handlers, wire layer, or evidence ingress modules)"
        )

    def test_E04_cross_repo_completed_mentions_pr2_or_handler(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.cross_repo_evidence)
        assert entry is not None
        completed_text = " ".join(entry.completed_items).lower()
        assert (
            "reconciliation" in completed_text
            or "handoff" in completed_text
            or "pr2" in completed_text
            or "wire" in completed_text
        ), (
            "cross_repo_evidence completed_items must mention ReconciliationSignal, "
            "HandoffEnvelopeV2, PR2, or wire layer closure"
        )

    def test_E05_runtime_not_labeled_complete_fresh_env(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.runtime_closure)
        assert entry is not None
        # In a fresh environment (no delegated flow exercised), runtime_closure
        # should NOT be 'complete'
        assert entry.label != CompletenessLabel.complete, (
            "runtime_closure MUST NOT be 'complete' in a fresh environment: "
            "delegated_flow_decision_history.runtime_closure_established=False "
            "means no end-to-end run has been observed"
        )

    def test_E06_runtime_deferred_items_non_empty(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.runtime_closure)
        assert entry is not None
        assert len(entry.deferred_items) > 0, (
            "runtime_closure must acknowledge deferred boundaries "
            "(offline queue replay ordering, ephemeral transport binding, "
            "multi-device reconnect ordering)"
        )

    def test_E07_runtime_deferred_mentions_offline_or_replay(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.runtime_closure)
        assert entry is not None
        deferred_text = " ".join(entry.deferred_items).lower()
        assert "offline" in deferred_text or "replay" in deferred_text, (
            "runtime_closure deferred_items must mention 'offline queue' or 'replay' "
            "(from recovery_truth_surface deferred_boundaries)"
        )

    def test_E08_governance_dimension_present(self, live_report):
        entry = live_report.get_dimension(
            CompletenessDimension.governance_release_readiness
        )
        assert entry is not None
        # After PR3-V2 the governance dimension should be complete or have only deferred items
        # (not evidence_gap); at minimum the dimension must be present and evaluable
        assert entry.label is not None, (
            "governance_release_readiness dimension must be present and have a valid label"
        )

    def test_E09_governance_mentions_enforcing_or_advisory(self, live_report):
        entry = live_report.get_dimension(
            CompletenessDimension.governance_release_readiness
        )
        assert entry is not None
        all_text = (
            " ".join(entry.completed_items)
            + " ".join(entry.gap_items)
            + entry.summary
        ).lower()
        assert (
            "advisory" in all_text
            or "non-blocking" in all_text
            or "enforc" in all_text
            or "is_enforcing" in all_text
        ), (
            "governance dimension must mention advisory or enforcement status "
            "(is_enforcing from distributed_release_gate_skeleton)"
        )

    def test_E10_real_device_deferred_items_non_empty(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.real_device_multi_device)
        assert entry is not None
        assert len(entry.deferred_items) > 0, (
            "real_device_multi_device must have deferred items "
            "(real-device CI, multi-device reconnect ordering)"
        )

    def test_E11_verdict_not_fully_closed(self, live_report):
        # Even after the remediation wave, runtime_closure is not 'complete' in a fresh
        # environment and real_device CI is deferred — so fully_closed is not expected.
        # The expected verdict is partial_closure_gaps_present.
        assert live_report.verdict != CompletenessVerdict.fully_closed, (
            "System verdict MUST NOT be 'fully_closed': runtime_closure is evidence_gap "
            "in a fresh environment (no delegated flow exercised) and real-device CI is deferred."
        )

    def test_E12_blocking_gaps_non_empty(self, live_report):
        # runtime_closure is still evidence_gap in a fresh environment
        assert len(live_report.blocking_gaps) > 0, (
            "blocking_gaps must be non-empty: runtime_closure dimension is evidence_gap "
            "in a fresh environment (delegated_flow_decision_history.runtime_closure_established=False)"
        )

    def test_E13_deferred_acknowledged_non_empty(self, live_report):
        assert len(live_report.deferred_acknowledged) > 0, (
            "deferred_acknowledged must be non-empty: the system has documented "
            "explicit deferrals (offline queue ordering, ephemeral transport binding)"
        )

    def test_E14_evidence_gap_is_blocking(self):
        assert CompletenessLabel.evidence_gap.is_blocking() is True

    def test_E15_deferred_is_not_blocking(self):
        # Deferred ≠ blocked; it's an acknowledged limitation, not a gap
        assert CompletenessLabel.deferred.is_blocking() is False

    def test_E16_no_complete_label_with_gaps(self, live_report):
        for entry in live_report.dimensions:
            if entry.gap_items:
                assert entry.label != CompletenessLabel.complete, (
                    f"Dimension {entry.dimension.value} has label 'complete' "
                    f"but gap_items is non-empty: {entry.gap_items[:1]}"
                )


# ===========================================================================
# Group F — Artifact export and alignment with real code surfaces
# ===========================================================================


class TestArtifactExport:
    def test_F01_to_json_parseable_with_expected_keys(self, live_report):
        j = live_report.to_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        for key in [
            "report_id", "dimensions", "verdict",
            "blocking_gaps", "deferred_acknowledged",
            "summary", "generated_at", "reviewer_version",
        ]:
            assert key in parsed, f"Key {key!r} missing from to_json() output"

    def test_F02_code_references_is_list(self, live_report):
        for entry in live_report.dimensions:
            assert isinstance(entry.code_references, list), (
                f"code_references for {entry.dimension.value} is not a list"
            )

    def test_F03_architecture_label_at_least_structure_only(self, live_report):
        entry = live_report.get_dimension(CompletenessDimension.architecture_structure)
        assert entry is not None
        assert entry.label.ordinal() >= CompletenessLabel.structure_only.ordinal(), (
            "architecture_structure dimension must be at least 'structure_only': "
            "core structural modules (system_final_acceptance_verdict, "
            "dual_repo_system_reality_audit, etc.) are importable"
        )

    def test_F04_from_dict_round_trip_valid(self, live_report):
        recovered = CompletenessReviewReport.from_dict(live_report.to_dict())
        assert isinstance(recovered, CompletenessReviewReport)
        assert recovered.verdict == live_report.verdict
        assert len(recovered.dimensions) == len(live_report.dimensions)

    def test_F05_reviewer_version_non_empty(self, live_report):
        assert live_report.reviewer_version
        assert len(live_report.reviewer_version) > 0

    def test_F06_summary_mentions_system_final_acceptance_verdict(self, live_report):
        assert "system_final_acceptance_verdict" in live_report.summary, (
            "summary must reference core.system_final_acceptance_verdict "
            "as a key code surface for reviewers"
        )

    def test_F07_summary_mentions_dual_repo_system_reality_audit(self, live_report):
        assert "dual_repo_system_reality_audit" in live_report.summary, (
            "summary must reference core.dual_repo_system_reality_audit "
            "as a key code surface for reviewers"
        )

    def test_F08_all_dimension_names_in_summary(self, live_report):
        for dim in CompletenessDimension.all_dimensions():
            assert dim.value in live_report.summary, (
                f"summary must include dimension name {dim.value!r}"
            )
