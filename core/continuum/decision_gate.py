"""
core.continuum.decision_gate — Decision Gate Engine
====================================================

Evaluates whether and how strongly the system should act on the current
state by computing::

    should_act_score = value - interruption_cost - risk_cost

where::

    value             = intent_probability × context_utility × urgency
    interruption_cost = interruption_sensitivity × focus_level × timing_penalty
    risk_cost         = action_risk × uncertainty

The gate maps the score to a graduated :class:`~core.continuum.types.ActionLevel`:

    +--------------+---------------------+
    | Score range  | ActionLevel         |
    +==============+=====================+
    | < 0.15       | observe             |
    +--------------+---------------------+
    | 0.15 – 0.40  | hint                |
    +--------------+---------------------+
    | 0.40 – 0.65  | assist              |
    +--------------+---------------------+
    | ≥ 0.65       | execute             |
    +--------------+---------------------+

Thresholds are configurable via
:class:`~core.continuum.config.ContinuumConfig`.

Usage::

    from core.continuum.decision_gate import DecisionGate
    from core.continuum.types import UnifiedState, HumanFieldState

    gate = DecisionGate()

    state = UnifiedState(
        human=HumanFieldState(
            intent_probability=0.8,
            focus_level=0.4,
            interruption_sensitivity=0.3,
        ),
        context_utility=0.7,
        urgency=0.6,
        action_risk=0.2,
        uncertainty=0.25,
    )
    decision = gate.evaluate(state)
    print(decision.action_level, decision.should_act_score)
"""

from __future__ import annotations

import time
from typing import Optional

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import ActionLevel, DecisionState, UnifiedState


# ---------------------------------------------------------------------------
# Default action-level thresholds
# ---------------------------------------------------------------------------

_THRESHOLD_HINT: float = 0.15
"""Minimum should_act_score to move from *observe* to *hint*."""

_THRESHOLD_ASSIST: float = 0.40
"""Minimum should_act_score to move from *hint* to *assist*."""

_THRESHOLD_EXECUTE: float = 0.65
"""Minimum should_act_score to move from *assist* to *execute*."""

_TIMING_PENALTY_DEFAULT: float = 0.5
"""Default timing penalty used when no explicit urgency/rhythm context is
provided.  This value represents a neutral (neither rushed nor idle) moment.
The penalty is subtracted from the raw interruption term so that a fully
neutral timing reduces interruption cost moderately."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


def _action_level_from_score(score: float) -> ActionLevel:
    """Map a *should_act_score* to a graduated :class:`ActionLevel`."""
    if score >= _THRESHOLD_EXECUTE:
        return ActionLevel.EXECUTE
    if score >= _THRESHOLD_ASSIST:
        return ActionLevel.ASSIST
    if score >= _THRESHOLD_HINT:
        return ActionLevel.HINT
    return ActionLevel.OBSERVE


def _build_reason(
    action_level: ActionLevel,
    score: float,
    value: float,
    interruption_cost: float,
    risk_cost: float,
) -> str:
    """Generate a human-readable explanation for the gate decision."""
    parts = [
        f"score={score:.3f}",
        f"value={value:.3f}",
        f"interruption_cost={interruption_cost:.3f}",
        f"risk_cost={risk_cost:.3f}",
    ]
    base = f"action_level={action_level.value} ({', '.join(parts)})"

    if action_level == ActionLevel.OBSERVE:
        return f"{base}; net score below hint threshold, monitoring only"
    if action_level == ActionLevel.HINT:
        return f"{base}; low-interruption ambient signal appropriate"
    if action_level == ActionLevel.ASSIST:
        return f"{base}; proactive partial engagement warranted"
    return f"{base}; full action cleared by decision gate"


def _confidence_from_score(score: float) -> float:
    """Derive decision confidence from the distance to the nearest threshold.

    Confidence is highest when the score is well above or well below a
    threshold boundary, and lowest when it sits right on the edge.
    """
    thresholds = [0.0, _THRESHOLD_HINT, _THRESHOLD_ASSIST, _THRESHOLD_EXECUTE, 1.0]
    min_dist = min(abs(score - t) for t in thresholds)
    # Map to [0, 1]: a distance of 0.125 (half-band) → confidence 1.0.
    return _clamp(min_dist / 0.125)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class DecisionGate:
    """Evaluates whether and how the system should act given the current state.

    The gate is **stateless** — it computes a fresh
    :class:`~core.continuum.types.DecisionState` on every call to
    :meth:`evaluate`.  No history is accumulated.

    Args:
        config:           Continuum configuration.  Defaults to
                          :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
        timing_penalty:   Base timing penalty applied to the interruption-cost
                          term.  Range ``[0, 1]``.  Higher values increase
                          interruption cost even when ``interruption_sensitivity``
                          is moderate.  Defaults to ``0.5``.
    """

    def __init__(
        self,
        config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG,
        *,
        timing_penalty: float = _TIMING_PENALTY_DEFAULT,
    ) -> None:
        self._cfg = config
        self._timing_penalty = _clamp(timing_penalty)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        state: UnifiedState,
        *,
        timing_penalty: Optional[float] = None,
    ) -> DecisionState:
        """Compute a :class:`~core.continuum.types.DecisionState` for *state*.

        Args:
            state:          Current fused state (output of
                            :class:`~core.continuum.state_fusion.StateFusion`
                            or equivalent).
            timing_penalty: Per-call override for the timing penalty.  When
                            ``None``, the instance-level default is used.

        Returns:
            Immutable :class:`~core.continuum.types.DecisionState` snapshot.
            All values are bounded in ``[0, 1]`` where applicable.
        """
        tp = _clamp(timing_penalty) if timing_penalty is not None else self._timing_penalty

        value = self._compute_value(state)
        interruption_cost = self._compute_interruption_cost(state, tp)
        risk_cost = self._compute_risk_cost(state)

        raw_score = value - interruption_cost - risk_cost
        should_act_score = _clamp(raw_score)

        action_level = _action_level_from_score(should_act_score)
        decision_confidence = _confidence_from_score(should_act_score)
        decision_reason = _build_reason(
            action_level, should_act_score, value, interruption_cost, risk_cost
        )

        return DecisionState(
            should_act_score=should_act_score,
            action_level=action_level,
            decision_reason=decision_reason,
            decision_confidence=decision_confidence,
            value_score=value,
            interruption_cost=interruption_cost,
            risk_cost=risk_cost,
            timestamp=time.time(),
        )

    # ------------------------------------------------------------------
    # Component computations
    # ------------------------------------------------------------------

    def _compute_value(self, state: UnifiedState) -> float:
        """Compute the *value* component of the gate formula.

        ``value = intent_probability × context_utility × urgency``

        A non-zero floor (``0.05``) is added so that even dormant states
        produce a minimal positive value signal; this prevents the score
        from being entirely governed by cost terms alone.
        """
        h = state.human
        raw = h.intent_probability * state.context_utility * _clamp(state.urgency + 0.05)
        return _clamp(raw)

    def _compute_interruption_cost(
        self, state: UnifiedState, timing_penalty: float
    ) -> float:
        """Compute the *interruption_cost* component.

        ``interruption_cost = interruption_sensitivity × focus_level × timing_penalty``

        The product is clamped and scaled to stay within ``[0, 1]``.
        """
        h = state.human
        raw = h.interruption_sensitivity * h.focus_level * timing_penalty
        return _clamp(raw)

    def _compute_risk_cost(self, state: UnifiedState) -> float:
        """Compute the *risk_cost* component.

        ``risk_cost = action_risk × uncertainty``
        """
        return _clamp(state.action_risk * state.uncertainty)
