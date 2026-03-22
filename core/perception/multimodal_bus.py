"""
core/perception/multimodal_bus.py — Request-Bound Multimodal Fusion (Subject Core Layer)

**Unified-Subject Architecture — Subject Core (OpenClawd) Layer**
------------------------------------------------------------------
``MultimodalBus`` handles *request-bound* multimodal payload fusion inside
the subject core (:class:`~core.openclawd.OpenClawd`).  It is distinct from
the *continuous host perception* pipeline owned by the runtime shell.

**Two multimodal input paths — do not confuse**::

    CONTINUOUS HOST PERCEPTION (runtime shell — MultimodalIngressBus)
        DesktopPresenceRuntime._try_start_ingest_bus()
        → MultimodalIngressBus tick loop → PerceptionFrame stream
        → Ambient sensory awareness of the Windows host device
        → Runs independently of individual requests

    REQUEST-BOUND FUSION (subject core — this module)
        OpenClawd.process(multimodal_context=payload)
        → MultimodalBus.ingest(message, multimodal_context)
        → ContextFuser → fusion_summary appended to the LLM prompt
        → Per-request; lifetime scoped to a single process() call

:class:`MultimodalBus` is called from within ``OpenClawd.process()`` during
the **Ingest** stage (Stage 1 of the four-stage liminal flow).  It:

1. Accepts a natural-language ``message``, an optional
   :class:`~core.schemas.multimodal.MultiModalContext` bundle, and optional
   device metadata.
2. Delegates fusion to :class:`~core.perception.context_fuser.ContextFuser`
   to build a lightweight fused context dict (base64 payloads are *never*
   included in the fused output).
3. Emits :data:`~core.perception.event_types.PERCEPTION_INGESTED` (before
   fusion) and :data:`~core.perception.event_types.PERCEPTION_FUSED` (after
   fusion) on the Galaxy :class:`~integration.event_bus.EventBus`.

Text-only requests are fully supported and produce an empty ``fusion_summary``
so that the LLM prompt is not modified.

Usage::

    from core.perception.multimodal_bus import MultimodalBus

    bus = MultimodalBus()
    fused = bus.ingest(
        message="What is this?",
        multimodal_context=req.multimodal_context,
        device_metadata={"device_id": device_id, "session_id": session_id},
    )
    # fused["fusion_summary"] is a compact string ready to append to the prompt
    # fused["images"] / fused["audio"] hold lightweight metadata (no base64)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.perception.context_fuser import ContextFuser
from core.perception.event_types import PERCEPTION_FUSED, PERCEPTION_INGESTED
from integration.event_bus import UIGalaxyEvent, event_bus as _galaxy_event_bus

logger = logging.getLogger(__name__)


class MultimodalBus:
    """Unified multimodal input bus for the Galaxy perception pipeline.

    Each call to :meth:`ingest` is stateless — the bus holds no mutable
    state, making it safe to instantiate per-request or as a singleton.
    """

    def __init__(self) -> None:
        self._fuser = ContextFuser()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(
        self,
        message: str,
        multimodal_context: Optional[Any] = None,
        device_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Ingest a request and return a fused context dict.

        Args:
            message:             The user's natural-language message.
            multimodal_context:  A :class:`~core.schemas.multimodal.MultiModalContext`
                                 instance (or any object with ``.images`` /
                                 ``.audio`` / ``.screen`` / ``.sensor``
                                 attributes).  Pass ``None`` for text-only
                                 requests.
            device_metadata:     Arbitrary dict with device/session info
                                 (e.g. ``{"device_id": …, "session_id": …}``).

        Returns:
            A dict with keys:
            * ``text``            — original message
            * ``images``          — lightweight image metadata list (no base64)
            * ``audio``           — lightweight audio metadata list (no base64)
            * ``screen``          — screen metadata dict or ``{}``
            * ``device``          — device metadata dict or ``{}``
            * ``fusion_summary``  — compact description for the LLM prompt
        """
        # --- emit PERCEPTION_INGESTED ----------------------------------------
        _img_count = 0
        _aud_count = 0
        if multimodal_context is not None:
            _img_count = len(getattr(multimodal_context, "images", None) or [])
            _aud_count = len(getattr(multimodal_context, "audio", None) or [])

        self._emit(
            PERCEPTION_INGESTED,
            {
                "message_len": len(message),
                "image_count": _img_count,
                "audio_count": _aud_count,
                "has_screen": multimodal_context is not None
                and getattr(multimodal_context, "screen", None) is not None,
                "device_id": (device_metadata or {}).get("device_id"),
            },
        )

        # --- decompose multimodal_context ------------------------------------
        images = self._extract_images(multimodal_context)
        audio = self._extract_audio(multimodal_context)
        screen = self._extract_screen(multimodal_context)

        # --- fuse ------------------------------------------------------------
        fused = self._fuser.fuse(
            text=message,
            images=images,
            audio=audio,
            screen=screen,
            device=device_metadata or {},
        )

        # --- emit PERCEPTION_FUSED -------------------------------------------
        # Log the summary but never log base64 payloads.
        self._emit(
            PERCEPTION_FUSED,
            {
                "image_count": len(fused["images"]),
                "audio_count": len(fused["audio"]),
                "has_screen": bool(fused["screen"]),
                "has_device": bool(fused["device"]),
                "fusion_summary": fused["fusion_summary"],
            },
        )

        logger.debug(
            "MultimodalBus.ingest: images=%d audio=%d summary=%r",
            len(fused["images"]),
            len(fused["audio"]),
            fused["fusion_summary"],
        )

        return fused

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_images(ctx: Optional[Any]) -> list:
        """Extract image metadata from a MultiModalContext, stripping base64."""
        if ctx is None:
            return []
        raw = getattr(ctx, "images", None) or []
        result = []
        for img in raw:
            if hasattr(img, "model_dump"):
                entry = img.model_dump()
            elif isinstance(img, dict):
                entry = dict(img)
            else:
                continue
            # Strip base64 payload — keep only metadata
            entry.pop("data", None)
            result.append(entry)
        return result

    @staticmethod
    def _extract_audio(ctx: Optional[Any]) -> list:
        """Extract audio metadata from a MultiModalContext, stripping base64."""
        if ctx is None:
            return []
        raw = getattr(ctx, "audio", None) or []
        result = []
        for aud in raw:
            if hasattr(aud, "model_dump"):
                entry = aud.model_dump()
            elif isinstance(aud, dict):
                entry = dict(aud)
            else:
                continue
            entry.pop("data", None)
            result.append(entry)
        return result

    @staticmethod
    def _extract_screen(ctx: Optional[Any]) -> Optional[Dict[str, Any]]:
        """Extract screen metadata from a MultiModalContext."""
        if ctx is None:
            return None
        screen = getattr(ctx, "screen", None)
        if isinstance(screen, dict):
            return screen
        return None

    @staticmethod
    def _emit(event_type: Any, data: Dict[str, Any]) -> None:
        """Publish an event on the Galaxy EventBus (best-effort; never raises)."""
        try:
            event = UIGalaxyEvent(
                event_type=event_type,
                source="perception_bus",
                data=data,
            )
            _galaxy_event_bus.publish(event)
        except Exception as exc:  # broad catch: EventBus errors must never crash the perception pipeline
            logger.debug("MultimodalBus: EventBus emit failed (%s): %s", event_type, exc)
