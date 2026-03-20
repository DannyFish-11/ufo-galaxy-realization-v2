"""
tests/test_pr6_manifest_stage.py
=================================
Tests for PR-6: Manifest Stage Surface (显现台).

Coverage
--------
1. ManifestStageState
   - dataclass defaults
   - to_dict() round-trip
   - __repr__ format

2. ManifestStageController — state mapping
   - focus_intensity derived from ambient * coherence + collapse nudge
   - stage_ready True when ambient >= STAGE_READY_THRESHOLD and retreat low
   - stage_ready False when ambient below threshold
   - stage_ready False when retreat_tendency high
   - top-N weights are stable (sorted descending by weight)
   - primary_model_id, support_model_ids, active_device_ids forwarded
   - task_summary forwarded (current_task_summary and task_summary aliases)
   - execution_stage forwarded
   - route_reason forwarded
   - source_phase forwarded
   - empty/None fields handled gracefully
   - focus clamped to [0, 1]

3. ManifestStageController — retreat softening
   - first call with high retreat returns raw focus (no previous state)
   - second call with high retreat blends toward previous
   - reset() clears previous state

4. ManifestStageController — smooth transition
   - sequential liminal → manifest projections increase focus monotonically
   - retreat injection mid-sequence softens focus

5. ManifestStageController — edge cases
   - all-None projection returns valid ManifestStageState
   - accepts typed object with to_dict()
   - accepts LiminalSpaceState object

6. ManifestSurface (Status Board V2)
   - render() returns non-empty string
   - contains expected field labels
   - ● READY label when stage_ready
   - ○ HOLD label when not stage_ready
   - handles None / missing fields gracefully
"""

from __future__ import annotations

import math
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Shared test fixtures
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
    "retreat_tendency": 0.05,
}

_RETREAT_SAMPLE: Dict[str, Any] = {
    **_MANIFEST_SAMPLE,
    "retreat_tendency": 0.75,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_liminal(ambient: float = 0.5, source_phase: str = "liminal") -> object:
    """Return a minimal LiminalSpaceState-like dict."""
    return {
        "depth_factor": 0.5,
        "topology_visibility": 0.5,
        "domain_path_emphasis": 0.0,
        "ambient_intensity": ambient,
        "source_phase": source_phase,
        "source_domain": None,
    }


# ---------------------------------------------------------------------------
# 1. ManifestStageState dataclass
# ---------------------------------------------------------------------------

class TestManifestStageState:
    """Tests for the ManifestStageState dataclass."""

    def setup_method(self):
        from desktop_projection.manifest_stage_state import ManifestStageState
        self.cls = ManifestStageState

    def test_defaults(self):
        s = self.cls()
        assert s.task_summary is None
        assert s.execution_stage is None
        assert s.primary_model_id is None
        assert s.support_model_ids == []
        assert s.active_device_ids == []
        assert s.active_weights == {}
        assert s.route_reason is None
        assert s.focus_intensity == 0.0
        assert s.stage_ready is False
        assert s.source_phase == "silent"

    def test_to_dict_round_trip(self):
        s = self.cls(
            task_summary="demo",
            execution_stage="executing",
            primary_model_id="gpt-4o",
            support_model_ids=["claude-3"],
            active_device_ids=["win"],
            active_weights={"gpt-4o": 0.9},
            route_reason="native",
            focus_intensity=0.75,
            stage_ready=True,
            source_phase="manifest",
        )
        d = s.to_dict()
        assert d["task_summary"] == "demo"
        assert d["execution_stage"] == "executing"
        assert d["primary_model_id"] == "gpt-4o"
        assert d["support_model_ids"] == ["claude-3"]
        assert d["active_device_ids"] == ["win"]
        assert d["active_weights"] == {"gpt-4o": 0.9}
        assert d["route_reason"] == "native"
        assert abs(d["focus_intensity"] - 0.75) < 1e-9
        assert d["stage_ready"] is True
        assert d["source_phase"] == "manifest"

    def test_repr_contains_key_fields(self):
        s = self.cls(source_phase="manifest", stage_ready=True, focus_intensity=0.8)
        r = repr(s)
        assert "manifest" in r
        assert "True" in r
        assert "0.800" in r


# ---------------------------------------------------------------------------
# 2. ManifestStageController — state mapping
# ---------------------------------------------------------------------------

class TestManifestStageControllerMapping:
    """Tests for ManifestStageController.update() field mapping."""

    def setup_method(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        self.ctrl = ManifestStageController()

    def test_focus_intensity_positive_when_ambient_and_coherence(self):
        liminal = _make_liminal(ambient=0.64)
        proj = {**_MANIFEST_SAMPLE, "coherence": 0.36, "collapse_tendency": 0.0}
        state = self.ctrl.update(proj, liminal)
        # base = sqrt(0.64 * 0.36) = sqrt(0.2304) = 0.48
        assert abs(state.focus_intensity - 0.48) < 1e-6

    def test_focus_intensity_nudged_by_collapse(self):
        liminal = _make_liminal(ambient=0.64)
        proj = {**_MANIFEST_SAMPLE, "coherence": 0.36, "collapse_tendency": 0.4}
        state = self.ctrl.update(proj, liminal)
        # 0.48 + 0.15 * 0.4 = 0.48 + 0.06 = 0.54
        assert abs(state.focus_intensity - 0.54) < 1e-6

    def test_focus_clamped_to_one(self):
        liminal = _make_liminal(ambient=1.0)
        proj = {**_MANIFEST_SAMPLE, "coherence": 1.0, "collapse_tendency": 1.0}
        state = self.ctrl.update(proj, liminal)
        assert state.focus_intensity <= 1.0

    def test_focus_zero_when_ambient_zero(self):
        liminal = _make_liminal(ambient=0.0)
        proj = {**_MANIFEST_SAMPLE, "coherence": 0.9, "collapse_tendency": 0.0}
        state = self.ctrl.update(proj, liminal)
        assert state.focus_intensity == 0.0

    def test_stage_ready_true_above_threshold(self):
        liminal = _make_liminal(ambient=0.5)  # >= 0.35
        proj = {**_MANIFEST_SAMPLE, "retreat_tendency": 0.1}
        state = self.ctrl.update(proj, liminal)
        assert state.stage_ready is True

    def test_stage_ready_false_below_threshold(self):
        liminal = _make_liminal(ambient=0.2)  # < 0.35
        state = self.ctrl.update(_MANIFEST_SAMPLE, liminal)
        assert state.stage_ready is False

    def test_stage_ready_false_at_exactly_threshold(self):
        from desktop_projection.manifest_stage_state import STAGE_READY_THRESHOLD
        liminal = _make_liminal(ambient=STAGE_READY_THRESHOLD)
        proj = {**_MANIFEST_SAMPLE, "retreat_tendency": 0.1}
        state = self.ctrl.update(proj, liminal)
        assert state.stage_ready is True

    def test_stage_ready_false_when_retreat_high(self):
        liminal = _make_liminal(ambient=0.8)
        proj = {**_MANIFEST_SAMPLE, "retreat_tendency": 0.8}
        state = self.ctrl.update(proj, liminal)
        assert state.stage_ready is False

    def test_active_weights_top_n_sorted(self):
        weights = {"m1": 0.2, "m2": 0.9, "m3": 0.5, "m4": 0.7, "m5": 0.3, "m6": 0.8}
        proj = {**_MANIFEST_SAMPLE, "active_weights": weights}
        state = self.ctrl.update(proj, _make_liminal())
        # top-5 by weight desc: m2(0.9), m6(0.8), m4(0.7), m3(0.5), m5(0.3)
        items = list(state.active_weights.items())
        assert items[0] == ("m2", 0.9)
        assert items[1] == ("m6", 0.8)
        assert items[2] == ("m4", 0.7)
        assert items[3] == ("m3", 0.5)
        assert items[4] == ("m5", 0.3)
        assert len(items) == 5  # m1 excluded (only top 5)

    def test_weights_stable_order_idempotent(self):
        """Same weights should produce identical ordering on repeated calls."""
        weights = {"a": 0.5, "b": 0.9, "c": 0.3}
        proj = {**_MANIFEST_SAMPLE, "active_weights": weights}
        ctrl = __import__(
            "desktop_projection.manifest_stage_controller",
            fromlist=["ManifestStageController"],
        ).ManifestStageController()
        s1 = ctrl.update(proj, _make_liminal())
        ctrl.reset()
        s2 = ctrl.update(proj, _make_liminal())
        assert list(s1.active_weights.items()) == list(s2.active_weights.items())

    def test_forwarded_fields(self):
        state = self.ctrl.update(_MANIFEST_SAMPLE, _make_liminal())
        assert state.primary_model_id == "gpt-4o"
        assert "claude-3" in state.support_model_ids
        assert "desktop-win" in state.active_device_ids
        assert state.route_reason == "native preferred"
        assert state.execution_stage == "planning"
        assert state.task_summary == "test task"
        assert state.source_phase == "manifest"

    def test_task_summary_alias(self):
        """task_summary field (instead of current_task_summary) should also work."""
        proj = {**_MANIFEST_SAMPLE, "current_task_summary": None, "task_summary": "alt task"}
        state = self.ctrl.update(proj, _make_liminal())
        assert state.task_summary == "alt task"

    def test_all_none_projection_returns_valid_state(self):
        state = self.ctrl.update(_SILENT_MINIMAL, _make_liminal(ambient=0.0))
        assert state.focus_intensity == 0.0
        assert state.stage_ready is False
        assert state.primary_model_id is None
        assert state.support_model_ids == []
        assert state.active_weights == {}

    def test_accepts_object_with_to_dict(self):
        """Controller accepts typed objects that implement to_dict()."""
        class FakeProjection:
            def to_dict(self):
                return dict(_MANIFEST_SAMPLE)
        state = self.ctrl.update(FakeProjection(), _make_liminal())
        assert state.primary_model_id == "gpt-4o"

    def test_accepts_liminal_state_object(self):
        """Controller accepts a LiminalSpaceState object (not just dict)."""
        from desktop_projection.state_space_mapper import LiminalSpaceState
        lim_obj = LiminalSpaceState(ambient_intensity=0.6, source_phase="liminal")
        state = self.ctrl.update(_MANIFEST_SAMPLE, lim_obj)
        assert state.stage_ready is True


# ---------------------------------------------------------------------------
# 3. ManifestStageController — retreat softening
# ---------------------------------------------------------------------------

class TestRetreatSoftening:
    """Tests for the retreat_tendency softening policy."""

    def test_first_call_no_softening(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController(retreat_blend=0.7)
        liminal = _make_liminal(ambient=0.6)
        proj = {**_RETREAT_SAMPLE, "coherence": 0.36, "collapse_tendency": 0.0}
        state = ctrl.update(proj, liminal)
        # No previous state → raw focus applies
        # sqrt(0.6 * 0.36) ≈ 0.4648
        expected = math.sqrt(0.6 * 0.36)
        assert abs(state.focus_intensity - expected) < 1e-6

    def test_second_call_retreat_softens_focus(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController(retreat_blend=0.7)
        liminal_hi = _make_liminal(ambient=0.64)
        proj_normal = {**_MANIFEST_SAMPLE, "coherence": 0.36, "collapse_tendency": 0.0, "retreat_tendency": 0.1}
        first = ctrl.update(proj_normal, liminal_hi)
        prev_focus = first.focus_intensity  # ~0.48

        liminal_lo = _make_liminal(ambient=0.0)
        proj_retreat = {**_MANIFEST_SAMPLE, "coherence": 0.0, "collapse_tendency": 0.0, "retreat_tendency": 0.9}
        second = ctrl.update(proj_retreat, liminal_lo)
        # raw_focus = 0.0; blended = 0.7 * 0.48 + 0.3 * 0.0 = 0.336
        expected = 0.7 * prev_focus
        assert abs(second.focus_intensity - expected) < 1e-6

    def test_reset_clears_previous(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController(retreat_blend=0.7)
        ctrl.update(_MANIFEST_SAMPLE, _make_liminal())
        assert ctrl.previous_state is not None
        ctrl.reset()
        assert ctrl.previous_state is None

    def test_invalid_retreat_blend_raises(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        with pytest.raises(ValueError):
            ManifestStageController(retreat_blend=1.5)


# ---------------------------------------------------------------------------
# 4. ManifestStageController — smooth transition
# ---------------------------------------------------------------------------

class TestSmoothTransition:
    """Integration-level: stage progression should be monotone in normal operation."""

    def test_liminal_to_manifest_focus_increases(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController()

        projections = [
            {**_LIMINAL_SAMPLE, "presence_intensity": p, "coherence": p, "collapse_tendency": p * 0.5}
            for p in [0.2, 0.4, 0.6, 0.8, 0.95]
        ]
        ambients = [0.1, 0.25, 0.45, 0.65, 0.85]

        focuses = []
        for proj, amb in zip(projections, ambients):
            state = ctrl.update(proj, _make_liminal(ambient=amb))
            focuses.append(state.focus_intensity)

        # Each step should not decrease (weakly monotone)
        for i in range(1, len(focuses)):
            assert focuses[i] >= focuses[i - 1] - 1e-6, (
                f"Focus decreased at step {i}: {focuses[i-1]:.4f} → {focuses[i]:.4f}"
            )

    def test_retreat_mid_sequence_softens(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController(retreat_blend=0.9)

        # Build up focus
        ctrl.update(_MANIFEST_SAMPLE, _make_liminal(ambient=0.8))
        prev_focus = ctrl.previous_state.focus_intensity

        # Inject retreat
        retreat_proj = {**_MANIFEST_SAMPLE, "retreat_tendency": 0.9, "coherence": 0.0}
        after_retreat = ctrl.update(retreat_proj, _make_liminal(ambient=0.0))

        # Focus should be softened, not fully zeroed
        assert after_retreat.focus_intensity > 0.0
        assert after_retreat.focus_intensity < prev_focus


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge-case coverage for ManifestStageController."""

    def test_empty_weights_returns_empty_active_weights(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        proj = {**_MANIFEST_SAMPLE, "active_weights": {}}
        state = ManifestStageController().update(proj, _make_liminal())
        assert state.active_weights == {}

    def test_none_weights_returns_empty_active_weights(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        proj = {**_MANIFEST_SAMPLE, "active_weights": None}
        state = ManifestStageController().update(proj, _make_liminal())
        assert state.active_weights == {}

    def test_focus_zero_when_coherence_zero(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        proj = {**_MANIFEST_SAMPLE, "coherence": 0.0, "collapse_tendency": 0.0}
        state = ManifestStageController().update(proj, _make_liminal(ambient=0.8))
        # sqrt(0.8 * 0.0) = 0
        assert state.focus_intensity == 0.0

    def test_source_phase_preserved_silent(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        state = ManifestStageController().update(_SILENT_MINIMAL, _make_liminal(ambient=0.0))
        assert state.source_phase == "silent"

    def test_top_n_custom(self):
        from desktop_projection.manifest_stage_controller import ManifestStageController
        ctrl = ManifestStageController(top_n=2)
        weights = {"a": 0.9, "b": 0.8, "c": 0.7, "d": 0.6}
        proj = {**_MANIFEST_SAMPLE, "active_weights": weights}
        state = ctrl.update(proj, _make_liminal())
        assert len(state.active_weights) == 2
        assert "a" in state.active_weights
        assert "b" in state.active_weights


# ---------------------------------------------------------------------------
# 6. ManifestSurface (Status Board V2)
# ---------------------------------------------------------------------------

class TestManifestSurface:
    """Tests for the ManifestSurface read-only render adapter."""

    def setup_method(self):
        from windows_client.status_board_v2.manifest_surface import ManifestSurface
        self.surface = ManifestSurface()

    def test_render_returns_non_empty_string(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_render_contains_expected_labels(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "Manifest Stage" in output
        assert "Focus" in output
        assert "Primary" in output
        assert "Weights" in output

    def test_render_ready_label_when_stage_ready(self):
        # ambient_intensity from StateSpaceMapper on manifest sample should be high
        output = self.surface.render(_MANIFEST_SAMPLE)
        # Should contain the READY or HOLD indicator
        assert "READY" in output or "HOLD" in output

    def test_render_hold_label_on_silent(self):
        output = self.surface.render(_SILENT_MINIMAL)
        assert "HOLD" in output

    def test_render_handles_none_fields_gracefully(self):
        output = self.surface.render(_SILENT_MINIMAL)
        assert isinstance(output, str)
        assert len(output) > 0

    def test_render_shows_primary_model(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "gpt-4o" in output

    def test_render_shows_task_summary(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "test task" in output

    def test_render_shows_execution_stage(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "planning" in output

    def test_render_shows_route_reason(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "native preferred" in output

    def test_render_shows_device(self):
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert "desktop-win" in output

    def test_render_is_read_only_no_command_interface(self):
        """Sanity check: render() returns a string, not a widget or callable."""
        output = self.surface.render(_MANIFEST_SAMPLE)
        assert isinstance(output, str)
        assert callable(getattr(self.surface, "render"))
        # No 'send', 'submit', 'execute', or 'command' methods.
        for forbidden in ("send", "submit", "execute", "command"):
            assert not hasattr(self.surface, forbidden), (
                f"ManifestSurface should not expose '{forbidden}' method"
            )
