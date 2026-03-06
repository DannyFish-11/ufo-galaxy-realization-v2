"""
异步任务工具 (Task Utilities)
==============================

提供安全的后台任务创建，防止异常被静默吞没。
"""

import asyncio
import logging
from typing import Coroutine, Optional

logger = logging.getLogger("UFO-Galaxy.TaskUtils")


def create_tracked_task(
    coro: Coroutine,
    *,
    name: Optional[str] = None,
    logger_override: Optional[logging.Logger] = None,
) -> asyncio.Task:
    """
    创建带异常追踪的后台任务

    与 asyncio.create_task() 相同，但自动添加 done_callback：
    - 如果任务因异常退出，记录 ERROR 日志
    - 如果任务被取消，静默忽略

    用法：
        from core.task_utils import create_tracked_task
        task = create_tracked_task(my_coro(), name="heartbeat")
    """
    task = asyncio.create_task(coro, name=name)
    _logger = logger_override or logger

    def _done_callback(t: asyncio.Task):
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            task_name = t.get_name() if hasattr(t, "get_name") else name or "unnamed"
            _logger.error(
                f"后台任务 {task_name!r} 异常退出: {exc}",
                exc_info=exc,
            )

    task.add_done_callback(_done_callback)
    return task
