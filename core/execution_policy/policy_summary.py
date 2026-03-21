#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.execution_policy.policy_summary
========================================

PR-11 (V4) — Execution Policy Schema

Provides stable, public-safe summary helpers for
:class:`~core.execution_policy.ExecutionPolicy` objects.

These helpers are designed for downstream consumers that need lightweight,
read-only access to policy information without depending on the full policy
object:

  * Status Board V2 surfaces
  * ``RuntimeProjection`` attachment
  * Manifest Stage controllers
  * Liminal layer hints
  * Read-only API endpoints

Public API
----------
summarise_policy(policy) → dict
    Serialize a policy into a compact, JSON-safe dict.

get_policy_hints(policy) → dict
    Return a minimal dict of boolean/scalar downstream hints.

attach_policy_to_projection(projection_dict, policy) → dict
    Attach an execution-policy summary to a projection dict in an additive,
    backward-compatible way.

build_policy_for_projection(projection_dict) → dict
    Convenience function: resolve and attach policy directly from a
    RuntimeProjection dict.

Design rules
------------
- All functions are pure and stateless.
- They never modify their inputs.
- They accept ``None`` gracefully and return safe defaults.
- They never raise — all exceptions are caught and logged.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .execution_policy import ExecutionPolicy, DEFAULT_CONSERVATIVE_POLICY
from .policy_band import PolicyBand

logger = logging.getLogger("Galaxy.ExecutionPolicy.Summary")

__all__ = [
    "summarise_policy",
    "get_policy_hints",
    "attach_policy_to_projection",
    "build_policy_for_projection",
]


# ---------------------------------------------------------------------------
# Primary serialisation helper
# ---------------------------------------------------------------------------


def summarise_policy(policy: Optional[ExecutionPolicy]) -> Dict[str, Any]:
    """Serialise an :class:`~.execution_policy.ExecutionPolicy` to a stable dict.

    Parameters
    ----------
    policy:
        An :class:`~.execution_policy.ExecutionPolicy` instance, or ``None``.
        When ``None``, the summary of
        :data:`~.execution_policy.DEFAULT_CONSERVATIVE_POLICY` is returned.

    Returns
    -------
    dict
        A JSON-serialisable dict with all policy fields.  Enum values are
        converted to their string ``.value``.  Never raises.
    """
    try:
        target = policy if policy is not None else DEFAULT_CONSERVATIVE_POLICY
        return target.to_dict()
    except Exception as exc:  # pragma: no cover
        logger.warning("summarise_policy: error serialising policy: %s", exc)
        return _fallback_summary()


# ---------------------------------------------------------------------------
# Hints helper
# ---------------------------------------------------------------------------


def get_policy_hints(policy: Optional[ExecutionPolicy]) -> Dict[str, Any]:
    """Return a compact dict of boolean/scalar downstream hints.

    Designed for quick checks in Manifest Stage controllers, Liminal engines,
    and Status Board surfaces that need a minimal API without importing the
    full policy object.

    Parameters
    ----------
    policy:
        An :class:`~.execution_policy.ExecutionPolicy` instance, or ``None``.

    Returns
    -------
    dict with keys:
        - ``policy_band``              (str)
        - ``can_execute``              (bool)
        - ``can_expand_cross_device``  (bool)
        - ``should_require_confirmation`` (bool)
        - ``max_executor_level``       (str | None)
        - ``risk_budget``              (float)
        - ``action_budget``            (int)
        - ``return_pressure``          (float)
    """
    try:
        target = policy if policy is not None else DEFAULT_CONSERVATIVE_POLICY
        return {
            "policy_band": target.policy_band.value,
            "can_execute": target.can_execute,
            "can_expand_cross_device": target.can_expand_cross_device,
            "should_require_confirmation": target.should_require_confirmation,
            "max_executor_level": target.max_executor_level,
            "risk_budget": target.risk_budget,
            "action_budget": target.action_budget,
            "return_pressure": target.return_pressure,
        }
    except Exception as exc:  # pragma: no cover
        logger.warning("get_policy_hints: error extracting hints: %s", exc)
        return {
            "policy_band": PolicyBand.OBSERVE_ONLY.value,
            "can_execute": False,
            "can_expand_cross_device": False,
            "should_require_confirmation": True,
            "max_executor_level": None,
            "risk_budget": 0.0,
            "action_budget": 0,
            "return_pressure": 0.0,
        }


# ---------------------------------------------------------------------------
# Additive projection attachment
# ---------------------------------------------------------------------------


def attach_policy_to_projection(
    projection: Dict[str, Any],
    policy: Optional[ExecutionPolicy],
) -> Dict[str, Any]:
    """Attach an execution-policy summary to a projection dict.

    Returns a **new** dict with ``"execution_policy"`` added.  The original
    ``projection`` dict is never modified.  Existing projection fields remain
    unchanged.

    Parameters
    ----------
    projection:
        A dict conforming to the :class:`~core.projection.RuntimeProjection`
        schema (or any compatible dict).
    policy:
        An :class:`~.execution_policy.ExecutionPolicy` to attach, or ``None``
        (uses :data:`~.execution_policy.DEFAULT_CONSERVATIVE_POLICY`).

    Returns
    -------
    dict
        A shallow copy of ``projection`` with ``"execution_policy"`` added.

    Example
    -------
    ::

        enriched = attach_policy_to_projection(projection.to_dict(), policy)
        # enriched["execution_policy"]["policy_band"] → "bounded_execute"
        # enriched["tri_state_phase"] → unchanged
    """
    try:
        enriched = dict(projection)
        enriched["execution_policy"] = summarise_policy(policy)
        return enriched
    except Exception as exc:  # pragma: no cover
        logger.warning("attach_policy_to_projection: error attaching policy: %s", exc)
        fallback = dict(projection)
        fallback["execution_policy"] = _fallback_summary()
        return fallback


# ---------------------------------------------------------------------------
# Convenience: resolve + attach from a projection dict
# ---------------------------------------------------------------------------


def build_policy_for_projection(projection: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve an :class:`~.execution_policy.ExecutionPolicy` from a
    ``RuntimeProjection`` dict and return a compact hints dict.

    This convenience function extracts available signals from a projection
    dict (``tri_state_phase``, ``runtime_domain``, ``retreat_tendency``,
    ``collapse_tendency``) and calls the resolver, then returns the hints
    dict suitable for embedding in a status surface.

    Parameters
    ----------
    projection:
        A dict conforming to the :class:`~core.projection.RuntimeProjection`
        schema.

    Returns
    -------
    dict
        The hints dict from :func:`get_policy_hints`.

    Example
    -------
    ::

        hints = build_policy_for_projection(projection.to_dict())
        if hints["can_execute"]:
            ...
    """
    try:
        from .policy_resolver import resolve_policy

        phase_str = projection.get("tri_state_phase")
        domain_str = projection.get("runtime_domain")
        retreat = projection.get("retreat_tendency")
        collapse = projection.get("collapse_tendency")

        # Optionally pull return intelligence if it's already attached
        return_summary = projection.get("return_intelligence")

        policy = resolve_policy(
            phase=phase_str,
            domain=domain_str,
            return_summary=return_summary,
            retreat_tendency=float(retreat) if retreat is not None else None,
            collapse_tendency=float(collapse) if collapse is not None else None,
        )
        return get_policy_hints(policy)
    except Exception as exc:  # pragma: no cover
        logger.warning("build_policy_for_projection: error building policy: %s", exc)
        return get_policy_hints(None)


# ---------------------------------------------------------------------------
# Internal fallback
# ---------------------------------------------------------------------------


def _fallback_summary() -> Dict[str, Any]:
    """Return a minimal safe summary dict when normal serialisation fails."""
    return {
        "policy_band": PolicyBand.OBSERVE_ONLY.value,
        "risk_budget": 0.0,
        "action_budget": 0,
        "fallback_budget": 0,
        "allowed_executor_levels": [],
        "cross_device_allowed": False,
        "requires_confirmation": True,
        "reason": "policy summary unavailable",
        "source_phase": None,
        "source_domain": None,
        "source_authority_role": None,
        "return_pressure": 0.0,
        "can_execute": False,
        "can_expand_cross_device": False,
        "should_require_confirmation": True,
        "max_executor_level": None,
    }
