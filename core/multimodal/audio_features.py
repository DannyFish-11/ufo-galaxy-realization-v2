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

    energy: float = 0.0             # RMS energy of the latest chunk
    speaking_ratio: float = 0.0     # Fraction of recent frames with speech
    pause_density: float = 0.0      # Speech-to-silence transition rate
    noise_level: float = 0.0        # Spectral-flatness proxy (0=tonal, 1=noise)
    audio_freshness_ms: float = float("inf")  # ms since last chunk was processed
    is_speaking: bool = False
    timestamp: float = field(default_factory=time.monotonic)
    samples: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))  # Raw PCM samples
    sample_rate: int = 16000        # Sample rate of the raw samples


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
    power = samples ** 2 + 1e-10
    geometric_mean = float(np.exp(np.mean(np.log(power))))
    arithmetic_mean = float(np.mean(power))
    noise_level = float(
        np.clip(geometric_mean / (arithmetic_mean + 1e-10), 0.0, 1.0)
    )

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
