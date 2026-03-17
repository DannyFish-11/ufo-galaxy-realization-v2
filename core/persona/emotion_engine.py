"""
Galaxy — EmotionEngine (PR-3)
================================

:class:`EmotionEngine` applies rule-based updates to a :class:`PersonaState`
given the current interaction context.  No model calls are made; all decisions
are deterministic keyword / threshold checks.

Usage::

    from core.persona.emotion_engine import EmotionEngine
    engine = EmotionEngine()

    delta = engine.compute_delta(
        message="谢谢你帮我解决了这个问题",
        interaction_mode="chat",
        task_success=True,
    )
    # delta is a dict of field → float/str increments
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from core.schemas.persona_state import PersonaState, _clip
from core.persona.persona_rules import (
    GRATITUDE_KEYWORDS,
    FRUSTRATION_KEYWORDS,
    CURIOSITY_KEYWORDS,
    URGENCY_KEYWORDS,
    TRUST_GRATITUDE_DELTA,
    FRUSTRATION_URGENCY_DELTA,
    FRUSTRATION_ENERGY_DELTA,
    CURIOSITY_DELTA,
    URGENCY_KEYWORD_DELTA,
    URGENCY_ENERGY_DELTA,
    LONG_MSG_FOCUS_DELTA,
    LONG_MSG_THRESHOLD,
    SHORT_MSG_ENERGY_DELTA,
    SHORT_MSG_THRESHOLD,
    TASK_SUCCESS_TRUST_DELTA,
    TASK_SUCCESS_ENERGY_DELTA,
    TASK_FAILURE_URGENCY_DELTA,
    TASK_FAILURE_ENERGY_DELTA,
    CONTROL_CONSOLE_FOCUS_DELTA,
    CONTROL_CONSOLE_URGENCY_DELTA,
    AMBIENT_ENERGY_DELTA,
    derive_mood,
    derive_expression_mode,
)

logger = logging.getLogger(__name__)

# Interaction mode string constants mirroring InteractionMode enum values
_MODE_CONTROL_CONSOLE = "control_console"
_MODE_AMBIENT_COMPANION = "ambient_companion"


def _contains_any(text: str, keywords: tuple) -> bool:
    """Return True if *text* contains any keyword (case-insensitive substring)."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


class EmotionEngine:
    """Rule-based persona delta calculator.

    Each call to :meth:`compute_delta` returns a numeric delta dict that
    :class:`~core.persona.state_store.StateStore` can apply to the stored
    :class:`PersonaState`.

    The engine is stateless — it does not hold any session state itself.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_delta(
        self,
        message: str,
        *,
        interaction_mode: Optional[str] = None,
        task_success: Optional[bool] = None,
        task_result_summary: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compute an incremental state delta for the given context.

        Args:
            message:             Raw user message text.
            interaction_mode:    String value of :class:`InteractionMode`
                                 (e.g. ``"control_console"``).  ``None`` is
                                 treated as ``"chat"``.
            task_success:        ``True`` if the last task succeeded,
                                 ``False`` if it failed, ``None`` if unknown.
            task_result_summary: Optional short summary from the task result
                                 (used for additional keyword heuristics).

        Returns:
            A dict with numeric deltas and optional string overrides.
            Example::

                {
                    "trust_level": 0.1,
                    "urgency": 0.2,
                    "energy": -0.1,
                    "_mood_override": "concerned",
                }

            Keys starting with ``_`` are directive overrides, not numeric
            increments.
        """
        delta: Dict[str, Any] = {}

        # ── 1. Message-level sentiment cues ──────────────────────────
        if message:
            # Gratitude → trust +
            if _contains_any(message, GRATITUDE_KEYWORDS):
                delta["trust_level"] = delta.get("trust_level", 0.0) + TRUST_GRATITUDE_DELTA

            # Frustration → urgency +, energy -
            if _contains_any(message, FRUSTRATION_KEYWORDS):
                delta["urgency"] = delta.get("urgency", 0.0) + FRUSTRATION_URGENCY_DELTA
                delta["energy"] = delta.get("energy", 0.0) + FRUSTRATION_ENERGY_DELTA

            # Curiosity → curiosity +
            if _contains_any(message, CURIOSITY_KEYWORDS):
                delta["curiosity"] = delta.get("curiosity", 0.0) + CURIOSITY_DELTA

            # Urgency keywords → urgency +, energy +
            if _contains_any(message, URGENCY_KEYWORDS):
                delta["urgency"] = delta.get("urgency", 0.0) + URGENCY_KEYWORD_DELTA
                delta["energy"] = delta.get("energy", 0.0) + URGENCY_ENERGY_DELTA

            # Message length heuristics
            msg_len = len(message)
            if msg_len >= LONG_MSG_THRESHOLD:
                delta["focus"] = delta.get("focus", 0.0) + LONG_MSG_FOCUS_DELTA
            elif msg_len <= SHORT_MSG_THRESHOLD:
                delta["energy"] = delta.get("energy", 0.0) + SHORT_MSG_ENERGY_DELTA

        # ── 2. Interaction mode ───────────────────────────────────────
        if interaction_mode == _MODE_CONTROL_CONSOLE:
            delta["focus"] = delta.get("focus", 0.0) + CONTROL_CONSOLE_FOCUS_DELTA
            delta["urgency"] = delta.get("urgency", 0.0) + CONTROL_CONSOLE_URGENCY_DELTA
        elif interaction_mode == _MODE_AMBIENT_COMPANION:
            delta["energy"] = delta.get("energy", 0.0) + AMBIENT_ENERGY_DELTA

        # ── 3. Task outcome ───────────────────────────────────────────
        if task_success is True:
            delta["trust_level"] = delta.get("trust_level", 0.0) + TASK_SUCCESS_TRUST_DELTA
            delta["energy"] = delta.get("energy", 0.0) + TASK_SUCCESS_ENERGY_DELTA
        elif task_success is False:
            delta["urgency"] = delta.get("urgency", 0.0) + TASK_FAILURE_URGENCY_DELTA
            delta["energy"] = delta.get("energy", 0.0) + TASK_FAILURE_ENERGY_DELTA
            # Failed control-console task → mood override to "focused"
            if interaction_mode == _MODE_CONTROL_CONSOLE:
                delta["_mood_override"] = "focused"

        return delta

    def apply_delta(
        self,
        state: PersonaState,
        delta: Dict[str, Any],
    ) -> PersonaState:
        """Apply *delta* to *state* in-place and return the mutated state.

        Numeric fields are clipped to ``[0.0, 1.0]`` after addition.
        ``_mood_override`` is applied after automatic mood derivation so that
        explicit overrides always win.

        Args:
            state: The :class:`PersonaState` to mutate.
            delta: Output of :meth:`compute_delta`.

        Returns:
            The same *state* object (mutated in place) for convenience.
        """
        from datetime import datetime, timezone

        _NUMERIC_FIELDS = {"energy", "focus", "curiosity", "urgency", "trust_level"}

        for key, value in delta.items():
            if key.startswith("_"):
                continue  # directive — handled separately
            if key in _NUMERIC_FIELDS:
                current = getattr(state, key, 0.0)
                setattr(state, key, _clip(current + value))

        # Re-derive mood and expression from updated numerics
        state.mood = derive_mood(
            urgency=state.urgency,
            focus=state.focus,
            energy=state.energy,
            trust_level=state.trust_level,
        )
        state.expression_mode = derive_expression_mode(state.mood, state.energy)

        # Honour explicit mood override (task failure + CONTROL_CONSOLE)
        mood_override = delta.get("_mood_override")
        if mood_override:
            state.mood = mood_override
            state.expression_mode = derive_expression_mode(state.mood, state.energy)

        state.updated_at = datetime.now(tz=timezone.utc)
        return state


__all__ = ["EmotionEngine"]
