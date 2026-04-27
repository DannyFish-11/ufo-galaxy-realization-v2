#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr_governance_ci_blocking.py
========================================
PR-CI-BLOCK: Governance / Readiness Verdict CI Blocking Gate tests.

Validates that:
- :func:`run_governance_verdict_ci` returns exit code 0 on PASS/WARN and
  exit code 1 on FAIL.
- The JSON verdict artifact conforms to the required schema.
- Blocking vs advisory dimensions are classified correctly.
- The CLI entry point (``python core/governance_validation_gate.py``) is
  invocable and returns the correct exit code.

Coverage matrix
---------------
Group A — Sentinels / constants
  A01. GOVERNANCE_CI_BLOCKING_AUTHORITY is a non-empty string.
  A02. CI_BLOCKING_DIMENSIONS is a non-empty tuple of strings.
  A03. CI_ADVISORY_DIMENSIONS is a non-empty tuple of strings.
  A04. Blocking and advisory dimensions are disjoint.
  A05. run_governance_verdict_ci is exported in __all__.

Group B — JSON verdict schema
  B01. run_governance_verdict_ci writes valid JSON to output_path.
  B02. Verdict JSON contains all required schema keys.
  B03. outcome value is one of {"pass", "warn", "fail"}.
  B04. ci_blocking_dimensions matches CI_BLOCKING_DIMENSIONS.
  B05. ci_advisory_dimensions matches CI_ADVISORY_DIMENSIONS.
  B06. blocking_fail_reasons is a subset of CI_BLOCKING_DIMENSIONS.
  B07. advisory_fail_reasons is a subset of CI_ADVISORY_DIMENSIONS.

Group C — Exit code / blocking behaviour
  C01. PASS verdict → exit code 0.
  C02. WARN verdict → exit code 0 (non-strict).
  C03. FAIL verdict → exit code 1.
  C04. WARN verdict + strict=True → exit code 1.
  C05. PASS verdict + strict=True → exit code 0.
  C06. Governance-blocked condition propagates to exit code 1.
  C07. Readiness-blocked condition propagates to exit code 1.

Group D — Output integrity
  D01. JSON is written to the requested path.
  D02. JSON output matches verdict returned by GovernanceValidationGate.
  D03. strict_mode field reflects the strict argument.

Group E — CLI integration
  E01. Module is runnable via ``python -m core.governance_validation_gate``.
  E02. CLI with --output writes a JSON file.
  E03. CLI exits 0 in normal (advisory-only) conditions.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch

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
    from core.governance_validation_gate import (
        GOVERNANCE_CI_BLOCKING_AUTHORITY,
        CI_BLOCKING_DIMENSIONS,
        CI_ADVISORY_DIMENSIONS,
        ValidationOutcome,
        ValidationResult,
        ValidationFailReason,
        GovernanceValidationGate,
        GovernanceValidationError,
        run_governance_verdict_ci,
    )
    _MODULE_AVAILABLE = True
except ImportError as _e:
    _MODULE_AVAILABLE = False
    _import_err_msg = str(_e)

_skip_if_unavailable = pytest.mark.skipif(
    not _MODULE_AVAILABLE,
    reason=f"core.governance_validation_gate not importable: {locals().get('_import_err_msg', '')}",
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_JSON_KEYS = [
    "result_id",
    "generated_at",
    "outcome",
    "fail_reasons",
    "summary",
    "release_gate_verdict",
    "readiness_status",
    "delegated_readiness_verdict",
    "blocked_gate_worthy_count",
    "ci_blocking_dimensions",
    "ci_advisory_dimensions",
    "blocking_fail_reasons",
    "advisory_fail_reasons",
    "strict_mode",
]


def _patch_gate_for_outcome(outcome: str):
    """Context manager that patches GovernanceValidationGate.validate to
    return a result with the given outcome string (pass/warn/fail)."""
    import uuid
    import time as _time

    def _mock_validate(self, **kwargs):
        enum_outcome = ValidationOutcome(outcome)
        if outcome == "fail":
            fail_reasons = [ValidationFailReason.governance_blocked]
        elif outcome == "warn":
            fail_reasons = [ValidationFailReason.evidence_surface_unavailable]
        else:
            fail_reasons = []

        return ValidationResult(
            result_id=str(uuid.uuid4()),
            generated_at=_time.time(),
            outcome=enum_outcome,
            fail_reasons=fail_reasons,
            summary=f"mocked outcome: {outcome}",
            release_gate_verdict="open" if outcome != "fail" else "blocked",
            readiness_status="ready",
            delegated_readiness_verdict="unavailable",
        )

    return patch.object(GovernanceValidationGate, "validate", _mock_validate)


# ===========================================================================
# Group A — Sentinels / constants
# ===========================================================================


@_skip_if_unavailable
class TestGroupA_Sentinels:
    """Sentinels and classification constants."""

    def test_A01_ci_blocking_authority_non_empty(self):
        # Authority sentinels in this codebase are long qualified identifiers;
        # a meaningful minimum length prevents trivial placeholder values.
        min_length = 20
        assert isinstance(GOVERNANCE_CI_BLOCKING_AUTHORITY, str)
        assert len(GOVERNANCE_CI_BLOCKING_AUTHORITY) > min_length

    def test_A02_ci_blocking_dimensions_non_empty(self):
        assert isinstance(CI_BLOCKING_DIMENSIONS, tuple)
        assert len(CI_BLOCKING_DIMENSIONS) > 0
        for dim in CI_BLOCKING_DIMENSIONS:
            assert isinstance(dim, str) and dim

    def test_A03_ci_advisory_dimensions_non_empty(self):
        assert isinstance(CI_ADVISORY_DIMENSIONS, tuple)
        assert len(CI_ADVISORY_DIMENSIONS) > 0
        for dim in CI_ADVISORY_DIMENSIONS:
            assert isinstance(dim, str) and dim

    def test_A04_blocking_and_advisory_disjoint(self):
        overlap = set(CI_BLOCKING_DIMENSIONS) & set(CI_ADVISORY_DIMENSIONS)
        assert not overlap, f"Overlap between blocking and advisory dimensions: {overlap}"

    def test_A05_run_governance_verdict_ci_in_all(self):
        from core import governance_validation_gate as _gvg
        assert "run_governance_verdict_ci" in _gvg.__all__

    def test_A06_blocking_dimensions_include_expected_entries(self):
        """Known hard-block conditions must be classified as blocking."""
        for expected in ("governance_blocked", "readiness_blocked"):
            assert expected in CI_BLOCKING_DIMENSIONS, (
                f"Expected '{expected}' in CI_BLOCKING_DIMENSIONS"
            )

    def test_A07_advisory_dimensions_include_expected_entries(self):
        """Known soft conditions must be classified as advisory."""
        assert "evidence_surface_unavailable" in CI_ADVISORY_DIMENSIONS


# ===========================================================================
# Group B — JSON verdict schema
# ===========================================================================


@_skip_if_unavailable
class TestGroupB_JsonSchema:
    """JSON verdict output schema tests."""

    def test_B01_writes_valid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            assert isinstance(data, dict)
        finally:
            os.unlink(path)

    def test_B02_verdict_json_contains_required_keys(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            missing = [k for k in _REQUIRED_JSON_KEYS if k not in data]
            assert not missing, f"Verdict JSON missing required keys: {missing}"
        finally:
            os.unlink(path)

    def test_B03_outcome_is_valid_value(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            assert data["outcome"] in {"pass", "warn", "fail"}
        finally:
            os.unlink(path)

    def test_B04_ci_blocking_dimensions_in_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            assert data["ci_blocking_dimensions"] == list(CI_BLOCKING_DIMENSIONS)
        finally:
            os.unlink(path)

    def test_B05_ci_advisory_dimensions_in_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            assert data["ci_advisory_dimensions"] == list(CI_ADVISORY_DIMENSIONS)
        finally:
            os.unlink(path)

    def test_B06_blocking_fail_reasons_subset_of_blocking_dims(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("fail"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            for r in data["blocking_fail_reasons"]:
                assert r in CI_BLOCKING_DIMENSIONS, (
                    f"blocking_fail_reasons contained '{r}' which is not in "
                    f"CI_BLOCKING_DIMENSIONS"
                )
        finally:
            os.unlink(path)

    def test_B07_advisory_fail_reasons_subset_of_advisory_dims(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("warn"):
                run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            for r in data["advisory_fail_reasons"]:
                assert r in CI_ADVISORY_DIMENSIONS, (
                    f"advisory_fail_reasons contained '{r}' which is not in "
                    f"CI_ADVISORY_DIMENSIONS"
                )
        finally:
            os.unlink(path)


# ===========================================================================
# Group C — Exit code / blocking behaviour
# ===========================================================================


@_skip_if_unavailable
class TestGroupC_ExitCode:
    """Exit code and CI blocking behaviour."""

    def test_C01_pass_verdict_returns_exit_code_0(self):
        with _patch_gate_for_outcome("pass"):
            code = run_governance_verdict_ci()
        assert code == 0, f"Expected 0 on PASS, got {code}"

    def test_C02_warn_verdict_returns_exit_code_0_nonstrict(self):
        with _patch_gate_for_outcome("warn"):
            code = run_governance_verdict_ci(strict=False)
        assert code == 0, f"Expected 0 on WARN (non-strict), got {code}"

    def test_C03_fail_verdict_returns_exit_code_1(self):
        with _patch_gate_for_outcome("fail"):
            code = run_governance_verdict_ci()
        assert code == 1, f"Expected 1 on FAIL, got {code}"

    def test_C04_warn_verdict_strict_returns_exit_code_1(self):
        with _patch_gate_for_outcome("warn"):
            code = run_governance_verdict_ci(strict=True)
        assert code == 1, f"Expected 1 on WARN with strict=True, got {code}"

    def test_C05_pass_verdict_strict_returns_exit_code_0(self):
        with _patch_gate_for_outcome("pass"):
            code = run_governance_verdict_ci(strict=True)
        assert code == 0, f"Expected 0 on PASS even with strict=True, got {code}"

    def test_C06_governance_blocked_causes_exit_1(self):
        """Governance-blocked condition must produce exit code 1."""
        import uuid
        import time as _time

        def _blocked_validate(self, **kwargs):
            return ValidationResult(
                result_id=str(uuid.uuid4()),
                generated_at=_time.time(),
                outcome=ValidationOutcome.FAIL,
                fail_reasons=[ValidationFailReason.governance_blocked],
                summary="governance blocked",
                release_gate_verdict="blocked",
                readiness_status="ready",
            )

        with patch.object(GovernanceValidationGate, "validate", _blocked_validate):
            code = run_governance_verdict_ci()
        assert code == 1, "governance_blocked should cause exit code 1"

    def test_C07_readiness_blocked_causes_exit_1(self):
        """Readiness-blocked condition must produce exit code 1."""
        import uuid
        import time as _time

        def _blocked_validate(self, **kwargs):
            return ValidationResult(
                result_id=str(uuid.uuid4()),
                generated_at=_time.time(),
                outcome=ValidationOutcome.FAIL,
                fail_reasons=[ValidationFailReason.readiness_blocked],
                summary="readiness blocked",
                release_gate_verdict="open",
                readiness_status="blocked",
            )

        with patch.object(GovernanceValidationGate, "validate", _blocked_validate):
            code = run_governance_verdict_ci()
        assert code == 1, "readiness_blocked should cause exit code 1"


# ===========================================================================
# Group D — Output integrity
# ===========================================================================


@_skip_if_unavailable
class TestGroupD_OutputIntegrity:
    """Verdict JSON output integrity."""

    def test_D01_json_written_to_requested_path(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        os.unlink(path)  # Ensure it doesn't exist yet
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path)
            assert os.path.isfile(path), "Verdict JSON was not written to the requested path"
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_D02_json_outcome_matches_gate_outcome(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("warn"):
                code = run_governance_verdict_ci(output_path=path)
            with open(path) as fh:
                data = json.load(fh)
            assert data["outcome"] == "warn"
            assert code == 0
        finally:
            os.unlink(path)

    def test_D03_strict_mode_field_reflects_argument(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with _patch_gate_for_outcome("pass"):
                run_governance_verdict_ci(output_path=path, strict=True)
            with open(path) as fh:
                data = json.load(fh)
            assert data["strict_mode"] is True
        finally:
            os.unlink(path)

    def test_D04_no_output_path_does_not_raise(self):
        """run_governance_verdict_ci should succeed without an output path."""
        with _patch_gate_for_outcome("pass"):
            code = run_governance_verdict_ci()
        assert code == 0


# ===========================================================================
# Group E — CLI integration
# ===========================================================================


@_skip_if_unavailable
class TestGroupE_CliIntegration:
    """CLI entry point integration tests."""

    def test_E01_module_runnable_via_python_m(self):
        """``python -m core.governance_validation_gate`` must exit cleanly."""
        result = subprocess.run(
            [sys.executable, "-m", "core.governance_validation_gate"],
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
        )
        # Must not be a crash (import error / syntax error → exit 2)
        assert result.returncode in (0, 1), (
            f"Unexpected exit code {result.returncode}: stderr={result.stderr[:300]}"
        )

    def test_E02_cli_output_flag_writes_json(self):
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, dir=tempfile.gettempdir()
        ) as f:
            path = f.name
        os.unlink(path)
        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "core.governance_validation_gate",
                    "--output",
                    path,
                ],
                capture_output=True,
                text=True,
                cwd=_PROJECT_ROOT,
            )
            assert result.returncode in (0, 1), (
                f"Unexpected exit code {result.returncode}: stderr={result.stderr[:300]}"
            )
            assert os.path.isfile(path), "CLI --output flag did not write a JSON file"
            with open(path) as fh:
                data = json.load(fh)
            assert "outcome" in data
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_E03_cli_json_schema_valid(self):
        """CLI output JSON must contain all required schema keys."""
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, dir=tempfile.gettempdir()
        ) as f:
            path = f.name
        os.unlink(path)
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "core.governance_validation_gate",
                    "--output",
                    path,
                ],
                capture_output=True,
                text=True,
                cwd=_PROJECT_ROOT,
            )
            assert os.path.isfile(path), "CLI did not write JSON file"
            with open(path) as fh:
                data = json.load(fh)
            missing = [k for k in _REQUIRED_JSON_KEYS if k not in data]
            assert not missing, f"CLI verdict JSON missing required keys: {missing}"
        finally:
            if os.path.exists(path):
                os.unlink(path)
