"""每个事件循环一把 ``asyncio.Lock`` —— 给进程级单例用的锁。

为什么不能整个进程一把 ``asyncio.Lock``
--------------------------------------
``asyncio.Lock`` 在第一次有人排队时绑定到那个循环。进程里不止一个循环(节点宿主线程、设备那一轮的
后台循环、测试各自的循环):

* 之后别的循环一排队,就当场抛 ``RuntimeError: ... is bound to a different event loop``;
* 一个循环停了而持锁的任务没收尾,这把锁就永远「锁着」且绑在已经没了的循环上,所有循环都进不来。

CI 上抓到过后一种(会话管理器:``[locked, waiters:1] is bound to a different event loop``)。

这里怎么做
----------
同一个循环里拿到的永远是同一把锁,照旧互斥;不同循环各一把。跨循环本来就互斥不了 —— 一把
``asyncio.Lock`` 管不了别的循环;要跨线程互斥的状态该用 ``threading.Lock``。键是循环本身(弱引用),
循环没了它那一项跟着回收。用法与 ``asyncio.Lock`` 相同:``async with lock:``。
"""

from __future__ import annotations

import asyncio
import weakref


class LoopLocalLock:
    """``async with`` 拿当前循环的那把锁。"""

    def __init__(self) -> None:
        self._locks: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock]" = weakref.WeakKeyDictionary()

    def current(self) -> asyncio.Lock:
        """当前事件循环的那把锁(没有就建一把)。只能在跑着的循环里调。"""
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = self._locks.setdefault(loop, asyncio.Lock())
        return lock

    def locked(self) -> bool:
        return self.current().locked()

    async def __aenter__(self) -> None:
        await self.current().acquire()

    async def __aexit__(self, *exc) -> None:
        self.current().release()
