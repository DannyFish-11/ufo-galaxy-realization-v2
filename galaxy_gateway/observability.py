"""
Gateway Observability — Round 7
================================

Provides end-to-end trace propagation, structured JSON logging, and in-process
Prometheus-compatible metrics for the cross-device pipeline:

    gateway → dispatcher / device_router → agent_bridge / runtime ↔ Android client

Public API
----------
TraceContext
    Immutable (trace_id, span_id) pair.  ``new()`` generates fresh IDs;
    ``from_message()`` extracts IDs from an incoming dict, generating any that
    are missing.

emit_gateway_log(event, *, trace_ctx, **fields)
    Emit a single-line JSON log entry to the ``Galaxy.Gateway`` logger.
    Respects the configured sampling rate so verbose paths don't flood logs.

GatewayMetrics
    Thread-safe, in-process counters and latency histograms.
    ``get_gateway_metrics()`` returns the process-level singleton.

prometheus_text()
    Render the current GatewayMetrics as Prometheus text-format exposition,
    suitable for appending to ``/metrics`` or ``/health/metrics`` responses.

Sampling
--------
Set ``GALAXY_TRACE_SAMPLE_RATE`` (float 0.0–1.0, default ``1.0``) to sub-sample
verbose trace log entries.  A value of ``0.1`` means ~10 % of eligible log
calls are written; ``1.0`` (default) writes all.  Error / warning events are
*always* written regardless of the sample rate.

Environment variables
---------------------
GALAXY_TRACE_SAMPLE_RATE   Fraction of trace log entries to write (default 1.0)
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

_gateway_logger = logging.getLogger("Galaxy.Gateway")

# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------

def _get_sample_rate() -> float:
    """Read the configured trace sample rate from the environment (0.0–1.0)."""
    try:
        rate = float(os.getenv("GALAXY_TRACE_SAMPLE_RATE", "1.0"))
        return max(0.0, min(1.0, rate))
    except (TypeError, ValueError):
        return 1.0


def _should_sample(*, always: bool = False) -> bool:
    """Return True if this log entry should be emitted."""
    if always:
        return True
    rate = _get_sample_rate()
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    return random.random() < rate


# ---------------------------------------------------------------------------
# TraceContext
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TraceContext:
    """Immutable (trace_id, span_id) pair for one request hop.

    Fields
    ------
    trace_id
        UUID4 string that is stable across the entire request lifetime.
        Propagated from ingress to egress across all hops.
    span_id
        UUID4 string that is unique per gateway processing span.
        A new span_id is generated at each hop; the trace_id stays the same.
    """

    trace_id: str
    span_id: str

    @classmethod
    def new(cls) -> "TraceContext":
        """Generate a brand-new trace/span pair."""
        return cls(trace_id=str(uuid.uuid4()), span_id=str(uuid.uuid4()))

    @classmethod
    def from_message(cls, msg: Dict[str, Any]) -> "TraceContext":
        """Extract trace context from an incoming dict, generating missing IDs.

        Accepts both ``trace_id`` / ``span_id`` keys (canonical) and the
        ``x-trace-id`` / ``x-span-id`` header-style variants.
        """
        trace_id = (
            msg.get("trace_id")
            or msg.get("x-trace-id")
            or msg.get("traceId")
            or str(uuid.uuid4())
        )
        span_id = str(uuid.uuid4())  # always a fresh span at the gateway
        return cls(trace_id=str(trace_id), span_id=span_id)

    def child_span(self) -> "TraceContext":
        """Return a new TraceContext with the same trace_id and a fresh span_id."""
        return TraceContext(trace_id=self.trace_id, span_id=str(uuid.uuid4()))

    def to_dict(self) -> Dict[str, str]:
        return {"trace_id": self.trace_id, "span_id": self.span_id}


# ---------------------------------------------------------------------------
# Structured logging
# ---------------------------------------------------------------------------

#: Events that are *always* written (bypass sampling).
_ALWAYS_LOG_EVENTS: frozenset = frozenset({
    "signaling_error",
    "signaling_timeout",
    "bridge_handoff_failed",
    "bridge_fallback",
    "routing_failed",
    "turn_fallback",
    "node95_unreachable",
    "cross_device_blocked",
    "trace_id_injected",
    "span_id_injected",
})


def emit_gateway_log(
    event: str,
    *,
    trace_ctx: Optional[TraceContext] = None,
    level: str = "info",
    **fields: Any,
) -> None:
    """Emit a single-line JSON log entry to ``Galaxy.Gateway``.

    Parameters
    ----------
    event:
        Machine-readable event name (snake_case), e.g. ``"signaling_start"``.
    trace_ctx:
        TraceContext carrying trace_id and span_id.  When provided its fields
        are merged into the log entry automatically.
    level:
        Log level: ``"debug"`` | ``"info"`` | ``"warning"`` | ``"error"``.
        Error/warning entries always bypass the sample-rate filter.
    **fields:
        Arbitrary key-value pairs merged into the JSON entry.
    """
    always = (event in _ALWAYS_LOG_EVENTS) or level in ("warning", "error")
    if not _should_sample(always=always):
        return

    entry: Dict[str, Any] = {"event": event, "ts": time.time()}
    if trace_ctx is not None:
        entry["trace_id"] = trace_ctx.trace_id
        entry["span_id"] = trace_ctx.span_id
    entry.update(fields)

    log_line = json.dumps(entry, ensure_ascii=False, default=str)

    log_fn = {
        "debug": _gateway_logger.debug,
        "warning": _gateway_logger.warning,
        "error": _gateway_logger.error,
    }.get(level, _gateway_logger.info)
    log_fn(log_line)


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class _LatencyHistogram:
    """Simple fixed-bucket latency histogram (thread-safe)."""

    # Default bucket boundaries in milliseconds
    _DEFAULT_BUCKETS_MS: Sequence[float] = (
        10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 30000
    )

    def __init__(self, buckets_ms: Optional[Sequence[float]] = None) -> None:
        self._buckets: List[float] = sorted(
            buckets_ms if buckets_ms is not None else self._DEFAULT_BUCKETS_MS
        )
        self._lock = threading.Lock()
        self._counts: List[int] = [0] * len(self._buckets)
        self._inf_count: int = 0
        self._sum_ms: float = 0.0
        self._total: int = 0

    def observe(self, latency_ms: float) -> None:
        with self._lock:
            self._sum_ms += latency_ms
            self._total += 1
            added = False
            for i, boundary in enumerate(self._buckets):
                if latency_ms <= boundary:
                    self._counts[i] += 1
                    added = True
                    break
            if not added:
                self._inf_count += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            buckets = {
                f"le_{b}ms": c
                for b, c in zip(self._buckets, self._counts)
            }
            buckets["le_inf"] = self._inf_count
            return {
                "count": self._total,
                "sum_ms": round(self._sum_ms, 3),
                "avg_ms": round(self._sum_ms / self._total, 3) if self._total else 0.0,
                "buckets": buckets,
            }

    def to_prometheus_lines(self, metric_name: str, help_text: str, labels: str = "") -> List[str]:
        """Render as Prometheus text format lines.

        Parameters
        ----------
        metric_name:
            Base metric name (e.g. ``"galaxy_gateway_signaling_latency_ms"``).
        help_text:
            Human-readable description for the ``# HELP`` line.
        labels:
            Optional pre-formatted label string to prepend inside ``{}``,
            e.g. ``'route_mode="cross_device"'``.  When empty no extra labels
            are added.  The ``le`` label is always appended automatically.
        """
        lines: List[str] = [
            f"# HELP {metric_name} {help_text}",
            f"# TYPE {metric_name} histogram",
        ]
        with self._lock:
            cumulative = 0
            for boundary, count in zip(self._buckets, self._counts):
                cumulative += count
                label_str = f'le="{boundary}"'
                if labels:
                    label_str = f"{labels},{label_str}"
                lines.append(f'{metric_name}_bucket{{{label_str}}} {cumulative}')
            # +Inf bucket
            cumulative += self._inf_count
            inf_label = 'le="+Inf"'
            if labels:
                inf_label = f"{labels},{inf_label}"
            lines.append(f'{metric_name}_bucket{{{inf_label}}} {cumulative}')
            lines.append(f"{metric_name}_sum {self._sum_ms:.3f}")
            lines.append(f"{metric_name}_count {self._total}")
        return lines


class GatewayMetrics:
    """In-process counters and latency histograms for the gateway pipeline.

    All attributes are thread-safe (protected by individual locks or atomic
    integer operations via Python's GIL for simple increments).

    Counters
    --------
    signaling_total           Total WebRTC signaling sessions started.
    signaling_success         Sessions that completed without error/timeout.
    signaling_failure         Sessions that ended with error or timeout.
    signaling_timeout         Subset of failures due to timeout specifically.
    turn_fallback_total       Times TURN relay candidates were used as fallback.
    candidate_retry_total     ICE candidate retry / re-attempt events.
    bridge_handoff_total      Agent bridge handoff attempts.
    bridge_handoff_success    Successful handoffs to the runtime.
    bridge_handoff_failure    Failed handoffs (runtime unreachable / timeout).
    bridge_fallback_total     Times the bridge fell back to local execution.
    routing_total             Total task routing attempts.
    routing_success           Successful task routings.
    routing_failure           Failed task routings.

    Histograms
    ----------
    signaling_latency_ms      Latency histogram for completed signaling sessions.
    bridge_latency_ms         Latency histogram for agent bridge handoff calls.
    routing_latency_ms        Latency histogram for full route_task() calls.
    """

    def __init__(self) -> None:
        # --- counters ---
        self._lock = threading.Lock()
        self.signaling_total: int = 0
        self.signaling_success: int = 0
        self.signaling_failure: int = 0
        self.signaling_timeout: int = 0
        self.turn_fallback_total: int = 0
        self.candidate_retry_total: int = 0
        self.bridge_handoff_total: int = 0
        self.bridge_handoff_success: int = 0
        self.bridge_handoff_failure: int = 0
        self.bridge_fallback_total: int = 0
        self.routing_total: int = 0
        self.routing_success: int = 0
        self.routing_failure: int = 0

        # --- histograms ---
        self.signaling_latency_ms = _LatencyHistogram()
        self.bridge_latency_ms = _LatencyHistogram()
        self.routing_latency_ms = _LatencyHistogram()

    # ------------------------------------------------------------------
    # Convenience increment helpers
    # ------------------------------------------------------------------

    def inc(self, counter: str, delta: int = 1) -> None:
        """Increment a named counter by *delta* (thread-safe)."""
        with self._lock:
            current = getattr(self, counter, 0)
            setattr(self, counter, current + delta)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all metrics."""
        with self._lock:
            return {
                "signaling": {
                    "total": self.signaling_total,
                    "success": self.signaling_success,
                    "failure": self.signaling_failure,
                    "timeout": self.signaling_timeout,
                    "turn_fallback": self.turn_fallback_total,
                    "candidate_retry": self.candidate_retry_total,
                    "latency_ms": self.signaling_latency_ms.snapshot(),
                },
                "bridge": {
                    "handoff_total": self.bridge_handoff_total,
                    "handoff_success": self.bridge_handoff_success,
                    "handoff_failure": self.bridge_handoff_failure,
                    "fallback_total": self.bridge_fallback_total,
                    "latency_ms": self.bridge_latency_ms.snapshot(),
                },
                "routing": {
                    "total": self.routing_total,
                    "success": self.routing_success,
                    "failure": self.routing_failure,
                    "latency_ms": self.routing_latency_ms.snapshot(),
                },
            }

    def prometheus_text(self) -> str:
        """Render metrics as Prometheus text-format exposition string."""
        lines: List[str] = []

        def _counter(name: str, help_text: str, value: int) -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        with self._lock:
            _counter("galaxy_gateway_signaling_total",
                     "Total WebRTC signaling sessions started",
                     self.signaling_total)
            _counter("galaxy_gateway_signaling_success_total",
                     "WebRTC signaling sessions completed successfully",
                     self.signaling_success)
            _counter("galaxy_gateway_signaling_failure_total",
                     "WebRTC signaling sessions ended with error or timeout",
                     self.signaling_failure)
            _counter("galaxy_gateway_signaling_timeout_total",
                     "WebRTC signaling sessions timed out",
                     self.signaling_timeout)
            _counter("galaxy_gateway_turn_fallback_total",
                     "Times TURN relay was used as ICE fallback",
                     self.turn_fallback_total)
            _counter("galaxy_gateway_candidate_retry_total",
                     "ICE candidate retry events",
                     self.candidate_retry_total)
            _counter("galaxy_gateway_bridge_handoff_total",
                     "Agent bridge handoff attempts",
                     self.bridge_handoff_total)
            _counter("galaxy_gateway_bridge_handoff_success_total",
                     "Agent bridge successful handoffs",
                     self.bridge_handoff_success)
            _counter("galaxy_gateway_bridge_handoff_failure_total",
                     "Agent bridge failed handoffs",
                     self.bridge_handoff_failure)
            _counter("galaxy_gateway_bridge_fallback_total",
                     "Agent bridge fallbacks to local execution",
                     self.bridge_fallback_total)
            _counter("galaxy_gateway_routing_total",
                     "Task routing attempts",
                     self.routing_total)
            _counter("galaxy_gateway_routing_success_total",
                     "Successful task routings",
                     self.routing_success)
            _counter("galaxy_gateway_routing_failure_total",
                     "Failed task routings",
                     self.routing_failure)

        lines.extend(self.signaling_latency_ms.to_prometheus_lines(
            "galaxy_gateway_signaling_latency_ms",
            "WebRTC signaling session latency in milliseconds",
        ))
        lines.extend(self.bridge_latency_ms.to_prometheus_lines(
            "galaxy_gateway_bridge_latency_ms",
            "Agent bridge handoff latency in milliseconds",
        ))
        lines.extend(self.routing_latency_ms.to_prometheus_lines(
            "galaxy_gateway_routing_latency_ms",
            "Task routing latency in milliseconds",
        ))

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_gateway_metrics: Optional[GatewayMetrics] = None
_metrics_lock = threading.Lock()


def get_gateway_metrics() -> GatewayMetrics:
    """Return the process-level :class:`GatewayMetrics` singleton."""
    global _gateway_metrics
    if _gateway_metrics is None:
        with _metrics_lock:
            if _gateway_metrics is None:
                _gateway_metrics = GatewayMetrics()
    return _gateway_metrics
