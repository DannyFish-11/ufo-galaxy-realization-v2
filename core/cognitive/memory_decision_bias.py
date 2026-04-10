#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_decision_bias
=====================================

PR-19 — Bounded Memory Decision-Bias Layer

Introduces a canonical **memory-informed runtime bias** representation that
lets memory-derived continuity / retrieval / novelty signals softly influence
runtime decisions (planning decomposition, node activation preference,
continuity-vs-fresh handling) without overriding hard governance, explicit
user intent, or live task semantics.

Design principles
-----------------
- **Advisory only**: :class:`MemoryDecisionBias` is a bounded soft-influence
  object.  It never replaces lifecycle governance, invocation governance,
  node activation-context readiness (PR-11, PR-14, PR-15 node tracks), or
  explicit user instructions.
- **Derived from already-available signals**: Bias is derived solely from
  already-running memory subsystems (:class:`~core.task_memory.TaskMemory`,
  :class:`~core.cognitive.working_memory.WorkingMemory`,
  :class:`~core.cognitive.long_term_memory.LongTermMemory`).  No new
  memory pipeline is started; derivation is synchronous and non-blocking.
- **Additive**: All consumers fall back gracefully when bias is absent or
  when derivation fails.
- **Explainable**: :func:`build_memory_bias_diagnostics` exposes the inferred
  posture, signal sources, and where the bias influenced runtime behaviour.

Memory posture taxonomy
-----------------------
CONTINUITY_SEEKING
    Rich recent-task history with high success rate; active working-memory
    context for this session.  Bias: prefer to resume prior context, keep
    execution in a single coherent agent (avoid fragmentation), lean toward
    continuity-aware model selection.

RETRIEVAL_SEEKING
    Prior task history exists but contains mixed success or the current
    request semantics suggest recall would help.  Bias: nudge planner to
    consider recall-supportive execution; no strong continuity preference.

NOVELTY
    Very sparse or absent prior context; session is effectively fresh.
    Bias: no continuity assumption; planner runs normally.

Authority sentinels
-------------------
MEMORY_DECISION_BIAS_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_DECISION_BIAS_PR19_SENTINEL
    Machine-checkable sentinel confirming the bias layer is present.

Usage::

    from core.cognitive.memory_decision_bias import (
        derive_memory_decision_bias,
        get_memory_planner_hint,
        build_memory_bias_diagnostics,
        MemoryDecisionBias,
        MemoryPosture,
    )

    bias = derive_memory_decision_bias(session_id="sess_abc")
    print(bias.posture)             # "continuity_seeking" | "retrieval_seeking" | "novelty"
    hint = get_memory_planner_hint(bias)
    print(hint.continuity_preference)  # "high" | "moderate" | "none"
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
    "core.cognitive.memory_decision_bias is the canonical bounded memory "
    "decision-bias layer for PR-19.  It derives MemoryDecisionBias from "
    "already-available memory signals (TaskMemory, WorkingMemory, "
    "LongTermMemory) and produces advisory MemoryPlannerHint objects for "
    "planner / kernel consumers.  It does not replace lifecycle governance, "
    "invocation governance, or node activation-context readiness checks."
)

MEMORY_DECISION_BIAS_PR19_SENTINEL: str = (
    "MEMORY_DECISION_BIAS::PR19_SENTINEL: "
    "Memory decision bias (PR-19) is present and active.  MemoryDecisionBias "
    "is derived from TaskMemory / WorkingMemory / LongTermMemory signals and "
    "wired into AgentKernel and ExecutionPlanner as a soft advisory influence."
)

# Policy sentinels
HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_1: "
    "Hard gates (lifecycle governance, invocation governance, node "
    "activation-context readiness) are ALWAYS authoritative.  "
    "MemoryDecisionBias is a soft influence layer that operates above and "
    "alongside hard gates, never replacing them."
)

MEMORY_BIAS_SUBORDINATE_TO_EXPLICIT_INTENT_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_2: "
    "Explicit user intent and current-turn task semantics are primary.  "
    "MemoryDecisionBias is subordinate: it must not silently override or "
    "contradict explicit user instructions or live task semantics."
)

MEMORY_BIAS_ADVISORY_NOT_ROUTING_AUTHORITY_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_3: "
    "MemoryDecisionBias is advisory.  It must not become a routing authority "
    "or global hidden memory controller.  Its influence is bounded, "
    "explainable, and transparent via diagnostics."
)

MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY: str = (
    "MEMORY_DECISION_BIAS::POLICY_4: "
    "MemoryDecisionBias is always derived from already-running memory "
    "subsystems (TaskMemory, WorkingMemory, LongTermMemory).  No new memory "
    "pipeline is started; derivation is synchronous and non-blocking."
)

# ---------------------------------------------------------------------------
# Constants — posture thresholds
# ---------------------------------------------------------------------------

# Minimum hot-area task records to consider a session continuity-capable
_MIN_RECORDS_FOR_CONTINUITY: int = 2

# Minimum success ratio in hot area to qualify for continuity_seeking posture
_MIN_SUCCESS_RATIO_FOR_CONTINUITY: float = 0.6

# Minimum working-memory depth (entries) for a session to be continuity-capable
_MIN_WORKING_MEMORY_DEPTH: int = 1

# Maximum age (seconds) of the most-recent task record for it to count as
# "active" continuity context.  Default 3600 = 1 hour.
_MAX_CONTINUITY_AGE_SECONDS: float = 3600.0

# Minimum hot-area task records to qualify for retrieval_seeking posture
_MIN_RECORDS_FOR_RETRIEVAL: int = 1

# Posture string constants
POSTURE_CONTINUITY_SEEKING: str = "continuity_seeking"
POSTURE_RETRIEVAL_SEEKING: str = "retrieval_seeking"
POSTURE_NOVELTY: str = "novelty"

# Continuity preference levels
CONTINUITY_PREFERENCE_HIGH: str = "high"
CONTINUITY_PREFERENCE_MODERATE: str = "moderate"
CONTINUITY_PREFERENCE_NONE: str = "none"


# ---------------------------------------------------------------------------
# MemoryPosture (string enum proxy — avoids Enum import issues)
# ---------------------------------------------------------------------------

class MemoryPosture:
    """Memory posture constants.

    Use these constants rather than bare strings to avoid typos.
    """

    CONTINUITY_SEEKING: str = POSTURE_CONTINUITY_SEEKING
    """Rich prior context — prefer continuity-aware handling."""

    RETRIEVAL_SEEKING: str = POSTURE_RETRIEVAL_SEEKING
    """Prior context exists but mixed — recall support may help."""

    NOVELTY: str = POSTURE_NOVELTY
    """Sparse or absent prior context — fresh handling is appropriate."""

    _ALL = frozenset([CONTINUITY_SEEKING, RETRIEVAL_SEEKING, NOVELTY])

    @classmethod
    def is_valid(cls, posture: str) -> bool:
        return posture in cls._ALL


# ---------------------------------------------------------------------------
# MemoryDecisionBias dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryDecisionBias:
    """Bounded, advisory memory decision bias derived from memory signals.

    All fields have safe defaults; consumers must never assume a field is
    non-None.  This dataclass is the canonical output of
    :func:`derive_memory_decision_bias`.

    Attributes
    ----------
    posture:
        Inferred memory posture: ``"continuity_seeking"`` /
        ``"retrieval_seeking"`` / ``"novelty"``.
    continuity_score:
        Normalised continuity signal [0.0, 1.0].  Higher values indicate
        richer, more successful prior context.
    retrieval_relevance:
        Normalised retrieval-need signal [0.0, 1.0].  Higher values indicate
        the current session could benefit from memory recall support.
    novelty_score:
        Novelty signal [0.0, 1.0].  Higher values indicate little or no
        relevant prior context (inverse of continuity).
    recent_task_count:
        Number of hot-area task records used in the derivation.
    recent_success_rate:
        Fraction of recent hot-area tasks that succeeded [0.0, 1.0].
    working_memory_depth:
        Number of working-memory entries for this session at derivation time.
    long_term_memory_entry_count:
        Total long-term memory entries available at derivation time.
    session_id:
        Session ID used for working-memory lookup (may be empty).
    influenced_by_memory:
        Always ``True`` when derived from live memory signals.
        ``False`` for the fallback instance.
    source:
        ``"memory_decision_bias"`` for live derivations; ``"fallback"``
        when signals were unavailable.
    timestamp:
        Unix epoch at derivation time.
    """

    posture: str = POSTURE_NOVELTY
    continuity_score: float = 0.0
    retrieval_relevance: float = 0.0
    novelty_score: float = 1.0
    recent_task_count: int = 0
    recent_success_rate: float = 0.0
    working_memory_depth: int = 0
    long_term_memory_entry_count: int = 0
    session_id: str = ""
    influenced_by_memory: bool = False
    source: str = "fallback"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "continuity_score": round(self.continuity_score, 4),
            "retrieval_relevance": round(self.retrieval_relevance, 4),
            "novelty_score": round(self.novelty_score, 4),
            "recent_task_count": self.recent_task_count,
            "recent_success_rate": round(self.recent_success_rate, 4),
            "working_memory_depth": self.working_memory_depth,
            "long_term_memory_entry_count": self.long_term_memory_entry_count,
            "session_id": self.session_id,
            "influenced_by_memory": self.influenced_by_memory,
            "source": self.source,
            "timestamp": self.timestamp,
        }

    def is_continuity_seeking(self) -> bool:
        """Return True when posture is continuity_seeking."""
        return self.posture == POSTURE_CONTINUITY_SEEKING

    def is_retrieval_seeking(self) -> bool:
        """Return True when posture is retrieval_seeking."""
        return self.posture == POSTURE_RETRIEVAL_SEEKING

    def is_novelty(self) -> bool:
        """Return True when posture is novelty (low memory dependence)."""
        return self.posture == POSTURE_NOVELTY


# ---------------------------------------------------------------------------
# Fallback bias (safe default when memory signals unavailable)
# ---------------------------------------------------------------------------

FALLBACK_MEMORY_BIAS: MemoryDecisionBias = MemoryDecisionBias(
    posture=POSTURE_NOVELTY,
    continuity_score=0.0,
    retrieval_relevance=0.0,
    novelty_score=1.0,
    recent_task_count=0,
    recent_success_rate=0.0,
    working_memory_depth=0,
    long_term_memory_entry_count=0,
    session_id="",
    influenced_by_memory=False,
    source="fallback",
)


# ---------------------------------------------------------------------------
# MemoryPlannerHint dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryPlannerHint:
    """Planner-facing hint derived from a :class:`MemoryDecisionBias`.

    This dataclass is the canonical output of :func:`get_memory_planner_hint`.

    Attributes
    ----------
    continuity_preference:
        Advisory continuity preference: ``"high"`` / ``"moderate"`` / ``"none"``.
    prefer_single_agent:
        When ``True``, the memory posture suggests keeping execution in a
        single coherent agent to preserve context continuity.  Advisory only.
    allow_context_injection:
        When ``True``, the memory layer has relevant prior context that may
        usefully be injected into the execution context.
    posture:
        The memory posture that produced this hint.
    influenced_by_memory:
        True when this hint was derived from live memory signals.
    diagnostic_note:
        Human-readable note explaining the hint decision.
    """

    continuity_preference: str = CONTINUITY_PREFERENCE_NONE
    prefer_single_agent: bool = False
    allow_context_injection: bool = False
    posture: str = POSTURE_NOVELTY
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "continuity_preference": self.continuity_preference,
            "prefer_single_agent": self.prefer_single_agent,
            "allow_context_injection": self.allow_context_injection,
            "posture": self.posture,
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Core derivation: memory signals → MemoryDecisionBias
# ---------------------------------------------------------------------------


def derive_memory_decision_bias(
    session_id: str = "",
    *,
    task_memory: Optional[Any] = None,
    working_memory: Optional[Any] = None,
    long_term_memory: Optional[Any] = None,
    trace_id: Optional[str] = None,
) -> MemoryDecisionBias:
    """Derive a :class:`MemoryDecisionBias` from available memory signals.

    This function reads from the already-running memory subsystems and
    produces a bounded, advisory bias object.  It never raises — returns
    :data:`FALLBACK_MEMORY_BIAS` on any error.

    Parameters
    ----------
    session_id:
        Session ID used for working-memory lookup.  May be empty.
    task_memory:
        Optional :class:`~core.task_memory.TaskMemory` instance for testing.
        Uses the process singleton when ``None``.
    working_memory:
        Optional :class:`~core.cognitive.working_memory.WorkingMemory`
        instance for testing.  Uses the process singleton when ``None``.
    long_term_memory:
        Optional :class:`~core.cognitive.long_term_memory.LongTermMemory`
        instance for testing.  Uses the process singleton when ``None``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryDecisionBias
        Bounded advisory bias.  Never raises; returns
        :data:`FALLBACK_MEMORY_BIAS` on any error.
    """
    try:
        return _derive_bias_impl(
            session_id=session_id,
            task_memory=task_memory,
            working_memory=working_memory,
            long_term_memory=long_term_memory,
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.debug(
            "derive_memory_decision_bias: error (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return FALLBACK_MEMORY_BIAS


def _derive_bias_impl(
    *,
    session_id: str,
    task_memory: Optional[Any],
    working_memory: Optional[Any],
    long_term_memory: Optional[Any],
    trace_id: Optional[str],
) -> MemoryDecisionBias:
    """Internal implementation of bias derivation."""
    now = time.time()

    # ------------------------------------------------------------------
    # 1. Gather task memory signals (hot-area summaries)
    # ------------------------------------------------------------------
    recent_task_count: int = 0
    recent_success_rate: float = 0.0
    most_recent_task_age: float = float("inf")

    try:
        _tm = task_memory
        if _tm is None:
            from core.task_memory import get_task_memory as _get_tm
            _tm = _get_tm()
        summaries = _tm.get_recent_summaries(n=10)
        recent_task_count = len(summaries)
        if summaries:
            successful = sum(1 for s in summaries if s.success)
            recent_success_rate = successful / recent_task_count
            # Age of the most recent record (seconds)
            most_recent_ts = max(s.timestamp for s in summaries)
            most_recent_task_age = now - most_recent_ts
    except Exception as _tm_err:
        logger.debug(
            "derive_memory_decision_bias: task_memory read failed (trace_id=%s): %s",
            trace_id,
            _tm_err,
        )

    # ------------------------------------------------------------------
    # 2. Gather working memory signals
    # ------------------------------------------------------------------
    working_memory_depth: int = 0
    try:
        _wm = working_memory
        if _wm is None:
            from core.cognitive.working_memory import get_working_memory as _get_wm
            _wm = _get_wm()
        if session_id:
            _entries = _wm.get(session_id=session_id)
            working_memory_depth = len(_entries) if _entries else 0
    except Exception as _wm_err:
        logger.debug(
            "derive_memory_decision_bias: working_memory read failed (trace_id=%s): %s",
            trace_id,
            _wm_err,
        )

    # ------------------------------------------------------------------
    # 3. Gather long-term memory entry count
    # ------------------------------------------------------------------
    long_term_memory_entry_count: int = 0
    try:
        _ltm = long_term_memory
        if _ltm is None:
            from core.cognitive.long_term_memory import get_long_term_memory as _get_ltm
            _ltm = _get_ltm()
        _all_entries = list(_ltm.retrieve_all())
        long_term_memory_entry_count = len(_all_entries)
    except Exception as _ltm_err:
        logger.debug(
            "derive_memory_decision_bias: long_term_memory read failed (trace_id=%s): %s",
            trace_id,
            _ltm_err,
        )

    # ------------------------------------------------------------------
    # 4. Compute continuity_score
    #    High when: recent task count is sufficient, success rate is good,
    #    and the most recent task is not too old.
    # ------------------------------------------------------------------
    continuity_score: float = 0.0

    if recent_task_count >= _MIN_RECORDS_FOR_CONTINUITY:
        # Weight by success rate and recency
        recency_factor = max(
            0.0,
            1.0 - (most_recent_task_age / _MAX_CONTINUITY_AGE_SECONDS),
        )
        continuity_score = recent_success_rate * recency_factor
        # Boost slightly if working memory is active for this session
        if working_memory_depth >= _MIN_WORKING_MEMORY_DEPTH:
            continuity_score = min(1.0, continuity_score + 0.15)

    continuity_score = max(0.0, min(1.0, continuity_score))

    # ------------------------------------------------------------------
    # 5. Compute retrieval_relevance
    #    Moderate when task history exists but continuity is low or mixed.
    # ------------------------------------------------------------------
    retrieval_relevance: float = 0.0

    if recent_task_count >= _MIN_RECORDS_FOR_RETRIEVAL:
        # Retrieval is more relevant when there's history but low continuity
        retrieval_relevance = max(
            0.0,
            min(1.0, (recent_task_count / 10.0) * (1.0 - continuity_score * 0.5)),
        )
        # Also boost if long-term memory is populated
        if long_term_memory_entry_count > 0:
            retrieval_relevance = min(1.0, retrieval_relevance + 0.1)

    retrieval_relevance = max(0.0, min(1.0, retrieval_relevance))

    # ------------------------------------------------------------------
    # 6. Compute novelty_score (inverse of continuity)
    # ------------------------------------------------------------------
    novelty_score: float = max(0.0, min(1.0, 1.0 - continuity_score))

    # ------------------------------------------------------------------
    # 7. Determine posture
    # ------------------------------------------------------------------
    posture: str
    if (
        recent_task_count >= _MIN_RECORDS_FOR_CONTINUITY
        and recent_success_rate >= _MIN_SUCCESS_RATIO_FOR_CONTINUITY
        and most_recent_task_age <= _MAX_CONTINUITY_AGE_SECONDS
        and (working_memory_depth >= _MIN_WORKING_MEMORY_DEPTH or continuity_score >= 0.5)
    ):
        posture = POSTURE_CONTINUITY_SEEKING
    elif recent_task_count >= _MIN_RECORDS_FOR_RETRIEVAL:
        posture = POSTURE_RETRIEVAL_SEEKING
    else:
        posture = POSTURE_NOVELTY

    logger.debug(
        "MemoryDecisionBias: posture=%s continuity=%.3f retrieval=%.3f novelty=%.3f "
        "tasks=%d success=%.2f wm_depth=%d ltm=%d trace_id=%s",
        posture,
        continuity_score,
        retrieval_relevance,
        novelty_score,
        recent_task_count,
        recent_success_rate,
        working_memory_depth,
        long_term_memory_entry_count,
        trace_id,
    )

    return MemoryDecisionBias(
        posture=posture,
        continuity_score=round(continuity_score, 4),
        retrieval_relevance=round(retrieval_relevance, 4),
        novelty_score=round(novelty_score, 4),
        recent_task_count=recent_task_count,
        recent_success_rate=round(recent_success_rate, 4),
        working_memory_depth=working_memory_depth,
        long_term_memory_entry_count=long_term_memory_entry_count,
        session_id=session_id,
        influenced_by_memory=True,
        source="memory_decision_bias",
    )


# ---------------------------------------------------------------------------
# MemoryPlannerHint derivation
# ---------------------------------------------------------------------------


def get_memory_planner_hint(
    bias: Optional[MemoryDecisionBias],
    *,
    trace_id: Optional[str] = None,
) -> MemoryPlannerHint:
    """Translate a :class:`MemoryDecisionBias` into a :class:`MemoryPlannerHint`.

    Parameters
    ----------
    bias:
        A :class:`MemoryDecisionBias` or ``None``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryPlannerHint
        Advisory hint for planner consumers.  Never raises.
    """
    try:
        if bias is None or not bias.influenced_by_memory:
            return MemoryPlannerHint(
                continuity_preference=CONTINUITY_PREFERENCE_NONE,
                prefer_single_agent=False,
                allow_context_injection=False,
                posture=POSTURE_NOVELTY,
                influenced_by_memory=False,
                diagnostic_note="memory_bias_unavailable: using novelty defaults",
            )

        posture = bias.posture

        if posture == POSTURE_CONTINUITY_SEEKING:
            note = (
                f"memory_posture={posture} (continuity_score={bias.continuity_score:.3f}, "
                f"tasks={bias.recent_task_count}, success={bias.recent_success_rate:.2f}): "
                "prefer continuity-aware single-agent execution to preserve context"
            )
            return MemoryPlannerHint(
                continuity_preference=CONTINUITY_PREFERENCE_HIGH,
                prefer_single_agent=True,
                allow_context_injection=True,
                posture=posture,
                influenced_by_memory=True,
                diagnostic_note=note,
            )

        elif posture == POSTURE_RETRIEVAL_SEEKING:
            note = (
                f"memory_posture={posture} (retrieval_relevance={bias.retrieval_relevance:.3f}, "
                f"tasks={bias.recent_task_count}): "
                "allow recall-supportive context injection; no strong continuity preference"
            )
            return MemoryPlannerHint(
                continuity_preference=CONTINUITY_PREFERENCE_MODERATE,
                prefer_single_agent=False,
                allow_context_injection=True,
                posture=posture,
                influenced_by_memory=True,
                diagnostic_note=note,
            )

        else:  # POSTURE_NOVELTY
            note = (
                f"memory_posture={posture} (tasks={bias.recent_task_count}, "
                f"novelty_score={bias.novelty_score:.3f}): "
                "low memory dependence — no continuity bias applied"
            )
            return MemoryPlannerHint(
                continuity_preference=CONTINUITY_PREFERENCE_NONE,
                prefer_single_agent=False,
                allow_context_injection=False,
                posture=posture,
                influenced_by_memory=True,
                diagnostic_note=note,
            )

    except Exception as exc:
        logger.debug("get_memory_planner_hint: error: %s", exc)
        return MemoryPlannerHint(
            continuity_preference=CONTINUITY_PREFERENCE_NONE,
            prefer_single_agent=False,
            allow_context_injection=False,
            posture=POSTURE_NOVELTY,
            influenced_by_memory=False,
            diagnostic_note=f"error_fallback: {exc}",
        )


# ---------------------------------------------------------------------------
# Diagnostics helper
# ---------------------------------------------------------------------------


def build_memory_bias_diagnostics(
    bias: Optional[MemoryDecisionBias],
    hint: Optional[MemoryPlannerHint] = None,
    *,
    influenced: bool = False,
    influence_source: str = "",
    trace_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a diagnostics payload for embedding in response metadata.

    Parameters
    ----------
    bias:
        The :class:`MemoryDecisionBias` that was active during execution.
    hint:
        Optional :class:`MemoryPlannerHint` derived from the bias.
    influenced:
        Whether memory bias actually influenced runtime behaviour.
    influence_source:
        Short description of where the bias influence was applied, e.g.
        ``"planner_strategy"`` or ``"chat_continuity"``.
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
            "memory_influenced_runtime": influenced,
            "influence_source": influence_source or "none",
            "trace_id": trace_id,
        }
        if bias is not None:
            diag["bias"] = bias.to_dict()
        if hint is not None:
            diag["planner_hint"] = hint.to_dict()
        return diag
    except Exception as exc:
        return {
            "memory_bias_active": False,
            "memory_influenced_runtime": False,
            "influence_source": "error",
            "error": str(exc),
            "trace_id": trace_id,
        }
