"""core/device_onboarding/runtime.py — 接入平面随网关起停。

启动:把花名册里的成员以离线身份回灌设备表 → 绑定事件循环(供线程里的发现回调
回到这里做自动接入)→ 起轮询循环(HA 已发现集成、tailnet、SSDP;NATS edge worker
订阅在循环里重试,NATS 往往比这里晚连上)。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from core.device_onboarding.service import auto_level, get_onboarding_service, onboarding_enabled

logger = logging.getLogger("Galaxy.Onboarding.Runtime")

_stop: Optional[asyncio.Event] = None
_task: Optional[asyncio.Task] = None


async def _loop(stop: asyncio.Event) -> None:
    from core.device_onboarding.sources import run_scan_loop, subscribe_workers

    subscribed = False

    async def _workers_until_subscribed() -> None:
        nonlocal subscribed
        while not stop.is_set() and not subscribed:
            subscribed = await subscribe_workers()
            if not subscribed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    pass

    await asyncio.gather(run_scan_loop(stop), _workers_until_subscribed())


async def start_onboarding() -> Dict[str, Any]:
    global _stop, _task
    if not onboarding_enabled():
        return {"status": "disabled"}
    svc = get_onboarding_service()
    svc.bind_loop(asyncio.get_running_loop())
    restored = svc.rehydrate()
    _stop = asyncio.Event()
    _task = asyncio.create_task(_loop(_stop), name="device-onboarding")
    return {"status": "ok", "restored_members": restored, "auto_level": auto_level()}


async def stop_onboarding() -> None:
    global _stop, _task
    if _stop is not None:
        _stop.set()
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
    _stop = _task = None
