#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_capability_bus.py
================================
PR-3 Acceptance Tests — Canonical Capability Bus

Validates that:
  1. CapabilityBusRole and CapabilityHealthStatus enums are complete and
     correctly classify canonical tool names.
  2. CapabilityBusEntry serialises / deserialises correctly (to_dict /
     from_dict round-trip).
  3. CapabilityBus.register / unregister / lookup / contains behave correctly.
  4. CapabilityBus.list_all and list_by_role return correct filtered views.
  5. CapabilityBus.set_health updates health without mutating unrelated fields.
  6. CapabilityBus.bus_snapshot reflects current state (counts, by_role,
     seeded_from_node_registry flag).
  7. CapabilityBus.seed_from_node_registry seeds nodes from
     config/node_registry.json without hardcoding node names.
  8. Every seeded node entry has role=NODE, a non-empty source_id, and a
     canonical ``node__<id>__execute`` name pattern.
  9. CapabilityBus.register_device_capability creates a valid DEVICE entry
     with ``device__<id>__<action>`` naming.
 10. CapabilityBus.register_mcp_tool creates MCP / MCP_GW entries correctly.
 11. CapabilityBus.register_skill creates SKILL entries correctly.
 12. Thread-safety: concurrent registrations do not corrupt bus state.
 13. CapabilityBus.clear() removes all entries and resets seeded flag.
 14. get_capability_bus() returns a stable singleton; reset_capability_bus()
     yields a fresh instance.
 15. CapabilityLayer.DEVICE is present and classifies device__ prefixes.
 16. CanonicalDispatcher.bus_catalog() returns a dict with total_count field.
 17. No second capability table is introduced — CapabilityBus is the single
     canonical registry.
 18. CapabilityBusEntry.from_dict handles unknown role/health gracefully.
 19. BusSnapshot.to_dict is JSON-serialisable.
 20. Duplicate registration replaces entry (last-writer-wins).
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_bus():
    """Return a fresh CapabilityBus instance (not the singleton)."""
    from core.capability_bus import CapabilityBus
    return CapabilityBus()


def _fresh_entry(
    name: str = "node__01__execute",
    role_str: str = "node",
    health_str: str = "healthy",
    source_id: str = "01",
    tags: Optional[List[str]] = None,
) -> "CapabilityBusEntry":
    from core.capability_bus import CapabilityBusEntry, CapabilityBusRole, CapabilityHealthStatus
    return CapabilityBusEntry(
        name=name,
        display_name=f"Node 01 (node {source_id})",
        description="Test node entry",
        role=CapabilityBusRole(role_str),
        source_id=source_id,
        health=CapabilityHealthStatus(health_str),
        tags=tags or ["node"],
    )


# ===========================================================================
# Section 1 — Enum correctness
# ===========================================================================

class TestCapabilityBusRoleEnum:
    """CapabilityBusRole values and from_tool_name() classification."""

    def test_all_expected_roles_present(self):
        from core.capability_bus import CapabilityBusRole
        expected = {"node", "device", "skill", "mcp", "mcp_gw", "github", "academic", "engineering", "resource", "builtin", "unknown"}
        actual = {r.value for r in CapabilityBusRole}
        assert expected == actual

    def test_from_tool_name_node(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("node__08__execute") == CapabilityBusRole.NODE

    def test_from_tool_name_device(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("device__android_01__tap") == CapabilityBusRole.DEVICE

    def test_from_tool_name_skill(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("skill__hello") == CapabilityBusRole.SKILL

    def test_from_tool_name_mcp(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("mcp__weather__get_forecast") == CapabilityBusRole.MCP

    def test_from_tool_name_mcp_gw(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("mcp__gateway__search") == CapabilityBusRole.MCP_GW

    def test_from_tool_name_github(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("github__install") == CapabilityBusRole.GITHUB

    def test_from_tool_name_builtin(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("builtin__chat") == CapabilityBusRole.BUILTIN

    def test_from_tool_name_unknown_prefix(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("legacy__something") == CapabilityBusRole.UNKNOWN

    def test_from_tool_name_empty_string(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("") == CapabilityBusRole.UNKNOWN


class TestCapabilityHealthStatusEnum:
    """CapabilityHealthStatus values."""

    def test_all_expected_values_present(self):
        from core.capability_bus import CapabilityHealthStatus
        expected = {"healthy", "degraded", "unavailable", "unknown"}
        assert expected == {h.value for h in CapabilityHealthStatus}


# ===========================================================================
# Section 2 — CapabilityBusEntry serialisation
# ===========================================================================

class TestCapabilityBusEntrySerialisation:
    """to_dict / from_dict round-trip."""

    def test_to_dict_has_required_keys(self):
        entry = _fresh_entry()
        d = entry.to_dict()
        for key in ("name", "display_name", "description", "role", "source_id",
                    "health", "tags", "metadata", "schema", "node_key", "registered_at"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_role_is_string(self):
        entry = _fresh_entry()
        d = entry.to_dict()
        assert isinstance(d["role"], str)

    def test_to_dict_health_is_string(self):
        entry = _fresh_entry()
        d = entry.to_dict()
        assert isinstance(d["health"], str)

    def test_from_dict_roundtrip(self):
        entry = _fresh_entry(name="skill__test_skill", role_str="skill", source_id="test_skill")
        d = entry.to_dict()
        from core.capability_bus import CapabilityBusEntry
        restored = CapabilityBusEntry.from_dict(d)
        assert restored.name == entry.name
        assert restored.role == entry.role
        assert restored.health == entry.health
        assert restored.source_id == entry.source_id

    def test_from_dict_unknown_role_defaults(self):
        from core.capability_bus import CapabilityBusEntry, CapabilityBusRole
        d = {"name": "x", "display_name": "x", "description": "x", "role": "nonexistent_role"}
        e = CapabilityBusEntry.from_dict(d)
        assert e.role == CapabilityBusRole.UNKNOWN

    def test_from_dict_unknown_health_defaults(self):
        from core.capability_bus import CapabilityBusEntry, CapabilityHealthStatus
        d = {"name": "x", "display_name": "x", "description": "x", "health": "bad_value"}
        e = CapabilityBusEntry.from_dict(d)
        assert e.health == CapabilityHealthStatus.UNKNOWN

    def test_to_dict_is_json_serialisable(self):
        entry = _fresh_entry(tags=["a", "b"])
        d = entry.to_dict()
        serialised = json.dumps(d)  # should not raise
        assert "node" in serialised


# ===========================================================================
# Section 3 — CapabilityBus register / unregister / lookup / contains
# ===========================================================================

class TestCapabilityBusRegistration:
    """Basic register / lookup / unregister behaviour."""

    def test_register_and_lookup(self):
        bus = _fresh_bus()
        entry = _fresh_entry()
        bus.register(entry)
        result = bus.lookup(entry.name)
        assert result is not None
        assert result.name == entry.name

    def test_lookup_missing_returns_none(self):
        bus = _fresh_bus()
        assert bus.lookup("nonexistent__cap") is None

    def test_contains_after_register(self):
        bus = _fresh_bus()
        entry = _fresh_entry()
        bus.register(entry)
        assert bus.contains(entry.name)

    def test_contains_false_for_unknown(self):
        bus = _fresh_bus()
        assert not bus.contains("node__99__execute")

    def test_unregister_removes_entry(self):
        bus = _fresh_bus()
        entry = _fresh_entry()
        bus.register(entry)
        result = bus.unregister(entry.name)
        assert result is True
        assert bus.lookup(entry.name) is None

    def test_unregister_missing_returns_false(self):
        bus = _fresh_bus()
        assert bus.unregister("nonexistent") is False

    def test_register_empty_name_raises(self):
        from core.capability_bus import CapabilityBusEntry, CapabilityBusRole, CapabilityHealthStatus
        bus = _fresh_bus()
        bad = CapabilityBusEntry(name="", display_name="x", description="x",
                                 role=CapabilityBusRole.NODE)
        with pytest.raises(ValueError):
            bus.register(bad)

    def test_duplicate_register_replaces_entry(self):
        from core.capability_bus import CapabilityBusEntry, CapabilityBusRole, CapabilityHealthStatus
        bus = _fresh_bus()
        e1 = CapabilityBusEntry(name="node__01__execute", display_name="v1",
                                description="v1", role=CapabilityBusRole.NODE)
        e2 = CapabilityBusEntry(name="node__01__execute", display_name="v2",
                                description="v2", role=CapabilityBusRole.NODE)
        bus.register(e1)
        bus.register(e2)
        assert bus.lookup("node__01__execute").display_name == "v2"

    def test_list_all_returns_all_entries(self):
        bus = _fresh_bus()
        for i in range(5):
            bus.register(_fresh_entry(name=f"node__{i:02d}__execute", source_id=str(i)))
        assert len(bus.list_all()) == 5

    def test_clear_removes_all_entries(self):
        bus = _fresh_bus()
        bus.register(_fresh_entry())
        bus.clear()
        assert bus.list_all() == []


# ===========================================================================
# Section 4 — list_by_role
# ===========================================================================

class TestListByRole:
    """list_by_role filtering."""

    def test_filter_nodes_only(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.register(_fresh_entry(name="node__01__execute", role_str="node"))
        bus.register(_fresh_entry(name="skill__hello", role_str="skill", source_id="hello"))
        nodes = bus.list_by_role(CapabilityBusRole.NODE)
        assert len(nodes) == 1
        assert nodes[0].name == "node__01__execute"

    def test_filter_skills_only(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.register(_fresh_entry(name="node__01__execute", role_str="node"))
        bus.register(_fresh_entry(name="skill__hello", role_str="skill", source_id="hello"))
        skills = bus.list_by_role(CapabilityBusRole.SKILL)
        assert len(skills) == 1
        assert skills[0].name == "skill__hello"

    def test_filter_returns_empty_for_missing_role(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.register(_fresh_entry(name="node__01__execute", role_str="node"))
        assert bus.list_by_role(CapabilityBusRole.DEVICE) == []


# ===========================================================================
# Section 5 — set_health
# ===========================================================================

class TestSetHealth:
    """set_health updates health, other fields unchanged."""

    def test_set_health_healthy(self):
        from core.capability_bus import CapabilityHealthStatus
        bus = _fresh_bus()
        entry = _fresh_entry(health_str="unknown")
        bus.register(entry)
        result = bus.set_health(entry.name, CapabilityHealthStatus.HEALTHY)
        assert result is True
        updated = bus.lookup(entry.name)
        assert updated.health == CapabilityHealthStatus.HEALTHY

    def test_set_health_preserves_display_name(self):
        from core.capability_bus import CapabilityHealthStatus
        bus = _fresh_bus()
        entry = _fresh_entry()
        bus.register(entry)
        bus.set_health(entry.name, CapabilityHealthStatus.DEGRADED)
        updated = bus.lookup(entry.name)
        assert updated.display_name == entry.display_name

    def test_set_health_missing_returns_false(self):
        from core.capability_bus import CapabilityHealthStatus
        bus = _fresh_bus()
        assert bus.set_health("nonexistent", CapabilityHealthStatus.HEALTHY) is False


# ===========================================================================
# Section 6 — BusSnapshot
# ===========================================================================

class TestBusSnapshot:
    """bus_snapshot returns correct state."""

    def test_total_count(self):
        bus = _fresh_bus()
        for i in range(3):
            bus.register(_fresh_entry(name=f"node__{i}__execute", source_id=str(i)))
        snap = bus.bus_snapshot()
        assert snap.total_count == 3

    def test_by_role_counts(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.register(_fresh_entry(name="node__01__execute", role_str="node"))
        bus.register(_fresh_entry(name="skill__hello", role_str="skill", source_id="hello"))
        snap = bus.bus_snapshot()
        assert snap.by_role.get("node", 0) == 1
        assert snap.by_role.get("skill", 0) == 1

    def test_healthy_count(self):
        from core.capability_bus import CapabilityHealthStatus
        bus = _fresh_bus()
        bus.register(_fresh_entry(name="node__01__execute", health_str="healthy"))
        bus.register(_fresh_entry(name="node__02__execute", source_id="02", health_str="unknown"))
        snap = bus.bus_snapshot()
        assert snap.healthy_count == 1

    def test_seeded_flag_false_initially(self):
        bus = _fresh_bus()
        snap = bus.bus_snapshot()
        assert snap.seeded_from_node_registry is False

    def test_snapshot_to_dict_json_serialisable(self):
        bus = _fresh_bus()
        bus.register(_fresh_entry())
        snap = bus.bus_snapshot()
        serialised = json.dumps(snap.to_dict())
        assert "total_count" in serialised


# ===========================================================================
# Section 7 — seed_from_node_registry
# ===========================================================================

class TestSeedFromNodeRegistry:
    """Acceptance criterion: node-registry-derived nodes in capability universe."""

    def test_seed_returns_positive_count(self):
        bus = _fresh_bus()
        count = bus.seed_from_node_registry()
        assert count > 0, "Expected at least one node to be seeded"

    def test_seeded_flag_set(self):
        bus = _fresh_bus()
        bus.seed_from_node_registry()
        snap = bus.bus_snapshot()
        assert snap.seeded_from_node_registry is True

    def test_all_seeded_entries_have_node_role(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.seed_from_node_registry()
        nodes = bus.list_by_role(CapabilityBusRole.NODE)
        assert len(nodes) > 0
        for e in nodes:
            assert e.role == CapabilityBusRole.NODE

    def test_all_seeded_entries_have_node_prefix(self):
        bus = _fresh_bus()
        bus.seed_from_node_registry()
        for e in bus.list_by_role_str("node"):
            assert e.name.startswith("node__"), f"Bad prefix: {e.name}"

    def test_no_hardcoded_node_names(self):
        """Seeded entries names come from the registry file, not from a hardcoded list."""
        import os
        reg_path = str(PROJECT_ROOT / "config" / "node_registry.json")
        with open(reg_path) as fh:
            raw = json.load(fh)
        nodes_dict = raw.get("nodes", raw)
        registry_ids = {str(info.get("id", "")) for info in nodes_dict.values()
                        if isinstance(info, dict)}

        bus = _fresh_bus()
        bus.seed_from_node_registry()
        seeded_ids = {e.source_id for e in bus.list_by_role_str("node")}
        assert seeded_ids == registry_ids, (
            "Seeded source_ids should match registry IDs exactly — no hardcoding"
        )

    def test_seeded_entries_have_node_key(self):
        bus = _fresh_bus()
        bus.seed_from_node_registry()
        for e in bus.list_by_role_str("node"):
            assert e.node_key, f"node_key should be set for {e.name}"

    def test_active_production_ready_nodes_are_healthy(self):
        from core.capability_bus import CapabilityHealthStatus
        reg_path = str(PROJECT_ROOT / "config" / "node_registry.json")
        with open(reg_path) as fh:
            raw = json.load(fh)
        nodes_dict = raw.get("nodes", raw)

        bus = _fresh_bus()
        bus.seed_from_node_registry()

        for node_key, info in nodes_dict.items():
            if not isinstance(info, dict):
                continue
            if info.get("status") == "active" and info.get("production_ready"):
                node_id = str(info.get("id", ""))
                entry = bus.lookup(f"node__{node_id}__execute")
                assert entry is not None
                assert entry.health == CapabilityHealthStatus.HEALTHY, (
                    f"Expected HEALTHY for {node_key} but got {entry.health}"
                )

    def test_seed_is_idempotent(self):
        bus = _fresh_bus()
        count1 = bus.seed_from_node_registry()
        count2 = bus.seed_from_node_registry()
        # Second seed replaces entries; count should be the same
        assert count1 == count2
        assert len(bus.list_all()) == count1

    def test_seed_missing_file_returns_zero(self):
        bus = _fresh_bus()
        count = bus.seed_from_node_registry(registry_path="/nonexistent/path.json")
        assert count == 0

    def test_snapshot_total_includes_seeded_nodes(self):
        bus = _fresh_bus()
        count = bus.seed_from_node_registry()
        snap = bus.bus_snapshot()
        assert snap.total_count >= count


# Helper: CapabilityBus.list_by_role_str convenience wrapper for tests.
# We patch CapabilityBus to add a helper so tests aren't fragile.
from core.capability_bus import CapabilityBus as _CapabilityBus


def _list_by_role_str(self, role_str: str):
    from core.capability_bus import CapabilityBusRole
    try:
        role = CapabilityBusRole(role_str)
    except ValueError:
        return []
    return self.list_by_role(role)


_CapabilityBus.list_by_role_str = _list_by_role_str  # type: ignore[attr-defined]


# ===========================================================================
# Section 8 — Device capability registration
# ===========================================================================

class TestDeviceCapabilityRegistration:
    """register_device_capability creates correct DEVICE entries."""

    def test_registers_device_entry(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        entry = bus.register_device_capability(
            device_id="android_001",
            action="take_screenshot",
            description="Capture the screen",
        )
        assert entry.name == "device__android_001__take_screenshot"
        assert entry.role == CapabilityBusRole.DEVICE

    def test_device_entry_in_bus(self):
        bus = _fresh_bus()
        bus.register_device_capability("android_001", "tap", "Tap at coordinates")
        assert bus.contains("device__android_001__tap")

    def test_device_entry_source_id(self):
        bus = _fresh_bus()
        entry = bus.register_device_capability("android_001", "swipe", "Swipe gesture")
        assert entry.source_id == "android_001"

    def test_device_entry_tags_include_device(self):
        bus = _fresh_bus()
        entry = bus.register_device_capability("android_001", "press_key", "Key press")
        assert "device" in entry.tags

    def test_device_entry_custom_tags(self):
        bus = _fresh_bus()
        entry = bus.register_device_capability(
            "android_001", "type_text", "Type text", tags=["input", "keyboard"]
        )
        assert "input" in entry.tags
        assert "keyboard" in entry.tags
        assert "device" in entry.tags

    def test_device_entry_display_name_default(self):
        bus = _fresh_bus()
        entry = bus.register_device_capability("dev1", "unlock", "Unlock device")
        assert "unlock" in entry.display_name

    def test_device_entry_display_name_custom(self):
        bus = _fresh_bus()
        entry = bus.register_device_capability(
            "dev1", "lock", "Lock device", display_name="Lock Screen"
        )
        assert entry.display_name == "Lock Screen"

    def test_multiple_device_actions(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        for action in ("tap", "swipe", "take_screenshot"):
            bus.register_device_capability("android_001", action, f"Device {action}")
        devices = bus.list_by_role(CapabilityBusRole.DEVICE)
        assert len(devices) == 3

    def test_list_by_role_device(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        bus.register_device_capability("phone_a", "tap", "Tap")
        bus.register(_fresh_entry(name="node__01__execute", role_str="node"))
        devices = bus.list_by_role(CapabilityBusRole.DEVICE)
        assert len(devices) == 1
        assert devices[0].source_id == "phone_a"


# ===========================================================================
# Section 9 — MCP and Skill registration helpers
# ===========================================================================

class TestMcpAndSkillRegistration:
    """register_mcp_tool and register_skill helpers."""

    def test_register_mcp_tool(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        entry = bus.register_mcp_tool("weather_api", "get_forecast", "Get weather forecast")
        assert entry.name == "mcp__weather_api__get_forecast"
        assert entry.role == CapabilityBusRole.MCP

    def test_register_mcp_gateway_tool(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        entry = bus.register_mcp_tool("gateway", "search_web", "Search the web")
        assert entry.name == "mcp__gateway__search_web"
        assert entry.role == CapabilityBusRole.MCP_GW

    def test_register_skill(self):
        from core.capability_bus import CapabilityBusRole
        bus = _fresh_bus()
        entry = bus.register_skill("hello_world", "Say hello")
        assert entry.name == "skill__hello_world"
        assert entry.role == CapabilityBusRole.SKILL

    def test_mcp_tags_include_mcp(self):
        bus = _fresh_bus()
        entry = bus.register_mcp_tool("srv1", "tool1", "Test tool")
        assert "mcp" in entry.tags

    def test_skill_tags_include_skill(self):
        bus = _fresh_bus()
        entry = bus.register_skill("my_skill", "My skill description")
        assert "skill" in entry.tags


# ===========================================================================
# Section 10 — Singleton behaviour
# ===========================================================================

class TestSingleton:
    """get_capability_bus / reset_capability_bus singleton semantics."""

    def test_get_returns_same_instance(self):
        from core.capability_bus import get_capability_bus
        bus1 = get_capability_bus()
        bus2 = get_capability_bus()
        assert bus1 is bus2

    def test_reset_returns_fresh_instance(self):
        from core.capability_bus import get_capability_bus, reset_capability_bus
        bus_before = get_capability_bus()
        bus_before.register(_fresh_entry())
        reset = reset_capability_bus()
        assert reset is not bus_before
        # Fresh instance has no entries
        assert reset.list_all() == []

    def test_reset_updates_singleton(self):
        from core.capability_bus import get_capability_bus, reset_capability_bus
        reset_capability_bus()
        bus = get_capability_bus()
        assert bus.list_all() == []


# ===========================================================================
# Section 11 — Thread safety
# ===========================================================================

class TestThreadSafety:
    """Concurrent registrations do not corrupt bus state."""

    def test_concurrent_registrations(self):
        from core.capability_bus import CapabilityBusEntry, CapabilityBusRole, CapabilityHealthStatus
        bus = _fresh_bus()
        errors: List[Exception] = []

        def register_batch(start: int, count: int) -> None:
            try:
                for i in range(start, start + count):
                    e = CapabilityBusEntry(
                        name=f"node__{i:03d}__execute",
                        display_name=f"Node {i}",
                        description=f"Test node {i}",
                        role=CapabilityBusRole.NODE,
                        source_id=str(i),
                    )
                    bus.register(e)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=register_batch, args=(i * 10, 10))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(bus.list_all()) == 50


# ===========================================================================
# Section 12 — CapabilityLayer.DEVICE in canonical_dispatcher
# ===========================================================================

class TestCanonicalDispatcherDeviceLayer:
    """CapabilityLayer.DEVICE is present and classifies device__ prefixes."""

    def test_device_layer_enum_member_exists(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert hasattr(CapabilityLayer, "DEVICE")
        assert CapabilityLayer.DEVICE.value == "device"

    def test_classify_device_prefix(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        layer = CapabilityLayer.classify("device__android_001__tap")
        assert layer == CapabilityLayer.DEVICE

    def test_classify_node_still_works(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert CapabilityLayer.classify("node__08__execute") == CapabilityLayer.NODE

    def test_classify_mcp_still_works(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert CapabilityLayer.classify("mcp__weather__forecast") == CapabilityLayer.MCP

    def test_classify_skill_still_works(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert CapabilityLayer.classify("skill__hello") == CapabilityLayer.SKILL

    def test_classify_github_still_works(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert CapabilityLayer.classify("github__install") == CapabilityLayer.GITHUB

    def test_classify_unknown_still_works(self):
        from core.capabilities.canonical_dispatcher import CapabilityLayer
        assert CapabilityLayer.classify("mystery__thing") == CapabilityLayer.UNKNOWN


# ===========================================================================
# Section 13 — bus_catalog() on CanonicalDispatcher
# ===========================================================================

class TestDispatcherBusCatalog:
    """CanonicalDispatcher.bus_catalog() returns a snapshot dict."""

    def test_bus_catalog_returns_dict(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        d = CanonicalDispatcher()
        result = d.bus_catalog()
        assert isinstance(result, dict)

    def test_bus_catalog_has_total_count(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        from core.capability_bus import reset_capability_bus
        reset_capability_bus()
        d = CanonicalDispatcher()
        result = d.bus_catalog()
        assert "total_count" in result

    def test_bus_catalog_reflects_registered_entries(self):
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        from core.capability_bus import reset_capability_bus
        bus = reset_capability_bus()
        bus.register(_fresh_entry())
        d = CanonicalDispatcher()
        result = d.bus_catalog()
        assert result["total_count"] == 1


# ===========================================================================
# Section 14 — capabilities/__init__.py exports
# ===========================================================================

class TestCapabilitiesPackageExports:
    """core.capabilities re-exports CapabilityBus symbols."""

    def test_get_capability_bus_importable_from_capabilities(self):
        from core.capabilities import get_capability_bus
        assert callable(get_capability_bus)

    def test_reset_capability_bus_importable_from_capabilities(self):
        from core.capabilities import reset_capability_bus
        assert callable(reset_capability_bus)

    def test_capability_bus_class_importable(self):
        from core.capabilities import CapabilityBus
        assert CapabilityBus is not None

    def test_capability_bus_entry_importable(self):
        from core.capabilities import CapabilityBusEntry
        assert CapabilityBusEntry is not None

    def test_capability_bus_role_importable(self):
        from core.capabilities import CapabilityBusRole
        assert CapabilityBusRole is not None

    def test_bus_snapshot_importable(self):
        from core.capabilities import BusSnapshot
        assert BusSnapshot is not None


# ===========================================================================
# Section 15 — No parallel capability table
# ===========================================================================

class TestNoParallelCapabilityTable:
    """Acceptance criterion: CapabilityBus is the single canonical registry.

    There must be no new hardcoded parallel capability table introduced in
    core/capability_bus.py or core/capabilities/canonical_dispatcher.py.
    This is enforced by inspecting that the bus reads from the existing
    config/node_registry.json rather than having a hardcoded list.
    """

    def test_capability_bus_py_has_no_hardcoded_node_list(self):
        """capability_bus.py must not contain a hardcoded list of node IDs."""
        bus_path = PROJECT_ROOT / "core" / "capability_bus.py"
        content = bus_path.read_text(encoding="utf-8")
        # Check that the file does not contain a hardcoded list/dict of all
        # node names.  A hardcoded list would look like a Python list/dict
        # literal with many Node_ entries.  Using a heuristic: if there are
        # more than 5 occurrences of "Node_" in the file it's a red flag.
        node_ref_count = content.count("Node_")
        assert node_ref_count <= 5, (
            f"capability_bus.py contains {node_ref_count} 'Node_' references — "
            "suggests hardcoded node list instead of reading from JSON registry"
        )

    def test_seed_reads_from_json_file(self):
        """seed_from_node_registry must read from the JSON file, not a hardcoded list."""
        bus = _fresh_bus()
        # Seed with a temporary file containing 2 custom nodes
        import tempfile
        import os
        custom_registry = {
            "nodes": {
                "Custom_Node_A": {"id": "A1", "name": "NodeA", "status": "active",
                                  "production_ready": True},
                "Custom_Node_B": {"id": "B2", "name": "NodeB", "status": "inactive",
                                  "production_ready": False},
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as fh:
            json.dump(custom_registry, fh)
            tmp_path = fh.name
        try:
            count = bus.seed_from_node_registry(registry_path=tmp_path)
            assert count == 2
            assert bus.contains("node__A1__execute")
            assert bus.contains("node__B2__execute")
        finally:
            os.unlink(tmp_path)
