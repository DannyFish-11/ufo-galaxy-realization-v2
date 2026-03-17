"""
Galaxy — Mode Selector (PR 2)
==============================

:class:`ModeSelector` encapsulates the **per-mode hint tables** and the
default field values for each :class:`~core.interaction.interaction_types.InteractionMode`.

It is deliberately separated from :class:`~core.interaction.scene_interpreter.SceneInterpreter`
so that callers can override individual hint fields without changing the
rule-matching logic.

Usage::

    from core.interaction.mode_selector import ModeSelector
    from core.interaction.interaction_types import InteractionMode

    selector = ModeSelector()
    decision = selector.build_decision(
        mode=InteractionMode.CONTROL_CONSOLE,
        confidence=0.9,
        rationale="Command keywords detected",
    )
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.interaction.interaction_types import InteractionDecision, InteractionMode

# ---------------------------------------------------------------------------
# Per-mode default hint tables
# ---------------------------------------------------------------------------

_MODE_DEFAULTS: Dict[InteractionMode, Dict[str, str]] = {
    InteractionMode.CHAT: {
        "relationship_mode": "user_companion",
        "ui_surface": "chat_panel",
        "voice_mode": "off",
        "avatar_mode": "idle",
    },
    InteractionMode.DEEP_THINKING: {
        "relationship_mode": "scholar_companion",
        "ui_surface": "infinite_canvas",
        "voice_mode": "ambient",
        "avatar_mode": "focused",
    },
    InteractionMode.CONTROL_CONSOLE: {
        "relationship_mode": "commander_executor",
        "ui_surface": "control_console",
        "voice_mode": "off",
        "avatar_mode": "standby",
    },
    InteractionMode.FIELD_ASSISTANT: {
        "relationship_mode": "field_guide",
        "ui_surface": "overlay_panel",
        "voice_mode": "active",
        "avatar_mode": "guiding",
    },
    InteractionMode.AMBIENT_COMPANION: {
        "relationship_mode": "ambient_presence",
        "ui_surface": "minimal_widget",
        "voice_mode": "ambient",
        "avatar_mode": "background",
    },
    InteractionMode.EXECUTION_BRIDGE: {
        "relationship_mode": "execution_bridge",
        "ui_surface": "terminal_panel",
        "voice_mode": "off",
        "avatar_mode": "executing",
    },
}


class ModeSelector:
    """Builds :class:`~core.interaction.interaction_types.InteractionDecision` objects
    using per-mode default hints.

    The selector is stateless and safe to share across requests.
    """

    def build_decision(
        self,
        mode: InteractionMode,
        confidence: float = 1.0,
        rationale: str = "",
        overrides: Optional[Dict[str, Any]] = None,
    ) -> InteractionDecision:
        """Construct an :class:`InteractionDecision` for the given *mode*.

        Args:
            mode:       The resolved :class:`InteractionMode`.
            confidence: Confidence score in ``[0.0, 1.0]``.
            rationale:  Short explanation of why this mode was selected.
            overrides:  Optional dict of field overrides applied on top of
                        the mode defaults (keys match ``InteractionDecision``
                        field names except ``mode``).

        Returns:
            A fully-populated :class:`InteractionDecision`.
        """
        defaults = _MODE_DEFAULTS.get(mode, _MODE_DEFAULTS[InteractionMode.CHAT])
        merged: Dict[str, Any] = {**defaults, **(overrides or {})}

        return InteractionDecision(
            mode=mode,
            relationship_mode=merged.get("relationship_mode", "user_companion"),
            ui_surface=merged.get("ui_surface", "chat_panel"),
            voice_mode=merged.get("voice_mode", "off"),
            avatar_mode=merged.get("avatar_mode", "idle"),
            confidence=max(0.0, min(1.0, confidence)),
            rationale=rationale,
        )


__all__ = ["ModeSelector"]
