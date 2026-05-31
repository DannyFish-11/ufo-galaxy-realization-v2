#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation.route_explanation
============================================

PR-21 (V4) — Routing Explanation & Decision Surface

Defines :class:`RouteExplanation`, the full per-decision explanation object
that captures:

- The selected primary route target (device_id or route label)
- The list of :class:`~.decision_basis.DecisionBasis` entries describing why
  the route was chosen
- The computed :class:`~.route_confidence.RouteConfidence`
- Rejected alternatives with their rejection reasons
- The active routing posture and policy narrative

:class:`RouteExplanation` is the **internal representation** produced by the
routing explanation layer and consumed by :mod:`.explanation_summary` to
generate the public-facing :class:`~.explanation_summary.RoutingExplanationSummary`.

Design rules
------------
- All models are **read-only** at consumption time (frozen dataclasses).
- ``to_dict()`` output is JSON-serialisable and stable.
- :class:`RejectedCandidate` carries enough context to explain *why* a device
  or route was not chosen, without re-running routing logic.
- Factory :func:`build_route_explanation` accepts partial inputs and degrades
  gracefully so explanation assembly never raises.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List, Optional

from .decision_basis import DecisionBasis, basis_list_to_dicts
from .route_confidence import RouteConfidence, compute_confidence, UNDETERMINED_CONFIDENCE

__all__ = [
    "RejectedCandidate",
    "RouteExplanation",
    "build_route_explanation",
    "EMPTY_ROUTE_EXPLANATION",
]


# ---------------------------------------------------------------------------
# RejectedCandidate dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RejectedCandidate:
    """A device or route that was considered but not selected.

    Attributes
    ----------
    candidate_id:
        Device identifier or route label of the rejected candidate.
    rejection_reason:
        Human-readable reason why this candidate was not selected.
    health_score:
        Health score at rejection time, if available (``None`` otherwise).
    capability_match:
        ``True`` if the candidate's capabilities matched requirements,
        ``False`` if capabilities were insufficient, ``None`` if not checked.
    was_available:
        ``True`` if the candidate was online/reachable at the time of routing,
        ``False`` if it was unreachable, ``None`` if not known.
    """

    candidate_id: str
    rejection_reason: str = "not selected"
    health_score: Optional[float] = None
    capability_match: Optional[bool] = None
    was_available: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "candidate_id": self.candidate_id,
            "rejection_reason": self.rejection_reason,
            "health_score": (
                round(self.health_score, 4) if self.health_score is not None else None
            ),
            "capability_match": self.capability_match,
            "was_available": self.was_available,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RejectedCandidate":
        """Reconstruct a :class:`RejectedCandidate` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        hs = data.get("health_score")
        return cls(
            candidate_id=str(data.get("candidate_id", "unknown")),
            rejection_reason=str(data.get("rejection_reason", "not selected")),
            health_score=float(hs) if hs is not None else None,
            capability_match=(
                bool(data["capability_match"])
                if data.get("capability_match") is not None
                else None
            ),
            was_available=(
                bool(data["was_available"])
                if data.get("was_available") is not None
                else None
            ),
        )


# ---------------------------------------------------------------------------
# RouteExplanation dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RouteExplanation:
    """Full per-decision routing explanation.

    Attributes
    ----------
    selected_target:
        Device identifier or route label of the chosen primary route.
        ``None`` if no route was selected (e.g. routing failed).
    decision_bases:
        Ordered list of :class:`~.decision_basis.DecisionBasis` entries that
        contributed to the routing decision.
    confidence:
        Computed :class:`~.route_confidence.RouteConfidence` derived from the
        decision bases.
    rejected_candidates:
        Devices or routes that were evaluated but not selected.
    policy_posture:
        Routing posture string at decision time (e.g. ``"local_preferred"``).
    policy_reason:
        Human-readable narrative from the routing policy resolver.
    policy_band:
        Execution-policy band at decision time (e.g. ``"bounded_execute"``).
        ``None`` if execution policy layer was unavailable.
    fallback_plan:
        Description of the fallback plan if the primary route fails.
        ``None`` if no fallback was defined.
    owner_agent:
        Agent role that owns this routing decision (e.g. ``"planner"``).
        ``None`` if not applicable.
    owner_component:
        Component or module that produced this explanation
        (e.g. ``"DeviceRouter"``).
        ``None`` if not set.
    task_id:
        Optional task identifier for traceability.
    trace_id:
        Optional distributed-trace identifier.
    explained_at:
        Unix timestamp of when this explanation was assembled.
    """

    selected_target: Optional[str] = None
    decision_bases: List[DecisionBasis] = dataclasses.field(default_factory=list)
    confidence: RouteConfidence = dataclasses.field(
        default_factory=lambda: UNDETERMINED_CONFIDENCE
    )
    rejected_candidates: List[RejectedCandidate] = dataclasses.field(default_factory=list)
    policy_posture: str = "undecided"
    policy_reason: str = "no routing decision recorded"
    policy_band: Optional[str] = None
    fallback_plan: Optional[str] = None
    owner_agent: Optional[str] = None
    owner_component: Optional[str] = None
    task_id: Optional[str] = None
    trace_id: Optional[str] = None
    explained_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "selected_target": self.selected_target,
            "decision_bases": basis_list_to_dicts(self.decision_bases),
            "confidence": self.confidence.to_dict(),
            "rejected_candidates": [rc.to_dict() for rc in self.rejected_candidates],
            "policy_posture": self.policy_posture,
            "policy_reason": self.policy_reason,
            "policy_band": self.policy_band,
            "fallback_plan": self.fallback_plan,
            "owner_agent": self.owner_agent,
            "owner_component": self.owner_component,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "explained_at": self.explained_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteExplanation":
        """Reconstruct a :class:`RouteExplanation` from a serialised dict.

        Unknown or missing fields are silently defaulted.
        """
        from .decision_basis import DecisionBasis as _DB

        raw_bases = data.get("decision_bases", [])
        bases: List[DecisionBasis] = []
        for raw in raw_bases:
            if isinstance(raw, dict):
                try:
                    bases.append(_DB.from_dict(raw))
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            elif isinstance(raw, DecisionBasis):
                bases.append(raw)

        raw_candidates = data.get("rejected_candidates", [])
        candidates: List[RejectedCandidate] = []
        for raw in raw_candidates:
            if isinstance(raw, dict):
                try:
                    candidates.append(RejectedCandidate.from_dict(raw))
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
            elif isinstance(raw, RejectedCandidate):
                candidates.append(raw)

        raw_conf = data.get("confidence", {})
        if isinstance(raw_conf, dict):
            try:
                confidence = RouteConfidence.from_dict(raw_conf)
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                confidence = UNDETERMINED_CONFIDENCE
        elif isinstance(raw_conf, RouteConfidence):
            confidence = raw_conf
        else:
            confidence = UNDETERMINED_CONFIDENCE

        return cls(
            selected_target=data.get("selected_target"),
            decision_bases=bases,
            confidence=confidence,
            rejected_candidates=candidates,
            policy_posture=str(data.get("policy_posture", "undecided")),
            policy_reason=str(data.get("policy_reason", "")),
            policy_band=data.get("policy_band"),
            fallback_plan=data.get("fallback_plan"),
            owner_agent=data.get("owner_agent"),
            owner_component=data.get("owner_component"),
            task_id=data.get("task_id"),
            trace_id=data.get("trace_id"),
            explained_at=float(data.get("explained_at", time.time())),
        )


# ---------------------------------------------------------------------------
# Pre-built sentinel
# ---------------------------------------------------------------------------

EMPTY_ROUTE_EXPLANATION: RouteExplanation = RouteExplanation(
    selected_target=None,
    decision_bases=[],
    confidence=UNDETERMINED_CONFIDENCE,
    rejected_candidates=[],
    policy_posture="undecided",
    policy_reason="no routing decision recorded — idle or uninitialised",
    policy_band=None,
    fallback_plan=None,
    owner_agent=None,
    owner_component="routing_explanation",
    task_id=None,
    trace_id=None,
)
"""Pre-built :class:`RouteExplanation` for idle / no-data cases."""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def build_route_explanation(
    *,
    selected_target: Optional[str] = None,
    decision_bases: Optional[List[DecisionBasis]] = None,
    rejected_candidates: Optional[List[RejectedCandidate]] = None,
    policy_posture: str = "undecided",
    policy_reason: str = "",
    policy_band: Optional[str] = None,
    fallback_plan: Optional[str] = None,
    owner_agent: Optional[str] = None,
    owner_component: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> RouteExplanation:
    """Build a :class:`RouteExplanation` with automatic confidence computation.

    Confidence is derived from the provided *decision_bases* via
    :func:`~.route_confidence.compute_confidence`.

    All parameters are optional.  The function never raises.

    Args:
        selected_target:    Device ID or route label of the chosen route.
        decision_bases:     List of :class:`~.decision_basis.DecisionBasis`
                            entries collected during routing.
        rejected_candidates: Devices or routes that were not selected.
        policy_posture:     Routing posture string.
        policy_reason:      Human-readable policy narrative.
        policy_band:        Execution-policy band string, or ``None``.
        fallback_plan:      Fallback description, or ``None``.
        owner_agent:        Agent role owning the decision, or ``None``.
        owner_component:    Component that produced this explanation.
        task_id:            Traceability task identifier.
        trace_id:           Distributed trace identifier.

    Returns:
        A frozen :class:`RouteExplanation`.
    """
    try:
        return _build_impl(
            selected_target=selected_target,
            decision_bases=decision_bases or [],
            rejected_candidates=rejected_candidates or [],
            policy_posture=policy_posture,
            policy_reason=policy_reason,
            policy_band=policy_band,
            fallback_plan=fallback_plan,
            owner_agent=owner_agent,
            owner_component=owner_component or "routing_explanation",
            task_id=task_id,
            trace_id=trace_id,
        )
    except Exception as exc:
        return EMPTY_ROUTE_EXPLANATION


def _build_impl(
    *,
    selected_target: Optional[str],
    decision_bases: List[DecisionBasis],
    rejected_candidates: List[RejectedCandidate],
    policy_posture: str,
    policy_reason: str,
    policy_band: Optional[str],
    fallback_plan: Optional[str],
    owner_agent: Optional[str],
    owner_component: str,
    task_id: Optional[str],
    trace_id: Optional[str],
) -> RouteExplanation:
    confidence = compute_confidence(decision_bases)

    return RouteExplanation(
        selected_target=selected_target,
        decision_bases=list(decision_bases),
        confidence=confidence,
        rejected_candidates=list(rejected_candidates),
        policy_posture=policy_posture,
        policy_reason=policy_reason or "no policy narrative provided",
        policy_band=policy_band,
        fallback_plan=fallback_plan,
        owner_agent=owner_agent,
        owner_component=owner_component,
        task_id=task_id,
        trace_id=trace_id,
    )
