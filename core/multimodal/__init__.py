"""Multimodal ingress foundation for Galaxy.

Modules:
  signal_quality         — SignalQuality / QualityFlag metadata
  vad                    — Lightweight energy-based Voice Activity Detection
  audio_features         — AudioState feature extraction
  audio_ingest           — Low-level microphone capture pipeline
  audio_capture_service  — High-level audio capture service with events
  video_features         — VideoState feature extraction
  webrtc_session         — WebRTC camera session (aiortc wrapper)
  webrtc_session_manager — WebRTC session manager with reconnect + events
  video_ingest           — Camera ingest pipeline
  perception_frame       — PerceptionFrame unified snapshot
  ingress_bus            — MultimodalIngressBus merging all signals
  multimodal_events      — Typed runtime events for audio/WebRTC pipelines
"""

from .signal_quality import SignalQuality, QualityFlag
from .perception_frame import PerceptionFrame, SystemSignals
from .ingress_bus import MultimodalIngressBus
from .multimodal_events import (
    MultimodalEventType,
    MultimodalEvent,
    AudioStreamStartedEvent,
    AudioStreamStoppedEvent,
    AudioStreamErrorEvent,
    AudioQualityDegradedEvent,
    WebRTCSessionStartedEvent,
    WebRTCSessionStoppedEvent,
    WebRTCSessionErrorEvent,
    WebRTCReconnectingEvent,
    WebRTCQualityMetricsEvent,
    TransportFallbackEvent,
)
from .audio_capture_service import AudioCaptureService, AudioCaptureConfig
from .webrtc_session_manager import WebRTCSessionManager, WebRTCManagerConfig

__all__ = [
    # Core quality / frame types
    "SignalQuality",
    "QualityFlag",
    "PerceptionFrame",
    "SystemSignals",
    "MultimodalIngressBus",
    # Event types
    "MultimodalEventType",
    "MultimodalEvent",
    "AudioStreamStartedEvent",
    "AudioStreamStoppedEvent",
    "AudioStreamErrorEvent",
    "AudioQualityDegradedEvent",
    "WebRTCSessionStartedEvent",
    "WebRTCSessionStoppedEvent",
    "WebRTCSessionErrorEvent",
    "WebRTCReconnectingEvent",
    "WebRTCQualityMetricsEvent",
    "TransportFallbackEvent",
    # High-level services
    "AudioCaptureService",
    "AudioCaptureConfig",
    "WebRTCSessionManager",
    "WebRTCManagerConfig",
]
