"""core/device_queue.py — 每台设备一个串行队列(跨设备整体方案阶段 4)。

一台手机不同时做两件事:智能体在它身上点着屏幕的时候,另一件交给它的事排在后面,而不是同时去抢同一块
屏幕。不同设备之间照样并行(多设备同时下发的上限是 ``GALAXY_MULTI_DEVICE_DISPATCH_LIMIT``)。

用现成的带背压队列(:class:`core.queueing.async_queue.AsyncTaskQueue`),每台设备一个、只开一个工位;
排队的事太多时当场说明,不无限堆。队列绑在创建它的事件循环上(测试里每个客户端一个循环),所以按
(循环, 设备)各建一个。
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, Tuple

from core.queueing.async_queue import AsyncTaskQueue, QueueFullError

logger = logging.getLogger("Galaxy.DeviceQueue")

#: 一台设备手上最多排着的事(含正在做的)。
MAX_WAITING = 32
#: 一件事默认最长做多久(秒);委派整段目标的会传更长的。
DEFAULT_TIMEOUT_S = 120.0

_queues: Dict[Tuple[int, str], AsyncTaskQueue] = {}


def dispatch_limit() -> int:
    """多设备同时下发的上限(与网关 ``DeviceRouter`` 同一个开关)。"""
    try:
        return max(1, int(os.environ.get("GALAXY_MULTI_DEVICE_DISPATCH_LIMIT", "8")))
    except ValueError:
        return 8


async def _queue_for(device_id: str) -> AsyncTaskQueue:
    key = (id(asyncio.get_running_loop()), device_id)
    q = _queues.get(key)
    if q is None:
        q = _queues[key] = AsyncTaskQueue(
            max_queue_size=MAX_WAITING, max_concurrent=1, task_timeout=DEFAULT_TIMEOUT_S, backpressure_threshold=1.0
        )
    if not q._started:
        await q.start()
    return q


async def run_on_device(
    device_id: str, job: Callable[[], Awaitable[Dict[str, Any]]], timeout: float = DEFAULT_TIMEOUT_S
) -> Dict[str, Any]:
    """在这台设备的队列里做一件事(``job()``):前面的做完才轮到它。返回它的结果(一个结果字典)。

    ``timeout`` 管的是轮到它之后做多久;排队等多久由前面那几件各自的期限决定。
    """
    if not device_id:
        return await job()
    q = await _queue_for(device_id)
    try:
        fut = await q.submit(job, timeout=timeout)
    except QueueFullError:
        return {"success": False, "error": f"「{device_id}」手上已经排着 {MAX_WAITING} 件事了,等它做完一些再交"}
    try:
        return await fut
    except asyncio.TimeoutError:
        return {"success": False, "error": f"在「{device_id}」上做了 {timeout:.0f} 秒没做完"}
    except Exception as exc:  # noqa: BLE001 — 一件事出错作为结果回给调用方,不炸掉队列
        return {"success": False, "error": str(exc)}


def reset_queues() -> None:
    """测试用。"""
    _queues.clear()
