"""面板 feed：聚合不占事件循环、并发读取并发读取共用一次计算（不留结果）、只取三个字段不跑 18 段全量聚合。

真机启动日志：首次 GET /api/v1/panel/feed 耗时 11.5 秒，之后 Electron 每 30 秒一次的兜底对账 1~3 秒；
这段时间里 /api/perception/desktop/frame、/audio、/chat/stream 全部排队、成批地一起"变慢"。
根因：build_panel_feed 是 async 函数，却把整份同步聚合（还每次都全量构建统一面板，只为取 3 个字段）
直接在事件循环里跑。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

import core.routes.panel as panel


@pytest.fixture(autouse=True)
def _fresh():
    panel.reset_panel_feed_cache()
    yield
    panel.reset_panel_feed_cache()


def test_assembly_runs_in_a_worker_thread_not_on_the_event_loop(monkeypatch):
    seen = {}

    def slow_assemble(st):
        seen["thread"] = threading.current_thread()
        time.sleep(0.4)
        return {"ok": True}

    monkeypatch.setattr(panel, "_assemble_panel_feed", slow_assemble)

    async def scenario():
        ticks = []

        async def heartbeat():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        hb = asyncio.create_task(heartbeat())
        feed = await panel.build_panel_feed()
        hb.cancel()
        return feed, ticks

    feed, ticks = asyncio.run(scenario())
    assert feed == {"ok": True}
    assert seen["thread"] is not threading.main_thread()
    # 聚合睡了 0.4 秒；事件循环在这期间没被占住：心跳间隔没有出现接近 0.4 秒的空洞
    gaps = [b - a for a, b in zip(ticks, ticks[1:])]
    assert len(ticks) > 8 and max(gaps) < 0.2, f"事件循环被占住了: max gap {max(gaps):.2f}s"


def test_concurrent_readers_share_one_computation(monkeypatch):
    calls = []

    def slow_assemble(st):
        calls.append(1)
        time.sleep(0.2)
        return {"n": len(calls)}

    monkeypatch.setattr(panel, "_assemble_panel_feed", slow_assemble)

    async def scenario():
        return await asyncio.gather(*(panel.build_panel_feed() for _ in range(6)))

    results = asyncio.run(scenario())
    assert len(calls) == 1
    assert all(r == {"n": 1} for r in results)


def test_reads_after_the_computation_finished_recompute_instead_of_reusing_a_stale_result(monkeypatch):
    """不留结果：feed 是被状态事件推着刷新的，事件之后的读取必须看到事件之后的状态。"""
    calls = []
    monkeypatch.setattr(panel, "_assemble_panel_feed", lambda st: calls.append(1) or {"n": len(calls)})

    async def scenario():
        a = await panel.build_panel_feed()
        b = await panel.build_panel_feed()
        return a, b

    a, b = asyncio.run(scenario())
    assert a == {"n": 1} and b == {"n": 2}


def test_one_cancelled_reader_does_not_cancel_the_shared_computation(monkeypatch):
    monkeypatch.setattr(panel, "_assemble_panel_feed", lambda st: time.sleep(0.2) or {"done": True})

    async def scenario():
        first = asyncio.create_task(panel.build_panel_feed())
        second = asyncio.create_task(panel.build_panel_feed())
        await asyncio.sleep(0.02)
        first.cancel()
        return await second

    assert asyncio.run(scenario()) == {"done": True}


def test_feed_takes_the_three_presence_fields_from_the_light_slice_not_the_full_aggregation(monkeypatch):
    import core.unified_panel_aggregation as upa

    def boom(*a, **k):
        raise AssertionError("面板 feed 不该再跑 18 段全量聚合")

    monkeypatch.setattr(upa, "build_unified_panel_payload", boom)
    monkeypatch.setattr(
        upa, "build_presence_slice", lambda: {"tri_state_phase": "liminal", "presence_intensity": 0.4, "coherence": 0.9}
    )
    feed = panel._assemble_panel_feed(None)
    assert feed["presence_intensity"] == 0.4 and feed["coherence"] == 0.9


def test_presence_slice_matches_what_the_full_payload_reports_for_those_fields():
    from core.unified_panel_aggregation import build_presence_slice, build_unified_panel_payload

    full = build_unified_panel_payload(mode="chat").to_dict()
    light = build_presence_slice()
    for k in ("tri_state_phase", "presence_intensity", "coherence"):
        assert light[k] == full[k], k
