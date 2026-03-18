"""
core.continuum.return_engine — Return-to-Formless Engine
=========================================================

Determines whether and how a continuum cycle should retreat from its current
phase back toward formless silence.

Return triggers
---------------
The engine recognises five canonical return triggers:

    finished          — task / expression completed normally.
    timeout           — maximum dwell time exceeded with no progression.
    low_value         — decision gate score has fallen below the minimum
                        action threshold persistently.
    high_uncertainty  — uncertainty has risen above a safe operating band,
                        making continued action unreliable.
    user_cancel       — explicit cancellation signal from the user / caller.

Return actions
--------------
Each trigger maps to one of four graduated return actions:

    hold              — stay in current phase; monitor for improvement.
    soft_decay        — reduce presence_intensity gently; no phase change yet.
    step_down         — transition to the next lower phase
                        (manifest → receding → formless).
    return_to_formless — immediate hard return to the formless phase.

Trigger → action mapping (defaults)::

    finished          → step_down
    timeout           → step_down
    low_value         → soft_decay (unless persistent → step_down)
    high_uncertainty  → return_to_formless
    user_cancel       → return_to_formless

All thresholds are configurable via
:class:`~core.continuum.config.ContinuumConfig`.

Usage::

    from core.continuum.return_engine import ReturnEngine, ReturnResult
    from core.continuum.types import ContinuumPhase, ContinuumState, DecisionState

    engine = ReturnEngine()
    state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)

    result = engine.evaluate(state, elapsed_ms=6000)
    if result.should_return:
        print(result.return_action, result.trigger)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import ContinuumPhase, ContinuumState


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReturnTrigger(str, Enum):
    """Canonical return triggers recognised by the :class:`ReturnEngine`."""

    FINISHED = "finished"
    """Normal task/expression completion."""

    TIMEOUT = "timeout"
    """Maximum dwell/activity time exceeded with no progression."""

    LOW_VALUE = "low_value"
    """Decision gate score has fallen below the minimum useful threshold."""

    HIGH_UNCERTAINTY = "high_uncertainty"
    """Uncertainty has risen above safe operating limits."""

    USER_CANCEL = "user_cancel"
    """Explicit cancellation by the user or calling context."""


class ReturnAction(str, Enum):
    """Graduated return actions emitted by the :class:`ReturnEngine`."""

    HOLD = "hold"
    """Remain in the current phase; no state change."""

    SOFT_DECAY = "soft_decay"
    """Gently reduce presence intensity without triggering a phase transition."""

    STEP_DOWN = "step_down"
    """Transition to the next lower phase (manifest → receding → formless)."""

    RETURN_TO_FORMLESS = "return_to_formless"
    """Immediate hard return to the formless phase, bypassing intermediate steps."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReturnResult:
    """Immutable result of a single return-engine evaluation.

    Attributes:
        should_return:  ``True`` when the engine recommends leaving the
                        current phase.
        trigger:        The :class:`ReturnTrigger` that fired, or ``None``
                        if no trigger was active.
        return_action:  The recommended :class:`ReturnAction`.
        reason:         Human-readable explanation.
        next_phase:     Target phase when ``return_action`` is
                        :attr:`ReturnAction.STEP_DOWN` or
                        :attr:`ReturnAction.RETURN_TO_FORMLESS`; ``None``
                        otherwise.
        decay_amount:   Suggested presence-intensity reduction for
                        ``soft_decay`` actions; ``0.0`` otherwise.
    """

    should_return: bool
    trigger: Optional[ReturnTrigger]
    return_action: ReturnAction
    reason: str
    next_phase: Optional[ContinuumPhase] = field(default=None)
    decay_amount: float = field(default=0.0)


# ---------------------------------------------------------------------------
# Default thresholds
# ---------------------------------------------------------------------------

_DEFAULT_LOW_VALUE_THRESHOLD: float = 0.10
"""Decision gate score below which a ``low_value`` trigger fires."""

_DEFAULT_HIGH_UNCERTAINTY_THRESHOLD: float = 0.85
"""Uncertainty above which a ``high_uncertainty`` trigger fires."""

_DEFAULT_SOFT_DECAY_AMOUNT: float = 0.05
"""Amount by which presence_intensity is reduced on a ``soft_decay`` action."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


def _step_down_phase(current: ContinuumPhase) -> ContinuumPhase:
    """Return the next lower phase from *current*.

    Phase order (descending)::

        manifest → receding → formless

    Liminal and formless both return ``formless``.
    """
    _order = {
        ContinuumPhase.MANIFEST: ContinuumPhase.RECEDING,
        ContinuumPhase.RECEDING: ContinuumPhase.FORMLESS,
        ContinuumPhase.LIMINAL: ContinuumPhase.FORMLESS,
        ContinuumPhase.FORMLESS: ContinuumPhase.FORMLESS,
    }
    return _order.get(current, ContinuumPhase.FORMLESS)


def _no_return(reason: str = "no trigger active") -> ReturnResult:
    """Convenience factory for a *hold / no-return* result."""
    return ReturnResult(
        should_return=False,
        trigger=None,
        return_action=ReturnAction.HOLD,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ReturnEngine:
    """Determines whether and how the continuum should retreat toward formless.

    The engine is **stateless** — each call to :meth:`evaluate` produces a
    fresh :class:`ReturnResult` based solely on the inputs provided.  Any
    persistent low-value counters or history must be tracked by the caller.

    Args:
        config:                   Continuum configuration.  Defaults to
                                  :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
        low_value_threshold:      Decision gate score below which ``low_value``
                                  fires.  Defaults to ``0.10``.
        high_uncertainty_threshold: Uncertainty above which ``high_uncertainty``
                                  fires.  Defaults to ``0.85``.
        soft_decay_amount:        Amount to reduce ``presence_intensity`` on a
                                  ``soft_decay`` action.  Defaults to ``0.05``.
    """

    def __init__(
        self,
        config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG,
        *,
        low_value_threshold: float = _DEFAULT_LOW_VALUE_THRESHOLD,
        high_uncertainty_threshold: float = _DEFAULT_HIGH_UNCERTAINTY_THRESHOLD,
        soft_decay_amount: float = _DEFAULT_SOFT_DECAY_AMOUNT,
    ) -> None:
        self._cfg = config
        self._low_value_threshold = _clamp(low_value_threshold)
        self._high_uncertainty_threshold = _clamp(high_uncertainty_threshold)
        self._soft_decay_amount = _clamp(soft_decay_amount)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        state: ContinuumState,
        *,
        elapsed_ms: float = 0.0,
        decision_score: Optional[float] = None,
        user_cancel: bool = False,
        finished: bool = False,
    ) -> ReturnResult:
        """Evaluate whether the system should return from the current phase.

        Triggers are checked in priority order (highest priority first):

        1. ``user_cancel``       — always fires a hard return immediately.
        2. ``high_uncertainty``  — fires a hard return when uncertainty
                                   exceeds the configured threshold.
        3. ``finished``          — fires a step-down when the caller signals
                                   normal completion.
        4. ``timeout``           — fires a step-down when ``elapsed_ms``
                                   exceeds the configured timeout.
        5. ``low_value``         — fires a soft-decay when the decision gate
                                   score is below the minimum threshold.

        If no trigger fires the result is :attr:`ReturnAction.HOLD`.

        Args:
            state:          Current :class:`~core.continuum.types.ContinuumState`.
            elapsed_ms:     Milliseconds elapsed since entering the current
                            phase.  Used for the ``timeout`` trigger.
            decision_score: Most recent decision gate score (``should_act_score``
                            from :class:`~core.continuum.decision_gate.DecisionGate`).
                            When ``None``, the ``low_value`` trigger is skipped.
            user_cancel:    ``True`` when the user or calling context has
                            explicitly requested cancellation.
            finished:       ``True`` when the current task / expression has
                            completed normally.

        Returns:
            Immutable :class:`ReturnResult` snapshot.
        """
        phase = state.phase

        # Use the stability field as an uncertainty proxy: lower stability
        # implies higher effective uncertainty for return purposes.
        effective_uncertainty = _clamp(1.0 - state.stability)

        # 1. User cancel — highest priority, hard return.
        if user_cancel:
            return ReturnResult(
                should_return=True,
                trigger=ReturnTrigger.USER_CANCEL,
                return_action=ReturnAction.RETURN_TO_FORMLESS,
                reason="user_cancel: explicit cancellation requested",
                next_phase=ContinuumPhase.FORMLESS,
                decay_amount=0.0,
            )

        # 2. High uncertainty — hard return.
        if effective_uncertainty >= self._high_uncertainty_threshold:
            return ReturnResult(
                should_return=True,
                trigger=ReturnTrigger.HIGH_UNCERTAINTY,
                return_action=ReturnAction.RETURN_TO_FORMLESS,
                reason=(
                    f"high_uncertainty: effective_uncertainty={effective_uncertainty:.3f} "
                    f">= threshold={self._high_uncertainty_threshold:.3f}"
                ),
                next_phase=ContinuumPhase.FORMLESS,
                decay_amount=0.0,
            )

        # 3. Finished — step down from current phase.
        if finished:
            next_p = _step_down_phase(phase)
            return ReturnResult(
                should_return=True,
                trigger=ReturnTrigger.FINISHED,
                return_action=ReturnAction.STEP_DOWN,
                reason=f"finished: normal completion, stepping down {phase.value} → {next_p.value}",
                next_phase=next_p,
                decay_amount=0.0,
            )

        # 4. Timeout — compare elapsed_ms to config timeout.
        timeout_ms = float(self._cfg.timeout_receding_ms)
        if elapsed_ms > 0.0 and elapsed_ms >= timeout_ms and phase != ContinuumPhase.FORMLESS:
            next_p = _step_down_phase(phase)
            return ReturnResult(
                should_return=True,
                trigger=ReturnTrigger.TIMEOUT,
                return_action=ReturnAction.STEP_DOWN,
                reason=(
                    f"timeout: elapsed={elapsed_ms:.0f}ms "
                    f">= timeout={timeout_ms:.0f}ms, "
                    f"stepping down {phase.value} → {next_p.value}"
                ),
                next_phase=next_p,
                decay_amount=0.0,
            )

        # 5. Low value — soft decay.
        if (
            decision_score is not None
            and decision_score < self._low_value_threshold
            and phase != ContinuumPhase.FORMLESS
        ):
            return ReturnResult(
                should_return=True,
                trigger=ReturnTrigger.LOW_VALUE,
                return_action=ReturnAction.SOFT_DECAY,
                reason=(
                    f"low_value: decision_score={decision_score:.3f} "
                    f"< threshold={self._low_value_threshold:.3f}"
                ),
                next_phase=None,
                decay_amount=self._soft_decay_amount,
            )

        return _no_return(
            f"no trigger active (phase={phase.value}, "
            f"elapsed_ms={elapsed_ms:.0f}, "
            f"uncertainty={effective_uncertainty:.3f})"
        )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def force_return(
        self,
        state: ContinuumState,
        trigger: ReturnTrigger = ReturnTrigger.USER_CANCEL,
    ) -> ReturnResult:
        """Force an immediate hard return to formless, bypassing all checks.

        Useful for error paths or external shutdown signals.

        Args:
            state:   Current :class:`~core.continuum.types.ContinuumState`.
            trigger: The trigger label to attach to the result.

        Returns:
            :class:`ReturnResult` with ``return_action=RETURN_TO_FORMLESS``.
        """
        return ReturnResult(
            should_return=True,
            trigger=trigger,
            return_action=ReturnAction.RETURN_TO_FORMLESS,
            reason=f"force_return: {trigger.value} (unconditional hard return)",
            next_phase=ContinuumPhase.FORMLESS,
            decay_amount=0.0,
        )
