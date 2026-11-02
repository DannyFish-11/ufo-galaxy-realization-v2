"""launcher/first_use_imports.py —— 第一次被用到时才在事件循环上 import 的模块,网关一起来就在旁边线程先载(第 12 轮)。

真跑查到:启动那一阵,服务线程在载 sklearn(自主学习引擎),循环上第一次 import 抢不到解释器 ——
第一次对话卡 2.5 秒、第一次任务 1.1 秒、第一台设备连上来 2.9 秒、节点登记 1.0 秒。
由 ``launcher/services.py::_warm_routes`` 在 ``route-warmup`` 线程里调。预热不成不影响服务:第一次用时照旧在那儿 import。
"""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)

FIRST_USE_MODULES = (
    "anyio._backends._asyncio",  # 第一个走线程池的请求
    "core.execution_policy",  # 第一次对话:desktop_presence_runtime.handle_request
    "core.execution.intent_profile",  # 第一次任务:openclawd._build_intent_profile
    "galaxy_gateway.android_bridge",  # 第一台设备连上规范设备入口:routes/websocket._handle_android_ws
    "core.node_declared_class",  # 节点登记 / 治理门 / 模型的节点目录
)


def warm_first_use() -> None:
    """把 :data:`FIRST_USE_MODULES` 先 import 一遍,节点目录先读一遍。永不抛出。"""
    for name in FIRST_USE_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("预热 import %s 没做成: %s", name, exc)
    try:
        from core.node_catalog import _load_catalog, _num_to_dir

        _load_catalog()
        _num_to_dir()
    except Exception as exc:  # noqa: BLE001
        logger.debug("节点目录预热没做成: %s", exc)


__all__ = ["FIRST_USE_MODULES", "warm_first_use"]
