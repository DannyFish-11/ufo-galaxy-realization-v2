"""tests/test_android_inbound_gateway_signal_reconcile.py
=========================================================
Integration / regression tests proving that inbound Android execution signals
flow through the **real canonical inbound gateway handlers** and materially
advance V2 canonical tracking / execution phase state.

These tests close the gap between:
  "reconciler implementation exists"  (covered by test_pr13_*)
and
  "canonical inbound path stably consumes reconciled Android execution signals"

Acceptance criteria verified here
-----------------------------------
AC1  ACK signals arriving via ``handle_command_result`` advance the canonical
     tracking record (``pending_ack`` → ``acknowledged``).
AC2  PROGRESS signals arriving via ``handle_task_progress`` advance the
     tracking record (``pending_ack``/``acknowledged`` → ``in_progress``).
AC3  RESULT signals arriving via ``handle_task_result`` advance the tracking
     record to ``completed`` through the canonical truth chain.
AC4  RESULT signals arriving via ``handle_goal_execution_result`` advance the
     tracking record to ``completed``.
AC5  ERROR signals arriving via ``handle_error`` advance the tracking record
     to ``failed``.
AC6  END signals arriving via ``handle_task_end`` advance the tracking record
     (phase advances via final_result mapping).
AC7  ``handle_command_result`` routes through ``_try_reconcile`` — the signal
     guard and reconcile path are exercised, not bypassed.
AC8  Messages without ``contract_id`` / ``session_id`` are silently no-ops
     (reconciler's ``has_key`` guard fires); handlers remain non-disruptive.
AC9  ``command_result`` maps to ``ack`` in the canonical signal-kind table.
AC10 ``command_result`` with terminal status maps to ``final_result``/``error``.

Coverage groups
---------------
Group A — Signal-kind mappings for ``command_result`` in the reconciler table.
Group B — ``handle_command_result`` wires ``_try_reconcile`` (AC1 / AC7).
Group C — ``handle_task_progress`` → PROGRESS phase advance (AC2).
Group D — ``handle_task_result`` → RESULT / truth-chain phase advance (AC3).
Group E — ``handle_goal_execution_result`` → RESULT phase advance (AC4).
Group F — ``handle_error`` → ERROR phase advance (AC5).
Group G — ``handle_task_end`` → END / completion phase advance (AC6).
Group H — No-key guard: messages without identity fields are no-ops (AC8).
Group I — Full ACK→PROGRESS→RESULT lifecycle through the inbound path.
"""

from __future__ import annotations

import asyncio
import uuid
from functools import partial
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Conditional imports — skip the entire suite if core modules unavailable
# ---------------------------------------------------------------------------

try:
    from core.android_execution_signal_reconciler import (
        AndroidSignalKind,
        normalize_android_message_to_signal_kind,
        reconcile_inbound_message,
    )
    from core.delegated_runtime_execution_tracker import (
        DelegatedExecutionPhase,
        DelegatedExecutionTrackingRuntime,
        create_execution_tracking_record,
    )
    import galaxy_gateway.android.handlers.task_lifecycle as _tl

    _CORE_AVAILABLE = True
except ImportError:
    _CORE_AVAILABLE = False

_GE_AVAILABLE: bool = False
if _CORE_AVAILABLE:
    try:
        import galaxy_gateway.android.handlers.goal_execution as _ge

        _GE_AVAILABLE = True
    except ImportError:
        pass

_SKIP_CORE = pytest.mark.skipif(not _CORE_AVAILABLE, reason="core modules unavailable")
_SKIP_GE = pytest.mark.skipif(not _GE_AVAILABLE, reason="goal_execution handler unavailable")

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _fresh_runtime() -> "DelegatedExecutionTrackingRuntime":
    """Return a fresh isolated tracking runtime (not the process singleton)."""
    return DelegatedExecutionTrackingRuntime()


def _make_record(
    *,
    session_id: str = "ses-int-001",
    contract_id: str = "ctr-int-001",
    device_id: str = "dev-int-001",
    runtime: Optional["DelegatedExecutionTrackingRuntime"] = None,
):
    """Create a tracking record and return ``(record, runtime)``."""
    rt = runtime or _fresh_runtime()
    rec = create_execution_tracking_record(
        session_id=session_id,
        contract_id=contract_id,
        device_id=device_id,
        trace_id="trace-int-001",
        source_runtime_posture="join_runtime",
        runtime=rt,
    )
    return rec, rt


def _make_bridge() -> Any:
    """Return a minimal mock AndroidBridge suitable for handler calls."""
    bridge = MagicMock()
    bridge._pending_responses = {}
    bridge._lock = asyncio.Lock()
    bridge._devices = {}
    return bridge


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _make_reconcile_with_runtime(
    rt: "DelegatedExecutionTrackingRuntime",
):
    """Return a reconcile callable that uses an isolated *rt* for test isolation."""
    def _reconcile(message: Dict[str, Any]) -> Any:
        return reconcile_inbound_message(message, runtime=rt)
    return _reconcile


def _find_record(
    rt: "DelegatedExecutionTrackingRuntime",
    contract_id: str,
    session_id: str,
) -> Any:
    """Look up the most recent tracking record by contract_id then session_id."""
    return rt.get_latest_for_contract(contract_id) or rt.get_latest_for_session(session_id)


# ===========================================================================
# Group A — signal-kind mappings for ``command_result``
# ===========================================================================


@_SKIP_CORE
class TestGroupA_CommandResultSignalKindMappings:
    """AC9, AC10: ``command_result`` entries in the reconciler normalisation table."""

    def test_a01_command_result_bare_maps_to_ack(self) -> None:
        """AC9: bare command_result (no status) → ack."""
        kind = normalize_android_message_to_signal_kind("command_result", "")
        assert kind == AndroidSignalKind.ack

    def test_a02_command_result_none_status_maps_to_ack(self) -> None:
        """AC9: command_result with None status → ack."""
        kind = normalize_android_message_to_signal_kind("command_result", None)
        assert kind == AndroidSignalKind.ack

    def test_a03_command_result_completed_maps_to_final_result(self) -> None:
        """AC10: command_result completed → final_result."""
        kind = normalize_android_message_to_signal_kind("command_result", "completed")
        assert kind == AndroidSignalKind.final_result

    def test_a04_command_result_success_maps_to_final_result(self) -> None:
        """AC10: command_result success → final_result."""
        kind = normalize_android_message_to_signal_kind("command_result", "success")
        assert kind == AndroidSignalKind.final_result

    def test_a05_command_result_failed_maps_to_error(self) -> None:
        """AC10: command_result failed → error."""
        kind = normalize_android_message_to_signal_kind("command_result", "failed")
        assert kind == AndroidSignalKind.error

    def test_a06_command_result_failure_maps_to_error(self) -> None:
        """AC10: command_result failure → error."""
        kind = normalize_android_message_to_signal_kind("command_result", "failure")
        assert kind == AndroidSignalKind.error

    def test_a07_command_result_running_maps_to_progress(self) -> None:
        """AC10: command_result running → progress."""
        kind = normalize_android_message_to_signal_kind("command_result", "running")
        assert kind == AndroidSignalKind.progress

    def test_a08_command_result_cancelled_maps_to_cancelled(self) -> None:
        """AC10: command_result cancelled → cancelled."""
        kind = normalize_android_message_to_signal_kind("command_result", "cancelled")
        assert kind == AndroidSignalKind.cancelled

    def test_a09_command_result_timeout_maps_to_timeout(self) -> None:
        """AC10: command_result timeout → timeout."""
        kind = normalize_android_message_to_signal_kind("command_result", "timeout")
        assert kind == AndroidSignalKind.timeout

    def test_a10_type_only_fallback_command_result_is_ack(self) -> None:
        """AC9: type-only fallback for command_result is ack (no status in message)."""
        kind = normalize_android_message_to_signal_kind("command_result")
        assert kind == AndroidSignalKind.ack


# ===========================================================================
# Group B — handle_command_result wires _try_reconcile (AC1 / AC7)
# ===========================================================================


@_SKIP_CORE
class TestGroupB_HandleCommandResultReconcileWiring:
    """AC1, AC7: ``handle_command_result`` must call ``_try_reconcile``."""

    def test_b01_try_reconcile_called_when_has_contract_id(self) -> None:
        """AC7: _try_reconcile is called when message carries contract_id."""
        bridge = _make_bridge()
        msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "task_id": "t-b01",
            "device_id": "dev-b01",
            "contract_id": "ctr-b01",
            "session_id": "ses-b01",
            "status": "",
        }
        reconcile_calls: list = []

        def _fake_reconcile(m: Dict[str, Any]) -> Any:
            reconcile_calls.append(dict(m))
            return MagicMock(was_updated=False, reject_reason="no_record", envelope=None)

        with patch.object(_tl, "_reconcile_inbound_message", _fake_reconcile):
            _run(_tl.handle_command_result(bridge, None, msg))

        assert len(reconcile_calls) >= 1, (
            "handle_command_result must call _reconcile_inbound_message when "
            "the message carries contract_id"
        )

    def test_b02_reconcile_not_called_when_reconciler_absent(self) -> None:
        """AC8: handler completes normally when reconciler module is absent."""
        bridge = _make_bridge()
        msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "contract_id": "ctr-b02",
            "session_id": "ses-b02",
        }
        with patch.object(_tl, "_reconcile_inbound_message", None):
            _run(_tl.handle_command_result(bridge, None, msg))  # must not raise

    def test_b03_pending_future_resolved_then_reconcile_runs(self) -> None:
        """AC1, AC7: future is resolved AND reconcile is attempted in the same call."""

        async def _inner() -> None:
            bridge = _make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            msg_id = str(uuid.uuid4())
            bridge._pending_responses[msg_id] = fut
            msg = {
                "type": "command_result",
                "message_id": msg_id,
                "contract_id": "ctr-b03",
                "session_id": "ses-b03",
                "status": "",
            }
            reconcile_calls: list = []

            def _fake_reconcile(m: Dict[str, Any]) -> Any:
                reconcile_calls.append(dict(m))
                return MagicMock(was_updated=False, reject_reason="no_record", envelope=None)

            with patch.object(_tl, "_reconcile_inbound_message", _fake_reconcile):
                await _tl.handle_command_result(bridge, None, msg)

            assert fut.done(), "pending future must be resolved"
            assert len(reconcile_calls) >= 1, "reconcile must be called after future resolution"

        asyncio.run(_inner())

    def test_b04_ack_advances_tracking_record_via_inbound_handler(self) -> None:
        """AC1: command_result ACK through real handler advances phase to acknowledged."""
        _, rt = _make_record(
            session_id="ses-b04",
            contract_id="ctr-b04",
        )
        bridge = _make_bridge()
        msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "task_id": "t-b04",
            "device_id": "dev-b04",
            "payload": {
                "contract_id": "ctr-b04",
                "session_id": "ses-b04",
            },
            "status": "",
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            _run(_tl.handle_command_result(bridge, None, msg))

        rec = _find_record(rt, "ctr-b04", "ses-b04")
        assert rec is not None, "tracking record must be findable in the runtime"
        assert rec.phase in (
            DelegatedExecutionPhase.acknowledged,
            DelegatedExecutionPhase.in_progress,
            DelegatedExecutionPhase.completed,
        ), f"phase must have advanced from pending_ack; got {rec.phase}"


# ===========================================================================
# Group C — handle_task_progress → PROGRESS phase advance (AC2)
# ===========================================================================


@_SKIP_CORE
class TestGroupC_HandleTaskProgressAdvancesPhase:
    """AC2: PROGRESS signals via ``handle_task_progress`` advance tracking phase."""

    def test_c01_progress_message_advances_tracking_record(self) -> None:
        """AC2: task_progress 'running' through real handler advances to in_progress."""
        _, rt = _make_record(
            session_id="ses-c01",
            contract_id="ctr-c01",
        )
        bridge = _make_bridge()
        msg = {
            "type": "task_progress",
            "task_id": "t-c01",
            "device_id": "dev-c01",
            "message_id": str(uuid.uuid4()),
            "progress": 42,
            "status": "running",
            "payload": {
                "contract_id": "ctr-c01",
                "session_id": "ses-c01",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_progress(bridge, None, msg))

        rec = _find_record(rt, "ctr-c01", "ses-c01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.in_progress, (
            f"progress signal must advance phase to in_progress; got {rec.phase}"
        )

    def test_c02_progress_ack_signal_advances_to_at_least_acknowledged(self) -> None:
        """AC2: task_progress 'pending' (ack kind) advances phase."""
        _, rt = _make_record(
            session_id="ses-c02",
            contract_id="ctr-c02",
        )
        bridge = _make_bridge()
        msg = {
            "type": "task_progress",
            "task_id": "t-c02",
            "device_id": "dev-c02",
            "message_id": str(uuid.uuid4()),
            "status": "pending",
            "payload": {
                "contract_id": "ctr-c02",
                "session_id": "ses-c02",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_progress(bridge, None, msg))

        rec = _find_record(rt, "ctr-c02", "ses-c02")
        assert rec is not None
        assert rec.phase in (
            DelegatedExecutionPhase.acknowledged,
            DelegatedExecutionPhase.in_progress,
            DelegatedExecutionPhase.completed,
        ), f"phase must have advanced; got {rec.phase}"

    def test_c03_progress_handler_calls_reconcile(self) -> None:
        """AC2: _try_reconcile is invoked inside handle_task_progress."""
        bridge = _make_bridge()
        calls: list = []
        msg = {
            "type": "task_progress",
            "task_id": "t-c03",
            "message_id": str(uuid.uuid4()),
            "contract_id": "ctr-c03",
            "session_id": "ses-c03",
        }

        def _fake(m: Dict[str, Any]) -> Any:
            calls.append(dict(m))
            return MagicMock(was_updated=False, reject_reason="no_record", envelope=None)

        with patch.object(_tl, "_reconcile_inbound_message", _fake):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_progress(bridge, None, msg))

        assert calls, "handle_task_progress must call _reconcile_inbound_message"


# ===========================================================================
# Group D — handle_task_result → RESULT / truth-chain phase advance (AC3)
# ===========================================================================


@_SKIP_CORE
class TestGroupD_HandleTaskResultAdvancesPhase:
    """AC3: RESULT signals via ``handle_task_result`` advance tracking to completed."""

    def test_d01_result_message_advances_tracking_record_via_legacy_path(self) -> None:
        """AC3: task_result 'completed' through legacy path (no truth chain) advances phase."""
        _, rt = _make_record(
            session_id="ses-d01",
            contract_id="ctr-d01",
        )
        bridge = _make_bridge()
        msg = {
            "type": "task_result",
            "task_id": "t-d01",
            "device_id": "dev-d01",
            "message_id": str(uuid.uuid4()),
            "status": "completed",
            "payload": {
                "contract_id": "ctr-d01",
                "session_id": "ses-d01",
                "result": "done",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_tl, "_run_task_result_truth_chain", None):
            with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
                with patch.object(_tl, "_ingest_participant_truth", None):
                    with patch.object(_tl, "_evaluate_continuity_legality", None):
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_tl.handle_task_result(bridge, None, msg))

        rec = _find_record(rt, "ctr-d01", "ses-d01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.completed, (
            f"RESULT signal must advance phase to completed; got {rec.phase}"
        )

    def test_d02_failed_result_advances_to_failed(self) -> None:
        """AC3: task_result 'failed' through legacy path advances phase to failed."""
        _, rt = _make_record(
            session_id="ses-d02",
            contract_id="ctr-d02",
        )
        bridge = _make_bridge()
        msg = {
            "type": "task_result",
            "task_id": "t-d02",
            "device_id": "dev-d02",
            "message_id": str(uuid.uuid4()),
            "status": "failed",
            "payload": {
                "contract_id": "ctr-d02",
                "session_id": "ses-d02",
                "error": "execution failed",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_tl, "_run_task_result_truth_chain", None):
            with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
                with patch.object(_tl, "_ingest_participant_truth", None):
                    with patch.object(_tl, "_evaluate_continuity_legality", None):
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_tl.handle_task_result(bridge, None, msg))

        rec = _find_record(rt, "ctr-d02", "ses-d02")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.failed, (
            f"failed RESULT signal must advance phase to failed; got {rec.phase}"
        )


# ===========================================================================
# Group E — handle_goal_execution_result → RESULT phase advance (AC4)
# ===========================================================================


@_SKIP_GE
class TestGroupE_HandleGoalExecutionResultAdvancesPhase:
    """AC4: RESULT signals via ``handle_goal_execution_result`` advance phase to completed."""

    def test_e01_goal_execution_result_advances_tracking_record_via_legacy_path(
        self,
    ) -> None:
        """AC4: goal_execution_result success through legacy path advances phase."""
        _, rt = _make_record(
            session_id="ses-e01",
            contract_id="ctr-e01",
        )
        bridge = _make_bridge()
        msg = {
            "type": "goal_execution_result",
            "device_id": "dev-e01",
            "message_id": str(uuid.uuid4()),
            "payload": {
                "task_id": "t-e01",
                "contract_id": "ctr-e01",
                "session_id": "ses-e01",
                "status": "success",
                "result": "goal achieved",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_ge, "_run_task_result_truth_chain", None):
            with patch.object(_ge, "_reconcile_goal_result", reconcile_with_rt):
                with patch.object(_ge, "_ingest_goal_result_truth", None):
                    with patch.object(_ge, "store_task_result", None):
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_ge.handle_goal_execution_result(bridge, None, msg))

        rec = _find_record(rt, "ctr-e01", "ses-e01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.completed, (
            f"goal_execution_result success must advance phase to completed; got {rec.phase}"
        )

    def test_e02_goal_execution_result_failed_advances_to_failed(self) -> None:
        """AC4: goal_execution_result failed through legacy path advances phase to failed."""
        _, rt = _make_record(
            session_id="ses-e02",
            contract_id="ctr-e02",
        )
        bridge = _make_bridge()
        msg = {
            "type": "goal_execution_result",
            "device_id": "dev-e02",
            "message_id": str(uuid.uuid4()),
            "payload": {
                "task_id": "t-e02",
                "contract_id": "ctr-e02",
                "session_id": "ses-e02",
                "status": "failed",
                "result": "goal failed",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_ge, "_run_task_result_truth_chain", None):
            with patch.object(_ge, "_reconcile_goal_result", reconcile_with_rt):
                with patch.object(_ge, "_ingest_goal_result_truth", None):
                    with patch.object(_ge, "store_task_result", None):
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_ge.handle_goal_execution_result(bridge, None, msg))

        rec = _find_record(rt, "ctr-e02", "ses-e02")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.failed, (
            f"failed goal_execution_result must advance phase to failed; got {rec.phase}"
        )


# ===========================================================================
# Group F — handle_error → ERROR phase advance (AC5)
# ===========================================================================


@_SKIP_CORE
class TestGroupF_HandleErrorAdvancesPhase:
    """AC5: ERROR signals via ``handle_error`` advance tracking record to failed."""

    def test_f01_error_message_advances_tracking_record_to_failed(self) -> None:
        """AC5: error message through real handler advances phase to failed."""
        _, rt = _make_record(
            session_id="ses-f01",
            contract_id="ctr-f01",
        )
        bridge = _make_bridge()
        msg = {
            "type": "error",
            "task_id": "t-f01",
            "device_id": "dev-f01",
            "message_id": str(uuid.uuid4()),
            "error_code": "EXECUTION_FAILED",
            "error_message": "task execution error",
            "contract_id": "ctr-f01",
            "session_id": "ses-f01",
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_error(bridge, None, msg))

        rec = _find_record(rt, "ctr-f01", "ses-f01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.failed, (
            f"error signal must advance phase to failed; got {rec.phase}"
        )

    def test_f02_error_handler_calls_reconcile(self) -> None:
        """AC5: _try_reconcile is invoked inside handle_error."""
        bridge = _make_bridge()
        calls: list = []
        msg = {
            "type": "error",
            "message_id": str(uuid.uuid4()),
            "contract_id": "ctr-f02",
            "session_id": "ses-f02",
            "error_code": "E002",
        }

        def _fake(m: Dict[str, Any]) -> Any:
            calls.append(dict(m))
            return MagicMock(was_updated=False, reject_reason="no_record", envelope=None)

        with patch.object(_tl, "_reconcile_inbound_message", _fake):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_error(bridge, None, msg))

        assert calls, "handle_error must call _reconcile_inbound_message"


# ===========================================================================
# Group G — handle_task_end → END / completion phase advance (AC6)
# ===========================================================================


@_SKIP_CORE
class TestGroupG_HandleTaskEndAdvancesPhase:
    """AC6: END signals via ``handle_task_end`` advance tracking phase."""

    def test_g01_task_end_completed_advances_tracking_record(self) -> None:
        """AC6: task_end 'completed' through real handler advances phase to completed."""
        _, rt = _make_record(
            session_id="ses-g01",
            contract_id="ctr-g01",
        )
        bridge = _make_bridge()
        msg = {
            "type": "task_end",
            "task_id": "t-g01",
            "device_id": "dev-g01",
            "message_id": str(uuid.uuid4()),
            "status": "completed",
            "payload": {
                "contract_id": "ctr-g01",
                "session_id": "ses-g01",
            },
        }
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_end(bridge, None, msg))

        rec = _find_record(rt, "ctr-g01", "ses-g01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.completed, (
            f"task_end 'completed' must advance phase to completed; got {rec.phase}"
        )

    def test_g02_task_end_returns_ack_regardless_of_reconcile_outcome(self) -> None:
        """AC6: task_end_ack is always returned (non-disruptive reconcile)."""
        bridge = _make_bridge()
        msg = {
            "type": "task_end",
            "task_id": "t-g02",
            "device_id": "dev-g02",
            "message_id": str(uuid.uuid4()),
            "status": "completed",
        }
        with patch.object(_tl, "_reconcile_inbound_message", None):
            with patch.object(_tl, "_ingest_participant_truth", None):
                result = _run(_tl.handle_task_end(bridge, None, msg))

        assert result.get("type") == "task_end_ack"


# ===========================================================================
# Group H — No-key guard: messages without identity fields are no-ops (AC8)
# ===========================================================================


@_SKIP_CORE
class TestGroupH_NoKeyGuard:
    """AC8: messages without contract_id / session_id are silently no-ops."""

    def test_h01_command_result_no_keys_does_not_raise(self) -> None:
        """AC8: handle_command_result without identity fields completes normally."""
        bridge = _make_bridge()
        msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "task_id": "t-h01",
        }
        reconcile_calls: list = []

        def _fake(m: Dict[str, Any]) -> Any:
            reconcile_calls.append(dict(m))
            return MagicMock(was_updated=False, reject_reason="no_key", envelope=None)

        with patch.object(_tl, "_reconcile_inbound_message", _fake):
            _run(_tl.handle_command_result(bridge, None, msg))
        # reconcile may be called but must not raise; no tracking advance expected

    def test_h02_task_progress_no_keys_does_not_raise(self) -> None:
        """AC8: handle_task_progress without identity fields completes normally."""
        bridge = _make_bridge()
        msg = {
            "type": "task_progress",
            "task_id": "t-h02",
            "message_id": str(uuid.uuid4()),
            "progress": 50,
        }
        with patch.object(_tl, "_reconcile_inbound_message", None):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_progress(bridge, None, msg))  # must not raise

    def test_h03_error_no_keys_does_not_raise(self) -> None:
        """AC8: handle_error without identity fields completes normally."""
        bridge = _make_bridge()
        msg = {
            "type": "error",
            "message_id": str(uuid.uuid4()),
            "error_code": "E_GENERIC",
        }
        with patch.object(_tl, "_reconcile_inbound_message", None):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_error(bridge, None, msg))  # must not raise


# ===========================================================================
# Group I — Full ACK → PROGRESS → RESULT lifecycle through inbound path
# ===========================================================================


@_SKIP_CORE
class TestGroupI_FullLifecycleThroughInboundPath:
    """AC1–AC3: Full ACK→PROGRESS→RESULT sequence advances tracking phase monotonically."""

    def test_i01_ack_progress_result_sequence_advances_phases(self) -> None:
        """AC1–AC3: three handler calls in sequence close the full tracking lifecycle."""
        _, rt = _make_record(
            session_id="ses-i01",
            contract_id="ctr-i01",
            device_id="dev-i01",
        )
        bridge = _make_bridge()
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        # -- Step 1: ACK (command_result, bare) → acknowledged --
        ack_msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "task_id": "t-i01",
            "device_id": "dev-i01",
            "payload": {
                "contract_id": "ctr-i01",
                "session_id": "ses-i01",
            },
            "status": "",
        }
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            _run(_tl.handle_command_result(bridge, None, ack_msg))

        rec = _find_record(rt, "ctr-i01", "ses-i01")
        assert rec is not None
        assert rec.phase in (
            DelegatedExecutionPhase.acknowledged,
            DelegatedExecutionPhase.in_progress,
        ), f"after ACK, phase must be at least acknowledged; got {rec.phase}"

        # -- Step 2: PROGRESS (task_progress, running) → in_progress --
        progress_msg = {
            "type": "task_progress",
            "task_id": "t-i01",
            "device_id": "dev-i01",
            "message_id": str(uuid.uuid4()),
            "progress": 60,
            "status": "running",
            "payload": {
                "contract_id": "ctr-i01",
                "session_id": "ses-i01",
            },
        }
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            with patch.object(_tl, "_ingest_participant_truth", None):
                _run(_tl.handle_task_progress(bridge, None, progress_msg))

        rec = _find_record(rt, "ctr-i01", "ses-i01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.in_progress, (
            f"after PROGRESS, phase must be in_progress; got {rec.phase}"
        )

        # -- Step 3: RESULT (task_result, completed) → completed --
        result_msg = {
            "type": "task_result",
            "task_id": "t-i01",
            "device_id": "dev-i01",
            "message_id": str(uuid.uuid4()),
            "status": "completed",
            "payload": {
                "contract_id": "ctr-i01",
                "session_id": "ses-i01",
                "result": "task finished",
            },
        }
        with patch.object(_tl, "_run_task_result_truth_chain", None):
            with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
                with patch.object(_tl, "_ingest_participant_truth", None):
                    with patch.object(_tl, "_evaluate_continuity_legality", None):
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_tl.handle_task_result(bridge, None, result_msg))

        rec = _find_record(rt, "ctr-i01", "ses-i01")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.completed, (
            f"after RESULT, phase must be completed; got {rec.phase}"
        )

    def test_i02_command_result_ack_then_command_result_final_result_closes(
        self,
    ) -> None:
        """AC1, AC10: two command_result signals (bare ACK then completed) close tracking."""
        _, rt = _make_record(
            session_id="ses-i02",
            contract_id="ctr-i02",
        )
        bridge = _make_bridge()
        reconcile_with_rt = _make_reconcile_with_runtime(rt)

        # ACK
        ack_msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "payload": {"contract_id": "ctr-i02", "session_id": "ses-i02"},
            "status": "",
        }
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            _run(_tl.handle_command_result(bridge, None, ack_msg))

        # Terminal result
        result_msg = {
            "type": "command_result",
            "message_id": str(uuid.uuid4()),
            "payload": {"contract_id": "ctr-i02", "session_id": "ses-i02"},
            "status": "completed",
        }
        with patch.object(_tl, "_reconcile_inbound_message", reconcile_with_rt):
            _run(_tl.handle_command_result(bridge, None, result_msg))

        rec = _find_record(rt, "ctr-i02", "ses-i02")
        assert rec is not None
        assert rec.phase == DelegatedExecutionPhase.completed, (
            f"command_result 'completed' must close tracking to completed; got {rec.phase}"
        )
