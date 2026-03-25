"""
tests/test_pr7_governed_system_resource_layer.py
=================================================
PR-7 "Governed System Resource Layer" test suite.

Acceptance criteria coverage:
  a) GitHub, academic, and at least one additional external/runtime-facing
     integration (device) can be represented through the governed system
     resource model.
     (SystemResourceRecord with correct resource_type, source, trust_level,
      capabilities; seed helpers produce valid records)
  b) OpenClawd can consume those resources without relying only on scattered
     hardcoded subsystem assumptions.
     (resource__list / resource__status / resource__health / resource__lookup
      dispatch through _dispatch_resource_tool; no new parallel resource
      authority is introduced)
  c) Resource metadata and attribution survive through the relevant execution
     path.
     (SystemResourceRecord.to_dict()/from_dict() round-trips; source and
      trust_level preserved; CapabilityBus entries carry resource tags)
  d) No new parallel resource registry/authority is introduced without clear
     justification.
     (All paths use get_system_resource_registry() singleton; RESOURCE role
      routes through CapabilityBus, not a competing store)
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously in an isolated event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_openclawd():
    """Return a minimally configured OpenClawd instance."""
    from core.openclawd import OpenClawd
    oc = OpenClawd.__new__(OpenClawd)
    oc._node_registry = {}
    oc._node_cache = {}
    oc._node_id_to_key = {}
    oc._skills = {}
    oc._mcp_tools = {}
    oc._pr8_trace_id = ""
    oc._pr8_session_id = ""
    oc._CORE_NODE_ACTIONS = {}
    oc._continuum_orchestrator = None
    oc._tool_permission_checker = None
    return oc


# ===========================================================================
# 1. Enum correctness
# ===========================================================================

class TestEnums:
    """All required enum values are present and have correct string values."""

    def test_system_resource_type_values(self):
        from core.system_resource import SystemResourceType
        for name, value in (
            ("GITHUB", "github"),
            ("ACADEMIC", "academic"),
            ("DEVICE", "device"),
            ("LOCAL_TOOL", "local_tool"),
            ("ENGINEERING", "engineering"),
            ("MCP", "mcp"),
            ("SKILL", "skill"),
            ("NODE", "node"),
            ("BUILTIN", "builtin"),
            ("UNKNOWN", "unknown"),
        ):
            assert hasattr(SystemResourceType, name), f"Missing: {name}"
            assert SystemResourceType[name].value == value

    def test_system_resource_health_values(self):
        from core.system_resource import SystemResourceHealth
        for name in ("HEALTHY", "DEGRADED", "UNAVAILABLE", "UNKNOWN"):
            assert hasattr(SystemResourceHealth, name), f"Missing: {name}"

    def test_trust_level_values(self):
        from core.system_resource import TrustLevel
        for name in ("TRUSTED", "VERIFIED", "RESTRICTED", "UNTRUSTED"):
            assert hasattr(TrustLevel, name), f"Missing: {name}"

    def test_system_resource_availability_values(self):
        from core.system_resource import SystemResourceAvailability
        for name in ("AVAILABLE", "LIMITED", "UNAVAILABLE", "UNKNOWN"):
            assert hasattr(SystemResourceAvailability, name), f"Missing: {name}"


# ===========================================================================
# 2. SystemResourceRecord — creation and serialisation
# ===========================================================================

class TestSystemResourceRecord:
    """SystemResourceRecord is created correctly and round-trips through dict."""

    def test_default_creation(self):
        from core.system_resource import SystemResourceRecord, SystemResourceType
        rec = SystemResourceRecord()
        assert rec.resource_id.startswith("res_")
        assert rec.resource_type == SystemResourceType.UNKNOWN
        assert rec.source == ""
        assert isinstance(rec.capabilities, list)
        assert isinstance(rec.tags, list)
        assert isinstance(rec.metadata, dict)

    def test_explicit_creation(self):
        from core.system_resource import (
            SystemResourceRecord, SystemResourceType, SystemResourceHealth,
            TrustLevel, SystemResourceAvailability,
        )
        rec = SystemResourceRecord(
            resource_id="test__gh",
            resource_type=SystemResourceType.GITHUB,
            source="github://api.github.com",
            origin="GitHub integration",
            health=SystemResourceHealth.HEALTHY,
            availability=SystemResourceAvailability.AVAILABLE,
            trust_level=TrustLevel.VERIFIED,
            auth_scope="token:GITHUB_TOKEN",
            capabilities=["github__ingest", "github__context"],
            tags=["github", "knowledge"],
            metadata={"pr": 4},
        )
        assert rec.resource_id == "test__gh"
        assert rec.resource_type == SystemResourceType.GITHUB
        assert rec.trust_level == TrustLevel.VERIFIED

    def test_to_dict_keys(self):
        from core.system_resource import SystemResourceRecord
        d = SystemResourceRecord().to_dict()
        for key in (
            "resource_id", "resource_type", "source", "origin",
            "health", "availability", "trust_level", "auth_scope",
            "capabilities", "tags", "metadata", "registered_at",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_enum_values_are_strings(self):
        from core.system_resource import SystemResourceRecord, SystemResourceType
        d = SystemResourceRecord(resource_type=SystemResourceType.GITHUB).to_dict()
        assert d["resource_type"] == "github"
        assert isinstance(d["health"], str)
        assert isinstance(d["trust_level"], str)

    def test_from_dict_round_trip(self):
        from core.system_resource import (
            SystemResourceRecord, SystemResourceType, TrustLevel,
        )
        orig = SystemResourceRecord(
            resource_id="roundtrip_01",
            resource_type=SystemResourceType.ACADEMIC,
            source="academic://arxiv",
            trust_level=TrustLevel.TRUSTED,
            capabilities=["academic__search"],
            tags=["academic"],
        )
        d = orig.to_dict()
        restored = SystemResourceRecord.from_dict(d)
        assert restored.resource_id == "roundtrip_01"
        assert restored.resource_type == SystemResourceType.ACADEMIC
        assert restored.trust_level == TrustLevel.TRUSTED
        assert restored.capabilities == ["academic__search"]

    def test_from_dict_handles_unknown_enum(self):
        from core.system_resource import SystemResourceRecord, SystemResourceType, TrustLevel
        d = {
            "resource_id": "bad_type",
            "resource_type": "nonexistent_type",
            "trust_level": "nonexistent_trust",
        }
        rec = SystemResourceRecord.from_dict(d)
        assert rec.resource_type == SystemResourceType.UNKNOWN
        assert rec.trust_level == TrustLevel.VERIFIED  # default

    def test_resource_id_uniqueness(self):
        from core.system_resource import SystemResourceRecord
        ids = {SystemResourceRecord().resource_id for _ in range(20)}
        assert len(ids) == 20


# ===========================================================================
# 3. SystemResourceSnapshot
# ===========================================================================

class TestSystemResourceSnapshot:
    """SystemResourceSnapshot aggregates counts correctly."""

    def test_snapshot_to_dict_keys(self):
        from core.system_resource import SystemResourceSnapshot
        d = SystemResourceSnapshot().to_dict()
        for key in ("resources", "total_count", "healthy_count", "unavailable_count", "captured_at"):
            assert key in d

    def test_snapshot_counts_match(self):
        from core.system_resource import (
            SystemResourceSnapshot, SystemResourceRecord,
            SystemResourceHealth, SystemResourceType,
        )
        recs = [
            SystemResourceRecord(health=SystemResourceHealth.HEALTHY, resource_type=SystemResourceType.GITHUB),
            SystemResourceRecord(health=SystemResourceHealth.HEALTHY, resource_type=SystemResourceType.ACADEMIC),
            SystemResourceRecord(health=SystemResourceHealth.UNAVAILABLE, resource_type=SystemResourceType.DEVICE),
            SystemResourceRecord(health=SystemResourceHealth.UNKNOWN, resource_type=SystemResourceType.MCP),
        ]
        snap = SystemResourceSnapshot(
            resources=recs,
            total_count=4,
            healthy_count=2,
            unavailable_count=1,
        )
        d = snap.to_dict()
        assert d["total_count"] == 4
        assert d["healthy_count"] == 2
        assert d["unavailable_count"] == 1
        assert len(d["resources"]) == 4


# ===========================================================================
# 4. SystemResourceRegistry — registration and discovery
# ===========================================================================

class TestSystemResourceRegistry:
    """Registry enrol, discover, update, and snapshot operations."""

    def _fresh_registry(self):
        from core.system_resource import SystemResourceRegistry
        return SystemResourceRegistry()

    def test_register_and_lookup(self):
        from core.system_resource import SystemResourceRecord, SystemResourceType
        reg = self._fresh_registry()
        rec = SystemResourceRecord(resource_id="res_test_01", resource_type=SystemResourceType.GITHUB)
        reg.register(rec)
        found = reg.lookup("res_test_01")
        assert found is rec

    def test_lookup_missing_returns_none(self):
        reg = self._fresh_registry()
        assert reg.lookup("nonexistent_id") is None

    def test_lookup_by_source(self):
        from core.system_resource import SystemResourceRecord
        reg = self._fresh_registry()
        rec = SystemResourceRecord(resource_id="res_src_01", source="github://api.github.com")
        reg.register(rec)
        found = reg.lookup_by_source("github://api.github.com")
        assert found is rec

    def test_lookup_by_source_missing(self):
        reg = self._fresh_registry()
        assert reg.lookup_by_source("nonexistent://foo") is None

    def test_register_replaces_existing(self):
        from core.system_resource import SystemResourceRecord, SystemResourceHealth
        reg = self._fresh_registry()
        rec1 = SystemResourceRecord(resource_id="res_dup", health=SystemResourceHealth.UNKNOWN)
        rec2 = SystemResourceRecord(resource_id="res_dup", health=SystemResourceHealth.HEALTHY)
        reg.register(rec1)
        reg.register(rec2)
        found = reg.lookup("res_dup")
        assert found.health == SystemResourceHealth.HEALTHY

    def test_unregister_returns_true_when_found(self):
        from core.system_resource import SystemResourceRecord
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="res_del"))
        assert reg.unregister("res_del") is True
        assert reg.lookup("res_del") is None

    def test_unregister_returns_false_when_missing(self):
        reg = self._fresh_registry()
        assert reg.unregister("nonexistent") is False

    def test_list_all(self):
        from core.system_resource import SystemResourceRecord
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="r1"))
        reg.register(SystemResourceRecord(resource_id="r2"))
        all_recs = reg.list_all()
        ids = {r.resource_id for r in all_recs}
        assert "r1" in ids
        assert "r2" in ids

    def test_list_by_type(self):
        from core.system_resource import SystemResourceRecord, SystemResourceType
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="gh1", resource_type=SystemResourceType.GITHUB))
        reg.register(SystemResourceRecord(resource_id="gh2", resource_type=SystemResourceType.GITHUB))
        reg.register(SystemResourceRecord(resource_id="ac1", resource_type=SystemResourceType.ACADEMIC))
        github_recs = reg.list_by_type(SystemResourceType.GITHUB)
        assert len(github_recs) == 2
        academic_recs = reg.list_by_type(SystemResourceType.ACADEMIC)
        assert len(academic_recs) == 1

    def test_set_health_returns_true_when_found(self):
        from core.system_resource import SystemResourceRecord, SystemResourceHealth
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="res_health"))
        updated = reg.set_health("res_health", SystemResourceHealth.DEGRADED)
        assert updated is True
        rec = reg.lookup("res_health")
        assert rec.health == SystemResourceHealth.DEGRADED

    def test_set_health_with_availability(self):
        from core.system_resource import (
            SystemResourceRecord, SystemResourceHealth, SystemResourceAvailability,
        )
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="res_avail"))
        reg.set_health("res_avail", SystemResourceHealth.DEGRADED, SystemResourceAvailability.LIMITED)
        rec = reg.lookup("res_avail")
        assert rec.availability == SystemResourceAvailability.LIMITED

    def test_set_health_returns_false_when_missing(self):
        from core.system_resource import SystemResourceHealth
        reg = self._fresh_registry()
        assert reg.set_health("nonexistent", SystemResourceHealth.HEALTHY) is False

    def test_snapshot_structure(self):
        from core.system_resource import SystemResourceRecord, SystemResourceHealth, SystemResourceType
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(
            resource_id="snap1", health=SystemResourceHealth.HEALTHY,
            resource_type=SystemResourceType.GITHUB,
        ))
        reg.register(SystemResourceRecord(
            resource_id="snap2", health=SystemResourceHealth.UNAVAILABLE,
            resource_type=SystemResourceType.DEVICE,
        ))
        snap = reg.snapshot()
        assert snap.total_count == 2
        assert snap.healthy_count == 1
        assert snap.unavailable_count == 1

    def test_snapshot_to_dict(self):
        from core.system_resource import SystemResourceRecord
        reg = self._fresh_registry()
        reg.register(SystemResourceRecord(resource_id="sd1"))
        d = reg.snapshot().to_dict()
        assert isinstance(d["resources"], list)
        assert d["total_count"] == 1


# ===========================================================================
# 5. Module-level singleton
# ===========================================================================

class TestModuleSingleton:
    """get_system_resource_registry() always returns the same instance."""

    def test_singleton_identity(self):
        from core.system_resource import get_system_resource_registry
        a = get_system_resource_registry()
        b = get_system_resource_registry()
        assert a is b

    def test_reset_produces_fresh_registry(self):
        from core.system_resource import (
            get_system_resource_registry, reset_system_resource_registry,
            SystemResourceRecord,
        )
        reset_system_resource_registry()
        reg = get_system_resource_registry()
        reg.register(SystemResourceRecord(resource_id="before_reset"))

        reset_system_resource_registry()
        fresh = get_system_resource_registry()
        assert fresh.lookup("before_reset") is None

    def test_reset_returns_new_instance(self):
        from core.system_resource import (
            get_system_resource_registry, reset_system_resource_registry,
        )
        before = get_system_resource_registry()
        reset_system_resource_registry()
        after = get_system_resource_registry()
        assert before is not after


# ===========================================================================
# 6. Built-in seeder helpers (acceptance criterion a)
# ===========================================================================

class TestSeederHelpers:
    """Seeder helpers produce correct SystemResourceRecord entries."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_seed_github_resource(self):
        from core.system_resource import (
            seed_github_resource, get_system_resource_registry,
            SystemResourceType, TrustLevel,
        )
        rec = seed_github_resource()
        assert rec.resource_type == SystemResourceType.GITHUB
        assert rec.resource_id == "builtin__github"
        assert "github" in rec.source
        assert rec.trust_level == TrustLevel.VERIFIED
        assert "github__ingest" in rec.capabilities
        assert "github__context" in rec.capabilities
        assert "github" in rec.tags
        # Check enrolled in singleton
        reg = get_system_resource_registry()
        assert reg.lookup("builtin__github") is rec

    def test_seed_academic_resource(self):
        from core.system_resource import (
            seed_academic_resource, get_system_resource_registry,
            SystemResourceType, TrustLevel, SystemResourceHealth,
        )
        rec = seed_academic_resource()
        assert rec.resource_type == SystemResourceType.ACADEMIC
        assert rec.resource_id == "builtin__academic"
        assert rec.trust_level == TrustLevel.TRUSTED
        assert rec.health == SystemResourceHealth.HEALTHY
        assert "academic__search" in rec.capabilities
        assert "academic__recall" in rec.capabilities
        reg = get_system_resource_registry()
        assert reg.lookup("builtin__academic") is rec

    def test_seed_engineering_resource(self):
        from core.system_resource import (
            seed_engineering_resource, get_system_resource_registry,
            SystemResourceType, TrustLevel,
        )
        rec = seed_engineering_resource()
        assert rec.resource_type == SystemResourceType.ENGINEERING
        assert rec.resource_id == "builtin__engineering"
        assert rec.trust_level == TrustLevel.TRUSTED
        assert "engineer__diagnose" in rec.capabilities
        assert "engineer__apply" in rec.capabilities
        reg = get_system_resource_registry()
        assert reg.lookup("builtin__engineering") is rec

    def test_seed_device_resource(self):
        from core.system_resource import (
            seed_device_resource, get_system_resource_registry,
            SystemResourceType, TrustLevel, SystemResourceHealth,
        )
        rec = seed_device_resource("android_001", capabilities=["device__android_001__screenshot"])
        assert rec.resource_type == SystemResourceType.DEVICE
        assert rec.resource_id == "device__android_001"
        assert rec.source == "device://android_001"
        assert rec.trust_level == TrustLevel.VERIFIED
        assert rec.health == SystemResourceHealth.UNKNOWN
        assert "device__android_001__screenshot" in rec.capabilities
        reg = get_system_resource_registry()
        assert reg.lookup("device__android_001") is rec

    def test_seed_local_tool_resource(self):
        from core.system_resource import (
            seed_local_tool_resource, get_system_resource_registry,
            SystemResourceType, TrustLevel, SystemResourceHealth,
        )
        rec = seed_local_tool_resource("file_system", capabilities=["node__06__read_file"])
        assert rec.resource_type == SystemResourceType.LOCAL_TOOL
        assert rec.resource_id == "local_tool__file_system"
        assert rec.trust_level == TrustLevel.TRUSTED
        assert rec.health == SystemResourceHealth.HEALTHY
        reg = get_system_resource_registry()
        assert reg.lookup("local_tool__file_system") is rec

    def test_seed_github_idempotent(self):
        """Multiple seed calls replace the record; registry stays clean."""
        from core.system_resource import seed_github_resource, get_system_resource_registry
        seed_github_resource()
        seed_github_resource()
        assert len(get_system_resource_registry().list_all()) == 1

    def test_seed_all_three_builtin_resources(self):
        """GitHub + academic + engineering all coexist without collision."""
        from core.system_resource import (
            seed_github_resource, seed_academic_resource, seed_engineering_resource,
            get_system_resource_registry,
        )
        seed_github_resource()
        seed_academic_resource()
        seed_engineering_resource()
        reg = get_system_resource_registry()
        assert reg.lookup("builtin__github") is not None
        assert reg.lookup("builtin__academic") is not None
        assert reg.lookup("builtin__engineering") is not None
        assert reg.snapshot().total_count == 3


# ===========================================================================
# 7. CapabilityBus — RESOURCE role and register_resource_capability
# ===========================================================================

class TestCapabilityBusResourceRole:
    """CapabilityBus gains RESOURCE role and register_resource_capability()."""

    def test_resource_role_exists(self):
        from core.capability_bus import CapabilityBusRole
        assert hasattr(CapabilityBusRole, "RESOURCE")
        assert CapabilityBusRole.RESOURCE.value == "resource"

    def test_from_tool_name_resource(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("resource__list") == CapabilityBusRole.RESOURCE
        assert CapabilityBusRole.from_tool_name("resource__status") == CapabilityBusRole.RESOURCE
        assert CapabilityBusRole.from_tool_name("resource__health") == CapabilityBusRole.RESOURCE

    def test_from_tool_name_existing_roles_unchanged(self):
        from core.capability_bus import CapabilityBusRole
        assert CapabilityBusRole.from_tool_name("github__install") == CapabilityBusRole.GITHUB
        assert CapabilityBusRole.from_tool_name("academic__search") == CapabilityBusRole.ACADEMIC
        assert CapabilityBusRole.from_tool_name("engineer__diagnose") == CapabilityBusRole.ENGINEERING

    def test_register_resource_capability_creates_entry(self):
        from core.capability_bus import CapabilityBus, CapabilityBusRole
        bus = CapabilityBus()
        entry = bus.register_resource_capability("list", description="List all governed resources")
        assert entry.name == "resource__list"
        assert entry.role == CapabilityBusRole.RESOURCE
        assert "resource" in entry.tags
        assert "governance" in entry.tags

    def test_register_resource_capability_visible_in_bus(self):
        from core.capability_bus import CapabilityBus, CapabilityBusRole
        bus = CapabilityBus()
        bus.register_resource_capability("status")
        found = bus.lookup("resource__status")
        assert found is not None
        assert found.role == CapabilityBusRole.RESOURCE

    def test_list_by_role_resource(self):
        from core.capability_bus import CapabilityBus, CapabilityBusRole
        bus = CapabilityBus()
        bus.register_resource_capability("list")
        bus.register_resource_capability("status")
        entries = bus.list_by_role(CapabilityBusRole.RESOURCE)
        names = {e.name for e in entries}
        assert "resource__list" in names
        assert "resource__status" in names

    def test_register_resource_capability_with_metadata(self):
        from core.capability_bus import CapabilityBus
        bus = CapabilityBus()
        entry = bus.register_resource_capability(
            "lookup",
            metadata={"pr": 7, "layer": "resource_governance"},
            tags=["custom_tag"],
        )
        assert entry.metadata["pr"] == 7
        assert "custom_tag" in entry.tags
        assert "resource" in entry.tags


# ===========================================================================
# 8. OpenClawd _RESOURCE_BUILTIN_TOOLS
# ===========================================================================

class TestResourceBuiltinTools:
    """_RESOURCE_BUILTIN_TOOLS contains the required tool definitions."""

    def test_resource_builtin_tools_exist(self):
        from core.openclawd import _RESOURCE_BUILTIN_TOOLS
        assert isinstance(_RESOURCE_BUILTIN_TOOLS, list)
        assert len(_RESOURCE_BUILTIN_TOOLS) >= 4

    def test_required_tool_names_present(self):
        from core.openclawd import _RESOURCE_BUILTIN_TOOLS
        names = {t["function"]["name"] for t in _RESOURCE_BUILTIN_TOOLS}
        for required in ("resource__list", "resource__status", "resource__health", "resource__lookup"):
            assert required in names, f"Missing tool: {required}"

    def test_tools_have_required_structure(self):
        from core.openclawd import _RESOURCE_BUILTIN_TOOLS
        for tool in _RESOURCE_BUILTIN_TOOLS:
            assert tool.get("type") == "function"
            fn = tool.get("function", {})
            assert "name" in fn
            assert "description" in fn
            assert isinstance(fn["description"], str) and fn["description"]

    def test_resource_tools_in_collect_tools(self):
        """resource__ tools appear in _collect_tools output."""
        oc = _make_openclawd()
        tools = oc._collect_tools()
        names = {t["function"]["name"] for t in tools}
        assert "resource__list" in names
        assert "resource__status" in names

    def test_collect_tools_still_has_github_and_academic(self):
        """Existing github__ and academic__ tools are still collected."""
        oc = _make_openclawd()
        tools = oc._collect_tools()
        names = {t["function"]["name"] for t in tools}
        assert "github__install" in names
        assert "academic__search" in names
        assert "engineer__diagnose" in names


# ===========================================================================
# 9. _dispatch_resource_tool — list action
# ===========================================================================

class TestDispatchResourceList:
    """resource__list dispatches correctly."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_list_all_returns_success(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {}))
        assert result["success"] is True
        assert "resources" in result
        assert "count" in result

    def test_list_all_shows_seeded_resources(self):
        from core.system_resource import seed_github_resource, seed_academic_resource
        seed_github_resource()
        seed_academic_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {}))
        assert result["count"] == 2

    def test_list_filtered_by_type(self):
        from core.system_resource import seed_github_resource, seed_academic_resource, seed_engineering_resource
        seed_github_resource()
        seed_academic_resource()
        seed_engineering_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {"resource_type": "github"}))
        assert result["success"] is True
        assert result["count"] == 1
        assert result["resources"][0]["resource_type"] == "github"

    def test_list_invalid_type_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {"resource_type": "nonexistent_type"}))
        assert result["success"] is False
        assert "resource_type" in result["error"].lower() or "nonexistent_type" in result["error"]


# ===========================================================================
# 10. _dispatch_resource_tool — status action
# ===========================================================================

class TestDispatchResourceStatus:
    """resource__status returns a valid snapshot."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_status_returns_success(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("status", {}))
        assert result["success"] is True

    def test_status_contains_counts(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("status", {}))
        assert "total_count" in result
        assert "healthy_count" in result
        assert "unavailable_count" in result

    def test_status_counts_reflect_seeded_resources(self):
        from core.system_resource import (
            seed_github_resource, seed_academic_resource,
            SystemResourceHealth, get_system_resource_registry,
        )
        seed_github_resource()
        r = seed_academic_resource()
        get_system_resource_registry().set_health("builtin__academic", SystemResourceHealth.HEALTHY)
        get_system_resource_registry().set_health("builtin__github", SystemResourceHealth.HEALTHY)
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("status", {}))
        assert result["total_count"] == 2
        assert result["healthy_count"] == 2


# ===========================================================================
# 11. _dispatch_resource_tool — health action
# ===========================================================================

class TestDispatchResourceHealth:
    """resource__health updates resource health/availability."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_health_update_valid(self):
        from core.system_resource import seed_github_resource, get_system_resource_registry, SystemResourceHealth
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {
            "resource_id": "builtin__github",
            "health": "degraded",
        }))
        assert result["success"] is True
        assert result["health"] == "degraded"
        rec = get_system_resource_registry().lookup("builtin__github")
        assert rec.health == SystemResourceHealth.DEGRADED

    def test_health_update_with_availability(self):
        from core.system_resource import (
            seed_github_resource, get_system_resource_registry,
            SystemResourceAvailability,
        )
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {
            "resource_id": "builtin__github",
            "health": "degraded",
            "availability": "limited",
        }))
        assert result["success"] is True
        rec = get_system_resource_registry().lookup("builtin__github")
        assert rec.availability == SystemResourceAvailability.LIMITED

    def test_health_missing_resource_id_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {"health": "healthy"}))
        assert result["success"] is False
        assert "resource_id" in result["error"]

    def test_health_missing_health_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {"resource_id": "builtin__github"}))
        assert result["success"] is False
        assert "health" in result["error"]

    def test_health_invalid_health_value_returns_error(self):
        from core.system_resource import seed_github_resource
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {
            "resource_id": "builtin__github",
            "health": "super_healthy",
        }))
        assert result["success"] is False
        assert "super_healthy" in result["error"]

    def test_health_nonexistent_resource_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("health", {
            "resource_id": "nonexistent__res",
            "health": "healthy",
        }))
        assert result["success"] is False
        assert "not found" in result["error"]


# ===========================================================================
# 12. _dispatch_resource_tool — lookup action
# ===========================================================================

class TestDispatchResourceLookup:
    """resource__lookup finds resources by ID or source."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_lookup_by_resource_id(self):
        from core.system_resource import seed_github_resource
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {"resource_id": "builtin__github"}))
        assert result["success"] is True
        assert result["resource"]["resource_id"] == "builtin__github"

    def test_lookup_by_source(self):
        from core.system_resource import seed_academic_resource
        seed_academic_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {"source": "academic://multi-source"}))
        assert result["success"] is True
        assert result["resource"]["resource_type"] == "academic"

    def test_lookup_not_found_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {"resource_id": "nonexistent__res"}))
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    def test_lookup_no_args_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {}))
        assert result["success"] is False

    def test_lookup_result_contains_attribution_fields(self):
        """Resource lookup result carries source attribution fields (criterion c)."""
        from core.system_resource import seed_academic_resource
        seed_academic_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {"resource_id": "builtin__academic"}))
        resource = result["resource"]
        assert "source" in resource
        assert "origin" in resource
        assert "trust_level" in resource
        assert "capabilities" in resource


# ===========================================================================
# 13. _dispatch_resource_tool — unknown action
# ===========================================================================

class TestDispatchResourceUnknown:
    def test_unknown_action_returns_error(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("fly_to_moon", {}))
        assert result["success"] is False
        assert "fly_to_moon" in result["error"]


# ===========================================================================
# 14. _dispatch_tool_call routes resource__ prefix (acceptance criterion b)
# ===========================================================================

class TestDispatchToolCallResourceRouting:
    """_dispatch_tool_call correctly routes resource__ prefixed tools."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_resource_list_via_dispatch_tool_call(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_tool_call("resource__list", {}))
        assert result["success"] is True
        assert "resources" in result

    def test_resource_status_via_dispatch_tool_call(self):
        oc = _make_openclawd()
        result = _run(oc._dispatch_tool_call("resource__status", {}))
        assert result["success"] is True
        assert "total_count" in result

    def test_existing_github_routing_still_works(self):
        """Existing github__ routing is unchanged (backward compat)."""
        oc = _make_openclawd()
        result = _run(oc._dispatch_tool_call("github__status", {}))
        # github__status always succeeds
        assert "success" in result

    def test_existing_academic_routing_still_works(self):
        """Existing academic__ routing is unchanged."""
        oc = _make_openclawd()
        result = _run(oc._dispatch_tool_call("academic__recall", {"query": "test"}))
        assert "success" in result

    def test_existing_engineer_routing_still_works(self):
        """Existing engineer__ routing is unchanged."""
        from core.system_resource import reset_system_resource_registry
        oc = _make_openclawd()
        result = _run(oc._dispatch_tool_call("engineer__status", {}))
        assert result["success"] is True


# ===========================================================================
# 15. Attribution survival (acceptance criterion c)
# ===========================================================================

class TestAttributionSurvival:
    """Resource metadata and attribution fields survive serialisation."""

    def test_github_source_attribution_fields(self):
        from core.system_resource import seed_github_resource
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()
        rec = seed_github_resource()
        d = rec.to_dict()
        assert d["source"].startswith("github://")
        assert d["trust_level"] == "verified"
        assert "github__ingest" in d["capabilities"]
        assert "github__context" in d["capabilities"]

    def test_academic_source_attribution_fields(self):
        from core.system_resource import seed_academic_resource
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()
        rec = seed_academic_resource()
        d = rec.to_dict()
        assert d["source"].startswith("academic://")
        assert d["trust_level"] == "trusted"
        assert "academic__search" in d["capabilities"]

    def test_device_source_attribution_fields(self):
        from core.system_resource import seed_device_resource
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()
        rec = seed_device_resource("tablet_001", capabilities=["device__tablet_001__capture"])
        d = rec.to_dict()
        assert d["source"] == "device://tablet_001"
        assert d["resource_type"] == "device"
        assert "device__tablet_001__capture" in d["capabilities"]

    def test_round_trip_preserves_source_attribution(self):
        """Source and trust_level survive to_dict → from_dict round-trip."""
        from core.system_resource import (
            SystemResourceRecord, SystemResourceType, TrustLevel,
        )
        orig = SystemResourceRecord(
            resource_id="attr_test",
            resource_type=SystemResourceType.GITHUB,
            source="github://owner/repo",
            origin="GitHub knowledge source",
            trust_level=TrustLevel.VERIFIED,
            capabilities=["github__ingest"],
            tags=["github", "knowledge"],
        )
        restored = SystemResourceRecord.from_dict(orig.to_dict())
        assert restored.source == "github://owner/repo"
        assert restored.trust_level == TrustLevel.VERIFIED
        assert restored.resource_type == SystemResourceType.GITHUB
        assert "github__ingest" in restored.capabilities


# ===========================================================================
# 16. No new parallel registry (acceptance criterion d)
# ===========================================================================

class TestNoParallelRegistry:
    """A single SystemResourceRegistry singleton is used throughout."""

    def test_singleton_is_always_same_object(self):
        from core.system_resource import get_system_resource_registry
        a = get_system_resource_registry()
        b = get_system_resource_registry()
        assert a is b

    def test_capability_bus_resource_role_routes_through_bus(self):
        """resource__ capabilities go through CapabilityBus, not a parallel store."""
        from core.capability_bus import CapabilityBus, CapabilityBusRole
        bus = CapabilityBus()
        bus.register_resource_capability("list")
        bus.register_resource_capability("status")
        bus.register_resource_capability("health")
        # All entries are in the CapabilityBus — no separate resource bus
        all_entries = bus.list_all()
        resource_entries = [e for e in all_entries if e.role == CapabilityBusRole.RESOURCE]
        assert len(resource_entries) == 3

    def test_resource_tool_dispatch_uses_singleton_registry(self):
        """_dispatch_resource_tool reads from the module-level singleton."""
        from core.system_resource import (
            seed_github_resource, get_system_resource_registry,
            reset_system_resource_registry,
        )
        reset_system_resource_registry()
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("lookup", {"resource_id": "builtin__github"}))
        assert result["success"] is True
        # Verify it used the singleton — remove and check miss
        get_system_resource_registry().unregister("builtin__github")
        result2 = _run(oc._dispatch_resource_tool("lookup", {"resource_id": "builtin__github"}))
        assert result2["success"] is False

    def test_no_competing_dispatch_authority(self):
        """The registry has no dispatch methods; dispatch stays in CapabilityBus/CanonicalDispatcher."""
        from core.system_resource import SystemResourceRegistry
        reg = SystemResourceRegistry()
        # Registry must not have dispatch-style methods
        assert not hasattr(reg, "dispatch")
        assert not hasattr(reg, "execute")
        assert not hasattr(reg, "call")


# ===========================================================================
# 17. OpenClawd integration — resource-aware reasoning (criterion b full)
# ===========================================================================

class TestOpenClawdResourceAwareness:
    """OpenClawd can consume governed resources without hardcoded subsystem assumptions."""

    def setup_method(self):
        from core.system_resource import reset_system_resource_registry
        reset_system_resource_registry()

    def test_list_by_type_academic_returns_academic_record(self):
        from core.system_resource import seed_academic_resource, seed_github_resource
        seed_academic_resource()
        seed_github_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {"resource_type": "academic"}))
        assert result["success"] is True
        assert result["count"] == 1
        assert result["resources"][0]["resource_type"] == "academic"

    def test_health_update_reflected_in_status(self):
        from core.system_resource import seed_github_resource
        seed_github_resource()
        oc = _make_openclawd()
        _run(oc._dispatch_resource_tool("health", {
            "resource_id": "builtin__github",
            "health": "healthy",
            "availability": "available",
        }))
        status = _run(oc._dispatch_resource_tool("status", {}))
        assert status["healthy_count"] == 1

    def test_all_three_builtin_resources_visible_to_openclawd(self):
        """OpenClawd can see GitHub, academic, and engineering resources."""
        from core.system_resource import (
            seed_github_resource, seed_academic_resource, seed_engineering_resource,
        )
        seed_github_resource()
        seed_academic_resource()
        seed_engineering_resource()
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {}))
        types = {r["resource_type"] for r in result["resources"]}
        assert "github" in types
        assert "academic" in types
        assert "engineering" in types

    def test_device_resource_visible_to_openclawd(self):
        """Device resources can be represented and seen by OpenClawd (criterion a)."""
        from core.system_resource import seed_device_resource
        seed_device_resource("android_phone", capabilities=["device__android_phone__screenshot"])
        oc = _make_openclawd()
        result = _run(oc._dispatch_resource_tool("list", {"resource_type": "device"}))
        assert result["success"] is True
        assert result["count"] == 1
        assert result["resources"][0]["resource_type"] == "device"
        assert "device__android_phone__screenshot" in result["resources"][0]["capabilities"]
