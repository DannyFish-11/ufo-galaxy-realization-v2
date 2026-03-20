#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/unified/device_health.py
================================
Block-4 (PR-4) — Device Health Scoring

Provides :class:`DeviceHealthScorer` which computes a composite health score
for each registered device based on:

- **Latency** (ms) — lower is better.
- **Error rate** (0–1 fraction) — lower is better.
- **Jitter** (ms) — lower is better.
- **Heartbeat stability** (0–1 fraction) — higher is better.

The composite :attr:`HealthScore.total_score` is in the range ``[0.0, 1.0]``
and is used by :class:`~core.unified.device_manager.UnifiedDeviceManager` and
routing layers to prefer healthy devices.

Integration
-----------
- :meth:`DeviceHealthScorer.update` is called from heartbeat handlers and
  command-result callbacks.
- :meth:`DeviceHealthScorer.score` is called by the
  :class:`~core.mesh.device_role_allocator.DeviceRoleAllocator` and any routing
  logic that needs to rank devices.
- Scores are also exposed via dashboard APIs added in Block-4.

Usage::

    from core.unified.device_health import DeviceHealthScorer

    scorer = DeviceHealthScorer()
    scorer.update("android_01", latency_ms=45.0, error=False)
    scorer.update("android_01", latency_ms=50.0, error=False)

    hs = scorer.score("android_01")
    print(hs.total_score)  # e.g. 0.87
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("Galaxy.Unified.DeviceHealth")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_WINDOW = 20          # Samples kept per device
_LATENCY_GOOD_MS = 50.0       # Latency ≤ this is scored as 1.0
_LATENCY_BAD_MS  = 2000.0     # Latency ≥ this is scored as 0.0
_JITTER_GOOD_MS  = 20.0       # Jitter ≤ this is scored as 1.0
_JITTER_BAD_MS   = 500.0      # Jitter ≥ this is scored as 0.0

# Component weights (must sum to 1.0)
_W_LATENCY    = 0.35
_W_ERROR_RATE = 0.30
_W_JITTER     = 0.20
_W_HEARTBEAT  = 0.15


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class HealthScore:
    """Composite health score for a single device.

    Attributes
    ----------
    device_id:
        Device identifier.
    total_score:
        Weighted composite score in ``[0.0, 1.0]``.  Higher = healthier.
    latency_score:
        Latency component score.
    error_rate_score:
        Error rate component score.
    jitter_score:
        Jitter component score.
    heartbeat_score:
        Heartbeat stability component score.
    sample_count:
        Number of data points used to compute this score.
    computed_at:
        Unix timestamp of computation.
    """

    device_id: str
    total_score: float = 1.0
    latency_score: float = 1.0
    error_rate_score: float = 1.0
    jitter_score: float = 1.0
    heartbeat_score: float = 1.0
    sample_count: int = 0
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "total_score": round(self.total_score, 4),
            "latency_score": round(self.latency_score, 4),
            "error_rate_score": round(self.error_rate_score, 4),
            "jitter_score": round(self.jitter_score, 4),
            "heartbeat_score": round(self.heartbeat_score, 4),
            "sample_count": self.sample_count,
            "computed_at": self.computed_at,
        }


@dataclass
class _DeviceSamples:
    """Internal sample buffer for one device."""

    latencies: Deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))
    errors: Deque[bool] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))
    heartbeat_timestamps: Deque[float] = field(default_factory=lambda: deque(maxlen=_DEFAULT_WINDOW))
    last_seen: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# DeviceHealthScorer
# ---------------------------------------------------------------------------


class DeviceHealthScorer:
    """Computes composite health scores for Galaxy devices.

    This is a **process-level singleton** accessed via
    :func:`get_device_health_scorer`.

    Thread safety: all public methods acquire a per-device lock.
    """

    def __init__(self, window: int = _DEFAULT_WINDOW) -> None:
        self._window = window
        self._samples: Dict[str, _DeviceSamples] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def update(
        self,
        device_id: str,
        latency_ms: Optional[float] = None,
        error: bool = False,
        heartbeat: bool = False,
    ) -> None:
        """Record a new observation for *device_id*.

        Args:
            device_id:   Target device.
            latency_ms:  Round-trip latency in milliseconds (if measured).
            error:       ``True`` if this observation represents a failure.
            heartbeat:   ``True`` if this observation is a heartbeat ping.
        """
        with self._lock:
            s = self._samples.setdefault(device_id, _DeviceSamples())
            s.last_seen = time.time()
            if latency_ms is not None:
                s.latencies.append(float(latency_ms))
            s.errors.append(error)
            if heartbeat:
                s.heartbeat_timestamps.append(time.time())

    def heartbeat(self, device_id: str, latency_ms: Optional[float] = None) -> None:
        """Convenience method to record a heartbeat event.

        Equivalent to calling :meth:`update` with ``heartbeat=True``.
        """
        self.update(device_id, latency_ms=latency_ms, heartbeat=True)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score(self, device_id: str) -> HealthScore:
        """Compute the health score for *device_id*.

        Devices with no samples receive a neutral score of 1.0 (optimistic
        default — benefit of the doubt until data arrives).

        Args:
            device_id:  Target device.

        Returns:
            :class:`HealthScore` with all component scores and the
            composite ``total_score``.
        """
        with self._lock:
            s = self._samples.get(device_id)

        if s is None or (not s.latencies and not s.errors):
            return HealthScore(device_id=device_id, total_score=1.0, sample_count=0)

        sample_count = max(len(s.latencies), len(s.errors))

        # Component: latency
        latency_score = self._score_latency(s)

        # Component: error rate
        error_rate_score = self._score_error_rate(s)

        # Component: jitter
        jitter_score = self._score_jitter(s)

        # Component: heartbeat stability
        heartbeat_score = self._score_heartbeat(s)

        total = (
            _W_LATENCY    * latency_score
            + _W_ERROR_RATE * error_rate_score
            + _W_JITTER     * jitter_score
            + _W_HEARTBEAT  * heartbeat_score
        )
        total = max(0.0, min(1.0, total))

        hs = HealthScore(
            device_id=device_id,
            total_score=round(total, 4),
            latency_score=round(latency_score, 4),
            error_rate_score=round(error_rate_score, 4),
            jitter_score=round(jitter_score, 4),
            heartbeat_score=round(heartbeat_score, 4),
            sample_count=sample_count,
        )
        logger.debug(
            "DeviceHealthScorer: device=%s score=%.3f latency=%.3f error=%.3f "
            "jitter=%.3f heartbeat=%.3f",
            device_id,
            hs.total_score,
            hs.latency_score,
            hs.error_rate_score,
            hs.jitter_score,
            hs.heartbeat_score,
        )
        return hs

    def score_all(self) -> Dict[str, HealthScore]:
        """Return health scores for all known devices."""
        with self._lock:
            device_ids = list(self._samples.keys())
        return {did: self.score(did) for did in device_ids}

    # ------------------------------------------------------------------
    # Component scorers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_latency(s: _DeviceSamples) -> float:
        if not s.latencies:
            return 1.0
        avg = sum(s.latencies) / len(s.latencies)
        if avg <= _LATENCY_GOOD_MS:
            return 1.0
        if avg >= _LATENCY_BAD_MS:
            return 0.0
        # Logarithmic interpolation
        return 1.0 - math.log(avg / _LATENCY_GOOD_MS) / math.log(
            _LATENCY_BAD_MS / _LATENCY_GOOD_MS
        )

    @staticmethod
    def _score_error_rate(s: _DeviceSamples) -> float:
        if not s.errors:
            return 1.0
        rate = sum(1 for e in s.errors if e) / len(s.errors)
        return max(0.0, 1.0 - rate)

    @staticmethod
    def _score_jitter(s: _DeviceSamples) -> float:
        if len(s.latencies) < 2:
            return 1.0
        latencies = list(s.latencies)
        diffs = [abs(latencies[i] - latencies[i - 1]) for i in range(1, len(latencies))]
        jitter = sum(diffs) / len(diffs)
        if jitter <= _JITTER_GOOD_MS:
            return 1.0
        if jitter >= _JITTER_BAD_MS:
            return 0.0
        return 1.0 - (jitter - _JITTER_GOOD_MS) / (_JITTER_BAD_MS - _JITTER_GOOD_MS)

    @staticmethod
    def _score_heartbeat(s: _DeviceSamples) -> float:
        if len(s.heartbeat_timestamps) < 2:
            return 1.0
        timestamps = sorted(s.heartbeat_timestamps)
        intervals = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]
        avg_interval = sum(intervals) / len(intervals)
        if avg_interval <= 0:
            return 0.0
        # Coefficient of variation — lower = more stable
        if len(intervals) < 2:
            return 1.0
        variance = sum((x - avg_interval) ** 2 for x in intervals) / len(intervals)
        std = math.sqrt(variance)
        cv = std / avg_interval if avg_interval > 0 else 1.0
        return max(0.0, 1.0 - min(cv, 1.0))

    # ------------------------------------------------------------------
    # Snapshot / reset
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of all health scores."""
        scores = self.score_all()
        return {
            "total_devices": len(scores),
            "scores": {did: hs.to_dict() for did, hs in scores.items()},
        }

    def reset_device(self, device_id: str) -> None:
        """Clear all samples for a device (e.g. after reconnect)."""
        with self._lock:
            self._samples.pop(device_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_scorer: Optional[DeviceHealthScorer] = None
_scorer_lock = threading.Lock()


def get_device_health_scorer() -> DeviceHealthScorer:
    """Return (or lazily create) the process-level :class:`DeviceHealthScorer`."""
    global _scorer
    with _scorer_lock:
        if _scorer is None:
            _scorer = DeviceHealthScorer()
    return _scorer


def reset_device_health_scorer() -> None:
    """Reset the singleton (intended for tests only)."""
    global _scorer
    with _scorer_lock:
        _scorer = None


# ---------------------------------------------------------------------------
# Convenience alias used by existing memory references to device_health.py
# ---------------------------------------------------------------------------

# Some callers may import ``DeviceHealthScorer`` as ``DeviceHealthScorer``
# directly — no alias needed.  But any caller that imports the module-level
# function can use the alias below for symmetry with other unified modules.

DeviceHealthScorerSingleton = get_device_health_scorer
