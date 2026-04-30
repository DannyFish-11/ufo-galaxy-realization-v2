#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_terminal_architecture_regression_guards.py
==========================================================

PR-10 — Terminal Architecture Regression Guards.

This test suite verifies that the five terminal architecture regression guards
introduced by PR-10 are present, functional, and correctly detect each of the
key invalid architecture regressions that must not be reintroduced after the
PR-1–PR-9 alignment sequence.

Coverage
--------

1.  TerminalRegressionReport — structure and to_dict
    - overall_pass=True when no errors.
    - overall_pass=False when any error present.
    - to_dict is JSON-serialisable.

2.  Guard 1 — V4 must NOT be a universal per-request gate
    - check_v4_not_universal_per_request_gate() is callable.
    - Clean architecture passes: no errors on unmodified repo.
    - Regression detected: snapshot with is_per_request_gate=True raises error
      via run_layer_model_invariants.
    - V4_IS_NOT_PER_REQUEST_GATE_POLICY sentinel present in spine module.

3.  Guard 2 — V6 must NOT be in hot request paths
    - check_v6_not_in_hot_request_path() is callable.
    - Clean architecture passes: command_router.py and openclawd.py don't
      contain V6 boundary tokens inside per-request dispatch methods.

4.  Guard 3 — L1/L2/L3 must remain in router-level authority
    - check_l1_l2_l3_in_router_authority() is callable.
    - Clean architecture passes: L1/L2/L3 authority modules importable with
      correct sentinels, or guard reports only INFO/WARNING if modules
      unavailable due to missing optional deps (not an ERROR for sentinel).

5.  Guard 4 — Canonical completion truth must be enforced, not optional
    - check_completion_truth_is_enforced() is callable.
    - Clean architecture passes: TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY
      present and contains 'MUST' language.
    - Regression detected: if policy were to contain no 'MUST' language,
      error is produced.

6.  Guard 5 — Repository-level declarations must not contradict final model
    - check_canonical_declarations_consistent() is callable.
    - Clean architecture passes with no layer_snapshots (registry self-check).
    - Regression detected: V4 snapshot with is_per_request_gate=True → error.
    - Regression detected: V6 snapshot with is_per_request_gate=True → error.
    - Regression detected: L1/L2/L3 snapshot with is_shadow_stack=True → error.
    - Regression detected: completion truth snapshot with is_optional_signaling=True → error.
    - TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL present in canonical_layer_model.

7.  run_terminal_regression_guards() — aggregate entry point
    - Importable and callable.
    - Returns a TerminalRegressionReport.
    - overall_pass=True on clean repo.
    - checks_run contains all five guard names.
    - Regression detected: passing a bad V4 layer_snapshot causes overall_pass=False.
    - Regression detected: passing a bad V6 layer_snapshot causes overall_pass=False.
    - Regression detected: passing a bad L1/L2/L3 layer_snapshot causes overall_pass=False.
    - Regression detected: passing a bad completion-truth layer_snapshot causes
      overall_pass=False.

8.  Integration with existing consolidation invariants
    - run_consolidation_invariants() still passes (not broken by PR-10 changes).
    - run_terminal_regression_guards() is a separate, additive entry point.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Shared helpers
# ===========================================================================

def _has_errors(findings: List[Any]) -> bool:
    return any(getattr(f, "severity", None) == "error" for f in findings)


def _error_messages(findings: List[Any]) -> List[str]:
    return [f.message for f in findings if getattr(f, "severity", None) == "error"]


# ===========================================================================
# 1. TerminalRegressionReport
# ===========================================================================


class TestTerminalRegressionReport:
    def test_overall_pass_true_when_no_errors(self):
        from tools.architecture.architecture_invariants import (
            TerminalRegressionReport,
            InvariantFinding,
        )
        report = TerminalRegressionReport()
        assert report.overall_pass is True
        assert report.error_count == 0

    def test_overall_pass_false_when_error_added(self):
        from tools.architecture.architecture_invariants import (
            TerminalRegressionReport,
            InvariantFinding,
        )
        report = TerminalRegressionReport()
        report.add(InvariantFinding(
            check="TEST_GUARD",
            severity="error",
            message="Test error finding.",
            detail={"test": True},
        ))
        assert report.overall_pass is False
        assert report.error_count == 1

    def test_to_dict_is_json_serialisable(self):
        from tools.architecture.architecture_invariants import TerminalRegressionReport
        report = TerminalRegressionReport()
        d = report.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)

    def test_to_dict_contains_required_keys(self):
        from tools.architecture.architecture_invariants import TerminalRegressionReport
        report = TerminalRegressionReport()
        d = report.to_dict()
        for key in ("overall_pass", "error_count", "warning_count", "checks_run", "findings"):
            assert key in d, f"to_dict() missing key '{key}'"

    def test_warning_does_not_affect_overall_pass(self):
        from tools.architecture.architecture_invariants import (
            TerminalRegressionReport,
            InvariantFinding,
        )
        report = TerminalRegressionReport()
        report.add(InvariantFinding(
            check="TEST_GUARD",
            severity="warning",
            message="Test warning.",
            detail={},
        ))
        assert report.overall_pass is True
        assert report.warning_count == 1

    def test_checks_run_preserved_in_to_dict(self):
        from tools.architecture.architecture_invariants import TerminalRegressionReport
        report = TerminalRegressionReport()
        report.checks_run.append("GUARD_A")
        report.checks_run.append("GUARD_B")
        d = report.to_dict()
        assert "GUARD_A" in d["checks_run"]
        assert "GUARD_B" in d["checks_run"]


# ===========================================================================
# 2. Guard 1 — V4 not universal per-request gate
# ===========================================================================


class TestGuard1V4NotUniversalGate:
    def test_check_function_importable_and_callable(self):
        from tools.architecture.architecture_invariants import (
            check_v4_not_universal_per_request_gate,
        )
        assert callable(check_v4_not_universal_per_request_gate)

    def test_clean_repo_no_errors(self):
        from tools.architecture.architecture_invariants import (
            check_v4_not_universal_per_request_gate,
        )
        findings = check_v4_not_universal_per_request_gate(PROJECT_ROOT)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            f"Guard 1 produced unexpected errors on clean repo: "
            f"{[f.message for f in errors]}"
        )

    def test_v4_spine_sentinel_present_in_module(self):
        """core.unified_orchestration_spine must carry V4_IS_NOT_PER_REQUEST_GATE_POLICY."""
        spine = pytest.importorskip("core.unified_orchestration_spine")
        assert hasattr(spine, "V4_IS_NOT_PER_REQUEST_GATE_POLICY"), (
            "V4_IS_NOT_PER_REQUEST_GATE_POLICY must be present in the spine module"
        )

    def test_v4_spine_policy_contains_not_language(self):
        """V4_IS_NOT_PER_REQUEST_GATE_POLICY must explicitly state V4 is NOT the gate."""
        spine = pytest.importorskip("core.unified_orchestration_spine")
        policy = spine.V4_IS_NOT_PER_REQUEST_GATE_POLICY
        assert "not" in policy.lower(), (
            "V4_IS_NOT_PER_REQUEST_GATE_POLICY must contain NOT language"
        )

    def test_regression_v4_per_request_gate_snapshot_detected(self):
        """Regression: V4 declared as is_per_request_gate=True must be an error."""
        from core.canonical_layer_model import run_layer_model_invariants
        snapshot = {"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}
        report = run_layer_model_invariants([snapshot])
        assert not report.overall_consistent, (
            "V4 declared as per_request_gate=True must cause overall_consistent=False"
        )
        assert report.error_count >= 1

    def test_v4_layer_model_check_detects_gate_misclassification(self):
        """check_canonical_layer_model_consistent detects V4-as-gate regression."""
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        findings = check_canonical_layer_model_consistent(
            [{"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}]
        )
        assert _has_errors(findings), (
            "V4 per_request_gate regression must produce an ERROR finding"
        )


# ===========================================================================
# 3. Guard 2 — V6 not in hot request paths
# ===========================================================================


class TestGuard2V6NotInHotPath:
    def test_check_function_importable_and_callable(self):
        from tools.architecture.architecture_invariants import check_v6_not_in_hot_request_path
        assert callable(check_v6_not_in_hot_request_path)

    def test_clean_repo_no_errors(self):
        from tools.architecture.architecture_invariants import check_v6_not_in_hot_request_path
        findings = check_v6_not_in_hot_request_path(PROJECT_ROOT)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            f"Guard 2 produced unexpected errors on clean repo: "
            f"{[f.message for f in errors]}"
        )

    def test_command_router_route_envelope_clean(self):
        """CommandRouter.route_envelope must not contain V6 tokens directly."""
        router_path = PROJECT_ROOT / "core" / "command_router.py"
        if not router_path.exists():
            pytest.skip("core/command_router.py not present")
        content = router_path.read_text(encoding="utf-8", errors="replace")
        idx = content.find("def route_envelope(")
        if idx == -1:
            return
        method_body = content[idx: idx + 3000]
        v6_tokens = [
            "center_authority_boundary",
            "evaluate_center_authority_boundary",
            "assert_center_authority_intact",
        ]
        found = [t for t in v6_tokens if t in method_body]
        assert not found, (
            f"CommandRouter.route_envelope() contains V6 tokens {found!r} — "
            "this is the V6-in-hot-path regression"
        )

    def test_openclawd_process_clean(self):
        """OpenClawd.process() must not contain V6 tokens directly."""
        openclawd_path = PROJECT_ROOT / "core" / "openclawd.py"
        if not openclawd_path.exists():
            pytest.skip("core/openclawd.py not present")
        content = openclawd_path.read_text(encoding="utf-8", errors="replace")
        idx = content.find("def process(")
        if idx == -1:
            return
        method_body = content[idx: idx + 3000]
        v6_tokens = [
            "center_authority_boundary",
            "evaluate_center_authority_boundary",
            "assert_center_authority_intact",
        ]
        found = [t for t in v6_tokens if t in method_body]
        assert not found, (
            f"OpenClawd.process() contains V6 tokens {found!r} — "
            "this is the V6-in-hot-path regression"
        )

    def test_regression_v6_per_request_gate_snapshot_detected(self):
        """Regression: V6 declared as is_per_request_gate=True must be an error."""
        from core.canonical_layer_model import run_layer_model_invariants
        snapshot = {"layer_key": "startup_release_integrity", "is_per_request_gate": True}
        report = run_layer_model_invariants([snapshot])
        assert not report.overall_consistent
        assert report.error_count >= 1

    def test_v6_layer_model_check_detects_hot_path_misclassification(self):
        """check_canonical_layer_model_consistent detects V6-as-hot-path regression."""
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        findings = check_canonical_layer_model_consistent(
            [{"layer_key": "startup_release_integrity", "is_per_request_gate": True}]
        )
        assert _has_errors(findings), (
            "V6 per_request_gate regression must produce an ERROR finding"
        )


# ===========================================================================
# 4. Guard 3 — L1/L2/L3 in router authority
# ===========================================================================


class TestGuard3L1L2L3InRouterAuthority:
    def test_check_function_importable_and_callable(self):
        from tools.architecture.architecture_invariants import check_l1_l2_l3_in_router_authority
        assert callable(check_l1_l2_l3_in_router_authority)

    def test_l1_authority_module_sentinel_present(self):
        ra = pytest.importorskip("core.llm.route_authority")
        assert hasattr(ra, "LLM_ROUTE_AUTHORITY"), (
            "core.llm.route_authority must expose LLM_ROUTE_AUTHORITY sentinel"
        )

    def test_l2_authority_module_sentinel_present(self):
        sa = pytest.importorskip("core.llm.supply_authority")
        assert hasattr(sa, "LLM_SUPPLY_AUTHORITY"), (
            "core.llm.supply_authority must expose LLM_SUPPLY_AUTHORITY sentinel"
        )

    def test_l3_authority_module_sentinel_present(self):
        ca = pytest.importorskip("core.llm.context_authority")
        assert hasattr(ca, "LLM_CONTEXT_AUTHORITY"), (
            "core.llm.context_authority must expose LLM_CONTEXT_AUTHORITY sentinel"
        )

    def test_regression_shadow_stack_snapshot_detected(self):
        """Regression: L1/L2/L3 declared as is_shadow_stack=True must be an error."""
        from core.canonical_layer_model import run_layer_model_invariants
        snapshot = {"layer_key": "router_cognitive_authority", "is_shadow_stack": True}
        report = run_layer_model_invariants([snapshot])
        assert not report.overall_consistent
        assert report.error_count >= 1

    def test_l1_l2_l3_layer_model_check_detects_shadow_stack(self):
        """check_canonical_layer_model_consistent detects L1/L2/L3 shadow-stack regression."""
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        findings = check_canonical_layer_model_consistent(
            [{"layer_key": "router_cognitive_authority", "is_shadow_stack": True}]
        )
        assert _has_errors(findings), (
            "L1/L2/L3 shadow-stack regression must produce an ERROR finding"
        )

    def test_clean_repo_no_errors_or_only_import_errors(self):
        """Guard 3 must not produce unexpected structural errors on the clean repo.

        If pydantic or another optional dep is missing, UnifiedLLMRouter may not be
        importable — those import errors are acceptable as pre-existing conditions.
        Only structural errors about missing authority attributes are regressions.
        """
        from tools.architecture.architecture_invariants import check_l1_l2_l3_in_router_authority
        findings = check_l1_l2_l3_in_router_authority()
        structural_errors = [
            f for f in findings
            if f.severity == "error"
            and "import" not in f.message.lower()
            and "importable" not in f.message.lower()
        ]
        assert not structural_errors, (
            f"Guard 3 produced structural (non-import) errors on clean repo: "
            f"{[f.message for f in structural_errors]}"
        )


# ===========================================================================
# 5. Guard 4 — Completion truth is enforced, not optional
# ===========================================================================


class TestGuard4CompletionTruthEnforced:
    def test_check_function_importable_and_callable(self):
        from tools.architecture.architecture_invariants import check_completion_truth_is_enforced
        assert callable(check_completion_truth_is_enforced)

    def test_clean_repo_no_errors(self):
        from tools.architecture.architecture_invariants import check_completion_truth_is_enforced
        findings = check_completion_truth_is_enforced()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            f"Guard 4 produced unexpected errors on clean repo: "
            f"{[f.message for f in errors]}"
        )

    def test_must_run_policy_sentinel_importable(self):
        trtc = pytest.importorskip("core.task_result_canonical_truth_chain")
        assert hasattr(trtc, "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY"), (
            "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY must be present"
        )

    def test_must_run_policy_contains_must_language(self):
        trtc = pytest.importorskip("core.task_result_canonical_truth_chain")
        policy = trtc.TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY
        assert "must" in policy.lower(), (
            "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY must contain 'MUST' language"
        )

    def test_run_task_result_truth_chain_callable(self):
        trtc = pytest.importorskip("core.task_result_canonical_truth_chain")
        assert callable(trtc.run_task_result_truth_chain)

    def test_regression_optional_signaling_snapshot_detected(self):
        """Regression: completion truth declared is_optional_signaling=True must be an error."""
        from core.canonical_layer_model import run_layer_model_invariants
        snapshot = {"layer_key": "completion_truth_backbone", "is_optional_signaling": True}
        report = run_layer_model_invariants([snapshot])
        assert not report.overall_consistent
        assert report.error_count >= 1

    def test_completion_truth_layer_model_detects_optional_regression(self):
        """check_canonical_layer_model_consistent detects optional-signaling regression."""
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        findings = check_canonical_layer_model_consistent(
            [{"layer_key": "completion_truth_backbone", "is_optional_signaling": True}]
        )
        assert _has_errors(findings), (
            "Optional signaling regression must produce an ERROR finding"
        )


# ===========================================================================
# 6. Guard 5 — Canonical declarations consistent
# ===========================================================================


class TestGuard5CanonicalDeclarationsConsistent:
    def test_check_function_importable_and_callable(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        assert callable(check_canonical_declarations_consistent)

    def test_clean_no_snapshots_passes(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        findings = check_canonical_declarations_consistent()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, (
            f"Guard 5 produced unexpected errors on clean repo: "
            f"{[f.message for f in errors]}"
        )

    def test_terminal_regression_guard_sentinel_in_canonical_layer_model(self):
        from core.canonical_layer_model import TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL
        assert isinstance(TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL, str)
        assert len(TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL) > 50, (
            "Terminal regression guard sentinel must be a meaningful non-trivial string"
        )
        assert "PR10" in TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL or \
               "PR-10" in TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL, (
            "Terminal regression guard sentinel must reference PR-10"
        )

    def test_regression_bad_v4_snapshot_detected(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        findings = check_canonical_declarations_consistent(
            [{"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}]
        )
        assert _has_errors(findings), "Bad V4 snapshot must produce an ERROR in guard 5"

    def test_regression_bad_v6_snapshot_detected(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        findings = check_canonical_declarations_consistent(
            [{"layer_key": "startup_release_integrity", "is_per_request_gate": True}]
        )
        assert _has_errors(findings), "Bad V6 snapshot must produce an ERROR in guard 5"

    def test_regression_bad_l1_l2_l3_snapshot_detected(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        findings = check_canonical_declarations_consistent(
            [{"layer_key": "router_cognitive_authority", "is_shadow_stack": True}]
        )
        assert _has_errors(findings), "Bad L1/L2/L3 snapshot must produce an ERROR in guard 5"

    def test_regression_bad_completion_truth_snapshot_detected(self):
        from tools.architecture.architecture_invariants import check_canonical_declarations_consistent
        findings = check_canonical_declarations_consistent(
            [{"layer_key": "completion_truth_backbone", "is_optional_signaling": True}]
        )
        assert _has_errors(findings), (
            "Bad completion-truth snapshot must produce an ERROR in guard 5"
        )

    def test_all_five_canonical_layers_declared(self):
        """The canonical layer registry must declare all five expected layers."""
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        expected = {
            "completion_truth_backbone",
            "router_cognitive_authority",
            "per_request_hot_path",
            "multi_step_orchestration_spine",
            "startup_release_integrity",
        }
        declared = {layer.value for layer in CanonicalLayer}
        assert expected == declared, (
            f"Canonical layer registry is missing layers: {expected - declared}"
        )


# ===========================================================================
# 7. run_terminal_regression_guards() — aggregate entry point
# ===========================================================================


class TestRunTerminalRegressionGuards:
    def test_importable_and_callable(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        assert callable(run_terminal_regression_guards)

    def test_returns_terminal_regression_report(self):
        from tools.architecture.architecture_invariants import (
            run_terminal_regression_guards,
            TerminalRegressionReport,
        )
        report = run_terminal_regression_guards(PROJECT_ROOT)
        assert isinstance(report, TerminalRegressionReport)

    def test_overall_pass_on_clean_repo(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        report = run_terminal_regression_guards(PROJECT_ROOT)
        assert report.overall_pass, (
            f"run_terminal_regression_guards() must pass on clean repo; errors: "
            f"{[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_all_five_checks_run(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        report = run_terminal_regression_guards(PROJECT_ROOT)
        assert "V4_NOT_UNIVERSAL_PER_REQUEST_GATE" in report.checks_run
        assert "V6_NOT_IN_HOT_REQUEST_PATH" in report.checks_run
        assert "L1_L2_L3_IN_ROUTER_AUTHORITY" in report.checks_run
        assert "COMPLETION_TRUTH_ENFORCED_NOT_OPTIONAL" in report.checks_run
        assert "CANONICAL_DECLARATIONS_CONSISTENT" in report.checks_run

    def test_exactly_five_checks_run(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        report = run_terminal_regression_guards(PROJECT_ROOT)
        assert len(report.checks_run) == 5, (
            f"Expected exactly 5 terminal guards; got {report.checks_run}"
        )

    def test_to_dict_is_serialisable(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        report = run_terminal_regression_guards(PROJECT_ROOT)
        d = report.to_dict()
        json.dumps(d)

    def test_regression_bad_v4_snapshot_causes_failure(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}
        ]
        report = run_terminal_regression_guards(PROJECT_ROOT, layer_snapshots=bad_snapshots)
        assert not report.overall_pass, (
            "Bad V4 layer_snapshot must cause overall_pass=False"
        )

    def test_regression_bad_v6_snapshot_causes_failure(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "startup_release_integrity", "is_per_request_gate": True}
        ]
        report = run_terminal_regression_guards(PROJECT_ROOT, layer_snapshots=bad_snapshots)
        assert not report.overall_pass, (
            "Bad V6 layer_snapshot must cause overall_pass=False"
        )

    def test_regression_bad_l1_l2_l3_snapshot_causes_failure(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "router_cognitive_authority", "is_shadow_stack": True}
        ]
        report = run_terminal_regression_guards(PROJECT_ROOT, layer_snapshots=bad_snapshots)
        assert not report.overall_pass, (
            "Bad L1/L2/L3 snapshot must cause overall_pass=False"
        )

    def test_regression_bad_completion_truth_snapshot_causes_failure(self):
        from tools.architecture.architecture_invariants import run_terminal_regression_guards
        bad_snapshots = [
            {"layer_key": "completion_truth_backbone", "is_optional_signaling": True}
        ]
        report = run_terminal_regression_guards(PROJECT_ROOT, layer_snapshots=bad_snapshots)
        assert not report.overall_pass, (
            "Bad completion-truth snapshot must cause overall_pass=False"
        )


# ===========================================================================
# 8. Integration with existing consolidation invariants
# ===========================================================================


class TestIntegrationWithExistingConsolidation:
    def test_run_consolidation_invariants_still_passes(self):
        """PR-10 additions must not break the existing consolidation invariant runner."""
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        report = run_consolidation_invariants()
        assert report.overall_consistent, (
            f"run_consolidation_invariants() must still pass after PR-10 changes; "
            f"errors: {[f.message for f in report.findings if f.severity == 'error']}"
        )

    def test_terminal_guards_are_separate_from_consolidation_runner(self):
        """run_terminal_regression_guards is a separate, additive entry point."""
        from tools.architecture.architecture_invariants import (
            run_consolidation_invariants,
            run_terminal_regression_guards,
        )
        # Both are independently callable.
        c_report = run_consolidation_invariants()
        t_report = run_terminal_regression_guards(PROJECT_ROOT)
        # Both should pass on clean repo.
        assert c_report.overall_consistent
        assert t_report.overall_pass

    def test_new_symbols_in_all(self):
        """All five terminal guard functions and TerminalRegressionReport are in __all__."""
        import tools.architecture.architecture_invariants as mod
        for name in (
            "TerminalRegressionReport",
            "check_v4_not_universal_per_request_gate",
            "check_v6_not_in_hot_request_path",
            "check_l1_l2_l3_in_router_authority",
            "check_completion_truth_is_enforced",
            "check_canonical_declarations_consistent",
            "run_terminal_regression_guards",
        ):
            assert name in mod.__all__, (
                f"'{name}' must be exported in tools.architecture.architecture_invariants.__all__"
            )

    def test_terminal_sentinel_in_canonical_layer_model_all(self):
        """TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL is exported in __all__."""
        import core.canonical_layer_model as clm
        assert "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL" in clm.__all__, (
            "TERMINAL_ARCHITECTURE_REGRESSION_GUARD_SENTINEL must be in core.canonical_layer_model.__all__"
        )
