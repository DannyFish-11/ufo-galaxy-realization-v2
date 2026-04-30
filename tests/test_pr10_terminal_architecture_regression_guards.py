#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_terminal_architecture_regression_guards.py
==========================================================

PR-10 — Terminal Architecture Regression Guards.

This test suite validates that the terminal regression guards in
``core.terminal_architecture_regression_guards`` correctly detect the five
most critical architecture regressions:

1. V4 (unified_orchestration_spine) incorrectly wired as universal per-request gate.
2. V6 (release_blocking_gate / center_authority_boundary) inserted into hot paths.
3. L1/L2/L3 no longer participating in router-level cognitive authority.
4. Canonical completion truth chain weakened to optional soft signaling.
5. Repository-level layer declarations diverging from the final integrated model.

Coverage
--------

1.  Module sentinels
    - TERMINAL_REGRESSION_GUARD_AUTHORITY is a non-empty string
    - TERMINAL_REGRESSION_GUARD_PR10_SENTINEL is a non-empty string
    - All five guard-level sentinel constants importable and non-empty

2.  RegressionFinding
    - construction with all fields
    - to_dict is JSON-serialisable

3.  RegressionReport
    - overall_safe=True when no error findings
    - overall_safe=False when any error finding present
    - error_count / warning_count computed correctly
    - to_dict is JSON-serialisable
    - guards_run list populated correctly

4.  check_v4_hot_path_isolation — Guard 1
    - Returns INFO (pass) when openclawd.py has no V4 reference
    - Returns ERROR when a fake source with unified_orchestration_spine import is scanned
    - Detects evaluate_orchestration_request call pattern
    - Reports correct violation key V4_IS_NOT_PER_REQUEST_GATE

5.  check_v6_hot_path_isolation — Guard 2
    - Returns INFO (pass) when openclawd.py has no V6 reference
    - Returns ERROR when a fake source with release_blocking_gate import is scanned
    - Detects center_authority_boundary call pattern
    - Reports correct violation key V6_IS_NOT_PER_REQUEST_GATE

6.  check_l1_l2_l3_router_fusion — Guard 3
    - Returns INFO on a system where L1/L2/L3 and facade are importable
    - Reports violation key L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK
      when a required module is not importable (simulated via bad snapshot)

7.  check_completion_truth_backbone — Guard 4
    - Returns INFO on a system where canonical_completion_ingress is importable
    - Reports violation key COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL when module missing

8.  check_layer_declarations_convergence — Guard 5
    - Returns INFO when no snapshots provided (registry self-consistent)
    - Returns ERROR for snapshot with V4 as per-request gate
    - Returns ERROR for snapshot with V6 as per-request gate
    - Returns ERROR for snapshot with L1/L2/L3 as shadow stack
    - Returns ERROR for snapshot with completion truth as optional signaling

9.  run_terminal_regression_guards — aggregate
    - overall_safe=True on clean system
    - guards_run contains all five guard names
    - to_dict serialisable
    - V4 regression snapshot produces overall_safe=False

10. Integration with architecture_invariants.run_consolidation_invariants
    - TERMINAL_REGRESSION_GUARDS appears in checks_run
    - check_terminal_regression_guards importable and callable
    - clean system: run_consolidation_invariants still overall_consistent=True
    - bad V4 snapshot: run_consolidation_invariants becomes not overall_consistent

11. Module __all__ completeness
    - all __all__ symbols importable from the module
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# 1. Module sentinels
# ===========================================================================


class TestModuleSentinels:
    def test_terminal_authority_sentinel_importable(self):
        from core.terminal_architecture_regression_guards import (
            TERMINAL_REGRESSION_GUARD_AUTHORITY,
        )
        assert isinstance(TERMINAL_REGRESSION_GUARD_AUTHORITY, str)
        assert TERMINAL_REGRESSION_GUARD_AUTHORITY.strip()

    def test_terminal_authority_sentinel_references_pr10(self):
        from core.terminal_architecture_regression_guards import (
            TERMINAL_REGRESSION_GUARD_AUTHORITY,
        )
        upper = TERMINAL_REGRESSION_GUARD_AUTHORITY.upper()
        assert "PR10" in upper or "PR-10" in upper

    def test_pr10_sentinel_importable(self):
        from core.terminal_architecture_regression_guards import (
            TERMINAL_REGRESSION_GUARD_PR10_SENTINEL,
        )
        assert isinstance(TERMINAL_REGRESSION_GUARD_PR10_SENTINEL, str)
        assert TERMINAL_REGRESSION_GUARD_PR10_SENTINEL.strip()

    def test_pr10_sentinel_references_pr10(self):
        from core.terminal_architecture_regression_guards import (
            TERMINAL_REGRESSION_GUARD_PR10_SENTINEL,
        )
        upper = TERMINAL_REGRESSION_GUARD_PR10_SENTINEL.upper()
        assert "PR10" in upper or "PR-10" in upper

    def test_v4_hot_path_isolation_guard_present(self):
        from core.terminal_architecture_regression_guards import V4_HOT_PATH_ISOLATION_GUARD
        assert isinstance(V4_HOT_PATH_ISOLATION_GUARD, str)
        assert "V4" in V4_HOT_PATH_ISOLATION_GUARD
        assert "NOT" in V4_HOT_PATH_ISOLATION_GUARD or "not" in V4_HOT_PATH_ISOLATION_GUARD.lower()

    def test_v6_hot_path_isolation_guard_present(self):
        from core.terminal_architecture_regression_guards import V6_HOT_PATH_ISOLATION_GUARD
        assert isinstance(V6_HOT_PATH_ISOLATION_GUARD, str)
        assert "V6" in V6_HOT_PATH_ISOLATION_GUARD
        assert "NOT" in V6_HOT_PATH_ISOLATION_GUARD or "not" in V6_HOT_PATH_ISOLATION_GUARD.lower()

    def test_l1_l2_l3_router_fusion_guard_present(self):
        from core.terminal_architecture_regression_guards import L1_L2_L3_ROUTER_FUSION_GUARD
        assert isinstance(L1_L2_L3_ROUTER_FUSION_GUARD, str)
        assert "L1" in L1_L2_L3_ROUTER_FUSION_GUARD

    def test_completion_truth_backbone_guard_present(self):
        from core.terminal_architecture_regression_guards import COMPLETION_TRUTH_BACKBONE_GUARD
        assert isinstance(COMPLETION_TRUTH_BACKBONE_GUARD, str)
        assert "completion" in COMPLETION_TRUTH_BACKBONE_GUARD.lower()

    def test_layer_declarations_convergence_guard_present(self):
        from core.terminal_architecture_regression_guards import (
            LAYER_DECLARATIONS_CONVERGENCE_GUARD,
        )
        assert isinstance(LAYER_DECLARATIONS_CONVERGENCE_GUARD, str)
        assert "layer" in LAYER_DECLARATIONS_CONVERGENCE_GUARD.lower()


# ===========================================================================
# 2. RegressionFinding
# ===========================================================================


class TestRegressionFinding:
    def test_construction_with_all_fields(self):
        from core.terminal_architecture_regression_guards import RegressionFinding
        f = RegressionFinding(
            guard="SOME_GUARD",
            severity="error",
            message="test message",
            detail={"key": "value"},
        )
        assert f.guard == "SOME_GUARD"
        assert f.severity == "error"
        assert f.message == "test message"
        assert f.detail == {"key": "value"}

    def test_to_dict_json_serialisable(self):
        from core.terminal_architecture_regression_guards import RegressionFinding
        f = RegressionFinding(
            guard="G", severity="warning", message="msg", detail={"x": 1}
        )
        d = f.to_dict()
        json.dumps(d)  # must not raise

    def test_to_dict_contains_all_fields(self):
        from core.terminal_architecture_regression_guards import RegressionFinding
        f = RegressionFinding(guard="G", severity="info", message="m")
        d = f.to_dict()
        assert "guard" in d
        assert "severity" in d
        assert "message" in d
        assert "detail" in d


# ===========================================================================
# 3. RegressionReport
# ===========================================================================


class TestRegressionReport:
    def test_overall_safe_true_when_no_errors(self):
        from core.terminal_architecture_regression_guards import (
            RegressionFinding,
            RegressionReport,
        )
        report = RegressionReport()
        report.add(RegressionFinding(guard="G", severity="info", message="ok"))
        assert report.overall_safe

    def test_overall_safe_false_when_error_present(self):
        from core.terminal_architecture_regression_guards import (
            RegressionFinding,
            RegressionReport,
        )
        report = RegressionReport()
        report.add(RegressionFinding(guard="G", severity="error", message="bad"))
        assert not report.overall_safe

    def test_error_count_correct(self):
        from core.terminal_architecture_regression_guards import (
            RegressionFinding,
            RegressionReport,
        )
        report = RegressionReport()
        report.add(RegressionFinding(guard="G", severity="error", message="e1"))
        report.add(RegressionFinding(guard="G", severity="error", message="e2"))
        report.add(RegressionFinding(guard="G", severity="warning", message="w1"))
        assert report.error_count == 2
        assert report.warning_count == 1

    def test_to_dict_json_serialisable(self):
        from core.terminal_architecture_regression_guards import RegressionReport
        report = RegressionReport()
        report.guards_run.append("TEST_GUARD")
        d = report.to_dict()
        json.dumps(d)

    def test_guards_run_populated(self):
        from core.terminal_architecture_regression_guards import RegressionReport
        report = RegressionReport()
        report.guards_run.extend(["GUARD_A", "GUARD_B"])
        assert "GUARD_A" in report.guards_run
        assert "GUARD_B" in report.guards_run


# ===========================================================================
# 4. check_v4_hot_path_isolation — Guard 1
# ===========================================================================


class TestCheckV4HotPathIsolation:
    """V4 must NOT be imported or called in per-request hot-path files."""

    def test_clean_project_passes(self):
        """On the real codebase, openclawd and command_router must not import V4."""
        from core.terminal_architecture_regression_guards import check_v4_hot_path_isolation
        findings = check_v4_hot_path_isolation(project_root=PROJECT_ROOT)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "V4 (unified_orchestration_spine) must not be referenced in "
            "per-request hot-path modules.  Errors: "
            + str([f.message for f in errors])
        )

    def test_fake_source_with_v4_import_triggers_error(self, tmp_path):
        """A fake openclawd.py that imports unified_orchestration_spine triggers ERROR."""
        from core.terminal_architecture_regression_guards import check_v4_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "openclawd.py").write_text(
            textwrap.dedent("""\
                from core.unified_orchestration_spine import evaluate_orchestration_request

                class OpenClawd:
                    def process(self, request):
                        return evaluate_orchestration_request(request)
            """),
            encoding="utf-8",
        )

        findings = check_v4_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when openclawd.py imports unified_orchestration_spine"
        assert any("V4_IS_NOT_PER_REQUEST_GATE" in f.detail.get("violation", "")
                   for f in errors)

    def test_fake_source_with_evaluate_call_triggers_error(self, tmp_path):
        """A fake command_router.py that calls evaluate_orchestration_request triggers ERROR."""
        from core.terminal_architecture_regression_guards import check_v4_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "command_router.py").write_text(
            textwrap.dedent("""\
                class CommandRouter:
                    def route_envelope(self, envelope):
                        result = evaluate_orchestration_request(envelope)
                        return result
            """),
            encoding="utf-8",
        )

        findings = check_v4_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when command_router.py calls evaluate_orchestration_request"

    def test_clean_fake_source_passes(self, tmp_path):
        """A fake openclawd.py with no V4 reference passes the guard."""
        from core.terminal_architecture_regression_guards import check_v4_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "openclawd.py").write_text(
            textwrap.dedent("""\
                class OpenClawd:
                    def process(self, request):
                        return self._route(request)
                    def _route(self, request):
                        return {}
            """),
            encoding="utf-8",
        )

        findings = check_v4_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_missing_hot_path_files_returns_info_not_error(self, tmp_path):
        """When hot-path files don't exist the guard returns INFO, not ERROR."""
        from core.terminal_architecture_regression_guards import check_v4_hot_path_isolation
        findings = check_v4_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 5. check_v6_hot_path_isolation — Guard 2
# ===========================================================================


class TestCheckV6HotPathIsolation:
    """V6 must NOT be imported or called in per-request hot-path files."""

    def test_clean_project_passes(self):
        """On the real codebase, openclawd and command_router must not import V6."""
        from core.terminal_architecture_regression_guards import check_v6_hot_path_isolation
        findings = check_v6_hot_path_isolation(project_root=PROJECT_ROOT)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "V6 (release_blocking_gate / center_authority_boundary) must not be "
            "referenced in per-request hot-path modules.  Errors: "
            + str([f.message for f in errors])
        )

    def test_fake_source_with_release_blocking_gate_import_triggers_error(self, tmp_path):
        """A fake openclawd.py that imports release_blocking_gate triggers ERROR."""
        from core.terminal_architecture_regression_guards import check_v6_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "openclawd.py").write_text(
            textwrap.dedent("""\
                from core.release_blocking_gate import evaluate_release_blocking_gate

                class OpenClawd:
                    def process(self, request):
                        evaluate_release_blocking_gate()
                        return {}
            """),
            encoding="utf-8",
        )

        findings = check_v6_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when openclawd.py imports release_blocking_gate"
        assert any("V6_IS_NOT_PER_REQUEST_GATE" in f.detail.get("violation", "")
                   for f in errors)

    def test_fake_source_with_center_authority_boundary_call_triggers_error(self, tmp_path):
        """A fake command_router.py that calls assert_center_authority_intact triggers ERROR."""
        from core.terminal_architecture_regression_guards import check_v6_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "command_router.py").write_text(
            textwrap.dedent("""\
                class CommandRouter:
                    def route_envelope(self, envelope):
                        assert_center_authority_intact()
                        return {}
            """),
            encoding="utf-8",
        )

        findings = check_v6_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when command_router.py calls assert_center_authority_intact"

    def test_clean_fake_source_passes(self, tmp_path):
        """A fake openclawd.py with no V6 reference passes the guard."""
        from core.terminal_architecture_regression_guards import check_v6_hot_path_isolation

        core_dir = tmp_path / "core"
        core_dir.mkdir()
        (core_dir / "openclawd.py").write_text(
            textwrap.dedent("""\
                class OpenClawd:
                    def process(self, request):
                        return {}
            """),
            encoding="utf-8",
        )

        findings = check_v6_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_missing_hot_path_files_returns_info_not_error(self, tmp_path):
        """When hot-path files don't exist the guard returns INFO, not ERROR."""
        from core.terminal_architecture_regression_guards import check_v6_hot_path_isolation
        findings = check_v6_hot_path_isolation(project_root=tmp_path)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 6. check_l1_l2_l3_router_fusion — Guard 3
# ===========================================================================


class TestCheckL1L2L3RouterFusion:
    """L1/L2/L3 must remain importable and fused in UnifiedLLMRouter."""

    def test_l1_l2_l3_importable_on_real_system(self):
        """All three cognitive authority modules must be importable."""
        l1 = pytest.importorskip("core.llm.route_authority")
        l2 = pytest.importorskip("core.llm.supply_authority")
        l3 = pytest.importorskip("core.llm.context_authority")
        assert hasattr(l1, "LLM_ROUTE_AUTHORITY")
        assert hasattr(l2, "LLM_SUPPLY_AUTHORITY")
        assert hasattr(l3, "LLM_CONTEXT_AUTHORITY")

    def test_unified_llm_router_facade_importable(self):
        """UnifiedLLMRouter facade must be importable with authority sentinel."""
        facade = pytest.importorskip("core.unified.llm_router")
        assert hasattr(facade, "UNIFIED_LLM_ROUTER_AUTHORITY")

    def test_guard_passes_on_real_system(self):
        """On the real codebase, check_l1_l2_l3_router_fusion must pass (no errors)."""
        from core.terminal_architecture_regression_guards import check_l1_l2_l3_router_fusion
        findings = check_l1_l2_l3_router_fusion()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "L1/L2/L3 router cognitive authority check failed.  Errors: "
            + str([f.message for f in errors])
        )

    def test_violation_key_present_in_detail_when_module_missing(self, monkeypatch):
        """When a sub-layer file is absent, violation key is L1_L2_L3_BELONGS_TO_ROUTER_LAYER."""
        import core.terminal_architecture_regression_guards as targ
        original_file_exists = targ._module_file_exists

        def patched_file_exists(module_path):
            if module_path == "core.llm.route_authority":
                return False  # simulate the file being removed
            return original_file_exists(module_path)

        monkeypatch.setattr(targ, "_module_file_exists", patched_file_exists)

        findings = targ.check_l1_l2_l3_router_fusion()
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when L1 module file is absent"
        assert any(
            "L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK"
            in f.detail.get("violation", "")
            for f in errors
        )


# ===========================================================================
# 7. check_completion_truth_backbone — Guard 4
# ===========================================================================


class TestCheckCompletionTruthBackbone:
    """Canonical completion truth backbone must remain present and enforced."""

    def test_completion_ingress_importable_on_real_system(self):
        """core.canonical_completion_ingress must be importable."""
        import core.canonical_completion_ingress as cci
        assert hasattr(cci, "CANONICAL_COMPLETION_INGRESS_SENTINEL")

    def test_guard_passes_on_real_system(self):
        """On the real codebase, check_completion_truth_backbone must pass."""
        from core.terminal_architecture_regression_guards import check_completion_truth_backbone
        findings = check_completion_truth_backbone()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "Completion truth backbone check failed.  Errors: "
            + str([f.message for f in errors])
        )

    def test_violation_key_present_when_module_missing(self, monkeypatch):
        """When canonical_completion_ingress is not importable, violation key is correct."""
        import core.terminal_architecture_regression_guards as targ
        original_try = targ._try_import

        def patched_try(module_path):
            if module_path == "core.canonical_completion_ingress":
                return False, None, "simulated missing module"
            return original_try(module_path)

        monkeypatch.setattr(targ, "_try_import", patched_try)

        findings = targ.check_completion_truth_backbone()
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when canonical_completion_ingress is missing"
        assert any(
            "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL" in f.detail.get("violation", "")
            for f in errors
        )

    def test_violation_when_sentinel_missing_from_module(self, monkeypatch):
        """When the module imports but lacks CANONICAL_COMPLETION_INGRESS_SENTINEL, emit ERROR."""
        import types
        import core.terminal_architecture_regression_guards as targ
        original_try = targ._try_import

        def patched_try(module_path):
            if module_path == "core.canonical_completion_ingress":
                stub = types.ModuleType("core.canonical_completion_ingress")
                # Deliberately omit the sentinel
                return True, stub, None
            return original_try(module_path)

        monkeypatch.setattr(targ, "_try_import", patched_try)

        findings = targ.check_completion_truth_backbone()
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when sentinel is missing from the module"
        assert any(
            "COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL" in f.detail.get("violation", "")
            for f in errors
        )


# ===========================================================================
# 8. check_layer_declarations_convergence — Guard 5
# ===========================================================================


class TestCheckLayerDeclarationsConvergence:
    """Canonical layer model must remain self-consistent."""

    def test_no_snapshots_passes(self):
        """Registry self-consistency check must pass on the real codebase."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        findings = check_layer_declarations_convergence()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_v4_per_request_gate_snapshot_triggers_error(self):
        """Snapshot declaring V4 as per-request gate must trigger ERROR."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        snapshots = [{"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}]
        findings = check_layer_declarations_convergence(snapshots)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when V4 declared as per-request gate"

    def test_v6_per_request_gate_snapshot_triggers_error(self):
        """Snapshot declaring V6 as per-request gate must trigger ERROR."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        snapshots = [{"layer_key": "startup_release_integrity", "is_per_request_gate": True}]
        findings = check_layer_declarations_convergence(snapshots)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when V6 declared as per-request gate"

    def test_l1_l2_l3_shadow_stack_snapshot_triggers_error(self):
        """Snapshot declaring L1/L2/L3 as shadow stack must trigger ERROR."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        snapshots = [{"layer_key": "router_cognitive_authority", "is_shadow_stack": True}]
        findings = check_layer_declarations_convergence(snapshots)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when L1/L2/L3 declared as shadow stack"

    def test_completion_truth_optional_snapshot_triggers_error(self):
        """Snapshot declaring completion truth as optional signaling must trigger ERROR."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        snapshots = [{"layer_key": "completion_truth_backbone", "is_optional_signaling": True}]
        findings = check_layer_declarations_convergence(snapshots)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected ERROR when completion truth declared as optional signaling"

    def test_clean_snapshots_pass(self):
        """Correct snapshots should produce no errors."""
        from core.terminal_architecture_regression_guards import (
            check_layer_declarations_convergence,
        )
        snapshots = [
            {"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": False},
            {"layer_key": "startup_release_integrity", "is_per_request_gate": False},
            {"layer_key": "router_cognitive_authority", "is_shadow_stack": False},
            {"layer_key": "completion_truth_backbone", "is_optional_signaling": False},
        ]
        findings = check_layer_declarations_convergence(snapshots)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 9. run_terminal_regression_guards — aggregate
# ===========================================================================


class TestRunTerminalRegressionGuards:
    def test_overall_safe_true_on_clean_system(self):
        """run_terminal_regression_guards must return overall_safe=True on the real codebase."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        report = run_terminal_regression_guards(project_root=PROJECT_ROOT)
        assert report.overall_safe, (
            "Terminal regression guards detected architecture errors on the current codebase.  "
            "Errors: " + str([f.message for f in report.findings if f.severity == "error"])
        )

    def test_all_five_guards_run(self):
        """All five guard names must appear in guards_run."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        report = run_terminal_regression_guards(project_root=PROJECT_ROOT)
        expected = {
            "V4_HOT_PATH_ISOLATION",
            "V6_HOT_PATH_ISOLATION",
            "L1_L2_L3_ROUTER_FUSION",
            "COMPLETION_TRUTH_BACKBONE",
            "LAYER_DECLARATIONS_CONVERGENCE",
        }
        assert expected.issubset(set(report.guards_run)), (
            f"Expected all five guards in guards_run.  Got: {report.guards_run}"
        )

    def test_to_dict_serialisable(self):
        """The report's to_dict must be JSON-serialisable."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        report = run_terminal_regression_guards(project_root=PROJECT_ROOT)
        d = report.to_dict()
        json.dumps(d)

    def test_v4_regression_snapshot_produces_not_safe(self):
        """Providing a V4-as-per-request-gate snapshot produces overall_safe=False."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}
        ]
        report = run_terminal_regression_guards(
            project_root=PROJECT_ROOT,
            layer_snapshots=bad_snapshots,
        )
        assert not report.overall_safe, (
            "Expected overall_safe=False when V4 regression snapshot provided"
        )
        assert report.error_count >= 1

    def test_v6_regression_snapshot_produces_not_safe(self):
        """Providing a V6-as-per-request-gate snapshot produces overall_safe=False."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "startup_release_integrity", "is_per_request_gate": True}
        ]
        report = run_terminal_regression_guards(
            project_root=PROJECT_ROOT,
            layer_snapshots=bad_snapshots,
        )
        assert not report.overall_safe

    def test_l1_l2_l3_shadow_stack_regression_snapshot_produces_not_safe(self):
        """Providing an L1/L2/L3-as-shadow-stack snapshot produces overall_safe=False."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "router_cognitive_authority", "is_shadow_stack": True}
        ]
        report = run_terminal_regression_guards(
            project_root=PROJECT_ROOT,
            layer_snapshots=bad_snapshots,
        )
        assert not report.overall_safe

    def test_completion_optional_regression_snapshot_produces_not_safe(self):
        """Providing a completion-truth-as-optional snapshot produces overall_safe=False."""
        from core.terminal_architecture_regression_guards import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "completion_truth_backbone", "is_optional_signaling": True}
        ]
        report = run_terminal_regression_guards(
            project_root=PROJECT_ROOT,
            layer_snapshots=bad_snapshots,
        )
        assert not report.overall_safe


# ===========================================================================
# 10. Integration with architecture_invariants.run_consolidation_invariants
# ===========================================================================


class TestConsolidationIntegration:
    def test_terminal_regression_guards_in_checks_run(self):
        """run_consolidation_invariants must include TERMINAL_REGRESSION_GUARDS."""
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        report = run_consolidation_invariants()
        assert "TERMINAL_REGRESSION_GUARDS" in report.checks_run, (
            "run_consolidation_invariants must include TERMINAL_REGRESSION_GUARDS in checks_run"
        )

    def test_check_terminal_regression_guards_importable(self):
        """check_terminal_regression_guards must be importable and callable."""
        from tools.architecture.architecture_invariants import check_terminal_regression_guards
        assert callable(check_terminal_regression_guards)

    def test_clean_system_consolidation_remains_consistent(self):
        """Adding terminal guards must not break run_consolidation_invariants on clean system."""
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        report = run_consolidation_invariants()
        assert report.overall_consistent, (
            "run_consolidation_invariants should be overall_consistent on the clean codebase.  "
            "Errors: " + str([f.message for f in report.findings if f.severity == "error"])
        )

    def test_bad_v4_snapshot_makes_consolidation_not_consistent(self):
        """Passing a V4-as-per-request-gate snapshot makes run_consolidation_invariants fail."""
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        bad_snapshots = [
            {"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}
        ]
        report = run_consolidation_invariants(layer_snapshots=bad_snapshots)
        assert not report.overall_consistent

    def test_check_terminal_regression_clean_returns_no_errors(self):
        """check_terminal_regression_guards alone returns no errors on clean system."""
        from tools.architecture.architecture_invariants import check_terminal_regression_guards
        findings = check_terminal_regression_guards()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            "check_terminal_regression_guards should return no errors on clean system.  "
            "Errors: " + str([f.message for f in errors])
        )

    def test_terminal_guards_present_in_all_exported(self):
        """check_terminal_regression_guards must be in __all__ of architecture_invariants."""
        from tools.architecture import architecture_invariants
        assert "check_terminal_regression_guards" in architecture_invariants.__all__


# ===========================================================================
# 11. Module __all__ completeness
# ===========================================================================


class TestAllSymbolsImportable:
    def test_all_symbols_importable(self):
        """All symbols listed in __all__ must be importable."""
        from core import terminal_architecture_regression_guards as targ
        for name in targ.__all__:
            assert hasattr(targ, name), (
                f"Symbol '{name}' listed in __all__ but not present in module"
            )
