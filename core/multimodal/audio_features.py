"""Audio feature extraction producing lightweight AudioState snapshots.

Features: energy, speaking_ratio, pause_density, noise_level, audio_freshness_ms.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .vad import VADState


@dataclass
class AudioState:
    """Lightweight audio state features emitted every ~100–300 ms."""

    energy: float = 0.0  # RMS energy of the latest chunk
    speaking_ratio: float = 0.0  # Fraction of recent frames with speech
    pause_density: float = 0.0  # Speech-to-silence transition rate
    noise_level: float = 0.0  # Spectral-flatness proxy (0=tonal, 1=noise)
    audio_freshness_ms: float = float("inf")  # ms since last chunk was processed
    is_speaking: bool = False
    #: 上面那些特征是不是**真的测过**。默认 True —— 只有 extract_audio_features()
    #: 这条路会产出已测量的状态。桌面壳只上报"麦克风在场"、本机没有跑特征管线时，
    #: 桥接会写一个 features_measured=False 的占位态：能量 0 / 没在说话都是
    #: 「没测」而不是「测出来是 0」。下游（人体场打分）必须据此区分，否则会把
    #: 「不知道」当成「安静」，凭空造出"用户不在/疲劳"的结论。
    features_measured: bool = True
    #: 这一块麦克风信号有没有真的过了回声消除。AEC 在没有参考信号(没开回环采集)时
    #: 会静默旁通，信号原样通过 —— 下游看到的"用户在说话"里可能混着 AI 自己的声音。
    #: 把它带进常驻感知，是为了让"世界"里能分清「听到的是干净的」还是「没消过」。
    echo_cancelled: bool = False
    #: 两级(线性对消 + 残余抑制)串起来的总回声抑制量，dB。0 表示没消或没测到。
    echo_suppression_db: float = 0.0
    timestamp: float = field(default_factory=time.monotonic)
    samples: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))  # Raw PCM samples
    sample_rate: int = 16000  # Sample rate of the raw samples


def extract_audio_features(
    audio_chunk: np.ndarray,
    vad_state: VADState,
    last_update_ts: Optional[float] = None,
    sample_rate: int = 16000,
) -> AudioState:
    """Derive an AudioState from a PCM chunk and a pre-computed VADState.

    Args:
        audio_chunk:    Raw float32 PCM samples.
        vad_state:      Result from VoiceActivityDetector.process_frame().
        last_update_ts: monotonic timestamp of the previous update (for freshness).
        sample_rate:    Audio sample rate in Hz.

    Returns:
        AudioState with all fields populated.
    """
    samples = audio_chunk.astype(np.float32).flatten()

    # Spectral flatness as a proxy for noise vs. tonal content.
    # exp(mean(log(p))) / mean(p) == 1 for white noise, < 1 for tonal signals.
    power = samples**2 + 1e-10
    geometric_mean = float(np.exp(np.mean(np.log(power))))
    arithmetic_mean = float(np.mean(power))
    noise_level = float(np.clip(geometric_mean / (arithmetic_mean + 1e-10), 0.0, 1.0))

    now = time.monotonic()
    freshness_ms = (now - last_update_ts) * 1000.0 if last_update_ts is not None else 0.0

    return AudioState(
        energy=vad_state.energy,
        speaking_ratio=vad_state.speaking_ratio,
        pause_density=vad_state.pause_density,
        noise_level=noise_level,
        audio_freshness_ms=max(freshness_ms, 0.0),
        is_speaking=vad_state.is_speaking,
        timestamp=now,
        samples=samples,
        sample_rate=sample_rate,
    )
