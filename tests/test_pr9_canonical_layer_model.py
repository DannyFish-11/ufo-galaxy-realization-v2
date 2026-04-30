"""
tests/test_pr9_canonical_layer_model.py
=========================================

PR-9: Canonical Runtime Layer Model — focused tests.

Validates that the normalized canonical layer model is internally consistent,
machine-checkable, and correctly classifies all five canonical runtime layers.

Coverage
--------
1.  CanonicalLayer enum — values, keys, completeness.
2.  CANONICAL_LAYER_REGISTRY — all five layers present, required fields.
3.  Layer declarations — canonical_modules, not_policies, hot-path, startup.
4.  NOT-policy sentinels — importable, non-empty strings.
5.  get_layer_declaration — returns correct declaration per layer.
6.  check_layer_model_consistent — valid snapshot passes, invalid fails.
7.  V4 invariant — V4 snapshot with is_per_request_gate=True is an error.
8.  V6 invariant — V6 snapshot with is_per_request_gate=True is an error.
9.  L1/L2/L3 invariant — router layer snapshot with is_shadow_stack=True is an error.
10. Completion truth invariant — completion backbone with is_optional_signaling=True is error.
11. run_layer_model_invariants — passes on clean snapshots, fails on bad ones.
12. Integration: run_consolidation_invariants includes layer model check (PR-9).
13. Architecture-facing modules agree on the same canonical layer model.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# 1. CanonicalLayer enum
# ===========================================================================

class TestCanonicalLayerEnum:
    def test_all_five_layers_defined(self):
        from core.canonical_layer_model import CanonicalLayer
        keys = {layer.value for layer in CanonicalLayer}
        assert "completion_truth_backbone" in keys
        assert "router_cognitive_authority" in keys
        assert "per_request_hot_path" in keys
        assert "multi_step_orchestration_spine" in keys
        assert "startup_release_integrity" in keys

    def test_exactly_five_layers(self):
        from core.canonical_layer_model import CanonicalLayer
        assert len(list(CanonicalLayer)) == 5

    def test_canonical_layer_keys_matches_enum(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_KEYS
        expected = frozenset(layer.value for layer in CanonicalLayer)
        assert CANONICAL_LAYER_KEYS == expected

    def test_layer_string_constants_match_enum(self):
        from core.canonical_layer_model import (
            CanonicalLayer,
            LAYER_COMPLETION_TRUTH_BACKBONE,
            LAYER_ROUTER_COGNITIVE_AUTHORITY,
            LAYER_PER_REQUEST_HOT_PATH,
            LAYER_MULTI_STEP_ORCHESTRATION_SPINE,
            LAYER_STARTUP_RELEASE_INTEGRITY,
        )
        assert CanonicalLayer.COMPLETION_TRUTH_BACKBONE.value == LAYER_COMPLETION_TRUTH_BACKBONE
        assert CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY.value == LAYER_ROUTER_COGNITIVE_AUTHORITY
        assert CanonicalLayer.PER_REQUEST_HOT_PATH.value == LAYER_PER_REQUEST_HOT_PATH
        assert CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE.value == LAYER_MULTI_STEP_ORCHESTRATION_SPINE
        assert CanonicalLayer.STARTUP_RELEASE_INTEGRITY.value == LAYER_STARTUP_RELEASE_INTEGRITY


# ===========================================================================
# 2. CANONICAL_LAYER_REGISTRY completeness
# ===========================================================================

class TestCanonicalLayerRegistry:
    def test_all_layers_in_registry(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        for layer in CanonicalLayer:
            assert layer in CANONICAL_LAYER_REGISTRY, \
                f"CanonicalLayer.{layer.name} missing from CANONICAL_LAYER_REGISTRY"

    def test_registry_entries_are_layer_declarations(self):
        from core.canonical_layer_model import (
            CanonicalLayer, CANONICAL_LAYER_REGISTRY, LayerDeclaration,
        )
        for layer in CanonicalLayer:
            assert isinstance(CANONICAL_LAYER_REGISTRY[layer], LayerDeclaration)

    def test_layer_declaration_has_required_fields(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        required = ("layer", "label", "version_tag", "scope", "canonical_modules", "not_policies")
        for layer in CanonicalLayer:
            decl = CANONICAL_LAYER_REGISTRY[layer]
            for attr in required:
                assert hasattr(decl, attr), \
                    f"LayerDeclaration for {layer.value} missing attribute '{attr}'"

    def test_all_canonical_modules_non_empty(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        for layer in CanonicalLayer:
            decl = CANONICAL_LAYER_REGISTRY[layer]
            assert len(decl.canonical_modules) > 0, \
                f"Layer '{layer.value}' must have at least one canonical_module"

    def test_to_dict_returns_serialisable_dict(self):
        import json
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        for layer in CanonicalLayer:
            decl = CANONICAL_LAYER_REGISTRY[layer]
            d = decl.to_dict()
            assert isinstance(d, dict)
            # Must be JSON-serialisable (no non-serialisable types).
            json.dumps(d)


# ===========================================================================
# 3. Layer declarations — hot-path and startup-only flags
# ===========================================================================

class TestLayerDeclarationFlags:
    def test_per_request_hot_path_is_hot_path(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        decl = CANONICAL_LAYER_REGISTRY[CanonicalLayer.PER_REQUEST_HOT_PATH]
        assert decl.is_hot_path is True

    def test_router_cognitive_authority_is_hot_path(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        decl = CANONICAL_LAYER_REGISTRY[CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY]
        assert decl.is_hot_path is True

    def test_v4_is_not_hot_path(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        decl = CANONICAL_LAYER_REGISTRY[CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE]
        assert decl.is_hot_path is False

    def test_v6_is_not_hot_path(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        decl = CANONICAL_LAYER_REGISTRY[CanonicalLayer.STARTUP_RELEASE_INTEGRITY]
        assert decl.is_hot_path is False

    def test_completion_truth_backbone_is_not_hot_path(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        decl = CANONICAL_LAYER_REGISTRY[CanonicalLayer.COMPLETION_TRUTH_BACKBONE]
        assert decl.is_hot_path is False

    def test_only_v6_is_startup_only(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        for layer in CanonicalLayer:
            decl = CANONICAL_LAYER_REGISTRY[layer]
            expected = layer == CanonicalLayer.STARTUP_RELEASE_INTEGRITY
            assert decl.is_startup_only == expected, \
                f"Layer '{layer.value}': expected is_startup_only={expected}, got {decl.is_startup_only}"


# ===========================================================================
# 4. NOT-policy sentinels
# ===========================================================================

class TestNotPolicySentinels:
    def test_v4_not_sentinel_importable_non_empty(self):
        from core.canonical_layer_model import V4_IS_NOT_PER_REQUEST_GATE
        assert isinstance(V4_IS_NOT_PER_REQUEST_GATE, str)
        assert len(V4_IS_NOT_PER_REQUEST_GATE) > 20

    def test_v6_not_sentinel_importable_non_empty(self):
        from core.canonical_layer_model import V6_IS_NOT_PER_REQUEST_GATE
        assert isinstance(V6_IS_NOT_PER_REQUEST_GATE, str)
        assert len(V6_IS_NOT_PER_REQUEST_GATE) > 20

    def test_l1_l2_l3_not_sentinel_importable_non_empty(self):
        from core.canonical_layer_model import L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK
        assert isinstance(L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK, str)
        assert len(L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK) > 20

    def test_completion_truth_not_sentinel_importable_non_empty(self):
        from core.canonical_layer_model import COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL
        assert isinstance(COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL, str)
        assert len(COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL) > 20

    def test_v4_sentinel_contains_expected_keywords(self):
        from core.canonical_layer_model import V4_IS_NOT_PER_REQUEST_GATE
        assert "V4" in V4_IS_NOT_PER_REQUEST_GATE or "per_request_gate" in V4_IS_NOT_PER_REQUEST_GATE.lower()
        assert "not" in V4_IS_NOT_PER_REQUEST_GATE.lower() or "NOT" in V4_IS_NOT_PER_REQUEST_GATE

    def test_v6_sentinel_contains_expected_keywords(self):
        from core.canonical_layer_model import V6_IS_NOT_PER_REQUEST_GATE
        assert "V6" in V6_IS_NOT_PER_REQUEST_GATE or "release" in V6_IS_NOT_PER_REQUEST_GATE.lower()
        assert "not" in V6_IS_NOT_PER_REQUEST_GATE.lower() or "NOT" in V6_IS_NOT_PER_REQUEST_GATE

    def test_boundary_layers_have_not_policies(self):
        from core.canonical_layer_model import CanonicalLayer, CANONICAL_LAYER_REGISTRY
        boundary_layers = {
            CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE,
            CanonicalLayer.STARTUP_RELEASE_INTEGRITY,
            CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY,
            CanonicalLayer.COMPLETION_TRUTH_BACKBONE,
        }
        for layer in boundary_layers:
            decl = CANONICAL_LAYER_REGISTRY[layer]
            assert len(decl.not_policies) > 0, \
                f"Layer '{layer.value}' should have at least one NOT-policy"


# ===========================================================================
# 5. get_layer_declaration
# ===========================================================================

class TestGetLayerDeclaration:
    def test_returns_correct_declaration_for_each_layer(self):
        from core.canonical_layer_model import (
            CanonicalLayer, CANONICAL_LAYER_REGISTRY, get_layer_declaration,
        )
        for layer in CanonicalLayer:
            decl = get_layer_declaration(layer)
            assert decl is CANONICAL_LAYER_REGISTRY[layer]

    def test_v4_declaration_has_version_tag_v4(self):
        from core.canonical_layer_model import CanonicalLayer, get_layer_declaration
        decl = get_layer_declaration(CanonicalLayer.MULTI_STEP_ORCHESTRATION_SPINE)
        assert "V4" in decl.version_tag

    def test_v6_declaration_has_version_tag_v6(self):
        from core.canonical_layer_model import CanonicalLayer, get_layer_declaration
        decl = get_layer_declaration(CanonicalLayer.STARTUP_RELEASE_INTEGRITY)
        assert "V6" in decl.version_tag

    def test_l1_l2_l3_declaration_has_expected_modules(self):
        from core.canonical_layer_model import CanonicalLayer, get_layer_declaration
        decl = get_layer_declaration(CanonicalLayer.ROUTER_COGNITIVE_AUTHORITY)
        modules_str = " ".join(decl.canonical_modules)
        assert "route_authority" in modules_str
        assert "supply_authority" in modules_str
        assert "context_authority" in modules_str


# ===========================================================================
# 6. check_layer_model_consistent — valid snapshots pass
# ===========================================================================

class TestCheckLayerModelConsistentValid:
    @pytest.mark.parametrize("layer_key", [
        "completion_truth_backbone",
        "router_cognitive_authority",
        "per_request_hot_path",
        "multi_step_orchestration_spine",
        "startup_release_integrity",
    ])
    def test_valid_snapshot_has_no_errors(self, layer_key):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {"layer_key": layer_key}
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors, f"Unexpected errors for valid snapshot {layer_key}: {errors}"

    def test_hot_path_snapshot_consistent_with_model(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "per_request_hot_path",
            "is_hot_path": True,
            "is_startup_only": False,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_v6_snapshot_consistent_with_model(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "startup_release_integrity",
            "is_hot_path": False,
            "is_startup_only": True,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 7. V4 invariant — is_per_request_gate=True must be an error
# ===========================================================================

class TestV4Invariant:
    def test_v4_per_request_gate_true_is_error(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": True,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error when V4 is declared as per_request_gate=True"
        assert any("V4_IS_NOT_PER_REQUEST_GATE" in e.detail.get("violation", "")
                   for e in errors)

    def test_v4_per_request_gate_false_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "multi_step_orchestration_spine",
            "is_per_request_gate": False,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_v4_per_request_gate_absent_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {"layer_key": "multi_step_orchestration_spine"}
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 8. V6 invariant — is_per_request_gate=True must be an error
# ===========================================================================

class TestV6Invariant:
    def test_v6_per_request_gate_true_is_error(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "startup_release_integrity",
            "is_per_request_gate": True,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error when V6 is declared as per_request_gate=True"
        assert any("V6_IS_NOT_PER_REQUEST_GATE" in e.detail.get("violation", "")
                   for e in errors)

    def test_v6_per_request_gate_false_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "startup_release_integrity",
            "is_per_request_gate": False,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 9. L1/L2/L3 invariant — is_shadow_stack=True must be an error
# ===========================================================================

class TestL1L2L3Invariant:
    def test_router_layer_shadow_stack_true_is_error(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "router_cognitive_authority",
            "is_shadow_stack": True,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error when L1/L2/L3 is declared as is_shadow_stack=True"
        assert any("L1_L2_L3_BELONGS_TO_ROUTER_LAYER_NOT_SHADOW_STACK" in e.detail.get("violation", "")
                   for e in errors)

    def test_router_layer_shadow_stack_false_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "router_cognitive_authority",
            "is_shadow_stack": False,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_router_layer_shadow_stack_absent_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {"layer_key": "router_cognitive_authority"}
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 10. Completion truth invariant — is_optional_signaling=True must be an error
# ===========================================================================

class TestCompletionTruthInvariant:
    def test_completion_truth_optional_signaling_true_is_error(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "completion_truth_backbone",
            "is_optional_signaling": True,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert errors, "Expected error when completion truth is declared as optional signaling"
        assert any("COMPLETION_TRUTH_IS_ENFORCED_NOT_OPTIONAL" in e.detail.get("violation", "")
                   for e in errors)

    def test_completion_truth_optional_signaling_false_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {
            "layer_key": "completion_truth_backbone",
            "is_optional_signaling": False,
        }
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors

    def test_completion_truth_optional_signaling_absent_is_ok(self):
        from core.canonical_layer_model import check_layer_model_consistent
        snapshot = {"layer_key": "completion_truth_backbone"}
        findings = check_layer_model_consistent(snapshot)
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 11. run_layer_model_invariants
# ===========================================================================

class TestRunLayerModelInvariants:
    def test_no_snapshots_passes(self):
        from core.canonical_layer_model import run_layer_model_invariants
        report = run_layer_model_invariants()
        assert report.overall_consistent, \
            f"Expected consistent report; errors: {[f.message for f in report.findings if f.severity == 'error']}"

    def test_valid_snapshots_pass(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [
            {"layer_key": "per_request_hot_path"},
            {"layer_key": "multi_step_orchestration_spine"},
            {"layer_key": "startup_release_integrity"},
        ]
        report = run_layer_model_invariants(snapshots)
        assert report.overall_consistent

    def test_invalid_v4_snapshot_fails(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [{"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}]
        report = run_layer_model_invariants(snapshots)
        assert not report.overall_consistent
        assert report.error_count >= 1

    def test_invalid_v6_snapshot_fails(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [{"layer_key": "startup_release_integrity", "is_per_request_gate": True}]
        report = run_layer_model_invariants(snapshots)
        assert not report.overall_consistent

    def test_invalid_l1_l2_l3_snapshot_fails(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [{"layer_key": "router_cognitive_authority", "is_shadow_stack": True}]
        report = run_layer_model_invariants(snapshots)
        assert not report.overall_consistent

    def test_invalid_completion_truth_snapshot_fails(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [{"layer_key": "completion_truth_backbone", "is_optional_signaling": True}]
        report = run_layer_model_invariants(snapshots)
        assert not report.overall_consistent

    def test_unknown_layer_key_fails(self):
        from core.canonical_layer_model import run_layer_model_invariants
        snapshots = [{"layer_key": "nonexistent_layer_xyz"}]
        report = run_layer_model_invariants(snapshots)
        assert not report.overall_consistent

    def test_report_to_dict_is_serialisable(self):
        import json
        from core.canonical_layer_model import run_layer_model_invariants
        report = run_layer_model_invariants()
        d = report.to_dict()
        json.dumps(d)

    def test_report_checks_run_contains_registry_check(self):
        from core.canonical_layer_model import run_layer_model_invariants
        report = run_layer_model_invariants()
        assert "LAYER_REGISTRY_SELF_CONSISTENT" in report.checks_run


# ===========================================================================
# 12. Integration: run_consolidation_invariants includes layer model check
# ===========================================================================

class TestConsolidationInvariantsIncludesLayerModel:
    def test_run_consolidation_includes_layer_model_check(self):
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        report = run_consolidation_invariants()
        assert "CANONICAL_LAYER_MODEL_CONSISTENT" in report.checks_run

    def test_run_consolidation_consistent_by_default(self):
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        report = run_consolidation_invariants()
        assert report.overall_consistent, \
            f"run_consolidation_invariants() should be consistent; errors: " \
            f"{[f.message for f in report.findings if f.severity == 'error']}"

    def test_run_consolidation_with_bad_v4_snapshot_fails(self):
        from tools.architecture.architecture_invariants import run_consolidation_invariants
        bad_snapshots = [{"layer_key": "multi_step_orchestration_spine", "is_per_request_gate": True}]
        report = run_consolidation_invariants(layer_snapshots=bad_snapshots)
        assert not report.overall_consistent

    def test_check_canonical_layer_model_consistent_importable(self):
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        assert callable(check_canonical_layer_model_consistent)

    def test_check_canonical_layer_model_consistent_clean_returns_no_errors(self):
        from tools.architecture.architecture_invariants import check_canonical_layer_model_consistent
        findings = check_canonical_layer_model_consistent()
        errors = [f for f in findings if f.severity == "error"]
        assert not errors


# ===========================================================================
# 13. Architecture-facing modules agree on the canonical layer model
# ===========================================================================

class TestArchitectureModulesAgreeOnLayerModel:
    """Validate that key architecture-facing modules are importable and expose
    the sentinels / policies that the canonical layer model relies on."""

    def test_unified_orchestration_spine_importable(self):
        import core.unified_orchestration_spine as spine
        assert hasattr(spine, "UNIFIED_ORCHESTRATION_SPINE_AUTHORITY")

    def test_v4_not_per_request_gate_policy_present_in_spine(self):
        import core.unified_orchestration_spine as spine
        assert hasattr(spine, "V4_IS_NOT_PER_REQUEST_GATE_POLICY")
        assert "NOT" in spine.V4_IS_NOT_PER_REQUEST_GATE_POLICY.upper() or \
               "not" in spine.V4_IS_NOT_PER_REQUEST_GATE_POLICY

    def test_release_blocking_gate_importable(self):
        import core.release_blocking_gate as gate
        assert hasattr(gate, "RELEASE_BLOCKING_GATE_AUTHORITY")

    def test_llm_route_authority_importable(self):
        ra = pytest.importorskip("core.llm.route_authority")
        assert hasattr(ra, "LLM_ROUTE_AUTHORITY")

    def test_llm_supply_authority_importable(self):
        sa = pytest.importorskip("core.llm.supply_authority")
        assert hasattr(sa, "LLM_SUPPLY_AUTHORITY")

    def test_llm_context_authority_importable(self):
        ca = pytest.importorskip("core.llm.context_authority")
        assert hasattr(ca, "LLM_CONTEXT_AUTHORITY")

    def test_unified_llm_router_importable(self):
        router = pytest.importorskip("core.unified.llm_router")
        assert hasattr(router, "UNIFIED_LLM_ROUTER_AUTHORITY")

    def test_canonical_completion_ingress_importable(self):
        import core.canonical_completion_ingress as cci
        assert hasattr(cci, "CANONICAL_COMPLETION_INGRESS_SENTINEL")

    def test_canonical_layer_model_authority_sentinel_present(self):
        from core.canonical_layer_model import CANONICAL_LAYER_MODEL_AUTHORITY
        assert isinstance(CANONICAL_LAYER_MODEL_AUTHORITY, str)
        assert "PR9" in CANONICAL_LAYER_MODEL_AUTHORITY or "PR-9" in CANONICAL_LAYER_MODEL_AUTHORITY

    def test_no_key_declaration_misclassifies_v4_as_universal_gate(self):
        """V4_IS_NOT_PER_REQUEST_GATE_POLICY in the spine must state V4 is NOT a per-request gate."""
        import core.unified_orchestration_spine as spine
        policy = spine.V4_IS_NOT_PER_REQUEST_GATE_POLICY
        assert "NOT" in policy or "not" in policy.lower(), \
            "V4_IS_NOT_PER_REQUEST_GATE_POLICY should include 'NOT' language"

    def test_no_key_declaration_misclassifies_v6_as_request_gate(self):
        """V6 release_blocking_gate must NOT present itself as a per-request gate."""
        import core.release_blocking_gate as gate
        # The authority sentinel must describe it as a release/CI gate, not per-request.
        authority = gate.RELEASE_BLOCKING_GATE_AUTHORITY
        # Should mention CI or release, not per-request invocation.
        assert "CI" in authority or "release" in authority.lower() or "posture" in authority.lower()

    def test_architecture_invariants_module_exported_in_core_shim(self):
        """core.architecture_invariants shim re-exports from tools.architecture.architecture_invariants."""
        import core.architecture_invariants as shim
        # After the shim loads the real module, CANONICAL_AUTHORITY_LABELS must be accessible.
        assert hasattr(shim, "CANONICAL_AUTHORITY_LABELS")
