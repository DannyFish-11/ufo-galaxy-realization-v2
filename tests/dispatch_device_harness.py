"""tests/dispatch_device_harness.py
=====================================

可派发测试设备装置(唯一属主)。

派发链自 PR-1-P0 / V3 槽位权威起要求设备走完整权威注册链才可被路由:

1. UDM(core.unified.device_manager)—— 设备身份 SSOT,且须为可派发类
   (android/windows)
2. 权威能力网络(core.capability_assimilation)—— PR-1-P0 能力硬门
3. UCM 活连接(core.unified.connection_manager)—— 在场真相;无连接的设备
   会在路由中被投影为 offline 并同步回能力层

老测试只注册单点(pool/registry)就派发,全部被新门拦下。用本装置一键
注册/清理,而不是在每个测试文件里重复三段注册代码。

用法::

    from tests.dispatch_device_harness import (
        register_dispatchable_device,
        cleanup_dispatchable_devices,
    )

    class MyTest(unittest.TestCase):
        def setUp(self):
            register_dispatchable_device("device_test", capabilities=["screen"])

        def tearDown(self):
            cleanup_dispatchable_devices()
"""
from __future__ import annotations

import asyncio
from typing import List, Optional
from unittest.mock import MagicMock

_REGISTERED: List[str] = []


def register_dispatchable_device(
    device_id: str,
    capabilities: Optional[List[str]] = None,
    device_type: str = "android",
) -> None:
    """把测试设备注册进完整权威链(UDM + 能力网络 + UCM 活连接)。幂等。"""
    caps = list(capabilities or ["screen"])

    from core.unified.device_manager import get_unified_device_manager
    get_unified_device_manager().register_device_from_dict(
        device_id,
        {"device_type": device_type, "status": "online", "capabilities": caps},
    )

    from core.capability_assimilation import get_capability_assimilation_layer
    get_capability_assimilation_layer().assimilate(device_id, capabilities=caps)

    from core.unified.connection_manager import get_unified_connection_manager
    ucm = get_unified_connection_manager()
    _run_async(ucm.register_connection(device_id, MagicMock()))

    if device_id not in _REGISTERED:
        _REGISTERED.append(device_id)


def cleanup_dispatchable_devices() -> None:
    """注销本装置注册过的全部测试设备(UDM/能力网络/UCM 三处)。"""
    from core.unified.device_manager import get_unified_device_manager
    from core.capability_assimilation import get_capability_assimilation_layer
    from core.unified.connection_manager import get_unified_connection_manager

    udm = get_unified_device_manager()
    layer = get_capability_assimilation_layer()
    ucm = get_unified_connection_manager()

    for device_id in list(_REGISTERED):
        try:
            _run_async(ucm.unregister_connection(device_id))
        except Exception:
            pass
        try:
            layer.mark_offline(device_id, reason="test_harness_cleanup")
        except Exception:
            pass
        try:
            udm.unregister_device(device_id)
        except Exception:
            pass
        _REGISTERED.remove(device_id)


def _run_async(coro) -> None:
    """在同步 setUp/tearDown 里跑一个协程;已有事件循环时排为任务。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(coro)
        return
    loop.create_task(coro)
