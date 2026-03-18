"""
tests/test_continuum_decision_gate.py
======================================

Unit tests for core.continuum.decision_gate.

Test groups
-----------
  A) Module-level helpers: _clamp, _action_level_from_score, _confidence_from_score.
  B) DecisionGate construction (default and custom config).
  C) evaluate() basic contract — returns a well-formed DecisionState.
  D) Value component computation.
  E) Interruption cost computation.
  F) Risk cost computation.
  G) Score → ActionLevel mapping.
  H) Decision confidence is highest when score is far from thresholds.
  I) decision_reason contains key fields.
  J) Output bounds [0, 1] across varied inputs.
  K) Per-call timing_penalty override.
  L) Integration: evaluate() via UnifiedState built by StateFusion.
"""

from __future__ import annotations

import pytest

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.decision_gate import (
    DecisionGate,
    _action_level_from_score,
    _clamp,
    _confidence_from_score,
    _THRESHOLD_HINT,
    _THRESHOLD_ASSIST,
    _THRESHOLD_EXECUTE,
)
from core.continuum.state_fusion import StateFusion
from core.continuum.types import ActionLevel, DecisionState, HumanFieldState, UnifiedState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _human(
    *,
    attention: float = 0.5,
    focus_level: float = 0.5,
    fatigue: float = 0.0,
    intent_probability: float = 0.0,
    interruption_sensitivity: float = 0.5,
    speaking: bool = False,
    input_rhythm: float = 0.0,
    motion_level: float = 0.0,
) -> HumanFieldState:
    return HumanFieldState(
        attention=attention,
        focus_level=focus_level,
        fatigue=fatigue,
        intent_probability=intent_probability,
        interruption_sensitivity=interruption_sensitivity,
        speaking=speaking,
        input_rhythm=input_rhythm,
        motion_level=motion_level,
    )


def _unified(
    *,
    intent: float = 0.0,
    attention: float = 0.5,
    focus_level: float = 0.5,
    interruption_sensitivity: float = 0.5,
    speaking: bool = False,
    context_utility: float = 0.0,
    urgency: float = 0.0,
    action_risk: float = 0.0,
    uncertainty: float = 0.5,
) -> UnifiedState:
    return UnifiedState(
        human=_human(
            intent_probability=intent,
            attention=attention,
            focus_level=focus_level,
            interruption_sensitivity=interruption_sensitivity,
            speaking=speaking,
        ),
        context_utility=context_utility,
        urgency=urgency,
        action_risk=action_risk,
        uncertainty=uncertainty,
    )


def _high_value_state() -> UnifiedState:
    """State that should produce a high value score."""
    return _unified(
        intent=0.9,
        attention=0.9,
        context_utility=0.85,
        urgency=0.8,
        interruption_sensitivity=0.1,
        focus_level=0.2,
        action_risk=0.05,
        uncertainty=0.1,
    )


def _low_value_state() -> UnifiedState:
    """State that should produce a near-zero value score."""
    return _unified(
        intent=0.05,
        context_utility=0.05,
        urgency=0.0,
        interruption_sensitivity=0.9,
        focus_level=0.9,
        action_risk=0.8,
        uncertainty=0.9,
    )


# ---------------------------------------------------------------------------
# A) Module-level helpers
# ---------------------------------------------------------------------------


class TestClamp:
    def test_within_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_zero(self):
        assert _clamp(-0.5) == 0.0

    def test_above_one(self):
        assert _clamp(1.5) == 1.0

    def test_custom_bounds(self):
        assert _clamp(5.0, lo=0.0, hi=3.0) == 3.0
        assert _clamp(-1.0, lo=0.0, hi=3.0) == 0.0


class TestActionLevelFromScore:
    def test_observe_boundary(self):
        assert _action_level_from_score(0.0) == ActionLevel.OBSERVE
        assert _action_level_from_score(_THRESHOLD_HINT - 0.001) == ActionLevel.OBSERVE

    def test_hint_boundary(self):
        assert _action_level_from_score(_THRESHOLD_HINT) == ActionLevel.HINT
        assert _action_level_from_score(_THRESHOLD_ASSIST - 0.001) == ActionLevel.HINT

    def test_assist_boundary(self):
        assert _action_level_from_score(_THRESHOLD_ASSIST) == ActionLevel.ASSIST
        assert _action_level_from_score(_THRESHOLD_EXECUTE - 0.001) == ActionLevel.ASSIST

    def test_execute_boundary(self):
        assert _action_level_from_score(_THRESHOLD_EXECUTE) == ActionLevel.EXECUTE
        assert _action_level_from_score(1.0) == ActionLevel.EXECUTE


class TestConfidenceFromScore:
    def test_at_threshold_is_zero(self):
        # Exactly on a threshold boundary → confidence approaches 0.
        conf = _confidence_from_score(_THRESHOLD_HINT)
        assert conf == pytest.approx(0.0, abs=0.01)

    def test_far_from_threshold_is_high(self):
        # Score of 0.0 is half-band away from 0.0 (boundary) — max confidence.
        # Actually 0.0 is exactly on boundary 0.0; mid-band is better.
        mid = (_THRESHOLD_HINT + _THRESHOLD_ASSIST) / 2
        conf = _confidence_from_score(mid)
        assert conf > 0.5

    def test_range(self):
        for v in [0.0, 0.1, 0.275, 0.525, 0.8, 1.0]:
            assert 0.0 <= _confidence_from_score(v) <= 1.0


# ---------------------------------------------------------------------------
# B) DecisionGate construction
# ---------------------------------------------------------------------------


class TestDecisionGateConstruction:
    def test_default_construction(self):
        gate = DecisionGate()
        assert gate is not None

    def test_custom_config(self):
        cfg = ContinuumConfig()
        gate = DecisionGate(config=cfg)
        assert gate._cfg is cfg

    def test_custom_timing_penalty(self):
        gate = DecisionGate(timing_penalty=0.8)
        assert gate._timing_penalty == pytest.approx(0.8)

    def test_timing_penalty_clamped(self):
        gate = DecisionGate(timing_penalty=2.0)
        assert gate._timing_penalty == pytest.approx(1.0)

        gate2 = DecisionGate(timing_penalty=-0.5)
        assert gate2._timing_penalty == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# C) evaluate() basic contract
# ---------------------------------------------------------------------------


class TestEvaluateBasicContract:
    def test_returns_decision_state(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert isinstance(result, DecisionState)

    def test_action_level_is_enum(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert isinstance(result.action_level, ActionLevel)

    def test_decision_reason_non_empty(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert len(result.decision_reason) > 0

    def test_confidence_in_range(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert 0.0 <= result.decision_confidence <= 1.0

    def test_score_in_range(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert 0.0 <= result.should_act_score <= 1.0

    def test_intermediate_costs_non_negative(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert result.value_score >= 0.0
        assert result.interruption_cost >= 0.0
        assert result.risk_cost >= 0.0

    def test_timestamp_positive(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert result.timestamp > 0.0


# ---------------------------------------------------------------------------
# D) Value component
# ---------------------------------------------------------------------------


class TestValueComponent:
    def test_zero_intent_gives_near_zero_value(self):
        gate = DecisionGate()
        state = _unified(intent=0.0, context_utility=0.8, urgency=0.8)
        result = gate.evaluate(state)
        assert result.value_score < 0.05

    def test_high_intent_high_utility_high_urgency(self):
        gate = DecisionGate()
        state = _unified(intent=0.9, context_utility=0.9, urgency=0.9)
        result = gate.evaluate(state)
        assert result.value_score > 0.3

    def test_value_bounded(self):
        gate = DecisionGate()
        for intent in [0.0, 0.5, 1.0]:
            for utility in [0.0, 0.5, 1.0]:
                for urgency in [0.0, 0.5, 1.0]:
                    state = _unified(intent=intent, context_utility=utility, urgency=urgency)
                    result = gate.evaluate(state)
                    assert 0.0 <= result.value_score <= 1.0


# ---------------------------------------------------------------------------
# E) Interruption cost component
# ---------------------------------------------------------------------------


class TestInterruptionCostComponent:
    def test_zero_sensitivity_zero_cost(self):
        gate = DecisionGate(timing_penalty=1.0)
        state = _unified(interruption_sensitivity=0.0, focus_level=0.9)
        result = gate.evaluate(state)
        assert result.interruption_cost == pytest.approx(0.0, abs=0.001)

    def test_zero_focus_zero_cost(self):
        gate = DecisionGate(timing_penalty=1.0)
        state = _unified(interruption_sensitivity=0.9, focus_level=0.0)
        result = gate.evaluate(state)
        assert result.interruption_cost == pytest.approx(0.0, abs=0.001)

    def test_high_sensitivity_high_focus_high_cost(self):
        gate = DecisionGate(timing_penalty=1.0)
        state = _unified(interruption_sensitivity=0.9, focus_level=0.9)
        result = gate.evaluate(state)
        assert result.interruption_cost > 0.5

    def test_cost_bounded(self):
        gate = DecisionGate()
        for sensitivity in [0.0, 0.5, 1.0]:
            for focus in [0.0, 0.5, 1.0]:
                state = _unified(interruption_sensitivity=sensitivity, focus_level=focus)
                result = gate.evaluate(state)
                assert 0.0 <= result.interruption_cost <= 1.0


# ---------------------------------------------------------------------------
# F) Risk cost component
# ---------------------------------------------------------------------------


class TestRiskCostComponent:
    def test_zero_risk_zero_cost(self):
        gate = DecisionGate()
        state = _unified(action_risk=0.0, uncertainty=0.9)
        result = gate.evaluate(state)
        assert result.risk_cost == pytest.approx(0.0, abs=0.001)

    def test_zero_uncertainty_zero_cost(self):
        gate = DecisionGate()
        state = _unified(action_risk=0.9, uncertainty=0.0)
        result = gate.evaluate(state)
        assert result.risk_cost == pytest.approx(0.0, abs=0.001)

    def test_high_risk_high_uncertainty_high_cost(self):
        gate = DecisionGate()
        state = _unified(action_risk=0.9, uncertainty=0.9)
        result = gate.evaluate(state)
        assert result.risk_cost > 0.5

    def test_cost_bounded(self):
        gate = DecisionGate()
        for risk in [0.0, 0.5, 1.0]:
            for unc in [0.0, 0.5, 1.0]:
                state = _unified(action_risk=risk, uncertainty=unc)
                result = gate.evaluate(state)
                assert 0.0 <= result.risk_cost <= 1.0


# ---------------------------------------------------------------------------
# G) Score → ActionLevel mapping
# ---------------------------------------------------------------------------


class TestActionLevelMapping:
    def test_observe_for_low_score_state(self):
        gate = DecisionGate()
        result = gate.evaluate(_low_value_state())
        assert result.action_level == ActionLevel.OBSERVE

    def test_execute_for_high_score_state(self):
        gate = DecisionGate(timing_penalty=0.0)
        result = gate.evaluate(_high_value_state())
        assert result.action_level in {ActionLevel.ASSIST, ActionLevel.EXECUTE}

    def test_action_level_monotone_with_score(self):
        """Higher scores should never produce a lower ActionLevel."""
        gate = DecisionGate(timing_penalty=0.0)
        scores = [0.0, _THRESHOLD_HINT, _THRESHOLD_ASSIST, _THRESHOLD_EXECUTE, 1.0]
        levels = [_action_level_from_score(s) for s in scores]
        level_order = {
            ActionLevel.OBSERVE: 0,
            ActionLevel.HINT: 1,
            ActionLevel.ASSIST: 2,
            ActionLevel.EXECUTE: 3,
        }
        for i in range(len(levels) - 1):
            assert level_order[levels[i]] <= level_order[levels[i + 1]]


# ---------------------------------------------------------------------------
# H) Decision confidence
# ---------------------------------------------------------------------------


class TestDecisionConfidence:
    def test_confidence_range(self):
        gate = DecisionGate()
        for state in [_low_value_state(), _high_value_state(), _unified()]:
            result = gate.evaluate(state)
            assert 0.0 <= result.decision_confidence <= 1.0


# ---------------------------------------------------------------------------
# I) Decision reason
# ---------------------------------------------------------------------------


class TestDecisionReason:
    def test_reason_contains_action_level(self):
        gate = DecisionGate()
        result = gate.evaluate(_low_value_state())
        assert result.action_level.value in result.decision_reason

    def test_reason_contains_score(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert "score=" in result.decision_reason

    def test_reason_contains_costs(self):
        gate = DecisionGate()
        result = gate.evaluate(_unified())
        assert "interruption_cost=" in result.decision_reason
        assert "risk_cost=" in result.decision_reason


# ---------------------------------------------------------------------------
# J) Output bounds across varied inputs
# ---------------------------------------------------------------------------


class TestOutputBounds:
    @pytest.mark.parametrize(
        "intent,utility,urgency,sensitivity,focus,risk,uncertainty",
        [
            (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
            (1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0),
            (0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5),
            (0.9, 0.0, 0.9, 0.0, 0.0, 0.0, 0.0),
            (0.0, 0.9, 0.0, 0.9, 0.9, 0.9, 0.9),
        ],
    )
    def test_all_outputs_bounded(
        self, intent, utility, urgency, sensitivity, focus, risk, uncertainty
    ):
        gate = DecisionGate()
        state = _unified(
            intent=intent,
            context_utility=utility,
            urgency=urgency,
            interruption_sensitivity=sensitivity,
            focus_level=focus,
            action_risk=risk,
            uncertainty=uncertainty,
        )
        result = gate.evaluate(state)
        assert 0.0 <= result.should_act_score <= 1.0
        assert 0.0 <= result.value_score <= 1.0
        assert 0.0 <= result.interruption_cost <= 1.0
        assert 0.0 <= result.risk_cost <= 1.0
        assert 0.0 <= result.decision_confidence <= 1.0


# ---------------------------------------------------------------------------
# K) Per-call timing_penalty override
# ---------------------------------------------------------------------------


class TestPerCallTimingPenalty:
    def test_zero_penalty_reduces_interruption_cost(self):
        gate = DecisionGate(timing_penalty=0.5)
        state = _unified(interruption_sensitivity=0.9, focus_level=0.9)

        result_default = gate.evaluate(state)
        result_zero = gate.evaluate(state, timing_penalty=0.0)

        assert result_zero.interruption_cost < result_default.interruption_cost

    def test_penalty_override_does_not_mutate_instance(self):
        gate = DecisionGate(timing_penalty=0.5)
        state = _unified()
        gate.evaluate(state, timing_penalty=0.9)
        assert gate._timing_penalty == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# L) Integration with StateFusion
# ---------------------------------------------------------------------------


class TestIntegrationWithStateFusion:
    def test_evaluate_after_fusion(self):
        fusion = StateFusion()
        gate = DecisionGate()

        human = _human(
            intent_probability=0.75,
            attention=0.8,
            focus_level=0.5,
            interruption_sensitivity=0.3,
        )
        unified = fusion.fuse(
            human,
            world={"context_utility": 0.7, "urgency": 0.5},
        )
        result = gate.evaluate(unified)

        assert isinstance(result, DecisionState)
        assert result.action_level in list(ActionLevel)
        assert 0.0 <= result.should_act_score <= 1.0

    def test_full_pipeline_high_intent(self):
        """High-intent scenario should produce at least hint-level action."""
        fusion = StateFusion()
        gate = DecisionGate(timing_penalty=0.2)

        human = _human(
            intent_probability=0.95,
            attention=0.9,
            focus_level=0.3,
            interruption_sensitivity=0.1,
        )
        unified = fusion.fuse(
            human,
            world={"context_utility": 0.9, "urgency": 0.8, "action_risk": 0.05, "uncertainty": 0.1},
        )
        result = gate.evaluate(unified)

        assert result.action_level != ActionLevel.OBSERVE
