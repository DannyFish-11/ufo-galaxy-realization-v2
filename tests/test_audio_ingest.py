"""Unit tests for audio ingest pipeline and features (PR-0A)."""
from __future__ import annotations

import asyncio
import time
from typing import List

import numpy as np
import pytest

from core.multimodal.vad import VoiceActivityDetector, VADConfig, VADState
from core.multimodal.audio_features import AudioState, extract_audio_features
from core.multimodal.audio_ingest import AudioIngestPipeline, AudioIngestConfig
from core.multimodal.signal_quality import SignalQuality, QualityFlag


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent(n: int = 1600) -> np.ndarray:
    return np.zeros(n, dtype=np.float32)


def _make_loud(n: int = 1600, amp: float = 0.5) -> np.ndarray:
    return np.ones(n, dtype=np.float32) * amp


def _make_vad_state(
    is_speaking: bool = True,
    energy: float = 0.1,
    speaking_ratio: float = 0.6,
    pause_density: float = 0.1,
) -> VADState:
    return VADState(
        is_speaking=is_speaking,
        energy=energy,
        speaking_ratio=speaking_ratio,
        pause_density=pause_density,
    )


# ---------------------------------------------------------------------------
# VAD tests
# ---------------------------------------------------------------------------

class TestVoiceActivityDetector:
    def test_silence_is_not_speaking(self):
        vad = VoiceActivityDetector()
        state = vad.process_frame(_make_silent())
        assert not state.is_speaking
        assert state.energy < 1e-6

    def test_loud_signal_triggers_speech_after_min_frames(self):
        config = VADConfig(energy_threshold=0.01, min_speech_frames=1)
        vad = VoiceActivityDetector(config=config)
        state = vad.process_frame(_make_loud())
        assert state.is_speaking
        assert state.energy > 0.1

    def test_requires_consecutive_frames_for_speech(self):
        config = VADConfig(energy_threshold=0.01, min_speech_frames=3)
        vad = VoiceActivityDetector(config=config)
        # Only 2 frames — should not yet confirm speech
        vad.process_frame(_make_loud())
        state = vad.process_frame(_make_loud())
        assert not state.is_speaking
        # Third frame confirms
        state = vad.process_frame(_make_loud())
        assert state.is_speaking

    def test_speaking_ratio_increases_with_activity(self):
        config = VADConfig(energy_threshold=0.01, min_speech_frames=1, window_duration_ms=300)
        vad = VoiceActivityDetector(config=config)
        for _ in range(10):
            vad.process_frame(_make_loud())
        state = vad.process_frame(_make_loud())
        assert state.speaking_ratio > 0.5

    def test_speaking_ratio_zero_for_silence(self):
        vad = VoiceActivityDetector()
        for _ in range(20):
            vad.process_frame(_make_silent())
        state = vad.process_frame(_make_silent())
        assert state.speaking_ratio == 0.0

    def test_pause_density_increases_with_alternation(self):
        config = VADConfig(energy_threshold=0.01, min_speech_frames=1)
        vad = VoiceActivityDetector(config=config)
        for _ in range(4):
            vad.process_frame(_make_loud())
            vad.process_frame(_make_silent())
        state = vad.process_frame(_make_silent())
        assert state.pause_density > 0.0

    def test_reset_clears_state(self):
        config = VADConfig(energy_threshold=0.01, min_speech_frames=1)
        vad = VoiceActivityDetector(config=config)
        for _ in range(5):
            vad.process_frame(_make_loud())
        vad.reset()
        state = vad.process_frame(_make_silent())
        assert state.speaking_ratio == 0.0
        assert not state.is_speaking

    def test_multichannel_input_is_handled(self):
        vad = VoiceActivityDetector()
        stereo = np.ones((1600, 2), dtype=np.float32) * 0.5
        state = vad.process_frame(stereo)
        assert state.energy > 0.0

    def test_energy_is_nonnegative(self):
        vad = VoiceActivityDetector()
        for _ in range(10):
            chunk = np.random.randn(1600).astype(np.float32)
            state = vad.process_frame(chunk)
            assert state.energy >= 0.0


# ---------------------------------------------------------------------------
# Audio feature extraction tests
# ---------------------------------------------------------------------------

class TestAudioFeatureExtraction:
    def test_returns_audio_state_type(self):
        chunk = np.random.randn(1600).astype(np.float32) * 0.1
        vad_state = _make_vad_state()
        state = extract_audio_features(chunk, vad_state, last_update_ts=time.monotonic())
        assert isinstance(state, AudioState)

    def test_silence_has_near_zero_energy(self):
        vad_state = _make_vad_state(is_speaking=False, energy=0.0)
        state = extract_audio_features(_make_silent(), vad_state)
        assert state.energy < 1e-6
        assert not state.is_speaking

    def test_noise_level_is_bounded(self):
        for _ in range(20):
            chunk = np.random.randn(1600).astype(np.float32) * 0.1
            vad_state = _make_vad_state()
            state = extract_audio_features(chunk, vad_state)
            assert 0.0 <= state.noise_level <= 1.0

    def test_freshness_ms_nonnegative(self):
        chunk = _make_loud()
        vad_state = _make_vad_state()
        past = time.monotonic() - 0.1
        state = extract_audio_features(chunk, vad_state, last_update_ts=past)
        assert state.audio_freshness_ms >= 0.0

    def test_freshness_zero_without_previous_ts(self):
        chunk = _make_loud()
        vad_state = _make_vad_state()
        state = extract_audio_features(chunk, vad_state, last_update_ts=None)
        assert state.audio_freshness_ms == 0.0

    def test_vad_fields_propagated(self):
        chunk = _make_loud()
        vad_state = _make_vad_state(
            is_speaking=True, energy=0.42, speaking_ratio=0.77, pause_density=0.22
        )
        state = extract_audio_features(chunk, vad_state)
        assert state.is_speaking
        assert state.energy == pytest.approx(0.42)
        assert state.speaking_ratio == pytest.approx(0.77)
        assert state.pause_density == pytest.approx(0.22)


# ---------------------------------------------------------------------------
# AudioIngestPipeline tests
# ---------------------------------------------------------------------------

class TestAudioIngestPipeline:
    def test_instantiation_default_config(self):
        pipeline = AudioIngestPipeline()
        assert pipeline is not None

    def test_custom_config(self):
        cfg = AudioIngestConfig(sample_rate=8000, chunk_duration_ms=200)
        pipeline = AudioIngestPipeline(config=cfg)
        assert pipeline.config.sample_rate == 8000

    def test_not_available_when_sounddevice_absent(self, monkeypatch):
        import core.multimodal.audio_ingest as mod
        monkeypatch.setattr(mod, "_SOUNDDEVICE_AVAILABLE", False)
        pipeline = AudioIngestPipeline()
        assert not pipeline.is_available

    @pytest.mark.asyncio
    async def test_run_returns_immediately_when_no_sounddevice(self, monkeypatch):
        import core.multimodal.audio_ingest as mod
        monkeypatch.setattr(mod, "_SOUNDDEVICE_AVAILABLE", False)
        pipeline = AudioIngestPipeline()
        await asyncio.wait_for(pipeline.run(), timeout=2.0)
        _, quality = pipeline.get_latest()
        assert quality.flag == QualityFlag.DEVICE_UNAVAILABLE

    def test_add_callback_registers(self):
        pipeline = AudioIngestPipeline()
        called: List[AudioState] = []
        pipeline.add_callback(lambda s, q: called.append(s))
        assert len(pipeline._callbacks) == 1

    @pytest.mark.asyncio
    async def test_process_chunk_invokes_callbacks(self):
        pipeline = AudioIngestPipeline()
        received: List[AudioState] = []
        pipeline.add_callback(lambda s, q: received.append(s))
        chunk = np.random.randn(1600).astype(np.float32) * 0.1
        await pipeline._process_chunk(chunk)
        assert len(received) == 1
        assert isinstance(received[0], AudioState)

    @pytest.mark.asyncio
    async def test_process_chunk_updates_quality_to_ok(self):
        pipeline = AudioIngestPipeline()
        await pipeline._process_chunk(_make_loud())
        _, quality = pipeline.get_latest()
        assert quality.flag == QualityFlag.OK

    @pytest.mark.asyncio
    async def test_multiple_chunks_accumulate_speaking_ratio(self):
        pipeline = AudioIngestPipeline()
        config = VADConfig(energy_threshold=0.01, min_speech_frames=1)
        pipeline._vad = VoiceActivityDetector(config=config)
        for _ in range(10):
            await pipeline._process_chunk(_make_loud())
        state, _ = pipeline.get_latest()
        assert state is not None
        assert state.speaking_ratio > 0.5

    def test_stop_sets_running_false(self):
        pipeline = AudioIngestPipeline()
        pipeline._running = True
        pipeline.stop()
        assert not pipeline._running

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_crash_pipeline(self):
        pipeline = AudioIngestPipeline()

        def bad_cb(s, q):
            raise RuntimeError("intentional error")

        pipeline.add_callback(bad_cb)
        # Should not raise
        await pipeline._process_chunk(_make_loud())
