"""
core/routes/panel.py
=====================
PR-1: Unified Panel API Route — GET /api/v1/panel/unified

Exposes the single canonical unified runtime/panel aggregation endpoint.
Downstream consumers (CLI status boards, Windows GUI, Android app, dashboard)
MUST read from this endpoint instead of fanning out across multiple separate
operator, projection, and Android-ecosystem endpoints.

Routes
------
  GET /api/v1/panel/unified
      Returns the current :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`
      as a JSON object.  The payload aggregates all canonical state families:

      - Operator/control-plane projection (task counts, device presence,
        topology, capability providers, active flow count).
      - Shell/presence manifestation (desktop_shell_state, presence_tristate,
        manifestation_summary).
      - Android runtime/ecosystem state (ecosystem counts + per-device
        execution-phase digest sourced from android_device_state_store).
      - Continuum/flow execution state (tri_state_phase, runtime_domain,
        presence_intensity, coherence).
      - Execution readiness verdict (READY/BLOCKED/DEGRADED/UNKNOWN).
      - Active surface spec (SurfaceType for the current interaction mode).

      Query parameters:
          mode (str, default "chat"): Interaction mode forwarded to
              SurfaceSelector for the active_surface_spec field.

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.
- **Single aggregation surface** — all sub-state is assembled by
  :mod:`~core.unified_panel_aggregation`, which reads from canonical singletons
  and does NOT introduce a second truth store.
- **Graceful degradation** — if any sub-source is unavailable its section is
  left at default empty/zero values and the endpoint still returns 200.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Panel")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

PANEL_ROUTES_AUTHORITY: str = (
    "PANEL_ROUTES_V1: core/routes/panel.py is the canonical owner of the "
    "/api/v1/panel/* route surface.  All handlers consume "
    "UnifiedPanelAggregationService projections — no raw subsystem internals."
)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the unified panel router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all ``core/routes/`` modules.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/panel/unified
    # ------------------------------------------------------------------

    @router.get("/api/v1/panel/unified")
    async def get_unified_panel(
        mode: str = Query(default="chat", description="Interaction mode for surface spec"),
    ) -> JSONResponse:
        """Return the canonical unified runtime/panel payload.

        Aggregates operator/control-plane, shell/presence, Android ecosystem,
        continuum/flow execution, execution readiness, and active surface spec
        into a single :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`.

        This is the **single canonical read endpoint** for panel clients.
        Prefer this over calling /api/v1/operator/snapshot,
        /api/v1/projection/runtime, and /api/v1/operator/devices/ecosystem
        separately.

        Query parameters
        ----------------
        mode : str
            Interaction mode string (``chat``, ``deep_thinking``,
            ``control_console``, etc.) forwarded to :class:`SurfaceSelector`
            to set the ``active_surface_spec`` field.  Defaults to ``"chat"``.

        Response schema
        ---------------
        The response is the JSON serialisation of
        :class:`~core.unified_panel_aggregation.UnifiedPanelPayload`.  Key
        families:

        - ``payload_id``, ``generated_at``, ``schema_version`` — identity
        - ``active_task_count``, ``active_flow_count``,
          ``online_device_count``, ... — operator/control-plane
        - ``desktop_shell_state``, ``presence_tristate``,
          ``manifestation_summary`` — shell/presence
        - ``tri_state_phase``, ``runtime_domain``,
          ``presence_intensity``, ``coherence`` — continuum/flow execution
        - ``android_ecosystem``, ``android_device_execution_digest`` — Android
        - ``readiness_verdict``, ``blocked_dimensions`` — execution readiness
        - ``active_surface_spec`` — surface type for ``mode``
        - ``_source`` — provenance authority string
        """
        try:
            from core.unified_panel_aggregation import build_unified_panel_payload
            payload = build_unified_panel_payload(mode=mode)
            return JSONResponse(content=payload.to_dict())
        except Exception as exc:
            logger.error("get_unified_panel endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": PANEL_ROUTES_AUTHORITY},
                status_code=500,
            )

    return router
