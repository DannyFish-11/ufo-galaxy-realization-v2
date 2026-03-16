#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Adaptive Semaphore (PR-G5)
=====================================

An ``asyncio.Semaphore`` wrapper whose concurrency limit auto-adjusts based
on observed call latency and error rate using the AIMD (Additive Increase /
Multiplicative Decrease) algorithm popularised by TCP congestion control.

Algorithm
---------
* **Additive Increase**: every *probe_interval* seconds, if the recent p99
  latency is below *target_latency_ms* and the error rate is below
  *error_rate_threshold*, increment the limit by 1 (up to *max_limit*).
* **Multiplicative Decrease**: when a timeout or error burst occurs
  (error rate ≥ *error_rate_threshold*), halve the current limit
  (floor at *min_limit*).

Env vars (all optional)
-----------------------
``GALAXY_AS_INIT_LIMIT``        — initial concurrency limit (default 10)
``GALAXY_AS_MIN_LIMIT``         — floor (default 2)
``GALAXY_AS_MAX_LIMIT``         — ceiling (default 50)
``GALAXY_AS_TARGET_LATENCY_MS`` — target p99 latency in ms (default 500)
``GALAXY_AS_ERROR_THRESHOLD``   — error rate [0-1] that triggers decrease (default 0.2)
``GALAXY_AS_PROBE_INTERVAL_S``  — seconds between AIMD evaluations (default 10)
``GALAXY_AS_SAMPLE_WINDOW``     — number of recent samples used (default 100)
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import time
from typing import Dict, Any, List

logger = logging.getLogger("Galaxy.Resilience.AdaptiveSemaphore")

_INIT_LIMIT = int(os.environ.get("GALAXY_AS_INIT_LIMIT", "10"))
_MIN_LIMIT = int(os.environ.get("GALAXY_AS_MIN_LIMIT", "2"))
_MAX_LIMIT = int(os.environ.get("GALAXY_AS_MAX_LIMIT", "50"))
_TARGET_LATENCY_MS = float(os.environ.get("GALAXY_AS_TARGET_LATENCY_MS", "500"))
_ERROR_THRESHOLD = float(os.environ.get("GALAXY_AS_ERROR_THRESHOLD", "0.2"))
_PROBE_INTERVAL_S = float(os.environ.get("GALAXY_AS_PROBE_INTERVAL_S", "10"))
_SAMPLE_WINDOW = int(os.environ.get("GALAXY_AS_SAMPLE_WINDOW", "100"))


class AdaptiveSemaphore:
    """Concurrency semaphore whose limit adapts to observed latency and errors.

    Parameters
    ----------
    initial_limit, min_limit, max_limit:
        Concurrency bounds.
    target_latency_ms:
        Desired p99 call latency; exceeding it may trigger a decrease.
    error_rate_threshold:
        Fraction of recent calls that may fail before limit is decreased.
    probe_interval:
        Seconds between AIMD evaluations.
    sample_window:
        Number of recent observations used for p99 / error-rate estimates.
    """

    def __init__(
        self,
        initial_limit: int = _INIT_LIMIT,
        min_limit: int = _MIN_LIMIT,
        max_limit: int = _MAX_LIMIT,
        target_latency_ms: float = _TARGET_LATENCY_MS,
        error_rate_threshold: float = _ERROR_THRESHOLD,
        probe_interval: float = _PROBE_INTERVAL_S,
        sample_window: int = _SAMPLE_WINDOW,
    ) -> None:
        self._limit = max(min_limit, min(initial_limit, max_limit))
        self._min_limit = min_limit
        self._max_limit = max_limit
        self._target_latency_ms = target_latency_ms
        self._error_rate_threshold = error_rate_threshold
        self._probe_interval = probe_interval
        self._sample_window = sample_window

        self._semaphore = asyncio.Semaphore(self._limit)
        self._lock = asyncio.Lock()

        self._latency_samples: List[float] = []
        self._error_flags: List[int] = []   # 1 = error, 0 = ok
        self._last_probe: float = time.monotonic()

        self._total_acquired: int = 0
        self._total_adjustments: int = 0

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "AdaptiveSemaphore":
        await self._semaphore.acquire()
        self._total_acquired += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._semaphore.release()

    # ------------------------------------------------------------------
    # Record observation and trigger AIMD
    # ------------------------------------------------------------------

    async def record(self, latency_ms: float, *, error: bool = False) -> None:
        """Record a completed call and potentially adjust the limit."""
        async with self._lock:
            self._latency_samples.append(latency_ms)
            self._error_flags.append(1 if error else 0)
            if len(self._latency_samples) > self._sample_window:
                self._latency_samples = self._latency_samples[-self._sample_window:]
                self._error_flags = self._error_flags[-self._sample_window:]

            now = time.monotonic()
            if (now - self._last_probe) >= self._probe_interval:
                self._last_probe = now
                await self._aimd_evaluate()

    async def _aimd_evaluate(self) -> None:
        """AIMD adjustment — must be called under self._lock."""
        if not self._latency_samples:
            return

        p99 = self._percentile(self._latency_samples, 99)
        error_rate = sum(self._error_flags) / max(len(self._error_flags), 1)

        if error_rate >= self._error_rate_threshold or p99 > self._target_latency_ms:
            # Multiplicative decrease
            new_limit = max(self._min_limit, math.floor(self._limit / 2))
            if new_limit != self._limit:
                logger.warning(
                    "AdaptiveSemaphore: decreasing limit %d → %d "
                    "(p99=%.1fms error_rate=%.2f)",
                    self._limit, new_limit, p99, error_rate,
                )
                self._adjust_semaphore(new_limit)
                self._total_adjustments += 1
        else:
            # Additive increase
            new_limit = min(self._max_limit, self._limit + 1)
            if new_limit != self._limit:
                logger.debug(
                    "AdaptiveSemaphore: increasing limit %d → %d "
                    "(p99=%.1fms error_rate=%.2f)",
                    self._limit, new_limit, p99, error_rate,
                )
                self._adjust_semaphore(new_limit)
                self._total_adjustments += 1

    def _adjust_semaphore(self, new_limit: int) -> None:
        """Resize the underlying semaphore by adding/removing tokens."""
        delta = new_limit - self._limit
        if delta > 0:
            for _ in range(delta):
                self._semaphore.release()
        elif delta < 0:
            # We cannot "take back" tokens from an asyncio.Semaphore, so we
            # track the debt and prevent release() calls until balanced.
            # Simplest safe approach: recreate the semaphore.
            self._semaphore = asyncio.Semaphore(new_limit)
        self._limit = new_limit

    @staticmethod
    def _percentile(data: List[float], pct: int) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        idx = max(0, min(len(sorted_data) - 1, int(len(sorted_data) * pct / 100)))
        return sorted_data[idx]

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def current_limit(self) -> int:
        return self._limit

    @property
    def total_acquired(self) -> int:
        return self._total_acquired

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a metrics snapshot compatible with the G2 JSON format."""
        p99 = self._percentile(self._latency_samples, 99)
        p50 = self._percentile(self._latency_samples, 50)
        error_rate = sum(self._error_flags) / max(len(self._error_flags), 1)
        return {
            "current_limit": self._limit,
            "min_limit": self._min_limit,
            "max_limit": self._max_limit,
            "total_acquired": self._total_acquired,
            "total_adjustments": self._total_adjustments,
            "sample_count": len(self._latency_samples),
            "p50_latency_ms": round(p50, 2),
            "p99_latency_ms": round(p99, 2),
            "recent_error_rate": round(error_rate, 4),
            "target_latency_ms": self._target_latency_ms,
            "error_rate_threshold": self._error_rate_threshold,
        }
