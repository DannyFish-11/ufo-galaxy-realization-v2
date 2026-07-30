"""core.voice_echo_guard — 反自激励门:分辨"麦克风听到的是用户,还是 AI 自己"。

要解决的真实缺陷
----------------
本地语音闭环是 ``麦克风 → VAD → Whisper → VoiceLoop._on_voice_input``。AI 用
TTS 从扬声器把回复念出来时,同一间屋子里的麦克风必然把这段声音重新采回去,VAD
判"有人在说话",Whisper 把 AI 自己的话转写成文字,再当作用户输入送进
``_on_voice_input``。后果有两条,而且都不是理论风险:

1. **AI 打断自己。** ``_on_voice_input`` 开头把"出词"当作用户开口的证据,
   ``is_speaking()`` 为真就调 ``interrupt_speech()``。而此刻正在说话的就是它
   自己 —— 于是每念一两句就被自己的回声掐断一次。
2. **AI 对自己说的话作答。** 转写出的文字继续往下走,进大脑,生成回复,再念出
   来,再被采回去 —— 自言自语的闭环。

``core/ambient_attention_loop.py`` 里对**它自己那条**感知通路写明并挡住了同一
个危险(见其"反自激励(anti-echo)"注释),但语音主闭环这条 —— 默认开启、真正
驱动对话的那条 —— 一直没有任何防护。本模块补上。

为什么不能简单地"朗读期间丢掉所有音频"
--------------------------------------
那会连真正的 barge-in 一起杀掉。"你一说话它就闭嘴"是本仓库明确提供的能力,不能
为了挡回声把它换掉。所以这里判的不是"此刻是否在朗读",而是**这段文字是不是我刚
刚说过的话**:

- 内容与刚说出口的话高度重合 → 自己的回声 → 丢弃,且**不触发 barge-in**。
- 内容是别的 → 用户真的开口了 → 照常打断、照常处理。

为什么按"文字"判而不按"是否在朗读"判
------------------------------------
``speech_output.is_speaking()`` 只反映 ``_active_speaker``,而 ``_active_speaker``
只在**流式**朗读路径上被设置。整段批处理路径(``GALAXY_TTS_STREAMING=0``)和原生
发声路径都不设它 —— 那两种模式下 ``is_speaking()`` 恒为 False,任何建立在它之上
的门(包括 ambient 那条)都是失效的。本模块挂在"文字真的变成声音"的那一刻,三条
发声路径一视同仁,因此比 ``is_speaking()`` 严格更可靠。

留存窗口
--------
麦克风侧有缓冲:``AudioCaptureService`` 攒够 ``asr_buffer_duration_s``(默认 3 秒)
才转写,加上 Whisper 本身的耗时,一段转写可能比它对应的声音晚好几秒才到。所以
"刚说过的话"必须在**说完之后**继续留存一段尾巴时间。又因为流式朗读是整段登记、
逐句播出的,一段长回复登记时刻很早、播完很晚,固定尾巴会让它在还没念完时就过期。
故留存时长按文本长度估算朗读耗时后再加尾巴。

不做的事(说明白,不含糊)
--------------------------
- 这不是回声消除(AEC)。没有做参考信号对齐,不处理"用户和 AI 同时说话"
  (double-talk)——那需要声学层的 AEC,不是文本层能解决的。
- barge-in 被打断时,尚未播出的后半段仍留在窗口里。清掉它会给**已经播出**的前半
  段重新打开回声口子,权衡之下选择留着;代价是打断后数秒内,用户若正好说出与那段
  未播出文字高度重合的话,会被误判一次。

默认开启(``GALAXY_VOICE_ECHO_GUARD=0`` 可关)。任何内部异常都判为"用户",绝不因
本模块失灵而让助手变聋。
"""

from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.VoiceEchoGuard")

# 判定结果
VERDICT_USER = "user"
VERDICT_SELF_ECHO = "self_echo"

# 最多留存多少条已说出口的话(防无界增长;远超任何真实对话所需)
_MAX_UTTERANCES = 32

# 朗读速度估算(中文 TTS 约每秒 5 字),用于推算一段文本要念多久
_CHARS_PER_SEC = 5.0

# 连续压制多少条后升一次 WARNING —— 万一相似度误判,要看得见,不能静默变聋
_SUPPRESS_STREAK_WARN = 5

_PUNCT_RE = re.compile(r"[\s,。、;:!?…—~·\"'“”‘’()()《》【】\[\]{}<>/\\|+*=&%$#@^_`,.;:!?~-]+")


# 统一走 core.config_flags —— 这里原先是 5 份逐字相同的本地 _flag 副本,
# 其中一个真 bug(空值把开关打开)因此要修 5 遍。详见该模块 docstring。
from core.config_flags import flag as _flag  # noqa: E402  (保留 _flag 名字以免动全部调用点)
from core.config_flags import num as _num  # noqa: E402

# _num 原为本地副本(两处,措辞略有差异)。它本来就正确处理了「空值视同未设置」,
# 而同文件的 _flag 漏了这一步 —— 那正是「空值把开关打开」那个 bug 的来源。一并收敛。


def enabled() -> bool:
    """反自激励门是否启用(默认开启)。"""
    return _flag("GALAXY_VOICE_ECHO_GUARD", "1")


def tail_seconds() -> float:
    """说完之后仍把这段话算作"刚说过"的尾巴时长(秒)。"""
    return max(0.0, _num("GALAXY_VOICE_ECHO_TAIL_S", 6.0))


def similarity_threshold() -> float:
    """判为自己回声所需的最低重合度(0~1)。"""
    return min(1.0, max(0.0, _num("GALAXY_VOICE_ECHO_SIM", 0.62)))


def min_chars() -> int:
    """短于此长度的转写一律判"用户"——"停"/"别说了" 这类打断口令必须永远通得过。"""
    return max(1, int(_num("GALAXY_VOICE_ECHO_MIN_CHARS", 4)))


def min_block() -> int:
    """至少要有这么长的一段【连续】重合,才可能是回声。

    只看总重合比例会误判:中文常用字少,一句短话("好的""可以吧")的每个字几乎
    必然散落在长回复的某处,总重合能凑到 1.0。要求一段足够长的连续命中,散落的
    单字重合就构不成证据了。
    """
    return max(2, int(_num("GALAXY_VOICE_ECHO_MIN_BLOCK", 4)))


def normalize(text: str) -> str:
    """归一化:去标点空白、英文转小写。ASR 的标点很不稳定,不能参与比对。"""
    return _PUNCT_RE.sub("", (text or "")).lower()


def _speech_duration_estimate(norm_len: int) -> float:
    """估算这段文本要念多久(秒)。"""
    return norm_len / _CHARS_PER_SEC if norm_len > 0 else 0.0


def overlap(asr_norm: str, utt_norm: str) -> Tuple[float, int]:
    """返回 ``(重合比例, 最长连续重合长度)``。

    重合比例是"转写文本中有多少比例能在已说出口的话里找到对应"——即 containment,
    而不是对称的相似度:已说出口的话通常长得多(整段回复),对称相似度会被长度差
    压到极小,根本判不出来。
    """
    if not asr_norm or not utt_norm:
        return 0.0, 0
    sm = difflib.SequenceMatcher(None, asr_norm, utt_norm, autojunk=False)
    blocks = sm.get_matching_blocks()
    matched = sum(b.size for b in blocks)
    longest = max((b.size for b in blocks), default=0)
    return min(1.0, matched / len(asr_norm)), longest


@dataclass
class _Utterance:
    """一段【确实已经变成声音】的文本。"""

    norm: str
    ts: float
    preview: str = field(default="", repr=False)

    def expires_at(self, tail: float) -> float:
        """过期时刻:登记时刻 + 估算朗读耗时 + 尾巴。"""
        return self.ts + _speech_duration_estimate(len(self.norm)) + tail


class EchoGuard:
    """记录"AI 刚说出口的话",据此判断一段转写是不是它自己的回声。

    线程安全:登记发生在朗读/播放协程里,判定发生在 ASR 线程池 worker 或事件循环
    线程里,两侧都可能并发,故全部状态由一把锁守护。
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._utterances: Deque[_Utterance] = deque(maxlen=_MAX_UTTERANCES)
        # 可观测计数
        self.noted: int = 0
        self.checked: int = 0
        self.suppressed: int = 0
        self.passed: int = 0
        self._streak: int = 0

    # ── 登记(由发声侧调用)─────────────────────────────────────────────────

    def note_utterance(self, text: str) -> None:
        """登记一段【已经/正在】变成声音的文本。降级安全,永不抛出。"""
        try:
            norm = normalize(text)
            if not norm:
                return
            with self._lock:
                self._utterances.append(_Utterance(norm=norm, ts=time.time(), preview=(text or "")[:40]))
                self.noted += 1
        except Exception as exc:  # noqa: BLE001 — 登记失败最多让门漏一句,不能影响朗读
            logger.debug("登记已说出口的文本失败(非致命): %s", exc)

    # ── 判定(由听侧调用)─────────────────────────────────────────────────

    def _prune_unlocked(self, now: float, tail: float) -> None:
        while self._utterances and self._utterances[0].expires_at(tail) < now:
            self._utterances.popleft()

    def recently_spoke(self) -> bool:
        """当前是否还有"刚说过的话"在留存窗口内。

        供不掌握文字、只能按时间挡的调用方(如 ambient 感知通路)使用;它比
        ``speech_output.is_speaking()`` 覆盖更全 —— 整段批处理和原生发声这两条
        路径不设 ``_active_speaker``,``is_speaking()`` 在那里恒为 False。
        """
        try:
            if not enabled():
                return False
            now = time.time()
            tail = tail_seconds()
            with self._lock:
                self._prune_unlocked(now, tail)
                return bool(self._utterances)
        except Exception as exc:  # noqa: BLE001
            logger.debug("recently_spoke 判定失败,按「没说过」处理: %s", exc)
            return False

    def classify(self, asr_text: str) -> Tuple[str, float, str]:
        """判定一段 ASR 文字的来源。返回 ``(verdict, score, reason)``。

        任何异常、任何不确定 → 判 ``VERDICT_USER``。宁可漏挡一次回声,也不能把
        用户真的说的话吃掉。
        """
        try:
            return self._classify_inner(asr_text)
        except Exception as exc:  # noqa: BLE001
            logger.warning("反自激励判定失败,按「用户输入」放行: %s", exc)
            return VERDICT_USER, 0.0, "guard_error"

    def _classify_inner(self, asr_text: str) -> Tuple[str, float, str]:
        if not enabled():
            return VERDICT_USER, 0.0, "disabled"

        norm = normalize(asr_text)
        if not norm:
            return VERDICT_USER, 0.0, "empty"
        if len(norm) < min_chars():
            # 太短判不准,而且"停/别念了"这类打断口令正是这个长度——必须放行。
            return VERDICT_USER, 0.0, "too_short"

        now = time.time()
        tail = tail_seconds()
        thr = similarity_threshold()
        need_block = min_block()

        with self._lock:
            self._prune_unlocked(now, tail)
            if not self._utterances:
                self.checked += 1
                self.passed += 1
                self._streak = 0
                return VERDICT_USER, 0.0, "nothing_recent"
            candidates = list(self._utterances)

        best_score = 0.0
        best_block = 0
        best_preview = ""
        for utt in candidates:
            score, longest = overlap(norm, utt.norm)
            if longest < need_block:
                continue  # 只有散落单字重合,不构成证据
            if score > best_score:
                best_score, best_block, best_preview = score, longest, utt.preview

        with self._lock:
            self.checked += 1
            if best_score >= thr:
                self.suppressed += 1
                self._streak += 1
                streak = self._streak
            else:
                self.passed += 1
                self._streak = 0
                streak = 0

        if best_score >= thr:
            if streak and streak % _SUPPRESS_STREAK_WARN == 0:
                # 相似度门若误判,症状是"助手不理人"。必须看得见,不能静默变聋。
                logger.warning(
                    "反自激励门已连续压制 %d 条语音输入(最近一条=%r,重合=%.2f)。"
                    "若用户其实在说话却没被响应,调高 GALAXY_VOICE_ECHO_SIM 或设 "
                    "GALAXY_VOICE_ECHO_GUARD=0 复核。",
                    streak,
                    asr_text[:40],
                    best_score,
                )
            return VERDICT_SELF_ECHO, best_score, f"matched:{best_preview}"
        return VERDICT_USER, best_score, f"below_threshold:{best_block}"

    # ── 观测 / 测试支持 ───────────────────────────────────────────────────

    def stats(self) -> Dict[str, object]:
        with self._lock:
            now = time.time()
            tail = tail_seconds()
            self._prune_unlocked(now, tail)
            return {
                "enabled": enabled(),
                "live_utterances": len(self._utterances),
                "noted": self.noted,
                "checked": self.checked,
                "suppressed": self.suppressed,
                "passed": self.passed,
                "suppress_streak": self._streak,
                "tail_s": tail,
                "sim_threshold": similarity_threshold(),
            }

    def clear(self) -> None:
        with self._lock:
            self._utterances.clear()
            self._streak = 0


# ── 进程级单例 ───────────────────────────────────────────────────────────────

_guard: Optional[EchoGuard] = None
_guard_lock = threading.Lock()


def get_echo_guard() -> EchoGuard:
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = EchoGuard()
    return _guard


def reset_echo_guard() -> None:
    """重置单例(测试用)。"""
    global _guard
    with _guard_lock:
        _guard = None


def note_utterance(text: str) -> None:
    """模块级快捷入口:登记一段已说出口的文本。"""
    get_echo_guard().note_utterance(text)


def classify_asr_text(text: str) -> Tuple[str, float, str]:
    """模块级快捷入口:判定一段 ASR 文字的来源。"""
    return get_echo_guard().classify(text)


def is_self_echo(text: str) -> bool:
    """便捷判定:这段转写是不是 AI 自己的回声。"""
    return classify_asr_text(text)[0] == VERDICT_SELF_ECHO


def recently_spoke() -> bool:
    """模块级快捷入口:留存窗口内是否还有刚说过的话。"""
    return get_echo_guard().recently_spoke()
