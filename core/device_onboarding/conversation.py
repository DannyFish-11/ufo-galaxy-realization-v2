"""core/device_onboarding/conversation.py — 设备这件事,在对话上下文里自己出现。

两件事,都落在同一条对话主线上(判据见 core/conversation_mainline.py,面板读的就是它):

**播报** :func:`announce`
    发现了新设备、有设备配对上了 —— 不等人来问,作为一句助手发言推给面板、记进主线。
    与自发开口(core/ambient_attention_loop.py 的 SPEAK)走同一对出口:
    ``emit_conversation`` 实时推面板,``record_session_turn`` 记进主线。

**确认** :func:`confirm_in_conversation`
    接入、移除这类要人点头的事,在对话里问、在对话里答,不另弹窗。规则写死在这里:

    1. 问的那一回合**不算数**。智能体在同一回合里再调一次工具,不会被当成答应 ——
       否则它自己就能给自己批准,工具返回里夹带的文字也能冒充人。
    2. 只认**人发起**的回合(文字对话、语音、手表)。自发注意力、视觉采样这类系统
       回合不算,即使它们挂在同一条会话上。来源未知一律不算(fail closed)。
    3. 看的是**人的原话**(``RuntimeSession.request_text``),不是模型的转述。
       明确的肯定才算答应;带否定的算拒绝;含糊的继续等 —— 和手表上的纪律一样,
       「嗯」「行吧」不构成授权。
    4. 一次答应只管一件事,用过即作废;十分钟没人答就作废。

手表/手机连着时仍然在手表上问(那条路会阻塞等回答),同时在对话里说一声问了什么。
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.Onboarding.Conversation")

#: 算作「人在说话」的回合来源(``DesktopPresenceRuntime.handle_request`` 的 ``source``)。
HUMAN_REQUEST_SOURCES = frozenset({"chat", "voice", "voice_duplex", "wear_voice", "wear_decision"})

#: 对话里的待确认,多久没人答就作废。
CONFIRM_TTL_S = 600.0

_YES = re.compile(
    r"^(好|好的|好啊|好吧好的|可以|行|行的|同意|确认|批准|接入|接吧|接进来|加进来|加吧|移除|删吧|执行|是|是的|对|对的|没问题|"
    r"ok|okay|yes|yep|sure|go|go ahead|confirm|approve)[!！。.~～ ]*$",
    re.IGNORECASE,
)
_NO = re.compile(r"(不|别|取消|算了|停|拒绝|no\b|nope|don'?t|cancel|stop)", re.IGNORECASE)


def interpret_reply(text: str) -> Optional[bool]:
    """人的原话 → 答应(True)/ 拒绝(False)/ 没表态(None)。只认短而明确的答复。"""
    t = (text or "").strip().lower()
    t = re.sub(r"^(嗯+|那|那就|就)[,，]?\s*", "", t)
    if not t:
        return None
    if _NO.search(t):
        return False
    if len(t) <= 12 and _YES.match(t):
        return True
    return None


# ── 当前回合 ─────────────────────────────────────────────────────────────────────


def _current_turn() -> Tuple[str, str, str]:
    """(runtime_session_id, source, 原话)。不在一个经正门的回合里时三者皆空。"""
    try:
        from core.liminal_activity import current_runtime_session

        rs = current_runtime_session()
    except Exception:  # noqa: BLE001
        rs = None
    if rs is None:
        return "", "", ""
    return (
        str(getattr(rs, "runtime_session_id", "") or ""),
        str(getattr(rs, "source", "") or ""),
        str(getattr(rs, "request_text", "") or ""),
    )


# ── 对话里的确认 ─────────────────────────────────────────────────────────────────


@dataclass
class _Pending:
    session_id: str
    what: str
    asked_in_turn: str
    asked_at: float


_pending: Dict[Tuple[str, str], _Pending] = {}
_lock = threading.Lock()


def _key(session_id: str, what: str) -> Tuple[str, str]:
    return (session_id or "", what)


def question_for(what: str) -> str:
    return f"要{what}吗?回一句「好」就执行,「不要」就算了。"


def confirm_in_conversation(what: str, session_id: str) -> Dict[str, Any]:
    """在对话里问/判一次。返回 ``{"state": "approved"|"denied"|"asked", "ask_user": ...}``。

    同一件事(同一会话、同一句 ``what``)第一次来 → 记下问题,返回 asked;
    之后某个**人发起的新回合**里再来 → 按那一回合人的原话判。
    """
    turn_id, source, text = _current_turn()
    now = time.time()
    k = _key(session_id, what)
    with _lock:
        for kk in [kk for kk, p in _pending.items() if now - p.asked_at > CONFIRM_TTL_S]:
            _pending.pop(kk, None)
        p = _pending.get(k)
        if p is None:
            _pending[k] = _Pending(session_id=session_id, what=what, asked_in_turn=turn_id, asked_at=now)
            return {"state": "asked", "ask_user": question_for(what)}
        new_human_turn = bool(turn_id) and turn_id != p.asked_in_turn and source in HUMAN_REQUEST_SOURCES
        if not new_human_turn:
            return {"state": "asked", "ask_user": question_for(what), "note": "还在等用户在对话里回答"}
        verdict = interpret_reply(text)
        if verdict is None:
            return {"state": "asked", "ask_user": f"没听清。{question_for(what)}"}
        _pending.pop(k, None)
    logger.info("[AUDIT] 对话确认 | %s | %s | 原话=%r", what, "答应" if verdict else "拒绝", text[:40])
    return {"state": "approved" if verdict else "denied"}


def is_pending(what: str, session_id: str) -> bool:
    """这件事是不是已经在对话里问过、还在等回答。"""
    now = time.time()
    with _lock:
        p = _pending.get(_key(session_id, what))
        return p is not None and now - p.asked_at <= CONFIRM_TTL_S


def reset_conversation_confirmations() -> None:
    """清掉对话里的一切待办:待确认、攒着没说的发现、刚配对待播报的。测试用。"""
    with _lock:
        _pending.clear()
        _just_paired.clear()
    _digest._take()


# ── 播报 ─────────────────────────────────────────────────────────────────────────


def _emit(text: str) -> None:
    """实时推给面板(内存里的一次推送,很便宜)。"""
    try:
        from core.lumiv_websocket_bridge import emit_conversation

        emit_conversation("ai", text, source="devices")
    except Exception as exc:  # noqa: BLE001
        logger.debug("设备播报推面板失败(非致命): %s", exc)


async def _record(text: str) -> None:
    """记进当前对话主线(面板重开时从这里读回来)。

    直接写 SessionManager —— 对话轮次的唯一属主,面板读的就是它。**不走**
    ``record_session_turn``:那条门还会写语义记忆,第一次用时要在事件循环上同步
    加载向量模型(干净环境里还要去下载),网关的事件循环就此卡住,设备连不进来。
    设备播报不需要被语义检索到。
    """
    try:
        from core.conversation_mainline import DEFAULT_MAINLINE_OWNER, mainline_session_id
        from core.session_manager import get_session_manager

        sid = mainline_session_id(create=True)
        if not sid:
            return
        sm = get_session_manager()
        await sm.ensure_session(sid, user_id=DEFAULT_MAINLINE_OWNER)
        await sm.add_message(sid, "assistant", text, metadata={"channel": "devices", "source": "device_onboarding"})
    except Exception as exc:  # noqa: BLE001
        logger.debug("设备播报记进主线失败(非致命): %s", exc)


async def announce(text: str) -> None:
    """作为一句助手发言:推给面板,并记进当前对话主线。失败只记日志。"""
    text = (text or "").strip()
    if text:
        _emit(text)
        await _record(text)


#: 还在跑的播报任务。留着引用,免得任务在跑完前被回收。
_background: set = set()


def announce_soon(text: str) -> None:
    """播报,但**不让调用方等**:配对、注册、工具调用都不该被一句播报拖住。

    推面板当场做;记进对话主线要落盘,丢到后台,调用方不等。
    """
    text = (text or "").strip()
    if not text:
        return
    _emit(text)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(_record(text))
        _background.add(task)
        task.add_done_callback(_background.discard)
        return
    try:
        asyncio.run(_record(text))
    except Exception as exc:  # noqa: BLE001
        logger.debug("设备播报记进主线失败(非致命): %s", exc)


class DiscoveryDigest:
    """把「发现了新设备」攒一小会儿再说一句,免得局域网里一扫出十几台就刷屏。"""

    def __init__(self, delay_s: float = 5.0) -> None:
        self.delay_s = delay_s
        self._names: list = []
        self._scheduled = False
        self._lock = threading.Lock()

    def add(self, name: str, how: str) -> None:
        with self._lock:
            self._names.append((name, how))
            if self._scheduled:
                return
            self._scheduled = True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.flush_now()
            return
        loop.call_later(self.delay_s, lambda: loop.create_task(self._flush()))

    def _take(self) -> list:
        with self._lock:
            names, self._names, self._scheduled = self._names, [], False
        return names

    @staticmethod
    def render(names: list) -> str:
        if not names:
            return ""
        if len(names) == 1:
            name, how = names[0]
            return f"附近发现一台新设备「{name}」({how})。要接入的话跟我说一声。"
        shown = "、".join(f"「{n}」" for n, _ in names[:5])
        more = f"等 {len(names)} 台" if len(names) > 5 else f"共 {len(names)} 台"
        return f"附近发现了新设备:{shown}{more}。想接入哪台跟我说。"

    async def _flush(self) -> None:
        await announce(self.render(self._take()))

    def flush_now(self) -> None:
        announce_soon(self.render(self._take()))


_digest = DiscoveryDigest()

#: 刚配对、还没连上来的设备:device_id → (名字, 配对时刻)。连上时说一声,只说一次。
_just_paired: Dict[str, Tuple[str, float]] = {}
_JUST_PAIRED_TTL_S = 3600.0


def note_new_candidate(name: str, how: str) -> None:
    _digest.add(name, how)


async def note_paired(device_id: str, name: str, device_type: str = "") -> None:
    """配对成功:在对话里说一声,并记下来,等它真正连上时再说一声。"""
    label = name or device_id
    with _lock:
        _just_paired[device_id] = (label, time.time())
    kind = {"windows_laptop": "笔记本", "windows_desktop": "电脑", "wearos": "手表"}.get(device_type, "设备")
    announce_soon(f"{kind}「{label}」配对好了,正在连过来。")


async def note_connected(device_id: str) -> None:
    """设备在规范入口注册成功。是刚配对的那台就说一声「连上了」。"""
    now = time.time()
    with _lock:
        hit = _just_paired.pop(device_id, None)
    if hit and now - hit[1] <= _JUST_PAIRED_TTL_S:
        announce_soon(f"「{hit[0]}」连上了,现在可以让我操作它。")
