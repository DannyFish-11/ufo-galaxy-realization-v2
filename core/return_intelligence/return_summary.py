"""
core/return_intelligence/return_summary.py
==========================================
:class:`ReturnSummary` — the stable, serialisable public summary of the
current return-intelligence state.

This is the **canonical read surface** for downstream projection consumers
(Status Board V2, Manifest Stage, Liminal layer, read-only API endpoints).

Design rules
------------
- Does **not** expose ``receding`` as a public phase.  ``receding`` is an
  internal :class:`~core.continuum.types.ContinuumPhase` and stays private
  to the continuum engine.
- Derives cleanly from :class:`~core.continuum.return_engine.ReturnResult`
  without changing the engine's contracts.
- All fields are ``None``-safe and carry stable defaults so that
  ``ReturnSummary()`` (no args) represents a healthy, non-returning system.
- ``to_dict()`` produces a stable, JSON-serialisable dict (no enum objects).

Usage::

    from core.return_intelligence import ReturnSummary, build_return_summary
    from core.continuum.return_engine import ReturnEngine
    from core.continuum.types import ContinuumState

    engine = ReturnEngine()
    result = engine.evaluate(state, elapsed_ms=elapsed)

    summary = build_return_summary(result)
    print(summary.to_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .return_modes import ReturnMode, MODES_THAT_SUPPRESS_MANIFEST, MODES_THAT_SOFTEN_LIMINAL


@dataclass(frozen=True)
class ReturnSummary:
    """Stable, public-facing summary of the current return-intelligence state.

    Produced from a :class:`~core.continuum.return_engine.ReturnResult` via
    :func:`~core.return_intelligence.return_projection_adapter.build_return_summary`.

    Attributes
    ----------
    is_returning
        ``True`` when the engine recommends any return action other than
        ``hold`` or ``none``.
    return_mode
        The public :class:`~core.return_intelligence.return_modes.ReturnMode`
        currently active.  ``ReturnMode.NONE`` when no return is in progress.
    return_action
        Raw return-action string (``"hold"``, ``"soft_decay"``,
        ``"step_down"``, ``"return_to_formless"``, or ``None``).
    return_trigger
        The trigger that fired (``"finished"``, ``"timeout"``,
        ``"low_value"``, ``"high_uncertainty"``, ``"user_cancel"``), or
        ``None`` when no trigger is active.
    decay_amount
        Suggested presence-intensity reduction for ``soft_decay`` actions.
        ``0.0`` when decay is not applicable.
    reason
        Human-readable explanation from the return engine.  Always non-empty.
    affects_manifest
        ``True`` when the active return mode is expected to suppress or
        degrade the Manifest Stage surface.
    affects_liminal
        ``True`` when the active return mode softens the Liminal spatial
        projection.
    """

    is_returning: bool = False
    return_mode: ReturnMode = ReturnMode.NONE
    return_action: Optional[str] = None
    return_trigger: Optional[str] = None
    decay_amount: float = 0.0
    reason: str = "no return active"
    affects_manifest: bool = False
    affects_liminal: bool = False

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain, JSON-serialisable dict.

        Enum values are converted to their string ``.value``.
        """
        return {
            "is_returning": self.is_returning,
            "return_mode": self.return_mode.value,
            "return_action": self.return_action,
            "return_trigger": self.return_trigger,
            "decay_amount": self.decay_amount,
            "reason": self.reason,
            "affects_manifest": self.affects_manifest,
            "affects_liminal": self.affects_liminal,
        }

    def __repr__(self) -> str:
        return (
            f"<ReturnSummary "
            f"mode={self.return_mode.value} "
            f"trigger={self.return_trigger!r} "
            f"returning={self.is_returning} "
            f"decay={self.decay_amount:.3f}>"
        )


# ---------------------------------------------------------------------------
# Convenience: idle (no return active) summary
# ---------------------------------------------------------------------------

IDLE_RETURN_SUMMARY: ReturnSummary = ReturnSummary(
    is_returning=False,
    return_mode=ReturnMode.NONE,
    return_action=None,
    return_trigger=None,
    decay_amount=0.0,
    reason="no return active",
    affects_manifest=False,
    affects_liminal=False,
)
"""A pre-built :class:`ReturnSummary` representing a healthy, non-returning system.

Use this as a default / fallback when no ``ReturnResult`` is available.
"""
