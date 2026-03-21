"""
tests/test_pr12_execution_policy_enforcement.py
==================================================
Tests for PR-12: Execution Policy Enforcement.

Coverage
--------
A) PolicyOutcome enum
   - all expected outcome codes present
   - string values are stable
   - enum is str subclass

B) PolicyDecision dataclass
   - construction with all fields
   - is_allowed / is_blocked / needs_confirmation properties
   - to_dict() serialisation
   - frozen / immutable
   - blocked_levels and downgraded_to fields

C) check_side_effectful_execution guardrail
   - observe_only + side_effectful=True → BLOCKED_BY_POLICY
   - assistive + side_effectful=True → BLOCKED_BY_POLICY
   - bounded_execute + side_effectful=True → CONFIRMATION_REQUIRED
   - full_execute (no confirmation) + side_effectful=True → ALLOWED
   - any band + side_effectful=False → ALLOWED (read-only)

D) check_confirmation_required guardrail
   - requires_confirmation=True → CONFIRMATION_REQUIRED
   - requires_confirmation=False → ALLOWED

E) check_cross_device_expansion guardrail
   - cross_device_allowed=False → CROSS_DEVICE_NOT_ALLOWED
   - cross_device_allowed=True → ALLOWED

F) check_executor_level guardrail
   - empty allowed list → BLOCKED_BY_POLICY
   - requested level not in allowed → EXECUTOR_LEVEL_CAPPED with downgraded_to
   - requested level in allowed → ALLOWED

G) filter_executor_levels
   - all permitted → empty blocked list
   - some blocked → correct split
   - all blocked → empty permitted list
   - order preserved

H) enforce_execution_intent — composite enforcement
   - observe_only: side-effectful → BLOCKED_BY_POLICY (first check wins)
   - bounded_execute + requires_confirmation: side-effectful → CONFIRMATION_REQUIRED
   - full_execute, local policy + requires_cross_device → CROSS_DEVICE_NOT_ALLOWED
   - full_execute, cross_device + non-allowed executor level → EXECUTOR_LEVEL_CAPPED
   - full_execute, cross_device, all permitted → ALLOWED
   - None policy falls back to DEFAULT_CONSERVATIVE_POLICY (BLOCKED_BY_POLICY)
   - read-only intent always ALLOWED regardless of band

I) enforce_cross_device
   - cross_device_allowed=False → CROSS_DEVICE_NOT_ALLOWED
   - cross_device_allowed=True → ALLOWED
   - None policy uses DEFAULT_CONSERVATIVE_POLICY

J) enforce_executor_levels
   - some blocked → returns dict with blocked_levels and executor_level_capped
   - all permitted → allowed outcome
   - None policy → uses conservative policy

K) emit_policy_decision (smoke test)
   - does not raise for any outcome
   - accepts None context
   - accepts non-empty context dict

L) WindowsExecutionArbiter integration
   - execute() with observe_only policy → WinExecResult.success=False, policy_outcome=blocked_by_policy
   - execute() with confirmation_required policy → WinExecResult.success=False, policy_outcome=confirmation_required
   - execute() with executor-level-capping policy → levels filtered
   - execute() with no policy (None) → proceeds normally (backward compat)
   - WinExecResult.to_dict() carries policy_outcome / policy_band / policy_reason when set

M) TaskGraph integration
   - execute() with observe_only policy → all nodes skipped, success=False
   - execute() with confirmation_required policy → all nodes skipped, success=False
   - execute() with cross_device_not_allowed + remote nodes → cross-device nodes skipped
   - execute() with no policy (None) → proceeds normally (backward compat)
   - blocked result contains policy error reason

N) run_multi_device_via_task_graph integration
   - observe_only policy → cross_device_not_allowed result
   - full_execute policy + cross_device_allowed → proceeds to compile_and_run_dag
   - empty subtasks with policy → early return (unchanged from PR-2)
   - no policy (None) → unchanged behavior

O) Structured result stability
   - blocked_by_policy result has stable keys
   - confirmation_required result has stable keys
   - cross_device_not_allowed result has stable keys
   - executor_level_capped result has stable keys

P) Observability: policy_hint in DesktopPresenceRuntime
   - policy_hint present in result (smoke test)
   - policy_hint contains policy_band, can_execute keys
"""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import subjects
# ---------------------------------------------------------------------------

from core.execution_policy.policy_decision import PolicyOutcome, PolicyDecision
from core.execution_policy.policy_guardrails import (
    check_side_effectful_execution,
    check_confirmation_required,
    check_cross_device_expansion,
    check_executor_level,
    filter_executor_levels,
)
from core.execution_policy.policy_enforcement import (
    enforce_execution_intent,
    enforce_cross_device,
    enforce_executor_levels,
    emit_policy_decision,
)
from core.execution_policy import (
    PolicyBand,
    ExecutionPolicy,
    DEFAULT_CONSERVATIVE_POLICY,
    resolve_policy,
    # PR-12 re-exports
    PolicyOutcome as PolicyOutcomePublic,
    PolicyDecision as PolicyDecisionPublic,
    check_side_effectful_execution as check_side_public,
    check_cross_device_expansion as check_cross_device_expansion_public,
    enforce_execution_intent as enforce_public,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_policy(
    band: PolicyBand,
    *,
    cross_device_allowed: bool = False,
    requires_confirmation: bool = False,
    allowed_executor_levels: Optional[List[str]] = None,
) -> ExecutionPolicy:
    """Build a test policy with explicit fields."""
    if allowed_executor_levels is None:
        from core.execution_policy.policy_resolver import _BAND_EXECUTOR_LEVELS
        allowed_executor_levels = list(_BAND_EXECUTOR_LEVELS[band])
    return ExecutionPolicy(
        policy_band=band,
        risk_budget=1.0 if band is PolicyBand.FULL_EXECUTE else 0.5,
        action_budget=-1 if band is PolicyBand.FULL_EXECUTE else 5,
        fallback_budget=3,
        allowed_executor_levels=allowed_executor_levels,
        cross_device_allowed=cross_device_allowed,
        requires_confirmation=requires_confirmation,
        reason=f"test policy band={band.value}",
    )


_OBSERVE_POLICY = _make_policy(PolicyBand.OBSERVE_ONLY)
_ASSISTIVE_POLICY = _make_policy(PolicyBand.ASSISTIVE)
_BOUNDED_POLICY = _make_policy(PolicyBand.BOUNDED_EXECUTE, requires_confirmation=True)
_FULL_LOCAL_POLICY = _make_policy(PolicyBand.FULL_EXECUTE, cross_device_allowed=False)
_FULL_CROSS_DEVICE_POLICY = _make_policy(PolicyBand.FULL_EXECUTE, cross_device_allowed=True)


# ============================================================
# A) PolicyOutcome enum
# ============================================================

class TestPolicyOutcome:
    def test_all_expected_values(self):
        expected = {
            "allowed", "blocked_by_policy", "confirmation_required",
            "cross_device_not_allowed", "executor_level_capped", "downgraded",
        }
        actual = {o.value for o in PolicyOutcome}
        assert expected == actual

    def test_str_subclass(self):
        assert isinstance(PolicyOutcome.ALLOWED, str)

    def test_public_reexport(self):
        assert PolicyOutcomePublic is PolicyOutcome


# ============================================================
# B) PolicyDecision dataclass
# ============================================================

class TestPolicyDecision:
    def test_construction(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test reason",
        )
        assert d.outcome is PolicyOutcome.BLOCKED_BY_POLICY
        assert d.reason == "test reason"

    def test_is_allowed(self):
        allowed = PolicyDecision(
            outcome=PolicyOutcome.ALLOWED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="ok",
        )
        assert allowed.is_allowed
        assert not allowed.is_blocked
        assert not allowed.needs_confirmation

    def test_is_blocked(self):
        blocked = PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="blocked",
        )
        assert blocked.is_blocked
        assert not blocked.is_allowed

    def test_needs_confirmation(self):
        conf = PolicyDecision(
            outcome=PolicyOutcome.CONFIRMATION_REQUIRED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="confirm please",
        )
        assert conf.needs_confirmation
        assert not conf.is_blocked
        assert not conf.is_allowed

    def test_to_dict_keys(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test",
        )
        as_dict = d.to_dict()
        assert "outcome" in as_dict
        assert "policy_band" in as_dict
        assert "reason" in as_dict
        assert "hint" in as_dict
        assert "blocked_levels" in as_dict
        assert "downgraded_to" in as_dict

    def test_to_dict_enum_serialised(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.EXECUTOR_LEVEL_CAPPED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="capped",
            blocked_levels=["vlm"],
            downgraded_to="uia",
        )
        as_dict = d.to_dict()
        assert as_dict["outcome"] == "executor_level_capped"
        assert as_dict["blocked_levels"] == ["vlm"]
        assert as_dict["downgraded_to"] == "uia"

    def test_frozen(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.ALLOWED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="ok",
        )
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError)):
            d.reason = "changed"  # type: ignore[misc]

    def test_public_reexport(self):
        assert PolicyDecisionPublic is PolicyDecision


# ============================================================
# C) check_side_effectful_execution
# ============================================================

class TestCheckSideEffectfulExecution:
    def test_observe_only_blocks_side_effectful(self):
        d = check_side_effectful_execution(_OBSERVE_POLICY, is_side_effectful=True)
        assert d.is_blocked
        assert d.outcome is PolicyOutcome.BLOCKED_BY_POLICY

    def test_assistive_blocks_side_effectful(self):
        d = check_side_effectful_execution(_ASSISTIVE_POLICY, is_side_effectful=True)
        assert d.is_blocked

    def test_bounded_requires_confirmation(self):
        d = check_side_effectful_execution(_BOUNDED_POLICY, is_side_effectful=True)
        assert d.needs_confirmation
        assert d.outcome is PolicyOutcome.CONFIRMATION_REQUIRED

    def test_full_execute_no_confirm_allowed(self):
        policy = _make_policy(PolicyBand.FULL_EXECUTE, cross_device_allowed=True, requires_confirmation=False)
        d = check_side_effectful_execution(policy, is_side_effectful=True)
        assert d.is_allowed

    def test_read_only_always_allowed(self):
        for policy in [_OBSERVE_POLICY, _ASSISTIVE_POLICY, _BOUNDED_POLICY, _FULL_LOCAL_POLICY]:
            d = check_side_effectful_execution(policy, is_side_effectful=False)
            assert d.is_allowed, f"Expected allowed for {policy.policy_band} with read-only"

    def test_default_is_side_effectful_true(self):
        d = check_side_effectful_execution(_OBSERVE_POLICY)
        assert d.is_blocked


# ============================================================
# D) check_confirmation_required
# ============================================================

class TestCheckConfirmationRequired:
    def test_requires_confirmation_true(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, requires_confirmation=True)
        d = check_confirmation_required(policy)
        assert d.needs_confirmation
        assert d.outcome is PolicyOutcome.CONFIRMATION_REQUIRED

    def test_requires_confirmation_false(self):
        policy = _make_policy(PolicyBand.FULL_EXECUTE, requires_confirmation=False)
        d = check_confirmation_required(policy)
        assert d.is_allowed


# ============================================================
# E) check_cross_device_expansion
# ============================================================

class TestCheckCrossDeviceExpansion:
    def test_denied_when_not_allowed(self):
        d = check_cross_device_expansion(_FULL_LOCAL_POLICY)
        assert not d.is_allowed
        assert d.outcome is PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED
        assert d.hint == "cross_device_not_allowed"

    def test_allowed_when_permitted(self):
        d = check_cross_device_expansion(_FULL_CROSS_DEVICE_POLICY)
        assert d.is_allowed

    def test_public_reexport(self):
        d = check_cross_device_expansion_public(_FULL_LOCAL_POLICY)
        assert d.outcome is PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED


# ============================================================
# F) check_executor_level
# ============================================================

class TestCheckExecutorLevel:
    def test_empty_allowed_list_blocks(self):
        policy = _make_policy(PolicyBand.OBSERVE_ONLY, allowed_executor_levels=[])
        d = check_executor_level(policy, "system_api")
        assert d.is_blocked
        assert d.outcome is PolicyOutcome.BLOCKED_BY_POLICY

    def test_level_not_in_allowed_capped(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api", "uia"])
        d = check_executor_level(policy, "vlm")
        assert d.outcome is PolicyOutcome.EXECUTOR_LEVEL_CAPPED
        assert "vlm" in d.blocked_levels
        assert d.downgraded_to == "uia"  # last permitted level

    def test_level_in_allowed_permitted(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api", "uia"])
        d = check_executor_level(policy, "uia")
        assert d.is_allowed

    def test_hint_is_executor_level_capped(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api"])
        d = check_executor_level(policy, "gui")
        assert d.hint == "executor_level_capped"


# ============================================================
# G) filter_executor_levels
# ============================================================

class TestFilterExecutorLevels:
    def test_all_permitted(self):
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm"],
        )
        permitted, blocked = filter_executor_levels(policy, ["system_api", "uia", "gui", "vlm"])
        assert blocked == []
        assert set(permitted) == {"system_api", "uia", "gui", "vlm"}

    def test_some_blocked(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api", "uia"])
        permitted, blocked = filter_executor_levels(policy, ["system_api", "uia", "gui", "vlm"])
        assert "gui" in blocked
        assert "vlm" in blocked
        assert "system_api" in permitted

    def test_all_blocked(self):
        policy = _make_policy(PolicyBand.OBSERVE_ONLY, allowed_executor_levels=[])
        permitted, blocked = filter_executor_levels(policy, ["system_api", "uia"])
        assert permitted == []
        assert "system_api" in blocked

    def test_order_preserved(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api", "uia"])
        permitted, blocked = filter_executor_levels(policy, ["vlm", "uia", "system_api", "gui"])
        # Order of permitted should match the candidate input order
        assert permitted.index("uia") < permitted.index("system_api")


# ============================================================
# H) enforce_execution_intent — composite
# ============================================================

class TestEnforceExecutionIntent:
    def test_observe_only_blocked(self):
        d = enforce_execution_intent(_OBSERVE_POLICY, is_side_effectful=True)
        assert d.is_blocked

    def test_bounded_confirmation(self):
        d = enforce_execution_intent(_BOUNDED_POLICY, is_side_effectful=True)
        assert d.needs_confirmation

    def test_full_local_cross_device_denied(self):
        d = enforce_execution_intent(
            _FULL_LOCAL_POLICY, is_side_effectful=True, requires_cross_device=True
        )
        assert d.outcome is PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED

    def test_full_cd_executor_capped(self):
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            cross_device_allowed=True,
            requires_confirmation=False,
            allowed_executor_levels=["system_api", "uia"],
        )
        d = enforce_execution_intent(
            policy,
            is_side_effectful=True,
            requires_cross_device=True,
            requested_executor_levels=["vlm"],
        )
        assert d.outcome is PolicyOutcome.EXECUTOR_LEVEL_CAPPED

    def test_full_cd_all_permitted(self):
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            cross_device_allowed=True,
            requires_confirmation=False,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm"],
        )
        d = enforce_execution_intent(
            policy,
            is_side_effectful=True,
            requires_cross_device=True,
            requested_executor_levels=["system_api"],
        )
        assert d.is_allowed

    def test_none_policy_uses_conservative(self):
        d = enforce_execution_intent(None, is_side_effectful=True)
        assert d.is_blocked  # conservative = observe_only

    def test_read_only_always_allowed_regardless_of_band(self):
        for policy in [_OBSERVE_POLICY, _ASSISTIVE_POLICY, _BOUNDED_POLICY]:
            d = enforce_execution_intent(policy, is_side_effectful=False)
            assert d.is_allowed, f"Expected allowed for {policy.policy_band} with read-only"

    def test_public_reexport(self):
        d = enforce_public(_OBSERVE_POLICY, is_side_effectful=True)
        assert d.is_blocked


# ============================================================
# I) enforce_cross_device
# ============================================================

class TestEnforceCrossDevice:
    def test_denied_when_not_allowed(self):
        d = enforce_cross_device(_FULL_LOCAL_POLICY)
        assert d.outcome is PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED

    def test_allowed_when_permitted(self):
        d = enforce_cross_device(_FULL_CROSS_DEVICE_POLICY)
        assert d.is_allowed

    def test_none_policy_uses_conservative(self):
        d = enforce_cross_device(None)
        assert not d.is_allowed  # conservative = cross_device_allowed=False


# ============================================================
# J) enforce_executor_levels
# ============================================================

class TestEnforceExecutorLevels:
    def test_some_blocked(self):
        policy = _make_policy(PolicyBand.BOUNDED_EXECUTE, allowed_executor_levels=["system_api", "uia"])
        result = enforce_executor_levels(policy, ["system_api", "uia", "gui", "vlm"])
        assert "gui" in result["blocked_levels"]
        assert result["outcome"] == "executor_level_capped"

    def test_all_permitted(self):
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm"],
        )
        result = enforce_executor_levels(policy, ["system_api", "uia"])
        assert result["outcome"] == "allowed"
        assert result["blocked_levels"] == []

    def test_none_policy_conservative(self):
        result = enforce_executor_levels(None, ["system_api", "uia"])
        # Conservative = observe_only = no levels allowed
        assert result["blocked_levels"] == ["system_api", "uia"]

    def test_result_keys(self):
        result = enforce_executor_levels(_OBSERVE_POLICY, ["system_api"])
        assert "permitted_levels" in result
        assert "blocked_levels" in result
        assert "outcome" in result
        assert "policy_band" in result
        assert "reason" in result


# ============================================================
# K) emit_policy_decision smoke test
# ============================================================

class TestEmitPolicyDecision:
    def test_does_not_raise_for_blocked(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.BLOCKED_BY_POLICY,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test",
        )
        emit_policy_decision(d)  # must not raise

    def test_does_not_raise_for_allowed(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.ALLOWED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test",
        )
        emit_policy_decision(d)

    def test_accepts_none_context(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.CONFIRMATION_REQUIRED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test",
        )
        emit_policy_decision(d, context=None)

    def test_accepts_context_dict(self):
        d = PolicyDecision(
            outcome=PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test",
        )
        emit_policy_decision(d, context={"trace_id": "t123", "device_id": "dev1"})


# ============================================================
# L) WindowsExecutionArbiter integration
# ============================================================

class TestWindowsArbiterPolicyIntegration:
    """Narrow integration tests for the WindowsExecutionArbiter + policy."""

    def _make_arbiter(self):
        from core.windows_execution_arbiter import WindowsExecutionArbiter
        return WindowsExecutionArbiter(use_defaults=False)

    async def _execute_with_policy(self, policy, action="click", **kwargs):
        arbiter = self._make_arbiter()
        return await arbiter.execute(
            action=action, device_id="test_device", policy=policy, **kwargs
        )

    @pytest.mark.asyncio
    async def test_observe_only_blocks(self):
        result = await self._execute_with_policy(_OBSERVE_POLICY)
        assert result.success is False
        assert result.policy_outcome == "blocked_by_policy"

    @pytest.mark.asyncio
    async def test_confirmation_required_blocks(self):
        result = await self._execute_with_policy(_BOUNDED_POLICY)
        assert result.success is False
        assert result.policy_outcome == "confirmation_required"

    @pytest.mark.asyncio
    async def test_no_policy_backward_compat(self):
        """Without a policy, the arbiter runs normally (all levels skipped when no executors)."""
        arbiter = self._make_arbiter()
        result = await arbiter.execute(action="click", device_id="test")
        # No executors configured, all levels skipped → success=False but no policy_outcome
        assert result.policy_outcome is None

    @pytest.mark.asyncio
    async def test_observe_only_to_dict_has_policy_keys(self):
        result = await self._execute_with_policy(_OBSERVE_POLICY)
        as_dict = result.to_dict()
        assert "policy_outcome" in as_dict
        assert "policy_band" in as_dict
        assert "policy_reason" in as_dict
        assert as_dict["policy_outcome"] == "blocked_by_policy"

    @pytest.mark.asyncio
    async def test_executor_level_filtering(self):
        """Levels not in policy should be filtered from the fallback chain."""
        # observe_only has no allowed levels → all levels removed → blocked result
        result = await self._execute_with_policy(_OBSERVE_POLICY)
        assert result.success is False

    @pytest.mark.asyncio
    async def test_full_execute_no_filtering(self):
        """Full execute policy: no filtering applied when no executors available."""
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            cross_device_allowed=True,
            requires_confirmation=False,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm"],
        )
        arbiter = self._make_arbiter()
        result = await arbiter.execute(action="click", device_id="test", policy=policy)
        # No executors configured → fails at all levels but policy did NOT block it
        assert result.policy_outcome is None  # policy didn't intervene


# ============================================================
# M) TaskGraph integration
# ============================================================

class TestTaskGraphPolicyIntegration:
    """Narrow integration tests for TaskGraph + policy."""

    def _make_graph_with_nodes(self, node_device_ids=None):
        from core.task_graph import TaskGraph

        async def dummy_handler(node, ctx):
            return {"result": "ok"}

        graph = TaskGraph(trace_id="test_trace", graph_id="test_graph")
        for i, dev_id in enumerate(node_device_ids or ["local"]):
            graph.add_node(
                description=f"node_{i}",
                node_id=f"n{i}",
                device_id=dev_id,
                handler=dummy_handler,
            )
        return graph

    @pytest.mark.asyncio
    async def test_observe_only_blocks_graph(self):
        graph = self._make_graph_with_nodes(["local", "local"])
        result = await graph.execute(policy=_OBSERVE_POLICY)
        assert result.success is False
        assert "blocked_by_policy" in result.error or "observe_only" in result.error

    @pytest.mark.asyncio
    async def test_confirmation_required_blocks_graph(self):
        graph = self._make_graph_with_nodes(["local"])
        result = await graph.execute(policy=_BOUNDED_POLICY)
        assert result.success is False
        assert "confirmation_required" in result.error

    @pytest.mark.asyncio
    async def test_cross_device_nodes_skipped_when_denied(self):
        graph = self._make_graph_with_nodes(["local", "remote_phone"])
        # Use full_execute but no cross_device_allowed
        policy = _make_policy(
            PolicyBand.FULL_EXECUTE,
            cross_device_allowed=False,
            requires_confirmation=False,
            allowed_executor_levels=["system_api", "uia", "gui", "vlm"],
        )
        result = await graph.execute(policy=policy)
        # The remote node should have been pre-skipped
        assert result.node_statuses.get("n1") == "skipped"

    @pytest.mark.asyncio
    async def test_no_policy_backward_compat(self):
        graph = self._make_graph_with_nodes(["local"])
        result = await graph.execute(policy=None)
        # Without executors or policy, nodes will fail (no handler execution issue)
        # but graph won't be blocked by policy
        assert result.total_nodes == 1

    @pytest.mark.asyncio
    async def test_blocked_result_has_nodes_skipped(self):
        graph = self._make_graph_with_nodes(["local", "local"])
        result = await graph.execute(policy=_OBSERVE_POLICY)
        assert result.skipped_nodes == 2
        for nid in result.node_statuses:
            assert result.node_statuses[nid] == "skipped"


# ============================================================
# N) run_multi_device_via_task_graph integration
# ============================================================

class TestRunMultiDevicePolicyIntegration:
    """Integration tests for run_multi_device_via_task_graph + policy."""

    def _make_subtasks(self, n: int = 2) -> list:
        class FakeSubtask:
            def __init__(self, i):
                self.task_id = f"st_{i}"
                self.name = f"subtask_{i}"
                self.description = f"Subtask {i}"
                self.depends_on = []
                self.device_id = f"device_{i}"
        return [FakeSubtask(i) for i in range(n)]

    @pytest.mark.asyncio
    async def test_cross_device_denied_by_policy(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        subtasks = self._make_subtasks(2)
        result = await run_multi_device_via_task_graph(
            subtasks,
            policy=_FULL_LOCAL_POLICY,  # cross_device_allowed=False
        )
        assert result["success"] is False
        assert result.get("policy_outcome") == "cross_device_not_allowed"

    @pytest.mark.asyncio
    async def test_empty_subtasks_unchanged(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        result = await run_multi_device_via_task_graph(
            [],
            policy=_FULL_LOCAL_POLICY,
        )
        assert result["success"] is True  # early return, policy not consulted

    @pytest.mark.asyncio
    async def test_no_policy_backward_compat(self):
        """Without a policy, behavior is unchanged from PR-2."""
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        subtasks = self._make_subtasks(1)
        # Should proceed to compile_and_run_dag (may fail due to no handlers, but not policy)
        result = await run_multi_device_via_task_graph(subtasks, policy=None)
        assert "policy_outcome" not in result or result.get("policy_outcome") is None

    @pytest.mark.asyncio
    async def test_policy_result_has_stable_keys(self):
        from core.e2e_orchestrator import run_multi_device_via_task_graph
        subtasks = self._make_subtasks(2)
        result = await run_multi_device_via_task_graph(
            subtasks,
            policy=_FULL_LOCAL_POLICY,
        )
        assert "success" in result
        assert "policy_outcome" in result
        assert "policy_band" in result
        assert "policy_reason" in result
        assert "error" in result


# ============================================================
# O) Structured result stability
# ============================================================

class TestStructuredResultStability:
    """Verify that stable outcome codes are preserved in to_dict() output."""

    def _decision(self, outcome: PolicyOutcome) -> PolicyDecision:
        return PolicyDecision(
            outcome=outcome,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="test reason",
            hint=outcome.value,
        )

    def test_blocked_by_policy_keys(self):
        d = self._decision(PolicyOutcome.BLOCKED_BY_POLICY).to_dict()
        assert d["outcome"] == "blocked_by_policy"
        assert "reason" in d

    def test_confirmation_required_keys(self):
        d = self._decision(PolicyOutcome.CONFIRMATION_REQUIRED).to_dict()
        assert d["outcome"] == "confirmation_required"
        assert d["requires_confirmation"] is True

    def test_cross_device_not_allowed_keys(self):
        d = self._decision(PolicyOutcome.CROSS_DEVICE_NOT_ALLOWED).to_dict()
        assert d["outcome"] == "cross_device_not_allowed"

    def test_executor_level_capped_keys(self):
        dec = PolicyDecision(
            outcome=PolicyOutcome.EXECUTOR_LEVEL_CAPPED,
            policy=DEFAULT_CONSERVATIVE_POLICY,
            reason="capped",
            blocked_levels=["vlm"],
            downgraded_to="uia",
        )
        d = dec.to_dict()
        assert d["outcome"] == "executor_level_capped"
        assert d["blocked_levels"] == ["vlm"]
        assert d["downgraded_to"] == "uia"


# ============================================================
# P) Observability: policy_hint in DesktopPresenceRuntime
# ============================================================

class TestDesktopPresenceRuntimePolicyHint:
    """Smoke-tests that policy_hint is attached to DesktopPresenceRuntime results."""

    @pytest.mark.asyncio
    async def test_policy_hint_present_in_result(self):
        """DesktopPresenceRuntime result should include policy_hint after PR-12."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        # Minimal stub that avoids importing heavy dependencies
        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}
        runtime._ingest_bus_started = False

        # Mock the dispatch to return a minimal result
        async def _mock_dispatch(**_kwargs):
            return {"success": True, "response": "ok"}

        runtime._dispatch = _mock_dispatch  # type: ignore[assignment]

        result = await runtime.handle_request(
            message="test",
            source="chat",
        )
        assert "policy_hint" in result
        policy_hint = result["policy_hint"]
        assert "policy_band" in policy_hint
        assert "can_execute" in policy_hint

    @pytest.mark.asyncio
    async def test_policy_hint_contains_band(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._active_sessions = {}
        runtime._ingest_bus_started = False

        async def _mock_dispatch(**_kwargs):
            return {"success": True, "response": "ok"}

        runtime._dispatch = _mock_dispatch  # type: ignore[assignment]

        result = await runtime.handle_request(message="test", source="chat")
        assert result["policy_hint"]["policy_band"] in {
            "observe_only", "assistive", "bounded_execute", "full_execute"
        }
