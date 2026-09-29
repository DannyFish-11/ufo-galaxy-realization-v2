#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Security Policy Routes (Phase 4)
==========================================

Exposes a configurable zero-trust security policy engine via REST.

Endpoints
---------
GET  /api/v1/security/policy
    Return the active policy table (JSON).

PUT  /api/v1/security/policy
    Replace the active policy table with a new one (JSON body). API auth.

POST /api/v1/security/policy/evaluate
    Evaluate an action/tool against the active policy and return the
    computed RiskLevel + whether HITL is required.

GET  /api/v1/security/tool-permissions
    Tool permission policies the ReAct loop and skill registry check against.

POST /api/v1/security/tool-permissions
    Add one tool permission policy (in-process; restart restores defaults). API auth.

Policy format
-------------
The policy table is a JSON object with a top-level ``rules`` list::

    {
        "rules": [
            {
                "match": {"tool": "shell_exec"},
                "risk_level": "high",
                "require_hitl": true
            },
            {
                "match": {"action_prefix": "delete_"},
                "risk_level": "critical",
                "require_hitl": true
            }
        ],
        "default_risk_level": "low",
        "default_require_hitl": false
    }

Each rule in ``rules`` may contain any subset of:
  * ``tool``         – exact tool name match
  * ``action``       – exact action name match
  * ``action_prefix``– prefix match on action name
  * ``action_regex`` – regex match on action name (Python ``re.search``)

The first matching rule wins.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.auth import require_auth

logger = logging.getLogger("Galaxy.API.SecurityPolicy")

# ---------------------------------------------------------------------------
# Default built-in policy
# ---------------------------------------------------------------------------

_DEFAULT_POLICY: Dict[str, Any] = {
    "rules": [
        # Shell execution is always high-risk
        {"match": {"tool": "shell_exec"}, "risk_level": "high", "require_hitl": True},
        {"match": {"tool": "bash"}, "risk_level": "high", "require_hitl": True},
        {"match": {"tool": "exec"}, "risk_level": "high", "require_hitl": True},
        # Delete / destroy operations
        {"match": {"action_prefix": "delete_"}, "risk_level": "critical", "require_hitl": True},
        {"match": {"action_prefix": "destroy_"}, "risk_level": "critical", "require_hitl": True},
        {"match": {"action_prefix": "rm_"}, "risk_level": "high", "require_hitl": True},
        # Format / wipe operations
        {
            "match": {"action_regex": r"(?i)(format|wipe|erase|drop_table)"},
            "risk_level": "critical",
            "require_hitl": True,
        },
        # File write operations
        {"match": {"action_prefix": "write_"}, "risk_level": "medium", "require_hitl": False},
        {"match": {"action_prefix": "upload_"}, "risk_level": "medium", "require_hitl": False},
        # Read-only operations — explicitly safe
        {"match": {"action_prefix": "read_"}, "risk_level": "low", "require_hitl": False},
        {"match": {"action_prefix": "list_"}, "risk_level": "low", "require_hitl": False},
        {"match": {"action_prefix": "get_"}, "risk_level": "low", "require_hitl": False},
    ],
    "default_risk_level": "low",
    "default_require_hitl": False,
}


# ---------------------------------------------------------------------------
# In-memory policy store (singleton)
# ---------------------------------------------------------------------------

_active_policy: Dict[str, Any] = dict(_DEFAULT_POLICY)


def get_policy() -> Dict[str, Any]:
    """Return the current active policy table."""
    return _active_policy


def set_policy(policy: Dict[str, Any]) -> None:
    """Replace the active policy table."""
    global _active_policy
    _active_policy = policy


def evaluate_policy(
    action: str = "",
    tool: str = "",
) -> Dict[str, Any]:
    """Evaluate *action* / *tool* against the active policy.

    Returns
    -------
    dict
        ``{"risk_level": str, "require_hitl": bool, "matched_rule": dict | None}``
    """
    policy = get_policy()
    rules: List[Dict[str, Any]] = policy.get("rules", [])
    default_risk = policy.get("default_risk_level", "low")
    default_hitl = policy.get("default_require_hitl", False)

    for rule in rules:
        match_spec: Dict[str, str] = rule.get("match", {})
        matched = False

        if "tool" in match_spec and tool:
            matched = match_spec["tool"] == tool

        if not matched and "action" in match_spec and action:
            matched = match_spec["action"] == action

        if not matched and "action_prefix" in match_spec and action:
            matched = action.startswith(match_spec["action_prefix"])

        if not matched and "action_regex" in match_spec and action:
            try:
                matched = bool(re.search(match_spec["action_regex"], action))
            except re.error:
                pass

        if matched:
            return {
                "risk_level": rule.get("risk_level", default_risk),
                "require_hitl": rule.get("require_hitl", default_hitl),
                "matched_rule": rule,
            }

    return {
        "risk_level": default_risk,
        "require_hitl": default_hitl,
        "matched_rule": None,
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_router() -> APIRouter:
    """Create and return the security policy routes router."""
    router = APIRouter()

    @router.get("/api/v1/security/policy")
    async def get_security_policy():
        """Return the active security policy table."""
        try:
            return JSONResponse(content={"ok": True, "policy": get_policy()})
        except Exception as exc:
            logger.error("get_security_policy failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    # 整张安全策略表可被这一个调用替换 —— 此前挂载时没有任何鉴权。
    @router.put("/api/v1/security/policy", dependencies=[Depends(require_auth)])
    async def update_security_policy(body: dict):
        """Replace the active security policy with the supplied JSON body.

        The body must be a valid policy object with a ``rules`` list.
        """
        try:
            if "rules" not in body or not isinstance(body["rules"], list):
                return JSONResponse(
                    status_code=422,
                    content={
                        "ok": False,
                        "error": "Policy body must contain a 'rules' list.",
                    },
                )
            set_policy(body)
            logger.info("Security policy updated (%d rules)", len(body["rules"]))
            return JSONResponse(content={"ok": True, "rules_count": len(body["rules"])})
        except Exception as exc:
            logger.error("update_security_policy failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.post("/api/v1/security/policy/evaluate")
    async def evaluate_action(body: dict):
        """Evaluate an action/tool name against the active policy.

        Request body::

            {"action": "delete_user", "tool": ""}

        Response::

            {"ok": true, "risk_level": "critical", "require_hitl": true, "matched_rule": {...}}
        """
        try:
            action = body.get("action", "")
            tool = body.get("tool", "")
            result = evaluate_policy(action=action, tool=tool)
            return JSONResponse(content={"ok": True, **result})
        except Exception as exc:
            logger.error("evaluate_action failed: %s", exc, exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(exc)},
            )

    @router.get("/api/v1/security/tool-permissions")
    async def list_tool_permissions():
        from core.tool_permissions import get_tool_permission_checker

        return JSONResponse(content={"ok": True, "policies": get_tool_permission_checker().list_policies()})

    @router.post("/api/v1/security/tool-permissions", dependencies=[Depends(require_auth)])
    async def add_tool_permission(body: dict):
        """追加一条工具权限策略。匹配时取最严格的一条，所以追加只会收紧、不会放宽已有策略。"""
        from pydantic import ValidationError

        from core.tool_permissions import ToolPermissionPolicy, get_tool_permission_checker

        try:
            policy = ToolPermissionPolicy(**body)
        except ValidationError as exc:
            return JSONResponse(status_code=422, content={"ok": False, "error": str(exc)})
        checker = get_tool_permission_checker()
        checker.add_policy(policy)
        logger.info("Tool permission policy added: %s", policy.tool_pattern)
        return JSONResponse(content={"ok": True, "policies": checker.list_policies()})

    return router
