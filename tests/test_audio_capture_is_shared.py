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
