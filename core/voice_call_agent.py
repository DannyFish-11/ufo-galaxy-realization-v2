"""core/voice_call_agent.py —— 手表通话里「边说边做」。

人和智能体在手表上通话,就像跟人打电话:说着说着让它去做件事,它答应一声就去做,电话不挂、话照说;
做完了它在电话里告诉你。

怎么做到的
==========
通话里接话的是实时语音模型(``core.voice_duplex_session``,OpenAI Realtime / Gemini Live)—— 它负责
**说**。**做**由中心智能体负责(``DesktopPresenceRuntime.handle_request``,和面板、手表语音问答是同一个
智能体、同一套工具与权限)。两者之间靠三个工具接起来,声明在实时会话里:

* ``agent_do(what)`` —— 把要做的事交给智能体。**立刻**回「已经开始做」,模型据此答应一声、接着说话;
  事情在后台跑。做完以后往通话里插一条以【回报】开头的系统消息,模型据此把结果说给人听。
  后台做完再插消息,而不是让工具调用一直挂着等:实时接口里一个挂着的调用会让对话卡住,
  而各家「异步工具调用」的支持参差不齐(Gemini 有的型号收到 scheduling 字段反而断开会话)。
* ``agent_status()`` —— 人问「做到哪了」时看一眼。
* ``agent_stop(task_id?)`` —— 人说「算了不用了」时停下。

智能体做事的途中要问人(高风险操作要批准、``ask_human`` 要人选一个)时,问题也进通话
(【智能体在问】),人在电话里答:

* 普通的问题,人的**原话**(实时转写,不是模型的转述)直接交回去:说中了哪个选项就是哪个,
  否则把原话交给提问的那一方自己判断;
* 高风险操作的**批准**仍然要在手表上点 —— 嘴上说「好」不算(转写会听错,AI 自己的回声也可能
  被当成人说的);嘴上说「不要」算拒绝(拒绝是安全的方向)。

交给智能体的话是语音模型转述的,所以来源记为 ``wear_call``:不进电脑三态(``core.presence_line``),
也**不**算「人亲口说的」(``core.device_onboarding.conversation.HUMAN_REQUEST_SOURCES``)—— 对话里的
确认不会被一句转述满足。人这几句的原话作为上下文一并带上。

挂断以后还没做完的事照样做完,结果作为通知发到手表上。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.VoiceCallAgent")

#: 交给智能体的那一轮的来源。不进电脑三态;不算人亲口说的(见模块说明)。
CALL_SOURCE = "wear_call"
#: 人在通话里回答智能体的提问时,作为 ``voice_input`` 的来源。
ANSWER_SOURCE = "wear_call_voice"

#: 带给智能体的通话上下文最多几句。
MAX_CONTEXT_TURNS = 12
#: 回报里结果最多说多少字(模型会再概括成一两句)。
MAX_REPORT_CHARS = 600
#: 手表通知的上限(galaxy-wearos AgentCommand.MAX_TITLE / MAX_TEXT)。
NOTIFY_TITLE, NOTIFY_MAX_TEXT = "Galaxy", 500
#: 插了一条消息之后,最多等这么久的回复;等不到(provider 没回)就不再挡着后面的回报。
NOTE_REPLY_WAIT_S = 15.0

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


def call_instructions(can_act: bool) -> str:
    """通话里实时语音模型的说明。"""
    text = "你是用户的智能体 Galaxy,用户正在手表上和你通话。像人打电话一样自然、简短地说话,一次一两句。"
    if not can_act:
        return text + (
            "这条通话用的语音服务不支持调用工具,所以通话里没法替他做事;他要你做事时照实告诉他,"
            "可以挂断后在手表上用语音问答让你去做。"
        )
    return text + (
        "他要你做事时,调用 agent_do 交给你的执行部分,同时继续和他说话(比如先答应一声);"
        "做完会有以【回报】开头的系统消息,收到后用一两句话告诉他结果;没有回报之前不要说做完了。"
        "他问进展就用 agent_status,他说不用了就用 agent_stop。"
        "有以【智能体在问】开头的系统消息时,把问题原样问他,然后等他回答 —— 他的原话系统会直接交过去,"
        "你不用为这个调工具。以【提醒】开头的系统消息照着告诉他。"
    )


def configure_call_session(cfg: Any) -> bool:
    """给一条通话的实时会话配上说明和工具。返回这条通话能不能把事交给智能体去做。

    * 这家接口不支持工具(阶跃,见 ``StepRealtimeAdapter``)或 ``GALAXY_VOICE_CALL_AGENT=0`` 时只聊;
    * 本地的实时服务(本机全模态 server)收不收 ``tools`` 字段没法预知,往里塞一个它不认的字段,
      失败方向是整通电话打不通 —— 默认只聊,``GALAXY_REALTIME_TOOLS=1`` 明确打开。

    配不上(配置缺字段、认不出 provider)就只聊 —— 这一步绝不能让电话打不通。
    """
    from core.config_flags import flag
    from core.voice_duplex_adapters import get_adapter
    from core.voice_duplex_session import is_local_endpoint

    provider = str(getattr(cfg, "provider", "") or "")
    try:
        can_act = bool(get_adapter(provider).supports_tools) and flag("GALAXY_VOICE_CALL_AGENT", True)
    except ValueError:
        can_act = False
    url = str(getattr(cfg, "url", "") or "")
    if can_act and url and is_local_endpoint(url):
        can_act = flag("GALAXY_REALTIME_TOOLS", False)
    try:
        cfg.tools = [dict(t) for t in CALL_TOOLS] if can_act else []
        cfg.instructions = "\n".join(x for x in (getattr(cfg, "instructions", ""), call_instructions(can_act)) if x)
    except AttributeError:  # 配置对象不让设(冻结的、带 __slots__ 的):这通电话只聊
        return False
    if not can_act:
        logger.info("通话只聊、不能把事交给智能体(provider=%s)", provider or "?")
    return can_act


@dataclass
class _Task:
    task_id: str
    what: str
    started: float
    state: str = "running"  # running / done / failed / stopped
    result: str = ""
    future: Optional["asyncio.Task[None]"] = None


class CallAgent:
    """一通通话的「边说边做」。由 ``VoiceCall`` 持有,吃同一条下行事件流。"""

    def __init__(
        self,
        device_id: str,
        call_id: str,
        session: Any,
        *,
        send_event: Optional[Callable[[str, str, str], Any]] = None,
        session_id: str = "",
    ) -> None:
        self.device_id = device_id
        self.call_id = call_id
        self.session = session
        #: 同一块手表的通话共用一条会话:智能体记得上一通电话里说过的事。
        self.session_id = session_id or f"wear_call:{device_id}"
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
            for ask in self._asks.values():
                if ask["state"] == "asked":
                    ask["heard"].append(ev.text)
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
                source=CALL_SOURCE,
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
        verdict = {"done": "做完了", "failed": "没做成", "stopped": "停下了"}.get(task.state, task.state)
        result = task.result[:MAX_REPORT_CHARS]
        self._tell_device(f"{verdict}:{task.what}")
        if self.closed:
            await self._notify_watch(f"{verdict}:{task.what}。{result}")
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
        """智能体要问人一件事(``request_human_decision`` 发给这块手表时)。"""
        high = urgency == "high"
        self._asks[decision_id] = {"options": list(options or []), "high": high, "state": "queued", "heard": []}
        labels = " / ".join(str(o.get("label") or o.get("id")) for o in options or [])
        note = f"【智能体在问】{title}。{summary}".strip()
        if labels:
            note += f" 可以选:{labels}。"
        if high:
            note += " 这件事要他在手表上点「批准」才算;他说不要就算拒绝。"
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
                self._asks.pop(decision_id, None)  # 已经在手表上答了,或者超时了
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
        """手表通话界面上显示一行「在做 / 做完了」(``voice_event`` 的 ``agent_task``)。"""
        if self._send_event is None or self.closed:
            return
        try:
            result = self._send_event("agent_task", text[:120], "")
            if asyncio.iscoroutine(result):
                asyncio.ensure_future(result)
        except Exception as exc:  # noqa: BLE001
            logger.debug("call=%s 显示进度失败: %s", self.call_id, exc)

    async def _notify_watch(self, text: str) -> None:
        """挂断以后做完的事:作为通知发到手表上。"""
        try:
            from core.routes._shared import connection_manager

            await connection_manager.send_to_device(
                self.device_id,
                {
                    "type": "command",
                    "command_id": f"callreport-{uuid.uuid4().hex[:10]}",
                    "command": "notify",
                    "device_id": self.device_id,
                    "timestamp": int(time.time() * 1000),
                    "params": {"title": NOTIFY_TITLE, "text": text[:NOTIFY_MAX_TEXT]},
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("call=%s 通话已挂断,结果没送到手表: %s", self.call_id, exc)

    def on_call_closed(self) -> None:
        """通话挂断:还在做的照样做完,结果改走通知;没问完的问题仍在手表上等人点。"""
        self.closed = True
        self._notes.clear()
        running = [t.task_id for t in self.tasks.values() if t.state == "running"]
        if running:
            logger.info("call=%s 挂断时还有 %d 件在做,做完发通知到手表", self.call_id, len(running))


_NO_ANSWER = object()


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
            return _NO_ANSWER, "【提醒】批准要他在手表上点一下「批准」,嘴上说不算;不想做就说不要。"
        return _NO_ANSWER, ""
    if matched is not None:
        return str(matched.get("id")), ""
    if len(options) == 2 and deny is not None and other is not None and verdict is not None:
        return str((other if verdict else deny)["id"]), ""
    if not options:
        return None, ""  # 开放的问题:原话就是回答,交给提问的一方判断
    return _NO_ANSWER, ""  # 有选项却没说中,也没明确表态:这句可能在说别的,不当成回答
