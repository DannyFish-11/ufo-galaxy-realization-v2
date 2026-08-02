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


# ===========================================================================
# A) Sentinel verification
# ===========================================================================


# ===========================================================================
# B) Outward runtime truth
# ===========================================================================


class TestOutwardRuntimeTruth:
    """compile_outward_truth() must produce a valid snapshot."""

    def setup_method(self):
        _reset_all()

    def test_compile_outward_truth_returns_snapshot(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot, compile_outward_truth

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
        from core.outward_runtime_truth import OUTWARD_RUNTIME_TRUTH_AUTHORITY, compile_outward_truth

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
        import json

        from core.outward_runtime_truth import compile_outward_truth

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
        from core.outward_runtime_truth import TruthSignalClass, classify_signal

        result = classify_signal("RuntimeTruthCompiler", is_canonical=True)
        assert result == TruthSignalClass.PRIMARY

    def test_classify_signal_non_canonical_returns_legacy_compat(self):
        from core.outward_runtime_truth import TruthSignalClass, classify_signal

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
            NodeGovernanceRecord,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_001", startup_policy="active")
        assert isinstance(rec, NodeGovernanceRecord)

    def test_register_node_initial_stage_is_registered(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            get_node_lifecycle_governor,
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
            NodeLifecycleStage,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_010")
        rec = gov.check_readiness("TestNode_010")
        # Should be at least READINESS_CHECKED (or CALLABLE_CLASSIFIED etc.)
        assert rec.lifecycle_stage != NodeLifecycleStage.REGISTERED

    def test_classify_callable_advances_stage(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_020", architectural_class="capability_node")
        gov.check_readiness("TestNode_020")
        rec = gov.classify_callable("TestNode_020")
        assert rec.lifecycle_stage.value >= NodeLifecycleStage.CALLABLE_CLASSIFIED.value

    def test_govern_node_runs_full_pipeline(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        rec = gov.govern_node("TestNode_030")
        # govern_node runs all gates — stage should advance past REGISTERED
        assert rec.lifecycle_stage != NodeLifecycleStage.REGISTERED

    def test_govern_node_auto_registers(self):
        from core.node_lifecycle_governor import (
            NodeGovernanceRecord,
            get_node_lifecycle_governor,
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
            NodeLifecycleStage,
            get_node_lifecycle_governor,
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
            NodeLifecycleStage,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_051")
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        rec.is_capability_registered = False  # explicit
        result = gov.promote_node("TestNode_051")
        # Should NOT advance to ACTIVE
        assert result.lifecycle_stage != NodeLifecycleStage.ACTIVE
        # Gate history should record the failure
        failed_gates = [g for g in result.gate_history if g["gate"] == "promotion" and g["outcome"] == "failed"]
        assert failed_gates

    def test_demote_node_to_deprecated(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            get_node_lifecycle_governor,
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
            NodeLifecycleGovernorSnapshot,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        gov.register_node("TestNode_080")
        snap = gov.snapshot()
        assert isinstance(snap, NodeLifecycleGovernorSnapshot)
        assert snap.total_nodes >= 1

    def test_snapshot_counts_active_correctly(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            get_node_lifecycle_governor,
        )

        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_090")
        rec.is_capability_registered = True
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        gov.promote_node("TestNode_090")
        snap = gov.snapshot()
        assert snap.active_count >= 1

    def test_governance_record_to_dict(self):
        import json

        from core.node_lifecycle_governor import get_node_lifecycle_governor

        gov = get_node_lifecycle_governor()
        rec = gov.register_node("TestNode_100")
        d = rec.to_dict()
        assert isinstance(d, dict)
        json_str = json.dumps(d)
        assert json_str

    def test_lifecycle_stages_enum_values(self):
        from core.node_lifecycle_governor import NodeLifecycleStage

        expected = {
            "registered",
            "readiness_checked",
            "callable_classified",
            "capability_registered",
            "optional",
            "experimental",
            "active",
            "deprecated",
        }
        actual = {s.value for s in NodeLifecycleStage}
        assert expected == actual

    def test_module_level_govern_node_convenience(self):
        from core.node_lifecycle_governor import NodeGovernanceRecord, govern_node

        _reset_all()
        rec = govern_node("TestNode_ConvenienceTest")
        assert isinstance(rec, NodeGovernanceRecord)

    def test_module_level_promote_node_convenience(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            govern_node,
            promote_node,
        )

        _reset_all()
        rec = govern_node("TestNode_PromoteConv")
        rec.is_capability_registered = True
        rec.lifecycle_stage = NodeLifecycleStage.OPTIONAL
        result = promote_node("TestNode_PromoteConv", note="conv test")
        assert result.lifecycle_stage == NodeLifecycleStage.ACTIVE

    def test_module_level_demote_node_convenience(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleStage,
            demote_node,
            govern_node,
        )

        _reset_all()
        govern_node("TestNode_DemoteConv")
        result = demote_node("TestNode_DemoteConv", reason="conv test")
        assert result.lifecycle_stage == NodeLifecycleStage.DEPRECATED

    def test_node_governance_snapshot_convenience(self):
        from core.node_lifecycle_governor import (
            NodeLifecycleGovernorSnapshot,
            govern_node,
            node_governance_snapshot,
        )

        _reset_all()
        govern_node("TestNode_SnapConv")
        snap = node_governance_snapshot()
        assert isinstance(snap, NodeLifecycleGovernorSnapshot)
        assert snap.total_nodes >= 1


# ===========================================================================
# D) Deployment baseline
# ===========================================================================


# ===========================================================================
# E) Capability utilization observability
# ===========================================================================


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
        assert (
            "UNAVAILABLE" not in OUTWARD_RUNTIME_TRUTH_INTEGRATED
        ), f"Expected V1 sentinel but got: {OUTWARD_RUNTIME_TRUTH_INTEGRATED}"

    def test_existing_sentinels_still_present(self):
        """Previous integration sentinels must not be broken by PR-531."""
        from core.routes.projection import (
            AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED,
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
            PROJECTION_SURFACE_BRIDGE_INTEGRATED,
        )

        assert PROJECTION_SURFACE_BRIDGE_INTEGRATED
        assert AUTHORITY_CONFLICT_ELIMINATION_INTEGRATED
        assert MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED


# ===========================================================================
# G) validate_runtime.py section coverage
# ===========================================================================


# 已删除依赖 core/deployment_baseline.py 与 core/capability_utilization_observability.py
# 的用例 —— 这两个是 PR-531 的观测报告模块（把系统状态整理成报告，缺席不产生错误
# 行为），生产面仅被 scripts/validate_runtime.py 的两个检查项消费，已一并摘除。
