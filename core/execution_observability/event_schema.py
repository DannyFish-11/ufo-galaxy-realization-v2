"""
core.execution_observability.event_schema
==========================================

Defines :class:`ExecutionEvent` — the top-level, serialisable event schema
that unifies trace, executor-level, fallback, and runtime-context fields.

Design principles
-----------------
* **Additive** — constructed from data already flowing through existing paths;
  nothing is removed.
* **Optional** — tri_state_phase, runtime_domain, and fallback_context are
  all optional so that callers that do not have these fields do not need to
  supply dummy values.
* **Import-light** — tri-state/domain enums are referenced by *string* value
  to avoid hard coupling with ``core.continuum.types`` in every consumer.
  Convenience constructors are provided that accept the real enum objects.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .executor_level import ExecutorLevel
from .fallback_schema import FallbackContext, FallbackReason
from .trace_schema import TraceCorrelation


@dataclass
class ExecutionEvent:
    """A single, unified execution-observability event.

    Attributes
    ----------
    event_id:
        Auto-generated unique ID for this event record.
    timestamp:
        Unix epoch (float) when the event was created.
    trace:
        :class:`TraceCorrelation` carrying trace/session/task/action IDs.
    executor_level:
        Which :class:`ExecutorLevel` tier handled (or attempted to handle)
        this action.
    fallback:
        Optional :class:`FallbackContext` describing why a fallback occurred.
    tri_state_phase:
        String value of the ``TriStatePhase`` active when this event was
        emitted (``"silent"`` / ``"liminal"`` / ``"manifest"``), if known.
    runtime_domain:
        String value of the ``RuntimeDomain`` (``"local"`` / ``"cross_device"``
        / ``"transition"``), if known.
    message:
        Human-readable description of what happened.
    metadata:
        Arbitrary key-value pairs for additional context.
    """

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    trace: TraceCorrelation = field(default_factory=TraceCorrelation.new)
    executor_level: ExecutorLevel = ExecutorLevel.UNKNOWN
    fallback: Optional[FallbackContext] = None
    tri_state_phase: Optional[str] = None
    runtime_domain: Optional[str] = None
    message: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience factories
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionEvent":
        """Reconstruct an :class:`ExecutionEvent` from a plain dict.

        Tolerates partial / missing fields.
        """
        trace_raw = data.get("trace") or {}
        fallback_raw = data.get("fallback")
        return cls(
            event_id=data.get("event_id") or uuid.uuid4().hex,
            timestamp=float(data.get("timestamp") or time.time()),
            trace=TraceCorrelation.from_dict(trace_raw if isinstance(trace_raw, dict) else {}),
            executor_level=ExecutorLevel.from_string(data.get("executor_level") or ""),
            fallback=FallbackContext.from_dict(fallback_raw) if isinstance(fallback_raw, dict) else None,
            tri_state_phase=data.get("tri_state_phase") or None,
            runtime_domain=data.get("runtime_domain") or None,
            message=data.get("message") or "",
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def build(
        cls,
        *,
        trace: Optional[TraceCorrelation] = None,
        executor_level: ExecutorLevel = ExecutorLevel.UNKNOWN,
        fallback: Optional[FallbackContext] = None,
        tri_state_phase: Optional[Any] = None,
        runtime_domain: Optional[Any] = None,
        message: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "ExecutionEvent":
        """Convenience constructor with sensible defaults.

        ``tri_state_phase`` and ``runtime_domain`` may be supplied as enum
        instances (from ``core.continuum.types``) or plain strings — both are
        normalised to their ``.value`` string.
        """
        def _to_str(v: Any) -> Optional[str]:
            if v is None:
                return None
            return v.value if hasattr(v, "value") else str(v)

        return cls(
            trace=trace if trace is not None else TraceCorrelation.new(),
            executor_level=executor_level,
            fallback=fallback,
            tri_state_phase=_to_str(tri_state_phase),
            runtime_domain=_to_str(runtime_domain),
            message=message,
            metadata=dict(metadata or {}),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        result: Dict[str, Any] = {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "trace": self.trace.to_dict(),
            "executor_level": self.executor_level.value,
            "message": self.message,
        }
        if self.fallback is not None:
            result["fallback"] = self.fallback.to_dict()
        if self.tri_state_phase is not None:
            result["tri_state_phase"] = self.tri_state_phase
        if self.runtime_domain is not None:
            result["runtime_domain"] = self.runtime_domain
        if self.metadata:
            result["metadata"] = self.metadata
        return result

    # ------------------------------------------------------------------
    # Projection helpers
    # ------------------------------------------------------------------

    def projection_summary(self) -> Dict[str, Any]:
        """Return a compact summary suitable for Status Board / Manifest consumers.

        Only includes fields that are non-empty / non-default, keeping
        payloads small when the full event is not needed.
        """
        summary: Dict[str, Any] = {
            "trace_id": self.trace.trace_id,
            "executor_level": self.executor_level.value,
        }
        if self.trace.task_id:
            summary["task_id"] = self.trace.task_id
        if self.trace.action_id:
            summary["action_id"] = self.trace.action_id
        if self.tri_state_phase:
            summary["tri_state_phase"] = self.tri_state_phase
        if self.runtime_domain:
            summary["runtime_domain"] = self.runtime_domain
        if self.fallback:
            summary["fallback_reason"] = self.fallback.reason.value
        if self.message:
            summary["message"] = self.message
        return summary
