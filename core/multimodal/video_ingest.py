"""WebRTC camera ingest pipeline with video state extraction.

Wraps WebRTCCameraSession and VideoFeatureExtractor to produce VideoState
frames every ~200–500 ms.  Handles camera unavailable / permission errors
gracefully: the pipeline degrades without breaking the main flow.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable, List, Optional

import numpy as np

from .webrtc_session import WebRTCCameraSession, WebRTCSessionConfig, WebRTCSessionState
from .video_features import VideoFeatureExtractor, VideoState
from .signal_quality import SignalQuality, QualityFlag

logger = logging.getLogger(__name__)


@dataclass
class VideoIngestConfig:
    """Configuration for the camera ingest pipeline."""

    sample_interval_ms: int = 300         # Feature extraction interval (~3.3 fps)
    enable_face_detection: bool = False   # Optional Haar-cascade face detection
    scene_change_threshold: float = 0.35
    no_frame_degraded_threshold_ms: float = 5000.0  # Mark degraded after this
    webrtc_config: Optional[WebRTCSessionConfig] = None


class VideoIngestPipeline:
    """Camera ingest pipeline that extracts lightweight VideoState features.

    Usage::

        pipeline = VideoIngestPipeline()
        answer_sdp = await pipeline.connect(offer_sdp)
        pipeline.add_callback(my_handler)
        await pipeline.run()          # blocks until stop() called

    The pipeline can also be used without a live WebRTC session by directly
    calling push_frame() to inject test / pre-captured frames.
    """

    def __init__(self, config: Optional[VideoIngestConfig] = None) -> None:
        self.config = config or VideoIngestConfig()
        self._session = WebRTCCameraSession(config=self.config.webrtc_config)
        self._extractor = VideoFeatureExtractor(
            fps=1000.0 / max(self.config.sample_interval_ms, 1),
            scene_change_threshold=self.config.scene_change_threshold,
        )
        self._running = False
        self._quality: SignalQuality = SignalQuality.missing("Not started")
        self._latest_state: Optional[VideoState] = None
        self._callbacks: List[Callable[[VideoState, SignalQuality], None]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if aiortc is installed."""
        return self._session.is_available

    def add_callback(
        self, cb: Callable[[VideoState, SignalQuality], None]
    ) -> None:
        """Register a callback invoked with each new VideoState."""
        self._callbacks.append(cb)

    def get_latest(self) -> tuple:
        """Return (VideoState | None, SignalQuality) for the most recent frame."""
        return self._latest_state, self._quality

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False

    async def connect(
        self, offer_sdp: str, offer_type: str = "offer"
    ) -> Optional[str]:
        """Establish a WebRTC session.  Returns answer SDP or None on failure."""
        return await self._session.connect(offer_sdp=offer_sdp, offer_type=offer_type)

    async def close(self) -> None:
        """Stop ingest and close the WebRTC session."""
        self.stop()
        await self._session.close()

    def push_frame(self, frame: np.ndarray) -> Optional[VideoState]:
        """Directly inject a frame (useful for testing without live WebRTC).

        Returns the extracted VideoState.
        """
        state = self._extractor.process_frame(
            frame, enable_face=self.config.enable_face_detection
        )
        self._latest_state = state
        quality = SignalQuality.ok(freshness_ms=state.video_freshness_ms)
        self._quality = quality
        for cb in list(self._callbacks):
            try:
                cb(state, quality)
            except Exception as exc:
                logger.debug("Video callback error: %s", exc)
        return state

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Feature extraction loop — polls the WebRTC session for new frames."""
        self._running = True
        if not self._session.is_available:
            self._quality = SignalQuality.device_unavailable()
            logger.warning("aiortc not available; video ingest running in stub mode")

        logger.info(
            "Video ingest loop started (interval=%d ms)", self.config.sample_interval_ms
        )

        while self._running:
            try:
                frame, frame_quality = self._session.get_latest_frame()

                if frame is not None and frame_quality.is_usable:
                    state = self._extractor.process_frame(
                        frame, enable_face=self.config.enable_face_detection
                    )
                    self._latest_state = state
                    self._quality = SignalQuality.ok(
                        freshness_ms=state.video_freshness_ms
                    )
                    for cb in list(self._callbacks):
                        try:
                            cb(state, self._quality)
                        except Exception as exc:
                            logger.debug("Video callback error: %s", exc)
                else:
                    # No usable frame — update staleness quality
                    if self._latest_state is not None:
                        age_ms = (
                            time.monotonic() - self._latest_state.timestamp
                        ) * 1000.0
                        if age_ms > self.config.no_frame_degraded_threshold_ms:
                            self._quality = SignalQuality.degraded(
                                "no new frames received"
                            )

                await asyncio.sleep(self.config.sample_interval_ms / 1000.0)

            except Exception as exc:
                logger.warning("Video ingest error: %s", exc)
                self._quality = SignalQuality.degraded(str(exc))
                await asyncio.sleep(1.0)

        logger.info("Video ingest loop stopped")

    # ------------------------------------------------------------------
    # Async generator interface
    # ------------------------------------------------------------------

    async def stream(self) -> AsyncIterator:
        """Yield (VideoState, SignalQuality) as they arrive."""
        states: asyncio.Queue = asyncio.Queue(maxsize=50)

        def _enqueue(state: VideoState, quality: SignalQuality) -> None:
            try:
                states.put_nowait((state, quality))
            except asyncio.QueueFull:
                pass

        self.add_callback(_enqueue)
        task = asyncio.create_task(self.run())
        try:
            while not task.done() or not states.empty():
                try:
                    yield await asyncio.wait_for(
                        states.get(),
                        timeout=self.config.sample_interval_ms / 1000.0 * 3,
                    )
                except asyncio.TimeoutError:
                    if task.done():
                        break
        finally:
            self.stop()
            await task
