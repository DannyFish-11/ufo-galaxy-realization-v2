"""
core/model_topology/model_supply_graph.py
==========================================
ModelSupplyGraph — the typed graph of ModelNode objects.

The graph holds:
- A **node registry** keyed by ``node_id``.
- Typed **edges** (SUPPORT / SUBSTITUTE / AGGREGATE) between nodes.
- Query helpers consumed by the routing layer.

Design
------
- Constructed from a ``ProviderInventory`` (via ``ModelSupplyGraph.from_inventory``).
- Edges are inferred from ``AggregatorRouterHint`` objects or can be added
  explicitly.
- No UI semantics; no dashboard imports.
- Deterministic ordering: ties broken by ``node_id`` lexicographic order.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .model_node import EdgeKind, ModelNode, node_from_entry
from .provider_inventory import ProviderInventory, ProviderInventoryEntry
from .topology_types import (
    AggregatorKind,
    AggregatorRouterHint,
    NormalizedTopologyEntry,
    ProviderCategory,
    TopologyRole,
)

logger = logging.getLogger("Galaxy.ModelTopology.ModelSupplyGraph")


# ---------------------------------------------------------------------------
# GraphEdge
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GraphEdge:
    """A directed, typed edge between two nodes in the supply graph."""

    source_node_id: str
    target_node_id: str
    kind: EdgeKind
    weight: float = 1.0

    def __repr__(self) -> str:
        return (
            f"<GraphEdge {self.source_node_id} --[{self.kind.value}]--> "
            f"{self.target_node_id} w={self.weight:.2f}>"
        )


# ---------------------------------------------------------------------------
# ModelSupplyGraph
# ---------------------------------------------------------------------------


class ModelSupplyGraph:
    """Typed graph of ModelNode objects with support/substitute/aggregate edges.

    Typical lifecycle::

        graph = ModelSupplyGraph.from_inventory(inventory)
        cores = graph.primary_multimodal_cores()
        available = graph.nodes_by_role(TopologyRole.REASONING)
    """

    def __init__(self) -> None:
        self._nodes: Dict[str, ModelNode] = {}
        self._edges: List[GraphEdge] = []

    # ------------------------------------------------------------------
    # Node registry
    # ------------------------------------------------------------------

    def add_node(self, node: ModelNode) -> None:
        """Add a node to the registry (overwrites on duplicate node_id)."""
        if node.node_id in self._nodes:
            logger.warning(
                "ModelSupplyGraph: duplicate node_id '%s'; overwriting.", node.node_id
            )
        self._nodes[node.node_id] = node

    def get_node(self, node_id: str) -> Optional[ModelNode]:
        return self._nodes.get(node_id)

    def all_nodes(self) -> List[ModelNode]:
        return list(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    def __iter__(self) -> Iterator[ModelNode]:
        return iter(self._nodes.values())

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    # ------------------------------------------------------------------
    # Edge registry
    # ------------------------------------------------------------------

    def add_edge(self, edge: GraphEdge) -> None:
        """Add an edge.  Duplicate edges are silently ignored."""
        if edge not in self._edges:
            self._edges.append(edge)

    def edges(self) -> List[GraphEdge]:
        return list(self._edges)

    def edges_from(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self._edges if e.source_node_id == node_id]

    def edges_to(self, node_id: str) -> List[GraphEdge]:
        return [e for e in self._edges if e.target_node_id == node_id]

    def edges_of_kind(self, kind: EdgeKind) -> List[GraphEdge]:
        return [e for e in self._edges if e.kind == kind]

    # ------------------------------------------------------------------
    # Query helpers (deterministic: ties broken by node_id lexicographic)
    # ------------------------------------------------------------------

    def available_nodes(self) -> List[ModelNode]:
        """All nodes whose availability flag is True."""
        return sorted(
            [n for n in self._nodes.values() if n.is_available],
            key=lambda n: (-n.base_weight, n.node_id),
        )

    def primary_multimodal_cores(self, available_only: bool = True) -> List[ModelNode]:
        """Native multimodal nodes sorted by base_weight descending.

        These are the top-priority supply candidates per the design principle
        "native multimodal has highest base priority".
        """
        pool = self.available_nodes() if available_only else self.all_nodes()
        return sorted(
            [n for n in pool if n.is_multimodal_native],
            key=lambda n: (-n.base_weight, n.node_id),
        )

    def nodes_by_role(
        self, role: TopologyRole, available_only: bool = True
    ) -> List[ModelNode]:
        """Nodes whose primary topology_role (or role_hints) matches ``role``."""
        pool = self.available_nodes() if available_only else self.all_nodes()
        return sorted(
            [n for n in pool if role in n.role_hints or n.topology_role == role],
            key=lambda n: (-n.base_weight, n.node_id),
        )

    def nodes_by_category(
        self, category: ProviderCategory, available_only: bool = True
    ) -> List[ModelNode]:
        pool = self.available_nodes() if available_only else self.all_nodes()
        return sorted(
            [n for n in pool if n.category == category],
            key=lambda n: (-n.base_weight, n.node_id),
        )

    def nodes_by_provider(
        self, provider_id: str, available_only: bool = True
    ) -> List[ModelNode]:
        pool = self.available_nodes() if available_only else self.all_nodes()
        return [n for n in pool if n.provider.provider_id == provider_id]

    def cross_device_capable_nodes(self, available_only: bool = True) -> List[ModelNode]:
        pool = self.available_nodes() if available_only else self.all_nodes()
        return sorted(
            [n for n in pool if n.is_cross_device_capable],
            key=lambda n: (-n.base_weight, n.node_id),
        )

    # ------------------------------------------------------------------
    # Construction from ProviderInventory
    # ------------------------------------------------------------------

    @classmethod
    def from_inventory(cls, inventory: ProviderInventory) -> "ModelSupplyGraph":
        """Build a ``ModelSupplyGraph`` from a ``ProviderInventory``.

        Nodes are created via ``node_from_entry`` for every inventory entry.
        Edges are inferred from ``inventory.aggregator_hints``.
        """
        graph = cls()

        # 1. Populate node registry
        for inv_entry in inventory:
            node = node_from_entry(inv_entry.entry)
            graph.add_node(node)

        logger.info(
            "ModelSupplyGraph.from_inventory: %d nodes registered.", len(graph)
        )

        # 2. Infer edges from aggregator hints
        _infer_edges_from_hints(graph, inventory.aggregator_hints)

        return graph

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: _node_to_dict(n) for nid, n in self._nodes.items()},
            "edges": [
                {
                    "source": e.source_node_id,
                    "target": e.target_node_id,
                    "kind": e.kind.value,
                    "weight": e.weight,
                }
                for e in self._edges
            ],
            "stats": {
                "total_nodes": len(self._nodes),
                "available_nodes": len(self.available_nodes()),
                "multimodal_cores": len(self.primary_multimodal_cores()),
                "total_edges": len(self._edges),
            },
        }

    def __repr__(self) -> str:
        return (
            f"<ModelSupplyGraph nodes={len(self._nodes)} "
            f"edges={len(self._edges)} "
            f"available={len(self.available_nodes())} "
            f"mm_cores={len(self.primary_multimodal_cores())}>"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _node_to_dict(node: ModelNode) -> dict:
    return {
        "node_id": node.node_id,
        "provider_id": node.provider.provider_id,
        "model_id": node.model.model_id,
        "topology_role": node.topology_role.value,
        "role_hints": [r.value for r in node.role_hints],
        "available": node.is_available,
        "native_multimodal": node.is_multimodal_native,
        "base_weight": node.base_weight,
        "dynamic_weight": node.dynamic_weight,
        "locality_hints": [h.value for h in node.locality_hints],
        "category": node.category.value,
        "speed_score": node.scoring.speed_score,
        "quality_score": node.scoring.quality_score,
    }


# AggregatorKind → TopologyRole mapping used for AGGREGATE edge inference
_AGGREGATOR_KIND_TO_ROLE: Dict[AggregatorKind, TopologyRole] = {
    AggregatorKind.MULTIMODAL_CORE_AGGREGATOR: TopologyRole.MULTIMODAL_CORE,
    AggregatorKind.REASONING_AGGREGATOR: TopologyRole.REASONING,
    AggregatorKind.EXECUTION_AGGREGATOR: TopologyRole.EXECUTION,
    AggregatorKind.MEMORY_AGGREGATOR: TopologyRole.MEMORY,
    AggregatorKind.ROUTE_ARBITER: TopologyRole.ROUTING,
    AggregatorKind.CROSS_DEVICE_AGGREGATOR: TopologyRole.CROSS_DEVICE,
}


def _infer_edges_from_hints(
    graph: ModelSupplyGraph,
    hints: List[AggregatorRouterHint],
) -> None:
    """Derive AGGREGATE + SUPPORT edges from aggregator hints.

    For each hint:
    - The first candidate is treated as the aggregator anchor.
    - Subsequent candidates get an AGGREGATE edge from the anchor.
    - Nodes in the graph that match the hint's role get a SUPPORT edge
      pointing toward the anchor.
    """
    for hint in hints:
        role = _AGGREGATOR_KIND_TO_ROLE.get(hint.kind)
        candidates = [c for c in hint.candidate_provider_ids if c in graph]

        if not candidates:
            continue

        anchor = candidates[0]
        for other in candidates[1:]:
            graph.add_edge(
                GraphEdge(
                    source_node_id=anchor,
                    target_node_id=other,
                    kind=EdgeKind.AGGREGATE,
                )
            )

        # SUPPORT edges: graph nodes with matching role → anchor
        if role is not None:
            for node in graph.nodes_by_role(role, available_only=False):
                if node.node_id != anchor and node.node_id not in candidates:
                    graph.add_edge(
                        GraphEdge(
                            source_node_id=node.node_id,
                            target_node_id=anchor,
                            kind=EdgeKind.SUPPORT,
                        )
                    )
