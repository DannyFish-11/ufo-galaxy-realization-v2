"""
tests/test_pending_delivery_buffer.py
======================================
Tests for galaxy_gateway.pending_delivery_buffer.

Validates:
 - Enqueue / flush round-trip
 - TTL expiry
 - Capacity eviction
 - Multi-device isolation
 - Stats reporting
 - discard_device / purge_expired
 - integration reality surface consistency
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest

from galaxy_gateway.pending_delivery_buffer import (
    PendingDeliveryBuffer,
    pending_delivery_buffer,
)
from core.cross_device_integration_reality import (
    CROSS_DEVICE_INTEGRATION_REALITY,
    INFLIGHT_TASK_LOSS_ON_DISCONNECT,
    PENDING_DELIVERY_BUFFER_PRESENT,
    PENDING_DELIVERY_BUFFER_TTL_S,
    PENDING_DELIVERY_BUFFER_MAX_QUEUE_PER_DEVICE,
    RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS,
    RESULT_INGESTION_ERROR_COUNTERS_PRESENT,
    INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT,
    INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART,
    assert_known_gaps_are_documented,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _msg(msg_type: str = "task_assign", task_id: str = "t1") -> Dict[str, Any]:
    return {"type": msg_type, "task_id": task_id, "payload": {}}


# ---------------------------------------------------------------------------
# Basic enqueue / flush
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_and_flush_delivers_message():
    buf = PendingDeliveryBuffer()
    received: List[Dict] = []

    async def send_fn(msg):
        received.append(msg)

    msg = _msg()
    await buf.enqueue("dev1", msg)
    delivered, skipped = await buf.flush("dev1", send_fn)

    assert delivered == 1
    assert skipped == 0
    assert len(received) == 1
    assert received[0] is msg


@pytest.mark.asyncio
async def test_flush_empty_queue_returns_zero():
    buf = PendingDeliveryBuffer()
    delivered, skipped = await buf.flush("no_such_device", AsyncMock())
    assert delivered == 0
    assert skipped == 0


@pytest.mark.asyncio
async def test_flush_removes_queue_for_device():
    buf = PendingDeliveryBuffer()
    await buf.enqueue("dev1", _msg())
    assert buf.queue_size("dev1") == 1

    await buf.flush("dev1", AsyncMock())
    assert buf.queue_size("dev1") == 0


@pytest.mark.asyncio
async def test_multiple_messages_delivered_in_order():
    buf = PendingDeliveryBuffer()
    for tid in ("x", "y", "z"):
        await buf.enqueue("dev1", _msg(task_id=tid))

    cap: List[str] = []

    async def ordered_send(msg):
        cap.append(msg["task_id"])

    await buf.flush("dev1", ordered_send)
    assert cap == ["x", "y", "z"]


# ---------------------------------------------------------------------------
# TTL expiry
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_expired_messages_skipped_on_flush():
    buf = PendingDeliveryBuffer(ttl_seconds=0.001)  # 1 ms TTL
    await buf.enqueue("dev1", _msg())
    # Wait for expiry
    await asyncio.sleep(0.05)

    received: List[Dict] = []

    async def send_fn(msg):
        received.append(msg)

    delivered, skipped = await buf.flush("dev1", send_fn)
    assert delivered == 0
    assert skipped == 1
    assert len(received) == 0


@pytest.mark.asyncio
async def test_non_expired_messages_delivered():
    buf = PendingDeliveryBuffer(ttl_seconds=60.0)
    await buf.enqueue("dev1", _msg())

    received: List[Dict] = []

    async def send_fn(msg):
        received.append(msg)

    delivered, skipped = await buf.flush("dev1", send_fn)
    assert delivered == 1
    assert skipped == 0


# ---------------------------------------------------------------------------
# Capacity eviction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_capacity_evicts_oldest_on_overflow():
    buf = PendingDeliveryBuffer(max_queue_per_device=3, ttl_seconds=60.0)

    for i in range(5):
        await buf.enqueue("dev1", _msg(task_id=f"t{i}"))

    assert buf.queue_size("dev1") == 3  # capped at 3
    assert buf.evicted_total == 2

    cap: List[str] = []

    async def send_fn(msg):
        cap.append(msg["task_id"])

    await buf.flush("dev1", send_fn)
    # Oldest messages (t0, t1) were evicted; newest (t2, t3, t4) kept
    assert cap == ["t2", "t3", "t4"]


# ---------------------------------------------------------------------------
# Multi-device isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flush_does_not_affect_other_devices():
    buf = PendingDeliveryBuffer()
    await buf.enqueue("dev1", _msg(task_id="for_dev1"))
    await buf.enqueue("dev2", _msg(task_id="for_dev2"))

    cap_dev1: List[str] = []

    async def send_fn(msg):
        cap_dev1.append(msg["task_id"])

    await buf.flush("dev1", send_fn)
    assert buf.queue_size("dev2") == 1  # dev2 unaffected


# ---------------------------------------------------------------------------
# discard_device
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_discard_device_removes_all_messages():
    buf = PendingDeliveryBuffer()
    for i in range(5):
        await buf.enqueue("dev1", _msg(task_id=f"t{i}"))

    count = await buf.discard_device("dev1")
    assert count == 5
    assert buf.queue_size("dev1") == 0


@pytest.mark.asyncio
async def test_discard_nonexistent_device_returns_zero():
    buf = PendingDeliveryBuffer()
    count = await buf.discard_device("no_such_device")
    assert count == 0


# ---------------------------------------------------------------------------
# purge_expired
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_purge_expired_removes_stale_messages():
    buf = PendingDeliveryBuffer(ttl_seconds=0.001)
    await buf.enqueue("dev1", _msg(task_id="stale"))
    await asyncio.sleep(0.05)
    await buf.enqueue("dev1", _msg(task_id="fresh"))

    # Patch TTL on fresh message — use a normal TTL for the second buffer
    buf2 = PendingDeliveryBuffer(ttl_seconds=0.001)
    await buf2.enqueue("dev1", _msg(task_id="stale"))
    await asyncio.sleep(0.05)
    removed = await buf2.purge_expired()
    assert removed == 1
    assert buf2.queue_size("dev1") == 0


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stats_reflect_operations():
    buf = PendingDeliveryBuffer(max_queue_per_device=2, ttl_seconds=60.0)

    await buf.enqueue("dev1", _msg(task_id="t1"))
    await buf.enqueue("dev1", _msg(task_id="t2"))
    await buf.enqueue("dev1", _msg(task_id="t3"))  # evicts t1

    cap: List[Any] = []

    async def send_fn(msg):
        cap.append(msg)

    await buf.flush("dev1", send_fn)

    s = buf.stats()
    assert s["enqueued_total"] == 3
    assert s["delivered_total"] == 2
    assert s["evicted_total"] == 1
    assert s["expired_total"] == 0
    assert s["active_device_queues"] == 0  # queue was drained


# ---------------------------------------------------------------------------
# Module-level singleton is a PendingDeliveryBuffer instance
# ---------------------------------------------------------------------------

def test_module_singleton_is_buffer_instance():
    assert isinstance(pending_delivery_buffer, PendingDeliveryBuffer)


# ---------------------------------------------------------------------------
# Integration reality surface tests
# ---------------------------------------------------------------------------

def test_inflight_task_loss_sentinel_is_false():
    """Pending-delivery buffer must be present → loss sentinel is False."""
    assert INFLIGHT_TASK_LOSS_ON_DISCONNECT is False, (
        "INFLIGHT_TASK_LOSS_ON_DISCONNECT should be False now that the "
        "pending-delivery buffer is in place."
    )


def test_pending_delivery_buffer_sentinel_is_true():
    assert PENDING_DELIVERY_BUFFER_PRESENT is True


def test_buffer_ttl_and_capacity_match_module():
    from galaxy_gateway.pending_delivery_buffer import (
        PENDING_DELIVERY_TTL_SECONDS,
        PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE,
    )
    assert PENDING_DELIVERY_BUFFER_TTL_S == PENDING_DELIVERY_TTL_SECONDS
    assert PENDING_DELIVERY_BUFFER_MAX_QUEUE_PER_DEVICE == PENDING_DELIVERY_MAX_QUEUE_PER_DEVICE


def test_result_ingestion_silent_paths_sentinel_is_false():
    """Observable error counters must be present → silent paths sentinel is False."""
    assert RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS is False, (
        "RESULT_INGESTION_HAS_SILENT_FAILURE_PATHS should be False now that "
        "observable error counters are in task_lifecycle.py."
    )


def test_result_ingestion_error_counters_present():
    assert RESULT_INGESTION_ERROR_COUNTERS_PRESENT is True


def test_observable_error_counters_importable():
    """The four observable error counters in task_lifecycle must be importable."""
    from galaxy_gateway.android.handlers.task_lifecycle import (
        RESULT_RECONCILE_ERRORS,
        RESULT_TRUTH_INGRESS_ERRORS,
        RESULT_DEVICE_ROUTER_ERRORS,
        RESULT_MEMORY_BACKFLOW_ERRORS,
    )
    # They start at 0 in a fresh module load
    assert isinstance(RESULT_RECONCILE_ERRORS, int)
    assert isinstance(RESULT_TRUTH_INGRESS_ERRORS, int)
    assert isinstance(RESULT_DEVICE_ROUTER_ERRORS, int)
    assert isinstance(RESULT_MEMORY_BACKFLOW_ERRORS, int)


def test_get_result_ingestion_error_counts_snapshot():
    """get_result_ingestion_error_counts() must return a dict with the expected keys."""
    from galaxy_gateway.android.handlers.task_lifecycle import (
        get_result_ingestion_error_counts,
    )
    counts = get_result_ingestion_error_counts()
    expected_keys = {
        "reconcile_errors",
        "truth_ingress_errors",
        "device_router_errors",
        "memory_backflow_errors",
        "total_errors",
    }
    assert set(counts.keys()) == expected_keys
    # All counts start at >= 0 (integers)
    for v in counts.values():
        assert isinstance(v, int)
        assert v >= 0
    # total_errors must be the sum of the four components
    assert counts["total_errors"] == (
        counts["reconcile_errors"]
        + counts["truth_ingress_errors"]
        + counts["device_router_errors"]
        + counts["memory_backflow_errors"]
    )


def test_residual_risks_still_documented():
    """Residual risks that are NOT yet fixed must remain True."""
    assert INFLIGHT_TASK_LOSS_RESIDUAL_RISK_ANDROID_TERMINAL_RECONNECT is True
    assert INFLIGHT_TASK_LOSS_RESIDUAL_RISK_PROCESS_RESTART is True


def test_assert_known_gaps_are_documented_passes():
    """The main gap-documentation assertion must pass with the current reality dict."""
    assert_known_gaps_are_documented()


def test_reality_dict_contains_all_expected_keys():
    r = CROSS_DEVICE_INTEGRATION_REALITY
    required_keys = {
        "ws_transport_protocol_aligned",
        "android_cross_device_disabled_by_default",
        "android_default_url_is_placeholder",
        "remote_access_requires_tailscale_or_vpnish",
        "inflight_task_loss_on_disconnect",
        "pending_delivery_buffer_present",
        "pending_delivery_buffer_ttl_s",
        "pending_delivery_buffer_max_queue_per_device",
        "result_ingestion_has_silent_failure_paths",
        "result_ingestion_error_counters_present",
        "inflight_task_loss_residual_risk_android_terminal_reconnect",
        "inflight_task_loss_residual_risk_process_restart",
        "android_reconnect_stops_permanently_at_limit",
        "e2e_live_ws_tests_present",
    }
    missing = required_keys - r.keys()
    assert not missing, f"Reality dict missing expected keys: {missing}"
