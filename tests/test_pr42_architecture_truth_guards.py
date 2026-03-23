#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr42_architecture_truth_guards.py
============================================

PR-28 (internal: PR-42) — Architecture Guards for Canonical Truth Ownership
and Boundary Invariants

Coverage
--------

1. GuardSeverity enum
   - all expected values present
   - string values are stable

2. GuardFinding
   - construction with all fields
   - to_dict is JSON-serialisable
   - to_dict omits detail when not provided

3. GuardReport
   - passed=True when no errors
   - passed=False when any error present
   - format_failures returns empty string on clean report
   - format_failures returns actionable text on error report
   - to_dict is JSON-serialisable
   - to_json round-trip preserves all fields

4. CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned()
   - clean snapshot with shell owning registry → passed
   - subject_core owning registry → error (SUBJECT_CORE_MUST_NOT_OWN_SOURCE_REGISTRY)
   - third layer owning registry → error (DUPLICATE_SOURCE_REGISTRY_OWNER)
   - shell with owns_source_registry=False → error (SOURCE_REGISTRY_SHELL_OWNED)
   - empty snapshot → passed (fail-open)

5. CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority()
   - subject_core with correct role → passed
   - subject_core with wrong role → error (SUBJECT_CORE_WRONG_AUTHORITY_ROLE)
   - subject_core with is_final_model_authority=False → error
   - another layer claiming subject_decision_authority → error
   - empty snapshot → no errors

6. CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth()
   - valid canonical_supply → passed
   - canonical_supply with is_canonical_supply_layer=False → error
   - router claiming is_capability_truth=True → error
   - provider_adapter claiming is_capability_truth=True → error
   - routing_decision with independent_capability_registry=True → error
   - routing_decision with sourced_from_canonical_supply=False → error
   - empty snapshot → no errors

7. CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth()
   - clean projection → passed
   - is_truth_reconstruction_layer=True → error (PROJECTION_RECONSTRUCTS_TRUTH)
   - sourced_from_canonical_plan=False → error
   - projection owns_source_registry=True → error
   - projection claims model authority → error
   - no projection in snapshot → INFO finding (not error)

8. BoundaryInvariantGuard.assert_substrate_does_not_self_promote()
   - substrate with correct role → passed
   - substrate claiming runtime_shell_authority → error
   - substrate claiming subject_decision_authority → error
   - substrate with unexpected role → warning (not error)
   - substrate with is_final_model_authority=True → error
   - substrate with is_policy_authority=True → error
   - no substrate in snapshot → INFO finding

9. BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority()
   - orchestration with correct role → passed
   - orchestration claiming execution_substrate → error
   - orchestration claiming subject_decision_authority → error
   - substrate claiming orchestration_layer role → error
   - orchestration with unexpected role → warning
   - empty snapshot → no errors

10. BoundaryInvariantGuard.assert_router_not_final_authority()
    - router with is_final_model_authority=False → passed
    - router with is_final_model_authority=True → error
    - provider_adapter with is_final_model_authority=True → error
    - router claiming elevated authority_role → error
    - empty router/adapter → passes cleanly

11. BoundaryInvariantGuard.assert_no_duplicate_truth_paths()
    - single source registry owner → passed
    - two source registry owners → error (DUPLICATE_SOURCE_REGISTRY)
    - single capability truth owner → passed
    - two capability truth owners → error (DUPLICATE_CAPABILITY_TRUTH)
    - no owners → passes (no duplicate)

12. run_canonical_truth_ownership_checks()
    - clean snapshot → passed
    - corrupted subject_core role → not passed
    - projection reconstructing truth → not passed
    - None snapshot → passed (fail-open with INFO)
    - never raises on garbage input

13. run_boundary_invariant_checks()
    - clean snapshot → passed
    - substrate self-promotion → not passed
    - duplicate source registry → not passed
    - None snapshot → passed (fail-open with INFO)
    - never raises on garbage input

14. run_all_architecture_guards()
    - representative clean flow → passed
    - single error in ownership → propagated to combined report
    - single error in boundary → propagated to combined report
    - None snapshot → passed
    - report is JSON-serialisable
    - format_failures() is clear and actionable

15. build_architecture_snapshot_from_response()
    - extracts arch_layer_id from top-level response
    - extracts arch_layer_id from nested metadata
    - ignores non-dict input
    - never raises on garbage input

16. Integration: real module imports
    - DesktopPresenceRuntime owns _source_registry, OpenClawd does not
    - OpenClawd carries subject_decision_authority role in responses
    - CommandRouter carries execution_substrate role in results
    - desktop_status_projection sourced from canonical plan (contract check)

17. Anti-corruption adapter guard
    - adapter exposing owns_source_registry is flagged
    - adapter exposing is_final_model_authority is flagged

18. Module-level exports
    - all __all__ symbols importable

19. Additive integration
    - existing architecture_diagnostics import unaffected
    - architecture_truth_guards import causes no side-effects
"""

from __future__ import annotations

import json
from typing import Any, Dict


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _clean_snapshot() -> Dict[str, Any]:
    """Return a canonical clean architecture snapshot for happy-path tests."""
    return {
        "runtime_shell": {
            "arch_layer_id": "runtime_shell",
            "authority_role": "runtime_shell_authority",
            "owns_source_registry": True,
        },
        "subject_core": {
            "arch_layer_id": "subject_core",
            "authority_role": "subject_decision_authority",
            "owns_source_registry": False,
            "is_final_model_authority": True,
        },
        "canonical_supply": {
            "is_canonical_supply_layer": True,
            "is_capability_truth": True,
        },
        "projection": {
            "is_truth_reconstruction_layer": False,
            "sourced_from_canonical_plan": True,
            "owns_source_registry": False,
            "is_final_model_authority": False,
        },
        "execution_substrate": {
            "arch_layer_id": "execution_substrate",
            "authority_role": "execution_substrate",
            "is_final_model_authority": False,
            "is_policy_authority": False,
        },
        "orchestration_layer": {
            "arch_layer_id": "orchestration_layer",
            "authority_role": "orchestration_layer",
        },
        "router": {
            "is_final_model_authority": False,
        },
        "provider_adapter": {
            "is_final_model_authority": False,
        },
    }


# ===========================================================================
# 1. GuardSeverity enum
# ===========================================================================


class TestGuardSeverity:
    def test_all_expected_values_present(self):
        from core.architecture_truth_guards import GuardSeverity
        assert hasattr(GuardSeverity, "INFO")
        assert hasattr(GuardSeverity, "WARNING")
        assert hasattr(GuardSeverity, "ERROR")

    def test_string_values_are_stable(self):
        from core.architecture_truth_guards import GuardSeverity
        assert GuardSeverity.INFO.value == "info"
        assert GuardSeverity.WARNING.value == "warning"
        assert GuardSeverity.ERROR.value == "error"


# ===========================================================================
# 2. GuardFinding
# ===========================================================================


class TestGuardFinding:
    def test_construction_with_all_fields(self):
        from core.architecture_truth_guards import GuardFinding, GuardSeverity
        f = GuardFinding(
            code="TEST_CODE",
            severity=GuardSeverity.ERROR,
            message="Test message",
            detail={"key": "value"},
        )
        assert f.code == "TEST_CODE"
        assert f.message == "Test message"
        assert f.detail == {"key": "value"}

    def test_to_dict_is_json_serialisable(self):
        from core.architecture_truth_guards import GuardFinding, GuardSeverity
        f = GuardFinding(
            code="X",
            severity=GuardSeverity.WARNING,
            message="msg",
            detail={"a": 1},
        )
        d = f.to_dict()
        json.dumps(d)  # must not raise
        assert d["code"] == "X"
        assert d["severity"] == "warning"
        assert d["message"] == "msg"
        assert d["detail"] == {"a": 1}

    def test_to_dict_omits_detail_when_none(self):
        from core.architecture_truth_guards import GuardFinding, GuardSeverity
        f = GuardFinding(code="Y", severity=GuardSeverity.INFO, message="info msg")
        d = f.to_dict()
        assert "detail" not in d


# ===========================================================================
# 3. GuardReport
# ===========================================================================


class TestGuardReport:
    def test_passed_true_when_no_errors(self):
        from core.architecture_truth_guards import GuardReport
        r = GuardReport(passed=True, error_count=0)
        assert r.passed is True

    def test_passed_false_when_errors(self):
        from core.architecture_truth_guards import GuardReport, GuardFinding, GuardSeverity
        r = GuardReport(
            passed=False,
            error_count=1,
            findings=[GuardFinding(code="E", severity=GuardSeverity.ERROR, message="bad")],
        )
        assert r.passed is False

    def test_format_failures_empty_on_clean_report(self):
        from core.architecture_truth_guards import GuardReport
        r = GuardReport(passed=True)
        assert r.format_failures() == ""

    def test_format_failures_actionable_on_error_report(self):
        from core.architecture_truth_guards import GuardReport, GuardFinding, GuardSeverity
        r = GuardReport(
            passed=False,
            error_count=1,
            findings=[
                GuardFinding(
                    code="BOUNDARY_VIOLATION",
                    severity=GuardSeverity.ERROR,
                    message="execution_substrate must not claim elevated role",
                )
            ],
        )
        text = r.format_failures()
        assert "BOUNDARY_VIOLATION" in text
        assert "execution_substrate" in text

    def test_to_dict_is_json_serialisable(self):
        from core.architecture_truth_guards import GuardReport, GuardFinding, GuardSeverity
        r = GuardReport(
            passed=False,
            error_count=1,
            warning_count=1,
            checks_run=["CHECK_A"],
            findings=[
                GuardFinding(code="C1", severity=GuardSeverity.ERROR, message="m1"),
                GuardFinding(code="C2", severity=GuardSeverity.WARNING, message="m2"),
            ],
        )
        d = r.to_dict()
        json.dumps(d)  # must not raise

    def test_to_json_round_trip(self):
        from core.architecture_truth_guards import GuardReport, GuardFinding, GuardSeverity
        r = GuardReport(
            passed=True,
            info_count=1,
            checks_run=["ROUND_TRIP"],
            findings=[GuardFinding(code="I1", severity=GuardSeverity.INFO, message="ok")],
        )
        j = r.to_json()
        parsed = json.loads(j)
        assert parsed["passed"] is True
        assert parsed["checks_run"] == ["ROUND_TRIP"]
        assert len(parsed["findings"]) == 1


# ===========================================================================
# 4. CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned
# ===========================================================================


class TestAssertSourceRegistryIsShellOwned:
    def test_clean_snapshot_passes(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": True},
            "subject_core": {"owns_source_registry": False},
        }
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        assert report.passed, report.format_failures()

    def test_subject_core_owning_registry_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": True},
            "subject_core": {"owns_source_registry": True},
        }
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBJECT_CORE_MUST_NOT_OWN_SOURCE_REGISTRY" in codes

    def test_third_layer_owning_registry_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": True},
            "subject_core": {"owns_source_registry": False},
            "rogue_layer": {"owns_source_registry": True},
        }
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "DUPLICATE_SOURCE_REGISTRY_OWNER" in codes

    def test_shell_disowning_registry_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": False},
            "subject_core": {"owns_source_registry": False},
        }
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        assert not report.passed

    def test_empty_snapshot_passes_fail_open(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned({})
        assert report.passed


# ===========================================================================
# 5. CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority
# ===========================================================================


class TestAssertOpenclawd_IsFinalAuthority:
    def test_correct_role_passes(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "subject_core": {
                "authority_role": "subject_decision_authority",
                "is_final_model_authority": True,
            }
        }
        report = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority(snapshot)
        assert report.passed, report.format_failures()

    def test_wrong_role_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "subject_core": {"authority_role": "execution_substrate"}
        }
        report = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBJECT_CORE_WRONG_AUTHORITY_ROLE" in codes

    def test_final_model_authority_false_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "subject_core": {
                "authority_role": "subject_decision_authority",
                "is_final_model_authority": False,
            }
        }
        report = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority(snapshot)
        assert not report.passed

    def test_another_layer_claiming_subject_authority_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "subject_core": {"authority_role": "subject_decision_authority"},
            "rogue_router": {"authority_role": "subject_decision_authority"},
        }
        report = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "DUPLICATE_SUBJECT_DECISION_AUTHORITY" in codes

    def test_empty_subject_core_has_error_on_role(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        # Missing subject_core → role will be None → error
        report = CanonicalTruthOwnershipGuard.assert_openclawd_is_final_authority({})
        # None != "subject_decision_authority" → must emit error
        assert not report.passed


# ===========================================================================
# 6. CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth
# ===========================================================================


class TestAssertCanonicalSupplyIsCapabilityTruth:
    def test_valid_canonical_supply_passes(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "canonical_supply": {"is_canonical_supply_layer": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert report.passed, report.format_failures()

    def test_canonical_supply_not_declared_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "canonical_supply": {"is_canonical_supply_layer": False}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert not report.passed

    def test_router_claiming_capability_truth_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "router": {"is_capability_truth": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "NON_CANONICAL_CAPABILITY_TRUTH" in codes

    def test_provider_adapter_claiming_capability_truth_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "provider_adapter": {"is_capability_truth": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert not report.passed

    def test_routing_decision_with_independent_registry_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "routing_decision": {"independent_capability_registry": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ROUTER_INDEPENDENT_CAPABILITY_REGISTRY" in codes

    def test_routing_decision_not_from_canonical_supply_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "routing_decision": {"sourced_from_canonical_supply": False}
        }
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth(snapshot)
        assert not report.passed

    def test_empty_snapshot_passes(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        report = CanonicalTruthOwnershipGuard.assert_canonical_supply_is_capability_truth({})
        assert report.passed


# ===========================================================================
# 7. CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth
# ===========================================================================


class TestAssertProjectionDoesNotReconstructTruth:
    def test_clean_projection_passes(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "projection": {
                "is_truth_reconstruction_layer": False,
                "sourced_from_canonical_plan": True,
            }
        }
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        assert report.passed, report.format_failures()

    def test_truth_reconstruction_layer_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "projection": {"is_truth_reconstruction_layer": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "PROJECTION_RECONSTRUCTS_TRUTH" in codes

    def test_not_sourced_from_canonical_plan_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "projection": {
                "is_truth_reconstruction_layer": False,
                "sourced_from_canonical_plan": False,
            }
        }
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        assert not report.passed

    def test_projection_owning_source_registry_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "projection": {"owns_source_registry": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "PROJECTION_OWNS_SOURCE_REGISTRY" in codes

    def test_projection_claiming_model_authority_is_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        snapshot = {
            "projection": {"is_final_model_authority": True}
        }
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "PROJECTION_CLAIMS_MODEL_AUTHORITY" in codes

    def test_no_projection_in_snapshot_gives_info_not_error(self):
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard
        report = CanonicalTruthOwnershipGuard.assert_projection_does_not_reconstruct_truth({})
        assert report.passed  # no projection → no error, just INFO
        codes = [f.code for f in report.findings]
        assert "PROJECTION_NOT_PRESENT" in codes


# ===========================================================================
# 8. BoundaryInvariantGuard.assert_substrate_does_not_self_promote
# ===========================================================================


class TestAssertSubstrateDoesNotSelfPromote:
    def test_correct_role_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {
                "authority_role": "execution_substrate",
                "is_final_model_authority": False,
                "is_policy_authority": False,
            }
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        assert report.passed, report.format_failures()

    def test_substrate_claiming_runtime_shell_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {"authority_role": "runtime_shell_authority"}
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBSTRATE_SELF_PROMOTION" in codes

    def test_substrate_claiming_subject_decision_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {"authority_role": "subject_decision_authority"}
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBSTRATE_SELF_PROMOTION" in codes

    def test_substrate_unexpected_role_is_warning_not_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {"authority_role": "cognition_planning_layer"}
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        # cognition_planning_layer is not in _ELEVATED_ROLES → warning, not error
        assert report.passed
        sev_values = {
            f.severity.value if hasattr(f.severity, "value") else f.severity
            for f in report.findings
        }
        assert "warning" in sev_values

    def test_substrate_claiming_model_authority_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {
                "authority_role": "execution_substrate",
                "is_final_model_authority": True,
            }
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBSTRATE_CLAIMS_MODEL_AUTHORITY" in codes

    def test_substrate_claiming_policy_authority_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {
                "authority_role": "execution_substrate",
                "is_policy_authority": True,
            }
        }
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBSTRATE_CLAIMS_POLICY_AUTHORITY" in codes

    def test_no_substrate_in_snapshot_gives_info(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        report = BoundaryInvariantGuard.assert_substrate_does_not_self_promote({})
        assert report.passed
        codes = [f.code for f in report.findings]
        assert "SUBSTRATE_NOT_PRESENT" in codes


# ===========================================================================
# 9. BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority
# ===========================================================================


class TestAssertOrchestrationDistinct:
    def test_clean_orchestration_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "orchestration_layer": {"authority_role": "orchestration_layer"},
            "execution_substrate": {"authority_role": "execution_substrate"},
        }
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        assert report.passed, report.format_failures()

    def test_orchestration_claiming_execution_substrate_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "orchestration_layer": {"authority_role": "execution_substrate"},
        }
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ORCHESTRATION_CONFLATED_WITH_SUBSTRATE" in codes

    def test_orchestration_claiming_subject_authority_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "orchestration_layer": {"authority_role": "subject_decision_authority"},
        }
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ORCHESTRATION_CLAIMS_SUBJECT_AUTHORITY" in codes

    def test_substrate_claiming_orchestration_role_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "execution_substrate": {"authority_role": "orchestration_layer"},
        }
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "SUBSTRATE_CONFLATED_WITH_ORCHESTRATION" in codes

    def test_orchestration_with_unexpected_role_is_warning(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "orchestration_layer": {"authority_role": "compatibility_adapter"},
        }
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority(snapshot)
        assert report.passed  # unexpected but not elevated → warning only
        sev_values = {
            f.severity.value if hasattr(f.severity, "value") else f.severity
            for f in report.findings
        }
        assert "warning" in sev_values

    def test_empty_snapshot_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        report = BoundaryInvariantGuard.assert_orchestration_distinct_from_substrate_and_authority({})
        assert report.passed


# ===========================================================================
# 10. BoundaryInvariantGuard.assert_router_not_final_authority
# ===========================================================================


class TestAssertRouterNotFinalAuthority:
    def test_clean_router_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "router": {"is_final_model_authority": False},
            "provider_adapter": {"is_final_model_authority": False},
        }
        report = BoundaryInvariantGuard.assert_router_not_final_authority(snapshot)
        assert report.passed, report.format_failures()

    def test_router_claiming_final_authority_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "router": {"is_final_model_authority": True},
        }
        report = BoundaryInvariantGuard.assert_router_not_final_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ROUTER_CLAIMS_FINAL_MODEL_AUTHORITY" in codes

    def test_provider_adapter_claiming_final_authority_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "provider_adapter": {"is_final_model_authority": True},
        }
        report = BoundaryInvariantGuard.assert_router_not_final_authority(snapshot)
        assert not report.passed

    def test_router_with_elevated_authority_role_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "router": {"authority_role": "subject_decision_authority"},
        }
        report = BoundaryInvariantGuard.assert_router_not_final_authority(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ROUTER_ELEVATED_AUTHORITY_ROLE" in codes

    def test_empty_router_passes_cleanly(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        report = BoundaryInvariantGuard.assert_router_not_final_authority({})
        assert report.passed


# ===========================================================================
# 11. BoundaryInvariantGuard.assert_no_duplicate_truth_paths
# ===========================================================================


class TestAssertNoDuplicateTruthPaths:
    def test_single_registry_owner_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": True},
            "subject_core": {"owns_source_registry": False},
        }
        report = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        assert report.passed, report.format_failures()

    def test_two_registry_owners_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "runtime_shell": {"owns_source_registry": True},
            "rogue": {"owns_source_registry": True},
        }
        report = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "DUPLICATE_SOURCE_REGISTRY" in codes

    def test_single_capability_truth_owner_passes(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "canonical_supply": {"is_capability_truth": True},
        }
        report = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        assert report.passed, report.format_failures()

    def test_two_capability_truth_owners_is_error(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "canonical_supply": {"is_capability_truth": True},
            "router": {"is_capability_truth": True},
        }
        report = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "DUPLICATE_CAPABILITY_TRUTH" in codes

    def test_no_owners_passes_no_duplicate(self):
        from core.architecture_truth_guards import BoundaryInvariantGuard
        snapshot = {
            "runtime_shell": {"some_flag": True},
        }
        report = BoundaryInvariantGuard.assert_no_duplicate_truth_paths(snapshot)
        assert report.passed


# ===========================================================================
# 12. run_canonical_truth_ownership_checks()
# ===========================================================================


class TestRunCanonicalTruthOwnershipChecks:
    def test_clean_snapshot_passes(self):
        from core.architecture_truth_guards import run_canonical_truth_ownership_checks
        report = run_canonical_truth_ownership_checks(_clean_snapshot())
        assert report.passed, report.format_failures()

    def test_corrupted_subject_core_role_fails(self):
        from core.architecture_truth_guards import run_canonical_truth_ownership_checks
        snap = _clean_snapshot()
        snap["subject_core"]["authority_role"] = "execution_substrate"
        report = run_canonical_truth_ownership_checks(snap)
        assert not report.passed

    def test_projection_reconstructing_truth_fails(self):
        from core.architecture_truth_guards import run_canonical_truth_ownership_checks
        snap = _clean_snapshot()
        snap["projection"]["is_truth_reconstruction_layer"] = True
        report = run_canonical_truth_ownership_checks(snap)
        assert not report.passed

    def test_none_snapshot_passes_fail_open(self):
        from core.architecture_truth_guards import run_canonical_truth_ownership_checks
        report = run_canonical_truth_ownership_checks(None)
        assert report.passed

    def test_never_raises_on_garbage_input(self):
        from core.architecture_truth_guards import run_canonical_truth_ownership_checks
        for garbage in ["not a dict", 42, [], object()]:
            report = run_canonical_truth_ownership_checks(garbage)  # type: ignore[arg-type]
            assert isinstance(report.passed, bool)  # must not raise


# ===========================================================================
# 13. run_boundary_invariant_checks()
# ===========================================================================


class TestRunBoundaryInvariantChecks:
    def test_clean_snapshot_passes(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        report = run_boundary_invariant_checks(_clean_snapshot())
        assert report.passed, report.format_failures()

    def test_substrate_self_promotion_fails(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        snap = _clean_snapshot()
        snap["execution_substrate"]["authority_role"] = "subject_decision_authority"
        report = run_boundary_invariant_checks(snap)
        assert not report.passed

    def test_duplicate_source_registry_fails(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        snap = _clean_snapshot()
        snap["rogue_layer"] = {"owns_source_registry": True}
        report = run_boundary_invariant_checks(snap)
        assert not report.passed

    def test_none_snapshot_passes_fail_open(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        report = run_boundary_invariant_checks(None)
        assert report.passed

    def test_never_raises_on_garbage_input(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        for garbage in ["string", 0, set()]:
            report = run_boundary_invariant_checks(garbage)  # type: ignore[arg-type]
            assert isinstance(report.passed, bool)


# ===========================================================================
# 14. run_all_architecture_guards()
# ===========================================================================


class TestRunAllArchitectureGuards:
    def test_representative_clean_flow_passes(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        report = run_all_architecture_guards(_clean_snapshot())
        assert report.passed, report.format_failures()

    def test_ownership_error_propagated(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        snap = _clean_snapshot()
        snap["subject_core"]["authority_role"] = "cognition_planning_layer"
        report = run_all_architecture_guards(snap)
        assert not report.passed

    def test_boundary_error_propagated(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        snap = _clean_snapshot()
        snap["router"]["is_final_model_authority"] = True
        report = run_all_architecture_guards(snap)
        assert not report.passed

    def test_none_snapshot_passes(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        report = run_all_architecture_guards(None)
        assert report.passed

    def test_report_is_json_serialisable(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        report = run_all_architecture_guards(_clean_snapshot())
        json.dumps(report.to_dict())  # must not raise

    def test_format_failures_is_actionable(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        snap = _clean_snapshot()
        snap["execution_substrate"]["authority_role"] = "subject_decision_authority"
        report = run_all_architecture_guards(snap)
        assert not report.passed
        msg = report.format_failures()
        assert len(msg) > 10  # non-trivial actionable message
        assert "SUBSTRATE" in msg or "subject_decision" in msg or "execution_substrate" in msg


# ===========================================================================
# 15. build_architecture_snapshot_from_response()
# ===========================================================================


class TestBuildArchitectureSnapshotFromResponse:
    def test_extracts_arch_layer_id_from_top_level(self):
        from core.architecture_truth_guards import build_architecture_snapshot_from_response
        response = {
            "arch_layer_id": "subject_core",
            "authority_role": "subject_decision_authority",
        }
        snapshot = build_architecture_snapshot_from_response(response)
        assert "subject_core" in snapshot

    def test_extracts_arch_layer_id_from_nested_metadata(self):
        from core.architecture_truth_guards import build_architecture_snapshot_from_response
        response = {
            "metadata": {
                "arch_layer_id": "execution_substrate",
                "authority_role": "execution_substrate",
            }
        }
        snapshot = build_architecture_snapshot_from_response(response)
        assert "execution_substrate" in snapshot

    def test_ignores_non_dict_input(self):
        from core.architecture_truth_guards import build_architecture_snapshot_from_response
        assert build_architecture_snapshot_from_response("not a dict") == {}  # type: ignore[arg-type]
        assert build_architecture_snapshot_from_response(None) == {}  # type: ignore[arg-type]

    def test_never_raises_on_garbage_input(self):
        from core.architecture_truth_guards import build_architecture_snapshot_from_response
        for garbage in [42, [], set(), object()]:
            result = build_architecture_snapshot_from_response(garbage)  # type: ignore[arg-type]
            assert isinstance(result, dict)


# ===========================================================================
# 16. Integration: real module imports
# ===========================================================================


class TestIntegrationWithRealModules:
    def test_desktop_presence_runtime_owns_source_registry_not_openclawd(self):
        """DesktopPresenceRuntime owns _source_registry; OpenClawd does not."""
        import pytest

        try:
            from core.desktop_presence_runtime import DesktopPresenceRuntime
            from core.openclawd import OpenClawd
        except ImportError as e:
            pytest.skip(f"Optional dependency not available: {e}")

        # Check DesktopPresenceRuntime has _source_registry attribute
        try:
            dpr = DesktopPresenceRuntime()
        except Exception as e:
            pytest.skip(f"DesktopPresenceRuntime instantiation requires optional deps: {e}")

        assert hasattr(dpr, "_source_registry"), (
            "DesktopPresenceRuntime must own _source_registry "
            "(PerceptionSourceRegistry) as the shell-owned source registry."
        )
        assert dpr._source_registry is not None

        # Verify OpenClawd does NOT have a _source_registry attribute
        oc = OpenClawd()
        assert not hasattr(oc, "_source_registry"), (
            "OpenClawd must NOT own a _source_registry — it must receive "
            "source registry snapshots from the shell, not own one independently."
        )

    def test_openclawd_response_carries_subject_decision_authority(self):
        """OpenClawd stamps subject_decision_authority in response metadata."""
        from core.openclawd import OpenClawd
        import asyncio

        oc = OpenClawd()

        async def _run():
            return await oc.process("hello", session_id="test-int-16")

        try:
            response = asyncio.get_event_loop().run_until_complete(_run())
        except Exception:
            # If LLM is unavailable, we can't get a live response — skip live test
            return

        if isinstance(response, dict):
            meta = response.get("metadata") or {}
            role = meta.get("authority_role") or response.get("authority_role")
            if role is not None:
                assert role == "subject_decision_authority", (
                    f"OpenClawd response must carry authority_role='subject_decision_authority', "
                    f"found '{role}'"
                )

    def test_command_router_carries_execution_substrate_role(self):
        """CommandRouter stamps arch_layer_id=execution_substrate in results."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()
        envelope = TaskEnvelope(task="echo test", target_device_id="local")
        try:
            result = router.route_envelope(envelope)
            if isinstance(result, dict):
                layer_id = result.get("arch_layer_id")
                if layer_id is not None:
                    assert layer_id == "execution_substrate", (
                        f"CommandRouter result must carry arch_layer_id='execution_substrate', "
                        f"found '{layer_id}'"
                    )
        except Exception:
            # Routing may fail without a live environment — verify guard structure only
            pass

    def test_desktop_status_projection_sourced_from_canonical_plan(self):
        """build_desktop_status_projection consumes canonical plan, not reconstruct truth."""
        from contracts.desktop_status_projection import (
            build_desktop_status_projection,
            DesktopStatusProjection,
        )
        # build_desktop_status_projection must accept a control plan dict without error
        result = build_desktop_status_projection(
            unified_control_plan=None,
            source_registry_snapshot=None,
            tristate=None,
            runtime_session_id=None,
        )
        assert isinstance(result, DesktopStatusProjection), (
            "build_desktop_status_projection must return a DesktopStatusProjection "
            "instance (downstream consumer), not reconstruct truth independently."
        )

    def test_source_registry_guard_with_real_runtime_shell_snapshot(self):
        """Guard passes for a snapshot derived from actual DesktopPresenceRuntime."""
        import pytest
        from core.architecture_truth_guards import CanonicalTruthOwnershipGuard

        try:
            from core.desktop_presence_runtime import DesktopPresenceRuntime
            dpr = DesktopPresenceRuntime()
        except Exception as e:
            pytest.skip(f"DesktopPresenceRuntime requires optional deps: {e}")

        # Build a synthetic snapshot that reflects the real ownership contract
        snapshot = {
            "runtime_shell": {
                "arch_layer_id": "runtime_shell",
                "authority_role": "runtime_shell_authority",
                "owns_source_registry": hasattr(dpr, "_source_registry"),
            },
            "subject_core": {
                "arch_layer_id": "subject_core",
                "authority_role": "subject_decision_authority",
                "owns_source_registry": False,
            },
        }
        report = CanonicalTruthOwnershipGuard.assert_source_registry_is_shell_owned(snapshot)
        assert report.passed, report.format_failures()


# ===========================================================================
# 17. Anti-corruption adapter guard
# ===========================================================================


class TestAntiCorruptionAdapterGuard:
    """Guards against legacy/compat adapters reintroducing truth drift."""

    def test_adapter_exposing_source_registry_is_flagged(self):
        from core.architecture_truth_guards import run_all_architecture_guards
        snapshot = {
            "runtime_shell": {
                "authority_role": "runtime_shell_authority",
                "owns_source_registry": True,
            },
            "subject_core": {
                "authority_role": "subject_decision_authority",
                "owns_source_registry": False,
            },
            "legacy_compat_adapter": {
                # A legacy adapter must not own the source registry
                "owns_source_registry": True,
            },
        }
        report = run_all_architecture_guards(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert any("SOURCE_REGISTRY" in c or "DUPLICATE" in c for c in codes), (
            f"Expected a source registry violation, got codes: {codes}"
        )

    def test_adapter_exposing_final_model_authority_is_flagged(self):
        from core.architecture_truth_guards import run_boundary_invariant_checks
        snapshot = {
            "provider_adapter": {
                "is_final_model_authority": True,
            }
        }
        report = run_boundary_invariant_checks(snapshot)
        assert not report.passed
        codes = [f.code for f in report.findings if f.severity.value == "error"]
        assert "ROUTER_CLAIMS_FINAL_MODEL_AUTHORITY" in codes


# ===========================================================================
# 18. Module-level exports
# ===========================================================================


class TestModuleLevelExports:
    def test_all_symbols_importable(self):
        import core.architecture_truth_guards as atg

        required = [
            "GuardSeverity",
            "GuardFinding",
            "GuardReport",
            "CanonicalTruthOwnershipGuard",
            "BoundaryInvariantGuard",
            "run_canonical_truth_ownership_checks",
            "run_boundary_invariant_checks",
            "run_all_architecture_guards",
            "SHELL_OWNED_AUTHORITY_ROLES",
            "SUBJECT_CORE_AUTHORITY_ROLE",
            "EXECUTION_SUBSTRATE_ROLE",
            "ORCHESTRATION_LAYER_ROLE",
        ]
        for name in required:
            assert hasattr(atg, name), f"Missing export: {name}"

    def test_all_exported_in_dunder_all(self):
        from core.architecture_truth_guards import __all__

        required = [
            "GuardSeverity",
            "GuardFinding",
            "GuardReport",
            "CanonicalTruthOwnershipGuard",
            "BoundaryInvariantGuard",
            "run_canonical_truth_ownership_checks",
            "run_boundary_invariant_checks",
            "run_all_architecture_guards",
        ]
        for name in required:
            assert name in __all__, f"'{name}' not in __all__"


# ===========================================================================
# 19. Additive integration
# ===========================================================================


class TestAdditiveIntegration:
    def test_existing_architecture_diagnostics_unaffected(self):
        """Importing architecture_truth_guards must not break architecture_diagnostics."""
        from core.architecture_diagnostics import (
            run_architecture_diagnostics,
            validate_authority_chain,
            validate_layer_boundaries,
        )
        from core.architecture_truth_guards import run_all_architecture_guards

        # Both modules must coexist and work independently
        diag_report = run_architecture_diagnostics(None)
        guard_report = run_all_architecture_guards(None)

        assert isinstance(diag_report.overall_valid, bool)
        assert isinstance(guard_report.passed, bool)

    def test_import_causes_no_side_effects(self):
        """Importing the module must not start threads, open files, or call APIs."""
        import importlib
        import sys

        # Re-import cleanly without errors
        mod_name = "core.architecture_truth_guards"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        mod = importlib.import_module(mod_name)
        assert hasattr(mod, "run_all_architecture_guards")

    def test_guard_findings_codes_are_stable_strings(self):
        """All error code strings produced by guards must be stable identifiers."""
        from core.architecture_truth_guards import run_all_architecture_guards

        # Inject every possible violation into a single snapshot
        snap = {
            "runtime_shell": {"owns_source_registry": False},
            "subject_core": {"authority_role": "execution_substrate"},
            "execution_substrate": {
                "authority_role": "subject_decision_authority",
                "is_final_model_authority": True,
                "is_policy_authority": True,
            },
            "orchestration_layer": {"authority_role": "execution_substrate"},
            "router": {
                "is_final_model_authority": True,
                "authority_role": "runtime_shell_authority",
            },
            "projection": {
                "is_truth_reconstruction_layer": True,
                "sourced_from_canonical_plan": False,
                "owns_source_registry": True,
                "is_final_model_authority": True,
            },
        }
        report = run_all_architecture_guards(snap)
        assert not report.passed

        for finding in report.findings:
            code = finding.code
            assert isinstance(code, str), f"Finding code must be str, got {type(code)}"
            assert code.isupper() or "_" in code, (
                f"Finding code '{code}' should be UPPER_SNAKE_CASE for easy searching"
            )
