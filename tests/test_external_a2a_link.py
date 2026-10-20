"""对外 A2A:中心智能体与派出去的 Agent 之间的「必达」通话(跨设备整体方案阶段 2)。

链路语义与 ufo-galaxy-android ``shared-protocol/.../A2ALinkTest`` 是同一组场景 —— 两端行为必须一致,
否则手机与中心之间会出现「一边以为送到了、一边没收到」。后半部分走真实的规范设备入口(``/ws/device``):
设备发来的 ``a2a`` 帧被确认、去重、按类交给处理器;中心发出的消息设备不在线时留着,重连后补发。
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import pytest

from core import a2a_link as a2a
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    _connect,
    _eventually,
    _online,
    _recv,
    _register,
    gateway,
    watch_id,
)

REPO = Path(__file__).resolve().parent.parent


def _pair():
    n = {"i": 0}

    def ids():
        n["i"] += 1
        return f"m{n['i']}"

    return (
        a2a.Link("s1", "center", "agent:phone", clock=lambda: 1, new_id=ids),
        a2a.Link("s1", "agent:phone", "center", clock=lambda: 1, new_id=ids),
    )


# ── 链路语义(与安卓 A2ALinkTest 同一组) ───────────────────────────────────────


def test_a_message_is_kept_until_it_is_acknowledged():
    center, phone = _pair()
    env = center.make(a2a.Kind.DELEGATE_GOAL, {"goal": "打开微信"})
    assert center.unacked() == [env]
    deliver, ack = phone.accept(env)
    assert deliver == [env] and ack is not None
    center.accept(ack)
    assert center.unacked() == []


def test_a_duplicate_is_acknowledged_again_but_delivered_once():
    center, phone = _pair()
    env = center.make(a2a.Kind.CONVERSATION)
    assert len(phone.accept(env)[0]) == 1
    deliver, ack = phone.accept(env)
    assert deliver == [] and ack is not None, "重复的也要回确认,发送方才会停"


def test_out_of_order_messages_are_delivered_in_order():
    center, phone = _pair()
    a, b, c = (
        center.make(k) for k in (a2a.Kind.DELEGATE_PROGRESS, a2a.Kind.DELEGATE_PROGRESS, a2a.Kind.DELEGATE_RESULT)
    )
    assert phone.accept(c)[0] == [] and phone.accept(b)[0] == []
    assert phone.accept(a)[0] == [a, b, c]


def test_after_a_reconnect_the_unacknowledged_ones_are_resent_and_nothing_is_delivered_twice():
    center, phone = _pair()
    a = center.make(a2a.Kind.CONTEXT_RETURN)
    b = center.make(a2a.Kind.RECALL)
    phone.accept(a)  # a 到了但确认在断线时丢了;b 根本没到
    resend = center.unacked()
    assert resend == [a, b]
    assert [e for r in resend for e in phone.accept(r)[0]] == [b]


def test_messages_that_need_no_ack_are_not_kept():
    center, _ = _pair()
    center.make(a2a.Kind.DELEGATE_PROGRESS, ack_required=False)
    assert center.unacked() == []


def test_an_ack_is_unordered_and_never_acknowledged_itself():
    center, phone = _pair()
    _, ack = phone.accept(center.make(a2a.Kind.TOOL_CALL))
    assert ack.seq == 0 and ack.kind == "ack"
    assert center.accept(ack) == ([], None)


def test_the_wire_form_round_trips_and_rejects_what_it_does_not_know():
    center, _ = _pair()
    env = center.make(a2a.Kind.AGENT_DISPATCH, {"bridge": "v1"}, task_id="t1", trace_id="tr")
    assert a2a.Envelope.from_dict(env.to_dict()) == env
    assert env.to_aip_frame("phone-1")["type"] == "a2a"
    assert a2a.Envelope.from_dict({**env.to_dict(), "kind": "made_up"}) is None
    assert a2a.Envelope.from_dict({**env.to_dict(), "protocol": "a2a/0"}) is None


def test_a_gap_that_never_fills_does_not_jam_the_link():
    center, phone = _pair()
    center.make(a2a.Kind.CONVERSATION)  # seq 1 永远丢了
    later = [center.make(a2a.Kind.CONVERSATION) for _ in range(a2a.MAX_BUFFERED + 1)]
    out = []
    for e in later:
        out += phone.accept(e)[0]
    assert out == later, "缺口补不上时按序交出缓着的,不卡死"


def test_when_the_phone_restarts_its_new_messages_are_still_delivered():
    center, phone = _pair()
    for _ in range(3):
        center.accept(phone.make(a2a.Kind.CONVERSATION))
    reborn = a2a.Link("s1", "agent:phone", "center")  # 手机进程重启:序号从 1 重新数
    first = reborn.make(a2a.Kind.CONVERSATION, {"text": "我回来了"})
    assert center.accept(first)[0] == [first], "不能因为序号比上一次小就当成旧消息吞掉"


def test_when_the_center_restarts_it_picks_up_where_the_phone_is():
    center, phone = _pair()
    for _ in range(3):
        _, ack = center.accept(phone.make(a2a.Kind.CONVERSATION))
        phone.accept(ack)
    reborn = a2a.Link("s1", "center", "agent:phone")  # 中心重启:不认识手机这一次的身份
    nxt = phone.make(a2a.Kind.DELEGATE_RESULT, {"ok": True})
    assert reborn.accept(nxt)[0] == [nxt], "不能干等手机早就了结的 1..3"


def test_after_a_center_restart_the_phones_resend_fills_in_what_was_never_acknowledged():
    center, phone = _pair()
    _, ack = center.accept(phone.make(a2a.Kind.CONVERSATION))
    phone.accept(ack)
    lost = [phone.make(a2a.Kind.CONVERSATION), phone.make(a2a.Kind.CONVERSATION)]  # 中心没收到就重启了
    reborn = a2a.Link("s1", "center", "agent:phone")
    out = [e for r in phone.unacked() for e in reborn.accept(r)[0]]
    assert [e.msg_id for e in out] == [e.msg_id for e in lost]


def test_a_lost_message_that_needed_no_ack_does_not_hold_back_the_next():
    center, phone = _pair()
    phone.make(a2a.Kind.DELEGATE_PROGRESS, ack_required=False)  # 丢了,也没人会补
    nxt = phone.make(a2a.Kind.DELEGATE_RESULT)
    assert center.accept(nxt)[0] == [nxt]


def test_what_was_buffered_when_the_peer_restarted_is_still_delivered():
    center, phone = _pair()
    phone.make(a2a.Kind.CONVERSATION)  # seq 1 永远没到
    held = phone.make(a2a.Kind.CONVERSATION)
    assert center.accept(held)[0] == [], "等 1"
    reborn = a2a.Link("s1", "agent:phone", "center")
    fresh = reborn.make(a2a.Kind.CONVERSATION)
    assert center.accept(fresh)[0] == [held, fresh], "已确认过的不能因为对端重启就丢了"


def test_the_kinds_are_exactly_the_ones_the_phone_knows():
    assert a2a.KINDS == {
        "agent_dispatch",
        "agent_installed",
        "context_handoff",
        "conversation",
        "delegate_goal",
        "delegate_progress",
        "delegate_result",
        "tool_call",
        "tool_result",
        "context_return",
        "recall",
        "ack",
    }
    from core.schemas.aip_v3 import MsgType

    assert MsgType("a2a").value == a2a.AIP_TYPE


def test_the_phone_side_speaks_the_same_kinds_when_the_android_repo_is_checked_out():
    import os

    root = os.environ.get("ANDROID_REPO_ROOT", "").strip()
    if not root:
        pytest.skip("ANDROID_REPO_ROOT not set")
    src = (Path(root) / "shared-protocol/src/main/java/com/ufo/galaxy/shared/protocol/A2A.kt").read_text(
        encoding="utf-8"
    )
    kotlin_kinds = set(re.findall(r'const val [A-Z_]+ = "([a-z_]+)"', src))
    assert kotlin_kinds == set(a2a.KINDS)
    assert f'const val PROTOCOL = "{a2a.PROTOCOL}"' in src
    to_json = re.search(r"fun toJson\(\): JsonObject = buildJsonObject \{(.*?)\n    \}", src, flags=re.DOTALL)
    assert to_json is not None, "A2AEnvelope.toJson 找不到了"
    kotlin_keys = set(re.findall(r'put\("([a-z_]+)"', to_json.group(1)))
    python_keys = set(a2a.Link("s", "a", "b").make(a2a.Kind.RECALL).to_dict())
    assert kotlin_keys == python_keys, "线上的键两端必须逐字一致(含 epoch / floor)"


# ── 经真实的规范设备入口 ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_links():
    a2a.reset_links()
    yield
    a2a.reset_links()


def _device_link(device_id):
    """设备那一端的链路(手机上的桥接 Agent 用的就是同一套语义)。"""
    return a2a.Link(device_id, a2a.agent_id_for(device_id), a2a.CENTER_AGENT)


def test_a_frame_from_the_device_is_acknowledged_and_handed_to_its_handler(gateway, watch_id):
    got = []

    async def on_handoff(device_id, env):
        got.append((device_id, env.body))

    a2a.register_handler(a2a.Kind.CONTEXT_HANDOFF, on_handoff)
    mine = _device_link(watch_id)
    env = mine.make(a2a.Kind.CONTEXT_HANDOFF, {"dialog": ["你好"]})
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(env.to_aip_frame(watch_id))
        reply = _recv(ws)
        ws.send_json(env.to_aip_frame(watch_id))  # 断线重连后的补发:重复
        reply2 = _recv(ws)
    assert reply.get("type") == "a2a" and reply["payload"]["kind"] == "ack", reply
    assert reply["payload"]["body"]["ack_of"] == env.msg_id
    assert reply2["payload"]["kind"] == "ack", "重复的也确认"
    assert got == [(watch_id, {"dialog": ["你好"]})], "处理器只被调一次"


def test_a_device_cannot_speak_as_another_devices_agent(gateway, watch_id):
    got = []

    async def on_any(device_id, env):
        got.append(env)

    a2a.register_handler(a2a.Kind.CONVERSATION, on_any)
    forged = a2a.Link("s", "agent:someone-else", a2a.CENTER_AGENT).make(a2a.Kind.CONVERSATION, {"text": "x"})
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)
        ws.send_json(forged.to_aip_frame(watch_id))
        reply = _recv(ws, timeout=2.0)
    assert got == []
    assert reply.get("payload", {}).get("kind") != "ack"


def test_a_message_to_an_offline_device_is_resent_when_it_comes_back(gateway, watch_id):
    async def send():
        return await a2a.send(watch_id, a2a.Kind.DELEGATE_GOAL, {"goal": "看看日程"})

    env, sent = gateway.portal.call(send)
    assert sent is False, "设备还没连上:没送出去"
    assert a2a.link_for(watch_id).unacked() == [env], "但留在发件箱里"

    mine = _device_link(watch_id)
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id)  # 登记时中心补发未确认的
        frame = _recv(ws)
        assert frame.get("type") == "a2a" and frame["payload"]["msg_id"] == env.msg_id, frame
        deliver, ack = mine.accept(a2a.Envelope.from_dict(frame["payload"]))
        assert [e.body for e in deliver] == [{"goal": "看看日程"}]
        ws.send_json(ack.to_aip_frame(watch_id))
        assert _eventually(lambda: a2a.link_for(watch_id).unacked() == [])


def test_the_protocol_gate_knows_the_frame():
    from contracts.cross_repo_schema_version_gate import REQUIRED_AIP_MESSAGE_TYPES

    assert "a2a" in REQUIRED_AIP_MESSAGE_TYPES


def test_a2a_means_only_this_the_hybrid_executors_direct_api_tier_is_called_api_direct():
    """代码里原先另一个「A2A」是混合执行里「直接调应用的 API / MCP」那一级,和 Agent 之间的通话撞名。

    改叫「API 直调」;旧调用方传的 ``"a2a"`` 照旧认成这一级。
    """
    from core.hybrid_executor import ExecutionLevel

    assert "A2A" not in ExecutionLevel.__members__
    assert ExecutionLevel("a2a") is ExecutionLevel.API_DIRECT
    assert ExecutionLevel.API_DIRECT.value == "api_direct"
