"""一个事件循环没收尾就没了,别的循环照样能写会话。

会话管理器是进程单例,原来用一把 ``asyncio.Lock``。这把锁第一次有人排队时绑死在当时的循环上;那个循环在有人
排队时被丢下(任务没取消),等待者就永远挂在锁上,此后在任何别的循环里拿锁都报
``bound to a different event loop`` —— 会话从此写不进去,只在日志里留一行 debug。

真实出现过:笔记本配对的测试自己起了一个服务循环,配对后的播报(``announce_soon`` → ``_record``)还在等锁,
循环就停了;同一进程里后面手机桥接交过来的对话、设备播报全都没记进会话(CI 上「环境耦合」那道检查红的就是这个)。
生产里同样有不止一个循环:没有运行中循环的同步调用方会 ``asyncio.run`` 一个临时循环记一句。
"""

from __future__ import annotations

import asyncio

import pytest

from core.loop_local_lock import LoopLocalLock


def _abandon_with_holder_and_waiter(lock):
    """在一个新循环里:一个任务占着锁不放,另一个在排队;然后不收尾就离开这个循环。返回 (循环, 任务们)。"""
    loop = asyncio.new_event_loop()

    async def setup():
        gate = asyncio.Event()

        async def hold():
            async with lock:
                await gate.wait()

        async def wait():
            async with lock:
                pass

        tasks = [asyncio.ensure_future(hold()), asyncio.ensure_future(wait())]
        await asyncio.sleep(0.05)
        return tasks

    tasks = loop.run_until_complete(setup())
    assert not tasks[0].done() and not tasks[1].done(), "两个任务都该还挂着(一个占锁、一个排队)"
    return loop, tasks


def _finish(loop, tasks):
    for t in tasks:
        t.cancel()
    loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
    loop.close()


def test_a_plain_asyncio_lock_is_what_broke():
    """先钉住病根:单独一把 asyncio.Lock,被丢下的循环里有人排过队,别的循环再拿就报错。"""
    lock = asyncio.Lock()
    loop, tasks = _abandon_with_holder_and_waiter(lock)
    try:

        async def take():
            async with lock:
                return "ok"

        with pytest.raises(RuntimeError, match="different event loop"):
            asyncio.run(take())
    finally:
        _finish(loop, tasks)


def test_another_loop_still_takes_the_lock_after_one_was_dropped():
    lock = LoopLocalLock()
    loop, tasks = _abandon_with_holder_and_waiter(lock)
    try:

        async def take():
            async with lock:
                return "ok"

        assert asyncio.run(take()) == "ok"
    finally:
        _finish(loop, tasks)


def test_within_one_loop_it_still_excludes():
    lock = LoopLocalLock()
    order = []

    async def worker(name):
        async with lock:
            order.append(f"{name}-in")
            await asyncio.sleep(0.01)
            order.append(f"{name}-out")

    async def main():
        await asyncio.gather(worker("a"), worker("b"))
        return lock.locked()

    assert asyncio.run(main()) is False
    assert order == ["a-in", "a-out", "b-in", "b-out"]


def test_sessions_still_write_after_a_loop_was_dropped_mid_write(monkeypatch):
    """会话管理器本身:一个循环里写会话写到一半(占着锁落盘)、另一个在排队,这个循环没了;别的循环照样建得了会话。"""
    from core.session_manager import SessionManager

    monkeypatch.setattr(SessionManager, "_load_state", lambda self: None)
    monkeypatch.setattr(SessionManager, "_persist_state", lambda self: None)
    sm = SessionManager()

    loop = asyncio.new_event_loop()

    async def setup():
        stuck = asyncio.Event()

        async def persist_never_finishes():
            await stuck.wait()

        sm._persist_off_loop = persist_never_finishes
        tasks = [
            asyncio.ensure_future(sm.ensure_session("s-dropped-1", user_id="u")),
            asyncio.ensure_future(sm.ensure_session("s-dropped-2", user_id="u")),
        ]
        await asyncio.sleep(0.05)
        return tasks

    tasks = loop.run_until_complete(setup())
    try:
        assert not any(t.done() for t in tasks)

        async def persist_now():
            return None

        sm._persist_off_loop = persist_now
        session = asyncio.run(sm.ensure_session("s-after", user_id="u", device_id="phone-1"))
        assert session.id == "s-after" and "phone-1" in session.devices
    finally:
        _finish(loop, tasks)
