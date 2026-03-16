#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Circuit Breaker (PR-G5)
==================================

A per-target circuit breaker implementing the classic three-state machine:

  CLOSED   → normal operation; failures are counted.
  OPEN     → circuit is open; calls are rejected immediately and the
             optional *fallback* is invoked instead.
  HALF_OPEN → recovery probe; a limited number of trial calls are allowed
             to pass.  Success → CLOSED; failure → OPEN again.

Design goals
------------
* **Zero-dependency** – uses only the stdlib (asyncio, threading, time).
* **Thread/coroutine safe** – an ``asyncio.Lock`` guards all state transitions.
* **Observable** – :meth:`CircuitBreaker.snapshot` returns a dict compatible
  with the G2 Prometheus/JSON metric format.
* **Configurable via env vars** – so defaults stay safe without code changes.

Env vars (all optional)
-----------------------
``GALAXY_CB_FAILURE_THRESHOLD``   — failures in window before opening (default 5)
``GALAXY_CB_RECOVERY_TIMEOUT_S``  — seconds OPEN before probe attempt (default 30)
``GALAXY_CB_HALF_OPEN_PROBES``    — trial calls allowed in HALF_OPEN (default 1)
``GALAXY_CB_WINDOW_SIZE``         — rolling failure window size (default 10)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger("Galaxy.Resilience.CircuitBreaker")

_ENV_FAILURE_THRESHOLD = int(os.environ.get("GALAXY_CB_FAILURE_THRESHOLD", "5"))
_ENV_RECOVERY_TIMEOUT = float(os.environ.get("GALAXY_CB_RECOVERY_TIMEOUT_S", "30"))
_ENV_HALF_OPEN_PROBES = int(os.environ.get("GALAXY_CB_HALF_OPEN_PROBES", "1"))
_ENV_WINDOW_SIZE = int(os.environ.get("GALAXY_CB_WINDOW_SIZE", "10"))


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is OPEN."""

    def __init__(self, target: str, opened_at: float) -> None:
        self.target = target
        self.opened_at = opened_at
        remaining = max(0.0, _ENV_RECOVERY_TIMEOUT - (time.monotonic() - opened_at))
        super().__init__(
            f"Circuit breaker OPEN for target '{target}'; "
            f"retry in {remaining:.1f}s"
        )


class CircuitBreaker:
    """Per-target circuit breaker.

    Parameters
    ----------
    target:
        Logical target name (device ID, node name, etc.).
    failure_threshold:
        Number of failures within the rolling window that trip the circuit.
    recovery_timeout:
        Seconds to wait in OPEN state before transitioning to HALF_OPEN.
    half_open_probes:
        Maximum concurrent trial calls allowed in HALF_OPEN state.
    window_size:
        Rolling window length used to count failures.
    fallback:
        Optional async callable invoked when the circuit is OPEN.  It
        receives the same ``(target, command, params)`` arguments as the
        primary executor and should return a degraded / cached result.
    """

    def __init__(
        self,
        target: str,
        failure_threshold: int = _ENV_FAILURE_THRESHOLD,
        recovery_timeout: float = _ENV_RECOVERY_TIMEOUT,
        half_open_probes: int = _ENV_HALF_OPEN_PROBES,
        window_size: int = _ENV_WINDOW_SIZE,
        fallback: Optional[Callable[..., Awaitable[Any]]] = None,
    ) -> None:
        self.target = target
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._half_open_probes = half_open_probes
        self._window_size = window_size
        self._fallback = fallback

        self._state: CircuitState = CircuitState.CLOSED
        self._failure_window: list[int] = []  # 1 = failure, 0 = success
        self._opened_at: float = 0.0
        self._half_open_calls: int = 0

        self._total_calls: int = 0
        self._total_failures: int = 0
        self._total_fallbacks: int = 0
        self._total_circuit_opens: int = 0

        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # State accessors (lock-free; safe for read-only metrics polling)
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == CircuitState.OPEN

    # ------------------------------------------------------------------
    # Core call guard
    # ------------------------------------------------------------------

    async def call(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *fn* guarded by the circuit breaker.

        * CLOSED/HALF_OPEN → executes *fn*; records success or failure.
        * OPEN → if recovery timeout has elapsed, transition to HALF_OPEN;
                 otherwise invoke *fallback* (if set) or raise
                 :class:`CircuitOpenError`.
        """
        async with self._lock:
            state = await self._current_state()

            if state == CircuitState.OPEN:
                self._total_calls += 1
                if self._fallback is not None:
                    self._total_fallbacks += 1
                    logger.debug(
                        "CircuitBreaker[%s] OPEN — invoking fallback", self.target
                    )
                    return await self._fallback(*args, **kwargs)
                raise CircuitOpenError(self.target, self._opened_at)

            if state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._half_open_probes:
                    self._total_calls += 1
                    if self._fallback is not None:
                        self._total_fallbacks += 1
                        return await self._fallback(*args, **kwargs)
                    raise CircuitOpenError(self.target, self._opened_at)
                self._half_open_calls += 1

            self._total_calls += 1

        # Execute outside the lock to avoid blocking metric readers
        try:
            result = await fn(*args, **kwargs)
        except Exception as exc:
            async with self._lock:
                await self._record_failure()
            raise
        else:
            async with self._lock:
                await self._record_success()
            return result

    # ------------------------------------------------------------------
    # Internal helpers (must be called under self._lock)
    # ------------------------------------------------------------------

    async def _current_state(self) -> CircuitState:
        """Re-evaluate OPEN → HALF_OPEN transition by timeout."""
        if (
            self._state == CircuitState.OPEN
            and (time.monotonic() - self._opened_at) >= self._recovery_timeout
        ):
            self._state = CircuitState.HALF_OPEN
            self._half_open_calls = 0
            logger.info(
                "CircuitBreaker[%s] → HALF_OPEN (recovery probe)", self.target
            )
        return self._state

    async def _record_success(self) -> None:
        self._push_window(0)
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            self._half_open_calls = 0
            logger.info(
                "CircuitBreaker[%s] → CLOSED (probe succeeded)", self.target
            )

    async def _record_failure(self) -> None:
        self._total_failures += 1
        self._push_window(1)
        recent_failures = sum(self._failure_window)
        if recent_failures >= self._failure_threshold:
            if self._state != CircuitState.OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._total_circuit_opens += 1
                logger.warning(
                    "CircuitBreaker[%s] → OPEN (%d failures in last %d calls)",
                    self.target, recent_failures, self._window_size,
                )

    def _push_window(self, value: int) -> None:
        self._failure_window.append(value)
        if len(self._failure_window) > self._window_size:
            self._failure_window.pop(0)

    # ------------------------------------------------------------------
    # Manual controls
    # ------------------------------------------------------------------

    async def reset(self) -> None:
        """Force the circuit into CLOSED state and clear failure history."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_window.clear()
            self._half_open_calls = 0
            self._opened_at = 0.0
        logger.info("CircuitBreaker[%s] manually reset to CLOSED", self.target)

    async def trip(self) -> None:
        """Force the circuit OPEN (useful for testing)."""
        async with self._lock:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._total_circuit_opens += 1
        logger.info("CircuitBreaker[%s] manually tripped to OPEN", self.target)

    @property
    def has_fallback(self) -> bool:
        """True when a fallback callable is configured."""
        return self._fallback is not None

    @property
    def opened_at(self) -> float:
        """Monotonic timestamp when the circuit was last opened (0.0 if not open)."""
        return self._opened_at

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Return a metrics snapshot compatible with the G2 JSON format."""
        recent_failures = sum(self._failure_window)
        window_len = len(self._failure_window)
        recent_error_rate = recent_failures / max(window_len, 1)
        return {
            "target": self.target,
            "state": self._state.value,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_fallbacks": self._total_fallbacks,
            "total_circuit_opens": self._total_circuit_opens,
            "recent_error_rate": round(recent_error_rate, 4),
            "window_size": self._window_size,
            "failure_threshold": self._failure_threshold,
            "recovery_timeout_s": self._recovery_timeout,
            "opened_at": self._opened_at if self._state == CircuitState.OPEN else None,
        }
