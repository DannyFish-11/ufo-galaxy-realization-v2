"""
core/routes/existence.py
=========================
PR-2: Desktop Existence Surface — GET /api/v1/existence/surface

Exposes the single canonical assistant-like existence surface assembled by
:mod:`~core.desktop_existence_surface`.  Downstream consumers (CLI status
boards, Windows GUI, Android app, dashboard) may call this endpoint to obtain
a coherent view of the assistant's existence across all five real state
families rather than reading fragmented state from separate endpoints.

Routes
------
  GET /api/v1/existence/surface
      Returns the current :class:`~core.desktop_existence_surface.DesktopExistenceSurface`
      as a JSON object.  The payload contains all five state-family snapshots:

      - ``subject_lifecycle``  — TriState subject lifecycle (SILENT/LIMINAL/MANIFEST)
      - ``shell_clothing``     — SystemState UI clothing (DORMANT/ISLAND/SIDESHEET/FULLAGENT)
      - ``continuum_posture``  — OpenClawd tri_state_phase + runtime_domain
      - ``cognitive_field``    — CognitiveFieldEngine activation / manifest_pressure
      - ``android_signals``    — Android device presence signals
      - ``existence_projection`` — Derived read-only presence verdict

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.
- **Single source** — all sub-state is assembled by
  :func:`~core.desktop_existence_surface.build_desktop_existence_surface`,
  which reads from canonical singletons and does NOT introduce a second truth
  store.
- **Graceful degradation** — if any source singleton is unavailable its
  family section is left at empty defaults and the endpoint still returns 200.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Existence")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

EXISTENCE_ROUTES_AUTHORITY: str = (
    "EXISTENCE_ROUTES_V1: core/routes/existence.py is the canonical owner of "
    "the /api/v1/existence/* route surface.  All handlers consume "
    "DesktopExistenceSurface projections — no raw subsystem internals."
)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the existence surface router.

    The ``service_manager`` and ``config`` parameters are accepted for
    signature compatibility with all other ``core/routes/`` factories.
    They are intentionally unused because this router's only handler
    delegates entirely to
    :func:`~core.desktop_existence_surface.build_desktop_existence_surface`.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/existence/surface
    # ------------------------------------------------------------------

    @router.get("/api/v1/existence/surface")
    def get_existence_surface() -> JSONResponse:
        """Return the current unified assistant-like existence surface.

        Reads from five real state families:

        1. Subject lifecycle tri-state (DesktopPresenceRuntime)
        2. UI shell clothing state (SystemStateMachine / SystemState)
        3. Continuum posture (ContinuumOrchestrator tri_state_phase/runtime_domain)
        4. Continuous cognitive field (CognitiveFieldEngine / CognitiveState)
        5. Android presence signals (android_device_state_store)

        Returns a JSON object containing all five family snapshots plus a
        derived ``existence_projection`` verdict.  All reads are best-effort;
        a source failure yields empty defaults for that family rather than an
        error response.
        """
        try:
            from core.desktop_existence_surface import build_desktop_existence_surface

            surface = build_desktop_existence_surface()
            return JSONResponse(content=surface.to_dict())
        except Exception as exc:
            logger.exception("existence surface build failed")
            return JSONResponse(
                content={"error": "existence surface unavailable", "detail": str(exc)},
                status_code=503,
            )

    return router
