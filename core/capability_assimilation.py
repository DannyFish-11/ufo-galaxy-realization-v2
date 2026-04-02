#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_assimilation.py
================================
PR-7: Capability & Node Assimilation — Unified Capability Assimilation Layer.

Establishes the canonical **Capability Assimilation Layer** that absorbs every
node, worker, executor, and specialist into a unified capability-provider /
execution-participant model without removing any existing node or orchestrator.

Architecture role
-----------------
Nodes are **not** system-execution authorities.  They are:

  * **capability providers** — they declare what they can do.
  * **execution participants** — they execute tasks assigned by the canonical
    execution spine (``OpenClawd → CommandRouter → TaskGraphRuntime``).
  * **fabric participants** — they maintain a presence / heartbeat in the
    network graph runtime.

This layer sits **between** the raw node registries and the three canonical
system graphs:

::

    ┌────────────────────────────────────────────────────────────────────┐
    │  Raw node / worker / executor registries                          │
    │  (NodeFabricRegistry, node_registry, SmartOrchestrator.nodes, …) │
    └──────────────────────────────┬─────────────────────────────────────┘
                                   │  assimilate()
                                   ▼
    ┌────────────────────────────────────────────────────────────────────┐
    │  CAPABILITY ASSIMILATION LAYER  (this module)                     │
    │  • CapabilityDescriptor   — what the node can do                  │
    │  • ExecutionProfile       — how the node executes tasks           │
    │  • FabricPresence         — heartbeat / reachability / status     │
    │  • AssimilationRecord     — canonical unified view per node        │
    └──────┬─────────────────────┬──────────────────────┬───────────────┘
           │                     │                       │
           ▼                     ▼                       ▼
    ┌──────────────┐  ┌──────────────────────┐  ┌───────────────────────┐
    │ capability   │  │  task graph runtime  │  │  network graph runtime│
    │ graph        │  │  (GraphNode as       │  │  (NetworkNode as      │
    │ (NodeFabric  │  │   executor/worker/   │  │   fabric participant  │
    │  Registry)   │  │   participant)       │  │   / route endpoint)   │
    └──────────────┘  └──────────────────────┘  └───────────────────────┘

Governance invariants
---------------------
1.  **Nodes are capability providers, NOT system authorities.**
    No assimilated node may form a parallel execution spine.
2.  **Node-level orchestrators are adapter/facade/local-coordinator only.**
    They MUST NOT override canonical execution authority.
    Governed by ``NODE_ORCHESTRATOR_ASSIMILATION_POLICY``.
3.  **All node output is absorbed into canonical graphs before consumption.**
    Consumers (scheduler, command routing, policy) MUST read from the
    assimilation layer, not from raw node registries.
4.  **Heartbeat / presence changes are observable.**
    Every registration, heartbeat, offline, and rejoin event is recorded in
    a 256-entry ring buffer.

Public API
----------
Authority sentinels:
    CAPABILITY_ASSIMILATION_AUTHORITY
    CAPABILITY_ASSIMILATION_LAYER_POSITION
    NODE_ORCHESTRATOR_ASSIMILATION_POLICY
    ASSIMILATION_CONTRACT_VERSION

Enumerations:
    NodeParticipantKind
    AssimilationPresenceState

Dataclasses:
    CapabilityDescriptor
    ExecutionProfile
    FabricPresence
    AssimilationRecord
    AssimilationEvent

Class:
    CapabilityAssimilationLayer

Helpers:
    assimilate_node(node_info_or_dict) -> AssimilationRecord
    get_capability_assimilation_layer() -> CapabilityAssimilationLayer
    reset_capability_assimilation_layer() -> None  # for testing
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityAssimilation")

__all__ = [
    # Authority sentinels
    "CAPABILITY_ASSIMILATION_AUTHORITY",
    "CAPABILITY_ASSIMILATION_LAYER_POSITION",
    "NODE_ORCHESTRATOR_ASSIMILATION_POLICY",
    "ASSIMILATION_CONTRACT_VERSION",
    "CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED",
    # Enumerations
    "NodeParticipantKind",
    "AssimilationPresenceState",
    # Dataclasses
    "CapabilityDescriptor",
    "ExecutionProfile",
    "FabricPresence",
    "AssimilationRecord",
    "AssimilationEvent",
    # Class
    "CapabilityAssimilationLayer",
    # Helpers
    "assimilate_node",
    "assimilate_device",
    "assimilate_mcp_provider",
    "assimilate_skill",
    "get_capability_assimilation_layer",
    "reset_capability_assimilation_layer",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Module authority marker — import this sentinel to assert that the canonical
#: capability assimilation layer (PR-7, extended in PR-D) is present and active.
CAPABILITY_ASSIMILATION_AUTHORITY: str = (
    "core.capability_assimilation"
    " — canonical capability & node assimilation layer (PR-7/PR-D)"
)

#: Layer position in the canonical control-plane stack.
#: Layer 7 sits above the task graph runtime (Layer 6) and below any
#: operator / UI surface.
CAPABILITY_ASSIMILATION_LAYER_POSITION: int = 7

#: Governs node-level orchestrators: they are adapter/facade/local-coordinator
#: **only** and MUST NOT redefine the system execution spine.
NODE_ORCHESTRATOR_ASSIMILATION_POLICY: str = (
    "NODE_ORCHESTRATOR_IS_ADAPTER_FACADE_ONLY"
    " — no parallel execution authority permitted"
)

#: Contract version for :class:`AssimilationRecord` serialisation.
ASSIMILATION_CONTRACT_VERSION: str = "v1"

# PR-509: Capability + Network Runtime Assimilation integration sentinel.
# Affirms that this layer is now wired into the capability_network_runtime_policy
# bridge so that runtime events (heartbeat, capability change, device presence)
# populate this layer via absorb_heartbeat_event() /
# absorb_capability_change_event() / absorb_device_presence_event().
CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED: str = (
    "CAPABILITY_ASSIMILATION::CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED_V1"
)

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NodeParticipantKind(str, Enum):
    """How a node participates in the canonical system.

    Every registered node maps to exactly one of these kinds after
    assimilation.  The kind governs which graphs the node is projected into
    and whether its capabilities are surfaced to the execution spine.
    """

    CAPABILITY_PROVIDER = "capability_provider"
    """Node exposes callable capabilities to OpenClawd / CommandRouter."""

    WORKER = "worker"
    """Node executes tasks dispatched by the task graph runtime."""

    SPECIALIST = "specialist"
    """Domain-specialist node (e.g. OCR, vision) — accessed via service
    adapters, not direct capability surfacing."""

    FABRIC_PARTICIPANT = "fabric_participant"
    """Node participates in the network fabric but does not expose
    task-execution capabilities directly."""

    LEGACY_FACADE = "legacy_facade"
    """Former orchestrator node demoted to adapter/facade/local-coordinator.
    Must NOT be treated as a system-execution authority."""

    DEVICE = "device"
    """Physical or virtual device provider (Android, desktop, IoT, etc.).
    Registered via device_registry / DeviceCommunication and absorbed into
    the capability graph so the planner can reason about device capabilities."""

    MCP_PROVIDER = "mcp_provider"
    """MCP-protocol tool/skill provider absorbed from mcp_bridge / mcp_loader.
    Surfaces MCP tools as first-class capabilities to the capability selection
    plane."""

    SKILL = "skill"
    """Skill-based capability provider registered via skill_loader / skill_registry.
    Skills are projected into the capability graph so that routing decisions can
    treat them the same as node-based capabilities."""

    UNKNOWN = "unknown"
    """Kind has not been determined; treated as fabric_participant only."""


class AssimilationPresenceState(str, Enum):
    """Node presence state as tracked by the assimilation layer."""

    ONLINE = "online"
    DEGRADED = "degraded"
    OFFLINE = "offline"
    STALE = "stale"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CapabilityDescriptor:
    """Canonical descriptor for capabilities declared by an assimilated node.

    Attributes
    ----------
    node_id:
        Owning node identifier.
    capabilities:
        List of capability name strings declared by the node.
    tags:
        Free-form classification labels (e.g. ``["llm", "inference"]``).
    constraints:
        Key-value constraints on when these capabilities apply (e.g.
        ``{"min_vram_gb": 8}``).
    scope:
        Logical scope (e.g. ``"local"``, ``"cluster"``, ``"global"``).
    contract_version:
        Descriptor schema version.
    """

    node_id: str
    capabilities: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)
    scope: str = "local"
    contract_version: str = ASSIMILATION_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "capabilities": list(self.capabilities),
            "tags": list(self.tags),
            "constraints": dict(self.constraints),
            "scope": self.scope,
            "contract_version": self.contract_version,
        }


@dataclass
class ExecutionProfile:
    """Execution profile for a node as a task executor / worker.

    Attributes
    ----------
    node_id:
        Owning node identifier.
    participant_kind:
        How the node participates in task execution.
    max_concurrent_tasks:
        Maximum number of concurrent tasks the node can handle (0 = unknown).
    priority:
        Scheduling priority hint (``"low"``, ``"normal"``, ``"high"``,
        ``"critical"``).
    supported_task_types:
        Task type names this node can handle (empty = unrestricted).
    metadata:
        Arbitrary profile metadata.
    """

    node_id: str
    participant_kind: NodeParticipantKind = NodeParticipantKind.WORKER
    max_concurrent_tasks: int = 0
    priority: str = "normal"
    supported_task_types: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "participant_kind": (
                self.participant_kind.value
                if isinstance(self.participant_kind, NodeParticipantKind)
                else self.participant_kind
            ),
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "priority": self.priority,
            "supported_task_types": list(self.supported_task_types),
            "metadata": dict(self.metadata),
        }


@dataclass
class FabricPresence:
    """Heartbeat / fabric-presence record for an assimilated node.

    Attributes
    ----------
    node_id:
        Owning node identifier.
    presence_state:
        Current presence state.
    host:
        Node host address (for transport reachability).
    port:
        Node port (0 = unknown / not applicable).
    transport_hints:
        Optional transport-layer route hints (e.g. ``{"protocol": "http",
        "path": "/api"}``) for the network graph runtime.
    last_heartbeat_at:
        Monotonic timestamp of the last heartbeat (``time.monotonic()``).
    heartbeat_count:
        Number of heartbeats received since assimilation.
    registered_at:
        Monotonic timestamp when the node was first assimilated.
    """

    node_id: str
    presence_state: AssimilationPresenceState = AssimilationPresenceState.UNKNOWN
    host: str = "localhost"
    port: int = 0
    transport_hints: Dict[str, Any] = field(default_factory=dict)
    last_heartbeat_at: float = field(default_factory=time.monotonic)
    heartbeat_count: int = 0
    registered_at: float = field(default_factory=time.monotonic)

    def heartbeat_age_secs(self) -> float:
        """Seconds since the last heartbeat."""
        return time.monotonic() - self.last_heartbeat_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "presence_state": (
                self.presence_state.value
                if isinstance(self.presence_state, AssimilationPresenceState)
                else self.presence_state
            ),
            "host": self.host,
            "port": self.port,
            "transport_hints": dict(self.transport_hints),
            "last_heartbeat_at": self.last_heartbeat_at,
            "heartbeat_age_secs": round(self.heartbeat_age_secs(), 2),
            "heartbeat_count": self.heartbeat_count,
            "registered_at": self.registered_at,
        }


@dataclass
class AssimilationRecord:
    """Canonical unified view of a node after assimilation.

    This is the single source of truth that consumers (scheduler, command
    routing, policy, task graph) should read instead of raw node registries.

    Attributes
    ----------
    node_id:
        Unique node identifier.
    capability_descriptor:
        Canonical capability declaration.
    execution_profile:
        Execution participation profile.
    fabric_presence:
        Heartbeat / reachability presence record.
    projected_to_task_graph:
        Whether the node has been projected into the task graph runtime.
    projected_to_network_graph:
        Whether the node has been projected into the network graph runtime.
    assimilation_notes:
        Human-readable notes about the assimilation (warnings, skips, etc.).
    """

    node_id: str
    capability_descriptor: Optional[CapabilityDescriptor] = None
    execution_profile: Optional[ExecutionProfile] = None
    fabric_presence: Optional[FabricPresence] = None
    projected_to_task_graph: bool = False
    projected_to_network_graph: bool = False
    assimilation_notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Ensure nested sub-records always carry the parent node_id."""
        if self.capability_descriptor is None:
            self.capability_descriptor = CapabilityDescriptor(node_id=self.node_id)
        elif self.capability_descriptor.node_id == "":
            self.capability_descriptor.node_id = self.node_id

        if self.execution_profile is None:
            self.execution_profile = ExecutionProfile(node_id=self.node_id)
        elif self.execution_profile.node_id == "":
            self.execution_profile.node_id = self.node_id

        if self.fabric_presence is None:
            self.fabric_presence = FabricPresence(node_id=self.node_id)
        elif self.fabric_presence.node_id == "":
            self.fabric_presence.node_id = self.node_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "capability_descriptor": self.capability_descriptor.to_dict(),
            "execution_profile": self.execution_profile.to_dict(),
            "fabric_presence": self.fabric_presence.to_dict(),
            "projected_to_task_graph": self.projected_to_task_graph,
            "projected_to_network_graph": self.projected_to_network_graph,
            "assimilation_notes": list(self.assimilation_notes),
            "contract_version": ASSIMILATION_CONTRACT_VERSION,
        }


@dataclass
class AssimilationEvent:
    """Observability event emitted by the assimilation layer.

    Stored in the 256-entry ring buffer accessible via
    :meth:`CapabilityAssimilationLayer.get_event_log`.

    Attributes
    ----------
    event_kind:
        One of ``"registered"``, ``"heartbeat"``, ``"offline"``,
        ``"rejoin"``, ``"capability_changed"``, ``"error"``.
    node_id:
        The affected node.
    timestamp:
        Wall-clock time (``time.time()``).
    details:
        Arbitrary details dict.
    """

    event_kind: str
    node_id: str
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_kind": self.event_kind,
            "node_id": self.node_id,
            "timestamp": self.timestamp,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# CapabilityAssimilationLayer
# ---------------------------------------------------------------------------

_RING_BUFFER_SIZE: int = 256


class CapabilityAssimilationLayer:
    """Unified Capability Assimilation Layer (process-level singleton).

    Responsibilities
    ----------------
    * Absorb NodeInfo-compatible objects from any node registry and produce
      canonical :class:`AssimilationRecord` objects.
    * Project assimilated nodes into:
        1. the **capability graph** (via :mod:`core.nodes.node_fabric_registry`
           — syncing capability descriptors).
        2. the **task graph runtime** (via :mod:`core.task_graph_runtime`
           — registering execution-participant nodes).
        3. the **network graph runtime** (via :mod:`core.network_graph_runtime`
           — registering fabric-presence nodes).
    * Track node heartbeats and presence state, emitting observable events.
    * Enforce ``NODE_ORCHESTRATOR_ASSIMILATION_POLICY``: nodes assimilated as
      ``LEGACY_FACADE`` are explicitly excluded from capability surfacing and
      task-graph authority.

    All external registry projections are attempted defensively (failures are
    recorded as notes/events, not exceptions).

    Thread safety
    -------------
    All mutations are protected by a :class:`threading.Lock`.  The layer is
    designed for concurrent heartbeat / registration from multiple threads.
    """

    _instance: Optional["CapabilityAssimilationLayer"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CapabilityAssimilationLayer":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._init_state()
                cls._instance = instance
        return cls._instance

    def _init_state(self) -> None:
        self._records: Dict[str, AssimilationRecord] = {}
        self._event_log: Deque[AssimilationEvent] = deque(maxlen=_RING_BUFFER_SIZE)
        self._rw_lock: threading.Lock = threading.Lock()

    # ── Core assimilation ─────────────────────────────────────────────────

    def assimilate(
        self,
        node_id: str,
        *,
        capabilities: Optional[List[str]] = None,
        participant_kind: NodeParticipantKind = NodeParticipantKind.WORKER,
        host: str = "localhost",
        port: int = 0,
        tags: Optional[List[str]] = None,
        constraints: Optional[Dict[str, Any]] = None,
        scope: str = "local",
        max_concurrent_tasks: int = 0,
        priority: str = "normal",
        supported_task_types: Optional[List[str]] = None,
        transport_hints: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AssimilationRecord:
        """Assimilate a node and project it into the canonical system graphs.

        Creates or updates the :class:`AssimilationRecord` for *node_id*.
        If the node was previously OFFLINE it is treated as a rejoin.

        Args:
            node_id:            Unique node identifier (must be non-empty).
            capabilities:       Capability names declared by the node.
            participant_kind:   How the node participates in the system.
            host:               Node host address.
            port:               Node port (0 = unknown).
            tags:               Classification labels.
            constraints:        Capability constraints.
            scope:              Capability scope.
            max_concurrent_tasks: Max concurrent task slots (0 = unknown).
            priority:           Scheduling priority hint.
            supported_task_types: Task types this node handles.
            transport_hints:    Route hints for the network graph.
            metadata:           Arbitrary metadata.

        Returns:
            The canonical :class:`AssimilationRecord` for the node.

        Raises:
            ValueError: If *node_id* is empty.
        """
        if not node_id:
            raise ValueError("node_id must be a non-empty string")

        caps = list(capabilities or [])
        tags_ = list(tags or [])
        constr = dict(constraints or {})
        tt = list(supported_task_types or [])
        hints = dict(transport_hints or {})
        meta = dict(metadata or {})

        with self._rw_lock:
            existing = self._records.get(node_id)
            is_rejoin = (
                existing is not None
                and existing.fabric_presence.presence_state
                == AssimilationPresenceState.OFFLINE
            )

            cap_desc = CapabilityDescriptor(
                node_id=node_id,
                capabilities=caps,
                tags=tags_,
                constraints=constr,
                scope=scope,
            )
            exec_profile = ExecutionProfile(
                node_id=node_id,
                participant_kind=participant_kind,
                max_concurrent_tasks=max_concurrent_tasks,
                priority=priority,
                supported_task_types=tt,
                metadata=meta,
            )
            presence_state = AssimilationPresenceState.ONLINE
            fabric = FabricPresence(
                node_id=node_id,
                presence_state=presence_state,
                host=host,
                port=port,
                transport_hints=hints,
                heartbeat_count=1 if not existing else existing.fabric_presence.heartbeat_count + 1,
                registered_at=(
                    existing.fabric_presence.registered_at
                    if existing
                    else time.monotonic()
                ),
            )

            notes: List[str] = []

            # ── Project to task graph runtime (defensive) ────────────────
            projected_task = False
            if participant_kind not in (
                NodeParticipantKind.LEGACY_FACADE,
                NodeParticipantKind.FABRIC_PARTICIPANT,
            ):
                projected_task = self._project_to_task_graph(
                    node_id, exec_profile, notes
                )

            # ── Project to network graph runtime (defensive) ─────────────
            projected_network = self._project_to_network_graph(
                node_id, fabric, cap_desc, notes
            )

            record = AssimilationRecord(
                node_id=node_id,
                capability_descriptor=cap_desc,
                execution_profile=exec_profile,
                fabric_presence=fabric,
                projected_to_task_graph=projected_task,
                projected_to_network_graph=projected_network,
                assimilation_notes=notes,
            )
            self._records[node_id] = record

        event_kind = "rejoin" if is_rejoin else "registered"
        self._emit_event(
            event_kind,
            node_id,
            {
                "capabilities": caps,
                "participant_kind": participant_kind.value
                if isinstance(participant_kind, NodeParticipantKind)
                else participant_kind,
                "host": host,
                "port": port,
            },
        )
        logger.info(
            "Assimilated node %s as %s (%s capabilities)",
            node_id,
            participant_kind.value
            if isinstance(participant_kind, NodeParticipantKind)
            else participant_kind,
            len(caps),
            extra={
                "event": event_kind,
                "node_id": node_id,
                "capabilities": caps,
            },
        )
        return record

    def assimilate_from_node_info(self, node_info: Any) -> AssimilationRecord:
        """Assimilate a :class:`~core.nodes.node_fabric_registry.NodeInfo`-compatible object.

        Reads the following attributes from *node_info* (all optional with
        sensible defaults so that any NodeInfo-like dict or object works):

        - ``node_id`` (str)
        - ``capabilities`` (list of objects with ``.name`` attribute, OR list
          of str)
        - ``role`` (NodeRole or str)
        - ``architectural_class`` (NodeArchitecturalClass or str)
        - ``host`` (str)
        - ``port`` (int)
        - ``metadata`` (dict)
        - ``dependencies`` (list of str)

        Args:
            node_info: A NodeInfo-compatible object or dict.

        Returns:
            The canonical :class:`AssimilationRecord`.
        """
        if isinstance(node_info, dict):
            node_id = node_info.get("node_id", "")
            caps_raw = node_info.get("capabilities", [])
            host = node_info.get("host", "localhost")
            port = node_info.get("port", 0)
            role_str = str(node_info.get("role", "worker"))
            arch_str = str(node_info.get("architectural_class", "capability_node"))
            meta = dict(node_info.get("metadata", {}))
        else:
            node_id = getattr(node_info, "node_id", "")
            caps_raw = getattr(node_info, "capabilities", [])
            host = getattr(node_info, "host", "localhost")
            port = getattr(node_info, "port", 0)
            role_str = str(getattr(getattr(node_info, "role", None), "value", "worker"))
            arch_str = str(
                getattr(
                    getattr(node_info, "architectural_class", None), "value", "capability_node"
                )
            )
            meta = dict(getattr(node_info, "metadata", {}) or {})

        # Normalise capability names from either str or objects with .name
        caps: List[str] = []
        for c in caps_raw:
            if isinstance(c, str):
                caps.append(c)
            else:
                name = getattr(c, "name", None)
                if name:
                    caps.append(str(name))

        # Map architectural class → NodeParticipantKind
        participant_kind = _arch_class_to_participant_kind(arch_str)

        return self.assimilate(
            node_id=node_id,
            capabilities=caps,
            participant_kind=participant_kind,
            host=host,
            port=port,
            tags=[role_str],
            metadata=meta,
        )

    # ── Heartbeat / presence ──────────────────────────────────────────────

    def heartbeat(
        self,
        node_id: str,
        *,
        health_score: float = 1.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Record a heartbeat for an assimilated node.

        Updates the node's :class:`FabricPresence` and emits a
        ``"heartbeat"`` event.

        Args:
            node_id:     Node identifier.
            health_score: Health score [0.0, 1.0].  Scores below 0.5 set
                          presence state to DEGRADED.
            details:     Optional extra details to include in the event.

        Returns:
            ``True`` if the node is known and the heartbeat was recorded,
            ``False`` if the node is not registered.
        """
        with self._rw_lock:
            record = self._records.get(node_id)
            if record is None:
                return False
            presence = record.fabric_presence
            presence.last_heartbeat_at = time.monotonic()
            presence.heartbeat_count += 1
            if health_score < 0.5:
                presence.presence_state = AssimilationPresenceState.DEGRADED
            elif presence.presence_state in (
                AssimilationPresenceState.OFFLINE,
                AssimilationPresenceState.STALE,
            ):
                presence.presence_state = AssimilationPresenceState.ONLINE
            else:
                presence.presence_state = AssimilationPresenceState.ONLINE

        self._emit_event(
            "heartbeat",
            node_id,
            {"health_score": health_score, **(details or {})},
        )
        return True

    def mark_offline(self, node_id: str, *, reason: str = "") -> bool:
        """Mark a node as OFFLINE in its :class:`FabricPresence`.

        Emits an ``"offline"`` event.

        Args:
            node_id: Node identifier.
            reason:  Human-readable reason for going offline.

        Returns:
            ``True`` if the node was known; ``False`` otherwise.
        """
        with self._rw_lock:
            record = self._records.get(node_id)
            if record is None:
                return False
            record.fabric_presence.presence_state = AssimilationPresenceState.OFFLINE

        self._emit_event("offline", node_id, {"reason": reason})
        logger.info(
            "Node %s marked OFFLINE — %s",
            node_id,
            reason or "(no reason)",
            extra={"event": "offline", "node_id": node_id},
        )
        return True

    def mark_stale_if_expired(
        self,
        *,
        heartbeat_ttl_secs: float = 60.0,
    ) -> List[str]:
        """Mark all nodes whose heartbeat is older than *heartbeat_ttl_secs* as STALE.

        Args:
            heartbeat_ttl_secs: Heartbeat age threshold in seconds.

        Returns:
            List of node IDs that were transitioned to STALE.
        """
        stale: List[str] = []
        with self._rw_lock:
            for node_id, record in self._records.items():
                presence = record.fabric_presence
                if presence.presence_state == AssimilationPresenceState.OFFLINE:
                    continue
                if presence.heartbeat_age_secs() > heartbeat_ttl_secs:
                    if presence.presence_state != AssimilationPresenceState.STALE:
                        presence.presence_state = AssimilationPresenceState.STALE
                        stale.append(node_id)
        for nid in stale:
            self._emit_event("stale", nid, {"ttl_secs": heartbeat_ttl_secs})
        return stale

    # ── Queries ───────────────────────────────────────────────────────────

    def get_record(self, node_id: str) -> Optional[AssimilationRecord]:
        """Return the :class:`AssimilationRecord` for *node_id*, or ``None``."""
        with self._rw_lock:
            return self._records.get(node_id)

    def list_records(self) -> List[AssimilationRecord]:
        """Return all current :class:`AssimilationRecord` objects."""
        with self._rw_lock:
            return list(self._records.values())

    def list_online_records(self) -> List[AssimilationRecord]:
        """Return records whose presence state is ONLINE."""
        with self._rw_lock:
            return [
                r
                for r in self._records.values()
                if r.fabric_presence.presence_state == AssimilationPresenceState.ONLINE
            ]

    def get_capability_descriptors(self) -> List[CapabilityDescriptor]:
        """Return all :class:`CapabilityDescriptor` objects for assimilated nodes."""
        with self._rw_lock:
            return [r.capability_descriptor for r in self._records.values()]

    def get_execution_profiles(self) -> List[ExecutionProfile]:
        """Return all :class:`ExecutionProfile` objects for assimilated nodes."""
        with self._rw_lock:
            return [r.execution_profile for r in self._records.values()]

    def get_fabric_presences(self) -> List[FabricPresence]:
        """Return all :class:`FabricPresence` objects for assimilated nodes."""
        with self._rw_lock:
            return [r.fabric_presence for r in self._records.values()]

    def get_event_log(self) -> Deque[AssimilationEvent]:
        """Return the 256-entry observability event ring buffer (read-only view)."""
        return self._event_log

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the assimilation layer state."""
        with self._rw_lock:
            records = list(self._records.values())

        by_kind: Dict[str, int] = {}
        by_presence: Dict[str, int] = {}
        for r in records:
            kind_val = (
                r.execution_profile.participant_kind.value
                if isinstance(r.execution_profile.participant_kind, NodeParticipantKind)
                else str(r.execution_profile.participant_kind)
            )
            by_kind[kind_val] = by_kind.get(kind_val, 0) + 1
            presence_val = (
                r.fabric_presence.presence_state.value
                if isinstance(r.fabric_presence.presence_state, AssimilationPresenceState)
                else str(r.fabric_presence.presence_state)
            )
            by_presence[presence_val] = by_presence.get(presence_val, 0) + 1

        return {
            "authority": CAPABILITY_ASSIMILATION_AUTHORITY,
            "layer_position": CAPABILITY_ASSIMILATION_LAYER_POSITION,
            "contract_version": ASSIMILATION_CONTRACT_VERSION,
            "total_nodes": len(records),
            "by_participant_kind": by_kind,
            "by_presence_state": by_presence,
            "projected_to_task_graph": sum(
                1 for r in records if r.projected_to_task_graph
            ),
            "projected_to_network_graph": sum(
                1 for r in records if r.projected_to_network_graph
            ),
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    def _project_to_task_graph(
        self,
        node_id: str,
        exec_profile: ExecutionProfile,
        notes: List[str],
    ) -> bool:
        """Project an execution-participant node into the task graph runtime."""
        try:
            from core.task_graph_runtime import get_task_graph_runtime, GraphNode

            runtime = get_task_graph_runtime()
            node = GraphNode(
                task_id=f"executor__{node_id}",
                metadata={
                    "assimilation_projection": True,
                    "participant_kind": (
                        exec_profile.participant_kind.value
                        if isinstance(exec_profile.participant_kind, NodeParticipantKind)
                        else exec_profile.participant_kind
                    ),
                    "priority": exec_profile.priority,
                    "max_concurrent_tasks": exec_profile.max_concurrent_tasks,
                },
            )
            runtime.register_node(node)
            return True
        except Exception as exc:
            notes.append(
                f"task_graph_projection skipped: {exc}"
            )
            logger.debug(
                "capability_assimilation: task graph projection unavailable for %s — %s",
                node_id,
                exc,
            )
            return False

    def _project_to_network_graph(
        self,
        node_id: str,
        fabric: FabricPresence,
        cap_desc: CapabilityDescriptor,
        notes: List[str],
    ) -> bool:
        """Project a node into the network graph runtime as a fabric participant."""
        try:
            from core.network_graph_runtime import (
                get_network_graph_runtime,
                NetworkNode,
                NetworkNodeRole,
            )

            runtime = get_network_graph_runtime()
            net_node = NetworkNode(
                node_id=node_id,
                role=NetworkNodeRole.FABRIC_PARTICIPANT,
                host=fabric.host,
                port=fabric.port,
                transport_hints=dict(fabric.transport_hints),
                tags=list(cap_desc.tags),
                metadata={"capabilities": list(cap_desc.capabilities)},
            )
            runtime.register_node(net_node)
            return True
        except Exception as exc:
            notes.append(
                f"network_graph_projection skipped: {exc}"
            )
            logger.debug(
                "capability_assimilation: network graph projection unavailable for %s — %s",
                node_id,
                exc,
            )
            return False

    def _emit_event(
        self,
        event_kind: str,
        node_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an :class:`AssimilationEvent` to the ring buffer."""
        event = AssimilationEvent(
            event_kind=event_kind,
            node_id=node_id,
            details=dict(details or {}),
        )
        self._event_log.append(event)


# ---------------------------------------------------------------------------
# Internal helper: architectural class → participant kind mapping
# ---------------------------------------------------------------------------


def _arch_class_to_participant_kind(arch_str: str) -> NodeParticipantKind:
    """Map a NodeArchitecturalClass string value to a :class:`NodeParticipantKind`."""
    _MAP: Dict[str, NodeParticipantKind] = {
        "capability_node": NodeParticipantKind.CAPABILITY_PROVIDER,
        "service_node": NodeParticipantKind.SPECIALIST,
        "legacy_orchestrator_node": NodeParticipantKind.LEGACY_FACADE,
        "experimental_node": NodeParticipantKind.FABRIC_PARTICIPANT,
        "archived_node": NodeParticipantKind.FABRIC_PARTICIPANT,
        "worker": NodeParticipantKind.WORKER,
        "worker_endpoint": NodeParticipantKind.WORKER,
        "agent": NodeParticipantKind.CAPABILITY_PROVIDER,
        "gateway": NodeParticipantKind.FABRIC_PARTICIPANT,
        "scheduler": NodeParticipantKind.FABRIC_PARTICIPANT,
        "storage": NodeParticipantKind.SPECIALIST,
        "tool": NodeParticipantKind.CAPABILITY_PROVIDER,
        "monitor": NodeParticipantKind.FABRIC_PARTICIPANT,
        # PR-D: extended provider classifications
        "device": NodeParticipantKind.DEVICE,
        "android_device": NodeParticipantKind.DEVICE,
        "iot_device": NodeParticipantKind.DEVICE,
        "desktop_device": NodeParticipantKind.DEVICE,
        "mcp_provider": NodeParticipantKind.MCP_PROVIDER,
        "mcp_server": NodeParticipantKind.MCP_PROVIDER,
        "mcp_tool": NodeParticipantKind.MCP_PROVIDER,
        "skill": NodeParticipantKind.SKILL,
        "skill_provider": NodeParticipantKind.SKILL,
        "specialist_executor": NodeParticipantKind.SPECIALIST,
    }
    return _MAP.get(arch_str.lower(), NodeParticipantKind.UNKNOWN)


# ---------------------------------------------------------------------------
# Module-level singleton helpers
# ---------------------------------------------------------------------------


def get_capability_assimilation_layer() -> CapabilityAssimilationLayer:
    """Return the global :class:`CapabilityAssimilationLayer` singleton."""
    return CapabilityAssimilationLayer()


def reset_capability_assimilation_layer() -> None:
    """Reset the :class:`CapabilityAssimilationLayer` singleton (for testing)."""
    CapabilityAssimilationLayer._instance = None


def assimilate_node(
    node_info_or_dict: Any,
) -> AssimilationRecord:
    """Convenience helper: assimilate a NodeInfo-compatible object or dict.

    Delegates to :meth:`CapabilityAssimilationLayer.assimilate_from_node_info`.

    Args:
        node_info_or_dict: A NodeInfo-compatible object or dict with at least
            a ``node_id`` key/attribute.

    Returns:
        The canonical :class:`AssimilationRecord`.
    """
    layer = get_capability_assimilation_layer()
    return layer.assimilate_from_node_info(node_info_or_dict)


# ---------------------------------------------------------------------------
# PR-D: Provider-specific assimilation helpers
# ---------------------------------------------------------------------------


def assimilate_device(
    device_id: str,
    *,
    capabilities: Optional[List[str]] = None,
    host: str = "localhost",
    port: int = 0,
    tags: Optional[List[str]] = None,
    transport_hints: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "AssimilationRecord":
    """Absorb a physical/virtual device into the capability assimilation layer.

    Devices are registered as :attr:`NodeParticipantKind.DEVICE` so that the
    capability selection plane can treat them as first-class capability
    providers alongside nodes, workers, skills, and MCP providers.

    Args:
        device_id:       Unique device identifier (e.g. ``"android-pixel7-001"``).
        capabilities:    Capability names the device exposes (e.g. ``["screen",
                         "camera", "touch"]``).
        host:            Device host address.
        port:            Device port (0 = dynamic / unknown).
        tags:            Classification labels (e.g. ``["android", "mobile"]``).
        transport_hints: Route hints (``{"preferred_path": "direct_ws"}``, etc.).
        metadata:        Arbitrary device metadata.

    Returns:
        The canonical :class:`AssimilationRecord` for the device.
    """
    layer = get_capability_assimilation_layer()
    return layer.assimilate(
        device_id,
        capabilities=capabilities,
        participant_kind=NodeParticipantKind.DEVICE,
        host=host,
        port=port,
        tags=tags,
        transport_hints=transport_hints,
        metadata=metadata,
    )


def assimilate_mcp_provider(
    provider_id: str,
    *,
    tools: Optional[List[str]] = None,
    host: str = "localhost",
    port: int = 0,
    tags: Optional[List[str]] = None,
    transport_hints: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "AssimilationRecord":
    """Absorb an MCP tool/skill provider into the capability assimilation layer.

    MCP providers are registered as :attr:`NodeParticipantKind.MCP_PROVIDER`
    so the capability graph can surface their tools as first-class capabilities.

    Args:
        provider_id:     Unique provider identifier (e.g. ``"mcp-filesystem-v1"``).
        tools:           Tool names exposed by this MCP server.
        host:            Provider host address.
        port:            Provider port (0 = dynamic / unknown).
        tags:            Classification labels (e.g. ``["mcp", "filesystem"]``).
        transport_hints: Route hints.
        metadata:        Arbitrary metadata.

    Returns:
        The canonical :class:`AssimilationRecord` for the MCP provider.
    """
    layer = get_capability_assimilation_layer()
    caps = list(tools or [])
    meta = dict(metadata or {})
    meta.setdefault("provider_type", "mcp")
    return layer.assimilate(
        provider_id,
        capabilities=caps,
        participant_kind=NodeParticipantKind.MCP_PROVIDER,
        host=host,
        port=port,
        tags=tags,
        transport_hints=transport_hints,
        metadata=meta,
    )


def assimilate_skill(
    skill_id: str,
    *,
    capabilities: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "AssimilationRecord":
    """Absorb a skill-based capability provider into the capability assimilation layer.

    Skills are registered as :attr:`NodeParticipantKind.SKILL` so that the
    capability selection plane can route to skill executors alongside nodes
    and devices.

    Args:
        skill_id:     Unique skill identifier (e.g. ``"skill-web-search-v2"``).
        capabilities: Capability names the skill exposes.
        tags:         Classification labels (e.g. ``["search", "web"]``).
        metadata:     Arbitrary metadata.

    Returns:
        The canonical :class:`AssimilationRecord` for the skill.
    """
    layer = get_capability_assimilation_layer()
    meta = dict(metadata or {})
    meta.setdefault("provider_type", "skill")
    return layer.assimilate(
        skill_id,
        capabilities=capabilities,
        participant_kind=NodeParticipantKind.SKILL,
        host="localhost",
        port=0,
        tags=tags,
        metadata=meta,
    )
