"""第一次要念的时候选 TTS 引擎（import 一串库、探测算力、检查模型），不能压在事件循环线程上。

被修的问题（Windows 真机日志）：第一轮对话的请求里，``GET /sessions/.../history`` 与 ``POST /chat/stream``
都显示约 7.4 秒、并且在同一毫秒完成 —— 循环被一件同步的事占住了 7 秒。选引擎就是这类事：
``begin_incremental_speech()`` 在循环线程上同步调 ``_get_engine()``，第一次调用要把候选引擎逐个
import + ``available()``，还要先做算力预检。

现在：``speech_engine_ready()`` 在工作线程里选；选择过程上锁（预热线程与第一次请求同时到，只选一遍）；
语音循环一启动就预热。
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

import core.speech_output as so


@pytest.fixture()
def fresh_engine_state(monkeypatch):
    monkeypatch.setattr(so, "_engine", None)
    monkeypatch.setattr(so, "_engine_failed", False)
    monkeypatch.setenv("GALAXY_SPEAK", "1")
    yield


class _Engine:
    pass


def _slow_selector(seen_threads, delay=0.3):
    def select():
        seen_threads.append(threading.get_ident())
        time.sleep(delay)
        so._engine = _Engine()
        return so._engine

    return select


def test_the_first_selection_runs_off_the_event_loop_thread(fresh_engine_state, monkeypatch):
    seen = []
    monkeypatch.setattr(so, "_select_engine", _slow_selector(seen))

    async def run():
        loop_thread = threading.get_ident()
        engine = await so.speech_engine_ready()
        return loop_thread, engine

    loop_thread, engine = asyncio.run(run())
    assert isinstance(engine, _Engine)
    assert seen and loop_thread not in seen


def test_the_loop_stays_responsive_while_the_engine_is_being_chosen(fresh_engine_state, monkeypatch):
    monkeypatch.setattr(so, "_select_engine", _slow_selector([], delay=0.5))

    async def run():
        ticks = []

        async def ticker():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.02)

        t = asyncio.create_task(ticker())
        await so.speech_engine_ready()
        t.cancel()
        gaps = [b - a for a, b in zip(ticks, ticks[1:])]
        return max(gaps) if gaps else 99.0

    assert asyncio.run(run()) < 0.2  # 循环线程被占住的话，这里会是 0.5 秒


def test_once_chosen_there_is_no_thread_hop(fresh_engine_state, monkeypatch):
    eng = _Engine()
    monkeypatch.setattr(so, "_engine", eng)
    monkeypatch.setattr(so, "_select_engine", lambda: (_ for _ in ()).throw(AssertionError("不该再选")))
    assert asyncio.run(so.speech_engine_ready()) is eng


def test_a_failed_selection_is_remembered_not_retried(fresh_engine_state, monkeypatch):
    monkeypatch.setattr(so, "_engine_failed", True)
    monkeypatch.setattr(so, "_select_engine", lambda: (_ for _ in ()).throw(AssertionError("不该再选")))
    assert asyncio.run(so.speech_engine_ready()) is None


def test_the_warm_up_and_a_first_request_select_only_once(fresh_engine_state, monkeypatch):
    calls = []

    def select():
        calls.append(1)
        time.sleep(0.2)
        so._engine = _Engine()
        return so._engine

    monkeypatch.setattr(so, "_select_engine", select)
    so.warm_speech_engine()  # 预热线程开始选
    time.sleep(0.05)
    assert isinstance(asyncio.run(so.speech_engine_ready()), _Engine)  # 第一次请求与它撞上
    assert len(calls) == 1


def test_warming_up_does_nothing_when_speech_is_off(fresh_engine_state, monkeypatch):
    monkeypatch.setenv("GALAXY_SPEAK", "0")
    monkeypatch.setattr(so, "_select_engine", lambda: (_ for _ in ()).throw(AssertionError("朗读关着，不该选")))
    so.warm_speech_engine()
    time.sleep(0.1)


def test_the_incremental_speech_entry_waits_for_the_engine_off_the_loop(fresh_engine_state, monkeypatch):
    """chat/stream 走的那个入口：选引擎在线程里，选完才建会话。"""
    import core.presence_line as pl

    seen = []
    monkeypatch.setattr(so, "_select_engine", _slow_selector(seen, delay=0.2))
    built = []
    monkeypatch.setattr(so, "begin_incremental_speech", lambda **kw: built.append(so._engine) or "speaker")

    async def run():
        loop_thread = threading.get_ident()
        speaker = await pl.desktop_incremental_speech(True, source="chat")
        return loop_thread, speaker

    loop_thread, speaker = asyncio.run(run())
    assert speaker == "speaker" and built and isinstance(built[0], _Engine)  # 建会话时引擎已选好
    assert loop_thread not in seen


def test_a_request_that_does_not_come_from_the_desktop_never_touches_the_engine(fresh_engine_state, monkeypatch):
    import core.presence_line as pl

    monkeypatch.setattr(so, "_select_engine", lambda: (_ for _ in ()).throw(AssertionError("不该选")))
    assert asyncio.run(pl.desktop_incremental_speech(False, source="chat")) is None
