"""tests/integration/stubs/multimodal_perception_stub.py
=========================================================
Minimal multimodal perception stub for canonical-path CI proof.

Purpose
-------
Provides deterministic, no-network fixtures for exercising the request-bound
multimodal context path through the real canonical chain:

    MultiModalContext (images/audio)
        → DesktopPresenceRuntime.handle_request(multimodal_context=...)
            → OpenClawd.process(multimodal_context=...)
                → MultimodalBus.ingest()
                    → CanonicalPerceptionState
                        → _select_multimodal_route()
                            → multimodal_route_decision in response metadata

This stub is NOT a disconnected mock.  The full DPR → OpenClawd chain runs for
real; only the LLM leaf is replaced (via LLMContractStub from the NL proof).
The multimodal_context itself is a real ``MultiModalContext`` Pydantic object
with a minimal (1×1 pixel) encoded image payload.

Usage::

    from tests.integration.stubs.multimodal_perception_stub import (
        make_image_context,
        make_android_vision_context,
        STUB_IMAGE_SOURCE,
        STUB_IMAGE_B64,
    )

    ctx = make_image_context()  # MultiModalContext with one stub PNG image
    android_ctx = make_android_vision_context(device_id="test-android-001")
"""

from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Deterministic test fixtures
# ---------------------------------------------------------------------------

#: Deterministic label for the stub perception source.
STUB_IMAGE_SOURCE: str = "multimodal_perception_stub"

#: Deterministic label for Android stub device.
STUB_ANDROID_SOURCE: str = "android_screen:test-android-001"

#: Minimal 1×1 transparent PNG, base64-encoded.
#: Using a real (but tiny) PNG so multimodal schema validation passes.
STUB_IMAGE_B64: str = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

#: Minimal WAV header bytes (44-byte minimal WAV), base64-encoded.
#: Used to inject audio modality without requiring audio hardware.
STUB_AUDIO_B64: str = (
    "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
)


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def make_image_context(source: Optional[str] = None):
    """Return a minimal :class:`~core.schemas.multimodal.MultiModalContext`
    with one stub PNG image.

    Parameters
    ----------
    source:
        Override the image source tag.  Defaults to ``STUB_IMAGE_SOURCE``.

    Returns
    -------
    MultiModalContext
    """
    from core.schemas.multimodal import MultiModalContext, MultiModalImage

    return MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/png",
                data=STUB_IMAGE_B64,
                source=source or STUB_IMAGE_SOURCE,
            )
        ]
    )


def make_android_vision_context(device_id: str = "test-android-001"):
    """Return a :class:`~core.schemas.multimodal.MultiModalContext` that
    mirrors the payload built by the Android vision handler
    (``galaxy_gateway.android.handlers.vision._process_via_runtime_shell``).

    The ``source`` tag is set to ``"android_screen:{device_id}"`` to match
    the real handler's convention, enabling tests to assert that the canonical
    path carries the Android origin marker end-to-end.

    Parameters
    ----------
    device_id:
        Android device identifier to embed in the source tag.

    Returns
    -------
    MultiModalContext
    """
    from core.schemas.multimodal import MultiModalContext, MultiModalImage

    return MultiModalContext(
        images=[
            MultiModalImage(
                mime="image/png",
                data=STUB_IMAGE_B64,
                source=f"android_screen:{device_id}",
            )
        ],
        screen={"mode": "full", "source": "android"},
        metadata={"device_id": device_id, "mode": "full"},
    )


def make_audio_context(source: Optional[str] = None):
    """Return a :class:`~core.schemas.multimodal.MultiModalContext` with one
    stub audio clip.  Used to prove that audio modality also triggers
    ``requires_native_multimodal=True`` in the canonical perception state.

    Parameters
    ----------
    source:
        Override the audio source tag.  Defaults to ``"stub_microphone"``.

    Returns
    -------
    MultiModalContext
    """
    from core.schemas.multimodal import MultiModalAudio, MultiModalContext

    return MultiModalContext(
        audio=[
            MultiModalAudio(
                mime="audio/wav",
                data=STUB_AUDIO_B64,
                source=source or "stub_microphone",
            )
        ]
    )
