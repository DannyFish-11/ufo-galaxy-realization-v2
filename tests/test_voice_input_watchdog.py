"""tests/test_voice_input_watchdog.py
========================================
语音输入一次性【可见】诊断看门狗:整条链路只在 INFO/DEBUG 打日志,而用户控制台是
WARNING 级 → 麦克风好坏都"看不见"。看门狗按计数在 WARNING 级如实说清死在哪一步。
"""

from __future__ import annotations

import asyncio
import logging

import core.multimodal.audio_capture_service as acs


def _run_watchdog(caplog, monkeypatch, **counters):
    monkeypatch.setenv("GALAXY_VOICE_DIAG_S", "0.01")
    svc = acs.AudioCaptureService()
    svc._chunks_seen = counters.get("chunks_seen", 0)
    svc._speech_chunks = counters.get("speech_chunks", 0)
    svc._transcripts = counters.get("transcripts", 0)
    with caplog.at_level(logging.WARNING):
        asyncio.run(svc._voice_input_watchdog())
    return caplog.text


def test_no_audio(caplog, monkeypatch):
    txt = _run_watchdog(caplog, monkeypatch, chunks_seen=0)
    assert "麦克风一个音频块都没收到" in txt


def test_audio_but_no_speech(caplog, monkeypatch):
    txt = _run_watchdog(caplog, monkeypatch, chunks_seen=200, speech_chunks=0)
    assert "VAD 从未判定为说话" in txt


def test_speech_but_no_text(caplog, monkeypatch):
    txt = _run_watchdog(caplog, monkeypatch, chunks_seen=200, speech_chunks=50, transcripts=0)
    assert "没转写出文字" in txt


def test_working(caplog, monkeypatch):
    txt = _run_watchdog(caplog, monkeypatch, chunks_seen=200, speech_chunks=50, transcripts=3)
    assert "语音输入正常" in txt


def test_disabled(caplog, monkeypatch):
    monkeypatch.setenv("GALAXY_VOICE_DIAG_S", "0")
    svc = acs.AudioCaptureService()
    with caplog.at_level(logging.WARNING):
        asyncio.run(svc._voice_input_watchdog())
    assert "语音输入" not in caplog.text  # 关掉 → 不打诊断
