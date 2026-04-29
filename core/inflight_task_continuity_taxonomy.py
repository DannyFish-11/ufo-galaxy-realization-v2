#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/inflight_task_continuity_taxonomy.py
==========================================
PR-06: In-Flight Task Continuity Taxonomy — formal system-level classification
of in-flight task continuity restoration after restart / process bounce /
controller recovery.

Problem addressed
-----------------
After restart the Galaxy V2 runtime can restore *state* (task records
re-hydrated into the lifecycle registry) and can evaluate per-task continuity
status via :mod:`core.inflight_task_continuity_contract`.  However, previously
there was no canonical **system-level taxonomy** that expressed the overall
in-flight task continuity posture with strict downgrade semantics.

The existing per-task :class:`~core.inflight_task_continuity_contract
.TaskContinuityStatus` classifies individual tasks but does not produce a
single formal verdict that acceptance / readiness / governance pipelines can
consume to answer: "has authoritative in-flight task continuity been restored
after this restart?"

This module closes that gap by defining a formal **In-Flight Task Continuity
Taxonomy** and contract that:

1. Establishes five mutually exclusive and exhaustive
   :class:`InFlightTaskContinuityClass` verdicts.
2. Defines precise evidence requirements for each class.
3. Enforces conservative *downgrade semantics*: insufficient evidence always
   yields the lowest applicable class rather than the optimistic one.
4. Prohibits treating task snapshot presence, replay/reconcile initiation, or
   result ingestion as equivalent to authoritative task continuity restoration.
5. Provides an :class:`InFlightTaskContinuityVerdict` dataclass that is
   consumable by recovery / readiness / acceptance pipelines.

Architecture role
-----------------
::

    ┌─────────────────────────────────────────────────────────────────────┐
    │  IN-FLIGHT TASK CONTINUITY TAXONOMY  (this module — PR-06)         │
    │                                                                     │
    │  Five continuity classes (strictly ordered):                       │
    │    1. authoritative_task_continuity_restored  (highest — all tasks │
    │       already lived in the registry at recovery time; no gap)      │
    │    2. resumable_with_replay_or_reconcile  (recoverable tasks exist;│
    │       replay / device reconnect / routing re-run can complete them)│
    │    3. state_restored_not_resumed  (state in registry or snapshot   │
    │       but no active recovery path with confirmed dispatch)         │
    │    4. history_or_evidence_only  (no live state; only historical    │
    │       records / completed results visible in evidence store)       │
    │    5. task_continuity_lost  (lowest — no tasks, or all abandoned / │
    │       ambiguous / interrupted with no history either)              │
    │                                                                     │
    │  Evidence dimensions evaluated:                                    │
    │    • resumed_count        — tasks already live at recovery time    │
    │    • recoverable_count    — state present; replay/reconnect needed │
    │    • interrupted_count    — need external re-issuance              │
    │    • abandoned_count      — terminal; no safe recovery path        │
    │    • needs_reconcile_count — duplicate/stale; reconcile required   │
    │    • ambiguous_count      — missing data; cannot classify          │
    │    • result_or_history_visible — evidence in durable store         │
    │    • execution_context_rebuilt — runtime contexts re-established   │
    │    • process_death_observed   — crash/restart/bounce detected      │
    │    • partial_recovery_only    — only partial recovery performed    │
    │                                                                     │
    │  Downgrade semantics:                                              │
    │    • snapshot-only → NEVER authoritative_task_continuity_restored  │
    │    • recoverable tasks without completed replay → NEVER            │
    │      authoritative_task_continuity_restored                        │
    │    • result present / history visible alone → NEVER higher than    │
    │      history_or_evidence_only                                      │
    │    • partial_recovery_only → cap at resumable_with_replay_or_      │
    │      reconcile (never authoritative)                               │
    │    • no evidence → task_continuity_lost                            │
    │                                                                     │
    │  Produces:                                                         │
    │    • InFlightTaskContinuityVerdict  (structured output)            │
    │                                                                     │
    │  Consumed by:                                                      │
    │    • system_final_acceptance_verdict (task_continuity dimension)   │
    │    • recovery / readiness / acceptance pipelines                   │
    └─────────────────────────────────────────────────────────────────────┘

Design principles
-----------------
1. **Additive only** — no existing module is modified by this file.
2. **Fail-conservative** — missing or ambiguous evidence yields the lowest
   defensible class rather than the optimistic one.
3. **No optimistic promotion** — snapshot presence, replay initiation,
   reconcile triggering, and result ingestion are explicitly excluded from
   being promoted to ``authoritative_task_continuity_restored``.
4. **Taxonomy boundary enforcement** — replay/reconcile/rebind/result-ingestion
   are treated as *separate* evidence dimensions from task continuity.
   Presence of any one does not imply the others.
5. **Projection-only** — this module evaluates evidence fed to it; it never
   mutates external state.

Critical boundary: what counts as continuity vs what does not
-------------------------------------------------------------
- **Task snapshot present** — does NOT imply continuity; snapshot shows state
  existed but says nothing about whether execution was interrupted.
- **Replay initiated / completed** — does NOT imply continuity; replay
  re-executes a task from a saved state, but the execution thread was
  interrupted at restart time.  Only ``resumed`` (task was already in the live
  registry at recovery time) implies no interruption gap.
- **Reconcile triggered** — does NOT imply continuity; reconcile resolves
  duplicate or stale records, not the interruption gap.
- **Rebind completed** — does NOT imply task continuity; client rebinding
  restores the conversation layer, not the task execution thread.
- **Result ingested** — does NOT imply continuity; a completed result visible
  in the evidence store means the task *was* completed, not that it continued
  without interruption.

Public API
----------
Sentinels::

    INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY
    INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL
    SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY
    REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY
    RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY
    RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY
    PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY
    EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY

Enumerations::

    InFlightTaskContinuityClass

Dataclasses::

    InFlightTaskContinuityEvidence
    InFlightTaskContinuityVerdict

Classes::

    InFlightTaskContinuityTaxonomyContract

Functions::

    build_task_continuity_verdict(
        evidence,
    ) -> InFlightTaskContinuityVerdict

    build_task_continuity_verdict_from_report(
        report,
        *,
        result_or_history_visible=False,
        execution_context_rebuilt=False,
        process_death_observed=False,
        partial_recovery_only=False,
    ) -> InFlightTaskContinuityVerdict
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.InFlightTaskContinuityTaxonomy")

__all__ = [
    # Sentinels
    "INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY",
    "INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL",
    "SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY",
    "REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY",
    "RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY",
    "RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY",
    "PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY",
    "EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY",
    # Enumerations
    "InFlightTaskContinuityClass",
    # Dataclasses
    "InFlightTaskContinuityEvidence",
    "InFlightTaskContinuityVerdict",
    # Classes
    "InFlightTaskContinuityTaxonomyContract",
    # Functions
    "build_task_continuity_verdict",
    "build_task_continuity_verdict_from_report",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY: str = (
    "INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY::"
    "core.inflight_task_continuity_taxonomy is the canonical authority for "
    "system-level in-flight task continuity classification after restart / "
    "process bounce / controller recovery (PR-06).  It converts structured "
    "evidence (per-task status counts, result/history visibility, execution "
    "context rebuild status) into a formal InFlightTaskContinuityClass verdict "
    "consumable by recovery, readiness, and acceptance pipelines.  This module "
    "is the system-level companion to core.inflight_task_continuity_contract "
    "which provides per-task verdicts."
)

INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL: str = (
    "INFLIGHT_TASK_CONTINUITY_TAXONOMY_PR06_SENTINEL::"
    "package=PR-06 "
    "track=inflight-task-continuity-taxonomy-formalization "
    "module=core.inflight_task_continuity_taxonomy "
    "title=restart-authoritative-inflight-task-continuity-taxonomy"
)

SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY: str = (
    "POLICY::SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_PR06: "
    "The presence of a task snapshot (a persisted record of a task's state at "
    "the time of interruption) is NOT equivalent to authoritative in-flight "
    "task continuity restoration.  A snapshot shows that task state was "
    "captured before the interruption gap, not that continuity was preserved "
    "across the gap.  Systems MUST NOT promote a verdict to "
    "authoritative_task_continuity_restored on the basis of snapshot presence "
    "alone.  Only tasks whose task_id was already present in the live lifecycle "
    "registry when recovery ran (TaskContinuityStatus.resumed) have no "
    "interruption gap and qualify as authoritative.  (PR-06)"
)

REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY: str = (
    "POLICY::REPLAY_COMPLETION_IS_NOT_CONTINUITY_PR06: "
    "Completing a task replay (re-executing a task from a persisted snapshot "
    "state) does NOT restore authoritative in-flight task continuity.  Replay "
    "means the task was re-started from a saved checkpoint; the execution "
    "thread was interrupted at restart time.  Even after successful replay "
    "completion, the verdict MUST remain at most "
    "resumable_with_replay_or_reconcile until the replay result is formally "
    "confirmed as a valid continuation.  (PR-06)"
)

RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY: str = (
    "POLICY::RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_PR06: "
    "Triggering or completing reconciliation (resolving duplicate or stale "
    "task records in the recovery snapshot) does NOT restore authoritative "
    "task continuity.  Reconcile addresses snapshot integrity issues; it "
    "does not confirm that the execution thread was uninterrupted.  A "
    "needs_reconcile task remains at state_restored_not_resumed or lower "
    "until reconciliation confirms the task's status.  (PR-06)"
)

RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY: str = (
    "POLICY::RESULT_INGESTION_IS_NOT_CONTINUITY_PR06: "
    "The presence of a completed task result in the evidence store (result "
    "ingested from a prior execution) does NOT indicate that in-flight task "
    "continuity was preserved.  A visible result means the task completed "
    "before or during the interruption; it is evidence that the task is no "
    "longer in-flight, not that its execution thread continued without "
    "interruption.  result_or_history_visible evidence at most supports "
    "history_or_evidence_only, never a higher class.  (PR-06)"
)

PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY: str = (
    "POLICY::PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_PR06: "
    "When partial_recovery_only is True (recovery was known to be incomplete "
    "— some state missing, some dispatch failed, or recovery aborted early), "
    "the verdict MUST NOT reach authoritative_task_continuity_restored.  The "
    "maximum achievable class under partial recovery is "
    "resumable_with_replay_or_reconcile if recoverable tasks exist, or "
    "state_restored_not_resumed if only state is visible.  This invariant "
    "prevents optimistic promotion after an incomplete recovery pass.  (PR-06)"
)

EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY: str = (
    "POLICY::EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_PR06: "
    "When a required evidence dimension is absent (not observed, not confirmed, "
    "or not determinable) the verdict MUST be degraded to the lowest class "
    "supported by the available evidence.  It is PROHIBITED to assume that an "
    "unobserved dimension is 'likely present' or 'probably ok'.  Unknown or "
    "absent evidence MUST be treated as not-present for verdict computation.  "
    "An empty snapshot or all-ambiguous/abandoned evidence MUST yield "
    "task_continuity_lost.  (PR-06)"
)


# ---------------------------------------------------------------------------
# InFlightTaskContinuityClass
# ---------------------------------------------------------------------------


class InFlightTaskContinuityClass(str, Enum):
    """Canonical system-level in-flight task continuity classification.

    Values are strictly ordered from highest (most continuity assured) to
    lowest (no continuity).  Downgrade semantics apply: insufficient evidence
    always yields the lowest class that honest evidence supports.

    Values
    ------
    authoritative_task_continuity_restored
        Full authoritative in-flight task continuity has been restored.
        Requires ALL of the following: total_evaluated > 0, ALL tasks have
        ``resumed`` status (already in the live registry when recovery ran —
        no interruption gap exists), no recoverable/interrupted/abandoned/
        needs_reconcile/ambiguous tasks present, and NOT partial_recovery_only.
        This is the only class that confirms execution continuity was never
        interrupted.

    resumable_with_replay_or_reconcile
        Recovery path exists but is not yet complete.  At least one task has
        ``recoverable`` status (state present, dispatch taken, device reconnect
        or routing re-run still needed).  The tasks CAN be brought back to full
        execution via replay / device reconnect / routing re-run, but this has
        not yet happened.  State ≠ continuity.

    state_restored_not_resumed
        Task state is present (in registry or snapshot) but no authoritative
        continuity is confirmed and no active replay/reconcile path is live.
        Applies when: only ``needs_reconcile`` tasks exist (state visible but
        reconciliation required before any action), or a mix of resumed and
        non-recoverable tasks is present without an active recovery path.
        Execution contexts have not been rebuilt.

    history_or_evidence_only
        No live task state exists in the registry.  Only historical records
        (completed results, audit logs, snapshot archives) are visible in the
        durable evidence store.  No active recovery path can restore
        in-flight execution.  The tasks are historically visible but not
        resumable from the current process state.

    task_continuity_lost
        No in-flight task continuity.  Either no tasks were evaluated, all
        tasks are in terminal/ambiguous states (abandoned, interrupted with no
        re-issuance path, ambiguous) AND no history is visible, or evidence is
        entirely absent.  This is the conservative default when no recovery
        evidence is present.
    """

    authoritative_task_continuity_restored = "authoritative_task_continuity_restored"
    resumable_with_replay_or_reconcile = "resumable_with_replay_or_reconcile"
    state_restored_not_resumed = "state_restored_not_resumed"
    history_or_evidence_only = "history_or_evidence_only"
    task_continuity_lost = "task_continuity_lost"

    @property
    def rank(self) -> int:
        """Numeric rank (higher = more continuity).  Used for ordering."""
        return _TASK_CONTINUITY_CLASS_RANK[self.value]

    def is_at_least(self, other: "InFlightTaskContinuityClass") -> bool:
        """True when this class has equal or higher continuity than *other*."""
        return self.rank >= other.rank

    @property
    def is_authoritative(self) -> bool:
        """True only for ``authoritative_task_continuity_restored``."""
        return self == InFlightTaskContinuityClass.authoritative_task_continuity_restored

    @property
    def requires_replay_or_reconcile(self) -> bool:
        """True when replay, reconcile, or device reconnect is still needed."""
        return self == InFlightTaskContinuityClass.resumable_with_replay_or_reconcile

    @property
    def is_state_only(self) -> bool:
        """True when state is visible but execution has not resumed."""
        return self == InFlightTaskContinuityClass.state_restored_not_resumed

    @property
    def is_evidence_only(self) -> bool:
        """True when only historical evidence is available (no live state)."""
        return self == InFlightTaskContinuityClass.history_or_evidence_only

    @property
    def is_lost(self) -> bool:
        """True when task continuity is definitively lost."""
        return self == InFlightTaskContinuityClass.task_continuity_lost

    @classmethod
    def from_string(cls, value: str) -> "InFlightTaskContinuityClass":
        """Return the matching member, defaulting to ``task_continuity_lost``."""
        if not isinstance(value, str):
            return cls.task_continuity_lost
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.task_continuity_lost


# Class-level rank mapping (defined after class to avoid forward-ref issues)
_TASK_CONTINUITY_CLASS_RANK: Dict[str, int] = {
    InFlightTaskContinuityClass.task_continuity_lost.value: 0,
    InFlightTaskContinuityClass.history_or_evidence_only.value: 1,
    InFlightTaskContinuityClass.state_restored_not_resumed.value: 2,
    InFlightTaskContinuityClass.resumable_with_replay_or_reconcile.value: 3,
    InFlightTaskContinuityClass.authoritative_task_continuity_restored.value: 4,
}


# ---------------------------------------------------------------------------
# InFlightTaskContinuityEvidence
# ---------------------------------------------------------------------------


@dataclass
class InFlightTaskContinuityEvidence:
    """Structured input evidence for in-flight task continuity classification.

    Each dimension represents an independently-observed evidence signal.
    Absent or indeterminate signals MUST be left as ``0`` / ``False``
    (never assumed present).

    Counts should be sourced from a :class:`~core.inflight_task_continuity_contract
    .TaskContinuityReport` when one is available; see
    :func:`build_task_continuity_verdict_from_report` for the convenience
    wrapper.

    Attributes
    ----------
    total_evaluated
        Total number of task records evaluated in the recovery snapshot.
    resumed_count
        Tasks whose task_id was already present in the live lifecycle registry
        when recovery ran.  No interruption gap; execution continuity formally
        confirmed.  This is the ONLY count that contributes to
        ``authoritative_task_continuity_restored``.
    recoverable_count
        Tasks with state present and dispatch taken but continuity not yet
        confirmed (device must reconnect or routing must re-run).
        State present ≠ continuity restored.
    interrupted_count
        Tasks that cannot auto-resume (REISSUABLE disposition); require
        explicit re-issuance from the original source.
    abandoned_count
        Tasks in terminal state (TERMINAL_ON_INTERRUPT); result may already
        have been delivered.  No safe continuity restoration possible.
    needs_reconcile_count
        Tasks with snapshot integrity issues (duplicate task_id, stale record).
        Must be explicitly reconciled before any recovery action.
    ambiguous_count
        Tasks with insufficient information to classify (empty task_id,
        undetermined disposition).  MUST NOT be upgraded.
    result_or_history_visible
        Completed task results or task history are readable from the durable
        evidence store.  This covers completed-result ingestion, audit logs,
        and archived snapshots.  Per RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY,
        this alone does NOT support any class higher than
        ``history_or_evidence_only``.
    execution_context_rebuilt
        The runtime execution contexts (device bindings, routing contexts,
        tool contexts) required to resume recoverable tasks have been
        re-established.  This is a supporting signal; it does NOT alone
        promote a verdict to ``authoritative_task_continuity_restored``.
    process_death_observed
        A process death event (crash, SIGKILL, OOM, restart, process bounce)
        was observed.  When True, all previously established task execution
        bindings are considered interrupted per policy.
    partial_recovery_only
        Recovery was known to be only partial.  Per
        PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY,
        this prevents ``authoritative_task_continuity_restored`` even if
        other evidence would otherwise permit it.
    evaluated_context
        Optional free-form description of the recovery context for audit.
    """

    # Per-task status counts
    total_evaluated: int = 0
    resumed_count: int = 0
    recoverable_count: int = 0
    interrupted_count: int = 0
    abandoned_count: int = 0
    needs_reconcile_count: int = 0
    ambiguous_count: int = 0

    # Additional runtime evidence dimensions
    result_or_history_visible: bool = False
    execution_context_rebuilt: bool = False
    process_death_observed: bool = False
    partial_recovery_only: bool = False

    # Audit field
    evaluated_context: str = ""

    @property
    def state_restored_count(self) -> int:
        """Tasks with state present (resumed + recoverable).

        NOTE: State present ≠ continuity restored.
        """
        return self.resumed_count + self.recoverable_count

    @property
    def non_terminal_count(self) -> int:
        """Tasks that have some form of state or recovery potential."""
        return (
            self.resumed_count
            + self.recoverable_count
            + self.needs_reconcile_count
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "total_evaluated": self.total_evaluated,
            "resumed_count": self.resumed_count,
            "recoverable_count": self.recoverable_count,
            "interrupted_count": self.interrupted_count,
            "abandoned_count": self.abandoned_count,
            "needs_reconcile_count": self.needs_reconcile_count,
            "ambiguous_count": self.ambiguous_count,
            "state_restored_count": self.state_restored_count,
            "result_or_history_visible": self.result_or_history_visible,
            "execution_context_rebuilt": self.execution_context_rebuilt,
            "process_death_observed": self.process_death_observed,
            "partial_recovery_only": self.partial_recovery_only,
            "evaluated_context": self.evaluated_context,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InFlightTaskContinuityEvidence":
        """Reconstruct from a serialised dict."""
        return cls(
            total_evaluated=int(d.get("total_evaluated", 0)),
            resumed_count=int(d.get("resumed_count", 0)),
            recoverable_count=int(d.get("recoverable_count", 0)),
            interrupted_count=int(d.get("interrupted_count", 0)),
            abandoned_count=int(d.get("abandoned_count", 0)),
            needs_reconcile_count=int(d.get("needs_reconcile_count", 0)),
            ambiguous_count=int(d.get("ambiguous_count", 0)),
            result_or_history_visible=bool(d.get("result_or_history_visible", False)),
            execution_context_rebuilt=bool(d.get("execution_context_rebuilt", False)),
            process_death_observed=bool(d.get("process_death_observed", False)),
            partial_recovery_only=bool(d.get("partial_recovery_only", False)),
            evaluated_context=str(d.get("evaluated_context", "")),
        )


# ---------------------------------------------------------------------------
# InFlightTaskContinuityVerdict
# ---------------------------------------------------------------------------


@dataclass
class InFlightTaskContinuityVerdict:
    """Structured in-flight task continuity verdict.

    This is the canonical output of :class:`InFlightTaskContinuityTaxonomyContract`
    and :func:`build_task_continuity_verdict`.  It is designed to be consumed
    by recovery, readiness, acceptance, and governance pipelines.

    Attributes
    ----------
    verdict_id
        Unique identifier for this verdict instance.
    generated_at
        Unix timestamp of verdict generation.
    taxonomy_sentinel
        Copy of :data:`INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY`.
    continuity_class
        The formal :class:`InFlightTaskContinuityClass` verdict.
    reason
        Human-readable explanation of the verdict and classification rule
        that applied.
    downgrade_reason
        If the verdict was downgraded from a higher class, this explains why.
        Empty string when no downgrade occurred.
    evidence
        The :class:`InFlightTaskContinuityEvidence` input that produced this
        verdict.  Included for auditability.
    is_authoritative
        Convenience flag: True only for
        ``authoritative_task_continuity_restored``.
    requires_replay_or_reconcile
        True when the verdict is ``resumable_with_replay_or_reconcile``.
    state_present_not_resumed
        True when the verdict is ``state_restored_not_resumed``.
    history_only
        True when the verdict is ``history_or_evidence_only``.
    continuity_lost
        True when the verdict is ``task_continuity_lost``.
    """

    verdict_id: str = field(default_factory=lambda: f"tctv_{uuid.uuid4().hex[:12]}")
    generated_at: float = field(default_factory=time.time)
    taxonomy_sentinel: str = INFLIGHT_TASK_CONTINUITY_TAXONOMY_IS_AUTHORITY
    continuity_class: InFlightTaskContinuityClass = (
        InFlightTaskContinuityClass.task_continuity_lost
    )
    reason: str = ""
    downgrade_reason: str = ""
    evidence: InFlightTaskContinuityEvidence = field(
        default_factory=InFlightTaskContinuityEvidence
    )

    @property
    def is_authoritative(self) -> bool:
        """True only for ``authoritative_task_continuity_restored``."""
        return self.continuity_class.is_authoritative

    @property
    def requires_replay_or_reconcile(self) -> bool:
        """True when replay, reconcile, or device reconnect is still needed."""
        return self.continuity_class.requires_replay_or_reconcile

    @property
    def state_present_not_resumed(self) -> bool:
        """True when state is visible but execution has not resumed."""
        return self.continuity_class.is_state_only

    @property
    def history_only(self) -> bool:
        """True when only historical evidence is available."""
        return self.continuity_class.is_evidence_only

    @property
    def continuity_lost(self) -> bool:
        """True when task continuity is definitively lost."""
        return self.continuity_class.is_lost

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "verdict_id": self.verdict_id,
            "generated_at": self.generated_at,
            "taxonomy_sentinel": self.taxonomy_sentinel,
            "continuity_class": self.continuity_class.value,
            "reason": self.reason,
            "downgrade_reason": self.downgrade_reason,
            "evidence": self.evidence.to_dict(),
            "is_authoritative": self.is_authoritative,
            "requires_replay_or_reconcile": self.requires_replay_or_reconcile,
            "state_present_not_resumed": self.state_present_not_resumed,
            "history_only": self.history_only,
            "continuity_lost": self.continuity_lost,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InFlightTaskContinuityVerdict":
        """Reconstruct from a serialised dict."""
        raw_class = d.get("continuity_class", "task_continuity_lost")
        try:
            cont_class = InFlightTaskContinuityClass(raw_class)
        except ValueError:
            cont_class = InFlightTaskContinuityClass.task_continuity_lost
        evidence_raw = d.get("evidence", {})
        evidence = (
            InFlightTaskContinuityEvidence.from_dict(evidence_raw)
            if isinstance(evidence_raw, dict)
            else InFlightTaskContinuityEvidence()
        )
        return cls(
            verdict_id=str(d.get("verdict_id", "")),
            generated_at=float(d.get("generated_at", 0.0)),
            taxonomy_sentinel=str(d.get("taxonomy_sentinel", "")),
            continuity_class=cont_class,
            reason=str(d.get("reason", "")),
            downgrade_reason=str(d.get("downgrade_reason", "")),
            evidence=evidence,
        )


# ---------------------------------------------------------------------------
# InFlightTaskContinuityTaxonomyContract
# ---------------------------------------------------------------------------


class InFlightTaskContinuityTaxonomyContract:
    """Evaluates system-level in-flight task continuity class after recovery.

    Converts an :class:`InFlightTaskContinuityEvidence` object into a formal
    :class:`InFlightTaskContinuityVerdict` using strict downgrade semantics.

    Classification rules (applied in strict descending priority)
    ------------------------------------------------------------
    1. **authoritative_task_continuity_restored** — requires ALL of:
       total_evaluated > 0, resumed_count == total_evaluated (ALL tasks were
       already in the live registry at recovery time), all other counts == 0,
       AND NOT partial_recovery_only.  process_death_observed is tolerated
       only if execution_context_rebuilt is also True.

    2. **resumable_with_replay_or_reconcile** — requires:
       recoverable_count > 0.  At least one task has state present and a
       dispatch path was taken; device reconnect or routing re-run will
       complete recovery.  May be capped if partial_recovery_only is True.

    3. **state_restored_not_resumed** — requires:
       non_terminal_count > 0 (state/snapshot visible) AND
       recoverable_count == 0 (no active replay path).  Applies when:
       only needs_reconcile tasks exist, or a mix of resumed + non-recoverable
       tasks is present without any recoverable path.

    4. **history_or_evidence_only** — requires:
       result_or_history_visible == True AND state_restored_count == 0 AND
       needs_reconcile_count == 0 (no live state in registry).

    5. **task_continuity_lost** — catch-all for everything else:
       empty snapshot (total_evaluated == 0) with no history, all tasks
       terminal/ambiguous, or no positive evidence at all.
    """

    def evaluate(
        self,
        evidence: InFlightTaskContinuityEvidence,
    ) -> InFlightTaskContinuityVerdict:
        """Evaluate the system-level task continuity class.

        Parameters
        ----------
        evidence
            :class:`InFlightTaskContinuityEvidence` populated from a
            :class:`~core.inflight_task_continuity_contract.TaskContinuityReport`
            and any additional runtime signals.

        Returns
        -------
        InFlightTaskContinuityVerdict
            Formal verdict with classification, reason, and downgrade notes.
        """
        verdict = InFlightTaskContinuityVerdict(evidence=evidence)

        # ------------------------------------------------------------------
        # Rule 1: authoritative_task_continuity_restored
        #
        # Conditions (ALL must hold):
        #   (a) at least one task evaluated
        #   (b) every evaluated task is resumed (no interruption gap for any)
        #   (c) no recoverable/interrupted/abandoned/needs_reconcile/ambiguous
        #   (d) not partial_recovery_only
        #   (e) process_death_observed implies execution_context_rebuilt
        #
        # Enforcement of SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY:
        #   Having tasks in the snapshot does NOT satisfy this rule; tasks must
        #   have been in the live registry BEFORE recovery ran (resumed status).
        # ------------------------------------------------------------------
        if (
            evidence.total_evaluated > 0
            and evidence.resumed_count == evidence.total_evaluated
            and evidence.recoverable_count == 0
            and evidence.interrupted_count == 0
            and evidence.abandoned_count == 0
            and evidence.needs_reconcile_count == 0
            and evidence.ambiguous_count == 0
            and not evidence.partial_recovery_only
            and (not evidence.process_death_observed or evidence.execution_context_rebuilt)
        ):
            verdict.continuity_class = (
                InFlightTaskContinuityClass.authoritative_task_continuity_restored
            )
            verdict.reason = (
                f"All {evidence.total_evaluated} evaluated task(s) were already "
                "present in the live lifecycle registry when recovery ran — no "
                "interruption gap exists for any task.  Execution continuity is "
                "formally confirmed for all in-flight tasks.  "
                "See SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY."
            )
            verdict.downgrade_reason = ""
            logger.info(
                "InFlightTaskContinuityTaxonomyContract: class=%s resumed=%d total=%d",
                verdict.continuity_class.value,
                evidence.resumed_count,
                evidence.total_evaluated,
            )
            return verdict

        # Collect downgrade reasons to explain why Rule 1 did not apply
        downgrade_parts: List[str] = []
        if evidence.partial_recovery_only:
            downgrade_parts.append(
                "partial_recovery_only=True prevents authoritative continuity "
                "(PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY)"
            )
        if evidence.process_death_observed and not evidence.execution_context_rebuilt:
            downgrade_parts.append(
                "process_death_observed=True with execution_context_rebuilt=False "
                "— execution bindings are considered interrupted"
            )
        if evidence.total_evaluated == 0:
            downgrade_parts.append("total_evaluated=0 — no tasks in snapshot")
        elif evidence.resumed_count < evidence.total_evaluated:
            downgrade_parts.append(
                f"resumed_count={evidence.resumed_count} < "
                f"total_evaluated={evidence.total_evaluated} — "
                "not all tasks had uninterrupted execution"
            )
        if evidence.recoverable_count > 0:
            downgrade_parts.append(
                f"recoverable_count={evidence.recoverable_count} — "
                "replay/reconnect still needed for some tasks"
            )
        if evidence.interrupted_count > 0:
            downgrade_parts.append(
                f"interrupted_count={evidence.interrupted_count} — "
                "some tasks require re-issuance"
            )
        if evidence.abandoned_count > 0:
            downgrade_parts.append(
                f"abandoned_count={evidence.abandoned_count} — "
                "some tasks are terminal"
            )
        if evidence.needs_reconcile_count > 0:
            downgrade_parts.append(
                f"needs_reconcile_count={evidence.needs_reconcile_count} — "
                "some tasks have snapshot integrity issues"
            )
        if evidence.ambiguous_count > 0:
            downgrade_parts.append(
                f"ambiguous_count={evidence.ambiguous_count} — "
                "some tasks have insufficient information"
            )

        # ------------------------------------------------------------------
        # Rule 2: resumable_with_replay_or_reconcile
        #
        # Condition: recoverable_count > 0
        #   At least one task has state present and dispatch was taken; only
        #   device reconnect or routing re-run is pending to complete recovery.
        #   Per REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY, replay completion
        #   alone does not upgrade to authoritative; and per
        #   PARTIAL_RECOVERY_MUST_NOT_CLAIM_AUTHORITATIVE_CONTINUITY_POLICY,
        #   partial_recovery_only does not further downgrade this class.
        # ------------------------------------------------------------------
        if evidence.recoverable_count > 0:
            verdict.continuity_class = (
                InFlightTaskContinuityClass.resumable_with_replay_or_reconcile
            )
            verdict.reason = (
                f"{evidence.recoverable_count} task(s) have state present in "
                "the live registry with dispatch confirmed, but execution "
                "continuity is not yet established.  For RESUMABLE tasks: "
                "device must reconnect.  For REPLAY_ONLY tasks: routing must "
                "re-run.  State restored ≠ continuity restored.  "
                "See REPLAY_COMPLETION_IS_NOT_CONTINUITY_POLICY."
            )
            verdict.downgrade_reason = "; ".join(downgrade_parts) if downgrade_parts else ""
            logger.info(
                "InFlightTaskContinuityTaxonomyContract: class=%s recoverable=%d",
                verdict.continuity_class.value,
                evidence.recoverable_count,
            )
            return verdict

        # ------------------------------------------------------------------
        # Rule 3: state_restored_not_resumed
        #
        # Condition: non_terminal_count > 0 AND recoverable_count == 0
        #   State is visible (some tasks in registry/snapshot) but no active
        #   replay/reconnect path is confirmed.  Covers:
        #   - Only needs_reconcile tasks (state visible, reconcile pending)
        #   - Mix of resumed + non-recoverable without any recoverable path
        #   Per RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY, reconcile
        #   initiation alone does not elevate to resumable_with_replay_or_reconcile.
        # ------------------------------------------------------------------
        if evidence.non_terminal_count > 0:
            verdict.continuity_class = (
                InFlightTaskContinuityClass.state_restored_not_resumed
            )
            verdict.reason = (
                "Task state is present in the registry or snapshot but execution "
                "continuity has not been confirmed and no active replay/reconnect "
                "path is established.  "
                f"resumed={evidence.resumed_count}, "
                f"needs_reconcile={evidence.needs_reconcile_count}.  "
                "Execution contexts have not been rebuilt.  "
                "See RECONCILE_TRIGGERED_IS_NOT_CONTINUITY_POLICY and "
                "SNAPSHOT_PRESENCE_IS_NOT_AUTHORITATIVE_CONTINUITY_POLICY."
            )
            verdict.downgrade_reason = "; ".join(downgrade_parts) if downgrade_parts else ""
            logger.info(
                "InFlightTaskContinuityTaxonomyContract: class=%s non_terminal=%d",
                verdict.continuity_class.value,
                evidence.non_terminal_count,
            )
            return verdict

        # ------------------------------------------------------------------
        # Rule 4: history_or_evidence_only
        #
        # Condition: result_or_history_visible == True AND no live state
        #   Completed results or historical records are accessible in the
        #   durable evidence store, but there is no live task state in the
        #   registry.  Per RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY, this
        #   evidence alone does NOT support any class higher than
        #   history_or_evidence_only.
        # ------------------------------------------------------------------
        if evidence.result_or_history_visible:
            verdict.continuity_class = (
                InFlightTaskContinuityClass.history_or_evidence_only
            )
            verdict.reason = (
                "No live task state is present in the registry, but completed "
                "task results or historical records are visible in the durable "
                "evidence store.  Execution continuity cannot be established from "
                "historical evidence alone.  "
                "See RESULT_INGESTION_IS_NOT_CONTINUITY_POLICY and "
                "EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY."
            )
            verdict.downgrade_reason = "; ".join(downgrade_parts) if downgrade_parts else ""
            logger.info(
                "InFlightTaskContinuityTaxonomyContract: class=%s history_visible=True",
                verdict.continuity_class.value,
            )
            return verdict

        # ------------------------------------------------------------------
        # Rule 5: task_continuity_lost (catch-all)
        #
        # Reaches here when:
        #   - total_evaluated == 0 AND no history visible
        #   - All tasks are terminal (abandoned, interrupted) with no history
        #   - All evidence is absent / indeterminate
        # Per EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY.
        # ------------------------------------------------------------------
        verdict.continuity_class = InFlightTaskContinuityClass.task_continuity_lost
        verdict.reason = (
            "No in-flight task continuity can be established.  "
            f"total_evaluated={evidence.total_evaluated}, "
            f"interrupted={evidence.interrupted_count}, "
            f"abandoned={evidence.abandoned_count}, "
            f"ambiguous={evidence.ambiguous_count}, "
            f"result_or_history_visible={evidence.result_or_history_visible}.  "
            "See EVIDENCE_ABSENT_DEFAULTS_TO_CONTINUITY_LOST_POLICY."
        )
        verdict.downgrade_reason = "; ".join(downgrade_parts) if downgrade_parts else ""
        logger.info(
            "InFlightTaskContinuityTaxonomyContract: class=%s total=%d",
            verdict.continuity_class.value,
            evidence.total_evaluated,
        )
        return verdict


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------


def build_task_continuity_verdict(
    evidence: InFlightTaskContinuityEvidence,
) -> InFlightTaskContinuityVerdict:
    """Build an :class:`InFlightTaskContinuityVerdict` from evidence.

    Convenience wrapper around :class:`InFlightTaskContinuityTaxonomyContract`.

    Parameters
    ----------
    evidence
        :class:`InFlightTaskContinuityEvidence` populated from recovery signals.

    Returns
    -------
    InFlightTaskContinuityVerdict
        Formal verdict with classification and downgrade reasoning.
    """
    return InFlightTaskContinuityTaxonomyContract().evaluate(evidence)


def build_task_continuity_verdict_from_report(
    report: Any,
    *,
    result_or_history_visible: bool = False,
    execution_context_rebuilt: bool = False,
    process_death_observed: bool = False,
    partial_recovery_only: bool = False,
) -> InFlightTaskContinuityVerdict:
    """Build a verdict directly from a :class:`~core.inflight_task_continuity_contract
    .TaskContinuityReport`.

    Extracts per-task status counts from the report and combines them with
    the provided additional evidence signals to produce a verdict.

    Parameters
    ----------
    report
        A :class:`~core.inflight_task_continuity_contract.TaskContinuityReport`
        instance (or any object exposing the same numeric count attributes).
    result_or_history_visible
        True when completed results or task history are visible in the durable
        evidence store.
    execution_context_rebuilt
        True when the runtime execution contexts required to resume recoverable
        tasks have been re-established.
    process_death_observed
        True when a process death / crash / restart was observed.
    partial_recovery_only
        True when recovery was known to be only partial.

    Returns
    -------
    InFlightTaskContinuityVerdict
    """
    evidence = InFlightTaskContinuityEvidence(
        total_evaluated=int(getattr(report, "total_evaluated", 0)),
        resumed_count=int(getattr(report, "resumed_count", 0)),
        recoverable_count=int(getattr(report, "recoverable_count", 0)),
        interrupted_count=int(getattr(report, "interrupted_count", 0)),
        abandoned_count=int(getattr(report, "abandoned_count", 0)),
        needs_reconcile_count=int(getattr(report, "needs_reconcile_count", 0)),
        ambiguous_count=int(getattr(report, "ambiguous_count", 0)),
        result_or_history_visible=result_or_history_visible,
        execution_context_rebuilt=execution_context_rebuilt,
        process_death_observed=process_death_observed,
        partial_recovery_only=partial_recovery_only,
    )
    return build_task_continuity_verdict(evidence)
