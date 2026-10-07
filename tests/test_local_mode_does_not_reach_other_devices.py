"""本地模式只用本机：往一台别的设备下发命令就是跨设备，不放行。

此前网关只在两处查跨设备开关：命令分析出「要跨设备」、以及多设备协同分发。显式指定**一台**目标设备的
单设备下发（``DeviceRouter.dispatch_task``：``/devices/parallel`` 把命令拆成每台设备一个子任务、
``CommandRouter`` 的 ``android_device`` 路径、安卓桥的 ``assign_task`` 都走它）不查 ——
真机实测：本地模式下 ``/devices/parallel`` 照样把命令送到了已连上的两台设备并执行。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from galaxy_gateway.cross_device_switch import ERROR_CODE_CROSS_DEVICE_DISABLED
from galaxy_gateway.device_router import DeviceRouter


def _device():
    return SimpleNamespace(device_id="laptop-1", websocket=None)


def _task():
    return {"task_id": "t1", "trace_id": "tr1", "command": "screenshot", "payload": {}}


@pytest.mark.asyncio
async def test_a_single_device_dispatch_is_refused_in_local_mode(monkeypatch):
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
    sent = AsyncMock(return_value={"success": True, "result": "sent"})
    with patch("core.aip_transport.get_aip_transport", return_value=SimpleNamespace(send=sent)):
        out = await DeviceRouter().dispatch_task(_task(), _device())
    assert out["success"] is False and out["error"] == ERROR_CODE_CROSS_DEVICE_DISABLED
    assert out["trace_id"] == "tr1"
    sent.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "env",
    [{"GALAXY_CROSS_DEVICE_ENABLED": "true"}, {"GALAXY_SYSTEM_MODE": "desktop-cross-device"}],
)
async def test_a_single_device_dispatch_goes_through_in_cross_device_mode(monkeypatch, env):
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sent = AsyncMock(return_value={"success": True, "result": "sent"})
    with patch("core.aip_transport.get_aip_transport", return_value=SimpleNamespace(send=sent)):
        out = await DeviceRouter().dispatch_task(_task(), _device())
    assert out["success"] is True
    sent.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_button_flips_it_live_without_a_restart(monkeypatch):
    """网关的开关随时读：按钮一翻，下一条命令就放行（模式的其余部分要重启，网关路由不用）。"""
    monkeypatch.delenv("GALAXY_CROSS_DEVICE_ENABLED", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_MODE", raising=False)
    sent = AsyncMock(return_value={"success": True, "result": "sent"})
    router = DeviceRouter()
    with patch("core.aip_transport.get_aip_transport", return_value=SimpleNamespace(send=sent)):
        assert (await router.dispatch_task(_task(), _device()))["success"] is False
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
        assert (await router.dispatch_task(_task(), _device()))["success"] is True
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "false")
        assert (await router.dispatch_task(_task(), _device()))["success"] is False
