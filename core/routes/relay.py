"""
UFO Galaxy - Relay Routes (Phase 2)
=====================================

Routes:
  POST /api/v1/relay/send        - 设备间中继转发
  POST /api/v1/relay/broadcast   - 广播到所有设备
  GET  /api/v1/relay/stats       - 中继统计
  GET  /api/v1/relay/history     - 中继历史
"""

import logging
from typing import Any, Dict, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import connection_manager

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create device relay routes router."""
    router = APIRouter()

    from core.proxy_relay import get_proxy_relay, RelayRequest as ProxyRelayRequest

    proxy_relay = get_proxy_relay()

    proxy_relay.set_sender(connection_manager.send_to_device)
    proxy_relay.set_online_getter(lambda: list(connection_manager.active_devices.keys()))

    class DeviceRelayRequest(BaseModel):
        """设备间中继请求"""
        source_device: str
        target_device: str
        payload_type: str = "task"
        payload: Dict[str, Any] = {}
        expect_reply: bool = False
        timeout_seconds: float = 30.0
        chain: List[str] = []

    @router.post("/api/v1/relay/send")
    async def relay_send(req: DeviceRelayRequest):
        """
        设备间中继 — Server 代理转发

        流程: source_device → Server(中继) → target_device
        如果 expect_reply=true, 服务端等待 target 回复后返回。
        """
        relay_req = ProxyRelayRequest(
            source_device=req.source_device,
            target_device=req.target_device,
            payload_type=req.payload_type,
            payload=req.payload,
            expect_reply=req.expect_reply,
            timeout_seconds=req.timeout_seconds,
            chain=req.chain,
        )
        result = await proxy_relay.relay(relay_req)
        return JSONResponse(result.to_dict())

    @router.post("/api/v1/relay/broadcast")
    async def relay_broadcast(source_device: str = "", payload_type: str = "task", payload: Dict[str, Any] = {}):
        """从一台设备广播到所有其他在线设备"""
        results = await proxy_relay.relay_broadcast(source_device, payload_type, payload)
        return JSONResponse({
            "source": source_device,
            "targets": {k: v.to_dict() for k, v in results.items()},
        })

    @router.get("/api/v1/relay/stats")
    async def relay_stats():
        """中继统计"""
        return JSONResponse(proxy_relay.get_stats())

    @router.get("/api/v1/relay/history")
    async def relay_history(limit: int = 50):
        """中继历史"""
        return JSONResponse({"history": proxy_relay.get_history(limit)})

    return router
