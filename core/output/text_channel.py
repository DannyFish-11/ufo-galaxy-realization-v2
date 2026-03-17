"""
Galaxy — Text Channel (PR-6)
=============================

Produces the **text** segment of the multi-channel output plan.

The text channel is always enabled; it is the universal fallback for every
interaction mode.  The channel decides on formatting hints (``"markdown"`` vs
``"plain"``) based on the active ``ui_surface``.

No external dependencies.  Safe to import in any context.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Surfaces that render markdown properly
_MARKDOWN_SURFACES = frozenset(
    {
        "infinite_canvas",
        "deep_thinking_canvas",
        "chat_panel",
        "control_console",
    }
)


class TextChannel:
    """Builds the text-output plan from a response string and rendering hints.

    Attributes:
        None (stateless; all logic is in :meth:`build`).
    """

    def build(
        self,
        response_text: str,
        ui_surface: str = "chat_panel",
        streaming: bool = False,
        persona_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a text-channel plan dict.

        Args:
            response_text: The text content to be rendered.
            ui_surface:    The active UI surface identifier (e.g.
                           ``"chat_panel"``, ``"infinite_canvas"``).
            streaming:     Whether the text will be streamed token-by-token.
            persona_state: Optional serialised
                           :class:`~core.schemas.persona_state.PersonaState`
                           dict; used to apply lightweight expression hints
                           (e.g. prefix/suffix annotations).

        Returns:
            A JSON-serialisable dict with keys:

            * ``enabled`` — always ``True``.
            * ``content`` — the response text.
            * ``format`` — ``"markdown"`` or ``"plain"``.
            * ``streaming`` — mirrors the *streaming* argument.
            * ``expression_hint`` — persona expression label or ``None``.
        """
        fmt = "markdown" if ui_surface in _MARKDOWN_SURFACES else "plain"
        expression_hint: Optional[str] = None
        if persona_state and isinstance(persona_state, dict):
            expression_hint = persona_state.get("expression_mode")

        return {
            "enabled": True,
            "content": response_text,
            "format": fmt,
            "streaming": streaming,
            "expression_hint": expression_hint,
        }


__all__ = ["TextChannel"]
