"""把一串紧挨着的「改一点、整份落盘」合成一次落盘。

启动时登记能力 / 节点是一连串同步调用，每一次都把**整张图**重新序列化并原子替换一遍（实测 106 次、
最大一份 93KB —— Linux 上 0.4 秒，Windows 上有杀软逐个扫临时文件，是几秒）。中间那 105 份没人会读：
下一次调用马上覆盖它们。

``PersistBatcher`` 只改**什么时候**写，不改写什么：批内的 ``request()`` 只记「脏了」，最外层批结束时写**一次**
（内容是那一刻的完整快照，与逐次写的最后一份相同）。批外的 ``request()`` 照旧立刻写。批内进程被杀，丢的是
一次还没做完的启动登记 —— 下次启动本来就会重做。
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Iterator


class PersistBatcher:
    def __init__(self, write: Callable[[], None]) -> None:
        self._write = write
        self._lock = threading.Lock()
        self._depth = 0
        self._dirty = False

    def request(self) -> None:
        """要落盘：批内只记一笔，批外立刻写。"""
        with self._lock:
            if self._depth:
                self._dirty = True
                return
        self._write()

    @contextmanager
    def batch(self) -> Iterator[None]:
        with self._lock:
            self._depth += 1
        try:
            yield
        finally:
            with self._lock:
                self._depth -= 1
                flush = self._depth == 0 and self._dirty
                if flush:
                    self._dirty = False
            if flush:
                self._write()
