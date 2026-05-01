"""
tests/test_durable_pending_delivery_buffer.py
==============================================
Durability tests for galaxy_gateway.pending_delivery_buffer.

Validates that:
  1. Buffered outbound device messages survive process-level state
     reinitialization (simulated by creating a new PendingDeliveryBuffer
     instance pointing at the same store file).
  2. Replay (flush) still occurs correctly on reconnect after restart.
  3. Bounded retention and TTL expiry still work with durable storage.
  4. The module-level singleton is backed by a durable store.
  5. Capacity eviction (oldest-first) is enforced on load.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from typing import Any, Dict, List

import pytest

from galaxy_gateway.pending_delivery_buffer import (
    PendingDeliveryBuffer,
    _DEFAULT_PENDING_DELIVERY_STORE_PATH,
    pending_delivery_buffer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(msg_type: str = "task_assign", task_id: str = "t1") -> Dict[str, Any]:
    return {"type": msg_type, "task_id": task_id, "payload": {}}


def _fresh_store() -> str:
    """Return a path to a fresh temporary JSON store file."""
    fd, path = tempfile.mkstemp(suffix=".json", prefix="pdb_test_")
    os.close(fd)
    os.unlink(path)  # Remove so the buffer starts empty
    return path


# ---------------------------------------------------------------------------
# 1. Messages survive process-level state reinitialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_messages_survive_process_restart():
    """Buffered messages written by one buffer instance are available in a
    new instance backed by the same store (simulating a V2 process restart).
    """
    store = _fresh_store()
    try:
        # --- "first process" ---
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf1.enqueue("dev1", _msg(task_id="task_alpha"))
        await buf1.enqueue("dev1", _msg(task_id="task_beta"))
        assert buf1.queue_size("dev1") == 2

        # --- "process restarts" — new instance, same store file ---
        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf2.queue_size("dev1") == 2, (
            "Messages must survive process restart when a durable store is used."
        )
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_restart_preserves_message_content_and_order():
    """Message content and ordering (FIFO) are preserved across restart."""
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        for tid in ("x", "y", "z"):
            await buf1.enqueue("dev1", _msg(task_id=tid))

        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        cap: List[str] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            cap.append(msg["task_id"])

        await buf2.flush("dev1", send_fn)
        assert cap == ["x", "y", "z"], (
            "Message order must be preserved through durable storage."
        )
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_multiple_devices_survive_restart():
    """Per-device queues are all restored after a simulated restart."""
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf1.enqueue("dev_a", _msg(task_id="for_a"))
        await buf1.enqueue("dev_b", _msg(task_id="for_b1"))
        await buf1.enqueue("dev_b", _msg(task_id="for_b2"))

        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf2.queue_size("dev_a") == 1
        assert buf2.queue_size("dev_b") == 2
    finally:
        if os.path.exists(store):
            os.unlink(store)


# ---------------------------------------------------------------------------
# 2. Replay (flush) on reconnect works correctly after restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_after_restart_delivers_all_messages():
    """Flush on reconnect after a simulated restart delivers all buffered
    messages to the send function.
    """
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf1.enqueue("dev1", _msg(task_id="t1"))
        await buf1.enqueue("dev1", _msg(task_id="t2"))

        # Restart
        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        received: List[Dict] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            received.append(msg)

        delivered, skipped = await buf2.flush("dev1", send_fn)
        assert delivered == 2
        assert skipped == 0
        assert [m["task_id"] for m in received] == ["t1", "t2"]
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_flush_removes_device_from_durable_store():
    """After a successful flush the device's queue must be removed from the
    durable store so a second restart does not re-replay the same messages.
    """
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf1.enqueue("dev1", _msg(task_id="once"))

        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf2.flush("dev1", asyncio.coroutine(lambda _: None) if False else (lambda _: asyncio.sleep(0)))

        # Third "restart" — queue must be gone
        buf3 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf3.queue_size("dev1") == 0, (
            "Flushed messages must not be re-replayed on a subsequent restart."
        )
    finally:
        if os.path.exists(store):
            os.unlink(store)


# ---------------------------------------------------------------------------
# 3. Bounded retention / TTL expiry still works with durable storage
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_messages_not_loaded_after_restart():
    """Messages whose TTL has already passed at load time are discarded and
    never reach the replay path.
    """
    store = _fresh_store()
    try:
        # Write a store file manually with a message that is already expired.
        past_ts = time.time() - 120.0  # 120 s ago — well beyond any TTL
        data = {
            "schema": "pending_delivery_buffer_v1",
            "saved_at": past_ts,
            "ttl_seconds": 60.0,
            "max_queue_per_device": 32,
            "queues": {
                "dev1": [
                    {"message": _msg(task_id="stale"), "enqueued_at": past_ts}
                ]
            },
        }
        with open(store, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        buf = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf.queue_size("dev1") == 0, (
            "Expired messages must be discarded when loading from durable store."
        )
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_fresh_messages_survive_and_expired_ones_dont():
    """When both fresh and expired messages are stored only fresh ones are
    restored after a simulated restart.
    """
    store = _fresh_store()
    try:
        past_ts = time.time() - 120.0
        future_ts = time.time() - 5.0   # 5 s old — well within TTL
        data = {
            "schema": "pending_delivery_buffer_v1",
            "saved_at": time.time(),
            "ttl_seconds": 60.0,
            "max_queue_per_device": 32,
            "queues": {
                "dev1": [
                    {"message": _msg(task_id="stale"), "enqueued_at": past_ts},
                    {"message": _msg(task_id="fresh"), "enqueued_at": future_ts},
                ]
            },
        }
        with open(store, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        buf = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf.queue_size("dev1") == 1

        cap: List[str] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            cap.append(msg["task_id"])

        await buf.flush("dev1", send_fn)
        assert cap == ["fresh"]
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_capacity_enforced_on_load():
    """If the persisted file contains more messages than the configured cap
    (e.g. the cap was lowered), the oldest messages are evicted on load.
    """
    store = _fresh_store()
    try:
        fresh_ts = time.time() - 1.0
        data = {
            "schema": "pending_delivery_buffer_v1",
            "saved_at": time.time(),
            "ttl_seconds": 60.0,
            "max_queue_per_device": 10,
            "queues": {
                "dev1": [
                    {"message": _msg(task_id=f"t{i}"), "enqueued_at": fresh_ts}
                    for i in range(5)
                ]
            },
        }
        with open(store, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        # Load with a reduced cap of 3
        buf = PendingDeliveryBuffer(max_queue_per_device=3, ttl_seconds=60.0, store_path=store)
        assert buf.queue_size("dev1") == 3

        cap: List[str] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            cap.append(msg["task_id"])

        await buf.flush("dev1", send_fn)
        # Oldest (t0, t1) were evicted; newest (t2, t3, t4) kept
        assert cap == ["t2", "t3", "t4"]
    finally:
        if os.path.exists(store):
            os.unlink(store)


# ---------------------------------------------------------------------------
# 4. Store-path sentinel and module singleton durability
# ---------------------------------------------------------------------------

def test_module_singleton_uses_durable_store():
    """The module-level singleton must be backed by a durable store."""
    s = pending_delivery_buffer.stats()
    assert s["is_durable"] is True, (
        "The module-level pending_delivery_buffer singleton must be created "
        "with a store_path so that buffered messages survive V2 restarts."
    )


def test_module_singleton_store_path_is_expected():
    """The module-level singleton must point at the canonical store path."""
    assert pending_delivery_buffer._store_path == _DEFAULT_PENDING_DELIVERY_STORE_PATH


def test_in_memory_buffer_is_not_durable():
    """A buffer created without store_path must report is_durable=False."""
    buf = PendingDeliveryBuffer()
    s = buf.stats()
    assert s["is_durable"] is False


# ---------------------------------------------------------------------------
# 5. Atomic write: corrupt/partial store doesn't crash on load
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_corrupt_store_does_not_raise():
    """A corrupt store file must be silently ignored (non-fatal load)."""
    store = _fresh_store()
    try:
        with open(store, "w", encoding="utf-8") as fh:
            fh.write("{invalid json{{{{")

        # Should not raise; just start empty
        buf = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf.queue_size("dev1") == 0
    finally:
        if os.path.exists(store):
            os.unlink(store)


# ---------------------------------------------------------------------------
# 6. discard_device and purge_expired persist their changes
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discard_device_persists():
    """discard_device must remove the device's entry from the durable store."""
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        await buf1.enqueue("dev1", _msg(task_id="t1"))
        await buf1.discard_device("dev1")

        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf2.queue_size("dev1") == 0
    finally:
        if os.path.exists(store):
            os.unlink(store)


@pytest.mark.asyncio
async def test_purge_expired_persists():
    """purge_expired must update the durable store."""
    store = _fresh_store()
    try:
        buf1 = PendingDeliveryBuffer(ttl_seconds=0.05, store_path=store)
        await buf1.enqueue("dev1", _msg(task_id="stale"))
        await asyncio.sleep(0.1)  # Let it expire
        await buf1.purge_expired()

        buf2 = PendingDeliveryBuffer(ttl_seconds=60.0, store_path=store)
        assert buf2.queue_size("dev1") == 0
    finally:
        if os.path.exists(store):
            os.unlink(store)
