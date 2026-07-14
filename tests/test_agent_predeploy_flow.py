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
# 门豁免夹具:本套件钉的是【预部署顺序契约】(物理设备先 deploy 后 execute),
# 不是设备级准入策略。后来加入的 PR-CAP-DEFAULT 能力推断 + V3 canonical 槽
# 权威会把假设备全部拦下(Transport is not alive)——按既定的 sanctioned
# bypass 模式(test_pr2_task_envelope_pipeline)豁免两道门,专门的门策略
# 契约由其各自的守卫套件钉。
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _bypass_dispatch_gates(monkeypatch):
    from core.canonical_dispatch_slot_authority import (
        CanonicalDispatchSlot,
        CanonicalDispatchSlotsResult,
        CanonicalDispatchSlotStatus,
    )

    def _approve_all(device_ids, execution_mode, **kwargs):
        slots = [
            CanonicalDispatchSlot(
                device_id=d,
                execution_mode=execution_mode,
                slot_approved=True,
                status=CanonicalDispatchSlotStatus.SLOT_APPROVED.value,
                reason="test override — predeploy-flow suite",
            )
            for d in device_ids
        ]
        return CanonicalDispatchSlotsResult(
            execution_mode=execution_mode,
            approved_slots=slots,
            blocked_slots=[],
            can_proceed=True,
            block_reason="",
        )

    monkeypatch.setattr(
        "core.canonical_dispatch_slot_authority.get_canonical_dispatch_slots",
        _approve_all,
    )
    monkeypatch.setattr(
        "core.capability_aware_routing_default.infer_dispatch_capabilities",
        lambda tool_name: [],
    )


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
        str(uuid.uuid4()),  # device_id
        str(uuid.uuid4()),  # agent_id
        str(uuid.uuid4()),  # trace_id
        str(uuid.uuid4()),  # task_id
        str(uuid.uuid4()),  # session_id
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
            "total_routed": 0,
            "total_failed": 0,
            "total_retried": 0,
            "total_cb_rejected": 0,
            "total_queued": 0,
        }
        router._queue_depth = 0
        router._cb = MagicMock(is_open=MagicMock(return_value=True))
        # __new__ 骨架随 CommandRouter 演进补齐:执行器兜底路径会查 _executor
        router._executor = None
        return router

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "device_type",
        [
            "android",
            "ios",
            "windows",
            "macos",
            "linux",
            "iot",
            "robot",
            "drone",
        ],
    )
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

        with (
            patch(
                "core.command_router.CommandRouter.route_envelope", new=AsyncMock(return_value=fake_route_result)
            ) as mock_route,
            patch("core.routes._shared.connection_manager", fake_cm),
        ):
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
        assert "agent_deploy" in call_order, f"agent_deploy not sent for device_type={device_type}"
        assert call_order[0] == "agent_deploy", f"agent_deploy was not the first message sent (order={call_order})"
        # agent_execute must follow — PR-7 起 execute 经 route_envelope
        # (统一基底根)承载,route_command 为有意绕开的 compat shim。
        mock_route.assert_called_once()
        _envelope = (
            mock_route.call_args.args[0] if mock_route.call_args.args else mock_route.call_args.kwargs.get("envelope")
        )
        assert (
            getattr(_envelope, "tool_name", None) == "agent_execute"
        ), f"route_envelope 未携带 agent_execute(got {getattr(_envelope, 'tool_name', None)!r})"
        assert getattr(_envelope, "targets", None) == [device_id]

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
        # 离线判定已收口到 connection_manager.is_online()(不再看 active_devices
        # 成员关系);MagicMock 默认返回真值会被当"在线",必须显式置 False。
        fake_cm.is_online = MagicMock(return_value=False)
        fake_cm.send_to_device = AsyncMock(return_value=True)

        with (
            patch("core.command_router.CommandRouter.route_envelope", new=AsyncMock()) as mock_route,
            patch("core.routes._shared.connection_manager", fake_cm),
        ):
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
        assert "offline" in result.get("error_message", "").lower() or "offline" in result.get("error_code", "").lower()
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

        with (
            patch("core.command_router.CommandRouter.route_envelope", new=AsyncMock()) as mock_route,
            patch("core.routes._shared.connection_manager", fake_cm),
        ):
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
        assert "deploy" in result.get("error_code", "").lower() or "deploy" in result.get("error_message", "").lower()
        mock_route.assert_not_called()


# ---------------------------------------------------------------------------
# dispatch_agent_remote — non-physical device: direct route (no deploy)
# ---------------------------------------------------------------------------


class TestDispatchAgentRemoteNonPhysical:
    def _build_router(self):
        from core.command_router import CommandRouter

        router = CommandRouter.__new__(CommandRouter)
        router._stats = {
            "total_routed": 0,
            "total_failed": 0,
            "total_retried": 0,
            "total_cb_rejected": 0,
            "total_queued": 0,
        }
        router._queue_depth = 0
        router._cb = MagicMock(is_open=MagicMock(return_value=True))
        # __new__ 骨架随 CommandRouter 演进补齐:执行器兜底路径会查 _executor
        router._executor = None
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

        with (
            patch(
                "core.command_router.CommandRouter.route_envelope", new=AsyncMock(return_value=fake_route_result)
            ) as mock_route,
            patch("core.routes._shared.connection_manager", fake_cm),
        ):
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
        # PR-7:直连 execute 同样经 route_envelope 承载
        mock_route.assert_called_once()
        _envelope = (
            mock_route.call_args.args[0] if mock_route.call_args.args else mock_route.call_args.kwargs.get("envelope")
        )
        assert getattr(_envelope, "tool_name", None) == "agent_execute"
        assert result["success"] is True
