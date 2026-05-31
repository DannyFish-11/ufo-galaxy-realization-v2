#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy Control Plane — Device Health Registry
===============================================

Per-device health tracking with circuit-breaker logic and quarantine support.

Circuit-breaker states
----------------------
CLOSED    – device is healthy; requests flow through normally.
OPEN      – device exceeded the failure threshold; requests are immediately
            rejected until the cooldown elapses.
HALF_OPEN – cooldown elapsed; one probe request is allowed.  Success →
            CLOSED.  Failure → OPEN again.

Quarantine
----------
When a device accumulates ``quarantine_threshold`` failures within
``quarantine_window_seconds`` it is marked *quarantined* and excluded
from scheduling.  Quarantine can only be lifted via an explicit API call
(see :meth:`DeviceHealthRegistry.unquarantine`).

Health score
------------
A composite ``health_score`` in [0, 100] is computed from:
  * heartbeat latency (lower is better)
  * recent error rate (lower is better)
  * circuit-breaker state (OPEN / HALF_OPEN penalties)

Usage
-----
    from core.control_plane.device_health_registry import (
        DeviceHealthRegistry,
        CircuitState,
    )

    reg = DeviceHealthRegistry()
    reg.record_failure("device_01")
    print(reg.is_eligible("device_01"))   # True until threshold
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    """Possible states of the per-device circuit breaker."""
    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


# ---------------------------------------------------------------------------
# Per-device state
# ---------------------------------------------------------------------------

@dataclass
class DeviceHealthState:
    """Mutable health state for a single device.

    All fields are updated under the parent registry's lock.
    """

    device_id: str

    # --- Circuit breaker -----------------------------------------------
    circuit_state: CircuitState = CircuitState.CLOSED
    consecutive_failures: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0

    # --- Health score components ---------------------------------------
    health_score: float = 100.0          # 0–100, higher is healthier
    heartbeat_latency_ms: float = 0.0
    recent_error_rate: float = 0.0       # EWMA in [0, 1]

    # --- Window-based failure tracking (for quarantine) ----------------
    recent_failures: List[float] = field(default_factory=list)  # monotonic timestamps

    # --- Quarantine ----------------------------------------------------
    quarantined: bool = False
    quarantine_reason: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class DeviceHealthRegistry:
    """Thread-safe registry of per-device health and circuit-breaker state.

    Parameters
    ----------
    circuit_failure_threshold:
        Consecutive failures that cause CLOSED → OPEN.  Default 5.
    circuit_cooldown_seconds:
        Seconds after last failure before OPEN → HALF_OPEN.  Default 60.
    quarantine_threshold:
        Failures within *quarantine_window_seconds* that trigger quarantine.
        Default 10.
    quarantine_window_seconds:
        Rolling window for failure counting.  Default 300 (5 min).
    health_latency_ceiling_ms:
        Latency beyond which the latency component of ``health_score``
        reaches zero.  Default 2 000 ms.
    """

    def __init__(
        self,
        *,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 60.0,
        quarantine_threshold: int = 10,
        quarantine_window_seconds: float = 300.0,
        health_latency_ceiling_ms: float = 2000.0,
    ) -> None:
        self._states: Dict[str, DeviceHealthState] = {}
        self._lock = threading.Lock()

        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self.quarantine_threshold = quarantine_threshold
        self.quarantine_window_seconds = quarantine_window_seconds
        self.health_latency_ceiling_ms = max(health_latency_ceiling_ms, 1.0)

        # Optional audit-event callback: fn(event_name, device_id, **kwargs)
        self._on_event: Optional[Callable] = None

    # ------------------------------------------------------------------
    # Internal helpers  (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _state(self, device_id: str) -> DeviceHealthState:
        """Return or lazily create the state for *device_id*."""
        if device_id not in self._states:
            self._states[device_id] = DeviceHealthState(device_id=device_id)
        return self._states[device_id]

    def _recalculate_health_score(self, state: DeviceHealthState) -> None:
        """Recompute ``health_score`` [0, 100] from latency and error-rate."""
        _LATENCY_WEIGHT = 0.40
        _ERROR_WEIGHT = 0.60
        lat_score = max(
            0.0,
            1.0 - state.heartbeat_latency_ms / self.health_latency_ceiling_ms,
        )
        err_score = 1.0 - state.recent_error_rate

        cb_penalty = 0.0
        if state.circuit_state == CircuitState.OPEN:
            cb_penalty = 0.50
        elif state.circuit_state == CircuitState.HALF_OPEN:
            cb_penalty = 0.25

        raw = (lat_score * _LATENCY_WEIGHT + err_score * _ERROR_WEIGHT) * (1.0 - cb_penalty)
        prev = state.health_score
        state.health_score = round(max(0.0, min(100.0, raw * 100)), 2)

        if abs(state.health_score - prev) >= 1.0:
            self._emit("DEVICE_HEALTH_CHANGED", state.device_id, health_score=state.health_score)

    def _emit(self, event_name: str, device_id: str, **kwargs) -> None:
        """Fire the optional event callback; never raises."""
        if self._on_event:
            try:
                self._on_event(event_name, device_id, **kwargs)
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

    def _purge_old_failures(self, state: DeviceHealthState) -> None:
        """Remove failure timestamps outside the quarantine window."""
        cutoff = time.monotonic() - self.quarantine_window_seconds
        state.recent_failures = [t for t in state.recent_failures if t >= cutoff]

    def _maybe_quarantine(self, state: DeviceHealthState) -> None:
        """Check if the device should be quarantined after a new failure."""
        if state.quarantined:
            return
        self._purge_old_failures(state)
        if len(state.recent_failures) >= self.quarantine_threshold:
            state.quarantined = True
            state.quarantine_reason = (
                f"{len(state.recent_failures)} failures in "
                f"{self.quarantine_window_seconds:.0f}s window"
            )
            self._emit("DEVICE_QUARANTINED", state.device_id, reason=state.quarantine_reason)

    # ------------------------------------------------------------------
    # Circuit-breaker helpers  (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _try_half_open_transition(self, state: DeviceHealthState) -> bool:
        """If OPEN and cooldown elapsed, transition to HALF_OPEN.

        Returns True if the transition happened.
        """
        if state.circuit_state != CircuitState.OPEN:
            return False
        elapsed = time.monotonic() - state.last_failure_time
        if elapsed >= self.circuit_cooldown_seconds:
            state.circuit_state = CircuitState.HALF_OPEN
            self._recalculate_health_score(state)
            self._emit("DEVICE_CIRCUIT_HALF_OPEN", state.device_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Recording API  (thread-safe, callable from any context)
    # ------------------------------------------------------------------

    def record_heartbeat(self, device_id: str, latency_ms: float = 0.0) -> None:
        """Record a successful heartbeat with optional round-trip latency."""
        with self._lock:
            state = self._state(device_id)
            state.heartbeat_latency_ms = max(0.0, latency_ms)
            self._recalculate_health_score(state)

    def record_success(self, device_id: str) -> None:
        """Record a successful task execution.

        Transitions HALF_OPEN / OPEN → CLOSED and resets consecutive
        failure counter.
        """
        with self._lock:
            state = self._state(device_id)
            state.last_success_time = time.monotonic()
            # Decay error rate on success
            state.recent_error_rate = max(0.0, state.recent_error_rate * 0.8)

            if state.circuit_state in (CircuitState.HALF_OPEN, CircuitState.OPEN):
                state.circuit_state = CircuitState.CLOSED
                state.consecutive_failures = 0
                self._recalculate_health_score(state)
                self._emit("DEVICE_CIRCUIT_CLOSED", device_id)
            elif state.circuit_state == CircuitState.CLOSED:
                state.consecutive_failures = 0
                self._recalculate_health_score(state)

    def record_failure(self, device_id: str, error: str = "") -> None:
        """Record a task or heartbeat failure.

        May trigger CLOSED → OPEN or HALF_OPEN → OPEN circuit transitions
        and quarantine if the window threshold is exceeded.
        """
        with self._lock:
            state = self._state(device_id)
            state.consecutive_failures += 1
            state.last_failure_time = time.monotonic()
            state.recent_failures.append(state.last_failure_time)

            # EWMA error-rate update
            state.recent_error_rate = min(1.0, state.recent_error_rate * 0.8 + 0.2)

            prev_circuit = state.circuit_state

            if state.circuit_state == CircuitState.HALF_OPEN:
                state.circuit_state = CircuitState.OPEN
                self._recalculate_health_score(state)
                self._emit(
                    "DEVICE_CIRCUIT_OPEN", device_id,
                    error=error, consecutive_failures=state.consecutive_failures,
                )
            elif (
                state.circuit_state == CircuitState.CLOSED
                and state.consecutive_failures >= self.circuit_failure_threshold
            ):
                state.circuit_state = CircuitState.OPEN
                self._recalculate_health_score(state)
                self._emit(
                    "DEVICE_CIRCUIT_OPEN", device_id,
                    error=error, consecutive_failures=state.consecutive_failures,
                )
            else:
                self._recalculate_health_score(state)

            self._maybe_quarantine(state)

    # ------------------------------------------------------------------
    # Eligibility queries
    # ------------------------------------------------------------------

    def is_eligible(self, device_id: str) -> bool:
        """Return True if *device_id* is allowed to receive new tasks.

        A device is *ineligible* when:
        * It is quarantined.
        * Its circuit is OPEN (and cooldown has not yet elapsed).
        """
        with self._lock:
            if device_id not in self._states:
                return True  # unknown → optimistically eligible
            state = self._states[device_id]
            if state.quarantined:
                return False
            # Allow OPEN → HALF_OPEN transition if cooldown elapsed
            if state.circuit_state == CircuitState.OPEN:
                self._try_half_open_transition(state)
            return state.circuit_state != CircuitState.OPEN

    def get_state(self, device_id: str) -> Optional[DeviceHealthState]:
        """Return a *copy* of the device health state, or None if unknown."""
        with self._lock:
            state = self._states.get(device_id)
            if state is None:
                return None
            # Return a shallow copy so callers can't mutate registry state
            import dataclasses
            return dataclasses.replace(state)

    def get_all_states(self) -> Dict[str, DeviceHealthState]:
        """Return a dict of shallow-copied device states."""
        with self._lock:
            import dataclasses
            return {did: dataclasses.replace(s) for did, s in self._states.items()}

    # ------------------------------------------------------------------
    # Quarantine management
    # ------------------------------------------------------------------

    def unquarantine(self, device_id: str) -> bool:
        """Lift quarantine on *device_id*.

        Also resets the circuit breaker to CLOSED and clears recent-failure
        history so the device can receive tasks immediately.

        Returns
        -------
        bool
            True if the device was quarantined (and is now unquarantined).
            False if the device was not quarantined (no-op, but safe to call).
        """
        with self._lock:
            state = self._state(device_id)
            was_quarantined = state.quarantined
            state.quarantined = False
            state.quarantine_reason = ""
            # Reset circuit state so requests flow through immediately
            state.circuit_state = CircuitState.CLOSED
            state.consecutive_failures = 0
            state.recent_failures.clear()
            self._recalculate_health_score(state)
            return was_quarantined

    # ------------------------------------------------------------------
    # Observability callback
    # ------------------------------------------------------------------

    def set_event_callback(self, callback: Callable) -> None:
        """Register a callback for health-change events.

        The callback signature is::

            callback(event_name: str, device_id: str, **kwargs) -> None

        Event names emitted:
        * ``DEVICE_HEALTH_CHANGED``
        * ``DEVICE_CIRCUIT_OPEN``
        * ``DEVICE_CIRCUIT_HALF_OPEN``
        * ``DEVICE_CIRCUIT_CLOSED``
        * ``DEVICE_QUARANTINED``
        """
        self._on_event = callback
