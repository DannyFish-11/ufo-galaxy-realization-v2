"""模型看到的是每台设备的「整体卡」,不是固定的角色(整体方案阶段 1)。

所有者:能力同化与角色分配不能是死的角色 —— 要把不同的设备当成不同的整体来看,由模型的泛化能力加上工程流程约束
决定它做什么。这里钉住:

1. ``devices__list`` 每台成员一张卡:是什么 / 能做什么(设备自己报的动作 + 一句说明)/ 现在怎么样 /
   能不能接派来的 Agent / 最近做过什么;
2. 手表经真实帧(规范入口)报上来的动作说明原样到模型眼前;它做过的事带结果出现在「最近」里;
3. 「能否接 Agent」:手机能、自己声明的载体能,手表和「手和眼」式电脑不能;
4. 固定的「感知 / 动作 / 在场」角色不进卡片,也不进任何派发路径(只留作观测标签);
5. 卡片有长度上限。
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path

import pytest

from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实帧形状共用一份
    _connect,
    _eventually,
    _online,
    _recv,
    _register,
    _watch_command_frame,
    _watch_command_result_frame,
    gateway,
    watch_id,
)

REPO = Path(__file__).resolve().parent.parent


def _list():
    import asyncio

    from core.device_onboarding.agent_tools import dispatch_devices_tool

    return asyncio.run(dispatch_devices_tool("list", {}, session_id="s-card"))


def _card(out, device_id):
    [c] = [m for m in out["members"] if m["device_id"] == device_id]
    return c


def _capability_report_with_descriptions(device_id):
    """与 galaxy-wearos ``WatchMember.capabilityReportFrame`` 同形(阶段 1 起带 capability_schemas 的 description)。"""
    return {
        "version": "3.0",
        "type": "capability_report",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "platform": "wearos",
        "supported_actions": ["notify", "haptic", "get_status"],
        "capability_schemas": [
            {"action": "notify", "description": "在手表上弹一条通知(标题 + 正文),戴表的人抬腕就能看到"},
            {"action": "haptic", "description": "让手表震一下提醒戴表的人"},
            {"action": "get_status", "description": "读手表的电量、连接与是否在佩戴"},
        ],
    }


# ── 1 / 2. 手表经真实帧到模型眼前 ───────────────────────────────────────────────


def test_the_watch_reports_what_its_actions_do_and_the_model_reads_it(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_capability_report_with_descriptions(watch_id))
        _recv(ws, timeout=2.0)
        assert _eventually(lambda: _online(watch_id))
        card = _card(_list(), watch_id)

    assert card["form"] == "watch"
    assert card["status"]["online"] is True
    does = {a["name"]: a["does"] for a in card["actions"]}
    assert does["notify"].startswith("在手表上弹一条通知"), does
    assert does["haptic"] == "让手表震一下提醒戴表的人"
    assert card["can_take_agent"] is False, "手表是人和智能体之间的入口和出口,不跑 Agent"


def test_what_the_watch_did_shows_up_with_its_result(gateway, watch_id):
    from core.capabilities.canonical_dispatcher import get_canonical_dispatcher

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        assert _eventually(lambda: _online(watch_id))

        async def invoke():
            return await get_canonical_dispatcher().dispatch(
                f"device__{watch_id}__notify", {"text": "x"}, session_id="s"
            )

        pending = gateway.portal.start_task_soon(invoke)
        frame = _recv(ws)

        async def busy_now():
            return _card(_list_async_safe(), watch_id)["status"].get("busy")

        assert gateway.portal.call(busy_now) is True, "有一条下发在等结果:忙"
        ws.send_json(_watch_command_result_frame(watch_id, frame["command_id"], True, {"shown": True}))
        assert pending.result(timeout=10).success is True
        card = _card(_list(), watch_id)

    assert card["status"].get("busy") is False
    [last] = card["recent"][:1]
    assert last["what"] == "notify" and last["state"] == "completed", card["recent"]


def _list_async_safe():
    from core.device_onboarding.agent_tools import _list as list_impl

    return list_impl({})


def test_the_wearers_interruptibility_is_on_the_watch_card(gateway, watch_id):
    report = {"score": 0.1, "band": "busy", "reasons": ["in_meeting"], "confidence": 0.8, "device": "wear_os"}
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(_watch_command_frame(watch_id, "interruptibility", report, "cmd_9", 9))
        _recv(ws)
        card = _card(_list(), watch_id)
    assert card["status"].get("interruptible") == "busy"


# ── 3. 能否接 Agent ────────────────────────────────────────────────────────────


@pytest.fixture
def registry(tmp_path, monkeypatch):
    from core.device_onboarding.service import reset_onboarding_service
    from core.unified.connection_manager import reset_unified_connection_manager
    from core.unified.device_manager import get_unified_device_manager, reset_unified_device_manager

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GALAXY_ONBOARDING_STATE_DIR", str(tmp_path / "ob"))
    for r in (reset_unified_device_manager, reset_unified_connection_manager, reset_onboarding_service):
        r()
    yield get_unified_device_manager()
    for r in (reset_unified_device_manager, reset_unified_connection_manager, reset_onboarding_service):
        r()


@pytest.mark.parametrize(
    "device_id,data,expected",
    [
        # 看设备自己说的(登记时报 join_runtime,或报能力时声明能装 Agent),不看类型
        (
            "phone-1",
            {"device_type": "Android_Agent", "transport": "websocket", "source_runtime_posture": "join_runtime"},
            True,
        ),
        ("phone-2", {"device_type": "Android_Agent", "transport": "websocket"}, False),
        ("wear-1", {"device_type": "wearos", "transport": "websocket"}, False),
        ("laptop-1", {"device_type": "windows_desktop", "transport": "websocket"}, False),
        (
            "carrier-1",
            {"device_type": "linux_server", "transport": "websocket", "can_host_agent": True},  # 载体自己声明
            True,
        ),
    ],
)
def test_who_can_take_a_dispatched_agent(registry, device_id, data, expected):
    registry.register_device_from_dict(device_id, data)
    assert _card(_list(), device_id)["can_take_agent"] is expected


def test_an_action_without_a_description_gets_a_plain_one(registry):
    from core.device_onboarding.device_card import ACTION_GLOSSARY, build_device_card

    card = build_device_card({"device_id": "x", "name": "x", "capabilities": ["screenshot", "made_up"]})
    does = {a["name"]: a["does"] for a in card["actions"]}
    assert does["screenshot"] == ACTION_GLOSSARY["screenshot"]
    assert does["made_up"] == "", "不认识的动作不编说明"


# ── 4. 固定角色不进卡片、不进派发 ───────────────────────────────────────────────


def test_fixed_roles_are_not_shown_to_the_model(registry):
    registry.register_device_from_dict("phone-1", {"device_type": "Android_Agent", "transport": "websocket"})
    text = str(_list()).lower()
    for word in ("perception", "presence", "body_score", "primary_body", "role_label"):
        assert word not in text, word


@pytest.mark.parametrize(
    "rel",
    [
        "galaxy_gateway/device_router.py",
        "core/command_router.py",
        "core/capabilities/canonical_dispatcher.py",
        "core/device_onboarding/agent_tools.py",
        "core/runtime/source_dispatch_orchestrator.py",
    ],
)
def test_no_dispatch_path_picks_devices_by_fixed_role(rel):
    src = (REPO / rel).read_text(encoding="utf-8")
    for marker in ("device_role_allocator", "compute_assignment", "DeviceRole.PERCEPTION", "DeviceRole.ACTION"):
        assert marker not in src, f"{rel} 用固定角色挑设备:{marker}"


# ── 5. 长度上限 ────────────────────────────────────────────────────────────────


def test_the_card_stays_short(registry):
    from core.device_onboarding.device_card import MAX_ACTIONS, build_device_card

    caps = [f"act_{i}" for i in range(200)]
    card = build_device_card({"device_id": "big", "name": "big", "capabilities": caps})
    assert len(card["actions"]) == MAX_ACTIONS and len(card["raw_capabilities"]) == MAX_ACTIONS


def test_the_tool_tells_the_model_it_decides():
    from core.device_onboarding import agent_tools

    [t] = [t for t in agent_tools.DEVICES_BUILTIN_TOOLS if t["function"]["name"] == "devices__list"]
    desc = t["function"]["description"]
    assert "You decide which device does what" in desc and "can_take_agent" in desc
    assert "grouped by role" not in desc
    assert "build_device_card" in inspect.getsource(agent_tools._list)


def test_the_phones_action_descriptions_reach_the_card(registry):
    """安卓的 capability_report 带的是 ``action_descriptions`` 映射(ufo-galaxy-android ``PhoneActionDescriptions``)。"""
    from galaxy_gateway.android.handlers.capability_report import _sync_supported_actions_to_capability_authority

    registry.register_device_from_dict("phone-9", {"device_type": "Android_Agent", "transport": "websocket"})
    _sync_supported_actions_to_capability_authority(
        device_id="phone-9",
        supported_actions=["camera", "sms"],
        capability_schemas=[],
        version="3.0",
        action_descriptions={"camera": "用手机摄像头拍照", "sms": "发一条短信(要人确认)"},
    )
    does = {a["name"]: a["does"] for a in _card(_list(), "phone-9")["actions"]}
    assert does == {"camera": "用手机摄像头拍照", "sms": "发一条短信(要人确认)"}


def test_the_watch_is_called_what_it_said_it_is(gateway, watch_id):
    """真机实测:手表登记报 ``device_name="OPPO Watch 3"``,名册里却叫「Android Device」—— 模型看到的名字是错的。"""
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        card = _card(_list(), watch_id)
    assert card["name"] == "OPPO Watch 3"


def test_a_phone_without_a_name_in_its_frame_is_called_what_it_was_paired_as(registry):
    from core.peer_trust import get_peer_trust_book
    from core.unified.models import UnifiedDeviceType
    from galaxy_gateway.android.device_naming import registration_name as _registration_name

    get_peer_trust_book().upsert("phone-7", name="小米 17", trust="friend")
    assert _registration_name({"device_id": "phone-7"}, "phone-7", UnifiedDeviceType.ANDROID) == "小米 17"
    assert (
        _registration_name({"device_id": "x"}, "x", UnifiedDeviceType.ANDROID) == "x"
    ), "没名字就用设备 id,不按平台起泛称"
