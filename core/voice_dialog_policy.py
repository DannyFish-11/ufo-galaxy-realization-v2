"""core/voice_dialog_policy.py — 对话政策(唯一属主)
========================================================

借鉴 GPT-Live(2026-07)的全双工对话体验,把"怎么接话"的政策收进**一个**模块,
供 voice_loop 与 ambient loop 共用(不散落成各处启发式):

1. **语义回合判定**(近似 Semantic VAD):静音≠说完。按转写文本的**内容**判断
   句子是否说完——以连接词/助词/逗号收尾视为"还没说完",动态延长等待窗口,
   让下一个片段并进同一回合,不抢话。
2. **eagerness 旋钮**:GALAXY_VOICE_EAGERNESS = low(耐心)/auto/high(抢答),
   映射等待窗口长短(对齐 OpenAI Realtime API 的 eagerness 设计)。
3. **hold(稍等别说话)**:识别"等一下/别说话/让我想想"→ 安静一个窗口;
   "好了/继续"或窗口到期恢复。ambient 的自发 SPEAK 同受此闸。
4. **委托分类**(对话节奏 ⊥ 推理深度,GPT-Live 的核心创新):把回合分成
   quick(直接答)/heavy(搜索/工具/多步任务)。heavy 由调用方立即致谢
   ("我去查,稍等")并把重活丢后台,结果回来再说——对话不被推理堵死。
5. **捧哏节奏**:后台任务跑着时,按节奏给一两声短填充("嗯,我在看"),
   不让对话死寂;有 hold 时不出声。

纯逻辑、零重依赖、全部可单测。诚实边界:真·全双工(同一时刻边说边听)需要
回声消除+双工模型,本政策做的是"委托+语义回合+填充"三件套——编排层能拿到的
全双工体感,不假装是模型级全双工。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger("Galaxy.VoiceDialogPolicy")


def _flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")


# ── 语义回合判定 ───────────────────────────────────────────────────────────────
# 以这些结尾 → 大概率还没说完(中文连接词/助词/悬垂标点 + 英文连接词)。
_ZH_DANGLING = (
    "然后",
    "接着",
    "再",
    "还有",
    "另外",
    "以及",
    "和",
    "或者",
    "或",
    "但是",
    "但",
    "不过",
    "因为",
    "所以",
    "如果",
    "要是",
    "就是",
    "那个",
    "这个",
    "呃",
    "嗯",
    "把",
    "给",
    "让",
    "帮我",
    "先",
    "比如",
    "还",
    "跟",
    "对了",
)
_EN_DANGLING = (
    "and",
    "or",
    "but",
    "so",
    "then",
    "also",
    "because",
    "if",
    "when",
    "like",
    "the",
    "a",
    "an",
    "to",
    "with",
    "for",
)
_DANGLING_PUNCT = ("，", ",", "、", "…", "——", "-", ":", "：")
# 明确"说完了"的收尾:问号/句号/叹号。
_TERMINAL_PUNCT = ("。", "？", "！", ".", "?", "!", "~", "～")

# eagerness → (悬垂时延长的等待秒数, 无标点长句的基础等待秒数)
_EAGERNESS_WAIT = {
    "low": (1.8, 0.8),  # 耐心:给用户充分思考停顿
    "auto": (1.0, 0.4),
    "high": (0.35, 0.0),  # 抢答:几乎不等
}


def eagerness() -> str:
    v = os.getenv("GALAXY_VOICE_EAGERNESS", "auto").strip().lower()
    return v if v in _EAGERNESS_WAIT else "auto"


def looks_incomplete(text: str) -> bool:
    """转写片段看起来还没说完?(内容判断,而非静音时长)"""
    t = (text or "").strip()
    if not t:
        return False
    if t.endswith(_TERMINAL_PUNCT):
        return False
    if t.endswith(_DANGLING_PUNCT):
        return True
    # 去掉尾部标点后取最后一个词判断
    bare = t.rstrip("".join(_DANGLING_PUNCT + _TERMINAL_PUNCT)).strip()
    if not bare:
        return False
    for w in _ZH_DANGLING:
        if bare.endswith(w):
            return True
    last_en = re.split(r"[\s]+", bare)[-1].lower()
    if last_en in _EN_DANGLING:
        return True
    return False


def end_of_turn_wait(text: str) -> float:
    """本回合在提交前应再等多少秒(0 = 说完了,立即接话)。

    悬垂结尾 → 按 eagerness 给足等待;干净收尾 → 0。
    """
    dangling_wait, base_wait = _EAGERNESS_WAIT[eagerness()]
    t = (text or "").strip()
    if not t:
        return 0.0
    if looks_incomplete(t):
        return dangling_wait
    if not t.endswith(_TERMINAL_PUNCT) and len(t) >= 12:
        # 无终止标点的长句:轻等一拍(ASR 常吞标点),eagerness=high 时为 0
        return base_wait
    return 0.0


# ── hold(稍等别说话)──────────────────────────────────────────────────────────
_HOLD_PATTERNS = (
    "等一下",
    "等等",
    "稍等",
    "先别说话",
    "别说话",
    "让我想想",
    "让我看看",
    "安静一下",
    "闭嘴",
    "hold on",
    "one moment",
    "give me a moment",
    "let me think",
    "wait a sec",
    "be quiet",
)
_RESUME_PATTERNS = (
    "好了",
    "我说完了",
    "继续",
    "可以了",
    "在吗",
    "回来了",
    "ok go",
    "i'm back",
    "im back",
    "continue",
    "go ahead",
)
_DEFAULT_HOLD_S = 90.0


class DialogPolicy:
    """会话级政策状态(hold 窗口 + 捧哏/致谢轮换)。"""

    def __init__(self) -> None:
        self._hold_until: float = 0.0
        self._ack_i = 0
        self._bc_i = 0

    # hold ------------------------------------------------------------------
    def check_hold_command(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return any(p in t for p in _HOLD_PATTERNS)

    def check_resume_command(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return any(p in t for p in _RESUME_PATTERNS)

    def hold(self, seconds: Optional[float] = None) -> None:
        if seconds is None:
            try:
                seconds = float(os.getenv("GALAXY_VOICE_HOLD_S", str(_DEFAULT_HOLD_S)))
            except (ValueError, TypeError):
                seconds = _DEFAULT_HOLD_S
        self._hold_until = time.monotonic() + max(1.0, seconds)
        logger.info("对话 hold %.0fs(用户要求安静)", seconds)

    def release_hold(self) -> None:
        self._hold_until = 0.0

    def is_holding(self) -> bool:
        return time.monotonic() < self._hold_until

    # 委托分类 ----------------------------------------------------------------
    # heavy = 需要搜索/工具/多步执行的任务型回合;quick = 闲聊/短问答。
    _HEAVY_MARKERS = (
        "搜索",
        "搜一下",
        "搜下",
        "查一下",
        "查查",
        "查询",
        "帮我查",
        "联网",
        "帮我做",
        "帮我写",
        "帮我找",
        "帮我生成",
        "帮我下载",
        "帮我安装",
        "帮我部署",
        "帮我整理",
        "帮我分析",
        "帮我总结",
        "执行",
        "运行",
        "跑一下",
        "下载",
        "安装",
        "部署",
        "打开并",
        "整理一下",
        "分析一下",
        "总结一下",
        "search for",
        "look up",
        "find out",
        "download",
        "install",
        "deploy",
        "run the",
        "analyze",
        "summarize",
        "research",
    )
    _MULTI_STEP = re.compile(r"(然后|接着|之后|再).{0,20}(然后|接着|之后|再|最后)")

    def classify_turn(self, text: str) -> str:
        t = (text or "").strip()
        if not t:
            return "quick"
        low = t.lower()
        if any(m in low for m in self._HEAVY_MARKERS):
            return "heavy"
        if self._MULTI_STEP.search(t):
            return "heavy"  # "先…然后…再…" 多步链
        if len(t) >= 60:
            return "heavy"  # 长指令大概率是任务
        return "quick"

    # 致谢 / 捧哏 --------------------------------------------------------------
    _ACKS = ("好,我去处理,稍等。", "收到,这就去办。", "明白,我看一下,马上回来。")
    _BACKCHANNELS = ("嗯,还在处理。", "快好了,再等我一下。")

    def ack_phrase(self) -> str:
        p = self._ACKS[self._ack_i % len(self._ACKS)]
        self._ack_i += 1
        return p

    def backchannel_phrase(self) -> str:
        p = self._BACKCHANNELS[self._bc_i % len(self._BACKCHANNELS)]
        self._bc_i += 1
        return p

    def should_backchannel(self, elapsed_s: float, emitted: int) -> bool:
        """后台任务跑了 elapsed_s 秒、已发过 emitted 次填充,现在该出声吗?

        节奏:首次 ~5s,之后每 ~12s 一次,最多 2 次;关闭开关/hold 时调用方自会跳过。
        """
        if not _flag("GALAXY_VOICE_BACKCHANNEL", "1"):
            return False
        if emitted >= 2:
            return False
        threshold = 5.0 if emitted == 0 else 5.0 + 12.0 * emitted
        return elapsed_s >= threshold


# ── 单例 ──────────────────────────────────────────────────────────────────────
_policy: Optional[DialogPolicy] = None


def get_dialog_policy() -> DialogPolicy:
    global _policy
    if _policy is None:
        _policy = DialogPolicy()
    return _policy


def reset_dialog_policy() -> None:
    global _policy
    _policy = None


def delegation_enabled() -> bool:
    """委托模式开关(默认开):heavy 回合先致谢、后台跑、回来再说。"""
    return _flag("GALAXY_VOICE_DELEGATE", "1")
