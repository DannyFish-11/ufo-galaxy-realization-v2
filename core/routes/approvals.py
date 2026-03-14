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
    action: str = "approve"      # "approve" | "deny"
    token: Optional[str] = None  # required when action == "approve"
    operator: str = ""
    reason: str = ""             # optional deny reason


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
                content={"ok": False, "error": str(exc)},
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
            return JSONResponse(
                content={"ok": True, "approval": req.model_dump(mode="json")}
            )
        except Exception as exc:
            logger.error("get_approval failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
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
                content={"ok": False, "error": str(exc)},
            )

    return router
