"""一批请求同一毫秒一起慢 = 事件循环被一件同步的事占住了。慢请求日志只看得到受害者 ——
``core/loop_stall_watch.py`` 要说出凶手在仓库里哪几行。"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

import core.loop_stall_watch as w


def _hog_the_loop_for(seconds: float) -> None:
    time.sleep(seconds)  # 故意在事件循环里同步睡


class _Said(logging.Handler):
    """直接挂在这个 logger 上收:不依赖冒泡到根(同一进程里别的测试可能改过日志配置)。"""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def said(monkeypatch):
    h = _Said()
    monkeypatch.setattr(w.logger, "disabled", False)
    monkeypatch.setattr(w.logger, "level", logging.NOTSET)
    w.logger.addHandler(h)
    yield h.lines
    w.logger.removeHandler(h)


def test_a_stall_is_reported_with_where_it_happened(monkeypatch, said):
    monkeypatch.setattr(w, "_started", False)
    monkeypatch.setattr(w, "STALL_S", 0.3)

    async def run():
        assert w.start()
        await asyncio.sleep(0.3)
        _hog_the_loop_for(0.9)
        await asyncio.sleep(0.6)

    asyncio.run(run())
    assert any("事件循环被卡住" in m and "_hog_the_loop_for" in m for m in said), said


def test_a_healthy_loop_says_nothing(monkeypatch, said):
    monkeypatch.setattr(w, "_started", False)

    async def run():
        assert w.start()
        for _ in range(8):
            await asyncio.sleep(0.1)

    asyncio.run(run())
    assert not [m for m in said if "事件循环被卡住" in m]


def test_no_running_loop_means_no_watch(monkeypatch):
    monkeypatch.setattr(w, "_started", False)
    assert w.start() is False


def test_the_launcher_starts_it_with_the_server():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    serve = src.index("asyncio.create_task(server.serve())")
    assert "loop_stall_watch.start()" in src[serve : serve + 400]


def test_another_loop_in_the_same_process_does_not_hide_a_stall(monkeypatch, said):
    """心跳归各自的循环:另一个循环一直在跳,也不能把这边的卡顿盖住。"""
    import threading

    monkeypatch.setattr(w, "STALL_S", 0.3)
    other = asyncio.new_event_loop()
    stop = threading.Event()

    def run_other():
        monkeypatch.setattr(w, "_started", False)
        asyncio.set_event_loop(other)

        async def idle():
            w.start()
            while not stop.is_set():
                await asyncio.sleep(0.05)

        other.run_until_complete(idle())

    t = threading.Thread(target=run_other, daemon=True)
    t.start()
    time.sleep(0.3)

    async def run():
        monkeypatch.setattr(w, "_started", False)
        assert w.start()
        await asyncio.sleep(0.3)
        _hog_the_loop_for(0.9)
        await asyncio.sleep(0.6)

    asyncio.run(run())
    stop.set()
    t.join(2)
    other.close()
    assert any("事件循环被卡住" in m and "_hog_the_loop_for" in m for m in said), said
