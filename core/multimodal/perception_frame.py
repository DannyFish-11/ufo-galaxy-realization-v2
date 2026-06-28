"""core/multimodal/perception_frame.py — Continuous Host Perception Snapshot

**Unified-Subject Architecture — Runtime Shell Layer**
------------------------------------------------------
``PerceptionFrame`` is the output unit of the *continuous host perception*
pipeline owned by :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
(the Windows desktop runtime shell).

Each frame is a timestamped snapshot of the ambient Windows environment:
audio, video, and system signals.  Frames are produced by
:class:`~core.multimodal.ingress_bus.MultimodalIngressBus` and represent
the subject's ongoing sensory awareness of the host device — independent of
any individual request.

This is distinct from ``multimodal_context`` (per-request payload fusion):

.. code-block:: text

    PerceptionFrame  ← continuous host perception (runtime shell)
        Audio / Video / System signals merged per tick interval
        Represents ambient Windows environment awareness

    multimodal_context ← request-bound payload (OpenClawd / MultimodalBus)
        Caller-attached images / audio clips for a single request
        Fused via MultimodalBus.ingest → fusion_summary for the prompt

Merges audio, video, and system signals into a single object consumed by
downstream reasoning layers.  Missing modalities are tolerated: quality
flags communicate availability, and all signal fields default to None.

Schema version: 1
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .audio_features import AudioState
from .video_features import VideoState
from .signal_quality import SignalQuality


@dataclass
class SystemSignals:
    """System-level signals (screen activity, resource usage, etc.)."""

    screen_activity: float = 0.0    # Proxy for engagement [0, 1]
    cpu_load: Optional[float] = None
    memory_load: Optional[float] = None
    active_app: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # PR-ACTIVE-PERCEPTION: tool-chain snapshot — what the host can do right now
    # Populated by MultimodalIngressBus._scan_toolchain() every N ticks.
    # Keys: python, node, docker, vscode, git, browser, … (empty dict = not scanned)
    toolchain: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ScreenState:
    """Latest screen snapshot (desktop overlay / native capture).

    Distinct from ``video`` (webcam看物理环境): ``screen`` 是屏幕内容本身。
    携带原始 JPEG base64（供认知层原生“看屏幕”，**不进 to_dict** 以免日志爆量）
    + 可选结构化屏幕上下文（如前台窗口 UIA 树）+ 一个便宜的帧间变化分数。
    """

    image_b64: Optional[str] = None        # raw JPEG base64 (NOT serialised)
    mime: str = "image/jpeg"
    change_score: float = 0.0              # cheap 0..1 change vs previous frame
    meta: Optional[Dict[str, Any]] = None  # structured screen context (UIA tree, etc.)
    screen_freshness_ms: float = 0.0
    has_image: bool = False


@dataclass
class PerceptionFrame:
    """Unified multimodal state snapshot for downstream consumption.

    Fields
    ------
    timestamp       Monotonic clock at frame construction.
    wall_clock      Wall-clock time (time.time()) for logging/tracing.
    audio           AudioState if audio modality is usable, else None.
    audio_quality   Quality/freshness descriptor for audio.
    video           VideoState if video modality is usable, else None.
    video_quality   Quality/freshness descriptor for video.
    screen          ScreenState if screen modality is usable, else None.
    screen_quality  Quality/freshness descriptor for the screen modality.
    system          SystemSignals if system modality is usable, else None.
    system_quality  Quality/freshness descriptor for system signals.
    frame_id        Monotonically increasing integer per ingress bus.
    schema_version  Protocol version (always 1 for this release).
    """

    # Timing
    timestamp: float = field(default_factory=time.monotonic)
    wall_clock: float = field(default_factory=time.time)

    # Audio modality
    audio: Optional[AudioState] = None
    audio_quality: SignalQuality = field(default_factory=SignalQuality.missing)

    # Video modality
    video: Optional[VideoState] = None
    video_quality: SignalQuality = field(default_factory=SignalQuality.missing)

    # Screen modality (屏幕上下文：连续屏幕感知)
    screen: Optional[ScreenState] = None
    screen_quality: SignalQuality = field(default_factory=SignalQuality.missing)

    # System modality
    system: Optional[SystemSignals] = None
    system_quality: SignalQuality = field(default_factory=SignalQuality.missing)

    # Frame metadata
    frame_id: int = 0
    schema_version: int = 1

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def overall_quality(self) -> float:
        """Aggregate quality score [0, 1] across all usable modalities."""
        scores: List[float] = []
        if self.audio_quality.is_usable:
            scores.append(self.audio_quality.confidence)
        if self.video_quality.is_usable:
            scores.append(self.video_quality.confidence)
        if self.screen_quality.is_usable:
            scores.append(self.screen_quality.confidence)
        if self.system_quality.is_usable:
            scores.append(self.system_quality.confidence)
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def active_modalities(self) -> List[str]:
        """List of modality names that are currently usable."""
        mods: List[str] = []
        if self.audio_quality.is_usable:
            mods.append("audio")
        if self.video_quality.is_usable:
            mods.append("video")
        if self.screen_quality.is_usable:
            mods.append("screen")
        if self.system_quality.is_usable:
            mods.append("system")
        return mods

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary (no binary payloads)."""
        result: Dict[str, Any] = {
            "timestamp": self.timestamp,
            "wall_clock": self.wall_clock,
            "frame_id": self.frame_id,
            "schema_version": self.schema_version,
            "overall_quality": self.overall_quality,
            "active_modalities": self.active_modalities,
            "audio_quality": {
                "flag": self.audio_quality.flag.value,
                "freshness_ms": self.audio_quality.freshness_ms,
                "confidence": self.audio_quality.confidence,
                "message": self.audio_quality.message,
            },
            "video_quality": {
                "flag": self.video_quality.flag.value,
                "freshness_ms": self.video_quality.freshness_ms,
                "confidence": self.video_quality.confidence,
                "message": self.video_quality.message,
            },
            "screen_quality": {
                "flag": self.screen_quality.flag.value,
                "freshness_ms": self.screen_quality.freshness_ms,
                "confidence": self.screen_quality.confidence,
                "message": self.screen_quality.message,
            },
            "system_quality": {
                "flag": self.system_quality.flag.value,
                "freshness_ms": self.system_quality.freshness_ms,
                "confidence": self.system_quality.confidence,
                "message": self.system_quality.message,
            },
        }

        if self.audio is not None:
            result["audio"] = {
                "energy": self.audio.energy,
                "speaking_ratio": self.audio.speaking_ratio,
                "pause_density": self.audio.pause_density,
                "noise_level": self.audio.noise_level,
                "audio_freshness_ms": self.audio.audio_freshness_ms,
                "is_speaking": self.audio.is_speaking,
            }

        if self.video is not None:
            result["video"] = {
                "motion_level": self.video.motion_level,
                "scene_change_rate": self.video.scene_change_rate,
                "face_presence": self.video.face_presence,
                "video_freshness_ms": self.video.video_freshness_ms,
            }

        if self.screen is not None:
            # 不含原始 base64（避免日志爆量）；只暴露存在性/变化/结构摘要。
            result["screen"] = {
                "has_image": self.screen.has_image,
                "mime": self.screen.mime,
                "change_score": self.screen.change_score,
                "meta_present": self.screen.meta is not None,
                "screen_freshness_ms": self.screen.screen_freshness_ms,
            }

        if self.system is not None:
            result["system"] = {
                "screen_activity": self.system.screen_activity,
                "cpu_load": self.system.cpu_load,
                "memory_load": self.system.memory_load,
                "active_app": self.system.active_app,
                "extra": self.system.extra,
            }

        return result
