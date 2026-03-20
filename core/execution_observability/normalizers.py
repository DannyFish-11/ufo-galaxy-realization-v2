"""
core.execution_observability.normalizers
=========================================

Helper functions (adapters) that convert raw dicts / objects coming from the
existing Galaxy execution paths into the unified
:class:`~core.execution_observability.ExecutionEvent` / sub-schema types.

Each normaliser is intentionally *tolerant*: missing or ``None`` fields are
handled gracefully so that callers do not need to guard every path.

Covered source paths
--------------------
* ``core/e2e_orchestrator.py``
    Context dicts and DAG result dicts produced by
    ``process_user_input()`` / ``compile_and_run_dag()``.

* ``galaxy_gateway/orchestrator/task_orchestrator.py``
    ``TaskEnvelope`` / ``TaskOrchestrator`` trace fields and execution
    attempt log entries.

* ``core/task_graph.py``
    ``TaskGraph`` instances and their ``run()`` result dicts.

* ``core/windows_execution_arbiter.py``
    ``WinExecAttempt`` dataclass entries from arbiter attempt logs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .event_schema import ExecutionEvent
from .executor_level import ExecutorLevel
from .fallback_schema import FallbackContext, FallbackReason
from .trace_schema import TraceCorrelation

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

# Keys that carry trace/routing semantics and should not be forwarded into the
# generic metadata dict of an ExecutionEvent.
_TRACE_RESERVED_KEYS = frozenset({
    "trace_id",
    "runtime_session_id",
    "task_id",
    "action_id",
    "command_id",
    "tri_state_phase",
    "runtime_domain",
    "phase",
    "domain",
    "message",
    "action",
    "executor_level",
    "level",
    "fallback_reason",
})


# ---------------------------------------------------------------------------
# e2e_orchestrator normaliser
# ---------------------------------------------------------------------------

def normalize_e2e_context(
    ctx: Dict[str, Any],
    *,
    message: str = "",
    executor_level: ExecutorLevel = ExecutorLevel.ORCHESTRATOR,
) -> ExecutionEvent:
    """Build an :class:`ExecutionEvent` from a ``core/e2e_orchestrator.py``
    context dict.

    The e2e orchestrator stores fields such as ``trace_id``,
    ``runtime_session_id``, ``tri_state_phase``, and ``runtime_domain`` at
    the top level of its context dict.

    Parameters
    ----------
    ctx:
        Raw context dict from ``process_user_input()`` or a DAG result dict.
    message:
        Optional human-readable annotation.
    executor_level:
        Override for the executor level (defaults to ``ORCHESTRATOR``).

    Returns
    -------
    ExecutionEvent
    """
    trace = TraceCorrelation.from_e2e_context(ctx)
    return ExecutionEvent.build(
        trace=trace,
        executor_level=executor_level,
        tri_state_phase=ctx.get("tri_state_phase") or ctx.get("phase"),
        runtime_domain=ctx.get("runtime_domain") or ctx.get("domain"),
        message=message or ctx.get("message", ""),
        metadata={k: v for k, v in ctx.items() if k not in _TRACE_RESERVED_KEYS},
    )


# ---------------------------------------------------------------------------
# task_orchestrator / TaskEnvelope normaliser
# ---------------------------------------------------------------------------

def normalize_task_envelope(
    envelope: Any,
    *,
    message: str = "",
    executor_level: ExecutorLevel = ExecutorLevel.ORCHESTRATOR,
) -> ExecutionEvent:
    """Build an :class:`ExecutionEvent` from a ``TaskEnvelope`` or similar
    object from ``galaxy_gateway/orchestrator/task_orchestrator.py``.

    Accepts either a dataclass/object with attributes or a plain dict.

    Parameters
    ----------
    envelope:
        ``TaskEnvelope`` instance, ``CommandEnvelope`` instance, or dict.
    message:
        Optional human-readable annotation.
    executor_level:
        Override for the executor level (defaults to ``ORCHESTRATOR``).
    """
    trace = TraceCorrelation.from_task_envelope(envelope)
    raw = envelope if isinstance(envelope, dict) else {}
    return ExecutionEvent.build(
        trace=trace,
        executor_level=executor_level,
        tri_state_phase=raw.get("tri_state_phase") if raw else None,
        runtime_domain=raw.get("runtime_domain") if raw else None,
        message=message,
    )


# ---------------------------------------------------------------------------
# task_graph normaliser
# ---------------------------------------------------------------------------

def normalize_task_graph_result(
    result: Dict[str, Any],
    *,
    graph: Optional[Any] = None,
    message: str = "",
) -> ExecutionEvent:
    """Build an :class:`ExecutionEvent` from a ``TaskGraph.run()`` result dict.

    ``TaskGraph.run()`` returns a dict with at least::

        {
            "success": bool,
            "done": [...],
            "failed": [...],
            "trace_id": str,
            "graph_id": str,
            "elapsed_ms": float,
        }

    Parameters
    ----------
    result:
        Dict returned by ``TaskGraph.run()``.
    graph:
        Optionally pass the ``TaskGraph`` instance itself to enrich with
        ``runtime_session_id`` when the result dict does not carry it.
    message:
        Optional human-readable annotation.
    """
    # Build trace — prefer data on the result dict, fall back to graph object
    trace_data: Dict[str, Any] = {
        "trace_id": result.get("trace_id") or "",
        "runtime_session_id": result.get("runtime_session_id") or (
            getattr(graph, "runtime_session_id", "") if graph else ""
        ),
        "task_id": result.get("graph_id") or (
            getattr(graph, "graph_id", None) if graph else None
        ),
    }
    trace = TraceCorrelation.from_dict(trace_data)

    failed_nodes: List[str] = result.get("failed") or []
    fallback: Optional[FallbackContext] = None
    if failed_nodes:
        fallback = FallbackContext(
            from_level=ExecutorLevel.ORCHESTRATOR,
            reason=FallbackReason.PARTIAL_FAILURE,
            raw_reason="partial_failure",
            message=f"{len(failed_nodes)} node(s) failed: {', '.join(failed_nodes[:3])}",
            metadata={"failed_nodes": failed_nodes},
        )

    return ExecutionEvent.build(
        trace=trace,
        executor_level=ExecutorLevel.ORCHESTRATOR,
        fallback=fallback,
        message=message or (
            "TaskGraph completed successfully"
            if result.get("success")
            else f"TaskGraph finished with {len(failed_nodes)} failure(s)"
        ),
        metadata={
            "elapsed_ms": result.get("elapsed_ms"),
            "done_count": len(result.get("done") or []),
            "failed_count": len(failed_nodes),
            "skipped_count": len(result.get("skipped") or []),
        },
    )


# ---------------------------------------------------------------------------
# Windows arbiter normaliser
# ---------------------------------------------------------------------------

def normalize_arbiter_attempt(
    attempt: Any,
    *,
    trace: Optional[TraceCorrelation] = None,
    tri_state_phase: Optional[str] = None,
    runtime_domain: Optional[str] = None,
) -> ExecutionEvent:
    """Build an :class:`ExecutionEvent` from a ``WinExecAttempt`` (arbiter log).

    ``WinExecAttempt`` has fields: ``executor_level``, ``fallback_reason``,
    ``action_summary``, ``status``, ``latency_ms``, ``device_id``.

    Accepts the dataclass object itself or a plain dict (``attempt.to_dict()``).
    """
    if isinstance(attempt, dict):
        level_raw = str(attempt.get("executor_level") or "")
        fallback_raw = str(attempt.get("fallback_reason") or "")
        action_summary = str(attempt.get("action_summary") or "")
        status = str(attempt.get("status") or "")
        latency_ms = attempt.get("latency_ms")
        device_id = attempt.get("device_id")
    else:
        _level = getattr(attempt, "executor_level", None)
        level_raw = _level.value if hasattr(_level, "value") else str(_level or "")
        fallback_raw = str(getattr(attempt, "fallback_reason", "") or "")
        action_summary = str(getattr(attempt, "action_summary", "") or "")
        status = getattr(attempt, "status", None)
        status = status.value if hasattr(status, "value") else str(status or "")
        latency_ms = getattr(attempt, "latency_ms", None)
        device_id = getattr(attempt, "device_id", None)

    exec_level = ExecutorLevel.from_string(level_raw)

    fallback: Optional[FallbackContext] = None
    if fallback_raw:
        fallback = FallbackContext(
            from_level=exec_level,
            reason=FallbackReason.from_string(fallback_raw),
            raw_reason=fallback_raw,
            message=f"{exec_level.value} fallback: {fallback_raw}",
            metadata={"action_summary": action_summary},
        )

    meta: Dict[str, Any] = {"status": status, "action_summary": action_summary}
    if latency_ms is not None:
        meta["latency_ms"] = latency_ms
    if device_id is not None:
        meta["device_id"] = device_id

    return ExecutionEvent.build(
        trace=trace if trace is not None else TraceCorrelation.new(),
        executor_level=exec_level,
        fallback=fallback,
        tri_state_phase=tri_state_phase,
        runtime_domain=runtime_domain,
        message=f"[{exec_level.value}] {action_summary or 'execution attempt'} → {status}",
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# Generic/observability-route normaliser
# ---------------------------------------------------------------------------

def normalize_observability_payload(
    payload: Dict[str, Any],
) -> ExecutionEvent:
    """Best-effort normaliser for arbitrary observability route payloads.

    Used to adapt existing ``core/routes/observability.py`` trace records
    (GatewayTraceStore entries) into the unified event shape.
    """
    # GatewayTraceStore entries typically have: command_id, task_id, trace_id,
    # action, status, latency_ms, device_id, timestamp.
    trace = TraceCorrelation(
        trace_id=payload.get("trace_id") or payload.get("command_id") or "",
        runtime_session_id=payload.get("runtime_session_id") or "",
        task_id=payload.get("task_id") or None,
        action_id=payload.get("command_id") or None,
    )
    raw_level = payload.get("executor_level") or payload.get("level") or ""
    exec_level = ExecutorLevel.from_string(str(raw_level))

    fallback_raw = payload.get("fallback_reason") or ""
    fallback: Optional[FallbackContext] = None
    if fallback_raw:
        fallback = FallbackContext(
            from_level=exec_level,
            reason=FallbackReason.from_string(str(fallback_raw)),
            raw_reason=str(fallback_raw),
            message=str(fallback_raw),
        )

    return ExecutionEvent.build(
        trace=trace,
        executor_level=exec_level,
        fallback=fallback,
        tri_state_phase=payload.get("tri_state_phase"),
        runtime_domain=payload.get("runtime_domain"),
        message=payload.get("message") or payload.get("action") or "",
        metadata={k: v for k, v in payload.items() if k not in _TRACE_RESERVED_KEYS},
    )
