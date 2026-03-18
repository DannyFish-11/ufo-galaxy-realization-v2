"""
tests/test_continuum_liminal_field.py
======================================

Unit tests for core.continuum.liminal_field.

Test groups
-----------
  A) LiminalMetrics dataclass.
  B) LiminalFieldEngine construction.
  C) compute() with a minimal / default UnifiedState.
  D) coherence computation.
  E) ambiguity computation.
  F) collapse_tendency computation.
  G) intervention_window computation.
  H) enrich_unified() phase-candidate promotion.
  I) History influence on coherence.
  J) Output bounds [0, 1] across varied inputs.
  K) StateFusion integration (fuse → compute pipeline).
"""

from __future__ import annotations

import pytest

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG, HysteresisConfig
from core.continuum.liminal_field import LiminalFieldEngine, LiminalMetrics
from core.continuum.state_fusion import StateFusion
from core.continuum.types import ContinuumPhase, HumanFieldState, UnifiedState


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
    fatigue: float = 0.0,
    interruption_sensitivity: float = 0.5,
    speaking: bool = False,
    context_utility: float = 0.0,
    urgency: float = 0.0,
    action_risk: float = 0.0,
    uncertainty: float = 0.5,
    phase_candidate: ContinuumPhase = ContinuumPhase.FORMLESS,
    candidate_confidence: float = 0.0,
) -> UnifiedState:
    return UnifiedState(
        human=_human(
            intent_probability=intent,
            attention=attention,
            focus_level=focus_level,
            fatigue=fatigue,
            interruption_sensitivity=interruption_sensitivity,
            speaking=speaking,
        ),
        context_utility=context_utility,
        urgency=urgency,
        action_risk=action_risk,
        uncertainty=uncertainty,
        phase_candidate=phase_candidate,
        candidate_confidence=candidate_confidence,
    )


def _strong_intent() -> UnifiedState:
    """UnifiedState with very strong intent, high utility, low risk/uncertainty."""
    return _unified(
        intent=0.9,
        attention=0.9,
        focus_level=0.8,
        interruption_sensitivity=0.2,
        context_utility=0.85,
        urgency=0.6,
        action_risk=0.1,
        uncertainty=0.1,
    )


def _ambiguous() -> UnifiedState:
    """UnifiedState with conflicting intent and high risk."""
    return _unified(
        intent=0.8,
        attention=0.3,
        context_utility=0.2,
        action_risk=0.8,
        uncertainty=0.7,
    )


def _blank() -> UnifiedState:
    """Minimal / default UnifiedState."""
    return UnifiedState()


def _build_history(
    start_intent: float,
    end_intent: float,
    n: int = 5,
) -> list[UnifiedState]:
    """Build a history list with linearly changing intent_probability."""
    step = (end_intent - start_intent) / max(n - 1, 1)
    return [
        _unified(intent=start_intent + i * step) for i in range(n)
    ]


# ===========================================================================
# A) LiminalMetrics dataclass
# ===========================================================================


class TestLiminalMetrics:
    def test_construction(self):
        m = LiminalMetrics(
            coherence=0.7,
            ambiguity=0.3,
            collapse_tendency=0.5,
            intervention_window=0.6,
        )
        assert m.coherence == pytest.approx(0.7)
        assert m.ambiguity == pytest.approx(0.3)
        assert m.collapse_tendency == pytest.approx(0.5)
        assert m.intervention_window == pytest.approx(0.6)

    def test_frozen(self):
        m = LiminalMetrics(
            coherence=0.5, ambiguity=0.5,
            collapse_tendency=0.5, intervention_window=0.5,
        )
        with pytest.raises((AttributeError, TypeError)):
            m.coherence = 0.9  # type: ignore[misc]

    def test_all_zeros_valid(self):
        m = LiminalMetrics(
            coherence=0.0, ambiguity=0.0,
            collapse_tendency=0.0, intervention_window=0.0,
        )
        assert m.coherence == 0.0

    def test_all_ones_valid(self):
        m = LiminalMetrics(
            coherence=1.0, ambiguity=1.0,
            collapse_tendency=1.0, intervention_window=1.0,
        )
        assert m.coherence == 1.0


# ===========================================================================
# B) LiminalFieldEngine construction
# ===========================================================================


class TestLiminalFieldEngineConstruction:
    def test_default_construction(self):
        engine = LiminalFieldEngine()
        assert engine is not None

    def test_custom_config(self):
        cfg = ContinuumConfig(ema_alpha=0.4)
        engine = LiminalFieldEngine(config=cfg)
        assert engine._cfg.ema_alpha == 0.4

    def test_default_config_is_singleton(self):
        engine = LiminalFieldEngine()
        assert engine._cfg is DEFAULT_CONTINUUM_CONFIG


# ===========================================================================
# C) compute() with minimal / default state
# ===========================================================================


class TestComputeMinimal:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_returns_liminal_metrics(self):
        m = self.engine.compute(_blank())
        assert isinstance(m, LiminalMetrics)

    def test_blank_state_low_coherence(self):
        m = self.engine.compute(_blank())
        assert m.coherence < 0.5

    def test_blank_state_high_ambiguity(self):
        m = self.engine.compute(_blank())
        assert m.ambiguity > 0.5

    def test_blank_state_low_collapse_tendency(self):
        m = self.engine.compute(_blank())
        assert m.collapse_tendency < 0.4

    def test_blank_state_all_in_bounds(self):
        m = self.engine.compute(_blank())
        for name in ["coherence", "ambiguity", "collapse_tendency", "intervention_window"]:
            v = getattr(m, name)
            assert 0.0 <= v <= 1.0, f"{name}={v} out of bounds"


# ===========================================================================
# D) coherence computation
# ===========================================================================


class TestCoherenceComputation:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_high_intent_attention_utility_raises_coherence(self):
        m = self.engine.compute(_strong_intent())
        assert m.coherence > 0.5

    def test_zero_intent_low_coherence(self):
        state = _unified(intent=0.0, attention=0.9, context_utility=0.9)
        m = self.engine.compute(state)
        assert m.coherence < 0.3

    def test_low_uncertainty_boosts_coherence(self):
        state_certain = _unified(intent=0.6, attention=0.7, uncertainty=0.1)
        state_uncertain = _unified(intent=0.6, attention=0.7, uncertainty=0.9)
        m_certain = self.engine.compute(state_certain)
        m_uncertain = self.engine.compute(state_uncertain)
        assert m_certain.coherence > m_uncertain.coherence

    def test_high_focus_contributes_to_coherence(self):
        state_hi = _unified(intent=0.5, attention=0.5, focus_level=0.9)
        state_lo = _unified(intent=0.5, attention=0.5, focus_level=0.1)
        m_hi = self.engine.compute(state_hi)
        m_lo = self.engine.compute(state_lo)
        assert m_hi.coherence > m_lo.coherence

    def test_context_utility_amplifies_coherence(self):
        state_hi = _unified(intent=0.7, attention=0.7, context_utility=0.9)
        state_lo = _unified(intent=0.7, attention=0.7, context_utility=0.1)
        m_hi = self.engine.compute(state_hi)
        m_lo = self.engine.compute(state_lo)
        assert m_hi.coherence > m_lo.coherence

    def test_history_rising_intent_boosts_coherence(self):
        """Rising intent trend in history should add a small coherence bonus."""
        state = _unified(intent=0.5, attention=0.5, uncertainty=0.3)
        history_rising = _build_history(start_intent=0.1, end_intent=0.9, n=6)
        history_flat = _build_history(start_intent=0.5, end_intent=0.5, n=6)
        m_rising = self.engine.compute(state, history=history_rising)
        m_flat = self.engine.compute(state, history=history_flat)
        assert m_rising.coherence >= m_flat.coherence


# ===========================================================================
# E) ambiguity computation
# ===========================================================================


class TestAmbiguityComputation:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_high_coherence_low_ambiguity(self):
        """Strong-intent state should have coherence > ambiguity."""
        m = self.engine.compute(_strong_intent())
        assert m.ambiguity < m.coherence

    def test_conflict_raises_ambiguity(self):
        """High intent + high action_risk = conflict → elevated ambiguity."""
        m_conflict = self.engine.compute(_ambiguous())
        m_clean = self.engine.compute(_strong_intent())
        assert m_conflict.ambiguity > m_clean.ambiguity

    def test_zero_intent_high_ambiguity(self):
        state = _unified(intent=0.0, context_utility=0.0, uncertainty=0.9)
        m = self.engine.compute(state)
        assert m.ambiguity > 0.6

    def test_ambiguity_in_bounds(self):
        for intent in [0.0, 0.3, 0.7, 1.0]:
            for risk in [0.0, 0.5, 1.0]:
                state = _unified(intent=intent, action_risk=risk)
                m = self.engine.compute(state)
                assert 0.0 <= m.ambiguity <= 1.0


# ===========================================================================
# F) collapse_tendency computation
# ===========================================================================


class TestCollapseTendency:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_strong_intent_low_sensitivity_high_collapse(self):
        state = _unified(
            intent=0.9,
            attention=0.9,
            interruption_sensitivity=0.1,
            context_utility=0.85,
            action_risk=0.05,
            uncertainty=0.05,
        )
        m = self.engine.compute(state)
        assert m.collapse_tendency > 0.4

    def test_high_sensitivity_suppresses_collapse(self):
        state_lo_sens = _unified(intent=0.8, attention=0.8, interruption_sensitivity=0.1,
                                 context_utility=0.7, action_risk=0.1, uncertainty=0.1)
        state_hi_sens = _unified(intent=0.8, attention=0.8, interruption_sensitivity=0.9,
                                 context_utility=0.7, action_risk=0.1, uncertainty=0.1)
        m_lo = self.engine.compute(state_lo_sens)
        m_hi = self.engine.compute(state_hi_sens)
        assert m_lo.collapse_tendency > m_hi.collapse_tendency

    def test_high_action_risk_suppresses_collapse(self):
        state_lo_risk = _unified(intent=0.8, attention=0.8, action_risk=0.05,
                                 interruption_sensitivity=0.2, uncertainty=0.1)
        state_hi_risk = _unified(intent=0.8, attention=0.8, action_risk=0.9,
                                 interruption_sensitivity=0.2, uncertainty=0.1)
        m_lo = self.engine.compute(state_lo_risk)
        m_hi = self.engine.compute(state_hi_risk)
        assert m_lo.collapse_tendency > m_hi.collapse_tendency

    def test_urgency_boosts_collapse(self):
        state_lo_urgency = _unified(intent=0.6, attention=0.6, interruption_sensitivity=0.3,
                                    urgency=0.0, action_risk=0.1, uncertainty=0.2)
        state_hi_urgency = _unified(intent=0.6, attention=0.6, interruption_sensitivity=0.3,
                                    urgency=0.9, action_risk=0.1, uncertainty=0.2)
        m_lo = self.engine.compute(state_lo_urgency)
        m_hi = self.engine.compute(state_hi_urgency)
        assert m_hi.collapse_tendency > m_lo.collapse_tendency

    def test_blank_state_near_zero_collapse(self):
        m = self.engine.compute(_blank())
        assert m.collapse_tendency < 0.4


# ===========================================================================
# G) intervention_window computation
# ===========================================================================


class TestInterventionWindow:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_speaking_narrows_window(self):
        state_speak = _unified(intent=0.7, attention=0.7, speaking=True,
                               interruption_sensitivity=0.3)
        state_silent = _unified(intent=0.7, attention=0.7, speaking=False,
                                interruption_sensitivity=0.3)
        m_speak = self.engine.compute(state_speak)
        m_silent = self.engine.compute(state_silent)
        assert m_silent.intervention_window > m_speak.intervention_window

    def test_high_sensitivity_narrows_window(self):
        state_hi = _unified(intent=0.7, attention=0.7, interruption_sensitivity=0.9)
        state_lo = _unified(intent=0.7, attention=0.7, interruption_sensitivity=0.1)
        m_hi = self.engine.compute(state_hi)
        m_lo = self.engine.compute(state_lo)
        assert m_lo.intervention_window > m_hi.intervention_window

    def test_high_fatigue_narrows_window(self):
        state_tired = _unified(intent=0.6, attention=0.6, fatigue=0.9,
                               interruption_sensitivity=0.3)
        state_fresh = _unified(intent=0.6, attention=0.6, fatigue=0.0,
                               interruption_sensitivity=0.3)
        m_tired = self.engine.compute(state_tired)
        m_fresh = self.engine.compute(state_fresh)
        assert m_fresh.intervention_window > m_tired.intervention_window

    def test_high_intent_opens_window(self):
        state_hi = _unified(intent=0.9, attention=0.9, interruption_sensitivity=0.2)
        state_lo = _unified(intent=0.1, attention=0.1, interruption_sensitivity=0.2)
        m_hi = self.engine.compute(state_hi)
        m_lo = self.engine.compute(state_lo)
        assert m_hi.intervention_window > m_lo.intervention_window

    def test_speaking_floor_clamps_to_zero(self):
        """Speaking + max sensitivity → window should be near zero."""
        state = _unified(intent=0.9, speaking=True, interruption_sensitivity=1.0, fatigue=0.9)
        m = self.engine.compute(state)
        assert m.intervention_window <= 0.05

    def test_window_in_bounds(self):
        for intent in [0.0, 0.5, 1.0]:
            for speaking in [True, False]:
                state = _unified(intent=intent, speaking=speaking)
                m = self.engine.compute(state)
                assert 0.0 <= m.intervention_window <= 1.0


# ===========================================================================
# H) enrich_unified() phase-candidate promotion
# ===========================================================================


class TestEnrichUnified:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_high_collapse_promotes_to_manifest(self):
        """When collapse_tendency ≥ manifest_enter, candidate → MANIFEST."""
        cfg = ContinuumConfig(hysteresis=HysteresisConfig(manifest_enter=0.1))
        engine = LiminalFieldEngine(config=cfg)
        state = _unified(
            intent=0.9, attention=0.9, interruption_sensitivity=0.1,
            context_utility=0.9, action_risk=0.05, uncertainty=0.05,
            phase_candidate=ContinuumPhase.LIMINAL,
        )
        metrics = engine.compute(state)
        enriched = engine.enrich_unified(state, metrics)
        assert enriched.phase_candidate == ContinuumPhase.MANIFEST
        assert enriched.candidate_confidence == pytest.approx(metrics.collapse_tendency, abs=1e-9)

    def test_low_collapse_keeps_candidate(self):
        """When collapse_tendency is low, candidate is not promoted."""
        state = _unified(
            intent=0.1,
            phase_candidate=ContinuumPhase.LIMINAL,
        )
        metrics = self.engine.compute(state)
        enriched = self.engine.enrich_unified(state, metrics)
        # Should not be MANIFEST
        assert enriched.phase_candidate != ContinuumPhase.MANIFEST

    def test_low_collapse_updates_confidence_to_coherence(self):
        state = _unified(intent=0.3, attention=0.3)
        metrics = self.engine.compute(state)
        enriched = self.engine.enrich_unified(state, metrics)
        assert enriched.candidate_confidence == pytest.approx(metrics.coherence, abs=1e-9)

    def test_original_state_unchanged(self):
        state = _unified(intent=0.5)
        metrics = self.engine.compute(state)
        _ = self.engine.enrich_unified(state, metrics)
        # Original state must not be mutated
        assert state.phase_candidate == ContinuumPhase.FORMLESS

    def test_already_manifest_not_doubled(self):
        """If already MANIFEST, enrich should not change phase_candidate."""
        cfg = ContinuumConfig(hysteresis=HysteresisConfig(manifest_enter=0.1))
        engine = LiminalFieldEngine(config=cfg)
        state = _unified(
            intent=0.9, attention=0.9, interruption_sensitivity=0.05,
            context_utility=0.9, action_risk=0.05, uncertainty=0.05,
            phase_candidate=ContinuumPhase.MANIFEST,
        )
        metrics = engine.compute(state)
        enriched = engine.enrich_unified(state, metrics)
        assert enriched.phase_candidate == ContinuumPhase.MANIFEST


# ===========================================================================
# I) History influence on coherence
# ===========================================================================


class TestHistoryInfluence:
    def setup_method(self):
        self.engine = LiminalFieldEngine()

    def test_rising_history_boosts_coherence(self):
        state = _unified(intent=0.5, attention=0.6, uncertainty=0.2)
        history_rising = _build_history(start_intent=0.1, end_intent=0.9, n=6)
        history_falling = _build_history(start_intent=0.9, end_intent=0.1, n=6)
        m_rising = self.engine.compute(state, history=history_rising)
        m_falling = self.engine.compute(state, history=history_falling)
        assert m_rising.coherence >= m_falling.coherence

    def test_flat_history_no_bonus(self):
        state = _unified(intent=0.5, attention=0.5)
        history_rising = _build_history(start_intent=0.1, end_intent=0.9, n=6)
        history_flat = _build_history(start_intent=0.5, end_intent=0.5, n=6)
        m_rising = self.engine.compute(state, history=history_rising)
        m_flat = self.engine.compute(state, history=history_flat)
        assert m_rising.coherence >= m_flat.coherence

    def test_single_history_entry_no_trend(self):
        state = _unified(intent=0.5)
        m_no_hist = self.engine.compute(state, history=None)
        m_one = self.engine.compute(state, history=[_unified(intent=0.9)])
        # Single entry → no trend computation, same result
        assert m_no_hist.coherence == pytest.approx(m_one.coherence, abs=1e-9)

    def test_empty_history_same_as_none(self):
        state = _unified(intent=0.5)
        m_none = self.engine.compute(state, history=None)
        m_empty = self.engine.compute(state, history=[])
        assert m_none.coherence == pytest.approx(m_empty.coherence, abs=1e-9)


# ===========================================================================
# J) Output bounds across varied inputs
# ===========================================================================


class TestOutputBounds:
    """All computed metrics must remain in [0, 1] across wide input ranges."""

    def setup_method(self):
        self.engine = LiminalFieldEngine()

    @pytest.mark.parametrize("intent,attention,risk,uncertainty", [
        (0.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0, 1.0),
        (0.5, 0.5, 0.5, 0.5),
        (0.9, 0.1, 0.8, 0.2),
        (0.3, 0.7, 0.1, 0.9),
    ])
    def test_bounds_parametric(self, intent, attention, risk, uncertainty):
        state = _unified(
            intent=intent, attention=attention,
            action_risk=risk, uncertainty=uncertainty,
        )
        m = self.engine.compute(state)
        for name in ["coherence", "ambiguity", "collapse_tendency", "intervention_window"]:
            v = getattr(m, name)
            assert 0.0 <= v <= 1.0, f"param test: {name}={v}"

    def test_extreme_speaking_bounds(self):
        state = _unified(
            intent=1.0, speaking=True,
            interruption_sensitivity=1.0, fatigue=1.0,
        )
        m = self.engine.compute(state)
        for name in ["coherence", "ambiguity", "collapse_tendency", "intervention_window"]:
            v = getattr(m, name)
            assert 0.0 <= v <= 1.0, f"speaking extreme: {name}={v}"

    def test_urgency_bounds(self):
        for urgency in [0.0, 0.5, 1.0]:
            state = _unified(intent=0.6, urgency=urgency)
            m = self.engine.compute(state)
            assert 0.0 <= m.collapse_tendency <= 1.0


# ===========================================================================
# K) StateFusion + LiminalFieldEngine integration
# ===========================================================================


class TestStateFusionIntegration:
    def setup_method(self):
        self.fusion = StateFusion()
        self.engine = LiminalFieldEngine()

    def test_fuse_then_compute_produces_metrics(self):
        human = HumanFieldState(
            intent_probability=0.7,
            attention=0.75,
            focus_level=0.6,
            interruption_sensitivity=0.3,
        )
        unified = self.fusion.fuse(human, world={"context_utility": 0.6, "urgency": 0.4})
        metrics = self.engine.compute(unified)
        assert isinstance(metrics, LiminalMetrics)
        for name in ["coherence", "ambiguity", "collapse_tendency", "intervention_window"]:
            v = getattr(metrics, name)
            assert 0.0 <= v <= 1.0

    def test_fuse_with_history_then_compute(self):
        human = HumanFieldState(intent_probability=0.5, attention=0.5)
        history = [
            self.fusion.fuse(
                HumanFieldState(intent_probability=0.1 + i * 0.1),
                world={"context_utility": 0.3},
            )
            for i in range(5)
        ]
        unified = self.fusion.fuse(human, world={"context_utility": 0.5})
        metrics = self.engine.compute(unified, history=history)
        assert 0.0 <= metrics.coherence <= 1.0

    def test_high_risk_world_raises_ambiguity(self):
        human = HumanFieldState(intent_probability=0.75, attention=0.75)
        unified = self.fusion.fuse(
            human,
            world={"action_risk": 0.9, "context_utility": 0.3, "uncertainty": 0.8},
        )
        metrics = self.engine.compute(unified)
        assert metrics.ambiguity > 0.4
