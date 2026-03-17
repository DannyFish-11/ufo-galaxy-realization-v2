"""
Galaxy — Multimodal Context Fuser (PR 1)
=========================================

:class:`ContextFuser` combines decomposed modality inputs (text, images, audio,
screen metadata, device metadata) into a single **fused context dict** that can
be forwarded through the Galaxy pipeline.

Design constraints
------------------
* **No base64 payloads in the fused dict** — image/audio entries in the output
  contain only lightweight metadata (mime type, source, timestamp, size hint).
  Base64 blobs are stripped to prevent accidental logging or serialisation of
  large payloads.
* **Deterministic** — given the same inputs the output is always the same
  (including ``fusion_summary``), which makes unit-testing straightforward.
* **Text-only safe** — when ``images`` and ``audio`` are empty and ``screen``/
  ``device`` are ``None``, ``fusion_summary`` is an empty string so that no
  extra text is appended to the LLM prompt.

Usage::

    from core.perception.context_fuser import ContextFuser

    fuser = ContextFuser()
    result = fuser.fuse(
        text="What is this?",
        images=[{"mime": "image/jpeg", "source": "webcam"}],
        audio=[],
        screen=None,
        device={"device_id": "dev-1"},
    )
    # result["fusion_summary"] == "[Multimodal context: 1 image(s) [webcam], device=dev-1]"
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

#: Hard limits to protect the pipeline from oversized payloads.
MAX_IMAGES: int = 20
MAX_AUDIO: int = 10


class ContextFuser:
    """Fuse multimodal inputs into a single lightweight context dict.

    All heavy base64 payloads are **stripped** from the output.  Only
    metadata (mime, source, timestamp) is preserved so that downstream
    components can log and route context safely.
    """

    def fuse(
        self,
        text: str,
        images: Optional[List[Dict[str, Any]]] = None,
        audio: Optional[List[Dict[str, Any]]] = None,
        screen: Optional[Dict[str, Any]] = None,
        device: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build and return the fused context dict.

        Args:
            text:    The original natural-language message.
            images:  List of image dicts, each potentially containing a
                     ``data`` (base64) field that will be **stripped**.
            audio:   List of audio dicts, each potentially containing a
                     ``data`` (base64) field that will be **stripped**.
            screen:  Optional screen-capture metadata dict.
            device:  Optional device metadata dict (e.g. ``{"device_id": …}``).

        Returns:
            A dict with keys:
            * ``text``            — original message (unchanged)
            * ``images``          — lightweight image metadata (no base64)
            * ``audio``           — lightweight audio metadata (no base64)
            * ``screen``          — screen metadata or ``{}``
            * ``device``          — device metadata or ``{}``
            * ``fusion_summary``  — compact human-readable description for the
                                    LLM prompt; empty string for text-only requests
        """
        images = images or []
        audio = audio or []

        # Enforce size limits
        if len(images) > MAX_IMAGES:
            logger.warning(
                "ContextFuser: %d images exceed MAX_IMAGES=%d; truncating",
                len(images),
                MAX_IMAGES,
            )
            images = images[:MAX_IMAGES]
        if len(audio) > MAX_AUDIO:
            logger.warning(
                "ContextFuser: %d audio clips exceed MAX_AUDIO=%d; truncating",
                len(audio),
                MAX_AUDIO,
            )
            audio = audio[:MAX_AUDIO]

        # Strip base64 payloads — keep only lightweight metadata
        safe_images = [self._strip_payload(img) for img in images]
        safe_audio = [self._strip_payload(aud) for aud in audio]

        summary = self._build_summary(safe_images, safe_audio, screen, device)

        return {
            "text": text,
            "images": safe_images,
            "audio": safe_audio,
            "screen": screen or {},
            "device": device or {},
            "fusion_summary": summary,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of *entry* without the ``data`` base64 field."""
        return {k: v for k, v in entry.items() if k != "data"}

    @staticmethod
    def _build_summary(
        images: List[Dict[str, Any]],
        audio: List[Dict[str, Any]],
        screen: Optional[Dict[str, Any]],
        device: Optional[Dict[str, Any]],
    ) -> str:
        """Build a compact textual summary suitable for appending to an LLM prompt.

        Returns an empty string when no media is attached (text-only request).
        """
        parts: List[str] = []

        if images:
            sources = sorted({img.get("source") or "unknown" for img in images})
            parts.append(f"{len(images)} image(s) [{', '.join(sources)}]")

        if audio:
            sources = sorted({aud.get("source") or "unknown" for aud in audio})
            parts.append(f"{len(audio)} audio clip(s) [{', '.join(sources)}]")

        if screen:
            title = screen.get("window_title") or screen.get("title") or "screen"
            parts.append(f"screen context [{title}]")

        if device:
            dev_id = device.get("device_id") or "unknown"
            parts.append(f"device={dev_id}")

        if not parts:
            return ""
        return "[Multimodal context: " + ", ".join(parts) + "]"
