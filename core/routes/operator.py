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
  GET /api/v1/readiness
      Runtime readiness matrix verdict and per-dimension status.  Backed by
      :func:`~core.runtime_readiness_matrix.get_readiness_matrix`.

  GET /api/v1/operator/snapshot
      Compact runtime overview — task counts, device presence, topology,
      capability totals.  Corresponds to
      :meth:`~core.operator_surface.OperatorSurface.operator_snapshot`.

  GET /api/v1/operator/flows
      List all known delegated flows as :class:`~core.flow_level_operator_surface.FlowOperatorProjection`
      dicts.  Sourced from :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface`
      over all entities in :class:`~core.delegated_flow_entity.DelegatedFlowEntityRuntime`.

  GET /api/v1/operator/flows/{flow_id}
      Canonical alias for /api/v1/operator/inspect/flow/{flow_id}.

  GET /api/v1/operator/llm
      LLM provider health summary from
      :meth:`~core.multi_llm_router.MultiLLMRouter.get_status`.

  GET /api/v1/operator/nats
      NATS bus connection state and statistics from
      :func:`~core.nats_bus.nats_bus.get_stats`.

  GET /api/v1/operator/heartbeat
      OpenClawd HeartbeatScheduler state — enabled flag, interval, cycle
      count, and configuration summary.

  GET /api/v1/ports
      Port registry — all known node and service ports from
      :class:`~core.port_config.PortConfig`.

  GET /api/v1/operator/devices/ecosystem
      Multi-device Android ecosystem state — per-device readiness, model
      identity, runtime availability, queue depth, and fallback tier.
      Sourced from :mod:`core.android_device_state_store`.

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

    # ------------------------------------------------------------------
    # GET /api/v1/readiness
    # ------------------------------------------------------------------

    @router.get("/api/v1/readiness")
    async def readiness() -> JSONResponse:
        """Return the runtime :class:`~core.runtime_readiness_matrix.ReadinessMatrix`.

        Evaluates all critical and advisory readiness dimensions and returns
        the full matrix with per-dimension status, the overall verdict
        (READY / BLOCKED / DEGRADED / UNKNOWN), and the list of dimensions
        that produced a BLOCKED or UNKNOWN verdict.

        Always returns a valid payload; evaluation errors yield UNKNOWN status.
        """
        try:
            from core.runtime_readiness_matrix import get_readiness_matrix
            matrix = get_readiness_matrix()
            return JSONResponse(content=matrix.to_dict())
        except Exception as exc:
            logger.error("readiness endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/flows
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/flows")
    async def list_flows() -> JSONResponse:
        """Return a list of all delegated flow projections.

        Queries :class:`~core.delegated_flow_entity.DelegatedFlowEntityRuntime`
        for all known entities and projects each one through
        :class:`~core.flow_level_operator_surface.FlowLevelOperatorSurface`.

        Flows with no projection (e.g. unknown to the surface) are skipped.
        Returns an empty list when no flows have been registered.
        """
        try:
            from core.delegated_flow_entity import get_delegated_flow_entity_runtime
            from core.flow_level_operator_surface import get_flow_level_operator_surface

            runtime = get_delegated_flow_entity_runtime()
            surface = get_flow_level_operator_surface()
            all_entities = runtime.list_all()

            projections = []
            for entity in all_entities:
                fid = entity.identity.delegated_flow_id
                proj = surface.inspect_flow(fid)
                if proj is not None:
                    projections.append(proj.to_dict())

            return JSONResponse(content={
                "flows": projections,
                "total": len(projections),
                "active": sum(
                    1 for e in all_entities if e.phase.is_active()
                ),
            })
        except Exception as exc:
            logger.error("list_flows endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/flows/{flow_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/flows/{flow_id}")
    async def get_flow(flow_id: str) -> JSONResponse:
        """Canonical alias for /api/v1/operator/inspect/flow/{flow_id}.

        Returns a :class:`~core.flow_level_operator_surface.FlowOperatorProjection`
        for the specified *flow_id*.  Returns HTTP 404 when unknown.
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
            logger.error("get_flow(%s) endpoint error: %s", flow_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/llm
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/llm")
    async def llm_status() -> JSONResponse:
        """Return LLM provider health summary.

        Sources data from :meth:`~core.multi_llm_router.MultiLLMRouter.get_status`
        (or the process-level :class:`~core.llm_manager.LLMManager` when
        MultiLLMRouter is not available as a singleton).

        Returns per-provider: status (healthy/degraded/down), latency,
        error count, success count, and circuit-breaker state.
        """
        try:
            # Prefer the canonical singleton from llm_manager / system
            llm_router = None
            try:
                from core.llm_manager import get_llm_manager
                llm_router = get_llm_manager()
            except Exception:
                pass

            if llm_router is None:
                try:
                    from core.multi_llm_router import MultiLLMRouter
                    llm_router = MultiLLMRouter()
                except Exception:
                    pass

            if llm_router is None:
                return JSONResponse(content={
                    "available": False,
                    "detail": "LLM router not available",
                    "authority": "OPERATOR_ROUTES_V1",
                })

            if hasattr(llm_router, "get_status"):
                status = llm_router.get_status()
            elif hasattr(llm_router, "get_provider_status"):
                status = {
                    "providers": llm_router.get_provider_status(),
                    "available": llm_router.is_available() if hasattr(llm_router, "is_available") else True,
                }
            else:
                status = {"detail": "get_status not available on LLM router"}

            return JSONResponse(content={"available": True, **status})
        except Exception as exc:
            logger.error("llm_status endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/nats
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/nats")
    async def nats_status() -> JSONResponse:
        """Return NATS bus connection state and statistics.

        Sources data from :func:`~core.nats_bus.nats_bus.is_connected` and
        :func:`~core.nats_bus.nats_bus.get_stats`.

        Returns::

            {
              "connected": bool,
              "noop_mode": bool,
              "nats_url": str,
              "stats": { "published": int, "received": int, ... }
            }
        """
        try:
            from core.nats_bus import nats_bus
            stats = nats_bus.get_stats()
            connected = nats_bus.is_connected() if hasattr(nats_bus, "is_connected") else stats.get("connected", False)
            import os
            nats_url = os.environ.get("GALAXY_NATS_URL", "nats://localhost:4222")
            return JSONResponse(content={
                "connected": connected,
                "noop_mode": stats.get("noop_mode", True),
                "nats_url": nats_url,
                "stats": stats,
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("nats_status endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/heartbeat
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/heartbeat")
    async def heartbeat_status() -> JSONResponse:
        """Return OpenClawd HeartbeatScheduler state.

        Sources data from
        :func:`~core.openclawd_heartbeat.get_heartbeat_scheduler`.

        Returns::

            {
              "enabled": bool,
              "running": bool,
              "cycle_count": int,
              "interval_seconds": int,
              "task_file": str,
              "tier1_model": str,
              "tier2_model": str
            }
        """
        try:
            from core.openclawd_heartbeat import get_heartbeat_scheduler
            scheduler = get_heartbeat_scheduler()
            if scheduler is None:
                return JSONResponse(content={
                    "enabled": False,
                    "running": False,
                    "detail": "HeartbeatScheduler not initialised (OpenClawd unavailable)",
                    "authority": "OPERATOR_ROUTES_V1",
                })
            running = (
                scheduler._task is not None
                and not scheduler._task.done()
            ) if hasattr(scheduler, "_task") else False
            return JSONResponse(content={
                "enabled": scheduler.is_enabled(),
                "running": running,
                "cycle_count": getattr(scheduler, "_cycle_count", 0),
                "interval_seconds": getattr(scheduler, "_interval_seconds", None),
                "task_file": getattr(scheduler, "_task_file", None),
                "tier1_model": getattr(scheduler, "_tier1_model", None),
                "tier2_model": getattr(scheduler, "_tier2_model", None),
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("heartbeat_status endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/ports
    # ------------------------------------------------------------------

    @router.get("/api/v1/ports")
    async def ports() -> JSONResponse:
        """Return the canonical port registry.

        Sources data from :class:`~core.port_config.PortConfig` — all
        known node ports and service/infrastructure ports.

        Returns::

            {
              "node_ports": { "Node_50_Transformer": 8050, ... },
              "service_ports": { "redis": 6379, "gateway": 8765, ... }
            }
        """
        try:
            from core.port_config import PortConfig
            pc = PortConfig()
            return JSONResponse(content={
                "node_ports": pc.list_node_ports(),
                "service_ports": pc.list_service_ports(),
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("ports endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/devices/ecosystem
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/devices/ecosystem")
    async def devices_ecosystem() -> JSONResponse:
        """Return multi-device Android ecosystem state.

        Sources per-device runtime snapshots absorbed from
        ``DEVICE_STATE_SNAPSHOT`` messages via
        :mod:`core.android_device_state_store`.

        Returns::

            {
              "total_devices_with_snapshot": int,
              "local_ai_ready_count": int,
              "model_ready_count": int,
              "accessibility_ready_count": int,
              "overlay_ready_count": int,
              "pending_first_download_count": int,
              "devices": [
                {
                  "device_id": str,
                  "absorbed_at": float,
                  "readiness": { ... },
                  "model": { ... },
                  "active_runtime_type": str | null,
                  "offline_queue_depth": int | null,
                  "current_fallback_tier": str | null,
                  "warmup_result": str | null
                }
              ]
            }
        """
        try:
            from core.android_device_state_store import get_device_ecosystem_summary
            summary = get_device_ecosystem_summary()
            return JSONResponse(content={"authority": "OPERATOR_ROUTES_V1", **summary})
        except Exception as exc:
            logger.error("devices_ecosystem endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/devices/ecosystem/{device_id}
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/devices/ecosystem/{device_id}")
    async def device_ecosystem(device_id: str) -> JSONResponse:
        """Return the Android ecosystem state snapshot for a single *device_id*.

        Returns HTTP 404 when no state snapshot has been received for the device.
        """
        try:
            from core.android_device_state_store import get_device_state_snapshot
            snap = get_device_state_snapshot(device_id)
            if snap is None:
                return JSONResponse(
                    content={"detail": f"no state snapshot for device '{device_id}'"},
                    status_code=404,
                )
            return JSONResponse(content=snap.to_dict())
        except Exception as exc:
            logger.error("device_ecosystem(%s) endpoint error: %s", device_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    return router
