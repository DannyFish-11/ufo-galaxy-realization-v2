"""设备自己声明能做的几件事,中心按声明对待它,不看它是什么类型的设备(``core/device_declarations.py``)。

声明在设备自述 ``self_description.declares`` 里(旧版设备在能力上报顶层或 payload),布尔值:能回答提问、
显示请求进度。原来还有一项「能显示消息」,已并回各设备自己报的消息动作(``ask_human__notify`` 调它)。
经真网关记下与撤掉的测试在 ``test_watch_reaches_the_central_agent.py``;这里钉住解析和几个按声明走的入口。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core import device_declarations as dd


def test_declarations_are_read_from_the_top_level_or_the_payload_and_default_to_no():
    assert dd.declared_in({"answers_decisions": True, "payload": {"shows_request_progress": "true"}}) == {
        "answers_decisions": True,
        "shows_request_progress": True,
    }
    assert "shows_messages" not in dd.DECLARATIONS, "发给谁是模型的判断,不再是一项声明"
    assert dd.declared_in({}) == {k: False for k in dd.DECLARATIONS}
    assert dd.declared_in({"answers_decisions": "yes"})["answers_decisions"] is False, "只认 true,不猜"


def test_who_is_asked_and_who_is_told_follows_what_each_device_said(monkeypatch):
    devices = {
        "watch-1": {"answers_decisions": True},
        "phone-1": {"shows_request_progress": True},
        "tv-1": {"answers_decisions": True},
    }

    async def online():
        return list(devices)

    monkeypatch.setattr(dd, "online_devices", online)
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager",
        lambda: SimpleNamespace(get_device=lambda did: SimpleNamespace(metadata=devices.get(did, {}))),
    )
    from core.interaction import agent_message, pending_decision_registry

    assert asyncio.run(pending_decision_registry._discover_target_devices()) == ["watch-1", "tv-1"], "什么类型都按声明"
    assert not hasattr(agent_message, "_discover_message_devices"), "不再按声明替模型挑发消息的设备"


def test_a_message_goes_through_the_named_devices_own_notify_action(monkeypatch):
    """点名了就只发给点名的,而且走那台设备自己报的消息动作(effect 为 notify、收 text);
    报了自述却没有这样的动作的照实说送不到;还没有自述的旧版设备照旧收一条 agent_message。"""
    from core import device_self
    from core.device_onboarding import agent_tools
    from core.interaction import agent_message as am
    from tests.device_self_frames import phone_self

    descs = {
        "p-1": device_self.read({"self_description": phone_self(["notification", "location"])}),
        "s-1": device_self.read({"self_description": phone_self(["location"])}),
    }
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager",
        lambda: SimpleNamespace(
            get_device=lambda did: SimpleNamespace(
                metadata={"self_description": descs[did]} if did in descs else {}, device_name=did
            )
        ),
    )
    calls, frames = [], []

    async def invoke(args, session_id):
        calls.append((args, session_id))
        return {"success": True}

    async def emit(did, msg):
        frames.append((did, msg["type"], msg["text"]))

    monkeypatch.setattr(agent_tools, "_invoke", invoke)
    monkeypatch.setattr(am, "_default_emit", emit)
    out = asyncio.run(
        am.dispatch_notify_tool(
            {"text": "到了", "title": "提醒", "device_ids": ["p-1", "s-1", "old-1"]}, session_id="s1"
        )
    )
    assert out["delivered"] == ["p-1", "old-1"] and out["failed"] == ["s-1"], out
    assert "notify" in out["reasons"]["s-1"], "报了自述却没有消息动作的,照实说送不到"
    args, _ = calls[0]
    assert args["action"] == "notification" and args["params"] == {"text": "到了", "title": "提醒"}, args
    assert frames == [("old-1", "agent_message", "到了")], "旧版设备照旧收 agent_message"


def test_only_a_runtime_posture_the_device_states_counts(monkeypatch):
    """完整运行时看设备明说的 join_runtime;登记处理给没报的设备补的默认值不算。"""
    from core.device_onboarding.taxonomy import FULL_RUNTIME_HOST, execution_model_for

    assert execution_model_for(metadata={"source_runtime_posture": "join_runtime"}) == FULL_RUNTIME_HOST
    for t in ("android_phone", "ios_tablet", "android_wear"):
        assert execution_model_for(aip_device_type=t, metadata={}) != FULL_RUNTIME_HOST, t


def test_the_fallback_router_finds_a_target_by_the_roster_not_by_kind_words(monkeypatch):
    """兜底路由(``e2e_pipeline``)按名册里的设备 id / 名字认目标,不按「手机 / 电脑」这类词。"""
    from core import e2e_pipeline

    roster = [
        SimpleNamespace(device_id="w-1", device_name="书房笔记本"),
        SimpleNamespace(device_id="p-9", device_name=""),
    ]
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager", lambda: SimpleNamespace(list_devices=lambda: roster)
    )
    assert e2e_pipeline._match_member(["书房笔记本"]) == "w-1"
    assert e2e_pipeline._match_member(["P-9"]) == "p-9"
    assert e2e_pipeline._match_member(["手机", "电脑"]) == "", "名册里没有叫这个的设备就不猜"
