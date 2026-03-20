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
from typing import Dict, List, Optional

from core.continuum.types import ContinuumState, RuntimeDomain

from .runtime_projection import RuntimeProjection

logger = logging.getLogger("Galaxy.Projection.ProjectionCompiler")

# TYPE_CHECKING import to avoid a circular dependency at runtime if
# topology_router ever imports from projection in the future.
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.model_topology.topology_router import TopologyRoutePlan


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

    if route_plan is not None:
        if route_plan.primary_model is not None:
            primary_model_id = route_plan.primary_model.node_id

        support_model_ids = [n.node_id for n in route_plan.support_models]

        # Flatten ModelWeightField → float (combined_weight)
        active_weights = {
            node_id: wf.combined_weight
            for node_id, wf in route_plan.active_weights.items()
        }

        route_reason = route_plan.route_reason

    # --- Device/execution-derived fields -----------------------------------
    active_device_ids: List[str] = []
    execution_stage: Optional[str] = None
    current_task_summary: Optional[str] = None

    if execution_summary is not None:
        active_device_ids = list(execution_summary.active_device_ids)
        execution_stage = execution_summary.execution_stage
        current_task_summary = execution_summary.current_task_summary

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
        active_device_ids=active_device_ids,
        execution_stage=execution_stage,
        current_task_summary=current_task_summary,
        timestamp=ts,
    )

    logger.debug(
        "build_runtime_projection: %r  route=%s  devices=%s",
        projection,
        route_plan is not None,
        len(active_device_ids),
    )
    return projection
