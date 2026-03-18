"""
core.continuum.liminal_field — Liminal Field Engine
====================================================

Computes liminal-state metrics from a :class:`~core.continuum.types.UnifiedState`
and optional recent history.

Metrics
-------
- ``coherence``           — degree to which signals form a coherent intent
                            ``[0, 1]``.
- ``ambiguity``           — unresolved signal uncertainty / conflict ``[0, 1]``.
- ``collapse_tendency``   — probability mass pushing toward
                            liminal → manifest ``[0, 1]``.
- ``intervention_window`` — openness of the system intervention window
                            ``[0, 1]``.

All values are bounded in ``[0, 1]``.

Usage::

    from core.continuum.liminal_field import LiminalFieldEngine, LiminalMetrics
    from core.continuum.types import UnifiedState, HumanFieldState

    engine = LiminalFieldEngine()

    state = UnifiedState(
        human=HumanFieldState(intent_probability=0.8, attention=0.75),
        context_utility=0.6,
        uncertainty=0.2,
    )
    metrics = engine.compute(state)
    print(metrics.coherence, metrics.collapse_tendency)

    # Optionally enrich the UnifiedState phase_candidate:
    enriched = engine.enrich_unified(state, metrics)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import ContinuumPhase, UnifiedState


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Metrics dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LiminalMetrics:
    """Immutable snapshot of liminal-field metrics for one evaluation cycle.

    All values are in ``[0, 1]``.
    """

    coherence: float
    """How well the current signals align toward a single intent.
    High coherence → signals are mutually reinforcing."""

    ambiguity: float
    """Degree of unresolved signal conflict or low-evidence state.
    High ambiguity → intent direction is unclear.
    Typically ≈ 1 − coherence, but may diverge when high intent_probability
    co-occurs with high action_risk (intent and risk both elevated)."""

    collapse_tendency: float
    """Momentum toward phase collapse (liminal → manifest).
    High when coherence is strong and interruption sensitivity is low."""

    intervention_window: float
    """Openness of the system intervention window.
    High → now is a good time for the system to introduce a signal.
    Narrows with high interruption_sensitivity or active speech."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class LiminalFieldEngine:
    """Computes :class:`LiminalMetrics` from a :class:`~core.continuum.types.UnifiedState`.

    The engine is **stateless**: it does not accumulate history across
    calls.  History is passed in explicitly so that retention policy is
    controlled upstream.

    Args:
        config: Continuum configuration.  Defaults to
            :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
    """

    def __init__(
        self, config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG
    ) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(
        self,
        state: UnifiedState,
        history: Optional[List[UnifiedState]] = None,
    ) -> LiminalMetrics:
        """Compute :class:`LiminalMetrics` for the given *state*.

        Args:
            state:   Current fused state (output of
                     :class:`~core.continuum.state_fusion.StateFusion`).
            history: Optional recent history (newest entry last).
                     Used to compute a temporal stability bonus on
                     coherence when intent is trending upward.

        Returns:
            Immutable :class:`LiminalMetrics` snapshot.
        """
        coherence = self._compute_coherence(state, history)
        ambiguity = self._compute_ambiguity(state, coherence)
        collapse_tendency = self._compute_collapse_tendency(state, coherence)
        intervention_window = self._compute_intervention_window(
            state, coherence, collapse_tendency
        )

        return LiminalMetrics(
            coherence=_clamp(coherence),
            ambiguity=_clamp(ambiguity),
            collapse_tendency=_clamp(collapse_tendency),
            intervention_window=_clamp(intervention_window),
        )

    def enrich_unified(
        self,
        state: UnifiedState,
        metrics: LiminalMetrics,
    ) -> UnifiedState:
        """Return a copy of *state* with ``phase_candidate`` updated from
        liminal metrics.

        If ``collapse_tendency`` exceeds the
        :attr:`~core.continuum.config.HysteresisConfig.manifest_enter`
        threshold the candidate is upgraded to
        :attr:`~core.continuum.types.ContinuumPhase.MANIFEST`; otherwise
        ``candidate_confidence`` is aligned to ``coherence``.

        Args:
            state:   Original :class:`UnifiedState`.
            metrics: Previously computed :class:`LiminalMetrics`.

        Returns:
            Updated :class:`UnifiedState` (new object; *state* is unchanged).
        """
        if (
            metrics.collapse_tendency
            >= self._cfg.hysteresis.manifest_enter
            and state.phase_candidate != ContinuumPhase.MANIFEST
        ):
            return state.model_copy(
                update={
                    "phase_candidate": ContinuumPhase.MANIFEST,
                    "candidate_confidence": metrics.collapse_tendency,
                }
            )
        return state.model_copy(
            update={"candidate_confidence": metrics.coherence}
        )

    # ------------------------------------------------------------------
    # Metric computation helpers
    # ------------------------------------------------------------------

    def _compute_coherence(
        self,
        state: UnifiedState,
        history: Optional[List[UnifiedState]],
    ) -> float:
        """Coherence = alignment of intent-bearing signals.

        Combines:
        - ``intent_probability × attention`` — core alignment between
          human intent and their directed attention.
        - ``context_utility`` — world context aligns with the intent.
        - ``1 − uncertainty`` — low uncertainty reinforces coherence.
        - ``focus_level`` — depth of engagement amplifies coherence.
        - Temporal trend bonus when recent history shows rising intent.
        """
        h = state.human

        core = _clamp(h.intent_probability * h.attention)
        context_align = _clamp(core * state.context_utility)
        certainty = 1.0 - state.uncertainty

        coherence = _clamp(
            0.40 * core
            + 0.30 * context_align
            + 0.20 * certainty
            + 0.10 * _clamp(h.focus_level)
        )

        # Temporal stability bonus: rising intent trend → small coherence lift.
        if history and len(history) >= 2:
            trend = self._intent_trend(history)
            if trend > 0.0:
                coherence = _clamp(coherence + 0.10 * trend)

        return coherence

    def _compute_ambiguity(
        self, state: UnifiedState, coherence: float
    ) -> float:
        """Ambiguity = unresolved uncertainty and signal conflict.

        Pure complement is ``1 − coherence``.  A conflict term is added
        when both ``intent_probability`` and ``action_risk`` are elevated
        (the human wants to act but the context is risky — an inherently
        ambiguous situation).
        """
        base_ambiguity = 1.0 - coherence
        h = state.human
        conflict = _clamp(h.intent_probability * state.action_risk)
        return _clamp(0.70 * base_ambiguity + 0.30 * conflict)

    def _compute_collapse_tendency(
        self, state: UnifiedState, coherence: float
    ) -> float:
        """Collapse tendency = readiness to commit to the manifest phase.

        Requires high coherence, low interruption sensitivity, and low
        action risk.  Urgency provides a supplemental boost.
        """
        h = state.human
        readiness = (
            coherence
            * (1.0 - h.interruption_sensitivity)
            * (1.0 - state.action_risk)
        )
        urgency_boost = _clamp(state.urgency * 0.30)
        return _clamp(readiness + urgency_boost)

    def _compute_intervention_window(
        self,
        state: UnifiedState,
        coherence: float,
        collapse_tendency: float,
    ) -> float:
        """Intervention window = how open the system action window is.

        The window is open when intent is forming, the human is not
        speaking, interruption sensitivity is moderate, and coherence
        is sufficient.

        The window narrows with active speech (hard interrupt) or peak
        interruption sensitivity.
        """
        h = state.human

        # Active speech is a hard interrupt — strong window penalty.
        speaking_penalty = 0.60 if h.speaking else 0.00
        sensitivity_penalty = h.interruption_sensitivity * 0.40

        base = _clamp(
            0.40 * h.intent_probability
            + 0.30 * coherence
            + 0.20 * (1.0 - h.fatigue)
            + 0.10 * collapse_tendency
        )

        return _clamp(base - speaking_penalty - sensitivity_penalty)

    # ------------------------------------------------------------------
    # History helpers
    # ------------------------------------------------------------------

    def _intent_trend(
        self, history: List[UnifiedState], window: int = 5
    ) -> float:
        """Normalised upward trend in ``intent_probability`` over history.

        Returns a value in ``[0, 1]``.  Negative trends are treated as
        zero (no coherence boost for falling intent).  A swing of 0.5
        over the window maps to a trend of 1.0.

        Args:
            history: History list, newest entry last.
            window:  Number of entries to consider.

        Returns:
            Trend magnitude in ``[0, 1]``; 0 for flat or falling intent.
        """
        recent = history[-window:]
        if len(recent) < 2:
            return 0.0

        delta = (
            recent[-1].human.intent_probability
            - recent[0].human.intent_probability
        )
        if delta <= 0.0:
            return 0.0
        # A delta of 0.5 across the window = full trend signal.
        return _clamp(delta * 2.0)
