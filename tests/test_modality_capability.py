"""tests/test_modality_capability.py
======================================
统一模态能力协商层:换模型自动适配(有音频的走原生/没音频的自动走桥),
每模态三态 native/bridge/unavailable,服务门控与桥可用性分开。

全部注入 EffectiveIO 替身,不加载真实模型、不触网。
"""

from __future__ import annotations

from dataclasses import dataclass

import core.modality_capability as mc
from core.modality_capability import negotiate


@dataclass
class _IO:
    """EffectiveIO 替身。"""

    vision: str = "none"
    audio_in: str = "asr_bridge"
    audio_out: str = "tts_bridge"
    video: str = "none"


# ── 自适配核心:同一套逻辑,换模型 → 计划自动变 ──────────────────────────────


def test_audio_model_native_when_serving_on(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_AUDIO", "1")
    io = _IO(audio_in="native", audio_out="native", vision="native")
    plan = negotiate(effio=io, asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "native"
    assert plan.audio_out.mode == "native"
    assert plan.audio_in.native_capable is True


def test_audio_model_but_serving_off_falls_to_bridge(monkeypatch):
    # 模型有音频能力,但全模态服务没开 → 自动走 ASR/TTS 桥(不是不可用)
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    io = _IO(audio_in="native", audio_out="native")
    plan = negotiate(effio=io, asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "bridge" and plan.audio_in.native_capable is True
    assert plan.audio_out.mode == "bridge" and plan.audio_out.native_capable is True


def test_model_without_audio_uses_bridge(monkeypatch):
    # 换一个没有原生音频的模型 → 自动走桥,零改动
    monkeypatch.delenv("GALAXY_NATIVE_AUDIO", raising=False)
    io = _IO(audio_in="asr_bridge", audio_out="tts_bridge")
    plan = negotiate(effio=io, asr_available=True, tts_available=True)
    assert plan.audio_in.mode == "bridge" and plan.audio_in.native_capable is False
    assert plan.audio_out.mode == "bridge" and plan.audio_out.native_capable is False


def test_no_asr_installed_audio_in_unavailable():
    io = _IO(audio_in="asr_bridge")
    plan = negotiate(effio=io, asr_available=False, tts_available=True)
    assert plan.audio_in.mode == "unavailable"
    assert "ASR" in plan.audio_in.reason


# ── 视觉 ──────────────────────────────────────────────────────────────────────


def test_vision_native_when_model_sees():
    plan = negotiate(effio=_IO(vision="native"), asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "native"


def test_vision_unavailable_without_vision_model():
    plan = negotiate(effio=_IO(vision="none"), asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"


# ── 视频 ──────────────────────────────────────────────────────────────────────


def test_video_frames_bridge_when_only_stills(monkeypatch):
    # 有静帧视觉但无原生视频 → 抽帧走视觉(bridge),不谎报也不彻底放弃
    monkeypatch.delenv("GALAXY_NATIVE_VIDEO", raising=False)
    plan = negotiate(effio=_IO(vision="native", video="frames_bridge"), asr_available=True, tts_available=True)
    assert plan.video_in.mode == "bridge"


def test_video_native_when_serving_on(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_VIDEO", "1")
    plan = negotiate(effio=_IO(vision="native", video="native"), asr_available=True, tts_available=True)
    assert plan.video_in.mode == "native"


def test_video_unavailable_without_any_vision():
    plan = negotiate(effio=_IO(vision="none", video="none"), asr_available=True, tts_available=True)
    assert plan.video_in.mode == "unavailable"


# ── 韧性 & 收口 ───────────────────────────────────────────────────────────────


def test_negotiate_survives_missing_capability_source(monkeypatch):
    # 能力源整个抛异常 → 不崩,给最保守计划(视觉/视频不可用,听说尽量走桥)
    def _boom(*a, **k):
        raise RuntimeError("catalog unavailable")

    monkeypatch.setattr("core.model_catalog.active_effective_io", _boom)
    monkeypatch.setattr("core.model_catalog.tier_effective_io", _boom)
    plan = negotiate(effio=None, asr_available=True, tts_available=True)
    assert plan.vision_in.mode == "unavailable"
    assert plan.audio_in.mode in ("bridge", "unavailable")


def test_negotiate_none_effio_uses_real_catalog():
    # effio=None 且 catalog 可用 → 用真实当前档位(默认档位含视觉 → native)
    plan = negotiate(effio=None, asr_available=True, tts_available=True)
    assert plan.vision_in.mode in ("native", "unavailable")  # 取决于当前档位,不抛即可


def test_plan_to_dict_shape():
    plan = negotiate(effio=_IO(vision="native"), asr_available=True, tts_available=True)
    d = plan.to_dict()
    assert set(d) >= {"vision_in", "audio_in", "audio_out", "video_in"}
    assert d["vision_in"]["mode"] == "native" and d["vision_in"]["usable"] is True


def test_modality_matrix_endpoint_lists_both_tiers():
    import asyncio

    import core.routes.modality as route

    out = asyncio.run(route.modality_matrix())
    assert out["success"] is True
    keys = {t["tier"] for t in out["tiers"]}
    assert {"A", "B"} <= keys  # 两档都在
    for t in out["tiers"]:
        assert set(t["plan"]) >= {"vision_in", "audio_in", "audio_out", "video_in"}
    assert sum(1 for t in out["tiers"] if t["active"]) == 1  # 恰一个 active


def test_model_catalog_video_capability_field():
    # video 能力字段确实进了 catalog 的能力矩阵(一个不落)
    from core.model_catalog import ModelCapability

    assert ModelCapability(video=True).to_dict()["video"] is True
    assert ModelCapability().to_dict()["video"] is False  # 默认 False,不破坏既有声明


def test_modality_bridge_delegates_to_negotiator(monkeypatch):
    # 收口验证:modality_bridge.resolve_audio_in/out 委托统一协商层,不再各自读 catalog
    import core.modality_bridge as mb

    monkeypatch.setattr(
        "core.modality_capability.negotiate",
        lambda **kw: mc.ModalityPlan(
            vision_in=mc.ModalityResolution(mc.VISION_IN, "native", ""),
            audio_in=mc.ModalityResolution(mc.AUDIO_IN, "native", ""),
            audio_out=mc.ModalityResolution(mc.AUDIO_OUT, "bridge", ""),
            video_in=mc.ModalityResolution(mc.VIDEO_IN, "unavailable", ""),
        ),
    )
    assert mb.resolve_audio_in() == "native"
    assert mb.resolve_audio_out() == "tts_bridge"  # bridge → 历史返回值
