"""
tests/test_pr5_liminal_projection_engine.py
=============================================
Tests for PR-5: Liminal Projection Engine.

Coverage
--------
1. StateSpaceMapper
   - depth_factor for all tri_state_phase values
   - depth_factor nudge from collapse_tendency
   - topology_visibility from active_weights
   - domain_path_emphasis for all runtime_domain values
   - ambient_intensity geometric mean
   - boundary conditions (None fields, empty weights, extremes)
   - accepts plain dict and object with to_dict()
   - phase/domain preserved in source_phase / source_domain

2. TransitionAnimator
   - interpolate() yields exactly `steps` frames
   - last frame equals target state (no overshoot)
   - first frame is not the source
   - easing curves are monotonically non-decreasing for t in [0,1]
   - ease_in_out starts slow and ends slow (midpoint fastest)
   - ease_out starts fast and slows
   - classify_transition() returns correct TransitionPhase
   - recommend_curve() returns EASE_OUT for retreat directions
   - single_frame() clamps t to [0, 1]
   - single_frame(t=0) ≈ source, single_frame(t=1) == target

3. LiminalSpaceEngine
   - first update returns [target] (no transition)
   - subsequent update returns list of frames
   - current_state updated to target after update
   - reset() clears current_state
   - render_text() produces non-empty string with expected labels

4. LiminalSurface (Status Board V2 adapter)
   - render() returns non-empty string
   - contains expected field labels
   - handles None / missing fields gracefully

5. Boundary conditions
   - all-None projection (silent minimal)
   - manifest extreme (depth close to 1.0)
   - cross_device domain (path emphasis = 1.0)
   - zero-weight topology (visibility = 0.0)
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SILENT_MINIMAL: Dict[str, Any] = {
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
    "timestamp": 1711533600.0,
}

_LIMINAL_SAMPLE: Dict[str, Any] = {
    "tri_state_phase": "liminal",
    "runtime_domain": "local",
    "presence_intensity": 0.6,
    "coherence": 0.75,
    "collapse_tendency": 0.3,
    "retreat_tendency": 0.1,
    "primary_model_id": "gpt-4o",
    "support_model_ids": ["claude-3"],
    "active_weights": {"gpt-4o": 0.9, "claude-3": 0.6},
    "route_reason": "native preferred",
    "active_device_ids": ["desktop-win"],
    "execution_stage": "planning",
    "current_task_summary": "test task",
    "timestamp": 1711533600.0,
}

_MANIFEST_SAMPLE: Dict[str, Any] = {
    **_LIMINAL_SAMPLE,
    "tri_state_phase": "manifest",
    "runtime_domain": "cross_device",
    "presence_intensity": 0.95,
    "coherence": 0.90,
    "collapse_tendency": 0.80,
}


# ---------------------------------------------------------------------------
# StateSpaceMapper tests
# ---------------------------------------------------------------------------

class TestStateSpaceMapper:
    """Tests for StateSpaceMapper.map()."""

    def setup_method(self):
        from desktop_projection.state_space_mapper import StateSpaceMapper
        self.mapper = StateSpaceMapper()

    def test_silent_minimal_depth(self):
        state = self.mapper.map(_SILENT_MINIMAL)
        # silent base = 0.05, collapse=None → 0.0, nudge = 0
        assert abs(state.depth_factor - 0.05) < 1e-9

    def test_liminal_depth_base(self):
        proj = {**_LIMINAL_SAMPLE, "collapse_tendency": 0.0}
        state = self.mapper.map(proj)
        # liminal base = 0.5, nudge = 0
        assert abs(state.depth_factor - 0.5) < 1e-9

    def test_manifest_depth_base(self):
        proj = {**_MANIFEST_SAMPLE, "collapse_tendency": 0.0}
        state = self.mapper.map(proj)
        # manifest base = 0.95, nudge = 0
        assert abs(state.depth_factor - 0.95) < 1e-9

    def test_collapse_nudges_depth(self):
        proj = {**_LIMINAL_SAMPLE, "collapse_tendency": 0.8}
        state = self.mapper.map(proj)
        # 0.5 + 0.25 * 0.8 = 0.7
        assert abs(state.depth_factor - 0.7) < 1e-9

    def test_depth_clamped_at_1(self):
        proj = {**_MANIFEST_SAMPLE, "collapse_tendency": 1.0}
        state = self.mapper.map(proj)
        assert state.depth_factor <= 1.0

    def test_topology_visibility_from_weights(self):
        proj = {**_LIMINAL_SAMPLE, "active_weights": {"m1": 0.9, "m2": 0.4}}
        state = self.mapper.map(proj)
        assert abs(state.topology_visibility - 0.9) < 1e-9

    def test_topology_visibility_empty_weights(self):
        proj = {**_LIMINAL_SAMPLE, "active_weights": {}}
        state = self.mapper.map(proj)
        assert state.topology_visibility == 0.0

    def test_topology_visibility_none_weights(self):
        proj = {**_LIMINAL_SAMPLE, "active_weights": None}
        state = self.mapper.map(proj)
        assert state.topology_visibility == 0.0

    def test_domain_path_local(self):
        proj = {**_LIMINAL_SAMPLE, "runtime_domain": "local"}
        state = self.mapper.map(proj)
        assert state.domain_path_emphasis == 0.0

    def test_domain_path_transition(self):
        proj = {**_LIMINAL_SAMPLE, "runtime_domain": "transition"}
        state = self.mapper.map(proj)
        assert state.domain_path_emphasis == 0.5

    def test_domain_path_cross_device(self):
        proj = {**_LIMINAL_SAMPLE, "runtime_domain": "cross_device"}
        state = self.mapper.map(proj)
        assert state.domain_path_emphasis == 1.0

    def test_domain_path_none_domain(self):
        proj = {**_LIMINAL_SAMPLE, "runtime_domain": None}
        state = self.mapper.map(proj)
        assert state.domain_path_emphasis == 0.0

    def test_ambient_geometric_mean(self):
        proj = {**_LIMINAL_SAMPLE, "presence_intensity": 0.64, "coherence": 0.36}
        state = self.mapper.map(proj)
        expected = math.sqrt(0.64 * 0.36)
        assert abs(state.ambient_intensity - expected) < 1e-9

    def test_ambient_with_none_values(self):
        proj = {**_SILENT_MINIMAL, "presence_intensity": None, "coherence": None}
        state = self.mapper.map(proj)
        assert state.ambient_intensity == 0.0

    def test_ambient_with_zero_coherence(self):
        proj = {**_LIMINAL_SAMPLE, "presence_intensity": 0.9, "coherence": 0.0}
        state = self.mapper.map(proj)
        assert state.ambient_intensity == 0.0

    def test_source_phase_preserved(self):
        state = self.mapper.map(_LIMINAL_SAMPLE)
        assert state.source_phase == "liminal"

    def test_source_domain_preserved(self):
        state = self.mapper.map(_MANIFEST_SAMPLE)
        assert state.source_domain == "cross_device"

    def test_source_domain_none_preserved(self):
        state = self.mapper.map(_SILENT_MINIMAL)
        assert state.source_domain is None

    def test_accepts_object_with_to_dict(self):
        """Mapper should work with any object that has a .to_dict() method."""
        class FakeProjection:
            def to_dict(self):
                return _LIMINAL_SAMPLE
        state = self.mapper.map(FakeProjection())
        assert state.source_phase == "liminal"

    def test_to_dict_round_trip(self):
        state = self.mapper.map(_LIMINAL_SAMPLE)
        d = state.to_dict()
        assert "depth_factor" in d
        assert "topology_visibility" in d
        assert "domain_path_emphasis" in d
        assert "ambient_intensity" in d
        assert "source_phase" in d
        assert "source_domain" in d

    def test_all_phase_domain_combinations(self):
        """Smoke test: all phase × domain combinations must not raise."""
        phases = ["silent", "liminal", "manifest"]
        domains = ["local", "transition", "cross_device", None]
        for phase in phases:
            for domain in domains:
                proj = {**_LIMINAL_SAMPLE, "tri_state_phase": phase, "runtime_domain": domain}
                state = self.mapper.map(proj)
                assert 0.0 <= state.depth_factor <= 1.0
                assert 0.0 <= state.topology_visibility <= 1.0
                assert 0.0 <= state.domain_path_emphasis <= 1.0
                assert 0.0 <= state.ambient_intensity <= 1.0


# ---------------------------------------------------------------------------
# TransitionAnimator tests
# ---------------------------------------------------------------------------

class TestTransitionAnimator:
    """Tests for TransitionAnimator."""

    def setup_method(self):
        from desktop_projection.transition_animator import TransitionAnimator, EasingCurve, TransitionPhase
        from desktop_projection.state_space_mapper import StateSpaceMapper, LiminalSpaceState
        self.TransitionAnimator = TransitionAnimator
        self.EasingCurve = EasingCurve
        self.TransitionPhase = TransitionPhase
        self.StateSpaceMapper = StateSpaceMapper
        self.LiminalSpaceState = LiminalSpaceState
        self.animator = TransitionAnimator()
        self.mapper = StateSpaceMapper()

    def _state(self, proj):
        return self.mapper.map(proj)

    def test_interpolate_yields_correct_step_count(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frames = list(self.animator.interpolate(source, target, steps=15))
        assert len(frames) == 15

    def test_last_frame_equals_target(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frames = list(self.animator.interpolate(source, target, steps=10))
        last = frames[-1]
        # All numeric dimensions should be exactly equal to target at t=1.
        assert abs(last.depth_factor - target.depth_factor) < 1e-9
        assert abs(last.topology_visibility - target.topology_visibility) < 1e-9
        assert abs(last.domain_path_emphasis - target.domain_path_emphasis) < 1e-9
        assert abs(last.ambient_intensity - target.ambient_intensity) < 1e-9

    def test_first_frame_not_equal_to_source(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_MANIFEST_SAMPLE)
        frames = list(self.animator.interpolate(source, target, steps=10))
        first = frames[0]
        # At least one dimension should differ from source.
        differ = (
            abs(first.depth_factor - source.depth_factor) > 1e-9
            or abs(first.topology_visibility - source.topology_visibility) > 1e-9
        )
        assert differ

    def test_single_step_gives_target(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frames = list(self.animator.interpolate(source, target, steps=1))
        assert len(frames) == 1
        assert abs(frames[0].depth_factor - target.depth_factor) < 1e-9

    @pytest.mark.parametrize("curve_name", ["linear", "ease_in_out", "ease_out"])
    def test_easing_monotonically_non_decreasing(self, curve_name):
        """Easing t in [0,1] should always produce non-decreasing output."""
        from desktop_projection.transition_animator import (
            _ease_linear, _ease_in_out, _ease_out, EasingCurve
        )
        fn_map = {
            "linear": _ease_linear,
            "ease_in_out": _ease_in_out,
            "ease_out": _ease_out,
        }
        fn = fn_map[curve_name]
        steps = 100
        prev = fn(0.0)
        for i in range(1, steps + 1):
            t = i / steps
            val = fn(t)
            assert val >= prev - 1e-12, f"{curve_name} not monotonic at t={t}"
            prev = val

    def test_ease_in_out_boundary_values(self):
        from desktop_projection.transition_animator import _ease_in_out
        assert abs(_ease_in_out(0.0) - 0.0) < 1e-9
        assert abs(_ease_in_out(1.0) - 1.0) < 1e-9

    def test_ease_out_boundary_values(self):
        from desktop_projection.transition_animator import _ease_out
        assert abs(_ease_out(0.0) - 0.0) < 1e-9
        assert abs(_ease_out(1.0) - 1.0) < 1e-9

    def test_classify_silent_to_liminal(self):
        source = self.LiminalSpaceState(source_phase="silent")
        target = self.LiminalSpaceState(source_phase="liminal")
        tp = self.animator.classify_transition(source, target)
        assert tp == self.TransitionPhase.SILENT_TO_LIMINAL

    def test_classify_liminal_to_manifest(self):
        source = self.LiminalSpaceState(source_phase="liminal")
        target = self.LiminalSpaceState(source_phase="manifest")
        tp = self.animator.classify_transition(source, target)
        assert tp == self.TransitionPhase.LIMINAL_TO_MANIFEST

    def test_classify_manifest_to_liminal(self):
        source = self.LiminalSpaceState(source_phase="manifest")
        target = self.LiminalSpaceState(source_phase="liminal")
        tp = self.animator.classify_transition(source, target)
        assert tp == self.TransitionPhase.MANIFEST_TO_LIMINAL

    def test_classify_liminal_to_silent(self):
        source = self.LiminalSpaceState(source_phase="liminal")
        target = self.LiminalSpaceState(source_phase="silent")
        tp = self.animator.classify_transition(source, target)
        assert tp == self.TransitionPhase.LIMINAL_TO_SILENT

    def test_classify_identity(self):
        source = self.LiminalSpaceState(source_phase="liminal")
        target = self.LiminalSpaceState(source_phase="liminal")
        tp = self.animator.classify_transition(source, target)
        assert tp == self.TransitionPhase.IDENTITY

    def test_recommend_curve_retreat_is_ease_out(self):
        tp = self.TransitionPhase.LIMINAL_TO_SILENT
        curve = self.animator.recommend_curve(tp)
        assert curve == self.EasingCurve.EASE_OUT

    def test_recommend_curve_forward_is_ease_in_out(self):
        tp = self.TransitionPhase.SILENT_TO_LIMINAL
        curve = self.animator.recommend_curve(tp)
        assert curve == self.EasingCurve.EASE_IN_OUT

    def test_single_frame_t0_is_source(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frame = self.animator.single_frame(source, target, t=0.0)
        assert abs(frame.depth_factor - source.depth_factor) < 1e-9

    def test_single_frame_t1_is_target(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frame = self.animator.single_frame(source, target, t=1.0)
        assert abs(frame.depth_factor - target.depth_factor) < 1e-9

    def test_single_frame_clamps_below_zero(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frame = self.animator.single_frame(source, target, t=-1.0)
        # Clamped to t=0 → depth should equal source
        assert abs(frame.depth_factor - source.depth_factor) < 1e-9

    def test_single_frame_clamps_above_one(self):
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_LIMINAL_SAMPLE)
        frame = self.animator.single_frame(source, target, t=2.0)
        # Clamped to t=1 → depth should equal target
        assert abs(frame.depth_factor - target.depth_factor) < 1e-9

    def test_interpolation_stability_no_nan(self):
        """No frame should contain NaN or Inf."""
        source = self._state(_SILENT_MINIMAL)
        target = self._state(_MANIFEST_SAMPLE)
        for frame in self.animator.interpolate(source, target, steps=50):
            assert math.isfinite(frame.depth_factor)
            assert math.isfinite(frame.topology_visibility)
            assert math.isfinite(frame.domain_path_emphasis)
            assert math.isfinite(frame.ambient_intensity)


# ---------------------------------------------------------------------------
# LiminalSpaceEngine tests
# ---------------------------------------------------------------------------

class TestLiminalSpaceEngine:
    """Tests for LiminalSpaceEngine."""

    def setup_method(self):
        from desktop_projection.liminal_space_engine import LiminalSpaceEngine
        self.LiminalSpaceEngine = LiminalSpaceEngine

    def test_initial_state_is_none(self):
        engine = self.LiminalSpaceEngine()
        assert engine.current_state is None

    def test_first_update_returns_single_frame(self):
        engine = self.LiminalSpaceEngine()
        frames = engine.update(_SILENT_MINIMAL)
        assert len(frames) == 1

    def test_first_update_sets_current_state(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_SILENT_MINIMAL)
        assert engine.current_state is not None
        assert engine.current_state.source_phase == "silent"

    def test_second_update_returns_transition_frames(self):
        engine = self.LiminalSpaceEngine(default_steps=10)
        engine.update(_SILENT_MINIMAL)
        frames = engine.update(_LIMINAL_SAMPLE)
        assert len(frames) == 10

    def test_current_state_updated_to_target(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_SILENT_MINIMAL)
        engine.update(_LIMINAL_SAMPLE)
        assert engine.current_state.source_phase == "liminal"

    def test_reset_clears_current_state(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_SILENT_MINIMAL)
        engine.reset()
        assert engine.current_state is None

    def test_reset_then_update_acts_as_first_call(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_SILENT_MINIMAL)
        engine.update(_LIMINAL_SAMPLE)
        engine.reset()
        frames = engine.update(_MANIFEST_SAMPLE)
        assert len(frames) == 1

    def test_render_text_produces_string(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_LIMINAL_SAMPLE)
        text = engine.render_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_render_text_contains_phase(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_LIMINAL_SAMPLE)
        text = engine.render_text()
        assert "liminal" in text.lower()

    def test_render_text_no_state_returns_placeholder(self):
        engine = self.LiminalSpaceEngine()
        text = engine.render_text()
        assert "no state" in text.lower()

    def test_render_text_explicit_state(self):
        from desktop_projection.state_space_mapper import StateSpaceMapper
        engine = self.LiminalSpaceEngine()
        state = StateSpaceMapper().map(_MANIFEST_SAMPLE)
        text = engine.render_text(state)
        assert "manifest" in text.lower()

    def test_custom_steps_used_in_transition(self):
        engine = self.LiminalSpaceEngine()
        engine.update(_SILENT_MINIMAL)
        frames = engine.update(_MANIFEST_SAMPLE, transition_steps=5)
        assert len(frames) == 5

    def test_last_frame_equals_target_state(self):
        from desktop_projection.state_space_mapper import StateSpaceMapper
        engine = self.LiminalSpaceEngine(default_steps=15)
        engine.update(_SILENT_MINIMAL)
        frames = engine.update(_MANIFEST_SAMPLE)
        target = StateSpaceMapper().map(_MANIFEST_SAMPLE)
        last = frames[-1]
        assert abs(last.depth_factor - target.depth_factor) < 1e-9


# ---------------------------------------------------------------------------
# LiminalSurface tests
# ---------------------------------------------------------------------------

class TestLiminalSurface:
    """Tests for the Status Board V2 LiminalSurface adapter."""

    def setup_method(self):
        from windows_client.status_board_v2.liminal_surface import LiminalSurface
        self.surface = LiminalSurface()

    def test_render_returns_string(self):
        result = self.surface.render(_LIMINAL_SAMPLE)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_contains_liminal_label(self):
        result = self.surface.render(_LIMINAL_SAMPLE)
        assert "Liminal" in result

    def test_render_contains_depth_label(self):
        result = self.surface.render(_LIMINAL_SAMPLE)
        assert "Depth" in result

    def test_render_contains_topology_label(self):
        result = self.surface.render(_LIMINAL_SAMPLE)
        assert "Topology" in result

    def test_render_contains_ambient_label(self):
        result = self.surface.render(_LIMINAL_SAMPLE)
        assert "Ambient" in result

    def test_render_minimal_projection(self):
        result = self.surface.render(_SILENT_MINIMAL)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_manifest_projection(self):
        result = self.surface.render(_MANIFEST_SAMPLE)
        assert "manifest" in result

    def test_render_does_not_raise_on_empty_dict(self):
        """An empty dict should not raise — graceful degradation."""
        result = self.surface.render({})
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Boundary condition tests
# ---------------------------------------------------------------------------

class TestBoundaryConditions:
    """Explicit boundary/extreme value tests."""

    def setup_method(self):
        from desktop_projection.state_space_mapper import StateSpaceMapper
        from desktop_projection.transition_animator import TransitionAnimator
        self.mapper = StateSpaceMapper()
        self.animator = TransitionAnimator()

    def test_silent_extreme_depth_near_zero(self):
        proj = {**_SILENT_MINIMAL, "collapse_tendency": 0.0}
        state = self.mapper.map(proj)
        assert state.depth_factor < 0.15

    def test_manifest_extreme_depth_near_one(self):
        proj = {**_MANIFEST_SAMPLE, "collapse_tendency": 1.0}
        state = self.mapper.map(proj)
        assert state.depth_factor >= 0.95

    def test_cross_device_full_path_emphasis(self):
        proj = {**_MANIFEST_SAMPLE, "runtime_domain": "cross_device"}
        state = self.mapper.map(proj)
        assert state.domain_path_emphasis == 1.0

    def test_zero_weights_zero_visibility(self):
        proj = {**_LIMINAL_SAMPLE, "active_weights": {"m1": 0.0, "m2": 0.0}}
        state = self.mapper.map(proj)
        assert state.topology_visibility == 0.0

    def test_all_dimensions_in_unit_interval(self):
        """All four dimensions must stay in [0, 1] for extreme inputs."""
        extreme = {
            "tri_state_phase": "manifest",
            "runtime_domain": "cross_device",
            "presence_intensity": 1.0,
            "coherence": 1.0,
            "collapse_tendency": 1.0,
            "retreat_tendency": 1.0,
            "active_weights": {"m": 1.0},
        }
        state = self.mapper.map(extreme)
        for dim_name in ("depth_factor", "topology_visibility", "domain_path_emphasis", "ambient_intensity"):
            val = getattr(state, dim_name)
            assert 0.0 <= val <= 1.0, f"{dim_name}={val} out of [0,1]"

    def test_zero_presence_zero_ambient(self):
        proj = {**_LIMINAL_SAMPLE, "presence_intensity": 0.0, "coherence": 0.0}
        state = self.mapper.map(proj)
        assert state.ambient_intensity == 0.0

    def test_max_presence_coherence_ambient_is_1(self):
        proj = {**_LIMINAL_SAMPLE, "presence_intensity": 1.0, "coherence": 1.0}
        state = self.mapper.map(proj)
        assert abs(state.ambient_intensity - 1.0) < 1e-9

    def test_identity_transition_all_same(self):
        """Same source and target → all frames identical to target."""
        from desktop_projection.state_space_mapper import LiminalSpaceState
        state = self.mapper.map(_LIMINAL_SAMPLE)
        frames = list(self.animator.interpolate(state, state, steps=10))
        for frame in frames:
            assert abs(frame.depth_factor - state.depth_factor) < 1e-9
