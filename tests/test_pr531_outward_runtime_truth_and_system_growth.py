#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr531_outward_runtime_truth_and_system_growth.py
============================================================
PR-531 — Unify Outward Runtime Truth and Govern System Growth.

Coverage domains
----------------
A) Sentinel verification — all PR-531 sentinel constants importable and correct.
B) Outward runtime truth — compile_outward_truth(), OutwardRuntimeTruthSnapshot,
   TruthSignalClass, source classification, ring-buffer recording.
C) Node lifecycle governor — registration, lifecycle gates, promotion pipeline,
   wild-growth detection, snapshot.
D) Deployment baseline — check_runtime_baseline(), environment tier mapping,
   per-requirement pass/fail, baseline_met assertion.
E) Capability utilization observability — record_capability_call(), record_failure(),
   get_utilization_report(), get_all_utilization_reports(), fire-and-forget safety.
F) Projection routes integration — OUTWARD_RUNTIME_TRUTH_INTEGRATED sentinel
   present in core.routes.projection.
G) validate_runtime.py section coverage — sections 11–14 callable without crash.

Design principles
-----------------
* All tests are CI-safe without live services.
* Singletons are reset between tests to avoid state leakage.
* Each domain has at least one success test and at least one isolation/failure test.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_all() -> None:
    """Reset all PR-531 singletons between tests."""
    try:
        from core.outward_runtime_truth import reset_outward_runtime_truth_runtime
        reset_outward_runtime_truth_runtime()
    except Exception:
        pass
    try:
        from core.node_lifecycle_governor import reset_node_lifecycle_governor
        reset_node_lifecycle_governor()
    except Exception:
        pass
    try:
        from core.deployment_baseline import reset_deployment_baseline_runtime
        reset_deployment_baseline_runtime()
    except Exception:
        pass
    try:
        from core.capability_utilization_observability import (
            reset_capability_utilization_observability,
        )
        reset_capability_utilization_observability()
    except Exception:
        pass


# ===========================================================================
# A) Sentinel verification
# ===========================================================================


class TestSentinels:
    """PR-531 sentinel constants must be importable and non-empty."""

    def test_outward_runtime_truth_authority_importable(self):
        from core.outward_runtime_truth import OUTWARD_RUNTIME_TRUTH_AUTHORITY
        assert OUTWARD_RUNTIME_TRUTH_AUTHORITY
        assert "PR531" in OUTWARD_RUNTIME_TRUTH_AUTHORITY

    def test_outward_runtime_truth_layer_position(self):
        from core.outward_runtime_truth import OUTWARD_RUNTIME_TRUTH_LAYER_POSITION
        assert OUTWARD_RUNTIME_TRUTH_LAYER_POSITION == 15

    def test_outward_truth_policy_sentinels_non_empty(self):
        from core.outward_runtime_truth import (
            NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY,
            NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY,
            OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY,
        )
        assert NO_SECONDARY_SOURCE_AS_PRIMARY_TRUTH_POLICY
        assert NO_PARALLEL_OUTWARD_ASSEMBLY_POLICY
        assert OUTWARD_SURFACE_MUST_PREFER_COMPILED_TRUTH_POLICY

    def test_node_lifecycle_governor_authority_importable(self):
        from core.node_lifecycle_governor import NODE_LIFECYCLE_GOVERNOR_AUTHORITY
        assert NODE_LIFECYCLE_GOVERNOR_AUTHORITY
        assert "PR531" in NODE_LIFECYCLE_GOVERNOR_AUTHORITY

    def test_node_lifecycle_governor_layer_position(self):
        from core.node_lifecycle_governor import NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION
        assert NODE_LIFECYCLE_GOVERNOR_LAYER_POSITION == 15

    def test_node_lifecycle_pipeline_sentinel_non_empty(self):
        from core.node_lifecycle_governor import NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED
        assert NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED
        assert "REGISTERED" in NODE_LIFECYCLE_GOVERNANCE_PIPELINE_DEFINED

    def test_node_lifecycle_policy_sentinels_non_empty(self):
        from core.node_lifecycle_governor import (
            NODE_MUST_PASS_LIFECYCLE_GATES_POLICY,
            NO_WILD_GROWTH_POLICY,
            PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY,
        )
        assert NODE_MUST_PASS_LIFECYCLE_GATES_POLICY
        assert NO_WILD_GROWTH_POLICY
        assert PROMOTION_REQUIRES_CAPABILITY_REGISTRATION_POLICY

    def test_deployment_baseline_authority_importable(self):
        from core.deployment_baseline import DEPLOYMENT_BASELINE_AUTHORITY
        assert DEPLOYMENT_BASELINE_AUTHORITY
        assert "PR531" in DEPLOYMENT_BASELINE_AUTHORITY

    def test_deployment_baseline_layer_position(self):
        from core.deployment_baseline import DEPLOYMENT_BASELINE_LAYER_POSITION
        assert DEPLOYMENT_BASELINE_LAYER_POSITION == 15

    def test_deployment_baseline_policy_sentinels_non_empty(self):
        from core.deployment_baseline import (
            CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY,
            ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY,
            DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED,
        )
        assert CORE_RUNTIME_MUST_BE_CHECKABLE_POLICY
        assert ENVIRONMENT_TIERS_MUST_MAP_TO_STARTUP_TIERS_POLICY
        assert DEPLOYMENT_BASELINE_CONVERGENCE_DEFINED

    def test_capability_utilization_authority_importable(self):
        from core.capability_utilization_observability import (
            CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY,
        )
        assert CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY
        assert "PR531" in CAPABILITY_UTILIZATION_OBSERVABILITY_AUTHORITY

    def test_capability_utilization_layer_position(self):
        from core.capability_utilization_observability import (
            CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION,
        )
        assert CAPABILITY_UTILIZATION_OBSERVABILITY_LAYER_POSITION == 15

    def test_capability_utilization_policy_sentinels_non_empty(self):
        from core.capability_utilization_observability import (
            OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY,
            UTILIZATION_DATA_IS_ADVISORY_POLICY,
            CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED,
        )
        assert OBSERVABILITY_DOES_NOT_BLOCK_DISPATCH_POLICY
        assert UTILIZATION_DATA_IS_ADVISORY_POLICY
        assert CAPABILITY_UTILIZATION_FOUNDATIONS_ESTABLISHED


# ===========================================================================
# B) Outward runtime truth
# ===========================================================================


class TestOutwardRuntimeTruth:
    """compile_outward_truth() must produce a valid snapshot."""

    def setup_method(self):
        _reset_all()

    def test_compile_outward_truth_returns_snapshot(self):
        from core.outward_runtime_truth import compile_outward_truth, OutwardRuntimeTruthSnapshot
        snapshot = compile_outward_truth()
        assert isinstance(snapshot, OutwardRuntimeTruthSnapshot)

    def test_snapshot_has_non_empty_id(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        assert snapshot.snapshot_id
        assert len(snapshot.snapshot_id) > 8

    def test_snapshot_compiled_at_is_positive(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        assert snapshot.compiled_at > 0

    def test_snapshot_has_authority(self):
        from core.outward_runtime_truth import compile_outward_truth, OUTWARD_RUNTIME_TRUTH_AUTHORITY
        snapshot = compile_outward_truth()
        assert snapshot.authority == OUTWARD_RUNTIME_TRUTH_AUTHORITY

    def test_snapshot_has_source_records(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        assert isinstance(snapshot.source_records, list)
        # At least some sources should have been queried (even if unavailable)
        assert len(snapshot.source_records) >= 1

    def test_snapshot_counts_are_non_negative(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        assert snapshot.primary_source_count >= 0
        assert snapshot.secondary_source_count >= 0
        assert snapshot.legacy_compat_source_count >= 0
        assert snapshot.unavailable_source_count >= 0

    def test_total_source_count_is_consistent(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        total = (
            snapshot.primary_source_count
            + snapshot.secondary_source_count
            + snapshot.legacy_compat_source_count
            + snapshot.unavailable_source_count
        )
        assert total == len(snapshot.source_records)

    def test_snapshot_to_dict_is_serialisable(self):
        from core.outward_runtime_truth import compile_outward_truth
        import json
        snapshot = compile_outward_truth()
        d = snapshot.to_dict()
        assert isinstance(d, dict)
        # Must be JSON-serialisable
        json_str = json.dumps(d)
        assert json_str

    def test_ring_buffer_records_snapshot(self):
        from core.outward_runtime_truth import (
            compile_outward_truth,
            get_outward_runtime_truth_runtime,
        )
        runtime = get_outward_runtime_truth_runtime()
        assert runtime.compile_count == 0
        compile_outward_truth()
        assert runtime.compile_count == 1
        assert runtime.latest_snapshot() is not None

    def test_ring_buffer_stores_multiple_snapshots(self):
        from core.outward_runtime_truth import (
            compile_outward_truth,
            get_outward_runtime_truth_runtime,
        )
        for _ in range(3):
            compile_outward_truth()
        runtime = get_outward_runtime_truth_runtime()
        assert runtime.compile_count == 3
        assert len(runtime.snapshot_list()) == 3

    def test_truth_signal_class_enum_values(self):
        from core.outward_runtime_truth import TruthSignalClass
        assert TruthSignalClass.PRIMARY.value == "primary"
        assert TruthSignalClass.SECONDARY.value == "secondary"
        assert TruthSignalClass.LEGACY_COMPAT.value == "legacy_compat"
        assert TruthSignalClass.UNAVAILABLE.value == "unavailable"

    def test_classify_signal_canonical_returns_primary(self):
        from core.outward_runtime_truth import classify_signal, TruthSignalClass
        result = classify_signal("RuntimeTruthCompiler", is_canonical=True)
        assert result == TruthSignalClass.PRIMARY

    def test_classify_signal_non_canonical_returns_legacy_compat(self):
        from core.outward_runtime_truth import classify_signal, TruthSignalClass
        result = classify_signal("legacy_fallback_view", is_canonical=False)
        assert result == TruthSignalClass.LEGACY_COMPAT

    def test_surfacing_notes_is_list(self):
        from core.outward_runtime_truth import compile_outward_truth
        snapshot = compile_outward_truth()
        assert isinstance(snapshot.surfacing_notes, list)

    def test_singleton_reset_clears_state(self):
        from core.outward_runtime_truth import (
            compile_outward_truth,
            get_outward_runtime_truth_runtime,
            reset_outward_runtime_truth_runtime,
        )
        compile_outward_truth()
        reset_outward_runtime_truth_runtime()
        runtime = get_outward_runtime_truth_runtime()
        assert runtime.compile_count == 0


# ===========================================================================
# C) Node lifecycle governor
# ===========================================================================


class TestNodeLifecycleGovernor:
    """Node lifecycle governor must govern nodes through the pipeline."""

    def setup_method(self):
        _reset_all()

    def test_singleton_is_accessible(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        assert gov is not None

    def test_singleton_is_same_instance(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov1 = get_node_lifecycle_governor()
        gov2 = get_node_lifecycle_governor()
        assert gov1 is gov2

    def test_register_node_returns_record(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeGovernanceRecord,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_001", startup_policy="active")
        assert isinstance(rec, NodeGovernanceRecord)

    def test_register_node_initial_stage_is_registered(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_002")
        assert rec.lifecycle_stage == NodeLifecycleStage.REGISTERED

    def test_register_node_idempotent(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        rec1 = gov.register_node("TestNode_003")
        rec2 = gov.register_node("TestNode_003")
        assert rec1 is rec2

    def test_register_node_stores_startup_policy(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_004", startup_policy="optional")
        assert rec.startup_policy == "optional"

    def test_check_readiness_advances_stage(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_010")
        rec = gov.check_readiness("TestNode_010")
        # Should be at least READINESS_CHECKED (or CALLABLE_CLASSIFIED etc.)
        assert rec.lifecycle_stage != NodeLifecycleStage.REGISTERED

    def test_classify_callable_advances_stage(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_020", architectural_class="capability_node")
        gov.check_readiness("TestNode_020")
        rec = gov.classify_callable("TestNode_020")
        assert rec.lifecycle_stage.value >= NodeLifecycleStage.CALLABLE_CLASSIFIED.value

    def test_govern_node_runs_full_pipeline(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.govern_node("TestNode_030")
        # govern_node runs all gates — stage should advance past REGISTERED
        assert rec.lifecycle_stage != NodeLifecycleStage.REGISTERED

    def test_govern_node_auto_registers(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeGovernanceRecord,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.govern_node("TestNode_031_auto")
        assert isinstance(rec, NodeGovernanceRecord)

    def test_govern_node_populates_gate_history(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        rec = gov.govern_node("TestNode_040")
        assert len(rec.gate_history) >= 1

    def test_promote_node_from_optional_to_active(self):
        """Promotion to ACTIVE requires capability_registered=True."""
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_050", startup_policy="active")
        # Manually set is_capability_registered to bypass live CapabilityRegistry
        rec.is_capability_registered = True
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        rec = gov.promote_node("TestNode_050", note="test promotion")
        assert rec.lifecycle_stage == NodeLifecycleStage.ACTIVE

    def test_promote_node_blocked_without_capability_registration(self):
        """Promotion to ACTIVE is blocked when capability not registered."""
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_051")
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        rec.is_capability_registered = False  # explicit
        result = gov.promote_node("TestNode_051")
        # Should NOT advance to ACTIVE
        assert result.lifecycle_stage != NodeLifecycleStage.ACTIVE
        # Gate history should record the failure
        failed_gates = [
            g for g in result.gate_history
            if g["gate"] == "promotion" and g["outcome"] == "failed"
        ]
        assert failed_gates

    def test_demote_node_to_deprecated(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_060")
        rec = gov.demote_node("TestNode_060", reason="end of life")
        assert rec.lifecycle_stage == NodeLifecycleStage.DEPRECATED
        assert any("end of life" in n for n in rec.promotion_notes)

    def test_get_record_returns_none_for_unknown(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        assert gov.get_record("NonExistentNode_XYZ") is None

    def test_list_records_returns_all(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_070")
        gov.register_node("TestNode_071")
        records = gov.list_records()
        names = {r.node_name for r in records}
        assert "TestNode_070" in names
        assert "TestNode_071" in names

    def test_snapshot_returns_governor_snapshot(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleGovernorSnapshot,
        )
        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_080")
        snap = gov.snapshot()
        assert isinstance(snap, NodeLifecycleGovernorSnapshot)
        assert snap.total_nodes >= 1

    def test_snapshot_counts_active_correctly(self):
        from core.node_lifecycle_governor import (
            get_node_lifecycle_governor,
            NodeLifecycleStage,
        )
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_090")
        rec.is_capability_registered = True
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        gov.promote_node("TestNode_090")
        snap = gov.snapshot()
        assert snap.active_count >= 1

    def test_governance_record_to_dict(self):
        from core.node_lifecycle_governor import get_node_lifecycle_governor
        import json
        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_100")
        d = rec.to_dict()
        assert isinstance(d, dict)
        json_str = json.dumps(d)
        assert json_str

    def test_lifecycle_stages_enum_values(self):
        from core.node_lifecycle_governor import NodeLifecycleStage
        expected = {
            "registered", "readiness_checked", "callable_classified",
            "capability_registered", "optional", "experimental",
            "active", "deprecated",
        }
        actual = {s.value for s in NodeLifecycleStage}
        assert expected == actual

    def test_module_level_govern_node_convenience(self):
        from core.node_lifecycle_governor import govern_node, NodeGovernanceRecord
        _reset_all()
        rec = govern_node("TestNode_ConvenienceTest")
        assert isinstance(rec, NodeGovernanceRecord)

    def test_module_level_promote_node_convenience(self):
        from core.node_lifecycle_governor import (
            govern_node,
            promote_node,
            NodeLifecycleStage,
        )
        _reset_all()
        rec = govern_node("TestNode_PromoteConv")
        rec.is_capability_registered = True
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        result = promote_node("TestNode_PromoteConv", note="conv test")
        assert result.lifecycle_stage == NodeLifecycleStage.ACTIVE

    def test_module_level_demote_node_convenience(self):
        from core.node_lifecycle_governor import (
            govern_node,
            demote_node,
            NodeLifecycleStage,
        )
        _reset_all()
        govern_node("TestNode_DemoteConv")
        result = demote_node("TestNode_DemoteConv", reason="conv test")
        assert result.lifecycle_stage == NodeLifecycleStage.DEPRECATED

    def test_node_governance_snapshot_convenience(self):
        from core.node_lifecycle_governor import (
            govern_node,
            node_governance_snapshot,
            NodeLifecycleGovernorSnapshot,
        )
        _reset_all()
        govern_node("TestNode_SnapConv")
        snap = node_governance_snapshot()
        assert isinstance(snap, NodeLifecycleGovernorSnapshot)
        assert snap.total_nodes >= 1


# ===========================================================================
# D) Deployment baseline
# ===========================================================================


class TestDeploymentBaseline:
    """Deployment baseline must be checkable in code."""

    def setup_method(self):
        _reset_all()

    def test_deployment_environment_tiers_defined(self):
        from core.deployment_baseline import DeploymentEnvironment
        assert DeploymentEnvironment.CORE_RUNTIME
        assert DeploymentEnvironment.STANDARD_DEV
        assert DeploymentEnvironment.FULL_PRODUCTION

    def test_deployment_environment_values(self):
        from core.deployment_baseline import DeploymentEnvironment
        assert DeploymentEnvironment.CORE_RUNTIME.value == "core_runtime"
        assert DeploymentEnvironment.STANDARD_DEV.value == "standard_dev"
        assert DeploymentEnvironment.FULL_PRODUCTION.value == "full_production"

    def test_check_runtime_baseline_returns_report(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
            DeploymentBaselineReport,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        assert isinstance(report, DeploymentBaselineReport)

    def test_core_runtime_baseline_met(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        assert report.baseline_met, (
            f"CORE_RUNTIME baseline_met=False; "
            f"failed checks: {report.summary_notes}"
        )

    def test_standard_dev_baseline_met(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
        )
        report = check_runtime_baseline(DeploymentEnvironment.STANDARD_DEV)
        assert report.baseline_met, (
            f"STANDARD_DEV baseline_met=False; "
            f"failed checks: {report.summary_notes}"
        )

    def test_report_has_requirements(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        assert len(report.requirements) >= 1

    def test_report_passed_count_matches_requirements(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
            BaselineCheckStatus,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        actual_passed = sum(
            1 for r in report.requirements if r.status == BaselineCheckStatus.PASSED
        )
        assert actual_passed == report.passed_count

    def test_report_failed_count_matches_requirements(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
            BaselineCheckStatus,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        actual_failed = sum(
            1 for r in report.requirements if r.status == BaselineCheckStatus.FAILED
        )
        assert actual_failed == report.failed_count

    def test_report_to_dict_serialisable(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
        )
        import json
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        d = report.to_dict()
        json_str = json.dumps(d)
        assert json_str

    def test_runtime_records_report(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            get_deployment_baseline_runtime,
            DeploymentEnvironment,
        )
        check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        rt = get_deployment_baseline_runtime()
        latest = rt.latest_report(DeploymentEnvironment.CORE_RUNTIME)
        assert latest is not None

    def test_multiple_reports_accumulate(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            get_deployment_baseline_runtime,
            DeploymentEnvironment,
        )
        check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        check_runtime_baseline(DeploymentEnvironment.STANDARD_DEV)
        rt = get_deployment_baseline_runtime()
        assert len(rt.all_reports()) >= 2

    def test_baseline_check_status_enum(self):
        from core.deployment_baseline import BaselineCheckStatus
        assert BaselineCheckStatus.PASSED.value == "passed"
        assert BaselineCheckStatus.FAILED.value == "failed"
        assert BaselineCheckStatus.WARN.value == "warn"
        assert BaselineCheckStatus.SKIPPED.value == "skipped"

    def test_startup_tier_model_check_passes(self):
        """startup_tier_model_importable check should always pass in this repo."""
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
            BaselineCheckStatus,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        tier_check = next(
            (r for r in report.requirements if r.check_name == "startup_tier_model_importable"),
            None,
        )
        assert tier_check is not None
        assert tier_check.status == BaselineCheckStatus.PASSED, tier_check.detail

    def test_node_dependencies_json_check_passes(self):
        from core.deployment_baseline import (
            check_runtime_baseline,
            DeploymentEnvironment,
            BaselineCheckStatus,
        )
        report = check_runtime_baseline(DeploymentEnvironment.CORE_RUNTIME)
        ndj_check = next(
            (r for r in report.requirements if r.check_name == "node_dependencies_json_valid"),
            None,
        )
        assert ndj_check is not None
        assert ndj_check.status == BaselineCheckStatus.PASSED, ndj_check.detail


# ===========================================================================
# E) Capability utilization observability
# ===========================================================================


class TestCapabilityUtilizationObservability:
    """Capability utilization observability must record and report correctly."""

    def setup_method(self):
        _reset_all()

    def test_singleton_is_accessible(self):
        from core.capability_utilization_observability import (
            get_capability_utilization_observability,
        )
        obs = get_capability_utilization_observability()
        assert obs is not None

    def test_singleton_is_same_instance(self):
        from core.capability_utilization_observability import (
            get_capability_utilization_observability,
        )
        obs1 = get_capability_utilization_observability()
        obs2 = get_capability_utilization_observability()
        assert obs1 is obs2

    def test_record_capability_call_does_not_raise(self):
        from core.capability_utilization_observability import record_capability_call
        record_capability_call("test::tool::action", caller="TestSuite", success=True)

    def test_record_failure_does_not_raise(self):
        from core.capability_utilization_observability import record_failure
        record_failure(
            "test::tool::action",
            caller="TestSuite",
            failure_domain="NODE_TIMEOUT",
        )

    def test_get_utilization_report_returns_none_for_unrecorded(self):
        from core.capability_utilization_observability import get_utilization_report
        report = get_utilization_report("nonexistent::tool")
        assert report is None

    def test_get_utilization_report_after_call(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_utilization_report,
            UtilizationReport,
        )
        record_capability_call("node::tool::A", caller="X", success=True, latency_ms=10.0)
        report = get_utilization_report("node::tool::A")
        assert isinstance(report, UtilizationReport)
        assert report.total_calls == 1
        assert report.success_count == 1
        assert report.failure_count == 0

    def test_success_rate_after_all_successes(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_utilization_report,
        )
        for _ in range(3):
            record_capability_call("node::tool::B", success=True)
        report = get_utilization_report("node::tool::B")
        assert report.success_rate == 1.0
        assert report.failure_rate == 0.0

    def test_success_rate_after_mixed_calls(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            record_failure,
            get_utilization_report,
        )
        record_capability_call("node::tool::C", success=True)
        record_capability_call("node::tool::C", success=True)
        record_failure("node::tool::C", failure_domain="TIMEOUT")
        report = get_utilization_report("node::tool::C")
        assert report.total_calls == 3
        assert report.failure_count == 1
        assert abs(report.success_rate - 2 / 3) < 0.001

    def test_failure_domains_tracked(self):
        from core.capability_utilization_observability import (
            record_failure,
            get_utilization_report,
        )
        record_failure("node::tool::D", failure_domain="NODE_UNAVAILABLE")
        record_failure("node::tool::D", failure_domain="NODE_UNAVAILABLE")
        record_failure("node::tool::D", failure_domain="CAPABILITY_MISSING")
        report = get_utilization_report("node::tool::D")
        assert report.failure_domains.get("NODE_UNAVAILABLE") == 2
        assert report.failure_domains.get("CAPABILITY_MISSING") == 1

    def test_average_latency_calculation(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_utilization_report,
        )
        record_capability_call("node::tool::E", success=True, latency_ms=10.0)
        record_capability_call("node::tool::E", success=True, latency_ms=20.0)
        report = get_utilization_report("node::tool::E")
        assert abs(report.average_latency_ms - 15.0) < 0.01

    def test_first_and_last_call_at_tracked(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_utilization_report,
        )
        record_capability_call("node::tool::F", success=True)
        time.sleep(0.01)
        record_capability_call("node::tool::F", success=True)
        report = get_utilization_report("node::tool::F")
        assert report.first_call_at is not None
        assert report.last_call_at is not None
        assert report.last_call_at >= report.first_call_at

    def test_get_all_utilization_reports_returns_summary(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_all_utilization_reports,
            UtilizationSummary,
        )
        record_capability_call("tool::alpha", success=True)
        record_capability_call("tool::beta", success=False, failure_domain="ERR")
        summary = get_all_utilization_reports()
        assert isinstance(summary, UtilizationSummary)
        assert summary.total_tracked_capabilities >= 2

    def test_summary_most_called_is_set(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_all_utilization_reports,
        )
        for _ in range(5):
            record_capability_call("tool::popular", success=True)
        record_capability_call("tool::rare", success=True)
        summary = get_all_utilization_reports()
        assert summary.most_called == "tool::popular"

    def test_summary_most_failing_is_set(self):
        from core.capability_utilization_observability import (
            record_failure,
            get_all_utilization_reports,
        )
        for _ in range(3):
            record_failure("tool::flaky", failure_domain="ERR")
        record_failure("tool::ok", failure_domain="ERR")
        summary = get_all_utilization_reports()
        assert summary.most_failing == "tool::flaky"

    def test_summary_to_dict_serialisable(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_all_utilization_reports,
        )
        import json
        record_capability_call("tool::test", success=True)
        summary = get_all_utilization_reports()
        d = summary.to_dict()
        json_str = json.dumps(d)
        assert json_str

    def test_utilization_report_to_dict(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_utilization_report,
        )
        import json
        record_capability_call("tool::dict_test", success=True, latency_ms=5.0)
        report = get_utilization_report("tool::dict_test")
        d = report.to_dict()
        assert d["tool_name"] == "tool::dict_test"
        json.dumps(d)

    def test_ring_buffer_overflow_does_not_raise(self):
        from core.capability_utilization_observability import (
            record_capability_call,
            get_capability_utilization_observability,
        )
        obs = get_capability_utilization_observability()
        # Write more records than the ring buffer can hold
        for i in range(2000):
            record_capability_call(f"tool::overflow_{i % 10}", success=True)
        # Should not raise; ring buffer silently drops oldest entries
        records = obs.list_records()
        assert len(records) <= 1024

    def test_observability_does_not_block_on_import_error(self):
        """record_capability_call() must not raise even if internal error occurs."""
        from core.capability_utilization_observability import record_capability_call
        # Should be safe even with unusual tool_name values
        record_capability_call("")
        record_capability_call("a" * 1000)

    def test_empty_summary_when_no_records(self):
        from core.capability_utilization_observability import get_all_utilization_reports
        summary = get_all_utilization_reports()
        assert summary.total_tracked_capabilities == 0
        assert summary.total_calls_recorded == 0


# ===========================================================================
# F) Projection routes integration
# ===========================================================================


class TestProjectionRoutesIntegration:
    """OUTWARD_RUNTIME_TRUTH_INTEGRATED sentinel must be present in projection routes."""

    def test_outward_runtime_truth_integrated_sentinel_present(self):
        from core.routes.projection import OUTWARD_RUNTIME_TRUTH_INTEGRATED
        assert OUTWARD_RUNTIME_TRUTH_INTEGRATED
        assert "OUTWARD_RUNTIME_TRUTH_INTEGRATED" in OUTWARD_RUNTIME_TRUTH_INTEGRATED

    def test_outward_runtime_truth_integrated_is_v1_not_unavailable(self):
        from core.routes.projection import OUTWARD_RUNTIME_TRUTH_INTEGRATED
        # The sentinel should confirm V1 integration, not unavailability
        assert "UNAVAILABLE" not in OUTWARD_RUNTIME_TRUTH_INTEGRATED, (
            f"Expected V1 sentinel but got: {OUTWARD_RUNTIME_TRUTH_INTEGRATED}"
        )

    def test_existing_sentinels_still_present(self):
        """Previous integration sentinels must not be broken by PR-531."""
        from core.routes.projection import (
            PROJECTION_SURFACE_BRIDGE_INTEGRATED,
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
        )
        assert PROJECTION_SURFACE_BRIDGE_INTEGRATED
        assert AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED
        assert MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED


# ===========================================================================
# G) validate_runtime.py section coverage
# ===========================================================================


class TestValidateRuntimeSections:
    """New validate_runtime.py sections 11–14 must run without crashing."""

    def setup_method(self):
        _reset_all()

    def test_check_outward_runtime_truth_callable(self):
        import importlib.util as ilu
        import sys as _sys

        vr_path = PROJECT_ROOT / "scripts" / "validate_runtime.py"
        spec = ilu.spec_from_file_location("_vr_ort", vr_path)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "check_outward_runtime_truth")
        # Should not raise
        mod.check_outward_runtime_truth()

    def test_check_node_lifecycle_governor_callable(self):
        import importlib.util as ilu

        vr_path = PROJECT_ROOT / "scripts" / "validate_runtime.py"
        spec = ilu.spec_from_file_location("_vr_nlg", vr_path)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "check_node_lifecycle_governor")
        mod.check_node_lifecycle_governor()

    def test_check_deployment_baseline_callable(self):
        import importlib.util as ilu

        vr_path = PROJECT_ROOT / "scripts" / "validate_runtime.py"
        spec = ilu.spec_from_file_location("_vr_db", vr_path)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "check_deployment_baseline")
        mod.check_deployment_baseline()

    def test_check_capability_utilization_callable(self):
        import importlib.util as ilu

        vr_path = PROJECT_ROOT / "scripts" / "validate_runtime.py"
        spec = ilu.spec_from_file_location("_vr_cu", vr_path)
        mod = ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        assert hasattr(mod, "check_capability_utilization_observability")
        mod.check_capability_utilization_observability()

    def test_validate_runtime_main_includes_new_checks(self):
        """The main() call list in validate_runtime.py must include all 4 new checks."""
        import ast

        vr_path = PROJECT_ROOT / "scripts" / "validate_runtime.py"
        source = vr_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        # Find main() function and collect all call names inside it
        call_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "main":
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call):
                        if isinstance(subnode.func, ast.Name):
                            call_names.add(subnode.func.id)

        for expected in [
            "check_outward_runtime_truth",
            "check_node_lifecycle_governor",
            "check_deployment_baseline",
            "check_capability_utilization_observability",
        ]:
            assert expected in call_names, (
                f"{expected} not found in validate_runtime.py main() call list"
            )
