"""tests/test_edge_tts_timeout.py
====================================
edge-tts 走 websocket 连微软云;国内/离线/受限网络下 communicate.save() 会【无限期
卡住】而不抛异常 → 上层 demote 换引擎逻辑永不触发 → 用户"他跟我说话一句没听到"。
本测试验证:save() 卡住时 synthesize 会在超时后【快速抛异常】(而非挂死),从而让
speech_output 能降级到离线引擎(Windows 落 SAPI)真正出声。
"""

from __future__ import annotations

import asyncio
import sys
import time
import types

import pytest


def _install_hanging_edge_tts(monkeypatch, delay=60.0):
    fake = types.ModuleType("edge_tts")

    class _Comm:
        def __init__(self, *a, **k):
            pass

        async def save(self, path):
            await asyncio.sleep(delay)  # 模拟连不上微软云:无限卡住

    fake.Communicate = _Comm
    monkeypatch.setitem(sys.modules, "edge_tts", fake)


def test_synth_times_out_fast_instead_of_hanging(monkeypatch, tmp_path):
    _install_hanging_edge_tts(monkeypatch)
    monkeypatch.setenv("GALAXY_EDGE_TTS_TIMEOUT_S", "0.2")
    from core.tts.edge_tts_engine import EdgeTTSEngine

    eng = EdgeTTSEngine()
    t0 = time.monotonic()
    with pytest.raises(Exception) as ei:
        asyncio.run(eng.synthesize("你好", output_path=str(tmp_path / "o.mp3")))
    elapsed = time.monotonic() - t0
    # 快速失败(远小于 save() 的 60s 卡死),且确实是超时类异常
    assert elapsed < 5.0
    assert isinstance(ei.value, (asyncio.TimeoutError, TimeoutError))


def test_timeout_env_override(monkeypatch, tmp_path):
    _install_hanging_edge_tts(monkeypatch)
    monkeypatch.setenv("GALAXY_EDGE_TTS_TIMEOUT_S", "0.1")
    from core.tts.edge_tts_engine import EdgeTTSEngine

    eng = EdgeTTSEngine()
    t0 = time.monotonic()
    with pytest.raises(Exception):
        asyncio.run(eng.synthesize("hi", output_path=str(tmp_path / "o.mp3")))
    # 0.1s 超时应比默认 8s 快得多
    assert time.monotonic() - t0 < 3.0
