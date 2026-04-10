#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_decision_bias
=====================================

PR-19 — Memory-Informed Runtime Bias Layer

Canonical bounded memory-decision-bias layer.  Derives a
:class:`MemoryBias` representation from already-available
:class:`~core.task_memory.TaskMemory` signals and makes those signals
available as a **soft, advisory** runtime bias for:

- planner decomposition style (continuity-aware vs fresh vs recall-supported)
- node candidate preference / continuity-seeking activation
- continuity-vs-fresh handling heuristics
- optional model-selection posture hints

Design principles
-----------------
- **Consumes, does not re-compute**: All signals are read from the existing
  :class:`~core.task_memory.TaskMemory` instance.  This module never starts
  a second memory pipeline.
- **Hints, not commands**: The produced :class:`MemoryBias` is a *bounded,
  advisory influence object*.  It biases execution preferences; it never
  replaces core authority figures.
- **Hard gates remain authoritative**: invocation governance, activation
  readiness, explicit user intent, and lifecycle-denial decisions are
  **never** affected by memory bias.
- **Explicit postures**: The bias always exposes one of three canonical
  memory postures — ``continuity_seeking``, ``retrieval_seeking``, or
  ``novelty`` — so diagnostics are always clear and actionable.
- **Additive, backward-compatible**: all consumers fall back gracefully when
  memory bias is absent or the ``TaskMemory`` singleton is unavailable.

Memory posture definitions
--------------------------
continuity_seeking
    Strong prior task context is present and recent history is coherent /
    high-success.  Runtime should prefer continuity-aware handling: reuse
    session context, lean on prior results, avoid unnecessary re-discovery.

retrieval_seeking
    Prior context exists but success rate is low or drift signals suggest
    the task is changing.  Runtime should prefer recall-supported execution:
    surface prior attempts for review, lean towards more careful planning.

novelty
    Minimal or no prior task history, or history is dominated by distinct
    task types.  Runtime should prefer fresh handling: do not carry over
    assumptions from unrelated prior sessions.

Authority sentinels
-------------------
MEMORY_DECISION_BIAS_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_DECISION_BIAS_PR19_SENTINEL
    Machine-checkable sentinel confirming the memory-bias layer is present.

Usage::

    from core.cognitive.memory_decision_bias import (
        derive_memory_bias,
        get_planner_continuity_guidance,
        build_memory_bias_diagnostics,
        MemoryBias,
        PlannerContinuityGuidance,
        MEMORY_POSTURE_CONTINUITY,
        MEMORY_POSTURE_RETRIEVAL,
        MEMORY_POSTURE_NOVELTY,
    )

    bias = derive_memory_bias()
    guidance = get_planner_continuity_guidance(bias)
    print(guidance.continuity_style)   # "continuity" | "retrieval" | "fresh"
    diag = build_memory_bias_diagnostics(bias, influenced=True,
                                         influence_surface="planner_strategy")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.MemoryDecisionBias")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

MEMORY_DECISION_BIAS_IS_AUTHORITY: str = (
    "MEMORY_DECISION_BIAS::CANONICAL_AUTHORITY: "
    "core.cognitive.memory_decision_bias is the canonical memory-decision-bias "
    "layer for PR-19.  It translates TaskMemory signals into bounded MemoryBias "
    "and PlannerContinuityGuidance objects.  It does not replace lifecycle "
    "governance, invocation governance, activation readiness, or explicit user "
    "intent.  Memory bias is always advisory and subordinate to hard gates."
)

MEMORY_DECISION_BIAS_PR19_SENTINEL: str = (
    "MEMORY_DECISION_BIAS::PR19_SENTINEL: "
    "Memory-informed runtime bias (PR-19) is present and active.  "
    "MemoryBias is derived from TaskMemory signals and wired into "
    "ExecutionPlanner continuity guidance and kernel execution handling."
)

# Policy sentinels
HARD_GATES_UNAFFECTED_BY_MEMORY_BIAS_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_1: "
    "Hard gates (lifecycle governance, invocation governance, node activation "
    "readiness, explicit user intent) are ALWAYS authoritative and are NEVER "
    "modified or bypassed by MemoryBias.  Memory bias is a soft influence layer "
    "that operates above and alongside hard gates."
)

MEMORY_BIAS_IS_ADVISORY_ONLY_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_2: "
    "MemoryBias is a soft, advisory influence on continuity handling and planner "
    "decomposition style.  Consumers MUST NOT treat it as a hard routing gate.  "
    "A continuity_seeking posture does not mandate session reuse — it merely "
    "biases toward continuity-aware handling when safe to do so."
)

MEMORY_BIAS_DERIVED_FROM_TASK_MEMORY_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_3: "
    "MemoryBias is always derived from TaskMemory signals already present in "
    "the runtime.  No second memory pipeline is started; the bias re-uses the "
    "already-available singleton TaskMemory instance."
)

MEMORY_BIAS_EXPLICIT_USER_INTENT_TAKES_PRIORITY_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_4: "
    "Explicit user intent (task semantics, direct instructions) always takes "
    "priority over memory-derived posture.  Memory bias may softly shape how a "
    "request is handled, but it MUST NOT override what the user explicitly asked "
    "for or how the IntentRouter classified the request."
)


# ---------------------------------------------------------------------------
# Memory posture constants
# ---------------------------------------------------------------------------

MEMORY_POSTURE_CONTINUITY: str = "continuity_seeking"
"""Strong prior context; runtime should prefer continuity-aware handling."""

MEMORY_POSTURE_RETRIEVAL: str = "retrieval_seeking"
"""Prior context present but quality is low; prefer recall-supported execution."""

MEMORY_POSTURE_NOVELTY: str = "novelty"
"""Minimal or unrelated prior history; prefer fresh handling."""

# Continuity style labels used in PlannerContinuityGuidance
_CONTINUITY_STYLE_CONTINUITY: str = "continuity"
_CONTINUITY_STYLE_RETRIEVAL: str = "retrieval"
_CONTINUITY_STYLE_FRESH: str = "fresh"


# ---------------------------------------------------------------------------
# Thresholds for posture classification
# ---------------------------------------------------------------------------

# Minimum number of recent task summaries to consider continuity
_MIN_TASKS_FOR_CONTINUITY: int = 2
# Success rate threshold: above this → potentially continuity-seeking
_SUCCESS_RATE_CONTINUITY_THRESHOLD: float = 0.70
# Success rate threshold: below this → leaning toward retrieval-seeking
_SUCCESS_RATE_RETRIEVAL_THRESHOLD: float = 0.45
# Minimum distinct task types to declare "novelty" (diverse history = low continuity)
_DIVERSITY_NOVELTY_THRESHOLD: int = 4


# ---------------------------------------------------------------------------
# MemoryBias dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBias:
    """Bounded, advisory memory-decision bias derived from TaskMemory signals.

    This dataclass is the canonical output of :func:`derive_memory_bias`.
    All fields have safe defaults; consumers must never assume any field is
    non-None.

    Attributes
    ----------
    memory_posture:
        One of :data:`MEMORY_POSTURE_CONTINUITY`, :data:`MEMORY_POSTURE_RETRIEVAL`,
        or :data:`MEMORY_POSTURE_NOVELTY`.  This is the primary signal.
    continuity_score:
        Normalised [0.0, 1.0] score reflecting how strongly prior task context
        supports continuity-aware handling.  Higher = stronger continuity signal.
    retrieval_relevance:
        Normalised [0.0, 1.0] score reflecting how likely memory retrieval
        would benefit the current execution.  Higher = recall more likely useful.
    novelty_score:
        Normalised [0.0, 1.0] score reflecting the degree of novelty / lack of
        relevant prior context.  Higher = prefer fresh handling.
    recent_task_count:
        Number of recent task summaries available in TaskMemory.
    recent_success_rate:
        Success rate of recent tasks in [0.0, 1.0].  -1.0 when no data.
    influenced:
        True when this bias was derived from live TaskMemory signals.
        False for the fallback/novelty default.
    source:
        ``"task_memory"`` when derived from live signals; ``"fallback"`` otherwise.
    diagnostic_note:
        Human-readable note explaining the posture decision.
    timestamp:
        Unix epoch at bias derivation time.
    """

    memory_posture: str = MEMORY_POSTURE_NOVELTY
    continuity_score: float = 0.0
    retrieval_relevance: float = 0.0
    novelty_score: float = 1.0
    recent_task_count: int = 0
    recent_success_rate: float = -1.0
    influenced: bool = False
    source: str = "fallback"
    diagnostic_note: str = ""
    timestamp: float = field(default_factory=time.time)

    def is_continuity_seeking(self) -> bool:
        """Return True when memory posture is continuity-seeking."""
        return self.memory_posture == MEMORY_POSTURE_CONTINUITY

    def is_retrieval_seeking(self) -> bool:
        """Return True when memory posture is retrieval-seeking."""
        return self.memory_posture == MEMORY_POSTURE_RETRIEVAL

    def is_novelty(self) -> bool:
        """Return True when memory posture is novelty / low-memory-dependence."""
        return self.memory_posture == MEMORY_POSTURE_NOVELTY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "memory_posture": self.memory_posture,
            "continuity_score": round(self.continuity_score, 4),
            "retrieval_relevance": round(self.retrieval_relevance, 4),
            "novelty_score": round(self.novelty_score, 4),
            "recent_task_count": self.recent_task_count,
            "recent_success_rate": round(self.recent_success_rate, 4),
            "influenced": self.influenced,
            "source": self.source,
            "diagnostic_note": self.diagnostic_note,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Fallback bias (safe default when TaskMemory is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_MEMORY_BIAS: MemoryBias = MemoryBias(
    memory_posture=MEMORY_POSTURE_NOVELTY,
    continuity_score=0.0,
    retrieval_relevance=0.0,
    novelty_score=1.0,
    recent_task_count=0,
    recent_success_rate=-1.0,
    influenced=False,
    source="fallback",
    diagnostic_note="task_memory_unavailable: using novelty fallback",
)


# ---------------------------------------------------------------------------
# PlannerContinuityGuidance dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerContinuityGuidance:
    """Planner continuity guidance derived from a :class:`MemoryBias`.

    This dataclass is the canonical output of
    :func:`get_planner_continuity_guidance`.

    Attributes
    ----------
    continuity_style:
        Suggested handling style: ``"continuity"`` / ``"retrieval"`` / ``"fresh"``.
    prefer_prior_context:
        When True, the planner should lean on prior task context / session history
        where safe.
    prefer_recall_support:
        When True, the planner should surface prior attempts and prefer
        recall-supported decomposition.
    memory_posture:
        The :class:`MemoryBias` posture that produced this guidance.
    continuity_score:
        Carried from the source :class:`MemoryBias`.
    influenced_by_memory:
        True when guidance was derived from live memory signals.
    diagnostic_note:
        Human-readable note explaining the guidance decision.
    """

    continuity_style: str = _CONTINUITY_STYLE_FRESH
    prefer_prior_context: bool = False
    prefer_recall_support: bool = False
    memory_posture: str = MEMORY_POSTURE_NOVELTY
    continuity_score: float = 0.0
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "continuity_style": self.continuity_style,
            "prefer_prior_context": self.prefer_prior_context,
            "prefer_recall_support": self.prefer_recall_support,
            "memory_posture": self.memory_posture,
            "continuity_score": round(self.continuity_score, 4),
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Core derivation: TaskMemory signals → MemoryBias
# ---------------------------------------------------------------------------


def derive_memory_bias(
    task_memory: Optional[Any] = None,
    *,
    n_recent: int = 5,
    trace_id: Optional[str] = None,
) -> MemoryBias:
    """Derive a :class:`MemoryBias` from :class:`~core.task_memory.TaskMemory` signals.

    Parameters
    ----------
    task_memory:
        A :class:`~core.task_memory.TaskMemory` instance or ``None``.
        When ``None``, the module attempts to load the global singleton via
        ``core.task_memory.get_task_memory()``.  If that also fails,
        :data:`FALLBACK_MEMORY_BIAS` is returned.
    n_recent:
        Number of recent task summaries to sample when classifying posture.
        Defaults to 5.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryBias
        A bounded, advisory bias derived from available memory signals.
        Never raises — returns :data:`FALLBACK_MEMORY_BIAS` on any error.
    """
    try:
        return _derive_bias_impl(
            task_memory=task_memory,
            n_recent=n_recent,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.debug(
            "derive_memory_bias: error (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return FALLBACK_MEMORY_BIAS


def _derive_bias_impl(
    *,
    task_memory: Optional[Any],
    n_recent: int,
    trace_id: Optional[str],
) -> MemoryBias:
    """Internal implementation of memory bias derivation."""
    # Attempt to obtain a TaskMemory instance if not provided
    mem = task_memory
    if mem is None:
        try:
            from core.task_memory import get_task_memory as _get_tm
            mem = _get_tm()
        except Exception as import_err:
            logger.debug(
                "derive_memory_bias: TaskMemory unavailable (trace_id=%s): %s",
                trace_id,
                import_err,
            )
            return FALLBACK_MEMORY_BIAS

    # Retrieve recent summaries
    try:
        summaries: List[Any] = mem.get_recent_summaries(n=n_recent)
    except Exception as read_err:
        logger.debug(
            "derive_memory_bias: get_recent_summaries failed (trace_id=%s): %s",
            trace_id,
            read_err,
        )
        return FALLBACK_MEMORY_BIAS

    recent_count = len(summaries)

    if recent_count == 0:
        # No history at all → novelty
        return MemoryBias(
            memory_posture=MEMORY_POSTURE_NOVELTY,
            continuity_score=0.0,
            retrieval_relevance=0.0,
            novelty_score=1.0,
            recent_task_count=0,
            recent_success_rate=-1.0,
            influenced=True,
            source="task_memory",
            diagnostic_note="no_prior_history: novelty posture (fresh handling preferred)",
        )

    # Compute success rate
    successes = sum(1 for s in summaries if getattr(s, "success", True))
    success_rate = successes / recent_count

    # Compute task type diversity (distinct task_type values)
    task_types = {getattr(s, "task_type", "") for s in summaries if getattr(s, "task_type", "")}
    diversity = len(task_types)

    # Classify posture
    posture, continuity_score, retrieval_relevance, novelty_score, note = _classify_posture(
        recent_count=recent_count,
        success_rate=success_rate,
        diversity=diversity,
    )

    logger.debug(
        "MemoryDecisionBias: posture=%s continuity=%.3f retrieval=%.3f novelty=%.3f "
        "tasks=%d success_rate=%.3f diversity=%d trace_id=%s",
        posture,
        continuity_score,
        retrieval_relevance,
        novelty_score,
        recent_count,
        success_rate,
        diversity,
        trace_id,
    )

    return MemoryBias(
        memory_posture=posture,
        continuity_score=round(continuity_score, 4),
        retrieval_relevance=round(retrieval_relevance, 4),
        novelty_score=round(novelty_score, 4),
        recent_task_count=recent_count,
        recent_success_rate=round(success_rate, 4),
        influenced=True,
        source="task_memory",
        diagnostic_note=note,
    )


def _classify_posture(
    *,
    recent_count: int,
    success_rate: float,
    diversity: int,
) -> tuple:
    """Classify memory posture from summary signals.

    Returns
    -------
    tuple of (posture, continuity_score, retrieval_relevance, novelty_score, note)
    """
    # Not enough history for continuity
    if recent_count < _MIN_TASKS_FOR_CONTINUITY:
        note = (
            f"task_count={recent_count} (below min={_MIN_TASKS_FOR_CONTINUITY}): "
            "novelty posture (insufficient history)"
        )
        return (MEMORY_POSTURE_NOVELTY, 0.1, 0.2, 0.9, note)

    # High diversity → tasks are varied; continuity unlikely to help
    if diversity >= _DIVERSITY_NOVELTY_THRESHOLD:
        # But if success rate is low, retrieval is more useful than fresh start
        if success_rate < _SUCCESS_RATE_RETRIEVAL_THRESHOLD:
            note = (
                f"diversity={diversity} success_rate={success_rate:.2f}: "
                "retrieval_seeking posture (diverse history with low success)"
            )
            return (MEMORY_POSTURE_RETRIEVAL, 0.2, 0.7, 0.4, note)
        note = (
            f"diversity={diversity}: "
            "novelty posture (highly diverse task types — continuity unlikely)"
        )
        return (MEMORY_POSTURE_NOVELTY, 0.2, 0.3, 0.8, note)

    # Low success rate → retrieval-seeking
    if success_rate < _SUCCESS_RATE_RETRIEVAL_THRESHOLD:
        note = (
            f"success_rate={success_rate:.2f} (below retrieval threshold={_SUCCESS_RATE_RETRIEVAL_THRESHOLD}): "
            "retrieval_seeking posture (prior attempts need review)"
        )
        retrieval_rel = min(1.0, 0.5 + (1.0 - success_rate) * 0.5)
        continuity_sc = max(0.0, success_rate * 0.5)
        return (
            MEMORY_POSTURE_RETRIEVAL,
            round(continuity_sc, 4),
            round(retrieval_rel, 4),
            round(1.0 - retrieval_rel, 4),
            note,
        )

    # High success rate with enough history → continuity-seeking
    if success_rate >= _SUCCESS_RATE_CONTINUITY_THRESHOLD:
        note = (
            f"success_rate={success_rate:.2f} task_count={recent_count}: "
            "continuity_seeking posture (strong prior context supports continuity)"
        )
        continuity_sc = min(1.0, 0.5 + success_rate * 0.5)
        retrieval_rel = max(0.0, 1.0 - success_rate)
        return (
            MEMORY_POSTURE_CONTINUITY,
            round(continuity_sc, 4),
            round(retrieval_rel, 4),
            round(1.0 - continuity_sc, 4),
            note,
        )

    # Moderate success rate → moderate novelty (don't lean either way)
    note = (
        f"success_rate={success_rate:.2f} task_count={recent_count}: "
        "novelty posture (moderate history — fresh handling preferred)"
    )
    continuity_sc = success_rate * 0.5
    return (
        MEMORY_POSTURE_NOVELTY,
        round(continuity_sc, 4),
        0.3,
        round(1.0 - continuity_sc, 4),
        note,
    )


# ---------------------------------------------------------------------------
# PlannerContinuityGuidance derivation
# ---------------------------------------------------------------------------


def get_planner_continuity_guidance(
    bias: Optional[MemoryBias],
    *,
    trace_id: Optional[str] = None,
) -> PlannerContinuityGuidance:
    """Translate a :class:`MemoryBias` into :class:`PlannerContinuityGuidance`.

    Parameters
    ----------
    bias:
        A :class:`MemoryBias` or ``None``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    PlannerContinuityGuidance
        Advisory guidance for the planner.  Never raises.
    """
    try:
        if bias is None or not bias.influenced:
            return PlannerContinuityGuidance(
                continuity_style=_CONTINUITY_STYLE_FRESH,
                prefer_prior_context=False,
                prefer_recall_support=False,
                memory_posture=MEMORY_POSTURE_NOVELTY,
                continuity_score=0.0,
                influenced_by_memory=False,
                diagnostic_note="memory_bias_unavailable: using fresh fallback",
            )

        posture = bias.memory_posture

        if posture == MEMORY_POSTURE_CONTINUITY:
            note = (
                f"memory_posture=continuity_seeking "
                f"continuity_score={bias.continuity_score:.3f}: "
                "prefer continuity-aware handling — lean on prior context"
            )
            return PlannerContinuityGuidance(
                continuity_style=_CONTINUITY_STYLE_CONTINUITY,
                prefer_prior_context=True,
                prefer_recall_support=False,
                memory_posture=posture,
                continuity_score=bias.continuity_score,
                influenced_by_memory=True,
                diagnostic_note=note,
            )

        if posture == MEMORY_POSTURE_RETRIEVAL:
            note = (
                f"memory_posture=retrieval_seeking "
                f"retrieval_relevance={bias.retrieval_relevance:.3f}: "
                "prefer recall-supported handling — surface prior attempts"
            )
            return PlannerContinuityGuidance(
                continuity_style=_CONTINUITY_STYLE_RETRIEVAL,
                prefer_prior_context=False,
                prefer_recall_support=True,
                memory_posture=posture,
                continuity_score=bias.continuity_score,
                influenced_by_memory=True,
                diagnostic_note=note,
            )

        # NOVELTY
        note = (
            f"memory_posture=novelty "
            f"novelty_score={bias.novelty_score:.3f}: "
            "prefer fresh handling — avoid unnecessary continuity assumptions"
        )
        return PlannerContinuityGuidance(
            continuity_style=_CONTINUITY_STYLE_FRESH,
            prefer_prior_context=False,
            prefer_recall_support=False,
            memory_posture=posture,
            continuity_score=bias.continuity_score,
            influenced_by_memory=True,
            diagnostic_note=note,
        )

    except Exception as exc:
        logger.debug("get_planner_continuity_guidance: error: %s", exc)
        return PlannerContinuityGuidance(
            continuity_style=_CONTINUITY_STYLE_FRESH,
            prefer_prior_context=False,
            prefer_recall_support=False,
            memory_posture=MEMORY_POSTURE_NOVELTY,
            continuity_score=0.0,
            influenced_by_memory=False,
            diagnostic_note=f"error_fallback: {exc}",
        )


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def build_memory_bias_diagnostics(
    bias: Optional[MemoryBias],
    *,
    influenced: bool = False,
    influence_surface: str = "",
    hard_gate_overrode: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a JSON-safe diagnostics dict for a :class:`MemoryBias`.

    Parameters
    ----------
    bias:
        The :class:`MemoryBias` to describe.  If ``None``, a minimal
        no-data dict is returned.
    influenced:
        Whether memory bias actually changed a runtime decision.
    influence_surface:
        Label for the decision surface where bias was applied
        (e.g., ``"planner_strategy"``, ``"node_candidate_selection"``).
    hard_gate_overrode:
        Whether a hard governance/readiness gate overrode the memory bias
        influence for this turn.
    trace_id:
        Optional correlation ID.

    Returns
    -------
    dict
        Diagnostics dict suitable for inclusion in ``KernelResponse`` or
        execution result metadata.
    """
    if bias is None:
        return {
            "memory_posture": None,
            "influenced": False,
            "influence_surface": influence_surface,
            "hard_gate_overrode": hard_gate_overrode,
            "source": "none",
            "trace_id": trace_id,
        }

    return {
        "memory_posture": bias.memory_posture,
        "continuity_score": round(bias.continuity_score, 4),
        "retrieval_relevance": round(bias.retrieval_relevance, 4),
        "novelty_score": round(bias.novelty_score, 4),
        "recent_task_count": bias.recent_task_count,
        "recent_success_rate": (
            round(bias.recent_success_rate, 4)
            if bias.recent_success_rate >= 0 else None
        ),
        "influenced": influenced,
        "influence_surface": influence_surface,
        "hard_gate_overrode": hard_gate_overrode,
        "source": bias.source,
        "diagnostic_note": bias.diagnostic_note,
        "trace_id": trace_id,
    }
