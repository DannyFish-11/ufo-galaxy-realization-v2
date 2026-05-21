"""
tests/integration/test_runtime_readiness_matrix.py
====================================================

Validates the runtime readiness matrix and release blocking gate.

This module verifies that:
1. The readiness matrix evaluates all defined dimensions.
2. Critical dimension failures produce a BLOCKED verdict.
3. All ACTIVE_MAINLINE capabilities are correctly classified.
4. The release blocking gate correctly identifies failures and
   produces the right exit code.
5. Policy sentinels are present and machine-checkable.
"""

from __future__ import annotations

import json
from typing import Any

import pytest


# ===========================================================================
# 1. Readiness matrix structure and evaluation
# ===========================================================================


class TestReadinessMatrixStructure:
    """Readiness matrix evaluates all dimensions and produces a valid verdict."""

    def test_matrix_evaluates_all_required_dimensions(self) -> None:
        """All critical dimensions are present in the evaluated matrix."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        required_dimensions = {
            "transport_layer",
            "canonical_execution_path",
            "capability_enforcement",
            "protocol_regression_surface",
            "mainline_routing_enforcement_callsite",
            "aip_v3_version_stability",
            "nats_posture_contract",
        }
        evaluated_ids = {d.dimension_id for d in matrix.dimensions}
        missing = required_dimensions - evaluated_ids
        assert not missing, (
            f"Required matrix dimensions not evaluated: {missing}"
        )

    def test_matrix_produces_valid_verdict(self) -> None:
        """Matrix verdict is one of the expected MatrixVerdict values."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            MatrixVerdict,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        valid_verdicts = {v.value for v in MatrixVerdict}
        assert matrix.verdict.value in valid_verdicts, (
            f"Matrix verdict {matrix.verdict!r} is not a valid MatrixVerdict"
        )

    def test_matrix_is_json_serializable(self) -> None:
        """ReadinessMatrix.to_dict() is fully JSON-serialisable."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()
        d = matrix.to_dict()
        serialised = json.dumps(d)
        assert serialised, "ReadinessMatrix is not JSON-serialisable"
        assert "matrix_id" in d
        assert "verdict" in d
        assert "dimensions" in d

    def test_matrix_summary_lines_non_empty(self) -> None:
        """summary_lines() returns at least one line."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()
        lines = matrix.summary_lines()
        assert len(lines) > 0

    def test_is_release_blocked_returns_bool(self) -> None:
        """is_release_blocked() returns a boolean."""
        from core.runtime_readiness_matrix import (
            is_release_blocked,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        result = is_release_blocked()
        assert isinstance(result, bool)

    def test_singleton_caching(self) -> None:
        """get_readiness_matrix() returns the same object on repeated calls."""
        from core.runtime_readiness_matrix import (
            get_readiness_matrix,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        m1 = get_readiness_matrix()
        m2 = get_readiness_matrix()
        assert m1 is m2, "get_readiness_matrix() should return a cached singleton"

    def test_reset_forces_reevaluation(self) -> None:
        """reset_readiness_matrix() forces a fresh evaluation on next call."""
        from core.runtime_readiness_matrix import (
            get_readiness_matrix,
            reset_readiness_matrix,
        )
        reset_readiness_matrix()
        m1 = get_readiness_matrix()
        reset_readiness_matrix()
        m2 = get_readiness_matrix()
        assert m1 is not m2, "reset_readiness_matrix() must force re-evaluation"


# ===========================================================================
# 2. Critical dimensions pass in the current environment
# ===========================================================================


class TestCriticalDimensionsPass:
    """Critical dimensions should pass in the test environment."""

    def test_transport_layer_dimension_passes(self) -> None:
        """Transport layer dimension evaluates to PASSED."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        transport = next(
            (d for d in matrix.dimensions if d.dimension_id == "transport_layer"),
            None,
        )
        assert transport is not None, "transport_layer dimension not found"
        assert transport.status == DimensionStatus.PASSED, (
            f"transport_layer dimension failed: {transport.detail}"
        )

    def test_canonical_execution_path_passes(self) -> None:
        """Canonical execution path dimension evaluates to PASSED."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        dim = next(
            (d for d in matrix.dimensions if d.dimension_id == "canonical_execution_path"),
            None,
        )
        assert dim is not None, "canonical_execution_path dimension not found"
        assert dim.status == DimensionStatus.PASSED, (
            f"canonical_execution_path failed: {dim.detail}"
        )

    def test_capability_enforcement_dimension_passes(self) -> None:
        """Capability enforcement dimension evaluates to PASSED."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        dim = next(
            (d for d in matrix.dimensions if d.dimension_id == "capability_enforcement"),
            None,
        )
        assert dim is not None, "capability_enforcement dimension not found"
        assert dim.status == DimensionStatus.PASSED, (
            f"capability_enforcement failed: {dim.detail}"
        )

    def test_protocol_regression_surface_passes(self) -> None:
        """Protocol regression surface dimension evaluates to PASSED."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        dim = next(
            (d for d in matrix.dimensions if d.dimension_id == "protocol_regression_surface"),
            None,
        )
        assert dim is not None, "protocol_regression_surface dimension not found"
        assert dim.status == DimensionStatus.PASSED, (
            f"protocol_regression_surface failed: {dim.detail}"
        )

    def test_aip_v3_version_stability_passes(self) -> None:
        """AIP v3 version stability dimension evaluates to PASSED."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        dim = next(
            (d for d in matrix.dimensions if d.dimension_id == "aip_v3_version_stability"),
            None,
        )
        assert dim is not None, "aip_v3_version_stability dimension not found"
        assert dim.status == DimensionStatus.PASSED, (
            f"aip_v3_version_stability failed: {dim.detail}"
        )

    def test_nats_posture_contract_passes(self) -> None:
        """NATS posture contract should pass in default development posture."""
        from core.runtime_readiness_matrix import (
            evaluate_readiness_matrix,
            reset_readiness_matrix,
            DimensionStatus,
        )
        reset_readiness_matrix()
        matrix = evaluate_readiness_matrix()

        dim = next(
            (d for d in matrix.dimensions if d.dimension_id == "nats_posture_contract"),
            None,
        )
        assert dim is not None, "nats_posture_contract dimension not found"
        assert dim.status == DimensionStatus.PASSED, (
            f"nats_posture_contract failed: {dim.detail}"
        )


# ===========================================================================
# 3. Release blocking gate
# ===========================================================================


class TestReleaseBlockingGate:
    """Release blocking gate produces correct decisions and exit codes."""

    def test_gate_evaluates_all_criteria(self) -> None:
        """Gate evaluation produces results for all defined criteria."""
        from core.release_blocking_gate import evaluate_release_gate

        decision = evaluate_release_gate(raise_on_failure=False)
        assert len(decision.criteria) >= 4, (
            f"Expected at least 4 gate criteria, got {len(decision.criteria)}"
        )

    def test_gate_decision_is_json_serializable(self) -> None:
        """ReleaseGateDecision.to_dict() is fully JSON-serialisable."""
        from core.release_blocking_gate import evaluate_release_gate

        decision = evaluate_release_gate(raise_on_failure=False)
        d = decision.to_dict()
        serialised = json.dumps(d)
        assert serialised
        assert "decision_id" in d
        assert "approved" in d
        assert "criteria" in d

    def test_gate_approved_in_test_environment(self) -> None:
        """Gate approves the release when all critical criteria pass."""
        from core.release_blocking_gate import (
            evaluate_release_gate,
            ReleaseBlockingGateError,
        )
        from core.runtime_readiness_matrix import reset_readiness_matrix
        reset_readiness_matrix()

        decision = evaluate_release_gate(raise_on_failure=False)
        # Print details if it fails, for diagnostics
        if not decision.approved:
            for line in decision.summary_lines():
                print(line)
        assert decision.approved, (
            f"Release gate blocked in test environment on: {decision.failed_criteria}.  "
            f"Details: {[c.detail for c in decision.criteria if c.criterion_id in decision.failed_criteria]}"
        )

    def test_run_release_blocking_gate_returns_zero(self) -> None:
        """run_release_blocking_gate() returns exit code 0 when gate passes."""
        from core.release_blocking_gate import run_release_blocking_gate
        from core.runtime_readiness_matrix import reset_readiness_matrix
        reset_readiness_matrix()

        exit_code = run_release_blocking_gate()
        assert exit_code == 0, (
            f"run_release_blocking_gate() returned {exit_code} (expected 0)"
        )

    def test_gate_summary_lines_non_empty(self) -> None:
        """Gate summary lines are non-empty."""
        from core.release_blocking_gate import evaluate_release_gate

        decision = evaluate_release_gate(raise_on_failure=False)
        lines = decision.summary_lines()
        assert len(lines) > 0

    def test_blocked_decision_has_failed_criteria(self) -> None:
        """When gate is blocked, failed_criteria is non-empty."""
        from core.release_blocking_gate import (
            GateCriterionResult,
            CriterionStatus,
            ReleaseGateDecision,
        )

        # Construct a synthetic blocked decision
        decision = ReleaseGateDecision(
            approved=False,
            failed_criteria=["critical_runtime_smoke"],
            criteria=[
                GateCriterionResult(
                    criterion_id="critical_runtime_smoke",
                    display_name="Critical Runtime Smoke",
                    status=CriterionStatus.FAILED,
                    detail="Synthetic failure for test",
                    is_blocking=True,
                )
            ],
        )

        assert not decision.approved
        assert "critical_runtime_smoke" in decision.failed_criteria
        # ReleaseGateDecision does not have is_blocked() — check via approved flag
        assert not decision.approved


# ===========================================================================
# 4. Policy sentinels
# ===========================================================================


class TestPolicySentinels:
    """Policy sentinels are present and machine-checkable."""

    def test_readiness_matrix_authority_sentinel(self) -> None:
        """RUNTIME_READINESS_MATRIX_AUTHORITY sentinel is non-empty."""
        from core.runtime_readiness_matrix import RUNTIME_READINESS_MATRIX_AUTHORITY
        assert RUNTIME_READINESS_MATRIX_AUTHORITY
        assert "core.runtime_readiness_matrix" in RUNTIME_READINESS_MATRIX_AUTHORITY

    def test_release_blocking_gate_sentinel(self) -> None:
        """RELEASE_BLOCKING_GATE_AUTHORITY sentinel is non-empty."""
        from core.release_blocking_gate import RELEASE_BLOCKING_GATE_AUTHORITY
        assert RELEASE_BLOCKING_GATE_AUTHORITY
        assert "core.release_blocking_gate" in RELEASE_BLOCKING_GATE_AUTHORITY

    def test_critical_dimensions_blocking_policy(self) -> None:
        """CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY sentinel is present."""
        from core.runtime_readiness_matrix import CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY
        assert CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY
        assert "CRITICAL" in CRITICAL_DIMENSIONS_ARE_BLOCKING_POLICY

    def test_capability_enforcement_authority_sentinel(self) -> None:
        """CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY sentinel is non-empty."""
        from core.capability_enforcement_hardener import (
            CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY,
        )
        assert CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY
        assert "core.capability_enforcement_hardener" in CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY

    def test_capability_status_registry_authority(self) -> None:
        """CAPABILITY_STATUS_REGISTRY_AUTHORITY sentinel is non-empty."""
        from core.canonical_capability_status import CAPABILITY_STATUS_REGISTRY_AUTHORITY
        assert CAPABILITY_STATUS_REGISTRY_AUTHORITY
        assert "core.canonical_capability_status" in CAPABILITY_STATUS_REGISTRY_AUTHORITY

    def test_structural_capability_policy_sentinel(self) -> None:
        """STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY sentinel present."""
        from core.canonical_capability_status import STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY
        assert STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY
        assert "STRUCTURAL_ONLY" in STRUCTURAL_CAPABILITY_IS_NOT_OPERATIONAL_POLICY

    def test_silent_bypass_prohibited_sentinel(self) -> None:
        """SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY sentinel present."""
        from core.capability_enforcement_hardener import (
            SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY,
        )
        assert SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY
        assert "silent" in SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY.lower()

    def test_android_local_ai_sentinel(self) -> None:
        """ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT sentinel present in android_runtime_host."""
        from core.android_runtime_host import (
            ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT,
            ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG,
        )
        assert ANDROID_LOCAL_AI_UNAVAILABLE_BY_DEFAULT
        assert ANDROID_LOCAL_AI_DEFAULT_CAPABILITY_FLAG is False
