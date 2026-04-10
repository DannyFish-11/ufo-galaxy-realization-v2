#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.cognitive_activation_budget
==========================================

PR-18 — Cognitive Activation Budgeting Layer

Canonical activation-budget layer that translates
:class:`~core.cognitive.cognitive_execution_policy.CognitiveExecutionHint`
outputs into bounded runtime guidance for:

- node activation intensity (``ActivationBudget``)
- planner breadth / exploration scope (``PlannerBreadthGuidance``)
- soft candidate-node widening / narrowing

Design principles
-----------------
- **Soft guidance, not hard authority**: ``ActivationBudget`` and
  ``PlannerBreadthGuidance`` are *influence* objects.  They never replace
  lifecycle governance, invocation governance, or node activation-context
  readiness (PR-11, PR-14, PR-15 node tracks).
- **Hard gates remain authoritative**: any narrowing performed via
  :func:`apply_candidate_narrowing` will never include nodes that the hard
  governance layer has already denied.  The budget layer operates *above*
  the hard-gate layer, not beside it.
- **Derived from existing hints**: ``ActivationBudget`` is derived solely
  from the already-computed :class:`~core.cognitive.cognitive_execution_policy.CognitiveExecutionHint`.
  No new cognitive pipeline is started.
- **Additive**: all consumers fall back gracefully when budget is absent.

Cognitive posture to budget mapping
------------------------------------
PASSIVE / SILENT  ->  intensity=low,      breadth=narrow,   max_candidates=5
LIMINAL           ->  intensity=moderate,  breadth=moderate, max_candidates=10
MANIFEST          ->  intensity=high,      breadth=broad,    max_candidates=unlimited

Authority sentinels
-------------------
COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY
    Asserts this module is the canonical activation-budget layer (PR-18).

COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL
    Machine-checkable sentinel confirming the budgeting layer is present.

Usage::

    from core.cognitive.cognitive_activation_budget import (
        derive_activation_budget,
        get_planner_breadth_guidance,
        apply_candidate_narrowing,
        ActivationBudget,
        PlannerBreadthGuidance,
    )
    from core.cognitive.cognitive_execution_policy import derive_cognitive_execution_hint

    hint = derive_cognitive_execution_hint()
    budget = derive_activation_budget(hint)
    guidance = get_planner_breadth_guidance(budget)
    print(guidance.breadth_mode)       # "narrow" | "moderate" | "broad"
    print(guidance.max_concurrent_agents)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.Cognitive.ActivationBudget")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

COGNITIVE_ACTIVATION_BUDGET_IS_AUTHORITY: str = (
    "COGNITIVE_ACTIVATION_BUDGET::CANONICAL_AUTHORITY: "
    "core.cognitive.cognitive_activation_budget is the canonical activation-budget "
    "layer for PR-18.  It translates CognitiveExecutionHint outputs into bounded "
    "ActivationBudget and PlannerBreadthGuidance objects.  It does not replace "
    "lifecycle governance, invocation governance, or node activation-context "
    "readiness checks."
)

COGNITIVE_ACTIVATION_BUDGET_PR18_SENTINEL: str = (
    "COGNITIVE_ACTIVATION_BUDGET::PR18_SENTINEL: "
    "Cognitive activation budgeting (PR-18) is present and active.  "
    "ActivationBudget is derived from CognitiveExecutionHint.activation_budget "
    "and wired into ExecutionPlanner breadth guidance and kernel execution handling."
)

# Policy sentinels
HARD_GATES_REMAIN_AUTHORITATIVE_POLICY: str = (
    "COGNITIVE_ACTIVATION_BUDGET::POLICY_1: "
    "Hard gates (lifecycle governance, invocation governance, node activation-context "
    "readiness) are ALWAYS authoritative.  ActivationBudget is a soft influence layer "
    "that operates above and alongside hard gates, never replacing them."
)

BUDGET_IS_SOFT_INFLUENCE_NOT_HARD_GATE_POLICY: str = (
    "COGNITIVE_ACTIVATION_BUDGET::POLICY_2: "
    "ActivationBudget is a soft, advisory influence on execution intensity and "
    "planner breadth.  Consumers MUST NOT treat it as a hard eligibility gate.  "
    "A budget of 0.0 does not mean no execution — it means prefer minimal/deferred."
)

BUDGET_DERIVED_FROM_COGNITIVE_HINT_POLICY: str = (
    "COGNITIVE_ACTIVATION_BUDGET::POLICY_3: "
    "ActivationBudget is always derived from a CognitiveExecutionHint produced by "
    "core.cognitive.cognitive_execution_policy.  No second cognitive pipeline is "
    "started; the budget re-uses the already-computed hint."
)

CANDIDATE_NARROWING_RESPECTS_HARD_GATES_POLICY: str = (
    "COGNITIVE_ACTIVATION_BUDGET::POLICY_4: "
    "apply_candidate_narrowing() applies a soft max-candidate limit based on the "
    "activation budget.  When governance_allowed is provided, only nodes present "
    "in that set can appear in the narrowed result.  Budget narrowing never "
    "re-admits a node that a hard gate has already denied."
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Breadth modes
BREADTH_MODE_NARROW: str = "narrow"
BREADTH_MODE_MODERATE: str = "moderate"
BREADTH_MODE_BROAD: str = "broad"

# Intensity levels
INTENSITY_LOW: str = "low"
INTENSITY_MODERATE: str = "moderate"
INTENSITY_HIGH: str = "high"

# Max candidate node counts per breadth mode
_MAX_CANDIDATES_NARROW: int = 5
_MAX_CANDIDATES_MODERATE: int = 10
_MAX_CANDIDATES_BROAD: int = 9999  # effectively unlimited

# Max concurrent agents per breadth mode
_MAX_AGENTS_NARROW: int = 1
_MAX_AGENTS_MODERATE: int = 3
_MAX_AGENTS_BROAD: int = 20  # matches ExecutionPlanner swarm cap

# Complexity threshold adjustments per breadth mode
# These offset the ExecutionPlanner's existing complexity thresholds so that
# passive posture raises the bar for complex strategies (fewer strategies
# trigger) and manifest posture lowers the bar (more strategies are eligible).
_COMPLEXITY_ADJ_NARROW: float = +0.15   # passive: harder to unlock complex strategies
_COMPLEXITY_ADJ_MODERATE: float = 0.0   # liminal: no adjustment
_COMPLEXITY_ADJ_BROAD: float = -0.10    # manifest: easier to unlock complex strategies

# Budget thresholds for intensity classification
_THRESHOLD_LOW_MAX: float = 0.40     # budget <= 0.40 → low intensity
_THRESHOLD_MODERATE_MAX: float = 0.75  # budget <= 0.75 → moderate intensity
# budget > 0.75 → high intensity


# ---------------------------------------------------------------------------
# ActivationBudget dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivationBudget:
    """Bounded, advisory activation budget derived from a CognitiveExecutionHint.

    This dataclass is the canonical output of :func:`derive_activation_budget`.
    All fields have safe defaults; consumers must never assume any field is
    non-None.

    Attributes
    ----------
    budget_value:
        Normalised activation budget [0.0, 1.0] carried from
        :attr:`~core.cognitive.cognitive_execution_policy.CognitiveExecutionHint.activation_budget`.
    intensity:
        Execution intensity level: ``"low"`` / ``"moderate"`` / ``"high"``.
    breadth_mode:
        Planner breadth mode: ``"narrow"`` / ``"moderate"`` / ``"broad"``.
    max_candidate_nodes:
        Soft upper bound on the number of candidate nodes to consider.
        This is advisory; hard governance gates are independent.
    max_concurrent_agents:
        Soft upper bound on concurrent agent count.
    strategy_preference:
        Optional preferred strategy bias: ``"single"`` for narrow posture,
        ``None`` for moderate/broad (no bias).
    cognitive_region:
        The cognitive region that produced this budget
        (``"silent"`` / ``"passive"`` / ``"liminal"`` / ``"manifest"``).
    influenced_by_budget:
        Always ``True`` when returned by :func:`derive_activation_budget`.
    source:
        ``"cognitive_activation_budget"`` when derived from live signals;
        ``"fallback"`` otherwise.
    timestamp:
        Unix epoch at budget derivation time.
    """

    budget_value: float = 0.2
    intensity: str = INTENSITY_LOW
    breadth_mode: str = BREADTH_MODE_NARROW
    max_candidate_nodes: int = _MAX_CANDIDATES_NARROW
    max_concurrent_agents: int = _MAX_AGENTS_NARROW
    strategy_preference: Optional[str] = "single"
    cognitive_region: str = "silent"
    influenced_by_budget: bool = True
    source: str = "cognitive_activation_budget"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "budget_value": round(self.budget_value, 4),
            "intensity": self.intensity,
            "breadth_mode": self.breadth_mode,
            "max_candidate_nodes": self.max_candidate_nodes,
            "max_concurrent_agents": self.max_concurrent_agents,
            "strategy_preference": self.strategy_preference,
            "cognitive_region": self.cognitive_region,
            "influenced_by_budget": self.influenced_by_budget,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def is_narrow(self) -> bool:
        """Return True when breadth mode is narrow (passive/silent)."""
        return self.breadth_mode == BREADTH_MODE_NARROW

    def is_moderate(self) -> bool:
        """Return True when breadth mode is moderate (liminal)."""
        return self.breadth_mode == BREADTH_MODE_MODERATE

    def is_broad(self) -> bool:
        """Return True when breadth mode is broad (manifest)."""
        return self.breadth_mode == BREADTH_MODE_BROAD


# ---------------------------------------------------------------------------
# Fallback budget (safe default when hint is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_ACTIVATION_BUDGET: ActivationBudget = ActivationBudget(
    budget_value=0.2,
    intensity=INTENSITY_LOW,
    breadth_mode=BREADTH_MODE_NARROW,
    max_candidate_nodes=_MAX_CANDIDATES_NARROW,
    max_concurrent_agents=_MAX_AGENTS_NARROW,
    strategy_preference="single",
    cognitive_region="silent",
    influenced_by_budget=False,
    source="fallback",
)


# ---------------------------------------------------------------------------
# PlannerBreadthGuidance dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerBreadthGuidance:
    """Planner breadth guidance derived from an :class:`ActivationBudget`.

    This dataclass is the canonical output of :func:`get_planner_breadth_guidance`.

    Attributes
    ----------
    breadth_mode:
        Suggested breadth mode: ``"narrow"`` / ``"moderate"`` / ``"broad"``.
    max_concurrent_agents:
        Advisory upper bound on concurrent agent count.
    complexity_threshold_adjustment:
        Float offset applied to existing complexity thresholds.  A positive
        value raises the bar for complex strategies (passive posture); a
        negative value lowers it (manifest posture).
    strategy_preference:
        Optional preferred strategy hint: ``"single"`` for narrow posture,
        ``None`` for moderate/broad.
    budget_value:
        The ``ActivationBudget.budget_value`` that produced this guidance.
    influenced_by_budget:
        True when this guidance was derived from an active budget (not fallback).
    diagnostic_note:
        Human-readable note explaining the breadth decision.
    """

    breadth_mode: str = BREADTH_MODE_NARROW
    max_concurrent_agents: int = _MAX_AGENTS_NARROW
    complexity_threshold_adjustment: float = _COMPLEXITY_ADJ_NARROW
    strategy_preference: Optional[str] = "single"
    budget_value: float = 0.2
    influenced_by_budget: bool = True
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "breadth_mode": self.breadth_mode,
            "max_concurrent_agents": self.max_concurrent_agents,
            "complexity_threshold_adjustment": round(self.complexity_threshold_adjustment, 4),
            "strategy_preference": self.strategy_preference,
            "budget_value": round(self.budget_value, 4),
            "influenced_by_budget": self.influenced_by_budget,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Core derivation: CognitiveExecutionHint → ActivationBudget
# ---------------------------------------------------------------------------


def derive_activation_budget(
    hint: Optional[Any],
    *,
    trace_id: Optional[str] = None,
) -> ActivationBudget:
    """Derive an :class:`ActivationBudget` from a :class:`CognitiveExecutionHint`.

    Parameters
    ----------
    hint:
        A :class:`~core.cognitive.cognitive_execution_policy.CognitiveExecutionHint`
        or ``None``.  When ``None`` or when the hint is a fallback hint,
        :data:`FALLBACK_ACTIVATION_BUDGET` is returned.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    ActivationBudget
        A bounded, advisory budget derived from the hint.  Never raises —
        returns :data:`FALLBACK_ACTIVATION_BUDGET` on any error.
    """
    try:
        return _derive_budget_impl(hint=hint, trace_id=trace_id)
    except Exception as exc:
        logger.debug(
            "derive_activation_budget: error (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return FALLBACK_ACTIVATION_BUDGET


def _derive_budget_impl(
    *,
    hint: Optional[Any],
    trace_id: Optional[str],
) -> ActivationBudget:
    """Internal implementation of budget derivation."""
    if hint is None:
        logger.debug(
            "derive_activation_budget: hint is None (trace_id=%s) — using fallback", trace_id
        )
        return FALLBACK_ACTIVATION_BUDGET

    # Read budget_value and cognitive_region from the hint
    budget_value: float = float(getattr(hint, "activation_budget", 0.2))
    cognitive_region: str = str(getattr(hint, "cognitive_region", "silent"))
    cognitive_wiring_active: bool = bool(getattr(hint, "cognitive_wiring_active", False))

    # If the hint is a fallback (wiring not active), return fallback budget
    if not cognitive_wiring_active:
        logger.debug(
            "derive_activation_budget: hint is fallback (trace_id=%s) — using fallback budget",
            trace_id,
        )
        return FALLBACK_ACTIVATION_BUDGET

    # Classify intensity
    intensity = _classify_intensity(budget_value)

    # Derive breadth mode from cognitive region (region is primary driver)
    breadth_mode = _region_to_breadth_mode(cognitive_region)

    # Derive per-breadth values
    max_candidates = _breadth_to_max_candidates(breadth_mode)
    max_agents = _breadth_to_max_agents(breadth_mode)
    strategy_pref = _breadth_to_strategy_preference(breadth_mode)

    logger.debug(
        "CognitiveActivationBudget: region=%s budget=%.3f intensity=%s breadth=%s "
        "max_candidates=%d max_agents=%d trace_id=%s",
        cognitive_region,
        budget_value,
        intensity,
        breadth_mode,
        max_candidates,
        max_agents,
        trace_id,
    )

    return ActivationBudget(
        budget_value=round(budget_value, 4),
        intensity=intensity,
        breadth_mode=breadth_mode,
        max_candidate_nodes=max_candidates,
        max_concurrent_agents=max_agents,
        strategy_preference=strategy_pref,
        cognitive_region=cognitive_region,
        influenced_by_budget=True,
        source="cognitive_activation_budget",
    )


# ---------------------------------------------------------------------------
# PlannerBreadthGuidance derivation
# ---------------------------------------------------------------------------


def get_planner_breadth_guidance(
    budget: Optional[ActivationBudget],
    *,
    trace_id: Optional[str] = None,
) -> PlannerBreadthGuidance:
    """Translate an :class:`ActivationBudget` into :class:`PlannerBreadthGuidance`.

    Parameters
    ----------
    budget:
        An :class:`ActivationBudget` or ``None``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    PlannerBreadthGuidance
        Guidance for the planner.  Never raises.
    """
    try:
        if budget is None or not budget.influenced_by_budget:
            return PlannerBreadthGuidance(
                breadth_mode=BREADTH_MODE_NARROW,
                max_concurrent_agents=_MAX_AGENTS_NARROW,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_NARROW,
                strategy_preference="single",
                budget_value=0.2,
                influenced_by_budget=False,
                diagnostic_note="activation_budget_unavailable: using narrow fallback",
            )

        breadth = budget.breadth_mode
        if breadth == BREADTH_MODE_NARROW:
            note = (
                f"activation_budget={budget.budget_value:.3f} (region={budget.cognitive_region}): "
                "passive posture — narrow breadth, prefer single-agent execution"
            )
            return PlannerBreadthGuidance(
                breadth_mode=BREADTH_MODE_NARROW,
                max_concurrent_agents=_MAX_AGENTS_NARROW,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_NARROW,
                strategy_preference="single",
                budget_value=budget.budget_value,
                influenced_by_budget=True,
                diagnostic_note=note,
            )
        elif breadth == BREADTH_MODE_MODERATE:
            note = (
                f"activation_budget={budget.budget_value:.3f} (region={budget.cognitive_region}): "
                "liminal posture — moderate breadth, planning-oriented exploration"
            )
            return PlannerBreadthGuidance(
                breadth_mode=BREADTH_MODE_MODERATE,
                max_concurrent_agents=_MAX_AGENTS_MODERATE,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_MODERATE,
                strategy_preference=None,
                budget_value=budget.budget_value,
                influenced_by_budget=True,
                diagnostic_note=note,
            )
        else:  # BREADTH_MODE_BROAD
            note = (
                f"activation_budget={budget.budget_value:.3f} (region={budget.cognitive_region}): "
                "manifest posture — broad breadth, high-intensity direct execution"
            )
            return PlannerBreadthGuidance(
                breadth_mode=BREADTH_MODE_BROAD,
                max_concurrent_agents=_MAX_AGENTS_BROAD,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_BROAD,
                strategy_preference=None,
                budget_value=budget.budget_value,
                influenced_by_budget=True,
                diagnostic_note=note,
            )
    except Exception as exc:
        logger.debug("get_planner_breadth_guidance: error: %s", exc)
        return PlannerBreadthGuidance(
            breadth_mode=BREADTH_MODE_NARROW,
            max_concurrent_agents=_MAX_AGENTS_NARROW,
            complexity_threshold_adjustment=_COMPLEXITY_ADJ_NARROW,
            strategy_preference="single",
            budget_value=0.2,
            influenced_by_budget=False,
            diagnostic_note=f"error_fallback: {exc}",
        )


# ---------------------------------------------------------------------------
# Candidate narrowing
# ---------------------------------------------------------------------------


def apply_candidate_narrowing(
    candidate_node_ids: List[str],
    budget: Optional[ActivationBudget],
    *,
    governance_allowed: Optional[Set[str]] = None,
    trace_id: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Apply soft candidate narrowing based on activation budget.

    This function applies a soft upper bound on the number of candidate nodes
    based on the activation budget.  It DOES NOT enforce hard governance gates.

    The ``governance_allowed`` parameter is used to ensure this function never
    re-admits a node that a hard gate has already denied.  When provided, the
    result will only contain nodes present in ``governance_allowed``.

    Parameters
    ----------
    candidate_node_ids:
        The full list of candidate node IDs to potentially narrow.
    budget:
        An :class:`ActivationBudget` or ``None``.  When ``None``, no narrowing
        is applied; all candidates (filtered by governance_allowed) are returned.
    governance_allowed:
        Optional set of node IDs that hard governance gates have already cleared.
        When provided, the narrowed result will only include nodes in this set.
        This preserves the authority of hard gates.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    Tuple[List[str], Dict[str, Any]]
        ``(narrowed_candidates, diagnostics)``
        - ``narrowed_candidates``: the (possibly narrowed and governance-filtered)
          list of node IDs.
        - ``diagnostics``: a dict describing whether and how narrowing was applied.
    """
    diag: Dict[str, Any] = {
        "input_count": len(candidate_node_ids),
        "governance_filter_applied": governance_allowed is not None,
        "budget_narrowing_applied": False,
        "narrowed_by": "none",
        "output_count": 0,
        "trace_id": trace_id,
    }

    try:
        # Step 1: Apply hard governance filter (preserves hard-gate authority)
        if governance_allowed is not None:
            filtered = [nid for nid in candidate_node_ids if nid in governance_allowed]
        else:
            filtered = list(candidate_node_ids)

        diag["post_governance_count"] = len(filtered)

        # Step 2: Apply soft budget narrowing
        if budget is None or not budget.influenced_by_budget:
            # No budget available — return governance-filtered candidates as-is
            diag["budget_narrowing_applied"] = False
            diag["narrowed_by"] = "none"
            diag["output_count"] = len(filtered)
            return filtered, diag

        max_candidates = budget.max_candidate_nodes

        if len(filtered) <= max_candidates:
            # Already within budget — no narrowing needed
            diag["budget_narrowing_applied"] = False
            diag["narrowed_by"] = "within_budget"
            diag["output_count"] = len(filtered)
            return filtered, diag

        # Apply soft narrowing: take the first N (preserving existing ordering
        # which is assumed to be by priority/relevance at the call site)
        narrowed = filtered[:max_candidates]
        diag["budget_narrowing_applied"] = True
        diag["narrowed_by"] = "activation_budget"
        diag["breadth_mode"] = budget.breadth_mode
        diag["budget_value"] = budget.budget_value
        diag["max_candidates"] = max_candidates
        diag["output_count"] = len(narrowed)

        logger.debug(
            "CognitiveActivationBudget.apply_candidate_narrowing: "
            "narrowed %d → %d (budget=%.3f breadth=%s trace_id=%s)",
            len(filtered),
            len(narrowed),
            budget.budget_value,
            budget.breadth_mode,
            trace_id,
        )
        return narrowed, diag

    except Exception as exc:
        logger.debug("apply_candidate_narrowing: error: %s", exc)
        diag["error"] = str(exc)
        diag["output_count"] = len(candidate_node_ids)
        return list(candidate_node_ids), diag


# ---------------------------------------------------------------------------
# Diagnostics helper
# ---------------------------------------------------------------------------


def build_budget_diagnostics(
    budget: Optional[ActivationBudget],
    guidance: Optional[PlannerBreadthGuidance] = None,
    *,
    influenced: bool = False,
    influence_source: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a diagnostics payload for embedding in response metadata.

    Parameters
    ----------
    budget:
        The :class:`ActivationBudget` that was active during execution.
    guidance:
        Optional :class:`PlannerBreadthGuidance` derived from the budget.
    influenced:
        Whether activation budget actually influenced the runtime behavior.
    influence_source:
        A short description of where the budget influence was applied, e.g.
        ``"planner_strategy"`` or ``"candidate_narrowing"``.
    trace_id:
        Optional correlation ID.

    Returns
    -------
    dict
        JSON-safe diagnostics dict.  Never raises.
    """
    try:
        diag: Dict[str, Any] = {
            "activation_budget_active": budget is not None and budget.influenced_by_budget,
            "budget_influenced_runtime": influenced,
            "influence_source": influence_source or "none",
            "trace_id": trace_id,
        }
        if budget is not None:
            diag["budget"] = budget.to_dict()
        if guidance is not None:
            diag["planner_breadth_guidance"] = guidance.to_dict()
        return diag
    except Exception as exc:
        logger.debug("build_budget_diagnostics: error: %s", exc)
        return {
            "activation_budget_active": False,
            "budget_influenced_runtime": False,
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_intensity(budget_value: float) -> str:
    """Classify a budget_value into a named intensity level."""
    if budget_value <= _THRESHOLD_LOW_MAX:
        return INTENSITY_LOW
    if budget_value <= _THRESHOLD_MODERATE_MAX:
        return INTENSITY_MODERATE
    return INTENSITY_HIGH


def _region_to_breadth_mode(region: str) -> str:
    """Map a cognitive region string to a breadth mode."""
    mapping = {
        "silent": BREADTH_MODE_NARROW,
        "passive": BREADTH_MODE_NARROW,
        "liminal": BREADTH_MODE_MODERATE,
        "manifest": BREADTH_MODE_BROAD,
    }
    return mapping.get(region, BREADTH_MODE_NARROW)


def _breadth_to_max_candidates(breadth_mode: str) -> int:
    """Return max candidate node count for a breadth mode."""
    mapping = {
        BREADTH_MODE_NARROW: _MAX_CANDIDATES_NARROW,
        BREADTH_MODE_MODERATE: _MAX_CANDIDATES_MODERATE,
        BREADTH_MODE_BROAD: _MAX_CANDIDATES_BROAD,
    }
    return mapping.get(breadth_mode, _MAX_CANDIDATES_NARROW)


def _breadth_to_max_agents(breadth_mode: str) -> int:
    """Return max concurrent agents for a breadth mode."""
    mapping = {
        BREADTH_MODE_NARROW: _MAX_AGENTS_NARROW,
        BREADTH_MODE_MODERATE: _MAX_AGENTS_MODERATE,
        BREADTH_MODE_BROAD: _MAX_AGENTS_BROAD,
    }
    return mapping.get(breadth_mode, _MAX_AGENTS_NARROW)


def _breadth_to_strategy_preference(breadth_mode: str) -> Optional[str]:
    """Return optional strategy preference for a breadth mode."""
    mapping: Dict[str, Optional[str]] = {
        BREADTH_MODE_NARROW: "single",
        BREADTH_MODE_MODERATE: None,
        BREADTH_MODE_BROAD: None,
    }
    return mapping.get(breadth_mode, "single")
