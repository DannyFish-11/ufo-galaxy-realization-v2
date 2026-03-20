"""
desktop_projection
==================
Liminal Projection Engine — PR-5.

Maps a :class:`~core.projection.RuntimeProjection` into a spatial
transition layer that drives the "silent → liminal → manifest" desktop
expansion sequence.

Public surface
--------------
::

    from desktop_projection import (
        LiminalSpaceState,
        StateSpaceMapper,
        LiminalSpaceEngine,
        TransitionAnimator,
        TransitionPhase,
    )

See ``docs/LIMINAL_PROJECTION_ENGINE.md`` for design rationale.
"""

from .state_space_mapper import LiminalSpaceState, StateSpaceMapper
from .liminal_space_engine import LiminalSpaceEngine
from .transition_animator import TransitionAnimator, TransitionPhase, EasingCurve

__all__ = [
    "LiminalSpaceState",
    "StateSpaceMapper",
    "LiminalSpaceEngine",
    "TransitionAnimator",
    "TransitionPhase",
    "EasingCurve",
]
