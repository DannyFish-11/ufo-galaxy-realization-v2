"""
tests/test_durable_pending_delivery_buffer.py
==============================================
Tests for DurablePendingDeliveryBuffer — file-backed persistent pending delivery.

Validates:
 - Messages survive process-level state reinitialization (new instance, same file)
 - Replay still occurs correctly on reconnect after a restart
 - Bounded retention / capacity eviction is preserved across restarts
 - TTL / expiry works across restarts (expired messages discarded on load)
 - Atomic snapshot write (no partial reads)
 - Graceful handling of missing / corrupt snapshot files
 - Stats counters are consistent after load
 - Reality surface sentinels reflect the new durability guarantee
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from galaxy_gateway.pending_delivery_buffer import (
    DurablePendingDeliveryBuffer,
    PendingDeliveryBuffer,
    PENDING_DELIVERY_STORE_PATH,
    pending_delivery_buffer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(msg_type: str = "task_assign", task_id: str = "t1") -> Dict[str, Any]:
    return {"type": msg_type, "task_id": task_id, "payload": {}}


def _tmp_store(tmp_dir: str, name: str = "pending.json") -> str:
    return os.path.join(tmp_dir, name)


# ---------------------------------------------------------------------------
# Process-restart simulation: new instance, same file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_messages_survive_process_restart():
    """Buffered messages survive simulated process restart (new instance, same file)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        # First "process": enqueue two messages.
        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf1.enqueue("dev1", _msg(task_id="t1"))
        await buf1.enqueue("dev1", _msg(task_id="t2"))
        assert buf1.queue_size("dev1") == 2
        assert os.path.exists(store), "Snapshot file must exist after enqueue"

        # Second "process": new instance loading from the same file.
        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf2.queue_size("dev1") == 2, (
            "Messages must be restored from snapshot on new instance creation"
        )


@pytest.mark.asyncio
async def test_replay_correct_on_reconnect_after_restart():
    """Replay delivers restored messages in FIFO order after a simulated restart."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        for tid in ("a", "b", "c"):
            await buf1.enqueue("dev1", _msg(task_id=tid))

        # Simulate restart
        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)

        received: List[str] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            received.append(msg["task_id"])

        delivered, skipped = await buf2.flush("dev1", send_fn)

        assert delivered == 3
        assert skipped == 0
        assert received == ["a", "b", "c"], "Messages must be replayed in FIFO order"


@pytest.mark.asyncio
async def test_queue_empty_after_flush_and_restart():
    """After flush, a subsequent restart sees no messages for that device."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf1.enqueue("dev1", _msg())
        await buf1.flush("dev1", AsyncMock())

        # Restart
        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf2.queue_size("dev1") == 0


# ---------------------------------------------------------------------------
# TTL / expiry across restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_messages_discarded_on_load():
    """Messages that have expired by the time of restart are silently discarded."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        # Use a very short TTL so messages expire quickly.
        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=0.05)
        await buf1.enqueue("dev1", _msg(task_id="stale"))

        # Wait for TTL to expire.
        await asyncio.sleep(0.15)

        # Restart: expired message must not be restored.
        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=0.05)
        assert buf2.queue_size("dev1") == 0, (
            "Expired messages must be discarded on load, not replayed"
        )
        assert buf2.expired_total >= 1


@pytest.mark.asyncio
async def test_non_expired_messages_loaded_correctly():
    """Non-expired messages are fully restored after restart."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf1.enqueue("dev1", _msg(task_id="live"))

        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        received: List[Dict] = []

        async def send_fn(msg: Dict[str, Any]) -> None:
            received.append(msg)

        delivered, skipped = await buf2.flush("dev1", send_fn)
        assert delivered == 1
        assert skipped == 0
        assert received[0]["task_id"] == "live"


# ---------------------------------------------------------------------------
# Capacity eviction across restart
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_eviction_preserved_across_restart():
    """Capacity limit is enforced when loading from a snapshot."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        # Fill buffer beyond capacity, then restart with smaller cap.
        buf1 = DurablePendingDeliveryBuffer(
            store_path=store, max_queue_per_device=10, ttl_seconds=60.0
        )
        for i in range(10):
            await buf1.enqueue("dev1", _msg(task_id=f"t{i}"))
        assert buf1.queue_size("dev1") == 10

        # Restart with a smaller cap — load must not exceed it.
        buf2 = DurablePendingDeliveryBuffer(
            store_path=store, max_queue_per_device=3, ttl_seconds=60.0
        )
        assert buf2.queue_size("dev1") <= 3


@pytest.mark.asyncio
async def test_bounded_retention_still_enforced_on_enqueue():
    """After restart, further enqueues still respect the capacity cap."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        buf1 = DurablePendingDeliveryBuffer(
            store_path=store, max_queue_per_device=3, ttl_seconds=60.0
        )
        for i in range(3):
            await buf1.enqueue("dev1", _msg(task_id=f"pre{i}"))

        # Restart
        buf2 = DurablePendingDeliveryBuffer(
            store_path=store, max_queue_per_device=3, ttl_seconds=60.0
        )
        assert buf2.queue_size("dev1") == 3

        # Enqueue one more — oldest must be evicted.
        await buf2.enqueue("dev1", _msg(task_id="new"))
        assert buf2.queue_size("dev1") == 3
        assert buf2.evicted_total >= 1


# ---------------------------------------------------------------------------
# Multi-device isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_multi_device_isolation_preserved_across_restart():
    """Per-device queues are isolated: flushing one does not affect others after restart."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)

        buf1 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf1.enqueue("dev1", _msg(task_id="for_dev1"))
        await buf1.enqueue("dev2", _msg(task_id="for_dev2"))

        # Restart
        buf2 = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf2.queue_size("dev1") == 1
        assert buf2.queue_size("dev2") == 1

        await buf2.flush("dev1", AsyncMock())
        assert buf2.queue_size("dev2") == 1, "dev2 queue must be unaffected by dev1 flush"


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

def test_missing_snapshot_starts_empty():
    """A missing snapshot file starts with an empty buffer (no error)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)
        buf = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf.stats()["total_pending_messages"] == 0


def test_corrupt_snapshot_starts_empty():
    """A corrupt snapshot file starts with an empty buffer (no error raised)."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)
        with open(store, "w", encoding="utf-8") as fh:
            fh.write("not valid json {{{")

        buf = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf.stats()["total_pending_messages"] == 0


def test_malformed_queues_value_starts_empty():
    """Snapshot with queues not being a dict is handled gracefully."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)
        payload = {"schema_version": 1, "queues": "not-a-dict"}
        with open(store, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

        buf = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        assert buf.stats()["total_pending_messages"] == 0


# ---------------------------------------------------------------------------
# Atomic write — snapshot is valid JSON after enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_is_valid_json_after_enqueue():
    """After enqueue the snapshot file contains valid parseable JSON."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)
        buf = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf.enqueue("dev1", _msg(task_id="t1"))

        with open(store, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        assert data["schema_version"] == 1
        assert "queues" in data
        assert "dev1" in data["queues"]
        assert len(data["queues"]["dev1"]) == 1
        assert data["queues"]["dev1"][0]["message"]["task_id"] == "t1"


@pytest.mark.asyncio
async def test_snapshot_updated_after_flush():
    """Snapshot is updated (device queue removed) after flush."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = _tmp_store(tmp_dir)
        buf = DurablePendingDeliveryBuffer(store_path=store, ttl_seconds=60.0)
        await buf.enqueue("dev1", _msg())
        await buf.flush("dev1", AsyncMock())

        with open(store, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        assert "dev1" not in data.get("queues", {}), (
            "After flush the snapshot must not retain the device queue"
        )


# ---------------------------------------------------------------------------
# Module-level singleton is DurablePendingDeliveryBuffer
# ---------------------------------------------------------------------------

def test_module_singleton_is_durable_buffer():
    """The module-level singleton must be a DurablePendingDeliveryBuffer instance."""
    assert isinstance(pending_delivery_buffer, DurablePendingDeliveryBuffer), (
        "pending_delivery_buffer singleton must be DurablePendingDeliveryBuffer "
        "so that buffered messages survive V2 process restarts."
    )


def test_module_singleton_still_is_pending_delivery_buffer():
    """DurablePendingDeliveryBuffer is-a PendingDeliveryBuffer (LSP check)."""
    assert isinstance(pending_delivery_buffer, PendingDeliveryBuffer)


# ---------------------------------------------------------------------------
# PENDING_DELIVERY_STORE_PATH constant exists
# ---------------------------------------------------------------------------

def test_store_path_constant_is_string():
    """PENDING_DELIVERY_STORE_PATH is a non-empty string."""
    assert isinstance(PENDING_DELIVERY_STORE_PATH, str)
    assert len(PENDING_DELIVERY_STORE_PATH) > 0


# ---------------------------------------------------------------------------
# Reality surface: process_restart sentinel is now False
# ---------------------------------------------------------------------------

def test_process_restart_residual_risk_is_false():
    """INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART must be False — durable buffer present."""
    from core.cross_device_integration_reality import (
        INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART,
        DURABLE_PENDING_DELIVERY_BUFFER_PRESENT,
    )
    assert DURABLE_PENDING_DELIVERY_BUFFER_PRESENT is True
    assert INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART is False, (
        "INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART must be False now that "
        "DurablePendingDeliveryBuffer backs the pending-delivery buffer."
    )


def test_dispatch_durability_verdict_is_runnable_but_conditional():
    """DISPATCH_DURABILITY_ACROSS_RESTART must be RUNNABLE_BUT_CONDITIONAL (not MISSING)."""
    from core.final_integrated_audit_verdict import (
        DISPATCH_DURABILITY_ACROSS_RESTART,
        CapabilityVerdict,
    )
    assert DISPATCH_DURABILITY_ACROSS_RESTART == CapabilityVerdict.RUNNABLE_BUT_CONDITIONAL, (
        "Pending-delivery buffer is now durable — restart durability must not be MISSING."
    )
