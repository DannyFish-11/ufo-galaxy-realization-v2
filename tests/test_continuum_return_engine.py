"""
tests/test_continuum_return_engine.py
=======================================

Unit tests for core.continuum.return_engine.

Test groups
-----------
  A) ReturnTrigger enum values.
  B) ReturnAction enum values.
  C) ReturnResult dataclass construction and immutability.
  D) ReturnEngine construction (default and custom config).
  E) evaluate() — no trigger fires when state is healthy.
  F) evaluate() — user_cancel trigger (highest priority).
  G) evaluate() — high_uncertainty trigger.
  H) evaluate() — finished trigger.
  I) evaluate() — timeout trigger.
  J) evaluate() — low_value trigger (soft decay).
  K) Trigger priority ordering.
  L) step_down phase logic.
  M) force_return() always returns to formless.
  N) Output bounds and types.
  O) Integration: DecisionGate score feeds return engine.
"""

from __future__ import annotations

import pytest

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.decision_gate import DecisionGate
from core.continuum.return_engine import (
    ReturnAction,
    ReturnEngine,
    ReturnResult,
    ReturnTrigger,
    _step_down_phase,
)
from core.continuum.state_fusion import StateFusion
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
    HumanFieldState,
    UnifiedState,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(
    phase: ContinuumPhase = ContinuumPhase.MANIFEST,
    presence_intensity: float = 0.7,
    stability: float = 1.0,
    decision_risk_cost: float = 0.0,
) -> ContinuumState:
    """Build a minimal ContinuumState for testing."""
    return ContinuumState(
        phase=phase,
        presence_intensity=presence_intensity,
        stability=stability,
        decision=DecisionState(
            should_act_score=0.5,
            action_level=ActionLevel.ASSIST,
            risk_cost=decision_risk_cost,
        ),
    )


def _engine(**kwargs) -> ReturnEngine:
    return ReturnEngine(**kwargs)


# ---------------------------------------------------------------------------
# A) ReturnTrigger enum
# ---------------------------------------------------------------------------


class TestReturnTriggerEnum:
    def test_all_expected_values_present(self):
        values = {t.value for t in ReturnTrigger}
        assert values == {"finished", "timeout", "low_value", "high_uncertainty", "user_cancel"}

    def test_string_enum(self):
        assert ReturnTrigger.FINISHED == "finished"
        assert ReturnTrigger.TIMEOUT == "timeout"
        assert ReturnTrigger.LOW_VALUE == "low_value"
        assert ReturnTrigger.HIGH_UNCERTAINTY == "high_uncertainty"
        assert ReturnTrigger.USER_CANCEL == "user_cancel"


# ---------------------------------------------------------------------------
# B) ReturnAction enum
# ---------------------------------------------------------------------------


class TestReturnActionEnum:
    def test_all_expected_values_present(self):
        values = {a.value for a in ReturnAction}
        assert values == {"hold", "soft_decay", "step_down", "return_to_formless"}

    def test_string_enum(self):
        assert ReturnAction.HOLD == "hold"
        assert ReturnAction.SOFT_DECAY == "soft_decay"
        assert ReturnAction.STEP_DOWN == "step_down"
        assert ReturnAction.RETURN_TO_FORMLESS == "return_to_formless"


# ---------------------------------------------------------------------------
# C) ReturnResult dataclass
# ---------------------------------------------------------------------------


class TestReturnResult:
    def test_construction(self):
        r = ReturnResult(
            should_return=True,
            trigger=ReturnTrigger.FINISHED,
            return_action=ReturnAction.STEP_DOWN,
            reason="test",
            next_phase=ContinuumPhase.RECEDING,
            decay_amount=0.0,
        )
        assert r.should_return is True
        assert r.trigger == ReturnTrigger.FINISHED
        assert r.return_action == ReturnAction.STEP_DOWN
        assert r.next_phase == ContinuumPhase.RECEDING

    def test_immutable(self):
        r = ReturnResult(
            should_return=False,
            trigger=None,
            return_action=ReturnAction.HOLD,
            reason="hold",
        )
        with pytest.raises((AttributeError, TypeError)):
            r.should_return = True  # type: ignore[misc]

    def test_defaults(self):
        r = ReturnResult(
            should_return=False,
            trigger=None,
            return_action=ReturnAction.HOLD,
            reason="hold",
        )
        assert r.next_phase is None
        assert r.decay_amount == 0.0


# ---------------------------------------------------------------------------
# D) ReturnEngine construction
# ---------------------------------------------------------------------------


class TestReturnEngineConstruction:
    def test_default_construction(self):
        engine = ReturnEngine()
        assert engine is not None

    def test_custom_config(self):
        cfg = ContinuumConfig()
        engine = ReturnEngine(config=cfg)
        assert engine._cfg is cfg

    def test_custom_thresholds(self):
        engine = ReturnEngine(
            low_value_threshold=0.05,
            high_uncertainty_threshold=0.70,
            soft_decay_amount=0.10,
        )
        assert engine._low_value_threshold == pytest.approx(0.05)
        assert engine._high_uncertainty_threshold == pytest.approx(0.70)
        assert engine._soft_decay_amount == pytest.approx(0.10)

    def test_thresholds_clamped(self):
        engine = ReturnEngine(
            low_value_threshold=2.0,
            high_uncertainty_threshold=-1.0,
        )
        assert engine._low_value_threshold == pytest.approx(1.0)
        assert engine._high_uncertainty_threshold == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# E) evaluate() — no trigger fires (hold)
# ---------------------------------------------------------------------------


class TestEvaluateNoTrigger:
    def test_healthy_state_returns_hold(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.MANIFEST, stability=1.0)
        result = engine.evaluate(state, elapsed_ms=100, decision_score=0.5)

        assert result.should_return is False
        assert result.return_action == ReturnAction.HOLD
        assert result.trigger is None

    def test_formless_with_timeout_stays_hold(self):
        """Timeout should not fire when already in formless."""
        engine = _engine()
        state = _state(phase=ContinuumPhase.FORMLESS)
        result = engine.evaluate(state, elapsed_ms=99999)
        assert result.should_return is False

    def test_high_score_no_low_value_trigger(self):
        engine = _engine(low_value_threshold=0.10)
        state = _state()
        result = engine.evaluate(state, decision_score=0.80)
        assert result.trigger != ReturnTrigger.LOW_VALUE

    def test_reason_non_empty_for_hold(self):
        engine = _engine()
        result = engine.evaluate(_state())
        assert len(result.reason) > 0


# ---------------------------------------------------------------------------
# F) evaluate() — user_cancel
# ---------------------------------------------------------------------------


class TestUserCancelTrigger:
    def test_user_cancel_fires_hard_return(self):
        engine = _engine()
        result = engine.evaluate(_state(), user_cancel=True)

        assert result.should_return is True
        assert result.trigger == ReturnTrigger.USER_CANCEL
        assert result.return_action == ReturnAction.RETURN_TO_FORMLESS
        assert result.next_phase == ContinuumPhase.FORMLESS

    def test_user_cancel_in_formless(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.FORMLESS)
        result = engine.evaluate(state, user_cancel=True)
        assert result.trigger == ReturnTrigger.USER_CANCEL

    def test_user_cancel_reason_contains_trigger(self):
        engine = _engine()
        result = engine.evaluate(_state(), user_cancel=True)
        assert "user_cancel" in result.reason


# ---------------------------------------------------------------------------
# G) evaluate() — high_uncertainty
# ---------------------------------------------------------------------------


class TestHighUncertaintyTrigger:
    def test_low_stability_triggers_high_uncertainty(self):
        engine = _engine(high_uncertainty_threshold=0.85)
        # stability=0.05 → effective_uncertainty = 0.95 > 0.85
        state = _state(stability=0.05)
        result = engine.evaluate(state)

        assert result.should_return is True
        assert result.trigger == ReturnTrigger.HIGH_UNCERTAINTY
        assert result.return_action == ReturnAction.RETURN_TO_FORMLESS
        assert result.next_phase == ContinuumPhase.FORMLESS

    def test_high_stability_no_uncertainty_trigger(self):
        engine = _engine(high_uncertainty_threshold=0.85)
        state = _state(stability=0.9)
        result = engine.evaluate(state)
        assert result.trigger != ReturnTrigger.HIGH_UNCERTAINTY

    def test_reason_contains_uncertainty_value(self):
        engine = _engine(high_uncertainty_threshold=0.85)
        state = _state(stability=0.0)
        result = engine.evaluate(state)
        assert "uncertainty" in result.reason.lower()


# ---------------------------------------------------------------------------
# H) evaluate() — finished
# ---------------------------------------------------------------------------


class TestFinishedTrigger:
    def test_finished_from_manifest(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, finished=True)

        assert result.should_return is True
        assert result.trigger == ReturnTrigger.FINISHED
        assert result.return_action == ReturnAction.STEP_DOWN
        assert result.next_phase == ContinuumPhase.RECEDING

    def test_finished_from_receding(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.RECEDING)
        result = engine.evaluate(state, finished=True)

        assert result.next_phase == ContinuumPhase.FORMLESS

    def test_finished_from_liminal(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.LIMINAL)
        result = engine.evaluate(state, finished=True)

        assert result.next_phase == ContinuumPhase.FORMLESS

    def test_finished_reason_contains_phase(self):
        engine = _engine()
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, finished=True)
        assert "manifest" in result.reason


# ---------------------------------------------------------------------------
# I) evaluate() — timeout
# ---------------------------------------------------------------------------


class TestTimeoutTrigger:
    def test_timeout_fires_after_threshold(self):
        cfg = ContinuumConfig(timeout_receding_ms=5000)
        engine = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, elapsed_ms=5001)

        assert result.should_return is True
        assert result.trigger == ReturnTrigger.TIMEOUT
        assert result.return_action == ReturnAction.STEP_DOWN

    def test_timeout_does_not_fire_before_threshold(self):
        cfg = ContinuumConfig(timeout_receding_ms=5000)
        engine = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, elapsed_ms=4999)

        assert result.trigger != ReturnTrigger.TIMEOUT

    def test_timeout_step_down_from_manifest(self):
        cfg = ContinuumConfig(timeout_receding_ms=1000)
        engine = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, elapsed_ms=2000)
        assert result.next_phase == ContinuumPhase.RECEDING

    def test_timeout_reason_contains_elapsed(self):
        cfg = ContinuumConfig(timeout_receding_ms=1000)
        engine = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, elapsed_ms=2000)
        assert "elapsed" in result.reason.lower()
        assert "2000" in result.reason


# ---------------------------------------------------------------------------
# J) evaluate() — low_value
# ---------------------------------------------------------------------------


class TestLowValueTrigger:
    def test_low_score_fires_soft_decay(self):
        engine = _engine(low_value_threshold=0.10)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, decision_score=0.05)

        assert result.should_return is True
        assert result.trigger == ReturnTrigger.LOW_VALUE
        assert result.return_action == ReturnAction.SOFT_DECAY
        assert result.decay_amount > 0.0

    def test_score_none_skips_low_value(self):
        engine = _engine(low_value_threshold=0.10)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, decision_score=None)
        assert result.trigger != ReturnTrigger.LOW_VALUE

    def test_low_value_not_in_formless(self):
        engine = _engine(low_value_threshold=0.10)
        state = _state(phase=ContinuumPhase.FORMLESS)
        result = engine.evaluate(state, decision_score=0.01)
        assert result.trigger != ReturnTrigger.LOW_VALUE

    def test_decay_amount_positive(self):
        engine = _engine(low_value_threshold=0.10, soft_decay_amount=0.08)
        state = _state(phase=ContinuumPhase.LIMINAL)
        result = engine.evaluate(state, decision_score=0.02)
        assert result.decay_amount == pytest.approx(0.08)

    def test_low_value_next_phase_is_none(self):
        engine = _engine(low_value_threshold=0.10)
        state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(state, decision_score=0.05)
        assert result.next_phase is None


# ---------------------------------------------------------------------------
# K) Trigger priority ordering
# ---------------------------------------------------------------------------


class TestTriggerPriority:
    def test_user_cancel_beats_finished(self):
        engine = _engine()
        state = _state(stability=1.0)
        result = engine.evaluate(state, user_cancel=True, finished=True)
        assert result.trigger == ReturnTrigger.USER_CANCEL

    def test_user_cancel_beats_timeout(self):
        engine = _engine()
        cfg = ContinuumConfig(timeout_receding_ms=100)
        engine2 = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST)
        # elapsed_ms=9999 far exceeds timeout_receding_ms=100
        result = engine2.evaluate(state, elapsed_ms=9999, user_cancel=True)
        assert result.trigger == ReturnTrigger.USER_CANCEL

    def test_high_uncertainty_beats_finished(self):
        engine = _engine(high_uncertainty_threshold=0.80)
        state = _state(stability=0.05)  # effective_uncertainty = 0.95 > 0.80
        result = engine.evaluate(state, finished=True)
        assert result.trigger == ReturnTrigger.HIGH_UNCERTAINTY

    def test_finished_beats_timeout(self):
        cfg = ContinuumConfig(timeout_receding_ms=100)
        engine = ReturnEngine(config=cfg)
        state = _state(phase=ContinuumPhase.MANIFEST, stability=1.0)
        result = engine.evaluate(state, elapsed_ms=9999, finished=True)
        assert result.trigger == ReturnTrigger.FINISHED

    def test_timeout_beats_low_value(self):
        cfg = ContinuumConfig(timeout_receding_ms=100)
        engine = ReturnEngine(config=cfg, low_value_threshold=0.50)
        state = _state(phase=ContinuumPhase.MANIFEST, stability=1.0)
        result = engine.evaluate(state, elapsed_ms=9999, decision_score=0.01)
        assert result.trigger == ReturnTrigger.TIMEOUT


# ---------------------------------------------------------------------------
# L) step_down phase logic
# ---------------------------------------------------------------------------


class TestStepDownPhase:
    def test_manifest_to_receding(self):
        assert _step_down_phase(ContinuumPhase.MANIFEST) == ContinuumPhase.RECEDING

    def test_receding_to_formless(self):
        assert _step_down_phase(ContinuumPhase.RECEDING) == ContinuumPhase.FORMLESS

    def test_liminal_to_formless(self):
        assert _step_down_phase(ContinuumPhase.LIMINAL) == ContinuumPhase.FORMLESS

    def test_formless_stays_formless(self):
        assert _step_down_phase(ContinuumPhase.FORMLESS) == ContinuumPhase.FORMLESS


# ---------------------------------------------------------------------------
# M) force_return()
# ---------------------------------------------------------------------------


class TestForceReturn:
    def test_force_return_always_to_formless(self):
        engine = _engine()
        for phase in ContinuumPhase:
            state = _state(phase=phase)
            result = engine.force_return(state)
            assert result.return_action == ReturnAction.RETURN_TO_FORMLESS
            assert result.next_phase == ContinuumPhase.FORMLESS
            assert result.should_return is True

    def test_force_return_custom_trigger(self):
        engine = _engine()
        result = engine.force_return(_state(), trigger=ReturnTrigger.TIMEOUT)
        assert result.trigger == ReturnTrigger.TIMEOUT

    def test_force_return_default_trigger_is_user_cancel(self):
        engine = _engine()
        result = engine.force_return(_state())
        assert result.trigger == ReturnTrigger.USER_CANCEL

    def test_force_return_reason_non_empty(self):
        engine = _engine()
        result = engine.force_return(_state())
        assert len(result.reason) > 0


# ---------------------------------------------------------------------------
# N) Output bounds and types
# ---------------------------------------------------------------------------


class TestOutputBoundsAndTypes:
    @pytest.mark.parametrize(
        "phase,stability",
        [
            (ContinuumPhase.FORMLESS, 1.0),
            (ContinuumPhase.LIMINAL, 0.9),
            (ContinuumPhase.MANIFEST, 0.5),
            (ContinuumPhase.RECEDING, 0.2),
        ],
    )
    def test_decay_amount_bounded(self, phase, stability):
        engine = _engine()
        state = _state(phase=phase, stability=stability)
        result = engine.evaluate(state, decision_score=0.05)
        assert 0.0 <= result.decay_amount <= 1.0

    def test_result_types(self):
        engine = _engine()
        result = engine.evaluate(_state())
        assert isinstance(result.should_return, bool)
        assert isinstance(result.return_action, ReturnAction)
        assert isinstance(result.reason, str)
        if result.trigger is not None:
            assert isinstance(result.trigger, ReturnTrigger)
        if result.next_phase is not None:
            assert isinstance(result.next_phase, ContinuumPhase)


# ---------------------------------------------------------------------------
# O) Integration: DecisionGate score feeds ReturnEngine
# ---------------------------------------------------------------------------


class TestIntegrationWithDecisionGate:
    def test_pipeline_low_intent_produces_soft_decay(self):
        """A very low-intent state should produce a low decision score,
        which the return engine should flag as low_value."""
        gate = DecisionGate(timing_penalty=0.5)
        engine = ReturnEngine(low_value_threshold=0.15)

        state = UnifiedState(
            human=HumanFieldState(
                intent_probability=0.02,
                focus_level=0.9,
                interruption_sensitivity=0.9,
            ),
            context_utility=0.01,
            urgency=0.0,
            action_risk=0.5,
            uncertainty=0.9,
        )
        decision = gate.evaluate(state)
        cont_state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(cont_state, decision_score=decision.should_act_score)

        # Low-intent state → score below threshold → soft decay expected.
        assert result.trigger == ReturnTrigger.LOW_VALUE
        assert result.return_action == ReturnAction.SOFT_DECAY

    def test_pipeline_high_intent_no_return(self):
        """A strong-intent state with low cost should produce a high score,
        so the return engine should hold."""
        gate = DecisionGate(timing_penalty=0.1)
        engine = ReturnEngine(low_value_threshold=0.10)

        state = UnifiedState(
            human=HumanFieldState(
                intent_probability=0.9,
                focus_level=0.2,
                interruption_sensitivity=0.1,
            ),
            context_utility=0.85,
            urgency=0.8,
            action_risk=0.05,
            uncertainty=0.1,
        )
        decision = gate.evaluate(state)
        cont_state = _state(phase=ContinuumPhase.MANIFEST)
        result = engine.evaluate(cont_state, decision_score=decision.should_act_score)

        assert result.trigger != ReturnTrigger.LOW_VALUE
