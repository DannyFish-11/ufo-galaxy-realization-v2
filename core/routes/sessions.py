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
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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

    # ── 迁移语义按作用域选,不按"调了哪个文件"选 ──────────────────────────
    #
    # 本仓有两套迁移语义,实测差异见 tests/test_session_migration_consistency.py:
    #   · 漫游 —— 会话跟着人走,同一时刻只在一台设备上(源设备移出 devices);
    #   · 共享 —— 一个会话同时挂在几台设备上,当前活跃的是某一台(源设备保留)。
    #
    # 在此之前,用哪一种**取决于调用方调了哪条路径**,而不是取决于场景 —— 那意味着
    # 同一次迁移走 REST 和走网关会得到不同的产品行为,而两边都不认为自己错了。
    #
    # 现在由 core.scope_authority 按作用域判:local → 漫游,cross_device → 共享,
    # transition/判不出来 → 不迁(见该模块头)。判据只有那一处,这里不重列规则。
    _authority = None
    try:
        from core.scope_authority import current_scope, require_migration  # noqa: PLC0415

        # require_migration 而不是"取判定再自己看一眼":它在不许迁的档位**抛异常**。
        # 迁移是有副作用的动作,返回值会被忽略,异常不会 —— 漏判一次的后果是会话
        # 跑到不该去的地方。
        _authority = require_migration(session_id, current_scope())
    except ImportError:  # pragma: no cover — 判据模块缺失时不改变既有行为
        logger.debug("scope_authority 不可用,迁移沿用既有(共享)语义")
    except Exception as exc:  # ScopeAuthorityRefused 及其它判定失败
        logger.warning("迁移被作用域判据拒绝: session=%s %s", session_id, exc)
        return {
            "success": False,
            "status_code": 409,
            "error": str(exc),
        }

    active_device = getattr(session, "active_device", "") or ""
    effective_source = source_device or active_device
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

    # ── 两阶段提交:先把上下文送到,送到了才改状态 ──────────────────────────
    #
    # 改前这里是先改状态再推送,而且**推送的返回值被丢掉了**
    # (``send_to_device`` 返回 bool,原来只是 ``await`` 了一下)。后果是:目标设备
    # 根本没收到会话,这个函数照样返回 ``success: True``,而中心侧的
    # ``active_device`` 已经指向目标设备并落盘 —— 用户还在源设备上说话,系统认为
    # 会话在另一台机器上。两边都不对,而且没有任何一处会报错。
    #
    # ``galaxy_gateway/session_roaming.py`` 那条路一直是两阶段提交(推送失败回滚),
    # 这里把同一个形状补上 —— 两条迁移路径在"失败了算不算迁移"这件事上必须一致,
    # 否则走哪条路决定了会不会丢会话。
    history = sm.get_full_history(session_id)
    push_ok = await cm.send_to_device(
        target_device,
        {
            "type": "session_sync",
            "session_id": session_id,
            "history": history,
            "context": getattr(session, "metadata", {}),
            "migrated_from": effective_source,
        },
    )
    if not push_ok:
        logger.error(
            "migrate_session_via_canonical_manager: 上下文推送到 %s 失败,迁移未发生",
            target_device,
        )
        return {
            "success": False,
            "status_code": 502,
            "error": (f"Context push to '{target_device}' failed; session '{session_id}' was not migrated"),
        }

    if target_device not in session.devices:
        session.devices.append(target_device)
    session.active_device = target_device
    session.updated_at = time.time()

    # 漫游语义下源设备要**移出**会话 —— 这正是漫游与共享的那处行为差异。
    # 共享语义下源设备保留(它仍是这个会话的成员,只是不再是 active)。
    if _authority is not None and _authority.migration == "roaming" and effective_source:
        if effective_source in session.devices and effective_source != target_device:
            session.devices.remove(effective_source)

    try:
        sm._persist_state()
    except Exception as exc:
        logger.warning("migrate_session_via_canonical_manager: persist_state failed: %s", exc)

    # 通知源设备:它已经不是 active 了。这一条送不到不算迁移失败 ——
    # 会话本体已经在目标设备上了,源设备收不到通知只是它自己不知道,
    # 与"目标设备没拿到会话"是两种严重程度。
    if effective_source:
        await cm.send_to_device(
            effective_source,
            {
                "type": "session_migrated",
                "session_id": session_id,
                "target_device": target_device,
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
    except Exception as exc:
        logger.warning("migrate_session_via_canonical_manager: audit append failed: %s", exc)

    return {
        "success": True,
        "status_code": 200,
        "session_id": session_id,
        "source_device": effective_source,
        "target_device": target_device,
        "active_device": session.active_device,
        "message": f"Session successfully migrated to {target_device}",
        "history_count": len(history),
        # 用了哪种语义、凭什么 —— 进响应,让"为什么源设备还在/不在了"说得出来。
        "scope_authority": (_authority.to_dict() if _authority is not None else None),
    }


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
        session = sm.create_session(req.user_id, req.device_id)
        return JSONResponse(
            {
                "success": True,
                "session": session.to_summary(),
            }
        )

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

    return router
