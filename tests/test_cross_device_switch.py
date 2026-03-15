"""
tests/test_cross_device_switch.py
==================================

Round 4 — Cross-Device Switch Hard Constraint Tests.

Covers:
  1. Feature-flag module — is_cross_device_enabled() reads env var correctly.
  2. guard_cross_device() raises CrossDeviceDisabledError when OFF; no-ops when ON.
  3. make_disabled_response() returns the canonical error dict when OFF.
  4. DeviceRouter.route_task() is blocked when switch is OFF and task requires
     cross-device coordination (coordinator must NOT be called).
  5. DeviceRouter._dispatch_cross_device_task() is blocked when switch is OFF.
  6. WebRTC proxy proxy_webrtc_signaling() closes WS with code 4001 when OFF.
  7. get_webrtc_endpoint_info() includes cross_device_enabled field.
  8. ON (default): route_task() passes through to coordinator; dispatcher works.
  9. ON: proxy_webrtc_signaling() does NOT close prematurely.
 10. Log entries include trace_id when switch is OFF.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from galaxy_gateway.cross_device_switch import (  # noqa: E402
    CrossDeviceDisabledError,
    ERROR_CODE_CROSS_DEVICE_DISABLED,
    ERROR_MSG_CROSS_DEVICE_DISABLED,
    HTTP_STATUS_CROSS_DEVICE_DISABLED,
    WS_CLOSE_CODE_CROSS_DEVICE_DISABLED,
    guard_cross_device,
    is_cross_device_enabled,
    make_disabled_response,
)
from galaxy_gateway.device_router import Device, DeviceRouter  # noqa: E402
from galaxy_gateway.webrtc_proxy import (  # noqa: E402
    get_webrtc_endpoint_info,
    proxy_webrtc_signaling,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws() -> MagicMock:
    """Build a minimal fake FastAPI WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.close = AsyncMock()
    ws.receive_text = AsyncMock(side_effect=Exception("stop"))
    return ws


# ===========================================================================
# 1. Feature-flag module — is_cross_device_enabled()
# ===========================================================================

class TestIsEnabled:
    """is_cross_device_enabled() reflects GALAXY_CROSS_DEVICE_ENABLED."""

    def test_default_is_enabled(self, monkeypatch):
        monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
        assert is_cross_device_enabled() is True

    def test_explicit_1_is_enabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        assert is_cross_device_enabled() is True

    def test_true_string_is_enabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
        assert is_cross_device_enabled() is True

    def test_0_is_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        assert is_cross_device_enabled() is False

    def test_false_string_is_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "false")
        assert is_cross_device_enabled() is False

    def test_no_string_is_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "no")
        assert is_cross_device_enabled() is False

    def test_mixed_case_false(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "FALSE")
        assert is_cross_device_enabled() is False


# ===========================================================================
# 2. guard_cross_device()
# ===========================================================================

class TestGuardCrossDevice:
    """guard_cross_device() raises when OFF and is silent when ON."""

    def test_raises_when_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        with pytest.raises(CrossDeviceDisabledError):
            guard_cross_device()

    def test_no_raise_when_on(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        guard_cross_device()  # must not raise

    def test_error_carries_trace_id_when_provided(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        tid = str(uuid.uuid4())
        with pytest.raises(CrossDeviceDisabledError) as exc_info:
            guard_cross_device(trace_id=tid)
        assert exc_info.value.trace_id == tid

    def test_error_generates_trace_id_when_absent(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        with pytest.raises(CrossDeviceDisabledError) as exc_info:
            guard_cross_device()
        assert exc_info.value.trace_id  # non-empty

    def test_raises_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        import logging
        with caplog.at_level(logging.WARNING, logger="galaxy_gateway.cross_device_switch"):
            with pytest.raises(CrossDeviceDisabledError):
                guard_cross_device(trace_id="test-trace-123")
        assert "cross_device_blocked" in caplog.text
        assert "test-trace-123" in caplog.text
        assert ERROR_CODE_CROSS_DEVICE_DISABLED in caplog.text


# ===========================================================================
# 3. make_disabled_response()
# ===========================================================================

class TestMakeDisabledResponse:
    """make_disabled_response() returns canonical error dict."""

    def test_structure(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        resp = make_disabled_response()
        assert resp["success"] is False
        assert resp["error"] == ERROR_CODE_CROSS_DEVICE_DISABLED
        assert "message" in resp
        assert "trace_id" in resp

    def test_propagates_trace_id(self):
        tid = "my-trace-id"
        resp = make_disabled_response(trace_id=tid)
        assert resp["trace_id"] == tid

    def test_generates_trace_id_when_absent(self):
        resp = make_disabled_response()
        assert resp["trace_id"]  # non-empty

    def test_logs_warning(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="galaxy_gateway.cross_device_switch"):
            make_disabled_response(trace_id="warn-trace")
        assert "cross_device_blocked" in caplog.text
        assert "warn-trace" in caplog.text


# ===========================================================================
# 4. DeviceRouter.route_task() — switch OFF blocks cross-device tasks
# ===========================================================================

class TestDeviceRouterSwitchOff:
    """When cross-device switch is OFF, route_task() must short-circuit."""

    @pytest.mark.asyncio
    async def test_route_task_cross_device_blocked_when_off(self, monkeypatch):
        """Cross-device analysis result is rejected; coordinator never called."""
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        router = DeviceRouter()
        coordinator_mock = AsyncMock()
        coordinator_mock.execute_cross_device_task = AsyncMock(
            return_value={"success": True, "result": "should not be called"}
        )

        # Patch analysis to always require cross-device
        async def _fake_analyze(command, context=None):
            return {"requires_cross_device": True, "task_type": "cross_device"}

        with patch.object(router, "_analyze_command", side_effect=_fake_analyze):
            with patch(
                "galaxy_gateway.device_router.get_cross_device_coordinator",
                return_value=coordinator_mock,
            ):
                result = await router.route_task("sync clipboard", {"trace_id": "rt-trace-1"})

        assert result["success"] is False
        assert result["error"] == ERROR_CODE_CROSS_DEVICE_DISABLED
        assert result["trace_id"] == "rt-trace-1"
        coordinator_mock.execute_cross_device_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_route_task_local_not_blocked_when_off(self, monkeypatch):
        """Local (single-device) tasks are NOT blocked by the cross-device switch."""
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        from core.device_types import DeviceType

        router = DeviceRouter()
        device = Device("dev1", "android_phone", ["tap"])
        device.status = "online"
        router.devices["dev1"] = device

        # Patch analysis to return a local (non-cross-device) task
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


# ===========================================================================
# 5. DeviceRouter._dispatch_cross_device_task() — switch OFF guard
# ===========================================================================

class TestDispatchCrossDeviceTaskGuard:
    """_dispatch_cross_device_task() must short-circuit when switch is OFF."""

    @pytest.mark.asyncio
    async def test_dispatch_cross_device_blocked_when_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        router = DeviceRouter()
        d1 = Device("d1", "android_phone", [])
        d2 = Device("d2", "windows_desktop", [])
        task = {"task_id": "t1", "command": "sync", "trace_id": "disp-trace-1"}

        result = await router._dispatch_cross_device_task(task, [d1, d2])

        assert result["success"] is False
        assert result["error"] == ERROR_CODE_CROSS_DEVICE_DISABLED
        assert result["trace_id"] == "disp-trace-1"

    @pytest.mark.asyncio
    async def test_dispatch_cross_device_allowed_when_on(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")

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
# 6. proxy_webrtc_signaling() — WS closed with 4001 when switch is OFF
# ===========================================================================

class TestProxyWebRTCSignalingSwitchOff:
    """proxy_webrtc_signaling() must close WS with 4001 when switch is OFF."""

    @pytest.mark.asyncio
    async def test_ws_closed_4001_when_off(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        ws = _make_ws()
        await proxy_webrtc_signaling(ws, "device-123")

        ws.accept.assert_called_once()
        ws.close.assert_called_once()
        call_kwargs = ws.close.call_args
        code = call_kwargs.kwargs.get("code") or call_kwargs.args[0]
        assert code == WS_CLOSE_CODE_CROSS_DEVICE_DISABLED

    @pytest.mark.asyncio
    async def test_ws_close_reason_mentions_disabled(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        ws = _make_ws()
        await proxy_webrtc_signaling(ws, "device-xyz")

        call_kwargs = ws.close.call_args
        reason = call_kwargs.kwargs.get("reason", "") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else ""
        )
        assert "disabled" in reason.lower()

    @pytest.mark.asyncio
    async def test_ws_blocked_logs_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")

        import logging

        ws = _make_ws()
        with caplog.at_level(logging.WARNING, logger="galaxy_gateway.webrtc_proxy"):
            await proxy_webrtc_signaling(ws, "log-device")

        assert "cross_device_blocked" in caplog.text
        assert "log-device" in caplog.text


# ===========================================================================
# 7. get_webrtc_endpoint_info() — includes cross_device_enabled flag
# ===========================================================================

class TestWebRTCEndpointInfo:
    """get_webrtc_endpoint_info() must expose the cross_device_enabled flag."""

    def test_includes_cross_device_enabled_true(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")
        info = get_webrtc_endpoint_info()
        assert "cross_device_enabled" in info
        assert info["cross_device_enabled"] is True

    def test_includes_cross_device_enabled_false(self, monkeypatch):
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "0")
        info = get_webrtc_endpoint_info()
        assert "cross_device_enabled" in info
        assert info["cross_device_enabled"] is False


# ===========================================================================
# 8 & 9. ON (regression pass-through) — route_task & WebRTC work normally
# ===========================================================================

class TestCrossDeviceSwitchOn:
    """When switch is ON, cross-device paths proceed normally (regression)."""

    @pytest.mark.asyncio
    async def test_route_task_calls_coordinator_when_on(self, monkeypatch):
        """Coordinator is invoked when switch is ON and task requires cross-device."""
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")

        router = DeviceRouter()
        coordinator_mock = MagicMock()
        coordinator_mock.execute_cross_device_task = AsyncMock(
            return_value={"success": True, "result": "done"}
        )

        async def _fake_analyze(command, context=None):
            return {"requires_cross_device": True, "task_type": "cross_device"}

        with patch.object(router, "_analyze_command", side_effect=_fake_analyze):
            with patch(
                "galaxy_gateway.device_router.get_cross_device_coordinator",
                return_value=coordinator_mock,
            ):
                result = await router.route_task("sync clipboard")

        assert result["success"] is True
        coordinator_mock.execute_cross_device_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_proxy_does_not_close_immediately_when_on(self, monkeypatch):
        """proxy_webrtc_signaling() does not early-close with 4001 when ON."""
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "1")

        ws = _make_ws()

        # Node_95 connection will fail but that's OK — we're only verifying
        # the switch does NOT trigger a 4001 close.
        with patch("websockets.connect", side_effect=ConnectionRefusedError("no node95")):
            await proxy_webrtc_signaling(ws, "device-on-test")

        # If close was called, it must NOT be with the cross-device-disabled code
        for call in ws.close.call_args_list:
            code = call.kwargs.get("code") or (call.args[0] if call.args else None)
            assert code != WS_CLOSE_CODE_CROSS_DEVICE_DISABLED, (
                "WS must not be closed with 4001 when cross-device is ON"
            )


# ===========================================================================
# 10. Single dispatcher — DeviceRouter is the canonical path
# ===========================================================================

class TestSingleDispatcher:
    """DeviceRouter.dispatch_task() is the canonical single dispatcher."""

    def test_device_router_exposes_dispatch_task(self):
        assert hasattr(DeviceRouter, "dispatch_task"), (
            "DeviceRouter must expose dispatch_task() as the canonical dispatcher"
        )

    def test_cross_device_switch_module_exists(self):
        """cross_device_switch.py must exist as the gate for all cross-device paths."""
        from galaxy_gateway import cross_device_switch  # noqa: F401

    def test_device_router_uses_switch_module(self):
        """device_router imports from cross_device_switch (not a local copy)."""
        import galaxy_gateway.device_router as dr_module
        # Verify the module-level names exist in device_router's namespace
        assert hasattr(dr_module, "is_cross_device_enabled"), (
            "device_router must import is_cross_device_enabled from cross_device_switch"
        )
        assert hasattr(dr_module, "make_disabled_response"), (
            "device_router must import make_disabled_response from cross_device_switch"
        )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
