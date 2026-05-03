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
  POST   /api/v1/sessions/migrate      - 跨设备会话迁移 (Phase 4)
"""

import asyncio
import logging
import time
from typing import Any, Dict, Optional

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


async def migrate_session_via_canonical_manager(
    *,
    session_id: str,
    target_device: str,
    source_device: str = "",
    context_override: Optional[Dict[str, Any]] = None,
    session_manager=None,
    ws_connection_manager=None,
) -> Dict[str, Any]:
    """Canonical session migration helper shared by REST and gateway handlers."""

    sm = session_manager or get_session_manager()
    cm = ws_connection_manager or connection_manager

    session = sm.get_session(session_id)
    if session is None:
        return {
            "success": False,
            "status_code": 404,
            "error": f"Session '{session_id}' not found",
        }

    effective_source = source_device or getattr(session, "active_device", "") or ""
    if effective_source and effective_source not in session.devices:
        return {
            "success": False,
            "status_code": 409,
            "error": (
                f"Device '{effective_source}' is not part of session '{session_id}'. "
                f"Known devices: {session.devices}"
            ),
        }

    if context_override:
        session.metadata.setdefault("migration_context", {})
        session.metadata["migration_context"].update(dict(context_override))

    if target_device not in session.devices:
        session.devices.append(target_device)
    session.active_device = target_device
    session.updated_at = time.time()

    try:
        sm._persist_state()
    except Exception:
        pass

    history = sm.get_full_history(session_id)
    if effective_source:
        await cm.send_to_device(
            effective_source,
            {
                "type": "session_migrated",
                "session_id": session_id,
                "target_device": target_device,
            },
        )
    await cm.send_to_device(
        target_device,
        {
            "type": "session_sync",
            "session_id": session_id,
            "history": history,
            "context": dict(getattr(session, "metadata", {})),
            "migrated_from": effective_source,
        },
    )

    try:
        from core.control_plane._globals import get_audit_ledger
        from core.control_plane.audit_ledger import EventType, Severity

        ledger = get_audit_ledger()
        ledger.append(
            event_type=EventType.DEVICE_REGISTERED,
            severity=Severity.INFO,
            source="sessions_migrate",
            session_id=session_id,
            device_id=target_device,
            message=f"Session migrated: {effective_source} → {target_device}",
            payload={
                "session_id": session_id,
                "source_device": effective_source,
                "target_device": target_device,
                "context_keys_merged": list((context_override or {}).keys()),
            },
        )
    except Exception:
        pass

    return {
        "success": True,
        "status_code": 200,
        "session_id": session_id,
        "source_device": effective_source,
        "target_device": target_device,
        "active_device": session.active_device,
        "message": f"Session successfully migrated to {target_device}",
        "history_count": len(history),
    }


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

    # ──────────────────────────────────────────────────────────────────────
    # Phase 4: Cross-device session migration
    # ──────────────────────────────────────────────────────────────────────

    @router.post("/api/v1/sessions/migrate")
    async def migrate_session(req: dict):
        """Migrate a session from one device to another.

        Accepts a JSON body matching :class:`SessionMigrateSchema`:

        .. code-block:: json

            {
                "session_id": "session_abc",
                "source_device": "phone_01",
                "target_device": "desktop_02",
                "context": {}
            }

        The endpoint:
          1. Validates the session exists on *source_device*.
          2. Merges the supplied *context* overrides into the session context.
          3. Moves the session's *active_device* to *target_device*.
          4. Notifies both devices via WebSocket.
          5. Emits a migration audit event.
        """
        from core.schemas.session import SessionMigrateSchema

        try:
            migrate_req = SessionMigrateSchema(**req)
        except Exception as exc:
            return JSONResponse(
                status_code=422,
                content={"success": False, "error": f"Invalid request: {exc}"},
            )

        result = await migrate_session_via_canonical_manager(
            session_id=migrate_req.session_id,
            source_device=migrate_req.source_device,
            target_device=migrate_req.target_device,
            context_override=migrate_req.context,
            session_manager=sm,
            ws_connection_manager=connection_manager,
        )
        status_code = int(result.pop("status_code", 200))
        return JSONResponse(result, status_code=status_code)

    return router
