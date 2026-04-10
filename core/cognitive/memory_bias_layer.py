#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_bias_layer
=================================

PR-19 — Memory-Informed Runtime Bias

Canonical **memory-bias layer** that derives bounded, advisory continuity /
retrieval / novelty signals from already-available memory sources
(:class:`~core.cognitive.working_memory.WorkingMemory`,
:class:`~core.cognitive.long_term_memory.LongTermMemory`,
:class:`~core.task_memory.TaskMemory`) and makes those signals available
to the runtime execution path.

Design principles
-----------------
- **Bounded and advisory**: :class:`MemoryBias` is a *hint*, not a command.
  It biases execution preferences rather than replacing core authority figures
  (governance, activation-context readiness, lifecycle denial, explicit user
  intent).
- **Consumes, does not re-compute**: All signals are read from already-live
  memory singletons.  This module never starts a second memory pipeline.
- **Soft influence, not hard gate**: A continuity bias does not force a
  specific execution mode; it softly influences planner strategy selection
  and handling heuristics.
- **Hard gates remain authoritative**: Invocation governance (PR-11),
  node activation-context readiness (PR-14/PR-15), activation-budget
  narrowing (PR-18), and explicit user instructions always take precedence.
- **Three canonical postures**:
  - ``CONTINUITY_SEEKING`` — sufficient recent working-memory / task context
    to prefer resuming prior context over fresh handling.
  - ``RETRIEVAL_SEEKING``  — relevant long-term memory entries exist that
    may support recall-augmented execution.
  - ``NOVELTY``            — low memory depth; no strong prior context;
    favour fresh, unconstrained handling.

Memory-posture to planner guidance mapping
-------------------------------------------
CONTINUITY_SEEKING  →  decomposition_hint="resume",  prefer_single=True
RETRIEVAL_SEEKING   →  decomposition_hint="recall",   prefer_single=False (allow team)
NOVELTY             →  decomposition_hint="fresh",    no bias

Authority sentinels
-------------------
MEMORY_BIAS_LAYER_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_BIAS_LAYER_PR19_SENTINEL
    Machine-checkable sentinel confirming the memory-bias layer is present.

Usage::

    from core.cognitive.memory_bias_layer import (
        derive_memory_bias,
        get_memory_planner_guidance,
        build_memory_bias_diagnostics,
        MemoryBias,
        MemoryPlannerGuidance,
    )

    bias = derive_memory_bias(session_id="sess_abc")
    guidance = get_memory_planner_guidance(bias)
    print(guidance.posture)            # "continuity" | "retrieval" | "novelty"
    print(guidance.decomposition_hint) # "resume" | "recall" | "fresh"
    diag = build_memory_bias_diagnostics(bias, influenced=guidance.influenced_by_memory)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Cognitive.MemoryBias")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

MEMORY_BIAS_LAYER_IS_AUTHORITY: str = (
    "MEMORY_BIAS_LAYER::CANONICAL_AUTHORITY: "
    "core.cognitive.memory_bias_layer is the canonical memory-bias layer for "
    "PR-19.  It derives bounded MemoryBias and MemoryPlannerGuidance objects "
    "from already-live memory sources (WorkingMemory, LongTermMemory, TaskMemory). "
    "It does not replace invocation governance, activation-context readiness, "
    "activation budgets, or explicit user instructions."
)

MEMORY_BIAS_LAYER_PR19_SENTINEL: str = (
    "MEMORY_BIAS_LAYER::PR19_SENTINEL: "
    "Memory-informed runtime bias (PR-19) is present and active.  "
    "MemoryBias is derived from live memory signals and wired into "
    "ExecutionPlanner strategy selection and AgentKernel response diagnostics."
)

# Policy sentinels
HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY: str = (
    "MEMORY_BIAS_LAYER::POLICY_1: "
    "Hard gates (invocation governance, lifecycle denial, activation-context "
    "readiness, explicit user intent) are ALWAYS authoritative.  MemoryBias is "
    "a soft advisory layer that operates alongside hard gates, never replacing them."
)

MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITATIVE_POLICY: str = (
    "MEMORY_BIAS_LAYER::POLICY_2: "
    "MemoryBias is strictly advisory.  Consumers MUST NOT treat any memory posture "
    "as a hard execution gate.  A NOVELTY posture does not prevent reuse of context; "
    "a CONTINUITY posture does not force single-agent execution."
)

MEMORY_BIAS_CONSUMES_EXISTING_SIGNALS_POLICY: str = (
    "MEMORY_BIAS_LAYER::POLICY_3: "
    "MemoryBias is always derived from already-live memory singletons "
    "(WorkingMemory, LongTermMemory, TaskMemory).  No new memory pipeline is "
    "started; no external calls are made."
)

MEMORY_BIAS_SUBORDINATE_TO_TASK_SEMANTICS_POLICY: str = (
    "MEMORY_BIAS_LAYER::POLICY_4: "
    "Explicit current-turn task semantics and user-stated intent always take "
    "precedence over memory-derived bias.  Memory bias is the lowest-priority "
    "influence on execution strategy selection."
)

# ---------------------------------------------------------------------------
# Posture constants
# ---------------------------------------------------------------------------

POSTURE_CONTINUITY: str = "continuity"
"""Sufficient recent memory context to favour resuming prior context."""

POSTURE_RETRIEVAL: str = "retrieval"
"""Relevant long-term memory entries may support recall-augmented execution."""

POSTURE_NOVELTY: str = "novelty"
"""Low memory depth; favour fresh, unconstrained handling."""

# Decomposition hints
DECOMP_HINT_RESUME: str = "resume"
"""Resume / continue from prior context (continuity posture)."""

DECOMP_HINT_RECALL: str = "recall"
"""Support execution with long-term memory recall (retrieval posture)."""

DECOMP_HINT_FRESH: str = "fresh"
"""Execute fresh with no continuity assumptions (novelty posture)."""

# Scoring thresholds
_CONTINUITY_SCORE_HIGH: float = 0.6
"""Working-memory depth score above which CONTINUITY_SEEKING is inferred."""

_RETRIEVAL_RELEVANCE_HIGH: float = 0.4
"""Long-term-memory depth score above which RETRIEVAL_SEEKING is inferred."""

# Working-memory entry counts that map to continuity scores
_WM_ENTRIES_HIGH: int = 5   # >= 5 recent entries → high continuity
_WM_ENTRIES_MED: int = 2    # >= 2 recent entries → moderate continuity
_LTM_ENTRIES_HIGH: int = 3  # >= 3 LTM entries → meaningful retrieval potential
_LTM_ENTRIES_MED: int = 1   # >= 1 LTM entry → low retrieval potential

# Recent task-memory recency window (seconds)
_TASK_MEMORY_RECENCY_WINDOW: float = 3600.0  # last 1 hour


# ---------------------------------------------------------------------------
# MemoryBias dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBias:
    """Bounded, advisory memory bias derived from live memory sources.

    This dataclass is the canonical output of :func:`derive_memory_bias`.
    All fields have safe defaults; consumers must never assume any field is
    non-None.

    Attributes
    ----------
    posture:
        Inferred memory posture: ``"continuity"`` / ``"retrieval"`` / ``"novelty"``.
    continuity_score:
        Normalised score [0.0, 1.0] reflecting depth of available recent
        working-memory context.  Higher means stronger continuity signal.
    retrieval_relevance:
        Normalised score [0.0, 1.0] reflecting depth of available long-term
        memory entries that could support recall-augmented execution.
    novelty_factor:
        Normalised score [0.0, 1.0] reflecting how "fresh" / memory-independent
        this request appears.  Higher means less prior context to leverage.
    recent_task_count:
        Number of recent task-memory records within the recency window.
    working_memory_depth:
        Number of working-memory entries for the session (0 when unknown).
    long_term_memory_depth:
        Number of long-term memory entries available (0 when unknown).
    influenced_by_memory:
        True when derived from live memory signals with meaningful content;
        False when returned from fallback path.
    source:
        ``"memory_bias_layer"`` for live derivations; ``"fallback"`` otherwise.
    session_id:
        The session ID used for working-memory lookup (may be empty).
    timestamp:
        Unix epoch at derivation time.
    """

    posture: str = POSTURE_NOVELTY
    continuity_score: float = 0.0
    retrieval_relevance: float = 0.0
    novelty_factor: float = 1.0
    recent_task_count: int = 0
    working_memory_depth: int = 0
    long_term_memory_depth: int = 0
    influenced_by_memory: bool = False
    source: str = "fallback"
    session_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "continuity_score": round(self.continuity_score, 4),
            "retrieval_relevance": round(self.retrieval_relevance, 4),
            "novelty_factor": round(self.novelty_factor, 4),
            "recent_task_count": self.recent_task_count,
            "working_memory_depth": self.working_memory_depth,
            "long_term_memory_depth": self.long_term_memory_depth,
            "influenced_by_memory": self.influenced_by_memory,
            "source": self.source,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
        }

    def is_continuity(self) -> bool:
        """Return True when posture is continuity-seeking."""
        return self.posture == POSTURE_CONTINUITY

    def is_retrieval(self) -> bool:
        """Return True when posture is retrieval-seeking."""
        return self.posture == POSTURE_RETRIEVAL

    def is_novelty(self) -> bool:
        """Return True when posture is novelty / low-memory."""
        return self.posture == POSTURE_NOVELTY


# ---------------------------------------------------------------------------
# Fallback bias (safe default when memory signals are unavailable)
# ---------------------------------------------------------------------------

FALLBACK_MEMORY_BIAS: MemoryBias = MemoryBias(
    posture=POSTURE_NOVELTY,
    continuity_score=0.0,
    retrieval_relevance=0.0,
    novelty_factor=1.0,
    recent_task_count=0,
    working_memory_depth=0,
    long_term_memory_depth=0,
    influenced_by_memory=False,
    source="fallback",
    session_id="",
)


# ---------------------------------------------------------------------------
# MemoryPlannerGuidance dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryPlannerGuidance:
    """Planner guidance derived from a :class:`MemoryBias`.

    This dataclass is the canonical output of :func:`get_memory_planner_guidance`.

    Attributes
    ----------
    posture:
        Memory posture: ``"continuity"`` / ``"retrieval"`` / ``"novelty"``.
    decomposition_hint:
        Hint for planner decomposition style:
        ``"resume"``  → prefer continuity-aware single-pass execution;
        ``"recall"``  → allow recall-augmented or retrieval-enriched execution;
        ``"fresh"``   → no prior context assumed, normal strategy selection.
    prefer_single_agent:
        When True (continuity posture), bias planner toward single-agent
        strategy to maintain context coherence.
    complexity_threshold_adjustment:
        Float offset applied to existing planner complexity thresholds.
        Positive value raises the bar for complex strategies (continuity wants
        simpler, coherent execution); negative / zero leaves it unchanged.
    influenced_by_memory:
        True when derived from a live memory bias (not fallback).
    diagnostic_note:
        Human-readable explanation of the guidance decision.
    """

    posture: str = POSTURE_NOVELTY
    decomposition_hint: str = DECOMP_HINT_FRESH
    prefer_single_agent: bool = False
    complexity_threshold_adjustment: float = 0.0
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "decomposition_hint": self.decomposition_hint,
            "prefer_single_agent": self.prefer_single_agent,
            "complexity_threshold_adjustment": round(
                self.complexity_threshold_adjustment, 4
            ),
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def derive_memory_bias(
    session_id: str = "",
    *,
    trace_id: Optional[str] = None,
) -> MemoryBias:
    """Derive a :class:`MemoryBias` from available memory sources.

    Reads from :class:`~core.cognitive.working_memory.WorkingMemory`,
    :class:`~core.cognitive.long_term_memory.LongTermMemory`, and
    :class:`~core.task_memory.TaskMemory` (all already-live singletons).
    Never raises — returns :data:`FALLBACK_MEMORY_BIAS` on any error.

    Parameters
    ----------
    session_id:
        Session identifier used to look up per-session working memory.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryBias
        A bounded, advisory memory bias.  Never raises.
    """
    try:
        return _derive_memory_bias_impl(session_id=session_id, trace_id=trace_id)
    except Exception as exc:
        logger.debug(
            "derive_memory_bias: error (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return FALLBACK_MEMORY_BIAS


def get_memory_planner_guidance(
    bias: Optional[MemoryBias],
    *,
    trace_id: Optional[str] = None,
) -> MemoryPlannerGuidance:
    """Derive :class:`MemoryPlannerGuidance` from a :class:`MemoryBias`.

    Parameters
    ----------
    bias:
        A :class:`MemoryBias` (or ``None``).  When ``None`` or when the bias
        is the fallback, returns a non-influencing guidance object.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryPlannerGuidance
        Advisory guidance for the execution planner.  Never raises.
    """
    try:
        return _get_memory_planner_guidance_impl(bias=bias, trace_id=trace_id)
    except Exception as exc:
        logger.debug(
            "get_memory_planner_guidance: error (trace_id=%s): %s — returning fallback",
            trace_id,
            exc,
        )
        return MemoryPlannerGuidance(
            posture=POSTURE_NOVELTY,
            decomposition_hint=DECOMP_HINT_FRESH,
            prefer_single_agent=False,
            complexity_threshold_adjustment=0.0,
            influenced_by_memory=False,
            diagnostic_note="fallback — guidance derivation failed",
        )


def build_memory_bias_diagnostics(
    bias: Optional[MemoryBias],
    *,
    influenced: bool = False,
    influence_source: str = "",
) -> Dict[str, Any]:
    """Build a JSON-safe diagnostics dict for a :class:`MemoryBias`.

    Parameters
    ----------
    bias:
        The :class:`MemoryBias` to diagnose.  When ``None``, returns a minimal
        fallback diagnostics dict.
    influenced:
        Whether memory bias actually influenced a runtime decision in this turn.
    influence_source:
        Where the influence was applied (e.g. ``"planner_strategy"``).

    Returns
    -------
    Dict[str, Any]
        JSON-safe diagnostics dict.  Never raises.
    """
    try:
        base: Dict[str, Any] = bias.to_dict() if bias is not None else FALLBACK_MEMORY_BIAS.to_dict()
        base["influenced_runtime_decision"] = influenced
        base["influence_source"] = influence_source or ""
        return base
    except Exception as exc:
        logger.debug("build_memory_bias_diagnostics: error — %s", exc)
        return {
            "posture": POSTURE_NOVELTY,
            "influenced_by_memory": False,
            "influenced_runtime_decision": False,
            "influence_source": influence_source or "",
            "source": "diagnostics_error",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Internal implementation helpers
# ---------------------------------------------------------------------------


def _derive_memory_bias_impl(
    *,
    session_id: str,
    trace_id: Optional[str],
) -> MemoryBias:
    """Internal implementation of memory bias derivation."""
    wm_depth: int = 0
    ltm_depth: int = 0
    recent_task_count: int = 0

    # ── 1. Working-memory depth (per-session continuity signal) ──────────────
    try:
        from core.cognitive.working_memory import get_working_memory as _get_wm
        _wm = _get_wm()
        if session_id:
            entries = _wm.get(session_id=session_id)
            wm_depth = len(entries) if entries else 0
        else:
            # No session_id — check total active sessions for a coarse signal
            sessions = _wm.list_sessions() if hasattr(_wm, "list_sessions") else []
            wm_depth = len(sessions)
    except Exception as _wm_err:
        logger.debug("derive_memory_bias: WorkingMemory read failed — %s", _wm_err)

    # ── 2. Long-term memory depth (retrieval signal) ─────────────────────────
    try:
        from core.cognitive.long_term_memory import get_long_term_memory as _get_ltm
        _ltm = _get_ltm()
        _global_entries = _ltm.retrieve_all(namespace="global")
        ltm_depth = len(_global_entries) if _global_entries else 0
    except Exception as _ltm_err:
        logger.debug("derive_memory_bias: LongTermMemory read failed — %s", _ltm_err)

    # ── 3. Task-memory recency (continuity reinforcement) ────────────────────
    try:
        from core.task_memory import get_task_memory as _get_tm
        _tm = _get_tm()
        _recent = _tm.get_recent_summaries(n=10)
        _now = time.time()
        recent_task_count = sum(
            1 for s in (_recent or [])
            if (_now - getattr(s, "timestamp", 0.0)) <= _TASK_MEMORY_RECENCY_WINDOW
        )
    except Exception as _tm_err:
        logger.debug("derive_memory_bias: TaskMemory read failed — %s", _tm_err)

    # ── 4. Compute normalised scores ─────────────────────────────────────────
    continuity_score = _compute_continuity_score(wm_depth, recent_task_count)
    retrieval_relevance = _compute_retrieval_relevance(ltm_depth)
    novelty_factor = max(0.0, 1.0 - continuity_score)

    # ── 5. Classify posture ───────────────────────────────────────────────────
    posture = _classify_posture(continuity_score, retrieval_relevance)

    # ── 6. Determine if memory signals are meaningful ─────────────────────────
    influenced = (wm_depth > 0 or ltm_depth > 0 or recent_task_count > 0)

    logger.debug(
        "MemoryBiasLayer: session=%s wm_depth=%d ltm_depth=%d recent_tasks=%d "
        "continuity=%.3f retrieval=%.3f posture=%s influenced=%s trace_id=%s",
        session_id,
        wm_depth,
        ltm_depth,
        recent_task_count,
        continuity_score,
        retrieval_relevance,
        posture,
        influenced,
        trace_id,
    )

    return MemoryBias(
        posture=posture,
        continuity_score=round(continuity_score, 4),
        retrieval_relevance=round(retrieval_relevance, 4),
        novelty_factor=round(novelty_factor, 4),
        recent_task_count=recent_task_count,
        working_memory_depth=wm_depth,
        long_term_memory_depth=ltm_depth,
        influenced_by_memory=influenced,
        source="memory_bias_layer",
        session_id=session_id,
    )


def _compute_continuity_score(wm_depth: int, recent_task_count: int) -> float:
    """Map working-memory and task-memory depth to a continuity score [0.0, 1.0]."""
    # Working memory is the primary continuity signal
    if wm_depth >= _WM_ENTRIES_HIGH:
        wm_score = 0.8
    elif wm_depth >= _WM_ENTRIES_MED:
        wm_score = 0.5
    elif wm_depth > 0:
        wm_score = 0.25
    else:
        wm_score = 0.0

    # Task memory recency reinforces continuity
    if recent_task_count >= 3:
        task_score = 0.2
    elif recent_task_count >= 1:
        task_score = 0.1
    else:
        task_score = 0.0

    return min(1.0, wm_score + task_score)


def _compute_retrieval_relevance(ltm_depth: int) -> float:
    """Map long-term memory depth to a retrieval relevance score [0.0, 1.0]."""
    if ltm_depth >= _LTM_ENTRIES_HIGH:
        return 0.7
    elif ltm_depth >= _LTM_ENTRIES_MED:
        return 0.35
    else:
        return 0.0


def _classify_posture(continuity_score: float, retrieval_relevance: float) -> str:
    """Classify the memory posture from continuity and retrieval scores."""
    # Continuity takes precedence if score is above threshold
    if continuity_score >= _CONTINUITY_SCORE_HIGH:
        return POSTURE_CONTINUITY
    # Retrieval is secondary
    if retrieval_relevance >= _RETRIEVAL_RELEVANCE_HIGH:
        return POSTURE_RETRIEVAL
    # Default: novelty / low-memory
    return POSTURE_NOVELTY


def _get_memory_planner_guidance_impl(
    *,
    bias: Optional[MemoryBias],
    trace_id: Optional[str],
) -> MemoryPlannerGuidance:
    """Internal implementation of planner guidance derivation."""
    if bias is None:
        return MemoryPlannerGuidance(
            posture=POSTURE_NOVELTY,
            decomposition_hint=DECOMP_HINT_FRESH,
            prefer_single_agent=False,
            complexity_threshold_adjustment=0.0,
            influenced_by_memory=False,
            diagnostic_note="bias is None — no memory influence",
        )

    if not bias.influenced_by_memory:
        return MemoryPlannerGuidance(
            posture=POSTURE_NOVELTY,
            decomposition_hint=DECOMP_HINT_FRESH,
            prefer_single_agent=False,
            complexity_threshold_adjustment=0.0,
            influenced_by_memory=False,
            diagnostic_note="fallback bias — no live memory signals",
        )

    posture = bias.posture

    if posture == POSTURE_CONTINUITY:
        guidance = MemoryPlannerGuidance(
            posture=posture,
            decomposition_hint=DECOMP_HINT_RESUME,
            prefer_single_agent=True,
            # Raise bar slightly for complex multi-agent strategies so that
            # continuity context is preserved in a coherent single-agent path.
            complexity_threshold_adjustment=+0.10,
            influenced_by_memory=True,
            diagnostic_note=(
                f"continuity posture (score={bias.continuity_score:.3f}, "
                f"wm_depth={bias.working_memory_depth}, "
                f"tasks={bias.recent_task_count}) — prefer resume/single-agent"
            ),
        )
    elif posture == POSTURE_RETRIEVAL:
        guidance = MemoryPlannerGuidance(
            posture=posture,
            decomposition_hint=DECOMP_HINT_RECALL,
            prefer_single_agent=False,
            # No complexity threshold adjustment — allow normal strategy
            # selection but flag recall support.
            complexity_threshold_adjustment=0.0,
            influenced_by_memory=True,
            diagnostic_note=(
                f"retrieval posture (relevance={bias.retrieval_relevance:.3f}, "
                f"ltm_depth={bias.long_term_memory_depth}) — recall-supported execution"
            ),
        )
    else:
        # POSTURE_NOVELTY — no bias; return non-influencing guidance.
        guidance = MemoryPlannerGuidance(
            posture=posture,
            decomposition_hint=DECOMP_HINT_FRESH,
            prefer_single_agent=False,
            complexity_threshold_adjustment=0.0,
            influenced_by_memory=True,  # signals present but posture is novelty
            diagnostic_note=(
                f"novelty posture (continuity={bias.continuity_score:.3f}, "
                f"retrieval={bias.retrieval_relevance:.3f}) — fresh handling"
            ),
        )

    logger.debug(
        "MemoryPlannerGuidance: posture=%s decomp=%s prefer_single=%s adj=%.2f trace_id=%s",
        guidance.posture,
        guidance.decomposition_hint,
        guidance.prefer_single_agent,
        guidance.complexity_threshold_adjustment,
        trace_id,
    )
    return guidance
