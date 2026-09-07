"""
launcher/shutdown.py — Graceful shutdown of core subsystems.

Responsibilities:
- async_shutdown: disconnect NATS bus and shut down core subsystems
  (event bridge, monitoring, cache) in a safe order.
- run_and_drain: 一次性命令(报告完就该退出的那种)用的事件循环收尾。
"""

import asyncio
import logging
from typing import Any, Awaitable, Callable, List, Optional

logger = logging.getLogger("Galaxy")

#: 收尾时给"还没结束的后台任务"多少秒响应取消。超过就不等了。
DRAIN_SECONDS = 3.0


def run_and_drain(
    coro: Awaitable[Any],
    *,
    drain_seconds: float = DRAIN_SECONDS,
    on_stuck: Optional[Callable[[List[str]], None]] = None,
) -> Any:
    """跑完一个协程就**一定要退出来**,不许被赖着不走的后台任务卡住。

    为什么不能直接用 ``asyncio.run``(真跑实测,不是推测):
    ``python main.py --check-only`` 会 import 全部 125 个节点模块,其中一些在
    import / 构造时就起了后台循环。报告打完之后 ``asyncio.run`` 进入收尾,
    ``_cancel_all_tasks`` 取消它们并 ``run_until_complete`` 等它们结束 ——
    只要有**一个**任务把 ``CancelledError`` 吞了(``while True: try: ... except
    Exception: pass`` 这种写法),这一等就是永远。

    实测结果:``--check-only`` 屏幕上打完"✓ 系统就绪，可以启动",进程再也不退,
    连着三次都是被 ``timeout`` 杀掉的(退出码 124)。用户看到的就是"报告出来了,
    然后它就停在那儿了" —— 和启动器那个沉默问题是同一族。

    这里改成:取消 + **有上限地**等 ``drain_seconds`` 秒,还赖着的就点名报出来,
    然后关掉循环走人。宁可说"有 N 个任务没响应取消",也不要无声地挂死。

    Args:
        coro:          要跑到底的协程。
        drain_seconds: 给未完成任务响应取消的秒数上限。
        on_stuck:      有任务赖着不走时,拿到它们的名字 —— 由调用方决定怎么说
                       (控制台一行 / 只记日志)。不传就只记日志。

    Returns:
        协程的返回值。
    """
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(coro)

        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.wait(pending, timeout=drain_seconds))

        stuck = [t for t in pending if not t.done()]
        if stuck:
            names = [(t.get_name() or repr(t)) for t in stuck]
            logger.warning(
                "%d 个后台任务没有响应取消(等了 %.1fs),不再等待: %s",
                len(stuck),
                drain_seconds,
                ", ".join(names[:8]) + (" …" if len(names) > 8 else ""),
            )
            if on_stuck is not None:
                try:
                    on_stuck(names)
                except Exception as exc:  # noqa: BLE001 — 报告用的回调不许反过来挡退出
                    logger.debug("on_stuck 回调抛异常,忽略: %s", exc)
        return result
    finally:
        # close() 不等待未完成的任务 —— 这正是我们要的:上面已经给过它们机会了。
        loop.close()
        asyncio.set_event_loop(None)


async def async_shutdown() -> None:
    """异步关闭核心子系统。

    Shutdown order:
      0. Persist in-flight task lifecycle snapshot so restart recovery can
         recover pending tasks after the next process start.
      1. Core subsystems bootstrapped by ``core.startup``
         (event bridge → monitoring → cache).
      2. NATS bus graceful disconnect.

    Failures are logged as warnings and do not prevent the remaining
    shutdown steps from running.
    """
    # Step 0: Persist in-flight task lifecycle state before any subsystem
    # teardown.  This ensures that tasks pending at shutdown time are
    # durably recorded and can be recovered by RuntimeRestartRecoveryCoordinator
    # on the next process start.
    try:
        from core.task_envelope_lifecycle_registry import persist_lifecycle_snapshot

        _ok = persist_lifecycle_snapshot()
        if _ok:
            logger.info("async_shutdown: lifecycle snapshot persisted for restart recovery.")
        else:
            logger.warning("async_shutdown: lifecycle snapshot persist returned False.")
    except Exception as exc:
        logger.warning("async_shutdown: lifecycle snapshot persist failed — %s", exc)

    try:
        from core.master_brain import get_master_brain

        brain = get_master_brain()
        if brain is not None:
            await brain.stop()
    except Exception as exc:
        logger.warning("MasterBrain 关闭异常: %s", exc)

    try:
        from core.startup import shutdown_subsystems

        await shutdown_subsystems()
    except Exception as exc:
        logger.warning("子系统关闭异常: %s", exc)

    try:
        from core.nats_bus import nats_bus

        await nats_bus.disconnect()
    except Exception as exc:
        logger.warning("NATS Bus 关闭异常: %s", exc)
