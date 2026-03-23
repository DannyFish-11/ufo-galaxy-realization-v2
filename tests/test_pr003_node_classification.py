"""
tests/test_pr003_node_classification.py
=========================================
PR-003: Classify node system for OpenClawd capability architecture.

Covers:
  1. NodeArchitecturalClass enum — all values exist and are serialisable.
  2. NodeInfo carries architectural_class; defaults to CAPABILITY_NODE.
  3. NodeInfo.to_dict() includes 'architectural_class'.
  4. NodeFabricRegistry.list_by_architectural_class() filters correctly.
  5. sync_capabilities_to_registry() only syncs CAPABILITY_NODE nodes.
  6. sync_capabilities_to_registry() skips SERVICE_NODE nodes.
  7. sync_capabilities_to_registry() skips LEGACY_ORCHESTRATOR_NODE nodes.
  8. sync_capabilities_to_registry() skips EXPERIMENTAL_NODE nodes.
  9. sync_capabilities_to_registry() skips ARCHIVED_NODE nodes.
 10. Capability metadata includes 'node_architectural_class'.
 11. get_metrics() includes 'by_architectural_class' breakdown.
 12. Legacy orchestrator nodes are registered in LEGACY_PATH_REGISTRY (PR-003 entries).
 13. LEGACY_ORCHESTRATOR_NODE_PREFIXES covers the known legacy nodes.
 14. classify_path_status() returns non-ACTIVE for known legacy paths.
 15. NodeArchitecturalClass values round-trip through string serialisation.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset() -> None:
    from core.nodes.node_fabric_registry import reset_node_fabric_registry
    reset_node_fabric_registry()
    try:
        from core.agent.capability_registry import CapabilityRegistry
        CapabilityRegistry._instance = None
    except ImportError:
        pass


def _make_node(
    node_id: str,
    architectural_class=None,
    capabilities: List[str] | None = None,
    healthy: bool = True,
):
    from core.nodes.node_fabric_registry import (
        NodeInfo,
        NodeRole,
        NodeStatus,
        NodeCapability,
        NodeArchitecturalClass,
    )
    caps = [NodeCapability(name=c, description=c) for c in (capabilities or [])]
    ac = architectural_class if architectural_class is not None else NodeArchitecturalClass.CAPABILITY_NODE
    node = NodeInfo(
        node_id=node_id,
        role=NodeRole.WORKER,
        architectural_class=ac,
        capabilities=caps,
        status=NodeStatus.HEALTHY,
    )
    if not healthy:
        # Make heartbeat stale so health_score returns 0
        node.last_heartbeat = time.monotonic() - 999.0
    return node


# ===========================================================================
# 1. NodeArchitecturalClass enum
# ===========================================================================


class TestNodeArchitecturalClassEnum:
    def test_all_expected_values_exist(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert NodeArchitecturalClass.CAPABILITY_NODE.value == "capability_node"
        assert NodeArchitecturalClass.SERVICE_NODE.value == "service_node"
        assert NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE.value == "legacy_orchestrator_node"
        assert NodeArchitecturalClass.EXPERIMENTAL_NODE.value == "experimental_node"
        assert NodeArchitecturalClass.ARCHIVED_NODE.value == "archived_node"

    def test_enum_is_string_subclass(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert isinstance(NodeArchitecturalClass.CAPABILITY_NODE, str)
        assert NodeArchitecturalClass.CAPABILITY_NODE == "capability_node"

    def test_roundtrip_from_value(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        for member in NodeArchitecturalClass:
            assert NodeArchitecturalClass(member.value) is member

    def test_five_members(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        assert len(list(NodeArchitecturalClass)) == 5


# ===========================================================================
# 2. NodeInfo default and explicit architectural_class
# ===========================================================================


class TestNodeInfoArchitecturalClass:
    def test_default_is_capability_node(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(node_id="test-default")
        assert node.architectural_class == NodeArchitecturalClass.CAPABILITY_NODE

    def test_explicit_service_node(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(
            node_id="test-service",
            architectural_class=NodeArchitecturalClass.SERVICE_NODE,
        )
        assert node.architectural_class == NodeArchitecturalClass.SERVICE_NODE

    def test_explicit_legacy_orchestrator_node(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(
            node_id="test-legacy",
            architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE,
        )
        assert node.architectural_class == NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE


# ===========================================================================
# 3. NodeInfo.to_dict() includes architectural_class
# ===========================================================================


class TestNodeInfoToDict:
    def test_to_dict_has_architectural_class(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(node_id="td-1", architectural_class=NodeArchitecturalClass.SERVICE_NODE)
        d = node.to_dict()
        assert "architectural_class" in d
        assert d["architectural_class"] == "service_node"

    def test_to_dict_capability_node(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(node_id="td-2", architectural_class=NodeArchitecturalClass.CAPABILITY_NODE)
        d = node.to_dict()
        assert d["architectural_class"] == "capability_node"

    def test_to_dict_legacy_orchestrator(self) -> None:
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(node_id="td-3", architectural_class=NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE)
        d = node.to_dict()
        assert d["architectural_class"] == "legacy_orchestrator_node"

    def test_to_dict_serialisable_to_string(self) -> None:
        """All to_dict values must be JSON-serialisable strings/primitives."""
        import json
        from core.nodes.node_fabric_registry import NodeInfo, NodeArchitecturalClass
        node = NodeInfo(node_id="td-4", architectural_class=NodeArchitecturalClass.EXPERIMENTAL_NODE)
        d = node.to_dict()
        # Should not raise
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        assert parsed["architectural_class"] == "experimental_node"


# ===========================================================================
# 4. list_by_architectural_class()
# ===========================================================================


class TestListByArchitecturalClass:
    def setup_method(self) -> None:
        _reset()

    def test_filter_capability_nodes(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeArchitecturalClass,
        )
        reg = get_node_fabric_registry()
        reg.register(_make_node("cap-1", NodeArchitecturalClass.CAPABILITY_NODE))
        reg.register(_make_node("svc-1", NodeArchitecturalClass.SERVICE_NODE))
        reg.register(_make_node("leg-1", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE))

        caps = reg.list_by_architectural_class(NodeArchitecturalClass.CAPABILITY_NODE)
        assert len(caps) == 1
        assert caps[0].node_id == "cap-1"

    def test_filter_service_nodes(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeArchitecturalClass,
        )
        reg = get_node_fabric_registry()
        reg.register(_make_node("cap-2", NodeArchitecturalClass.CAPABILITY_NODE))
        reg.register(_make_node("svc-2", NodeArchitecturalClass.SERVICE_NODE))

        svcs = reg.list_by_architectural_class(NodeArchitecturalClass.SERVICE_NODE)
        assert len(svcs) == 1
        assert svcs[0].node_id == "svc-2"

    def test_filter_legacy_orchestrator_nodes(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeArchitecturalClass,
        )
        reg = get_node_fabric_registry()
        reg.register(_make_node("leg-2", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE))
        reg.register(_make_node("leg-3", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE))
        reg.register(_make_node("cap-3", NodeArchitecturalClass.CAPABILITY_NODE))

        legacy = reg.list_by_architectural_class(NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE)
        assert len(legacy) == 2
        assert {n.node_id for n in legacy} == {"leg-2", "leg-3"}

    def test_empty_result_when_none_match(self) -> None:
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeArchitecturalClass,
        )
        reg = get_node_fabric_registry()
        reg.register(_make_node("cap-4", NodeArchitecturalClass.CAPABILITY_NODE))

        archived = reg.list_by_architectural_class(NodeArchitecturalClass.ARCHIVED_NODE)
        assert archived == []


# ===========================================================================
# 5–9. sync_capabilities_to_registry() filtering by architectural_class
# ===========================================================================


class TestCapabilitySyncFilter:
    """Tests that only CAPABILITY_NODE nodes are injected into CapabilityRegistry."""

    def setup_method(self) -> None:
        _reset()

    def _run_sync_with_mock_registry(self, nodes):
        """Register nodes, patch CapabilityRegistry, run sync, return injected items."""
        from core.nodes.node_fabric_registry import get_node_fabric_registry

        reg = get_node_fabric_registry()
        for node in nodes:
            reg.register(node)

        injected_items: List[Any] = []

        mock_cap_item_cls = MagicMock(side_effect=lambda **kw: kw)
        mock_registry_instance = MagicMock()
        mock_registry_instance.inject_item.side_effect = lambda item: injected_items.append(item)
        mock_cap_registry_cls = MagicMock()
        mock_cap_registry_cls.get_instance.return_value = mock_registry_instance

        with patch.dict(
            "sys.modules",
            {
                "core.agent.capability_registry": MagicMock(
                    CapabilityRegistry=mock_cap_registry_cls,
                    CapabilityItem=mock_cap_item_cls,
                )
            },
        ):
            count = reg.sync_capabilities_to_registry()

        return count, injected_items

    def test_capability_node_is_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [_make_node("cn-1", NodeArchitecturalClass.CAPABILITY_NODE, ["run", "query"])]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 2
        assert len(items) == 2

    def test_service_node_is_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [_make_node("svc-s", NodeArchitecturalClass.SERVICE_NODE, ["ocr", "embed"])]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 0
        assert items == []

    def test_legacy_orchestrator_node_is_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [_make_node("leg-s", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE, ["orchestrate"])]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 0
        assert items == []

    def test_experimental_node_is_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [_make_node("exp-s", NodeArchitecturalClass.EXPERIMENTAL_NODE, ["alpha"])]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 0
        assert items == []

    def test_archived_node_is_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [_make_node("arc-s", NodeArchitecturalClass.ARCHIVED_NODE, ["old"])]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 0
        assert items == []

    def test_mixed_nodes_only_capability_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [
            _make_node("cap-mix", NodeArchitecturalClass.CAPABILITY_NODE, ["action1"]),
            _make_node("svc-mix", NodeArchitecturalClass.SERVICE_NODE, ["backend_op"]),
            _make_node("leg-mix", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE, ["old_flow"]),
        ]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 1
        # Verify the injected item belongs to the capability node
        item = items[0]
        assert "cap-mix" in item["name"]

    def test_unhealthy_capability_node_not_synced(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass

        nodes = [
            _make_node("cap-dead", NodeArchitecturalClass.CAPABILITY_NODE, ["act"], healthy=False)
        ]
        count, items = self._run_sync_with_mock_registry(nodes)
        assert count == 0


# ===========================================================================
# 10. Capability metadata includes node_architectural_class
# ===========================================================================


class TestCapabilityMetadata:
    def setup_method(self) -> None:
        _reset()

    def test_injected_item_metadata_has_architectural_class(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeArchitecturalClass

        reg = get_node_fabric_registry()
        reg.register(_make_node("meta-cap", NodeArchitecturalClass.CAPABILITY_NODE, ["my_action"]))

        captured: List[Dict[str, Any]] = []

        mock_cap_item_cls = MagicMock(side_effect=lambda **kw: kw)
        mock_registry_instance = MagicMock()
        mock_registry_instance.inject_item.side_effect = lambda item: captured.append(item)
        mock_cap_registry_cls = MagicMock()
        mock_cap_registry_cls.get_instance.return_value = mock_registry_instance

        with patch.dict(
            "sys.modules",
            {
                "core.agent.capability_registry": MagicMock(
                    CapabilityRegistry=mock_cap_registry_cls,
                    CapabilityItem=mock_cap_item_cls,
                )
            },
        ):
            reg.sync_capabilities_to_registry()

        assert len(captured) == 1
        item = captured[0]
        assert "metadata" in item
        assert item["metadata"]["node_architectural_class"] == "capability_node"


# ===========================================================================
# 11. get_metrics() includes by_architectural_class
# ===========================================================================


class TestGetMetrics:
    def setup_method(self) -> None:
        _reset()

    def test_metrics_has_by_architectural_class(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry

        reg = get_node_fabric_registry()
        metrics = reg.get_metrics()
        assert "by_architectural_class" in metrics

    def test_metrics_by_architectural_class_counts(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry, NodeArchitecturalClass

        reg = get_node_fabric_registry()
        reg.register(_make_node("m-cap-1", NodeArchitecturalClass.CAPABILITY_NODE))
        reg.register(_make_node("m-cap-2", NodeArchitecturalClass.CAPABILITY_NODE))
        reg.register(_make_node("m-svc-1", NodeArchitecturalClass.SERVICE_NODE))
        reg.register(_make_node("m-leg-1", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE))

        metrics = reg.get_metrics()
        by_ac = metrics["by_architectural_class"]
        assert by_ac.get("capability_node", 0) == 2
        assert by_ac.get("service_node", 0) == 1
        assert by_ac.get("legacy_orchestrator_node", 0) == 1

    def test_metrics_by_architectural_class_empty(self) -> None:
        from core.nodes.node_fabric_registry import get_node_fabric_registry

        reg = get_node_fabric_registry()
        metrics = reg.get_metrics()
        assert metrics["by_architectural_class"] == {}


# ===========================================================================
# 12. Legacy orchestrator paths in LEGACY_PATH_REGISTRY (PR-003 entries)
# ===========================================================================


class TestLegacyOrchestratorPathRegistry:
    def test_node_110_pr003_entry_exists(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "nodes.Node_110_SmartOrchestrator" in LEGACY_PATH_REGISTRY

    def test_node_81_pr003_entry_exists(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "nodes.Node_81_Orchestrator" in LEGACY_PATH_REGISTRY

    def test_node_50_pr003_entry_exists(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        assert "nodes.Node_50_Transformer" in LEGACY_PATH_REGISTRY

    def test_pr003_entries_mention_legacy_orchestrator_node(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        for path in [
            "nodes.Node_110_SmartOrchestrator",
            "nodes.Node_81_Orchestrator",
            "nodes.Node_50_Transformer",
        ]:
            entry = LEGACY_PATH_REGISTRY[path]
            combined = (entry.notes or "") + (entry.recommendation or "")
            assert "LEGACY_ORCHESTRATOR_NODE" in combined, (
                f"Entry for {path} should reference LEGACY_ORCHESTRATOR_NODE; got: {combined}"
            )

    def test_pr003_entries_reference_openclawd(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        for path in [
            "nodes.Node_110_SmartOrchestrator",
            "nodes.Node_81_Orchestrator",
        ]:
            entry = LEGACY_PATH_REGISTRY[path]
            combined = (entry.recommendation or "") + (entry.notes or "")
            assert "openclawd" in combined.lower() or "OpenClawd" in combined, (
                f"Entry for {path} should reference OpenClawd; got: {combined}"
            )


# ===========================================================================
# 13. LEGACY_ORCHESTRATOR_NODE_PREFIXES
# ===========================================================================


class TestLegacyOrchestratorNodePrefixes:
    def test_prefixes_exist(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES
        assert LEGACY_ORCHESTRATOR_NODE_PREFIXES is not None
        assert len(LEGACY_ORCHESTRATOR_NODE_PREFIXES) >= 3

    def test_node_110_in_prefixes(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES
        assert "nodes.Node_110_SmartOrchestrator" in LEGACY_ORCHESTRATOR_NODE_PREFIXES

    def test_node_81_in_prefixes(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES
        assert "nodes.Node_81_Orchestrator" in LEGACY_ORCHESTRATOR_NODE_PREFIXES

    def test_node_50_in_prefixes(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES
        assert "nodes.Node_50_Transformer" in LEGACY_ORCHESTRATOR_NODE_PREFIXES

    def test_prefixes_is_frozenset(self) -> None:
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_NODE_PREFIXES
        assert isinstance(LEGACY_ORCHESTRATOR_NODE_PREFIXES, frozenset)


# ===========================================================================
# 14. classify_path_status() for known legacy paths
# ===========================================================================


class TestClassifyPathStatus:
    def test_node_110_server_is_not_active(self) -> None:
        from core.orchestration_authority.legacy_paths import (
            classify_path_status,
            LegacyPathStatus,
        )
        status = classify_path_status("nodes.Node_110_SmartOrchestrator.server")
        assert status != LegacyPathStatus.ACTIVE

    def test_node_81_is_not_active(self) -> None:
        from core.orchestration_authority.legacy_paths import (
            classify_path_status,
            LegacyPathStatus,
        )
        status = classify_path_status("nodes.Node_81_Orchestrator.main")
        assert status != LegacyPathStatus.ACTIVE

    def test_node_50_is_deprecated(self) -> None:
        from core.orchestration_authority.legacy_paths import (
            classify_path_status,
            LegacyPathStatus,
        )
        status = classify_path_status("nodes.Node_50_Transformer.task_orchestrator")
        assert status == LegacyPathStatus.DEPRECATED

    def test_unknown_path_is_active(self) -> None:
        from core.orchestration_authority.legacy_paths import (
            classify_path_status,
            LegacyPathStatus,
        )
        status = classify_path_status("nodes.SomeFutureNode.new_action")
        assert status == LegacyPathStatus.ACTIVE


# ===========================================================================
# 15. NodeArchitecturalClass string serialisation round-trip
# ===========================================================================


class TestArchitecturalClassSerialisation:
    def test_all_values_round_trip_via_str(self) -> None:
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        for member in NodeArchitecturalClass:
            # NodeArchitecturalClass is a str Enum; round-trip via .value
            assert NodeArchitecturalClass(member.value) is member

    def test_all_values_json_serialisable(self) -> None:
        import json
        from core.nodes.node_fabric_registry import NodeArchitecturalClass, NodeInfo
        for member in NodeArchitecturalClass:
            node = NodeInfo(node_id=f"serial-{member.value}", architectural_class=member)
            d = node.to_dict()
            # Must not raise
            dumped = json.dumps(d)
            parsed = json.loads(dumped)
            assert parsed["architectural_class"] == member.value
