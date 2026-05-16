#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy – Async Task Queue (Phase 5.3)
=======================================

A general-purpose async task queue providing:

* **Configurable concurrency** – a semaphore limits simultaneous task
  execution to ``max_concurrent_tasks``.
* **Backpressure** – when the queue fill ratio exceeds
  ``backpressure_threshold``, new submissions are rejected with
  :class:`QueueFullError` (``reject_new`` strategy) or the oldest waiting
  item is dropped (``drop_oldest`` strategy).
* **Per-task timeout** – each task has an individual deadline.
* **Metrics** – queue depth, processed count, rejected count, and running
  average latency are tracked and exposed via :meth:`AsyncTaskQueue.stats`.
* **Audit** – optional integration with
  :class:`~core.control_plane.audit_ledger.AuditLedger`.

Design
------
* Built on :class:`asyncio.Queue` + :class:`asyncio.Semaphore`.
* Worker coroutines are spawned lazily (up to *max_concurrent_tasks*)
  when the queue is started.
* :meth:`submit` is the only way to enqueue work; results are returned via
  :class:`asyncio.Future` so callers can ``await`` them or ignore them for
  fire-and-forget semantics.

Usage
-----
    from core.queueing.async_queue import AsyncTaskQueue, QueueFullError

    queue = AsyncTaskQueue(max_queue_size=100, max_concurrent=4)
    await queue.start()

    async def my_tool(x: int) -> int:
        await asyncio.sleep(0.1)
        return x * 2

    future = await queue.submit(my_tool, 21)
    result = await future       # 42

    await queue.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger("Galaxy.Queueing.AsyncTaskQueue")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class QueueFullError(Exception):
    """Raised when the queue is saturated and a new task cannot be accepted."""

    def __init__(self, queue_size: int, max_size: int) -> None:
        self.queue_size = queue_size
        self.max_size = max_size
        super().__init__(
            f"Queue saturated: {queue_size}/{max_size} items pending"
        )


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class QueueTask:
    """A single unit of work in the queue."""

    task_id: str = field(default_factory=lambda: f"qt_{uuid.uuid4().hex[:8]}")
    fn: Callable[..., Awaitable[Any]] = field(repr=False, default=None)  # type: ignore[assignment]
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 60.0
    submitted_at: float = field(default_factory=time.monotonic)
    future: asyncio.Future = field(default=None, repr=False)  # type: ignore[assignment]


@dataclass
class QueueStats:
    """Snapshot of queue metrics."""

    queue_depth: int
    running: int
    max_concurrent: int
    max_queue_size: int
    total_submitted: int
    total_completed: int
    total_failed: int
    total_rejected: int
    avg_latency_ms: float
    backpressure_active: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "queue_depth": self.queue_depth,
            "running": self.running,
            "max_concurrent": self.max_concurrent,
            "max_queue_size": self.max_queue_size,
            "total_submitted": self.total_submitted,
            "total_completed": self.total_completed,
            "total_failed": self.total_failed,
            "total_rejected": self.total_rejected,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "backpressure_active": self.backpressure_active,
            "utilisation": round(self.queue_depth / max(self.max_queue_size, 1), 4),
        }


# ---------------------------------------------------------------------------
# AsyncTaskQueue
# ---------------------------------------------------------------------------

class AsyncTaskQueue:
    """Bounded async task queue with configurable concurrency and backpressure.

    Parameters
    ----------
    max_queue_size:
        Maximum number of tasks that may wait in the queue.
    max_concurrent:
        Maximum number of tasks that may execute simultaneously.
    task_timeout:
        Default per-task deadline in seconds.
    backpressure_threshold:
        Fill-ratio (0–1) above which new tasks are rejected.
    shed_strategy:
        ``"reject_new"`` raises :class:`QueueFullError`; ``"drop_oldest"``
        drops the head of the queue instead.
    ledger:
        Optional :class:`~core.control_plane.audit_ledger.AuditLedger`.
    """

    def __init__(
        self,
        max_queue_size: int = 500,
        max_concurrent: int = 20,
        task_timeout: float = 60.0,
        backpressure_threshold: float = 0.8,
        shed_strategy: str = "reject_new",
        ledger: Optional[Any] = None,
    ) -> None:
        self._max_queue_size = max_queue_size
        self._max_concurrent = max_concurrent
        self._task_timeout = task_timeout
        self._backpressure_threshold = backpressure_threshold
        self._shed_strategy = shed_strategy
        self._ledger = ledger

        self._queue: asyncio.Queue[QueueTask] = asyncio.Queue(maxsize=max_queue_size)
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(max_concurrent)
        self._workers: List[asyncio.Task] = []
        self._running: int = 0
        self._lock = asyncio.Lock()

        # Metrics
        self._total_submitted = 0
        self._total_completed = 0
        self._total_failed = 0
        self._total_rejected = 0
        self._latency_samples: List[float] = []   # last N samples (ms)
        self._max_latency_samples = 500

        self._started = False
        self._stopping = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start *max_concurrent* worker coroutines."""
        if self._started:
            return
        self._started = True
        self._stopping = False
        for _ in range(self._max_concurrent):
            worker = asyncio.create_task(self._worker())
            self._workers.append(worker)
        logger.info(
            "AsyncTaskQueue started: max_queue=%d max_concurrent=%d",
            self._max_queue_size, self._max_concurrent,
        )

    async def stop(self, timeout: float = 10.0) -> None:
        """Drain pending tasks and stop all workers."""
        self._stopping = True
        # Drain: send sentinel None for each worker
        for _ in self._workers:
            try:
                self._queue.put_nowait(None)  # type: ignore[arg-type]
            except asyncio.QueueFull:
                pass
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._workers, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            for w in self._workers:
                w.cancel()
        self._workers.clear()
        self._started = False
        logger.info("AsyncTaskQueue stopped.")

    async def force_stop(self) -> None:
        """Cancel all workers immediately without draining the queue.

        Intended for test cleanup or emergency shutdown scenarios.
        """
        self._stopping = True
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        self._started = False

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------

    async def submit(
        self,
        fn: Callable[..., Awaitable[Any]],
        *args: Any,
        timeout: Optional[float] = None,
        task_id: Optional[str] = None,
        **kwargs: Any,
    ) -> asyncio.Future:
        """Enqueue *fn* for execution.

        Returns an :class:`asyncio.Future` that resolves to the return value
        of *fn* (or the exception raised by it).

        Raises
        ------
        QueueFullError
            When the queue is at its backpressure threshold and the shed
            strategy is ``reject_new``.
        RuntimeError
            When the queue has not been started yet.
        """
        if not self._started:
            raise RuntimeError("AsyncTaskQueue.start() must be called before submit()")

        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()

        async with self._lock:
            current_depth = self._queue.qsize()
            fill_ratio = current_depth / self._max_queue_size
            backpressure = fill_ratio >= self._backpressure_threshold

            if backpressure:
                if self._shed_strategy == "reject_new":
                    self._total_rejected += 1
                    self._emit_queue_metric()
                    raise QueueFullError(current_depth, self._max_queue_size)

                if self._shed_strategy == "drop_oldest":
                    try:
                        dropped = self._queue.get_nowait()
                        if dropped is not None:
                            dropped.future.set_exception(
                                QueueFullError(current_depth, self._max_queue_size)
                            )
                        self._total_rejected += 1
                        logger.warning(
                            "Backpressure: dropped oldest task %s",
                            dropped.task_id if dropped else "sentinel",
                        )
                    except asyncio.QueueEmpty:
                        pass

            qt = QueueTask(
                task_id=task_id or f"qt_{uuid.uuid4().hex[:8]}",
                fn=fn,
                args=args,
                kwargs=kwargs,
                timeout=timeout if timeout is not None else self._task_timeout,
                future=future,
            )
            self._total_submitted += 1

        # Put outside the lock to avoid blocking
        await self._queue.put(qt)
        return future

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------

    async def _worker(self) -> None:
        """Pull tasks from the queue and execute them under the semaphore."""
        while not self._stopping:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if item is None:  # sentinel
                self._queue.task_done()
                break

            task = item
            async with self._semaphore:
                async with self._lock:
                    self._running += 1
                start = time.monotonic()
                try:
                    result = await asyncio.wait_for(
                        task.fn(*task.args, **task.kwargs),
                        timeout=task.timeout,
                    )
                    if not task.future.done():
                        task.future.set_result(result)
                    async with self._lock:
                        self._total_completed += 1
                except asyncio.TimeoutError as exc:
                    if not task.future.done():
                        task.future.set_exception(
                            TimeoutError(f"Task {task.task_id} timed out after {task.timeout}s")
                        )
                    async with self._lock:
                        self._total_failed += 1
                    logger.warning("Task %s timed out", task.task_id)
                except Exception as exc:
                    if not task.future.done():
                        task.future.set_exception(exc)
                    async with self._lock:
                        self._total_failed += 1
                    logger.exception("Task %s failed: %s", task.task_id, exc)
                finally:
                    elapsed_ms = (time.monotonic() - start) * 1000
                    async with self._lock:
                        self._running -= 1
                        self._latency_samples.append(elapsed_ms)
                        if len(self._latency_samples) > self._max_latency_samples:
                            self._latency_samples = self._latency_samples[-self._max_latency_samples:]
                    self._queue.task_done()
                    self._emit_queue_metric()

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def stats(self) -> QueueStats:
        """Return a snapshot of current queue metrics."""
        depth = self._queue.qsize()
        fill_ratio = depth / self._max_queue_size
        avg_latency = (
            sum(self._latency_samples) / len(self._latency_samples)
            if self._latency_samples
            else 0.0
        )
        return QueueStats(
            queue_depth=depth,
            running=self._running,
            max_concurrent=self._max_concurrent,
            max_queue_size=self._max_queue_size,
            total_submitted=self._total_submitted,
            total_completed=self._total_completed,
            total_failed=self._total_failed,
            total_rejected=self._total_rejected,
            avg_latency_ms=avg_latency,
            backpressure_active=fill_ratio >= self._backpressure_threshold,
        )

    def _emit_queue_metric(self) -> None:
        """Emit queue metrics to the audit ledger if available."""
        if self._ledger is None:
            return
        try:
            from core.control_plane.audit_ledger import EventType, Severity
            s = self.stats()
            self._ledger.append(
                event_type=EventType.QUEUE_METRIC,
                severity=Severity.DEBUG,
                source="async_queue",
                message=f"queue_depth={s.queue_depth} running={s.running} avg_latency={s.avg_latency_ms:.1f}ms",
                payload=s.to_dict(),
            )
        except Exception:
            logger.debug("Failed to emit queue metric to audit ledger", exc_info=True)
