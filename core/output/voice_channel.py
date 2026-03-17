"""
Galaxy — Voice Channel stub (PR-6)
====================================

Returns a **structured TTS plan** without performing any actual synthesis.
A future PR will replace this stub with a real TTS back-end; callers that
consume the plan dict do not need to change.

No external dependencies.  Safe to import in any context.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Default voice parameters — can be overridden via persona_state hints
_DEFAULT_VOICE_ID = "default"
_DEFAULT_SPEED = 1.0
_DEFAULT_PITCH = 1.0

# Interaction modes that enable voice by default
_VOICE_ENABLED_MODES = frozenset(
    {"field_assistant", "ambient_companion"}
)


class VoiceChannel:
    """Builds the voice-output plan (stub).

    The channel checks whether the :class:`~core.schemas.interaction_envelope.OutputPlan`
    requests voice (``voice == True``) and assembles a TTS parameter dict for
    the client to consume or forward to an external TTS service.

    No audio is synthesised here.
    """

    def build(
        self,
        response_text: str,
        enabled: bool = False,
        mode: str = "chat",
        persona_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return a voice-channel plan dict.

        Args:
            response_text: Text to be synthesised when the plan is executed.
            enabled:       Whether voice output is requested (mirrors
                           ``OutputPlan.voice``).
            mode:          Active interaction mode string.
            persona_state: Optional persona state dict; used to derive voice
                           mood hints.

        Returns:
            A JSON-serialisable dict with keys:

            * ``enabled`` — whether TTS should be triggered.
            * ``tts_plan`` — nested dict of TTS parameters (only present when
              *enabled* is ``True``).
            * ``note`` — human-readable stub notice.
        """
        if not enabled:
            return {
                "enabled": False,
                "tts_plan": None,
                "note": "stub: voice not requested for this interaction mode",
            }

        # Derive mood hint from persona state
        mood: str = "calm"
        if persona_state and isinstance(persona_state, dict):
            mood = persona_state.get("mood", "calm")

        tts_plan: Dict[str, Any] = {
            "engine": "stub",
            "text": response_text,
            "voice_id": _DEFAULT_VOICE_ID,
            "speed": _DEFAULT_SPEED,
            "pitch": _DEFAULT_PITCH,
            "mood_hint": mood,
        }

        return {
            "enabled": True,
            "tts_plan": tts_plan,
            "note": "stub: TTS plan ready — audio synthesis not yet implemented",
        }


__all__ = ["VoiceChannel"]
