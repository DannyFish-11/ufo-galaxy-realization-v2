#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.distributed_execution.merge_status
=========================================

PR-14 (V4) — Distributed Task Merge & Recovery

Defines :class:`MergeStatus` — the stable, serialisable enum that classifies
the overall outcome of merging results from multiple tasks, devices, or
DAG branches.

Merge Status Semantics
-----------------------
+----------------------+--------------------------------------------------------+
| Status               | Meaning                                                |
+======================+========================================================+
| ``success``          | All required branches completed successfully.          |
|                      | No failures, no timeouts.                              |
+----------------------+--------------------------------------------------------+
| ``partial_success``  | Some branches completed; some failed or were skipped,  |
|                      | but the core intent was achieved.  Optional branches   |
|                      | may have been skipped without loss of goal.            |
+----------------------+--------------------------------------------------------+
| ``degraded_success`` | The goal was nominally achieved but with reduced        |
|                      | fidelity — e.g. a fallback path was used, quality was  |
|                      | lowered, or a non-critical branch failed such that     |
|                      | the result is still usable but incomplete.             |
+----------------------+--------------------------------------------------------+
| ``failed``           | One or more required branches failed and the overall   |
|                      | task goal was not achieved.                            |
+----------------------+--------------------------------------------------------+
| ``timed_out``        | The merge window expired before sufficient branches    |
|                      | completed.  Results that did arrive may be present     |
|                      | but the overall task is considered incomplete.         |
+----------------------+--------------------------------------------------------+

:data:`MERGE_STATUS_ORDER` provides a total ordering from best to worst
outcome, useful for choosing the minimum status across a set of results.

:func:`merge_status_severity` maps each status to an integer severity level
(0 = best, 4 = worst).

:func:`worst_of` returns the more severe of two :class:`MergeStatus` values.
"""

from __future__ import annotations

from enum import Enum


__all__ = [
    "MergeStatus",
    "MERGE_STATUS_ORDER",
    "merge_status_severity",
    "worst_of",
    "is_terminal_failure",
    "is_successful_outcome",
]


# ---------------------------------------------------------------------------
# Merge status enum
# ---------------------------------------------------------------------------


class MergeStatus(str, Enum):
    """Stable, serialisable classification of a multi-branch merge outcome.

    String values are stable identifiers safe for serialisation, logging, and
    API responses.
    """

    SUCCESS = "success"
    """All required branches succeeded; no failures or timeouts."""

    PARTIAL_SUCCESS = "partial_success"
    """Core intent achieved; some optional or non-critical branches failed."""

    DEGRADED_SUCCESS = "degraded_success"
    """Goal nominally achieved via fallback or reduced fidelity."""

    FAILED = "failed"
    """Required branches failed; overall task goal not achieved."""

    TIMED_OUT = "timed_out"
    """Merge window expired before sufficient branches completed."""


# ---------------------------------------------------------------------------
# Ordering
# ---------------------------------------------------------------------------

#: Ordered list from best to worst outcome.
MERGE_STATUS_ORDER: list = [
    MergeStatus.SUCCESS,
    MergeStatus.PARTIAL_SUCCESS,
    MergeStatus.DEGRADED_SUCCESS,
    MergeStatus.FAILED,
    MergeStatus.TIMED_OUT,
]

_STATUS_SEVERITY: dict = {
    s: i for i, s in enumerate(MERGE_STATUS_ORDER)
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def merge_status_severity(status: MergeStatus) -> int:
    """Return severity level: 0 = best (success), 4 = worst (timed_out).

    Args:
        status: A :class:`MergeStatus` value.

    Returns:
        Integer severity level.
    """
    return _STATUS_SEVERITY.get(status, len(MERGE_STATUS_ORDER))


def worst_of(a: MergeStatus, b: MergeStatus) -> MergeStatus:
    """Return the more severe of two :class:`MergeStatus` values.

    Args:
        a: First status.
        b: Second status.

    Returns:
        The status with higher severity.
    """
    return a if merge_status_severity(a) >= merge_status_severity(b) else b


def is_terminal_failure(status: MergeStatus) -> bool:
    """True if the status represents a non-recoverable failure or timeout.

    Args:
        status: A :class:`MergeStatus` value.

    Returns:
        ``True`` for :attr:`~MergeStatus.FAILED` and
        :attr:`~MergeStatus.TIMED_OUT`; ``False`` otherwise.
    """
    return status in (MergeStatus.FAILED, MergeStatus.TIMED_OUT)


def is_successful_outcome(status: MergeStatus) -> bool:
    """True if the status represents any form of success (including degraded).

    Args:
        status: A :class:`MergeStatus` value.

    Returns:
        ``True`` for :attr:`~MergeStatus.SUCCESS`,
        :attr:`~MergeStatus.PARTIAL_SUCCESS`, and
        :attr:`~MergeStatus.DEGRADED_SUCCESS`; ``False`` otherwise.
    """
    return status in (
        MergeStatus.SUCCESS,
        MergeStatus.PARTIAL_SUCCESS,
        MergeStatus.DEGRADED_SUCCESS,
    )
