"""
core.continuum.temporal_engine — Temporal Continuity Engine
===========================================================

Implements stable, jitter-free state-continuum evolution via:

  - EMA smoothing    : exponential moving-average on numeric signals.
  - Hysteresis       : dual enter/exit thresholds per phase transition.
  - Dwell guard      : minimum time-in-phase before a transition is allowed.
  - Rate limiter     : cap on maximum signal delta per evaluation tick.
  - Decay function   : smooth retreat of presence_intensity (receding phase).

Public API
----------
Standalone helpers (also useful in tests and downstream modules)::

    apply_ema(new_val, prev_val, alpha)          -> float
    apply_rate_limit(new_val, prev_val, max_d)   -> float
    apply_decay(value, decay_rate)               -> float

Component classes::

    HysteresisGate   — stateful dual-threshold gate
    DwellGuard       — minimum-dwell time enforcer

Main engine::

    TemporalEngine   — combines all of the above; consumes UnifiedState,
                       produces ContinuumState.

Usage example::

    from core.continuum import UnifiedState, HumanFieldState, ContinuumPhase
    from core.continuum.temporal_engine import TemporalEngine

    engine = TemporalEngine()
    state  = engine.tick(UnifiedState(
        human=HumanFieldState(intent_probability=0.85, attention=0.80),
        context_utility=0.70,
        phase_candidate=ContinuumPhase.LIMINAL,
        candidate_confidence=0.72,
    ))
    print(state.phase, state.presence_intensity)
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import ContinuumPhase, ContinuumState, UnifiedState


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Default per-tick decay rate applied while in the *receding* phase.
_DEFAULT_DECAY_RATE: float = 0.05

#: EMA alpha used to penalise stability on a phase flip.
#: ``apply_ema(0.0, prev, alpha)`` halves stability at ``alpha=0.5``.
_STABILITY_FLIP_ALPHA: float = 0.5

#: EMA alpha for gradual stability recovery between flips.
_STABILITY_RECOVERY_ALPHA: float = 0.05


# ---------------------------------------------------------------------------
# Internal utility
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *value* clamped to the closed interval [*lo*, *hi*]."""
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Standalone signal-processing functions
# ---------------------------------------------------------------------------


def apply_ema(new_val: float, prev_val: float, alpha: float) -> float:
    """Compute one step of an exponential moving average.

    Formula::

        result = alpha * new_val + (1 - alpha) * prev_val

    Args:
        new_val:  Raw (un-smoothed) incoming value.
        prev_val: Previous smoothed value.
        alpha:    Smoothing factor in ``(0.0, 1.0]``.
                  Low alpha → smooth / slow to react.
                  High alpha → responsive / fast to react.

    Returns:
        Updated smoothed value.  Not clamped — callers should clamp as needed.
    """
    return alpha * new_val + (1.0 - alpha) * prev_val


def apply_rate_limit(new_val: float, prev_val: float, max_delta: float) -> float:
    """Cap the magnitude of change from *prev_val* to *new_val*.

    If ``|new_val - prev_val| > max_delta`` the returned value is
    ``prev_val ± max_delta`` (sign matches the direction of change).
    Otherwise *new_val* is returned unchanged.

    Args:
        new_val:   Target value (after EMA smoothing).
        prev_val:  Value from the previous tick.
        max_delta: Maximum absolute change permitted in a single tick.
                   Must be non-negative.

    Returns:
        Rate-limited value.
    """
    delta = new_val - prev_val
    if abs(delta) > max_delta:
        return prev_val + max_delta * (1.0 if delta > 0.0 else -1.0)
    return new_val


def apply_decay(value: float, decay_rate: float = _DEFAULT_DECAY_RATE) -> float:
    """Apply one step of multiplicative exponential decay.

    Each call multiplies *value* by ``(1 - decay_rate)``::

        result = value * (1 - decay_rate)

    This models the smooth retreat of presence_intensity in the
    *receding* phase toward zero.

    Args:
        value:      Current signal magnitude.  Expected range ``[0.0, 1.0]``.
        decay_rate: Fraction removed per call.  Must be in ``(0.0, 1.0)``.
                    Defaults to :data:`_DEFAULT_DECAY_RATE` (``0.05``).

    Returns:
        Decayed value, clamped to ``[0.0, 1.0]``.
    """
    return _clamp(value * (1.0 - decay_rate))


# ---------------------------------------------------------------------------
# HysteresisGate
# ---------------------------------------------------------------------------


class HysteresisGate:
    """Dual-threshold hysteresis gate for a scalar signal.

    Prevents rapid toggling near a single threshold by requiring the signal
    to cross a *higher* ``enter`` threshold to become active, and to drop
    strictly *below* a *lower* ``exit_`` threshold to become inactive.

    Example::

        gate = HysteresisGate(enter=0.68, exit_=0.45)

        gate.update(0.70)  # → True   signal crossed enter threshold
        gate.update(0.60)  # → True   still above exit; stays active
        gate.update(0.40)  # → False  dropped below exit
        gate.update(0.65)  # → False  above exit but below enter; stays inactive
        gate.update(0.70)  # → True   crossed enter again

    Raises:
        ValueError: if ``enter <= exit_`` (hysteresis gap would be zero or
                    inverted, making the gate meaningless).
    """

    def __init__(self, enter: float, exit_: float) -> None:
        """
        Args:
            enter: Signal must reach or exceed this value to activate.
            exit_: Signal must drop strictly below this value to deactivate.
        """
        if enter <= exit_:
            raise ValueError(
                f"HysteresisGate requires enter ({enter}) > exit_ ({exit_}); "
                "the hysteresis gap must be positive."
            )
        self.enter: float = enter
        self.exit_: float = exit_
        self._active: bool = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """``True`` when the gate is currently activated."""
        return self._active

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def update(self, signal: float) -> bool:
        """Feed a new signal sample and return the updated activation state.

        Args:
            signal: Current signal value (typically in ``[0.0, 1.0]``).

        Returns:
            ``True`` if the gate is (or just became) active after this sample.
        """
        if not self._active and signal >= self.enter:
            self._active = True
        elif self._active and signal < self.exit_:
            self._active = False
        return self._active

    def reset(self, active: bool = False) -> None:
        """Reset the gate to a known activation state.

        Args:
            active: Target state after reset.  Defaults to ``False``.
        """
        self._active = active


# ---------------------------------------------------------------------------
# DwellGuard
# ---------------------------------------------------------------------------


class DwellGuard:
    """Enforces a minimum dwell time before a phase transition is permitted.

    :py:meth:`reset` restarts the timer (call whenever the engine enters a
    new phase).  :py:meth:`is_satisfied` returns ``True`` only after at least
    ``dwell_ms`` milliseconds have elapsed.

    :py:func:`time.monotonic` is used internally, so the guard is unaffected
    by wall-clock adjustments.

    Example::

        guard = DwellGuard(dwell_ms=200)
        guard.reset()
        guard.is_satisfied()          # False (immediately after reset)
        time.sleep(0.25)
        guard.is_satisfied()          # True  (250 ms > 200 ms dwell)

    Args:
        dwell_ms: Minimum time in milliseconds a phase must be occupied
                  before any outbound transition is allowed.  Pass ``0``
                  to disable enforcement (always satisfied).
    """

    def __init__(self, dwell_ms: int) -> None:
        self.dwell_ms: int = dwell_ms
        self._entered_at: float = time.monotonic()

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Restart the dwell timer from now."""
        self._entered_at = time.monotonic()

    def elapsed_ms(self) -> float:
        """Milliseconds elapsed since the last :py:meth:`reset`."""
        return (time.monotonic() - self._entered_at) * 1000.0

    def is_satisfied(self) -> bool:
        """``True`` if the minimum dwell time has been met or exceeded."""
        return self.dwell_ms == 0 or self.elapsed_ms() >= self.dwell_ms

    def remaining_ms(self) -> float:
        """Milliseconds remaining until the dwell requirement is satisfied.

        Returns ``0.0`` once the guard is satisfied.
        """
        return max(0.0, self.dwell_ms - self.elapsed_ms())


# ---------------------------------------------------------------------------
# TemporalEngine
# ---------------------------------------------------------------------------


class TemporalEngine:
    """Converts raw :class:`~core.continuum.types.UnifiedState` snapshots
    into stable :class:`~core.continuum.types.ContinuumState` outputs.

    Each call to :py:meth:`tick` advances the engine by one evaluation cycle:

    1. Derive raw numeric signals from the incoming :class:`UnifiedState`.
    2. Apply EMA smoothing to all signals.
    3. Apply per-tick rate limiting on ``presence_intensity``.
    4. Apply exponential decay to ``presence_intensity`` in *receding* phase.
    5. Evaluate phase transitions subject to hysteresis gates and dwell guards.
    6. Update temporal stability based on recent phase-flip frequency.
    7. Return an immutable :class:`ContinuumState` snapshot.

    The engine is **stateful**: smoothed signal history and phase-transition
    timing accumulate across successive :py:meth:`tick` calls.

    It is **not** thread-safe; callers must serialise concurrent access.

    Phase-transition graph (only these edges are permitted)::

        FORMLESS → LIMINAL → MANIFEST → RECEDING → FORMLESS
                 ↑__________|

    Signal mappings
    ---------------
    *presence_intensity*
        Weighted blend: ``intent_probability × 0.5 + attention × 0.3
        + context_utility × 0.2``.

    *coherence*
        Candidate confidence scaled by low uncertainty:
        ``candidate_confidence × (1 − uncertainty × 0.5)``.

    *collapse_tendency*
        Candidate confidence × intent_probability when the mode-collapse
        engine suggests *liminal* or *manifest*; otherwise ``0.0``.

    *retreat_tendency*
        Risk/uncertainty pressure: ``action_risk × 0.5 + uncertainty × 0.3
        + (1 − attention) × 0.2``.

    Usage::

        engine = TemporalEngine()
        state  = engine.tick(UnifiedState(...))

    Args:
        config:     Master continuum configuration.
                    Defaults to :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
        decay_rate: Per-tick decay rate applied to ``presence_intensity``
                    while in the *receding* phase.
                    Defaults to :data:`_DEFAULT_DECAY_RATE`.
    """

    #: Allowed outbound transitions for each phase.
    _ALLOWED_NEXT: Dict[ContinuumPhase, tuple] = {
        ContinuumPhase.FORMLESS: (ContinuumPhase.LIMINAL,),
        ContinuumPhase.LIMINAL: (ContinuumPhase.MANIFEST, ContinuumPhase.FORMLESS),
        ContinuumPhase.MANIFEST: (ContinuumPhase.RECEDING,),
        ContinuumPhase.RECEDING: (ContinuumPhase.FORMLESS,),
    }

    def __init__(
        self,
        config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG,
        *,
        decay_rate: float = _DEFAULT_DECAY_RATE,
    ) -> None:
        self.config = config
        self.decay_rate = decay_rate

        # --- EMA-smoothed signals (mutable internal state) ---
        self._smoothed: Dict[str, float] = {
            "presence_intensity": 0.0,
            "coherence": 0.0,
            "ambiguity": 1.0,
            "collapse_tendency": 0.0,
            "retreat_tendency": 0.0,
        }

        # --- Phase tracking ---
        self._phase: ContinuumPhase = ContinuumPhase.FORMLESS

        # --- Hysteresis gates ---
        self._liminal_gate = HysteresisGate(
            enter=config.hysteresis.liminal_enter,
            exit_=config.hysteresis.liminal_exit,
        )
        self._manifest_gate = HysteresisGate(
            enter=config.hysteresis.manifest_enter,
            exit_=config.hysteresis.manifest_exit,
        )

        # --- Dwell guards (one per phase that has a minimum dwell) ---
        self._dwell_guards: Dict[ContinuumPhase, DwellGuard] = {
            ContinuumPhase.LIMINAL: DwellGuard(config.dwell.liminal_ms),
            ContinuumPhase.MANIFEST: DwellGuard(config.dwell.manifest_ms),
            ContinuumPhase.RECEDING: DwellGuard(config.dwell.receding_ms),
        }

        # --- Stability tracking ---
        self._stability: float = 1.0
        self._flip_timestamps: Deque[float] = deque()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_phase(self) -> ContinuumPhase:
        """The phase as of the most recent :py:meth:`tick` call."""
        return self._phase

    @property
    def smoothed_signals(self) -> Dict[str, float]:
        """Read-only snapshot of the current EMA-smoothed signals."""
        return dict(self._smoothed)

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Return the engine to its pristine formless initial state.

        Clears all smoothed signal history, resets phase to *formless*,
        deactivates hysteresis gates, and resets dwell timers.
        """
        self._smoothed = {
            "presence_intensity": 0.0,
            "coherence": 0.0,
            "ambiguity": 1.0,
            "collapse_tendency": 0.0,
            "retreat_tendency": 0.0,
        }
        self._phase = ContinuumPhase.FORMLESS
        self._liminal_gate.reset(False)
        self._manifest_gate.reset(False)
        for guard in self._dwell_guards.values():
            guard.reset()
        self._stability = 1.0
        self._flip_timestamps.clear()

    def tick(self, unified: UnifiedState) -> ContinuumState:
        """Advance the engine by one evaluation cycle.

        Args:
            unified: Fused perception/context snapshot for this tick.

        Returns:
            An immutable :class:`ContinuumState` representing the engine
            output after processing this tick.
        """
        # 1. Derive raw (un-smoothed) numeric signals.
        raw = self._derive_raw_signals(unified)

        # 2. Apply EMA smoothing and rate-limit presence_intensity.
        alpha = self.config.ema_alpha
        max_delta = self.config.max_delta_per_tick
        for name, raw_val in raw.items():
            prev = self._smoothed[name]
            smoothed = apply_ema(raw_val, prev, alpha)
            if name == "presence_intensity":
                smoothed = apply_rate_limit(smoothed, prev, max_delta)
            self._smoothed[name] = _clamp(smoothed)

        # 3. Decay presence_intensity when in the receding phase.
        if self._phase == ContinuumPhase.RECEDING:
            self._smoothed["presence_intensity"] = apply_decay(
                self._smoothed["presence_intensity"], self.decay_rate
            )

        # 4. Evaluate candidate phase transition.
        new_phase = self._evaluate_phase()

        # 5. Record transition; update dwell timers and stability.
        if new_phase != self._phase:
            self._phase = new_phase
            if new_phase in self._dwell_guards:
                self._dwell_guards[new_phase].reset()
            # Penalise stability on every phase flip.
            self._stability = apply_ema(0.0, self._stability, _STABILITY_FLIP_ALPHA)
            self._flip_timestamps.append(time.monotonic())
        else:
            # Gradual stability recovery when no flip occurs.
            self._stability = apply_ema(1.0, self._stability, _STABILITY_RECOVERY_ALPHA)

        # Prune flip timestamps older than 10 s (sliding window bookkeeping).
        now = time.monotonic()
        while self._flip_timestamps and now - self._flip_timestamps[0] > 10.0:
            self._flip_timestamps.popleft()

        return ContinuumState(
            phase=self._phase,
            presence_intensity=self._smoothed["presence_intensity"],
            coherence=self._smoothed["coherence"],
            ambiguity=self._smoothed["ambiguity"],
            collapse_tendency=self._smoothed["collapse_tendency"],
            retreat_tendency=self._smoothed["retreat_tendency"],
            stability=_clamp(self._stability),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_phase(self) -> ContinuumPhase:
        """Determine the target phase using hysteresis gates and dwell guards.

        Returns:
            The phase the engine should move to (may equal the current phase
            if no transition is warranted or permitted).
        """
        current = self._phase
        intensity = self._smoothed["presence_intensity"]
        collapse = self._smoothed["collapse_tendency"]
        retreat = self._smoothed["retreat_tendency"]

        # Update hysteresis gates with current smoothed signals.
        liminal_active = self._liminal_gate.update(intensity)
        manifest_active = self._manifest_gate.update(collapse)

        if current == ContinuumPhase.FORMLESS:
            # formless → liminal: intensity crosses the liminal enter threshold.
            if liminal_active:
                return ContinuumPhase.LIMINAL

        elif current == ContinuumPhase.LIMINAL:
            dwell = self._dwell_guards[ContinuumPhase.LIMINAL]
            if not dwell.is_satisfied():
                return current  # Dwell not yet met; block outbound transition.
            # liminal → manifest: collapse_tendency crosses manifest enter.
            if manifest_active:
                return ContinuumPhase.MANIFEST
            # liminal → formless: intensity drops below the liminal exit.
            if not liminal_active:
                return ContinuumPhase.FORMLESS

        elif current == ContinuumPhase.MANIFEST:
            dwell = self._dwell_guards[ContinuumPhase.MANIFEST]
            if not dwell.is_satisfied():
                return current
            # manifest → receding: collapse gate deactivated or retreat pressure high.
            if not manifest_active or retreat >= 0.7:
                return ContinuumPhase.RECEDING

        elif current == ContinuumPhase.RECEDING:
            dwell = self._dwell_guards[ContinuumPhase.RECEDING]
            if not dwell.is_satisfied():
                return current
            # receding → formless: presence decays below the formless floor.
            if self._smoothed["presence_intensity"] <= self.config.min_presence_formless:
                return ContinuumPhase.FORMLESS

        return current

    def _derive_raw_signals(self, unified: UnifiedState) -> Dict[str, float]:
        """Extract and normalise raw numeric signals from a :class:`UnifiedState`.

        These values are *not* yet smoothed.  EMA is applied in :py:meth:`tick`.

        Args:
            unified: Current fused state snapshot.

        Returns:
            Dict mapping signal names to raw ``[0.0, 1.0]`` values.
        """
        human = unified.human

        # Presence intensity: weighted blend of intent, attention, context utility.
        presence = (
            human.intent_probability * 0.5
            + human.attention * 0.3
            + unified.context_utility * 0.2
        )

        # Coherence: candidate confidence scaled by confidence in low uncertainty.
        coherence = unified.candidate_confidence * (1.0 - unified.uncertainty * 0.5)

        # Ambiguity: complement of coherence.
        ambiguity = 1.0 - coherence

        # Collapse tendency: active only when mode-collapse suggests liminal/manifest.
        if unified.phase_candidate in (
            ContinuumPhase.LIMINAL,
            ContinuumPhase.MANIFEST,
        ):
            collapse = unified.candidate_confidence * human.intent_probability
        else:
            collapse = 0.0

        # Retreat tendency: risk, uncertainty, and low attention pressure.
        retreat = (
            unified.action_risk * 0.5
            + unified.uncertainty * 0.3
            + (1.0 - human.attention) * 0.2
        )

        return {
            "presence_intensity": _clamp(presence),
            "coherence": _clamp(coherence),
            "ambiguity": _clamp(ambiguity),
            "collapse_tendency": _clamp(collapse),
            "retreat_tendency": _clamp(retreat),
        }
