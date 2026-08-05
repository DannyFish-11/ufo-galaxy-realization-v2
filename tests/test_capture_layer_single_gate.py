#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_capture_layer_single_gate.py
===========================================
采集层收口：帧变化判据只有一套，且跨消费者节拍不漏变化。

收口前的两个问题：
1. **两套判据**——注意力循环用感知指纹（准），常驻感知桥用 base64 长度差（把
   "同尺寸不同内容"当成没变化）。同一份数据两套结论，必然分叉；
2. **慢消费者漏变化**——``change_score`` 表达"距上一次采集的变化"，采集侧 200ms
   一拍，注意力循环若干秒一拍；等消费者来读，变化早被后续帧消化回 0。

收口后：门控只在 ``core.multimodal.frame_gate``，采集侧算一次并给出**单调变化
序号**，消费者按序号判断"从我上次看之后变没变过"，与两边节拍快慢无关。
"""

from __future__ import annotations

import asyncio
import base64
import io
from typing import Optional

import pytest

from core.multimodal.frame_gate import FrameGate
from core.multimodal.ingest_runtime import _desktop_perception_bridge_loop
from core.multimodal.ingress_bus import MultimodalIngressBus
from core.perception.desktop_perception_store import get_desktop_perception_store


def _frame(shade: int, size: int = 64) -> str:
    """生成一张纯色 JPEG 的 base64（内容不同、字节长度几乎相同）。"""
    try:
        from PIL import Image

        img = Image.new("L", (size, size), color=shade)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001 — 无 PIL 时退化为等长字节串
        return base64.b64encode(bytes([shade]) * 512).decode()


@pytest.fixture(autouse=True)
def _clean_store():
    store = get_desktop_perception_store()
    store.resume(reason="test-setup")
    yield store
    store.resume(reason="test-teardown")


# ===========================================================================
# 一、门控本体：单调序号语义
# ===========================================================================


def test_change_seq_is_monotonic_and_only_advances_on_change() -> None:
    gate = FrameGate()
    a, b = _frame(10), _frame(240)

    gate.score(a)
    first = gate.change_seq
    assert first == 1, "第一帧应记为一次变化"

    gate.score(a)  # 同一帧
    assert gate.change_seq == first, "同一帧不应推进序号"

    gate.score(b)  # 明显不同的帧
    assert gate.change_seq == first + 1, "内容变了却没推进序号 —— 门控失明"


def test_gate_detects_same_length_different_content() -> None:
    """这正是长度差判据看不见、感知指纹看得见的情形（收口要保住的能力）。"""
    a, b = _frame(10), _frame(240)
    assert abs(len(a) - len(b)) <= max(4, len(a) * 0.02), "构造的两帧应长度接近（否则本用例失去意义）"

    gate = FrameGate()
    gate.score(a)
    seq_after_first = gate.change_seq
    gate.score(b)
    assert gate.change_seq > seq_after_first, "同长度不同内容被判成没变化 —— 回到长度差判据的盲区"


def test_reset_does_not_rewind_change_seq() -> None:
    """隐私边界重置只丢指纹，不回退序号（回退会让消费者误以为回到了旧状态）。"""
    gate = FrameGate()
    gate.score(_frame(10))
    before = gate.change_seq
    gate.reset()
    assert gate.change_seq == before, "序号被回退了"
    gate.score(_frame(10))
    assert gate.change_seq == before + 1, "重置后的第一帧应重新记一次变化"


def test_single_gate_implementation_is_shared() -> None:
    """注意力循环与采集层必须是同一个门控实现（不是各自一份）。"""
    import core.ambient_attention_loop as ambient
    import core.multimodal.frame_gate as fg

    assert ambient.FrameGate is fg.FrameGate, "帧差门控又分叉成两套实现"


# ===========================================================================
# 二、采集侧：帧上带序号
# ===========================================================================


async def _run_bridge(bus: MultimodalIngressBus, seconds: float = 0.12, period: float = 0.02):
    task = asyncio.get_running_loop().create_task(_desktop_perception_bridge_loop(bus, period))
    await asyncio.sleep(seconds)
    return task


async def _stop(task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


def test_perception_frame_carries_change_seq() -> None:
    """常驻感知帧必须带上变化序号（慢消费者的唯一可靠判据）。"""

    async def _run():
        store = get_desktop_perception_store()
        store.update_frame(_frame(30), source="desktop_screen", screen={"w": 1})
        store.update_frame(_frame(60), source="desktop_camera")
        bus = MultimodalIngressBus()
        task = await _run_bridge(bus)
        try:
            return bus.build_frame()
        finally:
            await _stop(task)

    frame = asyncio.run(_run())
    assert frame.screen is not None and frame.screen.change_seq >= 1, "屏幕帧没有变化序号"
    assert frame.video is not None and frame.video.change_seq >= 1, "摄像头帧没有变化序号"


def test_slow_consumer_never_misses_a_change() -> None:
    """慢消费者必须看得见期间发生过的变化 —— 这正是收口修掉的漏检。

    采集侧飞快转，中途换一帧；消费者只在最后看一眼。若按 change_score 判断，
    此时早已被后续同帧消化回 0（漏检）；按序号判断则必然看得见。
    """

    async def _run():
        store = get_desktop_perception_store()
        bus = MultimodalIngressBus()
        store.update_frame(_frame(20), source="desktop_screen", screen={"w": 1})
        task = await _run_bridge(bus, seconds=0.1)
        try:
            seq_before = bus.build_frame().screen.change_seq
            store.update_frame(_frame(230), source="desktop_screen", screen={"w": 1})
            await asyncio.sleep(0.25)  # 采集侧转很多拍，score 早已归零
            f = bus.build_frame()
            return seq_before, f.screen.change_seq, f.screen.change_score
        finally:
            await _stop(task)

    seq_before, seq_after, score_now = asyncio.run(_run())
    assert score_now == 0.0, f"前提不成立：变化尚未被消化（score={score_now}）"
    assert seq_after > seq_before, "变化已被后续帧消化，慢消费者据此漏检 —— 序号没起作用"


def test_privacy_epoch_change_resets_capture_gate() -> None:
    """隐私暂停→恢复后，采集侧门控必须丢弃暂停前的指纹。

    否则恢复后的第一帧会与"被遮住之前"那帧做差，变化量本身泄露了被遮期间的事。

    判据用**序号增量**而不是瞬时 change_score：后者会被后续同帧消化回 0。
    构造上恢复后的新帧与暂停前几乎相同 —— 只有门控真被重置（新帧被当成"第一帧"）
    才会记一次变化；没重置的话这点差异远低于阈值，序号纹丝不动。
    """

    async def _run():
        store = get_desktop_perception_store()
        bus = MultimodalIngressBus()
        store.update_frame(_frame(20), source="desktop_screen", screen={"w": 1})
        task = await _run_bridge(bus, seconds=0.1)
        try:
            seq_before = bus.build_frame().screen.change_seq
            store.pause(reason="test")
            await asyncio.sleep(0.05)
            store.resume(reason="test")
            store.update_frame(_frame(21), source="desktop_screen", screen={"w": 1})  # 与暂停前极相似
            await asyncio.sleep(0.1)
            return seq_before, bus.build_frame().screen.change_seq
        finally:
            await _stop(task)

    seq_before, seq_after = asyncio.run(_run())
    assert seq_after > seq_before, "跨隐私边界没有重置门控 —— 恢复后的帧与被遮前那帧做了差"


def test_near_identical_frame_does_not_bump_seq_without_privacy_boundary() -> None:
    """对照组：没有隐私边界时，同样这点微小差异不该被记成变化。

    这条保证上面那个用例判的是"重置"，而不是"这点差异本来就够大"。
    """
    gate = FrameGate()
    gate.score(_frame(20))
    seq = gate.change_seq
    gate.score(_frame(21))
    assert gate.change_seq == seq, "微小差异被当成了变化 —— 隐私重置用例失去判别力"


# ===========================================================================
# 三、消费侧：注意力循环读采集层的世界
# ===========================================================================


def _loop_with_hub(monkeypatch, frame_obj):
    import core.ambient_attention_loop as ambient
    import core.multimodal.ingest_runtime as ir

    class _Bus:
        def build_frame(self):
            return frame_obj

    monkeypatch.setattr(ir, "get_ingest_bus", lambda: _Bus())
    return ambient.AmbientAttentionLoop()


class _Sc:
    def __init__(self, seq: int):
        self.change_seq = seq


class _Fr:
    def __init__(self, s: Optional[int], v: Optional[int]):
        self.screen = _Sc(s) if s is not None else None
        self.video = _Sc(v) if v is not None else None


def test_ambient_reads_hub_verdict(monkeypatch) -> None:
    """采集层在跑时，注意力循环按序号判断，而不是自己再算一遍。"""
    frame = _Fr(5, 3)
    loop = _loop_with_hub(monkeypatch, frame)

    assert loop._changed_via_hub() is True, "首次读到画面应判为有变化"
    assert loop._changed_via_hub() is False, "序号没动却报有变化"

    frame.screen = _Sc(6)
    assert loop._changed_via_hub() is True, "序号推进了却没判出变化 —— 会漏掉真实变化"


def test_ambient_falls_back_when_hub_absent(monkeypatch) -> None:
    """采集层未启用时退回本地门控（行为与接入前一致，不因收口而失能）。"""
    import core.ambient_attention_loop as ambient
    import core.multimodal.ingest_runtime as ir

    monkeypatch.setattr(ir, "get_ingest_bus", lambda: None)
    assert ambient.AmbientAttentionLoop()._changed_via_hub() is None


def test_ambient_falls_back_when_hub_has_no_frames_yet(monkeypatch) -> None:
    """bus 在跑但还没有任何画面 → 交回本地门控如实判断，不谎报"没变化"。"""
    loop = _loop_with_hub(monkeypatch, _Fr(0, 0))
    assert loop._changed_via_hub() is None


def test_ambient_survives_hub_errors(monkeypatch) -> None:
    """读采集层出错不得连坐注意力循环（退回本地门控即可）。"""
    import core.ambient_attention_loop as ambient
    import core.multimodal.ingest_runtime as ir

    class _Broken:
        def build_frame(self):
            raise RuntimeError("bus exploded")

    monkeypatch.setattr(ir, "get_ingest_bus", lambda: _Broken())
    assert ambient.AmbientAttentionLoop()._changed_via_hub() is None


def test_gather_observation_actually_consults_the_hub(monkeypatch) -> None:
    """真实调用点必须用采集层的判定 —— 光有 _changed_via_hub 不算接上了。

    判别式：store 里有一帧全新画面（本地门控必判"第一帧=有变化"），但采集层
    报"自你上次看以来没变过"。接上了 → 这一拍应被跳过（返回 None）；
    没接上 → 本地门控会判有变化，产出一份观察。
    """
    import core.ambient_attention_loop as ambient
    import core.multimodal.ingest_runtime as ir

    store = get_desktop_perception_store()
    store.update_frame(_frame(77), source="desktop_screen", screen={"w": 1})

    class _Bus:
        def build_frame(self):
            return _Fr(9, 9)  # 序号恒定 = 自上次以来没变过

    monkeypatch.setattr(ir, "get_ingest_bus", lambda: _Bus())

    loop = ambient.AmbientAttentionLoop()
    loop._last_action_ts = 0.0  # 越过冷却，让判定真正落在"变没变"上
    loop._hub_seen_seqs = (9, 9)  # 已经看过这个序号

    assert loop._gather_observation() is None, "采集层说没变，本循环却仍自行判定有变化 —— 接缝没生效"


def test_gather_observation_acts_when_hub_reports_change(monkeypatch) -> None:
    """对照组：采集层报"变了"时，同样的输入必须产出观察（证明上面判的是接缝）。"""
    import core.ambient_attention_loop as ambient
    import core.multimodal.ingest_runtime as ir

    store = get_desktop_perception_store()
    store.update_frame(_frame(88), source="desktop_screen", screen={"w": 1})

    class _Bus:
        def build_frame(self):
            return _Fr(10, 9)  # 序号推进了

    monkeypatch.setattr(ir, "get_ingest_bus", lambda: _Bus())

    loop = ambient.AmbientAttentionLoop()
    loop._last_action_ts = 0.0
    loop._hub_seen_seqs = (9, 9)

    obs = loop._gather_observation()
    assert obs is not None and obs.screen_b64, "采集层报有变化，却没有产出观察"
