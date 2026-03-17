"""
Galaxy — Generative UI Widget Schema (PR-5)
===========================================

Defines:

* :class:`SurfaceType` — canonical enum of all supported UI surface types.
* :class:`SurfaceSpec` — lightweight descriptor returned by the runtime to
  clients, carrying the surface type and a minimal set of layout hints.

No external dependencies — stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class SurfaceType(str, Enum):
    """Canonical set of UI surface types understood by Galaxy clients.

    The string value equals the enum name in lower-case so that JSON
    serialisation is human-readable and round-trip stable.
    """

    #: Standard conversational chat panel — the universal fallback.
    CHAT_PANEL = "chat_panel"

    #: Expanded reasoning canvas for deep analytical discussions.
    DEEP_THINKING_CANVAS = "deep_thinking_canvas"

    #: Dashboard-style control surface for task/script execution.
    CONTROL_CONSOLE = "control_console"

    #: Overlay stub for on-site field assistance guided by visual context.
    FIELD_ASSISTANT_OVERLAY_STUB = "field_assistant_overlay_stub"

    #: Ambient low-engagement companion surface.
    AMBIENT_COMPANION = "ambient_companion"


@dataclass
class SurfaceSpec:
    """Lightweight descriptor for a rendered UI surface.

    Attributes:
        surface_type:   The :class:`SurfaceType` selected for the current
                        interaction.
        title:          Human-readable label for the surface (used as a
                        window/panel title hint).
        layout_hints:   Optional dict of layout parameters forwarded to the
                        client renderer.  All keys are advisory — clients may
                        ignore hints they do not understand.
        fallback_surface: The :class:`SurfaceType` to use if the requested
                        surface cannot be rendered by the client.
    """

    surface_type: SurfaceType = SurfaceType.CHAT_PANEL
    title: str = "Galaxy"
    layout_hints: Dict[str, Any] = field(default_factory=dict)
    fallback_surface: SurfaceType = SurfaceType.CHAT_PANEL

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "surface_type": self.surface_type.value,
            "title": self.title,
            "layout_hints": self.layout_hints,
            "fallback_surface": self.fallback_surface.value,
        }


# ---------------------------------------------------------------------------
# Surface metadata — title and layout_hints defaults per surface type
# ---------------------------------------------------------------------------

_SURFACE_META: Dict[SurfaceType, Dict[str, Any]] = {
    SurfaceType.CHAT_PANEL: {
        "title": "Galaxy — Chat",
        "layout_hints": {
            "input_position": "bottom",
            "message_density": "normal",
            "show_avatar": False,
        },
    },
    SurfaceType.DEEP_THINKING_CANVAS: {
        "title": "Galaxy — Deep Thinking",
        "layout_hints": {
            "input_position": "bottom",
            "message_density": "sparse",
            "show_avatar": True,
            "canvas_mode": "infinite_scroll",
        },
    },
    SurfaceType.CONTROL_CONSOLE: {
        "title": "Galaxy — Control Console",
        "layout_hints": {
            "input_position": "top",
            "show_task_progress": True,
            "show_log_panel": True,
            "show_avatar": False,
        },
    },
    SurfaceType.FIELD_ASSISTANT_OVERLAY_STUB: {
        "title": "Galaxy — Field Assistant",
        "layout_hints": {
            "overlay_mode": True,
            "show_camera_hint": True,
            "voice_active": True,
            "show_avatar": True,
        },
    },
    SurfaceType.AMBIENT_COMPANION: {
        "title": "Galaxy — Companion",
        "layout_hints": {
            "minimised": True,
            "animation_density": "low",
            "show_avatar": True,
            "voice_active": True,
        },
    },
}


def get_surface_meta(surface_type: SurfaceType) -> Dict[str, Any]:
    """Return the default title and layout_hints for *surface_type*."""
    return _SURFACE_META.get(surface_type, _SURFACE_META[SurfaceType.CHAT_PANEL])


__all__ = ["SurfaceType", "SurfaceSpec", "get_surface_meta"]
