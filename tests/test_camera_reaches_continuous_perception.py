#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_camera_reaches_continuous_perception.py
=======================================================
摄像头画面必须真的进入**常驻感知**（MultimodalIngressBus），而不是只报一个"在场"。

断链原文：``ingest_runtime`` 的桌面桥对屏幕传 ``ScreenState(image_b64=...)``，
对摄像头却传 ``VideoState()`` 空壳 —— 画面被丢在门外。而常驻感知这份"世界"
正是注意力循环、三相状态机与模态路由共同消费的输入，缺一路即残缺现实。

判据一律是外部可观察结果：真的推一帧摄像头进 store，真的跑桥接循环，
然后从 bus 产出的 PerceptionFrame 里取到画面本体。
"""

from __future__ import annotations

import asyncio
import base64

import pytest

from core.multimodal.ingest_runtime import _desktop_perception_bridge_loop
from core.multimodal.ingress_bus import MultimodalIngressBus
from core.perception.desktop_perception_store import get_desktop_perception_store

_CAM = base64.b64encode(b"camera-frame-bytes-0001").decode()
_SCR = base64.b64encode(b"screen-frame-bytes-0001").decode()


@pytest.fixture(autouse=True)
def _clean_store():
    store = get_desktop_perception_store()
    store.resume(reason="test-setup")
    yield store
    store.resume(reason="test-teardown")


async def _one_bridge_tick(bus: MultimodalIngressBus) -> None:
    """真跑桥接循环，转一圈就取消（循环本体是无限的）。"""
    task = asyncio.get_running_loop().create_task(_desktop_perception_bridge_loop(bus, 0.01))
    await asyncio.sleep(0.12)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_camera_frame_reaches_perception_frame() -> None:
    """推一帧摄像头 → 常驻感知帧里必须有画面本体（不是空壳）。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_frame(_CAM, source="desktop_camera")
        bus = MultimodalIngressBus()
        await _one_bridge_tick(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.video is not None, "摄像头帧没有进入常驻感知 —— 桥接仍在丢画面"
    assert frame.video.has_image is True
    assert frame.video.image_b64 == _CAM, "常驻感知里的摄像头画面与推入的不一致"


def test_camera_and_screen_do_not_cross_slots() -> None:
    """屏幕与摄像头分槽：两路各归其位，绝不串槽。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_frame(_CAM, source="desktop_camera")
        store.update_frame(_SCR, source="desktop_screen", screen={"w": 1})
        bus = MultimodalIngressBus()
        await _one_bridge_tick(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.video is not None and frame.screen is not None
    assert frame.video.image_b64 == _CAM
    assert frame.screen.image_b64 == _SCR


def test_privacy_pause_keeps_camera_out_of_perception() -> None:
    """隐私暂停期间摄像头帧在写入口就被挡 → 常驻感知里不得出现画面。

    这条同时证明新链路仍受**同一个**隐私闸门约束，没有另开旁路。
    """

    async def _run():
        store = get_desktop_perception_store()
        store.pause(reason="test")
        store.update_frame(_CAM, source="desktop_camera")  # 应被拒收
        bus = MultimodalIngressBus()
        await _one_bridge_tick(bus)
        return bus.build_frame()

    frame = asyncio.run(_run())
    assert frame.video is None or not frame.video.has_image, "隐私暂停期间摄像头画面仍进了常驻感知"


def test_frame_dict_never_carries_raw_camera_base64() -> None:
    """序列化体不得带原始 base64（与 screen 同规，避免日志/事件总线爆量）。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_frame(_CAM, source="desktop_camera")
        bus = MultimodalIngressBus()
        await _one_bridge_tick(bus)
        return bus.build_frame().to_dict()

    d = asyncio.run(_run())
    video = d.get("video") or {}
    assert video.get("has_image") is True, f"序列化体应暴露存在性; got {video}"
    assert "image_b64" not in video, "序列化体带上了原始 base64 —— 日志会被灌爆"
    assert _CAM not in str(d), "帧的任何字段都不应泄漏原始摄像头 base64"


def test_camera_change_score_tracks_new_frames() -> None:
    """变化度与屏幕同款口径：换一帧不同内容会产生变化度（门控看得见"画面变了"）。

    必须在**同一条**桥接循环里观察 —— 变化度是循环内的帧间状态，重起循环即复位。
    变化是瞬时的（同帧再被读到就归零），故在窗口内采样峰值，避免时序竞态。
    """

    async def _run():
        store = get_desktop_perception_store()
        bus = MultimodalIngressBus()
        store.update_frame(_CAM, source="desktop_camera")
        task = asyncio.get_running_loop().create_task(_desktop_perception_bridge_loop(bus, 0.02))
        try:
            await asyncio.sleep(0.1)  # 让首帧被反复读到，变化度回落到 0
            settled = bus.build_frame().video.change_score
            # 换一帧长度明显不同的内容，在窗口内采样变化度峰值
            store.update_frame(base64.b64encode(b"a-much-longer-camera-frame" * 4).decode(), source="desktop_camera")
            peak = 0.0
            for _ in range(40):
                await asyncio.sleep(0.005)
                v = bus.build_frame().video
                if v is not None:
                    peak = max(peak, v.change_score)
            return settled, peak
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    settled, peak = asyncio.run(_run())
    assert settled == 0.0, f"同一帧被反复读到时不应持续报变化; got {settled}"
    assert peak > 0, f"换帧后应出现变化度峰值（否则门控对摄像头失明）; got {peak}"
