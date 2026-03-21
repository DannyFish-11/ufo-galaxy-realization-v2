"""
core/projection/runtime_projection.py
======================================
RuntimeProjection — the unified projection contract for OpenClawd status boards
and spatial projection layers.

This module defines a **single additive object** that aggregates the most
important runtime signals into one wire-safe, serialisable schema.

Sources
-------
- :class:`~core.continuum.types.ContinuumState` — tri-state phase, runtime
  domain, and presence/coherence/tendency metrics.
- :class:`~core.model_topology.topology_router.TopologyRoutePlan` — primary
  model, support models, active weights, and route reason from PR-2.
- Optional device/execution summary fields — active device IDs, execution stage,
  and task summary (populated by callers when available; default to empty/None).

Design principles
-----------------
- **No UI semantics** — this module carries no widget, page, or view references.
- **Additive** — does not modify any existing API, state, or routing modules.
- **Fully serialisable** — :meth:`RuntimeProjection.to_dict` and
  :meth:`RuntimeProjection.to_json` produce stable, round-trippable output.
- **Optional-safe** — all fields from external sources are optional so that a
  minimal projection (continuum state only) is always valid.

Usage::

    from core.projection import RuntimeProjection, build_runtime_projection

    projection = build_runtime_projection(continuum_state, route_plan)
    payload = projection.to_dict()
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from core.continuum.types import RuntimeDomain, TriStatePhase


# ---------------------------------------------------------------------------
# RuntimeProjection
# ---------------------------------------------------------------------------


class RuntimeProjection(BaseModel):
    """Unified projection object that combines all major runtime dimensions.

    Produced by :func:`~core.projection.projection_compiler.build_runtime_projection`
    from a :class:`~core.continuum.types.ContinuumState` and an optional
    :class:`~core.model_topology.topology_router.TopologyRoutePlan`.

    All fields sourced from optional inputs carry ``None`` or empty-collection
    defaults so that the object is always constructable even when only minimal
    information is available.

    Fields
    ------
    tri_state_phase
        The public three-state view of the system (silent / liminal / manifest).
        Always populated; never ``None``.
    runtime_domain
        Execution domain (local / cross_device / transition).  ``None`` when
        the domain has not yet been resolved (early formless phase).
    presence_intensity
        EMA-smoothed overall presence strength [0, 1].
    coherence
        Degree to which sensed signals form a coherent intent [0, 1].
    collapse_tendency
        Probability mass pushing toward phase collapse (liminal → manifest) [0, 1].
    retreat_tendency
        Probability mass pushing toward retreat [0, 1].
    primary_model_id
        ID of the top-ranked model node from the topology route plan.
        ``None`` when no route plan was provided or the inventory is empty.
    support_model_ids
        Ordered list of supporting model node IDs.
    active_weights
        Mapping of ``model_id → combined_weight`` for every model node
        considered during the last routing cycle.
    route_reason
        Human-readable explanation of the last routing decision.
    active_device_ids
        IDs of devices currently considered active.  Populated by callers
        that have device-management context; defaults to an empty list.
    execution_stage
        Freeform tag describing the current execution stage
        (e.g. ``"planning"``, ``"executing"``, ``"completing"``).
    current_task_summary
        Short human-readable summary of the task currently in progress.
    timestamp
        Unix epoch seconds when this projection was assembled.
    """

    tri_state_phase: TriStatePhase = Field(
        description="Public three-state view of the system (silent / liminal / manifest).",
    )
    runtime_domain: Optional[RuntimeDomain] = Field(
        default=None,
        description="Execution domain (local / cross_device / transition). None if undetermined.",
    )
    presence_intensity: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="EMA-smoothed overall presence strength [0, 1].",
    )
    coherence: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Degree to which signals form a coherent intent [0, 1].",
    )
    collapse_tendency: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Probability mass toward phase collapse [0, 1].",
    )
    retreat_tendency: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Probability mass toward retreat [0, 1].",
    )
    primary_model_id: Optional[str] = Field(
        default=None,
        description="Top-ranked model node ID from the topology route plan.",
    )
    support_model_ids: List[str] = Field(
        default_factory=list,
        description="Ordered list of supporting model node IDs.",
    )
    active_weights: Dict[str, float] = Field(
        default_factory=dict,
        description="Mapping of model_id → combined_weight for all routed nodes.",
    )
    route_reason: Optional[str] = Field(
        default=None,
        description="Human-readable explanation of the last routing decision.",
    )
    active_device_ids: List[str] = Field(
        default_factory=list,
        description="IDs of currently active devices.",
    )
    execution_stage: Optional[str] = Field(
        default=None,
        description="Current execution stage tag (e.g. 'planning', 'executing').",
    )
    current_task_summary: Optional[str] = Field(
        default=None,
        description="Short summary of the task currently in progress.",
    )
    execution_intent_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Compact summary of the current ExecutionIntentProfile (PR-22). "
            "Populated by build_runtime_projection when an intent profile is available. "
            "Read-only surface for governance/debug consumers."
        ),
    )
    governance: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Governance-enriched projection summary (PR-26). "
            "Contains projection-safe summaries of execution intent (PR-22), "
            "readiness/policy posture (PR-23), fallback decision trace (PR-24), "
            "and execution lifecycle trace (PR-25). "
            "Populated by build_runtime_projection when governance inputs are provided. "
            "None when no governance inputs were available. "
            "Read-only surface; does not affect base projection behaviour."
        ),
    )
    runtime_governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Unified runtime governance snapshot (PR-27). "
            "Assembles the complete runtime posture — tri-state phase, runtime domain, "
            "execution intent (PR-22), readiness/policy posture (PR-23), fallback trace "
            "(PR-24), execution lifecycle trace (PR-25), and projection governance (PR-26) "
            "— into one canonical, serialisable object. "
            "Populated when a RuntimeGovernanceSnapshot is available. "
            "None when no snapshot was assembled. "
            "Read-only surface; does not affect base projection behaviour."
        ),
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this projection was assembled.",
    )

    model_config = {"from_attributes": True}

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        """Return a plain dict representation suitable for JSON serialisation.

        Enum values are serialised to their string ``value``; ``None`` fields
        are preserved so that consumers can distinguish "not set" from "0".
        """
        return {
            "tri_state_phase": self.tri_state_phase.value,
            "runtime_domain": (
                self.runtime_domain.value if self.runtime_domain is not None else None
            ),
            "presence_intensity": self.presence_intensity,
            "coherence": self.coherence,
            "collapse_tendency": self.collapse_tendency,
            "retreat_tendency": self.retreat_tendency,
            "primary_model_id": self.primary_model_id,
            "support_model_ids": list(self.support_model_ids),
            "active_weights": dict(self.active_weights),
            "route_reason": self.route_reason,
            "active_device_ids": list(self.active_device_ids),
            "execution_stage": self.execution_stage,
            "current_task_summary": self.current_task_summary,
            "execution_intent_summary": self.execution_intent_summary,
            "governance": self.governance,
            "runtime_governance_snapshot": self.runtime_governance_snapshot,
            "timestamp": self.timestamp,
        }

    def to_json(self, **dumps_kwargs) -> str:
        """Return a JSON string representation of this projection.

        Args:
            **dumps_kwargs: Extra keyword arguments forwarded to :func:`json.dumps`.

        Returns:
            A compact, stable JSON string.
        """
        return json.dumps(self.to_dict(), **dumps_kwargs)

    def __repr__(self) -> str:
        return (
            f"<RuntimeProjection "
            f"phase={self.tri_state_phase.value} "
            f"domain={self.runtime_domain.value if self.runtime_domain else 'None'} "
            f"primary={self.primary_model_id!r} "
            f"devices={self.active_device_ids}>"
        )
