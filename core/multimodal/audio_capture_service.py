"""High-level audio capture service for the Galaxy multimodal pipeline.

Wraps :class:`AudioIngestPipeline` and :class:`MultimodalIngressBus` to
provide a single entry point for starting/stopping microphone capture with
observability, runtime event emission, and a callback interface suitable
for ASR or agent consumption.

Usage::

    service = AudioCaptureService()
    service.add_asr_callback(my_asr_handler)   # (AudioState, SignalQuality) -> None
    await service.start()
    # ... later ...
    await service.stop()

Graceful degradation
--------------------
If ``sounddevice`` is not installed, :meth:`start` returns immediately
without raising.  Downstream consumers receive ``DEVICE_UNAVAILABLE``
quality signals.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from .audio_ingest import AudioIngestPipeline, AudioIngestConfig
from .audio_features import AudioState
from .signal_quality import SignalQuality
from .multimodal_events import (
    AudioStreamStartedEvent,
    AudioStreamStoppedEvent,
    AudioStreamErrorEvent,
    AudioQualityDegradedEvent,
    MultimodalEvent,
)

logger = logging.getLogger(__name__)

# Latency threshold above which a quality-degraded event is emitted (ms)
_LATENCY_WARNING_MS: float = 200.0


@dataclass
class AudioCaptureConfig:
    """Configuration for :class:`AudioCaptureService`.

    Attributes
    ----------
    sample_rate         Microphone sample rate in Hz.
    chunk_duration_ms   Target chunk duration in milliseconds.
    device              sounddevice device index (None = system default).
    latency_warning_ms  Threshold above which audio latency is flagged.
    trace_id            Optional trace correlation ID passed to events.
    runtime_session_id  Optional runtime session ID passed to events.
    """

    sample_rate: int = 16000
    chunk_duration_ms: int = 100
    device: Optional[int] = None
    latency_warning_ms: float = _LATENCY_WARNING_MS
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None


class AudioCaptureService:
    """High-level microphone capture service with runtime event emission.

    The service owns an :class:`AudioIngestPipeline` and acts as its primary
    consumer.  It forwards audio frames to registered ASR/agent callbacks and
    emits structured :class:`MultimodalEvent` objects for observability.

    Thread safety
    -------------
    :meth:`start` and :meth:`stop` must be called from within an asyncio
    event loop.  :meth:`add_asr_callback` and :meth:`add_event_listener` are
    safe to call before :meth:`start`.
    """

    def __init__(self, config: Optional[AudioCaptureConfig] = None) -> None:
        self.config = config or AudioCaptureConfig()
        self._pipeline = AudioIngestPipeline(
            config=AudioIngestConfig(
                sample_rate=self.config.sample_rate,
                chunk_duration_ms=self.config.chunk_duration_ms,
                device=self.config.device,
            )
        )
        self._asr_callbacks: List[Callable[[AudioState, SignalQuality], None]] = []
        self._event_listeners: List[Callable[[MultimodalEvent], None]] = []
        self._task: Optional[asyncio.Task] = None

        # Metrics
        self._chunks_processed: int = 0
        self._start_ts: Optional[float] = None

        # Wire internal callback to pipeline
        self._pipeline.add_callback(self._on_audio_chunk)

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if sounddevice is importable on this host."""
        return self._pipeline.is_available

    def add_asr_callback(
        self, cb: Callable[[AudioState, SignalQuality], None]
    ) -> None:
        """Register a callback invoked with each new :class:`AudioState`.

        Suitable for wiring directly into an ASR or agent pipeline.
        """
        self._asr_callbacks.append(cb)

    def add_event_listener(
        self, listener: Callable[[MultimodalEvent], None]
    ) -> None:
        """Register a listener for :class:`MultimodalEvent` objects."""
        self._event_listeners.append(listener)

    def get_latest(self) -> tuple:
        """Return ``(AudioState | None, SignalQuality)`` for the last chunk."""
        return self._pipeline.get_latest()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start microphone capture in a background task.

        Returns immediately.  If already running, this is a no-op.
        """
        if self._task is not None and not self._task.done():
            logger.debug("AudioCaptureService already running")
            return

        self._start_ts = time.monotonic()
        self._chunks_processed = 0

        if not self.is_available:
            logger.warning("AudioCaptureService: sounddevice unavailable; skipping start")
            return

        self._emit_event(
            AudioStreamStartedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                sample_rate=self.config.sample_rate,
                chunk_duration_ms=self.config.chunk_duration_ms,
                device=self.config.device,
            )
        )
        self._task = asyncio.create_task(self._run(), name="audio_capture_service")
        logger.info(
            "AudioCaptureService started (sr=%d, chunk_ms=%d)",
            self.config.sample_rate,
            self.config.chunk_duration_ms,
        )

    async def stop(self) -> None:
        """Stop microphone capture and await the background task."""
        self._pipeline.stop()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

        duration_s = (
            time.monotonic() - self._start_ts if self._start_ts is not None else 0.0
        )
        self._emit_event(
            AudioStreamStoppedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                reason="stopped",
                total_chunks_processed=self._chunks_processed,
                total_duration_s=duration_s,
            )
        )
        logger.info(
            "AudioCaptureService stopped (chunks=%d, duration=%.1fs)",
            self._chunks_processed,
            duration_s,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Wrap pipeline.run() and emit error events on failure."""
        try:
            await self._pipeline.run()
        except Exception as exc:
            logger.warning("AudioCaptureService pipeline error: %s", exc)
            self._emit_event(
                AudioStreamErrorEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    error=str(exc),
                    recoverable=False,
                )
            )

    def _on_audio_chunk(
        self, state: AudioState, quality: SignalQuality
    ) -> None:
        """Internal callback: update metrics, check latency, forward to ASR."""
        self._chunks_processed += 1

        # Latency / quality check
        latency_ms = quality.freshness_ms or 0.0
        if latency_ms > self.config.latency_warning_ms:
            self._emit_event(
                AudioQualityDegradedEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    latency_ms=latency_ms,
                    quality_flag=quality.flag.value,
                )
            )

        # Forward to registered ASR / agent consumers
        for cb in list(self._asr_callbacks):
            try:
                cb(state, quality)
            except Exception as exc:
                logger.debug("ASR callback error: %s", exc)

    def _emit_event(self, event: MultimodalEvent) -> None:
        """Dispatch a :class:`MultimodalEvent` to all registered listeners."""
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception as exc:
                logger.debug("Event listener error: %s", exc)
