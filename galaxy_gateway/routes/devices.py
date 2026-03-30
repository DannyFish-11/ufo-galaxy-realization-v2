"""
galaxy_gateway/routes/devices.py — Device management and legacy compatibility routes.

Routes:
  GET  /api/devices                   - List all devices
  GET  /api/devices/{device_id}       - Get single device info
  GET  /api/devices/connected         - List connected devices
  POST /api/devices/register          - Legacy registration shim
  GET  /api/devices/list              - Legacy list shim
  POST /api/devices/heartbeat         - Legacy heartbeat shim
  POST /api/devices/unregister        - Legacy unregister shim
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from galaxy_gateway.dependencies import get_device_manager, get_websocket_manager
from galaxy_gateway.protocol import DeviceInfo, DeviceType

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================================================
# Current device management endpoints
# ============================================================================

@router.get("/api/devices")
async def get_devices(dm=Depends(get_device_manager)):
    """Return all registered devices."""
    return dm.to_dict()


@router.get("/api/devices/connected")
async def get_connected_devices(wsm=Depends(get_websocket_manager)):
    """Return connected device list."""
    return {
        "connected_devices": wsm.get_connected_devices(),
        "count": wsm.get_device_count(),
    }


@router.get("/api/devices/{device_id}")
async def get_device(
    device_id: str,
    dm=Depends(get_device_manager),
    wsm=Depends(get_websocket_manager),
):
    """Return info for a single device."""
    device = dm.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return {
        "device": device.model_dump(),
        "is_connected": wsm.is_device_connected(device_id),
    }


# ============================================================================
# Legacy HTTP device API compatibility shim
# Maps old /api/devices/* paths → current device-manager behaviour
# ============================================================================

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


@router.post("/api/devices/register")
async def legacy_register_device(
    req: _LegacyRegisterRequest,
    dm=Depends(get_device_manager),
):
    """Legacy registration endpoint — maps to current device-manager logic."""
    logger.info("Legacy /api/devices/register called for device %s", req.device_id)
    device_info = DeviceInfo(
        device_id=req.device_id,
        device_type=(
            DeviceType(req.device_type)
            if req.device_type in [dt.value for dt in DeviceType]
            else DeviceType.UNKNOWN
        ),
        name=req.device_name or req.device_id,
        os_version=req.os_version,
        metadata={"app_version": req.app_version, "capabilities": req.capabilities},
    )
    dm.register_device(device_info)
    return {
        "success": True,
        "device_id": req.device_id,
        "message": "设备注册成功",
        "server_version": "3.0.0",
    }


@router.get("/api/devices/list")
async def legacy_list_devices(dm=Depends(get_device_manager)):
    """Legacy device-list endpoint — maps to current ``GET /api/devices``."""
    logger.info("Legacy /api/devices/list called")
    devices = dm.to_dict()
    return {"devices": devices, "total": len(devices) if isinstance(devices, list) else 0}


@router.post("/api/devices/heartbeat")
async def legacy_device_heartbeat(
    req: _LegacyHeartbeatRequest,
    dm=Depends(get_device_manager),
):
    """Legacy heartbeat endpoint — maps to current device status-update logic."""
    logger.info("Legacy /api/devices/heartbeat called for device %s", req.device_id)
    dm.update_device_status(req.device_id, "online")
    return {"success": True, "device_id": req.device_id}


@router.post("/api/devices/unregister")
async def legacy_unregister_device(
    req: _LegacyUnregisterRequest,
    dm=Depends(get_device_manager),
):
    """Legacy unregister endpoint — safely unregisters the device when possible."""
    logger.info("Legacy /api/devices/unregister called for device %s", req.device_id)
    dm.update_device_status(req.device_id, "offline")
    return {"success": True, "device_id": req.device_id}
