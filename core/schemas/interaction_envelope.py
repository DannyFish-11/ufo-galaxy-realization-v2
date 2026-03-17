"""
Galaxy — InteractionEnvelope schema (PR-4)
==========================================

Defines the canonical :class:`InteractionEnvelope` dataclass that unifies:

* **interaction mode** — selected by :class:`~core.interaction.scene_interpreter.SceneInterpreter`
* **persona state** — current affective snapshot from the Persona/Spirit Engine
* **multimodal context** — fused perception data produced by the MultimodalBus
* **output plan** — per-channel rendering instructions for UI/voice/avatar layers

All fields use plain Python types so the schema is importable without any
external dependencies.  The companion :class:`OutputPlan` captures default
rendering hints derived from the interaction mode.

Schema version: 1
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# OutputPlan
# ---------------------------------------------------------------------------

@dataclass
class OutputPlan:
    """Per-channel rendering plan derived from the selected interaction mode.

    All boolean flags default to ``False`` except ``text``, which is always
    ``True`` (text is the universal fallback channel).

    Attributes:
        text:       Render a text response.  Always ``True``.
        voice:      Emit TTS audio output.
        avatar:     Activate avatar / persona visual.
        overlay:    Show an on-screen annotation overlay (field-assistant mode).
        ui_surface: Hint for the UI renderer, e.g. ``"chat_panel"``,
                    ``"infinite_canvas"``, ``"control_console"``.
    """

    text: bool = True
    voice: bool = False
    avatar: bool = False
    overlay: bool = False
    ui_surface: str = "chat_panel"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "text": self.text,
            "voice": self.voice,
            "avatar": self.avatar,
            "overlay": self.overlay,
            "ui_surface": self.ui_surface,
        }

    @classmethod
    def text_only(cls) -> "OutputPlan":
        """Return a minimal text-only fallback plan."""
        return cls()

    @classmethod
    def from_mode(cls, mode: str) -> "OutputPlan":
        """Derive a sensible default :class:`OutputPlan` for *mode*.

        Args:
            mode: Interaction mode string (see
                  :class:`~core.interaction.interaction_types.InteractionMode`).

        Returns:
            An :class:`OutputPlan` with per-channel flags tuned for the mode.
        """
        _MODE_DEFAULTS: Dict[str, Dict[str, Any]] = {
            "chat": {
                "text": True, "voice": False, "avatar": False,
                "overlay": False, "ui_surface": "chat_panel",
            },
            "deep_thinking": {
                "text": True, "voice": False, "avatar": True,
                "overlay": False, "ui_surface": "infinite_canvas",
            },
            "control_console": {
                "text": True, "voice": False, "avatar": False,
                "overlay": False, "ui_surface": "control_console",
            },
            "field_assistant": {
                "text": True, "voice": True, "avatar": True,
                "overlay": True, "ui_surface": "field_overlay",
            },
            "ambient_companion": {
                "text": True, "voice": True, "avatar": True,
                "overlay": False, "ui_surface": "ambient",
            },
            "execution_bridge": {
                "text": True, "voice": False, "avatar": False,
                "overlay": False, "ui_surface": "control_console",
            },
        }
        defaults = _MODE_DEFAULTS.get(mode, _MODE_DEFAULTS["chat"])
        return cls(**defaults)


# ---------------------------------------------------------------------------
# InteractionEnvelope
# ---------------------------------------------------------------------------

@dataclass
class InteractionEnvelope:
    """Unified interaction context envelope produced once per request.

    The envelope is built by :class:`~core.interaction.interaction_builder.InteractionBuilder`
    after the multimodal bus, scene interpreter, and persona engine have all
    run.  It is attached to the response payload under ``interaction_envelope``
    so that clients (Windows / Android / Dashboard) can adapt their rendering
    accordingly.

    Attributes:
        interaction_id:    Unique identifier for this envelope (``ix_<hex>``).
        trace_id:          End-to-end trace identifier threading through all
                           internal hops (matches the ``trace_id`` in metadata).
        session_id:        Session the envelope belongs to.
        mode:              Selected interaction mode string (e.g. ``"chat"``).
        relationship_mode: Human-readable relationship label from the scene
                           interpreter (e.g. ``"scholar_companion"``).
        persona_state:     Serialised :class:`~core.schemas.persona_state.PersonaState`
                           dict (from ``PersonaState.to_dict()``).
        multimodal_context: Fused multimodal context dict from the
                            MultimodalBus, or ``None`` for text-only requests.
        output_plan:       :class:`OutputPlan` describing per-channel rendering
                           flags.
        created_at:        UTC timestamp when the envelope was constructed.
    """

    interaction_id: str = field(
        default_factory=lambda: f"ix_{uuid.uuid4().hex[:16]}"
    )
    trace_id: Optional[str] = None
    session_id: str = "__global__"
    mode: str = "chat"
    relationship_mode: str = "user_companion"
    persona_state: Optional[Dict[str, Any]] = None
    multimodal_context: Optional[Dict[str, Any]] = None
    output_plan: OutputPlan = field(default_factory=OutputPlan)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "interaction_id": self.interaction_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "mode": self.mode,
            "relationship_mode": self.relationship_mode,
            "persona_state": self.persona_state,
            "multimodal_context": self.multimodal_context,
            "output_plan": self.output_plan.to_dict(),
            "created_at": self.created_at.isoformat(),
        }

    # Alias for pydantic-style callers
    def model_dump(self) -> Dict[str, Any]:
        """Alias of :meth:`to_dict` for pydantic-style compatibility."""
        return self.to_dict()


__all__ = ["OutputPlan", "InteractionEnvelope"]
