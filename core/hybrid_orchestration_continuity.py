#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/hybrid_orchestration_continuity.py
========================================
PR-59: Hybrid Orchestration Lifecycle, Durability, and Recovery Closure

Background
----------
Prior to this module, hybrid execution in the Galaxy runtime was largely
represented as a *degrade-only edge* — the ``HybridExecutionArbiter`` ran a
three-level fallback chain (A2A → GUI → VLM) but did not carry canonical
orchestration lifecycle semantics.  Specifically:

* Hybrid executions had no explicit lifecycle state (created → running →
  interrupted → completed/failed/cancelled).
* There was no durable or semi-durable record that a hybrid execution was
  in progress at the time of a restart or device disconnect.
* Recovery logic in :mod:`core.runtime_restart_recovery` had no awareness
  of hybrid executions, so in-flight hybrid work was silently lost with no
  observable interruption signal.
* The boundary between *durable* hybrid state (lifecycle stage, mode
  selection, execution identity) and *ephemeral* hybrid state (live A2A
  connections, active GUI handles, VLM screenshot context) was undeclared.

This module closes the gap by introducing:

1. :class:`HybridOrchestrationLifecycleState` — explicit lifecycle state
   machine for a hybrid execution as a canonical orchestration runtime path.
2. :class:`HybridOrchestrationRecord` — immutable-on-transition, fully
   serialisable record of a hybrid execution's position in the orchestration
   lifecycle.
3. :class:`HybridOrchestrationContinuityRegistry` — in-process registry that
   tracks live hybrid executions, classifies them as terminal or non-terminal,
   and exposes hooks for the restart/recovery coordinator to:
   - mark all in-flight (non-terminal) executions as ``interrupted``;
   - recover them for replay or resumption;
   - leave terminal executions unchanged (idempotency invariant).
4. Explicit durability-boundary sentinels distinguishing what canonical state
   survives a restart (execution identity, lifecycle position, mode) from
   what is intentionally ephemeral (live transport handles, GUI automation
   state, VLM screenshot context).

Design principles
-----------------
- **Additive only** — does not modify ``core.hybrid_executor`` or
  ``core.hybrid_execution_policy``.
- **Canonical orchestration path** — hybrid execution is treated as a
  first-class lifecycle path under V2 orchestration authority, not a
  degrade-only fallback.
- **Terminal-state idempotency** — once an execution reaches a terminal
  state (``completed``, ``failed``, ``cancelled``) it MUST NOT be
  transitioned further; recovery operations leave terminal executions as-is.
- **Explicit non-goals** — live transport handles, GUI automation context,
  and VLM screenshot state are intentionally ephemeral and are NOT recovered.
- **Fully serialisable** — :class:`HybridOrchestrationRecord` can be
  round-tripped through ``to_dict()`` / ``from_dict()`` for audit and replay.

Durability boundaries
---------------------
**Durable (survives restart via in-process registry + structured record)**:
- Execution identity (``execution_id``, ``session_id``, ``task_id``)
- Lifecycle state at interruption (``interrupted``)
- Selected hybrid execution mode
- Timestamps: started_at, updated_at
- Resume count (how many times this execution has been resumed)

**Ephemeral (intentionally not recovered)**:
- Live A2A transport handles / MCP call state
- Active GUI automation handles (accessibility trees, ADB connections)
- VLM screenshot buffers and inference context
- Pending async futures for in-flight API calls

Sentinels
---------
:data:`HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY`
    Affirms this module is the canonical lifecycle/continuity authority for
    hybrid orchestrations in the Galaxy runtime.
:data:`HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY`
    Affirms that hybrid execution is a first-class canonical orchestration
    runtime path, not merely a degrade-only edge.
:data:`HYBRID_RECORD_IS_SERIALISABLE_POLICY`
    Affirms every :class:`HybridOrchestrationRecord` is round-trippable
    through ``to_dict()`` / ``from_dict()``.
:data:`HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY`
    Affirms that ``interrupted`` is a non-terminal state that can transition
    to ``resuming`` and back to ``running``.
:data:`HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY`
    Affirms that terminal states (completed, failed, cancelled) MUST NOT be
    further transitioned.
:data:`HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY`
    Affirms that live transport handles (A2A, GUI, VLM context) are
    intentionally ephemeral and are NOT recovered across restarts.
:data:`HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL`
    Monotonic sentinel string for PR-59 feature identification.

Public API
----------
Enums:
    :class:`HybridOrchestrationLifecycleState`

Classes:
    :class:`HybridOrchestrationRecord`
    :class:`HybridOrchestrationContinuityRegistry`

Functions:
    :func:`get_continuity_registry`
    :func:`reset_continuity_registry`
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.HybridOrchestrationContinuity")

__all__ = [
    # Sentinels — PR-59
    "HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY",
    "HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY",
    "HYBRID_RECORD_IS_SERIALISABLE_POLICY",
    "HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY",
    "HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY",
    "HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY",
    "HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL",
    # Sentinels — PR-6
    "HYBRID_PARTIAL_RESULT_MERGE_POLICY",
    "HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE_POLICY",
    "HYBRID_CONTINUITY_PR6_SENTINEL",
    # Enums
    "HybridOrchestrationLifecycleState",
    "HybridPartialResultDisposition",
    # Classes
    "HybridOrchestrationRecord",
    "HybridOrchestrationContinuityRegistry",
    "HybridContinuityPersistenceStore",
    # Functions — registry
    "get_continuity_registry",
    "reset_continuity_registry",
    # Functions — persistence
    "save_hybrid_execution",
    "load_hybrid_execution",
    "recover_hybrid_executions",
    "get_hybrid_persistence_store",
    "reset_hybrid_persistence_store",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY: str = (
    "HYBRID_ORCHESTRATION_CONTINUITY_IS_AUTHORITY: "
    "core/hybrid_orchestration_continuity.py is the canonical lifecycle, "
    "durability, and recovery closure authority for hybrid orchestration in "
    "the Galaxy V2 runtime (PR-59)."
)

HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH_POLICY: str = (
    "POLICY::HYBRID_LIFECYCLE_IS_CANONICAL_ORCHESTRATION_PATH: "
    "Hybrid execution is a first-class canonical orchestration runtime path "
    "under V2 orchestration authority.  It carries explicit lifecycle states "
    "(created → dispatched → running → interrupted/completed/failed/cancelled) "
    "and is NOT merely a degrade-only fallback edge."
)

HYBRID_RECORD_IS_SERIALISABLE_POLICY: str = (
    "POLICY::HYBRID_RECORD_IS_SERIALISABLE: every HybridOrchestrationRecord "
    "MUST be round-trippable through to_dict() / from_dict() to enable "
    "auditing, recovery, and test assertions.  Records are fully serialisable "
    "to JSON without loss of lifecycle-critical fields."
)

HYBRID_INTERRUPTION_IS_RECOVERABLE_POLICY: str = (
    "POLICY::HYBRID_INTERRUPTION_IS_RECOVERABLE: the 'interrupted' lifecycle "
    "state is non-terminal.  Interrupted executions MAY transition to "
    "'resuming' and back to 'running' for continuation, or to 'cancelled' "
    "for explicit abandonment.  The recovery coordinator MUST mark all "
    "non-terminal executions as 'interrupted' on restart."
)

HYBRID_TERMINAL_STATE_IS_IMMUTABLE_POLICY: str = (
    "POLICY::HYBRID_TERMINAL_STATE_IS_IMMUTABLE: once a HybridOrchestrationRecord "
    "reaches a terminal state (completed, failed, cancelled), its lifecycle_state "
    "MUST NOT be further transitioned.  Recovery operations leave terminal "
    "records as-is (idempotency invariant)."
)

HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL_POLICY: str = (
    "POLICY::HYBRID_TRANSPORT_HANDLES_ARE_EPHEMERAL: live transport handles "
    "(A2A MCP connections, GUI automation handles, VLM screenshot buffers) are "
    "INTENTIONALLY ephemeral and are NOT recovered across process restarts.  "
    "Only execution identity, lifecycle state, selected mode, and timestamps "
    "are considered durable.  New transport handles are created when executions "
    "are re-dispatched after recovery."
)

HYBRID_ORCHESTRATION_CONTINUITY_PR59_SENTINEL: str = (
    "HYBRID_ORCHESTRATION_CONTINUITY_PR59::"
    "hybrid-orchestration-lifecycle-durability-recovery-closure-pr59-v1"
)

# ---------------------------------------------------------------------------
# PR-6 sentinels — partial-result merge and durable persistence
# ---------------------------------------------------------------------------

HYBRID_PARTIAL_RESULT_MERGE_POLICY: str = (
    "POLICY::HYBRID_PARTIAL_RESULT_MERGE: After interruption, partial local "
    "results are classified as PRESERVED (available for resume/merge) because "
    "the local execution context may still be valid.  Partial remote results "
    "are classified as INVALIDATED by the recovery coordinator because the "
    "underlying transport (A2A, GUI, VLM) is gone after a restart and the "
    "partial remote data can no longer be trusted.  A MERGED disposition is "
    "recorded when local and remote partial results are combined under V2 "
    "canonical orchestration authority before interruption completes.  A "
    "RESUMED disposition is recorded when the execution was re-started from "
    "preserved partial result state.  No partial-result operation may "
    "transition a terminal-state record (idempotency invariant)."
)

HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE_POLICY: str = (
    "POLICY::HYBRID_CONTINUITY_PERSISTENCE_IS_DURABLE: "
    "HybridContinuityPersistenceStore provides file-backed durable storage "
    "for HybridOrchestrationRecord instances.  Non-terminal records (created, "
    "dispatched, running, interrupted, resuming) are restored after process "
    "restart via recover_hybrid_executions() and can be re-registered into "
    "the live HybridOrchestrationContinuityRegistry for continued tracking. "
    "Terminal records (completed, failed, cancelled) are saved for audit "
    "purposes but are NOT restored into the live registry by default. "
    "Live transport handles (A2A connections, GUI handles, VLM context) are "
    "NEVER persisted — only execution identity, lifecycle state, mode, "
    "timestamps, resume_count, and partial result snapshots are written."
)

HYBRID_CONTINUITY_PR6_SENTINEL: str = (
    "HYBRID_CONTINUITY_PR6::"
    "hybrid-execution-continuity-interruption-restart-partial-result-closure-pr6-v1"
)


# ---------------------------------------------------------------------------
# HybridOrchestrationLifecycleState
# ---------------------------------------------------------------------------


class HybridOrchestrationLifecycleState(str, Enum):
    """Explicit lifecycle states for a hybrid execution in the orchestration runtime.

    State machine
    -------------
    ::

        created
          ├─→ dispatched
          └─→ cancelled

        dispatched
          ├─→ running
          ├─→ interrupted  (device disconnect / restart before execution started)
          └─→ cancelled

        running
          ├─→ interrupted  (device disconnect / restart while executing)
          ├─→ completed    (terminal)
          ├─→ failed       (terminal)
          └─→ cancelled    (terminal)

        interrupted
          ├─→ resuming
          └─→ cancelled    (terminal)

        resuming
          ├─→ running
          ├─→ interrupted  (process restart while resuming)
          ├─→ completed    (terminal)
          └─→ failed       (terminal)

    Terminal states: completed, failed, cancelled
    Non-terminal states: created, dispatched, running, interrupted, resuming
    """

    created = "created"
    dispatched = "dispatched"
    running = "running"
    interrupted = "interrupted"
    resuming = "resuming"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True if this is a terminal state (no further transitions allowed)."""
        return self in (
            HybridOrchestrationLifecycleState.completed,
            HybridOrchestrationLifecycleState.failed,
            HybridOrchestrationLifecycleState.cancelled,
        )

    @property
    def is_recoverable(self) -> bool:
        """True if this non-terminal state can be recovered after interruption."""
        return self == HybridOrchestrationLifecycleState.interrupted

    @property
    def is_active(self) -> bool:
        """True if the execution is currently progressing (not waiting/terminal)."""
        return self in (
            HybridOrchestrationLifecycleState.running,
            HybridOrchestrationLifecycleState.resuming,
        )


# ---------------------------------------------------------------------------
# Valid transition table
# ---------------------------------------------------------------------------

_VALID_TRANSITIONS: Dict[HybridOrchestrationLifecycleState, Set[HybridOrchestrationLifecycleState]] = {
    HybridOrchestrationLifecycleState.created: {
        HybridOrchestrationLifecycleState.dispatched,
        HybridOrchestrationLifecycleState.cancelled,
    },
    HybridOrchestrationLifecycleState.dispatched: {
        HybridOrchestrationLifecycleState.running,
        HybridOrchestrationLifecycleState.interrupted,
        HybridOrchestrationLifecycleState.cancelled,
    },
    HybridOrchestrationLifecycleState.running: {
        HybridOrchestrationLifecycleState.interrupted,
        HybridOrchestrationLifecycleState.completed,
        HybridOrchestrationLifecycleState.failed,
        HybridOrchestrationLifecycleState.cancelled,
    },
    HybridOrchestrationLifecycleState.interrupted: {
        HybridOrchestrationLifecycleState.resuming,
        HybridOrchestrationLifecycleState.cancelled,
    },
    HybridOrchestrationLifecycleState.resuming: {
        HybridOrchestrationLifecycleState.running,
        HybridOrchestrationLifecycleState.interrupted,
        HybridOrchestrationLifecycleState.completed,
        HybridOrchestrationLifecycleState.failed,
    },
    # Terminal states have no valid outgoing transitions
    HybridOrchestrationLifecycleState.completed: set(),
    HybridOrchestrationLifecycleState.failed: set(),
    HybridOrchestrationLifecycleState.cancelled: set(),
}


def _is_valid_transition(
    from_state: HybridOrchestrationLifecycleState,
    to_state: HybridOrchestrationLifecycleState,
) -> bool:
    """Return True if the transition from *from_state* to *to_state* is valid."""
    return to_state in _VALID_TRANSITIONS.get(from_state, set())


# ---------------------------------------------------------------------------
# HybridPartialResultDisposition (PR-6)
# ---------------------------------------------------------------------------


class HybridPartialResultDisposition(str, Enum):
    """Classification of a partial local/remote execution result after interruption.

    Used to express how the hybrid orchestration runtime should treat a
    partial result that existed at the time of an interruption or restart.

    Values
    ------
    preserved
        The partial result is from a local execution leg.  It is retained
        and available for merge or resume because the local execution context
        may still be valid.
    invalidated
        The partial result is from a remote execution leg.  It is dropped
        because the underlying transport (A2A connection, GUI handle, VLM
        session) is gone after a restart and the partial remote data can no
        longer be trusted without re-verification.
    merged
        Local and remote partial results were combined under V2 canonical
        orchestration authority before or during interruption handling.
    resumed
        The execution was re-started from preserved partial result state.
        The partial result was used as the starting point for the resumed run.
    """

    preserved = "preserved"
    invalidated = "invalidated"
    merged = "merged"
    resumed = "resumed"


# ---------------------------------------------------------------------------
# HybridOrchestrationRecord
# ---------------------------------------------------------------------------


@dataclass
class HybridOrchestrationRecord:
    """Serialisable record of a hybrid execution in the orchestration lifecycle.

    This record tracks a hybrid execution from creation through all lifecycle
    transitions.  It is the canonical *durable* representation of a hybrid
    execution's position in the orchestration runtime.

    Durable fields (survive restart)
    ---------------------------------
    execution_id, session_id, task_id, mode, lifecycle_state,
    started_at, updated_at, resume_count, partial_result_snapshot,
    partial_result_origin, partial_result_disposition

    Ephemeral fields (NOT recovered — intentional)
    -----------------------------------------------
    result_snapshot (only populated on completion), interruption_reason
    (informational only).  Live transport handles are NEVER stored here.

    Parameters
    ----------
    execution_id:
        Unique identifier for this hybrid execution (stable across resumes).
    session_id:
        Associated orchestration session identifier (may be empty).
    task_id:
        Associated canonical task identifier (may be empty).
    mode:
        Selected hybrid execution mode string (from HybridExecutionMode).
    lifecycle_state:
        Current :class:`HybridOrchestrationLifecycleState`.
    started_at:
        Wall-clock timestamp when execution entered ``running`` the first time.
    updated_at:
        Wall-clock timestamp of the last lifecycle transition.
    completed_at:
        Wall-clock timestamp when execution reached a terminal state (or None).
    result_snapshot:
        Optional result dict snapshot (populated on ``completed``).
    interruption_reason:
        Human-readable reason for interruption (populated on ``interrupted``).
    resume_count:
        Number of times this execution has been resumed from ``interrupted``.
    partial_result_snapshot:
        Optional partial result dict recorded when execution is interrupted
        before completion.  Local partial results (``partial_result_origin``
        == ``"local"``) are classified as ``preserved``; remote partial
        results (``partial_result_origin`` == ``"remote"``) are classified
        as ``invalidated`` by the recovery coordinator on restart.
    partial_result_origin:
        Origin of the partial result: ``"local"``, ``"remote"``, or ``""``
        when no partial result is recorded.
    partial_result_disposition:
        How the partial result is handled after interruption.  One of the
        :class:`HybridPartialResultDisposition` values: ``"preserved"``,
        ``"invalidated"``, ``"merged"``, ``"resumed"``, or ``None``.
    """

    execution_id: str = field(default_factory=lambda: f"hexec_{uuid.uuid4().hex[:12]}")
    session_id: str = ""
    task_id: str = ""
    mode: str = "sequential_degrade"
    lifecycle_state: HybridOrchestrationLifecycleState = field(
        default=HybridOrchestrationLifecycleState.created
    )
    started_at: Optional[float] = None
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result_snapshot: Optional[Dict[str, Any]] = None
    interruption_reason: Optional[str] = None
    resume_count: int = 0
    partial_result_snapshot: Optional[Dict[str, Any]] = None
    partial_result_origin: str = ""
    partial_result_disposition: Optional[str] = None

    @property
    def is_terminal(self) -> bool:
        """True if this record is in a terminal state."""
        return self.lifecycle_state.is_terminal

    def transition(
        self,
        target_state: HybridOrchestrationLifecycleState,
        *,
        reason: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Attempt to transition to *target_state*.

        Parameters
        ----------
        target_state:
            The desired new lifecycle state.
        reason:
            Optional human-readable reason (used for interruption).
        result:
            Optional result dict (used for completion).

        Returns
        -------
        bool
            True if the transition was applied; False if it was rejected
            (invalid transition or terminal-state guard).
        """
        if self.lifecycle_state.is_terminal:
            logger.debug(
                "HybridOrchestrationRecord: rejected transition %s→%s for "
                "execution_id=%s — source state is terminal",
                self.lifecycle_state.value,
                target_state.value,
                self.execution_id,
            )
            return False

        if not _is_valid_transition(self.lifecycle_state, target_state):
            logger.warning(
                "HybridOrchestrationRecord: invalid transition %s→%s for "
                "execution_id=%s",
                self.lifecycle_state.value,
                target_state.value,
                self.execution_id,
            )
            return False

        now = time.time()
        prev_state = self.lifecycle_state
        self.lifecycle_state = target_state
        self.updated_at = now

        if target_state == HybridOrchestrationLifecycleState.running and self.started_at is None:
            self.started_at = now
        if target_state == HybridOrchestrationLifecycleState.interrupted:
            self.interruption_reason = reason
        if target_state == HybridOrchestrationLifecycleState.resuming:
            self.resume_count += 1
        if target_state.is_terminal:
            self.completed_at = now
            if result is not None:
                self.result_snapshot = result

        logger.debug(
            "HybridOrchestrationRecord: %s→%s execution_id=%s",
            prev_state.value,
            target_state.value,
            self.execution_id,
        )
        return True

    def set_partial_result(
        self,
        snapshot: Dict[str, Any],
        origin: str,
        *,
        disposition: Optional[str] = None,
    ) -> None:
        """Record a partial execution result (PR-6).

        This should be called when partial local or remote work has produced
        output that must survive interruption.  The *origin* controls default
        disposition semantics (local → preserved; remote → invalidated by the
        recovery coordinator on restart).

        Terminal records are silently ignored.

        Parameters
        ----------
        snapshot:
            The partial result dict.  Must be JSON-serialisable.
        origin:
            ``"local"`` or ``"remote"``.  Drives disposition classification
            by the recovery coordinator.
        disposition:
            Optional explicit :class:`HybridPartialResultDisposition` value.
            When ``None`` the disposition is left unset for the recovery
            coordinator to classify.
        """
        if self.lifecycle_state.is_terminal:
            logger.debug(
                "HybridOrchestrationRecord: set_partial_result ignored for "
                "terminal execution_id=%s",
                self.execution_id,
            )
            return
        self.partial_result_snapshot = snapshot
        self.partial_result_origin = origin
        if disposition is not None:
            self.partial_result_disposition = disposition

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "execution_id": self.execution_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "mode": self.mode,
            "lifecycle_state": self.lifecycle_state.value,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "result_snapshot": self.result_snapshot,
            "interruption_reason": self.interruption_reason,
            "resume_count": self.resume_count,
            "partial_result_snapshot": self.partial_result_snapshot,
            "partial_result_origin": self.partial_result_origin,
            "partial_result_disposition": self.partial_result_disposition,
            "is_terminal": self.is_terminal,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HybridOrchestrationRecord":
        """Deserialise from *data*.

        Raises ``ValueError`` if *data* is not a dict.
        """
        if not isinstance(data, dict):
            raise ValueError(
                f"HybridOrchestrationRecord.from_dict expects a dict, "
                f"got {type(data).__name__!r}"
            )
        raw_state = data.get("lifecycle_state", "created")
        try:
            state = HybridOrchestrationLifecycleState(raw_state)
        except ValueError:
            state = HybridOrchestrationLifecycleState.created

        return cls(
            execution_id=data.get("execution_id", f"hexec_{uuid.uuid4().hex[:12]}"),
            session_id=data.get("session_id", ""),
            task_id=data.get("task_id", ""),
            mode=data.get("mode", "sequential_degrade"),
            lifecycle_state=state,
            started_at=data.get("started_at"),
            updated_at=float(data.get("updated_at", time.time())),
            completed_at=data.get("completed_at"),
            result_snapshot=data.get("result_snapshot"),
            interruption_reason=data.get("interruption_reason"),
            resume_count=int(data.get("resume_count", 0)),
            partial_result_snapshot=data.get("partial_result_snapshot"),
            partial_result_origin=data.get("partial_result_origin", ""),
            partial_result_disposition=data.get("partial_result_disposition"),
        )


# ---------------------------------------------------------------------------
# HybridOrchestrationContinuityRegistry
# ---------------------------------------------------------------------------


class HybridOrchestrationContinuityRegistry:
    """In-process registry tracking hybrid executions through their lifecycle.

    This registry is the single point of truth for the orchestration lifecycle
    state of all active and recently-terminal hybrid executions.  It:

    - Accepts new :class:`HybridOrchestrationRecord` registrations.
    - Validates and applies lifecycle transitions.
    - Classifies records as terminal or non-terminal.
    - Exposes ``mark_all_running_as_interrupted`` for the restart/recovery
      coordinator to call on process startup.
    - Exposes ``list_interrupted`` for recovery enumeration.

    Thread-safety note: this implementation uses a simple ``dict`` with no
    locking.  It is designed for single-threaded or event-loop usage.  For
    multi-threaded environments wrap access with an external lock.
    """

    def __init__(self) -> None:
        self._records: Dict[str, HybridOrchestrationRecord] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, record: HybridOrchestrationRecord) -> None:
        """Add *record* to the registry.

        If a record with the same ``execution_id`` already exists it is
        silently replaced (idempotent re-registration).
        """
        self._records[record.execution_id] = record
        logger.debug(
            "HybridOrchestrationContinuityRegistry: registered execution_id=%s "
            "state=%s",
            record.execution_id,
            record.lifecycle_state.value,
        )

    def create_and_register(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        mode: str = "sequential_degrade",
    ) -> HybridOrchestrationRecord:
        """Create a new :class:`HybridOrchestrationRecord` and register it.

        Parameters
        ----------
        session_id:
            Associated orchestration session identifier.
        task_id:
            Associated canonical task identifier.
        mode:
            Hybrid execution mode string.

        Returns
        -------
        :class:`HybridOrchestrationRecord`
            The newly created and registered record.
        """
        record = HybridOrchestrationRecord(
            session_id=session_id,
            task_id=task_id,
            mode=mode,
        )
        self.register(record)
        return record

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------

    def transition(
        self,
        execution_id: str,
        target_state: HybridOrchestrationLifecycleState,
        *,
        reason: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Apply a lifecycle transition to the record for *execution_id*.

        Parameters
        ----------
        execution_id:
            The execution to transition.
        target_state:
            Desired new lifecycle state.
        reason:
            Optional reason (used for interruption logging).
        result:
            Optional result dict (used for completion).

        Returns
        -------
        bool
            True if the transition was applied; False if unknown execution_id
            or the transition was rejected.
        """
        record = self._records.get(execution_id)
        if record is None:
            logger.warning(
                "HybridOrchestrationContinuityRegistry: transition requested "
                "for unknown execution_id=%s",
                execution_id,
            )
            return False
        return record.transition(target_state, reason=reason, result=result)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, execution_id: str) -> Optional[HybridOrchestrationRecord]:
        """Return the record for *execution_id*, or None if not found."""
        return self._records.get(execution_id)

    def list_all(self) -> List[HybridOrchestrationRecord]:
        """Return all registered records (terminal and non-terminal)."""
        return list(self._records.values())

    def list_non_terminal(self) -> List[HybridOrchestrationRecord]:
        """Return all records in non-terminal states."""
        return [r for r in self._records.values() if not r.is_terminal]

    def list_terminal(self) -> List[HybridOrchestrationRecord]:
        """Return all records in terminal states."""
        return [r for r in self._records.values() if r.is_terminal]

    def list_interrupted(self) -> List[HybridOrchestrationRecord]:
        """Return all records in the ``interrupted`` state."""
        return [
            r for r in self._records.values()
            if r.lifecycle_state == HybridOrchestrationLifecycleState.interrupted
        ]

    # ------------------------------------------------------------------
    # Recovery operations
    # ------------------------------------------------------------------

    def mark_all_running_as_interrupted(
        self, reason: str = "process_restart"
    ) -> int:
        """Mark all non-terminal, non-interrupted records as ``interrupted``.

        Called by the restart/recovery coordinator at process startup to
        signal that any in-flight hybrid executions have been interrupted by
        the restart.  Terminal records are left unchanged (idempotency).

        Parameters
        ----------
        reason:
            Human-readable reason for the interruption.

        Returns
        -------
        int
            Number of records transitioned to ``interrupted``.
        """
        count = 0
        for record in self._records.values():
            if record.is_terminal:
                continue
            if record.lifecycle_state == HybridOrchestrationLifecycleState.interrupted:
                continue
            # Only states that can transition to interrupted are:
            # dispatched → interrupted, running → interrupted
            if record.lifecycle_state in (
                HybridOrchestrationLifecycleState.dispatched,
                HybridOrchestrationLifecycleState.running,
                HybridOrchestrationLifecycleState.resuming,
            ):
                applied = record.transition(
                    HybridOrchestrationLifecycleState.interrupted,
                    reason=reason,
                )
                if applied:
                    count += 1
            elif record.lifecycle_state == HybridOrchestrationLifecycleState.created:
                # Created executions never started: cancel them directly
                applied = record.transition(
                    HybridOrchestrationLifecycleState.cancelled,
                    reason=reason,
                )
                if applied:
                    count += 1

        logger.info(
            "HybridOrchestrationContinuityRegistry: marked %d executions as "
            "interrupted/cancelled (reason=%r)",
            count,
            reason,
        )
        return count

    def clear_terminal(self) -> int:
        """Remove all terminal records from the registry.

        Returns
        -------
        int
            Number of records removed.
        """
        terminal_ids = [
            eid for eid, r in self._records.items() if r.is_terminal
        ]
        for eid in terminal_ids:
            del self._records[eid]
        logger.debug(
            "HybridOrchestrationContinuityRegistry: cleared %d terminal records",
            len(terminal_ids),
        )
        return len(terminal_ids)

    def count(self) -> int:
        """Return the total number of registered records."""
        return len(self._records)

    # ------------------------------------------------------------------
    # PR-6: partial-result and persistence integration
    # ------------------------------------------------------------------

    def invalidate_remote_partial_results(self) -> int:
        """Mark all remote partial results as ``invalidated`` (PR-6).

        Called by the recovery coordinator at process startup to classify
        any partial results whose origin is ``"remote"`` as ``invalidated``.
        Remote transport (A2A connections, GUI handles, VLM context) is gone
        after a restart so remote partial data can no longer be trusted.

        Local partial results (``partial_result_origin`` == ``"local"``) are
        left as-is; they are implicitly ``preserved`` for resume or merge.

        Terminal records are not modified.

        Returns
        -------
        int
            Number of records whose ``partial_result_disposition`` was set to
            ``"invalidated"``.
        """
        count = 0
        for record in self._records.values():
            if record.is_terminal:
                continue
            if (
                record.partial_result_snapshot is not None
                and record.partial_result_origin == "remote"
                and record.partial_result_disposition
                != HybridPartialResultDisposition.invalidated.value
            ):
                record.partial_result_disposition = (
                    HybridPartialResultDisposition.invalidated.value
                )
                count += 1
        logger.info(
            "HybridOrchestrationContinuityRegistry: invalidated %d remote "
            "partial results",
            count,
        )
        return count

    def restore_from_persistence(
        self,
        store: "HybridContinuityPersistenceStore",
        *,
        skip_terminal: bool = True,
    ) -> int:
        """Re-register records loaded from the durable persistence store (PR-6).

        This should be called once during restart recovery, after
        :meth:`mark_all_running_as_interrupted`, to reconstruct the registry
        with records that were durably saved before the restart.

        Records whose ``execution_id`` already exists in the registry are
        silently skipped (the in-process record takes precedence).

        Parameters
        ----------
        store:
            The :class:`HybridContinuityPersistenceStore` from which to load
            records.
        skip_terminal:
            When ``True`` (default), terminal records are not restored into
            the registry.  They remain on disk for audit.

        Returns
        -------
        int
            Number of records newly registered from the persistence store.
        """
        restored = store.list_recoverable() if skip_terminal else store.list_all()
        count = 0
        for record in restored:
            if record.execution_id in self._records:
                # In-process record takes precedence; skip
                continue
            self._records[record.execution_id] = record
            count += 1
        logger.info(
            "HybridOrchestrationContinuityRegistry: restored %d records "
            "from persistence store (skip_terminal=%s)",
            count,
            skip_terminal,
        )
        return count


# ---------------------------------------------------------------------------
# Singleton management — registry
# ---------------------------------------------------------------------------

_registry_instance: Optional[HybridOrchestrationContinuityRegistry] = None


def get_continuity_registry() -> HybridOrchestrationContinuityRegistry:
    """Return the process-level :class:`HybridOrchestrationContinuityRegistry`."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = HybridOrchestrationContinuityRegistry()
    return _registry_instance


def reset_continuity_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry_instance
    _registry_instance = None


# ---------------------------------------------------------------------------
# HybridContinuityPersistenceStore (PR-6)
# ---------------------------------------------------------------------------

_DEFAULT_HYBRID_STORE_DIR = os.path.join(
    os.environ.get(
        "GALAXY_DATA_DIR",
        os.path.join(os.path.dirname(__file__), "..", "data"),
    ),
    "hybrid_executions",
)


class HybridContinuityPersistenceStore:
    """Thread-safe, file-backed durable store for :class:`HybridOrchestrationRecord`.

    Each execution's record is stored as a single JSON file in *store_dir*.
    The filename is ``<execution_id>.json``.

    This store follows the same structural pattern as
    :class:`~core.mesh.mesh_session_persistence.MeshSessionPersistenceStore`:
    ``save`` writes atomically, ``load`` reads by key, ``list_recoverable``
    returns non-terminal records, and ``list_all`` returns every record on
    disk regardless of lifecycle state.

    Design principles
    -----------------
    - **Additive only** — does not modify any existing module.
    - **Terminal records are auditable** — terminal records are saved to disk
      but not returned by :meth:`list_recoverable`.  They remain for audit.
    - **Live transport handles NEVER persisted** — only JSON-serialisable
      fields from :meth:`HybridOrchestrationRecord.to_dict` are written.
    - **Atomic writes** — uses a ``.tmp`` file + ``os.replace`` for
      crash-safe updates.
    - **Thread-safe** — a per-store :class:`threading.Lock` guards all I/O.

    Parameters
    ----------
    store_dir:
        Directory in which to persist JSON files.  Created automatically
        if it does not exist.  Defaults to ``data/hybrid_executions/``
        relative to the repository root.
    """

    def __init__(self, store_dir: Optional[str] = None) -> None:
        self._store_dir = store_dir or _DEFAULT_HYBRID_STORE_DIR
        self._lock = threading.Lock()
        self._ensure_dir()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def save(self, record: HybridOrchestrationRecord) -> bool:
        """Persist *record* to disk.

        Parameters
        ----------
        record:
            The :class:`HybridOrchestrationRecord` to save.

        Returns
        -------
        bool
            ``True`` on success; ``False`` if the write failed.
        """
        if not record.execution_id:
            logger.warning(
                "HybridContinuityPersistenceStore: save skipped — empty execution_id"
            )
            return False
        try:
            data = record.to_dict()
            path = self._record_path(record.execution_id)
            tmp_path = path + ".tmp"
            with self._lock:
                with open(tmp_path, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
                os.replace(tmp_path, path)
            logger.debug(
                "HybridContinuityPersistenceStore: saved execution_id=%s "
                "state=%s",
                record.execution_id,
                record.lifecycle_state.value,
            )
            return True
        except Exception as exc:
            logger.warning(
                "HybridContinuityPersistenceStore: save failed "
                "execution_id=%s: %s",
                record.execution_id,
                exc,
            )
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            return False

    def load(self, execution_id: str) -> Optional[HybridOrchestrationRecord]:
        """Load a single record by *execution_id*.

        Returns ``None`` if not found or if the file is corrupt.
        """
        path = self._record_path(execution_id)
        with self._lock:
            if not os.path.exists(path):
                return None
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                return HybridOrchestrationRecord.from_dict(data)
            except Exception as exc:
                logger.warning(
                    "HybridContinuityPersistenceStore: load failed "
                    "execution_id=%s: %s",
                    execution_id,
                    exc,
                )
                return None

    def list_recoverable(self) -> List[HybridOrchestrationRecord]:
        """Return all non-terminal records from the store.

        Non-terminal states: created, dispatched, running, interrupted,
        resuming.  These are the records that can be restored into the live
        :class:`HybridOrchestrationContinuityRegistry` after restart.
        """
        return [r for r in self.list_all() if not r.is_terminal]

    def list_all(self) -> List[HybridOrchestrationRecord]:
        """Return all records from the store (terminal and non-terminal)."""
        records: List[HybridOrchestrationRecord] = []
        with self._lock:
            try:
                for fname in os.listdir(self._store_dir):
                    if not fname.endswith(".json"):
                        continue
                    path = os.path.join(self._store_dir, fname)
                    try:
                        with open(path, "r", encoding="utf-8") as fh:
                            data = json.load(fh)
                        records.append(HybridOrchestrationRecord.from_dict(data))
                    except Exception as exc:
                        logger.warning(
                            "HybridContinuityPersistenceStore: skipping "
                            "corrupt file %s: %s",
                            fname,
                            exc,
                        )
            except OSError as exc:
                logger.warning(
                    "HybridContinuityPersistenceStore: list_all failed: %s",
                    exc,
                )
        return records

    def delete(self, execution_id: str) -> bool:
        """Remove the persisted record for *execution_id*.

        Returns ``True`` if deleted, ``False`` if not found.
        """
        path = self._record_path(execution_id)
        with self._lock:
            if not os.path.exists(path):
                return False
            try:
                os.remove(path)
                logger.debug(
                    "HybridContinuityPersistenceStore: deleted execution_id=%s",
                    execution_id,
                )
                return True
            except OSError as exc:
                logger.warning(
                    "HybridContinuityPersistenceStore: delete failed "
                    "execution_id=%s: %s",
                    execution_id,
                    exc,
                )
                return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_dir(self) -> None:
        try:
            os.makedirs(self._store_dir, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "HybridContinuityPersistenceStore: could not create "
                "store_dir=%s: %s",
                self._store_dir,
                exc,
            )

    def _record_path(self, execution_id: str) -> str:
        return os.path.join(self._store_dir, f"{execution_id}.json")


# ---------------------------------------------------------------------------
# Singleton management — persistence store
# ---------------------------------------------------------------------------

_persistence_store_instance: Optional[HybridContinuityPersistenceStore] = None
_persistence_store_lock = threading.Lock()


def get_hybrid_persistence_store(
    store_dir: Optional[str] = None,
) -> HybridContinuityPersistenceStore:
    """Return the process-level :class:`HybridContinuityPersistenceStore`."""
    global _persistence_store_instance
    with _persistence_store_lock:
        if _persistence_store_instance is None:
            _persistence_store_instance = HybridContinuityPersistenceStore(
                store_dir=store_dir
            )
    return _persistence_store_instance


def reset_hybrid_persistence_store() -> None:
    """Reset the persistence store singleton (for testing)."""
    global _persistence_store_instance
    with _persistence_store_lock:
        _persistence_store_instance = None


# ---------------------------------------------------------------------------
# Module-level persistence convenience functions
# ---------------------------------------------------------------------------


def save_hybrid_execution(
    record: HybridOrchestrationRecord,
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> bool:
    """Persist *record* to the durable store.

    Parameters
    ----------
    record:
        The :class:`HybridOrchestrationRecord` to save.
    store:
        Optional explicit store.  Defaults to the process-level singleton.

    Returns
    -------
    bool
        ``True`` on success.
    """
    effective_store = store if store is not None else get_hybrid_persistence_store()
    return effective_store.save(record)


def load_hybrid_execution(
    execution_id: str,
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> Optional[HybridOrchestrationRecord]:
    """Load a record by *execution_id* from the durable store.

    Returns ``None`` if not found.
    """
    effective_store = store if store is not None else get_hybrid_persistence_store()
    return effective_store.load(execution_id)


def recover_hybrid_executions(
    *,
    store: Optional[HybridContinuityPersistenceStore] = None,
) -> List[HybridOrchestrationRecord]:
    """Return all non-terminal records from the durable store.

    Convenience entry-point for startup recovery::

        from core.hybrid_orchestration_continuity import recover_hybrid_executions
        records = recover_hybrid_executions()
        for r in records:
            registry.register(r)

    Returns
    -------
    list of :class:`HybridOrchestrationRecord`
        Records in non-terminal states that are eligible for restoration.
    """
    effective_store = store if store is not None else get_hybrid_persistence_store()
    return effective_store.list_recoverable()
