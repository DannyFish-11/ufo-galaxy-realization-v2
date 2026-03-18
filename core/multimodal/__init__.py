"""Multimodal ingress foundation for Galaxy.

Modules:
  signal_quality  — SignalQuality / QualityFlag metadata
  vad             — Lightweight energy-based Voice Activity Detection
  audio_features  — AudioState feature extraction
  audio_ingest    — Microphone capture pipeline
  video_features  — VideoState feature extraction
  webrtc_session  — WebRTC camera session management
  video_ingest    — Camera ingest pipeline
  perception_frame — PerceptionFrame unified snapshot
  ingress_bus     — MultimodalIngressBus merging all signals
"""

from .signal_quality import SignalQuality, QualityFlag
from .perception_frame import PerceptionFrame, SystemSignals
from .ingress_bus import MultimodalIngressBus

__all__ = [
    "SignalQuality",
    "QualityFlag",
    "PerceptionFrame",
    "SystemSignals",
    "MultimodalIngressBus",
]
