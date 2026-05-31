#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.distributed_execution.merge_summary
==========================================

PR-14 (V4) — Distributed Task Merge & Recovery

Defines :class:`MergeSummary` — the stable, serialisable public summary of a
multi-device / DAG / parallel execution merge result.

This is the **canonical read surface** for downstream projection consumers
(Status Board V2, Manifest Stage, Liminal layer, read-only API endpoints,
observability surfaces).

Design rules
------------
- All fields are ``None``-safe and carry stable defaults so that
  ``MergeSummary()`` (no args) represents a failed empty merge.
- ``to_dict()`` produces a stable, JSON-serialisable dict (no enum objects).
- ``from_dict()`` reconstructs from a plain dict (e.g. deserialised JSON).
- The summary carries both a :class:`~.merge_status.MergeStatus` and an
  optional :class:`~.recovery_policy.RecoveryRecommendation` that can be
  populated by callers after merging.

Projection adapter
------------------
:func:`attach_merge_summary_to_projection` adds the summary to an existing
``RuntimeProjection`` dict additively (read-only from the projection's
perspective).

:func:`get_merge_hints` extracts a compact boolean/scalar hint dict suitable
for quick downstream checks.
"""

from __future__ import annotations

import dataclasses
import time
from typing import Any, Dict, List, Optional

from .merge_status import MergeStatus, is_successful_outcome, is_terminal_failure
from .recovery_policy import RecoveryRecommendation

__all__ = [
    "MergeSummary",
    "EMPTY_MERGE_SUMMARY",
    "attach_merge_summary_to_projection",
    "get_merge_hints",
]


# ---------------------------------------------------------------------------
# MergeSummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class MergeSummary:
    """Stable, public-facing summary of a distributed execution merge result.

    Produced by the helpers in :mod:`~.result_merge`.

    Attributes
    ----------
    merge_status
        Overall :class:`~.merge_status.MergeStatus` of the merged execution.
    total_count
        Total number of branches/subtasks/devices in the merge.
    successful_count
        Number of branches that completed successfully.
    failed_count
        Number of branches that failed (non-timeout).
    timed_out_count
        Number of branches that timed out.
    skipped_count
        Number of branches that were skipped (optional / cancelled).
    merged_payloads
        List of per-branch result payload dicts (trimmed for serialisation).
    errors
        List of human-readable error strings from failed branches.
    warnings
        List of human-readable warning strings (e.g. skipped / degraded).
    recovery_recommendation
        Optional :class:`~.recovery_policy.RecoveryRecommendation` attached
        after merging.  ``None`` when no recovery analysis has been run.
    task_id
        Task identifier propagated from input signals.
    trace_id
        Trace identifier propagated from input signals.
    runtime_session_id
        Runtime session identifier propagated from input signals.
    merged_at
        Unix timestamp when the summary was created.
    """

    merge_status: MergeStatus = MergeStatus.FAILED
    total_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    timed_out_count: int = 0
    skipped_count: int = 0
    merged_payloads: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    errors: List[str] = dataclasses.field(default_factory=list)
    warnings: List[str] = dataclasses.field(default_factory=list)
    recovery_recommendation: Optional[RecoveryRecommendation] = None
    task_id: str = ""
    trace_id: str = ""
    runtime_session_id: str = ""
    merged_at: float = dataclasses.field(default_factory=time.time)

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def is_successful(self) -> bool:
        """True if the merge status represents any form of success."""
        return is_successful_outcome(self.merge_status)

    @property
    def is_terminal_failure(self) -> bool:
        """True if the merge status is a non-recoverable failure or timeout."""
        return is_terminal_failure(self.merge_status)

    @property
    def success_rate(self) -> float:
        """Fraction of branches that succeeded (0.0–1.0).

        Returns ``0.0`` when ``total_count`` is 0.
        """
        if self.total_count == 0:
            return 0.0
        return self.successful_count / self.total_count

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain, JSON-serialisable dict.

        Enum values are converted to their string ``.value``.
        Recovery recommendation is inlined if present.
        """
        result: Dict[str, Any] = {
            "merge_status": self.merge_status.value,
            "total_count": self.total_count,
            "successful_count": self.successful_count,
            "failed_count": self.failed_count,
            "timed_out_count": self.timed_out_count,
            "skipped_count": self.skipped_count,
            "success_rate": round(self.success_rate, 4),
            "is_successful": self.is_successful,
            "is_terminal_failure": self.is_terminal_failure,
            "merged_payloads": list(self.merged_payloads),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "recovery_recommendation": (
                self.recovery_recommendation.to_dict()
                if self.recovery_recommendation is not None
                else None
            ),
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "merged_at": self.merged_at,
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MergeSummary":
        """Reconstruct from a plain dict (e.g. deserialised from JSON).

        Degrades gracefully when fields are absent.
        """
        rec_data = data.get("recovery_recommendation")
        recovery_recommendation: Optional[RecoveryRecommendation] = None
        if isinstance(rec_data, dict):
            try:
                recovery_recommendation = RecoveryRecommendation.from_dict(rec_data)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

        return cls(
            merge_status=MergeStatus(
                data.get("merge_status", MergeStatus.FAILED.value)
            ),
            total_count=int(data.get("total_count", 0)),
            successful_count=int(data.get("successful_count", 0)),
            failed_count=int(data.get("failed_count", 0)),
            timed_out_count=int(data.get("timed_out_count", 0)),
            skipped_count=int(data.get("skipped_count", 0)),
            merged_payloads=list(data.get("merged_payloads") or []),
            errors=list(data.get("errors") or []),
            warnings=list(data.get("warnings") or []),
            recovery_recommendation=recovery_recommendation,
            task_id=str(data.get("task_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            runtime_session_id=str(data.get("runtime_session_id") or ""),
            merged_at=float(data.get("merged_at") or time.time()),
        )

    def __repr__(self) -> str:
        return (
            f"<MergeSummary "
            f"status={self.merge_status.value} "
            f"total={self.total_count} "
            f"ok={self.successful_count} "
            f"failed={self.failed_count} "
            f"timeout={self.timed_out_count} "
            f"trace={self.trace_id!r}>"
        )


# ---------------------------------------------------------------------------
# Pre-built idle / empty summary
# ---------------------------------------------------------------------------

EMPTY_MERGE_SUMMARY: MergeSummary = MergeSummary(
    merge_status=MergeStatus.FAILED,
    total_count=0,
    successful_count=0,
    failed_count=0,
    timed_out_count=0,
    skipped_count=0,
    merged_payloads=[],
    errors=["No merge has been performed."],
    warnings=[],
    recovery_recommendation=None,
    task_id="",
    trace_id="",
    runtime_session_id="",
)
"""Pre-built :class:`MergeSummary` representing an empty/uninitialised merge.

Use as a safe default / fallback when no merge has been run.
"""


# ---------------------------------------------------------------------------
# Projection adapter
# ---------------------------------------------------------------------------


def attach_merge_summary_to_projection(
    projection_dict: Dict[str, Any],
    summary: MergeSummary,
) -> Dict[str, Any]:
    """Attach a :class:`MergeSummary` to a ``RuntimeProjection`` dict additively.

    The summary is inserted under the key ``"merge_summary"`` alongside any
    existing projection fields.  The original dict is **not** mutated.

    Args:
        projection_dict:  Existing projection dict (e.g. from
                          ``RuntimeProjection.to_dict()``).
        summary:          The :class:`MergeSummary` to attach.

    Returns:
        A new dict with ``"merge_summary"`` added.
    """
    if not isinstance(projection_dict, dict):
        projection_dict = {}
    return {
        **projection_dict,
        "merge_summary": summary.to_dict(),
    }


def get_merge_hints(summary: MergeSummary) -> Dict[str, Any]:
    """Extract a compact hint dict from a :class:`MergeSummary`.

    Suitable for quick downstream boolean/scalar checks without needing to
    inspect the full summary.

    Args:
        summary: A :class:`MergeSummary` instance.

    Returns:
        A plain dict with the following keys:

        ``merge_status``
            String value of :attr:`MergeSummary.merge_status`.
        ``is_successful``
            True if any success variant.
        ``is_terminal_failure``
            True if failed or timed out.
        ``has_errors``
            True if :attr:`MergeSummary.errors` is non-empty.
        ``has_warnings``
            True if :attr:`MergeSummary.warnings` is non-empty.
        ``success_rate``
            Float fraction of successful branches.
        ``has_recovery_recommendation``
            True if a recovery recommendation is attached.
        ``recovery_posture``
            String posture value if recommendation present, else ``None``.
        ``total_count``
            Total branch count.
        ``task_id``
            Task identifier.
        ``trace_id``
            Trace identifier.
    """
    rec = summary.recovery_recommendation
    return {
        "merge_status": summary.merge_status.value,
        "is_successful": summary.is_successful,
        "is_terminal_failure": summary.is_terminal_failure,
        "has_errors": bool(summary.errors),
        "has_warnings": bool(summary.warnings),
        "success_rate": round(summary.success_rate, 4),
        "has_recovery_recommendation": rec is not None,
        "recovery_posture": rec.posture.value if rec is not None else None,
        "total_count": summary.total_count,
        "task_id": summary.task_id,
        "trace_id": summary.trace_id,
    }
