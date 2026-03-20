"""
core.execution_observability — Execution Observability Unification (PR-7)
=========================================================================

A small, **additive** package that unifies execution observability semantics
across the existing runtime / orchestration paths in Galaxy.

This package does **not** replace or duplicate any existing observability
infrastructure.  It provides stable, serialisable schemas that existing
signal sources (``core/e2e_orchestrator.py``,
``galaxy_gateway/orchestrator/task_orchestrator.py``, ``core/task_graph.py``,
``core/windows_execution_arbiter.py``) can be normalised *into*, so that
downstream consumers (RuntimeProjection, Status Board v2, Manifest stage) can
read a consistent shape regardless of which orchestration path was active.

Public API
----------
ExecutorLevel
    Enum of execution tiers (system_api → uia → gui → vlm → …).

FallbackReason
    Enum of structured fallback reasons already implied by the repo.

FallbackContext
    Dataclass carrying the full fallback event (from_level, to_level, reason,
    message, metadata).

TraceCorrelation
    Dataclass for trace-correlation fields: trace_id, runtime_session_id,
    optional task_id / action_id.

ExecutionEvent
    Top-level, serialisable event combining trace, executor-level, fallback,
    tri-state / domain context, and a human-readable message.

Normalizers (``core.execution_observability.normalizers``)
    Helper functions that convert raw dicts from the existing paths into the
    unified schemas above.
"""

from .executor_level import ExecutorLevel
from .fallback_schema import FallbackContext, FallbackReason
from .trace_schema import TraceCorrelation
from .event_schema import ExecutionEvent

__all__ = [
    "ExecutorLevel",
    "FallbackReason",
    "FallbackContext",
    "TraceCorrelation",
    "ExecutionEvent",
]
