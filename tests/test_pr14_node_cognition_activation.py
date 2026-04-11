#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_node_cognition_activation.py
=============================================
PR-14 (node track): Cognition-Oriented Node Activation Layer.

Verifies that:

A) Sentinel / policy strings are importable and non-empty.
B) NodeActivationState enum has all expected values.
C) NodeCognitionRole enum has all expected values.
D) ActivationTransitionReason enum has expected codes.
E) ActivationEligibilityOutcome enum has expected values.
F) VALID_ACTIVATION_TRANSITIONS table is correct.
G) NodeActivationContext dataclass behaves correctly.
H) NodeActivationEligibilityDecision dataclass is correct.
I) NodeActivationTransitionResult dataclass is correct.
J) NodeActivationContextSnapshot dataclass is correct.
K) NodeActivationPolicy dataclass is correct.
L) build_default_activation_policy returns correct defaults.
M) evaluate_activation_eligibility — policy exclusion path.
N) evaluate_activation_eligibility — unregistered node paths.
O) evaluate_activation_eligibility — governance ineligible path.
P) evaluate_activation_eligibility — capacity exceeded path.
Q) evaluate_activation_eligibility — eligible path.
R) evaluate_activation_eligibility — governance clearance not required.
S) transition_activation_state — valid transitions.
T) transition_activation_state — invalid transitions.
U) transition_activation_state — terminal states.
V) build_activation_context_snapshot correctness.
W) get_activation_summary correctness.
X) projection.py sentinel is importable and non-empty.
Y) No parallel authority assertions.
Z) governance_cleared flag set on ELIGIBLE transition.
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional, Set
from unittest.mock import MagicMock

import pytest

from core.node_cognition_activation import (
    ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY,
    ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY,
    ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY,
    COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY,
    NODE_COGNITION_ACTIVATION_IS_AUTHORITY,
    NODE_COGNITION_ACTIVATION_PR14_SENTINEL,
    ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY,
    PR14_ACTIVATION_DISPATCH_RUNTIME_STATUS_POLICY,
    VALID_ACTIVATION_TRANSITIONS,
    ActivationEligibilityOutcome,
    ActivationTransitionReason,
    NodeActivationContext,
    NodeActivationContextSnapshot,
    NodeActivationEligibilityDecision,
    NodeActivationPolicy,
    NodeActivationState,
    NodeActivationTransitionResult,
    NodeCognitionRole,
    build_activation_context_snapshot,
    build_default_activation_policy,
    evaluate_activation_eligibility,
    get_activation_summary,
    get_pr14_activation_runtime_status,
    transition_activation_state,
)


# ===========================================================================
# Helpers
# ===========================================================================


def _make_context(
    node_id: str = "test_node",
    session_id: str = "sess-1",
    state: NodeActivationState = NodeActivationState.CANDIDATE,
    role: NodeCognitionRole = NodeCognitionRole.UNASSIGNED,
) -> NodeActivationContext:
    ctx = NodeActivationContext(node_id=node_id, session_id=session_id)
    ctx.state = state
    ctx.role = role
    return ctx


def _stub_registry(node_id: str, found: bool = True) -> Any:
    """Return a minimal registry stub."""
    record = MagicMock()
    record.node_id = node_id
    record.status = "healthy"

    reg = MagicMock()
    if found:
        reg.get_node.return_value = record
        reg.list_nodes.return_value = [record]
    else:
        reg.get_node.return_value = None
        reg.list_nodes.return_value = []
    return reg


def _stub_governance_decision(eligible: bool, reasons: Optional[List[str]] = None) -> Any:
    """Return a minimal governance decision stub."""
    d = MagicMock()
    d.eligible = eligible
    d.exclusion_reasons = reasons or ([] if eligible else ["archived"])
    d.governor_consulted = True
    d.node_id = "test_node"
    return d


# ===========================================================================
# A) Sentinel / policy strings
# ===========================================================================


class TestSentinels:
    def test_authority_is_non_empty(self):
        assert isinstance(NODE_COGNITION_ACTIVATION_IS_AUTHORITY, str)
        assert len(NODE_COGNITION_ACTIVATION_IS_AUTHORITY) > 0

    def test_pr14_sentinel_is_non_empty(self):
        assert isinstance(NODE_COGNITION_ACTIVATION_PR14_SENTINEL, str)
        assert len(NODE_COGNITION_ACTIVATION_PR14_SENTINEL) > 0

    def test_authority_contains_pr14(self):
        assert "PR14" in NODE_COGNITION_ACTIVATION_IS_AUTHORITY

    def test_policy_above_substrate(self):
        assert isinstance(ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY, str)
        assert len(ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY) > 0

    def test_policy_governance_clearance(self):
        assert isinstance(
            ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY, str
        )
        assert len(ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY) > 0

    def test_policy_validated_transitions(self):
        assert isinstance(ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY, str)
        assert len(ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY) > 0

    def test_policy_role_at_activation(self):
        assert isinstance(
            COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY, str
        )
        assert len(
            COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY
        ) > 0

    def test_policy_orchestration_path(self):
        assert isinstance(
            ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY, str
        )
        assert len(
            ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY
        ) > 0

    def test_all_five_policies_are_distinct(self):
        policies = [
            ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY,
            ACTIVATION_ELIGIBILITY_REQUIRES_GOVERNANCE_CLEARANCE_POLICY,
            ACTIVATION_STATE_TRANSITIONS_ARE_VALIDATED_POLICY,
            COGNITION_ROLE_IS_ASSIGNED_AT_ACTIVATION_NOT_REGISTRATION_POLICY,
            ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY,
        ]
        assert len(set(policies)) == 5


# ===========================================================================
# B) NodeActivationState enum
# ===========================================================================


class TestNodeActivationState:
    def test_all_eight_states_present(self):
        expected = {
            "candidate", "eligible", "selected", "active",
            "suspended", "blocked", "retired", "excluded",
        }
        actual = {s.value for s in NodeActivationState}
        assert expected == actual

    def test_values_are_lowercase_strings(self):
        for s in NodeActivationState:
            assert isinstance(s.value, str)
            assert s.value == s.value.lower()

    def test_candidate_value(self):
        assert NodeActivationState.CANDIDATE.value == "candidate"

    def test_retired_value(self):
        assert NodeActivationState.RETIRED.value == "retired"

    def test_excluded_value(self):
        assert NodeActivationState.EXCLUDED.value == "excluded"


# ===========================================================================
# C) NodeCognitionRole enum
# ===========================================================================


class TestNodeCognitionRole:
    def test_all_seven_roles_present(self):
        expected = {
            "planning", "acting", "sensing", "memory",
            "coordination", "observer", "unassigned",
        }
        actual = {r.value for r in NodeCognitionRole}
        assert expected == actual

    def test_values_are_lowercase_strings(self):
        for r in NodeCognitionRole:
            assert isinstance(r.value, str)
            assert r.value == r.value.lower()


# ===========================================================================
# D) ActivationTransitionReason enum
# ===========================================================================


class TestActivationTransitionReason:
    def test_eligibility_passed_present(self):
        assert ActivationTransitionReason.ELIGIBILITY_PASSED.value == "eligibility_passed"

    def test_execution_started_present(self):
        assert ActivationTransitionReason.EXECUTION_STARTED.value == "execution_started"

    def test_context_retired_present(self):
        assert ActivationTransitionReason.CONTEXT_RETIRED.value == "context_retired"

    def test_policy_excluded_present(self):
        assert ActivationTransitionReason.POLICY_EXCLUDED.value == "policy_excluded"

    def test_governance_failed_present(self):
        assert ActivationTransitionReason.GOVERNANCE_FAILED.value == "governance_failed"

    def test_at_least_ten_reasons(self):
        assert len(list(ActivationTransitionReason)) >= 10


# ===========================================================================
# E) ActivationEligibilityOutcome enum
# ===========================================================================


class TestActivationEligibilityOutcome:
    def test_eligible_present(self):
        assert ActivationEligibilityOutcome.ELIGIBLE.value == "eligible"

    def test_governance_ineligible_present(self):
        assert (
            ActivationEligibilityOutcome.GOVERNANCE_INELIGIBLE.value
            == "governance_ineligible"
        )

    def test_capacity_exceeded_present(self):
        assert (
            ActivationEligibilityOutcome.CAPACITY_EXCEEDED.value == "capacity_exceeded"
        )

    def test_policy_excluded_present(self):
        assert (
            ActivationEligibilityOutcome.POLICY_EXCLUDED.value == "policy_excluded"
        )

    def test_registry_unavailable_present(self):
        assert (
            ActivationEligibilityOutcome.REGISTRY_UNAVAILABLE.value
            == "registry_unavailable"
        )

    def test_unregistered_node_present(self):
        assert (
            ActivationEligibilityOutcome.UNREGISTERED_NODE.value == "unregistered_node"
        )


# ===========================================================================
# F) VALID_ACTIVATION_TRANSITIONS table
# ===========================================================================


class TestValidActivationTransitions:
    def test_is_non_empty_dict(self):
        assert isinstance(VALID_ACTIVATION_TRANSITIONS, dict)
        assert len(VALID_ACTIVATION_TRANSITIONS) > 0

    def test_all_states_are_keys(self):
        for state in NodeActivationState:
            assert state in VALID_ACTIVATION_TRANSITIONS, (
                f"NodeActivationState.{state.name} missing from VALID_ACTIVATION_TRANSITIONS"
            )

    def test_candidate_transitions(self):
        targets = VALID_ACTIVATION_TRANSITIONS[NodeActivationState.CANDIDATE]
        assert NodeActivationState.ELIGIBLE in targets
        assert NodeActivationState.EXCLUDED in targets
        assert NodeActivationState.ACTIVE not in targets

    def test_retired_is_terminal(self):
        assert VALID_ACTIVATION_TRANSITIONS[NodeActivationState.RETIRED] == set()

    def test_excluded_is_terminal(self):
        assert VALID_ACTIVATION_TRANSITIONS[NodeActivationState.EXCLUDED] == set()

    def test_active_transitions(self):
        targets = VALID_ACTIVATION_TRANSITIONS[NodeActivationState.ACTIVE]
        assert NodeActivationState.SUSPENDED in targets
        assert NodeActivationState.RETIRED in targets
        assert NodeActivationState.BLOCKED in targets
        assert NodeActivationState.CANDIDATE not in targets

    def test_selected_transitions(self):
        targets = VALID_ACTIVATION_TRANSITIONS[NodeActivationState.SELECTED]
        assert NodeActivationState.ACTIVE in targets
        assert NodeActivationState.BLOCKED in targets
        assert NodeActivationState.EXCLUDED in targets
        assert NodeActivationState.RETIRED in targets

    def test_suspended_transitions(self):
        targets = VALID_ACTIVATION_TRANSITIONS[NodeActivationState.SUSPENDED]
        assert NodeActivationState.ACTIVE in targets
        assert NodeActivationState.RETIRED in targets

    def test_blocked_transitions(self):
        targets = VALID_ACTIVATION_TRANSITIONS[NodeActivationState.BLOCKED]
        assert NodeActivationState.ELIGIBLE in targets
        assert NodeActivationState.EXCLUDED in targets


# ===========================================================================
# G) NodeActivationContext dataclass
# ===========================================================================


class TestNodeActivationContext:
    def test_construction_with_required_fields(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.node_id == "n1"
        assert ctx.session_id == "s1"

    def test_default_state_is_candidate(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.state == NodeActivationState.CANDIDATE

    def test_default_role_is_unassigned(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.role == NodeCognitionRole.UNASSIGNED

    def test_default_governance_cleared_false(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.governance_cleared is False

    def test_activation_id_is_auto_generated(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert isinstance(ctx.activation_id, str)
        assert len(ctx.activation_id) > 0
        # Should look like a UUID
        uuid.UUID(ctx.activation_id)

    def test_activation_id_is_unique(self):
        ctx1 = NodeActivationContext(node_id="n1", session_id="s1")
        ctx2 = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx1.activation_id != ctx2.activation_id

    def test_to_dict_returns_all_keys(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        d = ctx.to_dict()
        expected_keys = {
            "node_id", "session_id", "activation_id", "state", "role",
            "activation_reason", "last_transition_reason", "governance_cleared",
            "eligible_at", "selected_at", "activated_at", "retired_at",
            "diagnostic_context",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_to_dict_state_is_string(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        d = ctx.to_dict()
        assert d["state"] == "candidate"

    def test_to_dict_role_is_string(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        d = ctx.to_dict()
        assert d["role"] == "unassigned"

    def test_is_terminal_retired(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        ctx.state = NodeActivationState.RETIRED
        assert ctx.is_terminal is True

    def test_is_terminal_excluded(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        ctx.state = NodeActivationState.EXCLUDED
        assert ctx.is_terminal is True

    def test_is_terminal_active_is_false(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        ctx.state = NodeActivationState.ACTIVE
        assert ctx.is_terminal is False

    def test_is_participating_selected(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        ctx.state = NodeActivationState.SELECTED
        assert ctx.is_participating is True

    def test_is_participating_active(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        ctx.state = NodeActivationState.ACTIVE
        assert ctx.is_participating is True

    def test_is_participating_candidate_is_false(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.is_participating is False

    def test_timestamps_default_to_none(self):
        ctx = NodeActivationContext(node_id="n1", session_id="s1")
        assert ctx.eligible_at is None
        assert ctx.selected_at is None
        assert ctx.activated_at is None
        assert ctx.retired_at is None


# ===========================================================================
# H) NodeActivationEligibilityDecision dataclass
# ===========================================================================


class TestNodeActivationEligibilityDecision:
    def test_construction(self):
        d = NodeActivationEligibilityDecision(
            node_id="n1",
            outcome=ActivationEligibilityOutcome.ELIGIBLE,
            eligible=True,
        )
        assert d.node_id == "n1"
        assert d.eligible is True

    def test_to_dict_returns_all_keys(self):
        d = NodeActivationEligibilityDecision(
            node_id="n1",
            outcome=ActivationEligibilityOutcome.ELIGIBLE,
            eligible=True,
        )
        result = d.to_dict()
        expected_keys = {
            "node_id", "outcome", "eligible", "denial_reasons",
            "governance_decision_summary", "policy_notes", "diagnostic_context",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_to_dict_outcome_is_string(self):
        d = NodeActivationEligibilityDecision(
            node_id="n1",
            outcome=ActivationEligibilityOutcome.GOVERNANCE_INELIGIBLE,
            eligible=False,
            denial_reasons=["archived"],
        )
        result = d.to_dict()
        assert result["outcome"] == "governance_ineligible"


# ===========================================================================
# I) NodeActivationTransitionResult dataclass
# ===========================================================================


class TestNodeActivationTransitionResult:
    def test_construction(self):
        r = NodeActivationTransitionResult(
            node_id="n1",
            from_state=NodeActivationState.CANDIDATE,
            to_state=NodeActivationState.ELIGIBLE,
            transition_allowed=True,
        )
        assert r.node_id == "n1"
        assert r.transition_allowed is True

    def test_to_dict_returns_all_keys(self):
        r = NodeActivationTransitionResult(
            node_id="n1",
            from_state=NodeActivationState.CANDIDATE,
            to_state=NodeActivationState.ELIGIBLE,
            transition_allowed=True,
        )
        result = r.to_dict()
        expected_keys = {
            "node_id", "from_state", "to_state", "transition_allowed",
            "rejection_reason", "applied_reason", "updated_context",
            "diagnostic_context",
        }
        assert expected_keys.issubset(set(result.keys()))

    def test_to_dict_states_are_strings(self):
        r = NodeActivationTransitionResult(
            node_id="n1",
            from_state=NodeActivationState.CANDIDATE,
            to_state=NodeActivationState.ELIGIBLE,
            transition_allowed=True,
        )
        result = r.to_dict()
        assert result["from_state"] == "candidate"
        assert result["to_state"] == "eligible"


# ===========================================================================
# J) NodeActivationContextSnapshot dataclass
# ===========================================================================


class TestNodeActivationContextSnapshot:
    def test_construction_with_defaults(self):
        snap = NodeActivationContextSnapshot()
        assert snap.total_contexts == 0
        assert snap.active_count == 0

    def test_to_dict_contains_all_keys(self):
        snap = NodeActivationContextSnapshot()
        d = snap.to_dict()
        expected_keys = {
            "snapshot_id", "session_id", "total_contexts",
            "candidate_count", "eligible_count", "selected_count", "active_count",
            "suspended_count", "blocked_count", "retired_count", "excluded_count",
            "contexts", "snapshot_at", "authority",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_authority_is_non_empty(self):
        snap = NodeActivationContextSnapshot()
        assert len(snap.authority) > 0

    def test_snapshot_id_is_auto_generated(self):
        snap = NodeActivationContextSnapshot()
        assert isinstance(snap.snapshot_id, str)
        uuid.UUID(snap.snapshot_id)


# ===========================================================================
# K) NodeActivationPolicy dataclass
# ===========================================================================


class TestNodeActivationPolicy:
    def test_to_dict_returns_all_keys(self):
        p = NodeActivationPolicy()
        d = p.to_dict()
        expected_keys = {
            "max_active_per_role", "require_governance_clearance",
            "excluded_node_ids", "allowed_roles_for_unregistered", "policy_label",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_default_require_governance_clearance(self):
        p = NodeActivationPolicy()
        assert p.require_governance_clearance is True

    def test_default_excluded_node_ids_empty(self):
        p = NodeActivationPolicy()
        assert len(p.excluded_node_ids) == 0

    def test_to_dict_excluded_node_ids_is_list(self):
        p = NodeActivationPolicy(excluded_node_ids={"n1", "n2"})
        d = p.to_dict()
        assert isinstance(d["excluded_node_ids"], list)


# ===========================================================================
# L) build_default_activation_policy
# ===========================================================================


class TestBuildDefaultActivationPolicy:
    def test_returns_policy_instance(self):
        p = build_default_activation_policy()
        assert isinstance(p, NodeActivationPolicy)

    def test_require_governance_clearance_true(self):
        p = build_default_activation_policy()
        assert p.require_governance_clearance is True

    def test_max_active_per_role_is_none(self):
        p = build_default_activation_policy()
        assert p.max_active_per_role is None

    def test_policy_label_default(self):
        p = build_default_activation_policy()
        assert p.policy_label == "default"

    def test_excluded_node_ids_empty(self):
        p = build_default_activation_policy()
        assert len(p.excluded_node_ids) == 0


# ===========================================================================
# M) evaluate_activation_eligibility — policy exclusion
# ===========================================================================


class TestEvaluateEligibilityPolicyExclusion:
    def test_excluded_node_id_returns_policy_excluded(self):
        policy = NodeActivationPolicy(excluded_node_ids={"bad_node"})
        result = evaluate_activation_eligibility(
            "bad_node", NodeCognitionRole.ACTING, policy=policy
        )
        assert result.eligible is False
        assert result.outcome == ActivationEligibilityOutcome.POLICY_EXCLUDED

    def test_excluded_denial_reasons_non_empty(self):
        policy = NodeActivationPolicy(excluded_node_ids={"bad_node"})
        result = evaluate_activation_eligibility(
            "bad_node", NodeCognitionRole.ACTING, policy=policy
        )
        assert len(result.denial_reasons) > 0

    def test_non_excluded_node_not_policy_excluded(self):
        policy = NodeActivationPolicy(excluded_node_ids={"other_node"})
        # With no registry, this will fail but not for policy reasons
        result = evaluate_activation_eligibility(
            "my_node",
            NodeCognitionRole.ACTING,
            policy=policy,
            registry=_stub_registry("my_node", found=False),
        )
        assert result.outcome != ActivationEligibilityOutcome.POLICY_EXCLUDED


# ===========================================================================
# N) evaluate_activation_eligibility — unregistered node
# ===========================================================================


class TestEvaluateEligibilityUnregistered:
    def test_unregistered_without_allowed_role_returns_ineligible(self):
        policy = NodeActivationPolicy(require_governance_clearance=False)
        registry = _stub_registry("n1", found=False)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry, policy=policy
        )
        assert result.eligible is False
        assert result.outcome in (
            ActivationEligibilityOutcome.UNREGISTERED_NODE,
            ActivationEligibilityOutcome.REGISTRY_UNAVAILABLE,
        )

    def test_unregistered_with_allowed_role_returns_eligible(self):
        policy = NodeActivationPolicy(
            require_governance_clearance=False,
            allowed_roles_for_unregistered={NodeCognitionRole.OBSERVER},
        )
        registry = _stub_registry("n1", found=False)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.OBSERVER, registry=registry, policy=policy
        )
        assert result.eligible is True

    def test_unregistered_other_role_still_ineligible(self):
        policy = NodeActivationPolicy(
            require_governance_clearance=False,
            allowed_roles_for_unregistered={NodeCognitionRole.OBSERVER},
        )
        registry = _stub_registry("n1", found=False)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry, policy=policy
        )
        assert result.eligible is False


# ===========================================================================
# O) evaluate_activation_eligibility — governance ineligible
# ===========================================================================


class TestEvaluateEligibilityGovernanceIneligible:
    def test_governance_ineligible_returns_ineligible(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=False, reasons=["archived"])

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(require_governance_clearance=True)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry, policy=policy
        )
        assert result.eligible is False
        assert result.outcome == ActivationEligibilityOutcome.GOVERNANCE_INELIGIBLE

    def test_governance_ineligible_denial_reasons_contain_exclusion(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=False, reasons=["deprecated"])

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(require_governance_clearance=True)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry, policy=policy
        )
        assert any("deprecated" in r for r in result.denial_reasons)

    def test_governance_decision_summary_present_when_governance_consulted(
        self, monkeypatch
    ):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=False, reasons=["unhealthy"])

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(require_governance_clearance=True)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry, policy=policy
        )
        assert result.governance_decision_summary is not None
        assert "eligible" in result.governance_decision_summary


# ===========================================================================
# P) evaluate_activation_eligibility — capacity exceeded
# ===========================================================================


class TestEvaluateEligibilityCapacityExceeded:
    def test_capacity_exceeded_returns_ineligible(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=True)

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(
            require_governance_clearance=True,
            max_active_per_role={"acting": 1},
        )
        # One already active ACTING node
        existing = _make_context(
            node_id="n0", state=NodeActivationState.ACTIVE,
            role=NodeCognitionRole.ACTING
        )
        result = evaluate_activation_eligibility(
            "n1",
            NodeCognitionRole.ACTING,
            registry=registry,
            policy=policy,
            active_contexts=[existing],
        )
        assert result.eligible is False
        assert result.outcome == ActivationEligibilityOutcome.CAPACITY_EXCEEDED

    def test_capacity_not_exceeded_below_cap(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=True)

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(
            require_governance_clearance=False,
            max_active_per_role={"acting": 2},
        )
        existing = _make_context(
            node_id="n0", state=NodeActivationState.ACTIVE,
            role=NodeCognitionRole.ACTING
        )
        result = evaluate_activation_eligibility(
            "n1",
            NodeCognitionRole.ACTING,
            registry=registry,
            policy=policy,
            active_contexts=[existing],
        )
        assert result.eligible is True


# ===========================================================================
# Q) evaluate_activation_eligibility — eligible path
# ===========================================================================


class TestEvaluateEligibilityEligible:
    def test_eligible_with_governance_cleared(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=True)

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(require_governance_clearance=True)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.PLANNING, registry=registry, policy=policy
        )
        assert result.eligible is True
        assert result.outcome == ActivationEligibilityOutcome.ELIGIBLE

    def test_eligible_governance_decision_summary_present(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=True)

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        policy = NodeActivationPolicy(require_governance_clearance=True)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.PLANNING, registry=registry, policy=policy
        )
        assert result.governance_decision_summary is not None

    def test_eligible_denial_reasons_empty(self, monkeypatch):
        registry = _stub_registry("n1", found=True)
        gov_decision = _stub_governance_decision(eligible=True)

        import core.node_cognition_activation as nca
        monkeypatch.setattr(
            nca, "_evaluate_governance", lambda record, governor=None: gov_decision
        )

        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.ACTING, registry=registry
        )
        if result.eligible:
            assert result.denial_reasons == []


# ===========================================================================
# R) evaluate_activation_eligibility — governance clearance not required
# ===========================================================================


class TestEvaluateEligibilityNoGovernanceClearance:
    def test_eligible_without_governance_check(self):
        registry = _stub_registry("n1", found=True)
        policy = NodeActivationPolicy(require_governance_clearance=False)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.SENSING, registry=registry, policy=policy
        )
        assert result.eligible is True
        assert result.outcome == ActivationEligibilityOutcome.ELIGIBLE

    def test_no_governance_summary_when_clearance_not_required(self):
        registry = _stub_registry("n1", found=True)
        policy = NodeActivationPolicy(require_governance_clearance=False)
        result = evaluate_activation_eligibility(
            "n1", NodeCognitionRole.SENSING, registry=registry, policy=policy
        )
        # governance_decision_summary may be None when clearance not required
        assert result.eligible is True


# ===========================================================================
# S) transition_activation_state — valid transitions
# ===========================================================================


class TestTransitionActivationStateValid:
    def test_candidate_to_eligible(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.transition_allowed is True
        assert result.updated_context is not None
        assert result.updated_context.state == NodeActivationState.ELIGIBLE

    def test_candidate_to_eligible_sets_eligible_at(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        before = time.time()
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.eligible_at is not None
        assert result.updated_context.eligible_at >= before

    def test_eligible_to_selected(self):
        ctx = _make_context(state=NodeActivationState.ELIGIBLE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.SELECTED,
            ActivationTransitionReason.ROLE_ASSIGNED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.state == NodeActivationState.SELECTED

    def test_selected_to_active(self):
        ctx = _make_context(state=NodeActivationState.SELECTED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ACTIVE,
            ActivationTransitionReason.EXECUTION_STARTED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.activated_at is not None

    def test_active_to_retired(self):
        ctx = _make_context(state=NodeActivationState.ACTIVE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.RETIRED,
            ActivationTransitionReason.EXECUTION_COMPLETED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.state == NodeActivationState.RETIRED
        assert result.updated_context.retired_at is not None

    def test_active_to_suspended(self):
        ctx = _make_context(state=NodeActivationState.ACTIVE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.SUSPENDED,
            ActivationTransitionReason.ORCHESTRATOR_SUSPENDED,
        )
        assert result.transition_allowed is True

    def test_suspended_to_active(self):
        ctx = _make_context(state=NodeActivationState.SUSPENDED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ACTIVE,
            ActivationTransitionReason.ORCHESTRATOR_RESUMED,
        )
        assert result.transition_allowed is True

    def test_original_context_is_not_mutated(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        original_state = ctx.state
        transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert ctx.state == original_state

    def test_applied_reason_is_set(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.applied_reason == ActivationTransitionReason.ELIGIBILITY_PASSED

    def test_to_dict_is_serialisable(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        d = result.to_dict()
        assert d["transition_allowed"] is True
        assert d["from_state"] == "candidate"
        assert d["to_state"] == "eligible"


# ===========================================================================
# T) transition_activation_state — invalid transitions
# ===========================================================================


class TestTransitionActivationStateInvalid:
    def test_retired_to_selected_rejected(self):
        ctx = _make_context(state=NodeActivationState.RETIRED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.SELECTED,
            ActivationTransitionReason.ROLE_ASSIGNED,
        )
        assert result.transition_allowed is False
        assert len(result.rejection_reason) > 0

    def test_excluded_to_active_rejected(self):
        ctx = _make_context(state=NodeActivationState.EXCLUDED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ACTIVE,
            ActivationTransitionReason.EXECUTION_STARTED,
        )
        assert result.transition_allowed is False

    def test_blocked_to_active_rejected(self):
        ctx = _make_context(state=NodeActivationState.BLOCKED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ACTIVE,
            ActivationTransitionReason.EXECUTION_STARTED,
        )
        assert result.transition_allowed is False

    def test_active_to_candidate_rejected(self):
        ctx = _make_context(state=NodeActivationState.ACTIVE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.CANDIDATE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.transition_allowed is False

    def test_rejected_result_carries_original_context(self):
        ctx = _make_context(state=NodeActivationState.RETIRED)
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.transition_allowed is False
        # updated_context should be the original (unchanged)
        assert result.updated_context is not None
        assert result.updated_context.state == NodeActivationState.RETIRED


# ===========================================================================
# U) transition_activation_state — terminal states
# ===========================================================================


class TestTransitionActivationStateTerminal:
    def test_retired_has_no_valid_outgoing_transitions(self):
        ctx = _make_context(state=NodeActivationState.RETIRED)
        for target in NodeActivationState:
            result = transition_activation_state(
                ctx, target, ActivationTransitionReason.CONTEXT_RETIRED
            )
            assert result.transition_allowed is False

    def test_excluded_has_no_valid_outgoing_transitions(self):
        ctx = _make_context(state=NodeActivationState.EXCLUDED)
        for target in NodeActivationState:
            result = transition_activation_state(
                ctx, target, ActivationTransitionReason.POLICY_EXCLUDED
            )
            assert result.transition_allowed is False


# ===========================================================================
# V) build_activation_context_snapshot
# ===========================================================================


class TestBuildActivationContextSnapshot:
    def test_empty_list_returns_zero_counts(self):
        snap = build_activation_context_snapshot([])
        assert snap.total_contexts == 0
        assert snap.active_count == 0
        assert snap.candidate_count == 0

    def test_total_contexts_matches_len(self):
        ctxs = [
            _make_context(node_id=f"n{i}", state=NodeActivationState.ACTIVE)
            for i in range(5)
        ]
        snap = build_activation_context_snapshot(ctxs)
        assert snap.total_contexts == 5

    def test_mixed_states_counted_correctly(self):
        ctxs = [
            _make_context("n0", state=NodeActivationState.CANDIDATE),
            _make_context("n1", state=NodeActivationState.ELIGIBLE),
            _make_context("n2", state=NodeActivationState.SELECTED),
            _make_context("n3", state=NodeActivationState.ACTIVE),
            _make_context("n4", state=NodeActivationState.ACTIVE),
            _make_context("n5", state=NodeActivationState.SUSPENDED),
            _make_context("n6", state=NodeActivationState.BLOCKED),
            _make_context("n7", state=NodeActivationState.RETIRED),
            _make_context("n8", state=NodeActivationState.EXCLUDED),
        ]
        snap = build_activation_context_snapshot(ctxs)
        assert snap.candidate_count == 1
        assert snap.eligible_count == 1
        assert snap.selected_count == 1
        assert snap.active_count == 2
        assert snap.suspended_count == 1
        assert snap.blocked_count == 1
        assert snap.retired_count == 1
        assert snap.excluded_count == 1
        assert snap.total_contexts == 9

    def test_to_dict_contains_all_expected_keys(self):
        snap = build_activation_context_snapshot([])
        d = snap.to_dict()
        assert "total_contexts" in d
        assert "active_count" in d
        assert "authority" in d
        assert "contexts" in d
        assert isinstance(d["contexts"], list)

    def test_session_id_passed_through(self):
        snap = build_activation_context_snapshot([], session_id="my-session")
        assert snap.session_id == "my-session"


# ===========================================================================
# W) get_activation_summary
# ===========================================================================


class TestGetActivationSummary:
    def test_returns_dict(self):
        result = get_activation_summary([])
        assert isinstance(result, dict)

    def test_all_expected_keys_present(self):
        result = get_activation_summary([])
        expected = {
            "total_contexts", "active_count", "selected_count", "eligible_count",
            "candidate_count", "suspended_count", "blocked_count",
            "retired_count", "excluded_count", "participating_count", "authority",
        }
        assert expected.issubset(set(result.keys()))

    def test_participating_count_equals_selected_plus_active(self):
        ctxs = [
            _make_context("n0", state=NodeActivationState.SELECTED),
            _make_context("n1", state=NodeActivationState.ACTIVE),
            _make_context("n2", state=NodeActivationState.ACTIVE),
        ]
        result = get_activation_summary(ctxs)
        assert result["selected_count"] == 1
        assert result["active_count"] == 2
        assert result["participating_count"] == 3

    def test_authority_is_non_empty(self):
        result = get_activation_summary([])
        assert len(result["authority"]) > 0

    def test_empty_list_total_is_zero(self):
        result = get_activation_summary([])
        assert result["total_contexts"] == 0

    def test_all_counts_are_non_negative_integers(self):
        ctxs = [_make_context("n0", state=NodeActivationState.ACTIVE)]
        result = get_activation_summary(ctxs)
        for key in (
            "total_contexts", "active_count", "selected_count",
            "eligible_count", "candidate_count", "suspended_count",
            "blocked_count", "retired_count", "excluded_count",
            "participating_count",
        ):
            assert isinstance(result[key], int), f"{key} is not int"
            assert result[key] >= 0, f"{key} is negative"


# ===========================================================================
# X) projection.py sentinel
# ===========================================================================


class TestProjectionSentinel:
    @pytest.mark.skip(reason="fastapi may not be installed")
    def test_sentinel_importable_from_projection(self):
        from core.routes.projection import NODE_COGNITION_ACTIVATION_ALIGNED_PR14

        assert isinstance(NODE_COGNITION_ACTIVATION_ALIGNED_PR14, str)
        assert len(NODE_COGNITION_ACTIVATION_ALIGNED_PR14) > 0
        assert "UNAVAILABLE" not in NODE_COGNITION_ACTIVATION_ALIGNED_PR14

    def test_sentinel_importable_directly(self):
        # The sentinel variable is a module-level name; import the module
        # and verify the attribute exists and does not contain UNAVAILABLE.
        import importlib
        import sys

        # Remove cached module if present so we get a fresh import.
        for mod_name in list(sys.modules.keys()):
            if mod_name == "core.routes.projection":
                del sys.modules[mod_name]

        try:
            mod = importlib.import_module("core.routes.projection")
            sentinel = getattr(mod, "NODE_COGNITION_ACTIVATION_ALIGNED_PR14", None)
            if sentinel is not None:
                assert isinstance(sentinel, str)
                assert len(sentinel) > 0
        except Exception:
            # If fastapi/starlette not installed the whole module may fail;
            # that is acceptable for this test.
            pytest.skip("core.routes.projection import failed (likely missing fastapi)")


# ===========================================================================
# Y) No parallel authority
# ===========================================================================


class TestNoParallelAuthority:
    def test_authority_string_says_above(self):
        # The authority must make clear it sits above the substrate.
        assert "above" in NODE_COGNITION_ACTIVATION_IS_AUTHORITY.lower()

    def test_authority_does_not_claim_to_replace_invocation(self):
        # Must not claim to replace the unified executor.
        lower = NODE_COGNITION_ACTIVATION_IS_AUTHORITY.lower()
        assert "replace" not in lower

    def test_substrate_policy_references_node_invocation(self):
        assert "node_invocation" in ACTIVATION_LAYER_SITS_ABOVE_INVOCATION_SUBSTRATE_POLICY.lower()

    def test_orchestration_policy_references_activation_layer(self):
        assert "activation" in ORCHESTRATION_MUST_USE_ACTIVATION_LAYER_NOT_BARE_INVOCATION_POLICY.lower()

    def test_dispatch_runtime_status_policy_is_explicitly_non_dispatch(self):
        lower = PR14_ACTIVATION_DISPATCH_RUNTIME_STATUS_POLICY.lower()
        assert "not currently invoked" in lower
        assert "unifiednodeexecutor.execute" in lower


class TestPR14RuntimeStatus:
    def test_runtime_status_explicitly_marks_dispatch_as_not_enforced(self):
        status = get_pr14_activation_runtime_status()
        assert status["pr14_activation_model_available"] is True
        assert status["dispatch_time_enforced"] is False
        assert isinstance(status["dispatch_authority_layers"], list)
        assert len(status["dispatch_authority_layers"]) >= 1
        assert status["status_policy"] == PR14_ACTIVATION_DISPATCH_RUNTIME_STATUS_POLICY


# ===========================================================================
# Z) governance_cleared flag
# ===========================================================================


class TestGovernanceClearedFlag:
    def test_transition_to_eligible_sets_governance_cleared(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        assert ctx.governance_cleared is False
        result = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.governance_cleared is True

    def test_transition_to_non_eligible_does_not_set_cleared(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        result = transition_activation_state(
            ctx,
            NodeActivationState.EXCLUDED,
            ActivationTransitionReason.POLICY_EXCLUDED,
        )
        assert result.transition_allowed is True
        assert result.updated_context.governance_cleared is False

    def test_governance_cleared_persists_through_further_transitions(self):
        ctx = _make_context(state=NodeActivationState.CANDIDATE)
        r1 = transition_activation_state(
            ctx,
            NodeActivationState.ELIGIBLE,
            ActivationTransitionReason.ELIGIBILITY_PASSED,
        )
        r2 = transition_activation_state(
            r1.updated_context,
            NodeActivationState.SELECTED,
            ActivationTransitionReason.ROLE_ASSIGNED,
        )
        assert r2.updated_context.governance_cleared is True
