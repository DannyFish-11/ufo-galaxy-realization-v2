#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr50_architecture_consolidation.py
==============================================

PR-10 (Consolidation) — Cross-cutting architecture invariant tests.

This test suite validates the outcomes of the PR-010 consolidation work:
  1. Consistency of authority labels across diagnostic surfaces.
  2. Consistency of canonical/legacy markers across representative modules.
  3. Baseline scorecard/diagnostic alignment.
  4. Projection/outward-truth representation consistency.
  5. Addon/package contract metadata uniformity.
  6. Cross-cutting invariant constants (shared vocabulary).

All tests are self-contained (no live servers, no real devices).

Test classes:

  TestArchitectureInvariantsConstants
    Validates CANONICAL_AUTHORITY_LABELS, LEGACY_BOUNDARY_LABELS,
    PROJECTION_TRUTH_MARKERS, AUTHORITY_CHAIN, CANONICAL_ADDON_CONTRACT_TYPES.

  TestCheckAuthorityLabelsConsistent
    check_authority_labels_consistent() with valid and invalid metadata.

  TestCheckCanonicalLegacyMarkersUniform
    check_canonical_legacy_markers_uniform() with various surface metadata.

  TestCheckProjectionIsOutwardTruth
    check_projection_is_outward_truth() with compliant and violating metadata.

  TestCheckAddonContractMetadataUniform
    check_addon_contract_metadata_uniform() with well-formed and malformed entries.

  TestRunConsolidationInvariants
    run_consolidation_invariants() aggregate entry point.

  TestConsolidationReport
    ConsolidationReport data type and to_dict().

  TestArchitectureDiagnosticsConsolidationChecks
    New checks added to ArchitectureDiagnostics in PR-010:
    check_projection_metadata_coherent() and
    check_canonical_legacy_labels_consistent().

  TestScorecardDiagnosticAlignment
    Verifies that the completion scorecard and architecture diagnostics are
    mutually consistent (no contradictory claims about canonical/legacy state).

  TestAuthorityLabelsCrossModuleConsistency
    Verifies that the authority-role string labels used in
    architecture_diagnostics, architecture_invariants, and the completion
    scorecard evidence modules all refer to the same canonical vocabulary.

  TestProjectionOutwardTruthCrossModule
    Verifies that projection metadata in ui_surface_authority is consistent
    with the outward-truth policy enforced by architecture_invariants.

  TestInstallableAddonContractMetadata
    Verifies that canonical addon contract types referenced in the scorecard
    are consistent with CANONICAL_ADDON_CONTRACT_TYPES.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# Imports under test
# ===========================================================================

from core.architecture_invariants import (
    AUTHORITY_CHAIN,
    CANONICAL_ADDON_CONTRACT_TYPES,
    CANONICAL_AUTHORITY_LABELS,
    LEGACY_BOUNDARY_LABELS,
    PROJECTION_TRUTH_MARKERS,
    ConsolidationReport,
    InvariantFinding,
    InvariantSeverity,
    check_addon_contract_metadata_uniform,
    check_authority_labels_consistent,
    check_canonical_legacy_markers_uniform,
    check_projection_is_outward_truth,
    run_consolidation_invariants,
)

from core.architecture_diagnostics import (
    ArchitectureDiagnostics,
    DiagnosticSeverity,
    run_architecture_diagnostics,
)

from core.architecture_completion import (
    CompletionDimension,
    MaturityLevel,
    get_architecture_completion_scorecard,
    reset_architecture_completion_scorecard,
)


# ===========================================================================
# Fixtures and helpers
# ===========================================================================

@pytest.fixture(autouse=True)
def reset_scorecard():
    """Ensure a clean scorecard singleton before each test."""
    reset_architecture_completion_scorecard()
    yield
    reset_architecture_completion_scorecard()


def _valid_diagnostics_snapshot() -> Dict[str, Any]:
    return {
        "runtime_shell": {
            "authority_metadata": {
                "layer_role": "runtime_shell_authority",
                "canonical_module": "core.desktop_presence_runtime",
            },
            "arch_layer_id": "runtime_shell",
        },
        "subject_core": {
            "metadata": {"authority_role": "subject_decision_authority"},
            "arch_layer_id": "subject_core",
        },
        "cognition_layer": {
            "authority_role": "cognition_planning_layer",
            "arch_layer_id": "cognition_layer",
        },
        "execution_substrate": {
            "execution_substrate_role": "execution_substrate",
            "arch_layer_id": "execution_substrate",
        },
    }


# ===========================================================================
# TestArchitectureInvariantsConstants
# ===========================================================================

class TestArchitectureInvariantsConstants:
    """1. Canonical constant sets are populated correctly."""

    def test_canonical_authority_labels_is_frozenset(self):
        assert isinstance(CANONICAL_AUTHORITY_LABELS, frozenset)

    def test_canonical_authority_labels_nonempty(self):
        assert len(CANONICAL_AUTHORITY_LABELS) > 0

    def test_runtime_shell_authority_in_canonical(self):
        assert "runtime_shell_authority" in CANONICAL_AUTHORITY_LABELS

    def test_subject_decision_authority_in_canonical(self):
        assert "subject_decision_authority" in CANONICAL_AUTHORITY_LABELS

    def test_cognition_planning_layer_in_canonical(self):
        assert "cognition_planning_layer" in CANONICAL_AUTHORITY_LABELS

    def test_execution_substrate_in_canonical(self):
        assert "execution_substrate" in CANONICAL_AUTHORITY_LABELS

    def test_legacy_boundary_labels_is_frozenset(self):
        assert isinstance(LEGACY_BOUNDARY_LABELS, frozenset)

    def test_legacy_ui_in_boundary_labels(self):
        assert "legacy_ui" in LEGACY_BOUNDARY_LABELS or "LEGACY_UI" in LEGACY_BOUNDARY_LABELS

    def test_legacy_shell_in_boundary_labels(self):
        assert "legacy_shell" in LEGACY_BOUNDARY_LABELS or "LEGACY_SHELL" in LEGACY_BOUNDARY_LABELS

    def test_deprecated_in_boundary_labels(self):
        assert "deprecated" in LEGACY_BOUNDARY_LABELS or "DEPRECATED" in LEGACY_BOUNDARY_LABELS

    def test_canonical_and_legacy_labels_do_not_overlap(self):
        overlap = CANONICAL_AUTHORITY_LABELS & LEGACY_BOUNDARY_LABELS
        assert len(overlap) == 0, f"Labels appear in both sets: {overlap}"

    def test_projection_truth_markers_is_frozenset(self):
        assert isinstance(PROJECTION_TRUTH_MARKERS, frozenset)

    def test_projection_driven_in_truth_markers(self):
        assert (
            "projection_driven" in PROJECTION_TRUTH_MARKERS
            or "PROJECTION_DRIVEN" in PROJECTION_TRUTH_MARKERS
        )

    def test_projection_markers_disjoint_from_legacy(self):
        overlap = PROJECTION_TRUTH_MARKERS & LEGACY_BOUNDARY_LABELS
        assert len(overlap) == 0, f"Projection markers overlap with legacy labels: {overlap}"

    def test_authority_chain_is_tuple(self):
        assert isinstance(AUTHORITY_CHAIN, tuple)

    def test_authority_chain_length(self):
        assert len(AUTHORITY_CHAIN) == 4

    def test_authority_chain_first_entry_is_runtime_shell(self):
        assert AUTHORITY_CHAIN[0][0] == "runtime_shell"

    def test_authority_chain_last_entry_is_execution_substrate(self):
        assert AUTHORITY_CHAIN[-1][0] == "execution_substrate"

    def test_authority_chain_roles_are_canonical(self):
        for _, role in AUTHORITY_CHAIN:
            assert role in CANONICAL_AUTHORITY_LABELS, f"Role '{role}' not in CANONICAL_AUTHORITY_LABELS"

    def test_canonical_addon_contract_types_nonempty(self):
        assert len(CANONICAL_ADDON_CONTRACT_TYPES) > 0

    def test_mcp_addon_in_contract_types(self):
        assert "mcp_addon" in CANONICAL_ADDON_CONTRACT_TYPES

    def test_skill_package_in_contract_types(self):
        assert "skill_package" in CANONICAL_ADDON_CONTRACT_TYPES


# ===========================================================================
# TestCheckAuthorityLabelsConsistent
# ===========================================================================

class TestCheckAuthorityLabelsConsistent:
    """2. check_authority_labels_consistent validates authority label vocabulary."""

    def test_empty_dict_returns_info(self):
        findings = check_authority_labels_consistent({})
        assert any(f.severity == InvariantSeverity.INFO.value for f in findings)

    def test_known_canonical_label_passes(self):
        findings = check_authority_labels_consistent(
            {"role": "subject_decision_authority"}
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_unknown_authority_label_is_error(self):
        findings = check_authority_labels_consistent(
            {"role": "some_unknown_authority"}
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_nested_unknown_label_is_error(self):
        findings = check_authority_labels_consistent(
            {"authority_metadata": {"layer_role": "mystery_layer"}}
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_all_canonical_labels_pass(self):
        for label in CANONICAL_AUTHORITY_LABELS:
            findings = check_authority_labels_consistent({"role": label})
            errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
            assert len(errors) == 0, f"Label '{label}' should not produce errors"

    def test_returns_list_of_invariant_findings(self):
        findings = check_authority_labels_consistent({"role": "runtime_shell_authority"})
        assert isinstance(findings, list)
        assert all(isinstance(f, InvariantFinding) for f in findings)


# ===========================================================================
# TestCheckCanonicalLegacyMarkersUniform
# ===========================================================================

class TestCheckCanonicalLegacyMarkersUniform:
    """3. check_canonical_legacy_markers_uniform validates canonical/legacy uniformity."""

    def test_empty_input_returns_info(self):
        findings = check_canonical_legacy_markers_uniform([])
        assert any(f.severity == InvariantSeverity.INFO.value for f in findings)

    def test_canonical_surface_passes(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "desktop_presence_runtime", "role": "runtime_shell_authority"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_legacy_surface_passes(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "dashboard.backend.main", "role": "legacy_ui"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_projection_driven_surface_passes(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "status_board_v2", "role": "projection_driven"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_unknown_role_is_warning(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "some_module", "role": "totally_unknown_role"}]
        )
        warnings = [f for f in findings if f.severity == InvariantSeverity.WARNING.value]
        assert len(warnings) >= 1

    def test_multiple_surfaces_mixed(self):
        surfaces = [
            {"surface_id": "core.openclawd", "role": "subject_decision_authority"},
            {"surface_id": "dashboard", "role": "LEGACY_UI"},
            {"surface_id": "status_board_v2", "role": "projection_driven"},
        ]
        findings = check_canonical_legacy_markers_uniform(surfaces)
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_returns_list_of_invariant_findings(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "x", "role": "execution_substrate"}]
        )
        assert isinstance(findings, list)
        assert all(isinstance(f, InvariantFinding) for f in findings)

    def test_info_for_correctly_labeled_canonical_surface(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "core.command_router", "role": "execution_substrate"}]
        )
        infos = [f for f in findings if f.severity == InvariantSeverity.INFO.value]
        assert len(infos) >= 1

    def test_info_for_correctly_labeled_legacy_surface(self):
        findings = check_canonical_legacy_markers_uniform(
            [{"surface_id": "dashboard", "role": "LEGACY_UI"}]
        )
        infos = [f for f in findings if f.severity == InvariantSeverity.INFO.value]
        assert len(infos) >= 1


# ===========================================================================
# TestCheckProjectionIsOutwardTruth
# ===========================================================================

class TestCheckProjectionIsOutwardTruth:
    """4. check_projection_is_outward_truth validates outward-truth policy."""

    def test_compliant_projection_passes(self):
        findings = check_projection_is_outward_truth(
            {"source": "projection", "is_outward_truth": True}
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_is_outward_truth_false_is_error(self):
        findings = check_projection_is_outward_truth({"is_outward_truth": False})
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_legacy_role_on_projection_is_error(self):
        findings = check_projection_is_outward_truth({"role": "legacy_ui"})
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_projection_driven_role_passes(self):
        findings = check_projection_is_outward_truth({"role": "projection_driven"})
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_empty_metadata_is_warning(self):
        findings = check_projection_is_outward_truth({})
        assert any(
            f.severity in (InvariantSeverity.WARNING.value, InvariantSeverity.INFO.value)
            for f in findings
        )

    def test_runtime_projection_source_passes(self):
        findings = check_projection_is_outward_truth(
            {"source": "runtime_projection", "is_outward_truth": True}
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_returns_list_of_invariant_findings(self):
        findings = check_projection_is_outward_truth({"source": "projection"})
        assert isinstance(findings, list)
        assert all(isinstance(f, InvariantFinding) for f in findings)


# ===========================================================================
# TestCheckAddonContractMetadataUniform
# ===========================================================================

class TestCheckAddonContractMetadataUniform:
    """5. check_addon_contract_metadata_uniform validates addon/package metadata."""

    def test_empty_registry_returns_info(self):
        findings = check_addon_contract_metadata_uniform([])
        assert any(f.severity == InvariantSeverity.INFO.value for f in findings)

    def test_well_formed_mcp_addon_passes(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "my_mcp", "contract_type": "mcp_addon", "version": "1.0.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_well_formed_skill_package_passes(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "my_skill", "contract_type": "skill_package", "version": "2.1.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_missing_addon_id_is_error(self):
        findings = check_addon_contract_metadata_uniform(
            [{"contract_type": "mcp_addon", "version": "1.0.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_missing_contract_type_is_error(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "x", "version": "1.0.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_missing_version_is_error(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "x", "contract_type": "mcp_addon"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) >= 1

    def test_unknown_contract_type_is_warning(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "x", "contract_type": "custom_type", "version": "1.0.0"}]
        )
        warnings = [f for f in findings if f.severity == InvariantSeverity.WARNING.value]
        assert len(warnings) >= 1

    def test_multiple_addons_all_valid(self):
        entries = [
            {"addon_id": "a", "contract_type": "mcp_addon", "version": "1.0"},
            {"addon_id": "b", "contract_type": "skill_package", "version": "2.0"},
        ]
        findings = check_addon_contract_metadata_uniform(entries)
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_all_canonical_contract_types_pass(self):
        for contract_type in CANONICAL_ADDON_CONTRACT_TYPES:
            findings = check_addon_contract_metadata_uniform(
                [{"addon_id": "x", "contract_type": contract_type, "version": "1.0.0"}]
            )
            errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
            assert len(errors) == 0, f"Contract type '{contract_type}' should not produce errors"


# ===========================================================================
# TestRunConsolidationInvariants
# ===========================================================================

class TestRunConsolidationInvariants:
    """6. run_consolidation_invariants aggregate entry point."""

    def test_returns_consolidation_report(self):
        report = run_consolidation_invariants()
        assert isinstance(report, ConsolidationReport)

    def test_empty_args_returns_consistent_report(self):
        report = run_consolidation_invariants()
        assert report.overall_consistent

    def test_valid_all_args_returns_consistent(self):
        report = run_consolidation_invariants(
            authority_metadata={"role": "subject_decision_authority"},
            surface_metadata=[
                {"surface_id": "dashboard", "role": "LEGACY_UI"},
                {"surface_id": "status_board_v2", "role": "projection_driven"},
            ],
            projection_metadata={"source": "projection", "is_outward_truth": True},
            addon_registry_snapshot=[
                {"addon_id": "my_mcp", "contract_type": "mcp_addon", "version": "1.0.0"}
            ],
        )
        assert report.overall_consistent

    def test_invalid_authority_label_makes_inconsistent(self):
        report = run_consolidation_invariants(
            authority_metadata={"role": "bad_authority"}
        )
        assert not report.overall_consistent

    def test_is_outward_truth_false_makes_inconsistent(self):
        report = run_consolidation_invariants(
            projection_metadata={"is_outward_truth": False}
        )
        assert not report.overall_consistent

    def test_missing_addon_field_makes_inconsistent(self):
        report = run_consolidation_invariants(
            addon_registry_snapshot=[{"contract_type": "mcp_addon", "version": "1.0"}]
        )
        assert not report.overall_consistent

    def test_checks_run_populated(self):
        report = run_consolidation_invariants(
            authority_metadata={"role": "execution_substrate"},
            projection_metadata={"source": "projection"},
        )
        assert len(report.checks_run) >= 2

    def test_to_dict_is_json_serialisable(self):
        report = run_consolidation_invariants(
            authority_metadata={"role": "runtime_shell_authority"},
        )
        d = report.to_dict()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)
        assert "overall_consistent" in json_str


# ===========================================================================
# TestConsolidationReport
# ===========================================================================

class TestConsolidationReport:
    """7. ConsolidationReport data type."""

    def test_default_is_consistent(self):
        report = ConsolidationReport()
        assert report.overall_consistent

    def test_add_error_makes_inconsistent(self):
        report = ConsolidationReport()
        report.add(InvariantFinding(
            check="TEST",
            severity=InvariantSeverity.ERROR.value,
            message="test error",
        ))
        assert not report.overall_consistent

    def test_add_warning_stays_consistent(self):
        report = ConsolidationReport()
        report.add(InvariantFinding(
            check="TEST",
            severity=InvariantSeverity.WARNING.value,
            message="test warning",
        ))
        assert report.overall_consistent

    def test_error_count_increments(self):
        report = ConsolidationReport()
        report.add(InvariantFinding(check="C", severity=InvariantSeverity.ERROR.value, message="e"))
        assert report.error_count == 1

    def test_warning_count_increments(self):
        report = ConsolidationReport()
        report.add(InvariantFinding(check="C", severity=InvariantSeverity.WARNING.value, message="w"))
        assert report.warning_count == 1

    def test_to_dict_keys(self):
        report = ConsolidationReport()
        d = report.to_dict()
        assert "overall_consistent" in d
        assert "error_count" in d
        assert "findings" in d
        assert "checks_run" in d

    def test_invariant_finding_to_dict(self):
        f = InvariantFinding(check="C", severity="error", message="msg", detail={"k": "v"})
        d = f.to_dict()
        assert d["check"] == "C"
        assert d["severity"] == "error"
        assert d["message"] == "msg"
        assert d["detail"] == {"k": "v"}


# ===========================================================================
# TestArchitectureDiagnosticsConsolidationChecks
# ===========================================================================

class TestArchitectureDiagnosticsConsolidationChecks:
    """8. New checks added to ArchitectureDiagnostics in PR-010."""

    def test_check_projection_metadata_coherent_skipped_when_absent(self):
        diag = ArchitectureDiagnostics({})
        diag.check_projection_metadata_coherent()
        report = diag.build_report()
        assert report.overall_valid
        assert "PROJECTION_METADATA_COHERENT" in report.checks_run

    def test_check_projection_metadata_coherent_with_valid_projection(self):
        snapshot = {
            "projection": {
                "source": "projection",
                "role": "projection_driven",
                "is_outward_truth": True,
            }
        }
        diag = ArchitectureDiagnostics(snapshot)
        diag.check_projection_metadata_coherent()
        report = diag.build_report()
        assert report.overall_valid

    def test_check_projection_metadata_coherent_legacy_role_is_error(self):
        snapshot = {
            "projection": {
                "role": "LEGACY_UI",
            }
        }
        diag = ArchitectureDiagnostics(snapshot)
        diag.check_projection_metadata_coherent()
        report = diag.build_report()
        assert not report.overall_valid

    def test_check_projection_metadata_coherent_false_outward_truth_is_error(self):
        snapshot = {
            "projection": {
                "is_outward_truth": False,
            }
        }
        diag = ArchitectureDiagnostics(snapshot)
        diag.check_projection_metadata_coherent()
        report = diag.build_report()
        assert not report.overall_valid

    def test_check_canonical_legacy_labels_consistent_no_violations(self):
        snapshot = _valid_diagnostics_snapshot()
        diag = ArchitectureDiagnostics(snapshot)
        diag.check_canonical_legacy_labels_consistent()
        report = diag.build_report()
        assert report.overall_valid
        assert "CANONICAL_LEGACY_LABELS_CONSISTENT" in report.checks_run

    def test_check_canonical_legacy_labels_consistent_empty_snapshot(self):
        diag = ArchitectureDiagnostics({})
        diag.check_canonical_legacy_labels_consistent()
        report = diag.build_report()
        assert report.overall_valid

    def test_run_all_checks_includes_new_checks(self):
        snapshot = _valid_diagnostics_snapshot()
        diag = ArchitectureDiagnostics(snapshot)
        diag.run_all_checks()
        assert "PROJECTION_METADATA_COHERENT" in diag.build_report().checks_run
        assert "CANONICAL_LEGACY_LABELS_CONSISTENT" in diag.build_report().checks_run

    def test_run_architecture_diagnostics_valid_snapshot(self):
        report = run_architecture_diagnostics(_valid_diagnostics_snapshot())
        assert report.overall_valid


# ===========================================================================
# TestScorecardDiagnosticAlignment
# ===========================================================================

class TestScorecardDiagnosticAlignment:
    """9. Scorecard and diagnostics tell the same architectural story."""

    def test_scorecard_generated_by_pr10(self):
        sc = get_architecture_completion_scorecard()
        assert sc.generated_by_pr == "PR-10"

    def test_scorecard_has_10_dimensions(self):
        sc = get_architecture_completion_scorecard()
        assert sc.total_dimensions == 10

    def test_scorecard_diagnostics_observability_is_complete(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY)
        assert dim is not None
        assert dim.maturity_level == MaturityLevel.COMPLETE

    def test_scorecard_test_coverage_is_complete(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.TEST_COVERAGE_ARCHITECTURE_INVARIANTS)
        assert dim is not None
        assert dim.maturity_level == MaturityLevel.COMPLETE

    def test_scorecard_test_coverage_includes_pr50(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.TEST_COVERAGE_ARCHITECTURE_INVARIANTS)
        assert dim is not None
        assert any("test_pr50" in m for m in dim.evidence_modules)

    def test_scorecard_diagnostics_observability_includes_architecture_invariants(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.DIAGNOSTICS_OBSERVABILITY_MATURITY)
        assert dim is not None
        assert any("architecture_invariants" in m for m in dim.evidence_modules)

    def test_scorecard_no_blocking_dimensions_are_legacy_ambiguity(self):
        sc = get_architecture_completion_scorecard()
        for dim in sc.dimensions:
            assert dim.maturity_level != MaturityLevel.LEGACY_AMBIGUITY, (
                f"Dimension {dim.dimension} is LEGACY_AMBIGUITY (blocking)"
            )

    def test_architecture_diagnostics_valid_on_canonical_snapshot(self):
        report = run_architecture_diagnostics(_valid_diagnostics_snapshot())
        assert report.overall_valid

    def test_scorecard_and_diagnostics_agree_on_authority_chain(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.AUTHORITY_CLARITY)
        assert dim is not None
        assert dim.canonical_path_established
        assert not dim.legacy_ambiguity_remains
        report = run_architecture_diagnostics(_valid_diagnostics_snapshot())
        assert report.overall_valid

    def test_scorecard_to_dict_is_json_serialisable(self):
        sc = get_architecture_completion_scorecard()
        d = sc.to_dict()
        json_str = json.dumps(d)
        assert "PR-10" in json_str

    def test_scorecard_overall_completion_pct_above_threshold(self):
        sc = get_architecture_completion_scorecard()
        assert sc.overall_completion_pct >= 70.0


# ===========================================================================
# TestAuthorityLabelsCrossModuleConsistency
# ===========================================================================

class TestAuthorityLabelsCrossModuleConsistency:
    """10. Authority-role labels are consistent across modules."""

    def test_diagnostics_expected_roles_are_canonical(self):
        from core.architecture_diagnostics import _LAYER_EXPECTED_ROLES
        for layer_key, role in _LAYER_EXPECTED_ROLES.items():
            assert role in CANONICAL_AUTHORITY_LABELS, (
                f"architecture_diagnostics._LAYER_EXPECTED_ROLES['{layer_key}'] = '{role}' "
                f"is not in CANONICAL_AUTHORITY_LABELS"
            )

    def test_authority_chain_roles_match_diagnostics_expected(self):
        from core.architecture_diagnostics import _LAYER_EXPECTED_ROLES
        for layer_key, role in AUTHORITY_CHAIN:
            if layer_key in _LAYER_EXPECTED_ROLES:
                assert _LAYER_EXPECTED_ROLES[layer_key] == role, (
                    f"AUTHORITY_CHAIN['{layer_key}'] = '{role}' does not match "
                    f"_LAYER_EXPECTED_ROLES['{layer_key}'] = '{_LAYER_EXPECTED_ROLES[layer_key]}'"
                )

    def test_scorecard_authority_clarity_evidence_uses_canonical_modules(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.AUTHORITY_CLARITY)
        assert dim is not None
        assert len(dim.evidence_modules) > 0
        assert any("openclawd" in m for m in dim.evidence_modules)
        assert any("command_router" in m for m in dim.evidence_modules)

    def test_canonical_authority_labels_matches_diagnostics_role_order(self):
        from core.architecture_diagnostics import _LAYER_EXPECTED_ROLES
        # All roles in _LAYER_EXPECTED_ROLES must be canonical authority labels.
        for layer_key, role in _LAYER_EXPECTED_ROLES.items():
            assert role in CANONICAL_AUTHORITY_LABELS, (
                f"_LAYER_EXPECTED_ROLES['{layer_key}'] = '{role}' "
                f"is not in CANONICAL_AUTHORITY_LABELS"
            )


# ===========================================================================
# TestProjectionOutwardTruthCrossModule
# ===========================================================================

class TestProjectionOutwardTruthCrossModule:
    """11. Projection outward-truth is consistent across modules."""

    def test_ui_surface_authority_status_board_is_projection_driven(self):
        from core.ui_surface_authority import (
            UISurfaceRole,
            is_projection_driven_surface,
        )
        assert is_projection_driven_surface("windows_client.status_board_v2")

    def test_ui_surface_authority_dashboard_is_deleted_not_legacy(self):
        from core.ui_surface_authority import is_legacy_surface
        assert not is_legacy_surface("dashboard.backend.main")

    def test_projection_driven_label_matches_ui_surface_authority_role(self):
        from core.ui_surface_authority import UISurfaceRole
        projection_driven_value = UISurfaceRole.PROJECTION_DRIVEN.value.lower()
        assert (
            projection_driven_value in PROJECTION_TRUTH_MARKERS
            or "PROJECTION_DRIVEN" in PROJECTION_TRUTH_MARKERS
            or "projection_driven" in PROJECTION_TRUTH_MARKERS
        )

    def test_legacy_ui_label_matches_ui_surface_authority_role(self):
        from core.ui_surface_authority import UISurfaceRole
        legacy_ui_value = UISurfaceRole.LEGACY_UI.value
        assert (
            legacy_ui_value in LEGACY_BOUNDARY_LABELS
            or legacy_ui_value.lower() in LEGACY_BOUNDARY_LABELS
        )

    def test_legacy_shell_label_matches_ui_surface_authority_role(self):
        from core.ui_surface_authority import UISurfaceRole
        legacy_shell_value = UISurfaceRole.LEGACY_SHELL.value
        assert (
            legacy_shell_value in LEGACY_BOUNDARY_LABELS
            or legacy_shell_value.lower() in LEGACY_BOUNDARY_LABELS
        )

    def test_scorecard_projection_alignment_dimension_is_canonical(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.PROJECTION_OUTWARD_TRUTH_ALIGNMENT)
        assert dim is not None
        assert dim.canonical_path_established
        assert not dim.legacy_ambiguity_remains

    def test_projection_diagnostics_check_on_valid_projection_snapshot(self):
        snapshot = {
            "projection": {"source": "projection", "is_outward_truth": True}
        }
        diag = ArchitectureDiagnostics(snapshot)
        diag.check_projection_metadata_coherent()
        report = diag.build_report()
        assert report.overall_valid


# ===========================================================================
# TestInstallableAddonContractMetadata
# ===========================================================================

class TestInstallableAddonContractMetadata:
    """12. Installable addon/package contract metadata is consistent."""

    def test_scorecard_installability_dimension_present(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        assert dim is not None

    def test_scorecard_installability_dimension_is_complete(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.INSTALLABILITY_ECOSYSTEM_READINESS)
        assert dim is not None
        assert dim.maturity_level == MaturityLevel.COMPLETE

    def test_scorecard_capability_integration_dimension_is_complete(self):
        sc = get_architecture_completion_scorecard()
        dim = sc.dimension_by_name(CompletionDimension.CAPABILITY_INTEGRATION_COMPLETENESS)
        assert dim is not None
        assert dim.maturity_level == MaturityLevel.COMPLETE

    def test_mcp_addon_contract_type_is_canonical(self):
        assert "mcp_addon" in CANONICAL_ADDON_CONTRACT_TYPES

    def test_skill_package_contract_type_is_canonical(self):
        assert "skill_package" in CANONICAL_ADDON_CONTRACT_TYPES

    def test_addon_check_valid_mcp_server_type(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "test_server", "contract_type": "mcp_server", "version": "1.0.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_addon_check_valid_skill_md_type(self):
        findings = check_addon_contract_metadata_uniform(
            [{"addon_id": "test_skill_md", "contract_type": "skill_md", "version": "1.0.0"}]
        )
        errors = [f for f in findings if f.severity == InvariantSeverity.ERROR.value]
        assert len(errors) == 0

    def test_consolidation_report_addon_check_integrates(self):
        report = run_consolidation_invariants(
            addon_registry_snapshot=[
                {"addon_id": "my_mcp", "contract_type": "mcp_addon", "version": "1.0.0"},
                {"addon_id": "my_skill", "contract_type": "skill_package", "version": "2.0.0"},
            ]
        )
        assert report.overall_consistent
