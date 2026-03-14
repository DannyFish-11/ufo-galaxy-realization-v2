#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — Audit Ledger
=====================================

Implements an append-only, in-memory event ledger for Control Plane tracing.
All significant actions (task dispatch, approval, execution, error) are
recorded as :class:`TraceEvent` objects that form a causal DAG via
``parent_ids`` links.

Key design decisions
---------------------
* **Immutability** – once appended, events are never mutated.
* **DAG-first** – every event carries ``parent_ids`` so the full causal
  history can be reconstructed without scanning the ledger in order.
* **Serialisation helpers** – :func:`events_to_json` and
  :func:`events_to_dag` allow downstream consumers (dashboards, replay
  engines) to consume the ledger without understanding its internals.
* **Thread/task safety** – a plain ``list`` is used; Python's GIL keeps
  single-operation appends safe.  For true concurrent writes, callers
  should hold their own lock.

Usage
-----
    from core.control_plane.audit_ledger import AuditLedger, EventType, Severity

    ledger = AuditLedger()
    eid = ledger.append(
        event_type=EventType.TASK_DISPATCHED,
        severity=Severity.INFO,
        source="scheduler",
        task_id="task_abc",
        payload={"device_id": "device_xyz"},
    )
    print(ledger.to_json())
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    """Coarse-grained categories for audit events."""

    # Task lifecycle
    TASK_CREATED = "task_created"
    TASK_DISPATCHED = "task_dispatched"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_RETRIED = "task_retried"

    # Agent / device events
    AGENT_CREATED = "agent_created"
    AGENT_DISPATCHED = "agent_dispatched"
    AGENT_EXECUTED = "agent_executed"
    AGENT_RESULT_RECEIVED = "agent_result_received"
    DEVICE_REGISTERED = "device_registered"
    DEVICE_HEARTBEAT = "device_heartbeat"
    DEVICE_DISCONNECTED = "device_disconnected"

    # Security / approval events
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    APPROVAL_TIMED_OUT = "approval_timed_out"

    # System events
    SYSTEM_ERROR = "system_error"
    CONFIG_CHANGED = "config_changed"
    SCHEDULER_DECISION = "scheduler_decision"


class Severity(str, Enum):
    """RFC-5424-inspired severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Core models
# ---------------------------------------------------------------------------

class TraceEvent(BaseModel):
    """A single immutable event in the audit ledger.

    The ``parent_ids`` field creates the causal DAG: each event points at
    the event(s) that directly caused it.  Root events (no parent) have an
    empty list.
    """

    event_id: str = Field(
        default_factory=lambda: f"ev_{uuid.uuid4().hex}",
        description="Globally unique event identifier.",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC wall-clock time when the event was recorded.",
    )
    event_type: EventType = Field(..., description="Semantic category of the event.")
    severity: Severity = Field(default=Severity.INFO, description="Log-level severity.")

    # Causal linkage
    parent_ids: List[str] = Field(
        default_factory=list,
        description=(
            "IDs of events that caused this event.  Empty for root events. "
            "Multiple parents are valid (e.g. a join node in a workflow)."
        ),
    )

    # Context identifiers
    trace_id: Optional[str] = Field(
        None,
        description="Distributed trace ID shared across an entire user request.",
    )
    task_id: Optional[str] = Field(None, description="Associated task ID, if any.")
    agent_id: Optional[str] = Field(None, description="Associated agent ID, if any.")
    device_id: Optional[str] = Field(None, description="Target / source device, if any.")
    session_id: Optional[str] = Field(None, description="User session, if applicable.")

    # Human-readable context
    source: str = Field(
        default="",
        description="Component that emitted this event (e.g. 'scheduler', 'security_interceptor').",
    )
    message: str = Field(
        default="",
        description="Short human-readable description of what happened.",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary structured data associated with the event.",
    )

    model_config = {"frozen": True}  # prevent post-creation mutation


class LedgerSnapshot(BaseModel):
    """Serialisable snapshot of the entire ledger at a point in time."""

    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:12]}")
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_count: int
    events: List[TraceEvent]


# ---------------------------------------------------------------------------
# DAG helpers
# ---------------------------------------------------------------------------

def events_to_dag(events: List[TraceEvent]) -> Dict[str, List[str]]:
    """Convert a list of :class:`TraceEvent` objects to an adjacency list.

    The adjacency list represents the **child → parent** direction:
    ``{ event_id: [parent_id, ...] }``.  This is DAG-friendly and can be
    fed directly into topological-sort or graph-visualisation libraries.

    Parameters
    ----------
    events:
        Any iterable of TraceEvent instances.

    Returns
    -------
    dict
        ``{ event_id: [parent_id, ...] }`` for every event in *events*.
        Events with no parents map to an empty list.
    """
    return {ev.event_id: list(ev.parent_ids) for ev in events}


def events_to_json(events: List[TraceEvent], *, indent: int = 2) -> str:
    """Serialise a list of TraceEvent objects to a JSON string.

    Each event is serialised via Pydantic's ``.model_dump()`` with
    ``mode="json"`` so that :class:`datetime` and :class:`Enum` values
    become JSON-safe strings.

    Parameters
    ----------
    events:
        Any iterable of TraceEvent instances.
    indent:
        JSON indentation level (default 2).

    Returns
    -------
    str
        Pretty-printed JSON array.
    """
    serialised = [ev.model_dump(mode="json") for ev in events]
    return json.dumps(serialised, ensure_ascii=False, indent=indent)


# ---------------------------------------------------------------------------
# In-memory ledger
# ---------------------------------------------------------------------------

class AuditLedger:
    """Append-only, in-memory store for :class:`TraceEvent` objects.

    Thread safety
    -------------
    Single-event ``append()`` is safe under CPython's GIL.  If you need
    atomic multi-event batches under true concurrency, wrap calls in an
    external ``threading.Lock``.
    """

    def __init__(self) -> None:
        self._events: List[TraceEvent] = []

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        event_type: EventType,
        *,
        severity: Severity = Severity.INFO,
        source: str = "",
        message: str = "",
        parent_ids: Optional[List[str]] = None,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Create and append a new :class:`TraceEvent`.

        Parameters
        ----------
        event_type:
            Semantic type of the event.
        severity:
            Log severity level.
        source:
            Emitting component name.
        message:
            Human-readable description.
        parent_ids:
            IDs of causally preceding events.
        trace_id / task_id / agent_id / device_id / session_id:
            Optional context identifiers.
        payload:
            Arbitrary structured data.

        Returns
        -------
        str
            The ``event_id`` of the newly created event.
        """
        event = TraceEvent(
            event_type=event_type,
            severity=severity,
            source=source,
            message=message,
            parent_ids=parent_ids or [],
            trace_id=trace_id,
            task_id=task_id,
            agent_id=agent_id,
            device_id=device_id,
            session_id=session_id,
            payload=payload or {},
        )
        self._events.append(event)
        return event.event_id

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def query(
        self,
        *,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        severity: Optional[Severity] = None,
        source: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[TraceEvent]:
        """Return events matching ALL supplied filter criteria.

        All filters are AND-combined.  Unset (``None``) filters are ignored.
        Results preserve insertion order; newest events last.

        Parameters
        ----------
        trace_id / task_id:
            Context-ID filters.
        event_type:
            Only return events of this type.
        severity:
            Only return events at this exact severity.
        source:
            Only return events from this component.
        limit:
            Cap the number of returned events (applied after filtering).
        """
        results: List[TraceEvent] = []
        for ev in self._events:
            if trace_id is not None and ev.trace_id != trace_id:
                continue
            if task_id is not None and ev.task_id != task_id:
                continue
            if event_type is not None and ev.event_type != event_type:
                continue
            if severity is not None and ev.severity != severity:
                continue
            if source is not None and ev.source != source:
                continue
            results.append(ev)
        if limit is not None:
            results = results[:limit]
        return results

    def get_by_id(self, event_id: str) -> Optional[TraceEvent]:
        """Return a single event by its ``event_id``, or ``None``."""
        for ev in self._events:
            if ev.event_id == event_id:
                return ev
        return None

    @property
    def all_events(self) -> List[TraceEvent]:
        """Read-only view of all events in insertion order."""
        return list(self._events)

    def __len__(self) -> int:
        return len(self._events)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self, *, indent: int = 2) -> str:
        """Serialise the entire ledger to a JSON string."""
        return events_to_json(self._events, indent=indent)

    def to_dag(self) -> Dict[str, List[str]]:
        """Return the full ledger as a DAG adjacency list."""
        return events_to_dag(self._events)

    def snapshot(self) -> LedgerSnapshot:
        """Return an immutable :class:`LedgerSnapshot` of the current state."""
        return LedgerSnapshot(
            event_count=len(self._events),
            events=list(self._events),
        )
