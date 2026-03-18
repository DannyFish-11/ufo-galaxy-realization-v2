"""Unit tests for the unified multimodal ingress bus and PerceptionFrame (PR-0C)."""
from __future__ import annotations

import asyncio
import time
from typing import List

import pytest

from core.multimodal.ingress_bus import MultimodalIngressBus
from core.multimodal.perception_frame import PerceptionFrame, SystemSignals
from core.multimodal.audio_features import AudioState
from core.multimodal.video_features import VideoState
from core.multimodal.signal_quality import SignalQuality, QualityFlag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audio_state() -> AudioState:
    return AudioState(
        energy=0.1,
        speaking_ratio=0.6,
        pause_density=0.1,
        noise_level=0.2,
        audio_freshness_ms=50.0,
        is_speaking=True,
    )


def _video_state() -> VideoState:
    return VideoState(
        motion_level=0.3,
        scene_change_rate=0.1,
        face_presence=None,
        video_freshness_ms=100.0,
    )


def _system_signals() -> SystemSignals:
    return SystemSignals(screen_activity=0.7, cpu_load=0.4)


# ---------------------------------------------------------------------------
# PerceptionFrame tests
# ---------------------------------------------------------------------------

class TestPerceptionFrame:
    def test_default_frame_all_missing(self):
        frame = PerceptionFrame()
        assert frame.audio is None
        assert frame.video is None
        assert frame.system is None
        assert frame.audio_quality.flag == QualityFlag.MISSING
        assert frame.video_quality.flag == QualityFlag.MISSING
        assert frame.system_quality.flag == QualityFlag.MISSING

    def test_overall_quality_zero_all_missing(self):
        frame = PerceptionFrame()
        assert frame.overall_quality == 0.0

    def test_overall_quality_with_audio(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.ok(confidence=0.9),
        )
        assert frame.overall_quality == pytest.approx(0.9)

    def test_overall_quality_average_of_modalities(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.ok(confidence=0.8),
            video=_video_state(),
            video_quality=SignalQuality.ok(confidence=0.6),
        )
        assert frame.overall_quality == pytest.approx(0.7)

    def test_active_modalities_empty_when_all_missing(self):
        frame = PerceptionFrame()
        assert frame.active_modalities == []

    def test_active_modalities_lists_usable(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.ok(),
            video=_video_state(),
            video_quality=SignalQuality.ok(),
        )
        mods = frame.active_modalities
        assert "audio" in mods
        assert "video" in mods
        assert "system" not in mods

    def test_active_modalities_degraded_is_usable(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.degraded("test"),
        )
        assert "audio" in frame.active_modalities

    def test_active_modalities_stale_not_usable(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.stale(freshness_ms=9999.0),
        )
        assert "audio" not in frame.active_modalities

    def test_to_dict_contains_required_keys(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.ok(freshness_ms=50.0),
            video=_video_state(),
            video_quality=SignalQuality.ok(freshness_ms=100.0),
        )
        d = frame.to_dict()
        assert "timestamp" in d
        assert "wall_clock" in d
        assert "frame_id" in d
        assert "schema_version" in d
        assert "overall_quality" in d
        assert "active_modalities" in d
        assert "audio_quality" in d
        assert "video_quality" in d
        assert "system_quality" in d
        assert "audio" in d
        assert "video" in d

    def test_to_dict_schema_version_is_1(self):
        d = PerceptionFrame().to_dict()
        assert d["schema_version"] == 1

    def test_to_dict_audio_fields(self):
        frame = PerceptionFrame(
            audio=_audio_state(),
            audio_quality=SignalQuality.ok(),
        )
        d = frame.to_dict()
        a = d["audio"]
        assert "energy" in a
        assert "speaking_ratio" in a
        assert "pause_density" in a
        assert "noise_level" in a
        assert "audio_freshness_ms" in a
        assert "is_speaking" in a

    def test_to_dict_video_fields(self):
        frame = PerceptionFrame(
            video=_video_state(),
            video_quality=SignalQuality.ok(),
        )
        d = frame.to_dict()
        v = d["video"]
        assert "motion_level" in v
        assert "scene_change_rate" in v
        assert "face_presence" in v
        assert "video_freshness_ms" in v

    def test_to_dict_system_fields(self):
        frame = PerceptionFrame(
            system=_system_signals(),
            system_quality=SignalQuality.ok(),
        )
        d = frame.to_dict()
        s = d["system"]
        assert "screen_activity" in s
        assert "cpu_load" in s
        assert s["screen_activity"] == pytest.approx(0.7)

    def test_to_dict_missing_modalities_absent(self):
        d = PerceptionFrame().to_dict()
        assert "audio" not in d
        assert "video" not in d
        assert "system" not in d


# ---------------------------------------------------------------------------
# MultimodalIngressBus tests
# ---------------------------------------------------------------------------

class TestMultimodalIngressBus:
    def test_instantiation(self):
        bus = MultimodalIngressBus()
        assert bus is not None

    def test_build_frame_returns_perception_frame(self):
        bus = MultimodalIngressBus()
        frame = bus.build_frame()
        assert isinstance(frame, PerceptionFrame)

    def test_build_frame_all_missing_by_default(self):
        bus = MultimodalIngressBus()
        frame = bus.build_frame()
        assert frame.audio is None
        assert frame.video is None
        assert frame.system is None
        assert frame.audio_quality.flag == QualityFlag.MISSING
        assert frame.video_quality.flag == QualityFlag.MISSING

    def test_frame_id_increments(self):
        bus = MultimodalIngressBus()
        f1 = bus.build_frame()
        f2 = bus.build_frame()
        assert f2.frame_id == f1.frame_id + 1

    def test_update_audio_reflected_in_frame(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_audio_state(), SignalQuality.ok(freshness_ms=50.0))
        frame = bus.build_frame()
        assert frame.audio is not None
        assert frame.audio.is_speaking
        assert frame.audio_quality.flag == QualityFlag.OK

    def test_update_video_reflected_in_frame(self):
        bus = MultimodalIngressBus()
        bus.update_video(_video_state(), SignalQuality.ok(freshness_ms=100.0))
        frame = bus.build_frame()
        assert frame.video is not None
        assert frame.video.motion_level == pytest.approx(0.3)
        assert frame.video_quality.flag == QualityFlag.OK

    def test_update_system_reflected_in_frame(self):
        bus = MultimodalIngressBus()
        bus.update_system(_system_signals())
        frame = bus.build_frame()
        assert frame.system is not None
        assert frame.system.screen_activity == pytest.approx(0.7)
        assert frame.system_quality.flag == QualityFlag.OK

    def test_missing_audio_does_not_break_video_frame(self):
        bus = MultimodalIngressBus()
        bus.update_video(_video_state(), SignalQuality.ok())
        frame = bus.build_frame()
        assert frame.audio is None
        assert frame.video is not None
        assert frame.audio_quality.flag == QualityFlag.MISSING

    def test_missing_video_does_not_break_audio_frame(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_audio_state(), SignalQuality.ok())
        frame = bus.build_frame()
        assert frame.audio is not None
        assert frame.video is None

    def test_stale_signal_downgraded(self):
        bus = MultimodalIngressBus(tick_ms=200)
        bus._stale_threshold_ms = 10.0  # artificially low
        bus.update_audio(_audio_state(), SignalQuality.ok())
        # Backdate the timestamp
        bus._audio_ts = time.monotonic() - 1.0
        frame = bus.build_frame()
        assert frame.audio_quality.flag == QualityFlag.STALE
        # Stale is not usable → audio should be None
        assert frame.audio is None

    def test_degraded_signal_is_usable(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_audio_state(), SignalQuality.degraded("test"))
        frame = bus.build_frame()
        assert frame.audio is not None

    def test_overall_quality_zero_when_all_missing(self):
        bus = MultimodalIngressBus()
        frame = bus.build_frame()
        assert frame.overall_quality == 0.0

    def test_overall_quality_nonzero_with_audio(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_audio_state(), SignalQuality.ok(confidence=0.8))
        frame = bus.build_frame()
        assert frame.overall_quality > 0.0

    def test_add_callback_registered(self):
        bus = MultimodalIngressBus()
        received: List[PerceptionFrame] = []
        bus.add_callback(received.append)
        assert len(bus._callbacks) == 1

    @pytest.mark.asyncio
    async def test_emit_invokes_callback(self):
        bus = MultimodalIngressBus()
        received: List[PerceptionFrame] = []
        bus.add_callback(received.append)
        frame = bus.build_frame()
        await bus._emit(frame)
        assert len(received) == 1
        assert isinstance(received[0], PerceptionFrame)

    @pytest.mark.asyncio
    async def test_subscribe_receives_frames(self):
        bus = MultimodalIngressBus(tick_ms=50)
        q = bus.subscribe()
        task = asyncio.create_task(bus.run())

        frames: List[PerceptionFrame] = []
        for _ in range(3):
            f = await asyncio.wait_for(q.get(), timeout=2.0)
            frames.append(f)

        bus.stop()
        await task

        assert len(frames) == 3
        assert all(isinstance(f, PerceptionFrame) for f in frames)
        # Frame IDs must be monotonically increasing
        ids = [f.frame_id for f in frames]
        assert ids == sorted(ids)
        assert ids[1] == ids[0] + 1

    @pytest.mark.asyncio
    async def test_run_and_stop(self):
        bus = MultimodalIngressBus(tick_ms=50)
        task = asyncio.create_task(bus.run())
        await asyncio.sleep(0.15)
        bus.stop()
        await asyncio.wait_for(task, timeout=2.0)
        assert not bus._running

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        bus = MultimodalIngressBus(tick_ms=50)
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        task = asyncio.create_task(bus.run())

        f1 = await asyncio.wait_for(q1.get(), timeout=2.0)
        f2 = await asyncio.wait_for(q2.get(), timeout=2.0)
        bus.stop()
        await task

        assert isinstance(f1, PerceptionFrame)
        assert isinstance(f2, PerceptionFrame)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_stop_bus(self):
        bus = MultimodalIngressBus(tick_ms=50)

        def bad_cb(frame: PerceptionFrame) -> None:
            raise RuntimeError("intentional")

        bus.add_callback(bad_cb)
        q = bus.subscribe()
        task = asyncio.create_task(bus.run())

        # Should still receive frames despite bad callback
        frame = await asyncio.wait_for(q.get(), timeout=2.0)
        bus.stop()
        await task
        assert isinstance(frame, PerceptionFrame)

    def test_unsubscribe_removes_queue(self):
        bus = MultimodalIngressBus()
        q = bus.subscribe()
        assert q in bus._subscribers
        bus.unsubscribe(q)
        assert q not in bus._subscribers

    @pytest.mark.asyncio
    async def test_live_audio_and_video_signals(self):
        """End-to-end: inject signals and verify they appear in emitted frames."""
        bus = MultimodalIngressBus(tick_ms=50)
        bus.update_audio(_audio_state(), SignalQuality.ok())
        bus.update_video(_video_state(), SignalQuality.ok())
        bus.update_system(_system_signals())

        q = bus.subscribe()
        task = asyncio.create_task(bus.run())
        frame = await asyncio.wait_for(q.get(), timeout=2.0)
        bus.stop()
        await task

        assert frame.audio is not None
        assert frame.video is not None
        assert frame.system is not None
        mods = frame.active_modalities
        assert "audio" in mods
        assert "video" in mods
        assert "system" in mods

    def test_to_dict_roundtrip(self):
        bus = MultimodalIngressBus()
        bus.update_audio(_audio_state(), SignalQuality.ok(freshness_ms=50.0))
        bus.update_video(_video_state(), SignalQuality.ok(freshness_ms=100.0))
        frame = bus.build_frame()
        d = frame.to_dict()
        assert d["schema_version"] == 1
        assert "audio" in d
        assert "video" in d
        assert d["audio"]["is_speaking"] is True
        assert d["video"]["motion_level"] == pytest.approx(0.3)
