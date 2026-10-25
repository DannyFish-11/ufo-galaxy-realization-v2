"""手表、手机、中心当一个整体:人在手表上问一句,中心智能体去手机上查,答案回到手表;智能体也读得到手表上的心率。

全程走真实的规范设备入口:手表、手机各一条 WebSocket,帧形状与两个客户端一致(手表 ``WatchMember``、
手机 ``GalaxyWebSocketClient`` / ``DeviceCommandFrames``)。智能体的推理循环是真的 ``OpenClawd._react_loop``,
工具执行是真的 ``_dispatch_tool_call``,只有「模型」换成按剧本出牌的假路由 —— 它从 ``devices__list`` 的设备卡里
**自己挑**有日历的那台(测试不告诉它是哪台),再调 ``devices__invoke``,最后用手机回来的内容作答。

单台设备的各段已有各自的测试(``test_watch_reaches_the_central_agent``、``test_the_agent_calls_a_phones_actions``);
这里钉的是它们**同时在线、互相接力**时这条链是通的。
"""

from __future__ import annotations

import ast
import json
import time
from types import SimpleNamespace

import pytest

from core.device_onboarding import agent_tools
from tests.test_phone_joins_through_its_bridge_agent import _until, phone_id  # noqa: F401 — 夹具共用
from tests.test_the_agent_calls_a_phones_actions import _card_actions
from tests.test_the_agent_calls_a_phones_actions import _connect as _connect_phone
from tests.test_the_agent_calls_a_phones_actions import _join, _result
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _register,
    _watch_command_frame,
    _watch_command_result_frame,
    gateway,
    watch_id,
)


def _watch_report(device_id, actions):
    """与 galaxy-wearos ``WatchMember.capabilityReportFrame`` 同形:只报此刻做得了的动作,每个带一句说明。"""
    return {
        "version": "3.0",
        "type": "capability_report",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "platform": "wearos",
        "supported_actions": list(actions),
        "capability_schemas": [{"action": a, "description": f"手表动作 {a}"} for a in actions],
    }


def _last_tool_result(messages):
    """模型看到的最近一次工具结果。循环在结果后面追加结局提示与上下文油表(各起一行 ``[...]``),只取前面的结果本身;
    结果是 JSON(摊在顶层的返回体),或 ``result`` 字段的 Python 写法。"""
    for m in reversed(messages):
        if m.get("role") == "tool":
            head = (m.get("content") or "").split("\n[")[0]
            for parse in (json.loads, ast.literal_eval):
                try:
                    return parse(head)
                except (ValueError, SyntaxError):
                    continue
            return {"raw": head}
    return {}


def _reply(content="", call=None):
    from core.multi_llm_router import LLMResponse

    tool_calls = None
    if call:
        name, args = call
        tool_calls = [
            {"id": f"c-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
        ]
    return LLMResponse(
        content=content,
        provider="scripted",
        model="scripted",
        input_tokens=1,
        output_tokens=1,
        latency_ms=1.0,
        tool_calls=tool_calls,
    )


class _ScriptedModel:
    """按剧本出牌的「模型」:先看有哪些设备 → 挑出报了 calendar 的那台去查 → 用查回来的日程作答。"""

    def __init__(self):
        self.offered, self.seen = [], []

    async def chat_with_tools(self, messages, tools=None, task_type=None, max_tokens=4096, **kwargs):
        self.offered.append(sorted(t["function"]["name"] for t in tools or []))
        last = _last_tool_result(messages)
        self.seen.append(last)
        if len(self.seen) == 1:
            return _reply(call=("devices__list", {}))
        if len(self.seen) == 2:
            with_calendar = [c for c in last.get("members", []) if any(a["name"] == "calendar" for a in c["actions"])]
            if not with_calendar:
                return _reply("没有能查日程的设备")
            return _reply(
                call=(
                    "devices__invoke",
                    {
                        "device_id": with_calendar[0]["device_id"],
                        "action": "calendar",
                        "params": {"from": "2026-10-25T12:00:00+08:00", "to": "2026-10-25T18:00:00+08:00"},
                    },
                )
            )
        events = last.get("events") or []
        if not events:
            return _reply(f"没查到:{last.get('raw') or last}")
        e = events[0]
        return _reply(f"下午 {e['start'][11:16]} 有「{e['title']}」,在{e.get('location', '')}")


@pytest.fixture
def center(monkeypatch):
    """中心智能体:真的推理循环 + 真的工具执行,模型按剧本。手表那一路的入口、分流、回包也都是真的。"""
    from core.compute_scheduler import ComputeScheduler
    from core.openclawd import OpenClawd

    # 没有真模型时调度器按本地小模型给 4096 的窗口,工具结果一进来就被当成「该压缩了」;
    # 中心用的是云端大模型,按它的窗口算
    monkeypatch.setattr(
        ComputeScheduler, "context_budget_for", lambda self, tag, profile=None, cfg=None: (128_000, "云端模型")
    )
    model = _ScriptedModel()
    calls = []

    class _Runtime:
        async def handle_request(self, **kw):
            calls.append(kw)
            clawd = OpenClawd.__new__(OpenClawd)
            clawd._capability_dispatcher = None
            clawd._tool_permission_checker = None
            clawd._get_router = lambda: model
            out = await clawd._react_loop(
                [{"role": "user", "content": kw["message"]}], tools=agent_tools.DEVICES_BUILTIN_TOOLS
            )
            return {"success": True, "response": out["response"], "runtime_session_id": "rs-1"}

    import core.desktop_presence_runtime as dpr

    monkeypatch.setattr(dpr, "get_desktop_presence_runtime", lambda: _Runtime())
    return SimpleNamespace(model=model, calls=calls)


def test_asked_on_the_watch_looked_up_on_the_phone_answered_on_the_watch(gateway, watch_id, phone_id, center):
    with _connect(gateway, watch_id) as watch, _connect_phone(gateway, phone_id) as phone:
        _register(watch, watch_id)
        watch.send_json(_watch_report(watch_id, ["notify", "haptic", "get_status", "heart_rate", "steps"]))
        _join(phone, phone_id, ["calendar", "location", "contacts"])
        assert _eventually(lambda: "calendar" in _card_actions(phone_id)), "设备卡上没有手机报的日历"
        assert _eventually(lambda: "heart_rate" in _card_actions(watch_id)), "设备卡上没有手表报的心率"

        watch.send_json(
            _watch_command_frame(watch_id, "voice_query", {"text": "我下午有什么安排", "source": "wear_os"}, "cmd_9", 9)
        )

        cmd = _until(phone, lambda m: m.get("type") == "command", timeout=20.0)
        assert cmd.get("command") == "calendar", cmd
        assert cmd["params"]["from"].startswith("2026-10-25T12:00"), cmd
        phone.send_json(
            _result(
                phone_id,
                cmd["command_id"],
                True,
                {
                    "events": [
                        {
                            "title": "设计评审",
                            "start": "2026-10-25T15:00:00+08:00",
                            "end": "2026-10-25T16:00:00+08:00",
                            "location": "会议室 A",
                            "all_day": False,
                        }
                    ]
                },
            )
        )

        answer = _until(
            watch, lambda m: m.get("type") == "command_result" and m.get("correlation_id") == "cmd_9", timeout=20.0
        )

    assert answer, "手表没收到回答"
    assert answer["success"] is True, answer
    assert answer["data"]["text"] == "下午 15:00 有「设计评审」,在会议室 A", answer

    # 是模型自己从设备卡里认出手机的:它看到的那张表里两台都在,只有手机有日历
    listed = {c["device_id"]: [a["name"] for a in c["actions"]] for c in center.model.seen[1]["members"]}
    assert "calendar" in listed[phone_id] and "calendar" not in listed[watch_id], listed
    assert "devices__invoke" in center.model.offered[0]
    assert center.calls[0]["source"] == "wear_voice" and center.calls[0]["device_id"] == watch_id


def test_a_phone_that_cannot_read_the_calendar_is_answered_honestly_on_the_watch(gateway, watch_id, phone_id, center):
    """手机说做不了(日历权限被收回),手表上听到的是原因,不是编出来的日程。"""
    with _connect(gateway, watch_id) as watch, _connect_phone(gateway, phone_id) as phone:
        _register(watch, watch_id)
        _join(phone, phone_id, ["calendar"])
        assert _eventually(lambda: "calendar" in _card_actions(phone_id))
        watch.send_json(_watch_command_frame(watch_id, "voice_query", {"text": "我下午有什么安排"}, "cmd_3", 3))
        cmd = _until(phone, lambda m: m.get("type") == "command", timeout=20.0)
        phone.send_json(_result(phone_id, cmd["command_id"], False, {}, "手机上没给日历权限"))
        answer = _until(
            watch, lambda m: m.get("type") == "command_result" and m.get("correlation_id") == "cmd_3", timeout=20.0
        )
    assert "手机上没给日历权限" in answer["data"]["text"], answer


def _invoke(gateway, device_id, action, params=None):
    async def call():
        return await agent_tools.dispatch_devices_tool(
            "invoke", {"device_id": device_id, "action": action, "params": params or {}}, session_id="sess-watch"
        )

    return gateway.portal.start_task_soon(call)


def test_the_agent_reads_the_heart_rate_on_the_watch(gateway, watch_id):
    with _connect(gateway, watch_id) as watch:
        _register(watch, watch_id)
        watch.send_json(_watch_report(watch_id, ["notify", "haptic", "get_status", "heart_rate"]))
        assert _eventually(lambda: "heart_rate" in _card_actions(watch_id))
        pending = _invoke(gateway, watch_id, "heart_rate")
        cmd = _until(watch, lambda m: m.get("type") == "command", timeout=10.0)
        assert cmd.get("command") == "heart_rate" and cmd.get("command_id"), cmd
        watch.send_json(
            _watch_command_result_frame(watch_id, cmd["command_id"], True, {"bpm": 72, "samples": 5, "measured_at": 1})
        )
        out = pending.result(timeout=15)
    assert out["success"] is True, out
    assert out["result"]["bpm"] == 72


def test_a_watch_whose_heart_rate_permission_was_taken_back_drops_it_from_its_card(gateway, watch_id):
    """戴表的人在设置里收回了身体传感器权限:手表回到 App 时重报,智能体的设备卡上不再有心率。"""
    with _connect(gateway, watch_id) as watch:
        _register(watch, watch_id)
        watch.send_json(_watch_report(watch_id, ["notify", "haptic", "get_status", "heart_rate", "steps"]))
        assert _eventually(lambda: "heart_rate" in _card_actions(watch_id))
        watch.send_json(_watch_report(watch_id, ["notify", "haptic", "get_status", "steps"]))
        assert _eventually(
            lambda: sorted(_card_actions(watch_id)) == ["get_status", "haptic", "notify", "steps"]
        ), _card_actions(watch_id)
