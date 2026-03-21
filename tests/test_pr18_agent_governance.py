#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr18_agent_governance.py
======================================
PR-18: Agent Responsibility Graph & Dispatch Governance

Tests covering:
1.  AgentRole enum — values, serialisation stability
2.  Role capability helpers — can_role_initiate_handoff, can_role_receive_handoff
3.  HANDOFF_GRAPH — structure, valid/invalid edges
4.  is_valid_handoff — expected valid edges, invalid edges
5.  describe_handoff_edge — output format
6.  OwnershipRecord — construction, to_dict, from_dict, round-trip
7.  apply_ownership_transfer — valid transfer, invalid edge, lifecycle guard
8.  HandoffPolicy — construction, to_dict, from_dict, is_depth_exceeded
9.  Pre-built policies — field values
10. get_policy_for_role — all roles return a policy
11. OwnershipSummary — construction, to_dict
12. build_ownership_summary — from record + policy
13. make_ownership_summary — from scalars, unknown role strings
14. attach_ownership_to_projection — additive, non-mutating
15. get_ownership_hints — all expected keys present
16. DispatchSummary — construction, to_dict
17. build_dispatch_summary — success path, failure path, recovery path
18. resolve_dispatch_summary — valid strings, unknown strings, graceful degradation
19. attach_dispatch_summary_to_result — additive, non-mutating
20. attach_dispatch_summary_to_handoff_result — success/failure extraction
21. attach_dispatch_summary_to_projection — additive, non-mutating
22. IDLE_DISPATCH_SUMMARY / IDLE_OWNERSHIP_SUMMARY sentinels
23. Projection route — GET /api/v1/projection/agent-dispatch
24. Graceful degradation when package unavailable
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# 1. AgentRole enum
# ---------------------------------------------------------------------------


class TestAgentRole:
    def test_all_expected_roles_present(self) -> None:
        from core.agent_governance import AgentRole

        expected = {
            "planner",
            "executor",
            "bridge",
            "recovery",
            "observer",
            "local_assistant",
            "remote_specialist",
            "unassigned",
        }
        actual = {r.value for r in AgentRole}
        assert expected == actual

    def test_role_values_are_strings(self) -> None:
        from core.agent_governance import AgentRole

        for role in AgentRole:
            assert isinstance(role.value, str)
            assert role.value  # non-empty

    def test_role_values_stable(self) -> None:
        from core.agent_governance import AgentRole

        assert AgentRole.PLANNER.value == "planner"
        assert AgentRole.EXECUTOR.value == "executor"
        assert AgentRole.BRIDGE.value == "bridge"
        assert AgentRole.RECOVERY.value == "recovery"
        assert AgentRole.OBSERVER.value == "observer"
        assert AgentRole.LOCAL_ASSISTANT.value == "local_assistant"
        assert AgentRole.REMOTE_SPECIALIST.value == "remote_specialist"
        assert AgentRole.UNASSIGNED.value == "unassigned"

    def test_role_is_json_serialisable(self) -> None:
        from core.agent_governance import AgentRole

        serialised = json.dumps([r.value for r in AgentRole])
        restored = json.loads(serialised)
        assert set(restored) == {r.value for r in AgentRole}

    def test_agent_role_description_returns_string(self) -> None:
        from core.agent_governance import AgentRole, agent_role_description

        for role in AgentRole:
            desc = agent_role_description(role)
            assert isinstance(desc, str)
            assert len(desc) > 10  # non-trivial

    def test_precedence_covers_all_roles(self) -> None:
        from core.agent_governance import AgentRole, AGENT_ROLE_PRECEDENCE

        assert set(AGENT_ROLE_PRECEDENCE) == set(AgentRole)
        assert len(AGENT_ROLE_PRECEDENCE) == len(AgentRole)


# ---------------------------------------------------------------------------
# 2. Role capability helpers
# ---------------------------------------------------------------------------


class TestRoleCapabilityHelpers:
    def test_roles_that_can_initiate(self) -> None:
        from core.agent_governance import AgentRole, can_role_initiate_handoff

        can_initiate = {r for r in AgentRole if can_role_initiate_handoff(r)}
        assert AgentRole.PLANNER in can_initiate
        assert AgentRole.EXECUTOR in can_initiate
        assert AgentRole.LOCAL_ASSISTANT in can_initiate
        assert AgentRole.BRIDGE in can_initiate
        # observer and unassigned cannot initiate
        assert AgentRole.OBSERVER not in can_initiate
        assert AgentRole.UNASSIGNED not in can_initiate

    def test_roles_that_can_receive(self) -> None:
        from core.agent_governance import AgentRole, can_role_receive_handoff

        can_receive = {r for r in AgentRole if can_role_receive_handoff(r)}
        assert AgentRole.EXECUTOR in can_receive
        assert AgentRole.REMOTE_SPECIALIST in can_receive
        assert AgentRole.BRIDGE in can_receive
        assert AgentRole.RECOVERY in can_receive
        # planner, observer, unassigned are not targets
        assert AgentRole.PLANNER not in can_receive
        assert AgentRole.OBSERVER not in can_receive

    def test_role_can_initiate_handoff_frozenset(self) -> None:
        from core.agent_governance import AgentRole, ROLE_CAN_INITIATE_HANDOFF

        assert AgentRole.PLANNER in ROLE_CAN_INITIATE_HANDOFF
        assert AgentRole.OBSERVER not in ROLE_CAN_INITIATE_HANDOFF

    def test_role_can_receive_handoff_frozenset(self) -> None:
        from core.agent_governance import AgentRole, ROLE_CAN_RECEIVE_HANDOFF

        assert AgentRole.EXECUTOR in ROLE_CAN_RECEIVE_HANDOFF
        assert AgentRole.OBSERVER not in ROLE_CAN_RECEIVE_HANDOFF


# ---------------------------------------------------------------------------
# 3. HANDOFF_GRAPH structure
# ---------------------------------------------------------------------------


class TestHandoffGraph:
    def test_graph_keys_cover_all_roles(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        assert set(HANDOFF_GRAPH.keys()) == set(AgentRole)

    def test_graph_values_are_frozensets_of_roles(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        for role, targets in HANDOFF_GRAPH.items():
            assert hasattr(targets, "__iter__")
            for t in targets:
                assert isinstance(t, AgentRole), (
                    f"Target {t!r} for {role} is not an AgentRole"
                )

    def test_observer_has_no_outgoing_edges(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        assert len(HANDOFF_GRAPH[AgentRole.OBSERVER]) == 0

    def test_unassigned_has_no_outgoing_edges(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        assert len(HANDOFF_GRAPH[AgentRole.UNASSIGNED]) == 0

    def test_planner_has_expected_targets(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        targets = HANDOFF_GRAPH[AgentRole.PLANNER]
        assert AgentRole.EXECUTOR in targets
        assert AgentRole.BRIDGE in targets
        assert AgentRole.LOCAL_ASSISTANT in targets
        assert AgentRole.REMOTE_SPECIALIST in targets

    def test_recovery_can_only_go_to_executor(self) -> None:
        from core.agent_governance import AgentRole, HANDOFF_GRAPH

        assert HANDOFF_GRAPH[AgentRole.RECOVERY] == frozenset({AgentRole.EXECUTOR})


# ---------------------------------------------------------------------------
# 4. is_valid_handoff
# ---------------------------------------------------------------------------


class TestIsValidHandoff:
    @pytest.mark.parametrize("source,target", [
        ("planner", "executor"),
        ("planner", "bridge"),
        ("planner", "local_assistant"),
        ("planner", "remote_specialist"),
        ("executor", "bridge"),
        ("executor", "remote_specialist"),
        ("executor", "recovery"),
        ("local_assistant", "bridge"),
        ("local_assistant", "remote_specialist"),
        ("local_assistant", "recovery"),
        ("bridge", "executor"),
        ("bridge", "remote_specialist"),
        ("bridge", "recovery"),
        ("recovery", "executor"),
        ("remote_specialist", "recovery"),
    ])
    def test_valid_edges(self, source: str, target: str) -> None:
        from core.agent_governance import AgentRole, is_valid_handoff

        s = AgentRole(source)
        t = AgentRole(target)
        assert is_valid_handoff(s, t), f"Expected {source}→{target} to be valid"

    @pytest.mark.parametrize("source,target", [
        ("observer", "executor"),
        ("observer", "bridge"),
        ("unassigned", "executor"),
        ("planner", "recovery"),  # planner does not directly hand off to recovery
        ("executor", "planner"),  # no back-edges to planner
        ("recovery", "bridge"),   # recovery only goes to executor
    ])
    def test_invalid_edges(self, source: str, target: str) -> None:
        from core.agent_governance import AgentRole, is_valid_handoff

        s = AgentRole(source)
        t = AgentRole(target)
        assert not is_valid_handoff(s, t), f"Expected {source}→{target} to be invalid"


# ---------------------------------------------------------------------------
# 5. describe_handoff_edge
# ---------------------------------------------------------------------------


class TestDescribeHandoffEdge:
    def test_valid_edge_contains_valid(self) -> None:
        from core.agent_governance import AgentRole, describe_handoff_edge

        desc = describe_handoff_edge(AgentRole.PLANNER, AgentRole.EXECUTOR)
        assert "valid" in desc.lower()
        assert "planner" in desc
        assert "executor" in desc

    def test_invalid_edge_contains_invalid(self) -> None:
        from core.agent_governance import AgentRole, describe_handoff_edge

        desc = describe_handoff_edge(AgentRole.OBSERVER, AgentRole.EXECUTOR)
        assert "invalid" in desc.lower()

    def test_recovery_edge_labelled(self) -> None:
        from core.agent_governance import AgentRole, describe_handoff_edge

        desc = describe_handoff_edge(AgentRole.BRIDGE, AgentRole.RECOVERY)
        assert "recovery" in desc.lower()


# ---------------------------------------------------------------------------
# 6. OwnershipRecord — construction, to_dict, from_dict, round-trip
# ---------------------------------------------------------------------------


class TestOwnershipRecord:
    def test_default_construction(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord

        rec = OwnershipRecord()
        assert rec.dispatch_owner == AgentRole.UNASSIGNED
        assert rec.current_owner == AgentRole.UNASSIGNED
        assert rec.final_outcome_owner is None
        assert rec.handoff_count == 0
        assert not rec.is_recovery_active
        assert not rec.is_complete

    def test_to_dict_keys(self) -> None:
        from core.agent_governance import OwnershipRecord

        rec = OwnershipRecord()
        d = rec.to_dict()
        required_keys = {
            "schema_version", "dispatch_owner", "current_owner",
            "final_outcome_owner", "handoff_count", "is_recovery_active",
            "is_complete", "trace_id", "task_id", "last_handoff_reason",
        }
        assert required_keys.issubset(d.keys())

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord

        rec = OwnershipRecord(dispatch_owner=AgentRole.PLANNER, current_owner=AgentRole.EXECUTOR)
        serialised = json.dumps(rec.to_dict())
        assert json.loads(serialised)

    def test_from_dict_round_trip(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord

        rec = OwnershipRecord(
            dispatch_owner=AgentRole.PLANNER,
            current_owner=AgentRole.BRIDGE,
            handoff_count=2,
            is_recovery_active=False,
            trace_id="trace-abc",
            task_id="task-001",
        )
        restored = OwnershipRecord.from_dict(rec.to_dict())
        assert restored.dispatch_owner == AgentRole.PLANNER
        assert restored.current_owner == AgentRole.BRIDGE
        assert restored.handoff_count == 2
        assert restored.trace_id == "trace-abc"
        assert restored.task_id == "task-001"

    def test_from_dict_unknown_role_defaults_to_unassigned(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord

        rec = OwnershipRecord.from_dict({
            "dispatch_owner": "nonexistent_role",
            "current_owner": "also_unknown",
        })
        assert rec.dispatch_owner == AgentRole.UNASSIGNED
        assert rec.current_owner == AgentRole.UNASSIGNED

    def test_from_dict_empty_input(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord

        rec = OwnershipRecord.from_dict({})
        assert rec.dispatch_owner == AgentRole.UNASSIGNED
        assert rec.handoff_count == 0


# ---------------------------------------------------------------------------
# 7. apply_ownership_transfer
# ---------------------------------------------------------------------------


class TestApplyOwnershipTransfer:
    def test_valid_transfer_updates_record(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord, apply_ownership_transfer

        rec = OwnershipRecord(
            dispatch_owner=AgentRole.PLANNER,
            current_owner=AgentRole.PLANNER,
        )
        result = apply_ownership_transfer(rec, AgentRole.EXECUTOR, reason="dispatch")
        assert result.success
        assert result.new_owner == AgentRole.EXECUTOR
        assert rec.current_owner == AgentRole.EXECUTOR
        assert rec.handoff_count == 1

    def test_invalid_edge_does_not_modify_record(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord, apply_ownership_transfer

        rec = OwnershipRecord(
            dispatch_owner=AgentRole.OBSERVER,
            current_owner=AgentRole.OBSERVER,
        )
        original_owner = rec.current_owner
        result = apply_ownership_transfer(rec, AgentRole.EXECUTOR)
        assert not result.success
        assert not result.is_valid_edge
        assert rec.current_owner == original_owner  # not modified
        assert rec.handoff_count == 0

    def test_transfer_to_recovery_sets_flag(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord, apply_ownership_transfer

        rec = OwnershipRecord(current_owner=AgentRole.BRIDGE)
        result = apply_ownership_transfer(rec, AgentRole.RECOVERY)
        assert result.success
        assert result.is_recovery_transition
        assert rec.is_recovery_active

    def test_transfer_blocked_when_lifecycle_complete(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord, apply_ownership_transfer

        rec = OwnershipRecord(
            current_owner=AgentRole.PLANNER,
            is_complete=True,
        )
        result = apply_ownership_transfer(rec, AgentRole.EXECUTOR)
        assert not result.success
        assert "complete" in result.rejection_reason.lower()

    def test_transfer_result_to_dict(self) -> None:
        from core.agent_governance import AgentRole, OwnershipRecord, apply_ownership_transfer

        rec = OwnershipRecord(current_owner=AgentRole.PLANNER)
        result = apply_ownership_transfer(rec, AgentRole.EXECUTOR)
        d = result.to_dict()
        assert "success" in d
        assert "previous_owner" in d
        assert "new_owner" in d


# ---------------------------------------------------------------------------
# 8. HandoffPolicy
# ---------------------------------------------------------------------------


class TestHandoffPolicy:
    def test_default_construction(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy()
        assert policy.ack_required
        assert policy.recovery_permitted
        assert policy.max_handoff_depth == 5
        assert policy.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy()
        d = policy.to_dict()
        assert "ack_required" in d
        assert "recovery_permitted" in d
        assert "max_handoff_depth" in d
        assert "handoff_timeout_hint_ms" in d
        assert "allow_recovery_retry" in d
        assert "policy_reason" in d

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy()
        assert json.loads(json.dumps(policy.to_dict()))

    def test_from_dict_round_trip(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy(
            ack_required=False,
            recovery_permitted=True,
            max_handoff_depth=3,
            handoff_timeout_hint_ms=5000,
            allow_recovery_retry=False,
            policy_reason="custom",
        )
        restored = HandoffPolicy.from_dict(policy.to_dict())
        assert restored.ack_required == policy.ack_required
        assert restored.max_handoff_depth == policy.max_handoff_depth
        assert restored.policy_reason == policy.policy_reason

    def test_from_dict_empty_input(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy.from_dict({})
        assert policy.ack_required  # default
        assert policy.max_handoff_depth == 5  # default

    def test_is_depth_exceeded_false(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy(max_handoff_depth=5)
        assert not policy.is_depth_exceeded(4)
        assert not policy.is_depth_exceeded(0)

    def test_is_depth_exceeded_true(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy(max_handoff_depth=5)
        assert policy.is_depth_exceeded(5)
        assert policy.is_depth_exceeded(10)

    def test_is_depth_exceeded_zero_max(self) -> None:
        from core.agent_governance import HandoffPolicy

        policy = HandoffPolicy(max_handoff_depth=0)
        assert policy.is_depth_exceeded(1)
        assert policy.is_depth_exceeded(0)  # any count exceeds zero limit


# ---------------------------------------------------------------------------
# 9. Pre-built policies
# ---------------------------------------------------------------------------


class TestPreBuiltPolicies:
    def test_default_policy_fields(self) -> None:
        from core.agent_governance import DEFAULT_HANDOFF_POLICY

        assert DEFAULT_HANDOFF_POLICY.ack_required
        assert DEFAULT_HANDOFF_POLICY.recovery_permitted
        assert DEFAULT_HANDOFF_POLICY.max_handoff_depth == 5
        assert DEFAULT_HANDOFF_POLICY.allow_recovery_retry

    def test_recovery_policy_fields(self) -> None:
        from core.agent_governance import RECOVERY_HANDOFF_POLICY

        assert not RECOVERY_HANDOFF_POLICY.ack_required
        assert RECOVERY_HANDOFF_POLICY.recovery_permitted
        assert RECOVERY_HANDOFF_POLICY.max_handoff_depth == 2

    def test_observer_policy_fields(self) -> None:
        from core.agent_governance import OBSERVER_HANDOFF_POLICY

        assert not OBSERVER_HANDOFF_POLICY.recovery_permitted
        assert OBSERVER_HANDOFF_POLICY.max_handoff_depth == 0
        assert not OBSERVER_HANDOFF_POLICY.allow_recovery_retry

    def test_policies_are_immutable(self) -> None:
        from core.agent_governance import DEFAULT_HANDOFF_POLICY
        import dataclasses

        assert dataclasses.fields(DEFAULT_HANDOFF_POLICY)  # is a dataclass
        # frozen=True means direct assignment should raise
        with pytest.raises((AttributeError, TypeError)):
            DEFAULT_HANDOFF_POLICY.max_handoff_depth = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 10. get_policy_for_role
# ---------------------------------------------------------------------------


class TestGetPolicyForRole:
    def test_all_roles_return_a_policy(self) -> None:
        from core.agent_governance import AgentRole, HandoffPolicy, get_policy_for_role

        for role in AgentRole:
            policy = get_policy_for_role(role)
            assert isinstance(policy, HandoffPolicy)

    def test_observer_gets_observer_policy(self) -> None:
        from core.agent_governance import AgentRole, OBSERVER_HANDOFF_POLICY, get_policy_for_role

        assert get_policy_for_role(AgentRole.OBSERVER) is OBSERVER_HANDOFF_POLICY

    def test_recovery_gets_recovery_policy(self) -> None:
        from core.agent_governance import AgentRole, RECOVERY_HANDOFF_POLICY, get_policy_for_role

        assert get_policy_for_role(AgentRole.RECOVERY) is RECOVERY_HANDOFF_POLICY


# ---------------------------------------------------------------------------
# 11. OwnershipSummary
# ---------------------------------------------------------------------------


class TestOwnershipSummary:
    def test_default_construction(self) -> None:
        from core.agent_governance import OwnershipSummary

        summary = OwnershipSummary()
        assert summary.dispatch_owner == "unassigned"
        assert summary.current_owner == "unassigned"
        assert summary.final_outcome_owner is None
        assert summary.handoff_count == 0
        assert not summary.is_recovery_active
        assert not summary.is_complete
        assert summary.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.agent_governance import OwnershipSummary

        summary = OwnershipSummary()
        d = summary.to_dict()
        required = {
            "schema_version", "dispatch_owner", "current_owner",
            "final_outcome_owner", "handoff_count", "is_recovery_active",
            "is_complete", "max_handoff_depth", "depth_exceeded",
            "recovery_permitted", "trace_id", "task_id",
            "last_handoff_reason", "policy_reason",
        }
        assert required.issubset(d.keys())

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.agent_governance import OwnershipSummary

        summary = OwnershipSummary()
        assert json.loads(json.dumps(summary.to_dict()))

    def test_idle_ownership_summary_sentinel(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, OwnershipSummary

        assert isinstance(IDLE_OWNERSHIP_SUMMARY, OwnershipSummary)
        assert IDLE_OWNERSHIP_SUMMARY.dispatch_owner == "unassigned"
        assert IDLE_OWNERSHIP_SUMMARY.handoff_count == 0


# ---------------------------------------------------------------------------
# 12. build_ownership_summary
# ---------------------------------------------------------------------------


class TestBuildOwnershipSummary:
    def test_builds_from_record_and_policy(self) -> None:
        from core.agent_governance import (
            AgentRole,
            OwnershipRecord,
            HandoffPolicy,
            OwnershipSummary,
            build_ownership_summary,
        )

        rec = OwnershipRecord(
            dispatch_owner=AgentRole.PLANNER,
            current_owner=AgentRole.EXECUTOR,
            handoff_count=1,
            trace_id="trace-1",
        )
        policy = HandoffPolicy(max_handoff_depth=3)
        summary = build_ownership_summary(rec, policy)
        assert isinstance(summary, OwnershipSummary)
        assert summary.dispatch_owner == "planner"
        assert summary.current_owner == "executor"
        assert summary.handoff_count == 1
        assert summary.max_handoff_depth == 3
        assert not summary.depth_exceeded
        assert summary.trace_id == "trace-1"

    def test_depth_exceeded_flag(self) -> None:
        from core.agent_governance import (
            AgentRole,
            OwnershipRecord,
            HandoffPolicy,
            build_ownership_summary,
        )

        rec = OwnershipRecord(handoff_count=5)
        policy = HandoffPolicy(max_handoff_depth=5)
        summary = build_ownership_summary(rec, policy)
        assert summary.depth_exceeded

    def test_uses_default_policy_when_none(self) -> None:
        from core.agent_governance import OwnershipRecord, build_ownership_summary

        rec = OwnershipRecord()
        summary = build_ownership_summary(rec, None)
        assert summary.max_handoff_depth == 5  # default policy


# ---------------------------------------------------------------------------
# 13. make_ownership_summary
# ---------------------------------------------------------------------------


class TestMakeOwnershipSummary:
    def test_basic_construction(self) -> None:
        from core.agent_governance import OwnershipSummary, make_ownership_summary

        summary = make_ownership_summary(
            dispatch_owner="planner",
            current_owner="executor",
            trace_id="t1",
        )
        assert isinstance(summary, OwnershipSummary)
        assert summary.dispatch_owner == "planner"
        assert summary.current_owner == "executor"
        assert summary.trace_id == "t1"

    def test_unknown_role_strings_default_to_unassigned(self) -> None:
        from core.agent_governance import make_ownership_summary

        summary = make_ownership_summary(
            dispatch_owner="nonexistent_role",
            current_owner="also_unknown",
        )
        assert summary.dispatch_owner == "unassigned"
        assert summary.current_owner == "unassigned"

    def test_empty_call_returns_valid_summary(self) -> None:
        from core.agent_governance import OwnershipSummary, make_ownership_summary

        summary = make_ownership_summary()
        assert isinstance(summary, OwnershipSummary)


# ---------------------------------------------------------------------------
# 14. attach_ownership_to_projection
# ---------------------------------------------------------------------------


class TestAttachOwnershipToProjection:
    def test_attaches_agent_ownership_key(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, attach_ownership_to_projection

        base = {"tri_state_phase": "ACTIVE"}
        result = attach_ownership_to_projection(base, IDLE_OWNERSHIP_SUMMARY)
        assert "agent_ownership" in result
        assert result["tri_state_phase"] == "ACTIVE"  # original preserved

    def test_does_not_mutate_original(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, attach_ownership_to_projection

        base: Dict[str, Any] = {}
        _ = attach_ownership_to_projection(base, IDLE_OWNERSHIP_SUMMARY)
        assert "agent_ownership" not in base

    def test_non_dict_input_is_treated_as_empty(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, attach_ownership_to_projection

        result = attach_ownership_to_projection(None, IDLE_OWNERSHIP_SUMMARY)  # type: ignore[arg-type]
        assert "agent_ownership" in result


# ---------------------------------------------------------------------------
# 15. get_ownership_hints
# ---------------------------------------------------------------------------


class TestGetOwnershipHints:
    def test_all_expected_keys_present(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, get_ownership_hints

        hints = get_ownership_hints(IDLE_OWNERSHIP_SUMMARY)
        required = {
            "dispatch_owner", "current_owner", "is_recovery_active",
            "is_complete", "depth_exceeded", "handoff_count",
            "has_final_owner", "recovery_permitted",
        }
        assert required.issubset(hints.keys())

    def test_idle_hints_values(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY, get_ownership_hints

        hints = get_ownership_hints(IDLE_OWNERSHIP_SUMMARY)
        assert not hints["is_recovery_active"]
        assert not hints["is_complete"]
        assert not hints["depth_exceeded"]
        assert not hints["has_final_owner"]
        assert hints["recovery_permitted"]


# ---------------------------------------------------------------------------
# 16. DispatchSummary
# ---------------------------------------------------------------------------


class TestDispatchSummary:
    def test_default_construction(self) -> None:
        from core.agent_governance import DispatchSummary

        ds = DispatchSummary()
        assert ds.dispatch_role == "unassigned"
        assert ds.target_role == "unassigned"
        assert not ds.handoff_valid
        assert not ds.dispatch_success
        assert ds.schema_version == 1

    def test_to_dict_keys(self) -> None:
        from core.agent_governance import DispatchSummary

        ds = DispatchSummary()
        d = ds.to_dict()
        required = {
            "schema_version", "dispatch_role", "target_role", "handoff_valid",
            "ownership", "trace_id", "task_id", "bridge_source",
            "dispatch_success", "failure_reason", "policy_reason",
        }
        assert required.issubset(d.keys())

    def test_to_dict_is_json_serialisable(self) -> None:
        from core.agent_governance import DispatchSummary

        ds = DispatchSummary()
        assert json.loads(json.dumps(ds.to_dict()))

    def test_idle_dispatch_summary_sentinel(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, DispatchSummary

        assert isinstance(IDLE_DISPATCH_SUMMARY, DispatchSummary)
        assert IDLE_DISPATCH_SUMMARY.dispatch_role == "unassigned"
        assert not IDLE_DISPATCH_SUMMARY.dispatch_success


# ---------------------------------------------------------------------------
# 17. build_dispatch_summary
# ---------------------------------------------------------------------------


class TestBuildDispatchSummary:
    def test_success_path(self) -> None:
        from core.agent_governance import AgentRole, DispatchSummary, build_dispatch_summary

        ds = build_dispatch_summary(
            dispatch_role=AgentRole.LOCAL_ASSISTANT,
            target_role=AgentRole.REMOTE_SPECIALIST,
            dispatch_success=True,
            trace_id="trace-001",
            task_id="task-001",
            bridge_source="runtime",
        )
        assert isinstance(ds, DispatchSummary)
        assert ds.dispatch_role == "local_assistant"
        assert ds.target_role == "remote_specialist"
        assert ds.dispatch_success
        assert ds.handoff_valid  # local_assistant → remote_specialist is valid
        assert ds.ownership.is_complete
        assert ds.ownership.final_outcome_owner == "remote_specialist"
        assert ds.bridge_source == "runtime"

    def test_failure_path_with_recovery(self) -> None:
        from core.agent_governance import AgentRole, build_dispatch_summary

        ds = build_dispatch_summary(
            dispatch_role=AgentRole.LOCAL_ASSISTANT,
            target_role=AgentRole.REMOTE_SPECIALIST,
            dispatch_success=False,
            failure_reason="timeout",
        )
        assert not ds.dispatch_success
        assert ds.ownership.is_recovery_active
        assert ds.ownership.current_owner == "recovery"

    def test_invalid_edge_flagged(self) -> None:
        from core.agent_governance import AgentRole, build_dispatch_summary

        ds = build_dispatch_summary(
            dispatch_role=AgentRole.OBSERVER,
            target_role=AgentRole.EXECUTOR,
            dispatch_success=False,
        )
        assert not ds.handoff_valid


# ---------------------------------------------------------------------------
# 18. resolve_dispatch_summary
# ---------------------------------------------------------------------------


class TestResolveDispatchSummary:
    def test_valid_strings(self) -> None:
        from core.agent_governance import DispatchSummary, resolve_dispatch_summary

        ds = resolve_dispatch_summary(
            dispatch_role_str="planner",
            target_role_str="executor",
            dispatch_success=True,
        )
        assert isinstance(ds, DispatchSummary)
        assert ds.dispatch_role == "planner"
        assert ds.target_role == "executor"
        assert ds.dispatch_success

    def test_unknown_strings_default_to_unassigned(self) -> None:
        from core.agent_governance import resolve_dispatch_summary

        ds = resolve_dispatch_summary(
            dispatch_role_str="made_up_role",
            target_role_str="also_fake",
        )
        assert ds.dispatch_role == "unassigned"
        assert ds.target_role == "unassigned"

    def test_empty_call_returns_valid_summary(self) -> None:
        from core.agent_governance import DispatchSummary, resolve_dispatch_summary

        ds = resolve_dispatch_summary()
        assert isinstance(ds, DispatchSummary)


# ---------------------------------------------------------------------------
# 19. attach_dispatch_summary_to_result
# ---------------------------------------------------------------------------


class TestAttachDispatchSummaryToResult:
    def test_attaches_agent_governance_key(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_result

        result = {"success": True, "trace_id": "t1"}
        enriched = attach_dispatch_summary_to_result(result, IDLE_DISPATCH_SUMMARY)
        assert "agent_governance" in enriched
        assert enriched["success"]  # original preserved

    def test_does_not_mutate_original(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_result

        result: Dict[str, Any] = {"success": True}
        _ = attach_dispatch_summary_to_result(result, IDLE_DISPATCH_SUMMARY)
        assert "agent_governance" not in result

    def test_non_dict_treated_as_empty(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_result

        enriched = attach_dispatch_summary_to_result(None, IDLE_DISPATCH_SUMMARY)  # type: ignore[arg-type]
        assert "agent_governance" in enriched


# ---------------------------------------------------------------------------
# 20. attach_dispatch_summary_to_handoff_result
# ---------------------------------------------------------------------------


class TestAttachDispatchSummaryToHandoffResult:
    def test_success_handoff_result(self) -> None:
        from core.agent_governance import attach_dispatch_summary_to_handoff_result

        handoff_result = {
            "success": True,
            "trace_id": "trace-001",
            "task_id": "task-001",
            "bridge_source": "runtime",
        }
        enriched = attach_dispatch_summary_to_handoff_result(
            handoff_result,
            dispatch_role_str="local_assistant",
            target_role_str="remote_specialist",
        )
        assert "agent_governance" in enriched
        gov = enriched["agent_governance"]
        assert gov["dispatch_success"]
        assert gov["bridge_source"] == "runtime"
        # original keys preserved
        assert enriched["success"]
        assert enriched["trace_id"] == "trace-001"

    def test_failed_handoff_result(self) -> None:
        from core.agent_governance import attach_dispatch_summary_to_handoff_result

        handoff_result = {
            "success": False,
            "bridge_source": "local_fallback",
            "error": "connection timeout",
        }
        enriched = attach_dispatch_summary_to_handoff_result(handoff_result)
        gov = enriched["agent_governance"]
        assert not gov["dispatch_success"]
        assert gov["ownership"]["is_recovery_active"]

    def test_empty_input(self) -> None:
        from core.agent_governance import attach_dispatch_summary_to_handoff_result

        enriched = attach_dispatch_summary_to_handoff_result({})
        assert "agent_governance" in enriched


# ---------------------------------------------------------------------------
# 21. attach_dispatch_summary_to_projection
# ---------------------------------------------------------------------------


class TestAttachDispatchSummaryToProjection:
    def test_attaches_agent_dispatch_key(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_projection

        base = {"tri_state_phase": "ACTIVE"}
        result = attach_dispatch_summary_to_projection(base, IDLE_DISPATCH_SUMMARY)
        assert "agent_dispatch" in result
        assert result["tri_state_phase"] == "ACTIVE"

    def test_does_not_mutate_original(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_projection

        base: Dict[str, Any] = {}
        _ = attach_dispatch_summary_to_projection(base, IDLE_DISPATCH_SUMMARY)
        assert "agent_dispatch" not in base

    def test_non_dict_treated_as_empty(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, attach_dispatch_summary_to_projection

        result = attach_dispatch_summary_to_projection(None, IDLE_DISPATCH_SUMMARY)  # type: ignore[arg-type]
        assert "agent_dispatch" in result


# ---------------------------------------------------------------------------
# 22. Sentinel values
# ---------------------------------------------------------------------------


class TestSentinels:
    def test_idle_dispatch_summary_is_serialisable(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY

        serialised = json.dumps(IDLE_DISPATCH_SUMMARY.to_dict())
        data = json.loads(serialised)
        assert data["dispatch_role"] == "unassigned"
        assert data["ownership"]["dispatch_owner"] == "unassigned"

    def test_idle_ownership_summary_is_serialisable(self) -> None:
        from core.agent_governance import IDLE_OWNERSHIP_SUMMARY

        serialised = json.dumps(IDLE_OWNERSHIP_SUMMARY.to_dict())
        data = json.loads(serialised)
        assert data["dispatch_owner"] == "unassigned"

    def test_idle_sentinels_frozen(self) -> None:
        from core.agent_governance import IDLE_DISPATCH_SUMMARY, IDLE_OWNERSHIP_SUMMARY

        with pytest.raises((AttributeError, TypeError)):
            IDLE_DISPATCH_SUMMARY.dispatch_role = "planner"  # type: ignore[misc]

        with pytest.raises((AttributeError, TypeError)):
            IDLE_OWNERSHIP_SUMMARY.dispatch_owner = "planner"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 23. Projection route
# ---------------------------------------------------------------------------


class TestAgentDispatchProjectionRoute:
    def test_route_returns_200(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        assert response.status_code == 200

    def test_response_contains_agent_dispatch_key(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        body = response.json()
        assert "agent_dispatch" in body

    def test_response_contains_ownership_hints_key(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        body = response.json()
        assert "ownership_hints" in body

    def test_agent_dispatch_has_required_fields(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        dispatch = response.json().get("agent_dispatch", {})
        required = {
            "dispatch_role", "target_role", "handoff_valid", "ownership",
            "dispatch_success", "policy_reason",
        }
        assert required.issubset(dispatch.keys())

    def test_ownership_hints_has_required_fields(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        hints = response.json().get("ownership_hints", {})
        required = {
            "dispatch_owner", "current_owner", "is_recovery_active",
            "is_complete", "depth_exceeded", "handoff_count",
            "has_final_owner", "recovery_permitted",
        }
        assert required.issubset(hints.keys())

    def test_response_is_json_serialisable(self) -> None:
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        from core.routes.projection import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/projection/agent-dispatch")
        # response.json() already succeeds if this passes
        body = response.json()
        # Re-serialise to confirm full tree is JSON-safe
        assert json.loads(json.dumps(body))


# ---------------------------------------------------------------------------
# 24. Graceful degradation — package unavailability simulation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    def test_resolve_dispatch_summary_never_raises(self) -> None:
        """resolve_dispatch_summary should never propagate exceptions."""
        from core.agent_governance import resolve_dispatch_summary

        # Even bizarre inputs should not raise
        ds = resolve_dispatch_summary(
            dispatch_role_str=None,  # type: ignore[arg-type]
            target_role_str=object(),  # type: ignore[arg-type]
        )
        # Should fall back to idle summary
        assert ds is not None

    def test_attach_handoff_result_with_non_dict_never_raises(self) -> None:
        from core.agent_governance import attach_dispatch_summary_to_handoff_result

        result = attach_dispatch_summary_to_handoff_result("not a dict")  # type: ignore[arg-type]
        assert "agent_governance" in result

    def test_ownership_record_from_dict_with_garbage_never_raises(self) -> None:
        from core.agent_governance import OwnershipRecord

        rec = OwnershipRecord.from_dict({
            "dispatch_owner": 12345,
            "handoff_count": "not_a_number",
        })
        # Defaults should be used gracefully
        assert rec is not None
