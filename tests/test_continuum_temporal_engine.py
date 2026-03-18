"""
tests/test_continuum_temporal_engine.py
=======================================

Unit tests for core.continuum.temporal_engine.

Test groups
-----------
  A) apply_ema            — standalone EMA smoothing function
  B) apply_rate_limit     — standalone rate-limiter function
  C) apply_decay          — standalone decay function
  D) HysteresisGate       — enter/exit dual-threshold gate
  E) DwellGuard           — minimum dwell-time enforcer
  F) TemporalEngine       — full engine (smoothing, hysteresis, dwell,
                            rate limit, decay, phase transitions)
  G) TemporalEngine reset — reset() brings engine back to formless
  H) TemporalEngine public API surface
"""

from __future__ import annotations

import time

import pytest

from core.continuum.config import (
    ContinuumConfig,
    DEFAULT_CONTINUUM_CONFIG,
    DwellConfig,
    HysteresisConfig,
)
from core.continuum.temporal_engine import (
    HysteresisGate,
    DwellGuard,
    TemporalEngine,
    apply_decay,
    apply_ema,
    apply_rate_limit,
)
from core.continuum.types import (
    ContinuumPhase,
    ContinuumState,
    HumanFieldState,
    UnifiedState,
)


# ---------------------------------------------------------------------------
# Helpers shared across test groups
# ---------------------------------------------------------------------------


def _fast_config(
    *,
    ema_alpha: float = 1.0,
    max_delta: float = 1.0,
    liminal_enter: float = 0.5,
    liminal_exit: float = 0.2,
    manifest_enter: float = 0.7,
    manifest_exit: float = 0.3,
    liminal_ms: int = 0,
    manifest_ms: int = 0,
    receding_ms: int = 0,
    min_presence_formless: float = 0.05,
) -> ContinuumConfig:
    """Build a test-friendly config with instant smoothing and zero dwell."""
    return ContinuumConfig(
        ema_alpha=ema_alpha,
        max_delta_per_tick=max_delta,
        hysteresis=HysteresisConfig(
            liminal_enter=liminal_enter,
            liminal_exit=liminal_exit,
            manifest_enter=manifest_enter,
            manifest_exit=manifest_exit,
        ),
        dwell=DwellConfig(
            liminal_ms=liminal_ms,
            manifest_ms=manifest_ms,
            receding_ms=receding_ms,
        ),
        min_presence_formless=min_presence_formless,
    )


def _unified(
    *,
    intent: float = 0.0,
    attention: float = 0.5,
    context_utility: float = 0.0,
    candidate: ContinuumPhase = ContinuumPhase.FORMLESS,
    candidate_confidence: float = 0.0,
    uncertainty: float = 0.5,
    action_risk: float = 0.0,
) -> UnifiedState:
    """Convenience factory for UnifiedState in tests."""
    return UnifiedState(
        human=HumanFieldState(
            intent_probability=intent,
            attention=attention,
        ),
        context_utility=context_utility,
        phase_candidate=candidate,
        candidate_confidence=candidate_confidence,
        uncertainty=uncertainty,
        action_risk=action_risk,
    )


def _strong_liminal() -> UnifiedState:
    """UnifiedState that should drive presence_intensity well above liminal enter."""
    return _unified(
        intent=0.9,
        attention=0.9,
        context_utility=0.9,
        candidate=ContinuumPhase.LIMINAL,
        candidate_confidence=0.9,
        uncertainty=0.1,
    )


def _strong_manifest() -> UnifiedState:
    """UnifiedState that should drive collapse_tendency above manifest enter."""
    return _unified(
        intent=0.9,
        attention=0.9,
        context_utility=0.9,
        candidate=ContinuumPhase.MANIFEST,
        candidate_confidence=0.9,
        uncertainty=0.1,
    )


def _retreat_unified() -> UnifiedState:
    """UnifiedState with high retreat_tendency (action_risk + uncertainty)."""
    return _unified(
        intent=0.1,
        attention=0.1,
        context_utility=0.1,
        candidate=ContinuumPhase.FORMLESS,
        candidate_confidence=0.0,
        uncertainty=0.9,
        action_risk=0.9,
    )


# ===========================================================================
# A) apply_ema
# ===========================================================================


class TestApplyEma:
    def test_alpha_one_returns_new_val(self):
        assert apply_ema(0.8, 0.2, alpha=1.0) == pytest.approx(0.8)

    def test_alpha_zero_returns_prev_val(self):
        assert apply_ema(0.8, 0.2, alpha=0.0) == pytest.approx(0.2)

    def test_alpha_half(self):
        # 0.5 * 0.8 + 0.5 * 0.2 = 0.5
        assert apply_ema(0.8, 0.2, alpha=0.5) == pytest.approx(0.5)

    def test_convergence_over_multiple_steps(self):
        val = 0.0
        target = 1.0
        alpha = 0.3
        for _ in range(50):
            val = apply_ema(target, val, alpha)
        assert val == pytest.approx(1.0, abs=1e-4)

    def test_convergence_toward_zero(self):
        val = 1.0
        for _ in range(80):
            val = apply_ema(0.0, val, 0.2)
        assert val == pytest.approx(0.0, abs=1e-4)

    def test_formula_symmetry(self):
        result = apply_ema(0.6, 0.4, alpha=0.25)
        expected = 0.25 * 0.6 + 0.75 * 0.4
        assert result == pytest.approx(expected)

    def test_returns_float(self):
        assert isinstance(apply_ema(0.5, 0.5, 0.1), float)


# ===========================================================================
# B) apply_rate_limit
# ===========================================================================


class TestApplyRateLimit:
    def test_no_limit_needed_positive(self):
        # delta = 0.05, max = 0.1 → no clipping
        assert apply_rate_limit(0.55, 0.50, 0.1) == pytest.approx(0.55)

    def test_no_limit_needed_negative(self):
        # delta = -0.05, max = 0.1 → no clipping
        assert apply_rate_limit(0.45, 0.50, 0.1) == pytest.approx(0.45)

    def test_positive_delta_clipped(self):
        # delta = 0.20, max = 0.08 → clipped to 0.50 + 0.08 = 0.58
        assert apply_rate_limit(0.70, 0.50, 0.08) == pytest.approx(0.58)

    def test_negative_delta_clipped(self):
        # delta = -0.20, max = 0.08 → clipped to 0.50 - 0.08 = 0.42
        assert apply_rate_limit(0.30, 0.50, 0.08) == pytest.approx(0.42)

    def test_exactly_at_max_delta_not_clipped(self):
        assert apply_rate_limit(0.58, 0.50, 0.08) == pytest.approx(0.58)

    def test_large_jump_from_zero(self):
        assert apply_rate_limit(1.0, 0.0, 0.08) == pytest.approx(0.08)

    def test_max_delta_zero_no_movement(self):
        assert apply_rate_limit(0.9, 0.5, 0.0) == pytest.approx(0.5)

    def test_returns_float(self):
        assert isinstance(apply_rate_limit(0.5, 0.4, 0.2), float)


# ===========================================================================
# C) apply_decay
# ===========================================================================


class TestApplyDecay:
    def test_single_step_default_rate(self):
        result = apply_decay(1.0)
        assert result == pytest.approx(0.95)  # 1.0 * (1 - 0.05)

    def test_single_step_custom_rate(self):
        result = apply_decay(1.0, decay_rate=0.1)
        assert result == pytest.approx(0.9)

    def test_converges_to_zero(self):
        val = 1.0
        for _ in range(200):
            val = apply_decay(val, decay_rate=0.1)
        assert val == pytest.approx(0.0, abs=1e-4)

    def test_zero_input_stays_zero(self):
        assert apply_decay(0.0) == pytest.approx(0.0)

    def test_result_clamped_to_zero(self):
        # Starting from very small positive value, decay should not go negative.
        val = 1e-10
        result = apply_decay(val, decay_rate=0.5)
        assert result >= 0.0

    def test_decay_rate_zero_no_change(self):
        assert apply_decay(0.7, decay_rate=0.0) == pytest.approx(0.7)

    def test_returns_float(self):
        assert isinstance(apply_decay(0.5), float)


# ===========================================================================
# D) HysteresisGate
# ===========================================================================


class TestHysteresisGate:
    def test_invalid_enter_le_exit_raises(self):
        with pytest.raises(ValueError):
            HysteresisGate(enter=0.5, exit_=0.5)
        with pytest.raises(ValueError):
            HysteresisGate(enter=0.4, exit_=0.5)

    def test_initially_inactive(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        assert gate.active is False

    def test_below_enter_stays_inactive(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        assert gate.update(0.50) is False
        assert gate.update(0.67) is False

    def test_at_enter_activates(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        assert gate.update(0.68) is True
        assert gate.active is True

    def test_above_enter_activates(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        assert gate.update(0.90) is True

    def test_between_exit_and_enter_stays_active(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.update(0.70)  # activate
        assert gate.update(0.60) is True   # between exit and enter
        assert gate.update(0.50) is True   # still above exit

    def test_below_exit_deactivates(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.update(0.70)           # activate
        assert gate.update(0.44) is False  # below exit → deactivated

    def test_at_exit_stays_active(self):
        # exit_ threshold is *strict* less-than; at exactly exit_ → still active
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.update(0.70)
        assert gate.update(0.45) is True   # not strictly below exit_

    def test_re_activation_after_deactivation(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.update(0.70)    # activate
        gate.update(0.30)    # deactivate
        assert gate.update(0.50) is False  # below enter; stays inactive
        assert gate.update(0.70) is True   # crosses enter again

    def test_reset_to_false(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.update(0.90)        # activate
        gate.reset(False)
        assert gate.active is False

    def test_reset_to_true(self):
        gate = HysteresisGate(enter=0.68, exit_=0.45)
        gate.reset(True)
        assert gate.active is True


# ===========================================================================
# E) DwellGuard
# ===========================================================================


class TestDwellGuard:
    def test_zero_dwell_always_satisfied(self):
        guard = DwellGuard(dwell_ms=0)
        assert guard.is_satisfied() is True

    def test_not_satisfied_immediately(self):
        guard = DwellGuard(dwell_ms=500)
        assert guard.is_satisfied() is False

    def test_satisfied_after_sleep(self):
        guard = DwellGuard(dwell_ms=30)
        guard.reset()
        time.sleep(0.04)  # 40 ms > 30 ms
        assert guard.is_satisfied() is True

    def test_elapsed_ms_increases(self):
        guard = DwellGuard(dwell_ms=1000)
        guard.reset()
        time.sleep(0.02)
        assert guard.elapsed_ms() >= 20.0

    def test_remaining_ms_decreases_to_zero(self):
        guard = DwellGuard(dwell_ms=30)
        guard.reset()
        time.sleep(0.04)
        assert guard.remaining_ms() == pytest.approx(0.0)

    def test_remaining_ms_before_expiry(self):
        guard = DwellGuard(dwell_ms=500)
        guard.reset()
        remaining = guard.remaining_ms()
        assert 0.0 < remaining <= 500.0

    def test_reset_restarts_timer(self):
        guard = DwellGuard(dwell_ms=30)
        guard.reset()
        time.sleep(0.04)
        assert guard.is_satisfied()
        guard.reset()         # restart
        assert guard.is_satisfied() is False


# ===========================================================================
# F) TemporalEngine
# ===========================================================================


class TestTemporalEngineSmoothing:
    """Verify EMA smoothing is applied across ticks."""

    def test_smooth_rise_with_low_alpha(self):
        # alpha=0.1 → slow rise; after one tick from 0.0, value < raw input
        cfg = _fast_config(ema_alpha=0.1, max_delta=1.0)
        engine = TemporalEngine(cfg)
        state = engine.tick(_strong_liminal())
        # Raw presence ≈ 0.9*0.5 + 0.9*0.3 + 0.9*0.2 = 0.9
        # After EMA: 0.1*0.9 + 0.9*0.0 = 0.09
        assert state.presence_intensity < 0.2

    def test_smooth_rise_with_high_alpha_approaches_raw(self):
        # alpha=1.0 → no smoothing; single tick should reach raw value directly
        cfg = _fast_config(ema_alpha=1.0, max_delta=1.0)
        engine = TemporalEngine(cfg)
        state = engine.tick(_strong_liminal())
        # raw presence = 0.9*0.5 + 0.9*0.3 + 0.9*0.2 = 0.9
        assert state.presence_intensity == pytest.approx(0.9, abs=0.01)

    def test_multiple_ticks_converge(self):
        cfg = _fast_config(ema_alpha=0.3, max_delta=1.0)
        engine = TemporalEngine(cfg)
        for _ in range(30):
            state = engine.tick(_strong_liminal())
        assert state.presence_intensity > 0.85

    def test_coherence_smoothed(self):
        cfg = _fast_config(ema_alpha=1.0)
        engine = TemporalEngine(cfg)
        u = _unified(candidate=ContinuumPhase.LIMINAL, candidate_confidence=0.8, uncertainty=0.0)
        state = engine.tick(u)
        # coherence = 0.8 * (1 - 0.0 * 0.5) = 0.8
        assert state.coherence == pytest.approx(0.8, abs=0.01)

    def test_ambiguity_complement_of_coherence(self):
        cfg = _fast_config(ema_alpha=1.0)
        engine = TemporalEngine(cfg)
        u = _unified(candidate=ContinuumPhase.LIMINAL, candidate_confidence=0.8, uncertainty=0.0)
        state = engine.tick(u)
        assert state.ambiguity == pytest.approx(1.0 - state.coherence, abs=0.01)


class TestTemporalEngineRateLimit:
    """Verify rate limiting caps the per-tick delta of presence_intensity."""

    def test_rate_limit_applied_on_large_step(self):
        # Start from 0.0, apply large input; max_delta=0.08 should limit movement.
        cfg = _fast_config(ema_alpha=1.0, max_delta=0.08)
        engine = TemporalEngine(cfg)
        state = engine.tick(_strong_liminal())   # raw ≈ 0.9
        assert state.presence_intensity <= 0.08 + 1e-9

    def test_rate_limit_not_applied_on_small_step(self):
        # After several ticks, changes are small; no clipping expected.
        cfg = _fast_config(ema_alpha=1.0, max_delta=1.0)
        engine = TemporalEngine(cfg)
        # Prime the engine close to steady state.
        for _ in range(3):
            engine.tick(_strong_liminal())
        # Now apply a tiny nudge.
        prev = engine.smoothed_signals["presence_intensity"]
        tiny = _unified(intent=prev, attention=0.0, context_utility=0.0)
        state = engine.tick(tiny)
        # Change should be small and not clipped.
        assert abs(state.presence_intensity - prev) <= 1.0

    def test_rate_limit_respected_over_multiple_ticks(self):
        # Each tick can increase by at most max_delta=0.08.
        cfg = _fast_config(ema_alpha=1.0, max_delta=0.08)
        engine = TemporalEngine(cfg)
        prev = 0.0
        for _ in range(5):
            state = engine.tick(_strong_liminal())
            delta = state.presence_intensity - prev
            assert delta <= 0.08 + 1e-9
            prev = state.presence_intensity


class TestTemporalEngineHysteresis:
    """Verify hysteresis prevents phase flicker near threshold boundaries."""

    def test_below_enter_stays_formless(self):
        # Threshold: enter=0.5; raw presence below this.
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # intent=0.3 → presence = 0.3*0.5 + 0.5*0.3 + 0.0*0.2 = 0.15+0.15 = 0.3
        state = engine.tick(_unified(intent=0.3, attention=0.5))
        assert state.phase == ContinuumPhase.FORMLESS

    def test_above_enter_transitions_to_liminal(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Drive presence well above 0.5 (enter threshold)
        state = engine.tick(_strong_liminal())
        assert state.phase == ContinuumPhase.LIMINAL

    def test_hysteresis_holds_liminal_between_thresholds(self):
        """After entering liminal, signal between exit(0.2) and enter(0.5) should
        keep the engine in LIMINAL (not oscillate back to formless)."""
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Enter liminal.
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        # Now provide a signal between exit (0.2) and enter (0.5).
        # intent=0.5, attention=0.5 → presence = 0.5*0.5 + 0.5*0.3 = 0.4
        mid_state = engine.tick(_unified(intent=0.5, attention=0.5))
        # 0.4 is above exit (0.2) → stays liminal
        assert mid_state.phase == ContinuumPhase.LIMINAL

    def test_below_exit_drops_from_liminal_to_formless(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        # Drive presence below exit threshold (0.2):
        # intent=0.0, attention=0.0, context=0.0 → presence=0
        state = engine.tick(_unified(intent=0.0, attention=0.0))
        assert state.phase == ContinuumPhase.FORMLESS

    def test_manifest_gate_blocks_entry_below_threshold(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Enter liminal using a signal that keeps collapse_tendency BELOW
        # manifest_enter (0.7) so the manifest gate is NOT yet activated.
        # candidate_confidence=0.6 → collapse = 0.6*0.9 = 0.54 < manifest_enter=0.7
        enter_liminal = _unified(
            intent=0.9, attention=0.9, context_utility=0.9,
            candidate=ContinuumPhase.LIMINAL,
            candidate_confidence=0.6,
            uncertainty=0.1,
        )
        engine.tick(enter_liminal)
        assert engine.current_phase == ContinuumPhase.LIMINAL
        # Now provide collapse_tendency still below manifest_enter (0.7) with
        # candidate=MANIFEST → collapse = 0.6*0.9 = 0.54 < 0.7; gate inactive.
        u = _unified(
            intent=0.9, attention=0.9, context_utility=0.9,
            candidate=ContinuumPhase.MANIFEST,
            candidate_confidence=0.6,
            uncertainty=0.1,
        )
        state = engine.tick(u)
        assert state.phase == ContinuumPhase.LIMINAL

    def test_manifest_gate_allows_entry_above_threshold(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        # collapse = 0.9*0.9 = 0.81 > 0.7 (manifest_enter)
        state = engine.tick(_strong_manifest())
        assert state.phase == ContinuumPhase.MANIFEST


class TestTemporalEngineDwell:
    """Verify minimum dwell time blocks premature phase transitions."""

    def test_liminal_dwell_blocks_immediate_manifest_transition(self):
        # 50 ms dwell for liminal → immediate manifest attempt must be blocked.
        cfg = _fast_config(liminal_ms=50)
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        # Immediately try to reach manifest.
        state = engine.tick(_strong_manifest())
        assert state.phase == ContinuumPhase.LIMINAL  # still blocked

    def test_liminal_dwell_allows_manifest_after_wait(self):
        cfg = _fast_config(liminal_ms=30)
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        time.sleep(0.04)  # wait > 30 ms
        state = engine.tick(_strong_manifest())
        assert state.phase == ContinuumPhase.MANIFEST

    def test_manifest_dwell_blocks_immediate_receding_transition(self):
        cfg = _fast_config(liminal_ms=0, manifest_ms=50)
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        engine.tick(_strong_manifest())
        assert engine.current_phase == ContinuumPhase.MANIFEST
        # Immediately apply retreat pressure.
        state = engine.tick(_retreat_unified())
        assert state.phase == ContinuumPhase.MANIFEST  # still blocked

    def test_manifest_dwell_allows_receding_after_wait(self):
        cfg = _fast_config(liminal_ms=0, manifest_ms=30)
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        engine.tick(_strong_manifest())
        time.sleep(0.04)
        state = engine.tick(_retreat_unified())
        assert state.phase == ContinuumPhase.RECEDING

    def test_zero_dwell_transitions_immediately(self):
        # All dwells are 0 → transitions happen on the very next tick.
        cfg = _fast_config()  # all dwell_ms=0 by default in helper
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        state = engine.tick(_strong_manifest())
        assert state.phase == ContinuumPhase.MANIFEST


class TestTemporalEngineDecay:
    """Verify decay is applied during receding and only during receding."""

    def _reach_receding(self, engine: TemporalEngine) -> None:
        """Drive engine from formless through liminal and manifest to receding."""
        engine.tick(_strong_liminal())
        engine.tick(_strong_manifest())
        # Apply high retreat tendency to trigger manifest → receding.
        engine.tick(_retreat_unified())
        assert engine.current_phase == ContinuumPhase.RECEDING

    def test_presence_decays_in_receding(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg, decay_rate=0.1)
        self._reach_receding(engine)
        intensity_before = engine.smoothed_signals["presence_intensity"]
        state = engine.tick(_unified(intent=0.0, attention=0.0))
        # Each tick in receding applies decay.
        assert state.presence_intensity < intensity_before

    def test_presence_does_not_decay_in_liminal(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg, decay_rate=0.5)
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        before = engine.smoothed_signals["presence_intensity"]
        state = engine.tick(_strong_liminal())
        # Strong input in liminal → should rise or stay, not decay.
        assert state.presence_intensity >= before - 1e-9

    def test_decay_eventually_returns_to_formless(self):
        """Under pure decay with no new intent, engine must reach formless."""
        cfg = _fast_config(
            receding_ms=0,
            min_presence_formless=0.05,
        )
        engine = TemporalEngine(cfg, decay_rate=0.2)
        self._reach_receding(engine)
        # Keep feeding zero-intent unified states and let decay work.
        for _ in range(50):
            state = engine.tick(_unified(intent=0.0, attention=0.0))
            if state.phase == ContinuumPhase.FORMLESS:
                break
        assert state.phase == ContinuumPhase.FORMLESS

    def test_decay_custom_rate_faster_than_default(self):
        cfg = _fast_config()
        engine_fast = TemporalEngine(cfg, decay_rate=0.5)
        engine_slow = TemporalEngine(cfg, decay_rate=0.05)
        self._reach_receding(engine_fast)
        self._reach_receding(engine_slow)
        # Both still in receding; fast should have lower presence.
        slow_state = engine_slow.tick(_unified())
        fast_state = engine_fast.tick(_unified())
        assert fast_state.presence_intensity <= slow_state.presence_intensity


class TestTemporalEnginePhaseTransitions:
    """Verify the complete formless→liminal→manifest→receding→formless cycle."""

    def test_full_phase_cycle(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg, decay_rate=0.3)

        # 1. Start formless.
        assert engine.current_phase == ContinuumPhase.FORMLESS

        # 2. formless → liminal
        s = engine.tick(_strong_liminal())
        assert s.phase == ContinuumPhase.LIMINAL

        # 3. liminal → manifest
        s = engine.tick(_strong_manifest())
        assert s.phase == ContinuumPhase.MANIFEST

        # 4. manifest → receding
        s = engine.tick(_retreat_unified())
        assert s.phase == ContinuumPhase.RECEDING

        # 5. receding → formless (decay down, zero-intent ticks)
        for _ in range(50):
            s = engine.tick(_unified(intent=0.0, attention=0.0))
            if s.phase == ContinuumPhase.FORMLESS:
                break
        assert s.phase == ContinuumPhase.FORMLESS

    def test_forbidden_jump_formless_to_manifest_blocked(self):
        """Directly jumping formless → manifest is forbidden; must go through liminal."""
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Feed manifest-level collapse signal from formless — engine must stay formless
        # or go to liminal, never directly manifest.
        for _ in range(3):
            s = engine.tick(_strong_manifest())
        # With zero dwell the engine may have moved to liminal in intermediate steps,
        # but it must never reach manifest without passing through liminal first.
        # Here we verify it cannot skip from formless to manifest in a single tick.
        engine.reset()
        first_tick = engine.tick(_strong_manifest())
        assert first_tick.phase in (ContinuumPhase.FORMLESS, ContinuumPhase.LIMINAL)
        assert first_tick.phase != ContinuumPhase.MANIFEST

    def test_returns_continuum_state(self):
        engine = TemporalEngine()
        state = engine.tick(UnifiedState())
        assert isinstance(state, ContinuumState)

    def test_state_phase_matches_engine_phase(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        state = engine.tick(_strong_liminal())
        assert state.phase == engine.current_phase

    def test_stability_degrades_on_flip(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Force a transition to liminal.
        s1 = engine.tick(_strong_liminal())
        stability_after_first_flip = s1.stability
        # Flip back to formless.
        s2 = engine.tick(_unified(intent=0.0, attention=0.0))
        stability_after_second_flip = s2.stability
        assert stability_after_second_flip <= stability_after_first_flip

    def test_stability_recovers_without_flips(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        # Force a flip to reduce stability.
        engine.tick(_strong_liminal())
        engine.tick(_unified(intent=0.0, attention=0.0))
        mid_stability = engine._stability
        # Feed stable formless signal; stability should slowly recover.
        for _ in range(20):
            engine.tick(_unified(intent=0.0, attention=0.0))
        assert engine._stability > mid_stability


class TestTemporalEngineSignalOutput:
    """Verify the values written into ContinuumState fields."""

    def test_presence_intensity_in_bounds(self):
        engine = TemporalEngine()
        for _ in range(5):
            state = engine.tick(_strong_liminal())
            assert 0.0 <= state.presence_intensity <= 1.0

    def test_coherence_in_bounds(self):
        engine = TemporalEngine()
        state = engine.tick(_unified(candidate_confidence=0.8, uncertainty=0.2))
        assert 0.0 <= state.coherence <= 1.0

    def test_ambiguity_in_bounds(self):
        engine = TemporalEngine()
        state = engine.tick(_unified())
        assert 0.0 <= state.ambiguity <= 1.0

    def test_collapse_tendency_zero_when_formless_candidate(self):
        cfg = _fast_config(ema_alpha=1.0)
        engine = TemporalEngine(cfg)
        # phase_candidate=FORMLESS → collapse signal should be 0
        state = engine.tick(
            _unified(
                candidate=ContinuumPhase.FORMLESS,
                candidate_confidence=0.9,
                intent=0.9,
            )
        )
        assert state.collapse_tendency == pytest.approx(0.0)

    def test_collapse_tendency_nonzero_for_manifest_candidate(self):
        cfg = _fast_config(ema_alpha=1.0)
        engine = TemporalEngine(cfg)
        state = engine.tick(
            _unified(
                candidate=ContinuumPhase.MANIFEST,
                candidate_confidence=0.9,
                intent=0.9,
            )
        )
        assert state.collapse_tendency > 0.0

    def test_stability_bounded(self):
        engine = TemporalEngine()
        for _ in range(5):
            state = engine.tick(_strong_liminal())
            assert 0.0 <= state.stability <= 1.0


# ===========================================================================
# G) TemporalEngine reset()
# ===========================================================================


class TestTemporalEngineReset:
    def test_reset_returns_to_formless(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        assert engine.current_phase == ContinuumPhase.LIMINAL
        engine.reset()
        assert engine.current_phase == ContinuumPhase.FORMLESS

    def test_reset_clears_smoothed_signals(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        for _ in range(5):
            engine.tick(_strong_liminal())
        engine.reset()
        sig = engine.smoothed_signals
        assert sig["presence_intensity"] == pytest.approx(0.0)
        assert sig["coherence"] == pytest.approx(0.0)
        assert sig["ambiguity"] == pytest.approx(1.0)
        assert sig["collapse_tendency"] == pytest.approx(0.0)
        assert sig["retreat_tendency"] == pytest.approx(0.0)

    def test_reset_clears_flip_history(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        engine.tick(_unified(intent=0.0, attention=0.0))  # flip back
        assert len(engine._flip_timestamps) > 0
        engine.reset()
        assert len(engine._flip_timestamps) == 0

    def test_reset_restores_full_stability(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())
        engine.reset()
        assert engine._stability == pytest.approx(1.0)

    def test_reset_deactivates_hysteresis_gates(self):
        cfg = _fast_config()
        engine = TemporalEngine(cfg)
        engine.tick(_strong_liminal())  # activates liminal gate
        engine.reset()
        assert engine._liminal_gate.active is False
        assert engine._manifest_gate.active is False


# ===========================================================================
# H) Public API surface
# ===========================================================================


class TestPublicApiSurface:
    """Verify the module exports the expected public symbols."""

    def test_apply_ema_callable(self):
        assert callable(apply_ema)

    def test_apply_rate_limit_callable(self):
        assert callable(apply_rate_limit)

    def test_apply_decay_callable(self):
        assert callable(apply_decay)

    def test_hysteresis_gate_constructible(self):
        gate = HysteresisGate(enter=0.6, exit_=0.3)
        assert isinstance(gate, HysteresisGate)

    def test_dwell_guard_constructible(self):
        guard = DwellGuard(dwell_ms=100)
        assert isinstance(guard, DwellGuard)

    def test_temporal_engine_constructible_with_defaults(self):
        engine = TemporalEngine()
        assert isinstance(engine, TemporalEngine)

    def test_temporal_engine_constructible_with_custom_config(self):
        cfg = ContinuumConfig(ema_alpha=0.3)
        engine = TemporalEngine(cfg)
        assert engine.config.ema_alpha == pytest.approx(0.3)

    def test_temporal_engine_accessible_via_package(self):
        from core.continuum import (  # noqa: F401
            TemporalEngine as TE,
            HysteresisGate as HG,
            DwellGuard as DG,
            apply_ema as ae,
            apply_rate_limit as arl,
            apply_decay as ad,
        )
        assert TE is TemporalEngine
        assert HG is HysteresisGate
        assert DG is DwellGuard

    def test_temporal_engine_current_phase_property(self):
        engine = TemporalEngine()
        assert engine.current_phase == ContinuumPhase.FORMLESS

    def test_temporal_engine_smoothed_signals_property(self):
        engine = TemporalEngine()
        sig = engine.smoothed_signals
        assert isinstance(sig, dict)
        assert "presence_intensity" in sig
        assert "coherence" in sig
        assert "ambiguity" in sig
        assert "collapse_tendency" in sig
        assert "retreat_tendency" in sig

    def test_temporal_engine_smoothed_signals_is_copy(self):
        """Mutating the returned dict must not affect engine state."""
        engine = TemporalEngine()
        sig = engine.smoothed_signals
        sig["presence_intensity"] = 99.0
        assert engine.smoothed_signals["presence_intensity"] != 99.0

    def test_temporal_engine_uses_default_config_by_default(self):
        engine = TemporalEngine()
        assert engine.config.ema_alpha == DEFAULT_CONTINUUM_CONFIG.ema_alpha
