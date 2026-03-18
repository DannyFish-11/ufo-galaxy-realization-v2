"""WebRTC camera session management.

Wraps an *aiortc* RTCPeerConnection to receive video frames from a
remote camera source.  Falls back gracefully when aiortc is not installed.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, List, Optional

import numpy as np

from .signal_quality import SignalQuality

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional aiortc import
# ---------------------------------------------------------------------------
_AIORTC_AVAILABLE = False
try:
    from aiortc import RTCPeerConnection, RTCSessionDescription  # noqa: F401

    _AIORTC_AVAILABLE = True
except Exception:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class WebRTCSessionState(str, Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class WebRTCSessionConfig:
    """Configuration for a WebRTC camera session."""

    stun_url: str = "stun:stun.l.google.com:19302"
    reconnect_delay_s: float = 3.0
    max_reconnects: int = 5
    frame_stale_threshold_ms: float = 5000.0  # ms before frame is considered stale


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

class WebRTCCameraSession:
    """Manages a WebRTC peer connection to receive camera video frames.

    Usage::

        session = WebRTCCameraSession()
        answer_sdp = await session.connect(offer_sdp)
        frame, quality = session.get_latest_frame()
        await session.close()
    """

    def __init__(self, config: Optional[WebRTCSessionConfig] = None) -> None:
        self.config = config or WebRTCSessionConfig()
        self._state = WebRTCSessionState.IDLE
        self._quality: SignalQuality = SignalQuality.missing("Not started")
        self._pc = None  # RTCPeerConnection when connected
        self._latest_frame: Optional[np.ndarray] = None
        self._last_frame_ts: Optional[float] = None
        self._frame_callbacks: List[Callable[[np.ndarray], None]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> WebRTCSessionState:
        return self._state

    @property
    def is_available(self) -> bool:
        """True if aiortc is installed."""
        return _AIORTC_AVAILABLE

    def add_frame_callback(self, cb: Callable[[np.ndarray], None]) -> None:
        """Register a callback invoked with each received BGR frame."""
        self._frame_callbacks.append(cb)

    def get_latest_frame(self) -> tuple:
        """Return (frame | None, SignalQuality)."""
        if self._latest_frame is None:
            return None, self._quality
        age_ms = (
            (time.monotonic() - self._last_frame_ts) * 1000.0
            if self._last_frame_ts is not None
            else float("inf")
        )
        if age_ms > self.config.frame_stale_threshold_ms:
            return self._latest_frame, SignalQuality.stale(freshness_ms=age_ms)
        return self._latest_frame, SignalQuality.ok(freshness_ms=age_ms)

    async def connect(
        self, offer_sdp: str, offer_type: str = "offer"
    ) -> Optional[str]:
        """Set the remote offer and return the local answer SDP.

        Returns None when aiortc is unavailable or connection fails.
        """
        if not _AIORTC_AVAILABLE:
            self._quality = SignalQuality.device_unavailable()
            logger.warning("aiortc not available; WebRTC camera ingest disabled")
            return None

        from aiortc import RTCPeerConnection, RTCSessionDescription

        self._state = WebRTCSessionState.CONNECTING
        try:
            self._pc = RTCPeerConnection()

            @self._pc.on("track")  # type: ignore[misc]
            async def on_track(track):
                if track.kind == "video":
                    asyncio.create_task(self._receive_video(track))

            @self._pc.on("connectionstatechange")  # type: ignore[misc]
            async def on_state_change():
                conn_state = self._pc.connectionState
                logger.info("WebRTC connection state: %s", conn_state)
                if conn_state == "connected":
                    self._state = WebRTCSessionState.CONNECTED
                    self._quality = SignalQuality.ok()
                elif conn_state in ("failed", "closed"):
                    self._state = WebRTCSessionState.FAILED
                    self._quality = SignalQuality.degraded("connection " + conn_state)

            await self._pc.setRemoteDescription(
                RTCSessionDescription(sdp=offer_sdp, type=offer_type)
            )
            answer = await self._pc.createAnswer()
            await self._pc.setLocalDescription(answer)
            return self._pc.localDescription.sdp

        except Exception as exc:
            self._state = WebRTCSessionState.FAILED
            self._quality = SignalQuality.degraded(str(exc))
            logger.warning("WebRTC connect error: %s", exc)
            return None

    async def close(self) -> None:
        """Gracefully close the peer connection."""
        if self._pc is not None:
            try:
                await self._pc.close()
            except Exception as exc:
                logger.debug("WebRTC close error: %s", exc)
        self._state = WebRTCSessionState.CLOSED
        self._quality = SignalQuality.missing("Closed")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    async def _receive_video(self, track) -> None:
        """Drain frames from the video track until it ends."""
        try:
            while True:
                frame = await track.recv()
                img = frame.to_ndarray(format="bgr24")
                self._latest_frame = img
                self._last_frame_ts = time.monotonic()
                for cb in list(self._frame_callbacks):
                    try:
                        cb(img)
                    except Exception as exc:
                        logger.debug("Frame callback error: %s", exc)
        except Exception as exc:
            logger.info("Video track ended: %s", exc)
            self._state = WebRTCSessionState.CLOSED
            self._quality = SignalQuality.degraded("track ended")
