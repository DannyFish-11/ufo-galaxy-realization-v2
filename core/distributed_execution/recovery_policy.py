#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.distributed_execution.recovery_policy
============================================

PR-14 (V4) — Distributed Task Merge & Recovery

Defines :class:`RecoveryPosture` — the stable, serialisable enum that
classifies which recovery action should be recommended when a distributed
or multi-device task experiences failures, timeouts, or degradation.

Also provides :func:`recommend_recovery` which derives a
:class:`RecoveryPosture` from a :class:`~.merge_status.MergeStatus` and
optional context hints.

Recovery Posture Semantics
---------------------------
+-----------------------------+--------------------------------------------------+
| Posture                     | Meaning                                          |
+=============================+==================================================+
| ``no_recovery_needed``      | No action required; task fully succeeded.        |
+-----------------------------+--------------------------------------------------+
| ``retry_same_device``       | Re-attempt on the same device / executor.        |
|                             | Appropriate for transient errors.                |
+-----------------------------+--------------------------------------------------+
| ``reroute_device``          | Redirect to a different device or execution      |
|                             | path.  Appropriate when the original device is   |
|                             | unavailable or unsuitable.                       |
+-----------------------------+--------------------------------------------------+
| ``skip_optional_branch``    | Skip the failed branch entirely; it is not       |
|                             | required for overall task success.               |
+-----------------------------+--------------------------------------------------+
| ``require_confirmation``    | Pause and request human or orchestrator          |
|                             | confirmation before proceeding.  Appropriate     |
|                             | for ambiguous or high-risk situations.           |
+-----------------------------+--------------------------------------------------+
| ``abort_task``              | Cancel the entire task; no automatic recovery    |
|                             | is possible or safe.                             |
+-----------------------------+--------------------------------------------------+
"""

from __future__ import annotations

import dataclasses
from enum import Enum
from typing import Any, Dict, Optional

from .merge_status import MergeStatus, is_terminal_failure

__all__ = [
    "RecoveryPosture",
    "POSTURE_DESCRIPTIONS",
    "RecoveryRecommendation",
    "recommend_recovery",
]


# ---------------------------------------------------------------------------
# Recovery posture enum
# ---------------------------------------------------------------------------


class RecoveryPosture(str, Enum):
    """Stable, serialisable recovery action classification.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    NO_RECOVERY_NEEDED = "no_recovery_needed"
    """Task fully succeeded; no recovery action required."""

    RETRY_SAME_DEVICE = "retry_same_device"
    """Re-attempt on the same device/executor (transient error)."""

    REROUTE_DEVICE = "reroute_device"
    """Redirect to a different device or execution path."""

    SKIP_OPTIONAL_BRANCH = "skip_optional_branch"
    """Skip the failed branch; it is not required for overall success."""

    REQUIRE_CONFIRMATION = "require_confirmation"
    """Pause and request confirmation before proceeding."""

    ABORT_TASK = "abort_task"
    """Cancel the entire task; no safe automatic recovery path."""


# ---------------------------------------------------------------------------
# Descriptions
# ---------------------------------------------------------------------------

POSTURE_DESCRIPTIONS: Dict[str, str] = {
    RecoveryPosture.NO_RECOVERY_NEEDED.value: (
        "Task completed successfully.  No recovery action is required."
    ),
    RecoveryPosture.RETRY_SAME_DEVICE.value: (
        "Re-attempt execution on the same device or executor.  Suitable for "
        "transient failures such as network blips, temporary resource "
        "exhaustion, or intermittent tool errors."
    ),
    RecoveryPosture.REROUTE_DEVICE.value: (
        "Redirect the task to a different device or execution path.  "
        "Appropriate when the original device is unavailable, lacks required "
        "capability, or has failed persistently."
    ),
    RecoveryPosture.SKIP_OPTIONAL_BRANCH.value: (
        "Skip the failed branch entirely.  The branch is optional and its "
        "absence does not prevent the overall task from succeeding."
    ),
    RecoveryPosture.REQUIRE_CONFIRMATION.value: (
        "Pause execution and request explicit confirmation from a human or "
        "orchestrator supervisor before taking any further action.  "
        "Appropriate for ambiguous, high-risk, or partially-conflicting "
        "results."
    ),
    RecoveryPosture.ABORT_TASK.value: (
        "Cancel the entire task immediately.  No automatic recovery path is "
        "safe or viable.  The task must be resubmitted or manually handled."
    ),
}


# ---------------------------------------------------------------------------
# Recovery recommendation dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RecoveryRecommendation:
    """Immutable, serialisable recovery recommendation.

    Produced by :func:`recommend_recovery`.

    Attributes
    ----------
    posture
        The recommended :class:`RecoveryPosture`.
    reason
        Human-readable explanation for the recommendation.
    merge_status_trigger
        The :class:`~.merge_status.MergeStatus` that triggered this
        recommendation.
    failed_count
        Number of failed branches/devices that contributed to this decision.
    timed_out_count
        Number of timed-out branches/devices.
    is_optional_branch_available
        Whether there is an optional branch that can be safely skipped.
    task_id
        Optional task identifier for traceability.
    trace_id
        Optional trace identifier for traceability.
    """

    posture: RecoveryPosture
    reason: str
    merge_status_trigger: MergeStatus
    failed_count: int = 0
    timed_out_count: int = 0
    is_optional_branch_available: bool = False
    task_id: str = ""
    trace_id: str = ""

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serialisable dict."""
        return {
            "posture": self.posture.value,
            "reason": self.reason,
            "merge_status_trigger": self.merge_status_trigger.value,
            "failed_count": self.failed_count,
            "timed_out_count": self.timed_out_count,
            "is_optional_branch_available": self.is_optional_branch_available,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecoveryRecommendation":
        """Reconstruct from a plain dict (e.g. deserialised from JSON)."""
        return cls(
            posture=RecoveryPosture(data.get("posture", RecoveryPosture.ABORT_TASK.value)),
            reason=data.get("reason", ""),
            merge_status_trigger=MergeStatus(
                data.get("merge_status_trigger", MergeStatus.FAILED.value)
            ),
            failed_count=int(data.get("failed_count", 0)),
            timed_out_count=int(data.get("timed_out_count", 0)),
            is_optional_branch_available=bool(data.get("is_optional_branch_available", False)),
            task_id=data.get("task_id", ""),
            trace_id=data.get("trace_id", ""),
        )

    def __repr__(self) -> str:
        return (
            f"<RecoveryRecommendation "
            f"posture={self.posture.value} "
            f"trigger={self.merge_status_trigger.value} "
            f"failed={self.failed_count} "
            f"timed_out={self.timed_out_count}>"
        )


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------

def recommend_recovery(
    merge_status: MergeStatus,
    *,
    failed_count: int = 0,
    timed_out_count: int = 0,
    total_count: int = 0,
    is_optional_branch_available: bool = False,
    retry_attempted: bool = False,
    reroute_available: bool = False,
    requires_confirmation: bool = False,
    task_id: str = "",
    trace_id: str = "",
) -> RecoveryRecommendation:
    """Derive a :class:`RecoveryRecommendation` from merge outcome and context.

    All keyword arguments are optional and degrade gracefully when absent.

    Resolution logic (in precedence order)
    ----------------------------------------
    1. ``success`` → ``no_recovery_needed``
    2. ``partial_success`` with optional branch available → ``skip_optional_branch``
    3. ``degraded_success`` → ``no_recovery_needed`` (already degraded successfully)
    4. ``requires_confirmation`` hint → ``require_confirmation``
    5. ``timed_out`` with reroute available → ``reroute_device``
    6. ``timed_out`` without reroute → ``retry_same_device``
    7. ``failed`` + retry not yet attempted → ``retry_same_device``
    8. ``failed`` + retry attempted + reroute available → ``reroute_device``
    9. ``failed`` + optional branch available → ``skip_optional_branch``
    10. ``failed`` all recovery options exhausted → ``abort_task``

    Args:
        merge_status:               Overall merge outcome.
        failed_count:               Number of failed branches/subtasks.
        timed_out_count:            Number of timed-out branches/subtasks.
        total_count:                Total branches/subtasks in the merge.
        is_optional_branch_available: Whether a failed branch was optional.
        retry_attempted:            Whether a retry has already been attempted.
        reroute_available:          Whether an alternative device/path exists.
        requires_confirmation:      External hint that confirmation is required.
        task_id:                    Traceability field.
        trace_id:                   Traceability field.

    Returns:
        A :class:`RecoveryRecommendation`.
    """
    # 1. Clean success
    if merge_status == MergeStatus.SUCCESS:
        return RecoveryRecommendation(
            posture=RecoveryPosture.NO_RECOVERY_NEEDED,
            reason="All branches succeeded; no recovery action required.",
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # 2. Degraded success — nominally acceptable
    if merge_status == MergeStatus.DEGRADED_SUCCESS:
        return RecoveryRecommendation(
            posture=RecoveryPosture.NO_RECOVERY_NEEDED,
            reason=(
                "Task completed with degraded fidelity.  "
                "Result is usable; no recovery action required."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # 3. Partial success with optional branch available
    if merge_status == MergeStatus.PARTIAL_SUCCESS and is_optional_branch_available:
        return RecoveryRecommendation(
            posture=RecoveryPosture.SKIP_OPTIONAL_BRANCH,
            reason=(
                "Core intent achieved; failed branch is optional and can be "
                "skipped without loss of overall goal."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # 4. Partial success without optional-branch shortcut
    if merge_status == MergeStatus.PARTIAL_SUCCESS:
        if requires_confirmation:
            return RecoveryRecommendation(
                posture=RecoveryPosture.REQUIRE_CONFIRMATION,
                reason=(
                    "Partial execution completed; confirmation required before "
                    "deciding how to handle remaining branches."
                ),
                merge_status_trigger=merge_status,
                failed_count=failed_count,
                timed_out_count=timed_out_count,
                is_optional_branch_available=is_optional_branch_available,
                task_id=task_id,
                trace_id=trace_id,
            )
        if reroute_available and retry_attempted:
            return RecoveryRecommendation(
                posture=RecoveryPosture.REROUTE_DEVICE,
                reason=(
                    "Partial success after retry; routing to an alternative "
                    "device or path for remaining work."
                ),
                merge_status_trigger=merge_status,
                failed_count=failed_count,
                timed_out_count=timed_out_count,
                is_optional_branch_available=is_optional_branch_available,
                task_id=task_id,
                trace_id=trace_id,
            )
        return RecoveryRecommendation(
            posture=RecoveryPosture.RETRY_SAME_DEVICE,
            reason=(
                "Partial success; retrying on same device for failed branches."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # 5. Confirmation hint overrides granular logic for terminal states
    if requires_confirmation:
        return RecoveryRecommendation(
            posture=RecoveryPosture.REQUIRE_CONFIRMATION,
            reason=(
                "Confirmation required before automatic recovery proceeds "
                f"(merge status: {merge_status.value})."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # --- From here: timed_out or failed ---

    if merge_status == MergeStatus.TIMED_OUT:
        if reroute_available:
            return RecoveryRecommendation(
                posture=RecoveryPosture.REROUTE_DEVICE,
                reason=(
                    "Execution timed out; rerouting to an available alternative "
                    "device or path."
                ),
                merge_status_trigger=merge_status,
                failed_count=failed_count,
                timed_out_count=timed_out_count,
                is_optional_branch_available=is_optional_branch_available,
                task_id=task_id,
                trace_id=trace_id,
            )
        return RecoveryRecommendation(
            posture=RecoveryPosture.RETRY_SAME_DEVICE,
            reason=(
                "Execution timed out; retrying on same device (no alternative "
                "route available)."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    # merge_status == MergeStatus.FAILED
    if not retry_attempted:
        return RecoveryRecommendation(
            posture=RecoveryPosture.RETRY_SAME_DEVICE,
            reason="Task failed; initial retry on same device recommended.",
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    if reroute_available:
        return RecoveryRecommendation(
            posture=RecoveryPosture.REROUTE_DEVICE,
            reason=(
                "Task failed after retry; rerouting to an alternative device "
                "or execution path."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    if is_optional_branch_available:
        return RecoveryRecommendation(
            posture=RecoveryPosture.SKIP_OPTIONAL_BRANCH,
            reason=(
                "Task failed after retry; failed branch is optional and can "
                "be skipped."
            ),
            merge_status_trigger=merge_status,
            failed_count=failed_count,
            timed_out_count=timed_out_count,
            is_optional_branch_available=is_optional_branch_available,
            task_id=task_id,
            trace_id=trace_id,
        )

    return RecoveryRecommendation(
        posture=RecoveryPosture.ABORT_TASK,
        reason=(
            "Task failed after retry; no reroute or optional-branch skip "
            "available.  Aborting task."
        ),
        merge_status_trigger=merge_status,
        failed_count=failed_count,
        timed_out_count=timed_out_count,
        is_optional_branch_available=is_optional_branch_available,
        task_id=task_id,
        trace_id=trace_id,
    )
