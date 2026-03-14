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

Schema version: 1
Pydantic: v2
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


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
            "tenant, user_id, session_id, …"
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
            "source": self.source,
            "tool_name": self.tool_name,
        }


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
        source=source,
        targets=targets,
        tool_name=command,
        args=params,
        priority=priority,
        timeout=timeout,
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
