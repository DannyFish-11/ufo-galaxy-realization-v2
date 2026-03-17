"""
PR-5: Generative UI Runtime — unit tests
=========================================

Covers:
* SurfaceType enum values and string round-trip
* SurfaceSpec construction and to_dict() serialisation
* SurfaceSelector.select_surface() mapping for every InteractionMode
* SurfaceSelector with None / dict / object envelopes
* SurfaceSelector unknown-mode fallback
* GenerativeUIRuntime.render_surface() happy-path and error resilience
* GenerativeUIRuntime.render_surface_dict() JSON-serialisable output
* get_generative_ui_runtime() singleton behaviour
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# SurfaceType tests
# ---------------------------------------------------------------------------

class TestSurfaceType:
    def test_all_expected_values_exist(self):
        from core.generative_ui.widget_schema import SurfaceType

        expected = {
            "chat_panel",
            "deep_thinking_canvas",
            "control_console",
            "field_assistant_overlay_stub",
            "ambient_companion",
        }
        actual = {st.value for st in SurfaceType}
        assert expected == actual

    def test_string_identity(self):
        from core.generative_ui.widget_schema import SurfaceType

        for st in SurfaceType:
            assert SurfaceType(st.value) is st


# ---------------------------------------------------------------------------
# SurfaceSpec tests
# ---------------------------------------------------------------------------

class TestSurfaceSpec:
    def test_default_surface_is_chat_panel(self):
        from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType

        spec = SurfaceSpec()
        assert spec.surface_type == SurfaceType.CHAT_PANEL

    def test_to_dict_keys(self):
        from core.generative_ui.widget_schema import SurfaceSpec

        d = SurfaceSpec().to_dict()
        assert set(d.keys()) == {"surface_type", "title", "layout_hints", "fallback_surface"}

    def test_to_dict_surface_type_is_string(self):
        from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType

        spec = SurfaceSpec(surface_type=SurfaceType.CONTROL_CONSOLE)
        d = spec.to_dict()
        assert d["surface_type"] == "control_console"
        assert isinstance(d["surface_type"], str)

    def test_to_dict_is_json_serialisable(self):
        from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType

        spec = SurfaceSpec(
            surface_type=SurfaceType.DEEP_THINKING_CANVAS,
            title="test",
            layout_hints={"foo": True},
        )
        # Should not raise
        json.dumps(spec.to_dict())


# ---------------------------------------------------------------------------
# SurfaceSelector — core mapping tests
# ---------------------------------------------------------------------------

class TestSurfaceSelectorMapping:
    """Verify every InteractionMode maps to the expected SurfaceType."""

    @pytest.mark.parametrize("mode,expected_surface", [
        ("chat", "chat_panel"),
        ("deep_thinking", "deep_thinking_canvas"),
        ("control_console", "control_console"),
        ("field_assistant", "field_assistant_overlay_stub"),
        ("ambient_companion", "ambient_companion"),
        ("execution_bridge", "control_console"),
    ])
    def test_mode_to_surface_via_string_dict(self, mode: str, expected_surface: str):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface({"mode": mode})
        assert spec.surface_type.value == expected_surface

    @pytest.mark.parametrize("mode,expected_surface", [
        ("chat", "chat_panel"),
        ("deep_thinking", "deep_thinking_canvas"),
        ("control_console", "control_console"),
        ("field_assistant", "field_assistant_overlay_stub"),
        ("ambient_companion", "ambient_companion"),
        ("execution_bridge", "control_console"),
    ])
    def test_mode_to_surface_via_interaction_mode_enum(self, mode: str, expected_surface: str):
        """Test with actual InteractionMode enum values via dataclass envelope."""
        from core.generative_ui.surface_selector import SurfaceSelector
        from core.interaction.interaction_types import InteractionMode
        from core.schemas.interaction_envelope import InteractionEnvelope

        envelope = InteractionEnvelope(mode=mode)
        selector = SurfaceSelector()
        spec = selector.select_surface(envelope)
        assert spec.surface_type.value == expected_surface

    def test_unknown_mode_falls_back_to_chat_panel(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface({"mode": "totally_unknown_mode"})
        assert spec.surface_type.value == "chat_panel"

    def test_none_envelope_falls_back_to_chat_panel(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface(None)
        assert spec.surface_type.value == "chat_panel"

    def test_none_envelope_with_explicit_fallback_mode(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface(None, mode="deep_thinking")
        assert spec.surface_type.value == "deep_thinking_canvas"

    def test_empty_dict_falls_back_to_default_mode(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface({})
        assert spec.surface_type.value == "chat_panel"

    def test_spec_has_non_empty_title(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        for mode in ("chat", "deep_thinking", "control_console",
                     "field_assistant", "ambient_companion", "execution_bridge"):
            spec = selector.select_surface({"mode": mode})
            assert spec.title, f"No title for mode={mode!r}"

    def test_spec_has_layout_hints_dict(self):
        from core.generative_ui.surface_selector import SurfaceSelector

        selector = SurfaceSelector()
        spec = selector.select_surface({"mode": "control_console"})
        assert isinstance(spec.layout_hints, dict)

    def test_fallback_surface_always_chat_panel(self):
        from core.generative_ui.surface_selector import SurfaceSelector
        from core.generative_ui.widget_schema import SurfaceType

        selector = SurfaceSelector()
        for mode in ("chat", "deep_thinking", "control_console",
                     "field_assistant", "ambient_companion", "execution_bridge"):
            spec = selector.select_surface({"mode": mode})
            assert spec.fallback_surface == SurfaceType.CHAT_PANEL


# ---------------------------------------------------------------------------
# SurfaceSelector — envelope input variants
# ---------------------------------------------------------------------------

class TestSurfaceSelectorInputVariants:
    def test_object_with_mode_attribute(self):
        """select_surface() should read .mode from any object."""
        from core.generative_ui.surface_selector import SurfaceSelector

        obj = MagicMock()
        obj.mode = "deep_thinking"
        spec = SurfaceSelector().select_surface(obj)
        assert spec.surface_type.value == "deep_thinking_canvas"

    def test_object_with_enum_mode_attribute(self):
        """select_surface() handles InteractionMode enum on .mode."""
        from core.generative_ui.surface_selector import SurfaceSelector
        from core.interaction.interaction_types import InteractionMode

        obj = MagicMock()
        obj.mode = InteractionMode.CONTROL_CONSOLE
        spec = SurfaceSelector().select_surface(obj)
        assert spec.surface_type.value == "control_console"

    def test_object_raising_on_mode_falls_back(self):
        """Bad .mode access must not propagate — falls back to chat_panel."""
        from core.generative_ui.surface_selector import SurfaceSelector

        class _RaisingMode:
            @property
            def mode(self):
                raise RuntimeError("deliberate failure")

        spec = SurfaceSelector().select_surface(_RaisingMode())
        assert spec.surface_type.value == "chat_panel"


# ---------------------------------------------------------------------------
# GenerativeUIRuntime tests
# ---------------------------------------------------------------------------

class TestGenerativeUIRuntime:
    def test_render_surface_returns_surface_spec(self):
        from core.generative_ui.runtime import GenerativeUIRuntime
        from core.generative_ui.widget_schema import SurfaceSpec

        runtime = GenerativeUIRuntime()
        spec = runtime.render_surface()
        assert isinstance(spec, SurfaceSpec)

    def test_render_surface_none_gives_chat_panel(self):
        from core.generative_ui.runtime import GenerativeUIRuntime

        runtime = GenerativeUIRuntime()
        spec = runtime.render_surface(None)
        assert spec.surface_type.value == "chat_panel"

    @pytest.mark.parametrize("mode,expected_surface", [
        ("chat", "chat_panel"),
        ("deep_thinking", "deep_thinking_canvas"),
        ("control_console", "control_console"),
        ("field_assistant", "field_assistant_overlay_stub"),
        ("ambient_companion", "ambient_companion"),
        ("execution_bridge", "control_console"),
    ])
    def test_render_surface_all_modes(self, mode: str, expected_surface: str):
        from core.generative_ui.runtime import GenerativeUIRuntime

        runtime = GenerativeUIRuntime()
        spec = runtime.render_surface({"mode": mode})
        assert spec.surface_type.value == expected_surface

    def test_render_surface_error_resilience(self):
        """A broken envelope must not raise — runtime returns fallback."""
        from core.generative_ui.runtime import GenerativeUIRuntime
        from core.generative_ui.widget_schema import SurfaceType

        runtime = GenerativeUIRuntime()

        class _Bomb:
            @property
            def mode(self):
                raise RuntimeError("deliberate failure")

        spec = runtime.render_surface(_Bomb())
        assert spec.surface_type == SurfaceType.CHAT_PANEL

    def test_render_surface_dict_is_json_serialisable(self):
        from core.generative_ui.runtime import GenerativeUIRuntime

        runtime = GenerativeUIRuntime()
        d = runtime.render_surface_dict({"mode": "deep_thinking"})
        assert isinstance(d, dict)
        # Must not raise
        json.dumps(d)

    def test_render_surface_dict_has_required_keys(self):
        from core.generative_ui.runtime import GenerativeUIRuntime

        runtime = GenerativeUIRuntime()
        d = runtime.render_surface_dict()
        assert set(d.keys()) == {"surface_type", "title", "layout_hints", "fallback_surface"}


class TestGenerativeUIRuntimeSingleton:
    def test_get_generative_ui_runtime_returns_same_instance(self):
        from core.generative_ui.runtime import get_generative_ui_runtime

        a = get_generative_ui_runtime()
        b = get_generative_ui_runtime()
        assert a is b

    def test_singleton_is_generative_ui_runtime_instance(self):
        from core.generative_ui.runtime import GenerativeUIRuntime, get_generative_ui_runtime

        assert isinstance(get_generative_ui_runtime(), GenerativeUIRuntime)
