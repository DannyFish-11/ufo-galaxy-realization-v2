"""
Galaxy — Generative UI Surface Selector (PR-5)
===============================================

Implements :class:`SurfaceSelector`, which maps an
:class:`~core.schemas.interaction_envelope.InteractionEnvelope` (or a plain
dict with a ``mode`` key) to a :class:`~core.generative_ui.widget_schema.SurfaceSpec`.

The mapping rules are::

    CHAT              → chat_panel
    DEEP_THINKING     → deep_thinking_canvas
    CONTROL_CONSOLE   → control_console
    FIELD_ASSISTANT   → field_assistant_overlay_stub
    AMBIENT_COMPANION → ambient_companion
    EXECUTION_BRIDGE  → control_console   (shares the console surface)
    <unknown>         → chat_panel        (safe fallback)

No external dependencies — stdlib only.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Union

from core.generative_ui.widget_schema import SurfaceSpec, SurfaceType, get_surface_meta

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mode → SurfaceType mapping table
# ---------------------------------------------------------------------------

_MODE_TO_SURFACE: Dict[str, SurfaceType] = {
    "chat": SurfaceType.CHAT_PANEL,
    "deep_thinking": SurfaceType.DEEP_THINKING_CANVAS,
    "control_console": SurfaceType.CONTROL_CONSOLE,
    "field_assistant": SurfaceType.FIELD_ASSISTANT_OVERLAY_STUB,
    "ambient_companion": SurfaceType.AMBIENT_COMPANION,
    # execution_bridge shares the control console surface
    "execution_bridge": SurfaceType.CONTROL_CONSOLE,
}


class SurfaceSelector:
    """Maps an interaction mode (or envelope) to a concrete :class:`SurfaceSpec`.

    Usage::

        selector = SurfaceSelector()
        spec = selector.select_surface(interaction_envelope)
        print(spec.surface_type)   # e.g. SurfaceType.DEEP_THINKING_CANVAS

    The selector is stateless and thread-safe — a single instance can be
    shared across the whole process.
    """

    def select_surface(
        self,
        interaction_envelope: Union[Any, Dict[str, Any], None] = None,
        *,
        mode: str = "chat",
    ) -> SurfaceSpec:
        """Return the :class:`SurfaceSpec` for the given *interaction_envelope*.

        Args:
            interaction_envelope: An
                :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
                instance, a plain dict with a ``mode`` key, or ``None``.
                When ``None`` or missing the ``mode`` key the selector falls
                back to *mode*.
            mode: Fallback mode string used when *interaction_envelope* is
                ``None`` or does not carry a mode (default ``"chat"``).

        Returns:
            A :class:`SurfaceSpec` populated with the surface type, title, and
            layout hints derived from the resolved mode.
        """
        resolved_mode = self._resolve_mode(interaction_envelope, fallback=mode)
        surface_type = _MODE_TO_SURFACE.get(resolved_mode)
        if surface_type is None:
            logger.debug(
                "SurfaceSelector: unknown mode %r, falling back to chat_panel", resolved_mode
            )
            surface_type = SurfaceType.CHAT_PANEL
        meta = get_surface_meta(surface_type)
        return SurfaceSpec(
            surface_type=surface_type,
            title=meta["title"],
            layout_hints=dict(meta["layout_hints"]),
            fallback_surface=SurfaceType.CHAT_PANEL,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_mode(
        envelope: Union[Any, Dict[str, Any], None],
        fallback: str = "chat",
    ) -> str:
        """Extract the mode string from *envelope*.

        Supports:
        * ``InteractionEnvelope`` dataclass instances (read ``.mode``).
        * Plain dicts with a ``"mode"`` key.
        * ``None`` — returns *fallback*.
        """
        if envelope is None:
            return fallback

        # Dict-like (e.g. already serialised via to_dict())
        if isinstance(envelope, dict):
            return str(envelope.get("mode", fallback)).lower()

        # Dataclass / object with a .mode attribute
        try:
            raw = envelope.mode
            # InteractionMode enum → .value gives the string
            return str(getattr(raw, "value", raw)).lower()
        except Exception:
            return fallback


__all__ = ["SurfaceSelector"]
