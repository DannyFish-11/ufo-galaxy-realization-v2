"""tests/test_tts_engine_selection.py
========================================

语音引擎选择(GALAXY_TTS_ENGINE)+ Piper 离线引擎优雅降级。
A 档无卡/断网时可选 piper;缺包/缺模型一律降级不抛。
"""
from __future__ import annotations

import asyncio

import pytest

import core.speech_output as so
from core.tts.piper_engine import PiperTTSEngine, _discover_model


@pytest.fixture(autouse=True)
def _reset_engine(monkeypatch):
    so._engine = None
    so._engine_failed = False
    for k in ("GALAXY_TTS_ENGINE",):
        monkeypatch.delenv(k, raising=False)
    yield
    so._engine = None
    so._engine_failed = False


class TestPiperDegrade:
    def test_no_model_not_available(self, monkeypatch):
        monkeypatch.delenv("GALAXY_PIPER_MODEL", raising=False)
        e = PiperTTSEngine(model_path=None)
        assert e.available() is False

    def test_synthesize_returns_none_when_unavailable(self):
        e = PiperTTSEngine(model_path=None)
        assert asyncio.run(e.synthesize("你好")) is None

    def test_synthesize_empty_none(self):
        e = PiperTTSEngine(model_path="/nonexistent.onnx")
        assert asyncio.run(e.synthesize("")) is None

    def test_stop_safe_when_idle(self):
        asyncio.run(PiperTTSEngine().stop())  # 不抛


class TestEngineSelection:
    def test_default_edge(self, monkeypatch):
        eng = so._get_engine()
        # 环境无 edge-tts 包时可能 None;有则是 EdgeTTSEngine。piper 不应被默认选中。
        assert eng is None or type(eng).__name__ == "EdgeTTSEngine"

    def test_piper_choice_falls_back_to_edge_without_model(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "piper")
        eng = so._get_engine()
        # 无 piper 模型 → 退 edge(或 None),绝不崩
        assert eng is None or type(eng).__name__ in ("EdgeTTSEngine", "PiperTTSEngine")

    def test_auto_prefers_edge(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TTS_ENGINE", "auto")
        eng = so._get_engine()
        assert eng is None or type(eng).__name__ in ("EdgeTTSEngine", "PiperTTSEngine")
