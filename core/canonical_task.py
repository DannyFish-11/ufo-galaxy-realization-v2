#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_task.py — PR-A: Canonical Task & Execution Spine
================================================================

**CanonicalTask — Unified Task Ontology**
-----------------------------------------
Establishes the single authoritative task *entity* for the Galaxy runtime.
``CanonicalTask`` is the task **ontology object** — it is NOT a transport
envelope.  It is distinct from :class:`~core.schemas.task_envelope.TaskEnvelope`
which is the *execution projection* of a canonical task.

Canonical layer hierarchy
--------------------------
::

    CanonicalTask         ← task ontology (this module)
        │
        │  project_to_task_envelope()
        ▼
    TaskEnvelope          ← execution projection / transport-ready contract
        │
        │  CommandRouter.route_envelope()
        ▼
    transport / executor  ← gateway substrate
        │
        │  ResultEnvelope
        ▼
    CanonicalTask.apply_result_envelope()  ← runtime/result update

Invariants
----------
1.  Every task entering the Galaxy runtime SHOULD be represented as a
    ``CanonicalTask`` before or at the point of dispatch.
2.  ``TaskEnvelope`` is derived FROM a ``CanonicalTask`` via
    :meth:`CanonicalTask.project_to_task_envelope`.
3.  ``ResultEnvelope`` flows back and updates the ``CanonicalTask`` via
    :meth:`CanonicalTask.apply_result_envelope`.
4.  ``CommandRouter.route_envelope()`` is the **sole** system-level dispatch
    spine.  ``CanonicalTask`` does NOT perform dispatch; it only produces
    envelopes that enter the router.
5.  Legacy orchestrators remain as facade/planner helpers; they may
    *contribute* to a ``CanonicalTask`` but MUST NOT dispatch outside the
    spine.

Public API
----------
Authority sentinels::

    CANONICAL_TASK_AUTHORITY
    CANONICAL_TASK_LAYER_POSITION
    CANONICAL_TASK_ONTOLOGY_VERSION
    CANONICAL_EXECUTION_SPINE_POLICY

Enumerations::

    TaskLifecycle
    TaskOrigin
    RemoteExecutionStyle
    FailureDomain

Dataclasses::

    TaskIdentity
    TaskIntent
    TaskPlanning
    TaskRouting
    TaskExecution
    TaskGraphRelations
    TaskResultSummary
    CanonicalTask
    CanonicalTaskRecord  (observability ring-buffer entry)
    CanonicalTaskSnapshot

Helpers::

    build_canonical_task(**kwargs) -> CanonicalTask
    project_to_task_envelope(task) -> TaskEnvelope
    apply_result_envelope(task, result_envelope) -> CanonicalTask
    get_canonical_task_runtime() -> CanonicalTaskRuntime
    reset_canonical_task_runtime()   # testing only
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalTask")

__all__ = [
    # Authority
    "CANONICAL_TASK_AUTHORITY",
    "CANONICAL_TASK_LAYER_POSITION",
    "CANONICAL_TASK_ONTOLOGY_VERSION",
    "CANONICAL_EXECUTION_SPINE_POLICY",
    # Enums
    "TaskLifecycle",
    "TaskOrigin",
    "RemoteExecutionStyle",
    "FailureDomain",
    # Sub-dataclasses
    "TaskIdentity",
    "TaskIntent",
    "TaskPlanning",
    "TaskRouting",
    "TaskExecution",
    "TaskGraphRelations",
    "TaskResultSummary",
    # Main entity
    "CanonicalTask",
    # Observability
    "CanonicalTaskRecord",
    "CanonicalTaskSnapshot",
    # Runtime
    "CanonicalTaskRuntime",
    # Helpers
    "build_canonical_task",
    "project_to_task_envelope",
    "apply_result_envelope",
    "get_canonical_task_runtime",
    "reset_canonical_task_runtime",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

CANONICAL_TASK_AUTHORITY: str = "CANONICAL_TASK_V1"
"""Sentinel: this module is the canonical task ontology authority for Galaxy.
Import to assert that a component operates on the canonical task layer."""

CANONICAL_TASK_LAYER_POSITION: int = 9
"""Layer position in the Galaxy architecture stack.
CanonicalTask sits above TaskEnvelope (execution projection) and
below the UI/operator surface layers."""

CANONICAL_TASK_ONTOLOGY_VERSION: str = "1.0"
"""Version of the CanonicalTask schema contract."""

CANONICAL_EXECUTION_SPINE_POLICY: str = (
    "REQUIRED: CanonicalTask → project_to_task_envelope() → "
    "CommandRouter.route_envelope() is the sole system-level dispatch spine; "
    "all legacy dispatch shortcuts must be registered in LegacyDispatchRegistry."
)
"""Policy: all system-level dispatch MUST flow through the canonical spine."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class TaskLifecycle(str, Enum):
    """Canonical lifecycle states for a CanonicalTask.

    The lifecycle progresses forward; some terminal states are final.
    """

    CREATED = "created"
    """Task object constructed, not yet admitted for execution."""

    ADMITTED = "admitted"
    """Task accepted for execution by the runtime authority."""

    PLANNED = "planned"
    """Execution plan (targets, transport, constraints) resolved."""

    ROUTED = "routed"
    """Routing decision made; effective path / transport selected."""

    DISPATCHED = "dispatched"
    """TaskEnvelope emitted and entered CommandRouter.route_envelope()."""

    RUNNING = "running"
    """Executor confirmed task is actively running on target."""

    COMPLETED = "completed"
    """Task completed successfully; result available."""

    FAILED = "failed"
    """Task failed; error_code and failure_domain populated."""

    CANCELLED = "cancelled"
    """Task was explicitly cancelled before or during execution."""

    DEGRADED = "degraded"
    """Task completed with degraded results (partial success / fallback used)."""


class TaskOrigin(str, Enum):
    """Origin of the task — how it entered the Galaxy runtime."""

    API_REQUEST = "api_request"
    """Originated from an HTTP/REST API call."""

    AI_INTENT = "ai_intent"
    """Originated from an AI agent intent / action resolution."""

    WORKFLOW_STEP = "workflow_step"
    """Originated as a step within a workflow execution."""

    ORCHESTRATOR_TASK = "orchestrator_task"
    """Originated from an orchestrator (galaxy/fusion/device)."""

    DEVICE_COMMAND = "device_command"
    """Originated as a direct device command."""

    MCP_TOOL_CALL = "mcp_tool_call"
    """Originated from an MCP tool call."""

    SKILL_INVOCATION = "skill_invocation"
    """Originated from a skill invocation."""

    SCHEDULER = "scheduler"
    """Originated from the task scheduler."""

    UNKNOWN = "unknown"
    """Origin not classified."""


class RemoteExecutionStyle(str, Enum):
    """Remote execution mode for cross-device tasks."""

    COMMAND_ONLY = "command_only"
    """Structured command/task dispatch to target device."""

    AGENT_RUNTIME = "agent_runtime"
    """Agent deploy + execute dispatch to target device."""

    LOCAL = "local"
    """Local execution on the host machine."""

    NONE = "none"
    """No remote execution; task is handled in-process."""


class FailureDomain(str, Enum):
    """Domain in which a task failure occurred."""

    ROUTING = "routing"
    """Failure occurred during routing / target selection."""

    TRANSPORT = "transport"
    """Failure occurred during transport (WebSocket/NATS/relay)."""

    EXECUTION = "execution"
    """Failure occurred during execution on the target."""

    POLICY = "policy"
    """Failure due to policy rejection (ACL/HITL/capability gate)."""

    TIMEOUT = "timeout"
    """Task exceeded its timeout budget."""

    INTERNAL = "internal"
    """Internal runtime error (bug / unexpected state)."""

    UNKNOWN = "unknown"
    """Failure domain not determined."""


# ---------------------------------------------------------------------------
# Sub-dataclasses (grouped fields)
# ---------------------------------------------------------------------------

@dataclass
class TaskIdentity:
    """Identity fields of a canonical task."""

    task_id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}")
    """Globally unique task identifier."""

    trace_id: str = field(default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}")
    """Distributed trace identifier propagated end-to-end."""

    session_id: str = ""
    """Session scope — ties tasks within one user/agent interaction."""

    root_task_id: str = ""
    """Identifier of the root task in a task tree (equals task_id for roots)."""

    parent_task_id: str = ""
    """Identifier of the immediate parent task (empty for root tasks)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "root_task_id": self.root_task_id,
            "parent_task_id": self.parent_task_id,
        }


@dataclass
class TaskIntent:
    """Intent fields of a canonical task."""

    goal: str = ""
    """Natural-language description of what this task aims to achieve."""

    origin: TaskOrigin = TaskOrigin.UNKNOWN
    """How/where this task originated."""

    reason: str = ""
    """Reason or justification for initiating this task."""

    requested_action: str = ""
    """Concrete action requested (tool name, skill name, command, etc.)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "origin": self.origin.value if isinstance(self.origin, TaskOrigin) else str(self.origin),
            "reason": self.reason,
            "requested_action": self.requested_action,
        }


@dataclass
class TaskPlanning:
    """Planning fields — execution strategy and constraints."""

    priority: int = 5
    """Execution priority (1=highest … 10=lowest)."""

    constraints: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary execution constraints (time budget, resource limits, etc.)."""

    required_capabilities: List[str] = field(default_factory=list)
    """Device/agent capabilities required to execute this task."""

    fallback_policy: str = ""
    """Fallback strategy when primary execution fails."""

    remote_execution_mode: RemoteExecutionStyle = RemoteExecutionStyle.NONE
    """Remote execution style selected during planning."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "priority": self.priority,
            "constraints": self.constraints,
            "required_capabilities": self.required_capabilities,
            "fallback_policy": self.fallback_policy,
            "remote_execution_mode": (
                self.remote_execution_mode.value
                if isinstance(self.remote_execution_mode, RemoteExecutionStyle)
                else str(self.remote_execution_mode)
            ),
        }


@dataclass
class TaskRouting:
    """Routing decision fields."""

    selected_targets: List[str] = field(default_factory=list)
    """Device/node identifiers selected as execution targets."""

    route_preference: str = ""
    """Preferred routing strategy (e.g. 'direct', 'relay', 'mesh')."""

    transport_preference: str = ""
    """Preferred transport layer (e.g. 'websocket', 'nats', 'relay')."""

    effective_path: str = ""
    """Actual path resolved during routing (populated after ROUTED state)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_targets": self.selected_targets,
            "route_preference": self.route_preference,
            "transport_preference": self.transport_preference,
            "effective_path": self.effective_path,
        }


@dataclass
class TaskExecution:
    """Execution specification fields."""

    tool: str = ""
    """Tool or command name to invoke."""

    skill: str = ""
    """Skill name (if executing via skill subsystem)."""

    command: str = ""
    """Raw command string (if applicable)."""

    args: Dict[str, Any] = field(default_factory=dict)
    """Arguments forwarded to the tool/command/skill."""

    timeout_seconds: float = 30.0
    """Maximum execution time budget in seconds."""

    retry_policy: str = ""
    """Retry strategy (e.g. 'linear:3', 'exponential:2', 'none')."""

    permission_level: int = 0
    """Required caller privilege level (0=open … 3=critical)."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool": self.tool,
            "skill": self.skill,
            "command": self.command,
            "args": self.args,
            "timeout_seconds": self.timeout_seconds,
            "retry_policy": self.retry_policy,
            "permission_level": self.permission_level,
        }


@dataclass
class TaskGraphRelations:
    """Graph relationship fields for task DAG tracking."""

    dependencies: List[str] = field(default_factory=list)
    """task_ids this task depends on (must complete before this task starts)."""

    retry_of: str = ""
    """task_id of the original task this is a retry of."""

    fallback_of: str = ""
    """task_id of the task this is a fallback for."""

    children: List[str] = field(default_factory=list)
    """task_ids of child tasks spawned by this task."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dependencies": self.dependencies,
            "retry_of": self.retry_of,
            "fallback_of": self.fallback_of,
            "children": self.children,
        }


@dataclass
class TaskResultSummary:
    """Result summary fields populated on task completion."""

    success: Optional[bool] = None
    """True = completed, False = failed, None = not yet terminal."""

    error_code: str = ""
    """Machine-readable error code on failure."""

    failure_domain: FailureDomain = FailureDomain.UNKNOWN
    """Domain in which failure occurred."""

    result_summary: str = ""
    """Human-readable result or error summary (max 400 chars)."""

    MAX_SUMMARY_LENGTH: int = field(default=400, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.result_summary and len(self.result_summary) > 400:
            self.result_summary = self.result_summary[:397] + "..."

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "error_code": self.error_code,
            "failure_domain": (
                self.failure_domain.value
                if isinstance(self.failure_domain, FailureDomain)
                else str(self.failure_domain)
            ),
            "result_summary": self.result_summary,
        }


# ---------------------------------------------------------------------------
# CanonicalTask — main entity
# ---------------------------------------------------------------------------

@dataclass
class CanonicalTask:
    """The unified task ontology object for the Galaxy runtime.

    ``CanonicalTask`` is the **task entity** — it carries the full semantic
    definition of a task from origin through planning, routing, execution,
    and result.

    It is NOT a transport envelope.  Use
    :meth:`project_to_task_envelope` to obtain a ``TaskEnvelope`` ready for
    ``CommandRouter.route_envelope()``.

    Usage::

        task = build_canonical_task(
            goal="take screenshot",
            origin=TaskOrigin.API_REQUEST,
            requested_action="screenshot",
            selected_targets=["android_01"],
        )
        envelope = task.project_to_task_envelope()
        result = await router.route_envelope(envelope)
        task = task.apply_result_envelope(result)
    """

    # ── Sub-objects (grouped fields) ─────────────────────────────────────
    identity: TaskIdentity = field(default_factory=TaskIdentity)
    intent: TaskIntent = field(default_factory=TaskIntent)
    planning: TaskPlanning = field(default_factory=TaskPlanning)
    routing: TaskRouting = field(default_factory=TaskRouting)
    execution: TaskExecution = field(default_factory=TaskExecution)
    graph: TaskGraphRelations = field(default_factory=TaskGraphRelations)
    result: TaskResultSummary = field(default_factory=TaskResultSummary)

    # ── Lifecycle ─────────────────────────────────────────────────────────
    lifecycle: TaskLifecycle = TaskLifecycle.CREATED
    """Current lifecycle state of this task."""

    # ── Timestamps ────────────────────────────────────────────────────────
    created_at: float = field(default_factory=time.time)
    admitted_at: Optional[float] = None
    planned_at: Optional[float] = None
    routed_at: Optional[float] = None
    dispatched_at: Optional[float] = None
    running_at: Optional[float] = None
    completed_at: Optional[float] = None

    # ── Metadata ─────────────────────────────────────────────────────────
    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary extra metadata (source adapter info, tags, etc.)."""

    # ── Convenience property accessors ───────────────────────────────────

    @property
    def task_id(self) -> str:
        return self.identity.task_id

    @property
    def trace_id(self) -> str:
        return self.identity.trace_id

    @property
    def session_id(self) -> str:
        return self.identity.session_id

    # ── Lifecycle management ──────────────────────────────────────────────

    def advance_lifecycle(self, new_state: TaskLifecycle) -> "CanonicalTask":
        """Advance to *new_state* and stamp the corresponding timestamp.

        Returns ``self`` for chaining.
        """
        self.lifecycle = new_state
        now = time.time()
        _ts_map = {
            TaskLifecycle.ADMITTED: "admitted_at",
            TaskLifecycle.PLANNED: "planned_at",
            TaskLifecycle.ROUTED: "routed_at",
            TaskLifecycle.DISPATCHED: "dispatched_at",
            TaskLifecycle.RUNNING: "running_at",
            TaskLifecycle.COMPLETED: "completed_at",
            TaskLifecycle.FAILED: "completed_at",
            TaskLifecycle.CANCELLED: "completed_at",
            TaskLifecycle.DEGRADED: "completed_at",
        }
        attr = _ts_map.get(new_state)
        if attr and getattr(self, attr) is None:
            setattr(self, attr, now)
        logger.debug(
            "CanonicalTask.advance_lifecycle | task_id=%s lifecycle=%s",
            self.task_id, new_state.value,
        )
        return self

    # ── Projection ────────────────────────────────────────────────────────

    def project_to_task_envelope(self) -> Any:
        """Project this CanonicalTask into a ``TaskEnvelope`` for dispatch.

        The resulting envelope is the *execution projection* of this task and
        is ready for ``CommandRouter.route_envelope()``.

        Returns
        -------
        TaskEnvelope | _FallbackEnvelope
            A transport-ready envelope derived from this task's fields.
        """
        return project_to_task_envelope(self)

    def apply_result_envelope(self, result: Any) -> "CanonicalTask":
        """Apply a ``ResultEnvelope`` (or dict) to update this task's result.

        Updates :attr:`result` and advances lifecycle to ``COMPLETED`` or
        ``FAILED`` depending on the result.

        Returns ``self`` for chaining.
        """
        return apply_result_envelope(self, result)

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "identity": self.identity.to_dict(),
            "intent": self.intent.to_dict(),
            "planning": self.planning.to_dict(),
            "routing": self.routing.to_dict(),
            "execution": self.execution.to_dict(),
            "graph": self.graph.to_dict(),
            "result": self.result.to_dict(),
            "lifecycle": self.lifecycle.value if isinstance(self.lifecycle, TaskLifecycle) else str(self.lifecycle),
            "created_at": self.created_at,
            "admitted_at": self.admitted_at,
            "planned_at": self.planned_at,
            "routed_at": self.routed_at,
            "dispatched_at": self.dispatched_at,
            "running_at": self.running_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Observability dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CanonicalTaskRecord:
    """A single observability ring-buffer entry for the task runtime."""

    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    trace_id: str = ""
    lifecycle: str = TaskLifecycle.CREATED.value
    origin: str = TaskOrigin.UNKNOWN.value
    tool: str = ""
    targets: List[str] = field(default_factory=list)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "lifecycle": self.lifecycle,
            "origin": self.origin,
            "tool": self.tool,
            "targets": self.targets,
            "ts": self.ts,
        }


@dataclass
class CanonicalTaskSnapshot:
    """Point-in-time snapshot of the CanonicalTaskRuntime state."""

    total_tasks: int = 0
    tasks_by_lifecycle: Dict[str, int] = field(default_factory=dict)
    tasks_by_origin: Dict[str, int] = field(default_factory=dict)
    recent_records: List[Dict[str, Any]] = field(default_factory=list)
    snapshot_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_tasks": self.total_tasks,
            "tasks_by_lifecycle": self.tasks_by_lifecycle,
            "tasks_by_origin": self.tasks_by_origin,
            "recent_records": self.recent_records,
            "snapshot_ts": self.snapshot_ts,
        }


# ---------------------------------------------------------------------------
# CanonicalTaskRuntime — singleton registry
# ---------------------------------------------------------------------------

class CanonicalTaskRuntime:
    """Singleton runtime that indexes all CanonicalTask instances.

    Provides:
    - Registration of tasks with a 256-entry observability ring-buffer.
    - Lookup by ``task_id``.
    - Snapshot for operator observability.

    Not a dispatch authority — it does not route envelopes.
    """

    _MAX_RING: int = 256

    def __init__(self) -> None:
        self._tasks: Dict[str, CanonicalTask] = {}
        self._ring: Deque[CanonicalTaskRecord] = deque(maxlen=self._MAX_RING)

    # ── Registration ─────────────────────────────────────────────────────

    def register(self, task: CanonicalTask) -> CanonicalTask:
        """Register *task* with the runtime.

        Subsequent calls with the same ``task_id`` update the stored task
        (idempotent upsert).

        Returns the task for chaining.
        """
        if not task.identity.task_id:
            raise ValueError("CanonicalTask must have a non-empty task_id")
        self._tasks[task.identity.task_id] = task
        rec = CanonicalTaskRecord(
            task_id=task.identity.task_id,
            trace_id=task.identity.trace_id,
            lifecycle=task.lifecycle.value if isinstance(task.lifecycle, TaskLifecycle) else str(task.lifecycle),
            origin=(
                task.intent.origin.value
                if isinstance(task.intent.origin, TaskOrigin)
                else str(task.intent.origin)
            ),
            tool=task.execution.tool or task.intent.requested_action,
            targets=list(task.routing.selected_targets),
        )
        self._ring.append(rec)
        logger.debug(
            "CanonicalTaskRuntime.register | task_id=%s lifecycle=%s origin=%s",
            task.task_id, task.lifecycle.value, rec.origin,
        )
        return task

    def update_lifecycle(self, task_id: str, new_state: TaskLifecycle) -> Optional[CanonicalTask]:
        """Advance a registered task to *new_state*.

        Returns the updated task or ``None`` if not found.
        """
        task = self._tasks.get(task_id)
        if task is None:
            return None
        task.advance_lifecycle(new_state)
        self.register(task)  # re-record updated state
        return task

    # ── Queries ───────────────────────────────────────────────────────────

    def get_by_task_id(self, task_id: str) -> Optional[CanonicalTask]:
        """Return the CanonicalTask with *task_id*, or ``None``."""
        return self._tasks.get(task_id)

    def get_by_trace_id(self, trace_id: str) -> List[CanonicalTask]:
        """Return all tasks sharing *trace_id*."""
        return [t for t in self._tasks.values() if t.identity.trace_id == trace_id]

    # ── Observability ─────────────────────────────────────────────────────

    def get_observability_log(self) -> List[CanonicalTaskRecord]:
        """Return a snapshot of the observability ring-buffer (most recent last)."""
        return list(self._ring)

    def snapshot(self) -> CanonicalTaskSnapshot:
        """Return a point-in-time snapshot of the runtime state."""
        by_lifecycle: Dict[str, int] = {}
        by_origin: Dict[str, int] = {}
        for task in self._tasks.values():
            lc = task.lifecycle.value if isinstance(task.lifecycle, TaskLifecycle) else str(task.lifecycle)
            by_lifecycle[lc] = by_lifecycle.get(lc, 0) + 1
            orig = (
                task.intent.origin.value
                if isinstance(task.intent.origin, TaskOrigin)
                else str(task.intent.origin)
            )
            by_origin[orig] = by_origin.get(orig, 0) + 1
        return CanonicalTaskSnapshot(
            total_tasks=len(self._tasks),
            tasks_by_lifecycle=by_lifecycle,
            tasks_by_origin=by_origin,
            recent_records=[r.to_dict() for r in self._ring],
        )


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_runtime_instance: Optional[CanonicalTaskRuntime] = None


def get_canonical_task_runtime() -> CanonicalTaskRuntime:
    """Return the process-global :class:`CanonicalTaskRuntime` singleton."""
    global _runtime_instance
    if _runtime_instance is None:
        _runtime_instance = CanonicalTaskRuntime()
    return _runtime_instance


def reset_canonical_task_runtime() -> None:
    """Reset the singleton (for testing only)."""
    global _runtime_instance
    _runtime_instance = None


# ---------------------------------------------------------------------------
# Builder helper
# ---------------------------------------------------------------------------

def build_canonical_task(
    *,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    session_id: str = "",
    root_task_id: str = "",
    parent_task_id: str = "",
    goal: str = "",
    origin: TaskOrigin = TaskOrigin.UNKNOWN,
    reason: str = "",
    requested_action: str = "",
    priority: int = 5,
    constraints: Optional[Dict[str, Any]] = None,
    required_capabilities: Optional[List[str]] = None,
    fallback_policy: str = "",
    remote_execution_mode: RemoteExecutionStyle = RemoteExecutionStyle.NONE,
    selected_targets: Optional[List[str]] = None,
    route_preference: str = "",
    transport_preference: str = "",
    tool: str = "",
    skill: str = "",
    command: str = "",
    args: Optional[Dict[str, Any]] = None,
    timeout_seconds: float = 30.0,
    retry_policy: str = "",
    permission_level: int = 0,
    dependencies: Optional[List[str]] = None,
    retry_of: str = "",
    fallback_of: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    register: bool = True,
) -> CanonicalTask:
    """Construct and optionally register a :class:`CanonicalTask`.

    All parameters are keyword-only.  Omit any field to use the default.

    Parameters
    ----------
    register:
        When ``True`` (default) the task is immediately registered with the
        :class:`CanonicalTaskRuntime` singleton.

    Returns
    -------
    CanonicalTask
    """
    effective_tool = tool or requested_action or command or skill or ""
    task = CanonicalTask(
        identity=TaskIdentity(
            task_id=task_id or f"task_{uuid.uuid4().hex[:16]}",
            trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            root_task_id=root_task_id,
            parent_task_id=parent_task_id,
        ),
        intent=TaskIntent(
            goal=goal,
            origin=origin,
            reason=reason,
            requested_action=requested_action,
        ),
        planning=TaskPlanning(
            priority=priority,
            constraints=constraints or {},
            required_capabilities=required_capabilities or [],
            fallback_policy=fallback_policy,
            remote_execution_mode=remote_execution_mode,
        ),
        routing=TaskRouting(
            selected_targets=selected_targets or [],
            route_preference=route_preference,
            transport_preference=transport_preference,
        ),
        execution=TaskExecution(
            tool=effective_tool,
            skill=skill,
            command=command,
            args=args or {},
            timeout_seconds=timeout_seconds,
            retry_policy=retry_policy,
            permission_level=permission_level,
        ),
        graph=TaskGraphRelations(
            dependencies=dependencies or [],
            retry_of=retry_of,
            fallback_of=fallback_of,
        ),
        metadata=metadata or {},
    )
    if register:
        get_canonical_task_runtime().register(task)
    return task


# ---------------------------------------------------------------------------
# Projection: CanonicalTask → TaskEnvelope
# ---------------------------------------------------------------------------

@dataclass
class _FallbackEnvelope:
    """Minimal envelope for environments where pydantic / TaskEnvelope
    is unavailable."""

    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    source: str = "canonical_task"
    targets: List[str] = field(default_factory=list)
    tool_name: str = ""
    args: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> str:
        return self.targets[0] if self.targets else ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "source": self.source,
            "targets": self.targets,
            "tool_name": self.tool_name,
            "args": self.args,
            "metadata": self.metadata,
        }


def project_to_task_envelope(task: CanonicalTask) -> Any:
    """Project a :class:`CanonicalTask` into a ``TaskEnvelope``.

    The ``TaskEnvelope`` is the *execution projection* of the canonical task.
    It is the contract consumed by ``CommandRouter.route_envelope()``.

    Parameters
    ----------
    task:
        The canonical task to project.

    Returns
    -------
    TaskEnvelope | _FallbackEnvelope
        A transport-ready envelope.
    """
    tool_name = (
        task.execution.tool
        or task.execution.skill
        or task.execution.command
        or task.intent.requested_action
        or "unknown"
    )
    meta: Dict[str, Any] = {
        "canonical_task_id": task.identity.task_id,
        "canonical_task_lifecycle": (
            task.lifecycle.value
            if isinstance(task.lifecycle, TaskLifecycle)
            else str(task.lifecycle)
        ),
        "canonical_task_origin": (
            task.intent.origin.value
            if isinstance(task.intent.origin, TaskOrigin)
            else str(task.intent.origin)
        ),
        "canonical_task_authority": CANONICAL_TASK_AUTHORITY,
        **task.metadata,
    }

    try:
        from core.schemas.task_envelope import TaskEnvelope as _TE  # type: ignore
        env = _TE(
            task_id=task.identity.task_id,
            trace_id=task.identity.trace_id,
            session_id=task.identity.session_id or None,
            source="canonical_task",
            targets=list(task.routing.selected_targets),
            tool_name=tool_name,
            args=dict(task.execution.args),
            metadata=meta,
        )
        # Stamp remote execution mode if set
        rem = task.planning.remote_execution_mode
        if rem not in (RemoteExecutionStyle.NONE, RemoteExecutionStyle.LOCAL):
            try:
                from core.schemas.remote_execution import RemoteExecutionMode  # type: ignore
                mode_val = rem.value
                if hasattr(_TE, "model_fields") and "remote_execution_mode" in _TE.model_fields:
                    env = env.model_copy(
                        update={"remote_execution_mode": RemoteExecutionMode(mode_val)}
                    )
            except Exception:
                pass
        return env
    except Exception as exc:
        logger.debug("project_to_task_envelope: TaskEnvelope unavailable (%s); using fallback", exc)
        return _FallbackEnvelope(
            task_id=task.identity.task_id,
            trace_id=task.identity.trace_id,
            session_id=task.identity.session_id,
            source="canonical_task",
            targets=list(task.routing.selected_targets),
            tool_name=tool_name,
            args=dict(task.execution.args),
            metadata=meta,
        )


# ---------------------------------------------------------------------------
# Result update: ResultEnvelope → CanonicalTask
# ---------------------------------------------------------------------------

def apply_result_envelope(task: CanonicalTask, result: Any) -> CanonicalTask:
    """Apply a result (``ResultEnvelope`` or dict) back to *task*.

    Updates :attr:`CanonicalTask.result` and advances the lifecycle to
    ``COMPLETED`` or ``FAILED`` based on the result's success flag.

    Parameters
    ----------
    task:
        The canonical task to update.
    result:
        A ``ResultEnvelope``, dict, or any object with a ``success`` attribute.

    Returns
    -------
    CanonicalTask
        The updated task (same object, mutated in-place).
    """
    raw: Dict[str, Any] = {}
    if isinstance(result, dict):
        raw = result
    elif hasattr(result, "to_dict"):
        try:
            raw = result.to_dict()
        except Exception:
            pass
    elif hasattr(result, "__dict__"):
        raw = {k: v for k, v in result.__dict__.items() if not k.startswith("_")}

    success = raw.get("success")
    if success is None and hasattr(result, "success"):
        success = result.success
    error_code = str(raw.get("error_code") or raw.get("error") or "")
    result_summary = str(raw.get("result_summary") or raw.get("result") or raw.get("message") or "")

    # Determine failure domain
    fd_raw = str(raw.get("failure_domain") or "")
    try:
        fd = FailureDomain(fd_raw) if fd_raw else FailureDomain.UNKNOWN
    except ValueError:
        fd = FailureDomain.UNKNOWN

    task.result = TaskResultSummary(
        success=success,
        error_code=error_code[:200] if error_code else "",
        failure_domain=fd,
        result_summary=result_summary,
    )

    if success is True:
        task.advance_lifecycle(TaskLifecycle.COMPLETED)
    elif success is False:
        task.advance_lifecycle(TaskLifecycle.FAILED)
    # If success is None, lifecycle remains unchanged (in-flight)

    # Re-register to update runtime state
    get_canonical_task_runtime().register(task)
    return task
