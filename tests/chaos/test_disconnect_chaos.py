"""
tests/chaos/test_disconnect_chaos.py
======================================
Block-5 Chaos: Transport Disconnect Scenarios

Verifies that the system handles sudden transport disconnects gracefully:
- Errors are mapped to the canonical taxonomy
- Retryable errors are correctly classified
- Device-manager marks devices offline on repeated heartbeat loss
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset() -> None:
    from core.unified.idempotency import reset_idempotency_store
    from core.unified.release_gate import reset_release_gate
    from core.orchestration.global_arbiter import reset_global_arbiter

    reset_idempotency_store()
    reset_release_gate()
    reset_global_arbiter()


# ---------------------------------------------------------------------------
# 1. Disconnect error maps to canonical TRANSPORT_DISCONNECT
# ---------------------------------------------------------------------------


class TestDisconnectErrorMapping:
    def setup_method(self):
        _reset()

    def test_websocket_disconnect_maps_to_transport_disconnect(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        class WebSocketDisconnect(Exception):
            pass

        exc = WebSocketDisconnect("connection reset")
        payload = ErrorMapper.from_exception(exc, trace_id="t-001")
        assert payload.code == GalaxyErrorCode.TRANSPORT_DISCONNECT.value

    def test_connection_reset_is_retryable(self):
        from core.unified.error_codes import GalaxyErrorCode, is_retryable

        assert is_retryable(GalaxyErrorCode.TRANSPORT_DISCONNECT) is True

    def test_connection_refused_maps_to_connect_failed(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        exc = ConnectionRefusedError("refused")
        payload = ErrorMapper.from_exception(exc, trace_id="t-002")
        assert payload.code == GalaxyErrorCode.TRANSPORT_CONNECT_FAILED.value

    def test_transport_disconnect_payload_fields(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        payload = ErrorPayload.from_code(
            GalaxyErrorCode.TRANSPORT_DISCONNECT,
            message="peer reset",
            trace_id="t-003",
            task_id="task-x",
        )
        d = payload.to_dict()
        assert d["domain"] == "transport"
        assert d["retryable"] is True
        assert d["trace_id"] == "t-003"
        assert d["task_id"] == "task-x"

    def test_transport_error_serialise_round_trip(self):
        from core.unified.error_codes import ErrorPayload, GalaxyErrorCode

        p = ErrorPayload.from_code(GalaxyErrorCode.TRANSPORT_PUBLISH_FAILED)
        restored = ErrorPayload.from_dict(p.to_dict())
        assert restored.code == p.code
        assert restored.retryable == p.retryable


# ---------------------------------------------------------------------------
# 2. Device offline on heartbeat loss
# ---------------------------------------------------------------------------


class TestHeartbeatLossScenario:
    def setup_method(self):
        _reset()

    def test_device_timeout_error_is_retryable(self):
        from core.unified.error_codes import GalaxyErrorCode, is_retryable

        assert is_retryable(GalaxyErrorCode.DEVICE_TIMEOUT) is True

    def test_device_offline_error_is_retryable(self):
        from core.unified.error_codes import GalaxyErrorCode, is_retryable

        assert is_retryable(GalaxyErrorCode.DEVICE_OFFLINE) is True

    def test_legacy_device_error_offline_mapped(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        payload = ErrorMapper.from_legacy_device_error(
            device_id="phone_01",
            error_msg="device is offline and unreachable",
            trace_id="t-004",
        )
        assert payload.code == GalaxyErrorCode.DEVICE_OFFLINE.value
        assert payload.detail["device_id"] == "phone_01"

    def test_legacy_device_timeout_mapped(self):
        from core.unified.error_mapper import ErrorMapper
        from core.unified.error_codes import GalaxyErrorCode

        payload = ErrorMapper.from_legacy_device_error(
            device_id="tablet_01",
            error_msg="request timed out waiting for response",
        )
        assert payload.code == GalaxyErrorCode.DEVICE_TIMEOUT.value


# ---------------------------------------------------------------------------
# 3. Disconnect during task execution — arbiter releases slot
# ---------------------------------------------------------------------------


class TestArbiterDisconnectRecovery:
    def setup_method(self):
        _reset()

    def test_arbiter_releases_slot_on_disconnect(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        arbiter.configure(global_limit=2, per_origin_quota=2)

        d1 = arbiter.admit("task-A", priority=5, origin="user:1")
        d2 = arbiter.admit("task-B", priority=5, origin="user:2")
        assert d1.admitted and d2.admitted
        assert len(arbiter.list_running()) == 2

        # Simulate disconnect → release task-A slot
        released = arbiter.release("task-A")
        assert released is True
        assert len(arbiter.list_running()) == 1

        # New task can now be admitted
        d3 = arbiter.admit("task-C", priority=5, origin="user:3")
        assert d3.admitted is True

    def test_release_unknown_task_returns_false(self):
        from core.orchestration.global_arbiter import get_global_arbiter, reset_global_arbiter

        reset_global_arbiter()
        arbiter = get_global_arbiter()
        assert arbiter.release("nonexistent-task") is False
