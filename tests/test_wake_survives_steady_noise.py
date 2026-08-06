#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_wake_survives_steady_noise.py

钉住：**风扇一直转，"叫它"也得有反应**。

这条缺陷
========
``VoiceWakeModule._detect_loop`` 里，识别唤醒词的 ``_process_buffer`` 只在
**「说话结束」那一拍**被调用：

.. code-block:: python

    if is_speech:
        speech_detected = True
        audio_buffer += data
    elif speech_detected and len(audio_buffer) > 0:   # ← 唯一的识别时机
        self._process_buffer(audio_buffer)

而判据原来是 ``webrtcvad.Vad(2)`` **独断**。webrtcvad 是频谱分类器，宽带稳态噪声
（风扇/空调）在它眼里跟摩擦音、清音很像，它照判有声 —— 这正是采集侧
（``core/multimodal/vad.py``）明确记录并已经处置掉的那条旧行为，而唤醒这条链
一直留着。

于是：VAD 恒判有声 ⇒ ``elif`` 那一拍永远不来 ⇒ ``_process_buffer`` 一次都不会被
调用 ⇒ **叫它永远没反应**。缓冲还被原来的「Prevent buffer overflow」逻辑滚着
（攒满就丢掉只留最后 1 秒），把唤醒词悄悄扔掉。实测（桩替掉 VAD 跑 60 秒）::

    VAD 恒判有声（稳态噪声）      _process_buffer 被调用 0 次
    VAD 正常起落（说一句、停一下）  _process_buffer 被调用 2 次

处置（两层，缺一不可）
======================
1. **判据同源**：改用 ``VoiceActivityDetector``，与采集管线同一套判据 ——
   取「频谱有声 ∩ 能量超自适应门限」的交集，稳态噪声不再恒判有声；
   ``GALAXY_VAD_*`` 一套环境变量对两条链同时生效（原来这里写死 ``2``，
   而 ``VADConfig`` 的文档还写着"与 voice_wake_module 保持一致"——靠人对齐）。
2. **控制流兜底**：连续有声攒满 ``BUFFER_MAX_MS`` 就强制转写一次。一条链的
   可用性不该完全押在另一条链的判据不出错上。

第 2 层不是多余的：判据再好也可能在没见过的声学环境下判错，而这条链的失效模式是
**静默的**（没有异常、没有日志，只是再也不响应）。
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

# pyaudio 在 CI 上没有；模块顶层是 try/except ImportError，但 VoiceWakeModule
# 本身不需要它就能构造，这里只是避免 import 期噪声。
sys.modules.setdefault("pyaudio", types.ModuleType("pyaudio"))

from core.voice_wake_module import VoiceWakeModule  # noqa: E402

_RATE = VoiceWakeModule.SAMPLE_RATE
_CHUNK = VoiceWakeModule.FRAME_LENGTH


def _pcm(a: np.ndarray) -> bytes:
    return (np.clip(a, -1, 1) * 32767).astype("<i2").tobytes()


def _fan(i: int, rng) -> bytes:
    """稳态宽带噪声：风扇/空调。画面里"什么都没发生"，但频谱上很像清音。"""
    return _pcm(rng.normal(0, 0.05, _CHUNK))


def _silence(i: int, rng) -> bytes:
    return _pcm(rng.normal(0, 0.0005, _CHUNK))


def _speech(i: int, rng) -> bytes:
    """真人说话：音节包络 + 基频漂移 + 词间停顿。

    注意 ``t`` 必须**跨帧推进**。用 ``np.arange(_CHUNK)/_RATE`` 每帧从零开始的话，
    造出来的是一段一模一样的定频音 —— 能量毫无起伏，会被稳态噪声判别（棘轮破解）
    正确地归成噪声。那种样本证明不了任何事。
    """
    t = (i * _CHUNK + np.arange(_CHUNK)) / _RATE
    syllable = 0.5 + 0.5 * np.sin(2 * np.pi * 3.5 * t)
    word_gap = 0.0 if (i // 30) % 4 == 3 else 1.0  # 每 ~0.9s 停 ~0.9s
    f0 = 140 + 60 * np.sin(2 * np.pi * 0.7 * t)
    wave = np.sin(2 * np.pi * f0 * t) + 0.4 * np.sin(2 * np.pi * 2 * f0 * t)
    return _pcm(0.35 * syllable * word_gap * wave + rng.normal(0, 0.003, _CHUNK))


def _run_vad(gen, frames: int = 200):
    mod = VoiceWakeModule()
    assert mod._init_vad(), "VAD 初始化失败 —— 缺 numpy 或 core.multimodal.vad"
    rng = np.random.RandomState(0)
    return [mod._is_speech(gen(i, rng)) for i in range(frames)]


# ---------------------------------------------------------------------------
# 一、判据本身：稳态噪声不许把"有人在说话"焊死
# ---------------------------------------------------------------------------


def test_steady_fan_noise_does_not_stay_active_forever():
    """**这就是被修掉的那条。** 旧判据（webrtcvad 独断）在这里恒为 True。"""
    seq = _run_vad(_fan)
    settled = seq[50:]  # 前 ~0.8s 留给自适应噪声底爬上来
    assert not any(settled), f"噪声底适应之后仍有 {sum(settled)} 帧判成说话 —— 唤醒会被焊死"


def test_digital_silence_is_never_speech():
    assert not any(_run_vad(_silence)), "数字静音被判成说话了"


def test_real_speech_is_still_detected():
    """区分度：把噪声挡住不能靠"什么都判成没有"。"""
    seq = _run_vad(_speech)
    assert sum(seq) > len(seq) * 0.5, f"真人说话只判出 {sum(seq)}/{len(seq)} 帧 —— 挡过头了"


def test_speech_has_gaps_so_the_end_of_utterance_tick_can_fire():
    """识别唤醒词全靠"说话结束"那一拍，所以说话段必须真的会落下来。"""
    seq = _run_vad(_speech)
    assert any(seq) and not all(seq), "说话段没有起落，'说话结束'那一拍永远不会来"


def test_aggressiveness_comes_from_the_shared_config(monkeypatch):
    """原来这里写死 ``webrtcvad.Vad(2)``，``GALAXY_VAD_*`` 配了也不生效。"""
    monkeypatch.setenv("GALAXY_VAD_WEBRTC_AGGRESSIVENESS", "3")
    mod = VoiceWakeModule()
    assert mod._init_vad()
    assert mod._vad.config.webrtc_aggressiveness == 3, "唤醒链没读共享配置，又写死了"


def test_frame_duration_matches_this_modules_real_feed_rate():
    """本模块按 30ms/块投喂，不能沿用 VADConfig 面向采集管线的 100ms 默认。

    差 3 倍多的话，比率类指标的滚动窗口整体算长，判据行为跟着漂。
    """
    mod = VoiceWakeModule()
    assert mod._init_vad()
    assert mod._vad.config.frame_duration_ms == VoiceWakeModule.CHUNK_DURATION_MS


# ---------------------------------------------------------------------------
# 二、控制流兜底：判据坏掉了，唤醒也不许彻底哑掉
# ---------------------------------------------------------------------------


class _StubStream:
    def __init__(self, chunk_bytes: int):
        self._data = b"\x00\x01" * chunk_bytes

    def read(self, n, exception_on_overflow=False):
        return self._data


def _drive_loop(*, vad_verdict, ticks: int):
    """真的跑 ``_detect_loop``，只把 VAD 与音频源换成桩。

    数 ``_process_buffer`` 的调用次数 —— 那是识别唤醒词的唯一入口。
    """
    mod = VoiceWakeModule()
    mod._vad = object()  # 只要非 None，走 Strategy 2
    mod._porcupine = None
    mod._stream = _StubStream(_CHUNK)
    mod._running = True

    calls = []
    mod._process_buffer = lambda buf: calls.append(len(buf))

    n = {"i": 0}

    def _fake_is_speech(_data):
        n["i"] += 1
        if n["i"] >= ticks:
            mod._running = False
        return vad_verdict(n["i"])

    mod._is_speech = _fake_is_speech
    mod._detect_loop()
    return calls


def test_wake_still_fires_when_the_vad_is_stuck_active():
    """**兜底那一层。** VAD 恒判有声时，修复前是 0 次。

    60 秒 / 30ms = 2000 帧；BUFFER_MAX_MS=3000ms 即每 100 帧该强制转写一次。
    """
    ticks = 2000
    calls = _drive_loop(vad_verdict=lambda i: True, ticks=ticks)
    expected = ticks // (VoiceWakeModule.BUFFER_MAX_MS // VoiceWakeModule.CHUNK_DURATION_MS)
    assert calls, "VAD 恒判有声时唤醒彻底哑掉了 —— 兜底没生效"
    assert len(calls) >= expected - 1, f"该强制转写 ~{expected} 次，实际 {len(calls)} 次"


def test_normal_speech_pattern_still_processes_on_utterance_end():
    """区分度：兜底不能顶替正常路径。

    说 1.2s（40 帧）停 1.2s，每一轮都该在"说话结束"那一拍出一次结果，
    而不是攒到 3 秒才被兜底冲刷。
    """
    calls = _drive_loop(vad_verdict=lambda i: (i // 40) % 2 == 0, ticks=400)
    assert len(calls) >= 4, f"正常起落只出了 {len(calls)} 次结果"
    # 每段 40 帧 × 30ms = 1.2s < BUFFER_MAX_MS，所以都该走"说话结束"而不是兜底
    flush_bytes = _RATE * 2 * VoiceWakeModule.BUFFER_MAX_MS // 1000
    assert all(c < flush_bytes for c in calls), "正常说话被兜底冲刷接管了，说明'说话结束'那一拍没生效"


def test_no_processing_when_nobody_speaks():
    """没人说话就不该惊动 Whisper —— 否则兜底会变成无脑定时转写。"""
    assert _drive_loop(vad_verdict=lambda i: False, ticks=500) == []


def test_buffer_is_not_silently_truncated():
    """原来攒满就丢掉只留最后 1 秒 —— 那恰恰是把唤醒词悄悄扔掉。

    现在攒满是**先转写再清空**，所以每一次交给 ``_process_buffer`` 的缓冲都是
    完整的 ``BUFFER_MAX_MS``，不是被截断过的残段。

    第一句 assert 不能省：旧逻辑下一次都不会调用 ``_process_buffer``，
    ``all()`` 在空列表上恒真，这条会**假绿**。
    """
    flush_bytes = _RATE * 2 * VoiceWakeModule.BUFFER_MAX_MS // 1000
    calls = _drive_loop(vad_verdict=lambda i: True, ticks=300)
    assert calls, "一次都没转写 —— 缓冲被静默滚掉了"
    assert all(c == flush_bytes for c in calls), f"交出去的不是完整缓冲：{calls}（旧的截断逻辑留 {_RATE} 字节）"
