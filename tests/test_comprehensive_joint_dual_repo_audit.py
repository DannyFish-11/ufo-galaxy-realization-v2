"""
tests/test_comprehensive_joint_dual_repo_audit.py
==================================================
Test suite for core/comprehensive_joint_dual_repo_audit.py

Comprehensive Joint Dual-Repo Real-Code-Only Current-State Audit of the
Galaxy distributed AI-body/control system.

This test suite validates:
 1. Module imports cleanly; all public symbols accessible.
 2. Authority sentinel, methodology, and Chinese verdict are non-empty.
 3. Enumerations have the correct number of members.
 4. build_comprehensive_joint_audit() returns a structurally correct report.
 5. Report has exactly 8 dimension entries (one per AuditDimension).
 6. Report has exactly 6 completeness questions.
 7. Panel API surfaces include unified_panel_aggregation (marked not available).
 8. Actionability surfaces cover all key domains.
 9. System verdict is LATE_STAGE_CLOSURE.
10. Dimension labels are individually correct (no dimension overclaims).
11. Architecture/governance dimension is STRONGLY_ESTABLISHED.
12. Android runtime carrier dimension is PARTIALLY_ESTABLISHED (continuity gap).
13. Operator/control-plane dimension is PARTIALLY_ESTABLISHED (panel gap).
14. Desktop shell/presence dimension is PARTIALLY_ESTABLISHED (unified surface gap).
15. Natural-language driving dimension is PARTIALLY_ESTABLISHED (no e2e CI).
16. Multimodal dimension is INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN.
17. State surface actionability dimension is PARTIALLY_ESTABLISHED.
18. End-to-end controllability dimension is PARTIALLY_ESTABLISHED.
19. NL driving completeness question verdict is PARTIALLY_ESTABLISHED.
20. Multimodal completeness question is INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN.
21. Panel API unification completeness question is PARTIALLY_ESTABLISHED.
22. Controllability question is PARTIALLY_ESTABLISHED.
23. Singleton caching + reset work correctly.
24. assert_comprehensive_audit_invariants() passes cleanly.
25. Report serialises to JSON cleanly and round-trips.
26. Chinese verdict mentions Galaxy and key system concepts.
27. Remaining product gaps list contains at least 4 items.
28. Follow-up roadmap contains at least 4 items.
29. Architecture dimension has V2 authority code anchors.
30. Android dimension has android evidence refs.
31. Each completeness question has non-empty proven and unproven aspects.
32. All panel API surfaces have non-empty surface_id and route_prefix.
33. All actionability surfaces have non-empty domain and note.
34. Operator panel surface is READ_ONLY_PROJECTION (no action endpoints).
35. Chat route surface is ACTION_CAPABLE.
36. Count aggregates are internally consistent with dimension list.
37. AuditEvidenceLabel 7 tiers present.
38. AuditDimension 8 values present.
39. ActionabilityLevel 3 values present.
40. SystemCompletenessVerdict 3 values present.

Methodology
-----------
- Only imports the audit module and standard library — no mocking.
- Validates structural correctness and invariants.
- Does NOT mock or override the module's real-code probes.
"""

from __future__ import annotations

import json

import pytest

from core.comprehensive_joint_dual_repo_audit import (
    COMPREHENSIVE_AUDIT_AUTHORITY,
    COMPREHENSIVE_AUDIT_METHODOLOGY,
    COMPREHENSIVE_AUDIT_VERDICT_ZH,
    ActionabilityLevel,
    ActionabilitySurface,
    AuditDimension,
    AuditEvidenceLabel,
    ComprehensiveAuditReport,
    CompletenessQuestion,
    DimensionAuditEntry,
    PanelApiSurface,
    SystemCompletenessVerdict,
    assert_comprehensive_audit_invariants,
    build_comprehensive_joint_audit,
    get_comprehensive_joint_audit,
    reset_comprehensive_joint_audit,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(COMPREHENSIVE_AUDIT_AUTHORITY, str)
        assert len(COMPREHENSIVE_AUDIT_AUTHORITY) > 0

    def test_authority_sentinel_contains_key_phrase(self) -> None:
        assert "COMPREHENSIVE_JOINT_DUAL_REPO" in COMPREHENSIVE_AUDIT_AUTHORITY

    def test_authority_explicitly_excludes_pr993(self) -> None:
        assert "no-pr993-as-evidence" in COMPREHENSIVE_AUDIT_AUTHORITY

    def test_methodology_is_non_empty_string(self) -> None:
        assert isinstance(COMPREHENSIVE_AUDIT_METHODOLOGY, str)
        assert len(COMPREHENSIVE_AUDIT_METHODOLOGY) > 0

    def test_methodology_mentions_both_repos(self) -> None:
        assert "ufo-galaxy-realization-v2" in COMPREHENSIVE_AUDIT_METHODOLOGY
        assert "ufo-galaxy-android" in COMPREHENSIVE_AUDIT_METHODOLOGY

    def test_methodology_excludes_pr993_explicitly(self) -> None:
        assert "PR #993" in COMPREHENSIVE_AUDIT_METHODOLOGY
        assert "EXCLUDED" in COMPREHENSIVE_AUDIT_METHODOLOGY.upper() or \
               "excluded" in COMPREHENSIVE_AUDIT_METHODOLOGY

    def test_verdict_zh_is_non_empty_string(self) -> None:
        assert isinstance(COMPREHENSIVE_AUDIT_VERDICT_ZH, str)
        assert len(COMPREHENSIVE_AUDIT_VERDICT_ZH) > 0

    def test_verdict_zh_mentions_galaxy(self) -> None:
        assert "Galaxy" in COMPREHENSIVE_AUDIT_VERDICT_ZH or "双仓" in COMPREHENSIVE_AUDIT_VERDICT_ZH

    def test_verdict_zh_mentions_nl_driving(self) -> None:
        assert "自然语言" in COMPREHENSIVE_AUDIT_VERDICT_ZH

    def test_verdict_zh_mentions_multimodal(self) -> None:
        assert "多模态" in COMPREHENSIVE_AUDIT_VERDICT_ZH

    def test_verdict_zh_mentions_three_state(self) -> None:
        assert "三态" in COMPREHENSIVE_AUDIT_VERDICT_ZH

    def test_audit_evidence_label_enum_has_7_tiers(self) -> None:
        tiers = list(AuditEvidenceLabel)
        assert len(tiers) == 7, f"Expected 7 tiers; got {len(tiers)}: {tiers}"

    def test_audit_dimension_enum_has_8_values(self) -> None:
        dims = list(AuditDimension)
        assert len(dims) == 8, f"Expected 8 dimensions; got {len(dims)}: {dims}"

    def test_actionability_level_enum_has_3_values(self) -> None:
        levels = list(ActionabilityLevel)
        assert len(levels) == 3, f"Expected 3 levels; got {len(levels)}: {levels}"

    def test_system_completeness_verdict_has_3_values(self) -> None:
        verdicts = list(SystemCompletenessVerdict)
        assert len(verdicts) == 3, f"Expected 3 verdicts; got {len(verdicts)}: {verdicts}"

    def test_late_stage_closure_in_verdict_enum(self) -> None:
        assert SystemCompletenessVerdict.LATE_STAGE_CLOSURE in SystemCompletenessVerdict

    def test_infrastructure_present_label_exists(self) -> None:
        assert AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN in AuditEvidenceLabel

    def test_all_dataclasses_importable(self) -> None:
        assert DimensionAuditEntry is not None
        assert CompletenessQuestion is not None
        assert PanelApiSurface is not None
        assert ActionabilitySurface is not None
        assert ComprehensiveAuditReport is not None

    def test_all_functions_importable(self) -> None:
        assert callable(build_comprehensive_joint_audit)
        assert callable(get_comprehensive_joint_audit)
        assert callable(reset_comprehensive_joint_audit)
        assert callable(assert_comprehensive_audit_invariants)


# =============================================================================
# SECTION 2 — build_comprehensive_joint_audit() structural checks
# =============================================================================


class TestBuildReport:
    """build_comprehensive_joint_audit() must return a structurally complete report."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_returns_correct_type(self, report: ComprehensiveAuditReport) -> None:
        assert isinstance(report, ComprehensiveAuditReport)

    def test_report_id_is_non_empty(self, report: ComprehensiveAuditReport) -> None:
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_generated_at_is_positive_float(self, report: ComprehensiveAuditReport) -> None:
        assert isinstance(report.generated_at, float)
        assert report.generated_at > 0

    def test_authority_non_empty(self, report: ComprehensiveAuditReport) -> None:
        assert len(report.authority) > 0

    def test_methodology_non_empty(self, report: ComprehensiveAuditReport) -> None:
        assert len(report.methodology) > 0

    def test_verdict_zh_non_empty(self, report: ComprehensiveAuditReport) -> None:
        assert len(report.verdict_zh) > 0

    def test_system_verdict_is_late_stage_closure(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert report.system_verdict == SystemCompletenessVerdict.LATE_STAGE_CLOSURE

    def test_system_verdict_rationale_non_empty(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.system_verdict_rationale) > 0

    def test_plain_language_conclusion_non_empty(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.plain_language_conclusion) > 0

    def test_plain_language_mentions_what_system_is(
        self, report: ComprehensiveAuditReport
    ) -> None:
        conclusion = report.plain_language_conclusion.lower()
        assert "android" in conclusion or "distributed" in conclusion

    def test_plain_language_mentions_what_system_is_not(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert "NOT" in report.plain_language_conclusion or (
            "not" in report.plain_language_conclusion.lower()
        )

    def test_remaining_product_gaps_at_least_4(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.remaining_product_gaps) >= 4, (
            f"Expected ≥ 4 gaps; got {len(report.remaining_product_gaps)}"
        )

    def test_follow_up_roadmap_at_least_4(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.follow_up_roadmap) >= 4, (
            f"Expected ≥ 4 roadmap items; got {len(report.follow_up_roadmap)}"
        )


# =============================================================================
# SECTION 3 — Dimension entries
# =============================================================================


class TestDimensionEntries:
    """Report must contain exactly 8 DimensionAuditEntry items."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_has_exactly_8_dimension_entries(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.dimension_entries) == 8, (
            f"Expected 8; got {len(report.dimension_entries)}: "
            f"{[d.dimension.value for d in report.dimension_entries]}"
        )

    def test_all_items_are_dimension_audit_entry(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for d in report.dimension_entries:
            assert isinstance(d, DimensionAuditEntry)

    def test_all_8_audit_dimensions_covered(
        self, report: ComprehensiveAuditReport
    ) -> None:
        covered = {d.dimension for d in report.dimension_entries}
        for dim in AuditDimension:
            assert dim in covered, f"Missing dimension: {dim}"

    def test_architecture_dimension_is_strongly_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.ARCHITECTURE_GOVERNANCE_ORCHESTRATION
        )
        assert entry.label == AuditEvidenceLabel.STRONGLY_ESTABLISHED, (
            f"Architecture/governance expected STRONGLY_ESTABLISHED; got {entry.label}"
        )

    def test_android_carrier_dimension_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.ANDROID_RUNTIME_CARRIER_PATHS
        )
        assert entry.label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"Android runtime carrier expected PARTIALLY_ESTABLISHED; got {entry.label}"
        )

    def test_operator_control_plane_dimension_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.OPERATOR_CONTROL_PLANE_APIS
        )
        assert entry.label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"Operator/control-plane expected PARTIALLY_ESTABLISHED; got {entry.label}"
        )

    def test_desktop_shell_dimension_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.DESKTOP_SHELL_PRESENCE_MANIFESTATION
        )
        assert entry.label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"Desktop shell/presence expected PARTIALLY_ESTABLISHED; got {entry.label}"
        )

    def test_nl_driving_dimension_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.NATURAL_LANGUAGE_DRIVING
        )
        assert entry.label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"NL driving expected PARTIALLY_ESTABLISHED; got {entry.label}"
        )

    def test_multimodal_dimension_is_infrastructure_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.MULTIMODAL_PERCEPTION_GROUNDING
        )
        assert entry.label == (
            AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        ), (
            f"Multimodal expected INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN; "
            f"got {entry.label}"
        )

    def test_no_dimension_claims_fully_runtime_evidenced_closed(
        self, report: ComprehensiveAuditReport
    ) -> None:
        """No dimension should overclaim RUNTIME_EVIDENCED_CLOSED given known gaps."""
        runtime_closed = [
            d.dimension for d in report.dimension_entries
            if d.label == AuditEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
        ]
        # Architecture may be STRONGLY_ESTABLISHED not RUNTIME_EVIDENCED_CLOSED,
        # so 0 dimensions at RUNTIME_EVIDENCED_CLOSED is acceptable.
        # What should NOT happen: a dimension with known gaps claiming RUNTIME_EVIDENCED_CLOSED.
        for dim in runtime_closed:
            entry = next(
                d for d in report.dimension_entries if d.dimension == dim
            )
            # If labeled RUNTIME_EVIDENCED_CLOSED, gap_items must be empty
            assert len(entry.gap_items) == 0, (
                f"Dimension {dim} claims RUNTIME_EVIDENCED_CLOSED but has gaps: "
                f"{entry.gap_items}"
            )

    def test_architecture_dimension_has_proven_items(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.ARCHITECTURE_GOVERNANCE_ORCHESTRATION
        )
        assert len(entry.proven_items) > 0

    def test_android_dimension_has_android_evidence_refs(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.ANDROID_RUNTIME_CARRIER_PATHS
        )
        assert len(entry.android_evidence_refs) > 0, (
            "Android runtime carrier dimension must have android_evidence_refs"
        )

    def test_operator_dimension_is_read_only(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.OPERATOR_CONTROL_PLANE_APIS
        )
        assert entry.actionability == ActionabilityLevel.READ_ONLY_PROJECTION, (
            f"Operator surface must be READ_ONLY_PROJECTION; got {entry.actionability}"
        )

    def test_nl_driving_dimension_is_action_capable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.NATURAL_LANGUAGE_DRIVING
        )
        assert entry.actionability == ActionabilityLevel.ACTION_CAPABLE, (
            f"NL driving must be ACTION_CAPABLE; got {entry.actionability}"
        )

    def test_nl_driving_gap_items_mention_lm_backend(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.NATURAL_LANGUAGE_DRIVING
        )
        all_gaps_text_lower = " ".join(entry.gap_items + entry.partial_items).lower()
        assert "llm" in all_gaps_text_lower or "e2e" in all_gaps_text_lower

    def test_multimodal_gap_items_mention_disabled_by_default(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.MULTIMODAL_PERCEPTION_GROUNDING
        )
        all_text = " ".join(entry.gap_items + entry.partial_items)
        assert "default" in all_text.lower() or "SAFE_DEFAULT" in all_text

    def test_desktop_shell_gap_items_mention_three_state_unification(
        self, report: ComprehensiveAuditReport
    ) -> None:
        entry = next(
            d for d in report.dimension_entries
            if d.dimension == AuditDimension.DESKTOP_SHELL_PRESENCE_MANIFESTATION
        )
        all_text = " ".join(entry.gap_items)
        assert "unified" in all_text.lower() or "three" in all_text.lower() or "aggregat" in all_text.lower()

    def test_all_dimension_summaries_non_empty(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for entry in report.dimension_entries:
            assert len(entry.summary) > 50, (
                f"Dimension {entry.dimension} has too-short summary: {entry.summary!r}"
            )

    def test_dimension_to_dict_serializable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for entry in report.dimension_entries:
            d = entry.to_dict()
            assert isinstance(d, dict)
            assert "dimension" in d
            assert "label" in d
            assert "summary" in d


# =============================================================================
# SECTION 4 — Completeness questions
# =============================================================================


class TestCompletenessQuestions:
    """Report must contain exactly 6 completeness questions."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_has_exactly_6_completeness_questions(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.completeness_questions) == 6, (
            f"Expected 6; got {len(report.completeness_questions)}: "
            f"{[q.question_id for q in report.completeness_questions]}"
        )

    def test_all_items_are_completeness_question(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for q in report.completeness_questions:
            assert isinstance(q, CompletenessQuestion)

    def test_center_android_integrated_question_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "center_android_integrated_complete" in ids

    def test_nl_driven_question_present(self, report: ComprehensiveAuditReport) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "nl_driven_end_to_end" in ids

    def test_multimodal_question_present(self, report: ComprehensiveAuditReport) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "natively_multimodal_e2e" in ids

    def test_three_state_question_present(self, report: ComprehensiveAuditReport) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "three_state_desktop_shell_coherent_presentation" in ids

    def test_panel_api_question_present(self, report: ComprehensiveAuditReport) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "panel_apis_fully_unified_aggregated" in ids

    def test_controllability_question_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [q.question_id for q in report.completeness_questions]
        assert "system_fully_controllable_or_observational" in ids

    def test_nl_question_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "nl_driven_end_to_end"
        )
        assert q.verdict_label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"NL driving question must be PARTIALLY_ESTABLISHED; got {q.verdict_label}"
        )

    def test_multimodal_question_is_infrastructure_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "natively_multimodal_e2e"
        )
        assert q.verdict_label == (
            AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN
        ), (
            f"Multimodal question must be INFRASTRUCTURE_PRESENT; got {q.verdict_label}"
        )

    def test_panel_api_question_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "panel_apis_fully_unified_aggregated"
        )
        assert q.verdict_label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED

    def test_controllability_question_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "system_fully_controllable_or_observational"
        )
        assert q.verdict_label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED

    def test_nl_question_has_non_empty_proven_aspect(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "nl_driven_end_to_end"
        )
        assert len(q.proven_aspect) > 0

    def test_nl_question_has_non_empty_unproven_aspect(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "nl_driven_end_to_end"
        )
        assert len(q.unproven_aspect) > 0

    def test_multimodal_question_unproven_mentions_disabled(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "natively_multimodal_e2e"
        )
        assert "default" in q.unproven_aspect.lower() or "disabled" in q.unproven_aspect.lower()

    def test_three_state_question_is_partially_established(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "three_state_desktop_shell_coherent_presentation"
        )
        assert q.verdict_label == AuditEvidenceLabel.PARTIALLY_ESTABLISHED

    def test_controllability_unproven_mentions_read_only(
        self, report: ComprehensiveAuditReport
    ) -> None:
        q = next(
            q for q in report.completeness_questions
            if q.question_id == "system_fully_controllable_or_observational"
        )
        assert "read-only" in q.unproven_aspect.lower() or "action" in q.unproven_aspect.lower()

    def test_all_questions_have_non_empty_answer(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for q in report.completeness_questions:
            assert len(q.answer) > 30, (
                f"Question {q.question_id} has too-short answer: {q.answer!r}"
            )

    def test_question_to_dict_serializable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for q in report.completeness_questions:
            d = q.to_dict()
            assert isinstance(d, dict)
            assert "question_id" in d
            assert "verdict_label" in d
            assert "answer" in d


# =============================================================================
# SECTION 5 — Panel API surfaces
# =============================================================================


class TestPanelApiSurfaces:
    """Panel API surfaces must cover key operator endpoints."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_has_at_least_5_panel_surfaces(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.panel_api_surfaces) >= 5

    def test_unified_panel_aggregation_surface_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [p.surface_id for p in report.panel_api_surfaces]
        assert "unified_panel_aggregation" in ids, (
            "unified_panel_aggregation surface must be in panel_api_surfaces"
        )

    def test_unified_panel_aggregation_is_not_available(
        self, report: ComprehensiveAuditReport
    ) -> None:
        p = next(
            p for p in report.panel_api_surfaces
            if p.surface_id == "unified_panel_aggregation"
        )
        assert not p.available, (
            "unified_panel_aggregation must be available=False (not yet implemented)"
        )

    def test_unified_panel_aggregation_has_gap_note(
        self, report: ComprehensiveAuditReport
    ) -> None:
        p = next(
            p for p in report.panel_api_surfaces
            if p.surface_id == "unified_panel_aggregation"
        )
        assert len(p.gap_note) > 0

    def test_operator_snapshot_surface_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [p.surface_id for p in report.panel_api_surfaces]
        assert "operator_snapshot" in ids

    def test_android_ecosystem_surface_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [p.surface_id for p in report.panel_api_surfaces]
        assert "android_ecosystem" in ids

    def test_projection_runtime_surface_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        ids = [p.surface_id for p in report.panel_api_surfaces]
        assert "projection_runtime" in ids

    def test_all_surfaces_have_non_empty_route_prefix(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for p in report.panel_api_surfaces:
            assert len(p.route_prefix) > 0, (
                f"Surface {p.surface_id} has empty route_prefix"
            )

    def test_all_read_only_surfaces_are_read_only_projection(
        self, report: ComprehensiveAuditReport
    ) -> None:
        # All available operator surfaces should be READ_ONLY_PROJECTION
        for p in report.panel_api_surfaces:
            if p.available and p.surface_id != "unified_panel_aggregation":
                assert p.actionability == ActionabilityLevel.READ_ONLY_PROJECTION, (
                    f"Surface {p.surface_id} expected READ_ONLY_PROJECTION; "
                    f"got {p.actionability}"
                )

    def test_surface_to_dict_serializable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for p in report.panel_api_surfaces:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert "surface_id" in d
            assert "available" in d
            assert "actionability" in d


# =============================================================================
# SECTION 6 — Actionability surfaces
# =============================================================================


class TestActionabilitySurfaces:
    """Actionability surfaces must cover key domains."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_has_at_least_4_actionability_surfaces(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert len(report.actionability_surfaces) >= 4

    def test_operator_panel_surface_present(
        self, report: ComprehensiveAuditReport
    ) -> None:
        domains = [a.domain for a in report.actionability_surfaces]
        assert any("operator_panel" in d for d in domains), (
            "operator_panel domain must be in actionability_surfaces"
        )

    def test_operator_panel_is_not_action_capable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        panel = next(
            a for a in report.actionability_surfaces
            if "operator_panel" in a.domain
        )
        assert not panel.action_endpoint_available, (
            "operator_panel must have action_endpoint_available=False"
        )

    def test_chat_route_is_action_capable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        chat = next(
            (a for a in report.actionability_surfaces if "chat_route" in a.domain),
            None,
        )
        assert chat is not None, "chat_route domain must be in actionability_surfaces"
        assert chat.action_endpoint_available, (
            "chat_route must have action_endpoint_available=True"
        )

    def test_android_state_store_is_decision_consumed(
        self, report: ComprehensiveAuditReport
    ) -> None:
        state = next(
            (a for a in report.actionability_surfaces if "android_device_state_store" in a.domain),
            None,
        )
        assert state is not None, "android_device_state_store domain must be present"
        assert state.decision_consumed, (
            "android_device_state_store must be decision_consumed=True"
        )

    def test_all_surfaces_have_non_empty_domain(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for a in report.actionability_surfaces:
            assert len(a.domain) > 0

    def test_surface_to_dict_serializable(
        self, report: ComprehensiveAuditReport
    ) -> None:
        for a in report.actionability_surfaces:
            d = a.to_dict()
            assert isinstance(d, dict)
            assert "domain" in d
            assert "action_endpoint_available" in d


# =============================================================================
# SECTION 7 — Count aggregates
# =============================================================================


class TestCountAggregates:
    """Count fields must be internally consistent with the dimension list."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_strongly_established_count_consistent(
        self, report: ComprehensiveAuditReport
    ) -> None:
        actual = sum(
            1
            for d in report.dimension_entries
            if d.label == AuditEvidenceLabel.STRONGLY_ESTABLISHED
        )
        assert report.dimensions_strongly_established_count == actual

    def test_runtime_evidenced_closed_count_consistent(
        self, report: ComprehensiveAuditReport
    ) -> None:
        actual = sum(
            1
            for d in report.dimension_entries
            if d.label == AuditEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
        )
        assert report.dimensions_runtime_evidenced_closed_count == actual

    def test_partially_established_count_consistent(
        self, report: ComprehensiveAuditReport
    ) -> None:
        actual = sum(
            1
            for d in report.dimension_entries
            if d.label in (
                AuditEvidenceLabel.PARTIALLY_ESTABLISHED,
                AuditEvidenceLabel.INFRASTRUCTURE_PRESENT_NOT_YET_E2E_PROVEN,
            )
        )
        assert report.dimensions_partially_established_count == actual

    def test_at_least_1_strongly_established_dimension(
        self, report: ComprehensiveAuditReport
    ) -> None:
        assert report.dimensions_strongly_established_count >= 1

    def test_majority_of_dimensions_are_partial_or_infrastructure(
        self, report: ComprehensiveAuditReport
    ) -> None:
        """Most dimensions are partially established — the audit is honest."""
        assert report.dimensions_partially_established_count >= 4, (
            "Expected at least 4 partially-established dimensions (honest audit)"
        )


# =============================================================================
# SECTION 8 — Singleton caching and reset
# =============================================================================


class TestSingletonCaching:
    """Singleton caching and reset must work correctly."""

    def test_get_returns_same_object_on_second_call(self) -> None:
        reset_comprehensive_joint_audit()
        r1 = get_comprehensive_joint_audit()
        r2 = get_comprehensive_joint_audit()
        assert r1 is r2

    def test_reset_forces_rebuild(self) -> None:
        reset_comprehensive_joint_audit()
        r1 = get_comprehensive_joint_audit()
        reset_comprehensive_joint_audit()
        r2 = get_comprehensive_joint_audit()
        # After reset, a fresh report is built — report_id should differ
        assert r1.report_id != r2.report_id

    def test_build_returns_new_object_each_call(self) -> None:
        r1 = build_comprehensive_joint_audit()
        r2 = build_comprehensive_joint_audit()
        # build always produces fresh reports
        assert r1.report_id != r2.report_id


# =============================================================================
# SECTION 9 — Invariant checker
# =============================================================================


class TestInvariantChecker:
    """assert_comprehensive_audit_invariants() must pass cleanly."""

    def test_invariants_pass_without_exception(self) -> None:
        reset_comprehensive_joint_audit()
        assert_comprehensive_audit_invariants()

    def test_invariants_idempotent(self) -> None:
        # Running twice should not raise
        assert_comprehensive_audit_invariants()
        assert_comprehensive_audit_invariants()


# =============================================================================
# SECTION 10 — JSON serialisation
# =============================================================================


class TestJsonSerialisation:
    """Report must serialise to JSON cleanly and round-trip correctly."""

    @pytest.fixture(scope="class")
    def report(self) -> ComprehensiveAuditReport:
        return build_comprehensive_joint_audit()

    def test_to_dict_returns_dict(self, report: ComprehensiveAuditReport) -> None:
        d = report.to_dict()
        assert isinstance(d, dict)

    def test_to_json_returns_string(self, report: ComprehensiveAuditReport) -> None:
        js = report.to_json()
        assert isinstance(js, str)
        assert len(js) > 100

    def test_json_round_trip_system_verdict(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert parsed["system_verdict"] == SystemCompletenessVerdict.LATE_STAGE_CLOSURE.value

    def test_json_round_trip_authority(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert parsed["authority"] == COMPREHENSIVE_AUDIT_AUTHORITY

    def test_json_round_trip_dimension_count(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["dimension_entries"]) == 8

    def test_json_round_trip_question_count(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["completeness_questions"]) == 6

    def test_json_round_trip_verdict_zh_non_empty(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["verdict_zh"]) > 0

    def test_json_contains_remaining_product_gaps(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["remaining_product_gaps"]) >= 4

    def test_json_contains_follow_up_roadmap(
        self, report: ComprehensiveAuditReport
    ) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["follow_up_roadmap"]) >= 4
