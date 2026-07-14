"""tests/test_audio_capture_asr_non_blocking.py
==================================================
语音链路稳定性排查发现的真实、可复现问题:

core/multimodal/audio_capture_service.py::add_whisper_callback() 注册的
_asr_callback 是从 AudioIngestPipeline._process_chunk() 的异步主循环里【同步】
调用的。之前它直接在这个回调里跑 whisper_asr.transcribe()——这是一个同步、
CPU 密集调用(几百毫秒到数秒不等)。而这条主循环和 FastAPI 服务共用同一个
事件循环，等于每次用户说完一句话触发转写，HTTP/WS/面板轮询等所有其它并发
工作都会被真实冻结相应时长，且没有任何用户可见提示。

core/voice_loop.py(用户实际部署默认启用的语音闭环，GALAXY_VOICE=1)正是通过
AudioCaptureService + add_whisper_callback 接入 ASR 的，所以这个问题是真实、
默认路径可复现的，不是理论上的边缘情况。

修复:transcribe() 调用改到线程池 worker 线程执行(run_in_executor)，不再
阻塞事件循环；对应地，_emit_voice_input() 在 worker 线程里调用时不能再用
asyncio.create_task()(那需要"当前线程有运行中的事件循环"，worker 线程没有)，
改为跨线程安全的 run_coroutine_threadsafe，调度到 start() 时捕获的主循环。
"""

from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest

from core.multimodal.audio_capture_service import AudioCaptureService
from core.multimodal.audio_features import AudioState
from core.multimodal.signal_quality import SignalQuality


class _SlowFakeWhisper:
    """模拟一次真实转写耗时的 Whisper——用来证明回调本身不再被这个耗时拖住。"""

    def __init__(self, delay_s: float = 0.3):
        self.delay_s = delay_s
        self.call_thread_names: list = []

    def transcribe(self, audio_np, sample_rate=16000, language="zh"):
        self.call_thread_names.append(threading.current_thread().name)
        time.sleep(self.delay_s)  # 模拟真实 CPU 密集转写耗时
        return "转写结果"


@pytest.mark.asyncio
async def test_transcribe_runs_off_the_event_loop_thread():
    """核心回归:transcribe() 必须跑在别的线程上，不能跟事件循环共用主线程。"""
    svc = AudioCaptureService()
    svc._loop = asyncio.get_running_loop()  # 模拟 start() 已捕获主循环

    fake_whisper = _SlowFakeWhisper(delay_s=0.3)
    svc.add_whisper_callback(fake_whisper, language="zh")
    asr_callback = svc._asr_callbacks[-1]

    speaking_state = AudioState(
        energy=0.5,
        speaking_ratio=0.6,
        pause_density=0.1,
        noise_level=0.2,
        audio_freshness_ms=50.0,
        is_speaking=True,
        samples=np.zeros(16000, dtype=np.float32),
        sample_rate=16000,
    )
    silence_state = AudioState(
        energy=0.0,
        speaking_ratio=0.0,
        pause_density=0.0,
        noise_level=0.0,
        audio_freshness_ms=50.0,
        is_speaking=False,
        samples=np.zeros(1, dtype=np.float32),
        sample_rate=16000,
    )
    fake_quality = SignalQuality.ok(freshness_ms=10.0)

    main_thread_name = threading.current_thread().name

    asr_callback(speaking_state, fake_quality)  # 积累 1.0s 语音到 buffer

    start = time.monotonic()
    asr_callback(silence_state, fake_quality)  # 说话结束(buffer_duration=1.0s > 0.5 阈值)→触发转写
    elapsed = time.monotonic() - start

    assert elapsed < 0.1, f"回调本身必须立即返回，不能同步等待 0.3s 的转写完成；实际耗时 {elapsed:.3f}s"

    # 等转写在后台线程真正跑完。
    await asyncio.sleep(0.5)
    assert fake_whisper.call_thread_names, "transcribe() 应该已经被调用过"
    assert (
        fake_whisper.call_thread_names[0] != main_thread_name
    ), "transcribe() 必须跑在非主线程(线程池 worker)上，不能占用事件循环所在线程"


@pytest.mark.asyncio
async def test_voice_input_delivered_when_transcribe_runs_in_worker_thread():
    """转写在 worker 线程完成后，async on_voice_input 回调必须仍然能正确送达
    (跨线程调度到主事件循环)，不能因为 RuntimeError(no running event loop)
    而静默丢失这次语音输入。"""
    svc = AudioCaptureService()
    svc._loop = asyncio.get_running_loop()

    received = []

    async def _on_voice_input(text: str) -> None:
        received.append(text)

    svc.on_voice_input = _on_voice_input

    fake_whisper = _SlowFakeWhisper(delay_s=0.05)
    svc.add_whisper_callback(fake_whisper, language="zh")
    asr_callback = svc._asr_callbacks[-1]

    speaking_state = AudioState(
        energy=0.5,
        speaking_ratio=0.6,
        pause_density=0.1,
        noise_level=0.2,
        audio_freshness_ms=50.0,
        is_speaking=True,
        samples=np.zeros(16000, dtype=np.float32),
        sample_rate=16000,
    )
    silence_state = AudioState(
        energy=0.0,
        speaking_ratio=0.0,
        pause_density=0.0,
        noise_level=0.0,
        audio_freshness_ms=50.0,
        is_speaking=False,
        samples=np.zeros(1, dtype=np.float32),
        sample_rate=16000,
    )
    fake_quality = SignalQuality.ok(freshness_ms=10.0)

    asr_callback(speaking_state, fake_quality)  # 积累 1.0s 语音到 buffer
    asr_callback(silence_state, fake_quality)  # 说话结束 → 触发转写

    # 给线程池 worker + run_coroutine_threadsafe 调度留足时间。
    for _ in range(20):
        if received:
            break
        await asyncio.sleep(0.05)

    assert received == ["转写结果"], "worker 线程里产出的转写结果必须正确送达主循环的 async 回调"
