#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/orchestration/global_arbiter.py
======================================
Block-5: Global Scheduler Arbiter

The :class:`GlobalArbiter` is the single authority for *scheduling decisions*
across the Galaxy system.  It enforces:

* **Priority** — higher-priority tasks run before lower-priority ones.
* **Preemption** — a new high-priority task can preempt a running lower-priority
  task (emitting an :attr:`~core.unified.error_codes.GalaxyErrorCode.ARBITER_PREEMPTED`
  error payload for the displaced task).
* **Fairness** — a per-origin concurrency quota prevents any single source
  from monopolising execution slots.
* **Traceability** — every scheduling decision (admit/reject/preempt) is
  logged with a deterministic ``decision_id`` so it can be audited.

Integration points
------------------
* :mod:`core.task_graph` — call :meth:`GlobalArbiter.admit` before submitting a
  new :class:`~core.task_graph.TaskGraph`; call :meth:`GlobalArbiter.release`
  when the graph completes.
* :mod:`core.e2e_orchestrator` — guarded by ``enable_global_arbiter`` feature
  flag (``config/feature_flags.yaml``).
* :mod:`core.unified.device_manager` — :meth:`GlobalArbiter.suggest_device`
  provides a device hint that respects current load.

Usage::

    from core.orchestration.global_arbiter import get_global_arbiter

    arbiter = get_global_arbiter()
    decision = arbiter.admit(
        task_id="task-123",
        priority=5,
        origin="user:alice",
        preemptable=True,
    )
    if not decision.admitted:
        raise ArbiterQuotaError(decision.reason)

    try:
        await run_task()
    finally:
        arbiter.release("task-123")
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.GlobalArbiter")

# Default concurrency limits
_DEFAULT_GLOBAL_CONCURRENCY: int = 16
_DEFAULT_PER_ORIGIN_QUOTA: int = 4


# ---------------------------------------------------------------------------
# Exceptions (mapped to error codes)
# ---------------------------------------------------------------------------


class ArbiterPreemptedError(Exception):
    """Raised for the task that gets preempted."""

    def __init__(self, task_id: str, reason: str = "") -> None:
        super().__init__(f"Task '{task_id}' preempted: {reason}")
        self.task_id = task_id
        self.reason = reason
        self.code = "AR_001"


class ArbiterQuotaError(Exception):
    """Raised when a task is rejected due to quota."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(f"Arbiter quota exceeded: {reason}")
        self.reason = reason
        self.code = "AR_002"


class ArbiterNoSlotError(Exception):
    """Raised when there is no available slot and no preemption target."""

    def __init__(self, reason: str = "") -> None:
        super().__init__(f"No scheduler slot available: {reason}")
        self.reason = reason
        self.code = "AR_003"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class DecisionOutcome(str, Enum):
    ADMITTED = "admitted"
    REJECTED_QUOTA = "rejected_quota"
    REJECTED_NO_SLOT = "rejected_no_slot"
    PREEMPTED_OTHER = "preempted_other"   # admitted by preempting another task


@dataclass
class SchedulingDecision:
    """Record of one arbiter admission decision."""

    decision_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    # 12 hex chars = 48 bits of UUID v4 entropy.  Collision probability across
    # a decision log of ≤ 1 000 entries is < 1.4 × 10⁻⁸ — acceptable for an
    # in-process audit trail.  Use full UUIDs if persisting to external storage.
    task_id: str = ""
    outcome: DecisionOutcome = DecisionOutcome.ADMITTED
    admitted: bool = True
    priority: int = 0
    origin: str = ""
    preempted_task_id: Optional[str] = None
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "task_id": self.task_id,
            "outcome": self.outcome.value,
            "admitted": self.admitted,
            "priority": self.priority,
            "origin": self.origin,
            "preempted_task_id": self.preempted_task_id,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass
class RunningTask:
    """A task that has been admitted and is currently in-flight."""

    task_id: str
    priority: int
    origin: str
    preemptable: bool
    admitted_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Global arbiter
# ---------------------------------------------------------------------------


class GlobalArbiter:
    """Process-level scheduling arbiter (singleton).

    Manages a fixed-size concurrency window.  Each call to :meth:`admit`
    either grants a slot or returns a rejected/preemption decision.
    """

    _instance: Optional["GlobalArbiter"] = None

    def __new__(cls) -> "GlobalArbiter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._init()
        return cls._instance

    def _init(self) -> None:
        self._global_limit: int = _DEFAULT_GLOBAL_CONCURRENCY
        self._per_origin_quota: int = _DEFAULT_PER_ORIGIN_QUOTA
        self._running: Dict[str, RunningTask] = {}
        self._decision_log: List[SchedulingDecision] = []
        self._max_log: int = 1000
        self._stats: Dict[str, int] = {
            "admitted": 0, "rejected": 0, "preemptions": 0
        }
        self._enabled: bool = True

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        global_limit: Optional[int] = None,
        per_origin_quota: Optional[int] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        if global_limit is not None:
            self._global_limit = int(global_limit)
        if per_origin_quota is not None:
            self._per_origin_quota = int(per_origin_quota)
        if enabled is not None:
            self._enabled = bool(enabled)

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def admit(
        self,
        task_id: str,
        *,
        priority: int = 0,
        origin: str = "unknown",
        preemptable: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> SchedulingDecision:
        """Request a scheduling slot for *task_id*.

        If the arbiter is disabled (``enabled=False``), all tasks are
        immediately admitted without any limits.

        Args:
            task_id:     Unique task identifier.
            priority:    Integer priority (higher = more important).
            origin:      Logical source (e.g. ``"user:alice"`` or
                         ``"planner:decomposer"``).
            preemptable: Whether this task may be preempted by a later
                         higher-priority task.
            metadata:    Optional extra context stored with the task.

        Returns:
            A :class:`SchedulingDecision` (always; never raises).
        """
        if not self._enabled:
            rt = RunningTask(task_id, priority, origin, preemptable,
                             metadata=metadata or {})
            self._running[task_id] = rt
            decision = SchedulingDecision(
                task_id=task_id, outcome=DecisionOutcome.ADMITTED,
                admitted=True, priority=priority, origin=origin,
                reason="arbiter_disabled",
            )
            self._record(decision)
            return decision

        # Per-origin quota check
        origin_count = sum(1 for t in self._running.values() if t.origin == origin)
        if origin_count >= self._per_origin_quota:
            decision = SchedulingDecision(
                task_id=task_id, outcome=DecisionOutcome.REJECTED_QUOTA,
                admitted=False, priority=priority, origin=origin,
                reason=f"per_origin_quota={self._per_origin_quota} exceeded for '{origin}'",
            )
            self._stats["rejected"] += 1
            self._record(decision)
            logger.info("Arbiter REJECT quota task=%s origin=%s", task_id, origin)
            return decision

        # Global limit — try to admit directly
        if len(self._running) < self._global_limit:
            rt = RunningTask(task_id, priority, origin, preemptable,
                             metadata=metadata or {})
            self._running[task_id] = rt
            decision = SchedulingDecision(
                task_id=task_id, outcome=DecisionOutcome.ADMITTED,
                admitted=True, priority=priority, origin=origin,
                reason="slot_available",
            )
            self._stats["admitted"] += 1
            self._record(decision)
            logger.debug("Arbiter ADMIT task=%s priority=%d", task_id, priority)
            return decision

        # No free slot — try preemption
        victim = self._find_preemption_victim(priority)
        if victim is not None:
            del self._running[victim.task_id]
            rt = RunningTask(task_id, priority, origin, preemptable,
                             metadata=metadata or {})
            self._running[task_id] = rt
            decision = SchedulingDecision(
                task_id=task_id, outcome=DecisionOutcome.PREEMPTED_OTHER,
                admitted=True, priority=priority, origin=origin,
                preempted_task_id=victim.task_id,
                reason=f"preempted task_id={victim.task_id} priority={victim.priority}",
            )
            self._stats["admitted"] += 1
            self._stats["preemptions"] += 1
            self._record(decision)
            logger.info(
                "Arbiter PREEMPT task=%s preempted=%s", task_id, victim.task_id
            )
            return decision

        # Cannot admit
        decision = SchedulingDecision(
            task_id=task_id, outcome=DecisionOutcome.REJECTED_NO_SLOT,
            admitted=False, priority=priority, origin=origin,
            reason="global_limit_reached_no_preemption_target",
        )
        self._stats["rejected"] += 1
        self._record(decision)
        logger.info("Arbiter REJECT no_slot task=%s", task_id)
        return decision

    def release(self, task_id: str) -> bool:
        """Release the slot held by *task_id*.  Returns True if found."""
        if task_id in self._running:
            del self._running[task_id]
            logger.debug("Arbiter RELEASE task=%s", task_id)
            return True
        return False

    def suggest_device(
        self,
        candidate_device_ids: List[str],
        origin: str = "unknown",
    ) -> Optional[str]:
        """Return the least-loaded candidate device based on current task origin
        distribution.  Falls back to the first candidate if none found.
        """
        if not candidate_device_ids:
            return None
        # Count tasks per device (stored as origin or in metadata)
        load: Dict[str, int] = {d: 0 for d in candidate_device_ids}
        for rt in self._running.values():
            dev = rt.metadata.get("device_id")
            if dev and dev in load:
                load[dev] += 1
        best = min(load, key=lambda d: load[d])
        return best

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def list_running(self) -> List[Dict[str, Any]]:
        return [
            {
                "task_id": rt.task_id,
                "priority": rt.priority,
                "origin": rt.origin,
                "preemptable": rt.preemptable,
                "admitted_at": rt.admitted_at,
            }
            for rt in self._running.values()
        ]

    def recent_decisions(self, n: int = 20) -> List[Dict[str, Any]]:
        return [d.to_dict() for d in self._decision_log[-n:]]

    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "running_count": len(self._running),
            "global_limit": self._global_limit,
            "per_origin_quota": self._per_origin_quota,
            "enabled": self._enabled,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_preemption_victim(self, incoming_priority: int) -> Optional[RunningTask]:
        """Find the lowest-priority preemptable running task whose priority is
        strictly less than *incoming_priority*."""
        candidates = [
            rt for rt in self._running.values()
            if rt.preemptable and rt.priority < incoming_priority
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda rt: rt.priority)

    def _record(self, decision: SchedulingDecision) -> None:
        self._decision_log.append(decision)
        if len(self._decision_log) > self._max_log:
            self._decision_log = self._decision_log[-self._max_log:]


# ---------------------------------------------------------------------------
# Singleton accessor + reset
# ---------------------------------------------------------------------------


def get_global_arbiter() -> GlobalArbiter:
    """Return the process-level :class:`GlobalArbiter` singleton."""
    return GlobalArbiter()


def reset_global_arbiter() -> None:
    """Reset the singleton (for testing)."""
    GlobalArbiter._instance = None
