#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Governance API Routes (Phase 5.2)
==========================================

Exposes governance status and controls via REST.

Endpoints
---------
GET  /api/v1/governance/policy
    Return the active governance policy (model, budget, tool, queue sub-policies).

GET  /api/v1/governance/budget/{session_id}
    Return current budget utilisation for a given session.

POST /api/v1/governance/budget/record
    Record actual LLM usage (tokens + cost) for a session.

GET  /api/v1/governance/tools/policy
    Return the active tool policy summary.

POST /api/v1/governance/tools/check
    Evaluate a tool invocation against the active policy.
    Returns allowed / denied + reason.

GET  /api/v1/governance/tools/audit
    Return recent tool governance audit log.

GET  /api/v1/governance/queue/stats
    Return current task-queue metrics (depth, latency, backpressure).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("Galaxy.API.Governance")

# ---------------------------------------------------------------------------
# Module-level singleton references (populated by get_governance_router)
# ---------------------------------------------------------------------------

_budget_enforcer = None
_tool_governor = None
_task_queue = None
_policy = None


def _get_policy():
    global _policy
    if _policy is None:
        from core.governance.policy_schema import load_governance_policy
        _policy = load_governance_policy()
    return _policy


def _get_budget_enforcer():
    global _budget_enforcer
    if _budget_enforcer is None:
        from core.governance.budget_enforcer import BudgetEnforcer
        p = _get_policy()
        _budget_enforcer = BudgetEnforcer(p.budget_policy, p.model_policy)
    return _budget_enforcer


def _get_tool_governor():
    global _tool_governor
    if _tool_governor is None:
        from core.governance.tool_governor import ToolGovernor
        p = _get_policy()
        _tool_governor = ToolGovernor(p.tool_policy)
    return _tool_governor


def _get_task_queue():
    global _task_queue
    return _task_queue


def set_task_queue(queue) -> None:
    """Inject an existing :class:`AsyncTaskQueue` instance from the app startup."""
    global _task_queue
    _task_queue = queue


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class BudgetRecordRequest(BaseModel):
    session_id: str = Field(..., description="Session identifier")
    tenant_id: str = Field(default="default", description="Tenant identifier")
    model: str = Field(..., description="Model that was used")
    tokens_used: int = Field(..., ge=0)
    cost_usd: float = Field(..., ge=0)


class ToolCheckRequest(BaseModel):
    tool_name: str = Field(..., description="Name of the tool to evaluate")
    risk_tier: str = Field(default="moderate", description="Risk tier: safe/moderate/high/critical")


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_router() -> APIRouter:
    """Create and return the governance API router."""
    router = APIRouter()

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------

    @router.get("/api/v1/governance/policy")
    async def get_policy() -> JSONResponse:
        """Return the full active governance policy."""
        p = _get_policy()
        return JSONResponse(p.model_dump())

    # ------------------------------------------------------------------
    # Budget
    # ------------------------------------------------------------------

    @router.get("/api/v1/governance/budget/{session_id}")
    async def get_budget_status(
        session_id: str,
        tenant_id: str = "default",
    ) -> JSONResponse:
        """Return current budget utilisation for *session_id*."""
        enforcer = _get_budget_enforcer()
        status = await enforcer.get_status(session_id, tenant_id)
        return JSONResponse(status.to_dict())

    @router.post("/api/v1/governance/budget/record")
    async def record_budget_usage(req: BudgetRecordRequest) -> JSONResponse:
        """Record actual LLM usage after a call completes."""
        enforcer = _get_budget_enforcer()
        await enforcer.record_usage(
            session_id=req.session_id,
            tenant_id=req.tenant_id,
            model=req.model,
            tokens_used=req.tokens_used,
            cost_usd=req.cost_usd,
        )
        return JSONResponse({"ok": True, "session_id": req.session_id})

    # ------------------------------------------------------------------
    # Tool governance
    # ------------------------------------------------------------------

    @router.get("/api/v1/governance/tools/policy")
    async def get_tool_policy() -> JSONResponse:
        """Return the active tool policy summary."""
        governor = _get_tool_governor()
        return JSONResponse(governor.get_policy_summary())

    @router.post("/api/v1/governance/tools/check")
    async def check_tool(req: ToolCheckRequest) -> JSONResponse:
        """Evaluate a tool invocation against the active governance policy."""
        governor = _get_tool_governor()
        decision = await governor.check(
            tool_name=req.tool_name,
            risk_tier=req.risk_tier,
        )
        return JSONResponse(decision.to_dict())

    @router.get("/api/v1/governance/tools/audit")
    async def get_tool_audit(
        tool_name: Optional[str] = None,
        allowed: Optional[bool] = None,
        limit: int = 50,
    ) -> JSONResponse:
        """Return recent tool governance audit log entries."""
        governor = _get_tool_governor()
        entries = governor.get_audit_log(
            tool_name=tool_name,
            allowed=allowed,
            limit=limit,
        )
        return JSONResponse([e.to_dict() for e in entries])

    # ------------------------------------------------------------------
    # Queue metrics
    # ------------------------------------------------------------------

    @router.get("/api/v1/governance/queue/stats")
    async def get_queue_stats() -> JSONResponse:
        """Return current async task queue metrics."""
        q = _get_task_queue()
        if q is None:
            return JSONResponse({"available": False, "message": "task queue not initialised"})
        return JSONResponse({"available": True, **q.stats().to_dict()})

    return router
