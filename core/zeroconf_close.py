"""把 Zeroconf 实例**真的**关掉 —— 一处权威。

问题
----
``Zeroconf.close()`` 要做同步 I/O:注销已经登记出去的服务、等对方确认。它自己会
检查是不是跑在事件循环线程上,是的话就**直接跳过注销**,只留一条

    unregister_all_services skipped as it does blocking i/o; use AsyncZeroconf with asyncio

真跑实测里这条就挂在"✓ 系统已停止"后面。看着像一句无害的告警,实际含义是:
**这次停机根本没有注销 mDNS 广播** —— 局域网里那条 ``_galaxy._tcp`` 还挂着,
要等 TTL 自己过期,期间别的设备仍然会发现一个已经不在了的网关。
"看起来接上了,其实没有"的标准形状。

做法
----
在事件循环线程上就把 ``close()`` 甩到工作线程里跑,**只极短地**等一下(循环不能
为它停住),没关完的留到进程收尾时再等;不在事件循环上就直接关。两个调用点(``core.lan_discovery`` 与
``galaxy_gateway.mdns_announcer``)都走这一处,不各写各的。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

logger = logging.getLogger("Galaxy.Zeroconf")

#: 在**事件循环线程上**最多阻塞多久等它关完(秒)。必须很短 —— 这段时间里
#: 循环转不动,uvicorn 的优雅停机、其它收尾任务全都排在后面。真跑实测:这里
#: 一等 3 秒,uvicorn 的 lifespan 就来不及收,屏幕上又冒出一段 CancelledError 裸栈。
ON_LOOP_BUDGET_S = 0.3

#: 进程收尾时(已经没有循环在转了)再等的上限(秒)。这时候阻塞是免费的。
DRAIN_TIMEOUT_S = 3.0

_pending_lock = threading.Lock()
_pending: "list[threading.Thread]" = []


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def close_zeroconf(zc: Any, *, label: str = "zeroconf", budget: float = ON_LOOP_BUDGET_S) -> bool:
    """关掉一个 Zeroconf 实例。返回**这一刻是否已经关完**。

    没关完不代表放弃:工作线程还在跑,由 :func:`drain_pending_closes` 在进程收尾
    时接着等 —— 那时候没有循环要照顾,阻塞是免费的。
    """
    if zc is None:
        return True

    if not _on_event_loop():
        try:
            zc.close()
            return True
        except Exception as exc:  # noqa: BLE001 —— 停机路径,报一声就走
            logger.warning("%s 关闭出错(继续停机): %s", label, exc)
            return False

    # 在事件循环线程上 —— 直接 close() 的话 zeroconf 会跳过注销。甩到线程里去,
    # 并且**只极短地**等一下:循环不能为它停住。
    outcome: dict = {}

    def _close() -> None:
        try:
            zc.close()
            outcome["ok"] = True
        except Exception as exc:  # noqa: BLE001
            outcome["ok"] = False
            outcome["err"] = exc

    worker = threading.Thread(target=_close, name=f"close-{label}", daemon=True)
    worker.start()
    worker.join(budget)

    if worker.is_alive():
        with _pending_lock:
            _pending.append(worker)
        logger.debug("%s 还在关,交给进程收尾时再等。", label)
        return False
    if not outcome.get("ok", False):
        logger.warning("%s 关闭出错(继续停机): %s", label, outcome.get("err"))
        return False
    return True


def drain_pending_closes(timeout: float = DRAIN_TIMEOUT_S) -> int:
    """进程收尾时把还没关完的 Zeroconf 等完。返回**仍未关完**的条数。

    到点就走 —— 停机路径不许变成"关不掉"。真有没关完的就照实说一句:局域网里
    那条广播要等 TTL 过期,别让人以为已经干净了。
    """
    with _pending_lock:
        workers = list(_pending)
        _pending.clear()
    if not workers:
        return 0

    deadline = time.monotonic() + max(0.0, timeout)
    for w in workers:
        w.join(max(0.0, deadline - time.monotonic()))

    stuck = [w for w in workers if w.is_alive()]
    if stuck:
        logger.warning(
            "%d 个 mDNS 广播在 %.1f 秒内没注销完,先退出;局域网里它们要等 TTL 过期才消失。",
            len(stuck),
            timeout,
        )
    return len(stuck)


__all__ = ["ON_LOOP_BUDGET_S", "DRAIN_TIMEOUT_S", "close_zeroconf", "drain_pending_closes"]
