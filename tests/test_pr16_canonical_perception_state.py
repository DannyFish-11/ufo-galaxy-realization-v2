"""tests/test_pr16_canonical_perception_state.py — PR-16: Canonical Perception State

Validates:
1. Text-only request produces a valid canonical perception state with no multimodal breakage.
2. Request-bound multimodal context is reflected in the canonical perception state.
3. Continuous perception presence is reflected when ingress is available.
4. Canonical perception state remains valid when continuous ingress is unavailable.
5. Shell/core boundary is preserved conceptually and in wiring.
6. Canonical perception state is serializable and safe for diagnostics.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio_state(**kwargs) -> Any:
    """Return a minimal AudioState-like mock."""
    from core.multimodal.audio_features import AudioState
    return AudioState(
        energy=kwargs.get("energy", 0.1),
        speaking_ratio=kwargs.get("speaking_ratio", 0.5),
        pause_density=kwargs.get("pause_density", 0.1),
        noise_level=kwargs.get("noise_level", 0.2),
        audio_freshness_ms=kwargs.get("audio_freshness_ms", 50.0),
        is_speaking=kwargs.get("is_speaking", True),
    )


def _make_video_state(**kwargs) -> Any:
    from core.multimodal.video_features import VideoState
    return VideoState(
        motion_level=kwargs.get("motion_level", 0.3),
        scene_change_rate=kwargs.get("scene_change_rate", 0.1),
        face_presence=kwargs.get("face_presence", 0.8),
        video_freshness_ms=kwargs.get("video_freshness_ms", 100.0),
    )


def _make_perception_frame(with_audio=True, with_video=False) -> Any:
    """Build a minimal PerceptionFrame for testing."""
    from core.multimodal.perception_frame import PerceptionFrame, SystemSignals
    from core.multimodal.signal_quality import SignalQuality, QualityFlag

    audio = _make_audio_state() if with_audio else None
    audio_q = SignalQuality(flag=QualityFlag.OK, freshness_ms=50.0, confidence=0.9)
    video = _make_video_state() if with_video else None
    video_q = (
        SignalQuality(flag=QualityFlag.OK, freshness_ms=100.0, confidence=0.8)
        if with_video
        else SignalQuality.missing()
    )
    return PerceptionFrame(
        audio=audio,
        audio_quality=audio_q,
        video=video,
        video_quality=video_q,
        frame_id=42,
    )


def _make_multimodal_context(n_images=1, n_audio=0, screen=None):
    """Build a minimal MultiModalContext for testing."""
    from core.schemas.multimodal import MultiModalContext, MultiModalImage, MultiModalAudio

    images = [
        MultiModalImage(mime="image/jpeg", data="FAKEBASE64==", source="webcam")
        for _ in range(n_images)
    ]
    audio = [
        MultiModalAudio(mime="audio/wav", data="FAKEAUDIO==", source="microphone")
        for _ in range(n_audio)
    ]
    return MultiModalContext(images=images, audio=audio, screen=screen)


# ---------------------------------------------------------------------------
# 1. Text-only request: valid canonical state, no multimodal breakage
# ---------------------------------------------------------------------------

class TestTextOnlyProducesValidCanonicalState:
    """A text-only request must produce a valid CanonicalPerceptionState."""

    def test_text_only_state_is_built(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(
            runtime_session_id="sess-001",
            trace_id="trace-001",
            fused_context={"images": [], "audio": [], "screen": {}, "device": {}, "fusion_summary": ""},
            multimodal_context=None,
            continuous_frame=None,
        )

        assert state is not None
        assert state.runtime_session_id == "sess-001"
        assert state.trace_id == "trace-001"

    def test_text_only_no_continuous(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(
            runtime_session_id="sess-001",
            trace_id="trace-001",
            continuous_frame=None,
        )

        assert state.has_continuous_perception is False

    def test_text_only_no_request_multimodal(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(
            runtime_session_id="sess-001",
            trace_id="trace-001",
            multimodal_context=None,
            fused_context=None,
        )

        assert state.has_request_multimodal is False

    def test_text_only_active_modalities_empty(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()

        assert state.active_modalities == []

    def test_text_only_perception_summary_contains_text_only(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(continuous_frame=None, multimodal_context=None)

        assert "text-only" in state.perception_summary

    def test_text_only_degradation_reason(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()

        assert "text_only" in state.degradation_reasons

    def test_text_only_no_native_multimodal_required(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()

        assert state.requires_native_multimodal is False

    def test_text_only_source_summary_flags(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()

        assert state.source_summary is not None
        assert state.source_summary["has_ingress_bus"] is False
        assert state.source_summary["has_request_context"] is False
        assert state.source_summary["request_image_count"] == 0
        assert state.source_summary["request_audio_count"] == 0


# ---------------------------------------------------------------------------
# 2. Request-bound multimodal context is reflected
# ---------------------------------------------------------------------------

class TestRequestMultimodalContextReflected:
    """Request-bound multimodal context must be accurately reflected in the state."""

    def test_has_request_multimodal_when_images_present(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=2)
        fused = {
            "images": [{"mime": "image/jpeg", "source": "webcam"}] * 2,
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 2 image(s) [webcam]]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.has_request_multimodal is True
        assert state.requires_native_multimodal is True

    def test_fusion_summary_is_captured(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"mime": "image/jpeg", "source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s) [webcam]]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.fusion_summary == "[Multimodal context: 1 image(s) [webcam]]"

    def test_image_modality_in_active_modalities(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"mime": "image/jpeg", "source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s)]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert "image" in state.active_modalities

    def test_audio_request_modality(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=0, n_audio=1)
        fused = {
            "images": [],
            "audio": [{"mime": "audio/wav", "source": "microphone"}],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 audio clip(s) [microphone]]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.has_request_multimodal is True
        assert "audio" in state.active_modalities
        assert state.requires_native_multimodal is True

    def test_source_summary_request_counts(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=3, n_audio=2)
        fused = {
            "images": [{"source": "webcam"}] * 3,
            "audio": [{"source": "microphone"}] * 2,
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 3 image(s), 2 audio clip(s)]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.source_summary["request_image_count"] == 3
        assert state.source_summary["request_audio_count"] == 2
        assert state.source_summary["has_request_context"] is True

    def test_perception_summary_includes_request_info(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s) [webcam]]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert "request(" in state.perception_summary


# ---------------------------------------------------------------------------
# 3. Continuous perception presence is reflected when ingress is available
# ---------------------------------------------------------------------------

class TestContinuousPerceptionReflected:
    """When a PerceptionFrame is supplied, the state must reflect it."""

    def test_has_continuous_perception_true(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert state.has_continuous_perception is True

    def test_frame_id_captured(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame()
        state = build_canonical_perception_state(continuous_frame=frame)

        assert state.continuous_frame_id == 42

    def test_continuous_overall_quality(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert state.continuous_overall_quality is not None
        assert 0.0 <= state.continuous_overall_quality <= 1.0

    def test_audio_summary_from_continuous_frame(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert state.audio_summary is not None
        assert state.audio_summary["source"] == "continuous"
        assert "is_speaking" in state.audio_summary

    def test_audio_modality_in_active_when_frame_has_audio(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert "audio" in state.active_modalities

    def test_quality_summary_populated(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert state.quality_summary is not None
        assert "overall" in state.quality_summary
        assert "audio_flag" in state.quality_summary

    def test_continuous_perception_summary(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        state = build_canonical_perception_state(continuous_frame=frame)

        assert "continuous" in state.perception_summary
        assert "text-only" not in state.perception_summary

    def test_continuous_and_request_both_present(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s) [webcam]]",
        }

        state = build_canonical_perception_state(
            continuous_frame=frame,
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.has_continuous_perception is True
        assert state.has_request_multimodal is True
        # Both paths reflected in summary
        assert "continuous" in state.perception_summary
        assert "request(" in state.perception_summary


# ---------------------------------------------------------------------------
# 4. State remains valid when continuous ingress is unavailable
# ---------------------------------------------------------------------------

class TestContinuousIngressUnavailableGraceful:
    """When the ingress bus is down, the state must still be valid."""

    def test_no_continuous_frame_has_continuous_false(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(continuous_frame=None)
        assert state.has_continuous_perception is False

    def test_degradation_reason_includes_unavailable(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(continuous_frame=None, multimodal_context=None)
        # text_only implies continuous_perception_unavailable; both must appear
        assert "continuous_perception_unavailable" in state.degradation_reasons

    def test_request_multimodal_still_works_without_ingress(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s) [webcam]]",
        }

        state = build_canonical_perception_state(
            continuous_frame=None,
            multimodal_context=ctx,
            fused_context=fused,
        )

        assert state.has_request_multimodal is True
        assert state.has_continuous_perception is False
        assert "image" in state.active_modalities

    def test_text_only_without_ingress_does_not_raise(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state(
            continuous_frame=None,
            multimodal_context=None,
            fused_context=None,
        )
        assert "text-only" in state.perception_summary


# ---------------------------------------------------------------------------
# 5. Shell/core boundary preservation
# ---------------------------------------------------------------------------

class TestShellCoreBoundary:
    """The shell owns continuous perception; OpenClawd consumes canonical state."""

    def test_desktop_presence_runtime_has_snapshot_method(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        assert hasattr(DesktopPresenceRuntime, "snapshot_continuous_perception")
        assert callable(DesktopPresenceRuntime.snapshot_continuous_perception)

    def test_snapshot_continuous_perception_returns_none_when_bus_not_running(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        runtime = DesktopPresenceRuntime()
        result = runtime.snapshot_continuous_perception()
        # Without an active ingest bus, returns None
        assert result is None

    def test_openclawd_has_build_canonical_perception_state_helper(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "_build_canonical_perception_state")
        assert callable(oc._build_canonical_perception_state)

    def test_openclawd_build_canonical_returns_dict_or_none(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        result = oc._build_canonical_perception_state(
            runtime_session_id="rs-test",
            trace_id="tr-test",
            multimodal_context=None,
            fused_context=None,
        )
        # Returns a dict (or None on catastrophic failure; dict expected here)
        assert result is None or isinstance(result, dict)

    def test_canonical_perception_state_module_is_in_perception_package(self):
        import core.perception.canonical_perception_state as _mod
        assert hasattr(_mod, "CanonicalPerceptionState")
        assert hasattr(_mod, "build_canonical_perception_state")

    def test_two_path_flags_are_independent(self):
        """has_continuous_perception and has_request_multimodal are independent."""
        from core.perception.canonical_perception_state import build_canonical_perception_state

        # Only continuous
        frame = _make_perception_frame()
        s1 = build_canonical_perception_state(continuous_frame=frame, multimodal_context=None)
        assert s1.has_continuous_perception is True
        assert s1.has_request_multimodal is False

        # Only request
        ctx = _make_multimodal_context(n_images=1)
        fused = {"images": [{"source": "webcam"}], "audio": [], "screen": {}, "device": {},
                 "fusion_summary": "[Multimodal context: 1 image(s)]"}
        s2 = build_canonical_perception_state(continuous_frame=None, multimodal_context=ctx,
                                              fused_context=fused)
        assert s2.has_continuous_perception is False
        assert s2.has_request_multimodal is True

        # Neither
        s3 = build_canonical_perception_state()
        assert s3.has_continuous_perception is False
        assert s3.has_request_multimodal is False


# ---------------------------------------------------------------------------
# 6. Serializable and safe for diagnostics
# ---------------------------------------------------------------------------

class TestSerializability:
    """CanonicalPerceptionState.to_dict() must be JSON-safe and complete."""

    def test_to_dict_returns_dict(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()
        d = state.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_has_required_keys(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()
        d = state.to_dict()

        required_keys = [
            "runtime_session_id",
            "trace_id",
            "has_continuous_perception",
            "has_request_multimodal",
            "active_modalities",
            "fusion_summary",
            "requires_native_multimodal",
            "degradation_reasons",
            "perception_summary",
            "quality_summary",
            "source_summary",
        ]
        for key in required_keys:
            assert key in d, f"Missing key in to_dict(): {key}"

    def test_to_dict_is_json_serializable(self):
        import json
        from core.perception.canonical_perception_state import build_canonical_perception_state

        frame = _make_perception_frame(with_audio=True)
        ctx = _make_multimodal_context(n_images=1)
        fused = {
            "images": [{"source": "webcam"}],
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 1 image(s)]",
        }

        state = build_canonical_perception_state(
            runtime_session_id="rs-json-test",
            trace_id="tr-json-test",
            continuous_frame=frame,
            multimodal_context=ctx,
            fused_context=fused,
        )

        d = state.to_dict()
        serialized = json.dumps(d)  # must not raise
        assert isinstance(serialized, str)
        assert "rs-json-test" in serialized

    def test_to_dict_contains_no_base64_payloads(self):
        """No base64 blobs should appear in the serialized state."""
        import json
        import re
        from core.perception.canonical_perception_state import build_canonical_perception_state

        ctx = _make_multimodal_context(n_images=2)
        fused = {
            "images": [{"mime": "image/jpeg", "source": "webcam"}] * 2,
            "audio": [],
            "screen": {},
            "device": {},
            "fusion_summary": "[Multimodal context: 2 image(s)]",
        }

        state = build_canonical_perception_state(
            multimodal_context=ctx,
            fused_context=fused,
        )

        serialized = json.dumps(state.to_dict())
        # No long base64 blobs in the serialized output
        base64_pattern = r'"[A-Za-z0-9+/]{80,}={0,2}"'
        match = re.search(base64_pattern, serialized)
        assert match is None, f"Base64 payload found in canonical state: {match.group()[:40]}..."

    def test_perception_summary_is_string(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()
        assert isinstance(state.perception_summary, str)
        assert len(state.perception_summary) > 0

    def test_active_modalities_is_list(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()
        assert isinstance(state.active_modalities, list)

    def test_degradation_reasons_is_list(self):
        from core.perception.canonical_perception_state import build_canonical_perception_state

        state = build_canonical_perception_state()
        assert isinstance(state.degradation_reasons, list)


# ---------------------------------------------------------------------------
# 7. OpenClawd integration: canonical_perception_state in response metadata
# ---------------------------------------------------------------------------

class TestOpenClawdIntegration:
    """OpenClawd.process() should include canonical_perception_state in metadata."""

    @pytest.mark.asyncio
    async def test_text_only_process_includes_canonical_perception(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "intent": "chat",
                    "metadata": {}, "execution_path": "local"}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(
                            message="hello",
                            runtime_session_id="rs-cps-test",
                        )

        assert result.get("success") is True
        meta = result.get("metadata", {})
        cps = meta.get("canonical_perception_state")
        assert cps is not None, "canonical_perception_state must be in response metadata"
        assert isinstance(cps, dict)
        assert cps["has_continuous_perception"] is False
        assert cps["has_request_multimodal"] is False
        assert "text-only" in cps["perception_summary"]

    @pytest.mark.asyncio
    async def test_multimodal_process_includes_canonical_perception(self):
        from core.openclawd import OpenClawd
        from core.schemas.multimodal import MultiModalContext, MultiModalImage

        oc = OpenClawd()
        ctx = MultiModalContext(
            images=[MultiModalImage(mime="image/jpeg", data="FAKE==", source="webcam")]
        )

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "intent": "chat",
                    "metadata": {}, "execution_path": "local"}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(
                            message="what is this?",
                            multimodal_context=ctx,
                            runtime_session_id="rs-mm-test",
                        )

        assert result.get("success") is True
        meta = result.get("metadata", {})
        cps = meta.get("canonical_perception_state")
        assert cps is not None
        assert cps["has_request_multimodal"] is True
        assert cps["requires_native_multimodal"] is True
        assert "image" in cps["active_modalities"]

    @pytest.mark.asyncio
    async def test_runtime_session_id_propagated_to_canonical_perception(self):
        from core.openclawd import OpenClawd

        oc = OpenClawd()

        async def _mock_chat(message, intent=None, device_id=None, session_id=None, trace_id=None):
            return {"success": True, "response": "ok", "intent": "chat",
                    "metadata": {}, "execution_path": "local"}

        with patch.object(oc, "_get_kernel", return_value=None):
            with patch.object(oc, "sync_device_capabilities", return_value=0):
                with patch.object(oc, "_parse_intent", return_value=None):
                    with patch.object(oc, "_dispatch_chat", side_effect=_mock_chat):
                        result = await oc.process(
                            message="ping",
                            runtime_session_id="rs-propagation-test",
                        )

        cps = result.get("metadata", {}).get("canonical_perception_state")
        assert cps is not None
        assert cps["runtime_session_id"] == "rs-propagation-test"
        assert cps["trace_id"] == "rs-propagation-test"
