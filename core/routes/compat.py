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

        PR5: Also writes through to UnifiedDeviceManager (UDM) as SSOT so that
        legacy Android clients that call this endpoint are reflected in the
        unified device registry.
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

        # PR5: SSOT write-through — legacy endpoint now delegates to UDM
        try:
            from galaxy_gateway.ssot import udm_write_register
            ok = udm_write_register(
                device_id=req.device_id,
                device_name=device_info["device_name"],
                device_type_raw=req.device_type,
                capabilities=req.capabilities,
                metadata={"os_version": req.os_version, "app_version": req.app_version},
                source="compat_legacy",
            )
            if ok:
                logger.info(
                    "Legacy 设备已写入 UDM (SSOT): %s (%s)", req.device_id, req.device_type,
                )
            else:
                logger.warning(
                    "Legacy 设备 UDM 写入失败（注册继续）: %s", req.device_id
                )
        except Exception as _udm_err:
            logger.debug("Legacy UDM write-through 异常（不影响注册）: %s", _udm_err)

        registered_devices[req.device_id] = device_info

        # 同步设备能力到 CapabilityRegistry，与 /api/v1/devices/register 保持一致
        synced_caps = 0
        try:
            from core.routes.devices import _sync_device_to_capability_registry
            synced_caps = _sync_device_to_capability_registry(device_info)
            if synced_caps:
                logger.info(
                    "Legacy 设备 %s 已同步 %d 个能力到 CapabilityRegistry",
                    req.device_id, synced_caps,
                )
        except Exception as _sync_err:
            logger.debug("Legacy 设备能力同步失败（不影响注册）: %s", _sync_err)

        # PR4: 广播实时事件（与 /api/v1/devices/register 保持一致）
        try:
            from core.routes._shared import broadcast_event
            await broadcast_event("device_update", {
                "action": "register",
                "device_id": req.device_id,
                "device_name": device_info["device_name"],
                "device_type": req.device_type,
                "capabilities": req.capabilities,
                "source": "legacy",
            })
            if synced_caps:
                await broadcast_event("capability_update", {
                    "source": "compat_legacy",
                    "device_id": req.device_id,
                    "synced_count": synced_caps,
                })
        except Exception as _bc_err:
            logger.debug("Legacy 设备注册广播事件失败: %s", _bc_err)

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

        PR5: Also propagates heartbeat to UDM to keep unified registry in sync.
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

        # PR5: UDM heartbeat write-through (best-effort)
        try:
            from galaxy_gateway.ssot import udm_write_heartbeat
            udm_write_heartbeat(req.device_id)
        except Exception as _udm_err:
            logger.debug("Legacy UDM heartbeat write-through 失败（不影响响应）: %s", _udm_err)

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
