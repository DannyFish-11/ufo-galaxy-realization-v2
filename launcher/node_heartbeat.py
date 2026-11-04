"""启动器拉起的节点进程,活着就一直在节点表里报活。

治理门(``core/node_invocation_governance.py``)按 ``NodeFabricRegistry`` 的心跳判节点健不健康:超过 60 秒没心跳
就是 ``unhealthy``,规范调用一律拒。可启动器只在节点起来那一刻登记一次心跳,之后没人再报 —— 于是开机一分钟后,
启动器拉起的节点(核心组的文件系统节点等)全被治理门以 ``unhealthy`` 拒掉;在本进程里起的节点不登记,反倒照常放行。
第 17 轮真跑查到的:手机上点了「批准」删文件,删的那一步被拒(``governance gate: DENIED … reasons=['unhealthy']``),
``GET /api/v1/nodes/Node_06_Filesystem`` 却说它 healthy。

这里每 :data:`INTERVAL_S` 秒看一遍启动器自己拉起的节点进程:

* 进程还在、``/health`` 应答了(没有端口的只看进程)→ 报一次活;
* 进程退了 → 记成 offline;
* 活着但不应答 → 不报:它到期就是 ``unhealthy``,如实。

一轮的登记只落盘一次(``batched_persistence``),在工作线程里做,不占事件循环。永不抛异常(后台任务)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy")

#: 多久报一次活。治理门的心跳期限是 60 秒,20 秒一轮,漏一两轮也不会误判。
INTERVAL_S = 20.0
#: 一次 ``/health`` 等多久。
PROBE_TIMEOUT_S = 2.0


def _launched_nodes(launcher: Any) -> List[tuple]:
    """``[(节点名, 进程, 端口)]``:只要启动器自己拉起、手里有进程的节点。"""
    try:
        from launcher.bootstrap import ServiceType
    except ImportError:  # pragma: no cover — 与 node_startup 同一套退路
        from .bootstrap import ServiceType  # type: ignore[no-redef]

    out = []
    for name, svc in list(getattr(launcher.service_manager, "services", {}).items()):
        proc = getattr(svc, "process", None)
        if getattr(svc, "service_type", None) != ServiceType.NODE or proc is None:
            continue
        cfg = launcher.node_configs.get(name, {})
        port = cfg.get("port") if isinstance(cfg, dict) else None
        out.append((name, proc, port or getattr(svc, "port", None)))
    return out


async def _answers(session: Any, port: Optional[int]) -> bool:
    if port is None:
        return True  # 没有端口的节点:进程在就算活着(与启动时「无端口，跳过健康检查」一致)
    try:
        async with session.get(f"http://127.0.0.1:{port}/health") as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001 — 不应答就是不应答
        return False


def _record(fresh: List[str], gone: List[str]) -> None:
    from core.nodes.node_fabric_registry import NodeStatus, get_node_fabric_registry

    fabric = get_node_fabric_registry()
    with fabric.batched_persistence():
        for name in fresh:
            fabric.heartbeat(name)
        for name in gone:
            if fabric.get(name) is not None:
                fabric.update_status(name, NodeStatus.OFFLINE)


async def refresh_once(launcher: Any) -> Dict[str, List[str]]:
    """看一遍、报一遍。返回 ``{"fresh": [...], "silent": [...], "gone": [...]}``(给测试与日志)。"""
    import aiohttp

    nodes = _launched_nodes(launcher)
    gone = [name for name, proc, _port in nodes if proc.poll() is not None]
    alive = [(name, port) for name, proc, port in nodes if proc.poll() is None]
    fresh: List[str] = []
    if alive:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_S)) as session:
            ok = await asyncio.gather(*(_answers(session, port) for _name, port in alive))
        fresh = [name for (name, _port), up in zip(alive, ok) if up]
    silent = [name for name, _port in alive if name not in fresh]
    if fresh or gone:
        await asyncio.to_thread(_record, fresh, gone)
    return {"fresh": fresh, "silent": silent, "gone": gone}


async def keep_launched_nodes_fresh(launcher: Any, interval_s: float = INTERVAL_S) -> None:
    """后台一直跑:每 ``interval_s`` 秒 :func:`refresh_once` 一次。"""
    while True:
        await asyncio.sleep(interval_s)
        try:
            seen = await refresh_once(launcher)
            if seen["silent"] or seen["gone"]:
                logger.debug("节点报活:不应答 %s,进程已退 %s", seen["silent"], seen["gone"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — 报活出错不该打断别的
            logger.debug("节点报活这一轮出错(下一轮再来): %s", exc)


def start(launcher: Any) -> None:
    """起报活任务(同一个启动器只起一个)。"""
    task = getattr(launcher, "_heartbeat_task", None)
    if task is not None and not task.done():
        return
    launcher._heartbeat_task = asyncio.get_running_loop().create_task(keep_launched_nodes_fresh(launcher))
