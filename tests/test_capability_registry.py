"""
tests/test_capability_registry.py
===================================
Unit tests for galaxy_gateway.capability_registry.GatewayCapabilityRegistry.

Covers:
  - ExecMode.from_str() parsing (including backward-compat cases)
  - upsert: insert and update semantics
  - purge: removes all capabilities for a device
  - query: filtering by action, exec_mode, device_id, tags
  - stats: counters update correctly
  - Thread-safety smoke test (basic)
"""

import sys
import threading
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from galaxy_gateway.capability_registry import (
    CapabilitySchema,
    ExecMode,
    GatewayCapabilityRegistry,
    get_gateway_capability_registry,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────


def _fresh_registry() -> GatewayCapabilityRegistry:
    """Return a brand-new registry instance (not the global singleton)."""
    return GatewayCapabilityRegistry()


# ──────────────────────────────────────────────────────────────────────────────
# ExecMode parsing
# ──────────────────────────────────────────────────────────────────────────────


class TestExecModeFromStr:
    def test_local(self):
        assert ExecMode.from_str("local") == ExecMode.LOCAL

    def test_remote(self):
        assert ExecMode.from_str("remote") == ExecMode.REMOTE

    def test_both(self):
        assert ExecMode.from_str("both") == ExecMode.BOTH

    def test_uppercase(self):
        assert ExecMode.from_str("LOCAL") == ExecMode.LOCAL

    def test_none_returns_both(self):
        assert ExecMode.from_str(None) == ExecMode.BOTH

    def test_empty_string_returns_both(self):
        assert ExecMode.from_str("") == ExecMode.BOTH

    def test_unknown_string_returns_both(self):
        assert ExecMode.from_str("invalid_mode") == ExecMode.BOTH


# ──────────────────────────────────────────────────────────────────────────────
# Registry CRUD
# ──────────────────────────────────────────────────────────────────────────────


class TestUpsert:
    def test_insert_returns_schema(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "tap", {"exec_mode": "local"})
        assert isinstance(schema, CapabilitySchema)
        assert schema.device_id == "dev-1"
        assert schema.action == "tap"
        assert schema.exec_mode == ExecMode.LOCAL

    def test_insert_missing_exec_mode_defaults_to_both(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "swipe", {})
        assert schema.exec_mode == ExecMode.BOTH

    def test_insert_increments_registration_count(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap")
        reg.upsert("dev-1", "swipe")
        assert reg.stats()["registrations"] == 2

    def test_update_overwrites_existing_schema(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap", {"exec_mode": "local", "version": "1.0"})
        reg.upsert("dev-1", "tap", {"exec_mode": "remote", "version": "2.0"})
        schemas = reg.get_by_device("dev-1")
        assert len(schemas) == 1
        assert schemas[0].exec_mode == ExecMode.REMOTE
        assert schemas[0].version == "2.0"

    def test_params_and_returns_stored(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "screenshot", {
            "params": {"quality": "int"},
            "returns": {"image": "bytes"},
        })
        assert schema.params == {"quality": "int"}
        assert schema.returns == {"image": "bytes"}

    def test_tags_stored(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "tap", {"tags": ["ui", "touch"]})
        assert "ui" in schema.tags
        assert "touch" in schema.tags

    def test_version_stored(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "tap", {"version": "3.2"})
        assert schema.version == "3.2"

    def test_multiple_devices(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap")
        reg.upsert("dev-2", "tap")
        assert len(reg.all_device_ids()) == 2

    def test_none_schema_dict(self):
        reg = _fresh_registry()
        schema = reg.upsert("dev-1", "tap", None)
        assert schema.exec_mode == ExecMode.BOTH


class TestPurge:
    def test_purge_removes_all_device_capabilities(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap")
        reg.upsert("dev-1", "swipe")
        removed = reg.purge("dev-1")
        assert removed == 2
        assert reg.get_by_device("dev-1") == []

    def test_purge_nonexistent_device_returns_zero(self):
        reg = _fresh_registry()
        assert reg.purge("nonexistent") == 0

    def test_purge_does_not_affect_other_devices(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap")
        reg.upsert("dev-2", "swipe")
        reg.purge("dev-1")
        assert reg.get_by_device("dev-2") != []

    def test_purge_cleans_device_id_from_store(self):
        reg = _fresh_registry()
        reg.upsert("dev-1", "tap")
        reg.purge("dev-1")
        assert "dev-1" not in reg.all_device_ids()


# ──────────────────────────────────────────────────────────────────────────────
# Query
# ──────────────────────────────────────────────────────────────────────────────


class TestQuery:
    def setup_method(self):
        self.reg = _fresh_registry()
        self.reg.upsert("dev-A", "tap",        {"exec_mode": "local",  "tags": ["ui"]})
        self.reg.upsert("dev-A", "screenshot", {"exec_mode": "both",   "tags": ["ui", "capture"]})
        self.reg.upsert("dev-B", "tap",        {"exec_mode": "remote", "tags": ["ui"]})
        self.reg.upsert("dev-B", "screenshot", {"exec_mode": "local",  "tags": ["capture"]})

    def test_query_no_filter_returns_all(self):
        results = self.reg.query()
        assert len(results) == 4

    def test_query_by_action(self):
        results = self.reg.query(action="tap")
        assert len(results) == 2
        assert all(s.action == "tap" for s in results)

    def test_query_by_device_id(self):
        results = self.reg.query(device_id="dev-A")
        assert len(results) == 2
        assert all(s.device_id == "dev-A" for s in results)

    def test_query_by_action_and_device(self):
        results = self.reg.query(action="tap", device_id="dev-A")
        assert len(results) == 1
        assert results[0].exec_mode == ExecMode.LOCAL

    # exec_mode filtering ──────────────────────────────────────────────────────

    def test_query_exec_mode_local_excludes_remote_only(self):
        # dev-B/tap is remote-only → should be excluded
        results = self.reg.query(action="tap", exec_mode=ExecMode.LOCAL)
        device_ids = [s.device_id for s in results]
        assert "dev-A" in device_ids
        assert "dev-B" not in device_ids

    def test_query_exec_mode_local_includes_both(self):
        # dev-A/screenshot is exec_mode=both → should be included when asking for local
        results = self.reg.query(action="screenshot", exec_mode=ExecMode.LOCAL)
        device_ids = [s.device_id for s in results]
        assert "dev-A" in device_ids  # both → ok for local

    def test_query_exec_mode_remote_excludes_local_only(self):
        # dev-A/tap is local-only → should be excluded
        results = self.reg.query(action="tap", exec_mode=ExecMode.REMOTE)
        device_ids = [s.device_id for s in results]
        assert "dev-A" not in device_ids
        assert "dev-B" in device_ids

    def test_query_exec_mode_both_returns_all_actions(self):
        results = self.reg.query(action="tap", exec_mode=ExecMode.BOTH)
        assert len(results) == 2

    def test_query_exec_mode_none_returns_all_actions(self):
        results = self.reg.query(action="tap", exec_mode=None)
        assert len(results) == 2

    # tags filtering ───────────────────────────────────────────────────────────

    def test_query_by_single_tag(self):
        results = self.reg.query(tags=["capture"])
        assert len(results) == 2  # dev-A/screenshot and dev-B/screenshot

    def test_query_by_multiple_tags_and(self):
        results = self.reg.query(tags=["ui", "capture"])
        assert len(results) == 1
        assert results[0].action == "screenshot"
        assert results[0].device_id == "dev-A"

    def test_query_nonexistent_tag_returns_empty(self):
        results = self.reg.query(tags=["nonexistent"])
        assert results == []

    # hit/miss counters ────────────────────────────────────────────────────────

    def test_hit_increments_on_match(self):
        before = self.reg.stats()["hits"]
        self.reg.query(action="tap")
        assert self.reg.stats()["hits"] == before + 1

    def test_miss_increments_on_no_match(self):
        before = self.reg.stats()["misses"]
        self.reg.query(action="nonexistent_action")
        assert self.reg.stats()["misses"] == before + 1


# ──────────────────────────────────────────────────────────────────────────────
# Stats
# ──────────────────────────────────────────────────────────────────────────────


class TestStats:
    def test_initial_stats_are_zero(self):
        reg = _fresh_registry()
        s = reg.stats()
        assert s["registrations"] == 0
        assert s["hits"] == 0
        assert s["misses"] == 0
        assert s["devices"] == 0
        assert s["total_capabilities"] == 0

    def test_stats_total_capabilities(self):
        reg = _fresh_registry()
        reg.upsert("d1", "tap")
        reg.upsert("d1", "swipe")
        reg.upsert("d2", "tap")
        s = reg.stats()
        assert s["total_capabilities"] == 3
        assert s["devices"] == 2

    def test_stats_after_purge(self):
        reg = _fresh_registry()
        reg.upsert("d1", "tap")
        reg.purge("d1")
        s = reg.stats()
        assert s["total_capabilities"] == 0
        assert s["devices"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    def test_get_instance_returns_same_object(self):
        a = GatewayCapabilityRegistry.get_instance()
        b = GatewayCapabilityRegistry.get_instance()
        assert a is b

    def test_get_gateway_capability_registry_shortcut(self):
        reg = get_gateway_capability_registry()
        assert isinstance(reg, GatewayCapabilityRegistry)


# ──────────────────────────────────────────────────────────────────────────────
# Thread-safety smoke test
# ──────────────────────────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_upserts_do_not_crash(self):
        reg = _fresh_registry()
        errors = []

        def worker(device_id: str):
            try:
                for i in range(20):
                    reg.upsert(device_id, f"action_{i}", {"exec_mode": "both"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(f"dev-{t}",)) for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert reg.stats()["registrations"] == 5 * 20
