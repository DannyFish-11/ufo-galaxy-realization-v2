"""
tests/test_five_domain_implementation_review.py
================================================
Test suite for core/five_domain_implementation_review.py

Validates:
 1. Module imports cleanly; all public symbols accessible.
 2. Authority sentinel and version are non-empty and well-formed.
 3. All five enumerations have the correct number of members.
 4. build_five_domain_review() returns a structurally correct report.
 5. Report has exactly 5 domain entries (one per ReviewDomain).
 6. Each domain entry has a non-empty canonical_path_summary.
 7. Each domain entry has at least one established_item.
 8. Each domain entry has at least one unproven_item.
 9. Each domain entry has a non-empty incompleteness_rationale.
10. Each domain entry has at least one implementation_cut_point.
11. Each domain entry has at least one modification_zone.
12. Each domain entry has at least one v2_anchor with available=True.
13. All CodeAnchor entries have non-empty path and correct repo.
14. All ImplementationCutPoint entries have non-empty description.
15. All ModificationZone entries have non-empty file_path and change_description.
16. Domain maturity labels are individually correct (no domain overclaims).
17. UNIFIED_PANEL_AGGREGATION is PARTIALLY_ESTABLISHED.
18. DESKTOP_THREE_STATE_PRESENCE is PARTIALLY_ESTABLISHED.
19. OPERATOR_ACTIONABILITY is OBSERVATION_PROJECTION_ONLY.
20. NATURAL_LANGUAGE_CANONICAL_PATH is PARTIALLY_ESTABLISHED.
21. MULTIMODAL_CANONICAL_PATH is INFRA_PRESENT_NOT_E2E.
22. Maturity unlock levels are correctly assigned per domain.
23. Singleton caching + reset work correctly.
24. assert_five_domain_review_invariants() passes cleanly.
25. Report serialises to JSON cleanly and round-trips without loss.
26. JSON output includes all five required top-level keys per domain.
27. domain_by_name() returns the correct entry for each ReviewDomain.
28. domain_by_name() raises KeyError for an unknown domain string.
29. Panel aggregation domain identifies the missing unified aggregator.
30. Desktop domain identifies all three distinct state systems.
31. Operator domain confirms all routes are GET-only (no POST).
32. NL domain confirms chat route and DPR as canonical ingress.
33. Multimodal domain identifies enable_multimodal_ingest gate.
34. Global invariant summary is non-empty.
35. CutPointKind NEW_MODULE cut points have non-empty target_path.
36. CutPointKind NEW_TEST cut points are present in at least 3 domains.
37. All modification_zones have file_path ending in .py or are source files.
38. Android anchors exist for each domain.
39. No domain has empty v2_anchors list.
40. No domain has empty android_anchors list.

Methodology
-----------
- Only imports the review module and standard library — no mocking.
- Validates structural correctness and invariants.
- Does NOT mock or override the module's real-code probes.
"""

from __future__ import annotations

import json
from typing import Generator

import pytest

from core.five_domain_implementation_review import (
    FIVE_DOMAIN_REVIEW_AUTHORITY,
    FIVE_DOMAIN_REVIEW_VERSION,
    CodeAnchor,
    CutPointKind,
    DomainReviewEntry,
    EvidenceStrength,
    FiveDomainReviewReport,
    ImplementationCutPoint,
    MaturityLevel,
    MaturityUnlockLevel,
    ModificationZone,
    ReviewDomain,
    assert_five_domain_review_invariants,
    build_five_domain_review,
    get_five_domain_review,
    reset_five_domain_review,
)

# ---------------------------------------------------------------------------
# Minimum length thresholds (kept as module constants for maintainability)
# ---------------------------------------------------------------------------
MIN_AUTHORITY_LENGTH: int = 40   # authority sentinel must be sufficiently long
MIN_SUMMARY_LENGTH: int = 50     # canonical_path_summary / incompleteness must be prose
MIN_DESCRIPTION_LENGTH: int = 20  # cut-point and modification-zone descriptions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report() -> Generator[FiveDomainReviewReport, None, None]:
    """Build report once per module; reset cache before and after.

    Uses ``build_five_domain_review()`` directly (not ``get_five_domain_review()``)
    so the module fixture gets a stable object independent of the singleton
    cache.  TestSingletonCaching tests explicitly manage the cache via
    ``reset_five_domain_review()`` and ``get_five_domain_review()``.
    """
    reset_five_domain_review()
    yield build_five_domain_review()
    reset_five_domain_review()


# ---------------------------------------------------------------------------
# 1. Module symbols
# ---------------------------------------------------------------------------


class TestModuleSymbols:
    """Module-level public symbols must all be importable."""

    def test_authority_sentinel_non_empty(self) -> None:
        assert len(FIVE_DOMAIN_REVIEW_AUTHORITY) > MIN_AUTHORITY_LENGTH

    def test_authority_sentinel_contains_module_name(self) -> None:
        assert "five_domain_implementation_review" in FIVE_DOMAIN_REVIEW_AUTHORITY

    def test_version_non_empty(self) -> None:
        assert len(FIVE_DOMAIN_REVIEW_VERSION) > 0

    def test_version_is_string(self) -> None:
        assert isinstance(FIVE_DOMAIN_REVIEW_VERSION, str)


# ---------------------------------------------------------------------------
# 2. Enumerations
# ---------------------------------------------------------------------------


class TestEnumerations:
    """All enumerations have the expected number of members."""

    def test_review_domain_has_five_members(self) -> None:
        assert len(ReviewDomain) == 5

    def test_evidence_strength_has_six_members(self) -> None:
        assert len(EvidenceStrength) == 6

    def test_cut_point_kind_has_five_members(self) -> None:
        assert len(CutPointKind) == 5

    def test_maturity_level_has_five_members(self) -> None:
        assert len(MaturityLevel) == 5

    def test_maturity_unlock_level_has_five_members(self) -> None:
        assert len(MaturityUnlockLevel) == 5

    def test_all_review_domain_values_unique(self) -> None:
        values = [d.value for d in ReviewDomain]
        assert len(values) == len(set(values))

    def test_all_maturity_level_values_unique(self) -> None:
        values = [m.value for m in MaturityLevel]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# 3. Report structure
# ---------------------------------------------------------------------------


class TestReportStructure:
    """Report has correct overall structure."""

    def test_report_has_five_domains(self, report: FiveDomainReviewReport) -> None:
        assert len(report.domains) == 5

    def test_report_authority_matches_sentinel(self, report: FiveDomainReviewReport) -> None:
        assert report.authority == FIVE_DOMAIN_REVIEW_AUTHORITY

    def test_report_version_matches_sentinel(self, report: FiveDomainReviewReport) -> None:
        assert report.version == FIVE_DOMAIN_REVIEW_VERSION

    def test_report_global_invariant_summary_non_empty(
        self, report: FiveDomainReviewReport
    ) -> None:
        assert len(report.global_invariant_summary) > MIN_SUMMARY_LENGTH

    def test_all_five_domains_present(self, report: FiveDomainReviewReport) -> None:
        actual = {d.domain for d in report.domains}
        expected = set(ReviewDomain)
        assert actual == expected


# ---------------------------------------------------------------------------
# 4. Per-domain structural completeness
# ---------------------------------------------------------------------------


class TestDomainStructuralCompleteness:
    """Every domain entry must have required non-empty fields."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_canonical_path_summary_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.canonical_path_summary) > MIN_SUMMARY_LENGTH, (
            f"{domain.value}: canonical_path_summary too short"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_established_items_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.established_items) >= 1, (
            f"{domain.value}: must have at least 1 established_item"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_unproven_items_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.unproven_items) >= 1, (
            f"{domain.value}: must have at least 1 unproven_item"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_incompleteness_rationale_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.incompleteness_rationale) > MIN_SUMMARY_LENGTH, (
            f"{domain.value}: incompleteness_rationale too short"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_implementation_cut_points_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.implementation_cut_points) >= 1, (
            f"{domain.value}: must have at least 1 implementation_cut_point"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_modification_zones_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.modification_zones) >= 1, (
            f"{domain.value}: must have at least 1 modification_zone"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_maturity_unlock_description_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.maturity_unlock_description) > MIN_SUMMARY_LENGTH, (
            f"{domain.value}: maturity_unlock_description too short"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_v2_anchors_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.v2_anchors) >= 1, (
            f"{domain.value}: must have at least 1 v2_anchor"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_at_least_one_available_v2_anchor(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        available = [a for a in entry.v2_anchors if a.available]
        assert len(available) >= 1, (
            f"{domain.value}: must have at least 1 v2_anchor with available=True"
        )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_android_anchors_non_empty(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert len(entry.android_anchors) >= 1, (
            f"{domain.value}: must have at least 1 android_anchor"
        )


# ---------------------------------------------------------------------------
# 5. CodeAnchor validation
# ---------------------------------------------------------------------------


class TestCodeAnchors:
    """All code anchors must have valid repo and path."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_anchors_have_non_empty_path(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for anchor in entry.v2_anchors + entry.android_anchors:
            assert len(anchor.path) > 0, (
                f"{domain.value}: CodeAnchor has empty path"
            )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_anchors_have_valid_repo(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for anchor in entry.v2_anchors:
            assert anchor.repo == "v2", (
                f"{domain.value}: v2_anchor has wrong repo: {anchor.repo}"
            )
        for anchor in entry.android_anchors:
            assert anchor.repo == "android", (
                f"{domain.value}: android_anchor has wrong repo: {anchor.repo}"
            )


# ---------------------------------------------------------------------------
# 6. ImplementationCutPoint validation
# ---------------------------------------------------------------------------


class TestImplementationCutPoints:
    """All cut points must be well-formed."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_cut_points_have_non_empty_target_path(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for cp in entry.implementation_cut_points:
            assert len(cp.target_path) > 0, (
                f"{domain.value}: cut point has empty target_path"
            )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_cut_points_have_non_empty_description(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for cp in entry.implementation_cut_points:
            assert len(cp.description) > MIN_DESCRIPTION_LENGTH, (
                f"{domain.value}: cut point description too short"
            )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_cut_points_have_valid_kind(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        valid_kinds = {k.value for k in CutPointKind}
        entry = report.domain_by_name(domain)
        for cp in entry.implementation_cut_points:
            assert cp.kind.value in valid_kinds, (
                f"{domain.value}: invalid cut point kind: {cp.kind}"
            )

    def test_new_test_cut_points_present_in_at_least_three_domains(
        self, report: FiveDomainReviewReport
    ) -> None:
        """At least 3 domains should have a NEW_TEST cut point."""
        count = 0
        for entry in report.domains:
            for cp in entry.implementation_cut_points:
                if cp.kind == CutPointKind.NEW_TEST:
                    count += 1
                    break
        assert count >= 3, (
            f"Expected NEW_TEST cut point in at least 3 domains; got {count}"
        )

    def test_new_module_cut_points_present_in_at_least_two_domains(
        self, report: FiveDomainReviewReport
    ) -> None:
        """At least 2 domains should have a NEW_MODULE cut point."""
        count = 0
        for entry in report.domains:
            for cp in entry.implementation_cut_points:
                if cp.kind == CutPointKind.NEW_MODULE:
                    count += 1
                    break
        assert count >= 2, (
            f"Expected NEW_MODULE cut point in at least 2 domains; got {count}"
        )


# ---------------------------------------------------------------------------
# 7. ModificationZone validation
# ---------------------------------------------------------------------------


class TestModificationZones:
    """All modification zones must be well-formed."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_zones_have_non_empty_file_path(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for zone in entry.modification_zones:
            assert len(zone.file_path) > 0, (
                f"{domain.value}: modification zone has empty file_path"
            )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_zones_have_non_empty_change_description(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for zone in entry.modification_zones:
            assert len(zone.change_description) > MIN_DESCRIPTION_LENGTH, (
                f"{domain.value}: modification zone change_description too short"
            )

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_all_zones_file_paths_are_python_or_test_files(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        for zone in entry.modification_zones:
            assert zone.file_path.endswith(".py"), (
                f"{domain.value}: modification zone file_path must be a .py file: {zone.file_path}"
            )


# ---------------------------------------------------------------------------
# 8. Domain maturity label correctness
# ---------------------------------------------------------------------------


class TestDomainMaturityLabels:
    """Each domain must have the correct current_maturity label."""

    def test_panel_aggregation_is_partially_established(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.UNIFIED_PANEL_AGGREGATION)
        assert entry.current_maturity == MaturityLevel.PARTIALLY_ESTABLISHED, (
            f"Expected PARTIALLY_ESTABLISHED; got {entry.current_maturity}"
        )

    def test_desktop_three_state_is_partially_established(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.DESKTOP_THREE_STATE_PRESENCE)
        assert entry.current_maturity == MaturityLevel.PARTIALLY_ESTABLISHED, (
            f"Expected PARTIALLY_ESTABLISHED; got {entry.current_maturity}"
        )

    def test_operator_actionability_is_observation_projection_only(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.OPERATOR_ACTIONABILITY)
        assert entry.current_maturity == MaturityLevel.OBSERVATION_PROJECTION_ONLY, (
            f"Expected OBSERVATION_PROJECTION_ONLY; got {entry.current_maturity}"
        )

    def test_nl_path_is_partially_established(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH)
        assert entry.current_maturity == MaturityLevel.PARTIALLY_ESTABLISHED, (
            f"Expected PARTIALLY_ESTABLISHED; got {entry.current_maturity}"
        )

    def test_multimodal_is_infra_present_not_e2e(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.MULTIMODAL_CANONICAL_PATH)
        assert entry.current_maturity == MaturityLevel.INFRA_PRESENT_NOT_E2E, (
            f"Expected INFRA_PRESENT_NOT_E2E; got {entry.current_maturity}"
        )


# ---------------------------------------------------------------------------
# 9. Domain maturity unlock labels
# ---------------------------------------------------------------------------


class TestMaturityUnlockLabels:
    """Each domain must have the correct maturity_unlock label."""

    def test_panel_aggregation_unlocks_canonical_surface(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.UNIFIED_PANEL_AGGREGATION)
        assert entry.maturity_unlock == MaturityUnlockLevel.CANONICAL_SURFACE_ESTABLISHED

    def test_desktop_presence_unlocks_coherent_joint_state(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.DESKTOP_THREE_STATE_PRESENCE)
        assert entry.maturity_unlock == MaturityUnlockLevel.COHERENT_JOINT_STATE_SURFACE

    def test_operator_unlocks_action_capable_control_plane(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.OPERATOR_ACTIONABILITY)
        assert entry.maturity_unlock == MaturityUnlockLevel.ACTION_CAPABLE_CONTROL_PLANE

    def test_nl_path_unlocks_ci_proven_e2e(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH)
        assert entry.maturity_unlock == MaturityUnlockLevel.CI_PROVEN_E2E_PATH

    def test_multimodal_unlocks_activatable_participation(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.MULTIMODAL_CANONICAL_PATH)
        assert entry.maturity_unlock == MaturityUnlockLevel.ACTIVATABLE_MULTIMODAL_PARTICIPATION


# ---------------------------------------------------------------------------
# 10. Domain-specific content validation
# ---------------------------------------------------------------------------


class TestDomainSpecificContent:
    """Key domain-specific findings must be present in established/unproven items."""

    def test_panel_aggregation_identifies_missing_unified_aggregator(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.UNIFIED_PANEL_AGGREGATION)
        all_items = entry.unproven_items + entry.partial_items
        text = " ".join(all_items).lower()
        assert "unified" in text or "aggregat" in text, (
            "Panel domain must mention unified aggregation gap"
        )

    def test_panel_aggregation_references_operator_routes(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.UNIFIED_PANEL_AGGREGATION)
        text = " ".join(entry.established_items).lower()
        assert "operator" in text or "route" in text

    def test_desktop_identifies_three_distinct_state_systems(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.DESKTOP_THREE_STATE_PRESENCE)
        established_text = " ".join(entry.established_items)
        assert "SILENT" in established_text or "LIMINAL" in established_text, (
            "Desktop domain must confirm TriState SILENT/LIMINAL/MANIFEST"
        )
        assert "DORMANT" in established_text or "ISLAND" in established_text, (
            "Desktop domain must confirm UI clothing states DORMANT/ISLAND/SIDESHEET/FULLAGENT"
        )

    def test_desktop_unproven_mentions_joint_surface_gap(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.DESKTOP_THREE_STATE_PRESENCE)
        all_items = entry.unproven_items + entry.partial_items
        text = " ".join(all_items).lower()
        assert "joint" in text or "unified" in text or "combined" in text, (
            "Desktop domain must mention missing joint projection surface"
        )

    def test_operator_confirms_all_routes_get_only(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.OPERATOR_ACTIONABILITY)
        established_text = " ".join(entry.established_items).lower()
        assert "get" in established_text or "read-only" in established_text, (
            "Operator domain must confirm GET-only routes"
        )

    def test_operator_unproven_mentions_no_post_endpoints(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.OPERATOR_ACTIONABILITY)
        all_items = entry.unproven_items
        text = " ".join(all_items).lower()
        assert "post" in text or "action" in text, (
            "Operator domain must mention absence of POST action endpoints"
        )

    def test_nl_domain_references_chat_route_and_dpr(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH)
        established_text = " ".join(entry.established_items).lower()
        assert "chat" in established_text or "desktoppresenceruntime" in established_text.replace(" ", "").lower(), (
            "NL domain must reference /api/v1/chat and DesktopPresenceRuntime"
        )

    def test_nl_domain_unproven_mentions_no_ci_e2e_test(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.NATURAL_LANGUAGE_CANONICAL_PATH)
        text = " ".join(entry.unproven_items).lower()
        assert "ci" in text or "test" in text or "mock" in text, (
            "NL domain must mention missing CI end-to-end test"
        )

    def test_multimodal_identifies_config_gate(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.MULTIMODAL_CANONICAL_PATH)
        all_items = entry.partial_items + entry.unproven_items
        text = " ".join(all_items).lower()
        assert (
            "default" in text or "disabled" in text or "gated" in text
            or "enable_multimodal_ingest" in text
        ), (
            "Multimodal domain must mention the enable_multimodal_ingest gate"
        )

    def test_multimodal_established_mentions_openclawd_integration(
        self, report: FiveDomainReviewReport
    ) -> None:
        entry = report.domain_by_name(ReviewDomain.MULTIMODAL_CANONICAL_PATH)
        text = " ".join(entry.established_items).lower()
        assert "multimodal" in text and ("openclawd" in text or "ingress" in text), (
            "Multimodal domain must mention OpenClawd multimodal ingress integration"
        )


# ---------------------------------------------------------------------------
# 11. Singleton caching and reset
# ---------------------------------------------------------------------------


class TestSingletonCaching:
    """Singleton caching and reset work correctly."""

    def test_get_returns_same_object_on_second_call(self) -> None:
        reset_five_domain_review()
        r1 = get_five_domain_review()
        r2 = get_five_domain_review()
        assert r1 is r2

    def test_reset_clears_cache(self) -> None:
        reset_five_domain_review()
        r1 = get_five_domain_review()
        reset_five_domain_review()
        r2 = get_five_domain_review()
        assert r1 is not r2

    def test_build_returns_fresh_object_each_time(self) -> None:
        r1 = build_five_domain_review()
        r2 = build_five_domain_review()
        assert r1 is not r2

    def test_get_after_reset_has_correct_domain_count(self) -> None:
        reset_five_domain_review()
        r = get_five_domain_review()
        assert len(r.domains) == 5


# ---------------------------------------------------------------------------
# 12. Invariant checker
# ---------------------------------------------------------------------------


class TestInvariantChecker:
    """assert_five_domain_review_invariants() must pass cleanly."""

    def test_invariants_pass(self) -> None:
        reset_five_domain_review()
        assert_five_domain_review_invariants()


# ---------------------------------------------------------------------------
# 13. JSON serialization
# ---------------------------------------------------------------------------


class TestJsonSerialization:
    """Report must serialise to JSON cleanly and round-trip."""

    def test_to_json_does_not_raise(self, report: FiveDomainReviewReport) -> None:
        js = report.to_json()
        assert isinstance(js, str)
        assert len(js) > 1000

    def test_json_is_valid(self, report: FiveDomainReviewReport) -> None:
        js = report.to_json()
        data = json.loads(js)
        assert isinstance(data, dict)

    def test_json_has_authority(self, report: FiveDomainReviewReport) -> None:
        data = json.loads(report.to_json())
        assert "authority" in data
        assert data["authority"] == FIVE_DOMAIN_REVIEW_AUTHORITY

    def test_json_has_version(self, report: FiveDomainReviewReport) -> None:
        data = json.loads(report.to_json())
        assert "version" in data

    def test_json_has_five_domains(self, report: FiveDomainReviewReport) -> None:
        data = json.loads(report.to_json())
        assert "domains" in data
        assert len(data["domains"]) == 5

    def test_json_domain_has_all_required_keys(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        required_keys = {
            "domain",
            "current_maturity",
            "canonical_path_summary",
            "established_items",
            "partial_items",
            "unproven_items",
            "incompleteness_rationale",
            "v2_anchors",
            "android_anchors",
            "implementation_cut_points",
            "modification_zones",
            "maturity_unlock",
            "maturity_unlock_description",
        }
        for d in data["domains"]:
            missing = required_keys - set(d.keys())
            assert not missing, (
                f"Domain {d.get('domain', '?')}: missing JSON keys: {missing}"
            )

    def test_json_anchor_has_all_required_keys(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        for domain_dict in data["domains"]:
            for anchor in domain_dict["v2_anchors"] + domain_dict["android_anchors"]:
                for key in ("repo", "path", "available", "note"):
                    assert key in anchor, (
                        f"CodeAnchor missing key '{key}' in domain {domain_dict['domain']}"
                    )

    def test_json_cut_point_has_all_required_keys(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        for domain_dict in data["domains"]:
            for cp in domain_dict["implementation_cut_points"]:
                for key in ("kind", "target_path", "description", "depends_on"):
                    assert key in cp, (
                        f"CutPoint missing key '{key}' in domain {domain_dict['domain']}"
                    )

    def test_json_mod_zone_has_all_required_keys(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        for domain_dict in data["domains"]:
            for zone in domain_dict["modification_zones"]:
                for key in ("file_path", "scope", "change_description"):
                    assert key in zone, (
                        f"ModZone missing key '{key}' in domain {domain_dict['domain']}"
                    )

    def test_json_round_trip_preserves_domain_names(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        domain_values = {d["domain"] for d in data["domains"]}
        expected = {rd.value for rd in ReviewDomain}
        assert domain_values == expected

    def test_json_round_trip_preserves_maturity_labels(
        self, report: FiveDomainReviewReport
    ) -> None:
        data = json.loads(report.to_json())
        for d in data["domains"]:
            assert d["current_maturity"] in {m.value for m in MaturityLevel}

    def test_json_indent_2_produces_multiline(
        self, report: FiveDomainReviewReport
    ) -> None:
        js = report.to_json(indent=2)
        assert "\n" in js


# ---------------------------------------------------------------------------
# 14. domain_by_name() helper
# ---------------------------------------------------------------------------


class TestDomainByName:
    """domain_by_name() must return correct entries and raise on unknown."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_domain_by_name_returns_correct_entry(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        assert entry.domain == domain

    def test_domain_by_name_raises_key_error_for_unknown(
        self, report: FiveDomainReviewReport
    ) -> None:
        # Use a simple namespace object with a .value attribute that matches no domain
        import types
        fake_domain = types.SimpleNamespace(value="NONEXISTENT_DOMAIN")
        with pytest.raises(KeyError):
            report.domain_by_name(fake_domain)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 15. Implementation cut point dependency chains
# ---------------------------------------------------------------------------


class TestCutPointDependencies:
    """Cut point dependency chains must be internally consistent."""

    @pytest.mark.parametrize("domain", list(ReviewDomain))
    def test_dependencies_reference_valid_target_paths(
        self, report: FiveDomainReviewReport, domain: ReviewDomain
    ) -> None:
        entry = report.domain_by_name(domain)
        all_paths = {cp.target_path for cp in entry.implementation_cut_points}
        for cp in entry.implementation_cut_points:
            for dep in cp.depends_on:
                assert dep in all_paths, (
                    f"{domain.value}: cut point {cp.target_path!r} depends on "
                    f"{dep!r} which is not in the cut point list"
                )
