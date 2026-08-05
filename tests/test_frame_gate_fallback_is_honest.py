#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_frame_gate_fallback_is_honest.py

钉住：**字节兜底路径不许发布一个假的"变化幅度"**。

背景
====
``FrameGate.score()`` 有两条路径。指纹路径（PIL 下采样成 16x16 灰度求归一化平均
像素差）是准的。字节兜底路径原来把 ``1 - byte_similarity()`` 直接当作变化度发布，
注释写着"与指纹路径同一量纲语义"，并用**写死的** ``sim < 0.995``（等价
``diff > 0.005``）判变化 —— 完全不看 ``self.threshold``，于是
``GALAXY_AMBIENT_DIFF_THRESHOLD`` 配了也不生效。

但真正的问题比"阈值没生效"更深。按真实采集管线（**固定**编码质量）实测：

===============================  ===========  ===========
场景                              字节 diff     指纹 diff
===============================  ===========  ===========
屏幕静止（字节完全相同）             0.0000       0.0000
摄像头传感器噪声，画面没变           0.6233       0.0022
摄像头噪声 σ=6，画面没变            0.8185       0.0020
弹出对话框（真变化 ~22%）           0.3766       0.1197
换了一整屏（真变化）                0.4215       0.0948
===============================  ===========  ===========

**噪声（0.62/0.82）比真实变化（0.38/0.42）分数还高。** 这不是阈值调不对，是这个量
在有损压缩帧上根本不携带"变化幅度"的信息 —— 任何阈值都分不开。而它恰恰在解码失败
时被触发，也就是摄像头正在产出坏帧的时候。

处置：只保留它**确实可靠**的那一位（字节完全相同 ⇒ 一定没变），其余按"变了"处理
（宁可多惊动模型一次，也不能悄悄丢掉一次真变化），分数给 0/1 而不是编一个幅度，
并把"这是降级值"这一位一路带到消费方。

注：既有的 14 条「采集层单一门控」测试改前改后都通过 —— 它们钉的是"只有一处实现"，
而分歧就住在那一处实现的内部。
"""

from __future__ import annotations

import base64
import io
import math
import struct

import numpy as np
import pytest
from PIL import Image

from core.multimodal.frame_gate import DEFAULT_DIFF_THRESHOLD, FrameGate, signature_or_reason

_JPEG_QUALITY = 85  # 真实管线里编码质量是固定的


def _jpeg(*, noise: float = 0.0, dialog: bool = False, seed: int = 1) -> str:
    """造一帧「桌面截图」。noise 模拟摄像头传感器噪声（画面内容不变）。"""
    rng = np.random.RandomState(seed)
    arr = np.full((480, 640, 3), 45, dtype=np.float32)
    arr[:60] = 78
    for _ in range(20):
        x, y = rng.randint(0, 560), rng.randint(70, 420)
        arr[y : y + 50, x : x + 70] = rng.randint(60, 190, 3)
    if dialog:
        arr[160:320, 160:480] = 245
    if noise:
        arr = arr + np.random.RandomState(seed + 999).normal(0, noise, arr.shape)
    buf = io.BytesIO()
    Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).save(buf, "JPEG", quality=_JPEG_QUALITY)
    return base64.b64encode(buf.getvalue()).decode()


def _wav(freq: float, *, amp: float = 0.4, secs: float = 0.2, rate: int = 16000) -> str:
    n = int(rate * secs)
    frames = b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))
    header = (
        b"RIFF"
        + struct.pack("<I", 36 + len(frames))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data"
        + struct.pack("<I", len(frames))
    )
    return base64.b64encode(header + frames).decode()


def _corrupt(tag: bytes) -> str:
    """解不开的负载 —— 真实成因是截断帧/坏帧，这里用等价物触发同一条路径。"""
    return base64.b64encode(b"NOT-AN-IMAGE-" + tag).decode()


# ---------------------------------------------------------------------------
# 一、这条缺陷本身：兜底路径不许给"没变"打出比"真变了"更高的分
# ---------------------------------------------------------------------------


def test_fallback_never_ranks_noise_above_a_real_change():
    """旧口径下这一条必然失败：噪声 0.62/0.82 > 真变化 0.38/0.42。"""
    gate = FrameGate()
    gate.score(_corrupt(b"seed"))

    gate.score(_corrupt(b"seed"))
    same = gate.last_score
    gate.score(_corrupt(b"different-payload"))
    changed = gate.last_score

    assert same == 0.0, f"字节完全相同却报了变化：{same}"
    assert changed > same, "兜底下'变了'必须严格高于'没变'"
    assert changed == 1.0, f"兜底只应给 0/1，不许编幅度：{changed}"


def test_fallback_marks_itself_as_degraded():
    """消费方要能分出"这是幅度"和"这只是变没变"。"""
    gate = FrameGate()
    gate.score(_corrupt(b"a"))
    assert gate.degraded is True
    assert gate.degraded_reason == "decode_failed"

    gate2 = FrameGate()
    gate2.score(_jpeg())
    gate2.score(_jpeg(dialog=True))
    assert gate2.degraded is False, "指纹路径不该被标成降级"
    assert gate2.degraded_reason == ""


def test_degraded_reason_separates_deployment_from_runtime_failure():
    """依赖缺失（部署问题）与解码失败（摄像头在产垃圾）此前被压成同一个 None。"""
    sig, reason = signature_or_reason(_jpeg())
    assert sig is not None and reason == ""

    sig2, reason2 = signature_or_reason(_corrupt(b"x"))
    assert sig2 is None and reason2 == "decode_failed"


# ---------------------------------------------------------------------------
# 二、判据要有区分度：主路径必须**不受影响**
# ---------------------------------------------------------------------------


def test_perceptual_path_still_measures_magnitude():
    """本次改动只动兜底。主路径仍然给真实幅度，且能把噪声和真变化分开。

    这一条是区分度证明：如果有人把 0/1 的做法误推到主路径上，它会红。
    """
    base = _jpeg()

    quiet = FrameGate()
    quiet.score(base)
    quiet.score(_jpeg(noise=6))
    assert quiet.last_score < DEFAULT_DIFF_THRESHOLD, f"传感器噪声被判成了变化：{quiet.last_score}"
    assert 0.0 < quiet.last_score < 0.02, f"主路径应给出真实的小幅度，而不是 0/1：{quiet.last_score}"

    loud = FrameGate()
    loud.score(base)
    loud.score(_jpeg(dialog=True))
    assert loud.last_score > DEFAULT_DIFF_THRESHOLD, f"弹出对话框没被判成变化：{loud.last_score}"
    assert loud.last_score > quiet.last_score * 10, "主路径必须把真变化和噪声拉开量级"


@pytest.mark.parametrize(
    "label,pct,should_fire",
    [("5% 面积", 5, False), ("10% 面积", 10, True), ("30% 面积", 30, True)],
)
def test_default_threshold_fires_on_realistic_screen_changes(label, pct, should_fire):
    """把 0.06 这个默认值本身钉住 —— 它是主路径唯一的可调判据。

    实测：≥10% 面积的窗口变化触发，5% 不触发。改这个默认值前先看这条。
    """
    buf = io.BytesIO()
    base_img = Image.new("RGB", (640, 480), (40, 44, 52))
    base_img.save(buf, "JPEG", quality=_JPEG_QUALITY)
    base = base64.b64encode(buf.getvalue()).decode()

    img = base_img.copy()
    from PIL import ImageDraw

    ImageDraw.Draw(img).rectangle([0, 0, 640, int(480 * pct / 100)], fill=(240, 240, 240))
    buf2 = io.BytesIO()
    img.save(buf2, "JPEG", quality=_JPEG_QUALITY)

    gate = FrameGate()
    gate.score(base)
    before = gate.change_seq
    gate.score(base64.b64encode(buf2.getvalue()).decode())
    assert (gate.change_seq != before) is should_fire, f"{label}: score={gate.last_score:.4f}"


# ---------------------------------------------------------------------------
# 三、音频走的是同一条兜底 —— 0/1 语义对它同样成立
# ---------------------------------------------------------------------------


def test_audio_goes_through_the_fallback_and_still_works():
    """``perceptual_signature`` 是图像解码，音频必然返回 None。

    音频这一档反而是好的：内容相同则字节相同。0/1 语义保住了它。
    """
    assert signature_or_reason(_wav(440))[0] is None

    gate = FrameGate()
    gate.score(_wav(440))

    gate.score(_wav(440))
    assert gate.last_score == 0.0, "同一段音频被判成变化了"

    seq_before = gate.change_seq
    gate.score(_wav(0, amp=0.0))
    assert gate.last_score == 1.0 and gate.change_seq != seq_before, "说完话转静音没被判成变化"


# ---------------------------------------------------------------------------
# 四、降级位要一路带到消费方
# ---------------------------------------------------------------------------


def test_degraded_bit_reaches_the_perception_frame():
    """帧上没有这一位的话，下游只能看到一个 0/1 的分数却以为是幅度。"""
    from core.multimodal.perception_frame import PerceptionFrame, ScreenState, SystemAudioState
    from core.multimodal.video_features import VideoState

    for state_cls in (ScreenState, SystemAudioState, VideoState):
        assert hasattr(state_cls(), "change_score_degraded"), f"{state_cls.__name__} 缺降级位"

    frame = PerceptionFrame()
    frame.screen = ScreenState(change_score=1.0, change_seq=3, change_score_degraded=True, has_image=True)
    payload = frame.to_dict()
    assert payload["screen"]["change_score_degraded"] is True, "降级位没进 to_dict —— 出了进程就丢了"
