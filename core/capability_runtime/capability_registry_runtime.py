#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.capability_runtime.capability_registry_runtime
=====================================================

PR-20 (V4) — Capability Runtime State

Provides :class:`CapabilityRuntimeRegistry` — a process-level singleton that
stores and exposes **live runtime state** for named capabilities.

Design constraints
------------------
* **Additive** — this registry sits *alongside* the existing
  :class:`~core.agent.capability_registry.CapabilityRegistry`.  It does NOT
  replace or modify that registry.
* **Thread-safe** — all writes and reads are protected by a
  :class:`threading.Lock`.
* **Graceful degradation** — reads for unknown capabilities return an
  ``UNKNOWN`` summary rather than raising.
* **No heavy dependencies** — the registry is a plain in-memory store; it
  does not connect to NATS, WebSocket, or any external transport.

Public API
----------
CapabilityRuntimeRegistry.get_instance()
    Singleton accessor.

register(state)
    Register or overwrite the runtime state for a capability.

update(name, **fields)
    Partial update to an existing state record.  Creates a new UNKNOWN
    state if the capability has not been registered yet.

get_state(name) → Optional[CapabilityRuntimeState]
    Retrieve the full runtime state for a capability.

get_summary(name) → CapabilityRuntimeSummary
    Return a public-safe summary.  Returns ``UNKNOWN_CAPABILITY_SUMMARY``
    when not found.

list_states() → list[CapabilityRuntimeState]
    Return all registered states.

list_summaries() → list[CapabilityRuntimeSummary]
    Return all summaries.

deregister(name)
    Remove a capability from the runtime registry.

stats() → dict
    Observability stats (total registered, available count, degraded count,
    etc.).
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

from .capability_state import CapabilityAvailability, CapabilityRuntimeState
from .capability_summary import (
    CapabilityRuntimeSummary,
    UNKNOWN_CAPABILITY_SUMMARY,
)

logger = logging.getLogger("Galaxy.CapabilityRuntime.Registry")

# ---------------------------------------------------------------------------
# Batch PR-6: Capability runtime registry authority sentinel
# ---------------------------------------------------------------------------

CAPABILITY_RUNTIME_REGISTRY_AUTHORITY = (
    "core.capability_runtime.capability_registry_runtime.CapabilityRuntimeRegistry"
)
"""Sentinel: ``CapabilityRuntimeRegistry`` is the canonical live runtime state
store for capability health and availability.

Responsibility (Batch PR-6 clarification)
-----------------------------------------
- **Role**: tracks *live runtime state* (availability, health, last-seen) for
  named capabilities.  Additive alongside the static capability catalog.
- **NOT** the capability inventory SSOT (that is ``CapabilityRegistry``).
- **NOT** the capability bus / discovery directory (that is ``CapabilityBus``).

This registry answers "is this capability currently healthy/available?"
while ``CapabilityRegistry`` answers "what capabilities are registered?"
"""


class CapabilityRuntimeRegistry:
    """Process-level singleton runtime registry for capability states.

    Thread-safe.  Additive alongside existing capability registries.
    """

    _instance: Optional["CapabilityRuntimeRegistry"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "CapabilityRuntimeRegistry":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialised = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialised:  # type: ignore[has-type]
            return
        self._states: Dict[str, CapabilityRuntimeState] = {}
        self._lock: threading.Lock = threading.Lock()
        self._initialised = True
        logger.debug(
            "CapabilityRuntimeRegistry initialised",
            extra={"event": "capability_runtime_registry_init"},
        )

    # ── Singleton accessor ────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "CapabilityRuntimeRegistry":
        """Return the process-level singleton."""
        if cls._instance is None:
            cls()
        return cls._instance  # type: ignore[return-value]

    # ── Write API ─────────────────────────────────────────────────────────

    def register(self, state: CapabilityRuntimeState) -> None:
        """Register or overwrite the runtime state for *state.name*.

        Parameters
        ----------
        state:
            The :class:`CapabilityRuntimeState` to store.
        """
        if not state.name:
            logger.warning(
                "CapabilityRuntimeRegistry.register() called with empty name — ignored",
                extra={"event": "capability_runtime_register_empty_name"},
            )
            return
        with self._lock:
            self._states[state.name] = state
        logger.debug(
            "Registered capability runtime state: %s (availability=%s)",
            state.name,
            state.availability.value if isinstance(state.availability, CapabilityAvailability) else state.availability,
            extra={
                "event": "capability_runtime_registered",
                "capability_name": state.name,
                "availability": (
                    state.availability.value
                    if isinstance(state.availability, CapabilityAvailability)
                    else state.availability
                ),
            },
        )

    def update(self, name: str, **fields: Any) -> None:
        """Partially update the runtime state for capability *name*.

        Creates a new ``UNKNOWN`` state if not previously registered.
        Only the fields explicitly passed are updated; all others are
        preserved.

        Parameters
        ----------
        name:
            Capability name.
        **fields:
            Field names and new values from
            :class:`~core.capability_runtime.capability_state.CapabilityRuntimeState`.
        """
        with self._lock:
            existing = self._states.get(name)
            if existing is None:
                existing = CapabilityRuntimeState(name=name)

            # Build updated state dict
            state_dict = existing.to_dict()
            for key, value in fields.items():
                if key in state_dict:
                    state_dict[key] = value
                else:
                    logger.debug(
                        "CapabilityRuntimeRegistry.update: unknown field '%s' for '%s' — ignored",
                        key, name,
                    )
            state_dict["last_updated"] = time.time()
            updated = CapabilityRuntimeState.from_dict(state_dict)
            self._states[name] = updated

        logger.debug(
            "Updated capability runtime state: %s (fields=%s)",
            name, list(fields.keys()),
            extra={
                "event": "capability_runtime_updated",
                "capability_name": name,
                "updated_fields": list(fields.keys()),
            },
        )

    def deregister(self, name: str) -> bool:
        """Remove capability *name* from the runtime registry.

        Returns
        -------
        bool
            ``True`` if the entry existed and was removed; ``False`` otherwise.
        """
        with self._lock:
            existed = name in self._states
            self._states.pop(name, None)
        if existed:
            logger.debug(
                "Deregistered capability runtime state: %s",
                name,
                extra={"event": "capability_runtime_deregistered", "capability_name": name},
            )
        return existed

    # ── Read API ──────────────────────────────────────────────────────────

    def get_state(self, name: str) -> Optional[CapabilityRuntimeState]:
        """Return the full runtime state for *name*, or ``None``."""
        with self._lock:
            return self._states.get(name)

    def get_summary(self, name: str) -> CapabilityRuntimeSummary:
        """Return a public-safe summary for *name*.

        Returns :data:`~core.capability_runtime.capability_summary.UNKNOWN_CAPABILITY_SUMMARY`
        when the capability has no recorded state.
        """
        state = self.get_state(name)
        if state is None:
            return UNKNOWN_CAPABILITY_SUMMARY
        return self._state_to_summary(state)

    def list_states(self) -> List[CapabilityRuntimeState]:
        """Return all registered runtime states (snapshot)."""
        with self._lock:
            return list(self._states.values())

    def list_summaries(self) -> List[CapabilityRuntimeSummary]:
        """Return public-safe summaries for all registered capabilities."""
        states = self.list_states()
        return [self._state_to_summary(s) for s in states]

    def stats(self) -> Dict[str, Any]:
        """Return observability stats."""
        states = self.list_states()
        availability_counts: Dict[str, int] = {}
        for s in states:
            key = (
                s.availability.value
                if isinstance(s.availability, CapabilityAvailability)
                else str(s.availability)
            )
            availability_counts[key] = availability_counts.get(key, 0) + 1

        return {
            "total_registered": len(states),
            "by_availability": availability_counts,
            "available_count": availability_counts.get(CapabilityAvailability.AVAILABLE.value, 0),
            "degraded_count": availability_counts.get(CapabilityAvailability.DEGRADED.value, 0),
            "unavailable_count": availability_counts.get(CapabilityAvailability.UNAVAILABLE.value, 0),
            "unknown_count": availability_counts.get(CapabilityAvailability.UNKNOWN.value, 0),
        }

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _state_to_summary(state: CapabilityRuntimeState) -> CapabilityRuntimeSummary:
        """Convert a :class:`CapabilityRuntimeState` to a summary."""
        # Resolve active constraint flag names
        constraint_flags: List[str] = []
        cf = state.constraint_flags
        if isinstance(cf, dict):
            constraint_flags = [k for k, v in cf.items() if v]
        elif hasattr(cf, "active_constraints"):
            constraint_flags = cf.active_constraints()

        # Derive a short reliability note from reliability_flags
        rf = state.reliability_flags
        notes_parts = []
        if isinstance(rf, dict):
            for key in ("health_score", "error_rate", "latency_ms"):
                if key in rf:
                    notes_parts.append(f"{key}={rf[key]}")
        reliability_notes = "; ".join(notes_parts) if notes_parts else ""

        avail_value = (
            state.availability.value
            if isinstance(state.availability, CapabilityAvailability)
            else str(state.availability)
        )

        return CapabilityRuntimeSummary(
            capability_name=state.name,
            availability=avail_value,
            preferred_device_ids=list(state.preferred_device_ids),
            constraint_flags=constraint_flags,
            reliability_notes=reliability_notes,
            device_bindings=list(state.device_bindings),
            last_updated=state.last_updated,
            metadata=dict(state.metadata),
        )
