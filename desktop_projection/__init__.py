"""
desktop_projection — Desktop Clothing Presentation Layer
=========================================================

**Unified-Subject Architecture — Desktop Clothing (Presentation Layer)**
------------------------------------------------------------------------
``desktop_projection`` is the **Windows desktop clothing presentation layer**
of the unified subject.  It translates subject lifecycle signals into desktop
visual transitions — the "clothing" that the subject wears on a Windows PC.

This package does NOT contain subject-core logic.  It is a *presentation*
concern that renders the subject's state as spatial animations and stage
transitions on the Windows desktop.

The clothing responds to the subject lifecycle but does NOT drive it:
- ``DesktopPresenceRuntime`` (shell) drives the tri-state lifecycle.
- ``OpenClawd`` (core) performs cognition and execution.
- This package *displays* the resulting state as desktop presence.

**Canonical consumption path**
-------------------------------
This package consumes :class:`~core.projection.RuntimeProjection` produced by
the canonical projection compiler::

    from core.projection import build_runtime_projection, compile_runtime_truth
    from desktop_projection import StateSpaceMapper, LiminalSpaceEngine

    # Preferred: use compile_runtime_truth() for the full canonical snapshot
    snapshot = compile_runtime_truth()
    # … or build a RuntimeProjection for the spatial mapper:
    projection = build_runtime_projection(continuum_state)
    spatial_state = StateSpaceMapper().map(projection)

Desktop consumers (status board, adapter surface) should use the canonical
adapter chain rather than assembling state independently:

1. ``GET /api/v1/projection/runtime-truth``  — canonical truth snapshot
2. ``GET /api/v1/projection/desktop-status-board``  — integrated PR-8 payload
3. :func:`~core.desktop_consumption_adapter.adapt_integration_payload` — flat view-model

Do **not** import raw subsystem modules (``multi_llm_router``,
``system_resource``, ``oneapi_system_position``) directly inside presentation
layer code; consume the canonical projection output instead.

See ``docs/PROJECTION_OUTPUT_AUTHORITY.md`` for the full canonical output
authority model.

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
