"""
core/routes/operator.py
========================
PR-510: Operator API — first-class read endpoints for OperatorSurface.

**Architecture role: READ-ONLY OPERATOR INSPECTION SURFACE**
-------------------------------------------------------------
This module exposes the :class:`~core.operator_surface.OperatorSurface`
as a supported, first-class HTTP API.  All responses are derived
exclusively from ``OperatorSurface`` projections — handlers MUST NOT
reconstruct truth from raw subsystem internals.

Canonical route ownership is declared in ``core/api_routes.py`` via the
``CANONICAL_API_ROUTES_AUTHORITY`` sentinel.

Routes
------
  GET /api/v1/operator/snapshot
      Compact runtime overview — task counts, device presence, topology,
      capability totals.  Corresponds to
      :meth:`~core.operator_surface.OperatorSurface.operator_snapshot`.

  GET /api/v1/operator/inspect/task/{task_id}
      Deep read-only projection for a single task.
      Returns 404 when the task is not present in any canonical runtime layer.

  GET /api/v1/operator/inspect/route/{task_id}
      Route decision projection for a single task.
      Returns 404 when no routing data is available for the task.

  GET /api/v1/operator/inspect/executor/{node_id}
      Executor/provider presence and capability projection.
      Returns 404 when the node is unknown.

  GET /api/v1/operator/inspect/failure/{task_id}
      Failure domain projection for a single task.
      Returns 404 when no failure data is available for the task.

  GET /api/v1/operator/inspect/lineage/{task_id}
      Task lineage / timeline projection.
      Returns 404 when no lineage data is available for the task.

Design constraints
------------------
- **Read-only** — no writes, no side-effects.
- **Projection-only** — all responses come from ``OperatorSurface``; handlers
  never reach into raw subsystem internals.
- **Graceful degradation** — errors in the underlying runtime layers are
  caught and surfaced as HTTP 500 with an ``"error"`` key rather than
  crashing the server.
- **Role-boundary-stable** — ``OperatorSurface`` is NOT recast as the
  final desktop/status visual authority here.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Operator")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

OPERATOR_ROUTES_AUTHORITY: str = (
    "OPERATOR_ROUTES_V1: core/routes/operator.py is the canonical owner "
    "of the /api/v1/operator/* route surface.  All handlers consume "
    "OperatorSurface projections — no raw subsystem internals."
)


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the operator inspection router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all ``core/routes/`` modules.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/operator/snapshot
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/snapshot")
    async def operator_snapshot() -> JSONResponse:
        """Return a compact :class:`~core.operator_surface.OperatorSnapshot`.

        Aggregates all canonical runtime dimensions — task counts, device
        presence, topology sizes, and capability provider counts.

        Always returns a valid payload; missing runtime layers yield
        zeroed fields rather than errors.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            snap = surface.operator_snapshot()
            return JSONResponse(content=snap.to_dict())
        except Exception as exc:
            logger.error("operator_snapshot endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/task/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/task/{task_id}")
    async def inspect_task(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.TaskInspection` for *task_id*.

        Returns HTTP 404 when the task is not present in any canonical
        runtime layer.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_task(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_task(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/route/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/route/{task_id}")
    async def inspect_route(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.RouteInspection` for *task_id*.

        Returns HTTP 404 when no routing data is available for the task.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_route(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"route for task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_route(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/executor/{node_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/executor/{node_id}")
    async def inspect_executor(node_id: str) -> JSONResponse:
        """Return an :class:`~core.operator_surface.ExecutorInspection` for *node_id*.

        Returns HTTP 404 when the node is unknown to the capability layer.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_executor(node_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"executor '{node_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_executor(%s) endpoint error: %s", node_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/failure/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/failure/{task_id}")
    async def inspect_failure(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.FailureDomainInspection` for *task_id*.

        Returns HTTP 404 when no failure domain data is available.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_failure_domain(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"failure domain for task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_failure(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/lineage/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/lineage/{task_id}")
    async def inspect_lineage(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.LineageInspection` for *task_id*.

        Returns HTTP 404 when no lineage data is available for the task.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_lineage(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"lineage for task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_lineage(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    return router
