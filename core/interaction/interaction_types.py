"""
Galaxy — Interaction Mode Types (PR 2)
=======================================

Defines:

* :class:`InteractionMode` — canonical enum of all supported interaction modes.
* :class:`InteractionDecision` — output of :class:`~core.interaction.scene_interpreter.SceneInterpreter`.

These types are intentionally dependency-free (stdlib only) so that they can be
imported early in the boot sequence without triggering heavy module loads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class InteractionMode(str, Enum):
    """Canonical set of interaction modes understood by the Galaxy runtime.

    The string value equals the enum name in lower-case so that JSON
    serialisation is human-readable and round-trip stable.
    """

    #: Default conversational mode — no special UI requirements.
    CHAT = "chat"

    #: Deep analytical / philosophical discussion requiring expanded reasoning.
    DEEP_THINKING = "deep_thinking"

    #: Task / script / command execution — control-console UI hints.
    CONTROL_CONSOLE = "control_console"

    #: On-site assistance guided by visual context (camera / screen share).
    FIELD_ASSISTANT = "field_assistant"

    #: Low-engagement background presence — ambient companion mode.
    AMBIENT_COMPANION = "ambient_companion"

    #: High-trust bridge between user intent and system execution layer.
    EXECUTION_BRIDGE = "execution_bridge"


@dataclass
class InteractionDecision:
    """Output of :class:`~core.interaction.scene_interpreter.SceneInterpreter`.

    All fields have sensible defaults so that callers can construct a minimal
    decision without providing every hint field.

    Attributes:
        mode:              Selected :class:`InteractionMode`.
        relationship_mode: Human-readable label for the current user-AI
                           relationship (e.g. ``"scholar_companion"``).
        ui_surface:        Hint for the UI renderer (e.g. ``"chat_panel"``).
        voice_mode:        Hint for the TTS / voice channel
                           (e.g. ``"off"``, ``"ambient"``, ``"active"``).
        avatar_mode:       Hint for the avatar / persona layer
                           (e.g. ``"idle"``, ``"focused"``, ``"guiding"``).
        confidence:        Float in ``[0.0, 1.0]`` indicating interpreter
                           confidence in the selected mode.
        rationale:         Short human-readable string explaining the decision.
    """

    mode: InteractionMode = InteractionMode.CHAT
    relationship_mode: str = "user_companion"
    ui_surface: str = "chat_panel"
    voice_mode: str = "off"
    avatar_mode: str = "idle"
    confidence: float = 1.0
    rationale: str = ""

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "mode": self.mode.value,
            "relationship_mode": self.relationship_mode,
            "ui_surface": self.ui_surface,
            "voice_mode": self.voice_mode,
            "avatar_mode": self.avatar_mode,
            "confidence": self.confidence,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionDecision":
        """Reconstruct from a plain dict (e.g. deserialised from JSON)."""
        return cls(
            mode=InteractionMode(data.get("mode", InteractionMode.CHAT.value)),
            relationship_mode=data.get("relationship_mode", "user_companion"),
            ui_surface=data.get("ui_surface", "chat_panel"),
            voice_mode=data.get("voice_mode", "off"),
            avatar_mode=data.get("avatar_mode", "idle"),
            confidence=float(data.get("confidence", 1.0)),
            rationale=data.get("rationale", ""),
        )


__all__ = ["InteractionMode", "InteractionDecision"]
