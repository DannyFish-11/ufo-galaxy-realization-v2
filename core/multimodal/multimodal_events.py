"""Multimodal I/O runtime events.

Defines typed event dataclasses emitted by audio and WebRTC pipelines so
downstream components (event buses, observability sinks, orchestrators) can
react without coupling to specific pipeline internals.

All events carry an optional ``trace_id`` and ``runtime_session_id`` to
allow end-to-end correlation across the Galaxy control plane.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

class MultimodalEventType(str, Enum):
    """Canonical event types for the multimodal I/O subsystem."""

    # Audio
    AUDIO_STREAM_STARTED = "audio.stream.started"
    AUDIO_STREAM_STOPPED = "audio.stream.stopped"
    AUDIO_STREAM_ERROR = "audio.stream.error"
    AUDIO_CHUNK = "audio.chunk"
    AUDIO_QUALITY_DEGRADED = "audio.quality.degraded"

    # WebRTC
    WEBRTC_SESSION_STARTED = "webrtc.session.started"
    WEBRTC_SESSION_STOPPED = "webrtc.session.stopped"
    WEBRTC_SESSION_ERROR = "webrtc.session.error"
    WEBRTC_RECONNECTING = "webrtc.reconnecting"
    WEBRTC_RECONNECTED = "webrtc.reconnected"
    WEBRTC_QUALITY_METRICS = "webrtc.quality.metrics"

    # Transport
    TRANSPORT_FALLBACK = "transport.fallback"


# ---------------------------------------------------------------------------
# Base event
# ---------------------------------------------------------------------------

@dataclass
class MultimodalEvent:
    """Base class for all multimodal runtime events.

    Attributes
    ----------
    event_type      Canonical event type string.
    timestamp       Monotonic timestamp at event creation.
    wall_clock      Wall-clock time for logging/tracing.
    event_id        Unique identifier for this event instance.
    trace_id        Optional trace correlation identifier (e.g. from AIP v3).
    runtime_session_id
                    Optional runtime session identifier.
    metadata        Arbitrary key/value payload for type-specific data.
    """

    event_type: MultimodalEventType
    timestamp: float = field(default_factory=time.monotonic)
    wall_clock: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Audio events
# ---------------------------------------------------------------------------

@dataclass
class AudioStreamStartedEvent(MultimodalEvent):
    """Emitted when the microphone capture pipeline begins streaming."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.AUDIO_STREAM_STARTED, init=False
    )
    sample_rate: int = 16000
    chunk_duration_ms: int = 100
    device: Optional[int] = None


@dataclass
class AudioStreamStoppedEvent(MultimodalEvent):
    """Emitted when the microphone capture pipeline has stopped."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.AUDIO_STREAM_STOPPED, init=False
    )
    reason: str = "stopped"
    total_chunks_processed: int = 0
    total_duration_s: float = 0.0


@dataclass
class AudioStreamErrorEvent(MultimodalEvent):
    """Emitted on an unrecoverable audio pipeline error."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.AUDIO_STREAM_ERROR, init=False
    )
    error: str = ""
    recoverable: bool = False


@dataclass
class AudioQualityDegradedEvent(MultimodalEvent):
    """Emitted when audio latency or chunk delay exceeds threshold."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.AUDIO_QUALITY_DEGRADED, init=False
    )
    latency_ms: float = 0.0
    quality_flag: str = "degraded"


# ---------------------------------------------------------------------------
# WebRTC events
# ---------------------------------------------------------------------------

@dataclass
class WebRTCSessionStartedEvent(MultimodalEvent):
    """Emitted when a WebRTC peer connection reaches 'connected' state."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.WEBRTC_SESSION_STARTED, init=False
    )
    session_id: str = ""
    has_video: bool = True
    has_audio: bool = False


@dataclass
class WebRTCSessionStoppedEvent(MultimodalEvent):
    """Emitted when a WebRTC session is closed or fails permanently."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.WEBRTC_SESSION_STOPPED, init=False
    )
    session_id: str = ""
    reason: str = "closed"
    total_reconnect_attempts: int = 0


@dataclass
class WebRTCSessionErrorEvent(MultimodalEvent):
    """Emitted when a WebRTC session encounters a non-fatal or fatal error."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.WEBRTC_SESSION_ERROR, init=False
    )
    session_id: str = ""
    error: str = ""
    recoverable: bool = True


@dataclass
class WebRTCReconnectingEvent(MultimodalEvent):
    """Emitted when WebRTC session manager initiates a reconnect attempt."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.WEBRTC_RECONNECTING, init=False
    )
    session_id: str = ""
    attempt: int = 1
    max_attempts: int = 5
    delay_s: float = 3.0


@dataclass
class WebRTCQualityMetricsEvent(MultimodalEvent):
    """Emitted periodically with WebRTC quality metrics.

    Fields
    ------
    bitrate_kbps    Estimated inbound bitrate in kbit/s.
    packet_loss_pct Packet loss percentage (0–100).
    rtt_ms          Round-trip time in milliseconds (if available).
    """

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.WEBRTC_QUALITY_METRICS, init=False
    )
    session_id: str = ""
    bitrate_kbps: float = 0.0
    packet_loss_pct: float = 0.0
    rtt_ms: Optional[float] = None


@dataclass
class TransportFallbackEvent(MultimodalEvent):
    """Emitted when the transport router falls back from WebRTC to screenshot."""

    event_type: MultimodalEventType = field(
        default=MultimodalEventType.TRANSPORT_FALLBACK, init=False
    )
    from_method: str = "webrtc"
    to_method: str = "http"
    reason: str = ""
    device_id: str = ""
