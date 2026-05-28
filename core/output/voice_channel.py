"""
Galaxy — Voice Channel (Real TTS via Edge-TTS)
===============================================

Replaces the previous stub with a real TTS back-end powered by edge-tts
(Microsoft Edge TTS service, free, no API key required).

The channel checks whether the
:class:`~core.schemas.interaction_envelope.OutputPlan` requests voice
(``voice == True``), synthesises the response text, and returns a plan
dict that includes the path to the generated audio file.

Dependencies
------------
pip install edge-tts

No external API key required.  Safe to import in any context; TTS is
only initialised when ``build()`` is called with ``enabled=True``.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.VoiceChannel")

# Default voice parameters — can be overridden via persona_state hints
_DEFAULT_VOICE_ID = "zh-CN-XiaoxiaoNeural"
_DEFAULT_SPEED = 1.0
_DEFAULT_PITCH = 1.0

# Interaction modes that enable voice by default
_VOICE_ENABLED_MODES = frozenset(
    {"field_assistant", "ambient_companion"}
)

# Mapping of mood hints to TTS voices
_MOOD_VOICE_MAP: Dict[str, str] = {
    "calm": "zh-CN-XiaoxiaoNeural",
    "serious": "zh-CN-XiaohanNeural",
    "cheerful": "zh-CN-YunxiNeural",
    "professional": "zh-CN-YunjianNeural",
    "childlike": "zh-CN-XiaoyiNeural",
}


class VoiceChannel:
    """Voice output channel using Edge TTS.

    The channel checks whether the :class:`~core.schemas.interaction_envelope.OutputPlan`
    requests voice (``voice == True``), synthesises the response text using
    edge-tts, and returns a plan dict with the audio file path.
    """

    def __init__(self) -> None:
        self._tts_engine: Optional[Any] = None

    def _get_tts_engine(self) -> Any:
        """Lazy-initialise the Edge TTS engine."""
        if self._tts_engine is None:
            try:
                from core.tts import EdgeTTSEngine
                self._tts_engine = EdgeTTSEngine()
            except ImportError as exc:
                logger.warning("Edge TTS not available: %s", exc)
                raise
        return self._tts_engine

    async def build(
        self,
        response_text: str,
        enabled: bool = False,
        mode: str = "chat",
        persona_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a voice-channel plan with real TTS synthesis.

        Args:
            response_text: Text to be synthesised.
            enabled:       Whether voice output is requested.
            mode:          Active interaction mode string.
            persona_state: Optional persona state dict; used to derive voice
                           mood hints and select voice.

        Returns:
            A JSON-serialisable dict with keys:

            * ``enabled`` — whether TTS was triggered.
            * ``tts_plan`` — nested dict of TTS parameters (only present when
              *enabled* is ``True``).
            * ``audio_path`` — path to the generated MP3 file (only present
              when synthesis succeeded).
            * ``note`` — human-readable status message.
        """
        if not enabled:
            return {
                "enabled": False,
                "tts_plan": None,
                "audio_path": None,
                "note": "voice not requested for this interaction mode",
            }

        # Derive mood hint and voice from persona state
        mood: str = "calm"
        voice: str = _DEFAULT_VOICE_ID
        if persona_state and isinstance(persona_state, dict):
            mood = persona_state.get("mood", "calm")
            voice = persona_state.get("voice", _MOOD_VOICE_MAP.get(mood, _DEFAULT_VOICE_ID))

        tts_plan: Dict[str, Any] = {
            "engine": "edge-tts",
            "text": response_text,
            "voice_id": voice,
            "speed": _DEFAULT_SPEED,
            "pitch": _DEFAULT_PITCH,
            "mood_hint": mood,
        }

        # Attempt real TTS synthesis
        try:
            tts_engine = self._get_tts_engine()
            audio_path = await tts_engine.synthesize(
                text=response_text,
                voice=voice,
            )
            tts_plan["audio_path"] = audio_path

            return {
                "enabled": True,
                "tts_plan": tts_plan,
                "audio_path": audio_path,
                "note": "TTS synthesis completed via edge-tts",
            }

        except ImportError:
            logger.warning("edge-tts not installed; falling back to plan-only mode")
            return {
                "enabled": True,
                "tts_plan": tts_plan,
                "audio_path": None,
                "note": "TTS plan ready — edge-tts not installed (pip install edge-tts)",
            }

        except Exception as exc:
            logger.warning("TTS synthesis failed: %s", exc)
            return {
                "enabled": True,
                "tts_plan": tts_plan,
                "audio_path": None,
                "note": f"TTS plan ready — synthesis failed: {exc}",
            }

    async def synthesize_and_play(
        self,
        response_text: str,
        persona_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Synthesize and immediately play the response.

        Args:
            response_text: Text to synthesise and play.
            persona_state: Optional persona state for voice selection.

        Returns:
            Result dict with ``audio_path`` and status.
        """
        # Derive voice from persona state
        voice: str = _DEFAULT_VOICE_ID
        if persona_state and isinstance(persona_state, dict):
            mood = persona_state.get("mood", "calm")
            voice = persona_state.get("voice", _MOOD_VOICE_MAP.get(mood, _DEFAULT_VOICE_ID))

        try:
            tts_engine = self._get_tts_engine()
            audio_path = await tts_engine.synthesize_and_play(
                text=response_text,
                voice=voice,
            )
            return {
                "played": True,
                "audio_path": audio_path,
                "text": response_text,
                "note": "TTS synthesis and playback completed",
            }

        except Exception as exc:
            logger.warning("TTS playback failed: %s", exc)
            return {
                "played": False,
                "audio_path": None,
                "text": response_text,
                "note": f"TTS playback failed: {exc}",
            }

    @staticmethod
    def is_voice_enabled_for_mode(mode: str) -> bool:
        """Check if voice is enabled by default for a given interaction mode.

        Args:
            mode: Interaction mode string.

        Returns:
            True if voice is enabled by default.
        """
        return mode in _VOICE_ENABLED_MODES


__all__ = ["VoiceChannel"]
