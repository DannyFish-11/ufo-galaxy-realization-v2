#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.distributed_execution
============================

PR-14 (V4) — Distributed Task Merge & Recovery

A focused, additive package that formalises how multi-device / DAG / parallel
execution results are merged into coherent outcomes and how recovery decisions
are expressed.

This package answers:
  - How are multiple task/device/subtask results merged? (:mod:`.result_merge`)
  - What is the overall merge status? (:class:`MergeStatus`)
  - How do we distinguish success, partial success, degraded success, failure,
    and timeout?
  - When something fails, what recovery posture should be recommended?
    (:class:`RecoveryPosture`, :func:`recommend_recovery`)
  - How can downstream projection / observability layers consume these results
    consistently? (:func:`attach_merge_summary_to_projection`,
    :func:`get_merge_hints`)

Source signals consumed (read-only, not modified)
--------------------------------------------------
* :class:`~core.unified.command_envelope.ResultEnvelope` — PR-2
* :class:`~core.task_graph.GraphExecutionResult` — PR-5
* Plain ``dict`` result payloads (parallel tracker aggregates, etc.)
* :class:`~core.cross_device_policy.RoutingPolicy` (optional, via hints)
* :class:`~core.execution_policy.ExecutionPolicy` (optional, via hints)

Public API
----------
MergeStatus
    Enum of merge outcomes: ``success``, ``partial_success``,
    ``degraded_success``, ``failed``, ``timed_out``.

MERGE_STATUS_ORDER
    Ordered list from best to worst outcome.

merge_status_severity(status) → int
    Severity level: 0 (success) to 4 (timed_out).

worst_of(a, b) → MergeStatus
    Return the more severe of two statuses.

is_terminal_failure(status) → bool
    True for ``failed`` and ``timed_out``.

is_successful_outcome(status) → bool
    True for any success variant.

RecoveryPosture
    Enum of recovery actions: ``no_recovery_needed``, ``retry_same_device``,
    ``reroute_device``, ``skip_optional_branch``, ``require_confirmation``,
    ``abort_task``.

POSTURE_DESCRIPTIONS
    Dict of human-readable descriptions for each posture.

RecoveryRecommendation
    Immutable, serialisable recovery recommendation dataclass.

recommend_recovery(merge_status, …) → RecoveryRecommendation
    Derive recovery recommendation from merge outcome and context hints.

MergeSummary
    Immutable, serialisable merge result summary.  Fields: merge_status,
    counts, payloads, errors, warnings, recovery_recommendation, trace IDs.

EMPTY_MERGE_SUMMARY
    Pre-built empty/uninitialised summary.

attach_merge_summary_to_projection(projection_dict, summary) → dict
    Attach a merge summary to a ``RuntimeProjection`` dict additively.

get_merge_hints(summary) → dict
    Compact boolean/scalar hints for quick downstream checks.

merge_result_envelopes(envelopes, …) → MergeSummary
    Merge a list of :class:`~core.unified.command_envelope.ResultEnvelope` objects.

merge_graph_result(graph_result, …) → MergeSummary
    Wrap a :class:`~core.task_graph.GraphExecutionResult` into a summary.

merge_dict_results(results, …) → MergeSummary
    Merge a list of plain dict result payloads.

merge_any(inputs, …) → MergeSummary
    Auto-dispatch merge for a heterogeneous list of result inputs.

What this package does NOT do
------------------------------
- It does **not** replace or modify ``TaskGraph``, ``DAGScheduler``,
  ``ConstellationRuntime``, ``DesktopPresenceRuntime``, or any existing
  orchestrator.
- It does **not** implement step semantics (planned for a later PR).
- It does **not** add a competing top-level runtime.
- All paths are additive and read-only from the perspective of existing
  orchestration layers.

See Also
--------
docs/DISTRIBUTED_TASK_MERGE_RECOVERY.md — design document for this package.
core/cross_device_policy/ — PR-13 cross-device role & routing (upstream signal).
core/execution_policy/ — PR-11 execution policy schema (upstream signal).
core/execution_observability/ — PR-7 observability layer (downstream consumer).
core/task_graph.py — existing DAG engine (not modified).
"""

from __future__ import annotations

from .merge_status import (
    MergeStatus,
    MERGE_STATUS_ORDER,
    merge_status_severity,
    worst_of,
    is_terminal_failure,
    is_successful_outcome,
)
from .recovery_policy import (
    RecoveryPosture,
    POSTURE_DESCRIPTIONS,
    RecoveryRecommendation,
    recommend_recovery,
)
from .merge_summary import (
    MergeSummary,
    EMPTY_MERGE_SUMMARY,
    attach_merge_summary_to_projection,
    get_merge_hints,
)
from .result_merge import (
    merge_result_envelopes,
    merge_graph_result,
    merge_dict_results,
    merge_any,
)

__all__ = [
    # Merge status
    "MergeStatus",
    "MERGE_STATUS_ORDER",
    "merge_status_severity",
    "worst_of",
    "is_terminal_failure",
    "is_successful_outcome",
    # Recovery policy
    "RecoveryPosture",
    "POSTURE_DESCRIPTIONS",
    "RecoveryRecommendation",
    "recommend_recovery",
    # Merge summary
    "MergeSummary",
    "EMPTY_MERGE_SUMMARY",
    "attach_merge_summary_to_projection",
    "get_merge_hints",
    # Result merge helpers
    "merge_result_envelopes",
    "merge_graph_result",
    "merge_dict_results",
    "merge_any",
]
