#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.execution_policy
========================================

PR-11 (V4) — Execution Policy Schema

Defines :class:`ExecutionPolicy` — the canonical, serialisable policy object
that captures the full set of execution constraints and budgets for a given
runtime context.

An :class:`ExecutionPolicy` is produced by
:func:`~core.execution_policy.policy_resolver.resolve_policy` from a
combination of existing system signals:

  * :class:`~core.continuum.types.TriStatePhase`
  * :class:`~core.continuum.types.RuntimeDomain`
  * :class:`~core.orchestration_authority.AuthorityRole`
  * :class:`~core.return_intelligence.ReturnSummary` / return pressure
  * optional :class:`~core.execution_observability.ExecutorLevel` context

Design rules
------------
- All fields have safe defaults so that ``ExecutionPolicy()`` with no
  arguments produces a conservative, valid policy.
- ``to_dict()`` is fully JSON-serialisable (no enum objects in output).
- The object is frozen/immutable once created.
- This schema is **read-only by consumers** — enforcement belongs in a
  future PR.

Usage::

    from core.execution_policy import ExecutionPolicy, PolicyBand

    policy = ExecutionPolicy(
        policy_band=PolicyBand.BOUNDED_EXECUTE,
        risk_budget=0.4,
        action_budget=3,
        fallback_budget=2,
        allowed_executor_levels=["system_api", "uia"],
        cross_device_allowed=False,
        requires_confirmation=True,
        reason="liminal phase with moderate return pressure",
    )
    print(policy.to_dict())
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from .policy_band import PolicyBand, band_allows_execution, band_allows_cross_device


__all__ = ["ExecutionPolicy", "DEFAULT_CONSERVATIVE_POLICY"]


@dataclasses.dataclass(frozen=True)
class ExecutionPolicy:
    """Canonical, immutable execution-policy object.

    Attributes
    ----------
    policy_band
        The top-level execution tier that classifies what class of execution
        is currently permitted.  See :class:`~.policy_band.PolicyBand`.
    risk_budget
        Normalised risk allowance [0.0, 1.0].  ``0.0`` = no risk accepted
        (observe-only); ``1.0`` = full risk envelope available.
        Consumers should not exceed this budget when choosing action plans.
    action_budget
        Maximum number of distinct side-effectful steps permitted in a single
        task execution.  ``0`` means no side-effects are allowed.  ``-1`` is
        unbounded (``full_execute`` band only).
    fallback_budget
        Maximum number of fallback / retry attempts permitted across all
        executor levels in a single task.
    allowed_executor_levels
        Ordered list of executor-level strings that are currently permitted.
        Sourced from :class:`~core.execution_observability.executor_level.ExecutorLevel`
        values.  An empty list means no executor is currently permitted
        (observe-only or error state).
    cross_device_allowed
        Whether cross-device expansion is permitted.  When ``False`` the
        system must constrain execution to the local device.
    requires_confirmation
        Whether a human-in-the-loop confirmation step is required before
        executing any side-effectful action.
    reason
        Human-readable explanation of why this policy was derived.  Always
        non-empty.  Suitable for logging, dashboards, and downstream hints.
    source_phase
        The :class:`~core.continuum.types.TriStatePhase` value that
        contributed to this policy (``None`` if not available at resolution
        time).
    source_domain
        The :class:`~core.continuum.types.RuntimeDomain` value that
        contributed to this policy (``None`` if not available).
    source_authority_role
        The :class:`~core.orchestration_authority.AuthorityRole` value that
        contributed to this policy (``None`` if not available).
    return_pressure
        A normalised [0.0, 1.0] measure of current return/receding pressure
        derived from the :class:`~core.return_intelligence.ReturnSummary`.
        ``0.0`` = no return pressure; ``1.0`` = maximum return pressure.
    """

    # Core policy band
    policy_band: PolicyBand = PolicyBand.OBSERVE_ONLY

    # Numeric budgets
    risk_budget: float = 0.0
    action_budget: int = 0
    fallback_budget: int = 0

    # Executor constraints
    allowed_executor_levels: List[str] = dataclasses.field(default_factory=list)

    # Expansion and confirmation flags
    cross_device_allowed: bool = False
    requires_confirmation: bool = True

    # Human-readable reason
    reason: str = "default conservative policy"

    # Source signals (for traceability)
    source_phase: Optional[str] = None
    source_domain: Optional[str] = None
    source_authority_role: Optional[str] = None
    return_pressure: float = 0.0

    # ------------------------------------------------------------------
    # Derived helpers
    # ------------------------------------------------------------------

    @property
    def can_execute(self) -> bool:
        """True if the policy permits at least some direct execution."""
        return band_allows_execution(self.policy_band) and self.action_budget != 0

    @property
    def can_expand_cross_device(self) -> bool:
        """True if cross-device expansion is permitted by this policy."""
        return self.cross_device_allowed

    @property
    def should_require_confirmation(self) -> bool:
        """True if confirmation is required before side-effectful steps."""
        return self.requires_confirmation

    @property
    def max_executor_level(self) -> Optional[str]:
        """The last (highest) permitted executor level, or ``None`` if none."""
        return self.allowed_executor_levels[-1] if self.allowed_executor_levels else None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation.

        Enum values are converted to their string ``.value``.
        """
        return {
            "policy_band": self.policy_band.value,
            "risk_budget": self.risk_budget,
            "action_budget": self.action_budget,
            "fallback_budget": self.fallback_budget,
            "allowed_executor_levels": list(self.allowed_executor_levels),
            "cross_device_allowed": self.cross_device_allowed,
            "requires_confirmation": self.requires_confirmation,
            "reason": self.reason,
            "source_phase": self.source_phase,
            "source_domain": self.source_domain,
            "source_authority_role": self.source_authority_role,
            "return_pressure": self.return_pressure,
            # Derived helpers for convenience
            "can_execute": self.can_execute,
            "can_expand_cross_device": self.can_expand_cross_device,
            "should_require_confirmation": self.should_require_confirmation,
            "max_executor_level": self.max_executor_level,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionPolicy":
        """Reconstruct an :class:`ExecutionPolicy` from a previously
        serialised dict.

        Unknown or missing fields are silently ignored / defaulted.
        """
        try:
            band = PolicyBand(data.get("policy_band", PolicyBand.OBSERVE_ONLY.value))
        except (ValueError, KeyError):
            band = PolicyBand.OBSERVE_ONLY

        return cls(
            policy_band=band,
            risk_budget=float(data.get("risk_budget", 0.0)),
            action_budget=int(data.get("action_budget", 0)),
            fallback_budget=int(data.get("fallback_budget", 0)),
            allowed_executor_levels=list(data.get("allowed_executor_levels", [])),
            cross_device_allowed=bool(data.get("cross_device_allowed", False)),
            requires_confirmation=bool(data.get("requires_confirmation", True)),
            reason=str(data.get("reason", "reconstructed from dict")),
            source_phase=data.get("source_phase"),
            source_domain=data.get("source_domain"),
            source_authority_role=data.get("source_authority_role"),
            return_pressure=float(data.get("return_pressure", 0.0)),
        )

    def __repr__(self) -> str:
        return (
            f"<ExecutionPolicy "
            f"band={self.policy_band.value} "
            f"risk={self.risk_budget:.2f} "
            f"actions={self.action_budget} "
            f"cross_device={self.cross_device_allowed} "
            f"confirm={self.requires_confirmation}>"
        )


# ---------------------------------------------------------------------------
# Default conservative policy (safe fallback)
# ---------------------------------------------------------------------------

DEFAULT_CONSERVATIVE_POLICY: ExecutionPolicy = ExecutionPolicy(
    policy_band=PolicyBand.OBSERVE_ONLY,
    risk_budget=0.0,
    action_budget=0,
    fallback_budget=0,
    allowed_executor_levels=[],
    cross_device_allowed=False,
    requires_confirmation=True,
    reason="default conservative policy — no signals available",
    source_phase=None,
    source_domain=None,
    source_authority_role=None,
    return_pressure=0.0,
)
"""Pre-built :class:`ExecutionPolicy` representing the most conservative,
safe-fallback state.  Returned by the resolver whenever inputs are absent
or cannot be parsed.
"""
