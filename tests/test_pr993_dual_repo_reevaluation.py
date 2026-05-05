"""
tests/test_pr993_dual_repo_reevaluation.py
==========================================
Test suite for core/pr993_dual_repo_reevaluation.py

Joint Dual-Repo Code-Grounded Reevaluation of PR #993 Claims.

This test suite validates that:
1. The module imports cleanly and all public symbols are accessible.
2. build_pr993_reevaluation() returns a structurally correct report.
3. All 7 PR #993 claim IDs have a corresponding ClaimValidation record.
4. All 6 canonical path IDs have a corresponding CanonicalPathStatus record.
5. Closure priorities include at least the expected P0 items.
6. Evidence strength labels are internally consistent.
7. The report serialises to JSON cleanly.
8. The assert_pr993_reevaluation_invariants() helper passes.
9. Singleton caching + reset work correctly.

Methodology
-----------
- Only imports the reevaluation module and standard library — no mocking.
- Validates structural correctness and invariants; not runtime execution paths.
"""

from __future__ import annotations

import json

import pytest

from core.pr993_dual_repo_reevaluation import (
    CanonicalPathId,
    CanonicalPathStatus,
    ClaimValidation,
    ClosurePriority,
    ClosurePriorityLevel,
    EvidenceStrength,
    PR993ClaimId,
    PR993ReevaluationReport,
    PR993_REEVALUATION_AUTHORITY,
    PR993_REEVALUATION_METHODOLOGY,
    assert_pr993_reevaluation_invariants,
    build_pr993_reevaluation,
    get_pr993_reevaluation,
    reset_pr993_reevaluation,
)


# =============================================================================
# SECTION 1 — Module import and sentinel sanity
# =============================================================================


class TestModuleImport:
    """All public symbols must be importable from the module."""

    def test_authority_sentinel_is_string(self) -> None:
        assert isinstance(PR993_REEVALUATION_AUTHORITY, str)
        assert len(PR993_REEVALUATION_AUTHORITY) > 0

    def test_methodology_sentinel_is_string(self) -> None:
        assert isinstance(PR993_REEVALUATION_METHODOLOGY, str)
        assert len(PR993_REEVALUATION_METHODOLOGY) > 0

    def test_claim_id_enum_coverage(self) -> None:
        """PR993ClaimId must cover all 7 PR #993 claim families."""
        claim_ids = list(PR993ClaimId)
        assert len(claim_ids) == 7, (
            f"Expected 7 claim IDs; got {len(claim_ids)}: {[c.value for c in claim_ids]}"
        )

    def test_canonical_path_id_enum_coverage(self) -> None:
        """CanonicalPathId must cover all 6 canonical paths."""
        path_ids = list(CanonicalPathId)
        assert len(path_ids) == 6, (
            f"Expected 6 canonical path IDs; got {len(path_ids)}"
        )

    def test_evidence_strength_enum_values(self) -> None:
        """EvidenceStrength must have 4 tiers."""
        assert len(list(EvidenceStrength)) == 4

    def test_closure_priority_level_enum_values(self) -> None:
        """ClosurePriorityLevel must have 4 tiers."""
        assert len(list(ClosurePriorityLevel)) == 4


# =============================================================================
# SECTION 2 — build_pr993_reevaluation() structural checks
# =============================================================================


class TestBuildReport:
    """build_pr993_reevaluation() must return a structurally complete report."""

    @pytest.fixture(scope="class")
    def report(self) -> PR993ReevaluationReport:
        return build_pr993_reevaluation()

    def test_returns_pr993_reevaluation_report(self, report: PR993ReevaluationReport) -> None:
        assert isinstance(report, PR993ReevaluationReport)

    def test_report_id_is_non_empty_string(self, report: PR993ReevaluationReport) -> None:
        assert isinstance(report.report_id, str)
        assert len(report.report_id) > 0

    def test_generated_at_is_positive(self, report: PR993ReevaluationReport) -> None:
        assert report.generated_at > 0

    def test_system_summary_is_non_empty(self, report: PR993ReevaluationReport) -> None:
        assert isinstance(report.system_summary, str)
        assert len(report.system_summary) > 0

    def test_dual_repo_verdict_is_non_empty(self, report: PR993ReevaluationReport) -> None:
        assert isinstance(report.dual_repo_verdict, str)
        assert len(report.dual_repo_verdict) > 0

    def test_all_claim_ids_present(self, report: PR993ReevaluationReport) -> None:
        """Every PR993ClaimId must appear exactly once in claim_validations."""
        seen = {c.claim_id for c in report.claim_validations}
        for claim_id in PR993ClaimId:
            assert claim_id in seen, (
                f"Missing ClaimValidation for PR993ClaimId.{claim_id.name}."
            )

    def test_all_canonical_path_ids_present(
        self, report: PR993ReevaluationReport
    ) -> None:
        """Every CanonicalPathId must appear exactly once in canonical_path_statuses."""
        seen = {p.path_id for p in report.canonical_path_statuses}
        for path_id in CanonicalPathId:
            assert path_id in seen, (
                f"Missing CanonicalPathStatus for CanonicalPathId.{path_id.name}."
            )

    def test_closure_priorities_non_empty(
        self, report: PR993ReevaluationReport
    ) -> None:
        assert len(report.closure_priorities) > 0

    def test_claim_count_sum_equals_total(
        self, report: PR993ReevaluationReport
    ) -> None:
        total = (
            report.strongly_established_count
            + report.partially_established_count
            + report.surface_alignment_only_count
            + report.missing_runtime_evidence_count
        )
        assert total == len(report.claim_validations)

    def test_path_count_sum_equals_total(
        self, report: PR993ReevaluationReport
    ) -> None:
        assert (
            report.canonical_paths_closed + report.canonical_paths_open
            == len(report.canonical_path_statuses)
        )


# =============================================================================
# SECTION 3 — Claim validation checks
# =============================================================================


class TestClaimValidations:
    """Individual claim validation records must be well-formed."""

    @pytest.fixture(scope="class")
    def by_id(self) -> dict:
        report = build_pr993_reevaluation()
        return {c.claim_id: c for c in report.claim_validations}

    def test_no_claim_is_missing_runtime_evidence(self, by_id: dict) -> None:
        """No top-level PR #993 claim should fall into the lowest evidence tier.

        All claims have at least structural/importable code evidence.
        """
        for claim_id, claim in by_id.items():
            assert claim.evidence_strength != EvidenceStrength.MISSING_RUNTIME_EVIDENCE, (
                f"Claim {claim_id.value} unexpectedly has MISSING_RUNTIME_EVIDENCE. "
                f"Gap note: {claim.gap_note}"
            )

    def test_system_identity_is_strongly_or_partially(self, by_id: dict) -> None:
        """System identity claim should be at least PARTIALLY_ESTABLISHED."""
        claim = by_id[PR993ClaimId.SYSTEM_IDENTITY_DISTRIBUTED_AI_BODY]
        assert claim.evidence_strength in (
            EvidenceStrength.STRONGLY_ESTABLISHED,
            EvidenceStrength.PARTIALLY_ESTABLISHED,
        ), f"Unexpected evidence strength: {claim.evidence_strength}"

    def test_v2_governance_has_code_anchors(self, by_id: dict) -> None:
        """V2 governance claim must have real code anchors."""
        claim = by_id[PR993ClaimId.V2_SOLE_GOVERNANCE_AUTHORITY]
        assert len(claim.code_anchors) >= 4, (
            f"V2 governance claim should have at least 4 code anchors; "
            f"got {len(claim.code_anchors)}: {claim.code_anchors}"
        )

    def test_android_runtime_carrier_has_code_anchors(self, by_id: dict) -> None:
        """Android runtime carrier claim must have real code anchors."""
        claim = by_id[PR993ClaimId.ANDROID_IS_RUNTIME_CARRIER_NOT_CLIENT]
        assert len(claim.code_anchors) >= 3, (
            f"Android runtime carrier claim should have at least 3 code anchors; "
            f"got {len(claim.code_anchors)}"
        )

    def test_network_is_body_has_multiple_proofs(self, by_id: dict) -> None:
        """Network-is-body claim must have at least 3 of the 5 structural proofs."""
        claim = by_id[PR993ClaimId.NETWORK_IS_THE_BODY]
        assert len(claim.code_anchors) >= 3, (
            f"Network-is-body claim should have at least 3 proof anchors; "
            f"got {len(claim.code_anchors)}"
        )

    def test_beyond_poc_has_four_chain_anchors(self, by_id: dict) -> None:
        """Beyond-PoC claim must confirm all 4 execution chains by import."""
        claim = by_id[PR993ClaimId.SYSTEM_BEYOND_POC]
        # Should have registration, capability_report, delegated_signal, handoff_v2_result
        assert len(claim.code_anchors) >= 4, (
            f"Beyond-PoC claim should have at least 4 chain anchors; "
            f"got {len(claim.code_anchors)}"
        )

    def test_remaining_work_closure_is_partially_established(
        self, by_id: dict
    ) -> None:
        """Remaining-work-is-closure claim should be PARTIALLY_ESTABLISHED.

        PR #993 itself acknowledged Axis 2 wire path as incomplete.
        A STRONGLY_ESTABLISHED verdict here would be inaccurate.
        """
        claim = by_id[PR993ClaimId.REMAINING_WORK_IS_CLOSURE_NOT_CAPABILITY]
        assert claim.evidence_strength == EvidenceStrength.PARTIALLY_ESTABLISHED, (
            f"remaining_work_closure expected PARTIALLY_ESTABLISHED; "
            f"got {claim.evidence_strength}. "
            "This claim cannot be STRONGLY_ESTABLISHED while the runtime state "
            "transparency axis still has a CI evidence gap."
        )

    def test_all_claims_have_android_side_evidence_string(
        self, by_id: dict
    ) -> None:
        """All claims must have a non-empty android_side_evidence string."""
        for claim_id, claim in by_id.items():
            assert claim.android_side_evidence, (
                f"Claim {claim_id.value} has empty android_side_evidence. "
                "All claims must document Android-side evidence."
            )


# =============================================================================
# SECTION 4 — Canonical path status checks
# =============================================================================


class TestCanonicalPathStatuses:
    """Canonical path status records must accurately reflect code reality."""

    @pytest.fixture(scope="class")
    def by_id(self) -> dict:
        report = build_pr993_reevaluation()
        return {p.path_id: p for p in report.canonical_path_statuses}

    def test_android_registration_is_v2_implemented(self, by_id: dict) -> None:
        """Android registration V2 side must be implemented."""
        path = by_id[CanonicalPathId.ANDROID_REGISTRATION]
        assert path.v2_side_implemented, (
            "galaxy_gateway.android.handlers.registration should be importable."
        )

    def test_android_registration_is_android_implemented(self, by_id: dict) -> None:
        """Android registration Android side must be implemented."""
        path = by_id[CanonicalPathId.ANDROID_REGISTRATION]
        assert path.android_side_implemented

    def test_runtime_snapshot_is_not_runtime_closed(self, by_id: dict) -> None:
        """Runtime snapshot uplink should NOT claim runtime_closed.

        No CI cross-repo emulator evidence exists.
        """
        path = by_id[CanonicalPathId.RUNTIME_SNAPSHOT_UPLINK]
        assert not path.runtime_closed, (
            "runtime_snapshot_uplink should not be runtime_closed — "
            "no CI emulator-backed cross-repo proof exists."
        )

    def test_runtime_snapshot_closure_label(self, by_id: dict) -> None:
        """Runtime snapshot uplink should be surface_alignment_only."""
        path = by_id[CanonicalPathId.RUNTIME_SNAPSHOT_UPLINK]
        assert path.closure_label == "surface_alignment_only", (
            f"Expected 'surface_alignment_only'; got {path.closure_label!r}."
        )

    def test_execution_event_is_not_runtime_closed(self, by_id: dict) -> None:
        """Execution event uplink should not be runtime_closed."""
        path = by_id[CanonicalPathId.EXECUTION_EVENT_UPLINK]
        assert not path.runtime_closed

    def test_task_dispatch_result_is_v2_implemented(self, by_id: dict) -> None:
        """Task dispatch/execute/result path V2 side must be implemented."""
        path = by_id[CanonicalPathId.TASK_DISPATCH_EXECUTE_RESULT]
        assert path.v2_side_implemented, (
            "DeviceRouter, task_lifecycle handler, handoff_v2_result should be importable."
        )

    def test_orchestration_consumes_android_truth_is_not_runtime_closed(
        self, by_id: dict
    ) -> None:
        """Orchestration-consumes-Android-truth should not be runtime_closed.

        The store is never filled in CI so the consume path has no real input.
        """
        path = by_id[CanonicalPathId.ORCHESTRATION_CONSUMES_ANDROID_TRUTH]
        assert not path.runtime_closed

    def test_all_paths_have_description(self, by_id: dict) -> None:
        """All canonical path statuses must have a non-empty description."""
        for path_id, path in by_id.items():
            assert path.description, (
                f"CanonicalPathId.{path_id.name} has empty description."
            )

    def test_open_paths_have_gap_description(self, by_id: dict) -> None:
        """All non-closed paths must have a non-empty gap_description."""
        for path_id, path in by_id.items():
            if not path.runtime_closed:
                assert path.gap_description, (
                    f"CanonicalPathId.{path_id.name} is not runtime_closed but "
                    "has empty gap_description."
                )


# =============================================================================
# SECTION 5 — Closure priority checks
# =============================================================================


class TestClosurePriorities:
    """Closure priority (next-PR roadmap) records must be well-formed."""

    @pytest.fixture(scope="class")
    def priorities(self) -> list:
        report = build_pr993_reevaluation()
        return report.closure_priorities

    def test_at_least_two_p0_priorities(self, priorities: list) -> None:
        """At least 2 P0 priorities must be defined (PR-A and PR-B)."""
        p0 = [p for p in priorities if p.level == ClosurePriorityLevel.P0_RUNTIME_EVIDENCE_BLOCKER]
        assert len(p0) >= 2, (
            f"Expected at least 2 P0 priorities; got {len(p0)}: "
            f"{[p.priority_id for p in p0]}"
        )

    def test_at_least_one_p1_priority(self, priorities: list) -> None:
        """At least 1 P1 priority must be defined."""
        p1 = [p for p in priorities if p.level == ClosurePriorityLevel.P1_CANONICAL_CLOSURE_GAP]
        assert len(p1) >= 1, f"Expected at least 1 P1 priority; got {len(p1)}."

    def test_p0_priorities_target_both_repos(self, priorities: list) -> None:
        """P0 priorities must target both repositories."""
        p0 = [p for p in priorities if p.level == ClosurePriorityLevel.P0_RUNTIME_EVIDENCE_BLOCKER]
        for p in p0:
            assert "DannyFish-11/ufo-galaxy-realization-v2" in p.target_repos, (
                f"P0 priority {p.priority_id} must target V2 repo."
            )
            assert "DannyFish-11/ufo-galaxy-android" in p.target_repos, (
                f"P0 priority {p.priority_id} must target Android repo."
            )

    def test_all_priorities_have_rationale(self, priorities: list) -> None:
        """Every priority must have a non-empty rationale."""
        for p in priorities:
            assert p.rationale, (
                f"Priority {p.priority_id} has empty rationale."
            )

    def test_priority_ids_are_unique(self, priorities: list) -> None:
        """Priority IDs must be unique."""
        ids = [p.priority_id for p in priorities]
        assert len(ids) == len(set(ids)), (
            f"Duplicate priority IDs: {ids}"
        )

    def test_android_runtime_ci_evidence_priority_exists(
        self, priorities: list
    ) -> None:
        """The PR-A runtime evidence P0 priority must be present."""
        ids = [p.priority_id for p in priorities]
        assert "P0-ANDROID-RUNTIME-CI-EVIDENCE" in ids, (
            f"Expected P0-ANDROID-RUNTIME-CI-EVIDENCE in priorities; got {ids}."
        )

    def test_delegated_exec_closure_priority_exists(
        self, priorities: list
    ) -> None:
        """The PR-B delegated execution P0 priority must be present."""
        ids = [p.priority_id for p in priorities]
        assert "P0-DELEGATED-EXEC-RUNTIME-CLOSURE" in ids, (
            f"Expected P0-DELEGATED-EXEC-RUNTIME-CLOSURE in priorities; got {ids}."
        )


# =============================================================================
# SECTION 6 — Serialisation checks
# =============================================================================


class TestSerialisation:
    """Report must be fully JSON-serialisable."""

    @pytest.fixture(scope="class")
    def report(self) -> PR993ReevaluationReport:
        return build_pr993_reevaluation()

    def test_to_dict_returns_dict(self, report: PR993ReevaluationReport) -> None:
        d = report.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_contains_required_keys(
        self, report: PR993ReevaluationReport
    ) -> None:
        d = report.to_dict()
        for key in (
            "report_id",
            "generated_at",
            "methodology",
            "claim_validations",
            "canonical_path_statuses",
            "closure_priorities",
            "system_summary",
            "dual_repo_verdict",
            "strongly_established_count",
            "partially_established_count",
            "surface_alignment_only_count",
            "missing_runtime_evidence_count",
            "canonical_paths_closed",
            "canonical_paths_open",
        ):
            assert key in d, f"Missing key '{key}' in to_dict() output."

    def test_to_json_is_valid_json(self, report: PR993ReevaluationReport) -> None:
        j = report.to_json()
        assert isinstance(j, str)
        parsed = json.loads(j)
        assert isinstance(parsed, dict)

    def test_claim_validation_to_dict(self, report: PR993ReevaluationReport) -> None:
        for claim in report.claim_validations:
            d = claim.to_dict()
            assert isinstance(d, dict)
            assert "claim_id" in d
            assert "evidence_strength" in d
            assert "code_anchors" in d

    def test_canonical_path_status_to_dict(
        self, report: PR993ReevaluationReport
    ) -> None:
        for path in report.canonical_path_statuses:
            d = path.to_dict()
            assert isinstance(d, dict)
            assert "path_id" in d
            assert "runtime_closed" in d
            assert "closure_label" in d

    def test_closure_priority_to_dict(
        self, report: PR993ReevaluationReport
    ) -> None:
        for p in report.closure_priorities:
            d = p.to_dict()
            assert isinstance(d, dict)
            assert "priority_id" in d
            assert "level" in d
            assert "target_repos" in d


# =============================================================================
# SECTION 7 — Singleton caching and test isolation
# =============================================================================


class TestSingletonCaching:
    """Singleton caching and reset must work correctly."""

    def test_get_returns_same_instance_on_second_call(self) -> None:
        reset_pr993_reevaluation()
        r1 = get_pr993_reevaluation()
        r2 = get_pr993_reevaluation()
        assert r1 is r2, "get_pr993_reevaluation() should return the same instance."

    def test_reset_clears_cache(self) -> None:
        reset_pr993_reevaluation()
        r1 = get_pr993_reevaluation()
        reset_pr993_reevaluation()
        r2 = get_pr993_reevaluation()
        assert r1 is not r2, "After reset, a new instance must be created."

    def test_build_always_returns_new_instance(self) -> None:
        r1 = build_pr993_reevaluation()
        r2 = build_pr993_reevaluation()
        assert r1 is not r2, "build_pr993_reevaluation() should return a new instance each call."


# =============================================================================
# SECTION 8 — Invariant assertion suite
# =============================================================================


class TestInvariantSuite:
    """assert_pr993_reevaluation_invariants() must pass without raising."""

    def test_invariants_pass(self) -> None:
        """The full invariant suite must pass without raising AssertionError."""
        reset_pr993_reevaluation()
        assert_pr993_reevaluation_invariants()


# =============================================================================
# SECTION 9 — PR #993 validation matrix spot-checks
# =============================================================================


class TestValidationMatrix:
    """Spot-checks against the expected PR #993 validation matrix outcomes."""

    @pytest.fixture(scope="class")
    def report(self) -> PR993ReevaluationReport:
        reset_pr993_reevaluation()
        return build_pr993_reevaluation()

    def test_system_has_at_least_one_strongly_established_claim(
        self, report: PR993ReevaluationReport
    ) -> None:
        """The system must have at least one strongly-established PR #993 claim."""
        assert report.strongly_established_count >= 1, (
            "Expected at least 1 STRONGLY_ESTABLISHED claim. "
            "The basic structural architecture (DeviceType, CommandRouter, OpenClawd) "
            "should produce at least one strong claim."
        )

    def test_system_has_at_least_one_partially_established_claim(
        self, report: PR993ReevaluationReport
    ) -> None:
        """At least 1 claim should be PARTIALLY_ESTABLISHED.

        Claim 6 (remaining work is closure) must be PARTIALLY_ESTABLISHED
        because Axis 2 (Android→V2 runtime state transparency) has a known
        CI evidence gap regardless of structural code presence.
        """
        assert report.partially_established_count >= 1, (
            f"Expected at least 1 PARTIALLY_ESTABLISHED claim; "
            f"got {report.partially_established_count}. "
            "The remaining_work_is_closure claim should be PARTIALLY_ESTABLISHED."
        )

    def test_system_has_no_missing_runtime_evidence_claims(
        self, report: PR993ReevaluationReport
    ) -> None:
        """No claim should be MISSING_RUNTIME_EVIDENCE."""
        assert report.missing_runtime_evidence_count == 0

    def test_majority_of_canonical_paths_are_open(
        self, report: PR993ReevaluationReport
    ) -> None:
        """Most canonical paths should still be open (no CI emulator evidence).

        The honest characterization is that the system architecture is complete
        but CI runtime proof is absent for most cross-repo paths.
        """
        assert report.canonical_paths_open >= 3, (
            f"Expected at least 3 open canonical paths; got {report.canonical_paths_open}. "
            "Without CI cross-repo emulator tests, most paths cannot be runtime_closed."
        )

    def test_android_registration_path_is_best_evidenced(
        self, report: PR993ReevaluationReport
    ) -> None:
        """Android registration should be among the most evidenced paths.

        Unit tests exist (test_android_capability_assimilation_ingress.py).
        """
        by_id = {p.path_id: p for p in report.canonical_path_statuses}
        reg = by_id[CanonicalPathId.ANDROID_REGISTRATION]
        # At minimum it should be v2_implemented
        assert reg.v2_side_implemented, (
            "Android registration V2 side should be implemented — "
            "galaxy_gateway.android.handlers.registration should be importable."
        )

    def test_verdict_contains_structurally_complete(
        self, report: PR993ReevaluationReport
    ) -> None:
        """The dual_repo_verdict must acknowledge structural completeness."""
        assert "STRUCTURALLY_COMPLETE" in report.dual_repo_verdict, (
            "dual_repo_verdict should contain 'STRUCTURALLY_COMPLETE' — "
            "the system architecture is structurally complete even if CI evidence is partial."
        )

    def test_p0_snapshot_evidence_gap_is_documented(
        self, report: PR993ReevaluationReport
    ) -> None:
        """The P0 snapshot evidence gap (PR-A) must be documented in priorities."""
        p0_snapshot = next(
            (
                p
                for p in report.closure_priorities
                if p.priority_id == "P0-ANDROID-RUNTIME-CI-EVIDENCE"
            ),
            None,
        )
        assert p0_snapshot is not None, "P0-ANDROID-RUNTIME-CI-EVIDENCE must be in priorities."
        assert "snapshot" in p0_snapshot.rationale.lower() or "store" in p0_snapshot.rationale.lower(), (
            "P0 snapshot priority rationale must mention 'snapshot' or 'store'."
        )
