#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.cognitive.memory_runtime_bias
====================================

PR-19 — Memory-Informed Runtime Bias Layer

Canonical bounded memory-bias layer that translates memory-derived
continuity/retrieval/novelty signals into soft, advisory runtime guidance
for:

- planner decomposition style (continuity-aware vs fresh-handling)
- node candidate preference / activation bias
- continuity-vs-fresh handling heuristics in execution paths

Design principles
-----------------
- **Bounded and advisory**: :class:`MemoryBias` and
  :class:`MemoryBiasPlannerHint` are *influence* objects.  They NEVER
  replace lifecycle governance, invocation governance, node
  activation-context readiness (PR-11, PR-14, PR-15 node tracks), or
  explicit user intent.  Hard gates remain fully authoritative.
- **Consumes existing signals**: All memory signals are read from
  already-available sources (:class:`~core.task_memory.TaskMemory`,
  :class:`~core.cognitive.working_memory.WorkingMemory`,
  :class:`~core.cognitive.long_term_memory.LongTermMemory`).  This
  module never starts a new memory pipeline.
- **Three distinct postures**: The bias layer distinguishes:
  - ``continuity_seeking``  — prior context is dense/relevant; prefer
    continuity-aware execution with resume/recall support.
  - ``retrieval_seeking``   — prior context exists but may need
    explicit recall or retrieval-augmented support.
  - ``novelty``             — low or empty memory state; prefer fresh,
    context-free handling.
- **Explicit non-authority**: Memory bias cannot override invocation
  governance, activation readiness, explicit user task semantics, or
  lifecycle-denial decisions.
- **Diagnostics**: All influence decisions are logged with the posture
  inferred, where it influenced behavior, and whether hard gates
  overrode that influence.

Authority sentinels
-------------------
MEMORY_RUNTIME_BIAS_IS_AUTHORITY
    Asserts this module is the canonical memory-bias layer (PR-19).

MEMORY_RUNTIME_BIAS_PR19_SENTINEL
    Machine-checkable sentinel confirming the memory-bias layer is present.

Usage::

    from core.cognitive.memory_runtime_bias import (
        derive_memory_bias,
        get_memory_planner_hint,
        build_memory_bias_diagnostics,
        MemoryBias,
        MemoryBiasPlannerHint,
        MemoryPosture,
    )

    bias = derive_memory_bias(session_id="sess_abc")
    hint = get_memory_planner_hint(bias)
    print(hint.posture)          # "continuity_seeking" | "retrieval_seeking" | "novelty"
    print(hint.prefer_continuity_strategy)   # True / False
    diag = build_memory_bias_diagnostics(bias, influenced=True, influence_surface="planner_strategy")
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
    "core.cognitive.memory_runtime_bias is the canonical memory-informed "
    "runtime bias layer for PR-19.  It translates memory-derived "
    "continuity/retrieval/novelty signals into bounded MemoryBias and "
    "MemoryBiasPlannerHint objects.  It does not replace lifecycle governance, "
    "invocation governance, node activation-context readiness checks, or "
    "explicit user intent.  Hard gates remain fully authoritative."
)

MEMORY_RUNTIME_BIAS_PR19_SENTINEL: str = (
    "MEMORY_RUNTIME_BIAS::PR19_SENTINEL: "
    "Memory-informed runtime bias (PR-19) is present and active.  "
    "MemoryBias is derived from available TaskMemory/WorkingMemory/LongTermMemory "
    "signals and wired into ExecutionPlanner strategy selection and kernel "
    "execution handling.  Hard governance gates are unaffected."
)

# Policy sentinels
HARD_GATES_OVERRIDE_MEMORY_BIAS_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_1: "
    "Hard gates (lifecycle governance, invocation governance, node "
    "activation-context readiness, explicit user intent) are ALWAYS "
    "authoritative.  MemoryBias is a soft influence layer that operates "
    "alongside hard gates, never replacing them."
)

MEMORY_BIAS_IS_ADVISORY_NOT_AUTHORITY_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_2: "
    "MemoryBias is bounded, explainable, and advisory.  It biases runtime "
    "preferences rather than commanding them.  Consumers MUST NOT treat it "
    "as a hard eligibility gate.  A posture of 'novelty' does not mean no "
    "memory support — it means prefer fresh handling over continuity assumptions."
)

MEMORY_BIAS_DERIVED_FROM_EXISTING_SIGNALS_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_3: "
    "MemoryBias is always derived from already-available memory/context signals "
    "(TaskMemory, WorkingMemory, LongTermMemory).  No new memory pipeline is "
    "started; the bias re-uses existing memory infrastructure."
)

EXPLICIT_USER_INTENT_REMAINS_PRIMARY_POLICY: str = (
    "MEMORY_RUNTIME_BIAS::POLICY_4: "
    "Explicit user intent and current-turn task semantics remain primary.  "
    "Memory bias is subordinate to explicit instructions, live task semantics, "
    "and hard governance decisions.  Memory cannot silently override user intent."
)


# ---------------------------------------------------------------------------
# MemoryPosture enum
# ---------------------------------------------------------------------------


class MemoryPosture(str, Enum):
    """Three broad memory postures that can be inferred from memory signals.

    Attributes
    ----------
    CONTINUITY_SEEKING:
        Prior context is dense and relevant; the system should favor
        continuity-aware execution — resume prior context, leverage
        accumulated session state, prefer recall-supported strategies.
    RETRIEVAL_SEEKING:
        Prior context exists but the current request may require explicit
        retrieval or recall support; bias planner toward retrieval-augmented
        or memory-consulting execution.
    NOVELTY:
        Memory state is sparse, empty, or not relevant to the current
        request; prefer fresh, context-free handling without unnecessary
        continuity assumptions.
    """

    CONTINUITY_SEEKING = "continuity_seeking"
    RETRIEVAL_SEEKING = "retrieval_seeking"
    NOVELTY = "novelty"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Memory density thresholds for posture classification
_CONTINUITY_DENSITY_THRESHOLD: float = 0.6  # >= this → continuity_seeking
_RETRIEVAL_DENSITY_THRESHOLD: float = 0.2   # >= this → retrieval_seeking; < → novelty

# Recency weights: recent entries are weighted more heavily
_RECENCY_WINDOW_SECONDS: float = 3600.0  # 1 hour = "recent"

# Complexity adjustment hints per posture (applied as advisory offsets)
# continuity_seeking: slightly lower complexity threshold → favor richer strategies
# retrieval_seeking:  slight increase → favor single-agent but include retrieval tool
# novelty:            no adjustment  → default planner thresholds unchanged
_COMPLEXITY_ADJ_CONTINUITY: float = -0.05
_COMPLEXITY_ADJ_RETRIEVAL: float = 0.05
_COMPLEXITY_ADJ_NOVELTY: float = 0.0


# ---------------------------------------------------------------------------
# MemoryBias dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBias:
    """Bounded, advisory memory bias derived from available memory signals.

    This dataclass is the canonical output of :func:`derive_memory_bias`.
    All fields have safe defaults; consumers must never assume any field
    is non-None.

    Attributes
    ----------
    posture:
        The inferred memory posture:
        ``"continuity_seeking"`` / ``"retrieval_seeking"`` / ``"novelty"``.
    memory_density:
        Normalised [0.0, 1.0] signal density derived from recent memory
        entries.  0.0 = empty/no memory; 1.0 = highly dense/relevant.
    recent_entry_count:
        Count of recent in-window memory entries used to derive the posture.
    total_entry_count:
        Total memory entries considered (including out-of-window entries).
    session_continuity_score:
        Float [0.0, 1.0] representing session-level continuity strength.
        Derived from working-memory entry count and recency.
    has_long_term_context:
        True when the long-term memory store has relevant cross-session
        entries that could inform the current request.
    influenced_by_memory:
        Always True when returned by :func:`derive_memory_bias` from live
        memory; False for the fallback bias.
    source:
        ``"memory_runtime_bias"`` when derived from live signals;
        ``"fallback"`` otherwise.
    timestamp:
        Unix epoch at bias derivation time.
    diagnostic_note:
        Human-readable note explaining the posture decision.
    """

    posture: str = MemoryPosture.NOVELTY.value
    memory_density: float = 0.0
    recent_entry_count: int = 0
    total_entry_count: int = 0
    session_continuity_score: float = 0.0
    has_long_term_context: bool = False
    influenced_by_memory: bool = False
    source: str = "fallback"
    timestamp: float = field(default_factory=time.time)
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "memory_density": round(self.memory_density, 4),
            "recent_entry_count": self.recent_entry_count,
            "total_entry_count": self.total_entry_count,
            "session_continuity_score": round(self.session_continuity_score, 4),
            "has_long_term_context": self.has_long_term_context,
            "influenced_by_memory": self.influenced_by_memory,
            "source": self.source,
            "timestamp": self.timestamp,
            "diagnostic_note": self.diagnostic_note,
        }

    def is_continuity_seeking(self) -> bool:
        """Return True when posture is continuity_seeking."""
        return self.posture == MemoryPosture.CONTINUITY_SEEKING.value

    def is_retrieval_seeking(self) -> bool:
        """Return True when posture is retrieval_seeking."""
        return self.posture == MemoryPosture.RETRIEVAL_SEEKING.value

    def is_novelty(self) -> bool:
        """Return True when posture is novelty."""
        return self.posture == MemoryPosture.NOVELTY.value


# ---------------------------------------------------------------------------
# Fallback bias (safe default when memory signals are unavailable)
# ---------------------------------------------------------------------------

FALLBACK_MEMORY_BIAS: MemoryBias = MemoryBias(
    posture=MemoryPosture.NOVELTY.value,
    memory_density=0.0,
    recent_entry_count=0,
    total_entry_count=0,
    session_continuity_score=0.0,
    has_long_term_context=False,
    influenced_by_memory=False,
    source="fallback",
    diagnostic_note="memory_signals_unavailable: using novelty fallback",
)


# ---------------------------------------------------------------------------
# MemoryBiasPlannerHint dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MemoryBiasPlannerHint:
    """Planner-consumable memory bias hint derived from a :class:`MemoryBias`.

    This dataclass is the canonical output of :func:`get_memory_planner_hint`.

    Attributes
    ----------
    posture:
        The memory posture string (``"continuity_seeking"`` /
        ``"retrieval_seeking"`` / ``"novelty"``).
    prefer_continuity_strategy:
        When True, the planner should prefer strategies that leverage
        prior context (resume, recall-augmented, specialized teams with
        memory access).
    prefer_retrieval_support:
        When True, the planner should consider including retrieval or
        recall-augmented tooling in the execution path.
    complexity_threshold_adjustment:
        Float offset applied to existing complexity thresholds (advisory).
        Negative values slightly lower the bar for richer strategies when
        continuity is strong; positive values slightly raise the bar to
        avoid over-engineering fresh-start tasks.
    session_continuity_score:
        The underlying session-continuity score [0.0, 1.0].
    influenced_by_memory:
        True when this hint was derived from an active memory signal
        (not fallback).
    diagnostic_note:
        Human-readable note explaining the hint decision.
    """

    posture: str = MemoryPosture.NOVELTY.value
    prefer_continuity_strategy: bool = False
    prefer_retrieval_support: bool = False
    complexity_threshold_adjustment: float = 0.0
    session_continuity_score: float = 0.0
    influenced_by_memory: bool = False
    diagnostic_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "posture": self.posture,
            "prefer_continuity_strategy": self.prefer_continuity_strategy,
            "prefer_retrieval_support": self.prefer_retrieval_support,
            "complexity_threshold_adjustment": round(
                self.complexity_threshold_adjustment, 4
            ),
            "session_continuity_score": round(self.session_continuity_score, 4),
            "influenced_by_memory": self.influenced_by_memory,
            "diagnostic_note": self.diagnostic_note,
        }


# ---------------------------------------------------------------------------
# Core derivation: memory signals → MemoryBias
# ---------------------------------------------------------------------------


def derive_memory_bias(
    session_id: str = "",
    *,
    trace_id: Optional[str] = None,
    task_memory: Optional[Any] = None,
    working_memory: Optional[Any] = None,
    long_term_memory: Optional[Any] = None,
) -> MemoryBias:
    """Derive a :class:`MemoryBias` from available memory/context signals.

    Parameters
    ----------
    session_id:
        The current session identifier.  Used to scope working-memory
        queries and continuity scoring.
    trace_id:
        Optional correlation ID for log entries.
    task_memory:
        Optional :class:`~core.task_memory.TaskMemory` instance for
        injection.  When None, the module attempts to load the process
        singleton via ``core.task_memory.get_task_memory()``.
    working_memory:
        Optional :class:`~core.cognitive.working_memory.WorkingMemory`
        instance.  When None, the module attempts to load via
        ``core.cognitive.working_memory.get_working_memory()``.
    long_term_memory:
        Optional :class:`~core.cognitive.long_term_memory.LongTermMemory`
        instance.  When None, the module attempts to load via
        ``core.cognitive.long_term_memory.get_long_term_memory()``.

    Returns
    -------
    MemoryBias
        A bounded, advisory memory bias.  Never raises — returns
        :data:`FALLBACK_MEMORY_BIAS` on any error.
    """
    try:
        return _derive_bias_impl(
            session_id=session_id,
            trace_id=trace_id,
            task_memory=task_memory,
            working_memory=working_memory,
            long_term_memory=long_term_memory,
        )
    except Exception as exc:
        logger.debug(
            "derive_memory_bias: error (trace_id=%s session=%s): %s — returning fallback",
            trace_id,
            session_id,
            exc,
        )
        return FALLBACK_MEMORY_BIAS


def _derive_bias_impl(
    *,
    session_id: str,
    trace_id: Optional[str],
    task_memory: Optional[Any],
    working_memory: Optional[Any],
    long_term_memory: Optional[Any],
) -> MemoryBias:
    """Internal implementation of memory bias derivation."""
    now = time.time()

    # ── 1. Collect TaskMemory signals ──────────────────────────────────────
    recent_task_count = 0
    total_task_count = 0
    _tm = task_memory
    if _tm is None:
        try:
            from core.task_memory import get_task_memory as _gtm
            _tm = _gtm()
        except Exception:
            _tm = None

    if _tm is not None:
        try:
            recent_summaries = _tm.get_recent_summaries(20)
            total_task_count = len(recent_summaries)
            # Count entries within the recency window
            recent_task_count = sum(
                1 for s in recent_summaries
                if (now - getattr(s, "timestamp", 0)) <= _RECENCY_WINDOW_SECONDS
            )
        except Exception as _e:
            logger.debug("derive_memory_bias: task_memory read error: %s", _e)

    # ── 2. Collect WorkingMemory signals ────────────────────────────────────
    working_entry_count = 0
    working_recency_score = 0.0
    _wm = working_memory
    if _wm is None:
        try:
            from core.cognitive.working_memory import get_working_memory as _gwm
            _wm = _gwm()
        except Exception:
            _wm = None

    if _wm is not None and session_id:
        try:
            wm_entries = _wm.get(session_id=session_id)
            working_entry_count = len(wm_entries)
            if working_entry_count > 0:
                # Score by recency: entries within window contribute fully
                _within = sum(
                    1 for e in wm_entries
                    if (now - getattr(e, "timestamp", 0)) <= _RECENCY_WINDOW_SECONDS
                )
                working_recency_score = _within / max(working_entry_count, 1)
        except Exception as _e:
            logger.debug("derive_memory_bias: working_memory read error: %s", _e)

    # ── 3. Collect LongTermMemory signals ────────────────────────────────────
    has_long_term_ctx = False
    _ltm = long_term_memory
    if _ltm is None:
        try:
            from core.cognitive.long_term_memory import get_long_term_memory as _gltm
            _ltm = _gltm()
        except Exception:
            _ltm = None

    if _ltm is not None:
        try:
            _ltm_entries = _ltm.retrieve_all()
            has_long_term_ctx = len(_ltm_entries) > 0
        except Exception as _e:
            logger.debug("derive_memory_bias: long_term_memory read error: %s", _e)

    # ── 4. Compute combined memory density ─────────────────────────────────
    # Memory density is a normalised [0, 1] signal:
    # - 50% weight on recent_task_count (normalised against a ceiling of 10)
    # - 30% weight on working_memory recency score
    # - 20% weight on working_entry_count (normalised against ceiling of 5)
    _task_density = min(recent_task_count / 10.0, 1.0) * 0.50
    _wm_recency = working_recency_score * 0.30
    _wm_density = min(working_entry_count / 5.0, 1.0) * 0.20
    memory_density = round(_task_density + _wm_recency + _wm_density, 4)

    # ── 5. Classify posture ─────────────────────────────────────────────────
    if memory_density >= _CONTINUITY_DENSITY_THRESHOLD:
        posture = MemoryPosture.CONTINUITY_SEEKING
        note = (
            f"memory_density={memory_density:.3f} "
            f"(recent_tasks={recent_task_count}, working={working_entry_count}): "
            "dense prior context — continuity-seeking posture"
        )
    elif memory_density >= _RETRIEVAL_DENSITY_THRESHOLD:
        posture = MemoryPosture.RETRIEVAL_SEEKING
        note = (
            f"memory_density={memory_density:.3f} "
            f"(recent_tasks={recent_task_count}, working={working_entry_count}): "
            "moderate prior context — retrieval-seeking posture"
        )
    else:
        posture = MemoryPosture.NOVELTY
        note = (
            f"memory_density={memory_density:.3f} "
            f"(recent_tasks={recent_task_count}, working={working_entry_count}): "
            "sparse prior context — novelty posture"
        )

    # Session continuity score: blend working recency + task density
    session_continuity_score = round(
        working_recency_score * 0.6 + min(recent_task_count / 10.0, 1.0) * 0.4, 4
    )

    logger.debug(
        "MemoryRuntimeBias: posture=%s density=%.3f "
        "recent_tasks=%d working=%d ltm=%s session=%s trace_id=%s",
        posture.value,
        memory_density,
        recent_task_count,
        working_entry_count,
        has_long_term_ctx,
        session_id,
        trace_id,
    )

    return MemoryBias(
        posture=posture.value,
        memory_density=memory_density,
        recent_entry_count=recent_task_count,
        total_entry_count=total_task_count,
        session_continuity_score=session_continuity_score,
        has_long_term_context=has_long_term_ctx,
        influenced_by_memory=True,
        source="memory_runtime_bias",
        diagnostic_note=note,
    )


# ---------------------------------------------------------------------------
# MemoryBiasPlannerHint derivation
# ---------------------------------------------------------------------------


def get_memory_planner_hint(
    bias: Optional[MemoryBias],
    *,
    trace_id: Optional[str] = None,
) -> MemoryBiasPlannerHint:
    """Translate a :class:`MemoryBias` into a :class:`MemoryBiasPlannerHint`.

    Parameters
    ----------
    bias:
        A :class:`MemoryBias` or ``None``.
    trace_id:
        Optional correlation ID for log entries.

    Returns
    -------
    MemoryBiasPlannerHint
        Planner guidance derived from the bias.  Never raises.
    """
    try:
        if bias is None or not bias.influenced_by_memory:
            return MemoryBiasPlannerHint(
                posture=MemoryPosture.NOVELTY.value,
                prefer_continuity_strategy=False,
                prefer_retrieval_support=False,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_NOVELTY,
                session_continuity_score=0.0,
                influenced_by_memory=False,
                diagnostic_note="memory_bias_unavailable: using novelty fallback hint",
            )

        posture = bias.posture

        if posture == MemoryPosture.CONTINUITY_SEEKING.value:
            note = (
                f"memory_density={bias.memory_density:.3f} "
                f"(session_continuity={bias.session_continuity_score:.3f}): "
                "continuity-seeking — prefer continuity-aware strategy, "
                "leverage prior context"
            )
            return MemoryBiasPlannerHint(
                posture=posture,
                prefer_continuity_strategy=True,
                prefer_retrieval_support=bias.has_long_term_context,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_CONTINUITY,
                session_continuity_score=bias.session_continuity_score,
                influenced_by_memory=True,
                diagnostic_note=note,
            )
        elif posture == MemoryPosture.RETRIEVAL_SEEKING.value:
            note = (
                f"memory_density={bias.memory_density:.3f} "
                f"(session_continuity={bias.session_continuity_score:.3f}): "
                "retrieval-seeking — support retrieval/recall tooling, "
                "moderate strategy preference"
            )
            return MemoryBiasPlannerHint(
                posture=posture,
                prefer_continuity_strategy=False,
                prefer_retrieval_support=True,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_RETRIEVAL,
                session_continuity_score=bias.session_continuity_score,
                influenced_by_memory=True,
                diagnostic_note=note,
            )
        else:  # novelty
            note = (
                f"memory_density={bias.memory_density:.3f} "
                f"(session_continuity={bias.session_continuity_score:.3f}): "
                "novelty — fresh handling, no continuity assumptions"
            )
            return MemoryBiasPlannerHint(
                posture=posture,
                prefer_continuity_strategy=False,
                prefer_retrieval_support=False,
                complexity_threshold_adjustment=_COMPLEXITY_ADJ_NOVELTY,
                session_continuity_score=bias.session_continuity_score,
                influenced_by_memory=True,
                diagnostic_note=note,
            )
    except Exception as exc:
        logger.debug("get_memory_planner_hint: error: %s", exc)
        return MemoryBiasPlannerHint(
            posture=MemoryPosture.NOVELTY.value,
            prefer_continuity_strategy=False,
            prefer_retrieval_support=False,
            complexity_threshold_adjustment=_COMPLEXITY_ADJ_NOVELTY,
            session_continuity_score=0.0,
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
    override_reason: str = "",
) -> Dict[str, Any]:
    """Build a diagnostics dict for surfacing memory bias decisions.

    Parameters
    ----------
    bias:
        The :class:`MemoryBias` instance (or None).
    influenced:
        Whether memory bias actually influenced a runtime decision.
    influence_surface:
        Human-readable identifier of the surface where the bias was applied
        (e.g. ``"planner_strategy"``, ``"kernel_process"``).
    hard_gate_overrode:
        True when a hard governance gate overrode the memory bias influence.
    override_reason:
        Optional reason string when ``hard_gate_overrode`` is True.

    Returns
    -------
    Dict[str, Any]
        A JSON-safe diagnostics dict.
    """
    if bias is None:
        return {
            "memory_bias_available": False,
            "posture": MemoryPosture.NOVELTY.value,
            "memory_density": 0.0,
            "influenced": False,
            "influence_surface": influence_surface or "none",
            "hard_gate_overrode": False,
            "override_reason": "",
            "source": "fallback",
        }
    return {
        "memory_bias_available": True,
        "posture": bias.posture,
        "memory_density": round(bias.memory_density, 4),
        "recent_entry_count": bias.recent_entry_count,
        "total_entry_count": bias.total_entry_count,
        "session_continuity_score": round(bias.session_continuity_score, 4),
        "has_long_term_context": bias.has_long_term_context,
        "influenced_by_memory": bias.influenced_by_memory,
        "influenced": influenced,
        "influence_surface": influence_surface or "none",
        "hard_gate_overrode": hard_gate_overrode,
        "override_reason": override_reason,
        "source": bias.source,
        "diagnostic_note": bias.diagnostic_note,
    }
