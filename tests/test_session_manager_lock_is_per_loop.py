"""会话管理器的锁按事件循环各一把(CI 上抓到的那一次:``[locked, waiters:1] is bound to a different event loop``)。

原先整个进程一把 ``asyncio.Lock``:它在第一次有人排队时绑定到那个循环。一个循环停了、持锁的任务没收尾,
这把锁就永远「锁着」且绑在已经没了的循环上 —— 之后任何别的循环来要锁(测试各自的循环、节点宿主线程、
设备那一轮的后台循环)都当场抛错,会话写不进去。
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def sm(monkeypatch):
    from core.session_manager import SessionManager

    manager = SessionManager()
    monkeypatch.setattr(manager, "_persist_state", lambda: None)  # 不落盘:这里只看锁
    manager._sessions.clear()
    manager._user_active_session.clear()
    return manager


def test_a_lock_left_held_in_an_abandoned_loop_does_not_lock_out_another_loop(sm):
    abandoned = asyncio.new_event_loop()

    async def hold():
        async with sm._lock:
            await asyncio.sleep(3600)

    async def queue_behind():
        async with sm._lock:
            pass

    holder, waiter = abandoned.create_task(hold()), abandoned.create_task(queue_behind())
    abandoned.run_until_complete(asyncio.sleep(0.05))  # 一个持锁、一个排队 → 这把锁绑在 abandoned 上
    try:
        # 那个循环就此停着(像一个停掉却没收尾任务的循环)。另一个循环照样能写会话。
        session = asyncio.run(sm.ensure_session("s-other-loop", user_id="u1"))
        assert session.id == "s-other-loop" and "s-other-loop" in sm._sessions
    finally:
        holder.cancel()
        waiter.cancel()
        abandoned.run_until_complete(asyncio.gather(holder, waiter, return_exceptions=True))
        abandoned.close()


def test_within_one_loop_it_still_serialises(sm):
    async def main():
        assert sm._lock.current() is sm._lock.current(), "同一个循环拿到的是同一把锁"
        events = []

        async def critical(name, delay):
            async with sm._lock:
                events.append(f"start:{name}")
                await asyncio.sleep(delay)
                events.append(f"end:{name}")

        await asyncio.gather(critical("a", 0.05), critical("b", 0.0))
        return events

    assert asyncio.run(main()) == ["start:a", "end:a", "start:b", "end:b"]


def test_each_loop_gets_its_own_lock_and_it_goes_away_with_the_loop(sm):
    async def grab():
        return id(sm._lock.current())

    first, second = asyncio.run(grab()), asyncio.run(grab())
    assert first and second
    import gc

    gc.collect()
    assert len(sm._lock._locks) == 0, "循环没了,它那把锁不留在表里"
