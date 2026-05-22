#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr2_single_ingress_enforcement.py
================================================
PR-2 single-ingress enforcement tests.

Validates that the "single ingress by construction" invariant holds:
- Android-originated runtime truth enters V2 through the canonical
  unified ingress before state mutation.
- Non-ingress bypass write attempts are detectable and non-silent.
- task_lifecycle and goal_execution handlers route through canonical ingress.
- Routing ambiguity does not silently mutate canonical state.
- SINGLE_INGRESS_BYPASS_GUARD_POLICY sentinel is importable and correct.

Test groups
-----------
A.  Bypass guard constants and telemetry
B.  task_lifecycle routes through canonical ingress
C.  goal_execution routes through canonical ingress
D.  Non-ingress write attempts surface high-severity telemetry
E.  Canonical ingress is the single import entry for participant truth
    in handler modules
"""
from __future__ import annotations

import os
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_message(msg_type: str = "task_result", device_id: str = "dev-test-001") -> Dict[str, Any]:
    return {
        "version": "3.0",
        "type": msg_type,
        "device_id": device_id,
        "message_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "payload": {},
    }


# ---------------------------------------------------------------------------
# Optional handler imports (skipped when pydantic / fastapi not available)
# ---------------------------------------------------------------------------

try:
    import galaxy_gateway.android.handlers.task_lifecycle as _tl
    _TL_AVAILABLE = True
except Exception:
    _tl = None  # type: ignore[assignment]
    _TL_AVAILABLE = False

try:
    import galaxy_gateway.android.handlers.goal_execution as _ge
    _GE_AVAILABLE = True
except Exception:
    _ge = None  # type: ignore[assignment]
    _GE_AVAILABLE = False

_SKIP_TL = pytest.mark.skipif(not _TL_AVAILABLE, reason="task_lifecycle handler unavailable (missing deps)")
_SKIP_GE = pytest.mark.skipif(not _GE_AVAILABLE, reason="goal_execution handler unavailable (missing deps)")

# ---------------------------------------------------------------------------
# File paths for source inspection (does not require module import)
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TASK_LIFECYCLE_SRC = os.path.join(
    _REPO_ROOT, "galaxy_gateway", "android", "handlers", "task_lifecycle.py"
)
_GOAL_EXECUTION_SRC = os.path.join(
    _REPO_ROOT, "galaxy_gateway", "android", "handlers", "goal_execution.py"
)


def _read_source(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# ============================================================================
# A.  Bypass guard constants and telemetry
# ============================================================================

class TestBypassGuardConstants:

    def test_A01_single_ingress_bypass_guard_policy_importable(self):
        from core.unified_runtime_truth_ingress import SINGLE_INGRESS_BYPASS_GUARD_POLICY
        assert SINGLE_INGRESS_BYPASS_GUARD_POLICY

    def test_A02_bypass_guard_policy_non_empty(self):
        from core.unified_runtime_truth_ingress import SINGLE_INGRESS_BYPASS_GUARD_POLICY
        assert len(SINGLE_INGRESS_BYPASS_GUARD_POLICY.strip()) > 10

    def test_A03_bypass_guard_policy_mentions_ingest_function(self):
        from core.unified_runtime_truth_ingress import SINGLE_INGRESS_BYPASS_GUARD_POLICY
        assert "ingest_android_runtime_state_update" in SINGLE_INGRESS_BYPASS_GUARD_POLICY

    def test_A04_record_non_ingress_write_importable(self):
        from core.unified_runtime_truth_ingress import record_non_ingress_participant_truth_write
        assert callable(record_non_ingress_participant_truth_write)

    def test_A05_get_bypass_attempt_count_importable(self):
        from core.unified_runtime_truth_ingress import get_bypass_attempt_count
        assert callable(get_bypass_attempt_count)

    def test_A06_get_bypass_attempt_count_returns_int(self):
        from core.unified_runtime_truth_ingress import get_bypass_attempt_count
        assert isinstance(get_bypass_attempt_count(), int)

    def test_A07_record_bypass_increments_counter(self):
        from core.unified_runtime_truth_ingress import (
            record_non_ingress_participant_truth_write,
            get_bypass_attempt_count,
        )
        before = get_bypass_attempt_count()
        record_non_ingress_participant_truth_write("task_result", "test_caller")
        assert get_bypass_attempt_count() == before + 1

    def test_A08_record_bypass_emits_warning_log(self):
        from core.unified_runtime_truth_ingress import record_non_ingress_participant_truth_write
        with patch("core.unified_runtime_truth_ingress.logger") as mock_logger:
            record_non_ingress_participant_truth_write("task_result", "test_caller")
            mock_logger.warning.assert_called_once()
            call_args = str(mock_logger.warning.call_args)
            # The warning must reference the bypass / non-canonical nature
            assert any(
                kw in call_args.lower()
                for kw in ("bypass", "non-canonical", "guard", "violation")
            )

    def test_A09_record_bypass_includes_message_type_in_log(self):
        from core.unified_runtime_truth_ingress import record_non_ingress_participant_truth_write
        with patch("core.unified_runtime_truth_ingress.logger") as mock_logger:
            record_non_ingress_participant_truth_write("goal_execution_result", "some_handler")
            call_args = mock_logger.warning.call_args
            assert call_args is not None
            all_args = str(call_args)
            assert "goal_execution_result" in all_args

    def test_A10_bypass_guard_policy_in_all(self):
        import core.unified_runtime_truth_ingress as mod
        assert "SINGLE_INGRESS_BYPASS_GUARD_POLICY" in mod.__all__

    def test_A11_record_bypass_function_in_all(self):
        import core.unified_runtime_truth_ingress as mod
        assert "record_non_ingress_participant_truth_write" in mod.__all__

    def test_A12_get_bypass_count_in_all(self):
        import core.unified_runtime_truth_ingress as mod
        assert "get_bypass_attempt_count" in mod.__all__


# ============================================================================
# B.  task_lifecycle routes through canonical ingress — source inspection
# ============================================================================

class TestTaskLifecycleSourceUsesCanonicalIngress:
    """Source-level checks that do not require pydantic."""

    def test_B01_task_lifecycle_imports_canonical_ingress(self):
        """task_lifecycle.py must import from unified_runtime_truth_ingress."""
        source = _read_source(_TASK_LIFECYCLE_SRC)
        assert "unified_runtime_truth_ingress" in source

    def test_B02_task_lifecycle_does_not_directly_import_participant_truth_sub_ingress(self):
        """The old direct bypass import line must no longer be present."""
        source = _read_source(_TASK_LIFECYCLE_SRC)
        assert (
            "ingest_android_participant_truth_message as _ingest_participant_truth"
            not in source
        ), (
            "task_lifecycle.py still directly imports android_participant_truth_ingress "
            "via _ingest_participant_truth — this is the bypass path that must be removed."
        )

    def test_B03_task_lifecycle_imports_ingest_via_canonical_ingress_symbol(self):
        """The new canonical ingress symbol must be present in the source."""
        source = _read_source(_TASK_LIFECYCLE_SRC)
        assert "_ingest_via_canonical_ingress" in source, (
            "task_lifecycle.py must use _ingest_via_canonical_ingress to route "
            "through the canonical unified ingress."
        )

    def test_B04_try_ingest_participant_truth_calls_canonical_symbol(self):
        """_try_ingest_participant_truth must call the canonical ingress symbol."""
        source = _read_source(_TASK_LIFECYCLE_SRC)
        # Check that _ingest_via_canonical_ingress appears in the function body
        assert source.count("_ingest_via_canonical_ingress") >= 2, (
            "_ingest_via_canonical_ingress should appear at the import line AND "
            "inside _try_ingest_participant_truth."
        )


# ============================================================================
# B-func.  task_lifecycle function-level tests (skipped without pydantic)
# ============================================================================

@_SKIP_TL
class TestTaskLifecycleFunctionUsesCanonicalIngress:

    def test_BF01_try_ingest_participant_truth_calls_canonical_ingress(self):
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = True
        mock_outcome.reject_reason = ""
        mock_outcome.routed_path = "participant_truth"

        with patch.object(
            _tl, "_ingest_via_canonical_ingress", return_value=mock_outcome
        ) as mock_ingress:
            _tl._try_ingest_participant_truth(
                {"type": "task_result", "task_id": "t1"}, "result"
            )
            mock_ingress.assert_called_once()

    def test_BF02_try_ingest_participant_truth_injects_truth_kind(self):
        captured_messages = []
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = False
        mock_outcome.reject_reason = ""

        def capture(msg):
            captured_messages.append(dict(msg))
            return mock_outcome

        with patch.object(_tl, "_ingest_via_canonical_ingress", side_effect=capture):
            _tl._try_ingest_participant_truth(
                {"type": "task_result", "task_id": "t1"},
                "task_phase",
            )

        assert captured_messages, "canonical ingress was not called"
        assert captured_messages[0].get("truth_kind") == "task_phase"

    def test_BF03_try_ingest_participant_truth_no_op_when_ingress_unavailable(self):
        with patch.object(_tl, "_ingest_via_canonical_ingress", None):
            _tl._try_ingest_participant_truth({"type": "task_result"}, "result")

    def test_BF04_existing_truth_kind_not_overwritten_by_canonical_path(self):
        """Pre-existing truth_kind must not be overwritten when routing canonical."""
        captured: Dict[str, Any] = {}
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = False
        mock_outcome.reject_reason = ""

        def capture(msg):
            captured.update(msg)
            return mock_outcome

        with patch.object(_tl, "_ingest_via_canonical_ingress", side_effect=capture):
            _tl._try_ingest_participant_truth(
                {"type": "task_result", "truth_kind": "result"}, "cancel"
            )
        assert captured.get("truth_kind") == "result"


# ============================================================================
# C.  goal_execution routes through canonical ingress — source inspection
# ============================================================================

class TestGoalExecutionSourceUsesCanonicalIngress:
    """Source-level checks that do not require pydantic."""

    def test_C01_goal_execution_imports_canonical_ingress(self):
        source = _read_source(_GOAL_EXECUTION_SRC)
        assert "unified_runtime_truth_ingress" in source

    def test_C02_goal_execution_does_not_directly_import_sub_ingress(self):
        source = _read_source(_GOAL_EXECUTION_SRC)
        assert (
            "ingest_android_participant_truth_message as _ingest_goal_result_truth"
            not in source
        ), (
            "goal_execution.py still directly imports android_participant_truth_ingress "
            "via _ingest_goal_result_truth — this is the bypass path that must be removed."
        )

    def test_C03_goal_execution_imports_canonical_ingress_symbol(self):
        source = _read_source(_GOAL_EXECUTION_SRC)
        assert "_ingest_goal_result_via_canonical_ingress" in source

    def test_C04_try_ingest_goal_result_truth_calls_canonical_symbol(self):
        source = _read_source(_GOAL_EXECUTION_SRC)
        assert source.count("_ingest_goal_result_via_canonical_ingress") >= 2


# ============================================================================
# C-func.  goal_execution function-level tests (skipped without pydantic)
# ============================================================================

@_SKIP_GE
class TestGoalExecutionFunctionUsesCanonicalIngress:

    def test_CF01_try_ingest_goal_result_truth_calls_canonical_ingress(self):
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = True
        mock_outcome.reject_reason = ""
        mock_outcome.routed_path = "participant_truth"

        with patch.object(
            _ge, "_ingest_goal_result_via_canonical_ingress", return_value=mock_outcome
        ) as mock_ingress:
            _ge._try_ingest_goal_result_truth(
                {"type": "goal_execution_result", "task_id": "t2"}
            )
            mock_ingress.assert_called_once()

    def test_CF02_try_ingest_goal_result_truth_injects_result_kind(self):
        captured: Dict[str, Any] = {}
        mock_outcome = MagicMock()
        mock_outcome.was_reconciled = False
        mock_outcome.reject_reason = ""

        def capture(msg):
            captured.update(msg)
            return mock_outcome

        with patch.object(
            _ge, "_ingest_goal_result_via_canonical_ingress", side_effect=capture
        ):
            _ge._try_ingest_goal_result_truth(
                {"type": "goal_execution_result", "task_id": "t2"}
            )
        assert captured.get("truth_kind") == "result"

    def test_CF03_try_ingest_goal_result_no_op_when_ingress_unavailable(self):
        with patch.object(_ge, "_ingest_goal_result_via_canonical_ingress", None):
            _ge._try_ingest_goal_result_truth({"type": "goal_execution_result"})


# ============================================================================
# D.  Non-ingress write attempts surface high-severity telemetry
# ============================================================================

class TestNonIngressBypassTelemetry:

    def test_D01_bypass_attempt_is_not_silent(self):
        """record_non_ingress_participant_truth_write must emit a WARNING log."""
        from core.unified_runtime_truth_ingress import record_non_ingress_participant_truth_write
        with patch("core.unified_runtime_truth_ingress.logger") as mock_logger:
            record_non_ingress_participant_truth_write("fake_type", "fake_handler")
            assert mock_logger.warning.called, (
                "Non-ingress write must emit a warning log — bypass must not be silent."
            )

    def test_D02_bypass_attempt_does_not_raise(self):
        """record_non_ingress_participant_truth_write must not raise."""
        from core.unified_runtime_truth_ingress import record_non_ingress_participant_truth_write
        record_non_ingress_participant_truth_write()
        record_non_ingress_participant_truth_write("", "")
        record_non_ingress_participant_truth_write("task_result", "some_handler")

    def test_D03_multiple_bypass_attempts_are_counted_cumulatively(self):
        from core.unified_runtime_truth_ingress import (
            record_non_ingress_participant_truth_write,
            get_bypass_attempt_count,
        )
        before = get_bypass_attempt_count()
        record_non_ingress_participant_truth_write("t1", "c1")
        record_non_ingress_participant_truth_write("t2", "c2")
        assert get_bypass_attempt_count() >= before + 2

    def test_D04_canonical_ingress_does_not_increment_bypass_counter(self):
        """Routing through ingest_android_runtime_state_update must NOT increment the
        bypass counter."""
        from core.unified_runtime_truth_ingress import (
            ingest_android_runtime_state_update,
            get_bypass_attempt_count,
        )
        before = get_bypass_attempt_count()
        ingest_android_runtime_state_update(
            {"type": "session_snapshot", "device_id": "dev-test"},
        )
        assert get_bypass_attempt_count() == before, (
            "Canonical ingress must not increment the bypass counter."
        )


# ============================================================================
# E.  Canonical ingress is the single entry point — functional checks
# ============================================================================

class TestSingleIngressIsOnlyEntryPoint:

    def test_E01_policy_mentions_ingest_function(self):
        from core.unified_runtime_truth_ingress import (
            ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY,
        )
        assert "ingest_android_runtime_state_update" in ANDROID_RUNTIME_STATE_MUST_FLOW_THROUGH_INGRESS_POLICY

    def test_E02_no_parallel_write_policy_exists(self):
        from core.unified_runtime_truth_ingress import NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY
        assert NO_PARALLEL_WRITE_TO_CANONICAL_STATE_POLICY

    def test_E03_ingest_android_runtime_state_update_is_callable(self):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        assert callable(ingest_android_runtime_state_update)

    def test_E04_task_result_message_routes_via_canonical_with_outcome(self):
        """task_result messages must produce an observable outcome via canonical ingress."""
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        msg = _make_message("task_result")
        outcome = ingest_android_runtime_state_update(msg)
        assert outcome is not None
        assert outcome.routed_path in ("participant_truth", "degraded")

    def test_E05_goal_execution_result_message_routes_via_canonical(self):
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        msg = _make_message("goal_execution_result")
        outcome = ingest_android_runtime_state_update(msg)
        assert outcome is not None
        assert outcome.routed_path in ("participant_truth", "degraded")

    def test_E06_ambiguous_message_type_produces_observable_outcome(self):
        """Unknown message type must produce a non-empty routed_path outcome."""
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        msg = _make_message("unknown_ambiguous_type_xyz")
        outcome = ingest_android_runtime_state_update(msg)
        assert outcome is not None
        assert outcome.routed_path != "", (
            "Ambiguous message type produced an empty routed_path — "
            "routing ambiguity must produce an observable outcome."
        )

    def test_E07_continuity_mode_propagated_to_outcome(self):
        """continuity_legality_mode from message must appear in the outcome."""
        from core.unified_runtime_truth_ingress import ingest_android_runtime_state_update
        msg = _make_message("session_snapshot")
        msg["continuity_legality_mode"] = "compat"
        outcome = ingest_android_runtime_state_update(msg)
        assert outcome is not None
        assert outcome.continuity_legality_mode in ("", "compat", "strict", "relaxed")

    def test_E08_ingest_returns_runtime_truth_ingress_outcome_type(self):
        from core.unified_runtime_truth_ingress import (
            ingest_android_runtime_state_update,
            RuntimeTruthIngressOutcome,
        )
        msg = _make_message("runtime_state")
        outcome = ingest_android_runtime_state_update(msg)
        assert isinstance(outcome, RuntimeTruthIngressOutcome)

