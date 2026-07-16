"""tests/test_ambient_fusion.py
=================================
ambient 在场循环【融合看】:每拍同时把屏幕+摄像头两路发给决策脑(此前只发一路),
且是否附图由统一模态协商层(vision 可用性)驱动——换无视觉模型自动省图。
摄像头单独变化也能触发(两路各一个门控)。

不依赖 PIL(用字节级门控路径)、不触网、不加载真实模型。
"""

from __future__ import annotations

import core.ambient_attention_loop as aal
from core.ambient_attention_loop import AmbientObservation, LLMRouterDecider


def _imgs(messages):
    """从 messages 抽出所有 image_url 的 base64 段。"""
    content = messages[0]["content"]
    if not isinstance(content, list):
        return []
    return [p["image_url"]["url"] for p in content if p.get("type") == "image_url"]


# ── 融合:两路都发 ────────────────────────────────────────────────────────────


def test_build_messages_sends_both_screen_and_camera(monkeypatch):
    monkeypatch.setattr(LLMRouterDecider, "_vision_usable", staticmethod(lambda: True))
    d = LLMRouterDecider(router=object())
    obs = AmbientObservation(
        frame_b64="SCREEN", screen_b64="SCREEN", camera_b64="CAMERA", frame_source="desktop_screen"
    )
    msgs = d._build_messages(obs)
    urls = _imgs(msgs)
    assert any("SCREEN" in u for u in urls) and any("CAMERA" in u for u in urls)
    assert len(urls) == 2  # 两路都发,不是只发一路


def test_build_messages_legacy_single_frame_still_works(monkeypatch):
    # 调用方只塞 frame_b64(未分路)→ 仍发主帧(向后兼容)
    monkeypatch.setattr(LLMRouterDecider, "_vision_usable", staticmethod(lambda: True))
    d = LLMRouterDecider(router=object())
    obs = AmbientObservation(frame_b64="ONLYFRAME")
    urls = _imgs(d._build_messages(obs))
    assert len(urls) == 1 and "ONLYFRAME" in urls[0]


# ── 协商层驱动:无视觉模型自动省图 ────────────────────────────────────────────


def test_build_messages_skips_images_when_vision_unavailable(monkeypatch):
    monkeypatch.setattr(LLMRouterDecider, "_vision_usable", staticmethod(lambda: False))
    d = LLMRouterDecider(router=object())
    obs = AmbientObservation(frame_b64="SCREEN", screen_b64="SCREEN", camera_b64="CAMERA")
    msgs = d._build_messages(obs)
    assert _imgs(msgs) == []  # 瞎子不发图
    assert isinstance(msgs[0]["content"], str)  # 退化为纯文本


def test_vision_usable_consults_negotiator(monkeypatch):
    import core.modality_capability as mc

    monkeypatch.setattr(
        "core.modality_capability.negotiate",
        lambda **k: mc.ModalityPlan(
            vision_in=mc.ModalityResolution(mc.VISION_IN, "unavailable", ""),
            audio_in=mc.ModalityResolution(mc.AUDIO_IN, "bridge", ""),
            audio_out=mc.ModalityResolution(mc.AUDIO_OUT, "bridge", ""),
            video_in=mc.ModalityResolution(mc.VIDEO_IN, "unavailable", ""),
        ),
    )
    assert LLMRouterDecider._vision_usable() is False


def test_vision_usable_defaults_true_when_negotiator_errors(monkeypatch):
    def _boom(**k):
        raise RuntimeError("x")

    monkeypatch.setattr("core.modality_capability.negotiate", _boom)
    assert LLMRouterDecider._vision_usable() is True  # 协商挂了不回退视觉


# ── 分路门控:摄像头单独变化也触发 ────────────────────────────────────────────


class _FakeStore:
    def __init__(self, media):
        self._media = media

    def snapshot_media(self):
        return dict(self._media)


def _loop(media):
    lp = aal.AmbientAttentionLoop(perception_store=_FakeStore(media), cooldown_s=0.0, interval_s=0.1)
    return lp


def test_gather_populates_both_streams():
    lp = _loop({"screen_b64": "S1", "camera_b64": "C1", "screen_mime": "image/jpeg"})
    obs = lp._gather_observation()
    assert obs is not None
    assert obs.screen_b64 == "S1" and obs.camera_b64 == "C1"
    assert obs.frame_b64 == "S1"  # 主帧屏幕优先


def test_camera_only_change_triggers():
    lp = _loop({"camera_b64": "CAM_FIRST"})
    assert lp._gather_observation() is not None  # 第一帧算变化
    # 摄像头帧变化(无屏幕)→ 第二路门控应触发
    lp._store = _FakeStore({"camera_b64": "CAM_SECOND_totally_different_bytes_xxxxxxxxxxxxxxxx"})
    assert lp._gather_observation() is not None


def test_no_change_skips():
    same = "SAME_FRAME_BYTES_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    lp = _loop({"screen_b64": same})
    assert lp._gather_observation() is not None  # 第一帧
    lp._store = _FakeStore({"screen_b64": same})  # 完全一样
    assert lp._gather_observation() is None  # 没变 → 跳过
