#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/network_graph_runtime.py
==============================
PR-7: Network Graph Runtime — Canonical Fabric / Route Topology Graph.

Tracks every assimilated node as a **fabric participant**, **reachable
endpoint**, or **route participant** so that the system has a single
observable, serialisable view of the network topology at runtime.

Architecture role
-----------------
This runtime is the third canonical system graph (alongside the
``capability graph`` backed by ``NodeFabricRegistry`` and the
``task graph runtime`` in ``core.task_graph_runtime``).

::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  NETWORK GRAPH RUNTIME  (this module)                               │
    │  Tracks: fabric_participant | reachable_endpoint | route_participant │
    │                                                                      │
    │  Edges: fabric_link (two nodes share a fabric layer)                 
    │         route_hint  (one node advertises a route to another)         │
    └──────────────────────────────────────────────────────────────────────┘
               ↑ projected from CapabilityAssimilationLayer

Invariants
----------
1.  ``NetworkGraphRuntime`` is the sole authority for the network topology
    view.  Callers must not maintain their own parallel topology maps.
2.  All node registrations originate from the assimilation layer; direct
    calls to ``register_node`` are allowed only for testing or explicit
    topology management.
3.  A 256-entry observability ring buffer records all topology changes.

Public API
----------
Authority sentinels:
    NETWORK_GRAPH_RUNTIME_AUTHORITY
    NETWORK_GRAPH_RUNTIME_LAYER_POSITION
    NETWORK_GRAPH_CONTRACT_VERSION

Enumerations:
    NetworkNodeRole
    NetworkEdgeKind

Dataclasses:
    NetworkNode
    NetworkEdge
    NetworkGraphRecord
    NetworkGraphSnapshot

Class:
    NetworkGraphRuntime

Helpers:
    get_network_graph_runtime() -> NetworkGraphRuntime
    reset_network_graph_runtime() -> None  # for testing
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.NetworkGraphRuntime")

__all__ = [
    # Authority sentinels
    "NETWORK_GRAPH_RUNTIME_AUTHORITY",
    "NETWORK_GRAPH_RUNTIME_LAYER_POSITION",
    "NETWORK_GRAPH_CONTRACT_VERSION",
    # Enumerations
    "NetworkNodeRole",
    "NetworkEdgeKind",
    # Dataclasses
    "NetworkNode",
    "NetworkEdge",
    "NetworkGraphRecord",
    "NetworkGraphSnapshot",
    # Class
    "NetworkGraphRuntime",
    # Helpers
    "get_network_graph_runtime",
    "reset_network_graph_runtime",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Module authority marker.
NETWORK_GRAPH_RUNTIME_AUTHORITY: str = (
    "core.network_graph_runtime"
    " — canonical fabric/route topology graph runtime (PR-7)"
)

#: Layer position within the canonical control-plane stack.
NETWORK_GRAPH_RUNTIME_LAYER_POSITION: int = 7

#: Contract version for serialised network graph objects.
NETWORK_GRAPH_CONTRACT_VERSION: str = "v1"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NetworkNodeRole(str, Enum):
    """Role of a node in the network graph.

    ``FABRIC_PARTICIPANT``
        Node is present in the system fabric and reachable via some transport.
    ``REACHABLE_ENDPOINT``
        Node exposes a known host:port endpoint that can be directly addressed.
    ``ROUTE_PARTICIPANT``
        Node participates in routing decisions (e.g. relay, gateway, mesh).
    ``UNKNOWN``
        Role not yet determined.
    """

    FABRIC_PARTICIPANT = "fabric_participant"
    REACHABLE_ENDPOINT = "reachable_endpoint"
    ROUTE_PARTICIPANT = "route_participant"
    UNKNOWN = "unknown"


class NetworkEdgeKind(str, Enum):
    """Kind of a directed edge in the network graph.

    ``FABRIC_LINK``
        Two nodes share a common fabric layer (e.g. same NATS cluster).
    ``ROUTE_HINT``
        Source node advertises a transport route to the target node.
    ``DEPENDENCY``
        Source node depends on target node being reachable (soft constraint).
    """

    FABRIC_LINK = "fabric_link"
    ROUTE_HINT = "route_hint"
    DEPENDENCY = "dependency"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NetworkNode:
    """A node in the network graph.

    Attributes
    ----------
    node_id:
        Unique identifier for this node in the network graph.
    role:
        Network participation role.
    host:
        Node host address (``""`` = unknown / not applicable).
    port:
        Node port (0 = unknown / not applicable).
    transport_hints:
        Optional route hints (e.g. ``{"protocol": "http", "path": "/api"}``).
    tags:
        Free-form labels.
    metadata:
        Arbitrary metadata.
    registered_at:
        Monotonic timestamp of initial registration.
    last_updated_at:
        Monotonic timestamp of the most recent update.
    """

    node_id: str
    role: NetworkNodeRole = NetworkNodeRole.FABRIC_PARTICIPANT
    host: str = ""
    port: int = 0
    transport_hints: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.monotonic)
    last_updated_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "role": self.role.value if isinstance(self.role, NetworkNodeRole) else self.role,
            "host": self.host,
            "port": self.port,
            "transport_hints": dict(self.transport_hints),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "registered_at": self.registered_at,
            "last_updated_at": self.last_updated_at,
        }


@dataclass
class NetworkEdge:
    """A directed edge in the network graph.

    Attributes
    ----------
    edge_id:
        Unique edge identifier.
    source_node_id:
        Source node identifier.
    target_node_id:
        Target node identifier.
    kind:
        Edge kind.
    metadata:
        Arbitrary metadata.
    created_at:
        Monotonic timestamp of edge creation.
    """

    edge_id: str
    source_node_id: str
    target_node_id: str
    kind: NetworkEdgeKind = NetworkEdgeKind.FABRIC_LINK
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "kind": self.kind.value if isinstance(self.kind, NetworkEdgeKind) else self.kind,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
        }


@dataclass
class NetworkGraphRecord:
    """Observability record emitted when the network graph changes.

    Attributes
    ----------
    record_id:
        Unique record identifier.
    event_kind:
        One of ``"node_registered"``, ``"node_updated"``,
        ``"node_removed"``, ``"edge_registered"``.
    node_id:
        Affected node (or source node for edge events).
    role:
        Network role at the time of the event.
    timestamp:
        Wall-clock time.
    details:
        Arbitrary details.
    """

    record_id: str
    event_kind: str
    node_id: str
    role: str = NetworkNodeRole.UNKNOWN.value
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event_kind": self.event_kind,
            "node_id": self.node_id,
            "role": self.role,
            "timestamp": self.timestamp,
            "details": dict(self.details),
            "contract_version": NETWORK_GRAPH_CONTRACT_VERSION,
        }


@dataclass
class NetworkGraphSnapshot:
    """Point-in-time snapshot of the network graph.

    Attributes
    ----------
    total_nodes:
        Total number of registered nodes.
    total_edges:
        Total number of registered edges.
    nodes_by_role:
        Count of nodes grouped by :class:`NetworkNodeRole`.
    recent_records:
        Up to *max_records* most recent :class:`NetworkGraphRecord` items.
    authority:
        Module authority sentinel.
    """

    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_role: Dict[str, int] = field(default_factory=dict)
    recent_records: List[NetworkGraphRecord] = field(default_factory=list)
    authority: str = NETWORK_GRAPH_RUNTIME_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "nodes_by_role": dict(self.nodes_by_role),
            "recent_records": [r.to_dict() for r in self.recent_records],
        }


# ---------------------------------------------------------------------------
# NetworkGraphRuntime
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256
_record_counter: int = 0
_record_lock: threading.Lock = threading.Lock()


def _next_record_id() -> str:
    global _record_counter
    with _record_lock:
        _record_counter += 1
        return f"ngr_{_record_counter}"


class NetworkGraphRuntime:
    """Canonical Network Graph Runtime (process-level singleton).

    Responsibilities
    ----------------
    * Track every assimilated node as a :class:`NetworkNode` keyed by
      ``node_id``.
    * Record :class:`NetworkEdge` objects for fabric links and route hints.
    * Maintain a 256-entry observability ring buffer.
    * Expose a point-in-time :meth:`snapshot` for the operator console.

    Thread safety
    -------------
    All mutations are protected by a :class:`threading.Lock`.
    """

    _instance: Optional["NetworkGraphRuntime"] = None
    _cls_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "NetworkGraphRuntime":
        with cls._cls_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_state()
                cls._instance = instance
        return cls._instance

    def _init_state(self) -> None:
        self._nodes: Dict[str, NetworkNode] = {}
        self._edges: Dict[str, NetworkEdge] = {}
        self._log: Deque[NetworkGraphRecord] = deque(maxlen=_RING_BUFFER_SIZE)
        self._rw_lock: threading.Lock = threading.Lock()

    # ── Node management ───────────────────────────────────────────────────

    def register_node(self, node: NetworkNode) -> NetworkNode:
        """Register or update a :class:`NetworkNode`.

        If a node with the same ``node_id`` already exists it is updated
        in-place (the ``registered_at`` timestamp is preserved).

        Args:
            node: The :class:`NetworkNode` to register.

        Returns:
            The registered (or updated) :class:`NetworkNode`.

        Raises:
            ValueError: If ``node.node_id`` is empty.
        """
        if not node.node_id:
            raise ValueError("NetworkNode.node_id must be non-empty")

        with self._rw_lock:
            is_update = node.node_id in self._nodes
            if is_update:
                existing = self._nodes[node.node_id]
                node.registered_at = existing.registered_at
            node.last_updated_at = time.monotonic()
            self._nodes[node.node_id] = node

        event_kind = "node_updated" if is_update else "node_registered"
        self._emit_record(
            event_kind,
            node.node_id,
            role=node.role.value if isinstance(node.role, NetworkNodeRole) else str(node.role),
            details={"host": node.host, "port": node.port, "tags": node.tags},
        )
        logger.debug(
            "network_graph_runtime: %s %s (role=%s)",
            event_kind,
            node.node_id,
            node.role,
            extra={"event": event_kind, "node_id": node.node_id},
        )
        return node

    def remove_node(self, node_id: str) -> bool:
        """Remove a :class:`NetworkNode` from the graph.

        Also removes all edges incident to this node.

        Args:
            node_id: Node identifier.

        Returns:
            ``True`` if the node was found and removed; ``False`` otherwise.
        """
        with self._rw_lock:
            if node_id not in self._nodes:
                return False
            del self._nodes[node_id]
            # Remove incident edges
            to_remove = [
                eid
                for eid, e in self._edges.items()
                if e.source_node_id == node_id or e.target_node_id == node_id
            ]
            for eid in to_remove:
                del self._edges[eid]

        self._emit_record(
            "node_removed",
            node_id,
            details={"removed_edges": len(to_remove)},
        )
        return True

    def get_node(self, node_id: str) -> Optional[NetworkNode]:
        """Return the :class:`NetworkNode` for *node_id*, or ``None``."""
        with self._rw_lock:
            return self._nodes.get(node_id)

    def all_nodes(self) -> List[NetworkNode]:
        """Return all registered :class:`NetworkNode` objects."""
        with self._rw_lock:
            return list(self._nodes.values())

    def list_by_role(self, role: NetworkNodeRole) -> List[NetworkNode]:
        """Return all nodes with the given :class:`NetworkNodeRole`."""
        with self._rw_lock:
            return [n for n in self._nodes.values() if n.role == role]

    # ── Edge management ───────────────────────────────────────────────────

    def register_edge(self, edge: NetworkEdge) -> NetworkEdge:
        """Register a :class:`NetworkEdge`.

        Edges with the same ``edge_id`` are overwritten.

        Args:
            edge: The :class:`NetworkEdge` to register.

        Returns:
            The registered :class:`NetworkEdge`.

        Raises:
            ValueError: If ``edge.edge_id`` is empty.
        """
        if not edge.edge_id:
            raise ValueError("NetworkEdge.edge_id must be non-empty")

        with self._rw_lock:
            self._edges[edge.edge_id] = edge

        self._emit_record(
            "edge_registered",
            edge.source_node_id,
            details={
                "edge_id": edge.edge_id,
                "target_node_id": edge.target_node_id,
                "kind": edge.kind.value if isinstance(edge.kind, NetworkEdgeKind) else edge.kind,
            },
        )
        return edge

    def all_edges(self) -> List[NetworkEdge]:
        """Return all registered :class:`NetworkEdge` objects."""
        with self._rw_lock:
            return list(self._edges.values())

    def edges_from(self, node_id: str) -> List[NetworkEdge]:
        """Return edges originating from *node_id*."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.source_node_id == node_id]

    def edges_to(self, node_id: str) -> List[NetworkEdge]:
        """Return edges pointing to *node_id*."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.target_node_id == node_id]

    # ── Observability ─────────────────────────────────────────────────────

    def get_topology_log(self) -> Deque[NetworkGraphRecord]:
        """Return the 256-entry topology-change ring buffer."""
        return self._log

    def snapshot(self, *, max_records: int = 20) -> NetworkGraphSnapshot:
        """Return a point-in-time :class:`NetworkGraphSnapshot`.

        Args:
            max_records: Maximum number of recent records to include.

        Returns:
            A :class:`NetworkGraphSnapshot`.
        """
        with self._rw_lock:
            nodes = list(self._nodes.values())
            edges = list(self._edges.values())

        by_role: Dict[str, int] = {}
        for n in nodes:
            role_val = (
                n.role.value if isinstance(n.role, NetworkNodeRole) else str(n.role)
            )
            by_role[role_val] = by_role.get(role_val, 0) + 1

        recent = list(self._log)[-max_records:] if self._log else []

        return NetworkGraphSnapshot(
            total_nodes=len(nodes),
            total_edges=len(edges),
            nodes_by_role=by_role,
            recent_records=recent,
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _emit_record(
        self,
        event_kind: str,
        node_id: str,
        *,
        role: str = NetworkNodeRole.UNKNOWN.value,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = NetworkGraphRecord(
            record_id=_next_record_id(),
            event_kind=event_kind,
            node_id=node_id,
            role=role,
            details=dict(details or {}),
        )
        self._log.append(record)


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------


def get_network_graph_runtime() -> NetworkGraphRuntime:
    """Return the global :class:`NetworkGraphRuntime` singleton."""
    return NetworkGraphRuntime()


def reset_network_graph_runtime() -> None:
    """Reset the :class:`NetworkGraphRuntime` singleton (for testing)."""
    NetworkGraphRuntime._instance = None
