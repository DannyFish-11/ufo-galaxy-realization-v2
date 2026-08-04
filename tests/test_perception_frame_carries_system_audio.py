#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_perception_frame_carries_system_audio.py
========================================================
采集层收口第三步：**帧里有的东西，规范态必须看得见**。

这里钉三处真实断链，它们是同一条缝的三段：

A. 桥接把真实麦克风特征清零
   ``_desktop_perception_bridge_loop`` 见到 store 里有音频就写
   ``bus.update_audio(AudioState(), SignalQuality.ok())`` —— 一个**全零**状态
   （energy=0 / is_speaking=False）却标成 OK。共享麦克风管线刚写进去的真实特征
   被它周期性覆盖；而 ``core/continuum/human_field.py`` 正是拿 energy /
   speaking_ratio / is_speaking 去算注意力、疲劳与意图。于是"用户正在说话"
   会被抹成"安静且疲劳"——凭空捏造出来的人体场。

B. 系统播放声根本进不了常驻感知
   ``SystemAudioCaptureService`` 采到的回环声只写进 store，只有**每次请求**那条
   注入路径看得到。常驻感知帧（PerceptionFrame）里没有任何槽位承载它，于是
   注意力循环、三相状态机、模态路由这套"世界"完全不知道用户此刻在听什么。

C. 规范感知态无视整条连续路径
   ``build_canonical_perception_state`` 只从 continuous frame 取 audio/video/
   system 三项特征，**不读 screen**；而 ``requires_native_multimodal`` 只看
   请求侧的图像/音频。第 0 层刚把摄像头真帧接进常驻感知，规范态却照旧看不见 ——
   管子通了，判据还是瞎的。

判据一律走外部可观察结果：真推数据进 store、真跑桥接循环、真建帧、真建规范态。
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from core.continuum.human_field import HumanFieldInferrer
from core.multimodal.audio_features import AudioState
from core.multimodal.ingest_runtime import _desktop_perception_bridge_loop
from core.multimodal.ingress_bus import MultimodalIngressBus
from core.multimodal.perception_frame import PerceptionFrame, ScreenState, SystemAudioState
from core.multimodal.signal_quality import QualityFlag, SignalQuality
from core.multimodal.video_features import VideoState
from core.perception.canonical_perception_state import build_canonical_perception_state
from core.perception.desktop_perception_store import get_desktop_perception_store

_CAM = base64.b64encode(b"camera-frame-bytes-0001").decode()
_SCR = base64.b64encode(b"screen-frame-bytes-0001").decode()
_MIC = base64.b64encode(b"microphone-clip-0001").decode()
_SYS = base64.b64encode(b"system-loopback-clip-0001").decode()
_SYS2 = base64.b64encode(b"system-loopback-clip-XXXX-totally-different").decode()


@pytest.fixture(autouse=True)
def _clean_store():
    store = get_desktop_perception_store()
    store.resume(reason="test-setup")
    yield store
    store.resume(reason="test-teardown")


async def _run_bridge(bus: MultimodalIngressBus, seconds: float = 0.12) -> None:
    """真跑桥接循环，转几圈就取消（循环本体是无限的）。"""
    task = asyncio.get_running_loop().create_task(_desktop_perception_bridge_loop(bus, 0.01))
    await asyncio.sleep(seconds)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def _measured_speaking_state() -> AudioState:
    """一份**已测量**的真实麦克风特征（共享管线会写成这样）。"""
    return AudioState(
        energy=0.72,
        speaking_ratio=0.8,
        pause_density=0.1,
        noise_level=0.2,
        audio_freshness_ms=20.0,
        is_speaking=True,
    )


# ===========================================================================
# A、桥接不得把真实麦克风特征清零
# ===========================================================================


def test_bridge_does_not_clobber_measured_microphone_features() -> None:
    """管线已写入真实特征时，桥接那一拍不得把它抹成全零。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_audio(_MIC, mime="audio/webm")
        bus = MultimodalIngressBus()
        # 共享麦克风管线先写进真实特征（这是 add_callback(bus.update_audio) 的实况）
        bus.update_audio(_measured_speaking_state(), SignalQuality.ok())
        await _run_bridge(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.audio is not None, "麦克风模态整个消失了"
    assert frame.audio.is_speaking is True, "桥接把'正在说话'抹成了'没在说话'"
    assert frame.audio.energy == pytest.approx(0.72), "桥接把真实能量清零 —— 人体场会据此判定用户不在"


def test_presence_only_audio_is_marked_unmeasured_not_silent() -> None:
    """没有本机特征管线时只能如实报"在场但未测量"，不得谎称"能量为零"。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_audio(_MIC, mime="audio/webm")
        bus = MultimodalIngressBus()
        await _run_bridge(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.audio is not None, "壳上报了麦克风在场，常驻感知却完全不知道"
    assert frame.audio.features_measured is False, "未测量的占位特征被标成了已测量 —— 下游会当真"
    assert frame.audio_quality.flag is not QualityFlag.OK, "未测量却打了 OK 质量标"


def test_human_field_does_not_fabricate_silence_from_unmeasured_audio() -> None:
    """未测量的音频不得参与人体场打分 —— 判据是"与完全没有音频时一模一样"。"""
    est = HumanFieldInferrer()

    unmeasured = PerceptionFrame(
        audio=AudioState(features_measured=False),
        audio_quality=SignalQuality.degraded("presence only"),
    )
    no_audio = PerceptionFrame()  # audio_quality 默认 missing

    a = est.infer(unmeasured)
    b = est.infer(no_audio)
    assert (a.attention, a.fatigue, a.intent_probability) == (
        b.attention,
        b.fatigue,
        b.intent_probability,
    ), "未测量的占位音频被当成'安静'参与打分，凭空造出注意力/疲劳/意图"


def test_measured_audio_still_moves_the_human_field() -> None:
    """对照组：**已测量**的说话状态必须真的抬高意图概率，否则上一条是空断言。"""
    est = HumanFieldInferrer()
    speaking = est.infer(PerceptionFrame(audio=_measured_speaking_state(), audio_quality=SignalQuality.ok()))
    silent = est.infer(PerceptionFrame())
    assert speaking.intent_probability > silent.intent_probability, "已测量的说话状态对人体场毫无影响"


# ===========================================================================
# B、系统播放声进入常驻感知帧
# ===========================================================================


def test_system_audio_reaches_perception_frame() -> None:
    """推一段回环声 → 常驻感知帧里必须有它（含本体，供原生多模态直接听）。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_system_audio(_SYS, mime="audio/wav")
        bus = MultimodalIngressBus()
        await _run_bridge(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.system_audio is not None, "系统播放声没有进入常驻感知 —— 世界里没有'用户在听什么'"
    assert frame.system_audio.has_audio is True
    assert frame.system_audio.audio_b64 == _SYS, "只报了在场，声音本体被丢在门外"
    assert frame.system_audio.mime == "audio/wav"
    assert "system_audio" in frame.active_modalities


def test_system_audio_does_not_collide_with_microphone_slot() -> None:
    """麦克风与系统声必须分槽：混一槽就再也分不出'人在说'还是'扬声器在放'。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_system_audio(_SYS, mime="audio/wav")
        bus = MultimodalIngressBus()
        bus.update_audio(_measured_speaking_state(), SignalQuality.ok())
        await _run_bridge(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.audio is not None and frame.audio.is_speaking is True, "系统声把麦克风槽覆盖了"
    assert frame.system_audio is not None and frame.system_audio.audio_b64 == _SYS


def test_frame_dict_never_carries_raw_system_audio_base64() -> None:
    """与屏幕/摄像头同规：序列化只暴露存在性与变化，不带本体（日志会爆量）。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_system_audio(_SYS, mime="audio/wav")
        bus = MultimodalIngressBus()
        await _run_bridge(bus)
        return bus.build_frame().to_dict()

    d = asyncio.run(_run())
    assert _SYS not in repr(d), "帧字典把系统播放声本体带出去了"
    assert d["system_audio"]["has_audio"] is True
    assert "change_seq" in d["system_audio"]


def test_system_audio_change_seq_only_advances_on_real_change() -> None:
    """同一段声音重复推送不得让序号乱跳；换一段才 +1（慢节拍消费者据此判断）。"""

    async def _run():
        store = get_desktop_perception_store()
        bus = MultimodalIngressBus()
        store.update_system_audio(_SYS, mime="audio/wav")
        task = asyncio.get_running_loop().create_task(_desktop_perception_bridge_loop(bus, 0.01))
        await asyncio.sleep(0.10)
        seq_same = bus.build_frame().system_audio.change_seq
        store.update_system_audio(_SYS2, mime="audio/wav")
        await asyncio.sleep(0.10)
        seq_changed = bus.build_frame().system_audio.change_seq
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return seq_same, seq_changed

    seq_same, seq_changed = asyncio.run(_run())
    assert seq_changed > seq_same, "换了一段声音，变化序号却没动 —— 慢节拍消费者永远看不到新内容"


def test_privacy_pause_keeps_system_audio_out_of_perception() -> None:
    """隐私急停后系统播放声不得再进帧 —— 它比麦克风更敏感。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_system_audio(_SYS, mime="audio/wav")
        bus = MultimodalIngressBus()
        await _run_bridge(bus)
        store.pause(reason="test-privacy")
        bus2 = MultimodalIngressBus()
        await _run_bridge(bus2)
        return bus2.build_frame()

    frame = asyncio.run(_run())
    assert frame.system_audio is None or not frame.system_audio.has_audio, "隐私暂停期间系统播放声仍在进帧"


# ===========================================================================
# C、规范感知态必须看得见连续路径
# ===========================================================================


def _cps(frame: PerceptionFrame) -> dict:
    return build_canonical_perception_state(continuous_frame=frame).to_dict()


def test_continuous_camera_image_requires_native_multimodal() -> None:
    """连续路径上有真实摄像头画面 → 规范态必须要求原生多模态模型。"""
    frame = PerceptionFrame(
        video=VideoState(image_b64=_CAM, has_image=True),
        video_quality=SignalQuality.ok(),
    )
    state = _cps(frame)
    assert state["requires_native_multimodal"] is True, "帧里有画面，规范态却认为不需要原生多模态 —— 路由会挑个瞎子模型"


def test_continuous_screen_reaches_canonical_state() -> None:
    """连续屏幕感知必须进规范态的 screen_summary，而不是只有请求侧才算数。"""
    frame = PerceptionFrame(
        screen=ScreenState(image_b64=_SCR, has_image=True, change_seq=3),
        screen_quality=SignalQuality.ok(),
    )
    state = _cps(frame)
    assert state["screen_summary"], "连续屏幕感知在规范态里整个消失"
    assert state["screen_summary"].get("source") == "continuous"
    assert state["requires_native_multimodal"] is True


def test_continuous_system_audio_reaches_canonical_state() -> None:
    """系统播放声必须在规范态里可见，且与麦克风区分开。"""
    frame = PerceptionFrame(
        system_audio=SystemAudioState(audio_b64=_SYS, has_audio=True),
        system_audio_quality=SignalQuality.ok(),
    )
    state = _cps(frame)
    assert "system_audio" in state["active_modalities"], "规范态不知道用户正在听东西"
    assert state["system_audio_summary"], "系统播放声没有摘要"
    assert state["system_audio_summary"].get("source") == "continuous"
    assert state["requires_native_multimodal"] is True


def test_featureless_continuous_frame_does_not_require_native_multimodal() -> None:
    """对照组：只有派生特征、没有任何本体的连续帧不得触发原生多模态要求，
    否则这个判据恒为真、等于没有。"""
    frame = PerceptionFrame(
        audio=_measured_speaking_state(),
        audio_quality=SignalQuality.ok(),
        video=VideoState(motion_level=0.4),  # 有运动特征但没有画面本体
        video_quality=SignalQuality.ok(),
    )
    state = _cps(frame)
    assert state["requires_native_multimodal"] is False, "没有任何本体也要求原生多模态 —— 判据恒真"


def test_canonical_state_never_leaks_raw_payloads() -> None:
    """规范态是要进日志与响应元数据的：不得夹带任何本体 base64。"""
    frame = PerceptionFrame(
        video=VideoState(image_b64=_CAM, has_image=True),
        video_quality=SignalQuality.ok(),
        screen=ScreenState(image_b64=_SCR, has_image=True),
        screen_quality=SignalQuality.ok(),
        system_audio=SystemAudioState(audio_b64=_SYS, has_audio=True),
        system_audio_quality=SignalQuality.ok(),
    )
    blob = repr(_cps(frame))
    for payload, name in ((_CAM, "摄像头"), (_SCR, "屏幕"), (_SYS, "系统播放声")):
        assert payload not in blob, f"规范态把{name}本体带进了日志"
