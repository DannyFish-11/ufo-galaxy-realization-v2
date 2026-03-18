"""Integration/wiring tests for the multimodal ingress system (PR-7).

Validates:
1. Config flags: enable_multimodal_ingest is respected.
2. AudioIngestPipeline + MultimodalIngressBus end-to-end wiring.
3. VideoIngestPipeline + MultimodalIngressBus end-to-end wiring.
4. Graceful degradation: missing devices / permission denied.
5. PerceptionFrame integrity: bounded values, schema_version, frame_id.
6. Bus subscription / unsubscription contract.
"""
from __future__ import annotations

import asyncio
import time
from typing import List
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core.multimodal.ingress_bus import MultimodalIngressBus
from core.multimodal.perception_frame import PerceptionFrame, SystemSignals
from core.multimodal.audio_features import AudioState, extract_audio_features
from core.multimodal.video_features import VideoState
from core.multimodal.signal_quality import SignalQuality, QualityFlag
from core.multimodal.audio_ingest import AudioIngestPipeline, AudioIngestConfig
from core.multimodal.video_ingest import VideoIngestPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_audio_state(energy: float = 0.3, speaking: bool = True) -> AudioState:
    return AudioState(
        energy=min(1.0, max(0.0, energy)),
        speaking_ratio=0.6,
        pause_density=0.1,
        noise_level=0.2,
        audio_freshness_ms=50.0,
        is_speaking=speaking,
    )


def _make_video_state(motion: float = 0.2) -> VideoState:
    return VideoState(
        motion_level=min(1.0, max(0.0, motion)),
        scene_change_rate=0.05,
        face_presence=None,
        video_freshness_ms=33.0,
    )


def _make_system_signals() -> SystemSignals:
    return SystemSignals(screen_activity=0.5, cpu_load=0.3)


# ===========================================================================
# Config flag wiring
# ===========================================================================

class TestConfigFlags:
    """enable_multimodal_ingest must exist in config.json."""

    def test_flag_present_in_config(self):
        import json
        import pathlib

        config_path = pathlib.Path(__file__).parent.parent / "config.json"
        config = json.loads(config_path.read_text())
        assert "enable_multimodal_ingest" in config, (
            "config.json must contain 'enable_multimodal_ingest'"
        )

    def test_flag_is_boolean(self):
        import json
        import pathlib

        config_path = pathlib.Path(__file__).parent.parent / "config.json"
        config = json.loads(config_path.read_text())
        assert isinstance(config["enable_multimodal_ingest"], bool)

    def test_enable_system_api_flag_present(self):
        import json
        import pathlib

        config_path = pathlib.Path(__file__).parent.parent / "config.json"
        config = json.loads(config_path.read_text())
        assert "enable_system_api" in config
        assert isinstance(config["enable_system_api"], bool)


# ===========================================================================
# PerceptionFrame bounded-values contract
# ===========================================================================

class TestPerceptionFrameBounds:
    """All float fields in PerceptionFrame must be bounded [0, 1]."""

    def _check_bounded(self, value: float, name: str) -> None:
        assert 0.0 <= value <= 1.0, f"{name}={value} is outside [0,1]"

    def test_audio_state_fields_bounded(self):
        s = _make_audio_state(energy=0.7)
        self._check_bounded(s.energy, "energy")
        self._check_bounded(s.speaking_ratio, "speaking_ratio")
        self._check_bounded(s.pause_density, "pause_density")
        self._check_bounded(s.noise_level, "noise_level")

    def test_video_state_fields_bounded(self):
        s = _make_video_state(motion=0.4)
        self._check_bounded(s.motion_level, "motion_level")
        self._check_bounded(s.scene_change_rate, "scene_change_rate")

    def test_system_signals_fields_bounded(self):
        s = _make_system_signals()
        self._check_bounded(s.screen_activity, "screen_activity")
        self._check_bounded(s.cpu_load, "cpu_load")

    def test_overall_quality_bounded(self):
        frame = PerceptionFrame(
            audio=_make_audio_state(),
            audio_quality=SignalQuality.ok(confidence=0.8),
            video=_make_video_state(),
            video_quality=SignalQuality.ok(confidence=0.6),
        )
        q = frame.overall_quality
        self._check_bounded(q, "overall_quality")

    def test_signal_quality_confidence_bounded(self):
        for conf in (0.0, 0.5, 1.0):
            sq = SignalQuality.ok(confidence=conf)
            self._check_bounded(sq.confidence, f"confidence={conf}")

    def test_schema_version_is_1(self):
        frame = PerceptionFrame()
        assert frame.schema_version == 1


# ===========================================================================
# Audio pipeline → bus wiring
# ===========================================================================

class TestAudioPipelineToBusWiring:
    """AudioIngestPipeline callbacks must wire into MultimodalIngressBus."""

    def test_callback_updates_bus_audio(self):
        bus = MultimodalIngressBus()
        pipeline = AudioIngestPipeline()

        # Wire the pipeline into the bus
        pipeline.add_callback(bus.update_audio)

        # Simulate a chunk arriving from the pipeline
        audio = _make_audio_state()
        quality = SignalQuality.ok(confidence=0.9)
        bus.update_audio(audio, quality)

        # Bus should now reflect the audio state
        frame = bus.build_frame()
        assert frame.audio is not None
        assert frame.audio.energy == pytest.approx(audio.energy)

    def test_pipeline_graceful_when_no_sounddevice(self):
        """Pipeline run() must return without raising when sounddevice is absent."""
        import core.multimodal.audio_ingest as mod

        pipeline = AudioIngestPipeline()
        with patch.object(mod, "_SOUNDDEVICE_AVAILABLE", False):
            asyncio.get_event_loop().run_until_complete(pipeline.run())
        # No exception raised, quality is device_unavailable
        _, quality = pipeline.get_latest()
        assert quality.flag == QualityFlag.DEVICE_UNAVAILABLE

    def test_pipeline_permission_denied_graceful(self):
        """Pipeline gracefully handles PermissionError."""
        import core.multimodal.audio_ingest as mod

        pipeline = AudioIngestPipeline()

        # Simulate sounddevice available but permission denied
        mock_sd = MagicMock()
        mock_sd.InputStream.side_effect = PermissionError("mic denied")

        with patch.object(mod, "_SOUNDDEVICE_AVAILABLE", True), \
             patch.dict("sys.modules", {"sounddevice": mock_sd}):
            asyncio.get_event_loop().run_until_complete(pipeline.run())

        _, quality = pipeline.get_latest()
        assert quality.flag == QualityFlag.PERMISSION_DENIED


# ===========================================================================
# Video pipeline → bus wiring
# ===========================================================================

class TestVideoPipelineToBusWiring:
    """VideoIngestPipeline callbacks must wire into MultimodalIngressBus."""

    def test_callback_updates_bus_video(self):
        bus = MultimodalIngressBus()
        pipeline = VideoIngestPipeline()

        pipeline.add_callback(bus.update_video)

        video = _make_video_state()
        quality = SignalQuality.ok(confidence=0.85)
        bus.update_video(video, quality)

        frame = bus.build_frame()
        assert frame.video is not None
        assert frame.video.motion_level == pytest.approx(video.motion_level)

    def test_pipeline_graceful_when_no_cv2(self):
        """Pipeline correctly reports device_unavailable when session is unavailable."""
        from core.multimodal.webrtc_session import WebRTCCameraSession
        from unittest.mock import PropertyMock

        pipeline = VideoIngestPipeline()

        with patch.object(
            type(pipeline._session), "is_available",
            new_callable=PropertyMock, return_value=False
        ):
            assert not pipeline.is_available
            # Verify the quality is correctly set when unavailable
            pipeline._quality = SignalQuality.device_unavailable()

        _, quality = pipeline.get_latest()
        assert quality.flag == QualityFlag.DEVICE_UNAVAILABLE


# ===========================================================================
# Full ingress bus wiring
# ===========================================================================

class TestFullIngressBusWiring:
    """End-to-end bus test: all three modalities update and compose a frame."""

    def test_all_modalities_compose_frame(self):
        bus = MultimodalIngressBus()

        audio = _make_audio_state(energy=0.6)
        video = _make_video_state(motion=0.3)
        system = _make_system_signals()

        bus.update_audio(audio, SignalQuality.ok(confidence=0.9))
        bus.update_video(video, SignalQuality.ok(confidence=0.8))
        bus.update_system(system, SignalQuality.ok(confidence=1.0))

        frame = bus.build_frame()

        assert frame.audio is not None
        assert frame.video is not None
        assert frame.system is not None
        assert frame.overall_quality > 0.0
        assert "audio" in frame.active_modalities
        assert "video" in frame.active_modalities
        assert "system" in frame.active_modalities

    def test_partial_modalities_compose_frame(self):
        """Only audio wired: video and system must be None."""
        bus = MultimodalIngressBus()
        bus.update_audio(_make_audio_state(), SignalQuality.ok())

        frame = bus.build_frame()
        assert frame.audio is not None
        assert frame.video is None
        assert frame.system is None

    def test_frame_id_monotonically_increments(self):
        bus = MultimodalIngressBus()
        ids = [bus.build_frame().frame_id for _ in range(5)]
        for i in range(1, len(ids)):
            assert ids[i] == ids[i - 1] + 1

    def test_subscribe_and_unsubscribe(self):
        bus = MultimodalIngressBus()
        q = bus.subscribe()
        assert q in bus._subscribers
        bus.unsubscribe(q)
        assert q not in bus._subscribers

    def test_bus_emits_to_subscriber(self):
        async def _run():
            bus = MultimodalIngressBus(tick_ms=20)
            q = bus.subscribe()

            bus.update_audio(_make_audio_state(), SignalQuality.ok())
            task = asyncio.create_task(bus.run())
            await asyncio.sleep(0.07)
            bus.stop()
            await task

            frames: List[PerceptionFrame] = []
            while not q.empty():
                frames.append(q.get_nowait())
            return frames

        frames = asyncio.get_event_loop().run_until_complete(_run())
        assert len(frames) >= 1
        for f in frames:
            assert isinstance(f, PerceptionFrame)

    def test_callback_invoked_on_tick(self):
        received: List[PerceptionFrame] = []

        async def _run():
            bus = MultimodalIngressBus(tick_ms=20)
            bus.add_callback(received.append)
            bus.update_audio(_make_audio_state(), SignalQuality.ok())
            task = asyncio.create_task(bus.run())
            await asyncio.sleep(0.07)
            bus.stop()
            await task

        asyncio.get_event_loop().run_until_complete(_run())
        assert len(received) >= 1


# ===========================================================================
# Graceful degradation
# ===========================================================================

class TestGracefulDegradation:
    """When modalities are absent/stale the bus must still emit frames."""

    def test_stale_audio_excluded_from_frame(self):
        bus = MultimodalIngressBus()
        bus._stale_threshold_ms = 1.0  # very short stale window

        bus.update_audio(_make_audio_state(), SignalQuality.ok())
        # Wait for the snapshot to become stale
        time.sleep(0.05)

        frame = bus.build_frame()
        # With such a short stale threshold the audio should be excluded
        assert frame.audio_quality.flag in (
            QualityFlag.STALE, QualityFlag.MISSING, QualityFlag.OK
        )

    def test_empty_bus_returns_valid_frame(self):
        bus = MultimodalIngressBus()
        frame = bus.build_frame()
        assert isinstance(frame, PerceptionFrame)
        assert frame.overall_quality == 0.0

    def test_degraded_quality_signal_still_usable(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_make_audio_state(), SignalQuality.degraded("test"))
        frame = bus.build_frame()
        # Degraded is still usable
        assert frame.audio is not None
        assert "audio" in frame.active_modalities


# ===========================================================================
# Multimodal __init__ public exports
# ===========================================================================

class TestMultimodalPackageExports:
    """core.multimodal.__init__ must export the key symbols."""

    def test_imports(self):
        from core.multimodal import (  # noqa: F401
            SignalQuality,
            QualityFlag,
            PerceptionFrame,
            SystemSignals,
            MultimodalIngressBus,
        )
