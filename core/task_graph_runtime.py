#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_graph_runtime.py
===========================
PR-6: Task Graph Runtime — Unified System-Level Task Execution Chassis.

Establishes the canonical **Task Graph Runtime** as the single unified chassis
for all task execution within Galaxy.  The existing DAG / workflow / step /
plan capabilities are preserved and absorbed as *contributors* to the runtime
via lightweight projection adapters — none of the legacy orchestration paths
are removed.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  TASK GRAPH RUNTIME  (this module)                                   │
    │  Unified lifecycle:                                                  │
    │    queued → dispatch → running → result → completed | failed         │
    │                                                                      │
    │  Node types:   task_node (unit of work)                              │
    │  Edge types:   dependency_edge  — structural DAG dependency          │
    │                dispatch_edge    — transport/carrier chosen            │
    │                result_edge      — result flows back to requester      │
    └──────────────────────────────────────────────────────────────────────┘
                        ↑ projection adapters
    ┌───────────────────────────────────────────────────────────────────┐
    │  Legacy orchestrators (retained as contributors)                  │
    │  • galaxy_gateway.orchestrator.GalaxyOrchestrator                 │
    │  • fusion.unified_orchestrator.UnifiedOrchestrator                │
    │  • core.orchestration.*                                           │
    │  • core.e2e_orchestrator                                          │
    │  Each emits node/edge records that the runtime indexes and tracks.│
    └───────────────────────────────────────────────────────────────────┘

Invariants
----------
1.  Every ``TaskEnvelope`` created anywhere in the system can be mapped to
    a ``GraphNode`` in the runtime.  The mapping key is ``task_id``.
2.  Every ``ResultEnvelope`` can be mapped back to the originating
    ``GraphNode`` and triggers a terminal state transition.
3.  ``TaskGraphRuntime`` is the **sole authority** for node state transitions
    beyond the initial *queued* state.  No orchestrator may silently change
    node state without going through the runtime API.
4.  Legacy orchestrators are explicitly NOT removed; they are demoted to
    **graph contributors** that register nodes/edges with the runtime.
5.  The runtime maintains a 256-entry observability ring buffer that can be
    consumed by ``status_board_v2`` and the operator console.

Public API
----------
Authority sentinels:
    TASK_GRAPH_RUNTIME_AUTHORITY
    TASK_GRAPH_RUNTIME_LAYER_POSITION
    TASK_GRAPH_NODE_CONTRACT_VERSION
    WORKFLOW_GRAPH_PROJECTION_POLICY

Enumerations:
    GraphNodeState
    GraphEdgeKind
    WorkflowContributorKind

Dataclasses:
    GraphNode
    GraphEdge
    GraphRuntimeRecord
    GraphRuntimeSnapshot
    WorkflowProjectionRecord

Helpers:
    envelope_to_graph_node(envelope) -> GraphNode
    result_envelope_to_node_update(result_envelope, node) -> GraphNode
    project_workflow_to_graph(workflow_record, runtime) -> WorkflowProjectionRecord
    get_task_graph_runtime() -> TaskGraphRuntime
    reset_task_graph_runtime() -> None   # for testing

Class:
    TaskGraphRuntime
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Iterator, List, Optional, Sequence

logger = logging.getLogger("Galaxy.TaskGraphRuntime")

__all__ = [
    # Authority sentinels
    "TASK_GRAPH_RUNTIME_AUTHORITY",
    "TASK_GRAPH_RUNTIME_LAYER_POSITION",
    "TASK_GRAPH_NODE_CONTRACT_VERSION",
    "WORKFLOW_GRAPH_PROJECTION_POLICY",
    # Enumerations
    "GraphNodeState",
    "GraphEdgeKind",
    "WorkflowContributorKind",
    # Dataclasses
    "GraphNode",
    "GraphEdge",
    "GraphRuntimeRecord",
    "GraphRuntimeSnapshot",
    "WorkflowProjectionRecord",
    # Helpers
    "envelope_to_graph_node",
    "result_envelope_to_node_update",
    "project_workflow_to_graph",
    "get_task_graph_runtime",
    "reset_task_graph_runtime",
    # Class
    "TaskGraphRuntime",
]

# ---------------------------------------------------------------------------
# Truncation limits (for result_summary and error fields)
# ---------------------------------------------------------------------------

MAX_RESULT_SUMMARY_LENGTH: int = 200
"""Maximum length for result_summary string stored on a GraphNode."""

MAX_ERROR_LENGTH: int = 400
"""Maximum length for error string stored on a GraphNode."""

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: This module is the canonical Task Graph Runtime for Galaxy.
#: All task lifecycle management flows through this runtime.
TASK_GRAPH_RUNTIME_AUTHORITY: str = "TASK_GRAPH_RUNTIME_V1"

#: Layer position in the Galaxy execution hierarchy.
#: 6 = Task Graph Runtime (above PR-5 admissibility/policy, below user surface).
TASK_GRAPH_RUNTIME_LAYER_POSITION: int = 6

#: Contract version for GraphNode serialisation.
TASK_GRAPH_NODE_CONTRACT_VERSION: str = "GRAPH_NODE_CONTRACT_V1"

#: Policy: legacy workflow/orchestration outputs are projected onto the task
#: graph as contributor records.  They are NEVER removed; only demoted to
#: graph contributors.
WORKFLOW_GRAPH_PROJECTION_POLICY: str = (
    "WORKFLOW_CONTRIBUTORS_PROJECTED_TO_GRAPH_NOT_REMOVED"
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class GraphNodeState(str, Enum):
    """Canonical lifecycle states for a single task graph node.

    Transition diagram::

        queued ──► dispatch ──► running ──► result ──► completed
                                                   └──► failed
    """
    QUEUED     = "queued"
    DISPATCH   = "dispatch"
    RUNNING    = "running"
    RESULT     = "result"
    COMPLETED  = "completed"
    FAILED     = "failed"


class GraphEdgeKind(str, Enum):
    """Kinds of edges in the task graph.

    dependency_edge
        Structural dependency: source must reach COMPLETED before target
        can advance beyond QUEUED.

    dispatch_edge
        Records the transport path chosen when a node moves from QUEUED to
        DISPATCH (e.g. direct_ws, nats, relay, gateway).

    result_edge
        Records the result flow from a terminal node back to the requester or
        dependent node.
    """
    DEPENDENCY = "dependency_edge"
    DISPATCH   = "dispatch_edge"
    RESULT     = "result_edge"


class WorkflowContributorKind(str, Enum):
    """Sources that can contribute nodes/edges to the task graph runtime."""
    GALAXY_ORCHESTRATOR   = "galaxy_orchestrator"
    UNIFIED_ORCHESTRATOR  = "unified_orchestrator"
    E2E_ORCHESTRATOR      = "e2e_orchestrator"
    TASK_GRAPH_ENGINE     = "task_graph_engine"         # core.task_graph.TaskGraph
    OPENCLAWD             = "openclawd"
    SCHEDULER             = "scheduler"
    COMMAND_ROUTER        = "command_router"
    UNKNOWN               = "unknown"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """A single node in the task graph runtime.

    Maps 1-to-1 with a ``TaskEnvelope`` (keyed by ``task_id``).
    """

    node_id: str = field(default_factory=lambda: f"gn_{uuid.uuid4().hex[:16]}")
    """Unique runtime node identifier.  Defaults to a prefixed UUID fragment."""

    task_id: str = ""
    """Task identifier from the originating ``TaskEnvelope``."""

    trace_id: str = ""
    """Distributed trace identifier propagated from the envelope."""

    session_id: str = ""
    """Session identifier for context continuity."""

    tool_name: str = ""
    """Tool, skill, or command name from the envelope."""

    device_id: str = ""
    """Target device ID (empty = unassigned / local)."""

    state: GraphNodeState = GraphNodeState.QUEUED
    """Current lifecycle state of the node."""

    contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN
    """Which orchestration layer contributed this node to the runtime."""

    depends_on: List[str] = field(default_factory=list)
    """node_ids that must reach COMPLETED before this node advances."""

    queued_at: float = field(default_factory=time.time)
    """Epoch timestamp when the node entered QUEUED state."""

    dispatch_at: Optional[float] = None
    """Epoch timestamp when the node entered DISPATCH state."""

    running_at: Optional[float] = None
    """Epoch timestamp when the node entered RUNNING state."""

    result_at: Optional[float] = None
    """Epoch timestamp when the result was received."""

    completed_at: Optional[float] = None
    """Epoch timestamp when the node reached a terminal state."""

    result_summary: str = ""
    """Human-readable summary of the terminal result."""

    error: str = ""
    """Error message if the node reached FAILED state."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata attached by contributors."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "node_id": self.node_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "tool_name": self.tool_name,
            "device_id": self.device_id,
            "state": self.state.value,
            "contributor": self.contributor.value,
            "depends_on": list(self.depends_on),
            "queued_at": self.queued_at,
            "dispatch_at": self.dispatch_at,
            "running_at": self.running_at,
            "result_at": self.result_at,
            "completed_at": self.completed_at,
            "result_summary": self.result_summary,
            "error": self.error,
            "metadata": dict(self.metadata),
        }


@dataclass
class GraphEdge:
    """A directed edge between two nodes in the task graph.

    Used for dependency, dispatch, and result flow tracking.
    """

    edge_id: str = field(default_factory=lambda: f"ge_{uuid.uuid4().hex[:12]}")
    """Unique edge identifier."""

    kind: GraphEdgeKind = GraphEdgeKind.DEPENDENCY
    """The semantic type of the edge."""

    source_node_id: str = ""
    """node_id of the source (origin) node."""

    target_node_id: str = ""
    """node_id of the target (destination) node."""

    transport_path: str = ""
    """For dispatch_edge: the transport strategy selected (e.g. 'direct_ws')."""

    created_at: float = field(default_factory=time.time)
    """Epoch timestamp when the edge was created."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata attached by contributors."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "edge_id": self.edge_id,
            "kind": self.kind.value,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "transport_path": self.transport_path,
            "created_at": self.created_at,
            "metadata": dict(self.metadata),
        }


@dataclass
class GraphRuntimeRecord:
    """An observability record emitted on each node state transition."""

    record_id: str = field(default_factory=lambda: f"gr_{uuid.uuid4().hex[:12]}")
    """Unique record identifier."""

    node_id: str = ""
    """The node that transitioned."""

    task_id: str = ""
    """task_id of the node for cross-correlation."""

    trace_id: str = ""
    """trace_id of the node for distributed tracing."""

    previous_state: str = ""
    """State before the transition."""

    new_state: str = ""
    """State after the transition."""

    transition_reason: str = ""
    """Human-readable reason for the transition."""

    contributor: str = ""
    """Contributor that triggered the transition."""

    ts: float = field(default_factory=time.time)
    """Epoch timestamp of the transition."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "record_id": self.record_id,
            "node_id": self.node_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "previous_state": self.previous_state,
            "new_state": self.new_state,
            "transition_reason": self.transition_reason,
            "contributor": self.contributor,
            "ts": self.ts,
        }


@dataclass
class GraphRuntimeSnapshot:
    """A point-in-time snapshot of the entire task graph runtime state.

    Suitable for consumption by ``status_board_v2`` and the operator console.
    """

    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:10]}")
    """Unique snapshot identifier."""

    ts: float = field(default_factory=time.time)
    """Epoch timestamp of the snapshot."""

    total_nodes: int = 0
    """Total number of nodes currently tracked by the runtime."""

    total_edges: int = 0
    """Total number of edges currently tracked by the runtime."""

    nodes_by_state: Dict[str, int] = field(default_factory=dict)
    """Count of nodes grouped by state value."""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    """Serialised GraphNode dicts (all tracked nodes)."""

    edges: List[Dict[str, Any]] = field(default_factory=list)
    """Serialised GraphEdge dicts (all tracked edges)."""

    recent_records: List[Dict[str, Any]] = field(default_factory=list)
    """Most-recent observability records from the ring buffer."""

    authority: str = TASK_GRAPH_RUNTIME_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "snapshot_id": self.snapshot_id,
            "ts": self.ts,
            "total_nodes": self.total_nodes,
            "total_edges": self.total_edges,
            "nodes_by_state": dict(self.nodes_by_state),
            "nodes": list(self.nodes),
            "edges": list(self.edges),
            "recent_records": list(self.recent_records),
            "authority": self.authority,
        }


@dataclass
class WorkflowProjectionRecord:
    """Records the projection of a legacy workflow contribution onto the task graph.

    Created whenever an orchestrator registers nodes/edges via the projection
    adapter.  Retained in the runtime's ring buffer for observability.
    """

    projection_id: str = field(default_factory=lambda: f"proj_{uuid.uuid4().hex[:12]}")
    """Unique projection record identifier."""

    contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN
    """Which orchestrator contributed this projection."""

    trace_id: str = ""
    """trace_id from the contributing workflow context."""

    session_id: str = ""
    """session_id from the contributing workflow context."""

    node_ids_registered: List[str] = field(default_factory=list)
    """node_ids that were registered in the runtime as a result of this projection."""

    edge_ids_registered: List[str] = field(default_factory=list)
    """edge_ids that were registered in the runtime as a result of this projection."""

    ts: float = field(default_factory=time.time)
    """Epoch timestamp of the projection."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary metadata from the workflow context."""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "projection_id": self.projection_id,
            "contributor": self.contributor.value,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "node_ids_registered": list(self.node_ids_registered),
            "edge_ids_registered": list(self.edge_ids_registered),
            "ts": self.ts,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# TaskGraphRuntime
# ---------------------------------------------------------------------------


class TaskGraphRuntime:
    """Unified task graph runtime — the system-level task execution chassis.

    Responsibilities
    ----------------
    * Track every in-flight task as a ``GraphNode`` keyed by ``task_id``.
    * Record structural (dependency), dispatch, and result ``GraphEdge`` objects.
    * Manage canonical node state transitions:
        ``queued → dispatch → running → result → completed | failed``
    * Provide a projection adapter so legacy workflow/orchestration layers can
      register their nodes/edges without any code removal.
    * Maintain a 256-entry observability ring buffer for ``status_board_v2``
      and the operator console.

    Thread safety
    -------------
    The runtime is designed for single-threaded async use.  If called from
    multiple threads, the caller is responsible for serialisation.
    """

    _RING_BUFFER_SIZE: int = 256

    def __init__(self) -> None:
        self._nodes: Dict[str, GraphNode] = {}          # keyed by task_id
        self._nodes_by_node_id: Dict[str, GraphNode] = {}  # keyed by node_id
        self._edges: Dict[str, GraphEdge] = {}          # keyed by edge_id
        self._records: Deque[GraphRuntimeRecord] = deque(maxlen=self._RING_BUFFER_SIZE)
        self._projections: Deque[WorkflowProjectionRecord] = deque(maxlen=self._RING_BUFFER_SIZE)

    # ── Node management ──────────────────────────────────────────────────────

    def register_node(self, node: GraphNode) -> GraphNode:
        """Register a new ``GraphNode`` with the runtime.

        If a node with the same ``task_id`` is already registered, the existing
        node is returned unchanged (idempotent registration).

        Args:
            node: The graph node to register.  Must have a non-empty ``task_id``.

        Returns:
            The registered node (existing node if already present).
        """
        if not node.task_id:
            raise ValueError("GraphNode.task_id must be non-empty")
        if node.task_id in self._nodes:
            return self._nodes[node.task_id]
        self._nodes[node.task_id] = node
        self._nodes_by_node_id[node.node_id] = node
        self._emit_record(
            node=node,
            previous_state="",
            new_state=node.state.value,
            reason="registered",
        )
        logger.debug(
            "task_graph_runtime | registered node_id=%s task_id=%s state=%s",
            node.node_id, node.task_id, node.state.value,
        )
        return node

    def get_node_by_task_id(self, task_id: str) -> Optional[GraphNode]:
        """Return the node registered for the given ``task_id``, or ``None``."""
        return self._nodes.get(task_id)

    def get_node_by_node_id(self, node_id: str) -> Optional[GraphNode]:
        """Return the node with the given ``node_id``, or ``None``."""
        return self._nodes_by_node_id.get(node_id)

    def all_nodes(self) -> List[GraphNode]:
        """Return all currently tracked nodes."""
        return list(self._nodes.values())

    # ── State transitions ────────────────────────────────────────────────────

    def transition(
        self,
        task_id: str,
        new_state: GraphNodeState,
        *,
        reason: str = "",
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
        result_summary: str = "",
        error: str = "",
        transport_path: str = "",
    ) -> Optional[GraphNode]:
        """Transition a node to ``new_state``.

        Creates appropriate edges:
        - DISPATCH transition → creates a ``dispatch_edge``
        - COMPLETED/FAILED transition → creates a ``result_edge``

        Args:
            task_id:        Identifies the node to transition.
            new_state:      The target lifecycle state.
            reason:         Human-readable explanation for the transition.
            contributor:    The orchestration layer driving the transition.
            result_summary: Terminal result summary (for COMPLETED state).
            error:          Error message (for FAILED state).
            transport_path: Transport strategy (for DISPATCH state).

        Returns:
            The updated ``GraphNode``, or ``None`` if ``task_id`` is unknown.
        """
        node = self._nodes.get(task_id)
        if node is None:
            logger.warning(
                "task_graph_runtime | transition: unknown task_id=%s", task_id
            )
            return None

        previous_state = node.state.value
        now = time.time()

        node.state = new_state
        node.contributor = contributor

        if new_state == GraphNodeState.DISPATCH:
            node.dispatch_at = now
            self._add_dispatch_edge(node, transport_path=transport_path)
        elif new_state == GraphNodeState.RUNNING:
            node.running_at = now
        elif new_state == GraphNodeState.RESULT:
            node.result_at = now
        elif new_state in (GraphNodeState.COMPLETED, GraphNodeState.FAILED):
            node.completed_at = now
            node.result_summary = result_summary
            node.error = error
            self._add_result_edge(node)

        self._emit_record(
            node=node,
            previous_state=previous_state,
            new_state=new_state.value,
            reason=reason or f"transition_to_{new_state.value}",
            contributor=contributor.value,
        )
        logger.info(
            "task_graph_runtime | transition task_id=%s %s → %s reason=%s",
            task_id, previous_state, new_state.value, reason,
        )
        return node

    # ── Edge management ──────────────────────────────────────────────────────

    def register_edge(self, edge: GraphEdge) -> GraphEdge:
        """Register a ``GraphEdge`` with the runtime.

        If an edge with the same ``edge_id`` already exists, it is returned
        unchanged (idempotent).

        Args:
            edge: The edge to register.

        Returns:
            The registered edge.
        """
        if edge.edge_id in self._edges:
            return self._edges[edge.edge_id]
        self._edges[edge.edge_id] = edge
        logger.debug(
            "task_graph_runtime | registered edge_id=%s kind=%s %s → %s",
            edge.edge_id, edge.kind.value,
            edge.source_node_id, edge.target_node_id,
        )
        return edge

    def add_dependency_edge(
        self,
        source_node_id: str,
        target_node_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GraphEdge:
        """Add a dependency edge from ``source_node_id`` → ``target_node_id``.

        The source node must complete before the target node can advance.

        Args:
            source_node_id: Node that must complete first.
            target_node_id: Node that depends on the source.
            metadata:       Optional metadata dict.

        Returns:
            The created ``GraphEdge``.
        """
        edge = GraphEdge(
            kind=GraphEdgeKind.DEPENDENCY,
            source_node_id=source_node_id,
            target_node_id=target_node_id,
            metadata=metadata or {},
        )
        return self.register_edge(edge)

    def all_edges(self) -> List[GraphEdge]:
        """Return all currently tracked edges."""
        return list(self._edges.values())

    # ── Envelope mapping helpers ─────────────────────────────────────────────

    def register_envelope(
        self,
        envelope: Any,
        *,
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
        device_id: str = "",
        depends_on: Optional[List[str]] = None,
    ) -> GraphNode:
        """Map a ``TaskEnvelope`` to a new ``GraphNode`` and register it.

        This is the canonical entry point for integrating TaskEnvelope objects
        into the runtime.  Idempotent: if the envelope's ``task_id`` is already
        registered, the existing node is returned.

        Args:
            envelope:    A ``TaskEnvelope`` instance (or any object exposing
                         ``task_id``, ``trace_id``, ``session_id``, ``tool_name``).
            contributor: Which orchestration layer is registering the envelope.
            device_id:   Override or supplement ``envelope.targets[0]``.
            depends_on:  List of ``task_id`` strings this task depends on.

        Returns:
            The registered (or pre-existing) ``GraphNode``.
        """
        node = envelope_to_graph_node(
            envelope,
            contributor=contributor,
            device_id=device_id,
            depends_on=depends_on or [],
        )

        registered = self.register_node(node)

        # Wire dependency edges for each listed dependency
        for dep_task_id in (depends_on or []):
            dep_node = self._nodes.get(dep_task_id)
            if dep_node is not None:
                self.add_dependency_edge(
                    source_node_id=dep_node.node_id,
                    target_node_id=registered.node_id,
                )
        return registered

    def complete_from_result_envelope(
        self,
        result_envelope: Any,
        *,
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> Optional[GraphNode]:
        """Map a ``ResultEnvelope`` back to its originating node and complete it.

        Transitions the node through RESULT → COMPLETED (or FAILED if the
        result envelope signals failure).

        Args:
            result_envelope: A ``ResultEnvelope`` instance (or any object
                             exposing ``task_id``, ``success``, ``result``,
                             ``error``).
            contributor:     Which layer is completing the node.

        Returns:
            The updated ``GraphNode``, or ``None`` if the task_id is unknown.
        """
        task_id = getattr(result_envelope, "task_id", "")
        if not task_id:
            logger.warning(
                "task_graph_runtime | complete_from_result_envelope: "
                "result_envelope has no task_id"
            )
            return None

        # Move to RESULT state first (acknowledges result receipt)
        self.transition(
            task_id,
            GraphNodeState.RESULT,
            reason="result_received",
            contributor=contributor,
        )

        # Determine terminal state
        success = getattr(result_envelope, "success", True)
        error_val = getattr(result_envelope, "error", "") or ""
        result_data = getattr(result_envelope, "result", None)
        summary = str(result_data)[:MAX_RESULT_SUMMARY_LENGTH] if result_data else ""

        terminal = GraphNodeState.COMPLETED if success else GraphNodeState.FAILED
        return self.transition(
            task_id,
            terminal,
            reason="result_processed",
            contributor=contributor,
            result_summary=summary,
            error=str(error_val) if error_val else "",
        )

    # ── Workflow projection adapter ──────────────────────────────────────────

    def project_workflow(
        self,
        *,
        contributor: WorkflowContributorKind,
        nodes: Sequence[GraphNode],
        edges: Optional[Sequence[GraphEdge]] = None,
        trace_id: str = "",
        session_id: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> WorkflowProjectionRecord:
        """Project a legacy workflow's nodes and edges onto the task graph.

        Legacy orchestrators call this method to register their task graph
        contributions without being removed from the codebase.  Each node and
        edge is registered idempotently.

        Args:
            contributor: The orchestration layer contributing the projection.
            nodes:       Sequence of ``GraphNode`` objects to register.
            edges:       Optional sequence of ``GraphEdge`` objects to register.
            trace_id:    Workflow trace ID for correlation.
            session_id:  Workflow session ID for context continuity.
            metadata:    Arbitrary metadata from the workflow context.

        Returns:
            A ``WorkflowProjectionRecord`` documenting the projection.
        """
        node_ids: List[str] = []
        edge_ids: List[str] = []

        for node in nodes:
            registered = self.register_node(node)
            node_ids.append(registered.node_id)

        for edge in (edges or []):
            registered_edge = self.register_edge(edge)
            edge_ids.append(registered_edge.edge_id)

        record = WorkflowProjectionRecord(
            contributor=contributor,
            trace_id=trace_id,
            session_id=session_id,
            node_ids_registered=node_ids,
            edge_ids_registered=edge_ids,
            metadata=metadata or {},
        )
        self._projections.append(record)
        logger.info(
            "task_graph_runtime | workflow_projection contributor=%s "
            "nodes=%d edges=%d trace_id=%s",
            contributor.value, len(node_ids), len(edge_ids), trace_id,
        )
        return record

    # ── Observability ────────────────────────────────────────────────────────

    def snapshot(self, *, max_records: int = 50) -> GraphRuntimeSnapshot:
        """Build a point-in-time observability snapshot.

        Suitable for consumption by ``status_board_v2`` and operator consoles.

        Args:
            max_records: Maximum number of recent records to include.

        Returns:
            A ``GraphRuntimeSnapshot`` with all current nodes/edges and recent
            transition records.
        """
        nodes_by_state: Dict[str, int] = {}
        for s in GraphNodeState:
            nodes_by_state[s.value] = 0
        for node in self._nodes.values():
            nodes_by_state[node.state.value] = nodes_by_state.get(node.state.value, 0) + 1

        recent = list(self._records)[-max_records:]

        return GraphRuntimeSnapshot(
            total_nodes=len(self._nodes),
            total_edges=len(self._edges),
            nodes_by_state=nodes_by_state,
            nodes=[n.to_dict() for n in self._nodes.values()],
            edges=[e.to_dict() for e in self._edges.values()],
            recent_records=[r.to_dict() for r in recent],
        )

    def get_observability_log(self) -> Deque[GraphRuntimeRecord]:
        """Return the internal 256-entry ring buffer of transition records."""
        return self._records

    def get_projection_log(self) -> Deque[WorkflowProjectionRecord]:
        """Return the internal 256-entry ring buffer of projection records."""
        return self._projections

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _add_dispatch_edge(self, node: GraphNode, transport_path: str = "") -> None:
        """Create a dispatch_edge for a node entering DISPATCH state."""
        edge = GraphEdge(
            kind=GraphEdgeKind.DISPATCH,
            source_node_id=node.node_id,
            target_node_id=node.device_id or node.node_id,
            transport_path=transport_path,
            metadata={"task_id": node.task_id},
        )
        self.register_edge(edge)

    def _add_result_edge(self, node: GraphNode) -> None:
        """Create a result_edge for a node entering a terminal state."""
        edge = GraphEdge(
            kind=GraphEdgeKind.RESULT,
            source_node_id=node.device_id or node.node_id,
            target_node_id=node.node_id,
            metadata={
                "task_id": node.task_id,
                "state": node.state.value,
            },
        )
        self.register_edge(edge)

    def _emit_record(
        self,
        node: GraphNode,
        previous_state: str,
        new_state: str,
        reason: str = "",
        contributor: str = "",
    ) -> None:
        """Append a transition record to the observability ring buffer."""
        record = GraphRuntimeRecord(
            node_id=node.node_id,
            task_id=node.task_id,
            trace_id=node.trace_id,
            previous_state=previous_state,
            new_state=new_state,
            transition_reason=reason,
            contributor=contributor or node.contributor.value,
        )
        self._records.append(record)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_runtime: Optional[TaskGraphRuntime] = None


def get_task_graph_runtime() -> TaskGraphRuntime:
    """Return (or lazily create) the module-level TaskGraphRuntime singleton."""
    global _runtime
    if _runtime is None:
        _runtime = TaskGraphRuntime()
    return _runtime


def reset_task_graph_runtime() -> None:
    """Reset the module-level singleton.  For testing only."""
    global _runtime
    _runtime = None


# ---------------------------------------------------------------------------
# Public helper functions
# ---------------------------------------------------------------------------


def envelope_to_graph_node(
    envelope: Any,
    *,
    contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    device_id: str = "",
    depends_on: Optional[List[str]] = None,
) -> GraphNode:
    """Construct a ``GraphNode`` from a ``TaskEnvelope`` (or compatible object).

    Reads ``task_id``, ``trace_id``, ``session_id``, ``tool_name``, and
    ``targets`` from the envelope using ``getattr`` so that both Pydantic
    models and plain dataclasses are supported.

    Args:
        envelope:    A ``TaskEnvelope`` or compatible object.
        contributor: Orchestration layer that owns this envelope.
        device_id:   Override device_id; falls back to ``envelope.targets[0]``.
        depends_on:  ``task_id`` list of dependency tasks.

    Returns:
        A new ``GraphNode`` in QUEUED state.
    """
    raw_task_id = getattr(envelope, "task_id", "") or ""
    if not raw_task_id:
        logger.warning(
            "envelope_to_graph_node: envelope has no task_id; auto-generating one. "
            "This may indicate an incorrectly constructed TaskEnvelope."
        )
        task_id = f"task_{uuid.uuid4().hex[:12]}"
    else:
        task_id = raw_task_id
    trace_id = getattr(envelope, "trace_id", "") or ""
    session_id = getattr(envelope, "session_id", "") or ""
    tool_name = getattr(envelope, "tool_name", "") or ""

    # Resolve device_id: explicit override → envelope targets → empty
    if not device_id:
        targets = getattr(envelope, "targets", None) or []
        device_id = targets[0] if targets else ""

    return GraphNode(
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id or "",
        tool_name=tool_name,
        device_id=device_id,
        state=GraphNodeState.QUEUED,
        contributor=contributor,
        depends_on=list(depends_on or []),
    )


def result_envelope_to_node_update(
    result_envelope: Any,
    node: GraphNode,
) -> GraphNode:
    """Apply a ``ResultEnvelope`` (or compatible object) to a ``GraphNode``.

    Returns the *same* node object with state, result_summary, error, and
    timestamps updated.  Does **not** register anything in the runtime;
    call :meth:`TaskGraphRuntime.complete_from_result_envelope` for the
    full runtime integration.

    Args:
        result_envelope: A ``ResultEnvelope`` or compatible object.
        node:            The target ``GraphNode`` to update (mutated in-place).

    Returns:
        The updated ``GraphNode``.
    """
    success = getattr(result_envelope, "success", True)
    error_val = getattr(result_envelope, "error", "") or ""
    result_data = getattr(result_envelope, "result", None)

    node.result_at = time.time()
    node.completed_at = time.time()
    node.state = GraphNodeState.COMPLETED if success else GraphNodeState.FAILED
    node.result_summary = str(result_data)[:MAX_RESULT_SUMMARY_LENGTH] if result_data else ""
    node.error = str(error_val)[:MAX_ERROR_LENGTH] if error_val else ""
    return node


def project_workflow_to_graph(
    workflow_record: Dict[str, Any],
    runtime: TaskGraphRuntime,
) -> WorkflowProjectionRecord:
    """Project a workflow execution record dict onto the task graph runtime.

    This is the convenience function for legacy orchestrators that produce a
    result dict (e.g. from ``compile_and_run_dag`` or ``TaskOrchestrator``)
    and want to register the implied nodes/edges without restructuring their
    internal flow.

    The function synthesises ``GraphNode`` objects from the ``node_statuses``
    field (if present) and registers them via ``runtime.project_workflow``.

    Args:
        workflow_record: A dict from a legacy orchestrator result.
            Expected keys (all optional, gracefully absent):
            - ``trace_id`` (str)
            - ``session_id`` (str)
            - ``graph_id`` (str)
            - ``node_statuses`` (Dict[str, str])  node_id → status string
            - ``contributor`` (str)  WorkflowContributorKind value
        runtime: The runtime to project onto.

    Returns:
        A ``WorkflowProjectionRecord`` documenting the projection.
    """
    trace_id = workflow_record.get("trace_id", "")
    session_id = workflow_record.get("session_id", "")
    contributor_str = workflow_record.get("contributor", WorkflowContributorKind.UNKNOWN.value)
    try:
        contributor = WorkflowContributorKind(contributor_str)
    except ValueError:
        contributor = WorkflowContributorKind.UNKNOWN

    node_statuses: Dict[str, str] = workflow_record.get("node_statuses", {}) or {}

    # Map legacy NodeStatus → GraphNodeState
    _status_map: Dict[str, GraphNodeState] = {
        "pending":    GraphNodeState.QUEUED,
        "queued":     GraphNodeState.QUEUED,
        "running":    GraphNodeState.RUNNING,
        "done":       GraphNodeState.COMPLETED,
        "completed":  GraphNodeState.COMPLETED,
        "failed":     GraphNodeState.FAILED,
        "skipped":    GraphNodeState.FAILED,
        "cancelled":  GraphNodeState.FAILED,
        "interrupted": GraphNodeState.FAILED,
        "dispatch":   GraphNodeState.DISPATCH,
        "result":     GraphNodeState.RESULT,
    }

    nodes: List[GraphNode] = []
    for raw_node_id, raw_status in node_statuses.items():
        mapped_state = _status_map.get(raw_status, GraphNodeState.QUEUED)
        node = GraphNode(
            task_id=raw_node_id,
            trace_id=trace_id,
            session_id=session_id,
            state=mapped_state,
            contributor=contributor,
            metadata={"legacy_status": raw_status, "graph_id": workflow_record.get("graph_id", "")},
        )
        nodes.append(node)

    return runtime.project_workflow(
        contributor=contributor,
        nodes=nodes,
        trace_id=trace_id,
        session_id=session_id,
        metadata=workflow_record,
    )
