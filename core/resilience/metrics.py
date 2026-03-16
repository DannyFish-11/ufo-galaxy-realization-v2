#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Resilience Metrics (PR-G5)
=====================================

Aggregated metrics for the resilience / protection layer:

  * Queue depth (from CommandRouter admission queue)
  * Rejection rate (requests turned away due to overload)
  * Fallback activations (circuit-breaker fallback invocations)
  * Circuit-breaker state per target
  * Adaptive-semaphore state

These metrics are exposed consistently with the G2 SLO/observability format
via :func:`get_resilience_metrics` (singleton) and rendered as either
Prometheus text or JSON by ``core/routes/resilience.py``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Resilience.Metrics")


class ResilienceMetrics:
    """Mutable, thread-safe container for resilience-layer metrics.

    All counters are monotonically increasing; gauges are point-in-time.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # ── Queue admission ──────────────────────────────────────────────
        self._queue_depth: int = 0
        self._queue_depth_max: int = 0
        self._total_accepted: int = 0
        self._total_rejected: int = 0    # admission rejections
        self._rejection_timestamps: List[float] = []  # rolling 60-s window

        # ── Fallback ─────────────────────────────────────────────────────
        self._total_fallbacks: int = 0

        # ── Circuit breaker ──────────────────────────────────────────────
        self._circuit_opens: int = 0     # cumulative opens across all targets

        # ── Initialisation time ──────────────────────────────────────────
        self._created_at: float = time.time()

    # ------------------------------------------------------------------
    # Queue depth
    # ------------------------------------------------------------------

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self._queue_depth = depth
            if depth > self._queue_depth_max:
                self._queue_depth_max = depth

    def record_accepted(self) -> None:
        with self._lock:
            self._total_accepted += 1

    def record_rejected(self) -> None:
        """Record one admission rejection and prune the rolling window."""
        now = time.time()
        with self._lock:
            self._total_rejected += 1
            self._rejection_timestamps.append(now)
            # Keep only last 60 s
            cutoff = now - 60.0
            self._rejection_timestamps = [
                t for t in self._rejection_timestamps if t >= cutoff
            ]

    # ------------------------------------------------------------------
    # Fallback / circuit breaker
    # ------------------------------------------------------------------

    def record_fallback(self) -> None:
        with self._lock:
            self._total_fallbacks += 1

    def record_circuit_open(self) -> None:
        with self._lock:
            self._circuit_opens += 1

    # ------------------------------------------------------------------
    # Snapshots
    # ------------------------------------------------------------------

    @property
    def rejection_rate_per_minute(self) -> float:
        """Rejections in the last 60 s (rolling window)."""
        with self._lock:
            return float(len(self._rejection_timestamps))

    def snapshot(self) -> Dict[str, Any]:
        """JSON-serialisable metrics snapshot (G2-compatible format)."""
        with self._lock:
            rate = float(len(self._rejection_timestamps))
            total = max(self._total_accepted + self._total_rejected, 1)
            return {
                "queue_depth": self._queue_depth,
                "queue_depth_max": self._queue_depth_max,
                "total_accepted": self._total_accepted,
                "total_rejected": self._total_rejected,
                "rejection_rate_per_min": round(rate, 2),
                "rejection_fraction": round(self._total_rejected / total, 4),
                "total_fallbacks": self._total_fallbacks,
                "total_circuit_opens": self._circuit_opens,
                "uptime_seconds": round(time.time() - self._created_at, 1),
            }

    def prometheus_text(self) -> str:
        """Prometheus text-exposition format (compatible with G2 /metrics)."""
        s = self.snapshot()
        lines = [
            "# HELP galaxy_resilience_queue_depth Current dispatch queue depth",
            "# TYPE galaxy_resilience_queue_depth gauge",
            f"galaxy_resilience_queue_depth {s['queue_depth']}",
            "# HELP galaxy_resilience_queue_depth_max Peak dispatch queue depth",
            "# TYPE galaxy_resilience_queue_depth_max gauge",
            f"galaxy_resilience_queue_depth_max {s['queue_depth_max']}",
            "# HELP galaxy_resilience_total_accepted_total Requests admitted to dispatch queue",
            "# TYPE galaxy_resilience_total_accepted_total counter",
            f"galaxy_resilience_total_accepted_total {s['total_accepted']}",
            "# HELP galaxy_resilience_total_rejected_total Requests rejected by admission control",
            "# TYPE galaxy_resilience_total_rejected_total counter",
            f"galaxy_resilience_total_rejected_total {s['total_rejected']}",
            "# HELP galaxy_resilience_rejection_rate_per_min Rejections in rolling 60-second window",
            "# TYPE galaxy_resilience_rejection_rate_per_min gauge",
            f"galaxy_resilience_rejection_rate_per_min {s['rejection_rate_per_min']}",
            "# HELP galaxy_resilience_total_fallbacks_total Fallback activations (circuit open)",
            "# TYPE galaxy_resilience_total_fallbacks_total counter",
            f"galaxy_resilience_total_fallbacks_total {s['total_fallbacks']}",
            "# HELP galaxy_resilience_total_circuit_opens_total Cumulative circuit-breaker open events",
            "# TYPE galaxy_resilience_total_circuit_opens_total counter",
            f"galaxy_resilience_total_circuit_opens_total {s['total_circuit_opens']}",
        ]
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_resilience_metrics: Optional[ResilienceMetrics] = None
_singleton_lock = threading.Lock()


def get_resilience_metrics() -> ResilienceMetrics:
    """Return the process-wide :class:`ResilienceMetrics` singleton."""
    global _resilience_metrics
    if _resilience_metrics is None:
        with _singleton_lock:
            if _resilience_metrics is None:
                _resilience_metrics = ResilienceMetrics()
    return _resilience_metrics
