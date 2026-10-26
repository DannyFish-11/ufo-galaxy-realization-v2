"""core/loop_local_lock.py — 给进程单例用的 ``async with`` 锁:每个事件循环各一把 asyncio.Lock。

单独一把 ``asyncio.Lock`` 第一次有人排队时就绑死在当时的事件循环上,之后在别的循环里一排队就
``RuntimeError: ... is bound to a different event loop``。那个循环要是在有人排队时没了(任务被丢下、没取消),
等待者永远挂在锁上,此后**每一次**拿锁都走排队那条路、都报这个错。

会话管理器就是这样坏的:它是进程单例,却不止被一个循环用到 —— 网关主循环之外,没有运行中循环的同步调用方会
``asyncio.run`` 一个临时循环记一句(``core/device_onboarding/conversation.py`` 的 ``announce_soon``),
测试里每个网关各起各的循环。锁一坏,会话从此写不进去,只在日志里留一行 debug。

同一个循环里照旧互斥。跨线程的一致性本来就不归 asyncio.Lock 管(会话落盘另有线程锁)。
"""

from __future__ import annotations

import asyncio
import threading
import weakref


class LoopLocalLock:
    """用法和 ``asyncio.Lock`` 一样(``async with lock:``),只是每个事件循环各拿各的那把。"""

    def __init__(self) -> None:
        # 以循环为弱键:循环没了,它那把锁跟着回收
        self._locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()
        self._guard = threading.Lock()

    def _current(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._guard:
            lock = self._locks.get(loop)
            if lock is None:
                lock = self._locks[loop] = asyncio.Lock()
            return lock

    def locked(self) -> bool:
        """当前循环里这把锁是不是被占着。"""
        return self._current().locked()

    async def __aenter__(self) -> None:
        await self._current().acquire()

    async def __aexit__(self, *exc_info) -> None:
        # 进出在同一个协程里,也就在同一个循环里:拿到的是进门时那把
        self._current().release()
