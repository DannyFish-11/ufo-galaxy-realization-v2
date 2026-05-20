"""
core/routes/operator.py
========================
PR-510 / PR-3: Operator API — read endpoints + canonical action endpoints.

**Architecture role: CANONICAL OPERATOR CONTROL PLANE**
--------------------------------------------------------
This module exposes the :class:`~core.operator_surface.OperatorSurface`
as a supported, first-class HTTP API.  All read responses are derived
exclusively from ``OperatorSurface`` projections — handlers MUST NOT
reconstruct truth from raw subsystem internals.

PR-3 (Operator Control-Plane Activation) upgrades this surface from
observation-only to action-capable by adding POST endpoints that route
operator-originated actions into the canonical runtime/orchestration path
via :meth:`~core.operator_surface.OperatorSurface.execute_operator_action`.

Canonical route ownership is declared in ``core/api_routes.py`` via the
``CANONICAL_API_ROUTES_AUTHORITY`` sentinel.

Routes
------
  GET /api/v1/operator/snapshot
      Compact runtime overview — task counts, device presence, topology,
      capability totals.  Corresponds to
      :meth:`~core.operator_surface.OperatorSurface.operator_snapshot`.

  GET /api/v1/operator/actions/availability
      Policy-aware operator action catalog with per-action availability,
      control_mode (automatic/manual/approval_gated), and state-basis gating.

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

  GET /api/v1/operator/devices/ecosystem/{device_id}
      Android runtime-state snapshot for a single device.
      Returns HTTP 404 when no snapshot has been received for the device.

  GET /api/v1/operator/devices/execution-events
      Recent Android execution phase events across all connected devices.
      Sourced from DEVICE_EXECUTION_EVENT messages absorbed by
      :mod:`core.android_device_state_store`.

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

  --- PR-3: Operator Control-Plane Action Endpoints ---

  POST /api/v1/operator/action
      General operator action endpoint.  Accepts an
      :class:`~core.operator_action_contract.OperatorActionRequest` body and
      routes the action into the canonical runtime via
      :meth:`~core.operator_surface.OperatorSurface.execute_operator_action`.
      Supported action_kind values: ``dispatch``, ``device_dispatch``,
      ``flow_cancel``.

  POST /api/v1/operator/dispatch
      Convenience endpoint for task-dispatch actions.  Equivalent to
      POST /api/v1/operator/action with action_kind=dispatch.  Accepts
      ``message``, ``device_id``, ``session_id``, ``user_id``,
      ``required_capabilities``, and ``context`` fields.

  POST /api/v1/operator/flows/{flow_id}/cancel
      Request cancellation of a specific in-flight delegated flow.  Routes
      through :meth:`~core.operator_surface.OperatorSurface.execute_operator_action`
      with action_kind=flow_cancel.  Safe semantics: terminal flows are not
      affected.

  --- PR-4: Operator Action Governance Endpoints ---

  GET /api/v1/operator/actions/audit
      Full operator action audit log.  Returns recent
      :class:`~core.pr4_operator_action_governance.OperatorActionAuditRecord` entries
      with who triggered each action, why it was allowed, pre/post state,
      success/failure/rollback result, and downstream effects.
      Supports filtering by action_kind and outcome.

  GET /api/v1/operator/board/operable-truth
      PR-4 operable board projection showing:
      (1) what is wrong (block/degraded/manual counts, active blockers),
      (2) what can currently be done (policy-derived available actions),
      (3) why actions are available or unavailable (state-basis),
      (4) last action feedback (kind, outcome, affected entities).
      Action availability is policy-derived — not hard-coded.

  GET /api/v1/operator/pr4/snapshot
      Top-level PR-4 operable surface snapshot combining board projection,
      recent audit records, pending Android-directed action count, and
      contract version/authority confirmation.

  POST /api/v1/operator/actions/android-directed
      Dispatch an Android-directed operator action.  Builds an
      :class:`~core.pr4_operator_action_governance.AndroidDirectedActionSpec`
      and stores it as pending until the Android device ACKs.

  POST /api/v1/operator/actions/android-directed/{dispatch_id}/ack
      Record that an Android device has ACKed a directed action.  Removes
      the action from the pending store.

  --- PR-X：设备 Dispatch 就绪控制面端点 ---

  GET /api/v1/operator/devices/{device_id}/dispatch-readiness
      单台设备的 dispatch 就绪状态：包含结构化 status 枚举、注册 gap 列表、
      阻断说明、附接状态等，而不仅是布尔标志。数据源：
      :mod:`core.device_dispatch_readiness_surface`。

  GET /api/v1/operator/devices/dispatch-readiness
      全设备 dispatch 就绪面板：枚举所有已知设备，汇总各 status 类别数量，
      每台设备携带完整结构化拦截原因。提供操作员和下游消费者一站式
      control-plane 视图。

Design constraints
------------------
- **Read endpoints: Read-only** — no writes, no side-effects.
- **Action endpoints: Canonical path only** — all actions enter the runtime
  via OperatorSurface.execute_operator_action() → DesktopPresenceRuntime.
  No parallel execution engine is introduced.
- **Projection-only reads** — all read responses come from ``OperatorSurface``;
  handlers never reach into raw subsystem internals.
- **Graceful degradation** — errors in the underlying runtime layers are
  caught and surfaced as HTTP 500 with an ``"error"`` key rather than
  crashing the server.
- **Role-boundary-stable** — ``OperatorSurface`` is NOT recast as the
  final desktop/status visual authority here.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Operator")

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

OPERATOR_ROUTES_AUTHORITY: str = (
    "OPERATOR_ROUTES_V1: core/routes/operator.py is the canonical owner "
    "of the /api/v1/operator/* route surface.  Read handlers consume "
    "OperatorSurface projections — no raw subsystem internals.  "
    "Action handlers (POST /api/v1/operator/action, POST /api/v1/operator/dispatch, "
    "POST /api/v1/operator/flows/{flow_id}/cancel) route into the canonical "
    "runtime via OperatorSurface.execute_operator_action() — no parallel "
    "execution engine."
)


def _operator_consumption_contract_boundary() -> Dict[str, Any]:
    return {
        "canonical_backend_contract": {
            "surface": "operator",
            "authority": "OPERATOR_ROUTES_V1",
            "source": "core.operator_surface + core.v2_unified_state_contract",
        },
        "consumption_layer_role": "operator_board_projection_consumer_only",
        "ui_visible_summary_role": "operator_visible_interpretation_only",
        "ui_visible_summary_is_backend_truth": False,
        "action_intent_approval_execution_chain": {
            "intent_entry": "/api/v1/operator/action",
            "approval_signal": "approval_token",
            "execution_path": "OperatorSurface.execute_operator_action",
        },
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------

def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the operator inspection router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all ``core/routes/`` modules.
    """
    router = APIRouter()

    def _build_roundtrip_runtime_result(result: Any) -> Dict[str, Any]:
        payload = dict(getattr(result, "runtime_result", {}) or {})
        payload.setdefault("accepted", bool(getattr(result, "accepted", False)))
        payload.setdefault("error", str(getattr(result, "error", "") or ""))
        payload.setdefault("action_kind", str(getattr(result, "action_kind", "")))
        return payload

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
    # GET /api/v1/operator/actions/availability
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/actions/availability")
    async def operator_actions_availability() -> JSONResponse:
        """Return current policy/state-gated operator action availability."""
        try:
            from core.operator_surface import get_operator_surface

            surface = get_operator_surface()
            return JSONResponse(
                content={
                    **surface.get_operator_action_availability(),
                    "authority": "OPERATOR_ROUTES_V1",
                }
            )
        except Exception as exc:
            logger.error("operator_actions_availability endpoint error: %s", exc)
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
                "authority": "OPERATOR_ROUTES_V1",
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
            return JSONResponse(content={"authority": "OPERATOR_ROUTES_V1", **snap.to_dict()})
        except Exception as exc:
            logger.error("device_ecosystem(%s) endpoint error: %s", device_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/devices/execution-events
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/devices/execution-events")
    async def devices_execution_events(
        flow_id: Optional[str] = Query(None, description="Filter by delegated flow id"),
        device_id: Optional[str] = Query(None, description="Filter by Android device id"),
        limit: int = Query(100, ge=1, le=500, description="Maximum number of events to return"),
    ) -> JSONResponse:
        """Return recent Android execution phase events.

        Sources ``DEVICE_EXECUTION_EVENT`` records absorbed by
        :mod:`core.android_device_state_store`.  Returns the most recent
        events across all connected Android devices, making delegated-execution
        phase progression visible to the V2 operator surface.

        Optional query parameters:

        * ``flow_id`` — filter to events belonging to a specific delegated flow.
        * ``device_id`` — filter to events emitted by a specific Android device.
        * ``limit`` — cap the number of returned events (default 100, max 500).

        Returns::

            {
              "total_events": int,
              "events": [
                {
                  "device_id": str,
                  "absorbed_at": float,
                  "flow_id": str | null,
                  "task_id": str | null,
                  "phase": str | null,
                  "step_index": int,
                  "is_blocking": bool,
                  "blocking_reason": str | null,
                  "stagnation_detected": bool,
                  "fallback_tier": str | null,
                  "event_ts": float | null
                },
                ...
              ],
              "authority": "OPERATOR_ROUTES_V1"
            }
        """
        try:
            from core.android_device_state_store import list_recent_execution_events
            events = list_recent_execution_events(
                flow_id=flow_id or None,
                device_id=device_id or None,
                limit=limit,
            )
            return JSONResponse(content={
                "total_events": len(events),
                "events": [e.to_dict() for e in events],
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("devices_execution_events endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ==================================================================
    # PR-3: Operator Control-Plane Action Endpoints
    # ==================================================================
    #
    # These endpoints upgrade the operator surface from observation-only
    # to action-capable.  Every action is routed through
    # OperatorSurface.execute_operator_action() → DesktopPresenceRuntime
    # so that:
    #   - the canonical tri-state lifecycle is respected
    #   - no parallel execution engine is introduced
    #   - all operator actions are traceable via ingress_carrier_context

    # ------------------------------------------------------------------
    # POST /api/v1/operator/action
    # ------------------------------------------------------------------

    @router.post("/api/v1/operator/action")
    async def operator_action(body: Dict[str, Any]) -> JSONResponse:
        """Execute an operator-panel action via the canonical runtime path.

        Accepts an :class:`~core.operator_action_contract.OperatorActionRequest`
        payload and routes the action through
        :meth:`~core.operator_surface.OperatorSurface.execute_operator_action`,
        which delegates to the canonical
        :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`.

        No parallel execution engine is introduced — all action kinds
        enter the same canonical tri-state lifecycle that chat and e2e
        requests use.

        Request body fields
        -------------------
        ``action_kind`` (required)
            One of ``"dispatch"``, ``"device_dispatch"``, ``"flow_cancel"``.
        ``message``
            Natural-language task message (for dispatch/device_dispatch).
        ``device_id``
            Target Android device (for device_dispatch; optional for dispatch).
        ``flow_id``
            Target flow ID (required for flow_cancel).
        ``session_id``
            Operator session ID for continuity tracing.
        ``user_id``
            Operator user ID (default: ``"operator"``).
        ``required_capabilities``
            Optional capability filter list.
        ``context``
            Optional conversation context list.

        Returns::

            {
              "action_id": str,
              "action_kind": str,
              "accepted": bool,
              "runtime_session_id": str,
              "trace_id": str,
              "operator_entry_mode": "operator_action",
              "runtime_result": { ... },
              "error": str,
              "generated_at": float,
              "authority": str
            }
        """
        try:
            from core.operator_action_contract import OperatorActionRequest
            from core.operator_surface import get_operator_surface
            from core.unified_panel_aggregation import record_last_operator_action_result
            request = OperatorActionRequest.from_dict(body)
            surface = get_operator_surface()
            result = await surface.execute_operator_action(request)
            record_last_operator_action_result(result)
            # PR-4: Record execution roundtrip so the unified panel surface
            # reflects the actual execution outcome (not just "accepted").
            try:
                from core.canonical_roundtrip import record_execution_roundtrip
                record_execution_roundtrip(
                    action_id=result.action_id,
                    action_kind=result.action_kind,
                    trace_id=result.trace_id,
                    session_id=result.runtime_session_id,
                    runtime_result=_build_roundtrip_runtime_result(result),
                )
            except Exception:
                pass
            status = 200 if result.accepted else 422
            return JSONResponse(
                content={**result.to_dict(), "authority": "OPERATOR_ROUTES_V1"},
                status_code=status,
            )
        except Exception as exc:
            logger.error("operator_action endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # POST /api/v1/operator/dispatch
    # ------------------------------------------------------------------

    @router.post("/api/v1/operator/dispatch")
    async def operator_dispatch(body: Dict[str, Any]) -> JSONResponse:
        """Convenience operator dispatch endpoint.

        Equivalent to POST /api/v1/operator/action with
        ``action_kind`` set to ``"dispatch"`` (or ``"device_dispatch"`` when
        ``device_id`` is provided).  Routes via the canonical
        :meth:`~core.desktop_presence_runtime.DesktopPresenceRuntime.handle_request`
        path.

        Request body fields
        -------------------
        ``message`` (required)
            Natural-language task message.
        ``device_id``
            Optional target device ID (switches to ``device_dispatch`` kind).
        ``session_id``
            Optional operator session ID.
        ``user_id``
            Operator user ID (default: ``"operator"``).
        ``required_capabilities``
            Optional capability filter list.
        ``context``
            Optional conversation context list.

        Returns::

            {
              "action_id": str,
              "action_kind": "dispatch" | "device_dispatch",
              "accepted": bool,
              "runtime_session_id": str,
              "trace_id": str,
              "operator_entry_mode": "operator_action",
              "runtime_result": { ... },
              "error": str,
              "generated_at": float,
              "authority": str
            }
        """
        try:
            from core.operator_action_contract import (
                OperatorActionRequest,
                OperatorActionKind,
            )
            from core.operator_surface import get_operator_surface
            from core.unified_panel_aggregation import record_last_operator_action_result
            # Determine kind: device_dispatch when device_id is present
            device_id = body.get("device_id") or None
            kind = (
                OperatorActionKind.device_dispatch.value
                if device_id
                else OperatorActionKind.dispatch.value
            )
            request = OperatorActionRequest(
                action_kind=kind,
                message=body.get("message", ""),
                device_id=device_id,
                session_id=body.get("session_id", ""),
                user_id=body.get("user_id", "operator"),
                required_capabilities=list(body.get("required_capabilities") or []),
                context=list(body.get("context") or []),
            )
            surface = get_operator_surface()
            result = await surface.execute_operator_action(request)
            record_last_operator_action_result(result)
            # PR-4: Record execution roundtrip so the unified panel surface
            # reflects the actual execution outcome (not just "accepted").
            try:
                from core.canonical_roundtrip import record_execution_roundtrip
                record_execution_roundtrip(
                    action_id=result.action_id,
                    action_kind=result.action_kind,
                    trace_id=result.trace_id,
                    session_id=result.runtime_session_id,
                    runtime_result=_build_roundtrip_runtime_result(result),
                )
            except Exception:
                pass
            status = 200 if result.accepted else 422
            return JSONResponse(
                content={**result.to_dict(), "authority": "OPERATOR_ROUTES_V1"},
                status_code=status,
            )
        except Exception as exc:
            logger.error("operator_dispatch endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # POST /api/v1/operator/flows/{flow_id}/cancel
    # ------------------------------------------------------------------

    @router.post("/api/v1/operator/flows/{flow_id}/cancel")
    async def operator_flow_cancel(flow_id: str) -> JSONResponse:
        """Request cancellation of a specific in-flight delegated flow.

        Routes through
        :meth:`~core.operator_surface.OperatorSurface.execute_operator_action`
        with ``action_kind=flow_cancel``.  Safe semantics: a flow that is
        already in a terminal phase (cancelled, completed, failed) is not
        affected — no error is raised.

        Path parameters
        ---------------
        ``flow_id``
            The delegated flow ID to cancel.

        Returns::

            {
              "action_id": str,
              "action_kind": "flow_cancel",
              "accepted": bool,
              "runtime_session_id": "",
              "trace_id": "",
              "operator_entry_mode": "operator_action",
              "runtime_result": {
                "flow_id": str,
                "phase_after_cancel": str,
                "_source": "delegated_flow_entity_runtime"
              },
              "error": str,
              "generated_at": float,
              "authority": str
            }

        Returns HTTP 404 when the flow is not found.
        Returns HTTP 422 when the cancellation was not accepted (e.g. invalid
        flow_id format).
        """
        try:
            from core.operator_action_contract import (
                OperatorActionRequest,
                OperatorActionKind,
            )
            from core.operator_surface import get_operator_surface
            from core.unified_panel_aggregation import record_last_operator_action_result
            request = OperatorActionRequest(
                action_kind=OperatorActionKind.flow_cancel.value,
                flow_id=flow_id,
            )
            surface = get_operator_surface()
            result = await surface.execute_operator_action(request)
            record_last_operator_action_result(result)
            # PR-4: Record execution roundtrip for flow_cancel so panel reflects
            # the cancellation outcome.
            try:
                from core.canonical_roundtrip import record_execution_roundtrip
                record_execution_roundtrip(
                    action_id=result.action_id,
                    action_kind=result.action_kind,
                    trace_id=result.trace_id,
                    session_id=result.runtime_session_id,
                    runtime_result=_build_roundtrip_runtime_result(result),
                )
            except Exception:
                pass
            if not result.accepted and "not found" in result.error:
                return JSONResponse(
                    content={
                        "detail": f"flow '{flow_id}' not found",
                        "authority": "OPERATOR_ROUTES_V1",
                    },
                    status_code=404,
                )
            status = 200 if result.accepted else 422
            return JSONResponse(
                content={**result.to_dict(), "authority": "OPERATOR_ROUTES_V1"},
                status_code=status,
            )
        except Exception as exc:
            logger.error("operator_flow_cancel(%s) endpoint error: %s", flow_id, exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ==================================================================
    # PR-4: Operator Action Governance Endpoints
    # ==================================================================
    #
    # These endpoints expose the PR-4 operator action governance surface:
    #   - Full operator action audit trail
    #   - Operable board projection (what is wrong, what can be done,
    #     why actions are available, last action feedback)
    #   - Android-directed action dispatch and ACK
    #   - Top-level PR-4 operable surface snapshot

    # ------------------------------------------------------------------
    # GET /api/v1/operator/actions/audit
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/actions/audit")
    async def operator_actions_audit(
        limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
        action_kind: Optional[str] = Query(None, description="Filter by action kind"),
        outcome: Optional[str] = Query(None, description="Filter by outcome"),
    ) -> JSONResponse:
        """Return the operator action audit log.

        Returns recent :class:`~core.pr4_operator_action_governance.OperatorActionAuditRecord`
        entries, newest first.  Each record carries:

        * who triggered the action (``operator_user_id``)
        * why it was allowed (``policy_evaluation``, ``policy_basis``)
        * pre-action runtime state (``pre_state``)
        * post-action runtime state (``post_state``)
        * success/failure/rollback result (``outcome``, ``error``, ``rollback_needed``)
        * downstream runtime/governance effects (``downstream_effects``)
        * Android-directed action correlation (``android_dispatch_id``, ``android_ack_received``)

        Query parameters:

        * ``limit`` — max records (default 50, max 500).
        * ``action_kind`` — filter by action kind string.
        * ``outcome`` — filter by outcome string.
        """
        try:
            from core.pr4_operator_action_governance import get_operator_action_audit_log
            records = get_operator_action_audit_log(
                limit=limit,
                action_kind=action_kind or None,
                outcome=outcome or None,
            )
            return JSONResponse(content={
                "total": len(records),
                "records": [r.to_dict() for r in records],
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("operator_actions_audit endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/board/operable-truth
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/board/operable-truth")
    async def operator_board_operable_truth() -> JSONResponse:
        """Return the PR-4 operable board projection.

        The operable-truth projection is the policy-driven operator board
        surface showing:

        * **What is wrong** — hard block count, soft degraded count, manual
          decision count, active blocker list.
        * **What can currently be done** — available actions with control_mode,
          reason, and approval requirements.
        * **Why actions are available or unavailable** — state-basis breakdown
          (hard_block_count, active_flow_count, online_device_count, etc.).
        * **Feedback/result of the last action** — last action kind, outcome,
          error, affected entities.
        * **Pending Android-directed actions** — actions dispatched to Android
          that are awaiting ACK.
        * **Unified reasoning contract** — ``runtime_decision_reasoning`` and
          ``latest_closure_reasoning`` now share the same reasoning block so
          board/operator consumers do not need to reconcile separate
          explanation schemas.

        Action availability is policy-derived — not hard-coded.
        """
        try:
            from core.pr4_operator_action_governance import build_operator_board_projection
            proj = build_operator_board_projection()
            return JSONResponse(content={
                **proj.to_dict(),
                "authority": "OPERATOR_ROUTES_V1",
                "consumption_contract_boundary": _operator_consumption_contract_boundary(),
            })
        except Exception as exc:
            logger.error("operator_board_operable_truth endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/pr4/snapshot
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/pr4/snapshot")
    async def pr4_operable_surface_snapshot(
        audit_limit: int = Query(10, ge=1, le=100, description="Recent audit records to include"),
    ) -> JSONResponse:
        """Return the PR-4 operable surface snapshot.

        The top-level PR-4 snapshot combines:

        * :class:`~core.pr4_operator_action_governance.OperatorActionBoardProjection`
          — operable truth board.
        * Recent :class:`~core.pr4_operator_action_governance.OperatorActionAuditRecord`
          entries.
        * Count of pending Android-directed actions.
        * Contract version and authority confirmation.

        Use this endpoint to verify that the PR-4 convergence layer is active
        and to inspect the current operable state of the V2 operator surface.
        """
        try:
            from core.pr4_operator_action_governance import build_pr4_operable_surface_snapshot
            snap = build_pr4_operable_surface_snapshot(recent_audit_limit=audit_limit)
            return JSONResponse(content={
                **snap.to_dict(),
                "authority": "OPERATOR_ROUTES_V1",
                "consumption_contract_boundary": _operator_consumption_contract_boundary(),
            })
        except Exception as exc:
            logger.error("pr4_operable_surface_snapshot endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # POST /api/v1/operator/actions/android-directed
    # ------------------------------------------------------------------

    @router.post("/api/v1/operator/actions/android-directed")
    async def operator_android_directed_action(body: Dict[str, Any]) -> JSONResponse:
        """Dispatch an Android-directed operator action.

        Builds an :class:`~core.pr4_operator_action_governance.AndroidDirectedActionSpec`
        for an operator action targeting a specific Android device.  The spec
        is stored as a pending action until the Android device ACKs it via the
        execution event channel.

        This endpoint represents the V2 center-side half of the Android-directed
        operator action convergence (PR-4 requirement: Android-directed actions
        are real runtime operations, not detached API requests).

        Request body fields
        -------------------
        ``action_kind`` (required)
            An :class:`~core.pr4_operator_action_governance.AndroidDirectedActionKind`
            value.
        ``device_id`` (required)
            The target Android device ID.
        ``operator_action_id``
            Optional correlation ID.  Auto-generated when empty.
        ``user_id``
            Operator user ID (default: ``"operator"``).
        ``target_flow_id``
            Optional target delegated flow ID.
        ``target_task_id``
            Optional target task ID.
        ``target_session_id``
            Optional target session ID.
        ``payload``
            Optional additional payload dict.

        Returns::

            {
              "android_dispatch_id": str,
              "action_kind": str,
              "device_id": str,
              "dispatched_at": float,
              "pending": true,
              "authority": str
            }
        """
        try:
            from core.pr4_operator_action_governance import (
                build_android_directed_action_spec,
            )

            action_kind = body.get("action_kind", "")
            device_id = body.get("device_id", "")
            if not action_kind:
                return JSONResponse(
                    content={"error": "action_kind is required", "authority": "OPERATOR_ROUTES_V1"},
                    status_code=422,
                )
            if not device_id:
                return JSONResponse(
                    content={"error": "device_id is required", "authority": "OPERATOR_ROUTES_V1"},
                    status_code=422,
                )

            spec = build_android_directed_action_spec(
                action_kind=action_kind,
                device_id=device_id,
                operator_action_id=body.get("operator_action_id") or f"opact_{uuid.uuid4().hex[:12]}",
                operator_user_id=body.get("user_id", "operator"),
                target_flow_id=body.get("target_flow_id", ""),
                target_task_id=body.get("target_task_id", ""),
                target_session_id=body.get("target_session_id", ""),
                payload=dict(body.get("payload") or {}),
            )

            return JSONResponse(content={
                **spec.to_dict(),
                "pending": True,
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("operator_android_directed_action endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # POST /api/v1/operator/actions/android-directed/{dispatch_id}/ack
    # ------------------------------------------------------------------

    @router.post("/api/v1/operator/actions/android-directed/{dispatch_id}/ack")
    async def operator_android_directed_action_ack(dispatch_id: str) -> JSONResponse:
        """Acknowledge that an Android device has executed a directed action.

        Called when a ``DEVICE_EXECUTION_EVENT`` with an ``operator_action_id``
        field is received from the Android device.  Marks the pending action as
        ACKed and removes it from the pending store.

        Path parameters
        ---------------
        ``dispatch_id``
            The ``android_dispatch_id`` from the
            :class:`~core.pr4_operator_action_governance.AndroidDirectedActionSpec`.

        Returns::

            {
              "acked": true,
              "dispatch_id": str,
              "authority": str
            }

        Returns HTTP 404 when the dispatch_id is not found in the pending store.
        """
        try:
            from core.pr4_operator_action_governance import (
                acknowledge_android_directed_action,
                get_android_directed_action_terminal_state,
            )
            acked = acknowledge_android_directed_action(dispatch_id)
            if not acked:
                terminal_state = get_android_directed_action_terminal_state(dispatch_id)
                if terminal_state.get("state") == "timed_out":
                    return JSONResponse(
                        content={
                            "detail": (
                                f"pending android action '{dispatch_id}' timed out "
                                "before ack"
                            ),
                            "dispatch_state": "timed_out",
                            "authority": "OPERATOR_ROUTES_V1",
                        },
                        status_code=409,
                    )
                return JSONResponse(
                    content={
                        "detail": f"pending android action '{dispatch_id}' not found",
                        "authority": "OPERATOR_ROUTES_V1",
                    },
                    status_code=404,
                )
            return JSONResponse(content={
                "acked": True,
                "dispatch_id": dispatch_id,
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error(
                "operator_android_directed_action_ack(%s) endpoint error: %s",
                dispatch_id,
                exc,
            )
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ==================================================================
    # PR-X: 设备 Dispatch 就绪控制面端点
    # ==================================================================
    #
    # 以下两个端点将 unified_dispatch_readiness_gate 的评估结果暴露为
    # 真正的 operator 可见面，终结"注册 gap / dispatch 拦截原因仅内部可知"
    # 的隐控平面问题。

    # ------------------------------------------------------------------
    # GET /api/v1/operator/devices/{device_id}/dispatch-readiness
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/devices/{device_id}/dispatch-readiness")
    async def device_dispatch_readiness(device_id: str) -> JSONResponse:
        """返回单台设备的 dispatch 就绪状态（结构化拦截原因）。

        数据源：:func:`~core.device_dispatch_readiness_surface.get_device_dispatch_readiness`
        → :func:`~core.unified_dispatch_readiness_gate.evaluate_dispatch_readiness`

        与 ``/api/v1/operator/devices/ecosystem/{device_id}`` 的区别
        --------------------------------------------------------------
        ecosystem 端点暴露设备的 AI/模型/无障碍就绪快照（来自
        DEVICE_STATE_SNAPSHOT 上报）。本端点暴露的是 **dispatch 门控评估**：
        注册是否完整、transport 是否在线、附接会话是否有效、能力是否满足、
        以及任何一条门控失败的具体原因。

        Returns::

            {
              "device_id": str,
              "dispatch_ready": bool,
              "registered": bool,
              "status": str,         # DispatchReadinessStatus 枚举值
              "reason": str,         # 人类可读解释
              "registration_gaps": [str, ...],   # 注册失败步骤（仅 BLOCKED_REGISTRATION_GAP 时非空）
              "attachment_state": str,
              "runtime_session_id": str | null,
              "runtime_attachment_session_id": str | null,
              "transport_alive": bool,
              "blocking_notes": [str, ...],      # 附加阻断上下文
              "surface_authority": str,
              "evaluated_at": float,
              "authority": str
            }
        """
        try:
            from core.device_dispatch_readiness_surface import get_device_dispatch_readiness
            result = get_device_dispatch_readiness(device_id)
            return JSONResponse(content={
                **result,
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error(
                "device_dispatch_readiness(%s) endpoint error: %s", device_id, exc
            )
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    # ------------------------------------------------------------------
    # GET /api/v1/operator/devices/dispatch-readiness
    # ------------------------------------------------------------------

    @router.get("/api/v1/operator/devices/dispatch-readiness")
    async def devices_dispatch_readiness_panel(
        device_ids: Optional[str] = Query(
            None,
            description="逗号分隔的设备 ID 列表（留空则枚举所有已知设备）",
        ),
    ) -> JSONResponse:
        """返回全设备 dispatch 就绪面板。

        枚举所有已知设备（来自 UDM、注册 gap 存储和状态快照存储），对每台
        设备运行 dispatch 就绪评估，返回汇总统计 + 每台设备的完整结构化
        拦截原因。

        这是注册 gap 与 dispatch gate 结果在 operator 控制面上的统一可视化
        端点。运维人员或下游监控消费者无需查阅内部日志即可得知：
        * 哪些设备因注册 gap 被拦截，gap 发生在哪个下游步骤？
        * 哪些设备因 transport 断线、附接失效、能力缺失等被拦截？
        * 哪些设备完全就绪可派发？

        Query parameters
        ----------------
        ``device_ids``
            可选，逗号分隔的设备 ID 列表。若不提供则自动枚举所有已知设备。

        Returns::

            {
              "devices": [
                {
                  "device_id": str,
                  "dispatch_ready": bool,
                  "registered": bool,
                  "status": str,
                  "reason": str,
                  "registration_gaps": [str, ...],
                  "attachment_state": str,
                  "runtime_session_id": str | null,
                  "transport_alive": bool,
                  "blocking_notes": [str, ...],
                  "evaluated_at": float
                },
                ...
              ],
              "summary": {
                "total": int,
                "dispatch_ready": int,
                "blocked_registration_gap": int,
                "blocked_stale_attachment": int,
                "blocked_transport": int,
                "blocked_capability": int,
                "blocked_session_validity": int,
                "blocked_cross_device_eligibility": int,
                "blocked_other": int,
                "not_registered": int,
                "gate_error": int,
                "total_blocked": int
              },
              "compiled_at": float,
              "authority": str
            }
        """
        try:
            from core.device_dispatch_readiness_surface import get_dispatch_readiness_panel
            explicit_ids: Optional[list] = None
            if device_ids:
                explicit_ids = [d.strip() for d in device_ids.split(",") if d.strip()]
            panel = get_dispatch_readiness_panel(device_ids=explicit_ids)
            return JSONResponse(content={
                **panel,
                "authority": "OPERATOR_ROUTES_V1",
            })
        except Exception as exc:
            logger.error("devices_dispatch_readiness_panel endpoint error: %s", exc)
            return JSONResponse(
                content={"error": str(exc), "authority": "OPERATOR_ROUTES_V1"},
                status_code=500,
            )

    return router
