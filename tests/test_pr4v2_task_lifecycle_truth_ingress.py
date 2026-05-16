"""tests/test_pr4v2_task_lifecycle_truth_ingress.py
====================================================
Tests for PR-4V2: Android participant truth wired into
``galaxy_gateway/android/handlers/task_lifecycle.py``.

These tests demonstrate that Android-originated cancel, status, failure, result,
and task_phase signals are absorbed into V2 canonical orchestration state via the
:func:`~core.android_participant_truth_ingress.ingest_android_participant_truth_message`
ingress path, satisfying the acceptance criteria:

  AC1  Android participant truth enters V2 via task_lifecycle gateway handlers.
  AC2  cancel / failure / result affect canonical tracking record phase.
  AC3  status / task_phase advance the tracking record (progress signal).
  AC4  The ingress path is non-disruptive: handler behaviour is unchanged when
       the ingress module is unavailable.

Coverage groups
---------------
Group A — _try_ingest_participant_truth: module callable, truth_kind injected.
Group B — handle_task_cancel calls ingress with truth_kind='cancel' (AC1/AC2).
Group C — handle_error calls ingress with truth_kind='failure' (AC1/AC2).
Group D — handle_task_result calls ingress with truth_kind='result' (AC1/AC2).
Group E — handle_task_end calls ingress with truth_kind='task_phase' (AC1/AC3).
Group F — handle_task_progress calls ingress with truth_kind='status' (AC1/AC3).
Group G — handle_task_status calls ingress with truth_kind='status' (AC1/AC3).
Group H — Graceful degradation: ingress absent → handlers still work (AC4).
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import the handlers module
# ---------------------------------------------------------------------------

try:
    import galaxy_gateway.android.handlers.task_lifecycle as _tl

    _MODULE_AVAILABLE = True
except ImportError:
    _MODULE_AVAILABLE = False

_SKIP = pytest.mark.skipif(not _MODULE_AVAILABLE, reason="task_lifecycle unavailable")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge() -> Any:
    """Build a minimal mock bridge suitable for handler calls."""
    bridge = MagicMock()
    bridge._pending_responses = {}
    bridge._lock = asyncio.Lock()
    bridge._devices = {}
    return bridge


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Group A — _try_ingest_participant_truth helper
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupA_TryIngestHelper:
    def test_a1_helper_exists(self) -> None:
        """AC1: _try_ingest_participant_truth must exist in the module."""
        assert hasattr(_tl, "_try_ingest_participant_truth")
        assert callable(_tl._try_ingest_participant_truth)

    def test_a2_truth_kind_injected_via_setdefault(self) -> None:
        """AC1: helper sets 'truth_kind' in the message if absent."""
        captured: Dict[str, Any] = {}

        def _fake_ingest(msg: Dict[str, Any], **_kw: Any) -> Any:
            captured.update(msg)
            return MagicMock(was_reconciled=False, reject_reason="no_record", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _tl._try_ingest_participant_truth({"task_id": "t1"}, "cancel")

        assert captured.get("truth_kind") == "cancel"

    def test_a3_existing_truth_kind_not_overwritten(self) -> None:
        """AC1: helper does not overwrite a truth_kind already in the message."""
        captured: Dict[str, Any] = {}

        def _fake_ingest(msg: Dict[str, Any], **_kw: Any) -> Any:
            captured.update(msg)
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _tl._try_ingest_participant_truth({"truth_kind": "result"}, "cancel")

        # original truth_kind preserved
        assert captured.get("truth_kind") == "result"

    def test_a4_none_ingress_is_noop(self) -> None:
        """AC4: if _ingest_participant_truth is None, helper does not raise."""
        with patch.object(_tl, "_ingest_participant_truth", None):
            _tl._try_ingest_participant_truth({"task_id": "t1"}, "cancel")  # must not raise

    def test_a5_exception_in_ingress_is_suppressed(self) -> None:
        """AC4: exceptions inside the ingress call are suppressed."""

        def _raising(msg: Dict[str, Any], **_kw: Any) -> Any:
            raise RuntimeError("simulated ingress crash")

        with patch.object(_tl, "_ingest_participant_truth", _raising):
            _tl._try_ingest_participant_truth({"task_id": "t1"}, "failure")  # must not raise


# ---------------------------------------------------------------------------
# Group B — handle_task_cancel
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupB_HandleTaskCancel:
    def test_b1_ingress_called_with_cancel_kind(self) -> None:
        """AC1/AC2: handle_task_cancel calls ingress with truth_kind='cancel'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-b1", "device_id": "dev-b1"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="no_record", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_cancel(bridge, None, msg))

        assert any(c.get("truth_kind") == "cancel" for c in calls), (
            "handle_task_cancel must call ingress with truth_kind='cancel'"
        )

    def test_b2_ack_returned_regardless_of_ingress_outcome(self) -> None:
        """AC4: task_cancel_ack is returned even if ingress is unavailable."""
        bridge = _make_bridge()
        msg = {"task_id": "t-b2", "device_id": "dev-b2"}

        with patch.object(_tl, "_ingest_participant_truth", None):
            result = _run(_tl.handle_task_cancel(bridge, None, msg))

        assert result.get("type") == "task_cancel_ack"

    def test_b3_ingress_receives_task_and_device_ids(self) -> None:
        """AC1: task_id and device_id propagate to ingress."""
        bridge = _make_bridge()
        msg = {"task_id": "t-b3", "device_id": "dev-b3"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_cancel(bridge, None, msg))

        assert calls, "ingress must be called"
        assert calls[0].get("task_id") == "t-b3"
        assert calls[0].get("device_id") == "dev-b3"


# ---------------------------------------------------------------------------
# Group C — handle_error
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupC_HandleError:
    def test_c1_ingress_called_with_failure_kind(self) -> None:
        """AC1/AC2: handle_error calls ingress with truth_kind='failure'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-c1", "device_id": "dev-c1", "error_code": "E001"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_error(bridge, None, msg))

        assert any(c.get("truth_kind") == "failure" for c in calls)

    def test_c2_handle_error_does_not_raise_when_ingress_absent(self) -> None:
        """AC4: handle_error completes normally without ingress."""
        bridge = _make_bridge()
        msg = {"task_id": "t-c2", "device_id": "dev-c2"}
        with patch.object(_tl, "_ingest_participant_truth", None):
            _run(_tl.handle_error(bridge, None, msg))  # must not raise


# ---------------------------------------------------------------------------
# Group D — handle_task_result
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupD_HandleTaskResult:
    def test_d1_ingress_called_with_result_kind(self) -> None:
        """AC1/AC2: handle_task_result calls ingress with truth_kind='result'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-d1", "device_id": "dev-d1", "status": "completed"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            with patch.object(_tl, "store_task_result", None):
                # Force legacy path (truth chain unavailable) so
                # _try_ingest_participant_truth is called directly.
                with patch.object(_tl, "_run_task_result_truth_chain", None):
                    # Allow continuity legality check (fail-open).
                    with patch.object(_tl, "_evaluate_continuity_legality", None):
                        # Bypass durable idempotency so the same task_id can be
                        # reused across test sessions without being suppressed.
                        with patch(
                            "core.durable_result_idempotency.check_result_idempotency",
                            return_value=False,
                        ):
                            _run(_tl.handle_task_result(bridge, None, msg))

        assert any(c.get("truth_kind") == "result" for c in calls)

    def test_d2_future_resolved_even_with_ingress(self) -> None:
        """AC4: pending future is still resolved when ingress is active."""
        resolved: list = []

        async def _inner() -> None:
            bridge = _make_bridge()
            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            bridge._pending_responses["t-d2"] = fut
            msg = {"task_id": "t-d2", "device_id": "dev-d2", "status": "completed"}

            def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
                return MagicMock(
                    was_reconciled=True, reject_reason="", envelope=None,
                    canonical_update="done", tracking_record_phase="completed",
                )

            with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
                with patch.object(_tl, "store_task_result", None):
                    # Force legacy path and allow continuity legality so the
                    # function proceeds to resolve the pending future.
                    with patch.object(_tl, "_run_task_result_truth_chain", None):
                        with patch.object(_tl, "_evaluate_continuity_legality", None):
                            with patch(
                                "core.durable_result_idempotency.check_result_idempotency",
                                return_value=False,
                            ):
                                await _tl.handle_task_result(bridge, None, msg)

            resolved.append(fut.done())

        asyncio.run(_inner())
        assert resolved[0]


# ---------------------------------------------------------------------------
# Group E — handle_task_end
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupE_HandleTaskEnd:
    def test_e1_ingress_called_with_task_phase_kind(self) -> None:
        """AC1/AC3: handle_task_end calls ingress with truth_kind='task_phase'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-e1", "device_id": "dev-e1", "status": "completed"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_end(bridge, None, msg))

        assert any(c.get("truth_kind") == "task_phase" for c in calls)

    def test_e2_ack_returned(self) -> None:
        """AC4: task_end_ack is returned regardless of ingress state."""
        bridge = _make_bridge()
        msg = {"task_id": "t-e2", "device_id": "dev-e2"}
        with patch.object(_tl, "_ingest_participant_truth", None):
            result = _run(_tl.handle_task_end(bridge, None, msg))
        assert result.get("type") == "task_end_ack"


# ---------------------------------------------------------------------------
# Group F — handle_task_progress
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupF_HandleTaskProgress:
    def test_f1_ingress_called_with_status_kind(self) -> None:
        """AC1/AC3: handle_task_progress calls ingress with truth_kind='status'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-f1", "device_id": "dev-f1", "progress": 50}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_progress(bridge, None, msg))

        assert any(c.get("truth_kind") == "status" for c in calls)


# ---------------------------------------------------------------------------
# Group G — handle_task_status
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupG_HandleTaskStatus:
    def test_g1_ingress_called_with_status_kind(self) -> None:
        """AC1/AC3: handle_task_status calls ingress with truth_kind='status'."""
        bridge = _make_bridge()
        msg = {"task_id": "t-g1", "device_id": "dev-g1"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_status(bridge, None, msg))

        assert any(c.get("truth_kind") == "status" for c in calls)

    def test_g2_resolved_status_in_ingress_payload(self) -> None:
        """AC1: handle_task_status passes resolved status value to ingress via payload."""
        bridge = _make_bridge()
        # No pending future → status resolves to COMPLETED
        msg = {"task_id": "t-g2", "device_id": "dev-g2"}
        calls: list = []

        def _fake_ingest(m: Dict[str, Any], **_kw: Any) -> Any:
            calls.append(dict(m))
            return MagicMock(was_reconciled=False, reject_reason="", envelope=None)

        with patch.object(_tl, "_ingest_participant_truth", _fake_ingest):
            _run(_tl.handle_task_status(bridge, None, msg))

        assert calls, "ingress must be called"
        payload = calls[0].get("payload") or {}
        assert "status" in payload, "resolved status must be in payload for ingress"

    def test_g3_status_response_returned(self) -> None:
        """AC4: task_status_response is returned regardless of ingress state."""
        bridge = _make_bridge()
        msg = {"task_id": "t-g3", "device_id": "dev-g3"}
        with patch.object(_tl, "_ingest_participant_truth", None):
            result = _run(_tl.handle_task_status(bridge, None, msg))
        assert result.get("type") == "task_status_response"


# ---------------------------------------------------------------------------
# Group H — Graceful degradation end-to-end
# ---------------------------------------------------------------------------


@_SKIP
class TestGroupH_GracefulDegradation:
    """Verify that all handlers work correctly when the ingress module is absent."""

    def _patch_none(self) -> Any:
        return patch.object(_tl, "_ingest_participant_truth", None)

    def test_h1_cancel_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h1", "device_id": "dev-h1"}
        with self._patch_none():
            result = _run(_tl.handle_task_cancel(bridge, None, msg))
        assert result.get("type") == "task_cancel_ack"

    def test_h2_error_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h2", "device_id": "dev-h2"}
        with self._patch_none():
            _run(_tl.handle_error(bridge, None, msg))  # must not raise

    def test_h3_result_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h3", "device_id": "dev-h3", "status": "completed"}
        with self._patch_none():
            with patch.object(_tl, "store_task_result", None):
                _run(_tl.handle_task_result(bridge, None, msg))  # must not raise

    def test_h4_end_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h4", "device_id": "dev-h4"}
        with self._patch_none():
            result = _run(_tl.handle_task_end(bridge, None, msg))
        assert result.get("type") == "task_end_ack"

    def test_h5_progress_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h5", "device_id": "dev-h5", "progress": 25}
        with self._patch_none():
            _run(_tl.handle_task_progress(bridge, None, msg))  # must not raise

    def test_h6_status_with_no_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {"task_id": "t-h6", "device_id": "dev-h6"}
        with self._patch_none():
            result = _run(_tl.handle_task_status(bridge, None, msg))
        assert result.get("type") == "task_status_response"


@_SKIP
class TestGroupI_LocalModeUnifiedClosure:
    def test_i1_local_mode_result_uses_unified_result_ingress(self) -> None:
        bridge = _make_bridge()
        msg = {
            "task_id": "t-i1",
            "device_id": "dev-i1",
            "status": "completed",
            "route_mode": "android_local",
            "type": "task_result",
        }

        _fake_outcome = SimpleNamespace(
            completion_notified=True,
            is_fully_closed=False,
            evidence_acceptance_verdict="quarantine",
            incomplete_reason="evidence_gate:quarantine",
        )
        _ingest_async = AsyncMock(return_value=_fake_outcome)

        with patch(
            "core.durable_result_idempotency.check_result_idempotency",
            return_value=False,
        ), patch(
            "core.durable_result_idempotency.record_result_idempotency",
            return_value=None,
        ), patch(
            "core.unified_result_ingress.ingest_result_async",
            _ingest_async,
        ), patch.object(
            _tl,
            "_run_task_result_truth_chain",
            side_effect=AssertionError("legacy truth chain should not run for local mode"),
        ):
            _run(_tl.handle_task_result(bridge, None, msg))

        assert _ingest_async.call_count == 1
        assert msg["completion_notified"] is True
        assert msg["is_fully_closed"] is False
        assert msg["evidence_acceptance_verdict"] == "quarantine"
