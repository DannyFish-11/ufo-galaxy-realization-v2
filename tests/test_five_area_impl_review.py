"""
tests/test_five_area_impl_review.py
====================================
Test suite for core/five_area_impl_review.py

Five-Area Implementation-Grade Joint Dual-Repo Review Artifact.

This test suite validates:
 1.  Module imports cleanly; all public symbols accessible.
 2.  Authority, methodology, and policy sentinels are non-empty.
 3.  Authority sentinel contains the canonical prefix.
 4.  Policy sentinel contains NO_PROSE_AS_EVIDENCE.
 5.  Enumerations have the correct number of members.
 6.  build_five_area_impl_review() returns a structurally correct report.
 7.  Report has exactly 5 area entries (one per ReviewArea).
 8.  All 5 ReviewArea values are represented in the report.
 9.  No area is overclaimed (STRONGLY_ESTABLISHED/RUNTIME_EVIDENCED_CLOSED with gaps).
10.  Every area has at least one importable code anchor OR at least one partial anchor.
11.  Every area has a non-empty canonical_path_summary.
12.  Every area has at least one established_item.
13.  Every area below STRONGLY_ESTABLISHED has at least one gap_item.
14.  Every area has at least one impl_cut_point.
15.  Every area has at least one modification_zone.
16.  Every area has a non-None maturity_unlock.
17.  Every area has a non-empty maturity_unlock_description.
18.  overall_summary is non-empty and mentions all 5 area identifiers.
19.  next_pr_priority_order has exactly 5 items, all valid ReviewArea values.
20.  assert_five_area_review_invariants() passes cleanly.
21.  Report serialises to JSON cleanly and round-trips with correct structure.
22.  Singleton caching + reset work correctly.
23.  UNIFIED_PANEL_AGGREGATION area is PARTIALLY_ESTABLISHED.
24.  DESKTOP_THREE_STATE_EXISTENCE area is PARTIALLY_ESTABLISHED.
25.  OPERATOR_ACTIONABILITY area is OBSERVATION_ONLY_NO_ACTION_SURFACE.
26.  NATURAL_LANGUAGE_CANONICAL_PATH area is PARTIALLY_ESTABLISHED.
27.  MULTIMODAL_CANONICAL_PATH area is INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN.
28.  UNIFIED_PANEL_AGGREGATION has a gap about no unified aggregation endpoint.
29.  DESKTOP_THREE_STATE_EXISTENCE has a gap about no unified three-state surface.
30.  OPERATOR_ACTIONABILITY has a gap about no action endpoints.
31.  NATURAL_LANGUAGE_CANONICAL_PATH has a gap about no NL e2e CI test.
32.  MULTIMODAL_CANONICAL_PATH has a gap about disabled-by-default or missing e2e test.
33.  UNIFIED_PANEL_AGGREGATION actionability is READ_ONLY_PROJECTION.
34.  OPERATOR_ACTIONABILITY actionability is READ_ONLY_PROJECTION.
35.  NATURAL_LANGUAGE_CANONICAL_PATH actionability is ACTION_CAPABLE.
36.  MULTIMODAL_CANONICAL_PATH actionability is ACTION_CAPABLE.
37.  UNIFIED_PANEL_AGGREGATION maturity_unlock is PANEL_STATE_UNIFIED.
38.  DESKTOP_THREE_STATE_EXISTENCE maturity_unlock is DESKTOP_ASSISTANT_PRESENCE.
39.  OPERATOR_ACTIONABILITY maturity_unlock is OPERATOR_ACTION_CAPABLE.
40.  NATURAL_LANGUAGE_CANONICAL_PATH maturity_unlock is NL_E2E_CI_PROVEN.
41.  MULTIMODAL_CANONICAL_PATH maturity_unlock is MULTIMODAL_E2E_ACTIVATED.
42.  UNIFIED_PANEL_AGGREGATION impl_cut_points contain at least one new_module or new_endpoint.
43.  OPERATOR_ACTIONABILITY impl_cut_points contain at least one new_endpoint.
44.  NATURAL_LANGUAGE_CANONICAL_PATH impl_cut_points contain at least one test_only.
45.  MULTIMODAL_CANONICAL_PATH impl_cut_points contain at least one test_only or wire_existing.
46.  CodeAnchor.to_dict() contains all required keys.
47.  ImplCutPoint.to_dict() contains all required keys.
48.  ModificationZone.to_dict() contains all required keys.
49.  AreaReviewEntry.to_dict() contains all required keys including the 8 content fields.
50.  FiveAreaImplReview.to_dict() contains all required top-level keys.
51.  ReviewArea has exactly 5 members.
52.  AreaMaturityLabel has exactly 8 members.
53.  ActionabilityLevel has exactly 3 members.
54.  FollowUpPrMaturityUnlock has exactly 5 members.
55.  All 5 FollowUpPrMaturityUnlock values appear as maturity_unlock in the entries.
56.  Each area has at least one code anchor with repo == "v2".
57.  MULTIMODAL_CANONICAL_PATH has at least one android_evidence_ref.
58.  OPERATOR_ACTIONABILITY code anchors include the operator route module.
59.  next_pr_priority_order starts with UNIFIED_PANEL_AGGREGATION.
60.  next_pr_priority_order ends with MULTIMODAL_CANONICAL_PATH.

Methodology
-----------
- Only imports the five_area_impl_review module and standard library — no mocking.
- Validates structural correctness and invariants.
- Does NOT mock or override the module's real-code probes.
"""

from __future__ import annotations

import json

import pytest

from core.five_area_impl_review import (
    FIVE_AREA_REVIEW_AUTHORITY,
    FIVE_AREA_REVIEW_METHODOLOGY,
    FIVE_AREA_REVIEW_POLICY_NO_PROSE_AS_EVIDENCE,
    ActionabilityLevel,
    AreaMaturityLabel,
    AreaReviewEntry,
    CodeAnchor,
    FiveAreaImplReview,
    FollowUpPrMaturityUnlock,
    ImplCutPoint,
    ModificationZone,
    ReviewArea,
    assert_five_area_review_invariants,
    build_five_area_impl_review,
    get_five_area_impl_review,
    reset_five_area_impl_review,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(FIVE_AREA_REVIEW_AUTHORITY, str)
        assert len(FIVE_AREA_REVIEW_AUTHORITY) > 0

    def test_authority_contains_canonical_prefix(self) -> None:
        assert FIVE_AREA_REVIEW_AUTHORITY.startswith(
            "FIVE_AREA_IMPL_REVIEW_AUTHORITY"
        )

    def test_authority_contains_dual_repo_phrase(self) -> None:
        assert "dual-repo" in FIVE_AREA_REVIEW_AUTHORITY

    def test_methodology_is_non_empty(self) -> None:
        assert isinstance(FIVE_AREA_REVIEW_METHODOLOGY, str)
        assert len(FIVE_AREA_REVIEW_METHODOLOGY) > 0

    def test_methodology_mentions_five_areas(self) -> None:
        assert "five" in FIVE_AREA_REVIEW_METHODOLOGY.lower()

    def test_policy_sentinel_contains_no_prose_as_evidence(self) -> None:
        assert "NO_PROSE_AS_EVIDENCE" in FIVE_AREA_REVIEW_POLICY_NO_PROSE_AS_EVIDENCE

    def test_policy_sentinel_mentions_overclaiming(self) -> None:
        assert "overclaiming" in FIVE_AREA_REVIEW_POLICY_NO_PROSE_AS_EVIDENCE.lower()


# =============================================================================
# SECTION 2 — Enumeration membership
# =============================================================================


class TestEnumerations:
    """Enumerations must have the correct number of members."""

    def test_review_area_has_five_members(self) -> None:
        assert len(ReviewArea) == 5

    def test_review_area_values(self) -> None:
        expected = {
            "UNIFIED_PANEL_AGGREGATION",
            "DESKTOP_THREE_STATE_EXISTENCE",
            "OPERATOR_ACTIONABILITY",
            "NATURAL_LANGUAGE_CANONICAL_PATH",
            "MULTIMODAL_CANONICAL_PATH",
        }
        assert {a.value for a in ReviewArea} == expected

    def test_area_maturity_label_has_eight_members(self) -> None:
        assert len(AreaMaturityLabel) == 8

    def test_area_maturity_label_values(self) -> None:
        expected = {
            "STRONGLY_ESTABLISHED",
            "RUNTIME_EVIDENCED_CLOSED",
            "PARTIALLY_ESTABLISHED",
            "INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN",
            "OBSERVATION_ONLY_NO_ACTION_SURFACE",
            "SURFACE_ALIGNMENT_ONLY",
            "MISSING_RUNTIME_EVIDENCE",
            "NOT_YET_IMPLEMENTED",
        }
        assert {a.value for a in AreaMaturityLabel} == expected

    def test_actionability_level_has_three_members(self) -> None:
        assert len(ActionabilityLevel) == 3

    def test_actionability_level_values(self) -> None:
        expected = {
            "READ_ONLY_PROJECTION",
            "DECISION_CONSUMED",
            "ACTION_CAPABLE",
        }
        assert {a.value for a in ActionabilityLevel} == expected

    def test_follow_up_pr_maturity_unlock_has_five_members(self) -> None:
        assert len(FollowUpPrMaturityUnlock) == 5

    def test_follow_up_pr_maturity_unlock_values(self) -> None:
        expected = {
            "PANEL_STATE_UNIFIED",
            "DESKTOP_ASSISTANT_PRESENCE",
            "OPERATOR_ACTION_CAPABLE",
            "NL_E2E_CI_PROVEN",
            "MULTIMODAL_E2E_ACTIVATED",
        }
        assert {a.value for a in FollowUpPrMaturityUnlock} == expected


# =============================================================================
# SECTION 3 — Build and report structure
# =============================================================================


class TestBuildReport:
    """build_five_area_impl_review() must return a structurally correct report."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def test_returns_five_area_impl_review_instance(
        self, review: FiveAreaImplReview
    ) -> None:
        assert isinstance(review, FiveAreaImplReview)

    def test_has_exactly_five_area_entries(self, review: FiveAreaImplReview) -> None:
        assert len(review.area_entries) == 5

    def test_all_review_areas_represented(self, review: FiveAreaImplReview) -> None:
        seen = {e.area for e in review.area_entries}
        assert seen == set(ReviewArea)

    def test_authority_matches_module_constant(
        self, review: FiveAreaImplReview
    ) -> None:
        assert review.authority == FIVE_AREA_REVIEW_AUTHORITY

    def test_methodology_matches_module_constant(
        self, review: FiveAreaImplReview
    ) -> None:
        assert review.methodology == FIVE_AREA_REVIEW_METHODOLOGY

    def test_report_id_is_non_empty_string(self, review: FiveAreaImplReview) -> None:
        assert isinstance(review.report_id, str)
        assert len(review.report_id) > 0

    def test_generated_at_is_positive_float(
        self, review: FiveAreaImplReview
    ) -> None:
        assert isinstance(review.generated_at, float)
        assert review.generated_at > 0

    def test_overall_summary_is_non_empty(self, review: FiveAreaImplReview) -> None:
        assert len(review.overall_summary) > 0

    def test_overall_summary_mentions_all_areas(
        self, review: FiveAreaImplReview
    ) -> None:
        summary = review.overall_summary
        for area in ReviewArea:
            assert area.value in summary, (
                f"overall_summary does not mention {area.value}"
            )

    def test_next_pr_priority_order_has_five_items(
        self, review: FiveAreaImplReview
    ) -> None:
        assert len(review.next_pr_priority_order) == 5

    def test_next_pr_priority_order_all_valid_review_area_values(
        self, review: FiveAreaImplReview
    ) -> None:
        valid = {a.value for a in ReviewArea}
        for item in review.next_pr_priority_order:
            assert item in valid, f"{item!r} is not a valid ReviewArea value"

    def test_next_pr_priority_order_starts_with_unified_panel(
        self, review: FiveAreaImplReview
    ) -> None:
        assert review.next_pr_priority_order[0] == ReviewArea.UNIFIED_PANEL_AGGREGATION.value

    def test_next_pr_priority_order_ends_with_multimodal(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            review.next_pr_priority_order[-1] == ReviewArea.MULTIMODAL_CANONICAL_PATH.value
        )

    def test_next_pr_priority_rationale_is_non_empty(
        self, review: FiveAreaImplReview
    ) -> None:
        assert len(review.next_pr_priority_rationale) > 0


# =============================================================================
# SECTION 4 — Per-area maturity labels
# =============================================================================


class TestAreaMaturityLabels:
    """Each area must carry the correct maturity label."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def _get(self, review: FiveAreaImplReview, area: ReviewArea) -> AreaReviewEntry:
        entry = review.get_area(area)
        assert entry is not None, f"Entry for {area.value} not found"
        return entry

    def test_unified_panel_aggregation_is_partially_established(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.UNIFIED_PANEL_AGGREGATION)
        assert entry.maturity_label == AreaMaturityLabel.PARTIALLY_ESTABLISHED

    def test_desktop_three_state_existence_is_partially_established(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.DESKTOP_THREE_STATE_EXISTENCE)
        assert entry.maturity_label == AreaMaturityLabel.PARTIALLY_ESTABLISHED

    def test_operator_actionability_is_observation_only(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.OPERATOR_ACTIONABILITY)
        assert (
            entry.maturity_label
            == AreaMaturityLabel.OBSERVATION_ONLY_NO_ACTION_SURFACE
        )

    def test_nl_canonical_path_is_partially_established(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH)
        assert entry.maturity_label == AreaMaturityLabel.PARTIALLY_ESTABLISHED

    def test_multimodal_canonical_path_is_infra_not_e2e_proven(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.MULTIMODAL_CANONICAL_PATH)
        assert (
            entry.maturity_label
            == AreaMaturityLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        )


# =============================================================================
# SECTION 5 — Per-area actionability levels
# =============================================================================


class TestAreaActionabilityLevels:
    """Each area must carry the correct actionability level."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def _get(self, review: FiveAreaImplReview, area: ReviewArea) -> AreaReviewEntry:
        entry = review.get_area(area)
        assert entry is not None
        return entry

    def test_unified_panel_aggregation_is_read_only(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            self._get(review, ReviewArea.UNIFIED_PANEL_AGGREGATION).actionability
            == ActionabilityLevel.READ_ONLY_PROJECTION
        )

    def test_desktop_three_state_is_read_only(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            self._get(review, ReviewArea.DESKTOP_THREE_STATE_EXISTENCE).actionability
            == ActionabilityLevel.READ_ONLY_PROJECTION
        )

    def test_operator_actionability_is_read_only(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            self._get(review, ReviewArea.OPERATOR_ACTIONABILITY).actionability
            == ActionabilityLevel.READ_ONLY_PROJECTION
        )

    def test_nl_canonical_path_is_action_capable(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            self._get(review, ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH).actionability
            == ActionabilityLevel.ACTION_CAPABLE
        )

    def test_multimodal_canonical_path_is_action_capable(
        self, review: FiveAreaImplReview
    ) -> None:
        assert (
            self._get(review, ReviewArea.MULTIMODAL_CANONICAL_PATH).actionability
            == ActionabilityLevel.ACTION_CAPABLE
        )


# =============================================================================
# SECTION 6 — Per-area maturity_unlock
# =============================================================================


class TestAreaMaturityUnlocks:
    """Each area must carry the correct maturity_unlock value."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def _get(self, review: FiveAreaImplReview, area: ReviewArea) -> AreaReviewEntry:
        entry = review.get_area(area)
        assert entry is not None
        return entry

    def test_unified_panel_maturity_unlock(self, review: FiveAreaImplReview) -> None:
        entry = self._get(review, ReviewArea.UNIFIED_PANEL_AGGREGATION)
        assert entry.maturity_unlock == FollowUpPrMaturityUnlock.PANEL_STATE_UNIFIED

    def test_desktop_three_state_maturity_unlock(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.DESKTOP_THREE_STATE_EXISTENCE)
        assert entry.maturity_unlock == FollowUpPrMaturityUnlock.DESKTOP_ASSISTANT_PRESENCE

    def test_operator_actionability_maturity_unlock(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.OPERATOR_ACTIONABILITY)
        assert entry.maturity_unlock == FollowUpPrMaturityUnlock.OPERATOR_ACTION_CAPABLE

    def test_nl_canonical_path_maturity_unlock(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH)
        assert entry.maturity_unlock == FollowUpPrMaturityUnlock.NL_E2E_CI_PROVEN

    def test_multimodal_canonical_path_maturity_unlock(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.MULTIMODAL_CANONICAL_PATH)
        assert entry.maturity_unlock == FollowUpPrMaturityUnlock.MULTIMODAL_E2E_ACTIVATED

    def test_all_five_unlock_values_used(self, review: FiveAreaImplReview) -> None:
        unlocks = {e.maturity_unlock for e in review.area_entries}
        assert unlocks == set(FollowUpPrMaturityUnlock)


# =============================================================================
# SECTION 7 — Per-area gap items
# =============================================================================


class TestAreaGapItems:
    """Each area must have honest gap items describing the known gaps."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def _get(self, review: FiveAreaImplReview, area: ReviewArea) -> AreaReviewEntry:
        entry = review.get_area(area)
        assert entry is not None
        return entry

    def test_unified_panel_has_gap_about_aggregation(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.UNIFIED_PANEL_AGGREGATION)
        combined = " ".join(entry.gap_items).lower()
        assert any(
            term in combined
            for term in ["unified", "aggregation", "single", "panel"]
        ), "UNIFIED_PANEL_AGGREGATION gap_items do not mention aggregation gap"

    def test_desktop_three_state_has_gap_about_unified_surface(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.DESKTOP_THREE_STATE_EXISTENCE)
        combined = " ".join(entry.gap_items).lower()
        assert any(
            term in combined
            for term in ["unified", "single", "joint", "coherent"]
        ), "DESKTOP_THREE_STATE_EXISTENCE gap_items do not mention unified surface gap"

    def test_operator_actionability_has_gap_about_no_action_endpoints(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.OPERATOR_ACTIONABILITY)
        combined = " ".join(entry.gap_items).lower()
        assert any(
            term in combined
            for term in ["action", "no action", "read-only", "read_only"]
        ), "OPERATOR_ACTIONABILITY gap_items do not mention lack of action endpoints"

    def test_nl_canonical_path_has_gap_about_no_e2e_ci_test(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH)
        combined = " ".join(entry.gap_items).lower()
        assert any(
            term in combined
            for term in ["ci", "test", "e2e", "end-to-end", "roundtrip"]
        ), "NATURAL_LANGUAGE_CANONICAL_PATH gap_items do not mention missing CI test"

    def test_multimodal_has_gap_about_missing_e2e_or_disabled(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.MULTIMODAL_CANONICAL_PATH)
        combined = " ".join(entry.gap_items).lower()
        assert any(
            term in combined
            for term in ["disabled", "e2e", "ci", "test", "end-to-end", "not yet"]
        ), (
            "MULTIMODAL_CANONICAL_PATH gap_items do not mention disabled-by-default "
            "or missing e2e CI test"
        )


# =============================================================================
# SECTION 8 — Per-area impl_cut_points
# =============================================================================


class TestAreaImplCutPoints:
    """Each area must have implementation cut points with appropriate change types."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def _get(self, review: FiveAreaImplReview, area: ReviewArea) -> AreaReviewEntry:
        entry = review.get_area(area)
        assert entry is not None
        return entry

    def test_all_areas_have_at_least_one_cut_point(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            assert len(entry.impl_cut_points) >= 1, (
                f"{entry.area.value} has no impl_cut_points"
            )

    def test_unified_panel_has_new_module_or_new_endpoint_cut_point(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.UNIFIED_PANEL_AGGREGATION)
        types = {cp.change_type for cp in entry.impl_cut_points}
        assert types & {"new_module", "new_endpoint"}, (
            "UNIFIED_PANEL_AGGREGATION cut points should include new_module or new_endpoint"
        )

    def test_operator_actionability_has_new_endpoint_cut_point(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.OPERATOR_ACTIONABILITY)
        types = {cp.change_type for cp in entry.impl_cut_points}
        assert "new_endpoint" in types, (
            "OPERATOR_ACTIONABILITY cut points should include new_endpoint"
        )

    def test_nl_canonical_path_has_test_only_cut_point(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.NATURAL_LANGUAGE_CANONICAL_PATH)
        types = {cp.change_type for cp in entry.impl_cut_points}
        assert "test_only" in types, (
            "NATURAL_LANGUAGE_CANONICAL_PATH cut points should include test_only"
        )

    def test_multimodal_has_test_only_or_wire_existing_cut_point(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = self._get(review, ReviewArea.MULTIMODAL_CANONICAL_PATH)
        types = {cp.change_type for cp in entry.impl_cut_points}
        assert types & {"test_only", "wire_existing"}, (
            "MULTIMODAL_CANONICAL_PATH cut points should include test_only or wire_existing"
        )

    def test_all_cut_points_have_required_fields(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            for cp in entry.impl_cut_points:
                assert cp.cut_point_id, f"cut_point_id is empty in {entry.area.value}"
                assert cp.description, f"description is empty in {entry.area.value}"
                assert cp.target_module, f"target_module is empty in {entry.area.value}"
                assert cp.change_type, f"change_type is empty in {entry.area.value}"
                assert cp.estimated_scope in {"small", "medium", "large"}, (
                    f"estimated_scope {cp.estimated_scope!r} not in {{small, medium, large}}"
                )


# =============================================================================
# SECTION 9 — Per-area code anchors
# =============================================================================


class TestAreaCodeAnchors:
    """Each area must have code anchors, at least one for the v2 repo."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def test_all_areas_have_at_least_one_code_anchor(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            assert len(entry.code_anchors) >= 1, (
                f"{entry.area.value} has no code anchors"
            )

    def test_all_areas_have_at_least_one_v2_anchor(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            v2_anchors = [a for a in entry.code_anchors if a.repo == "v2"]
            assert len(v2_anchors) >= 1, (
                f"{entry.area.value} has no v2 code anchors"
            )

    def test_operator_actionability_anchors_include_operator_route(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = review.get_area(ReviewArea.OPERATOR_ACTIONABILITY)
        assert entry is not None
        modules = {a.module_path for a in entry.code_anchors}
        assert "core.routes.operator" in modules, (
            "OPERATOR_ACTIONABILITY anchors should include core.routes.operator"
        )

    def test_multimodal_has_android_evidence_refs(
        self, review: FiveAreaImplReview
    ) -> None:
        entry = review.get_area(ReviewArea.MULTIMODAL_CANONICAL_PATH)
        assert entry is not None
        assert len(entry.android_evidence_refs) >= 1, (
            "MULTIMODAL_CANONICAL_PATH should have android_evidence_refs"
        )

    def test_all_code_anchors_have_required_fields(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            for anchor in entry.code_anchors:
                assert anchor.module_path, "module_path is empty"
                assert anchor.repo in {"v2", "android"}, (
                    f"repo {anchor.repo!r} not in {{v2, android}}"
                )
                assert anchor.role, "role is empty"
                assert isinstance(anchor.importable, bool)


# =============================================================================
# SECTION 10 — Invariant checker
# =============================================================================


class TestInvariantChecker:
    """assert_five_area_review_invariants() must pass on a correctly built review."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def test_invariants_pass_on_fresh_build(
        self, review: FiveAreaImplReview
    ) -> None:
        assert_five_area_review_invariants(review)

    def test_invariants_detect_too_few_entries(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries = review.area_entries[:3]
        with pytest.raises(AssertionError, match="Expected 5 area entries"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_empty_canonical_path_summary(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries[0].canonical_path_summary = ""
        with pytest.raises(AssertionError, match="canonical_path_summary"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_missing_code_anchors(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries[0].code_anchors = []
        with pytest.raises(AssertionError, match="code anchor"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_missing_impl_cut_points(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries[0].impl_cut_points = []
        with pytest.raises(AssertionError, match="impl_cut_point"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_missing_modification_zone(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries[0].modification_zones = []
        with pytest.raises(AssertionError, match="modification_zone"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_none_maturity_unlock(self) -> None:
        review = build_five_area_impl_review()
        review.area_entries[0].maturity_unlock = None
        with pytest.raises(AssertionError, match="maturity_unlock"):
            assert_five_area_review_invariants(review)

    def test_invariants_detect_empty_overall_summary(self) -> None:
        review = build_five_area_impl_review()
        review.overall_summary = ""
        with pytest.raises(AssertionError, match="overall_summary"):
            assert_five_area_review_invariants(review)


# =============================================================================
# SECTION 11 — JSON serialisation
# =============================================================================


class TestJsonSerialisation:
    """Report must serialise to JSON cleanly and round-trip correctly."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def test_to_json_returns_string(self, review: FiveAreaImplReview) -> None:
        result = review.to_json()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_to_json_parses_as_valid_json(self, review: FiveAreaImplReview) -> None:
        result = review.to_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_to_dict_has_required_top_level_keys(
        self, review: FiveAreaImplReview
    ) -> None:
        d = review.to_dict()
        required = {
            "report_id",
            "generated_at",
            "authority",
            "methodology",
            "area_entries",
            "overall_summary",
            "next_pr_priority_order",
            "next_pr_priority_rationale",
        }
        assert required.issubset(d.keys()), (
            f"Missing keys: {required - d.keys()}"
        )

    def test_to_dict_area_entries_has_five_items(
        self, review: FiveAreaImplReview
    ) -> None:
        d = review.to_dict()
        assert len(d["area_entries"]) == 5

    def test_area_entry_to_dict_has_required_keys(
        self, review: FiveAreaImplReview
    ) -> None:
        required = {
            "area",
            "maturity_label",
            "code_anchors",
            "canonical_path_summary",
            "established_items",
            "partial_items",
            "gap_items",
            "overclaiming_rationale",
            "impl_cut_points",
            "modification_zones",
            "maturity_unlock",
            "maturity_unlock_description",
            "actionability",
            "android_evidence_refs",
        }
        for entry in review.area_entries:
            d = entry.to_dict()
            assert required.issubset(d.keys()), (
                f"{entry.area.value}: missing keys {required - d.keys()}"
            )

    def test_code_anchor_to_dict_has_required_keys(
        self, review: FiveAreaImplReview
    ) -> None:
        required = {"module_path", "repo", "role", "importable"}
        for entry in review.area_entries:
            for anchor in entry.code_anchors:
                d = anchor.to_dict()
                assert required.issubset(d.keys()), (
                    f"CodeAnchor missing keys: {required - d.keys()}"
                )

    def test_impl_cut_point_to_dict_has_required_keys(
        self, review: FiveAreaImplReview
    ) -> None:
        required = {
            "cut_point_id",
            "description",
            "target_module",
            "change_type",
            "estimated_scope",
        }
        for entry in review.area_entries:
            for cp in entry.impl_cut_points:
                d = cp.to_dict()
                assert required.issubset(d.keys()), (
                    f"ImplCutPoint missing keys: {required - d.keys()}"
                )

    def test_modification_zone_to_dict_has_required_keys(
        self, review: FiveAreaImplReview
    ) -> None:
        required = {"zone_id", "files_or_modules", "rationale"}
        for entry in review.area_entries:
            for zone in entry.modification_zones:
                d = zone.to_dict()
                assert required.issubset(d.keys()), (
                    f"ModificationZone missing keys: {required - d.keys()}"
                )

    def test_round_trip_area_count(self, review: FiveAreaImplReview) -> None:
        json_str = review.to_json()
        parsed = json.loads(json_str)
        assert len(parsed["area_entries"]) == 5

    def test_round_trip_authority(self, review: FiveAreaImplReview) -> None:
        json_str = review.to_json()
        parsed = json.loads(json_str)
        assert parsed["authority"] == FIVE_AREA_REVIEW_AUTHORITY


# =============================================================================
# SECTION 12 — Singleton caching
# =============================================================================


class TestSingletonCaching:
    """Singleton caching and reset must work correctly."""

    def test_get_returns_same_instance_on_successive_calls(self) -> None:
        reset_five_area_impl_review()
        r1 = get_five_area_impl_review()
        r2 = get_five_area_impl_review()
        assert r1 is r2

    def test_reset_allows_fresh_build(self) -> None:
        r1 = get_five_area_impl_review()
        reset_five_area_impl_review()
        r2 = get_five_area_impl_review()
        assert r1 is not r2

    def test_get_returns_five_area_impl_review(self) -> None:
        reset_five_area_impl_review()
        result = get_five_area_impl_review()
        assert isinstance(result, FiveAreaImplReview)

    def test_get_area_helper_returns_correct_entry(self) -> None:
        reset_five_area_impl_review()
        review = get_five_area_impl_review()
        for area in ReviewArea:
            entry = review.get_area(area)
            assert entry is not None, f"get_area({area.value}) returned None"
            assert entry.area == area

    def test_get_area_returns_none_for_nonexistent(self) -> None:
        reset_five_area_impl_review()
        review = get_five_area_impl_review()
        # Monkey-patch to remove all entries temporarily
        original = review.area_entries
        review.area_entries = []
        result = review.get_area(ReviewArea.UNIFIED_PANEL_AGGREGATION)
        assert result is None
        review.area_entries = original


# =============================================================================
# SECTION 13 — Overclaiming prevention
# =============================================================================


class TestOverclaimingPrevention:
    """Areas with gap items must not be labeled STRONGLY_ESTABLISHED."""

    @pytest.fixture(scope="class")
    def review(self) -> FiveAreaImplReview:
        reset_five_area_impl_review()
        return build_five_area_impl_review()

    def test_no_area_with_gaps_is_strongly_established(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            if entry.gap_items:
                assert entry.maturity_label != AreaMaturityLabel.STRONGLY_ESTABLISHED, (
                    f"{entry.area.value} has gap_items but is labeled STRONGLY_ESTABLISHED"
                )

    def test_no_area_with_gaps_is_runtime_evidenced_closed(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            if entry.gap_items:
                assert entry.maturity_label != AreaMaturityLabel.RUNTIME_EVIDENCED_CLOSED, (
                    f"{entry.area.value} has gap_items but is labeled "
                    f"RUNTIME_EVIDENCED_CLOSED"
                )

    def test_all_areas_below_strongly_established_have_overclaiming_rationale(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            if entry.maturity_label not in (
                AreaMaturityLabel.STRONGLY_ESTABLISHED,
                AreaMaturityLabel.RUNTIME_EVIDENCED_CLOSED,
            ):
                assert len(entry.overclaiming_rationale) > 0, (
                    f"{entry.area.value} is {entry.maturity_label.value} but "
                    f"overclaiming_rationale is empty"
                )

    def test_all_areas_have_non_empty_maturity_unlock_description(
        self, review: FiveAreaImplReview
    ) -> None:
        for entry in review.area_entries:
            assert len(entry.maturity_unlock_description) > 0, (
                f"{entry.area.value} has empty maturity_unlock_description"
            )
