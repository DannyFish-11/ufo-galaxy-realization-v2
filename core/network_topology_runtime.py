#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/network_topology_runtime.py
==================================
PR-8: Network Topology Runtime — Canonical Unified Network Topology.

Unifies the previously scattered transport hierarchy, relay/mesh/direct paths,
NATS fabric, gateway substrate, and topology semantic views into a single
**canonical network topology runtime**.  This module does **not** replace the
existing topology components; it absorbs them via adapter/assimilation
projections and becomes the authoritative source for:

  * Topology node identity and kind (device, gateway, relay, mesh participant,
    NATS fabric endpoint, runtime/provider node)
  * Topology edge identity and kind (direct, gateway, relay, mesh, fabric,
    projected semantic)
  * Per-node and per-edge **connection state** (reachable, connected, degraded,
    preferred, fallback, latent, unavailable)
  * Transport preference, route availability, effective path, fallback path

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  NETWORK TOPOLOGY RUNTIME  (this module, Layer 8)                  │
    │                                                                     │
    │  Absorbs:                                                           │
    │    • transport_hierarchy  (direct_ws / relay / mesh roles)          │
    │    • agent_bus_fabric     (strategy selection, NATS / gateway)      │
    │    • nats_bus             (NATS fabric carrier connectivity)        │
    │    • gateway_nats_adapter (gateway substrate connectivity)          │
    │    • device connectivity  (RoutabilitySummary / preferred_path)     │
    │    • status board topology semantic layer (projected)               │
    │    • fusion topology graph structures (structural capability)       │
    │                                                                     │
    │  Exposes:                                                           │
    │    • canonical topology view → scheduler, observer, renderer        │
    │    • snapshot() → operator console / status board                  │
    │    • 256-entry observability ring buffer                            │
    └─────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **NetworkTopologyRuntime is the sole canonical topology authority.**
    Renderer, layout, and status-board surfaces MUST consume topology from
    this runtime, not from scattered partial state sources.
    Governed by ``TOPOLOGY_CONSUMER_POLICY``.

2.  **Transport hierarchy roles are absorbed, not replaced.**
    ``TRANSPORT_ROLE_DIRECT_WS``, ``TRANSPORT_ROLE_RELAY``, and
    ``TRANSPORT_ROLE_MESH`` from ``core.transport_hierarchy`` map directly to
    edge and node kinds in this runtime.

3.  **Fabric/gateway state is absorbed as dynamic input.**
    NATS fabric connectivity and gateway substrate state are absorbed via
    ``assimilate_nats_state()`` and ``assimilate_gateway_state()``.
    These calls update the respective topology nodes in place.

4.  **All topology mutations are observable.**
    Every node registration, state change, and edge change is recorded in a
    256-entry ring buffer.

Public API
----------
Authority sentinels:
    NETWORK_TOPOLOGY_RUNTIME_AUTHORITY
    NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION
    NETWORK_TOPOLOGY_CONTRACT_VERSION
    TOPOLOGY_CONSUMER_POLICY
    TRANSPORT_HIERARCHY_ASSIMILATION_POLICY

Enumerations:
    TopologyNodeKind
    TopologyEdgeKind
    TopologyConnectionState

Dataclasses:
    TopologyNode
    TopologyEdge
    TopologyRecord
    TopologySnapshot
    TransportPathInfo

Class:
    NetworkTopologyRuntime

Absorption helpers:
    assimilate_transport_hierarchy_record(record) -> TopologyEdge
    assimilate_nats_state(is_connected, host, port) -> TopologyNode
    assimilate_gateway_state(gateway_id, host, port, is_connected) -> TopologyNode
    assimilate_device_connectivity(device_id, preferred_path, effective_routable,
                                   fallback_available, mesh_overlay_available)
                                   -> TopologyNode
    project_transport_path(source_id, target_id, strategy_record)
        -> TransportPathInfo

Module-level singleton helpers:
    get_network_topology_runtime() -> NetworkTopologyRuntime
    reset_network_topology_runtime() -> None  # for testing
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

from core.runtime_truth_governance import (
    RECOVERY_STATUS_DEGRADED,
    RECOVERY_STATUS_LIVE,
    RECOVERY_STATUS_REVALIDATED,
    TRUTH_GRADE_DURABLE,
    TRUTH_GRADE_PROJECTION,
    TRUTH_GRADE_RECOVERABLE,
    TRUTH_GRADE_REVALIDATED,
    TRUTH_GRADE_RUNTIME_ONLY,
    build_truth_governance,
    load_json_payload,
    write_json_atomically,
)

logger = logging.getLogger("Galaxy.NetworkTopologyRuntime")

__all__ = [
    # Authority sentinels
    "NETWORK_TOPOLOGY_RUNTIME_AUTHORITY",
    "NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION",
    "NETWORK_TOPOLOGY_CONTRACT_VERSION",
    "TOPOLOGY_CONSUMER_POLICY",
    "TRANSPORT_HIERARCHY_ASSIMILATION_POLICY",
    # Enumerations
    "TopologyNodeKind",
    "TopologyEdgeKind",
    "TopologyConnectionState",
    # Dataclasses
    "TopologyNode",
    "TopologyEdge",
    "TopologyRecord",
    "TopologySnapshot",
    "TransportPathInfo",
    "GroundedTopologyRelation",
    "GroundedRuntimeTopology",
    # Class
    "NetworkTopologyRuntime",
    # Absorption helpers
    "assimilate_transport_hierarchy_record",
    "assimilate_nats_state",
    "assimilate_gateway_state",
    "assimilate_device_connectivity",
    "project_transport_path",
    "build_grounded_runtime_topology",
    # Singleton helpers
    "get_network_topology_runtime",
    "reset_network_topology_runtime",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Module authority marker.  Import this sentinel to declare that the caller
#: consumes the canonical network topology runtime (PR-8).
NETWORK_TOPOLOGY_RUNTIME_AUTHORITY: str = (
    "core.network_topology_runtime"
    " — canonical unified network topology runtime (PR-8)"
)

#: Layer position in the canonical control-plane stack.
#: Layer 8 sits above the capability assimilation layer (Layer 7).
NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION: int = 8

#: Contract version for serialised topology objects.
NETWORK_TOPOLOGY_CONTRACT_VERSION: str = "v1"
_NETWORK_TOPOLOGY_STATE_PATH_ENV: str = "GALAXY_NETWORK_TOPOLOGY_RUNTIME_STATE_PATH"
_DEFAULT_NETWORK_TOPOLOGY_STATE_PATH: str = os.getenv(
    _NETWORK_TOPOLOGY_STATE_PATH_ENV,
    "data/runtime/network_topology_runtime_state.json",
)

#: Policy sentinel: renderer, layout, and status-board surfaces MUST consume
#: topology from NetworkTopologyRuntime, not from partial topology sources.
TOPOLOGY_CONSUMER_POLICY: str = (
    "TOPOLOGY_CONSUMER::MUST_READ_FROM_NETWORK_TOPOLOGY_RUNTIME"
    " — direct partial-source reads are prohibited in consumers"
)

#: Policy sentinel: transport hierarchy roles (direct_ws / relay / mesh) are
#: absorbed into this runtime rather than replaced or duplicated.
TRANSPORT_HIERARCHY_ASSIMILATION_POLICY: str = (
    "TRANSPORT_HIERARCHY::ABSORBED_INTO_TOPOLOGY_RUNTIME"
    " — no parallel transport hierarchy mapping outside this module"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TopologyNodeKind(str, Enum):
    """Canonical kind of a node in the network topology runtime.

    ``DEVICE``
        A physical or virtual end-user device (phone, tablet, desktop).
    ``GATEWAY``
        A Galaxy Gateway WebSocket transport node.
    ``RELAY``
        A ProxyRelay / server-mediated forwarding node.
    ``MESH_PARTICIPANT``
        A node participating in mesh overlay / peer-exchange topology.
    ``NATS_FABRIC_ENDPOINT``
        A NATS JetStream cluster endpoint (fabric carrier layer).
    ``RUNTIME_PROVIDER_NODE``
        A runtime or capability-provider node (LLM inference, service, etc.).
    ``UNKNOWN``
        Kind not yet determined.
    """

    DEVICE = "device"
    GATEWAY = "gateway"
    RELAY = "relay"
    MESH_PARTICIPANT = "mesh_participant"
    NATS_FABRIC_ENDPOINT = "nats_fabric_endpoint"
    RUNTIME_PROVIDER_NODE = "runtime_provider_node"
    UNKNOWN = "unknown"


class TopologyEdgeKind(str, Enum):
    """Canonical kind of a directed edge in the network topology.

    ``DIRECT``
        Direct WebSocket transport path (primary, highest preference).
    ``GATEWAY``
        Galaxy Gateway substrate transport path.
    ``RELAY``
        ProxyRelay / server-mediated fallback path.
    ``MESH``
        Mesh overlay / peer-exchange path (overlay only, not primary).
    ``FABRIC``
        NATS fabric / JetStream carrier link.
    ``PROJECTED_SEMANTIC``
        A semantically projected edge (e.g. status board topology layer,
        fusion topology structural capability edge).
    """

    DIRECT = "direct"
    GATEWAY = "gateway"
    RELAY = "relay"
    MESH = "mesh"
    FABRIC = "fabric"
    PROJECTED_SEMANTIC = "projected_semantic"


class TopologyConnectionState(str, Enum):
    """Connection state of a topology node or edge.

    ``REACHABLE``
        Node/edge is reachable but not actively connected.
    ``CONNECTED``
        Node/edge has an active established connection.
    ``DEGRADED``
        Node/edge is connected but in a degraded state.
    ``PREFERRED``
        Node/edge is the preferred path for dispatch.
    ``FALLBACK``
        Node/edge is a fallback path (active only when preferred is unavailable).
    ``LATENT``
        Node/edge is known but currently inactive / standby.
    ``UNAVAILABLE``
        Node/edge is not reachable.
    """

    REACHABLE = "reachable"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    PREFERRED = "preferred"
    FALLBACK = "fallback"
    LATENT = "latent"
    UNAVAILABLE = "unavailable"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TopologyNode:
    """A node in the canonical network topology runtime.

    Attributes
    ----------
    node_id:
        Unique identifier for this node.
    kind:
        Canonical node kind.
    state:
        Current connection/reachability state.
    host:
        Node host address (``""`` = unknown / not applicable).
    port:
        Node port (0 = unknown / not applicable).
    transport_hints:
        Optional transport-layer route hints.
    tags:
        Free-form classification labels.
    metadata:
        Arbitrary metadata.
    registered_at:
        Monotonic timestamp of initial registration.
    last_updated_at:
        Monotonic timestamp of the most recent update.
    """

    node_id: str
    kind: TopologyNodeKind = TopologyNodeKind.UNKNOWN
    state: TopologyConnectionState = TopologyConnectionState.LATENT
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
            "kind": self.kind.value if isinstance(self.kind, TopologyNodeKind) else self.kind,
            "state": (
                self.state.value
                if isinstance(self.state, TopologyConnectionState)
                else self.state
            ),
            "host": self.host,
            "port": self.port,
            "transport_hints": dict(self.transport_hints),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "registered_at": self.registered_at,
            "last_updated_at": self.last_updated_at,
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class TopologyEdge:
    """A directed edge in the canonical network topology.

    Attributes
    ----------
    edge_id:
        Unique edge identifier.
    source_node_id:
        Source node identifier.
    target_node_id:
        Target node identifier.
    kind:
        Edge kind (transport path type).
    state:
        Connection state of this edge.
    preferred:
        Whether this edge is the preferred path for dispatch.
    latency_hint_ms:
        Optional latency hint in milliseconds (0 = unknown).
    metadata:
        Arbitrary metadata.
    created_at:
        Monotonic timestamp of edge creation.
    last_updated_at:
        Monotonic timestamp of the most recent update.
    """

    edge_id: str
    source_node_id: str
    target_node_id: str
    kind: TopologyEdgeKind = TopologyEdgeKind.DIRECT
    state: TopologyConnectionState = TopologyConnectionState.LATENT
    preferred: bool = False
    latency_hint_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    last_updated_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "kind": self.kind.value if isinstance(self.kind, TopologyEdgeKind) else self.kind,
            "state": (
                self.state.value
                if isinstance(self.state, TopologyConnectionState)
                else self.state
            ),
            "preferred": self.preferred,
            "latency_hint_ms": self.latency_hint_ms,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class TopologyRecord:
    """Observability record emitted when the topology changes.

    Attributes
    ----------
    record_id:
        Unique record identifier.
    event_kind:
        One of ``"node_registered"``, ``"node_updated"``, ``"node_removed"``,
        ``"node_state_changed"``, ``"edge_registered"``, ``"edge_updated"``,
        ``"edge_removed"``, ``"nats_assimilated"``, ``"gateway_assimilated"``,
        ``"device_assimilated"``.
    node_id:
        Affected node (or source node for edge events).
    kind:
        Node or edge kind at the time of the event.
    state:
        Connection state at the time of the event.
    timestamp:
        Wall-clock time.
    details:
        Arbitrary details.
    """

    record_id: str
    event_kind: str
    node_id: str
    kind: str = TopologyNodeKind.UNKNOWN.value
    state: str = TopologyConnectionState.LATENT.value
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "event_kind": self.event_kind,
            "node_id": self.node_id,
            "kind": self.kind,
            "state": self.state,
            "timestamp": self.timestamp,
            "details": dict(self.details),
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class TransportPathInfo:
    """Canonical transport path information for a source→target pair.

    Attributes
    ----------
    source_id:
        Source node identifier.
    target_id:
        Target node identifier.
    effective_path:
        The currently active/preferred edge kind.
    fallback_path:
        The fallback edge kind (``None`` if no fallback is available).
    available_paths:
        All edge kinds that are currently in REACHABLE, CONNECTED, PREFERRED,
        or FALLBACK state.
    transport_strategy:
        The transport strategy string from ``agent_bus_fabric``
        (``"direct"``, ``"gateway"``, ``"nats"``, ``"relay"``, ``"mesh"``).
    preferred_edge_id:
        Edge identifier of the preferred path (``""`` if none).
    """

    source_id: str
    target_id: str
    effective_path: str = ""
    fallback_path: Optional[str] = None
    available_paths: List[str] = field(default_factory=list)
    transport_strategy: str = ""
    preferred_edge_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "effective_path": self.effective_path,
            "fallback_path": self.fallback_path,
            "available_paths": list(self.available_paths),
            "transport_strategy": self.transport_strategy,
            "preferred_edge_id": self.preferred_edge_id,
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class TopologySnapshot:
    """Point-in-time snapshot of the network topology runtime.

    Attributes
    ----------
    total_nodes:
        Total number of registered topology nodes.
    total_edges:
        Total number of registered topology edges.
    nodes_by_kind:
        Count of nodes grouped by :class:`TopologyNodeKind`.
    nodes_by_state:
        Count of nodes grouped by :class:`TopologyConnectionState`.
    edges_by_kind:
        Count of edges grouped by :class:`TopologyEdgeKind`.
    preferred_edges:
        List of edge IDs that are marked as preferred.
    recent_records:
        Up to *max_records* most recent :class:`TopologyRecord` items.
    authority:
        Module authority sentinel.
    """

    total_nodes: int = 0
    total_edges: int = 0
    nodes_by_kind: Dict[str, int] = field(default_factory=dict)
    nodes_by_state: Dict[str, int] = field(default_factory=dict)
    edges_by_kind: Dict[str, int] = field(default_factory=dict)
    preferred_edges: List[str] = field(default_factory=list)
    recent_records: List[TopologyRecord] = field(default_factory=list)
    authority: str = NETWORK_TOPOLOGY_RUNTIME_AUTHORITY
    truth_governance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "nodes_by_kind": dict(self.nodes_by_kind),
            "nodes_by_state": dict(self.nodes_by_state),
            "edges_by_kind": dict(self.edges_by_kind),
            "preferred_edges": list(self.preferred_edges),
            "recent_records": [r.to_dict() for r in self.recent_records],
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
            "truth_governance": dict(self.truth_governance),
        }


@dataclass
class GroundedTopologyRelation:
    """Runtime-grounded relation in the unified topology graph."""

    relation_kind: str
    source_id: str
    target_id: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    truth_grade: str = TRUTH_GRADE_PROJECTION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_kind": self.relation_kind,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "evidence": dict(self.evidence),
            "truth_grade": self.truth_grade,
        }


@dataclass
class GroundedRuntimeTopology:
    """Grounded runtime topology built from live runtime/state objects."""

    runtime_host: str = "v2_control_plane"
    generated_at: float = field(default_factory=time.time)
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[GroundedTopologyRelation] = field(default_factory=list)
    galaxy_tree: Dict[str, Any] = field(default_factory=dict)
    authority: str = (
        "RUNTIME_TOPOLOGY_GROUNDED_V1::core.network_topology_runtime.build_grounded_runtime_topology"
    )
    truth_governance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_host": self.runtime_host,
            "generated_at": self.generated_at,
            "nodes": list(self.nodes),
            "relations": [r.to_dict() for r in self.relations],
            "galaxy_tree": dict(self.galaxy_tree),
            "authority": self.authority,
            "truth_governance": dict(self.truth_governance),
        }


# ---------------------------------------------------------------------------
# NetworkTopologyRuntime
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256
_record_counter: int = 0
_record_lock: threading.Lock = threading.Lock()

# Mapping: transport strategy string → TopologyEdgeKind
_STRATEGY_TO_EDGE_KIND: Dict[str, TopologyEdgeKind] = {
    "direct": TopologyEdgeKind.DIRECT,
    "gateway": TopologyEdgeKind.GATEWAY,
    "nats": TopologyEdgeKind.FABRIC,
    "relay": TopologyEdgeKind.RELAY,
    "mesh": TopologyEdgeKind.MESH,
}

# Mapping: transport_hierarchy preferred_path → TopologyEdgeKind
_PATH_TO_EDGE_KIND: Dict[str, TopologyEdgeKind] = {
    "direct_ws": TopologyEdgeKind.DIRECT,
    "ucm": TopologyEdgeKind.DIRECT,
    "gateway": TopologyEdgeKind.GATEWAY,
    "relay": TopologyEdgeKind.RELAY,
    "mesh": TopologyEdgeKind.MESH,
    "nats": TopologyEdgeKind.FABRIC,
}


def _next_record_id() -> str:
    global _record_counter
    with _record_lock:
        _record_counter += 1
        return f"ntr_{_record_counter}"


class NetworkTopologyRuntime:
    """Canonical Network Topology Runtime (process-level singleton).

    Responsibilities
    ----------------
    * Maintain the canonical set of :class:`TopologyNode` objects (device,
      gateway, relay, mesh participant, NATS fabric endpoint, runtime provider).
    * Maintain :class:`TopologyEdge` objects representing transport paths
      between nodes (direct, gateway, relay, mesh, fabric, projected semantic).
    * Track per-node and per-edge :class:`TopologyConnectionState`.
    * Absorb transport hierarchy, NATS fabric, gateway substrate, and device
      connectivity state via dedicated ``assimilate_*`` methods.
    * Expose a canonical :meth:`snapshot` for renderer, layout, status board,
      and operator console consumers.
    * Maintain a 256-entry observability ring buffer.

    Thread safety
    -------------
    All mutations are protected by a :class:`threading.Lock`.
    """

    _instance: Optional["NetworkTopologyRuntime"] = None
    _cls_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "NetworkTopologyRuntime":
        with cls._cls_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_state()
                cls._instance = instance
        return cls._instance

    def _init_state(self) -> None:
        self._nodes: Dict[str, TopologyNode] = {}
        self._edges: Dict[str, TopologyEdge] = {}
        self._log: Deque[TopologyRecord] = deque(maxlen=_RING_BUFFER_SIZE)
        self._rw_lock: threading.Lock = threading.Lock()
        self._state_path = _DEFAULT_NETWORK_TOPOLOGY_STATE_PATH
        self._last_recovered_at: Optional[float] = None
        self._recovered_node_ids: set[str] = set()
        self._recovered_edge_ids: set[str] = set()

    # PR-AIPV3-TOPO: AIP v3 state event emission for topology changes

    def _emit_aip_v3_state_event(self, event_category: str, event_action: str, node_id: str, details: Dict[str, Any]) -> None:
        """Emit STATE_EVENT AIP v3 message for topology changes.

        Best-effort: published via NATS if connected, otherwise logged only.
        This makes topology state changes observable by any AIP v3 consumer.
        """
        try:
            import asyncio
            from core.schemas.aip_v3 import StateEventMsg  # noqa: PLC0415
            from core.nats_bus import get_nats_bus  # noqa: PLC0415

            msg = StateEventMsg(
                device_id=node_id,
                event_category=event_category,
                event_action=event_action,
                payload=details,
            )
            nats = get_nats_bus()
            if nats.is_connected():
                asyncio.get_event_loop().create_task(nats.publish_state_event(msg))
            else:
                logger.debug("AIPV3-TOPO STATE_EVENT: %s", msg.model_dump_json(exclude_none=True))
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ── Node management ───────────────────────────────────────────────────

    def register_node(self, node: TopologyNode) -> TopologyNode:
        """Register or update a :class:`TopologyNode`.

        If a node with the same ``node_id`` already exists it is updated
        in-place (the ``registered_at`` timestamp is preserved).

        Args:
            node: The :class:`TopologyNode` to register.

        Returns:
            The registered (or updated) :class:`TopologyNode`.

        Raises:
            ValueError: If ``node.node_id`` is empty.
        """
        if not node.node_id:
            raise ValueError("TopologyNode.node_id must be non-empty")

        with self._rw_lock:
            is_update = node.node_id in self._nodes
            if is_update:
                existing = self._nodes[node.node_id]
                node.registered_at = existing.registered_at
            node.last_updated_at = time.monotonic()
            node.metadata = dict(node.metadata)
            node.tags = [tag for tag in node.tags if tag != "recovered_unrevalidated"]
            node.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(
                    RECOVERY_STATUS_REVALIDATED if node.node_id in self._recovered_node_ids else RECOVERY_STATUS_LIVE
                ),
                field_truth_grades={
                    "topology_membership": TRUTH_GRADE_PROJECTION,
                    "connection_state": TRUTH_GRADE_RUNTIME_ONLY,
                },
                notes=[
                    "Topology state is a canonical runtime view, not durable lifecycle authority.",
                ],
            )
            self._nodes[node.node_id] = node
            self._recovered_node_ids.discard(node.node_id)

        event_kind = "node_updated" if is_update else "node_registered"
        self._emit_record(
            event_kind,
            node.node_id,
            kind=node.kind.value if isinstance(node.kind, TopologyNodeKind) else str(node.kind),
            state=(
                node.state.value
                if isinstance(node.state, TopologyConnectionState)
                else str(node.state)
            ),
            details={"host": node.host, "port": node.port, "tags": node.tags},
        )
        logger.debug(
            "network_topology_runtime: %s %s (kind=%s state=%s)",
            event_kind,
            node.node_id,
            node.kind,
            node.state,
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="node_registered",
            node_id=node.node_id,
            details={"kind": node.kind.value if isinstance(node.kind, TopologyNodeKind) else str(node.kind),
                     "state": node.state.value if isinstance(node.state, TopologyConnectionState) else str(node.state),
                     "host": node.host, "port": node.port},
        )
        self.persist_durable_state()
        return node

    def update_node_state(
        self, node_id: str, state: TopologyConnectionState
    ) -> Optional[TopologyNode]:
        """Update the :class:`TopologyConnectionState` of a registered node.

        Args:
            node_id: Node identifier.
            state:   New connection state.

        Returns:
            The updated :class:`TopologyNode`, or ``None`` if not found.
        """
        with self._rw_lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            node.state = state
            node.last_updated_at = time.monotonic()
            node.metadata = dict(node.metadata)
            node.tags = [tag for tag in node.tags if tag != "recovered_unrevalidated"]
            node.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=RECOVERY_STATUS_REVALIDATED,
                field_truth_grades={
                    "topology_membership": TRUTH_GRADE_PROJECTION,
                    "connection_state": TRUTH_GRADE_REVALIDATED,
                },
            )
            self._recovered_node_ids.discard(node_id)

        self._emit_record(
            "node_state_changed",
            node_id,
            kind=node.kind.value if isinstance(node.kind, TopologyNodeKind) else str(node.kind),
            state=state.value if isinstance(state, TopologyConnectionState) else str(state),
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="node_state_changed",
            node_id=node_id,
            details={"new_state": state.value if isinstance(state, TopologyConnectionState) else str(state)},
        )
        self.persist_durable_state()
        return node

    def remove_node(self, node_id: str) -> bool:
        """Remove a :class:`TopologyNode` from the topology.

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
            to_remove = [
                eid
                for eid, e in self._edges.items()
                if e.source_node_id == node_id or e.target_node_id == node_id
            ]
            for eid in to_remove:
                del self._edges[eid]
                self._recovered_edge_ids.discard(eid)
            self._recovered_node_ids.discard(node_id)

        self._emit_record(
            "node_removed",
            node_id,
            details={"removed_edges": len(to_remove)},
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="node_removed",
            node_id=node_id,
            details={"removed_edges": len(to_remove) if 'to_remove' in locals() else 0},
        )
        self.persist_durable_state()
        return True

    def get_node(self, node_id: str) -> Optional[TopologyNode]:
        """Return the :class:`TopologyNode` for *node_id*, or ``None``."""
        with self._rw_lock:
            return self._nodes.get(node_id)

    def all_nodes(self) -> List[TopologyNode]:
        """Return all registered :class:`TopologyNode` objects."""
        with self._rw_lock:
            return list(self._nodes.values())

    def nodes_by_kind(self, kind: TopologyNodeKind) -> List[TopologyNode]:
        """Return all nodes with the given :class:`TopologyNodeKind`."""
        with self._rw_lock:
            return [n for n in self._nodes.values() if n.kind == kind]

    def nodes_by_state(self, state: TopologyConnectionState) -> List[TopologyNode]:
        """Return all nodes with the given :class:`TopologyConnectionState`."""
        with self._rw_lock:
            return [n for n in self._nodes.values() if n.state == state]

    # ── Edge management ───────────────────────────────────────────────────

    def register_edge(self, edge: TopologyEdge) -> TopologyEdge:
        """Register or update a :class:`TopologyEdge`.

        Edges with the same ``edge_id`` are overwritten.

        Args:
            edge: The :class:`TopologyEdge` to register.

        Returns:
            The registered :class:`TopologyEdge`.

        Raises:
            ValueError: If ``edge.edge_id`` is empty.
        """
        if not edge.edge_id:
            raise ValueError("TopologyEdge.edge_id must be non-empty")

        with self._rw_lock:
            self._edges[edge.edge_id] = edge
            edge.last_updated_at = time.monotonic()
            edge.metadata = dict(edge.metadata)
            edge.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(
                    RECOVERY_STATUS_REVALIDATED if edge.edge_id in self._recovered_edge_ids else RECOVERY_STATUS_LIVE
                ),
                field_truth_grades={
                    "topology_membership": TRUTH_GRADE_PROJECTION,
                    "connection_state": TRUTH_GRADE_RUNTIME_ONLY,
                },
            )
            self._recovered_edge_ids.discard(edge.edge_id)

        self._emit_record(
            "edge_registered",
            edge.source_node_id,
            kind=edge.kind.value if isinstance(edge.kind, TopologyEdgeKind) else str(edge.kind),
            state=(
                edge.state.value
                if isinstance(edge.state, TopologyConnectionState)
                else str(edge.state)
            ),
            details={
                "edge_id": edge.edge_id,
                "target_node_id": edge.target_node_id,
                "preferred": edge.preferred,
            },
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="edge_registered",
            node_id=edge.source_node_id,
            details={"edge_id": edge.edge_id, "target": edge.target_node_id,
                     "kind": edge.kind.value if isinstance(edge.kind, TopologyEdgeKind) else str(edge.kind)},
        )
        self.persist_durable_state()
        return edge

    def update_edge_state(
        self, edge_id: str, state: TopologyConnectionState, *, preferred: Optional[bool] = None
    ) -> Optional[TopologyEdge]:
        """Update the state of a registered edge.

        Args:
            edge_id:   Edge identifier.
            state:     New connection state.
            preferred: If provided, update the ``preferred`` flag as well.

        Returns:
            The updated :class:`TopologyEdge`, or ``None`` if not found.
        """
        with self._rw_lock:
            edge = self._edges.get(edge_id)
            if edge is None:
                return None
            edge.state = state
            if preferred is not None:
                edge.preferred = preferred
            edge.last_updated_at = time.monotonic()
            edge.metadata = dict(edge.metadata)
            edge.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=RECOVERY_STATUS_REVALIDATED,
                field_truth_grades={
                    "topology_membership": TRUTH_GRADE_PROJECTION,
                    "connection_state": TRUTH_GRADE_REVALIDATED,
                },
            )
            self._recovered_edge_ids.discard(edge_id)

        self._emit_record(
            "edge_updated",
            edge.source_node_id,
            kind=edge.kind.value if isinstance(edge.kind, TopologyEdgeKind) else str(edge.kind),
            state=state.value if isinstance(state, TopologyConnectionState) else str(state),
            details={"edge_id": edge_id},
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="edge_state_changed",
            node_id=edge_id,
            details={"new_state": state.value if isinstance(state, TopologyConnectionState) else str(state)},
        )
        self.persist_durable_state()
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        """Remove a :class:`TopologyEdge`.

        Args:
            edge_id: Edge identifier.

        Returns:
            ``True`` if found and removed; ``False`` otherwise.
        """
        with self._rw_lock:
            if edge_id not in self._edges:
                return False
            edge = self._edges.pop(edge_id)
            self._recovered_edge_ids.discard(edge_id)

        self._emit_record(
            "edge_removed",
            edge.source_node_id,
            details={"edge_id": edge_id},
        )
        self._emit_aip_v3_state_event(
            event_category="topology",
            event_action="edge_removed",
            node_id=edge_id,
            details={},
        )
        self.persist_durable_state()
        return True

    def all_edges(self) -> List[TopologyEdge]:
        """Return all registered :class:`TopologyEdge` objects."""
        with self._rw_lock:
            return list(self._edges.values())

    def edges_from(self, node_id: str) -> List[TopologyEdge]:
        """Return edges originating from *node_id*."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.source_node_id == node_id]

    def edges_to(self, node_id: str) -> List[TopologyEdge]:
        """Return edges pointing to *node_id*."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.target_node_id == node_id]

    def preferred_edges(self) -> List[TopologyEdge]:
        """Return all edges marked as preferred."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.preferred]

    # ── Absorption APIs ───────────────────────────────────────────────────

    def absorb_nats_state(
        self,
        *,
        is_connected: bool,
        host: str = "",
        port: int = 0,
        node_id: str = "nats_fabric",
    ) -> TopologyNode:
        """Absorb NATS fabric carrier connectivity state.

        Creates or updates a ``NATS_FABRIC_ENDPOINT`` topology node reflecting
        the current NATS connection state.

        Args:
            is_connected: Whether the NATS fabric is currently connected.
            host:         NATS server host.
            port:         NATS server port.
            node_id:      Override node identifier (default ``"nats_fabric"``).

        Returns:
            The created/updated :class:`TopologyNode`.
        """
        state = (
            TopologyConnectionState.CONNECTED
            if is_connected
            else TopologyConnectionState.UNAVAILABLE
        )
        node = TopologyNode(
            node_id=node_id,
            kind=TopologyNodeKind.NATS_FABRIC_ENDPOINT,
            state=state,
            host=host,
            port=port,
            tags=["nats", "fabric"],
        )
        self.register_node(node)
        self._emit_record(
            "nats_assimilated",
            node_id,
            kind=TopologyNodeKind.NATS_FABRIC_ENDPOINT.value,
            state=state.value,
            details={"is_connected": is_connected, "host": host, "port": port},
        )
        logger.debug(
            "network_topology_runtime: nats_assimilated node=%s connected=%s",
            node_id,
            is_connected,
        )
        return node

    def absorb_gateway_state(
        self,
        *,
        gateway_id: str,
        host: str = "",
        port: int = 0,
        is_connected: bool = False,
    ) -> TopologyNode:
        """Absorb Galaxy Gateway substrate connectivity state.

        Creates or updates a ``GATEWAY`` topology node reflecting the current
        gateway connection state.

        Args:
            gateway_id:   Unique gateway identifier.
            host:         Gateway host address.
            port:         Gateway port.
            is_connected: Whether the gateway is currently connected.

        Returns:
            The created/updated :class:`TopologyNode`.
        """
        state = (
            TopologyConnectionState.CONNECTED
            if is_connected
            else TopologyConnectionState.UNAVAILABLE
        )
        node = TopologyNode(
            node_id=gateway_id,
            kind=TopologyNodeKind.GATEWAY,
            state=state,
            host=host,
            port=port,
            tags=["gateway", "substrate"],
        )
        self.register_node(node)
        self._emit_record(
            "gateway_assimilated",
            gateway_id,
            kind=TopologyNodeKind.GATEWAY.value,
            state=state.value,
            details={"is_connected": is_connected, "host": host, "port": port},
        )
        logger.debug(
            "network_topology_runtime: gateway_assimilated node=%s connected=%s",
            gateway_id,
            is_connected,
        )
        return node

    def absorb_device_connectivity(
        self,
        *,
        device_id: str,
        preferred_path: str = "",
        effective_routable: bool = False,
        fallback_available: bool = False,
        mesh_overlay_available: bool = False,
        host: str = "",
        port: int = 0,
    ) -> TopologyNode:
        """Absorb device connectivity state from RoutabilitySummary.

        Creates or updates a ``DEVICE`` topology node and corresponding edges
        reflecting the device's current connectivity status.

        The transport hierarchy mapping is:
          ``direct_ws`` / ``ucm``  →  DIRECT edge + PREFERRED state
          ``relay``                →  RELAY edge + FALLBACK state
          ``mesh``                 →  MESH edge + LATENT state (overlay only)
          no path                  →  UNAVAILABLE state

        Args:
            device_id:             Device identifier.
            preferred_path:        Preferred transport path string (from
                                   ``RoutabilitySummary.preferred_path``).
            effective_routable:    Whether the device is currently routable.
            fallback_available:    Whether a relay fallback is available.
            mesh_overlay_available: Whether mesh overlay is available.
            host:                  Device host address.
            port:                  Device port.

        Returns:
            The created/updated :class:`TopologyNode`.
        """
        if effective_routable:
            state = TopologyConnectionState.CONNECTED
        elif fallback_available:
            state = TopologyConnectionState.FALLBACK
        elif mesh_overlay_available:
            state = TopologyConnectionState.LATENT
        else:
            state = TopologyConnectionState.UNAVAILABLE

        node = TopologyNode(
            node_id=device_id,
            kind=TopologyNodeKind.DEVICE,
            state=state,
            host=host,
            port=port,
            tags=["device"],
            metadata={
                "preferred_path": preferred_path,
                "effective_routable": effective_routable,
                "fallback_available": fallback_available,
                "mesh_overlay_available": mesh_overlay_available,
            },
        )
        self.register_node(node)

        # Register transport path edges
        self._register_device_transport_edges(
            device_id=device_id,
            preferred_path=preferred_path,
            effective_routable=effective_routable,
            fallback_available=fallback_available,
            mesh_overlay_available=mesh_overlay_available,
        )

        self._emit_record(
            "device_assimilated",
            device_id,
            kind=TopologyNodeKind.DEVICE.value,
            state=state.value,
            details={
                "preferred_path": preferred_path,
                "effective_routable": effective_routable,
                "fallback_available": fallback_available,
                "mesh_overlay_available": mesh_overlay_available,
            },
        )
        logger.debug(
            "network_topology_runtime: device_assimilated device=%s path=%s routable=%s",
            device_id,
            preferred_path,
            effective_routable,
        )
        return node

    def _register_device_transport_edges(
        self,
        *,
        device_id: str,
        preferred_path: str,
        effective_routable: bool,
        fallback_available: bool,
        mesh_overlay_available: bool,
    ) -> None:
        """Internal: register transport path edges for a device."""
        # Direct / UCM edge
        if preferred_path in ("direct_ws", "ucm") and effective_routable:
            edge = TopologyEdge(
                edge_id=f"{device_id}::direct",
                source_node_id="galaxy_gateway",
                target_node_id=device_id,
                kind=TopologyEdgeKind.DIRECT,
                state=TopologyConnectionState.PREFERRED,
                preferred=True,
            )
            self.register_edge(edge)

        # Gateway edge — PR-D: absorbed into device transport edges
        if preferred_path == "gateway" and effective_routable:
            edge = TopologyEdge(
                edge_id=f"{device_id}::gateway",
                source_node_id="galaxy_gateway",
                target_node_id=device_id,
                kind=TopologyEdgeKind.GATEWAY,
                state=TopologyConnectionState.PREFERRED,
                preferred=True,
            )
            self.register_edge(edge)

        # Relay fallback edge
        if fallback_available or preferred_path == "relay":
            relay_state = (
                TopologyConnectionState.PREFERRED
                if preferred_path == "relay" and effective_routable
                else TopologyConnectionState.FALLBACK
            )
            edge = TopologyEdge(
                edge_id=f"{device_id}::relay",
                source_node_id="galaxy_relay",
                target_node_id=device_id,
                kind=TopologyEdgeKind.RELAY,
                state=relay_state,
                preferred=(preferred_path == "relay" and effective_routable),
            )
            self.register_edge(edge)

        # Mesh overlay edge
        if mesh_overlay_available or preferred_path == "mesh":
            edge = TopologyEdge(
                edge_id=f"{device_id}::mesh",
                source_node_id="galaxy_mesh",
                target_node_id=device_id,
                kind=TopologyEdgeKind.MESH,
                state=TopologyConnectionState.LATENT,
                preferred=False,
            )
            self.register_edge(edge)

    def project_transport_path(
        self,
        source_id: str,
        target_id: str,
        *,
        transport_strategy: str = "",
        fallback_used: bool = False,
    ) -> TransportPathInfo:
        """Project a canonical transport path for a source→target pair.

        Reads the current topology state and produces a :class:`TransportPathInfo`
        describing the effective path, fallback, and available paths.

        Args:
            source_id:          Source node identifier.
            target_id:          Target node identifier.
            transport_strategy: Current transport strategy string (from
                                ``agent_bus_fabric.select_transport_strategy``).
            fallback_used:      Whether the fallback path is currently in use.

        Returns:
            A :class:`TransportPathInfo` for this node pair.
        """
        with self._rw_lock:
            candidate_edges = [
                e
                for e in self._edges.values()
                if e.source_node_id == source_id and e.target_node_id == target_id
            ]

        active_states = {
            TopologyConnectionState.CONNECTED,
            TopologyConnectionState.PREFERRED,
            TopologyConnectionState.REACHABLE,
            TopologyConnectionState.FALLBACK,
        }

        available: List[str] = []
        effective_path = ""
        fallback_path: Optional[str] = None
        preferred_edge_id = ""

        for edge in candidate_edges:
            edge_state = (
                edge.state
                if isinstance(edge.state, TopologyConnectionState)
                else TopologyConnectionState(edge.state)
            )
            edge_kind = (
                edge.kind.value if isinstance(edge.kind, TopologyEdgeKind) else str(edge.kind)
            )
            if edge_state in active_states:
                available.append(edge_kind)
            if edge.preferred:
                effective_path = edge_kind
                preferred_edge_id = edge.edge_id
            if edge_state == TopologyConnectionState.FALLBACK and fallback_path is None:
                fallback_path = edge_kind

        # If no explicit preferred edge, use strategy hint
        if not effective_path and transport_strategy:
            effective_path = _STRATEGY_TO_EDGE_KIND.get(
                transport_strategy, TopologyEdgeKind.DIRECT
            ).value

        return TransportPathInfo(
            source_id=source_id,
            target_id=target_id,
            effective_path=effective_path,
            fallback_path=fallback_path,
            available_paths=available,
            transport_strategy=transport_strategy,
            preferred_edge_id=preferred_edge_id,
        )

    # ── Observability ─────────────────────────────────────────────────────

    def get_topology_log(self) -> Deque[TopologyRecord]:
        """Return the 256-entry topology-change ring buffer."""
        return self._log

    def snapshot(self, *, max_records: int = 20) -> TopologySnapshot:
        """Return a point-in-time :class:`TopologySnapshot`.

        Args:
            max_records: Maximum number of recent records to include.

        Returns:
            A :class:`TopologySnapshot`.
        """
        with self._rw_lock:
            nodes = list(self._nodes.values())
            edges = list(self._edges.values())

        by_kind: Dict[str, int] = {}
        by_state: Dict[str, int] = {}
        for n in nodes:
            k = n.kind.value if isinstance(n.kind, TopologyNodeKind) else str(n.kind)
            s = n.state.value if isinstance(n.state, TopologyConnectionState) else str(n.state)
            by_kind[k] = by_kind.get(k, 0) + 1
            by_state[s] = by_state.get(s, 0) + 1

        edges_by_kind: Dict[str, int] = {}
        preferred: List[str] = []
        for e in edges:
            k = e.kind.value if isinstance(e.kind, TopologyEdgeKind) else str(e.kind)
            edges_by_kind[k] = edges_by_kind.get(k, 0) + 1
            if e.preferred:
                preferred.append(e.edge_id)

        recent = list(self._log)[-max_records:] if self._log else []

        return TopologySnapshot(
            total_nodes=len(nodes),
            total_edges=len(edges),
            nodes_by_kind=by_kind,
            nodes_by_state=by_state,
            edges_by_kind=edges_by_kind,
            preferred_edges=preferred,
            recent_records=recent,
            truth_governance=build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(
                    RECOVERY_STATUS_DEGRADED if self._last_recovered_at else RECOVERY_STATUS_LIVE
                ),
                revalidation_required=bool(self._recovered_node_ids or self._recovered_edge_ids),
                degraded=bool(self._recovered_node_ids or self._recovered_edge_ids),
                field_truth_grades={
                    "topology_membership": TRUTH_GRADE_PROJECTION,
                    "connection_state": (
                        TRUTH_GRADE_RECOVERABLE if self._last_recovered_at else TRUTH_GRADE_RUNTIME_ONLY
                    ),
                },
                notes=[
                    "Recovered topology is retained as degraded/recoverable view truth until live connectivity assimilations arrive.",
                ],
                extra={
                    "durable_state_path": self._state_path,
                    "recovered_at": self._last_recovered_at,
                    "recovered_node_count": len(self._recovered_node_ids),
                    "recovered_edge_count": len(self._recovered_edge_ids),
                },
            ),
        )

    # ── Internal ──────────────────────────────────────────────────────────

    def _emit_record(
        self,
        event_kind: str,
        node_id: str,
        *,
        kind: str = TopologyNodeKind.UNKNOWN.value,
        state: str = TopologyConnectionState.LATENT.value,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        record = TopologyRecord(
            record_id=_next_record_id(),
            event_kind=event_kind,
            node_id=node_id,
            kind=kind,
            state=state,
            details=dict(details or {}),
        )
        self._log.append(record)

    def persist_durable_state(self) -> None:
        with self._rw_lock:
            payload = {
                "contract_version": "network_topology_runtime_durable_v1",
                "persisted_at": time.time(),
                "nodes": [node.to_dict() for node in self._nodes.values()],
                "edges": [edge.to_dict() for edge in self._edges.values()],
            }
        write_json_atomically(self._state_path, payload)

    def restore_durable_state(self) -> Dict[str, int]:
        payload = load_json_payload(self._state_path)
        node_payloads = payload.get("nodes")
        edge_payloads = payload.get("edges")
        if not isinstance(node_payloads, list) or not isinstance(edge_payloads, list):
            return {"nodes_restored": 0, "edges_restored": 0}
        recovered_wallclock = time.time()
        recovered_monotonic = time.monotonic()
        restored_nodes = 0
        restored_edges = 0
        with self._rw_lock:
            for item in node_payloads:
                if not isinstance(item, dict):
                    continue
                node_id = str(item.get("node_id") or "")
                if not node_id or node_id in self._nodes:
                    continue
                previous_state = str(item.get("state") or TopologyConnectionState.LATENT.value)
                metadata = dict(item.get("metadata") or {})
                metadata["recovered_previous_state"] = previous_state
                metadata["_truth_governance"] = build_truth_governance(
                    TRUTH_GRADE_RECOVERABLE,
                    source="core.network_topology_runtime.NetworkTopologyRuntime",
                    recovery_status=RECOVERY_STATUS_DEGRADED,
                    revalidation_required=True,
                    degraded=True,
                    field_truth_grades={
                        "topology_membership": TRUTH_GRADE_RECOVERABLE,
                        "connection_state": TRUTH_GRADE_RECOVERABLE,
                    },
                    notes=[
                        "Recovered topology nodes are degraded until fresh transport/runtime assimilation revalidates them.",
                        "The previous pre-restart state is retained for operator observability only.",
                    ],
                    extra={"recovered_at": recovered_wallclock},
                )
                self._nodes[node_id] = TopologyNode(
                    node_id=node_id,
                    kind=TopologyNodeKind(str(item.get("kind") or TopologyNodeKind.UNKNOWN.value)),
                    state=TopologyConnectionState.DEGRADED,
                    host=str(item.get("host") or ""),
                    port=int(item.get("port") or 0),
                    transport_hints=dict(item.get("transport_hints") or {}),
                    tags=list(item.get("tags") or []) + ["recovered_unrevalidated"],
                    metadata=metadata,
                    registered_at=recovered_monotonic,
                    last_updated_at=recovered_monotonic,
                )
                self._recovered_node_ids.add(node_id)
                restored_nodes += 1
            for item in edge_payloads:
                if not isinstance(item, dict):
                    continue
                edge_id = str(item.get("edge_id") or "")
                if not edge_id or edge_id in self._edges:
                    continue
                previous_state = str(item.get("state") or TopologyConnectionState.LATENT.value)
                metadata = dict(item.get("metadata") or {})
                metadata["recovered_previous_state"] = previous_state
                metadata["_truth_governance"] = build_truth_governance(
                    TRUTH_GRADE_RECOVERABLE,
                    source="core.network_topology_runtime.NetworkTopologyRuntime",
                    recovery_status=RECOVERY_STATUS_DEGRADED,
                    revalidation_required=True,
                    degraded=True,
                    field_truth_grades={
                        "topology_membership": TRUTH_GRADE_RECOVERABLE,
                        "connection_state": TRUTH_GRADE_RECOVERABLE,
                    },
                    notes=[
                        "Recovered topology edges remain degraded until live path assimilation revalidates them.",
                        "The previous pre-restart state is retained for operator observability only.",
                    ],
                    extra={"recovered_at": recovered_wallclock},
                )
                self._edges[edge_id] = TopologyEdge(
                    edge_id=edge_id,
                    source_node_id=str(item.get("source_node_id") or ""),
                    target_node_id=str(item.get("target_node_id") or ""),
                    kind=TopologyEdgeKind(str(item.get("kind") or TopologyEdgeKind.DIRECT.value)),
                    state=TopologyConnectionState.DEGRADED,
                    preferred=bool(item.get("preferred")),
                    latency_hint_ms=int(item.get("latency_hint_ms") or 0),
                    metadata=metadata,
                    created_at=recovered_monotonic,
                    last_updated_at=recovered_monotonic,
                )
                self._recovered_edge_ids.add(edge_id)
                restored_edges += 1
            if restored_nodes or restored_edges:
                self._last_recovered_at = recovered_wallclock
        return {"nodes_restored": restored_nodes, "edges_restored": restored_edges}

    def clear_durable_state(self) -> None:
        try:
            if os.path.exists(self._state_path):
                os.remove(self._state_path)
        except OSError:
            logger.warning("network_topology_runtime durable clear failed: %s", self._state_path)


# ---------------------------------------------------------------------------
# Module-level absorption helpers (convenience wrappers)
# ---------------------------------------------------------------------------


def assimilate_transport_hierarchy_record(
    strategy_record: Any,
    *,
    source_id: str = "galaxy_gateway",
    target_id: str = "",
) -> Optional["TopologyEdge"]:
    """Absorb a ``FabricTransportStrategyRecord`` into the topology runtime.

    Creates a :class:`TopologyEdge` from the strategy's selected transport,
    marking it as preferred when no fallback was used.

    Args:
        strategy_record: A ``FabricTransportStrategyRecord`` from
                         ``core.agent_bus_fabric.select_transport_strategy``.
        source_id:       Source node identifier (default ``"galaxy_gateway"``).
        target_id:       Target node identifier (required for a useful edge).

    Returns:
        The registered :class:`TopologyEdge`, or ``None`` if ``target_id``
        is empty.
    """
    if not target_id:
        return None

    runtime = get_network_topology_runtime()
    strategy = getattr(strategy_record, "strategy", "")
    fallback_used = getattr(strategy_record, "fallback_used", False)
    edge_kind = _STRATEGY_TO_EDGE_KIND.get(strategy, TopologyEdgeKind.DIRECT)
    state = (
        TopologyConnectionState.FALLBACK
        if fallback_used
        else TopologyConnectionState.PREFERRED
    )
    edge = TopologyEdge(
        edge_id=f"{source_id}::{target_id}::{strategy}",
        source_node_id=source_id,
        target_node_id=target_id,
        kind=edge_kind,
        state=state,
        preferred=not fallback_used,
        metadata={"transport_strategy": strategy, "fallback_used": fallback_used},
    )
    return runtime.register_edge(edge)


def assimilate_nats_state(
    is_connected: bool,
    host: str = "",
    port: int = 0,
    node_id: str = "nats_fabric",
) -> "TopologyNode":
    """Convenience wrapper: absorb NATS fabric state into the topology runtime.

    Args:
        is_connected: Whether the NATS fabric is currently connected.
        host:         NATS server host.
        port:         NATS server port.
        node_id:      Override node identifier (default ``"nats_fabric"``).

    Returns:
        The created/updated :class:`TopologyNode`.
    """
    return get_network_topology_runtime().absorb_nats_state(
        is_connected=is_connected,
        host=host,
        port=port,
        node_id=node_id,
    )


def assimilate_gateway_state(
    gateway_id: str,
    host: str = "",
    port: int = 0,
    is_connected: bool = False,
) -> "TopologyNode":
    """Convenience wrapper: absorb gateway substrate state into the topology runtime.

    Args:
        gateway_id:   Unique gateway identifier.
        host:         Gateway host address.
        port:         Gateway port.
        is_connected: Whether the gateway is currently connected.

    Returns:
        The created/updated :class:`TopologyNode`.
    """
    return get_network_topology_runtime().absorb_gateway_state(
        gateway_id=gateway_id,
        host=host,
        port=port,
        is_connected=is_connected,
    )


def assimilate_device_connectivity(
    device_id: str,
    preferred_path: str = "",
    effective_routable: bool = False,
    fallback_available: bool = False,
    mesh_overlay_available: bool = False,
    host: str = "",
    port: int = 0,
) -> "TopologyNode":
    """Convenience wrapper: absorb device connectivity state.

    Args:
        device_id:             Device identifier.
        preferred_path:        Preferred transport path string.
        effective_routable:    Whether the device is currently routable.
        fallback_available:    Whether a relay fallback is available.
        mesh_overlay_available: Whether mesh overlay is available.
        host:                  Device host address.
        port:                  Device port.

    Returns:
        The created/updated :class:`TopologyNode`.
    """
    return get_network_topology_runtime().absorb_device_connectivity(
        device_id=device_id,
        preferred_path=preferred_path,
        effective_routable=effective_routable,
        fallback_available=fallback_available,
        mesh_overlay_available=mesh_overlay_available,
        host=host,
        port=port,
    )


def project_transport_path(
    source_id: str,
    target_id: str,
    *,
    transport_strategy: str = "",
    fallback_used: bool = False,
) -> "TransportPathInfo":
    """Convenience wrapper: project a canonical transport path.

    Args:
        source_id:          Source node identifier.
        target_id:          Target node identifier.
        transport_strategy: Current transport strategy string.
        fallback_used:      Whether the fallback path is currently in use.

    Returns:
        A :class:`TransportPathInfo`.
    """
    return get_network_topology_runtime().project_transport_path(
        source_id,
        target_id,
        transport_strategy=transport_strategy,
        fallback_used=fallback_used,
    )


def build_grounded_runtime_topology(*, max_allocation_records: int = 128) -> GroundedRuntimeTopology:
    """Build a grounded runtime topology from live canonical runtime objects."""
    now = time.time()
    runtime = get_network_topology_runtime()
    topology_nodes = runtime.all_nodes()
    grounded_nodes: List[Dict[str, Any]] = [n.to_dict() for n in topology_nodes]
    relations: List[GroundedTopologyRelation] = []

    node_ids = {str(n.get("node_id") or "") for n in grounded_nodes}

    try:
        from core.nodes.node_fabric_registry import get_node_fabric_registry

        for node in get_node_fabric_registry().list_nodes():
            sid = f"fabric::{node.node_id}"
            if sid in node_ids:
                continue
            grounded_nodes.append(
                {
                    "node_id": sid,
                    "kind": "runtime_provider_node",
                    "state": str(node.status.value if hasattr(node.status, "value") else node.status),
                    "host": node.host,
                    "port": node.port,
                    "tags": ["node_fabric", str(node.role.value if hasattr(node.role, "value") else node.role)],
                    "metadata": {
                        "fabric_node_id": node.node_id,
                        "architectural_class": str(
                            node.architectural_class.value
                            if hasattr(node.architectural_class, "value")
                            else node.architectural_class
                        ),
                        "runtime_host": str(getattr(node, "runtime_host", "v2_control_plane")),
                        "session_owner": str(getattr(node, "session_owner", "") or ""),
                        "execution_owner": str(getattr(node, "execution_owner", "") or ""),
                        "participant_id": str(getattr(node, "participant_id", "") or ""),
                        "device_id": str(getattr(node, "device_id", "") or ""),
                    },
                    "truth_governance": dict((node.metadata or {}).get("_truth_governance") or {}),
                    "registered_at": float(getattr(node, "registered_at", now) or now),
                    "last_updated_at": float(getattr(node, "last_heartbeat", now) or now),
                    "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
                }
            )
            node_ids.add(sid)
            relations.append(
                GroundedTopologyRelation(
                    relation_kind="runtime_host_registers_node",
                    source_id="v2_control_plane",
                    target_id=sid,
                    evidence={"node_id": node.node_id},
                    truth_grade=str(
                        ((node.metadata or {}).get("_truth_governance") or {}).get(
                            "truth_grade",
                            TRUTH_GRADE_RECOVERABLE,
                        )
                    ),
                )
            )
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    try:
        from core.canonical_task import get_canonical_task_runtime

        allocation_records = get_canonical_task_runtime().list_allocation_records(
            limit=max(1, int(max_allocation_records))
        )
        for rec in allocation_records:
            owner = str(rec.execution_owner or rec.selected_executor or rec.execution_location or "").strip()
            if not owner:
                continue
            relations.append(
                GroundedTopologyRelation(
                    relation_kind="task_allocated_to_executor",
                    source_id=f"task::{rec.task_id}",
                    target_id=owner,
                    evidence={
                        "requested_allocation": rec.requested_allocation,
                        "accepted_allocation": rec.accepted_allocation,
                        "fallback_used": bool(rec.fallback_used),
                        "canonical_closed": bool(rec.canonical_closed),
                        "session_owner": rec.session_owner,
                        "execution_owner": rec.execution_owner,
                        "runtime_host": rec.runtime_host,
                        "updated_at": rec.updated_at,
                    },
                    truth_grade=TRUTH_GRADE_DURABLE,
                )
            )
    except Exception as exc:
        logger.debug("Fallback triggered: %s", exc)
        allocation_records = []

    root_children: List[str] = []
    for node in grounded_nodes:
        node_id = str(node.get("node_id") or "")
        if not node_id:
            continue
        kind = str(node.get("kind") or "unknown")
        if kind in {"runtime_provider_node", "device", "gateway", "nats_fabric_endpoint"}:
            root_children.append(node_id)

    galaxy_tree = {
        "root": "v2_control_plane",
        "children": sorted(set(root_children)),
        "relation_count": len(relations),
        "allocation_relation_count": len(
            [r for r in relations if r.relation_kind == "task_allocated_to_executor"]
        ),
    }

    return GroundedRuntimeTopology(
        runtime_host="v2_control_plane",
        generated_at=now,
        nodes=grounded_nodes,
        relations=relations,
        galaxy_tree=galaxy_tree,
        truth_governance=build_truth_governance(
            TRUTH_GRADE_PROJECTION,
            source="core.network_topology_runtime.build_grounded_runtime_topology",
            recovery_status=runtime.snapshot().truth_governance.get("recovery_status", RECOVERY_STATUS_LIVE),
            revalidation_required=runtime.snapshot().truth_governance.get("revalidation_required", False),
            degraded=runtime.snapshot().truth_governance.get("degraded", False),
            field_truth_grades={
                "grounded_runtime_topology": TRUTH_GRADE_PROJECTION,
                "task_allocation_relations": TRUTH_GRADE_DURABLE,
                "recovered_node_registry_relations": TRUTH_GRADE_RECOVERABLE,
            },
            notes=[
                "Grounded runtime topology is an outward projection rebuilt from canonical task truth plus recoverable topology/node views.",
            ],
        ),
    )


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------


def get_network_topology_runtime() -> NetworkTopologyRuntime:
    """Return the global :class:`NetworkTopologyRuntime` singleton."""
    return NetworkTopologyRuntime()


def reset_network_topology_runtime(*, clear_durable_state: bool = False) -> None:
    """Reset the :class:`NetworkTopologyRuntime` singleton (for testing)."""
    if clear_durable_state and NetworkTopologyRuntime._instance is not None:
        try:
            NetworkTopologyRuntime._instance.clear_durable_state()
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
    NetworkTopologyRuntime._instance = None
