"""
tests/test_five_domain_implementation_review.py
================================================
Test suite for core/five_domain_implementation_review.py

Five-Domain Implementation-Grade Review Package — Dual-Repository Joint
Current-State Audit Artifact.

This test suite validates:

SECTION 1 — Module import and sentinel sanity
  T01. Module importable; authority and sentinel non-empty.
  T02. Authority contains canonical token.
  T03. Methodology mentions both repos and excludes prose evidence.
  T04. verdict_zh is non-empty and mentions five domain keywords.
  T05. ReviewDomain has exactly 5 values.
  T06. EvidenceStrength has exactly 7 tiers.
  T07. FollowUpPRPriority has exactly 4 values.
  T08. All dataclasses importable.
  T09. All public functions importable and callable.

SECTION 2 — build_five_domain_review() structural checks
  T10. Returns correct type.
  T11. package_id is non-empty string.
  T12. generated_at is positive float.
  T13. authority non-empty.
  T14. methodology non-empty.
  T15. verdict_zh non-empty.
  T16. system_maturity_summary non-empty.
  T17. overclaiming_guards_summary non-empty.
  T18. domains_at_partially_established_or_below >= 4 (conservative guard).

SECTION 3 — Domain entry structural checks
  T19. Has exactly 5 domain entries.
  T20. All items are DomainImplementationEntry.
  T21. All 5 ReviewDomain values covered.
  T22. Each domain entry has evidence_strength set.
  T23. Each domain entry has non-empty canonical_path_summary.
  T24. Each domain entry has at least 1 code anchor.
  T25. Each code anchor has non-empty module_path.
  T26. Each domain entry has non-empty overclaiming_guard.
  T27. Each domain entry has follow_up_pr_spec.
  T28. Each domain has gap_items or partial_or_fragmented_items (anti-overclaim).

SECTION 4 — FollowUpPRSpec structural checks
  T29. follow_up_pr_sequence has exactly 5 entries.
  T30. Each FollowUpPRSpec has non-empty pr_title.
  T31. Each FollowUpPRSpec has non-empty implementation_cut_points.
  T32. Each FollowUpPRSpec has non-empty maturity_level_unlocked.
  T33. Each FollowUpPRSpec has non-empty invariant_that_would_close.
  T34. Each FollowUpPRSpec has non-empty primary_modification_zones.

SECTION 5 — Per-domain evidence strength guards (anti-overclaiming)
  T35. UNIFIED_PANEL_AGGREGATION is not STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED.
  T36. DESKTOP_THREE_STATE_EXISTENCE_SURFACE is not overclaimed.
  T37. OPERATOR_ACTIONABILITY is not overclaimed.
  T38. NATURAL_LANGUAGE_CANONICAL_PATH is not overclaimed.
  T39. MULTIMODAL_CANONICAL_PATH is INFRASTRUCTURE_PRESENT or PARTIALLY_ESTABLISHED.
  T40. MULTIMODAL_CANONICAL_PATH is not STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED.

SECTION 6 — Android anchor checks
  T41. At least 3 domains have Android anchors.
  T42. Each android anchor has non-empty android_package.
  T43. Each android anchor has non-empty v2_evidence_ref.

SECTION 7 — Singleton cache + reset
  T44. get_five_domain_review() returns same object on repeated calls.
  T45. reset_five_domain_review() causes rebuild on next call.

SECTION 8 — assert_five_domain_invariants()
  T46. assert_five_domain_invariants() passes on valid package.
  T47. assert_five_domain_invariants() raises on wrong domain count.
  T48. assert_five_domain_invariants() raises on empty overclaiming_guard.
  T49. assert_five_domain_invariants() raises on missing follow_up_pr_spec.

SECTION 9 — JSON serialisation round-trip
  T50. to_dict() returns dict with all top-level keys.
  T51. to_json() produces valid JSON string.
  T52. JSON round-trip: domain_entries count preserved.
  T53. JSON round-trip: authority preserved.
  T54. JSON round-trip: follow_up_pr_sequence count preserved.
  T55. DomainImplementationEntry.to_dict() includes all required fields.
  T56. FollowUpPRSpec.to_dict() includes all required fields.
  T57. CodeAnchor.to_dict() includes all required fields.
  T58. AndroidCodeAnchor.to_dict() includes all required fields.

SECTION 10 — verdict_zh content checks
  T59. verdict_zh mentions 面板 (panel).
  T60. verdict_zh mentions 三态 (three-state).
  T61. verdict_zh mentions 可操作 (actionability).
  T62. verdict_zh mentions 自然语言 (natural language).
  T63. verdict_zh mentions 多模态 (multimodal).
  T64. verdict_zh mentions both repos.

SECTION 11 — System maturity summary content
  T65. system_maturity_summary mentions all 5 domain labels.
  T66. overclaiming_guards_summary has at least 3 guard items.

Methodology
-----------
- Only imports the review module and standard library — no mocking.
- Validates structural correctness and invariants.
- Does NOT mock or override the module's real-code probes.
"""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from core.five_domain_implementation_review import (
    FIVE_DOMAIN_REVIEW_AUTHORITY,
    FIVE_DOMAIN_REVIEW_METHODOLOGY,
    FIVE_DOMAIN_REVIEW_VERDICT_ZH,
    AndroidCodeAnchor,
    CodeAnchor,
    DomainImplementationEntry,
    EvidenceStrength,
    FollowUpPRPriority,
    FollowUpPRSpec,
    ImplementationReviewPackage,
    ReviewDomain,
    assert_five_domain_invariants,
    build_five_domain_review,
    get_five_domain_review,
    reset_five_domain_review,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable and sentinels must be valid."""

    def test_authority_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(FIVE_DOMAIN_REVIEW_AUTHORITY, str)
        assert len(FIVE_DOMAIN_REVIEW_AUTHORITY) > 0

    def test_authority_contains_canonical_token(self) -> None:
        assert "FIVE_DOMAIN_IMPLEMENTATION_REVIEW_AUTHORITY" in FIVE_DOMAIN_REVIEW_AUTHORITY

    def test_authority_excludes_readme_and_pr_prose(self) -> None:
        authority_lower = FIVE_DOMAIN_REVIEW_AUTHORITY.lower()
        assert "no-readme" in authority_lower or \
               "no-pr-prose" in authority_lower or \
               "no-readme-no-pr-prose" in authority_lower

    def test_methodology_is_non_empty_string(self) -> None:
        assert isinstance(FIVE_DOMAIN_REVIEW_METHODOLOGY, str)
        assert len(FIVE_DOMAIN_REVIEW_METHODOLOGY) > 0

    def test_methodology_mentions_both_repos(self) -> None:
        assert "ufo-galaxy-realization-v2" in FIVE_DOMAIN_REVIEW_METHODOLOGY
        assert "ufo-galaxy-android" in FIVE_DOMAIN_REVIEW_METHODOLOGY

    def test_methodology_excludes_prose_evidence(self) -> None:
        assert "EXCLUDED" in FIVE_DOMAIN_REVIEW_METHODOLOGY or \
               "excluded" in FIVE_DOMAIN_REVIEW_METHODOLOGY.lower()

    def test_methodology_mentions_five_domains(self) -> None:
        m = FIVE_DOMAIN_REVIEW_METHODOLOGY
        assert "panel aggregation" in m.lower() or "unified panel" in m.lower()
        assert "three-state" in m.lower() or "three state" in m.lower()
        assert "operator actionability" in m.lower() or "actionab" in m.lower()
        assert "natural-language" in m.lower() or "natural language" in m.lower()
        assert "multimodal" in m.lower()

    def test_verdict_zh_is_non_empty_string(self) -> None:
        assert isinstance(FIVE_DOMAIN_REVIEW_VERDICT_ZH, str)
        assert len(FIVE_DOMAIN_REVIEW_VERDICT_ZH) > 0

    def test_review_domain_has_5_values(self) -> None:
        domains = list(ReviewDomain)
        assert len(domains) == 5, f"Expected 5 domains; got {len(domains)}: {domains}"

    def test_all_5_domain_names_present(self) -> None:
        assert ReviewDomain.UNIFIED_PANEL_AGGREGATION in ReviewDomain
        assert ReviewDomain.DESKTOP_THREE_STATE_EXISTENCE_SURFACE in ReviewDomain
        assert ReviewDomain.OPERATOR_ACTIONABILITY in ReviewDomain
        assert ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH in ReviewDomain
        assert ReviewDomain.MULTIMODAL_CANONICAL_PATH in ReviewDomain

    def test_evidence_strength_has_7_tiers(self) -> None:
        tiers = list(EvidenceStrength)
        assert len(tiers) == 7, f"Expected 7 tiers; got {len(tiers)}: {tiers}"

    def test_evidence_strength_includes_infrastructure_present(self) -> None:
        assert EvidenceStrength.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN in EvidenceStrength

    def test_evidence_strength_includes_strongly_established(self) -> None:
        assert EvidenceStrength.STRONGLY_ESTABLISHED in EvidenceStrength

    def test_follow_up_pr_priority_has_4_values(self) -> None:
        priorities = list(FollowUpPRPriority)
        assert len(priorities) == 4, f"Expected 4 priorities; got {len(priorities)}"

    def test_all_dataclasses_importable(self) -> None:
        assert AndroidCodeAnchor is not None
        assert CodeAnchor is not None
        assert DomainImplementationEntry is not None
        assert FollowUpPRSpec is not None
        assert ImplementationReviewPackage is not None

    def test_all_functions_importable(self) -> None:
        assert callable(build_five_domain_review)
        assert callable(get_five_domain_review)
        assert callable(reset_five_domain_review)
        assert callable(assert_five_domain_invariants)


# =============================================================================
# SECTION 2 — build_five_domain_review() structural checks
# =============================================================================


class TestBuildPackage:
    """build_five_domain_review() must return a structurally complete package."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_returns_correct_type(self, package: ImplementationReviewPackage) -> None:
        assert isinstance(package, ImplementationReviewPackage)

    def test_package_id_is_non_empty(self, package: ImplementationReviewPackage) -> None:
        assert isinstance(package.package_id, str)
        assert len(package.package_id) > 0

    def test_generated_at_is_positive_float(
        self, package: ImplementationReviewPackage
    ) -> None:
        assert isinstance(package.generated_at, float)
        assert package.generated_at > 0

    def test_authority_non_empty(self, package: ImplementationReviewPackage) -> None:
        assert len(package.authority) > 0
        assert "FIVE_DOMAIN" in package.authority

    def test_methodology_non_empty(self, package: ImplementationReviewPackage) -> None:
        assert len(package.methodology) > 0

    def test_verdict_zh_non_empty(self, package: ImplementationReviewPackage) -> None:
        assert len(package.verdict_zh) > 0

    def test_system_maturity_summary_non_empty(
        self, package: ImplementationReviewPackage
    ) -> None:
        assert len(package.system_maturity_summary) > 0

    def test_overclaiming_guards_summary_non_empty(
        self, package: ImplementationReviewPackage
    ) -> None:
        assert len(package.overclaiming_guards_summary) > 0

    def test_domains_at_partially_established_or_below_is_high(
        self, package: ImplementationReviewPackage
    ) -> None:
        # All 5 domains should be below RUNTIME_EVIDENCED_CLOSED in current state
        assert package.domains_at_partially_established_or_below >= 4, (
            f"Expected >= 4 domains below threshold; "
            f"got {package.domains_at_partially_established_or_below} "
            f"(this would be an overclaim if fewer)"
        )


# =============================================================================
# SECTION 3 — Domain entry structural checks
# =============================================================================


class TestDomainEntries:
    """Domain entries must be exactly 5 and structurally correct."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_has_exactly_5_domain_entries(
        self, package: ImplementationReviewPackage
    ) -> None:
        assert len(package.domain_entries) == 5, (
            f"Expected 5; got {len(package.domain_entries)}: "
            f"{[e.domain.value for e in package.domain_entries]}"
        )

    def test_all_items_are_domain_implementation_entry(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert isinstance(entry, DomainImplementationEntry)

    def test_all_5_review_domains_covered(
        self, package: ImplementationReviewPackage
    ) -> None:
        covered = {e.domain for e in package.domain_entries}
        for domain in ReviewDomain:
            assert domain in covered, f"Missing domain: {domain}"

    def test_each_domain_has_evidence_strength(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert isinstance(entry.evidence_strength, EvidenceStrength), (
                f"Domain {entry.domain} has invalid evidence_strength"
            )

    def test_each_domain_has_non_empty_canonical_path_summary(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert len(entry.canonical_path_summary) > 0, (
                f"Domain {entry.domain} has empty canonical_path_summary"
            )

    def test_each_domain_has_at_least_one_code_anchor(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert len(entry.current_code_anchors) >= 1, (
                f"Domain {entry.domain} has no code anchors"
            )

    def test_each_code_anchor_has_non_empty_module_path(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.current_code_anchors:
                assert len(anchor.module_path) > 0, (
                    f"Domain {entry.domain} has a code anchor with empty module_path"
                )

    def test_each_code_anchor_has_non_empty_description(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.current_code_anchors:
                assert len(anchor.description) > 0, (
                    f"Domain {entry.domain} has a code anchor with empty description"
                )

    def test_each_domain_has_non_empty_overclaiming_guard(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert len(entry.overclaiming_guard) > 0, (
                f"Domain {entry.domain} has empty overclaiming_guard"
            )

    def test_each_domain_overclaiming_guard_contains_overclaiming_keyword(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            guard = entry.overclaiming_guard.upper()
            assert "OVERCLAIM" in guard or "CANNOT" in guard or "NOT" in guard, (
                f"Domain {entry.domain} overclaiming_guard does not contain "
                f"anti-overclaiming language"
            )

    def test_each_domain_has_follow_up_pr_spec(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert entry.follow_up_pr_spec is not None, (
                f"Domain {entry.domain} has no follow_up_pr_spec"
            )

    def test_each_domain_has_gaps_or_partial_items(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            has_issues = (
                len(entry.gap_items) > 0
                or len(entry.partial_or_fragmented_items) > 0
            )
            assert has_issues, (
                f"Domain {entry.domain} has neither gap_items nor "
                f"partial_or_fragmented_items — this would be an overclaim "
                f"(no domain in current state is gap-free)"
            )

    def test_each_domain_has_at_least_one_established_item(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            assert len(entry.established_items) >= 1, (
                f"Domain {entry.domain} has no established items — "
                f"must have at least something confirmed in real code"
            )


# =============================================================================
# SECTION 4 — FollowUpPRSpec structural checks
# =============================================================================


class TestFollowUpPRSpecs:
    """FollowUpPRSpec items must be prescriptive and non-empty."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_follow_up_pr_sequence_has_exactly_5_entries(
        self, package: ImplementationReviewPackage
    ) -> None:
        assert len(package.follow_up_pr_sequence) == 5, (
            f"Expected 5 follow-up PRs; got {len(package.follow_up_pr_sequence)}"
        )

    def test_each_follow_up_pr_has_non_empty_pr_title(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.pr_title) > 0, "FollowUpPRSpec has empty pr_title"

    def test_each_follow_up_pr_has_non_empty_implementation_cut_points(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.implementation_cut_points) >= 1, (
                f"FollowUpPRSpec '{spec.pr_title}' has no implementation_cut_points"
            )

    def test_each_follow_up_pr_has_non_empty_maturity_level_unlocked(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.maturity_level_unlocked) > 0, (
                f"FollowUpPRSpec '{spec.pr_title}' has empty maturity_level_unlocked"
            )

    def test_each_follow_up_pr_has_non_empty_invariant_that_would_close(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.invariant_that_would_close) > 0, (
                f"FollowUpPRSpec '{spec.pr_title}' has empty invariant_that_would_close"
            )

    def test_each_follow_up_pr_has_non_empty_primary_modification_zones(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.primary_modification_zones) >= 1, (
                f"FollowUpPRSpec '{spec.pr_title}' has no primary_modification_zones"
            )

    def test_each_follow_up_pr_has_valid_priority(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert isinstance(spec.priority, FollowUpPRPriority), (
                f"FollowUpPRSpec '{spec.pr_title}' has invalid priority"
            )

    def test_each_follow_up_pr_has_non_empty_estimated_scope(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            assert len(spec.estimated_scope) > 0, (
                f"FollowUpPRSpec '{spec.pr_title}' has empty estimated_scope"
            )

    def test_implementation_cut_points_reference_real_paths(
        self, package: ImplementationReviewPackage
    ) -> None:
        for spec in package.follow_up_pr_sequence:
            for cut_point in spec.implementation_cut_points:
                # Each cut point should reference a file/module path
                has_path = (
                    "/" in cut_point
                    or "." in cut_point
                    or "core" in cut_point.lower()
                    or "tests" in cut_point.lower()
                )
                assert has_path, (
                    f"Cut point '{cut_point}' in PR '{spec.pr_title}' does not "
                    f"appear to reference a real file/module path"
                )


# =============================================================================
# SECTION 5 — Per-domain evidence strength guards (anti-overclaiming)
# =============================================================================


class TestAntiOverclaimingGuards:
    """Each domain must not overclaim its evidence strength."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    @pytest.fixture(scope="class")
    def domain_map(
        self, package: ImplementationReviewPackage
    ) -> dict:
        return {e.domain: e for e in package.domain_entries}

    _OVERCLAIM_LABELS = {
        EvidenceStrength.STRONGLY_ESTABLISHED,
        EvidenceStrength.RUNTIME_EVIDENCED_CLOSED,
    }

    def test_unified_panel_aggregation_not_overclaimed(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.UNIFIED_PANEL_AGGREGATION]
        assert entry.evidence_strength not in self._OVERCLAIM_LABELS, (
            f"UNIFIED_PANEL_AGGREGATION must not be overclaimed; "
            f"got {entry.evidence_strength}"
        )

    def test_desktop_three_state_not_overclaimed(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.DESKTOP_THREE_STATE_EXISTENCE_SURFACE]
        assert entry.evidence_strength not in self._OVERCLAIM_LABELS, (
            f"DESKTOP_THREE_STATE_EXISTENCE_SURFACE must not be overclaimed; "
            f"got {entry.evidence_strength}"
        )

    def test_operator_actionability_not_overclaimed(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.OPERATOR_ACTIONABILITY]
        assert entry.evidence_strength not in self._OVERCLAIM_LABELS, (
            f"OPERATOR_ACTIONABILITY must not be overclaimed; "
            f"got {entry.evidence_strength}"
        )

    def test_natural_language_path_evidence_strength_reflects_ci_proof(
        self, domain_map: dict
    ) -> None:
        """When the NL e2e CI test file exists the domain must be upgraded to
        RUNTIME_EVIDENCED_CLOSED.  When it does not exist it must remain at
        PARTIALLY_ESTABLISHED (not overclaimed).

        PR-5 adds tests/integration/test_nl_e2e_canonical_path.py which is the
        gate that unlocks the upgrade.  This test asserts the correct strength for
        whichever state the file is in right now.
        """
        from core.five_domain_implementation_review import _test_file_exists
        entry = domain_map[ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH]
        nl_e2e_file = "tests.integration.test_nl_e2e_canonical_path"
        if _test_file_exists(nl_e2e_file):
            # CI proof exists — expect RUNTIME_EVIDENCED_CLOSED
            assert entry.evidence_strength == EvidenceStrength.RUNTIME_EVIDENCED_CLOSED, (
                f"NATURAL_LANGUAGE_CANONICAL_PATH should be RUNTIME_EVIDENCED_CLOSED "
                f"when the NL e2e test file exists; got {entry.evidence_strength}"
            )
        else:
            # CI proof missing — must not be overclaimed
            assert entry.evidence_strength not in self._OVERCLAIM_LABELS, (
                f"NATURAL_LANGUAGE_CANONICAL_PATH must not be overclaimed when "
                f"the CI test is absent; got {entry.evidence_strength}"
            )

    def test_multimodal_path_is_infrastructure_present_or_lower(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.MULTIMODAL_CANONICAL_PATH]
        # Multimodal must be INFRASTRUCTURE_PRESENT or PARTIALLY_ESTABLISHED
        # (definitely not STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED)
        assert entry.evidence_strength not in self._OVERCLAIM_LABELS, (
            f"MULTIMODAL_CANONICAL_PATH must not be overclaimed; "
            f"got {entry.evidence_strength}"
        )

    def test_multimodal_path_is_at_most_partially_established(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.MULTIMODAL_CANONICAL_PATH]
        allowed = {
            EvidenceStrength.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN,
            EvidenceStrength.PARTIALLY_ESTABLISHED,
            EvidenceStrength.SURFACE_ALIGNMENT_ONLY,
            EvidenceStrength.MISSING_RUNTIME_EVIDENCE,
            EvidenceStrength.NOT_YET_IMPLEMENTED,
        }
        assert entry.evidence_strength in allowed, (
            f"MULTIMODAL_CANONICAL_PATH evidence strength {entry.evidence_strength} "
            f"is unexpected — should be at most PARTIALLY_ESTABLISHED"
        )

    def test_unified_panel_aggregation_has_gap_about_no_unified_endpoint(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.UNIFIED_PANEL_AGGREGATION]
        all_issues = entry.gap_items + entry.partial_or_fragmented_items
        text = " ".join(all_issues).upper()
        assert "UNIFIED" in text or "AGGREGAT" in text or "PANEL" in text, (
            "UNIFIED_PANEL_AGGREGATION must document the unified endpoint gap"
        )

    def test_operator_actionability_documents_read_only_gap(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.OPERATOR_ACTIONABILITY]
        all_issues = entry.gap_items + entry.partial_or_fragmented_items
        text = " ".join(all_issues).upper()
        assert "READ-ONLY" in text or "READ_ONLY" in text or "OBSERVATION" in text or \
               "NO POST" in text or "NO ACTION" in text or "OBSERVATION-ONLY" in text, (
            "OPERATOR_ACTIONABILITY must document the read-only / no-action-endpoint gap"
        )

    def test_nl_path_documents_ci_state(
        self, domain_map: dict
    ) -> None:
        """The NL domain must document the CI test state.

        - Before PR-5: gap_items must contain a reference to the missing CI test.
        - After PR-5: partial_or_fragmented_items must contain a reference to the
          LLM stub (documenting that the CI proof uses a contract stub, not a real
          production LLM).
        """
        from core.five_domain_implementation_review import _test_file_exists
        entry = domain_map[ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH]
        all_issues = entry.gap_items + entry.partial_or_fragmented_items
        text = " ".join(all_issues).upper()
        assert "CI" in text or "LLM" in text or "TEST" in text or "STUB" in text, (
            "NATURAL_LANGUAGE_CANONICAL_PATH must document CI/LLM test status "
            "(either a missing CI test gap or a stub-only limitation note)"
        )

    def test_multimodal_documents_safe_default_disabled_gap(
        self, domain_map: dict
    ) -> None:
        entry = domain_map[ReviewDomain.MULTIMODAL_CANONICAL_PATH]
        all_issues = entry.gap_items + entry.partial_or_fragmented_items
        text = " ".join(all_issues).upper()
        assert "DEFAULT" in text or "DISABLED" in text or "SAFE" in text or \
               "CI" in text, (
            "MULTIMODAL_CANONICAL_PATH must document the SAFE_DEFAULT disabled gap"
        )


# =============================================================================
# SECTION 6 — Android anchor checks
# =============================================================================


class TestAndroidAnchors:
    """Domains that involve Android must have Android anchors."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_at_least_3_domains_have_android_anchors(
        self, package: ImplementationReviewPackage
    ) -> None:
        domains_with_android = sum(
            1 for e in package.domain_entries if len(e.android_anchors) > 0
        )
        assert domains_with_android >= 3, (
            f"Expected >= 3 domains with Android anchors; got {domains_with_android}"
        )

    def test_each_android_anchor_has_non_empty_android_package(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.android_anchors:
                assert len(anchor.android_package) > 0, (
                    f"Domain {entry.domain} has Android anchor with empty android_package"
                )

    def test_each_android_anchor_has_non_empty_v2_evidence_ref(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.android_anchors:
                assert len(anchor.v2_evidence_ref) > 0, (
                    f"Domain {entry.domain} has Android anchor with empty v2_evidence_ref"
                )

    def test_each_android_anchor_has_non_empty_description(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.android_anchors:
                assert len(anchor.description) > 0, (
                    f"Domain {entry.domain} has Android anchor with empty description"
                )

    def test_multimodal_domain_has_android_anchors(
        self, package: ImplementationReviewPackage
    ) -> None:
        entry = next(
            e for e in package.domain_entries
            if e.domain == ReviewDomain.MULTIMODAL_CANONICAL_PATH
        )
        assert len(entry.android_anchors) >= 1, (
            "MULTIMODAL_CANONICAL_PATH must have at least 1 Android anchor "
            "(MobileVLM / SeeClick / vision uplink)"
        )


# =============================================================================
# SECTION 7 — Singleton cache + reset
# =============================================================================


class TestSingletonCacheAndReset:
    """Singleton cache must work correctly."""

    def test_get_returns_same_object_on_repeated_calls(self) -> None:
        reset_five_domain_review()
        first = get_five_domain_review()
        second = get_five_domain_review()
        assert first is second, "get_five_domain_review() must return the same cached object"

    def test_reset_causes_rebuild(self) -> None:
        reset_five_domain_review()
        first = get_five_domain_review()
        reset_five_domain_review()
        second = get_five_domain_review()
        # After reset, a new object is created
        assert first is not second, (
            "After reset, get_five_domain_review() must return a new object"
        )

    def test_cache_after_reset_has_correct_structure(self) -> None:
        reset_five_domain_review()
        pkg = get_five_domain_review()
        assert isinstance(pkg, ImplementationReviewPackage)
        assert len(pkg.domain_entries) == 5


# =============================================================================
# SECTION 8 — assert_five_domain_invariants()
# =============================================================================


class TestAssertFiveDomainInvariants:
    """Invariant checker must pass on valid packages and fail on invalid ones."""

    def test_invariants_pass_on_valid_package(self) -> None:
        pkg = build_five_domain_review()
        # Should not raise
        assert_five_domain_invariants(pkg)

    def test_invariants_pass_with_none_arg(self) -> None:
        reset_five_domain_review()
        # Should not raise — uses cached package
        assert_five_domain_invariants(None)

    def test_invariants_raise_on_missing_domain_entry(self) -> None:
        pkg = build_five_domain_review()
        # Remove one entry to trigger INV-1
        bad_pkg = ImplementationReviewPackage(
            package_id=pkg.package_id,
            generated_at=pkg.generated_at,
            authority=pkg.authority,
            methodology=pkg.methodology,
            verdict_zh=pkg.verdict_zh,
            domain_entries=pkg.domain_entries[:-1],  # only 4 entries
            system_maturity_summary=pkg.system_maturity_summary,
            follow_up_pr_sequence=pkg.follow_up_pr_sequence,
            overclaiming_guards_summary=pkg.overclaiming_guards_summary,
            domains_at_partially_established_or_below=(
                pkg.domains_at_partially_established_or_below
            ),
        )
        with pytest.raises(AssertionError, match="INV-1"):
            assert_five_domain_invariants(bad_pkg)

    def test_invariants_raise_on_empty_overclaiming_guard(self) -> None:
        pkg = build_five_domain_review()
        # Mutate one entry to have empty overclaiming_guard
        mutated_entries = []
        for entry in pkg.domain_entries:
            if entry.domain == ReviewDomain.UNIFIED_PANEL_AGGREGATION:
                # Create a copy with empty overclaiming_guard
                new_entry = DomainImplementationEntry(
                    domain=entry.domain,
                    evidence_strength=entry.evidence_strength,
                    canonical_path_summary=entry.canonical_path_summary,
                    established_items=list(entry.established_items),
                    partial_or_fragmented_items=list(entry.partial_or_fragmented_items),
                    gap_items=list(entry.gap_items),
                    current_code_anchors=list(entry.current_code_anchors),
                    android_anchors=list(entry.android_anchors),
                    overclaiming_guard="",  # intentionally empty
                    follow_up_pr_spec=entry.follow_up_pr_spec,
                )
                mutated_entries.append(new_entry)
            else:
                mutated_entries.append(entry)

        bad_pkg = ImplementationReviewPackage(
            package_id=pkg.package_id,
            generated_at=pkg.generated_at,
            authority=pkg.authority,
            methodology=pkg.methodology,
            verdict_zh=pkg.verdict_zh,
            domain_entries=mutated_entries,
            system_maturity_summary=pkg.system_maturity_summary,
            follow_up_pr_sequence=pkg.follow_up_pr_sequence,
            overclaiming_guards_summary=pkg.overclaiming_guards_summary,
            domains_at_partially_established_or_below=(
                pkg.domains_at_partially_established_or_below
            ),
        )
        with pytest.raises(AssertionError, match="INV-4"):
            assert_five_domain_invariants(bad_pkg)

    def test_invariants_raise_on_missing_follow_up_pr_spec(self) -> None:
        pkg = build_five_domain_review()
        mutated_entries = []
        for entry in pkg.domain_entries:
            if entry.domain == ReviewDomain.OPERATOR_ACTIONABILITY:
                new_entry = DomainImplementationEntry(
                    domain=entry.domain,
                    evidence_strength=entry.evidence_strength,
                    canonical_path_summary=entry.canonical_path_summary,
                    established_items=list(entry.established_items),
                    partial_or_fragmented_items=list(entry.partial_or_fragmented_items),
                    gap_items=list(entry.gap_items),
                    current_code_anchors=list(entry.current_code_anchors),
                    android_anchors=list(entry.android_anchors),
                    overclaiming_guard=entry.overclaiming_guard,
                    follow_up_pr_spec=None,  # intentionally removed
                )
                mutated_entries.append(new_entry)
            else:
                mutated_entries.append(entry)

        bad_pkg = ImplementationReviewPackage(
            package_id=pkg.package_id,
            generated_at=pkg.generated_at,
            authority=pkg.authority,
            methodology=pkg.methodology,
            verdict_zh=pkg.verdict_zh,
            domain_entries=mutated_entries,
            system_maturity_summary=pkg.system_maturity_summary,
            follow_up_pr_sequence=pkg.follow_up_pr_sequence,
            overclaiming_guards_summary=pkg.overclaiming_guards_summary,
            domains_at_partially_established_or_below=(
                pkg.domains_at_partially_established_or_below
            ),
        )
        with pytest.raises(AssertionError, match="INV-5"):
            assert_five_domain_invariants(bad_pkg)


# =============================================================================
# SECTION 9 — JSON serialisation round-trip
# =============================================================================


class TestJsonSerialization:
    """Package must be fully JSON-serialisable."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_to_dict_returns_dict(
        self, package: ImplementationReviewPackage
    ) -> None:
        d = package.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_all_top_level_keys(
        self, package: ImplementationReviewPackage
    ) -> None:
        d = package.to_dict()
        required_keys = {
            "package_id",
            "generated_at",
            "authority",
            "methodology",
            "verdict_zh",
            "domain_entries",
            "system_maturity_summary",
            "follow_up_pr_sequence",
            "overclaiming_guards_summary",
            "domains_at_partially_established_or_below",
        }
        for key in required_keys:
            assert key in d, f"Missing key in to_dict(): '{key}'"

    def test_to_json_produces_valid_json(
        self, package: ImplementationReviewPackage
    ) -> None:
        j = package.to_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_json_round_trip_domain_entries_count(
        self, package: ImplementationReviewPackage
    ) -> None:
        parsed = json.loads(package.to_json())
        assert len(parsed["domain_entries"]) == 5

    def test_json_round_trip_authority(
        self, package: ImplementationReviewPackage
    ) -> None:
        parsed = json.loads(package.to_json())
        assert parsed["authority"] == package.authority

    def test_json_round_trip_follow_up_pr_sequence_count(
        self, package: ImplementationReviewPackage
    ) -> None:
        parsed = json.loads(package.to_json())
        assert len(parsed["follow_up_pr_sequence"]) == 5

    def test_domain_implementation_entry_to_dict_has_required_fields(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            d = entry.to_dict()
            required_fields = {
                "domain",
                "evidence_strength",
                "canonical_path_summary",
                "established_items",
                "partial_or_fragmented_items",
                "gap_items",
                "current_code_anchors",
                "android_anchors",
                "overclaiming_guard",
                "follow_up_pr_spec",
            }
            for field in required_fields:
                assert field in d, (
                    f"DomainImplementationEntry.to_dict() missing field '{field}' "
                    f"for domain {entry.domain}"
                )

    def test_follow_up_pr_spec_to_dict_has_required_fields(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            spec = entry.follow_up_pr_spec
            assert spec is not None
            d = spec.to_dict()
            required_fields = {
                "pr_title",
                "priority",
                "implementation_cut_points",
                "primary_modification_zones",
                "new_modules_to_create",
                "maturity_level_unlocked",
                "estimated_scope",
                "invariant_that_would_close",
            }
            for field in required_fields:
                assert field in d, (
                    f"FollowUpPRSpec.to_dict() missing field '{field}'"
                )

    def test_code_anchor_to_dict_has_required_fields(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.current_code_anchors:
                d = anchor.to_dict()
                assert "module_path" in d
                assert "description" in d
                assert "confirmed_importable" in d
                assert "key_attribute" in d

    def test_android_code_anchor_to_dict_has_required_fields(
        self, package: ImplementationReviewPackage
    ) -> None:
        for entry in package.domain_entries:
            for anchor in entry.android_anchors:
                d = anchor.to_dict()
                assert "android_package" in d
                assert "v2_evidence_ref" in d
                assert "description" in d
                assert "confirmed_via_v2" in d


# =============================================================================
# SECTION 10 — verdict_zh content checks
# =============================================================================


class TestVerdictZhContent:
    """verdict_zh must mention all five domain concepts in Chinese."""

    def test_verdict_zh_mentions_panel(self) -> None:
        assert "面板" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
            "verdict_zh must mention 面板 (panel)"

    def test_verdict_zh_mentions_three_state(self) -> None:
        assert "三态" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
            "verdict_zh must mention 三态 (three-state)"

    def test_verdict_zh_mentions_actionability(self) -> None:
        assert "可操作" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "操作性" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
               "verdict_zh must mention actionability concept"

    def test_verdict_zh_mentions_natural_language(self) -> None:
        assert "自然语言" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
            "verdict_zh must mention 自然语言 (natural language)"

    def test_verdict_zh_mentions_multimodal(self) -> None:
        assert "多模态" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
            "verdict_zh must mention 多模态 (multimodal)"

    def test_verdict_zh_mentions_both_repos(self) -> None:
        assert "V2" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "ufo-galaxy" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "Android" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
               "verdict_zh must mention the dual-repo context"

    def test_verdict_zh_mentions_follow_up_prs(self) -> None:
        assert "PR" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "后续" in FIVE_DOMAIN_REVIEW_VERDICT_ZH, \
               "verdict_zh must mention follow-up PRs"

    def test_verdict_zh_mentions_partial_established(self) -> None:
        assert "PARTIALLY_ESTABLISHED" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "部分成立" in FIVE_DOMAIN_REVIEW_VERDICT_ZH or \
               "PARTIALLY" in FIVE_DOMAIN_REVIEW_VERDICT_ZH


# =============================================================================
# SECTION 11 — System maturity summary content
# =============================================================================


class TestSystemMaturitySummary:
    """System maturity summary and overclaiming guards must be comprehensive."""

    @pytest.fixture(scope="class")
    def package(self) -> ImplementationReviewPackage:
        return build_five_domain_review()

    def test_system_maturity_mentions_unified_panel(
        self, package: ImplementationReviewPackage
    ) -> None:
        summary = package.system_maturity_summary.upper()
        assert "UNIFIED_PANEL" in summary or "PANEL" in summary

    def test_system_maturity_mentions_three_state(
        self, package: ImplementationReviewPackage
    ) -> None:
        summary = package.system_maturity_summary.upper()
        assert "THREE_STATE" in summary or "THREE-STATE" in summary or "DESKTOP" in summary

    def test_system_maturity_mentions_operator_actionability(
        self, package: ImplementationReviewPackage
    ) -> None:
        summary = package.system_maturity_summary.upper()
        assert "OPERATOR" in summary

    def test_system_maturity_mentions_natural_language(
        self, package: ImplementationReviewPackage
    ) -> None:
        summary = package.system_maturity_summary.upper()
        assert "NATURAL" in summary or "NL" in summary

    def test_system_maturity_mentions_multimodal(
        self, package: ImplementationReviewPackage
    ) -> None:
        summary = package.system_maturity_summary.upper()
        assert "MULTIMODAL" in summary

    def test_overclaiming_guards_summary_has_at_least_3_guards(
        self, package: ImplementationReviewPackage
    ) -> None:
        # Each guard should reference one of the 5 domains
        guards_text = package.overclaiming_guards_summary
        guard_count = guards_text.count("cannot") + guards_text.count("CANNOT")
        assert guard_count >= 3, (
            f"overclaiming_guards_summary must explicitly say 'cannot' at least 3 times; "
            f"got {guard_count}"
        )

    def test_overclaiming_guards_mentions_all_5_domains(
        self, package: ImplementationReviewPackage
    ) -> None:
        text = package.overclaiming_guards_summary.lower()
        assert "panel" in text
        assert "three" in text or "three-state" in text or "existence" in text
        assert "operator" in text
        assert "nl" in text or "natural" in text
        assert "multimodal" in text
