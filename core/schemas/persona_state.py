"""
Galaxy — PersonaState schema (PR-3)
=====================================

Defines the canonical :class:`PersonaState` dataclass used by the Persona /
Spirit Engine layer.  All fields are plain Python types so the schema is
importable without any heavy runtime dependencies.

Schema version: 1
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# PersonaState
# ---------------------------------------------------------------------------

@dataclass
class PersonaState:
    """Mutable snapshot of the agent's current affective/motivational state.

    All numeric fields are floats in ``[0.0, 1.0]`` unless noted otherwise.

    Attributes:
        session_id:       Session this state belongs to.  ``"__global__"`` for
                          the session-independent baseline.
        mood:             Qualitative mood label, e.g. ``"calm"``, ``"focused"``,
                          ``"curious"``, ``"concerned"``.
        energy:           Processing / engagement energy level.
        focus:            Task focus sharpness.
        curiosity:        Drive to explore / ask follow-ups.
        urgency:          Perceived time-pressure or criticality.
        trust_level:      Accumulated trust signal from the session history.
        expression_mode:  Surface style hint for UI/voice layers, e.g.
                          ``"quiet_luminous"``, ``"direct"``, ``"warm"``.
        updated_at:       Wall-clock timestamp of the last mutation.
    """

    session_id: str = "__global__"
    mood: str = "calm"
    energy: float = 0.6
    focus: float = 0.7
    curiosity: float = 0.5
    urgency: float = 0.1
    trust_level: float = 0.5
    expression_mode: str = "quiet_luminous"
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "session_id": self.session_id,
            "mood": self.mood,
            "energy": round(self.energy, 4),
            "focus": round(self.focus, 4),
            "curiosity": round(self.curiosity, 4),
            "urgency": round(self.urgency, 4),
            "trust_level": round(self.trust_level, 4),
            "expression_mode": self.expression_mode,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def default_baseline(cls, session_id: str = "__global__") -> "PersonaState":
        """Return a fresh calm/neutral baseline state."""
        return cls(session_id=session_id)


# ---------------------------------------------------------------------------
# Numeric-field clipping helper
# ---------------------------------------------------------------------------

def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* into [lo, hi]."""
    return max(lo, min(hi, value))


__all__ = ["PersonaState", "_clip"]
