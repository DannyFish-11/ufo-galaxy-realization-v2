"""
PR-1: Multimodal Perception Bus — unit tests
=============================================

Covers:
* text-only request: fusion returns only text, empty media, empty summary
* image+audio context: deterministic fused summary with metadata (no base64)
* EventBus events PERCEPTION_INGESTED and PERCEPTION_FUSED are emitted
* ContextFuser size-limit enforcement (MAX_IMAGES / MAX_AUDIO)
* OpenClawd.process() text-only path is unaffected by the bus
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# ContextFuser tests
# ---------------------------------------------------------------------------

class TestContextFuserTextOnly:
    """Text-only requests must return empty media and empty fusion_summary."""

    def test_fuse_text_only(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(text="Hello world")

        assert result["text"] == "Hello world"
        assert result["images"] == []
        assert result["audio"] == []
        assert result["screen"] == {}
        assert result["device"] == {}
        assert result["fusion_summary"] == ""

    def test_fuse_explicit_empty_lists(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(text="hi", images=[], audio=[], screen=None, device=None)
        assert result["fusion_summary"] == ""


class TestContextFuserWithMedia:
    """Image and/or audio context should produce a deterministic summary."""

    def test_single_image(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(
            text="What is this?",
            images=[{"mime": "image/jpeg", "source": "webcam", "data": "BASE64=="}],
        )

        assert len(result["images"]) == 1
        assert "data" not in result["images"][0], "base64 payload must be stripped"
        assert result["images"][0]["source"] == "webcam"
        assert result["fusion_summary"] == "[Multimodal context: 1 image(s) [webcam]]"

    def test_single_audio(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(
            text="Transcribe this.",
            audio=[{"mime": "audio/wav", "source": "microphone", "data": "BASE64=="}],
        )

        assert len(result["audio"]) == 1
        assert "data" not in result["audio"][0], "base64 payload must be stripped"
        assert result["fusion_summary"] == "[Multimodal context: 1 audio clip(s) [microphone]]"

    def test_image_and_audio_summary_is_deterministic(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        images = [
            {"mime": "image/jpeg", "source": "webcam", "data": "X"},
            {"mime": "image/png", "source": "screenshot", "data": "Y"},
        ]
        audio = [{"mime": "audio/wav", "source": "microphone", "data": "Z"}]

        r1 = fuser.fuse(text="test", images=images, audio=audio)
        r2 = fuser.fuse(text="test", images=images, audio=audio)

        assert r1["fusion_summary"] == r2["fusion_summary"]
        assert "screenshot" in r1["fusion_summary"]
        assert "webcam" in r1["fusion_summary"]
        assert "microphone" in r1["fusion_summary"]

    def test_screen_metadata_included_in_summary(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(
            text="help",
            screen={"window_title": "VS Code", "resolution": "2560x1440"},
        )

        assert result["screen"]["window_title"] == "VS Code"
        assert "screen context" in result["fusion_summary"]
        assert "VS Code" in result["fusion_summary"]

    def test_device_metadata_included_in_summary(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        result = fuser.fuse(text="hi", device={"device_id": "android-01"})

        assert result["device"]["device_id"] == "android-01"
        assert "device=android-01" in result["fusion_summary"]

    def test_base64_never_in_fused_images(self):
        from core.perception.context_fuser import ContextFuser

        fuser = ContextFuser()
        large_b64 = "A" * 50_000
        result = fuser.fuse(
            text="x",
            images=[{"mime": "image/jpeg", "source": "upload", "data": large_b64}],
        )
        for img in result["images"]:
            assert "data" not in img


class TestContextFuserSizeLimits:
    """Payloads exceeding MAX_IMAGES / MAX_AUDIO should be truncated."""

    def test_images_truncated_at_max(self):
        from core.perception.context_fuser import MAX_IMAGES, ContextFuser

        fuser = ContextFuser()
        too_many = [{"mime": "image/jpeg", "source": "cam"} for _ in range(MAX_IMAGES + 5)]
        result = fuser.fuse(text="hi", images=too_many)
        assert len(result["images"]) == MAX_IMAGES

    def test_audio_truncated_at_max(self):
        from core.perception.context_fuser import MAX_AUDIO, ContextFuser

        fuser = ContextFuser()
        too_many = [{"mime": "audio/wav", "source": "mic"} for _ in range(MAX_AUDIO + 3)]
        result = fuser.fuse(text="hi", audio=too_many)
        assert len(result["audio"]) == MAX_AUDIO


# ---------------------------------------------------------------------------
# MultimodalBus tests
# ---------------------------------------------------------------------------

class TestMultimodalBusTextOnly:
    """Text-only path through the bus."""

    def test_ingest_text_only_no_context(self):
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        result = bus.ingest(message="Hello")

        assert result["text"] == "Hello"
        assert result["images"] == []
        assert result["audio"] == []
        assert result["fusion_summary"] == ""

    def test_ingest_text_only_returns_all_keys(self):
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        result = bus.ingest(message="test")

        assert set(result.keys()) == {"text", "images", "audio", "screen", "device", "fusion_summary"}


class TestMultimodalBusWithContext:
    """Bus with a MultiModalContext object (Pydantic-like stub)."""

    def _make_context(self, n_images: int = 1, n_audio: int = 1):
        """Build a minimal MultiModalContext-like object."""
        from core.schemas.multimodal import MultiModalAudio, MultiModalContext, MultiModalImage

        images = [
            MultiModalImage(mime="image/jpeg", data="FAKE_B64", source="webcam")
            for _ in range(n_images)
        ]
        audio = [
            MultiModalAudio(mime="audio/wav", data="FAKE_B64", source="microphone")
            for _ in range(n_audio)
        ]
        return MultiModalContext(images=images, audio=audio)

    def test_ingest_image_audio_produces_summary(self):
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        ctx = self._make_context(n_images=2, n_audio=1)
        result = bus.ingest(
            message="What's this?",
            multimodal_context=ctx,
            device_metadata={"device_id": "dev-1"},
        )

        assert len(result["images"]) == 2
        assert len(result["audio"]) == 1
        assert result["fusion_summary"] != ""
        assert "image" in result["fusion_summary"]
        assert "audio" in result["fusion_summary"]

    def test_base64_stripped_in_output(self):
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        ctx = self._make_context(n_images=1, n_audio=1)
        result = bus.ingest(message="hi", multimodal_context=ctx)

        for img in result["images"]:
            assert "data" not in img, "image base64 must be stripped"
        for aud in result["audio"]:
            assert "data" not in aud, "audio base64 must be stripped"

    def test_device_metadata_in_fused(self):
        from core.perception.multimodal_bus import MultimodalBus

        bus = MultimodalBus()
        result = bus.ingest(
            message="hi",
            device_metadata={"device_id": "phone-1", "session_id": "sess-abc"},
        )

        assert result["device"]["device_id"] == "phone-1"


# ---------------------------------------------------------------------------
# EventBus event emission tests
# ---------------------------------------------------------------------------

class TestMultimodalBusEvents:
    """PERCEPTION_INGESTED and PERCEPTION_FUSED must be emitted."""

    def test_events_emitted_on_text_only(self):
        from core.perception.multimodal_bus import MultimodalBus

        emitted: list = []

        with patch(
            "core.perception.multimodal_bus._galaxy_event_bus.publish",
            side_effect=lambda evt: emitted.append(evt.event_type.name),
        ):
            bus = MultimodalBus()
            bus.ingest(message="hello")

        assert "PERCEPTION_INGESTED" in emitted
        assert "PERCEPTION_FUSED" in emitted

    def test_events_emitted_with_context(self):
        from core.schemas.multimodal import MultiModalContext, MultiModalImage
        from core.perception.multimodal_bus import MultimodalBus

        emitted: list = []

        ctx = MultiModalContext(
            images=[MultiModalImage(mime="image/png", data="X", source="cam")]
        )

        with patch(
            "core.perception.multimodal_bus._galaxy_event_bus.publish",
            side_effect=lambda evt: emitted.append(evt.event_type.name),
        ):
            bus = MultimodalBus()
            bus.ingest(message="see this", multimodal_context=ctx)

        assert emitted.count("PERCEPTION_INGESTED") == 1
        assert emitted.count("PERCEPTION_FUSED") == 1

    def test_eventbus_failure_is_non_fatal(self):
        """If EventBus.publish raises the bus must still return a result."""
        from core.perception.multimodal_bus import MultimodalBus

        with patch(
            "core.perception.multimodal_bus._galaxy_event_bus.publish",
            side_effect=RuntimeError("bus down"),
        ):
            bus = MultimodalBus()
            result = bus.ingest(message="hi")

        assert result["text"] == "hi"
        assert result["fusion_summary"] == ""


# ---------------------------------------------------------------------------
# EventType enum membership tests
# ---------------------------------------------------------------------------

class TestPerceptionEventTypes:
    """PERCEPTION_INGESTED and PERCEPTION_FUSED must be in EventType."""

    def test_event_types_exist(self):
        from integration.event_bus import EventType

        assert hasattr(EventType, "PERCEPTION_INGESTED")
        assert hasattr(EventType, "PERCEPTION_FUSED")

    def test_event_type_aliases(self):
        from core.perception.event_types import PERCEPTION_FUSED, PERCEPTION_INGESTED
        from integration.event_bus import EventType

        assert PERCEPTION_INGESTED is EventType.PERCEPTION_INGESTED
        assert PERCEPTION_FUSED is EventType.PERCEPTION_FUSED


# ---------------------------------------------------------------------------
# OpenClawd integration — text-only path unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_openclawd_process_text_only_unaffected():
    """OpenClawd.process() text-only path must return success and a response."""
    from core.openclawd import OpenClawd

    oc = OpenClawd()

    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            with patch.object(oc, "_parse_intent", return_value=None):
                with patch.object(
                    oc,
                    "_dispatch_chat",
                    return_value={"success": True, "response": "OK"},
                ):
                    result = await oc.process(message="hello")

    assert result["success"] is True
    assert result["response"] == "OK"
    # fusion_summary is empty for text-only → message is unchanged
    assert result.get("trace_id") is not None


@pytest.mark.asyncio
async def test_openclawd_process_multimodal_injects_summary():
    """When multimodal_context is provided the handler receives the augmented message."""
    from core.schemas.multimodal import MultiModalContext, MultiModalImage
    from core.openclawd import OpenClawd

    oc = OpenClawd()
    ctx = MultiModalContext(
        images=[MultiModalImage(mime="image/jpeg", data="X", source="webcam")]
    )

    received_messages: list = []

    async def _mock_dispatch_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
        received_messages.append(message)
        return {"success": True, "response": "got it"}

    with patch.object(oc, "_get_kernel", return_value=None):
        with patch.object(oc, "sync_device_capabilities", return_value=0):
            with patch.object(oc, "_parse_intent", return_value=None):
                with patch.object(oc, "_dispatch_chat", side_effect=_mock_dispatch_chat):
                    result = await oc.process(
                        message="describe",
                        multimodal_context=ctx,
                    )

    assert result["success"] is True
    assert len(received_messages) == 1
    # The handler received the augmented message that includes the fusion summary
    assert "[Multimodal context:" in received_messages[0]
    assert "webcam" in received_messages[0]
