#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cross_device_policy.assignment_summary
=============================================

PR-13 (V4) — Cross-Device Role & Routing Policy

Provides stable, public-safe summary helpers for
:class:`~core.cross_device_policy.RoutingPolicy` objects.

These helpers are designed for downstream consumers that need lightweight,
read-only access to cross-device routing information without depending on the
full policy objects:

  * ``RuntimeProjection`` attachment
  * Status Board V2 surfaces
  * Manifest Stage controllers
  * Execution-observability payloads
  * Read-only API endpoints

Public API
----------
CrossDeviceAssignmentSummary
    Serialisable dataclass carrying the full cross-device routing state,
    including role assignments and routing posture.

IDLE_ASSIGNMENT_SUMMARY
    Pre-built summary for local-only / no-cross-device state.

build_assignment_summary(policy) → CrossDeviceAssignmentSummary
    Convert a :class:`~.routing_policy.RoutingPolicy` to a public-safe summary.

attach_cross_device_to_projection(projection_dict, summary) → dict
    Attach a summary to a ``RuntimeProjection`` dict additively.

get_assignment_hints(summary) → dict
    Compact boolean/scalar hints for quick downstream checks.

Design rules
------------
- All functions are pure and stateless.
- They never modify their inputs.
- They accept ``None`` gracefully and return safe defaults.
- They never raise — all exceptions are caught and logged.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, List, Optional

from .device_role import DeviceRole, DeviceRoleAssignment
from .routing_policy import RoutingPolicy, RoutingPosture, DEFAULT_LOCAL_ROUTING_POLICY

logger = logging.getLogger("Galaxy.CrossDevicePolicy.Summary")

__all__ = [
    "CrossDeviceAssignmentSummary",
    "IDLE_ASSIGNMENT_SUMMARY",
    "build_assignment_summary",
    "attach_cross_device_to_projection",
    "get_assignment_hints",
]


# ---------------------------------------------------------------------------
# Summary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CrossDeviceAssignmentSummary:
    """Stable, serialisable summary of a cross-device routing assignment.

    Produced by :func:`build_assignment_summary` from a
    :class:`~.routing_policy.RoutingPolicy`.  Safe to expose through APIs,
    Status Board, and projection surfaces.

    Attributes
    ----------
    posture:
        String representation of the routing posture.
    source_device_id:
        Identifier of the request-originating device, or ``None``.
    primary_execution_device_id:
        Identifier of the primary executor, or ``None`` if not yet assigned.
    support_device_ids:
        List of device IDs assigned a SUPPORT role.
    observer_device_ids:
        List of device IDs assigned an OBSERVER role.
    relay_device_ids:
        List of device IDs assigned a RELAY role.
    fallback_device_ids:
        List of device IDs assigned a FALLBACK role.
    all_assignments:
        Full list of serialised :class:`~.device_role.DeviceRoleAssignment`
        dicts.
    runtime_domain_intent:
        The intended runtime domain (plain string).
    expansion_allowed_by_execution_policy:
        Whether execution policy allows cross-device expansion.
    confirmation_required_before_expansion:
        Whether confirmation is required before expanding cross-device.
    is_cross_device:
        Convenience flag: True if the posture involves more than one device.
    policy_reason:
        Human-readable explanation of the routing choice.
    task_id:
        Optional task identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    """

    posture: str = RoutingPosture.UNDECIDED.value
    source_device_id: Optional[str] = None
    primary_execution_device_id: Optional[str] = None
    support_device_ids: List[str] = dataclasses.field(default_factory=list)
    observer_device_ids: List[str] = dataclasses.field(default_factory=list)
    relay_device_ids: List[str] = dataclasses.field(default_factory=list)
    fallback_device_ids: List[str] = dataclasses.field(default_factory=list)
    all_assignments: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    runtime_domain_intent: Optional[str] = None
    expansion_allowed_by_execution_policy: bool = False
    confirmation_required_before_expansion: bool = True
    is_cross_device: bool = False
    policy_reason: str = "no cross-device signals available"
    task_id: Optional[str] = None
    trace_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "posture": self.posture,
            "source_device_id": self.source_device_id,
            "primary_execution_device_id": self.primary_execution_device_id,
            "support_device_ids": list(self.support_device_ids),
            "observer_device_ids": list(self.observer_device_ids),
            "relay_device_ids": list(self.relay_device_ids),
            "fallback_device_ids": list(self.fallback_device_ids),
            "all_assignments": list(self.all_assignments),
            "runtime_domain_intent": self.runtime_domain_intent,
            "expansion_allowed_by_execution_policy": (
                self.expansion_allowed_by_execution_policy
            ),
            "confirmation_required_before_expansion": (
                self.confirmation_required_before_expansion
            ),
            "is_cross_device": self.is_cross_device,
            "policy_reason": self.policy_reason,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CrossDeviceAssignmentSummary":
        """Reconstruct a :class:`CrossDeviceAssignmentSummary` from a dict.

        Unknown or missing fields are silently defaulted.
        """
        return cls(
            posture=str(data.get("posture", RoutingPosture.UNDECIDED.value)),
            source_device_id=data.get("source_device_id"),
            primary_execution_device_id=data.get("primary_execution_device_id"),
            support_device_ids=list(data.get("support_device_ids", [])),
            observer_device_ids=list(data.get("observer_device_ids", [])),
            relay_device_ids=list(data.get("relay_device_ids", [])),
            fallback_device_ids=list(data.get("fallback_device_ids", [])),
            all_assignments=list(data.get("all_assignments", [])),
            runtime_domain_intent=data.get("runtime_domain_intent"),
            expansion_allowed_by_execution_policy=bool(
                data.get("expansion_allowed_by_execution_policy", False)
            ),
            confirmation_required_before_expansion=bool(
                data.get("confirmation_required_before_expansion", True)
            ),
            is_cross_device=bool(data.get("is_cross_device", False)),
            policy_reason=str(data.get("policy_reason", "reconstructed from dict")),
            task_id=data.get("task_id"),
            trace_id=data.get("trace_id"),
        )

    def __repr__(self) -> str:
        return (
            f"<CrossDeviceAssignmentSummary "
            f"posture={self.posture} "
            f"primary={self.primary_execution_device_id!r} "
            f"cross_device={self.is_cross_device}>"
        )


# ---------------------------------------------------------------------------
# Pre-built idle summary
# ---------------------------------------------------------------------------

IDLE_ASSIGNMENT_SUMMARY: CrossDeviceAssignmentSummary = CrossDeviceAssignmentSummary(
    posture=RoutingPosture.LOCAL_PREFERRED.value,
    source_device_id=None,
    primary_execution_device_id=None,
    support_device_ids=[],
    observer_device_ids=[],
    relay_device_ids=[],
    fallback_device_ids=[],
    all_assignments=[],
    runtime_domain_intent="local",
    expansion_allowed_by_execution_policy=False,
    confirmation_required_before_expansion=True,
    is_cross_device=False,
    policy_reason="idle local state — no cross-device activity",
    task_id=None,
    trace_id=None,
)
"""Pre-built :class:`CrossDeviceAssignmentSummary` for local-only state.

Returned by helpers whenever no cross-device signals are available.
"""


# ---------------------------------------------------------------------------
# Primary builder
# ---------------------------------------------------------------------------


def build_assignment_summary(
    policy: Optional[RoutingPolicy],
) -> CrossDeviceAssignmentSummary:
    """Convert a :class:`~.routing_policy.RoutingPolicy` to a
    :class:`CrossDeviceAssignmentSummary`.

    Parameters
    ----------
    policy:
        A :class:`~.routing_policy.RoutingPolicy` instance, or ``None``.
        When ``None``, returns :data:`IDLE_ASSIGNMENT_SUMMARY`.

    Returns
    -------
    CrossDeviceAssignmentSummary
        A stable, JSON-serialisable summary.  Never raises.
    """
    try:
        target = policy if policy is not None else DEFAULT_LOCAL_ROUTING_POLICY

        def _ids(role: DeviceRole) -> List[str]:
            return [
                a.device_id
                for a in target.assigned_devices
                if a.role is role and a.device_id is not None
            ]

        return CrossDeviceAssignmentSummary(
            posture=target.posture.value,
            source_device_id=target.source_device_id,
            primary_execution_device_id=target.primary_execution_device_id,
            support_device_ids=_ids(DeviceRole.SUPPORT),
            observer_device_ids=_ids(DeviceRole.OBSERVER),
            relay_device_ids=_ids(DeviceRole.RELAY),
            fallback_device_ids=_ids(DeviceRole.FALLBACK),
            all_assignments=[a.to_dict() for a in target.assigned_devices],
            runtime_domain_intent=target.runtime_domain_intent,
            expansion_allowed_by_execution_policy=(
                target.expansion_allowed_by_execution_policy
            ),
            confirmation_required_before_expansion=(
                target.confirmation_required_before_expansion
            ),
            is_cross_device=target.is_cross_device,
            policy_reason=target.policy_reason,
            task_id=target.task_id,
            trace_id=target.trace_id,
        )
    except Exception as exc:  # pragma: no cover
        logger.warning("build_assignment_summary: error building summary: %s", exc)
        return IDLE_ASSIGNMENT_SUMMARY


# ---------------------------------------------------------------------------
# Additive projection attachment
# ---------------------------------------------------------------------------


def attach_cross_device_to_projection(
    projection: Dict[str, Any],
    summary: Optional[CrossDeviceAssignmentSummary],
) -> Dict[str, Any]:
    """Attach a cross-device routing summary to a projection dict.

    Returns a **new** dict with ``"cross_device_routing"`` added.  The
    original ``projection`` dict is never modified.  Existing projection
    fields remain unchanged.

    Parameters
    ----------
    projection:
        A dict conforming to the ``RuntimeProjection`` schema (or any
        compatible dict).
    summary:
        A :class:`CrossDeviceAssignmentSummary` to attach, or ``None``
        (attaches :data:`IDLE_ASSIGNMENT_SUMMARY`).

    Returns
    -------
    dict
        A shallow copy of ``projection`` with ``"cross_device_routing"``
        added.
    """
    try:
        enriched = dict(projection)
        target = summary if summary is not None else IDLE_ASSIGNMENT_SUMMARY
        enriched["cross_device_routing"] = target.to_dict()
        return enriched
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "attach_cross_device_to_projection: error attaching summary: %s", exc
        )
        fallback = dict(projection)
        fallback["cross_device_routing"] = IDLE_ASSIGNMENT_SUMMARY.to_dict()
        return fallback


# ---------------------------------------------------------------------------
# Compact hints helper
# ---------------------------------------------------------------------------


def get_assignment_hints(
    summary: Optional[CrossDeviceAssignmentSummary],
) -> Dict[str, Any]:
    """Return a compact dict of boolean/scalar downstream hints.

    Designed for quick checks in Manifest Stage controllers, TaskGraph
    handlers, and Status Board surfaces that need a minimal API without
    importing the full summary object.

    Parameters
    ----------
    summary:
        A :class:`CrossDeviceAssignmentSummary` instance, or ``None``
        (uses :data:`IDLE_ASSIGNMENT_SUMMARY`).

    Returns
    -------
    dict with keys:
        - ``posture``                               (str)
        - ``is_cross_device``                       (bool)
        - ``has_primary``                           (bool)
        - ``has_fallback``                          (bool)
        - ``expansion_allowed_by_execution_policy`` (bool)
        - ``confirmation_required_before_expansion``(bool)
        - ``primary_execution_device_id``           (str | None)
        - ``source_device_id``                      (str | None)
        - ``support_count``                         (int)
        - ``observer_count``                        (int)
    """
    try:
        target = summary if summary is not None else IDLE_ASSIGNMENT_SUMMARY
        return {
            "posture": target.posture,
            "is_cross_device": target.is_cross_device,
            "has_primary": target.primary_execution_device_id is not None,
            "has_fallback": len(target.fallback_device_ids) > 0,
            "expansion_allowed_by_execution_policy": (
                target.expansion_allowed_by_execution_policy
            ),
            "confirmation_required_before_expansion": (
                target.confirmation_required_before_expansion
            ),
            "primary_execution_device_id": target.primary_execution_device_id,
            "source_device_id": target.source_device_id,
            "support_count": len(target.support_device_ids),
            "observer_count": len(target.observer_device_ids),
        }
    except Exception as exc:  # pragma: no cover
        logger.warning("get_assignment_hints: error extracting hints: %s", exc)
        return {
            "posture": RoutingPosture.UNDECIDED.value,
            "is_cross_device": False,
            "has_primary": False,
            "has_fallback": False,
            "expansion_allowed_by_execution_policy": False,
            "confirmation_required_before_expansion": True,
            "primary_execution_device_id": None,
            "source_device_id": None,
            "support_count": 0,
            "observer_count": 0,
        }
