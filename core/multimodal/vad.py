"""Lightweight Voice Activity Detection (VAD) based on RMS energy.

No heavy ASR or neural networks — intentionally minimal.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

import numpy as np


@dataclass
class VADConfig:
    """Configuration for the VAD."""

    energy_threshold: float = 0.01       # RMS threshold for activity
    frame_duration_ms: int = 20           # Duration of each VAD frame (ms)
    window_duration_ms: int = 300         # Rolling window for ratio metrics (ms)
    min_speech_frames: int = 3            # Consecutive active frames to confirm speech


@dataclass
class VADState:
    """Snapshot produced by the VAD after processing one frame."""

    is_speaking: bool = False
    energy: float = 0.0
    speaking_ratio: float = 0.0     # Fraction of recent frames with activity
    pause_density: float = 0.0      # Fraction of speech→silence transitions
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
        self.config = config or VADConfig()
        self.sample_rate = sample_rate

        self._window_frames = max(
            1,
            int(self.config.window_duration_ms / max(self.config.frame_duration_ms, 1)),
        )
        self._recent: Deque[bool] = deque(maxlen=self._window_frames)
        self._consecutive_speech = 0
        self._last_speech_ts: Optional[float] = None

    def process_frame(self, audio_chunk: np.ndarray) -> VADState:
        """Process one chunk of PCM audio and return a VADState."""
        samples = audio_chunk.astype(np.float32).flatten()
        energy = float(np.sqrt(np.mean(samples ** 2))) if samples.size else 0.0
        is_active = energy > self.config.energy_threshold

        if is_active:
            self._consecutive_speech += 1
        else:
            self._consecutive_speech = 0

        is_speech = (
            is_active and self._consecutive_speech >= self.config.min_speech_frames
        )

        if is_speech:
            self._last_speech_ts = time.monotonic()

        self._recent.append(is_active)

        n = len(self._recent)
        speaking_ratio = sum(self._recent) / n if n > 0 else 0.0

        # Pause density: proportion of speech→silence transitions in the window
        recent_list = list(self._recent)
        transitions = sum(
            1
            for i in range(1, len(recent_list))
            if recent_list[i - 1] and not recent_list[i]
        )
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
        self._consecutive_speech = 0
        self._last_speech_ts = None
