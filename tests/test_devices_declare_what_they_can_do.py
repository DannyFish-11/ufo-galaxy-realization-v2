"""设备自己声明能做的几件事,中心按声明对待它,不看它是什么类型的设备(``core/device_declarations.py``)。

声明在能力上报里(顶层或 payload),布尔值:能回答提问、能显示消息、显示请求进度。经真网关记下与撤掉的
测试在 ``test_watch_reaches_the_central_agent.py``;这里钉住解析和几个按声明走的入口。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core import device_declarations as dd


def test_declarations_are_read_from_the_top_level_or_the_payload_and_default_to_no():
    assert dd.declared_in({"answers_decisions": True, "payload": {"shows_messages": "true"}}) == {
        "answers_decisions": True,
        "shows_messages": True,
        "shows_request_progress": False,
    }
    assert dd.declared_in({}) == {k: False for k in dd.DECLARATIONS}
    assert dd.declared_in({"answers_decisions": "yes"})["answers_decisions"] is False, "只认 true,不猜"


def test_who_is_asked_and_who_is_told_follows_what_each_device_said(monkeypatch):
    devices = {
        "watch-1": {"answers_decisions": True, "shows_messages": True},
        "phone-1": {"shows_request_progress": True},
        "tv-1": {"shows_messages": True},
    }

    async def online():
        return list(devices)

    monkeypatch.setattr(dd, "online_devices", online)
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager",
        lambda: SimpleNamespace(get_device=lambda did: SimpleNamespace(metadata=devices.get(did, {}))),
    )
    from core.interaction import agent_message, pending_decision_registry

    assert asyncio.run(pending_decision_registry._discover_target_devices()) == ["watch-1"]
    assert asyncio.run(agent_message._discover_message_devices()) == ["watch-1", "tv-1"], "什么类型都按声明"


def test_the_agent_can_name_the_devices_a_message_goes_to(monkeypatch):
    from core.interaction import agent_message as am

    sent = []

    async def emit(did, msg):
        sent.append(did)

    async def discover():
        return ["watch-1"]

    monkeypatch.setattr(am, "_default_emit", emit)
    monkeypatch.setattr(am, "_discover_message_devices", discover)
    out = asyncio.run(am.dispatch_notify_tool({"text": "到了", "device_ids": ["tv-1"]}))
    assert out["success"] and sent == ["tv-1"], "点名了就只发给点名的"


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
