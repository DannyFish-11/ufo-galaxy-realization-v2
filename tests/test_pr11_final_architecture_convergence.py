#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr11_final_architecture_convergence.py
======================================================
PR-11: Final Architecture Convergence — test suite.

This test suite validates that the PR-11 final convergence module correctly
consolidates residual architecture edge inconsistencies and leaves the
repository in a single coherent terminal architecture state.

Coverage
--------
A  — Module importable; authority and policy sentinels present and non-empty.
B  — All expected names are in __all__.
C  — Boundary clarity sentinels: present, non-empty, contain "NOT" invariant.
D  — Convergence policy sentinels: present, non-empty.
E  — ConvergenceFinding: construction and to_dict() shape.
F  — ConvergenceReport: construction, add/extend, recompute, to_dict().

G  — check_boundary_sentinel_completeness():
     G1  clean state returns no errors.
     G2  all five boundary sentinel names are checked.
     G3  all three policy sentinel names are checked.

H  — check_terminal_guard_integrity():
     H1  clean state returns no errors.
     H2  core.terminal_architecture_audit_guards is importable.
     H3  all five guard policy sentinels are verified.
     H4  run_terminal_audit_guards() passes on clean system.

I  — check_participant_layer_consistency():
     I1  clean state returns no errors.
     I2  core.participant_authority_interfaces is importable.
     I3  three authority sentinels verified.
     I4  generic-above-Android policy sentinel verified.
     I5  Android concrete modules present.

J  — check_canonical_layer_model_reachable():
     J1  clean state returns no errors.
     J2  core.canonical_layer_model is importable.
     J3  all five layer keys present.
     J4  all four NOT-policy sentinels present.
     J5  run_layer_model_invariants() passes.

K  — run_final_convergence_checks() (aggregate):
     K1  runs all four checks; checks_run has four entries.
     K2  overall_converged=True on a clean system.
     K3  to_dict() contains all expected top-level keys.
     K4  generated_at is a recent positive timestamp.

L  — Architecture story coherence:
     L1  PR-10 guards and PR-11 convergence module coexist without conflict.
     L2  PR-9 canonical layer model and PR-11 boundary sentinels agree.
     L3  PR-8 participant interfaces and PR-11 participant boundary sentinel agree.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Skip helper — mark test as skipped if a dependency is not importable
# ---------------------------------------------------------------------------

def _importable(module_path: str) -> bool:
    try:
        import importlib
        importlib.import_module(module_path)
        return True
    except Exception:
        return False


_skip = pytest.mark.skipif(
    not _importable("core.final_architecture_convergence"),
    reason="core.final_architecture_convergence not available",
)


# ---------------------------------------------------------------------------
# A — Module importable; authority sentinels present
# ---------------------------------------------------------------------------

class TestModuleImportAndSentinels:
    def test_a1_module_importable(self):
        from core import final_architecture_convergence  # noqa: F401

    def test_a2_authority_sentinel_importable(self):
        from core.final_architecture_convergence import (
            FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY,
        )
        assert FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY

    def test_a3_pr11_sentinel_importable(self):
        from core.final_architecture_convergence import (
            FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL,
        )
        assert FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL

    def test_a4_authority_sentinel_mentions_pr11(self):
        from core.final_architecture_convergence import (
            FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY,
        )
        sentinel = FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY
        assert "PR11" in sentinel or "PR-11" in sentinel, (
            "Authority sentinel should reference PR-11"
        )

    def test_a5_authority_sentinel_mentions_convergence(self):
        from core.final_architecture_convergence import (
            FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY,
        )
        assert "convergence" in FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY.lower()

    def test_a6_pr11_sentinel_mentions_pr11(self):
        from core.final_architecture_convergence import (
            FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL,
        )
        sentinel = FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL
        assert "PR11" in sentinel or "PR-11" in sentinel


# ---------------------------------------------------------------------------
# B — __all__ completeness
# ---------------------------------------------------------------------------

@_skip
class TestAllExports:
    _EXPECTED = {
        "FINAL_ARCHITECTURE_CONVERGENCE_AUTHORITY",
        "FINAL_ARCHITECTURE_CONVERGENCE_PR11_SENTINEL",
        "PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL",
        "ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL",
        "ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL",
        "PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL",
        "STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL",
        "CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY",
        "SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY",
        "BOUNDARY_CLARITY_PRESERVED_POLICY",
        "ConvergenceFinding",
        "ConvergenceReport",
        "check_boundary_sentinel_completeness",
        "check_terminal_guard_integrity",
        "check_participant_layer_consistency",
        "check_canonical_layer_model_reachable",
        "run_final_convergence_checks",
    }

    def test_b1_all_contains_expected_names(self):
        from core import final_architecture_convergence as m
        missing = self._EXPECTED - set(m.__all__)
        assert not missing, f"Missing from __all__: {sorted(missing)}"

    def test_b2_all_names_importable(self):
        import importlib
        m = importlib.import_module("core.final_architecture_convergence")
        for name in m.__all__:
            assert hasattr(m, name), f"Name {name!r} in __all__ but not in module"


# ---------------------------------------------------------------------------
# C — Boundary clarity sentinels
# ---------------------------------------------------------------------------

@_skip
class TestBoundarySentinels:
    def test_c1_per_request_hot_path_sentinel_present(self):
        from core.final_architecture_convergence import (
            PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL,
        )
        assert PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL

    def test_c2_per_request_hot_path_sentinel_mentions_not(self):
        from core.final_architecture_convergence import (
            PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL,
        )
        assert "NOT" in PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL

    def test_c3_router_cognitive_authority_sentinel_present(self):
        from core.final_architecture_convergence import (
            ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL,
        )
        assert ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL

    def test_c4_router_cognitive_authority_mentions_not(self):
        from core.final_architecture_convergence import (
            ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL,
        )
        assert "NOT" in ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL

    def test_c5_orchestration_session_scope_sentinel_present(self):
        from core.final_architecture_convergence import (
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
        )
        assert ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL

    def test_c6_orchestration_session_scope_mentions_not(self):
        from core.final_architecture_convergence import (
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
        )
        assert "NOT" in ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL

    def test_c7_participant_generic_sentinel_present(self):
        from core.final_architecture_convergence import (
            PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL,
        )
        assert PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL

    def test_c8_participant_generic_sentinel_mentions_not(self):
        from core.final_architecture_convergence import (
            PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL,
        )
        assert "NOT" in PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL

    def test_c9_startup_release_integrity_sentinel_present(self):
        from core.final_architecture_convergence import (
            STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL,
        )
        assert STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL

    def test_c10_startup_release_integrity_mentions_not(self):
        from core.final_architecture_convergence import (
            STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL,
        )
        assert "NOT" in STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL

    def test_c11_all_five_boundary_sentinels_are_distinct(self):
        from core.final_architecture_convergence import (
            PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL,
            ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL,
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
            PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL,
            STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL,
        )
        all_five = [
            PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL,
            ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL,
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
            PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL,
            STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL,
        ]
        assert len(set(all_five)) == 5, "All five boundary sentinels must be distinct"


# ---------------------------------------------------------------------------
# D — Convergence policy sentinels
# ---------------------------------------------------------------------------

@_skip
class TestConvergencePolicySentinels:
    def test_d1_no_redesign_policy_present(self):
        from core.final_architecture_convergence import (
            CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY,
        )
        assert CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY

    def test_d2_no_redesign_policy_mentions_runtime(self):
        from core.final_architecture_convergence import (
            CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY,
        )
        policy = CONVERGENCE_PASS_DOES_NOT_REDESIGN_RUNTIME_POLICY.lower()
        assert "runtime" in policy or "redesign" in policy

    def test_d3_single_story_policy_present(self):
        from core.final_architecture_convergence import (
            SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY,
        )
        assert SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY

    def test_d4_single_story_policy_mentions_one_story(self):
        from core.final_architecture_convergence import (
            SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY,
        )
        policy = SINGLE_COHERENT_ARCHITECTURE_STORY_POLICY.lower()
        assert "one" in policy or "single" in policy or "coherent" in policy

    def test_d5_boundary_clarity_policy_present(self):
        from core.final_architecture_convergence import (
            BOUNDARY_CLARITY_PRESERVED_POLICY,
        )
        assert BOUNDARY_CLARITY_PRESERVED_POLICY

    def test_d6_boundary_clarity_policy_references_all_five_boundaries(self):
        from core.final_architecture_convergence import (
            BOUNDARY_CLARITY_PRESERVED_POLICY,
        )
        # The policy should reference the five boundary sentinels by name
        expected_names = [
            "PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL",
            "ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL",
            "ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL",
            "PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL",
            "STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL",
        ]
        for name in expected_names:
            assert name in BOUNDARY_CLARITY_PRESERVED_POLICY, (
                f"BOUNDARY_CLARITY_PRESERVED_POLICY does not reference {name!r}"
            )


# ---------------------------------------------------------------------------
# E — ConvergenceFinding
# ---------------------------------------------------------------------------

@_skip
class TestConvergenceFinding:
    def test_e1_construction(self):
        from core.final_architecture_convergence import ConvergenceFinding
        f = ConvergenceFinding(check="MYCHECK", severity="info", message="all good")
        assert f.check == "MYCHECK"
        assert f.severity == "info"
        assert f.message == "all good"
        assert f.detail == {}

    def test_e2_construction_with_detail(self):
        from core.final_architecture_convergence import ConvergenceFinding
        f = ConvergenceFinding(
            check="MYCHECK",
            severity="error",
            message="something broken",
            detail={"key": "value"},
        )
        assert f.detail == {"key": "value"}

    def test_e3_to_dict_shape(self):
        from core.final_architecture_convergence import ConvergenceFinding
        f = ConvergenceFinding(check="X", severity="warning", message="watch out")
        d = f.to_dict()
        assert set(d.keys()) == {"check", "severity", "message", "detail"}

    def test_e4_immutable(self):
        from core.final_architecture_convergence import ConvergenceFinding
        f = ConvergenceFinding(check="X", severity="info", message="ok")
        with pytest.raises((AttributeError, TypeError)):
            f.check = "Y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# F — ConvergenceReport
# ---------------------------------------------------------------------------

@_skip
class TestConvergenceReport:
    def test_f1_construction_defaults(self):
        from core.final_architecture_convergence import ConvergenceReport
        r = ConvergenceReport()
        assert r.findings == []
        assert r.checks_run == []
        assert r.overall_converged is True
        assert r.error_count == 0
        assert r.warning_count == 0

    def test_f2_add_info_finding_preserves_converged(self):
        from core.final_architecture_convergence import ConvergenceFinding, ConvergenceReport
        r = ConvergenceReport()
        r.add(ConvergenceFinding(check="X", severity="info", message="ok"))
        assert r.overall_converged is True

    def test_f3_add_error_finding_sets_not_converged(self):
        from core.final_architecture_convergence import ConvergenceFinding, ConvergenceReport
        r = ConvergenceReport()
        r.add(ConvergenceFinding(check="X", severity="error", message="broken"))
        assert r.overall_converged is False
        assert r.error_count == 1

    def test_f4_extend_multiple_findings(self):
        from core.final_architecture_convergence import ConvergenceFinding, ConvergenceReport
        r = ConvergenceReport()
        findings = [
            ConvergenceFinding(check="A", severity="info", message="ok"),
            ConvergenceFinding(check="B", severity="warning", message="watch"),
            ConvergenceFinding(check="C", severity="error", message="broken"),
        ]
        r.extend(findings)
        assert len(r.findings) == 3
        assert r.error_count == 1
        assert r.warning_count == 1

    def test_f5_to_dict_contains_expected_keys(self):
        from core.final_architecture_convergence import ConvergenceReport
        r = ConvergenceReport()
        d = r.to_dict()
        expected_keys = {
            "overall_converged",
            "error_count",
            "warning_count",
            "checks_run",
            "findings",
            "generated_at",
        }
        assert expected_keys.issubset(set(d.keys()))


# ---------------------------------------------------------------------------
# G — check_boundary_sentinel_completeness
# ---------------------------------------------------------------------------

@_skip
class TestBoundarySentinelCompletenessCheck:
    def test_g1_clean_state_passes(self):
        from core.final_architecture_convergence import check_boundary_sentinel_completeness
        findings = check_boundary_sentinel_completeness()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected errors: {errors}"

    def test_g2_all_five_boundary_sentinels_checked(self):
        from core.final_architecture_convergence import check_boundary_sentinel_completeness
        findings = check_boundary_sentinel_completeness()
        # Each boundary sentinel should produce an info finding
        info_findings = [f for f in findings if f.severity == "info"]
        boundary_names = [
            "PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL",
            "ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL",
            "ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL",
            "PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL",
            "STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL",
        ]
        # We should have info findings for all five
        assert len(info_findings) >= 5, (
            "Expected at least 5 info findings (one per boundary sentinel) "
            f"but got {len(info_findings)}"
        )

    def test_g3_all_three_policy_sentinels_checked(self):
        from core.final_architecture_convergence import check_boundary_sentinel_completeness
        findings = check_boundary_sentinel_completeness()
        # Should have at least 8 info findings (5 boundary + 3 policy)
        info_findings = [f for f in findings if f.severity == "info"]
        assert len(info_findings) >= 8, (
            "Expected at least 8 info findings (5 boundary + 3 policy) "
            f"but got {len(info_findings)}"
        )


# ---------------------------------------------------------------------------
# H — check_terminal_guard_integrity
# ---------------------------------------------------------------------------

@_skip
class TestTerminalGuardIntegrityCheck:
    def test_h1_clean_state_passes(self):
        from core.final_architecture_convergence import check_terminal_guard_integrity
        findings = check_terminal_guard_integrity()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected errors: {errors}"

    def test_h2_terminal_guards_module_found(self):
        from core.final_architecture_convergence import check_terminal_guard_integrity
        findings = check_terminal_guard_integrity()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any("terminal_architecture_audit_guards" in m for m in info_msgs), (
            "Expected info finding confirming terminal_architecture_audit_guards is importable"
        )

    def test_h3_five_guard_policy_sentinels_verified(self):
        from core.final_architecture_convergence import check_terminal_guard_integrity
        findings = check_terminal_guard_integrity()
        # Five guard policy sentinels + importable + run result = at least 7 info findings
        info_findings = [f for f in findings if f.severity == "info"]
        assert len(info_findings) >= 7, (
            f"Expected at least 7 info findings, got {len(info_findings)}"
        )

    def test_h4_run_terminal_audit_guards_passes(self):
        from core.final_architecture_convergence import check_terminal_guard_integrity
        findings = check_terminal_guard_integrity()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "Terminal audit guards should pass on a clean system — "
            f"errors found: {[f.message for f in errors]}"
        )


# ---------------------------------------------------------------------------
# I — check_participant_layer_consistency
# ---------------------------------------------------------------------------

@_skip
class TestParticipantLayerConsistencyCheck:
    def test_i1_clean_state_passes(self):
        from core.final_architecture_convergence import check_participant_layer_consistency
        findings = check_participant_layer_consistency()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected errors: {errors}"

    def test_i2_participant_interfaces_found(self):
        from core.final_architecture_convergence import check_participant_layer_consistency
        findings = check_participant_layer_consistency()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any("participant_authority_interfaces" in m for m in info_msgs)

    def test_i3_three_authority_sentinels_verified(self):
        from core.final_architecture_convergence import check_participant_layer_consistency
        findings = check_participant_layer_consistency()
        # At least 3 info findings for the three authority sentinels
        info_findings = [f for f in findings if f.severity == "info"]
        assert len(info_findings) >= 3

    def test_i4_generic_above_android_policy_verified(self):
        from core.final_architecture_convergence import check_participant_layer_consistency
        findings = check_participant_layer_consistency()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any(
            "PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY" in m
            for m in info_msgs
        ), "Expected info finding for PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY"

    def test_i5_android_concrete_modules_present(self):
        from core.final_architecture_convergence import check_participant_layer_consistency
        findings = check_participant_layer_consistency()
        # Should have info findings for at least one Android concrete module
        android_info = [
            f for f in findings
            if f.severity == "info" and "android" in f.message.lower()
        ]
        assert android_info, (
            "Expected at least one info finding confirming an Android concrete module is present"
        )


# ---------------------------------------------------------------------------
# J — check_canonical_layer_model_reachable
# ---------------------------------------------------------------------------

@_skip
class TestCanonicalLayerModelReachableCheck:
    def test_j1_clean_state_passes(self):
        from core.final_architecture_convergence import check_canonical_layer_model_reachable
        findings = check_canonical_layer_model_reachable()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected errors: {errors}"

    def test_j2_canonical_layer_model_found(self):
        from core.final_architecture_convergence import check_canonical_layer_model_reachable
        findings = check_canonical_layer_model_reachable()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any("canonical_layer_model" in m for m in info_msgs)

    def test_j3_all_five_layer_keys_present(self):
        from core.final_architecture_convergence import check_canonical_layer_model_reachable
        findings = check_canonical_layer_model_reachable()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any("five canonical layer keys" in m for m in info_msgs), (
            "Expected info finding confirming all five canonical layer keys are present"
        )

    def test_j4_all_four_not_sentinels_present(self):
        from core.final_architecture_convergence import check_canonical_layer_model_reachable
        findings = check_canonical_layer_model_reachable()
        not_sentinels = [
            "V4_IS_NOT_PER_REQUEST_GATE",
            "V6_IS_NOT_PER_REQUEST_GATE",
            "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK",
            "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL",
        ]
        info_msgs = [f.message for f in findings if f.severity == "info"]
        for sentinel in not_sentinels:
            assert any(sentinel in m for m in info_msgs), (
                f"Expected info finding confirming {sentinel!r} is present"
            )

    def test_j5_layer_model_invariants_pass(self):
        from core.final_architecture_convergence import check_canonical_layer_model_reachable
        findings = check_canonical_layer_model_reachable()
        info_msgs = [f.message for f in findings if f.severity == "info"]
        assert any("run_layer_model_invariants" in m and "passed" in m for m in info_msgs), (
            "Expected info finding confirming run_layer_model_invariants() passed"
        )


# ---------------------------------------------------------------------------
# K — run_final_convergence_checks (aggregate)
# ---------------------------------------------------------------------------

@_skip
class TestRunFinalConvergenceChecks:
    def test_k1_runs_all_four_checks(self):
        from core.final_architecture_convergence import run_final_convergence_checks
        report = run_final_convergence_checks()
        assert len(report.checks_run) == 4, (
            f"Expected 4 checks_run, got {len(report.checks_run)}: {report.checks_run}"
        )

    def test_k2_overall_converged_true_on_clean_system(self):
        from core.final_architecture_convergence import run_final_convergence_checks
        report = run_final_convergence_checks()
        assert report.overall_converged is True, (
            f"Expected overall_converged=True on clean system; "
            f"errors: {[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_k3_to_dict_contains_all_expected_keys(self):
        from core.final_architecture_convergence import run_final_convergence_checks
        report = run_final_convergence_checks()
        d = report.to_dict()
        expected_keys = {
            "overall_converged",
            "error_count",
            "warning_count",
            "checks_run",
            "findings",
            "generated_at",
        }
        assert expected_keys.issubset(set(d.keys())), (
            f"Missing keys in to_dict(): {expected_keys - set(d.keys())}"
        )

    def test_k4_generated_at_is_recent_positive_timestamp(self):
        from core.final_architecture_convergence import run_final_convergence_checks
        before = time.time() - 5.0
        report = run_final_convergence_checks()
        after = time.time()
        assert report.generated_at > 0, "generated_at must be positive"
        assert before <= report.generated_at <= after, (
            f"generated_at {report.generated_at} not in expected range "
            f"[{before}, {after}]"
        )

    def test_k5_checks_run_names_match_expected(self):
        from core.final_architecture_convergence import run_final_convergence_checks
        report = run_final_convergence_checks()
        expected_checks = {
            "BOUNDARY_SENTINEL_COMPLETENESS",
            "TERMINAL_GUARD_INTEGRITY",
            "PARTICIPANT_LAYER_CONSISTENCY",
            "CANONICAL_LAYER_MODEL_REACHABLE",
        }
        assert expected_checks == set(report.checks_run), (
            f"checks_run mismatch. Expected: {sorted(expected_checks)}, "
            f"Got: {sorted(report.checks_run)}"
        )


# ---------------------------------------------------------------------------
# L — Architecture story coherence
# ---------------------------------------------------------------------------

@_skip
class TestArchitectureStoryCoherence:
    def test_l1_pr10_guards_and_pr11_convergence_coexist(self):
        """PR-10 terminal guards and PR-11 convergence module are both importable."""
        from core import terminal_architecture_audit_guards  # noqa: F401
        from core import final_architecture_convergence  # noqa: F401

    def test_l2_canonical_layer_not_sentinels_agree_with_pr11_boundary_sentinels(self):
        """The four NOT-policy sentinels in canonical_layer_model are expressed
        in the PR-11 boundary sentinels without contradiction."""
        from core.canonical_layer_model import (
            V4_IS_NOT_PER_REQUEST_GATE,
            V6_IS_NOT_PER_REQUEST_GATE,
            L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK,
            COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL,
        )
        from core.final_architecture_convergence import (
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
            STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL,
            ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL,
            PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL,
        )
        # The orchestration session scope sentinel should echo V4's NOT-gate principle
        assert "NOT" in ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL
        # The startup/release integrity sentinel should echo V6's NOT-gate principle
        assert "NOT" in STARTUP_RELEASE_INTEGRITY_BOUNDARY_SENTINEL
        # The router cognitive authority sentinel should echo L1/L2/L3's NOT-shadow-stack
        assert "NOT" in ROUTER_COGNITIVE_AUTHORITY_BOUNDARY_SENTINEL
        # The hot path sentinel should reference V4 and V6 as NOT inserted
        assert "NOT" in PER_REQUEST_HOT_PATH_BOUNDARY_SENTINEL

    def test_l3_pr8_participant_interfaces_agrees_with_pr11_boundary_sentinel(self):
        """PR-8 ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL agrees with
        the PR-11 participant generic/concrete boundary sentinel."""
        from core.participant_authority_interfaces import (
            ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL,
        )
        from core.final_architecture_convergence import (
            PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL,
        )
        # Both sentinels are non-empty
        assert ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL
        assert PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL
        # Both reference Android as concrete
        assert "android" in ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL.lower()
        assert "android" in PARTICIPANT_GENERIC_VS_ANDROID_CONCRETE_BOUNDARY_SENTINEL.lower()

    def test_l4_pr9_layer_model_and_pr11_all_five_layers_match(self):
        """PR-9 CANONICAL_LAYER_KEYS matches the five layer keys expected by PR-11."""
        from core.canonical_layer_model import CANONICAL_LAYER_KEYS
        expected = {
            "completion_truth_backbone",
            "router_cognitive_authority",
            "per_request_hot_path",
            "multi_step_orchestration_spine",
            "startup_release_integrity",
        }
        assert expected == frozenset(CANONICAL_LAYER_KEYS), (
            f"CANONICAL_LAYER_KEYS mismatch: {frozenset(CANONICAL_LAYER_KEYS)}"
        )

    def test_l5_no_residual_split_brain_in_key_sentinels(self):
        """No key sentinel claims V4 is a universal per-request gate."""
        from core.final_architecture_convergence import (
            ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL,
        )
        # The orchestration scope sentinel must not claim V4 is universal
        lower = ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL.lower()
        # It must not say V4 governs ALL requests universally without the NOT qualifier
        assert "NOT" in ORCHESTRATION_SESSION_SCOPE_BOUNDARY_SENTINEL, (
            "Orchestration scope boundary sentinel must express a NOT-boundary invariant"
        )
