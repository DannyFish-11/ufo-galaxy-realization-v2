"""core/voice_call_agent.py —— 实时语音里「边说边做」(设备打来的通话、本机自己的实时语音)。

人用一台设备和智能体通话、或在本机旁用实时语音说话,就像跟人说话:说着说着让它去做件事,它答应一声就去做,
话照说;做完了它告诉你。

这里不分设备是什么:通话说明里只有设备登记时自己报的名字,哪种设备打来都是同一个来源、同一套做法;
挂断后结果怎么告诉人,交给智能体看设备卡片自己判断。

怎么做到的
==========
接话的是实时语音模型(``core.voice_duplex_session``:OpenAI Realtime、Gemini Live、阶跃、本机的全模态
server)—— 它负责**说**。**做**由中心智能体负责(``DesktopPresenceRuntime.handle_request``,和面板、
设备上的语音问答是同一个智能体、同一套工具与权限)。事情怎么交过去,看说话的模型会不会调工具:

**会调工具**(设备通话,接的是 OpenAI / Gemini 这类云端实时接口)—— 它自己把事交过来,靠三个工具,
声明在实时会话里:

* ``agent_do(what)`` —— 把要做的事交给智能体。**立刻**回「已经开始做」,模型据此答应一声、接着说话;
  事情在后台跑。做完以后往通话里插一条以【回报】开头的系统消息,模型据此把结果说给人听。
  后台做完再插消息,而不是让工具调用一直挂着等:实时接口里一个挂着的调用会让对话卡住,
  而各家「异步工具调用」的支持参差不齐(Gemini 有的型号收到 scheduling 字段反而断开会话)。
* ``agent_status()`` —— 人问「做到哪了」时看一眼。
* ``agent_stop(task_id?)`` —— 人说「算了不用了」时停下。

**不会调工具,或者是本机自己的实时语音** —— 智能体自己旁听:人说完一句(实时转写,不是模型的转述),
快档模型(``fast_response``,本地优先)判一下这句是要做事、要停、问进展,还是只是在聊;要做事就把**人的
原话**交给智能体,和上面同一套后台做、回报。阶跃没有可核实的工具资料、本机 server 收不收 ``tools``
没法预知,都走这一路;本机这边一律走这一路 —— 智能体在本机上本来就听得见人,交过去的是人的原话,
和回合制语音一样算人说的(来源 ``voice_duplex``)。

智能体做事的途中要问人(高风险操作要批准、``ask_human`` 要人选一个)时,问题也进通话
(【智能体在问】),人在电话里答:

* 普通的问题,人的**原话**(实时转写,不是模型的转述)直接交回去:说中了哪个选项就是哪个,
  否则把原话交给提问的那一方自己判断;
* 高风险操作的**批准**仍然要在弹出的确认上点 —— 嘴上说「好」不算(转写会听错,AI 自己的回声也可能
  被当成人说的);嘴上说「不要」算拒绝(拒绝是安全的方向)。

设备通话里交给智能体的事来源记为 ``device_call``:不进电脑三态(``core.presence_line``),也**不**算
「人亲口说的」(``core.device_onboarding.conversation.HUMAN_REQUEST_SOURCES``)—— 调工具交过来的是语音
模型的转述;旁听交过来的是转写,AI 自己的回声也可能被转写进来;对话里的确认都不该被它满足。人这几句的
原话作为上下文一并带上。

挂断以后还没做完的事照样做完;结果交给智能体,由它看设备卡片决定发到哪台、怎么说(刚才通话的那台,
或人此刻更可能看到的别的设备)。只有 ``GALAXY_VOICE_CALL_AGENT=0`` 才只聊。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.VoiceCallAgent")

#: 设备通话里交给智能体的那一轮的来源(哪种设备打来都一样)。不进电脑三态;不算人亲口说的(见模块说明)。
CALL_SOURCE = "device_call"
#: 本机自己的实时语音交给智能体的那一轮的来源:人的原话,和回合制语音一样算人说的。
DESKTOP_SOURCE = "voice_duplex"
#: 人在通话里回答智能体的提问时,作为 ``voice_input`` 的来源。
ANSWER_SOURCE = "device_call_voice"

#: 带给智能体的通话上下文最多几句。
MAX_CONTEXT_TURNS = 12
#: 回报里结果最多说多少字(模型会再概括成一两句)。
MAX_REPORT_CHARS = 600
#: 插了一条消息之后,最多等这么久的回复;等不到(provider 没回)就不再挡着后面的回报。
NOTE_REPLY_WAIT_S = 15.0

#: 旁听时判一句话的说明。只回一个字。
LISTEN_PROMPT = (
    "你在旁听用户和语音助手的对话,判断用户刚说的这句话要不要交给执行部分。只回一个字:\n"
    "做 —— 要办一件事(操作设备或应用,查实时的信息,发消息,记事,提醒,改设置,找文件……);\n"
    "停 —— 让交出去、正在做的事别做了;\n"
    "问 —— 问交出去的事做到哪了;\n"
    "不 —— 闲聊、问常识、打招呼、附和,语音助手自己接就行。"
)
_LISTEN_VERDICTS = {"做": "do", "停": "stop", "问": "status"}

_DENY_IDS = frozenset({"deny", "no", "reject", "cancel"})
_DENY_LABELS = frozenset({"不要", "拒绝", "取消", "不"})

CALL_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "agent_do",
        "description": (
            "把用户要你做的事交给你自己的执行部分去做(操作设备、查资料、发消息、记事、提醒……)。"
            "它在后台做,你可以继续和用户说话;做完会有一条以【回报】开头的系统消息告诉你结果。"
            "没收到回报之前不要说已经做完了。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"what": {"type": "string", "description": "要做的事,把用户的要求说完整"}},
            "required": ["what"],
        },
    },
    {
        "name": "agent_status",
        "description": "看看交出去的事做到哪了。用户问进展时用。",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "agent_stop",
        "description": "用户说不用做了、停下时,停掉交出去的事。不给 task_id 就停掉全部还在做的。",
        "parameters": {"type": "object", "properties": {"task_id": {"type": "string"}}},
    },
]


_NOTES_HOWTO = (
    "有以【智能体在问】开头的系统消息时,把问题原样问他,然后等他回答 —— 他的原话系统会直接交过去,"
    "你不用为这个做什么。以【提醒】、【进展】开头的系统消息照着告诉他。"
)


def call_agent_enabled() -> bool:
    """实时语音里接不接智能体。默认接;``GALAXY_VOICE_CALL_AGENT=0`` 只聊。"""
    from core.config_flags import flag

    return flag("GALAXY_VOICE_CALL_AGENT", True)


def device_name(device_id: str) -> str:
    """设备登记时自己报的名字;没报、查不到是空串。"""
    if not device_id:
        return ""
    try:
        from core.unified.device_manager import get_unified_device_manager

        d = get_unified_device_manager().get_device(device_id)
    except Exception:  # noqa: BLE001 — 查不到就不说名字
        return ""
    name = str(getattr(d, "device_name", "") or "") if d is not None else ""
    return "" if name == device_id else name


def describe_caller(device_id: str) -> str:
    """人在哪儿和智能体说话。设备只说它自己报的名字,不按设备是什么分说法;没有设备 id 就是本机。"""
    if not device_id:
        return "用户就在本机旁,用语音和你说话"
    name = device_name(device_id)
    return f"用户正在用设备「{name}」和你语音通话" if name else "用户正在用一台设备和你语音通话"


def call_instructions(mode: str, *, device_id: str) -> str:
    """实时语音模型的说明。``mode``:``tools`` 自己调工具交事 / ``listen`` 智能体旁听 / ``""`` 只聊;
    ``device_id``:打来电话的设备,空 = 本机自己的实时语音。"""
    text = f"你是用户的智能体 Galaxy,{describe_caller(device_id)}。像人说话一样自然、简短,一次一两句。"
    if mode == "tools":
        return text + (
            "他要你做事时,调用 agent_do 交给你的执行部分,同时继续和他说话(比如先答应一声);"
            "做完会有以【回报】开头的系统消息,收到后用一两句话告诉他结果;没有回报之前不要说做完了。"
            "他问进展就用 agent_status,他说不用了就用 agent_stop。" + _NOTES_HOWTO
        )
    if mode == "listen":
        return text + (
            "你负责说话;他要你做的事,你的执行部分在旁边听着,会自己接过去做 —— 你答应一声就行,"
            "别说你做不了,也别说已经做完了。做完会有以【回报】开头的系统消息,收到后用一两句话告诉他结果。"
            + _NOTES_HOWTO
        )
    return text + "这条通话里没法替他做事;他要你做事时照实告诉他,可以挂断后用文字或语音问答让你去做。"


def configure_call_session(cfg: Any, *, device_id: str) -> str:
    """给一条实时会话配上说明和工具。返回事情怎么交给智能体:``tools`` / ``listen`` / ``""``(只聊)。

    ``device_id`` 是打来电话的设备;空串 = 本机自己的实时语音。必须明说:漏了就会被当成本机、改走旁听。

    * 设备通话、这家接口会调工具(OpenAI / Gemini)→ ``tools``,模型自己交;
    * 接口不支持工具(阶跃,见 ``StepRealtimeAdapter``)→ ``listen``,智能体旁听;
    * 本机的实时服务(本机全模态 server)收不收 ``tools`` 字段没法预知,往里塞一个它不认的字段,
      失败方向是整通电话打不通 → ``listen``;``GALAXY_REALTIME_TOOLS=1`` 明确让它调工具;
    * 本机自己的实时语音 → ``listen``(见模块说明);
    * ``GALAXY_VOICE_CALL_AGENT=0`` → 只聊。

    配不上(配置缺字段、认不出 provider)就旁听 —— 这一步绝不能让电话打不通。
    """
    from core.config_flags import flag
    from core.voice_duplex_adapters import get_adapter
    from core.voice_duplex_session import is_local_endpoint

    provider = str(getattr(cfg, "provider", "") or "")
    if not call_agent_enabled():
        mode = ""
    elif not device_id:
        mode = "listen"
    else:
        try:
            tools_ok = bool(get_adapter(provider).supports_tools)
        except ValueError:
            tools_ok = False
        url = str(getattr(cfg, "url", "") or "")
        if tools_ok and url and is_local_endpoint(url):
            tools_ok = flag("GALAXY_REALTIME_TOOLS", False)
        mode = "tools" if tools_ok else "listen"
    try:
        cfg.tools = [dict(t) for t in CALL_TOOLS] if mode == "tools" else []
        cfg.instructions = "\n".join(
            x for x in (getattr(cfg, "instructions", ""), call_instructions(mode, device_id=device_id)) if x
        )
    except AttributeError:  # 配置对象不让设(冻结的、带 __slots__ 的):不声明工具,智能体旁听
        return "listen" if mode else ""
    logger.info("实时语音交事的方式:%s(provider=%s)", mode or "只聊", provider or "?")
    return mode


@dataclass
class _Task:
    task_id: str
    what: str
    started: float
    state: str = "running"  # running / done / failed / stopped
    result: str = ""
    future: Optional["asyncio.Task[None]"] = None


class CallAgent:
    """一条实时语音的「边说边做」。设备通话由 ``VoiceCall`` 持有,本机的由 ``VoiceLoop`` 持有,吃同一条下行事件流。

    会话声明了工具就等模型调;没声明就旁听(见模块说明)。
    """

    def __init__(
        self,
        device_id: str,
        call_id: str,
        session: Any,
        *,
        send_event: Optional[Callable[[str, str, str], Any]] = None,
        session_id: str = "",
        source: str = CALL_SOURCE,
    ) -> None:
        self.device_id = device_id
        self.call_id = call_id
        self.session = session
        #: 同一台设备的通话共用一条会话:智能体记得上一通电话里说过的事。本机的是 ``voice_duplex:desktop``
        #: —— 不用对话主线:人说的话旁录已经记进主线,智能体做事时会把这一轮再记一遍,主线上就成了两句。
        self.session_id = session_id or f"{source}:{device_id or 'desktop'}"
        self.source = source
        #: 会话里没声明工具:模型交不过来,智能体自己旁听。
        self.listening = not getattr(getattr(session, "config", None), "tools", None)
        self._send_event = send_event
        self.tasks: Dict[str, _Task] = {}
        self.transcript: List[Dict[str, str]] = []
        self._reply = ""
        self._responding = False
        self._note_sent_at = 0.0
        self._user_speaking = False
        #: 待插进通话的消息:(文字, 属于哪个提问 / "")
        self._notes: List[tuple] = []
        #: 智能体在问的事:decision_id → {options, high, state: queued/asking/asked, heard: [...]}
        self._asks: Dict[str, Dict[str, Any]] = {}
        #: 旁听时正在判的话
        self._hearing: set = set()
        self.closed = False

    # ── 下行事件 ────────────────────────────────────────────────────────

    async def on_event(self, ev: Any) -> bool:
        """看一条下行事件。返回 True 表示这条归本类处理、不再转给设备。"""
        name = getattr(ev.type, "value", str(ev.type))
        if name == "tool_call":
            await self._on_tool_call(ev)
            return True
        if name == "user_speech_started":
            self._user_speaking = True
        elif name == "user_speech_stopped":
            self._user_speaking = False
        elif name == "final_transcript" and ev.text:
            self._user_speaking = False
            self._remember("user", ev.text)
            answering = False
            for ask in self._asks.values():
                if ask["state"] == "asked":
                    ask["heard"].append(ev.text)
                answering = answering or ask["state"] in ("asking", "asked")
            if self.listening and not answering:
                self._track(self._hear(ev.text, list(self.transcript[:-1])))
        elif name in ("assistant_text_delta", "assistant_audio_delta"):
            self._responding = True
            self._reply += getattr(ev, "text", "") or ""
        elif name == "response_done":
            self._responding, self._note_sent_at = False, 0.0
            if self._reply.strip():
                self._remember("assistant", self._reply.strip())
            self._reply = ""
            self._answer_asks()
        await self._flush_notes()
        return False

    def _remember(self, role: str, text: str) -> None:
        self.transcript.append({"role": role, "content": text})
        del self.transcript[:-MAX_CONTEXT_TURNS]

    def _track(self, coro: Any) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._hearing.add(task)
        task.add_done_callback(self._hearing.discard)

    # ── 旁听 ────────────────────────────────────────────────────────────

    async def _hear(self, text: str, context: List[Dict[str, str]]) -> None:
        """人说完一句:要做事就把原话交给智能体;要停就停;问进展就把进展插回去。"""
        from core.voice_dialog_policy import BARGE_IN_BACKCHANNEL, get_dialog_policy

        if get_dialog_policy().classify_barge_in(text) == BARGE_IN_BACKCHANNEL:
            return  # 「嗯」「对」:附和,不是在要什么
        verdict = await _judge(text, context, [t.what for t in self.tasks.values() if t.state == "running"])
        if self.closed or not verdict:
            return
        logger.info("call=%s 旁听:%s ← %s", self.call_id, verdict, text[:60])
        if verdict == "do":
            self._start(text)
        elif verdict == "stop":
            self._stop("")
        elif verdict == "status" and self.tasks:
            lines = [f"「{t['what']}」{_STATE_WORDS.get(t['state'], t['state'])}" for t in self._status()["tasks"]]
            self._notes.append(("【进展】" + ";".join(lines), ""))
            await self._flush_notes()

    # ── 工具 ────────────────────────────────────────────────────────────

    async def _on_tool_call(self, ev: Any) -> None:
        name, args = ev.tool_name, dict(ev.tool_args or {})
        if name == "agent_do":
            out = self._start(str(args.get("what") or "").strip())
        elif name == "agent_status":
            out = self._status()
        elif name == "agent_stop":
            out = self._stop(str(args.get("task_id") or "").strip())
        else:
            out = {"ok": False, "error": f"没有这个工具:{name}"}
        if not await self.session.send_tool_result(ev.tool_call_id, name, out):
            logger.warning("call=%s 工具结果没交回去(%s)", self.call_id, name)

    def _start(self, what: str) -> Dict[str, Any]:
        if not what:
            return {"ok": False, "error": "要做什么没说清楚"}
        task = _Task(task_id=uuid.uuid4().hex[:8], what=what, started=time.time())
        self.tasks[task.task_id] = task
        task.future = asyncio.get_running_loop().create_task(self._run(task, list(self.transcript)))
        logger.info("call=%s 交给智能体 task=%s: %s", self.call_id, task.task_id, what[:120])
        self._tell_device(f"在做:{what}")
        return {"ok": True, "task_id": task.task_id, "status": "已经开始做,做完会告诉你"}

    async def _run(self, task: _Task, context: List[Dict[str, str]]) -> None:
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            rt = await get_desktop_presence_runtime().handle_request(
                message=task.what,
                source=self.source,
                device_id=self.device_id,
                session_id=self.session_id,
                context=context,
            )
            reply = str(rt.get("response") or rt.get("error") or "").strip()
            if rt.get("stopped"):
                task.state, task.result = "stopped", "被停下了"
            elif str((rt.get("metadata") or {}).get("model") or "") == "none":
                # 一个模型都调不通:智能体只回了一句说明(「还没有可用的 AI 服务…」),事情没做 —— 不能报成做完了
                task.state, task.result = "failed", reply or "智能体这边没有可用的模型"
            elif rt.get("success", True) is False:
                task.state, task.result = "failed", reply or "没做成,原因不明"
            else:
                task.state, task.result = "done", reply or "做完了"
        except asyncio.CancelledError:
            task.state, task.result = "stopped", "被停下了(停的那一刻正在做的那一步可能已经做了)"
            self._tell_device(f"停下了:{task.what}")
            return
        except Exception as exc:  # noqa: BLE001 — 出错也要报回去,不能让人干等
            logger.warning("call=%s task=%s 出错: %s", self.call_id, task.task_id, exc, exc_info=True)
            task.state, task.result = "failed", f"出错了:{exc}"
        await self._report(task)

    def _status(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "ok": True,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "what": t.what,
                    "state": t.state,
                    "seconds": round(now - t.started),
                    "result": t.result[:200],
                }
                for t in self.tasks.values()
            ],
        }

    def _stop(self, task_id: str) -> Dict[str, Any]:
        targets = [t for t in self.tasks.values() if t.state == "running" and (not task_id or t.task_id == task_id)]
        for t in targets:
            if t.future is not None and not t.future.done():
                t.future.cancel()
        return {"ok": True, "stopped": [t.task_id for t in targets]}

    # ── 回报 ────────────────────────────────────────────────────────────

    async def _report(self, task: _Task) -> None:
        verdict = _STATE_WORDS.get(task.state, task.state)
        result = task.result[:MAX_REPORT_CHARS]
        self._tell_device(f"{verdict}:{task.what}")
        if self.closed:
            await self._hand_over_after_hangup(task.what, verdict, result)
            return
        self._notes.append((f"【回报】交给你做的「{task.what}」{verdict}。结果:{result}", ""))
        await self._flush_notes()

    async def _flush_notes(self) -> None:
        """人在说话、模型在说话时都不插 —— 等这一句说完再说结果,不打断谁。"""
        if self._responding and self._note_sent_at and time.time() - self._note_sent_at > NOTE_REPLY_WAIT_S:
            self._responding, self._note_sent_at = False, 0.0  # 插的那条一直没等到回复,不再挡着
        while self._notes and not self._responding and not self._user_speaking and not self.closed:
            note, decision_id = self._notes.pop(0)
            if not await self.session.send_note(note):
                logger.warning("call=%s 消息没插进通话: %s", self.call_id, note[:80])
            if decision_id in self._asks:
                self._asks[decision_id]["state"] = "asking"
            # 插了一条就会有一次回复;等它说完再插下一条
            self._responding, self._note_sent_at = True, time.time()

    # ── 智能体在问 ──────────────────────────────────────────────────────

    def on_decision(
        self, decision_id: str, title: str, summary: str, options: List[Dict[str, str]], urgency: str
    ) -> None:
        """智能体要问人一件事(``request_human_decision`` 发给正在通话的这台设备时)。"""
        high = urgency == "high"
        self._asks[decision_id] = {"options": list(options or []), "high": high, "state": "queued", "heard": []}
        labels = " / ".join(str(o.get("label") or o.get("id")) for o in options or [])
        note = f"【智能体在问】{title}。{summary}".strip()
        if labels:
            note += f" 可以选:{labels}。"
        if high:
            note += " 这件事要他在弹出的确认上点「批准」才算;他说不要就算拒绝。"
        self._notes.append((note, decision_id))
        try:
            asyncio.get_running_loop().create_task(self._flush_notes())
        except RuntimeError:
            pass  # 没有事件循环:下一条下行事件时再插

    def _answer_asks(self) -> None:
        """一次回复说完(``response_done``)时看提问:刚问出口的开始听;听着的,把人这一轮的原话判一判。

        只在回复说完时判 —— 人说完一句,模型接话,说完了,人这一轮的话才算齐(Gemini 的转写是一段段
        来的;OpenAI 的转写可能比回复还晚到)。问出口之前听到的话不算回答。
        """
        from core.interaction.pending_decision_registry import get_pending_decision_registry

        registry = get_pending_decision_registry()
        for decision_id, ask in list(self._asks.items()):
            if registry.get(decision_id) is None:
                self._asks.pop(decision_id, None)  # 已经在设备上点了,或者超时了
                continue
            if ask["state"] == "asking":
                ask["state"] = "asked"
                continue
            if ask["state"] != "asked" or not ask["heard"]:
                continue
            text, ask["heard"] = " ".join(ask["heard"]).strip(), []
            picked, reminder = _answer(text, ask["options"], ask["high"])
            if reminder:
                self._notes.append((reminder, ""))
            if picked is _NO_ANSWER:
                continue
            registry.resolve(decision_id, selected_option=picked, voice_input=text, source=ANSWER_SOURCE)
            self._asks.pop(decision_id, None)
            logger.info("call=%s 通话里答了 decision=%s option=%r", self.call_id, decision_id, picked)
            return  # 一轮话只答一个问题

    # ── 设备侧 ──────────────────────────────────────────────────────────

    def _tell_device(self, text: str) -> None:
        """通话界面上显示一行「在做 / 做完了」(``voice_event`` 的 ``agent_task``)。"""
        if self._send_event is None or self.closed:
            return
        try:
            result = self._send_event("agent_task", text[:120], "")
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("call=%s 显示进度失败: %s", self.call_id, exc)

    async def _hand_over_after_hangup(self, what: str, verdict: str, result: str) -> None:
        """挂断以后才有结果的事:交给智能体,由它决定怎么告诉人 —— 发到刚才通话的设备,还是人此刻更可能
        看到的别的设备,用哪个动作,看设备卡片和当时的情况。这里不替它挑设备,也不替它挑动作。

        来源用 ``device_call``(不算人亲口说的):这条是系统转来的结果,不能被当成人在回答对话里的确认。
        """
        if self.device_id:
            name = device_name(self.device_id)
            where = f"刚才的电话是在设备 {self.device_id}" + (f"(「{name}」)" if name else "") + " 上打的"
        else:
            where = "刚才是在本机旁用实时语音说的"
        message = (
            f"【通话已挂断】通话里交给你的「{what}」{verdict}。结果:{result}\n"
            f"用户已经不在通话里了,{where}。用你判断合适的方式把结果告诉他:看各设备的卡片决定发到哪台、"
            "用哪个动作。不用回复这条消息本身。"
        )
        try:
            from core.desktop_presence_runtime import get_desktop_presence_runtime

            await get_desktop_presence_runtime().handle_request(
                message=message,
                source=CALL_SOURCE,
                device_id=self.device_id,
                session_id=self.session_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 通话已挂断,结果没交给智能体转告: %s", self.call_id, exc)

    def on_call_closed(self) -> None:
        """通话挂断:还在做的照样做完,结果交给智能体转告;没问完的问题仍在设备上等人点。"""
        self.closed = True
        self._notes.clear()
        for t in list(self._hearing):
            t.cancel()
        running = [t.task_id for t in self.tasks.values() if t.state == "running"]
        if running:
            logger.info("call=%s 挂断时还有 %d 件在做,做完交给智能体转告", self.call_id, len(running))


_NO_ANSWER = object()
_STATE_WORDS = {"running": "在做", "done": "做完了", "failed": "没做成", "stopped": "停下了"}


async def _judge(text: str, context: List[Dict[str, str]], running: List[str]) -> str:
    """旁听:人刚说的这句 → ``do`` / ``stop`` / ``status`` / ``""``(只是在聊,或判不了)。

    用快档(``fast_response``,本地优先)。一个模型都调不通时判不了 —— 当成在聊:智能体那时也做不了事。
    """
    from core.llm.route_authority import get_llm_route_authority

    said = "\n".join(f"{'用户' if m['role'] == 'user' else '助手'}:{m['content']}" for m in context[-6:])
    doing = ";".join(running) if running else "没有"
    prompt = (f"前面说的:\n{said}\n" if said else "") + f"交出去正在做的事:{doing}\n用户刚说:{text}"
    try:
        resp = await get_llm_route_authority().chat(
            [{"role": "system", "content": LISTEN_PROMPT}, {"role": "user", "content": prompt}],
            task_type="fast_response",
            complexity=0.1,
            feature_context="voice_listen",
            temperature=0,
            max_tokens=4,
        )
    except Exception as exc:  # noqa: BLE001 — 判不了就当在聊,不能让通话出错
        logger.warning("旁听判断失败(当成在聊): %s", exc)
        return ""
    if str(getattr(resp, "provider", "") or "") == "none":
        return ""
    reply = str(getattr(resp, "content", "") or "").strip()
    return _LISTEN_VERDICTS.get(reply[:1], "")


def _is_deny(option: Dict[str, str]) -> bool:
    return str(option.get("id") or "").lower() in _DENY_IDS or str(option.get("label") or "") in _DENY_LABELS


def _answer(text: str, options: List[Dict[str, str]], high: bool) -> tuple:
    """人的一句原话 → (选中的选项 id / None 表示自由回答 / _NO_ANSWER 表示没答, 要说给人听的提醒)。"""
    from core.device_onboarding.conversation import interpret_reply

    verdict = interpret_reply(text)
    labelled = sorted(options, key=lambda o: -len(str(o.get("label") or "")))
    matched = next((o for o in labelled if o.get("label") and str(o["label"]) in text), None)
    deny = next((o for o in options if _is_deny(o)), None)
    other = next((o for o in options if not _is_deny(o)), None)
    if high:
        if (matched is not None and _is_deny(matched)) or verdict is False:
            return (str(deny["id"]) if deny else None), ""
        if verdict is True or (matched is not None and not _is_deny(matched)):
            return _NO_ANSWER, "【提醒】批准要他在弹出的确认上点一下「批准」,嘴上说不算;不想做就说不要。"
        return _NO_ANSWER, ""
    if matched is not None:
        return str(matched.get("id")), ""
    if len(options) == 2 and deny is not None and other is not None and verdict is not None:
        return str((other if verdict else deny)["id"]), ""
    if not options:
        return None, ""  # 开放的问题:原话就是回答,交给提问的一方判断
    return _NO_ANSWER, ""  # 有选项却没说中,也没明确表态:这句可能在说别的,不当成回答
