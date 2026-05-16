"""core/multimodal/ingest_runtime.py — Runtime Shell: Native Multimodal Host Perception Bus

**Unified-Subject Architecture — Runtime Shell Ownership**
------------------------------------------------------------
This module is owned by :class:`~core.desktop_presence_runtime.DesktopPresenceRuntime`
(the outer Windows desktop runtime shell).  The runtime shell is responsible for
*continuous host perception* — sensing the ambient Windows environment (audio,
video, system signals) and making that context available to the subject core
(``OpenClawd``) when processing requests.

This is the **continuous host ingress path** — distinct from the
*request-bound* ``multimodal_context`` payload that callers attach to
individual requests and that is fused inside ``OpenClawd`` via
``MultimodalBus.ingest``.

Distinction summary::

    CONTINUOUS HOST PERCEPTION (this module — shell ownership)
        MultimodalIngressBus → PerceptionFrame stream
        → Ambient sensory context of the Windows environment
        → Available across all requests; independent of any single request

    REQUEST-BOUND MULTIMODAL CONTEXT (core/perception/multimodal_bus.py)
        MultimodalBus.ingest(multimodal_context=...) → fusion_summary
        → Per-request image/audio payloads attached by the caller
        → Fused inside OpenClawd for a single request cycle

The singleton :class:`~core.multimodal.ingress_bus.MultimodalIngressBus`
is optionally started on system boot when ``enable_multimodal_ingest``
config flag is ``True``.  Audio and video pipelines are wired in only when
the corresponding optional dependencies are present (``sounddevice``, ``cv2``).

Public API
----------
- :func:`get_ingest_bus` — return the singleton bus (may be ``None`` when
  ingest is disabled or failed to start).
- :func:`start_ingest_bus` — start the singleton bus; idempotent, safe to
  call multiple times.
- :func:`stop_ingest_bus` — stop and discard the singleton bus.

Backward-compatibility guarantee
---------------------------------
When ``enable_multimodal_ingest`` is ``False`` (the default) or when audio /
video dependencies are absent, this module degrades gracefully: no exception is
raised, no pipeline is started, and callers that check :func:`get_ingest_bus`
receive ``None``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger("Galaxy.MultimodalIngestRuntime")

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_ingest_bus: Optional["MultimodalIngressBus"] = None  # type: ignore[name-defined]
_ingest_task: Optional[asyncio.Task] = None  # background task running bus.run()


def get_ingest_bus():
    """Return the running singleton :class:`~core.multimodal.ingress_bus.MultimodalIngressBus`.

    Returns ``None`` when the bus has not been started (i.e., when
    ``enable_multimodal_ingest`` is ``False`` or startup failed).
    """
    return _ingest_bus


def start_ingest_bus(
    *,
    runtime_session_id: Optional[str] = None,
    tick_ms: int = 200,
) -> bool:
    """Start the singleton MultimodalIngressBus if not already running.

    Wires available audio/video pipelines into the bus callbacks.  Missing
    hardware drivers or optional deps are silently skipped.

    Args:
        runtime_session_id: Optional correlation ID for structured logs /
            EventBus observability.
        tick_ms: Tick interval for the ingress bus loop (default 200 ms).

    Returns:
        ``True`` when the bus was (or is already) running after this call.
        ``False`` when startup was skipped due to a missing dependency or error.
    """
    global _ingest_bus, _ingest_task  # noqa: PLW0603

    # Check config flag —— import lazily to avoid circular imports at module load.
    try:
        from core.unified_config import config as _cfg
        if not _cfg.get("enable_multimodal_ingest", False):
            logger.debug(
                "enable_multimodal_ingest=false — skipping ingest bus startup"
            )
            return False
    except Exception as _cfg_err:
        logger.debug("Could not read unified_config: %s — skipping ingest bus", _cfg_err)
        return False

    # Idempotent: bus already running.
    if _ingest_bus is not None and _ingest_bus._running:
        logger.debug("MultimodalIngressBus already running — no-op")
        return True

    # ── Construct bus ─────────────────────────────────────────────────────
    try:
        from core.multimodal.ingress_bus import MultimodalIngressBus
        bus = MultimodalIngressBus(tick_ms=tick_ms)
    except Exception as _bus_err:
        logger.debug("MultimodalIngressBus unavailable: %s", _bus_err)
        return False

    # ── Wire audio pipeline (optional — skip if sounddevice missing) ──────
    audio_available = False
    try:
        from core.multimodal.audio_ingest import AudioIngestPipeline
        audio_pipeline = AudioIngestPipeline()
        audio_pipeline.add_callback(bus.update_audio)
        _schedule_pipeline(audio_pipeline, "audio")
        audio_available = True
    except Exception as _audio_err:
        logger.debug(
            "AudioIngestPipeline unavailable (non-fatal): %s", _audio_err
        )

    # ── Wire video pipeline (optional — skip if cv2 / camera missing) ─────
    video_available = False
    try:
        from core.multimodal.video_ingest import VideoIngestPipeline
        video_pipeline = VideoIngestPipeline()
        video_pipeline.add_callback(bus.update_video)
        _schedule_pipeline(video_pipeline, "video")
        video_available = True
    except Exception as _video_err:
        logger.debug(
            "VideoIngestPipeline unavailable (non-fatal): %s", _video_err
        )

    # ── Start bus tick loop ───────────────────────────────────────────────
    try:
        loop = asyncio.get_running_loop()
        _ingest_task = loop.create_task(bus.run())
    except RuntimeError:
        # No running event loop — bus will be started on next loop iteration.
        _ingest_task = None

    _ingest_bus = bus

    # ── Emit observability event ──────────────────────────────────────────
    _emit_ingest_active(
        runtime_session_id=runtime_session_id,
        audio_available=audio_available,
        video_available=video_available,
    )

    # ── Register sources in the shell-owned PerceptionSourceRegistry ──────
    _register_ingest_sources(
        audio_available=audio_available,
        video_available=video_available,
    )

    logger.info(
        "MultimodalIngressBus started — audio=%s video=%s runtime_session_id=%s",
        audio_available,
        video_available,
        runtime_session_id or "n/a",
    )
    return True


def stop_ingest_bus() -> None:
    """Stop and discard the singleton MultimodalIngressBus.

    Safe to call when the bus is not running.
    """
    global _ingest_bus, _ingest_task  # noqa: PLW0603

    if _ingest_bus is not None:
        try:
            _ingest_bus.stop()
        except Exception:
            pass
        _ingest_bus = None

    if _ingest_task is not None:
        try:
            _ingest_task.cancel()
        except Exception:
            pass
        _ingest_task = None

    logger.debug("MultimodalIngressBus stopped")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _schedule_pipeline(pipeline, name: str) -> None:
    """Schedule a pipeline's ``run()`` coroutine as a background asyncio task."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(pipeline.run())
        logger.debug("Scheduled %s pipeline as background task", name)
    except RuntimeError:
        logger.debug(
            "No running event loop — %s pipeline not scheduled (will start on first loop)",
            name,
        )


def _emit_ingest_active(
    *,
    runtime_session_id: Optional[str],
    audio_available: bool,
    video_available: bool,
) -> None:
    """Emit a ``MULTIMODAL_INGEST_ACTIVE`` event on the StateEventBus."""
    active_modalities = [
        name for name, available in (("audio", audio_available), ("video", video_available))
        if available
    ]
    try:
        from core.state_event_bus import emit as _seb_emit, StateEventType
        _seb_emit(
            StateEventType.MULTIMODAL_INGEST_ACTIVE,
            source="multimodal.ingest_runtime",
            payload={
                "audio_available": audio_available,
                "video_available": video_available,
                "modalities": active_modalities,
            },
            runtime_session_id=runtime_session_id or "",
        )
    except Exception as _seb_err:
        logger.debug("StateEventBus emit failed (non-fatal): %s", _seb_err)


def _register_ingest_sources(
    *,
    audio_available: bool,
    video_available: bool,
) -> None:
    """PR-17: Register microphone and local camera sources in the shell registry.

    Called from :func:`start_ingest_bus` after the bus starts so that the
    ``PerceptionSourceRegistry`` owned by ``DesktopPresenceRuntime`` reflects
    the sources that are actually wired into the ingress pipeline.

    Degrades silently: if the runtime singleton or the registry are unavailable
    (e.g. during unit tests that do not instantiate the runtime shell) this
    helper is a no-op.
    """
    try:
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        runtime = get_desktop_presence_runtime()
        registry = runtime.source_registry

        from core.multimodal.perception_source_registry import (
            PerceptionSourceType,
            SourceModality,
            SourceHealthStatus,
        )

        # -- Microphone source --------------------------------------------
        mic_id = registry.register(
            source_type=PerceptionSourceType.MICROPHONE,
            modality=SourceModality.AUDIO,
            source_id="builtin:microphone",
            display_name="System Microphone",
            transport="local",
            priority=10,
            health=(
                SourceHealthStatus.HEALTHY
                if audio_available
                else SourceHealthStatus.UNAVAILABLE
            ),
        )
        if audio_available:
            registry.mark_active(mic_id)
            registry.set_primary_audio(mic_id)
        else:
            registry.mark_unavailable(mic_id, "sounddevice library unavailable or no microphone hardware")

        # -- Local webcam / camera source ---------------------------------
        cam_id = registry.register(
            source_type=PerceptionSourceType.WEBCAM,
            modality=SourceModality.VIDEO,
            source_id="builtin:webcam",
            display_name="Local Webcam",
            transport="local",
            priority=10,
            health=(
                SourceHealthStatus.HEALTHY
                if video_available
                else SourceHealthStatus.UNAVAILABLE
            ),
        )
        if video_available:
            registry.mark_active(cam_id)
            registry.set_primary_video(cam_id)
        else:
            registry.mark_unavailable(cam_id, "aiortc or OpenCV (cv2) unavailable, or no camera hardware detected")

        logger.debug(
            "_register_ingest_sources: microphone=%s webcam=%s",
            "active" if audio_available else "unavailable",
            "active" if video_available else "unavailable",
        )
    except Exception as _err:
        logger.debug(
            "_register_ingest_sources: skipped (non-fatal): %s", _err
        )
