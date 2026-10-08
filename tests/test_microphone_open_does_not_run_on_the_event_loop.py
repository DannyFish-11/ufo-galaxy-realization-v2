"""开麦克风、探测回环设备都是会阻塞的系统调用，不能压在事件循环线程上。

被修的问题（Windows 真机日志）：``语音交互 已开启`` 之后，紧跟着「系统播放声采集不可用」，同一时刻起一个 5 秒的
整体冻结 —— 面板、对话、感知上传的请求全部排在后面，然后在同一毫秒一起完成。原因是 ``AudioIngestPipeline``
在循环线程上枚举并实测每个输入设备、打开 PortAudio 流，``SystemAudioCaptureService.start()`` 在循环线程上
``probe()``、枚举设备、打开 WASAPI 回环。Windows 上这些每步可以是上百毫秒到数秒。

这里用「记下调用发生在哪个线程」的假 sounddevice 钉住：它们都不在事件循环线程上。
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types

import pytest

import core.multimodal.audio_ingest as ai


class _Recorder:
    def __init__(self):
        self.calls = {}

    def note(self, what):
        self.calls.setdefault(what, set()).add(threading.get_ident())


@pytest.fixture()
def fake_sd(monkeypatch):
    rec = _Recorder()
    fake = types.ModuleType("sounddevice")

    class Stream:
        def __init__(self, **kw):
            rec.note("InputStream()")

        def __enter__(self):
            rec.note("InputStream.__enter__")
            return self

        def __exit__(self, *a):
            rec.note("InputStream.__exit__")
            return False

    def query_devices(*a, **k):
        rec.note("query_devices")
        return [{"name": "mic", "max_input_channels": 1, "max_output_channels": 0}]

    def check_input_settings(**k):
        rec.note("check_input_settings")

    fake.InputStream = Stream
    fake.query_devices = query_devices
    fake.check_input_settings = check_input_settings
    fake.query_hostapis = lambda: [{"name": "fake"}]
    fake.default = type("D", (), {"device": (0, 0)})()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(ai, "_SOUNDDEVICE_AVAILABLE", True)
    return rec


def test_the_microphone_is_enumerated_and_opened_off_the_loop_thread(fake_sd, monkeypatch):
    monkeypatch.setattr("core.multimodal.system_audio_capture_service.ensure_started", lambda *a, **k: None)
    seen = {}

    async def run():
        seen["loop"] = threading.get_ident()
        pipeline = ai.AudioIngestPipeline()
        task = asyncio.create_task(pipeline.run())
        await asyncio.sleep(0.4)
        pipeline.stop()
        await asyncio.wait_for(task, 3.0)

    asyncio.run(run())
    for what in ("query_devices", "check_input_settings", "InputStream()", "InputStream.__enter__"):
        assert what in fake_sd.calls, f"{what} 没被调用 —— 测试没走到该走的路径"
        assert seen["loop"] not in fake_sd.calls[what], f"{what} 在事件循环线程上执行了"
    assert "InputStream.__exit__" in fake_sd.calls and seen["loop"] not in fake_sd.calls["InputStream.__exit__"]


def test_the_loopback_probe_and_open_are_off_the_loop_thread(monkeypatch):
    import core.multimodal.system_audio_capture_service as svc_mod
    import core.multimodal.system_audio_ingest as ingest

    seen_threads = []
    monkeypatch.setattr(svc_mod, "enabled", lambda: True)
    monkeypatch.setattr(
        ingest, "probe", lambda: (seen_threads.append(threading.get_ident()), {"available": False, "reason": "x"})[1]
    )

    async def run():
        loop_thread = threading.get_ident()
        svc = svc_mod.SystemAudioCaptureService(sample_rate=16000)
        assert await svc.start() is False
        return loop_thread

    loop_thread = asyncio.run(run())
    assert seen_threads and loop_thread not in seen_threads


def test_a_second_run_during_the_slow_open_does_not_open_a_second_stream(fake_sd, monkeypatch):
    """开流前的等待会让出事件循环：这时进来的第二个 run() 必须仍被认作「已有人在驱动」。"""
    monkeypatch.setattr("core.multimodal.system_audio_capture_service.ensure_started", lambda *a, **k: None)
    opened = []
    real = sys.modules["sounddevice"].InputStream

    class Counting(real):
        def __init__(self, **kw):
            opened.append(1)
            super().__init__(**kw)

    sys.modules["sounddevice"].InputStream = Counting

    async def run():
        p = ai.AudioIngestPipeline()
        t1 = asyncio.create_task(p.run())
        t2 = asyncio.create_task(p.run())
        await asyncio.sleep(0.4)
        p.stop()
        await asyncio.wait({t1, t2}, timeout=3.0)

    asyncio.run(run())
    assert len(opened) == 1
