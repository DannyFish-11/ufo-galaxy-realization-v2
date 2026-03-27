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

from fastapi import APIRouter, Request
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

    # ------------------------------------------------------------------
    # GET /api/v1/projection/routing-explanation
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/routing-explanation")
    async def get_routing_explanation_projection() -> JSONResponse:
        """Return the current routing explanation summary for the active runtime state.

        This endpoint is **read-only** and **additive** (PR-21).  It does not
        modify any existing projection, router, execution policy, or device
        module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"routing_explanation"`` key populated by the PR-21 routing
        explanation schema, and a flat ``"explanation_hints"`` quick-check
        dict.

        The ``"routing_explanation"`` block makes the routing decision basis
        **explicit and inspectable** and answers:
          - Which device/route was selected as the primary target?
          - What decision factors drove the choice (policy, health, capability,
            latency, availability, authority role, fallback)?
          - How confident is the system in this routing decision?
          - Which candidates were rejected and why?
          - Is a fallback plan available?
          - Which agent role owns this routing decision?
          - What execution-policy band constrained the route options?

        Response schema (additions over /agent-dispatch)
        -------------------------------------------------
        .. code-block:: json

            {
              "tri_state_phase": "...",
              ...,
              "agent_dispatch": { ... },
              "routing_explanation": {
                "schema_version": 1,
                "route_target": null,
                "decision_basis_list": [],
                "confidence": {
                  "score": 0.0,
                  "band": "undetermined",
                  "basis_count": 0,
                  "accepted_factor_count": 0,
                  "rejected_factor_count": 0,
                  "contributing_factors": [],
                  "reason": "no basis entries — undetermined confidence"
                },
                "rejected_alternatives": [],
                "fallback_plan": null,
                "owner_agent": null,
                "owner_component": "routing_explanation",
                "policy_posture": "undecided",
                "policy_band": null,
                "policy_reason": "no routing decision recorded",
                "is_cross_device": false,
                "has_fallback": false,
                "task_id": null,
                "trace_id": null
              },
              "explanation_hints": {
                "route_target": null,
                "policy_posture": "undecided",
                "policy_band": null,
                "confidence_score": 0.0,
                "confidence_band": "undetermined",
                "is_cross_device": false,
                "has_fallback": false,
                "has_rejected_alternatives": false,
                "rejected_count": 0,
                "basis_count": 0,
                "owner_agent": null
              }
            }

        This endpoint is the primary read-only integration point for the
        PR-21 routing explanation layer.  Downstream governance tooling,
        status boards, and debugging utilities should consume this endpoint
        to inspect why the current routing decision was made.
        """
        payload = _assemble_projection_with_routing_explanation()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/governance
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/governance")
    async def get_governance_projection() -> JSONResponse:
        """Return the current governance-enriched projection summary (PR-26).

        This endpoint is **read-only** and **additive** (PR-26).  It does not
        modify any existing projection, execution, readiness, fallback, or
        trace module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus a nested
        ``"governance"`` key populated by the PR-26 governance assembly layer,
        and a flat ``"governance_hints"`` quick-check dict.

        The ``"governance"`` block makes execution governance state
        **explicit and inspectable** and answers:
          - What execution intent is active (action_level, mode, target)?
          - Is the system ready to execute (readiness status, policy band)?
          - Was a fallback decision made (outcome, fallback_path)?
          - What is the execution lifecycle trace (stages, final_status)?
          - What tri-state phase and runtime domain was active at assembly time?
          - Is governance data available at all (governance_available)?

        This endpoint is the primary read-only integration point for the
        PR-26 projection assembly governance layer.  Downstream governance
        tooling, status boards, and debugging utilities should consume this
        endpoint to inspect the current governance posture in projection form.
        """
        payload = _assemble_projection_with_governance()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime-governance
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime-governance")
    async def get_runtime_governance_snapshot() -> JSONResponse:
        """Return the unified runtime governance snapshot (PR-27).

        This endpoint is **read-only** and **additive** (PR-27).  It does not
        modify any existing projection, execution, readiness, fallback, trace,
        or projection governance module.

        The response contains the unified
        :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        as a serialised JSON payload.  The snapshot assembles the complete
        current runtime posture — including tri-state phase, runtime domain,
        execution intent (PR-22), readiness/policy posture (PR-23), fallback
        trace (PR-24), execution lifecycle trace (PR-25), and projection
        governance data (PR-26) — into one canonical, stable object.

        This is the canonical read-only surface for the runtime governance
        snapshot and the primary integration point for downstream surfaces
        (status boards, mesh/session work, device handoff) that need a
        single unified governance view.

        The ``"snapshot"`` block answers:
          - What tri-state phase is the system currently in?
          - What runtime domain is active or intended?
          - What governance posture applies across intent/readiness/fallback/trace?
          - What execution lifecycle summary is currently available?
          - What projection-governance summary is currently available?
          - Is governance data available at all (governance_available)?
          - What is the top-level posture (execute / observe / blocked / degraded)?

        Response schema
        ---------------
        See :class:`~core.runtime_governance.snapshot.RuntimeGovernanceSnapshot`
        for the full field reference.
        """
        payload = _assemble_runtime_governance_snapshot_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/policy-alignment
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/policy-alignment")
    async def get_policy_alignment() -> JSONResponse:
        """Return the Execution Policy Alignment Surface (PR-28).

        This endpoint is **read-only** and **additive** (PR-28).  It does not
        modify any existing projection, execution, readiness, fallback, trace,
        governance, or dispatch module.

        The response contains the canonical
        :class:`~core.policy.alignment_surface.ExecutionPolicyAlignmentSummary`
        as a serialised JSON payload.  The summary answers, in one narrow
        read-only structure:

          - Are runtime policy, readiness policy, fallback posture,
            dispatch/handoff posture, and projection governance in agreement?
          - If they are not aligned, where is the mismatch?
          - Is the current posture local-preferred, local-then-expand,
            remote-required, blocked, degraded, or confirmation-gated?
          - What policy hints should downstream status surfaces, debugging
            tools, and later mesh/session work consume?

        This is the "policy explanation" layer that sits above existing
        governance summaries and answers *why* the system chose a particular
        route/posture.

        Response schema
        ---------------
        See :class:`~core.policy.alignment_surface.ExecutionPolicyAlignmentSummary`
        for the full field reference.

        Top-level keys:
          - ``alignment_id``           — unique ID for this assessment
          - ``aligned``                — True when all dimensions agree
          - ``blocked``                — True when any dimension signals a block
          - ``degraded``               — True when operating in degraded mode
          - ``confirmation_required``  — True when confirmation is required
          - ``policy_posture``         — resolved posture string
          - ``mismatches``             — list of detected mismatches
          - ``alignment_hints``        — quick-access boolean/string hints
          - ``runtime_policy_summary`` — per-dimension runtime policy view
          - ``readiness_policy_summary`` — per-dimension readiness policy view
          - ``fallback_policy_summary``  — per-dimension fallback posture view
          - ``dispatch_policy_summary``  — per-dimension dispatch/handoff view
          - ``projection_policy_summary`` — per-dimension projection governance view
        """
        payload = _assemble_policy_alignment_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/memberships  (PR-32)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/memberships")
    async def get_mesh_memberships() -> JSONResponse:
        """Return canonical Mesh Membership contracts for all registered devices.

        This endpoint is **read-only** and **additive** (PR-32).  It does not
        modify any existing registry, projection, or orchestration module.

        The response contains a ``"memberships"`` list where each entry is a
        fully serialised :class:`~contracts.mesh_membership.MeshMembership`
        contract derived from the current
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.

        This is the canonical answer to:

            *"How does each registered device participate in the mesh/body,
            and what is its formal role and authority?"*

        Example response::

            {
              "mesh_id": "default_mesh",
              "total": 2,
              "memberships": [
                {
                  "membership_id": "...",
                  "mesh_id": "default_mesh",
                  "member_device_id": "phone_001",
                  "roles": ["primary", "source"],
                  "authority_scope": "mesh_authority",
                  "routing_intent": "undecided",
                  ...
                },
                ...
              ]
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            registry = get_body_mesh_registry()
            memberships = registry.get_mesh_memberships(mesh_id="default_mesh")
            payload = {
                "mesh_id": "default_mesh",
                "total": len(memberships),
                "memberships": [m.to_dict() for m in memberships],
            }
        except Exception as exc:
            payload = {
                "mesh_id": "default_mesh",
                "total": 0,
                "memberships": [],
                "error": str(exc),
            }
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/session  (PR-33)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/session")
    async def get_mesh_session() -> JSONResponse:
        """Return a canonical Mesh Session contract for the current registry state.

        This endpoint is **read-only** and **additive** (PR-33).  It does not
        modify any existing registry, projection, or orchestration module.

        The response contains a fully serialised :class:`~contracts.mesh_session.MeshSession`
        contract derived from the current
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.

        This is the canonical answer to:

            *"When multiple devices cooperate on one task flow, what is the
            canonical session object that represents that cooperation?"*

        Example response::

            {
              "session_id": "msess_...",
              "status": "pending",
              "source_device_id": "phone_001",
              "primary_device_id": "tablet_002",
              "participants": [...],
              "subtask_assignments": [],
              "multi_device_required": true,
              ...
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            registry = get_body_mesh_registry()
            session = registry.get_mesh_session(mesh_id="default_mesh")
            if session is None:
                from contracts.mesh_session import build_mesh_session
                session = build_mesh_session(mesh_id="default_mesh")
            payload = session.to_dict()
        except Exception as exc:
            try:
                from contracts.mesh_session import build_mesh_session, MeshSessionStatus
                session = build_mesh_session(mesh_id="default_mesh")
                payload = session.to_dict()
                payload["error"] = str(exc)
            except Exception as inner_exc:
                payload = {
                    "session_id": "",
                    "status": "unknown",
                    "error": str(exc),
                    "inner_error": str(inner_exc),
                }
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # POST /api/v1/runtime/takeover  (PR-34)
    # ------------------------------------------------------------------

    @router.post("/api/v1/runtime/takeover")
    async def runtime_local_takeover(request: Request) -> JSONResponse:
        """Accept a handoff envelope and execute the local takeover path.

        This endpoint is the canonical **target-side local takeover entry
        point** introduced in PR-34.  It:

        1. Reads the incoming JSON body as a handoff envelope (or legacy
           payload dict).
        2. Normalises it to a
           :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`.
        3. Runs the target-side takeover path via
           :func:`~core.runtime.target_takeover.execute_local_takeover`.
        4. Returns a serialised
           :class:`~contracts.local_takeover_result.LocalTakeoverResult`.

        The endpoint degrades gracefully: if the body cannot be parsed or the
        execution path is unavailable, a minimal failure result is returned
        with ``success: false`` and a ``reason`` field.

        Example request body (Handoff Envelope v2)::

            {
              "trace_id": "trace_abc",
              "task_id": "task_001",
              "session_id": "sess_xyz",
              "task_spec": {
                "tool_name": "screenshot",
                "args": {}
              }
            }

        Example response::

            {
              "result_id": "...",
              "trace_id": "trace_abc",
              "success": true,
              "status": "succeeded",
              "result": { "action_taken": "...", ... },
              "execution_trace": { ... },
              ...
            }
        """
        payload: Any = None
        try:
            payload = await request.json()
        except Exception as exc:
            logger.warning("runtime_local_takeover: failed to parse body: %s", exc)

        try:
            from core.runtime.target_takeover import execute_local_takeover
            result = execute_local_takeover(
                payload,
                capture_governance=True,
                capture_policy_alignment=False,
            )
            result_dict = result.to_dict() if hasattr(result, "to_dict") else {}
        except Exception as exc:
            logger.warning(
                "runtime_local_takeover: execute_local_takeover raised: %s", exc
            )
            try:
                from contracts.local_takeover_result import failure_result, LocalTakeoverStatus
                result = failure_result(
                    reason=f"internal_error:{exc}",
                    status=LocalTakeoverStatus.failed,
                )
                result_dict = result.to_dict()
            except Exception as inner_exc:
                result_dict = {
                    "success": False,
                    "status": "failed",
                    "reason": f"internal_error:{exc}",
                    "inner_error": str(inner_exc),
                }
        return JSONResponse(content=result_dict)

    # ------------------------------------------------------------------
    # GET /api/v1/runtime/source-dispatch-summary  (PR-35)
    # ------------------------------------------------------------------

    @router.get("/api/v1/runtime/source-dispatch-summary")
    async def get_source_dispatch_summary() -> JSONResponse:
        """Return a read-only source dispatch orchestration summary.

        This endpoint is the canonical **source-side dispatch projection**
        introduced in PR-35.  It exposes a
        :class:`~contracts.source_dispatch.SourceDispatchSummary` by:

        1. Fetching available governance/policy/mesh context signals.
        2. Invoking :func:`~core.runtime.source_dispatch_orchestrator.build_source_dispatch_plan`
           to evaluate the current dispatch posture without executing.
        3. Returning a compact :class:`~contracts.source_dispatch.SourceDispatchSummary`.

        The endpoint is **read-only** (GET) and never triggers execution.
        It degrades gracefully when context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "dispatch_id": "...",
              "trace_id": null,
              "mode": "local",
              "success": false,
              "decision_reason": "default_local",
              "target_device_id": null,
              "error_count": 0,
              "has_execution_trace": false,
              "has_takeover_result": false,
              "has_mesh_session": false,
              "timestamp": 1700000000.0
            }
        """
        try:
            from core.runtime.source_dispatch_orchestrator import build_source_dispatch_plan
            from contracts.source_dispatch import build_source_dispatch_summary

            plan = build_source_dispatch_plan()
            summary = build_source_dispatch_summary(
                dispatch_id=plan.dispatch_id,
                trace_id=plan.trace_id,
                task_id=plan.task_id,
                session_id=plan.session_id,
                mode=plan.mode,
                success=plan.ready,
                decision_reason=(
                    plan.readiness_notes[0] if plan.readiness_notes else None
                ),
                target_device_id=(
                    plan.selected_target.target_device_id
                    if plan.selected_target
                    else None
                ),
                has_mesh_session=plan.mesh_session is not None,
            )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning(
                "get_source_dispatch_summary: failed to build summary: %s", exc
            )
            original_exc = exc
            try:
                from contracts.source_dispatch import SourceDispatchSummary, SourceDispatchMode

                fallback = SourceDispatchSummary(
                    mode=SourceDispatchMode.unknown,
                    success=False,
                    decision_reason=f"summary_error:{original_exc}",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "mode": "unknown",
                        "success": False,
                        "decision_reason": f"summary_error:{original_exc}",
                        "fallback_error": str(fallback_exc),
                        "timestamp": _time.time(),
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/runtime/result-merge-summary  (PR-36)
    # ------------------------------------------------------------------

    @router.get("/api/v1/runtime/result-merge-summary")
    async def get_result_merge_summary() -> JSONResponse:
        """Return a read-only cross-runtime result merge summary.

        This endpoint is the canonical **cross-runtime merge projection**
        introduced in PR-36.  It exposes a
        :class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`
        representing the current merge posture.  No execution is triggered.

        The endpoint is **read-only** (GET) and degrades gracefully when
        context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "merge_id": "...",
              "trace_id": null,
              "merge_policy": "primary_wins",
              "success": false,
              "partial": false,
              "fallback_applied": false,
              "unit_count": 0,
              "succeeded_unit_count": 0,
              "failed_unit_count": 0,
              "conflict_count": 0,
              "error_count": 0,
              "has_merged_output": false,
              "merge_reason": "no_active_merge",
              "timestamp": 1700000000.0
            }
        """
        try:
            from contracts.cross_runtime_result_merge import (
                build_result_merge_summary,
                ResultMergePolicy,
            )

            summary = build_result_merge_summary(
                merge_policy=ResultMergePolicy.primary_wins,
                success=False,
                partial=False,
                fallback_applied=False,
                unit_count=0,
                succeeded_unit_count=0,
                failed_unit_count=0,
                conflict_count=0,
                error_count=0,
                has_merged_output=False,
                merge_reason="no_active_merge",
            )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning(
                "get_result_merge_summary: failed to build summary: %s", exc
            )
            try:
                from contracts.cross_runtime_result_merge import ResultMergeSummary, ResultMergePolicy

                fallback = ResultMergeSummary(
                    merge_policy=ResultMergePolicy.unknown,
                    success=False,
                    merge_reason="summary_unavailable",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning(
                    "get_result_merge_summary: fallback construction failed: %s", fallback_exc
                )
                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "merge_policy": "unknown",
                        "success": False,
                        "merge_reason": "summary_unavailable",
                        "timestamp": _time.time(),
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/mesh/coordinator-summary  (PR-37)
    # ------------------------------------------------------------------

    @router.get("/api/v1/mesh/coordinator-summary")
    async def get_mesh_coordinator_summary() -> JSONResponse:
        """Return a read-only mesh session coordinator summary.

        This endpoint is the canonical **mesh session coordinator projection**
        introduced in PR-37.  It exposes a
        :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`
        representing the current coordination posture.  No execution is
        triggered.

        The summary is derived from the live
        :class:`~core.mesh.body_mesh_registry.BodyMeshRegistry` state.
        The endpoint is **read-only** (GET) and degrades gracefully when
        context is unavailable.

        Example response::

            {
              "summary_id": "...",
              "coordinator_id": "...",
              "session_id": null,
              "mesh_id": "default_mesh",
              "trace_id": null,
              "status": "pending",
              "participant_count": 0,
              "assignment_count": 0,
              "pending_count": 0,
              "completed_count": 0,
              "failed_count": 0,
              "barrier_status": "unknown",
              "merge_owner_device_id": null,
              "has_result_merge_summary": false,
              "timestamp": 1700000000.0
            }
        """
        try:
            from core.mesh.body_mesh_registry import get_body_mesh_registry
            from contracts.mesh_session_coordinator import build_coordinator_summary

            registry = get_body_mesh_registry()
            coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
            if coordinator is not None:
                summary = build_coordinator_summary(coordinator=coordinator)
            else:
                summary = build_coordinator_summary(
                    mesh_id="default_mesh",
                )
            return JSONResponse(content=summary.to_dict())
        except Exception as exc:
            logger.warning(
                "get_mesh_coordinator_summary: failed to build summary: %s", exc
            )
            try:
                from contracts.mesh_session_coordinator import (
                    MeshSessionCoordinatorSummary,
                    MeshCoordinatorStatus,
                )
                import time as _time

                fallback = MeshSessionCoordinatorSummary(
                    status=MeshCoordinatorStatus.unknown,
                    mesh_id="default_mesh",
                )
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning(
                    "get_mesh_coordinator_summary: fallback construction failed: %s",
                    fallback_exc,
                )
                return JSONResponse(
                    content={
                        "summary_id": str(_uuid.uuid4()),
                        "status": "unknown",
                        "mesh_id": "default_mesh",
                        "timestamp": _time.time(),
                    }
                )

    @router.get("/api/v1/projection/runtime/multi-device")
    async def get_multi_device_runtime_projection() -> JSONResponse:
        """Return the unified multi-device runtime projection.

        This endpoint is the canonical **unified multi-device runtime projection**
        introduced in PR-38.  It assembles a
        :class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`
        that aggregates state across all device, host, mesh, session, dispatch,
        handoff, coordination, and result contracts (PR-29–PR-37) into a single
        read-only projection.

        The endpoint is **read-only** (GET), never modifies state, and degrades
        gracefully when individual sub-components are unavailable.

        Example response::

            {
              "projection_id": "mdrt_proj_abc123def456",
              "generated_at": 1700000000.0,
              "runtime_devices": [...],
              "runtime_hosts": [...],
              "mesh_memberships": [...],
              "mesh_sessions": [...],
              "source_dispatches": [],
              "handoff_summaries": [],
              "takeover_summaries": [],
              "coordinator_summaries": [...],
              "merged_results": [],
              "governance_snapshot": null,
              "policy_alignment": null,
              "metadata": {}
            }
        """
        try:
            from contracts.multi_device_runtime_projection import (
                build_multi_device_runtime_projection,
            )
            from core.mesh.body_mesh_registry import get_body_mesh_registry

            registry = get_body_mesh_registry()

            # --- runtime devices (PR-29) ---
            runtime_devices: list = []
            try:
                from contracts.registered_runtime_device import build_registered_runtime_device
                from core.unified.device_manager import UnifiedDeviceManager

                udm = UnifiedDeviceManager.get_instance()
                if udm is not None:
                    for dev in (udm.get_all_devices() or []):
                        try:
                            from contracts.registered_runtime_device import from_udm_device
                            runtime_devices.append(from_udm_device(dev).to_dict())
                        except Exception:
                            pass
            except Exception as exc:
                logger.debug("multi-device projection: devices unavailable: %s", exc)

            # --- runtime hosts (PR-30) ---
            runtime_hosts: list = []
            try:
                from contracts.local_runtime_host import from_registered_runtime_device as host_from_device

                for dev_dict in runtime_devices:
                    try:
                        runtime_hosts.append(host_from_device(dev_dict).to_dict())
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("multi-device projection: hosts unavailable: %s", exc)

            # --- mesh memberships (PR-32) ---
            mesh_memberships: list = []
            try:
                memberships = registry.get_mesh_memberships()
                for m in (memberships or []):
                    try:
                        d = m.to_dict() if hasattr(m, "to_dict") else dict(m)
                        mesh_memberships.append(d)
                    except Exception:
                        pass
            except Exception as exc:
                logger.debug("multi-device projection: memberships unavailable: %s", exc)

            # --- mesh sessions (PR-33) ---
            mesh_sessions: list = []
            try:
                session = registry.get_mesh_session(mesh_id="default_mesh")
                if session is not None:
                    mesh_sessions.append(
                        session.to_dict() if hasattr(session, "to_dict") else dict(session)
                    )
            except Exception as exc:
                logger.debug("multi-device projection: mesh session unavailable: %s", exc)

            # --- coordinator summaries (PR-37) ---
            coordinator_summaries: list = []
            try:
                coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
                if coordinator is not None:
                    from contracts.mesh_session_coordinator import build_coordinator_summary
                    summary = build_coordinator_summary(coordinator=coordinator)
                    coordinator_summaries.append(summary.to_dict())
            except Exception as exc:
                logger.debug("multi-device projection: coordinator unavailable: %s", exc)

            projection = build_multi_device_runtime_projection(
                runtime_devices=runtime_devices,
                runtime_hosts=runtime_hosts,
                mesh_memberships=mesh_memberships,
                mesh_sessions=mesh_sessions,
                coordinator_summaries=coordinator_summaries,
            )
            return JSONResponse(content=projection.to_dict())

        except Exception as exc:
            logger.warning(
                "get_multi_device_runtime_projection: failed to assemble projection: %s",
                exc,
            )
            try:
                from contracts.multi_device_runtime_projection import (
                    MultiDeviceRuntimeProjection,
                )

                fallback = MultiDeviceRuntimeProjection()
                return JSONResponse(content=fallback.to_dict())
            except Exception as fallback_exc:
                import uuid as _uuid
                import time as _time

                logger.warning(
                    "get_multi_device_runtime_projection: fallback construction failed: %s",
                    fallback_exc,
                )
                return JSONResponse(
                    content={
                        "projection_id": f"mdrt_proj_{_uuid.uuid4().hex[:12]}",
                        "generated_at": _time.time(),
                        "runtime_devices": [],
                        "runtime_hosts": [],
                        "mesh_memberships": [],
                        "mesh_sessions": [],
                        "source_dispatches": [],
                        "handoff_summaries": [],
                        "takeover_summaries": [],
                        "coordinator_summaries": [],
                        "merged_results": [],
                        "governance_snapshot": None,
                        "policy_alignment": None,
                        "runtime_recovery": None,
                        "metadata": {},
                    }
                )

    # ------------------------------------------------------------------
    # GET /api/v1/projection/runtime/recovery
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/runtime/recovery")
    async def get_runtime_recovery_posture() -> JSONResponse:
        """Return the current runtime recovery and reconciliation posture.

        This endpoint is the canonical **read-only** advisory surface for
        recovery/reconciliation state introduced in PR-39.  It derives a
        :class:`~contracts.runtime_recovery_reconciliation.RuntimeReconciliationState`
        from the unified multi-device runtime projection and returns it as JSON.

        Example response::

            {
              "reconciliation_id": "rrec_...",
              "status": "resolved",
              "incident_count": 0,
              "participant_count": 0,
              "replay_required": false,
              "resume_allowed": false,
              "merge_confirmation_required": false,
              "has_barrier": false,
              "reason": "no incidents",
              ...
            }

        Returns
        -------
        JSONResponse
            A compact recovery summary dict.  Always returns 200; individual
            sub-component failures are logged and produce minimal safe defaults.
        """
        try:
            from contracts.runtime_recovery_reconciliation import (
                from_multi_device_projection,
                build_recovery_summary,
                RecoveryStatus,
            )

            # Attempt to get the projection dict from the multi-device projection
            projection_dict: Dict[str, Any] = {}
            try:
                from contracts.multi_device_runtime_projection import (
                    build_multi_device_runtime_projection,
                )
                projection_obj = build_multi_device_runtime_projection()
                projection_dict = projection_obj.to_dict()
            except Exception as exc:
                logger.debug("get_runtime_recovery_posture: projection unavailable: %s", exc)

            reconciliation = from_multi_device_projection(projection_dict)
            summary = build_recovery_summary(
                incidents=list(reconciliation.incidents),
                reconciliation=reconciliation,
            )
            return JSONResponse(content=summary.to_dict())

        except Exception as exc:
            logger.warning(
                "get_runtime_recovery_posture: failed to assemble recovery posture: %s",
                exc,
            )
            import uuid as _uuid2
            import time as _time2

            return JSONResponse(
                content={
                    "summary_id": f"rrsum_{_uuid2.uuid4().hex[:10]}",
                    "generated_at": _time2.time(),
                    "overall_status": "pending",
                    "incident_count": 0,
                    "resolved_incident_count": 0,
                    "pending_incident_count": 0,
                    "needs_intervention_count": 0,
                    "replay_required": False,
                    "resume_allowed": False,
                    "merge_confirmation_required": False,
                    "has_barrier": False,
                    "recommended_action_types": [],
                    "most_recent_incident_type": None,
                    "most_recent_recovery_id": None,
                    "reason": "recovery posture unavailable",
                    "metadata": {},
                }
            )

    @router.get("/api/v1/projection/runtime/session-snapshot")
    async def get_runtime_session_snapshot() -> JSONResponse:
        """Return a durable runtime session snapshot summary.

        This endpoint is the canonical **read-only** surface for the
        Durable Runtime Session Snapshot Contract introduced in PR-40.
        It derives a :class:`~contracts.runtime_session_snapshot.RuntimeSessionSnapshot`
        from the unified multi-device runtime projection (PR-38) and returns a
        compact summary as JSON.

        Example response::

            {
              "summary_id": "rsnsum_...",
              "snapshot_id": "rsnap_...",
              "session_id": "",
              "status": "unknown",
              "runtime_device_count": 0,
              "has_dispatch_state": false,
              "has_recovery_state": false,
              ...
            }

        Returns
        -------
        JSONResponse
            A compact session snapshot summary dict.  Always returns 200;
            individual sub-component failures are logged and produce safe defaults.
        """
        try:
            from contracts.runtime_session_snapshot import (
                from_multi_device_runtime_projection,
                build_runtime_session_snapshot_summary,
            )

            # Attempt to get the multi-device projection
            projection_dict: Dict[str, Any] = {}
            try:
                from contracts.multi_device_runtime_projection import (
                    build_multi_device_runtime_projection,
                )
                projection_obj = build_multi_device_runtime_projection()
                projection_dict = projection_obj.to_dict()
            except Exception as exc:
                logger.debug(
                    "get_runtime_session_snapshot: projection unavailable: %s", exc
                )

            snapshot = from_multi_device_runtime_projection(projection_dict)
            summary = build_runtime_session_snapshot_summary(snapshot)
            return JSONResponse(content=summary.to_dict())

        except Exception as exc:
            logger.warning(
                "get_runtime_session_snapshot: failed to assemble snapshot: %s",
                exc,
            )
            import uuid as _uuid_fallback
            import time as _time_fallback

            return JSONResponse(
                content={
                    "summary_id": f"rsnsum_{_uuid_fallback.uuid4().hex[:10]}",
                    "snapshot_id": None,
                    "session_id": "",
                    "trace_id": None,
                    "task_id": None,
                    "mesh_session_id": None,
                    "source_device_id": None,
                    "primary_device_id": None,
                    "status": "unknown",
                    "runtime_device_count": 0,
                    "runtime_host_count": 0,
                    "mesh_membership_count": 0,
                    "takeover_count": 0,
                    "has_dispatch_state": False,
                    "has_coordinator_state": False,
                    "has_merged_result": False,
                    "has_recovery_state": False,
                    "has_mesh_session": False,
                    "has_governance_snapshot": False,
                    "has_policy_alignment": False,
                    "created_at": None,
                    "updated_at": None,
                    "generated_at": _time_fallback.time(),
                    "metadata": {"error": "session snapshot unavailable"},
                }
            )

    # ------------------------------------------------------------------
    # GET /api/v1/projection/canonical-routing  (PR-3)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/canonical-routing")
    async def get_canonical_routing_projection() -> JSONResponse:
        """Return the canonical routing projection with OneAPI and provider status.

        This endpoint is **read-only** and **additive** (PR-3).  It does not
        modify any existing projection, router, or model supply module.

        The response contains the standard
        :class:`~core.projection.RuntimeProjection` fields plus enriched
        canonical routing data, including:

        - ``routing_authority`` — the canonical routing authority sentinel
        - ``route_reason`` — human-readable routing rationale
        - ``primary_model_id`` / ``support_model_ids`` — canonical model IDs
        - ``active_weights`` — full weight breakdown
        - ``oneapi_summary`` — OneAPI system integration position (when applicable)
        - ``provider_status_summary`` — compact provider health summary (when available)

        Source priority:

        1. ``TopologyRoutePlan`` (canonical) — ``routing_authority`` is set to
           :data:`~core.model_topology.topology_router.CANONICAL_ROUTING_AUTHORITY`.
        2. No topology available — all routing fields are ``None``/empty with
           ``routing_authority = "none"``.

        This endpoint is the canonical integration point for desktop status
        board consumers that need unified routing + provider status without
        coupling to the dashboard UI.

        Response schema
        ---------------
        See :class:`~core.projection.RuntimeProjection` for full field reference.
        Additional top-level keys:

        - ``oneapi_summary``          — OneAPI integration position dict or null
        - ``provider_status_summary`` — provider health summary dict or null
        - ``canonical_routing_hints`` — quick-access routing hints dict

        Example ``canonical_routing_hints``::

            {
              "has_route": true,
              "routing_authority": "core.model_topology.topology_router.TopologyRouter",
              "is_canonical": true,
              "is_legacy": false,
              "primary_model_id": "openai/gpt-4o",
              "support_count": 2,
              "has_oneapi": false,
              "provider_available_count": 3,
              "provider_degraded_count": 0,
              "route_reason": "..."
            }
        """
        payload = _assemble_canonical_routing_payload()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/server-canonicalization-status  (PR-5)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/server-canonicalization-status")
    async def get_server_canonicalization_status() -> JSONResponse:
        """Return a read-only server-side canonicalization status summary.

        This endpoint is **read-only** and **additive** (PR-5).  It does not
        modify any existing projection, router, or model supply module.

        PR-5 completes the server-side canonicalization phase that follows
        PR-4 (OneAPI lower-horizon cleanup).  This endpoint exposes a
        machine-checkable summary of:

        - Which routing/projection fields have been canonicalized
        - Which legacy UCP keys remain as compatibility bridges
        - Whether the canonical routing authority is active
        - The PR-4 OneAPI lower-horizon guarantee status
        - Downstream consumer guidance

        Response schema
        ---------------
        .. code-block:: json

            {
              "canonicalization_stage": "pr5_server_side",
              "canonical_routing_authority": "core.model_topology...",
              "canonical_projection_authority": "contracts.desktop_status_projection...",
              "legacy_ucp_routing_keys": ["chosen_model", ...],
              "legacy_routing_fields": ["chosen_model", ...],
              "oneapi_lower_horizon_guaranteed": true,
              "oneapi_integration_field_present": true,
              "pr4_guarantees_intact": true,
              "consumer_guidance": {
                "prefer_topology_route_plan": true,
                "prefer_oneapi_integration_block": true,
                "avoid_legacy_ucp_keys": true,
                "legacy_routing_fallback_active_field": "model_routing.legacy_routing_fallback_active"
              },
              "timestamp": 1234567890.0
            }
        """
        payload = _assemble_server_canonicalization_status()
        return JSONResponse(content=payload)

    # ------------------------------------------------------------------
    # GET /api/v1/projection/desktop-topology  (PR-6, hardened PR-7)
    # ------------------------------------------------------------------

    @router.get("/api/v1/projection/desktop-topology")
    async def get_desktop_topology_projection() -> JSONResponse:
        """Return the topology-ready projection block for desktop surfaces.

        This endpoint is **read-only** and **additive** (PR-6, PR-7).  It does
        not modify any existing projection, router, or model supply module.

        Returns the :class:`~contracts.desktop_status_projection.DesktopTopologyProjection`
        block derived from the canonical ``TopologyRoutePlan`` (when available),
        with legacy fallback explicitly marked and degraded.

        This is the single canonical integration point for desktop topology
        surfaces (constellation-style boards) that need a renderer-agnostic,
        topology-ready projection without reconstructing routing truth from
        legacy keys or dashboard-era summaries.

        PR-7 readiness / quality semantics
        -----------------------------------
        The ``projection_quality`` block provides structured machine-readable
        semantics about whether the topology data is authoritative.  Consumers
        **must** inspect this block before treating topology data as ground truth:

        - ``projection_quality.readiness`` — one of ``"canonical"``,
          ``"degraded"``, ``"partial"``, ``"unavailable"``.
        - ``projection_quality.authoritative`` — ``true`` only when
          ``readiness == "canonical"``.  **Never treat data as authoritative
          routing truth when this is ``false``.**
        - ``projection_quality.degraded`` — ``true`` when routing was
          assembled from legacy UCP keys; the block must not be used as full truth.
        - ``projection_quality.quality_note`` — human-readable explanation for
          operators / diagnostic logs.

        Additional semantics
        --------------------
        - ``canonical_source_present`` — ``true`` when sourced from
          ``TopologyRoutePlan``; ``false`` on legacy/fallback path.
        - ``legacy_fallback_active`` — ``true`` when routing data was
          assembled from legacy UCP keys; signals degraded projection.
        - ``oneapi_integration`` — always present as a **lower-horizon** block;
          never promoted to top-layer peer.
        - ``contract_authority`` — machine-checkable PR-6 sentinel.

        Response schema
        ---------------
        .. code-block:: json

            {
              "primary_model_id": "gpt-4o",
              "primary_provider_id": "openai",
              "primary_vendor_source": "direct",
              "primary_is_native_multimodal": false,
              "support_model_ids": ["claude-3-5-sonnet"],
              "route_reason": "...",
              "route_phase": "manifest",
              "route_domain": "local",
              "primary_provider_available": true,
              "routing_authority_source": "topology_router",
              "canonical_source_present": true,
              "legacy_fallback_active": false,
              "oneapi_integration": { "system_layer": "aggregator_integration", ... },
              "health_severity": "ok",
              "projection_quality": {
                "readiness": "canonical",
                "authoritative": true,
                "degraded": false,
                "partial": false,
                "quality_note": "Topology projection is fully canonical and authoritative...",
                "quality_authority": "contracts.desktop_status_projection.TopologyProjectionQualityBlock"
              },
              "contract_authority": "contracts.desktop_status_projection.DesktopTopologyProjection"
            }
        """
        payload = _assemble_desktop_topology_payload()
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


def _assemble_canonical_routing_payload() -> Dict[str, Any]:
    """Assemble a canonical routing projection payload with OneAPI and provider status.

    Builds the standard RuntimeProjection and enriches it with:
    - ``oneapi_summary`` from core.oneapi_system_position
    - ``provider_status_summary`` from the canonical model supply state
    - ``canonical_routing_hints`` for quick-access downstream consumers

    Always returns a valid dict.  All enrichment steps are optional and
    degrade gracefully when the relevant sub-systems are unavailable.
    """
    try:
        from core.projection import build_runtime_projection, ExecutionSummary
        from core.continuum.types import ContinuumPhase, ContinuumState  # noqa: F401
    except Exception as exc:
        logger.warning(
            "_assemble_canonical_routing_payload: imports unavailable: %s", exc
        )
        base = _minimal_fallback_payload()
        base["oneapi_summary"] = None
        base["provider_status_summary"] = None
        base["canonical_routing_hints"] = _build_routing_hints(base, None, None)
        return base

    continuum_state = _get_continuum_state()
    route_plan = _get_route_plan(continuum_state)
    execution_summary = _get_execution_summary()

    # --- Derive oneapi_summary -------------------------------------------
    oneapi_summary: Optional[Any] = None
    try:
        from core.projection.projection_helpers import (
            extract_oneapi_source_from_route_plan,
            build_oneapi_projection_summary,
        )
        if route_plan is not None:
            route_plan_dict = route_plan.to_dict()
            oneapi_summary = extract_oneapi_source_from_route_plan(route_plan_dict)
        # If route-based extraction did not find OneAPI participation, fall back
        # to the canonical system-level summary to make the integration position
        # visible in the projection even when OneAPI is not the active route.
        if oneapi_summary is None:
            oneapi_summary = build_oneapi_projection_summary()
    except Exception as exc:
        logger.debug(
            "_assemble_canonical_routing_payload: oneapi_summary derivation skipped: %s",
            exc,
        )

    # --- Derive provider_status_summary ----------------------------------
    provider_status_summary: Optional[Any] = None
    try:
        from core.projection.projection_helpers import extract_provider_status_summary

        model_supply: Optional[Any] = None
        try:
            from core.model_topology import ProviderInventory
            inventory = ProviderInventory.from_config()
            # Build a minimal model_supply dict from the inventory if possible.
            if hasattr(inventory, "to_dict"):
                model_supply = inventory.to_dict()
            elif hasattr(inventory, "providers"):
                model_supply = {
                    "providers": [
                        {
                            "provider_id": p.provider_id,
                            "health_status": getattr(p, "health_status", "healthy"),
                        }
                        for p in (inventory.providers or [])
                    ]
                }
        except Exception:
            pass

        if model_supply:
            provider_status_summary = extract_provider_status_summary(model_supply)
    except Exception as exc:
        logger.debug(
            "_assemble_canonical_routing_payload: provider_status_summary skipped: %s",
            exc,
        )

    # --- Build projection -------------------------------------------------
    try:
        if continuum_state is None:
            base = _minimal_fallback_payload()
        else:
            projection = build_runtime_projection(
                continuum_state=continuum_state,
                route_plan=route_plan,
                execution_summary=execution_summary,
                oneapi_summary=oneapi_summary,
                provider_status_summary=provider_status_summary,
                timestamp=time.time(),
            )
            base = projection.to_dict()
    except Exception as exc:
        logger.warning(
            "_assemble_canonical_routing_payload: projection assembly failed: %s", exc
        )
        base = _minimal_fallback_payload()
        base["oneapi_summary"] = oneapi_summary
        base["provider_status_summary"] = provider_status_summary

    # --- Attach canonical routing hints ----------------------------------
    base["canonical_routing_hints"] = _build_routing_hints(
        base, oneapi_summary, provider_status_summary
    )
    return base


def _build_routing_hints(
    projection_dict: Dict[str, Any],
    oneapi_summary: Optional[Any],
    provider_status_summary: Optional[Any],
) -> Dict[str, Any]:
    """Build a compact canonical routing hints dict for quick consumer access."""
    from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

    routing_authority = projection_dict.get("routing_authority", "none")
    primary_model_id = projection_dict.get("primary_model_id")
    support_model_ids = projection_dict.get("support_model_ids") or []
    route_reason = projection_dict.get("route_reason")

    has_route = bool(primary_model_id)
    is_canonical = routing_authority == CANONICAL_ROUTING_AUTHORITY
    is_legacy = routing_authority not in (CANONICAL_ROUTING_AUTHORITY, "none")
    has_oneapi = oneapi_summary is not None

    provider_available_count = 0
    provider_degraded_count = 0
    if isinstance(provider_status_summary, dict):
        provider_available_count = provider_status_summary.get("available", 0)
        provider_degraded_count = provider_status_summary.get("degraded", 0)

    return {
        "has_route": has_route,
        "routing_authority": routing_authority,
        "is_canonical": is_canonical,
        "is_legacy": is_legacy,
        "primary_model_id": primary_model_id,
        "support_count": len(support_model_ids),
        "has_oneapi": has_oneapi,
        "provider_available_count": provider_available_count,
        "provider_degraded_count": provider_degraded_count,
        "route_reason": route_reason,
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


def _assemble_projection_with_routing_explanation() -> Dict[str, Any]:
    """Assemble a projection dict enriched with the PR-21 routing explanation summary.

    Builds the agent-dispatch projection (which includes all previous layers),
    then derives and attaches the routing explanation summary and hints.
    Always returns a valid dict with ``"routing_explanation"`` and
    ``"explanation_hints"`` keys even when the package is unavailable.
    """
    base = _assemble_projection_with_agent_dispatch()

    try:
        from core.routing_explanation import (
            IDLE_EXPLANATION_SUMMARY,
            attach_explanation_to_projection,
            get_explanation_hints,
            resolve_explanation_from_projection,
        )

        summary = resolve_explanation_from_projection(base)
        result = attach_explanation_to_projection(base, summary)
        result["explanation_hints"] = get_explanation_hints(summary)
        return result

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Routing-explanation assembly failed, attaching idle placeholder: %s", exc
        )
        base["routing_explanation"] = {
            "schema_version": 1,
            "route_target": None,
            "decision_basis_list": [],
            "confidence": {
                "score": 0.0,
                "band": "undetermined",
                "basis_count": 0,
                "accepted_factor_count": 0,
                "rejected_factor_count": 0,
                "contributing_factors": [],
                "reason": "routing explanation unavailable",
            },
            "rejected_alternatives": [],
            "fallback_plan": None,
            "owner_agent": None,
            "owner_component": "routing_explanation",
            "policy_posture": "undecided",
            "policy_band": None,
            "policy_reason": "no routing decision recorded",
            "is_cross_device": False,
            "has_fallback": False,
            "task_id": None,
            "trace_id": None,
        }
        base["explanation_hints"] = {
            "route_target": None,
            "policy_posture": "undecided",
            "policy_band": None,
            "confidence_score": 0.0,
            "confidence_band": "undetermined",
            "is_cross_device": False,
            "has_fallback": False,
            "has_rejected_alternatives": False,
            "rejected_count": 0,
            "basis_count": 0,
            "owner_agent": None,
        }
        return base


def _assemble_projection_with_governance() -> Dict[str, Any]:
    """Assemble a projection dict enriched with PR-26 governance assembly data.

    Builds the standard projection first, then assembles and attaches the
    governance summary derived from any available governance inputs
    (intent profile, readiness result, fallback trace, execution trace envelope).

    Always returns a valid dict with ``"governance"`` and
    ``"governance_hints"`` keys even when governance inputs are unavailable
    (in which case ``"governance"`` will reflect a minimal unavailable state).
    """
    base = _assemble_projection()

    try:
        from core.projection.assembly_governance import assemble_projection_governance

        continuum_state = _get_continuum_state()

        gov_summary = assemble_projection_governance(
            intent_profile=None,
            readiness_result=None,
            fallback_trace=None,
            execution_trace_envelope=None,
            state_continuum=continuum_state,
        )
        base["governance"] = gov_summary.to_dict()
        base["governance_hints"] = {
            "governance_available": gov_summary.governance_available,
            "action_level": gov_summary.execution.action_level,
            "intent_mode": gov_summary.execution.intent_mode,
            "ready": gov_summary.policy.ready,
            "policy_status": gov_summary.policy.status,
            "blocked": gov_summary.policy.blocked,
            "degraded": gov_summary.policy.degraded,
            "fallback_outcome": gov_summary.fallback.outcome,
            "trace_final_status": gov_summary.execution_trace.final_status,
            "tri_state_phase": gov_summary.tri_state_phase,
            "runtime_domain": gov_summary.runtime_domain,
        }
        return base

    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Governance projection assembly failed, attaching minimal placeholder: %s", exc
        )
        base["governance"] = {
            "governance_available": False,
            "execution": {"available": False, "action_level": "observe", "intent_mode": "advisory"},
            "policy": {"available": False, "ready": False, "status": "blocked", "blocked": True},
            "fallback": {"available": False, "outcome": "noop"},
            "execution_trace": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "tri_state_phase": None,
            "runtime_domain": None,
            "assembled_at": time.time(),
        }
        base["governance_hints"] = {
            "governance_available": False,
            "action_level": "observe",
            "intent_mode": "advisory",
            "ready": False,
            "policy_status": "blocked",
            "blocked": True,
            "degraded": False,
            "fallback_outcome": "noop",
            "trace_final_status": "pending",
            "tri_state_phase": None,
            "runtime_domain": None,
        }
        return base


def _assemble_runtime_governance_snapshot_payload() -> Dict[str, Any]:
    """Assemble and return the runtime governance snapshot payload.

    Builds the projection governance summary (PR-26) and then assembles the
    unified runtime governance snapshot (PR-27) from all available runtime
    inputs.  Always returns a valid serialisable dict; individual component
    failures result in graceful defaults rather than errors.
    """
    try:
        from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

        # Get the projection governance summary (PR-26) first, it is the
        # richest governance source available at projection time.
        proj_gov = None
        try:
            from core.projection.assembly_governance import assemble_projection_governance

            continuum_state = _get_continuum_state()
            proj_gov = assemble_projection_governance(
                intent_profile=None,
                readiness_result=None,
                fallback_trace=None,
                execution_trace_envelope=None,
                state_continuum=continuum_state,
            )
        except Exception as exc:
            logger.warning(
                "Runtime governance snapshot: projection governance unavailable: %s", exc
            )

        # Resolve tri_state_phase / runtime_domain from live continuum state
        tri_state_phase: Optional[str] = None
        runtime_domain: Optional[str] = None
        try:
            cs = _get_continuum_state()
            if cs is not None:
                if isinstance(cs, dict):
                    tri_state_phase = cs.get("tri_state_phase")
                    runtime_domain = cs.get("runtime_domain")
                else:
                    phase = getattr(cs, "tri_state_phase", None)
                    domain = getattr(cs, "runtime_domain", None)
                    if phase is not None:
                        tri_state_phase = (
                            phase.value if hasattr(phase, "value") else str(phase)
                        )
                    if domain is not None:
                        runtime_domain = (
                            domain.value if hasattr(domain, "value") else str(domain)
                        )
        except Exception as exc:
            logger.warning(
                "Runtime governance snapshot: failed to resolve phase/domain: %s", exc
            )

        snapshot = assemble_runtime_governance_snapshot(
            projection_governance=proj_gov,
            tri_state_phase=tri_state_phase,
            runtime_domain=runtime_domain,
        )
        return snapshot.to_dict()

    except Exception as exc:
        logger.warning(
            "Runtime governance snapshot assembly failed, returning minimal payload: %s", exc
        )
        import uuid

        return {
            "snapshot_id": str(uuid.uuid4()),
            "trace_id": None,
            "runtime_session_id": None,
            "tri_state_phase": None,
            "runtime_domain": None,
            "governance_available": False,
            "intent_summary": {"available": False, "action_level": "observe", "intent_mode": "advisory"},
            "readiness_summary": {"available": False, "ready": False, "status": "blocked", "blocked": True},
            "fallback_summary": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "execution_trace_summary": {"available": False, "final_status": "pending", "stage_count": 0, "stages": []},
            "projection_governance_summary": {"available": False, "governance_available": False},
            "posture": "unknown",
            "blocked": False,
            "degraded": False,
            "timestamp": time.time(),
        }


def _assemble_policy_alignment_payload() -> Dict[str, Any]:
    """Assemble and return the execution policy alignment surface payload (PR-28).

    Builds the projection governance summary (PR-26), the runtime governance
    snapshot (PR-27), and then assembles the execution policy alignment surface
    (PR-28) from all available runtime inputs.  Always returns a valid
    serialisable dict; individual component failures result in graceful defaults
    rather than errors.
    """
    try:
        from core.policy.alignment_surface import build_execution_policy_alignment_surface

        # Get projection governance (PR-26)
        proj_gov = None
        try:
            from core.projection.assembly_governance import assemble_projection_governance

            continuum_state = _get_continuum_state()
            proj_gov = assemble_projection_governance(
                intent_profile=None,
                readiness_result=None,
                fallback_trace=None,
                execution_trace_envelope=None,
                state_continuum=continuum_state,
            )
        except Exception as exc:
            logger.warning(
                "Policy alignment: projection governance unavailable: %s", exc
            )

        # Get runtime governance snapshot (PR-27)
        runtime_snapshot = None
        try:
            from core.runtime_governance.snapshot import assemble_runtime_governance_snapshot

            runtime_snapshot = assemble_runtime_governance_snapshot(
                projection_governance=proj_gov,
            )
        except Exception as exc:
            logger.warning(
                "Policy alignment: runtime governance snapshot unavailable: %s", exc
            )

        # Resolve tri_state_phase / runtime_domain from live continuum state
        tri_state_phase: Optional[str] = None
        runtime_domain: Optional[str] = None
        try:
            cs = _get_continuum_state()
            if cs is not None:
                if isinstance(cs, dict):
                    tri_state_phase = cs.get("tri_state_phase")
                    runtime_domain = cs.get("runtime_domain")
                else:
                    phase = getattr(cs, "tri_state_phase", None)
                    domain = getattr(cs, "runtime_domain", None)
                    if phase is not None:
                        tri_state_phase = (
                            phase.value if hasattr(phase, "value") else str(phase)
                        )
                    if domain is not None:
                        runtime_domain = (
                            domain.value if hasattr(domain, "value") else str(domain)
                        )
        except Exception as exc:
            logger.warning(
                "Policy alignment: failed to resolve phase/domain: %s", exc
            )

        alignment = build_execution_policy_alignment_surface(
            runtime_governance_snapshot=runtime_snapshot,
            projection_governance=proj_gov,
            tri_state_phase=tri_state_phase,
            runtime_domain=runtime_domain,
        )
        return alignment.to_dict()

    except Exception as exc:
        logger.warning(
            "Policy alignment assembly failed, returning minimal payload: %s", exc
        )
        import uuid

        return {
            "alignment_id": str(uuid.uuid4()),
            "trace_id": None,
            "runtime_session_id": None,
            "tri_state_phase": None,
            "runtime_domain": None,
            "aligned": False,
            "blocked": False,
            "degraded": True,
            "confirmation_required": False,
            "policy_posture": "unknown",
            "runtime_policy_summary": {"dimension": "runtime_policy", "available": False},
            "readiness_policy_summary": {"dimension": "readiness_policy", "available": False},
            "fallback_policy_summary": {"dimension": "fallback_policy", "available": False},
            "dispatch_policy_summary": {"dimension": "dispatch_policy", "available": False},
            "projection_policy_summary": {"dimension": "projection_policy", "available": False},
            "mismatches": [],
            "alignment_hints": {
                "can_execute_locally": False,
                "can_expand_cross_device": False,
                "is_confirmation_gated": False,
                "is_blocked": False,
                "is_degraded": True,
                "preferred_domain": None,
                "effective_action_level": "observe",
                "alignment_confidence": 0.0,
                "policy_posture": "unknown",
                "hint_source": "empty",
            },
            "timestamp": time.time(),
        }


def _assemble_server_canonicalization_status() -> Dict[str, Any]:
    """Assemble the PR-5 server-side canonicalization status summary.

    Returns a machine-checkable dict describing:
    - Canonical routing/projection authorities
    - Legacy UCP keys demoted by PR-5
    - PR-4 OneAPI lower-horizon guarantee status
    - Consumer guidance for downstream surfaces
    """
    from contracts.desktop_status_projection import (
        LEGACY_UCP_ROUTING_KEYS,
        PROJECTION_CONTRACT_AUTHORITY,
    )
    from core.model_topology.topology_router import (
        CANONICAL_ROUTING_AUTHORITY,
        LEGACY_ROUTING_FIELDS,
    )
    from core.projection.projection_compiler import (
        LEGACY_PROJECTION_UCP_KEYS,
        PROJECTION_COMPILER_AUTHORITY,
    )

    # Check PR-4 oneapi_integration guarantee.
    oneapi_integration_present = False
    try:
        from contracts.desktop_status_projection import DesktopStatusProjection
        _test_proj = DesktopStatusProjection()
        oneapi_integration_present = hasattr(_test_proj, "oneapi_integration")
    except Exception:
        pass

    return {
        "canonicalization_stage": "pr5_server_side",
        "pr_description": (
            "PR-5 completes server-side canonicalization after PR-4 OneAPI "
            "lower-horizon cleanup.  Legacy UCP routing keys are demoted to "
            "compatibility-only status.  Canonical TopologyRoutePlan and "
            "DesktopStatusProjection are the preferred server outputs."
        ),
        "canonical_routing_authority": CANONICAL_ROUTING_AUTHORITY,
        "canonical_projection_compiler_authority": PROJECTION_COMPILER_AUTHORITY,
        "canonical_projection_contract_authority": PROJECTION_CONTRACT_AUTHORITY,
        "legacy_ucp_routing_keys": sorted(LEGACY_UCP_ROUTING_KEYS),
        "legacy_routing_fields": list(LEGACY_ROUTING_FIELDS),
        "legacy_projection_ucp_keys": list(LEGACY_PROJECTION_UCP_KEYS),
        "oneapi_lower_horizon_guaranteed": True,
        "oneapi_integration_field_present": oneapi_integration_present,
        "pr4_guarantees_intact": True,
        "consumer_guidance": {
            "prefer_topology_route_plan": True,
            "prefer_oneapi_integration_block": True,
            "avoid_legacy_ucp_keys": True,
            "legacy_routing_fallback_active_field": (
                "model_routing.legacy_routing_fallback_active"
            ),
            "canonical_endpoint": "/api/v1/projection/canonical-routing",
            "desktop_status_endpoint": "/api/v1/projection/runtime",
        },
        "timestamp": time.time(),
    }


def _assemble_desktop_topology_payload() -> Dict[str, Any]:
    """PR-6: Assemble the topology-ready projection payload for desktop surfaces.

    Builds a :class:`~contracts.desktop_status_projection.DesktopTopologyProjection`
    from live runtime state (canonical ``TopologyRoutePlan`` when available,
    legacy fallback with explicit degradation marking otherwise).

    Always returns a valid dict.  All sub-components are optional and degrade
    gracefully when the relevant sub-systems are unavailable.
    """
    try:
        from contracts.desktop_status_projection import (
            build_desktop_status_projection,
        )
    except Exception as exc:
        logger.warning(
            "_assemble_desktop_topology_payload: import failed: %s", exc
        )
        return _minimal_desktop_topology_fallback()

    # Build a UCP dict from the live topology route plan so that the
    # topology-ready projection block is sourced from canonical data.
    ucp: Dict[str, Any] = {}
    try:
        continuum_state = _get_continuum_state()
        route_plan = _get_route_plan(continuum_state)
        if route_plan is not None:
            ucp["topology_route_plan"] = route_plan.to_dict()
    except Exception as exc:
        logger.debug(
            "_assemble_desktop_topology_payload: route_plan derivation skipped: %s",
            exc,
        )

    try:
        proj = build_desktop_status_projection(unified_control_plan=ucp)
        topo = proj.topology_ready
        if topo is None:
            return _minimal_desktop_topology_fallback()
        result = topo.to_dict()
        result["_assembled_at"] = time.time()
        return result
    except Exception as exc:
        logger.warning(
            "_assemble_desktop_topology_payload: projection assembly failed: %s", exc
        )
        return _minimal_desktop_topology_fallback()


def _minimal_desktop_topology_fallback() -> Dict[str, Any]:
    """Return a minimal valid desktop topology payload for failure cases."""
    return {
        "primary_model_id": None,
        "primary_provider_id": None,
        "primary_vendor_source": None,
        "primary_is_native_multimodal": False,
        "support_model_ids": [],
        "route_reason": None,
        "route_phase": None,
        "route_domain": None,
        "primary_provider_available": True,
        "routing_authority_source": "none",
        "canonical_source_present": False,
        "legacy_fallback_active": False,
        "oneapi_integration": None,
        "health_severity": "unknown",
        "projection_quality": {
            "readiness": "unavailable",
            "authoritative": False,
            "degraded": False,
            "partial": False,
            "quality_note": (
                "No routing data is available. Topology block cannot provide routing truth. "
                "Consumers must not render constellation topology from this block."
            ),
            "quality_authority": (
                "contracts.desktop_status_projection.TopologyProjectionQualityBlock"
            ),
        },
        "contract_authority": (
            "contracts.desktop_status_projection.DesktopTopologyProjection"
        ),
        "_assembled_at": time.time(),
    }
