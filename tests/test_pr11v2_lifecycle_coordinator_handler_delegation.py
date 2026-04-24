"""tests/test_pr11v2_lifecycle_coordinator_handler_delegation.py
================================================================
PR-11-V2: Tests verifying that gateway handlers delegate lifecycle
processing to the AndroidDelegatedRuntimeLifecycleCoordinator.

Coverage groups
---------------
A.  reconciliation_signal handler — delegates to coordinator.
B.  takeover_response handler — delegates to coordinator.
C.  delegated_signal handler — delegates to coordinator.
D.  Coordinator on_execution_signal — device_id is threaded through.
E.  Coordinator on_execution_signal — PR-5A result_consumer_called flag.
F.  ACK response shapes — all three handlers return correct ACK types.
G.  Handler imports — coordinator is importable from each handler module.
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import uuid
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# ---------------------------------------------------------------------------
# Helpers for importing handler modules directly (bypasses galaxy_gateway
# __init__.py which requires pydantic, unavailable in the test environment).
# ---------------------------------------------------------------------------

_HANDLERS_DIR = os.path.join(
    _PROJECT_ROOT,
    "galaxy_gateway", "android", "handlers",
)


def _load_handler_module(filename: str):
    """Load a handler module by filename, bypassing the package __init__.py."""
    path = os.path.join(_HANDLERS_DIR, filename)
    spec = importlib.util.spec_from_file_location(
        f"_test_handler_{filename[:-3]}", path
    )
    if spec is None or spec.loader is None:
        return None
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)  # type: ignore[union-attr]
        return m
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Guard imports
# ---------------------------------------------------------------------------

try:
    from core.android_delegated_runtime_lifecycle_coordinator import (
        AndroidLifecycleCoordinatorOutcome,
        get_lifecycle_coordinator,
        reset_lifecycle_coordinator,
    )
    _LC_AVAILABLE = True
except ImportError:
    _LC_AVAILABLE = False

_recon_mod = _load_handler_module("reconciliation_signal.py")
_RECON_HANDLER_AVAILABLE = _recon_mod is not None and hasattr(_recon_mod, "handle_reconciliation_signal")

_takeover_mod = _load_handler_module("takeover_response.py")
_TAKEOVER_HANDLER_AVAILABLE = _takeover_mod is not None and hasattr(_takeover_mod, "handle_takeover_response")

_delegated_mod = _load_handler_module("delegated_signal.py")
_DELEGATED_HANDLER_AVAILABLE = _delegated_mod is not None and hasattr(_delegated_mod, "handle_delegated_execution_signal")


if _RECON_HANDLER_AVAILABLE:
    handle_reconciliation_signal = _recon_mod.handle_reconciliation_signal  # type: ignore[union-attr]

if _TAKEOVER_HANDLER_AVAILABLE:
    handle_takeover_response = _takeover_mod.handle_takeover_response  # type: ignore[union-attr]

if _DELEGATED_HANDLER_AVAILABLE:
    handle_delegated_execution_signal = _delegated_mod.handle_delegated_execution_signal  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bridge() -> MagicMock:
    return MagicMock()


def _make_websocket() -> MagicMock:
    return MagicMock()


def _run(coro) -> Any:
    return asyncio.run(coro)


def _mock_outcome(event_type: str = "test", was_handled: bool = True, extra: dict | None = None) -> Any:
    if not _LC_AVAILABLE:
        return MagicMock()
    return AndroidLifecycleCoordinatorOutcome(
        was_handled=was_handled,
        event_type=event_type,
        session_id="sess-test",
        phase_before="handoff_dispatched",
        phase_after="reconciled",
        was_transitioned=True,
        description=f"{event_type} processed",
        extra=extra or {},
    )


# ===========================================================================
# Group A: reconciliation_signal handler delegation
# ===========================================================================

@pytest.mark.skipif(
    not _RECON_HANDLER_AVAILABLE or not _LC_AVAILABLE,
    reason="reconciliation_signal handler or coordinator unavailable",
)
class TestReconciliationSignalDelegation:

    def test_A01_handler_delegates_to_coordinator_on_reconciliation_signal(self):
        """handle_reconciliation_signal must call coordinator.on_reconciliation_signal."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev-A01",
            "message_id": str(uuid.uuid4()),
            "session_id": "sess-A01",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_reconciliation_signal.return_value = _mock_outcome("reconciliation_signal")

        with patch.object(_recon_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            _run(handle_reconciliation_signal(bridge, ws, message))

        mock_coordinator.on_reconciliation_signal.assert_called_once()
        call_kwargs = mock_coordinator.on_reconciliation_signal.call_args
        assert call_kwargs.kwargs.get("message") is message

    def test_A02_handler_returns_reconciliation_signal_ack(self):
        """handle_reconciliation_signal must return reconciliation_signal_ack."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "reconciliation_signal",
            "device_id": "dev-A02",
            "message_id": "mid-A02",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_reconciliation_signal.return_value = _mock_outcome("reconciliation_signal")

        with patch.object(_recon_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_reconciliation_signal(bridge, ws, message))

        assert ack["type"] == "reconciliation_signal_ack"
        assert ack["device_id"] == "dev-A02"
        assert ack["correlation_id"] == "mid-A02"
        assert ack["version"] == "3.0"

    def test_A03_handler_is_non_raising_when_coordinator_raises(self):
        """handle_reconciliation_signal must not raise when coordinator raises."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {"type": "reconciliation_signal", "device_id": "dev-A03"}
        mock_coordinator = MagicMock()
        mock_coordinator.on_reconciliation_signal.side_effect = RuntimeError("coordinator exploded")

        with patch.object(_recon_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_reconciliation_signal(bridge, ws, message))

        assert ack["type"] == "reconciliation_signal_ack"

    def test_A04_handler_degrades_gracefully_when_coordinator_absent(self):
        """handle_reconciliation_signal must return ACK even when coordinator is None."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {"type": "reconciliation_signal", "device_id": "dev-A04"}

        with patch.object(_recon_mod, "_get_lifecycle_coordinator", None):
            ack = _run(handle_reconciliation_signal(bridge, ws, message))

        assert ack["type"] == "reconciliation_signal_ack"


# ===========================================================================
# Group B: takeover_response handler delegation
# ===========================================================================

@pytest.mark.skipif(
    not _TAKEOVER_HANDLER_AVAILABLE or not _LC_AVAILABLE,
    reason="takeover_response handler or coordinator unavailable",
)
class TestTakeoverResponseDelegation:

    def test_B01_handler_delegates_to_coordinator_on_takeover_response(self):
        """handle_takeover_response must call coordinator.on_takeover_response."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "takeover_response",
            "device_id": "dev-B01",
            "message_id": str(uuid.uuid4()),
            "takeover_id": "tkv-B01",
            "accepted": True,
            "reason": "",
            "session_id": "sess-B01",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = _mock_outcome("takeover_response")

        with patch.object(_takeover_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            _run(handle_takeover_response(bridge, ws, message))

        mock_coordinator.on_takeover_response.assert_called_once()
        kwargs = mock_coordinator.on_takeover_response.call_args.kwargs
        assert kwargs["session_id"] == "sess-B01"
        assert kwargs["takeover_id"] == "tkv-B01"
        assert kwargs["accepted"] is True
        assert kwargs["device_id"] == "dev-B01"

    def test_B02_handler_threads_rejected_decision(self):
        """handle_takeover_response threads accepted=False correctly."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "takeover_response",
            "device_id": "dev-B02",
            "takeover_id": "tkv-B02",
            "accepted": False,
            "reason": "device_busy",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = _mock_outcome("takeover_response")

        with patch.object(_takeover_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            _run(handle_takeover_response(bridge, ws, message))

        kwargs = mock_coordinator.on_takeover_response.call_args.kwargs
        assert kwargs["accepted"] is False
        assert kwargs["reason"] == "device_busy"

    def test_B03_handler_returns_takeover_response_ack(self):
        """handle_takeover_response must return takeover_response_ack."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "takeover_response",
            "device_id": "dev-B03",
            "message_id": "mid-B03",
            "takeover_id": "tkv-B03",
            "accepted": True,
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.return_value = _mock_outcome("takeover_response")

        with patch.object(_takeover_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_takeover_response(bridge, ws, message))

        assert ack["type"] == "takeover_response_ack"
        assert ack["device_id"] == "dev-B03"
        assert ack["correlation_id"] == "mid-B03"
        assert ack["takeover_id"] == "tkv-B03"
        assert ack["accepted"] is True

    def test_B04_handler_is_non_raising_when_coordinator_raises(self):
        """handle_takeover_response must not raise when coordinator raises."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "takeover_response",
            "device_id": "dev-B04",
            "takeover_id": "tkv-B04",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_takeover_response.side_effect = RuntimeError("boom")

        with patch.object(_takeover_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_takeover_response(bridge, ws, message))

        assert ack["type"] == "takeover_response_ack"


# ===========================================================================
# Group C: delegated_signal handler delegation
# ===========================================================================

@pytest.mark.skipif(
    not _DELEGATED_HANDLER_AVAILABLE or not _LC_AVAILABLE,
    reason="delegated_signal handler or coordinator unavailable",
)
class TestDelegatedSignalDelegation:

    def test_C01_handler_delegates_to_coordinator_on_execution_signal(self):
        """handle_delegated_execution_signal must call coordinator.on_execution_signal."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "delegated_execution_signal",
            "device_id": "dev-C01",
            "message_id": str(uuid.uuid4()),
            "session_id": "sess-C01",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_execution_signal.return_value = _mock_outcome(
            "execution_signal",
            extra={"signal_kind": "ack", "was_updated": True, "result_consumer_called": False},
        )

        with patch.object(_delegated_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            _run(handle_delegated_execution_signal(bridge, ws, message))

        mock_coordinator.on_execution_signal.assert_called_once()
        kwargs = mock_coordinator.on_execution_signal.call_args.kwargs
        assert kwargs["message"] is message
        assert kwargs["device_id"] == "dev-C01"

    def test_C02_handler_returns_delegated_execution_signal_ack(self):
        """handle_delegated_execution_signal must return delegated_execution_signal_ack."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "delegated_execution_signal",
            "device_id": "dev-C02",
            "message_id": "mid-C02",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_execution_signal.return_value = _mock_outcome(
            "execution_signal",
            extra={"signal_kind": "", "was_updated": False, "result_consumer_called": False},
        )

        with patch.object(_delegated_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_delegated_execution_signal(bridge, ws, message))

        assert ack["type"] == "delegated_execution_signal_ack"
        assert ack["device_id"] == "dev-C02"
        assert ack["correlation_id"] == "mid-C02"
        assert ack["version"] == "3.0"

    def test_C03_handler_is_non_raising_when_coordinator_raises(self):
        """handle_delegated_execution_signal must not raise when coordinator raises."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {"type": "delegated_execution_signal", "device_id": "dev-C03"}
        mock_coordinator = MagicMock()
        mock_coordinator.on_execution_signal.side_effect = RuntimeError("coordinator exploded")

        with patch.object(_delegated_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_delegated_execution_signal(bridge, ws, message))

        assert ack["type"] == "delegated_execution_signal_ack"

    def test_C04_handler_logs_result_consumer_called(self):
        """handle_delegated_execution_signal logs result_consumer_called from extra."""
        bridge = _make_bridge()
        ws = _make_websocket()
        message = {
            "type": "delegated_execution_signal",
            "device_id": "dev-C04",
            "session_id": "sess-C04",
        }
        mock_coordinator = MagicMock()
        mock_coordinator.on_execution_signal.return_value = _mock_outcome(
            "execution_signal",
            extra={"signal_kind": "result", "was_updated": True, "result_consumer_called": True},
        )

        # Verify no exception is raised when result_consumer_called=True
        with patch.object(_delegated_mod, "_get_lifecycle_coordinator", return_value=mock_coordinator):
            ack = _run(handle_delegated_execution_signal(bridge, ws, message))

        assert ack["type"] == "delegated_execution_signal_ack"


# ===========================================================================
# Group D: Coordinator on_execution_signal — device_id parameter
# ===========================================================================

@pytest.mark.skipif(not _LC_AVAILABLE, reason="coordinator unavailable")
class TestCoordinatorExecutionSignalDeviceId:

    def test_D01_on_execution_signal_accepts_device_id_kwarg(self):
        """on_execution_signal must accept device_id as a keyword argument."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {
            "type": "delegated_execution_signal",
            "device_id": "dev-D01",
            "session_id": "sess-D01",
        }
        outcome = lc.on_execution_signal(message=message, device_id="dev-D01")
        assert outcome.was_handled is True
        assert outcome.event_type == "execution_signal"

    def test_D02_on_execution_signal_device_id_falls_back_to_message(self):
        """on_execution_signal extracts device_id from message when kwarg is empty."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {
            "type": "delegated_execution_signal",
            "device_id": "dev-D02",
        }
        outcome = lc.on_execution_signal(message=message)
        assert outcome.was_handled is True

    def test_D03_on_execution_signal_extra_has_result_consumer_called(self):
        """on_execution_signal must include result_consumer_called in extra."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {"type": "delegated_execution_signal"}
        outcome = lc.on_execution_signal(message=message)
        assert "result_consumer_called" in outcome.extra


# ===========================================================================
# Group E: Coordinator on_execution_signal — PR-5A result consumer
# ===========================================================================

@pytest.mark.skipif(not _LC_AVAILABLE, reason="coordinator unavailable")
class TestCoordinatorPR5AResultConsumer:

    def test_E01_result_consumer_called_when_result_kind_updated(self):
        """on_execution_signal calls result consumer for result-kind updated signals."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {"type": "delegated_execution_signal", "session_id": "sess-E01"}

        mock_ingress_outcome = MagicMock()
        mock_ingress_outcome.was_updated = True
        mock_ingress_outcome.reject_reason = ""
        mock_ingress_env = MagicMock()
        mock_ingress_env.signal_kind = MagicMock()
        mock_ingress_env.signal_kind.value = "result"
        mock_ingress_env.session_id = "sess-E01"
        mock_ingress_outcome.envelope = mock_ingress_env

        mock_consumer = MagicMock()
        mock_consumer.consume_android_behavioral_result = MagicMock(return_value={})

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_ingress_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = lc.on_execution_signal(
                message=message,
                device_id="dev-E01",
            )

        assert outcome.was_handled is True
        assert outcome.extra.get("result_consumer_called") is True
        mock_consumer.consume_android_behavioral_result.assert_called_once()
        call_kwargs = mock_consumer.consume_android_behavioral_result.call_args
        assert call_kwargs.args[0] is mock_ingress_outcome
        assert "android_bridge:dev-E01" in call_kwargs.kwargs.get("source", "")

    def test_E02_result_consumer_not_called_for_non_result_kind(self):
        """on_execution_signal does not call result consumer for non-result signals."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {"type": "delegated_execution_signal"}

        mock_ingress_outcome = MagicMock()
        mock_ingress_outcome.was_updated = True
        mock_ingress_outcome.reject_reason = ""
        mock_ingress_env = MagicMock()
        mock_ingress_env.signal_kind = MagicMock()
        mock_ingress_env.signal_kind.value = "ack"  # not "result"
        mock_ingress_env.session_id = ""
        mock_ingress_outcome.envelope = mock_ingress_env

        mock_consumer = MagicMock()

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_ingress_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = lc.on_execution_signal(message=message)

        assert outcome.extra.get("result_consumer_called") is False
        mock_consumer.consume_android_behavioral_result.assert_not_called()

    def test_E03_result_consumer_not_called_when_not_updated(self):
        """on_execution_signal does not call consumer when signal was not updated."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {"type": "delegated_execution_signal"}

        mock_ingress_outcome = MagicMock()
        mock_ingress_outcome.was_updated = False  # not updated
        mock_ingress_outcome.reject_reason = "duplicate"
        mock_ingress_env = MagicMock()
        mock_ingress_env.signal_kind = MagicMock()
        mock_ingress_env.signal_kind.value = "result"
        mock_ingress_env.session_id = ""
        mock_ingress_outcome.envelope = mock_ingress_env

        mock_consumer = MagicMock()

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_ingress_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = lc.on_execution_signal(message=message)

        assert outcome.extra.get("result_consumer_called") is False
        mock_consumer.consume_android_behavioral_result.assert_not_called()

    def test_E04_result_consumer_exception_is_non_fatal(self):
        """on_execution_signal does not raise when result consumer raises."""
        reset_lifecycle_coordinator()
        lc = get_lifecycle_coordinator()
        message = {"type": "delegated_execution_signal"}

        mock_ingress_outcome = MagicMock()
        mock_ingress_outcome.was_updated = True
        mock_ingress_outcome.reject_reason = ""
        mock_ingress_env = MagicMock()
        mock_ingress_env.signal_kind = MagicMock()
        mock_ingress_env.signal_kind.value = "result"
        mock_ingress_env.session_id = ""
        mock_ingress_outcome.envelope = mock_ingress_env

        mock_consumer = MagicMock()
        mock_consumer.consume_android_behavioral_result.side_effect = RuntimeError("consumer exploded")

        with patch(
            "core.android_delegated_runtime_lifecycle_coordinator._ingest_execution_signal",
            return_value=mock_ingress_outcome,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._android_result_consumer",
            mock_consumer,
        ), patch(
            "core.android_delegated_runtime_lifecycle_coordinator._RESULT_CONSUMER_AVAILABLE",
            True,
        ):
            outcome = lc.on_execution_signal(message=message)

        # Must still return was_handled=True; consumer exception is non-fatal.
        assert outcome.was_handled is True
        assert outcome.extra.get("result_consumer_called") is False


# ===========================================================================
# Group F: ACK response shapes
# ===========================================================================

@pytest.mark.skipif(
    not (_RECON_HANDLER_AVAILABLE and _TAKEOVER_HANDLER_AVAILABLE and _DELEGATED_HANDLER_AVAILABLE),
    reason="one or more handlers unavailable",
)
class TestAckResponseShapes:

    def _noop_coordinator(self, event_type: str = "test") -> MagicMock:
        mock = MagicMock()
        mock.on_reconciliation_signal.return_value = _mock_outcome(event_type)
        mock.on_takeover_response.return_value = _mock_outcome(event_type)
        mock.on_execution_signal.return_value = _mock_outcome(
            event_type,
            extra={"signal_kind": "", "was_updated": False, "result_consumer_called": False},
        )
        return mock

    def test_F01_reconciliation_ack_has_required_fields(self):
        msg = {"device_id": "dev-F01", "message_id": "mid-F01"}
        coordinator = self._noop_coordinator()
        with patch.object(_recon_mod, "_get_lifecycle_coordinator", return_value=coordinator):
            ack = _run(handle_reconciliation_signal(_make_bridge(), _make_websocket(), msg))
        for key in ("version", "type", "device_id", "message_id", "correlation_id"):
            assert key in ack, f"Missing field: {key}"
        assert ack["type"] == "reconciliation_signal_ack"

    def test_F02_takeover_ack_has_required_fields(self):
        msg = {"device_id": "dev-F02", "message_id": "mid-F02", "takeover_id": "tkv-F02"}
        coordinator = self._noop_coordinator()
        with patch.object(_takeover_mod, "_get_lifecycle_coordinator", return_value=coordinator):
            ack = _run(handle_takeover_response(_make_bridge(), _make_websocket(), msg))
        for key in ("version", "type", "device_id", "message_id", "correlation_id", "takeover_id", "accepted"):
            assert key in ack, f"Missing field: {key}"
        assert ack["type"] == "takeover_response_ack"

    def test_F03_delegated_ack_has_required_fields(self):
        msg = {"device_id": "dev-F03", "message_id": "mid-F03"}
        coordinator = self._noop_coordinator()
        with patch.object(_delegated_mod, "_get_lifecycle_coordinator", return_value=coordinator):
            ack = _run(handle_delegated_execution_signal(_make_bridge(), _make_websocket(), msg))
        for key in ("version", "type", "device_id", "message_id", "correlation_id"):
            assert key in ack, f"Missing field: {key}"
        assert ack["type"] == "delegated_execution_signal_ack"


# ===========================================================================
# Group G: Handler imports — coordinator importable from each handler module
# ===========================================================================

class TestHandlerImports:

    def test_G01_reconciliation_signal_module_imports_coordinator(self):
        """reconciliation_signal module exposes _get_lifecycle_coordinator."""
        m = _load_handler_module("reconciliation_signal.py")
        if m is None:
            pytest.skip("reconciliation_signal handler not loadable")
        assert hasattr(m, "_get_lifecycle_coordinator"), (
            "reconciliation_signal handler must expose _get_lifecycle_coordinator"
        )

    def test_G02_takeover_response_module_imports_coordinator(self):
        """takeover_response module exposes _get_lifecycle_coordinator."""
        m = _load_handler_module("takeover_response.py")
        if m is None:
            pytest.skip("takeover_response handler not loadable")
        assert hasattr(m, "_get_lifecycle_coordinator"), (
            "takeover_response handler must expose _get_lifecycle_coordinator"
        )

    def test_G03_delegated_signal_module_imports_coordinator(self):
        """delegated_signal module exposes _get_lifecycle_coordinator."""
        m = _load_handler_module("delegated_signal.py")
        if m is None:
            pytest.skip("delegated_signal handler not loadable")
        assert hasattr(m, "_get_lifecycle_coordinator"), (
            "delegated_signal handler must expose _get_lifecycle_coordinator"
        )

    def test_G04_reconciliation_signal_module_no_longer_imports_individual_ingress(self):
        """reconciliation_signal handler must NOT directly import participant truth ingress."""
        m = _load_handler_module("reconciliation_signal.py")
        if m is None:
            pytest.skip("reconciliation_signal handler not loadable")
        assert not hasattr(m, "_ingest_participant_truth"), (
            "reconciliation_signal handler must delegate to coordinator, "
            "not directly import _ingest_participant_truth"
        )

    def test_G05_takeover_response_module_no_longer_imports_individual_tracking(self):
        """takeover_response handler must NOT directly import takeover tracking."""
        m = _load_handler_module("takeover_response.py")
        if m is None:
            pytest.skip("takeover_response handler not loadable")
        assert not hasattr(m, "_record_takeover_response"), (
            "takeover_response handler must delegate to coordinator, "
            "not directly import _record_takeover_response"
        )

    def test_G06_delegated_signal_module_no_longer_imports_individual_ingress(self):
        """delegated_signal handler must NOT directly import delegated signal ingress."""
        m = _load_handler_module("delegated_signal.py")
        if m is None:
            pytest.skip("delegated_signal handler not loadable")
        assert not hasattr(m, "_ingest_delegated_signal"), (
            "delegated_signal handler must delegate to coordinator, "
            "not directly import _ingest_delegated_signal"
        )
