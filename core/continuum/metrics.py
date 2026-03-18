"""
core.continuum.metrics — Lightweight Continuum Observability Metrics
====================================================================

Provides thread-safe in-process counters and latency timers for the
state continuum pipeline.  The implementation is intentionally minimal:
no external dependencies are required.  All operations degrade gracefully
to no-ops when metrics are not needed.

Public API
----------
ContinuumMetrics
    Process-level singleton holding counters and latency data.

get_continuum_metrics() → ContinuumMetrics
    Return (and lazily create) the process-level singleton.

ContinuumMetrics.record_tick(phase, elapsed_ms, degraded, skipped)
    Record a single evaluation tick with its outcome.

ContinuumMetrics.record_stage(stage_name, elapsed_ms, skipped)
    Record per-stage timing.

ContinuumMetrics.snapshot() → dict
    Return a serialisable dict of all current metric values.

ContinuumMetrics.reset()
    Zero all counters (useful between test cases).

Usage::

    from core.continuum.metrics import get_continuum_metrics

    m = get_continuum_metrics()
    m.record_tick(phase="liminal", elapsed_ms=12.4)
    snap = m.snapshot()
    print(snap["ticks_total"], snap["ticks_degraded"])
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

__all__ = [
    "ContinuumMetrics",
    "get_continuum_metrics",
]

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LATENCY_BUCKETS_MS: List[float] = [5, 10, 25, 50, 100, 250, 500, 1000]


class _LatencyTracker:
    """Thread-safe min/max/sum/count latency accumulator with fixed buckets."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._count: int = 0
        self._sum_ms: float = 0.0
        self._min_ms: float = float("inf")
        self._max_ms: float = 0.0
        self._buckets: Dict[str, int] = {f"le_{b}ms": 0 for b in _LATENCY_BUCKETS_MS}
        self._buckets["le_inf"] = 0

    def observe(self, latency_ms: float) -> None:
        with self._lock:
            self._count += 1
            self._sum_ms += latency_ms
            if latency_ms < self._min_ms:
                self._min_ms = latency_ms
            if latency_ms > self._max_ms:
                self._max_ms = latency_ms
            added = False
            for b in _LATENCY_BUCKETS_MS:
                key = f"le_{b}ms"
                if latency_ms <= b:
                    self._buckets[key] += 1
                    added = True
                    break
            if not added:
                self._buckets["le_inf"] += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "count": self._count,
                "sum_ms": round(self._sum_ms, 3),
                "avg_ms": round(self._sum_ms / self._count, 3) if self._count else 0.0,
                "min_ms": round(self._min_ms, 3) if self._count else 0.0,
                "max_ms": round(self._max_ms, 3),
                "buckets": dict(self._buckets),
            }

    def reset(self) -> None:
        with self._lock:
            self._count = 0
            self._sum_ms = 0.0
            self._min_ms = float("inf")
            self._max_ms = 0.0
            for key in self._buckets:
                self._buckets[key] = 0


# ---------------------------------------------------------------------------
# ContinuumMetrics
# ---------------------------------------------------------------------------


class ContinuumMetrics:
    """Thread-safe in-process counters and timers for the continuum pipeline.

    Counters
    --------
    ticks_total
        Number of times ``ContinuumOrchestrator.run()`` was called.
    ticks_degraded
        Number of ticks that returned a degraded formless state.
    ticks_skipped
        Number of ticks skipped by the sampling guardrail.
    ticks_budget_exceeded
        Number of ticks aborted because they exceeded ``max_tick_ms``.
    phases
        Per-phase tick counter dict (formless / liminal / manifest / receding).

    Latency
    -------
    tick_latency
        Full per-tick latency histogram (ms).
    stage_latency
        Per-stage latency histogram dict keyed by stage name.
    """

    _STAGES = (
        "perception",
        "human_field",
        "state_fusion",
        "liminal_field",
        "temporal_engine",
        "decision_gate",
        "expression_engine",
        "return_engine",
    )

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ticks_total: int = 0
        self._ticks_degraded: int = 0
        self._ticks_skipped: int = 0
        self._ticks_budget_exceeded: int = 0
        self._phases: Dict[str, int] = {
            "formless": 0,
            "liminal": 0,
            "manifest": 0,
            "receding": 0,
        }
        self._tick_latency = _LatencyTracker()
        self._stage_latency: Dict[str, _LatencyTracker] = {
            s: _LatencyTracker() for s in self._STAGES
        }

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_tick(
        self,
        *,
        phase: str = "formless",
        elapsed_ms: float = 0.0,
        degraded: bool = False,
        skipped: bool = False,
        budget_exceeded: bool = False,
    ) -> None:
        """Record a single completed (or skipped) continuum tick.

        Args:
            phase:           The phase of the resulting ``ContinuumState``.
            elapsed_ms:      Wall-clock time for the full tick (ms).
            degraded:        True when the tick returned a degraded state.
            skipped:         True when the tick was skipped by sampling.
            budget_exceeded: True when the tick exceeded ``max_tick_ms``.
        """
        with self._lock:
            self._ticks_total += 1
            if skipped:
                self._ticks_skipped += 1
                return
            if degraded:
                self._ticks_degraded += 1
            if budget_exceeded:
                self._ticks_budget_exceeded += 1
            self._phases[phase] = self._phases.get(phase, 0) + 1
        self._tick_latency.observe(elapsed_ms)

    def record_stage(
        self,
        stage_name: str,
        elapsed_ms: float,
        *,
        skipped: bool = False,
    ) -> None:
        """Record timing for one pipeline stage.

        Args:
            stage_name: Name matching one of ``_STAGES``.
            elapsed_ms: Wall-clock time for this stage (ms).
            skipped:    True if the stage was bypassed by a feature flag.
        """
        if skipped:
            return
        tracker = self._stage_latency.get(stage_name)
        if tracker is not None:
            tracker.observe(elapsed_ms)

    # ------------------------------------------------------------------
    # Snapshot / reset
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable dict of all current metric values."""
        with self._lock:
            phases = dict(self._phases)
            totals = {
                "ticks_total": self._ticks_total,
                "ticks_degraded": self._ticks_degraded,
                "ticks_skipped": self._ticks_skipped,
                "ticks_budget_exceeded": self._ticks_budget_exceeded,
            }
        return {
            **totals,
            "phases": phases,
            "tick_latency": self._tick_latency.snapshot(),
            "stage_latency": {
                name: tracker.snapshot()
                for name, tracker in self._stage_latency.items()
            },
        }

    def reset(self) -> None:
        """Zero all counters and latency data.  Useful between test cases."""
        with self._lock:
            self._ticks_total = 0
            self._ticks_degraded = 0
            self._ticks_skipped = 0
            self._ticks_budget_exceeded = 0
            for key in self._phases:
                self._phases[key] = 0
        self._tick_latency.reset()
        for tracker in self._stage_latency.values():
            tracker.reset()


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_singleton_lock = threading.Lock()
_singleton: Optional[ContinuumMetrics] = None


def get_continuum_metrics() -> ContinuumMetrics:
    """Return the process-level :class:`ContinuumMetrics` singleton.

    The singleton is created lazily on first call and reused thereafter.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = ContinuumMetrics()
    return _singleton
