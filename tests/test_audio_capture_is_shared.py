#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_audio_capture_is_shared.py
=========================================
麦克风采集收口：一路物理流，多方订阅。

收口前：``AudioIngestPipeline`` 被实例化两次 —— 一次在常驻感知 bus 启动里，
一次在 ``AudioCaptureService`` 内部（语音循环用）—— 于是**同一个麦克风开了
两路 sd.InputStream**。后果不只是 CPU 翻倍：在 Windows MME/WASAPI 独占等后端下
第二路常常直接打不开，表现为"语音循环好好的，常驻感知却永远听不到声音"
（或反过来），而现场只看得到一句设备打开失败。

收口后：进程级共享实例 + 引用计数。判据是外部可观察结果 —— 两个消费方拿到的
必须是同一个管线对象、同一条流上的回调都收得到、一方停不得关掉另一方的耳朵。
"""

from __future__ import annotations

import asyncio

import pytest

from core.multimodal.audio_features import AudioState
from core.multimodal.audio_ingest import (
    AudioIngestConfig,
    acquire_shared_audio_pipeline,
    release_shared_audio_pipeline,
    reset_shared_audio_pipeline,
    shared_audio_pipeline_refcount,
)
from core.multimodal.signal_quality import SignalQuality


@pytest.fixture(autouse=True)
def _fresh_shared():
    reset_shared_audio_pipeline()
    yield
    reset_shared_audio_pipeline()


# ===========================================================================
# 一、共享与引用计数
# ===========================================================================


def test_two_consumers_share_one_pipeline() -> None:
    """两个消费方必须拿到同一个管线（否则就是两路物理流）。"""
    a = acquire_shared_audio_pipeline()
    b = acquire_shared_audio_pipeline()
    assert a is b, "两个消费方各拿到一个管线 —— 同一个麦克风会被开两次"
    assert shared_audio_pipeline_refcount() == 2


def test_release_by_one_consumer_does_not_deafen_the_other() -> None:
    """一方停不得把另一方的耳朵关掉 —— 引用降到 0 才真停。"""
    a = acquire_shared_audio_pipeline()
    acquire_shared_audio_pipeline()
    a._running = True  # 模拟采集正在跑

    release_shared_audio_pipeline()
    assert a._running is True, "还有订阅方在听，却已经把流停了"
    assert shared_audio_pipeline_refcount() == 1

    release_shared_audio_pipeline()
    assert a._running is False, "最后一个订阅方释放后仍未停流（设备被占住不放）"
    assert shared_audio_pipeline_refcount() == 0


def test_over_release_does_not_go_negative() -> None:
    """多余的释放不得把计数搞成负数（否则后续真订阅方会被误判为 0 而停流）。"""
    acquire_shared_audio_pipeline()
    release_shared_audio_pipeline()
    release_shared_audio_pipeline()  # 多释放一次
    assert shared_audio_pipeline_refcount() == 0
    a = acquire_shared_audio_pipeline()
    a._running = True
    release_shared_audio_pipeline()
    assert a._running is False


def test_conflicting_config_is_reported_not_silently_applied(caplog) -> None:
    """第二方要求了不同采样率 → 必须如实告警并沿用既有实例（一个进程只有一副耳朵）。"""
    import logging

    acquire_shared_audio_pipeline(AudioIngestConfig(sample_rate=16000))
    with caplog.at_level(logging.WARNING):
        second = acquire_shared_audio_pipeline(AudioIngestConfig(sample_rate=48000))
    assert second.config.sample_rate == 16000, "静默改了配置 —— 先接入方的判据会错位"
    assert any("共享麦克风采集" in r.message for r in caplog.records), "配置冲突被静默吞掉"


# ===========================================================================
# 二、扇出：一条流喂到所有订阅方
# ===========================================================================


def test_one_stream_feeds_all_subscribers() -> None:
    """同一条流上的样本必须送达每一个订阅方。"""
    got_a, got_b = [], []
    pipeline = acquire_shared_audio_pipeline()
    acquire_shared_audio_pipeline()
    pipeline.add_callback(lambda s, q: got_a.append(s))
    pipeline.add_callback(lambda s, q: got_b.append(s))

    state = AudioState()
    for cb in list(pipeline._callbacks):
        cb(state, SignalQuality.ok())

    assert got_a and got_b, f"扇出没送达所有订阅方: a={len(got_a)} b={len(got_b)}"


# ===========================================================================
# 三、两个真实消费方确实走了共享入口
# ===========================================================================


def test_capture_service_uses_the_shared_pipeline() -> None:
    """语音循环用的采集服务必须挂在共享管线上，而不是自建一路。"""
    from core.multimodal.audio_capture_service import AudioCaptureService

    shared = acquire_shared_audio_pipeline()
    svc = AudioCaptureService()
    assert svc._pipeline is shared, "采集服务仍在自建管线 —— 同一麦克风两路流"
    assert shared_audio_pipeline_refcount() == 2, "采集服务没有登记引用（停止时会误停共享流）"


def test_capture_service_stop_releases_instead_of_killing_stream() -> None:
    """采集服务 stop() 走引用释放，不得直接停掉共享流。"""
    from core.multimodal.audio_capture_service import AudioCaptureService

    shared = acquire_shared_audio_pipeline()  # 模拟 bus 也在听
    svc = AudioCaptureService()
    shared._running = True

    asyncio.run(svc.stop())
    assert shared._running is True, "采集服务停止时把常驻感知的耳朵也关掉了"
    assert shared_audio_pipeline_refcount() == 1


def test_ingest_runtime_wires_shared_pipeline() -> None:
    """常驻感知 bus 的音频接线也必须走共享入口（AST 钉，注释不算）。"""
    import ast
    import inspect

    import core.multimodal.ingest_runtime as ir

    tree = ast.parse(inspect.getsource(ir))
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "acquire_shared_audio_pipeline"
    ]
    assert calls, "bus 侧仍在直接构造 AudioIngestPipeline —— 回到两路物理流"


# ===========================================================================
# 四、共享之后：驱动这条流的也只能有一个
# ===========================================================================
#
# 收口成共享实例只解决了"两个对象"，没有解决"同一个对象被 run() 两次"：
# 常驻感知 bus 走 ingest_runtime._schedule_pipeline(pipeline.run())，语音循环走
# AudioCaptureService._run() → self._pipeline.run()，共享之后这两处 await 的是
# **同一个对象**。run() 原先没有可重入闸，于是同一个麦克风上又开出两路
# sd.InputStream —— 正是收口要消除的那件事，只是从"两个实例"挪到了"两次 run"。
# 上面那条 test_two_consumers_share_one_pipeline 只钉了对象同一性，钉不住这个。


class _FakeStream:
    opened: list = []

    def __init__(self, **kw):
        type(self).opened.append(kw)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def _fake_sounddevice(monkeypatch):
    import sys
    import types

    import core.multimodal.audio_ingest as ai

    _FakeStream.opened = []
    fake = types.ModuleType("sounddevice")
    fake.InputStream = _FakeStream
    fake.query_devices = lambda *a, **k: [{"name": "mic", "max_input_channels": 1, "max_output_channels": 0}]
    fake.query_hostapis = lambda: [{"name": "fake"}]
    fake.default = type("D", (), {"device": (0, 0)})()
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    monkeypatch.setattr(ai, "_SOUNDDEVICE_AVAILABLE", True)
    monkeypatch.setattr(ai, "_resolve_input_device", lambda sd, dev, sr, ch: dev)
    return _FakeStream


def test_two_run_calls_open_only_one_physical_stream(_fake_sounddevice) -> None:
    """两个订阅方各自 await run() → 物理流仍然只能有一路。"""

    async def _run():
        p = acquire_shared_audio_pipeline()
        acquire_shared_audio_pipeline()
        t1 = asyncio.create_task(p.run())
        t2 = asyncio.create_task(p.run())
        await asyncio.sleep(0.25)
        p.stop()
        done, pending = await asyncio.wait({t1, t2}, timeout=3.0)
        for t in pending:
            t.cancel()
        return len(done)

    finished = asyncio.run(_run())
    assert len(_fake_sounddevice.opened) == 1, (
        f"同一个共享管线开了 {len(_fake_sounddevice.opened)} 路 sd.InputStream —— " "同一麦克风又被开了多次"
    )
    assert finished == 2, "后来的那次 run() 没有正常返回（调用方会以为采集还活着）"


def test_second_run_waits_instead_of_returning_early(_fake_sounddevice) -> None:
    """后来者必须等到流真正停下才返回 —— run() 的语义对每个调用方都是"返回=采集结束"。

    若它立刻返回，AudioCaptureService._run() 的任务会当场结束，服务看起来"没在跑"，
    而实际上流还开着。
    """

    async def _run():
        p = acquire_shared_audio_pipeline()
        t1 = asyncio.create_task(p.run())
        await asyncio.sleep(0.1)
        t2 = asyncio.create_task(p.run())
        await asyncio.sleep(0.3)
        early = t2.done()
        p.stop()
        await asyncio.wait({t1, t2}, timeout=3.0)
        return early, t2.done()

    returned_early, returned_after_stop = asyncio.run(_run())
    assert returned_early is False, "流还开着，后来的 run() 就已经返回了"
    assert returned_after_stop is True, "流停了，后来的 run() 却没返回（任务泄漏）"


def test_pipeline_can_be_driven_again_after_it_stops(_fake_sounddevice) -> None:
    """停掉之后必须能重新驱动 —— 否则可重入闸变成一次性的，重启语音就再也开不了流。"""

    async def _run():
        p = acquire_shared_audio_pipeline()
        t1 = asyncio.create_task(p.run())
        await asyncio.sleep(0.2)
        p.stop()
        await asyncio.wait({t1}, timeout=3.0)
        t2 = asyncio.create_task(p.run())
        await asyncio.sleep(0.2)
        p.stop()
        await asyncio.wait({t2}, timeout=3.0)

    asyncio.run(_run())
    assert len(_fake_sounddevice.opened) == 2, "停止后无法重新开流 —— 闸门锁死了"
