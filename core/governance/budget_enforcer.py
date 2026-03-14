#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Budget Enforcer (Phase 5.2)
=====================================

Tracks token / USD cost usage per-session and per-day.  Integrates with
the LLM router: when a budget is about to be exceeded the enforcer either
downgrades the requested model to the fallback model or raises an explicit
:class:`BudgetExceededError` depending on the configured ``on_exceed``
policy.

Design
------
* All state is kept in plain dicts protected by an :class:`asyncio.Lock`.
  For distributed deployments callers should wrap this with a Redis backend.
* Costs are recorded **after** the LLM call returns its actual usage;
  *estimated* cost may be checked before the call via :meth:`check_budget`.
* Per-session budget resets never happen automatically — callers should
  create a new :class:`BudgetEnforcer` or call :meth:`reset_session` when
  a session ends.
* Per-day counters reset automatically at UTC midnight.

Usage
-----
    from core.governance.budget_enforcer import BudgetEnforcer
    from core.governance.policy_schema import load_governance_policy

    policy = load_governance_policy()
    enforcer = BudgetEnforcer(policy.budget_policy, policy.model_policy)

    # Before LLM call — check and possibly downgrade:
    model = await enforcer.enforce_pre_call(
        session_id="sess_abc",
        tenant_id="tenant_xyz",
        requested_model="gpt-4",
        estimated_cost_usd=0.05,
    )
    # model may be the fallback if budget was tight

    # After LLM call — record actual usage:
    await enforcer.record_usage(
        session_id="sess_abc",
        tenant_id="tenant_xyz",
        model="gpt-4",
        tokens_used=2000,
        cost_usd=0.06,
    )
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Dict, Optional

from .policy_schema import BudgetPolicy, ModelPolicy, OnBudgetExceed

logger = logging.getLogger("Galaxy.Governance.BudgetEnforcer")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BudgetExceededError(Exception):
    """Raised when a budget is exceeded and the policy action is ``deny``."""

    def __init__(
        self,
        scope: str,
        budget_usd: float,
        spent_usd: float,
        requested_usd: float,
    ) -> None:
        self.scope = scope
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd
        self.requested_usd = requested_usd
        super().__init__(
            f"Budget exceeded [{scope}]: limit={budget_usd:.4f} USD, "
            f"spent={spent_usd:.4f} USD, requested={requested_usd:.4f} USD"
        )


# ---------------------------------------------------------------------------
# Internal counters
# ---------------------------------------------------------------------------

class _Counter:
    """Simple monotonic cost counter that can be reset."""

    def __init__(self) -> None:
        self.total_usd: float = 0.0
        self.total_tokens: int = 0

    def add(self, cost_usd: float, tokens: int) -> None:
        self.total_usd += cost_usd
        self.total_tokens += tokens

    def reset(self) -> None:
        self.total_usd = 0.0
        self.total_tokens = 0


# ---------------------------------------------------------------------------
# BudgetStatus
# ---------------------------------------------------------------------------

class BudgetStatus:
    """Snapshot of budget utilisation for a given scope."""

    __slots__ = (
        "session_id", "tenant_id", "date_utc",
        "session_spent_usd", "session_limit_usd", "session_pct",
        "daily_spent_usd", "daily_limit_usd", "daily_pct",
        "tenant_daily_spent_usd", "tenant_daily_limit_usd", "tenant_daily_pct",
        "warning",
    )

    def __init__(
        self,
        session_id: str,
        tenant_id: str,
        date_utc: str,
        session_spent: float,
        session_limit: float,
        daily_spent: float,
        daily_limit: float,
        tenant_daily_spent: float,
        tenant_daily_limit: float,
        warning_threshold: float,
    ) -> None:
        self.session_id = session_id
        self.tenant_id = tenant_id
        self.date_utc = date_utc
        self.session_spent_usd = session_spent
        self.session_limit_usd = session_limit
        self.session_pct = (session_spent / session_limit) if session_limit else 0.0
        self.daily_spent_usd = daily_spent
        self.daily_limit_usd = daily_limit
        self.daily_pct = (daily_spent / daily_limit) if daily_limit else 0.0
        self.tenant_daily_spent_usd = tenant_daily_spent
        self.tenant_daily_limit_usd = tenant_daily_limit
        self.tenant_daily_pct = (tenant_daily_spent / tenant_daily_limit) if tenant_daily_limit else 0.0
        self.warning = (
            self.session_pct >= warning_threshold
            or self.daily_pct >= warning_threshold
            or self.tenant_daily_pct >= warning_threshold
        )

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "tenant_id": self.tenant_id,
            "date_utc": self.date_utc,
            "session": {
                "spent_usd": round(self.session_spent_usd, 6),
                "limit_usd": self.session_limit_usd,
                "pct": round(self.session_pct, 4),
            },
            "daily": {
                "spent_usd": round(self.daily_spent_usd, 6),
                "limit_usd": self.daily_limit_usd,
                "pct": round(self.daily_pct, 4),
            },
            "tenant_daily": {
                "spent_usd": round(self.tenant_daily_spent_usd, 6),
                "limit_usd": self.tenant_daily_limit_usd,
                "pct": round(self.tenant_daily_pct, 4),
            },
            "warning": self.warning,
        }


# ---------------------------------------------------------------------------
# BudgetEnforcer
# ---------------------------------------------------------------------------

class BudgetEnforcer:
    """Thread-safe (asyncio) budget tracker and enforcement engine.

    Parameters
    ----------
    budget_policy:
        :class:`BudgetPolicy` parsed from governance config.
    model_policy:
        :class:`ModelPolicy` used to resolve the fallback model when
        ``on_exceed`` is ``downgrade``.
    """

    def __init__(
        self,
        budget_policy: BudgetPolicy,
        model_policy: Optional[ModelPolicy] = None,
    ) -> None:
        self._policy = budget_policy
        self._model_policy = model_policy
        self._lock = asyncio.Lock()

        # session_id -> _Counter
        self._session: Dict[str, _Counter] = {}

        # date_str -> global daily counter
        self._daily: Dict[str, _Counter] = {}

        # tenant_id -> date_str -> _Counter
        self._tenant_daily: Dict[str, Dict[str, _Counter]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _today(self) -> str:
        return date.today().isoformat()

    def _session_counter(self, session_id: str) -> _Counter:
        if session_id not in self._session:
            self._session[session_id] = _Counter()
        return self._session[session_id]

    def _daily_counter(self, today: str) -> _Counter:
        if today not in self._daily:
            self._daily[today] = _Counter()
        return self._daily[today]

    def _tenant_daily_counter(self, tenant_id: str, today: str) -> _Counter:
        if tenant_id not in self._tenant_daily:
            self._tenant_daily[tenant_id] = {}
        if today not in self._tenant_daily[tenant_id]:
            self._tenant_daily[tenant_id][today] = _Counter()
        return self._tenant_daily[tenant_id][today]

    def _fallback_model(self) -> str:
        if self._model_policy:
            return self._model_policy.fallback_model
        return "llama2"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enforce_pre_call(
        self,
        session_id: str,
        tenant_id: str,
        requested_model: str,
        estimated_cost_usd: float,
    ) -> str:
        """Check budgets before an LLM call.

        Returns the model to use — either *requested_model* if budgets are
        fine, or the fallback model when budgets are tight and the policy is
        ``downgrade``.

        Raises
        ------
        BudgetExceededError
            When budget would be exceeded and the policy is ``deny``.
        """
        async with self._lock:
            today = self._today()
            sess = self._session_counter(session_id)
            daily = self._daily_counter(today)
            tenant = self._tenant_daily_counter(tenant_id, today)

            violations: List[tuple] = []

            if sess.total_usd + estimated_cost_usd > self._policy.session_budget_usd:
                violations.append(("session", self._policy.session_budget_usd, sess.total_usd))
            if daily.total_usd + estimated_cost_usd > self._policy.daily_budget_usd:
                violations.append(("daily", self._policy.daily_budget_usd, daily.total_usd))
            if tenant.total_usd + estimated_cost_usd > self._policy.tenant_daily_budget_usd:
                violations.append(("tenant_daily", self._policy.tenant_daily_budget_usd, tenant.total_usd))

            if violations:
                scope, limit, spent = violations[0]
                if self._policy.on_exceed == OnBudgetExceed.DENY:
                    raise BudgetExceededError(scope, limit, spent, estimated_cost_usd)
                else:
                    logger.warning(
                        "Budget overrun [%s] session=%s tenant=%s: "
                        "limit=%.4f spent=%.4f requested=%.4f — downgrading model",
                        scope, session_id, tenant_id, limit, spent, estimated_cost_usd,
                    )
                    return self._fallback_model()

            # Warn if approaching threshold
            p = self._policy
            threshold = p.warning_threshold
            for label, spent_val, limit_val in [
                ("session", sess.total_usd, p.session_budget_usd),
                ("daily", daily.total_usd, p.daily_budget_usd),
                ("tenant_daily", tenant.total_usd, p.tenant_daily_budget_usd),
            ]:
                if limit_val > 0 and (spent_val + estimated_cost_usd) / limit_val >= threshold:
                    logger.warning(
                        "Budget warning [%s] session=%s: %.0f%% of %.4f USD used",
                        label, session_id,
                        100 * (spent_val + estimated_cost_usd) / limit_val,
                        limit_val,
                    )

        return requested_model

    async def record_usage(
        self,
        session_id: str,
        tenant_id: str,
        model: str,
        tokens_used: int,
        cost_usd: float,
    ) -> None:
        """Record actual usage after an LLM call completes."""
        async with self._lock:
            today = self._today()
            self._session_counter(session_id).add(cost_usd, tokens_used)
            self._daily_counter(today).add(cost_usd, tokens_used)
            self._tenant_daily_counter(tenant_id, today).add(cost_usd, tokens_used)

        logger.debug(
            "Usage recorded: session=%s tenant=%s model=%s tokens=%d cost=%.6f USD",
            session_id, tenant_id, model, tokens_used, cost_usd,
        )

    async def get_status(self, session_id: str, tenant_id: str) -> BudgetStatus:
        """Return current budget utilisation snapshot."""
        async with self._lock:
            today = self._today()
            sess = self._session_counter(session_id)
            daily = self._daily_counter(today)
            tenant = self._tenant_daily_counter(tenant_id, today)

            return BudgetStatus(
                session_id=session_id,
                tenant_id=tenant_id,
                date_utc=today,
                session_spent=sess.total_usd,
                session_limit=self._policy.session_budget_usd,
                daily_spent=daily.total_usd,
                daily_limit=self._policy.daily_budget_usd,
                tenant_daily_spent=tenant.total_usd,
                tenant_daily_limit=self._policy.tenant_daily_budget_usd,
                warning_threshold=self._policy.warning_threshold,
            )

    def reset_session(self, session_id: str) -> None:
        """Reset a session's cost counter (call when session ends)."""
        self._session.pop(session_id, None)

    def all_session_ids(self) -> list[str]:
        """Return all tracked session IDs."""
        return list(self._session.keys())
