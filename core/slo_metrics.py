"""
core/slo_metrics.py — Galaxy SLO Metrics  (PR-G2)
====================================================

Exposes runtime SLO indicators for health_monitor / system_manager:

  - Startup duration (ms)          — time from process start to first ready
  - Heartbeat loss rate            — rolling fraction of failed heartbeat checks
  - Reconnect attempts total       — cumulative restarts triggered by unhealthy nodes
  - Command latency p50 / p95 (ms) — rolling percentiles over recent health-check
                                      round-trip latencies

All attributes are thread-safe.  No external dependencies beyond the stdlib.

Public API
----------
get_slo_metrics() -> SLOMetrics
    Return the process-level singleton.

SLOMetrics
    .record_startup(duration_ms)
    .record_heartbeat(success: bool)
    .record_reconnect(node_id: str = "")
    .record_command_latency(latency_ms: float)

    .heartbeat_loss_rate -> float          (0.0 – 1.0)
    .command_latency_p50 -> float          (ms, NaN when no data)
    .command_latency_p95 -> float          (ms, NaN when no data)

    .snapshot() -> dict
    .prometheus_text() -> str

Environment variables
---------------------
GALAXY_SLO_LATENCY_WINDOW   Max latency samples kept for percentile calc
                             (default 1000).
GALAXY_SLO_HEARTBEAT_WINDOW Max heartbeat results kept for loss-rate calc
                             (default 200).
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(sorted_samples: List[float], pct: float) -> float:
    """Compute *pct*-th percentile (0-100) from a *sorted* list.

    Returns ``math.nan`` when the list is empty.
    Uses the nearest-rank method.
    """
    n = len(sorted_samples)
    if n == 0:
        return math.nan
    # nearest-rank index (1-based); min(index, n) guards against floating-point
    # edge cases where ceil rounds exactly to n+1 (should not happen for valid
    # 0-100 percentile inputs, but is cheap defensive programming).
    index = max(1, math.ceil(pct / 100.0 * n))
    return sorted_samples[min(index, n) - 1]


# ---------------------------------------------------------------------------
# SLOMetrics
# ---------------------------------------------------------------------------

class SLOMetrics:
    """Thread-safe in-process SLO metric collector.

    Parameters
    ----------
    latency_window:
        Maximum number of command-latency samples retained for percentile
        computation.  Older samples are discarded (FIFO).
    heartbeat_window:
        Maximum number of heartbeat results (bool) retained for loss-rate
        computation.  Older results are discarded (FIFO).
    """

    def __init__(
        self,
        latency_window: int = 1000,
        heartbeat_window: int = 200,
    ) -> None:
        self._lock = threading.Lock()

        # --- startup ---
        self._startup_duration_ms: Optional[float] = None
        self._startup_recorded_at: Optional[float] = None

        # --- heartbeat ---
        self._heartbeat_results: Deque[bool] = deque(maxlen=heartbeat_window)
        self._heartbeat_total: int = 0
        self._heartbeat_failures: int = 0

        # --- reconnect ---
        self._reconnect_total: int = 0

        # --- command latency ---
        self._latency_samples: Deque[float] = deque(maxlen=latency_window)

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_startup(self, duration_ms: float) -> None:
        """Record how long the system took to reach the 'ready' state.

        Only the **first** call has effect; subsequent calls are no-ops so
        that partial re-initialisations do not clobber the original value.
        """
        with self._lock:
            if self._startup_duration_ms is None:
                self._startup_duration_ms = max(0.0, float(duration_ms))
                self._startup_recorded_at = time.time()

    def record_heartbeat(self, success: bool) -> None:
        """Record one heartbeat check result.

        Parameters
        ----------
        success:
            ``True`` if the node/service responded within the deadline,
            ``False`` if it failed or timed out.
        """
        with self._lock:
            self._heartbeat_results.append(success)
            self._heartbeat_total += 1
            if not success:
                self._heartbeat_failures += 1

    def record_reconnect(self, node_id: str = "") -> None:
        """Increment the reconnect-attempt counter.

        Parameters
        ----------
        node_id:
            Optional identifier of the node being reconnected (for future
            per-node breakdowns; currently only the aggregate counter is kept).
        """
        with self._lock:
            self._reconnect_total += 1

    def record_command_latency(self, latency_ms: float) -> None:
        """Append one command round-trip latency observation (in ms)."""
        with self._lock:
            self._latency_samples.append(float(latency_ms))

    # ------------------------------------------------------------------
    # Computed properties
    # ------------------------------------------------------------------

    @property
    def startup_duration_ms(self) -> Optional[float]:
        """Startup duration in milliseconds, or ``None`` if not yet recorded."""
        with self._lock:
            return self._startup_duration_ms

    @property
    def heartbeat_loss_rate(self) -> float:
        """Fraction of recent heartbeat checks that failed (0.0 – 1.0).

        Computed from the rolling window of the most recent
        ``heartbeat_window`` results.  Returns ``0.0`` when no checks have
        been recorded yet.
        """
        with self._lock:
            total = len(self._heartbeat_results)
            if total == 0:
                return 0.0
            failures = sum(1 for r in self._heartbeat_results if not r)
            return failures / total

    @property
    def reconnect_total(self) -> int:
        """Cumulative number of reconnect attempts since process start."""
        with self._lock:
            return self._reconnect_total

    @property
    def command_latency_p50(self) -> float:
        """50th-percentile command latency (ms) over the rolling window.

        Returns ``math.nan`` when no samples have been recorded.
        """
        with self._lock:
            if not self._latency_samples:
                return math.nan
            sorted_s = sorted(self._latency_samples)
        return _percentile(sorted_s, 50.0)

    @property
    def command_latency_p95(self) -> float:
        """95th-percentile command latency (ms) over the rolling window.

        Returns ``math.nan`` when no samples have been recorded.
        """
        with self._lock:
            if not self._latency_samples:
                return math.nan
            sorted_s = sorted(self._latency_samples)
        return _percentile(sorted_s, 95.0)

    # ------------------------------------------------------------------
    # Snapshot / export
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all SLO metrics."""
        p50 = self.command_latency_p50
        p95 = self.command_latency_p95
        with self._lock:
            hb_total = self._heartbeat_total
            hb_failures = self._heartbeat_failures
            latency_count = len(self._latency_samples)
        return {
            "startup": {
                "duration_ms": self._startup_duration_ms,
                "recorded_at": self._startup_recorded_at,
            },
            "heartbeat": {
                "total": hb_total,
                "failures": hb_failures,
                "loss_rate": round(self.heartbeat_loss_rate, 6),
            },
            "reconnect": {
                "attempts_total": self.reconnect_total,
            },
            "command_latency": {
                "sample_count": latency_count,
                "p50_ms": None if math.isnan(p50) else round(p50, 3),
                "p95_ms": None if math.isnan(p95) else round(p95, 3),
            },
        }

    def prometheus_text(self) -> str:
        """Render SLO metrics as a Prometheus text-format exposition string."""
        lines: List[str] = []

        def _gauge(name: str, help_text: str, value: Optional[float]) -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value if value is not None else 'NaN'}")

        def _counter(name: str, help_text: str, value: int) -> None:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        # startup
        _gauge(
            "galaxy_slo_startup_duration_ms",
            "System startup duration in milliseconds (set once at first ready state)",
            self._startup_duration_ms,
        )

        # heartbeat
        with self._lock:
            hb_total = self._heartbeat_total
            hb_failures = self._heartbeat_failures
        _counter(
            "galaxy_slo_heartbeat_total",
            "Total heartbeat checks performed",
            hb_total,
        )
        _counter(
            "galaxy_slo_heartbeat_failure_total",
            "Total heartbeat checks that failed or timed out",
            hb_failures,
        )
        _gauge(
            "galaxy_slo_heartbeat_loss_rate",
            "Fraction of recent heartbeat checks that failed (rolling window, 0.0-1.0)",
            round(self.heartbeat_loss_rate, 6),
        )

        # reconnect
        _counter(
            "galaxy_slo_reconnect_attempts_total",
            "Cumulative number of node reconnect/restart attempts",
            self.reconnect_total,
        )

        # command latency
        p50 = self.command_latency_p50
        p95 = self.command_latency_p95
        with self._lock:
            latency_count = len(self._latency_samples)
        _gauge(
            "galaxy_slo_command_latency_p50_ms",
            "50th-percentile command round-trip latency in milliseconds (rolling window)",
            None if math.isnan(p50) else round(p50, 3),
        )
        _gauge(
            "galaxy_slo_command_latency_p95_ms",
            "95th-percentile command round-trip latency in milliseconds (rolling window)",
            None if math.isnan(p95) else round(p95, 3),
        )
        _gauge(
            "galaxy_slo_command_latency_sample_count",
            "Number of command latency samples currently in the rolling window",
            float(latency_count),
        )

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_slo_metrics: Optional[SLOMetrics] = None
_slo_lock = threading.Lock()


def get_slo_metrics() -> SLOMetrics:
    """Return the process-level :class:`SLOMetrics` singleton.

    The singleton is created lazily on first access.  Window sizes are
    read from environment variables at creation time:

    ``GALAXY_SLO_LATENCY_WINDOW``   (default 1000)
    ``GALAXY_SLO_HEARTBEAT_WINDOW`` (default 200)
    """
    global _slo_metrics
    if _slo_metrics is None:
        with _slo_lock:
            if _slo_metrics is None:
                latency_window = int(os.getenv("GALAXY_SLO_LATENCY_WINDOW", "1000"))
                heartbeat_window = int(os.getenv("GALAXY_SLO_HEARTBEAT_WINDOW", "200"))
                _slo_metrics = SLOMetrics(
                    latency_window=latency_window,
                    heartbeat_window=heartbeat_window,
                )
    return _slo_metrics
