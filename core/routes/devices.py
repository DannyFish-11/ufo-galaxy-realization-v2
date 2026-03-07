"""
UFO Galaxy - Device Routes
============================

Routes:
  POST   /api/v1/devices/register              - 注册设备
  POST   /api/v1/devices/status                - 更新设备状态
  GET    /api/v1/devices                       - 列出所有设备
  GET    /api/v1/devices/discover              - 按条件发现设备
  GET    /api/v1/devices/{device_id}           - 获取设备详情
  POST   /api/v1/devices/{device_id}/heartbeat - 设备心跳
  DELETE /api/v1/devices/{device_id}           - 注销设备
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from core.routes._shared import (
    connection_manager,
    registered_devices,
    node_status_cache,
)
from core.routes._models import DeviceRegisterRequest, DeviceStatusUpdate

logger = logging.getLogger("UFO-Galaxy.API")


def create_router(service_manager=None, config=None) -> APIRouter:
    """Create device management routes router."""
    router = APIRouter()

    @router.post("/api/v1/devices/register")
    async def register_device(req: DeviceRegisterRequest):
        """注册设备"""
        device_info = {
            "device_id": req.device_id,
            "device_type": req.device_type,
            "device_name": req.device_name or f"Device-{req.device_id[:8]}",
            "capabilities": req.capabilities,
            "os_version": req.os_version,
            "app_version": req.app_version,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "registered"
        }
        registered_devices[req.device_id] = device_info
        logger.info(f"设备注册: {req.device_id} ({req.device_type})")

        return JSONResponse({
            "success": True,
            "device_id": req.device_id,
            "message": "设备注册成功",
            "server_version": "3.0.0",
            "available_nodes": list(node_status_cache.keys())[:20]
        })

    @router.post("/api/v1/devices/status")
    async def update_device_status(req: DeviceStatusUpdate):
        """更新设备状态"""
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
            registered_devices[req.device_id]["status_detail"] = req.status

            # 广播状态更新
            await connection_manager.broadcast_status({
                "type": "device_status_update",
                "device_id": req.device_id,
                "status": req.status,
                "timestamp": datetime.now().isoformat()
            })

            return {"success": True}
        raise HTTPException(status_code=404, detail="设备未注册")

    @router.get("/api/v1/devices")
    async def list_devices():
        """列出所有设备"""
        devices = []
        for did, info in registered_devices.items():
            devices.append({
                **info,
                "online": did in connection_manager.active_devices
            })
        return JSONResponse({"devices": devices, "total": len(devices)})

    @router.get("/api/v1/devices/discover")
    async def discover_devices(
        device_type: Optional[str] = Query(None, description="按设备类型过滤（如 android_phone）"),
        capability: Optional[str] = Query(None, description="按能力过滤（如 GUI_SCREENSHOT）"),
        status: Optional[str] = Query(None, description="按状态过滤（registered / online / offline）"),
    ):
        """发现设备（按类型、能力、状态过滤）"""
        devices = []
        for did, info in registered_devices.items():
            is_online = did in connection_manager.active_devices
            # 类型过滤
            if device_type and info.get("device_type") != device_type:
                continue
            # 状态过滤
            effective_status = "online" if is_online else info.get("status", "registered")
            if status and effective_status != status:
                continue
            # 能力过滤
            if capability:
                caps = info.get("capabilities", [])
                if capability not in caps:
                    continue
            devices.append({**info, "online": is_online})
        return JSONResponse({"devices": devices, "total": len(devices)})

    @router.get("/api/v1/devices/{device_id}")
    async def get_device(device_id: str):
        """获取设备详情"""
        if device_id in registered_devices:
            info = registered_devices[device_id]
            info["online"] = device_id in connection_manager.active_devices
            return JSONResponse(info)
        raise HTTPException(status_code=404, detail="设备未找到")

    @router.post("/api/v1/devices/{device_id}/heartbeat")
    async def device_heartbeat(device_id: str):
        """设备心跳接口（REST 方式）

        Android 客户端可通过此端点上报心跳，服务端更新 ``last_seen`` 并广播在线状态。
        WebSocket 心跳由 ``/ws/device/{device_id}`` 通道处理（推荐）。
        """
        if device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        registered_devices[device_id]["last_seen"] = datetime.now().isoformat()
        registered_devices[device_id]["status"] = "registered"

        await connection_manager.broadcast_status({
            "type": "device_heartbeat",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        })

        return JSONResponse({"success": True, "device_id": device_id})

    @router.delete("/api/v1/devices/{device_id}")
    async def unregister_device(device_id: str):
        """注销设备（从注册表中移除）

        设备断开后可调用此端点彻底注销。若设备仍有活跃 WebSocket 连接，
        该连接不会被强制关闭；重连时设备需重新注册。
        """
        if device_id not in registered_devices:
            raise HTTPException(status_code=404, detail="设备未注册")

        del registered_devices[device_id]

        await connection_manager.broadcast_status({
            "type": "device_unregistered",
            "device_id": device_id,
            "timestamp": datetime.now().isoformat(),
        })

        logger.info(f"设备注销: {device_id}")
        return JSONResponse({"success": True, "device_id": device_id})

    return router
