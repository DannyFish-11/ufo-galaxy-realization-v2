#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/continuation_rebind_registry.py
========================================
PR-2: Continuation / Waiter Cross-Restart Rebind Registry — closes the
dispatch-result-return control chain after V2 restart.

Background
----------
After a V2 process restart, in-memory :class:`asyncio.Future` waiters
registered with :class:`~core.canonical_completion_ingress.CanonicalCompletionIngress`
are lost.  PR-1 added :meth:`~core.runtime_restart_recovery
.RuntimeRestartRecoveryCoordinator._reconcile_continuation_waiters` which
**fails** stale futures with a ``RuntimeError("restart_recovery")``.  This
unblocks callers so they do not hang indefinitely.

However, failing a future is only the **first half** of the closed loop.
The second half is:

    *When the recovered task is re-dispatched and a new waiter registers for
    the same task_id, the registry must know that this is a REBIND — a
    continuation of a pre-restart dispatch — so the caller can handle the
    result correctly.*

Without this registry, the caller that received the restart error has no way
to know when the re-dispatch completes.  The control chain "restarts from
scratch" rather than continuing the original semantic.

This module closes that gap by:

1. :class:`ContinuationRebindRecord` — records that a pre-restart waiter for
   a given ``task_id`` was failed at recovery, and that re-dispatch is pending.

2. :class:`ContinuationRebindRegistry` — thread-safe registry mapping
   ``task_id`` → :class:`ContinuationRebindRecord`.  The recovery coordinator
   calls :meth:`register_rebind_pending` for every task whose waiter was
   failed.  When the re-dispatched result arrives and a new
   :meth:`register_new_waiter` is called, the registry records the rebind and
   marks the loop closed.

3. :func:`get_continuation_rebind_registry` / :func:`reset_continuation_rebind_registry`
   — process-level singleton management.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Graceful degradation** — every method returns a safe value on failure.
- **Thread-safe** — a per-registry :class:`threading.Lock` guards all state.
- **Observable** — :meth:`~ContinuationRebindRegistry.snapshot` returns a
  JSON-serialisable view for operator observability.

Sentinels
---------
:data:`CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY`
    Module-level authority sentinel.
:data:`CONTINUATION_REBIND_CLOSED_LOOP_POLICY`
    Affirms the closed-loop semantic: failed waiter → re-dispatch → rebind
    → result delivery constitutes the complete continuation closure.
:data:`REBIND_MUST_USE_SAME_TASK_ID_POLICY`
    Affirms the task_id is the stable correlation key across restart.
:data:`REBIND_IS_IDEMPOTENT_POLICY`
    Affirms that calling register_rebind_pending more than once for the same
    task_id is safe and idempotent.

Public API
----------
Classes:
    :class:`ContinuationRebindRecord`
    :class:`ContinuationRebindRegistry`

Functions:
    :func:`get_continuation_rebind_registry`
    :func:`reset_continuation_rebind_registry`
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ContinuationRebindRegistry")

__all__ = [
    # Authority / policy sentinels
    "CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY",
    "CONTINUATION_REBIND_CLOSED_LOOP_POLICY",
    "REBIND_MUST_USE_SAME_TASK_ID_POLICY",
    "REBIND_IS_IDEMPOTENT_POLICY",
    "CONTINUATION_REBIND_REGISTRY_PR2_SENTINEL",
    # Classes
    "RebindState",
    "ContinuationRebindRecord",
    "ContinuationRebindRegistry",
    # Functions
    "get_continuation_rebind_registry",
    "reset_continuation_rebind_registry",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY: str = (
    "CONTINUATION_REBIND_REGISTRY::PR2_AUTHORITY_V1: "
    "core.continuation_rebind_registry is the canonical registry for "
    "tracking the state of continuation/waiter rebind across V2 restart. "
    "It records which task IDs had their in-memory futures failed at recovery "
    "and whether the re-dispatched result has been delivered.  (PR-2)"
)
"""Module-level authority sentinel."""

CONTINUATION_REBIND_CLOSED_LOOP_POLICY: str = (
    "CONTINUATION_REBIND_REGISTRY::CLOSED_LOOP_POLICY_V1: "
    "The complete continuation closed loop after V2 restart is: "
    "(1) pre-restart: caller registers future via CanonicalCompletionIngress; "
    "(2) restart: RuntimeRestartRecoveryCoordinator fails the stale future "
    "    with RuntimeError('restart_recovery') and calls "
    "    register_rebind_pending(task_id); "
    "(3) re-dispatch: recovered task is re-dispatched to the device; "
    "(4) rebind: new waiter is registered for the same task_id via "
    "    register_new_waiter(task_id, future); "
    "(5) result delivery: Android returns result, future is resolved. "
    "Steps (1)-(5) constitute the full closed loop.  "
    "The ContinuationRebindRegistry makes step (4) traceable and verifiable.  "
    "(PR-2)"
)
"""Policy: the five-step closed loop for continuation rebind after restart."""

REBIND_MUST_USE_SAME_TASK_ID_POLICY: str = (
    "CONTINUATION_REBIND_REGISTRY::SAME_TASK_ID_POLICY_V1: "
    "The task_id is the stable correlation key across V2 restart.  When a "
    "recovered task (disposition RESUMABLE or REPLAY_ONLY) is re-dispatched, "
    "it MUST use the same task_id that was registered in the lifecycle snapshot. "
    "This allows ContinuationRebindRegistry.register_new_waiter(task_id) to "
    "correlate the new future with the pre-restart dispatch.  (PR-2)"
)
"""Policy: same task_id must be used for rebind correlation."""

REBIND_IS_IDEMPOTENT_POLICY: str = (
    "CONTINUATION_REBIND_REGISTRY::IDEMPOTENT_POLICY_V1: "
    "Calling register_rebind_pending(task_id) more than once for the same "
    "task_id is safe and idempotent.  The first call sets the record; "
    "subsequent calls are no-ops with a debug log.  This allows the recovery "
    "coordinator to be re-run safely without creating duplicate records.  "
    "(PR-2)"
)
"""Policy: register_rebind_pending is idempotent."""

CONTINUATION_REBIND_REGISTRY_PR2_SENTINEL: str = (
    "CONTINUATION_REBIND_REGISTRY::PR2_INTEGRATED_V1: "
    "PR-2 continuation rebind registry is active.  "
    "RuntimeRestartRecoveryCoordinator calls register_rebind_pending() for "
    "every RESUMABLE/REPLAY_ONLY task whose waiter was failed.  "
    "When a new waiter is registered for the same task_id, "
    "register_new_waiter() is called to close the loop."
)
"""Integration sentinel confirming PR-2 continuation rebind registry is live."""


# ---------------------------------------------------------------------------
# RebindState
# ---------------------------------------------------------------------------


class RebindState(str, Enum):
    """State of a continuation rebind record.

    pending_rebind
        The pre-restart future was failed; waiting for re-dispatch and a new
        waiter to be registered.
    rebound
        A new waiter has been registered for the same task_id after re-dispatch.
    completed
        The re-dispatched result has been delivered and the future resolved.
    """

    pending_rebind = "pending_rebind"
    rebound = "rebound"
    completed = "completed"


# ---------------------------------------------------------------------------
# ContinuationRebindRecord
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ContinuationRebindRecord:
    """Record of a single continuation rebind lifecycle.

    Attributes
    ----------
    record_id:
        Unique identifier for this record.
    task_id:
        The task whose pre-restart future was failed.
    state:
        Current state of the rebind.
    failed_at:
        Unix epoch seconds when the pre-restart future was failed.
    rebound_at:
        Unix epoch seconds when the new waiter was registered.  None until
        the rebind occurs.
    completed_at:
        Unix epoch seconds when the re-dispatched result was delivered.
        None until completion.
    recovery_id:
        Optional identifier of the recovery run that failed the original future.
    metadata:
        Arbitrary extensibility bag.
    """

    record_id: str = dataclasses.field(
        default_factory=lambda: f"crr_{uuid.uuid4().hex[:12]}"
    )
    task_id: str = ""
    state: RebindState = RebindState.pending_rebind
    failed_at: float = dataclasses.field(default_factory=time.time)
    rebound_at: Optional[float] = None
    completed_at: Optional[float] = None
    recovery_id: Optional[str] = None
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "state": self.state.value,
            "failed_at": self.failed_at,
            "rebound_at": self.rebound_at,
            "completed_at": self.completed_at,
            "recovery_id": self.recovery_id,
            "metadata": dict(self.metadata),
            "authority": CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ContinuationRebindRecord":
        """Reconstruct from a dict.

        Notes
        -----
        If ``record_id`` is missing, a new unique ID is generated (acceptable
        since ``record_id`` is an internal correlation identifier; the stable
        key used by the registry is ``task_id``).  If ``task_id`` is missing,
        a warning is emitted — the record will have an empty ``task_id`` and
        will not be indexable by the registry.
        """
        task_id = str(d.get("task_id") or "")
        if not task_id:
            logger.warning(
                "ContinuationRebindRecord.from_dict: missing task_id — "
                "reconstructed record will have empty task_id and cannot be "
                "indexed by ContinuationRebindRegistry.  Dict keys: %s",
                list(d.keys()),
            )
        return cls(
            record_id=d.get("record_id") or f"crr_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            state=RebindState(d.get("state") or RebindState.pending_rebind.value),
            failed_at=float(d.get("failed_at") or time.time()),
            rebound_at=d.get("rebound_at"),
            completed_at=d.get("completed_at"),
            recovery_id=d.get("recovery_id"),
            metadata=dict(d.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# ContinuationRebindRegistry
# ---------------------------------------------------------------------------


class ContinuationRebindRegistry:
    """Thread-safe registry for continuation rebind state across V2 restart.

    Tracks the three-phase lifecycle for each recovered task:

    1. ``pending_rebind`` — future was failed at recovery; re-dispatch pending.
    2. ``rebound`` — new waiter registered for the re-dispatched task.
    3. ``completed`` — result delivered; loop closed.

    See :data:`CONTINUATION_REBIND_CLOSED_LOOP_POLICY` for the full semantic.
    """

    def __init__(self) -> None:
        self._lock: threading.Lock = threading.Lock()
        self._records: Dict[str, ContinuationRebindRecord] = {}

    # ── Registration ─────────────────────────────────────────────────────

    def register_rebind_pending(
        self,
        task_id: str,
        *,
        recovery_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContinuationRebindRecord:
        """Record that the pre-restart future for *task_id* was failed.

        Called by :class:`~core.runtime_restart_recovery
        .RuntimeRestartRecoveryCoordinator` after it resolves a stale waiter.

        Idempotent: if a record for *task_id* already exists, returns the
        existing record unchanged.  See :data:`REBIND_IS_IDEMPOTENT_POLICY`.

        Parameters
        ----------
        task_id:
            The task whose stale future was failed.
        recovery_id:
            Optional identifier of the recovery run.
        metadata:
            Optional extra metadata.

        Returns
        -------
        :class:`ContinuationRebindRecord`
            The new (or existing) record.
        """
        with self._lock:
            if task_id in self._records:
                logger.debug(
                    "ContinuationRebindRegistry.register_rebind_pending: "
                    "task_id=%s already has record (idempotent no-op). "
                    "See REBIND_IS_IDEMPOTENT_POLICY.",
                    task_id,
                )
                return self._records[task_id]

            rec = ContinuationRebindRecord(
                task_id=task_id,
                state=RebindState.pending_rebind,
                recovery_id=recovery_id,
                metadata=dict(metadata or {}),
            )
            self._records[task_id] = rec
            logger.info(
                "ContinuationRebindRegistry: task_id=%s → pending_rebind "
                "(waiter failed at restart; awaiting re-dispatch). "
                "See CONTINUATION_REBIND_CLOSED_LOOP_POLICY.",
                task_id,
            )
            return rec

    def register_new_waiter(
        self,
        task_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ContinuationRebindRecord]:
        """Record that a new waiter has been registered for *task_id* after re-dispatch.

        Called when the re-dispatched task registers a new future in
        :class:`~core.canonical_completion_ingress.CanonicalCompletionIngress`.

        If no pending-rebind record exists for *task_id*, returns ``None``
        (the task was not a recovery rebind).

        Parameters
        ----------
        task_id:
            The task being re-dispatched.
        metadata:
            Optional extra metadata.

        Returns
        -------
        :class:`ContinuationRebindRecord` | None
            Updated record, or None if task_id was not a rebind.
        """
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return None
            if rec.state != RebindState.pending_rebind:
                logger.debug(
                    "ContinuationRebindRegistry.register_new_waiter: "
                    "task_id=%s state=%s (not pending_rebind — no-op)",
                    task_id,
                    rec.state.value,
                )
                return rec
            rec.state = RebindState.rebound
            rec.rebound_at = time.time()
            if metadata:
                rec.metadata.update(metadata)
            logger.info(
                "ContinuationRebindRegistry: task_id=%s → rebound "
                "(new waiter registered; re-dispatch in progress). "
                "See CONTINUATION_REBIND_CLOSED_LOOP_POLICY.",
                task_id,
            )
            return rec

    def mark_completed(
        self,
        task_id: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[ContinuationRebindRecord]:
        """Record that the re-dispatched result for *task_id* was delivered.

        Marks the rebind record as ``completed``, closing the control chain
        loop.  See :data:`CONTINUATION_REBIND_CLOSED_LOOP_POLICY`.

        Returns ``None`` if no record exists for *task_id*.
        """
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return None
            rec.state = RebindState.completed
            rec.completed_at = time.time()
            if metadata:
                rec.metadata.update(metadata)
            logger.info(
                "ContinuationRebindRegistry: task_id=%s → completed "
                "(result delivered; control chain loop closed). "
                "See CONTINUATION_REBIND_CLOSED_LOOP_POLICY.",
                task_id,
            )
            return rec

    # ── Queries ──────────────────────────────────────────────────────────

    def get_record(self, task_id: str) -> Optional[ContinuationRebindRecord]:
        """Return the rebind record for *task_id*, or None."""
        with self._lock:
            return self._records.get(task_id)

    def is_pending_rebind(self, task_id: str) -> bool:
        """Return True if *task_id* is waiting for a rebind (re-dispatch pending)."""
        with self._lock:
            rec = self._records.get(task_id)
            return rec is not None and rec.state == RebindState.pending_rebind

    def is_loop_closed(self, task_id: str) -> bool:
        """Return True if the complete continuation loop for *task_id* is closed."""
        with self._lock:
            rec = self._records.get(task_id)
            return rec is not None and rec.state == RebindState.completed

    def pending_rebind_count(self) -> int:
        """Return the number of tasks still waiting for a rebind."""
        with self._lock:
            return sum(
                1 for r in self._records.values()
                if r.state == RebindState.pending_rebind
            )

    def rebound_count(self) -> int:
        """Return the number of tasks that have had a new waiter registered."""
        with self._lock:
            return sum(
                1 for r in self._records.values()
                if r.state == RebindState.rebound
            )

    def completed_count(self) -> int:
        """Return the number of tasks whose continuation loop has been fully closed."""
        with self._lock:
            return sum(
                1 for r in self._records.values()
                if r.state == RebindState.completed
            )

    def list_pending_task_ids(self) -> List[str]:
        """Return a list of task IDs that are still in pending_rebind state."""
        with self._lock:
            return [
                tid for tid, r in self._records.items()
                if r.state == RebindState.pending_rebind
            ]

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of the registry state."""
        with self._lock:
            records_list = [r.to_dict() for r in self._records.values()]
        return {
            "total": len(records_list),
            "pending_rebind": sum(
                1 for r in records_list if r["state"] == RebindState.pending_rebind.value
            ),
            "rebound": sum(
                1 for r in records_list if r["state"] == RebindState.rebound.value
            ),
            "completed": sum(
                1 for r in records_list if r["state"] == RebindState.completed.value
            ),
            "records": records_list,
            "authority": CONTINUATION_REBIND_REGISTRY_IS_AUTHORITY,
        }

    def reset(self) -> None:
        """Clear all records (test isolation only)."""
        with self._lock:
            self._records.clear()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_registry_instance: Optional[ContinuationRebindRegistry] = None
_registry_lock: threading.Lock = threading.Lock()


def get_continuation_rebind_registry() -> ContinuationRebindRegistry:
    """Return the process-level :class:`ContinuationRebindRegistry` singleton."""
    global _registry_instance
    if _registry_instance is None:
        with _registry_lock:
            if _registry_instance is None:
                _registry_instance = ContinuationRebindRegistry()
    return _registry_instance


def reset_continuation_rebind_registry() -> None:
    """Reset the singleton (for testing)."""
    global _registry_instance
    with _registry_lock:
        _registry_instance = None
