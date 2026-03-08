"""
Galaxy - Android HTTP Compatibility Shim
=============================================

Backward-compatible REST endpoints that map legacy Android client calls to
the current ``/api/v1/devices/*`` route handlers.

Routes added
------------
  POST /api/devices/register     → /api/v1/devices/register
  GET  /api/devices/list         → /api/v1/devices
  POST /api/devices/heartbeat    → /api/v1/devices/status
  POST /api/devices/unregister   → device marked offline (safe no-op)
"""

import logging
from datetime import datetime

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.routes._shared import connection_manager, registered_devices, node_status_cache

logger = logging.getLogger("Galaxy.API")


# ---------------------------------------------------------------------------
# Request models (kept minimal for backward compatibility)
# ---------------------------------------------------------------------------

class _LegacyRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: list = []
    os_version: str = ""
    app_version: str = ""


class _LegacyHeartbeatRequest(BaseModel):
    device_id: str
    status: dict = {}


class _LegacyUnregisterRequest(BaseModel):
    device_id: str


# ---------------------------------------------------------------------------
# Router factory (matches the pattern used by all other route modules)
# ---------------------------------------------------------------------------

def create_router(service_manager=None, config=None) -> APIRouter:
    """Create the legacy device API compatibility shim router."""
    router = APIRouter()

    @router.post("/api/devices/register")
    async def legacy_register_device(req: _LegacyRegisterRequest):
        """
        Legacy registration shim — delegates to /api/v1/devices/register logic.
        """
        logger.info(
            "Legacy /api/devices/register called for device %s", req.device_id
        )
        device_info = {
            "device_id": req.device_id,
            "device_type": req.device_type,
            "device_name": req.device_name or f"Device-{req.device_id[:8]}",
            "capabilities": req.capabilities,
            "os_version": req.os_version,
            "app_version": req.app_version,
            "registered_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "status": "registered",
        }
        registered_devices[req.device_id] = device_info

        return JSONResponse({
            "success": True,
            "device_id": req.device_id,
            "message": "设备注册成功",
            "server_version": "2.0.0",
            "available_nodes": list(node_status_cache.keys())[:20],
        })

    @router.get("/api/devices/list")
    async def legacy_list_devices():
        """
        Legacy device-list shim — returns same payload as /api/v1/devices.
        """
        logger.info("Legacy /api/devices/list called")
        devices = []
        for did, info in registered_devices.items():
            devices.append({
                **info,
                "online": did in connection_manager.active_devices,
            })
        return JSONResponse({"devices": devices, "total": len(devices)})

    @router.post("/api/devices/heartbeat")
    async def legacy_device_heartbeat(req: _LegacyHeartbeatRequest):
        """
        Legacy heartbeat shim — maps to /api/v1/devices/status update.
        """
        logger.info(
            "Legacy /api/devices/heartbeat called for device %s", req.device_id
        )
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
            if req.status:
                registered_devices[req.device_id]["status_detail"] = req.status
            await connection_manager.broadcast_status({
                "type": "device_status_update",
                "device_id": req.device_id,
                "status": req.status,
                "timestamp": datetime.now().isoformat(),
            })
        return JSONResponse({"success": True, "device_id": req.device_id})

    @router.post("/api/devices/unregister")
    async def legacy_unregister_device(req: _LegacyUnregisterRequest):
        """
        Legacy unregister shim — marks device offline (safe no-op if unknown).
        """
        logger.info(
            "Legacy /api/devices/unregister called for device %s", req.device_id
        )
        if req.device_id in registered_devices:
            registered_devices[req.device_id]["status"] = "offline"
            registered_devices[req.device_id]["last_seen"] = datetime.now().isoformat()
        return JSONResponse({"success": True, "device_id": req.device_id})

    return router
