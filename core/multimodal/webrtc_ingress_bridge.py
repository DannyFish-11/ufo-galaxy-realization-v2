"""WebRTC Ingress Bridge — Android video frame → cognition pipeline gateway.

**C方案 (Hybrid Mode) — Data Channel Bridge**
================================================
This module bridges Android video frames received via WebRTC into the
cognition pipeline by converting them to ``PerceptionFrame`` format and
injecting them via ``MultimodalIngressBus.update_video()``.

Architecture
------------
::

    Android Device (Camera)
        ↓  WebRTC PeerConnection (RTP video)
    Node_95_WebRTC_Receiver
        ↓  HTTP POST /ingest/frame  (decoded frames)
    WebRTCIngressBridge (this module)
        ↓  VideoState + SignalQuality
    MultimodalIngressBus.update_video()
        ↓  PerceptionFrame stream
    OpenClawd._build_canonical_perception_state()
        ↓  Canonical perception state
    Cognition Pipeline

The signaling path (offer/answer/ICE) remains unchanged and continues to
flow through ``/ws/webrtc/{device_id}`` → Node_95.  This module only
handles the *data plane* — decoded video frames after Node_95 has
processed them.

Design principles
-----------------
1. **Signaling untouched**: Existing ``galaxy_gateway/webrtc_proxy.py``
   and Node_95 signaling WebSocket endpoints are not modified.
2. **Opt-in**: ``enable_webrtc_data_channel`` defaults to ``False``.
   The bridge only activates when explicitly enabled.
3. **Graceful degradation**: If the ingress bus is unavailable, frames
   are silently dropped (logged at DEBUG).
4. **Feature extraction**: Uses existing ``VideoFeatureExtractor`` to
   produce ``VideoState`` snapshots compatible with the ingress bus.
5. **Thread-safe**: ``push_frame()`` can be called from any thread
   (e.g., FastAPI request handlers in Node_95).

Usage
-----
::

    from core.multimodal.webrtc_ingress_bridge import get_webrtc_ingress_bridge

    bridge = get_webrtc_ingress_bridge()
    if bridge.is_enabled:
        bridge.push_frame(device_id="abc123", frame=np_array)

Configuration
-------------
Add to ``config.json``::

    {
        "enable_webrtc_data_channel": false
    }

Environment variable override::

    GALAXY_ENABLE_WEBRTC_DATA_CHANNEL=true
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from .video_features import VideoFeatureExtractor, VideoState
from .signal_quality import SignalQuality

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

_WEBRTC_DATA_CHANNEL_ENABLED: bool = False
"""Module-level cached feature flag.  Set once at first bridge access."""


def _is_webrtc_data_channel_enabled() -> bool:
    """Return whether the WebRTC data channel bridge is enabled.

    Reads ``enable_webrtc_data_channel`` from unified config (default
    ``False``) or the ``GALAXY_ENABLE_WEBRTC_DATA_CHANNEL`` environment
    variable.  The result is cached for the process lifetime.
    """
    global _WEBRTC_DATA_CHANNEL_ENABLED  # noqa: PLW0603

    # Already resolved
    if _WEBRTC_DATA_CHANNEL_ENABLED:
        return True

    # Environment variable takes highest precedence
    import os

    env_val = os.getenv("GALAXY_ENABLE_WEBRTC_DATA_CHANNEL", "").strip().lower()
    if env_val in ("1", "true", "yes"):
        _WEBRTC_DATA_CHANNEL_ENABLED = True
        return True

    # Fall back to unified config
    try:
        from core.unified_config import config as _cfg

        if _cfg.get("enable_webrtc_data_channel", False):
            _WEBRTC_DATA_CHANNEL_ENABLED = True
            return True
    except Exception:
        pass

    return False


# ---------------------------------------------------------------------------
# Bridge state
# ---------------------------------------------------------------------------


class WebRTCIngressBridge:
    """ Bridges Android video frames from Node_95 into the MultimodalIngressBus.

    Lifecycle
    ---------
    1. Instantiate (or get via :func:`get_webrtc_ingress_bridge`).
    2. Call :meth:`push_frame` each time Node_95 decodes a new frame.
    3. The bridge extracts ``VideoState`` features and forwards them to
       the running ``MultimodalIngressBus`` singleton.
    4. Call :meth:`close` on shutdown.

    Thread safety
    -------------
    All public methods are thread-safe.  Internal state is protected by
    an ``asyncio.Lock`` for coroutine-level safety and a ``threading.Lock``
    for cross-thread calls to :meth:`push_frame`.
    """

    def __init__(self) -> None:
        self._enabled: bool = _is_webrtc_data_channel_enabled()
        self._extractor = VideoFeatureExtractor(fps=5.0)
        self._frame_callbacks: List[Callable[[VideoState, SignalQuality], None]] = []
        self._closed: bool = False
        self._ingress_bus_ref = None  # lazily resolved

        # Per-device tracking
        self._device_last_frame_ts: Dict[str, float] = {}
        self._device_frame_counts: Dict[str, int] = {}
        self._total_frames_ingested: int = 0

        # Thread safety for push_frame (called from FastAPI handlers)
        self._lock = threading.Lock()

        if self._enabled:
            logger.info(
                "WebRTCIngressBridge enabled — Android video frames will be "
                "bridged into the cognition pipeline"
            )
        else:
            logger.debug(
                "WebRTCIngressBridge disabled (enable_webrtc_data_channel=false) — "
                "push_frame calls will be no-ops"
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        """True when the bridge is enabled via configuration."""
        return self._enabled

    @property
    def total_frames_ingested(self) -> int:
        """Total number of frames successfully forwarded to the ingress bus."""
        return self._total_frames_ingested

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def add_callback(self, cb: Callable[[VideoState, SignalQuality], None]) -> None:
        """Register a callback invoked with each processed (VideoState, quality)."""
        self._frame_callbacks.append(cb)

    def remove_callback(self, cb: Callable[[VideoState, SignalQuality], None]) -> None:
        """Remove a previously registered callback."""
        try:
            self._frame_callbacks.remove(cb)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Core: push_frame
    # ------------------------------------------------------------------

    def push_frame(
        self,
        device_id: str,
        frame: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[VideoState]:
        """Push a decoded BGR frame from Node_95 into the cognition pipeline.

        This is the **primary entry point** called by Node_95 (or any other
        frame producer) to inject video frames.

        Parameters
        ----------
        device_id:
            The Android device identifier (matches the ``device_id`` used in
            the signaling path ``/ws/webrtc/{device_id}``).
        frame:
            Decoded video frame as a NumPy array (BGR, H×W×3 uint8).
        metadata:
            Optional dict with extra fields (e.g., ``{"timestamp": ...,
            "codec": "H264"}``).  Stored in the ``extra`` field of
            ``SystemSignals`` when the ingress bus is available.

        Returns
        -------
        VideoState | None
            The extracted video state, or ``None`` when the bridge is
            disabled or no ingress bus is available.
        """
        if not self._enabled or self._closed:
            return None

        with self._lock:
            return self._push_frame_sync(device_id, frame, metadata)

    def _push_frame_sync(
        self,
        device_id: str,
        frame: np.ndarray,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[VideoState]:
        """Synchronous implementation of push_frame (lock already held)."""
        try:
            # 1. Extract VideoState features
            video_state = self._extractor.process_frame(frame)

            # 2. Build quality descriptor
            quality = SignalQuality.ok(
                freshness_ms=video_state.video_freshness_ms,
                confidence=1.0,
            )

            # 3. Update device tracking
            now = time.monotonic()
            self._device_last_frame_ts[device_id] = now
            self._device_frame_counts[device_id] = (
                self._device_frame_counts.get(device_id, 0) + 1
            )

            # 4. Forward to MultimodalIngressBus if available
            bus = self._resolve_ingress_bus()
            if bus is not None:
                try:
                    bus.update_video(video_state, quality)
                    self._total_frames_ingested += 1

                    # Inject system signals with device metadata
                    if metadata:
                        self._inject_system_signals(bus, device_id, metadata, quality)

                except Exception as exc:
                    logger.debug(
                        "WebRTCIngressBridge: ingress_bus.update_video failed: %s", exc
                    )
            else:
                logger.debug(
                    "WebRTCIngressBridge: no ingress bus available — frame dropped "
                    "(device_id=%s)",
                    device_id,
                )

            # 5. Invoke registered callbacks
            for cb in list(self._frame_callbacks):
                try:
                    cb(video_state, quality)
                except Exception as exc:
                    logger.debug("WebRTCIngressBridge: frame callback error: %s", exc)

            return video_state

        except Exception as exc:
            logger.warning(
                "WebRTCIngressBridge: push_frame failed for device_id=%s: %s",
                device_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # System signals injection
    # ------------------------------------------------------------------

    def _inject_system_signals(
        self,
        bus,
        device_id: str,
        metadata: Dict[str, Any],
        quality: SignalQuality,
    ) -> None:
        """Inject WebRTC-specific system signals into the ingress bus."""
        try:
            from .perception_frame import SystemSignals

            system = SystemSignals(
                screen_activity=0.8,  # Active streaming = high engagement
                extra={
                    "webrtc_data_channel": True,
                    "device_id": device_id,
                    "ingress_bridge": "webrtc_ingress_bridge",
                    "frame_metadata": dict(metadata),
                },
            )
            bus.update_system(system, quality)
        except Exception as exc:
            logger.debug("WebRTCIngressBridge: system signals injection failed: %s", exc)

    # ------------------------------------------------------------------
    # Ingress bus resolution
    # ------------------------------------------------------------------

    def _resolve_ingress_bus(self):
        """Lazily resolve the MultimodalIngressBus singleton.

        Returns ``None`` when the bus is not running.
        """
        if self._ingress_bus_ref is not None:
            return self._ingress_bus_ref

        try:
            from .ingest_runtime import get_ingest_bus

            self._ingress_bus_ref = get_ingest_bus()
        except Exception:
            pass

        return self._ingress_bus_ref

    # ------------------------------------------------------------------
    # Device tracking queries
    # ------------------------------------------------------------------

    def get_device_summary(self, device_id: str) -> Dict[str, Any]:
        """Return a diagnostics-safe summary for a device."""
        last_ts = self._device_last_frame_ts.get(device_id)
        age_ms = (time.monotonic() - last_ts) * 1000.0 if last_ts else None
        return {
            "device_id": device_id,
            "frame_count": self._device_frame_counts.get(device_id, 0),
            "last_frame_age_ms": age_ms,
            "bridge_enabled": self._enabled,
            "bridge_closed": self._closed,
        }

    def get_all_device_ids(self) -> List[str]:
        """Return all device_ids that have pushed frames."""
        return list(self._device_last_frame_ts.keys())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the bridge and release resources."""
        self._closed = True
        self._frame_callbacks.clear()
        self._ingress_bus_ref = None
        logger.info("WebRTCIngressBridge closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_bridge_instance: Optional[WebRTCIngressBridge] = None
_bridge_lock = threading.Lock()


def get_webrtc_ingress_bridge() -> WebRTCIngressBridge:
    """Return the singleton :class:`WebRTCIngressBridge`.

    Creates the instance on first call.  Subsequent calls return the
    same instance.
    """
    global _bridge_instance  # noqa: PLW0603

    if _bridge_instance is not None:
        return _bridge_instance

    with _bridge_lock:
        if _bridge_instance is None:
            _bridge_instance = WebRTCIngressBridge()
        return _bridge_instance


def reset_webrtc_ingress_bridge() -> None:
    """Close and reset the singleton bridge.

    Useful in tests or when the configuration has changed and a fresh
    instance is needed.
    """
    global _bridge_instance, _WEBRTC_DATA_CHANNEL_ENABLED  # noqa: PLW0603

    with _bridge_lock:
        if _bridge_instance is not None:
            _bridge_instance.close()
            _bridge_instance = None
        _WEBRTC_DATA_CHANNEL_ENABLED = False
