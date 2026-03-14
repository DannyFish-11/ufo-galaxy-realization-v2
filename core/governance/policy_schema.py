#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Governance Policy Schema (Phase 5.2)
==============================================

Pydantic v2 models for validating ``config/governance_policy.json``.

Usage
-----
    from core.governance.policy_schema import load_governance_policy

    policy = load_governance_policy()          # loads default config file
    policy = load_governance_policy(path)      # loads custom path

The schema validates all three sub-policies:

* **ModelPolicy**   – safety tiers, allowed models, fallback model
* **BudgetPolicy**  – per-session / per-day / per-tenant USD budgets
* **ToolPolicy**    – allow/deny lists, per-risk-tier rate limits
* **QueuePolicy**   – queue sizing, concurrency, backpressure settings
"""

from __future__ import annotations

import json
import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SafetyTierName(str, Enum):
    RESTRICTED = "restricted"
    STANDARD = "standard"
    ELEVATED = "elevated"


class OnBudgetExceed(str, Enum):
    DOWNGRADE = "downgrade"
    DENY = "deny"


class DefaultToolAction(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


class ShedStrategy(str, Enum):
    REJECT_NEW = "reject_new"
    DROP_OLDEST = "drop_oldest"


# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

class SafetyTierConfig(BaseModel):
    """Configuration for a single safety tier (allowed models, limits)."""

    allowed_models: List[str] = Field(default_factory=list)
    max_tokens_per_request: int = Field(default=8192, ge=1)


class ModelPolicy(BaseModel):
    """Policy governing model selection and safety tiers."""

    default_safety_tier: SafetyTierName = SafetyTierName.STANDARD
    safety_tiers: Dict[str, SafetyTierConfig] = Field(default_factory=dict)
    fallback_model: str = Field(default="llama2")
    on_budget_exceed: OnBudgetExceed = OnBudgetExceed.DOWNGRADE


class BudgetPolicy(BaseModel):
    """Per-session and per-day token/cost budgets."""

    session_budget_usd: float = Field(default=1.0, ge=0)
    daily_budget_usd: float = Field(default=20.0, ge=0)
    tenant_daily_budget_usd: float = Field(default=100.0, ge=0)
    warning_threshold: float = Field(default=0.8, ge=0, le=1)
    on_exceed: OnBudgetExceed = OnBudgetExceed.DOWNGRADE

    @field_validator("warning_threshold")
    @classmethod
    def _threshold_range(cls, v: float) -> float:
        if not (0 <= v <= 1):
            raise ValueError("warning_threshold must be in [0, 1]")
        return v


class RiskTierConfig(BaseModel):
    """Per-risk-tier tool action and rate-limit settings."""

    action: Literal["allow", "deny"] = "allow"
    rate_limit_per_minute: int = Field(default=60, ge=0)
    require_audit: bool = False


class ToolPolicy(BaseModel):
    """Tool governance: allow/deny lists and per-tier rate limits."""

    default_action: DefaultToolAction = DefaultToolAction.ALLOW
    allow_list: List[str] = Field(default_factory=list)
    deny_list: List[str] = Field(default_factory=list)
    risk_tiers: Dict[str, RiskTierConfig] = Field(default_factory=dict)
    per_tool_overrides: Dict[str, RiskTierConfig] = Field(default_factory=dict)


class QueuePolicy(BaseModel):
    """Async task queue sizing and backpressure settings."""

    max_queue_size: int = Field(default=500, ge=1)
    max_concurrent_tasks: int = Field(default=20, ge=1)
    task_timeout_seconds: float = Field(default=60.0, ge=1)
    backpressure_threshold: float = Field(default=0.8, ge=0, le=1)
    shed_strategy: ShedStrategy = ShedStrategy.REJECT_NEW

    @field_validator("backpressure_threshold")
    @classmethod
    def _bp_range(cls, v: float) -> float:
        if not (0 <= v <= 1):
            raise ValueError("backpressure_threshold must be in [0, 1]")
        return v


# ---------------------------------------------------------------------------
# Root schema
# ---------------------------------------------------------------------------

class GovernancePolicy(BaseModel):
    """Root governance policy document."""

    version: str = Field(default="1.0.0")
    model_policy: ModelPolicy = Field(default_factory=ModelPolicy)
    budget_policy: BudgetPolicy = Field(default_factory=BudgetPolicy)
    tool_policy: ToolPolicy = Field(default_factory=ToolPolicy)
    queue_policy: QueuePolicy = Field(default_factory=QueuePolicy)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "governance_policy.json"


def load_governance_policy(path: Optional[str | Path] = None) -> GovernancePolicy:
    """Load and validate a governance policy from *path*.

    If *path* is ``None`` the built-in default file is used.  If the file
    cannot be read, a default :class:`GovernancePolicy` is returned so the
    system degrades gracefully.
    """
    resolved = Path(path) if path is not None else _DEFAULT_POLICY_PATH
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
        # Strip meta-keys starting with "_" (e.g. "_comment")
        raw = {k: v for k, v in raw.items() if not k.startswith("_")}
        return GovernancePolicy.model_validate(raw)
    except FileNotFoundError:
        return GovernancePolicy()
    except Exception:  # malformed JSON / validation error — fail safe
        return GovernancePolicy()
