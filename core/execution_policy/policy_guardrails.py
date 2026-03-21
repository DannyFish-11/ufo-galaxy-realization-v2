#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_guardrails
==========================================

PR-12 (V4) — Execution Policy Enforcement

Stateless guardrail helpers that check an :class:`~.execution_policy.ExecutionPolicy`
against a specific execution intent and return a structured
:class:`~.policy_decision.PolicyDecision`.

Each helper is a pure function: it reads the policy, applies one enforcement
rule, and returns a decision.  It never mutates state or raises exceptions.

Enforcement rules
-----------------
1. :func:`check_side_effectful_execution` — block when ``policy_band`` is
   ``observe_only`` or ``assistive`` and the action would produce side effects.

2. :func:`check_confirmation_required` — surface ``requires_confirmation``
   as a structured ``confirmation_required`` result rather than silently
   ignoring it.

3. :func:`check_cross_device_expansion` — deny cross-device expansion when
   ``cross_device_allowed`` is ``False``.

4. :func:`check_executor_level` — verify that a requested executor level is
   in the policy's ``allowed_executor_levels`` list.

5. :func:`filter_executor_levels` — filter a candidate list of executor levels
   down to those permitted by the policy, returning both the allowed subset
   and the blocked subset.

Usage::

    from core.execution_policy.policy_guardrails import (
        check_side_effectful_execution,
        check_cross_device_expansion,
        check_confirmation_required,
        check_executor_level,
        filter_executor_levels,
    )
    from core.execution_policy import resolve_policy

    policy = resolve_policy(phase="liminal")
    decision = check_side_effectful_execution(policy, is_side_effectful=True)
    if decision.is_blocked:
        return decision.to_dict()
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .execution_policy import ExecutionPolicy
from .policy_band import PolicyBand, band_allows_execution
from .policy_decision import PolicyDecision, PolicyOutcome, _make_allowed


__all__ = [
    "check_side_effectful_execution",
    "check_confirmation_required",
    "check_cross_device_expansion",
    "check_executor_level",
    "filter_executor_levels",
]


# ---------------------------------------------------------------------------
# Rule 1: Side-effectful execution gate
# ---------------------------------------------------------------------------


def check_side_effectful_execution(
    policy: ExecutionPolicy,
    *,
    is_side_effectful: bool = True,
) -> PolicyDecision:
    """Check whether the policy permits a potentially side-effectful action.

    When *is_side_effectful* is ``True`` (the default), execution is blocked
    if the policy band is ``observe_only`` or ``assistive``.

    When the band permits execution but ``requires_confirmation`` is set, a
    ``confirmation_required`` decision is returned instead of ``allowed``.
    Callers should surface the confirmation requirement before proceeding.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.
    is_side_effectful:
        ``True`` when the action would produce real side effects (default).
        ``False`` for read-only / sensing operations that are always allowed.

    Returns
    -------
    PolicyDecision
        - ``ALLOWED`` if the policy permits the action.
        - ``BLOCKED_BY_POLICY`` if the band does not allow side effects.
        - ``CONFIRMATION_REQUIRED`` if confirmation is needed before proceeding.
    """
    # Read-only operations are always allowed regardless of policy band.
    if not is_side_effectful:
        return _make_allowed(policy, reason="read-only operation — policy band not restricting")

    # Check whether the band allows any execution at all.
    if not band_allows_execution(policy.policy_band):
        return PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=policy,
            reason=(
                f"policy_band={policy.policy_band.value!r} does not permit "
                "side-effectful execution"
            ),
            hint="blocked_by_policy",
        )

    # Band allows execution; check confirmation requirement.
    if policy.should_require_confirmation:
        return PolicyDecision(
            outcome=PolicyOutcome.CONFIRMATION_REQUIRED,
            policy=policy,
            reason=(
                "confirmation required before side-effectful execution "
                f"(policy_band={policy.policy_band.value!r})"
            ),
            hint="confirmation_required",
        )

    return _make_allowed(
        policy,
        reason=f"side-effectful execution permitted (policy_band={policy.policy_band.value!r})",
    )


# ---------------------------------------------------------------------------
# Rule 2: Confirmation gate (standalone check)
# ---------------------------------------------------------------------------


def check_confirmation_required(policy: ExecutionPolicy) -> PolicyDecision:
    """Surface the ``requires_confirmation`` flag as a structured decision.

    Unlike :func:`check_side_effectful_execution` this helper is only
    concerned with whether confirmation is required, not with the band.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to inspect.

    Returns
    -------
    PolicyDecision
        - ``CONFIRMATION_REQUIRED`` when ``policy.requires_confirmation`` is
          ``True``.
        - ``ALLOWED`` otherwise.
    """
    if policy.should_require_confirmation:
        return PolicyDecision(
            outcome=PolicyOutcome.CONFIRMATION_REQUIRED,
            policy=policy,
            reason=(
                f"requires_confirmation=True in current policy "
                f"(policy_band={policy.policy_band.value!r})"
            ),
            hint="confirmation_required",
        )
    return _make_allowed(policy, reason="confirmation not required by policy")


# ---------------------------------------------------------------------------
# Rule 3: Cross-device expansion gate
# ---------------------------------------------------------------------------


def check_cross_device_expansion(policy: ExecutionPolicy) -> PolicyDecision:
    """Check whether cross-device expansion is permitted.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.

    Returns
    -------
    PolicyDecision
        - ``CROSS_DEVICE_NOT_ALLOWED`` when ``policy.cross_device_allowed``
          is ``False``.
        - ``ALLOWED`` otherwise.
    """
    if not policy.can_expand_cross_device:
        return PolicyDecision(
            outcome=PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED,
            policy=policy,
            reason=(
                f"cross_device_allowed=False in current policy "
                f"(policy_band={policy.policy_band.value!r})"
            ),
            hint="cross_device_not_allowed",
        )
    return _make_allowed(policy, reason="cross-device expansion permitted by policy")


# ---------------------------------------------------------------------------
# Rule 4: Executor level gate
# ---------------------------------------------------------------------------


def check_executor_level(
    policy: ExecutionPolicy,
    requested_level: str,
) -> PolicyDecision:
    """Check whether *requested_level* is permitted by the policy.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.
    requested_level:
        The executor level string to validate (e.g. ``"gui"``, ``"vlm"``).
        Should match a value from
        :class:`~core.execution_observability.executor_level.ExecutorLevel`.

    Returns
    -------
    PolicyDecision
        - ``BLOCKED_BY_POLICY`` when no executor levels are permitted.
        - ``EXECUTOR_LEVEL_CAPPED`` when *requested_level* is not in the
          policy's allowed list.  ``downgraded_to`` is set to the highest
          permitted level.
        - ``ALLOWED`` when *requested_level* is in the allowed list.
    """
    allowed = policy.allowed_executor_levels
    if not allowed:
        return PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=policy,
            reason=(
                f"no executor levels permitted by policy "
                f"(policy_band={policy.policy_band.value!r})"
            ),
            hint="blocked_by_policy",
            blocked_levels=[requested_level],
        )

    if requested_level not in allowed:
        # Suggest the highest-ranked permitted level as an alternative.
        suggested = allowed[-1] if allowed else None
        return PolicyDecision(
            outcome=PolicyOutcome.EXECUTOR_LEVEL_CAPPED,
            policy=policy,
            reason=(
                f"executor_level={requested_level!r} is not in policy's "
                f"allowed_executor_levels={allowed}"
            ),
            hint="executor_level_capped",
            blocked_levels=[requested_level],
            downgraded_to=suggested,
        )

    return _make_allowed(
        policy,
        reason=f"executor_level={requested_level!r} is permitted by policy",
    )


# ---------------------------------------------------------------------------
# Rule 5: Bulk executor level filter
# ---------------------------------------------------------------------------


def filter_executor_levels(
    policy: ExecutionPolicy,
    candidate_levels: List[str],
) -> Tuple[List[str], List[str]]:
    """Filter *candidate_levels* by the policy's allowed executor levels.

    Returns a tuple of ``(permitted_levels, blocked_levels)``.  The order
    of *candidate_levels* is preserved in both output lists.

    Parameters
    ----------
    policy:
        The :class:`~.execution_policy.ExecutionPolicy` to enforce.
    candidate_levels:
        The executor levels the caller wants to attempt (in preference order).

    Returns
    -------
    tuple[list[str], list[str]]
        ``(permitted_levels, blocked_levels)``.  Both lists are subsets of
        *candidate_levels*.  ``permitted_levels`` may be empty if none are
        allowed.

    Example
    -------
    ::

        permitted, blocked = filter_executor_levels(policy, ["system_api", "uia", "gui", "vlm"])
        # If policy is bounded_execute: permitted=["system_api", "uia"], blocked=["gui", "vlm"]
    """
    allowed_set = set(policy.allowed_executor_levels)
    permitted: List[str] = []
    blocked: List[str] = []
    for level in candidate_levels:
        if level in allowed_set:
            permitted.append(level)
        else:
            blocked.append(level)
    return permitted, blocked
