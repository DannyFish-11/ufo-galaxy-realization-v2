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
