"""tests/test_video_frame_sampling.py
=========================================
D:视频抽帧自适配——连续视频 → 视觉路,由统一模态协商层(video_in 三态)驱动。

验证 resolve_video_in / resolve_video_sampling 三态:
  - unavailable(当前档位无视觉)→ 不抽(should_sample=False),省算力;
  - frames_bridge(有静态视觉、无原生视频)→ 抽稀疏静帧喂视觉;
  - native(GALAXY_NATIVE_VIDEO + 模型原生视频)→ 送更密的连续帧。
并验证 vision_sampler.run_sampling_session 在"无视觉"时【提前跳过】——不碰
Node_95、不真抽帧。全部注入协商替身,不触网、不加载真实模型。
"""

from __future__ import annotations

import asyncio

import core.modality_bridge as mb
import core.modality_capability as mc


def _plan(video_mode):
    """构造一个 video_in=video_mode 的 ModalityPlan 替身。"""
    return mc.ModalityPlan(
        vision_in=mc.ModalityResolution(mc.VISION_IN, "native" if video_mode != "unavailable" else "unavailable", ""),
        audio_in=mc.ModalityResolution(mc.AUDIO_IN, "bridge", ""),
        audio_out=mc.ModalityResolution(mc.AUDIO_OUT, "bridge", ""),
        video_in=mc.ModalityResolution(mc.VIDEO_IN, video_mode, ""),
    )


# ── resolve_video_in:三态映射 ────────────────────────────────────────────────


def test_resolve_video_in_native(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("native"))
    assert mb.resolve_video_in() == "native"


def test_resolve_video_in_bridge(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("bridge"))
    assert mb.resolve_video_in() == "frames_bridge"


def test_resolve_video_in_unavailable(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("unavailable"))
    assert mb.resolve_video_in() == "unavailable"


def test_resolve_video_in_survives_negotiator_boom(monkeypatch):
    def _boom(**k):
        raise RuntimeError("negotiator down")

    monkeypatch.setattr(mc, "negotiate", _boom)
    # 协商层塌了也别崩,退回 frames_bridge(有静态视觉时最保守可用形态)
    assert mb.resolve_video_in() == "frames_bridge"


# ── resolve_video_sampling:抽帧决策 ──────────────────────────────────────────


def test_sampling_unavailable_means_no_sample(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("unavailable"))
    should, fps, mode = mb.resolve_video_sampling()
    assert should is False and fps == 0.0 and mode == "unavailable"


def test_sampling_bridge_uses_sparse_default(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("bridge"))
    monkeypatch.setattr(mb, "_VIDEO_FPS_BRIDGE", 1.0)
    monkeypatch.setattr(mb, "_VIDEO_FPS_NATIVE", 4.0)
    should, fps, mode = mb.resolve_video_sampling()
    assert should is True and fps == 1.0 and mode == "frames_bridge"


def test_sampling_native_uses_denser_default(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("native"))
    monkeypatch.setattr(mb, "_VIDEO_FPS_BRIDGE", 1.0)
    monkeypatch.setattr(mb, "_VIDEO_FPS_NATIVE", 4.0)
    should, fps, mode = mb.resolve_video_sampling()
    assert should is True and fps == 4.0 and mode == "native"


def test_sampling_explicit_fps_respected(monkeypatch):
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("bridge"))
    should, fps, mode = mb.resolve_video_sampling(requested_fps=7.0)
    assert should is True and fps == 7.0  # 调用方硬要 7 fps → 尊重


def test_sampling_explicit_fps_still_gated_by_unavailable(monkeypatch):
    # 关键:即便调用方硬传 fps,当前档位没视觉也一律不抽(喂盲模型是浪费)
    monkeypatch.setattr(mc, "negotiate", lambda **k: _plan("unavailable"))
    should, fps, mode = mb.resolve_video_sampling(requested_fps=7.0)
    assert should is False and mode == "unavailable"


# ── vision_sampler:无视觉时提前跳过,不碰 Node_95 ────────────────────────────


def test_run_sampling_skips_when_no_vision(monkeypatch):
    import core.services.vision_sampler as vs

    monkeypatch.setattr("core.modality_bridge.resolve_video_sampling", lambda f: (False, 0.0, "unavailable"))
    out = asyncio.run(vs.run_sampling_session(device_id="dev1", duration=5.0))
    assert out["success"] is False
    assert out["frames_sampled"] == 0
    assert out["video_mode"] == "unavailable"
    assert "跳过" in out["reason"]  # 明确告知是"自适配跳过",不是 Node_95 挂了
