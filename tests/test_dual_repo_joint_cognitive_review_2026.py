"""tests/test_dual_repo_joint_cognitive_review_2026.py
======================================================
Tests for core/dual_repo_joint_cognitive_review_2026.py — the 2026
dual-repo joint cognitive review module.

These tests verify that:
1. The module's code-grounded probes run without exception.
2. The seven cognitive areas are all covered.
3. Area verdicts are one of the defined JointCognitiveVerdict values.
4. The ANDROID_HEAD_AT_REVIEW constant matches the audited Android HEAD.
5. The JOINT_COGNITIVE_VERDICTS pre-computed dict is well-formed.
6. The overall report serialises cleanly.
7. V2 main path probe passes (fully_real).
8. Temporal probe passes (conditionally_real, not nominal_only).
9. Stage 10 scheduling probe passes (structural_authority, not nominal_only).
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

from core.dual_repo_joint_cognitive_review_2026 import (
    ANDROID_HEAD_AT_REVIEW,
    JOINT_COGNITIVE_REVIEW_AUTHORITY,
    JOINT_COGNITIVE_VERDICTS,
    JointCognitiveAreaId,
    JointCognitiveAreaResult,
    JointCognitiveReport,
    JointCognitiveVerdict,
    build_strict_dual_repo_total_review,
    build_joint_cognitive_review,
)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


class TestModuleConstants:
    def test_android_head_at_review_format(self) -> None:
        """ANDROID_HEAD_AT_REVIEW must be a valid 40-char hex SHA."""
        assert isinstance(ANDROID_HEAD_AT_REVIEW, str)
        assert len(ANDROID_HEAD_AT_REVIEW) == 40
        # must be lowercase hex
        assert ANDROID_HEAD_AT_REVIEW == ANDROID_HEAD_AT_REVIEW.lower()
        assert all(c in "0123456789abcdef" for c in ANDROID_HEAD_AT_REVIEW)

    def test_android_head_matches_current_review_ref(self) -> None:
        """ANDROID_HEAD_AT_REVIEW must match the ref updated in this PR."""
        assert ANDROID_HEAD_AT_REVIEW == "be9aeb91057bfa3fb648834e5f0997d019e34542"

    def test_authority_sentinel_format(self) -> None:
        assert "DUAL_REPO_JOINT_COGNITIVE_REVIEW" in JOINT_COGNITIVE_REVIEW_AUTHORITY
        assert "2026" in JOINT_COGNITIVE_REVIEW_AUTHORITY

    def test_pre_computed_verdicts_all_areas_covered(self) -> None:
        """JOINT_COGNITIVE_VERDICTS must include every JointCognitiveAreaId."""
        defined_area_ids = {a.value for a in JointCognitiveAreaId}
        missing = defined_area_ids - set(JOINT_COGNITIVE_VERDICTS.keys())
        assert not missing, f"JOINT_COGNITIVE_VERDICTS missing areas: {missing}"

    def test_pre_computed_verdicts_values_valid(self) -> None:
        """All verdict values must be valid JointCognitiveVerdict members."""
        valid = {v.value for v in JointCognitiveVerdict}
        for area_id, verdict_val in JOINT_COGNITIVE_VERDICTS.items():
            assert verdict_val in valid, (
                f"Area {area_id!r} has invalid verdict {verdict_val!r}; "
                f"expected one of {sorted(valid)}"
            )

    def test_v2_main_path_verdict_is_fully_real(self) -> None:
        """V2 main path must be declared fully_real."""
        key = JointCognitiveAreaId.v2_real_main_path.value
        assert JOINT_COGNITIVE_VERDICTS[key] == JointCognitiveVerdict.fully_real.value

    def test_temporal_verdict_is_conditionally_real(self) -> None:
        """Temporal must be declared conditionally_real (not nominal_only)."""
        key = JointCognitiveAreaId.temporal_conditional_real.value
        verdict = JOINT_COGNITIVE_VERDICTS[key]
        assert verdict == JointCognitiveVerdict.conditionally_real.value, (
            f"Temporal should be conditionally_real, got {verdict!r}"
        )

    def test_stage10_verdict_is_structural_authority(self) -> None:
        """Stage 10 scheduling convergence must be declared structural_authority."""
        key = JointCognitiveAreaId.stage10_scheduling_convergence.value
        verdict = JOINT_COGNITIVE_VERDICTS[key]
        assert verdict == JointCognitiveVerdict.structural_authority.value, (
            f"Stage 10 should be structural_authority, got {verdict!r}"
        )

    def test_android_role_is_partially_wired(self) -> None:
        """Android role must be declared partially_wired (not fully_real)."""
        key = JointCognitiveAreaId.android_real_role.value
        verdict = JOINT_COGNITIVE_VERDICTS[key]
        assert verdict == JointCognitiveVerdict.partially_wired.value, (
            f"Android role should be partially_wired, got {verdict!r}"
        )


# ---------------------------------------------------------------------------
# build_joint_cognitive_review() — smoke + structure
# ---------------------------------------------------------------------------


class TestBuildJointCognitiveReview:
    def test_runs_without_exception(self) -> None:
        report = build_joint_cognitive_review()
        assert isinstance(report, JointCognitiveReport)

    def test_all_seven_areas_present(self) -> None:
        report = build_joint_cognitive_review()
        area_ids = {a.area_id for a in report.areas}
        expected = {a.value for a in JointCognitiveAreaId}
        missing = expected - area_ids
        assert not missing, f"Report missing cognitive areas: {missing}"

    def test_area_verdicts_valid(self) -> None:
        """Every area verdict must be a JointCognitiveVerdict value."""
        report = build_joint_cognitive_review()
        valid = {v.value for v in JointCognitiveVerdict}
        for area in report.areas:
            assert area.verdict.value in valid, (
                f"Area {area.area_id!r} has invalid verdict {area.verdict!r}"
            )

    def test_metadata_preserved(self) -> None:
        report = build_joint_cognitive_review()
        assert report.android_head_at_review == ANDROID_HEAD_AT_REVIEW
        assert "DUAL_REPO_JOINT_COGNITIVE_REVIEW" in report.authority

    def test_counts_consistent(self) -> None:
        report = build_joint_cognitive_review()
        assert report.probe_passed_count + report.probe_failed_count == len(report.areas)
        assert report.probe_passed_count >= 0
        assert report.probe_failed_count >= 0

    def test_overall_summary_non_empty(self) -> None:
        report = build_joint_cognitive_review()
        assert report.overall_summary_zh, "overall_summary_zh must not be empty"

    def test_serialises_to_json(self) -> None:
        report = build_joint_cognitive_review()
        serialised = json.dumps(report.to_dict(), ensure_ascii=False)
        assert len(serialised) > 100
        parsed = json.loads(serialised)
        assert "areas" in parsed
        assert "android_head_at_review" in parsed
        assert parsed["android_head_at_review"] == ANDROID_HEAD_AT_REVIEW

    def test_pre_computed_verdicts_in_report(self) -> None:
        report = build_joint_cognitive_review()
        assert report.pre_computed_verdicts
        assert set(report.pre_computed_verdicts.keys()) == {a.value for a in JointCognitiveAreaId}

    def test_evidence_strings_non_empty(self) -> None:
        report = build_joint_cognitive_review()
        for area in report.areas:
            assert area.evidence_zh, (
                f"Area {area.area_id!r} must have non-empty evidence_zh"
            )

    def test_honest_gap_strings_present(self) -> None:
        """Every area result must have a non-empty honest_gap_zh."""
        report = build_joint_cognitive_review()
        for area in report.areas:
            assert area.honest_gap_zh, (
                f"Area {area.area_id!r} must have non-empty honest_gap_zh "
                "(no gap is dishonest — even fully_real areas should note cross-device limits)"
            )


# ---------------------------------------------------------------------------
# Per-area probe pass/fail expectations
# ---------------------------------------------------------------------------


class TestPerAreaProbeResults:
    """Verify specific probes pass or have the expected verdict.

    These tests assert on the actual probe results, making the cognitive
    review's code-grounded claims verifiable by the test suite.
    """

    def _get_area(self, report: JointCognitiveReport, area_id: str) -> JointCognitiveAreaResult:
        for area in report.areas:
            if area.area_id == area_id:
                return area
        pytest.fail(f"Area {area_id!r} not found in report")

    def test_v2_main_path_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.v2_real_main_path.value)
        assert area.probe_passed, (
            f"V2 main path probe must pass. Detail: {area.probe_detail}"
        )
        assert area.verdict == JointCognitiveVerdict.fully_real

    def test_nats_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.nats_distributed_activation.value)
        assert area.probe_passed, (
            f"NATS distributed activation probe must pass. Detail: {area.probe_detail}"
        )

    def test_temporal_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.temporal_conditional_real.value)
        assert area.probe_passed, (
            f"Temporal probe must pass. Detail: {area.probe_detail}"
        )
        assert area.verdict != JointCognitiveVerdict.nominal_only, (
            "Temporal must not be nominal_only — it is real SDK code, even if conditionally active"
        )

    def test_android_role_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.android_real_role.value)
        assert area.probe_passed, (
            f"Android role probe must pass. Detail: {area.probe_detail}"
        )
        assert area.verdict == JointCognitiveVerdict.partially_wired, (
            "Android role must be partially_wired — not fully_real (needs live device)"
        )

    def test_dual_repo_coupling_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.dual_repo_coupling_boundary.value)
        assert area.probe_passed, (
            f"Dual-repo coupling probe must pass. Detail: {area.probe_detail}"
        )

    def test_stage6_to_9_hardening_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.stage6_to_9_hardening.value)
        assert area.probe_passed, (
            f"Stage 6-9 hardening probe must pass. Detail: {area.probe_detail}"
        )
        assert area.verdict != JointCognitiveVerdict.nominal_only, (
            "Stage 6-9 hardening must not be nominal_only — it is real code"
        )

    def test_stage10_scheduling_probe_passes(self) -> None:
        report = build_joint_cognitive_review()
        area = self._get_area(report, JointCognitiveAreaId.stage10_scheduling_convergence.value)
        assert area.probe_passed, (
            f"Stage 10 scheduling convergence probe must pass. Detail: {area.probe_detail}"
        )
        assert area.verdict == JointCognitiveVerdict.structural_authority, (
            "Stage 10 must be structural_authority (harness exists, not all callers route through it)"
        )


# ---------------------------------------------------------------------------
# Stage 6-10 cognition audit integration
# ---------------------------------------------------------------------------


class TestDeepestCognitionAuditStage6to10:
    """Verify Stage 6-10 checks integrated into deepest_dual_repo_cognition_audit."""

    def test_stage6_check_importable(self) -> None:
        from core.deepest_dual_repo_cognition_audit import check_stage6_master_brain_nats_lifecycle
        result = check_stage6_master_brain_nats_lifecycle()
        assert result.passed, f"Stage 6 check failed: {result.failure_detail}"

    def test_stage7_check_importable(self) -> None:
        from core.deepest_dual_repo_cognition_audit import (
            check_stage7_distributed_execution_result_correlation,
        )
        result = check_stage7_distributed_execution_result_correlation()
        assert result.passed, f"Stage 7 check failed: {result.failure_detail}"

    def test_stage8_check_importable(self) -> None:
        from core.deepest_dual_repo_cognition_audit import check_stage8_master_brain_state_persistence
        result = check_stage8_master_brain_state_persistence()
        assert result.passed, f"Stage 8 check failed: {result.failure_detail}"

    def test_stage9_check_importable(self) -> None:
        from core.deepest_dual_repo_cognition_audit import check_stage9_temporal_conditional_real
        result = check_stage9_temporal_conditional_real()
        assert result.passed, f"Stage 9 check failed: {result.failure_detail}"

    def test_stage10_check_importable(self) -> None:
        from core.deepest_dual_repo_cognition_audit import check_stage10_scheduling_truth_harness
        result = check_stage10_scheduling_truth_harness()
        assert result.passed, f"Stage 10 check failed: {result.failure_detail}"

    def test_stage6_to_10_included_in_audit_snapshot(self) -> None:
        """Stage 6-10 check names must appear in the full audit snapshot."""
        from core.deepest_dual_repo_cognition_audit import build_cognition_audit_snapshot

        snapshot = build_cognition_audit_snapshot()
        check_names = {c["check_name"] for c in snapshot["checks"]}
        expected = {
            "stage6_master_brain_nats_lifecycle",
            "stage7_distributed_execution_result_correlation",
            "stage8_master_brain_state_persistence",
            "stage9_temporal_conditional_real",
            "stage10_scheduling_truth_harness",
        }
        missing = expected - check_names
        assert not missing, f"Stage 6-10 checks missing from audit snapshot: {missing}"

    def test_system_verdict_updated_for_stage6_to_10(self) -> None:
        """SYSTEM_VERDICT must reference Stage 6-10 hardening."""
        from core.deepest_dual_repo_cognition_audit import SYSTEM_VERDICT

        assert "STAGE6_TO_10" in SYSTEM_VERDICT, (
            f"SYSTEM_VERDICT must reflect Stage 6-10 hardening: {SYSTEM_VERDICT!r}"
        )


# ---------------------------------------------------------------------------
# complete_joint_system_review android_audited_ref is current
# ---------------------------------------------------------------------------


class TestCompleteJointSystemReviewRefUpdated:
    def test_android_audited_ref_matches_current_head(self) -> None:
        """complete_joint_system_review.ANDROID_AUDITED_REF must match current Android HEAD."""
        from core.complete_joint_system_review import ANDROID_AUDITED_REF

        assert ANDROID_AUDITED_REF == "be9aeb91057bfa3fb648834e5f0997d019e34542", (
            f"ANDROID_AUDITED_REF is stale: {ANDROID_AUDITED_REF!r}. "
            "Update to match the current Android HEAD reviewed in this PR."
        )


class TestStrictDualRepoTotalReview:
    def test_strict_review_has_required_sections(self) -> None:
        review = build_strict_dual_repo_total_review()
        assert review["positioning"] == "中心相对主体的分布式 AI 系统"
        assert review["strong_judgments"]
        assert review["closure_grading_table"]
        assert review["unresolved_issues"]
        assert review["implementation_priorities"]

    def test_strong_judgment_declares_center_subject_and_participant_runtime(self) -> None:
        review = build_strict_dual_repo_total_review()
        judgments = "\n".join(item["judgment"] for item in review["strong_judgments"])
        assert "V2 已形成 runtime shell" in judgments
        assert "V2 中心主体 + Android participant runtime" in judgments

    def test_closure_table_covers_required_grade_classes(self) -> None:
        review = build_strict_dual_repo_total_review()
        grades = {row["grade"] for row in review["closure_grading_table"]}
        assert "真实闭环" in grades
        assert "半闭环" in grades
        assert "contract/formal 成立" in grades
        assert "helper/test/probe/audit 成立" in grades
        assert "默认主路径未成立" in grades

    def test_required_unresolved_issues_are_explicit(self) -> None:
        review = build_strict_dual_repo_total_review()
        issues = "\n".join(review["unresolved_issues"])
        assert "主体仍锚定 V2" in issues
        assert "/ws/webrtc 仍为 media-only" in issues
        assert "DEVICE_PERCEPTION_EMISSION" in issues
        assert "ANDROID_AUDITED_REF 不一致" in issues
        assert "default-off 能力" in issues

    def test_evidence_probes_capture_default_off_and_protocol_mismatch(self) -> None:
        review = build_strict_dual_repo_total_review()
        probes = review["evidence_probes"]
        assert probes["chat_is_adapter_surface"] is True
        assert probes["ws_device_canonical"] is True
        assert probes["ws_webrtc_media_only"] is True
        assert probes["default_multimodal_off"] is True
        assert probes["v2_has_device_perception_emission"] is False
        assert probes["cross_repo_ref_mismatch"] is True
