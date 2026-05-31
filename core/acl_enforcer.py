#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/acl_enforcer.py
====================
PR-5 Capability 5 — ACL Enforcer

Validates TaskEnvelope against a permission policy before execution:
  1. Checks ``permission_level`` against the caller's granted level.
  2. Checks ``required_capabilities`` against the executing agent's caps.
  3. Emits an audit event (M2 ``agent.state`` / ``skill.invoke``) for every
     check — pass or fail — so the audit trail is always complete.

Policy is read from ``config/acl_policy.json`` if present; defaults are
applied otherwise (fail-open at level 0–1, fail-closed at 2–3 when no
caller level is provided).

Usage::

    from core.acl_enforcer import get_acl_enforcer

    enforcer = get_acl_enforcer()
    result = enforcer.check(
        envelope=envelope,
        caller_level=1,           # 0=anonymous … 3=system
        agent_capabilities=["screen", "filesystem"],
    )
    if not result.allowed:
        raise PermissionError(result.reason)
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ACLEnforcer")

_POLICY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "config", "acl_policy.json",
)

# Default policy: levels 0 and 1 require no special handling; levels 2+ need
# an explicit caller_level grant ≥ the task's permission_level.
_DEFAULT_POLICY: Dict[str, Any] = {
    "strict_above_level": 1,   # levels > this require explicit grant
    "default_agent_capabilities": [],
    "audit_all": True,
}


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ACLCheckResult:
    allowed: bool = True
    reason: str = ""
    task_id: str = ""
    permission_level: int = 0
    required_capabilities: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    caller_level: int = 0


# ---------------------------------------------------------------------------
# ACLEnforcer
# ---------------------------------------------------------------------------

class ACLEnforcer:
    """Pre-execution ACL check for TaskEnvelope objects.

    Emits an audit event on every check regardless of outcome.
    """

    def __init__(self, policy: Optional[Dict[str, Any]] = None) -> None:
        self._policy = self._load_policy(policy)

    # ── Public API ──────────────────────────────────────────────────────────

    def check(
        self,
        envelope: Any,
        caller_level: int = 0,
        agent_capabilities: Optional[List[str]] = None,
    ) -> ACLCheckResult:
        """Check *envelope* against ACL policy.

        Parameters
        ----------
        envelope:
            A ``TaskEnvelope`` (or any object with ``task_id``,
            ``permission_level``, ``required_capabilities``).
        caller_level:
            The privilege level of the caller (0=anonymous … 3=system).
        agent_capabilities:
            Capabilities the executing agent currently has.  Defaults to the
            policy ``default_agent_capabilities``.
        """
        agent_caps: List[str] = list(
            agent_capabilities
            if agent_capabilities is not None
            else self._policy.get("default_agent_capabilities", [])
        )

        # ── Permission level check ───────────────────────────────────────────
        strict_above = self._policy.get("strict_above_level", 1)
        task_level: int = getattr(envelope, "permission_level", 0)
        req_caps: List[str] = list(getattr(envelope, "required_capabilities", []))

        allowed = True
        reason = ""

        if task_level > strict_above and caller_level < task_level:
            allowed = False
            reason = (
                f"permission_level {task_level} requires caller_level ≥ {task_level}, "
                f"got {caller_level}"
            )

        # ── Capability check ─────────────────────────────────────────────────
        missing = [c for c in req_caps if c not in agent_caps]
        if missing and allowed:
            allowed = False
            reason = f"missing required_capabilities: {missing}"

        result = ACLCheckResult(
            allowed=allowed,
            reason=reason,
            task_id=getattr(envelope, "task_id", ""),
            permission_level=task_level,
            required_capabilities=req_caps,
            missing_capabilities=missing,
            caller_level=caller_level,
        )

        self._emit_audit(envelope, result)
        return result

    # ── Audit event emission ─────────────────────────────────────────────────

    def _emit_audit(self, envelope: Any, result: ACLCheckResult) -> None:
        """Emit an M2 audit event regardless of ACL outcome."""
        outcome = "allowed" if result.allowed else "denied"
        logger.info(
            "acl.audit | task_id=%s permission_level=%d caller_level=%d "
            "required_caps=%s outcome=%s reason=%r",
            result.task_id,
            result.permission_level,
            result.caller_level,
            result.required_capabilities,
            outcome,
            result.reason or "ok",
        )
        try:
            from integration.event_bus import event_bus, EventType
            et = getattr(EventType, "SKILL_INVOKE", None)
            if et is None:
                return
            event_bus.publish_sync(et, "acl_enforcer", {
                "task_id": result.task_id,
                "trace_id": getattr(envelope, "trace_id", ""),
                "session_id": getattr(envelope, "session_id", None),
                "tool_name": getattr(envelope, "tool_name", ""),
                "permission_level": result.permission_level,
                "caller_level": result.caller_level,
                "required_capabilities": result.required_capabilities,
                "missing_capabilities": result.missing_capabilities,
                "outcome": outcome,
                "reason": result.reason,
                "ts": time.time(),
            })
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ── Policy loading ───────────────────────────────────────────────────────

    @staticmethod
    def _load_policy(override: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        if override is not None:
            return {**_DEFAULT_POLICY, **override}
        if os.path.isfile(_POLICY_PATH):
            try:
                with open(_POLICY_PATH, encoding="utf-8") as f:
                    loaded = json.load(f)
                logger.debug("ACL policy loaded from %s", _POLICY_PATH)
                return {**_DEFAULT_POLICY, **loaded}
            except Exception as exc:
                logger.warning("Failed to load ACL policy (%s); using defaults.", exc)
        return dict(_DEFAULT_POLICY)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_enforcer: Optional[ACLEnforcer] = None


def get_acl_enforcer() -> ACLEnforcer:
    """Return (or lazily create) the module-level ACLEnforcer."""
    global _enforcer
    if _enforcer is None:
        _enforcer = ACLEnforcer()
    return _enforcer
