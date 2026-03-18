"""Unit tests for WebRTC camera ingest pipeline and video features (PR-0B)."""
from __future__ import annotations

import asyncio
import time
from typing import List, Optional

import numpy as np
import pytest

from core.multimodal.video_features import VideoFeatureExtractor, VideoState
from core.multimodal.webrtc_session import (
    WebRTCCameraSession,
    WebRTCSessionConfig,
    WebRTCSessionState,
)
from core.multimodal.video_ingest import VideoIngestPipeline, VideoIngestConfig
from core.multimodal.signal_quality import SignalQuality, QualityFlag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _black(h: int = 64, w: int = 64, channels: int = 3) -> np.ndarray:
    return np.zeros((h, w, channels), dtype=np.uint8)


def _white(h: int = 64, w: int = 64, channels: int = 3) -> np.ndarray:
    return np.ones((h, w, channels), dtype=np.uint8) * 255


def _gray_2d(h: int = 64, w: int = 64) -> np.ndarray:
    return np.zeros((h, w), dtype=np.uint8)


# ---------------------------------------------------------------------------
# VideoFeatureExtractor tests
# ---------------------------------------------------------------------------

class TestVideoFeatureExtractor:
    def test_first_frame_returns_valid_state(self):
        extractor = VideoFeatureExtractor()
        state = extractor.process_frame(_black())
        assert isinstance(state, VideoState)
        assert state.motion_level == 0.0  # no previous frame

    def test_identical_frames_zero_motion(self):
        extractor = VideoFeatureExtractor()
        frame = _black()
        extractor.process_frame(frame)
        state = extractor.process_frame(frame)
        assert state.motion_level < 0.05

    def test_different_frames_nonzero_motion(self):
        extractor = VideoFeatureExtractor()
        extractor.process_frame(_black())
        state = extractor.process_frame(_white())
        assert state.motion_level > 0.5

    def test_motion_level_bounded_0_1(self):
        extractor = VideoFeatureExtractor()
        extractor.process_frame(_black())
        state = extractor.process_frame(_white())
        assert 0.0 <= state.motion_level <= 1.0

    def test_scene_change_rate_increments_on_large_change(self):
        extractor = VideoFeatureExtractor(scene_change_threshold=0.1)
        black = _black()
        white = _white()
        extractor.process_frame(black)
        for _ in range(5):
            extractor.process_frame(white)
            extractor.process_frame(black)
        state = extractor.process_frame(white)
        assert state.scene_change_rate > 0.0

    def test_no_scene_change_on_static_feed(self):
        extractor = VideoFeatureExtractor(scene_change_threshold=0.35)
        frame = _black()
        for _ in range(10):
            extractor.process_frame(frame)
        state = extractor.process_frame(frame)
        assert state.scene_change_rate == 0.0

    def test_face_presence_none_when_disabled(self):
        extractor = VideoFeatureExtractor()
        extractor.process_frame(_black())
        state = extractor.process_frame(_black(), enable_face=False)
        assert state.face_presence is None

    def test_grayscale_2d_input(self):
        extractor = VideoFeatureExtractor()
        state = extractor.process_frame(_gray_2d())
        assert isinstance(state, VideoState)

    def test_freshness_ms_nonnegative(self):
        extractor = VideoFeatureExtractor()
        extractor.process_frame(_black())
        state = extractor.process_frame(_white())
        assert state.video_freshness_ms >= 0.0

    def test_freshness_zero_on_first_frame(self):
        extractor = VideoFeatureExtractor()
        state = extractor.process_frame(_black())
        assert state.video_freshness_ms == 0.0

    def test_single_channel_bgr_shape(self):
        extractor = VideoFeatureExtractor()
        # single-channel 3-D
        frame = np.zeros((64, 64, 1), dtype=np.uint8)
        state = extractor.process_frame(frame)
        assert isinstance(state, VideoState)

    def test_float32_input(self):
        extractor = VideoFeatureExtractor()
        frame = np.zeros((64, 64, 3), dtype=np.float32)
        state = extractor.process_frame(frame)
        assert isinstance(state, VideoState)


# ---------------------------------------------------------------------------
# WebRTCCameraSession tests
# ---------------------------------------------------------------------------

class TestWebRTCCameraSession:
    def test_initial_state_is_idle(self):
        session = WebRTCCameraSession()
        assert session.state == WebRTCSessionState.IDLE

    def test_not_available_without_aiortc(self, monkeypatch):
        import core.multimodal.webrtc_session as mod
        monkeypatch.setattr(mod, "_AIORTC_AVAILABLE", False)
        session = WebRTCCameraSession()
        assert not session.is_available

    @pytest.mark.asyncio
    async def test_connect_returns_none_without_aiortc(self, monkeypatch):
        import core.multimodal.webrtc_session as mod
        monkeypatch.setattr(mod, "_AIORTC_AVAILABLE", False)
        session = WebRTCCameraSession()
        result = await session.connect("dummy_sdp")
        assert result is None
        assert session.state == WebRTCSessionState.IDLE  # connect was short-circuited

    def test_get_latest_frame_returns_none_initially(self):
        session = WebRTCCameraSession()
        frame, quality = session.get_latest_frame()
        assert frame is None
        assert not quality.is_usable

    def test_get_latest_frame_returns_frame_when_set(self):
        session = WebRTCCameraSession()
        fake_frame = _black()
        session._latest_frame = fake_frame
        session._last_frame_ts = time.monotonic()
        frame, quality = session.get_latest_frame()
        assert frame is not None
        assert quality.is_usable

    def test_stale_frame_has_stale_quality(self):
        session = WebRTCCameraSession(
            config=WebRTCSessionConfig(frame_stale_threshold_ms=10.0)
        )
        session._latest_frame = _black()
        session._last_frame_ts = time.monotonic() - 1.0  # 1 second ago
        _, quality = session.get_latest_frame()
        assert quality.flag == QualityFlag.STALE

    def test_add_frame_callback(self):
        session = WebRTCCameraSession()
        session.add_frame_callback(lambda f: None)
        assert len(session._frame_callbacks) == 1

    @pytest.mark.asyncio
    async def test_close_without_connection(self):
        session = WebRTCCameraSession()
        await session.close()  # Must not raise
        assert session.state == WebRTCSessionState.CLOSED

    @pytest.mark.asyncio
    async def test_quality_becomes_device_unavailable_without_aiortc(self, monkeypatch):
        import core.multimodal.webrtc_session as mod
        monkeypatch.setattr(mod, "_AIORTC_AVAILABLE", False)
        session = WebRTCCameraSession()
        await session.connect("dummy_sdp")
        assert session._quality.flag == QualityFlag.DEVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# VideoIngestPipeline tests
# ---------------------------------------------------------------------------

class TestVideoIngestPipeline:
    def test_instantiation_default_config(self):
        pipeline = VideoIngestPipeline()
        assert pipeline is not None

    def test_custom_config(self):
        cfg = VideoIngestConfig(sample_interval_ms=500, enable_face_detection=False)
        pipeline = VideoIngestPipeline(config=cfg)
        assert pipeline.config.sample_interval_ms == 500

    def test_not_available_without_aiortc(self, monkeypatch):
        import core.multimodal.webrtc_session as mod
        monkeypatch.setattr(mod, "_AIORTC_AVAILABLE", False)
        pipeline = VideoIngestPipeline()
        assert not pipeline.is_available

    def test_add_callback(self):
        pipeline = VideoIngestPipeline()
        pipeline.add_callback(lambda s, q: None)
        assert len(pipeline._callbacks) == 1

    def test_get_latest_returns_none_initially(self):
        pipeline = VideoIngestPipeline()
        state, quality = pipeline.get_latest()
        assert state is None
        assert quality.flag == QualityFlag.MISSING

    def test_push_frame_extracts_video_state(self):
        pipeline = VideoIngestPipeline()
        state = pipeline.push_frame(_black())
        assert isinstance(state, VideoState)

    def test_push_frame_invokes_callbacks(self):
        pipeline = VideoIngestPipeline()
        received: List[VideoState] = []
        pipeline.add_callback(lambda s, q: received.append(s))
        pipeline.push_frame(_black())
        assert len(received) == 1
        assert isinstance(received[0], VideoState)

    def test_push_frame_updates_latest(self):
        pipeline = VideoIngestPipeline()
        pipeline.push_frame(_black())
        state, quality = pipeline.get_latest()
        assert state is not None
        assert quality.flag == QualityFlag.OK

    def test_push_frame_motion_detection(self):
        pipeline = VideoIngestPipeline()
        pipeline.push_frame(_black())
        state = pipeline.push_frame(_white())
        assert state.motion_level > 0.5

    def test_stop_sets_running_false(self):
        pipeline = VideoIngestPipeline()
        pipeline._running = True
        pipeline.stop()
        assert not pipeline._running

    @pytest.mark.asyncio
    async def test_run_without_frames_does_not_crash(self, monkeypatch):
        import core.multimodal.webrtc_session as mod
        monkeypatch.setattr(mod, "_AIORTC_AVAILABLE", False)
        pipeline = VideoIngestPipeline(config=VideoIngestConfig(sample_interval_ms=50))
        task = asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.15)
        pipeline.stop()
        await task  # Must complete without exception

    @pytest.mark.asyncio
    async def test_run_processes_injected_frames(self):
        pipeline = VideoIngestPipeline(config=VideoIngestConfig(sample_interval_ms=50))
        received: List[VideoState] = []
        pipeline.add_callback(lambda s, q: received.append(s))

        # Inject a frame into the session before run() starts polling
        fake_frame = _black()
        pipeline._session._latest_frame = fake_frame
        pipeline._session._last_frame_ts = time.monotonic()
        pipeline._session._quality = SignalQuality.ok()

        task = asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.2)
        pipeline.stop()
        await task

        assert len(received) > 0
        assert isinstance(received[0], VideoState)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash_run(self):
        pipeline = VideoIngestPipeline(config=VideoIngestConfig(sample_interval_ms=50))

        def bad_cb(s, q):
            raise RuntimeError("intentional")

        pipeline.add_callback(bad_cb)
        pipeline._session._latest_frame = _black()
        pipeline._session._last_frame_ts = time.monotonic()
        pipeline._session._quality = SignalQuality.ok()

        task = asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.15)
        pipeline.stop()
        await task  # Must not raise
