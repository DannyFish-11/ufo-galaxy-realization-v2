"""
core/model_topology/topology_router.py
=========================================
TopologyRouter — consumes a ``ProviderInventory`` + ``AggregatorRouterHint``
list and produces a ``TopologyRoutePlan``.

Architecture
------------
    ProviderInventory  ──┐
                         ├──▶  TopologyRouter  ──▶  TopologyRoutePlan
    AggregatorRouterHint ┘         │
                                   └─ builds ModelSupplyGraph
                                      applies ModelWeightField per node
                                      runs routing_policy selection

``TopologyRoutePlan`` is the stable output contract consumed by downstream
layers (execution arbiter, status board projection, etc.).

Canonical Routing Authority
---------------------------
**This module is the single canonical model-routing authority.**

- ``TopologyRouter`` is the sole canonical routing decision-maker.
- ``TopologyRoutePlan`` is the sole canonical routing output contract.
- All projection-facing routing fields (selected model, selected provider,
  native multimodal flag, support models, route reason, weights) must be
  sourced from a ``TopologyRoutePlan`` whenever one is available.

The ``CANONICAL_ROUTING_AUTHORITY`` sentinel (below) identifies this module
as the authority source for runtime diagnostics and guardrail tooling.

Legacy routing helpers (``MultiLLMRouter``, dashboard provider endpoints,
top-level ``chosen_model``/``chosen_provider`` UCP keys) are compatibility
bridges only.  See ``docs/MODEL_ROUTING_AUTHORITY.md`` for the full policy.

Design
------
- Deterministic: same inputs → same output.
- Additive: does not modify any existing routing/LLM-manager code.
- No UI semantics; no dashboard imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from core.continuum.types import RuntimeDomain, TriStatePhase

from .model_node import ModelNode
from .model_supply_graph import ModelSupplyGraph
from .model_weight_field import ModelWeightField, apply_weight_fields, compute_weight_field
from .provider_inventory import ProviderInventory
from .routing_policy import (
    PolicyConfig,
    _DEFAULT_POLICY_CONFIG,
    _build_route_reason,
    _select_primary_node,
    _select_support_nodes,
)
from .topology_types import AggregatorRouterHint

logger = logging.getLogger("Galaxy.ModelTopology.TopologyRouter")

# ---------------------------------------------------------------------------
# Canonical routing authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the **single canonical model-routing authority**.
#:
#: Downstream consumers (projection builders, diagnostics, guardrail tooling)
#: can compare against this value to assert that routing data originates from
#: the topology-routing path rather than legacy scattered sources.
#:
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` for the full routing authority policy.
CANONICAL_ROUTING_AUTHORITY: str = "core.model_topology.topology_router.TopologyRouter"


# ---------------------------------------------------------------------------
# TopologyRoutePlan — output of the router
# ---------------------------------------------------------------------------


@dataclass
class TopologyRoutePlan:
    """The canonical routing output contract produced by ``TopologyRouter``.

    This is the **sole** canonical routing output contract for downstream
    projection consumers (execution arbiter, status-board projection, desktop
    topology surface, etc.).  Downstream surfaces must source all routing truth
    from a ``TopologyRoutePlan`` when one is available, and must not reconstruct
    routing conclusions from legacy scattered keys (``chosen_model``,
    ``chosen_provider``, ``MultiLLMRouter`` summaries, or dashboard-era UCP
    fields).

    Attributes
    ----------
    primary_model:
        The top-ranked model node selected as the primary supply.
        ``None`` only when the inventory is completely empty.
    support_models:
        Ordered list of supporting model nodes (up to ``max_support_models``).
    active_weights:
        Mapping of node_id → ``ModelWeightField`` for every node considered
        during this routing cycle.  Carries the full weight breakdown
        (base_weight, state_modifier, domain_modifier, combined_weight) for
        all considered nodes, not only those selected.
    route_reason:
        Human-readable string explaining the routing decision.
    phase:
        The ``TriStatePhase`` used for this plan.
    domain:
        The ``RuntimeDomain`` used for this plan.
    graph:
        The ``ModelSupplyGraph`` constructed for this plan (available for
        inspection / downstream use).

    Serialisation
    -------------
    ``to_dict()`` is the **stable serialisation pathway** consumed by
    downstream projection builders.  It exposes the complete canonical
    primary/support/route-metadata/weight semantics required by later
    projection and desktop-status-board PRs.
    """

    primary_model: Optional[ModelNode]
    support_models: List[ModelNode]
    active_weights: Dict[str, ModelWeightField]
    route_reason: str
    phase: TriStatePhase
    domain: RuntimeDomain
    graph: ModelSupplyGraph

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _node_to_dict(node: ModelNode, wf: ModelWeightField) -> dict:
        """Serialize a single ``ModelNode`` with its weight field.

        Returns the canonical per-node shape consumed by downstream
        projection layers:

        - ``node_id``          — unique identity in the supply graph
        - ``model_id``         — canonical model identifier
        - ``provider_id``      — canonical provider identity
        - ``vendor_source``    — provider category (direct / oneapi / local …)
        - ``native_multimodal``— whether the node handles media natively
        - ``topology_role``    — primary topological role
        - ``combined_weight``  — effective weight for this routing cycle
        """
        return {
            "node_id": node.node_id,
            "model_id": node.model.model_id,
            "provider_id": node.provider.provider_id,
            "vendor_source": node.category.value,
            "native_multimodal": node.is_multimodal_native,
            "topology_role": node.topology_role.value,
            "combined_weight": wf.combined_weight,
        }

    def to_dict(self) -> dict:
        """Return the stable serialised form of this route plan.

        This is the canonical downstream-facing representation.  All
        projection builders consuming routing truth should use this dict
        rather than reading raw ``ModelNode`` attributes directly, so that
        the contract can evolve in one place.

        Top-level keys
        --------------
        phase, domain         — routing context
        primary_model         — canonical primary model record (or ``None``)
        support_models        — list of canonical support model records
        route_reason          — human-readable routing rationale
        authority             — ``CANONICAL_ROUTING_AUTHORITY`` sentinel;
                                downstream can assert this is present to
                                confirm the plan originated from the
                                topology-routing path
        active_weights        — full weight breakdown for every node
                                considered in this cycle (node_id →
                                {base, state_modifier, domain_modifier,
                                combined}); allows downstream to understand
                                which nodes were evaluated and at what weight
        graph_stats           — summary statistics from the supply graph
        """
        def _wf_for(node: ModelNode) -> ModelWeightField:
            return self.active_weights.get(
                node.node_id,
                compute_weight_field(node, self.phase, self.domain),
            )

        return {
            "phase": self.phase.value,
            "domain": self.domain.value,
            "primary_model": (
                self._node_to_dict(self.primary_model, _wf_for(self.primary_model))
                if self.primary_model
                else None
            ),
            "support_models": [
                self._node_to_dict(n, _wf_for(n))
                for n in self.support_models
            ],
            "route_reason": self.route_reason,
            "authority": CANONICAL_ROUTING_AUTHORITY,
            "active_weights": {
                node_id: {
                    "base_weight": wf.base_weight,
                    "state_modifier": wf.state_modifier,
                    "domain_modifier": wf.domain_modifier,
                    "combined_weight": wf.combined_weight,
                }
                for node_id, wf in self.active_weights.items()
            },
            "graph_stats": self.graph.to_dict()["stats"],
        }

    def __repr__(self) -> str:
        primary_id = self.primary_model.node_id if self.primary_model else "None"
        support_ids = [n.node_id for n in self.support_models]
        return (
            f"<TopologyRoutePlan phase={self.phase.value} "
            f"domain={self.domain.value} "
            f"primary={primary_id} "
            f"support={support_ids}>"
        )


# ---------------------------------------------------------------------------
# TopologyRouter
# ---------------------------------------------------------------------------


class TopologyRouter:
    """Builds a ``ModelSupplyGraph`` from a ``ProviderInventory`` and produces
    deterministic ``TopologyRoutePlan`` objects.

    Usage::

        router = TopologyRouter(inventory)
        plan = router.route(TriStatePhase.SILENT, RuntimeDomain.LOCAL)
    """

    def __init__(
        self,
        inventory: ProviderInventory,
        policy_config: Optional[PolicyConfig] = None,
    ) -> None:
        self._inventory = inventory
        self._policy_config = policy_config or _DEFAULT_POLICY_CONFIG
        self._graph = ModelSupplyGraph.from_inventory(inventory)
        logger.info(
            "TopologyRouter initialised: %r", self._graph
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def graph(self) -> ModelSupplyGraph:
        """The ``ModelSupplyGraph`` built from the inventory."""
        return self._graph

    def route(
        self,
        phase: TriStatePhase,
        domain: RuntimeDomain,
    ) -> TopologyRoutePlan:
        """Produce a ``TopologyRoutePlan`` for *phase* and *domain*.

        The plan is fully deterministic: identical inputs always yield an
        identical plan.

        Args:
            phase:  The current ``TriStatePhase``.
            domain: The current ``RuntimeDomain``.

        Returns:
            A populated ``TopologyRoutePlan``.
        """
        config = self._policy_config
        graph = self._graph

        # --- Primary selection -------------------------------------------
        primary_pair = _select_primary_node(graph, phase, domain, config)
        primary_node: Optional[ModelNode] = primary_pair[0] if primary_pair else None
        primary_wf: Optional[ModelWeightField] = primary_pair[1] if primary_pair else None

        # --- Support selection -------------------------------------------
        primary_id = primary_node.node_id if primary_node else "__none__"
        support_pairs = _select_support_nodes(graph, phase, domain, primary_id, config)
        support_nodes = [n for n, _ in support_pairs]

        # --- Collect active weights for all nodes in the plan ------------
        active_weights: Dict[str, ModelWeightField] = {}
        if primary_node and primary_wf:
            active_weights[primary_node.node_id] = primary_wf
        for node, wf in support_pairs:
            active_weights[node.node_id] = wf

        # --- Build route reason ------------------------------------------
        reason = _build_route_reason(phase, domain, primary_node, len(support_nodes))

        plan = TopologyRoutePlan(
            primary_model=primary_node,
            support_models=support_nodes,
            active_weights=active_weights,
            route_reason=reason,
            phase=phase,
            domain=domain,
            graph=graph,
        )
        logger.info("TopologyRouter.route: %r", plan)
        return plan

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def route_all_phases(
        self, domain: RuntimeDomain = RuntimeDomain.LOCAL
    ) -> Dict[str, TopologyRoutePlan]:
        """Produce plans for all three public tri-state phases.

        Returns a mapping of ``phase.value → TopologyRoutePlan``.
        """
        return {
            phase.value: self.route(phase, domain)
            for phase in (
                TriStatePhase.SILENT,
                TriStatePhase.LIMINAL,
                TriStatePhase.MANIFEST,
            )
        }
