#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr11_node_invocation_governance_eligibility.py
==========================================================
PR-11: Enforce Governance Eligibility at Invocation Time.

Covers:
  A) Authority module: sentinels and policies are importable and contain the
     expected identifier strings.

  B) NodeInvocationGovernanceOverride enum has the expected values.

  C) NodeInvocationGovernanceDecision dataclass can be instantiated and
     serialised via to_dict().

  D) evaluate_invocation_governance — COMPAT_INTERNAL override path:
     - invocation_allowed=True, governance_status="override_compat_internal".
     - No registry or governance lookup performed.

  E) evaluate_invocation_governance — unregistered node (not in registry):
     - invocation_allowed=True, governance_status="unregistered_unmanaged".

  F) evaluate_invocation_governance — governance-eligible registered node:
     - invocation_allowed=True, governance_status="eligible".

  G) evaluate_invocation_governance — governance-ineligible registered node:
     - invocation_allowed=False, governance_status="ineligible_denied".
     - denial_reasons reflects the exclusion reason(s).

  H) evaluate_invocation_governance — governance-ineligible archived node:
     - invocation_allowed=False, denial_reasons includes "archived_node".

  I) evaluate_invocation_governance — governance-ineligible unhealthy node:
     - invocation_allowed=False, denial_reasons includes "unhealthy".

  J) evaluate_invocation_governance — registry lookup error: invocation
     proceeds as unregistered_unmanaged (graceful degradation).

  K) build_invocation_denial_diagnostics returns the expected keys/values.

  L) UnifiedNodeExecutor.execute() integration:
     - Ineligible registered node → NodeInvocationResult.success=False,
       eligibility_denial populated, error message contains denial reasons.
     - Eligible registered node → proceeds to execution (does not short-circuit
       before reaching the load/execute step; failure is due to missing files,
       not governance).
     - COMPAT_INTERNAL override on ineligible node → proceeds to execution
       (governance gate bypassed).
     - Unregistered node → proceeds to execution (unmanaged).

  M) NodeInvocationResult.eligibility_denial field is propagated in to_legacy_dict().

  N) NodeInvocationEnvelope.governance_override field is accepted and forwarded.

  O) PR-11 sentinels in node_invocation.py are importable.

  P) Projection.py sentinel NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11 is
     importable and not the UNAVAILABLE stub.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_node_info(
    node_id: str,
    arch_class_value: str = "CAPABILITY_NODE",
    healthy: bool = True,
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
    return mock


def _make_registry(node_info: Optional[Any] = None) -> Any:
    """Create a minimal NodeFabricRegistry-like mock."""
    reg = MagicMock()
    reg.get = MagicMock(return_value=node_info)
    return reg


# ===========================================================================
# A) Authority sentinels
# ===========================================================================

class TestAuthorityModule:
    """The authority module is importable and sentinels contain expected identifiers."""

    def test_authority_sentinel_importable(self) -> None:
        from core.node_invocation_governance import NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY
        assert "PR11_AUTHORITY" in NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY
        assert "UnifiedNodeExecutor" in NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY

    def test_pr11_sentinel_importable(self) -> None:
        from core.node_invocation_governance import NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL
        assert "PR11_SENTINEL" in NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL

    def test_policy_gate_importable(self) -> None:
        from core.node_invocation_governance import GOVERNANCE_GATE_ENFORCED_AT_INVOCATION_TIME_POLICY
        assert "GATE_AT_INVOCATION" in GOVERNANCE_GATE_ENFORCED_AT_INVOCATION_TIME_POLICY

    def test_policy_ineligible_importable(self) -> None:
        from core.node_invocation_governance import INELIGIBLE_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY
        assert "INELIGIBLE_NOT_INVOCABLE" in INELIGIBLE_NODES_CANNOT_BE_CANONICALLY_INVOKED_POLICY

    def test_policy_diagnostics_importable(self) -> None:
        from core.node_invocation_governance import INVOCATION_DENIAL_CARRIES_STRUCTURED_DIAGNOSTICS_POLICY
        assert "DENIAL_DIAGNOSTICS" in INVOCATION_DENIAL_CARRIES_STRUCTURED_DIAGNOSTICS_POLICY

    def test_policy_override_importable(self) -> None:
        from core.node_invocation_governance import OVERRIDE_PATH_IS_EXPLICIT_AUDITABLE_NON_CANONICAL_POLICY
        assert "OVERRIDE_AUDITABLE" in OVERRIDE_PATH_IS_EXPLICIT_AUDITABLE_NON_CANONICAL_POLICY

    def test_policy_unregistered_importable(self) -> None:
        from core.node_invocation_governance import UNREGISTERED_NODES_PROCEED_WITH_UNMANAGED_WARNING_POLICY
        assert "UNREGISTERED_UNMANAGED" in UNREGISTERED_NODES_PROCEED_WITH_UNMANAGED_WARNING_POLICY


# ===========================================================================
# B) NodeInvocationGovernanceOverride enum
# ===========================================================================

class TestGovernanceOverrideEnum:
    """NodeInvocationGovernanceOverride has expected values."""

    def test_none_value(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceOverride
        assert NodeInvocationGovernanceOverride.NONE.value == "none"

    def test_compat_internal_value(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceOverride
        assert NodeInvocationGovernanceOverride.COMPAT_INTERNAL.value == "compat_internal"


# ===========================================================================
# C) NodeInvocationGovernanceDecision dataclass
# ===========================================================================

class TestGovernanceDecisionDataclass:
    """NodeInvocationGovernanceDecision can be instantiated and serialised."""

    def test_instantiation_allowed(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(
            node_id="test-node",
            invocation_allowed=True,
            governance_status="eligible",
        )
        assert d.node_id == "test-node"
        assert d.invocation_allowed is True
        assert d.denial_reasons == []
        assert d.governance_status == "eligible"

    def test_instantiation_denied(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(
            node_id="archived-node",
            invocation_allowed=False,
            denial_reasons=["archived_node"],
            governance_status="ineligible_denied",
        )
        assert d.invocation_allowed is False
        assert "archived_node" in d.denial_reasons

    def test_to_dict_keys(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(
            node_id="n1",
            invocation_allowed=True,
        )
        result = d.to_dict()
        for key in ("node_id", "invocation_allowed", "denial_reasons",
                    "governance_status", "registry_consulted",
                    "governor_consulted", "evaluated_at", "authority"):
            assert key in result, f"Missing key: {key}"

    def test_to_dict_authority_contains_pr11(self) -> None:
        from core.node_invocation_governance import NodeInvocationGovernanceDecision
        d = NodeInvocationGovernanceDecision(node_id="n1", invocation_allowed=True)
        assert "PR11" in d.to_dict()["authority"]


# ===========================================================================
# D) COMPAT_INTERNAL override path
# ===========================================================================

class TestCompatInternalOverride:
    """COMPAT_INTERNAL override bypasses the governance gate entirely."""

    def test_compat_internal_allows_ineligible_node(self) -> None:
        from core.node_invocation_governance import (
            evaluate_invocation_governance,
            NodeInvocationGovernanceOverride,
        )
        # Even with an archived node in the registry, override bypasses the gate
        archived_node = _make_node_info("arc-1", arch_class_value="ARCHIVED_NODE")
        registry = _make_registry(node_info=archived_node)

        decision = evaluate_invocation_governance(
            "arc-1",
            registry=registry,
            override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL,
        )
        assert decision.invocation_allowed is True
        assert decision.governance_status == "override_compat_internal"

    def test_compat_internal_does_not_consult_registry(self) -> None:
        from core.node_invocation_governance import (
            evaluate_invocation_governance,
            NodeInvocationGovernanceOverride,
        )
        registry = _make_registry()
        evaluate_invocation_governance(
            "any-node",
            registry=registry,
            override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL,
        )
        # Registry.get should NOT be called when override is COMPAT_INTERNAL
        registry.get.assert_not_called()

    def test_compat_internal_registry_consulted_false(self) -> None:
        from core.node_invocation_governance import (
            evaluate_invocation_governance,
            NodeInvocationGovernanceOverride,
        )
        decision = evaluate_invocation_governance(
            "some-node",
            override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL,
        )
        assert decision.registry_consulted is False


# ===========================================================================
# E) Unregistered node
# ===========================================================================

class TestUnregisteredNode:
    """Nodes not in the registry proceed as unregistered_unmanaged."""

    def test_unregistered_node_allowed(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        registry = _make_registry(node_info=None)  # returns None → not registered
        decision = evaluate_invocation_governance("ghost-node", registry=registry)
        assert decision.invocation_allowed is True
        assert decision.governance_status == "unregistered_unmanaged"

    def test_unregistered_node_no_denial_reasons(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        registry = _make_registry(node_info=None)
        decision = evaluate_invocation_governance("ghost-node", registry=registry)
        assert decision.denial_reasons == []

    def test_unregistered_node_registry_consulted_true(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        registry = _make_registry(node_info=None)
        decision = evaluate_invocation_governance("ghost-node", registry=registry)
        assert decision.registry_consulted is True


# ===========================================================================
# F) Governance-eligible registered node
# ===========================================================================

class TestEligibleRegisteredNode:
    """Governance-eligible registered nodes are allowed."""

    def test_eligible_capability_node_allowed(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        cap_node = _make_node_info("cap-1", arch_class_value="CAPABILITY_NODE", healthy=True)
        registry = _make_registry(node_info=cap_node)

        decision = evaluate_invocation_governance("cap-1", registry=registry)
        assert decision.invocation_allowed is True
        assert decision.governance_status == "eligible"
        assert decision.denial_reasons == []
        assert decision.registry_consulted is True

    def test_eligible_node_decision_has_diagnostic_context(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        cap_node = _make_node_info("cap-2", arch_class_value="CAPABILITY_NODE", healthy=True)
        registry = _make_registry(node_info=cap_node)

        decision = evaluate_invocation_governance("cap-2", registry=registry)
        assert isinstance(decision.diagnostic_context, dict)


# ===========================================================================
# G) Governance-ineligible registered node (service node)
# ===========================================================================

class TestIneligibleRegisteredNode:
    """Governance-ineligible registered nodes are denied."""

    def test_service_node_denied(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        svc_node = _make_node_info("svc-1", arch_class_value="SERVICE_NODE", healthy=True)
        registry = _make_registry(node_info=svc_node)

        decision = evaluate_invocation_governance("svc-1", registry=registry)
        assert decision.invocation_allowed is False
        assert decision.governance_status == "ineligible_denied"
        assert len(decision.denial_reasons) > 0

    def test_ineligible_node_has_diagnostic_context(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        svc_node = _make_node_info("svc-2", arch_class_value="SERVICE_NODE", healthy=True)
        registry = _make_registry(node_info=svc_node)

        decision = evaluate_invocation_governance("svc-2", registry=registry)
        assert isinstance(decision.diagnostic_context, dict)


# ===========================================================================
# H) Archived node
# ===========================================================================

class TestArchivedNode:
    """Archived nodes are denied with 'archived_node' in denial_reasons."""

    def test_archived_node_denied(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        arc_node = _make_node_info("arc-1", arch_class_value="ARCHIVED_NODE", healthy=True)
        registry = _make_registry(node_info=arc_node)

        decision = evaluate_invocation_governance("arc-1", registry=registry)
        assert decision.invocation_allowed is False
        assert "archived_node" in decision.denial_reasons

    def test_archived_node_governance_status_ineligible(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        arc_node = _make_node_info("arc-2", arch_class_value="ARCHIVED_NODE", healthy=True)
        registry = _make_registry(node_info=arc_node)

        decision = evaluate_invocation_governance("arc-2", registry=registry)
        assert decision.governance_status == "ineligible_denied"


# ===========================================================================
# I) Unhealthy node
# ===========================================================================

class TestUnhealthyNode:
    """Unhealthy nodes are denied with 'unhealthy' in denial_reasons."""

    def test_unhealthy_node_denied(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        sick_node = _make_node_info("sick-1", arch_class_value="CAPABILITY_NODE", healthy=False)
        registry = _make_registry(node_info=sick_node)

        decision = evaluate_invocation_governance("sick-1", registry=registry)
        assert decision.invocation_allowed is False
        assert "unhealthy" in decision.denial_reasons

    def test_unhealthy_node_registry_consulted(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        sick_node = _make_node_info("sick-2", arch_class_value="CAPABILITY_NODE", healthy=False)
        registry = _make_registry(node_info=sick_node)

        decision = evaluate_invocation_governance("sick-2", registry=registry)
        assert decision.registry_consulted is True


# ===========================================================================
# J) Registry lookup error → graceful degradation
# ===========================================================================

class TestRegistryLookupError:
    """If registry.get() raises, the gate falls back to unregistered_unmanaged."""

    def test_registry_error_allows_invocation(self) -> None:
        from core.node_invocation_governance import evaluate_invocation_governance
        registry = MagicMock()
        registry.get = MagicMock(side_effect=RuntimeError("DB error"))

        decision = evaluate_invocation_governance("err-node", registry=registry)
        # Should allow through as unregistered/unmanaged on lookup error
        assert decision.invocation_allowed is True


# ===========================================================================
# K) build_invocation_denial_diagnostics
# ===========================================================================

class TestBuildInvocationDenialDiagnostics:
    """build_invocation_denial_diagnostics returns a well-formed dict."""

    def test_basic_structure(self) -> None:
        from core.node_invocation_governance import (
            NodeInvocationGovernanceDecision,
            build_invocation_denial_diagnostics,
        )
        decision = NodeInvocationGovernanceDecision(
            node_id="denied-1",
            invocation_allowed=False,
            denial_reasons=["archived_node"],
            governance_status="ineligible_denied",
            registry_consulted=True,
            governor_consulted=False,
        )
        payload = build_invocation_denial_diagnostics(decision)
        for key in ("node_id", "denial_reasons", "governance_status",
                    "diagnostic_context", "registry_consulted",
                    "governor_consulted", "denied_at", "sentinel"):
            assert key in payload, f"Missing key: {key}"

    def test_denial_reasons_copied(self) -> None:
        from core.node_invocation_governance import (
            NodeInvocationGovernanceDecision,
            build_invocation_denial_diagnostics,
        )
        decision = NodeInvocationGovernanceDecision(
            node_id="denied-2",
            invocation_allowed=False,
            denial_reasons=["unhealthy", "non_capability_architectural_class"],
            governance_status="ineligible_denied",
        )
        payload = build_invocation_denial_diagnostics(decision)
        assert "unhealthy" in payload["denial_reasons"]
        assert "non_capability_architectural_class" in payload["denial_reasons"]

    def test_sentinel_contains_pr11(self) -> None:
        from core.node_invocation_governance import (
            NodeInvocationGovernanceDecision,
            build_invocation_denial_diagnostics,
        )
        decision = NodeInvocationGovernanceDecision(
            node_id="n",
            invocation_allowed=False,
            denial_reasons=["archived_node"],
            governance_status="ineligible_denied",
        )
        payload = build_invocation_denial_diagnostics(decision)
        assert "PR11" in payload["sentinel"]


# ===========================================================================
# L) UnifiedNodeExecutor.execute() integration
# ===========================================================================

class TestUnifiedNodeExecutorGovernanceGate:
    """UnifiedNodeExecutor.execute() enforces the governance gate."""

    @pytest.mark.asyncio
    async def test_ineligible_node_denied_by_executor(self) -> None:
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor
        from core.node_invocation_governance import NodeInvocationGovernanceOverride

        # Build a registry with an archived node
        arc_node = _make_node_info("arc-exec-1", arch_class_value="ARCHIVED_NODE", healthy=True)
        registry = _make_registry(node_info=arc_node)

        executor = UnifiedNodeExecutor()

        # Patch get_node_fabric_registry to return our mock
        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            return_value=registry,
        ):
            envelope = NodeInvocationEnvelope(
                node_id="arc-exec-1",
                action="test_action",
            )
            result = await executor.execute(envelope)

        assert result.success is False
        assert result.eligibility_denial is not None
        assert "archived_node" in result.eligibility_denial.get("denial_reasons", [])

    @pytest.mark.asyncio
    async def test_eligible_node_proceeds_past_gate(self) -> None:
        """An eligible node passes the gate; failure (if any) is due to missing files."""
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

        cap_node = _make_node_info("cap-exec-1", arch_class_value="CAPABILITY_NODE", healthy=True)
        registry = _make_registry(node_info=cap_node)

        executor = UnifiedNodeExecutor()

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            return_value=registry,
        ):
            envelope = NodeInvocationEnvelope(
                node_id="cap-exec-1",
                action="test_action",
            )
            result = await executor.execute(envelope)

        # Either succeeds (if node dir exists) or fails due to missing directory,
        # but NOT due to governance denial
        assert result.eligibility_denial is None, (
            "Governance denial should not be set for an eligible node"
        )

    @pytest.mark.asyncio
    async def test_compat_internal_override_bypasses_gate(self) -> None:
        """COMPAT_INTERNAL override lets an ineligible node proceed past the gate."""
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor
        from core.node_invocation_governance import NodeInvocationGovernanceOverride

        arc_node = _make_node_info("arc-override-1", arch_class_value="ARCHIVED_NODE")
        registry = _make_registry(node_info=arc_node)

        executor = UnifiedNodeExecutor()

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            return_value=registry,
        ):
            envelope = NodeInvocationEnvelope(
                node_id="arc-override-1",
                action="test_action",
                governance_override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL.value,
            )
            result = await executor.execute(envelope)

        # Must NOT be denied for governance reasons
        assert result.eligibility_denial is None, (
            "COMPAT_INTERNAL override should bypass the governance gate"
        )

    @pytest.mark.asyncio
    async def test_unregistered_node_proceeds_past_gate(self) -> None:
        """Nodes not in the registry are treated as unmanaged and proceed."""
        from core.node_invocation import NodeInvocationEnvelope, UnifiedNodeExecutor

        registry = _make_registry(node_info=None)

        executor = UnifiedNodeExecutor()

        with patch(
            "core.node_invocation_governance.get_node_fabric_registry",
            return_value=registry,
        ):
            envelope = NodeInvocationEnvelope(
                node_id="unregistered-node-xyz",
                action="test_action",
            )
            result = await executor.execute(envelope)

        # Must NOT be denied for governance reasons
        assert result.eligibility_denial is None


# ===========================================================================
# M) eligibility_denial propagated in to_legacy_dict()
# ===========================================================================

class TestEligibilityDenialInLegacyDict:
    """eligibility_denial is present in to_legacy_dict() when populated."""

    def test_eligibility_denial_in_legacy_dict(self) -> None:
        from core.node_invocation import NodeInvocationResult
        denial = {"node_id": "n", "denial_reasons": ["archived_node"]}
        result = NodeInvocationResult(
            success=False,
            node_id="n",
            action="act",
            request_id="req1",
            trace_id="trc1",
            error="governance denied",
            eligibility_denial=denial,
        )
        d = result.to_legacy_dict()
        assert "eligibility_denial" in d
        assert d["eligibility_denial"]["denial_reasons"] == ["archived_node"]

    def test_no_eligibility_denial_when_none(self) -> None:
        from core.node_invocation import NodeInvocationResult
        result = NodeInvocationResult(
            success=True,
            node_id="n",
            action="act",
            request_id="req1",
            trace_id="trc1",
        )
        d = result.to_legacy_dict()
        assert "eligibility_denial" not in d


# ===========================================================================
# N) NodeInvocationEnvelope.governance_override field
# ===========================================================================

class TestEnvelopeGovernanceOverrideField:
    """NodeInvocationEnvelope.governance_override is accepted and defaults to None."""

    def test_default_is_none(self) -> None:
        from core.node_invocation import NodeInvocationEnvelope
        env = NodeInvocationEnvelope(node_id="n", action="act")
        assert env.governance_override is None

    def test_compat_internal_accepted(self) -> None:
        from core.node_invocation import NodeInvocationEnvelope
        from core.node_invocation_governance import NodeInvocationGovernanceOverride
        env = NodeInvocationEnvelope(
            node_id="n",
            action="act",
            governance_override=NodeInvocationGovernanceOverride.COMPAT_INTERNAL.value,
        )
        assert env.governance_override == "compat_internal"


# ===========================================================================
# O) PR-11 sentinels in node_invocation.py
# ===========================================================================

class TestNodeInvocationPR11Sentinels:
    """PR-11 sentinels are importable from core.node_invocation."""

    def test_governance_gate_sentinel(self) -> None:
        from core.node_invocation import (
            GOVERNANCE_ELIGIBILITY_ENFORCED_AT_INVOCATION_TIME_PR11_SENTINEL,
        )
        assert "PR11_SENTINEL" in GOVERNANCE_ELIGIBILITY_ENFORCED_AT_INVOCATION_TIME_PR11_SENTINEL

    def test_ineligible_denied_policy(self) -> None:
        from core.node_invocation import (
            CANONICAL_INVOCATION_DENIES_INELIGIBLE_NODES_PR11_POLICY,
        )
        assert "INELIGIBLE_DENIED_PR11" in CANONICAL_INVOCATION_DENIES_INELIGIBLE_NODES_PR11_POLICY


# ===========================================================================
# P) Projection sentinel
# ===========================================================================

class TestProjectionSentinel:
    """NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11 is importable and not the UNAVAILABLE stub."""

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_importable(self) -> None:
        from core.routes.projection import NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11
        assert "PR11" in NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_is_not_unavailable(self) -> None:
        from core.routes.projection import NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11
        assert "UNAVAILABLE" not in NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11

    @pytest.mark.skipif(
        True,
        reason="projection.py requires fastapi; skip in minimal test environment",
    )
    def test_sentinel_contains_governance_terms(self) -> None:
        from core.routes.projection import NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11
        assert "governance" in NODE_INVOCATION_GOVERNANCE_ALIGNED_PR11.lower()

    def test_authority_module_sentinel_directly(self) -> None:
        """PR-11 authority sentinel can be verified without fastapi."""
        from core.node_invocation_governance import NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL
        assert "PR11_SENTINEL" in NODE_INVOCATION_GOVERNANCE_PR11_SENTINEL

    def test_authority_mentions_governance_gate(self) -> None:
        """PR-11 authority string mentions governance gate."""
        from core.node_invocation_governance import NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY
        assert "UnifiedNodeExecutor" in NODE_INVOCATION_GOVERNANCE_IS_AUTHORITY
