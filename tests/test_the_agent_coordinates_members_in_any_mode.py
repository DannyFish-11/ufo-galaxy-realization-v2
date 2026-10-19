"""中心智能体协调已加入的设备，不看这台电脑是什么模式。

所有者的定义：「跨设备」不管在哪台设备上，都是说**这台设备**加入（电脑的开关 = 电脑加入；手机的开关 = 手机加入；
手表配对即加入），而不是智能体被模式限制。跨设备、多设备本身是让中心智能体去协调的。

此前电脑的「跨设备」开关同时是一道全局闸：本地模式下每一个「往别的设备下发」的入口都回 ``cross_device_disabled``，
真机探针里配上了、登记进 UDM / UCM、拿到 mesh 会话的手表，智能体就是用不了；按钮一关还把设备接入平面
（智能体的 devices__* 工具）、局域网发现、mDNS 一起写成 false。本文件钉住拆闸后的样子：

1. 下发入口（网关 ``DeviceRouter.dispatch_task``、单设备命令 REST、命令路由的设备执行桥、``devices__invoke``）
   在两种模式下行为一样 —— 能不能下发由成员资格决定；
2. 「跨设备」按钮只写它自己的东西：关掉它不带走设备工具、局域网发现、mDNS；旧按钮留在 .env 里的三个 false 启动时迁移掉；
3. 成员找得到智能体不分模式：mDNS 广播、局域网发现一直做；
4. 任务派发（NATS worker）只看它自己的开关，开了就把总线拉起来；
5. 安卓侧的就绪门不再含「V2 跨设备开关」。
"""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import GALAXY_TEST_API_TOKEN

_AUTH_HEADERS = {"Authorization": f"Bearer {GALAXY_TEST_API_TOKEN}"}

MODES = pytest.mark.parametrize(
    "mode_env",
    [
        {},
        {"GALAXY_CROSS_DEVICE_ENABLED": "false"},
        {"GALAXY_CROSS_DEVICE_ENABLED": "true"},
        {"GALAXY_SYSTEM_MODE": "desktop-cross-device"},
    ],
    ids=["default_local", "local", "cross_device", "cross_device_by_mode"],
)


@pytest.fixture
def mode(monkeypatch):
    for k in (
        "GALAXY_CROSS_DEVICE_ENABLED",
        "GALAXY_SYSTEM_MODE",
        "GALAXY_MASTER_BRAIN_ENABLED",
        "GALAXY_NATS_ENABLED",
        "GALAXY_NATS_URL",
    ):
        monkeypatch.delenv(k, raising=False)

    def apply(env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)

    return apply


# ── 1. 下发入口 ─────────────────────────────────────────────────────────────────


@MODES
@pytest.mark.asyncio
async def test_the_gateway_dispatches_to_one_member_in_any_mode(mode, mode_env):
    from galaxy_gateway.device_router import DeviceRouter

    mode(mode_env)
    sent = AsyncMock(return_value={"success": True, "result": "sent"})
    task = {"task_id": "t1", "trace_id": "tr1", "command": "screenshot", "payload": {}}
    with patch("core.aip_transport.get_aip_transport", return_value=SimpleNamespace(send=sent)):
        out = await DeviceRouter().dispatch_task(task, SimpleNamespace(device_id="laptop-1", websocket=None))
    assert out["success"] is True, out
    sent.assert_awaited_once()


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
    return TestClient(app, headers=_AUTH_HEADERS), sent


@MODES
def test_the_single_device_command_route_sends_in_any_mode(devices_client, mode, mode_env):
    client, sent = devices_client
    mode(mode_env)
    r = client.post("/api/v1/devices/laptop-1/command", json={"command": "screenshot", "params": {}})
    assert r.status_code == 200 and r.json()["success"] is True, r.text
    assert sent and sent[0][0] == "laptop-1"


def test_the_single_device_command_route_sends_the_frame_devices_understand(devices_client):
    """真机实测:这条路由原先发 ``{type:"CONTROL_COMMAND", payload:{...}}`` —— 手表、手机都不认,接口却回「已发送」。
    设备认的只有规范派发与命令路由发的那一种。"""
    client, sent = devices_client
    r = client.post("/api/v1/devices/wear-1/command", json={"command": "notify", "params": {"text": "水开了"}})
    frame = sent[0][1]
    assert frame["type"] == "command" and frame["command"] == "notify" and frame["params"] == {"text": "水开了"}
    assert frame["command_id"] == r.json()["command_id"], "设备回 command_result 要靠它对上号"


@pytest.fixture
def node_executor(monkeypatch):
    """真实的 ``_command_node_executor``（``create_router`` 里注册给命令路由的那一个）。"""
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


@MODES
def test_the_command_routers_device_bridge_sends_in_any_mode(node_executor, mode, mode_env):
    executor, sent = node_executor
    mode(mode_env)
    out = asyncio.run(executor("laptop-1", "screenshot", {}))
    assert out == {"sent_to_device": "laptop-1", "success": True}
    assert sent and sent[0][1]["command"] == "screenshot"


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


@MODES
def test_the_agents_invoke_goes_to_the_canonical_dispatcher_in_any_mode(phone, mode, mode_env):
    """``devices__invoke`` 对讲 AIP 的成员一律走规范派发链（权限门在里面），不先问模式。"""
    from core.capabilities import canonical_dispatcher as cd

    mode(mode_env)
    seen = []

    class _Result:
        def as_legacy_dict(self):
            return {"success": True, "result": "done"}

    class _Dispatcher:
        async def dispatch(self, name, params, session_id=""):
            seen.append(name)
            return _Result()

    with patch.object(cd, "get_canonical_dispatcher", return_value=_Dispatcher()):
        out = _invoke(phone)
    assert out == {"success": True, "result": "done"}
    assert seen == ["device__phone-1__screenshot"]


def test_a_device_that_is_not_a_member_is_still_reported_as_such(phone, mode):
    out = _invoke("nobody")
    assert out["success"] is False and "没有这个成员" in out["error"]


# ── 2. 按钮只写它自己的东西 ──────────────────────────────────────────────────────


def test_the_button_does_not_own_the_agents_device_tools_or_discovery():
    from core.routes.config_bundles import CONFIG_BUNDLES

    b = next(x for x in CONFIG_BUNDLES if x["key"] == "cross_device")
    assert tuple(b.get("members") or ()) == ("GALAXY_NATS_ENABLED",)
    for key in (
        "GALAXY_ONBOARDING_ENABLED",
        "GALAXY_LAN_DISCOVERY",
        "GALAXY_MDNS",
        "GALAXY_HEADSCALE_URL",
        "GALAXY_TURN_URL",
    ):
        assert key not in (b.get("members") or ()), key


def test_the_agents_device_tools_survive_the_button_being_off(monkeypatch):
    from core.device_onboarding.agent_tools import devices_tools_for_agent

    monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "false")
    monkeypatch.delenv("GALAXY_ONBOARDING_ENABLED", raising=False)
    names = {t["function"]["name"] for t in devices_tools_for_agent()}
    assert {"devices__invoke", "devices__list"} <= names, names
    monkeypatch.setenv("GALAXY_ONBOARDING_ENABLED", "false")  # 设备接入平面有它自己的开关
    assert devices_tools_for_agent() == []


def _write(path, text):
    path.write_text(text, encoding="utf-8")
    from dotenv import dotenv_values

    return dict(dotenv_values(str(path)))


_OLD_BUTTON_OFF = """GALAXY_API_TOKEN=x
# 跨设备
GALAXY_CROSS_DEVICE_ENABLED=false
GALAXY_NATS_ENABLED=false
# 设备接入
GALAXY_ONBOARDING_ENABLED=false
# 局域网发现
GALAXY_LAN_DISCOVERY=false
# mDNS
GALAXY_MDNS=false
OTHER=1
"""


def test_the_three_falses_the_old_button_left_behind_are_cleared_on_startup(tmp_path):
    from main import migrate_former_cross_device_members

    env = tmp_path / ".env"
    dotenv = _write(env, _OLD_BUTTON_OFF)
    assert migrate_former_cross_device_members(str(env), dotenv) is True
    text = env.read_text(encoding="utf-8")
    for key in ("GALAXY_ONBOARDING_ENABLED", "GALAXY_LAN_DISCOVERY", "GALAXY_MDNS"):
        assert key not in text and key not in dotenv, key
    for kept in ("GALAXY_CROSS_DEVICE_ENABLED=false", "GALAXY_NATS_ENABLED=false", "OTHER=1", "# 跨设备"):
        assert kept in text, kept
    for gone in ("# 设备接入", "# 局域网发现", "# mDNS"):
        assert gone not in text, gone
    assert migrate_former_cross_device_members(str(env), dotenv) is False, "第二次什么都不做"


@pytest.mark.parametrize(
    "text",
    [
        # 只手写了一项 false:那是人的选择
        "GALAXY_CROSS_DEVICE_ENABLED=false\nGALAXY_MDNS=false\n",
        # 主键开着时写的:不是按钮关时留下的指纹
        "GALAXY_CROSS_DEVICE_ENABLED=true\nGALAXY_ONBOARDING_ENABLED=false\nGALAXY_LAN_DISCOVERY=false\nGALAXY_MDNS=false\n",
    ],
)
def test_a_hand_written_false_is_left_alone(tmp_path, text):
    from main import migrate_former_cross_device_members

    env = tmp_path / ".env"
    dotenv = _write(env, text)
    assert migrate_former_cross_device_members(str(env), dotenv) is False
    assert env.read_text(encoding="utf-8") == text


def test_the_migration_runs_before_the_env_reaches_the_process():
    import inspect

    import main

    src = inspect.getsource(main.load_env_files_into_environ)
    assert src.index("migrate_former_cross_device_members(") < src.index("os.environ[_k] = _v"), "先迁移再注入"


# ── 3. 成员找得到智能体,不分模式 ────────────────────────────────────────────────


@MODES
def test_mdns_is_on_in_any_mode(monkeypatch, mode, mode_env):
    from galaxy_gateway.mdns_announcer import mdns_enabled

    mode(mode_env)
    monkeypatch.delenv("GALAXY_MDNS", raising=False)
    assert mdns_enabled() is True
    monkeypatch.setenv("GALAXY_MDNS", "0")
    assert mdns_enabled() is False


@pytest.mark.asyncio
async def test_the_launcher_starts_lan_discovery_in_local_mode_and_explains_the_tailnet(mode):
    from launcher.bus_phase import _network_rows

    lan = ("局域网发现", "已发布 _galaxy._tcp", "ok")
    tailnet = SimpleNamespace(wanted=lambda: False, start_lan_discovery=lambda: lan)
    svc = SimpleNamespace(tailnet=tailnet, start_tailscale=AsyncMock(side_effect=AssertionError("不该去入网")))
    rows = await _network_rows(svc, cross_device=False)
    assert lan in rows
    assert any(r[0] == "Tailscale" and r[2] == "info" for r in rows), rows


@pytest.mark.asyncio
async def test_a_configured_headscale_joins_the_tailnet_in_local_mode(mode):
    from launcher.bus_phase import _network_rows

    lan = ("局域网发现", "已发布", "ok")
    tailnet = SimpleNamespace(wanted=lambda: True, start_lan_discovery=lambda: lan, not_on_tailnet_details=lambda: [])
    svc = SimpleNamespace(tailnet=tailnet, start_tailscale=AsyncMock(return_value="100.64.0.7"))
    rows = await _network_rows(svc, cross_device=False)
    assert ("Tailscale", "100.64.0.7", "ok") in rows
    svc.start_tailscale.assert_awaited_once()


# ── 4. 任务派发只看它自己的开关 ──────────────────────────────────────────────────


@MODES
@pytest.mark.parametrize("flag", [None, "true", "false"])
def test_task_dispatch_follows_its_own_switch(mode, mode_env, flag, monkeypatch):
    from core.system_mode import master_brain_requested, master_brain_wanted, nats_wanted

    mode(mode_env)
    if flag is not None:
        monkeypatch.setenv("GALAXY_MASTER_BRAIN_ENABLED", flag)
    wanted = flag == "true"
    assert master_brain_wanted() is wanted
    assert master_brain_requested() is wanted
    if wanted:
        assert nats_wanted() is True, "任务派发要总线:开了它,总线跟着起"


def test_every_reader_of_the_task_dispatch_switch_agrees(mode, monkeypatch):
    import logging

    from core.master_brain import master_brain_enabled
    from core.system_mode import master_brain_idle_status, resolve_fabric_config
    from core.worker_runtime import worker_enabled

    assert master_brain_enabled() is False and worker_enabled() is False
    assert master_brain_idle_status(logging.getLogger("t")) == "disabled"

    monkeypatch.setenv("GALAXY_MASTER_BRAIN_ENABLED", "true")  # 本地模式里开
    assert master_brain_enabled() is True and worker_enabled() is True
    assert resolve_fabric_config().nats_enabled is True
    assert resolve_fabric_config().cross_device_enabled is False, "电脑仍没加入网络:两件事分开"


def test_the_removed_mode_helpers_stay_removed():
    import core.system_mode as sm

    for gone in ("cross_device_refusal", "master_brain_waiting_for_mode"):
        assert not hasattr(sm, gone), gone
        assert gone not in sm.__all__


# ── 5. 安卓侧就绪门 ──────────────────────────────────────────────────────────────


def test_android_readiness_does_not_wait_for_the_computers_switch():
    from core import android_mode_gate_policy, unified_execution_governance

    for mod in (android_mode_gate_policy, unified_execution_governance):
        src = open(mod.__file__, encoding="utf-8").read()
        assert "v2_cross_device_switch" not in src, mod.__name__


def test_nothing_reads_the_switch_as_a_reason_to_refuse():
    """全仓(除这个开关本身的定义、入口判定、启动与面板展示)不再有人拿「跨设备」开关去拒绝下发。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    offenders = []
    for top in ("core", "galaxy_gateway"):
        for dirpath, _dirs, files in os.walk(os.path.join(root, top)):
            for f in files:
                if not f.endswith(".py"):
                    continue
                text = open(os.path.join(dirpath, f), encoding="utf-8").read()
                if "cross_device_disabled" in text or "cross_device_refusal" in text:
                    offenders.append(os.path.relpath(os.path.join(dirpath, f), root))
    assert offenders == [], offenders
