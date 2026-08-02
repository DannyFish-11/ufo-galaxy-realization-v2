"""core.anticipatory_context — 预判式上下文注入(ACI)
======================================================

要解决的延迟在哪
-----------------
``core.session_memory_facade.get_unified_context`` 是全仓**唯一**的记忆读入口,
而它是**同步**的,却要在一次调用里跑完:长期记忆全量列举 → 跨 4 个 namespace 的
BM25 检索 → 会话历史 → 自适应任务史 → 事件链 → 向量语义召回。这一整套压在请求
路径上,用户每问一句都要等它跑完才轮到模型开口。

它在"一问一答"里不显眼(反正模型也要想几百毫秒),但在**持续在场**的主体上就很刺眼:
双工语音里人是连着说的,每一轮前面都插着这么一段串行 I/O。

ACI 的做法
-----------
一轮对话**结束之后**,趁着没人说话的空档,用**廉价预判**猜下一轮大概会问什么,
提前把上下文组装好放进缓存;下一轮真来的时候若猜中,直接拿走,那段 I/O 的耗时
从请求路径上消失。猜错就是普通的 miss —— 退化成今天的行为,一分钱不多花。

"绝不占本地模型算力"是硬约束
-----------------------------
这台机器上的本地模型(视觉/语音/推理)是主体的感官和思考本身,预判是**辅助**,
辅助不能跟本体抢算力。所以:

* **预判不用模型**。纯词法:上一轮用户问句 + 助手回答里的高频实词。没有 LLM 调用、
  没有 embedding、没有分类器。
* **预取只做 I/O**,而且丢到工作线程,不占事件循环。(向量后端在装了 chromadb 时
  会为 query 算一次句向量 —— 那是几毫秒的小模型,与本地大模型不是一回事;没装
  chromadb 时后端自动降级成关键词检索,连这个都没有。)
* **只在请求空档跑**。有请求在飞就不预取;预取排队时又来了新请求就直接放弃。
  宁可不预取,也不跟正在服务用户的那条路径抢。

安全性:为什么"猜错了"不会污染上下文
-------------------------------------
把为 Q1 组装的上下文喂给 Q2 是有害的 —— 它会让模型看见与当前问题无关的记忆。
所以命中判定是**保守**的,四道闸:

1. **同一会话**。缓存按 session_id 分槽,跨会话永不复用。
2. **轮次没变**。上下文里含最近若干轮对话;预取之后若又落了新轮次,缓存即作废
   (``turn_epoch`` 不等就丢)。这条保证缓存不会比现算的少一轮内容。
3. **词法足够接近**。精确匹配,或实词 Jaccard ≥ 阈值。
4. **一次性**。取走即失效,一份预取不会喂给两个不同的问题。

外加 TTL 与容量上限。任何一道不过就是 miss,走原路现算 —— 最坏情况等于没装 ACI。

第三条有一个刻意的例外:**纯延续句**("继续""然后呢""再来一个")本身没有实词,
按 Jaccard 必然 miss,但它恰恰是最该命中的一类 —— 它的语义完全依附于上一轮。
所以为它单开一条规则:仅当预取条目是**由上一轮用户问句派生**(kind=topic_continuity)
时才允许延续句命中。这是有意的语义判断,不是把阈值放松。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("Galaxy.ACI")

#: 预判条目的存活时间。超过就作废 —— 上下文里的"最近任务史/事件链"会随时间变化。
_DEFAULT_TTL_S = 120.0

#: 每个会话最多缓存几条预判。多了收益递减(猜第 4 个的命中率很低),却按倍数占内存。
_DEFAULT_MAX_PER_SESSION = 3

#: 最多同时缓存几个会话。防止长期运行后无界增长。
_DEFAULT_MAX_SESSIONS = 32

#: 一轮结束到开始预取之间的静默期。给请求路径留出彻底收尾的时间(结果落盘、
#: 事件发射、朗读启动),避免预取和收尾抢线程池。
_DEFAULT_SETTLE_DELAY_S = 1.2

#: 实词 Jaccard 命中阈值。0.6 是刻意偏保守的取值:宁可 miss(退化成现算)也不要
#: 把为另一个问题组装的上下文喂进来。
_DEFAULT_JACCARD_THRESHOLD = 0.6

#: 延续句识别:短且以这些词起头/构成。命中它们的问句语义完全依附上一轮。
_CONTINUATION_MARKERS = (
    "继续",
    "然后呢",
    "然后",
    "接着",
    "再来",
    "再说说",
    "还有呢",
    "还有吗",
    "go on",
    "continue",
    "and then",
    "more",
)

#: 停用词。只用于**预判**(从助手回答里挑实词),不参与命中判定的正确性,
#: 所以不必完备 —— 漏掉几个只会让预判稍差一点,不会造成错误命中。
_STOPWORDS = {
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "也",
    "都",
    "就",
    "而",
    "你",
    "我",
    "他",
    "她",
    "它",
    "这",
    "那",
    "有",
    "没",
    "不",
    "吗",
    "呢",
    "吧",
    "啊",
    "个",
    "一个",
    "可以",
    "已经",
    "需要",
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "and",
    "or",
    "in",
    "on",
    "for",
    "it",
    "this",
    "that",
    "you",
    "i",
    "we",
    "they",
    "can",
    "will",
    "have",
    "has",
    "with",
}

#: 实词切分:连续的中文字符按单字切(中文没有空格),拉丁字母/数字按词切。
#: 用最朴素的办法是刻意的 —— 引入分词器就等于引入一个模型和一份词典。
_TOKEN_RE = re.compile(r"[a-zA-Z0-9_]+|[一-鿿]")


def aci_enabled() -> bool:
    """ACI 是否启用。默认开 —— 四道闸决定了最坏情况等于没装它。"""
    return str(os.getenv("GALAXY_ACI_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except (TypeError, ValueError):
        return default


def normalize_query(text: str) -> str:
    """归一化问句:去首尾空白、压缩内部空白、小写。用于精确匹配。"""
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def content_tokens(text: str) -> set:
    """抽实词集合。停用词与单个拉丁字符被剔除。"""
    return {t for t in (m.group(0).lower() for m in _TOKEN_RE.finditer(text or "")) if t not in _STOPWORDS}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def is_continuation(text: str) -> bool:
    """是不是一句"纯延续"——语义完全依附上一轮、自身没有内容。"""
    norm = normalize_query(text)
    if not norm:
        return True
    if len(norm) > 12:
        return False
    return any(norm.startswith(m) or norm == m for m in _CONTINUATION_MARKERS) or not content_tokens(norm)


@dataclass
class _Entry:
    """一条预取好的上下文。"""

    query: str
    tokens: set
    normalized: str
    messages: List[Dict[str, str]]
    turn_epoch: int
    created_at: float
    kind: str  # "topic_continuity"(由上一轮用户问句派生) | "assistant_topic"


@dataclass
class _SessionSlot:
    entries: List[_Entry] = field(default_factory=list)
    turn_epoch: int = 0
    inflight: int = 0
    last_touch: float = field(default_factory=time.time)


class AnticipatoryContext:
    """ACI 的进程内状态。用 :func:`get_anticipatory_context` 取单例。"""

    def __init__(self) -> None:
        self._slots: Dict[str, _SessionSlot] = {}
        self._tasks: set = set()
        self._stats: Dict[str, int] = {
            # 计数单位必须写清楚。真跑时看到 scheduled=2 / completed=4,还以为
            # "完成得比安排的还多" —— 其实一次 schedule 会预取 1~2 条(每条预判一次),
            # 两个数根本不同量纲。改名把单位钉在名字里。
            "prefetch_runs_scheduled": 0,  # 安排过几次预取(每轮对话结束最多一次)
            "prefetch_entries_cached": 0,  # 真正存进缓存的条目数(一次预取可产出多条)
            "prefetch_skipped_busy": 0,
            "prefetch_failed": 0,
            # take() 被调用但**会话 ID 为空**的次数。这条是真跑逼出来的:原先这种
            # 情况直接 return None 且不计数,于是"门根本没被调用"和"门被调用了但
            # 调用方没给会话 ID"在统计上完全一样 —— 而后者是接线错误,前者不是。
            # 排查时这两种要花完全不同的力气去查,不能混。
            "take_without_session": 0,
            "hit_exact": 0,
            "hit_lexical": 0,
            "hit_continuation": 0,
            "miss": 0,
            "expired": 0,
            "stale_epoch": 0,
        }

    # ── 会话槽 ──────────────────────────────────────────────────────────────

    def _slot(self, session_id: str) -> _SessionSlot:
        slot = self._slots.get(session_id)
        if slot is None:
            slot = _SessionSlot()
            self._slots[session_id] = slot
            self._evict_sessions()
        slot.last_touch = time.time()
        return slot

    def _evict_sessions(self) -> None:
        limit = _env_int("GALAXY_ACI_MAX_SESSIONS", _DEFAULT_MAX_SESSIONS)
        if len(self._slots) <= limit:
            return
        # 按最后触碰时间淘汰最旧的。会话槽只是缓存,丢掉不影响正确性。
        for sid, _ in sorted(self._slots.items(), key=lambda kv: kv[1].last_touch)[: len(self._slots) - limit]:
            self._slots.pop(sid, None)

    # ── 请求在飞与轮次计数(命中判定的两块地基)────────────────────────────

    def note_context_requested(self, session_id: str) -> None:
        """有请求开始组装上下文了 —— 从这一刻起不许预取。"""
        self._slot(session_id).inflight += 1

    def note_turn_recorded(self, session_id: str, role: str = "") -> None:
        """记下一轮已落库:轮次计数 +1,并把该会话的既有预判全部作废。

        为什么必须作废:上下文里含"最近若干轮对话",轮次一变,之前预取的那份就
        **少一轮**。让它继续命中等于给模型一份删掉了最新对话的上下文。
        """
        slot = self._slot(session_id)
        slot.turn_epoch += 1
        if slot.entries:
            self._stats["stale_epoch"] += len(slot.entries)
            slot.entries.clear()
        if role == "assistant":
            # 助手轮次落库 = 这一次请求真的收尾了。
            slot.inflight = max(0, slot.inflight - 1)

    # ── 取(请求路径上,必须极快)────────────────────────────────────────────

    def take(self, session_id: str, query: str) -> Optional[List[Dict[str, str]]]:
        """尝试取走一份预取好的上下文。未命中返回 None。

        本方法在请求热路径上被调用,只做集合运算,不做任何 I/O。
        """
        if not aci_enabled():
            return None
        if not session_id:
            self._stats["take_without_session"] += 1
            return None
        slot = self._slots.get(session_id)
        if slot is None or not slot.entries:
            self._stats["miss"] += 1
            return None

        ttl = _env_float("GALAXY_ACI_TTL_S", _DEFAULT_TTL_S)
        now = time.time()
        fresh: List[_Entry] = []
        for e in slot.entries:
            if now - e.created_at > ttl:
                self._stats["expired"] += 1
            elif e.turn_epoch != slot.turn_epoch:
                self._stats["stale_epoch"] += 1
            else:
                fresh.append(e)
        slot.entries = fresh
        if not fresh:
            self._stats["miss"] += 1
            return None

        norm = normalize_query(query)
        tokens = content_tokens(query)

        # 闸 3a:精确匹配。
        for e in fresh:
            if e.normalized and e.normalized == norm:
                return self._consume(slot, e, "hit_exact")

        # 闸 3b:实词 Jaccard。
        threshold = _env_float("GALAXY_ACI_JACCARD", _DEFAULT_JACCARD_THRESHOLD)
        best, best_score = None, 0.0
        for e in fresh:
            score = _jaccard(tokens, e.tokens)
            if score > best_score:
                best, best_score = e, score
        if best is not None and best_score >= threshold:
            return self._consume(slot, best, "hit_lexical")

        # 闸 3c:纯延续句 —— 只认由上一轮用户问句派生的那条。
        if is_continuation(query):
            for e in fresh:
                if e.kind == "topic_continuity":
                    return self._consume(slot, e, "hit_continuation")

        self._stats["miss"] += 1
        return None

    def _consume(self, slot: _SessionSlot, entry: _Entry, stat_key: str) -> List[Dict[str, str]]:
        """闸 4:取走即失效。一份预取绝不喂给两个不同的问题。"""
        slot.entries = [e for e in slot.entries if e is not entry]
        self._stats[stat_key] += 1
        logger.debug("ACI 命中(%s) query=%s kind=%s", stat_key, entry.query[:40], entry.kind)
        return list(entry.messages)

    # ── 预判与预取(空档期,后台线程)────────────────────────────────────────

    @staticmethod
    def predict_queries(
        last_user_query: str,
        last_assistant_text: str = "",
        *,
        limit: int = 2,
    ) -> List[tuple]:
        """廉价预判:下一轮大概会问什么。**不调用任何模型。**

        返回 ``[(query, kind), ...]``,两个来源、按可靠性排序:

        1. ``topic_continuity`` —— **上一轮用户问句**。追问在词面上往往很稀薄
           ("那再改一下"),但检索需要的 topic 与上一轮几乎一致,所以直接拿上一轮
           的问句去预取,是命中率最高的一条,也是**延续句唯一允许命中**的那条。
        2. ``assistant_topic`` —— **助手刚讲过的实词**。人的下一个问题常常落在 AI
           刚提到的东西上。取词频最高的若干实词拼成伪查询,足够让 BM25/向量检索
           定位到同一片区域。

        为什么返回 kind 而不是让调用方按下标猜:曾经就是按 ``idx == 0`` 判定的,
        于是"没有上一轮用户问句、只有助手文本"时,助手猜测条目落在 0 号位、被错标成
        ``topic_continuity`` —— 一句没有内容的"继续"就能命中一份**纯猜测**的上下文。
        种类是条目的固有属性,必须跟着条目走。
        """
        out: List[tuple] = []
        primary = (last_user_query or "").strip()
        if primary:
            out.append((primary, "topic_continuity"))

        if last_assistant_text and len(out) < limit:
            freq: Dict[str, int] = {}
            for tok in (m.group(0).lower() for m in _TOKEN_RE.finditer(last_assistant_text)):
                if tok in _STOPWORDS or (len(tok) == 1 and tok.isascii()):
                    continue
                freq[tok] = freq.get(tok, 0) + 1
            top = [t for t, _ in sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))[:8]]
            if top:
                out.append((" ".join(top), "assistant_topic"))
        return out[:limit]

    def schedule_after_turn(
        self,
        session_id: str,
        *,
        last_user_query: str,
        last_assistant_text: str = "",
    ) -> Optional[asyncio.Task]:
        """一轮结束后安排预取。返回后台任务(便于测试);未安排时返回 None。

        fire-and-forget:调用方绝不 await 它,预取失败也绝不影响对话。
        """
        if not aci_enabled() or not session_id:
            return None
        queries = self.predict_queries(last_user_query, last_assistant_text)
        if not queries:
            return None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 没有事件循环(同步上下文)就不预取。宁可不做,也不另起线程池:
            # 那会绕过下面"有请求在飞就放弃"的闸门。
            return None

        self._stats["prefetch_runs_scheduled"] += 1
        task = loop.create_task(self._prefetch(session_id, queries))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def _prefetch(self, session_id: str, queries: Sequence[tuple]) -> None:
        slot = self._slot(session_id)
        epoch_at_schedule = slot.turn_epoch
        try:
            await asyncio.sleep(_env_float("GALAXY_ACI_SETTLE_DELAY_S", _DEFAULT_SETTLE_DELAY_S))
        except asyncio.CancelledError:
            raise

        # 静默期里情况可能已经变了:新请求进来了,或者又落了一轮。两种都放弃 ——
        # 前者是"不跟正在服务用户的路径抢",后者是"算出来也已经过期"。
        if slot.inflight > 0 or slot.turn_epoch != epoch_at_schedule:
            self._stats["prefetch_skipped_busy"] += 1
            return

        for query, kind in queries:
            if slot.inflight > 0 or slot.turn_epoch != epoch_at_schedule:
                self._stats["prefetch_skipped_busy"] += 1
                return
            try:
                messages = await asyncio.to_thread(self._load_context, session_id, query)
            except Exception as exc:  # noqa: BLE001
                self._stats["prefetch_failed"] += 1
                logger.debug("ACI 预取失败(忽略) query=%s: %s", query[:40], exc)
                continue
            if not messages:
                continue
            # 再查一次:预取本身耗时,期间可能又变了。写进去前必须重验。
            if slot.turn_epoch != epoch_at_schedule:
                self._stats["stale_epoch"] += 1
                return
            entry = _Entry(
                query=query,
                tokens=content_tokens(query),
                normalized=normalize_query(query),
                messages=messages,
                turn_epoch=epoch_at_schedule,
                created_at=time.time(),
                kind=kind,
            )
            slot.entries.append(entry)
            max_per = _env_int("GALAXY_ACI_MAX_PER_SESSION", _DEFAULT_MAX_PER_SESSION)
            if len(slot.entries) > max_per:
                slot.entries = slot.entries[-max_per:]
            self._stats["prefetch_entries_cached"] += 1

    @staticmethod
    def _load_context(session_id: str, query: str) -> List[Dict[str, str]]:
        """在工作线程里跑那段昂贵的同步组装。

        惰性 import:``session_memory_facade`` 会 import 本模块(取门),顶层互 import
        会成环。
        """
        from core.session_memory_facade import build_unified_context_uncached

        return build_unified_context_uncached(session_id, query)

    # ── 观测 ────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """命中统计。``hit_rate`` 只在有过取用尝试时才有意义。"""
        hits = self._stats["hit_exact"] + self._stats["hit_lexical"] + self._stats["hit_continuation"]
        attempts = hits + self._stats["miss"]
        return {
            **self._stats,
            "hits": hits,
            "attempts": attempts,
            "hit_rate": round(hits / attempts, 4) if attempts else 0.0,
            "enabled": aci_enabled(),
            "sessions_tracked": len(self._slots),
        }

    def reset(self) -> None:
        """测试用:清空全部状态。"""
        self._slots.clear()
        for t in list(self._tasks):
            t.cancel()
        self._tasks.clear()
        for k in self._stats:
            self._stats[k] = 0


_instance: Optional[AnticipatoryContext] = None


def get_anticipatory_context() -> AnticipatoryContext:
    global _instance
    if _instance is None:
        _instance = AnticipatoryContext()
    return _instance


def reset_anticipatory_context() -> None:
    """测试用。"""
    global _instance
    if _instance is not None:
        _instance.reset()
    _instance = None
