"""Redis 列表操作的**进程内替身** —— 连不上 Redis 时顶上，不让节点起不来。

为什么有这个东西
================
全仓的约定是「Redis 连不上就降级到内存」。``core/cache.py`` 里白纸黑字写着::

    # Redis 在桌面单机模式是可选项:连不上会安静降级到内存缓存
    logger.info("Redis 未连接(降级到内存缓存,桌面单机属正常): %s", e)

``core/vector_backend.py``(退到 ``_LocalKeywordBackend``)、``core/nats_bus.py``
(退到进程内分发)也都是这个路子。

只有 ``Node_80_MemorySystem`` 反着来:连不上就 ``raise`` →
``Application startup failed. Exiting.``。实测把 125 个节点逐个拉起来，它是
**唯一**一个因为缺外部服务而死的 —— 其余 124 个在零容器状态下都起得来。而它同时
还提供长期记忆(MemOS)、用户画像(SQLite)、向量检索(Chroma)，**三者都不依赖
Redis**：为了一个可降级的子能力，把另外三个也带走了。

为什么不复用 core.cache.CacheManager
====================================
那套已经做了同样的降级，但它的接口只有**字符串** ``get``/``set``。这里要的是
Redis 的**列表**语义(``rpush`` 追加、``lrange`` 按闭区间与负下标取)。硬套会把
语义弄拧 —— 与其用一个形状不对的抽象，不如照着实际用到的那几个方法写个小的。

取舍
====
它是**进程内**的:重启即失忆，多进程不共享。承载它的是"1 小时过期的对话上下文"，
单机场景下这个取舍成立；真要跨进程共享、要重启保活，就把 Redis 起起来 ——
调用方应当通过 ``/health`` 之类的地方**如实上报**当前是哪个后端，而不是让人以为
Redis 在跑（那正是修复前 ``"redis_available": client is not None`` 干的事：降级后
替身也非 None，于是它恒为 True）。
"""

from __future__ import annotations

import time
from typing import Dict, List

__all__ = ["InProcessListStore"]


class InProcessListStore:
    """只实现短期记忆真正用到的那 6 个 Redis 操作。

    ``rpush`` / ``lrange`` / ``expire`` / ``delete`` / ``ping`` / ``close``。
    刻意不做全:多实现一个方法就多一份"以为它等价于 Redis"的错觉。
    """

    def __init__(self) -> None:
        self._lists: Dict[str, List[str]] = {}
        self._expiry: Dict[str, float] = {}

    def _sweep(self, key: str) -> None:
        exp = self._expiry.get(key)
        if exp is not None and time.monotonic() >= exp:
            self._lists.pop(key, None)
            self._expiry.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def rpush(self, key: str, value: str) -> int:
        self._sweep(key)
        self._lists.setdefault(key, []).append(value)
        return len(self._lists[key])

    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """复刻 Redis 的**闭区间 + 负下标**语义。

        这两条都容易写错，而写错的表现是"静默少取/多取几条" —— 不报错，只是
        对话上下文莫名其妙少了一句。``recall`` 用的正是 ``lrange(key, -limit, -1)``。
        """
        self._sweep(key)
        items = self._lists.get(key, [])
        if not items:
            return []
        n = len(items)
        s = start if start >= 0 else max(n + start, 0)
        e = end if end >= 0 else n + end
        if s > e or s >= n:
            return []
        return items[s : min(e, n - 1) + 1]

    async def expire(self, key: str, ttl: int) -> bool:
        if key not in self._lists:
            return False
        self._expiry[key] = time.monotonic() + ttl
        return True

    async def delete(self, key: str) -> int:
        existed = key in self._lists
        self._lists.pop(key, None)
        self._expiry.pop(key, None)
        return 1 if existed else 0

    async def close(self) -> None:
        self._lists.clear()
        self._expiry.clear()
