#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr15_node_activation_context.py
============================================
PR-15 (node track): Canonical Node Activation Context Layer.

Covers:
  A) Authority module: sentinels and policies are importable and contain the
     expected identifier strings.

  B) NodeActivationPolicyKind enum has the expected values (ALWAYS_ACTIVE,
     TOPOLOGY_CONDITIONAL, DEMAND_ACTIVATED, DORMANT) and is a str subclass.

  C) NodeActivationReadinessDecision dataclass can be instantiated and
     serialised via to_dict().

  D) evaluate_node_activation_context — ALWAYS_ACTIVE: ready=True.

  E) evaluate_node_activation_context — DORMANT: ready=False, denial_reason="dormant".

  F) evaluate_node_activation_context — DEMAND_ACTIVATED without context:
     ready=False, denial_reason="demand_context_missing".

  G) evaluate_node_activation_context — DEMAND_ACTIVATED with context:
     ready=True, denial_reason="".

  H) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL without
     topology_runtime (degraded mode): ready=True, topology_consulted=False.

  I) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL with topology
     runtime, node present and reachable: ready=True, topology_consulted=True.

  J) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL with topology
     runtime, node absent from topology:
     ready=False, denial_reason="topology_unreachable".

  K) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL with topology
     runtime, node in UNAVAILABLE state: ready=False, denial_reason="topology_unreachable".

  L) get_activation_policy_kind_for_node — from activation_policy field.

  M) get_activation_policy_kind_for_node — from metadata dict fallback.

  N) get_activation_policy_kind_for_node — no policy set: defaults to ALWAYS_ACTIVE.

  O) get_activation_policy_kind_for_node — unknown policy value: defaults to ALWAYS_ACTIVE.

  P) build_activation_context_denial_diagnostics returns expected keys/values.

  Q) NodeInfo.activation_policy field is present in NodeFabricRegistry.NodeInfo.

  R) NodeInfo.to_dict() includes activation_policy key.

  S) NodeFabricRegistry round-trip preserves activation_policy.

  T) evaluate_invocation_governance — governance-eligible ALWAYS_ACTIVE node:
     invocation_allowed=True, activation_context_status="ready".

  U) evaluate_invocation_governance — governance-eligible DORMANT node:
     invocation_allowed=False, governance_status="activation_context_blocked",
     activation_context_status="blocked_dormant".

  V) evaluate_invocation_governance — governance-eligible DEMAND_ACTIVATED node
     without demand_context: invocation_allowed=False,
     activation_context_status="blocked_demand_context_missing".

  W) evaluate_invocation_governance — governance-eligible DEMAND_ACTIVATED node
     with demand_context: invocation_allowed=True, activation_context_status="ready".

  X) evaluate_invocation_governance — governance-ineligible node:
     invocation_allowed=False, governance_status="ineligible_denied",
     activation_context_evaluated=False (activation context not consulted).

  Y) NodeInvocationGovernanceDecision.to_dict() includes
     activation_context_status and activation_context_evaluated.

  Z) Projection sentinel NODE_ACTIVATION_CONTEXT_ALIGNED_PR15 is importable
     and not the UNAVAILABLE stub.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node_info(
    node_id: str,
    arch_class_value: str = "CAPABILITY_NODE",
    healthy: bool = True,
    activation_policy: Optional[str] = None,
) -> Any:
    """Create a minimal NodeInfo-like object for tests."""
    from core.nodes.node_fabric_registry import NodeArchitecturalClass, NodeStatus

    arch_map = {
        "CAPABILITY_NODE": NodeArchitecturalClass.CAPABILITY_NODE,
        "ARCHIVED_NODE": NodeArchitecturalClass.ARCHIVED_NODE,
        "SERVICE_NODE": NodeArchitecturalClass.SERVICE_NODE,
        "LEGACY_ORCHESTRATOR_NODE": NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE,
        "EXPERIMENTAL_NODE": NodeArchitecturalClass.EXPERIMENTAL_NODE,
    }
    arch = arch_map.get(arch_class_value, NodeArchitecturalClass.CAPABILITY_NODE)

    mock = MagicMock()
    mock.node_id = node_id
    mock.architectural_class = arch
    mock.is_healthy = MagicMock(return_value=healthy)
    mock.status = NodeStatus.HEALTHY if healthy else NodeStatus.UNHEALTHY
    mock.activation_policy = activation_policy
    mock.metadata = {}
    return mock


def _stub_registry(node_id: str, node_info: Any = None, found: bool = True) -> Any:
    """Return a minimal registry stub."""
    reg = MagicMock()
    if found and node_info is not None:
        reg.get.return_value = node_info
    elif found:
        reg.get.return_value = _make_node_info(node_id)
    else:
        reg.get.return_value = None
    return reg


def _stub_eligibility(eligible: bool = True, reasons=None) -> Any:
    """Return a minimal governance eligibility stub."""
    elig = MagicMock()
    elig.eligible = eligible
    elig.exclusion_reasons = reasons if reasons is not None else ([] if eligible else ["archived_node"])
    elig.governor_consulted = False
    elig.diagnostic_context = {"stub": True}
    return elig


# ---------------------------------------------------------------------------
# A) Authority sentinels and policies
# ---------------------------------------------------------------------------


class TestAuthorityModule:
    def test_authority_sentinel_importable(self):
        from core.node_activation_context import NODE_ACTIVATION_CONTEXT_IS_AUTHORITY
        assert "NODE_ACTIVATION_CONTEXT" in NODE_ACTIVATION_CONTEXT_IS_AUTHORITY
        assert "PR15" in NODE_ACTIVATION_CONTEXT_IS_AUTHORITY

    def test_pr_sentinel_importable(self):
        from core.node_activation_context import NODE_ACTIVATION_CONTEXT_PR15_SENTINEL
        assert "PR15" in NODE_ACTIVATION_CONTEXT_PR15_SENTINEL

    def test_five_policy_sentinels_importable(self):
        from core.node_activation_context import (
            ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY,
            DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY,
            TOPOLOGY_CONDITIONAL_REQUIRES_CONNECTIVITY_POLICY,
            DEMAND_ACTIVATED_REQUIRES_EXPLICIT_REQUEST_POLICY,
            ACTIVATION_POLICY_CLASSIFICATION_IS_RUNTIME_METADATA_POLICY,
        )
        for sentinel in [
            ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY,
            DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY,
            TOPOLOGY_CONDITIONAL_REQUIRES_CONNECTIVITY_POLICY,
            DEMAND_ACTIVATED_REQUIRES_EXPLICIT_REQUEST_POLICY,
            ACTIVATION_POLICY_CLASSIFICATION_IS_RUNTIME_METADATA_POLICY,
        ]:
            assert isinstance(sentinel, str) and len(sentinel) > 0

    def test_authority_is_non_empty_string(self):
        from core.node_activation_context import NODE_ACTIVATION_CONTEXT_IS_AUTHORITY
        assert isinstance(NODE_ACTIVATION_CONTEXT_IS_AUTHORITY, str)
        assert len(NODE_ACTIVATION_CONTEXT_IS_AUTHORITY) > 20

    def test_enriches_governance_policy_mentions_governance(self):
        from core.node_activation_context import (
            ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY,
        )
        assert "governance" in ACTIVATION_CONTEXT_ENRICHES_INVOCATION_GOVERNANCE_POLICY.lower()

    def test_dormant_policy_mentions_dormant(self):
        from core.node_activation_context import (
            DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY,
        )
        assert "DORMANT" in DORMANT_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY


# ---------------------------------------------------------------------------
# B) NodeActivationPolicyKind enum
# ---------------------------------------------------------------------------


class TestNodeActivationPolicyKind:
    def test_always_active_value(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert NodeActivationPolicyKind.ALWAYS_ACTIVE.value == "always_active"

    def test_topology_conditional_value(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL.value == "topology_conditional"

    def test_demand_activated_value(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert NodeActivationPolicyKind.DEMAND_ACTIVATED.value == "demand_activated"

    def test_dormant_value(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert NodeActivationPolicyKind.DORMANT.value == "dormant"

    def test_is_str_subclass(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert issubclass(NodeActivationPolicyKind, str)

    def test_has_four_members(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert len(NodeActivationPolicyKind) == 4

    def test_coercible_from_string(self):
        from core.node_activation_context import NodeActivationPolicyKind
        assert NodeActivationPolicyKind("always_active") == NodeActivationPolicyKind.ALWAYS_ACTIVE
        assert NodeActivationPolicyKind("dormant") == NodeActivationPolicyKind.DORMANT


# ---------------------------------------------------------------------------
# C) NodeActivationReadinessDecision dataclass
# ---------------------------------------------------------------------------


class TestNodeActivationReadinessDecision:
    def test_instantiation_minimal(self):
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
        )
        d = NodeActivationReadinessDecision(
            node_id="test-node",
            policy_kind=NodeActivationPolicyKind.ALWAYS_ACTIVE,
            ready=True,
        )
        assert d.node_id == "test-node"
        assert d.ready is True
        assert d.denial_reason == ""

    def test_to_dict_has_expected_keys(self):
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
        )
        d = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.DORMANT,
            ready=False,
            denial_reason="dormant",
        )
        result = d.to_dict()
        for key in ["node_id", "policy_kind", "ready", "denial_reason",
                    "diagnostic_context", "topology_consulted",
                    "demand_context_present", "evaluated_at", "authority"]:
            assert key in result, f"Missing key: {key}"

    def test_to_dict_policy_kind_is_string(self):
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
        )
        d = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            ready=True,
        )
        assert d.to_dict()["policy_kind"] == "topology_conditional"

    def test_to_dict_is_json_serialisable(self):
        import json
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
        )
        d = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.DEMAND_ACTIVATED,
            ready=False,
            denial_reason="demand_context_missing",
        )
        json.dumps(d.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# D) evaluate_node_activation_context — ALWAYS_ACTIVE
# ---------------------------------------------------------------------------


class TestEvaluateAlwaysActive:
    def test_ready_without_extras(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.ALWAYS_ACTIVE)
        assert result.ready is True
        assert result.denial_reason == ""

    def test_ready_with_demand_context(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.ALWAYS_ACTIVE, demand_context="some-demand"
        )
        assert result.ready is True

    def test_topology_not_consulted(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        topo = MagicMock()
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.ALWAYS_ACTIVE, topology_runtime=topo
        )
        assert result.ready is True
        topo.get_node.assert_not_called()

    def test_topology_consulted_false(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.ALWAYS_ACTIVE)
        assert result.topology_consulted is False

    def test_policy_kind_in_result(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.ALWAYS_ACTIVE)
        assert result.policy_kind == NodeActivationPolicyKind.ALWAYS_ACTIVE


# ---------------------------------------------------------------------------
# E) evaluate_node_activation_context — DORMANT
# ---------------------------------------------------------------------------


class TestEvaluateDormant:
    def test_blocked(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.DORMANT)
        assert result.ready is False
        assert result.denial_reason == "dormant"

    def test_topology_not_consulted(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        topo = MagicMock()
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.DORMANT, topology_runtime=topo
        )
        assert result.ready is False
        topo.get_node.assert_not_called()

    def test_demand_context_has_no_effect(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.DORMANT, demand_context="explicit-demand"
        )
        assert result.ready is False
        assert result.denial_reason == "dormant"

    def test_to_dict_json_serialisable(self):
        import json
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.DORMANT)
        json.dumps(result.to_dict())


# ---------------------------------------------------------------------------
# F) evaluate_node_activation_context — DEMAND_ACTIVATED without context
# ---------------------------------------------------------------------------


class TestEvaluateDemandActivatedNoContext:
    def test_blocked_without_demand(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.DEMAND_ACTIVATED)
        assert result.ready is False
        assert result.denial_reason == "demand_context_missing"

    def test_blocked_with_empty_string(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.DEMAND_ACTIVATED, demand_context=""
        )
        assert result.ready is False
        assert result.denial_reason == "demand_context_missing"

    def test_demand_context_present_false(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context("n1", NodeActivationPolicyKind.DEMAND_ACTIVATED)
        assert result.demand_context_present is False


# ---------------------------------------------------------------------------
# G) evaluate_node_activation_context — DEMAND_ACTIVATED with context
# ---------------------------------------------------------------------------


class TestEvaluateDemandActivatedWithContext:
    def test_ready_with_demand(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.DEMAND_ACTIVATED, demand_context="task-12345"
        )
        assert result.ready is True
        assert result.denial_reason == ""

    def test_demand_context_present_true(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.DEMAND_ACTIVATED, demand_context="task-x"
        )
        assert result.demand_context_present is True


# ---------------------------------------------------------------------------
# H) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL no runtime
# ---------------------------------------------------------------------------


class TestEvaluateTopologyConditionalNoRuntime:
    def test_ready_without_topology_runtime(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL
        )
        assert result.ready is True
        assert result.topology_consulted is False

    def test_note_mentions_degraded(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        result = evaluate_node_activation_context(
            "n1", NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL
        )
        note = result.diagnostic_context.get("note", "")
        assert "degraded" in note.lower()


# ---------------------------------------------------------------------------
# I) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL reachable
# ---------------------------------------------------------------------------


class TestEvaluateTopologyConditionalReachable:
    def _reachable_topo_node(self, node_id: str) -> Any:
        topo_node = MagicMock()
        topo_node.node_id = node_id
        try:
            from core.network_topology_runtime import TopologyConnectionState
            topo_node.state = TopologyConnectionState.CONNECTED
        except ImportError:
            # Stub: use any non-UNAVAILABLE state
            topo_node.state = MagicMock()
            topo_node.state.value = "connected"
        return topo_node

    def test_ready_when_node_reachable(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        topo_node = self._reachable_topo_node("n1")
        topo = MagicMock()
        topo.get_node.return_value = topo_node

        result = evaluate_node_activation_context(
            "n1",
            NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            topology_runtime=topo,
        )
        assert result.ready is True
        assert result.topology_consulted is True

    def test_get_node_called_with_node_id(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        topo_node = self._reachable_topo_node("n1")
        topo = MagicMock()
        topo.get_node.return_value = topo_node

        evaluate_node_activation_context(
            "n1",
            NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            topology_runtime=topo,
        )
        topo.get_node.assert_called_once_with("n1")


# ---------------------------------------------------------------------------
# J) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL node absent
# ---------------------------------------------------------------------------


class TestEvaluateTopologyConditionalAbsent:
    def test_blocked_when_node_not_in_topology(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        topo = MagicMock()
        topo.get_node.return_value = None  # node not in topology

        result = evaluate_node_activation_context(
            "n1",
            NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            topology_runtime=topo,
        )
        assert result.ready is False
        assert result.denial_reason == "topology_unreachable"
        assert result.topology_consulted is True


# ---------------------------------------------------------------------------
# K) evaluate_node_activation_context — TOPOLOGY_CONDITIONAL UNAVAILABLE state
# ---------------------------------------------------------------------------


class TestEvaluateTopologyConditionalUnavailable:
    def test_blocked_when_state_unavailable(self):
        from core.node_activation_context import (
            evaluate_node_activation_context,
            NodeActivationPolicyKind,
        )
        try:
            from core.network_topology_runtime import TopologyConnectionState
        except ImportError:
            pytest.skip("NetworkTopologyRuntime not available")

        topo_node = MagicMock()
        topo_node.state = TopologyConnectionState.UNAVAILABLE

        topo = MagicMock()
        topo.get_node.return_value = topo_node

        result = evaluate_node_activation_context(
            "n1",
            NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            topology_runtime=topo,
        )
        assert result.ready is False
        assert result.denial_reason == "topology_unreachable"
        assert result.topology_consulted is True


# ---------------------------------------------------------------------------
# L) get_activation_policy_kind_for_node — from activation_policy field
# ---------------------------------------------------------------------------


class TestGetActivationPolicyFromField:
    def test_dormant_from_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy="dormant")
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.DORMANT

    def test_always_active_from_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy="always_active")
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.ALWAYS_ACTIVE

    def test_topology_conditional_from_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy="topology_conditional")
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL

    def test_demand_activated_from_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy="demand_activated")
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.DEMAND_ACTIVATED


# ---------------------------------------------------------------------------
# M) get_activation_policy_kind_for_node — from metadata dict
# ---------------------------------------------------------------------------


class TestGetActivationPolicyFromMetadata:
    def test_dormant_from_metadata(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1")  # activation_policy=None
        node.metadata["activation_policy"] = "dormant"
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.DORMANT

    def test_demand_activated_from_metadata(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1")
        node.metadata["activation_policy"] = "demand_activated"
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.DEMAND_ACTIVATED

    def test_field_takes_priority_over_metadata(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        # activation_policy field = dormant; metadata = demand_activated
        node = _make_node_info("n1", activation_policy="dormant")
        node.metadata["activation_policy"] = "demand_activated"
        # Field should win
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.DORMANT


# ---------------------------------------------------------------------------
# N) get_activation_policy_kind_for_node — no policy set
# ---------------------------------------------------------------------------


class TestGetActivationPolicyDefault:
    def test_defaults_to_always_active_no_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1")  # activation_policy=None
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.ALWAYS_ACTIVE

    def test_defaults_to_always_active_none_field(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy=None)
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.ALWAYS_ACTIVE


# ---------------------------------------------------------------------------
# O) get_activation_policy_kind_for_node — unknown policy value
# ---------------------------------------------------------------------------


class TestGetActivationPolicyUnknown:
    def test_unknown_value_defaults_to_always_active(self):
        from core.node_activation_context import (
            get_activation_policy_kind_for_node,
            NodeActivationPolicyKind,
        )
        node = _make_node_info("n1", activation_policy="not_a_real_policy")
        assert get_activation_policy_kind_for_node(node) == NodeActivationPolicyKind.ALWAYS_ACTIVE


# ---------------------------------------------------------------------------
# P) build_activation_context_denial_diagnostics
# ---------------------------------------------------------------------------


class TestBuildActivationContextDenialDiagnostics:
    def test_dormant_denial_keys(self):
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
            build_activation_context_denial_diagnostics,
        )
        decision = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.DORMANT,
            ready=False,
            denial_reason="dormant",
        )
        result = build_activation_context_denial_diagnostics(decision)
        for key in ["node_id", "denial_reason", "policy_kind", "diagnostic_context",
                    "topology_consulted", "demand_context_present", "denied_at", "sentinel"]:
            assert key in result, f"Missing key: {key}"

    def test_sentinel_contains_pr15(self):
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
            build_activation_context_denial_diagnostics,
        )
        decision = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.DORMANT,
            ready=False,
            denial_reason="dormant",
        )
        result = build_activation_context_denial_diagnostics(decision)
        assert "PR15" in result["sentinel"]

    def test_json_serialisable(self):
        import json
        from core.node_activation_context import (
            NodeActivationReadinessDecision,
            NodeActivationPolicyKind,
            build_activation_context_denial_diagnostics,
        )
        decision = NodeActivationReadinessDecision(
            node_id="n1",
            policy_kind=NodeActivationPolicyKind.TOPOLOGY_CONDITIONAL,
            ready=False,
            denial_reason="topology_unreachable",
            topology_consulted=True,
        )
        result = build_activation_context_denial_diagnostics(decision)
        json.dumps(result)


# ---------------------------------------------------------------------------
# Q) NodeInfo.activation_policy field in NodeFabricRegistry
# ---------------------------------------------------------------------------


class TestNodeInfoActivationPolicyField:
    def setup_method(self):
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

    def test_field_exists(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="test-ap", role=NodeRole.WORKER)
        assert hasattr(node, "activation_policy")

    def test_defaults_to_none(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="test-ap-2", role=NodeRole.WORKER)
        assert node.activation_policy is None

    def test_can_be_set_to_dormant(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="test-ap-3", role=NodeRole.WORKER, activation_policy="dormant")
        assert node.activation_policy == "dormant"

    def test_can_be_set_to_demand_activated(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="test-ap-4", role=NodeRole.WORKER, activation_policy="demand_activated")
        assert node.activation_policy == "demand_activated"


# ---------------------------------------------------------------------------
# R) NodeInfo.to_dict() includes activation_policy
# ---------------------------------------------------------------------------


class TestNodeInfoToDictActivationPolicy:
    def test_to_dict_has_activation_policy_key(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="dict-test", role=NodeRole.WORKER)
        assert "activation_policy" in node.to_dict()

    def test_to_dict_activation_policy_none_when_unset(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="dict-test-2", role=NodeRole.WORKER)
        assert node.to_dict()["activation_policy"] is None

    def test_to_dict_activation_policy_value_preserved(self):
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="dict-test-3", role=NodeRole.WORKER, activation_policy="demand_activated")
        assert node.to_dict()["activation_policy"] == "demand_activated"

    def test_to_dict_json_serialisable(self):
        import json
        from core.nodes.node_fabric_registry import NodeInfo, NodeRole
        node = NodeInfo(node_id="dict-test-4", role=NodeRole.WORKER, activation_policy="dormant")
        json.dumps(node.to_dict())


# ---------------------------------------------------------------------------
# S) NodeFabricRegistry round-trip preserves activation_policy
# ---------------------------------------------------------------------------


class TestNodeFabricRegistryActivationPolicy:
    def setup_method(self):
        from core.nodes.node_fabric_registry import reset_node_fabric_registry
        reset_node_fabric_registry()

    def test_register_and_get_preserves_activation_policy(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeInfo,
            NodeRole,
        )
        fab = get_node_fabric_registry()
        node = NodeInfo(node_id="rt-ap-01", role=NodeRole.WORKER, activation_policy="dormant")
        fab.register(node)
        retrieved = fab.get("rt-ap-01")
        assert retrieved is not None
        assert retrieved.activation_policy == "dormant"

    def test_register_none_policy_preserved(self):
        from core.nodes.node_fabric_registry import (
            get_node_fabric_registry,
            NodeInfo,
            NodeRole,
        )
        fab = get_node_fabric_registry()
        node = NodeInfo(node_id="rt-ap-02", role=NodeRole.WORKER)
        fab.register(node)
        retrieved = fab.get("rt-ap-02")
        assert retrieved.activation_policy is None


# ---------------------------------------------------------------------------
# T) evaluate_invocation_governance — eligible ALWAYS_ACTIVE
# ---------------------------------------------------------------------------


class TestGovernanceGateAlwaysActive:
    def test_allowed_with_ready_status(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="always_active")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert decision.invocation_allowed is True
        assert decision.governance_status == "eligible"
        assert decision.activation_context_evaluated is True
        assert decision.activation_context_status == "ready"

    def test_activation_context_evaluated_true(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert decision.activation_context_evaluated is True


# ---------------------------------------------------------------------------
# U) evaluate_invocation_governance — eligible DORMANT
# ---------------------------------------------------------------------------


class TestGovernanceGateDormant:
    def test_blocked_by_activation_context(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="dormant")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert decision.invocation_allowed is False
        assert decision.governance_status == "activation_context_blocked"
        assert decision.activation_context_status == "blocked_dormant"
        assert decision.activation_context_evaluated is True

    def test_denial_reasons_contain_dormant(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="dormant")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert any("dormant" in r for r in decision.denial_reasons)

    def test_diagnostic_context_has_activation_denial(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="dormant")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert "activation_context_denial" in decision.diagnostic_context


# ---------------------------------------------------------------------------
# V) evaluate_invocation_governance — DEMAND_ACTIVATED without demand_context
# ---------------------------------------------------------------------------


class TestGovernanceGateDemandActivatedNoContext:
    def test_blocked_without_demand_context(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="demand_activated")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert decision.invocation_allowed is False
        assert decision.governance_status == "activation_context_blocked"
        assert decision.activation_context_status == "blocked_demand_context_missing"

    def test_denial_reason_in_denial_reasons(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="demand_activated")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert any("demand_context_missing" in r for r in decision.denial_reasons)


# ---------------------------------------------------------------------------
# W) evaluate_invocation_governance — DEMAND_ACTIVATED with demand_context
# ---------------------------------------------------------------------------


class TestGovernanceGateDemandActivatedWithContext:
    def test_allowed_with_demand_context(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1", activation_policy="demand_activated")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=True)

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance(
                "n1", registry=registry, demand_context="task-999"
            )

        assert decision.invocation_allowed is True
        assert decision.activation_context_status == "ready"


# ---------------------------------------------------------------------------
# X) evaluate_invocation_governance — governance-ineligible node
# ---------------------------------------------------------------------------


class TestGovernanceGateIneligible:
    def test_ineligible_not_evaluated_for_activation(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        # Even a DORMANT node should get governance_status=ineligible_denied
        # when governance itself denies it (activation not consulted)
        node_info = _make_node_info("n1", activation_policy="dormant", healthy=False)
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=False, reasons=["archived_node"])

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert decision.invocation_allowed is False
        assert decision.governance_status == "ineligible_denied"
        assert decision.activation_context_evaluated is False
        assert decision.activation_context_status == "not_evaluated"

    def test_denial_reasons_from_governance(self):
        from core.node_invocation_governance import evaluate_invocation_governance
        node_info = _make_node_info("n1")
        registry = _stub_registry("n1", node_info=node_info)
        eligibility = _stub_eligibility(eligible=False, reasons=["archived_node"])

        with patch(
            "core.node_governance_runtime.evaluate_node_governance_eligibility",
            return_value=eligibility,
        ):
            decision = evaluate_invocation_governance("n1", registry=registry)

        assert "archived_node" in decision.denial_reasons


# ---------------------------------------------------------------------------
# Y) NodeInvocationGovernanceDecision.to_dict() includes new fields
# ---------------------------------------------------------------------------


class TestGovernanceDecisionToDict:
    def test_to_dict_has_activation_context_status(self):
        from core.node_invocation_governance import (
            NodeInvocationGovernanceDecision,
        )
        d = NodeInvocationGovernanceDecision(
            node_id="n1",
            invocation_allowed=True,
            activation_context_status="ready",
            activation_context_evaluated=True,
        )
        result = d.to_dict()
        assert "activation_context_status" in result
        assert "activation_context_evaluated" in result

    def test_to_dict_values_correct(self):
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(
            node_id="n1",
            invocation_allowed=False,
            governance_status="activation_context_blocked",
            activation_context_status="blocked_dormant",
            activation_context_evaluated=True,
        )
        result = d.to_dict()
        assert result["activation_context_status"] == "blocked_dormant"
        assert result["activation_context_evaluated"] is True

    def test_to_dict_json_serialisable(self):
        import json
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(
            node_id="n1",
            invocation_allowed=True,
            activation_context_status="ready",
            activation_context_evaluated=True,
        )
        json.dumps(d.to_dict())


# ---------------------------------------------------------------------------
# Z) Projection sentinel
# ---------------------------------------------------------------------------


class TestProjectionSentinelPR15:
    @pytest.fixture(autouse=True)
    def _require_fastapi(self):
        pytest.importorskip("fastapi", reason="fastapi not installed")

    def test_sentinel_importable(self):
        from core.routes.projection import NODE_ACTIVATION_CONTEXT_ALIGNED_PR15
        assert isinstance(NODE_ACTIVATION_CONTEXT_ALIGNED_PR15, str)
        assert len(NODE_ACTIVATION_CONTEXT_ALIGNED_PR15) > 0

    def test_sentinel_is_not_unavailable_stub(self):
        from core.routes.projection import NODE_ACTIVATION_CONTEXT_ALIGNED_PR15
        assert "UNAVAILABLE" not in NODE_ACTIVATION_CONTEXT_ALIGNED_PR15

    def test_sentinel_contains_pr15(self):
        from core.routes.projection import NODE_ACTIVATION_CONTEXT_ALIGNED_PR15
        assert "PR15" in NODE_ACTIVATION_CONTEXT_ALIGNED_PR15

    def test_sentinel_mentions_node_activation_context(self):
        from core.routes.projection import NODE_ACTIVATION_CONTEXT_ALIGNED_PR15
        assert "node_activation_context" in NODE_ACTIVATION_CONTEXT_ALIGNED_PR15.lower()
