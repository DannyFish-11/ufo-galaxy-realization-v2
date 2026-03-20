"""
core/model_topology/model_weight_field.py
==========================================
ModelWeightField — deterministic weight computation for a ModelNode.

The weight field combines three multiplicative factors:

1. ``base_weight``      — static value derived from the node's scoring profile
                          and topology role (set once at construction time).
2. ``state_modifier``   — a tri-state phase multiplier (SILENT / LIMINAL /
                          MANIFEST) that re-weights the node's role according
                          to the current system phase.
3. ``domain_modifier``  — a runtime domain multiplier (LOCAL / CROSS_DEVICE /
                          TRANSITION) that adjusts for the execution scope.

The combined weight is::

    combined = base_weight * state_modifier * domain_modifier

Tie-breaking
------------
When two weight fields produce identical ``combined_weight`` values, ordering
is resolved by ``node_id`` lexicographic order (ascending).  This guarantees a
fully deterministic route plan regardless of dict/set iteration order.

Design
------
- No UI semantics.
- Stateless: calling ``compute()`` with the same inputs always returns the
  same result.
- ``apply_to_node()`` mutates ``node.dynamic_weight`` in-place.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.continuum.types import RuntimeDomain, TriStatePhase

from .model_node import ModelNode
from .topology_types import TopologyRole

logger = logging.getLogger("Galaxy.ModelTopology.ModelWeightField")


# ---------------------------------------------------------------------------
# Phase modifiers — per (TriStatePhase, TopologyRole) combination
# ---------------------------------------------------------------------------
#
# These are additive multipliers applied to the base_weight.  A value > 1
# amplifies the node; < 1 diminishes it; == 1 is neutral.

_PHASE_ROLE_MODIFIER: Dict[Tuple[TriStatePhase, TopologyRole], float] = {
    # ---- SILENT: emphasize multimodal + perception; minimize execution ----
    (TriStatePhase.SILENT, TopologyRole.MULTIMODAL_CORE): 1.4,
    (TriStatePhase.SILENT, TopologyRole.REASONING):        0.7,
    (TriStatePhase.SILENT, TopologyRole.EXECUTION):        0.3,  # minimized
    (TriStatePhase.SILENT, TopologyRole.MEMORY):           1.0,
    (TriStatePhase.SILENT, TopologyRole.ROUTING):          0.5,  # minimized
    (TriStatePhase.SILENT, TopologyRole.CROSS_DEVICE):     0.2,  # minimized
    (TriStatePhase.SILENT, TopologyRole.GENERAL):          0.8,
    (TriStatePhase.SILENT, TopologyRole.UNKNOWN):          0.6,
    # ---- LIMINAL: reasoning + routing aggregators up; multimodal anchor ----
    (TriStatePhase.LIMINAL, TopologyRole.MULTIMODAL_CORE): 1.3,  # anchor kept
    (TriStatePhase.LIMINAL, TopologyRole.REASONING):       1.3,  # increased
    (TriStatePhase.LIMINAL, TopologyRole.EXECUTION):       0.6,
    (TriStatePhase.LIMINAL, TopologyRole.MEMORY):          1.1,
    (TriStatePhase.LIMINAL, TopologyRole.ROUTING):         1.3,  # increased
    (TriStatePhase.LIMINAL, TopologyRole.CROSS_DEVICE):    1.0,
    (TriStatePhase.LIMINAL, TopologyRole.GENERAL):         0.9,
    (TriStatePhase.LIMINAL, TopologyRole.UNKNOWN):         0.7,
    # ---- MANIFEST: execution roles up; cross-device specialists allowed ----
    (TriStatePhase.MANIFEST, TopologyRole.MULTIMODAL_CORE): 1.2,
    (TriStatePhase.MANIFEST, TopologyRole.REASONING):       1.0,
    (TriStatePhase.MANIFEST, TopologyRole.EXECUTION):       1.4,  # increased
    (TriStatePhase.MANIFEST, TopologyRole.MEMORY):          1.0,
    (TriStatePhase.MANIFEST, TopologyRole.ROUTING):         1.0,
    (TriStatePhase.MANIFEST, TopologyRole.CROSS_DEVICE):    1.2,  # allowed
    (TriStatePhase.MANIFEST, TopologyRole.GENERAL):         1.0,
    (TriStatePhase.MANIFEST, TopologyRole.UNKNOWN):         0.8,
}

_DEFAULT_PHASE_MODIFIER = 1.0


# ---------------------------------------------------------------------------
# Domain modifiers — per (RuntimeDomain, TopologyRole)
# ---------------------------------------------------------------------------

_DOMAIN_ROLE_MODIFIER: Dict[Tuple[RuntimeDomain, TopologyRole], float] = {
    # LOCAL: prefer local-affine roles; penalise cross-device specialists
    (RuntimeDomain.LOCAL, TopologyRole.MULTIMODAL_CORE): 1.1,
    (RuntimeDomain.LOCAL, TopologyRole.REASONING):        1.0,
    (RuntimeDomain.LOCAL, TopologyRole.EXECUTION):        1.0,
    (RuntimeDomain.LOCAL, TopologyRole.MEMORY):           1.0,
    (RuntimeDomain.LOCAL, TopologyRole.ROUTING):          1.0,
    (RuntimeDomain.LOCAL, TopologyRole.CROSS_DEVICE):     0.4,  # penalized
    (RuntimeDomain.LOCAL, TopologyRole.GENERAL):          1.0,
    (RuntimeDomain.LOCAL, TopologyRole.UNKNOWN):          0.9,
    # CROSS_DEVICE: amplify cross-device specialists
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.MULTIMODAL_CORE): 1.1,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.REASONING):        1.0,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.EXECUTION):        1.1,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.MEMORY):           1.0,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.ROUTING):          1.1,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.CROSS_DEVICE):     1.5,  # amplified
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.GENERAL):          1.0,
    (RuntimeDomain.CROSS_DEVICE, TopologyRole.UNKNOWN):          0.9,
    # TRANSITION: neutral; slight boost to routing/arbiter nodes
    (RuntimeDomain.TRANSITION, TopologyRole.MULTIMODAL_CORE): 1.1,
    (RuntimeDomain.TRANSITION, TopologyRole.REASONING):        1.0,
    (RuntimeDomain.TRANSITION, TopologyRole.EXECUTION):        0.8,
    (RuntimeDomain.TRANSITION, TopologyRole.MEMORY):           1.0,
    (RuntimeDomain.TRANSITION, TopologyRole.ROUTING):          1.2,  # slight boost
    (RuntimeDomain.TRANSITION, TopologyRole.CROSS_DEVICE):     1.1,
    (RuntimeDomain.TRANSITION, TopologyRole.GENERAL):          0.9,
    (RuntimeDomain.TRANSITION, TopologyRole.UNKNOWN):          0.8,
}

_DEFAULT_DOMAIN_MODIFIER = 1.0


# ---------------------------------------------------------------------------
# ModelWeightField
# ---------------------------------------------------------------------------


@dataclass
class ModelWeightField:
    """Deterministic weight computation record for one ModelNode.

    Attributes
    ----------
    node_id:
        The node this field belongs to (for tie-breaking and tracing).
    base_weight:
        Static weight derived from the node at construction time.
    state_modifier:
        Multiplier derived from ``(TriStatePhase, TopologyRole)`` table.
    domain_modifier:
        Multiplier derived from ``(RuntimeDomain, TopologyRole)`` table.
    combined_weight:
        ``base_weight * state_modifier * domain_modifier`` (rounded to 6 dp).
    """

    node_id: str
    base_weight: float
    state_modifier: float = 1.0
    domain_modifier: float = 1.0
    combined_weight: float = field(init=False)

    def __post_init__(self) -> None:
        self._recompute()

    def _recompute(self) -> None:
        self.combined_weight = round(
            self.base_weight * self.state_modifier * self.domain_modifier, 6
        )

    # ------------------------------------------------------------------
    # Comparison (deterministic: combined desc, node_id asc for ties)
    # ------------------------------------------------------------------

    def __lt__(self, other: "ModelWeightField") -> bool:
        if self.combined_weight != other.combined_weight:
            return self.combined_weight > other.combined_weight  # descending
        return self.node_id < other.node_id  # ascending tie-break

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ModelWeightField):
            return NotImplemented
        return (
            self.combined_weight == other.combined_weight
            and self.node_id == other.node_id
        )

    def __repr__(self) -> str:
        return (
            f"<WeightField {self.node_id} "
            f"base={self.base_weight:.4f} "
            f"state×={self.state_modifier:.2f} "
            f"domain×={self.domain_modifier:.2f} "
            f"→ {self.combined_weight:.6f}>"
        )


# ---------------------------------------------------------------------------
# Public factory
# ---------------------------------------------------------------------------


def compute_weight_field(
    node: ModelNode,
    phase: TriStatePhase,
    domain: RuntimeDomain,
) -> ModelWeightField:
    """Compute a ``ModelWeightField`` for *node* given *phase* and *domain*.

    The modifiers are read from the policy tables above.  Unknown combinations
    fall back to 1.0 (neutral).
    """
    role = node.topology_role
    state_mod = _PHASE_ROLE_MODIFIER.get((phase, role), _DEFAULT_PHASE_MODIFIER)
    domain_mod = _DOMAIN_ROLE_MODIFIER.get((domain, role), _DEFAULT_DOMAIN_MODIFIER)

    wf = ModelWeightField(
        node_id=node.node_id,
        base_weight=node.base_weight,
        state_modifier=state_mod,
        domain_modifier=domain_mod,
    )
    logger.debug("compute_weight_field: %r", wf)
    return wf


def apply_weight_fields(
    nodes: List[ModelNode],
    phase: TriStatePhase,
    domain: RuntimeDomain,
) -> List[Tuple[ModelNode, ModelWeightField]]:
    """Compute weight fields for a list of nodes and sort them deterministically.

    Returns a list of ``(node, weight_field)`` pairs sorted by
    ``weight_field`` (combined_weight desc, node_id asc for ties).
    """
    pairs = [(n, compute_weight_field(n, phase, domain)) for n in nodes]
    pairs.sort(key=lambda p: p[1])
    # Also update the node's dynamic_weight in-place
    for node, wf in pairs:
        node.dynamic_weight = wf.combined_weight
    return pairs
