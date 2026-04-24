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

  GET /api/v1/operator/inspect/recovery/{task_id}
      Recovery disposition projection for a single task: whether work was
      resumed, replayed, re-dispatched, or treated as terminal after
      interruption.  Returns 404 when no recovery record is available.

  GET /api/v1/operator/inspect/partial-result/{task_id}
      Hybrid orchestration partial-result outcome: preserved, invalidated,
      merged, or resumed.  Returns 404 when no hybrid execution record is
      found for the task.

  GET /api/v1/operator/inspect/audit-evidence/{task_id}
      Durable audit evidence coverage for a single task — record counts
      by kind, timestamp range.  Always returns a valid payload.

  GET /api/v1/operator/review/{task_id}
      Unified end-to-end postmortem review: combines task lifecycle, routing
      decision, recovery disposition, partial-result outcome, audit evidence,
      and lineage in one response.  Always returns a valid payload.

  GET /api/v1/operator/inspect/flow/{flow_id}
      Flow-level canonical projection for a delegated flow: identity, lineage,
      Android execution phase, blocking reason, recovery/truth/result status.
      Returns 404 when the flow is unknown.

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

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/recovery/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/recovery/{task_id}")
    async def inspect_recovery(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.RecoveryInspection` for *task_id*.

        Surfaces recovery disposition: whether the task was resumed,
        replayed, re-dispatched, or treated as terminal after an
        interruption.

        Returns HTTP 404 when no recovery record is available for the task.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_recovery(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"recovery record for task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_recovery(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/partial-result/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/partial-result/{task_id}")
    async def inspect_partial_result(task_id: str) -> JSONResponse:
        """Return a :class:`~core.operator_surface.PartialResultInspection` for *task_id*.

        Surfaces the hybrid orchestration partial-result disposition:
        whether partial work was preserved, invalidated, merged, or used
        for resumption.

        Returns HTTP 404 when no hybrid execution record is found for the task.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_partial_result(task_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"partial result record for task '{task_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_partial_result(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/audit-evidence/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/audit-evidence/{task_id}")
    async def inspect_audit_evidence(task_id: str) -> JSONResponse:
        """Return an :class:`~core.operator_surface.AuditEvidenceInspection` for *task_id*.

        Surfaces durable audit evidence coverage: how many audit records
        of each kind exist for this task in the durable store.

        Always returns a valid payload (zero counts when no evidence exists).
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_audit_evidence(task_id)
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_audit_evidence(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/review/{task_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/review/{task_id}")
    async def end_to_end_review(task_id: str) -> JSONResponse:
        """Return an :class:`~core.operator_surface.EndToEndReviewSummary` for *task_id*.

        Unified postmortem-ready view combining task lifecycle, routing
        decision, recovery disposition, partial-result outcome, audit
        evidence, and lineage for a single task.

        Always returns a valid payload; missing dimensions produce ``null``
        fields rather than errors.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.end_to_end_review(task_id)
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("end_to_end_review(%s) endpoint error: %s", task_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/inspect/flow/{flow_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/inspect/flow/{flow_id}")
    async def inspect_flow(flow_id: str) -> JSONResponse:
        """Return a :class:`~core.flow_level_operator_surface.FlowOperatorProjection` for *flow_id*.

        Provides the canonical flow-level operator projection for a
        delegated flow, covering:

        * Flow identity, lineage, and delegated object bindings
          (canonical_task_id, contract_id, binding_id, device_id).
        * Current Android canonical execution phase
          (planning / grounding / execution / replan / stagnation /
          gate_decision / takeover / collaboration / completed / failed /
          unknown).
        * Most recent Android canonical execution event absorbed from the
          Android runtime.
        * Current blocking reason (gate, stagnation, etc.), if any.
        * Recovery, truth alignment, and result convergence status summaries.
        * Operator review notes about evidence gaps.

        Returns HTTP 404 when the delegated flow is not known to the
        DelegatedFlowEntityRuntime.
        """
        try:
            from core.operator_surface import get_operator_surface
            surface = get_operator_surface()
            result = surface.inspect_flow(flow_id)
            if result is None:
                return JSONResponse(
                    content={"detail": f"flow '{flow_id}' not found"},
                    status_code=404,
                )
            return JSONResponse(content=result.to_dict())
        except Exception as exc:
            logger.error("inspect_flow(%s) endpoint error: %s", flow_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    return router
