"""听写引擎还在下载 / 加载时，常驻注意力循环不往线程池里丢「转写」去空等。

Windows 真机日志：语音模型首次下载（145MB，约两分钟）期间，每一拍都 ``to_thread(transcribe_b64)`` —— 进去就卡在
同一把加载锁上，到 45 秒期限才被取消（屏幕上是「转写 45 秒没有回应」），线程却还占着池里的位置；
别的 ``to_thread`` 调用（面板数据、感知帧……）跟着变慢。现在这一拍直接放弃转写，引擎在一个专门的后台线程里只加载一次。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from core import modality_bridge as mb


@pytest.fixture(autouse=True)
def _fresh_asr_state(monkeypatch):
    monkeypatch.setattr(mb, "_asr_singleton", None)
    monkeypatch.setattr(mb, "_asr_failed", False)
    monkeypatch.setattr(mb, "_asr_warming", False)
    monkeypatch.setattr(mb, "_asr_warm_logged", False)
    monkeypatch.setattr("core.native_modal.get_active_backend", lambda: None)


class _Engine:
    def transcribe(self, pcm, sample_rate=16000, language="zh"):
        return "你好"


def test_state_names():
    assert mb.asr_state() == "cold"
    mb._asr_warming = True
    assert mb.asr_state() == "warming"
    mb._asr_singleton = _Engine()
    assert mb.asr_state() == "ready"


def test_a_cold_engine_is_warmed_once_in_the_background_and_this_beat_does_not_wait(monkeypatch):
    gate = threading.Event()
    loads = []

    def slow_get_asr():
        loads.append(1)
        gate.wait(5)  # 模型还在下载
        mb._asr_singleton = _Engine()
        return mb._asr_singleton

    monkeypatch.setattr(mb, "_get_asr", slow_get_asr)
    t0 = time.monotonic()
    assert mb.can_listen_now() is False
    assert mb.can_listen_now() is False  # 第二拍:不再起第二个加载线程
    assert time.monotonic() - t0 < 1.0, "没有立刻放弃,在等加载"
    time.sleep(0.2)
    assert mb.asr_state() == "warming" and len(loads) == 1
    gate.set()
    for _ in range(50):
        if mb.asr_state() == "ready":
            break
        time.sleep(0.05)
    assert mb.asr_state() == "ready"
    assert mb.can_listen_now() is True


def test_a_failed_engine_is_not_retried_every_beat(monkeypatch):
    mb._asr_failed = True
    monkeypatch.setattr(mb, "_get_asr", lambda: pytest.fail("不该再去加载"))
    assert mb.can_listen_now() is False


def test_a_native_backend_needs_no_asr(monkeypatch):
    monkeypatch.setattr("core.native_modal.get_active_backend", lambda: object())
    assert mb.can_listen_now() is True
    assert mb.asr_state() == "cold"  # 没去碰听写引擎


def test_the_ambient_loop_skips_transcription_while_the_engine_warms(monkeypatch):
    from core.ambient_attention_loop import AmbientAttentionLoop

    called = []
    monkeypatch.setattr(mb, "can_listen_now", lambda: False)
    monkeypatch.setattr(mb, "transcribe_b64", lambda *a, **k: called.append(1) or "不该到这里")
    loop_obj = AmbientAttentionLoop.__new__(AmbientAttentionLoop)
    obs = type("Obs", (), {"audio_b64": "AAAA", "audio_mime": "audio/webm", "audio_transcript": None})()
    asyncio.run(AmbientAttentionLoop._transcribe_async(loop_obj, obs))
    assert called == [] and obs.audio_transcript is None
