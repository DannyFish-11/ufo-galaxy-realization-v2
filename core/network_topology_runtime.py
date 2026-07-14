"""
core.network_topology_runtime — Canonical Network Topology Runtime (PR-8)
==========================================================================
Canonical device/gateway/fabric topology runtime for the V2 control plane.

Responsibilities
----------------
1. Maintain the single authoritative node/edge topology view:
   devices, gateways, relays, mesh participants, NATS fabric endpoints
   and runtime provider nodes.
2. Absorb transport hierarchy signals (NATS fabric state, gateway substrate
   state, device connectivity reports) into topology nodes and edges.
3. Project transport path selections as topology edges.
4. Provide a JSON-safe :class:`TopologySnapshot` for renderers, planners and
   the operator console.
5. Persist a durable view and restore it as *degraded* recoverable truth
   after a runtime restart.

Legacy PR-28 surface
--------------------
The original network-position/path-assessment surface
(:class:`NetworkPosition`, :class:`PathAssessment`, ``assess_path`` …) is
retained for ``AIPTransport`` smart transport selection.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import platform
import socket
import subprocess
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
    TRUTH_GRADE_PROJECTION,
    TRUTH_GRADE_RECOVERABLE,
    build_truth_governance,
    load_json_payload,
    write_json_atomically,
)

logger = logging.getLogger("Galaxy.NetworkTopology")

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
    "TransportPathInfo",
    "TopologySnapshot",
    "GroundedRuntimeTopology",
    # Class
    "NetworkTopologyRuntime",
    # Module-level assimilation / projection helpers
    "assimilate_nats_state",
    "assimilate_gateway_state",
    "assimilate_device_connectivity",
    "assimilate_transport_hierarchy_record",
    "project_transport_path",
    "build_grounded_runtime_topology",
    # Singleton helpers
    "get_network_topology_runtime",
    "reset_network_topology_runtime",
    # Legacy PR-28 surface
    "NetworkPosition",
    "PathAssessment",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Module authority marker.
NETWORK_TOPOLOGY_RUNTIME_AUTHORITY: str = (
    "core.network_topology_runtime" " — canonical device/gateway/fabric topology runtime (PR-8)"
)

#: Layer position within the canonical control-plane stack.
NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION: int = 8

#: Contract version for serialised topology objects.
NETWORK_TOPOLOGY_CONTRACT_VERSION: str = "v1"

#: Consumer policy: renderers/planners/narratives read topology only from here.
TOPOLOGY_CONSUMER_POLICY: str = (
    "TOPOLOGY_CONSUMER_POLICY::all topology consumers (status board renderer,"
    " planner, operator narrative, projection surfaces) MUST consume topology"
    " from NETWORK_TOPOLOGY_RUNTIME snapshots — no consumer maintains its own"
    " shadow topology map."
)

#: Transport hierarchy assimilation policy.
TRANSPORT_HIERARCHY_ASSIMILATION_POLICY: str = (
    "TRANSPORT_HIERARCHY_ASSIMILATION_POLICY::transport hierarchy signals"
    " (NATS fabric state, gateway substrate state, device connectivity,"
    " transport path selection) are ABSORBED into NETWORK_TOPOLOGY_RUNTIME"
    " nodes and edges rather than tracked in per-transport side maps."
)

_NETWORK_TOPOLOGY_STATE_PATH_ENV: str = "GALAXY_NETWORK_TOPOLOGY_RUNTIME_STATE_PATH"
_DEFAULT_NETWORK_TOPOLOGY_STATE_PATH: str = os.getenv(
    _NETWORK_TOPOLOGY_STATE_PATH_ENV,
    "data/runtime/network_topology_runtime_state.json",
)

#: Canonical runtime-host identity used as the implicit edge source for
#: absorbed connectivity edges and the grounded topology root.
GROUNDED_RUNTIME_HOST_ID: str = "v2_control_plane"

#: Canonical node id used for the (single) NATS fabric endpoint node.
NATS_FABRIC_NODE_ID: str = "nats_fabric"

_TOPOLOGY_PROBE_INTERVAL = 30.0


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TopologyNodeKind(str, Enum):
    """Kind of a node in the canonical topology."""

    DEVICE = "device"
    GATEWAY = "gateway"
    RELAY = "relay"
    MESH_PARTICIPANT = "mesh_participant"
    NATS_FABRIC_ENDPOINT = "nats_fabric_endpoint"
    RUNTIME_PROVIDER_NODE = "runtime_provider_node"
    UNKNOWN = "unknown"


class TopologyEdgeKind(str, Enum):
    """Kind of a directed edge in the canonical topology."""

    DIRECT = "direct"
    GATEWAY = "gateway"
    RELAY = "relay"
    MESH = "mesh"
    FABRIC = "fabric"
    PROJECTED_SEMANTIC = "projected_semantic"


class TopologyConnectionState(str, Enum):
    """Connection state for topology nodes and edges."""

    REACHABLE = "reachable"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    PREFERRED = "preferred"
    FALLBACK = "fallback"
    LATENT = "latent"
    UNAVAILABLE = "unavailable"


def _kind_value(kind: Any) -> str:
    return kind.value if isinstance(kind, Enum) else str(kind)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TopologyNode:
    """A node in the canonical topology."""

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
            "kind": _kind_value(self.kind),
            "state": _kind_value(self.state),
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
    """A directed edge in the canonical topology."""

    edge_id: str
    source_node_id: str
    target_node_id: str
    kind: TopologyEdgeKind = TopologyEdgeKind.DIRECT
    state: TopologyConnectionState = TopologyConnectionState.LATENT
    preferred: bool = False
    latency_hint_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.monotonic)
    last_updated_at: float = field(default_factory=time.monotonic)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "kind": _kind_value(self.kind),
            "state": _kind_value(self.state),
            "preferred": bool(self.preferred),
            "latency_hint_ms": self.latency_hint_ms,
            "metadata": dict(self.metadata),
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class TopologyRecord:
    """Observability record emitted whenever the topology changes."""

    record_id: str
    event_kind: str
    node_id: str = ""
    kind: str = TopologyNodeKind.UNKNOWN.value
    state: str = ""
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
    """Projection of one transport path selection between two nodes."""

    source_id: str = ""
    target_id: str = ""
    effective_path: str = ""
    fallback_path: str = ""
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
    """Point-in-time snapshot of the canonical topology."""

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
            "truth_governance": dict(self.truth_governance),
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


@dataclass
class GroundedRuntimeTopology:
    """Operator-facing grounded topology rooted at the V2 runtime host."""

    runtime_host: str = GROUNDED_RUNTIME_HOST_ID
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    galaxy_tree: Dict[str, Any] = field(default_factory=dict)
    truth_governance: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "runtime_host": self.runtime_host,
            "nodes": list(self.nodes),
            "relations": list(self.relations),
            "galaxy_tree": dict(self.galaxy_tree),
            "truth_governance": dict(self.truth_governance),
            "contract_version": NETWORK_TOPOLOGY_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Legacy PR-28 dataclasses (network-position / path-assessment surface)
# ---------------------------------------------------------------------------


@dataclass
class NetworkPosition:
    """Network position of a single device (legacy PR-28 surface)."""

    device_id: str = ""
    lan_subnet: str = ""
    lan_ip: str = ""
    tailscale_ip: str = ""
    tailscale_hostname: str = ""
    public_ip: str = ""
    public_port: int = 0
    nat_type: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    last_seen: float = field(default_factory=time.time)
    rtt_ms: float = 999.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "lan_subnet": self.lan_subnet,
            "lan_ip": self.lan_ip,
            "tailscale_ip": self.tailscale_ip,
            "tailscale_hostname": self.tailscale_hostname,
            "public_ip": self.public_ip,
            "nat_type": self.nat_type,
            "capabilities": list(self.capabilities),
            "rtt_ms": self.rtt_ms,
        }


@dataclass
class PathAssessment:
    """Best path assessment between two devices (legacy PR-28 surface)."""

    source: str = ""
    target: str = ""
    best_path: str = "unknown"
    recommended_transport: str = "websocket"
    estimated_rtt_ms: float = 999.0
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "best_path": self.best_path,
            "recommended_transport": self.recommended_transport,
            "estimated_rtt_ms": round(self.estimated_rtt_ms, 1),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# NetworkTopologyRuntime
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256
_record_counter: int = 0
_record_lock: threading.Lock = threading.Lock()

#: Mapping from device preferred-path / transport-strategy strings to kinds.
_PATH_TO_EDGE_KIND: Dict[str, TopologyEdgeKind] = {
    "direct": TopologyEdgeKind.DIRECT,
    "direct_ws": TopologyEdgeKind.DIRECT,
    "tcp": TopologyEdgeKind.DIRECT,
    "relay": TopologyEdgeKind.RELAY,
    "derp_relay": TopologyEdgeKind.RELAY,
    "gateway": TopologyEdgeKind.GATEWAY,
    "gateway_ws": TopologyEdgeKind.GATEWAY,
    "websocket": TopologyEdgeKind.GATEWAY,
    "mesh": TopologyEdgeKind.MESH,
    "nats": TopologyEdgeKind.FABRIC,
    "nats_fabric": TopologyEdgeKind.FABRIC,
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
    * Track every topology participant as a :class:`TopologyNode`.
    * Track connectivity paths as :class:`TopologyEdge` objects.
    * Absorb NATS fabric / gateway substrate / device connectivity signals.
    * Maintain a 256-entry observability ring buffer.
    * Persist a durable view; restore it as degraded recoverable truth.

    Thread safety
    -------------
    All mutations are protected by a :class:`threading.RLock`.
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
        self._rw_lock: threading.RLock = threading.RLock()
        self._state_path: str = _DEFAULT_NETWORK_TOPOLOGY_STATE_PATH
        self._last_recovered_at: Optional[float] = None
        self._recovered_node_ids: set[str] = set()
        self._recovered_edge_ids: set[str] = set()
        # Legacy PR-28 network-position state
        self._positions: Dict[str, NetworkPosition] = {}
        self._my_device_id: str = ""
        self._my_position: NetworkPosition = NetworkPosition()
        self._running = False
        self._probe_task: Optional[asyncio.Task] = None

    # ── Node management ───────────────────────────────────────────────────

    def register_node(self, node: TopologyNode) -> TopologyNode:
        """Register or update a :class:`TopologyNode`.

        Re-registration updates the node in place and preserves the
        original ``registered_at`` timestamp.

        Raises:
            ValueError: If ``node.node_id`` is empty.
        """
        if not node.node_id:
            raise ValueError("TopologyNode.node_id must be non-empty")

        with self._rw_lock:
            is_update = node.node_id in self._nodes
            if is_update:
                node.registered_at = self._nodes[node.node_id].registered_at
            node.last_updated_at = time.monotonic()
            node.metadata = dict(node.metadata)
            node.tags = [tag for tag in node.tags if tag != "recovered_unrevalidated"]
            node.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(
                    RECOVERY_STATUS_REVALIDATED if node.node_id in self._recovered_node_ids else RECOVERY_STATUS_LIVE
                ),
                field_truth_grades={"topology_view": TRUTH_GRADE_PROJECTION},
                notes=[
                    "Topology runtime is a canonical runtime topology view, not durable lifecycle truth.",
                ],
            )
            self._nodes[node.node_id] = node
            self._recovered_node_ids.discard(node.node_id)

        self._emit_record(
            "node_updated" if is_update else "node_registered",
            node.node_id,
            kind=_kind_value(node.kind),
            state=_kind_value(node.state),
            details={"host": node.host, "port": node.port, "tags": list(node.tags)},
        )
        self.persist_durable_state()
        return node

    def update_node_state(self, node_id: str, state: TopologyConnectionState) -> Optional[TopologyNode]:
        """Update a node's connection state; ``None`` for unknown nodes."""
        with self._rw_lock:
            node = self._nodes.get(node_id)
            if node is None:
                return None
            node.state = state
            node.last_updated_at = time.monotonic()
        self._emit_record(
            "node_state_changed",
            node_id,
            kind=_kind_value(node.kind),
            state=_kind_value(state),
        )
        self.persist_durable_state()
        return node

    def remove_node(self, node_id: str) -> bool:
        """Remove a node and all edges incident to it."""
        with self._rw_lock:
            node = self._nodes.pop(node_id, None)
            if node is None:
                return False
            removed_edges = [
                eid for eid, e in self._edges.items() if e.source_node_id == node_id or e.target_node_id == node_id
            ]
            for eid in removed_edges:
                del self._edges[eid]
                self._recovered_edge_ids.discard(eid)
            self._recovered_node_ids.discard(node_id)

        self._emit_record(
            "node_removed",
            node_id,
            kind=_kind_value(node.kind),
            details={"removed_edges": len(removed_edges)},
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
        """Register a :class:`TopologyEdge` (same ``edge_id`` overwrites).

        Raises:
            ValueError: If ``edge.edge_id`` is empty.
        """
        if not edge.edge_id:
            raise ValueError("TopologyEdge.edge_id must be non-empty")

        with self._rw_lock:
            edge.last_updated_at = time.monotonic()
            edge.metadata = dict(edge.metadata)
            edge.metadata["_truth_governance"] = build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(
                    RECOVERY_STATUS_REVALIDATED if edge.edge_id in self._recovered_edge_ids else RECOVERY_STATUS_LIVE
                ),
                field_truth_grades={"topology_view": TRUTH_GRADE_PROJECTION},
            )
            self._edges[edge.edge_id] = edge
            self._recovered_edge_ids.discard(edge.edge_id)

        self._emit_record(
            "edge_registered",
            edge.source_node_id,
            kind=_kind_value(edge.kind),
            state=_kind_value(edge.state),
            details={
                "edge_id": edge.edge_id,
                "target_node_id": edge.target_node_id,
                "preferred": bool(edge.preferred),
            },
        )
        self.persist_durable_state()
        return edge

    def update_edge_state(
        self,
        edge_id: str,
        state: TopologyConnectionState,
        *,
        preferred: Optional[bool] = None,
    ) -> Optional[TopologyEdge]:
        """Update an edge's state (and optionally its preference flag)."""
        with self._rw_lock:
            edge = self._edges.get(edge_id)
            if edge is None:
                return None
            edge.state = state
            if preferred is not None:
                edge.preferred = bool(preferred)
            edge.last_updated_at = time.monotonic()
        self._emit_record(
            "edge_state_changed",
            edge.source_node_id,
            kind=_kind_value(edge.kind),
            state=_kind_value(state),
            details={"edge_id": edge_id},
        )
        self.persist_durable_state()
        return edge

    def remove_edge(self, edge_id: str) -> bool:
        """Remove an edge; ``False`` if not present."""
        with self._rw_lock:
            edge = self._edges.pop(edge_id, None)
            if edge is None:
                return False
            self._recovered_edge_ids.discard(edge_id)
        self._emit_record(
            "edge_removed",
            edge.source_node_id,
            kind=_kind_value(edge.kind),
            details={"edge_id": edge_id},
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
        """Return only the edges flagged as preferred."""
        with self._rw_lock:
            return [e for e in self._edges.values() if e.preferred]

    # ── Transport hierarchy absorption ────────────────────────────────────

    def absorb_nats_state(self, is_connected: bool, host: str = "", port: int = 0) -> TopologyNode:
        """Absorb NATS fabric state into the canonical NATS endpoint node."""
        with self._rw_lock:
            existing = self._nodes.get(NATS_FABRIC_NODE_ID)
            node = TopologyNode(
                node_id=NATS_FABRIC_NODE_ID,
                kind=TopologyNodeKind.NATS_FABRIC_ENDPOINT,
                state=(TopologyConnectionState.CONNECTED if is_connected else TopologyConnectionState.UNAVAILABLE),
                host=host or (existing.host if existing else ""),
                port=port or (existing.port if existing else 0),
                tags=["nats", "fabric"],
                metadata={"is_connected": bool(is_connected)},
            )
            self.register_node(node)
        self._emit_record(
            "nats_assimilated",
            NATS_FABRIC_NODE_ID,
            kind=TopologyNodeKind.NATS_FABRIC_ENDPOINT.value,
            state=_kind_value(node.state),
            details={"is_connected": bool(is_connected), "host": node.host, "port": node.port},
        )
        return node

    def absorb_gateway_state(
        self,
        gateway_id: str,
        host: str = "",
        port: int = 0,
        is_connected: bool = False,
    ) -> TopologyNode:
        """Absorb gateway substrate state into a GATEWAY node."""
        with self._rw_lock:
            existing = self._nodes.get(gateway_id)
            node = TopologyNode(
                node_id=gateway_id,
                kind=TopologyNodeKind.GATEWAY,
                state=(TopologyConnectionState.CONNECTED if is_connected else TopologyConnectionState.UNAVAILABLE),
                host=host or (existing.host if existing else ""),
                port=port or (existing.port if existing else 0),
                tags=["gateway", "substrate"],
                metadata={"is_connected": bool(is_connected)},
            )
            self.register_node(node)
        self._emit_record(
            "gateway_assimilated",
            gateway_id,
            kind=TopologyNodeKind.GATEWAY.value,
            state=_kind_value(node.state),
            details={"is_connected": bool(is_connected), "host": node.host, "port": node.port},
        )
        return node

    def absorb_device_connectivity(
        self,
        device_id: str,
        *,
        preferred_path: str = "",
        effective_routable: bool = False,
        fallback_available: bool = False,
        mesh_overlay_available: bool = False,
        host: str = "",
        port: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TopologyNode:
        """Absorb a device connectivity report into a DEVICE node + edges.

        Edge projection
        ---------------
        * ``preferred_path`` (direct_ws/relay/gateway/…) → a preferred edge of
          the mapped kind in ``PREFERRED`` (or ``FALLBACK`` if not routable)
          state.
        * ``fallback_available`` → an additional RELAY edge in ``FALLBACK``
          state.
        * ``mesh_overlay_available`` → an additional MESH edge in ``LATENT``
          state.
        """
        if effective_routable:
            state = TopologyConnectionState.CONNECTED if preferred_path else TopologyConnectionState.REACHABLE
        elif fallback_available:
            state = TopologyConnectionState.FALLBACK
        elif mesh_overlay_available:
            state = TopologyConnectionState.LATENT
        else:
            state = TopologyConnectionState.UNAVAILABLE

        node_metadata: Dict[str, Any] = dict(metadata or {})
        node_metadata.update(
            {
                "preferred_path": preferred_path,
                "effective_routable": bool(effective_routable),
                "fallback_available": bool(fallback_available),
                "mesh_overlay_available": bool(mesh_overlay_available),
            }
        )

        with self._rw_lock:
            existing = self._nodes.get(device_id)
            node = TopologyNode(
                node_id=device_id,
                kind=TopologyNodeKind.DEVICE,
                state=state,
                host=host or (existing.host if existing else ""),
                port=port or (existing.port if existing else 0),
                tags=["device"],
                metadata=node_metadata,
            )
            self.register_node(node)

            preferred_kind = _PATH_TO_EDGE_KIND.get(str(preferred_path).lower())
            if preferred_kind is not None:
                self.register_edge(
                    TopologyEdge(
                        edge_id=f"{GROUNDED_RUNTIME_HOST_ID}::{device_id}::preferred",
                        source_node_id=GROUNDED_RUNTIME_HOST_ID,
                        target_node_id=device_id,
                        kind=preferred_kind,
                        state=(
                            TopologyConnectionState.PREFERRED
                            if effective_routable
                            else TopologyConnectionState.FALLBACK
                        ),
                        preferred=True,
                        metadata={"preferred_path": preferred_path},
                    )
                )
            if fallback_available:
                self.register_edge(
                    TopologyEdge(
                        edge_id=f"{GROUNDED_RUNTIME_HOST_ID}::{device_id}::fallback",
                        source_node_id=GROUNDED_RUNTIME_HOST_ID,
                        target_node_id=device_id,
                        kind=TopologyEdgeKind.RELAY,
                        state=TopologyConnectionState.FALLBACK,
                        preferred=False,
                        metadata={"role": "fallback"},
                    )
                )
            if mesh_overlay_available:
                self.register_edge(
                    TopologyEdge(
                        edge_id=f"{GROUNDED_RUNTIME_HOST_ID}::{device_id}::mesh",
                        source_node_id=GROUNDED_RUNTIME_HOST_ID,
                        target_node_id=device_id,
                        kind=TopologyEdgeKind.MESH,
                        state=TopologyConnectionState.LATENT,
                        preferred=False,
                        metadata={"role": "mesh_overlay"},
                    )
                )

        self._emit_record(
            "device_assimilated",
            device_id,
            kind=TopologyNodeKind.DEVICE.value,
            state=_kind_value(state),
            details={
                "preferred_path": preferred_path,
                "effective_routable": bool(effective_routable),
                "fallback_available": bool(fallback_available),
                "mesh_overlay_available": bool(mesh_overlay_available),
            },
        )
        return node

    def project_transport_path(
        self,
        source_id: str,
        target_id: str,
        *,
        transport_strategy: str = "direct",
    ) -> TransportPathInfo:
        """Project the transport path view between two nodes (read-only).

        Inspects the registered edges between *source_id* and *target_id*:
        the preferred edge determines ``effective_path`` /
        ``preferred_edge_id``; edges in active states (PREFERRED, CONNECTED,
        REACHABLE, FALLBACK) populate ``available_paths``; the first FALLBACK
        edge populates ``fallback_path``. With no preferred edge the
        *transport_strategy* hint becomes the effective path.
        """
        with self._rw_lock:
            edges = [e for e in self._edges.values() if e.source_node_id == source_id and e.target_node_id == target_id]

        active_states = {
            TopologyConnectionState.PREFERRED,
            TopologyConnectionState.CONNECTED,
            TopologyConnectionState.REACHABLE,
            TopologyConnectionState.FALLBACK,
        }
        available_paths: List[str] = []
        for e in edges:
            kind_val = _kind_value(e.kind)
            if e.state in active_states and kind_val not in available_paths:
                available_paths.append(kind_val)

        preferred_edge = next((e for e in edges if e.preferred), None)
        fallback_edge = next((e for e in edges if e.state == TopologyConnectionState.FALLBACK), None)
        return TransportPathInfo(
            source_id=source_id,
            target_id=target_id,
            effective_path=(_kind_value(preferred_edge.kind) if preferred_edge else transport_strategy),
            fallback_path=_kind_value(fallback_edge.kind) if fallback_edge else "",
            available_paths=available_paths,
            transport_strategy=transport_strategy,
            preferred_edge_id=preferred_edge.edge_id if preferred_edge else "",
        )

    def assimilate_transport_hierarchy_record(
        self,
        record: Any,
        *,
        source_id: str = GROUNDED_RUNTIME_HOST_ID,
        target_id: str = "",
    ) -> Optional[TopologyEdge]:
        """Absorb a fabric transport strategy record as a topology edge.

        ``record`` must expose ``strategy`` (str) and ``fallback_used``
        (bool) attributes. Returns ``None`` when *target_id* is empty.
        """
        if not target_id:
            return None
        strategy = str(getattr(record, "strategy", "") or "")
        fallback_used = bool(getattr(record, "fallback_used", False))
        return self.register_edge(
            TopologyEdge(
                edge_id=f"{source_id}::{target_id}::{strategy}",
                source_node_id=source_id,
                target_node_id=target_id,
                kind=_PATH_TO_EDGE_KIND.get(strategy.lower(), TopologyEdgeKind.DIRECT),
                state=(TopologyConnectionState.FALLBACK if fallback_used else TopologyConnectionState.PREFERRED),
                preferred=not fallback_used,
                metadata={"transport_strategy": strategy, "fallback_used": fallback_used},
            )
        )

    # ── Observability ─────────────────────────────────────────────────────

    def get_topology_log(self) -> Deque[TopologyRecord]:
        """Return the 256-entry topology-change ring buffer."""
        return self._log

    def snapshot(self, *, max_records: int = 20) -> TopologySnapshot:
        """Return a point-in-time :class:`TopologySnapshot`."""
        with self._rw_lock:
            nodes = list(self._nodes.values())
            edges = list(self._edges.values())
            degraded = bool(self._recovered_node_ids or self._recovered_edge_ids)
            recovered_at = self._last_recovered_at
            recovered_nodes = len(self._recovered_node_ids)
            recovered_edges = len(self._recovered_edge_ids)

        nodes_by_kind: Dict[str, int] = {}
        nodes_by_state: Dict[str, int] = {}
        for n in nodes:
            kind_val = _kind_value(n.kind)
            state_val = _kind_value(n.state)
            nodes_by_kind[kind_val] = nodes_by_kind.get(kind_val, 0) + 1
            nodes_by_state[state_val] = nodes_by_state.get(state_val, 0) + 1

        edges_by_kind: Dict[str, int] = {}
        for e in edges:
            kind_val = _kind_value(e.kind)
            edges_by_kind[kind_val] = edges_by_kind.get(kind_val, 0) + 1

        return TopologySnapshot(
            total_nodes=len(nodes),
            total_edges=len(edges),
            nodes_by_kind=nodes_by_kind,
            nodes_by_state=nodes_by_state,
            edges_by_kind=edges_by_kind,
            preferred_edges=[e.edge_id for e in edges if e.preferred],
            recent_records=list(self._log)[-max_records:] if self._log else [],
            truth_governance=build_truth_governance(
                TRUTH_GRADE_PROJECTION,
                source="core.network_topology_runtime.NetworkTopologyRuntime",
                recovery_status=(RECOVERY_STATUS_DEGRADED if recovered_at else RECOVERY_STATUS_LIVE),
                revalidation_required=degraded,
                degraded=degraded,
                field_truth_grades={
                    "topology_view": TRUTH_GRADE_PROJECTION,
                    "restored_view": TRUTH_GRADE_RECOVERABLE,
                },
                notes=[
                    "Recovered topology entries remain degraded/recoverable view truth "
                    "until live updates replace them.",
                ],
                extra={
                    "durable_state_path": self._state_path,
                    "recovered_at": recovered_at,
                    "recovered_node_count": recovered_nodes,
                    "recovered_edge_count": recovered_edges,
                },
            ),
        )

    # ── Durable state ─────────────────────────────────────────────────────

    def persist_durable_state(self) -> None:
        with self._rw_lock:
            payload = {
                "contract_version": "network_topology_runtime_durable_v1",
                "persisted_at": time.time(),
                "nodes": [node.to_dict() for node in self._nodes.values()],
                "edges": [edge.to_dict() for edge in self._edges.values()],
            }
        try:
            write_json_atomically(self._state_path, payload)
        except OSError:
            logger.warning("network_topology_runtime durable persist failed: %s", self._state_path)

    def restore_durable_state(self, state: Optional[dict] = None) -> Dict[str, int]:
        """Restore the persisted topology as degraded recoverable truth.

        Restored nodes are forced into ``DEGRADED`` state and tagged
        ``recovered_unrevalidated`` until live updates replace them.
        """
        payload = state if isinstance(state, dict) else load_json_payload(self._state_path)
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
                metadata = dict(item.get("metadata") or {})
                metadata["_truth_governance"] = build_truth_governance(
                    TRUTH_GRADE_RECOVERABLE,
                    source="core.network_topology_runtime.NetworkTopologyRuntime",
                    recovery_status=RECOVERY_STATUS_DEGRADED,
                    revalidation_required=True,
                    degraded=True,
                    field_truth_grades={"topology_view": TRUTH_GRADE_RECOVERABLE},
                    extra={"recovered_at": recovered_wallclock},
                )
                try:
                    kind = TopologyNodeKind(str(item.get("kind") or TopologyNodeKind.UNKNOWN.value))
                except ValueError:
                    kind = TopologyNodeKind.UNKNOWN
                self._nodes[node_id] = TopologyNode(
                    node_id=node_id,
                    kind=kind,
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
                metadata = dict(item.get("metadata") or {})
                metadata["_truth_governance"] = build_truth_governance(
                    TRUTH_GRADE_RECOVERABLE,
                    source="core.network_topology_runtime.NetworkTopologyRuntime",
                    recovery_status=RECOVERY_STATUS_DEGRADED,
                    revalidation_required=True,
                    degraded=True,
                    field_truth_grades={"topology_view": TRUTH_GRADE_RECOVERABLE},
                    extra={"recovered_at": recovered_wallclock},
                )
                try:
                    kind = TopologyEdgeKind(str(item.get("kind") or TopologyEdgeKind.DIRECT.value))
                except ValueError:
                    kind = TopologyEdgeKind.DIRECT
                self._edges[edge_id] = TopologyEdge(
                    edge_id=edge_id,
                    source_node_id=str(item.get("source_node_id") or ""),
                    target_node_id=str(item.get("target_node_id") or ""),
                    kind=kind,
                    state=TopologyConnectionState.DEGRADED,
                    preferred=bool(item.get("preferred")),
                    latency_hint_ms=float(item.get("latency_hint_ms") or 0.0),
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

    # ── Internal ──────────────────────────────────────────────────────────

    def _emit_record(
        self,
        event_kind: str,
        node_id: str,
        *,
        kind: str = TopologyNodeKind.UNKNOWN.value,
        state: str = "",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._log.append(
            TopologyRecord(
                record_id=_next_record_id(),
                event_kind=event_kind,
                node_id=node_id,
                kind=kind,
                state=state,
                details=dict(details or {}),
            )
        )

    # ════════════════════════════════════════════════════════════════════
    # Legacy PR-28 surface: network positions & path assessment
    # ════════════════════════════════════════════════════════════════════

    async def start(self, device_id: str = "") -> None:
        """Start legacy topology discovery (network-position probing)."""
        self._my_device_id = device_id or self._detect_device_id()
        self._running = True
        self._my_position = await self._discover_self()
        self._my_position.device_id = self._my_device_id
        with self._rw_lock:
            self._positions[self._my_device_id] = self._my_position
        self._probe_task = asyncio.create_task(
            self._refresh_loop(),
            name="network_topology_refresh",
        )
        logger.info(
            "NetworkTopologyRuntime started | device=%s lan=%s ts=%s",
            self._my_device_id,
            self._my_position.lan_subnet,
            self._my_position.tailscale_ip or "none",
        )

    async def stop(self) -> None:
        """Stop legacy topology monitoring."""
        self._running = False
        if self._probe_task and not self._probe_task.done():
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
        logger.info("NetworkTopologyRuntime stopped")

    def register_device(self, position: NetworkPosition) -> None:
        """Register or update a peer device's network position."""
        with self._rw_lock:
            existing = self._positions.get(position.device_id)
            if existing:
                if position.lan_ip:
                    existing.lan_ip = position.lan_ip
                if position.tailscale_ip:
                    existing.tailscale_ip = position.tailscale_ip
                if position.public_ip:
                    existing.public_ip = position.public_ip
                if position.capabilities:
                    existing.capabilities = list(set(existing.capabilities + position.capabilities))
                existing.last_seen = time.time()
            else:
                self._positions[position.device_id] = position

    def unregister_device(self, device_id: str) -> None:
        with self._rw_lock:
            self._positions.pop(device_id, None)

    def assess_path(self, source: str, target: str) -> PathAssessment:
        """Assess best network path from source to target device.

        Used by AIPTransport for smart transport selection.
        """
        with self._rw_lock:
            src_pos = self._positions.get(source)
            tgt_pos = self._positions.get(target)

        if not src_pos or not tgt_pos:
            return PathAssessment(
                source=source,
                target=target,
                best_path="unknown",
                recommended_transport="websocket",
                estimated_rtt_ms=999.0,
                reason="Device position not in topology map",
            )

        # Path 1: Same subnet → TCP direct
        if src_pos.lan_subnet and tgt_pos.lan_subnet:
            if src_pos.lan_subnet == tgt_pos.lan_subnet:
                return PathAssessment(
                    source=source,
                    target=target,
                    best_path="same_subnet",
                    recommended_transport="tcp",
                    estimated_rtt_ms=1.0,
                    reason=f"Same LAN subnet {src_pos.lan_subnet}",
                )

        # Path 2: Same Tailscale tailnet → P2P via WireGuard
        if src_pos.tailscale_ip and tgt_pos.tailscale_ip:
            return PathAssessment(
                source=source,
                target=target,
                best_path="same_tailnet",
                recommended_transport="tailscale_p2p",
                estimated_rtt_ms=max(5.0, min(src_pos.rtt_ms, tgt_pos.rtt_ms, 50.0)),
                reason=f"Tailscale P2P: {src_pos.tailscale_ip} -> {tgt_pos.tailscale_ip}",
            )

        # Path 3: P2P capable (public IP + good NAT)
        if tgt_pos.public_ip and tgt_pos.nat_type in ("full_cone", "restricted", "none"):
            if "quic" in tgt_pos.capabilities:
                return PathAssessment(
                    source=source,
                    target=target,
                    best_path="p2p_quic",
                    recommended_transport="quic",
                    estimated_rtt_ms=50.0,
                    reason=f"QUIC P2P to {tgt_pos.public_ip}",
                )

        # Path 4: DERP relay
        if src_pos.tailscale_ip and not tgt_pos.tailscale_ip:
            return PathAssessment(
                source=source,
                target=target,
                best_path="derp_relay",
                recommended_transport="tailscale_p2p",
                estimated_rtt_ms=150.0,
                reason="Target not on tailnet, using DERP relay",
            )

        # Path 5: WebSocket gateway (ultimate fallback)
        return PathAssessment(
            source=source,
            target=target,
            best_path="gateway_ws",
            recommended_transport="websocket",
            estimated_rtt_ms=100.0,
            reason="No P2P path available, fallback to WebSocket gateway",
        )

    def get_topology_summary(self) -> Dict[str, Any]:
        """Return JSON-safe legacy network-position summary."""
        with self._rw_lock:
            return {
                "my_device_id": self._my_device_id,
                "my_position": self._my_position.to_dict(),
                "device_count": len(self._positions),
                "devices": {did: pos.to_dict() for did, pos in self._positions.items()},
            }

    # ── Legacy internal: self discovery ───────────────────────────────────

    async def _discover_self(self) -> NetworkPosition:
        """Discover this device's own network position."""
        pos = NetworkPosition()
        try:
            pos.lan_ip = self._get_lan_ip()
            pos.lan_subnet = self._subnet_from_ip(pos.lan_ip)
        except Exception:
            pass
        try:
            pos.tailscale_ip, pos.tailscale_hostname = await self._get_tailscale_info()
        except Exception:
            pass
        pos.capabilities = self._detect_capabilities()
        return pos

    @staticmethod
    def _detect_device_id() -> str:
        return f"{platform.system().lower()}-{platform.node() or 'unknown'}"

    @staticmethod
    def _get_lan_ip() -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        finally:
            s.close()

    @staticmethod
    def _subnet_from_ip(ip: str, prefix: int = 24) -> str:
        try:
            return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False))
        except Exception:
            return ""

    async def _get_tailscale_info(self) -> Tuple[str, str]:
        import shutil

        if not shutil.which("tailscale"):
            return "", ""
        try:
            result = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            if result.returncode == 0:
                status = json.loads(result.stdout)
                self_info = status.get("Self", {})
                ts_ips = self_info.get("TailscaleIPs", [""])
                return (ts_ips[0] if ts_ips else ""), self_info.get("HostName", "")
        except Exception:
            pass
        return "", ""

    @staticmethod
    def _detect_capabilities() -> List[str]:
        caps = ["websocket", "tcp", "udp"]
        import shutil

        if shutil.which("tailscale"):
            caps.append("tailscale_p2p")
        try:
            import aioquic  # noqa: F401

            caps.append("quic")
        except ImportError:
            pass
        return caps

    async def _refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(_TOPOLOGY_PROBE_INTERVAL)
            except asyncio.CancelledError:
                break
            if not self._running:
                break
            try:
                new_pos = await self._discover_self()
                new_pos.device_id = self._my_device_id
                with self._rw_lock:
                    self._my_position = new_pos
                    self._positions[self._my_device_id] = new_pos
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module-level assimilation / projection helpers
# ---------------------------------------------------------------------------


def assimilate_nats_state(is_connected: bool, host: str = "", port: int = 0) -> TopologyNode:
    """Absorb NATS fabric state into the singleton runtime."""
    return get_network_topology_runtime().absorb_nats_state(is_connected, host, port)


def assimilate_gateway_state(
    gateway_id: str, host: str = "", port: int = 0, is_connected: bool = False
) -> TopologyNode:
    """Absorb gateway substrate state into the singleton runtime."""
    return get_network_topology_runtime().absorb_gateway_state(gateway_id, host, port, is_connected)


def assimilate_device_connectivity(
    device_id: str,
    *,
    preferred_path: str = "",
    effective_routable: bool = False,
    fallback_available: bool = False,
    mesh_overlay_available: bool = False,
    host: str = "",
    port: int = 0,
    metadata: Optional[Dict[str, Any]] = None,
) -> TopologyNode:
    """Absorb a device connectivity report into the singleton runtime."""
    return get_network_topology_runtime().absorb_device_connectivity(
        device_id,
        preferred_path=preferred_path,
        effective_routable=effective_routable,
        fallback_available=fallback_available,
        mesh_overlay_available=mesh_overlay_available,
        host=host,
        port=port,
        metadata=metadata,
    )


def project_transport_path(
    source_id: str,
    target_id: str,
    *,
    transport_strategy: str = "direct",
) -> TransportPathInfo:
    """Project the transport path view between two nodes (read-only)."""
    return get_network_topology_runtime().project_transport_path(
        source_id,
        target_id,
        transport_strategy=transport_strategy,
    )


def assimilate_transport_hierarchy_record(
    record: Any,
    *,
    source_id: str = GROUNDED_RUNTIME_HOST_ID,
    target_id: str = "",
) -> Optional[TopologyEdge]:
    """Absorb a fabric transport strategy record into the singleton runtime."""
    return get_network_topology_runtime().assimilate_transport_hierarchy_record(
        record, source_id=source_id, target_id=target_id
    )


def build_grounded_runtime_topology(*, max_allocation_records: int = 64) -> GroundedRuntimeTopology:
    """Build the operator-facing grounded topology rooted at the V2 host.

    Combines the canonical topology view with task-allocation relations from
    the canonical task runtime (``task_allocated_to_executor``).
    """
    runtime = get_network_topology_runtime()
    snapshot_nodes = runtime.all_nodes()
    snapshot_edges = runtime.all_edges()

    nodes: List[Dict[str, Any]] = [
        {
            "id": GROUNDED_RUNTIME_HOST_ID,
            "kind": TopologyNodeKind.RUNTIME_PROVIDER_NODE.value,
            "state": TopologyConnectionState.CONNECTED.value,
            "is_runtime_host": True,
        }
    ]
    galaxy_children: Dict[str, List[str]] = {}
    for node in snapshot_nodes:
        node_dict = node.to_dict()
        node_dict["id"] = node.node_id
        nodes.append(node_dict)
        galaxy_children.setdefault(_kind_value(node.kind), []).append(node.node_id)

    relations: List[Dict[str, Any]] = [
        {
            "relation_kind": f"topology_edge::{_kind_value(edge.kind)}",
            "source_id": edge.source_node_id,
            "target_id": edge.target_node_id,
            "edge_id": edge.edge_id,
            "state": _kind_value(edge.state),
            "preferred": bool(edge.preferred),
        }
        for edge in snapshot_edges
    ]

    # Task allocation relations from the canonical task runtime (best-effort).
    try:
        from core.canonical_task import get_canonical_task_runtime

        allocation_records = get_canonical_task_runtime().list_allocation_records(limit=max_allocation_records)
        for record in allocation_records:
            executor = str(record.selected_executor or "")
            if not executor or executor == "unknown":
                continue
            relations.append(
                {
                    "relation_kind": "task_allocated_to_executor",
                    "source_id": f"task::{record.task_id}",
                    "target_id": executor,
                    "accepted_allocation": record.accepted_allocation,
                    "execution_location": record.execution_location,
                    "canonical_closed": bool(record.canonical_closed),
                    "fallback_used": bool(record.fallback_used),
                }
            )
    except Exception as exc:
        logger.debug("build_grounded_runtime_topology: allocation relations skipped: %s", exc)

    return GroundedRuntimeTopology(
        runtime_host=GROUNDED_RUNTIME_HOST_ID,
        nodes=nodes,
        relations=relations,
        galaxy_tree={
            "root": GROUNDED_RUNTIME_HOST_ID,
            "children": galaxy_children,
        },
        truth_governance=build_truth_governance(
            TRUTH_GRADE_PROJECTION,
            source="core.network_topology_runtime.build_grounded_runtime_topology",
            field_truth_grades={"grounded_topology": TRUTH_GRADE_PROJECTION},
            notes=[
                "Grounded runtime topology is an outward projection assembled from runtime views.",
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
