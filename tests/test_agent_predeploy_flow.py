"""
tests/test_agent_predeploy_flow.py
===================================
Integration tests for the enforced two-step remote execution flow.

Verifies:
  1.  For physical device types, dispatch_agent_remote triggers agent_deploy
      **before** agent_execute.
  2.  When the WebSocket send for deploy succeeds, agent_execute is called.
  3.  When the device is offline (not in active_devices), deploy fails
      immediately and agent_execute is never called.
  4.  When the WebSocket send for deploy returns False, deploy fails
      immediately and agent_execute is never called.
  5.  For non-physical device types (cloud, browser), dispatch_agent_remote
      skips the deploy step and routes agent_execute directly.
  6.  get_device_type helper on UnifiedDeviceManager returns correct values.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.device_policy import requires_agent_deploy  # noqa: E402
from core.unified.device_manager import UnifiedDeviceManager  # noqa: E402
from core.unified.models import UnifiedDevice, UnifiedDeviceType  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_device(device_id: str, device_type: str) -> UnifiedDevice:
    return UnifiedDevice(
        device_id=device_id,
        device_name=device_id,
        device_type=UnifiedDeviceType(device_type),
    )


def _create_test_ids():
    """Generate fresh UUIDs for device_id, agent_id, trace_id, task_id, session_id."""
    return (
        str(uuid.uuid4()),   # device_id
        str(uuid.uuid4()),   # agent_id
        str(uuid.uuid4()),   # trace_id
        str(uuid.uuid4()),   # task_id
        str(uuid.uuid4()),   # session_id
    )


# ---------------------------------------------------------------------------
# UnifiedDeviceManager.get_device_type tests
# ---------------------------------------------------------------------------

class TestGetDeviceType:
    def setup_method(self):
        # Reset singleton state between tests
        UnifiedDeviceManager._instance = None

    def test_returns_device_type_string_for_known_device(self):
        mgr = UnifiedDeviceManager()
        device = _make_device("dev-android-1", "android")
        mgr.register_device(device)
        assert mgr.get_device_type("dev-android-1") == "android"

    def test_returns_none_for_unknown_device(self):
        mgr = UnifiedDeviceManager()
        assert mgr.get_device_type("nonexistent-device") is None

    @pytest.mark.parametrize("dt", ["android", "ios", "windows", "macos", "linux"])
    def test_returns_lowercase_string(self, dt: str):
        mgr = UnifiedDeviceManager()
        device = _make_device(f"dev-{dt}", dt)
        mgr.register_device(device)
        result = mgr.get_device_type(f"dev-{dt}")
        assert result is not None
        assert result.lower() == dt


# ---------------------------------------------------------------------------
# dispatch_agent_remote — physical device two-step flow
# ---------------------------------------------------------------------------

class TestDispatchAgentRemotePhysicalDevice:
    """Two-step deploy→execute must fire for all physical device types."""

    def _build_router(self):
        """Import CommandRouter lazily to avoid heavy dep loading at module level."""
        from core.command_router import CommandRouter
        router = CommandRouter.__new__(CommandRouter)
        # Minimal attribute initialisation to avoid __init__ side-effects
        router._stats = {
            "total_routed": 0, "total_failed": 0, "total_retried": 0,
            "total_cb_rejected": 0, "total_queued": 0,
        }
        router._queue_depth = 0
        router._cb = MagicMock(is_open=MagicMock(return_value=True))
        return router

    @pytest.mark.asyncio
    @pytest.mark.parametrize("device_type", [
        "android", "ios", "windows", "macos", "linux", "iot", "robot", "drone",
    ])
    async def test_deploy_sent_before_execute_for_physical_device(self, device_type: str):
        """agent_deploy must be sent and agent_execute must follow on success."""
        # Reset UDM singleton
        UnifiedDeviceManager._instance = None
        mgr = UnifiedDeviceManager()

        device_id, agent_id, trace_id, task_id, session_id = _create_test_ids()
        device = _make_device(device_id, device_type)
        mgr.register_device(device)

        router = self._build_router()
        call_order: List[str] = []

        async def fake_send_to_device(did: str, msg: Dict[str, Any]) -> bool:
            call_order.append(msg.get("type", "unknown"))
            return True

        fake_route_result = {
            "success": True,
            "result": "dispatched",
            "latency_ms": 5.0,
            "via": "command_router",
        }

        # Patch connection_manager and route_command
        fake_cm = MagicMock()
        fake_cm.active_devices = {device_id}
        fake_cm.send_to_device = AsyncMock(side_effect=fake_send_to_device)

        with patch("core.command_router.CommandRouter.route_command", new=AsyncMock(return_value=fake_route_result)) as mock_route, \
             patch("core.routes._shared.connection_manager", fake_cm):
            result = await router.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template="executor",
                task="open settings",
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
            )

        # agent_deploy must come first
        assert "agent_deploy" in call_order, (
            f"agent_deploy not sent for device_type={device_type}"
        )
        assert call_order[0] == "agent_deploy", (
            f"agent_deploy was not the first message sent (order={call_order})"
        )
        # agent_execute must follow
        mock_route.assert_called_once()
        call_kwargs = mock_route.call_args
        actual_command = call_kwargs.kwargs.get("command") or (
            call_kwargs.args[1] if call_kwargs.args and len(call_kwargs.args) > 1 else None
        )
        assert actual_command == "agent_execute", (
            f"route_command was not called with command='agent_execute' (got {actual_command!r})"
        )

        assert result["success"] is True
        assert result["agent_id"] == agent_id
        assert result["trace_id"] == trace_id
        assert result["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_deploy_fails_when_device_offline(self):
        """If the device is not in active_devices, return error immediately."""
        UnifiedDeviceManager._instance = None
        mgr = UnifiedDeviceManager()

        device_id, agent_id, trace_id, task_id, session_id = _create_test_ids()
        device = _make_device(device_id, "android")
        mgr.register_device(device)

        router = self._build_router()

        fake_cm = MagicMock()
        fake_cm.active_devices = {}  # device offline
        fake_cm.send_to_device = AsyncMock(return_value=True)

        with patch("core.command_router.CommandRouter.route_command", new=AsyncMock()) as mock_route, \
             patch("core.routes._shared.connection_manager", fake_cm):
            result = await router.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template="executor",
                task="take screenshot",
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
            )

        assert result["success"] is False
        assert "offline" in result.get("error_message", "").lower() or \
               "offline" in result.get("error_code", "").lower()
        # agent_execute must NOT have been called
        mock_route.assert_not_called()

    @pytest.mark.asyncio
    async def test_deploy_fails_when_send_returns_false(self):
        """If send_to_device returns False, return error without calling agent_execute."""
        UnifiedDeviceManager._instance = None
        mgr = UnifiedDeviceManager()

        device_id, agent_id, trace_id, task_id, session_id = _create_test_ids()
        device = _make_device(device_id, "windows")
        mgr.register_device(device)

        router = self._build_router()

        fake_cm = MagicMock()
        fake_cm.active_devices = {device_id}
        fake_cm.send_to_device = AsyncMock(return_value=False)  # send fails

        with patch("core.command_router.CommandRouter.route_command", new=AsyncMock()) as mock_route, \
             patch("core.routes._shared.connection_manager", fake_cm):
            result = await router.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template="executor",
                task="open notepad",
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
            )

        assert result["success"] is False
        assert "deploy" in result.get("error_code", "").lower() or \
               "deploy" in result.get("error_message", "").lower()
        mock_route.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_agent_remote — non-physical device: direct route (no deploy)
# ---------------------------------------------------------------------------

class TestDispatchAgentRemoteNonPhysical:
    def _build_router(self):
        from core.command_router import CommandRouter
        router = CommandRouter.__new__(CommandRouter)
        router._stats = {
            "total_routed": 0, "total_failed": 0, "total_retried": 0,
            "total_cb_rejected": 0, "total_queued": 0,
        }
        router._queue_depth = 0
        router._cb = MagicMock(is_open=MagicMock(return_value=True))
        return router

    @pytest.mark.asyncio
    @pytest.mark.parametrize("device_type", ["cloud", "browser", "unknown"])
    async def test_no_deploy_for_non_physical_device(self, device_type: str):
        """Non-physical devices must go directly to agent_execute."""
        UnifiedDeviceManager._instance = None
        mgr = UnifiedDeviceManager()

        device_id, agent_id, trace_id, task_id, session_id = _create_test_ids()
        # Use UNKNOWN for types not in UnifiedDeviceType enum
        try:
            udt = UnifiedDeviceType(device_type)
        except ValueError:
            udt = UnifiedDeviceType.UNKNOWN
        device = UnifiedDevice(
            device_id=device_id,
            device_name=device_id,
            device_type=udt,
        )
        mgr.register_device(device)

        router = self._build_router()

        fake_route_result = {
            "success": True,
            "result": "dispatched",
            "latency_ms": 3.0,
            "via": "command_router",
        }

        fake_cm = MagicMock()
        fake_cm.active_devices = {device_id}
        fake_cm.send_to_device = AsyncMock(return_value=True)

        with patch("core.command_router.CommandRouter.route_command", new=AsyncMock(return_value=fake_route_result)) as mock_route, \
             patch("core.routes._shared.connection_manager", fake_cm):
            result = await router.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template="executor",
                task="query data",
                session_id=session_id,
                trace_id=trace_id,
                task_id=task_id,
            )

        # deploy must NOT have been sent via connection_manager.send_to_device
        fake_cm.send_to_device.assert_not_called()
        # route_command must have been called with agent_execute
        mock_route.assert_called_once()
        result_kw = mock_route.call_args.kwargs
        assert result_kw.get("command") == "agent_execute"
        assert result["success"] is True
