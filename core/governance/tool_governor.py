#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Tool Governor (Phase 5.2)
====================================

Governs tool invocations with:

* **Allow / deny lists** – explicit per-tool name overrides.
* **Risk-tier policies** – broad action + rate-limit settings per tier.
* **Token-bucket rate limiting** – per-tool, configurable capacity and
  refill rate (capacity = ``rate_limit_per_minute / 60`` tokens/second).
* **Audit event emission** – every governance decision is recorded as a
  structured :class:`ToolDecision` and optionally forwarded to an
  :class:`AuditLedger`.

Design
------
* Rate-limit state is kept in a plain dict; bucket refill is done
  lazily on each ``check()`` call so there is no background timer.
* All state mutations are protected by an :class:`asyncio.Lock`.
* The governor is intentionally stateless with respect to long-term
  storage — callers that need persistence should layer a DB on top.

Usage
-----
    from core.governance.tool_governor import ToolGovernor, ToolRateLimitError
    from core.governance.policy_schema import load_governance_policy

    policy = load_governance_policy()
    governor = ToolGovernor(policy.tool_policy)

    decision = await governor.check(tool_name="bash", risk_tier="high")
    if not decision.allowed:
        raise PermissionError(decision.reason)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .policy_schema import ToolPolicy, RiskTierConfig

logger = logging.getLogger("Galaxy.Governance.ToolGovernor")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ToolRateLimitError(Exception):
    """Raised when a tool's rate limit is exhausted."""

    def __init__(self, tool_name: str, limit_per_minute: int) -> None:
        self.tool_name = tool_name
        self.limit_per_minute = limit_per_minute
        super().__init__(
            f"Rate limit exhausted for tool '{tool_name}': "
            f"max {limit_per_minute} calls/min"
        )


class ToolDeniedError(PermissionError):
    """Raised when a tool invocation is denied by governance policy."""

    def __init__(self, tool_name: str, reason: str) -> None:
        self.tool_name = tool_name
        self.reason = reason
        super().__init__(f"Tool '{tool_name}' denied: {reason}")


# ---------------------------------------------------------------------------
# Decision record
# ---------------------------------------------------------------------------

@dataclass
class ToolDecision:
    """Governance decision for a single tool invocation attempt."""

    tool_name: str
    allowed: bool
    reason: str
    risk_tier: str
    rate_limited: bool = False
    require_audit: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "allowed": self.allowed,
            "reason": self.reason,
            "risk_tier": self.risk_tier,
            "rate_limited": self.rate_limited,
            "require_audit": self.require_audit,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Token bucket
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Simple token-bucket for rate limiting.

    *capacity* tokens are available at t=0; tokens refill at *rate* tokens/s.
    Calling :meth:`consume` returns ``True`` when a token is available and
    consumes it, ``False`` when the bucket is empty.
    """

    __slots__ = ("capacity", "rate", "_tokens", "_last_refill")

    def __init__(self, rate_per_minute: int) -> None:
        self.capacity: float = max(float(rate_per_minute), 1.0)
        self.rate: float = rate_per_minute / 60.0          # tokens/second
        self._tokens: float = self.capacity
        self._last_refill: float = time.monotonic()

    def consume(self) -> bool:
        """Attempt to consume one token; return True on success."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        self._last_refill = now

        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False


# ---------------------------------------------------------------------------
# ToolGovernor
# ---------------------------------------------------------------------------

class ToolGovernor:
    """Central governance engine for tool invocations.

    Parameters
    ----------
    tool_policy:
        :class:`ToolPolicy` parsed from the governance config.
    ledger:
        Optional :class:`~core.control_plane.audit_ledger.AuditLedger`
        instance; when provided, all ``require_audit`` decisions are
        appended to it.
    """

    def __init__(
        self,
        tool_policy: ToolPolicy,
        ledger: Optional[Any] = None,          # AuditLedger — avoid circular import
    ) -> None:
        self._policy = tool_policy
        self._ledger = ledger
        self._lock = asyncio.Lock()

        # tool_name -> _TokenBucket
        self._buckets: Dict[str, _TokenBucket] = {}

        # Audit log (in-memory list of ToolDecision)
        self._audit_log: List[ToolDecision] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_tier_config(self, tool_name: str, risk_tier: str) -> RiskTierConfig:
        """Resolve the effective :class:`RiskTierConfig` for *tool_name*."""
        # Per-tool override takes highest priority
        if tool_name in self._policy.per_tool_overrides:
            return self._policy.per_tool_overrides[tool_name]
        # Then risk-tier config
        if risk_tier in self._policy.risk_tiers:
            return self._policy.risk_tiers[risk_tier]
        # Default
        return RiskTierConfig(
            action=self._policy.default_action.value,
            rate_limit_per_minute=60,
        )

    def _get_bucket(self, tool_name: str, rate_per_minute: int) -> _TokenBucket:
        """Return (or lazily create) the token bucket for *tool_name*."""
        if tool_name not in self._buckets:
            self._buckets[tool_name] = _TokenBucket(rate_per_minute)
        return self._buckets[tool_name]

    def _emit_audit(self, decision: ToolDecision) -> None:
        """Record the decision in the in-memory log and optionally ledger."""
        self._audit_log.append(decision)
        if self._ledger is not None and decision.require_audit:
            try:
                from core.control_plane.audit_ledger import EventType, Severity
                self._ledger.append(
                    event_type=EventType.TOOL_GOVERNANCE_DECISION,
                    severity=Severity.WARNING if not decision.allowed else Severity.INFO,
                    source="tool_governor",
                    message=decision.reason,
                    payload=decision.to_dict(),
                )
            except Exception:
                pass  # Never fail because of audit

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        tool_name: str,
        risk_tier: str = "moderate",
    ) -> ToolDecision:
        """Evaluate a tool invocation request.

        Parameters
        ----------
        tool_name:
            Name of the tool being invoked (must match exactly or be in a
            deny/allow list).
        risk_tier:
            Risk classification of the tool: ``safe``, ``moderate``,
            ``high``, or ``critical``.

        Returns
        -------
        ToolDecision
            Always returned (never raises).  Callers should check
            :attr:`ToolDecision.allowed` and raise as appropriate.
        """
        async with self._lock:
            # 1. Explicit deny list
            if tool_name in self._policy.deny_list:
                decision = ToolDecision(
                    tool_name=tool_name,
                    allowed=False,
                    reason="tool is on the explicit deny list",
                    risk_tier=risk_tier,
                    require_audit=True,
                )
                self._emit_audit(decision)
                return decision

            # 2. Explicit allow list (bypasses tier check but still rate-limited)
            on_allow_list = bool(self._policy.allow_list) and tool_name in self._policy.allow_list

            # 3. Tier config
            tier_cfg = self._resolve_tier_config(tool_name, risk_tier)

            # 4. Tier-level deny
            if not on_allow_list and tier_cfg.action == "deny":
                decision = ToolDecision(
                    tool_name=tool_name,
                    allowed=False,
                    reason=f"tier '{risk_tier}' action is deny",
                    risk_tier=risk_tier,
                    require_audit=tier_cfg.require_audit,
                )
                self._emit_audit(decision)
                return decision

            # 5. Rate limit check (skip for rate_limit = 0 which means fully blocked)
            rate_limit = tier_cfg.rate_limit_per_minute
            if rate_limit == 0:
                decision = ToolDecision(
                    tool_name=tool_name,
                    allowed=False,
                    reason=f"rate limit for tier '{risk_tier}' is 0 (blocked)",
                    risk_tier=risk_tier,
                    rate_limited=True,
                    require_audit=tier_cfg.require_audit,
                )
                self._emit_audit(decision)
                return decision

            bucket = self._get_bucket(tool_name, rate_limit)
            if not bucket.consume():
                decision = ToolDecision(
                    tool_name=tool_name,
                    allowed=False,
                    reason=f"rate limit exceeded ({rate_limit} calls/min)",
                    risk_tier=risk_tier,
                    rate_limited=True,
                    require_audit=tier_cfg.require_audit,
                )
                self._emit_audit(decision)
                return decision

            # 6. Allowed
            decision = ToolDecision(
                tool_name=tool_name,
                allowed=True,
                reason="allowed by governance policy",
                risk_tier=risk_tier,
                require_audit=tier_cfg.require_audit,
            )
            self._emit_audit(decision)
            return decision

    def get_audit_log(
        self,
        tool_name: Optional[str] = None,
        allowed: Optional[bool] = None,
        limit: int = 100,
    ) -> List[ToolDecision]:
        """Return recent audit log entries, newest first."""
        entries = list(reversed(self._audit_log))
        if tool_name is not None:
            entries = [e for e in entries if e.tool_name == tool_name]
        if allowed is not None:
            entries = [e for e in entries if e.allowed == allowed]
        return entries[:limit]

    def clear_audit_log(self) -> None:
        """Clear the in-memory audit log."""
        self._audit_log.clear()

    def reset_bucket(self, tool_name: str) -> None:
        """Reset the token bucket for *tool_name* (useful in tests)."""
        self._buckets.pop(tool_name, None)

    def get_policy_summary(self) -> Dict[str, Any]:
        """Return a human-readable summary of the active tool policy."""
        return {
            "default_action": self._policy.default_action.value,
            "allow_list": self._policy.allow_list,
            "deny_list": self._policy.deny_list,
            "risk_tiers": {
                tier: cfg.model_dump()
                for tier, cfg in self._policy.risk_tiers.items()
            },
            "per_tool_overrides": {
                tool: cfg.model_dump()
                for tool, cfg in self._policy.per_tool_overrides.items()
            },
        }
