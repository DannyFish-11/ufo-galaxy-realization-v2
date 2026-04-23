#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/audit_event_semantics.py
==============================
PR-E: Audit Event Semantics — Canonical Unified Audit Event Vocabulary.

Establishes the single **Audit Event Semantics** authority for the Galaxy
runtime.  This module unifies the audit event vocabulary across operator
surface, replay foundation, and control-plane audit ledger, preventing
multiple parallel audit formats.

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  AUDIT EVENT SEMANTICS  (this module)                           │
    │                                                                  │
    │  Defines the canonical vocabulary for:                          │
    │    • task lifecycle audit events (accepted/admitted/dispatched/ │
    │      completed/failed)                                          │
    │    • route/path decision events                                 │
    │    • policy decision / degradation events                       │
    │    • fallback / retry trigger events                            │
    │    • failure domain summary events                              │
    │                                                                  │
    │  Consumed by:                                                   │
    │    • ReplayFoundation.emit_runtime_event()                      │
    │    • OperatorSurface (event kind labels)                        │
    │    • control_plane.audit_ledger (EventType alignment)           │
    │    • Future: incident forensics / compliance audit              │
    └──────────────────────────────────────────────────────────────────┘

Unified semantic contract
-------------------------
The module provides:

1.  ``AuditEventKind`` — canonical string enum of all audit event kinds.
    Subsumed from :class:`~core.replay_foundation.ReplayEventKind` with
    additional governance / policy / provider kinds.

2.  ``AUDIT_EVENT_DESCRIPTIONS`` — human-readable description for each kind,
    used in explainability output.

3.  ``AuditEventRecord`` — lightweight canonical audit record (distinct from
    replay's ``RuntimeEventRecord``; focused on compliance / audit trail).

4.  ``AuditEventSemantics`` — singleton that bridges the replay foundation
    and the control-plane audit ledger with a unified event API.

5.  Helper functions matching the operator/replay vocabulary.

Projection discipline
---------------------
This module does NOT produce system truth.  It translates canonical runtime
events into the unified audit vocabulary.  Consumers (dashboards, compliance
systems) read audit records from :class:`AuditEventSemantics`, not from raw
subsystem event streams.

Public API
----------
Authority sentinels::

    AUDIT_EVENT_SEMANTICS_AUTHORITY
    AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION
    AUDIT_UNIFIED_VOCABULARY_POLICY

Enumerations::

    AuditEventKind

Constants::

    AUDIT_EVENT_DESCRIPTIONS  (Dict[AuditEventKind, str])

Dataclasses::

    AuditEventRecord
    AuditSemanticSnapshot

Class::

    AuditEventSemantics

Helpers::

    audit_task_accepted(task_id, ...) -> AuditEventRecord
    audit_task_admitted(task_id, ...) -> AuditEventRecord
    audit_task_dispatched(task_id, ...) -> AuditEventRecord
    audit_task_completed(task_id, ...) -> AuditEventRecord
    audit_task_failed(task_id, ...) -> AuditEventRecord
    audit_route_decision(task_id, ...) -> AuditEventRecord
    audit_policy_decision(task_id, ...) -> AuditEventRecord
    audit_fallback_triggered(task_id, ...) -> AuditEventRecord
    audit_retry_triggered(task_id, ...) -> AuditEventRecord
    audit_failure_domain(task_id, ...) -> AuditEventRecord
    get_audit_event_semantics() -> AuditEventSemantics
    reset_audit_event_semantics() -> None   # testing only
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

logger = logging.getLogger("Galaxy.AuditEventSemantics")

__all__ = [
    # Authority sentinels
    "AUDIT_EVENT_SEMANTICS_AUTHORITY",
    "AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION",
    "AUDIT_UNIFIED_VOCABULARY_POLICY",
    "AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL",
    # Enumerations
    "AuditEventKind",
    # Constants
    "AUDIT_EVENT_DESCRIPTIONS",
    # Dataclasses
    "AuditEventRecord",
    "AuditSemanticSnapshot",
    # Class
    "AuditEventSemantics",
    # Helpers
    "audit_task_accepted",
    "audit_task_admitted",
    "audit_task_dispatched",
    "audit_task_completed",
    "audit_task_failed",
    "audit_route_decision",
    "audit_policy_decision",
    "audit_fallback_triggered",
    "audit_retry_triggered",
    "audit_failure_domain",
    "get_audit_event_semantics",
    "reset_audit_event_semantics",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

AUDIT_EVENT_SEMANTICS_AUTHORITY: str = "AUDIT_EVENT_SEMANTICS_V1"
"""Sentinel: this module is the canonical audit event vocabulary authority.
Import to assert that an audit consumer uses the unified event vocabulary."""

AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION: str = "1.0"
"""Version of the audit event semantics contract."""

AUDIT_UNIFIED_VOCABULARY_POLICY: str = (
    "REQUIRED: All audit consumers must use AuditEventKind from this module; "
    "parallel audit formats in separate subsystems are prohibited; "
    "all audit trail entries must flow through AuditEventSemantics."
)
"""Policy: single canonical audit vocabulary; no parallel audit formats."""

AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT_SENTINEL: str = (
    "AUDIT_EVENT_SEMANTICS_DURABLE_AUDIT::DISPATCH_SPINE_V1: "
    "AuditEventSemantics now supports an optional durable audit sink via "
    "AuditEventSemantics.set_audit_store().  When a DurableAuditStore is "
    "attached, every AuditEventRecord appended to the ring buffer is also "
    "written to the JSONL store so that canonical dispatch-spine audit "
    "events (accepted/dispatched/completed/failed/route/fallback) are "
    "durably reviewable across process lifetimes.  The ring buffer remains "
    "the authoritative in-process read surface; the store is observational."
)
"""Sentinel confirming AuditEventSemantics supports durable audit storage."""


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class AuditEventKind(str, Enum):
    """Canonical unified audit event vocabulary for Galaxy.

    Subsumes and aligns with:
    - :class:`~core.replay_foundation.ReplayEventKind`
    - :class:`~core.control_plane.audit_ledger.EventType`

    String values are stable; do not rename them.
    """

    # ── Task lifecycle ────────────────────────────────────────────────
    TASK_ACCEPTED = "task_accepted"
    """Task accepted at system boundary (API/AI intent/skill invocation)."""

    TASK_ADMITTED = "task_admitted"
    """Task admitted for execution by the runtime authority."""

    TASK_DISPATCHED = "task_dispatched"
    """TaskEnvelope emitted and entered CommandRouter."""

    TASK_COMPLETED = "task_completed"
    """Task completed successfully."""

    TASK_FAILED = "task_failed"
    """Task failed with error_code and failure_domain."""

    TASK_CANCELLED = "task_cancelled"
    """Task explicitly cancelled."""

    TASK_DEGRADED = "task_degraded"
    """Task completed with degraded result (fallback used)."""

    # ── Route / path decisions ────────────────────────────────────────
    ROUTE_DECISION = "route_decision"
    """A routing decision was made for a task."""

    ROUTE_SELECTED = "route_selected"
    """A specific route/target/transport was selected."""

    ROUTE_DEGRADED = "route_degraded"
    """Routing fell back to a degraded path."""

    # ── Policy decisions ──────────────────────────────────────────────
    POLICY_ADMIT = "policy_admit"
    """Task admitted by policy convergence evaluation."""

    POLICY_REJECT = "policy_reject"
    """Task rejected by policy convergence evaluation."""

    POLICY_DEGRADE = "policy_degrade"
    """Task degraded by policy — reduced execution mode."""

    POLICY_DECISION = "policy_decision"
    """A generic policy decision was recorded."""

    # ── Fallback / retry ──────────────────────────────────────────────
    FALLBACK_TRIGGERED = "fallback_triggered"
    """Fallback execution path triggered."""

    FALLBACK_SUCCEEDED = "fallback_succeeded"
    """Fallback execution succeeded."""

    FALLBACK_FAILED = "fallback_failed"
    """Fallback execution also failed."""

    RETRY_TRIGGERED = "retry_triggered"
    """Retry attempt triggered."""

    RETRY_SUCCEEDED = "retry_succeeded"
    """Retry attempt succeeded."""

    RETRY_FAILED = "retry_failed"
    """Retry attempt failed."""

    # ── Failure domain ────────────────────────────────────────────────
    FAILURE_DOMAIN_IDENTIFIED = "failure_domain_identified"
    """Failure domain for a task has been identified and recorded."""

    # ── Provider / executor ───────────────────────────────────────────
    EXECUTOR_SELECTED = "executor_selected"
    """An executor/provider node was selected for a task."""

    EXECUTOR_RESULT = "executor_result"
    """Result received from executor/provider."""

    # ── Device / presence ────────────────────────────────────────────
    DEVICE_REGISTERED = "device_registered"
    """Device registered with the runtime."""

    DEVICE_HEARTBEAT = "device_heartbeat"
    """Device heartbeat recorded."""

    DEVICE_DISCONNECTED = "device_disconnected"
    """Device disconnected."""

    # ── Generic ───────────────────────────────────────────────────────
    RUNTIME_EVENT = "runtime_event"
    """Generic runtime event not covered by a specific kind."""


# ---------------------------------------------------------------------------
# Human-readable descriptions for explainability output
# ---------------------------------------------------------------------------

AUDIT_EVENT_DESCRIPTIONS: Dict[AuditEventKind, str] = {
    AuditEventKind.TASK_ACCEPTED: (
        "Task accepted at the system boundary; origin and intent recorded."
    ),
    AuditEventKind.TASK_ADMITTED: (
        "Task admitted for execution; planning constraints resolved."
    ),
    AuditEventKind.TASK_DISPATCHED: (
        "TaskEnvelope entered CommandRouter; execution spine engaged."
    ),
    AuditEventKind.TASK_COMPLETED: (
        "Task completed successfully; result lineage available."
    ),
    AuditEventKind.TASK_FAILED: (
        "Task failed; failure domain and error code recorded."
    ),
    AuditEventKind.TASK_CANCELLED: (
        "Task explicitly cancelled before or during execution."
    ),
    AuditEventKind.TASK_DEGRADED: (
        "Task completed with degraded result; fallback path was used."
    ),
    AuditEventKind.ROUTE_DECISION: (
        "Routing decision recorded; targets and transport strategy selected."
    ),
    AuditEventKind.ROUTE_SELECTED: (
        "Effective route selected; path and transport confirmed."
    ),
    AuditEventKind.ROUTE_DEGRADED: (
        "Routing degraded; fallback path used due to primary unavailability."
    ),
    AuditEventKind.POLICY_ADMIT: (
        "Policy convergence admitted the task for execution."
    ),
    AuditEventKind.POLICY_REJECT: (
        "Policy convergence rejected the task; reason recorded."
    ),
    AuditEventKind.POLICY_DEGRADE: (
        "Policy convergence degraded the task execution mode."
    ),
    AuditEventKind.POLICY_DECISION: (
        "Policy decision recorded; verdict and score available."
    ),
    AuditEventKind.FALLBACK_TRIGGERED: (
        "Fallback execution path triggered due to primary task failure."
    ),
    AuditEventKind.FALLBACK_SUCCEEDED: (
        "Fallback execution completed successfully."
    ),
    AuditEventKind.FALLBACK_FAILED: (
        "Fallback execution also failed; task is in error state."
    ),
    AuditEventKind.RETRY_TRIGGERED: (
        "Retry attempt triggered; original task was retried."
    ),
    AuditEventKind.RETRY_SUCCEEDED: (
        "Retry attempt completed successfully."
    ),
    AuditEventKind.RETRY_FAILED: (
        "Retry attempt failed; escalation may occur."
    ),
    AuditEventKind.FAILURE_DOMAIN_IDENTIFIED: (
        "Failure domain identified and recorded for diagnostics."
    ),
    AuditEventKind.EXECUTOR_SELECTED: (
        "Executor or provider node selected for task execution."
    ),
    AuditEventKind.EXECUTOR_RESULT: (
        "Result received from executor; result lineage updated."
    ),
    AuditEventKind.DEVICE_REGISTERED: (
        "Device registered with the runtime; capabilities catalogued."
    ),
    AuditEventKind.DEVICE_HEARTBEAT: (
        "Device heartbeat recorded; presence confirmed."
    ),
    AuditEventKind.DEVICE_DISCONNECTED: (
        "Device disconnected; presence marked unavailable."
    ),
    AuditEventKind.RUNTIME_EVENT: (
        "Generic runtime event recorded for observability."
    ),
}


# ---------------------------------------------------------------------------
# AuditEventRecord
# ---------------------------------------------------------------------------

@dataclass
class AuditEventRecord:
    """Canonical, lightweight audit record for compliance and observability.

    Distinct from :class:`~core.replay_foundation.RuntimeEventRecord` which
    carries full replay data.  This record is optimised for audit trail
    consumption (lightweight, exportable).
    """

    audit_id: str = field(
        default_factory=lambda: f"aud_{uuid.uuid4().hex[:16]}"
    )
    recorded_at: float = field(default_factory=time.time)

    kind: str = AuditEventKind.RUNTIME_EVENT
    """Audit event kind (AuditEventKind value)."""

    # Traceability
    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""

    # Source
    source: str = ""
    """Component that emitted this audit event."""

    # Message
    message: str = ""
    """Human-readable description of the event."""

    # Structured payload for downstream consumers
    payload: Dict[str, Any] = field(default_factory=dict)

    # Causal linkage
    parent_audit_ids: List[str] = field(default_factory=list)

    def description(self) -> str:
        """Return the canonical description for this event's kind."""
        try:
            kind_enum = AuditEventKind(self.kind)
            return AUDIT_EVENT_DESCRIPTIONS.get(kind_enum, self.message)
        except ValueError:
            return self.message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "recorded_at": self.recorded_at,
            "kind": self.kind,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "source": self.source,
            "message": self.message,
            "payload": self.payload,
            "parent_audit_ids": self.parent_audit_ids,
            "description": self.description(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEventRecord":
        return cls(
            audit_id=data.get("audit_id", f"aud_{uuid.uuid4().hex[:16]}"),
            recorded_at=data.get("recorded_at", time.time()),
            kind=data.get("kind", AuditEventKind.RUNTIME_EVENT),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
            session_id=data.get("session_id", ""),
            source=data.get("source", ""),
            message=data.get("message", ""),
            payload=data.get("payload", {}),
            parent_audit_ids=data.get("parent_audit_ids", []),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


@dataclass
class AuditSemanticSnapshot:
    """Snapshot of recent audit records from the semantics runtime."""

    snapshot_id: str = field(
        default_factory=lambda: f"audsnap_{uuid.uuid4().hex[:12]}"
    )
    generated_at: float = field(default_factory=time.time)
    event_count: int = 0
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    authority: str = AUDIT_EVENT_SEMANTICS_AUTHORITY
    contract_version: str = AUDIT_EVENT_SEMANTICS_CONTRACT_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "generated_at": self.generated_at,
            "event_count": self.event_count,
            "recent_events": self.recent_events,
            "authority": self.authority,
            "contract_version": self.contract_version,
        }


# ---------------------------------------------------------------------------
# AuditEventSemantics — main class
# ---------------------------------------------------------------------------

class AuditEventSemantics:
    """Singleton canonical audit event semantics runtime.

    Maintains a 256-entry ring buffer of :class:`AuditEventRecord` and
    provides query APIs to retrieve audit records by task, kind, or trace.

    Bridges :class:`~core.replay_foundation.ReplayFoundation` (execution
    replay) and the operator surface (observability) with a unified audit
    vocabulary.

    Durable audit sink
    ------------------
    When :meth:`set_audit_store` has been called with a
    :class:`~core.replay_audit_persistence.DurableAuditStore`, every
    :class:`AuditEventRecord` appended to the ring buffer is **also**
    written to the durable JSONL store.  The ring buffer remains the
    authoritative in-process read surface; the store provides forensic
    reviewability of dispatch-spine events across process lifetimes.
    """

    _MAX_RING: int = 256

    def __init__(self) -> None:
        self._ring: Deque[AuditEventRecord] = deque(maxlen=self._MAX_RING)
        self._by_task: Dict[str, List[AuditEventRecord]] = {}
        # Optional durable audit sink (wired by production bootstrap)
        self._audit_store: Any = None

    def set_audit_store(self, store: Any) -> None:
        """Attach a :class:`~core.replay_audit_persistence.DurableAuditStore`.

        Once attached, every :class:`AuditEventRecord` recorded here is also
        written to *store* for durable auditability of dispatch-spine events.

        Parameters
        ----------
        store:
            A :class:`~core.replay_audit_persistence.DurableAuditStore`
            instance.  Pass ``None`` to detach.
        """
        self._audit_store = store

    def record(self, record: AuditEventRecord) -> AuditEventRecord:
        """Append an :class:`AuditEventRecord` to the ring and durable store."""
        self._ring.append(record)
        if record.task_id:
            self._by_task.setdefault(record.task_id, []).append(record)
        # Write to durable store when attached
        if self._audit_store is not None:
            try:
                from core.replay_audit_persistence import append_replay_audit_record
                append_replay_audit_record(
                    record.to_dict(),
                    "audit_event",
                    store=self._audit_store,
                )
            except Exception as _exc:  # noqa: BLE001
                logger.debug(
                    "AuditEventSemantics: durable write skipped: %s", _exc
                )
        return record

    def get_by_task(self, task_id: str) -> List[AuditEventRecord]:
        """Return all audit records for *task_id*."""
        return list(self._by_task.get(task_id, []))

    def get_by_kind(self, kind: str) -> List[AuditEventRecord]:
        """Return all audit records matching *kind* from the ring buffer."""
        return [r for r in self._ring if r.kind == kind]

    def get_by_trace(self, trace_id: str) -> List[AuditEventRecord]:
        """Return all audit records for *trace_id* from the ring buffer."""
        return [r for r in self._ring if r.trace_id == trace_id]

    def all_events(self) -> List[AuditEventRecord]:
        """Return a snapshot copy of all events in the ring."""
        return list(self._ring)

    def snapshot(self) -> AuditSemanticSnapshot:
        """Return an :class:`AuditSemanticSnapshot`."""
        recent = list(self._ring)[-20:]
        return AuditSemanticSnapshot(
            event_count=len(self._ring),
            recent_events=[r.to_dict() for r in recent],
        )


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

_SEMANTICS: Optional[AuditEventSemantics] = None


def get_audit_event_semantics() -> AuditEventSemantics:
    """Return the singleton :class:`AuditEventSemantics` instance."""
    global _SEMANTICS
    if _SEMANTICS is None:
        _SEMANTICS = AuditEventSemantics()
    return _SEMANTICS


def reset_audit_event_semantics() -> None:
    """Reset the singleton — for testing only."""
    global _SEMANTICS
    _SEMANTICS = None


# ---------------------------------------------------------------------------
# Helper factory functions
# ---------------------------------------------------------------------------

def _emit(
    kind: AuditEventKind,
    task_id: str,
    *,
    trace_id: str = "",
    session_id: str = "",
    source: str = "",
    message: str = "",
    payload: Optional[Dict[str, Any]] = None,
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    rec = AuditEventRecord(
        kind=kind.value,
        task_id=task_id,
        trace_id=trace_id,
        session_id=session_id,
        source=source,
        message=message or AUDIT_EVENT_DESCRIPTIONS.get(kind, ""),
        payload=payload or {},
        parent_audit_ids=parent_audit_ids or [],
    )
    get_audit_event_semantics().record(rec)
    return rec


def audit_task_accepted(
    task_id: str,
    *,
    trace_id: str = "",
    session_id: str = "",
    source: str = "",
    origin: str = "",
    goal: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a TASK_ACCEPTED audit record."""
    return _emit(
        AuditEventKind.TASK_ACCEPTED,
        task_id,
        trace_id=trace_id,
        session_id=session_id,
        source=source,
        payload={"origin": origin, "goal": goal},
        parent_audit_ids=parent_audit_ids,
    )


def audit_task_admitted(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a TASK_ADMITTED audit record."""
    return _emit(
        AuditEventKind.TASK_ADMITTED,
        task_id,
        trace_id=trace_id,
        source=source,
        parent_audit_ids=parent_audit_ids,
    )


def audit_task_dispatched(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    targets: Optional[List[str]] = None,
    transport: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a TASK_DISPATCHED audit record."""
    return _emit(
        AuditEventKind.TASK_DISPATCHED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={"targets": targets or [], "transport": transport},
        parent_audit_ids=parent_audit_ids,
    )


def audit_task_completed(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    success: bool = True,
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a TASK_COMPLETED audit record."""
    return _emit(
        AuditEventKind.TASK_COMPLETED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={"success": success},
        parent_audit_ids=parent_audit_ids,
    )


def audit_task_failed(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    error_code: str = "",
    failure_domain: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a TASK_FAILED audit record."""
    return _emit(
        AuditEventKind.TASK_FAILED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={"error_code": error_code, "failure_domain": failure_domain},
        parent_audit_ids=parent_audit_ids,
    )


def audit_route_decision(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    selected_targets: Optional[List[str]] = None,
    transport_strategy: str = "",
    effective_path: str = "",
    route_explanation: str = "",
    degradation_reason: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a ROUTE_DECISION audit record."""
    return _emit(
        AuditEventKind.ROUTE_DECISION,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={
            "selected_targets": selected_targets or [],
            "transport_strategy": transport_strategy,
            "effective_path": effective_path,
            "route_explanation": route_explanation,
            "degradation_reason": degradation_reason,
        },
        parent_audit_ids=parent_audit_ids,
    )


def audit_policy_decision(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    verdict: str = "",
    policy_score: float = 0.0,
    degradation_reason: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a POLICY_DECISION audit record."""
    return _emit(
        AuditEventKind.POLICY_DECISION,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={
            "verdict": verdict,
            "policy_score": policy_score,
            "degradation_reason": degradation_reason,
        },
        parent_audit_ids=parent_audit_ids,
    )


def audit_fallback_triggered(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    fallback_task_id: str = "",
    reason: str = "",
    primary_failure_domain: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a FALLBACK_TRIGGERED audit record."""
    return _emit(
        AuditEventKind.FALLBACK_TRIGGERED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={
            "fallback_task_id": fallback_task_id,
            "reason": reason,
            "primary_failure_domain": primary_failure_domain,
        },
        parent_audit_ids=parent_audit_ids,
    )


def audit_retry_triggered(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    retry_task_id: str = "",
    attempt_number: int = 1,
    reason: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a RETRY_TRIGGERED audit record."""
    return _emit(
        AuditEventKind.RETRY_TRIGGERED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={
            "retry_task_id": retry_task_id,
            "attempt_number": attempt_number,
            "reason": reason,
        },
        parent_audit_ids=parent_audit_ids,
    )


def audit_failure_domain(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    failure_domain: str = "",
    error_code: str = "",
    parent_audit_ids: Optional[List[str]] = None,
) -> AuditEventRecord:
    """Emit a FAILURE_DOMAIN_IDENTIFIED audit record."""
    return _emit(
        AuditEventKind.FAILURE_DOMAIN_IDENTIFIED,
        task_id,
        trace_id=trace_id,
        source=source,
        payload={
            "failure_domain": failure_domain,
            "error_code": error_code,
        },
        parent_audit_ids=parent_audit_ids,
    )
