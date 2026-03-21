#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_decision
=======================================

PR-12 (V4) — Execution Policy Enforcement

Defines structured decision types returned by the policy guardrails and
enforcement layer.  Every enforcement check returns a :class:`PolicyDecision`
that callers can inspect before proceeding with execution.

Design rules
------------
- All outcomes are stable string values safe for logs, APIs, and tests.
- :class:`PolicyDecision` is immutable (frozen dataclass).
- Callers should never catch ``PolicyDecision`` as an exception; it is a
  return value, not an error.
- To convert a ``blocked_by_policy`` decision into a structured API response,
  use :meth:`PolicyDecision.to_dict`.

Usage::

    from core.execution_policy.policy_decision import PolicyOutcome, PolicyDecision
    from core.execution_policy import DEFAULT_CONSERVATIVE_POLICY

    decision = PolicyDecision(
        outcome=PolicyOutcome.BLOCKED_BY_POLICY,
        policy=DEFAULT_CONSERVATIVE_POLICY,
        reason="observe_only band does not permit side-effectful execution",
        hint="blocked_by_policy",
    )
    if not decision.is_allowed:
        return decision.to_dict()
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, List, Optional

from .execution_policy import ExecutionPolicy, DEFAULT_CONSERVATIVE_POLICY


__all__ = ["PolicyOutcome", "PolicyDecision"]


class PolicyOutcome(str, Enum):
    """Stable outcome codes returned by the enforcement layer.

    The string values are JSON-serialisable and suitable for use in API
    responses, structured logs, and test assertions.
    """

    ALLOWED = "allowed"
    """Execution is permitted under the current policy."""

    BLOCKED_BY_POLICY = "blocked_by_policy"
    """Execution is blocked because the policy band does not permit it.

    Typical causes:
    - ``policy_band = observe_only`` with a side-effectful action.
    - ``policy_band = assistive`` with a direct execution request.
    """

    CONFIRMATION_REQUIRED = "confirmation_required"
    """Execution requires a human-in-the-loop confirmation step.

    The action is *not* blocked outright; it should be held until the
    caller surfaces the confirmation and receives approval.
    """

    CROSS_DEVICE_NOT_ALLOWED = "cross_device_not_allowed"
    """Cross-device expansion was requested but the policy disallows it.

    The action should be constrained to the local device or held until
    policy changes.
    """

    EXECUTOR_LEVEL_CAPPED = "executor_level_capped"
    """The requested executor level is not in the policy's allowed list.

    The enforcement layer may suggest a lower permitted level via
    :attr:`PolicyDecision.downgraded_to`.
    """

    DOWNGRADED = "downgraded"
    """Execution intent was downgraded to a lower band or executor level.

    The action may proceed but at reduced capability.  The downgraded
    level is indicated by :attr:`PolicyDecision.downgraded_to`.
    """


@dataclasses.dataclass(frozen=True)
class PolicyDecision:
    """Immutable result of a policy enforcement check.

    Attributes
    ----------
    outcome
        The :class:`PolicyOutcome` of the check.
    policy
        The :class:`~core.execution_policy.ExecutionPolicy` that was applied.
    reason
        Human-readable explanation of the decision.  Always non-empty.
    hint
        Short stable string hint for API consumers (mirrors ``outcome.value``
        by default but can carry additional context such as a suggested
        alternative).
    blocked_levels
        Executor levels that were filtered out by policy (present when
        ``outcome == EXECUTOR_LEVEL_CAPPED``).
    downgraded_to
        The level or band the system was downgraded to (present when
        ``outcome == EXECUTOR_LEVEL_CAPPED`` or ``DOWNGRADED``).
    """

    outcome: PolicyOutcome
    policy: ExecutionPolicy
    reason: str
    hint: str = ""
    blocked_levels: List[str] = dataclasses.field(default_factory=list)
    downgraded_to: Optional[str] = None

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def is_allowed(self) -> bool:
        """True if the execution intent is permitted to proceed."""
        return self.outcome is PolicyOutcome.ALLOWED

    @property
    def is_blocked(self) -> bool:
        """True if execution must be halted by policy."""
        return self.outcome is PolicyOutcome.BLOCKED_BY_POLICY

    @property
    def needs_confirmation(self) -> bool:
        """True if a confirmation step is required before proceeding."""
        return self.outcome is PolicyOutcome.CONFIRMATION_REQUIRED

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        Safe to return directly as an API response body or to include in
        a structured result envelope.
        """
        return {
            "outcome": self.outcome.value,
            "policy_band": self.policy.policy_band.value,
            "reason": self.reason,
            "hint": self.hint or self.outcome.value,
            "blocked_levels": list(self.blocked_levels),
            "downgraded_to": self.downgraded_to,
            "requires_confirmation": self.policy.requires_confirmation,
            "cross_device_allowed": self.policy.cross_device_allowed,
        }

    def __repr__(self) -> str:
        return (
            f"<PolicyDecision outcome={self.outcome.value} "
            f"band={self.policy.policy_band.value} "
            f"reason={self.reason!r}>"
        )


# ---------------------------------------------------------------------------
# Pre-built allowed decision (fast path)
# ---------------------------------------------------------------------------

def _make_allowed(policy: ExecutionPolicy, reason: str = "execution permitted by policy") -> PolicyDecision:
    """Return an ALLOWED :class:`PolicyDecision` for *policy*."""
    return PolicyDecision(
        outcome=PolicyOutcome.ALLOWED,
        policy=policy,
        reason=reason,
        hint="allowed",
    )
