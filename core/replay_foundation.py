#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/replay_foundation.py
==========================
PR-E: Replay Foundation — Canonical Task Execution Replay & Audit Chassis.

Establishes the **Replay Foundation** for the Galaxy runtime.  This module
provides the data structures and runtime to record, query, and replay task
execution chains, route decisions, fallback/retry history, and result
lineage.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  REPLAY FOUNDATION  (this module, Layer 10)                     │
    │                                                                  │
    │  Records (write):                                               │
    │    • TaskExecutionRecord  — per-task execution snapshot         │
    │    • RuntimeEventRecord   — system-level audit event            │
    │    • RouteDecisionRecord  — routing/path decision snapshot      │
    │    • FallbackRecord       — fallback trigger and outcome        │
    │    • RetryRecord          — retry trigger and outcome           │
    │                                                                  │
    │  Queries (read):                                                │
    │    • get_execution_record(task_id)                              │
    │    • get_task_lineage(task_id)                                  │
    │    • get_route_decisions(task_id)                               │
    │    • get_fallback_history(task_id)                              │
    │    • get_retry_history(task_id)                                 │
    │    • get_result_lineage(task_id)                                │
    │    • replay_task_timeline(task_id) → ordered event list        │
    │    • snapshot()                                                 │
    │                                                                  │
    │  Downstream consumers:                                          │
    │    • OperatorSurface (inspect_lineage)                         │
    │    • AuditEventSemantics (structured audit trail)              │
    │    • Future: time-travel debugging / incident forensics        │
    └──────────────────────────────────────────────────────────────────┘

Design invariants
-----------------
1.  **Append-only.**  Records are never mutated after creation.
2.  **Serialisable.**  All record types provide ``to_dict()`` and
    ``from_dict()`` for persistence and replay.
3.  **Queryable by task_id and trace_id.**  Every record carries both
    identifiers so that full task lineage can be reconstructed.
4.  **256-entry ring buffer.**  The runtime keeps a ring buffer for
    recent records; older records can be archived externally.
5.  **Time-travel ready.**  ``replay_task_timeline`` returns an ordered
    event list that can be replayed step-by-step by a debugging tool.

Public API
----------
Authority sentinels::

    REPLAY_FOUNDATION_AUTHORITY
    REPLAY_FOUNDATION_LAYER_POSITION
    REPLAY_FOUNDATION_CONTRACT_VERSION
    REPLAY_ONLY_PRINCIPLE

Record types::

    ReplayEventKind
    TaskExecutionRecord
    RuntimeEventRecord
    RouteDecisionRecord
    ReplayFallbackRecord
    ReplayRetryRecord
    TaskLineage
    ReplayFoundationSnapshot

Class::

    ReplayFoundation

Helpers::

    record_task_execution(task) -> TaskExecutionRecord
    record_route_decision(task_id, ...) -> RouteDecisionRecord
    record_fallback(primary_task_id, fallback_task_id, reason) -> ReplayFallbackRecord
    record_retry(original_task_id, retry_task_id, reason, attempt) -> ReplayRetryRecord
    emit_runtime_event(kind, task_id, ...) -> RuntimeEventRecord
    get_replay_foundation() -> ReplayFoundation
    reset_replay_foundation() -> None   # testing only
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

try:
    from core.replay_audit_persistence import append_replay_audit_record as _append_audit_record
except ImportError:  # noqa: BLE001
    _append_audit_record = None  # type: ignore[assignment]

logger = logging.getLogger("Galaxy.ReplayFoundation")

__all__ = [
    # Authority sentinels
    "REPLAY_FOUNDATION_AUTHORITY",
    "REPLAY_FOUNDATION_LAYER_POSITION",
    "REPLAY_FOUNDATION_CONTRACT_VERSION",
    "REPLAY_ONLY_PRINCIPLE",
    "REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL",
    "REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY",
    # Enumerations
    "ReplayEventKind",
    # Record types
    "TaskExecutionRecord",
    "RuntimeEventRecord",
    "RouteDecisionRecord",
    "ReplayFallbackRecord",
    "ReplayRetryRecord",
    "TaskLineage",
    "ReplayFoundationSnapshot",
    # Class
    "ReplayFoundation",
    # Helpers
    "record_task_execution",
    "record_route_decision",
    "record_fallback",
    "record_retry",
    "emit_runtime_event",
    "get_replay_foundation",
    "reset_replay_foundation",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

REPLAY_FOUNDATION_AUTHORITY: str = "REPLAY_FOUNDATION_V1"
"""Sentinel: this module is the canonical replay/audit chassis for Galaxy.
Import to assert that a component records or replays execution records through
this foundation."""

REPLAY_FOUNDATION_LAYER_POSITION: int = 10
"""Layer position in the Galaxy architecture stack.
ReplayFoundation sits at layer 10 alongside OperatorSurface."""

REPLAY_FOUNDATION_CONTRACT_VERSION: str = "1.0"
"""Version of the ReplayFoundation record contract."""

REPLAY_ONLY_PRINCIPLE: str = (
    "REQUIRED: ReplayFoundation records are append-only and serialisable; "
    "replay consumers must not mutate records; "
    "all execution-chain events must be recorded here for time-travel support."
)
"""Principle: replay records are immutable; all key decisions are recorded."""

REPLAY_FOUNDATION_DURABLE_AUDIT_SENTINEL: str = (
    "REPLAY_FOUNDATION_DURABLE_AUDIT::PR_B2_V1: "
    "ReplayFoundation now supports an optional durable audit sink via "
    "ReplayFoundation.set_audit_store().  When a DurableAuditStore is "
    "attached, every appended record is also written to the JSONL store so "
    "replay history survives process lifetime.  (PR-B2)"
)
"""Sentinel confirming durable audit sink support is active (PR-B2)."""

REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY: str = (
    "REPLAY_FOUNDATION::OWNERSHIP_BOUNDARY_FIELD_POLICY_V1: "
    "TaskExecutionRecord.participant_ownership_boundary carries the ownership "
    "classification determined at the Android participant truth ingress "
    "boundary.  Allowed values: 'canonicalized', 'participant_local_only', "
    "'fallback_non_canonical', 'rejected_non_canonical', '' (unset). "
    "This field propagates ownership context from the ingress layer through "
    "to replay records so that replay/recovery consumers can distinguish "
    "canonical execution history from participant-local or fallback records. "
    "(PR-4V2 ownership chain, canonical ownership truth bridge)"
)
"""Policy: replay execution records carry participant ownership boundary."""

_NON_CANONICAL_OWNERSHIP_BOUNDARIES: frozenset = frozenset(
    {
        "participant_local_only",
        "fallback_non_canonical",
        "rejected_non_canonical",
    }
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class ReplayEventKind(str, Enum):
    """Kind of event recorded in the replay foundation."""

    # Task lifecycle
    TASK_CREATED = "task_created"
    TASK_ADMITTED = "task_admitted"
    TASK_PLANNED = "task_planned"
    TASK_ROUTED = "task_routed"
    TASK_DISPATCHED = "task_dispatched"
    TASK_RUNNING = "task_running"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"
    TASK_DEGRADED = "task_degraded"

    # Route / path events
    ROUTE_DECISION = "route_decision"
    ROUTE_SELECTED = "route_selected"
    ROUTE_FALLBACK = "route_fallback"

    # Execution events
    EXECUTOR_SELECTED = "executor_selected"
    EXECUTOR_RESULT = "executor_result"

    # Retry / fallback events
    RETRY_TRIGGERED = "retry_triggered"
    RETRY_SUCCEEDED = "retry_succeeded"
    RETRY_FAILED = "retry_failed"
    FALLBACK_TRIGGERED = "fallback_triggered"
    FALLBACK_SUCCEEDED = "fallback_succeeded"
    FALLBACK_FAILED = "fallback_failed"

    # Policy events
    POLICY_ADMIT = "policy_admit"
    POLICY_REJECT = "policy_reject"
    POLICY_DEGRADE = "policy_degrade"

    # Failure
    FAILURE_DOMAIN_IDENTIFIED = "failure_domain_identified"

    # Generic
    RUNTIME_EVENT = "runtime_event"


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------

@dataclass
class TaskExecutionRecord:
    """Immutable snapshot of a task execution for replay purposes.

    Created when a :class:`~core.canonical_task.CanonicalTask` reaches a
    terminal lifecycle state (COMPLETED, FAILED, CANCELLED, DEGRADED).

    Carries all fields needed to reconstruct the full execution story:
    - task identity and intent
    - route and executor selection
    - effective path used
    - fallback / retry summary
    - result lineage
    """

    record_id: str = field(
        default_factory=lambda: f"exec_{uuid.uuid4().hex[:16]}"
    )
    recorded_at: float = field(default_factory=time.time)

    # Identity
    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    root_task_id: str = ""
    parent_task_id: str = ""

    # Intent
    goal: str = ""
    origin: str = ""
    requested_action: str = ""

    # Lifecycle outcome
    final_lifecycle: str = ""
    success: Optional[bool] = None
    error_code: str = ""
    failure_domain: str = ""
    degradation_reason: str = ""

    # Route / executor
    selected_targets: List[str] = field(default_factory=list)
    transport_strategy: str = ""
    effective_path: str = ""
    executor_node_id: str = ""

    # Retry / fallback summary
    retry_count: int = 0
    fallback_triggered: bool = False
    fallback_task_id: str = ""

    # Ownership boundary (from Android participant truth ingress)
    # Allowed values: 'canonicalized', 'participant_local_only',
    # 'fallback_non_canonical', 'rejected_non_canonical', '' (unset).
    # Policy: REPLAY_RECORD_CARRIES_OWNERSHIP_BOUNDARY_POLICY
    participant_ownership_boundary: str = ""

    # Timestamps
    created_at: Optional[float] = None
    dispatched_at: Optional[float] = None
    completed_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "recorded_at": self.recorded_at,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "root_task_id": self.root_task_id,
            "parent_task_id": self.parent_task_id,
            "goal": self.goal,
            "origin": self.origin,
            "requested_action": self.requested_action,
            "final_lifecycle": self.final_lifecycle,
            "success": self.success,
            "error_code": self.error_code,
            "failure_domain": self.failure_domain,
            "degradation_reason": self.degradation_reason,
            "selected_targets": self.selected_targets,
            "transport_strategy": self.transport_strategy,
            "effective_path": self.effective_path,
            "executor_node_id": self.executor_node_id,
            "retry_count": self.retry_count,
            "fallback_triggered": self.fallback_triggered,
            "fallback_task_id": self.fallback_task_id,
            "participant_ownership_boundary": self.participant_ownership_boundary,
            "created_at": self.created_at,
            "dispatched_at": self.dispatched_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskExecutionRecord":
        return cls(
            record_id=data.get("record_id", f"exec_{uuid.uuid4().hex[:16]}"),
            recorded_at=data.get("recorded_at", time.time()),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            session_id=data.get("session_id", ""),
            root_task_id=data.get("root_task_id", ""),
            parent_task_id=data.get("parent_task_id", ""),
            goal=data.get("goal", ""),
            origin=data.get("origin", ""),
            requested_action=data.get("requested_action", ""),
            final_lifecycle=data.get("final_lifecycle", ""),
            success=data.get("success"),
            error_code=data.get("error_code", ""),
            failure_domain=data.get("failure_domain", ""),
            degradation_reason=data.get("degradation_reason", ""),
            selected_targets=data.get("selected_targets", []),
            transport_strategy=data.get("transport_strategy", ""),
            effective_path=data.get("effective_path", ""),
            executor_node_id=data.get("executor_node_id", ""),
            retry_count=data.get("retry_count", 0),
            fallback_triggered=data.get("fallback_triggered", False),
            fallback_task_id=data.get("fallback_task_id", ""),
            participant_ownership_boundary=data.get("participant_ownership_boundary", ""),
            created_at=data.get("created_at"),
            dispatched_at=data.get("dispatched_at"),
            completed_at=data.get("completed_at"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class RuntimeEventRecord:
    """Immutable audit record for a system-level runtime event.

    Used by :meth:`ReplayFoundation.emit_runtime_event` to record key
    decisions and transitions for audit and replay.
    """

    event_id: str = field(
        default_factory=lambda: f"ev_{uuid.uuid4().hex[:16]}"
    )
    recorded_at: float = field(default_factory=time.time)
    kind: str = ReplayEventKind.RUNTIME_EVENT
    task_id: str = ""
    trace_id: str = ""
    source: str = ""
    message: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)

    # Causal linkage for DAG reconstruction
    parent_event_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "recorded_at": self.recorded_at,
            "kind": self.kind,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source": self.source,
            "message": self.message,
            "payload": self.payload,
            "parent_event_ids": self.parent_event_ids,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeEventRecord":
        return cls(
            event_id=data.get("event_id", f"ev_{uuid.uuid4().hex[:16]}"),
            recorded_at=data.get("recorded_at", time.time()),
            kind=data.get("kind", ReplayEventKind.RUNTIME_EVENT),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            source=data.get("source", ""),
            message=data.get("message", ""),
            payload=data.get("payload", {}),
            parent_event_ids=data.get("parent_event_ids", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class RouteDecisionRecord:
    """Immutable snapshot of a routing decision for a task."""

    record_id: str = field(
        default_factory=lambda: f"route_{uuid.uuid4().hex[:12]}"
    )
    recorded_at: float = field(default_factory=time.time)

    task_id: str = ""
    trace_id: str = ""

    # Inputs that drove the decision
    requested_targets: List[str] = field(default_factory=list)
    required_capabilities: List[str] = field(default_factory=list)

    # Decision outputs
    selected_targets: List[str] = field(default_factory=list)
    transport_strategy: str = ""
    route_preference: str = ""
    effective_path: str = ""
    fallback_available: bool = False

    # Policy context
    capability_fit: bool = False
    policy_score: float = 0.0
    transport_usable: bool = False
    admissibility_verdict: str = ""
    route_explanation: str = ""
    degradation_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "recorded_at": self.recorded_at,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "requested_targets": self.requested_targets,
            "required_capabilities": self.required_capabilities,
            "selected_targets": self.selected_targets,
            "transport_strategy": self.transport_strategy,
            "route_preference": self.route_preference,
            "effective_path": self.effective_path,
            "fallback_available": self.fallback_available,
            "capability_fit": self.capability_fit,
            "policy_score": self.policy_score,
            "transport_usable": self.transport_usable,
            "admissibility_verdict": self.admissibility_verdict,
            "route_explanation": self.route_explanation,
            "degradation_reason": self.degradation_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RouteDecisionRecord":
        return cls(
            record_id=data.get("record_id", f"route_{uuid.uuid4().hex[:12]}"),
            recorded_at=data.get("recorded_at", time.time()),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            requested_targets=data.get("requested_targets", []),
            required_capabilities=data.get("required_capabilities", []),
            selected_targets=data.get("selected_targets", []),
            transport_strategy=data.get("transport_strategy", ""),
            route_preference=data.get("route_preference", ""),
            effective_path=data.get("effective_path", ""),
            fallback_available=data.get("fallback_available", False),
            capability_fit=data.get("capability_fit", False),
            policy_score=data.get("policy_score", 0.0),
            transport_usable=data.get("transport_usable", False),
            admissibility_verdict=data.get("admissibility_verdict", ""),
            route_explanation=data.get("route_explanation", ""),
            degradation_reason=data.get("degradation_reason", ""),
        )


@dataclass
class ReplayFallbackRecord:
    """Immutable record of a fallback trigger in the execution chain."""

    record_id: str = field(
        default_factory=lambda: f"fallback_{uuid.uuid4().hex[:12]}"
    )
    recorded_at: float = field(default_factory=time.time)

    primary_task_id: str = ""
    fallback_task_id: str = ""
    trace_id: str = ""

    reason: str = ""
    primary_failure_domain: str = ""
    primary_error_code: str = ""

    # Outcome
    fallback_succeeded: Optional[bool] = None
    fallback_lifecycle: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "recorded_at": self.recorded_at,
            "primary_task_id": self.primary_task_id,
            "fallback_task_id": self.fallback_task_id,
            "trace_id": self.trace_id,
            "reason": self.reason,
            "primary_failure_domain": self.primary_failure_domain,
            "primary_error_code": self.primary_error_code,
            "fallback_succeeded": self.fallback_succeeded,
            "fallback_lifecycle": self.fallback_lifecycle,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplayFallbackRecord":
        return cls(
            record_id=data.get("record_id", f"fallback_{uuid.uuid4().hex[:12]}"),
            recorded_at=data.get("recorded_at", time.time()),
            primary_task_id=data.get("primary_task_id", ""),
            fallback_task_id=data.get("fallback_task_id", ""),
            trace_id=data.get("trace_id", ""),
            reason=data.get("reason", ""),
            primary_failure_domain=data.get("primary_failure_domain", ""),
            primary_error_code=data.get("primary_error_code", ""),
            fallback_succeeded=data.get("fallback_succeeded"),
            fallback_lifecycle=data.get("fallback_lifecycle", ""),
        )


@dataclass
class ReplayRetryRecord:
    """Immutable record of a retry trigger in the execution chain."""

    record_id: str = field(
        default_factory=lambda: f"retry_{uuid.uuid4().hex[:12]}"
    )
    recorded_at: float = field(default_factory=time.time)

    original_task_id: str = ""
    retry_task_id: str = ""
    trace_id: str = ""

    attempt_number: int = 1
    reason: str = ""
    original_error_code: str = ""

    # Outcome
    retry_succeeded: Optional[bool] = None
    retry_lifecycle: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "recorded_at": self.recorded_at,
            "original_task_id": self.original_task_id,
            "retry_task_id": self.retry_task_id,
            "trace_id": self.trace_id,
            "attempt_number": self.attempt_number,
            "reason": self.reason,
            "original_error_code": self.original_error_code,
            "retry_succeeded": self.retry_succeeded,
            "retry_lifecycle": self.retry_lifecycle,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ReplayRetryRecord":
        return cls(
            record_id=data.get("record_id", f"retry_{uuid.uuid4().hex[:12]}"),
            recorded_at=data.get("recorded_at", time.time()),
            original_task_id=data.get("original_task_id", ""),
            retry_task_id=data.get("retry_task_id", ""),
            trace_id=data.get("trace_id", ""),
            attempt_number=data.get("attempt_number", 1),
            reason=data.get("reason", ""),
            original_error_code=data.get("original_error_code", ""),
            retry_succeeded=data.get("retry_succeeded"),
            retry_lifecycle=data.get("retry_lifecycle", ""),
        )


@dataclass
class TaskLineage:
    """Reconstructed lineage of a task from replay records."""

    task_id: str = ""
    trace_id: str = ""
    root_task_id: str = ""

    execution_record: Optional[TaskExecutionRecord] = None
    route_decisions: List[RouteDecisionRecord] = field(default_factory=list)
    fallback_history: List[ReplayFallbackRecord] = field(default_factory=list)
    retry_history: List[ReplayRetryRecord] = field(default_factory=list)

    # Ordered replay timeline
    replay_timeline: List[RuntimeEventRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "root_task_id": self.root_task_id,
            "execution_record": (
                self.execution_record.to_dict()
                if self.execution_record else None
            ),
            "route_decisions": [r.to_dict() for r in self.route_decisions],
            "fallback_history": [r.to_dict() for r in self.fallback_history],
            "retry_history": [r.to_dict() for r in self.retry_history],
            "replay_timeline": [e.to_dict() for e in self.replay_timeline],
        }


@dataclass
class ReplayFoundationSnapshot:
    """Snapshot of the replay foundation ring buffers."""

    snapshot_id: str = field(
        default_factory=lambda: f"rfsnap_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)

    execution_record_count: int = 0
    non_canonical_rejected_count: int = 0
    runtime_event_count: int = 0
    route_decision_count: int = 0
    fallback_record_count: int = 0
    retry_record_count: int = 0

    recent_execution_records: List[Dict[str, Any]] = field(default_factory=list)
    recent_non_canonical_execution_records: List[Dict[str, Any]] = field(default_factory=list)
    recent_runtime_events: List[Dict[str, Any]] = field(default_factory=list)

    authority: str = REPLAY_FOUNDATION_AUTHORITY
    contract_version: str = REPLAY_FOUNDATION_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "execution_record_count": self.execution_record_count,
            "non_canonical_rejected_count": self.non_canonical_rejected_count,
            "runtime_event_count": self.runtime_event_count,
            "route_decision_count": self.route_decision_count,
            "fallback_record_count": self.fallback_record_count,
            "retry_record_count": self.retry_record_count,
            "recent_execution_records": self.recent_execution_records,
            "recent_non_canonical_execution_records": self.recent_non_canonical_execution_records,
            "recent_runtime_events": self.recent_runtime_events,
            "authority": self.authority,
            "contract_version": self.contract_version,
        }


# ---------------------------------------------------------------------------
# ReplayFoundation — main class
# ---------------------------------------------------------------------------

class ReplayFoundation:
    """Canonical replay and audit foundation for the Galaxy runtime.

    Maintains append-only ring buffers of:
    - :class:`TaskExecutionRecord` — per-task execution snapshots
    - :class:`RuntimeEventRecord`  — ordered audit event stream
    - :class:`RouteDecisionRecord` — routing decision snapshots
    - :class:`ReplayFallbackRecord`— fallback trigger records
    - :class:`ReplayRetryRecord`   — retry trigger records

    Provides query APIs to reconstruct task lineage and replay execution
    timelines.  Does NOT perform any dispatch or mutation of canonical state.

    Durable audit sink (PR-B2)
    --------------------------
    When :meth:`set_audit_store` has been called with a
    :class:`~core.replay_audit_persistence.DurableAuditStore`, every record
    appended to the ring buffers is **also** written to the durable JSONL
    store.  The ring buffers remain the authoritative in-process read
    surfaces; the durable store provides forensic reviewability across
    process lifetimes.
    """

    _MAX_RING: int = 256

    def __init__(self) -> None:
        self._execution_records: Dict[str, TaskExecutionRecord] = {}
        self._execution_ring: Deque[TaskExecutionRecord] = deque(
            maxlen=self._MAX_RING
        )
        self._non_canonical_execution_ring: Deque[TaskExecutionRecord] = deque(
            maxlen=self._MAX_RING
        )
        self._non_canonical_rejected_count: int = 0
        self._event_ring: Deque[RuntimeEventRecord] = deque(
            maxlen=self._MAX_RING
        )
        # Secondary indexes by task_id
        self._events_by_task: Dict[str, List[RuntimeEventRecord]] = {}
        self._routes_by_task: Dict[str, List[RouteDecisionRecord]] = {}
        self._fallbacks_by_task: Dict[str, List[ReplayFallbackRecord]] = {}
        self._retries_by_task: Dict[str, List[ReplayRetryRecord]] = {}
        # Optional durable audit sink (PR-B2)
        self._audit_store: Optional[Any] = None

    # ── Durable audit sink ───────────────────────────────────────────────

    def set_audit_store(self, store: Any) -> None:
        """Attach a :class:`~core.replay_audit_persistence.DurableAuditStore`.

        Once attached, every record appended to this foundation is also
        written to *store* for durable auditability (PR-B2).

        Parameters
        ----------
        store:
            A :class:`~core.replay_audit_persistence.DurableAuditStore`
            instance.  Pass ``None`` to detach.
        """
        self._audit_store = store

    def _durable_append(self, record_dict: Dict[str, Any], kind: str) -> None:
        """Write *record_dict* to the durable audit store if one is attached."""
        if self._audit_store is None:
            return
        if _append_audit_record is None:
            return
        try:
            _append_audit_record(record_dict, kind, store=self._audit_store)
        except Exception as _exc:  # noqa: BLE001
            logger.debug(
                "ReplayFoundation: durable audit append failed (kind=%s): %s",
                kind,
                _exc,
            )

    # ── Execution Records ────────────────────────────────────────────────

    def record_execution(self, record: TaskExecutionRecord) -> TaskExecutionRecord:
        """Append a :class:`TaskExecutionRecord` to the foundation.

        Idempotent by ``record_id``.  When a durable audit store is attached,
        the record is also written to the store (PR-B2).
        """
        boundary = str(record.participant_ownership_boundary or "")
        if boundary in _NON_CANONICAL_OWNERSHIP_BOUNDARIES:
            self._non_canonical_execution_ring.append(record)
            self._non_canonical_rejected_count += 1
            self._durable_append(
                {
                    **record.to_dict(),
                    "_non_canonical_blocked": True,
                    "ownership_admission_eligible": False,
                },
                "task_execution_non_canonical_blocked",
            )
            return record
        self._execution_records[record.record_id] = record
        self._execution_ring.append(record)
        self._durable_append(record.to_dict(), "task_execution")
        return record

    def get_execution_record(self, task_id: str) -> Optional[TaskExecutionRecord]:
        """Return the most-recent execution record for *task_id*, or ``None``."""
        for rec in reversed(self._execution_ring):
            if rec.task_id == task_id:
                return rec
        return None

    # ── Runtime Events ───────────────────────────────────────────────────

    def emit_event(self, event: RuntimeEventRecord) -> RuntimeEventRecord:
        """Append a :class:`RuntimeEventRecord` to the event ring.

        When a durable audit store is attached, the event is also written to
        the store for persistent auditability (PR-B2).
        """
        self._event_ring.append(event)
        if event.task_id:
            self._events_by_task.setdefault(event.task_id, []).append(event)
        self._durable_append(event.to_dict(), "runtime_event")
        return event

    def get_events_for_task(self, task_id: str) -> List[RuntimeEventRecord]:
        """Return all events recorded for *task_id*, in insertion order."""
        return list(self._events_by_task.get(task_id, []))

    # ── Route Decisions ──────────────────────────────────────────────────

    def record_route(self, record: RouteDecisionRecord) -> RouteDecisionRecord:
        """Append a :class:`RouteDecisionRecord`.

        When a durable audit store is attached, the record is also written to
        the store for persistent auditability (PR-B2).
        """
        if record.task_id:
            self._routes_by_task.setdefault(record.task_id, []).append(record)
        self._durable_append(record.to_dict(), "route_decision")
        return record

    def get_route_decisions(self, task_id: str) -> List[RouteDecisionRecord]:
        """Return all route decisions recorded for *task_id*."""
        return list(self._routes_by_task.get(task_id, []))

    # ── Fallback Records ─────────────────────────────────────────────────

    def record_fallback(self, record: ReplayFallbackRecord) -> ReplayFallbackRecord:
        """Append a :class:`ReplayFallbackRecord`.

        When a durable audit store is attached, the record is also written to
        the store for persistent auditability (PR-B2).
        """
        if record.primary_task_id:
            self._fallbacks_by_task.setdefault(
                record.primary_task_id, []
            ).append(record)
        self._durable_append(record.to_dict(), "fallback")
        return record

    def get_fallback_history(self, task_id: str) -> List[ReplayFallbackRecord]:
        """Return all fallback records for *task_id* as primary task."""
        return list(self._fallbacks_by_task.get(task_id, []))

    # ── Retry Records ────────────────────────────────────────────────────

    def record_retry(self, record: ReplayRetryRecord) -> ReplayRetryRecord:
        """Append a :class:`ReplayRetryRecord`.

        When a durable audit store is attached, the record is also written to
        the store for persistent auditability (PR-B2).
        """
        if record.original_task_id:
            self._retries_by_task.setdefault(
                record.original_task_id, []
            ).append(record)
        self._durable_append(record.to_dict(), "retry")
        return record

    def get_retry_history(self, task_id: str) -> List[ReplayRetryRecord]:
        """Return all retry records for *task_id* as original task."""
        return list(self._retries_by_task.get(task_id, []))

    # ── Lineage / Timeline ───────────────────────────────────────────────

    def get_task_lineage(self, task_id: str) -> TaskLineage:
        """Reconstruct the full :class:`TaskLineage` for *task_id*.

        Always returns a :class:`TaskLineage` — fields will be empty if no
        records exist for the task.
        """
        exec_rec = self.get_execution_record(task_id)
        trace_id = exec_rec.trace_id if exec_rec else ""
        root_id = exec_rec.root_task_id if exec_rec else task_id

        events = self.get_events_for_task(task_id)
        sorted_events = sorted(events, key=lambda e: e.recorded_at)

        return TaskLineage(
            task_id=task_id,
            trace_id=trace_id,
            root_task_id=root_id,
            execution_record=exec_rec,
            route_decisions=self.get_route_decisions(task_id),
            fallback_history=self.get_fallback_history(task_id),
            retry_history=self.get_retry_history(task_id),
            replay_timeline=sorted_events,
        )

    def replay_task_timeline(self, task_id: str) -> List[Dict[str, Any]]:
        """Return an ordered list of event dicts suitable for time-travel replay.

        Each entry is a serialised :class:`RuntimeEventRecord` dict, sorted by
        ``recorded_at``.
        """
        lineage = self.get_task_lineage(task_id)
        return [e.to_dict() for e in lineage.replay_timeline]

    def get_result_lineage(self, task_id: str) -> Dict[str, Any]:
        """Return a concise result lineage summary for *task_id*."""
        exec_rec = self.get_execution_record(task_id)
        fallbacks = self.get_fallback_history(task_id)
        retries = self.get_retry_history(task_id)
        return {
            "task_id": task_id,
            "final_lifecycle": exec_rec.final_lifecycle if exec_rec else "",
            "success": exec_rec.success if exec_rec else None,
            "failure_domain": exec_rec.failure_domain if exec_rec else "",
            "retry_count": len(retries),
            "fallback_count": len(fallbacks),
            "effective_path": exec_rec.effective_path if exec_rec else "",
            "executor_node_id": exec_rec.executor_node_id if exec_rec else "",
        }

    # ── Snapshot ─────────────────────────────────────────────────────────

    def snapshot(self) -> ReplayFoundationSnapshot:
        """Return a :class:`ReplayFoundationSnapshot` of recent ring-buffer state."""
        recent_exec = list(self._execution_ring)[-20:]
        recent_non_canonical_exec = list(self._non_canonical_execution_ring)[-20:]
        recent_events = list(self._event_ring)[-20:]
        return ReplayFoundationSnapshot(
            execution_record_count=len(self._execution_ring),
            non_canonical_rejected_count=self._non_canonical_rejected_count,
            runtime_event_count=len(self._event_ring),
            route_decision_count=sum(
                len(v) for v in self._routes_by_task.values()
            ),
            fallback_record_count=sum(
                len(v) for v in self._fallbacks_by_task.values()
            ),
            retry_record_count=sum(
                len(v) for v in self._retries_by_task.values()
            ),
            recent_execution_records=[r.to_dict() for r in recent_exec],
            recent_non_canonical_execution_records=[r.to_dict() for r in recent_non_canonical_exec],
            recent_runtime_events=[e.to_dict() for e in recent_events],
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_FOUNDATION: Optional[ReplayFoundation] = None


def get_replay_foundation() -> ReplayFoundation:
    """Return the singleton :class:`ReplayFoundation` instance."""
    global _FOUNDATION
    if _FOUNDATION is None:
        _FOUNDATION = ReplayFoundation()
    return _FOUNDATION


def reset_replay_foundation() -> None:
    """Reset the singleton — for testing only."""
    global _FOUNDATION
    _FOUNDATION = None


# ---------------------------------------------------------------------------
# Module-level helper functions
# ---------------------------------------------------------------------------

def record_task_execution(task: Any) -> TaskExecutionRecord:
    """Build and record a :class:`TaskExecutionRecord` from a ``CanonicalTask``.

    Gracefully handles missing fields so that partial task objects do not
    cause exceptions.

    Parameters
    ----------
    task:
        A :class:`~core.canonical_task.CanonicalTask` instance.
    """
    try:
        rec = TaskExecutionRecord(
            task_id=task.identity.task_id,
            trace_id=task.identity.trace_id,
            session_id=task.identity.session_id,
            root_task_id=task.identity.root_task_id,
            parent_task_id=task.identity.parent_task_id,
            goal=task.intent.goal,
            origin=task.intent.origin.value if task.intent.origin else "",
            requested_action=task.intent.requested_action,
            final_lifecycle=task.lifecycle.value,
            success=task.result.success,
            error_code=task.result.error_code,
            failure_domain=(
                task.result.failure_domain.value
                if hasattr(task.result.failure_domain, "value")
                else str(task.result.failure_domain)
            ),
            selected_targets=list(task.routing.selected_targets),
            transport_strategy=getattr(task.routing, "transport_preference", ""),
            effective_path=task.routing.effective_path,
            created_at=task.created_at,
            dispatched_at=task.dispatched_at,
            completed_at=task.completed_at,
        )
    except Exception as exc:
        logger.warning("record_task_execution: failed to extract fields: %s", exc)
        rec = TaskExecutionRecord(
            task_id=getattr(getattr(task, "identity", None), "task_id", ""),
        )
    get_replay_foundation().record_execution(rec)
    return rec


def record_route_decision(
    task_id: str,
    trace_id: str = "",
    *,
    selected_targets: Optional[List[str]] = None,
    transport_strategy: str = "",
    effective_path: str = "",
    route_explanation: str = "",
    degradation_reason: str = "",
    capability_fit: bool = False,
    policy_score: float = 0.0,
    transport_usable: bool = False,
    admissibility_verdict: str = "",
    fallback_available: bool = False,
) -> RouteDecisionRecord:
    """Build and record a :class:`RouteDecisionRecord`.

    Parameters
    ----------
    task_id:
        task_id of the task for which the routing decision was made.
    trace_id:
        Optional distributed trace ID.
    """
    rec = RouteDecisionRecord(
        task_id=task_id,
        trace_id=trace_id,
        selected_targets=selected_targets or [],
        transport_strategy=transport_strategy,
        effective_path=effective_path,
        route_explanation=route_explanation,
        degradation_reason=degradation_reason,
        capability_fit=capability_fit,
        policy_score=policy_score,
        transport_usable=transport_usable,
        admissibility_verdict=admissibility_verdict,
        fallback_available=fallback_available,
    )
    get_replay_foundation().record_route(rec)
    return rec


def record_fallback(
    primary_task_id: str,
    fallback_task_id: str,
    reason: str = "",
    *,
    trace_id: str = "",
    primary_failure_domain: str = "",
    primary_error_code: str = "",
) -> ReplayFallbackRecord:
    """Build and record a :class:`ReplayFallbackRecord`."""
    rec = ReplayFallbackRecord(
        primary_task_id=primary_task_id,
        fallback_task_id=fallback_task_id,
        trace_id=trace_id,
        reason=reason,
        primary_failure_domain=primary_failure_domain,
        primary_error_code=primary_error_code,
    )
    get_replay_foundation().record_fallback(rec)
    return rec


def record_retry(
    original_task_id: str,
    retry_task_id: str,
    reason: str = "",
    attempt_number: int = 1,
    *,
    trace_id: str = "",
    original_error_code: str = "",
) -> ReplayRetryRecord:
    """Build and record a :class:`ReplayRetryRecord`."""
    rec = ReplayRetryRecord(
        original_task_id=original_task_id,
        retry_task_id=retry_task_id,
        trace_id=trace_id,
        attempt_number=attempt_number,
        reason=reason,
        original_error_code=original_error_code,
    )
    get_replay_foundation().record_retry(rec)
    return rec


def emit_runtime_event(
    kind: str,
    task_id: str = "",
    *,
    trace_id: str = "",
    source: str = "",
    message: str = "",
    payload: Optional[Dict[str, Any]] = None,
    parent_event_ids: Optional[List[str]] = None,
) -> RuntimeEventRecord:
    """Build and emit a :class:`RuntimeEventRecord` to the foundation.

    Parameters
    ----------
    kind:
        :class:`ReplayEventKind` value (or a custom string).
    task_id:
        task_id this event relates to.
    """
    ev = RuntimeEventRecord(
        kind=kind,
        task_id=task_id,
        trace_id=trace_id,
        source=source,
        message=message,
        payload=payload or {},
        parent_event_ids=parent_event_ids or [],
    )
    get_replay_foundation().emit_event(ev)
    return ev
