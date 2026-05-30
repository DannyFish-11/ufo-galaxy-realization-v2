#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/state_schema.py
=============================
PR-1 (Block-1) — Unified State Schema

Defines shared data structures (dataclasses) used across all Galaxy modules for:
  - DeviceState      — canonical device presence/status snapshot
  - TaskState        — canonical task lifecycle snapshot
  - CognitiveState   — cognitive/continuum engine snapshot
  - PresenceState    — tri-state presence projection snapshot
  - ExecutionState   — execution pipeline snapshot

Design goals
------------
- **Additive** — existing code can keep using dicts; modules migrate
  incrementally by importing these types.
- **No external dependencies** — stdlib-only (dataclasses + enum) so this
  module can be safely imported anywhere in the core without circular deps.
- **Serialisable** — every class provides ``to_dict()`` / ``from_dict()``
  helpers for JSON serialisation.

Usage::

    from core.unified.state_schema import DeviceState, TaskState

    device = DeviceState(
        device_id="dev-001",
        status="online",
        entry_path="canonical",
    )
    payload = device.to_dict()
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Shared enums
# ---------------------------------------------------------------------------


class EntryPath(str, Enum):
    """Indicates whether a request arrived via the canonical or legacy path."""

    CANONICAL = "canonical"
    LEGACY = "legacy"
    UNKNOWN = "unknown"


class TaskStatus(str, Enum):
    """Canonical task lifecycle status values."""

    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class PresencePhase(str, Enum):
    """Tri-state presence phase (silent → liminal → manifest)."""

    SILENT = "silent"
    LIMINAL = "liminal"
    MANIFEST = "manifest"


class ExecutionStatus(str, Enum):
    """Status of an execution pipeline run."""

    IDLE = "idle"
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    DEGRADED = "degraded"


# ---------------------------------------------------------------------------
# DeviceState
# ---------------------------------------------------------------------------


@dataclass
class DeviceState:
    """Canonical snapshot of a single device's presence and status.

    Attributes
    ----------
    device_id:
        Globally unique device identifier.
    status:
        Current device status (``online``, ``offline``, ``busy``, ``error``,
        ``initializing``, ``disconnected``).
    device_type:
        Device category (``android``, ``windows``, ``ios``, …).
    capabilities:
        List of capability strings the device currently exposes.
    entry_path:
        Whether this state was last updated via the canonical or legacy path.
    via_legacy_adapter:
        ``True`` when the last update arrived through a legacy adapter.
    trace_id:
        Correlation ID from the request that produced this state.
    state_version:
        Monotonically increasing integer for conflict detection.
    updated_at:
        Unix timestamp (float) of the last state update.
    metadata:
        Arbitrary extra fields for extensibility.
    """

    device_id: str
    status: str = "offline"
    device_type: str = "unknown"
    capabilities: List[str] = field(default_factory=list)
    entry_path: str = EntryPath.UNKNOWN.value
    via_legacy_adapter: bool = False
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    state_version: int = 0
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# TaskState
# ---------------------------------------------------------------------------


@dataclass
class TaskState:
    """Enhanced canonical snapshot of a task's lifecycle with JudgeLoop support.

    This is the single source of truth for all task execution.  Every organ
    (Coder, Verifier, Research, etc.) reads this state and writes structured
    results back to it.  The JudgeLoop uses this to make pass/retry/switch/stop
    decisions.

    Attributes
    ----------
    task_id / trace_id / session_id:
        Identity & correlation.
    goal:
        User's original intent — the single sentence OpenClawd extracts.
    constraints:
        Confirmed constraints (budget, time, style rules, etc.).
    phase:
        JudgeLoop phase: interpret/plan/dispatch/execute/verify/judge/respond.
    sub_tasks:
        If the task was split, the sub-task states live here.
    judge_history:
        Every Judge decision (pass/retry/switch/stop + reason).
    failure_points:
        Current blockers / failed checks.
    verified_items:
        Checks that have already passed.
    user_preferences:
        Injected from LongTermMemory (style, speed, verbosity, etc.).
    tool_name / status / entry_path / via_legacy_adapter:
        Legacy fields (kept for backward compat).
    created_at / updated_at:
        Timestamps.
    result_summary / error:
        Final output or failure reason.
    metadata:
        Extension bucket.
    """

    # ── identity ──
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str = ""

    # ── JudgeLoop core (NEW) ──
    goal: str = ""                           # 用户原始意图
    constraints: List[str] = field(default_factory=list)   # 已确认约束
    phase: str = "interpret"                 # JudgeLoop阶段
    sub_tasks: List[Dict[str, Any]] = field(default_factory=list)  # 子任务
    judge_history: List[Dict[str, Any]] = field(default_factory=list)  # 裁决历史
    failure_points: List[str] = field(default_factory=list)   # 失败点
    verified_items: List[str] = field(default_factory=list)   # 已验证项
    user_preferences: Dict[str, Any] = field(default_factory=dict)   # 用户偏好

    # ── legacy (kept for backward compat) ──
    tool_name: str = ""
    status: str = TaskStatus.CREATED.value
    entry_path: str = EntryPath.UNKNOWN.value
    via_legacy_adapter: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result_summary: str = ""
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)

    # ── JudgeLoop helpers (NEW) ──
    def add_judge_record(self, decision: str, reason: str) -> None:
        """Append a Judge decision to the history."""
        self.judge_history.append({
            "decision": decision,
            "reason": reason,
            "timestamp": time.time(),
        })
        self.updated_at = time.time()

    def mark_verified(self, item: str) -> None:
        """Mark an item as passed."""
        if item not in self.verified_items:
            self.verified_items.append(item)
        self.updated_at = time.time()

    def mark_failure(self, point: str) -> None:
        """Record a failure point."""
        if point not in self.failure_points:
            self.failure_points.append(point)
        self.updated_at = time.time()

    def resolve_failure(self, point: str) -> None:
        """Remove a failure point (on retry success)."""
        if point in self.failure_points:
            self.failure_points.remove(point)
        self.updated_at = time.time()

    def set_goal(self, goal: str) -> None:
        """Set the user goal (Interpret step)."""
        self.goal = goal
        self.phase = "plan"
        self.updated_at = time.time()

    def set_phase(self, phase: str) -> None:
        """Move to the next JudgeLoop phase."""
        self.phase = phase
        self.updated_at = time.time()

    def is_blocked(self) -> bool:
        """Return True if there are unresolved failure points."""
        return len(self.failure_points) > 0

    def all_verified(self, required: List[str]) -> bool:
        """Return True if all required items are verified."""
        return all(r in self.verified_items for r in required)


# ---------------------------------------------------------------------------
# CognitiveState
# ---------------------------------------------------------------------------


@dataclass
class CognitiveState:
    """Snapshot of the continuum / cognitive engine state for a session.

    Attributes
    ----------
    session_id:
        Session this cognitive state belongs to.
    trace_id:
        Correlation ID.
    activation:
        Current cognitive activation level (0.0–1.0).
    intent_vector:
        Normalised intent representation (list of floats or empty list).
    uncertainty:
        Current uncertainty level (0.0–1.0).
    momentum:
        Directional momentum of cognitive processing (float).
    entry_path:
        Whether this snapshot was generated via canonical or legacy path.
    tick_ms:
        Duration of the last cognitive tick in milliseconds.
    degrade_reason:
        Non-empty when the engine degraded (e.g. ``tick_budget_exceeded``).
    updated_at:
        Unix timestamp of this snapshot.
    metadata:
        Extra fields.
    """

    session_id: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    activation: float = 0.0
    intent_vector: List[float] = field(default_factory=list)
    uncertainty: float = 0.0
    momentum: float = 0.0
    entry_path: str = EntryPath.UNKNOWN.value
    tick_ms: float = 0.0
    degrade_reason: str = ""
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CognitiveState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# PresenceState
# ---------------------------------------------------------------------------


@dataclass
class PresenceState:
    """Canonical snapshot of presence projection for a runtime session.

    Attributes
    ----------
    runtime_session_id:
        Identifier of the DesktopPresenceRuntime session.
    trace_id:
        Correlation ID.
    phase:
        Current presence phase (see :class:`PresencePhase`).
    device_id:
        Device on which presence is projected.
    intensity:
        Presence intensity / projection strength (0.0–1.0).
    entry_path:
        Whether this state transition was triggered via canonical or legacy path.
    transition_count:
        Number of phase transitions in this session so far.
    updated_at:
        Unix timestamp.
    metadata:
        Extra fields.
    """

    runtime_session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    phase: str = PresencePhase.SILENT.value
    device_id: str = ""
    intensity: float = 0.0
    entry_path: str = EntryPath.UNKNOWN.value
    transition_count: int = 0
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PresenceState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# ExecutionState
# ---------------------------------------------------------------------------


@dataclass
class ExecutionState:
    """Canonical snapshot of an execution pipeline run.

    Attributes
    ----------
    execution_id:
        Unique identifier for this execution run.
    task_id:
        Parent task identifier.
    trace_id:
        Correlation ID.
    status:
        Current execution status (see :class:`ExecutionStatus`).
    device_id:
        Device that executed (or is executing) this run.
    tool_name:
        Tool/action being executed.
    entry_path:
        Whether this execution was triggered via canonical or legacy path.
    via_legacy_adapter:
        ``True`` when triggered through a legacy adapter.
    latency_ms:
        Observed execution latency (populated after completion).
    error:
        Error description if status is ``failure``.
    created_at:
        Unix timestamp when execution started.
    updated_at:
        Unix timestamp of the last status change.
    metadata:
        Extra fields.
    """

    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    task_id: str = ""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: str = ExecutionStatus.IDLE.value
    device_id: str = ""
    tool_name: str = ""
    entry_path: str = EntryPath.UNKNOWN.value
    via_legacy_adapter: bool = False
    latency_ms: float = 0.0
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionState":
        known = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------

__all__ = [
    "EntryPath",
    "TaskStatus",
    "PresencePhase",
    "ExecutionStatus",
    "DeviceState",
    "TaskState",
    "CognitiveState",
    "PresenceState",
    "ExecutionState",
]
