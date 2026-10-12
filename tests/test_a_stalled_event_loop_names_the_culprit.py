"""一批请求同一毫秒一起慢 = 事件循环被一件同步的事占住了。慢请求日志只看得到受害者 ——
``core/loop_stall_watch.py`` 要说出凶手在仓库里哪几行。"""

from __future__ import annotations

import asyncio
import logging
import time

import core.loop_stall_watch as w


def _hog_the_loop_for(seconds: float) -> None:
    time.sleep(seconds)  # 故意在事件循环里同步睡


def test_a_stall_is_reported_with_where_it_happened(monkeypatch, caplog):
    monkeypatch.setattr(w, "_started", False)
    monkeypatch.setattr(w, "STALL_S", 0.3)

    async def run():
        assert w.start()
        await asyncio.sleep(0.3)
        _hog_the_loop_for(0.9)
        await asyncio.sleep(0.6)

    with caplog.at_level(logging.WARNING, logger=w.logger.name):
        asyncio.run(run())
    said = [r.getMessage() for r in caplog.records]
    assert any("事件循环被卡住" in m and "_hog_the_loop_for" in m for m in said), said


def test_a_healthy_loop_says_nothing(monkeypatch, caplog):
    monkeypatch.setattr(w, "_started", False)

    async def run():
        assert w.start()
        for _ in range(8):
            await asyncio.sleep(0.1)

    with caplog.at_level(logging.WARNING, logger=w.logger.name):
        asyncio.run(run())
    assert not [r for r in caplog.records if "事件循环被卡住" in r.getMessage()]


def test_no_running_loop_means_no_watch(monkeypatch):
    monkeypatch.setattr(w, "_started", False)
    assert w.start() is False


def test_the_launcher_starts_it_with_the_server():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    serve = src.index("asyncio.create_task(server.serve())")
    assert "loop_stall_watch.start()" in src[serve : serve + 400]
