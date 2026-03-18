"""
tests/test_continuum_types.py
=============================

Unit tests for core.continuum.types and core.continuum.config.

Covers:
  A) ContinuumPhase enum values and string serialisation.
  B) HumanFieldState default values and field constraints.
  C) UnifiedState construction and nested model access.
  D) DecisionState fields and defaults.
  E) ExpressionState enum fields.
  F) ContinuumState convenience factories and JSON serialisation.
  G) ContinuumConfig sub-configs and DEFAULT_CONTINUUM_CONFIG.
  H) Round-trip dict/JSON serialisation for all top-level models.
"""

from __future__ import annotations

import json
import pytest

from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    DecisionState,
    ExpressionState,
    FormSignature,
    HumanFieldState,
    SpatialPresence,
    UnifiedState,
)
from core.continuum.config import (
    ContinuumConfig,
    DEFAULT_CONTINUUM_CONFIG,
    DwellConfig,
    FeatureFlags,
    HysteresisConfig,
)


# ===========================================================================
# A) ContinuumPhase enum
# ===========================================================================


class TestContinuumPhase:
    def test_all_four_phases_exist(self):
        phases = {p.value for p in ContinuumPhase}
        assert phases == {"formless", "liminal", "manifest", "receding"}

    def test_phase_is_str_enum(self):
        assert ContinuumPhase.FORMLESS == "formless"
        assert isinstance(ContinuumPhase.LIMINAL, str)

    def test_phase_from_string(self):
        assert ContinuumPhase("liminal") == ContinuumPhase.LIMINAL

    def test_forbidden_phase_string_raises(self):
        with pytest.raises(ValueError):
            ContinuumPhase("unknown_phase")


# ===========================================================================
# B) HumanFieldState
# ===========================================================================


class TestHumanFieldState:
    def test_default_construction(self):
        hf = HumanFieldState()
        assert hf.attention == 0.5
        assert hf.focus_level == 0.5
        assert hf.fatigue == 0.0
        assert hf.intent_probability == 0.0
        assert hf.interruption_sensitivity == 0.5
        assert hf.speaking is False

    def test_field_bounds_enforced(self):
        with pytest.raises(Exception):
            HumanFieldState(attention=1.5)
        with pytest.raises(Exception):
            HumanFieldState(fatigue=-0.1)

    def test_custom_values(self):
        hf = HumanFieldState(
            attention=0.9,
            intent_probability=0.7,
            speaking=True,
        )
        assert hf.attention == 0.9
        assert hf.speaking is True

    def test_dict_serialisable(self):
        hf = HumanFieldState()
        d = hf.model_dump()
        assert isinstance(d, dict)
        assert "attention" in d
        assert "timestamp" in d


# ===========================================================================
# C) UnifiedState
# ===========================================================================


class TestUnifiedState:
    def test_default_construction(self):
        us = UnifiedState()
        assert us.phase_candidate == ContinuumPhase.FORMLESS
        assert us.candidate_confidence == 0.0

    def test_nested_human_field_accessible(self):
        us = UnifiedState()
        assert isinstance(us.human, HumanFieldState)
        assert us.human.attention == 0.5

    def test_override_human_field(self):
        hf = HumanFieldState(attention=0.8, intent_probability=0.6)
        us = UnifiedState(human=hf, phase_candidate=ContinuumPhase.LIMINAL)
        assert us.human.attention == 0.8
        assert us.phase_candidate == ContinuumPhase.LIMINAL

    def test_dict_serialisable(self):
        us = UnifiedState()
        d = us.model_dump()
        assert "human" in d
        assert "phase_candidate" in d
        assert d["phase_candidate"] == "formless"


# ===========================================================================
# D) DecisionState
# ===========================================================================


class TestDecisionState:
    def test_default_action_level(self):
        ds = DecisionState()
        assert ds.action_level == ActionLevel.OBSERVE

    def test_action_level_all_values(self):
        levels = {l.value for l in ActionLevel}
        assert levels == {"observe", "hint", "assist", "execute"}

    def test_dict_round_trip(self):
        ds = DecisionState(
            should_act_score=0.55,
            action_level=ActionLevel.ASSIST,
            decision_reason="test reason",
        )
        d = ds.model_dump()
        assert d["action_level"] == "assist"
        assert d["decision_reason"] == "test reason"


# ===========================================================================
# E) ExpressionState
# ===========================================================================


class TestExpressionState:
    def test_defaults(self):
        es = ExpressionState()
        assert es.motion == 0.0
        assert es.form_signature == FormSignature.NONE
        assert es.spatial_presence == SpatialPresence.ABSENT
        assert es.phase_signature == ContinuumPhase.FORMLESS

    def test_form_signature_enum(self):
        es = ExpressionState(form_signature=FormSignature.DIFFUSE_CLUSTER)
        assert es.form_signature == "diffuse_cluster"

    def test_spatial_presence_enum(self):
        es = ExpressionState(spatial_presence=SpatialPresence.PERIPHERAL)
        assert es.spatial_presence == "peripheral"


# ===========================================================================
# F) ContinuumState factories and serialisation
# ===========================================================================


class TestContinuumState:
    def test_formless_default_factory(self):
        cs = ContinuumState.formless_default()
        assert cs.phase == ContinuumPhase.FORMLESS
        assert cs.presence_intensity == 0.0
        assert cs.degraded is False

    def test_degraded_fallback_factory(self):
        cs = ContinuumState.degraded_fallback("test_error")
        assert cs.phase == ContinuumPhase.FORMLESS
        assert cs.degraded is True
        assert cs.degrade_reason == "test_error"

    def test_version_field(self):
        cs = ContinuumState()
        assert cs.version == 1

    def test_trace_id_generated(self):
        cs1 = ContinuumState()
        cs2 = ContinuumState()
        assert cs1.trace_id.startswith("cont_")
        assert cs1.trace_id != cs2.trace_id

    def test_nested_decision_and_expression_accessible(self):
        cs = ContinuumState()
        assert isinstance(cs.decision, DecisionState)
        assert isinstance(cs.expression, ExpressionState)

    def test_full_json_round_trip(self):
        cs = ContinuumState(
            phase=ContinuumPhase.LIMINAL,
            presence_intensity=0.42,
            coherence=0.37,
        )
        json_str = cs.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["phase"] == "liminal"
        assert parsed["presence_intensity"] == pytest.approx(0.42)

    def test_model_dump_is_json_serialisable(self):
        cs = ContinuumState.formless_default()
        d = cs.model_dump()
        # Should not raise
        json.dumps(d)


# ===========================================================================
# G) Config models
# ===========================================================================


class TestHysteresisConfig:
    def test_defaults(self):
        h = HysteresisConfig()
        assert h.liminal_enter == pytest.approx(0.68)
        assert h.liminal_exit == pytest.approx(0.45)
        assert h.manifest_enter == pytest.approx(0.78)
        assert h.manifest_exit == pytest.approx(0.52)

    def test_enter_greater_than_exit(self):
        h = HysteresisConfig()
        assert h.liminal_enter > h.liminal_exit
        assert h.manifest_enter > h.manifest_exit


class TestDwellConfig:
    def test_defaults(self):
        d = DwellConfig()
        assert d.liminal_ms == 800
        assert d.manifest_ms == 1200
        assert d.receding_ms == 600


class TestFeatureFlags:
    def test_defaults(self):
        f = FeatureFlags()
        assert f.enabled is True
        assert f.debug is False
        assert f.allow_emergency_jump is False


class TestContinuumConfig:
    def test_defaults(self):
        cfg = ContinuumConfig()
        assert cfg.tick_ms == 120
        assert cfg.ema_alpha == pytest.approx(0.25)
        assert cfg.max_delta_per_tick == pytest.approx(0.08)
        assert cfg.timeout_receding_ms == 5000

    def test_nested_sub_configs(self):
        cfg = ContinuumConfig()
        assert isinstance(cfg.hysteresis, HysteresisConfig)
        assert isinstance(cfg.dwell, DwellConfig)
        assert isinstance(cfg.flags, FeatureFlags)

    def test_partial_override(self):
        cfg = ContinuumConfig(
            ema_alpha=0.35,
            hysteresis=HysteresisConfig(liminal_enter=0.72),
        )
        assert cfg.ema_alpha == pytest.approx(0.35)
        assert cfg.hysteresis.liminal_enter == pytest.approx(0.72)
        # Other nested defaults unchanged
        assert cfg.dwell.liminal_ms == 800

    def test_dict_serialisable(self):
        cfg = ContinuumConfig()
        d = cfg.model_dump()
        assert "hysteresis" in d
        assert "dwell" in d
        assert "flags" in d
        json.dumps(d)


class TestDefaultConfig:
    def test_default_singleton_is_config(self):
        assert isinstance(DEFAULT_CONTINUUM_CONFIG, ContinuumConfig)

    def test_default_singleton_values(self):
        assert DEFAULT_CONTINUUM_CONFIG.flags.enabled is True
        assert DEFAULT_CONTINUUM_CONFIG.ema_alpha == pytest.approx(0.25)


# ===========================================================================
# H) Cross-model JSON serialisation
# ===========================================================================


class TestJsonSerialisation:
    """Ensure every top-level model survives a dict/JSON round-trip."""

    @pytest.mark.parametrize(
        "model",
        [
            HumanFieldState(),
            UnifiedState(),
            DecisionState(),
            ExpressionState(),
            ContinuumState.formless_default(),
            ContinuumState.degraded_fallback(),
            ContinuumConfig(),
        ],
    )
    def test_model_dump_json_serialisable(self, model):
        d = model.model_dump()
        json_str = json.dumps(d)
        assert isinstance(json_str, str)

    @pytest.mark.parametrize(
        "model",
        [
            HumanFieldState(),
            UnifiedState(),
            DecisionState(),
            ExpressionState(),
            ContinuumState.formless_default(),
            ContinuumConfig(),
        ],
    )
    def test_model_dump_json_and_reload(self, model):
        json_str = model.model_dump_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
