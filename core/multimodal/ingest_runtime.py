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

from typing import Callable  # auto: missing import


import asyncio
import logging
from typing import Optional

logger = logging.getLogger("Galaxy.MultimodalIngestRuntime")

# ---------------------------------------------------------------------------
# Canonical default path declaration
# ---------------------------------------------------------------------------

MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH: str = (
    "CANONICAL_DEFAULT_PATH::MULTIMODAL_INGEST_V1: "
    "Continuous host perception (MultimodalIngressBus) is the canonical default "
    "runtime path for ambient sensory input.  enable_multimodal_ingest defaults "
    "to True in the canonical configuration; the SAFE_DEFAULT (disabled) posture "
    "is an explicit opt-out preserved for constrained or text-only deployments, "
    "not the canonical default.  Any dispatch path that bypasses the ingest bus "
    "when it is running is classified as a compat/fallback path, not canonical."
)
"""Sentinel declaring :func:`start_ingest_bus` as the canonical default runtime path.

Prior to this PR the ambient continuous ingest path was default-off (SAFE_DEFAULT
profile, enable_multimodal_ingest=False).  This sentinel records the promotion:
continuous host perception is now the canonical default runtime path.
"""

# ---------------------------------------------------------------------------
# Module-level singleton state
# ---------------------------------------------------------------------------

_ingest_bus: Optional["MultimodalIngressBus"] = None  # type: ignore[name-defined]
_ingest_task: Optional[asyncio.Task] = None  # background task running bus.run()
_pipeline_tasks: list = []  # background tasks running pipeline.run()


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
    goal_submitter: "Optional[Callable[[str], None]]" = None,
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
    # 默认 True：与 MULTIMODAL_INGEST_CANONICAL_DEFAULT_PATH 一致——连续宿主感知是
    # 规范默认路径；显式置 false 才走 SAFE_DEFAULT（text-only / 受限部署）opt-out。
    try:
        from core.unified_config import config as _cfg
        if not _cfg.get("enable_multimodal_ingest", True):
            logger.debug(
                "enable_multimodal_ingest=false — skipping ingest bus startup"
            )
            return False
    except Exception as _cfg_err:
        # 读不到配置时不再静默放弃：连续感知是规范默认，缺配置按默认开（仍会优雅降级）。
        logger.debug("unified_config unavailable (%s) — proceeding with canonical default ON", _cfg_err)

    # Idempotent: a bus instance already exists. (Its run() task may not
    # have started ticking yet — checking ``_running`` here would race and
    # respawn a new bus/task set on every call.)
    if _ingest_bus is not None:
        logger.debug("MultimodalIngressBus already started — no-op")
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

    # ── Wire desktop perception bridge（覆盖层三路 → 主动感知 bus）─────────────
    # 这是【屏幕】进入连续感知的唯一通路，也让摄像头/麦克风按覆盖层实际采集如实反映到
    # bus（避免与本地 cv2/sounddevice 抢设备）。store 为空时各模态保持 missing → 优雅降级。
    desktop_bridge = _start_desktop_perception_bridge(bus, tick_ms)

    # PR-ACTIVE-PERCEPTION: wire autonomous goal submitter (shell-owned)
    if goal_submitter is not None:
        bus._goal_submitter = goal_submitter

    # ── Start bus tick loop ───────────────────────────────────────────────
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running event loop — bus will be started on next loop iteration.
        _ingest_task = None
    else:
        coro = bus.run()
        try:
            _ingest_task = loop.create_task(coro)
        except RuntimeError:
            # Loop is shutting down — close the coroutine to avoid a
            # "never awaited" leak.
            coro.close()
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
        "MultimodalIngressBus started — audio=%s video=%s desktop_bridge=%s(screen+cam+mic) "
        "goal_submitter=%s runtime_session_id=%s",
        audio_available,
        video_available,
        desktop_bridge,
        goal_submitter is not None,
        runtime_session_id or "n/a",
    )
    return True


def stop_ingest_bus() -> list:
    """Stop and discard the singleton MultimodalIngressBus.

    Safe to call when the bus is not running.

    Returns:
        The list of cancelled background tasks. Async callers should await
        them (e.g. ``asyncio.gather(*tasks, return_exceptions=True)``) so the
        cancellations complete before the event loop closes.
    """
    global _ingest_bus, _ingest_task  # noqa: PLW0603

    cancelled: list = []

    if _ingest_bus is not None:
        try:
            _ingest_bus.stop()
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        _ingest_bus = None

    if _ingest_task is not None:
        try:
            _ingest_task.cancel()
            cancelled.append(_ingest_task)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        _ingest_task = None

    for task in _pipeline_tasks:
        try:
            task.cancel()
            cancelled.append(task)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
    _pipeline_tasks.clear()

    logger.debug("MultimodalIngressBus stopped")
    return cancelled


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _desktop_perception_bridge_loop(bus, period_s: float) -> None:
    """周期把【桌面覆盖层】采集的屏幕/摄像头/麦克风帧从 DesktopPerceptionStore
    推进 MultimodalIngressBus —— 让主动持续感知 bus 真正“看到屏幕、看到摄像头、听到麦克风”。

    - 屏幕：唯一进入连续感知的通路；带便宜的帧间变化分数（按 base64 长度变化估算，免解码）。
    - 摄像头/麦克风：以“在场”特征态如实反映（具体特征仍由本地 cv2/sounddevice 管道补充）。
    store 为空（未启用覆盖层感知）时各模态保持 missing，bus 自然降级，绝不抛错。
    """
    import asyncio as _asyncio
    try:
        from core.perception.desktop_perception_store import get_desktop_perception_store
        from core.multimodal.audio_features import AudioState
        from core.multimodal.video_features import VideoState
        from core.multimodal.perception_frame import ScreenState
        from core.multimodal.signal_quality import SignalQuality
    except Exception as exc:  # noqa: BLE001
        logger.debug("desktop perception bridge deps unavailable: %s", exc)
        return
    store = get_desktop_perception_store()
    prev_screen_len: Optional[int] = None
    while True:
        try:
            snap = store.snapshot_media()
            scr = snap.get("screen_b64")
            if scr:
                cur = len(scr)
                if prev_screen_len is None:
                    change = 1.0
                else:
                    change = min(1.0, abs(cur - prev_screen_len) / max(1, prev_screen_len))
                prev_screen_len = cur
                bus.update_screen(
                    ScreenState(
                        image_b64=scr,
                        mime=snap.get("screen_mime", "image/jpeg"),
                        change_score=change,
                        meta=snap.get("screen_meta"),
                        has_image=True,
                    ),
                    SignalQuality.ok(),
                )
            if snap.get("camera_b64"):
                bus.update_video(VideoState(), SignalQuality.ok())
            if snap.get("audio_b64"):
                bus.update_audio(AudioState(), SignalQuality.ok())
        except Exception as exc:  # noqa: BLE001
            logger.debug("desktop perception bridge tick error: %s", exc)
        await _asyncio.sleep(period_s)


def _start_desktop_perception_bridge(bus, tick_ms: int) -> bool:
    """把桌面感知桥接循环调度为后台任务。无运行中的事件循环时跳过（返回 False）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("No running event loop — desktop perception bridge not scheduled")
        return False
    period_s = max(0.5, tick_ms / 1000.0)
    coro = _desktop_perception_bridge_loop(bus, period_s)
    try:
        _pipeline_tasks.append(loop.create_task(coro))
        logger.debug("Scheduled desktop perception bridge (period=%.2fs)", period_s)
        return True
    except RuntimeError:
        coro.close()
        return False


def _schedule_pipeline(pipeline, name: str) -> None:
    """Schedule a pipeline's ``run()`` coroutine as a background asyncio task."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug(
            "No running event loop — %s pipeline not scheduled (will start on first loop)",
            name,
        )
        return
    coro = pipeline.run()
    try:
        _pipeline_tasks.append(loop.create_task(coro))
        logger.debug("Scheduled %s pipeline as background task", name)
    except RuntimeError:
        # Loop is shutting down — close the coroutine to avoid a leak.
        coro.close()
        logger.debug("Event loop closing — %s pipeline not scheduled", name)


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
