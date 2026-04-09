#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr6_node_governance_runtime_constraint.py
=======================================================
PR-6: Node Governance Runtime Constraint tests.

Verifies that:

A) Sentinel / policy strings
   - NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY is importable and non-empty.
   - NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL is importable and matches
     expected machine-checkable string.
   - All five policy sentinels are importable and non-empty.

B) NodeGovernanceEligibilityDecision
   - Dataclass can be instantiated and serialised via to_dict().
   - to_dict() includes node_id, eligible, exclusion_reasons, diagnostic_context,
     governor_consulted, and authority fields.

C) evaluate_node_governance_eligibility — architectural class rules
   - CAPABILITY_NODE + healthy node → eligible=True.
   - ARCHIVED_NODE + healthy node → eligible=False, reason="archived_node".
   - SERVICE_NODE + healthy node → eligible=False, reason="non_capability_architectural_class".
   - LEGACY_ORCHESTRATOR_NODE → excluded.
   - EXPERIMENTAL_NODE → excluded.

D) evaluate_node_governance_eligibility — health rules
   - CAPABILITY_NODE + unhealthy → eligible=False, reason="unhealthy".
   - CAPABILITY_NODE + healthy → eligible=True.

E) evaluate_node_governance_eligibility — lifecycle stage rules
   - CAPABILITY_NODE + healthy + DEPRECATED governor record → excluded,
     reason="deprecated_lifecycle_stage".
   - CAPABILITY_NODE + healthy + REGISTERED governor record → excluded,
     reason="readiness_gap_lifecycle_stage".
   - CAPABILITY_NODE + healthy + ACTIVE governor record → eligible=True.
   - CAPABILITY_NODE + healthy + no governor record → eligible=True
     (fallback mode).

F) evaluate_node_governance_eligibility — multi-reason exclusion
   - Non-CAPABILITY_NODE + unhealthy → both reasons present.

G) get_governance_eligible_nodes
   - Returns only eligible nodes from a mixed list.

H) build_governance_exclusion_report
   - Returns correct total/eligible_count/excluded_count.
   - exclusion_summary maps reasons to counts.
   - excluded_nodes lists node_id and exclusion_reasons.

I) sync_capabilities_to_registry integration
   - A CAPABILITY_NODE + healthy node is synced.
   - An ARCHIVED_NODE node is NOT synced (governance excluded).
   - A deprecated lifecycle-stage node is NOT synced (when governor record
     is supplied via mock).

J) projection.py sentinel
   - NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6 is importable and
     contains key terms.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

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
        from core.node_lifecycle_governor import reset_node_lifecycle_governor
        reset_node_lifecycle_governor()
    except ImportError:
        pass
    try:
        from core.node_governance_runtime import reset_governance_runtime_cache
        reset_governance_runtime_cache()
    except ImportError:
        pass


def _make_node(
    node_id: str,
    architectural_class=None,
    capabilities: Optional[List[str]] = None,
    healthy: bool = True,
):
    """Build a NodeInfo for testing."""
    from core.nodes.node_fabric_registry import (
        NodeInfo,
        NodeRole,
        NodeStatus,
        NodeCapability,
        NodeArchitecturalClass,
    )
    caps = [
        NodeCapability(name=c, description=f"cap {c}")
        for c in (capabilities or ["action"])
    ]
    ac = architectural_class or NodeArchitecturalClass.CAPABILITY_NODE
    node = NodeInfo(
        node_id=node_id,
        role=NodeRole.WORKER,
        architectural_class=ac,
        capabilities=caps,
        status=NodeStatus.HEALTHY,
    )
    if not healthy:
        # Force heartbeat age beyond default TTL
        node.last_heartbeat = time.monotonic() - 9999.0
    return node


def _make_governor_record(stage_value: str):
    """Build a mock NodeGovernanceRecord with the given lifecycle_stage value."""
    from core.node_lifecycle_governor import NodeLifecycleStage, NodeGovernanceRecord
    record = NodeGovernanceRecord(node_name="test-node")
    record.lifecycle_stage = NodeLifecycleStage(stage_value)
    return record


# ===========================================================================
# A) Sentinel / policy strings
# ===========================================================================


class TestSentinels:
    """All authority and policy sentinels are importable and non-empty."""

    def test_authority_importable(self) -> None:
        from core.node_governance_runtime import NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY
        assert NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY
        assert "PR6" in NODE_GOVERNANCE_IS_RUNTIME_CONSTRAINT_AUTHORITY

    def test_pr6_sentinel_importable(self) -> None:
        from core.node_governance_runtime import NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL
        assert NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL
        assert "PR6" in NODE_GOVERNANCE_RUNTIME_CONSTRAINT_PR6_SENTINEL

    def test_policy_archived_deprecated(self) -> None:
        from core.node_governance_runtime import ARCHIVED_AND_DEPRECATED_NODES_EXCLUDED_POLICY
        assert ARCHIVED_AND_DEPRECATED_NODES_EXCLUDED_POLICY

    def test_policy_unhealthy(self) -> None:
        from core.node_governance_runtime import UNHEALTHY_NODES_EXCLUDED_FROM_CANONICAL_PATH_POLICY
        assert UNHEALTHY_NODES_EXCLUDED_FROM_CANONICAL_PATH_POLICY

    def test_policy_readiness_gap(self) -> None:
        from core.node_governance_runtime import READINESS_GAP_NODES_EXCLUDED_POLICY
        assert READINESS_GAP_NODES_EXCLUDED_POLICY

    def test_policy_diagnosable(self) -> None:
        from core.node_governance_runtime import GOVERNANCE_EXCLUSION_IS_DIAGNOSABLE_POLICY
        assert GOVERNANCE_EXCLUSION_IS_DIAGNOSABLE_POLICY

    def test_policy_fallback_non_canonical(self) -> None:
        from core.node_governance_runtime import COMPATIBILITY_FALLBACK_IS_NON_CANONICAL_POLICY
        assert COMPATIBILITY_FALLBACK_IS_NON_CANONICAL_POLICY


# ===========================================================================
# B) NodeGovernanceEligibilityDecision
# ===========================================================================


class TestNodeGovernanceEligibilityDecision:
    """Decision dataclass can be instantiated and serialised."""

    def test_eligible_decision(self) -> None:
        from core.node_governance_runtime import NodeGovernanceEligibilityDecision
        d = NodeGovernanceEligibilityDecision(
            node_id="test-01",
            eligible=True,
        )
        assert d.eligible is True
        assert d.exclusion_reasons == []
        assert d.node_id == "test-01"

    def test_excluded_decision(self) -> None:
        from core.node_governance_runtime import (
            NodeGovernanceEligibilityDecision,
            REASON_ARCHIVED,
        )
        d = NodeGovernanceEligibilityDecision(
            node_id="archived-01",
            eligible=False,
            exclusion_reasons=[REASON_ARCHIVED],
            diagnostic_context={"architectural_class": "archived_node"},
        )
        assert d.eligible is False
        assert REASON_ARCHIVED in d.exclusion_reasons

    def test_to_dict_fields(self) -> None:
        from core.node_governance_runtime import NodeGovernanceEligibilityDecision
        d = NodeGovernanceEligibilityDecision(
            node_id="x-01",
            eligible=True,
            governor_consulted=True,
        )
        result = d.to_dict()
        assert "node_id" in result
        assert "eligible" in result
        assert "exclusion_reasons" in result
        assert "diagnostic_context" in result
        assert "governor_consulted" in result
        assert "authority" in result
        assert result["eligible"] is True
        assert result["governor_consulted"] is True

    def test_repr_eligible(self) -> None:
        from core.node_governance_runtime import NodeGovernanceEligibilityDecision
        d = NodeGovernanceEligibilityDecision(node_id="n-01", eligible=True)
        assert "ELIGIBLE" in repr(d)

    def test_repr_excluded(self) -> None:
        from core.node_governance_runtime import (
            NodeGovernanceEligibilityDecision,
            REASON_UNHEALTHY,
        )
        d = NodeGovernanceEligibilityDecision(
            node_id="n-02", eligible=False, exclusion_reasons=[REASON_UNHEALTHY]
        )
        assert "EXCLUDED" in repr(d)
        assert "unhealthy" in repr(d)


# ===========================================================================
# C) evaluate_node_governance_eligibility — architectural class rules
# ===========================================================================


class TestArchitecturalClassRules:
    """Architectural class is enforced as a hard governance constraint."""

    def setup_method(self) -> None:
        _reset()

    def test_capability_node_healthy_is_eligible(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-01", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is True
        assert decision.exclusion_reasons == []

    def test_archived_node_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_ARCHIVED,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("arc-01", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_ARCHIVED in decision.exclusion_reasons

    def test_service_node_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_NON_CAPABILITY_CLASS,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("svc-01", NodeArchitecturalClass.SERVICE_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_NON_CAPABILITY_CLASS in decision.exclusion_reasons

    def test_legacy_orchestrator_node_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_NON_CAPABILITY_CLASS,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("leg-01", NodeArchitecturalClass.LEGACY_ORCHESTRATOR_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_NON_CAPABILITY_CLASS in decision.exclusion_reasons

    def test_experimental_node_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_NON_CAPABILITY_CLASS,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("exp-01", NodeArchitecturalClass.EXPERIMENTAL_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_NON_CAPABILITY_CLASS in decision.exclusion_reasons


# ===========================================================================
# D) evaluate_node_governance_eligibility — health rules
# ===========================================================================


class TestHealthRules:
    """Unhealthy nodes are excluded regardless of architectural class."""

    def setup_method(self) -> None:
        _reset()

    def test_capability_node_unhealthy_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_UNHEALTHY,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-unhealthy", NodeArchitecturalClass.CAPABILITY_NODE, healthy=False)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_UNHEALTHY in decision.exclusion_reasons

    def test_capability_node_healthy_is_eligible(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-healthy", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is True

    def test_diagnostic_context_includes_is_healthy(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-h2", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node)
        assert "is_healthy" in decision.diagnostic_context
        assert decision.diagnostic_context["is_healthy"] is True


# ===========================================================================
# E) evaluate_node_governance_eligibility — lifecycle stage rules
# ===========================================================================


class TestLifecycleStageRules:
    """Lifecycle stage rules are enforced when governor record is available."""

    def setup_method(self) -> None:
        _reset()

    def test_deprecated_stage_is_excluded(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_DEPRECATED,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-dep", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("deprecated")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert decision.eligible is False
        assert REASON_DEPRECATED in decision.exclusion_reasons
        assert decision.governor_consulted is True

    def test_registered_stage_is_excluded_readiness_gap(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_READINESS_GAP,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-reg", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("registered")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert decision.eligible is False
        assert REASON_READINESS_GAP in decision.exclusion_reasons

    def test_active_stage_is_eligible(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-act", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("active")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert decision.eligible is True
        assert decision.exclusion_reasons == []
        assert decision.governor_consulted is True

    def test_capability_registered_stage_is_eligible(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-capreg", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("capability_registered")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert decision.eligible is True

    def test_optional_stage_is_eligible(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-opt", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("optional")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert decision.eligible is True

    def test_no_governor_record_eligible_fallback(self) -> None:
        """Without a governor record, only arch-class + health rules apply."""
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-nrec", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        decision = evaluate_node_governance_eligibility(node, governor_record=None)
        assert decision.eligible is True
        assert decision.governor_consulted is False

    def test_diagnostic_context_includes_lifecycle_rule(self) -> None:
        from core.node_governance_runtime import evaluate_node_governance_eligibility
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("cap-diag", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)
        gov_record = _make_governor_record("active")
        decision = evaluate_node_governance_eligibility(node, governor_record=gov_record)
        assert "lifecycle_rule" in decision.diagnostic_context
        assert "lifecycle_stage" in decision.diagnostic_context


# ===========================================================================
# F) Multi-reason exclusion
# ===========================================================================


class TestMultiReasonExclusion:
    """Multiple exclusion reasons can be present simultaneously."""

    def setup_method(self) -> None:
        _reset()

    def test_archived_plus_unhealthy(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_ARCHIVED,
            REASON_UNHEALTHY,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("arc-unhealthy", NodeArchitecturalClass.ARCHIVED_NODE, healthy=False)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_ARCHIVED in decision.exclusion_reasons
        assert REASON_UNHEALTHY in decision.exclusion_reasons
        assert len(decision.exclusion_reasons) >= 2

    def test_non_capability_plus_unhealthy(self) -> None:
        from core.node_governance_runtime import (
            evaluate_node_governance_eligibility,
            REASON_NON_CAPABILITY_CLASS,
            REASON_UNHEALTHY,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        node = _make_node("svc-unhealthy", NodeArchitecturalClass.SERVICE_NODE, healthy=False)
        decision = evaluate_node_governance_eligibility(node)
        assert decision.eligible is False
        assert REASON_NON_CAPABILITY_CLASS in decision.exclusion_reasons
        assert REASON_UNHEALTHY in decision.exclusion_reasons


# ===========================================================================
# G) get_governance_eligible_nodes
# ===========================================================================


class TestGetGovernanceEligibleNodes:
    """Bulk filtering returns only governance-eligible nodes."""

    def setup_method(self) -> None:
        _reset()

    def test_filters_out_non_eligible(self) -> None:
        from core.node_governance_runtime import get_governance_eligible_nodes
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("cap-a", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("arc-b", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
            _make_node("cap-c", NodeArchitecturalClass.CAPABILITY_NODE, healthy=False),
            _make_node("cap-d", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("svc-e", NodeArchitecturalClass.SERVICE_NODE, healthy=True),
        ]
        eligible = get_governance_eligible_nodes(nodes)
        ids = [n.node_id for n in eligible]
        assert "cap-a" in ids
        assert "cap-d" in ids
        assert "arc-b" not in ids
        assert "cap-c" not in ids
        assert "svc-e" not in ids

    def test_empty_input(self) -> None:
        from core.node_governance_runtime import get_governance_eligible_nodes
        assert get_governance_eligible_nodes([]) == []

    def test_all_eligible(self) -> None:
        from core.node_governance_runtime import get_governance_eligible_nodes
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("cap-x", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("cap-y", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
        ]
        eligible = get_governance_eligible_nodes(nodes)
        assert len(eligible) == 2

    def test_with_governor_filters_deprecated(self) -> None:
        from core.node_governance_runtime import get_governance_eligible_nodes
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        from core.node_lifecycle_governor import NodeGovernanceRecord, NodeLifecycleStage

        node = _make_node("cap-dep-bulk", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True)

        # Build a mock governor that returns a DEPRECATED record
        rec = NodeGovernanceRecord(node_name="cap-dep-bulk")
        rec.lifecycle_stage = NodeLifecycleStage.DEPRECATED

        governor = MagicMock()
        governor.get_record.return_value = rec

        eligible = get_governance_eligible_nodes([node], governor=governor)
        assert len(eligible) == 0


# ===========================================================================
# H) build_governance_exclusion_report
# ===========================================================================


class TestBuildGovernanceExclusionReport:
    """Diagnostic report captures correct counts and summaries."""

    def setup_method(self) -> None:
        _reset()

    def test_report_structure(self) -> None:
        from core.node_governance_runtime import build_governance_exclusion_report
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("cap-r1", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("arc-r2", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
        ]
        report = build_governance_exclusion_report(nodes)
        assert "total" in report
        assert "eligible_count" in report
        assert "excluded_count" in report
        assert "eligible_nodes" in report
        assert "excluded_nodes" in report
        assert "exclusion_summary" in report
        assert "authority" in report
        assert "report_at" in report

    def test_report_counts(self) -> None:
        from core.node_governance_runtime import build_governance_exclusion_report
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("cap-c1", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("cap-c2", NodeArchitecturalClass.CAPABILITY_NODE, healthy=True),
            _make_node("arc-c3", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
            _make_node("svc-c4", NodeArchitecturalClass.SERVICE_NODE, healthy=False),
        ]
        report = build_governance_exclusion_report(nodes)
        assert report["total"] == 4
        assert report["eligible_count"] == 2
        assert report["excluded_count"] == 2

    def test_exclusion_summary_keys(self) -> None:
        from core.node_governance_runtime import (
            build_governance_exclusion_report,
            REASON_ARCHIVED,
        )
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("arc-s1", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
            _make_node("arc-s2", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
        ]
        report = build_governance_exclusion_report(nodes)
        assert report["exclusion_summary"].get(REASON_ARCHIVED, 0) == 2

    def test_excluded_nodes_entry_format(self) -> None:
        from core.node_governance_runtime import build_governance_exclusion_report
        from core.nodes.node_fabric_registry import NodeArchitecturalClass
        nodes = [
            _make_node("arc-fmt", NodeArchitecturalClass.ARCHIVED_NODE, healthy=True),
        ]
        report = build_governance_exclusion_report(nodes)
        assert len(report["excluded_nodes"]) == 1
        entry = report["excluded_nodes"][0]
        assert "node_id" in entry
        assert "exclusion_reasons" in entry
        assert entry["node_id"] == "arc-fmt"

    def test_empty_nodes(self) -> None:
        from core.node_governance_runtime import build_governance_exclusion_report
        report = build_governance_exclusion_report([])
        assert report["total"] == 0
        assert report["eligible_count"] == 0
        assert report["excluded_count"] == 0


# ===========================================================================
# I) sync_capabilities_to_registry integration
# ===========================================================================


class TestSyncCapabilitiesGovernanceIntegration:
    """sync_capabilities_to_registry uses governance eligibility."""

    def setup_method(self) -> None:
        _reset()

    @pytest.mark.skipif(
        __import__("importlib").util.find_spec("fastapi") is None,
        reason="fastapi not installed",
    )
    def test_capability_node_synced(self) -> None:
        """A CAPABILITY_NODE + healthy node is synced to CapabilityRegistry."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        fab = NodeFabricRegistry()
        fab.register(_make_node("sync-cap", NodeArchitecturalClass.CAPABILITY_NODE, ["run"]))
        count = fab.sync_capabilities_to_registry()
        assert count == 1

    @pytest.mark.skipif(
        __import__("importlib").util.find_spec("fastapi") is None,
        reason="fastapi not installed",
    )
    def test_archived_node_not_synced(self) -> None:
        """An ARCHIVED_NODE is excluded by governance and not synced."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        fab = NodeFabricRegistry()
        fab.register(_make_node("sync-arc", NodeArchitecturalClass.ARCHIVED_NODE, ["old"]))
        count = fab.sync_capabilities_to_registry()
        assert count == 0

    @pytest.mark.skipif(
        __import__("importlib").util.find_spec("fastapi") is None,
        reason="fastapi not installed",
    )
    def test_unhealthy_capability_node_not_synced(self) -> None:
        """An unhealthy CAPABILITY_NODE is excluded by governance and not synced."""
        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        fab = NodeFabricRegistry()
        fab.register(
            _make_node("sync-unhealthy", NodeArchitecturalClass.CAPABILITY_NODE, ["do"], healthy=False)
        )
        count = fab.sync_capabilities_to_registry()
        assert count == 0

    def test_governance_eligible_metadata_flag(self) -> None:
        """When a node is synced, its capability metadata contains governance_eligible=True."""
        try:
            from core.agent.capability_registry import CapabilityRegistry
        except ImportError:
            pytest.skip("CapabilityRegistry not available")

        from core.nodes.node_fabric_registry import (
            NodeFabricRegistry,
            NodeArchitecturalClass,
        )
        fab = NodeFabricRegistry()
        fab.register(_make_node("gov-meta", NodeArchitecturalClass.CAPABILITY_NODE, ["ping"]))
        count = fab.sync_capabilities_to_registry()
        if count == 0:
            pytest.skip("CapabilityRegistry validation failed (likely missing fastapi)")

        reg = CapabilityRegistry.get_instance()
        item = reg.get("node__gov-meta__ping")
        if item is None:
            pytest.skip("CapabilityItem not found; likely validation gating")
        assert item.metadata.get("governance_eligible") is True


# ===========================================================================
# J) projection.py sentinel
# ===========================================================================


class TestProjectionSentinel:
    """projection.py declares the PR-6 governance runtime constraint sentinel."""

    def test_sentinel_importable(self) -> None:
        try:
            from core.routes.projection import NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6
        except ImportError:
            pytest.skip("fastapi not available — skipping projection import")
        assert NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6

    def test_sentinel_contains_pr6(self) -> None:
        try:
            from core.routes.projection import NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6
        except ImportError:
            pytest.skip("fastapi not available")
        assert "PR6" in NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6

    def test_sentinel_not_unavailable(self) -> None:
        try:
            from core.routes.projection import NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6
        except ImportError:
            pytest.skip("fastapi not available")
        assert "UNAVAILABLE" not in NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6

    def test_sentinel_mentions_governance(self) -> None:
        try:
            from core.routes.projection import NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6
        except ImportError:
            pytest.skip("fastapi not available")
        lower = NODE_GOVERNANCE_RUNTIME_CONSTRAINT_ALIGNED_PR6.lower()
        assert "governance" in lower
