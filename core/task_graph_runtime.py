#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_graph_runtime.py
===========================
PR-6 / PR-C: Task Graph Runtime — Unified System-Level Task Execution Chassis.

Establishes the canonical **Task Graph Runtime** as the single unified chassis
for all task execution within Galaxy.  The existing DAG / workflow / step /
plan capabilities are preserved and absorbed as *contributors* to the runtime
via lightweight projection adapters — none of the legacy orchestration paths
are removed.

PR-C additions (Graph Runtime Convergence)
------------------------------------------
* Extended ``GraphNodeState`` covering the full CanonicalTask lifecycle:
  admitted, planned, routed, partial_result, cancelled, degraded, replayed.
* Extended ``GraphEdgeKind`` with retry_edge, fallback_edge, fanout_edge,
  fanin_edge — providing explicit lineage for all non-happy-path flows.
* New observability dataclasses: ``RetryRecord``, ``FallbackRecord``,
  ``FanoutRecord``.
* New ``TaskGraphRuntime`` methods:
  - ``register_canonical_task()``   — maps a CanonicalTask entity to a node
  - ``register_retry()``            — creates a retry edge + RetryRecord
  - ``register_fallback()``         — creates a fallback edge + FallbackRecord
  - ``register_fanout()``           — creates fanout edges from one parent
  - ``register_fanin()``            — creates fanin edges to one aggregator
  - ``get_retry_lineage()``         — full retry chain for a task_id
  - ``get_fallback_lineage()``      — full fallback chain for a task_id
  - ``get_fanout_children()``       — direct fanout children of a task_id
  - ``get_fanin_parents()``         — direct fanin parents of a task_id
* Updated ``snapshot()`` to include retry/fallback/fanout/fanin counts and
  the canonical ``GRAPH_RUNTIME_CONVERGENCE_AUTHORITY`` sentinel.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────────┐
    │  TASK GRAPH RUNTIME  (this module)                                   │
    │  Full lifecycle:                                                     │
    │    queued → admitted → planned → routed → dispatch → running         │
    │          → result | partial_result → completed | failed              │
    │          → cancelled | degraded | replayed                           │
    │                                                                      │
    │  Node types:   task_node (unit of work)                              │
    │  Edge types:   dependency_edge  — structural DAG dependency          │
    │                dispatch_edge    — transport/carrier chosen            │
    │                result_edge      — result flows back to requester      │
    │                retry_edge       — retry attempt lineage               │
    │                fallback_edge    — degraded path lineage               │
    │                fanout_edge      — multi-target dispatch child         │
    │                fanin_edge       — aggregated result from children     │
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
6.  retry / fallback / fanout / fanin relations form explicit graph edges —
    not scattered log entries — so that lineage is always queryable.

Public API
----------
Authority sentinels:
    TASK_GRAPH_RUNTIME_AUTHORITY
    TASK_GRAPH_RUNTIME_LAYER_POSITION
    TASK_GRAPH_NODE_CONTRACT_VERSION
    WORKFLOW_GRAPH_PROJECTION_POLICY
    GRAPH_RUNTIME_CONVERGENCE_AUTHORITY

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
    RetryRecord
    FallbackRecord
    FanoutRecord

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
    "GRAPH_RUNTIME_CONVERGENCE_AUTHORITY",
    "TASK_GRAPH_RUNTIME_REALIZATION_AUTHORITY",
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
    "RetryRecord",
    "FallbackRecord",
    "FanoutRecord",
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

#: PR-C convergence authority sentinel.  Signals that retry / fallback /
#: fanout / fanin edges, the extended lifecycle states, and the CanonicalTask
#: integration path are all active in this runtime instance.
GRAPH_RUNTIME_CONVERGENCE_AUTHORITY: str = "GRAPH_RUNTIME_CONVERGENCE_V1"

#: PR-508 realization authority sentinel.  Signals that lifecycle transitions,
#: retry/fallback/fanout/fanin graph writes, workflow/orchestrator graph
#: contribution, and lineage queries are all backed by real runtime writes.
TASK_GRAPH_RUNTIME_REALIZATION_AUTHORITY: str = "TASK_GRAPH_RUNTIME_REALIZATION_V1"

#: Stage 10 sentinel: register_node_raw() convenience method added so that
#: lightweight callers (WakeRouter, etc.) can register task-graph nodes without
#: importing or constructing GraphNode directly.
#: Also: register_canonical_task() now reads intent.requested_action as a
#: fallback when intent.tool_name is absent, fixing CanonicalTask tool_name
#: propagation into the task graph.
TASK_GRAPH_STAGE10_CONVERGENCE: str = (
    "TASK_GRAPH_STAGE10_V1: register_node_raw() added; "
    "register_canonical_task() reads requested_action fallback for tool_name; "
    "WakeRouter routing decisions now registered in TaskGraphRuntime."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class GraphNodeState(str, Enum):
    """Canonical lifecycle states for a single task graph node.

    Transition diagram (PR-C extended)::

        queued -> admitted -> planned -> routed -> dispatch -> running
                                                                 |
                                                  +--------------+
                                                  v              v
                                                result    partial_result
                                                  |              |
                                            +-----+------+       |
                                            v            v       v
                                        completed      failed  degraded
                                                         |
                                                  cancelled / replayed

    The original 6-state set (queued, dispatch, running, result, completed,
    failed) is fully preserved for backward compatibility.  The 7 new states
    (admitted, planned, routed, partial_result, cancelled, degraded, replayed)
    are additive.
    """
    # Original PR-6 states (preserved, unchanged)
    QUEUED     = "queued"
    DISPATCH   = "dispatch"
    RUNNING    = "running"
    RESULT     = "result"
    COMPLETED  = "completed"
    FAILED     = "failed"

    # PR-C extended states -- aligned with CanonicalTask.TaskLifecycle
    ADMITTED       = "admitted"
    PLANNED        = "planned"
    ROUTED         = "routed"
    PARTIAL_RESULT = "partial_result"
    CANCELLED      = "cancelled"
    DEGRADED       = "degraded"
    REPLAYED       = "replayed"


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

    retry_edge  (PR-C)
        Links the original failed node to its retry attempt node.

    fallback_edge  (PR-C)
        Links the primary failed/degraded node to the fallback node.

    fanout_edge  (PR-C)
        Links a parent dispatch node to one of its parallel child nodes.

    fanin_edge  (PR-C)
        Links a child node back to the aggregator node collecting results.
    """
    DEPENDENCY = "dependency_edge"
    DISPATCH   = "dispatch_edge"
    RESULT     = "result_edge"
    RETRY      = "retry_edge"
    FALLBACK   = "fallback_edge"
    FANOUT     = "fanout_edge"
    FANIN      = "fanin_edge"


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

    # PR-C lineage counts
    total_retry_records: int = 0
    """Total number of retry relations recorded."""

    total_fallback_records: int = 0
    """Total number of fallback relations recorded."""

    total_fanout_records: int = 0
    """Total number of fanout/fanin relations recorded."""

    convergence_authority: str = GRAPH_RUNTIME_CONVERGENCE_AUTHORITY
    """Signals that PR-C convergence features are active."""

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
            "total_retry_records": self.total_retry_records,
            "total_fallback_records": self.total_fallback_records,
            "total_fanout_records": self.total_fanout_records,
            "convergence_authority": self.convergence_authority,
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
# PR-C Observability dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RetryRecord:
    """Observability record for a retry relation between two graph nodes.

    Created when :meth:`TaskGraphRuntime.register_retry` is called.
    """

    record_id: str = field(default_factory=lambda: f"retry_{uuid.uuid4().hex[:12]}")
    """Unique retry record identifier."""

    original_task_id: str = ""
    """task_id of the original node that failed or was retried."""

    retry_task_id: str = ""
    """task_id of the new retry attempt node."""

    edge_id: str = ""
    """edge_id of the retry_edge created for this record."""

    attempt_number: int = 1
    """Monotonically increasing retry attempt counter (1-based)."""

    reason: str = ""
    """Human-readable reason for the retry."""

    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "original_task_id": self.original_task_id,
            "retry_task_id": self.retry_task_id,
            "edge_id": self.edge_id,
            "attempt_number": self.attempt_number,
            "reason": self.reason,
            "ts": self.ts,
        }


@dataclass
class FallbackRecord:
    """Observability record for a fallback relation between two graph nodes.

    Created when :meth:`TaskGraphRuntime.register_fallback` is called.
    """

    record_id: str = field(default_factory=lambda: f"fallback_{uuid.uuid4().hex[:12]}")
    """Unique fallback record identifier."""

    primary_task_id: str = ""
    """task_id of the primary node that triggered the fallback."""

    fallback_task_id: str = ""
    """task_id of the fallback node."""

    edge_id: str = ""
    """edge_id of the fallback_edge created for this record."""

    reason: str = ""
    """Human-readable reason for the fallback."""

    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "primary_task_id": self.primary_task_id,
            "fallback_task_id": self.fallback_task_id,
            "edge_id": self.edge_id,
            "reason": self.reason,
            "ts": self.ts,
        }


@dataclass
class FanoutRecord:
    """Observability record for a fanout/fanin multi-target dispatch.

    Created when :meth:`TaskGraphRuntime.register_fanout` or
    :meth:`TaskGraphRuntime.register_fanin` is called.
    """

    record_id: str = field(default_factory=lambda: f"fanout_{uuid.uuid4().hex[:12]}")
    """Unique fanout record identifier."""

    parent_task_id: str = ""
    """task_id of the parent/aggregator node."""

    child_task_ids: List[str] = field(default_factory=list)
    """task_ids of child nodes in this fanout/fanin group."""

    edge_ids: List[str] = field(default_factory=list)
    """edge_ids created for this fanout/fanin."""

    direction: str = "fanout"
    """'fanout' (parent -> children) or 'fanin' (children -> parent)."""

    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "parent_task_id": self.parent_task_id,
            "child_task_ids": list(self.child_task_ids),
            "edge_ids": list(self.edge_ids),
            "direction": self.direction,
            "ts": self.ts,
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
        # PR-C: retry / fallback / fanout lineage ring buffers
        self._retry_records: Deque[RetryRecord] = deque(maxlen=self._RING_BUFFER_SIZE)
        self._fallback_records: Deque[FallbackRecord] = deque(maxlen=self._RING_BUFFER_SIZE)
        self._fanout_records: Deque[FanoutRecord] = deque(maxlen=self._RING_BUFFER_SIZE)

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

    def register_node_raw(
        self,
        task_id: str,
        *,
        tool_name: str = "",
        trace_id: str = "",
        session_id: str = "",
        device_id: str = "",
        contributor: "WorkflowContributorKind" = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        """Convenience wrapper: build a ``GraphNode`` from raw fields and register it.

        Stage 10: Added to allow lightweight callers (e.g. WakeRouter) to register
        a task-graph node without importing or constructing ``GraphNode`` directly.
        Idempotent: if a node for *task_id* already exists, the existing node is
        returned unchanged.

        Args:
            task_id:     Unique task identifier.
            tool_name:   Tool / command / event type name.
            trace_id:    Distributed trace id.
            session_id:  Session correlation id.
            device_id:   Target device id (empty = unassigned).
            contributor: Which orchestration layer is registering the node.
            metadata:    Optional dict of extra metadata.

        Returns:
            The registered (or pre-existing) ``GraphNode``.
        """
        if contributor is None:
            contributor = WorkflowContributorKind.UNKNOWN
        node = GraphNode(
            task_id=task_id,
            trace_id=trace_id,
            session_id=session_id,
            tool_name=tool_name,
            device_id=device_id,
            state=GraphNodeState.QUEUED,
            contributor=contributor,
            metadata=dict(metadata or {}),
        )
        return self.register_node(node)

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
        # Only overwrite contributor when explicitly provided (not default UNKNOWN)
        if contributor != WorkflowContributorKind.UNKNOWN:
            node.contributor = contributor

        if new_state == GraphNodeState.DISPATCH:
            node.dispatch_at = now
            self._add_dispatch_edge(node, transport_path=transport_path)
        elif new_state == GraphNodeState.RUNNING:
            node.running_at = now
        elif new_state == GraphNodeState.RESULT:
            node.result_at = now
        elif new_state == GraphNodeState.PARTIAL_RESULT:
            node.result_at = now
        elif new_state in (
            GraphNodeState.COMPLETED,
            GraphNodeState.FAILED,
            GraphNodeState.CANCELLED,
            GraphNodeState.DEGRADED,
        ):
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

    # ── PR-C: CanonicalTask integration ─────────────────────────────────────

    def register_canonical_task(
        self,
        canonical_task: Any,
        *,
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> GraphNode:
        """Map a ``CanonicalTask`` entity to a ``GraphNode`` and register it.

        Reads ``task_id``, ``trace_id``, ``session_id``, ``tool_name``,
        ``lifecycle``, and routing fields from the CanonicalTask using
        ``getattr`` so that both dataclass and Pydantic forms are supported.

        Args:
            canonical_task: A ``CanonicalTask`` instance (or compatible object).
            contributor:    Orchestration layer registering the task.

        Returns:
            The registered (or pre-existing) ``GraphNode``.
        """
        task_id = getattr(canonical_task, "task_id", "") or ""
        trace_id = getattr(canonical_task, "trace_id", "") or ""
        session_id = getattr(canonical_task, "session_id", "") or ""

        intent = getattr(canonical_task, "intent", None)
        # TaskIntent uses 'requested_action' as the action/tool field.
        # Fall back from tool_name → requested_action to handle both
        # TaskEnvelope-like objects and proper CanonicalTask instances.
        tool_name = ""
        if intent is not None:
            tool_name = (
                getattr(intent, "tool_name", "") or
                getattr(intent, "requested_action", "") or
                ""
            )

        routing = getattr(canonical_task, "routing", None)
        device_id = getattr(routing, "selected_device_id", "") or "" if routing else ""

        # Map CanonicalTask lifecycle → GraphNodeState
        lifecycle_val = getattr(canonical_task, "lifecycle", None)
        lifecycle_str = lifecycle_val.value if hasattr(lifecycle_val, "value") else str(lifecycle_val)
        _lc_map = {
            "created":    GraphNodeState.QUEUED,
            "admitted":   GraphNodeState.ADMITTED,
            "planned":    GraphNodeState.PLANNED,
            "routed":     GraphNodeState.ROUTED,
            "dispatched": GraphNodeState.DISPATCH,
            "running":    GraphNodeState.RUNNING,
            "completed":  GraphNodeState.COMPLETED,
            "failed":     GraphNodeState.FAILED,
            "cancelled":  GraphNodeState.CANCELLED,
            "degraded":   GraphNodeState.DEGRADED,
        }
        initial_state = _lc_map.get(lifecycle_str, GraphNodeState.QUEUED)

        if not task_id:
            logger.warning(
                "register_canonical_task: CanonicalTask has no task_id; skipping."
            )
            task_id = f"ctask_{uuid.uuid4().hex[:12]}"

        # Check for existing node first (idempotent)
        existing = self._nodes.get(task_id)
        if existing is not None:
            return existing

        node = GraphNode(
            task_id=task_id,
            trace_id=trace_id,
            session_id=session_id,
            tool_name=tool_name,
            device_id=device_id,
            state=initial_state,
            contributor=contributor,
        )
        return self.register_node(node)

    # ── PR-C: Retry / Fallback / Fanout / Fanin ──────────────────────────────

    def register_retry(
        self,
        original_task_id: str,
        retry_task_id: str,
        *,
        attempt_number: int = 1,
        reason: str = "",
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> RetryRecord:
        """Record a retry relation between an original node and a retry node.

        Creates a ``retry_edge`` from the original node to the retry node and
        appends a ``RetryRecord`` to the observability ring buffer.  Both nodes
        must be registered before calling this method; if either is absent a
        warning is logged and the record is still created (for observability).

        Args:
            original_task_id: task_id of the node that failed or was retried.
            retry_task_id:    task_id of the new retry attempt node.
            attempt_number:   Monotonically increasing retry counter (1-based).
            reason:           Human-readable retry reason.
            contributor:      Orchestration layer registering the retry.

        Returns:
            The created ``RetryRecord``.
        """
        original_node = self._nodes.get(original_task_id)
        retry_node = self._nodes.get(retry_task_id)

        if original_node is None:
            logger.warning(
                "task_graph_runtime | register_retry: original_task_id=%s not found",
                original_task_id,
            )
        if retry_node is None:
            logger.warning(
                "task_graph_runtime | register_retry: retry_task_id=%s not found",
                retry_task_id,
            )

        src_node_id = original_node.node_id if original_node else original_task_id
        tgt_node_id = retry_node.node_id if retry_node else retry_task_id

        edge = GraphEdge(
            kind=GraphEdgeKind.RETRY,
            source_node_id=src_node_id,
            target_node_id=tgt_node_id,
            metadata={
                "original_task_id": original_task_id,
                "retry_task_id": retry_task_id,
                "attempt_number": attempt_number,
                "reason": reason,
            },
        )
        self.register_edge(edge)

        record = RetryRecord(
            original_task_id=original_task_id,
            retry_task_id=retry_task_id,
            edge_id=edge.edge_id,
            attempt_number=attempt_number,
            reason=reason,
        )
        self._retry_records.append(record)
        logger.info(
            "task_graph_runtime | retry_registered original=%s retry=%s attempt=%d",
            original_task_id, retry_task_id, attempt_number,
        )
        return record

    def register_fallback(
        self,
        primary_task_id: str,
        fallback_task_id: str,
        *,
        reason: str = "",
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> FallbackRecord:
        """Record a fallback relation between a primary node and a fallback node.

        Creates a ``fallback_edge`` from the primary node to the fallback node
        and appends a ``FallbackRecord`` to the observability ring buffer.

        Args:
            primary_task_id:  task_id of the primary node that triggered fallback.
            fallback_task_id: task_id of the fallback execution node.
            reason:           Human-readable fallback reason.
            contributor:      Orchestration layer registering the fallback.

        Returns:
            The created ``FallbackRecord``.
        """
        primary_node = self._nodes.get(primary_task_id)
        fallback_node = self._nodes.get(fallback_task_id)

        if primary_node is None:
            logger.warning(
                "task_graph_runtime | register_fallback: primary_task_id=%s not found",
                primary_task_id,
            )
        if fallback_node is None:
            logger.warning(
                "task_graph_runtime | register_fallback: fallback_task_id=%s not found",
                fallback_task_id,
            )

        src_node_id = primary_node.node_id if primary_node else primary_task_id
        tgt_node_id = fallback_node.node_id if fallback_node else fallback_task_id

        edge = GraphEdge(
            kind=GraphEdgeKind.FALLBACK,
            source_node_id=src_node_id,
            target_node_id=tgt_node_id,
            metadata={
                "primary_task_id": primary_task_id,
                "fallback_task_id": fallback_task_id,
                "reason": reason,
            },
        )
        self.register_edge(edge)

        record = FallbackRecord(
            primary_task_id=primary_task_id,
            fallback_task_id=fallback_task_id,
            edge_id=edge.edge_id,
            reason=reason,
        )
        self._fallback_records.append(record)
        logger.info(
            "task_graph_runtime | fallback_registered primary=%s fallback=%s",
            primary_task_id, fallback_task_id,
        )
        return record

    def register_fanout(
        self,
        parent_task_id: str,
        child_task_ids: List[str],
        *,
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> FanoutRecord:
        """Register a multi-target fanout from one parent to multiple children.

        Creates a ``fanout_edge`` from the parent node to each child node and
        appends a ``FanoutRecord`` to the observability ring buffer.

        Args:
            parent_task_id: task_id of the parent (dispatcher) node.
            child_task_ids: task_ids of the parallel child execution nodes.
            contributor:    Orchestration layer registering the fanout.

        Returns:
            The created ``FanoutRecord``.
        """
        parent_node = self._nodes.get(parent_task_id)
        if parent_node is None:
            logger.warning(
                "task_graph_runtime | register_fanout: parent_task_id=%s not found",
                parent_task_id,
            )

        src_node_id = parent_node.node_id if parent_node else parent_task_id
        edge_ids: List[str] = []

        for child_task_id in child_task_ids:
            child_node = self._nodes.get(child_task_id)
            tgt_node_id = child_node.node_id if child_node else child_task_id
            edge = GraphEdge(
                kind=GraphEdgeKind.FANOUT,
                source_node_id=src_node_id,
                target_node_id=tgt_node_id,
                metadata={
                    "parent_task_id": parent_task_id,
                    "child_task_id": child_task_id,
                },
            )
            self.register_edge(edge)
            edge_ids.append(edge.edge_id)

        record = FanoutRecord(
            parent_task_id=parent_task_id,
            child_task_ids=list(child_task_ids),
            edge_ids=edge_ids,
            direction="fanout",
        )
        self._fanout_records.append(record)
        logger.info(
            "task_graph_runtime | fanout_registered parent=%s children=%d",
            parent_task_id, len(child_task_ids),
        )
        return record

    def register_fanin(
        self,
        child_task_ids: List[str],
        aggregator_task_id: str,
        *,
        contributor: WorkflowContributorKind = WorkflowContributorKind.UNKNOWN,
    ) -> FanoutRecord:
        """Register a multi-target fanin from multiple children to one aggregator.

        Creates a ``fanin_edge`` from each child node to the aggregator node
        and appends a ``FanoutRecord`` (direction='fanin') to the ring buffer.

        Args:
            child_task_ids:      task_ids of the parallel child nodes.
            aggregator_task_id:  task_id of the aggregator (collector) node.
            contributor:         Orchestration layer registering the fanin.

        Returns:
            The created ``FanoutRecord`` (with direction='fanin').
        """
        agg_node = self._nodes.get(aggregator_task_id)
        if agg_node is None:
            logger.warning(
                "task_graph_runtime | register_fanin: aggregator_task_id=%s not found",
                aggregator_task_id,
            )

        tgt_node_id = agg_node.node_id if agg_node else aggregator_task_id
        edge_ids: List[str] = []

        for child_task_id in child_task_ids:
            child_node = self._nodes.get(child_task_id)
            src_node_id = child_node.node_id if child_node else child_task_id
            edge = GraphEdge(
                kind=GraphEdgeKind.FANIN,
                source_node_id=src_node_id,
                target_node_id=tgt_node_id,
                metadata={
                    "child_task_id": child_task_id,
                    "aggregator_task_id": aggregator_task_id,
                },
            )
            self.register_edge(edge)
            edge_ids.append(edge.edge_id)

        record = FanoutRecord(
            parent_task_id=aggregator_task_id,
            child_task_ids=list(child_task_ids),
            edge_ids=edge_ids,
            direction="fanin",
        )
        self._fanout_records.append(record)
        logger.info(
            "task_graph_runtime | fanin_registered aggregator=%s children=%d",
            aggregator_task_id, len(child_task_ids),
        )
        return record

    # ── PR-C: Lineage query helpers ───────────────────────────────────────────

    def get_retry_lineage(self, task_id: str) -> List[RetryRecord]:
        """Return all retry records involving ``task_id`` (as original or retry).

        Records are returned in insertion order.
        """
        return [
            r for r in self._retry_records
            if r.original_task_id == task_id or r.retry_task_id == task_id
        ]

    def get_fallback_lineage(self, task_id: str) -> List[FallbackRecord]:
        """Return all fallback records involving ``task_id`` (as primary or fallback).

        Records are returned in insertion order.
        """
        return [
            r for r in self._fallback_records
            if r.primary_task_id == task_id or r.fallback_task_id == task_id
        ]

    def get_fanout_children(self, parent_task_id: str) -> List[str]:
        """Return task_ids of all direct fanout children for ``parent_task_id``."""
        children: List[str] = []
        for r in self._fanout_records:
            if r.direction == "fanout" and r.parent_task_id == parent_task_id:
                children.extend(r.child_task_ids)
        return children

    def get_fanin_parents(self, aggregator_task_id: str) -> List[str]:
        """Return task_ids of all fanin children for ``aggregator_task_id``."""
        parents: List[str] = []
        for r in self._fanout_records:
            if r.direction == "fanin" and r.parent_task_id == aggregator_task_id:
                parents.extend(r.child_task_ids)
        return parents

    def get_retry_log(self) -> Deque[RetryRecord]:
        """Return the internal retry ring buffer."""
        return self._retry_records

    def get_fallback_log(self) -> Deque[FallbackRecord]:
        """Return the internal fallback ring buffer."""
        return self._fallback_records

    def get_fanout_log(self) -> Deque[FanoutRecord]:
        """Return the internal fanout/fanin ring buffer."""
        return self._fanout_records

    # ── Workflow projection adapter ────────────────────────────────────────── ──────────────────────────────────────────

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
            total_retry_records=len(self._retry_records),
            total_fallback_records=len(self._fallback_records),
            total_fanout_records=len(self._fanout_records),
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
        "pending":       GraphNodeState.QUEUED,
        "queued":        GraphNodeState.QUEUED,
        "admitted":      GraphNodeState.ADMITTED,
        "planned":       GraphNodeState.PLANNED,
        "routed":        GraphNodeState.ROUTED,
        "running":       GraphNodeState.RUNNING,
        "done":          GraphNodeState.COMPLETED,
        "completed":     GraphNodeState.COMPLETED,
        "failed":        GraphNodeState.FAILED,
        "skipped":       GraphNodeState.FAILED,
        "cancelled":     GraphNodeState.CANCELLED,
        "interrupted":   GraphNodeState.FAILED,
        "dispatch":      GraphNodeState.DISPATCH,
        "dispatched":    GraphNodeState.DISPATCH,
        "result":        GraphNodeState.RESULT,
        "partial_result": GraphNodeState.PARTIAL_RESULT,
        "degraded":      GraphNodeState.DEGRADED,
        "replayed":      GraphNodeState.REPLAYED,
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
