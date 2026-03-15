#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Multi-Modal Input Schema (PR 1 foundation)
====================================================

Defines canonical Pydantic models for multi-modal inputs (images, audio, and
future sensor / screen signals).  All models are designed for backward
compatibility: every field that is not strictly required has a sensible default
so that existing text-only callers are never affected.

Usage example::

    from core.schemas.multimodal import MultiModalInput, MultiModalContext, MultiModalImage

    ctx = MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/jpeg",
                # ``data`` is a base64-encoded payload — keep payloads small
                # (< 1 MB recommended) to avoid latency and cost overruns.
                data="<base64-encoded JPEG>",
                source="webcam",
            )
        ]
    )
    request = MultiModalInput(message="Describe what you see", context=ctx)

Schema version: 1
Pydantic: v2
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

#: Schema version for forward-compatible negotiation between producers and consumers.
SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Leaf-level media models
# ---------------------------------------------------------------------------

class MultiModalImage(BaseModel):
    """A single image payload attached to a multi-modal request.

    ``data`` must be a **base64-encoded** byte string of the raw image.
    Consumers should enforce a size cap (recommended: ≤ 1 MB per image) to
    avoid excessive latency and API cost.
    """

    mime: str = Field(
        description="MIME type of the image, e.g. 'image/jpeg' or 'image/png'.",
    )
    data: str = Field(
        description=(
            "Base64-encoded image bytes.  Keep payloads small (≤ 1 MB) "
            "to avoid latency and cost overruns when passed to the model router."
        ),
    )
    source: Optional[str] = Field(
        default=None,
        description="Origin of the image, e.g. 'webcam', 'screenshot', 'upload'.",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC capture time of the image (ISO 8601).",
    )


class MultiModalAudio(BaseModel):
    """A single audio payload attached to a multi-modal request.

    ``data`` must be a **base64-encoded** byte string of the raw audio.
    Consumers should enforce a size cap to avoid excessive latency and cost.
    """

    mime: str = Field(
        description="MIME type of the audio, e.g. 'audio/wav' or 'audio/webm'.",
    )
    data: str = Field(
        description=(
            "Base64-encoded audio bytes.  Keep payloads small to avoid "
            "latency and cost overruns when passed to the model router."
        ),
    )
    source: Optional[str] = Field(
        default=None,
        description="Origin of the audio, e.g. 'microphone', 'upload'.",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC capture time of the audio segment (ISO 8601).",
    )


# ---------------------------------------------------------------------------
# Aggregate context model
# ---------------------------------------------------------------------------

class MultiModalContext(BaseModel):
    """Aggregated multi-modal context attached to a single request.

    All collections default to empty so that text-only callers can omit them
    entirely without breaking request parsing.

    Attributes:
        images: List of base64-encoded image payloads (see ``MultiModalImage``).
        audio:  List of base64-encoded audio payloads (see ``MultiModalAudio``).
        screen: Optional freeform dict carrying screen-capture metadata
                (e.g. resolution, window title, captured_at timestamp).
        sensor: Optional freeform dict carrying device-sensor data
                (e.g. gesture, pressure, accelerometer readings).
        metadata: Arbitrary extra key/value pairs for forward-compatible
                  extensions without a schema bump.
    """

    images: List[MultiModalImage] = Field(
        default_factory=list,
        description="Ordered list of image payloads.  Each item is base64-encoded.",
    )
    audio: List[MultiModalAudio] = Field(
        default_factory=list,
        description="Ordered list of audio payloads.  Each item is base64-encoded.",
    )
    screen: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Screen-capture metadata (resolution, window title, timestamp, …).",
    )
    sensor: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Device-sensor snapshot (gesture, pressure, GPS, accelerometer, …).",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extension data for forward-compatible additions.",
    )


# ---------------------------------------------------------------------------
# Top-level input model
# ---------------------------------------------------------------------------

class MultiModalInput(BaseModel):
    """Canonical top-level model for a multi-modal chat / agent request.

    Wraps the free-text ``message`` together with an optional
    ``MultiModalContext`` carrying images, audio, and sensor signals.

    All fields except ``message`` are optional so that existing text-only
    callers continue to work without modification.
    """

    message: str = Field(
        description="The natural-language instruction or query from the user.",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Originating device identifier (used for routing and logging).",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session identifier for maintaining conversation continuity.",
    )
    context: Optional[MultiModalContext] = Field(
        default=None,
        description=(
            "Multi-modal context bundle.  Absent for text-only requests. "
            "When present, ``context.images`` contains base64-encoded image "
            "payloads that are forwarded unchanged to the model router."
        ),
    )
