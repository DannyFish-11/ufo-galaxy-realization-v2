#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.explanation_summary
=============================================

PR-21 (V4) — Routing Explanation & Decision Surface

Defines the public-facing :class:`RoutingExplanationSummary` — the stable,
read-only surface through which all consumers inspect routing explanation data.

This module also provides:

- :func:`build_explanation_summary` — convert a
  :class:`~.route_explanation.RouteExplanation` to a summary in one call.
- :func:`attach_explanation_to_projection` — additively enrich a projection
  dict with ``"routing_explanation"`` and ``"explanation_hints"`` keys.
- :func:`get_explanation_hints` — extract a compact hint dict for quick-check
  consumers.
- :data:`IDLE_EXPLANATION_SUMMARY` — pre-built summary for idle / no-data cases.
- :func:`resolve_explanation_from_projection` — derive an explanation summary
  from available projection signals (cross-device routing, execution policy,
  device health) without touching routing logic.

Design rules
------------
- **Read-only** — this module never writes state or alters routing behaviour.
- Graceful degradation — all public functions accept partial/missing data
  and return safe defaults rather than raising.
- Stable serialisation — ``to_dict()`` output does not change between minor
  versions; new fields are always optional.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List, Optional

from .decision_basis import (
    DecisionBasis,
    DecisionFactor,
    basis_from_policy_posture,
    basis_from_health_score,
    basis_from_availability,
    basis_list_to_dicts,
    make_decision_basis,
)
from .route_confidence import (
    RouteConfidence,
    ConfidenceBand,
    compute_confidence,
    UNDETERMINED_CONFIDENCE,
)
from .route_explanation import (
    RejectedCandidate,
    RouteExplanation,
    build_route_explanation,
    EMPTY_ROUTE_EXPLANATION,
)

__all__ = [
    "RoutingExplanationSummary",
    "build_explanation_summary",
    "attach_explanation_to_projection",
    "get_explanation_hints",
    "resolve_explanation_from_projection",
    "IDLE_EXPLANATION_SUMMARY",
]


# ---------------------------------------------------------------------------
# RoutingExplanationSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RoutingExplanationSummary:
    """Public-facing summary of a routing decision explanation.

    This is the stable surface through which downstream code (status board,
    governance audits, debugging tools) reads routing explanation data.

    Attributes
    ----------
    schema_version:
        Integer version of this schema for forward-compatibility.  Currently 1.
    route_target:
        Device ID or route label of the selected route.  ``None`` if no route
        was chosen (idle, failed, or uninitialised).
    decision_basis_list:
        Ordered list of serialised :class:`~.decision_basis.DecisionBasis`
        entries (as dicts) that explain the routing decision.
    confidence:
        Serialised :class:`~.route_confidence.RouteConfidence` for the decision.
    rejected_alternatives:
        List of serialised :class:`~.route_explanation.RejectedCandidate` entries.
    fallback_plan:
        Description of the fallback path if the primary route fails.
        ``None`` if no fallback was defined.
    owner_agent:
        Agent role that owns this routing decision (e.g. ``"planner"``).
    owner_component:
        Module/component that produced this explanation.
    policy_posture:
        Routing posture string at decision time.
    policy_band:
        Execution-policy band at decision time (e.g. ``"bounded_execute"``).
    policy_reason:
        Human-readable policy narrative.
    is_cross_device:
        ``True`` if the selected route is a cross-device route.
    has_fallback:
        ``True`` if a fallback plan is defined.
    task_id:
        Traceability task identifier.
    trace_id:
        Distributed trace identifier.
    summarised_at:
        Unix timestamp of when this summary was assembled.
    """

    schema_version: int = 1
    route_target: Optional[str] = None
    decision_basis_list: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    confidence: Dict[str, Any] = dataclasses.field(
        default_factory=lambda: UNDETERMINED_CONFIDENCE.to_dict()
    )
    rejected_alternatives: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    fallback_plan: Optional[str] = None
    owner_agent: Optional[str] = None
    owner_component: Optional[str] = None
    policy_posture: str = "undecided"
    policy_band: Optional[str] = None
    policy_reason: str = "no routing decision recorded"
    is_cross_device: bool = False
    has_fallback: bool = False
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    summarised_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "schema_version": self.schema_version,
            "route_target": self.route_target,
            "decision_basis_list": list(self.decision_basis_list),
            "confidence": dict(self.confidence),
            "rejected_alternatives": list(self.rejected_alternatives),
            "fallback_plan": self.fallback_plan,
            "owner_agent": self.owner_agent,
            "owner_component": self.owner_component,
            "policy_posture": self.policy_posture,
            "policy_band": self.policy_band,
            "policy_reason": self.policy_reason,
            "is_cross_device": self.is_cross_device,
            "has_fallback": self.has_fallback,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "summarised_at": self.summarised_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RoutingExplanationSummary":
        """Reconstruct a :class:`RoutingExplanationSummary` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        return cls(
            schema_version=int(data.get("schema_version", 1)),
            route_target=data.get("route_target"),
            decision_basis_list=list(data.get("decision_basis_list", [])),
            confidence=dict(data.get("confidence", UNDETERMINED_CONFIDENCE.to_dict())),
            rejected_alternatives=list(data.get("rejected_alternatives", [])),
            fallback_plan=data.get("fallback_plan"),
            owner_agent=data.get("owner_agent"),
            owner_component=data.get("owner_component"),
            policy_posture=str(data.get("policy_posture", "undecided")),
            policy_band=data.get("policy_band"),
            policy_reason=str(data.get("policy_reason", "")),
            is_cross_device=bool(data.get("is_cross_device", False)),
            has_fallback=bool(data.get("has_fallback", False)),
            task_id=data.get("task_id"),
            trace_id=data.get("trace_id"),
            summarised_at=float(data.get("summarised_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Pre-built idle sentinel
# ---------------------------------------------------------------------------

IDLE_EXPLANATION_SUMMARY: RoutingExplanationSummary = RoutingExplanationSummary(
    schema_version=1,
    route_target=None,
    decision_basis_list=[],
    confidence=UNDETERMINED_CONFIDENCE.to_dict(),
    rejected_alternatives=[],
    fallback_plan=None,
    owner_agent=None,
    owner_component="routing_explanation",
    policy_posture="undecided",
    policy_band=None,
    policy_reason="no routing decision recorded — idle or uninitialised",
    is_cross_device=False,
    has_fallback=False,
    task_id=None,
    trace_id=None,
)
"""Pre-built :class:`RoutingExplanationSummary` for idle / no-data cases."""


# ---------------------------------------------------------------------------
# build_explanation_summary
# ---------------------------------------------------------------------------


def build_explanation_summary(
    explanation: RouteExplanation,
) -> RoutingExplanationSummary:
    """Convert a :class:`~.route_explanation.RouteExplanation` to a summary.

    This is the canonical way to produce a :class:`RoutingExplanationSummary`
    from a full explanation object.  The function never raises.

    Args:
        explanation: A :class:`~.route_explanation.RouteExplanation` produced
            by :func:`~.route_explanation.build_route_explanation`.

    Returns:
        A frozen :class:`RoutingExplanationSummary`.
    """
    try:
        return _build_summary_impl(explanation)
    except Exception:
        return IDLE_EXPLANATION_SUMMARY


def _build_summary_impl(explanation: RouteExplanation) -> RoutingExplanationSummary:
    # Postures that do NOT represent cross-device routing.
    # These string values correspond to RoutingPosture enum values in
    # core.cross_device_policy.routing_policy — kept as literals here
    # to avoid a hard import dependency from the explanation layer into
    # the routing policy module (explanation is read-only / downstream).
    _LOCAL_POSTURES = {"local_preferred", "undecided"}
    is_cross = explanation.policy_posture not in _LOCAL_POSTURES

    return RoutingExplanationSummary(
        schema_version=1,
        route_target=explanation.selected_target,
        decision_basis_list=basis_list_to_dicts(explanation.decision_bases),
        confidence=explanation.confidence.to_dict(),
        rejected_alternatives=[rc.to_dict() for rc in explanation.rejected_candidates],
        fallback_plan=explanation.fallback_plan,
        owner_agent=explanation.owner_agent,
        owner_component=explanation.owner_component,
        policy_posture=explanation.policy_posture,
        policy_band=explanation.policy_band,
        policy_reason=explanation.policy_reason,
        is_cross_device=is_cross,
        has_fallback=explanation.fallback_plan is not None,
        task_id=explanation.task_id,
        trace_id=explanation.trace_id,
    )


# ---------------------------------------------------------------------------
# resolve_explanation_from_projection
# ---------------------------------------------------------------------------


def resolve_explanation_from_projection(
    projection: Dict[str, Any],
) -> RoutingExplanationSummary:
    """Derive a :class:`RoutingExplanationSummary` from an assembled projection dict.

    This function reads existing signals from the projection payload — cross-device
    routing posture, execution policy band, device formation, agent dispatch —
    and assembles an explanation summary **without** modifying any routing logic.

    It is the primary integration point used by the
    ``GET /api/v1/projection/routing-explanation`` endpoint.

    Args:
        projection: A dict assembled by one of the ``_assemble_projection_with_*``
            helpers in :mod:`core.routes.projection`.

    Returns:
        A :class:`RoutingExplanationSummary`.  Never raises.
    """
    try:
        return _resolve_from_projection_impl(projection)
    except Exception:
        return IDLE_EXPLANATION_SUMMARY


def _resolve_from_projection_impl(
    projection: Dict[str, Any],
) -> RoutingExplanationSummary:
    bases: List[DecisionBasis] = []
    rejected: List[RejectedCandidate] = []

    # ------------------------------------------------------------------
    # 1. Cross-device routing signals
    # ------------------------------------------------------------------
    cross_device = projection.get("cross_device_routing", {}) or {}
    posture = str(cross_device.get("posture", "undecided"))
    policy_reason = str(cross_device.get("policy_reason", "no policy reason available"))
    is_cross_device: bool = bool(cross_device.get("is_cross_device", False))

    primary_target: Optional[str] = (
        cross_device.get("primary_execution_device_id")
        or cross_device.get("source_device_id")
    )

    if posture != "undecided":
        bases.append(basis_from_policy_posture(posture, policy_reason))

    expansion_allowed: bool = bool(
        cross_device.get("expansion_allowed_by_execution_policy", False)
    )
    if not expansion_allowed and is_cross_device:
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.POLICY,
                signal_value=expansion_allowed,
                description="Cross-device expansion is blocked by execution policy",
                accepted=False,
                weight=0.25,
            )
        )

    # ------------------------------------------------------------------
    # 2. Execution policy signals
    # ------------------------------------------------------------------
    exec_policy = projection.get("execution_policy", {}) or {}
    policy_band: Optional[str] = exec_policy.get("policy_band")

    if policy_band:
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.EXECUTION_BUDGET,
                signal_value=policy_band,
                description=f"Execution policy band: '{policy_band}'",
                accepted=True,
                weight=0.20,
            )
        )

    can_execute: bool = bool(exec_policy.get("can_execute", True))
    if not can_execute:
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.EXECUTION_BUDGET,
                signal_value=can_execute,
                description="Execution policy does not permit task execution in current band",
                accepted=False,
                weight=0.20,
            )
        )

    # ------------------------------------------------------------------
    # 3. Device formation signals
    # ------------------------------------------------------------------
    formation = projection.get("device_formation", {}) or {}
    formation_reason = formation.get("formation_reason", "")
    if formation_reason and formation_reason != "no active formation":
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.FORMATION,
                signal_value=formation.get("is_multi_device", False),
                description=f"Device formation: {formation_reason}",
                accepted=True,
                weight=0.10,
            )
        )

    fallback_available: bool = bool(formation.get("fallback_available", False))
    fallback_plan: Optional[str] = None
    if fallback_available:
        fallback_device_ids = formation.get("fallback_device_ids", [])
        if fallback_device_ids:
            fallback_plan = (
                f"Fallback device(s) available: {', '.join(fallback_device_ids)}"
            )
        else:
            fallback_plan = "Fallback path available (device IDs not specified)"

    # ------------------------------------------------------------------
    # 4. Agent dispatch signals
    # ------------------------------------------------------------------
    agent_dispatch = projection.get("agent_dispatch", {}) or {}
    dispatch_role = agent_dispatch.get("dispatch_role", "unassigned")
    owner_agent: Optional[str] = None if dispatch_role == "unassigned" else dispatch_role

    handoff_valid: bool = bool(agent_dispatch.get("handoff_valid", False))
    if dispatch_role not in ("unassigned", ""):
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.AGENT_HANDOFF,
                signal_value=dispatch_role,
                description=f"Agent dispatch role: '{dispatch_role}' (handoff valid: {handoff_valid})",
                accepted=handoff_valid,
                weight=0.10,
            )
        )

    # ------------------------------------------------------------------
    # 5. Derive fallback explanation entry if fallback is engaged
    # ------------------------------------------------------------------
    if fallback_available and fallback_plan:
        bases.append(
            make_decision_basis(
                factor=DecisionFactor.FALLBACK,
                signal_value=True,
                description=fallback_plan,
                accepted=True,
                weight=0.05,
            )
        )

    # ------------------------------------------------------------------
    # 6. Build the explanation and summarise
    # ------------------------------------------------------------------
    explanation = build_route_explanation(
        selected_target=primary_target,
        decision_bases=bases,
        rejected_candidates=rejected,
        policy_posture=posture,
        policy_reason=policy_reason,
        policy_band=policy_band,
        fallback_plan=fallback_plan,
        owner_agent=owner_agent,
        owner_component="routing_explanation",
        task_id=None,
        trace_id=None,
    )
    return build_explanation_summary(explanation)


# ---------------------------------------------------------------------------
# attach_explanation_to_projection
# ---------------------------------------------------------------------------


def attach_explanation_to_projection(
    projection: Dict[str, Any],
    summary: RoutingExplanationSummary,
) -> Dict[str, Any]:
    """Additively attach a routing explanation summary to a projection dict.

    This function is **additive and non-mutating** — it creates a new dict
    that contains all existing projection keys plus ``"routing_explanation"``.

    Args:
        projection: Existing projection dict (not modified in-place).
        summary:    :class:`RoutingExplanationSummary` to attach.

    Returns:
        A new dict with the ``"routing_explanation"`` key added.
    """
    result = dict(projection)
    result["routing_explanation"] = summary.to_dict()
    return result


# ---------------------------------------------------------------------------
# get_explanation_hints
# ---------------------------------------------------------------------------


def get_explanation_hints(
    summary: RoutingExplanationSummary,
) -> Dict[str, Any]:
    """Return a compact hint dict for quick-check consumers.

    The hints dict exposes the most commonly needed boolean and scalar signals
    without requiring callers to navigate the full explanation structure.

    Args:
        summary: A :class:`RoutingExplanationSummary`.

    Returns:
        A flat JSON-serialisable dict with routing explanation quick-checks.
    """
    conf = summary.confidence
    conf_band = conf.get("band", ConfidenceBand.UNDETERMINED.value) if isinstance(conf, dict) else ConfidenceBand.UNDETERMINED.value
    conf_score = conf.get("score", 0.0) if isinstance(conf, dict) else 0.0

    return {
        "route_target": summary.route_target,
        "policy_posture": summary.policy_posture,
        "policy_band": summary.policy_band,
        "confidence_score": round(conf_score, 4),
        "confidence_band": conf_band,
        "is_cross_device": summary.is_cross_device,
        "has_fallback": summary.has_fallback,
        "has_rejected_alternatives": len(summary.rejected_alternatives) > 0,
        "rejected_count": len(summary.rejected_alternatives),
        "basis_count": len(summary.decision_basis_list),
        "owner_agent": summary.owner_agent,
    }
