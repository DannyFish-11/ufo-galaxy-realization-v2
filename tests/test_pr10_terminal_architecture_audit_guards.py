#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr10_terminal_architecture_audit_guards.py
=========================================================
PR-10: Terminal Architecture Audit Guards — regression prevention tests.

This test suite validates that the five terminal architecture audit guards
correctly detect key architectural regressions in the validated final
integrated center-distributed architecture.

Coverage
--------
A  — Module sentinels: importable, non-empty, contain expected keywords.
B  — TerminalGuardFinding: construction, to_dict() shape.
C  — TerminalGuardReport: construction, add/extend, recompute, to_dict().

D  — Guard 1 (V4 scope regression):
     D1  clean state passes (no regression detected).
     D2  snapshot with is_per_request_gate=True is an error.
     D3  snapshot with is_per_request_gate=False is OK.
     D4  V4_IS_NOT_PER_REQUEST_GATE_POLICY sentinel intact in live module.
     D5  UNIFIED_ORCHESTRATION_SPINE_AUTHORITY sentinel intact in live module.
     D6  Per-request hot-path modules (command_router, openclawd) do NOT
         import unified_orchestration_spine.

E  — Guard 2 (V6 hot-path regression):
     E1  clean state passes.
     E2  snapshot with is_per_request_gate=True for startup_release_integrity
         is an error.
     E3  V6_IS_NOT_PER_REQUEST_GATE sentinel intact in canonical_layer_model.
     E4  Per-request hot-path modules do NOT import V6 boundary symbols.

F  — Guard 3 (L1/L2/L3 router detachment):
     F1  clean state passes.
     F2  snapshot with is_shadow_stack=True for router_cognitive_authority
         is an error.
     F3  UnifiedLLMRouter has _l1/_l2/_l3 authority attributes.
     F4  UnifiedLLMRouter has _get_l1/_l2/_l3 helper methods.
     F5  L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK sentinel intact.

G  — Guard 4 (completion truth bypass):
     G1  clean state passes.
     G2  snapshot with is_optional_signaling=True for completion_truth_backbone
         is an error.
     G3  TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY sentinel intact.
     G4  run_task_result_truth_chain callable present.
     G5  core.canonical_completion_ingress importable.
     G6  COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL sentinel intact.

H  — Guard 5 (architecture declaration coherence):
     H1  clean state passes.
     H2  all five canonical layer keys present.
     H3  all four NOT-policy sentinels present.
     H4  run_layer_model_invariants() returns overall_consistent=True.
     H5  check_layer_model_consistent with bad snapshot surfaces as error.

I  — run_terminal_audit_guards (aggregate):
     I1  runs all five guards; guards_run has five entries.
     I2  overall_passed=True on a clean system.
     I3  overall_passed=False when any guard gets a regression snapshot.
     I4  policy_sentinels list has five entries.
     I5  to_dict() contains all expected top-level keys.
     I6  generated_at is a recent positive timestamp.

J  — Integration with canonical_layer_model:
     J1  run_terminal_audit_guards() coherence guard uses canonical_layer_model.
     J2  canonical_layer_model.run_layer_model_invariants() passes on its own.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Availability guards
# ---------------------------------------------------------------------------

try:
    from core.terminal_architecture_audit_guards import (
        ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY,
        COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY,
        L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY,
        TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY,
        TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL,
        TerminalGuardFinding,
        TerminalGuardReport,
        V4_SCOPE_REGRESSION_GUARD_POLICY,
        V6_HOT_PATH_REGRESSION_GUARD_POLICY,
        check_architecture_declaration_coherence,
        check_completion_truth_bypass,
        check_l1_l2_l3_router_detachment,
        check_v4_scope_regression,
        check_v6_hot_path_regression,
        run_terminal_audit_guards,
    )
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_skip = pytest.mark.skipif(not _MODULE_AVAILABLE,
                           reason="core.terminal_architecture_audit_guards not available")


# ===========================================================================
# A — Module sentinels
# ===========================================================================


@_skip
class TestModuleSentinels:
    def test_authority_sentinel_present(self):
        assert isinstance(TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY, str)
        assert TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY.strip()

    def test_pr10_sentinel_present(self):
        assert isinstance(TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL, str)
        assert TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL.strip()

    def test_v4_guard_policy_present(self):
        assert isinstance(V4_SCOPE_REGRESSION_GUARD_POLICY, str)
        assert V4_SCOPE_REGRESSION_GUARD_POLICY.strip()
        assert "V4" in V4_SCOPE_REGRESSION_GUARD_POLICY

    def test_v6_guard_policy_present(self):
        assert isinstance(V6_HOT_PATH_REGRESSION_GUARD_POLICY, str)
        assert V6_HOT_PATH_REGRESSION_GUARD_POLICY.strip()
        assert "V6" in V6_HOT_PATH_REGRESSION_GUARD_POLICY

    def test_l123_guard_policy_present(self):
        assert isinstance(L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY, str)
        assert L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY.strip()
        assert "L1" in L1_L2_L3_ROUTER_DETACHMENT_REGRESSION_GUARD_POLICY

    def test_completion_guard_policy_present(self):
        assert isinstance(COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY, str)
        assert COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY.strip()
        assert "truth" in COMPLETION_TRUTH_BYPASS_REGRESSION_GUARD_POLICY.lower()

    def test_coherence_guard_policy_present(self):
        assert isinstance(ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY, str)
        assert ARCHITECTURE_DECLARATION_COHERENCE_GUARD_POLICY.strip()

    def test_authority_sentinel_contains_pr10(self):
        assert "PR10" in TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY or \
               "PR-10" in TERMINAL_ARCHITECTURE_AUDIT_GUARDS_AUTHORITY

    def test_pr10_sentinel_contains_pr10(self):
        assert "PR-10" in TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL or \
               "PR10" in TERMINAL_ARCHITECTURE_AUDIT_GUARDS_PR10_SENTINEL


# ===========================================================================
# B — TerminalGuardFinding
# ===========================================================================


@_skip
class TestTerminalGuardFinding:
    def test_construction(self):
        f = TerminalGuardFinding(
            guard="TEST_GUARD",
            severity="error",
            message="Something went wrong.",
            detail={"key": "value"},
        )
        assert f.guard == "TEST_GUARD"
        assert f.severity == "error"
        assert f.message == "Something went wrong."
        assert f.detail == {"key": "value"}

    def test_to_dict_shape(self):
        f = TerminalGuardFinding(
            guard="TEST_GUARD",
            severity="info",
            message="All good.",
        )
        d = f.to_dict()
        assert set(d.keys()) == {"guard", "severity", "message", "detail"}

    def test_to_dict_values(self):
        f = TerminalGuardFinding(
            guard="G1",
            severity="warning",
            message="Hmm.",
            detail={"x": 1},
        )
        d = f.to_dict()
        assert d["guard"] == "G1"
        assert d["severity"] == "warning"
        assert d["detail"] == {"x": 1}

    def test_default_detail_is_empty_dict(self):
        f = TerminalGuardFinding(guard="G", severity="info", message="ok")
        assert f.detail == {}


# ===========================================================================
# C — TerminalGuardReport
# ===========================================================================


@_skip
class TestTerminalGuardReport:
    def test_construction_defaults(self):
        r = TerminalGuardReport()
        assert r.overall_passed is True
        assert r.error_count == 0
        assert r.warning_count == 0
        assert r.findings == []
        assert r.guards_run == []

    def test_add_error_recomputes(self):
        r = TerminalGuardReport()
        r.add(TerminalGuardFinding("G", "error", "bad"))
        assert r.error_count == 1
        assert r.overall_passed is False

    def test_add_warning_does_not_fail(self):
        r = TerminalGuardReport()
        r.add(TerminalGuardFinding("G", "warning", "hmm"))
        assert r.warning_count == 1
        assert r.overall_passed is True

    def test_extend_multiple(self):
        r = TerminalGuardReport()
        r.extend([
            TerminalGuardFinding("G", "error", "e1"),
            TerminalGuardFinding("G", "error", "e2"),
        ])
        assert r.error_count == 2
        assert r.overall_passed is False

    def test_to_dict_keys(self):
        r = TerminalGuardReport()
        d = r.to_dict()
        expected = {
            "overall_passed", "error_count", "warning_count",
            "guards_run", "findings", "generated_at", "policy_sentinels",
        }
        assert expected.issubset(set(d.keys()))

    def test_to_dict_findings_serialised(self):
        r = TerminalGuardReport()
        r.add(TerminalGuardFinding("G", "info", "ok"))
        d = r.to_dict()
        assert isinstance(d["findings"], list)
        assert len(d["findings"]) == 1
        assert d["findings"][0]["severity"] == "info"

    def test_generated_at_recent(self):
        before = time.time()
        r = TerminalGuardReport()
        after = time.time()
        assert before <= r.generated_at <= after


# ===========================================================================
# D — Guard 1: V4 scope regression
# ===========================================================================


@_skip
class TestV4ScopeRegressionGuard:
    def test_d1_clean_state_passes(self):
        """On a clean system, the guard should produce no errors."""
        findings = check_v4_scope_regression()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected V4 scope regression errors: {errors}"

    def test_d2_snapshot_per_request_gate_true_is_error(self):
        """Snapshot declaring V4 as per-request gate must produce an error."""
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": True,
        }
        findings = check_v4_scope_regression(snapshot=snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error for V4 is_per_request_gate=True"
        assert any("V4_IS_NOT_PER_REQUEST_GATE" in str(f.detail) or
                   "per_request_gate" in str(f.detail).lower() or
                   "per-request" in f.message.lower()
                   for f in errors)

    def test_d3_snapshot_per_request_gate_false_is_ok(self):
        """Snapshot declaring V4 as NOT a per-request gate must not produce errors
        for that specific snapshot check."""
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": False,
        }
        findings = check_v4_scope_regression(snapshot=snapshot)
        # No error specifically about this snapshot key
        snapshot_errors = [f for f in findings
                           if f.severity == "error"
                           and "is_per_request_gate" in str(f.detail)]
        assert not snapshot_errors

    def test_d4_v4_not_per_request_policy_intact(self):
        """V4_IS_NOT_PER_REQUEST_GATE_POLICY must be present in live module."""
        try:
            from core.unified_orchestration_spine import V4_IS_NOT_PER_REQUEST_GATE_POLICY
        except ImportError:
            pytest.skip("core.unified_orchestration_spine not available")
        assert isinstance(V4_IS_NOT_PER_REQUEST_GATE_POLICY, str)
        assert V4_IS_NOT_PER_REQUEST_GATE_POLICY.strip()
        assert "NOT" in V4_IS_NOT_PER_REQUEST_GATE_POLICY

    def test_d5_unified_spine_authority_intact(self):
        """UNIFIED_ORCHESTRATION_SPINE_AUTHORITY must be present."""
        try:
            from core.unified_orchestration_spine import UNIFIED_ORCHESTRATION_SPINE_AUTHORITY
        except ImportError:
            pytest.skip("core.unified_orchestration_spine not available")
        assert isinstance(UNIFIED_ORCHESTRATION_SPINE_AUTHORITY, str)
        assert UNIFIED_ORCHESTRATION_SPINE_AUTHORITY.strip()

    def test_d6_command_router_does_not_import_v4(self):
        """core.command_router must NOT import unified_orchestration_spine."""
        source_path = PROJECT_ROOT / "core" / "command_router.py"
        if not source_path.exists():
            pytest.skip("core/command_router.py not found")
        source = source_path.read_text(encoding="utf-8")
        assert "unified_orchestration_spine" not in source, (
            "core/command_router.py imports unified_orchestration_spine — "
            "V4 has been inserted into the per-request hot path (regression)."
        )

    def test_d7_openclawd_does_not_import_v4(self):
        """core.openclawd must NOT import unified_orchestration_spine."""
        source_path = PROJECT_ROOT / "core" / "openclawd.py"
        if not source_path.exists():
            pytest.skip("core/openclawd.py not found")
        source = source_path.read_text(encoding="utf-8")
        assert "unified_orchestration_spine" not in source, (
            "core/openclawd.py imports unified_orchestration_spine — "
            "V4 has been inserted into the per-request hot path (regression)."
        )

    def test_d_guard_returns_list(self):
        findings = check_v4_scope_regression()
        assert isinstance(findings, list)
        assert all(isinstance(f, TerminalGuardFinding) for f in findings)


# ===========================================================================
# E — Guard 2: V6 hot-path regression
# ===========================================================================


@_skip
class TestV6HotPathRegressionGuard:
    def test_e1_clean_state_passes(self):
        findings = check_v6_hot_path_regression()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected V6 hot-path regression errors: {errors}"

    def test_e2_snapshot_startup_integrity_per_request_gate_true_is_error(self):
        snapshot = {
            "layer_key": "startup_release_integrity",
            "is_per_request_gate": True,
        }
        findings = check_v6_hot_path_regression(snapshot=snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error for V6 is_per_request_gate=True"
        assert any("V6" in f.guard or "hot" in f.message.lower() or
                   "per-request" in f.message.lower()
                   for f in errors)

    def test_e3_v6_not_per_request_gate_sentinel_intact(self):
        try:
            from core.canonical_layer_model import V6_IS_NOT_PER_REQUEST_GATE
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        assert isinstance(V6_IS_NOT_PER_REQUEST_GATE, str)
        assert V6_IS_NOT_PER_REQUEST_GATE.strip()
        assert "NOT" in V6_IS_NOT_PER_REQUEST_GATE

    def test_e4_command_router_does_not_import_v6(self):
        source_path = PROJECT_ROOT / "core" / "command_router.py"
        if not source_path.exists():
            pytest.skip("core/command_router.py not found")
        source = source_path.read_text(encoding="utf-8")
        for symbol in ["assert_center_authority_intact", "evaluate_center_authority_boundary"]:
            assert symbol not in source, (
                f"core/command_router.py references '{symbol}' — "
                "V6 boundary inserted into per-request hot path (regression)."
            )

    def test_e5_openclawd_does_not_import_v6(self):
        source_path = PROJECT_ROOT / "core" / "openclawd.py"
        if not source_path.exists():
            pytest.skip("core/openclawd.py not found")
        source = source_path.read_text(encoding="utf-8")
        for symbol in ["assert_center_authority_intact", "evaluate_center_authority_boundary"]:
            assert symbol not in source, (
                f"core/openclawd.py references '{symbol}' — "
                "V6 boundary inserted into per-request hot path (regression)."
            )

    def test_e_guard_returns_list(self):
        findings = check_v6_hot_path_regression()
        assert isinstance(findings, list)
        assert all(isinstance(f, TerminalGuardFinding) for f in findings)


# ===========================================================================
# F — Guard 3: L1/L2/L3 router detachment
# ===========================================================================


@_skip
class TestL1L2L3RouterDetachmentGuard:
    def test_f1_clean_state_passes(self):
        """On a clean system, the guard should produce no errors."""
        findings = check_l1_l2_l3_router_detachment()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected L1/L2/L3 detachment errors: {errors}"

    def test_f2_snapshot_is_shadow_stack_true_is_error(self):
        """Snapshot declaring L1/L2/L3 as shadow_stack must produce an error."""
        snapshot = {
            "layer_key": "router_cognitive_authority",
            "is_shadow_stack": True,
        }
        findings = check_l1_l2_l3_router_detachment(snapshot=snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error for L1/L2/L3 is_shadow_stack=True"
        assert any("shadow" in f.message.lower() or "L1" in f.guard
                   for f in errors)

    def test_f3_unified_llm_router_source_has_authority_attributes(self):
        """core/unified/llm_router.py source must reference L1/L2/L3 authority attrs."""
        source_path = PROJECT_ROOT / "core" / "unified" / "llm_router.py"
        if not source_path.exists():
            pytest.skip("core/unified/llm_router.py not found")
        source = source_path.read_text(encoding="utf-8")
        for attr in ["_l1_authority", "_l2_authority", "_l3_authority"]:
            assert attr in source, (
                f"UnifiedLLMRouter source is missing '{attr}' — "
                "L1/L2/L3 cognitive authority detached (regression)."
            )

    def test_f4_unified_llm_router_source_has_helper_methods(self):
        """core/unified/llm_router.py source must define L1/L2/L3 helpers."""
        source_path = PROJECT_ROOT / "core" / "unified" / "llm_router.py"
        if not source_path.exists():
            pytest.skip("core/unified/llm_router.py not found")
        source = source_path.read_text(encoding="utf-8")
        for method in ["_get_l1_route_authority", "_get_l2_supply_authority",
                       "_get_l3_context_authority"]:
            assert method in source, (
                f"UnifiedLLMRouter source does not define '{method}' — "
                "L1/L2/L3 authority helper removed (regression)."
            )

    def test_f5_l123_not_shadow_stack_sentinel_intact(self):
        try:
            from core.canonical_layer_model import (
                L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK,
            )
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        assert isinstance(L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK, str)
        assert L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK.strip()
        assert "NOT" in L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK

    def test_f_guard_returns_list(self):
        findings = check_l1_l2_l3_router_detachment()
        assert isinstance(findings, list)
        assert all(isinstance(f, TerminalGuardFinding) for f in findings)


# ===========================================================================
# G — Guard 4: completion truth bypass
# ===========================================================================


@_skip
class TestCompletionTruthBypassGuard:
    def test_g1_clean_state_passes(self):
        findings = check_completion_truth_bypass()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected completion truth bypass errors: {errors}"

    def test_g2_snapshot_is_optional_signaling_true_is_error(self):
        snapshot = {
            "layer_key": "completion_truth_backbone",
            "is_optional_signaling": True,
        }
        findings = check_completion_truth_bypass(snapshot=snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error for completion truth is_optional_signaling=True"
        assert any("optional" in f.message.lower() or "truth" in f.message.lower()
                   for f in errors)

    def test_g3_task_result_truth_chain_must_run_policy_intact(self):
        try:
            from core.task_result_canonical_truth_chain import (
                TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY,
            )
        except ImportError:
            pytest.skip("core.task_result_canonical_truth_chain not available")
        assert isinstance(TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY, str)
        assert TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY.strip()
        assert "MUST" in TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY
        assert "truth" in TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY.lower()

    def test_g4_run_task_result_truth_chain_callable(self):
        try:
            from core.task_result_canonical_truth_chain import run_task_result_truth_chain
        except ImportError:
            pytest.skip("core.task_result_canonical_truth_chain not available")
        assert callable(run_task_result_truth_chain)

    def test_g5_canonical_completion_ingress_importable(self):
        try:
            import core.canonical_completion_ingress  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"core.canonical_completion_ingress is not importable: {exc}. "
                "Canonical completion ingress backbone unavailable."
            )

    def test_g6_completion_truth_enforced_not_optional_sentinel_intact(self):
        try:
            from core.canonical_layer_model import (
                COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL,
            )
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        assert isinstance(COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL, str)
        assert COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL.strip()
        assert "NOT" in COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL

    def test_g_guard_returns_list(self):
        findings = check_completion_truth_bypass()
        assert isinstance(findings, list)
        assert all(isinstance(f, TerminalGuardFinding) for f in findings)


# ===========================================================================
# H — Guard 5: architecture declaration coherence
# ===========================================================================


@_skip
class TestArchitectureDeclarationCoherenceGuard:
    def test_h1_clean_state_passes(self):
        findings = check_architecture_declaration_coherence()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Architecture declaration coherence errors: {errors}"

    def test_h2_all_five_canonical_layer_keys_present(self):
        try:
            from core.canonical_layer_model import CANONICAL_LAYER_KEYS
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        expected = {
            "completion_truth_backbone",
            "router_cognitive_authority",
            "per_request_hot_path",
            "multi_step_orchestration_spine",
            "startup_release_integrity",
        }
        assert expected.issubset(CANONICAL_LAYER_KEYS), (
            f"Missing layer keys: {expected - frozenset(CANONICAL_LAYER_KEYS)}"
        )

    def test_h3_all_four_not_policy_sentinels_present(self):
        try:
            from core.canonical_layer_model import (
                COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL,
                L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK,
                V4_IS_NOT_PER_REQUEST_GATE,
                V6_IS_NOT_PER_REQUEST_GATE,
            )
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        for sentinel in [
            V4_IS_NOT_PER_REQUEST_GATE,
            V6_IS_NOT_PER_REQUEST_GATE,
            L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK,
            COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL,
        ]:
            assert isinstance(sentinel, str) and sentinel.strip(), \
                f"NOT-policy sentinel is empty or missing: {sentinel!r}"

    def test_h4_run_layer_model_invariants_consistent(self):
        try:
            from core.canonical_layer_model import run_layer_model_invariants
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        report = run_layer_model_invariants()
        assert report.overall_consistent, (
            f"run_layer_model_invariants() returned overall_consistent=False "
            f"({report.error_count} error(s)): "
            f"{[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_h5_bad_snapshot_surfaces_as_error(self):
        """A snapshot with is_per_request_gate=True for V4 must surface as error."""
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": True,
        }
        findings = check_architecture_declaration_coherence(snapshot=snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, (
            "Expected an error when checking a snapshot that violates "
            "the V4 layer invariant via architecture declaration coherence guard."
        )

    def test_h_guard_returns_list(self):
        findings = check_architecture_declaration_coherence()
        assert isinstance(findings, list)
        assert all(isinstance(f, TerminalGuardFinding) for f in findings)


# ===========================================================================
# I — run_terminal_audit_guards (aggregate)
# ===========================================================================


@_skip
class TestRunTerminalAuditGuards:
    def test_i1_all_five_guards_run(self):
        report = run_terminal_audit_guards()
        assert len(report.guards_run) == 5

    def test_i2_overall_passed_on_clean_system(self):
        report = run_terminal_audit_guards()
        assert report.overall_passed, (
            f"Terminal audit guards report overall_passed=False on a clean system "
            f"({report.error_count} error(s)): "
            f"{[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_i3_overall_failed_on_v4_regression_snapshot(self):
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": True,
        }
        report = run_terminal_audit_guards(snapshot=snapshot)
        assert not report.overall_passed, (
            "Expected overall_passed=False when V4 regression snapshot is provided."
        )

    def test_i4_policy_sentinels_list_has_five_entries(self):
        report = run_terminal_audit_guards()
        assert len(report.policy_sentinels) == 5

    def test_i5_to_dict_top_level_keys(self):
        report = run_terminal_audit_guards()
        d = report.to_dict()
        expected_keys = {
            "overall_passed", "error_count", "warning_count",
            "guards_run", "findings", "generated_at", "policy_sentinels",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_i6_generated_at_recent(self):
        before = time.time()
        report = run_terminal_audit_guards()
        after = time.time()
        assert before <= report.generated_at <= after

    def test_i_guards_run_names(self):
        report = run_terminal_audit_guards()
        expected_guards = {
            "V4_SCOPE_REGRESSION",
            "V6_HOT_PATH_REGRESSION",
            "L1_L2_L3_ROUTER_DETACHMENT_REGRESSION",
            "COMPLETION_TRUTH_BYPASS_REGRESSION",
            "ARCHITECTURE_DECLARATION_COHERENCE",
        }
        assert expected_guards == set(report.guards_run)

    def test_i_v6_regression_snapshot_fails(self):
        snapshot = {
            "layer_key": "startup_release_integrity",
            "is_per_request_gate": True,
        }
        report = run_terminal_audit_guards(snapshot=snapshot)
        assert not report.overall_passed

    def test_i_l123_regression_snapshot_fails(self):
        snapshot = {
            "layer_key": "router_cognitive_authority",
            "is_shadow_stack": True,
        }
        report = run_terminal_audit_guards(snapshot=snapshot)
        assert not report.overall_passed

    def test_i_completion_truth_regression_snapshot_fails(self):
        snapshot = {
            "layer_key": "completion_truth_backbone",
            "is_optional_signaling": True,
        }
        report = run_terminal_audit_guards(snapshot=snapshot)
        assert not report.overall_passed


# ===========================================================================
# J — Integration with canonical_layer_model
# ===========================================================================


@_skip
class TestIntegrationWithCanonicalLayerModel:
    def test_j1_coherence_guard_depends_on_canonical_layer_model(self):
        """check_architecture_declaration_coherence uses canonical_layer_model."""
        findings = check_architecture_declaration_coherence()
        # If canonical_layer_model is available and consistent, no error.
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_j2_canonical_layer_model_invariants_pass_independently(self):
        """run_layer_model_invariants passes on the built-in registry."""
        try:
            from core.canonical_layer_model import run_layer_model_invariants
        except ImportError:
            pytest.skip("core.canonical_layer_model not available")
        report = run_layer_model_invariants()
        assert report.overall_consistent, (
            f"Canonical layer model invariants failed: "
            f"{[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_j_terminal_guards_module_importable(self):
        """core.terminal_architecture_audit_guards must remain importable."""
        import core.terminal_architecture_audit_guards  # noqa: F401

    def test_j_canonical_layer_model_importable(self):
        """core.canonical_layer_model must remain importable."""
        import core.canonical_layer_model  # noqa: F401
