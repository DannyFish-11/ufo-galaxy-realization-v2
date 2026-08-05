"""语音活动检测(VAD):频谱判据与电平判据**取交集**,缺一不可。

两条判据的分工
--------------

1. **webrtcvad(频谱)** —— Google WebRTC 的 GMM 语音/非语音分类器。它回答
   "像不像人声",挡得住音调型、脉冲型的非语音。
   ``webrtcvad`` 对运行时是**可选**依赖(在 ``requirements.txt`` 的可选块里,
   语音唤醒用得上),但在 ``requirements-dev.txt`` 里是必装的 —— 否则这条路径
   在 CI 上永远跑不到,见下面"为什么必须两条一起"。

2. **能量 + 自适应噪声底(电平)** —— 回答"比当前环境底噪高出足够多吗"。
   它不依赖任何第三方包,也是 webrtcvad 缺失/采样率不受支持时的唯一兜底。

为什么必须**两条一起**,而不是"主判据 + 回退"
---------------------------------------------
两者过滤的是**正交**的失败模式,任何一条单独用都留着一个大洞:

* webrtcvad **挡不住宽带稳态噪声**。白噪声(风扇/空调)的宽带能量在 GMM 眼里
  跟摩擦音、清音很像,它照判"有声"。实测风扇档 RMS 0.05:webrtcvad 判活 100%。
* 电平判据**挡不住与人声等响的非语音**,但它挡得住上面那种 —— 因为噪声底会
  把环境学进去,门限随之升上去。

改这里之前是"webrtcvad 一旦可用就独断",于是下面那整套"棘轮破解 / 稳态噪声
重播种"(专为修真机症状「一启用就一直判定有人在说话」而写)**被完全旁路**——
它只维护噪声底,不参与判决。而 CI 一直看不见:``webrtcvad`` 那时不在任何 CI
安装的依赖里,主判据这条路径**从来没跑过**。

交集不牺牲灵敏度:自适应门限随环境走(安静房间底噪 0.0008 → 门限 0.0024,
轻声照样过),而且**噪声底还没学到时电平闸不参与** —— 那时能量法只剩固定阈值
0.01 兜底,拿它去闸会误杀轻声说话。见 :meth:`VoiceActivityDetector._has_credible_floor`。

``VADConfig.webrtc_requires_level=False`` 可退回旧的"独断"行为 —— 留着是为了
真机排障时一键区分"是不是这条判据判错了",不是推荐用法。

两个真机 bug 的来龙去脉(两者互为反向,必须一起看)
----------------------------------------------------

**Bug A — 自我投毒(旧)**:此前**每一帧**(包括正在说话的帧)都计入噪声底估计,
持续说话 ~10s 后噪声底收敛到语音电平本身,自适应门限变得不可企及 →
VAD 永久不再判活。修法是"只把确认静音的帧计入噪声底"。

**Bug B — 噪声底棘轮(新,由 A 的修法引入)**:排除活跃帧之后,噪声底就**只能降
不能升**了。安静环境下启动、随后风扇/空调起来 → 噪声帧因为被判"活跃"而永远
不被计入噪声底 → 门限永远停在开机时那个极低的值 → **每一帧噪声都判成说话**。
实测复现:安静段 RMS 0.0008 起步、噪声段 RMS 0.006,20 秒内 198/200 帧误判为
"有人在说话"(99%);而噪声从一开始就在的对照组是 0% —— 证明病根是棘轮而非阈值。

**破解 A 与 B 的对称困境**:光看能量无法区分"持续说话"和"稳态噪声",两个 bug
因此互为反向、按下葫芦浮起瓢。真正的判别信息是**平稳性**:人声是高度非平稳的
(音节起伏,能量变异系数大),而风扇/空调是平稳的(变异系数很小)。所以当活跃
状态持续超过 [VADConfig.stationary_probe_frames] 帧时,本模块检查这段活跃期的
能量变异系数 —— 低于 [VADConfig.stationary_cv] 即判定为稳态噪声,**强制把这些帧
计入噪声底**让门限升上去;高于该值则认定是真人在持续说话,继续排除。

一切参数均可用 ``GALAXY_VAD_*`` 环境变量在真机上调,无需改代码。
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional

import numpy as np

logger = logging.getLogger("Galaxy.VAD")

#: webrtcvad 只接受 8/16/32/48 kHz 的 16-bit 单声道 PCM。
_WEBRTC_SUPPORTED_RATES = (8000, 16000, 32000, 48000)

#: webrtcvad 只接受 10/20/30 ms 的帧;本模块按 20ms 切分。
_WEBRTC_SUBFRAME_MS = 20


def _env_float(name: str, default: float) -> float:
    try:
        raw = os.environ.get(name)
        return float(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class VADConfig:
    """VAD 配置。"""

    energy_threshold: float = 0.01  # 固定 RMS 阈值(能量快路径)
    # 真机复现:此值此前假设 20ms/帧,但实际管线(audio_ingest / audio_capture_service)
    # 按 ~100ms/块投喂 —— window_duration_ms 换算出的窗口于是比文档意图长 5 倍。
    frame_duration_ms: int = 100  # 与真实投喂节奏一致
    window_duration_ms: int = 300  # 比率类指标的滚动窗口
    min_speech_frames: int = 3  # 连续活跃到此数才确认为说话

    speech_hangover_frames: int = 3
    """确认说话后,活跃中断多少帧之内仍保持"正在说话"(语音挂起/平滑)。

    人说话时音节之间天然有低谷,单看逐帧能量会在波谷处掉到门限以下 —— 没有
    挂起就会让"正在说话"状态反复抖动,把一句连贯的话切成碎片(下游 ASR 分段
    与三态切换都会跟着抖)。3 帧 ≈ 300ms,足够跨过音节间隙,又不至于把真正的
    句末静默拖长。这是标准 VAD 做法。"""

    # ── webrtcvad(主判据)────────────────────────────────────────────
    use_webrtc: bool = True
    """是否优先使用 webrtcvad。缺包/采样率不支持时自动回退到能量法。"""

    webrtc_aggressiveness: int = 2
    """0–3,越大越严(越不容易把噪声当语音)。2 是通话场景常用值,
    与 ``core/voice_wake_module.py`` 保持一致。"""

    webrtc_voiced_ratio: float = 0.5
    """一个 100ms 块被切成 5 个 20ms 子帧;其中判为语音的比例达到该值才算活跃。
    要求过半可以滤掉"偶发一两个子帧误判"。"""

    webrtc_requires_level: bool = True
    """webrtcvad 判"有声"时,是否**还要**能量超过自适应门限才算活跃(取交集)。

    默认 ``True``。设 ``False`` 会退回"webrtcvad 独断"的旧行为 —— 那正是真机上
    「一启用就一直判定有人在说话」的来源:webrtcvad 是频谱分类器,宽带稳态噪声
    (风扇/空调)在它眼里跟摩擦音、清音很像,它照判有声,而下面那整套噪声底逻辑
    被完全旁路。实测风扇档白噪声 RMS 0.05:独断时判活 100%,取交集后 0%。

    留这个开关不是为了让人退回旧行为,是为了在真机上能一键区分"是不是这条判据
    判错了"——排障时把它关掉再跑一遍,症状是否复现直接给出答案。
    ``GALAXY_VAD_WEBRTC_REQUIRES_LEVEL=0`` 可在不改代码的情况下切换。"""

    # ── 能量 + 自适应噪声底(回退)──────────────────────────────────
    adaptive: bool = True
    adaptive_speech_mult: float = 3.0  # 能量 > 噪声底 × 该倍数 → 判活(约 +9.5 dB)
    adaptive_min_floor: float = 0.0020  # 绝对下限(≈ -54 dBFS),防数字静音误触发
    noise_window_frames: int = 100  # 噪声底估计的滚动窗口(帧)
    noise_percentile: float = 20.0  # 取该分位数作噪声底(避开语音峰值)
    adaptive_hangover_frames: int = 5  # 语音结束后再跳过几帧才恢复计入噪声底

    # ── 棘轮破解:稳态噪声探测 ────────────────────────────────────────
    stationary_probe_frames: int = 25
    """活跃状态连续持续到此帧数(默认 25 × 100ms = 2.5s)后,开始检查平稳性。
    真人很少不间断地"活跃"这么久而能量毫无起伏。"""

    stationary_cv: float = 0.18
    """能量变异系数(std/mean)阈值。低于它 → 判定为稳态噪声(风扇/空调),
    强制计入噪声底让门限升上去;高于它 → 认定是真人在持续说话,继续排除。"""

    @classmethod
    def from_env(cls) -> "VADConfig":
        """应用 ``GALAXY_VAD_*`` 环境变量覆盖(供实时管线用)。

        显式传入 config 的调用方(多为测试)绕过本方法,保持确定性。
        """
        return cls(
            energy_threshold=_env_float("GALAXY_VAD_ENERGY_THRESHOLD", cls.energy_threshold),
            min_speech_frames=int(_env_float("GALAXY_VAD_MIN_SPEECH_FRAMES", cls.min_speech_frames)),
            use_webrtc=_env_bool("GALAXY_VAD_USE_WEBRTC", cls.use_webrtc),
            webrtc_aggressiveness=int(_env_float("GALAXY_VAD_WEBRTC_AGGRESSIVENESS", cls.webrtc_aggressiveness)),
            webrtc_voiced_ratio=_env_float("GALAXY_VAD_WEBRTC_VOICED_RATIO", cls.webrtc_voiced_ratio),
            webrtc_requires_level=_env_bool("GALAXY_VAD_WEBRTC_REQUIRES_LEVEL", cls.webrtc_requires_level),
            adaptive=_env_bool("GALAXY_VAD_ADAPTIVE", cls.adaptive),
            adaptive_speech_mult=_env_float("GALAXY_VAD_SPEECH_MULT", cls.adaptive_speech_mult),
            adaptive_min_floor=_env_float("GALAXY_VAD_MIN_FLOOR", cls.adaptive_min_floor),
            adaptive_hangover_frames=int(_env_float("GALAXY_VAD_HANGOVER_FRAMES", cls.adaptive_hangover_frames)),
            stationary_probe_frames=int(_env_float("GALAXY_VAD_STATIONARY_FRAMES", cls.stationary_probe_frames)),
            stationary_cv=_env_float("GALAXY_VAD_STATIONARY_CV", cls.stationary_cv),
        )


@dataclass
class VADState:
    """处理完一帧后的快照。"""

    is_speaking: bool = False
    energy: float = 0.0
    speaking_ratio: float = 0.0  # 近段窗口内活跃帧占比
    pause_density: float = 0.0  # 语音→静音跃迁占比
    last_speech_ts: Optional[float] = None
    backend: str = "energy"
    """本帧实际使用的判据。

    ``"webrtc+energy"`` 频谱 ∩ 自适应门限(稳态,正常情况);
    ``"webrtc+floor"``  频谱 ∩ 绝对下限(暖机期,噪声底还没学到);
    ``"webrtc"``        频谱独断(仅当 ``webrtc_requires_level=False``,排障用);
    ``"energy"``        webrtcvad 不可用时的能量回退。
    """

    # ── 判决依据:默认就带出来,排障不需要先去翻开关 ──────────────────────
    #
    # 这几个数每帧本来就在算,此前算完即扔。于是真机上"它又一直判有人说话"时,
    # 手里只有一个 backend 字符串 —— 知道走了哪条判据,不知道它凭什么这么判,
    # 只能靠改环境变量重跑去复现。而这类症状恰恰高度依赖现场声学环境,
    # 换个时间就未必复现得出来。
    #
    # 带出来的成本是三个 float;换来的是"一帧的快照就能说清为什么"。
    noise_floor: Optional[float] = None
    """当前噪声底(``noise_percentile`` 分位数)。``None`` = 样本还不够,尚未可信。"""

    adaptive_threshold: Optional[float] = None
    """本帧实际生效的自适应门限(``max(min_floor, noise_floor × speech_mult)``)。
    与 :attr:`energy` 一比就知道电平判据为什么给出这个结论。``None`` 同上。"""

    webrtc_voiced_ratio: Optional[float] = None
    """webrtcvad 判为语音的子帧比例。``None`` = 本帧没用上 webrtcvad
    (缺包 / 采样率不支持 / 数据太短 / 调用失败)。

    它与 :attr:`adaptive_threshold` 一起,把"频谱说有声但电平不够"和"频谱就说
    没有"这两种完全不同的情形分开 —— 只看 is_speaking 是分不出来的。"""


class VoiceActivityDetector:
    """语音活动检测器。输入 float32 PCM 块(采样率见构造参数)。"""

    def __init__(
        self,
        config: Optional[VADConfig] = None,
        sample_rate: int = 16000,
    ) -> None:
        # config=None 是实时管线路径 → 应用 GALAXY_VAD_* 环境变量;
        # 显式传入的 config(多为测试)保持原样,确定性不变。
        self.config = config if config is not None else VADConfig.from_env()
        self.sample_rate = sample_rate

        self._window_frames = max(
            1,
            int(self.config.window_duration_ms / max(self.config.frame_duration_ms, 1)),
        )
        self._recent: Deque[bool] = deque(maxlen=self._window_frames)
        self._consecutive_speech = 0
        self._last_speech_ts: Optional[float] = None
        # 近段"确认静音"帧的能量,用于估计噪声底(见模块文档 Bug A/B)。
        self._energy_history: Deque[float] = deque(maxlen=max(1, self.config.noise_window_frames))
        self._hangover_remaining = 0
        # 当前这段连续活跃期的能量序列,用于稳态噪声判别(棘轮破解)。
        self._active_run_energies: List[float] = []
        # 是否已判定当前环境为稳态噪声(用于只重播种一次,而不是每帧都清空)。
        self._stationary_locked = False
        # 语音挂起剩余帧数(平滑音节波谷,避免"正在说话"抖动)。
        self._speech_hangover = 0

        self._webrtc = self._init_webrtc()

    # ------------------------------------------------------------------
    # webrtcvad
    # ------------------------------------------------------------------

    def _init_webrtc(self):
        """构造 webrtcvad 实例;不可用时返回 None 并说明原因(只说一次)。"""
        if not self.config.use_webrtc:
            return None
        if self.sample_rate not in _WEBRTC_SUPPORTED_RATES:
            logger.info(
                "VAD: 采样率 %d Hz 不在 webrtcvad 支持列表 %s,回退能量法",
                self.sample_rate,
                _WEBRTC_SUPPORTED_RATES,
            )
            return None
        try:
            import webrtcvad  # type: ignore[import-untyped]

            vad = webrtcvad.Vad(int(self.config.webrtc_aggressiveness))
            logger.info("VAD: 使用 webrtcvad(aggressiveness=%d)", self.config.webrtc_aggressiveness)
            return vad
        except Exception as exc:  # noqa: BLE001 — 缺包/构造失败都只是回退,不致命
            logger.info("VAD: webrtcvad 不可用(%s),回退能量法", exc)
            return None

    def _webrtc_voiced_ratio(self, samples: np.ndarray) -> Optional[float]:
        """把一块 PCM 切成 20ms 子帧交给 webrtcvad,返回判为语音的比例。

        返回 ``None`` 表示这块数据没法交给 webrtcvad(太短/调用失败),
        调用方应回退到能量法 —— 而不是当成"没有语音"。
        """
        if self._webrtc is None:
            return None
        subframe = int(self.sample_rate * _WEBRTC_SUBFRAME_MS / 1000)
        if subframe <= 0 or samples.size < subframe:
            return None
        # float32 [-1,1] → int16 PCM。先裁剪,避免溢出回绕把削顶噪声变成尖峰。
        pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
        n_full = pcm16.size // subframe
        voiced = 0
        try:
            for i in range(n_full):
                chunk = pcm16[i * subframe : (i + 1) * subframe].tobytes()
                if self._webrtc.is_speech(chunk, self.sample_rate):
                    voiced += 1
        except Exception as exc:  # noqa: BLE001 — 单次调用失败即回退,不影响后续帧
            logger.debug("VAD: webrtcvad.is_speech 失败,本帧回退能量法: %s", exc)
            return None
        return voiced / n_full if n_full else None

    # ------------------------------------------------------------------
    # 能量 + 自适应噪声底(回退判据)
    # ------------------------------------------------------------------

    def _has_credible_floor(self) -> bool:
        """噪声底是否已经学到、可以当判据用。

        样本不够时噪声底是空的,此时 :meth:`_energy_is_active` 只能退回固定阈值
        0.01 —— 而那个数按它自己的注释"只代表不算安静,不代表肯定是语音",拿它
        当电平闸会误杀轻声说话(实测:安静房间 RMS 0.01 的轻声全部被挡)。
        """
        return bool(self.config.adaptive) and len(self._energy_history) >= 5

    def _energy_is_active(self, energy: float) -> bool:
        """能量判活。

        **噪声底一旦可信,它就是权威判据** —— 固定阈值只在还没学到噪声底时兜底。

        为什么不能像从前那样把两者简单 OR(真机实测的第二处假阳性根源):
        固定阈值 0.01 被当成"肯定是语音"的快路径,可它其实只代表"不算安静"。
        在稍吵的房间里(实测底噪 RMS 0.05),噪声每一帧都 > 0.01,于是 OR 让它
        无条件判活 —— 辛苦学到的噪声底(自适应门限 0.15)被整个绕过,误判率
        99%。而自适应门限本身已经内含灵敏度(× ``adaptive_speech_mult``),
        安静环境下它比 0.01 更低(底噪 0.0008 → 门限 0.0024),低增益麦克风的
        轻声说话照样能触发 —— 这正是当初引入自适应路径要解决的问题,不受影响。
        """
        active, _, _ = self._energy_verdict(energy)
        return active

    def _energy_verdict(self, energy: float) -> "tuple[bool, Optional[float], Optional[float]]":
        """能量判活,并把**判据本身**一起交出来:``(是否判活, 噪声底, 生效门限)``。

        噪声底与门限每帧本来就在算,此前算完即扔。真机上"它又一直判有人说话"时,
        手里只剩一个布尔值 —— 说不出它凭什么这么判,只能靠改环境变量重跑复现,
        而这类症状高度依赖现场声学环境,换个时间未必复现得出来。所以默认带出来。

        噪声底不可信时后两项为 ``None``(而不是塞一个假的 0.0)—— 那时判据是固定
        阈值,报一个"噪声底"只会误导排障的人。
        """
        if not self._has_credible_floor():
            # 还没学到噪声底 → 只能靠固定阈值兜底。
            return energy > self.config.energy_threshold, None, None
        noise_floor = float(np.percentile(self._energy_history, self.config.noise_percentile))
        adaptive_threshold = max(self.config.adaptive_min_floor, noise_floor * self.config.adaptive_speech_mult)
        return energy > adaptive_threshold, noise_floor, adaptive_threshold

    def _looks_stationary(self) -> bool:
        """当前这段持续活跃期是否像**稳态噪声**(而不是有人在持续说话)。

        判据是能量变异系数 std/mean:人声因音节起伏而变异大,风扇/空调则近乎恒定。
        这是打破"自我投毒 ↔ 噪声底棘轮"对称困境的关键信息 —— 光看能量高低是分不
        出这两种情况的。
        """
        run = self._active_run_energies
        if len(run) < self.config.stationary_probe_frames:
            return False
        arr = np.asarray(run[-self.config.stationary_probe_frames :], dtype=np.float64)
        mean = float(arr.mean())
        if mean <= 0.0:
            return False
        cv = float(arr.std() / mean)
        return cv < self.config.stationary_cv

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def process_frame(self, audio_chunk: np.ndarray) -> VADState:
        """处理一块 PCM,返回 :class:`VADState`。"""
        samples = audio_chunk.astype(np.float32).flatten()
        energy = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0

        # ── 判活:两条判据**取交集**,不是二选一 ──
        #
        # 它们过滤的是**正交**的失败模式,任何一条单独用都留着一个大洞:
        #
        #   webrtcvad(频谱)  回答"像不像人声"    —— 挡得住音调型/脉冲型非语音,
        #                                          **挡不住宽带稳态噪声**:白噪声
        #                                          的宽带能量在 GMM 眼里跟摩擦音、
        #                                          清音很像,它照判"有声"。
        #   自适应噪声底(电平) 回答"比环境底高出足够多吗" —— 挡得住稳态环境噪声
        #                                          (不管频谱像什么),挡不住与人声
        #                                          等响的非语音。
        #
        # 改这里之前是 webrtcvad **独断**:它一旦可用,下面那整套"棘轮破解 / 稳态
        # 噪声重播种"(专为修「一启用就一直判定有人在说话」而写)就被完全旁路,
        # 因为它只维护噪声底、不参与 is_active。实测风扇档白噪声(RMS 0.05):
        # webrtcvad 路径判活 100%,能量回退路径判活 0%。这正是真机上那个症状。
        #
        # 而 CI 一直看不见:webrtcvad 在 requirements.txt 里是注释掉的,CI 从不
        # 安装它,于是**主判据这条路从来没在 CI 上跑过**。
        #
        # 取交集不会牺牲灵敏度:自适应门限本身随环境走(安静房间底噪 0.0008 →
        # 门限 0.0024,轻声说话照样过),它要求的只是"比当前环境高约 9.5 dB"——
        # 那本来就是能量回退路径一直在用的判据,不是新增的严苛条件。
        # 电平闸**只在噪声底可信时**参与。还没学到噪声底时,能量法只剩固定阈值
        # 0.01 兜底,而按它自己的注释那个数"只代表不算安静,不代表肯定是语音"——
        # 拿它闸 webrtcvad 会误杀轻声说话(实测:安静房间 RMS 0.01 的轻声全被挡)。
        # 那种时候 webrtcvad 就是手里最好的信息,让它独断是对的。
        #
        # 这不会把 bug 放回来:稳态噪声从开机就在时,前 25 帧确实按 webrtcvad 判活,
        # 但正是这段活跃期喂给了"稳态噪声探测",第 25 帧一到就重播种噪声底、
        # 门限一步升到位,之后电平闸接管 —— 实测第 26 帧起即转静。
        ratio = self._webrtc_voiced_ratio(samples) if samples.size else None
        energy_active, noise_floor, adaptive_threshold = self._energy_verdict(energy)
        if ratio is not None:
            spectral_active = ratio >= self.config.webrtc_voiced_ratio
            if not self.config.webrtc_requires_level:
                is_active = spectral_active
                backend = "webrtc"
            elif self._has_credible_floor():
                is_active = spectral_active and energy_active
                backend = "webrtc+energy"
            else:
                # 暖机期(噪声底还没学到):电平闸退到**绝对下限**,而不是完全撤掉。
                #
                # 撤掉的代价是实测出来的:启动最初几帧 webrtcvad 会把 RMS 0.002 的
                # 高斯噪声判成有声(ratio=1.00),而此时没有任何东西能否决它 ——
                # 于是开机头 ~200ms 冒出一段假的"正在说话"。那就是「一启用就一直
                # 判定有人在说话」缩短后的残留,不是另一个 bug。
                #
                # 为什么用 ``adaptive_min_floor`` 而不是 ``energy_threshold``:
                # 稳态门限是 ``max(adaptive_min_floor, 噪声底 × 倍数)``,恒 ≥
                # ``adaptive_min_floor``。所以拿它当暖机闸,**不可能否决任何稳态期
                # 会放行的帧** —— 学到噪声底前后不会出现"先能说话、后说不了"的
                # 反转。固定阈值 0.01 没有这个性质(安静房间门限能低到 0.0024),
                # 拿它闸就会误杀轻声说话,那正是上面不用它的原因。
                is_active = spectral_active and energy > self.config.adaptive_min_floor
                backend = "webrtc+floor"
        else:
            is_active = energy_active
            backend = "energy"

        # ── 噪声底维护 ──
        if is_active:
            self._active_run_energies.append(energy)
            self._hangover_remaining = self.config.adaptive_hangover_frames
            # 棘轮破解:持续活跃且能量平稳 → 这不是人在说话,是稳态噪声。
            # 强制计入噪声底,让自适应门限升上去,否则会永远误判(实测 99%)。
            if self._looks_stationary():
                if not self._stationary_locked:
                    # 首次判定"环境已变成稳态噪声":此刻噪声底里装的还是安静期
                    # 那批旧样本,已经不代表现在的环境了。若只是逐帧追加,要等
                    # 整个 100 帧窗口被冲刷完门限才升得上去 —— 实测这段过渡期
                    # 仍有约一半的帧在误判。直接用这段实测到的稳态能量重播种,
                    # 让门限一步到位。
                    self._energy_history.clear()
                    for e in self._active_run_energies[-self.config.stationary_probe_frames :]:
                        self._energy_history.append(e)
                    self._stationary_locked = True
                    logger.debug("VAD: 判定为稳态噪声,噪声底重播种至 ~%.5f", energy)
                self._energy_history.append(energy)
        else:
            self._active_run_energies.clear()
            self._stationary_locked = False
            if self._hangover_remaining > 0:
                self._hangover_remaining -= 1
            else:
                # 只有"确认静音"的帧才进噪声底 —— 这是 Bug A(自我投毒)的修法:
                # 否则持续说话会把窗口填满语音能量,门限自我抬高到不可企及。
                self._energy_history.append(energy)

        if is_active:
            self._consecutive_speech += 1
        else:
            self._consecutive_speech = 0

        # 语音挂起:确认说话后,短暂的音节波谷不应让状态抖动(见 speech_hangover_frames)。
        if is_active and self._consecutive_speech >= self.config.min_speech_frames:
            is_speech = True
            self._speech_hangover = self.config.speech_hangover_frames
        elif self._speech_hangover > 0:
            self._speech_hangover -= 1
            is_speech = True
        else:
            is_speech = False

        if is_speech:
            self._last_speech_ts = time.monotonic()

        self._recent.append(is_active)

        n = len(self._recent)
        speaking_ratio = sum(self._recent) / n if n > 0 else 0.0

        recent_list = list(self._recent)
        transitions = sum(1 for i in range(1, len(recent_list)) if recent_list[i - 1] and not recent_list[i])
        pause_density = transitions / max(n - 1, 1)

        return VADState(
            is_speaking=is_speech,
            energy=energy,
            speaking_ratio=speaking_ratio,
            pause_density=pause_density,
            last_speech_ts=self._last_speech_ts,
            backend=backend,
            noise_floor=noise_floor,
            adaptive_threshold=adaptive_threshold,
            webrtc_voiced_ratio=ratio,
        )

    def reset(self) -> None:
        """重置滚动状态。"""
        self._recent.clear()
        self._energy_history.clear()
        self._consecutive_speech = 0
        self._last_speech_ts = None
        self._hangover_remaining = 0
        self._active_run_energies.clear()
        self._stationary_locked = False
        self._speech_hangover = 0
