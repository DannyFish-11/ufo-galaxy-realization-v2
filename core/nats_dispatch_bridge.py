"""命令目标是「只挂在 NATS 上的 worker」时，经 ``NATSExecutor`` 派发 —— 多机模式的第三条路。

## 被修的问题

``CommandRouter`` 的执行器（``routes/command.py::_command_node_executor``）只认两种目标：本机的节点目录，
和通过 WebSocket 连上网关的设备。主脑（``MasterBrain``）名下、只通过 NATS 汇报心跳的 worker，
两种都不是 —— 命令发给它，得到的是「Target … not found」。而 ``NATSExecutor`` 这个现成的、带超时与
回退语义（``GALAXY_NATS_EXECUTOR_FALLBACK`` / ``GALAXY_NATS_EXECUTOR_TIMEOUT``）的实现从来没被装到任何地方：
面板上那两个键存得进、读得出，却什么也改变不了。

## 规则

* 只在**跨设备模式**里问（本地模式不往别的机器派发，见 ``core.system_mode.cross_device_refusal``）；
* 只认主脑**确认还活着**的 worker（心跳没超时）—— 死了的 worker 照旧是「没找到」，不是挂着等 30 秒超时；
* 不是它的目标返回 ``None``，调用方按原来的路径处理。不替执行器已有的两条路做决定。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.NatsDispatchBridge")


def _alive_worker(target: str) -> bool:
    from core.master_brain import get_master_brain

    brain = get_master_brain()
    if brain is None:
        return False
    info = brain.get_worker_topology().get(target)
    return bool(info and info.get("alive"))


async def dispatch_to_nats_worker(target: str, command: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """目标是一台活着的 NATS worker：经 NATSExecutor 派发并返回结果；否则返回 ``None``。"""
    from core.system_mode import cross_device_requested

    if not cross_device_requested():
        return None
    try:
        if not _alive_worker(target):
            return None
        from core.command_router import get_nats_executor

        executor = get_nats_executor()
        await executor.start()  # 订阅结果；幂等
        return await executor(target, command, params)
    except Exception as exc:  # noqa: BLE001 — 这条路出任何事都按「没找到」回给调用方，不炸命令路由
        logger.warning("NATS worker 派发失败(按未找到处理): %s", exc)
        return None
