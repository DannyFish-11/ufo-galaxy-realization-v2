#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/inflight_task_continuity_contract.py
==========================================
PR-P1-1: In-Flight Task Continuity Contract — formal judgment of task-level
continuity restoration after restart / process bounce / controller recovery.

Problem addressed
-----------------
After restart the Galaxy V2 runtime can restore *state* (task records
re-hydrated into the lifecycle registry via
:mod:`core.task_lifecycle_persistence`) but previously could not formally
express whether *task-level continuity* was actually restored.

The gap was that existing code classified tasks by
:class:`~core.task_lifecycle_persistence.InFlightTaskDisposition` (what
*should be done* with a task) without producing a structured verdict on
whether *continuity was established*.  The system could say "RESUMABLE task
was re-registered" — which is state restoration — but not "this task's
execution continuity has been formally confirmed as recovered vs. merely
state-present vs. interrupted vs. abandoned".

This module closes that gap by defining:

1. :class:`TaskContinuityStatus` — the canonical per-task continuity verdict.
2. :class:`InFlightTaskContinuityRecord` — per-task continuity assessment
   record.
3. :class:`TaskContinuityReport` — aggregated, structured surface consumable
   by recovery / readiness / acceptance pipelines.
4. :class:`InFlightTaskContinuityContract` — evaluation logic that converts
   recovered :class:`~core.task_lifecycle_persistence.RestoredTaskRecord`
   objects plus live registry evidence into the above verdicts.
5. :func:`build_continuity_report` — convenience function.

Critical invariant
------------------
**State restored ≠ Continuity restored.**

A task that has been re-added to the live
:class:`~core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry`
is *state-present*, not *continuity-confirmed*.  The contract evaluator
enforces this by tracking:

* ``state_restored_count`` — tasks whose state is present in the registry
  (``resumed`` + ``recoverable``).
* ``continuity_restored_count`` — tasks whose execution continuity is
  *formally confirmed* (``resumed`` only: the task was already in the live
  registry before the recovery snapshot was consumed, meaning no interruption
  gap exists).
* ``continuity_gap_count`` — the difference; represents tasks where state is
  present but continuity has NOT been confirmed (``recoverable``).

Status classification rules
----------------------------
``resumed``
    The task_id was **already present** in the live registry when recovery
    ran (live state supersedes snapshot state).  No interruption gap exists;
    execution continuity is formally confirmed.

``recoverable``
    Disposition is ``RESUMABLE`` or ``REPLAY_ONLY``; dispatch action was
    taken (task re-entered registry).  State is present but continuity is
    **not yet confirmed** — device must reconnect (RESUMABLE) or routing
    must re-run (REPLAY_ONLY) before execution resumes.

``interrupted``
    Disposition is ``REISSUABLE`` (task was at gateway ingress); the task
    cannot auto-resume.  External action (re-issuance from the source) is
    required.

``abandoned``
    Disposition is ``TERMINAL_ON_INTERRUPT`` (task was in result completion;
    result may already have been delivered).  No safe continuity restoration
    is possible.

``needs_reconcile``
    Duplicate task_id in the snapshot, stale snapshot record (age beyond
    threshold), or conflicting state indicators.  Must be explicitly
    reconciled before any recovery action.

``ambiguous``
    task_id is empty/missing, disposition could not be determined, or
    critical fields are absent.  MUST NOT be upgraded to any positive
    status.

Policy sentinels
----------------
:data:`INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY`
    Affirms this module is the canonical continuity judgment layer.
:data:`STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY`
    Prohibits treating state restoration as continuity confirmation.
:data:`AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY`
    Prohibits upgrading ``ambiguous`` or ``needs_reconcile`` status.
:data:`INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY`
    Requires that interrupted/unreissuable tasks are downgraded, not
    optimistically classified.
:data:`DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY`
    Duplicate task_ids must yield ``needs_reconcile``, not ``recoverable``.
:data:`STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY`
    Stale snapshot records must yield ``needs_reconcile``, not ``resumed``.
:data:`CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY`
    The :class:`TaskContinuityReport` is the canonical surface for
    acceptance/readiness verdict consumption.

Public API
----------
Enumerations::

    TaskContinuityStatus

Dataclasses::

    InFlightTaskContinuityRecord
    TaskContinuityReport

Classes::

    InFlightTaskContinuityContract

Functions::

    build_continuity_report(
        restored_records,
        *,
        already_pending_ids=None,
        dispatched_ids=None,
        snapshot_timestamp=None,
        stale_threshold_seconds=None,
    ) -> TaskContinuityReport
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("Galaxy.InFlightTaskContinuityContract")

__all__ = [
    # Sentinels
    "INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY",
    "INFLIGHT_TASK_CONTINUITY_CONTRACT_PR_P1_1_SENTINEL",
    "STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY",
    "AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY",
    "INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY",
    "DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY",
    "STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY",
    "CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY",
    # Enumerations
    "TaskContinuityStatus",
    # Dataclasses
    "InFlightTaskContinuityRecord",
    "TaskContinuityReport",
    # Classes
    "InFlightTaskContinuityContract",
    # Functions
    "build_continuity_report",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY: str = (
    "INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY::"
    "core.inflight_task_continuity_contract is the canonical judgment layer "
    "for in-flight task continuity after restart / process bounce / controller "
    "recovery (PR-P1-1).  It converts recovered RestoredTaskRecord objects "
    "plus live registry evidence into formal TaskContinuityStatus verdicts "
    "and a structured TaskContinuityReport consumable by recovery, readiness, "
    "and acceptance pipelines."
)

INFLIGHT_TASK_CONTINUITY_CONTRACT_PR_P1_1_SENTINEL: str = (
    "INFLIGHT_TASK_CONTINUITY_CONTRACT_PR_P1_1::"
    "package=PR-P1-1 "
    "track=inflight-task-continuity-recovery-closure "
    "module=core.inflight_task_continuity_contract "
    "title=in-flight-task-continuity-contract-after-restart"
)

STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY: str = (
    "POLICY::STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_PR_P1_1: "
    "Re-inserting a recovered task into the lifecycle registry is *state "
    "restoration*, not *continuity confirmation*.  A task is classified as "
    "TaskContinuityStatus.resumed ONLY when its task_id was already present "
    "in the live registry at the time recovery ran — meaning no interruption "
    "gap existed.  All other cases where state is present but the execution "
    "thread was interrupted are classified as TaskContinuityStatus.recoverable "
    "at best.  Callers MUST NOT treat 'state in registry' as 'continuity "
    "restored'.  The continuity_gap_count field in TaskContinuityReport makes "
    "this gap explicit and machine-readable.  (PR-P1-1)"
)

AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY: str = (
    "POLICY::AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_PR_P1_1: "
    "Tasks classified as TaskContinuityStatus.ambiguous or "
    "TaskContinuityStatus.needs_reconcile MUST NOT be upgraded to any "
    "positive status (resumed, recoverable, interrupted) by any downstream "
    "consumer.  Ambiguous continuity means the system cannot determine whether "
    "the task is safe to resume, replay, or abandon.  Such tasks MUST remain "
    "in their ambiguous/reconcile classification until explicit operator or "
    "automated reconciliation resolves the ambiguity.  (PR-P1-1)"
)

INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY: str = (
    "POLICY::INTERRUPTED_TASK_MUST_BE_DOWNGRADED_PR_P1_1: "
    "Tasks with InFlightTaskDisposition.REISSUABLE (owned by gateway_ingress "
    "at interruption time) MUST be classified as TaskContinuityStatus.interrupted "
    "even when their snapshot record is well-formed and their state is present. "
    "REISSUABLE tasks cannot auto-resume; they require explicit re-issuance "
    "from the original source.  Classifying them as recoverable or resumed "
    "would be an optimistic upgrade that misrepresents the system's actual "
    "recovery posture.  (PR-P1-1)"
)

DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY: str = (
    "POLICY::DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_PR_P1_1: "
    "When the recovery snapshot contains more than one record with the same "
    "task_id, ALL occurrences of that task_id MUST be classified as "
    "TaskContinuityStatus.needs_reconcile.  The presence of duplicate records "
    "indicates a snapshot integrity issue or a race condition between snapshot "
    "writes; treating either record as authoritative without reconciliation "
    "risks duplicate ownership or duplicate completion.  (PR-P1-1)"
)

STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY: str = (
    "POLICY::STALE_RECOVERY_MUST_TRIGGER_RECONCILE_PR_P1_1: "
    "A snapshot record whose age (current_time - snapshot_created_at) exceeds "
    "STALE_SNAPSHOT_THRESHOLD_SECONDS MUST be classified as "
    "TaskContinuityStatus.needs_reconcile regardless of its disposition.  "
    "Stale records may represent tasks that were already completed, timed out, "
    "or abandoned before the snapshot was read.  Resuming or replaying them "
    "without reconciliation risks duplicate work or incorrect state transitions. "
    "(PR-P1-1)"
)

CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_POLICY: str = (
    "POLICY::CONTINUITY_REPORT_IS_CONSUMABLE_BY_ACCEPTANCE_PR_P1_1: "
    "TaskContinuityReport is the canonical structured surface for recovery, "
    "readiness, and acceptance pipeline consumption.  It exposes: "
    "continuity_restored_count (resumed tasks only), state_restored_count "
    "(resumed + recoverable), continuity_gap_count (state present but "
    "continuity not confirmed), has_unrecovered_tasks (any recoverable or "
    "interrupted), has_ambiguous_tasks (any ambiguous or needs_reconcile), "
    "and per-task InFlightTaskContinuityRecord entries.  "
    "acceptance/readiness verdicts that consume this report MUST distinguish "
    "continuity_restored from state_restored and MUST NOT declare recovery "
    "complete when continuity_gap_count > 0 or has_ambiguous_tasks is True. "
    "(PR-P1-1)"
)

# ---------------------------------------------------------------------------
# Default threshold for stale snapshot records
# ---------------------------------------------------------------------------

#: Records older than this many seconds are classified as needs_reconcile.
STALE_SNAPSHOT_THRESHOLD_SECONDS: float = 86400.0  # 24 hours


# ---------------------------------------------------------------------------
# TaskContinuityStatus
# ---------------------------------------------------------------------------


class TaskContinuityStatus(str, Enum):
    """Canonical per-task continuity status after restart recovery.

    Values
    ------
    resumed
        Execution continuity formally confirmed.  The task_id was already
        present in the live lifecycle registry when recovery ran — no
        interruption gap exists.  Live state supersedes snapshot state.

    recoverable
        State is present in the registry (dispatch action taken) but
        continuity is not yet confirmed.  For ``RESUMABLE`` tasks: device
        must reconnect before execution resumes.  For ``REPLAY_ONLY`` tasks:
        routing must re-run.  State restored ≠ continuity restored.

    interrupted
        Task cannot auto-resume.  ``REISSUABLE`` tasks (gateway_ingress
        ownership at interruption) need explicit re-issuance from the
        original source.  No automatic recovery path exists.

    abandoned
        No safe continuity restoration possible.  ``TERMINAL_ON_INTERRUPT``
        tasks were in result_completion; the result may already have been
        delivered.  Re-registering would risk duplicate completion.

    needs_reconcile
        Snapshot integrity issue: duplicate task_id, stale record, or
        conflicting state indicators.  Must be explicitly reconciled before
        any recovery action is taken.  MUST NOT be upgraded.

    ambiguous
        Insufficient information to classify.  task_id missing, disposition
        undetermined, or critical fields absent.  MUST NOT be upgraded to
        any positive status.
    """

    resumed = "resumed"
    recoverable = "recoverable"
    interrupted = "interrupted"
    abandoned = "abandoned"
    needs_reconcile = "needs_reconcile"
    ambiguous = "ambiguous"

    @property
    def is_positive(self) -> bool:
        """True for statuses that represent at least partial recovery progress."""
        return self in (
            TaskContinuityStatus.resumed,
            TaskContinuityStatus.recoverable,
        )

    @property
    def requires_action(self) -> bool:
        """True when explicit external action is required to proceed."""
        return self in (
            TaskContinuityStatus.interrupted,
            TaskContinuityStatus.needs_reconcile,
        )

    @property
    def is_terminal(self) -> bool:
        """True for statuses that represent a terminal or unrecoverable state."""
        return self in (
            TaskContinuityStatus.abandoned,
            TaskContinuityStatus.ambiguous,
        )


# ---------------------------------------------------------------------------
# InFlightTaskContinuityRecord
# ---------------------------------------------------------------------------


@dataclass
class InFlightTaskContinuityRecord:
    """Per-task continuity assessment record produced by the contract evaluator.

    Attributes
    ----------
    task_id
        Canonical task identifier.
    trace_id
        Distributed trace identifier.
    disposition
        :class:`~core.task_lifecycle_persistence.InFlightTaskDisposition`
        string value at the time of interruption.
    continuity_status
        Formal continuity verdict for this task.
    reason
        Human-readable explanation of the verdict.
    device_id
        Target device at interruption time (may be empty).
    snapshot_age_seconds
        Age of the snapshot record in seconds at evaluation time.
    snapshot_id
        Identifier of the recovery snapshot this record came from.
    evaluated_at
        Unix timestamp when this record was evaluated.
    """

    task_id: str = ""
    trace_id: str = ""
    disposition: str = ""
    continuity_status: TaskContinuityStatus = TaskContinuityStatus.ambiguous
    reason: str = ""
    device_id: str = ""
    snapshot_age_seconds: float = 0.0
    snapshot_id: str = ""
    evaluated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "disposition": self.disposition,
            "continuity_status": self.continuity_status.value,
            "reason": self.reason,
            "device_id": self.device_id,
            "snapshot_age_seconds": self.snapshot_age_seconds,
            "snapshot_id": self.snapshot_id,
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InFlightTaskContinuityRecord":
        """Reconstruct from a serialised dict."""
        raw_status = d.get("continuity_status", "ambiguous")
        try:
            status = TaskContinuityStatus(raw_status)
        except ValueError:
            status = TaskContinuityStatus.ambiguous
        return cls(
            task_id=d.get("task_id", ""),
            trace_id=d.get("trace_id", ""),
            disposition=d.get("disposition", ""),
            continuity_status=status,
            reason=d.get("reason", ""),
            device_id=d.get("device_id", ""),
            snapshot_age_seconds=float(d.get("snapshot_age_seconds", 0.0)),
            snapshot_id=d.get("snapshot_id", ""),
            evaluated_at=float(d.get("evaluated_at", 0.0)),
        )


# ---------------------------------------------------------------------------
# TaskContinuityReport
# ---------------------------------------------------------------------------


@dataclass
class TaskContinuityReport:
    """Structured, aggregated in-flight task continuity surface.

    This is the canonical output of :class:`InFlightTaskContinuityContract`
    and is designed to be consumed by recovery, readiness, and acceptance
    pipelines.

    Attributes
    ----------
    report_id
        Unique identifier for this report.
    generated_at
        Unix timestamp when the report was assembled.
    continuity_sentinel
        Copy of :data:`INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY`.
    total_evaluated
        Total number of task records evaluated.
    resumed_count
        Tasks with ``resumed`` status — execution continuity formally
        confirmed (task was already in live registry at recovery time).
    recoverable_count
        Tasks with ``recoverable`` status — state present, continuity
        pending (device reconnect or routing re-run required).
    interrupted_count
        Tasks with ``interrupted`` status — need external re-issuance.
    abandoned_count
        Tasks with ``abandoned`` status — no safe recovery path.
    needs_reconcile_count
        Tasks with ``needs_reconcile`` status — duplicate/stale/conflicting.
    ambiguous_count
        Tasks with ``ambiguous`` status — insufficient information.
    records
        Per-task :class:`InFlightTaskContinuityRecord` entries.
    state_restored_count
        ``resumed_count + recoverable_count`` — tasks whose state is
        present in the registry.  This is NOT continuity confirmation.
    continuity_restored_count
        ``resumed_count`` only — tasks whose execution continuity is
        formally confirmed.
    continuity_gap_count
        ``state_restored_count - continuity_restored_count`` — tasks where
        state is present but continuity has NOT been confirmed.
        A value > 0 means recovery is incomplete at the task level.
    has_unrecovered_tasks
        True when any task is ``recoverable`` or ``interrupted``.
    has_ambiguous_tasks
        True when any task is ``ambiguous`` or ``needs_reconcile``.
    """

    report_id: str = field(default_factory=lambda: f"ctyr_{uuid.uuid4().hex[:12]}")
    generated_at: float = field(default_factory=time.time)
    continuity_sentinel: str = INFLIGHT_TASK_CONTINUITY_CONTRACT_IS_AUTHORITY

    total_evaluated: int = 0
    resumed_count: int = 0
    recoverable_count: int = 0
    interrupted_count: int = 0
    abandoned_count: int = 0
    needs_reconcile_count: int = 0
    ambiguous_count: int = 0

    records: List[InFlightTaskContinuityRecord] = field(default_factory=list)

    @property
    def state_restored_count(self) -> int:
        """Tasks with state present in the registry (resumed + recoverable)."""
        return self.resumed_count + self.recoverable_count

    @property
    def continuity_restored_count(self) -> int:
        """Tasks with formally confirmed execution continuity (resumed only)."""
        return self.resumed_count

    @property
    def continuity_gap_count(self) -> int:
        """Tasks where state is present but continuity is NOT confirmed."""
        return self.state_restored_count - self.continuity_restored_count

    @property
    def has_unrecovered_tasks(self) -> bool:
        """True when any recoverable or interrupted tasks remain."""
        return (self.recoverable_count + self.interrupted_count) > 0

    @property
    def has_ambiguous_tasks(self) -> bool:
        """True when any ambiguous or needs_reconcile tasks exist."""
        return (self.ambiguous_count + self.needs_reconcile_count) > 0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "continuity_sentinel": self.continuity_sentinel,
            "total_evaluated": self.total_evaluated,
            "resumed_count": self.resumed_count,
            "recoverable_count": self.recoverable_count,
            "interrupted_count": self.interrupted_count,
            "abandoned_count": self.abandoned_count,
            "needs_reconcile_count": self.needs_reconcile_count,
            "ambiguous_count": self.ambiguous_count,
            "state_restored_count": self.state_restored_count,
            "continuity_restored_count": self.continuity_restored_count,
            "continuity_gap_count": self.continuity_gap_count,
            "has_unrecovered_tasks": self.has_unrecovered_tasks,
            "has_ambiguous_tasks": self.has_ambiguous_tasks,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TaskContinuityReport":
        """Reconstruct from a serialised dict."""
        obj = cls(
            report_id=d.get("report_id", ""),
            generated_at=float(d.get("generated_at", 0.0)),
            continuity_sentinel=d.get("continuity_sentinel", ""),
            total_evaluated=int(d.get("total_evaluated", 0)),
            resumed_count=int(d.get("resumed_count", 0)),
            recoverable_count=int(d.get("recoverable_count", 0)),
            interrupted_count=int(d.get("interrupted_count", 0)),
            abandoned_count=int(d.get("abandoned_count", 0)),
            needs_reconcile_count=int(d.get("needs_reconcile_count", 0)),
            ambiguous_count=int(d.get("ambiguous_count", 0)),
            records=[
                InFlightTaskContinuityRecord.from_dict(r)
                for r in d.get("records", [])
            ],
        )
        return obj


# ---------------------------------------------------------------------------
# InFlightTaskContinuityContract
# ---------------------------------------------------------------------------


class InFlightTaskContinuityContract:
    """Evaluates in-flight task continuity after restart recovery.

    Converts a list of recovered
    :class:`~core.task_lifecycle_persistence.RestoredTaskRecord` objects
    plus live registry evidence into formal :class:`TaskContinuityStatus`
    verdicts and a structured :class:`TaskContinuityReport`.

    This class is the single authoritative source for the distinction between
    *state restored* and *continuity restored* (see
    :data:`STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY`).

    Parameters
    ----------
    stale_threshold_seconds
        Snapshot records older than this many seconds are classified as
        ``needs_reconcile``.  Defaults to
        :data:`STALE_SNAPSHOT_THRESHOLD_SECONDS` (24 hours).
    """

    def __init__(
        self,
        stale_threshold_seconds: float = STALE_SNAPSHOT_THRESHOLD_SECONDS,
    ) -> None:
        self._stale_threshold = stale_threshold_seconds

    def evaluate(
        self,
        restored_records: List[Any],
        *,
        already_pending_ids: Optional[Set[str]] = None,
        dispatched_ids: Optional[Set[str]] = None,
        snapshot_timestamp: Optional[float] = None,
    ) -> TaskContinuityReport:
        """Evaluate continuity for a list of recovered task records.

        Parameters
        ----------
        restored_records
            List of :class:`~core.task_lifecycle_persistence.RestoredTaskRecord`
            instances from :func:`~core.task_lifecycle_persistence
            .restore_inflight_tasks_from_snapshot`.
        already_pending_ids
            Set of ``task_id`` strings that were already present in the live
            lifecycle registry when the recovery snapshot was consumed.  Tasks
            in this set receive ``resumed`` status (live state supersedes
            snapshot; no interruption gap).
        dispatched_ids
            Set of ``task_id`` strings for which a dispatch action was taken
            during recovery (task was re-registered in the lifecycle registry).
            Tasks in this set (but not in ``already_pending_ids``) receive
            ``recoverable`` or ``interrupted`` status depending on their
            disposition.
        snapshot_timestamp
            Unix timestamp when the snapshot was written.  Used to compute
            ``snapshot_age_seconds`` for stale detection.  If not provided,
            falls back to ``RestoredTaskRecord.registered_at``.

        Returns
        -------
        TaskContinuityReport
        """
        already_pending: Set[str] = set(already_pending_ids or [])
        dispatched: Set[str] = set(dispatched_ids or [])
        now = time.time()

        # Detect duplicate task_ids in the snapshot (MUST yield needs_reconcile).
        task_id_occurrences: Dict[str, int] = {}
        for rec in restored_records:
            tid = getattr(rec, "task_id", None) or ""
            if tid:
                task_id_occurrences[tid] = task_id_occurrences.get(tid, 0) + 1

        duplicate_task_ids: Set[str] = {
            tid for tid, cnt in task_id_occurrences.items() if cnt > 1
        }

        report = TaskContinuityReport()
        report.total_evaluated = len(restored_records)

        for rec in restored_records:
            entry = self._evaluate_record(
                rec,
                already_pending=already_pending,
                dispatched=dispatched,
                duplicate_task_ids=duplicate_task_ids,
                now=now,
                snapshot_timestamp=snapshot_timestamp,
            )
            report.records.append(entry)
            if entry.continuity_status == TaskContinuityStatus.resumed:
                report.resumed_count += 1
            elif entry.continuity_status == TaskContinuityStatus.recoverable:
                report.recoverable_count += 1
            elif entry.continuity_status == TaskContinuityStatus.interrupted:
                report.interrupted_count += 1
            elif entry.continuity_status == TaskContinuityStatus.abandoned:
                report.abandoned_count += 1
            elif entry.continuity_status == TaskContinuityStatus.needs_reconcile:
                report.needs_reconcile_count += 1
            else:
                report.ambiguous_count += 1

        logger.info(
            "InFlightTaskContinuityContract.evaluate: total=%d "
            "resumed=%d recoverable=%d interrupted=%d abandoned=%d "
            "needs_reconcile=%d ambiguous=%d | "
            "state_restored=%d continuity_restored=%d continuity_gap=%d",
            report.total_evaluated,
            report.resumed_count,
            report.recoverable_count,
            report.interrupted_count,
            report.abandoned_count,
            report.needs_reconcile_count,
            report.ambiguous_count,
            report.state_restored_count,
            report.continuity_restored_count,
            report.continuity_gap_count,
        )
        return report

    def _evaluate_record(
        self,
        rec: Any,
        *,
        already_pending: Set[str],
        dispatched: Set[str],
        duplicate_task_ids: Set[str],
        now: float,
        snapshot_timestamp: Optional[float],
    ) -> InFlightTaskContinuityRecord:
        """Evaluate a single recovered task record."""
        task_id: str = getattr(rec, "task_id", None) or ""
        trace_id: str = getattr(rec, "trace_id", None) or ""
        device_id: str = getattr(rec, "target_device_id", None) or ""
        snapshot_id: str = getattr(rec, "snapshot_id", None) or ""
        registered_at: float = float(getattr(rec, "registered_at", now) or now)
        disposition_raw: str = ""

        # Extract disposition value — handles enum or string
        raw_disp = getattr(rec, "disposition", None)
        if raw_disp is not None:
            disposition_raw = (
                raw_disp.value if hasattr(raw_disp, "value") else str(raw_disp)
            )

        # Compute snapshot age
        ref_ts = snapshot_timestamp if snapshot_timestamp is not None else registered_at
        snapshot_age = now - ref_ts

        entry = InFlightTaskContinuityRecord(
            task_id=task_id,
            trace_id=trace_id,
            disposition=disposition_raw,
            device_id=device_id,
            snapshot_age_seconds=snapshot_age,
            snapshot_id=snapshot_id,
        )

        # Rule 1: ambiguous — missing task_id
        if not task_id:
            entry.continuity_status = TaskContinuityStatus.ambiguous
            entry.reason = (
                "task_id is empty or missing; cannot evaluate continuity. "
                "See AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY."
            )
            return entry

        # Rule 2: duplicate task_id → needs_reconcile
        # (Enforce DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY)
        if task_id in duplicate_task_ids:
            entry.continuity_status = TaskContinuityStatus.needs_reconcile
            entry.reason = (
                f"task_id={task_id!r} appears more than once in the recovery "
                "snapshot; snapshot integrity cannot be assumed. "
                "See DUPLICATE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY."
            )
            return entry

        # Rule 3: stale record → needs_reconcile
        # (Enforce STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY)
        if snapshot_age > self._stale_threshold:
            entry.continuity_status = TaskContinuityStatus.needs_reconcile
            entry.reason = (
                f"task_id={task_id!r} snapshot record is stale "
                f"(age={snapshot_age:.1f}s > threshold={self._stale_threshold:.1f}s); "
                "may represent a task that timed out or was completed before "
                "the snapshot was consumed. "
                "See STALE_RECOVERY_MUST_TRIGGER_RECONCILE_POLICY."
            )
            return entry

        # Rule 4: already in live registry → resumed
        # (Enforce STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY — but the
        #  EXCEPTION is that if the task was ALREADY active before recovery
        #  ran, no interruption gap exists.)
        if task_id in already_pending:
            entry.continuity_status = TaskContinuityStatus.resumed
            entry.reason = (
                f"task_id={task_id!r} was already present in the live lifecycle "
                "registry at recovery time — live state supersedes snapshot; "
                "execution continuity is formally confirmed. "
                "See STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY."
            )
            return entry

        # Rules 5–8: classify by disposition
        # (terminal check must happen BEFORE dispatch check)
        if disposition_raw == "terminal_on_interrupt":
            entry.continuity_status = TaskContinuityStatus.abandoned
            entry.reason = (
                f"task_id={task_id!r} disposition=TERMINAL_ON_INTERRUPT: "
                "task was in result_completion at interruption; result may "
                "already have been delivered.  No safe continuity restoration "
                "is possible.  See INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY."
            )
            return entry

        if disposition_raw == "reissuable":
            # REISSUABLE tasks MUST be interrupted, not recoverable, even
            # if state was placed in the registry.
            # (INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY)
            entry.continuity_status = TaskContinuityStatus.interrupted
            entry.reason = (
                f"task_id={task_id!r} disposition=REISSUABLE: task was at "
                "gateway_ingress at interruption; cannot auto-resume; explicit "
                "re-issuance from the original source is required. "
                "See INTERRUPTED_TASK_MUST_BE_DOWNGRADED_POLICY."
            )
            return entry

        if disposition_raw in ("resumable", "replay_only"):
            if task_id in dispatched:
                # State is present, dispatch was taken.
                # BUT continuity is NOT confirmed (device must reconnect or
                # routing must re-run).  Classify as recoverable.
                # (STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY)
                entry.continuity_status = TaskContinuityStatus.recoverable
                if disposition_raw == "resumable":
                    entry.reason = (
                        f"task_id={task_id!r} disposition=RESUMABLE: dispatch "
                        "action taken; task is in live registry under "
                        "DEVICE_DISPATCH ownership.  State present but continuity "
                        "not confirmed — device must reconnect and re-dispatch "
                        "before execution resumes. "
                        "See STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY."
                    )
                else:
                    entry.reason = (
                        f"task_id={task_id!r} disposition=REPLAY_ONLY: dispatch "
                        "action taken; task is in live registry under ROUTING "
                        "ownership.  State present but continuity not confirmed "
                        "— routing layer must re-run before execution resumes. "
                        "See STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY."
                    )
            else:
                # Dispatch was NOT taken (e.g., registry unavailable, dispatch
                # was skipped for another reason not captured in already_pending).
                # State may not even be present.
                entry.continuity_status = TaskContinuityStatus.recoverable
                entry.reason = (
                    f"task_id={task_id!r} disposition={disposition_raw.upper()}: "
                    "dispatch action not confirmed taken; task may not be in the "
                    "live registry.  Classify as recoverable to avoid false "
                    "continuity claims — operator must verify registry state. "
                    "See STATE_RESTORED_IS_NOT_CONTINUITY_RESTORED_POLICY."
                )
            return entry

        # Fallthrough: unknown disposition → ambiguous
        entry.continuity_status = TaskContinuityStatus.ambiguous
        entry.reason = (
            f"task_id={task_id!r} disposition={disposition_raw!r} is unknown; "
            "cannot determine continuity status. "
            "See AMBIGUOUS_CONTINUITY_MUST_NOT_BE_UPGRADED_POLICY."
        )
        return entry


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def build_continuity_report(
    restored_records: List[Any],
    *,
    already_pending_ids: Optional[Set[str]] = None,
    dispatched_ids: Optional[Set[str]] = None,
    snapshot_timestamp: Optional[float] = None,
    stale_threshold_seconds: Optional[float] = None,
) -> TaskContinuityReport:
    """Build a :class:`TaskContinuityReport` from recovered task records.

    Convenience wrapper around :class:`InFlightTaskContinuityContract`.

    Parameters
    ----------
    restored_records
        List of :class:`~core.task_lifecycle_persistence.RestoredTaskRecord`
        instances.
    already_pending_ids
        Set of ``task_id`` strings already in the live lifecycle registry.
    dispatched_ids
        Set of ``task_id`` strings for which dispatch actions were taken.
    snapshot_timestamp
        Unix timestamp when the snapshot was written.
    stale_threshold_seconds
        Override for the stale threshold.  Defaults to
        :data:`STALE_SNAPSHOT_THRESHOLD_SECONDS`.

    Returns
    -------
    TaskContinuityReport
    """
    threshold = (
        stale_threshold_seconds
        if stale_threshold_seconds is not None
        else STALE_SNAPSHOT_THRESHOLD_SECONDS
    )
    contract = InFlightTaskContinuityContract(stale_threshold_seconds=threshold)
    return contract.evaluate(
        restored_records,
        already_pending_ids=already_pending_ids,
        dispatched_ids=dispatched_ids,
        snapshot_timestamp=snapshot_timestamp,
    )
