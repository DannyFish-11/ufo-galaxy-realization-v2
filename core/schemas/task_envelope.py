#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — TaskEnvelope (canonical Agent-Bus message schema)
===========================================================

A single, authoritative envelope used across all internal routing paths:
  - gateway command dispatch
  - device-to-device relay (ProxyRelay)
  - node / worker execution
  - MCP tool calls and skill invocations

Every component that originates or forwards a task MUST wrap it in a
TaskEnvelope.  Legacy endpoints convert their request models using the
helper adapters below so that all internal code sees a consistent shape.

Schema version: 2
Pydantic: v2

PR-5 additions (capability closure):
  - session_id        : explicit session identifier for context continuity
  - lifecycle_status  : task.lifecycle state machine (created→running→done/failed)
  - permission_level  : required caller privilege level (0=open … 3=critical)
  - required_capabilities : list of device/agent capabilities required to run

PR-5 RemoteExecutionMode addition:
  - remote_execution_mode : explicit remote execution style over the cross-device
                            substrate ('agent_runtime' or 'command_only'); None
                            for local tasks.  Optional — backward-compatible.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from core.schemas.remote_execution import ExecutorTargetType, RemoteExecutionMode


# ---------------------------------------------------------------------------
# Lifecycle state literals (Capability 1)
# ---------------------------------------------------------------------------

TaskLifecycleStatus = Literal["created", "running", "done", "failed"]

# ---------------------------------------------------------------------------
# Canonical TaskEnvelope
# ---------------------------------------------------------------------------

class TaskEnvelope(BaseModel):
    """Canonical internal task representation used across the Agent Bus.

    All fields have sensible defaults so that partial construction is
    convenient; consumers that require certain fields should validate them
    explicitly before processing.
    """

    # ── Identity ────────────────────────────────────────────────────────────
    task_id: str = Field(
        default_factory=lambda: f"task_{uuid.uuid4().hex[:16]}",
        description="Globally unique task identifier.",
    )
    trace_id: str = Field(
        default_factory=lambda: f"trace_{uuid.uuid4().hex[:12]}",
        description=(
            "Distributed trace identifier. Set by the originating gateway "
            "and propagated unchanged through the entire call chain so that "
            "all logs for a single user request share the same trace_id."
        ),
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Session identifier for context continuity across multiple tasks "
            "within the same user/agent interaction. Used by TaskMemory to "
            "scope memory injection. (Capability 3)"
        ),
    )

    # ── Routing ─────────────────────────────────────────────────────────────
    source: str = Field(
        default="",
        description="Originating component: 'api', 'ws', 'scheduler', 'ai', device_id, …",
    )
    targets: List[str] = Field(
        default_factory=list,
        description="One or more target device / worker / node identifiers.",
    )

    # ── Invocation ──────────────────────────────────────────────────────────
    tool_name: str = Field(
        default="",
        description="Tool, skill, command, or MCP tool name to invoke.",
    )
    args: Dict[str, Any] = Field(
        default_factory=dict,
        description="Named arguments forwarded to the tool/command.",
    )

    # ── Scheduling ──────────────────────────────────────────────────────────
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Execution priority 1 (highest) – 10 (lowest).",
    )
    timeout: float = Field(
        default=30.0,
        gt=0,
        description="Maximum execution time in seconds.",
    )

    # ── Lifecycle (Capability 1) ─────────────────────────────────────────────
    lifecycle_status: TaskLifecycleStatus = Field(
        default="created",
        description=(
            "Task lifecycle state machine: created → running → done | failed. "
            "Updated in-place by CommandRouter / TaskOrchestrator as the task "
            "progresses. Drives M2 task.lifecycle events. (Capability 1)"
        ),
    )

    # ── Access Control (Capability 5) ────────────────────────────────────────
    permission_level: int = Field(
        default=0,
        ge=0,
        le=3,
        description=(
            "Required privilege level for this task: "
            "0=open (no restrictions), 1=normal (authenticated), "
            "2=elevated (admin-equivalent), 3=critical (destructive/system). "
            "Checked by ACLEnforcer before execution. (Capability 5)"
        ),
    )
    required_capabilities: List[str] = Field(
        default_factory=list,
        description=(
            "Device/agent capabilities required to execute this task "
            "(e.g. 'screen', 'filesystem', 'http_client'). "
            "ACLEnforcer validates the executing agent has all listed caps. "
            "(Capabilities 4 & 5)"
        ),
    )

    # ── Timestamps ──────────────────────────────────────────────────────────
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when the envelope was first created.",
    )

    # ── Free-form metadata ───────────────────────────────────────────────────
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arbitrary key-value pairs: mode, notify_ws, relay hints, "
            "tenant, user_id, …"
        ),
    )

    # ── Remote execution style (PR-5) ────────────────────────────────────────
    remote_execution_mode: Optional[RemoteExecutionMode] = Field(
        default=None,
        description=(
            "Remote execution style over the cross-device substrate. "
            "'agent_runtime' for richer targets that execute agent tasks; "
            "'command_only' for thinner targets that accept structured commands. "
            "None for local tasks or when the mode is not yet determined. "
            "Optional — callers that do not set this field continue to work "
            "unchanged. (PR-5)"
        ),
    )

    # ── Executor target type (PR-E) ───────────────────────────────────────────
    executor_target_type: Optional[ExecutorTargetType] = Field(
        default=None,
        description=(
            "Explicit executor target type for first-class dispatch routing. "
            "When set, CommandRouter.route_envelope() branches on this field "
            "rather than inferring target kind from ID patterns or metadata "
            "heuristics. "
            "'android_device' — Android device via gateway/DeviceRouter; "
            "'node_service' — Galaxy node service via DeviceRouter; "
            "'go_worker' — Go edge worker via MasterBrain/NATS; "
            "'local' — local runtime execution. "
            "None preserves existing metadata-based routing (backward compat). "
            "(PR-E)"
        ),
    )

    model_config = {"from_attributes": True}

    # ── Convenience helpers ─────────────────────────────────────────────────

    @property
    def target(self) -> str:
        """Return the first target (shorthand for single-target tasks)."""
        return self.targets[0] if self.targets else ""

    def log_context(self) -> Dict[str, str]:
        """Return a dict suitable for structured log fields."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id or "",
            "source": self.source,
            "tool_name": self.tool_name,
            "lifecycle_status": self.lifecycle_status,
            "permission_level": str(self.permission_level),
        }

    def transition(self, new_status: TaskLifecycleStatus) -> "TaskEnvelope":
        """Return a copy of this envelope with the lifecycle_status updated.

        Validates allowed transitions:
          created  → running
          running  → done | failed
          done     → (terminal, no further transitions)
          failed   → (terminal, no further transitions)
        """
        _allowed: Dict[str, set] = {
            "created": {"running"},
            "running": {"done", "failed"},
            "done": set(),
            "failed": set(),
        }
        if new_status not in _allowed.get(self.lifecycle_status, set()):
            raise ValueError(
                f"Invalid lifecycle transition: {self.lifecycle_status!r} → {new_status!r}"
            )
        return self.model_copy(update={"lifecycle_status": new_status})


# ---------------------------------------------------------------------------
# Adapter helpers (legacy → TaskEnvelope)
# ---------------------------------------------------------------------------

def envelope_from_command_request(
    *,
    command: str,
    targets: List[str],
    params: Dict[str, Any],
    source: str = "api",
    mode: str = "sync",
    timeout: float = 30.0,
    priority: int = 5,
    notify_ws: bool = True,
    request_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    session_id: Optional[str] = None,
    permission_level: int = 0,
    required_capabilities: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskEnvelope:
    """Build a TaskEnvelope from a legacy CommandDispatchRequest / UnifiedCommandRequest.

    Callers pass keyword arguments taken directly from the legacy model; this
    function handles ID defaulting and metadata packing.
    """
    meta = dict(metadata or {})
    meta.setdefault("mode", mode)
    meta.setdefault("notify_ws", notify_ws)
    if request_id:
        meta.setdefault("request_id", request_id)

    return TaskEnvelope(
        task_id=task_id or request_id or f"task_{uuid.uuid4().hex[:16]}",
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        source=source,
        targets=targets,
        tool_name=command,
        args=params,
        priority=priority,
        timeout=timeout,
        permission_level=permission_level,
        required_capabilities=required_capabilities or [],
        metadata=meta,
    )


def envelope_from_relay_request(
    *,
    source_device: str,
    target_device: str,
    payload_type: str,
    payload: Dict[str, Any],
    timeout_seconds: float = 30.0,
    priority: int = 5,
    chain: Optional[List[str]] = None,
    relay_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskEnvelope:
    """Build a TaskEnvelope from a ProxyRelay RelayRequest."""
    meta = dict(metadata or {})
    meta.setdefault("payload_type", payload_type)
    if chain:
        meta.setdefault("relay_chain", chain)
    if relay_id:
        meta.setdefault("relay_id", relay_id)

    return TaskEnvelope(
        task_id=relay_id or f"task_{uuid.uuid4().hex[:16]}",
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        source=source_device,
        targets=[target_device] + (chain or []),
        tool_name=payload_type,
        args=payload,
        priority=priority,
        timeout=timeout_seconds,
        metadata=meta,
    )


def envelope_from_mcp_call(
    *,
    server_name: str,
    tool_name: str,
    arguments: Dict[str, Any],
    source: str = "api",
    timeout: float = 30.0,
    trace_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> TaskEnvelope:
    """Build a TaskEnvelope from an MCP tool-call request."""
    meta = dict(metadata or {})
    meta.setdefault("mcp_server", server_name)

    return TaskEnvelope(
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        source=source,
        targets=[server_name],
        tool_name=tool_name,
        args=arguments,
        timeout=timeout,
        metadata=meta,
    )
