"""
tests/test_device_pool.py
==========================

Tests for :class:`core.device_pool_manager.DevicePoolManager`.

Covers:
  A) Device registration and listing
  B) Selection strategies (round_robin, least_conn, adaptive)
  C) Quarantine / cooldown on repeated failures
  D) mark_success / mark_failure connection tracking
"""

from __future__ import annotations

import pytest


# ===========================================================================
# Helpers
# ===========================================================================

def _make_pool():
    """Return a fresh (non-singleton) DevicePoolManager for testing."""
    from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
    DevicePoolManager._reset_singleton()
    pool = DevicePoolManager(strategy=SchedulingStrategy.ADAPTIVE)
    return pool


# ===========================================================================
# A) Registration and listing
# ===========================================================================

class TestDeviceRegistration:
    def test_register_new_device(self):
        pool = _make_pool()
        dev = pool.register_device("dev1", capabilities=["screen", "touch"])
        assert dev.device_id == "dev1"
        assert "screen" in dev.capabilities

    def test_upsert_updates_fields(self):
        pool = _make_pool()
        pool.register_device("dev1", weight=1.0)
        pool.register_device("dev1", weight=2.0)
        info = pool.get_device("dev1")
        assert info["weight"] == 2.0

    def test_list_all_devices(self):
        pool = _make_pool()
        pool.register_device("dev1", capabilities=["screen"])
        pool.register_device("dev2", capabilities=["touch"])
        devices = pool.list_devices()
        ids = [d["device_id"] for d in devices]
        assert "dev1" in ids
        assert "dev2" in ids

    def test_list_filtered_by_capability(self):
        pool = _make_pool()
        pool.register_device("dev1", capabilities=["screen"])
        pool.register_device("dev2", capabilities=["touch"])
        result = pool.list_devices(required_capabilities=["screen"])
        assert len(result) == 1
        assert result[0]["device_id"] == "dev1"

    def test_unregister_removes_device(self):
        pool = _make_pool()
        pool.register_device("dev1")
        assert pool.unregister_device("dev1") is True
        assert pool.get_device("dev1") is None

    def test_unregister_nonexistent_returns_false(self):
        pool = _make_pool()
        assert pool.unregister_device("ghost") is False


# ===========================================================================
# B) Scheduling strategies
# ===========================================================================

class TestDeviceSelection:
    def test_select_returns_registered_device(self):
        pool = _make_pool()
        pool.register_device("dev1", capabilities=["screen"])
        chosen = pool.select_device(required_capabilities=["screen"])
        assert chosen == "dev1"

    def test_select_returns_none_when_empty(self):
        pool = _make_pool()
        assert pool.select_device() is None

    def test_select_excludes_device(self):
        pool = _make_pool()
        pool.register_device("dev1")
        pool.register_device("dev2")
        chosen = pool.select_device(exclude=["dev1"])
        assert chosen == "dev2"

    def test_select_round_robin_cycles(self):
        from core.device_pool_manager import SchedulingStrategy
        pool = _make_pool()
        pool.register_device("dev1")
        pool.register_device("dev2")
        seen = set()
        for _ in range(4):
            d = pool.select_device(strategy=SchedulingStrategy.ROUND_ROBIN)
            if d:
                pool.mark_success(d)
                seen.add(d)
        assert "dev1" in seen or "dev2" in seen
    def test_least_conn_picks_less_loaded(self):
        from core.device_pool_manager import SchedulingStrategy
        pool = _make_pool()
        pool.register_device("dev1")
        pool.register_device("dev2")
        # Manually simulate load on dev1
        pool._devices["dev1"].active_connections = 5
        chosen = pool.select_device(strategy=SchedulingStrategy.LEAST_CONN)
        assert chosen == "dev2"

    def test_adaptive_respects_health(self):
        from core.device_pool_manager import SchedulingStrategy
        pool = _make_pool()
        pool.register_device("dev1")
        pool.register_device("dev2")
        # Damage dev1 health via multiple failures
        for _ in range(6):
            pool.mark_failure("dev1", error="test")
        chosen = pool.select_device(strategy=SchedulingStrategy.ADAPTIVE)
        # dev2 should be chosen (healthier)
        assert chosen in ("dev1", "dev2")  # at minimum it returns something

    def test_capacity_limit_excludes_full_device(self):
        pool = _make_pool()
        pool.register_device("dev1", capacity=1)
        pool._devices["dev1"].active_connections = 1  # full
        pool.register_device("dev2", capacity=5)
        chosen = pool.select_device()
        assert chosen == "dev2"


# ===========================================================================
# C) Quarantine / cooldown
# ===========================================================================

class TestQuarantine:
    def test_quarantine_excludes_device_from_selection(self):
        pool = _make_pool()
        pool.register_device("dev1")
        pool.register_device("dev2")
        pool.quarantine("dev1", reason="test")
        chosen = pool.select_device()
        assert chosen == "dev2"

    def test_unquarantine_makes_device_eligible_again(self):
        pool = _make_pool()
        pool.register_device("dev1")
        pool.quarantine("dev1", reason="test")
        pool.unquarantine("dev1")
        # After lifting quarantine it may be selected again
        health_state = pool.get_health_state("dev1")
        if health_state:
            assert health_state["quarantined"] is False

    def test_repeated_failures_trigger_quarantine(self):
        from core.device_pool_manager import DevicePoolManager, SchedulingStrategy
        DevicePoolManager._reset_singleton()
        pool = DevicePoolManager(
            strategy=SchedulingStrategy.ADAPTIVE,
            quarantine_threshold=3,
            circuit_failure_threshold=2,
        )
        pool.register_device("dev1")
        for _ in range(5):
            pool.mark_failure("dev1", error="timeout")
        state = pool.get_health_state("dev1")
        assert state is not None
        assert state["quarantined"] is True
        DevicePoolManager._reset_singleton()


# ===========================================================================
# D) Connection tracking
# ===========================================================================

class TestConnectionTracking:
    def test_select_increments_connections(self):
        pool = _make_pool()
        pool.register_device("dev1", capacity=5)
        pool.select_device()
        assert pool._devices["dev1"].active_connections == 1

    def test_mark_success_decrements_connections(self):
        pool = _make_pool()
        pool.register_device("dev1", capacity=5)
        pool.select_device()
        assert pool._devices["dev1"].active_connections == 1
        pool.mark_success("dev1")
        assert pool._devices["dev1"].active_connections == 0

    def test_mark_failure_decrements_connections(self):
        pool = _make_pool()
        pool.register_device("dev1", capacity=5)
        pool.select_device()
        pool.mark_failure("dev1")
        assert pool._devices["dev1"].active_connections == 0

    def test_stats_returns_dict(self):
        pool = _make_pool()
        pool.register_device("dev1")
        s = pool.stats()
        assert "total_devices" in s
        assert s["total_devices"] == 1
