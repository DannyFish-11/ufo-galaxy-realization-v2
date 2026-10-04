"""core/session_migration.py — 会话迁移的规范面（路线图 D3）。

一次迁移只有这一个入口：:func:`migrate_session`。核心 REST（``POST /api/v1/sessions/migrate``）、
网关 REST（``POST /api/v1/sessions/{id}/migrate``）、网关 WS 的 ``session_migrate``、安卓桥的
``session_migrate`` 都调它。

为什么要有它
------------
此前迁移的实现放在路由文件 ``core/routes/sessions.py`` 里（``migrate_session_via_canonical_manager``），
网关和安卓桥从一个路由模块里 import 它；而 ``legacy_paths`` 为 ``SessionRoamingManager`` 点名的规范替代
（``core.canonical_session_axis`` + ``core.attached_runtime_session``）**都不提供迁移**。更实在的问题是：
本仓有两个会话存储，迁移只认其中一个 ——

- **核心会话**（``core.session_manager``）：对话主线。REST 建的、聊天用的都在这里；
- **漫游会话**（``SessionRoamingManager``）：唤醒事件建的（``core.e2e_orchestrator.process_wake_event``）。
  网关的 ``GET /api/v1/sessions`` 列的是它们。

网关列出来的漫游会话，拿同一个网关的迁移端点去迁会 404 —— 列表和迁移看的不是同一个存储；而漫游
存储自己的迁移引擎（``SessionRoamingManager.migrate_session``）只被一个没人调用的「注意力转移自动迁移」
调用，等于没有入口。

它怎么做
--------
1. **先找会话在哪个存储里**：先核心、再漫游；都没有 → 404。**两个存储不合并**（合出来的只是第三个，
   见结论 ``session-migration-canonical-surface``）。
2. **作用域判据**（``core.scope_authority.require_migration``）：两个存储一样过这道门；不许迁 → 409。
3. **执行**：核心会话走下面的两阶段提交（先把上下文送到，送到了才改状态）；漫游会话交给
   ``SessionRoamingManager.migrate_session`` —— 它本来就是两阶段提交，这里不重写。
4. 返回形状两个存储一致，多两个键：``store``（``core`` / ``session_roaming``）与
   ``migration_semantics``（``roaming`` / ``shared``）。漫游存储一次只挂一台设备，天然是漫游语义。
5. 成功后发 ``SESSION_MIGRATED`` 事件；``core.event_bridge`` 把它推给前端。漫游会话由
   ``SessionRoamingManager`` 的迁移回调发（``event_bridge`` 已改为经 ``set_migration_callback`` 挂上）。

``core/`` 取漫游存储走 ``core.upper_ports``（端口 ``gateway.session_roaming.session_roaming``），不 import 网关。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("Galaxy.SessionMigration")

STORE_CORE = "core"
STORE_ROAMING = "session_roaming"


async def migrate_session(
    *,
    session_id: str,
    target_device: str,
    source_device: str = "",
    context_override: Optional[Dict[str, Any]] = None,
    session_manager: Any = None,
    ws_connection_manager: Any = None,
    roaming_manager: Any = None,
) -> Dict[str, Any]:
    """把 *session_id* 迁到 *target_device*。返回 ``success`` / ``status_code`` / ``store`` / … 的字典。"""
    if session_manager is None:
        from core.session_manager import get_session_manager

        session_manager = get_session_manager()
    if ws_connection_manager is None:
        from core.routes._shared import connection_manager as ws_connection_manager

    session = session_manager.get_session(session_id)
    roaming = None
    if session is None:
        roaming = roaming_manager if roaming_manager is not None else _roaming_store()
        if roaming is None or roaming.get_session(session_id) is None:
            return {
                "success": False,
                "status_code": 404,
                "error": f"Session '{session_id}' not found",
            }

    authority, refused = _scope_gate(session_id)
    if refused is not None:
        return refused

    if session is not None:
        result = await _migrate_core_session(
            session,
            session_id=session_id,
            target_device=target_device,
            source_device=source_device,
            context_override=context_override,
            sm=session_manager,
            cm=ws_connection_manager,
            authority=authority,
        )
        result["store"] = STORE_CORE
        if result.get("success"):
            result["migration_semantics"] = getattr(authority, "migration", None) or "shared"
            _announce(session_id, result.get("source_device") or "", target_device)
        return result

    return await _migrate_roaming_session(
        roaming,
        session_id=session_id,
        target_device=target_device,
        source_device=source_device,
        context_override=context_override,
        authority=authority,
    )


def close_roaming_session(session_id: str) -> Dict[str, Any]:
    """关闭一个**漫游会话**：状态 → closed，设备映射释放，落盘。核心 REST 与网关 REST 都调它。

    只有漫游存储有「关闭」这个状态；核心会话（``core.session_manager``）是对话主线，不关闭，
    只归档 / 导出。所以这里不会去碰核心会话 —— 找不到漫游会话就是 404，不是"关了个寂寞"。
    """
    roaming = _roaming_store()
    if roaming is None or not roaming.get_session(session_id):
        return {"success": False, "status_code": 404, "error": f"Roaming session not found: {session_id}"}
    roaming.close_session(session_id)
    return {
        "success": True,
        "status_code": 200,
        "store": STORE_ROAMING,
        "session": roaming.get_session(session_id).to_dict(),
    }


def _roaming_store() -> Any:
    try:
        from core import upper_ports

        return upper_ports.resolve("gateway.session_roaming.session_roaming")
    except ImportError:  # PortUnavailable 继承 ImportError：网关不在就只有核心存储
        return None


async def _migrate_roaming_session(
    roaming: Any,
    *,
    session_id: str,
    target_device: str,
    source_device: str,
    context_override: Optional[Dict[str, Any]],
    authority: Any,
) -> Dict[str, Any]:
    """漫游会话：交给 ``SessionRoamingManager.migrate_session``（它自己是两阶段提交，推送失败回滚）。"""
    session = roaming.get_session(session_id)
    current = str(getattr(session, "device_id", "") or "")
    if source_device and source_device != current:
        return {
            "success": False,
            "status_code": 409,
            "store": STORE_ROAMING,
            "error": f"Device '{source_device}' is not part of session '{session_id}'. Current device: {current}",
        }
    if context_override:
        meta = session.context.meta
        meta.setdefault("migration_context", {})
        meta["migration_context"].update(dict(context_override))

    ok = await roaming.migrate_session(session_id, target_device)
    if not ok:
        return {
            "success": False,
            "status_code": 502,
            "store": STORE_ROAMING,
            "error": f"Context push to '{target_device}' failed; session '{session_id}' was not migrated",
        }
    return {
        "success": True,
        "status_code": 200,
        "store": STORE_ROAMING,
        "migration_semantics": "roaming",
        "session_id": session_id,
        "source_device": current,
        "target_device": target_device,
        "active_device": target_device,
        "message": f"Session successfully migrated to {target_device}",
        "history_count": len(getattr(session.context, "history", []) or []),
        "scope_authority": (authority.to_dict() if authority is not None else None),
    }


def _announce(session_id: str, source_device: str, target_device: str) -> None:
    """发 ``SESSION_MIGRATED``。事件总线不在只是前端少一条推送，不影响迁移本身。"""
    try:
        from integration.event_bus import EventType, event_bus

        event_bus.publish_sync(
            EventType.SESSION_MIGRATED,
            source="session_migration",
            data={"session_id": session_id, "from_device": source_device, "to_device": target_device},
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("SESSION_MIGRATED 未发出: %s", exc)


def _scope_gate(session_id: str) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """作用域判据。返回 ``(判定, None)`` 或 ``(None, 拒绝时的响应)``。两个存储都先过这道门。"""
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
    try:
        from core.scope_authority import current_scope, require_migration  # noqa: PLC0415

        # require_migration 而不是"取判定再自己看一眼":它在不许迁的档位**抛异常**。
        # 迁移是有副作用的动作,返回值会被忽略,异常不会 —— 漏判一次的后果是会话
        # 跑到不该去的地方。
        return require_migration(session_id, current_scope()), None
    except ImportError:  # pragma: no cover — 判据模块缺失时不改变既有行为
        logger.debug("scope_authority 不可用,迁移沿用既有(共享)语义")
        return None, None
    except Exception as exc:  # ScopeAuthorityRefused 及其它判定失败
        logger.warning("迁移被作用域判据拒绝: session=%s %s", session_id, exc)
        return None, {
            "success": False,
            "status_code": 409,
            "error": str(exc),
        }


async def _migrate_core_session(
    session: Any,
    *,
    session_id: str,
    target_device: str,
    source_device: str,
    context_override: Optional[Dict[str, Any]],
    sm: Any,
    cm: Any,
    authority: Any,
) -> Dict[str, Any]:
    """核心会话（``core.session_manager``）的迁移引擎。原 ``core/routes/sessions.py`` 里的实现搬来，
    只把作用域判据提到了 :func:`_scope_gate`（两个存储共用）。"""
    _authority = authority
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


__all__ = ["STORE_CORE", "STORE_ROAMING", "migrate_session"]
