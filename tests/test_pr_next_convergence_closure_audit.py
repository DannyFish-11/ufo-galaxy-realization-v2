"""
tests/test_pr_next_convergence_closure_audit.py
================================================
Tests for core/pr_next_convergence_closure_audit.py

Validates the PR-next-convergence audit module:
- ConvergenceClosureAuditRecord structure and serialization
- CloneToRunAudit practical operability assessment
- ThreeStateRuntimeAudit three-state presence audit
- ClosureGovernancePropagationAudit Android truth propagation audit
- AndroidTruthInOperatorBoardAudit operator board audit
- get_board_reasoning_for_closure() board reasoning API
"""
from __future__ import annotations

import time
from typing import Any, Dict

import pytest

from core.pr_next_convergence_closure_audit import (
    PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY,
    PR_NEXT_CONVERGENCE_CONTRACT_VERSION,
    PR_NEXT_CONVERGENCE_PR_TITLE,
    PR_NEXT_CONVERGENCE_PR_TITLE_EN,
    PR_NEXT_CONVERGENCE_ANCHOR,
    OperabilityVerdict,
    ThreeStateSourceVerdict,
    ClosureGovernancePropagationTier,
    CloneToRunAudit,
    CloneToRunAuditCheckpoint,
    ThreeStateRuntimeAudit,
    ClosureGovernancePropagationAudit,
    AndroidTruthInOperatorBoardAudit,
    ConvergenceClosureAuditRecord,
    build_clone_to_run_audit,
    build_three_state_runtime_audit,
    build_closure_governance_propagation_audit,
    build_android_truth_operator_board_audit,
    get_board_reasoning_for_closure,
    build_convergence_closure_audit,
)


# ---------------------------------------------------------------------------
# 权威标志与合同版本测试
# ---------------------------------------------------------------------------


class TestAuthoritySentinels:
    def test_authority_contains_pr_next_convergence(self):
        assert "PR_NEXT_CONVERGENCE_CLOSURE_AUDIT" in PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY

    def test_authority_identifies_module(self):
        assert "core.pr_next_convergence_closure_audit" in PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY

    def test_contract_version_semver(self):
        parts = PR_NEXT_CONVERGENCE_CONTRACT_VERSION.split(".")
        assert len(parts) == 3, "Contract version must be X.Y.Z semver"

    def test_pr_title_is_chinese(self):
        # Title should contain Chinese characters
        assert PR_NEXT_CONVERGENCE_PR_TITLE, "PR title must be non-empty"
        # The Chinese title should contain key terms
        assert "可用性" in PR_NEXT_CONVERGENCE_PR_TITLE or "审查" in PR_NEXT_CONVERGENCE_PR_TITLE
        assert "闭环" in PR_NEXT_CONVERGENCE_PR_TITLE or "治理" in PR_NEXT_CONVERGENCE_PR_TITLE

    def test_pr_title_en_contains_key_terms(self):
        title_lower = PR_NEXT_CONVERGENCE_PR_TITLE_EN.lower()
        assert "operability" in title_lower or "closure" in title_lower
        assert "operator" in title_lower or "governance" in title_lower

    def test_convergence_anchor_is_993p2(self):
        assert PR_NEXT_CONVERGENCE_ANCHOR == "993P2"


# ---------------------------------------------------------------------------
# 枚举测试
# ---------------------------------------------------------------------------


class TestEnumerations:
    def test_operability_verdict_values(self):
        assert OperabilityVerdict.CLONE_READY.value == "clone_ready"
        assert OperabilityVerdict.PARTIALLY_OPERABLE.value == "partially_operable"
        assert OperabilityVerdict.BLOCKED.value == "blocked"

    def test_three_state_source_verdict_values(self):
        assert ThreeStateSourceVerdict.EXISTS_IN_CODE.value == "exists_in_code"
        assert ThreeStateSourceVerdict.PARTIALLY_IN_CODE.value == "partially_in_code"
        assert ThreeStateSourceVerdict.NARRATIVE_ONLY.value == "narrative_only"

    def test_closure_propagation_tier_values(self):
        assert ClosureGovernancePropagationTier.FULLY_PROPAGATED.value == "fully_propagated"
        assert ClosureGovernancePropagationTier.PARTIALLY_PROPAGATED.value == "partially_propagated"
        assert ClosureGovernancePropagationTier.ROUTING_ONLY.value == "routing_only"
        assert ClosureGovernancePropagationTier.NOT_PROPAGATED.value == "not_propagated"


# ---------------------------------------------------------------------------
# CloneToRunAudit 测试
# ---------------------------------------------------------------------------


class TestCloneToRunAudit:
    def test_build_returns_audit(self):
        audit = build_clone_to_run_audit()
        assert isinstance(audit, CloneToRunAudit)

    def test_has_operability_verdict(self):
        audit = build_clone_to_run_audit()
        assert audit.operability_verdict in list(OperabilityVerdict)

    def test_has_checkpoints(self):
        audit = build_clone_to_run_audit()
        assert len(audit.checkpoints) >= 5, "Must have at least 5 checkpoints"

    def test_checkpoints_have_required_fields(self):
        audit = build_clone_to_run_audit()
        for cp in audit.checkpoints:
            assert cp.checkpoint_id, "Each checkpoint must have an ID"
            assert cp.description_zh, "Each checkpoint must have a description"
            assert cp.evidence_zh, "Each checkpoint must have evidence"
            assert isinstance(cp.passed, bool)
            assert isinstance(cp.blocking, bool)

    def test_has_android_local_mode_verdict(self):
        audit = build_clone_to_run_audit()
        assert audit.android_local_mode_verdict_zh
        # Should mention AutonomousExecutionPipeline or local mode concepts
        assert (
            "AutonomousExecutionPipeline" in audit.android_local_mode_verdict_zh
            or "本地" in audit.android_local_mode_verdict_zh
        )

    def test_has_multi_device_verdict(self):
        audit = build_clone_to_run_audit()
        assert audit.multi_device_reality_verdict_zh
        # Should distinguish between semantic and runtime-level claims
        assert "中心" in audit.multi_device_reality_verdict_zh or "设备" in audit.multi_device_reality_verdict_zh

    def test_has_blocking_gaps(self):
        audit = build_clone_to_run_audit()
        assert len(audit.blocking_gaps_zh) >= 1, "Must identify at least one blocking gap"

    def test_has_already_working(self):
        audit = build_clone_to_run_audit()
        assert len(audit.already_working_zh) >= 3, "Must identify at least 3 working items"

    def test_verdict_is_not_clone_ready(self):
        # System is not yet fully clone-ready (Android APK needs manual build etc.)
        audit = build_clone_to_run_audit()
        assert audit.operability_verdict != OperabilityVerdict.CLONE_READY, (
            "System should not be fully clone-ready given Android dependency requirements"
        )

    def test_to_dict_serializes_correctly(self):
        audit = build_clone_to_run_audit()
        d = audit.to_dict()
        assert "operability_verdict" in d
        assert "checkpoints" in d
        assert "android_local_mode_verdict_zh" in d
        assert "multi_device_reality_verdict_zh" in d
        assert isinstance(d["checkpoints"], list)
        assert len(d["checkpoints"]) >= 5

    def test_checkpoint_to_dict_has_all_fields(self):
        audit = build_clone_to_run_audit()
        for cp in audit.checkpoints:
            d = cp.to_dict()
            assert "checkpoint_id" in d
            assert "passed" in d
            assert "evidence_zh" in d
            assert "blocking" in d
            assert "v2_anchors" in d
            assert isinstance(d["v2_anchors"], list)


# ---------------------------------------------------------------------------
# ThreeStateRuntimeAudit 测试
# ---------------------------------------------------------------------------


class TestThreeStateRuntimeAudit:
    def test_build_returns_audit(self):
        audit = build_three_state_runtime_audit()
        assert isinstance(audit, ThreeStateRuntimeAudit)

    def test_verdict_is_valid_enum(self):
        audit = build_three_state_runtime_audit()
        assert audit.verdict in list(ThreeStateSourceVerdict)

    def test_verdict_is_not_narrative_only(self):
        # The system has real code for tri_state_phase and participation tiers
        audit = build_three_state_runtime_audit()
        assert audit.verdict != ThreeStateSourceVerdict.NARRATIVE_ONLY, (
            "Three-state concepts should at least be partially in code"
        )

    def test_has_honest_assessment(self):
        audit = build_three_state_runtime_audit()
        assert audit.honest_assessment_zh, "Must provide an honest assessment in Chinese"
        # Should mention the two separate semantic lines
        assert "线路" in audit.honest_assessment_zh or "两条" in audit.honest_assessment_zh or "两个" in audit.honest_assessment_zh

    def test_has_operator_board_gap(self):
        audit = build_three_state_runtime_audit()
        assert audit.operator_board_gap_zh, "Must describe the operator board gap"

    def test_display_tri_state_assessment(self):
        audit = build_three_state_runtime_audit()
        assert audit.display_tri_state_sources_zh, "Must describe display tri-state sources"

    def test_android_participation_tri_state_assessed(self):
        audit = build_three_state_runtime_audit()
        # android_participation_tri_state_exists should be True since
        # android_network_participation module has 7 tiers
        assert audit.android_participation_tri_state_exists is True

    def test_unified_tri_state_api_not_yet_available(self):
        # A unified tri-state API (merging both semantic lines) does not yet exist
        audit = build_three_state_runtime_audit()
        assert audit.unified_tri_state_api_exists is False

    def test_to_dict_has_required_keys(self):
        audit = build_three_state_runtime_audit()
        d = audit.to_dict()
        required_keys = [
            "verdict",
            "display_tri_state_exists_in_code",
            "display_tri_state_sources_zh",
            "display_tri_state_panel_projected",
            "android_participation_tri_state_exists",
            "android_participation_tri_state_panel_projected",
            "unified_tri_state_api_exists",
            "honest_assessment_zh",
            "operator_board_gap_zh",
            "v2_anchors",
            "android_anchors",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# ClosureGovernancePropagationAudit 测试
# ---------------------------------------------------------------------------


class TestClosureGovernancePropagationAudit:
    def test_build_returns_audit(self):
        audit = build_closure_governance_propagation_audit()
        assert isinstance(audit, ClosureGovernancePropagationAudit)

    def test_propagation_tier_is_valid(self):
        audit = build_closure_governance_propagation_audit()
        assert audit.propagation_tier in list(ClosureGovernancePropagationTier)

    def test_is_not_routing_only(self):
        # PR 1142 + this PR should take it beyond routing_only
        audit = build_closure_governance_propagation_audit()
        assert audit.propagation_tier != ClosureGovernancePropagationTier.ROUTING_ONLY, (
            "After PR 1142 and this PR, propagation should be beyond routing_only"
        )

    def test_is_not_not_propagated(self):
        audit = build_closure_governance_propagation_audit()
        assert audit.propagation_tier != ClosureGovernancePropagationTier.NOT_PROPAGATED

    def test_closure_reflects_acceptance_verdict(self):
        # unified_result_ingress.is_fully_closed is controlled by acceptance gate
        audit = build_closure_governance_propagation_audit()
        assert audit.closure_reflects_acceptance_verdict is True, (
            "UnifiedResultIngress must block is_fully_closed when acceptance verdict is quarantine/reject"
        )

    def test_has_honest_assessment(self):
        audit = build_closure_governance_propagation_audit()
        assert audit.honest_assessment_zh
        # Should mention the progression through layers
        assert "传播" in audit.honest_assessment_zh or "路由" in audit.honest_assessment_zh

    def test_has_what_this_pr_fixes(self):
        audit = build_closure_governance_propagation_audit()
        assert audit.what_this_pr_fixes_zh
        assert "notify_with_android_context" in audit.what_this_pr_fixes_zh

    def test_has_what_still_needs_android(self):
        audit = build_closure_governance_propagation_audit()
        assert audit.what_still_needs_android_side_zh
        # Should mention Android-side requirements
        assert "Android" in audit.what_still_needs_android_side_zh

    def test_to_dict_has_required_keys(self):
        audit = build_closure_governance_propagation_audit()
        d = audit.to_dict()
        required_keys = [
            "propagation_tier",
            "android_truth_in_result_acceptance",
            "closure_reflects_acceptance_verdict",
            "operator_board_has_android_reasoning",
            "readiness_surface_consumes_android_truth",
            "honest_assessment_zh",
            "what_this_pr_fixes_zh",
            "what_still_needs_android_side_zh",
            "v2_anchors",
            "android_anchors",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# AndroidTruthInOperatorBoardAudit 测试
# ---------------------------------------------------------------------------


class TestAndroidTruthInOperatorBoardAudit:
    def test_build_returns_audit(self):
        audit = build_android_truth_operator_board_audit()
        assert isinstance(audit, AndroidTruthInOperatorBoardAudit)

    def test_board_reasoning_api_available(self):
        # This module itself provides the board reasoning API
        audit = build_android_truth_operator_board_audit()
        assert audit.board_reasoning_api_available is True

    def test_has_gap_description(self):
        audit = build_android_truth_operator_board_audit()
        assert audit.gap_before_this_pr_zh, "Must describe gap before this PR"
        assert "PR 1142" in audit.gap_before_this_pr_zh

    def test_has_fix_description(self):
        audit = build_android_truth_operator_board_audit()
        assert audit.fix_in_this_pr_zh
        assert "notify_with_android_context" in audit.fix_in_this_pr_zh

    def test_has_remaining_gap(self):
        audit = build_android_truth_operator_board_audit()
        assert audit.remaining_gap_zh, "Must honestly describe remaining gaps"

    def test_to_dict_has_required_keys(self):
        audit = build_android_truth_operator_board_audit()
        d = audit.to_dict()
        required_keys = [
            "panel_has_android_participation_verdict",
            "completion_ingress_has_android_context",
            "board_reasoning_api_available",
            "operator_route_can_read_android_truth",
            "gap_before_this_pr_zh",
            "fix_in_this_pr_zh",
            "remaining_gap_zh",
            "v2_anchors",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# get_board_reasoning_for_closure 测试
# ---------------------------------------------------------------------------


class TestGetBoardReasoningForClosure:
    def test_basic_accept_reasoning(self):
        result = get_board_reasoning_for_closure(
            task_id="task-123",
            android_participation_tier="dispatch_eligible",
            acceptance_verdict="accept",
            is_fully_closed=True,
            device_id="device-abc",
        )
        assert result["task_id"] == "task-123"
        assert result["android_participation_tier"] == "dispatch_eligible"
        assert result["acceptance_verdict"] == "accept"
        assert result["is_fully_closed"] is True
        assert result["device_id"] == "device-abc"
        assert "causal_explanation_zh" in result
        assert "闭环" in result["causal_explanation_zh"] or "完全闭环" in result["causal_explanation_zh"]

    def test_quarantine_reasoning(self):
        result = get_board_reasoning_for_closure(
            task_id="task-456",
            android_participation_tier="session_attached",
            acceptance_verdict="quarantine",
            is_fully_closed=False,
        )
        assert result["acceptance_verdict"] == "quarantine"
        assert result["is_fully_closed"] is False
        assert "quarantine" in result["causal_explanation_zh"]
        assert "is_fully_closed=False" in result["causal_explanation_zh"]

    def test_reject_reasoning(self):
        result = get_board_reasoning_for_closure(
            task_id="task-789",
            acceptance_verdict="reject",
            is_fully_closed=False,
        )
        assert "reject" in result["causal_explanation_zh"]
        assert result["android_participation_tier"] == "unknown"

    def test_accept_provisional_reasoning(self):
        result = get_board_reasoning_for_closure(
            task_id="task-provisional",
            android_participation_tier="capability_visible",
            acceptance_verdict="accept_provisional",
            is_fully_closed=False,
        )
        assert "accept_provisional" in result["causal_explanation_zh"]
        assert "warning" in result["causal_explanation_zh"].lower() or "provisional" in result["causal_explanation_zh"]

    def test_local_only_tier_reasoning(self):
        result = get_board_reasoning_for_closure(
            task_id="task-local",
            android_participation_tier="local_only",
            acceptance_verdict="accept",
            is_fully_closed=True,
        )
        assert "local_only" in result["causal_explanation_zh"]

    def test_unknown_tier_defaults_gracefully(self):
        result = get_board_reasoning_for_closure(task_id="task-unknown")
        assert result["android_participation_tier"] == "unknown"
        assert result["acceptance_verdict"] == "unknown"
        assert "causal_explanation_zh" in result

    def test_has_source_authority(self):
        result = get_board_reasoning_for_closure(task_id="task-src")
        assert "_source" in result
        assert "PR_NEXT_CONVERGENCE" in result["_source"]

    def test_has_generated_at(self):
        before = time.time()
        result = get_board_reasoning_for_closure(task_id="task-ts")
        after = time.time()
        assert before <= result["generated_at"] <= after

    def test_required_keys_present(self):
        result = get_board_reasoning_for_closure(task_id="task-keys")
        required = [
            "task_id",
            "android_participation_tier",
            "acceptance_verdict",
            "is_fully_closed",
            "device_id",
            "causal_explanation_zh",
            "generated_at",
            "_source",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# ConvergenceClosureAuditRecord 测试
# ---------------------------------------------------------------------------


class TestConvergenceClosureAuditRecord:
    def test_build_returns_record(self):
        record = build_convergence_closure_audit()
        assert isinstance(record, ConvergenceClosureAuditRecord)

    def test_all_sub_audits_populated(self):
        record = build_convergence_closure_audit()
        assert record.operability_audit is not None
        assert record.three_state_audit is not None
        assert record.closure_governance_audit is not None
        assert record.operator_board_audit is not None

    def test_authority_matches(self):
        record = build_convergence_closure_audit()
        assert record.authority == PR_NEXT_CONVERGENCE_CLOSURE_AUDIT_AUTHORITY

    def test_pr_title_present(self):
        record = build_convergence_closure_audit()
        assert record.pr_title == PR_NEXT_CONVERGENCE_PR_TITLE
        assert record.pr_title_en == PR_NEXT_CONVERGENCE_PR_TITLE_EN

    def test_what_is_already_working_not_empty(self):
        record = build_convergence_closure_audit()
        assert len(record.what_is_already_working_zh) >= 3

    def test_what_this_pr_fixes_not_empty(self):
        record = build_convergence_closure_audit()
        assert len(record.what_this_pr_fixes_zh) >= 3

    def test_what_still_needs_android_not_empty(self):
        record = build_convergence_closure_audit()
        assert len(record.what_still_needs_android_side_zh) >= 2

    def test_to_dict_serializes_all_fields(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()

        required_top_level_keys = [
            "authority",
            "contract_version",
            "pr_title",
            "pr_title_en",
            "convergence_anchor",
            "android_audited_ref",
            "generated_at",
            "operability_audit",
            "three_state_audit",
            "closure_governance_audit",
            "operator_board_audit",
            "what_is_already_working_zh",
            "what_this_pr_fixes_zh",
            "what_still_needs_android_side_zh",
            "probe_results",
        ]
        for key in required_top_level_keys:
            assert key in d, f"Missing top-level key: {key}"

    def test_sub_audits_serialized(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        assert d["operability_audit"] is not None
        assert d["three_state_audit"] is not None
        assert d["closure_governance_audit"] is not None
        assert d["operator_board_audit"] is not None

    def test_convergence_anchor_is_993p2(self):
        record = build_convergence_closure_audit()
        assert record.convergence_anchor == "993P2"

    def test_probe_results_present(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        probe_results = d.get("probe_results", {})
        assert isinstance(probe_results, dict)
        # Should have at least some probe results
        assert len(probe_results) > 0

    def test_probe_results_include_key_checks(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        probe_results = d.get("probe_results", {})
        # These probes must be present (they detect this PR's own changes)
        assert "board_reasoning_api" in probe_results
        assert "result_truth_acceptance_gate" in probe_results

    def test_this_module_detected_by_probes(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        probe_results = d.get("probe_results", {})
        # This module should be found by its own probe
        assert probe_results.get("board_reasoning_api") is True

    def test_acceptance_gate_detected(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        probe_results = d.get("probe_results", {})
        assert probe_results.get("result_truth_acceptance_gate") is True

    def test_result_ingress_detected(self):
        record = build_convergence_closure_audit()
        d = record.to_dict()
        probe_results = d.get("probe_results", {})
        assert probe_results.get("unified_result_ingress") is True


# ---------------------------------------------------------------------------
# 整体完整性测试（确保这个 PR 的修改在代码探针层面真实可检测）
# ---------------------------------------------------------------------------


class TestPrNextConvergenceCodeProbes:
    def test_completion_ingress_has_android_context(self):
        """Verify that canonical_completion_ingress has notify_with_android_context."""
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("completion_ingress_has_android_context") is True, (
            "canonical_completion_ingress must contain notify_with_android_context "
            "(this PR adds it)"
        )

    def test_panel_has_android_participation_verdict(self):
        """Verify that unified_panel_aggregation has android_participation_verdict field."""
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("panel_has_android_participation_verdict") is True, (
            "unified_panel_aggregation must contain android_participation_verdict "
            "(this PR adds it)"
        )

    def test_dispatch_consumes_participation_evidence(self):
        """Verify that source_dispatch_orchestrator consumes get_android_participation_evidence (PR 1142)."""
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("dispatch_consumes_participation_evidence") is True, (
            "source_dispatch_orchestrator must consume get_android_participation_evidence "
            "(added in PR 1142)"
        )

    def test_android_network_participation_has_7_tiers(self):
        """Verify that android_network_participation module defines distributed_participant tier."""
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("participation_has_7_tiers") is True

    def test_operator_surface_available(self):
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("operator_surface") is True

    def test_operational_readiness_surface_available(self):
        from core.pr_next_convergence_closure_audit import _collect_probes
        p = _collect_probes()
        assert p.get("operational_readiness_surface") is True
