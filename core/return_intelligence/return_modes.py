"""
core/return_intelligence/return_modes.py
=========================================
Public-safe ReturnMode definitions for the return intelligence layer.

``ReturnMode`` is a *public-facing* enum that maps the internal
:class:`~core.continuum.return_engine.ReturnAction` values to labels that
downstream projection consumers can safely use.  It intentionally carries no
``receding`` concept — the internal ``receding`` phase is an implementation
detail of the continuum engine and must never appear on a public surface.

Relationship to ReturnAction
----------------------------
The mapping is one-to-one in value, but the intent is different:

- :class:`~core.continuum.return_engine.ReturnAction` belongs to the *engine*
  and describes what the continuum *should do* next.
- :class:`ReturnMode` belongs to the *projection layer* and describes what
  return behaviour is *currently observable* to downstream consumers.

Downstream consumers (Status Board V2, Manifest Stage, Liminal layer) should
read :attr:`ReturnSummary.return_mode`, which is derived from
:class:`ReturnMode`.

Influence on projection surfaces
---------------------------------
+---------------------+--------------------------------------------------+
| ReturnMode          | Downstream effect                                |
+=====================+==================================================+
| NONE                | No return active; system is progressing forward. |
+---------------------+--------------------------------------------------+
| HOLD                | Stay in current phase; no intensity change.      |
+---------------------+--------------------------------------------------+
| SOFT_DECAY          | Gently reduce presence / ambient intensity.      |
+---------------------+--------------------------------------------------+
| STEP_DOWN           | Phase-level descent; liminal ← manifest.         |
+---------------------+--------------------------------------------------+
| RETURN_TO_FORMLESS  | Hard reset; immediate silent/formless state.     |
+---------------------+--------------------------------------------------+
"""

from __future__ import annotations

from enum import Enum


class ReturnMode(str, Enum):
    """Public-safe representation of the active return behaviour.

    Values align with :class:`~core.continuum.return_engine.ReturnAction` but
    are owned by the projection/intelligence layer, not the continuum engine.

    ``NONE`` is added here to indicate "no return is currently active",
    corresponding to a :class:`~core.continuum.return_engine.ReturnResult`
    with ``should_return=False``.
    """

    NONE = "none"
    """No return is active; the system is either holding or progressing."""

    HOLD = "hold"
    """The engine recommends staying in the current phase with no change."""

    SOFT_DECAY = "soft_decay"
    """Gently reduce presence intensity; no phase transition yet."""

    STEP_DOWN = "step_down"
    """Step down one phase level (e.g. manifest → liminal → silent)."""

    RETURN_TO_FORMLESS = "return_to_formless"
    """Immediate hard return to the formless / silent base state."""


# ---------------------------------------------------------------------------
# Influence-hint constants
# ---------------------------------------------------------------------------

#: ReturnModes that suppress ``stage_ready`` on the Manifest Surface.
MODES_THAT_SUPPRESS_MANIFEST: frozenset[ReturnMode] = frozenset(
    {ReturnMode.STEP_DOWN, ReturnMode.RETURN_TO_FORMLESS}
)

#: ReturnModes that cause liminal ambient intensity to soften.
MODES_THAT_SOFTEN_LIMINAL: frozenset[ReturnMode] = frozenset(
    {ReturnMode.SOFT_DECAY, ReturnMode.STEP_DOWN, ReturnMode.RETURN_TO_FORMLESS}
)

#: ReturnModes that indicate the system is actively returning (not holding).
ACTIVE_RETURN_MODES: frozenset[ReturnMode] = frozenset(
    {ReturnMode.SOFT_DECAY, ReturnMode.STEP_DOWN, ReturnMode.RETURN_TO_FORMLESS}
)
