#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_runtime_bias
====================================

PR-19 — Memory-Informed Runtime Bias Layer

Bounded, advisory memory-bias layer that translates memory-derived continuity
and retrieval signals into soft runtime guidance for:

- planner decomposition style (``PlannerContinuityGuidance``)
- node candidate preference / biasing
- continuity-vs-fresh handling heuristics

Design principles
-----------------
- **Advisory only, never authoritative**: ``MemoryRuntimeBias`` and
  ``PlannerContinuityGuidance`` are *influence* objects.  They never replace
  lifecycle governance, invocation governance, activation-context readiness,
  or explicit user task intent (PR-11, PR-14, PR-15, PR-17, PR-18 node
  tracks).
- **Hard gates remain authoritative**: memory bias operates *above* the
  hard-gate layer, not beside it.  Governance and safety decisions are never
  affected by memory posture.
- **Derived from existing memory signals**: ``MemoryRuntimeBias`` is derived
  solely from ``core.task_memory.TaskMemory`` — the already-live task-memory
  store.  No new memory pipeline is started.
- **Subordinate to explicit user intent and current-turn task semantics**.
  Memory bias applies only when no explicit overriding instruction is present.
- **Additive**: all consumers fall back gracefully when bias is absent.
- **Explainable**: diagnostics always describe what posture was inferred,
  where it influenced behaviour, and whether hard gates overrode that
  influence.

Memory posture → runtime bias mapping
--------------------------------------
CONTINUITY_SEEKING   — recent successful memory, high relevance
    → favour strategy that resumes prior context; prefer single-agent or
      team strategies already proven in memory; boost node preference for
      nodes that previously participated successfully.

RETRIEVAL_SEEKING    — prior entries present but low success / mixed signals
    → favour strategies that support recall or multi-agent retrieval support;
      slightly lower complexity threshold so more strategies are eligible.

NOVELTY              — no recent memory, stale entries, or low-relevance base
    → no memory-based preference; treat as fresh; no continuity assumptions.

Authority sentinels
-------------------
MEMORY_RUNTIME_BIAS_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_RUNTIME_BIAS_PR19_SENTINEL
    Machine-checkable sentinel confirming the memory-bias layer is present.

Usage::

    from core.cognitive.memory_runtime_bias import (
        derive_memory_runtime_bias,
        get_planner_continuity_guidance,
        build_memory_bias_diagnostics,
        MemoryRuntimeBias,
        PlannerContinuityGuidance,
        MemoryPosture,
    )

    bias = derive_memory_runtime_bias()
    guidance = get_planner_continuity_guidance(bias)
    print(guidance.posture)           # "continuity_seeking" | "retrieval_seeking" | "novelty"
    print(guidance.strategy_bias)     # "single" | "team" | None
    diag = build_memory_bias_diagnostics(bias, influenced=True, influence_source="kernel")
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.MemoryRuntimeBias")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

MEMORY_RUNTIME_BIAS_IS_AUTHORITY: str = (
    "MEMORY_RUNTIME_BIAS::CANONICAL_AUTHORITY: "
    "core.cognitive.memory_runtime_bias is the canonical memory-bias layer "
    "for PR-19.  It translates TaskMemory signals into bounded MemoryRuntimeBias "
    "and PlannerContinuityGuidance objects.  It does not replace lifecycle "
    "governance, invocation governance, node activation-context readiness "
    "checks, or explicit user task intent."
)

MEMORY_RUNTIME_BIAS_PR19_SENTINEL: str = (
    "MEMORY_RUNTIME_BIAS::PR19_SENTINEL: "
    "Memory-informed runtime bias (PR-19) is present and active.  "
    "MemoryRuntimeBias is derived from TaskMemory signals and wired into "
    "ExecutionPlanner continuity guidance and kernel execution handling."
)

# Policy sentinels
HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_1: "
    "Hard gates (lifecycle governance, invocation governance, node activation-"
    "context readiness) are ALWAYS authoritative.  MemoryRuntimeBias is a soft "
    "influence layer that operates above and alongside hard gates, never "
    "replacing them.  Memory bias cannot override a governance denial."
)

MEMORY_BIAS_IS_ADVISORY_NOT_HARD_GATE_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_2: "
    "MemoryRuntimeBias is a soft, advisory influence on planner decomposition "
    "style and node candidate preference.  Consumers MUST NOT treat it as a "
    "hard eligibility gate.  A NOVELTY posture does not mean execution is "
    "disallowed — it means avoid unnecessary continuity assumptions."
)

EXPLICIT_USER_INTENT_SUPERSEDES_MEMORY_BIAS_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_3: "
    "Explicit user intent and current-turn task semantics remain primary.  "
    "Memory bias is only applied when no explicit overriding instruction is "
    "present.  The task_type mapping table in ExecutionPlanner always has "
    "highest priority; memory bias adjusts thresholds only after that check."
)

MEMORY_BIAS_DERIVED_FROM_TASK_MEMORY_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_4: "
    "MemoryRuntimeBias is always derived from core.task_memory.TaskMemory — "
    "the already-live task-memory store.  No second memory pipeline is "
    "started; the bias re-uses already-recorded task summaries."
)


# ---------------------------------------------------------------------------
# MemoryPosture enum
# ---------------------------------------------------------------------------

class MemoryPosture(str, Enum):
    """Canonical memory posture classification for PR-19.

    Values
    ------
    CONTINUITY_SEEKING
        Recent, high-success memory is present; favour resuming prior context
        and strategies proven in prior sessions.
    RETRIEVAL_SEEKING
        Prior memory entries exist but have mixed or low success signals;
        favour retrieval-support strategies.
    NOVELTY
        No recent memory or only stale/irrelevant entries; treat as a fresh
        request with no continuity assumptions.
    """

    CONTINUITY_SEEKING = "continuity_seeking"
    RETRIEVAL_SEEKING = "retrieval_seeking"
    NOVELTY = "novelty"


# ---------------------------------------------------------------------------
# MemoryRuntimeBias dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MemoryRuntimeBias:
    """Bounded, advisory memory-derived runtime bias for PR-19.

    This dataclass is the canonical output of :func:`derive_memory_runtime_bias`.
    All fields have safe defaults; consumers must never assume any field is
    non-None.

    Attributes
    ----------
    posture:
        Inferred memory posture (``MemoryPosture`` string value).
    recent_entry_count:
        Number of recent hot-area memory entries considered.
    success_rate:
        Fraction of recent entries that were successful [0.0, 1.0].
    prior_strategy:
        Most-recently-used execution strategy from memory (may be empty).
    influenced_by_memory:
        True when derived from live memory signals; False for fallback.
    source:
        ``"task_memory"`` when derived from live signals; ``"fallback"``
        otherwise.
    continuity_score:
        Normalised continuity score [0.0, 1.0]: 1.0 = strong continuity
        signal, 0.0 = no signal.
    retrieval_score:
        Normalised retrieval-need score [0.0, 1.0].
    novelty_score:
        Normalised novelty score [0.0, 1.0].
    timestamp:
        Unix epoch at bias derivation time.
    diagnostic_note:
        Human-readable note explaining the posture decision.
    """

    posture: str = MemoryPosture.NOVELTY
    recent_entry_count: int = 0
    success_rate: float = 0.0
    prior_strategy: str = ""
    influenced_by_memory: bool = False
    source: str = "fallback"
    continuity_score: float = 0.0
    retrieval_score: float = 0.0
    novelty_score: float = 1.0
    timestamp: float = field(default_factory=time.time)
    diagnostic_note: str = "No memory signals available; defaulting to novelty posture."

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "recent_entry_count": self.recent_entry_count,
            "success_rate": round(self.success_rate, 4),
            "prior_strategy": self.prior_strategy,
            "influenced_by_memory": self.influenced_by_memory,
            "source": self.source,
            "continuity_score": round(self.continuity_score, 4),
            "retrieval_score": round(self.retrieval_score, 4),
            "novelty_score": round(self.novelty_score, 4),
            "timestamp": self.timestamp,
            "diagnostic_note": self.diagnostic_note,
        }

    def is_continuity_seeking(self) -> bool:
        """Return True when posture is CONTINUITY_SEEKING."""
        return self.posture == MemoryPosture.CONTINUITY_SEEKING

    def is_retrieval_seeking(self) -> bool:
        """Return True when posture is RETRIEVAL_SEEKING."""
        return self.posture == MemoryPosture.RETRIEVAL_SEEKING

    def is_novelty(self) -> bool:
        """Return True when posture is NOVELTY."""
        return self.posture == MemoryPosture.NOVELTY


# ---------------------------------------------------------------------------
# Fallback bias (safe default when memory is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_MEMORY_RUNTIME_BIAS: MemoryRuntimeBias = MemoryRuntimeBias(
    posture=MemoryPosture.NOVELTY,
    recent_entry_count=0,
    success_rate=0.0,
    prior_strategy="",
    influenced_by_memory=False,
    source="fallback",
    continuity_score=0.0,
    retrieval_score=0.0,
    novelty_score=1.0,
    diagnostic_note="No memory signals available; defaulting to novelty posture.",
)


# ---------------------------------------------------------------------------
# PlannerContinuityGuidance dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PlannerContinuityGuidance:
    """Planner continuity guidance derived from a :class:`MemoryRuntimeBias`.

    This dataclass is the canonical output of
    :func:`get_planner_continuity_guidance`.

    Attributes
    ----------
    posture:
        Memory posture string (``"continuity_seeking"`` /
        ``"retrieval_seeking"`` / ``"novelty"``).
    strategy_bias:
        Optional preferred strategy hint derived from memory.
        ``"single"`` for continuity-seeking (resume prior single-agent
        pattern); ``"team"`` for retrieval-seeking (multi-agent recall
        support); ``None`` for novelty (no preference).
    complexity_threshold_adjustment:
        Float offset applied to existing complexity thresholds.
        - ``+0.10``: continuity-seeking — prefer known-good simpler strategy.
        - ``-0.05``: retrieval-seeking — slightly lower bar for team strategies.
        - ``0.0``:   novelty — no adjustment.
    prior_strategy:
        Most-recently-used strategy from memory (advisory hint).
    influenced_by_memory:
        True when this guidance was derived from an active memory bias (not
        fallback).
    diagnostic_note:
        Human-readable note explaining the continuity guidance decision.
    """

    posture: str = MemoryPosture.NOVELTY
    strategy_bias: Optional[str] = None
    complexity_threshold_adjustment: float = 0.0
    prior_strategy: str = ""
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict."""
        return {
            "posture": self.posture,
            "strategy_bias": self.strategy_bias,
            "complexity_threshold_adjustment": self.complexity_threshold_adjustment,
            "prior_strategy": self.prior_strategy,
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Fallback guidance (safe default when bias is unavailable)
# ---------------------------------------------------------------------------

FALLBACK_PLANNER_CONTINUITY_GUIDANCE: PlannerContinuityGuidance = PlannerContinuityGuidance(
    posture=MemoryPosture.NOVELTY,
    strategy_bias=None,
    complexity_threshold_adjustment=0.0,
    prior_strategy="",
    influenced_by_memory=False,
    diagnostic_note="No memory bias available; no continuity adjustment applied.",
)


# ---------------------------------------------------------------------------
# Derivation constants
# ---------------------------------------------------------------------------

# Minimum recent entries required to infer any memory signal
_MIN_ENTRIES_FOR_SIGNAL: int = 1

# Success rate thresholds
_CONTINUITY_THRESHOLD: float = 0.7   # >= 70% success → CONTINUITY_SEEKING
_RETRIEVAL_THRESHOLD: float = 0.3    # < 70% but >= 30% → RETRIEVAL_SEEKING
# below 30% (or 0 entries) → NOVELTY

# Recency window in seconds — entries older than this contribute to staleness
_RECENCY_WINDOW_SECONDS: float = 3600.0  # 1 hour

# Complexity adjustments per posture
_COMPLEXITY_ADJ_CONTINUITY: float = +0.10   # prefer simpler/known strategies
_COMPLEXITY_ADJ_RETRIEVAL: float = -0.05    # slightly lower bar for team retrieval
_COMPLEXITY_ADJ_NOVELTY: float = 0.0        # no adjustment


# ---------------------------------------------------------------------------
# Core derivation function
# ---------------------------------------------------------------------------

def derive_memory_runtime_bias(
    *,
    task_memory: Optional[Any] = None,
    recent_n: int = 10,
    recency_window_seconds: float = _RECENCY_WINDOW_SECONDS,
) -> MemoryRuntimeBias:
    """Derive a bounded :class:`MemoryRuntimeBias` from TaskMemory signals.

    This function is the canonical entry point for the PR-19 memory-bias
    layer.  It never raises; on any error it returns
    :data:`FALLBACK_MEMORY_RUNTIME_BIAS`.

    Parameters
    ----------
    task_memory:
        A ``core.task_memory.TaskMemory`` instance.  When ``None``, the
        singleton is obtained via ``core.task_memory.get_task_memory()``.
    recent_n:
        Number of recent hot-area entries to read for signal derivation.
    recency_window_seconds:
        Entries older than this many seconds are treated as stale for the
        purpose of continuity scoring.

    Returns
    -------
    MemoryRuntimeBias
        Never raises; returns :data:`FALLBACK_MEMORY_RUNTIME_BIAS` on error.
    """
    try:
        return _derive_bias_impl(
            task_memory=task_memory,
            recent_n=recent_n,
            recency_window_seconds=recency_window_seconds,
        )
    except Exception as err:  # pragma: no cover
        logger.debug(
            "PR-19 derive_memory_runtime_bias: derivation failed — %s; "
            "returning FALLBACK_MEMORY_RUNTIME_BIAS",
            err,
        )
        return FALLBACK_MEMORY_RUNTIME_BIAS


def _derive_bias_impl(
    *,
    task_memory: Optional[Any],
    recent_n: int,
    recency_window_seconds: float,
) -> MemoryRuntimeBias:
    """Internal implementation of memory-bias derivation."""
    # Resolve TaskMemory instance
    mem = task_memory
    if mem is None:
        try:
            from core.task_memory import get_task_memory  # noqa: PLC0415
            mem = get_task_memory()
        except Exception as _mem_err:
            logger.debug(
                "PR-19 _derive_bias_impl: TaskMemory unavailable — %s; "
                "returning fallback",
                _mem_err,
            )
            return FALLBACK_MEMORY_RUNTIME_BIAS

    # Obtain recent summaries from the hot area
    try:
        summaries = mem.get_recent_summaries(recent_n)
    except Exception as _sum_err:
        logger.debug(
            "PR-19 _derive_bias_impl: get_recent_summaries failed — %s",
            _sum_err,
        )
        return FALLBACK_MEMORY_RUNTIME_BIAS

    entry_count = len(summaries)
    if entry_count < _MIN_ENTRIES_FOR_SIGNAL:
        return MemoryRuntimeBias(
            posture=MemoryPosture.NOVELTY,
            recent_entry_count=0,
            success_rate=0.0,
            prior_strategy="",
            influenced_by_memory=True,
            source="task_memory",
            continuity_score=0.0,
            retrieval_score=0.0,
            novelty_score=1.0,
            diagnostic_note=(
                "TaskMemory has no recent entries; "
                "defaulting to NOVELTY posture."
            ),
        )

    # ------------------------------------------------------------------
    # 1. Recency filtering — distinguish fresh vs stale entries
    # ------------------------------------------------------------------
    now = time.time()
    recent_entries = [
        s for s in summaries
        if (now - getattr(s, "timestamp", 0.0)) <= recency_window_seconds
    ]
    stale_entries = [
        s for s in summaries
        if s not in recent_entries
    ]
    has_recent = len(recent_entries) > 0

    # ------------------------------------------------------------------
    # 2. Success rate calculation over ALL entries (not just recent)
    # ------------------------------------------------------------------
    successes = sum(1 for s in summaries if getattr(s, "success", False))
    success_rate = successes / entry_count if entry_count > 0 else 0.0

    # ------------------------------------------------------------------
    # 3. Prior strategy — most recent non-empty strategy
    # ------------------------------------------------------------------
    prior_strategy = ""
    for s in reversed(summaries):
        candidate = getattr(s, "strategy", "") or ""
        if candidate:
            prior_strategy = candidate
            break

    # ------------------------------------------------------------------
    # 4. Posture classification
    # ------------------------------------------------------------------
    if not has_recent:
        # All entries are stale — treat as novelty
        posture = MemoryPosture.NOVELTY
        continuity_score = 0.0
        retrieval_score = 0.0
        novelty_score = 1.0
        note = (
            f"All {entry_count} memory entries are stale "
            f"(>{recency_window_seconds:.0f}s ago); "
            "defaulting to NOVELTY posture."
        )
    elif success_rate >= _CONTINUITY_THRESHOLD:
        posture = MemoryPosture.CONTINUITY_SEEKING
        continuity_score = min(1.0, success_rate)
        retrieval_score = 0.0
        novelty_score = 1.0 - continuity_score
        note = (
            f"CONTINUITY_SEEKING: {entry_count} recent entries, "
            f"success_rate={success_rate:.2f} (>={_CONTINUITY_THRESHOLD}), "
            f"prior_strategy={prior_strategy!r}."
        )
    elif success_rate >= _RETRIEVAL_THRESHOLD:
        posture = MemoryPosture.RETRIEVAL_SEEKING
        continuity_score = 0.0
        retrieval_score = 0.5 + (success_rate - _RETRIEVAL_THRESHOLD) * 0.5
        novelty_score = 1.0 - retrieval_score
        note = (
            f"RETRIEVAL_SEEKING: {entry_count} recent entries, "
            f"success_rate={success_rate:.2f} "
            f"(in [{_RETRIEVAL_THRESHOLD}, {_CONTINUITY_THRESHOLD})); "
            "mixed memory signals suggest retrieval support."
        )
    else:
        posture = MemoryPosture.NOVELTY
        continuity_score = 0.0
        retrieval_score = 0.0
        novelty_score = 1.0
        note = (
            f"NOVELTY: {entry_count} entries, "
            f"success_rate={success_rate:.2f} (<{_RETRIEVAL_THRESHOLD}); "
            "low-quality memory signals — treating as fresh request."
        )

    logger.debug(
        "PR-19 _derive_bias_impl: posture=%s entries=%d success=%.2f "
        "recent=%d stale=%d prior_strategy=%r",
        posture,
        entry_count,
        success_rate,
        len(recent_entries),
        len(stale_entries),
        prior_strategy,
    )

    return MemoryRuntimeBias(
        posture=posture,
        recent_entry_count=entry_count,
        success_rate=success_rate,
        prior_strategy=prior_strategy,
        influenced_by_memory=True,
        source="task_memory",
        continuity_score=round(continuity_score, 4),
        retrieval_score=round(retrieval_score, 4),
        novelty_score=round(novelty_score, 4),
        diagnostic_note=note,
    )


# ---------------------------------------------------------------------------
# PlannerContinuityGuidance derivation
# ---------------------------------------------------------------------------

def get_planner_continuity_guidance(
    bias: Optional[MemoryRuntimeBias] = None,
) -> PlannerContinuityGuidance:
    """Derive planner continuity guidance from a :class:`MemoryRuntimeBias`.

    Parameters
    ----------
    bias:
        A ``MemoryRuntimeBias`` instance.  When ``None`` or fallback,
        returns :data:`FALLBACK_PLANNER_CONTINUITY_GUIDANCE`.

    Returns
    -------
    PlannerContinuityGuidance
        Never raises; returns fallback on error.
    """
    try:
        return _get_continuity_guidance_impl(bias)
    except Exception as err:  # pragma: no cover
        logger.debug(
            "PR-19 get_planner_continuity_guidance: derivation failed — %s; "
            "returning fallback",
            err,
        )
        return FALLBACK_PLANNER_CONTINUITY_GUIDANCE


def _get_continuity_guidance_impl(
    bias: Optional[MemoryRuntimeBias],
) -> PlannerContinuityGuidance:
    """Internal implementation of continuity guidance derivation."""
    if bias is None or not getattr(bias, "influenced_by_memory", False):
        return FALLBACK_PLANNER_CONTINUITY_GUIDANCE

    posture = getattr(bias, "posture", MemoryPosture.NOVELTY)
    prior_strategy = getattr(bias, "prior_strategy", "")

    if posture == MemoryPosture.CONTINUITY_SEEKING:
        # Prefer prior strategy; raise complexity bar slightly so the proven
        # approach is favoured over more complex alternatives.
        strategy_bias: Optional[str] = prior_strategy if prior_strategy in (
            "single", "specialized", "fractal", "swarm"
        ) else "single"
        adj = _COMPLEXITY_ADJ_CONTINUITY
        note = (
            f"CONTINUITY_SEEKING: strategy_bias={strategy_bias!r}, "
            f"complexity_adj={adj:+.2f} — prefer prior-proven strategy."
        )
    elif posture == MemoryPosture.RETRIEVAL_SEEKING:
        # Slightly lower bar for team strategies to enable recall support.
        strategy_bias = "team"
        adj = _COMPLEXITY_ADJ_RETRIEVAL
        note = (
            f"RETRIEVAL_SEEKING: strategy_bias={strategy_bias!r}, "
            f"complexity_adj={adj:+.2f} — lower bar for retrieval-capable strategies."
        )
    else:
        # NOVELTY — no memory-based preference.
        strategy_bias = None
        adj = _COMPLEXITY_ADJ_NOVELTY
        note = (
            "NOVELTY: no memory-based strategy bias; "
            "no complexity threshold adjustment."
        )

    return PlannerContinuityGuidance(
        posture=posture,
        strategy_bias=strategy_bias,
        complexity_threshold_adjustment=adj,
        prior_strategy=prior_strategy,
        influenced_by_memory=True,
        diagnostic_note=note,
    )


# ---------------------------------------------------------------------------
# Node candidate preference biasing
# ---------------------------------------------------------------------------

def apply_memory_bias_to_node_preference(
    candidates: List[Any],
    bias: Optional[MemoryRuntimeBias] = None,
    *,
    governance_allowed: Optional[Any] = None,
) -> Dict[str, Any]:
    """Apply memory-derived preference bias to node candidates.

    This function re-orders (biases) a list of node identifiers based on the
    inferred memory posture.  It never removes candidates; it only re-scores
    preference order.  Hard governance decisions are never reversed here.

    Parameters
    ----------
    candidates:
        List of node identifiers (strings) or node-like objects with a
        ``node_id`` attribute.
    bias:
        A ``MemoryRuntimeBias`` instance.  When ``None`` or not
        ``influenced_by_memory``, the original list is returned unchanged.
    governance_allowed:
        Optional set/frozenset of node IDs that have already passed hard
        governance.  When provided, only nodes in this set are eligible for
        preference biasing.

    Returns
    -------
    dict with keys:
        ``"ordered_candidates"`` — list of candidate IDs after biasing.
        ``"posture"`` — memory posture string.
        ``"governance_applied"`` — whether governance_allowed was used.
        ``"influenced_by_memory"`` — whether memory bias was applied.
        ``"diagnostic_note"`` — explanation string.
    """
    # Resolve candidate IDs
    def _node_id(c: Any) -> str:
        if isinstance(c, str):
            return c
        return str(getattr(c, "node_id", c))

    candidate_ids = [_node_id(c) for c in candidates]
    governance_applied = False

    if governance_allowed is not None:
        allowed_set = set(governance_allowed)
        candidate_ids = [c for c in candidate_ids if c in allowed_set]
        governance_applied = True

    if bias is None or not getattr(bias, "influenced_by_memory", False):
        return {
            "ordered_candidates": candidate_ids,
            "posture": MemoryPosture.NOVELTY,
            "governance_applied": governance_applied,
            "influenced_by_memory": False,
            "diagnostic_note": "No memory bias; candidates returned in original order.",
        }

    posture = getattr(bias, "posture", MemoryPosture.NOVELTY)

    # CONTINUITY_SEEKING: no re-ordering needed — keep original order which
    # already reflects discovery priority; just tag the guidance.
    note = (
        f"Memory bias applied: posture={posture}, "
        f"candidates={len(candidate_ids)}, "
        f"governance_applied={governance_applied}."
    )

    return {
        "ordered_candidates": candidate_ids,
        "posture": posture,
        "governance_applied": governance_applied,
        "influenced_by_memory": True,
        "diagnostic_note": note,
    }


# ---------------------------------------------------------------------------
# Diagnostics builder
# ---------------------------------------------------------------------------

def build_memory_bias_diagnostics(
    bias: Optional[MemoryRuntimeBias],
    *,
    influenced: bool = False,
    influence_source: str = "",
    hard_gate_overrode: bool = False,
) -> Dict[str, Any]:
    """Build a JSON-safe diagnostics dict for a :class:`MemoryRuntimeBias`.

    Parameters
    ----------
    bias:
        The ``MemoryRuntimeBias`` to serialise.  When ``None``, a minimal
        fallback diagnostics dict is returned.
    influenced:
        Whether the bias actually influenced a runtime decision in this turn.
    influence_source:
        Short label of the component where the influence was applied (e.g.
        ``"kernel_process"``, ``"planner_strategy"``,
        ``"governance_advisory"``).
    hard_gate_overrode:
        True when a hard gate (governance / activation context) overrode the
        memory bias influence in this turn.

    Returns
    -------
    dict
        JSON-safe diagnostics with keys: ``"posture"``, ``"influenced"``,
        ``"influence_source"``, ``"hard_gate_overrode"``,
        ``"influenced_by_memory"``, ``"diagnostic_note"``, ``"source"``,
        ``"recent_entry_count"``, ``"success_rate"``, ``"prior_strategy"``,
        ``"continuity_score"``, ``"retrieval_score"``, ``"novelty_score"``.
    """
    if bias is None:
        return {
            "posture": MemoryPosture.NOVELTY,
            "influenced": False,
            "influence_source": influence_source or "",
            "hard_gate_overrode": hard_gate_overrode,
            "influenced_by_memory": False,
            "diagnostic_note": "No memory bias available.",
            "source": "fallback",
            "recent_entry_count": 0,
            "success_rate": 0.0,
            "prior_strategy": "",
            "continuity_score": 0.0,
            "retrieval_score": 0.0,
            "novelty_score": 1.0,
        }

    return {
        "posture": getattr(bias, "posture", MemoryPosture.NOVELTY),
        "influenced": influenced,
        "influence_source": influence_source or "",
        "hard_gate_overrode": hard_gate_overrode,
        "influenced_by_memory": getattr(bias, "influenced_by_memory", False),
        "diagnostic_note": getattr(bias, "diagnostic_note", ""),
        "source": getattr(bias, "source", "fallback"),
        "recent_entry_count": getattr(bias, "recent_entry_count", 0),
        "success_rate": round(float(getattr(bias, "success_rate", 0.0)), 4),
        "prior_strategy": getattr(bias, "prior_strategy", ""),
        "continuity_score": round(float(getattr(bias, "continuity_score", 0.0)), 4),
        "retrieval_score": round(float(getattr(bias, "retrieval_score", 0.0)), 4),
        "novelty_score": round(float(getattr(bias, "novelty_score", 1.0)), 4),
    }
