#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/failure_degraded_recovery_policy.py
==========================================
PR-513 — Failure / Degraded / Recovery Closure.

This module is the **failure-degraded-recovery policy layer** for the Galaxy
canonical runtime architecture.  It establishes a coherent, unified model for
failure, degraded, partial, fallback, retry, abort, and recovery states and
propagates them consistently through execution behaviour, runtime state,
operator inspection, and projection/status surfaces.

Architecture role
-----------------
::

    ┌───────────────────────────────────────────────────────────────────┐
    │  EXECUTION SPINE / DISPATCH SURFACE                               │
    │  CommandRouter  ·  Scheduler  ·  TaskOrchestrator  ·  AgentKernel │
    └────────────────────────────┬──────────────────────────────────────┘
                                 │  FAILURE / DEGRADED / RECOVERY TRUTH
                                 ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │  FAILURE-DEGRADED-RECOVERY POLICY LAYER  (this module, Layer 13) │
    │                                                                   │
    │  Records (non-blocking, runtime-truth writes):                    │
    │    • Failure truth → TaskGraphRuntime (node failed) +            │
    │                       AuditEventSemantics (TASK_FAILED) +        │
    │                       ReplayFoundation (TaskExecutionRecord)      │
    │    • Degraded transition → OperatorSurface + AuditEventSemantics  │
    │    • Recovery transition → TaskGraphRuntime (RECOVERED node) +    │
    │                             AuditEventSemantics (repair)          │
    │                                                                   │
    │  Snapshot helpers:                                                │
    │    • query_degraded_state()  — routable executor health          │
    │    • snapshot_failure_recovery_state() — unified view            │
    └────────────────────────────┬──────────────────────────────────────┘
                                 │  READS / WRITES CANONICAL LAYERS
                                 ▼
    ┌───────────────────────────────────────────────────────────────────┐
    │  RUNTIME TRUTH LAYERS (Layers 6–12)                               │
    │  TaskGraphRuntime · ReplayFoundation · AuditEventSemantics       │
    │  CapabilityAssimilationLayer · NetworkTopologyRuntime             │
    │  OperatorSurface · ClosureAuditRuntime                            │
    └───────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **Failure and degraded states are runtime truths, not logging artifacts.**
    :data:`FAILURE_AS_RUNTIME_TRUTH_POLICY` asserts that every failure or
    degraded condition materialises in TaskGraphRuntime and/or
    AuditEventSemantics, not just in log output.

2.  **No new parallel failure/degraded authority.**
    This module writes to the same canonical layers already established by
    PRs 506–512.  It MUST NOT introduce a new competing state authority.
    Governed by :data:`NO_PARALLEL_AUTHORITY_POLICY`.

3.  **Recovery transitions are first-class runtime events.**
    Recovery, repair, and retry-success flows are recorded in the same
    runtime layers as failure events so that the operator can observe
    full failure → recovery arcs.
    Governed by :data:`RECOVERY_AS_FIRST_CLASS_EVENT_POLICY`.

4.  **Propagation is best-effort and non-blocking.**
    All writes to canonical layers are wrapped in try/except so that a
    failure to write runtime metadata never aborts the primary execution
    path.  Governed by :data:`NON_BLOCKING_PROPAGATION_POLICY`.

5.  **Authority discipline is preserved.**
    This module consumes ``TaskGraphRuntime``, ``ReplayFoundation``,
    ``AuditEventSemantics``, and ``OperatorSurface`` as the only canonical
    authorities.  It does not invent new state stores.
    Governed by :data:`AUTHORITY_DISCIPLINE_POLICY`.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger("Galaxy.FailureDegradedRecoveryPolicy")

# ===========================================================================
# Module-level authority / policy sentinels
# ===========================================================================

#: Authority sentinel for this module.  Import-verified by closure audit.
FAILURE_DEGRADED_RECOVERY_AUTHORITY: str = (
    "FAILURE_DEGRADED_RECOVERY_POLICY::AUTHORITY_V1: "
    "core/failure_degraded_recovery_policy.py is the canonical layer for "
    "failure/degraded/recovery runtime truth propagation in the Galaxy system."
)

#: Layer position in the canonical authority stack (above closure audit, layer 12).
FAILURE_DEGRADED_RECOVERY_LAYER_POSITION: int = 13

# ---------------------------------------------------------------------------
# Policy sentinels — governance vocabulary
# ---------------------------------------------------------------------------

#: Failure and degraded conditions must update canonical runtime state.
FAILURE_AS_RUNTIME_TRUTH_POLICY: str = (
    "FAILURE_AS_RUNTIME_TRUTH_V1: Every failure or degraded event MUST "
    "materialise as a write to TaskGraphRuntime and/or AuditEventSemantics. "
    "Silent log-only failure handling is prohibited."
)

#: No new parallel failure/degraded state authority may be introduced.
NO_PARALLEL_AUTHORITY_POLICY: str = (
    "NO_PARALLEL_AUTHORITY_V1: This module writes to existing canonical layers "
    "(TaskGraphRuntime, ReplayFoundation, AuditEventSemantics). "
    "New competing state stores for failure/degraded truth are prohibited."
)

#: Recovery transitions are first-class runtime events.
RECOVERY_AS_FIRST_CLASS_EVENT_POLICY: str = (
    "RECOVERY_AS_FIRST_CLASS_EVENT_V1: Recovery, repair, and retry-success "
    "transitions MUST be recorded in the same canonical runtime layers "
    "as failure events so that full failure→recovery arcs are operator-visible."
)

#: Propagation writes are best-effort and must not abort the primary path.
NON_BLOCKING_PROPAGATION_POLICY: str = (
    "NON_BLOCKING_PROPAGATION_V1: All canonical-layer writes from this module "
    "are wrapped in try/except. A propagation write failure MUST NOT abort "
    "the primary execution path."
)

#: Authority discipline — only consume established canonical layers.
AUTHORITY_DISCIPLINE_POLICY: str = (
    "AUTHORITY_DISCIPLINE_V1: This module MUST consume only TaskGraphRuntime, "
    "ReplayFoundation, AuditEventSemantics, CapabilityAssimilationLayer, "
    "NetworkTopologyRuntime, and OperatorSurface as canonical authorities."
)

#: PR-513 integration sentinel — verifiable by closure audit.
FAILURE_DEGRADED_RECOVERY_INTEGRATED: str = (
    "FAILURE_DEGRADED_RECOVERY_POLICY::INTEGRATED_V1: "
    "PR-513 failure/degraded/recovery closure is wired into "
    "core/routes/tasks.py (GAP-512-001), "
    "core/scheduler.py (GAP-512-002), "
    "core/command_router.py (GAP-512-004), "
    "galaxy_gateway/orchestrator/task_orchestrator.py (GAP-512-006), "
    "core/agent/kernel.py (GAP-512-007)."
)

__all__ = [
    # Authority / policy sentinels
    "FAILURE_DEGRADED_RECOVERY_AUTHORITY",
    "FAILURE_DEGRADED_RECOVERY_LAYER_POSITION",
    "FAILURE_AS_RUNTIME_TRUTH_POLICY",
    "NO_PARALLEL_AUTHORITY_POLICY",
    "RECOVERY_AS_FIRST_CLASS_EVENT_POLICY",
    "NON_BLOCKING_PROPAGATION_POLICY",
    "AUTHORITY_DISCIPLINE_POLICY",
    "FAILURE_DEGRADED_RECOVERY_INTEGRATED",
    # Enums
    "FailureRuntimeState",
    # Dataclasses
    "DegradedTruthRecord",
    "RecoveryTransitionRecord",
    "FailureRecoverySnapshot",
    # Singleton
    "FailureDegradedRecoveryRuntime",
    "get_failure_degraded_recovery_runtime",
    "reset_failure_degraded_recovery_runtime",
    # Helpers
    "record_failure_truth",
    "record_degraded_transition",
    "record_recovery_transition",
    "query_degraded_state",
    "snapshot_failure_recovery_state",
    "propagate_failure_to_canonical",
    "propagate_recovery_to_canonical",
]

# ===========================================================================
# Enums
# ===========================================================================

_RING_BUFFER_SIZE = 256


class FailureRuntimeState(str, Enum):
    """Canonical states for a task/executor in the failure-recovery arc.

    These states extend the ``GraphNodeState`` vocabulary (PR-508) to cover
    the full failure → degraded → recovery lifecycle.
    """

    HEALTHY = "healthy"
    """Normal operation — no failure or degradation."""

    PARTIAL = "partial"
    """Partial success: some sub-tasks succeeded, others did not."""

    DEGRADED = "degraded"
    """Capability reduced but system is still operational at lower fidelity."""

    FALLBACK_ACTIVE = "fallback_active"
    """Primary path failed; fallback execution path is in use."""

    RETRY_PENDING = "retry_pending"
    """Execution failed; a retry attempt is scheduled or in-flight."""

    FAILED = "failed"
    """Terminal failure — all retry/fallback attempts exhausted."""

    ABORTED = "aborted"
    """Execution was explicitly aborted (e.g. cancellation, policy rejection)."""

    RECOVERING = "recovering"
    """System is in the process of recovering from a failure."""

    RECOVERED = "recovered"
    """Recovery completed successfully — system back to healthy or degraded."""


# ===========================================================================
# Dataclasses
# ===========================================================================


@dataclass
class DegradedTruthRecord:
    """Runtime truth record for a failure or degraded condition.

    Attributes
    ----------
    task_id:
        Canonical task identifier.
    trace_id:
        Canonical trace identifier.
    failure_state:
        The :class:`FailureRuntimeState` that describes this condition.
    failure_domain:
        The failure domain string from ``core.failure_domains.FailureDomain``
        (e.g. ``"timeout_failure"``).
    error_code:
        Raw error code or exception class name that triggered this record.
    source:
        Module/method that produced this record (e.g. ``"command_router"``).
    attempt_number:
        Retry attempt index (1-based).  ``0`` for first/only attempt.
    degraded_capabilities:
        List of capability names that are no longer available.
    message:
        Human-readable description of the condition.
    detected_at:
        UNIX timestamp when this record was created.
    """

    task_id: str
    trace_id: str = ""
    failure_state: FailureRuntimeState = FailureRuntimeState.FAILED
    failure_domain: str = ""
    error_code: str = ""
    source: str = ""
    attempt_number: int = 0
    degraded_capabilities: List[str] = field(default_factory=list)
    message: str = ""
    detected_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "failure_state": self.failure_state.value
            if hasattr(self.failure_state, "value")
            else str(self.failure_state),
            "failure_domain": self.failure_domain,
            "error_code": self.error_code,
            "source": self.source,
            "attempt_number": self.attempt_number,
            "degraded_capabilities": self.degraded_capabilities,
            "message": self.message,
            "detected_at": self.detected_at,
        }


@dataclass
class RecoveryTransitionRecord:
    """Runtime truth record for a recovery or repair transition.

    Attributes
    ----------
    task_id:
        Canonical task identifier.
    trace_id:
        Canonical trace identifier.
    prior_state:
        The :class:`FailureRuntimeState` *before* recovery.
    recovered_state:
        The :class:`FailureRuntimeState` *after* recovery.
    recovery_method:
        How recovery was achieved (e.g. ``"retry_success"``, ``"fallback_success"``,
        ``"circuit_breaker_closed"``, ``"manual_repair"``).
    source:
        Module/method that produced this record.
    restored_capabilities:
        List of capability names restored during recovery.
    message:
        Human-readable description of the recovery transition.
    transitioned_at:
        UNIX timestamp when this transition occurred.
    """

    task_id: str
    trace_id: str = ""
    prior_state: FailureRuntimeState = FailureRuntimeState.FAILED
    recovered_state: FailureRuntimeState = FailureRuntimeState.RECOVERED
    recovery_method: str = ""
    source: str = ""
    restored_capabilities: List[str] = field(default_factory=list)
    message: str = ""
    transitioned_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "prior_state": self.prior_state.value
            if hasattr(self.prior_state, "value")
            else str(self.prior_state),
            "recovered_state": self.recovered_state.value
            if hasattr(self.recovered_state, "value")
            else str(self.recovered_state),
            "recovery_method": self.recovery_method,
            "source": self.source,
            "restored_capabilities": self.restored_capabilities,
            "message": self.message,
            "transitioned_at": self.transitioned_at,
        }


@dataclass
class FailureRecoverySnapshot:
    """Point-in-time snapshot of failure/degraded/recovery runtime state.

    Attributes
    ----------
    degraded_records:
        Recent :class:`DegradedTruthRecord` entries (ring-buffer snapshot).
    recovery_records:
        Recent :class:`RecoveryTransitionRecord` entries.
    total_failures_recorded:
        Cumulative failure records written in this runtime session.
    total_recoveries_recorded:
        Cumulative recovery transitions written.
    snapshot_at:
        UNIX timestamp of this snapshot.
    """

    degraded_records: List[DegradedTruthRecord] = field(default_factory=list)
    recovery_records: List[RecoveryTransitionRecord] = field(default_factory=list)
    total_failures_recorded: int = 0
    total_recoveries_recorded: int = 0
    snapshot_at: float = field(default_factory=time.time)

    def summary(self) -> Dict[str, Any]:
        return {
            "degraded_records_count": len(self.degraded_records),
            "recovery_records_count": len(self.recovery_records),
            "total_failures_recorded": self.total_failures_recorded,
            "total_recoveries_recorded": self.total_recoveries_recorded,
            "snapshot_at": self.snapshot_at,
        }


# ===========================================================================
# Runtime singleton
# ===========================================================================


class FailureDegradedRecoveryRuntime:
    """Singleton runtime for failure/degraded/recovery state management.

    This class maintains ring-buffer logs of :class:`DegradedTruthRecord`
    and :class:`RecoveryTransitionRecord` entries and provides helpers to
    propagate them to the canonical runtime layers (TaskGraphRuntime,
    ReplayFoundation, AuditEventSemantics).

    **All write methods are non-blocking.**  Writes to canonical layers are
    wrapped in try/except per :data:`NON_BLOCKING_PROPAGATION_POLICY`.
    """

    def __init__(self) -> None:
        self._degraded_log: Deque[DegradedTruthRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._recovery_log: Deque[RecoveryTransitionRecord] = deque(
            maxlen=_RING_BUFFER_SIZE
        )
        self._total_failures: int = 0
        self._total_recoveries: int = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Write helpers
    # ------------------------------------------------------------------

    def record_failure(self, record: DegradedTruthRecord) -> DegradedTruthRecord:
        """Append a failure/degraded record to the ring buffer.

        Does **not** propagate to canonical layers — callers that want
        canonical propagation should use :func:`record_failure_truth` or
        :func:`propagate_failure_to_canonical`.
        """
        with self._lock:
            self._degraded_log.append(record)
            self._total_failures += 1
        return record

    def record_recovery(
        self, record: RecoveryTransitionRecord
    ) -> RecoveryTransitionRecord:
        """Append a recovery transition record to the ring buffer."""
        with self._lock:
            self._recovery_log.append(record)
            self._total_recoveries += 1
        return record

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> FailureRecoverySnapshot:
        """Return a point-in-time snapshot of the ring buffers."""
        with self._lock:
            return FailureRecoverySnapshot(
                degraded_records=list(self._degraded_log),
                recovery_records=list(self._recovery_log),
                total_failures_recorded=self._total_failures,
                total_recoveries_recorded=self._total_recoveries,
            )

    def list_failure_records(self) -> List[DegradedTruthRecord]:
        """Return all current failure/degraded records (oldest first)."""
        with self._lock:
            return list(self._degraded_log)

    def list_recovery_records(self) -> List[RecoveryTransitionRecord]:
        """Return all current recovery transition records (oldest first)."""
        with self._lock:
            return list(self._recovery_log)


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_singleton: Optional[FailureDegradedRecoveryRuntime] = None
_singleton_lock = threading.Lock()


def get_failure_degraded_recovery_runtime() -> FailureDegradedRecoveryRuntime:
    """Return the module-level :class:`FailureDegradedRecoveryRuntime` singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = FailureDegradedRecoveryRuntime()
    return _singleton


def reset_failure_degraded_recovery_runtime() -> None:
    """Reset the singleton (test helper — not for production use)."""
    global _singleton
    with _singleton_lock:
        _singleton = None


# ===========================================================================
# Canonical propagation helpers
# ===========================================================================


def propagate_failure_to_canonical(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    failure_state: FailureRuntimeState = FailureRuntimeState.FAILED,
    failure_domain: str = "",
    error_code: str = "",
    message: str = "",
    attempt_number: int = 0,
) -> DegradedTruthRecord:
    """Record a failure condition and propagate it to canonical runtime layers.

    This is the primary entry-point for failure-truth propagation.  It:

    1.  Appends a :class:`DegradedTruthRecord` to the runtime ring buffer.
    2.  Transitions the ``TaskGraphRuntime`` node to ``FAILED`` state.
    3.  Emits a ``TASK_FAILED`` event via ``AuditEventSemantics``.
    4.  Records a ``TaskExecutionRecord`` in ``ReplayFoundation``.

    All canonical-layer writes are best-effort (wrapped in try/except)
    per :data:`NON_BLOCKING_PROPAGATION_POLICY`.

    Args:
        task_id: Canonical task identifier.
        trace_id: Canonical trace identifier.
        source: Module/method that detected the failure.
        failure_state: The :class:`FailureRuntimeState` for this condition.
        failure_domain: Failure-domain taxonomy string.
        error_code: Raw error code or exception class name.
        message: Human-readable description.
        attempt_number: Retry attempt index (0 = first/only attempt).

    Returns:
        The :class:`DegradedTruthRecord` that was appended to the ring buffer.
    """
    record = DegradedTruthRecord(
        task_id=task_id,
        trace_id=trace_id,
        failure_state=failure_state,
        failure_domain=failure_domain,
        error_code=error_code,
        source=source,
        attempt_number=attempt_number,
        message=message,
    )
    get_failure_degraded_recovery_runtime().record_failure(record)

    # ── Write to TaskGraphRuntime ────────────────────────────────────────────
    try:
        from core.task_graph_runtime import (
            get_task_graph_runtime,
            GraphNodeState as _GNS,
        )
        _tgr = get_task_graph_runtime()
        _tgr.transition(task_id, _GNS.FAILED)
    except Exception as _tgr_exc:
        logger.debug(
            "propagate_failure_to_canonical: TaskGraphRuntime.transition skipped: %s",
            _tgr_exc,
        )

    # ── Emit audit TASK_FAILED ───────────────────────────────────────────────
    try:
        from core.audit_event_semantics import audit_task_failed
        audit_task_failed(
            task_id,
            trace_id=trace_id,
            source=source,
            error_code=error_code,
        )
    except Exception as _audit_exc:
        logger.debug(
            "propagate_failure_to_canonical: AuditEventSemantics write skipped: %s",
            _audit_exc,
        )

    # ── Record TaskExecutionRecord in ReplayFoundation ───────────────────────
    try:
        from core.replay_foundation import record_task_execution
        from core.canonical_task import build_canonical_task, TaskOrigin, TaskLifecycle
        _task = build_canonical_task(
            task_id=task_id,
            trace_id=trace_id,
            tool=source or "unknown",
            origin=TaskOrigin.UNKNOWN,
            register=False,
        )
        # Mark result fields as failed
        _task.result.success = False
        _task.result.error_code = error_code
        _task.lifecycle = TaskLifecycle.FAILED
        record_task_execution(_task)
    except Exception as _rep_exc:
        logger.debug(
            "propagate_failure_to_canonical: ReplayFoundation write skipped: %s",
            _rep_exc,
        )

    return record


def propagate_recovery_to_canonical(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    prior_state: FailureRuntimeState = FailureRuntimeState.FAILED,
    recovered_state: FailureRuntimeState = FailureRuntimeState.RECOVERED,
    recovery_method: str = "",
    message: str = "",
) -> RecoveryTransitionRecord:
    """Record a recovery transition and propagate it to canonical runtime layers.

    This is the primary entry-point for recovery-truth propagation.  It:

    1.  Appends a :class:`RecoveryTransitionRecord` to the runtime ring buffer.
    2.  Emits a ``TASK_COMPLETED`` / repair audit event via ``AuditEventSemantics``.
    3.  Transitions the ``TaskGraphRuntime`` node to reflect the recovery.

    All canonical-layer writes are best-effort per
    :data:`NON_BLOCKING_PROPAGATION_POLICY`.

    Args:
        task_id: Canonical task identifier.
        trace_id: Canonical trace identifier.
        source: Module/method that observed the recovery.
        prior_state: The :class:`FailureRuntimeState` before recovery.
        recovered_state: The :class:`FailureRuntimeState` after recovery.
        recovery_method: How recovery was achieved (e.g. ``"retry_success"``).
        message: Human-readable description.

    Returns:
        The :class:`RecoveryTransitionRecord` that was appended.
    """
    rec = RecoveryTransitionRecord(
        task_id=task_id,
        trace_id=trace_id,
        prior_state=prior_state,
        recovered_state=recovered_state,
        recovery_method=recovery_method,
        source=source,
        message=message,
    )
    get_failure_degraded_recovery_runtime().record_recovery(rec)

    # ── Transition TaskGraphRuntime to COMPLETED (recovered) ────────────────
    try:
        from core.task_graph_runtime import (
            get_task_graph_runtime,
            GraphNodeState as _GNS,
        )
        _tgr = get_task_graph_runtime()
        _tgr.transition(task_id, _GNS.COMPLETED)
    except Exception as _tgr_exc:
        logger.debug(
            "propagate_recovery_to_canonical: TaskGraphRuntime.transition skipped: %s",
            _tgr_exc,
        )

    # ── Emit audit repair / completed event ─────────────────────────────────
    try:
        from core.audit_event_semantics import audit_task_completed
        audit_task_completed(
            task_id,
            trace_id=trace_id,
            source=source,
            success=True,
        )
    except Exception as _audit_exc:
        logger.debug(
            "propagate_recovery_to_canonical: AuditEventSemantics write skipped: %s",
            _audit_exc,
        )

    return rec


# ===========================================================================
# Module-level convenience helpers
# ===========================================================================


def record_failure_truth(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    failure_state: FailureRuntimeState = FailureRuntimeState.FAILED,
    failure_domain: str = "",
    error_code: str = "",
    message: str = "",
    attempt_number: int = 0,
) -> DegradedTruthRecord:
    """Convenience wrapper — see :func:`propagate_failure_to_canonical`."""
    return propagate_failure_to_canonical(
        task_id,
        trace_id=trace_id,
        source=source,
        failure_state=failure_state,
        failure_domain=failure_domain,
        error_code=error_code,
        message=message,
        attempt_number=attempt_number,
    )


def record_degraded_transition(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    degraded_capabilities: Optional[List[str]] = None,
    message: str = "",
) -> DegradedTruthRecord:
    """Record a degraded-capability transition (partial operation).

    Writes the degraded condition to the ring buffer and emits a
    ``TASK_DEGRADED`` audit event.  Does **not** transition the
    TaskGraphRuntime node (the task may still be running at lower fidelity).

    Args:
        task_id: Canonical task identifier.
        trace_id: Canonical trace identifier.
        source: Module/method that observed the degradation.
        degraded_capabilities: Capability names that became unavailable.
        message: Human-readable description.

    Returns:
        The :class:`DegradedTruthRecord` appended to the ring buffer.
    """
    record = DegradedTruthRecord(
        task_id=task_id,
        trace_id=trace_id,
        failure_state=FailureRuntimeState.DEGRADED,
        source=source,
        degraded_capabilities=degraded_capabilities or [],
        message=message,
    )
    get_failure_degraded_recovery_runtime().record_failure(record)

    # ── Emit degraded audit event ────────────────────────────────────────────
    try:
        from core.audit_event_semantics import (
            AuditEventRecord,
            AuditEventKind,
            get_audit_event_semantics,
        )
        _rec = AuditEventRecord(
            kind=AuditEventKind.TASK_DEGRADED.value,
            task_id=task_id,
            trace_id=trace_id,
            source=source,
            message=message or "task capability degraded",
            payload={
                "degraded_capabilities": degraded_capabilities or [],
                "message": message,
            },
        )
        get_audit_event_semantics().record(_rec)
    except Exception as _audit_exc:
        logger.debug(
            "record_degraded_transition: AuditEventSemantics write skipped: %s",
            _audit_exc,
        )

    return record


def record_recovery_transition(
    task_id: str,
    *,
    trace_id: str = "",
    source: str = "",
    prior_state: FailureRuntimeState = FailureRuntimeState.FAILED,
    recovered_state: FailureRuntimeState = FailureRuntimeState.RECOVERED,
    recovery_method: str = "",
    message: str = "",
) -> RecoveryTransitionRecord:
    """Convenience wrapper — see :func:`propagate_recovery_to_canonical`."""
    return propagate_recovery_to_canonical(
        task_id,
        trace_id=trace_id,
        source=source,
        prior_state=prior_state,
        recovered_state=recovered_state,
        recovery_method=recovery_method,
        message=message,
    )


def query_degraded_state() -> Dict[str, Any]:
    """Query the canonical runtime for current degraded executor states.

    Reads from :class:`~core.capability_network_runtime_policy` to identify
    which executors are currently in a degraded presence state.

    Returns:
        Dict with keys:
        - ``"degraded_executors"``: list of node_id strings in degraded state
        - ``"total_online"``: total online executor count
        - ``"total_degraded"``: count of degraded executors
        - ``"snapshot_at"``: UNIX timestamp
    """
    result: Dict[str, Any] = {
        "degraded_executors": [],
        "total_online": 0,
        "total_degraded": 0,
        "snapshot_at": time.time(),
    }
    try:
        from core.capability_network_runtime_policy import query_routable_executors
        executors = query_routable_executors()
        result["total_online"] = len(executors)
        degraded = [
            e.node_id
            for e in executors
            if e.presence_state == "degraded"
        ]
        result["degraded_executors"] = degraded
        result["total_degraded"] = len(degraded)
    except Exception as _exc:
        logger.debug("query_degraded_state: capability layer unavailable: %s", _exc)
    return result


def snapshot_failure_recovery_state() -> Dict[str, Any]:
    """Return a unified snapshot of failure/degraded/recovery runtime state.

    Combines:
    - Ring-buffer summary from :class:`FailureDegradedRecoveryRuntime`
    - Degraded executor query from capability layer

    Returns:
        Dict combining :meth:`FailureRecoverySnapshot.summary` and
        the ``query_degraded_state`` result.
    """
    runtime_snapshot = get_failure_degraded_recovery_runtime().snapshot()
    degraded_state = query_degraded_state()
    summary = runtime_snapshot.summary()
    summary.update(degraded_state)
    return summary
