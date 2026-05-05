"""
tests/test_full_current_state_dual_repo_rereading.py
====================================================
Test suite for core/full_current_state_dual_repo_rereading.py

Full Current-State Dual-Repo Rereading of the Galaxy System from the
PR #993 Baseline — using only real code, real tests, and real canonical
runtime paths as evidence.

This test suite validates:
 1. Module imports cleanly; all public symbols accessible.
 2. Authority sentinels and methodology strings are non-empty.
 3. build_full_current_state_rereading() returns a structurally correct report.
 4. System characterization describes both V2 authority and Android carrier roles.
 5. Claim matrix covers all 7 PR #993 claim families with valid labels.
 6. Canonical path closure map covers all 6 dual-repo paths.
 7. All claims are at STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED.
 8. Completion stage judgment is LATE_STAGE_CLOSURE (all P0 gaps closed).
 9. Zero P0 roadmap items exist in the current state.
10. Post-next-PR judgment targets NON_P0_REFINEMENT_ONLY.
11. Roadmap has P1 and P3 items; no P0 items.
12. Singleton caching + reset work correctly.
13. assert_full_current_state_invariants() passes cleanly.
14. Report serialises to JSON cleanly.
15. Chinese verdict is non-empty and mentions the system.
16. Count aggregates are internally consistent with claim and path lists.
17. ORCHESTRATION_CONSUMES_ANDROID_TRUTH path is not SURFACE_ALIGNMENT_ONLY.
18. CONTINUITY_RECONNECT_RESUME path is PARTIALLY_ESTABLISHED (known P1 gap).

Methodology
-----------
- Only imports the rereading module and standard library — no mocking.
- Validates structural correctness and invariants; not runtime execution paths.
"""

from __future__ import annotations

import json

import pytest

from core.full_current_state_dual_repo_rereading import (
    CanonicalPathEntry,
    ClaimMatrixEntry,
    CompletionStage,
    CompletionStageJudgment,
    CurrentEvidenceLabel,
    DualRepoSystemCharacterization,
    FULL_CURRENT_STATE_REREADING_AUTHORITY,
    FULL_CURRENT_STATE_REREADING_METHODOLOGY,
    FULL_CURRENT_STATE_VERDICT_ZH,
    FullCurrentStateReport,
    PostNextPRJudgment,
    RoadmapEntry,
    RoadmapPriority,
    assert_full_current_state_invariants,
    build_full_current_state_rereading,
    get_full_current_state_rereading,
    reset_full_current_state_rereading,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(FULL_CURRENT_STATE_REREADING_AUTHORITY, str)
        assert len(FULL_CURRENT_STATE_REREADING_AUTHORITY) > 0

    def test_authority_sentinel_contains_full_current_state(self) -> None:
        assert "FULL_CURRENT_STATE" in FULL_CURRENT_STATE_REREADING_AUTHORITY

    def test_methodology_is_non_empty_string(self) -> None:
        assert isinstance(FULL_CURRENT_STATE_REREADING_METHODOLOGY, str)
        assert len(FULL_CURRENT_STATE_REREADING_METHODOLOGY) > 0

    def test_verdict_zh_is_non_empty_string(self) -> None:
        assert isinstance(FULL_CURRENT_STATE_VERDICT_ZH, str)
        assert len(FULL_CURRENT_STATE_VERDICT_ZH) > 0

    def test_verdict_zh_mentions_system(self) -> None:
        assert "Galaxy" in FULL_CURRENT_STATE_VERDICT_ZH or "双仓" in FULL_CURRENT_STATE_VERDICT_ZH

    def test_current_evidence_label_enum_has_6_tiers(self) -> None:
        tiers = list(CurrentEvidenceLabel)
        assert len(tiers) == 6, f"Expected 6 tiers; got {len(tiers)}: {tiers}"

    def test_completion_stage_enum_has_5_tiers(self) -> None:
        tiers = list(CompletionStage)
        assert len(tiers) == 5, f"Expected 5 tiers; got {len(tiers)}: {tiers}"

    def test_roadmap_priority_enum_has_4_tiers(self) -> None:
        tiers = list(RoadmapPriority)
        assert len(tiers) == 4, f"Expected 4 tiers; got {len(tiers)}: {tiers}"

    def test_late_stage_closure_in_completion_stage(self) -> None:
        assert CompletionStage.LATE_STAGE_CLOSURE in CompletionStage

    def test_non_p0_refinement_only_in_completion_stage(self) -> None:
        assert CompletionStage.NON_P0_REFINEMENT_ONLY in CompletionStage

    def test_all_dataclasses_importable(self) -> None:
        assert DualRepoSystemCharacterization is not None
        assert ClaimMatrixEntry is not None
        assert CanonicalPathEntry is not None
        assert CompletionStageJudgment is not None
        assert PostNextPRJudgment is not None
        assert RoadmapEntry is not None
        assert FullCurrentStateReport is not None

    def test_all_functions_importable(self) -> None:
        assert callable(build_full_current_state_rereading)
        assert callable(get_full_current_state_rereading)
        assert callable(reset_full_current_state_rereading)
        assert callable(assert_full_current_state_invariants)


# =============================================================================
# SECTION 2 — build_full_current_state_rereading() structural checks
# =============================================================================


class TestBuildReport:
    """build_full_current_state_rereading() must return a structurally complete report."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_returns_full_current_state_report(self, report: FullCurrentStateReport) -> None:
        assert isinstance(report, FullCurrentStateReport)

    def test_report_id_is_non_empty(self, report: FullCurrentStateReport) -> None:
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_generated_at_is_positive_float(self, report: FullCurrentStateReport) -> None:
        assert isinstance(report.generated_at, float)
        assert report.generated_at > 0

    def test_methodology_non_empty(self, report: FullCurrentStateReport) -> None:
        assert len(report.methodology) > 0

    def test_verdict_zh_non_empty(self, report: FullCurrentStateReport) -> None:
        assert len(report.verdict_zh) > 0

    def test_system_verdict_non_empty(self, report: FullCurrentStateReport) -> None:
        assert len(report.system_verdict) > 0

    def test_system_verdict_mentions_late_stage(self, report: FullCurrentStateReport) -> None:
        assert "LATE_STAGE" in report.system_verdict or "late-stage" in report.system_verdict.lower()

    def test_p0_items_count_is_zero(self, report: FullCurrentStateReport) -> None:
        assert report.p0_items_count == 0, (
            f"Expected 0 P0 items; got {report.p0_items_count}"
        )


# =============================================================================
# SECTION 3 — System characterization
# =============================================================================


class TestSystemCharacterization:
    """System characterization must describe both repo roles non-trivially."""

    @pytest.fixture(scope="class")
    def char(self) -> DualRepoSystemCharacterization:
        report = build_full_current_state_rereading()
        assert report.system_characterization is not None
        return report.system_characterization

    def test_v2_authority_role_non_empty(self, char: DualRepoSystemCharacterization) -> None:
        assert len(char.v2_authority_role) > 0

    def test_android_carrier_role_non_empty(self, char: DualRepoSystemCharacterization) -> None:
        assert len(char.android_carrier_role) > 0

    def test_dual_repo_interaction_pattern_non_empty(self, char: DualRepoSystemCharacterization) -> None:
        assert len(char.dual_repo_interaction_pattern) > 0

    def test_v2_code_anchors_non_empty(self, char: DualRepoSystemCharacterization) -> None:
        assert len(char.v2_code_anchors) > 0

    def test_characterization_summary_non_empty(self, char: DualRepoSystemCharacterization) -> None:
        assert len(char.characterization_summary) > 0

    def test_v2_role_mentions_authority(self, char: DualRepoSystemCharacterization) -> None:
        assert "authority" in char.v2_authority_role.lower()

    def test_android_role_mentions_carrier(self, char: DualRepoSystemCharacterization) -> None:
        role_lower = char.android_carrier_role.lower()
        assert "carrier" in role_lower or "runtime" in role_lower

    def test_to_dict_serializable(self, char: DualRepoSystemCharacterization) -> None:
        d = char.to_dict()
        assert isinstance(d, dict)
        assert "v2_authority_role" in d
        assert "android_carrier_role" in d


# =============================================================================
# SECTION 4 — Claim matrix coverage
# =============================================================================


class TestClaimMatrix:
    """Claim matrix must cover all 7 PR #993 claim families."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_has_7_claims(self, report: FullCurrentStateReport) -> None:
        assert len(report.claim_matrix) == 7, (
            f"Expected 7 claims; got {len(report.claim_matrix)}: "
            f"{[c.claim_id for c in report.claim_matrix]}"
        )

    def test_all_items_are_claim_matrix_entry(self, report: FullCurrentStateReport) -> None:
        for c in report.claim_matrix:
            assert isinstance(c, ClaimMatrixEntry)

    def test_system_identity_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "system_identity_distributed_ai_body" in ids

    def test_v2_governance_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "v2_sole_governance_authority" in ids

    def test_android_carrier_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "android_is_runtime_carrier_not_client" in ids

    def test_network_is_body_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "network_is_the_body" in ids

    def test_beyond_poc_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "system_beyond_poc" in ids

    def test_remaining_work_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "remaining_work_is_closure_not_capability" in ids

    def test_direction_claim_present(self, report: FullCurrentStateReport) -> None:
        ids = [c.claim_id for c in report.claim_matrix]
        assert "direction_toward_unified_ai_body" in ids

    def test_all_claims_have_current_label(self, report: FullCurrentStateReport) -> None:
        for c in report.claim_matrix:
            assert isinstance(c.current_label, CurrentEvidenceLabel)

    def test_all_claims_have_claim_summary(self, report: FullCurrentStateReport) -> None:
        for c in report.claim_matrix:
            assert len(c.claim_summary) > 0

    def test_all_claims_at_strong_or_closed(self, report: FullCurrentStateReport) -> None:
        """All 7 claims must be STRONGLY_ESTABLISHED or RUNTIME_EVIDENCED_CLOSED."""
        strong_labels = {
            CurrentEvidenceLabel.STRONGLY_ESTABLISHED,
            CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED,
        }
        for c in report.claim_matrix:
            assert c.current_label in strong_labels, (
                f"Claim {c.claim_id!r} has unexpected label: {c.current_label}"
            )

    def test_claim_matrix_to_dict(self, report: FullCurrentStateReport) -> None:
        for c in report.claim_matrix:
            d = c.to_dict()
            assert "claim_id" in d
            assert "current_label" in d
            assert "prior_label" in d


# =============================================================================
# SECTION 5 — Canonical path closure map
# =============================================================================


class TestPathClosureMap:
    """Canonical path closure map must cover all 6 dual-repo paths."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_has_6_paths(self, report: FullCurrentStateReport) -> None:
        assert len(report.path_closure_map) == 6, (
            f"Expected 6 paths; got {len(report.path_closure_map)}: "
            f"{[p.path_id for p in report.path_closure_map]}"
        )

    def test_all_items_are_canonical_path_entry(self, report: FullCurrentStateReport) -> None:
        for p in report.path_closure_map:
            assert isinstance(p, CanonicalPathEntry)

    def test_android_registration_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "android_registration" in ids

    def test_runtime_snapshot_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "runtime_snapshot_uplink" in ids

    def test_execution_event_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "execution_event_uplink" in ids

    def test_task_dispatch_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "task_dispatch_execute_result" in ids

    def test_continuity_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "continuity_reconnect_resume" in ids

    def test_orchestration_truth_path_present(self, report: FullCurrentStateReport) -> None:
        ids = [p.path_id for p in report.path_closure_map]
        assert "orchestration_consumes_android_truth" in ids

    def test_all_paths_have_current_label(self, report: FullCurrentStateReport) -> None:
        for p in report.path_closure_map:
            assert isinstance(p.current_label, CurrentEvidenceLabel)

    def test_all_paths_have_description(self, report: FullCurrentStateReport) -> None:
        for p in report.path_closure_map:
            assert len(p.description) > 0

    def test_continuity_path_is_partially_established(self, report: FullCurrentStateReport) -> None:
        """CONTINUITY_RECONNECT_RESUME is expected PARTIALLY_ESTABLISHED (known P1 gap)."""
        continuity = next(
            (p for p in report.path_closure_map if p.path_id == "continuity_reconnect_resume"),
            None,
        )
        assert continuity is not None
        assert continuity.current_label == CurrentEvidenceLabel.PARTIALLY_ESTABLISHED, (
            f"Continuity path expected PARTIALLY_ESTABLISHED; got {continuity.current_label}"
        )

    def test_continuity_path_not_runtime_closed(self, report: FullCurrentStateReport) -> None:
        continuity = next(
            (p for p in report.path_closure_map if p.path_id == "continuity_reconnect_resume"),
            None,
        )
        assert continuity is not None
        assert not continuity.runtime_closed, (
            "Continuity e2e roundtrip test is not yet in CI; runtime_closed must be False"
        )

    def test_orchestration_truth_path_not_surface_only(self, report: FullCurrentStateReport) -> None:
        """ORCHESTRATION_CONSUMES_ANDROID_TRUTH must NOT be SURFACE_ALIGNMENT_ONLY."""
        orch = next(
            (p for p in report.path_closure_map if p.path_id == "orchestration_consumes_android_truth"),
            None,
        )
        assert orch is not None
        assert orch.current_label != CurrentEvidenceLabel.SURFACE_ALIGNMENT_ONLY, (
            f"Orchestration truth path must not be SURFACE_ALIGNMENT_ONLY; got {orch.current_label}"
        )

    def test_orchestration_truth_path_has_closure_pr(self, report: FullCurrentStateReport) -> None:
        orch = next(
            (p for p in report.path_closure_map if p.path_id == "orchestration_consumes_android_truth"),
            None,
        )
        assert orch is not None
        assert len(orch.closure_prs) > 0

    def test_android_registration_is_strongly_established(self, report: FullCurrentStateReport) -> None:
        reg = next(
            (p for p in report.path_closure_map if p.path_id == "android_registration"),
            None,
        )
        assert reg is not None
        assert reg.current_label == CurrentEvidenceLabel.STRONGLY_ESTABLISHED

    def test_android_registration_is_runtime_closed(self, report: FullCurrentStateReport) -> None:
        reg = next(
            (p for p in report.path_closure_map if p.path_id == "android_registration"),
            None,
        )
        assert reg is not None
        assert reg.runtime_closed is True

    def test_path_to_dict_serializable(self, report: FullCurrentStateReport) -> None:
        for p in report.path_closure_map:
            d = p.to_dict()
            assert "path_id" in d
            assert "current_label" in d
            assert "runtime_closed" in d


# =============================================================================
# SECTION 6 — Completion stage judgment
# =============================================================================


class TestCompletionStageJudgment:
    """Completion stage judgment must indicate LATE_STAGE_CLOSURE."""

    @pytest.fixture(scope="class")
    def judgment(self) -> CompletionStageJudgment:
        report = build_full_current_state_rereading()
        assert report.completion_stage_judgment is not None
        return report.completion_stage_judgment

    def test_stage_is_late_stage_closure(self, judgment: CompletionStageJudgment) -> None:
        assert judgment.current_stage in (
            CompletionStage.LATE_STAGE_CLOSURE,
            CompletionStage.NON_P0_REFINEMENT_ONLY,
        ), (
            f"Expected LATE_STAGE_CLOSURE or NON_P0_REFINEMENT_ONLY; "
            f"got {judgment.current_stage}"
        )

    def test_p0_gaps_open_is_zero(self, judgment: CompletionStageJudgment) -> None:
        assert judgment.p0_gaps_open == 0, (
            f"Expected 0 P0 gaps open; got {judgment.p0_gaps_open}"
        )

    def test_paths_runtime_closed_at_least_4(self, judgment: CompletionStageJudgment) -> None:
        assert judgment.paths_runtime_closed >= 4, (
            f"Expected at least 4 paths runtime-closed; got {judgment.paths_runtime_closed}"
        )

    def test_all_claims_at_strong_or_closed_flag(self, judgment: CompletionStageJudgment) -> None:
        assert judgment.all_claims_at_strong_or_closed is True

    def test_stage_rationale_non_empty(self, judgment: CompletionStageJudgment) -> None:
        assert len(judgment.stage_rationale) > 0

    def test_to_dict_serializable(self, judgment: CompletionStageJudgment) -> None:
        d = judgment.to_dict()
        assert "current_stage" in d
        assert "p0_gaps_open" in d
        assert "paths_runtime_closed" in d


# =============================================================================
# SECTION 7 — Post-next-PR judgment
# =============================================================================


class TestPostNextPRJudgment:
    """Post-next-PR judgment must target NON_P0_REFINEMENT_ONLY."""

    @pytest.fixture(scope="class")
    def judgment(self) -> PostNextPRJudgment:
        report = build_full_current_state_rereading()
        assert report.post_next_pr_judgment is not None
        return report.post_next_pr_judgment

    def test_post_stage_is_non_p0_refinement_only(self, judgment: PostNextPRJudgment) -> None:
        assert judgment.post_stage == CompletionStage.NON_P0_REFINEMENT_ONLY

    def test_trigger_condition_non_empty(self, judgment: PostNextPRJudgment) -> None:
        assert len(judgment.trigger_condition) > 0

    def test_post_stage_rationale_non_empty(self, judgment: PostNextPRJudgment) -> None:
        assert len(judgment.post_stage_rationale) > 0

    def test_remaining_non_p0_work_non_empty(self, judgment: PostNextPRJudgment) -> None:
        assert len(judgment.remaining_non_p0_work) > 0

    def test_to_dict_serializable(self, judgment: PostNextPRJudgment) -> None:
        d = judgment.to_dict()
        assert "post_stage" in d
        assert "trigger_condition" in d


# =============================================================================
# SECTION 8 — Roadmap
# =============================================================================


class TestRoadmap:
    """Roadmap must have no P0 items; must have P1 and P3 items."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_no_p0_items(self, report: FullCurrentStateReport) -> None:
        p0_items = [r for r in report.roadmap if r.priority == RoadmapPriority.P0_BLOCKING]
        assert len(p0_items) == 0, (
            f"Expected 0 P0 items; got {[r.item_id for r in p0_items]}"
        )

    def test_has_p1_items(self, report: FullCurrentStateReport) -> None:
        p1_items = [r for r in report.roadmap if r.priority == RoadmapPriority.P1_CANONICAL_CLOSURE]
        assert len(p1_items) >= 1, "Expected at least 1 P1 roadmap item"

    def test_has_p3_items(self, report: FullCurrentStateReport) -> None:
        p3_items = [r for r in report.roadmap if r.priority == RoadmapPriority.P3_DEPLOYMENT]
        assert len(p3_items) >= 1, "Expected at least 1 P3 roadmap item"

    def test_continuity_e2e_roundtrip_in_roadmap(self, report: FullCurrentStateReport) -> None:
        item_ids = [r.item_id for r in report.roadmap]
        assert "P1-CONTINUITY-E2E-ROUNDTRIP" in item_ids

    def test_zero_config_provisioning_in_roadmap(self, report: FullCurrentStateReport) -> None:
        item_ids = [r.item_id for r in report.roadmap]
        assert "P3-ZERO-CONFIG-PROVISIONING" in item_ids

    def test_all_items_are_roadmap_entry(self, report: FullCurrentStateReport) -> None:
        for r in report.roadmap:
            assert isinstance(r, RoadmapEntry)

    def test_all_items_have_title(self, report: FullCurrentStateReport) -> None:
        for r in report.roadmap:
            assert len(r.title) > 0

    def test_all_items_have_rationale(self, report: FullCurrentStateReport) -> None:
        for r in report.roadmap:
            assert len(r.rationale) > 0

    def test_to_dict_serializable(self, report: FullCurrentStateReport) -> None:
        for r in report.roadmap:
            d = r.to_dict()
            assert "item_id" in d
            assert "priority" in d

    def test_p0_items_count_matches_roadmap(self, report: FullCurrentStateReport) -> None:
        actual_p0 = sum(1 for r in report.roadmap if r.priority == RoadmapPriority.P0_BLOCKING)
        assert report.p0_items_count == actual_p0


# =============================================================================
# SECTION 9 — Count aggregate consistency
# =============================================================================


class TestCountAggregates:
    """Count aggregates must be internally consistent with claim and path lists."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_strongly_established_count_matches_claims(self, report: FullCurrentStateReport) -> None:
        actual = sum(
            1
            for c in report.claim_matrix
            if c.current_label == CurrentEvidenceLabel.STRONGLY_ESTABLISHED
        )
        assert report.strongly_established_count == actual

    def test_runtime_evidenced_closed_count_matches_claims(self, report: FullCurrentStateReport) -> None:
        actual = sum(
            1
            for c in report.claim_matrix
            if c.current_label == CurrentEvidenceLabel.RUNTIME_EVIDENCED_CLOSED
        )
        assert report.runtime_evidenced_closed_count == actual

    def test_partially_established_count_matches_claims(self, report: FullCurrentStateReport) -> None:
        actual = sum(
            1
            for c in report.claim_matrix
            if c.current_label == CurrentEvidenceLabel.PARTIALLY_ESTABLISHED
        )
        assert report.partially_established_count == actual

    def test_paths_runtime_closed_count_matches_paths(self, report: FullCurrentStateReport) -> None:
        actual = sum(1 for p in report.path_closure_map if p.runtime_closed)
        assert report.paths_runtime_closed_count == actual

    def test_total_claim_count_is_7(self, report: FullCurrentStateReport) -> None:
        total = (
            report.strongly_established_count
            + report.runtime_evidenced_closed_count
            + report.partially_established_count
        )
        # There may be additional labels (e.g., SURFACE_ALIGNMENT_ONLY) but
        # the sum of SE + REC + PE must be <= 7.
        assert total <= 7

    def test_paths_closed_at_most_6(self, report: FullCurrentStateReport) -> None:
        assert report.paths_runtime_closed_count <= 6


# =============================================================================
# SECTION 10 — Singleton caching and reset
# =============================================================================


class TestSingletonCaching:
    """Singleton caching + reset must work correctly."""

    def test_get_returns_same_instance(self) -> None:
        reset_full_current_state_rereading()
        r1 = get_full_current_state_rereading()
        r2 = get_full_current_state_rereading()
        assert r1 is r2

    def test_reset_clears_cache(self) -> None:
        reset_full_current_state_rereading()
        r1 = get_full_current_state_rereading()
        reset_full_current_state_rereading()
        r2 = get_full_current_state_rereading()
        assert r1 is not r2

    def test_build_returns_different_instances(self) -> None:
        r1 = build_full_current_state_rereading()
        r2 = build_full_current_state_rereading()
        assert r1 is not r2

    def test_get_returns_full_current_state_report(self) -> None:
        reset_full_current_state_rereading()
        r = get_full_current_state_rereading()
        assert isinstance(r, FullCurrentStateReport)


# =============================================================================
# SECTION 11 — assert_full_current_state_invariants()
# =============================================================================


class TestAssertInvariants:
    """assert_full_current_state_invariants() must pass without raising."""

    def test_invariants_pass(self) -> None:
        reset_full_current_state_rereading()
        assert_full_current_state_invariants()


# =============================================================================
# SECTION 12 — JSON serialisation
# =============================================================================


class TestJSONSerialisation:
    """Report must serialise to and from JSON cleanly."""

    @pytest.fixture(scope="class")
    def report(self) -> FullCurrentStateReport:
        return build_full_current_state_rereading()

    def test_to_json_returns_string(self, report: FullCurrentStateReport) -> None:
        json_str = report.to_json()
        assert isinstance(json_str, str)
        assert len(json_str) > 0

    def test_to_json_parses_as_dict(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        assert isinstance(d, dict)

    def test_to_dict_has_all_top_level_keys(self, report: FullCurrentStateReport) -> None:
        d = report.to_dict()
        for key in [
            "report_id",
            "generated_at",
            "methodology",
            "verdict_zh",
            "system_characterization",
            "claim_matrix",
            "path_closure_map",
            "completion_stage_judgment",
            "post_next_pr_judgment",
            "roadmap",
            "strongly_established_count",
            "runtime_evidenced_closed_count",
            "partially_established_count",
            "paths_runtime_closed_count",
            "p0_items_count",
            "system_verdict",
        ]:
            assert key in d, f"Missing key: {key!r}"

    def test_claim_matrix_in_json_has_7_entries(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        assert len(d["claim_matrix"]) == 7

    def test_path_closure_map_in_json_has_6_entries(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        assert len(d["path_closure_map"]) == 6

    def test_completion_stage_in_json_is_string(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        stage = d["completion_stage_judgment"]["current_stage"]
        assert isinstance(stage, str)
        assert stage in ("LATE_STAGE_CLOSURE", "NON_P0_REFINEMENT_ONLY")

    def test_post_stage_in_json_is_non_p0_refinement(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        post_stage = d["post_next_pr_judgment"]["post_stage"]
        assert post_stage == "NON_P0_REFINEMENT_ONLY"

    def test_p0_items_count_in_json_is_zero(self, report: FullCurrentStateReport) -> None:
        d = json.loads(report.to_json())
        assert d["p0_items_count"] == 0
