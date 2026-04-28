"""tests/test_task_result_canonical_truth_chain.py
===================================================
Tests for ``core/task_result_canonical_truth_chain.py``.

These tests verify that the four canonical must-run truth-chain steps for a
``task_result`` message are correctly tracked, that ``is_truth_chain_complete``
is only True when all four steps ran without a fatal failure, and that optional
enrichment steps (absent by design in this module) cannot masquerade as main
chain completeness.

Acceptance criteria tested
--------------------------
AC-TTC-1  When all four backing modules are available and functional,
           ``run_task_result_truth_chain`` returns a :class:`TruthChainOutcome`
           with ``is_truth_chain_complete = True``.

AC-TTC-2  When any one of the four backing modules is unavailable (None),
           ``is_truth_chain_complete`` is ``False`` and ``incomplete_reason``
           names the missing step.

AC-TTC-3  A missing truth_ingress module alone marks the outcome as incomplete
           ("result arrived but truth ingress missing → unresolved").

AC-TTC-4  A step that finds no matching record (NOT_RECONCILED /
           COMPLETED_NO_MATCH) does NOT prevent ``is_truth_chain_complete``
           from being True — record absence is not a fatal gap.

AC-TTC-5  Exceptions inside any step are caught, recorded as
           FAILED_EXCEPTION, and prevent ``is_truth_chain_complete``.

AC-TTC-6  Optional enrichment steps (memory backflow, device-router
           notification) are absent from the module and their absence cannot
           cause ``is_truth_chain_complete`` to change.

AC-TTC-7  ``to_dict()`` produces a serialisable mapping with all expected keys.

AC-TTC-8  Full chain integration: message with task_id + result_status →
           all four steps run → outcome is complete.

AC-TTC-9  ``handle_task_result`` in ``task_lifecycle`` calls
           ``_run_task_result_truth_chain`` when it is available, and falls back
           to legacy helpers when it is None, without raising.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

try:
    import core.task_result_canonical_truth_chain as _ttc
    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_SKIP = pytest.mark.skipif(not _MODULE_AVAILABLE, reason="task_result_canonical_truth_chain unavailable")

# ---------------------------------------------------------------------------
# Import task_lifecycle for integration test
# ---------------------------------------------------------------------------

try:
    import galaxy_gateway.android.handlers.task_lifecycle as _tl
    _TL_AVAILABLE = True
except ImportError:
    _TL_AVAILABLE = False

_TL_SKIP = pytest.mark.skipif(not _TL_AVAILABLE, reason="task_lifecycle unavailable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ingest_ok(was_reconciled: bool = True) -> Any:
    """Return a fake ingest function that succeeds."""
    def _fake(msg: Dict[str, Any], **_kw: Any) -> Any:
        return MagicMock(
            was_reconciled=was_reconciled,
            reject_reason="",
            envelope=None,
        )
    return _fake


def _make_reconcile_ok(was_updated: bool = True) -> Any:
    """Return a fake reconcile function that succeeds."""
    def _fake(msg: Dict[str, Any], **_kw: Any) -> Any:
        return MagicMock(was_updated=was_updated, reject_reason="")
    return _fake


def _make_runtime_ok(task_found: bool = True) -> Any:
    """Return a fake get_canonical_task_runtime that succeeds."""
    mock_runtime = MagicMock()
    mock_runtime.update_lifecycle.return_value = MagicMock() if task_found else None
    return lambda: mock_runtime


def _make_ingress_ok(resolved: bool = False) -> Any:
    """Return a fake get_canonical_completion_ingress that succeeds."""
    mock_ingress = MagicMock()
    mock_ingress.notify.return_value = resolved
    mock_ingress.complete_pending_dispatch.return_value = False
    return lambda: mock_ingress


# ---------------------------------------------------------------------------
# Group A — Module structure
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupA_ModuleStructure:
    def test_a1_module_has_run_function(self) -> None:
        assert hasattr(_ttc, "run_task_result_truth_chain")
        assert callable(_ttc.run_task_result_truth_chain)

    def test_a2_truth_chain_outcome_exists(self) -> None:
        assert hasattr(_ttc, "TruthChainOutcome")

    def test_a3_must_run_policy_sentinel_present(self) -> None:
        assert hasattr(_ttc, "TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY")
        assert "truth_ingress" in _ttc.TASK_RESULT_TRUTH_CHAIN_MUST_RUN_POLICY.lower()

    def test_a4_optional_enrichment_policy_sentinel_present(self) -> None:
        assert hasattr(_ttc, "TRUTH_CHAIN_OPTIONAL_ENRICHMENT_POLICY")

    def test_a5_step_status_constants(self) -> None:
        assert hasattr(_ttc, "StepStatus")
        assert _ttc.StepStatus.COMPLETED == "completed"
        assert _ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE == "skipped_module_unavailable"
        assert _ttc.StepStatus.FAILED_EXCEPTION == "failed_exception"


# ---------------------------------------------------------------------------
# Group B — AC-TTC-1: Full happy-path chain completes
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupB_FullChainComplete:
    """AC-TTC-1: all four modules available → is_truth_chain_complete = True."""

    def _run_all_ok(self, msg: Dict[str, Any]) -> Any:
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            return _ttc.run_task_result_truth_chain(msg)

    def test_b1_is_truth_chain_complete_true(self) -> None:
        """AC-TTC-1: all four steps available → complete."""
        msg = {"task_id": "t-b1", "status": "completed"}
        outcome = self._run_all_ok(msg)
        assert outcome.is_truth_chain_complete is True, (
            f"Expected complete but got incomplete_reason={outcome.incomplete_reason!r}"
        )

    def test_b2_all_four_steps_completed_status(self) -> None:
        """AC-TTC-1: all four step statuses are 'completed' or 'completed_no_match'."""
        msg = {"task_id": "t-b2", "status": "completed"}
        outcome = self._run_all_ok(msg)
        for step_name in (
            "truth_ingress_status",
            "reconcile_status",
            "authority_update_status",
            "completion_linkage_status",
        ):
            status = getattr(outcome, step_name)
            assert status in (
                _ttc.StepStatus.COMPLETED,
                _ttc.StepStatus.COMPLETED_NO_MATCH,
                _ttc.StepStatus.SKIPPED_NO_TASK_ID,
                _ttc.StepStatus.SKIPPED_NO_KEY,
            ), f"{step_name}={status!r} unexpectedly indicates a fatal failure"

    def test_b3_task_id_and_status_in_outcome(self) -> None:
        """AC-TTC-1: outcome carries task_id and result_status."""
        msg = {"task_id": "t-b3", "status": "completed"}
        outcome = self._run_all_ok(msg)
        assert outcome.task_id == "t-b3"
        assert outcome.result_status == "completed"

    def test_b4_incomplete_reason_empty_when_complete(self) -> None:
        """AC-TTC-1: no incomplete_reason when chain is complete."""
        msg = {"task_id": "t-b4", "status": "completed"}
        outcome = self._run_all_ok(msg)
        assert outcome.incomplete_reason == ""

    def test_b5_failed_status_maps_to_failed_lifecycle(self) -> None:
        """AC-TTC-1: 'failed' status causes authority update with FAILED lifecycle."""
        if _ttc.TaskLifecycle is None:
            pytest.skip("TaskLifecycle not available in this environment")
        calls: list = []
        mock_runtime = MagicMock()
        def _capture_update(task_id: str, lifecycle: Any) -> MagicMock:
            calls.append((task_id, lifecycle))
            return MagicMock()
        mock_runtime.update_lifecycle.side_effect = _capture_update

        msg = {"task_id": "t-b5", "status": "failed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", lambda: mock_runtime),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            _ttc.run_task_result_truth_chain(msg)

        assert calls, "authority update must be called"
        _, lifecycle = calls[0]
        assert lifecycle == _ttc.TaskLifecycle.FAILED


# ---------------------------------------------------------------------------
# Group C — AC-TTC-2 / AC-TTC-3: Missing any module → incomplete
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupC_MissingModulesIncomplete:
    """AC-TTC-2 / AC-TTC-3: missing any critical module → is_truth_chain_complete = False."""

    def _run_with_missing(
        self,
        msg: Dict[str, Any],
        missing: str,
    ) -> Any:
        patches: Dict[str, Any] = {
            "_ingest_participant_truth": _make_ingest_ok(),
            "_reconcile_inbound_message": _make_reconcile_ok(),
            "_get_canonical_task_runtime": _make_runtime_ok(),
            "_get_canonical_completion_ingress": _make_ingress_ok(),
        }
        patches[missing] = None
        with (
            patch.object(_ttc, "_ingest_participant_truth", patches["_ingest_participant_truth"]),
            patch.object(_ttc, "_reconcile_inbound_message", patches["_reconcile_inbound_message"]),
            patch.object(_ttc, "_get_canonical_task_runtime", patches["_get_canonical_task_runtime"]),
            patch.object(_ttc, "_get_canonical_completion_ingress", patches["_get_canonical_completion_ingress"]),
        ):
            return _ttc.run_task_result_truth_chain(msg)

    def test_c1_missing_truth_ingress(self) -> None:
        """AC-TTC-3: truth_ingress missing → is_truth_chain_complete = False."""
        msg = {"task_id": "t-c1", "status": "completed"}
        outcome = self._run_with_missing(msg, "_ingest_participant_truth")
        assert outcome.is_truth_chain_complete is False
        assert outcome.truth_ingress_status == _ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE
        assert "truth_ingress" in outcome.incomplete_reason

    def test_c2_missing_reconcile(self) -> None:
        """AC-TTC-2: reconcile missing → is_truth_chain_complete = False."""
        msg = {"task_id": "t-c2", "session_id": "s-c2", "status": "completed"}
        outcome = self._run_with_missing(msg, "_reconcile_inbound_message")
        assert outcome.is_truth_chain_complete is False
        assert outcome.reconcile_status == _ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE
        assert "reconcile" in outcome.incomplete_reason

    def test_c3_missing_authority_update(self) -> None:
        """AC-TTC-2: authority runtime missing → is_truth_chain_complete = False."""
        msg = {"task_id": "t-c3", "status": "completed"}
        outcome = self._run_with_missing(msg, "_get_canonical_task_runtime")
        assert outcome.is_truth_chain_complete is False
        assert outcome.authority_update_status == _ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE
        assert "authority_update" in outcome.incomplete_reason

    def test_c4_missing_completion_ingress(self) -> None:
        """AC-TTC-2: completion ingress missing → is_truth_chain_complete = False."""
        msg = {"task_id": "t-c4", "status": "completed"}
        outcome = self._run_with_missing(msg, "_get_canonical_completion_ingress")
        assert outcome.is_truth_chain_complete is False
        assert outcome.completion_linkage_status == _ttc.StepStatus.SKIPPED_MODULE_UNAVAILABLE
        assert "completion_linkage" in outcome.incomplete_reason

    def test_c5_all_modules_missing(self) -> None:
        """AC-TTC-2: all critical modules missing → clearly incomplete."""
        msg = {"task_id": "t-c5", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", None),
            patch.object(_ttc, "_reconcile_inbound_message", None),
            patch.object(_ttc, "_get_canonical_task_runtime", None),
            patch.object(_ttc, "_get_canonical_completion_ingress", None),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.is_truth_chain_complete is False
        # incomplete_reason should name all four missing steps
        reason = outcome.incomplete_reason
        assert "truth_ingress" in reason
        assert "reconcile" in reason
        assert "authority_update" in reason
        assert "completion_linkage" in reason


# ---------------------------------------------------------------------------
# Group D — AC-TTC-4: No-match is not fatal
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupD_NoMatchNotFatal:
    """AC-TTC-4: steps with no matching record still allow chain completion."""

    def test_d1_reconcile_no_key_is_not_fatal(self) -> None:
        """Reconcile without any correlation key → COMPLETED_NO_MATCH, chain complete."""
        # Message has no contract_id / session_id → reconcile records no-match
        msg = {"task_id": "t-d1", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.is_truth_chain_complete is True

    def test_d2_authority_update_no_task_found(self) -> None:
        """Authority update with no task registered → authority_task_found=False but step completes."""
        msg = {"task_id": "t-d2", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok(task_found=False)),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.authority_task_found is False
        assert outcome.authority_update_status == _ttc.StepStatus.COMPLETED
        assert outcome.is_truth_chain_complete is True

    def test_d3_completion_ingress_no_awaiter(self) -> None:
        """Completion linkage with no registered awaiter → resolved=False but step completes."""
        msg = {"task_id": "t-d3", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok(resolved=False)),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.completion_linkage_resolved is False
        assert outcome.completion_linkage_status == _ttc.StepStatus.COMPLETED
        assert outcome.is_truth_chain_complete is True


# ---------------------------------------------------------------------------
# Group E — AC-TTC-5: Exceptions are captured, step fails
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupE_ExceptionsAreCaptured:
    """AC-TTC-5: exceptions inside any step set FAILED_EXCEPTION and prevent completion."""

    def test_e1_truth_ingress_exception(self) -> None:
        def _raising(msg: Dict[str, Any], **_kw: Any) -> Any:
            raise RuntimeError("ingress crash")
        msg = {"task_id": "t-e1", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _raising),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.truth_ingress_status == _ttc.StepStatus.FAILED_EXCEPTION
        assert outcome.is_truth_chain_complete is False

    def test_e2_reconcile_exception(self) -> None:
        def _raising(msg: Dict[str, Any], **_kw: Any) -> Any:
            raise ValueError("reconcile crash")
        msg = {"task_id": "t-e2", "session_id": "s-e2", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _raising),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.reconcile_status == _ttc.StepStatus.FAILED_EXCEPTION
        assert outcome.is_truth_chain_complete is False

    def test_e3_authority_update_exception(self) -> None:
        mock_runtime = MagicMock()
        mock_runtime.update_lifecycle.side_effect = RuntimeError("runtime crash")
        msg = {"task_id": "t-e3", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", lambda: mock_runtime),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.authority_update_status == _ttc.StepStatus.FAILED_EXCEPTION
        assert outcome.is_truth_chain_complete is False

    def test_e4_completion_linkage_exception(self) -> None:
        mock_ingress = MagicMock()
        mock_ingress.notify.side_effect = RuntimeError("ingress crash")
        mock_ingress.complete_pending_dispatch.side_effect = RuntimeError("direct crash")
        msg = {"task_id": "t-e4", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", lambda: mock_ingress),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        assert outcome.completion_linkage_status == _ttc.StepStatus.FAILED_EXCEPTION
        assert outcome.is_truth_chain_complete is False

    def test_e5_exceptions_are_not_re_raised(self) -> None:
        """AC-TTC-5: exception-raising steps must not propagate exceptions to caller."""
        def _raising(*_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("crash")
        msg = {"task_id": "t-e5", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _raising),
            patch.object(_ttc, "_reconcile_inbound_message", _raising),
            patch.object(_ttc, "_get_canonical_task_runtime", None),
            patch.object(_ttc, "_get_canonical_completion_ingress", None),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)  # must not raise
        assert not outcome.is_truth_chain_complete


# ---------------------------------------------------------------------------
# Group F — AC-TTC-6: Optional enrichment outside this module
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupF_OptionalEnrichmentNotInModule:
    """AC-TTC-6: memory backflow and device-router notification are absent."""

    def test_f1_no_store_task_result_in_module(self) -> None:
        """Module must not import or call store_task_result."""
        assert not hasattr(_ttc, "store_task_result"), (
            "store_task_result must not be part of the canonical truth chain"
        )

    def test_f2_no_device_router_in_module(self) -> None:
        """Module must not import device_router."""
        assert not hasattr(_ttc, "device_router"), (
            "device_router notification must not be part of the canonical truth chain"
        )

    def test_f3_is_truth_chain_complete_unaffected_by_enrichment_absence(self) -> None:
        """AC-TTC-6: chain completion is not affected by enrichment steps."""
        msg = {"task_id": "t-f3", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)
        # chain is complete even though memory backflow was never called
        assert outcome.is_truth_chain_complete is True


# ---------------------------------------------------------------------------
# Group G — AC-TTC-7: to_dict() serialisation
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupG_ToDictSerialisation:
    """AC-TTC-7: to_dict() returns all expected keys."""

    def test_g1_to_dict_keys(self) -> None:
        outcome = _ttc.TruthChainOutcome(task_id="t-g1", result_status="completed")
        outcome._compute_completeness()
        d = outcome.to_dict()
        expected_keys = {
            "task_id",
            "result_status",
            "truth_ingress_status",
            "reconcile_status",
            "authority_update_status",
            "completion_linkage_status",
            "truth_ingress_was_reconciled",
            "reconcile_was_updated",
            "authority_task_found",
            "completion_linkage_resolved",
            "is_truth_chain_complete",
            "incomplete_reason",
        }
        assert expected_keys <= set(d.keys()), (
            f"Missing keys: {expected_keys - set(d.keys())}"
        )

    def test_g2_to_dict_no_private_fields(self) -> None:
        outcome = _ttc.TruthChainOutcome(task_id="t-g2")
        d = outcome.to_dict()
        for k in d.keys():
            assert not k.startswith("_"), f"Private field {k!r} exposed in to_dict()"


# ---------------------------------------------------------------------------
# Group H — AC-TTC-8: Full integration — task_id + result_status flow
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupH_FullIntegration:
    """AC-TTC-8: result → reconcile → authority update → completion linkage."""

    def test_h1_full_chain_with_task_id(self) -> None:
        """Full chain succeeds with task_id supplied as argument."""
        calls: Dict[str, list] = {
            "ingest": [],
            "reconcile": [],
            "runtime": [],
            "ingress_notify": [],
        }

        def _ingest(msg: Dict[str, Any], **_kw: Any) -> Any:
            calls["ingest"].append(msg)
            return MagicMock(was_reconciled=True)

        def _reconcile(msg: Dict[str, Any], **_kw: Any) -> Any:
            calls["reconcile"].append(msg)
            return MagicMock(was_updated=False)

        mock_runtime = MagicMock()
        mock_runtime.update_lifecycle.side_effect = lambda *a: calls["runtime"].append(a) or MagicMock()

        mock_ingress = MagicMock()
        mock_ingress.notify.side_effect = lambda e: calls["ingress_notify"].append(e) or False
        mock_ingress.complete_pending_dispatch.return_value = True

        msg = {"task_id": "t-h1", "status": "completed", "device_id": "dev-h1"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _ingest),
            patch.object(_ttc, "_reconcile_inbound_message", _reconcile),
            patch.object(_ttc, "_get_canonical_task_runtime", lambda: mock_runtime),
            patch.object(_ttc, "_get_canonical_completion_ingress", lambda: mock_ingress),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg, task_id="t-h1", result_status="completed")

        assert outcome.is_truth_chain_complete is True
        assert len(calls["ingest"]) == 1, "truth_ingress must be called once"
        assert len(calls["reconcile"]) >= 1 or outcome.reconcile_status in (
            _ttc.StepStatus.COMPLETED_NO_MATCH,
            _ttc.StepStatus.COMPLETED,
        )
        assert len(calls["ingress_notify"]) == 1, "completion_linkage notify must be called once"

    def test_h2_task_id_from_message(self) -> None:
        """task_id read from message when not supplied as arg."""
        msg = {"task_id": "t-h2", "status": "completed"}
        with (
            patch.object(_ttc, "_ingest_participant_truth", _make_ingest_ok()),
            patch.object(_ttc, "_reconcile_inbound_message", _make_reconcile_ok()),
            patch.object(_ttc, "_get_canonical_task_runtime", _make_runtime_ok()),
            patch.object(_ttc, "_get_canonical_completion_ingress", _make_ingress_ok()),
        ):
            outcome = _ttc.run_task_result_truth_chain(msg)  # no task_id kwarg
        assert outcome.task_id == "t-h2"
        assert outcome.is_truth_chain_complete is True


# ---------------------------------------------------------------------------
# Group I — AC-TTC-9: handle_task_result calls canonical chain
# ---------------------------------------------------------------------------


@_TL_SKIP
class TestGroupI_TaskLifecycleCalls:
    """AC-TTC-9: handle_task_result uses _run_task_result_truth_chain when available."""

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def _make_bridge(self) -> Any:
        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._lock = asyncio.Lock()
        bridge._devices = {}
        return bridge

    def test_i1_canonical_chain_called_when_available(self) -> None:
        """handle_task_result calls _run_task_result_truth_chain."""
        bridge = self._make_bridge()
        msg = {"task_id": "t-i1", "device_id": "dev-i1", "status": "completed"}
        calls: list = []

        def _fake_chain(message: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(message))
            return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

        with (
            patch.object(_tl, "_run_task_result_truth_chain", _fake_chain),
            patch.object(_tl, "store_task_result", None),
        ):
            self._run(_tl.handle_task_result(bridge, None, msg))

        assert len(calls) >= 1, "canonical chain must be called at least once"
        assert calls[0].get("task_id") == "t-i1"

    def test_i2_fallback_to_legacy_when_chain_unavailable(self) -> None:
        """When _run_task_result_truth_chain is None, legacy helpers run without raising."""
        bridge = self._make_bridge()
        msg = {"task_id": "t-i2", "device_id": "dev-i2", "status": "completed"}
        reconcile_calls: list = []
        ingest_calls: list = []

        def _fake_reconcile(m: Dict[str, Any]) -> None:
            reconcile_calls.append(m)

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            ingest_calls.append(m)
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with (
            patch.object(_tl, "_run_task_result_truth_chain", None),
            patch.object(_tl, "_reconcile_inbound_message", _fake_reconcile),
            patch.object(_tl, "_ingest_participant_truth", _fake_ingest),
            patch.object(_tl, "store_task_result", None),
        ):
            self._run(_tl.handle_task_result(bridge, None, msg))  # must not raise

    def test_i3_future_still_resolved_when_chain_runs(self) -> None:
        """Future resolution still happens after the canonical chain runs."""
        resolved: list = []

        async def _inner() -> None:
            bridge = self._make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            bridge._pending_responses["t-i3"] = fut
            msg = {"task_id": "t-i3", "device_id": "dev-i3", "status": "completed"}

            def _fake_chain(message: Dict[str, Any], **_kw: Any) -> Any:
                return MagicMock(is_truth_chain_complete=True, incomplete_reason="")

            with (
                patch.object(_tl, "_run_task_result_truth_chain", _fake_chain),
                patch.object(_tl, "store_task_result", None),
            ):
                await _tl.handle_task_result(bridge, None, msg)

            resolved.append(fut.done())

        asyncio.run(_inner())
        assert resolved[0], "pending Future must be resolved after handle_task_result"
