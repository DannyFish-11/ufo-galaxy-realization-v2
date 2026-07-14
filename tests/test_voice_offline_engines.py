"""tests/test_voice_offline_engines.py
==========================================

A 档离线语音对(听/说)引擎:SenseVoice ASR + MeloTTS。
覆盖优雅降级(缺包不抛)+ 引擎选择器(GALAXY_ASR_ENGINE / GALAXY_TTS_ENGINE)。
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from core.asr.sensevoice_asr import SenseVoiceASR
from core.tts.melo_engine import MeloTTSEngine

# ── SenseVoice ASR 降级 ──


class TestSenseVoiceDegrade:
    def test_unavailable_without_funasr(self):
        # 本环境无 funasr → 加载失败,available()=False,绝不抛。
        e = SenseVoiceASR(model="__galaxy_nonexistent__")
        assert e.available() is False
        assert e.is_loaded is False

    def test_transcribe_returns_empty_when_unavailable(self):
        e = SenseVoiceASR(model="__galaxy_nonexistent__")
        out = e.transcribe(np.zeros(16000, dtype=np.float32), sample_rate=16000, language="zh")
        assert out == ""

    def test_clean_strips_rich_tags(self):
        cleaned = SenseVoiceASR._clean("<|zh|><|NEUTRAL|><|Speech|>你好世界<|/zh|>")
        assert "<|" not in cleaned
        assert "你好世界" in cleaned

    def test_clean_empty(self):
        assert SenseVoiceASR._clean("") == ""


# ── MeloTTS 降级 ──


class TestMeloDegrade:
    def test_unavailable_without_pkg(self):
        e = MeloTTSEngine()
        assert e.available() is False

    def test_synthesize_none_when_unavailable(self):
        assert asyncio.run(MeloTTSEngine().synthesize("你好")) is None

    def test_synthesize_empty_none(self):
        assert asyncio.run(MeloTTSEngine().synthesize("")) is None

    def test_stop_safe_when_idle(self):
        asyncio.run(MeloTTSEngine().stop())  # 不抛

    def test_speed_env_parse_safe(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MELO_SPEED", "not_a_number")
        e = MeloTTSEngine()
        assert e.speed == 1.0  # 非法值回退 1.0,不抛


# ── ASR 引擎选择器(modality_bridge._get_asr)──


class TestAsrSelection:
    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        import core.modality_bridge as mb

        mb._asr_singleton = None
        mb._asr_failed = False
        monkeypatch.delenv("GALAXY_ASR_ENGINE", raising=False)
        yield
        mb._asr_singleton = None
        mb._asr_failed = False

    def test_auto_prefers_sensevoice(self, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "_try_sensevoice", lambda: "SV")
        monkeypatch.setattr(mb, "_try_whisper", lambda: "WH")
        monkeypatch.setenv("GALAXY_ASR_ENGINE", "auto")
        assert mb._get_asr() == "SV"

    def test_auto_falls_back_to_whisper(self, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "_try_sensevoice", lambda: None)
        monkeypatch.setattr(mb, "_try_whisper", lambda: "WH")
        monkeypatch.setenv("GALAXY_ASR_ENGINE", "auto")
        assert mb._get_asr() == "WH"

    def test_whisper_forced_skips_sensevoice(self, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "_try_sensevoice", lambda: "SV")
        monkeypatch.setattr(mb, "_try_whisper", lambda: "WH")
        monkeypatch.setenv("GALAXY_ASR_ENGINE", "whisper")
        assert mb._get_asr() == "WH"

    def test_sensevoice_forced_falls_back(self, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "_try_sensevoice", lambda: None)
        monkeypatch.setattr(mb, "_try_whisper", lambda: "WH")
        monkeypatch.setenv("GALAXY_ASR_ENGINE", "sensevoice")
        assert mb._get_asr() == "WH"

    def test_all_none_sets_failed(self, monkeypatch):
        import core.modality_bridge as mb

        monkeypatch.setattr(mb, "_try_sensevoice", lambda: None)
        monkeypatch.setattr(mb, "_try_whisper", lambda: None)
        monkeypatch.setenv("GALAXY_ASR_ENGINE", "auto")
        assert mb._get_asr() is None
        assert mb._asr_failed is True


# ── TTS 引擎选择器含 melo(speech_output._get_engine)──


class TestTtsMeloSelection:
    @pytest.fixture(autouse=True)
    def _reset(self, monkeypatch):
        import core.speech_output as so

        so._engine = None
        so._engine_failed = False
        monkeypatch.delenv("GALAXY_TTS_ENGINE", raising=False)
        yield
        so._engine = None
        so._engine_failed = False

    def test_melo_choice_degrades_gracefully(self, monkeypatch):
        import core.speech_output as so

        monkeypatch.setenv("GALAXY_TTS_ENGINE", "melo")
        eng = so._get_engine()
        # 无 melo/piper 模型 → 退 edge(或 None),绝不崩。
        assert eng is None or type(eng).__name__ in ("EdgeTTSEngine", "MeloTTSEngine", "PiperTTSEngine")

    def test_melo_preferred_when_available(self, monkeypatch):
        import core.speech_output as so

        # 用哨兵替换内部 _try_*:验证 melo 档优先选 melo。
        # (通过环境驱动真实选择路径,melo 优先于 piper/edge。)
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "melo")

        class _FakeMelo:
            def available(self):
                return True

        monkeypatch.setattr("core.tts.melo_engine.MeloTTSEngine", lambda *a, **k: _FakeMelo())
        eng = so._get_engine()
        assert isinstance(eng, _FakeMelo)
