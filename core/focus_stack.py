"""core.focus_stack — 焦点栈:让打断与恢复连贯
================================================

问题
-----
主体是**持续在场**的(见 ``DesktopPresenceRuntime`` 的常驻在场),但它的上下文
一直是**扁平**的:会话记忆只是一条按时间排列的轮次流。人不是这么说话的 ——

    "帮我把季度报告整理一下"          ← 事情 A 开始
    "等一下,先看看老王刚发的那条消息"   ← 事情 B 插进来
    "好,回复他'收到'"                 ← 还在 B
    "行了,继续"                       ← 回到 A —— 但"继续"什么?

扁平的轮次流里,"继续"只能靠模型自己从十几轮历史里推断指代。轮次一多,或者中间
插了第三件事,它就开始猜错;猜错的表现是"AI 突然接着讲一件你已经放下的事"。

焦点栈把这层结构**显式**化:当前在做什么、被搁下的还有哪些、各自搁了多久。它作为
一段上下文喂给模型,"继续"就有了确定的指代。

判定规则(廉价、无模型)
------------------------
词法工具与 ACI 同源(``core.anticipatory_context`` 的实词切分),理由和那边一样:
引入分词器/分类器就等于引入一个模型和一份词典,而这条路径要在每一轮用户发言上跑。
相似度用**包含度**而非 Jaccard,原因见 :func:`_containment`。

    与当前焦点词法相近      → 还在同一件事,只更新它(touch)
    是一句纯延续句          → 还在同一件事(它的语义依附于当前焦点)
    与某个**被挂起**的焦点相近 → 恢复那个焦点(它重新成为当前),不新建
    都不像                  → 新焦点入栈,当前焦点被压下去

第三条是这个结构真正值钱的地方:"回到报告那件事"能被认出来是**恢复**而不是
第三件新事,于是栈不会无限增长,而且模型拿到的是"回到 A"而不是"又来了个 C"。

刻意的边界
-----------
* **不做语义理解**。词法相近判不出"那份文件"和"季度报告"是同一件事;也判不出
  "回复老王一句收到"与"看看老王刚发的消息"是同一件事 —— 两句只共享"老王"这一个
  专名,占比不过阈值。判错的代价是栈里多一个条目:上下文里多一行,栈深有上限、
  会被淘汰收口,**不会造成错误行为**。宁可多一个条目,也不引入一个要占算力、
  还会给出置信度未知答案的分类器。这条限制是明知的,由
  ``tests/test_focus_stack.py::TestKnownLexicalLimits`` 如实记录而非掩盖。
* **不自动结束焦点**。人很少显式说"这件事做完了"。所以用**容量 + 陈旧淘汰**收口:
  栈深有上限,太久没碰的焦点自动掉出。焦点栈是**工作记忆**,不是任务清单 ——
  任务清单是另一件事,有它自己的存储。
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.FocusStack")

#: 栈深上限(含当前焦点)。人同时挂着的事情很少超过这个数;超了就淘汰最陈旧的。
_DEFAULT_MAX_DEPTH = 5

#: 陈旧阈值(秒)。超过这么久没被碰过的**挂起**焦点自动掉出 —— 那多半已经不做了。
#: 当前焦点不受此限:它是"正在做的事",不该因为思考久了就消失。
_DEFAULT_STALE_S = 1800.0

#: 判"还在同一件事"的包含度阈值:这句话的词法特征里有多大比例已经属于该焦点。
#: 判错的代价小(栈里多一个条目),所以取值比 ACI 的命中阈值宽松 —— ACI 判错是把
#: 无关记忆喂给模型,量级完全不同。
_DEFAULT_SAME_TOPIC_OVERLAP = 0.25

#: 判"恢复某个挂起焦点"的阈值。**高于**同题阈值 —— 恢复是更强的断言,它会改变
#: 栈的形状(把一个挂起项拉回当前),所以要求更像才做。
_DEFAULT_RESUME_OVERLAP = 0.35


def focus_stack_enabled() -> bool:
    return str(os.getenv("GALAXY_FOCUS_STACK_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off")


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


@dataclass
class Focus:
    """一件正在做或被搁下的事。"""

    topic: str
    tokens: set = field(default_factory=set)
    opened_at: float = field(default_factory=time.time)
    last_touched: float = field(default_factory=time.time)
    touches: int = 1

    def touch(self, text: str = "") -> None:
        self.last_touched = time.time()
        self.touches += 1
        if text:
            # 焦点的词法指纹随对话累积 —— 一件事被谈得越多,越容易被认出来。
            self.tokens |= topic_tokens(text)

    def as_dict(self) -> Dict[str, Any]:
        now = time.time()
        return {
            "topic": self.topic,
            "opened_at": self.opened_at,
            "age_s": round(max(0.0, now - self.opened_at), 3),
            "idle_s": round(max(0.0, now - self.last_touched), 3),
            "touches": self.touches,
        }


class FocusStack:
    """一个会话的焦点栈。栈顶 = 当前焦点。"""

    def __init__(self) -> None:
        self._stack: List[Focus] = []

    # ── 状态 ────────────────────────────────────────────────────────────────

    @property
    def current(self) -> Optional[Focus]:
        return self._stack[-1] if self._stack else None

    @property
    def suspended(self) -> List[Focus]:
        """被挂起的焦点,**由近及远** —— 最近搁下的排在最前,与人的直觉一致。"""
        return list(reversed(self._stack[:-1]))

    def depth(self) -> int:
        return len(self._stack)

    # ── 推进 ────────────────────────────────────────────────────────────────

    def observe(self, text: str) -> Dict[str, Any]:
        """观察一句用户发言,更新栈。返回本次发生了什么(供观测与测试)。

        ``action`` 取值:``"opened"`` | ``"continued"`` | ``"resumed"`` | ``"ignored"``。
        """
        from core.anticipatory_context import is_continuation

        text = (text or "").strip()
        if not text or not focus_stack_enabled():
            return {"action": "ignored", "reason": "empty_or_disabled"}

        self._evict_stale()
        tokens = topic_tokens(text)

        # 纯延续句:语义依附当前焦点。没有当前焦点时它不成立(没什么可继续的),
        # 也不该拿它去开一个以"继续"为题的新焦点 —— 那是个没有内容的题目。
        if is_continuation(text):
            cur = self.current
            if cur is None:
                return {"action": "ignored", "reason": "continuation_without_focus"}
            cur.touch()
            return {"action": "continued", "topic": cur.topic, "reason": "continuation"}

        cur = self.current
        cur_score = _containment(tokens, cur.tokens) if cur is not None else 0.0
        if cur is not None and cur_score >= _env_float("GALAXY_FOCUS_SAME_TOPIC_OVERLAP", _DEFAULT_SAME_TOPIC_OVERLAP):
            cur.touch(text)
            return {"action": "continued", "topic": cur.topic, "reason": "lexical_same_topic"}

        # 恢复:与某个挂起的焦点足够像 → 把它拉回栈顶,而不是新建第三件事。
        # 还要求它比当前焦点更像 —— 否则就该留在当前焦点上(那条已经在上面判过了,
        # 这里防的是"两边都不过同题阈值、但当前焦点其实更接近"的情形)。
        resume_threshold = _env_float("GALAXY_FOCUS_RESUME_OVERLAP", _DEFAULT_RESUME_OVERLAP)
        best_idx, best_score = -1, 0.0
        for idx, focus in enumerate(self._stack[:-1]):
            score = _containment(tokens, focus.tokens)
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx >= 0 and best_score >= resume_threshold and best_score > cur_score:
            focus = self._stack.pop(best_idx)
            focus.touch(text)
            self._stack.append(focus)
            logger.debug("焦点恢复: %s(相似度 %.2f)", focus.topic[:30], best_score)
            return {"action": "resumed", "topic": focus.topic, "reason": "lexical_resume"}

        focus = Focus(topic=_summarise(text), tokens=set(tokens))
        self._stack.append(focus)
        self._enforce_depth()
        logger.debug("新焦点入栈: %s(栈深 %d)", focus.topic[:30], len(self._stack))
        return {"action": "opened", "topic": focus.topic, "reason": "new_topic"}

    def drop_current(self) -> Optional[Focus]:
        """显式结束当前焦点,上一个自动恢复为当前。"""
        return self._stack.pop() if self._stack else None

    def clear(self) -> None:
        self._stack.clear()

    # ── 收口 ────────────────────────────────────────────────────────────────

    def _evict_stale(self) -> None:
        """淘汰太久没碰的**挂起**焦点。当前焦点不受此限。"""
        stale_s = _env_float("GALAXY_FOCUS_STALE_S", _DEFAULT_STALE_S)
        if stale_s <= 0 or len(self._stack) <= 1:
            return
        now = time.time()
        keep = [f for f in self._stack[:-1] if now - f.last_touched <= stale_s]
        if len(keep) != len(self._stack) - 1:
            logger.debug("焦点栈淘汰 %d 个陈旧挂起项", len(self._stack) - 1 - len(keep))
        self._stack = keep + self._stack[-1:]

    def _enforce_depth(self) -> None:
        """超深时丢掉**最陈旧的挂起项**,而不是最早入栈的。

        按入栈顺序丢会把"很早开始、但一直在做"的那件事丢掉 —— 那恰恰是最不该丢的。
        """
        max_depth = _env_int("GALAXY_FOCUS_MAX_DEPTH", _DEFAULT_MAX_DEPTH)
        while len(self._stack) > max_depth:
            suspended = self._stack[:-1]
            victim = min(suspended, key=lambda f: f.last_touched)
            self._stack.remove(victim)

    # ── 输出 ────────────────────────────────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        return {
            "depth": len(self._stack),
            "current": self.current.as_dict() if self.current else None,
            "suspended": [f.as_dict() for f in self.suspended],
        }

    def as_context_message(self) -> Optional[Dict[str, str]]:
        """渲染成一条可直接喂给模型的 system 消息;栈为空时返回 None。

        只在**有挂起项**时才输出挂起清单:栈里只有一件事的时候,把它复述一遍是
        纯噪声(轮次历史里已经有了),白占上下文窗口。
        """
        cur = self.current
        if cur is None:
            return None
        lines = [f"当前焦点:{cur.topic}"]
        suspended = self.suspended
        if suspended:
            lines.append("被搁置的事项(由近及远,用户说“继续/回到刚才”时优先指这些):")
            lines.extend(f"  {i + 1}. {f.topic}(搁置 {int(f.as_dict()['idle_s'])} 秒)" for i, f in enumerate(suspended))
        elif cur.touches <= 1:
            # 只有一件事、而且才刚开始 —— 没有任何结构信息可传达。
            return None
        return {"role": "system", "content": "[焦点栈]\n" + "\n".join(lines)}


_CJK_RUN_RE = None  # 惰性编译,见 topic_tokens


def topic_tokens(text: str) -> set:
    """抽话题级词法特征:**非停用实词的 unigram ∪ 相邻 bigram**。

    为什么不直接复用 ACI 的 ``content_tokens``
    -------------------------------------------
    两边比的东西不一样,所以判据也不该一样:

    * ACI 比的是**问句与问句**。它要认的是"几乎同一个问题"(改了一两个字的重述),
      高阈值 + 单字特征就够,而且单字特征更稳。
    * 焦点栈比的是**一句话与一个累积起来的话题**。人复述同一件事时用词会变
      ("季度报告"→"那份报告"→"报告的营收部分"),要认出来靠的是**词**而不是**字**。

    中文没有空格,单字切分下"一、下、那、事、于、上、中"这类高频字会制造大量
    假匹配 —— 两句毫不相干的话也能共享三四个这样的字。把相邻字组成 bigram
    ("季度""报告""老王""消息")就把粒度提到了词级:bigram 的区分度远高于单字,
    而这仍然只是字符串切片,**没有引入词典,也没有引入模型**。

    并集而非只取 bigram:只取 bigram 对改写太脆(换一个字,跨过它的两个 bigram
    同时失效);unigram 提供一层软兜底。这是 CJK 检索里的常规做法。
    """
    global _CJK_RUN_RE
    if _CJK_RUN_RE is None:
        _CJK_RUN_RE = re.compile(r"[一-鿿]+|[a-zA-Z0-9_]+")

    from core.anticipatory_context import _STOPWORDS

    tokens: set = set()
    for match in _CJK_RUN_RE.finditer(text or ""):
        chunk = match.group(0)
        if chunk[0].isascii():
            low = chunk.lower()
            if low not in _STOPWORDS and len(low) > 1:
                tokens.add(low)
            continue
        # 先剔停用字,再在**剩下的相邻字**之间组 bigram。先剔后组是有意的:
        # "报告的营收"里"告的""的营"都是噪声,剔掉"的"之后才得到"报告""营收"。
        kept = [ch for ch in chunk if ch not in _STOPWORDS]
        tokens.update(kept)
        tokens.update(a + b for a, b in zip(kept, kept[1:]))
    return tokens


def _containment(utterance: set, focus: set) -> float:
    """这句话里有多大比例的实词已经属于该焦点。

    **不是 Jaccard。** 第一版用的是对称 Jaccard,方向是错的:焦点的词法指纹会随
    对话累积(见 ``Focus.touch``),于是一件被谈得越多的事,词集越大、并集越大、
    Jaccard 越小 —— 越难被匹配上。这与直觉完全相反:谈得越久的话题应该**越容易**
    被认出来才对。

    改成非对称的包含度(|A∩B| / |A|)后,分母只跟当前这句话的长度有关,焦点积累
    多少词都不会稀释它。这也更贴合要问的问题:"你刚说的这些,是不是已经在这件事
    的范围里了"。
    """
    if not utterance or not focus:
        return 0.0
    return len(utterance & focus) / len(utterance)


def _summarise(text: str, limit: int = 40) -> str:
    """把一句发言压成一个焦点标题。截断而非摘要 —— 摘要要模型。"""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


# ---------------------------------------------------------------------------
# 每会话注册表
# ---------------------------------------------------------------------------

_stacks: Dict[str, FocusStack] = {}
_MAX_SESSIONS = 32


def get_focus_stack(session_id: str) -> FocusStack:
    """取(或建)某个会话的焦点栈。"""
    stack = _stacks.get(session_id)
    if stack is None:
        stack = FocusStack()
        _stacks[session_id] = stack
        if len(_stacks) > _MAX_SESSIONS:
            # 焦点栈是工作记忆,丢掉最老的会话不影响正确性。
            for sid in list(_stacks)[: len(_stacks) - _MAX_SESSIONS]:
                _stacks.pop(sid, None)
    return stack


def reset_focus_stacks() -> None:
    """测试用。"""
    _stacks.clear()
