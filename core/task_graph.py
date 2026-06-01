"""
core/task_graph.py
==================
PR-5: Task DAG Orchestration Engine

Defines a general-purpose, dependency-graph-based task execution engine
that supports:
  - Parallel execution of independent nodes
  - Per-node retry policy with configurable back-off
  - Partial rollback / recovery (failed branches can be skipped while
    independent branches continue)
  - Node-level lifecycle events (pending→running→done/failed/skipped)
  - trace_id / runtime_session_id propagation into every node execution

Usage example::

    from core.task_graph import TaskGraph, TaskNode, NodeStatus

    async def my_handler(node: TaskNode, ctx: dict) -> dict:
        return {"result": "ok"}

    graph = TaskGraph(trace_id="abc123")
    n1 = graph.add_node("fetch_data",  handler=my_handler)
    n2 = graph.add_node("process",     handler=my_handler, depends_on=[n1.node_id])
    n3 = graph.add_node("save_result", handler=my_handler, depends_on=[n2.node_id])
    n4 = graph.add_node("notify",      handler=my_handler, depends_on=[n1.node_id])

    result = await graph.execute(context={"session_id": "s1"})

Design notes
------------
- ``TaskGraph`` is *not* a replacement for the existing ``DAGScheduler`` in
  ``core/orchestrator_engine.py``, which operates on ``SubTask`` objects from
  an LLM-driven decomposition.  Instead it is a lower-level, reusable engine
  that any orchestration layer can delegate to.
- Backward-compatible: existing callers are never forced to use this module.
  If compilation into a ``TaskGraph`` fails, callers fall back to their own
  linear execution path and emit a warning.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid
from collections import defaultdict, deque
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.TaskGraph")

# PR-AIPV3-DAG: AIP v3 unified message models for cross-device task dispatch
_AIPV3_AVAILABLE = False
try:
    from core.schemas.aip_v3 import TaskAssignMsg, TaskResultMsg, MsgType  # noqa: PLC0415
    _AIPV3_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class NodeStatus(str, Enum):
    """Lifecycle states for a single DAG node."""
    PENDING    = "pending"
    RUNNING    = "running"
    DONE       = "done"
    FAILED     = "failed"
    SKIPPED    = "skipped"
    CANCELLED  = "cancelled"   # Block-4: cancel signal received
    INTERRUPTED = "interrupted"  # Block-4: immediate abort signal


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RetryPolicy:
    """Per-node retry configuration."""

    max_retries: int = 0
    """Maximum number of retry attempts after the first failure (0 = no retries)."""

    retry_delay_seconds: float = 1.0
    """Seconds to wait between retry attempts."""

    backoff_multiplier: float = 1.0
    """Multiply ``retry_delay_seconds`` by this factor on each subsequent retry."""


@dataclasses.dataclass
class TaskNode:
    """A single node (task) in the execution DAG.

    Attributes:
        node_id:       Unique identifier within the graph.
        description:   Human-readable description of the task.
        depends_on:    IDs of nodes that must reach ``DONE`` before this node starts.
        device_id:     Target device for this task (empty string = unassigned).
        status:        Current lifecycle status.
        handler:       Async callable ``(node, ctx) -> dict`` that performs the work.
        retry_policy:  Retry configuration for this node.
        rollback:      Optional async callable ``(node, ctx)`` to undo side-effects.
        result:        Output dict produced by the handler (populated after execution).
        error:         Error message if status is FAILED.
        attempt:       Number of execution attempts made (1-based).
        started_at:    Unix timestamp when the node began executing.
        completed_at:  Unix timestamp when the node finished.
    """

    node_id: str = dataclasses.field(
        default_factory=lambda: f"node_{uuid.uuid4().hex[:8]}"
    )
    description: str = ""
    depends_on: List[str] = dataclasses.field(default_factory=list)
    device_id: str = ""
    status: NodeStatus = NodeStatus.PENDING

    handler: Optional[
        Callable[["TaskNode", Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
    ] = dataclasses.field(default=None, repr=False)

    retry_policy: RetryPolicy = dataclasses.field(default_factory=RetryPolicy)

    rollback: Optional[
        Callable[["TaskNode", Dict[str, Any]], Coroutine[Any, Any, None]]
    ] = dataclasses.field(default=None, repr=False)

    result: Optional[Dict[str, Any]] = dataclasses.field(default=None)
    error: str = ""
    attempt: int = 0
    started_at: Optional[float] = dataclasses.field(default=None)
    completed_at: Optional[float] = dataclasses.field(default=None)


@dataclasses.dataclass
class TaskEdge:
    """A directed edge between two nodes in the DAG.

    Attributes:
        from_node:  ID of the source node.
        to_node:    ID of the destination node.
        condition:  Optional sync predicate ``(from_node: TaskNode) -> bool``.
                    If provided and returns ``False``, the destination node is
                    skipped instead of executed.
    """

    from_node: str
    to_node: str
    condition: Optional[Callable[["TaskNode"], bool]] = dataclasses.field(
        default=None, repr=False
    )


# ---------------------------------------------------------------------------
# Graph execution result
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class GraphExecutionResult:
    """Summary returned by :meth:`TaskGraph.execute`."""

    graph_id: str
    trace_id: str
    runtime_session_id: str

    total_nodes: int = 0
    done_nodes: int = 0
    failed_nodes: int = 0
    skipped_nodes: int = 0

    success: bool = False
    error: str = ""
    elapsed_ms: float = 0.0

    node_results: Dict[str, Optional[Dict[str, Any]]] = dataclasses.field(
        default_factory=dict
    )
    node_errors: Dict[str, str] = dataclasses.field(default_factory=dict)
    node_statuses: Dict[str, str] = dataclasses.field(default_factory=dict)


# ---------------------------------------------------------------------------
# TaskGraph
# ---------------------------------------------------------------------------


class TaskGraph:
    """Directed Acyclic Graph execution engine.

    Thread-safe for a single ``await graph.execute(...)`` call.  Do *not*
    call ``execute`` concurrently on the same instance.

    Args:
        trace_id:            Trace identifier propagated into every node
                             execution context.
        runtime_session_id:  Session identifier propagated similarly.
        graph_id:            Optional stable identifier for this graph.
    """

    def __init__(
        self,
        trace_id: str = "",
        runtime_session_id: str = "",
        graph_id: str = "",
    ) -> None:
        self.graph_id: str = graph_id or f"dag_{uuid.uuid4().hex[:10]}"
        self.trace_id: str = trace_id or uuid.uuid4().hex
        self.runtime_session_id: str = runtime_session_id or ""

        self._nodes: Dict[str, TaskNode] = {}
        self._edges: List[TaskEdge] = []

        # Adjacency: successor_id → list of predecessor_ids (built at execute time)
        self._predecessors: Dict[str, List[str]] = defaultdict(list)
        # Adjacency: predecessor_id → list of (successor_id, condition)
        self._successors: Dict[str, List[TaskEdge]] = defaultdict(list)

        # Block-4: cancellation flag
        self._cancel_requested: bool = False
        self._interrupt_requested: bool = False

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def add_node(
        self,
        description: str,
        *,
        node_id: Optional[str] = None,
        depends_on: Optional[List[str]] = None,
        device_id: str = "",
        handler: Optional[
            Callable[["TaskNode", Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
        ] = None,
        retry_policy: Optional[RetryPolicy] = None,
        rollback: Optional[
            Callable[["TaskNode", Dict[str, Any]], Coroutine[Any, Any, None]]
        ] = None,
    ) -> TaskNode:
        """Add a node to the graph and return it.

        Args:
            description:   Human-readable name / description.
            node_id:       Explicit ID (auto-generated if omitted).
            depends_on:    List of prerequisite node IDs.
            device_id:     Target device (empty = unassigned).
            handler:       Async worker coroutine.
            retry_policy:  Per-node retry configuration.
            rollback:      Optional rollback coroutine.

        Returns:
            The newly created :class:`TaskNode`.
        """
        node = TaskNode(
            node_id=node_id or f"node_{uuid.uuid4().hex[:8]}",
            description=description,
            depends_on=list(depends_on or []),
            device_id=device_id,
            handler=handler,
            retry_policy=retry_policy or RetryPolicy(),
            rollback=rollback,
        )
        self._nodes[node.node_id] = node
        return node

    def add_edge(
        self,
        from_node_id: str,
        to_node_id: str,
        condition: Optional[Callable[["TaskNode"], bool]] = None,
    ) -> TaskEdge:
        """Add an explicit directed edge (dependency).

        Usually dependencies are declared via ``depends_on`` in
        :meth:`add_node`; this method allows attaching a *condition* to an
        existing dependency.

        Args:
            from_node_id:  Source node (must already exist).
            to_node_id:    Destination node (must already exist).
            condition:     Optional predicate evaluated on the source node.

        Returns:
            The created :class:`TaskEdge`.
        """
        if from_node_id not in self._nodes:
            raise ValueError(f"Source node '{from_node_id}' not in graph")
        if to_node_id not in self._nodes:
            raise ValueError(f"Destination node '{to_node_id}' not in graph")
        edge = TaskEdge(from_node=from_node_id, to_node=to_node_id, condition=condition)
        self._edges.append(edge)
        return edge

    # ------------------------------------------------------------------
    # Block-4: Cancellation / interrupt
    # ------------------------------------------------------------------

    def cancel(self, reason: str = "") -> None:
        """Request graceful cancellation of the running graph.

        After this is called, no new nodes will be started and any nodes
        currently pending will be marked :attr:`NodeStatus.CANCELLED`.
        Already-running nodes are allowed to finish naturally.

        Args:
            reason:  Human-readable reason for cancellation.
        """
        self._cancel_requested = True
        logger.info(
            "TaskGraph '%s' | cancel requested reason=%r trace_id=%s",
            self.graph_id,
            reason,
            self.trace_id,
        )
        self._emit_cancel_event("cancel", reason)

    def interrupt(self, reason: str = "") -> None:
        """Request immediate interruption of the running graph.

        After this is called all pending nodes are marked
        :attr:`NodeStatus.INTERRUPTED` and execution halts at the next
        scheduling opportunity.

        Args:
            reason:  Human-readable reason for interruption.
        """
        self._interrupt_requested = True
        self._cancel_requested = True  # also stop new nodes
        logger.info(
            "TaskGraph '%s' | interrupt requested reason=%r trace_id=%s",
            self.graph_id,
            reason,
            self.trace_id,
        )
        self._emit_cancel_event("interrupt", reason)

    # PR-AIPV3-DAG: AIP v3 message emission for task lifecycle

    def _emit_aip_v3_task_assign(self, node: TaskNode) -> None:
        """Emit AIP v3 TASK_ASSIGN message before node execution.

        Best-effort: published via NATS if connected, otherwise logged only.
        This makes DAG node dispatch observable by any AIP v3 consumer.
        """
        if not _AIPV3_AVAILABLE:
            return
        try:
            import asyncio
            msg = TaskAssignMsg(
                device_id=node.device_id or "local",
                task_id=f"{self.graph_id}:{node.node_id}",
                action=node.description or "execute",
                params={"node_id": node.node_id, "graph_id": self.graph_id},
                trace_id=self.trace_id,
                session_id=self.runtime_session_id,
            )
            from core.nats_bus import get_nats_bus  # noqa: PLC0415
            nats = get_nats_bus()
            if nats.is_connected():
                asyncio.get_running_loop().create_task(nats.publish_task_assign(msg))
            else:
                # Log the AIP v3 message for local debugging / tracing
                logger.debug("AIPV3-DAG TASK_ASSIGN: %s", msg.model_dump_json(exclude_none=True))
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    def _emit_aip_v3_task_result(self, node: TaskNode) -> None:
        """Emit AIP v3 TASK_RESULT message after node completion.

        Best-effort: published via NATS if connected, otherwise logged only.
        """
        if not _AIPV3_AVAILABLE:
            return
        try:
            import asyncio
            status_map = {
                NodeStatus.DONE: "completed",
                NodeStatus.FAILED: "failed",
                NodeStatus.SKIPPED: "skipped",
                NodeStatus.CANCELLED: "cancelled",
                NodeStatus.INTERRUPTED: "interrupted",
            }
            msg = TaskResultMsg(
                device_id=node.device_id or "local",
                task_id=f"{self.graph_id}:{node.node_id}",
                status=status_map.get(node.status, str(node.status)),
                result=node.result if isinstance(node.result, dict) else {"value": node.result},
                error=node.error or "",
                duration_ms=int((node.completed_at - node.started_at) * 1000) if node.completed_at and node.started_at else 0,
                trace_id=self.trace_id,
                session_id=self.runtime_session_id,
            )
            from core.nats_bus import get_nats_bus  # noqa: PLC0415
            nats = get_nats_bus()
            if nats.is_connected():
                asyncio.get_running_loop().create_task(nats.publish_task_result(msg))
            else:
                logger.debug("AIPV3-DAG TASK_RESULT: %s", msg.model_dump_json(exclude_none=True))
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    def _emit_cancel_event(self, verb: str, reason: str) -> None:
        """Best-effort StateEventBus emission for cancel/interrupt."""
        try:
            from core.state_event_bus import get_state_event_bus, StateEventType
            bus = get_state_event_bus()
            event_type = getattr(StateEventType, "TASK_FAILED", StateEventType.GENERIC)
            bus.publish(
                event_type,
                source="task_graph",
                payload={
                    "event": f"task_graph.{verb}",
                    "graph_id": self.graph_id,
                    "reason": reason,
                },
                trace_id=self.trace_id,
                runtime_session_id=self.runtime_session_id,
            )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ------------------------------------------------------------------
    # Topological utilities (internal)
    # ------------------------------------------------------------------

    def _build_adjacency(self) -> None:
        """Populate ``_predecessors`` / ``_successors`` from ``depends_on`` + edges."""
        self._predecessors = defaultdict(list)
        self._successors = defaultdict(list)

        # From node.depends_on declarations
        for node in self._nodes.values():
            for dep_id in node.depends_on:
                if dep_id not in self._nodes:
                    raise ValueError(
                        f"Node '{node.node_id}' depends_on unknown node '{dep_id}'"
                    )
                self._predecessors[node.node_id].append(dep_id)
                # Create an implicit edge (no condition) if not already present
                implicit = TaskEdge(from_node=dep_id, to_node=node.node_id)
                self._successors[dep_id].append(implicit)

        # From explicit edges (add from_node as predecessor of to_node if not already present
        # from the depends_on declarations above, to avoid double-counting in_degree)
        for edge in self._edges:
            existing_preds = self._predecessors.get(edge.to_node, [])
            if edge.from_node not in existing_preds:
                self._predecessors[edge.to_node].append(edge.from_node)
            self._successors[edge.from_node].append(edge)

    def topological_layers(self) -> List[List[str]]:
        """Return nodes grouped into parallel layers via Kahn's algorithm.

        Each layer contains nodes whose dependencies are all satisfied by
        earlier layers (so all nodes within a layer can run concurrently).

        Returns:
            Ordered list of layers; each layer is a list of node IDs.

        Raises:
            ValueError: if a cycle is detected.
        """
        self._build_adjacency()

        in_degree: Dict[str, int] = {nid: 0 for nid in self._nodes}
        for nid, preds in self._predecessors.items():
            # Deduplicate predecessors
            in_degree[nid] = len(set(preds))

        queue: deque[str] = deque(nid for nid, d in in_degree.items() if d == 0)
        layers: List[List[str]] = []
        visited = 0

        while queue:
            layer = list(queue)
            layers.append(layer)
            visited += len(layer)
            queue = deque()
            for nid in layer:
                seen: Set[str] = set()
                for edge in self._successors.get(nid, []):
                    succ = edge.to_node
                    if succ not in seen:
                        seen.add(succ)
                        in_degree[succ] -= 1
                        if in_degree[succ] == 0:
                            queue.append(succ)

        if visited < len(self._nodes):
            cycle_nodes = [nid for nid, d in in_degree.items() if d > 0]
            raise ValueError(
                f"TaskGraph '{self.graph_id}': cycle detected involving nodes "
                f"{cycle_nodes}"
            )
        return layers

    # ------------------------------------------------------------------
    # Lifecycle event helpers
    # ------------------------------------------------------------------

    def _emit_node_event(self, node: TaskNode, status: NodeStatus) -> None:
        """Best-effort lifecycle event emission for a node."""
        try:
            from integration.event_bus import event_bus, EventType
            et = getattr(EventType, "TASK_LIFECYCLE", None)
            if et is None:
                return
            event_bus.publish_sync(et, "task_graph", {
                "graph_id": self.graph_id,
                "node_id": node.node_id,
                "description": node.description,
                "device_id": node.device_id,
                "trace_id": self.trace_id,
                "runtime_session_id": self.runtime_session_id,
                "status": status.value,
                "attempt": node.attempt,
                "ts": time.time(),
            })
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # ------------------------------------------------------------------
    # Node execution (with retries)
    # ------------------------------------------------------------------

    async def _run_node(
        self,
        node: TaskNode,
        context: Dict[str, Any],
    ) -> None:
        """Execute a single node, honouring its retry policy.

        PR-AIPV3-DAG: Emits TASK_ASSIGN before execution and TASK_RESULT
        after completion so DAG node lifecycle is observable via AIP v3.

        Updates ``node.status``, ``node.result``, ``node.error``,
        ``node.started_at``, ``node.completed_at``, and ``node.attempt``
        in-place.
        """
        if node.status == NodeStatus.SKIPPED:
            return

        # Enrich context with trace information
        exec_ctx = {
            **context,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "graph_id": self.graph_id,
            "node_id": node.node_id,
            "device_id": node.device_id,
        }

        policy = node.retry_policy
        max_attempts = max(1, policy.max_retries + 1)
        delay = policy.retry_delay_seconds

        node.status = NodeStatus.RUNNING
        node.started_at = time.time()
        self._emit_node_event(node, NodeStatus.RUNNING)
        # PR-AIPV3-DAG: Emit TASK_ASSIGN AIP v3 message
        self._emit_aip_v3_task_assign(node)
        logger.info(
            "TaskGraph '%s' | node='%s' status=running trace_id=%s",
            self.graph_id, node.description or node.node_id, self.trace_id,
        )

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            node.attempt = attempt
            try:
                if node.handler is None:
                    node.result = {}
                else:
                    node.result = await node.handler(node, exec_ctx) or {}
                node.status = NodeStatus.DONE
                node.error = ""
                node.completed_at = time.time()
                self._emit_node_event(node, NodeStatus.DONE)
                # PR-AIPV3-DAG: Emit TASK_RESULT AIP v3 message
                self._emit_aip_v3_task_result(node)
                logger.info(
                    "TaskGraph '%s' | node='%s' status=done attempt=%d",
                    self.graph_id, node.description or node.node_id, attempt,
                )
                return
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                last_exc = exc
                logger.warning(
                    "TaskGraph '%s' | node='%s' attempt=%d/%d failed: %s",
                    self.graph_id,
                    node.description or node.node_id,
                    attempt,
                    max_attempts,
                    exc,
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay)
                    delay *= policy.backoff_multiplier

        # All attempts exhausted
        node.status = NodeStatus.FAILED
        node.error = str(last_exc)
        node.completed_at = time.time()
        self._emit_node_event(node, NodeStatus.FAILED)
        # PR-AIPV3-DAG: Emit TASK_RESULT with failed status
        self._emit_aip_v3_task_result(node)
        logger.error(
            "TaskGraph '%s' | node='%s' status=failed error=%r",
            self.graph_id, node.description or node.node_id, node.error,
        )

        # Attempt rollback if provided
        if node.rollback is not None:
            try:
                logger.info(
                    "TaskGraph '%s' | node='%s' running rollback",
                    self.graph_id, node.description or node.node_id,
                )
                await node.rollback(node, exec_ctx)
            except Exception as rb_exc:
                logger.warning(
                    "TaskGraph '%s' | node='%s' rollback raised: %s",
                    self.graph_id, node.description or node.node_id, rb_exc,
                )

    # ------------------------------------------------------------------
    # Main execution loop
    # ------------------------------------------------------------------

    async def execute(
        self,
        context: Optional[Dict[str, Any]] = None,
        *,
        continue_on_failure: bool = True,
        policy: Optional[Any] = None,
    ) -> GraphExecutionResult:
        """Execute the DAG.

        Nodes within the same topological layer are executed concurrently
        using ``asyncio.gather``.  A node is *skipped* if any of its direct
        predecessors failed (or were skipped) and ``continue_on_failure`` is
        ``True``; otherwise the graph halts on the first failure.

        Args:
            context:            Arbitrary key-value pairs propagated into
                                every handler invocation alongside trace/session IDs.
            continue_on_failure: When ``True`` (default), failed nodes cause
                                dependent nodes to be skipped; independent
                                branches continue.  When ``False``, the graph
                                stops after the first failed node.
            policy:             Optional :class:`~core.execution_policy.ExecutionPolicy`.
                                When supplied (PR-12):

                                - If ``policy_band`` is ``observe_only`` the
                                  entire graph is blocked and a failed result is
                                  returned immediately.
                                - Nodes with a non-empty ``device_id`` are
                                  treated as cross-device; if the policy has
                                  ``cross_device_allowed=False`` those nodes are
                                  skipped and a ``cross_device_not_allowed``
                                  marker is attached to the result.
                                - Policy decision details are logged for
                                  observability.

                                When ``None`` no enforcement is applied
                                (backward compatible).

        Returns:
            :class:`GraphExecutionResult` with a full status summary.
        """
        t0 = time.monotonic()
        ctx = dict(context or {})

        result = GraphExecutionResult(
            graph_id=self.graph_id,
            trace_id=self.trace_id,
            runtime_session_id=self.runtime_session_id,
            total_nodes=len(self._nodes),
        )

        if not self._nodes:
            result.success = True
            result.elapsed_ms = (time.monotonic() - t0) * 1000
            return result

        # ── PR-12: Policy enforcement (additive, non-breaking) ─────────────────
        if policy is not None:
            _policy_block_result = self._apply_policy_to_graph(policy, result, t0)
            if _policy_block_result is not None:
                return _policy_block_result

        # --- Build adjacency and compute execution order ---
        try:
            layers = self.topological_layers()
        except ValueError as exc:
            result.error = str(exc)
            result.success = False
            result.elapsed_ms = (time.monotonic() - t0) * 1000
            logger.error("TaskGraph '%s' build failed: %s", self.graph_id, exc)
            return result

        logger.info(
            "TaskGraph '%s' executing: %d nodes / %d layers | trace_id=%s",
            self.graph_id, len(self._nodes), len(layers), self.trace_id,
        )

        halt = False

        for layer_idx, layer_node_ids in enumerate(layers):
            if halt:
                # Mark remaining nodes as skipped / cancelled
                for nid in layer_node_ids:
                    node = self._nodes[nid]
                    if node.status == NodeStatus.PENDING:
                        if self._cancel_requested:
                            new_status = (
                                NodeStatus.INTERRUPTED
                                if self._interrupt_requested
                                else NodeStatus.CANCELLED
                            )
                            node.status = new_status
                            node.error = "interrupted by graph.interrupt()" if self._interrupt_requested else "cancelled by graph.cancel()"
                            self._emit_node_event(node, new_status)
                        else:
                            node.status = NodeStatus.SKIPPED
                            self._emit_node_event(node, NodeStatus.SKIPPED)
                continue

            # Block-4: check cancel/interrupt at each layer boundary
            if self._cancel_requested:
                cancel_status = (
                    NodeStatus.INTERRUPTED
                    if self._interrupt_requested
                    else NodeStatus.CANCELLED
                )
                for nid in layer_node_ids:
                    node = self._nodes[nid]
                    if node.status == NodeStatus.PENDING:
                        node.status = cancel_status
                        node.error = f"graph {cancel_status.value}"
                        self._emit_node_event(node, cancel_status)
                halt = True
                continue

            # Determine which nodes in this layer can run vs. must be skipped
            runnable: List[TaskNode] = []
            for nid in layer_node_ids:
                node = self._nodes[nid]

                # Check whether any predecessor failed / was skipped
                preds = list(dict.fromkeys(self._predecessors.get(nid, [])))
                blocking_pred: Optional[TaskNode] = None
                skip_due_to_condition = False

                for pred_id in preds:
                    pred_node = self._nodes[pred_id]
                    if pred_node.status in (NodeStatus.FAILED, NodeStatus.SKIPPED):
                        blocking_pred = pred_node
                        break
                    # Evaluate edge condition if present
                    for edge in self._successors.get(pred_id, []):
                        if edge.to_node == nid and edge.condition is not None:
                            try:
                                if not edge.condition(pred_node):
                                    skip_due_to_condition = True
                            except Exception as exc:
                                logger.warning("Exception suppressed: %s", exc)

                if blocking_pred is not None or skip_due_to_condition:
                    node.status = NodeStatus.SKIPPED
                    node.error = (
                        f"predecessor '{blocking_pred.node_id}' "
                        f"in state '{blocking_pred.status}'"
                        if blocking_pred else "edge condition not satisfied"
                    )
                    self._emit_node_event(node, NodeStatus.SKIPPED)
                    logger.info(
                        "TaskGraph '%s' | node='%s' skipped: %s",
                        self.graph_id, node.description or nid, node.error,
                    )
                else:
                    runnable.append(node)

            # Run all runnable nodes in this layer concurrently
            if runnable:
                logger.info(
                    "TaskGraph '%s' | layer %d/%d: running %d node(s) concurrently",
                    self.graph_id, layer_idx + 1, len(layers), len(runnable),
                )
                await asyncio.gather(
                    *[self._run_node(n, ctx) for n in runnable],
                    return_exceptions=False,
                )

            # Post-layer: check for failures
            layer_failed = any(
                self._nodes[nid].status == NodeStatus.FAILED
                for nid in layer_node_ids
            )
            if layer_failed and not continue_on_failure:
                halt = True

        # --- Aggregate results ---
        for nid, node in self._nodes.items():
            result.node_results[nid] = node.result
            result.node_errors[nid] = node.error
            result.node_statuses[nid] = node.status.value

            if node.status == NodeStatus.DONE:
                result.done_nodes += 1
            elif node.status == NodeStatus.FAILED:
                result.failed_nodes += 1
            elif node.status in (NodeStatus.SKIPPED, NodeStatus.CANCELLED, NodeStatus.INTERRUPTED):
                result.skipped_nodes += 1

        result.success = result.failed_nodes == 0
        result.elapsed_ms = (time.monotonic() - t0) * 1000

        logger.info(
            "TaskGraph '%s' finished | done=%d failed=%d skipped=%d "
            "elapsed_ms=%.1f trace_id=%s",
            self.graph_id,
            result.done_nodes,
            result.failed_nodes,
            result.skipped_nodes,
            result.elapsed_ms,
            self.trace_id,
        )
        return result

    # ------------------------------------------------------------------
    # PR-12: Policy enforcement helpers
    # ------------------------------------------------------------------

    def _apply_policy_to_graph(
        self,
        policy: Any,
        result: "GraphExecutionResult",
        t0: float,
    ) -> "Optional[GraphExecutionResult]":
        """Apply execution policy guardrails to the graph before execution.

        Returns a completed :class:`GraphExecutionResult` when execution must
        be blocked entirely, or ``None`` if execution may proceed.

        Side effects when not blocking:
        - Cross-device nodes are skipped when ``cross_device_allowed=False``.
        - A policy decision is logged for every meaningful outcome.
        """
        try:
            from core.execution_policy.policy_guardrails import (
                check_side_effectful_execution,
                check_cross_device_expansion,
            )
            from core.execution_policy.policy_enforcement import emit_policy_decision

            # ── 1. Observe-only band blocks all side-effectful execution ──────
            side_effect_decision = check_side_effectful_execution(
                policy, is_side_effectful=True
            )
            emit_policy_decision(
                side_effect_decision,
                context={"graph_id": self.graph_id, "trace_id": self.trace_id},
            )
            if side_effect_decision.is_blocked:
                logger.info(
                    "TaskGraph '%s' | policy_blocked | band=%s | %s | trace_id=%s",
                    self.graph_id,
                    policy.policy_band.value if hasattr(policy, "policy_band") else "?",
                    side_effect_decision.reason,
                    self.trace_id,
                )
                result.success = False
                result.error = side_effect_decision.reason
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                # Mark all nodes as skipped
                for node in self._nodes.values():
                    node.status = NodeStatus.SKIPPED
                    node.error = "blocked_by_policy"
                    result.node_statuses[node.node_id] = NodeStatus.SKIPPED.value
                    result.node_errors[node.node_id] = node.error
                result.skipped_nodes = len(self._nodes)
                return result

            # ── 2. Confirmation required — block the graph (hold) ─────────────
            if side_effect_decision.needs_confirmation:
                logger.info(
                    "TaskGraph '%s' | confirmation_required | trace_id=%s",
                    self.graph_id,
                    self.trace_id,
                )
                result.success = False
                result.error = "confirmation_required: " + side_effect_decision.reason
                result.elapsed_ms = (time.monotonic() - t0) * 1000
                for node in self._nodes.values():
                    node.status = NodeStatus.SKIPPED
                    node.error = "confirmation_required"
                    result.node_statuses[node.node_id] = NodeStatus.SKIPPED.value
                    result.node_errors[node.node_id] = node.error
                result.skipped_nodes = len(self._nodes)
                return result

            # ── 3. Cross-device check — skip non-local nodes if disallowed ────
            cross_device_decision = check_cross_device_expansion(policy)
            if not cross_device_decision.is_allowed:
                cross_device_nodes = [
                    n for n in self._nodes.values() if n.device_id and n.device_id != "local"
                ]
                if cross_device_nodes:
                    emit_policy_decision(
                        cross_device_decision,
                        context={
                            "graph_id": self.graph_id,
                            "trace_id": self.trace_id,
                            "cross_device_node_count": len(cross_device_nodes),
                        },
                    )
                    logger.info(
                        "TaskGraph '%s' | cross_device_not_allowed | "
                        "skipping %d cross-device nodes | trace_id=%s",
                        self.graph_id,
                        len(cross_device_nodes),
                        self.trace_id,
                    )
                    for node in cross_device_nodes:
                        node.status = NodeStatus.SKIPPED
                        node.error = "cross_device_not_allowed"
            return None  # execution may proceed (possibly with some nodes pre-skipped)

        except Exception as exc:
            # Never block execution because of a guardrail error
            logger.debug(
                "TaskGraph '%s' policy guardrails error (non-fatal): %s",
                self.graph_id,
                exc,
            )
            return None

    # ------------------------------------------------------------------
    # Ready-queue helper (for external polling / incremental execution)
    # ------------------------------------------------------------------

    def ready_nodes(self) -> List[TaskNode]:
        """Return nodes that are PENDING and have all predecessors DONE.

        Useful for external schedulers that want to drive execution
        step-by-step rather than calling :meth:`execute`.
        """
        self._build_adjacency()
        ready: List[TaskNode] = []
        for node in self._nodes.values():
            if node.status != NodeStatus.PENDING:
                continue
            preds = list(dict.fromkeys(self._predecessors.get(node.node_id, [])))
            if all(self._nodes[p].status == NodeStatus.DONE for p in preds):
                ready.append(node)
        return ready

    # ------------------------------------------------------------------
    # Snapshot / introspection
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable status snapshot of the graph."""
        return {
            "graph_id": self.graph_id,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "description": n.description,
                    "device_id": n.device_id,
                    "status": n.status.value,
                    "depends_on": n.depends_on,
                    "attempt": n.attempt,
                    "error": n.error,
                    "started_at": n.started_at,
                    "completed_at": n.completed_at,
                }
                for n in self._nodes.values()
            ],
        }


# ---------------------------------------------------------------------------
# Convenience factory: compile SubTask list → TaskGraph
# ---------------------------------------------------------------------------


def compile_subtasks_to_graph(
    subtasks: List[Any],
    *,
    trace_id: str = "",
    runtime_session_id: str = "",
    default_retry_policy: Optional[RetryPolicy] = None,
    node_handler: Optional[
        Callable[["TaskNode", Dict[str, Any]], Coroutine[Any, Any, Dict[str, Any]]]
    ] = None,
) -> TaskGraph:
    """Compile a list of :class:`~core.schemas.orchestration.SubTask` objects
    into a :class:`TaskGraph`.

    This is the bridge between the LLM-driven decomposition layer
    (``SubTask`` / ``DAGScheduler``) and the low-level execution engine.

    Args:
        subtasks:              List of SubTask objects (must have ``task_id``,
                               ``name``, ``description``, ``depends_on``,
                               ``device_id`` / ``device_type`` attributes).
        trace_id:              Trace ID to embed in the graph.
        runtime_session_id:    Session ID to embed in the graph.
        default_retry_policy:  Retry policy applied to every node unless the
                               subtask provides its own.
        node_handler:          Default handler coroutine to attach to every
                               node.  If ``None``, nodes will return ``{}``
                               when executed.

    Returns:
        A :class:`TaskGraph` ready for ``await graph.execute()``.

    Raises:
        ValueError: propagated from :meth:`TaskGraph.topological_layers` if
                    a cycle is detected.
    """
    graph = TaskGraph(trace_id=trace_id, runtime_session_id=runtime_session_id)
    policy = default_retry_policy or RetryPolicy()

    # First pass: add nodes
    id_map: Dict[str, str] = {}  # subtask.task_id → graph node_id
    name_map: Dict[str, str] = {}  # subtask.name → subtask.task_id
    for st in subtasks:
        st_id: str = getattr(st, "task_id", None) or str(uuid.uuid4().hex[:8])
        st_name: str = getattr(st, "name", st_id)
        name_map[st_name] = st_id

    for st in subtasks:
        st_id = getattr(st, "task_id", None) or str(uuid.uuid4().hex[:8])
        st_name = getattr(st, "name", st_id)
        st_desc = getattr(st, "description", st_name)
        st_device = getattr(st, "device_id", "") or getattr(st, "device_type", "") or ""

        node = graph.add_node(
            description=st_desc,
            node_id=st_id,
            device_id=st_device,
            handler=node_handler,
            retry_policy=policy,
        )
        id_map[st_id] = node.node_id

    # Second pass: resolve depends_on (may be names or IDs)
    for st in subtasks:
        st_id = getattr(st, "task_id", None) or str(uuid.uuid4().hex[:8])
        raw_deps: List[str] = list(getattr(st, "depends_on", []) or [])
        resolved: List[str] = []
        for dep in raw_deps:
            # Try direct ID lookup first
            if dep in graph._nodes:
                resolved.append(dep)
            elif dep in name_map:
                # name → task_id → node_id
                resolved.append(name_map[dep])
            # else: silently drop unresolvable dependency
        graph._nodes[st_id].depends_on = resolved

    return graph
