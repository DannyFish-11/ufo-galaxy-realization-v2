#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_capability_truth_convergence.py
==========================================
Acceptance tests — Capability Truth Convergence (PR: consolidate capability
truth around registry and resolver)

Validates that:
  1. CapabilityManager.register_capability() entries are visible through
     CapabilityResolver (bridge is active).
  2. CapabilityBus.register() entries are visible through CapabilityResolver
     (bridge is active).
  3. CapabilityManager entries registered via compat path reach
     CapabilityRegistry directly.
  4. CapabilityBus entries reach CapabilityRegistry (all role types).
  5. Governance sentinels are present in the expected modules.
  6. The canonical resolver path (CapabilityResolver) is the single read
     surface — CapabilityManager and CapabilityBus are bridges, not truth
     sinks.
  7. NodeFabricRegistry.sync_capabilities_to_registry() entries reach the
     resolver (pre-existing path, regression-check).
  8. Device-capability entries (simulate _sync_device_to_capability_registry)
     reach the resolver (pre-existing path, regression-check).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_all() -> None:
    """Reset all singleton registries between tests for isolation."""
    from core.agent.capability_registry import CapabilityRegistry
    from core.unified.capability_resolver import reset_capability_resolver
    from core.capability_bus import reset_capability_bus

    reg = CapabilityRegistry.get_instance()
    reg._items.clear()
    reg._validation_errors.clear()
    reg._last_refresh = 0.0

    reset_capability_resolver()
    reset_capability_bus()


def _make_item(name: str, source: str = "node", description: str = "A test item") -> Any:
    from core.agent.capability_registry import CapabilityItem
    return CapabilityItem(
        name=name,
        description=description,
        source=source,
        source_id="test_src",
        parameters={},
        available=True,
    )


def _resolver_names() -> list:
    """Return canonical names visible through CapabilityResolver."""
    from core.unified.capability_resolver import get_capability_resolver
    resolver = get_capability_resolver()
    resolver.invalidate_cache()
    return [c.name for c in resolver.resolve_all()]


# ---------------------------------------------------------------------------
# 1. Governance sentinels are present
# ---------------------------------------------------------------------------

class TestGovernanceSentinels:
    """Verify that sentinel constants are present in the expected modules."""

    def test_capability_registry_sentinel(self):
        from core.agent.capability_registry import CAPABILITY_REGISTRY_IS_CANONICAL_TRUTH_SOURCE
        assert CAPABILITY_REGISTRY_IS_CANONICAL_TRUTH_SOURCE is True

    def test_capability_bus_sentinel(self):
        from core.capability_bus import CAPABILITY_BUS_CANONICAL_BRIDGE_ACTIVE
        assert CAPABILITY_BUS_CANONICAL_BRIDGE_ACTIVE is True

    def test_capability_manager_sentinel(self):
        from core.capability_manager import CAPABILITY_MANAGER_CANONICAL_BRIDGE_ACTIVE
        assert CAPABILITY_MANAGER_CANONICAL_BRIDGE_ACTIVE is True


# ---------------------------------------------------------------------------
# 2. CapabilityBus.register() → CapabilityRegistry → CapabilityResolver
# ---------------------------------------------------------------------------

class TestCapabilityBusCanonicalBridge:
    """CapabilityBus entries must reach CapabilityResolver via the bridge."""

    def setup_method(self):
        _reset_all()

    def test_bus_register_node_visible_in_registry(self):
        from core.capability_bus import (
            get_capability_bus, CapabilityBusEntry, CapabilityBusRole,
            CapabilityHealthStatus,
        )
        from core.agent.capability_registry import CapabilityRegistry
        bus = get_capability_bus()
        bus.register(CapabilityBusEntry(
            name="node__99__execute",
            display_name="Test Node 99",
            description="Test node capability",
            role=CapabilityBusRole.NODE,
            source_id="99",
            health=CapabilityHealthStatus.HEALTHY,
        ))
        reg = CapabilityRegistry.get_instance()
        assert "node__99__execute" in reg._items

    def test_bus_register_node_visible_via_resolver(self):
        from core.capability_bus import (
            get_capability_bus, CapabilityBusEntry, CapabilityBusRole,
            CapabilityHealthStatus,
        )
        bus = get_capability_bus()
        bus.register(CapabilityBusEntry(
            name="node__100__execute",
            display_name="Test Node 100",
            description="Test node capability for resolver",
            role=CapabilityBusRole.NODE,
            source_id="100",
            health=CapabilityHealthStatus.HEALTHY,
        ))
        assert "node__100__execute" in _resolver_names()

    def test_bus_register_skill_visible_via_resolver(self):
        from core.capability_bus import (
            get_capability_bus, CapabilityBusEntry, CapabilityBusRole,
            CapabilityHealthStatus,
        )
        bus = get_capability_bus()
        bus.register_skill(
            skill_id="test_skill_01",
            description="A test skill for convergence",
        )
        assert "skill__test_skill_01" in _resolver_names()

    def test_bus_register_mcp_visible_via_resolver(self):
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()
        bus.register_mcp_tool(
            server_id="srv_test",
            tool_name="list_files",
            description="List files in a directory",
        )
        assert "mcp__srv_test__list_files" in _resolver_names()

    def test_bus_register_device_visible_via_resolver(self):
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()
        bus.register_device_capability(
            device_id="phone_01",
            action="take_screenshot",
            description="Capture current screen on phone_01",
        )
        assert "device__phone_01__take_screenshot" in _resolver_names()

    def test_bus_register_unavailable_health_available_false(self):
        """UNAVAILABLE health entries should be available=False in registry."""
        from core.capability_bus import (
            get_capability_bus, CapabilityBusEntry, CapabilityBusRole,
            CapabilityHealthStatus,
        )
        from core.agent.capability_registry import CapabilityRegistry
        bus = get_capability_bus()
        bus.register(CapabilityBusEntry(
            name="node__dead__execute",
            display_name="Dead Node",
            description="An unavailable node",
            role=CapabilityBusRole.NODE,
            source_id="dead",
            health=CapabilityHealthStatus.UNAVAILABLE,
        ))
        # The item should still be in the registry (for diagnostics), but
        # marked as not available.
        reg = CapabilityRegistry.get_instance()
        item = reg._items.get("node__dead__execute")
        assert item is not None
        assert item.available is False

    def test_bus_register_helper_methods_all_bridge(self):
        """Verify all bus registration helpers bridge to CapabilityRegistry."""
        from core.capability_bus import get_capability_bus
        from core.agent.capability_registry import CapabilityRegistry

        bus = get_capability_bus()
        bus.register_academic_capability(
            action="search_papers",
            description="Search academic papers",
        )
        reg = CapabilityRegistry.get_instance()
        assert "academic__search_papers" in reg._items


# ---------------------------------------------------------------------------
# 3. CapabilityManager.register_capability() → CapabilityRegistry → Resolver
# ---------------------------------------------------------------------------

class TestCapabilityManagerCanonicalBridge:
    """CapabilityManager entries must reach CapabilityResolver via the bridge."""

    def setup_method(self):
        _reset_all()
        # Reset CapabilityManager singleton
        from core.capability_manager import CapabilityManager
        CapabilityManager._instance = None

    def test_manager_register_visible_in_registry(self):
        from core.capability_manager import CapabilityManager
        from core.agent.capability_registry import CapabilityRegistry
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="auto_node_cap",
            description="Capability from capability manager",
            node_id="node_42",
            node_name="AutoNode42",
            category="auto_generated",
        ))
        reg = CapabilityRegistry.get_instance()
        assert "auto_node_cap" in reg._items

    def test_manager_register_visible_via_resolver(self):
        from core.capability_manager import CapabilityManager
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="resolver_visible_cap",
            description="Capability that should appear in resolver",
            node_id="node_55",
            node_name="Node55",
        ))
        assert "resolver_visible_cap" in _resolver_names()

    def test_manager_register_metadata_preserved(self):
        """Bridged entry should carry node metadata in CapabilityRegistry."""
        from core.capability_manager import CapabilityManager
        from core.agent.capability_registry import CapabilityRegistry
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="meta_cap",
            description="Capability with metadata check",
            node_id="node_meta",
            node_name="MetaNode",
            category="testing",
        ))
        item = CapabilityRegistry.get_instance()._items.get("meta_cap")
        assert item is not None
        assert item.metadata.get("node_name") == "MetaNode"
        assert item.metadata.get("category") == "testing"
        assert item.metadata.get("via_capability_manager") is True

    def test_manager_register_empty_description_uses_fallback(self):
        """Bridge should not fail on empty description; fallback is used."""
        from core.capability_manager import CapabilityManager
        from core.agent.capability_registry import CapabilityRegistry
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="nodesc_cap",
            description="",
            node_id="node_x",
            node_name="NodeX",
        ))
        # The description was empty; the bridge uses a fallback.
        item = CapabilityRegistry.get_instance()._items.get("nodesc_cap")
        assert item is not None
        assert item.description  # must not be empty

    def test_manager_bridge_does_not_break_existing_store(self):
        """Bridge must not interfere with CapabilityManager's own store."""
        from core.capability_manager import CapabilityManager
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="local_only_cap",
            description="Stored locally in CapabilityManager",
            node_id="node_local",
            node_name="LocalNode",
        ))
        assert "local_only_cap" in mgr.capabilities


# ---------------------------------------------------------------------------
# 4. Regression: direct CapabilityRegistry writes remain visible
# ---------------------------------------------------------------------------

class TestDirectRegistryWritesStillWork:
    """Direct writes to CapabilityRegistry must still reach the resolver."""

    def setup_method(self):
        _reset_all()

    def test_inject_item_visible_via_resolver(self):
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem
        reg = CapabilityRegistry.get_instance()
        reg.inject_item(CapabilityItem(
            name="node__direct__run",
            description="Direct inject node capability",
            source="node",
            source_id="direct_node",
            parameters={},
            available=True,
        ))
        assert "node__direct__run" in _resolver_names()

    def test_inject_mcp_tool_visible_via_resolver(self):
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        reg.inject_mcp_tool(
            server_id="mcp_srv",
            tool_name="get_content",
            description="Fetch content from MCP server",
            parameters={},
        )
        assert "mcp__mcp_srv__get_content" in _resolver_names()

    def test_inject_skill_visible_via_resolver(self):
        from core.agent.capability_registry import CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        reg.inject_skill(
            skill_id="my_skill",
            skill_name="My Skill",
            description="A skill injected directly",
            parameters={},
        )
        assert "skill__my_skill" in _resolver_names()


# ---------------------------------------------------------------------------
# 5. NodeFabricRegistry.sync_capabilities_to_registry() → resolver
# ---------------------------------------------------------------------------

class TestNodeFabricRegistrySync:
    """NodeFabricRegistry capability sync must remain visible via resolver."""

    def setup_method(self):
        _reset_all()

    def test_sync_capability_node_visible_via_resolver(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeRole, NodeStatus,
            NodeCapability, NodeArchitecturalClass,
        )
        fabric = NodeFabricRegistry()
        fabric._nodes.clear()

        node = NodeInfo(
            node_id="test_fabric_node",
            role=NodeRole.WORKER,
            architectural_class=NodeArchitecturalClass.CAPABILITY_NODE,
            status=NodeStatus.HEALTHY,
            capabilities=[
                NodeCapability(
                    name="compute",
                    description="Compute capability for testing",
                )
            ],
        )
        # Force heartbeat fresh
        import time
        node.last_heartbeat = time.monotonic()
        fabric.register(node)
        fabric.sync_capabilities_to_registry()

        assert "node__test_fabric_node__compute" in _resolver_names()

    def test_non_capability_node_not_synced(self):
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry, NodeInfo, NodeRole, NodeStatus,
            NodeCapability, NodeArchitecturalClass,
        )
        import time
        fabric = NodeFabricRegistry()
        fabric._nodes.clear()

        node = NodeInfo(
            node_id="service_node_x",
            role=NodeRole.WORKER,
            architectural_class=NodeArchitecturalClass.SERVICE_NODE,
            status=NodeStatus.HEALTHY,
            capabilities=[
                NodeCapability(name="internal_service", description="Internal service cap"),
            ],
        )
        node.last_heartbeat = time.monotonic()
        fabric.register(node)
        fabric.sync_capabilities_to_registry()

        names = _resolver_names()
        assert "node__service_node_x__internal_service" not in names


# ---------------------------------------------------------------------------
# 6. CapabilityBus is NOT a parallel truth sink — it must bridge to registry
# ---------------------------------------------------------------------------

class TestCapabilityBusIsNotIsolatedSink:
    """CapabilityBus must not hold capabilities that are invisible to the
    resolver (i.e., it must not be an isolated truth sink)."""

    def setup_method(self):
        _reset_all()

    def test_bus_entry_reaches_resolver_not_just_bus(self):
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()
        bus.register_skill("bridge_skill", description="Should reach resolver")

        # Entry visible in bus
        assert bus.lookup("skill__bridge_skill") is not None
        # Entry ALSO visible in resolver (not just bus)
        assert "skill__bridge_skill" in _resolver_names()

    def test_multiple_bus_entries_all_reach_resolver(self):
        from core.capability_bus import get_capability_bus
        bus = get_capability_bus()
        bus.register_skill("s1", description="Skill one")
        bus.register_skill("s2", description="Skill two")
        bus.register_mcp_tool("srv", "tool_a", description="MCP tool A")

        names = _resolver_names()
        assert "skill__s1" in names
        assert "skill__s2" in names
        assert "mcp__srv__tool_a" in names


# ---------------------------------------------------------------------------
# 7. CapabilityManager is NOT a parallel truth sink
# ---------------------------------------------------------------------------

class TestCapabilityManagerIsNotIsolatedSink:
    """CapabilityManager must not hold capabilities invisible to the resolver."""

    def setup_method(self):
        _reset_all()
        from core.capability_manager import CapabilityManager
        CapabilityManager._instance = None

    def test_manager_entry_reaches_resolver(self):
        from core.capability_manager import CapabilityManager
        mgr = CapabilityManager()
        asyncio.run(mgr.register_capability(
            name="sink_test_cap",
            description="Capability that must not be a sink",
            node_id="node_sink",
            node_name="SinkNode",
        ))
        # Must be visible through resolver, not just manager
        assert "sink_test_cap" in mgr.capabilities
        assert "sink_test_cap" in _resolver_names()
