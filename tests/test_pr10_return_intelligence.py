"""
tests/test_pr10_return_intelligence.py
=======================================
Tests for PR-10: Return Intelligence Formalization.

Coverage
--------
A) ReturnMode enum
   - all values present
   - string coercion
   - influence-hint frozensets correct

B) ReturnSummary
   - default (idle) construction
   - to_dict() round-trip
   - IDLE_RETURN_SUMMARY constant
   - frozen / immutable
   - __repr__ format

C) build_return_summary — from ReturnResult
   - no-return (hold) result → mode=NONE, is_returning=False
   - user_cancel → mode=RETURN_TO_FORMLESS, is_returning=True
   - finished → mode=STEP_DOWN, affects_manifest=True, affects_liminal=True
   - timeout → mode=STEP_DOWN
   - low_value → mode=SOFT_DECAY, affects_liminal=True, affects_manifest=False
   - high_uncertainty → mode=RETURN_TO_FORMLESS
   - None input → IDLE_RETURN_SUMMARY
   - dict input (duck-typed)
   - decay_amount propagated for soft_decay
   - reason propagated

D) attach_return_summary
   - does not mutate original projection dict
   - return_intelligence key added
   - all ReturnSummary fields present in attached dict
   - backward-compatible: existing projection fields unchanged

E) get_return_hints
   - idle summary → all hints False / zero
   - step_down summary → suppresses_manifest=True, softens_liminal=True
   - soft_decay summary → suppresses_manifest=False, softens_liminal=True
   - return_mode string matches

F) None / non-return edge cases
   - None result → IDLE_RETURN_SUMMARY
   - hold action with should_return=False → mode=NONE

G) Downstream helper stability
   - build_return_summary is idempotent (calling twice returns equal result)
   - attach_return_summary works on minimal projection dict
   - ReturnSurface.render() returns non-empty string
   - ReturnSurface.render() with return_intelligence key
   - ReturnSurface.render() without return_intelligence key (graceful degradation)

H) Integration: ReturnEngine → build_return_summary pipeline
   - evaluate on finished state → STEP_DOWN summary
   - evaluate on healthy state → NONE summary
   - force_return → RETURN_TO_FORMLESS summary
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Helpers: minimal projection dict
# ---------------------------------------------------------------------------

_MINIMAL_PROJECTION: Dict[str, Any] = {
    "tri_state_phase": "silent",
    "runtime_domain": None,
    "presence_intensity": None,
    "coherence": None,
    "collapse_tendency": None,
    "retreat_tendency": None,
    "primary_model_id": None,
    "support_model_ids": [],
    "active_weights": {},
    "route_reason": None,
    "active_device_ids": [],
    "execution_stage": None,
    "current_task_summary": None,
    "timestamp": 1700000000.0,
}

_MANIFEST_PROJECTION: Dict[str, Any] = {
    **_MINIMAL_PROJECTION,
    "tri_state_phase": "manifest",
    "presence_intensity": 0.72,
    "coherence": 0.61,
    "collapse_tendency": 0.45,
    "retreat_tendency": 0.18,
}


# ===========================================================================
# A) ReturnMode enum
# ===========================================================================

class TestReturnMode:
    def test_all_values_present(self):
        from core.return_intelligence import ReturnMode
        values = {m.value for m in ReturnMode}
        assert values == {"none", "hold", "soft_decay", "step_down", "return_to_formless"}

    def test_string_coercion(self):
        from core.return_intelligence import ReturnMode
        assert ReturnMode("none") == ReturnMode.NONE
        assert ReturnMode("soft_decay") == ReturnMode.SOFT_DECAY

    def test_suppress_manifest_frozenset(self):
        from core.return_intelligence import ReturnMode, MODES_THAT_SUPPRESS_MANIFEST
        assert ReturnMode.STEP_DOWN in MODES_THAT_SUPPRESS_MANIFEST
        assert ReturnMode.RETURN_TO_FORMLESS in MODES_THAT_SUPPRESS_MANIFEST
        assert ReturnMode.SOFT_DECAY not in MODES_THAT_SUPPRESS_MANIFEST
        assert ReturnMode.HOLD not in MODES_THAT_SUPPRESS_MANIFEST
        assert ReturnMode.NONE not in MODES_THAT_SUPPRESS_MANIFEST

    def test_soften_liminal_frozenset(self):
        from core.return_intelligence import ReturnMode, MODES_THAT_SOFTEN_LIMINAL
        assert ReturnMode.SOFT_DECAY in MODES_THAT_SOFTEN_LIMINAL
        assert ReturnMode.STEP_DOWN in MODES_THAT_SOFTEN_LIMINAL
        assert ReturnMode.RETURN_TO_FORMLESS in MODES_THAT_SOFTEN_LIMINAL
        assert ReturnMode.HOLD not in MODES_THAT_SOFTEN_LIMINAL
        assert ReturnMode.NONE not in MODES_THAT_SOFTEN_LIMINAL

    def test_active_return_modes_frozenset(self):
        from core.return_intelligence import ReturnMode, ACTIVE_RETURN_MODES
        assert ReturnMode.SOFT_DECAY in ACTIVE_RETURN_MODES
        assert ReturnMode.STEP_DOWN in ACTIVE_RETURN_MODES
        assert ReturnMode.RETURN_TO_FORMLESS in ACTIVE_RETURN_MODES
        assert ReturnMode.HOLD not in ACTIVE_RETURN_MODES
        assert ReturnMode.NONE not in ACTIVE_RETURN_MODES


# ===========================================================================
# B) ReturnSummary
# ===========================================================================

class TestReturnSummary:
    def test_default_construction(self):
        from core.return_intelligence import ReturnSummary, ReturnMode
        s = ReturnSummary()
        assert s.is_returning is False
        assert s.return_mode == ReturnMode.NONE
        assert s.return_action is None
        assert s.return_trigger is None
        assert s.decay_amount == 0.0
        assert s.reason == "no return active"
        assert s.affects_manifest is False
        assert s.affects_liminal is False

    def test_to_dict_round_trip(self):
        from core.return_intelligence import ReturnSummary, ReturnMode
        s = ReturnSummary(
            is_returning=True,
            return_mode=ReturnMode.SOFT_DECAY,
            return_action="soft_decay",
            return_trigger="low_value",
            decay_amount=0.05,
            reason="low_value trigger",
            affects_manifest=False,
            affects_liminal=True,
        )
        d = s.to_dict()
        assert d["is_returning"] is True
        assert d["return_mode"] == "soft_decay"
        assert d["return_action"] == "soft_decay"
        assert d["return_trigger"] == "low_value"
        assert d["decay_amount"] == 0.05
        assert d["reason"] == "low_value trigger"
        assert d["affects_manifest"] is False
        assert d["affects_liminal"] is True

    def test_to_dict_has_no_enum_objects(self):
        from core.return_intelligence import ReturnSummary, ReturnMode
        import json
        s = ReturnSummary(return_mode=ReturnMode.STEP_DOWN)
        d = s.to_dict()
        # Should be JSON-serialisable without errors.
        dumped = json.dumps(d)
        assert "step_down" in dumped

    def test_idle_return_summary_constant(self):
        from core.return_intelligence import IDLE_RETURN_SUMMARY, ReturnMode
        assert IDLE_RETURN_SUMMARY.is_returning is False
        assert IDLE_RETURN_SUMMARY.return_mode == ReturnMode.NONE
        assert IDLE_RETURN_SUMMARY.decay_amount == 0.0

    def test_frozen(self):
        from core.return_intelligence import ReturnSummary
        s = ReturnSummary()
        with pytest.raises((AttributeError, TypeError)):
            s.is_returning = True  # type: ignore[misc]

    def test_repr_contains_mode(self):
        from core.return_intelligence import ReturnSummary, ReturnMode
        s = ReturnSummary(return_mode=ReturnMode.STEP_DOWN)
        assert "step_down" in repr(s)


# ===========================================================================
# C) build_return_summary
# ===========================================================================

class TestBuildReturnSummary:
    """Uses ReturnEngine to produce real ReturnResult objects."""

    def _make_result(self, **kwargs):
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        state = ContinuumState(
            phase=kwargs.pop("phase", ContinuumPhase.MANIFEST),
            presence_intensity=kwargs.pop("presence_intensity", 0.7),
            stability=kwargs.pop("stability", 0.9),
        )
        engine = ReturnEngine()
        return engine.evaluate(state, **kwargs)

    def test_no_return_gives_none_mode(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        result = self._make_result()  # healthy state, no triggers
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.NONE
        assert summary.is_returning is False

    def test_user_cancel_gives_return_to_formless(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        result = self._make_result(user_cancel=True)
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.RETURN_TO_FORMLESS
        assert summary.is_returning is True
        assert summary.return_trigger == "user_cancel"

    def test_finished_gives_step_down(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        result = self._make_result(finished=True)
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.STEP_DOWN
        assert summary.is_returning is True
        assert summary.return_trigger == "finished"
        assert summary.affects_manifest is True
        assert summary.affects_liminal is True

    def test_timeout_gives_step_down(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        from core.continuum.config import DEFAULT_CONTINUUM_CONFIG
        # Use a very large elapsed_ms to guarantee timeout.
        timeout_ms = float(DEFAULT_CONTINUUM_CONFIG.timeout_receding_ms)
        result = self._make_result(elapsed_ms=timeout_ms + 1000.0)
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.STEP_DOWN
        assert summary.is_returning is True
        assert summary.return_trigger == "timeout"

    def test_low_value_gives_soft_decay(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        result = self._make_result(decision_score=0.01)
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.SOFT_DECAY
        assert summary.is_returning is True
        assert summary.return_trigger == "low_value"
        assert summary.affects_manifest is False
        assert summary.affects_liminal is True
        assert summary.decay_amount > 0.0

    def test_high_uncertainty_gives_return_to_formless(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        from core.continuum.types import ContinuumPhase, ContinuumState
        # Low stability → high effective_uncertainty → high_uncertainty trigger.
        from core.continuum.return_engine import ReturnEngine
        state = ContinuumState(
            phase=ContinuumPhase.MANIFEST,
            presence_intensity=0.7,
            stability=0.05,  # → effective_uncertainty = 0.95 > 0.85 threshold
        )
        engine = ReturnEngine()
        result = engine.evaluate(state)
        summary = build_return_summary(result)
        assert summary.return_mode == ReturnMode.RETURN_TO_FORMLESS
        assert summary.is_returning is True
        assert summary.return_trigger == "high_uncertainty"

    def test_none_input_returns_idle(self):
        from core.return_intelligence import build_return_summary, IDLE_RETURN_SUMMARY
        summary = build_return_summary(None)
        assert summary == IDLE_RETURN_SUMMARY

    def test_dict_input(self):
        """build_return_summary must handle a plain dict (duck-typed ReturnResult)."""
        from core.return_intelligence import build_return_summary, ReturnMode
        d = {
            "should_return": True,
            "return_action": "step_down",
            "trigger": "finished",
            "reason": "test reason",
            "decay_amount": 0.0,
        }
        summary = build_return_summary(d)
        assert summary.return_mode == ReturnMode.STEP_DOWN
        assert summary.is_returning is True
        assert summary.return_trigger == "finished"

    def test_decay_amount_propagated(self):
        from core.return_intelligence import build_return_summary
        result = self._make_result(decision_score=0.01)
        summary = build_return_summary(result)
        assert summary.decay_amount == pytest.approx(0.05, abs=1e-3)

    def test_reason_propagated(self):
        from core.return_intelligence import build_return_summary
        result = self._make_result(user_cancel=True)
        summary = build_return_summary(result)
        assert "user_cancel" in summary.reason


# ===========================================================================
# D) attach_return_summary
# ===========================================================================

class TestAttachReturnSummary:
    def test_does_not_mutate_original(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        original = dict(_MINIMAL_PROJECTION)
        enriched = attach_return_summary(original, IDLE_RETURN_SUMMARY)
        assert "return_intelligence" not in original
        assert "return_intelligence" in enriched

    def test_return_intelligence_key_added(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        enriched = attach_return_summary(_MINIMAL_PROJECTION, IDLE_RETURN_SUMMARY)
        ri = enriched["return_intelligence"]
        assert isinstance(ri, dict)
        assert "is_returning" in ri
        assert "return_mode" in ri
        assert "affects_manifest" in ri
        assert "affects_liminal" in ri

    def test_all_summary_fields_present(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        enriched = attach_return_summary(_MANIFEST_PROJECTION, IDLE_RETURN_SUMMARY)
        ri = enriched["return_intelligence"]
        expected_keys = {
            "is_returning", "return_mode", "return_action",
            "return_trigger", "decay_amount", "reason",
            "affects_manifest", "affects_liminal",
        }
        assert expected_keys.issubset(set(ri.keys()))

    def test_backward_compatible_existing_fields(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        enriched = attach_return_summary(_MANIFEST_PROJECTION, IDLE_RETURN_SUMMARY)
        # Existing fields must be unchanged.
        assert enriched["tri_state_phase"] == "manifest"
        assert enriched["presence_intensity"] == 0.72
        assert enriched["coherence"] == 0.61

    def test_attach_step_down_summary(self):
        from core.return_intelligence import attach_return_summary, ReturnSummary, ReturnMode
        summary = ReturnSummary(
            is_returning=True,
            return_mode=ReturnMode.STEP_DOWN,
            return_action="step_down",
            return_trigger="finished",
            decay_amount=0.0,
            reason="test",
            affects_manifest=True,
            affects_liminal=True,
        )
        enriched = attach_return_summary(_MANIFEST_PROJECTION, summary)
        ri = enriched["return_intelligence"]
        assert ri["is_returning"] is True
        assert ri["return_mode"] == "step_down"
        assert ri["affects_manifest"] is True


# ===========================================================================
# E) get_return_hints
# ===========================================================================

class TestGetReturnHints:
    def test_idle_hints_all_false(self):
        from core.return_intelligence import get_return_hints, IDLE_RETURN_SUMMARY
        hints = get_return_hints(IDLE_RETURN_SUMMARY)
        assert hints["is_returning"] is False
        assert hints["suppresses_manifest"] is False
        assert hints["softens_liminal"] is False
        assert hints["decay_amount"] == 0.0
        assert hints["return_mode"] == "none"

    def test_step_down_hints(self):
        from core.return_intelligence import get_return_hints, ReturnSummary, ReturnMode
        summary = ReturnSummary(
            is_returning=True,
            return_mode=ReturnMode.STEP_DOWN,
            affects_manifest=True,
            affects_liminal=True,
        )
        hints = get_return_hints(summary)
        assert hints["is_returning"] is True
        assert hints["suppresses_manifest"] is True
        assert hints["softens_liminal"] is True
        assert hints["return_mode"] == "step_down"

    def test_soft_decay_hints(self):
        from core.return_intelligence import get_return_hints, ReturnSummary, ReturnMode
        summary = ReturnSummary(
            is_returning=True,
            return_mode=ReturnMode.SOFT_DECAY,
            decay_amount=0.05,
            affects_manifest=False,
            affects_liminal=True,
        )
        hints = get_return_hints(summary)
        assert hints["suppresses_manifest"] is False
        assert hints["softens_liminal"] is True
        assert hints["decay_amount"] == pytest.approx(0.05)

    def test_hints_return_mode_is_string(self):
        from core.return_intelligence import get_return_hints, ReturnSummary, ReturnMode
        summary = ReturnSummary(return_mode=ReturnMode.RETURN_TO_FORMLESS)
        hints = get_return_hints(summary)
        assert isinstance(hints["return_mode"], str)
        assert hints["return_mode"] == "return_to_formless"


# ===========================================================================
# F) None / non-return edge cases
# ===========================================================================

class TestEdgeCases:
    def test_none_result_returns_idle(self):
        from core.return_intelligence import build_return_summary, IDLE_RETURN_SUMMARY
        assert build_return_summary(None) == IDLE_RETURN_SUMMARY

    def test_hold_action_with_should_return_false(self):
        from core.return_intelligence import build_return_summary, ReturnMode
        d = {
            "should_return": False,
            "return_action": "hold",
            "trigger": None,
            "reason": "no trigger active",
            "decay_amount": 0.0,
        }
        summary = build_return_summary(d)
        assert summary.return_mode == ReturnMode.NONE
        assert summary.is_returning is False

    def test_decay_amount_clamped_to_zero_on_idle(self):
        from core.return_intelligence import build_return_summary, IDLE_RETURN_SUMMARY
        assert IDLE_RETURN_SUMMARY.decay_amount == 0.0

    def test_affects_flags_false_on_idle(self):
        from core.return_intelligence import IDLE_RETURN_SUMMARY
        assert IDLE_RETURN_SUMMARY.affects_manifest is False
        assert IDLE_RETURN_SUMMARY.affects_liminal is False

    def test_attach_to_empty_dict(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        enriched = attach_return_summary({}, IDLE_RETURN_SUMMARY)
        assert "return_intelligence" in enriched
        assert enriched["return_intelligence"]["return_mode"] == "none"


# ===========================================================================
# G) Downstream helper stability
# ===========================================================================

class TestDownstreamHelperStability:
    def test_build_return_summary_idempotent(self):
        from core.return_intelligence import build_return_summary
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
        engine = ReturnEngine()
        result = engine.evaluate(state, finished=True)

        s1 = build_return_summary(result)
        s2 = build_return_summary(result)
        assert s1 == s2

    def test_attach_return_summary_minimal_dict(self):
        from core.return_intelligence import attach_return_summary, IDLE_RETURN_SUMMARY
        enriched = attach_return_summary({"tri_state_phase": "silent"}, IDLE_RETURN_SUMMARY)
        assert enriched["tri_state_phase"] == "silent"
        assert "return_intelligence" in enriched

    def test_return_surface_render_non_empty(self):
        from windows_client.status_board_v2.return_surface import ReturnSurface
        surface = ReturnSurface()
        result = surface.render(_MINIMAL_PROJECTION)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_return_surface_render_with_return_intelligence(self):
        from core.return_intelligence import attach_return_summary, ReturnSummary, ReturnMode
        from windows_client.status_board_v2.return_surface import ReturnSurface
        summary = ReturnSummary(
            is_returning=True,
            return_mode=ReturnMode.STEP_DOWN,
            return_action="step_down",
            return_trigger="finished",
            reason="normal completion",
            affects_manifest=True,
            affects_liminal=True,
        )
        enriched = attach_return_summary(_MANIFEST_PROJECTION, summary)
        surface = ReturnSurface()
        result = surface.render(enriched)
        assert "step_down" in result
        assert "RETURNING" in result

    def test_return_surface_render_without_return_intelligence_key(self):
        """Surface must render gracefully when return_intelligence key is absent."""
        from windows_client.status_board_v2.return_surface import ReturnSurface
        # _MINIMAL_PROJECTION has no return_intelligence key.
        surface = ReturnSurface()
        result = surface.render(_MINIMAL_PROJECTION)
        assert isinstance(result, str)
        assert "idle" in result or "Return Intelligence" in result

    def test_return_surface_contains_expected_labels(self):
        from windows_client.status_board_v2.return_surface import ReturnSurface
        surface = ReturnSurface()
        result = surface.render(_MINIMAL_PROJECTION)
        assert "Return Intelligence" in result
        assert "Mode" in result
        assert "Trigger" in result


# ===========================================================================
# H) Integration: ReturnEngine → build_return_summary pipeline
# ===========================================================================

class TestReturnEngineIntegration:
    def test_finished_state_gives_step_down_summary(self):
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        from core.return_intelligence import build_return_summary, ReturnMode

        state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
        engine = ReturnEngine()
        result = engine.evaluate(state, finished=True)
        summary = build_return_summary(result)

        assert summary.return_mode == ReturnMode.STEP_DOWN
        assert summary.is_returning is True
        assert summary.affects_manifest is True

    def test_healthy_state_gives_none_summary(self):
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        from core.return_intelligence import build_return_summary, ReturnMode

        state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
        engine = ReturnEngine()
        result = engine.evaluate(state)
        summary = build_return_summary(result)

        assert summary.return_mode == ReturnMode.NONE
        assert summary.is_returning is False

    def test_force_return_gives_return_to_formless_summary(self):
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        from core.return_intelligence import build_return_summary, ReturnMode

        state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
        engine = ReturnEngine()
        result = engine.force_return(state)
        summary = build_return_summary(result)

        assert summary.return_mode == ReturnMode.RETURN_TO_FORMLESS
        assert summary.is_returning is True
        assert summary.affects_manifest is True
        assert summary.affects_liminal is True

    def test_summary_is_public_safe_no_receding(self):
        """ReturnSummary structured fields must never expose 'receding' as a public state.

        The ``reason`` field is a human-readable explanation from the engine
        and may mention internal phase names.  The public-facing *structured*
        fields (return_mode, return_action, return_trigger) must not carry the
        internal ``receding`` phase value.
        """
        from core.continuum.return_engine import ReturnEngine
        from core.continuum.types import ContinuumPhase, ContinuumState
        from core.return_intelligence import build_return_summary

        state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
        engine = ReturnEngine()
        result = engine.evaluate(state, finished=True)
        summary = build_return_summary(result)

        d = summary.to_dict()
        # Structured state fields must not expose "receding" as a phase value.
        assert d["return_mode"] != "receding"
        assert d.get("return_action") != "receding"
        assert d.get("return_trigger") != "receding"

    def test_all_trigger_types_produce_valid_summaries(self):
        """Each trigger type must produce a non-error summary with expected fields."""
        from core.continuum.return_engine import ReturnEngine, ReturnTrigger
        from core.continuum.types import ContinuumPhase, ContinuumState
        from core.return_intelligence import build_return_summary, ReturnMode
        from core.continuum.config import DEFAULT_CONTINUUM_CONFIG

        engine = ReturnEngine()
        timeout_ms = float(DEFAULT_CONTINUUM_CONFIG.timeout_receding_ms)

        scenarios = [
            # (kwargs to engine.evaluate, expected ReturnMode, expected is_returning)
            ({"finished": True}, ReturnMode.STEP_DOWN, True),
            ({"user_cancel": True}, ReturnMode.RETURN_TO_FORMLESS, True),
            ({"elapsed_ms": timeout_ms + 1}, ReturnMode.STEP_DOWN, True),
            ({"decision_score": 0.01}, ReturnMode.SOFT_DECAY, True),
            ({}, ReturnMode.NONE, False),
        ]

        for kwargs, expected_mode, expected_returning in scenarios:
            state = ContinuumState(phase=ContinuumPhase.MANIFEST, presence_intensity=0.7)
            result = engine.evaluate(state, **kwargs)
            summary = build_return_summary(result)
            assert summary.return_mode == expected_mode, (
                f"kwargs={kwargs}: expected {expected_mode}, got {summary.return_mode}"
            )
            assert summary.is_returning == expected_returning, (
                f"kwargs={kwargs}: expected is_returning={expected_returning}, got {summary.is_returning}"
            )
            d = summary.to_dict()
            assert isinstance(d, dict)
            assert "return_mode" in d
