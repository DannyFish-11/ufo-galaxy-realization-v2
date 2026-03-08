"""
Galaxy - Session Routes
==========================

Routes:
  GET    /api/v1/sessions              - 列出会话
  POST   /api/v1/sessions              - 创建新会话
  GET    /api/v1/sessions/{id}         - 获取会话详情
  POST   /api/v1/sessions/{id}/join    - 设备加入会话
  GET    /api/v1/sessions/{id}/history - 获取会话历史
  POST   /api/v1/sessions/{id}/sync   - 同步会话到设备
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.session_manager import get_session_manager
from core.routes._shared import connection_manager

logger = logging.getLogger("Galaxy.API.Sessions")


# ══════════════ Request Models ══════════════

class CreateSessionRequest(BaseModel):
    user_id: str
    device_id: str = ""


class JoinSessionRequest(BaseModel):
    device_id: str


class SyncSessionRequest(BaseModel):
    device_id: str
    max_turns: int = 50


# ══════════════ Router ══════════════

def create_router(service_manager=None, config=None) -> APIRouter:
    router = APIRouter()
    sm = get_session_manager()

    # 设置 WebSocket 广播回调
    def _on_session_update(session_id: str, message: dict, devices: list):
        """会话更新时广播到所有关联设备"""
        payload = {
            "type": "session_update",
            "session_id": session_id,
            "message": message,
        }
        for device_id in devices:
            asyncio.ensure_future(
                connection_manager.send_to_device(device_id, payload)
            )
        # 同时推送给 status 订阅者
        asyncio.ensure_future(connection_manager.broadcast_status(payload))

    sm.set_update_callback(_on_session_update)

    @router.get("/api/v1/sessions")
    async def list_sessions(user_id: Optional[str] = None, device_id: Optional[str] = None):
        """列出会话"""
        if device_id:
            sessions = sm.list_device_sessions(device_id)
        else:
            sessions = sm.list_sessions(user_id)
        return JSONResponse({"success": True, "sessions": sessions})

    @router.post("/api/v1/sessions")
    async def create_session(req: CreateSessionRequest):
        """创建新会话"""
        session = sm.create_session(req.user_id, req.device_id)
        return JSONResponse({
            "success": True,
            "session": session.to_summary(),
        })

    @router.get("/api/v1/sessions/{session_id}")
    async def get_session(session_id: str):
        """获取会话详情"""
        session = sm.get_session(session_id)
        if not session:
            return JSONResponse(
                {"success": False, "error": f"会话不存在: {session_id}"},
                status_code=404,
            )
        return JSONResponse({"success": True, "session": session.to_dict()})

    @router.post("/api/v1/sessions/{session_id}/join")
    async def join_session(session_id: str, req: JoinSessionRequest):
        """设备加入会话"""
        ok = sm.join_session(session_id, req.device_id)
        if not ok:
            return JSONResponse(
                {"success": False, "error": f"会话不存在: {session_id}"},
                status_code=404,
            )
        # 向新设备推送会话历史
        history = sm.get_full_history(session_id)
        await connection_manager.send_to_device(req.device_id, {
            "type": "session_sync",
            "session_id": session_id,
            "history": history,
        })
        return JSONResponse({"success": True, "message": f"设备 {req.device_id} 已加入会话"})

    @router.get("/api/v1/sessions/{session_id}/history")
    async def get_history(session_id: str, max_turns: int = 50):
        """获取会话历史"""
        session = sm.get_session(session_id)
        if not session:
            return JSONResponse(
                {"success": False, "error": f"会话不存在: {session_id}"},
                status_code=404,
            )
        history = sm.get_full_history(session_id)
        if max_turns and len(history) > max_turns:
            history = history[-max_turns:]
        return JSONResponse({"success": True, "history": history})

    @router.post("/api/v1/sessions/{session_id}/sync")
    async def sync_session(session_id: str, req: SyncSessionRequest):
        """同步会话历史到指定设备"""
        session = sm.get_session(session_id)
        if not session:
            return JSONResponse(
                {"success": False, "error": f"会话不存在: {session_id}"},
                status_code=404,
            )
        history = sm.get_full_history(session_id)
        if req.max_turns and len(history) > req.max_turns:
            history = history[-req.max_turns:]

        sent = await connection_manager.send_to_device(req.device_id, {
            "type": "session_sync",
            "session_id": session_id,
            "history": history,
        })
        return JSONResponse({
            "success": sent,
            "message": f"已同步 {len(history)} 条消息到设备 {req.device_id}" if sent
                       else f"设备 {req.device_id} 不在线",
        })

    return router
