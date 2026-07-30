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
6. **barge-in 分类**(``classify_barge_in``):朗读期间用户出声,分"应答"与"真打断"。
   人在听别人说话时会一直出声("嗯""对""好""哦")—— 那是积极倾听,不是抢话。原先
   "一出词就掐断"的行为让 AI 每讲两句就被"嗯"一声打断,对话进行不下去。

诚实边界(逐条,不含糊)
------------------------
* **回声消除已经有了。** ``core/multimodal/acoustic_echo_canceller.py`` 在信号层做
  AEC(实测合成路径 27 dB ERLE),参考信号来自系统播放声回环采集。所以"同一时刻边说
  边听"的**听**这一半现在是通的:麦克风可以在朗读期间一直开着,而且能分清谁在说。
* **说的那一半仍是半双工。** 用户真打断时 AI 的反应是**停下来**,不是边说边接话。
  再往前需要双工模型通路(持续上行 + 持续下行的连接),那不是政策层的事。
* **"压低音量继续说"(ducking)做不了。** 现有播放层没有运行期音量控制:edge-tts 的
  ``volume`` 是**合成时**参数(烤进生成的音频里),``_play_audio(path)`` 只是播一个
  文件,``engine.stop()` 只能整段掐断。要做 ducking 得先把播放层换成能在播放中调音量
  的实现 —— 那是另一件事,这里不假装支持,``classify_barge_in`` 只返回"应答/打断"两
  种,不返回一个没人能兑现的 duck。
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Optional

logger = logging.getLogger("Galaxy.VoiceDialogPolicy")


# 统一走 core.config_flags —— 这里原先是 5 份逐字相同的本地 _flag 副本,
# 其中一个真 bug(空值把开关打开)因此要修 5 遍。详见该模块 docstring。
from core.config_flags import flag as _flag  # noqa: E402  (保留 _flag 名字以免动全部调用点)

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


# ── barge-in 分类 ─────────────────────────────────────────────────────────────
#: 用户在 AI 朗读期间出声的两种性质
BARGE_IN_BACKCHANNEL = "backchannel"  # 应答/积极倾听 —— 不该打断
BARGE_IN_INTERRUPT = "interrupt"  # 真的要抢话 —— 立刻掐断

#: 纯应答词。必须是**语义空**的:含任何实义内容都不算应答。
#: 刻意不含"继续"—— 它是 hold 的恢复口令,归 check_resume_command 管。
#:
#: 顺序**无关**:下面会按长度降序排一次再用。剥离时短词先匹配会咬掉长词的前缀 ——
#: 例如先剥 "ok" 会把 "okay" 变成 "ay",于是 "okay" 被误判成打断(实测踩到)。
#: 靠手工把长词写在前面太脆,新增一个词就可能悄悄破功,故程序化排序。
_BACKCHANNEL_TOKENS_RAW = (
    "嗯嗯",
    "嗯",
    "呃",
    "哦",
    "噢",
    "喔",
    "唔",
    "啊",
    "对对",
    "对",
    "是的",
    "是",
    "好的",
    "好",
    "行",
    "可以",
    "没错",
    "明白",
    "懂了",
    "知道了",
    "了解",
    "ok",
    "okay",
    "yeah",
    "yep",
    "yes",
    "uhhuh",
    "mhm",
    "right",
    "sure",
    "gotit",
    "isee",
)

#: 按长度降序:剥离时长词先匹配,避免短词咬掉长词的前缀。
_BACKCHANNEL_TOKENS = tuple(sorted(_BACKCHANNEL_TOKENS_RAW, key=len, reverse=True))

#: 永远算打断的词(与 _HOLD_PATTERNS 一起用)
_STOP_WORDS = ("停", "别念", "别说", "闭嘴", "打住", "stop", "shutup", "waitwait")

#: 超过这个长度就不可能是纯应答了
_MAX_BACKCHANNEL_CHARS = 6

_BACKCHANNEL_STRIP = re.compile(r"[\s,。、;:!?…—~·\"'“”‘’()()《》【】\[\]{}<>/\\|+*=&%$#@^_`,.;:!?~-]+")


def normalize_for_backchannel(text: str) -> str:
    """归一化:去标点空白、英文转小写。ASR 的标点极不稳定,不能参与判断。"""
    return _BACKCHANNEL_STRIP.sub("", (text or "")).lower()


def backchannel_tolerance_enabled() -> bool:
    """是否启用"应答不打断"(默认开启)。

    默认开启是因为反面明显更糟:用户说一声"嗯"就把 AI 的话掐断,是个谁都能立刻察觉的
    毛病。设 ``GALAXY_VOICE_BACKCHANNEL_TOLERANCE=0`` 可退回"一出词就打断"的旧行为。
    """
    return _flag("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", "1")


class DialogPolicy:
    """会话级政策状态(hold 窗口 + 捧哏/致谢轮换 + barge-in 分类)。"""

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

    # barge-in 语义 ----------------------------------------------------------

    def classify_barge_in(self, text: str) -> str:
        """AI 正在朗读时用户出声了 —— 这是"打断"还是"应答"?返回
        ``BARGE_IN_BACKCHANNEL`` 或 ``BARGE_IN_INTERRUPT``。

        为什么需要分开
        --------------
        原先的 barge-in 是"ASR 一出词就掐断朗读"。但人在听别人说话时会一直出声
        ——"嗯""对""好""哦" —— 那是**积极倾听**,不是要抢话。把这些当打断,结果是
        AI 每讲两句就被"嗯"一声打断,对话根本进行不下去。这是"边说边听"体验里最刺眼
        的一处,也是纯政策层就能修的一处。

        判据(刻意保守,宁可判成打断也不要吃掉用户真的要说的话):
        - 归一化后必须**完全由**应答词构成 —— 含任何实义内容即判打断;
        - 且长度不超过 ``_MAX_BACKCHANNEL_CHARS``;
        - 且不含任何停止/hold 类词("停""别说了")—— 那些永远是打断。

        注意本方法**只回答分类**,不关心 AI 此刻是否真在朗读。调用方要先确认在朗读
        中再问 —— AI 没在说话时,"嗯"是一个(弱)用户回合,不是应答。
        """
        # hold / stop 类模式要拿【原始小写文本】去比对,不能用归一化后的文本:
        # _HOLD_PATTERNS 里有 6 个含空格的多词模式("hold on"/"let me think"/"be quiet"…),
        # 而归一化会把空格去掉,那些模式于是永远匹配不到 —— 一个恒为假的 any()。
        # 目前它还不构成行为缺陷(那些句子都会因"含实义内容"落到 interrupt),但只要将来
        # 加进一个短的、恰好全由应答词组成的多词 hold 口令,这道闸门就会静默失效。
        raw = (text or "").strip().lower()
        if any(p in raw for p in _HOLD_PATTERNS) or any(p in raw for p in _STOP_WORDS):
            return BARGE_IN_INTERRUPT

        t = normalize_for_backchannel(text)
        if not t:
            return BARGE_IN_INTERRUPT
        if len(t) > _MAX_BACKCHANNEL_CHARS:
            return BARGE_IN_INTERRUPT
        # 归一化后的文本也过一遍 stop 词:ASR 可能把"别 说 了"断开,去空格后才连成词
        if any(p in t for p in _STOP_WORDS):
            return BARGE_IN_INTERRUPT
        rest = t
        for token in _BACKCHANNEL_TOKENS:
            rest = rest.replace(token, "")
        return BARGE_IN_BACKCHANNEL if not rest.strip() else BARGE_IN_INTERRUPT

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
