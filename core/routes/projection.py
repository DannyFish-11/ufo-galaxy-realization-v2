"""
core/routes/projection.py
==========================
Read-only RuntimeProjection endpoint for the Status Board V2.

This module exposes **two GET endpoints**:

  GET /api/v1/projection/runtime
      Returns the current RuntimeProjection assembled from live ContinuumState
      (and an optional TopologyRoutePlan if the model topology layer is
      available).

  GET /api/v1/projection/return
      Returns the current ReturnSummary (PR-10 return intelligence) alongside
      the RuntimeProjection.  The payload contains all RuntimeProjection fields
      plus a nested ``"return_intelligence"`` key populated by the
      return-intelligence adapter.

Design constraints
------------------
- **Read-only** — this router never writes state, sends commands, or triggers
  actions.  It only reads and serialises.
- **Not dashboard** — this module is part of ``core/routes/``, intentionally
  separate from ``dashboard/backend/``.
- **Graceful degradation** — if the continuum layer or topology layer is
  unavailable the endpoint returns a minimal valid projection rather than an
  error, so that the status board always has something to display.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger("Galaxy.Routes.Projection")


def create_router(service_manager=None, config=None) -> APIRouter:  # noqa: ARG001
    """Create and return the projection router.

    The ``service_manager`` and ``config`` parameters follow the same
    convention used by all other ``core/routes/`` modules and are accepted
    (but not required) to allow uniform registration in ``core/api_routes.py``.
    """
    router = APIRouter()

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime")
    async def get_runtime_projection() -> JSONResponse:
        """Return the current RuntimeProjection as JSON.

        This endpoint is **read-only**.  It assembles a
        :class:`~core.projection.RuntimeProjection` from the live
        ``ContinuumState`` (and optionally the ``TopologyRoutePlan`` if
        the model topology layer has been initialised) and returns a
        stable JSON payload.

        The Status Board V2 polls this endpoint to render all its surfaces.

        Response schema
        ---------------
        See :class:`~core.projection.RuntimeProjection` for the full field
        reference.  Every field maps directly to a surface in the status board:

        - ``tri_state_phase``        → PhaseSurface
        - ``runtime_domain``         → DomainSurface
        - ``primary_model_id``       → TopologySurface
        - ``support_model_ids``      → TopologySurface
        - ``active_weights``         → TopologySurface
        - ``active_device_ids``      → DeviceSurface
        - ``execution_stage``        → DeviceSurface
        - ``presence_intensity``     → MetricsSurface
        - ``coherence``              → MetricsSurface
        - ``collapse_tendency``      → MetricsSurface
        - ``retreat_tendency``       → MetricsSurface
        """
        payload = _assemble_projection()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/return
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/return")
    async def get_return_projection() -> JSONResponse:
        """Return the current RuntimeProjection enriched with return intelligence.

        This endpoint is **read-only**.  It returns all standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"return_intelligence"`` key containing the
        :class:`~core.return_intelligence.ReturnSummary` for the current
        continuum state.

        The ``"return_intelligence"`` key is safe for public consumers —
        it never exposes the internal ``receding`` phase.

        Response schema (additions over /runtime)
        ------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "return_intelligence": {
                "is_returning": false,
                "return_mode": "none",
                "return_action": null,
                "return_trigger": null,
                "decay_amount": 0.0,
                "reason": "no return active",
                "affects_manifest": false,
                "affects_liminal": false
              }
            }

        This endpoint is consumed by the ReturnSurface in Status Board V2
        and any other downstream systems that need return context.
        """
        payload = _assemble_projection_with_return()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/execution_policy
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/execution_policy")
    async def get_execution_policy_projection() -> JSONResponse:
        """Return the current execution-policy summary derived from live signals.

        This endpoint is **read-only** and **additive** — it does not modify
        any existing projection, continuum, or orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"execution_policy"`` key populated by the PR-11 policy schema.

        The ``"execution_policy"`` block answers:
          - What policy band applies (``observe_only`` / ``assistive`` /
            ``bounded_execute`` / ``full_execute``)?
          - What risk/action/fallback budgets are available?
          - Which executor levels are permitted?
          - Whether cross-device expansion is allowed?
          - Whether confirmation is required?

        The ``"hints"`` sub-key provides quick boolean checks for downstream
        consumers (manifest stage, liminal controllers, status board).

        This endpoint does **not** enforce the policy — enforcement is
        deferred to a follow-up PR.

        Response schema (additions over /return)
        -----------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "return_intelligence": { ... },
              "execution_policy": {
                "policy_band": "bounded_execute",
                "risk_budget": 0.5,
                "action_budget": 5,
                "fallback_budget": 2,
                "allowed_executor_levels": ["system_api", "uia", "orchestrator"],
                "cross_device_allowed": false,
                "requires_confirmation": true,
                "reason": "...",
                "can_execute": true,
                "can_expand_cross_device": false,
                "should_require_confirmation": true,
                "max_executor_level": "orchestrator"
              }
            }
        """
        payload = _assemble_projection_with_execution_policy()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/cross_device_routing
    # ------------------------------------------------------------------

    @router.get("/api/v1/execution/merge-summary")
    async def get_merge_summary() -> JSONResponse:
        """Return a read-only distributed execution merge summary.

        This endpoint is **read-only** and **additive** (PR-14).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"merge_summary"`` key populated by the PR-14 distributed merge and
        recovery schema.

        When no live merge context is available, the endpoint returns the
        pre-built :data:`~core.distributed_execution.EMPTY_MERGE_SUMMARY`
        alongside a recovery recommendation of ``no_recovery_needed``.

        Response schema (additions over /cross_device_routing)
        -------------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "merge_summary": {
                "merge_status": "success",
                "total_count": 0,
                "successful_count": 0,
                "failed_count": 0,
                "timed_out_count": 0,
                "skipped_count": 0,
                "success_rate": 0.0,
                "is_successful": false,
                "is_terminal_failure": true,
                "merged_payloads": [],
                "errors": [],
                "warnings": [],
                "recovery_recommendation": null,
                "task_id": "",
                "trace_id": "",
                "runtime_session_id": "",
                "merged_at": 0.0
              },
              "merge_hints": {
                "merge_status": "success",
                "is_successful": true,
                "is_terminal_failure": false,
                "has_errors": false,
                "has_warnings": false,
                "success_rate": 1.0,
                "has_recovery_recommendation": false,
                "recovery_posture": null,
                "total_count": 0,
                "task_id": "",
                "trace_id": ""
              }
            }
        """
        payload = _assemble_projection_with_merge_summary()
        return JSONResponse(content=payload)

    @router.get("/api/v1/projection/cross_device_routing")
    async def get_cross_device_routing_projection() -> JSONResponse:
        """Return the current cross-device routing summary derived from live signals.

        This endpoint is **read-only** and **additive** (PR-13).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"cross_device_routing"`` key populated by the PR-13 cross-device
        role and routing policy schema.

        The ``"cross_device_routing"`` block answers:
          - What routing posture is intended (``local_preferred`` /
            ``local_then_expand`` / ``remote_required`` / ``split_execution``
            / ``mirrored_observation``)?
          - Which device originated the request?
          - Which device is the primary executor?
          - Which devices are support / observer / relay / fallback?
          - Is cross-device expansion permitted by execution policy?
          - Is confirmation required before expansion?

        Response schema (additions over /execution_policy)
        ---------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "execution_policy": { ... },
              "cross_device_routing": {
                "posture": "local_preferred",
                "source_device_id": null,
                "primary_execution_device_id": null,
                "support_device_ids": [],
                "observer_device_ids": [],
                "relay_device_ids": [],
                "fallback_device_ids": [],
                "all_assignments": [],
                "runtime_domain_intent": "local",
                "expansion_allowed_by_execution_policy": false,
                "confirmation_required_before_expansion": true,
                "is_cross_device": false,
                "policy_reason": "..."
              }
            }
        """
        payload = _assemble_projection_with_cross_device_routing()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/task_semantics
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/task_semantics")
    async def get_task_semantics_projection() -> JSONResponse:
        """Return semantic step-kind hints derived from the current runtime state.

        This endpoint is **read-only** and **additive** (PR-15).  It does not
        modify any existing projection, continuum, orchestration, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"task_semantics"`` key populated by the PR-15 task-semantics schema
        and a flat ``"semantic_hints"`` quick-check dict.

        The ``"task_semantics"`` block describes the semantic step classification
        for the current idle/active task state and answers:
          - How many steps are classified and of what kind?
          - Does the task contain side-effectful steps?
          - Does the task contain cross-device steps?
          - Which steps are visible in manifest/projection surfaces?
          - Which steps emit observability highlights?

        Response schema (additions over /cross_device_routing)
        -------------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "cross_device_routing": { ... },
              "task_semantics": {
                "task_id": "",
                "trace_id": "",
                "classified_steps": [],
                "total_steps": 0,
                "has_side_effectful_steps": false,
                "has_cross_device_steps": false,
                "has_confirmation_required_steps": false,
                "has_rollback_steps": false,
                "primary_visible_steps": [],
                "observability_highlight_steps": [],
                "unresolved_count": 0,
                "is_fully_resolved": true
              },
              "semantic_hints": {
                "total_steps": 0,
                "has_side_effectful_steps": false,
                "has_cross_device_steps": false,
                ...
              }
            }
        """
        payload = _assemble_projection_with_task_semantics()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/device-formation
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/device-formation")
    async def get_device_formation_projection() -> JSONResponse:
        """Return the current device-formation summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-17).  It does not
        modify any existing projection, device manager, device router, or
        orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"device_formation"`` key populated by the PR-17 formation schema, and
        a flat ``"formation_hints"`` quick-check dict.

        The ``"device_formation"`` block makes multi-device participation
        **explicit and inspectable** and answers:
          - Which devices are in the current execution formation?
          - Which device is the source/origin?
          - Which device is the primary executor?
          - Which devices are support / observer / relay / fallback members?
          - Which device owns merge responsibility?
          - What barrier/completion posture is intended?
          - Is a multi-device formation required by policy?

        Response schema (additions over /task_semantics)
        -------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "task_semantics": { ... },
              "device_formation": {
                "schema_version": 1,
                "formation_id": "...",
                "task_id": null,
                "trace_id": null,
                "is_multi_device": false,
                "member_count": 0,
                "source_device_id": null,
                "primary_execution_device_id": null,
                "merge_owner_device_id": null,
                "barrier_posture": "wait_primary",
                "multi_device_required": false,
                "merge_confirmation_required": false,
                "fallback_available": false,
                "formation_reason": "no active formation",
                "runtime_domain_intent": "local",
                "all_member_device_ids": [],
                "fallback_device_ids": [],
                "support_device_ids": [],
                "observer_device_ids": [],
                "relay_device_ids": [],
                "policy_reason": "..."
              },
              "formation_hints": {
                "is_multi_device": false,
                "member_count": 0,
                "fallback_available": false,
                "multi_device_required": false,
                "merge_confirmation_required": false,
                "has_primary": false,
                "has_source": false,
                "has_merge_owner": false,
                "barrier_posture": "wait_primary",
                "runtime_domain_intent": "local"
              }
            }

        This endpoint is consumed by the DeviceFormationSurface in Status
        Board V2 and any downstream governance / reliability work that needs
        explicit formation context.
        """
        payload = _assemble_projection_with_device_formation()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/agent-dispatch
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/agent-dispatch")
    async def get_agent_dispatch_projection() -> JSONResponse:
        """Return the current agent-dispatch governance summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-18).  It does not
        modify any existing projection, agent bridge, command router, or
        orchestration module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"agent_dispatch"`` key populated by the PR-18 governance schema, and
        a flat ``"ownership_hints"`` quick-check dict.

        The ``"agent_dispatch"`` block makes agent ownership and handoff
        governance **explicit and inspectable** and answers:
          - Which agent role initiated the current dispatch?
          - Which role currently holds execution responsibility?
          - Who owns the final outcome?
          - Is a recovery agent active?
          - Has the handoff depth limit been exceeded?
          - Is the governing handoff edge valid per the responsibility graph?

        Response schema (additions over /device-formation)
        ---------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "device_formation": { ... },
              "agent_dispatch": {
                "schema_version": 1,
                "dispatch_role": "unassigned",
                "target_role": "unassigned",
                "handoff_valid": false,
                "ownership": {
                  "dispatch_owner": "unassigned",
                  "current_owner": "unassigned",
                  "final_outcome_owner": null,
                  "handoff_count": 0,
                  "is_recovery_active": false,
                  "is_complete": false,
                  "max_handoff_depth": 5,
                  "depth_exceeded": false,
                  "recovery_permitted": true
                },
                "trace_id": null,
                "task_id": null,
                "bridge_source": null,
                "dispatch_success": false,
                "failure_reason": "",
                "policy_reason": "..."
              },
              "ownership_hints": {
                "dispatch_owner": "unassigned",
                "current_owner": "unassigned",
                "is_recovery_active": false,
                "is_complete": false,
                "depth_exceeded": false,
                "handoff_count": 0,
                "has_final_owner": false,
                "recovery_permitted": true
              }
            }

        This endpoint is consumed by any downstream governance / reliability
        work that needs explicit agent ownership context.
        """
        payload = _assemble_projection_with_agent_dispatch()
        return JSONResponse(content=payload)

    return router


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assemble_projection() -> Dict[str, Any]:
    """Assemble a projection dict from live runtime state.

    Always returns a valid dict.  Individual sub-components (continuum, topology)
    are optional; missing components fall back to safe defaults so that the
    status board is never blocked by a partially initialised system.

    Import errors (e.g. missing optional transitive dependencies) are caught
    and result in the minimal fallback payload rather than a 500 error.
    """
    try:
        from core.projection import build_runtime_projection, ExecutionSummary
        from core.continuum.types import ContinuumPhase, ContinuumState  # noqa: F401
    except Exception as exc:
        logger.warning("Projection imports unavailable, returning minimal payload: %s", exc)
        return _minimal_fallback_payload()

    # --- 1. Continuum state ------------------------------------------------
    continuum_state = _get_continuum_state()

    # --- 2. Optional topology route plan -----------------------------------
    route_plan = _get_route_plan(continuum_state)

    # --- 3. Optional execution summary ------------------------------------
    execution_summary = _get_execution_summary()

    # --- 4. Build and serialise -------------------------------------------
    try:
        if continuum_state is None:
            return _minimal_fallback_payload()
        projection = build_runtime_projection(
            continuum_state=continuum_state,
            route_plan=route_plan,
            execution_summary=execution_summary,
            timestamp=time.time(),
        )
        return projection.to_dict()
    except Exception as exc:  # pragma: no cover
        logger.warning("Projection assembly failed, returning minimal payload: %s", exc)
        return _minimal_fallback_payload()


def _get_continuum_state():
    """Return the live ContinuumState, or a minimal silent state on failure."""
    try:
        # Try the cognitive field engine first (Block-3 integration).
        from core.cognitive.cognitive_field_engine import CognitiveFieldEngine
        engine = CognitiveFieldEngine.get_instance()
        if engine is not None and hasattr(engine, "get_continuum_state"):
            state = engine.get_continuum_state()
            if state is not None:
                return state
    except Exception:
        pass

    try:
        # Fallback: desktop presence runtime if available.
        from core.desktop_presence_runtime import get_presence_runtime
        runtime = get_presence_runtime()
        if runtime is not None and hasattr(runtime, "get_continuum_state"):
            state = runtime.get_continuum_state()
            if state is not None:
                return state
    except Exception:
        pass

    try:
        # Final fallback: minimal silent state so the board always renders.
        from core.continuum.types import ContinuumPhase, ContinuumState
        return ContinuumState(phase=ContinuumPhase.FORMLESS)
    except Exception:
        return None


def _get_route_plan(continuum_state):
    """Return the current TopologyRoutePlan, or None if topology is not ready."""
    try:
        from core.model_topology import TopologyRouter, ProviderInventory
        from core.continuum.types import RuntimeDomain

        inventory = ProviderInventory.from_config()
        router = TopologyRouter(inventory)
        domain = continuum_state.runtime_domain or RuntimeDomain.LOCAL
        return router.route(continuum_state.tri_state_phase, domain)
    except Exception:
        return None


def _get_execution_summary() -> Optional[Any]:
    """Return an ExecutionSummary if execution context is available."""
    try:
        from core.projection import ExecutionSummary

        try:
            from core.unified.device_manager import UnifiedDeviceManager
            udm = UnifiedDeviceManager.get_instance()
            if udm is None:
                return None
            online = udm.get_online_devices() if hasattr(udm, "get_online_devices") else []
            device_ids = [d.device_id for d in online] if online else []
            return ExecutionSummary(active_device_ids=device_ids)
        except Exception:
            return None
    except Exception:
        return None


def _minimal_fallback_payload() -> Dict[str, Any]:
    """Return a minimal valid projection payload for failure cases."""
    return {
        "tri_state_phase": "silent",
        "runtime_domain": None,
        "presence_intensity": None,
        "coherence": None,
        "collapse_tendency": None,
        "retreat_tendency": None,
        "primary_model_id": None,
        "support_model_ids": [],
        "active_weights": {},
        "route_reason": None,
        "active_device_ids": [],
        "execution_stage": None,
        "current_task_summary": None,
        "timestamp": time.time(),
    }


def _assemble_projection_with_return() -> Dict[str, Any]:
    """Assemble a projection dict enriched with return-intelligence data.

    Builds the standard projection first, then attaches the return summary
    derived from the live continuum state.  Always returns a valid dict with
    a ``"return_intelligence"`` key even when the return layer is unavailable.
    """
    base = _assemble_projection()

    try:
        from core.return_intelligence import build_return_summary, attach_return_summary, IDLE_RETURN_SUMMARY

        continuum_state = _get_continuum_state()
        if continuum_state is None:
            return attach_return_summary(base, IDLE_RETURN_SUMMARY)

        try:
            from core.continuum.return_engine import ReturnEngine
            engine = ReturnEngine()
            result = engine.evaluate(continuum_state)
            summary = build_return_summary(result)
        except Exception as exc:
            logger.warning("Return engine evaluation failed, using idle summary: %s", exc)
            summary = IDLE_RETURN_SUMMARY

        return attach_return_summary(base, summary)

    except Exception as exc:  # pragma: no cover
        logger.warning("Return-intelligence assembly failed, returning base projection: %s", exc)
        # Attach a minimal idle return intelligence block so consumers always find the key.
        base["return_intelligence"] = {
            "is_returning": False,
            "return_mode": "none",
            "return_action": None,
            "return_trigger": None,
            "decay_amount": 0.0,
            "reason": "return intelligence unavailable",
            "affects_manifest": False,
            "affects_liminal": False,
        }
        return base


def _assemble_projection_with_execution_policy() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the execution-policy summary.

    Builds the standard projection (with return intelligence), then derives
    and attaches the PR-11 execution policy.  Always returns a valid dict with
    an ``"execution_policy"`` key even when the policy layer is unavailable.
    """
    base = _assemble_projection_with_return()

    try:
        from core.execution_policy import (
            resolve_policy,
            attach_policy_to_projection,
            DEFAULT_CONSERVATIVE_POLICY,
        )

        phase_str = base.get("tri_state_phase")
        domain_str = base.get("runtime_domain")
        retreat = base.get("retreat_tendency")
        collapse = base.get("collapse_tendency")
        return_intel = base.get("return_intelligence")

        # Optionally pull authority role from the running continuum context
        authority_role = None
        try:
            from core.orchestration_authority import AuthorityRole
            authority_role = AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        except Exception:
            pass

        policy = resolve_policy(
            phase=phase_str,
            domain=domain_str,
            authority_role=authority_role,
            return_summary=return_intel,
            retreat_tendency=float(retreat) if retreat is not None else None,
            collapse_tendency=float(collapse) if collapse is not None else None,
        )
        return attach_policy_to_projection(base, policy)

    except Exception as exc:  # pragma: no cover
        logger.warning("Execution-policy assembly failed, attaching conservative default: %s", exc)
        from core.execution_policy.policy_summary import _fallback_summary
        base["execution_policy"] = _fallback_summary()
        return base


def _assemble_projection_with_cross_device_routing() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the cross-device routing summary.

    Builds the standard projection (with execution policy), then derives and
    attaches the PR-13 cross-device routing summary.  Always returns a valid
    dict with a ``"cross_device_routing"`` key even when the package is
    unavailable.
    """
    base = _assemble_projection_with_execution_policy()

    try:
        from core.cross_device_policy import (
            resolve_routing_summary,
            attach_cross_device_to_projection,
            IDLE_ASSIGNMENT_SUMMARY,
        )

        domain_str = base.get("runtime_domain")

        # Extract execution policy object if available
        execution_policy = base.get("execution_policy")

        # Optionally pull authority role
        authority_role = None
        try:
            from core.orchestration_authority import AuthorityRole
            authority_role = AuthorityRole.AUTHORITATIVE_ENTRYPOINT
        except Exception:
            pass

        summary = resolve_routing_summary(
            runtime_domain=domain_str,
            execution_policy=execution_policy,
            authority_role=authority_role,
        )
        return attach_cross_device_to_projection(base, summary)

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Cross-device routing assembly failed, attaching idle summary: %s", exc
        )
        try:
            from core.cross_device_policy import IDLE_ASSIGNMENT_SUMMARY
            base["cross_device_routing"] = IDLE_ASSIGNMENT_SUMMARY.to_dict()
        except Exception:
            base["cross_device_routing"] = {"posture": "undecided", "is_cross_device": False}
        return base


def _assemble_projection_with_merge_summary() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the distributed merge summary.

    Builds the standard projection (with cross-device routing), then attaches
    the PR-14 merge summary and hints.  Always returns a valid dict with a
    ``"merge_summary"`` key even when the package is unavailable.
    """
    base = _assemble_projection_with_cross_device_routing()

    try:
        from core.distributed_execution import (
            EMPTY_MERGE_SUMMARY,
            attach_merge_summary_to_projection,
            get_merge_hints,
        )

        # Use the empty summary as a safe idle default — no live merge
        # context is available at projection-query time.  Future code that
        # does perform a live merge should store the summary in a registry
        # and retrieve it here.
        summary = EMPTY_MERGE_SUMMARY
        result = attach_merge_summary_to_projection(base, summary)
        result["merge_hints"] = get_merge_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Merge-summary assembly failed, attaching empty placeholder: %s", exc
        )
        base["merge_summary"] = {
            "merge_status": "failed",
            "total_count": 0,
            "successful_count": 0,
            "failed_count": 0,
            "timed_out_count": 0,
        }
        base["merge_hints"] = {
            "merge_status": "failed",
            "is_successful": False,
            "is_terminal_failure": True,
        }
        return base


def _assemble_projection_with_task_semantics() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-15 task semantic summary.

    Builds the standard projection (with merge summary), then attaches
    the task-semantics summary and hints.  Always returns a valid dict with
    ``"task_semantics"`` and ``"semantic_hints"`` keys even when the package
    is unavailable.
    """
    base = _assemble_projection_with_merge_summary()

    try:
        from core.task_semantics import (
            EMPTY_SEMANTIC_SUMMARY,
            attach_semantic_summary_to_projection,
            get_semantic_hints,
        )

        # Use the empty summary as the idle default — no active task context
        # is available at projection-query time.  Future code that maintains
        # a live task context registry should retrieve the appropriate summary
        # here.
        summary = EMPTY_SEMANTIC_SUMMARY
        result = attach_semantic_summary_to_projection(base, summary)
        result["semantic_hints"] = get_semantic_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Task-semantics assembly failed, attaching empty placeholder: %s", exc
        )
        base["task_semantics"] = {
            "task_id": "",
            "trace_id": "",
            "classified_steps": [],
            "total_steps": 0,
            "has_side_effectful_steps": False,
            "has_cross_device_steps": False,
            "unresolved_count": 0,
            "is_fully_resolved": True,
        }
        base["semantic_hints"] = {
            "total_steps": 0,
            "has_side_effectful_steps": False,
            "has_cross_device_steps": False,
        }
        return base


def _assemble_projection_with_device_formation() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-17 device-formation summary.

    Builds the standard projection (with task semantics), then derives and
    attaches the device-formation summary and hints.  Always returns a valid
    dict with ``"device_formation"`` and ``"formation_hints"`` keys even when
    the package is unavailable.
    """
    base = _assemble_projection_with_task_semantics()

    try:
        from core.device_formation import (
            IDLE_FORMATION_SUMMARY,
            attach_formation_to_projection,
            get_formation_hints,
            resolve_formation_summary,
        )

        domain_str = base.get("runtime_domain")

        # Seed from cross-device routing summary if present
        cross_device_routing = base.get("cross_device_routing", {})
        routing_summary = cross_device_routing if isinstance(cross_device_routing, dict) else {}

        summary = resolve_formation_summary(
            runtime_domain=domain_str,
            cross_device_routing_summary=routing_summary,
            execution_policy=base.get("execution_policy"),
        )
        result = attach_formation_to_projection(base, summary)
        result["formation_hints"] = get_formation_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Device-formation assembly failed, attaching idle placeholder: %s", exc
        )
        base["device_formation"] = {
            "schema_version": 1,
            "formation_id": "empty",
            "task_id": None,
            "trace_id": None,
            "is_multi_device": False,
            "member_count": 0,
            "source_device_id": None,
            "primary_execution_device_id": None,
            "merge_owner_device_id": None,
            "barrier_posture": "wait_primary",
            "multi_device_required": False,
            "merge_confirmation_required": False,
            "fallback_available": False,
            "formation_reason": "no active formation",
            "runtime_domain_intent": "local",
            "all_member_device_ids": [],
            "fallback_device_ids": [],
            "support_device_ids": [],
            "observer_device_ids": [],
            "relay_device_ids": [],
            "policy_reason": "idle default",
        }
        base["formation_hints"] = {
            "is_multi_device": False,
            "member_count": 0,
            "fallback_available": False,
            "multi_device_required": False,
            "merge_confirmation_required": False,
            "has_primary": False,
            "has_source": False,
            "has_merge_owner": False,
            "barrier_posture": "wait_primary",
            "runtime_domain_intent": "local",
        }
        return base


def _assemble_projection_with_agent_dispatch() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-18 agent-dispatch governance summary.

    Builds the device-formation projection (which includes all previous layers),
    then derives and attaches the agent-dispatch governance summary and ownership
    hints.  Always returns a valid dict with ``"agent_dispatch"`` and
    ``"ownership_hints"`` keys even when the package is unavailable.
    """
    base = _assemble_projection_with_device_formation()

    try:
        from core.agent_governance import (
            IDLE_DISPATCH_SUMMARY,
            attach_dispatch_summary_to_projection,
            get_ownership_hints,
            resolve_dispatch_summary,
        )

        # Seed from formation/runtime context available in the base projection
        runtime_domain = base.get("runtime_domain", "local")
        device_formation = base.get("device_formation", {})
        is_multi_device = (
            device_formation.get("is_multi_device", False)
            if isinstance(device_formation, dict)
            else False
        )

        # Choose dispatch role hint based on available context
        dispatch_role_str = "local_assistant" if not is_multi_device else "planner"
        target_role_str = (
            "remote_specialist" if is_multi_device else "executor"
        )

        summary = resolve_dispatch_summary(
            dispatch_role_str=dispatch_role_str,
            target_role_str=target_role_str,
            dispatch_success=False,  # idle — no live dispatch in projection
        )
        result = attach_dispatch_summary_to_projection(base, summary)
        result["ownership_hints"] = get_ownership_hints(summary.ownership)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Agent-dispatch governance assembly failed, attaching idle placeholder: %s", exc
        )
        base["agent_dispatch"] = {
            "schema_version": 1,
            "dispatch_role": "unassigned",
            "target_role": "unassigned",
            "handoff_valid": False,
            "ownership": {
                "schema_version": 1,
                "dispatch_owner": "unassigned",
                "current_owner": "unassigned",
                "final_outcome_owner": None,
                "handoff_count": 0,
                "is_recovery_active": False,
                "is_complete": False,
                "max_handoff_depth": 5,
                "depth_exceeded": False,
                "recovery_permitted": True,
                "trace_id": None,
                "task_id": None,
                "last_handoff_reason": "idle",
                "policy_reason": "idle default",
            },
            "trace_id": None,
            "task_id": None,
            "bridge_source": None,
            "dispatch_success": False,
            "failure_reason": "",
            "policy_reason": "idle default",
        }
        base["ownership_hints"] = {
            "dispatch_owner": "unassigned",
            "current_owner": "unassigned",
            "is_recovery_active": False,
            "is_complete": False,
            "depth_exceeded": False,
            "handoff_count": 0,
            "has_final_owner": False,
            "recovery_permitted": True,
        }
        return base
