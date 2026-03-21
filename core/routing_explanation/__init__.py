#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.routing_explanation
==========================

PR-21 (V4) — Routing Explanation & Decision Surface

A focused additive package that provides a **unified, serialisable routing
explanation layer** on top of the existing routing, projection, and policy
infrastructure.

Purpose
-------
As routing grows in complexity it must be explainable.  This package collects
the decision factors already present in the system (cross-device routing
posture, execution policy band, device health, capability state, device
formation, agent dispatch governance) and exposes them as a stable,
read-only surface that downstream code can inspect to understand *why* a
route was chosen.

Source signals consumed (read-only, not modified)
-------------------------------------------------
* :class:`~core.cross_device_policy.routing_policy.RoutingPolicy` /
  :class:`~core.cross_device_policy.assignment_summary.CrossDeviceAssignmentSummary`
  — posture, policy reason, expansion flag.
* :mod:`core.execution_policy` policy band and budget signals.
* :mod:`core.unified.device_health` :class:`~core.unified.device_health.HealthScore`
  composite score.
* :mod:`core.device_formation` formation membership and fallback.
* :mod:`core.agent_governance` dispatch role and handoff validity.
* Projection payloads assembled by :mod:`core.routes.projection`.

What this package does NOT do
------------------------------
- It does **not** replace or modify any router (DeviceRouter, LLMRouter, etc.).
- It does **not** add new routing strategies or change routing outcomes.
- It does **not** modify transport behaviour.
- It does **not** write state; all functions are read-only or produce new objects.

Public API
----------
DecisionFactor
    Enum of routing decision factor categories:
    ``policy``, ``health``, ``capability``, ``latency``,
    ``availability``, ``authority_role``, ``fallback``,
    ``execution_budget``, ``formation``, ``agent_handoff``.

factor_description(factor) → str
    Human-readable description of a :class:`DecisionFactor`.

DecisionBasis
    Frozen dataclass for a single decision factor entry.

make_decision_basis(factor, …) → DecisionBasis
    Safe factory for :class:`DecisionBasis`.

basis_from_health_score(device_id, score, threshold) → DecisionBasis
    Convenience builder from a device health score.

basis_from_policy_posture(posture, reason) → DecisionBasis
    Convenience builder from a routing posture and policy reason.

basis_from_availability(device_id, is_available) → DecisionBasis
    Convenience builder from a device availability flag.

basis_from_capability(name, is_available) → DecisionBasis
    Convenience builder from a capability availability check.

ConfidenceBand
    Enum: ``high`` / ``medium`` / ``low`` / ``undetermined``.

RouteConfidence
    Frozen dataclass for a routing confidence score.

compute_confidence(bases) → RouteConfidence
    Compute confidence from a list of :class:`DecisionBasis` entries.

UNDETERMINED_CONFIDENCE
    Pre-built :class:`RouteConfidence` for idle / no-data cases.

RejectedCandidate
    Frozen dataclass for a rejected route candidate.

RouteExplanation
    Frozen dataclass for the full per-decision explanation.

build_route_explanation(…) → RouteExplanation
    Factory; auto-computes confidence from bases.

EMPTY_ROUTE_EXPLANATION
    Pre-built :class:`RouteExplanation` for idle / no-data cases.

RoutingExplanationSummary
    Frozen dataclass for the public-facing summary surface.

build_explanation_summary(explanation) → RoutingExplanationSummary
    Convert a :class:`RouteExplanation` to a summary.

attach_explanation_to_projection(projection, summary) → dict
    Additively attach summary to a projection dict.

get_explanation_hints(summary) → dict
    Compact hint dict for quick-check consumers.

resolve_explanation_from_projection(projection) → RoutingExplanationSummary
    Derive a summary from an assembled projection dict without touching
    routing logic.

IDLE_EXPLANATION_SUMMARY
    Pre-built :class:`RoutingExplanationSummary` for idle / no-data cases.
"""

from .decision_basis import (
    DecisionFactor,
    FACTOR_DESCRIPTIONS,
    DecisionBasis,
    make_decision_basis,
    basis_from_health_score,
    basis_from_policy_posture,
    basis_from_availability,
    basis_from_capability,
    basis_list_to_dicts,
    factor_description,
)
from .route_confidence import (
    ConfidenceBand,
    CONFIDENCE_BAND_DESCRIPTIONS,
    RouteConfidence,
    compute_confidence,
    UNDETERMINED_CONFIDENCE,
)
from .route_explanation import (
    RejectedCandidate,
    RouteExplanation,
    build_route_explanation,
    EMPTY_ROUTE_EXPLANATION,
)
from .explanation_summary import (
    RoutingExplanationSummary,
    build_explanation_summary,
    attach_explanation_to_projection,
    get_explanation_hints,
    resolve_explanation_from_projection,
    IDLE_EXPLANATION_SUMMARY,
)

__all__ = [
    # Decision factor
    "DecisionFactor",
    "FACTOR_DESCRIPTIONS",
    "DecisionBasis",
    "make_decision_basis",
    "basis_from_health_score",
    "basis_from_policy_posture",
    "basis_from_availability",
    "basis_from_capability",
    "basis_list_to_dicts",
    "factor_description",
    # Confidence
    "ConfidenceBand",
    "CONFIDENCE_BAND_DESCRIPTIONS",
    "RouteConfidence",
    "compute_confidence",
    "UNDETERMINED_CONFIDENCE",
    # Explanation
    "RejectedCandidate",
    "RouteExplanation",
    "build_route_explanation",
    "EMPTY_ROUTE_EXPLANATION",
    # Summary
    "RoutingExplanationSummary",
    "build_explanation_summary",
    "attach_explanation_to_projection",
    "get_explanation_hints",
    "resolve_explanation_from_projection",
    "IDLE_EXPLANATION_SUMMARY",
]
