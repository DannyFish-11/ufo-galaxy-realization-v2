"""
core/model_topology/model_node.py
===================================
ModelNode — the atomic unit of the V2 model supply graph.

A ``ModelNode`` represents one provider/model slot in the topology graph.
It is constructible directly from a ``NormalizedTopologyEntry`` produced by
the PR-1 ConfigBridge, and carries the full data needed by the weight-field
and routing-policy layers.

Design
------
- Immutable provider / model / modality / scoring / availability identity.
- Mutable ``base_weight`` and ``dynamic_weight`` (updated by the weight field).
- ``topology_role`` is the *primary* role; ``role_hints`` is the full list.
- ``locality_hints`` expresses location preferences (local / remote / any).
- No UI semantics; no dashboard imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

from .topology_types import (
    AvailabilityStatus,
    ModalityCapability,
    ModelIdentity,
    NormalizedTopologyEntry,
    ProviderCategory,
    ProviderIdentity,
    ScoringProfile,
    TopologyRole,
)

logger = logging.getLogger("Galaxy.ModelTopology.ModelNode")


# ---------------------------------------------------------------------------
# EdgeKind — describes the relationship between two ModelNodes
# ---------------------------------------------------------------------------


class EdgeKind(str, Enum):
    """Typed edge in the model supply graph.

    SUPPORT:     Node B augments Node A (e.g. vision specialist supplements
                 a general-purpose core).
    SUBSTITUTE:  Node B can replace Node A when A is unavailable.
    AGGREGATE:   Node B aggregates / routes across a group that includes A.
    """

    SUPPORT = "support"
    SUBSTITUTE = "substitute"
    AGGREGATE = "aggregate"


# ---------------------------------------------------------------------------
# LocalityHint — expresses geographic / device-scope preference
# ---------------------------------------------------------------------------


class LocalityHint(str, Enum):
    """Locality preference for a node's execution scope."""

    LOCAL = "local"           # Prefers same-device execution
    REMOTE = "remote"         # Prefers remote / cloud execution
    CROSS_DEVICE = "cross_device"  # Optimised for cross-device fan-out
    ANY = "any"               # No strong preference


# ---------------------------------------------------------------------------
# ModelNode
# ---------------------------------------------------------------------------


@dataclass
class ModelNode:
    """Atomic unit of the model supply graph.

    Attributes
    ----------
    node_id:
        Unique identifier within the graph.  Convention: ``{provider_id}``.
    provider:
        Immutable provider identity (id + display_name).
    model:
        Immutable model identity (model_id + provider_id + alternatives).
    modality:
        Multimodal capability flags.
    scoring:
        Speed/quality scoring profile (1–10).
    availability:
        Whether the node is currently usable.
    category:
        Source/category classification.
    topology_role:
        Primary topological role used by routing policy.
    role_hints:
        Full list of role hints (may include secondary roles).
    locality_hints:
        Preferred execution scope(s).
    base_weight:
        Static weight derived from scoring + multimodal priority.
        Native multimodal nodes receive the highest base weight.
    dynamic_weight:
        Runtime-adjusted weight produced by ``ModelWeightField``.
        Starts equal to ``base_weight``; updated each routing cycle.
    raw_metadata:
        Pass-through of the original entry's raw metadata.
    """

    node_id: str
    provider: ProviderIdentity
    model: ModelIdentity
    modality: ModalityCapability
    scoring: ScoringProfile
    availability: AvailabilityStatus
    category: ProviderCategory = ProviderCategory.UNKNOWN
    topology_role: TopologyRole = TopologyRole.GENERAL
    role_hints: List[TopologyRole] = field(default_factory=list)
    locality_hints: List[LocalityHint] = field(default_factory=list)
    base_weight: float = 1.0
    dynamic_weight: float = 1.0
    raw_metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def is_available(self) -> bool:
        return self.availability.available

    @property
    def is_multimodal_native(self) -> bool:
        return self.modality.native_multimodal

    @property
    def is_cross_device_capable(self) -> bool:
        return (
            TopologyRole.CROSS_DEVICE in self.role_hints
            or LocalityHint.CROSS_DEVICE in self.locality_hints
        )

    def __repr__(self) -> str:
        avail = "✓" if self.is_available else "✗"
        mm = "MM" if self.is_multimodal_native else "--"
        return (
            f"<ModelNode {self.node_id} role={self.topology_role.value} "
            f"{mm} {avail} bw={self.base_weight:.2f} dw={self.dynamic_weight:.2f}>"
        )


# ---------------------------------------------------------------------------
# Construction helper
# ---------------------------------------------------------------------------

# Multimodal native nodes get this bonus multiplied on top of their composite.
_NATIVE_MULTIMODAL_BASE_MULTIPLIER = 1.5

# Primary role → base weight addend (stacked on top of composite score)
_ROLE_ADDEND: dict = {
    TopologyRole.MULTIMODAL_CORE: 2.0,
    TopologyRole.REASONING: 0.5,
    TopologyRole.EXECUTION: 0.3,
    TopologyRole.MEMORY: 0.2,
    TopologyRole.ROUTING: 0.1,
    TopologyRole.CROSS_DEVICE: 0.4,
    TopologyRole.GENERAL: 0.0,
    TopologyRole.UNKNOWN: 0.0,
}


def _compute_base_weight(entry: NormalizedTopologyEntry) -> float:
    """Derive a deterministic base weight from scoring + multimodal status.

    Formula:
        composite = (speed + quality) / 20   # normalised 0-1
        role_add  = _ROLE_ADDEND[primary_role]
        base      = (composite + role_add)
        if native_multimodal:
            base *= _NATIVE_MULTIMODAL_BASE_MULTIPLIER
    """
    composite = entry.scoring.composite_score / 10.0  # 0.0 – 1.0
    primary_role = (
        entry.role_hints[0] if entry.role_hints else TopologyRole.GENERAL
    )
    role_add = _ROLE_ADDEND.get(primary_role, 0.0)
    base = composite + role_add
    if entry.is_multimodal_native:
        base *= _NATIVE_MULTIMODAL_BASE_MULTIPLIER
    return round(base, 4)


def _infer_locality_hints(entry: NormalizedTopologyEntry) -> List[LocalityHint]:
    hints: List[LocalityHint] = []
    if entry.category == ProviderCategory.LOCAL:
        hints.append(LocalityHint.LOCAL)
    elif entry.category in (ProviderCategory.REMOTE, ProviderCategory.ONEAPI):
        hints.append(LocalityHint.REMOTE)
    if TopologyRole.CROSS_DEVICE in entry.role_hints:
        hints.append(LocalityHint.CROSS_DEVICE)
    if not hints:
        hints.append(LocalityHint.ANY)
    return hints


def node_from_entry(entry: NormalizedTopologyEntry) -> ModelNode:
    """Construct a ``ModelNode`` from a ``NormalizedTopologyEntry``.

    This is the canonical factory used by ``TopologyRouter`` / graph builders.
    """
    primary_role = entry.role_hints[0] if entry.role_hints else TopologyRole.GENERAL
    base_weight = _compute_base_weight(entry)
    locality_hints = _infer_locality_hints(entry)

    node = ModelNode(
        node_id=entry.provider.provider_id,
        provider=entry.provider,
        model=entry.model,
        modality=entry.modality,
        scoring=entry.scoring,
        availability=entry.availability,
        category=entry.category,
        topology_role=primary_role,
        role_hints=list(entry.role_hints),
        locality_hints=locality_hints,
        base_weight=base_weight,
        dynamic_weight=base_weight,  # starts equal to base
        raw_metadata=dict(entry.raw_metadata),
    )
    logger.debug("node_from_entry: created %r", node)
    return node
