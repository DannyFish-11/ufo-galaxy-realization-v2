"""手机加入:中心派一个桥接 Agent 过去,手机的本地上下文并进中心,手机上的对话就是和中心智能体的对话。

跨设备整体方案阶段 3。全程走真实的规范设备入口(``/ws/device``),帧形状与 ufo-galaxy-android 一致:
先 ``auth``(配对 / 网关令牌),再 ``device_register``(``device_type="Android_Agent"``),再
``capability_report``;之后中心与手机之间说话走对外 A2A(``core/a2a_link.py``)。手机那一端的行为与
安卓 ``BridgeAgentRuntime``(``BridgeAgentRuntimeTest``)是同一组场景。
"""

from __future__ import annotations

import time
import uuid

import pytest

from core import a2a_link as a2a
from core import phone_bridge
from tests.test_watch_reaches_the_central_agent import (  # noqa: F401 — 夹具与真实入口共用一份
    STATIC_TOKEN,
    _connect,
    _eventually,
    _recv,
    _register,
    _watch_capability_report_frame,
    gateway,
    watch_id,
)


@pytest.fixture(autouse=True)
def _fresh():
    a2a.reset_links()
    phone_bridge.reset_bridges()
    yield
    a2a.reset_links()
    phone_bridge.reset_bridges()


@pytest.fixture
def phone_id():
    return f"Google_Pixel_9-{uuid.uuid4().hex[:8]}"


def _now():
    return int(time.time() * 1000)


def _phone_auth(device_id):
    # shared-protocol AuthMessage:令牌在顶层
    return {
        "type": "auth",
        "token": STATIC_TOKEN,
        "device_id": device_id,
        "device_type": "android",
        "protocol_version": "3.0",
    }


def _phone_register(device_id):
    # GalaxyWebSocketClient.sendHandshake 第 1 步
    return {
        "type": "device_register",
        "protocol": "AIP/1.0",
        "version": "3.0",
        "device_id": device_id,
        "device_type": "Android_Agent",
        "trace_id": uuid.uuid4().hex,
        "timestamp": _now(),
        "source_runtime_posture": "join_runtime",
    }


def _phone_capability_report(device_id):
    # GalaxyWebSocketClient.sendHandshake 第 2 步
    return {
        "type": "capability_report",
        "version": "3.0",
        "platform": "android",
        "device_id": device_id,
        "device_type": "Android_Agent",
        "timestamp": _now(),
        "supported_actions": ["screen_capture", "app_control", "notification", "sms"],
        "action_descriptions": {
            "screen_capture": "截一张手机当前屏幕",
            "app_control": "打开、切换或关闭手机上的应用",
            "notification": "在手机上弹一条通知",
            "sms": "给联系人发短信",
        },
        "capabilities": ["goal_execution", "local_model"],
        "metadata": {"goal_execution_enabled": True, "cross_device_enabled": True},
        "bridge_agent": "bridge/1",  # 新版 App 声明能装桥接 Agent(BridgeAgentRuntime.BRIDGE_VERSION)
    }


def _until(ws, pred, timeout=8.0):
    """读帧直到 ``pred(frame)``;返回那一帧(超时返回 ``{}``)。"""
    end = time.time() + timeout
    while time.time() < end:
        m = _recv(ws, timeout=max(0.2, end - time.time()))
        if m.get("__timeout__"):
            return {}
        if pred(m):
            return m
    return {}


def _a2a_kind(kind):
    return lambda m: m.get("type") == "a2a" and m.get("payload", {}).get("kind") == kind


class _Phone:
    """手机那一端的桥接 Agent(只用到协议这一层;安卓 BridgeAgentRuntime 同语义)。"""

    def __init__(self, ws, device_id):
        self.ws, self.id, self.link = ws, device_id, None

    def join(self):
        self.ws.send_json(_phone_auth(self.id))
        assert _until(self.ws, lambda m: m.get("type") == "auth_ok"), "认证没回 auth_ok"
        self.ws.send_json(_phone_register(self.id))
        ack = _until(self.ws, lambda m: m.get("type") == "device_register_ack", timeout=30.0)
        assert ack.get("success") is True, ack
        self.ws.send_json(_phone_capability_report(self.id))
        return self.take(a2a.Kind.AGENT_DISPATCH)

    def take(self, kind, timeout=8.0):
        """等中心发来某类消息,收下(回确认),返回信封。"""
        frame = _until(self.ws, _a2a_kind(kind), timeout)
        assert frame, f"没等到中心的 {kind}"
        env = a2a.Envelope.from_dict(frame["payload"])
        if self.link is None:
            self.link = a2a.Link(env.session_id, a2a.agent_id_for(self.id), a2a.CENTER_AGENT)
        deliver, ack = self.link.accept(env)
        if ack is not None:
            self.ws.send_json(ack.to_aip_frame(self.id))
        return env

    def say(self, kind, body=None, **kw):
        env = self.link.make(kind, body or {}, **kw)
        self.ws.send_json(env.to_aip_frame(self.id))
        return env

    def install(self, dialog=None):
        dialog = dialog or [
            {"role": "user", "text": "帮我订明早七点去公司的车"},
            {"role": "assistant", "text": "好,我先看看滴滴"},
        ]
        self.say(a2a.Kind.AGENT_INSTALLED, {"runtime": "android", "bridge_version": "bridge/1", "resumed": False})
        self.say(
            a2a.Kind.CONTEXT_HANDOFF,
            {
                "dialog": dialog,
                "loop_progress": {"step": 2, "total": 5, "action": "打开滴滴"},
                "trajectory": [{"action": "查天气", "status": "success", "steps": 3}],
            },
        )
        assert _eventually(lambda: phone_bridge.bridge_state(self.id)["installed"]), "中心没记下装好了"
        # 交接是按帧顺序处理的:等它整段落进会话再往下走(进程里第一次记对话要先加载记忆的嵌入模型,慢)
        assert _eventually(lambda: phone_bridge.bridge_state(self.id)["handoff_turns"] >= len(dialog), timeout=30.0)
        assert _eventually(
            lambda: dialog[-1]["text"] in _session_texts(self.id), timeout=30.0
        ), "交接过来的对话没落进中心的会话"


def _session_texts(device_id):
    from core.session_memory_facade import get_session_context

    return [str(t.get("content")) for t in get_session_context(phone_bridge.bridge_session_id(device_id), max_turns=50)]


# ── 登记:手机的凭证在连接上,不在登记帧里 ──────────────────────────────────────
#
# 安卓先发 auth(令牌在顶层)、再发不带令牌的 device_register;OkHttp 握手头里也带着 Bearer。
# 此前登记只认帧里的令牌,认证开着时真手机永远登记不上(INGRESS_AUTHENTICATION_FAILED)。


def _register_ack(ws, device_id):
    ws.send_json(_phone_register(device_id))
    return _until(ws, lambda m: m.get("type") == "device_register_ack", timeout=30.0)


def test_a_phone_that_authenticated_on_the_connection_can_register(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        ws.send_json(_phone_auth(phone_id))
        assert _until(ws, lambda m: m.get("type") == "auth_ok")
        ack = _register_ack(ws, phone_id)
    assert ack.get("success") is True, ack


def test_a_phone_whose_handshake_carries_the_token_can_register(gateway, phone_id):
    headers = {"X-Device-ID": phone_id, "Authorization": f"Bearer {STATIC_TOKEN}"}
    with gateway.websocket_connect(f"/ws/device/{phone_id}", headers=headers) as ws:
        ack = _register_ack(ws, phone_id)
    assert ack.get("success") is True, ack


def test_a_connection_with_no_credential_still_cannot_register(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        ws.send_json({**_phone_auth(phone_id), "token": "not-a-real-token"})
        assert _until(ws, lambda m: str(m.get("type", "")).startswith("auth_"))
        ack = _register_ack(ws, phone_id)
    assert ack.get("success") is False and ack.get("error_code") == "INGRESS_AUTHENTICATION_FAILED", ack


# ── 接入握手 ────────────────────────────────────────────────────────────────────


def test_a_phone_that_reports_its_capabilities_gets_a_bridge_agent(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        dispatch = _Phone(ws, phone_id).join()
    body = dispatch.body
    assert dispatch.session_id == phone_bridge.bridge_session_id(phone_id)
    assert dispatch.to_agent == a2a.agent_id_for(phone_id)
    assert body["bridge_version"] == phone_bridge.BRIDGE_VERSION
    assert body["conversation"]["source"] == "device_chat"
    does = {t["name"]: t["does"] for t in body["tools"]}
    assert does.get("screen_capture") == "截一张手机当前屏幕", "桥接 Agent 知道手机自己报的动作和说明"
    assert "sms" in body["confirm_actions"]


def test_an_older_phone_app_that_does_not_declare_the_bridge_gets_none(gateway, phone_id):
    """旧版 App 不认 a2a 帧、也不会回确认:派过去只会留在发件箱里,每次重连补发一遍。不声明就不派。"""
    with _connect(gateway, phone_id) as ws:
        ws.send_json(_phone_auth(phone_id))
        assert _until(ws, lambda m: m.get("type") == "auth_ok")
        assert _register_ack(ws, phone_id).get("success") is True
        report = _phone_capability_report(phone_id)
        report.pop("bridge_agent")
        ws.send_json(report)
        got = _until(ws, _a2a_kind(a2a.Kind.AGENT_DISPATCH), timeout=2.5)
    assert got == {}
    assert a2a.links_of(phone_id) == [] or all(not l.unacked() for l in a2a.links_of(phone_id))


def test_the_declaration_is_read_the_same_way_the_phone_writes_it():
    assert phone_bridge.declares_bridge_support({"bridge_agent": "bridge/1"})
    assert phone_bridge.declares_bridge_support({"payload": {"bridge_agent": "bridge/2"}}), "同一大版本的新小版本也认"
    assert not phone_bridge.declares_bridge_support({})
    assert not phone_bridge.declares_bridge_support({"bridge_agent": "other/1"})


def test_a_watch_gets_no_bridge_agent(gateway, watch_id):
    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id, STATIC_TOKEN)
        ws.send_json(_watch_capability_report_frame(watch_id))
        got = _until(ws, _a2a_kind(a2a.Kind.AGENT_DISPATCH), timeout=2.5)
    assert got == {}, "手表只是入口和出口,不接 Agent"


# ── 上交上下文 ──────────────────────────────────────────────────────────────────


def test_the_phones_local_context_lands_in_its_session_at_the_center(gateway, phone_id):
    with _connect(gateway, phone_id) as ws:
        phone = _Phone(ws, phone_id)
        phone.join()
        phone.install()
        assert _eventually(lambda: "帮我订明早七点去公司的车" in _session_texts(phone_id))
        texts = _session_texts(phone_id)
        assert "好,我先看看滴滴" in texts
        assert any("第 2/5 步" in t and "打开滴滴" in t for t in texts), texts
        # 重连后手机又交了一遍同样的对话:不重复记
        phone.say(a2a.Kind.CONTEXT_HANDOFF, {"dialog": [{"role": "user", "text": "帮我订明早七点去公司的车"}]})
        time.sleep(0.5)
    assert _session_texts(phone_id).count("帮我订明早七点去公司的车") == 1


# ── 对话桥接 ────────────────────────────────────────────────────────────────────


def test_what_the_person_says_on_the_phone_reaches_the_central_agent_and_the_answer_comes_back(
    gateway, phone_id, monkeypatch
):
    import core.desktop_presence_runtime as dpr

    calls = []

    class _Runtime:
        async def handle_request(self, message, **kw):
            calls.append((message, kw))
            return {"success": True, "response": "订好了,明早七点楼下上车"}

    monkeypatch.setattr(dpr, "get_desktop_presence_runtime", lambda: _Runtime())
    with _connect(gateway, phone_id) as ws:
        phone = _Phone(ws, phone_id)
        phone.join()
        phone.install()
        said = phone.say(a2a.Kind.CONVERSATION, {"role": "user", "text": "就订七点的"})
        reply = phone.take(a2a.Kind.CONVERSATION, timeout=10.0)
    assert reply.body["text"] == "订好了,明早七点楼下上车"
    assert reply.body["in_reply_to"] == said.msg_id and reply.body["success"] is True
    message, kw = calls[0]
    assert message == "就订七点的"
    assert kw["source"] == "device_chat", "手机上说的话算人发起的回合,不进电脑三态"
    assert kw["session_id"] == phone_bridge.bridge_session_id(phone_id), "和交接过来的上下文是同一个会话"
    assert kw["device_id"] == phone_id


def test_bridge_chat_is_a_remote_human_request():
    from core.device_onboarding.conversation import HUMAN_REQUEST_SOURCES
    from core.presence_line import REMOTE_SOURCES

    assert phone_bridge.BRIDGE_CHAT_SOURCE in REMOTE_SOURCES
    assert phone_bridge.BRIDGE_CHAT_SOURCE in HUMAN_REQUEST_SOURCES


# ── 委派整段目标 ─────────────────────────────────────────────────────────────────


def test_the_agent_can_hand_a_whole_goal_to_the_phone(gateway, phone_id):
    from core.device_onboarding.agent_tools import devices_tools_for_agent, dispatch_devices_tool

    assert "devices__delegate" in {t["function"]["name"] for t in devices_tools_for_agent()}
    with _connect(gateway, phone_id) as ws:
        phone = _Phone(ws, phone_id)
        phone.join()
        phone.install()

        async def _delegate():
            return await dispatch_devices_tool(
                "delegate",
                {"device_id": phone_id, "goal": "打开滴滴叫车到公司", "constraints": ["不要付款"], "timeout_s": 20},
            )

        pending = gateway.portal.start_task_soon(_delegate)
        goal = phone.take(a2a.Kind.DELEGATE_GOAL, timeout=10.0)
        assert goal.body == {"goal": "打开滴滴叫车到公司", "constraints": ["不要付款"]}
        phone.say(a2a.Kind.DELEGATE_PROGRESS, {"step": 1, "total": 3}, task_id=goal.task_id, ack_required=False)
        phone.say(a2a.Kind.DELEGATE_RESULT, {"success": True, "summary": "已叫车,司机 3 分钟到"}, task_id=goal.task_id)
        out = pending.result(timeout=15)
    assert out["success"] is True and out["summary"] == "已叫车,司机 3 分钟到"
    assert out["progress"] == [{"step": 1, "total": 3}]


def test_delegating_to_a_device_that_cannot_take_an_agent_is_refused_up_front(gateway, watch_id, phone_id):
    from core.device_onboarding.agent_tools import dispatch_devices_tool

    with _connect(gateway, watch_id) as ws:
        _register(ws, watch_id, STATIC_TOKEN)
        out = gateway.portal.call(dispatch_devices_tool, "delegate", {"device_id": watch_id, "goal": "看看日程"})
    assert out["success"] is False and "can_take_agent" in out["error"]
    with _connect(gateway, phone_id) as ws:
        _Phone(ws, phone_id).join()  # 派了,但手机还没回「装好了」(旧版 App)
        out = gateway.portal.call(dispatch_devices_tool, "delegate", {"device_id": phone_id, "goal": "叫车"})
    assert out["success"] is False and "桥接 Agent" in out["error"]


# ── 交还 ────────────────────────────────────────────────────────────────────────


def test_turning_cross_device_off_on_the_phone_returns_the_context(gateway, phone_id):
    from core.session_memory_facade import record_session_turn

    with _connect(gateway, phone_id) as ws:
        phone = _Phone(ws, phone_id)
        phone.join()
        phone.install()

        async def _answer():
            await record_session_turn(
                conversation_session_id=phone_bridge.bridge_session_id(phone_id),
                role="assistant",
                content="车订好了,明早七点楼下",
                device_id=phone_id,
            )

        gateway.portal.call(_answer)
        phone.say(a2a.Kind.CONTEXT_RETURN, {"request": True})
        back = phone.take(a2a.Kind.CONTEXT_RETURN)
    assert back.body["summary"] == "车订好了,明早七点楼下"
    assert back.body["open_items"] == []
    assert phone_bridge.bridge_state(phone_id)["installed"] is False


def test_the_device_card_says_whether_the_bridge_agent_is_on(gateway, phone_id):
    from core.device_onboarding.agent_tools import dispatch_devices_tool

    with _connect(gateway, phone_id) as ws:
        phone = _Phone(ws, phone_id)
        phone.join()
        phone.install()
        cards = gateway.portal.call(dispatch_devices_tool, "list", {})
    card = next(m for m in cards["members"] if m["device_id"] == phone_id)
    assert card["can_take_agent"] is True
    assert card["agent_installed"] is True
