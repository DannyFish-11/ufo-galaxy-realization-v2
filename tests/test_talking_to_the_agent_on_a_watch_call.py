"""实时语音里「边说边做」:跟智能体打电话(手表)、在电脑旁跟它说话,就像跟人说话 —— 说一声让它去做,
话照说,做完它告诉你。

钉住的性质:

* 三家实时接口的帧:OpenAI / Gemini 声明工具、解出工具调用、交回结果、插一条系统消息;阶跃不声明(没核实);
* 事情怎么交过去:手表通话里云端 OpenAI / Gemini 自己调工具交;阶跃、本地服务、电脑自己的实时语音由智能体
  旁听;配不上也绝不打不通;只有 ``GALAXY_VOICE_CALL_AGENT=0`` 才只聊;
* 旁听:人说完一句,快档模型判做 / 停 / 问 / 在聊;要做的交**人的原话**;附和、正在回答提问的话不判;
  判不了(没有模型、出错)当在聊;
* 交给智能体以后**立刻**回「已经开始做」(模型接着说话),智能体在后台做;做完在没人说话时插【回报】;
  进展、停下;挂断后做完的事作为通知送到手表;手表通话界面上显示「在做 / 做完了」;
* 智能体在问:问题进通话;问出口之后人的原话才算回答;普通问题按原话答;高风险的批准嘴上说不算、
  说不要算拒绝;有选项却没说中的话不当回答;
* 来源 ``wear_call``:不进电脑三态,也不算人亲口说的(交过去的是语音模型的转述);
* 真 WebRTC 手表 + 真通话路由 + 跑在本地真 WebSocket 上的 OpenAI 实时协议端:说一句 → 工具调用 → 结果交回
  → 智能体做完 → 回报插回通话;本地服务那一路:说一句 → 旁听交过去 → 回报插回通话;
* 电脑自己的实时语音(真 ``VoiceLoop`` + 本地真 WebSocket):旁听交过去(来源 ``voice_duplex``,不在对话主线上重记),
  回报插回实时会话;这一路的回复不再由电脑另外念一遍。
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from core import voice_call_agent as vca
from core.voice_duplex_adapters import DuplexEvent, DuplexEventType, get_adapter
from core.voice_duplex_session import DuplexSession, DuplexSessionConfig

TOOLS = vca.CALL_TOOLS


def _cfg(provider: str = "openai_realtime", url: str = "wss://api.openai.com/v1/realtime", **kw: Any):
    return DuplexSessionConfig(url=url, api_key="k", provider=provider, **kw)


def ev(kind: str, **kw: Any) -> DuplexEvent:
    return DuplexEvent(DuplexEventType(kind), **kw)


# ---------------------------------------------------------------------------
# 一、帧
# ---------------------------------------------------------------------------


def test_openai_declares_the_tools_and_decodes_a_call_once():
    a = get_adapter("openai_realtime")
    session = a.session_update(_cfg(tools=TOOLS))["session"]
    assert [t["name"] for t in session["tools"]] == ["agent_do", "agent_status", "agent_stop"]
    assert session["tools"][0]["type"] == "function" and session["tool_choice"] == "auto"
    assert "tools" not in a.session_update(_cfg())["session"], "没配工具就不声明"

    item = {"type": "function_call", "call_id": "c1", "name": "agent_do", "arguments": '{"what": "提醒我喝水"}'}
    got = a.decode({"type": "response.output_item.done", "item": item})
    assert got.type is DuplexEventType.TOOL_CALL
    assert (got.tool_call_id, got.tool_name, got.tool_args) == ("c1", "agent_do", {"what": "提醒我喝水"})
    assert a.decode({"type": "response.function_call_arguments.done", "call_id": "c1", "arguments": "{}"}) is None
    assert a.decode({"type": "response.output_item.done", "item": {"type": "message"}}) is None
    bad = a.decode({"type": "response.output_item.done", "item": {**item, "arguments": "{not json"}})
    assert bad.tool_args == {"_raw": "{not json"}, "解不开的参数原样留着,不丢"


def test_openai_hands_back_a_result_and_inserts_a_system_note():
    a = get_adapter("openai_realtime")
    out, create = a.tool_result_frames("c1", "agent_do", {"ok": True, "task_id": "t1"})
    assert out["item"]["type"] == "function_call_output" and out["item"]["call_id"] == "c1"
    assert json.loads(out["item"]["output"]) == {"ok": True, "task_id": "t1"}
    assert create == {"type": "response.create"}, "交回结果后要让它接着说"
    note, create = a.note_frames("【回报】做完了")
    assert note["item"]["role"] == "system" and note["item"]["content"][0]["text"] == "【回报】做完了"
    assert create == {"type": "response.create"}


def test_gemini_declares_functions_and_decodes_several_calls_in_one_frame():
    a = get_adapter("gemini_live")
    setup = a.session_update(_cfg("gemini_live", model="m", tools=TOOLS))["setup"]
    decl = setup["tools"][0]["functionDeclarations"]
    assert [d["name"] for d in decl] == ["agent_do", "agent_status", "agent_stop"]
    assert decl[0]["parameters"]["type"] == "OBJECT" and decl[0]["parameters"]["properties"]["what"]["type"] == "STRING"
    assert setup["inputAudioTranscription"] == {}, "要知道人说了什么(上下文、手表字幕)"
    assert "tools" not in a.session_update(_cfg("gemini_live", model="m"))["setup"]

    frame = {
        "toolCall": {
            "functionCalls": [
                {"id": "g1", "name": "agent_do", "args": {"what": "关灯"}},
                {"id": "g2", "name": "agent_status", "args": {}},
            ]
        }
    }
    got = a.decode_all(frame)
    assert [(e.tool_call_id, e.tool_name, e.tool_args) for e in got] == [
        ("g1", "agent_do", {"what": "关灯"}),
        ("g2", "agent_status", {}),
    ]
    assert a.decode_all({"toolCallCancellation": {"ids": ["g1"]}}) == []
    (resp,) = a.tool_result_frames("g1", "agent_do", {"ok": True})
    assert resp == {"toolResponse": {"functionResponses": [{"id": "g1", "name": "agent_do", "response": {"ok": True}}]}}
    (note,) = a.note_frames("【回报】做完了")
    assert note["clientContent"]["turnComplete"] is True


def test_step_never_declares_tools():
    session = get_adapter("step_realtime").session_update(_cfg("step_realtime", voice="v", tools=TOOLS))["session"]
    assert "tools" not in session and "tool_choice" not in session


# ---------------------------------------------------------------------------
# 二、一通电话能不能把事交出去
# ---------------------------------------------------------------------------


def test_how_work_reaches_the_agent(monkeypatch):
    for provider, url in (
        ("openai_realtime", "wss://api.openai.com/v1/realtime"),
        ("gemini_live", "wss://g.example/ws"),
    ):
        cfg = _cfg(provider, url)
        assert vca.configure_call_session(cfg) == "tools"
        assert cfg.tools and "agent_do" in cfg.instructions

    step = _cfg("step_realtime", "wss://api.stepfun.com/v1/realtime")
    assert vca.configure_call_session(step) == "listen", "不会调工具的不是只聊:智能体旁听"
    assert step.tools == [] and "执行部分在旁边听着" in step.instructions and "【回报】" in step.instructions

    local = _cfg(url="ws://127.0.0.1:32550/v1/realtime")
    assert vca.configure_call_session(local) == "listen", "本地服务收不收 tools 没法预知:不塞 tools,旁听"
    assert local.tools == []
    desktop = _cfg()
    assert vca.configure_call_session(desktop, where="desktop") == "listen", "电脑上智能体自己听得见人"
    assert desktop.tools == [] and "电脑旁" in desktop.instructions
    monkeypatch.setenv("GALAXY_REALTIME_TOOLS", "1")
    assert vca.configure_call_session(_cfg(url="ws://127.0.0.1:32550/v1/realtime")) == "tools"

    class Frozen:
        __slots__ = ("provider", "url")

        def __init__(self) -> None:
            self.provider, self.url = "openai_realtime", "wss://x"

    assert vca.configure_call_session(Frozen()) == "listen", "配不上就不声明工具、旁听,绝不让电话打不通"
    assert vca.configure_call_session(SimpleNamespace(sample_rate=16000)) == "listen"

    monkeypatch.setenv("GALAXY_VOICE_CALL_AGENT", "0")
    off = _cfg()
    assert vca.configure_call_session(off) == "" and off.tools == [] and "没法替他做事" in off.instructions


def test_a_call_from_a_phone_is_told_apart_from_a_watch(monkeypatch):
    records = {
        "watch-1": SimpleNamespace(form_factor="watch", aip_device_type="android_wear", device_type=None),
        "phone-1": SimpleNamespace(form_factor="phone", aip_device_type="android_phone", device_type=None),
    }
    monkeypatch.setattr(
        "core.unified.device_manager.get_unified_device_manager",
        lambda: SimpleNamespace(get_device=lambda did: records.get(did)),
    )
    assert vca.device_kind("watch-1") == "watch", "手表报的类型里也有 android,先认手表"
    assert vca.device_kind("phone-1") == "phone"
    assert vca.device_kind("unknown") == "watch", "认不出按手表:通话本来是给手表做的"

    phone = _cfg()
    assert vca.configure_call_session(phone, where="phone") == "tools"
    assert "手机上和你通话" in phone.instructions and "手表" not in phone.instructions
    assert vca.CALL_DEVICES["phone"]["source"] == vca.PHONE_CALL_SOURCE
    assert vca.CALL_DEVICES["phone"]["notify"] == "notification", "手机报的弹通知动作叫 notification"


def test_the_call_source_stays_off_the_desktop_and_is_not_the_persons_own_words():
    from core.device_onboarding.conversation import HUMAN_REQUEST_SOURCES
    from core.presence_line import REMOTE_SOURCES

    for source in (vca.CALL_SOURCE, vca.PHONE_CALL_SOURCE):
        assert source in REMOTE_SOURCES
        assert source not in HUMAN_REQUEST_SOURCES, "交过去的是语音模型的转述,对话里的确认不能被它满足"


# ---------------------------------------------------------------------------
# 三、真 WebSocket 上的会话
# ---------------------------------------------------------------------------


class FakeRealtimeServer:
    """跑在本地真 WebSocket 上、说 OpenAI 实时协议的服务端:记下收到的帧,按测试的吩咐发帧。"""

    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self.conns: List[Any] = []
        self.port = 0
        self._server: Any = None

    async def start(self) -> "FakeRealtimeServer":
        import websockets

        async def handler(ws: Any) -> None:
            self.conns.append(ws)
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                if msg.get("type") == "session.update":
                    await ws.send(json.dumps({"type": "session.updated", "session": msg.get("session", {})}))

        self._server = await websockets.serve(handler, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self

    async def send(self, *frames: Dict[str, Any]) -> None:
        for f in frames:
            await self.conns[-1].send(json.dumps(f))

    def got(self, type_: str) -> List[Dict[str, Any]]:
        return [m for m in self.received if m.get("type") == type_]

    async def wait_for(self, pred: Any, timeout: float = 5.0) -> List[Dict[str, Any]]:
        end = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < end:
            hit = [m for m in self.received if pred(m)]
            if hit:
                return hit
            await asyncio.sleep(0.02)
        raise AssertionError(f"等不到;收到的是 {[m.get('type') for m in self.received]}")

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()


def _fc(call_id: str, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    item = {
        "type": "function_call",
        "call_id": call_id,
        "name": name,
        "arguments": json.dumps(args, ensure_ascii=False),
    }
    return {"type": "response.output_item.done", "item": item}


async def test_a_real_session_declares_tools_surfaces_calls_and_sends_results_back():
    srv = await FakeRealtimeServer().start()
    sess = DuplexSession(_cfg(url=f"ws://127.0.0.1:{srv.port}/v1/realtime", tools=TOOLS))
    try:
        assert await sess.connect()
        (upd,) = await srv.wait_for(lambda m: m.get("type") == "session.update")
        assert [t["name"] for t in upd["session"]["tools"]] == ["agent_do", "agent_status", "agent_stop"]
        await srv.send(_fc("c9", "agent_do", {"what": "关客厅的灯"}))
        while True:
            got = await sess.next_event(timeout=5)
            assert got is not None
            if got.type is DuplexEventType.TOOL_CALL:
                break
        assert (got.tool_call_id, got.tool_args) == ("c9", {"what": "关客厅的灯"})
        assert sess.supports_tools
        assert await sess.send_tool_result("c9", "agent_do", {"ok": True})
        assert await sess.send_note("【回报】灯关了")
        await srv.wait_for(lambda m: m.get("type") == "conversation.item.create" and m["item"]["type"] == "message")
        outs = [m for m in srv.got("conversation.item.create") if m["item"]["type"] == "function_call_output"]
        assert outs and outs[0]["item"]["call_id"] == "c9"
        assert len(srv.got("response.create")) == 2
    finally:
        await sess.close()
        await srv.stop()


# ---------------------------------------------------------------------------
# 四、边说边做
# ---------------------------------------------------------------------------


class FakeSession:
    def __init__(self, tools: bool = True) -> None:
        self.config = SimpleNamespace(tools=list(TOOLS) if tools else [])
        self.results: List[tuple] = []
        self.notes: List[str] = []

    async def send_tool_result(self, call_id: str, name: str, output: Dict[str, Any]) -> bool:
        self.results.append((call_id, name, output))
        return True

    async def send_note(self, text: str) -> bool:
        self.notes.append(text)
        return True


class FakeRuntime:
    """智能体:记下交过来的事;每件事等测试说「做完」才返回。"""

    def __init__(self, reply: str = "做好了", success: bool = True) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.release = asyncio.Event()
        self.reply, self.success = reply, success

    async def handle_request(self, **kw: Any) -> Dict[str, Any]:
        self.calls.append(kw)
        await self.release.wait()
        return {"success": self.success, "response": self.reply}


@pytest.fixture
def agent(monkeypatch):
    runtime = FakeRuntime()
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)
    shown: List[tuple] = []
    a = vca.CallAgent("watch-1", "call_1", FakeSession(), send_event=lambda e, t, err: shown.append((e, t)))
    a.runtime, a.shown = runtime, shown  # type: ignore[attr-defined]
    return a


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_handing_work_over_answers_at_once_and_the_agent_works_in_the_background(agent):
    await agent.on_event(ev("final_transcript", text="帮我提醒三点开会"))
    consumed = await agent.on_event(
        ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "三点提醒开会"})
    )
    assert consumed, "工具调用不转给设备"
    ((call_id, name, out),) = agent.session.results
    assert call_id == "c1" and out["ok"] and out["task_id"], "立刻回「已经开始做」,模型接着说话"
    await _settle()
    (req,) = agent.runtime.calls
    assert req["message"] == "三点提醒开会" and req["source"] == "wear_call" and req["device_id"] == "watch-1"
    assert req["session_id"] == "wear_call:watch-1", "同一块手表的通话共用一条会话,智能体记得之前说过的"
    assert {"role": "user", "content": "帮我提醒三点开会"} in req["context"], "人的原话作为上下文带上"
    assert agent.shown[-1] == ("agent_task", "在做:三点提醒开会")
    assert agent.session.notes == [], "还没做完,不报"


async def test_the_report_waits_until_nobody_is_talking(agent):
    await agent.on_event(ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "关灯"}))
    await agent.on_event(ev("assistant_text_delta", text="好,我去关"))
    agent.runtime.release.set()
    await _settle()
    assert agent.session.notes == [], "模型正在说,不插嘴"
    await agent.on_event(ev("user_speech_started"))
    await agent.on_event(ev("response_done"))
    assert agent.session.notes == [], "人正在说,不插嘴"
    await agent.on_event(ev("user_speech_stopped"))
    (note,) = agent.session.notes
    assert note.startswith("【回报】") and "关灯" in note and "做好了" in note
    assert agent.shown[-1] == ("agent_task", "做完了:关灯")


async def test_progress_and_stopping(agent):
    await agent.on_event(ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "整理下载文件夹"}))
    await _settle()
    await agent.on_event(ev("tool_call", tool_call_id="c2", tool_name="agent_status", tool_args={}))
    status = agent.session.results[-1][2]
    assert status["tasks"][0]["what"] == "整理下载文件夹" and status["tasks"][0]["state"] == "running"
    await agent.on_event(ev("tool_call", tool_call_id="c3", tool_name="agent_stop", tool_args={}))
    assert agent.session.results[-1][2]["stopped"] == [status["tasks"][0]["task_id"]]
    await _settle()
    assert next(iter(agent.tasks.values())).state == "stopped"
    assert agent.shown[-1] == ("agent_task", "停下了:整理下载文件夹")


async def test_a_failure_is_reported_as_a_failure(agent):
    agent.runtime.success, agent.runtime.reply = False, "找不到那台打印机"
    await agent.on_event(ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "打印报告"}))
    agent.runtime.release.set()
    await _settle()
    assert "没做成" in agent.session.notes[0] and "找不到那台打印机" in agent.session.notes[0]


async def test_an_agent_without_a_model_is_reported_as_not_done(agent, monkeypatch):
    async def _no_model(**kw: Any) -> Dict[str, Any]:
        return {"success": True, "response": "还没有可用的 AI 服务", "metadata": {"model": "none"}}

    monkeypatch.setattr(agent.runtime, "handle_request", _no_model)
    await agent.on_event(ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "订机票"}))
    await _settle()
    assert "没做成" in agent.session.notes[0] and "还没有可用的 AI 服务" in agent.session.notes[0]
    assert agent.shown[-1] == ("agent_task", "没做成:订机票"), "只回了一句说明的,不能报成做完了"


async def test_work_finished_after_hanging_up_arrives_as_a_watch_notification(agent, monkeypatch):
    sent: List[tuple] = []

    async def _send(device_id: str, msg: Dict[str, Any]) -> bool:
        sent.append((device_id, msg))
        return True

    monkeypatch.setattr("core.routes._shared.connection_manager.send_to_device", _send)
    await agent.on_event(ev("tool_call", tool_call_id="c1", tool_name="agent_do", tool_args={"what": "查明天的天气"}))
    agent.on_call_closed()
    agent.runtime.release.set()
    await _settle()
    assert agent.session.notes == []
    ((device_id, msg),) = sent
    assert device_id == "watch-1" and msg["type"] == "command" and msg["command"] == "notify"
    assert "查明天的天气" in msg["params"]["text"] and len(msg["params"]["text"]) <= 500


async def test_a_note_that_never_gets_a_reply_does_not_block_the_next_one(agent, monkeypatch):
    agent._notes.append(("【回报】一", ""))
    await agent._flush_notes()
    agent._notes.append(("【回报】二", ""))
    await agent._flush_notes()
    assert agent.session.notes == ["【回报】一"], "等这一条的回复"
    monkeypatch.setattr(vca.time, "time", lambda: agent._note_sent_at + vca.NOTE_REPLY_WAIT_S + 1)
    await agent._flush_notes()
    assert agent.session.notes == ["【回报】一", "【回报】二"]


# ── 智能体在问 ─────────────────────────────────────────────────────────────


@pytest.fixture
def registry():
    from core.interaction.pending_decision_registry import get_pending_decision_registry

    reg = get_pending_decision_registry()
    yield reg
    for did in list(reg.pending_ids()):
        reg.cancel(did)


def _ask(agent, registry, options, urgency="normal"):
    rec = registry.register(options=[o["id"] for o in options], urgency=urgency, timeout_s=60)
    agent.on_decision(rec.decision_id, "要发给张三吗?", "刚写好的邮件", options, urgency)
    return rec


async def _asked(agent) -> None:
    await _settle()  # 插进通话
    await agent.on_event(ev("assistant_text_delta", text="要发给张三吗?"))
    await agent.on_event(ev("response_done"))  # 问出口了


async def _say(agent, words: str) -> None:
    await agent.on_event(ev("final_transcript", text=words))
    await agent.on_event(ev("assistant_text_delta", text="好的"))
    await agent.on_event(ev("response_done"))


YES_NO = [{"id": "approve", "label": "批准"}, {"id": "deny", "label": "不要"}]


async def test_the_question_is_asked_in_the_call_and_answered_by_voice(agent, registry):
    rec = _ask(agent, registry, YES_NO)
    await agent.on_event(ev("final_transcript", text="好"))  # 问出口之前听到的,不算
    await _asked(agent)
    assert agent.session.notes[0].startswith("【智能体在问】要发给张三吗?")
    assert not rec.future.done(), "问出口之前的话不是回答"
    await _say(agent, "好")
    outcome = rec.future.result()
    assert outcome.selected_option == "approve" and outcome.voice_input == "好" and outcome.source == "wear_call_voice"


async def test_naming_an_option_picks_it_and_unrelated_words_are_not_an_answer(agent, registry):
    rec = _ask(agent, registry, [{"id": "r", "label": "红色"}, {"id": "b", "label": "蓝色"}])
    await _asked(agent)
    await _say(agent, "等一下我想想")
    assert not rec.future.done(), "有选项却没说中、也没表态的话,不当回答"
    await _say(agent, "要蓝色的吧")
    assert rec.future.result().selected_option == "b"


async def test_an_open_question_takes_the_persons_own_words(agent, registry):
    rec = _ask(agent, registry, [])
    await _asked(agent)
    await _say(agent, "写周五下午三点")
    outcome = rec.future.result()
    assert outcome.selected_option is None and outcome.voice_input == "写周五下午三点"


async def test_a_high_risk_approval_needs_a_tap_but_saying_no_refuses(agent, registry):
    rec = _ask(agent, registry, YES_NO, urgency="high")
    await _asked(agent)
    assert "在手表上点「批准」" in agent.session.notes[0]
    await _say(agent, "好")
    assert not rec.future.done(), "高风险操作嘴上说好不算"
    await agent.on_event(ev("response_done"))  # 让【提醒】插进去
    assert any(n.startswith("【提醒】") for n in agent.session.notes)
    await _say(agent, "不要")
    assert rec.future.result().selected_option == "deny"


async def test_a_question_answered_on_the_watch_is_dropped_from_the_call(agent, registry):
    rec = _ask(agent, registry, YES_NO)
    await _asked(agent)
    registry.resolve(rec.decision_id, selected_option="deny", source="wear")
    await _say(agent, "好")
    assert rec.future.result().selected_option == "deny" and agent._asks == {}


async def test_asking_a_watch_that_is_on_a_call_reaches_the_call(monkeypatch, registry):
    from core.interaction.pending_decision_registry import OnTimeout, request_human_decision

    heard: List[tuple] = []
    call = SimpleNamespace(agent=SimpleNamespace(on_decision=lambda *a: heard.append(a)))
    monkeypatch.setattr(
        "core.voice_call_bridge.VoiceCallRegistry.get", lambda self, did: call if did == "watch-1" else None
    )

    async def _emit(device_id: str, message: Dict[str, Any]) -> None:
        return None

    task = asyncio.ensure_future(
        request_human_decision(
            title="要删吗?",
            options=YES_NO,
            urgency="high",
            on_timeout=OnTimeout.CANCEL,
            timeout_s=1,
            devices=["watch-1", "phone-1"],
            emit=_emit,
        )
    )
    await asyncio.sleep(0.05)
    assert heard and heard[0][1] == "要删吗?" and heard[0][4] == "high"
    await task


# ---------------------------------------------------------------------------
# 四之二、旁听(说话的模型不会调工具)
# ---------------------------------------------------------------------------


@pytest.fixture
def listener(monkeypatch):
    runtime = FakeRuntime()
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)
    heard: List[tuple] = []
    verdicts: Dict[str, str] = {}

    async def judge(text: str, context: List[Dict[str, str]], running: List[str]) -> str:
        heard.append((text, context, running))
        return verdicts.get(text, "")

    monkeypatch.setattr(vca, "_judge", judge)
    a = vca.CallAgent("watch-1", "call_1", FakeSession(tools=False))
    a.runtime, a.heard, a.verdicts = runtime, heard, verdicts  # type: ignore[attr-defined]
    return a


async def test_listening_hands_the_persons_own_words_to_the_agent(listener):
    assert listener.listening, "会话没声明工具:智能体旁听"
    listener.verdicts["帮我把客厅的灯关了"] = "do"
    await listener.on_event(ev("final_transcript", text="今天好累"))
    await listener.on_event(ev("final_transcript", text="帮我把客厅的灯关了"))
    await _settle()
    assert [h[0] for h in listener.heard] == ["今天好累", "帮我把客厅的灯关了"]
    assert listener.heard[1][1] == [{"role": "user", "content": "今天好累"}], "判的时候带上前面说的"
    (req,) = listener.runtime.calls
    assert req["message"] == "帮我把客厅的灯关了", "交过去的是人的原话"
    assert req["source"] == "wear_call"
    assert listener.session.notes == [], "在聊的那句没交,要做的还没做完"
    listener.runtime.release.set()
    await _settle()
    assert listener.session.notes[0].startswith("【回报】交给你做的「帮我把客厅的灯关了」做完了")


async def test_listening_leaves_backchannels_and_answers_alone(listener, registry):
    await listener.on_event(ev("final_transcript", text="嗯"))
    rec = _ask(listener, registry, [])
    await _asked(listener)
    await _say(listener, "写周五下午三点")
    await _settle()
    assert listener.heard == [], "附和不是在要什么;在回答智能体的提问时,话是回答,不是新的事"
    assert rec.future.result().voice_input == "写周五下午三点"


async def test_listening_stops_and_reports_progress(listener):
    listener.verdicts.update({"帮我订明天的会议室": "do", "做到哪了": "status", "算了不用了": "stop"})
    await listener.on_event(ev("final_transcript", text="帮我订明天的会议室"))
    await _settle()
    await listener.on_event(ev("final_transcript", text="做到哪了"))
    await _settle()
    assert listener.heard[-1][2] == ["帮我订明天的会议室"], "判的时候知道交出去了什么"
    assert listener.session.notes == ["【进展】「帮我订明天的会议室」在做"]
    await listener.on_event(ev("final_transcript", text="算了不用了"))
    await _settle()
    (task,) = listener.tasks.values()
    assert task.state == "stopped" and len(listener.runtime.calls) == 1


async def test_the_judge_uses_the_fast_tier_and_treats_no_model_as_chatting(monkeypatch):
    asked: List[Dict[str, Any]] = []
    reply = {"provider": "ollama", "content": "做"}

    class Authority:
        async def chat(self, messages: List[Dict[str, str]], **kw: Any) -> Any:
            asked.append({"messages": messages, **kw})
            if reply.get("raise"):
                raise RuntimeError("断了")
            return SimpleNamespace(provider=reply["provider"], content=reply["content"])

    monkeypatch.setattr("core.llm.route_authority.get_llm_route_authority", lambda: Authority())
    assert await vca._judge("帮我关灯", [{"role": "assistant", "content": "在呢"}], ["订会议室"]) == "do"
    assert asked[0]["task_type"] == "fast_response" and asked[0]["max_tokens"] <= 8
    prompt = asked[0]["messages"][-1]["content"]
    assert "助手:在呢" in prompt and "订会议室" in prompt and prompt.endswith("用户刚说:帮我关灯")
    reply["content"] = "停。"
    assert await vca._judge("别订了", [], ["订会议室"]) == "stop"
    reply["content"] = "不"
    assert await vca._judge("今天天气不错", [], []) == ""
    reply.update(provider="none", content="做")  # 降级说明是什么字都不算数
    assert await vca._judge("帮我关灯", [], []) == "", "一个模型都没有:判不了,当在聊"
    reply["raise"] = True
    assert await vca._judge("帮我关灯", [], []) == "", "出错也不能让通话出错"


# ---------------------------------------------------------------------------
# 五、通话的下行泵
# ---------------------------------------------------------------------------


class QueueSession:
    class config:  # noqa: N801
        sample_rate = 16000

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def events(self):
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        self.closed = True


async def test_the_call_feeds_the_agent_and_keeps_tool_calls_off_the_watch():
    from core.voice_call_bridge import VoiceCall, webrtc_available

    if webrtc_available() is not None:
        pytest.skip(webrtc_available())
    sent: List[str] = []
    seen: List[str] = []
    closed: List[bool] = []

    class Agent:
        async def on_event(self, e: Any) -> bool:
            seen.append(e.type.value)
            return e.type is DuplexEventType.TOOL_CALL

        def on_call_closed(self) -> None:
            closed.append(True)

    sess = QueueSession()
    call = VoiceCall("watch-1", sess, send_event=lambda e, t, err: sent.append(e))
    call.agent = Agent()
    call.start_downlink()
    for item in (
        ev("final_transcript", text="帮我关灯"),
        ev("tool_call", tool_name="agent_do"),
        ev("response_done"),
        None,
    ):
        sess.queue.put_nowait(item)
    await asyncio.sleep(0.1)
    assert seen == ["final_transcript", "tool_call", "response_done"]
    assert sent == ["final_transcript", "response_done"], "工具调用不转给手表"
    await call.close()
    assert closed == [True]


# ---------------------------------------------------------------------------
# 六、端到端:真 WebRTC 手表 + 真通话路由 + 本地真 WebSocket 上的 OpenAI 实时协议端
# ---------------------------------------------------------------------------


async def test_end_to_end_say_it_on_the_watch_and_hear_it_done(monkeypatch):
    from core.voice_call_bridge import get_call_registry, webrtc_available

    if webrtc_available() is not None:
        pytest.skip(webrtc_available())
    from aiortc import RTCPeerConnection, RTCSessionDescription

    from galaxy_gateway.voice_call_route import close_voice_route, maybe_handle_voice_message

    srv = await FakeRealtimeServer().start()
    runtime = FakeRuntime(reply="三点的提醒设好了")
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)
    monkeypatch.setenv("GALAXY_REALTIME_URL", f"ws://127.0.0.1:{srv.port}/v1/realtime")
    monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "openai_realtime")
    monkeypatch.setenv("GALAXY_REALTIME_TOOLS", "1")
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    to_watch: List[Dict[str, Any]] = []

    async def send_json(payload: Dict[str, Any]) -> None:
        to_watch.append(payload)

    watch = RTCPeerConnection()
    watch.addTransceiver("audio", direction="sendrecv")
    try:
        offer = await watch.createOffer()
        await watch.setLocalDescription(offer)
        await maybe_handle_voice_message(
            "conn_e2e", "voice_call_start", {"sdp": watch.localDescription.sdp}, "watch-e2e", send_json
        )
        accepted = next((m for m in to_watch if m["type"] == "voice_call_accepted"), None)
        assert accepted is not None, f"通话没接通: {to_watch}"
        await watch.setRemoteDescription(RTCSessionDescription(sdp=accepted["sdp"], type="answer"))
        (upd,) = await srv.wait_for(lambda m: m.get("type") == "session.update")
        assert "agent_do" in [t["name"] for t in upd["session"]["tools"]], "这通电话的会话声明了工具"
        assert "Galaxy" in upd["session"]["instructions"]

        # 人说了一句,模型决定交给智能体
        await srv.send(
            {"type": "input_audio_buffer.speech_started"},
            {"type": "input_audio_buffer.speech_stopped"},
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "三点提醒我开会"},
            _fc("call_a", "agent_do", {"what": "下午三点提醒我开会"}),
            {"type": "response.audio_transcript.delta", "delta": "好,我来设"},
            {"type": "response.done"},
        )
        outs = await srv.wait_for(
            lambda m: m.get("type") == "conversation.item.create" and m["item"]["type"] == "function_call_output"
        )
        assert json.loads(outs[0]["item"]["output"])["ok"] is True
        await srv.wait_for(lambda m: m.get("type") == "response.create")
        for _ in range(50):
            if runtime.calls:
                break
            await asyncio.sleep(0.02)
        assert runtime.calls[0]["message"] == "下午三点提醒我开会" and runtime.calls[0]["source"] == "wear_call"

        runtime.release.set()  # 智能体做完了
        notes = await srv.wait_for(
            lambda m: m.get("type") == "conversation.item.create" and m["item"].get("role") == "system"
        )
        assert "三点的提醒设好了" in notes[0]["item"]["content"][0]["text"]
        tasks = [m["text"] for m in to_watch if m.get("type") == "voice_event" and m.get("event") == "agent_task"]
        assert tasks[0].startswith("在做:") and tasks[-1].startswith("做完了:"), tasks
        assert not [
            m for m in to_watch if m.get("type") == "voice_event" and m.get("event") == "error"
        ], "错误事件会让手表挂断,工具这一路不能发"
    finally:
        await close_voice_route("conn_e2e")
        await get_call_registry().end_all(reason="test_teardown")
        await watch.close()
        await srv.stop()


async def test_a_local_realtime_service_on_a_call_listens_and_reports_back(monkeypatch):
    """本机的实时服务(全模态 server)不塞 tools:人说一句,智能体旁听交过去,回报插回通话。"""
    from core.voice_call_bridge import get_call_registry, webrtc_available

    if webrtc_available() is not None:
        pytest.skip(webrtc_available())
    from aiortc import RTCPeerConnection

    from galaxy_gateway.voice_call_route import close_voice_route, maybe_handle_voice_message

    srv = await FakeRealtimeServer().start()
    runtime = FakeRuntime(reply="灯关了")
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)

    async def judge(text: str, context: List[Dict[str, str]], running: List[str]) -> str:
        return "do" if "关" in text else ""

    monkeypatch.setattr(vca, "_judge", judge)
    monkeypatch.setenv("GALAXY_REALTIME_URL", f"ws://127.0.0.1:{srv.port}/v1/realtime")
    monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "openai_realtime")
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    to_watch: List[Dict[str, Any]] = []

    async def send_json(payload: Dict[str, Any]) -> None:
        to_watch.append(payload)

    watch = RTCPeerConnection()
    watch.addTransceiver("audio", direction="sendrecv")
    try:
        offer = await watch.createOffer()
        await watch.setLocalDescription(offer)
        await maybe_handle_voice_message(
            "conn_listen", "voice_call_start", {"sdp": watch.localDescription.sdp}, "watch-listen", send_json
        )
        assert any(m["type"] == "voice_call_accepted" for m in to_watch), to_watch
        (upd,) = await srv.wait_for(lambda m: m.get("type") == "session.update")
        assert not upd["session"].get("tools"), "本机服务收不收 tools 没法预知:不塞"
        assert "执行部分在旁边听着" in upd["session"]["instructions"]
        await srv.send(
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "把客厅的灯关了"},
            {"type": "response.audio_transcript.delta", "delta": "好的"},
            {"type": "response.done"},
        )
        for _ in range(100):
            if runtime.calls:
                break
            await asyncio.sleep(0.02)
        assert runtime.calls and runtime.calls[0]["message"] == "把客厅的灯关了"
        runtime.release.set()
        notes = await srv.wait_for(
            lambda m: m.get("type") == "conversation.item.create" and m["item"].get("role") == "system"
        )
        assert "灯关了" in notes[0]["item"]["content"][0]["text"]
    finally:
        await close_voice_route("conn_listen")
        await get_call_registry().end_all(reason="test_teardown")
        await watch.close()
        await srv.stop()


# ---------------------------------------------------------------------------
# 七、电脑自己的实时语音
# ---------------------------------------------------------------------------


async def test_the_desktops_own_realtime_voice_acts_too(monkeypatch):
    """电脑上的双工此前只旁录、从不交给智能体 —— 说「帮我打开浏览器」,它只会聊。现在旁听交过去。"""
    from core.multimodal.audio_capture_service import AudioCaptureConfig, AudioCaptureService
    from core.voice_loop import VoiceLoop

    srv = await FakeRealtimeServer().start()
    runtime = FakeRuntime(reply="浏览器打开了")
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)

    async def judge(text: str, context: List[Dict[str, str]], running: List[str]) -> str:
        return "do" if "打开" in text else ""

    monkeypatch.setattr(vca, "_judge", judge)
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "sk-test")
    monkeypatch.setenv("GALAXY_REALTIME_URL", f"ws://127.0.0.1:{srv.port}/v1/realtime")
    loop = VoiceLoop(object(), speak_responses=False)
    try:
        assert await loop._try_start_duplex(AudioCaptureConfig, AudioCaptureService)
        (upd,) = await srv.wait_for(lambda m: m.get("type") == "session.update")
        assert not upd["session"].get("tools") and "电脑旁" in upd["session"]["instructions"]
        await srv.send(
            {"type": "conversation.item.input_audio_transcription.completed", "transcript": "帮我打开浏览器"},
            {"type": "response.audio_transcript.delta", "delta": "好"},
            {"type": "response.done"},
        )
        for _ in range(3000):
            if runtime.calls:
                break
            await asyncio.sleep(0.02)
        (req,) = runtime.calls
        assert req["message"] == "帮我打开浏览器" and req["source"] == "voice_duplex"
        assert req["session_id"] == "voice_duplex:desktop"
        assert (
            req["session_id"] != loop._duplex_bridge.conversation_session_id
        ), "人说的话旁录已经记进对话主线;智能体做事会把这一轮再记一遍,用主线就成了两句"
        runtime.release.set()
        # 旁录那一路落会话记忆时可能同步加载嵌入模型、卡住事件循环几秒 —— 多等一会儿
        notes = await srv.wait_for(
            lambda m: m.get("type") == "conversation.item.create" and m["item"].get("role") == "system",
            timeout=60,
        )
        assert "浏览器打开了" in notes[0]["item"]["content"][0]["text"]
    finally:
        await loop.stop()
        await srv.stop()


# ---------------------------------------------------------------------------
# 八、手机打来的电话
# ---------------------------------------------------------------------------


async def test_a_call_from_a_phone_acts_too_and_reports_on_the_phone_after_hanging_up(monkeypatch):
    """手机和手表走同一条通话路由:说明里说的是手机,交过去的来源是 phone_call,挂断后做完的事用手机的
    notification 动作弹通知(手表的是 notify)。"""
    from core.voice_call_bridge import get_call_registry, webrtc_available

    if webrtc_available() is not None:
        pytest.skip(webrtc_available())
    from aiortc import RTCPeerConnection, RTCSessionDescription

    from galaxy_gateway.voice_call_route import close_voice_route, maybe_handle_voice_message

    srv = await FakeRealtimeServer().start()
    runtime = FakeRuntime(reply="明天晴")
    monkeypatch.setattr("core.desktop_presence_runtime.get_desktop_presence_runtime", lambda: runtime)
    monkeypatch.setattr(vca, "device_kind", lambda device_id: "phone")
    sent: List[tuple] = []

    async def _send_to_device(device_id: str, msg: Dict[str, Any]) -> bool:
        sent.append((device_id, msg))
        return True

    monkeypatch.setattr("core.routes._shared.connection_manager.send_to_device", _send_to_device)
    monkeypatch.setenv("GALAXY_REALTIME_URL", f"ws://127.0.0.1:{srv.port}/v1/realtime")
    monkeypatch.setenv("GALAXY_REALTIME_PROVIDER", "openai_realtime")
    monkeypatch.setenv("GALAXY_REALTIME_TOOLS", "1")
    monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "1")
    to_phone: List[Dict[str, Any]] = []

    async def send_json(payload: Dict[str, Any]) -> None:
        to_phone.append(payload)

    phone = RTCPeerConnection()
    phone.addTransceiver("audio", direction="sendrecv")
    try:
        offer = await phone.createOffer()
        await phone.setLocalDescription(offer)
        await maybe_handle_voice_message(
            "conn_phone", "voice_call_start", {"sdp": phone.localDescription.sdp}, "phone-e2e", send_json
        )
        accepted = next((m for m in to_phone if m["type"] == "voice_call_accepted"), None)
        assert accepted is not None, to_phone
        await phone.setRemoteDescription(RTCSessionDescription(sdp=accepted["sdp"], type="answer"))
        (upd,) = await srv.wait_for(lambda m: m.get("type") == "session.update")
        assert "手机上和你通话" in upd["session"]["instructions"]
        await srv.send(_fc("call_p", "agent_do", {"what": "查明天的天气"}), {"type": "response.done"})
        for _ in range(100):
            if runtime.calls:
                break
            await asyncio.sleep(0.02)
        assert runtime.calls[0]["source"] == "phone_call" and runtime.calls[0]["session_id"] == "phone_call:phone-e2e"
        await close_voice_route("conn_phone")  # 挂断,事情还没做完
        runtime.release.set()
        for _ in range(100):
            if sent:
                break
            await asyncio.sleep(0.02)
        ((device_id, msg),) = sent
        assert device_id == "phone-e2e" and msg["command"] == "notification", msg
        assert "明天晴" in msg["params"]["text"]
    finally:
        await close_voice_route("conn_phone")
        await get_call_registry().end_all(reason="test_teardown")
        await phone.close()
        await srv.stop()
