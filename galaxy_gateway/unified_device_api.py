"""
Unified Device & Session API Router
====================================

Provides a single REST API surface for:
1. Device registration / discovery / heartbeat  (backed by core.device_registry)
2. Session roaming (create / migrate / query)    (backed by session_roaming)

Mount into FastAPI via::

    from galaxy_gateway.unified_device_api import router as unified_router
    app.include_router(unified_router, prefix="/api/v1")
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger("UFO-Galaxy.UnifiedDeviceAPI")

router = APIRouter(tags=["Unified Devices & Sessions"])


# ============================================================================
# Request / Response models
# ============================================================================

class RegisterDeviceRequest(BaseModel):
    device_id: Optional[str] = None
    device_type: str = "custom"
    name: str = ""
    capabilities: List[str] = Field(default_factory=list)
    ip_address: str = ""
    port: int = 0
    manufacturer: str = ""
    model: str = ""
    os_version: str = ""
    app_version: str = ""
    groups: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SessionCreateRequest(BaseModel):
    device_id: str
    wake_word: str = ""
    meta: Dict[str, Any] = Field(default_factory=dict)


class SessionMigrateRequest(BaseModel):
    session_id: str
    target_device_id: str


class SessionTurnRequest(BaseModel):
    session_id: str
    role: str  # "user" | "assistant"
    content: str


# ============================================================================
# Device endpoints (delegates to core.device_registry)
# ============================================================================

def _registry():
    from core.device_registry import device_registry
    return device_registry


@router.post("/devices/register")
async def register_device(req: RegisterDeviceRequest):
    """统一设备注册 — 写入 core.device_registry（持久化 JSON）"""
    registry = _registry()
    device = await registry.register(
        device_id=req.device_id,
        device_type=req.device_type,
        name=req.name,
        capabilities=req.capabilities,
        ip_address=req.ip_address,
        port=req.port,
        manufacturer=req.manufacturer,
        model=req.model,
        os_version=req.os_version,
        app_version=req.app_version,
        groups=req.groups,
        tags=req.tags,
        metadata=req.metadata,
    )
    return {"success": True, "device_id": device.device_id}


@router.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """统一设备注销"""
    ok = await _registry().unregister(device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True, "device_id": device_id}


@router.get("/devices")
async def list_devices(
    device_type: Optional[str] = Query(None),
    online_only: bool = Query(False),
):
    """列出所有设备（支持按类型和在线状态过滤）"""
    from core.device_types import DeviceStatus
    registry = _registry()
    devices = registry.list_devices(device_type=device_type)
    if online_only:
        devices = [d for d in devices if d.status == DeviceStatus.ONLINE]
    return [d.to_dict() for d in devices]


@router.get("/devices/{device_id}")
async def get_device(device_id: str):
    """获取单个设备信息"""
    device = _registry().get(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device.to_dict()


@router.post("/devices/{device_id}/heartbeat")
async def device_heartbeat(device_id: str):
    """设备心跳"""
    ok = await _registry().heartbeat(device_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found")
    return {"success": True, "device_id": device_id}


@router.get("/devices/stats/overview")
async def device_stats():
    """设备统计概览"""
    return _registry().get_stats()


@router.get("/devices/discover/available")
async def discover_devices(
    device_type: Optional[str] = Query(None),
    capability: Optional[str] = Query(None),
):
    """设备发现 — 查找可用设备"""
    devices = await _registry().discover(
        device_type=device_type,
        capability=capability,
        online_only=True,
    )
    return [d.to_dict() for d in devices]


# ============================================================================
# Session Roaming endpoints
# ============================================================================

def _session_mgr():
    from galaxy_gateway.session_roaming import session_roaming
    return session_roaming


@router.post("/sessions")
async def create_session(req: SessionCreateRequest):
    """创建新会话"""
    mgr = _session_mgr()
    session = mgr.create_session(
        device_id=req.device_id,
        wake_word=req.wake_word,
        meta=req.meta,
    )
    return session.to_dict()


@router.get("/sessions")
async def list_sessions(state: Optional[str] = Query(None)):
    """列出会话"""
    from galaxy_gateway.session_roaming import SessionState
    mgr = _session_mgr()
    s = SessionState(state) if state else None
    return mgr.list_sessions(state=s)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """获取会话详情"""
    session = _session_mgr().get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.to_dict()


@router.post("/sessions/migrate")
async def migrate_session(req: SessionMigrateRequest):
    """迁移会话到目标设备"""
    ok = await _session_mgr().migrate_session(req.session_id, req.target_device_id)
    if not ok:
        raise HTTPException(status_code=400, detail="Migration failed")
    return {"success": True, "session_id": req.session_id, "target": req.target_device_id}


@router.post("/sessions/turn")
async def add_session_turn(req: SessionTurnRequest):
    """向会话添加一轮对话"""
    _session_mgr().add_turn(req.session_id, req.role, req.content)
    return {"success": True}


@router.delete("/sessions/{session_id}")
async def close_session(session_id: str):
    """关闭会话"""
    _session_mgr().close_session(session_id)
    return {"success": True, "session_id": session_id}


@router.get("/sessions/stats/overview")
async def session_stats():
    """会话统计"""
    return _session_mgr().get_stats()
