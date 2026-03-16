#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Unified Device Pool Manager
======================================

Single scheduling / health / weight entry point for all device operations.

Design principles
-----------------
* **Single source of truth** – all device registration, health tracking,
  capacity management and scheduling decisions go through this class.
* **Delegating architecture** – internally delegates health tracking to
  :class:`core.control_plane.device_health_registry.DeviceHealthRegistry`
  so the existing circuit-breaker / quarantine logic is reused unchanged.
* **Strategy pattern** – supports three built-in scheduling strategies:
  ``round_robin``, ``least_conn``, and ``adaptive`` (score-weighted).
* **Backward compatible** – ``DeviceOrchestrator`` and other callers keep
  their existing APIs; they simply delegate to this manager internally.

Usage
-----
    from core.device_pool_manager import get_device_pool_manager

    pool = get_device_pool_manager()
    pool.register_device("dev_01", capabilities=["screen", "touch"])
    dev = pool.select_device(required_capabilities=["screen"])
    pool.mark_success("dev_01")
    pool.mark_failure("dev_01", error="timeout")
"""

from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.DevicePoolManager")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class SchedulingStrategy(str, Enum):
    """Available device-selection strategies."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONN  = "least_conn"
    ADAPTIVE    = "adaptive"


# ---------------------------------------------------------------------------
# Device record
# ---------------------------------------------------------------------------

@dataclass
class PoolDevice:
    """Metadata and runtime state for a single device in the pool."""

    device_id: str
    capabilities: List[str] = field(default_factory=list)
    device_type: str = ""
    weight: float = 1.0
    capacity: int = 10          # max concurrent tasks
    active_connections: int = 0
    registered_at: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------- derived / runtime ----------
    @property
    def is_full(self) -> bool:
        return self.active_connections >= self.capacity

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "device_type": self.device_type,
            "capabilities": self.capabilities,
            "weight": self.weight,
            "capacity": self.capacity,
            "active_connections": self.active_connections,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# DevicePoolManager
# ---------------------------------------------------------------------------

class DevicePoolManager:
    """Unified device pool — registration, health, weights, and scheduling.

    Parameters
    ----------
    strategy:
        Default scheduling strategy.  Can be overridden per
        :meth:`select_device` call.
    quarantine_threshold:
        Failures within the window that trigger quarantine.
        Forwarded to the underlying :class:`DeviceHealthRegistry`.
    circuit_failure_threshold:
        Consecutive failures that open the circuit breaker.
    """

    _instance: Optional["DevicePoolManager"] = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._instance_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
        return cls._instance

    def __init__(
        self,
        strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE,
        quarantine_threshold: int = 10,
        circuit_failure_threshold: int = 5,
    ) -> None:
        if self._initialized:
            return
        self._initialized = True

        self.strategy = strategy
        self._lock = threading.Lock()
        self._devices: Dict[str, PoolDevice] = {}

        # Round-robin cursor (device_id iterator cycle)
        self._rr_cycle: Optional[itertools.cycle] = None

        # Delegate health / circuit-breaker tracking
        self._health_registry = self._make_health_registry(
            quarantine_threshold=quarantine_threshold,
            circuit_failure_threshold=circuit_failure_threshold,
        )
        logger.info(
            "DevicePoolManager 初始化完成 [strategy=%s]", strategy.value
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_health_registry(
        quarantine_threshold: int,
        circuit_failure_threshold: int,
    ):
        try:
            from core.control_plane.device_health_registry import DeviceHealthRegistry
            return DeviceHealthRegistry(
                quarantine_threshold=quarantine_threshold,
                circuit_failure_threshold=circuit_failure_threshold,
            )
        except Exception as exc:
            logger.warning("DeviceHealthRegistry 不可用，降级为 None: %s", exc)
            return None

    def _rebuild_rr_cycle(self) -> None:
        """Rebuild round-robin iterator from current device IDs."""
        ids = list(self._devices.keys())
        self._rr_cycle = itertools.cycle(ids) if ids else None

    def _health_score(self, device_id: str) -> float:
        """Return health score [0, 100] for *device_id*."""
        if self._health_registry is None:
            return 100.0
        state = self._health_registry.get_state(device_id)
        if state is None:
            return 100.0
        return state.health_score

    def _is_eligible(self, device_id: str) -> bool:
        """Return True if the device can accept new tasks."""
        if self._health_registry is None:
            return True
        return self._health_registry.is_eligible(device_id)

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        capabilities: Optional[List[str]] = None,
        device_type: str = "",
        weight: float = 1.0,
        capacity: int = 10,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PoolDevice:
        """Register a new device or update an existing one.

        Returns the :class:`PoolDevice` record after upsert.
        """
        with self._lock:
            if device_id in self._devices:
                dev = self._devices[device_id]
                dev.capabilities = capabilities or dev.capabilities
                dev.device_type = device_type or dev.device_type
                dev.weight = weight
                dev.capacity = capacity
                if metadata:
                    dev.metadata.update(metadata)
                logger.debug("设备已更新: %s", device_id)
            else:
                dev = PoolDevice(
                    device_id=device_id,
                    capabilities=capabilities or [],
                    device_type=device_type,
                    weight=weight,
                    capacity=capacity,
                    metadata=metadata or {},
                )
                self._devices[device_id] = dev
                self._rebuild_rr_cycle()
                logger.info("设备已注册: %s (caps=%s)", device_id, dev.capabilities)

            # Emit audit event
            self._emit_audit("device_registered", device_id=device_id)
            return dev

    def unregister_device(self, device_id: str) -> bool:
        """Remove a device from the pool. Returns True if it existed."""
        with self._lock:
            if device_id not in self._devices:
                return False
            del self._devices[device_id]
            self._rebuild_rr_cycle()
            logger.info("设备已注销: %s", device_id)
            return True

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_devices(
        self,
        required_capabilities: Optional[List[str]] = None,
        device_type: Optional[str] = None,
        eligible_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List registered devices with optional filters.

        Args:
            required_capabilities: Only return devices that have ALL listed
                capabilities.
            device_type: Filter by device type string.
            eligible_only: Skip quarantined / circuit-open devices.

        Returns:
            List of device info dicts, each annotated with ``health_score``
            and ``eligible``.
        """
        with self._lock:
            result = []
            for dev in self._devices.values():
                if device_type and dev.device_type != device_type:
                    continue
                if required_capabilities:
                    if not all(c in dev.capabilities for c in required_capabilities):
                        continue
                eligible = self._is_eligible(dev.device_id)
                if eligible_only and not eligible:
                    continue
                info = dev.to_dict()
                info["health_score"] = self._health_score(dev.device_id)
                info["eligible"] = eligible
                result.append(info)
            return result

    def get_device(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return a single device's info dict, or None if not found."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev is None:
                return None
            info = dev.to_dict()
            info["health_score"] = self._health_score(dev.device_id)
            info["eligible"] = self._is_eligible(dev.device_id)
            return info

    # ------------------------------------------------------------------
    # Scheduling / selection
    # ------------------------------------------------------------------

    def select_device(
        self,
        required_capabilities: Optional[List[str]] = None,
        device_type: Optional[str] = None,
        strategy: Optional[SchedulingStrategy] = None,
        exclude: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Select the best eligible device according to *strategy*.

        Args:
            required_capabilities: The device must have all these capabilities.
            device_type: Optional device-type filter.
            strategy: Override the pool-level default strategy.
            exclude: Device IDs to skip (e.g. already tried).

        Returns:
            ``device_id`` of the selected device, or ``None`` if no
            eligible device is available.
        """
        effective_strategy = strategy or self.strategy
        exclude_set = set(exclude or [])

        with self._lock:
            candidates = [
                dev for dev in self._devices.values()
                if dev.device_id not in exclude_set
                and not dev.is_full
                and self._is_eligible(dev.device_id)
                and (not device_type or dev.device_type == device_type)
                and (
                    not required_capabilities
                    or all(c in dev.capabilities for c in required_capabilities)
                )
            ]

            if not candidates:
                return None

            if effective_strategy == SchedulingStrategy.ROUND_ROBIN:
                chosen = self._select_rr(candidates)
            elif effective_strategy == SchedulingStrategy.LEAST_CONN:
                chosen = min(candidates, key=lambda d: d.active_connections)
            else:
                # ADAPTIVE — weighted composite score
                chosen = self._select_adaptive(candidates)

            if chosen:
                chosen.active_connections += 1
                logger.debug(
                    "选中设备: %s [strategy=%s, conns=%d]",
                    chosen.device_id, effective_strategy.value, chosen.active_connections,
                )
                return chosen.device_id
            return None

    def _select_rr(self, candidates: List[PoolDevice]) -> Optional[PoolDevice]:
        """Round-robin selection among *candidates*."""
        candidate_ids = {d.device_id for d in candidates}
        # Scan the cycle until we find one in the candidate set
        if self._rr_cycle is None:
            return candidates[0] if candidates else None
        for _ in range(len(self._devices) + 1):
            try:
                dev_id = next(self._rr_cycle)
            except StopIteration:
                break
            if dev_id in candidate_ids:
                return self._devices[dev_id]
        # Fallback
        return candidates[0] if candidates else None

    def _select_adaptive(self, candidates: List[PoolDevice]) -> Optional[PoolDevice]:
        """Weighted-score selection: health × weight / (connections + 1)."""

        def score(dev: PoolDevice) -> float:
            h = self._health_score(dev.device_id) / 100.0
            conn_penalty = 1.0 / (dev.active_connections + 1)
            return h * dev.weight * conn_penalty

        if not candidates:
            return None
        return max(candidates, key=score)

    # ------------------------------------------------------------------
    # Feedback API (called after task execution)
    # ------------------------------------------------------------------

    def mark_success(self, device_id: str) -> None:
        """Record a successful task completion for *device_id*."""
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.active_connections > 0:
                dev.active_connections -= 1
        if self._health_registry:
            self._health_registry.record_success(device_id)

    def mark_failure(self, device_id: str, error: str = "") -> None:
        """Record a task failure for *device_id*.

        Internally calls :meth:`DeviceHealthRegistry.record_failure` which
        handles circuit-breaker transitions and quarantine.
        """
        with self._lock:
            dev = self._devices.get(device_id)
            if dev and dev.active_connections > 0:
                dev.active_connections -= 1
        if self._health_registry:
            self._health_registry.record_failure(device_id, error=error)

    def mark_heartbeat(self, device_id: str, latency_ms: float = 0.0) -> None:
        """Forward a heartbeat signal to the health registry."""
        if self._health_registry:
            self._health_registry.record_heartbeat(device_id, latency_ms=latency_ms)

    # ------------------------------------------------------------------
    # Quarantine / management
    # ------------------------------------------------------------------

    def quarantine(self, device_id: str, reason: str = "manual") -> None:
        """Manually quarantine a device (exclude from scheduling)."""
        if self._health_registry is not None:
            if hasattr(self._health_registry, "quarantine"):
                self._health_registry.quarantine(device_id, reason=reason)
            elif hasattr(self._health_registry, "_states"):
                with self._health_registry._lock:
                    state = self._health_registry._state(device_id)
                    state.quarantined = True
                    state.quarantine_reason = reason
        logger.warning("设备已手动隔离: %s (%s)", device_id, reason)

    def unquarantine(self, device_id: str) -> None:
        """Lift the quarantine from *device_id*."""
        if self._health_registry is not None:
            if hasattr(self._health_registry, "unquarantine"):
                self._health_registry.unquarantine(device_id)
            elif hasattr(self._health_registry, "_states"):
                with self._health_registry._lock:
                    state = self._health_registry._states.get(device_id)
                    if state:
                        state.quarantined = False
                        state.quarantine_reason = ""
        logger.info("设备隔离已解除: %s", device_id)

    def get_health_state(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Return raw health state dict for *device_id*."""
        if self._health_registry is None:
            return None
        state = self._health_registry.get_state(device_id)
        if state is None:
            return None
        return {
            "device_id": device_id,
            "health_score": state.health_score,
            "circuit_state": state.circuit_state,
            "consecutive_failures": state.consecutive_failures,
            "quarantined": state.quarantined,
            "quarantine_reason": state.quarantine_reason,
        }

    # ------------------------------------------------------------------
    # Audit helper
    # ------------------------------------------------------------------

    @staticmethod
    def _emit_audit(event_name: str, **kwargs) -> None:
        """Fire an audit-ledger event (best-effort, never raises)."""
        try:
            from core.control_plane.audit_ledger import AuditLedger, EventType
            ledger = AuditLedger.get_instance()
            et = getattr(EventType, event_name.upper(), None)
            if et is None:
                return
            ledger.append(et, **kwargs)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        """Return pool-level statistics."""
        with self._lock:
            total = len(self._devices)
            eligible = sum(
                1 for d in self._devices
                if self._is_eligible(d)
            )
            total_conns = sum(
                d.active_connections for d in self._devices.values()
            )
            return {
                "total_devices": total,
                "eligible_devices": eligible,
                "total_active_connections": total_conns,
                "strategy": self.strategy.value,
            }

    def reset(self) -> None:
        """Reset pool state (used in tests; not for production use)."""
        with self._lock:
            self._devices.clear()
            self._rr_cycle = None
        logger.debug("DevicePoolManager 已重置")

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset the singleton instance for test isolation."""
        cls._instance = None
        global _pool_manager
        _pool_manager = None


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_pool_manager: Optional[DevicePoolManager] = None
_factory_lock = threading.Lock()


def get_device_pool_manager(
    strategy: SchedulingStrategy = SchedulingStrategy.ADAPTIVE,
) -> DevicePoolManager:
    """Return (or create) the global :class:`DevicePoolManager` singleton."""
    global _pool_manager
    if _pool_manager is None:
        with _factory_lock:
            if _pool_manager is None:
                _pool_manager = DevicePoolManager(strategy=strategy)
    return _pool_manager
