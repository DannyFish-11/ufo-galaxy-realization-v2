"""Unified multimodal ingress bus.

Merges audio, video, and system signals into a single PerceptionFrame
stream for downstream consumption.  Missing modalities are tolerated:
quality flags and default values are used when a source is absent or stale.

Usage::

    bus = MultimodalIngressBus(tick_ms=200)

    # Wire up sources
    audio_pipeline.add_callback(bus.update_audio)
    video_pipeline.add_callback(bus.update_video)

    # Consume frames
    q = bus.subscribe()
    asyncio.create_task(bus.run())
    frame = await q.get()   # PerceptionFrame
"""
from __future__ import annotations

import asyncio
import itertools
import logging
import time
from typing import Callable, List, Optional

from .audio_features import AudioState
from .video_features import VideoState
from .perception_frame import PerceptionFrame, SystemSignals
from .signal_quality import SignalQuality, QualityFlag

logger = logging.getLogger(__name__)


class MultimodalIngressBus:
    """Merges audio / video / system signals into a PerceptionFrame stream.

    The bus runs a periodic tick loop that composes a PerceptionFrame from
    the latest signal snapshots and dispatches it to all registered
    subscribers and callbacks.

    Thread safety: signal updates (update_audio / update_video /
    update_system) are safe to call from any thread or asyncio task.
    Subscription and emission must happen within the same event loop.
    """

    def __init__(self, tick_ms: int = 200) -> None:
        self._tick_ms = tick_ms
        self._frame_counter = itertools.count()

        # Latest snapshots ------------------------------------------------
        self._audio: Optional[AudioState] = None
        self._audio_quality: SignalQuality = SignalQuality.missing("No audio source")
        self._audio_ts: Optional[float] = None

        self._video: Optional[VideoState] = None
        self._video_quality: SignalQuality = SignalQuality.missing("No video source")
        self._video_ts: Optional[float] = None

        self._system: Optional[SystemSignals] = None
        self._system_quality: SignalQuality = SignalQuality.missing("No system source")
        self._system_ts: Optional[float] = None

        # Staleness threshold
        self._stale_threshold_ms: float = 2000.0

        # Consumers -------------------------------------------------------
        self._running = False
        self._subscribers: List[asyncio.Queue] = []
        self._callbacks: List[Callable[[PerceptionFrame], None]] = []

    # ------------------------------------------------------------------
    # Signal injection
    # ------------------------------------------------------------------

    def update_audio(
        self, state: AudioState, quality: SignalQuality
    ) -> None:
        """Ingest a new AudioState snapshot."""
        self._audio = state
        self._audio_quality = quality
        self._audio_ts = time.monotonic()

    def update_video(
        self, state: VideoState, quality: SignalQuality
    ) -> None:
        """Ingest a new VideoState snapshot."""
        self._video = state
        self._video_quality = quality
        self._video_ts = time.monotonic()

    def update_system(
        self,
        signals: SystemSignals,
        quality: Optional[SignalQuality] = None,
    ) -> None:
        """Ingest new system signals."""
        self._system = signals
        self._system_quality = quality if quality is not None else SignalQuality.ok()
        self._system_ts = time.monotonic()

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    def add_callback(self, cb: Callable[[PerceptionFrame], None]) -> None:
        """Register a synchronous callback invoked for each frame."""
        self._callbacks.append(cb)

    def subscribe(self) -> asyncio.Queue:
        """Return an asyncio.Queue that receives each PerceptionFrame."""
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Remove a previously-subscribed queue."""
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Frame construction
    # ------------------------------------------------------------------

    def _apply_staleness(
        self, ts: Optional[float], quality: SignalQuality
    ) -> SignalQuality:
        """Downgrade quality to STALE when the signal has not been updated."""
        if ts is None:
            return quality
        age_ms = (time.monotonic() - ts) * 1000.0
        if age_ms > self._stale_threshold_ms and quality.flag == QualityFlag.OK:
            return SignalQuality.stale(
                freshness_ms=age_ms,
                confidence=quality.confidence * 0.5,
            )
        return quality

    def build_frame(self) -> PerceptionFrame:
        """Compose a PerceptionFrame from the current snapshots."""
        aq = self._apply_staleness(self._audio_ts, self._audio_quality)
        vq = self._apply_staleness(self._video_ts, self._video_quality)
        sq = self._apply_staleness(self._system_ts, self._system_quality)

        return PerceptionFrame(
            frame_id=next(self._frame_counter),
            audio=self._audio if aq.is_usable else None,
            audio_quality=aq,
            video=self._video if vq.is_usable else None,
            video_quality=vq,
            system=self._system if sq.is_usable else None,
            system_quality=sq,
        )

    # ------------------------------------------------------------------
    # Emission
    # ------------------------------------------------------------------

    async def _emit(self, frame: PerceptionFrame) -> None:
        """Dispatch a frame to all callbacks and subscriber queues."""
        for cb in list(self._callbacks):
            try:
                cb(frame)
            except Exception as exc:
                logger.debug("Ingress bus callback error: %s", exc)

        for q in list(self._subscribers):
            try:
                q.put_nowait(frame)
            except asyncio.QueueFull:
                pass  # slow consumer — drop rather than block

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Tick loop: emits a PerceptionFrame every tick_ms milliseconds."""
        self._running = True
        logger.info("Multimodal ingress bus started (tick=%d ms)", self._tick_ms)
        try:
            while self._running:
                frame = self.build_frame()
                await self._emit(frame)
                await asyncio.sleep(self._tick_ms / 1000.0)
        finally:
            self._running = False
            logger.info("Multimodal ingress bus stopped")

    def stop(self) -> None:
        """Signal the tick loop to stop."""
        self._running = False

    # ------------------------------------------------------------------
    # Async generator interface
    # ------------------------------------------------------------------

    async def stream(self):
        """Async generator: yields PerceptionFrames from the bus."""
        q = self.subscribe()
        task = asyncio.create_task(self.run())
        try:
            while not task.done() or not q.empty():
                try:
                    yield await asyncio.wait_for(
                        q.get(), timeout=self._tick_ms / 1000.0 * 3
                    )
                except asyncio.TimeoutError:
                    if task.done():
                        break
        finally:
            self.stop()
            await task
