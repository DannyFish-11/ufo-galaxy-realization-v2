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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from core.auth import require_auth
from core.routes._shared import connection_manager
from core.session_manager import get_session_manager

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


class ReconcileSessionRequest(BaseModel):
    """把设备本地(离线)自建的会话认领到用户 canonical 主线。"""

    local_session_id: str
    canonical_session_id: str = ""
    user_id: str = ""
    device_id: str = ""
    merge_history: bool = True


class IngestTurnModel(BaseModel):
    role: str
    content: str
    ts: float = 0.0
    metadata: Optional[Dict[str, Any]] = None


class IngestTurnsRequest(BaseModel):
    """手机离线期间记录的对话轮次,重连后补录进统一主线。"""

    session_id: str
    user_id: str = ""
    device_id: str = ""
    turns: List[IngestTurnModel] = []


async def migrate_session_via_canonical_manager(
    *,
    session_id: str,
    target_device: str,
    source_device: str = "",
    context_override: Optional[Dict[str, Any]] = None,
    session_manager=None,
    ws_connection_manager=None,
) -> Dict[str, Any]:
    """旧名，保留给既有调用方。迁移的规范面是 :func:`core.session_migration.migrate_session`，这里只转过去。"""
    from core.session_migration import migrate_session

    return await migrate_session(
        session_id=session_id,
        target_device=target_device,
        source_device=source_device,
        context_override=context_override,
        session_manager=session_manager or get_session_manager(),
        ws_connection_manager=ws_connection_manager or connection_manager,
    )


async def reconcile_session_to_canonical(
    *,
    local_session_id: str,
    canonical_session_id: str = "",
    user_id: str = "",
    device_id: str = "",
    merge_history: bool = True,
    session_manager=None,
    ws_connection_manager=None,
) -> Dict[str, Any]:
    """把设备本地/离线自建的 ``local_session_id`` 认领到用户 canonical 会话主线。

    目标主线的选择优先级:显式 ``canonical_session_id`` > 用户活跃会话 > 新建一条。
    步骤:
      1. 解析/确定目标 canonical 主线(必要时新建并确保存在)。
      2. 可选:把本地会话已记录的历史轮次并入主线(经统一记忆门,自带相邻去重)。
      3. 登记别名 ``local_session_id → canonical``——此后带该本地 id 进来的任何轮次
         (在线 goal_execution / 面板 / 离线补录)都自动归并到这条主线。
      4. 向设备推送合并后的 session_sync。
    """
    from core.session_memory_facade import record_session_turn

    sm = session_manager or get_session_manager()
    cm = ws_connection_manager or connection_manager

    if not local_session_id:
        return {"success": False, "status_code": 422, "error": "local_session_id required"}

    owner = user_id or f"device::{device_id or 'default'}"

    # 1. 目标主线
    target = sm.resolve_session_alias(canonical_session_id) if canonical_session_id else ""
    if not target and user_id:
        target = sm._user_active_session.get(user_id, "")
    if not target:
        target = sm.get_or_create_session_sync(owner, device_id or "").conversation_session_id
    canonical = sm.resolve_session_alias(target)
    sm.ensure_session_sync(canonical, user_id=owner, device_id=device_id or "")

    # 2. 合并本地历史(在登记别名之前抓取本地会话对象,此刻 local 尚无别名、指向自身)
    merged = 0
    local_resolved = sm.resolve_session_alias(local_session_id)
    local_session = sm.get_session(local_resolved)
    if merge_history and local_session is not None and local_resolved != canonical:
        for msg in list(getattr(local_session, "history", []) or []):
            role = getattr(msg, "role", "") or ""
            content = getattr(msg, "content", "") or ""
            if not role or not content:
                continue
            md = dict(getattr(msg, "metadata", {}) or {})
            md.setdefault("reconciled_from", local_session_id)
            await record_session_turn(
                conversation_session_id=canonical,
                role=role,
                content=content,
                user_id=user_id,
                device_id=getattr(msg, "device_id", "") or device_id,
                metadata=md,
            )
            merged += 1

    # 3. 登记别名(合并之后,避免 resolve(local) 提前折向 canonical)
    aliased = sm.register_session_alias(local_session_id, canonical)

    # 4. 推送合并后的完整历史给设备
    history = sm.get_full_history(canonical)
    if device_id:
        try:
            await cm.send_to_device(
                device_id,
                {
                    "type": "session_sync",
                    "session_id": canonical,
                    "history": history,
                    "reconciled_from": local_session_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("reconcile session_sync push failed: %s", exc)

    return {
        "success": True,
        "status_code": 200,
        "local_session_id": local_session_id,
        "canonical_session_id": canonical,
        "aliased": aliased,
        "merged_turns": merged,
        "history_count": len(history),
    }


async def ingest_conversation_turns(
    *,
    session_id: str,
    turns: List[Any],
    user_id: str = "",
    device_id: str = "",
    session_manager=None,
) -> Dict[str, Any]:
    """把一批(通常来自手机离线期间的)对话轮次补录进统一会话主线。

    ``session_id`` 会先经别名解析到 canonical 主线;每条轮次走 ``record_session_turn``
    这道统一记忆门(会话历史 + 工作记忆 + 对话记忆 + 统一语义记忆一次写齐,自带相邻去重)。
    """
    from core.session_memory_facade import record_session_turn

    sm = session_manager or get_session_manager()
    canonical = sm.resolve_session_alias(session_id)
    if not canonical:
        return {"success": False, "status_code": 422, "error": "session_id required"}

    ingested = 0
    for t in turns or []:
        role = (getattr(t, "role", "") or "").strip()
        content = (getattr(t, "content", "") or "").strip()
        if not role or not content:
            continue
        md = dict(getattr(t, "metadata", None) or {})
        md.setdefault("offline_ingest", True)
        ts = getattr(t, "ts", 0.0) or 0.0
        if ts:
            md.setdefault("client_ts", ts)
        await record_session_turn(
            conversation_session_id=canonical,
            role=role,
            content=content,
            user_id=user_id,
            device_id=device_id,
            metadata=md,
        )
        ingested += 1

    return {
        "success": True,
        "status_code": 200,
        "session_id": canonical,
        "ingested": ingested,
        "history_count": len(sm.get_full_history(canonical)),
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
            asyncio.ensure_future(connection_manager.send_to_device(device_id, payload))
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
        # SessionManager.create_session 是 **async** 的(它要拿 self._lock)。
        # 这里原来漏了 await —— session 拿到的是个协程对象,下一行 .to_summary()
        # 直接 AttributeError。真跑实测:POST /api/v1/sessions 一律 HTTP 500
        # ("'coroutine' object has no attribute 'to_summary'"),也就是说
        # **建会话这条 HTTP 路从来没通过**。
        session = await sm.create_session(req.user_id, req.device_id)
        return JSONResponse(
            {
                "success": True,
                "session": session.to_summary(),
            }
        )

    # 必须注册在 /api/v1/sessions/{session_id} **之前** —— 路由按注册顺序匹配,
    # 放在后面的话 "primary" 会被当成一个会话 id,永远 404。
    @router.get("/api/v1/sessions/primary")
    async def get_primary_session():
        """当前对话主线 —— 面板上那条上下文是哪一条会话。

        语音、双工、自发开口都记进这一条(判据只有一份,见 core/conversation_mainline.py),
        面板打开时读它,于是面板关掉再开,前后说过的话都齐。没有任何真实对话时
        ``session_id`` 为空串 —— 那是「还没聊过」,不是错误。
        """
        from core.conversation_mainline import mainline_session_id

        sid = mainline_session_id()
        return JSONResponse({"success": True, "session_id": sid})

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
        # 同上,join_session 也是 async。漏 await 的后果比上面那条更隐蔽:
        # ok 拿到的是协程对象,**恒为真**,于是 404 分支永远走不到 ——
        # 会话根本不存在时这个接口照样回 success: true,而设备压根没加进去。
        ok = await sm.join_session(session_id, req.device_id)
        if not ok:
            return JSONResponse(
                {"success": False, "error": f"会话不存在: {session_id}"},
                status_code=404,
            )
        # 向新设备推送会话历史
        history = sm.get_full_history(session_id)
        await connection_manager.send_to_device(
            req.device_id,
            {
                "type": "session_sync",
                "session_id": session_id,
                "history": history,
            },
        )
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
            history = history[-req.max_turns :]

        sent = await connection_manager.send_to_device(
            req.device_id,
            {
                "type": "session_sync",
                "session_id": session_id,
                "history": history,
            },
        )
        return JSONResponse(
            {
                "success": sent,
                "message": (
                    f"已同步 {len(history)} 条消息到设备 {req.device_id}" if sent else f"设备 {req.device_id} 不在线"
                ),
            }
        )

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

    # ──────────────────────────────────────────────────────────────────────
    # 跨设备统一上下文:对账(reconcile)+ 离线轮次补录(ingest)
    # ──────────────────────────────────────────────────────────────────────

    @router.post("/api/v1/sessions/reconcile")
    async def reconcile_session(req: ReconcileSessionRequest):
        """把设备本地/离线自建的会话认领到用户 canonical 主线(重连对账)。"""
        result = await reconcile_session_to_canonical(
            local_session_id=req.local_session_id,
            canonical_session_id=req.canonical_session_id,
            user_id=req.user_id,
            device_id=req.device_id,
            merge_history=req.merge_history,
            session_manager=sm,
            ws_connection_manager=connection_manager,
        )
        status_code = int(result.pop("status_code", 200))
        return JSONResponse(result, status_code=status_code)

    @router.post("/api/v1/sessions/ingest_turns")
    async def ingest_turns(req: IngestTurnsRequest):
        """补录手机离线期间记录的对话轮次到统一主线(先经别名解析)。"""
        result = await ingest_conversation_turns(
            session_id=req.session_id,
            turns=req.turns,
            user_id=req.user_id,
            device_id=req.device_id,
            session_manager=sm,
        )
        status_code = int(result.pop("status_code", 200))
        return JSONResponse(result, status_code=status_code)

    # ------------------------------------------------------------------
    # 会话证据导出、记忆管理、情绪状态重置（写好了没有入口的三件）
    # ------------------------------------------------------------------

    @router.get("/api/v1/sessions/{session_id}/evidence/export", dependencies=[Depends(require_auth)])
    async def export_session_evidence(session_id: str, include_lineage: bool = True):
        """会话证据链导出成 JSONL 下载（含血缘祖先的合并视图）。"""
        path = await asyncio.to_thread(get_session_manager().export_jsonl, session_id, include_lineage=include_lineage)
        if not path:
            return JSONResponse({"success": False, "error": f"会话不存在：{session_id}"}, status_code=404)
        return FileResponse(path, media_type="application/x-ndjson", filename=f"{session_id}.evidence.jsonl")

    @router.delete("/api/v1/memory/long-term/{namespace}", dependencies=[Depends(require_auth)])
    async def forget_memory_namespace(namespace: str):
        """忘掉长期记忆里的这一类（整个命名空间）。"""
        from core.cognitive.long_term_memory import get_long_term_memory

        removed = get_long_term_memory().forget_namespace(namespace=namespace)
        return {"success": True, "namespace": namespace, "removed": removed}

    @router.post("/api/v1/sessions/{session_id}/persona/reset", dependencies=[Depends(require_auth)])
    async def reset_session_persona(session_id: str):
        """把这个会话的情绪状态复位到平静基线。"""
        from core.diagnostics_internals import jsonable
        from core.persona.state_store import get_state_store

        return {"success": True, "state": jsonable(get_state_store().reset_state(session_id))}

    return router
