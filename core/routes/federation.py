"""
UFO Galaxy - Federation Routes
================================

Routes:
  GET    /api/v1/federation/info                        - 本实例联邦信息
  GET    /api/v1/federation/peers                       - 列出 peer 实例
  POST   /api/v1/federation/peers                       - 注册 peer
  DELETE /api/v1/federation/peers/{instance_id}        - 注销 peer
  GET    /api/v1/federation/peers/cleanup               - 清理 stale peers
  POST   /api/v1/federation/heartbeat                   - 接收心跳
  POST   /api/v1/federation/task                        - 接收转发任务
  POST   /api/v1/federation/forward                     - 转发任务给 peer
  GET    /api/v1/federation/health                      - 联邦健康摘要
  GET    /api/v1/federation/peers/{instance_id}/ping    - Peer 心跳检查
"""

import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create Galaxy Federation routes router."""
    router = APIRouter()

    @router.get("/api/v1/federation/info")
    async def federation_info():
        """获取本实例联邦信息"""
        try:
            from core.galaxy_federation import get_federation
            return JSONResponse(get_federation().local_info())
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers")
    async def federation_list_peers():
        """列出所有已知的联邦 peer 实例"""
        try:
            from core.galaxy_federation import get_federation
            return JSONResponse({"peers": get_federation().list_peers()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/peers")
    async def federation_register_peer(request: Request):
        """手动注册一个 peer 实例"""
        body = await request.json()
        url = body.get("url", "")
        instance_id = body.get("instance_id", "")
        name = body.get("name", "")
        if not url:
            raise HTTPException(status_code=400, detail="url is required")
        try:
            from core.galaxy_federation import get_federation
            peer = get_federation().register_peer(url, instance_id=instance_id, name=name)
            return JSONResponse({"success": True, "peer": peer.to_dict()})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.delete("/api/v1/federation/peers/{instance_id}")
    async def federation_unregister_peer(instance_id: str):
        """注销指定 peer 实例"""
        try:
            from core.galaxy_federation import get_federation
            removed = get_federation().unregister_peer(instance_id)
            if not removed:
                raise HTTPException(status_code=404, detail=f"Peer '{instance_id}' not found")
            return JSONResponse({"success": True, "instance_id": instance_id})
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers/cleanup")
    async def federation_cleanup_peers(max_age: int = 60):
        """移除 last_heartbeat 超过 max_age 秒的 stale peers"""
        try:
            from core.galaxy_federation import get_federation
            removed = get_federation().cleanup_stale_peers(max_age=max_age)
            return JSONResponse({"success": True, "removed": removed})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/heartbeat")
    async def federation_receive_heartbeat(request: Request):
        """接收来自其他实例的心跳"""
        body = await request.json()
        try:
            from core.galaxy_federation import get_federation
            result = get_federation().receive_heartbeat(body)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/api/v1/federation/task")
    async def federation_receive_task(request: Request):
        """接收来自其他实例的转发任务（简单 echo 处理）"""
        body = await request.json()
        from_instance = body.get("from_instance", "unknown")
        task = body.get("task", {})
        logger.info(f"Federation task received from {from_instance}: {task.get('command', '')}")
        return JSONResponse({
            "success": True,
            "from_instance": from_instance,
            "task_received": task,
        })

    @router.post("/api/v1/federation/forward")
    async def federation_forward_task(request: Request):
        """将任务转发给指定 peer 实例"""
        body = await request.json()
        target = body.get("target", "")
        task = body.get("task", {})
        if not target:
            raise HTTPException(status_code=400, detail="target is required")
        try:
            from core.galaxy_federation import get_federation
            result = await get_federation().forward_task(target, task)
            return JSONResponse(result)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/health")
    async def federation_health_summary():
        """联邦健康摘要：本地状态 + peers 数量 + alive/degraded/offline 统计"""
        try:
            from core.galaxy_federation import get_federation, _federation_enabled
            fed = get_federation()
            peers = fed.list_peers()
            alive = sum(1 for p in peers if p["status"] == "healthy")
            degraded = sum(1 for p in peers if p["status"] == "degraded")
            offline = sum(1 for p in peers if p["status"] == "offline")
            return JSONResponse({
                "instance_id": fed.instance_id,
                "local_url": fed.local_url,
                "enabled": _federation_enabled(),
                "peers_count": len(peers),
                "alive": alive,
                "degraded": degraded,
                "offline": offline,
            })
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/api/v1/federation/peers/{instance_id}/ping")
    async def federation_peer_ping(instance_id: str):
        """检查特定 peer 的最后心跳时间，返回状态和心跳年龄"""
        try:
            from core.galaxy_federation import get_federation
            peer = get_federation().get_peer(instance_id)
            if not peer:
                raise HTTPException(status_code=404, detail=f"Peer '{instance_id}' not found")
            age = time.time() - peer.last_heartbeat
            return JSONResponse({
                "instance_id": instance_id,
                "status": peer.status,
                "last_heartbeat_age_s": round(age, 1),
                "alive": peer.is_alive(),
            })
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    return router
