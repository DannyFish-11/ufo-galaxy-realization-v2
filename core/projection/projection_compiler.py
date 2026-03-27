"""
core/projection/projection_compiler.py
========================================
projection_compiler — assembles a :class:`~core.projection.runtime_projection.RuntimeProjection`
from existing core state objects.

The compiler is the **only** place that knows how to translate between the
raw runtime state objects (continuum, topology, device/execution summaries)
and the unified projection contract.  Downstream consumers (status boards,
spatial projection layers, API endpoints) call :func:`build_runtime_projection`
and receive a self-contained, serialisable snapshot.

Design
------
- Additive: does not modify :class:`~core.continuum.types.ContinuumState`,
  :class:`~core.model_topology.topology_router.TopologyRoutePlan`, or any
  other existing module.
- No UI semantics.
- All external inputs beyond ``continuum_state`` are optional; missing data
  results in ``None``/empty-collection fields in the projection rather than
  errors.

Usage::

    from core.projection import build_runtime_projection
    from core.continuum.types import ContinuumState, ContinuumPhase

    state = ContinuumState(phase=ContinuumPhase.LIMINAL, coherence=0.6)
    projection = build_runtime_projection(state)

    # With a route plan from PR-2:
    from core.model_topology import TopologyRouter, ProviderInventory
    plan = TopologyRouter(inventory).route(state.tri_state_phase, state.runtime_domain or RuntimeDomain.LOCAL)
    projection = build_runtime_projection(state, route_plan=plan)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from core.continuum.types import ContinuumState, RuntimeDomain

from .runtime_projection import RuntimeProjection

logger = logging.getLogger("Galaxy.Projection.ProjectionCompiler")

# TYPE_CHECKING import to avoid a circular dependency at runtime if
# topology_router ever imports from projection in the future.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.model_topology.topology_router import TopologyRoutePlan


# ---------------------------------------------------------------------------
# PR-5: Post-canonical server projection policy
# ---------------------------------------------------------------------------

#: Tuple of top-level UCP keys that are **legacy/compatibility-only** in the
#: projection layer.  When a ``route_plan`` (:class:`TopologyRoutePlan`) is
#: available, projection consumers must source all routing truth from the
#: canonical route plan rather than these scattered keys.
#:
#: History:
#: - PR-2 established ``TopologyRoutePlan`` as the sole canonical routing
#:   output contract.
#: - PR-3 added ``vendor_source``/``oneapi_source`` to the projection layer.
#: - PR-4 completed OneAPI lower-horizon cleanup (``oneapi_integration``
#:   block in ``DesktopStatusProjection``).
#: - PR-5 (this module) formalises the demotion of these scattered UCP keys
#:   so that machine-checkable guardrails can enforce canonical-first
#:   consumption.  See ``docs/SERVER_SIDE_CANONICALIZATION.md``.
LEGACY_PROJECTION_UCP_KEYS: tuple = (
    "chosen_model",
    "chosen_provider",
    "is_native_multimodal",
    "support_model_ids",
    "route_reason",
    "multimodal_route",
)

#: Sentinel string that marks the canonical projection compiler as the sole
#: assembly authority for :class:`RuntimeProjection`.  Downstream surfaces
#: must not assemble a ``RuntimeProjection`` outside of this function.
PROJECTION_COMPILER_AUTHORITY: str = (
    "core.projection.projection_compiler.build_runtime_projection"
)

#: PR-6: Sentinel string identifying the topology-ready projection delivery
#: layer.  Mirrors :data:`contracts.desktop_status_projection.TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY`
#: so that the projection compiler can reference the same canonical authority
#: from within the ``core.projection`` namespace.
TOPOLOGY_PROJECTION_DELIVERY_AUTHORITY: str = (
    "contracts.desktop_status_projection.DesktopTopologyProjection"
)

#: PR-7: Sentinel string identifying the topology projection quality/readiness
#: block as a PR-7 canonical contract artefact.  Mirrors
#: :data:`contracts.desktop_status_projection.TOPOLOGY_READINESS_CONTRACT_AUTHORITY`
#: so that the projection compiler can reference the same authority from within
#: the ``core.projection`` namespace.
TOPOLOGY_READINESS_CONTRACT_AUTHORITY: str = (
    "contracts.desktop_status_projection.TopologyProjectionQualityBlock"
)

#: PR-8: Sentinel string identifying the final desktop status board integration
#: payload as a PR-8 canonical contract artefact.  Mirrors
#: :data:`contracts.desktop_status_projection.DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY`
#: so that the projection compiler can reference the same canonical authority
#: from within the ``core.projection`` namespace.
DESKTOP_STATUS_BOARD_INTEGRATION_AUTHORITY: str = (
    "contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload"
)


# ---------------------------------------------------------------------------
# ExecutionSummary — lightweight placeholder for device/execution context
# ---------------------------------------------------------------------------


class ExecutionSummary:
    """Minimal placeholder carrying optional device and execution context.

    Pass an instance of this class to :func:`build_runtime_projection` when
    you have device-management or task-orchestration context to include in the
    projection.  All fields are optional; unset fields result in ``None`` or
    empty-list defaults in the assembled projection.

    Attributes
    ----------
    active_device_ids:
        IDs of devices currently considered active by the caller's device
        management layer.  Defaults to an empty list.
    execution_stage:
        Freeform string tag for the current execution stage
        (e.g. ``"planning"``, ``"executing"``, ``"completing"``).
    current_task_summary:
        Short human-readable description of the task currently in progress.
    """

    def __init__(
        self,
        active_device_ids: Optional[List[str]] = None,
        execution_stage: Optional[str] = None,
        current_task_summary: Optional[str] = None,
    ) -> None:
        self.active_device_ids: List[str] = active_device_ids or []
        self.execution_stage: Optional[str] = execution_stage
        self.current_task_summary: Optional[str] = current_task_summary


# ---------------------------------------------------------------------------
# build_runtime_projection
# ---------------------------------------------------------------------------


def build_runtime_projection(
    continuum_state: ContinuumState,
    route_plan: "Optional[TopologyRoutePlan]" = None,
    execution_summary: Optional[ExecutionSummary] = None,
    timestamp: Optional[float] = None,
    intent_profile: "Optional[Any]" = None,
    readiness_result: "Optional[Any]" = None,
    fallback_trace: "Optional[Any]" = None,
    execution_trace_envelope: "Optional[Any]" = None,
    oneapi_summary: "Optional[Dict[str, Any]]" = None,
    provider_status_summary: "Optional[Dict[str, Any]]" = None,
) -> RuntimeProjection:
    """Assemble a :class:`RuntimeProjection` from core runtime state.

    This is the single entry-point for constructing a ``RuntimeProjection``.
    It extracts the relevant fields from each input object and combines them
    into the unified projection contract.

    Args:
        continuum_state:
            The current :class:`~core.continuum.types.ContinuumState`.
            All continuum-derived fields (tri_state_phase, runtime_domain,
            presence_intensity, coherence, collapse_tendency, retreat_tendency)
            are sourced exclusively from this object.
        route_plan:
            Optional :class:`~core.model_topology.topology_router.TopologyRoutePlan`
            produced by the PR-2 :class:`~core.model_topology.TopologyRouter`.
            When provided, populates primary_model_id, support_model_ids,
            active_weights, and route_reason.  When ``None``, those fields
            default to ``None`` / empty collections.
        execution_summary:
            Optional :class:`ExecutionSummary` carrying device IDs, execution
            stage, and task summary from the caller's execution context.  When
            ``None``, those fields default to empty list / ``None``.
        timestamp:
            Optional explicit Unix epoch timestamp for this projection.
            Defaults to :func:`time.time` at call time.
        intent_profile:
            Optional :class:`~core.execution.intent_profile.ExecutionIntentProfile`
            (PR-22).  When provided, its compact summary is included in the
            ``execution_intent_summary`` field of the projection for
            governance/debug consumers.  Additive; does not affect other fields.
        readiness_result:
            Optional :class:`~core.execution.readiness_gate.ReadinessResult`
            (PR-23).  When provided together with other governance inputs, used
            to populate the ``governance`` field of the projection.
            Additive; does not affect base projection fields.
        fallback_trace:
            Optional :class:`~core.execution.fallback_trace.FallbackDecisionTrace`
            (PR-24).  When provided together with other governance inputs, used
            to populate the ``governance`` field of the projection.
            Additive; does not affect base projection fields.
        execution_trace_envelope:
            Optional :class:`~contracts.execution_trace.ExecutionTraceEnvelope`
            (PR-25).  When provided together with other governance inputs, used
            to populate the ``governance`` field of the projection.
            Additive; does not affect base projection fields.
        oneapi_summary:
            Optional dict describing the OneAPI system integration position
            (PR-3).  When ``None`` and a ``route_plan`` is provided, the
            compiler will attempt to derive this automatically from the
            canonical route plan when the primary node uses the OneAPI
            vendor source.  Pass an explicit dict to override auto-derivation.
        provider_status_summary:
            Optional dict carrying a compact provider health/availability
            summary (PR-3).  When ``None``, the field is absent from the
            assembled projection.  Callers should derive this from the
            canonical model supply state when available.

    Returns:
        A fully populated (or minimally populated) :class:`RuntimeProjection`.
    """
    ts = timestamp if timestamp is not None else time.time()

    # --- Continuum-derived fields ------------------------------------------
    tri_state_phase = continuum_state.tri_state_phase
    runtime_domain = continuum_state.runtime_domain
    presence_intensity = continuum_state.presence_intensity
    coherence = continuum_state.coherence
    collapse_tendency = continuum_state.collapse_tendency
    retreat_tendency = continuum_state.retreat_tendency

    # --- Topology/route-derived fields -------------------------------------
    primary_model_id: Optional[str] = None
    support_model_ids: List[str] = []
    active_weights: Dict[str, float] = {}
    route_reason: Optional[str] = None
    # Routing authority: set to CANONICAL_ROUTING_AUTHORITY when populated from
    # a TopologyRoutePlan; "none" otherwise.
    routing_authority: str = "none"

    if route_plan is not None:
        from core.model_topology.topology_router import CANONICAL_ROUTING_AUTHORITY

        if route_plan.primary_model is not None:
            primary_model_id = route_plan.primary_model.node_id

        support_model_ids = [n.node_id for n in route_plan.support_models]

        # Flatten ModelWeightField → float (combined_weight)
        active_weights = {
            node_id: wf.combined_weight
            for node_id, wf in route_plan.active_weights.items()
        }

        route_reason = route_plan.route_reason
        routing_authority = CANONICAL_ROUTING_AUTHORITY

        # Auto-derive oneapi_summary when the caller did not supply one and
        # the primary node's vendor_source is "oneapi".
        if oneapi_summary is None and route_plan.primary_model is not None:
            try:
                _category_obj = getattr(route_plan.primary_model, "category", None)
                _category = (
                    _category_obj.value
                    if _category_obj is not None and hasattr(_category_obj, "value")
                    else str(_category_obj) if _category_obj is not None else ""
                )
                if _category == "oneapi":
                    from core.oneapi_system_position import build_oneapi_integration_summary
                    oneapi_summary = build_oneapi_integration_summary().to_dict()
            except Exception as _oa_exc:
                logger.debug(
                    "build_runtime_projection: oneapi_summary auto-derivation skipped: %s",
                    _oa_exc,
                )

    # --- Device/execution-derived fields -----------------------------------
    active_device_ids: List[str] = []
    execution_stage: Optional[str] = None
    current_task_summary: Optional[str] = None

    if execution_summary is not None:
        active_device_ids = list(execution_summary.active_device_ids)
        execution_stage = execution_summary.execution_stage
        current_task_summary = execution_summary.current_task_summary

    # --- Execution intent summary (PR-22) ----------------------------------
    execution_intent_summary: Optional[Dict] = None
    if intent_profile is not None:
        try:
            execution_intent_summary = intent_profile.compact_summary()
        except Exception as _exc:
            logger.warning(
                "build_runtime_projection: intent_profile.compact_summary() failed "
                "(intent_profile type=%s): %s",
                type(intent_profile).__name__,
                _exc,
            )

    # --- Governance summary (PR-26) ----------------------------------------
    governance: Optional[Dict] = None
    _governance_inputs = (intent_profile, readiness_result, fallback_trace, execution_trace_envelope)
    if any(x is not None for x in _governance_inputs):
        try:
            from .assembly_governance import assemble_projection_governance
            gov_summary = assemble_projection_governance(
                intent_profile=intent_profile,
                readiness_result=readiness_result,
                fallback_trace=fallback_trace,
                execution_trace_envelope=execution_trace_envelope,
                state_continuum=continuum_state,
                timestamp=ts,
            )
            governance = gov_summary.to_dict()
        except Exception as _gov_exc:
            logger.warning(
                "build_runtime_projection: governance assembly failed: %s",
                _gov_exc,
            )

    projection = RuntimeProjection(
        tri_state_phase=tri_state_phase,
        runtime_domain=runtime_domain,
        presence_intensity=presence_intensity,
        coherence=coherence,
        collapse_tendency=collapse_tendency,
        retreat_tendency=retreat_tendency,
        primary_model_id=primary_model_id,
        support_model_ids=support_model_ids,
        active_weights=active_weights,
        route_reason=route_reason,
        routing_authority=routing_authority,
        active_device_ids=active_device_ids,
        execution_stage=execution_stage,
        current_task_summary=current_task_summary,
        execution_intent_summary=execution_intent_summary,
        governance=governance,
        oneapi_summary=oneapi_summary,
        provider_status_summary=provider_status_summary,
        timestamp=ts,
    )

    logger.debug(
        "build_runtime_projection: %r  route=%s  devices=%s  intent=%s  governance=%s",
        projection,
        route_plan is not None,
        len(active_device_ids),
        intent_profile is not None,
        governance is not None,
    )
    return projection
