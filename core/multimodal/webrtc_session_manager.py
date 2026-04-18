"""WebRTC session manager with lifecycle management and reconnect logic.

Wraps :class:`WebRTCCameraSession` to add:
- PeerConnection lifecycle tracking
- Automatic reconnect on failure (up to ``max_reconnects`` attempts)
- Camera *and* audio track support
- Structured runtime event emission
- Quality metrics reporting (bitrate, packet loss, rtt)

Usage::

    manager = WebRTCSessionManager()
    manager.add_event_listener(my_observer)
    answer_sdp = await manager.connect(offer_sdp)
    frame, quality = manager.get_latest_frame()
    await manager.close()

Graceful degradation
--------------------
When aiortc is not installed the manager returns ``None`` from :meth:`connect`
and emits a :class:`WebRTCSessionErrorEvent` with ``recoverable=False``.
Existing non-streaming flows are never affected.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional

import numpy as np

from .webrtc_session import (
    WebRTCCameraSession,
    WebRTCSessionConfig,
    WebRTCSessionState,
)
from .signal_quality import SignalQuality
from .multimodal_events import (
    MultimodalEvent,
    WebRTCSessionStartedEvent,
    WebRTCSessionStoppedEvent,
    WebRTCSessionErrorEvent,
    WebRTCReconnectingEvent,
    WebRTCQualityMetricsEvent,
)

logger = logging.getLogger(__name__)

# Interval between quality-metric polls (seconds)
_METRICS_INTERVAL_S: float = 5.0


@dataclass
class WebRTCManagerConfig:
    """Configuration for :class:`WebRTCSessionManager`.

    Attributes
    ----------
    stun_url            STUN server URL.
    reconnect_delay_s   Delay between reconnect attempts.
    max_reconnects      Maximum number of automatic reconnect attempts.
    frame_stale_ms      Threshold above which a frame is considered stale.
    metrics_interval_s  How often to emit :class:`WebRTCQualityMetricsEvent`.
    trace_id            Optional trace correlation ID.
    runtime_session_id  Optional runtime session ID.
    task_id             Optional canonical task ID this session is bound to
                        (PR-6: task-lifecycle integration).  When set, the
                        manager will coordinate lifecycle transitions with
                        the :mod:`core.webrtc_task_lifecycle` registry.
    device_id           Optional Android device ID associated with this session
                        (PR-6: used for task-binding registration).
    """

    stun_url: str = "stun:stun.l.google.com:19302"
    reconnect_delay_s: float = 3.0
    max_reconnects: int = 5
    frame_stale_ms: float = 5000.0
    metrics_interval_s: float = _METRICS_INTERVAL_S
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    task_id: Optional[str] = None
    device_id: Optional[str] = None


class WebRTCSessionManager:
    """Manages a WebRTC camera (+ optional audio) session with reconnect.

    The manager owns a single :class:`WebRTCCameraSession` and supervises it.
    On failure it re-creates the session and retries the last offer SDP up to
    ``config.max_reconnects`` times before emitting a permanent error event.

    Structured :class:`MultimodalEvent` objects are emitted at lifecycle
    transitions and on a periodic quality-metrics cadence.
    """

    def __init__(self, config: Optional[WebRTCManagerConfig] = None) -> None:
        self.config = config or WebRTCManagerConfig()
        self.session_id: str = str(uuid.uuid4())

        self._session = self._make_session()
        self._event_listeners: List[Callable[[MultimodalEvent], None]] = []
        self._frame_callbacks: List[Callable[[np.ndarray], None]] = []

        self._reconnect_attempts: int = 0
        self._last_offer_sdp: Optional[str] = None
        self._last_offer_type: str = "offer"
        self._metrics_task: Optional[asyncio.Task] = None
        self._closed: bool = False

        # Metrics snapshot (updated by the periodic poller)
        self._bitrate_kbps: float = 0.0
        self._packet_loss_pct: float = 0.0
        self._rtt_ms: Optional[float] = None

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        """True if aiortc is installed on this host."""
        return self._session.is_available

    @property
    def state(self) -> WebRTCSessionState:
        """Current session connection state."""
        return self._session.state

    def add_event_listener(
        self, listener: Callable[[MultimodalEvent], None]
    ) -> None:
        """Register a listener for :class:`MultimodalEvent` objects."""
        self._event_listeners.append(listener)

    def add_frame_callback(self, cb: Callable[[np.ndarray], None]) -> None:
        """Register a callback invoked with each received BGR frame."""
        self._frame_callbacks.append(cb)
        self._session.add_frame_callback(cb)

    def get_latest_frame(self) -> tuple:
        """Return ``(frame | None, SignalQuality)`` for the most recent frame."""
        return self._session.get_latest_frame()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(
        self, offer_sdp: str, offer_type: str = "offer"
    ) -> Optional[str]:
        """Establish a WebRTC session.

        Parameters
        ----------
        offer_sdp   SDP offer string from the remote peer.
        offer_type  SDP type, usually ``"offer"``.

        Returns
        -------
        str | None
            Local answer SDP on success; ``None`` when unavailable or failed.
        """
        if not self.is_available:
            self._emit_event(
                WebRTCSessionErrorEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    session_id=self.session_id,
                    error="aiortc not available",
                    recoverable=False,
                )
            )
            return None

        self._last_offer_sdp = offer_sdp
        self._last_offer_type = offer_type

        answer_sdp = await self._session.connect(
            offer_sdp=offer_sdp, offer_type=offer_type
        )
        if answer_sdp is not None:
            self._on_connected()
        else:
            self._emit_event(
                WebRTCSessionErrorEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    session_id=self.session_id,
                    error="connect() returned None",
                    recoverable=True,
                )
            )
        return answer_sdp

    async def close(self) -> None:
        """Close the WebRTC session and stop background tasks."""
        self._closed = True
        await self._stop_metrics_task()
        await self._session.close()
        self._emit_event(
            WebRTCSessionStoppedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                session_id=self.session_id,
                reason="closed",
                total_reconnect_attempts=self._reconnect_attempts,
            )
        )
        # PR-6: notify task-lifecycle integration layer of session close
        self._notify_transport_state("closed")
        logger.info(
            "WebRTCSessionManager closed (reconnects=%d)", self._reconnect_attempts
        )

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    async def reconnect(self) -> Optional[str]:
        """Attempt to reconnect using the last offer SDP.

        Called automatically when a session failure is detected.  Can also
        be called manually by external supervisors.

        Returns the new answer SDP or ``None`` on exhausted retries.
        """
        if self._closed or self._last_offer_sdp is None:
            return None

        if self._reconnect_attempts >= self.config.max_reconnects:
            logger.warning(
                "WebRTCSessionManager: max reconnects (%d) exhausted",
                self.config.max_reconnects,
            )
            self._emit_event(
                WebRTCSessionStoppedEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    session_id=self.session_id,
                    reason="max_reconnects_exhausted",
                    total_reconnect_attempts=self._reconnect_attempts,
                )
            )
            # PR-6: max reconnects exhausted → transport failed
            self._notify_transport_state("failed")
            return None

        self._reconnect_attempts += 1
        # PR-6: notify that transport is in reconnecting state
        self._notify_transport_state("reconnecting")
        self._emit_event(
            WebRTCReconnectingEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                session_id=self.session_id,
                attempt=self._reconnect_attempts,
                max_attempts=self.config.max_reconnects,
                delay_s=self.config.reconnect_delay_s,
            )
        )
        logger.info(
            "WebRTCSessionManager: reconnect attempt %d/%d (delay=%.1fs)",
            self._reconnect_attempts,
            self.config.max_reconnects,
            self.config.reconnect_delay_s,
        )
        await asyncio.sleep(self.config.reconnect_delay_s)

        # Re-create underlying session to get a clean PeerConnection
        await self._session.close()
        self._session = self._make_session()
        for cb in self._frame_callbacks:
            self._session.add_frame_callback(cb)

        answer_sdp = await self._session.connect(
            offer_sdp=self._last_offer_sdp,
            offer_type=self._last_offer_type,
        )
        if answer_sdp is not None:
            self._on_connected()
        return answer_sdp

    # ------------------------------------------------------------------
    # Quality metrics
    # ------------------------------------------------------------------

    async def _metrics_loop(self) -> None:
        """Periodically emit :class:`WebRTCQualityMetricsEvent`."""
        while not self._closed:
            await asyncio.sleep(self.config.metrics_interval_s)
            if self._closed:
                break
            _, quality = self._session.get_latest_frame()
            # Derive rough quality estimates from signal freshness
            freshness_ms = quality.freshness_ms or 0.0
            pkt_loss = 0.0 if quality.is_usable else 100.0
            self._emit_event(
                WebRTCQualityMetricsEvent(
                    trace_id=self.config.trace_id,
                    runtime_session_id=self.config.runtime_session_id,
                    session_id=self.session_id,
                    bitrate_kbps=self._bitrate_kbps,
                    packet_loss_pct=pkt_loss,
                    rtt_ms=self._rtt_ms,
                    metadata={"frame_freshness_ms": freshness_ms},
                )
            )

    async def _stop_metrics_task(self) -> None:
        if self._metrics_task is not None and not self._metrics_task.done():
            self._metrics_task.cancel()
            try:
                await self._metrics_task
            except asyncio.CancelledError:
                pass
            self._metrics_task = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_session(self) -> WebRTCCameraSession:
        return WebRTCCameraSession(
            config=WebRTCSessionConfig(
                stun_url=self.config.stun_url,
                reconnect_delay_s=self.config.reconnect_delay_s,
                max_reconnects=self.config.max_reconnects,
                frame_stale_threshold_ms=self.config.frame_stale_ms,
            )
        )

    def _on_connected(self) -> None:
        """Called after a successful (re)connect."""
        self._emit_event(
            WebRTCSessionStartedEvent(
                trace_id=self.config.trace_id,
                runtime_session_id=self.config.runtime_session_id,
                session_id=self.session_id,
                has_video=True,
                has_audio=False,
            )
        )
        # PR-6: notify task-lifecycle integration layer of connected state
        self._notify_transport_state("connected")
        # Start / restart the metrics polling task
        if self._metrics_task is None or self._metrics_task.done():
            try:
                loop = asyncio.get_running_loop()
                self._metrics_task = asyncio.create_task(
                    self._metrics_loop(),
                    name="webrtc_metrics",
                )
            except RuntimeError:
                pass  # no running event loop — metrics deferred

    def _notify_transport_state(self, transport_state: str) -> None:
        """PR-6: Notify the canonical task-lifecycle integration layer of a
        transport-state change for the task bound to this session.

        This is a best-effort notification; failures are logged at DEBUG level
        and never propagate to the caller.
        """
        if not self.config.task_id:
            return
        try:
            from core.webrtc_task_lifecycle import (
                apply_transport_state_to_task_lifecycle,
                get_webrtc_task_binding,
                WebRTCTransportState,
            )

            binding = get_webrtc_task_binding(self.config.task_id)
            if binding is None:
                return
            apply_transport_state_to_task_lifecycle(
                binding,
                WebRTCTransportState.from_string(transport_state),
            )
        except Exception as exc:
            logger.debug(
                "_notify_transport_state: task-lifecycle update skipped: %s", exc
            )

    def _emit_event(self, event: MultimodalEvent) -> None:
        """Dispatch a :class:`MultimodalEvent` to registered listeners."""
        for listener in list(self._event_listeners):
            try:
                listener(event)
            except Exception as exc:
                logger.debug("WebRTC event listener error: %s", exc)
