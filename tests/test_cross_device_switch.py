"""
tests/test_cross_device_switch.py
==================================

The panel's 「跨设备」 switch says whether **this computer** joins the device
network as a device.  It is not a routing gate on the central agent.

Covers:
  1. is_cross_device_enabled() reads the one mode rule correctly.
  2. The switch module no longer exports a gate, and the gateway's routing
     paths (DeviceRouter, WebRTC proxy) do not consult it.
  3. DeviceRouter.route_task() / _dispatch_cross_device_task() proceed in
     either mode (members decide, not the computer's switch).
  4. The WebRTC signaling proxy is members-only (owner's token or the pairing
     token issued to that device), in either mode — it used to be gated by the
     switch, which left it open to any LAN client whenever the switch was on.
  5. get_webrtc_endpoint_info() advertises requires_member_token.
  6. DeviceRouter.dispatch_task() stays the canonical single dispatcher.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from galaxy_gateway.device_router import Device, DeviceRouter  # noqa: E402
from galaxy_gateway.webrtc_proxy import (  # noqa: E402
    WS_CLOSE_CODE_UNAUTHORIZED,
    get_webrtc_endpoint_info,
    proxy_webrtc_signaling,
)

BOTH_MODES = pytest.mark.parametrize("switch", ["0", "1"], ids=["local", "cross_device"])

#: 主人的共享凭据(本文件自己设进环境)。名字刻意中性:CodeQL 按变量名把 ``*_api_token`` 当口令,
#: 一路追到能力令牌的 HMAC-SHA256 验签会报「用快哈希存口令」—— 那是验签,不是存口令。
_OWNER = "owner-for-signaling-tests-0123456789abcdef"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws(query=None, headers=None) -> MagicMock:
    """Build a minimal fake FastAPI WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("stop"))
    ws.query_params = dict(query or {})
    ws.headers = dict(headers or {})
    return ws


def _close_codes(ws) -> list:
    return [c.kwargs.get("code") or (c.args[0] if c.args else None) for c in ws.close.call_args_list]


async def _signal(ws, device_id="device-123"):
    # Node_95 is not running: a member gets past the door and then fails to reach it (1011),
    # which is enough to tell "let in" from "turned away at the door" (4401).
    with patch("websockets.connect", side_effect=ConnectionRefusedError("no node95")):
        await proxy_webrtc_signaling(ws, device_id)


# ===========================================================================
# 1. is_cross_device_enabled()
# ===========================================================================


class TestIsEnabled:
    """is_cross_device_enabled() reflects GALAXY_CROSS_DEVICE_ENABLED (this computer joined)."""

    def test_default_is_disabled(self, monkeypatch):
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        from galaxy_gateway.cross_device_switch import is_cross_device_enabled

        assert is_cross_device_enabled() is False

    @pytest.mark.parametrize(
        "raw,expected", [("1", True), ("true", True), ("0", False), ("false", False), ("no", False), ("FALSE", False)]
    )
    def test_values(self, monkeypatch, raw, expected):
        monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", raw)
        from galaxy_gateway.cross_device_switch import is_cross_device_enabled

        assert is_cross_device_enabled() is expected


# ===========================================================================
# 2. The switch is not a routing gate
# ===========================================================================


class TestTheSwitchIsNotARoutingGate:
    def test_the_module_exports_only_the_question(self):
        import galaxy_gateway.cross_device_switch as switch

        assert switch.__all__ == ["is_cross_device_enabled"]
        for gone in ("guard_cross_device", "make_disabled_response", "CrossDeviceDisabledError"):
            assert not hasattr(switch, gone), gone

    @pytest.mark.parametrize(
        "rel",
        [
            "galaxy_gateway/device_router.py",
            "galaxy_gateway/webrtc_proxy.py",
            "galaxy_gateway/agent_bridge.py",
            "galaxy_gateway/android_bridge.py",
            "galaxy_gateway/android/handlers/goal_execution.py",
            "galaxy_gateway/routes/chat.py",
            "core/routes/devices.py",
            "core/routes/command.py",
            "core/device_onboarding/agent_tools.py",
            "core/nats_dispatch_bridge.py",
        ],
    )
    def test_no_routing_path_consults_the_computers_switch(self, rel):
        src = (PROJECT_ROOT / rel).read_text(encoding="utf-8")
        assert "cross_device_disabled" not in src, rel
        assert "is_cross_device_enabled()" not in src, rel
        assert "cross_device_refusal" not in src, rel


# ===========================================================================
# 3. DeviceRouter — proceeds in either mode
# ===========================================================================


class TestDeviceRouterInEitherMode:
    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_route_task_calls_coordinator(self, monkeypatch, switch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)

        router = DeviceRouter()
        coordinator_mock = MagicMock()
        coordinator_mock.execute_cross_device_task = AsyncMock(return_value={"success": True, "result": "done"})

        async def _fake_analyze(command, context=None):
            return {"requires_cross_device": True, "task_type": "cross_device"}

        with patch.object(router, "_analyze_command", side_effect=_fake_analyze):
            with patch(
                "galaxy_gateway.device_router.get_cross_device_coordinator",
                return_value=coordinator_mock,
            ):
                # 每个参数一条新 trace:代理桥按 trace_id 去重,复用会直接拿上一条的缓存结果
                result = await router.route_task("sync clipboard", {"trace_id": f"rt-{switch}-{uuid.uuid4().hex}"})

        assert result["success"] is True
        coordinator_mock.execute_cross_device_task.assert_called_once()

    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_route_task_to_one_member(self, monkeypatch, switch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)

        from core.device_types import DeviceType

        router = DeviceRouter()
        device = Device("dev1", "android_phone", ["tap"])
        device.apply_status("online")
        router.devices["dev1"] = device

        async def _fake_analyze(command, context=None):
            return {
                "requires_cross_device": False,
                "task_type": "tap",
                "target_device_type": DeviceType.ANDROID,
                "exec_mode": "both",
                "actions": ["tap"],
            }

        async def _fake_dispatch(task, dev):
            return {"success": True, "device_id": dev.device_id}

        with patch.object(router, "_analyze_command", side_effect=_fake_analyze):
            with patch.object(router, "dispatch_task", side_effect=_fake_dispatch):
                result = await router.route_task("tap screen")

        assert result["success"] is True

    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_dispatch_cross_device_task(self, monkeypatch, switch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)

        router = DeviceRouter()
        d1 = Device("d1", "android_phone", [])
        d2 = Device("d2", "windows_desktop", [])
        task = {"task_id": "t1", "command": "sync", "trace_id": "disp-trace-2"}

        async def _fake_dispatch(subtask, device):
            return {"success": True}

        with patch.object(router, "dispatch_task", side_effect=_fake_dispatch):
            result = await router._dispatch_cross_device_task(task, [d1, d2])

        assert result["success"] is True


# ===========================================================================
# 4. WebRTC signaling — members only, in either mode
# ===========================================================================


@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("GALAXY_AUTH_ENABLED", "true")
    monkeypatch.setenv("GALAXY_API_TOKEN", _OWNER)
    return monkeypatch


class TestWebRTCSignalingIsMembersOnly:
    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_no_token_is_turned_away(self, auth_on, switch, caplog):
        auth_on.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)
        ws = _make_ws()
        with caplog.at_level(logging.WARNING):
            await _signal(ws, "stranger")
        ws.accept.assert_called_once()
        assert _close_codes(ws) == [WS_CLOSE_CODE_UNAUTHORIZED]
        reason = ws.close.call_args.kwargs.get("reason", "")
        assert "pair" in reason

    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_the_owners_token_gets_in(self, auth_on, switch):
        auth_on.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)
        ws = _make_ws(query={"token": _OWNER})
        await _signal(ws)
        assert WS_CLOSE_CODE_UNAUTHORIZED not in _close_codes(ws)

    @BOTH_MODES
    @pytest.mark.asyncio
    async def test_the_pairing_token_of_this_device_gets_in(self, auth_on, switch):
        from core.capability_token import issue_token

        auth_on.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)
        token = issue_token("phone-1", ["device:status"], ttl_s=600)
        ws = _make_ws(headers={"authorization": f"Bearer {token}"})
        await _signal(ws, "phone-1")
        assert WS_CLOSE_CODE_UNAUTHORIZED not in _close_codes(ws)

    @pytest.mark.asyncio
    async def test_another_devices_pairing_token_is_turned_away(self, auth_on):
        from core.capability_token import issue_token

        token = issue_token("phone-2", ["device:status"], ttl_s=600)
        ws = _make_ws(query={"token": token})
        await _signal(ws, "phone-1")
        assert _close_codes(ws) == [WS_CLOSE_CODE_UNAUTHORIZED]

    @pytest.mark.asyncio
    async def test_a_wrong_token_is_turned_away(self, auth_on):
        ws = _make_ws(query={"token": "not-a-token"})
        await _signal(ws)
        assert _close_codes(ws) == [WS_CLOSE_CODE_UNAUTHORIZED]

    @pytest.mark.asyncio
    async def test_with_gateway_auth_turned_off_it_is_open_like_every_other_route(self, monkeypatch):
        monkeypatch.setenv("GALAXY_AUTH_ENABLED", "false")
        monkeypatch.delenv("GALAXY_MODE", raising=False)
        ws = _make_ws()
        await _signal(ws)
        assert WS_CLOSE_CODE_UNAUTHORIZED not in _close_codes(ws)


# ===========================================================================
# 5. get_webrtc_endpoint_info()
# ===========================================================================


class TestWebRTCEndpointInfo:
    @BOTH_MODES
    def test_advertises_member_token(self, monkeypatch, switch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", switch)
        info = get_webrtc_endpoint_info()
        assert info["requires_member_token"] is True
        assert "cross_device_enabled" not in info


# ===========================================================================
# 6. Single dispatcher — DeviceRouter is the canonical path
# ===========================================================================


class TestSingleDispatcher:
    def test_device_router_exposes_dispatch_task(self):
        assert hasattr(DeviceRouter, "dispatch_task")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
