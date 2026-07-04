"""tests/test_gateway_mounted_lifespan_503.py
================================================
回归防护:被主 app 挂载(app.mount("/gateway", gateway_app))时,Gateway 的
必需核心服务必须就绪,/gateway/* 不再恒返回 503。

背景
----
Starlette 不会为【被挂载的子应用】运行其 lifespan;而 galaxy_gateway 的 lifespan
负责创建 device/message/websocket/task 四个服务并写入 gateway_app.state。主 app
又是命令式启动、没有自己的 lifespan(unified_launcher 的 FastAPI(...) 无 lifespan
参数),于是子应用 lifespan 永不触发 → gateway_app.state.X 恒为 None →
galaxy_gateway.dependencies._get_state 对这四个 required 依赖抛 HTTP 503
"Service not ready" → 真机上 /gateway/* 全部 503。

修复(core/startup.py 挂载后调用 lifecycle.init_gateway_core_services):只补齐
这四个【必需】服务(可选服务缺失时 dependencies 返回 None、不 503),刻意不跑完整
lifespan(避免 NATS/TCP/UDP 监听/AIPTransport 与主 app 双绑端口/重复注册)。

本测试锁住:init 前 required 依赖抛 503;init 后四个依赖都能取到实例;可选依赖
(nats_adapter 等)在只跑 core 服务时仍安全返回 None(不 503)。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException


class _Req:
    """最小请求替身:dependencies 只读 request.app.state。"""
    def __init__(self, app):
        self.app = app


@pytest.mark.asyncio
async def test_required_deps_503_before_init_and_resolve_after():
    from galaxy_gateway.app import app as gw
    from galaxy_gateway.bootstrap.lifecycle import init_gateway_core_services
    from galaxy_gateway.dependencies import (
        get_device_manager,
        get_message_handler,
        get_websocket_manager,
        get_task_orchestrator,
        get_nats_adapter,
    )

    # 用一个干净的 state,确保"init 前"确实是未就绪态(其它测试可能已 init 过全局 app)。
    from starlette.datastructures import State
    gw.state = State()
    req = _Req(gw)

    # BEFORE：required 依赖必须 503。
    for getter in (get_device_manager, get_message_handler,
                   get_websocket_manager, get_task_orchestrator):
        with pytest.raises(HTTPException) as ei:
            getter(req)
        assert ei.value.status_code == 503, f"{getter.__name__} 未按预期 503"

    # INIT：只补必需核心服务。
    dm, mh, wsm, to = await init_gateway_core_services(gw)
    try:
        # AFTER：四个 required 依赖都应取到实例,不再 503。
        assert get_device_manager(req) is dm
        assert get_message_handler(req) is mh
        assert get_websocket_manager(req) is wsm
        assert get_task_orchestrator(req) is to
        assert type(dm).__name__ == "DeviceManager"
        assert type(wsm).__name__ == "WebSocketManager"
        assert type(to).__name__ == "TaskOrchestrator"

        # 可选依赖:只跑 core 服务时未设置 → dependencies 应安全返回 None(绝不 503)。
        assert get_nats_adapter(req) is None
    finally:
        # 干净收尾(与 core/startup 的 shutdown 钩子一致)。
        import contextlib
        with contextlib.suppress(Exception):
            await to.stop()
        with contextlib.suppress(Exception):
            await wsm.stop()


@pytest.mark.asyncio
async def test_init_also_updates_legacy_module_globals():
    """旧 import 路径(from galaxy_gateway.app import websocket_manager)也要被填上。"""
    from galaxy_gateway.app import app as gw
    from galaxy_gateway.bootstrap.lifecycle import init_gateway_core_services
    import galaxy_gateway.app as gw_app

    from starlette.datastructures import State
    gw.state = State()

    dm, mh, wsm, to = await init_gateway_core_services(gw)
    try:
        assert gw_app.device_manager is dm
        assert gw_app.websocket_manager is wsm
        assert gw_app.task_orchestrator is to
    finally:
        import contextlib
        with contextlib.suppress(Exception):
            await to.stop()
        with contextlib.suppress(Exception):
            await wsm.stop()
