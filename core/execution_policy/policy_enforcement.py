#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_enforcement
==========================================

PR-12 (V4) — Execution Policy Enforcement

Thin enforcement orchestrator that ties together the guardrail helpers and
observability logging.  This is the primary entry-point for execution paths
that want to honour the execution policy.

Responsibilities
----------------
- Accept an :class:`~.execution_policy.ExecutionPolicy` and a description of
  execution intent.
- Apply the relevant :mod:`~.policy_guardrails` checks in priority order.
- Emit a structured log entry for every meaningful policy outcome.
- Return a stable :class:`~.policy_decision.PolicyDecision` without raising.

Design rules
------------
- Enforcement is **additive**: existing execution paths call this module
  optionally; they never crash if the policy is ``None``.
- Enforcement is **safe-by-default**: when no policy is supplied the
  :data:`~.execution_policy.DEFAULT_CONSERVATIVE_POLICY` is used.
- Every decision is logged at ``DEBUG`` level (``INFO`` for blocks) so that
  policy decisions are observable without flooding production logs.
- The module never imports optional/platform-specific packages at module
  level to keep startup cost zero.

Usage::

    from core.execution_policy.policy_enforcement import enforce_execution_intent
    from core.execution_policy import resolve_policy

    policy = resolve_policy(phase="manifest", domain="cross_device")

    decision = enforce_execution_intent(
        policy,
        is_side_effectful=True,
        requires_cross_device=True,
        requested_executor_levels=["gui", "vlm"],
    )
    if not decision.is_allowed:
        return decision.to_dict()   # structured public-safe result
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .execution_policy import ExecutionPolicy, DEFAULT_CONSERVATIVE_POLICY
from .policy_decision import PolicyDecision, PolicyOutcome, _make_allowed
from .policy_guardrails import (
    check_side_effectful_execution,
    check_cross_device_expansion,
    check_executor_level,
    filter_executor_levels,
)

logger = logging.getLogger("Galaxy.ExecutionPolicy.Enforcement")

__all__ = [
    "enforce_execution_intent",
    "emit_policy_decision",
    "enforce_cross_device",
    "enforce_executor_levels",
]


# ---------------------------------------------------------------------------
# Main enforcement entry point
# ---------------------------------------------------------------------------


def enforce_execution_intent(
    policy: Optional[ExecutionPolicy],
    *,
    is_side_effectful: bool = True,
    requires_cross_device: bool = False,
    requested_executor_levels: Optional[List[str]] = None,
    context: Optional[Dict[str, Any]] = None,
) -> PolicyDecision:
    """Enforce policy against a composite execution intent.

    Applies guardrail checks in the following priority order:

    1. Side-effectful execution gate (``observe_only`` / ``assistive`` blocks).
    2. Cross-device expansion gate (when *requires_cross_device* is ``True``).
    3. Executor level cap (first disallowed level in *requested_executor_levels*).

    The first failing check short-circuits the remaining checks and its
    decision is returned immediately.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.  When
        ``None``, :data:`~.execution_policy.DEFAULT_CONSERVATIVE_POLICY` is
        used.
    is_side_effectful:
        ``True`` (default) when the intent involves actions with real side
        effects.  ``False`` for read-only / sensing operations.
    requires_cross_device:
        ``True`` when the intent requires executing on a remote device.
    requested_executor_levels:
        Ordered list of executor levels the caller wants to use.  The first
        disallowed level in this list will trigger an
        :attr:`~.policy_decision.PolicyOutcome.EXECUTOR_LEVEL_CAPPED` result.
    context:
        Optional dict attached to the log entry for correlation (e.g.
        ``trace_id``, ``device_id``).

    Returns
    -------
    PolicyDecision
        A stable, structured decision.  Never raises.

    Example
    -------
    ::

        decision = enforce_execution_intent(
            policy,
            is_side_effectful=True,
            requires_cross_device=True,
        )
        if decision.is_blocked:
            return {"error": decision.hint, "detail": decision.reason}
        if decision.needs_confirmation:
            return {"status": "pending_confirmation", "reason": decision.reason}
    """
    effective_policy = policy if policy is not None else DEFAULT_CONSERVATIVE_POLICY
    ctx = context or {}

    try:
        # ── 1. Side-effectful execution gate ──────────────────────────────
        side_effect_decision = check_side_effectful_execution(
            effective_policy, is_side_effectful=is_side_effectful
        )
        if not side_effect_decision.is_allowed:
            emit_policy_decision(side_effect_decision, context=ctx)
            return side_effect_decision

        # ── 2. Cross-device expansion gate ────────────────────────────────
        if requires_cross_device:
            cross_device_decision = check_cross_device_expansion(effective_policy)
            if not cross_device_decision.is_allowed:
                emit_policy_decision(cross_device_decision, context=ctx)
                return cross_device_decision

        # ── 3. Executor level cap ─────────────────────────────────────────
        if requested_executor_levels:
            for level in requested_executor_levels:
                level_decision = check_executor_level(effective_policy, level)
                if not level_decision.is_allowed:
                    emit_policy_decision(level_decision, context=ctx)
                    return level_decision

        # All checks passed
        allowed_decision = _make_allowed(
            effective_policy,
            reason=(
                f"execution intent cleared all policy checks "
                f"(band={effective_policy.policy_band.value})"
            ),
        )
        emit_policy_decision(allowed_decision, context=ctx)
        return allowed_decision

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "enforce_execution_intent: unexpected error, returning conservative block: %s", exc
        )
        return PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=effective_policy,
            reason=f"enforcement error (safe default): {exc}",
            hint="blocked_by_policy",
        )


# ---------------------------------------------------------------------------
# Cross-device enforcement helper
# ---------------------------------------------------------------------------


def enforce_cross_device(
    policy: Optional[ExecutionPolicy],
    *,
    context: Optional[Dict[str, Any]] = None,
) -> PolicyDecision:
    """Enforce cross-device expansion policy in a single call.

    Convenience wrapper for callers that only need the cross-device check
    (e.g. :func:`~core.e2e_orchestrator.run_multi_device_via_task_graph`).

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.
        Defaults to the conservative policy when ``None``.
    context:
        Optional correlation context for logging.

    Returns
    -------
    PolicyDecision
    """
    effective_policy = policy if policy is not None else DEFAULT_CONSERVATIVE_POLICY
    decision = check_cross_device_expansion(effective_policy)
    emit_policy_decision(decision, context=context or {})
    return decision


# ---------------------------------------------------------------------------
# Executor-level filter enforcement helper
# ---------------------------------------------------------------------------


def enforce_executor_levels(
    policy: Optional[ExecutionPolicy],
    candidate_levels: List[str],
    *,
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Filter *candidate_levels* by policy and emit an observability entry.

    Parameters
    ----------
    policy:
        The policy to enforce.  Defaults to conservative when ``None``.
    candidate_levels:
        The executor levels the caller wants to attempt, in preference order.
    context:
        Optional correlation context for logging.

    Returns
    -------
    dict with keys:
        - ``permitted_levels`` (list[str])
        - ``blocked_levels`` (list[str])
        - ``outcome`` (str) — ``"allowed"`` or ``"executor_level_capped"``
        - ``policy_band`` (str)
        - ``reason`` (str)
    """
    effective_policy = policy if policy is not None else DEFAULT_CONSERVATIVE_POLICY
    permitted, blocked = filter_executor_levels(effective_policy, candidate_levels)
    ctx = context or {}

    if blocked:
        outcome_str = PolicyOutcome.EXECUTOR_LEVEL_CAPPED.value
        reason = (
            f"executor levels {blocked} removed by policy "
            f"(band={effective_policy.policy_band.value}); "
            f"permitted: {permitted}"
        )
        _log_decision(
            outcome=outcome_str,
            policy=effective_policy,
            reason=reason,
            context=ctx,
            level="info",
        )
    else:
        outcome_str = PolicyOutcome.ALLOWED.value
        reason = (
            f"all executor levels permitted "
            f"(band={effective_policy.policy_band.value})"
        )
        _log_decision(
            outcome=outcome_str,
            policy=effective_policy,
            reason=reason,
            context=ctx,
            level="debug",
        )

    return {
        "permitted_levels": permitted,
        "blocked_levels": blocked,
        "outcome": outcome_str,
        "policy_band": effective_policy.policy_band.value,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Observability emission
# ---------------------------------------------------------------------------


def emit_policy_decision(
    decision: PolicyDecision,
    *,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit a structured log entry for *decision*.

    Blocks and cross-device denials are logged at ``INFO`` level.
    Allowed and confirmation-required decisions are logged at ``DEBUG``.

    The log entry always includes:
    - ``policy_decision`` — the outcome string
    - ``policy_band`` — the active policy band
    - ``reason`` — human-readable explanation
    - ``hint`` — short stable outcome code
    - Any extra fields from *context* (e.g. ``trace_id``, ``device_id``)

    Parameters
    ----------
    decision:
        The :class:`~.policy_decision.PolicyDecision` to emit.
    context:
        Optional dict of additional log fields.
    """
    outcome = decision.outcome.value
    is_significant = decision.outcome in (
        PolicyOutcome.BLOCKED_BY_POLICY,
        PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED,
        PolicyOutcome.EXECUTOR_LEVEL_CAPPED,
        PolicyOutcome.CONFIRMATION_REQUIRED,
    )
    log_level = "info" if is_significant else "debug"
    _log_decision(
        outcome=outcome,
        policy=decision.policy,
        reason=decision.reason,
        context=context or {},
        level=log_level,
        blocked_levels=decision.blocked_levels,
        downgraded_to=decision.downgraded_to,
    )


# ---------------------------------------------------------------------------
# Internal structured log helper
# ---------------------------------------------------------------------------


def _log_decision(
    *,
    outcome: str,
    policy: ExecutionPolicy,
    reason: str,
    context: Dict[str, Any],
    level: str = "debug",
    blocked_levels: Optional[List[str]] = None,
    downgraded_to: Optional[str] = None,
) -> None:
    """Emit a single structured log line."""
    extra: Dict[str, Any] = {
        "policy_decision": outcome,
        "policy_band": policy.policy_band.value,
        "reason": reason,
        "cross_device_allowed": policy.cross_device_allowed,
        "requires_confirmation": policy.requires_confirmation,
    }
    if blocked_levels:
        extra["blocked_levels"] = blocked_levels
    if downgraded_to is not None:
        extra["downgraded_to"] = downgraded_to
    extra.update(context)

    msg = (
        "policy_enforcement | %s | band=%s | %s"
    )
    args = (outcome, policy.policy_band.value, reason)

    if level == "info":
        logger.info(msg, *args, extra=extra)
    else:
        logger.debug(msg, *args, extra=extra)
