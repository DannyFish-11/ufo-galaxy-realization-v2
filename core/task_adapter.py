#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_adapter.py — PR-A: Canonical Task Adapter
=====================================================

**Unified Task Adapter — all inputs → CanonicalTask**
------------------------------------------------------
This module is the *single normalization layer* that converts every type of
task input entering the Galaxy runtime into a :class:`~core.canonical_task.CanonicalTask`.

Supported input origins
-----------------------
- **API request** — HTTP/REST payload (dict with action/tool/goal keys)
- **AI intent action** — AI agent intent object or dict
- **Workflow step** — workflow step descriptor
- **Orchestrator task** — galaxy/fusion/device orchestrator task dict
- **Device command** — device_id + action command dict
- **MCP tool call** — MCP tool invocation payload
- **Skill invocation** — skill name + args dict
- **Existing TaskEnvelope** — already-projected envelope (fast path)
- **Existing CanonicalTask** — passthrough (no-op)

Architecture position
---------------------
The adapter sits *between* all entry points and the canonical task entity:

::

    API / AI / Workflow / Orchestrator / Device / MCP / Skill
                            │
                            ▼
               TaskAdapterLayer.adapt(payload, origin)
                            │
                            ▼
                    CanonicalTask  (ontology)
                            │
                  project_to_task_envelope()
                            ▼
                    TaskEnvelope  (execution projection)
                            │
               CommandRouter.route_envelope()
                            ▼
                    transport / executor

Design invariants
-----------------
1.  **Non-destructive** — legacy input models are never modified.
2.  **Graceful** — all optional imports are guarded; adapter never raises
    on import failure.
3.  **Observable** — every adaptation is recorded in a 256-entry ring-buffer.
4.  **Origin-aware** — the ``TaskOrigin`` enum value is set from the caller.

Public API
----------
Authority sentinels::

    TASK_ADAPTER_AUTHORITY
    TASK_ADAPTER_NORMALIZATION_POLICY

Enumerations::

    (uses TaskOrigin from canonical_task)

Dataclasses::

    AdaptationRecord

Classes::

    TaskAdapterLayer

Helpers::

    adapt_to_canonical_task(payload, *, origin) -> CanonicalTask
    get_adaptation_log() -> List[AdaptationRecord]
    reset_adaptation_log()   # testing only
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.TaskAdapter")

__all__ = [
    # Authority
    "TASK_ADAPTER_AUTHORITY",
    "TASK_ADAPTER_NORMALIZATION_POLICY",
    # Dataclass
    "AdaptationRecord",
    # Class
    "TaskAdapterLayer",
    # Helpers
    "adapt_to_canonical_task",
    "get_adaptation_log",
    "reset_adaptation_log",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

TASK_ADAPTER_AUTHORITY: str = "TASK_ADAPTER_V1"
"""Sentinel: identifies this module as the canonical task adapter authority."""

TASK_ADAPTER_NORMALIZATION_POLICY: str = (
    "ALL task input origins (api_request/ai_intent/workflow_step/orchestrator_task/"
    "device_command/mcp_tool_call/skill_invocation) MUST be normalized to "
    "CanonicalTask before entering the execution spine."
)
"""Policy: all inputs MUST pass through the adapter before dispatch."""


# ---------------------------------------------------------------------------
# Adaptation record (observability ring-buffer entry)
# ---------------------------------------------------------------------------

@dataclass
class AdaptationRecord:
    """A single entry in the task adaptation observability log."""

    record_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    trace_id: str = ""
    origin: str = "unknown"
    tool: str = ""
    targets: List[str] = field(default_factory=list)
    was_passthrough: bool = False
    """True when the input was already a CanonicalTask or TaskEnvelope."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "origin": self.origin,
            "tool": self.tool,
            "targets": self.targets,
            "was_passthrough": self.was_passthrough,
        }


# ---------------------------------------------------------------------------
# Adaptation log (ring-buffer)
# ---------------------------------------------------------------------------

_LOG_MAX: int = 256
_adaptation_log: Deque[AdaptationRecord] = deque(maxlen=_LOG_MAX)


def get_adaptation_log() -> List[AdaptationRecord]:
    """Return a snapshot of the adaptation log (most recent last)."""
    return list(_adaptation_log)


def reset_adaptation_log() -> None:
    """Clear the adaptation log (for testing only)."""
    _adaptation_log.clear()


def _append_record(rec: AdaptationRecord) -> None:
    _adaptation_log.append(rec)


# ---------------------------------------------------------------------------
# Internal extraction helpers
# ---------------------------------------------------------------------------

def _extract_dict(payload: Any) -> Dict[str, Any]:
    """Extract a raw dict from any payload type."""
    if isinstance(payload, dict):
        return payload
    if hasattr(payload, "model_dump"):
        try:
            return payload.model_dump()
        except Exception:
            pass
    if hasattr(payload, "to_dict"):
        try:
            return payload.to_dict()
        except Exception:
            pass
    if hasattr(payload, "__dict__"):
        return {k: v for k, v in payload.__dict__.items() if not k.startswith("_")}
    return {}


def _pick_tool(raw: Dict[str, Any]) -> str:
    """Pick the best tool/action name from a raw dict."""
    for key in ("tool_name", "tool", "skill", "command", "action", "task_type", "requested_action"):
        val = raw.get(key)
        if val:
            return str(val)
    return ""


def _pick_targets(raw: Dict[str, Any]) -> List[str]:
    """Extract target device list from a raw dict."""
    targets = raw.get("targets") or raw.get("selected_targets") or []
    if isinstance(targets, list) and targets:
        return [str(t) for t in targets]
    for key in ("target_device_id", "device_id", "target_device", "device"):
        val = raw.get(key)
        if val:
            return [str(val)]
    return []


def _pick_args(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Extract args/payload from a raw dict."""
    for key in ("args", "payload", "params", "kwargs", "input"):
        val = raw.get(key)
        if isinstance(val, dict):
            return val
    return {}


# ---------------------------------------------------------------------------
# TaskAdapterLayer
# ---------------------------------------------------------------------------

class TaskAdapterLayer:
    """Stateless adapter that normalizes heterogeneous inputs to CanonicalTask.

    Usage::

        adapter = TaskAdapterLayer()
        task = adapter.adapt(payload, origin=TaskOrigin.API_REQUEST)
        envelope = task.project_to_task_envelope()
        result = await router.route_envelope(envelope)
    """

    # ── Main adapt entry point ────────────────────────────────────────────

    def adapt(
        self,
        payload: Any,
        *,
        origin: Any = None,
        session_id: str = "",
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Any:
        """Normalize *payload* into a :class:`~core.canonical_task.CanonicalTask`.

        Parameters
        ----------
        payload:
            Any task input: dict, CanonicalTask, TaskEnvelope, orchestrator
            task, MCP call, skill invocation, etc.
        origin:
            :class:`~core.canonical_task.TaskOrigin` value (or string) for
            observability.  When omitted, origin is inferred from the payload.
        session_id:
            Optional session scope.
        trace_id:
            Existing trace identifier (a new one is generated if omitted).
        task_id:
            Existing task identifier (a new one is generated if omitted).

        Returns
        -------
        CanonicalTask
        """
        try:
            from core.canonical_task import (  # type: ignore
                CanonicalTask,
                TaskOrigin,
                build_canonical_task,
            )
        except Exception as exc:
            logger.error("TaskAdapterLayer.adapt: canonical_task unavailable: %s", exc)
            raise

        # ── Passthrough: already a CanonicalTask ─────────────────────────
        if isinstance(payload, CanonicalTask):
            _append_record(AdaptationRecord(
                task_id=payload.task_id,
                trace_id=payload.trace_id,
                origin=payload.intent.origin.value if hasattr(payload.intent.origin, "value") else str(payload.intent.origin),
                tool=payload.execution.tool,
                targets=list(payload.routing.selected_targets),
                was_passthrough=True,
            ))
            return payload

        # ── Fast path: TaskEnvelope → CanonicalTask ──────────────────────
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TE  # type: ignore
            if isinstance(payload, _TE):
                return self._from_task_envelope(payload, origin=origin, TaskOrigin=TaskOrigin, build=build_canonical_task)
        except Exception:
            pass

        # ── Resolve origin ────────────────────────────────────────────────
        resolved_origin = self._resolve_origin(origin, payload, TaskOrigin)

        # ── Dispatch to per-origin builder ────────────────────────────────
        raw = _extract_dict(payload)

        return self._build_from_raw(
            raw=raw,
            origin=resolved_origin,
            session_id=session_id,
            trace_id=trace_id,
            task_id=task_id,
            TaskOrigin=TaskOrigin,
            build=build_canonical_task,
        )

    # ── Per-origin builders ───────────────────────────────────────────────

    def _from_task_envelope(
        self,
        envelope: Any,
        *,
        origin: Any,
        TaskOrigin: Any,
        build: Any,
    ) -> Any:
        """Build a CanonicalTask from an existing TaskEnvelope."""
        resolved_origin = self._resolve_origin(origin, None, TaskOrigin) or TaskOrigin.UNKNOWN
        task = build(
            task_id=getattr(envelope, "task_id", None),
            trace_id=getattr(envelope, "trace_id", None),
            session_id=getattr(envelope, "session_id", None) or "",
            origin=resolved_origin,
            requested_action=getattr(envelope, "tool_name", "") or "",
            tool=getattr(envelope, "tool_name", "") or "",
            args=dict(getattr(envelope, "args", {}) or {}),
            selected_targets=list(getattr(envelope, "targets", []) or []),
            metadata={"adapted_from": "task_envelope"},
        )
        _append_record(AdaptationRecord(
            task_id=task.task_id,
            trace_id=task.trace_id,
            origin=resolved_origin.value if hasattr(resolved_origin, "value") else str(resolved_origin),
            tool=task.execution.tool,
            targets=list(task.routing.selected_targets),
            was_passthrough=True,
        ))
        return task

    def _build_from_raw(
        self,
        raw: Dict[str, Any],
        *,
        origin: Any,
        session_id: str,
        trace_id: Optional[str],
        task_id: Optional[str],
        TaskOrigin: Any,
        build: Any,
    ) -> Any:
        """Build a CanonicalTask from a raw dict."""
        tool = _pick_tool(raw)
        targets = _pick_targets(raw)
        args = _pick_args(raw)
        goal = str(raw.get("goal") or raw.get("description") or raw.get("intent") or "")
        reason = str(raw.get("reason") or raw.get("purpose") or "")

        # Extract identity fields
        tid = task_id or str(raw.get("task_id") or "")
        trid = trace_id or str(raw.get("trace_id") or "")
        sid = session_id or str(raw.get("session_id") or "")

        task = build(
            task_id=tid or None,
            trace_id=trid or None,
            session_id=sid,
            origin=origin,
            goal=goal,
            reason=reason,
            requested_action=tool,
            tool=tool,
            args=args,
            selected_targets=targets,
            metadata={"adapted_from": origin.value if hasattr(origin, "value") else str(origin)},
        )
        _append_record(AdaptationRecord(
            task_id=task.task_id,
            trace_id=task.trace_id,
            origin=origin.value if hasattr(origin, "value") else str(origin),
            tool=task.execution.tool,
            targets=list(task.routing.selected_targets),
            was_passthrough=False,
        ))
        return task

    # ── Origin resolution ─────────────────────────────────────────────────

    def _resolve_origin(self, origin: Any, payload: Any, TaskOrigin: Any) -> Any:
        """Resolve the TaskOrigin from caller hint or payload heuristics."""
        if origin is not None:
            if isinstance(origin, TaskOrigin):
                return origin
            try:
                return TaskOrigin(str(origin))
            except ValueError:
                pass
        # Heuristic from payload
        if payload is not None:
            raw = _extract_dict(payload) if not isinstance(payload, dict) else payload
            src = str(raw.get("source") or raw.get("origin") or "").lower()
            if "api" in src:
                return TaskOrigin.API_REQUEST
            if "ai" in src or "intent" in src or "agent" in src:
                return TaskOrigin.AI_INTENT
            if "workflow" in src or "step" in src:
                return TaskOrigin.WORKFLOW_STEP
            if "orchestrat" in src:
                return TaskOrigin.ORCHESTRATOR_TASK
            if "device" in src or "command" in src:
                return TaskOrigin.DEVICE_COMMAND
            if "mcp" in src:
                return TaskOrigin.MCP_TOOL_CALL
            if "skill" in src:
                return TaskOrigin.SKILL_INVOCATION
            if "scheduler" in src:
                return TaskOrigin.SCHEDULER
        return TaskOrigin.UNKNOWN


# ---------------------------------------------------------------------------
# Module-level singleton adapter
# ---------------------------------------------------------------------------

_adapter_instance: Optional[TaskAdapterLayer] = None


def _get_adapter() -> TaskAdapterLayer:
    global _adapter_instance
    if _adapter_instance is None:
        _adapter_instance = TaskAdapterLayer()
    return _adapter_instance


# ---------------------------------------------------------------------------
# Top-level helper
# ---------------------------------------------------------------------------

def adapt_to_canonical_task(
    payload: Any,
    *,
    origin: Any = None,
    session_id: str = "",
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
) -> Any:
    """Normalize *payload* into a :class:`~core.canonical_task.CanonicalTask`.

    Convenience wrapper around the module-level :class:`TaskAdapterLayer`
    singleton.

    Parameters
    ----------
    payload:
        Any task input (see module docstring for supported types).
    origin:
        :class:`~core.canonical_task.TaskOrigin` or string hint.
    session_id, trace_id, task_id:
        Optional identity overrides.

    Returns
    -------
    CanonicalTask
    """
    return _get_adapter().adapt(
        payload,
        origin=origin,
        session_id=session_id,
        trace_id=trace_id,
        task_id=task_id,
    )
