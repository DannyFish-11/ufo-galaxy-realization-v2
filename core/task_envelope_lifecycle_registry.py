#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/task_envelope_lifecycle_registry.py
=========================================
PR-S5 — Unify Task Envelope / Result Lifecycle Semantics

Defines the **canonical** task-envelope lifecycle registry for the server
runtime.  A single instance of :class:`TaskEnvelopeLifecycleRegistry` tracks
every in-flight envelope from gateway ingress through routing, device
dispatch, and result completion.

Design goals
------------
1. **Single ownership model** — one registry, one place where futures are
   registered and resolved, so there is no ambiguity about who "owns" a
   pending task.
2. **Correlation propagated** — task_id and trace_id are the canonical
   correlation keys.  Every stage that touches an envelope reads them from
   the envelope itself, not from an ad-hoc dict key.
3. **Envelope-driven timeouts** — timeout duration comes from
   ``envelope.timeout`` (defaulting to 30 s); callers no longer hard-code
   magic constants.
4. **Reconnect / resume awareness** — when a device reconnects the registry
   can return all pending envelopes whose primary target matches that device_id
   so the caller can choose to retry or surface them.
5. **Stable lifecycle ownership enum** — :class:`LifecycleOwner` documents
   which stage holds authority at any given moment.

Architectural note
------------------
This registry is *not* an execution engine or workflow scheduler.  It is a
lightweight in-memory bookkeeping layer that replaces several ad-hoc
``Dict[str, asyncio.Future]`` dicts scattered across the gateway subsystem
(``GatewayNATSAdapter._pending``, ``DeviceRouter._task_events``, etc.).

Those legacy dicts remain for backward compatibility but are now documented
as **compat surfaces** in ``legacy_paths.py``.  New code MUST use this
registry.

Usage::

    from core.task_envelope_lifecycle_registry import (
        get_lifecycle_registry,
        LifecycleOwner,
    )
    from core.schemas.task_envelope import TaskEnvelope

    registry = get_lifecycle_registry()

    envelope = TaskEnvelope(tool_name="open_app", args={"app": "calendar"})
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    registry.register(envelope, future=future, owner=LifecycleOwner.DEVICE_DISPATCH)

    # … dispatch to device …

    # When device responds:
    registry.complete(envelope.task_id, {"success": True, "result": "ok"})

    result = await asyncio.wait_for(future, timeout=envelope.timeout)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TaskEnvelopeLifecycleRegistry")

__all__ = [
    "LifecycleOwner",
    "PendingEnvelopeRecord",
    "LifecycleRegistrySnapshot",
    "TaskEnvelopeLifecycleRegistry",
    "get_lifecycle_registry",
    "reset_lifecycle_registry",
]

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 30.0
_MAX_RECORDS = 500  # max completed-record history kept


class LifecycleOwner(str, Enum):
    """Canonical ownership stages for an in-flight task envelope.

    Each value identifies the subsystem that is responsible for the envelope
    at a given moment.  The value is stored in :class:`PendingEnvelopeRecord`
    so that observability tooling can pinpoint where a task got stuck.

    Attributes
    ----------
    GATEWAY_INGRESS:
        The gateway received the request and built the initial envelope from
        the raw inbound message (e.g. WebSocket frame, NATS payload, HTTP
        body).  No routing decision has been made yet.
    ROUTING:
        The :class:`~galaxy_gateway.device_router.DeviceRouter` (or
        :class:`~core.command_router.CommandRouter`) is evaluating which
        execution substrate to use.
    DEVICE_DISPATCH:
        The envelope has been sent to a specific device via WebSocket or NATS
        and the server is waiting for a ``task_result`` response.
    CROSS_DEVICE:
        A cross-device orchestration is in progress; multiple sub-envelopes
        may be pending simultaneously under a single parent task_id.
    RESULT_COMPLETION:
        The result has arrived and is in the process of being written back to
        the caller (future resolution, WebSocket push, NATS reply).
    """

    GATEWAY_INGRESS = "gateway_ingress"
    ROUTING = "routing"
    DEVICE_DISPATCH = "device_dispatch"
    CROSS_DEVICE = "cross_device"
    RESULT_COMPLETION = "result_completion"


# ---------------------------------------------------------------------------
# PendingEnvelopeRecord
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class PendingEnvelopeRecord:
    """A point-in-time snapshot of a single pending task envelope.

    Parameters
    ----------
    task_id:
        Canonical task identifier (from ``envelope.task_id``).
    trace_id:
        Distributed trace identifier (from ``envelope.trace_id``).
    target_device_id:
        Primary target device (``envelope.target``).  Empty string for
        local-only tasks.
    tool_name:
        Tool / command being invoked (``envelope.tool_name``).
    owner:
        Which subsystem currently owns the envelope.
    timeout:
        Maximum wait time in seconds (from ``envelope.timeout``).
    registered_at:
        Wall-clock time when the envelope was registered (seconds since
        epoch, from :func:`time.time`).
    future:
        Optional :class:`asyncio.Future` that will be resolved when the
        task completes.  ``None`` for fire-and-forget dispatches.
    metadata:
        Arbitrary extra fields stored by the registering caller.
    """

    task_id: str
    trace_id: str
    target_device_id: str
    tool_name: str
    owner: LifecycleOwner
    timeout: float
    registered_at: float
    future: Optional[asyncio.Future] = dataclasses.field(
        default=None, repr=False, compare=False
    )
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def is_timed_out(self, now: Optional[float] = None) -> bool:
        """Return ``True`` when the wall-clock age exceeds ``self.timeout``."""
        now = now if now is not None else time.time()
        return (now - self.registered_at) >= self.timeout

    def elapsed(self, now: Optional[float] = None) -> float:
        """Return the elapsed time in seconds since registration."""
        now = now if now is not None else time.time()
        return now - self.registered_at

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict (future is excluded)."""
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "target_device_id": self.target_device_id,
            "tool_name": self.tool_name,
            "owner": self.owner.value,
            "timeout": self.timeout,
            "registered_at": self.registered_at,
            "elapsed": round(self.elapsed(), 3),
            "is_timed_out": self.is_timed_out(),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PendingEnvelopeRecord":
        """Reconstruct from a serialised dict (no future)."""
        return cls(
            task_id=d.get("task_id", ""),
            trace_id=d.get("trace_id", ""),
            target_device_id=d.get("target_device_id", ""),
            tool_name=d.get("tool_name", ""),
            owner=LifecycleOwner(d.get("owner", LifecycleOwner.GATEWAY_INGRESS.value)),
            timeout=float(d.get("timeout", _DEFAULT_TIMEOUT)),
            registered_at=float(d.get("registered_at", time.time())),
            metadata=dict(d.get("metadata", {})),
        )


# ---------------------------------------------------------------------------
# LifecycleRegistrySnapshot
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class LifecycleRegistrySnapshot:
    """Point-in-time snapshot of the lifecycle registry.

    Parameters
    ----------
    pending_count:
        Number of envelopes currently in-flight.
    timed_out_count:
        Number of currently registered envelopes whose wall-clock age
        exceeds their declared timeout.
    completed_count:
        Total number of successfully completed tasks recorded since the
        registry was created (or last reset).
    failed_count:
        Total number of failed / cancelled tasks recorded.
    pending_records:
        Serialised list of currently pending records.
    snapshot_at:
        Wall-clock time when this snapshot was taken.
    """

    pending_count: int
    timed_out_count: int
    completed_count: int
    failed_count: int
    pending_records: List[Dict[str, Any]]
    snapshot_at: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-safe dict."""
        return {
            "pending_count": self.pending_count,
            "timed_out_count": self.timed_out_count,
            "completed_count": self.completed_count,
            "failed_count": self.failed_count,
            "pending_records": self.pending_records,
            "snapshot_at": self.snapshot_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LifecycleRegistrySnapshot":
        """Reconstruct from a serialised dict."""
        return cls(
            pending_count=int(d.get("pending_count", 0)),
            timed_out_count=int(d.get("timed_out_count", 0)),
            completed_count=int(d.get("completed_count", 0)),
            failed_count=int(d.get("failed_count", 0)),
            pending_records=list(d.get("pending_records", [])),
            snapshot_at=float(d.get("snapshot_at", time.time())),
        )


# ---------------------------------------------------------------------------
# TaskEnvelopeLifecycleRegistry
# ---------------------------------------------------------------------------

class TaskEnvelopeLifecycleRegistry:
    """Canonical in-memory registry for in-flight task envelopes.

    Thread-safety note
    ------------------
    This implementation is **not** thread-safe by design — the gateway
    subsystem is asyncio-based.  All callers are expected to be running in
    the same event loop.  For test isolation use
    :func:`reset_lifecycle_registry`.

    Attributes
    ----------
    _pending : Dict[str, PendingEnvelopeRecord]
        Live in-flight records keyed by task_id.
    _completed : int
        Running count of successfully completed tasks.
    _failed : int
        Running count of failed / cancelled tasks.
    """

    CANONICAL_AUTHORITY = "core.task_envelope_lifecycle_registry.TaskEnvelopeLifecycleRegistry"

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._pending: Dict[str, PendingEnvelopeRecord] = {}
        self._completed: int = 0
        self._failed: int = 0
        self._max_records = max_records

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        envelope: Any,
        *,
        future: Optional[asyncio.Future] = None,
        owner: LifecycleOwner = LifecycleOwner.GATEWAY_INGRESS,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PendingEnvelopeRecord:
        """Register an in-flight envelope.

        Parameters
        ----------
        envelope:
            A :class:`~core.schemas.task_envelope.TaskEnvelope`.
        future:
            Optional :class:`asyncio.Future` to resolve when the task
            completes.  ``None`` for fire-and-forget dispatches.
        owner:
            Which subsystem currently owns the envelope.
        timeout:
            Override timeout in seconds.  If ``None`` the value is taken
            from ``envelope.timeout`` (default: 30 s).
        metadata:
            Arbitrary extra data to store with the record.

        Returns
        -------
        PendingEnvelopeRecord
            The record that was stored.
        """
        task_id = getattr(envelope, "task_id", None) or str(uuid.uuid4())
        trace_id = getattr(envelope, "trace_id", None) or ""
        target_device_id = getattr(envelope, "target", "") or ""
        tool_name = getattr(envelope, "tool_name", "") or ""
        _timeout = timeout if timeout is not None else getattr(envelope, "timeout", _DEFAULT_TIMEOUT)

        record = PendingEnvelopeRecord(
            task_id=task_id,
            trace_id=trace_id,
            target_device_id=target_device_id,
            tool_name=tool_name,
            owner=owner,
            timeout=float(_timeout),
            registered_at=time.time(),
            future=future,
            metadata=dict(metadata or {}),
        )
        self._pending[task_id] = record
        logger.debug(
            "lifecycle_registry.register | task_id=%s trace_id=%s owner=%s "
            "tool=%s target=%s timeout=%.1fs",
            task_id, trace_id, owner.value, tool_name, target_device_id, _timeout,
        )
        return record

    # ── Ownership transfer ────────────────────────────────────────────────────

    def transfer_ownership(
        self,
        task_id: str,
        new_owner: LifecycleOwner,
    ) -> bool:
        """Update the ownership stage for a pending record.

        Parameters
        ----------
        task_id:
            The task identifier.
        new_owner:
            The subsystem that is now responsible.

        Returns
        -------
        bool
            ``True`` if the record was found and updated; ``False`` if the
            task_id is not currently pending.
        """
        record = self._pending.get(task_id)
        if record is None:
            return False
        updated = dataclasses.replace(record, owner=new_owner)
        self._pending[task_id] = updated
        logger.debug(
            "lifecycle_registry.transfer | task_id=%s owner=%s",
            task_id, new_owner.value,
        )
        return True

    # ── Result completion ─────────────────────────────────────────────────────

    def complete(
        self,
        task_id: str,
        result: Dict[str, Any],
    ) -> bool:
        """Resolve a pending task with a successful result.

        Resolves the associated :class:`asyncio.Future` (if any) and removes
        the record from the pending table.  Increments the ``_completed``
        counter.

        Parameters
        ----------
        task_id:
            The task to complete.
        result:
            The result dict to set on the future.

        Returns
        -------
        bool
            ``True`` if a matching record was found; ``False`` otherwise.
        """
        record = self._pending.pop(task_id, None)
        if record is None:
            logger.debug(
                "lifecycle_registry.complete: no pending record for task_id=%s", task_id
            )
            return False

        self._completed += 1
        logger.info(
            "lifecycle_registry.complete | task_id=%s trace_id=%s elapsed=%.2fs",
            task_id, record.trace_id, record.elapsed(),
        )

        fut = record.future
        if fut is not None and not fut.done():
            fut.set_result(result)

        return True

    def fail(
        self,
        task_id: str,
        error: str,
    ) -> bool:
        """Mark a pending task as failed.

        Sets an exception on the associated future (if any).  Increments
        the ``_failed`` counter.

        Parameters
        ----------
        task_id:
            The task to fail.
        error:
            Human-readable error description.

        Returns
        -------
        bool
            ``True`` if a matching record was found; ``False`` otherwise.
        """
        record = self._pending.pop(task_id, None)
        if record is None:
            logger.debug(
                "lifecycle_registry.fail: no pending record for task_id=%s", task_id
            )
            return False

        self._failed += 1
        logger.warning(
            "lifecycle_registry.fail | task_id=%s trace_id=%s error=%r elapsed=%.2fs",
            task_id, record.trace_id, error[:200], record.elapsed(),
        )

        fut = record.future
        if fut is not None and not fut.done():
            fut.set_exception(RuntimeError(error))

        return True

    # ── Timeout handling ──────────────────────────────────────────────────────

    def cancel_timed_out(self) -> List[str]:
        """Cancel all pending envelopes whose wall-clock age exceeds their timeout.

        For each timed-out record:
        * The associated future (if any) is cancelled.
        * The record is removed from ``_pending``.
        * ``_failed`` is incremented.

        This method is intended to be called periodically from a background
        maintenance task (e.g. every 5–10 seconds).

        Returns
        -------
        list of str
            The task_ids that were cancelled.
        """
        now = time.time()
        cancelled_ids: List[str] = []
        for task_id, record in list(self._pending.items()):
            if record.is_timed_out(now):
                logger.warning(
                    "lifecycle_registry.timeout | task_id=%s trace_id=%s "
                    "tool=%s target=%s elapsed=%.2fs timeout=%.1fs owner=%s",
                    task_id, record.trace_id, record.tool_name,
                    record.target_device_id, record.elapsed(now),
                    record.timeout, record.owner.value,
                )
                fut = record.future
                if fut is not None and not fut.done():
                    fut.cancel()
                del self._pending[task_id]
                self._failed += 1
                cancelled_ids.append(task_id)
        return cancelled_ids

    # ── Reconnect / resume ────────────────────────────────────────────────────

    def get_pending_for_device(
        self,
        device_id: str,
    ) -> List[PendingEnvelopeRecord]:
        """Return all pending envelopes whose primary target matches *device_id*.

        Called when a device reconnects so the caller can decide whether to
        retry or surface the pending tasks to the end user.

        Parameters
        ----------
        device_id:
            The device that just reconnected.

        Returns
        -------
        list of PendingEnvelopeRecord
        """
        return [
            record
            for record in self._pending.values()
            if record.target_device_id == device_id
        ]

    def resume_for_device(
        self,
        device_id: str,
        resend_callback: Optional[Any] = None,
    ) -> List[str]:
        """Surface or retry pending envelopes for a reconnected device.

        For each pending envelope targeting *device_id*:
        * Ownership is transferred to :attr:`LifecycleOwner.DEVICE_DISPATCH`.
        * If *resend_callback* is provided it is called with the task_id and
          metadata so the caller can re-issue the WebSocket message.

        Parameters
        ----------
        device_id:
            The device that reconnected.
        resend_callback:
            Optional callable ``(task_id: str, metadata: dict) -> None``.

        Returns
        -------
        list of str
            task_ids of envelopes that were surfaced.
        """
        surfaced: List[str] = []
        for record in self.get_pending_for_device(device_id):
            self.transfer_ownership(record.task_id, LifecycleOwner.DEVICE_DISPATCH)
            surfaced.append(record.task_id)
            logger.info(
                "lifecycle_registry.resume | task_id=%s trace_id=%s device_id=%s",
                record.task_id, record.trace_id, device_id,
            )
            if resend_callback is not None:
                try:
                    resend_callback(record.task_id, record.metadata)
                except Exception as _cb_exc:
                    logger.warning(
                        "lifecycle_registry.resume: callback error for task_id=%s — %s",
                        record.task_id, _cb_exc,
                    )
        return surfaced

    # ── Queries ───────────────────────────────────────────────────────────────

    def get_record(self, task_id: str) -> Optional[PendingEnvelopeRecord]:
        """Return the pending record for *task_id*, or ``None``."""
        return self._pending.get(task_id)

    def is_pending(self, task_id: str) -> bool:
        """Return ``True`` if *task_id* is currently pending."""
        return task_id in self._pending

    def pending_count(self) -> int:
        """Return the number of currently in-flight envelopes."""
        return len(self._pending)

    def all_pending_task_ids(self) -> List[str]:
        """Return a snapshot list of currently pending task_ids."""
        return list(self._pending.keys())

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def snapshot(self) -> LifecycleRegistrySnapshot:
        """Return a point-in-time snapshot of the registry state."""
        now = time.time()
        pending_records = [r.to_dict() for r in self._pending.values()]
        timed_out_count = sum(
            1 for r in self._pending.values() if r.is_timed_out(now)
        )
        return LifecycleRegistrySnapshot(
            pending_count=len(self._pending),
            timed_out_count=timed_out_count,
            completed_count=self._completed,
            failed_count=self._failed,
            pending_records=pending_records,
            snapshot_at=now,
        )

    # ── Cancellation ──────────────────────────────────────────────────────────

    def cancel_all(self) -> int:
        """Cancel all pending envelopes.

        Intended for shutdown or test teardown.  Returns the number of
        records cancelled.
        """
        count = 0
        for task_id, record in list(self._pending.items()):
            fut = record.future
            if fut is not None and not fut.done():
                fut.cancel()
            del self._pending[task_id]
            count += 1
        return count


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[TaskEnvelopeLifecycleRegistry] = None


def get_lifecycle_registry() -> TaskEnvelopeLifecycleRegistry:
    """Return (or lazily create) the module-level :class:`TaskEnvelopeLifecycleRegistry`."""
    global _registry
    if _registry is None:
        _registry = TaskEnvelopeLifecycleRegistry()
    return _registry


def reset_lifecycle_registry() -> None:
    """Reset the module-level singleton (for test isolation)."""
    global _registry
    if _registry is not None:
        _registry.cancel_all()
    _registry = None
