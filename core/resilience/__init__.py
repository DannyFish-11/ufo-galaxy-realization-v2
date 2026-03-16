"""
Galaxy – Resilience & Protection (PR-G5)
=========================================

Provides:
  - CircuitBreaker  — per-target CLOSED/OPEN/HALF_OPEN state machine
  - AdaptiveSemaphore — concurrency limit that adjusts to observed latency
  - ResilienceMetrics — queue depth, rejection rate, fallback activation counters
"""

from core.resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitOpenError
from core.resilience.adaptive_semaphore import AdaptiveSemaphore
from core.resilience.metrics import ResilienceMetrics, get_resilience_metrics

__all__ = [
    "CircuitBreaker",
    "CircuitState",
    "CircuitOpenError",
    "AdaptiveSemaphore",
    "ResilienceMetrics",
    "get_resilience_metrics",
]
