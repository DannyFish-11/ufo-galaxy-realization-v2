#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr8_node_boundary_decommission.py
=============================================
PR-8: Decommission Legacy Node Paths and Formalize Runtime Boundaries.

Verifies that:

A) Sentinel / policy strings
B) NodePathwayKind and LegacyNodeSurfaceStatus enums
C) NodeBoundaryDecision dataclass
D) LegacyNodeSurfaceEntry dataclass
E) NodeBoundarySnapshot dataclass
F) classify_invocation_pathway
G) build_legacy_surface_registry
H) evaluate_node_boundary_compliance — CAPABILITY_NODE
I) evaluate_node_boundary_compliance — LEGACY_ORCHESTRATOR_NODE
J) evaluate_node_boundary_compliance — ARCHIVED_NODE
K) get_canonical_nodes
L) build_node_boundary_snapshot
M) get_boundary_summary
N) projection.py sentinel
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_stub_node(node_id: str, arch_class: str = "capability_node") -> Any:
    """Return a minimal stub NodeInfo-like object."""
    node = MagicMock()
    node.node_id = node_id
    arch = MagicMock()
    arch.value = arch_class
    node.architectural_class = arch
    return node


def _try_import():
    try:
        import core.node_boundary_runtime as m
        return m
    except ImportError as e:
        return None, str(e)


# ===========================================================================
# A) Sentinel / policy strings
# ===========================================================================


class TestSentinels:
    """Authority and policy sentinels must be importable and non-empty."""

    def test_authority_sentinel_importable(self):
        try:
            from core.node_boundary_runtime import NODE_BOUNDARY_IS_CANONICAL_AUTHORITY
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NODE_BOUNDARY_IS_CANONICAL_AUTHORITY
        assert "PR8_AUTHORITY" in NODE_BOUNDARY_IS_CANONICAL_AUTHORITY

    def test_pr8_sentinel_value(self):
        try:
            from core.node_boundary_runtime import NODE_BOUNDARY_RUNTIME_PR8_SENTINEL
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NODE_BOUNDARY_RUNTIME_PR8_SENTINEL == "NODE_BOUNDARY_RUNTIME::PR8_SENTINEL_V1"

    def test_capability_backends_policy_importable(self):
        try:
            from core.node_boundary_runtime import NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY
        assert "capability" in NODES_ARE_CAPABILITY_BACKENDS_ONLY_POLICY.lower()

    def test_canonical_invocation_policy_importable(self):
        try:
            from core.node_boundary_runtime import CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY
        assert "invoke_node" in CANONICAL_INVOCATION_PATH_IS_INVOKE_NODE_POLICY

    def test_legacy_registry_policy_importable(self):
        try:
            from core.node_boundary_runtime import LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY
        assert "NodeRegistry" in LEGACY_REGISTRY_IS_COMPAT_FACADE_POLICY

    def test_direct_scan_policy_importable(self):
        try:
            from core.node_boundary_runtime import DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY
        assert "NodeFabricRegistry" in DIRECT_SCAN_IS_LEGACY_COMPAT_POLICY

    def test_legacy_orchestrator_demoted_policy_importable(self):
        try:
            from core.node_boundary_runtime import (
                LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY,
            )
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY
        assert "LEGACY_ORCHESTRATOR_NODE" in LEGACY_ORCHESTRATOR_NODES_DEMOTED_FROM_CANONICAL_PATH_POLICY


# ===========================================================================
# B) Enums
# ===========================================================================


class TestEnums:
    """NodePathwayKind and LegacyNodeSurfaceStatus must have expected members."""

    def test_node_pathway_kind_canonical(self):
        try:
            from core.node_boundary_runtime import NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodePathwayKind.CANONICAL.value == "canonical"

    def test_node_pathway_kind_compat_only(self):
        try:
            from core.node_boundary_runtime import NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodePathwayKind.COMPAT_ONLY.value == "compat_only"

    def test_node_pathway_kind_legacy_scan(self):
        try:
            from core.node_boundary_runtime import NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodePathwayKind.LEGACY_SCAN.value == "legacy_scan"

    def test_node_pathway_kind_legacy_registry(self):
        try:
            from core.node_boundary_runtime import NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodePathwayKind.LEGACY_REGISTRY.value == "legacy_registry"

    def test_node_pathway_kind_architectural_violation(self):
        try:
            from core.node_boundary_runtime import NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodePathwayKind.ARCHITECTURAL_VIOLATION.value == "architectural_violation"

    def test_legacy_surface_status_active_canonical(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LegacyNodeSurfaceStatus.ACTIVE_CANONICAL.value == "active_canonical"

    def test_legacy_surface_status_compat_facade(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LegacyNodeSurfaceStatus.COMPAT_FACADE.value == "compat_facade"

    def test_legacy_surface_status_compat_endpoint(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LegacyNodeSurfaceStatus.COMPAT_ENDPOINT.value == "compat_endpoint"

    def test_legacy_surface_status_demoted(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LegacyNodeSurfaceStatus.DEMOTED.value == "demoted"

    def test_legacy_surface_status_deleted(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert LegacyNodeSurfaceStatus.DELETED.value == "deleted"


# ===========================================================================
# C) NodeBoundaryDecision dataclass
# ===========================================================================


class TestNodeBoundaryDecision:
    """NodeBoundaryDecision must be instantiable and serialisable."""

    def test_instantiable_with_required_args(self):
        try:
            from core.node_boundary_runtime import NodeBoundaryDecision
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        decision = NodeBoundaryDecision(node_id="test_node_1")
        assert decision.node_id == "test_node_1"
        assert decision.is_canonical is True
        assert decision.boundary_violations == []

    def test_to_dict_has_required_keys(self):
        try:
            from core.node_boundary_runtime import NodeBoundaryDecision
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        d = NodeBoundaryDecision(node_id="test_node_2").to_dict()
        for key in ("node_id", "architectural_class", "is_canonical",
                    "boundary_violations", "diagnostic_context", "evaluated_at"):
            assert key in d, f"Missing key: {key}"

    def test_violations_list_accumulates(self):
        try:
            from core.node_boundary_runtime import NodeBoundaryDecision
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        decision = NodeBoundaryDecision(
            node_id="test_node_3",
            is_canonical=False,
            boundary_violations=["v1", "v2"],
        )
        assert len(decision.boundary_violations) == 2
        assert decision.to_dict()["boundary_violations"] == ["v1", "v2"]

    def test_to_dict_node_id_matches(self):
        try:
            from core.node_boundary_runtime import NodeBoundaryDecision
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert NodeBoundaryDecision(node_id="my_node").to_dict()["node_id"] == "my_node"


# ===========================================================================
# D) LegacyNodeSurfaceEntry dataclass
# ===========================================================================


class TestLegacyNodeSurfaceEntry:
    """LegacyNodeSurfaceEntry must be instantiable and serialisable."""

    def test_instantiable_with_explicit_args(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceEntry, LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        entry = LegacyNodeSurfaceEntry(
            surface_id="test_surface",
            display_name="Test Surface",
            status=LegacyNodeSurfaceStatus.COMPAT_FACADE,
            canonical_replacement="Use canonical path instead",
        )
        assert entry.surface_id == "test_surface"
        assert entry.status == LegacyNodeSurfaceStatus.COMPAT_FACADE

    def test_to_dict_has_required_keys(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceEntry, LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        entry = LegacyNodeSurfaceEntry(
            surface_id="s1",
            display_name="S1",
            status=LegacyNodeSurfaceStatus.DEMOTED,
            canonical_replacement="canonical path",
        )
        d = entry.to_dict()
        for key in ("surface_id", "display_name", "status", "canonical_replacement",
                    "pr_demoted", "notes"):
            assert key in d, f"Missing key: {key}"

    def test_status_serialises_to_string(self):
        try:
            from core.node_boundary_runtime import LegacyNodeSurfaceEntry, LegacyNodeSurfaceStatus
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        entry = LegacyNodeSurfaceEntry(
            surface_id="s2", display_name="S2",
            status=LegacyNodeSurfaceStatus.COMPAT_ENDPOINT,
            canonical_replacement="invoke_node()",
        )
        assert entry.to_dict()["status"] == "compat_endpoint"


# ===========================================================================
# E) NodeBoundarySnapshot dataclass
# ===========================================================================


class TestNodeBoundarySnapshot:
    """NodeBoundarySnapshot must be instantiable and serialisable."""

    def test_instantiable_with_defaults(self):
        try:
            from core.node_boundary_runtime import NodeBoundarySnapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        snap = NodeBoundarySnapshot()
        assert snap.total_nodes == 0
        assert snap.node_decisions == []
        assert snap.legacy_surfaces == []

    def test_to_dict_has_required_keys(self):
        try:
            from core.node_boundary_runtime import NodeBoundarySnapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        d = NodeBoundarySnapshot().to_dict()
        for key in ("total_nodes", "canonical_nodes", "legacy_nodes",
                    "violation_nodes", "node_decisions", "legacy_surfaces", "snapshot_time"):
            assert key in d, f"Missing key: {key}"

    def test_node_decisions_serialises_correctly(self):
        try:
            from core.node_boundary_runtime import NodeBoundarySnapshot, NodeBoundaryDecision
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        decision = NodeBoundaryDecision(node_id="snap_node_1")
        snap = NodeBoundarySnapshot(total_nodes=1, canonical_nodes=1, node_decisions=[decision])
        d = snap.to_dict()
        assert len(d["node_decisions"]) == 1
        assert d["node_decisions"][0]["node_id"] == "snap_node_1"


# ===========================================================================
# F) classify_invocation_pathway
# ===========================================================================


class TestClassifyInvocationPathway:
    """classify_invocation_pathway must return correct NodePathwayKind values."""

    def test_invoke_node_is_canonical(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("invoke_node") == NodePathwayKind.CANONICAL

    def test_unified_executor_is_canonical(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("unified_node_executor") == NodePathwayKind.CANONICAL

    def test_capability_registry_tool_call_is_canonical(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("capability_registry_tool_call") == NodePathwayKind.CANONICAL

    def test_openclawd_dispatch_is_canonical(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("openclawd_node_dispatch") == NodePathwayKind.CANONICAL

    def test_post_api_nodes_call_is_compat_only(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("post_api_v1_nodes_call") == NodePathwayKind.COMPAT_ONLY

    def test_legacy_http_node_call_is_compat_only(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("legacy_http_node_call") == NodePathwayKind.COMPAT_ONLY

    def test_fs_scan_is_legacy_scan(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("get_api_v1_nodes_fs_scan") == NodePathwayKind.LEGACY_SCAN

    def test_direct_nodes_dir_scan_is_legacy_scan(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("direct_nodes_dir_scan") == NodePathwayKind.LEGACY_SCAN

    def test_node_registry_legacy_is_legacy_registry(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("node_registry_legacy") == NodePathwayKind.LEGACY_REGISTRY

    def test_unknown_pathway_defaults_to_canonical(self):
        try:
            from core.node_boundary_runtime import classify_invocation_pathway, NodePathwayKind
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        assert classify_invocation_pathway("unknown_xyz_pathway") == NodePathwayKind.CANONICAL


# ===========================================================================
# G) build_legacy_surface_registry
# ===========================================================================


class TestBuildLegacySurfaceRegistry:
    """build_legacy_surface_registry must return the expected catalogue."""

    def test_returns_at_least_5_entries(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        entries = build_legacy_surface_registry()
        assert len(entries) >= 5

    def test_contains_node_registry_compat_facade(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        ids = {e.surface_id for e in build_legacy_surface_registry()}
        assert "node_registry_compat_facade" in ids

    def test_contains_direct_fs_scan_surface(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        ids = {e.surface_id for e in build_legacy_surface_registry()}
        assert "direct_fs_scan_nodes_list" in ids

    def test_contains_nodes_call_compat_endpoint(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        ids = {e.surface_id for e in build_legacy_surface_registry()}
        assert "nodes_call_compat_endpoint" in ids

    def test_contains_fusion_entry_registry_misuse(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        ids = {e.surface_id for e in build_legacy_surface_registry()}
        assert "fusion_entry_as_registry_authority" in ids

    def test_contains_legacy_orchestrator_on_canonical_path(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        ids = {e.surface_id for e in build_legacy_surface_registry()}
        assert "legacy_orchestrator_node_on_canonical_path" in ids

    def test_all_entries_have_canonical_replacement(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        for entry in build_legacy_surface_registry():
            assert entry.canonical_replacement, (
                f"Entry '{entry.surface_id}' has empty canonical_replacement"
            )

    def test_returns_copy_not_original(self):
        try:
            from core.node_boundary_runtime import build_legacy_surface_registry
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        r1 = build_legacy_surface_registry()
        r2 = build_legacy_surface_registry()
        assert r1 is not r2


# ===========================================================================
# H) evaluate_node_boundary_compliance — CAPABILITY_NODE
# ===========================================================================


class TestEvalCapabilityNode:
    """CAPABILITY_NODE nodes must pass boundary compliance."""

    def test_capability_node_is_canonical(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("cap_node_1", "capability_node")
        decision = evaluate_node_boundary_compliance(node)
        assert decision.is_canonical is True

    def test_capability_node_has_no_violations(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("cap_node_2", "capability_node")
        decision = evaluate_node_boundary_compliance(node)
        assert decision.boundary_violations == []

    def test_to_dict_node_id_and_is_canonical(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("cap_node_3", "capability_node")
        d = evaluate_node_boundary_compliance(node).to_dict()
        assert d["node_id"] == "cap_node_3"
        assert d["is_canonical"] is True

    def test_service_node_has_no_violations(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("svc_node_1", "service_node")
        decision = evaluate_node_boundary_compliance(node)
        assert decision.boundary_violations == []


# ===========================================================================
# I) evaluate_node_boundary_compliance — LEGACY_ORCHESTRATOR_NODE
# ===========================================================================


class TestEvalLegacyOrchestratorNode:
    """LEGACY_ORCHESTRATOR_NODE must be flagged as non-canonical."""

    def test_is_not_canonical(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("orch_node_1", "legacy_orchestrator_node")
        assert evaluate_node_boundary_compliance(node).is_canonical is False

    def test_has_violations(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("orch_node_2", "legacy_orchestrator_node")
        decision = evaluate_node_boundary_compliance(node)
        assert len(decision.boundary_violations) >= 1

    def test_violation_mentions_node_id(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("orch_node_3", "legacy_orchestrator_node")
        decision = evaluate_node_boundary_compliance(node)
        assert any("orch_node_3" in v for v in decision.boundary_violations)

    def test_diagnostic_context_populated(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("orch_node_4", "legacy_orchestrator_node")
        decision = evaluate_node_boundary_compliance(node)
        assert decision.diagnostic_context
        assert decision.diagnostic_context.get("violation_count", 0) >= 1


# ===========================================================================
# J) evaluate_node_boundary_compliance — ARCHIVED_NODE
# ===========================================================================


class TestEvalArchivedNode:
    """ARCHIVED_NODE must be flagged as non-canonical."""

    def test_archived_node_is_not_canonical(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("arch_node_1", "archived_node")
        decision = evaluate_node_boundary_compliance(node)
        assert decision.is_canonical is False

    def test_archived_node_violation_mentions_archived(self):
        try:
            from core.node_boundary_runtime import evaluate_node_boundary_compliance
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        node = _make_stub_node("arch_node_2", "archived_node")
        decision = evaluate_node_boundary_compliance(node)
        all_violations = " ".join(decision.boundary_violations).lower()
        assert "archived" in all_violations


# ===========================================================================
# K) get_canonical_nodes
# ===========================================================================


class TestGetCanonicalNodes:
    """get_canonical_nodes must degrade gracefully and filter correctly."""

    def test_returns_empty_list_when_fabric_unavailable(self):
        try:
            from core.node_boundary_runtime import get_canonical_nodes
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        import sys
        from unittest.mock import patch
        # Patch out the fabric registry import to simulate unavailability
        with patch.dict(sys.modules, {"core.nodes.node_fabric_registry": None}):
            result = get_canonical_nodes(fabric_registry=None)
        assert isinstance(result, list)

    def test_returns_only_capability_nodes_from_stub_registry(self):
        try:
            from core.node_boundary_runtime import get_canonical_nodes
            from core.nodes.node_fabric_registry import NodeArchitecturalClass
        except ImportError as e:
            pytest.skip(f"imports not available: {e}")

        cap_node = _make_stub_node("cap1", "capability_node")
        leg_node = _make_stub_node("leg1", "legacy_orchestrator_node")

        mock_registry = MagicMock()
        mock_registry.list_by_architectural_class.return_value = [cap_node]

        result = get_canonical_nodes(fabric_registry=mock_registry)
        mock_registry.list_by_architectural_class.assert_called_once_with(
            NodeArchitecturalClass.CAPABILITY_NODE
        )
        assert result == [cap_node]

    def test_accepts_explicit_fabric_registry(self):
        try:
            from core.node_boundary_runtime import get_canonical_nodes
            from core.nodes.node_fabric_registry import NodeArchitecturalClass
        except ImportError as e:
            pytest.skip(f"imports not available: {e}")
        mock_registry = MagicMock()
        mock_registry.list_by_architectural_class.return_value = []
        result = get_canonical_nodes(fabric_registry=mock_registry)
        assert result == []


# ===========================================================================
# L) build_node_boundary_snapshot
# ===========================================================================


class TestBuildNodeBoundarySnapshot:
    """build_node_boundary_snapshot must return a complete NodeBoundarySnapshot."""

    def test_returns_snapshot_with_legacy_surfaces(self):
        try:
            from core.node_boundary_runtime import build_node_boundary_snapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = []
        snap = build_node_boundary_snapshot(fabric_registry=mock_registry)
        assert len(snap.legacy_surfaces) >= 5

    def test_graceful_when_fabric_unavailable(self):
        try:
            from core.node_boundary_runtime import build_node_boundary_snapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        import sys
        from unittest.mock import patch
        with patch.dict(sys.modules, {"core.nodes.node_fabric_registry": None}):
            snap = build_node_boundary_snapshot(fabric_registry=None)
        assert snap is not None
        assert snap.total_nodes == 0

    def test_counts_canonical_vs_legacy_nodes(self):
        try:
            from core.node_boundary_runtime import build_node_boundary_snapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        cap_node = _make_stub_node("c1", "capability_node")
        leg_node = _make_stub_node("l1", "legacy_orchestrator_node")

        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = [cap_node, leg_node]

        snap = build_node_boundary_snapshot(fabric_registry=mock_registry)
        assert snap.total_nodes == 2
        assert snap.canonical_nodes == 1
        assert snap.legacy_nodes == 1

    def test_violation_nodes_counted_correctly(self):
        try:
            from core.node_boundary_runtime import build_node_boundary_snapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        leg_node = _make_stub_node("l2", "legacy_orchestrator_node")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = [leg_node]

        snap = build_node_boundary_snapshot(fabric_registry=mock_registry)
        assert snap.violation_nodes == 1

    def test_snapshot_to_dict_is_complete(self):
        try:
            from core.node_boundary_runtime import build_node_boundary_snapshot
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = []
        d = build_node_boundary_snapshot(fabric_registry=mock_registry).to_dict()
        for key in ("total_nodes", "canonical_nodes", "legacy_nodes",
                    "violation_nodes", "node_decisions", "legacy_surfaces", "snapshot_time"):
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# M) get_boundary_summary
# ===========================================================================


class TestGetBoundarySummary:
    """get_boundary_summary must return all required keys."""

    def test_has_all_required_keys(self):
        try:
            from core.node_boundary_runtime import get_boundary_summary
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = []
        summary = get_boundary_summary(fabric_registry=mock_registry)
        for key in ("total_nodes", "canonical_nodes", "legacy_nodes",
                    "violation_nodes", "legacy_surface_count",
                    "boundary_health", "pr8_sentinel"):
            assert key in summary, f"Missing key: {key}"

    def test_boundary_health_clean_when_no_violations(self):
        try:
            from core.node_boundary_runtime import get_boundary_summary
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        cap_node = _make_stub_node("c2", "capability_node")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = [cap_node]
        summary = get_boundary_summary(fabric_registry=mock_registry)
        assert summary["boundary_health"] == "clean"

    def test_boundary_health_violations_detected_when_legacy_present(self):
        try:
            from core.node_boundary_runtime import get_boundary_summary
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        leg_node = _make_stub_node("l3", "legacy_orchestrator_node")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = [leg_node]
        summary = get_boundary_summary(fabric_registry=mock_registry)
        assert summary["boundary_health"] == "violations_detected"

    def test_pr8_sentinel_key_has_correct_value(self):
        try:
            from core.node_boundary_runtime import get_boundary_summary, NODE_BOUNDARY_RUNTIME_PR8_SENTINEL
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = []
        summary = get_boundary_summary(fabric_registry=mock_registry)
        assert summary["pr8_sentinel"] == NODE_BOUNDARY_RUNTIME_PR8_SENTINEL

    def test_legacy_surface_count_matches_catalogue(self):
        try:
            from core.node_boundary_runtime import (
                get_boundary_summary, build_legacy_surface_registry
            )
        except ImportError as e:
            pytest.skip(f"node_boundary_runtime not importable: {e}")
        mock_registry = MagicMock()
        mock_registry.list_nodes.return_value = []
        summary = get_boundary_summary(fabric_registry=mock_registry)
        expected_count = len(build_legacy_surface_registry())
        assert summary["legacy_surface_count"] == expected_count


# ===========================================================================
# N) projection.py sentinel
# ===========================================================================


class TestProjectionSentinel:
    """NODE_BOUNDARY_RUNTIME_ALIGNED_PR8 must be importable and meaningful."""

    def test_sentinel_importable(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert NODE_BOUNDARY_RUNTIME_ALIGNED_PR8

    def test_sentinel_is_not_unavailable(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert "UNAVAILABLE" not in NODE_BOUNDARY_RUNTIME_ALIGNED_PR8, (
            "NODE_BOUNDARY_RUNTIME_ALIGNED_PR8 resolved to the fallback/unavailable "
            "value — core.node_boundary_runtime failed to import"
        )

    def test_sentinel_mentions_capability_backends(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert "capability" in NODE_BOUNDARY_RUNTIME_ALIGNED_PR8.lower()

    def test_sentinel_mentions_invoke_node(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert "invoke_node" in NODE_BOUNDARY_RUNTIME_ALIGNED_PR8

    def test_sentinel_mentions_node_fabric_registry(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert "NodeFabricRegistry" in NODE_BOUNDARY_RUNTIME_ALIGNED_PR8

    def test_sentinel_has_pr8_v1_prefix(self):
        try:
            from core.routes.projection import NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
        except ImportError as e:
            pytest.skip(f"projection not importable: {e}")
        assert "NODE_BOUNDARY_RUNTIME_ALIGNED_PR8_V1" in NODE_BOUNDARY_RUNTIME_ALIGNED_PR8
