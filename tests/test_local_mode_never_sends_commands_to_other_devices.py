"""本地模式只用本机：每一个「把命令送到另一台设备」的入口都拒绝，说法一致。

真机实测（真服务器 + 两台真配对、真 WebSocket 的设备客户端）发现：本地模式下 ``/devices/parallel`` 把命令送到了
两台设备并执行 —— 命令路由的设备执行桥（``_command_node_executor``）直接 ``send_to_device``，网关的开关一处都没查。
入口一共这几处，各自有用例：

1. ``core.system_mode.cross_device_refusal``：统一的拒绝（错误码与网关同为 ``cross_device_disabled``）；
2. ``POST /api/v1/devices/{id}/command``（单设备命令 REST）；
3. 命令路由的设备执行桥（``/devices/parallel`` 拆出的每台设备、``/devices/cross-device`` 都落到这里）；
4. 智能体的 ``devices__invoke``（讲 AIP 的设备；桥接的智能家居 / 驱动节点不在此列）；
5. ``DeviceRouter.dispatch_task``（见 ``test_local_mode_does_not_reach_other_devices.py``）。
"""

from __future__ import annotations

import asyncio

import pytest

from core.system_mode import cross_device_refusal


@pytest.fixture(autouse=True)
def _clean_mode(monkeypatch):
    for k in ("GALAXY_CROSS_DEVICE_ENABLED", "GALAXY_SYSTEM_MODE"):
        monkeypatch.delenv(k, raising=False)


def test_the_refusal_is_one_shape_with_the_gateways_error_code(monkeypatch):
    from galaxy_gateway.cross_device_switch import ERROR_CODE_CROSS_DEVICE_DISABLED

    out = cross_device_refusal("tr-1")
    assert out["success"] is False and out["error"] == ERROR_CODE_CROSS_DEVICE_DISABLED == "cross_device_disabled"
    assert out["trace_id"] == "tr-1"
    assert "本地模式" in out["message"] and "跨设备" in out["how_to_fix"]
    assert "devices__request_cross_device" in out["how_to_fix"], "告诉模型下一步怎么办"
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    assert cross_device_refusal() is None


# ── 2. 单设备命令 REST ──────────────────────────────────────────────────────────


@pytest.fixture
def devices_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    import core.routes.devices as devices_mod

    sent: list = []

    async def send_to_device(device_id, message):
        sent.append((device_id, message))
        return True

    monkeypatch.setattr(devices_mod, "_is_device_registered_canonical", lambda _id: True)
    monkeypatch.setattr(devices_mod.connection_manager, "send_to_device", send_to_device)
    app = FastAPI()
    app.include_router(devices_mod.create_router() if hasattr(devices_mod, "create_router") else devices_mod.router)
    return TestClient(app), sent


def test_the_single_device_command_route_refuses_in_local_mode(devices_client):
    client, sent = devices_client
    r = client.post("/api/v1/devices/laptop-1/command", json={"command": "screenshot", "params": {}})
    assert r.status_code == 403 and r.json()["error"] == "cross_device_disabled"
    assert sent == [], "一条消息都不能发出去"


def test_the_single_device_command_route_sends_in_cross_device_mode(devices_client, monkeypatch):
    client, sent = devices_client
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    r = client.post("/api/v1/devices/laptop-1/command", json={"command": "screenshot", "params": {}})
    assert r.status_code == 200 and r.json()["success"] is True
    assert sent and sent[0][0] == "laptop-1"


# ── 3. 命令路由的设备执行桥 ─────────────────────────────────────────────────────


@pytest.fixture
def node_executor(monkeypatch):
    """真实的 ``_command_node_executor``（``create_router`` 里注册给命令路由的那一个），设备在线、记下发出的消息。"""
    import core.routes.command as command_mod
    from core.command_router import get_command_router

    sent: list = []

    async def send_to_device(device_id, message):
        sent.append((device_id, message))
        return True

    monkeypatch.setattr(command_mod.connection_manager, "is_online", lambda _id: True)
    monkeypatch.setattr(command_mod.connection_manager, "send_to_device", send_to_device)
    command_mod.create_router()
    return get_command_router()._executor, sent


def test_the_command_routers_device_bridge_refuses_in_local_mode(node_executor):
    executor, sent = node_executor
    out = asyncio.run(executor("laptop-1", "screenshot", {}))
    assert out["success"] is False and out["error"] == "cross_device_disabled"
    assert sent == []


def test_the_command_routers_device_bridge_sends_in_cross_device_mode(node_executor, monkeypatch):
    executor, sent = node_executor
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
    out = asyncio.run(executor("laptop-1", "screenshot", {}))
    assert out == {"sent_to_device": "laptop-1", "success": True}
    assert sent and sent[0][1]["command"] == "screenshot"


# ── 4. 智能体 devices__invoke ───────────────────────────────────────────────────


@pytest.fixture
def phone(tmp_path, monkeypatch):
    from core.device_onboarding.service import reset_onboarding_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import get_unified_device_manager, reset_unified_device_manager

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "ob"))
    for r in (reset_unified_device_manager, reset_unified_connection_manager, reset_onboarding_service):
        r()
    get_unified_device_manager().register_device_from_dict(
        "phone-1", {"device_type": "Android_Agent", "transport": "websocket"}
    )
    yield "phone-1"
    for r in (reset_unified_device_manager, reset_unified_connection_manager, reset_onboarding_service):
        r()


def _invoke(device_id, action="screenshot"):
    from core.device_onboarding.agent_tools import dispatch_devices_tool

    return asyncio.run(dispatch_devices_tool("invoke", {"device_id": device_id, "action": action}, session_id="s1"))


def test_the_agent_cannot_operate_another_device_in_local_mode_and_is_told_what_to_do(phone):
    out = _invoke(phone)
    assert out["success"] is False and out["error"] == "cross_device_disabled"
    assert "devices__request_cross_device" in out["how_to_fix"]


def test_in_cross_device_mode_the_agent_gets_past_the_mode_gate(phone, monkeypatch):
    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    out = _invoke(phone)
    assert out.get("error") != "cross_device_disabled"  # 设备没连着,所以仍失败 —— 但不再是模式拦的


def test_a_device_that_is_not_there_is_still_reported_as_such_in_local_mode(phone):
    out = _invoke("nobody")
    assert out["success"] is False and "没有这个成员" in out["error"]


def test_the_refusal_is_wired_into_the_native_branch_only():
    """桥接的智能家居与驱动节点不被模式拦住：它们各有自己的开关。"""
    import inspect

    from core.device_onboarding import agent_tools

    src = inspect.getsource(agent_tools._invoke)
    assert src.index("cross_device_refusal") < src.index("get_canonical_dispatcher().dispatch"), "派发前先拒"
    assert src.count("cross_device_refusal") == 2  # 导入 + 调用,只在 AIP 设备那一支
