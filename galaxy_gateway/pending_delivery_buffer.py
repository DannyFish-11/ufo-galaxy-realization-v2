"""
galaxy_gateway/pending_delivery_buffer.py
==========================================
Pending-delivery buffer for Android WebSocket messages.

WHY THIS EXISTS
---------------
``AndroidBridge.send_to_device()`` returns ``None`` when the target device is
temporarily disconnected.  Under the prior behaviour those messages were
silently dropped — no retry, no record.  The result was:

* In-flight tasks dispatched shortly before a disconnect were permanently lost.
* The orchestration layer had no opportunity to re-deliver them after the
  device reconnected.
* This was the primary cause of ``INFLIGHT_TASK_LOSS_ON_DISCONNECT = True``
  in the cross-device integration reality surface.

DESIGN
------
``PendingDeliveryBuffer`` is a per-device FIFO queue of undelivered messages.
When ``AndroidBridge.send_to_device()`` finds a device disconnected it may
call ``buffer.enqueue(device_id, message)`` to park the message.  When
``AndroidBridge.reconnect_device()`` re-establishes the WebSocket it calls
``buffer.flush(device_id)`` to drain all queued messages into the live
connection.

Guarantees
~~~~~~~~~~
* **Capacity limit** — each per-device queue is capped at
  ``PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE`` messages (default 32).  Oldest
  messages are evicted when the cap is exceeded so the buffer never causes
  unbounded memory growth.
* **TTL** — each buffered message carries an enqueue timestamp.  Flush skips
  (and discards) messages older than ``PENDING_DELIVERY_TTL_SECONDS`` (default
  60 s, i.e. safely beyond the 30 s command timeout).
* **Thread-safety** — all mutations are protected by ``asyncio.Lock`` because
  the buffer is shared across concurrent coroutines within a single event loop.
* **In-process only** — the buffer is not durable.  A V2 process restart
  causes pending messages to be lost.  Callers that need durability must
  implement their own persistence layer.

INTEGRATION POINTS
------------------
* Enqueue path: ``AndroidBridge.send_to_device()`` (device offline → buffer).
* Flush path: ``AndroidBridge.reconnect_device()`` (on successful reconnect).
* Expiry sweep: ``AndroidBridge.cleanup_stale_devices()`` calls
  ``buffer.purge_expired()`` so stale entries don't linger after a device
  is cleaned up.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants (overridable via environment for tests)
# ---------------------------------------------------------------------------

#: Maximum number of pending messages per device.  Oldest messages are
#: evicted when this limit is reached.
PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE: int = 32

#: Buffered messages older than this many seconds are discarded on flush.
#: Kept above the default V2 command_timeout (30 s) so that genuinely
#: in-flight tasks survive brief network blips, but stale payloads from
#: long disconnections are not re-delivered.
PENDING_DELIVERY_TTL_SECONDS: float = 60.0


class _BufferedMessage:
    """A single message parked in the pending-delivery buffer."""

    __slots__ = ("message", "enqueued_at", "attempt_count")

    def __init__(self, message: Dict[str, Any]) -> None:
        self.message: Dict[str, Any] = message
        self.enqueued_at: float = time.monotonic()
        self.attempt_count: int = 0

    def is_expired(self, ttl: float = PENDING_DELIVERY_TTL_SECONDS) -> bool:
        return (time.monotonic() - self.enqueued_at) > ttl


class PendingDeliveryBuffer:
    """Thread-safe, per-device pending message buffer.

    Parameters
    ----------
    max_queue_per_device:
        Hard cap on the number of pending messages per device queue.
        Oldest entries are evicted silently when the cap is exceeded.
    ttl_seconds:
        Messages older than this many seconds are discarded on flush
        and on explicit :meth:`purge_expired` calls.
    """

    def __init__(
        self,
        max_queue_per_device: int = PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE,
        ttl_seconds: float = PENDING_DELIVERY_TTL_SECONDS,
    ) -> None:
        self._max_queue: int = max_queue_per_device
        self._ttl: float = ttl_seconds
        # device_id → deque[_BufferedMessage]
        self._queues: Dict[str, Deque[_BufferedMessage]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

        # Observable counters — readable by tests and monitoring.
        self.enqueued_total: int = 0
        self.delivered_total: int = 0
        self.evicted_total: int = 0  # dropped due to capacity
        self.expired_total: int = 0   # dropped due to TTL

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    async def enqueue(self, device_id: str, message: Dict[str, Any]) -> None:
        """Buffer *message* for delivery to *device_id* when it reconnects.

        If the per-device queue is already at capacity the **oldest** entry is
        silently evicted to make room for the new message, ensuring that recent
        messages (most likely to still be useful) are preserved.
        """
        async with self._lock:
            queue = self._queues.setdefault(device_id, deque())
            if len(queue) >= self._max_queue:
                evicted = queue.popleft()
                self.evicted_total += 1
                logger.debug(
                    "pending_delivery_buffer: evicted oldest message for "
                    "device_id=%s (queue full, capacity=%d) evicted_type=%s",
                    device_id,
                    self._max_queue,
                    evicted.message.get("type", "?"),
                )
            queue.append(_BufferedMessage(message))
            self.enqueued_total += 1
            logger.debug(
                "pending_delivery_buffer: enqueued message for device_id=%s "
                "queue_len=%d type=%s",
                device_id,
                len(queue),
                message.get("type", "?"),
            )

    # ------------------------------------------------------------------
    # Flush
    # ------------------------------------------------------------------

    async def flush(
        self,
        device_id: str,
        send_fn,  # Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> Tuple[int, int]:
        """Drain the pending queue for *device_id* by calling *send_fn*.

        *send_fn* is called once per pending message with the message dict as
        its sole argument.  It must be an async callable.  Expired messages
        are discarded **before** ``send_fn`` is called for them.

        Returns
        -------
        (delivered, skipped) :
            *delivered* — number of messages successfully sent.
            *skipped* — number of messages discarded (TTL expired).
        """
        async with self._lock:
            queue = self._queues.pop(device_id, deque())

        if not queue:
            return 0, 0

        delivered = 0
        skipped = 0
        pending: List[_BufferedMessage] = list(queue)

        for buffered in pending:
            if buffered.is_expired(self._ttl):
                skipped += 1
                self.expired_total += 1
                logger.debug(
                    "pending_delivery_buffer: discarding expired message "
                    "for device_id=%s age=%.1fs type=%s",
                    device_id,
                    time.monotonic() - buffered.enqueued_at,
                    buffered.message.get("type", "?"),
                )
                continue

            try:
                buffered.attempt_count += 1
                await send_fn(buffered.message)
                delivered += 1
                self.delivered_total += 1
                logger.info(
                    "pending_delivery_buffer: re-delivered message to "
                    "device_id=%s type=%s age=%.1fs",
                    device_id,
                    buffered.message.get("type", "?"),
                    time.monotonic() - buffered.enqueued_at,
                )
            except Exception as exc:
                skipped += 1
                logger.warning(
                    "pending_delivery_buffer: failed to re-deliver message to "
                    "device_id=%s type=%s: %s",
                    device_id,
                    buffered.message.get("type", "?"),
                    exc,
                )

        if delivered or skipped:
            logger.info(
                "pending_delivery_buffer: flush complete device_id=%s "
                "delivered=%d skipped=%d",
                device_id,
                delivered,
                skipped,
            )

        return delivered, skipped

    # ------------------------------------------------------------------
    # Inspection / maintenance
    # ------------------------------------------------------------------

    def queue_size(self, device_id: str) -> int:
        """Return the number of pending messages for *device_id* (non-locking)."""
        return len(self._queues.get(device_id, ()))

    async def purge_expired(self) -> int:
        """Remove all expired messages across all device queues.

        Returns the total number of messages removed.  Intended to be called
        periodically (e.g. alongside the stale-device cleanup task) to prevent
        long-disconnected devices from retaining unbounded buffered messages.
        """
        removed = 0
        async with self._lock:
            empty_keys: List[str] = []
            for device_id, queue in self._queues.items():
                before = len(queue)
                # Build a fresh deque keeping only non-expired messages.
                live = deque(m for m in queue if not m.is_expired(self._ttl))
                expired_count = before - len(live)
                if expired_count:
                    self._queues[device_id] = live
                    self.expired_total += expired_count
                    removed += expired_count
                    logger.debug(
                        "pending_delivery_buffer: purged %d expired messages "
                        "for device_id=%s",
                        expired_count,
                        device_id,
                    )
                if not live:
                    empty_keys.append(device_id)
            for key in empty_keys:
                self._queues.pop(key, None)
        return removed

    async def discard_device(self, device_id: str) -> int:
        """Unconditionally remove all pending messages for *device_id*.

        Called by ``cleanup_stale_devices`` when a device is permanently
        removed from the transport cache.

        Returns the number of messages discarded.
        """
        async with self._lock:
            queue = self._queues.pop(device_id, deque())
            count = len(queue)
        if count:
            logger.debug(
                "pending_delivery_buffer: discarded %d pending messages for "
                "deregistered device_id=%s",
                count,
                device_id,
            )
        return count

    def stats(self) -> Dict[str, Any]:
        """Return a snapshot of buffer statistics for monitoring."""
        return {
            "enqueued_total": self.enqueued_total,
            "delivered_total": self.delivered_total,
            "evicted_total": self.evicted_total,
            "expired_total": self.expired_total,
            "active_device_queues": len(self._queues),
            "total_pending_messages": sum(len(q) for q in self._queues.values()),
        }


# ---------------------------------------------------------------------------
# Module-level singleton — shared by AndroidBridge
# ---------------------------------------------------------------------------

#: The shared pending-delivery buffer instance used by AndroidBridge.
#: Tests may replace this with a fresh instance via
#: ``galaxy_gateway.pending_delivery_buffer.pending_delivery_buffer = PendingDeliveryBuffer()``.
pending_delivery_buffer: PendingDeliveryBuffer = PendingDeliveryBuffer()
