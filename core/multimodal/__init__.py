"""Multimodal ingress foundation for Galaxy.

Modules:
  signal_quality              — SignalQuality / QualityFlag metadata
  vad                         — Lightweight energy-based Voice Activity Detection
  audio_features              — AudioState feature extraction
  audio_ingest                — Low-level microphone capture pipeline
  audio_capture_service       — High-level audio capture service with events
  video_features              — VideoState feature extraction
  webrtc_session              — WebRTC camera session (aiortc wrapper)
  webrtc_session_manager      — WebRTC session manager with reconnect + events
  video_ingest                — Camera ingest pipeline
  perception_frame            — PerceptionFrame unified snapshot
  ingress_bus                 — MultimodalIngressBus merging all signals
  multimodal_events           — Typed runtime events for audio/WebRTC pipelines
  perception_source_registry  — Runtime-shell-owned source registry (PR-17)
  webrtc_ingress_bridge       — WebRTC → cognition pipeline bridge (C方案)
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
from .perception_source_registry import (
    PerceptionSourceType,
    SourceModality,
    SourceHealthStatus,
    PerceptionSourceRecord,
    PerceptionSourceRegistry,
)
from .modality_confidence_policy import (
    ModalityPresence,
    SourceDegradationSeverity,
    ModalitySemantics,
    RoutingEligibilityReason,
    ModalityConfidencePolicy,
    RoutingEligibilityAssessment,
    PerceptionRoutingReadiness,
    assess_modality_confidence,
    assess_routing_eligibility,
    build_perception_routing_readiness,
)
from .webrtc_ingress_bridge import (
    WebRTCIngressBridge,
    get_webrtc_ingress_bridge,
    reset_webrtc_ingress_bridge,
)

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
    # Perception source registry (PR-17)
    "PerceptionSourceType",
    "SourceModality",
    "SourceHealthStatus",
    "PerceptionSourceRecord",
    "PerceptionSourceRegistry",
    # Modality confidence policy — source-to-routing calibration (PR-27)
    "ModalityPresence",
    "SourceDegradationSeverity",
    "ModalitySemantics",
    "RoutingEligibilityReason",
    "ModalityConfidencePolicy",
    "RoutingEligibilityAssessment",
    "PerceptionRoutingReadiness",
    "assess_modality_confidence",
    "assess_routing_eligibility",
    "build_perception_routing_readiness",
    # WebRTC ingress bridge (C方案 — Hybrid Mode)
    "WebRTCIngressBridge",
    "get_webrtc_ingress_bridge",
    "reset_webrtc_ingress_bridge",
]
