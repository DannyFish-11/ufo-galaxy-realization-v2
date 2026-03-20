"""
desktop_projection
==================
Liminal Projection Engine — PR-5 / Manifest Stage Surface — PR-6.

Maps a :class:`~core.projection.RuntimeProjection` into a spatial
transition layer that drives the "silent → liminal → manifest" desktop
expansion sequence, and further into the manifest-stage 显现台 surface.

Public surface
--------------
::

    from desktop_projection import (
        # Liminal layer (PR-5)
        LiminalSpaceState,
        StateSpaceMapper,
        LiminalSpaceEngine,
        TransitionAnimator,
        TransitionPhase,
        # Manifest stage (PR-6)
        ManifestStageState,
        ManifestStageController,
        STAGE_READY_THRESHOLD,
        RETREAT_SOFTENING_THRESHOLD,
    )

See ``docs/LIMINAL_PROJECTION_ENGINE.md`` and ``docs/MANIFEST_STAGE.md``
for design rationale.
"""

from .state_space_mapper import LiminalSpaceState, StateSpaceMapper
from .liminal_space_engine import LiminalSpaceEngine
from .transition_animator import TransitionAnimator, TransitionPhase, EasingCurve
from .manifest_stage_state import ManifestStageState, STAGE_READY_THRESHOLD
from .manifest_stage_controller import ManifestStageController, RETREAT_SOFTENING_THRESHOLD

__all__ = [
    # Liminal layer (PR-5)
    "LiminalSpaceState",
    "StateSpaceMapper",
    "LiminalSpaceEngine",
    "TransitionAnimator",
    "TransitionPhase",
    "EasingCurve",
    # Manifest stage (PR-6)
    "ManifestStageState",
    "ManifestStageController",
    "STAGE_READY_THRESHOLD",
    "RETREAT_SOFTENING_THRESHOLD",
]
