"""
core.execution_observability.trace_schema
==========================================

Defines :class:`TraceCorrelation` — the canonical set of trace-correlation
fields shared across all Galaxy execution paths.

Background
----------
``trace_id`` is already propagated in:

* ``core/e2e_orchestrator.py``                            (generated per request)
* ``core/continuum/orchestrator.py``                      (passed to sub-engines)
* ``galaxy_gateway/orchestrator/task_orchestrator.py``    (from TaskEnvelope)
* ``core/task_graph.py``                                  (stored on TaskGraph)
* ``core/unified/command_envelope.py``                    (CommandEnvelope.trace_id)

This module provides a single *normalised* shape so that downstream consumers
(RuntimeProjection, Status Board v2, Manifest stage) do not have to parse each
source independently.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TraceCorrelation:
    """Canonical trace-correlation fields for a single execution event.

    Attributes
    ----------
    trace_id:
        Top-level distributed trace identifier.  Always non-empty; generated
        automatically when missing.
    runtime_session_id:
        Session identifier (maps to ``runtime_session_id`` in TaskGraph /
        CommandEnvelope).  May be empty for fire-and-forget calls.
    task_id:
        Optional task identifier (``TaskGraph.graph_id``,
        ``TaskEnvelope.task_id``, etc.).
    action_id:
        Optional fine-grained action identifier within a task.
    """

    trace_id: str = ""
    runtime_session_id: str = ""
    task_id: Optional[str] = None
    action_id: Optional[str] = None

    def __post_init__(self) -> None:
        # Ensure trace_id is never empty
        if not self.trace_id:
            self.trace_id = uuid.uuid4().hex

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def new(cls, *, runtime_session_id: str = "", task_id: Optional[str] = None,
            action_id: Optional[str] = None) -> "TraceCorrelation":
        """Create a fresh :class:`TraceCorrelation` with a generated trace_id."""
        return cls(
            trace_id=uuid.uuid4().hex,
            runtime_session_id=runtime_session_id,
            task_id=task_id,
            action_id=action_id,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceCorrelation":
        """Build from a plain dict, tolerating missing or ``None`` values.

        All fields default gracefully; ``trace_id`` is generated if absent.
        """
        return cls(
            trace_id=data.get("trace_id") or "",
            runtime_session_id=data.get("runtime_session_id") or "",
            task_id=data.get("task_id"),
            action_id=data.get("action_id"),
        )

    @classmethod
    def from_e2e_context(cls, ctx: Dict[str, Any]) -> "TraceCorrelation":
        """Normalise trace fields from ``core/e2e_orchestrator.py`` context dicts.

        The e2e orchestrator stores trace fields at the top level of the
        context dict (``ctx["trace_id"]``, ``ctx["runtime_session_id"]``, etc.).
        """
        return cls.from_dict(ctx)

    @classmethod
    def from_task_envelope(cls, envelope: Any) -> "TraceCorrelation":
        """Normalise from a ``TaskEnvelope`` or ``CommandEnvelope`` object.

        Accepts any object with ``trace_id`` / ``runtime_session_id`` /
        ``task_id`` attributes, or a plain dict.
        """
        if isinstance(envelope, dict):
            return cls.from_dict(envelope)
        return cls(
            trace_id=getattr(envelope, "trace_id", "") or "",
            runtime_session_id=getattr(envelope, "runtime_session_id", "") or "",
            task_id=getattr(envelope, "task_id", None) or None,
            action_id=getattr(envelope, "action_id", None) or None,
        )

    @classmethod
    def from_task_graph(cls, graph: Any) -> "TraceCorrelation":
        """Normalise from a :class:`~core.task_graph.TaskGraph` instance.

        ``TaskGraph`` exposes ``trace_id``, ``runtime_session_id``, and
        ``graph_id`` (used as task_id when no explicit task_id is set).
        """
        if isinstance(graph, dict):
            return cls.from_dict(graph)
        return cls(
            trace_id=getattr(graph, "trace_id", "") or "",
            runtime_session_id=getattr(graph, "runtime_session_id", "") or "",
            task_id=getattr(graph, "graph_id", None) or None,
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        result: Dict[str, Any] = {
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
        }
        if self.task_id is not None:
            result["task_id"] = self.task_id
        if self.action_id is not None:
            result["action_id"] = self.action_id
        return result

    def child(self, *, action_id: Optional[str] = None) -> "TraceCorrelation":
        """Return a child correlation that inherits trace/session/task context."""
        return TraceCorrelation(
            trace_id=self.trace_id,
            runtime_session_id=self.runtime_session_id,
            task_id=self.task_id,
            action_id=action_id or self.action_id,
        )
