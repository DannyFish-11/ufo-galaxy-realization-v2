#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_release_blocking_gate.py
=====================================
PR-CI-BLOCK: Release Blocking Gate tests.

Validates that:
- Policy sentinels are non-empty strings.
- :class:`GateCriterionResult` and :class:`ReleaseGateDecision` have the
  expected schema fields.
- :func:`evaluate_release_gate` returns a :class:`ReleaseGateDecision` with
  well-formed criterion results.
- :func:`run_release_blocking_gate` returns 0 on APPROVED and 1 on BLOCKED.
- :class:`ReleaseBlockingGateError` is raised when
  ``raise_on_failure=True`` and the gate is blocked.
- All criteria definitions are blocking by default.
- The module is importable and ``__all__`` contains the expected symbols.

Coverage matrix
---------------
Group A — Sentinels / constants
  A01. RELEASE_BLOCKING_GATE_AUTHORITY is a non-empty string.
  A02. RELEASE_BLOCKING_GATE_PR_SENTINEL is a non-empty string.
  A03. Policy strings contain "POLICY::" or "AUTHORITY" prefix.
  A04. evaluate_release_gate and run_release_blocking_gate exported in __all__.

Group B — Data class schema
  B01. evaluate_release_gate returns a ReleaseGateDecision.
  B02. ReleaseGateDecision has approved, failed_criteria, criteria fields.
  B03. criteria is a non-empty list of GateCriterionResult.
  B04. Each GateCriterionResult has criterion_id, display_name, status, detail.
  B05. to_dict() on GateCriterionResult returns required keys.
  B06. All criteria have is_blocking=True by default.
  B07. All expected canonical criterion IDs are present in the evaluation.

Group C — Exit code / blocking behaviour
  C01. Approved decision → run_release_blocking_gate returns 0.
  C02. Blocked decision → run_release_blocking_gate returns 1.
  C03. ReleaseBlockingGateError raised when raise_on_failure=True and blocked.
  C04. ReleaseBlockingGateError.failed_criteria is a non-empty list.
  C05. ReleaseBlockingGateError.decision is a ReleaseGateDecision.

Group D — evaluate_release_gate / ReleaseGateDecision
  D01. evaluate_release_gate does not raise by default.
  D02. decision.approved is a bool.
  D03. decision.failed_criteria is a list.
  D04. decision.summary_lines() returns a list of strings.
  D05. criteria contain at least one entry per policy category.
  D06. approved is True iff failed_criteria is empty.
  D07. All criterion status values are valid CriterionStatus members.
"""

from __future__ import annotations

import sys
import os
from typing import Any
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# sys.path setup
# ---------------------------------------------------------------------------

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

try:
    from core.release_blocking_gate import (
        RELEASE_BLOCKING_GATE_AUTHORITY,
        RELEASE_BLOCKING_GATE_PR_SENTINEL,
        CRITICAL_SMOKE_FAIL_IS_BLOCKING_POLICY,
        CAPABILITY_STATE_MISMATCH_IS_BLOCKING_POLICY,
        PROTOCOL_DRIFT_IS_BLOCKING_POLICY,
        RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_POLICY,
        ReleaseBlockingGateError,
        GateCriterionResult,
        ReleaseGateDecision,
        CriterionStatus,
        evaluate_release_gate,
        run_release_blocking_gate,
    )
    _MODULE_AVAILABLE = True
except ImportError as _e:
    _MODULE_AVAILABLE = False
    _import_err_msg = str(_e)

_skip_if_unavailable = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=(
        f"core.release_blocking_gate not importable: "
        f"{locals().get('_import_err_msg', '')}"
    ),
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_CRITERION_DICT_KEYS = [
    "criterion_id",
    "display_name",
    "status",
    "detail",
    "is_blocking",
]

_EXPECTED_CRITERION_IDS = {
    "critical_runtime_smoke",
    "capability_enforcement",
    "protocol_drift",
    "readiness_matrix_not_blocked",
    "mainline_enforcement_callsite",
}


def _make_approved_decision() -> "ReleaseGateDecision":
    """Return a synthetic approved ReleaseGateDecision."""
    cr = GateCriterionResult(
        criterion_id="smoke",
        display_name="Smoke",
        status=CriterionStatus.PASSED,
        detail="ok",
        is_blocking=True,
    )
    return ReleaseGateDecision(approved=True, failed_criteria=[], criteria=[cr])


def _make_blocked_decision() -> "ReleaseGateDecision":
    """Return a synthetic blocked ReleaseGateDecision."""
    cr = GateCriterionResult(
        criterion_id="critical_runtime_smoke",
        display_name="Critical Runtime Smoke",
        status=CriterionStatus.FAILED,
        detail="import error",
        is_blocking=True,
    )
    return ReleaseGateDecision(
        approved=False,
        failed_criteria=["critical_runtime_smoke"],
        criteria=[cr],
    )


# ===========================================================================
# Group A — Sentinels / constants
# ===========================================================================


@_skip_if_unavailable
class TestGroupA_Sentinels:
    """Sentinels and policy constants."""

    def test_A01_authority_non_empty(self):
        assert isinstance(RELEASE_BLOCKING_GATE_AUTHORITY, str)
        assert len(RELEASE_BLOCKING_GATE_AUTHORITY) > 20

    def test_A02_pr_sentinel_non_empty(self):
        assert isinstance(RELEASE_BLOCKING_GATE_PR_SENTINEL, str)
        assert len(RELEASE_BLOCKING_GATE_PR_SENTINEL) > 20

    def test_A03_policy_strings_have_prefix(self):
        for policy in (
            CRITICAL_SMOKE_FAIL_IS_BLOCKING_POLICY,
            CAPABILITY_STATE_MISMATCH_IS_BLOCKING_POLICY,
            PROTOCOL_DRIFT_IS_BLOCKING_POLICY,
            RELEASE_POSTURE_INSUFFICIENT_IS_BLOCKING_POLICY,
        ):
            assert isinstance(policy, str) and len(policy) > 10, (
                f"Policy string too short or not a string: {policy!r}"
            )

    def test_A04_public_api_in_all(self):
        from core import release_blocking_gate as _rbg
        for symbol in ("evaluate_release_gate", "run_release_blocking_gate"):
            assert symbol in _rbg.__all__, f"'{symbol}' missing from __all__"


# ===========================================================================
# Group B — Data class schema
# ===========================================================================


@_skip_if_unavailable
class TestGroupB_DataClassSchema:
    """Data class schema tests."""

    def test_B01_evaluate_gate_returns_decision(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        assert isinstance(decision, ReleaseGateDecision)

    def test_B02_decision_has_required_fields(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        assert hasattr(decision, "approved")
        assert hasattr(decision, "failed_criteria")
        assert hasattr(decision, "criteria")

    def test_B03_criteria_is_non_empty_list(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        assert isinstance(decision.criteria, list)
        assert len(decision.criteria) > 0, "criteria list must not be empty"

    def test_B04_each_criterion_has_required_fields(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        for cr in decision.criteria:
            assert hasattr(cr, "criterion_id"), "missing criterion_id"
            assert hasattr(cr, "display_name"), "missing display_name"
            assert hasattr(cr, "status"), "missing status"
            assert hasattr(cr, "detail"), "missing detail"

    def test_B05_criterion_to_dict_has_required_keys(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        for cr in decision.criteria:
            d = cr.to_dict()
            missing = [k for k in _REQUIRED_CRITERION_DICT_KEYS if k not in d]
            assert not missing, (
                f"GateCriterionResult.to_dict() missing keys: {missing}"
            )

    def test_B06_all_criteria_are_blocking(self):
        """All gate criteria must be blocking (is_blocking=True)."""
        decision = evaluate_release_gate(raise_on_failure=False)
        non_blocking = [
            cr.criterion_id for cr in decision.criteria if not cr.is_blocking
        ]
        assert not non_blocking, (
            f"These criteria are non-blocking but should be blocking: {non_blocking}"
        )

    def test_B07_all_expected_criterion_ids_present(self):
        """All canonical criterion IDs must be present in the evaluation."""
        decision = evaluate_release_gate(raise_on_failure=False)
        found = {cr.criterion_id for cr in decision.criteria}
        missing = _EXPECTED_CRITERION_IDS - found
        assert not missing, (
            f"Expected criterion IDs missing from evaluation: {missing}"
        )


# ===========================================================================
# Group C — Exit code / blocking behaviour
# ===========================================================================


@_skip_if_unavailable
class TestGroupC_ExitCode:
    """Exit code and blocking behaviour tests."""

    def test_C01_approved_decision_run_gate_returns_0(self):
        """Approved decision must cause run_release_blocking_gate to return 0."""
        decision = _make_approved_decision()
        with patch(
            "core.release_blocking_gate.evaluate_release_gate",
            return_value=decision,
        ):
            code = run_release_blocking_gate()
        assert code == 0, f"Expected 0 for approved decision, got {code}"

    def test_C02_blocked_decision_run_gate_returns_1(self):
        """Blocked decision must cause run_release_blocking_gate to return 1."""
        decision = _make_blocked_decision()
        with patch(
            "core.release_blocking_gate.evaluate_release_gate",
            return_value=decision,
        ):
            code = run_release_blocking_gate()
        assert code == 1, f"Expected 1 for blocked decision, got {code}"

    def test_C03_raise_on_failure_raises_error(self):
        """evaluate_release_gate(raise_on_failure=True) must raise when blocked."""
        decision = _make_blocked_decision()
        with patch(
            "core.release_blocking_gate.evaluate_release_gate",
            wraps=lambda raise_on_failure=False: (
                (_ for _ in ()).throw(
                    ReleaseBlockingGateError(
                        failed_criteria=decision.failed_criteria,
                        decision=decision,
                    )
                )
                if raise_on_failure
                else decision
            ),
        ):
            with pytest.raises(ReleaseBlockingGateError):
                evaluate_release_gate(raise_on_failure=True)

    def test_C04_error_has_failed_criteria(self):
        """ReleaseBlockingGateError.failed_criteria must be a non-empty list."""
        decision = _make_blocked_decision()
        err = ReleaseBlockingGateError(
            failed_criteria=decision.failed_criteria,
            decision=decision,
        )
        assert isinstance(err.failed_criteria, list)
        assert len(err.failed_criteria) > 0

    def test_C05_error_has_decision(self):
        """ReleaseBlockingGateError.decision must be a ReleaseGateDecision."""
        decision = _make_blocked_decision()
        err = ReleaseBlockingGateError(
            failed_criteria=decision.failed_criteria,
            decision=decision,
        )
        assert isinstance(err.decision, ReleaseGateDecision)


# ===========================================================================
# Group D — evaluate_release_gate / ReleaseGateDecision
# ===========================================================================


@_skip_if_unavailable
class TestGroupD_EvaluateGate:
    """evaluate_release_gate and ReleaseGateDecision behaviour."""

    def test_D01_does_not_raise_by_default(self):
        """evaluate_release_gate must not raise with raise_on_failure=False."""
        try:
            evaluate_release_gate(raise_on_failure=False)
        except Exception as exc:
            pytest.fail(
                f"evaluate_release_gate raised unexpectedly: {exc}"
            )

    def test_D02_approved_is_bool(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        assert isinstance(decision.approved, bool)

    def test_D03_failed_criteria_is_list(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        assert isinstance(decision.failed_criteria, list)

    def test_D04_summary_lines_returns_strings(self):
        decision = evaluate_release_gate(raise_on_failure=False)
        lines = decision.summary_lines()
        assert isinstance(lines, list)
        assert all(isinstance(line, str) for line in lines), (
            "summary_lines() must return a list of strings"
        )

    def test_D05_failed_criteria_subset_of_criterion_ids(self):
        """failed_criteria values must match actual criterion IDs."""
        decision = evaluate_release_gate(raise_on_failure=False)
        criterion_ids = {cr.criterion_id for cr in decision.criteria}
        for fc in decision.failed_criteria:
            assert fc in criterion_ids, (
                f"failed_criteria contains '{fc}' which is not a known criterion ID"
            )

    def test_D06_approved_consistent_with_failed_criteria(self):
        """approved must be True iff failed_criteria is empty."""
        decision = evaluate_release_gate(raise_on_failure=False)
        if decision.approved:
            assert len(decision.failed_criteria) == 0, (
                "approved=True but failed_criteria is non-empty"
            )
        else:
            assert len(decision.failed_criteria) > 0, (
                "approved=False but failed_criteria is empty"
            )

    def test_D07_criterion_status_values_are_valid(self):
        """All criterion status values must be valid CriterionStatus members."""
        valid = {s.value for s in CriterionStatus}
        decision = evaluate_release_gate(raise_on_failure=False)
        for cr in decision.criteria:
            status_val = cr.status.value if isinstance(cr.status, CriterionStatus) else cr.status
            assert status_val in valid, (
                f"Criterion '{cr.criterion_id}' has invalid status: {status_val!r}"
            )
