"""
Galaxy - Structured Task Lifecycle Logger
==========================================

Provides :func:`emit_task_log`, a thin wrapper that emits a single-line JSON
log entry to the ``Galaxy.TaskLifecycle`` logger for every notable task event.

Supported *event* values (lifecycle):
  - ``task_received``   — task/request arrived at the top-level entry point
  - ``task_dispatched`` — task sent to a handler / device
  - ``task_completed``  — task finished successfully
  - ``task_failed``     — task ended with an error
  - ``task_cancelled``  — task was cancelled before or during execution
  - ``task_timeout``    — task exceeded its time budget
  - ``aggregation_done``— parallel subtask group aggregation finished

Callers should pass all available observability fields as keyword arguments::

    emit_task_log(
        "task_completed",
        task_id="goal_abc123",
        trace_id="req_xyz",
        device_id="phone_01",
        latency_ms=142.3,
        status="success",
    )

Metrics (TODO)
--------------
No metrics framework is currently present in the repository.  The stubs below
show where to hook in Prometheus / OpenTelemetry / statsd counters and
histograms once a framework is added.

  TODO[metrics]: Initialise counters and histograms, e.g.:
    from prometheus_client import Counter, Histogram
    _TASK_COUNTER = Counter(
        "galaxy_task_total", "Task lifecycle events",
        labelnames=["event", "task_type", "status"],
    )
    _LATENCY_HIST = Histogram(
        "galaxy_task_latency_ms", "Task end-to-end latency in ms",
        labelnames=["task_type"],
        buckets=[10, 50, 100, 250, 500, 1000, 5000, 30000],
    )

  TODO[metrics]: Inside emit_task_log(), record metrics, e.g.:
    _TASK_COUNTER.labels(
        event=event,
        task_type=fields.get("task_type", ""),
        status=fields.get("status", ""),
    ).inc()
    if "latency_ms" in fields:
        _LATENCY_HIST.labels(task_type=fields.get("task_type", "")).observe(
            fields["latency_ms"]
        )
"""

import json
import logging
import time
from typing import Any

_task_logger = logging.getLogger("Galaxy.TaskLifecycle")


def emit_task_log(event: str, **fields: Any) -> None:
    """Emit a structured JSON log entry for a task lifecycle *event*.

    The entry always contains ``event`` and ``ts`` (Unix timestamp).  All
    additional keyword arguments are merged into the entry as-is.

    Example output (one line)::

        {"event": "task_completed", "ts": 1700000000.123, "task_id": "goal_abc",
         "trace_id": "req_xyz", "device_id": "dev1", "latency_ms": 84.2,
         "status": "success", "task_type": "goal_execution"}
    """
    entry: dict = {"event": event, "ts": time.time()}
    entry.update(fields)
    _task_logger.info(json.dumps(entry, ensure_ascii=False, default=str))

    # TODO[metrics]: Record counter / histogram here once a metrics framework
    # (prometheus_client, opentelemetry, statsd, …) is available.
    # See module-level docstring for sample code.
