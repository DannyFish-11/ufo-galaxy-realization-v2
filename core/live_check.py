"""core/live_check.py —— 边想边说边改的核对线：先说、同时核、错了当场改。

设计见 ``docs/GROUNDED_AGENT_DESIGN.md`` §3。核对**永远不挡第一句话**：它只产出「修订」。

一次回答（一轮）里：

1. **分句**：模型流式出字，凑满一句（。！？；换行）就是一段，按出现先后编号；
2. **要不要核**：只用规则判，不调模型 ——「已经做好了」这类句子、说某台设备在线 / 离线的句子要核；
   开场、过渡、复述、提问不核；
3. **去核**：并发、每轮有上限，按快慢分级。这一期只接**快的两级**，结论都来自类型化的事实，不从文本里反解结构：

   * 「做好了」→ 这一轮**真实的工具结果**（:class:`TurnLedger` 记下的每次调用成没成）；
   * 「X 在线 / 离线」→ 连接管理器此刻的在线表；

4. **结论**：证实 → 不改；驳倒 → 修订（原句留着，后面跟一句更正）；查不到 → 标「未核实」。

修订怎么到各处（§3.4）：

* 面板：SSE 一帧 ``{"type": "revise", ...}``，原句划掉、跟一句更正（``done`` 帧再带一份全量）；
* 记忆与会话：写进去的是**改过的文字**（:func:`corrected_text`）—— 错话不当事实留在上下文里，下一轮不会被当证据；
* 语音：念出去的收不回；整段收尾才念的那条路念改过的版本（只念实质更正，不念「未核实」），边生成边念的口头更正在三期。

本模块在热路径上（每轮一次）：模块级只依赖标准库，不 import ``core.meta``（G10）。
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("Galaxy.LiveCheck")

SUPPORTED = "supported"
REFUTED = "refuted"
UNVERIFIED = "unverified"

#: 一轮里最多为更正打断几次生成(所有者的决定:口头更正每轮最多一两处)。
MAX_CONTINUATIONS = 1
#: 一轮最多核几句（核对是陪跑，不是第二个任务）。
MAX_CHECKS_PER_TURN = 12
#: 收尾时等还没核完的那几句多久（秒）。快的两级都是进程内查表，平时毫秒级。
SETTLE_S = 1.0
#: 一句话太短（「好的。」）不值得核。
_MIN_SENTENCE = 4

_SENT_END = "。！？!?；;\n"

# ── 判要不要核（规则） ──────────────────────────────────────────────────────

#: 说自己已经把一件事做成了。动词表只列会改变外面世界的动作 —— 「我已经知道了」不是在说做了什么。
_DONE = re.compile(
    r"(已经|已|都已|这就|刚刚|刚才)\S{0,6}?"
    r"(打开|关掉|关闭|关上|开启|启动|停止|发送|发出|发给|删除|删掉|移除|保存|安装|装好|卸载|设置|设好|调到|调成|"
    r"执行|运行|完成|搞定|处理|改好|修好|提交|创建|新建|写入|写好|移动|复制|下载|上传|点击|点开|输入|切换|播放|暂停)"
    r"|(完成了|做好了|弄好了|搞定了|办好了|已完成|执行成功|操作成功)"
)
#: 否定 / 将来 / 提问：不是在说「已经做成」。
_NOT_DONE = re.compile(r"(没有|没能|未能|还没|尚未|失败|不能|无法|要不要|需要我|我来|我会|我将|准备|打算|可以帮|是否)")

_ONLINE_WORDS = ("在线", "已连接", "连着", "连上了", "已上线")
_OFFLINE_WORDS = ("离线", "断开", "断线", "没连上", "未连接", "掉线", "不在线")


def split_sentences(text: str) -> Tuple[List[str], str]:
    """切出完整的句子；最后那截没到句界的原样返回（流式时等下一段再说）。"""
    out: List[str] = []
    start = 0
    for i, ch in enumerate(text):
        if ch in _SENT_END:
            piece = text[start : i + 1]
            if piece.strip():
                out.append(piece)
            start = i + 1
    return out, text[start:]


def classify(sentence: str) -> Tuple[str, ...]:
    """这句话要核什么。空元组 = 不核。"""
    s = sentence.strip()
    if len(s) < _MIN_SENTENCE or s.endswith(("？", "?")):
        return ()
    kinds: List[str] = []
    if _DONE.search(s) and not _NOT_DONE.search(s):
        kinds.append("completion")
    if any(w in s for w in _ONLINE_WORDS + _OFFLINE_WORDS):
        kinds.append("device_state")
    return tuple(kinds)


# ── 一轮的账：这一轮真实做了什么 ───────────────────────────────────────────


@dataclass(frozen=True)
class ToolOutcome:
    name: str
    success: bool
    error: str = ""


@dataclass
class Revision:
    seg: int
    original: str
    verdict: str
    note: str
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seg": self.seg,
            "original": self.original,
            "verdict": self.verdict,
            "note": self.note,
            "source": self.source,
        }


def _acting(name: str) -> bool:
    """会改变外面世界的工具才算「做了」(只读的查询不算)。按风险表判,与权限门同一份。"""
    try:
        from core.tool_permissions import get_tool_permission_checker

        policy = get_tool_permission_checker()._find_policy(name)  # noqa: SLF001 — 只读查询,不计频率账
    except Exception:  # noqa: BLE001
        return True
    return policy is None or policy.risk_level.value != "safe"


async def _verify_completion(text: str, outcomes: List[ToolOutcome]) -> Optional[Tuple[str, str, str]]:
    acts = [o for o in outcomes if _acting(o.name)]
    if not acts:
        return UNVERIFIED, "这一轮没有执行任何会改动东西的操作", "turn_ledger"
    ok = [o for o in acts if o.success]
    bad = [o for o in acts if not o.success]
    if not bad:
        return SUPPORTED, "、".join(sorted({o.name for o in ok})) + " 成功", "turn_ledger"
    first = bad[0]
    why = f"{first.name}:{first.error[:80]}" if first.error else first.name
    if not ok:
        return REFUTED, f"这一轮的操作没有成功({why})", "turn_ledger"
    return UNVERIFIED, f"这一轮有 {len(bad)} 个操作没成功({why})", "turn_ledger"


def _known_devices() -> List[Tuple[str, str, bool]]:
    """(设备号, 名字, 在线) —— 每台成员的整体视图(``OnboardingService.member_view``:名字取自设备登记,在线取自
    连接管理器的各通道),与模型经 ``devices__list`` 看到的是同一份。

    此前只读连接管理器:那里的元数据没有名字(规范入口登记时只放 device_type / platform / ingress),于是只有
    模型照原样念出设备号时才核得上 —— 第 8 轮真跑:真连着的「小米手表」被说成离线,核对线一声没吭。
    """
    try:
        from core.device_onboarding.service import get_onboarding_service

        groups = get_onboarding_service().overview()["groups"]
        rows = [
            (str(v["device_id"]), str(v.get("name") or ""), bool(v.get("online"))) for g in groups.values() for v in g
        ]
        if rows:
            return rows
    except Exception as exc:  # noqa: BLE001 — 退回连接管理器
        logger.debug("成员视图不可用,退回在线表: %s", exc)
    try:
        from core.unified.connection_manager import get_unified_connection_manager

        ucm = get_unified_connection_manager()
        rows: List[Tuple[str, str, bool]] = []
        for did, view in ucm.get_presence_view().items():
            info = ucm.get_connection(did)
            meta = getattr(info, "metadata", None) or {}
            name = str(meta.get("device_name") or meta.get("name") or "")
            rows.append((str(did), name, bool(view.get("online"))))
        return rows
    except Exception:  # noqa: BLE001
        return []


async def _verify_device_state(text: str) -> Optional[Tuple[str, str, str]]:
    hits = [d for d in _known_devices() if (d[1] and d[1] in text) or (len(d[0]) >= 4 and d[0] in text)]
    if len(hits) != 1:
        return None  # 说的是哪台认不准:不核,不猜
    did, name, online = hits[0]
    says_offline = any(w in text for w in _OFFLINE_WORDS)
    says_online = not says_offline and any(w in text for w in _ONLINE_WORDS)
    if not (says_online or says_offline):
        return None
    now = "在线" if online else "离线"
    if says_online == online:
        return SUPPORTED, f"{name or did} 现在{now}", "presence"
    return REFUTED, f"{name or did} 现在{now}", "presence"


async def _verify(kinds: Tuple[str, ...], text: str, outcomes: List[ToolOutcome]) -> Optional[Tuple[str, str, str]]:
    """先核最硬的那一条;一条驳倒就是驳倒。"""
    verdicts = []
    if "device_state" in kinds:
        verdicts.append(await _verify_device_state(text))
    if "completion" in kinds:
        verdicts.append(await _verify_completion(text, outcomes))
    verdicts = [v for v in verdicts if v is not None]
    for v in verdicts:
        if v[0] == REFUTED:
            return v
    for v in verdicts:
        if v[0] == UNVERIFIED:
            return v
    return verdicts[0] if verdicts else None


class TurnLedger:
    """一轮的账:这一轮做了哪些工具调用(成没成)、说出去的句子核成了什么。

    建它的是一轮的入口(:func:`open_turn`;流式对话由 ``/api/v1/chat/stream`` 先建好、经上下文传进去),
    工具循环每调一次工具记一笔(:func:`note_tool_outcome`),流式出字时喂给 :meth:`feed`。
    """

    def __init__(self, on_revision: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._on_revision = on_revision
        #: 正在流的那条令牌流(流式对话才有):驳倒一句时请它收住,带着更正接着说
        self.stream: Any = None
        self._continued = 0
        self._outcomes: List[ToolOutcome] = []
        self._buf = ""
        self._seen: Dict[str, int] = {}
        self._revisions: Dict[int, Revision] = {}
        self._tasks: set = set()
        self._gen = 0
        self._checks = 0
        self.started_at = time.time()

    # -- 工具结果 --------------------------------------------------------

    def note(self, name: str, success: bool, error: str = "") -> None:
        self._outcomes.append(ToolOutcome(str(name or ""), bool(success), str(error or "")[:200]))

    def outcomes(self) -> List[ToolOutcome]:
        return list(self._outcomes)

    # -- 流式出字 --------------------------------------------------------

    def feed(self, delta: str) -> None:
        """模型新吐出的一段字。凑满一句就交给核对线;永不抛出(流式通道不能因为核对坏掉)。"""
        try:
            self._buf += delta or ""
            sentences, self._buf = split_sentences(self._buf)
            for s in sentences:
                self._submit(s)
        except Exception as exc:  # noqa: BLE001
            logger.debug("核对线吃字失败(非致命): %s", exc)

    def reset(self) -> None:
        """已流出的内容作废(级联换档 / 工具轮):没核完的作废,核完的结论也不算数。"""
        self._gen += 1
        self._buf = ""
        self._seen.clear()
        self._revisions.clear()
        self._checks = 0
        for task in list(self._tasks):
            task.cancel()

    def _submit(self, sentence: str) -> None:
        key = sentence.strip()
        if not key or key in self._seen:
            return
        seg = len(self._seen)
        self._seen[key] = seg
        kinds = classify(key)
        if not kinds or self._checks >= MAX_CHECKS_PER_TURN:
            return
        self._checks += 1
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        task = loop.create_task(self._check(self._gen, seg, key, kinds))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _check(self, gen: int, seg: int, text: str, kinds: Tuple[str, ...]) -> None:
        try:
            verdict = await _verify(kinds, text, self.outcomes())
        except Exception as exc:  # noqa: BLE001 — 核不了就当没核,不出修订
            logger.debug("核对出错(当没核): %s", exc)
            return
        if verdict is None or gen != self._gen:
            return
        rev = Revision(seg, text, verdict[0], verdict[1], verdict[2])
        self._revisions[seg] = rev
        if rev.verdict == REFUTED and self.stream is not None and self._continued < MAX_CONTINUATIONS:
            # 已说出口、还在生成:请生成在下一段之后收住,带着这条结论接着说(同一个气泡,先更正再往下)
            self._continued += 1
            self.stream.request_stop(continuation_note(rev))
        if rev.verdict != SUPPORTED and self._on_revision is not None:
            try:
                self._on_revision(rev.to_dict())
            except Exception as exc:  # noqa: BLE001
                logger.debug("修订没推出去: %s", exc)

    async def settle(self, text: str = "", timeout: float = SETTLE_S) -> List[Revision]:
        """收尾:把最后那截(和流式没见过的全文句子)交给核对线,等没核完的最多 ``timeout`` 秒。"""
        if self._buf.strip():
            self._submit(self._buf)
            self._buf = ""
        if text:
            sentences, tail = split_sentences(text)
            for s in sentences + ([tail] if tail.strip() else []):
                self._submit(s)
        pending = [t for t in self._tasks if not t.done()]
        if pending:
            await asyncio.wait(pending, timeout=timeout)
        return self.revisions()

    def late_spoken_corrections(self) -> List[str]:
        """生成已经结束才核出来的驳倒:念完之前补一句口头更正(已经打断过生成、让它自己更正了的不重复)。"""
        budget = max(0, MAX_SPOKEN_CORRECTIONS - self._continued)
        refuted = [r for r in self.revisions() if r.verdict == REFUTED][self._continued :]
        return [f"更正一下：{spoken_note(r)}。" for r in refuted[:budget]]

    def revisions(self) -> List[Revision]:
        """不是「证实」的那些修订,按句子先后。"""
        return [r for _, r in sorted(self._revisions.items()) if r.verdict != SUPPORTED]


# ── 一轮的上下文 ─────────────────────────────────────────────────────────────

_TURN: "contextvars.ContextVar[Optional[TurnLedger]]" = contextvars.ContextVar("galaxy_turn_ledger", default=None)


@contextlib.contextmanager
def use_turn(ledger: TurnLedger) -> Iterator[TurnLedger]:
    token = _TURN.set(ledger)
    try:
        yield ledger
    finally:
        _TURN.reset(token)


def open_turn() -> Optional["contextvars.Token"]:
    """一轮开始。上下文里已经有一本(流式对话先建好的)就沿用它,返回 None。"""
    if _TURN.get() is not None:
        return None
    return _TURN.set(TurnLedger())


def close_turn(token: Optional["contextvars.Token"]) -> None:
    if token is not None:
        with contextlib.suppress(ValueError):
            _TURN.reset(token)


def note_tool_outcome(name: str, success: bool, error: str = "") -> None:
    """工具循环每调一次工具记一笔。不在一轮里就什么都不做。永不抛出。"""
    ledger = _TURN.get()
    if ledger is not None:
        with contextlib.suppress(Exception):
            ledger.note(name, success, error)


# ── 把修订用到文字上 ─────────────────────────────────────────────────────────


#: 一轮里最多口头更正几处(所有者的决定)。
MAX_SPOKEN_CORRECTIONS = 2


def spoken_note(rev: Revision) -> str:
    """念出来的那句更正:不念工具名和原始报错,只说人听得懂的那半句。"""
    if rev.source == "turn_ledger":
        return "刚才说的那件事其实没有做成"
    return rev.note


def corrected_text(
    text: str, revisions: List[Revision], *, spoken: bool = False, max_spoken: int = MAX_SPOKEN_CORRECTIONS
) -> str:
    """把修订写进文字:驳倒的跟一句「更正」,查不到的标「未核实」。

    ``spoken=True`` 是要念出来的版本(所有者的决定):只念实质更正,每轮最多 ``max_spoken`` 处,「未核实」不念。
    """
    out = text
    said = 0
    for rev in revisions:
        if rev.original not in out:
            continue
        if rev.verdict == REFUTED:
            if spoken and said >= max_spoken:
                continue
            said += 1
            note = spoken_note(rev) if spoken else rev.note
            out = out.replace(rev.original, f"{rev.original.rstrip()}（更正：{note}）", 1)
        elif rev.verdict == UNVERIFIED and not spoken:
            out = out.replace(rev.original, f"{rev.original.rstrip()}（未核实：{rev.note}）", 1)
        elif rev.verdict == SUPPORTED and not spoken:  # 事后核实了的猜想(core/live_check_late.py)
            out = out.replace(rev.original, f"{rev.original.rstrip()}（已核实：{rev.note}）", 1)
    return out


async def settle_current(text: str, timeout: float = SETTLE_S) -> List[Revision]:
    """当前这一轮:把整段回答交给核对线收尾,拿回修订。不在一轮里返回空。永不抛出。"""
    ledger = _TURN.get()
    if ledger is None:
        return []
    try:
        return await ledger.settle(text, timeout)
    except Exception as exc:  # noqa: BLE001
        logger.debug("核对收尾失败(当没核): %s", exc)
        return []


def stream_ledger(put: Callable[[Tuple[str, Any]], None]) -> Tuple[TurnLedger, Any]:
    """流式对话用:一本账 + 一条接好核对线的令牌流(``core.llm_stream.TokenStream``)。

    出字即进核对线(不等这一帧被消费);核出来不是「证实」的句子经 ``put(("revise", 修订))`` 推出去;
    驳倒一句时请这条流收住、带着更正接着说;已流出的内容作废时核对线一起作废。
    """
    from core.llm_stream import TokenStream

    ledger = TurnLedger(on_revision=lambda rev: put(("revise", rev)))

    def on_delta(text: str) -> None:
        put(("delta", text))
        ledger.feed(text)

    def on_reset() -> None:
        put(("reset", None))
        ledger.reset()

    ledger.stream = TokenStream(on_delta=on_delta, on_reset=on_reset)
    return ledger, ledger.stream


def finish_speaking(speaker: Any, ledger: Optional[TurnLedger]) -> None:
    """边生成边念收尾:先补念生成结束后才核出来的更正(每轮最多两处),再冲刷尾句。人一开口打断,讲话器不再收字,更正随之作废。"""
    if ledger is not None:
        for line in ledger.late_spoken_corrections():
            with contextlib.suppress(Exception):
                speaker.feed(line)
    speaker.finish()


def late_check(result: Any, *, session_id: str, source: str) -> bool:
    """一轮收尾之后:慢的两级(联网核、换一个模型裁决,``core/live_check_late.py``)交给后台。永不抛出。

    在 :func:`close_turn` 之前调:要这一轮的起点(这之后的调用都是这一轮的,裁判不从里面挑)和快的两级已经核过的句子。
    """
    ledger = _TURN.get()
    if ledger is None or not isinstance(result, dict):
        return False
    try:
        from core.live_check_late import after_turn

        already = [r.original for r in ledger.revisions()]
        text = str(result.get("response_original") or result.get("response") or "")
        return after_turn(text, session_id=session_id, source=source, started_at=ledger.started_at, already=already)
    except Exception as exc:  # noqa: BLE001
        logger.debug("事后核对没交出去: %s", exc)
        return False


def continuation_note(rev: Revision) -> str:
    """带给模型接着说的那句核对结论。"""
    return (
        f"[核对] 你刚才说的「{rev.original.strip()}」与这一轮的事实不符:{rev.note}。"
        "请从这里接着说:先用一句话更正它,不要重复前面已经说过的内容。"
    )


def take_correction(sink: Any, partial: str) -> Optional[List[Dict[str, str]]]:
    """生成被核对线收住了:返回要追加进对话、让模型接着说的两条消息;没有就是 None。

    已经说出去的那一截记在 ``sink.prefix``(最终回答 = 前面这些 + 接着说的那一截,见 :func:`full_answer`)。
    """
    if sink is None or not getattr(sink, "stop_requested", False):
        return None
    note = sink.stop_note
    sink.stop_requested = False
    sink.stop_note = ""
    sink.prefix += partial or ""
    return [{"role": "assistant", "content": partial or ""}, {"role": "user", "content": note}]


def full_answer(sink: Any, content: str) -> str:
    """最终回答:被收住之前说出去的 + 最后一次生成的。没被收住过就是 ``content`` 本身。"""
    prefix = getattr(sink, "prefix", "") if sink is not None else ""
    return f"{prefix}{content or ''}" if prefix else (content or "")


async def attach_revisions(result: Any, *, desktop: bool = True) -> None:
    """一轮收尾:修订挂进结果(``revisions``),要念出来的版本放 ``response_spoken``。永不抛出。

    电脑发起的(``desktop=True``):``response`` 不动 —— 面板拿原文 + 修订画「划掉、跟一句更正」(所有者的决定:
    留原文)。别的设备发起的(手表 / 手机只显示一段字):``response`` 换成改过的文字,原文放 ``response_original``。
    """
    if not isinstance(result, dict):
        return
    try:
        text = str(result.get("response") or "")
        revs = await settle_current(text)
        if not revs:
            return
        result["revisions"] = [r.to_dict() for r in revs]
        spoken = corrected_text(text, revs, spoken=True)
        if spoken != text:
            result["response_spoken"] = spoken
        if not desktop:
            result["response_original"] = text
            result["response"] = corrected_text(text, revs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("修订没挂上(非致命): %s", exc)


__all__ = [
    "MAX_CHECKS_PER_TURN",
    "MAX_SPOKEN_CORRECTIONS",
    "REFUTED",
    "Revision",
    "SETTLE_S",
    "SUPPORTED",
    "TurnLedger",
    "UNVERIFIED",
    "attach_revisions",
    "classify",
    "continuation_note",
    "close_turn",
    "corrected_text",
    "finish_speaking",
    "full_answer",
    "late_check",
    "note_tool_outcome",
    "open_turn",
    "settle_current",
    "split_sentences",
    "spoken_note",
    "stream_ledger",
    "take_correction",
    "use_turn",
]
