"""
Galaxy – HITL Approval Routes
================================

Exposes the Control Plane security interceptor via REST so operators can
approve or deny pending high-risk command approvals.

Endpoints
---------
GET  /api/v1/approvals
    List all pending approval requests.

GET  /api/v1/approvals/{request_id}
    Get details of a specific approval request.

POST /api/v1/approvals/{request_id}
    Approve or deny an approval request.

    Body:
        {
            "action": "approve" | "deny",
            "token": "<ack_token>",          # required for approve
            "operator": "<operator_name>",   # optional
            "reason": "<deny_reason>"        # optional, used for deny
        }
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API.Approvals")


class ApprovalActionRequest(BaseModel):
    action: str = "approve"  # "approve" | "deny"
    token: Optional[str] = None  # required when action == "approve"
    operator: str = ""
    reason: str = ""  # optional deny reason
    # 审批分级:approve 时授权的档位(所有者的决定:默认记「同一个动作 + 同一个对象」到这段对话结束)。
    #   session=本会话(默认) once=只这一次 always=一直允许(持久化,面板上能撤)
    grant: str = "session"


def _publish(request_id: str = "") -> None:
    """待批清单变了:推给桌面外壳(面板据此刷新),岛上那张卡撤掉。永不抛出。"""
    try:
        from core.approval_gate import publish_pending, remove_approval_card

        if request_id:
            remove_approval_card(request_id)
        publish_pending()
    except Exception as exc:  # noqa: BLE001
        logger.debug("待批清单没推出去: %s", exc)


def _record_grant(req, body: ApprovalActionRequest) -> None:
    """按人选的档位落授权(「动作 × 对象」,本会话的绑那段对话),并告诉还在等的那一方选了哪档。

    * 有人在等这一条(``waited``):批准本身就放行了这一次,「只这一次」不再另记一笔;
    * 没人在等(排队的):记下来,调用方重试时凭它通过。
    """
    try:
        from core.approval_gate import DEFAULT_SCOPE, GRANT_CHOICES, node_key
        from core.autonomy_policy import get_grant_store

        ctx = req.context if isinstance(req.context, dict) else {}
        scope = body.grant if body.grant in GRANT_CHOICES else DEFAULT_SCOPE
        ctx["granted_scope"] = scope
        key = ctx.get("approval_key")
        if not key and ctx.get("node_id") and ctx.get("node_action"):
            key = node_key(ctx["node_id"], ctx["node_action"])
        if key and not (ctx.get("waited") and scope == "once"):
            get_grant_store().grant_key(
                key,
                scope,
                target=str(ctx.get("target") or ""),
                session_id=str(ctx.get("session_id") or ""),
                operator=body.operator or "api_operator",
            )
    except Exception as exc:  # noqa: BLE001 — 授权没记上不影响这次批准本身
        logger.warning("grant 记录失败(审批本身已生效): %s", exc)
    _publish(req.request_id)


def create_router() -> APIRouter:
    """Create and return the approvals routes router."""
    router = APIRouter()

    def _registry():
        from core.control_plane._globals import get_approval_registry

        return get_approval_registry()

    @router.get("/api/v1/approvals")
    async def list_pending_approvals():
        """List all pending HITL approval requests."""
        try:
            registry = _registry()
            pending = registry.list_pending()
            return JSONResponse(
                content={
                    "ok": True,
                    "count": len(pending),
                    "approvals": [req.model_dump(mode="json") for req in pending],
                }
            )
        except Exception as exc:
            logger.error("list_pending_approvals failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "internal error"},
            )

    @router.get("/api/v1/approvals/{request_id}")
    async def get_approval(request_id: str):
        """Get details of a specific approval request."""
        try:
            registry = _registry()
            req = registry.get_request(request_id)
            if req is None:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"Approval request '{request_id}' not found"},
                )
            return JSONResponse(content={"ok": True, "approval": req.model_dump(mode="json")})
        except Exception as exc:
            logger.error("get_approval failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "internal error"},
            )

    @router.post("/api/v1/approvals/{request_id}")
    async def resolve_approval(request_id: str, body: ApprovalActionRequest):
        """Approve or deny a pending HITL approval request.

        For **approve**: supply the ``token`` field (the ``ack_token`` shown
        in the approval request details).

        For **deny**: set ``action="deny"`` and optionally provide a
        ``reason`` string.
        """
        try:
            registry = _registry()
            req = registry.get_request(request_id)
            if req is None:
                return JSONResponse(
                    status_code=404,
                    content={"ok": False, "error": f"Approval request '{request_id}' not found"},
                )

            if body.action == "approve":
                if not body.token:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "ok": False,
                            "error": "token is required for approve action",
                            "hint": "Use the ack_token from GET /api/v1/approvals/{request_id}",
                        },
                    )
                success = registry.ack(
                    request_id,
                    body.token,
                    operator=body.operator or "api_operator",
                )
                if not success:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "ok": False,
                            "error": "Approval failed: invalid token or request already resolved",
                        },
                    )
                _record_grant(req, body)
                return JSONResponse(
                    content={
                        "ok": True,
                        "result": "approved",
                        "request_id": request_id,
                    }
                )

            elif body.action == "deny":
                success = registry.deny(
                    request_id,
                    operator=body.operator or "api_operator",
                    reason=body.reason or "Denied via API",
                )
                _publish(request_id)
                return JSONResponse(
                    content={
                        "ok": success,
                        "result": "denied" if success else "already_resolved",
                        "request_id": request_id,
                    }
                )

            else:
                return JSONResponse(
                    status_code=400,
                    content={
                        "ok": False,
                        "error": f"Unknown action '{body.action}'; use 'approve' or 'deny'",
                    },
                )

        except Exception as exc:
            logger.error("resolve_approval failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": "internal error"},
            )

    # ── 授权记录管理(审批分级配套;独立路径避免与 {request_id} 撞) ──────────
    @router.get("/api/v1/approval-grants")
    async def list_grants():
        """列出全部授权记录(always 持久 / session / once 待消费),供面板展示与撤销。"""
        try:
            from core.autonomy_policy import get_grant_store

            return JSONResponse(content={"ok": True, "grants": get_grant_store().list_grants()})
        except Exception as exc:  # noqa: BLE001
            logger.error("list_grants failed: %s", exc, exc_info=True)
            return JSONResponse(status_code=500, content={"ok": False, "error": "internal error"})

    @router.delete("/api/v1/approval-grants/{grant_key:path}")
    async def revoke_grant(grant_key: str):
        """撤销一条授权(key 形如 "Node_36_UIAWindows:click")。「永久允许」由此收回。"""
        try:
            from core.autonomy_policy import get_grant_store

            ok = get_grant_store().revoke(grant_key)
            return JSONResponse(content={"ok": ok, "revoked": grant_key if ok else None})
        except Exception as exc:  # noqa: BLE001
            logger.error("revoke_grant failed: %s", exc, exc_info=True)
            return JSONResponse(status_code=500, content={"ok": False, "error": "internal error"})

    return router
