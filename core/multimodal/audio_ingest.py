"""Microphone capture pipeline with VAD and lightweight audio state features.

Runs in local/server contexts where *sounddevice* is available.
Degrades gracefully when the device is missing or permission is denied —
the pipeline returns immediately without raising, leaving the rest of the
system unaffected.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

import numpy as np

from .vad import VoiceActivityDetector, VADConfig
from .audio_features import AudioState, extract_audio_features
from .signal_quality import SignalQuality, QualityFlag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional sounddevice import
# ---------------------------------------------------------------------------
_SOUNDDEVICE_AVAILABLE = False
try:
    import sounddevice as _sd  # noqa: F401

    _SOUNDDEVICE_AVAILABLE = True
except Exception:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class AudioIngestConfig:
    """Configuration for the microphone ingest pipeline."""

    sample_rate: int = 16000          # Hz
    channels: int = 1
    chunk_duration_ms: int = 100      # Target chunk size (~10 Hz update rate)
    device: Optional[int] = None      # None → use system default microphone
    vad_config: Optional[VADConfig] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class AudioIngestPipeline:
    """Microphone capture pipeline with VAD and lightweight audio state.

    Usage::

        pipeline = AudioIngestPipeline()
        pipeline.add_callback(my_handler)
        await pipeline.run()          # blocks until stop() is called

    Or as an async generator::

        async for state, quality in pipeline.stream():
            ...
    """

    def __init__(self, config: Optional[AudioIngestConfig] = None) -> None:
        self.config = config or AudioIngestConfig()
        self._vad = VoiceActivityDetector(
            config=self.config.vad_config,
            sample_rate=self.config.sample_rate,
        )
        self._running = False
        self._quality: SignalQuality = SignalQuality.missing("Not started")
        self._latest_state: Optional[AudioState] = None
        self._callbacks: List[Callable[[AudioState, SignalQuality], None]] = []
        self._last_update_ts: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if sounddevice is importable on this host."""
        return _SOUNDDEVICE_AVAILABLE

    def add_callback(
        self, cb: Callable[[AudioState, SignalQuality], None]
    ) -> None:
        """Register a callback invoked with each new AudioState."""
        self._callbacks.append(cb)

    def get_latest(self) -> tuple:
        """Return (AudioState | None, SignalQuality) for the most recent frame."""
        return self._latest_state, self._quality

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Start the microphone ingest loop.

        Returns immediately (without raising) when:
        - sounddevice is not installed
        - microphone permission is denied
        - the device is not found
        """
        if not _SOUNDDEVICE_AVAILABLE:
            self._quality = SignalQuality.device_unavailable()
            logger.warning("sounddevice is not available; audio ingest disabled")
            return

        import sounddevice as sd  # deferred to avoid import-time failure

        chunk_size = max(
            1,
            int(self.config.sample_rate * self.config.chunk_duration_ms / 1000),
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # capture() must be called from within a running asyncio event loop.
            # Without one, the sounddevice callback cannot enqueue audio chunks
            # safely, so we exit early rather than silently misbehaving.
            logger.warning(
                "AudioIngestPipeline.capture() called with no running event loop — "
                "audio capture cannot start.  Call capture() from an async context."
            )
            self._quality = SignalQuality.device_unavailable()
            return
        queue: asyncio.Queue = asyncio.Queue(maxsize=30)

        def _sd_callback(indata: np.ndarray, frames: int, time_info, status) -> None:
            if status:
                logger.debug("sounddevice status: %s", status)
            chunk = indata[:, 0].copy() if indata.ndim > 1 else indata.flatten().copy()
            try:
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except asyncio.QueueFull:
                pass  # drop frame rather than block

        self._running = True
        self._quality = SignalQuality.ok()

        try:
            with sd.InputStream(
                samplerate=self.config.sample_rate,
                channels=self.config.channels,
                dtype="float32",
                blocksize=chunk_size,
                device=self.config.device,
                callback=_sd_callback,
            ):
                logger.info(
                    "Audio ingest started (sr=%d, chunk_ms=%d)",
                    self.config.sample_rate,
                    self.config.chunk_duration_ms,
                )
                while self._running:
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=1.0)
                        await self._process_chunk(chunk)
                    except asyncio.TimeoutError:
                        pass

        except PermissionError:
            self._quality = SignalQuality.permission_denied()
            logger.warning("Microphone permission denied")
        except Exception as exc:
            self._quality = SignalQuality.degraded(str(exc))
            logger.warning("Audio ingest error: %s", exc)
        finally:
            self._running = False
            logger.info("Audio ingest stopped")

    async def _process_chunk(self, chunk: np.ndarray) -> None:
        """Update VAD + features and invoke registered callbacks."""
        now = time.monotonic()
        vad_state = self._vad.process_frame(chunk)
        state = extract_audio_features(chunk, vad_state, self._last_update_ts)
        self._last_update_ts = now
        self._latest_state = state
        self._quality = SignalQuality.ok(
            freshness_ms=(time.monotonic() - now) * 1000.0
        )
        for cb in list(self._callbacks):
            try:
                cb(state, self._quality)
            except Exception as exc:
                logger.debug("Audio callback error: %s", exc)

    # ------------------------------------------------------------------
    # Async generator interface
    # ------------------------------------------------------------------

    async def stream(self) -> AsyncIterator:
        """Yield (AudioState, SignalQuality) tuples as they arrive."""
        states: asyncio.Queue = asyncio.Queue(maxsize=50)

        def _enqueue(state: AudioState, quality: SignalQuality) -> None:
            try:
                states.put_nowait((state, quality))
            except asyncio.QueueFull:
                pass

        self.add_callback(_enqueue)
        task = asyncio.create_task(self.run())
        try:
            while not task.done() or not states.empty():
                try:
                    yield await asyncio.wait_for(states.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    if task.done():
                        break
        finally:
            self.stop()
            await task
