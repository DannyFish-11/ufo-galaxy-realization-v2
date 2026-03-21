#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.decision_basis
=========================================

PR-21 (V4) — Routing Explanation & Decision Surface

Defines the **decision factor taxonomy** and the :class:`DecisionBasis`
dataclass that captures a single factor contributing to a routing decision.

Decision factors are gathered from existing routing signals — device health
scores, cross-device policy postures, capability checks, latency observations,
and availability state — and unified into a stable, serialisable representation
that downstream code can inspect without altering routing outcomes.

Design rules
------------
- All models are **read-only** at consumption time.
- ``to_dict()`` output is JSON-serialisable and stable across versions.
- The factory :func:`make_decision_basis` accepts partial inputs and degrades
  gracefully so explanation assembly never raises.
"""

from __future__ import annotations

import dataclasses
import time
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "DecisionFactor",
    "FACTOR_DESCRIPTIONS",
    "DecisionBasis",
    "make_decision_basis",
]


# ---------------------------------------------------------------------------
# Decision factor enum
# ---------------------------------------------------------------------------


class DecisionFactor(str, Enum):
    """Taxonomy of factors that can influence a routing decision.

    String values are stable identifiers safe for serialisation and logging.
    """

    POLICY = "policy"
    """The routing posture or cross-device policy drove this factor."""

    HEALTH = "health"
    """Device health score (latency, error rate, jitter, heartbeat) contributed."""

    CAPABILITY = "capability"
    """Capability availability or capability constraint flags contributed."""

    LATENCY = "latency"
    """Observed or estimated round-trip latency was a deciding signal."""

    AVAILABILITY = "availability"
    """Device or service availability (online/offline/degraded) was a signal."""

    AUTHORITY_ROLE = "authority_role"
    """The current orchestration authority role affected routing permission."""

    FALLBACK = "fallback"
    """A fallback path was engaged because the preferred route was unavailable."""

    EXECUTION_BUDGET = "execution_budget"
    """Execution policy budget (risk, action, confirmation) limited options."""

    FORMATION = "formation"
    """Device formation membership or barrier posture contributed."""

    AGENT_HANDOFF = "agent_handoff"
    """Agent dispatch governance or handoff depth constrained the route."""


# ---------------------------------------------------------------------------
# Human-readable descriptions
# ---------------------------------------------------------------------------

FACTOR_DESCRIPTIONS: Dict[str, str] = {
    DecisionFactor.POLICY.value: (
        "The routing posture (local_preferred, remote_required, split_execution, "
        "etc.) derived from execution policy and runtime domain drove this aspect "
        "of the decision."
    ),
    DecisionFactor.HEALTH.value: (
        "The device health scorer reported a composite health score based on "
        "latency, error rate, jitter, and heartbeat stability.  Devices below the "
        "health threshold were deprioritised or excluded."
    ),
    DecisionFactor.CAPABILITY.value: (
        "Capability availability or constraint flags (locked, degraded, pending) "
        "determined whether the device or route could satisfy the task requirements."
    ),
    DecisionFactor.LATENCY.value: (
        "Observed or estimated round-trip latency was used to rank candidate "
        "devices.  High latency routes were penalised in the scoring step."
    ),
    DecisionFactor.AVAILABILITY.value: (
        "The device or service availability state (online, offline, degraded) "
        "was checked before the route could be accepted."
    ),
    DecisionFactor.AUTHORITY_ROLE.value: (
        "The current orchestration authority role (e.g. AUTHORITATIVE_ENTRYPOINT, "
        "LEGACY_COMPATIBILITY) from core.orchestration_authority affected whether "
        "cross-device expansion was permitted."
    ),
    DecisionFactor.FALLBACK.value: (
        "The preferred primary route was unavailable; a fallback device or route "
        "was engaged according to the active fallback policy."
    ),
    DecisionFactor.EXECUTION_BUDGET.value: (
        "The execution policy budget (risk budget, action budget, confirmation "
        "requirement) constrained the set of acceptable routes."
    ),
    DecisionFactor.FORMATION.value: (
        "Device formation membership or barrier posture (wait_primary, "
        "wait_all_members, etc.) influenced which device received the task."
    ),
    DecisionFactor.AGENT_HANDOFF.value: (
        "Agent dispatch governance (handoff depth, valid handoff edges, ownership "
        "transfer policy) constrained which agent role could receive the dispatch."
    ),
}


def factor_description(factor: DecisionFactor) -> str:
    """Return a human-readable description for *factor*."""
    return FACTOR_DESCRIPTIONS.get(factor.value, f"Unknown factor: {factor.value}")


# ---------------------------------------------------------------------------
# DecisionBasis dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class DecisionBasis:
    """A single factor that contributed to (or constrained) a routing decision.

    Attributes
    ----------
    factor:
        The :class:`DecisionFactor` category for this basis entry.
    signal_value:
        Raw signal value captured at decision time (e.g. a health score float,
        a posture string, a latency in ms).  Always a JSON-serialisable scalar
        or ``None``.
    description:
        Human-readable explanation of how this factor affected the decision.
    accepted:
        ``True`` if this factor *favoured* the selected route; ``False`` if it
        was a constraint or rejection signal that was overridden (e.g. fallback).
    weight:
        Relative weight of this factor in the overall confidence calculation.
        In range ``[0.0, 1.0]``.  ``None`` when weight is not applicable.
    recorded_at:
        Unix timestamp of when this basis entry was created.
    """

    factor: DecisionFactor
    signal_value: Optional[Any] = None
    description: str = ""
    accepted: bool = True
    weight: Optional[float] = None
    recorded_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "factor": self.factor.value,
            "signal_value": self.signal_value,
            "description": self.description or factor_description(self.factor),
            "accepted": self.accepted,
            "weight": round(self.weight, 4) if self.weight is not None else None,
            "recorded_at": self.recorded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DecisionBasis":
        """Reconstruct a :class:`DecisionBasis` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        try:
            factor = DecisionFactor(data.get("factor", DecisionFactor.POLICY.value))
        except (ValueError, KeyError):
            factor = DecisionFactor.POLICY

        return cls(
            factor=factor,
            signal_value=data.get("signal_value"),
            description=str(data.get("description", "")),
            accepted=bool(data.get("accepted", True)),
            weight=float(data["weight"]) if data.get("weight") is not None else None,
            recorded_at=float(data.get("recorded_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def make_decision_basis(
    factor: Any,
    signal_value: Optional[Any] = None,
    description: str = "",
    accepted: bool = True,
    weight: Optional[float] = None,
) -> DecisionBasis:
    """Create a :class:`DecisionBasis` entry with coercion and safe defaults.

    Args:
        factor: A :class:`DecisionFactor` value, its string representation,
            or any object that can be coerced.  Falls back to
            :attr:`DecisionFactor.POLICY` on unknown input.
        signal_value: Raw signal value (any JSON-serialisable scalar, or None).
        description: Human-readable explanation of the factor's influence.
        accepted: Whether this factor favoured (``True``) or constrained
            (``False``) the selected route.
        weight: Relative weight in ``[0.0, 1.0]``, or ``None``.

    Returns:
        A new :class:`DecisionBasis` instance.  Never raises.
    """
    try:
        if isinstance(factor, DecisionFactor):
            coerced = factor
        elif isinstance(factor, str):
            coerced = DecisionFactor(factor)
        else:
            coerced = DecisionFactor(str(factor))
    except (ValueError, KeyError):
        coerced = DecisionFactor.POLICY

    clamped_weight: Optional[float] = None
    if weight is not None:
        try:
            clamped_weight = float(max(0.0, min(1.0, weight)))
        except (TypeError, ValueError):
            clamped_weight = None

    return DecisionBasis(
        factor=coerced,
        signal_value=signal_value,
        description=description or factor_description(coerced),
        accepted=bool(accepted),
        weight=clamped_weight,
    )


# ---------------------------------------------------------------------------
# Convenience builders for common signal sources
# ---------------------------------------------------------------------------


def basis_from_health_score(
    device_id: str,
    health_score: float,
    threshold: float = 0.5,
) -> DecisionBasis:
    """Build a :class:`DecisionBasis` entry from a device health score.

    Args:
        device_id:    Device identifier (included in description).
        health_score: Composite health score in ``[0.0, 1.0]``.
        threshold:    Minimum score to be considered healthy (default 0.5).

    Returns:
        A :class:`DecisionBasis` with factor :attr:`DecisionFactor.HEALTH`.
    """
    accepted = health_score >= threshold
    description = (
        f"Device '{device_id}' health score {health_score:.3f} "
        f"({'accepted' if accepted else 'below threshold ' + str(threshold)})"
    )
    return make_decision_basis(
        factor=DecisionFactor.HEALTH,
        signal_value=round(health_score, 4),
        description=description,
        accepted=accepted,
        weight=0.35,  # mirrors _W_LATENCY dominant weight in DeviceHealthScorer
    )


def basis_from_policy_posture(posture: str, reason: str) -> DecisionBasis:
    """Build a :class:`DecisionBasis` from a routing posture and policy reason.

    Args:
        posture: Routing posture string (e.g. ``"local_preferred"``).
        reason:  Policy narrative explaining why this posture was chosen.

    Returns:
        A :class:`DecisionBasis` with factor :attr:`DecisionFactor.POLICY`.
    """
    description = f"Routing posture '{posture}': {reason}"
    return make_decision_basis(
        factor=DecisionFactor.POLICY,
        signal_value=posture,
        description=description,
        accepted=True,
        weight=0.30,
    )


def basis_from_availability(device_id: str, is_available: bool) -> DecisionBasis:
    """Build a :class:`DecisionBasis` from a device availability flag.

    Args:
        device_id:    Device identifier.
        is_available: ``True`` if the device is currently reachable/online.

    Returns:
        A :class:`DecisionBasis` with factor :attr:`DecisionFactor.AVAILABILITY`.
    """
    status = "online" if is_available else "offline/unavailable"
    description = f"Device '{device_id}' availability: {status}"
    return make_decision_basis(
        factor=DecisionFactor.AVAILABILITY,
        signal_value=is_available,
        description=description,
        accepted=is_available,
        weight=0.20,
    )


def basis_from_capability(capability_name: str, is_available: bool) -> DecisionBasis:
    """Build a :class:`DecisionBasis` from a capability availability check.

    Args:
        capability_name: Name of the capability checked.
        is_available:    ``True`` if the capability is available and routable.

    Returns:
        A :class:`DecisionBasis` with factor :attr:`DecisionFactor.CAPABILITY`.
    """
    status = "available" if is_available else "unavailable/constrained"
    description = f"Capability '{capability_name}': {status}"
    return make_decision_basis(
        factor=DecisionFactor.CAPABILITY,
        signal_value=is_available,
        description=description,
        accepted=is_available,
        weight=0.15,
    )


def basis_list_to_dicts(bases: List[DecisionBasis]) -> List[Dict[str, Any]]:
    """Convert a list of :class:`DecisionBasis` entries to a list of dicts."""
    return [b.to_dict() for b in bases]
