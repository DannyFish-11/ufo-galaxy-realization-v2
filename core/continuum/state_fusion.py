"""
core.continuum.state_fusion — Unified State Fusion Engine
=========================================================

Merges a :class:`~core.continuum.types.HumanFieldState` with optional
world/system context and recent :class:`~core.continuum.types.UnifiedState`
history into a new :class:`~core.continuum.types.UnifiedState` ready for
the temporal engine and liminal-field computation.

World context is passed as a plain ``dict``; unknown keys are silently
ignored.  All numeric values are clamped to ``[0, 1]``.

Recognised world-context keys
------------------------------
- ``context_utility``  — utility estimate of acting on the current context.
- ``urgency``          — time-sensitivity of potential action.
- ``action_risk``      — estimated risk / irreversibility of acting.
- ``uncertainty``      — model confidence (1.0 = fully uncertain).

Usage::

    from core.continuum.state_fusion import StateFusion
    from core.continuum.types import HumanFieldState

    fusion = StateFusion()
    unified = fusion.fuse(
        human=HumanFieldState(intent_probability=0.7, attention=0.8),
        world={"urgency": 0.6, "context_utility": 0.5},
    )
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import ContinuumPhase, HumanFieldState, UnifiedState


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


# ---------------------------------------------------------------------------
# Fusion engine
# ---------------------------------------------------------------------------


class StateFusion:
    """Fuses :class:`HumanFieldState` + world context + history into
    :class:`UnifiedState`.

    The fusion is **deterministic** and **stateless** with respect to the
    engine object: history is passed in explicitly by the caller so that
    retention policy is controlled upstream.

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

    def fuse(
        self,
        human: HumanFieldState,
        world: Optional[Dict[str, Any]] = None,
        history: Optional[List[UnifiedState]] = None,
    ) -> UnifiedState:
        """Produce a :class:`UnifiedState` from all available inputs.

        Args:
            human:   Current :class:`HumanFieldState` snapshot.
            world:   Optional dict of world/system context signals.
                     Recognised keys: ``context_utility``, ``urgency``,
                     ``action_risk``, ``uncertainty``.
                     Unknown keys are silently ignored.
            history: Optional recent :class:`UnifiedState` history
                     (newest entry last).  Used to derive temporal trend
                     adjustments on utility and urgency.

        Returns:
            :class:`UnifiedState` with all fields populated.
        """
        w: Dict[str, Any] = world or {}

        context_utility = _clamp(float(w.get("context_utility", 0.0)))
        urgency = _clamp(float(w.get("urgency", 0.0)))
        action_risk = _clamp(float(w.get("action_risk", 0.0)))
        uncertainty = _clamp(float(w.get("uncertainty", 0.5)))

        # Apply trend nudges from history when available.
        if history:
            context_utility, urgency = self._apply_history_trend(
                context_utility, urgency, history
            )

        phase_candidate, candidate_confidence = self._infer_phase_candidate(
            human=human,
            context_utility=context_utility,
            urgency=urgency,
            action_risk=action_risk,
            uncertainty=uncertainty,
        )

        return UnifiedState(
            human=human,
            context_utility=context_utility,
            urgency=urgency,
            action_risk=action_risk,
            uncertainty=uncertainty,
            phase_candidate=phase_candidate,
            candidate_confidence=candidate_confidence,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Phase candidate inference
    # ------------------------------------------------------------------

    def _infer_phase_candidate(
        self,
        human: HumanFieldState,
        context_utility: float,
        urgency: float,
        action_risk: float,
        uncertainty: float,
    ) -> Tuple[ContinuumPhase, float]:
        """Suggest a raw phase candidate before temporal filtering.

        This is a heuristic: the
        :class:`~core.continuum.temporal_engine.TemporalEngine` applies
        hysteresis and dwell guards on top.

        Returns:
            ``(phase, confidence)`` tuple where confidence is the raw
            signal strength supporting the candidate phase.
        """
        # Presence signal: combination of intent + attention + utility + urgency.
        presence = _clamp(
            0.40 * human.intent_probability
            + 0.30 * human.attention
            + 0.20 * context_utility
            + 0.10 * urgency
        )

        # Collapse signal: strong intent + high utility + low risk/uncertainty.
        collapse = _clamp(
            0.40 * human.intent_probability
            + 0.30 * context_utility
            + 0.20 * urgency
            - 0.15 * action_risk
            - 0.10 * uncertainty
        )

        # Retreat signal: high risk/uncertainty/fatigue suppresses action.
        retreat = _clamp(
            0.40 * action_risk
            + 0.30 * uncertainty
            + 0.20 * human.fatigue
            - 0.20 * context_utility
        )

        # --- Phase selection -------------------------------------------
        # MANIFEST: collapse is strong, presence is sufficient, retreat low.
        if collapse >= 0.70 and presence >= 0.60 and retreat < 0.40:
            return ContinuumPhase.MANIFEST, _clamp(collapse)

        # LIMINAL: sufficient presence, retreat not dominant.
        if presence >= 0.45 and retreat < 0.50:
            confidence = _clamp((presence - 0.45) / 0.55 + 0.20)
            return ContinuumPhase.LIMINAL, confidence

        # RECEDING: retreat dominates.
        if retreat >= 0.60:
            return ContinuumPhase.RECEDING, _clamp(retreat)

        # FORMLESS: default / low-signal state.
        return ContinuumPhase.FORMLESS, _clamp(1.0 - presence)

    # ------------------------------------------------------------------
    # History trend helper
    # ------------------------------------------------------------------

    def _apply_history_trend(
        self,
        context_utility: float,
        urgency: float,
        history: List[UnifiedState],
        window: int = 5,
    ) -> Tuple[float, float]:
        """Nudge *context_utility* and *urgency* by the recent trend.

        A rising trend amplifies the current value slightly; a falling
        trend suppresses it.  The nudge is capped at ±10 % so that
        history can only refine, not override, the current world context.

        Args:
            context_utility: Current raw context utility value.
            urgency:         Current raw urgency value.
            history:         Recent UnifiedState history, newest last.
            window:          Number of history entries to consider.

        Returns:
            Adjusted ``(context_utility, urgency)`` tuple.
        """
        recent = history[-window:]
        if len(recent) < 2:
            return context_utility, urgency

        utility_delta = (
            recent[-1].context_utility - recent[0].context_utility
        )
        urgency_delta = recent[-1].urgency - recent[0].urgency

        # Small nudge in the direction of the delta (capped at ±10 %).
        adj_utility = _clamp(context_utility + 0.10 * utility_delta)
        adj_urgency = _clamp(urgency + 0.10 * urgency_delta)
        return adj_utility, adj_urgency
