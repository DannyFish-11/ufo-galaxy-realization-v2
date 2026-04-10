#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_decision_bias
====================================

PR-19 — Memory-Informed Runtime Bias Layer

Canonical bounded memory-bias layer.  Derives memory posture signals from
already-available :class:`~core.task_memory.TaskMemory` records and translates
them into advisory :class:`MemoryDecisionBias` and :class:`MemoryBiasGuidance`
objects that can softly influence planner decomposition style, context
injection depth, and execution continuity preferences.

Design principles
-----------------
- **Advisory only**: :class:`MemoryDecisionBias` and :class:`MemoryBiasGuidance`
  are *hints*, not commands.  They never replace lifecycle governance, invocation
  governance, node activation-context readiness (PR-11, PR-14, PR-15), or
  cognitive activation budgeting (PR-18).
- **Subordinate to explicit user intent**: memory posture can only *softly bias*
  runtime behavior when explicit task semantics and hard gates leave room for it.
- **Consumes, does not re-invent**: all signals are read from the existing
  :class:`~core.task_memory.TaskMemory` instance.  No new memory pipeline is
  introduced.
- **Explainable and bounded**: every :class:`MemoryDecisionBias` instance carries
  a ``diagnostic_note`` and a ``memory_posture`` field that explain the decision.
- **Graceful degradation**: every public function returns a safe fallback value
  on import failure or exception.

Memory posture taxonomy
-----------------------
CONTINUITY_SEEKING
    Recent context is substantial and successful.  Runtime behavior should
    prefer continuing from the prior context rather than starting fresh.  The
    planner injects more historical context, and execution prefers strategies
    seen to work in prior turns.

RETRIEVAL_SEEKING
    Memory records exist but continuity is uncertain.  Runtime behavior should
    be biased toward recall-supported execution: inject available context,
    prefer strategies that can leverage prior results.

NOVELTY
    Memory is absent, sparse, or predominantly failed.  Runtime behavior should
    default to fresh handling without continuity assumptions.

Authority sentinels
-------------------
MEMORY_DECISION_BIAS_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_DECISION_BIAS_PR19_SENTINEL
    Machine-checkable sentinel confirming the memory-bias layer is present.

Usage::

    from core.cognitive.memory_decision_bias import (
        derive_memory_bias,
        get_memory_bias_guidance,
        build_memory_bias_diagnostics,
        MemoryDecisionBias,
        MemoryBiasGuidance,
        MemoryPosture,
    )

    bias = derive_memory_bias(session_id="sess_abc")
    guidance = get_memory_bias_guidance(bias)
    print(guidance.posture_label)        # "continuity_seeking" | "retrieval_seeking" | "novelty"
    print(guidance.context_injection_n)  # how many memory records to inject
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.MemoryDecisionBias")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

MEMORY_DECISION_BIAS_IS_AUTHORITY: str = (
    "MEMORY_DECISION_BIAS::CANONICAL_AUTHORITY: "
    "core.cognitive.memory_decision_bias is the canonical memory-informed "
    "runtime bias layer for PR-19.  It translates TaskMemory signals into "
    "bounded MemoryDecisionBias and MemoryBiasGuidance objects.  It does not "
    "replace lifecycle governance, invocation governance, node activation-context "
    "readiness, or cognitive activation budgeting (PR-18).  Memory bias is "
    "advisory and subordinate to explicit user intent and hard governance gates."
)

MEMORY_DECISION_BIAS_PR19_SENTINEL: str = (
    "MEMORY_DECISION_BIAS::PR19_SENTINEL: "
    "Memory-informed runtime bias (PR-19) is present and active.  "
    "MemoryDecisionBias is derived from TaskMemory signals and wired into "
    "ExecutionPlanner context injection and planner strategy guidance.  "
    "KernelResponse carries memory_bias_hint for downstream diagnostics."
)

# Policy sentinels
MEMORY_BIAS_SUBORDINATE_TO_GOVERNANCE_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_1: "
    "MemoryDecisionBias is ALWAYS subordinate to hard governance gates "
    "(lifecycle governance, invocation governance, node activation-context "
    "readiness).  Memory posture cannot override any hard gate decision.  "
    "A posture of CONTINUITY_SEEKING does not guarantee continuity will be used."
)

MEMORY_BIAS_SUBORDINATE_TO_EXPLICIT_INTENT_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_2: "
    "Explicit user intent and current-turn task semantics remain primary.  "
    "MemoryDecisionBias is a soft hint that may be overridden by the user's "
    "explicit request or by other runtime policy layers."
)

MEMORY_BIAS_DERIVED_FROM_TASK_MEMORY_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_3: "
    "MemoryDecisionBias is always derived from the already-available "
    "core.task_memory.TaskMemory instance.  No new memory subsystem is "
    "introduced; the bias layer re-uses existing memory signals only."
)

MEMORY_BIAS_EXPLAINABLE_AND_BOUNDED_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_4: "
    "Every MemoryDecisionBias instance carries a diagnostic_note and a "
    "memory_posture field that explain the inferred posture and the signals "
    "that produced it.  Diagnostics must clearly show whether memory influenced "
    "runtime behavior and whether any hard gate overrode that influence."
)


# ---------------------------------------------------------------------------
# MemoryPosture enum
# ---------------------------------------------------------------------------


class MemoryPosture(str, Enum):
    """Canonical memory posture taxonomy for PR-19.

    Values
    ------
    CONTINUITY_SEEKING
        Recent memory is rich and successful; prefer continuity-aware handling.
    RETRIEVAL_SEEKING
        Memory exists but continuity is uncertain; prefer recall-supported execution.
    NOVELTY
        Memory is absent, sparse, or predominantly failed; prefer fresh handling.
    """

    CONTINUITY_SEEKING = "continuity_seeking"
    RETRIEVAL_SEEKING = "retrieval_seeking"
    NOVELTY = "novelty"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Minimum recent task count to consider continuity-seeking posture
_CONTINUITY_MIN_TASKS: int = 2
# Minimum success rate to consider continuity-seeking (0.0–1.0)
_CONTINUITY_MIN_SUCCESS_RATE: float = 0.6
# Minimum recent task count to consider retrieval-seeking posture
_RETRIEVAL_MIN_TASKS: int = 1
# Maximum recency age (seconds) for retrieval-seeking (5 minutes)
_RETRIEVAL_MAX_AGE_SECONDS: float = 300.0
# Context injection counts per posture
_CONTEXT_INJECTION_CONTINUITY: int = 5
_CONTEXT_INJECTION_RETRIEVAL: int = 3
_CONTEXT_INJECTION_NOVELTY: int = 0


# ---------------------------------------------------------------------------
# MemoryDecisionBias dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryDecisionBias:
    """Bounded, advisory memory decision bias derived from TaskMemory signals.

    This dataclass is the canonical output of :func:`derive_memory_bias`.
    All fields have safe defaults; consumers must never assume any field is
    non-None.

    Attributes
    ----------
    posture:
        The inferred :class:`MemoryPosture`.
    memory_posture:
        String label for the posture (matches ``posture.value``).
    continuity_score:
        Normalised continuity signal strength [0.0, 1.0].  High means strong
        prior context is available.
    retrieval_relevance:
        Normalised retrieval-readiness signal [0.0, 1.0].  High means memory
        records are available and may support recall-based execution.
    novelty_score:
        Normalised novelty signal [0.0, 1.0].  High means little or no prior
        context; fresh handling is appropriate.
    recent_task_count:
        Number of recent tasks available in hot-zone memory.
    recent_success_rate:
        Success rate of recent tasks [0.0, 1.0].
    influenced_by_memory:
        True when derived from live TaskMemory signals; False for fallback.
    source:
        ``"memory_decision_bias"`` for live derivations; ``"fallback"`` otherwise.
    diagnostic_note:
        Human-readable description of the posture decision and signals used.
    timestamp:
        Unix epoch at bias derivation time.
    """

    posture: MemoryPosture = MemoryPosture.NOVELTY
    memory_posture: str = MemoryPosture.NOVELTY.value
    continuity_score: float = 0.0
    retrieval_relevance: float = 0.0
    novelty_score: float = 1.0
    recent_task_count: int = 0
    recent_success_rate: float = 0.0
    influenced_by_memory: bool = False
    source: str = "fallback"
    diagnostic_note: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture.value,
            "memory_posture": self.memory_posture,
            "continuity_score": round(self.continuity_score, 4),
            "retrieval_relevance": round(self.retrieval_relevance, 4),
            "novelty_score": round(self.novelty_score, 4),
            "recent_task_count": self.recent_task_count,
            "recent_success_rate": round(self.recent_success_rate, 4),
            "influenced_by_memory": self.influenced_by_memory,
            "source": self.source,
            "diagnostic_note": self.diagnostic_note,
            "timestamp": self.timestamp,
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

FALLBACK_MEMORY_BIAS: MemoryDecisionBias = MemoryDecisionBias(
    posture=MemoryPosture.NOVELTY,
    memory_posture=MemoryPosture.NOVELTY.value,
    continuity_score=0.0,
    retrieval_relevance=0.0,
    novelty_score=1.0,
    recent_task_count=0,
    recent_success_rate=0.0,
    influenced_by_memory=False,
    source="fallback",
    diagnostic_note="memory_unavailable: using novelty fallback",
)


# ---------------------------------------------------------------------------
# MemoryBiasGuidance dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBiasGuidance:
    """Planner / execution guidance derived from a :class:`MemoryDecisionBias`.

    This dataclass is the canonical output of :func:`get_memory_bias_guidance`.

    Attributes
    ----------
    posture_label:
        The posture label (``"continuity_seeking"`` / ``"retrieval_seeking"`` /
        ``"novelty"``).
    prefer_continuity:
        When True, planner should prefer strategies and context that continue
        prior work.  Advisory only.
    prefer_retrieval:
        When True, planner should prefer strategies that leverage prior memory
        records.  Advisory only.
    context_injection_n:
        Recommended number of historical memory records to inject into the
        execution context.  ``0`` means no injection suggested.
    strategy_continuity_hint:
        Optional strategy hint based on recent successful strategies.
        ``None`` when no useful hint is available.
    influenced_by_memory:
        True when derived from live memory signals (not fallback).
    diagnostic_note:
        Human-readable note explaining the guidance decision.
    """

    posture_label: str = MemoryPosture.NOVELTY.value
    prefer_continuity: bool = False
    prefer_retrieval: bool = False
    context_injection_n: int = 0
    strategy_continuity_hint: Optional[str] = None
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture_label": self.posture_label,
            "prefer_continuity": self.prefer_continuity,
            "prefer_retrieval": self.prefer_retrieval,
            "context_injection_n": self.context_injection_n,
            "strategy_continuity_hint": self.strategy_continuity_hint,
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Core derivation: TaskMemory signals → MemoryDecisionBias
# ---------------------------------------------------------------------------


def derive_memory_bias(
    session_id: Optional[str] = None,
    *,
    task_memory: Optional[Any] = None,
    trace_id: Optional[str] = None,
) -> MemoryDecisionBias:
    """Derive a :class:`MemoryDecisionBias` from available TaskMemory signals.

    Parameters
    ----------
    session_id:
        Optional session ID used to filter task memory records.  When provided,
        only records matching the session are used for continuity signals.
        Falls back to all recent records when no session-specific records exist.
    task_memory:
        Optional pre-constructed :class:`~core.task_memory.TaskMemory` instance.
        When ``None``, the module-level singleton is obtained via
        ``core.task_memory.get_task_memory()``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryDecisionBias
        A bounded, advisory memory bias.  Never raises — returns
        :data:`FALLBACK_MEMORY_BIAS` on any error.
    """
    try:
        return _derive_bias_impl(
            session_id=session_id,
            task_memory=task_memory,
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
    session_id: Optional[str],
    task_memory: Optional[Any],
    trace_id: Optional[str],
) -> MemoryDecisionBias:
    """Internal implementation of memory bias derivation."""
    # Obtain TaskMemory instance
    mem = task_memory
    if mem is None:
        try:
            from core.task_memory import get_task_memory as _get_task_mem
            mem = _get_task_mem()
        except Exception as import_err:
            logger.debug(
                "_derive_bias_impl: TaskMemory unavailable (trace_id=%s): %s",
                trace_id,
                import_err,
            )
            return FALLBACK_MEMORY_BIAS

    # Collect recent task summaries (up to 10 for signal analysis)
    try:
        recent: List[Any] = mem.get_recent_summaries(n=10)
    except Exception as mem_err:
        logger.debug(
            "_derive_bias_impl: get_recent_summaries failed (trace_id=%s): %s",
            trace_id,
            mem_err,
        )
        return FALLBACK_MEMORY_BIAS

    recent_count = len(recent)

    if recent_count == 0:
        return MemoryDecisionBias(
            posture=MemoryPosture.NOVELTY,
            memory_posture=MemoryPosture.NOVELTY.value,
            continuity_score=0.0,
            retrieval_relevance=0.0,
            novelty_score=1.0,
            recent_task_count=0,
            recent_success_rate=0.0,
            influenced_by_memory=True,
            source="memory_decision_bias",
            diagnostic_note="no_recent_tasks: novelty posture (fresh handling preferred)",
        )

    # Compute success rate from recent records
    successes = sum(1 for r in recent if getattr(r, "success", True))
    success_rate = successes / recent_count if recent_count > 0 else 0.0

    # Compute recency score: fraction of recent records that are within the
    # retrieval-relevant time window
    now = time.time()
    recent_in_window = sum(
        1 for r in recent
        if (now - float(getattr(r, "timestamp", 0.0))) <= _RETRIEVAL_MAX_AGE_SECONDS
    )
    recency_fraction = recent_in_window / recent_count if recent_count > 0 else 0.0

    # Derive the dominant prior strategy (for continuity hint)
    strategy_counts: Dict[str, int] = {}
    for r in recent:
        strat = getattr(r, "strategy", "") or ""
        if strat:
            strategy_counts[strat] = strategy_counts.get(strat, 0) + 1
    dominant_strategy: Optional[str] = (
        max(strategy_counts, key=strategy_counts.__getitem__)
        if strategy_counts else None
    )

    # Compute normalised signal scores
    # continuity_score: high when many recent tasks and high success rate
    continuity_score = min(1.0, (recent_count / 10.0) * success_rate)
    # retrieval_relevance: high when records exist and are recent
    retrieval_relevance = min(1.0, (recent_count / 10.0) * recency_fraction)
    # novelty_score: inverse of how much memory context is available
    novelty_score = max(0.0, 1.0 - continuity_score - (retrieval_relevance * 0.3))
    novelty_score = min(1.0, novelty_score)

    # Classify posture
    if (
        recent_count >= _CONTINUITY_MIN_TASKS
        and success_rate >= _CONTINUITY_MIN_SUCCESS_RATE
        and continuity_score >= 0.1
    ):
        posture = MemoryPosture.CONTINUITY_SEEKING
        note = (
            f"continuity_seeking: recent_count={recent_count} "
            f"success_rate={success_rate:.2f} continuity_score={continuity_score:.3f} "
            f"(prior_strategy={dominant_strategy or 'none'})"
        )
    elif recent_count >= _RETRIEVAL_MIN_TASKS and retrieval_relevance > 0.0:
        posture = MemoryPosture.RETRIEVAL_SEEKING
        note = (
            f"retrieval_seeking: recent_count={recent_count} "
            f"success_rate={success_rate:.2f} retrieval_relevance={retrieval_relevance:.3f} "
            f"recency_fraction={recency_fraction:.2f}"
        )
    else:
        posture = MemoryPosture.NOVELTY
        note = (
            f"novelty: recent_count={recent_count} success_rate={success_rate:.2f} "
            f"continuity_score={continuity_score:.3f} — low memory signal"
        )

    logger.debug(
        "MemoryDecisionBias: posture=%s recent=%d success=%.2f "
        "continuity=%.3f retrieval=%.3f trace_id=%s",
        posture.value,
        recent_count,
        success_rate,
        continuity_score,
        retrieval_relevance,
        trace_id,
    )

    return MemoryDecisionBias(
        posture=posture,
        memory_posture=posture.value,
        continuity_score=round(continuity_score, 4),
        retrieval_relevance=round(retrieval_relevance, 4),
        novelty_score=round(novelty_score, 4),
        recent_task_count=recent_count,
        recent_success_rate=round(success_rate, 4),
        influenced_by_memory=True,
        source="memory_decision_bias",
        diagnostic_note=note,
    )


# ---------------------------------------------------------------------------
# MemoryBiasGuidance derivation
# ---------------------------------------------------------------------------


def get_memory_bias_guidance(
    bias: Optional[MemoryDecisionBias],
    *,
    task_memory: Optional[Any] = None,
    trace_id: Optional[str] = None,
) -> MemoryBiasGuidance:
    """Translate a :class:`MemoryDecisionBias` into :class:`MemoryBiasGuidance`.

    Parameters
    ----------
    bias:
        A :class:`MemoryDecisionBias` or ``None``.
    task_memory:
        Optional :class:`~core.task_memory.TaskMemory` instance used to read
        the dominant prior strategy for the ``strategy_continuity_hint`` field.
        If ``None`` and ``bias`` is a continuity-seeking live bias, a best-effort
        strategy hint will be derived from the bias's cached signals.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryBiasGuidance
        Advisory guidance for the planner.  Never raises.
    """
    try:
        return _get_guidance_impl(bias=bias, task_memory=task_memory, trace_id=trace_id)
    except Exception as exc:
        logger.debug("get_memory_bias_guidance: error: %s", exc)
        return MemoryBiasGuidance(
            posture_label=MemoryPosture.NOVELTY.value,
            prefer_continuity=False,
            prefer_retrieval=False,
            context_injection_n=0,
            strategy_continuity_hint=None,
            influenced_by_memory=False,
            diagnostic_note=f"error_fallback: {exc}",
        )


def _get_guidance_impl(
    *,
    bias: Optional[MemoryDecisionBias],
    task_memory: Optional[Any],
    trace_id: Optional[str],
) -> MemoryBiasGuidance:
    """Internal guidance derivation."""
    if bias is None or not bias.influenced_by_memory:
        return MemoryBiasGuidance(
            posture_label=MemoryPosture.NOVELTY.value,
            prefer_continuity=False,
            prefer_retrieval=False,
            context_injection_n=0,
            strategy_continuity_hint=None,
            influenced_by_memory=False,
            diagnostic_note="memory_bias_unavailable: no guidance applied",
        )

    posture = bias.posture

    if posture == MemoryPosture.CONTINUITY_SEEKING:
        # Derive dominant prior strategy for continuity hint
        strategy_hint = _get_dominant_strategy_hint(task_memory=task_memory)
        note = (
            f"continuity_seeking: prefer_continuity=True "
            f"context_injection_n={_CONTEXT_INJECTION_CONTINUITY} "
            f"strategy_hint={strategy_hint or 'none'} "
            f"(recent_count={bias.recent_task_count} "
            f"success_rate={bias.recent_success_rate:.2f})"
        )
        return MemoryBiasGuidance(
            posture_label=MemoryPosture.CONTINUITY_SEEKING.value,
            prefer_continuity=True,
            prefer_retrieval=False,
            context_injection_n=_CONTEXT_INJECTION_CONTINUITY,
            strategy_continuity_hint=strategy_hint,
            influenced_by_memory=True,
            diagnostic_note=note,
        )

    elif posture == MemoryPosture.RETRIEVAL_SEEKING:
        note = (
            f"retrieval_seeking: prefer_retrieval=True "
            f"context_injection_n={_CONTEXT_INJECTION_RETRIEVAL} "
            f"(recent_count={bias.recent_task_count} "
            f"retrieval_relevance={bias.retrieval_relevance:.3f})"
        )
        return MemoryBiasGuidance(
            posture_label=MemoryPosture.RETRIEVAL_SEEKING.value,
            prefer_continuity=False,
            prefer_retrieval=True,
            context_injection_n=_CONTEXT_INJECTION_RETRIEVAL,
            strategy_continuity_hint=None,
            influenced_by_memory=True,
            diagnostic_note=note,
        )

    else:  # NOVELTY
        note = (
            f"novelty: no_memory_bias "
            f"(recent_count={bias.recent_task_count} "
            f"continuity_score={bias.continuity_score:.3f})"
        )
        return MemoryBiasGuidance(
            posture_label=MemoryPosture.NOVELTY.value,
            prefer_continuity=False,
            prefer_retrieval=False,
            context_injection_n=_CONTEXT_INJECTION_NOVELTY,
            strategy_continuity_hint=None,
            influenced_by_memory=True,
            diagnostic_note=note,
        )


def _get_dominant_strategy_hint(task_memory: Optional[Any]) -> Optional[str]:
    """Read the dominant prior strategy from TaskMemory for continuity hinting."""
    try:
        mem = task_memory
        if mem is None:
            from core.task_memory import get_task_memory as _g
            mem = _g()
        summaries = mem.get_recent_summaries(n=5)
        counts: Dict[str, int] = {}
        for s in summaries:
            strat = getattr(s, "strategy", "") or ""
            if strat and getattr(s, "success", True):
                counts[strat] = counts.get(strat, 0) + 1
        if counts:
            return max(counts, key=counts.__getitem__)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Diagnostics helper
# ---------------------------------------------------------------------------


def build_memory_bias_diagnostics(
    bias: Optional[MemoryDecisionBias],
    guidance: Optional[MemoryBiasGuidance] = None,
    *,
    influenced: bool = False,
    influence_source: str = "",
    hard_gate_overrode: bool = False,
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a diagnostics payload for embedding in response metadata.

    Parameters
    ----------
    bias:
        The :class:`MemoryDecisionBias` that was active during execution.
    guidance:
        Optional :class:`MemoryBiasGuidance` derived from the bias.
    influenced:
        Whether memory bias actually influenced the runtime behavior.
    influence_source:
        Short description of where the bias was applied, e.g.
        ``"planner_context_injection"`` or ``"strategy_hint"``.
    hard_gate_overrode:
        True when a hard gate (governance, activation context, etc.) overrode
        the memory bias influence.  Used to satisfy the diagnostics acceptance
        criterion.
    trace_id:
        Optional correlation ID.

    Returns
    -------
    dict
        JSON-safe diagnostics dict.  Never raises.
    """
    try:
        diag: Dict[str, Any] = {
            "memory_bias_active": bias is not None and bias.influenced_by_memory,
            "memory_bias_influenced_runtime": influenced,
            "influence_source": influence_source or "none",
            "hard_gate_overrode_memory_bias": hard_gate_overrode,
            "trace_id": trace_id,
        }
        if bias is not None:
            diag["memory_bias"] = bias.to_dict()
        if guidance is not None:
            diag["memory_bias_guidance"] = guidance.to_dict()
        return diag
    except Exception as exc:
        logger.debug("build_memory_bias_diagnostics: error: %s", exc)
        return {
            "memory_bias_active": False,
            "memory_bias_influenced_runtime": False,
            "error": str(exc),
        }
