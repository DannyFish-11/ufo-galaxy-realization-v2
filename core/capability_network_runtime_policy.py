#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_network_runtime_policy.py
==========================================
PR-509: Capability + Network Runtime Assimilation — Policy Integration Layer.

This module is the **integration bridge** that:

1.  Absorbs representative runtime events (NATS/gateway/connectivity/heartbeat/
    path) into :class:`~core.network_topology_runtime.NetworkTopologyRuntime`.
2.  Absorbs executor/provider/device capability changes into the canonical
    :class:`~core.capability_assimilation.CapabilityAssimilationLayer`.
3.  Exposes **planner/router/policy consumption helpers** so that routing
    decisions read canonical capability + network truth rather than
    bypassing these layers.
4.  Establishes **topology semantics sentinels** that clarify the boundary
    between *device/network topology* (this layer) and *model/provider
    topology* (a separate concern, not redesigned here).

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  RUNTIME EVENTS                                                      │
    │  (NATS connect/disconnect, gateway start/stop, device presence,     │
    │   heartbeat, capability change, path change)                         │
    └──────────────────────────┬───────────────────────────────────────────┘
                               │  absorb_*_event() helpers (this module)
                               ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │  CANONICAL RUNTIME LAYERS  (Layer 7–8)                               │
    │  CapabilityAssimilationLayer  ←→  NetworkTopologyRuntime             │
    └──────────────────────────┬───────────────────────────────────────────┘
                               │  query_routable_executors()
                               │  query_network_path()
                               ▼
    ┌──────────────────────────────────────────────────────────────────────┐
    │  CONSUMERS                                                           │
    │  CommandRouter · Scheduler · AdmissibilityPolicyConvergence         │
    └──────────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Routing decisions MUST read canonical runtime truth.**
    Consumers MUST call :func:`query_routable_executors` and
    :func:`query_network_path` rather than reading raw registries.
    Governed by :data:`CANONICAL_RUNTIME_CONSUMPTION_POLICY`.

2.  **Device/network topology is distinct from model/provider topology.**
    This module operates on device/network/transport topology only.
    Model/provider routing topology is a separate concern and is NOT
    redesigned here.  Governed by :data:`TOPOLOGY_SEMANTICS_DISAMBIGUATION`.

3.  **All runtime event absorption is non-blocking and failure-isolated.**
    Absorption errors must never abort the caller.  Each helper wraps
    absorption in a ``try/except`` and logs a debug message on failure.

4.  **Capability assimilation is canonical for executor/provider/device state.**
    Presence state, health, and capability sets are authoritative only when
    written through the assimilation layer.

Public API
----------
Authority sentinels:
    CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY
    CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_LAYER_POSITION
    CANONICAL_RUNTIME_CONSUMPTION_POLICY
    TOPOLOGY_SEMANTICS_DISAMBIGUATION
    DEVICE_NETWORK_TOPOLOGY_BOUNDARY
    MODEL_PROVIDER_TOPOLOGY_BOUNDARY

Event absorption helpers (NATS / gateway / device):
    absorb_nats_connectivity_event(is_connected, host, port) -> None
    absorb_gateway_connectivity_event(gateway_id, host, port, is_connected) -> None
    absorb_device_presence_event(device_id, *, is_online, preferred_path,
                                  effective_routable, fallback_available,
                                  mesh_overlay_available, host, port) -> None
    absorb_heartbeat_event(node_id, *, health_score, details) -> None
    absorb_capability_change_event(node_id, *, capabilities, participant_kind,
                                    host, port, tags, metadata) -> None
    absorb_path_change_event(source_id, target_id, *, transport_strategy,
                              fallback_used) -> None

Planner/router/policy consumption helpers:
    query_routable_executors(required_capabilities) -> List[RoutableExecutor]
    query_network_path(source_id, target_id) -> NetworkPathResult
    snapshot_canonical_runtime() -> CanonicalRuntimeSnapshot

Dataclasses:
    RoutableExecutor
    NetworkPathResult
    CanonicalRuntimeSnapshot
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityNetworkRuntimePolicy")

__all__ = [
    # Authority sentinels
    "CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY",
    "CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_LAYER_POSITION",
    "CANONICAL_RUNTIME_CONSUMPTION_POLICY",
    "TOPOLOGY_SEMANTICS_DISAMBIGUATION",
    "DEVICE_NETWORK_TOPOLOGY_BOUNDARY",
    "MODEL_PROVIDER_TOPOLOGY_BOUNDARY",
    # Dataclasses
    "RoutableExecutor",
    "NetworkPathResult",
    "CanonicalRuntimeSnapshot",
    # Event absorption helpers
    "absorb_nats_connectivity_event",
    "absorb_gateway_connectivity_event",
    "absorb_device_presence_event",
    "absorb_heartbeat_event",
    "absorb_capability_change_event",
    "absorb_path_change_event",
    # Planner/router/policy consumption helpers
    "query_routable_executors",
    "query_network_path",
    "snapshot_canonical_runtime",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Module authority marker — identifies the PR-509 capability + network
#: runtime assimilation policy integration layer.
CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY: str = (
    "core.capability_network_runtime_policy"
    " — PR-509 capability+network runtime assimilation policy layer"
)

#: Layer position: sits above CapabilityAssimilation (7) and
#: NetworkTopologyRuntime (8), bridging both into a unified policy surface.
CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_LAYER_POSITION: int = 9

#: Governs all routing/planner/policy consumers: they MUST read from the
#: canonical runtime layers via this module's query helpers, not from raw
#: legacy registries or scattered state sources.
CANONICAL_RUNTIME_CONSUMPTION_POLICY: str = (
    "CANONICAL_RUNTIME_CONSUMPTION_REQUIRED"
    " — planner/router/policy MUST consume capability+network truth via "
    "query_routable_executors() and query_network_path(); "
    "direct registry reads are governance violations."
)

#: Topology semantics disambiguation sentinel.
#: Clarifies the two distinct topology domains present in this system.
TOPOLOGY_SEMANTICS_DISAMBIGUATION: str = (
    "TOPOLOGY_SEMANTICS_DISAMBIGUATION_V1"
    " — Two topology domains coexist: "
    "(1) DEVICE/NETWORK topology: physical devices, network paths, "
    "gateway/NATS fabric, transport edges — managed by NetworkTopologyRuntime; "
    "(2) MODEL/PROVIDER topology: LLM model routing, provider selection, "
    "model supply graph — managed separately. "
    "This module operates on domain (1) only."
)

#: Sentinel marking the device/network topology boundary.
#: Any code that consumes or populates device connectivity, gateway state,
#: NATS fabric state, transport paths, or device presence MUST operate in
#: this domain.
DEVICE_NETWORK_TOPOLOGY_BOUNDARY: str = (
    "DEVICE_NETWORK_TOPOLOGY_DOMAIN"
    " — Covers: physical devices, network paths, NATS fabric endpoints, "
    "gateways, relay/mesh/direct transport edges, device presence/heartbeat."
)

#: Sentinel marking the model/provider topology boundary.
#: This domain is NOT redesigned in PR-509.  It covers LLM model routing,
#: provider selection, model capability mapping, and supply-side topology.
MODEL_PROVIDER_TOPOLOGY_BOUNDARY: str = (
    "MODEL_PROVIDER_TOPOLOGY_DOMAIN"
    " — Covers: LLM model routing, provider selection, model supply graph. "
    "NOT redesigned in PR-509. "
    "Consumers of model routing MUST NOT mix this with device/network topology."
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RoutableExecutor:
    """A capability-capable, network-reachable executor selected by the policy layer.

    Attributes
    ----------
    node_id:
        Canonical node identifier.
    participant_kind:
        How this executor participates in the system (from
        :class:`~core.capability_assimilation.NodeParticipantKind`).
    capabilities:
        Capability names declared by this executor.
    presence_state:
        Current presence state (from
        :class:`~core.capability_assimilation.AssimilationPresenceState`).
    network_state:
        Current network topology connection state for this node, or
        ``"unknown"`` if not found in the network topology runtime.
    health_score:
        Last recorded health score [0.0, 1.0].
    host:
        Executor host address.
    port:
        Executor port (0 = unknown).
    """

    node_id: str
    participant_kind: str = "worker"
    capabilities: List[str] = field(default_factory=list)
    presence_state: str = "unknown"
    network_state: str = "unknown"
    health_score: float = 1.0
    host: str = "localhost"
    port: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "participant_kind": self.participant_kind,
            "capabilities": list(self.capabilities),
            "presence_state": self.presence_state,
            "network_state": self.network_state,
            "health_score": self.health_score,
            "host": self.host,
            "port": self.port,
        }


@dataclass
class NetworkPathResult:
    """Result of a canonical network path query.

    Attributes
    ----------
    source_id:
        Source node identifier.
    target_id:
        Target node identifier.
    transport_strategy:
        Active transport strategy (e.g. ``"direct_ws"``, ``"relay"``,
        ``"nats_fabric"``).
    is_reachable:
        Whether a path is currently available.
    fallback_used:
        Whether a fallback path is in use.
    edge_kind:
        The topology edge kind on the active path.
    path_state:
        Connection state of the resolved path.
    latency_hint_ms:
        Optional latency hint in milliseconds (0 = unknown).
    """

    source_id: str
    target_id: str
    transport_strategy: str = ""
    is_reachable: bool = False
    fallback_used: bool = False
    edge_kind: str = "unknown"
    path_state: str = "unknown"
    latency_hint_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "transport_strategy": self.transport_strategy,
            "is_reachable": self.is_reachable,
            "fallback_used": self.fallback_used,
            "edge_kind": self.edge_kind,
            "path_state": self.path_state,
            "latency_hint_ms": self.latency_hint_ms,
        }


@dataclass
class CanonicalRuntimeSnapshot:
    """Unified snapshot of capability + network runtime state for operators/planners.

    Attributes
    ----------
    timestamp:
        Snapshot wall-clock time.
    total_executors:
        Total number of assimilated executors/providers.
    online_executors:
        Number of executors in ONLINE presence state.
    degraded_executors:
        Number of executors in DEGRADED presence state.
    offline_executors:
        Number of executors in OFFLINE presence state.
    total_topology_nodes:
        Total topology nodes in the network topology runtime.
    total_topology_edges:
        Total topology edges in the network topology runtime.
    available_topology_nodes:
        Topology nodes in a reachable/connected/preferred state.
    routable_executors:
        List of :class:`RoutableExecutor` objects (online + reachable).
    topology_domain:
        The topology domain identifier (always DEVICE_NETWORK_TOPOLOGY_DOMAIN).
    """

    timestamp: float = field(default_factory=time.time)
    total_executors: int = 0
    online_executors: int = 0
    degraded_executors: int = 0
    offline_executors: int = 0
    total_topology_nodes: int = 0
    total_topology_edges: int = 0
    available_topology_nodes: int = 0
    routable_executors: List[RoutableExecutor] = field(default_factory=list)
    topology_domain: str = DEVICE_NETWORK_TOPOLOGY_BOUNDARY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_executors": self.total_executors,
            "online_executors": self.online_executors,
            "degraded_executors": self.degraded_executors,
            "offline_executors": self.offline_executors,
            "total_topology_nodes": self.total_topology_nodes,
            "total_topology_edges": self.total_topology_edges,
            "available_topology_nodes": self.available_topology_nodes,
            "routable_executor_count": len(self.routable_executors),
            "routable_executors": [e.to_dict() for e in self.routable_executors],
            "topology_domain": self.topology_domain,
        }


# ---------------------------------------------------------------------------
# Event absorption helpers — NATS / gateway / device / capability
# ---------------------------------------------------------------------------


def absorb_nats_connectivity_event(
    is_connected: bool,
    host: str = "",
    port: int = 0,
    node_id: str = "nats_fabric",
) -> None:
    """Absorb a NATS connectivity change event into the network topology runtime.

    Called when the NATS fabric connects or disconnects.  Creates or updates
    the ``nats_fabric`` topology node to reflect the current connectivity state.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        is_connected: Whether the NATS fabric is currently connected.
        host:         NATS server host address.
        port:         NATS server port.
        node_id:      Topology node identifier (default ``"nats_fabric"``).
    """
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()
        runtime.absorb_nats_state(
            is_connected=is_connected,
            host=host,
            port=port,
            node_id=node_id,
        )
        logger.debug(
            "absorb_nats_connectivity_event: node=%s connected=%s",
            node_id,
            is_connected,
        )
    except Exception as exc:
        logger.debug(
            "absorb_nats_connectivity_event: absorption failed (non-fatal): %s", exc
        )


def absorb_gateway_connectivity_event(
    gateway_id: str,
    host: str = "",
    port: int = 0,
    is_connected: bool = False,
) -> None:
    """Absorb a gateway substrate connectivity change into the network topology runtime.

    Called when a Galaxy Gateway adapter starts or stops.  Creates or updates
    the gateway topology node.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        gateway_id:   Unique gateway identifier.
        host:         Gateway host address.
        port:         Gateway port.
        is_connected: Whether the gateway is currently connected.
    """
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()
        runtime.absorb_gateway_state(
            gateway_id=gateway_id,
            host=host,
            port=port,
            is_connected=is_connected,
        )
        logger.debug(
            "absorb_gateway_connectivity_event: gateway=%s connected=%s",
            gateway_id,
            is_connected,
        )
    except Exception as exc:
        logger.debug(
            "absorb_gateway_connectivity_event: absorption failed (non-fatal): %s", exc
        )


def absorb_device_presence_event(
    device_id: str,
    *,
    is_online: bool = True,
    preferred_path: str = "",
    effective_routable: bool = False,
    fallback_available: bool = False,
    mesh_overlay_available: bool = False,
    host: str = "",
    port: int = 0,
    capabilities: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Absorb a device presence/connectivity change into both canonical runtime layers.

    This helper writes to **both**:
    - :class:`~core.network_topology_runtime.NetworkTopologyRuntime` — device
      connectivity node reflecting transport routability.
    - :class:`~core.capability_assimilation.CapabilityAssimilationLayer` — device
      capability record reflecting online/offline state.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        device_id:             Unique device identifier.
        is_online:             Whether the device is currently online.
        preferred_path:        Preferred transport path string.
        effective_routable:    Whether the device is currently routable.
        fallback_available:    Whether a relay fallback path is available.
        mesh_overlay_available: Whether mesh overlay is available.
        host:                  Device host address.
        port:                  Device port (0 = unknown).
        capabilities:          Capability names to assimilate/update.
        tags:                  Classification labels.
        metadata:              Arbitrary metadata.
    """
    # 1. Absorb into network topology runtime
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()
        runtime.absorb_device_connectivity(
            device_id=device_id,
            preferred_path=preferred_path,
            effective_routable=effective_routable,
            fallback_available=fallback_available,
            mesh_overlay_available=mesh_overlay_available,
            host=host,
            port=port,
        )
    except Exception as exc:
        logger.debug(
            "absorb_device_presence_event: topology absorption failed (non-fatal): %s",
            exc,
        )

    # 2. Absorb into capability assimilation layer
    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            NodeParticipantKind,
        )
        layer = get_capability_assimilation_layer()
        existing = layer.get_record(device_id)
        if existing is not None:
            if is_online:
                layer.heartbeat(device_id)
            else:
                layer.mark_offline(device_id, reason="device_presence_event_offline")
        else:
            layer.assimilate(
                device_id,
                capabilities=list(capabilities or []),
                participant_kind=NodeParticipantKind.DEVICE,
                host=host,
                port=port,
                tags=tags,
                metadata=metadata,
            )
    except Exception as exc:
        logger.debug(
            "absorb_device_presence_event: capability absorption failed (non-fatal): %s",
            exc,
        )


def absorb_heartbeat_event(
    node_id: str,
    *,
    health_score: float = 1.0,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Absorb a heartbeat event into the capability assimilation layer.

    Called when a node/worker/executor sends a heartbeat signal.
    Updates :class:`~core.capability_assimilation.FabricPresence` for the node
    and transitions degraded/offline nodes back to ONLINE if health_score >= 0.5.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        node_id:      Node identifier.
        health_score: Health score in [0.0, 1.0].  Below 0.5 sets DEGRADED.
        details:      Optional extra details (load, memory, etc.).
    """
    try:
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        result = layer.heartbeat(node_id, health_score=health_score, details=details)
        if not result:
            logger.debug(
                "absorb_heartbeat_event: node_id=%s not registered; heartbeat ignored",
                node_id,
            )
    except Exception as exc:
        logger.debug(
            "absorb_heartbeat_event: absorption failed (non-fatal): %s", exc
        )


def absorb_capability_change_event(
    node_id: str,
    *,
    capabilities: Optional[List[str]] = None,
    participant_kind: Optional[str] = None,
    host: str = "localhost",
    port: int = 0,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Absorb an executor/provider capability change into the capability assimilation layer.

    Called when a node changes its declared capabilities, comes online for the
    first time, or updates its execution profile.  Delegates to
    :meth:`~core.capability_assimilation.CapabilityAssimilationLayer.assimilate`.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        node_id:          Node identifier.
        capabilities:     Updated capability names.
        participant_kind: Participant kind string (default ``"worker"``).
        host:             Host address.
        port:             Port (0 = unknown).
        tags:             Classification labels.
        metadata:         Arbitrary metadata.
    """
    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            NodeParticipantKind,
        )
        kind_str = participant_kind or "worker"
        try:
            kind = NodeParticipantKind(kind_str)
        except ValueError:
            kind = NodeParticipantKind.WORKER

        layer = get_capability_assimilation_layer()
        layer.assimilate(
            node_id,
            capabilities=capabilities,
            participant_kind=kind,
            host=host,
            port=port,
            tags=tags,
            metadata=metadata,
        )
        logger.debug(
            "absorb_capability_change_event: node=%s capabilities=%s",
            node_id,
            capabilities,
        )
    except Exception as exc:
        logger.debug(
            "absorb_capability_change_event: absorption failed (non-fatal): %s", exc
        )


def absorb_path_change_event(
    source_id: str,
    target_id: str,
    *,
    transport_strategy: str = "",
    fallback_used: bool = False,
) -> None:
    """Absorb a transport path change event into the network topology runtime.

    Called when the active transport path between two nodes changes (e.g.
    primary→fallback, relay→direct).  Registers or updates a
    :class:`~core.network_topology_runtime.TopologyEdge` in the topology
    runtime so that planner/router/policy code can query canonical path state.

    All errors are caught and logged; the caller is never interrupted.

    Args:
        source_id:          Source node identifier.
        target_id:          Target node identifier.
        transport_strategy: New transport strategy string.
        fallback_used:      Whether the fallback path is now active.
    """
    if not source_id or not target_id:
        return
    try:
        from core.network_topology_runtime import (
            get_network_topology_runtime,
            TopologyEdge,
            TopologyEdgeKind,
            TopologyConnectionState,
        )
        runtime = get_network_topology_runtime()

        _STRATEGY_TO_KIND = {
            "direct_ws": TopologyEdgeKind.DIRECT,
            "relay": TopologyEdgeKind.RELAY,
            "mesh": TopologyEdgeKind.MESH,
            "nats_fabric": TopologyEdgeKind.FABRIC,
            "gateway": TopologyEdgeKind.GATEWAY,
        }
        edge_kind = _STRATEGY_TO_KIND.get(transport_strategy, TopologyEdgeKind.DIRECT)
        state = (
            TopologyConnectionState.FALLBACK
            if fallback_used
            else TopologyConnectionState.PREFERRED
        )
        edge = TopologyEdge(
            edge_id=f"{source_id}::{target_id}::{transport_strategy}",
            source_node_id=source_id,
            target_node_id=target_id,
            kind=edge_kind,
            state=state,
            preferred=not fallback_used,
            metadata={
                "transport_strategy": transport_strategy,
                "fallback_used": fallback_used,
            },
        )
        runtime.register_edge(edge)
        logger.debug(
            "absorb_path_change_event: %s→%s strategy=%s fallback=%s",
            source_id,
            target_id,
            transport_strategy,
            fallback_used,
        )
    except Exception as exc:
        logger.debug(
            "absorb_path_change_event: absorption failed (non-fatal): %s", exc
        )


# ---------------------------------------------------------------------------
# Planner/router/policy consumption helpers
# ---------------------------------------------------------------------------


def query_routable_executors(
    required_capabilities: Optional[List[str]] = None,
) -> List[RoutableExecutor]:
    """Query the canonical runtime for executors that are online and reachable.

    Reads **only** from canonical runtime layers:
    - :class:`~core.capability_assimilation.CapabilityAssimilationLayer`
      for online executor presence and capabilities.
    - :class:`~core.network_topology_runtime.NetworkTopologyRuntime`
      for per-node network reachability state.

    This is the authoritative API for planner/router/policy code.  Callers
    MUST NOT read raw node registries to perform routing decisions.
    See :data:`CANONICAL_RUNTIME_CONSUMPTION_POLICY`.

    Args:
        required_capabilities: Optional list of capability names that a
            candidate executor must expose.  If empty or ``None``, all online
            executors are returned.

    Returns:
        List of :class:`RoutableExecutor` objects, ordered by health_score
        (descending).  May be empty if no online, reachable executor is found.
    """
    results: List[RoutableExecutor] = []
    required = set(required_capabilities or [])

    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
        layer = get_capability_assimilation_layer()
        online_records = layer.list_online_records()
    except Exception as exc:
        logger.debug("query_routable_executors: capability layer unavailable: %s", exc)
        return results

    # Resolve per-node topology state
    topology_states: Dict[str, str] = {}
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        topology_runtime = get_network_topology_runtime()
        topo_snap = topology_runtime.snapshot()
        for node in topo_snap.nodes:
            topology_states[node.node_id] = node.state.value if hasattr(node.state, "value") else str(node.state)
    except Exception as exc:
        logger.debug("query_routable_executors: topology runtime unavailable: %s", exc)

    for record in online_records:
        caps = set(record.capability_descriptor.capabilities)
        if required and not required.issubset(caps):
            continue

        net_state = topology_states.get(record.node_id, "unknown")

        exec_profile = record.execution_profile
        health = record.fabric_presence.last_heartbeat_at  # use as proxy if needed
        # Derive health score: use presence_state to set a score
        pstate = record.fabric_presence.presence_state
        if pstate == AssimilationPresenceState.DEGRADED:
            h_score = 0.4
        elif pstate == AssimilationPresenceState.ONLINE:
            h_score = 1.0
        else:
            h_score = 0.0

        results.append(
            RoutableExecutor(
                node_id=record.node_id,
                participant_kind=exec_profile.participant_kind.value
                if hasattr(exec_profile.participant_kind, "value")
                else str(exec_profile.participant_kind),
                capabilities=list(caps),
                presence_state=pstate.value if hasattr(pstate, "value") else str(pstate),
                network_state=net_state,
                health_score=h_score,
                host=record.fabric_presence.host,
                port=record.fabric_presence.port,
            )
        )

    results.sort(key=lambda e: e.health_score, reverse=True)
    return results


def query_network_path(
    source_id: str,
    target_id: str,
) -> NetworkPathResult:
    """Query the canonical network topology runtime for the best path between two nodes.

    Reads **only** from :class:`~core.network_topology_runtime.NetworkTopologyRuntime`.
    Callers MUST NOT compute path reachability from raw transport state.
    See :data:`CANONICAL_RUNTIME_CONSUMPTION_POLICY`.

    Args:
        source_id: Source node identifier.
        target_id: Target node identifier.

    Returns:
        A :class:`NetworkPathResult` reflecting the current canonical path state.
        ``is_reachable`` will be ``False`` if no path can be determined.
    """
    result = NetworkPathResult(source_id=source_id, target_id=target_id)

    try:
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()

        # Look for an existing edge between source and target
        with runtime._rw_lock:
            matching_edges = [
                e for e in runtime._edges.values()
                if e.source_node_id == source_id and e.target_node_id == target_id
            ]

        if matching_edges:
            # Pick the best edge (prefer connected/preferred/reachable states)
            edge = matching_edges[0]
            state_val = edge.state.value if hasattr(edge.state, "value") else str(edge.state)
            kind_val = edge.kind.value if hasattr(edge.kind, "value") else str(edge.kind)
            reachable = state_val not in ("unavailable", "latent")
            result.transport_strategy = edge.metadata.get("transport_strategy", kind_val)
            result.fallback_used = bool(edge.metadata.get("fallback_used", False))
            result.edge_kind = kind_val
            result.path_state = state_val
            result.is_reachable = reachable
        else:
            # No edge registered; check if target node exists and is reachable
            with runtime._rw_lock:
                target_node = runtime._nodes.get(target_id)
            if target_node is not None:
                state_val = target_node.state.value if hasattr(target_node.state, "value") else str(target_node.state)
                reachable = state_val in ("reachable", "connected", "preferred")
                result.path_state = state_val
                result.is_reachable = reachable
    except Exception as exc:
        logger.debug("query_network_path: topology runtime unavailable: %s", exc)

    return result


def snapshot_canonical_runtime() -> CanonicalRuntimeSnapshot:
    """Return a unified snapshot of the canonical capability + network runtime state.

    Reads from both :class:`~core.capability_assimilation.CapabilityAssimilationLayer`
    and :class:`~core.network_topology_runtime.NetworkTopologyRuntime`.  Returns
    a :class:`CanonicalRuntimeSnapshot` that consumers (planner, operator console,
    status board) can use without reading internal runtime structures directly.

    Returns:
        A :class:`CanonicalRuntimeSnapshot` with counts and routable executor list.
    """
    snap = CanonicalRuntimeSnapshot()

    # Capability assimilation counts
    try:
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
        layer = get_capability_assimilation_layer()
        layer_snap = layer.snapshot()
        snap.total_executors = layer_snap.get("total_nodes", 0)
        by_presence = layer_snap.get("by_presence_state", {})
        snap.online_executors = by_presence.get("online", 0)
        snap.degraded_executors = by_presence.get("degraded", 0)
        snap.offline_executors = by_presence.get("offline", 0)
    except Exception as exc:
        logger.debug("snapshot_canonical_runtime: capability layer unavailable: %s", exc)

    # Network topology runtime counts
    try:
        from core.network_topology_runtime import get_network_topology_runtime
        topology_runtime = get_network_topology_runtime()
        topo_snap = topology_runtime.snapshot()
        snap.total_topology_nodes = topo_snap.total_nodes
        snap.total_topology_edges = topo_snap.total_edges
        unavailable = topo_snap.nodes_by_state.get("unavailable", 0)
        latent = topo_snap.nodes_by_state.get("latent", 0)
        snap.available_topology_nodes = snap.total_topology_nodes - unavailable - latent
    except Exception as exc:
        logger.debug("snapshot_canonical_runtime: topology runtime unavailable: %s", exc)

    # Routable executors
    snap.routable_executors = query_routable_executors()

    return snap
