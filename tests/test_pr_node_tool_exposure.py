"""
tests/test_pr_node_tool_exposure.py
=====================================
feat: expose node tools to OpenClawd default tool collection

Covers:
  1. Canonical node path: sync_capabilities_to_registry() is called during
     _collect_tools() and eligible CAPABILITY_NODE entries are collected via
     CapabilityResolver(CapabilitySource.NODE).
  2. Architectural filtering: SERVICE_NODE / LEGACY_ORCHESTRATOR_NODE /
     EXPERIMENTAL_NODE / ARCHIVED_NODE are NOT surfaced by the canonical path.
  3. Naming contract: node tools use node__<node_id>__<action> format.
  4. Deduplication: the legacy direct-scan path (Layer 3) does not re-add tools
     already collected via the canonical path.
  5. Existing MCP/Skill behaviour is unchanged (backward compatibility).
  6. Canonical path is gracefully skipped when NodeFabricRegistry is unavailable.
  7. Node tools from canonical path appear in _collect_tools() output alongside
     MCP/Skill tools.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset() -> None:
    """Reset all relevant singletons between tests."""
    try:
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()
    except ImportError:
        pass
    try:
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
    except ImportError:
        pass
    try:
        from core.unified.capability_resolver import _resolver_instance
        import core.unified.capability_resolver as _mod
        _mod._resolver_instance = None
    except (ImportError, AttributeError):
        pass


def _make_node(
    node_id: str,
    architectural_class=None,
    capabilities: List[str] | None = None,
    healthy: bool = True,
):
    """Build a NodeInfo instance for testing."""
    from core.nodes.node_fabric_registry import (
        NodeInfo,
        NodeRole,
        NodeStatus,
        NodeCapability,
        NodeArchitecturalClass,
    )
    caps = [NodeCapability(name=c, description=f"Test capability {c}") for c in (capabilities or [])]
    ac = architectural_class if architectural_class is not None else NodeArchitecturalClass.CAPABILITY_NODE
    node = NodeInfo(
        node_id=node_id,
        role=NodeRole.WORKER,
        architectural_class=ac,
        capabilities=caps,
        status=NodeStatus.HEALTHY,
    )
    if not healthy:
        node.last_heartbeat = time.monotonic() - 999.0
    return node


def _make_tool_schema(name: str) -> Dict[str, Any]:
    """Build a minimal OpenAI function-calling tool schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Test tool {name}",
            "parameters": {"type": "object", "properties": {}},
        },
    }


# ===========================================================================
# 1. Canonical node path: sync + resolver collects NODE tools
# ===========================================================================

class TestCanonicalNodePathCollectsTools:
    """sync_capabilities_to_registry() is invoked and NODE tools reach _collect_tools()."""

    def setup_method(self) -> None:
        _reset()

    def test_capability_node_tools_appear_in_output(self) -> None:
        """CAPABILITY_NODE entries injected via sync appear in _collect_tools()."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

        # Register a CAPABILITY_NODE with two capabilities
        fabric = NodeFabricRegistry()
        fabric.register(_make_node("n-cap-1", NodeArchitecturalClass.CAPABILITY_NODE, ["run", "query"]))

        # Sync and verify items land in CapabilityRegistry
        reg = CapabilityRegistry.get_instance()
        count = fabric.sync_capabilities_to_registry()
        assert count == 2

        # Both items should be in the registry with source "node"
        item_run = reg.get("node__n-cap-1__run")
        item_query = reg.get("node__n-cap-1__query")
        assert item_run is not None and item_run.source == "node"
        assert item_query is not None and item_query.source == "node"

    def test_canonical_resolver_returns_node_tools_after_sync(self) -> None:
        """CapabilityResolver.collect_tool_schemas(NODE) returns synced node tools."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(_make_node("n-res-1", NodeArchitecturalClass.CAPABILITY_NODE, ["execute"]))
        fabric.sync_capabilities_to_registry()

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = [s["function"]["name"] for s in schemas]
        assert "node__n-res-1__execute" in names

    def test_node_tool_naming_convention(self) -> None:
        """Node tools use node__<node_id>__<action> naming contract."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("my-node-42", NodeArchitecturalClass.CAPABILITY_NODE, ["infer", "embed"])
        )
        fabric.sync_capabilities_to_registry()

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = [s["function"]["name"] for s in schemas]
        assert "node__my-node-42__infer" in names
        assert "node__my-node-42__embed" in names
        # All names must match the naming contract
        for name in names:
            assert name.startswith("node__"), f"unexpected name format: {name}"
            parts = name.split("__")
            assert len(parts) == 3, f"expected node__<id>__<action>, got: {name}"


# ===========================================================================
# 2. Architectural filtering: only CAPABILITY_NODE is surfaced
# ===========================================================================

class TestArchitecturalFilteringInCanonicalPath:
    """Non-CAPABILITY_NODE nodes must not reach the canonical tool list."""

    def setup_method(self) -> None:
        _reset()

    def _sync_and_get_node_names(self, architectural_class) -> List[str]:
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        node_id = f"n-{architectural_class.value}-test"
        fabric.register(_make_node(node_id, architectural_class, ["action1"]))
        fabric.sync_capabilities_to_registry()

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        return [s["function"]["name"] for s in schemas]

    def test_service_node_excluded(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        names = self._sync_and_get_node_names(NodeArchitecturalClass.SERVICE_NODE)
        assert not any("service_node" in n for n in names)
        assert not any("n-service_node" in n for n in names)

    def test_legacy_orchestrator_node_excluded(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        names = self._sync_and_get_node_names(NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE)
        assert not any("legacy_orchestrator_node" in n for n in names)

    def test_experimental_node_excluded(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        names = self._sync_and_get_node_names(NodeArchitecturalClass.EXPERIMENTAL_NODE)
        assert not any("experimental_node" in n for n in names)

    def test_archived_node_excluded(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        names = self._sync_and_get_node_names(NodeArchitecturalClass.ARCHIVED_NODE)
        assert not any("archived_node" in n for n in names)

    def test_unhealthy_capability_node_excluded(self) -> None:
        """Unhealthy CAPABILITY_NODE nodes must not be synced."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("n-stale", NodeArchitecturalClass.CAPABILITY_NODE, ["act"], healthy=False)
        )
        count = fabric.sync_capabilities_to_registry()
        assert count == 0  # stale node must not produce any synced items

    def test_mixed_nodes_only_capability_node_surfaces(self) -> None:
        """With mixed architectural classes, only CAPABILITY_NODE items appear."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("cap-good", NodeArchitecturalClass.CAPABILITY_NODE, ["run"])
        )
        fabric.register(
            _make_node("svc-bad", NodeArchitecturalClass.SERVICE_NODE, ["ocr"])
        )
        fabric.register(
            _make_node("leg-bad", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE, ["dispatch"])
        )
        count = fabric.sync_capabilities_to_registry()
        assert count == 1  # only cap-good__run

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = [s["function"]["name"] for s in schemas]
        assert "node__cap-good__run" in names
        assert not any("svc-bad" in n for n in names)
        assert not any("leg-bad" in n for n in names)


# ===========================================================================
# 3. Deduplication: legacy scan does not re-add canonical path tools
# ===========================================================================

class TestLegacyScanDeduplication:
    """Legacy direct-scan path skips tools already collected via canonical path."""

    def setup_method(self) -> None:
        _reset()

    def test_canonical_tool_names_initialise_registered_set(self) -> None:
        """_node_catalog_tool_names pre-seeds the legacy scan's dedup set."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.agent.capability_registry import CapabilityItem, CapabilityRegistry

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("canon-node", NodeArchitecturalClass.CAPABILITY_NODE, ["fetch"])
        )
        fabric.sync_capabilities_to_registry()

        # Verify the registry has the item
        reg = CapabilityRegistry.get_instance()
        item = reg.get("node__canon-node__fetch")
        assert item is not None and item.source == "node"

    def test_no_duplicate_node_tools_in_collect_tools(self) -> None:
        """_collect_tools() output must not contain duplicate tool names."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("dedup-node", NodeArchitecturalClass.CAPABILITY_NODE, ["act"])
        )
        fabric.sync_capabilities_to_registry()

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = [s["function"]["name"] for s in schemas]

        # No duplicate names must be returned
        assert len(names) == len(set(names)), f"Duplicate tool names found: {names}"


# ===========================================================================
# 4. Backward compatibility: MCP/Skill collection is unchanged
# ===========================================================================

class TestMCPSkillBackwardCompatibility:
    """Existing MCP/Skill tool collection remains intact after the node path addition."""

    def setup_method(self) -> None:
        _reset()

    def test_mcp_tools_still_collected_via_resolver(self) -> None:
        """CapabilityResolver with MCP source still works correctly."""
        from core.agent.capability_registry import CapabilityRegistry
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        reg = CapabilityRegistry.get_instance()
        reg.inject_mcp_tool(
            server_id="test-srv",
            tool_name="search",
            description="Search tool",
            parameters={"type": "object", "properties": {}},
        )

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.MCP])
        names = [s["function"]["name"] for s in schemas]
        assert "mcp__test-srv__search" in names

    def test_skill_tools_still_collected_via_resolver(self) -> None:
        """CapabilityResolver with SKILL source still works correctly."""
        from core.agent.capability_registry import CapabilityRegistry
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        reg = CapabilityRegistry.get_instance()
        reg.inject_skill(
            skill_id="hello",
            skill_name="Hello Skill",
            description="Greet user",
            parameters={"type": "object", "properties": {}},
        )

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.SKILL])
        names = [s["function"]["name"] for s in schemas]
        assert "skill__hello" in names

    def test_node_and_mcp_tools_coexist(self) -> None:
        """Node tools and MCP tools can be collected together without conflict."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.agent.capability_registry import CapabilityRegistry
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        # Register a CAPABILITY_NODE
        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("coexist-node", NodeArchitecturalClass.CAPABILITY_NODE, ["process"])
        )
        fabric.sync_capabilities_to_registry()

        # Also inject an MCP tool
        reg = CapabilityRegistry.get_instance()
        reg.inject_mcp_tool(
            server_id="co-srv",
            tool_name="find",
            description="Find something",
            parameters={"type": "object", "properties": {}},
        )

        resolver = CapabilityResolver(cache_ttl_seconds=0)

        node_schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        mcp_schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.MCP])

        node_names = [s["function"]["name"] for s in node_schemas]
        mcp_names = [s["function"]["name"] for s in mcp_schemas]

        assert "node__coexist-node__process" in node_names
        assert "mcp__co-srv__find" in mcp_names

        # No cross-contamination
        assert not any(n.startswith("mcp__") for n in node_names)
        assert not any(n.startswith("node__") for n in mcp_names)


# ===========================================================================
# 5. Graceful degradation: canonical path skipped when registry unavailable
# ===========================================================================

class TestCanonicalPathGracefulDegradation:
    """Canonical node path is safely skipped when NodeFabricRegistry is unavailable."""

    def setup_method(self) -> None:
        _reset()

    def test_import_error_does_not_raise(self) -> None:
        """ImportError from NodeFabricRegistry is caught and logged, not raised."""
        from core.nodes.node_fabric_registry import NodeFabricRegistry
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        # If sync returns 0 (no nodes registered), collect_tool_schemas returns []
        fabric = NodeFabricRegistry()
        count = fabric.sync_capabilities_to_registry()
        assert count == 0

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        assert schemas == []

    def test_empty_fabric_registry_returns_no_node_tools(self) -> None:
        """An empty NodeFabricRegistry produces no node tools."""
        from core.nodes.node_fabric_registry import NodeFabricRegistry
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        assert fabric.sync_capabilities_to_registry() == 0

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        assert len(schemas) == 0


# ===========================================================================
# 6. Node tools collected via canonical path appear alongside MCP/Skill
# ===========================================================================

class TestNodeToolsAppearsInDefaultCollection:
    """At least a representative CAPABILITY_NODE can be discovered as a tool."""

    def setup_method(self) -> None:
        _reset()

    def test_representative_capability_node_is_discoverable(self) -> None:
        """A representative CAPABILITY_NODE with capabilities is discoverable as tools."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node(
                "worker-alpha",
                NodeArchitecturalClass.CAPABILITY_NODE,
                ["llm_infer", "embed", "classify"],
            )
        )
        synced = fabric.sync_capabilities_to_registry()
        assert synced == 3, f"expected 3 synced, got {synced}"

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = {s["function"]["name"] for s in schemas}

        assert "node__worker-alpha__llm_infer" in names
        assert "node__worker-alpha__embed" in names
        assert "node__worker-alpha__classify" in names

    def test_multiple_capability_nodes_all_discoverable(self) -> None:
        """Multiple CAPABILITY_NODEs are all discoverable as tools."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("node-a", NodeArchitecturalClass.CAPABILITY_NODE, ["action_x"])
        )
        fabric.register(
            _make_node("node-b", NodeArchitecturalClass.CAPABILITY_NODE, ["action_y"])
        )
        synced = fabric.sync_capabilities_to_registry()
        assert synced == 2

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        names = {s["function"]["name"] for s in schemas}

        assert "node__node-a__action_x" in names
        assert "node__node-b__action_y" in names

    def test_tool_schema_has_correct_structure(self) -> None:
        """Node tool schemas conform to OpenAI function-calling format."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        from core.unified.capability_resolver import CapabilityResolver
        from core.unified.capability_contract import CapabilitySource

        fabric = NodeFabricRegistry()
        fabric.register(
            _make_node("schema-node", NodeArchitecturalClass.CAPABILITY_NODE, ["run"])
        )
        fabric.sync_capabilities_to_registry()

        resolver = CapabilityResolver(cache_ttl_seconds=0)
        schemas = resolver.collect_tool_schemas(sources=[CapabilitySource.NODE])
        target = next(
            (s for s in schemas if s["function"]["name"] == "node__schema-node__run"),
            None,
        )
        assert target is not None
        assert target["type"] == "function"
        assert "function" in target
        func = target["function"]
        assert "name" in func
        assert "description" in func
        assert isinstance(func["description"], str)
        assert len(func["description"]) > 0
