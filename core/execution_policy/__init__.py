#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy
======================

PR-11 (V4) — Execution Policy Schema

A focused, additive package that introduces a formal execution-policy schema
layer for the Galaxy runtime.

This package answers, given current system signals:
  - What class of execution is permitted? (``policy_band``)
  - What risk/action/fallback budget is available?
  - Which executor levels are permitted?
  - Whether cross-device expansion is allowed?
  - Whether confirmation is required before side-effectful steps?

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.continuum.types.TriStatePhase` — PR-3
* :class:`~core.continuum.types.RuntimeDomain` — PR-3
* :class:`~core.orchestration_authority.AuthorityRole` — PR-9
* :class:`~core.return_intelligence.ReturnSummary` — PR-10
* :class:`~core.execution_observability.executor_level.ExecutorLevel` — PR-7

Public API
----------
PolicyBand
    Enum of execution tiers: ``observe_only``, ``assistive``,
    ``bounded_execute``, ``full_execute``.

BAND_ORDER
    Ordered list of bands from least to most permissive.

band_allows_execution(band) → bool
    True if the band permits at least some direct execution.

band_allows_cross_device(band) → bool
    True if the band is eligible for cross-device expansion.

band_requires_confirmation(band) → bool
    True if the band level implies confirmation is advisable.

ExecutionPolicy
    Immutable, serialisable policy dataclass.  Fields:
    ``policy_band``, ``risk_budget``, ``action_budget``,
    ``fallback_budget``, ``allowed_executor_levels``,
    ``cross_device_allowed``, ``requires_confirmation``, ``reason``,
    and source-signal traceability fields.

DEFAULT_CONSERVATIVE_POLICY
    Pre-built ``ExecutionPolicy`` for safe-fallback use.

resolve_policy(phase, domain, authority_role, return_summary, …) → ExecutionPolicy
    Derive a policy from runtime signals.  All inputs optional.  Degrades
    gracefully when signals are absent.

summarise_policy(policy) → dict
    Serialise a policy into a compact, JSON-safe dict.

get_policy_hints(policy) → dict
    Minimal boolean/scalar hints for downstream consumers.

attach_policy_to_projection(projection_dict, policy) → dict
    Attach a policy summary to a RuntimeProjection dict additively.

build_policy_for_projection(projection_dict) → dict
    Resolve and attach policy from a projection dict in one call.

RETURN_PRESSURE_FORCE_OBSERVE
    Return-pressure threshold that overrides the band to ``observe_only``.

RETURN_PRESSURE_RESTRICT
    Return-pressure threshold that restricts budgets and forces confirmation.

What this package does NOT do
------------------------------
- It does **not** replace or modify the runtime/orchestrator logic in
  ``WindowsExecutionArbiter``, ``TaskGraph``, ``ConstellationRuntime``, etc.
- Enforcement is additive: existing paths call the helpers optionally and
  fall back to their own behaviour when no policy is supplied.

Enforcement (PR-12)
-------------------
PolicyOutcome
    Enum of stable outcome codes: ``allowed``, ``blocked_by_policy``,
    ``confirmation_required``, ``cross_device_not_allowed``,
    ``executor_level_capped``, ``downgraded``.

PolicyDecision
    Immutable result of a policy check.  Fields: ``outcome``, ``policy``,
    ``reason``, ``hint``, ``blocked_levels``, ``downgraded_to``.
    Properties: ``is_allowed``, ``is_blocked``, ``needs_confirmation``.
    Method: ``to_dict()``.

enforce_execution_intent(policy, *, is_side_effectful, requires_cross_device, …)
    Composite enforcement check — applies all relevant guardrails in order.

enforce_cross_device(policy) → PolicyDecision
    Cross-device-only check.

enforce_executor_levels(policy, candidate_levels) → dict
    Filter candidate levels and emit an observability entry.

emit_policy_decision(decision) → None
    Emit a structured observability log for a decision.

check_side_effectful_execution(policy, *, is_side_effectful) → PolicyDecision
    Block when band is observe_only/assistive.

check_confirmation_required(policy) → PolicyDecision
    Surface requires_confirmation as a structured result.

check_cross_device_expansion(policy) → PolicyDecision
    Deny when cross_device_allowed is False.

check_executor_level(policy, requested_level) → PolicyDecision
    Cap executor level to policy's allowed list.

filter_executor_levels(policy, candidate_levels) → (permitted, blocked)
    Partition a level list into permitted / blocked subsets.

See Also
--------
docs/EXECUTION_POLICY_SCHEMA.md — policy schema design document.
docs/EXECUTION_POLICY_ENFORCEMENT.md — enforcement design document (PR-12).
"""

from __future__ import annotations

from .policy_band import (
    PolicyBand,
    BAND_ORDER,
    band_allows_execution,
    band_allows_cross_device,
    band_requires_confirmation,
)
from .execution_policy import ExecutionPolicy, DEFAULT_CONSERVATIVE_POLICY
from .policy_resolver import (
    resolve_policy,
    RETURN_PRESSURE_FORCE_OBSERVE,
    RETURN_PRESSURE_RESTRICT,
)
from .policy_summary import (
    summarise_policy,
    get_policy_hints,
    attach_policy_to_projection,
    build_policy_for_projection,
)
from .policy_decision import PolicyOutcome, PolicyDecision
from .policy_guardrails import (
    check_side_effectful_execution,
    check_confirmation_required,
    check_cross_device_expansion,
    check_executor_level,
    filter_executor_levels,
)
from .policy_enforcement import (
    enforce_execution_intent,
    enforce_cross_device,
    enforce_executor_levels,
    emit_policy_decision,
)

__all__ = [
    # Band enum and helpers
    "PolicyBand",
    "BAND_ORDER",
    "band_allows_execution",
    "band_allows_cross_device",
    "band_requires_confirmation",
    # Policy dataclass
    "ExecutionPolicy",
    "DEFAULT_CONSERVATIVE_POLICY",
    # Resolver
    "resolve_policy",
    "RETURN_PRESSURE_FORCE_OBSERVE",
    "RETURN_PRESSURE_RESTRICT",
    # Summary helpers
    "summarise_policy",
    "get_policy_hints",
    "attach_policy_to_projection",
    "build_policy_for_projection",
    # PR-12 Enforcement — decision types
    "PolicyOutcome",
    "PolicyDecision",
    # PR-12 Enforcement — guardrail helpers
    "check_side_effectful_execution",
    "check_confirmation_required",
    "check_cross_device_expansion",
    "check_executor_level",
    "filter_executor_levels",
    # PR-12 Enforcement — orchestration helpers
    "enforce_execution_intent",
    "enforce_cross_device",
    "enforce_executor_levels",
    "emit_policy_decision",
]
