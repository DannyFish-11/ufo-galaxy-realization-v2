"""中心智能体直接调手机的动作:``devices__invoke`` → 手机收到 ``command`` → 手机回 ``command_result``。

和手表同一个约定(``UnifiedConnectionManager.send_command_and_wait`` 按 ``command_id`` 认领)。全程走真实的
规范设备入口,帧形状与 ufo-galaxy-android 一致:登记沿用 ``test_phone_joins_through_its_bridge_agent``,
能力上报是 ``GalaxyWebSocketClient.sendCapabilityReport``,结果帧是 ``DeviceCommandFrames.resultFrame``。

此前手机报了一串动作却一个都接不了:``command`` 帧在手机上被当成一个空目标交给本地循环,也不回结果,
中心干等 30 秒报超时。手机那一侧的修正与测试在安卓仓(``PhoneCommandExecutorTest``、
``PhoneDirectCommandWireTest``);这里钉住中心这一侧:调得到、结果拿得回、拒绝原样带回、
不再报的动作从设备卡上撤掉。
"""

from __future__ import annotations

import time

from core.device_onboarding import agent_tools
from tests.test_phone_joins_through_its_bridge_agent import (  # noqa: F401 — 夹具与登记帧共用一份
    _phone_auth,
    _phone_register,
    _until,
    phone_id,
)
from tests.test_watch_reaches_the_central_agent import _eventually, gateway  # noqa: F401


def _now():
    return int(time.time() * 1000)


def _report(device_id, actions):
    # GalaxyWebSocketClient.sendCapabilityReport:只报手机真做得了的动作,每个带一句说明
    return {
        "type": "capability_report",
        "version": "3.0",
        "platform": "android",
        "device_id": device_id,
        "device_type": "Android_Agent",
        "timestamp": _now(),
        "supported_actions": list(actions),
        "action_descriptions": {a: f"手机动作 {a}" for a in actions},
        "capabilities": ["autonomous_goal_execution"],
        "metadata": {"goal_execution_enabled": True, "cross_device_enabled": True, "device_role": "phone"},
    }


def _result(device_id, command_id, success, data, error=None):
    # DeviceCommandFrames.resultFrame
    payload = {"success": success, **data}
    if not success:
        payload["error"] = error or "没做成"
    return {
        "version": "3.0",
        "type": "command_result",
        "device_id": device_id,
        "command_id": command_id,
        "correlation_id": command_id,
        "timestamp": _now(),
        "success": success,
        "payload": payload,
    }


def _join(ws, device_id, actions):
    ws.send_json(_phone_auth(device_id))
    assert _until(ws, lambda m: m.get("type") == "auth_ok"), "认证没回 auth_ok"
    ws.send_json(_phone_register(device_id))
    ack = _until(ws, lambda m: m.get("type") == "device_register_ack", timeout=30.0)
    assert ack.get("success") is True, ack
    ws.send_json(_report(device_id, actions))


def _card_actions(device_id):
    from core.device_onboarding.device_card import _actions

    return [a["name"] for a in _actions(device_id, [])]


def _invoke(gateway, device_id, action, params=None):
    async def call():
        return await agent_tools.dispatch_devices_tool(
            "invoke", {"device_id": device_id, "action": action, "params": params or {}}, session_id="sess-phone"
        )

    return gateway.portal.start_task_soon(call)


def _connect(gateway, device_id):
    return gateway.websocket_connect(f"/ws/device/{device_id}", headers={"X-Device-ID": device_id})


def test_the_agent_calls_the_phones_location_and_gets_the_coordinates(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        _join(ws, phone_id, ["location", "sensor_data"])
        assert _eventually(lambda: "location" in _card_actions(phone_id)), "设备卡上没有手机报的动作"
        pending = _invoke(gateway, phone_id, "location")
        cmd = _until(ws, lambda m: m.get("type") == "command", timeout=10.0)
        assert cmd.get("command") == "location" and cmd.get("command_id"), cmd
        ws.send_json(_result(phone_id, cmd["command_id"], True, {"latitude": 31.23, "longitude": 121.47, "age_s": 3}))
        out = pending.result(timeout=15)
    assert out["success"] is True, out
    assert out["result"]["latitude"] == 31.23 and out["result"]["longitude"] == 121.47


def test_a_refusal_on_the_phone_comes_back_with_its_reason(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        _join(ws, phone_id, ["contacts"])
        assert _eventually(lambda: "contacts" in _card_actions(phone_id))
        pending = _invoke(gateway, phone_id, "contacts", {"query": "张三"})
        cmd = _until(ws, lambda m: m.get("type") == "command", timeout=10.0)
        assert cmd.get("params") == {"query": "张三"}, cmd
        ws.send_json(_result(phone_id, cmd["command_id"], False, {}, "手机上没打开:通讯录"))
        out = pending.result(timeout=15)
    assert out["success"] is False
    assert "通讯录" in out["error"], out


def test_actions_the_phone_stops_reporting_leave_its_card(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        _join(ws, phone_id, ["location", "contacts", "sensor_data"])
        assert _eventually(lambda: sorted(_card_actions(phone_id)) == ["contacts", "location", "sensor_data"])
        # 人在手机上收回了位置和通讯录权限:手机只重发能力上报(不重发登记)
        ws.send_json(_report(phone_id, ["sensor_data"]))
        assert _eventually(lambda: _card_actions(phone_id) == ["sensor_data"]), _card_actions(phone_id)
