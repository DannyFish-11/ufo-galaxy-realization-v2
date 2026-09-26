"""智能体能主动跟你说一句话 —— agent_message 终于有了发送方。

为什么要这道门
==============
协议里的 ``agent_message`` 和手表那头(弹通知、记会话、按 message_id 去重)早就就位,
网关这头却没有任何代码发它。于是"跑完了告诉你一声"这类不需要你回答的话,
手表上永远收不到 —— 它只会在你先问、或者智能体要你做决定时才出现。

钉的事:
  1. 报文形状是手表读得懂的那一份(顶层字段,另在 payload 里各放一份);
  2. 每条有自己的 message_id(手表靠它去重);
  3. 投递走与 decision_request 同一条路,一台失败不连坐,没人收到时如实报出;
  4. 智能体真的有工具可调(ask_human__notify),而且它走到了这里。
"""

from __future__ import annotations

import asyncio
import types

import pytest

from core.interaction import agent_message as am

# ---------------------------------------------------------------------------
# 一、报文
# ---------------------------------------------------------------------------


def test_message_has_the_fields_the_watch_reads_at_top_level():
    m = am.build_agent_message(text="构建跑完了,全绿", title="任务完成", conversation_id="conv-1")
    # galaxy-wearos AIPClient 的 agent_message 分支读的就是这三个顶层字段
    assert m["type"] == "agent_message"
    assert m["text"] == "构建跑完了,全绿"
    assert m["conversation_id"] == "conv-1"
    assert m["message_id"]
    assert m["title"] == "任务完成"
    # 只读 payload 的客户端也拿得到同样的内容
    for k in ("text", "conversation_id", "message_id", "title", "reply_expected", "requires_ack"):
        assert m["payload"][k] == m[k]


def test_each_message_gets_its_own_id():
    """手表按 message_id 去重 —— 两条不同的话撞了 id,第二条就会被当成重发吞掉。"""
    ids = {am.build_agent_message(text="x")["message_id"] for _ in range(50)}
    assert len(ids) == 50


def test_empty_text_is_refused():
    with pytest.raises(ValueError):
        am.build_agent_message(text="   ")


def test_overlong_text_and_title_are_truncated():
    m = am.build_agent_message(text="a" * 5000, title="t" * 200)
    assert len(m["text"]) == am.MAX_TEXT_CHARS
    assert len(m["title"]) == am.MAX_TITLE_CHARS


# ---------------------------------------------------------------------------
# 二、投递
# ---------------------------------------------------------------------------


def _run(coro):
    return asyncio.run(coro)


def test_delivers_to_each_target_and_one_failure_does_not_stop_the_rest():
    sent = []

    async def emit(did, msg):
        if did == "phone-broken":
            raise ConnectionError("gone")
        sent.append((did, msg["text"]))

    out = _run(am.push_agent_message(text="好了", devices=["watch-1", "phone-broken", "watch-2"], emit=emit))
    assert out["delivered"] == ["watch-1", "watch-2"]
    assert out["failed"] == ["phone-broken"]
    assert sent == [("watch-1", "好了"), ("watch-2", "好了")]


def test_no_devices_online_is_reported_not_hidden():
    out = _run(am.push_agent_message(text="好了", devices=[], emit=lambda *_: None))
    assert out["delivered"] == []
    assert out["targets"] == []


def test_default_targets_come_from_the_same_discovery_as_decisions(monkeypatch):
    """发给谁,与 decision_request 用同一个判据 —— 两套判据早晚会判出两种答案。"""
    sent = []

    async def discover():
        return ["watch-9"]

    async def emit(did, msg):
        sent.append(did)

    monkeypatch.setattr(am, "_discover_target_devices", discover)
    monkeypatch.setattr(am, "_default_emit", emit)
    out = _run(am.push_agent_message(text="hi"))
    assert out["delivered"] == ["watch-9"] and sent == ["watch-9"]


# ---------------------------------------------------------------------------
# 三、智能体真的能调到
# ---------------------------------------------------------------------------


def test_the_agent_has_a_notify_tool():
    from core.openclawd import _ASK_HUMAN_BUILTIN_TOOLS

    names = [t["function"]["name"] for t in _ASK_HUMAN_BUILTIN_TOOLS]
    assert "ask_human__notify" in names
    spec = next(t["function"] for t in _ASK_HUMAN_BUILTIN_TOOLS if t["function"]["name"] == "ask_human__notify")
    assert spec["parameters"]["required"] == ["text"]


def _fake_agent(session_id="sess-1"):
    from core.openclawd import OpenClawd

    agent = types.SimpleNamespace(_current_session_id=session_id)
    return agent, OpenClawd


def test_the_tool_call_reaches_the_watch(monkeypatch):
    """从智能体调工具,一路走到设备收到那条报文。"""
    got = []

    async def discover():
        return ["watch-1"]

    async def emit(did, msg):
        got.append((did, msg))

    monkeypatch.setattr(am, "_discover_target_devices", discover)
    monkeypatch.setattr(am, "_default_emit", emit)
    agent, OpenClawd = _fake_agent()
    out = _run(OpenClawd._dispatch_ask_human_tool(agent, "notify", {"text": "测试跑完了", "title": "完成"}))
    assert out["success"] is True
    assert out["delivered"] == ["watch-1"]
    did, msg = got[0]
    assert did == "watch-1" and msg["text"] == "测试跑完了" and msg["title"] == "完成"
    # 智能体当前会话作为 conversation_id,设备据此把它归进同一串上下文
    assert msg["conversation_id"] == "sess-1"


def test_nobody_received_it_is_not_success(monkeypatch):
    """一台都没送到时,智能体必须知道 —— 否则它会在回复里说"已经告诉你了"。"""

    async def discover():
        return []

    monkeypatch.setattr(am, "_discover_target_devices", discover)
    agent, OpenClawd = _fake_agent()
    out = _run(OpenClawd._dispatch_ask_human_tool(agent, "notify", {"text": "hi"}))
    assert out["success"] is False
    assert out["delivered"] == []


def test_notify_without_text_is_rejected():
    agent, OpenClawd = _fake_agent()
    out = _run(OpenClawd._dispatch_ask_human_tool(agent, "notify", {"title": "only a title"}))
    assert out["success"] is False
