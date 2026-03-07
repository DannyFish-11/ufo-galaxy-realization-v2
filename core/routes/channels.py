"""
UFO Galaxy - Channel Plugin Routes
=====================================

Routes:
  GET  /api/v1/channels                      - 列出渠道插件
  POST /api/v1/channels/load                 - 加载渠道插件
  POST /api/v1/channels/auto_load            - 自动扫描加载
  POST /api/v1/channels/{plugin_id}/send     - 发送消息
  GET  /api/v1/channels/health               - 健康检查
  GET  /api/v1/channels/{plugin_id}/schema   - 插件配置 schema
"""

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create channel plugin routes router."""
    router = APIRouter()

    # Rate limiter for channel send endpoint
    try:
        from core.security_middleware import RateLimiter as _RateLimiter
        _channel_send_limiter = _RateLimiter(requests_per_minute=60, burst_size=20)
    except Exception:
        _channel_send_limiter = None

    @router.get("/api/v1/channels")
    async def channel_list_plugins():
        """列出已加载的渠道插件"""
        try:
            from core.channel_plugins import get_channel_loader
            return JSONResponse({"plugins": get_channel_loader().list_plugins()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/load")
    async def channel_load_plugin(request: Request):
        """加载渠道插件（内置或外部路径）"""
        body = await request.json()
        plugin_id = body.get("plugin_id", "")
        path = body.get("path")
        cfg = body.get("config")
        if not plugin_id:
            raise HTTPException(status_code=400, detail="plugin_id is required")
        try:
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().load_plugin(plugin_id, path=path, config=cfg)
            if not result.get("success"):
                raise HTTPException(status_code=400, detail=result.get("error", "load failed"))
            return JSONResponse(result)
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/auto_load")
    async def channel_auto_load(request: Request):
        """自动扫描并加载渠道插件目录（默认 external/channels/）"""
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:
                logger.debug("channel_auto_load: no JSON body, using defaults")
            plugins_dir = body.get("directory") if body else None
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().auto_load_plugins(plugins_dir=plugins_dir)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/channels/{plugin_id}/send")
    async def channel_send_message(plugin_id: str, request: Request):
        """通过指定渠道插件发送消息"""
        if _channel_send_limiter is not None:
            client_ip = request.client.host if request.client else "unknown"
            if not _channel_send_limiter.is_allowed(client_ip):
                raise HTTPException(status_code=429, detail="Rate limit exceeded")
        body = await request.json()
        message = body.get("message", "")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        try:
            from core.channel_plugins import get_channel_loader
            result = await get_channel_loader().send(plugin_id, message, **{
                k: v for k, v in body.items() if k != "message"
            })
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/channels/health")
    async def channel_health_check():
        """检查所有已加载渠道插件健康状态"""
        try:
            from core.channel_plugins import get_channel_loader
            results = await get_channel_loader().health_check_all()
            if not results:
                overall = "unknown"
            elif all(
                isinstance(v, dict) and v.get("healthy", False)
                for v in results.values()
            ):
                overall = "healthy"
            else:
                overall = "degraded"
            return JSONResponse({"health": results, "overall": overall})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/channels/{plugin_id}/schema")
    async def channel_get_schema(plugin_id: str):
        """获取指定渠道插件的配置 schema"""
        try:
            from core.channel_plugins import get_channel_loader
            adapter = get_channel_loader().get_adapter(plugin_id)
            if adapter is None:
                raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not loaded")
            return JSONResponse({"plugin_id": plugin_id, "schema": adapter.get_config_schema()})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
