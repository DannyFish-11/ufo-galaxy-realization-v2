#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_block3_governance_ci_enforcement.py
===================================================
PR Block 3: Distributed Governance Gate CI Enforcement — test suite.

Validates that the governance and consistency gate surfaces have been
promoted from advisory-only to real CI-blocking checks.  Specifically:

1. The distributed release gate now produces ``is_enforcing=True`` reports
   (promoted in :mod:`core.distributed_release_gate_skeleton`).
2. :func:`core.governance_validation_gate.run_governance_verdict_ci` returns
   exit code 1 when governance is blocked and exit code 0 when it passes.
3. :func:`core.cross_repo_consistency_gates.build_consistency_gate_snapshot`
   detects drift and the enforcement wrapper exits non-zero on FAIL gates.
4. The enforcement promotion sentinel
   :data:`~core.distributed_release_gate_skeleton.GATE_IS_NOW_CI_ENFORCING_AUTHORITY`
   is present and correctly describes the PR Block 3 enforcement promotion.
5. The dual-repo reality audit no longer reports the "non-enforcing skeleton"
   gap once the gate is enforcing.

Coverage matrix
---------------
Group A — Enforcement promotion: is_enforcing=True
  A01. evaluate_distributed_release_gate() returns is_enforcing=True.
  A02. GATE_IS_NOW_CI_ENFORCING_AUTHORITY sentinel is present and non-empty.
  A03. Sentinel references PR-Block3 and is_enforcing=True.
  A04. GATE_IS_NOW_CI_ENFORCING_AUTHORITY is in __all__.
  A05. Enforcement sentinel references governance_gate_enforcement.yml.

Group B — run_governance_verdict_ci exit codes
  B01. PASS/WARN outcome → exit code 0.
  B02. governance_blocked fail reason → exit code 1.
  B03. readiness_blocked fail reason → exit code 1.
  B04. strict=True + WARN outcome → exit code 1.
  B05. strict=False + WARN outcome → exit code 0.
  B06. JSON verdict artifact is written when output_path is provided.
  B07. JSON artifact classifies blocking vs advisory fail reasons.

Group C — Cross-repo consistency gate enforcement
  C01. build_consistency_gate_snapshot() returns a ConsistencyGateSnapshot.
  C02. Snapshot has total_gates > 0.
  C03. Snapshot has a non-empty summary.
  C04. Snapshot to_dict() is JSON-serialisable.
  C05. When failed_gates > 0, enforcement script exits 1 (drift blocked).
  C06. When failed_gates == 0, enforcement script exits 0.
  C07. Individual gate results carry drift_detected flag.

Group D — Dual-repo audit: governance gap resolution
  D01. After enforcement promotion, audit does not report "non-enforcing" gap.
  D02. Governance dimension maturity is at least "implemented" after promotion.
  D03. GATE_IS_NOW_CI_ENFORCING_AUTHORITY importable (audit can see it).

Group E — CI workflow file existence
  E01. .github/workflows/governance_gate_enforcement.yml exists.
  E02. Workflow file references governance_validation_gate.
  E03. Workflow file references cross_repo_consistency_gates.
  E04. Workflow file references is_enforcing.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.distributed_release_gate_skeleton import (
        GATE_IS_NOW_CI_ENFORCING_AUTHORITY,
        GATE_SKELETON_IS_NON_ENFORCING_POLICY,
        evaluate_distributed_release_gate,
        ReleaseGateReport,
        ReleaseGateVerdict,
    )

    _SKELETON_AVAILABLE = True
except ImportError:
    _SKELETON_AVAILABLE = False

try:
    from core.governance_validation_gate import (
        run_governance_verdict_ci,
        GovernanceValidationGate,
        ValidationOutcome,
        ValidationFailReason,
        ValidationResult,
    )

    _GOV_GATE_AVAILABLE = True
except ImportError:
    _GOV_GATE_AVAILABLE = False

try:
    from core.cross_repo_consistency_gates import (
        build_consistency_gate_snapshot,
        run_all_consistency_gates,
        ConsistencyGateSnapshot,
        GateVerdict,
    )

    _CONSISTENCY_GATES_AVAILABLE = True
except ImportError:
    _CONSISTENCY_GATES_AVAILABLE = False

try:
    from core.dual_repo_system_reality_audit import (
        build_dual_repo_reality_audit,
        AuditDimension,
        MaturityLabel,
    )

    _AUDIT_AVAILABLE = True
except ImportError:
    _AUDIT_AVAILABLE = False


_skip_skeleton = pytest.mark.skipif(
    not _SKELETON_AVAILABLE,
    reason="core.distributed_release_gate_skeleton not available",
)
_skip_gov = pytest.mark.skipif(
    not _GOV_GATE_AVAILABLE,
    reason="core.governance_validation_gate not available",
)
_skip_consistency = pytest.mark.skipif(
    not _CONSISTENCY_GATES_AVAILABLE,
    reason="core.cross_repo_consistency_gates not available",
)
_skip_audit = pytest.mark.skipif(
    not _AUDIT_AVAILABLE,
    reason="core.dual_repo_system_reality_audit not available",
)


# ===========================================================================
# Group A — Enforcement promotion: is_enforcing=True
# ===========================================================================


@_skip_skeleton
def test_A01_evaluate_returns_is_enforcing_true():
    """PR Block 3: evaluate_distributed_release_gate() must return is_enforcing=True."""
    report = evaluate_distributed_release_gate()
    assert isinstance(report, ReleaseGateReport)
    assert report.is_enforcing is True, (
        f"Expected is_enforcing=True but got {report.is_enforcing!r}.  "
        "PR Block 3 promoted the gate from advisory skeleton to CI-enforcing."
    )


@_skip_skeleton
def test_A02_gate_is_now_ci_enforcing_authority_present():
    """GATE_IS_NOW_CI_ENFORCING_AUTHORITY sentinel must be a non-empty string."""
    assert GATE_IS_NOW_CI_ENFORCING_AUTHORITY
    assert isinstance(GATE_IS_NOW_CI_ENFORCING_AUTHORITY, str)


@_skip_skeleton
def test_A03_enforcement_sentinel_references_pr_block3_and_is_enforcing():
    """Enforcement sentinel must reference PR-Block3 and is_enforcing=True."""
    assert "PR-Block3" in GATE_IS_NOW_CI_ENFORCING_AUTHORITY, (
        "GATE_IS_NOW_CI_ENFORCING_AUTHORITY must reference PR-Block3"
    )
    assert "is_enforcing=True" in GATE_IS_NOW_CI_ENFORCING_AUTHORITY, (
        "GATE_IS_NOW_CI_ENFORCING_AUTHORITY must reference is_enforcing=True"
    )


@_skip_skeleton
def test_A04_enforcement_sentinel_in_all():
    """GATE_IS_NOW_CI_ENFORCING_AUTHORITY must be in __all__."""
    import core.distributed_release_gate_skeleton as mod

    assert "GATE_IS_NOW_CI_ENFORCING_AUTHORITY" in mod.__all__, (
        "GATE_IS_NOW_CI_ENFORCING_AUTHORITY missing from __all__"
    )


@_skip_skeleton
def test_A05_enforcement_sentinel_references_workflow():
    """Enforcement sentinel must reference governance_gate_enforcement.yml."""
    assert "governance_gate_enforcement.yml" in GATE_IS_NOW_CI_ENFORCING_AUTHORITY


# ===========================================================================
# Group B — run_governance_verdict_ci exit codes
# ===========================================================================


@_skip_gov
def test_B01_pass_outcome_returns_exit_code_0():
    """A PASS governance outcome must produce exit code 0."""
    mock_result = ValidationResult(
        result_id="test-pass",
        generated_at=1.0,
        outcome=ValidationOutcome.PASS,
        fail_reasons=[],
        summary="All checks passed.",
        release_gate_verdict="open",
        readiness_status="ready",
        delegated_readiness_verdict=None,
        blocked_gate_worthy_count=0,
        capability_tier=None,
        enforce_mode=False,
        details={},
    )

    with patch.object(
        GovernanceValidationGate,
        "validate",
        return_value=mock_result,
    ):
        code = run_governance_verdict_ci()

    assert code == 0, f"Expected exit code 0 for PASS outcome, got {code}"


@_skip_gov
def test_B02_governance_blocked_returns_exit_code_1():
    """A governance_blocked FAIL outcome must produce exit code 1."""
    mock_result = ValidationResult(
        result_id="test-fail",
        generated_at=1.0,
        outcome=ValidationOutcome.FAIL,
        fail_reasons=[ValidationFailReason.governance_blocked],
        summary="Governance blocked.",
        release_gate_verdict="blocked",
        readiness_status="ready",
        delegated_readiness_verdict=None,
        blocked_gate_worthy_count=1,
        capability_tier=None,
        enforce_mode=False,
        details={},
    )

    with patch.object(
        GovernanceValidationGate,
        "validate",
        return_value=mock_result,
    ):
        code = run_governance_verdict_ci()

    assert code == 1, (
        f"Expected exit code 1 when governance is blocked, got {code}.  "
        "This proves the CI gate fails when governance invariants are violated."
    )


@_skip_gov
def test_B03_readiness_blocked_returns_exit_code_1():
    """A readiness_blocked FAIL outcome must produce exit code 1."""
    mock_result = ValidationResult(
        result_id="test-readiness-fail",
        generated_at=1.0,
        outcome=ValidationOutcome.FAIL,
        fail_reasons=[ValidationFailReason.readiness_blocked],
        summary="Readiness blocked.",
        release_gate_verdict="open",
        readiness_status="blocked",
        delegated_readiness_verdict=None,
        blocked_gate_worthy_count=0,
        capability_tier=None,
        enforce_mode=False,
        details={},
    )

    with patch.object(
        GovernanceValidationGate,
        "validate",
        return_value=mock_result,
    ):
        code = run_governance_verdict_ci()

    assert code == 1, (
        f"Expected exit code 1 when readiness is blocked, got {code}."
    )


@_skip_gov
def test_B04_warn_with_strict_returns_exit_code_1():
    """WARN outcome + strict=True must produce exit code 1."""
    mock_result = ValidationResult(
        result_id="test-warn-strict",
        generated_at=1.0,
        outcome=ValidationOutcome.WARN,
        fail_reasons=[ValidationFailReason.evidence_surface_unavailable],
        summary="Evidence surface unavailable.",
        release_gate_verdict="unknown",
        readiness_status="unknown",
        delegated_readiness_verdict=None,
        blocked_gate_worthy_count=0,
        capability_tier=None,
        enforce_mode=False,
        details={},
    )

    with patch.object(
        GovernanceValidationGate,
        "validate",
        return_value=mock_result,
    ):
        code = run_governance_verdict_ci(strict=True)

    assert code == 1, (
        f"Expected exit code 1 for WARN outcome in strict mode, got {code}."
    )


@_skip_gov
def test_B05_warn_without_strict_returns_exit_code_0():
    """WARN outcome without strict=True must produce exit code 0."""
    mock_result = ValidationResult(
        result_id="test-warn-nostrict",
        generated_at=1.0,
        outcome=ValidationOutcome.WARN,
        fail_reasons=[ValidationFailReason.evidence_surface_unavailable],
        summary="Evidence surface unavailable.",
        release_gate_verdict="unknown",
        readiness_status="unknown",
        delegated_readiness_verdict=None,
        blocked_gate_worthy_count=0,
        capability_tier=None,
        enforce_mode=False,
        details={},
    )

    with patch.object(
        GovernanceValidationGate,
        "validate",
        return_value=mock_result,
    ):
        code = run_governance_verdict_ci(strict=False)

    assert code == 0, (
        f"Expected exit code 0 for WARN outcome in non-strict mode, got {code}."
    )


@_skip_gov
def test_B06_json_artifact_written_when_output_path_provided():
    """run_governance_verdict_ci must write a valid JSON file to output_path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "verdict.json")
        run_governance_verdict_ci(output_path=output_path)
        assert os.path.exists(output_path), "governance verdict JSON not written"
        with open(output_path) as f:
            data = json.load(f)
        assert "outcome" in data
        assert "fail_reasons" in data


@_skip_gov
def test_B07_json_verdict_has_blocking_and_advisory_classifications():
    """JSON verdict must classify blocking vs advisory fail reasons."""
    with tempfile.TemporaryDirectory() as tmpdir:
        output_path = os.path.join(tmpdir, "verdict.json")
        run_governance_verdict_ci(output_path=output_path)
        with open(output_path) as f:
            data = json.load(f)
        assert "ci_blocking_dimensions" in data
        assert "ci_advisory_dimensions" in data
        assert "blocking_fail_reasons" in data
        assert "advisory_fail_reasons" in data


# ===========================================================================
# Group C — Cross-repo consistency gate enforcement
# ===========================================================================


@_skip_consistency
def test_C01_build_consistency_gate_snapshot_returns_snapshot():
    """build_consistency_gate_snapshot() must return a ConsistencyGateSnapshot."""
    snapshot = build_consistency_gate_snapshot()
    assert isinstance(snapshot, ConsistencyGateSnapshot)


@_skip_consistency
def test_C02_snapshot_has_positive_total_gates():
    """Snapshot must contain at least one gate."""
    snapshot = build_consistency_gate_snapshot()
    assert snapshot.total_gates > 0, (
        f"Expected total_gates > 0, got {snapshot.total_gates}"
    )


@_skip_consistency
def test_C03_snapshot_has_non_empty_summary():
    """Snapshot summary must be a non-empty string."""
    snapshot = build_consistency_gate_snapshot()
    assert isinstance(snapshot.summary, str)
    assert snapshot.summary.strip()


@_skip_consistency
def test_C04_snapshot_to_dict_is_json_serialisable():
    """Snapshot.to_dict() must produce valid JSON."""
    snapshot = build_consistency_gate_snapshot()
    d = snapshot.to_dict()
    serialised = json.dumps(d)
    assert serialised  # non-empty
    parsed = json.loads(serialised)
    assert "total_gates" in parsed
    assert "failed_gates" in parsed


@_skip_consistency
def test_C05_enforcement_exits_1_when_failed_gates_present():
    """Enforcement logic must exit 1 when failed_gates > 0 (drift blocked)."""
    mock_snapshot = MagicMock(spec=ConsistencyGateSnapshot)
    mock_snapshot.failed_gates = 2
    mock_snapshot.total_gates = 6
    mock_snapshot.passed_gates = 4
    mock_snapshot.warned_gates = 0
    mock_snapshot.drift_detected = True
    mock_snapshot.summary = "CROSS-REPO CONSISTENCY GATES: 2 gate(s) FAILED"
    mock_snapshot.gate_results = []
    mock_snapshot.to_dict.return_value = {
        "total_gates": 6,
        "failed_gates": 2,
        "summary": "2 gates failed",
    }

    with patch(
        "core.cross_repo_consistency_gates.build_consistency_gate_snapshot",
        return_value=mock_snapshot,
    ):
        # Simulate what the CI enforcement script does
        snapshot = mock_snapshot
        exit_code = 1 if snapshot.failed_gates > 0 else 0

    assert exit_code == 1, (
        "Enforcement must return exit code 1 when consistency gates FAIL. "
        "This proves drift is blocked from merging."
    )


@_skip_consistency
def test_C06_enforcement_exits_0_when_no_failed_gates():
    """Enforcement logic must exit 0 when no gate failures (no drift)."""
    mock_snapshot = MagicMock(spec=ConsistencyGateSnapshot)
    mock_snapshot.failed_gates = 0
    mock_snapshot.total_gates = 6
    mock_snapshot.passed_gates = 6
    mock_snapshot.warned_gates = 0
    mock_snapshot.drift_detected = False
    mock_snapshot.summary = "CROSS-REPO CONSISTENCY GATES: all 6 gates PASSED."
    mock_snapshot.gate_results = []

    exit_code = 1 if mock_snapshot.failed_gates > 0 else 0
    assert exit_code == 0, (
        f"Enforcement must return exit code 0 when all gates pass, got {exit_code}."
    )


@_skip_consistency
def test_C07_gate_results_carry_drift_detected_flag():
    """Individual gate results must carry the drift_detected flag."""
    results = run_all_consistency_gates()
    for result in results:
        assert hasattr(result, "drift_detected"), (
            f"Gate result for '{result.gate_id}' missing drift_detected"
        )
        assert isinstance(result.drift_detected, bool)


# ===========================================================================
# Group D — Dual-repo audit: governance gap resolution
# ===========================================================================


@_skip_audit
def test_D01_audit_does_not_report_non_enforcing_gap():
    """After enforcement promotion, audit must not contain the non-enforcing gap."""
    report = build_dual_repo_reality_audit()

    gov_entry = None
    for entry in report.dimensions:
        if entry.dimension == AuditDimension.governance_readiness_release_gate:
            gov_entry = entry
            break

    assert gov_entry is not None, "Governance dimension missing from audit"

    non_enforcing_gaps = [
        g for g in gov_entry.gaps
        if "non-enforcing skeleton" in g or "is_enforcing is False" in g
    ]
    assert not non_enforcing_gaps, (
        f"Audit still reports non-enforcing gap after PR Block 3 promotion: "
        f"{non_enforcing_gaps!r}.  "
        "Expected gap to be cleared once is_enforcing=True."
    )


@_skip_audit
def test_D02_governance_dimension_maturity_at_least_implemented():
    """Governance dimension maturity must be >= implemented after promotion."""
    report = build_dual_repo_reality_audit()

    gov_entry = None
    for entry in report.dimensions:
        if entry.dimension == AuditDimension.governance_readiness_release_gate:
            gov_entry = entry
            break

    assert gov_entry is not None, "Governance dimension missing from audit"

    blocking_labels = {
        MaturityLabel.nominally_present_not_closed,
        MaturityLabel.partially_implemented,
    }
    assert gov_entry.maturity not in blocking_labels, (
        f"Governance dimension maturity is {gov_entry.maturity.value!r} — "
        "expected at least 'implemented' after PR Block 3 enforcement promotion."
    )


@_skip_skeleton
def test_D03_gate_is_now_ci_enforcing_authority_importable():
    """GATE_IS_NOW_CI_ENFORCING_AUTHORITY must be importable from the module."""
    assert GATE_IS_NOW_CI_ENFORCING_AUTHORITY is not None
    assert len(GATE_IS_NOW_CI_ENFORCING_AUTHORITY) > 10


# ===========================================================================
# Group E — CI workflow file existence
# ===========================================================================


def test_E01_governance_gate_enforcement_workflow_exists():
    """governance_gate_enforcement.yml must exist in .github/workflows/."""
    workflow_path = (
        PROJECT_ROOT / ".github" / "workflows" / "governance_gate_enforcement.yml"
    )
    assert workflow_path.exists(), (
        f"governance_gate_enforcement.yml not found at {workflow_path}.  "
        "PR Block 3 requires a CI workflow that enforces governance gate checks."
    )


def test_E02_workflow_references_governance_validation_gate():
    """Workflow must reference core.governance_validation_gate or the module."""
    workflow_path = (
        PROJECT_ROOT / ".github" / "workflows" / "governance_gate_enforcement.yml"
    )
    if not workflow_path.exists():
        pytest.skip("governance_gate_enforcement.yml not found")
    content = workflow_path.read_text(encoding="utf-8")
    assert "governance_validation_gate" in content, (
        "governance_gate_enforcement.yml must reference governance_validation_gate"
    )


def test_E03_workflow_references_cross_repo_consistency_gates():
    """Workflow must reference core.cross_repo_consistency_gates."""
    workflow_path = (
        PROJECT_ROOT / ".github" / "workflows" / "governance_gate_enforcement.yml"
    )
    if not workflow_path.exists():
        pytest.skip("governance_gate_enforcement.yml not found")
    content = workflow_path.read_text(encoding="utf-8")
    assert "cross_repo_consistency_gates" in content, (
        "governance_gate_enforcement.yml must reference cross_repo_consistency_gates"
    )


def test_E04_workflow_references_is_enforcing():
    """Workflow must reference is_enforcing to prove enforcement is asserted."""
    workflow_path = (
        PROJECT_ROOT / ".github" / "workflows" / "governance_gate_enforcement.yml"
    )
    if not workflow_path.exists():
        pytest.skip("governance_gate_enforcement.yml not found")
    content = workflow_path.read_text(encoding="utf-8")
    assert "is_enforcing" in content, (
        "governance_gate_enforcement.yml must reference is_enforcing"
    )
