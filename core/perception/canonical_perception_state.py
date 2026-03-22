"""core/perception/canonical_perception_state.py — Canonical Perception State

**Unified-Subject Architecture — Shell/Core Perception Handoff**
----------------------------------------------------------------
``CanonicalPerceptionState`` is the single canonical object that represents
the perception truth consumed by :class:`~core.openclawd.OpenClawd`.

It unifies two distinct perception paths — preserving their conceptual
distinction — into one structured, serializable, diagnosable object:

.. code-block:: text

    CONTINUOUS HOST PERCEPTION (runtime shell — DesktopPresenceRuntime)
        MultimodalIngressBus → PerceptionFrame
        Ambient, ongoing sensory awareness of the Windows host device
        Owned by the runtime shell; independent of any single request

    REQUEST-BOUND MULTIMODAL CONTEXT (subject core — OpenClawd)
        multimodal_context parameter → MultimodalBus.ingest()
        Per-request images / audio / screen / sensor payload bundle
        Owned by OpenClawd; lifetime scoped to one process() call

    CanonicalPerceptionState  ← unified at the handoff/consumption boundary
        Assembled inside OpenClawd.process() using both sources
        OpenClawd uses this as its primary perception input contract
        Serializable, diagnosable, loggable

Usage::

    from core.perception.canonical_perception_state import (
        CanonicalPerceptionState,
        build_canonical_perception_state,
    )

    state = build_canonical_perception_state(
        runtime_session_id=runtime_session_id,
        trace_id=trace_id,
        fused_context=mm_context_dict,       # from MultimodalBus.ingest()
        multimodal_context=multimodal_context,  # raw request payload
        continuous_frame=frame,              # PerceptionFrame from ingress bus
    )
    # state.to_dict() is safe to log and include in response metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalPerceptionState:
    """Unified canonical perception state consumed by OpenClawd as its primary
    perception input contract.

    Unifies continuous host perception (runtime shell owned) and request-bound
    multimodal context (OpenClawd owned) without erasing their conceptual
    distinction.  The two-path model is preserved through explicit flags:
    ``has_continuous_perception`` and ``has_request_multimodal``.

    Fields
    ------
    runtime_session_id
        Correlation ID from :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
    trace_id
        Trace ID for the current request (equals ``runtime_session_id`` when
        routed through the runtime shell).
    has_continuous_perception
        ``True`` when a live :class:`~core.multimodal.perception_frame.PerceptionFrame`
        from the runtime shell ingress bus was available for this request.
    continuous_frame_id
        Frame ID of the continuous perception snapshot, when available.
    continuous_wall_clock
        Wall-clock time of the continuous perception snapshot.
    continuous_overall_quality
        Aggregate quality score [0, 1] of the continuous perception snapshot.
    has_request_multimodal
        ``True`` when the request carried a non-empty multimodal context
        (images, audio, screen, or sensor data).
    active_modalities
        Union of modality names that are active across both perception paths.
        Possible values: ``"audio"``, ``"video"``, ``"system"``,
        ``"image"``, ``"screen"``, ``"sensor"``.
    audio_summary
        Lightweight audio feature summary (no base64).  May originate from the
        continuous ingress frame or from the request-bound context.
    video_summary
        Lightweight video feature summary (no base64).
    screen_summary
        Screen capture metadata, if present in the request-bound context.
    sensor_summary
        Device sensor snapshot, if present in the request-bound context.
    system_summary
        System-level feature summary from the continuous perception frame.
    quality_summary
        Quality descriptors for each modality dimension.
    source_summary
        High-level summary of which perception sources contributed.
    fusion_summary
        Compact derived string for LLM prompt augmentation.  A useful derived
        field; not the canonical truth (see ``has_request_multimodal``).
    requires_native_multimodal
        ``True`` when images or audio are present in the request-bound context,
        indicating that a native multimodal model should be preferred/required
        for downstream routing.
    degradation_reasons
        List of human-readable strings explaining why perception is degraded or
        limited.  Empty when all sources are fully available.
    perception_summary
        Concise single-line description of the current perception state for
        downstream control logic and diagnostics.
    """

    # Runtime/session correlation IDs
    runtime_session_id: Optional[str] = None
    trace_id: Optional[str] = None

    # Continuous host perception (runtime shell owned)
    has_continuous_perception: bool = False
    continuous_frame_id: Optional[int] = None
    continuous_wall_clock: Optional[float] = None
    continuous_overall_quality: Optional[float] = None

    # Request-bound multimodal context (OpenClawd owned)
    has_request_multimodal: bool = False

    # Active modalities (union of continuous + request-bound)
    active_modalities: List[str] = field(default_factory=list)

    # Feature summaries (lightweight; no base64 payloads)
    audio_summary: Optional[Dict[str, Any]] = None
    video_summary: Optional[Dict[str, Any]] = None
    screen_summary: Optional[Dict[str, Any]] = None
    sensor_summary: Optional[Dict[str, Any]] = None
    system_summary: Optional[Dict[str, Any]] = None

    # Quality and source descriptors
    quality_summary: Optional[Dict[str, Any]] = None
    source_summary: Optional[Dict[str, Any]] = None

    # Fusion summary (derived, not the canonical truth)
    fusion_summary: Optional[str] = None

    # Native multimodal routing hint
    requires_native_multimodal: bool = False

    # Degradation context
    degradation_reasons: List[str] = field(default_factory=list)

    # Concise perception summary for downstream control/diagnostics
    perception_summary: str = ""

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a plain dict suitable for logging and response metadata.

        No binary payloads are included.  Safe to emit as JSON.
        """
        return {
            "runtime_session_id": self.runtime_session_id,
            "trace_id": self.trace_id,
            "has_continuous_perception": self.has_continuous_perception,
            "continuous_frame_id": self.continuous_frame_id,
            "continuous_wall_clock": self.continuous_wall_clock,
            "continuous_overall_quality": self.continuous_overall_quality,
            "has_request_multimodal": self.has_request_multimodal,
            "active_modalities": list(self.active_modalities),
            "audio_summary": self.audio_summary,
            "video_summary": self.video_summary,
            "screen_summary": self.screen_summary,
            "sensor_summary": self.sensor_summary,
            "system_summary": self.system_summary,
            "quality_summary": self.quality_summary,
            "source_summary": self.source_summary,
            "fusion_summary": self.fusion_summary,
            "requires_native_multimodal": self.requires_native_multimodal,
            "degradation_reasons": list(self.degradation_reasons),
            "perception_summary": self.perception_summary,
        }


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_canonical_perception_state(
    *,
    runtime_session_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    fused_context: Optional[Dict[str, Any]] = None,
    multimodal_context: Optional[Any] = None,
    continuous_frame: Optional[Any] = None,
) -> CanonicalPerceptionState:
    """Build a :class:`CanonicalPerceptionState` from all available perception inputs.

    Combines the continuous host perception snapshot from the runtime shell
    (``continuous_frame``) with the request-bound multimodal context
    (``multimodal_context`` and its fused derivative ``fused_context``) into a
    single canonical object.

    The two-path model is preserved: ``has_continuous_perception`` and
    ``has_request_multimodal`` remain distinct flags.  The resulting object is
    the primary perception contract that OpenClawd uses for downstream control
    logic and diagnostics.

    Args:
        runtime_session_id: Correlation ID from
            :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`.
        trace_id:           Trace ID for the current request.
        fused_context:      Output of ``MultimodalBus.ingest()`` — request-bound
                            fusion dict with ``images``, ``audio``, ``screen``,
                            ``device``, and ``fusion_summary`` keys.
        multimodal_context: Raw :class:`~core.schemas.multimodal.MultiModalContext`
                            from the request (or ``None`` for text-only).
        continuous_frame:   :class:`~core.multimodal.perception_frame.PerceptionFrame`
                            from the runtime shell ingress bus (or ``None``
                            when the bus is unavailable).

    Returns:
        A fully populated :class:`CanonicalPerceptionState`.  Always succeeds;
        text-only requests receive a valid state with
        ``has_continuous_perception=False``, ``has_request_multimodal=False``,
        and a ``"text-only"`` perception summary.
    """
    state = CanonicalPerceptionState(
        runtime_session_id=runtime_session_id,
        trace_id=trace_id,
    )

    degradation_reasons: List[str] = []
    active_modalities: List[str] = []

    # ------------------------------------------------------------------
    # Path 1: Continuous host perception (runtime shell owned)
    # ------------------------------------------------------------------
    if continuous_frame is not None:
        state.has_continuous_perception = True
        state.continuous_frame_id = getattr(continuous_frame, "frame_id", None)
        state.continuous_wall_clock = getattr(continuous_frame, "wall_clock", None)
        state.continuous_overall_quality = getattr(continuous_frame, "overall_quality", None)

        frame_modalities: List[str] = list(
            getattr(continuous_frame, "active_modalities", None) or []
        )
        active_modalities.extend(frame_modalities)

        # Audio features from continuous perception
        audio_state = getattr(continuous_frame, "audio", None)
        if audio_state is not None:
            state.audio_summary = {
                "source": "continuous",
                "energy": getattr(audio_state, "energy", None),
                "speaking_ratio": getattr(audio_state, "speaking_ratio", None),
                "is_speaking": getattr(audio_state, "is_speaking", None),
                "noise_level": getattr(audio_state, "noise_level", None),
            }

        # Video features from continuous perception
        video_state = getattr(continuous_frame, "video", None)
        if video_state is not None:
            state.video_summary = {
                "source": "continuous",
                "motion_level": getattr(video_state, "motion_level", None),
                "face_presence": getattr(video_state, "face_presence", None),
            }

        # System features from continuous perception
        system_state = getattr(continuous_frame, "system", None)
        if system_state is not None:
            state.system_summary = {
                "source": "continuous",
                "screen_activity": getattr(system_state, "screen_activity", None),
                "cpu_load": getattr(system_state, "cpu_load", None),
                "memory_load": getattr(system_state, "memory_load", None),
                "active_app": getattr(system_state, "active_app", None),
            }

        # Quality descriptors from continuous frame
        aq = getattr(continuous_frame, "audio_quality", None)
        vq = getattr(continuous_frame, "video_quality", None)
        sq = getattr(continuous_frame, "system_quality", None)
        state.quality_summary = {
            "overall": getattr(continuous_frame, "overall_quality", 0.0),
            "audio_flag": (
                getattr(getattr(aq, "flag", None), "value", None) if aq else None
            ),
            "video_flag": (
                getattr(getattr(vq, "flag", None), "value", None) if vq else None
            ),
            "system_flag": (
                getattr(getattr(sq, "flag", None), "value", None) if sq else None
            ),
        }
    else:
        degradation_reasons.append("continuous_perception_unavailable")

    # ------------------------------------------------------------------
    # Path 2: Request-bound multimodal context (OpenClawd owned)
    # ------------------------------------------------------------------
    _img_count = 0
    _aud_count = 0
    _has_screen = False
    _has_sensor = False

    if multimodal_context is not None:
        _img_count = len(getattr(multimodal_context, "images", None) or [])
        _aud_count = len(getattr(multimodal_context, "audio", None) or [])
        _has_screen = getattr(multimodal_context, "screen", None) is not None
        _has_sensor = getattr(multimodal_context, "sensor", None) is not None
        if _img_count > 0 or _aud_count > 0 or _has_screen or _has_sensor:
            state.has_request_multimodal = True

    # Fused context enrichment (from MultimodalBus.ingest output)
    if fused_context is not None:
        fusion_str = fused_context.get("fusion_summary") or ""
        if fusion_str:
            state.fusion_summary = fusion_str

        fused_images: List[Dict[str, Any]] = list(fused_context.get("images") or [])
        fused_audio: List[Dict[str, Any]] = list(fused_context.get("audio") or [])
        fused_screen: Dict[str, Any] = fused_context.get("screen") or {}

        if fused_images:
            if "image" not in active_modalities:
                active_modalities.append("image")
            img_sources = [img.get("source") for img in fused_images if img.get("source")]
            # Only populate video_summary from request path when continuous is absent
            if state.video_summary is None:
                state.video_summary = {
                    "source": "request",
                    "image_count": len(fused_images),
                    "sources": img_sources,
                }
            state.has_request_multimodal = True

        if fused_audio:
            if "audio" not in active_modalities:
                active_modalities.append("audio")
            # Only populate audio_summary from request path when continuous is absent
            if state.audio_summary is None:
                aud_sources = [a.get("source") for a in fused_audio if a.get("source")]
                state.audio_summary = {
                    "source": "request",
                    "count": len(fused_audio),
                    "sources": aud_sources,
                }
            state.has_request_multimodal = True

        if fused_screen:
            if "screen" not in active_modalities:
                active_modalities.append("screen")
            state.screen_summary = fused_screen
            state.has_request_multimodal = True

        if _has_sensor:
            if "sensor" not in active_modalities:
                active_modalities.append("sensor")
            sensor_raw = getattr(multimodal_context, "sensor", None)
            if isinstance(sensor_raw, dict):
                state.sensor_summary = sensor_raw
            state.has_request_multimodal = True

    # ------------------------------------------------------------------
    # Native multimodal routing hint
    # ------------------------------------------------------------------
    _has_request_images = bool(fused_context and (fused_context.get("images") or []))
    _has_request_audio = bool(fused_context and (fused_context.get("audio") or []))
    state.requires_native_multimodal = _has_request_images or _has_request_audio

    # ------------------------------------------------------------------
    # Source summary
    # ------------------------------------------------------------------
    state.source_summary = {
        "has_ingress_bus": state.has_continuous_perception,
        "has_request_context": state.has_request_multimodal,
        "request_image_count": _img_count,
        "request_audio_count": _aud_count,
        "request_has_screen": _has_screen,
        "request_has_sensor": _has_sensor,
    }

    # ------------------------------------------------------------------
    # Active modalities (deduplicated, preserving insertion order)
    # ------------------------------------------------------------------
    seen: set = set()
    deduped: List[str] = []
    for mod in active_modalities:
        if mod not in seen:
            seen.add(mod)
            deduped.append(mod)
    state.active_modalities = deduped

    # ------------------------------------------------------------------
    # Degradation reasons
    # ------------------------------------------------------------------
    if not state.has_continuous_perception and not state.has_request_multimodal:
        degradation_reasons.append("text_only")
    state.degradation_reasons = degradation_reasons

    # ------------------------------------------------------------------
    # Perception summary (concise, for downstream control/diagnostics)
    # ------------------------------------------------------------------
    parts: List[str] = []
    if state.has_continuous_perception:
        q = state.continuous_overall_quality
        parts.append(
            f"continuous(q={q:.2f})" if q is not None else "continuous"
        )
    if state.has_request_multimodal:
        parts.append(
            f"request({state.fusion_summary})" if state.fusion_summary else "request(multimodal)"
        )
    if not parts:
        parts.append("text-only")
    non_trivial = [d for d in degradation_reasons if d != "text_only"]
    if non_trivial:
        parts.append(f"degraded:{','.join(non_trivial)}")
    state.perception_summary = " | ".join(parts)

    return state
