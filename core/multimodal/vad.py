"""Lightweight Voice Activity Detection (VAD) based on RMS energy.

No heavy ASR or neural networks — intentionally minimal.

Adaptive noise floor
--------------------
A *fixed* absolute RMS threshold silently fails on low-gain microphones: real
machines reported "收到音频但 VAD 从未判定为说话" (audio arrives, but VAD never
sees speech) because quiet-but-real speech stayed below the hard 0.01 gate. To
fix this the detector also tracks the ambient noise floor (a low percentile of
recent frame energies) and fires when energy rises clearly above it — so it
adapts to whatever input gain the user's mic happens to have, instead of
demanding they crank up Windows input volume first. The fixed threshold is kept
as a fast "definitely speech" path; the adaptive path only *adds* sensitivity.
Everything is env-tunable (see :meth:`VADConfig.from_env`) and on by default.
"""

from __future__ import annotations

import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np


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
    """Configuration for the VAD."""

    energy_threshold: float = 0.01  # RMS threshold for activity (fast path)
    frame_duration_ms: int = 20  # Duration of each VAD frame (ms)
    window_duration_ms: int = 300  # Rolling window for ratio metrics (ms)
    min_speech_frames: int = 3  # Consecutive active frames to confirm speech

    # 自适应噪声门限(修复"麦克风增益低→固定阈值 0.01 永不触发"):除固定阈值外,
    # 再按"能量显著高于近段噪声底"判活。对任意麦克风增益自适应,无需用户先调高
    # 系统输入音量。仅【增加】灵敏度,不改变对响亮语音/纯静音的既有判定。
    adaptive: bool = True
    adaptive_speech_mult: float = 3.0  # 能量 > 噪声底 × 该倍数 → 判活(约 +9.5 dB)
    adaptive_min_floor: float = 0.0020  # 绝对下限(≈ -54 dBFS),防数字静音/极低底噪误触发
    noise_window_frames: int = 100  # 噪声底估计的滚动窗口(帧)
    noise_percentile: float = 20.0  # 取窗口内该分位数作噪声底(避开语音峰值)

    @classmethod
    def from_env(cls) -> "VADConfig":
        """Build a config with ``GALAXY_VAD_*`` env overrides applied.

        Used for the live pipeline (which constructs the detector with no
        explicit config) so operators can tune sensitivity on the real machine
        without code changes. Tests that pass an explicit :class:`VADConfig`
        bypass this and keep fully deterministic values.
        """
        return cls(
            energy_threshold=_env_float("GALAXY_VAD_ENERGY_THRESHOLD", cls.energy_threshold),
            min_speech_frames=int(_env_float("GALAXY_VAD_MIN_SPEECH_FRAMES", cls.min_speech_frames)),
            adaptive=_env_bool("GALAXY_VAD_ADAPTIVE", cls.adaptive),
            adaptive_speech_mult=_env_float("GALAXY_VAD_SPEECH_MULT", cls.adaptive_speech_mult),
            adaptive_min_floor=_env_float("GALAXY_VAD_MIN_FLOOR", cls.adaptive_min_floor),
        )


@dataclass
class VADState:
    """Snapshot produced by the VAD after processing one frame."""

    is_speaking: bool = False
    energy: float = 0.0
    speaking_ratio: float = 0.0  # Fraction of recent frames with activity
    pause_density: float = 0.0  # Fraction of speech→silence transitions
    last_speech_ts: Optional[float] = None


class VoiceActivityDetector:
    """Energy-based VAD for lightweight speech activity sensing.

    Works on raw float32 PCM chunks at the configured sample_rate.
    """

    def __init__(
        self,
        config: Optional[VADConfig] = None,
        sample_rate: int = 16000,
    ) -> None:
        # config=None 是实时管线路径 → 应用 GALAXY_VAD_* 环境变量;显式传入的
        # config(多为测试)保持原样,确定性不变。
        self.config = config if config is not None else VADConfig.from_env()
        self.sample_rate = sample_rate

        self._window_frames = max(
            1,
            int(self.config.window_duration_ms / max(self.config.frame_duration_ms, 1)),
        )
        self._recent: Deque[bool] = deque(maxlen=self._window_frames)
        self._consecutive_speech = 0
        self._last_speech_ts: Optional[float] = None
        # 近段帧能量,用于估计噪声底(自适应门限)。
        self._energy_history: Deque[float] = deque(maxlen=max(1, self.config.noise_window_frames))

    def _is_active(self, energy: float) -> bool:
        """判活:固定阈值(快路径)∪ 显著高于噪声底(自适应,救低增益麦克风)。"""
        if energy > self.config.energy_threshold:
            return True
        if not self.config.adaptive or len(self._energy_history) < 5:
            return False
        noise_floor = float(np.percentile(self._energy_history, self.config.noise_percentile))
        adaptive_threshold = max(self.config.adaptive_min_floor, noise_floor * self.config.adaptive_speech_mult)
        return energy > adaptive_threshold

    def process_frame(self, audio_chunk: np.ndarray) -> VADState:
        """Process one chunk of PCM audio and return a VADState."""
        samples = audio_chunk.astype(np.float32).flatten()
        energy = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
        # 噪声底基于历史帧估计;先判活再把当前帧计入,避免当前语音帧抬高本次门限。
        is_active = self._is_active(energy)
        self._energy_history.append(energy)

        if is_active:
            self._consecutive_speech += 1
        else:
            self._consecutive_speech = 0

        is_speech = is_active and self._consecutive_speech >= self.config.min_speech_frames

        if is_speech:
            self._last_speech_ts = time.monotonic()

        self._recent.append(is_active)

        n = len(self._recent)
        speaking_ratio = sum(self._recent) / n if n > 0 else 0.0

        # Pause density: proportion of speech→silence transitions in the window
        recent_list = list(self._recent)
        transitions = sum(1 for i in range(1, len(recent_list)) if recent_list[i - 1] and not recent_list[i])
        pause_density = transitions / max(n - 1, 1)

        return VADState(
            is_speaking=is_speech,
            energy=energy,
            speaking_ratio=speaking_ratio,
            pause_density=pause_density,
            last_speech_ts=self._last_speech_ts,
        )

    def reset(self) -> None:
        """Reset rolling state."""
        self._recent.clear()
        self._energy_history.clear()
        self._consecutive_speech = 0
        self._last_speech_ts = None
