"""
tests/test_post_closure_dual_repo_reassessment.py
==================================================
Test suite for core/post_closure_dual_repo_reassessment.py

Post-Closure Dual-Repo Reassessment of the Galaxy System.

This test suite validates:
1. Module imports cleanly; all public symbols accessible.
2. build_post_closure_reassessment() returns a structurally correct report.
3. All 7 claim IDs have a corresponding PostClosureClaimStatus.
4. All 6 canonical path IDs have a corresponding PostClosurePathStatus.
5. All 4 closure PRs (V2#1011, V2#1013, V2#1015, Android#335) are recorded.
6. Claims upgraded by the closure PRs have appropriate updated labels.
7. Canonical paths closed by closure PRs are marked runtime_closed=True.
8. The orchestration path is explicitly labeled STILL_MISSING_DECISION_PATH_CLOSURE.
9. At least one P0 next-PR item exists and targets orchestration consumption.
10. Counts and summaries are internally consistent.
11. Singleton caching + reset work correctly.
12. assert_post_closure_invariants() passes cleanly.
13. Report serialises to JSON cleanly.
14. Chinese system conclusion is non-empty.

Methodology
-----------
- Only imports the reassessment module and standard library — no mocking.
- Validates structural correctness and invariants; not runtime execution paths.
"""

from __future__ import annotations

import json

import pytest

from core.post_closure_dual_repo_reassessment import (
    ClosurePRRecord,
    ClosureStatus,
    NextPRItem,
    NextPRPriority,
    POST_CLOSURE_DUAL_REPO_VERDICT_ZH,
    POST_CLOSURE_REASSESSMENT_AUTHORITY,
    POST_CLOSURE_REASSESSMENT_METHODOLOGY,
    PostClosureClaimId,
    PostClosureClaimStatus,
    PostClosurePathId,
    PostClosurePathStatus,
    PostClosureReport,
    assert_post_closure_invariants,
    build_post_closure_reassessment,
    get_post_closure_reassessment,
    reset_post_closure_reassessment,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(POST_CLOSURE_REASSESSMENT_AUTHORITY, str)
        assert len(POST_CLOSURE_REASSESSMENT_AUTHORITY) > 0

    def test_methodology_sentinel_is_non_empty_string(self) -> None:
        assert isinstance(POST_CLOSURE_REASSESSMENT_METHODOLOGY, str)
        assert len(POST_CLOSURE_REASSESSMENT_METHODOLOGY) > 0

    def test_verdict_zh_is_non_empty_string(self) -> None:
        assert isinstance(POST_CLOSURE_DUAL_REPO_VERDICT_ZH, str)
        assert len(POST_CLOSURE_DUAL_REPO_VERDICT_ZH) > 0

    def test_claim_id_enum_covers_7_families(self) -> None:
        claim_ids = list(PostClosureClaimId)
        assert len(claim_ids) == 7, (
            f"Expected 7 claim IDs; got {len(claim_ids)}: "
            f"{[c.value for c in claim_ids]}"
        )

    def test_path_id_enum_covers_6_paths(self) -> None:
        path_ids = list(PostClosurePathId)
        assert len(path_ids) == 6, (
            f"Expected 6 path IDs; got {len(path_ids)}"
        )

    def test_closure_status_enum_covers_6_tiers(self) -> None:
        statuses = list(ClosureStatus)
        assert len(statuses) == 6, (
            f"Expected 6 ClosureStatus tiers; got {len(statuses)}"
        )

    def test_next_pr_priority_enum_covers_4_tiers(self) -> None:
        tiers = list(NextPRPriority)
        assert len(tiers) == 4, (
            f"Expected 4 NextPRPriority tiers; got {len(tiers)}"
        )

    def test_closure_status_has_strongly_established(self) -> None:
        assert ClosureStatus.STRONGLY_ESTABLISHED in ClosureStatus

    def test_closure_status_has_runtime_evidenced_closed(self) -> None:
        assert ClosureStatus.RUNTIME_EVIDENCED_CLOSED in ClosureStatus

    def test_closure_status_has_still_missing_decision_path(self) -> None:
        assert ClosureStatus.STILL_MISSING_DECISION_PATH_CLOSURE in ClosureStatus


# =============================================================================
# SECTION 2 — build_post_closure_reassessment() structural checks
# =============================================================================


class TestBuildReport:
    """build_post_closure_reassessment() must return a structurally complete report."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_returns_post_closure_report(self, report: PostClosureReport) -> None:
        assert isinstance(report, PostClosureReport)

    def test_report_id_is_non_empty(self, report: PostClosureReport) -> None:
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_generated_at_is_positive_float(self, report: PostClosureReport) -> None:
        assert isinstance(report.generated_at, float)
        assert report.generated_at > 0

    def test_methodology_non_empty(self, report: PostClosureReport) -> None:
        assert report.methodology
        assert len(report.methodology) > 0

    def test_verdict_zh_non_empty(self, report: PostClosureReport) -> None:
        assert report.verdict_zh
        assert len(report.verdict_zh) > 0

    def test_system_characterization_non_empty(self, report: PostClosureReport) -> None:
        assert report.system_characterization
        assert len(report.system_characterization) > 0

    def test_updated_verdict_non_empty(self, report: PostClosureReport) -> None:
        assert report.updated_verdict
        assert len(report.updated_verdict) > 0


# =============================================================================
# SECTION 3 — Closure PR catalog
# =============================================================================


class TestClosurePRCatalog:
    """The four closure PRs must all be recorded in the catalog."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_at_least_4_closure_prs_recorded(self, report: PostClosureReport) -> None:
        assert len(report.closure_prs) >= 4, (
            f"Expected at least 4 closure PRs; got {len(report.closure_prs)}"
        )

    def test_all_items_are_closure_pr_records(self, report: PostClosureReport) -> None:
        for pr in report.closure_prs:
            assert isinstance(pr, ClosurePRRecord)

    def test_v2_pr1011_recorded(self, report: PostClosureReport) -> None:
        refs = [pr.pr_ref for pr in report.closure_prs]
        assert "V2#1011" in refs, f"V2#1011 (PR-A) not in closure PR catalog: {refs}"

    def test_v2_pr1013_recorded(self, report: PostClosureReport) -> None:
        refs = [pr.pr_ref for pr in report.closure_prs]
        assert "V2#1013" in refs, f"V2#1013 (PR-B) not in closure PR catalog: {refs}"

    def test_v2_pr1015_recorded(self, report: PostClosureReport) -> None:
        refs = [pr.pr_ref for pr in report.closure_prs]
        assert "V2#1015" in refs, f"V2#1015 (PR-C V2) not in closure PR catalog: {refs}"

    def test_android_pr335_recorded(self, report: PostClosureReport) -> None:
        refs = [pr.pr_ref for pr in report.closure_prs]
        assert "Android#335" in refs, (
            f"Android#335 (PR-C Android) not in closure PR catalog: {refs}"
        )

    def test_pr1011_closes_snapshot_path(self, report: PostClosureReport) -> None:
        pr_a = next(pr for pr in report.closure_prs if pr.pr_ref == "V2#1011")
        assert PostClosurePathId.RUNTIME_SNAPSHOT_UPLINK in pr_a.paths_closed

    def test_pr1013_closes_dispatch_path(self, report: PostClosureReport) -> None:
        pr_b = next(pr for pr in report.closure_prs if pr.pr_ref == "V2#1013")
        assert PostClosurePathId.TASK_DISPATCH_EXECUTE_RESULT in pr_b.paths_closed

    def test_pr1015_closes_continuity_path(self, report: PostClosureReport) -> None:
        pr_c = next(pr for pr in report.closure_prs if pr.pr_ref == "V2#1015")
        assert PostClosurePathId.CONTINUITY_RECONNECT_RESUME in pr_c.paths_closed

    def test_pr1011_references_e2e_test_module(self, report: PostClosureReport) -> None:
        pr_a = next(pr for pr in report.closure_prs if pr.pr_ref == "V2#1011")
        assert any(
            "test_android_runtime_state_snapshot_e2e" in m
            for m in pr_a.v2_test_modules
        ), f"PR-A test modules: {pr_a.v2_test_modules}"

    def test_pr1013_references_delegated_closure_test(
        self, report: PostClosureReport
    ) -> None:
        pr_b = next(pr for pr in report.closure_prs if pr.pr_ref == "V2#1013")
        assert any(
            "test_delegated_execution_runtime_closure" in m
            for m in pr_b.v2_test_modules
        ), f"PR-B test modules: {pr_b.v2_test_modules}"

    def test_closure_prs_serialise_to_dict(self, report: PostClosureReport) -> None:
        for pr in report.closure_prs:
            d = pr.to_dict()
            assert isinstance(d, dict)
            assert "pr_ref" in d
            assert "paths_closed" in d


# =============================================================================
# SECTION 4 — Claim status coverage and upgrade labels
# =============================================================================


class TestClaimStatusCoverage:
    """All 7 claim IDs must have a status; closure PRs must upgrade appropriate claims."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_exactly_7_claim_statuses(self, report: PostClosureReport) -> None:
        assert len(report.claim_statuses) == 7

    def test_all_claim_ids_covered(self, report: PostClosureReport) -> None:
        seen = {c.claim_id for c in report.claim_statuses}
        for cid in PostClosureClaimId:
            assert cid in seen, f"Missing claim status for {cid.name}"

    def test_all_items_are_post_closure_claim_status(
        self, report: PostClosureReport
    ) -> None:
        for c in report.claim_statuses:
            assert isinstance(c, PostClosureClaimStatus)

    def test_no_claim_is_surface_alignment_only(self, report: PostClosureReport) -> None:
        """Post-closure: all claims should be at least PARTIALLY_ESTABLISHED."""
        bad = [
            c.claim_id.value
            for c in report.claim_statuses
            if c.updated_label == ClosureStatus.SURFACE_ALIGNMENT_ONLY
        ]
        assert not bad, (
            f"Unexpected SURFACE_ALIGNMENT_ONLY claims after closure: {bad}"
        )

    def test_no_claim_is_obsolete_draft_noise(self, report: PostClosureReport) -> None:
        bad = [
            c.claim_id.value
            for c in report.claim_statuses
            if c.updated_label == ClosureStatus.OBSOLETE_DRAFT_NOISE
        ]
        assert not bad, f"Unexpected OBSOLETE_DRAFT_NOISE claims: {bad}"

    def test_at_least_5_claims_upgraded(self, report: PostClosureReport) -> None:
        """Closure PRs should upgrade at least 5 of 7 claims."""
        upgraded = sum(1 for c in report.claim_statuses if c.changed)
        assert upgraded >= 5, (
            f"Expected at least 5 upgraded claims; got {upgraded}. "
            "PR-A, PR-B, PR-C should each upgrade multiple claims."
        )

    def test_android_carrier_claim_is_runtime_evidenced(
        self, report: PostClosureReport
    ) -> None:
        carrier = next(
            c for c in report.claim_statuses
            if c.claim_id == PostClosureClaimId.ANDROID_IS_RUNTIME_CARRIER_NOT_CLIENT
        )
        assert carrier.updated_label == ClosureStatus.RUNTIME_EVIDENCED_CLOSED, (
            f"Expected RUNTIME_EVIDENCED_CLOSED for Android carrier claim; "
            f"got {carrier.updated_label}"
        )

    def test_system_beyond_poc_claim_is_runtime_evidenced(
        self, report: PostClosureReport
    ) -> None:
        beyond_poc = next(
            c for c in report.claim_statuses
            if c.claim_id == PostClosureClaimId.SYSTEM_BEYOND_POC
        )
        assert beyond_poc.updated_label == ClosureStatus.RUNTIME_EVIDENCED_CLOSED, (
            f"Expected RUNTIME_EVIDENCED_CLOSED for beyond PoC claim; "
            f"got {beyond_poc.updated_label}"
        )

    def test_system_identity_claim_upgraded(self, report: PostClosureReport) -> None:
        identity = next(
            c for c in report.claim_statuses
            if c.claim_id == PostClosureClaimId.SYSTEM_IDENTITY_DISTRIBUTED_AI_BODY
        )
        assert identity.updated_label in (
            ClosureStatus.STRONGLY_ESTABLISHED,
            ClosureStatus.RUNTIME_EVIDENCED_CLOSED,
        ), f"Unexpected label for system_identity: {identity.updated_label}"

    def test_claim_statuses_have_prior_labels(self, report: PostClosureReport) -> None:
        for c in report.claim_statuses:
            assert isinstance(c.prior_label, str) and c.prior_label, (
                f"Claim {c.claim_id.value} has empty prior_label"
            )

    def test_claims_with_changed_true_have_closure_pr_refs(
        self, report: PostClosureReport
    ) -> None:
        for c in report.claim_statuses:
            if c.changed:
                assert c.closure_pr_refs, (
                    f"Claim {c.claim_id.value} is marked changed=True "
                    f"but has no closure_pr_refs"
                )

    def test_claim_statuses_serialise_to_dict(self, report: PostClosureReport) -> None:
        for c in report.claim_statuses:
            d = c.to_dict()
            assert "claim_id" in d
            assert "prior_label" in d
            assert "updated_label" in d
            assert "changed" in d


# =============================================================================
# SECTION 5 — Canonical path status coverage and runtime-closed flags
# =============================================================================


class TestPathStatusCoverage:
    """All 6 path IDs must have a status; closure PRs must close appropriate paths."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_exactly_6_path_statuses(self, report: PostClosureReport) -> None:
        assert len(report.path_statuses) == 6

    def test_all_path_ids_covered(self, report: PostClosureReport) -> None:
        seen = {p.path_id for p in report.path_statuses}
        for pid in PostClosurePathId:
            assert pid in seen, f"Missing path status for {pid.name}"

    def test_all_items_are_post_closure_path_status(
        self, report: PostClosureReport
    ) -> None:
        for p in report.path_statuses:
            assert isinstance(p, PostClosurePathStatus)

    def test_runtime_snapshot_uplink_is_closed(self, report: PostClosureReport) -> None:
        """PR-A closed this path — was surface_alignment_only."""
        snap = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.RUNTIME_SNAPSHOT_UPLINK
        )
        assert snap.runtime_closed is True, (
            "RUNTIME_SNAPSHOT_UPLINK should be runtime_closed after PR-A"
        )
        assert snap.prior_label == "surface_alignment_only", (
            f"Expected prior_label=surface_alignment_only; got {snap.prior_label}"
        )
        assert snap.updated_label == ClosureStatus.RUNTIME_EVIDENCED_CLOSED

    def test_task_dispatch_result_is_closed(self, report: PostClosureReport) -> None:
        """PR-B closed this path — was partially_established."""
        dispatch = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.TASK_DISPATCH_EXECUTE_RESULT
        )
        assert dispatch.runtime_closed is True, (
            "TASK_DISPATCH_EXECUTE_RESULT should be runtime_closed after PR-B"
        )
        assert dispatch.prior_label == "partially_established", (
            f"Expected prior_label=partially_established; got {dispatch.prior_label}"
        )
        assert dispatch.updated_label == ClosureStatus.RUNTIME_EVIDENCED_CLOSED

    def test_execution_event_uplink_is_closed(self, report: PostClosureReport) -> None:
        """PR-A + PR-B closed this path."""
        evt = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.EXECUTION_EVENT_UPLINK
        )
        assert evt.runtime_closed is True, (
            "EXECUTION_EVENT_UPLINK should be runtime_closed after PR-A + PR-B"
        )

    def test_android_registration_is_closed(self, report: PostClosureReport) -> None:
        reg = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.ANDROID_REGISTRATION
        )
        assert reg.runtime_closed is True, (
            "ANDROID_REGISTRATION should be runtime_closed"
        )

    def test_orchestration_path_is_still_missing_decision_path(
        self, report: PostClosureReport
    ) -> None:
        """This path should remain STILL_MISSING_DECISION_PATH_CLOSURE."""
        orch = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH
        )
        assert orch.runtime_closed is False, (
            "ORCHESTRATION_CONSUMES_ANDROID_TRUTH should still be open"
        )
        assert orch.updated_label == ClosureStatus.STILL_MISSING_DECISION_PATH_CLOSURE, (
            f"Expected STILL_MISSING_DECISION_PATH_CLOSURE; got {orch.updated_label}"
        )
        assert orch.prior_label == "surface_alignment_only", (
            f"Expected prior_label=surface_alignment_only; got {orch.prior_label}"
        )
        # Updated label should reflect that the status has changed (no longer surface_alignment)
        assert orch.updated_label != ClosureStatus.SURFACE_ALIGNMENT_ONLY

    def test_orchestration_path_has_gap_description(
        self, report: PostClosureReport
    ) -> None:
        orch = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH
        )
        assert orch.gap_description, (
            "ORCHESTRATION_CONSUMES_ANDROID_TRUTH must have a gap_description"
        )

    def test_at_least_4_paths_runtime_closed(self, report: PostClosureReport) -> None:
        closed = [p for p in report.path_statuses if p.runtime_closed]
        assert len(closed) >= 4, (
            f"Expected at least 4 paths runtime_closed; got {len(closed)}: "
            f"{[p.path_id.value for p in closed]}"
        )

    def test_open_paths_are_expected_ones(self, report: PostClosureReport) -> None:
        open_paths = [p.path_id for p in report.path_statuses if not p.runtime_closed]
        for pid in open_paths:
            assert pid in (
                PostClosurePathId.CONTINUITY_RECONNECT_RESUME,
                PostClosurePathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH,
            ), (
                f"Unexpected open path: {pid.value}. "
                "Only continuity_reconnect_resume and orchestration_consumes_android_truth "
                "should remain open."
            )

    def test_path_statuses_have_prior_labels(self, report: PostClosureReport) -> None:
        for p in report.path_statuses:
            assert isinstance(p.prior_label, str) and p.prior_label, (
                f"Path {p.path_id.value} has empty prior_label"
            )

    def test_closed_paths_reference_closure_prs(self, report: PostClosureReport) -> None:
        for p in report.path_statuses:
            if p.runtime_closed:
                assert p.closure_pr_refs, (
                    f"Path {p.path_id.value} is runtime_closed but has no closure_pr_refs"
                )

    def test_path_statuses_serialise_to_dict(self, report: PostClosureReport) -> None:
        for p in report.path_statuses:
            d = p.to_dict()
            assert "path_id" in d
            assert "prior_label" in d
            assert "prior_runtime_closed" in d
            assert "updated_label" in d
            assert "runtime_closed" in d


# =============================================================================
# SECTION 6 — Next-PR roadmap
# =============================================================================


class TestNextPRRoadmap:
    """Updated next-PR roadmap must have the correct P0 item and priorities."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_at_least_1_next_pr_item(self, report: PostClosureReport) -> None:
        assert len(report.next_pr_items) >= 1

    def test_all_items_are_next_pr_items(self, report: PostClosureReport) -> None:
        for item in report.next_pr_items:
            assert isinstance(item, NextPRItem)

    def test_exactly_1_p0_item(self, report: PostClosureReport) -> None:
        p0 = [n for n in report.next_pr_items if n.priority == NextPRPriority.P0_DECISION_PATH_CLOSURE]
        assert len(p0) >= 1, (
            f"Expected at least 1 P0 next-PR item; got {len(p0)}"
        )

    def test_p0_item_targets_orchestration_decision_path(
        self, report: PostClosureReport
    ) -> None:
        p0 = next(
            n for n in report.next_pr_items
            if n.priority == NextPRPriority.P0_DECISION_PATH_CLOSURE
        )
        # The P0 item must clearly reference orchestration/routing/dispatch
        combined = (p0.title + " " + p0.rationale).lower()
        assert any(
            kw in combined
            for kw in ["orchestration", "routing", "dispatch", "decision"]
        ), (
            f"P0 item title/rationale should reference orchestration/routing/dispatch. "
            f"Got title='{p0.title}'"
        )

    def test_p0_item_references_v2_repo(self, report: PostClosureReport) -> None:
        p0 = next(
            n for n in report.next_pr_items
            if n.priority == NextPRPriority.P0_DECISION_PATH_CLOSURE
        )
        assert any("ufo-galaxy-realization-v2" in r for r in p0.target_repos), (
            f"P0 item must target V2 repo; got {p0.target_repos}"
        )

    def test_at_least_1_p1_item(self, report: PostClosureReport) -> None:
        p1 = [n for n in report.next_pr_items if n.priority == NextPRPriority.P1_CANONICAL_CLOSURE_GAP]
        assert len(p1) >= 1, f"Expected at least 1 P1 next-PR item; got {len(p1)}"

    def test_no_stale_p0_items_about_closed_gaps(self, report: PostClosureReport) -> None:
        """P0 items must NOT reference gaps that the closure PRs already closed."""
        for item in report.next_pr_items:
            if item.priority == NextPRPriority.P0_DECISION_PATH_CLOSURE:
                combined = (item.title + " " + item.rationale).lower()
                # The prior P0 gaps (snapshot CI evidence, delegated exec closure)
                # should no longer appear as P0 items
                assert "android-runtime-ci-evidence" not in item.item_id.lower(), (
                    f"P0 item '{item.item_id}' appears to reference a closed gap "
                    "(snapshot CI evidence was closed by PR-A)"
                )
                assert "delegated-exec-runtime-closure" not in item.item_id.lower(), (
                    f"P0 item '{item.item_id}' appears to reference a closed gap "
                    "(delegated exec runtime closure was closed by PR-B)"
                )

    def test_next_pr_items_serialise_to_dict(self, report: PostClosureReport) -> None:
        for item in report.next_pr_items:
            d = item.to_dict()
            assert "item_id" in d
            assert "priority" in d
            assert "title" in d
            assert "rationale" in d


# =============================================================================
# SECTION 7 — Aggregate counts
# =============================================================================


class TestAggregateCounts:
    """Aggregate counts must be internally consistent with the detail lists."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_claim_bucket_sum_equals_total_claims(
        self, report: PostClosureReport
    ) -> None:
        total = (
            report.strongly_established_count
            + report.runtime_evidenced_closed_count
            + report.partially_established_count
            + report.surface_alignment_only_count
            + report.still_missing_decision_path_count
        )
        assert total == len(report.claim_statuses), (
            f"Claim bucket sum {total} != len(claim_statuses) {len(report.claim_statuses)}"
        )

    def test_path_closed_plus_open_equals_total_paths(
        self, report: PostClosureReport
    ) -> None:
        total = report.paths_runtime_closed + report.paths_still_open
        assert total == len(report.path_statuses), (
            f"paths_runtime_closed + paths_still_open {total} != "
            f"len(path_statuses) {len(report.path_statuses)}"
        )

    def test_paths_runtime_closed_is_at_least_4(
        self, report: PostClosureReport
    ) -> None:
        assert report.paths_runtime_closed >= 4, (
            f"Expected at least 4 runtime-closed paths; got {report.paths_runtime_closed}"
        )

    def test_claims_upgraded_is_at_least_5(self, report: PostClosureReport) -> None:
        assert report.claims_upgraded >= 5, (
            f"Expected at least 5 upgraded claims; got {report.claims_upgraded}"
        )

    def test_strongly_established_plus_runtime_evidenced_is_majority(
        self, report: PostClosureReport
    ) -> None:
        strong = report.strongly_established_count + report.runtime_evidenced_closed_count
        assert strong >= 5, (
            f"Expected at least 5 claims to be strongly established or "
            f"runtime evidenced closed; got {strong}"
        )


# =============================================================================
# SECTION 8 — Chinese system conclusion
# =============================================================================


class TestChineseConclusion:
    """The Chinese system conclusion must be substantive and reference key facts."""

    def test_verdict_zh_is_non_empty(self) -> None:
        assert POST_CLOSURE_DUAL_REPO_VERDICT_ZH
        assert len(POST_CLOSURE_DUAL_REPO_VERDICT_ZH) > 100

    def test_verdict_zh_mentions_pr_a_number(self) -> None:
        assert "1011" in POST_CLOSURE_DUAL_REPO_VERDICT_ZH, (
            "Chinese verdict should mention PR #1011 (PR-A)"
        )

    def test_verdict_zh_mentions_pr_b_number(self) -> None:
        assert "1013" in POST_CLOSURE_DUAL_REPO_VERDICT_ZH, (
            "Chinese verdict should mention PR #1013 (PR-B)"
        )

    def test_verdict_zh_mentions_pr_c_number(self) -> None:
        assert "1015" in POST_CLOSURE_DUAL_REPO_VERDICT_ZH, (
            "Chinese verdict should mention PR #1015 (PR-C V2)"
        )

    def test_verdict_zh_mentions_android_pr335(self) -> None:
        assert "335" in POST_CLOSURE_DUAL_REPO_VERDICT_ZH, (
            "Chinese verdict should mention Android #335 (PR-C Android)"
        )

    def test_verdict_zh_mentions_orchestration_gap(self) -> None:
        combined = POST_CLOSURE_DUAL_REPO_VERDICT_ZH.lower()
        assert any(
            kw in combined
            for kw in ["orchestration", "routing", "dispatch", "决策", "路由", "分发"]
        ), "Chinese verdict should mention the orchestration/decision-path gap"

    def test_report_verdict_zh_matches_module_constant(self) -> None:
        report = build_post_closure_reassessment()
        assert report.verdict_zh == POST_CLOSURE_DUAL_REPO_VERDICT_ZH


# =============================================================================
# SECTION 9 — JSON serialisation
# =============================================================================


class TestSerialisation:
    """Report must serialise to JSON cleanly and round-trip correctly."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_to_dict_returns_dict(self, report: PostClosureReport) -> None:
        d = report.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_contains_required_keys(self, report: PostClosureReport) -> None:
        d = report.to_dict()
        for key in [
            "report_id",
            "generated_at",
            "methodology",
            "verdict_zh",
            "closure_prs",
            "claim_statuses",
            "path_statuses",
            "next_pr_items",
            "strongly_established_count",
            "runtime_evidenced_closed_count",
            "partially_established_count",
            "paths_runtime_closed",
            "paths_still_open",
            "claims_upgraded",
            "system_characterization",
            "updated_verdict",
        ]:
            assert key in d, f"Key '{key}' missing from to_dict()"

    def test_to_json_returns_non_empty_string(self, report: PostClosureReport) -> None:
        j = report.to_json()
        assert isinstance(j, str)
        assert len(j) > 0

    def test_to_json_is_valid_json(self, report: PostClosureReport) -> None:
        j = report.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_to_json_round_trips_report_id(self, report: PostClosureReport) -> None:
        parsed = json.loads(report.to_json())
        assert parsed["report_id"] == report.report_id

    def test_to_json_round_trips_claim_statuses(self, report: PostClosureReport) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["claim_statuses"]) == len(report.claim_statuses)

    def test_to_json_round_trips_path_statuses(self, report: PostClosureReport) -> None:
        parsed = json.loads(report.to_json())
        assert len(parsed["path_statuses"]) == len(report.path_statuses)


# =============================================================================
# SECTION 10 — Singleton caching and test isolation
# =============================================================================


class TestSingletonCaching:
    """get_post_closure_reassessment() must cache the report; reset clears it."""

    def setup_method(self) -> None:
        reset_post_closure_reassessment()

    def test_get_returns_post_closure_report(self) -> None:
        r = get_post_closure_reassessment()
        assert isinstance(r, PostClosureReport)

    def test_get_returns_same_instance_on_second_call(self) -> None:
        r1 = get_post_closure_reassessment()
        r2 = get_post_closure_reassessment()
        assert r1 is r2, "get_post_closure_reassessment() should return the same object"

    def test_reset_clears_cache(self) -> None:
        r1 = get_post_closure_reassessment()
        reset_post_closure_reassessment()
        r2 = get_post_closure_reassessment()
        assert r1 is not r2, "After reset, a new report instance should be returned"

    def test_build_always_returns_new_instance(self) -> None:
        r1 = build_post_closure_reassessment()
        r2 = build_post_closure_reassessment()
        assert r1 is not r2, "build_post_closure_reassessment() should always return new instance"

    def test_singleton_is_thread_safe(self) -> None:
        """Multiple threads calling get must all receive valid reports."""
        import threading

        results = []
        lock = threading.Lock()

        def _get():
            r = get_post_closure_reassessment()
            with lock:
                results.append(r)

        threads = [threading.Thread(target=_get) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 10
        # All must be the same instance after caching
        assert all(r is results[0] for r in results), (
            "All threads should receive the same cached instance"
        )


# =============================================================================
# SECTION 11 — assert_post_closure_invariants() helper
# =============================================================================


class TestInvariantHelper:
    """The assert_post_closure_invariants() helper must pass cleanly."""

    def setup_method(self) -> None:
        reset_post_closure_reassessment()

    def test_invariants_pass(self) -> None:
        assert_post_closure_invariants()

    def test_invariants_pass_idempotently(self) -> None:
        assert_post_closure_invariants()
        assert_post_closure_invariants()


# =============================================================================
# SECTION 12 — Comparison with prior reevaluation (regression guard)
# =============================================================================


class TestComparisonWithPriorReevaluation:
    """The post-closure report must be materially stronger than the prior."""

    @pytest.fixture(scope="class")
    def report(self) -> PostClosureReport:
        return build_post_closure_reassessment()

    def test_prior_reevaluation_module_still_importable(self) -> None:
        """The prior reevaluation is a baseline; it must still work."""
        from core.pr993_dual_repo_reevaluation import build_pr993_reevaluation
        prior = build_pr993_reevaluation()
        assert prior is not None

    def test_post_closure_has_more_runtime_closed_paths(self, report: PostClosureReport) -> None:
        """Post-closure should have significantly more runtime-closed paths."""
        from core.pr993_dual_repo_reevaluation import build_pr993_reevaluation
        prior = build_pr993_reevaluation()
        assert report.paths_runtime_closed > prior.canonical_paths_closed, (
            f"Post-closure should close more paths than prior "
            f"(post: {report.paths_runtime_closed}, prior: {prior.canonical_paths_closed})"
        )

    def test_snapshot_path_was_upgraded_from_prior(self, report: PostClosureReport) -> None:
        snap = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.RUNTIME_SNAPSHOT_UPLINK
        )
        assert snap.prior_label == "surface_alignment_only", (
            "Prior label should record the original surface_alignment_only status"
        )
        assert snap.updated_label != ClosureStatus.SURFACE_ALIGNMENT_ONLY, (
            "Post-closure snapshot path should no longer be surface_alignment_only"
        )

    def test_dispatch_path_was_upgraded_from_prior(self, report: PostClosureReport) -> None:
        dispatch = next(
            p for p in report.path_statuses
            if p.path_id == PostClosurePathId.TASK_DISPATCH_EXECUTE_RESULT
        )
        assert dispatch.prior_label == "partially_established"
        assert dispatch.runtime_closed is True
        assert dispatch.updated_label == ClosureStatus.RUNTIME_EVIDENCED_CLOSED
