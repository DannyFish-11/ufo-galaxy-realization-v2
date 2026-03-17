"""
Galaxy — Avatar Channel stub (PR-6)
=====================================

Returns a **structured avatar animation plan** without performing any actual
3-D rendering.  A future PR will wire this to a real avatar runtime; clients
consuming the plan dict do not need to change.

No external dependencies.  Safe to import in any context.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Mapping from persona mood to avatar expression
_MOOD_TO_EXPRESSION: Dict[str, str] = {
    "calm": "neutral",
    "curious": "curious",
    "focused": "concentrated",
    "excited": "enthusiastic",
    "tired": "subdued",
    "concerned": "attentive",
    "joyful": "happy",
}

# Mapping from interaction mode to avatar animation state
_MODE_TO_ANIMATION: Dict[str, str] = {
    "chat": "idle",
    "deep_thinking": "thinking",
    "control_console": "monitoring",
    "field_assistant": "guiding",
    "ambient_companion": "ambient",
    "execution_bridge": "processing",
}


class AvatarChannel:
    """Builds the avatar-output plan (stub).

    Derives an ``expression`` and ``animation`` state from the active persona
    mood and interaction mode, producing a plan dict that a future avatar
    renderer can consume directly.
    """

    def build(
        self,
        enabled: bool = False,
        mode: str = "chat",
        persona_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return an avatar-channel plan dict.

        Args:
            enabled:       Whether avatar output is requested (mirrors
                           ``OutputPlan.avatar``).
            mode:          Active interaction mode string.
            persona_state: Optional persona state dict; used to derive
                           expression hints from mood and energy.

        Returns:
            A JSON-serialisable dict with keys:

            * ``enabled`` — whether avatar should be rendered.
            * ``avatar_plan`` — nested dict of animation parameters (only
              present when *enabled* is ``True``).
            * ``note`` — human-readable stub notice.
        """
        if not enabled:
            return {
                "enabled": False,
                "avatar_plan": None,
                "note": "stub: avatar not requested for this interaction mode",
            }

        # Derive expression from persona mood
        expression = "neutral"
        energy: float = 0.65
        if persona_state and isinstance(persona_state, dict):
            mood = persona_state.get("mood", "calm")
            expression = _MOOD_TO_EXPRESSION.get(mood, "neutral")
            energy = float(persona_state.get("energy", 0.65))

        animation = _MODE_TO_ANIMATION.get(mode, "idle")

        avatar_plan: Dict[str, Any] = {
            "expression": expression,
            "animation": animation,
            "pose": "default",
            "energy_level": energy,
            "blink": True,
        }

        return {
            "enabled": True,
            "avatar_plan": avatar_plan,
            "note": "stub: avatar plan ready — 3D rendering not yet implemented",
        }


__all__ = ["AvatarChannel"]
