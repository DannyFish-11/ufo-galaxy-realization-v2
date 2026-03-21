#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.distributed_execution.result_merge
=========================================

PR-14 (V4) — Distributed Task Merge & Recovery

Provides helpers for merging heterogeneous result inputs from multi-device,
parallel, and DAG-based execution into a single coherent
:class:`~.merge_summary.MergeSummary`.

Supported input types
---------------------
All helpers degrade gracefully when fields are absent or inputs are ``None``.

:class:`~core.unified.command_envelope.ResultEnvelope`
    Canonical executor result envelope (PR-2).  Fields: ``success``,
    ``error``, ``elapsed_ms``, ``task_id``, ``trace_id``, ``device_id``.

:class:`~core.task_graph.GraphExecutionResult`
    DAG execution summary (PR-5).  Fields: ``success``, ``failed_nodes``,
    ``done_nodes``, ``skipped_nodes``, ``total_nodes``, ``trace_id``,
    ``runtime_session_id``, ``node_results``, ``node_errors``.

``dict``
    Lightweight dict-based result payloads (e.g. from parallel tracker
    aggregate or ad-hoc subtask results).  Expected optional keys:
    ``success``, ``error``, ``task_id``, ``trace_id``, ``device_id``,
    ``timed_out``, ``elapsed_ms``, ``result``.

Public API
----------
merge_result_envelopes(envelopes, …) → MergeSummary
    Merge a list of :class:`ResultEnvelope` objects.

merge_graph_result(graph_result, …) → MergeSummary
    Wrap a :class:`GraphExecutionResult` into a :class:`MergeSummary`.

merge_dict_results(results, …) → MergeSummary
    Merge a list of plain dicts.

merge_any(inputs, …) → MergeSummary
    Auto-dispatch: accepts any mix of the above input types.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Union

from .merge_status import MergeStatus, worst_of

logger = logging.getLogger("Galaxy.DistributedExecution.ResultMerge")

__all__ = [
    "merge_result_envelopes",
    "merge_graph_result",
    "merge_dict_results",
    "merge_any",
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_status(
    successful: int,
    failed: int,
    timed_out: int,
    total: int,
) -> MergeStatus:
    """Classify overall merge status from branch counts.

    Logic:
    - ``total == 0`` → ``failed`` (nothing to merge)
    - ``timed_out > 0`` and ``successful == 0`` → ``timed_out``
    - ``failed == 0`` and ``timed_out == 0`` → ``success``
    - ``successful > 0`` and ``failed > 0`` (no timeouts) → ``partial_success``
    - ``timed_out > 0`` and ``successful > 0`` → ``partial_success``
    - all failed or all timed-out with no success → ``failed`` / ``timed_out``
    """
    if total == 0:
        return MergeStatus.FAILED

    if successful == total:
        return MergeStatus.SUCCESS

    if failed == total:
        return MergeStatus.FAILED

    if timed_out == total:
        return MergeStatus.TIMED_OUT

    # Mixed outcomes
    if successful == 0 and timed_out > 0:
        return MergeStatus.TIMED_OUT

    if successful == 0:
        return MergeStatus.FAILED

    # Some succeeded, some did not
    return MergeStatus.PARTIAL_SUCCESS


def _extract_ids_from_envelope(env: Any) -> Dict[str, str]:
    """Safely extract trace/task/device IDs from a ResultEnvelope-like object."""
    return {
        "task_id": getattr(env, "task_id", "") or "",
        "trace_id": getattr(env, "trace_id", "") or "",
        "device_id": getattr(env, "device_id", "") or "",
        "runtime_session_id": getattr(env, "runtime_session_id", "") or "",
    }


def _extract_ids_from_dict(d: Dict[str, Any]) -> Dict[str, str]:
    """Safely extract trace/task/device IDs from a plain dict."""
    return {
        "task_id": str(d.get("task_id") or ""),
        "trace_id": str(d.get("trace_id") or ""),
        "device_id": str(d.get("device_id") or ""),
        "runtime_session_id": str(d.get("runtime_session_id") or ""),
    }


# ---------------------------------------------------------------------------
# Public merge helpers
# ---------------------------------------------------------------------------


def merge_result_envelopes(
    envelopes: List[Any],
    *,
    task_id: str = "",
    trace_id: str = "",
    runtime_session_id: str = "",
) -> "MergeSummary":  # noqa: F821 — forward ref resolved at module level
    """Merge a list of :class:`~core.unified.command_envelope.ResultEnvelope` objects.

    Degrades gracefully when ``envelopes`` is empty or contains ``None``
    entries.

    Args:
        envelopes:          List of :class:`ResultEnvelope` instances.
        task_id:            Override task ID for the summary.
        trace_id:           Override trace ID for the summary.
        runtime_session_id: Override session ID for the summary.

    Returns:
        A :class:`MergeSummary` instance.
    """
    from .merge_summary import MergeSummary  # local import avoids circular

    valid = [e for e in (envelopes or []) if e is not None]
    if not valid:
        return MergeSummary(
            merge_status=MergeStatus.FAILED,
            total_count=0,
            successful_count=0,
            failed_count=0,
            timed_out_count=0,
            merged_payloads=[],
            errors=[],
            warnings=["No result envelopes provided to merge."],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    successful = 0
    failed = 0
    timed_out = 0
    errors: List[str] = []
    warnings: List[str] = []
    merged_payloads: List[Dict[str, Any]] = []

    # Use first non-empty IDs from inputs if not provided
    _task_id = task_id
    _trace_id = trace_id
    _session_id = runtime_session_id

    for env in valid:
        ids = _extract_ids_from_envelope(env)
        if not _task_id:
            _task_id = ids["task_id"]
        if not _trace_id:
            _trace_id = ids["trace_id"]
        if not _session_id:
            _session_id = ids["runtime_session_id"]

        success = bool(getattr(env, "success", False))
        error = getattr(env, "error", None) or ""
        result = getattr(env, "result", {}) or {}
        elapsed_ms = float(getattr(env, "elapsed_ms", 0.0) or 0.0)

        if success:
            successful += 1
        else:
            # Check for timed_out indicator in result payload or error message
            is_timeout = (
                "timeout" in error.lower()
                or "timed_out" in error.lower()
                or bool(result.get("timed_out"))
            )
            if is_timeout:
                timed_out += 1
                warnings.append(
                    f"Branch timed out: task_id={ids['task_id']} "
                    f"device={ids['device_id']}"
                )
            else:
                failed += 1
                if error:
                    errors.append(
                        f"Branch failed [{ids['device_id']}]: {error}"
                    )

        merged_payloads.append({
            "task_id": ids["task_id"],
            "trace_id": ids["trace_id"],
            "device_id": ids["device_id"],
            "success": success,
            "result": result,
            "error": error,
            "elapsed_ms": elapsed_ms,
        })

    status = _classify_status(successful, failed, timed_out, len(valid))

    return MergeSummary(
        merge_status=status,
        total_count=len(valid),
        successful_count=successful,
        failed_count=failed,
        timed_out_count=timed_out,
        merged_payloads=merged_payloads,
        errors=errors,
        warnings=warnings,
        task_id=_task_id,
        trace_id=_trace_id,
        runtime_session_id=_session_id,
    )


def merge_graph_result(
    graph_result: Any,
    *,
    task_id: str = "",
    trace_id: str = "",
    runtime_session_id: str = "",
) -> "MergeSummary":  # noqa: F821
    """Wrap a :class:`~core.task_graph.GraphExecutionResult` into a
    :class:`MergeSummary`.

    Degrades gracefully if ``graph_result`` is ``None`` or lacks expected
    attributes.

    Args:
        graph_result:       A :class:`~core.task_graph.GraphExecutionResult`
                            instance or ``None``.
        task_id:            Override task ID for the summary.
        trace_id:           Override trace ID for the summary.
        runtime_session_id: Override session ID for the summary.

    Returns:
        A :class:`MergeSummary` instance.
    """
    from .merge_summary import MergeSummary

    if graph_result is None:
        return MergeSummary(
            merge_status=MergeStatus.FAILED,
            total_count=0,
            successful_count=0,
            failed_count=0,
            timed_out_count=0,
            merged_payloads=[],
            errors=["No GraphExecutionResult provided."],
            warnings=[],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    _trace_id = trace_id or getattr(graph_result, "trace_id", "") or ""
    _session_id = runtime_session_id or getattr(graph_result, "runtime_session_id", "") or ""
    _task_id = task_id or getattr(graph_result, "graph_id", "") or ""

    done = int(getattr(graph_result, "done_nodes", 0) or 0)
    failed = int(getattr(graph_result, "failed_nodes", 0) or 0)
    skipped = int(getattr(graph_result, "skipped_nodes", 0) or 0)
    total = int(getattr(graph_result, "total_nodes", 0) or 0)
    overall_success = bool(getattr(graph_result, "success", False))
    graph_error = getattr(graph_result, "error", "") or ""

    # Build merged payloads from node results
    node_results: Dict[str, Any] = getattr(graph_result, "node_results", {}) or {}
    node_errors: Dict[str, str] = getattr(graph_result, "node_errors", {}) or {}
    node_statuses: Dict[str, str] = getattr(graph_result, "node_statuses", {}) or {}

    merged_payloads: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []

    for node_id, node_result in node_results.items():
        node_status = node_statuses.get(node_id, "unknown")
        node_error = node_errors.get(node_id, "") or ""
        merged_payloads.append({
            "node_id": node_id,
            "status": node_status,
            "result": node_result or {},
            "error": node_error,
        })
        if node_error:
            errors.append(f"Node [{node_id}] error: {node_error}")
        if node_status in ("skipped", "cancelled", "interrupted"):
            warnings.append(f"Node [{node_id}] was {node_status}.")

    if graph_error:
        errors.append(f"Graph error: {graph_error}")

    # Classify status
    if total == 0:
        status = MergeStatus.FAILED
    elif overall_success:
        if skipped > 0:
            status = MergeStatus.PARTIAL_SUCCESS
        else:
            status = MergeStatus.SUCCESS
    else:
        status = _classify_status(done, failed, 0, total)

    return MergeSummary(
        merge_status=status,
        total_count=total,
        successful_count=done,
        failed_count=failed,
        timed_out_count=0,
        skipped_count=skipped,
        merged_payloads=merged_payloads,
        errors=errors,
        warnings=warnings,
        task_id=_task_id,
        trace_id=_trace_id,
        runtime_session_id=_session_id,
    )


def merge_dict_results(
    results: List[Dict[str, Any]],
    *,
    task_id: str = "",
    trace_id: str = "",
    runtime_session_id: str = "",
) -> "MergeSummary":  # noqa: F821
    """Merge a list of plain dict result payloads.

    Expected optional dict keys: ``success``, ``error``, ``task_id``,
    ``trace_id``, ``device_id``, ``timed_out``, ``elapsed_ms``, ``result``.

    Degrades gracefully when keys are absent.

    Args:
        results:            List of plain dict results.
        task_id:            Override task ID for the summary.
        trace_id:           Override trace ID for the summary.
        runtime_session_id: Override session ID for the summary.

    Returns:
        A :class:`MergeSummary` instance.
    """
    from .merge_summary import MergeSummary

    valid = [r for r in (results or []) if isinstance(r, dict)]
    if not valid:
        return MergeSummary(
            merge_status=MergeStatus.FAILED,
            total_count=0,
            successful_count=0,
            failed_count=0,
            timed_out_count=0,
            merged_payloads=[],
            errors=[],
            warnings=["No dict results provided to merge."],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    successful = 0
    failed = 0
    timed_out = 0
    errors: List[str] = []
    warnings: List[str] = []
    merged_payloads: List[Dict[str, Any]] = []

    _task_id = task_id
    _trace_id = trace_id
    _session_id = runtime_session_id

    for r in valid:
        ids = _extract_ids_from_dict(r)
        if not _task_id:
            _task_id = ids["task_id"]
        if not _trace_id:
            _trace_id = ids["trace_id"]
        if not _session_id:
            _session_id = ids["runtime_session_id"]

        success = bool(r.get("success", False))
        error = str(r.get("error") or "")
        is_timeout = bool(r.get("timed_out", False)) or (
            "timeout" in error.lower() or "timed_out" in error.lower()
        )
        result_payload = r.get("result") or {}
        elapsed_ms = float(r.get("elapsed_ms") or 0.0)

        if success:
            successful += 1
        elif is_timeout:
            timed_out += 1
            warnings.append(
                f"Branch timed out: task_id={ids['task_id']} "
                f"device={ids['device_id']}"
            )
        else:
            failed += 1
            if error:
                errors.append(
                    f"Branch failed [{ids['device_id'] or ids['task_id']}]: {error}"
                )

        merged_payloads.append({
            "task_id": ids["task_id"],
            "trace_id": ids["trace_id"],
            "device_id": ids["device_id"],
            "success": success,
            "result": result_payload,
            "error": error,
            "elapsed_ms": elapsed_ms,
        })

    status = _classify_status(successful, failed, timed_out, len(valid))

    return MergeSummary(
        merge_status=status,
        total_count=len(valid),
        successful_count=successful,
        failed_count=failed,
        timed_out_count=timed_out,
        merged_payloads=merged_payloads,
        errors=errors,
        warnings=warnings,
        task_id=_task_id,
        trace_id=_trace_id,
        runtime_session_id=_session_id,
    )


def merge_any(
    inputs: List[Any],
    *,
    task_id: str = "",
    trace_id: str = "",
    runtime_session_id: str = "",
) -> "MergeSummary":  # noqa: F821
    """Auto-dispatch merge for a heterogeneous list of result inputs.

    Accepts any mix of:
    - :class:`~core.unified.command_envelope.ResultEnvelope` objects
    - :class:`~core.task_graph.GraphExecutionResult` objects
    - plain ``dict`` payloads

    Each input is classified and routed to the appropriate merge helper.
    Homogeneous sub-lists are merged independently; if the list contains
    only a single :class:`GraphExecutionResult`, delegates directly to
    :func:`merge_graph_result`.

    Degrades gracefully when ``inputs`` is empty or contains ``None`` values.

    Args:
        inputs:             Mixed list of result inputs.
        task_id:            Override task ID for the summary.
        trace_id:           Override trace ID for the summary.
        runtime_session_id: Override session ID for the summary.

    Returns:
        A single :class:`MergeSummary`.
    """
    from .merge_summary import MergeSummary

    # Lazy imports to avoid circular dependencies at module load
    try:
        from core.unified.command_envelope import ResultEnvelope as _RE
    except ImportError:
        _RE = None

    try:
        from core.task_graph import GraphExecutionResult as _GER
    except ImportError:
        _GER = None

    valid = [i for i in (inputs or []) if i is not None]
    if not valid:
        return MergeSummary(
            merge_status=MergeStatus.FAILED,
            total_count=0,
            successful_count=0,
            failed_count=0,
            timed_out_count=0,
            merged_payloads=[],
            errors=[],
            warnings=["No inputs provided to merge_any."],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    envelopes = []
    graph_results = []
    dicts = []

    for item in valid:
        if _GER is not None and isinstance(item, _GER):
            graph_results.append(item)
        elif _RE is not None and isinstance(item, _RE):
            envelopes.append(item)
        elif isinstance(item, dict):
            dicts.append(item)
        else:
            # Unknown type: try dict-like coercion
            try:
                dicts.append(dict(item))
            except (TypeError, ValueError):
                logger.warning(
                    "merge_any: skipping unrecognised input type %s",
                    type(item).__name__,
                )

    # Single GraphExecutionResult: delegate directly
    if len(graph_results) == 1 and not envelopes and not dicts:
        return merge_graph_result(
            graph_results[0],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    # Collect sub-summaries from each category
    sub_summaries = []
    if envelopes:
        sub_summaries.append(
            merge_result_envelopes(
                envelopes,
                task_id=task_id,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
        )
    for gr in graph_results:
        sub_summaries.append(
            merge_graph_result(
                gr,
                task_id=task_id,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
        )
    if dicts:
        sub_summaries.append(
            merge_dict_results(
                dicts,
                task_id=task_id,
                trace_id=trace_id,
                runtime_session_id=runtime_session_id,
            )
        )

    if not sub_summaries:
        return MergeSummary(
            merge_status=MergeStatus.FAILED,
            total_count=0,
            successful_count=0,
            failed_count=0,
            timed_out_count=0,
            merged_payloads=[],
            errors=["All inputs were unrecognised types."],
            warnings=[],
            task_id=task_id,
            trace_id=trace_id,
            runtime_session_id=runtime_session_id,
        )

    # Combine sub-summaries into one
    total = sum(s.total_count for s in sub_summaries)
    successful = sum(s.successful_count for s in sub_summaries)
    failed = sum(s.failed_count for s in sub_summaries)
    timed_out = sum(s.timed_out_count for s in sub_summaries)
    skipped = sum(getattr(s, "skipped_count", 0) for s in sub_summaries)
    all_payloads = []
    all_errors: List[str] = []
    all_warnings: List[str] = []
    for s in sub_summaries:
        all_payloads.extend(s.merged_payloads)
        all_errors.extend(s.errors)
        all_warnings.extend(s.warnings)

    # Overall status: use worst across sub-summaries
    overall_status = sub_summaries[0].merge_status
    for s in sub_summaries[1:]:
        overall_status = worst_of(overall_status, s.merge_status)

    _task_id = task_id or next(
        (s.task_id for s in sub_summaries if s.task_id), ""
    )
    _trace_id = trace_id or next(
        (s.trace_id for s in sub_summaries if s.trace_id), ""
    )
    _session_id = runtime_session_id or next(
        (s.runtime_session_id for s in sub_summaries if s.runtime_session_id), ""
    )

    return MergeSummary(
        merge_status=overall_status,
        total_count=total,
        successful_count=successful,
        failed_count=failed,
        timed_out_count=timed_out,
        skipped_count=skipped,
        merged_payloads=all_payloads,
        errors=all_errors,
        warnings=all_warnings,
        task_id=_task_id,
        trace_id=_trace_id,
        runtime_session_id=_session_id,
    )
