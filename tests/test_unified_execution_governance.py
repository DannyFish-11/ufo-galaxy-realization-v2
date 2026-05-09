"""tests/test_unified_execution_governance.py
=============================================
Tests for the Unified Execution Governance Contract.

Coverage groups
---------------
A.  Module imports — authority sentinels, enums, dataclasses, functions all
    importable from ``core.unified_execution_governance``.
B.  ``ExecutionType`` enum — all values, from_string(), unknown fallback.
C.  ``ExecutionPriority`` — numeric ordering: takeover < parallel = goal.
D.  ``CancellationReason`` enum — all values present.
E.  ``RollbackPolicy`` enum — all values present.
F.  ``TimeoutPolicy`` enum — all values present.
G.  ``FailureSemantic`` enum — all values present.
H.  ``ConflictResolution`` enum — all values present.
I.  ``get_execution_type_policy()`` — returns correct policy per type; None for unknown.
J.  ``ExecutionTypePolicy.to_dict()`` — all fields present and serialisable.
K.  ``ExecutionGovernanceVerdict.to_dict()`` — all fields present.
L.  ``evaluate_execution_governance()`` — accepted when no conflicts and gates pass.
M.  ``evaluate_execution_governance()`` — rejected when mode gate fails.
N.  ``evaluate_execution_governance()`` — goal_execution rejected when active takeover.
O.  ``evaluate_execution_governance()`` — parallel_subtask rejected when active takeover.
P.  ``evaluate_execution_governance()`` — takeover NOT blocked by goal_execution.
Q.  ``evaluate_execution_governance()`` — concurrent limit enforced per type.
R.  ``evaluate_execution_governance()`` — skip_conflict_check bypasses conflict.
S.  ``evaluate_execution_governance()`` — register_if_accepted=False does not track.
T.  ``is_takeover_active()`` — True after takeover accepted; False after notify_completed.
U.  ``get_active_execution_type()`` — returns highest-priority type.
V.  ``notify_execution_completed()`` — returns True when found; False when not.
W.  ``resolve_execution_conflict()`` — takeover beats goal_execution.
X.  ``resolve_execution_conflict()`` — goal_execution vs parallel_subtask (same priority → reject_incoming FIFO).
Y.  ``resolve_execution_conflict()`` — goal_execution incoming vs active takeover → reject_incoming.
Z.  Multi-type conflict scenario: takeover → goal_execution → parallel_subtask sequence.
AA. ``ExecutionConflict.to_dict()`` — all fields present.
AB. ``ConflictResolutionResult.to_dict()`` — all fields present.
AC. ``evaluate_execution_governance()`` — unknown type → rejected with policy-not-found reason.
AD. Policy: takeover has blocks_lower_priority=True; goal/parallel do not.
AE. Policy: takeover max_concurrent_per_device=1; goal=3; parallel=5.
AF. Policy: takeover rollback_on_cancel=required_undo; goal/parallel=notify_only.
AG. Policy: takeover default_timeout_s > goal > parallel (numeric values).
AH. ``_clear_all_active_executions()`` resets tracking for test isolation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.unified_execution_governance import (
    # Sentinels
    UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY,
    UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
    UNIFIED_EXECUTION_GOVERNANCE_SENTINEL,
    TAKEOVER_BLOCKS_LOWER_PRIORITY,
    PRIORITY_ORDER_POLICY,
    CANCELLATION_PROPAGATION_POLICY,
    ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS,
    STALE_ANDROID_RUNTIME_TRUTH_DOWNGRADES_AUTHORITY_POLICY,
    # Enums
    ExecutionType,
    ExecutionPriority,
    CancellationReason,
    RollbackPolicy,
    TimeoutPolicy,
    FailureSemantic,
    ConflictResolution,
    # Dataclasses
    ExecutionGovernanceVerdict,
    ExecutionConflict,
    ConflictResolutionResult,
    # Functions
    get_execution_type_policy,
    evaluate_execution_governance,
    resolve_execution_conflict,
    is_takeover_active,
    get_active_execution_type,
    get_execution_runtime_snapshot,
    notify_execution_completed,
    _clear_all_active_executions,
    _clear_active_executions_for_device,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_active_executions():
    """Ensure active execution registry is clean before and after each test."""
    _clear_all_active_executions()
    yield
    _clear_all_active_executions()


def _patch_mode_gate_pass(execution_type: ExecutionType = ExecutionType.goal_execution):
    """Return a patch context that makes mode gate evaluation return 'pass'."""
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(True, [], "all gates pass"),
    )


def _patch_mode_gate_fail(reason: str = "test gate fail"):
    """Return a patch context that makes mode gate evaluation return 'fail'."""
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(False, ["android_cross_device_enabled"], reason),
    )


# ---------------------------------------------------------------------------
# A. Module imports
# ---------------------------------------------------------------------------

class TestModuleImports:
    def test_authority_sentinel_importable(self):
        assert UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY
        assert "unified_execution_governance" in UNIFIED_EXECUTION_GOVERNANCE_AUTHORITY.lower()

    def test_contract_version_importable(self):
        assert UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION == "1.0.0"

    def test_pr_sentinel_importable(self):
        assert "v1 present" in UNIFIED_EXECUTION_GOVERNANCE_SENTINEL

    def test_policy_sentinels_importable(self):
        assert TAKEOVER_BLOCKS_LOWER_PRIORITY
        assert PRIORITY_ORDER_POLICY
        assert CANCELLATION_PROPAGATION_POLICY
        assert STALE_ANDROID_RUNTIME_TRUTH_DOWNGRADES_AUTHORITY_POLICY


# ---------------------------------------------------------------------------
# B. ExecutionType enum
# ---------------------------------------------------------------------------

class TestExecutionTypeEnum:
    def test_all_values_present(self):
        values = {e.value for e in ExecutionType}
        assert "goal_execution" in values
        assert "parallel_subtask" in values
        assert "takeover_request" in values
        assert "unknown" in values

    def test_from_string_goal_execution(self):
        assert ExecutionType.from_string("goal_execution") == ExecutionType.goal_execution

    def test_from_string_parallel_subtask(self):
        assert ExecutionType.from_string("parallel_subtask") == ExecutionType.parallel_subtask

    def test_from_string_takeover_request(self):
        assert ExecutionType.from_string("takeover_request") == ExecutionType.takeover_request

    def test_from_string_unknown_fallback(self):
        assert ExecutionType.from_string("nonexistent_type") == ExecutionType.unknown

    def test_from_string_empty_string_fallback(self):
        assert ExecutionType.from_string("") == ExecutionType.unknown


# ---------------------------------------------------------------------------
# C. ExecutionPriority — numeric ordering
# ---------------------------------------------------------------------------

class TestExecutionPriority:
    def test_takeover_highest_priority(self):
        assert ExecutionPriority.PRIORITY_1_TAKEOVER < ExecutionPriority.PRIORITY_2_GOAL

    def test_goal_and_parallel_equal_priority(self):
        assert ExecutionPriority.PRIORITY_2_GOAL == ExecutionPriority.PRIORITY_2_PARALLEL

    def test_unknown_lowest_priority(self):
        assert ExecutionPriority.PRIORITY_UNKNOWN > ExecutionPriority.PRIORITY_2_GOAL


# ---------------------------------------------------------------------------
# D–H. Other enums completeness
# ---------------------------------------------------------------------------

class TestOtherEnums:
    def test_cancellation_reason_values(self):
        values = {e.value for e in CancellationReason}
        assert "user_cancelled" in values
        assert "timeout" in values
        assert "mode_switch_to_local" in values
        assert "device_disconnected" in values
        assert "higher_priority_execution" in values
        assert "policy_rejected" in values
        assert "unknown" in values

    def test_rollback_policy_values(self):
        values = {e.value for e in RollbackPolicy}
        assert "none" in values
        assert "best_effort_undo" in values
        assert "required_undo" in values
        assert "checkpoint_restore" in values
        assert "notify_only" in values

    def test_timeout_policy_values(self):
        values = {e.value for e in TimeoutPolicy}
        assert "none" in values
        assert "soft" in values
        assert "hard" in values

    def test_failure_semantic_values(self):
        values = {e.value for e in FailureSemantic}
        assert "retry" in values
        assert "fallback_local" in values
        assert "reject_with_reason" in values
        assert "escalate_to_operator" in values
        assert "wait_and_requeue" in values

    def test_conflict_resolution_values(self):
        values = {e.value for e in ConflictResolution}
        assert "accept_incoming" in values
        assert "reject_incoming" in values
        assert "queue_incoming" in values
        assert "escalate" in values


# ---------------------------------------------------------------------------
# I. get_execution_type_policy()
# ---------------------------------------------------------------------------

class TestGetExecutionTypePolicy:
    def test_goal_execution_policy_returned(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        assert policy is not None
        assert policy.execution_type == ExecutionType.goal_execution

    def test_parallel_subtask_policy_returned(self):
        policy = get_execution_type_policy(ExecutionType.parallel_subtask)
        assert policy is not None
        assert policy.execution_type == ExecutionType.parallel_subtask

    def test_takeover_request_policy_returned(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy is not None
        assert policy.execution_type == ExecutionType.takeover_request

    def test_unknown_type_returns_none(self):
        policy = get_execution_type_policy(ExecutionType.unknown)
        assert policy is None


# ---------------------------------------------------------------------------
# J. ExecutionTypePolicy.to_dict()
# ---------------------------------------------------------------------------

class TestExecutionTypePolicyToDict:
    def test_goal_execution_policy_to_dict(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        d = policy.to_dict()
        assert d["execution_type"] == "goal_execution"
        assert "priority" in d
        assert "required_gates" in d
        assert "cancellable" in d
        assert "rollback_on_cancel" in d
        assert "rollback_on_failure" in d
        assert "timeout_policy" in d
        assert "default_timeout_s" in d
        assert "failure_semantic" in d
        assert "blocks_lower_priority" in d
        assert "max_concurrent_per_device" in d
        assert "_authority" in d

    def test_policy_dict_is_json_serialisable(self):
        import json
        for et in (ExecutionType.goal_execution, ExecutionType.parallel_subtask, ExecutionType.takeover_request):
            policy = get_execution_type_policy(et)
            assert policy is not None
            json.dumps(policy.to_dict())  # must not raise


# ---------------------------------------------------------------------------
# K. ExecutionGovernanceVerdict.to_dict()
# ---------------------------------------------------------------------------

class TestExecutionGovernanceVerdictToDict:
    def test_accepted_verdict_to_dict(self):
        verdict = ExecutionGovernanceVerdict(
            execution_type=ExecutionType.goal_execution,
            device_id="device-test",
            accepted=True,
        )
        d = verdict.to_dict()
        assert d["execution_type"] == "goal_execution"
        assert d["device_id"] == "device-test"
        assert d["accepted"] is True
        assert "_authority" in d
        assert "_contract_version" in d

    def test_rejected_verdict_to_dict(self):
        verdict = ExecutionGovernanceVerdict(
            execution_type=ExecutionType.goal_execution,
            device_id="device-test",
            accepted=False,
            rejection_reason="gate failed",
            blocking_gates=["android_cross_device_enabled"],
            conflict=True,
            active_conflicting_type=ExecutionType.takeover_request,
            failure_semantic=FailureSemantic.wait_and_requeue,
        )
        d = verdict.to_dict()
        assert d["accepted"] is False
        assert d["rejection_reason"] == "gate failed"
        assert d["blocking_gates"] == ["android_cross_device_enabled"]
        assert d["conflict"] is True
        assert d["active_conflicting_type"] == "takeover_request"
        assert d["failure_semantic"] == "wait_and_requeue"

    def test_verdict_to_json(self):
        import json
        verdict = ExecutionGovernanceVerdict(
            execution_type=ExecutionType.takeover_request,
            device_id="device-json",
            accepted=True,
        )
        j = verdict.to_json()
        parsed = json.loads(j)
        assert parsed["execution_type"] == "takeover_request"


# ---------------------------------------------------------------------------
# L. evaluate_execution_governance() — accepted when gates pass
# ---------------------------------------------------------------------------

class TestEvaluateGovernanceAccepted:
    def test_goal_execution_accepted_when_gates_pass(self):
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.goal_execution,
                "device-accept-test",
                register_if_accepted=False,
            )
        assert verdict.accepted is True
        assert verdict.execution_type == ExecutionType.goal_execution

    def test_parallel_subtask_accepted_when_gates_pass(self):
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.parallel_subtask,
                "device-accept-parallel",
                register_if_accepted=False,
            )
        assert verdict.accepted is True

    def test_takeover_request_accepted_when_gates_pass(self):
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.takeover_request,
                "device-accept-takeover",
                register_if_accepted=False,
            )
        assert verdict.accepted is True


# ---------------------------------------------------------------------------
# M. evaluate_execution_governance() — rejected when mode gate fails
# ---------------------------------------------------------------------------

class TestEvaluateGovernanceGateFail:
    def test_goal_execution_rejected_when_gate_fails(self):
        with _patch_mode_gate_fail("android_cross_device_enabled OFF"):
            verdict = evaluate_execution_governance(
                ExecutionType.goal_execution,
                "device-gate-fail",
                register_if_accepted=False,
            )
        assert verdict.accepted is False
        assert "gate" in verdict.rejection_reason.lower()
        assert "android_cross_device_enabled" in verdict.blocking_gates

    def test_takeover_rejected_when_gate_fails(self):
        with _patch_mode_gate_fail("local_loop_ready=False"):
            verdict = evaluate_execution_governance(
                ExecutionType.takeover_request,
                "device-gate-fail-takeover",
                register_if_accepted=False,
            )
        assert verdict.accepted is False
        assert verdict.failure_semantic == FailureSemantic.escalate_to_operator


# ---------------------------------------------------------------------------
# N. goal_execution rejected when active takeover
# ---------------------------------------------------------------------------

class TestTakeoverBlocksGoalExecution:
    def test_goal_execution_blocked_by_active_takeover(self):
        device_id = "device-conflict-n"
        # Register an active takeover
        with _patch_mode_gate_pass():
            takeover_verdict = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-001",
                register_if_accepted=True,
            )
        assert takeover_verdict.accepted is True

        # Now try goal_execution — should be blocked
        with _patch_mode_gate_pass():
            goal_verdict = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-001",
                register_if_accepted=False,
            )
        assert goal_verdict.accepted is False
        assert goal_verdict.conflict is True
        assert goal_verdict.active_conflicting_type == ExecutionType.takeover_request
        assert "takeover" in goal_verdict.rejection_reason.lower()
        assert goal_verdict.failure_semantic == FailureSemantic.wait_and_requeue

    def test_goal_execution_unblocked_after_takeover_completes(self):
        device_id = "device-unblock-n"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-002",
                register_if_accepted=True,
            )

        notify_execution_completed(device_id, ExecutionType.takeover_request, "tkv-002")

        with _patch_mode_gate_pass():
            goal_verdict = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=False,
            )
        assert goal_verdict.accepted is True


# ---------------------------------------------------------------------------
# O. parallel_subtask rejected when active takeover
# ---------------------------------------------------------------------------

class TestTakeoverBlocksParallelSubtask:
    def test_parallel_subtask_blocked_by_active_takeover(self):
        device_id = "device-conflict-o"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-par-001",
                register_if_accepted=True,
            )

        with _patch_mode_gate_pass():
            par_verdict = evaluate_execution_governance(
                ExecutionType.parallel_subtask,
                device_id,
                register_if_accepted=False,
            )
        assert par_verdict.accepted is False
        assert par_verdict.conflict is True
        assert par_verdict.active_conflicting_type == ExecutionType.takeover_request
        assert par_verdict.failure_semantic == FailureSemantic.wait_and_requeue


# ---------------------------------------------------------------------------
# P. takeover NOT blocked by active goal_execution
# ---------------------------------------------------------------------------

class TestTakeoverNotBlockedByGoalExecution:
    def test_takeover_accepted_when_goal_execution_active(self):
        device_id = "device-takeover-p"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-p-001",
                register_if_accepted=True,
            )

        # Takeover should not be blocked by goal_execution (goal doesn't block higher priority)
        with _patch_mode_gate_pass():
            takeover_verdict = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                register_if_accepted=False,
            )
        assert takeover_verdict.accepted is True
        assert not takeover_verdict.conflict


# ---------------------------------------------------------------------------
# Q. Concurrency limit enforced per type
# ---------------------------------------------------------------------------

class TestConcurrencyLimit:
    def test_takeover_max_concurrent_one(self):
        device_id = "device-concurrency-q"
        with _patch_mode_gate_pass():
            v1 = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-c-001",
                register_if_accepted=True,
            )
        assert v1.accepted is True

        # Second takeover on same device must be rejected
        with _patch_mode_gate_pass():
            v2 = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-c-002",
                register_if_accepted=False,
                skip_conflict_check=True,  # bypass conflict check, test concurrency only
            )
        assert v2.accepted is False
        assert "concurrency limit" in v2.rejection_reason.lower()

    def test_goal_execution_allows_up_to_three(self):
        device_id = "device-goal-limit-q"
        with _patch_mode_gate_pass():
            for i in range(3):
                v = evaluate_execution_governance(
                    ExecutionType.goal_execution,
                    device_id,
                    execution_id=f"goal-q-00{i}",
                    register_if_accepted=True,
                )
                assert v.accepted is True, f"Goal #{i} should be accepted"

        # 4th must be rejected
        with _patch_mode_gate_pass():
            v4 = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-q-003",
                register_if_accepted=False,
                skip_conflict_check=True,
            )
        assert v4.accepted is False
        assert "concurrency" in v4.rejection_reason.lower()


# ---------------------------------------------------------------------------
# R. skip_conflict_check bypasses conflict detection
# ---------------------------------------------------------------------------

class TestSkipConflictCheck:
    def test_skip_conflict_check_allows_evaluation_despite_takeover(self):
        device_id = "device-skip-r"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-skip-001",
                register_if_accepted=True,
            )

        # With skip_conflict_check=True, conflict not checked — gate check decides
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=False,
                skip_conflict_check=True,
            )
        # Gates pass and concurrency not exceeded → accepted
        assert verdict.accepted is True
        assert not verdict.conflict


# ---------------------------------------------------------------------------
# S. register_if_accepted=False does not track
# ---------------------------------------------------------------------------

class TestRegisterIfAccepted:
    def test_no_registration_when_flag_false(self):
        device_id = "device-noreg-s"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=False,
            )
        # Should not be tracked
        assert get_active_execution_type(device_id) is None

    def test_registration_when_flag_true(self):
        device_id = "device-reg-s"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=True,
            )
        assert get_active_execution_type(device_id) == ExecutionType.goal_execution


# ---------------------------------------------------------------------------
# T. is_takeover_active()
# ---------------------------------------------------------------------------

class TestIsTakeoverActive:
    def test_false_when_no_active_executions(self):
        assert not is_takeover_active("device-no-takeover-t")

    def test_true_after_takeover_accepted(self):
        device_id = "device-takeover-t"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-t-001",
                register_if_accepted=True,
            )
        assert is_takeover_active(device_id) is True

    def test_false_after_notify_completed(self):
        device_id = "device-takeover-t2"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-t2-001",
                register_if_accepted=True,
            )
        notify_execution_completed(device_id, ExecutionType.takeover_request, "tkv-t2-001")
        assert not is_takeover_active(device_id)

    def test_false_when_only_goal_execution_active(self):
        device_id = "device-goal-only-t"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=True,
            )
        assert not is_takeover_active(device_id)


# ---------------------------------------------------------------------------
# U. get_active_execution_type()
# ---------------------------------------------------------------------------

class TestGetActiveExecutionType:
    def test_none_when_no_active(self):
        assert get_active_execution_type("device-empty-u") is None

    def test_returns_takeover_when_both_takeover_and_goal_active(self):
        device_id = "device-priority-u"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-u-001",
                register_if_accepted=True,
            )
        # Force-add a takeover (skip conflict check for this test)
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-u-001",
                register_if_accepted=True,
                skip_conflict_check=True,
            )
        # get_active_execution_type should return highest priority = takeover
        assert get_active_execution_type(device_id) == ExecutionType.takeover_request


# ---------------------------------------------------------------------------
# V. notify_execution_completed()
# ---------------------------------------------------------------------------

class TestNotifyExecutionCompleted:
    def test_returns_true_when_found(self):
        device_id = "device-notify-v"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-v-001",
                register_if_accepted=True,
            )
        result = notify_execution_completed(device_id, ExecutionType.goal_execution, "goal-v-001")
        assert result is True

    def test_returns_false_when_not_found(self):
        result = notify_execution_completed("device-not-there", ExecutionType.goal_execution, "nonexistent")
        assert result is False

    def test_removes_only_matching_entry(self):
        device_id = "device-notify-v2"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-v2-001",
                register_if_accepted=True,
            )
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-v2-002",
                register_if_accepted=True,
            )
        notify_execution_completed(device_id, ExecutionType.goal_execution, "goal-v2-001")
        # One goal still active
        assert get_active_execution_type(device_id) == ExecutionType.goal_execution


# ---------------------------------------------------------------------------
# W. resolve_execution_conflict() — takeover beats goal_execution
# ---------------------------------------------------------------------------

class TestResolveExecutionConflict:
    def test_takeover_incoming_beats_goal_active(self):
        result = resolve_execution_conflict(
            incoming_type=ExecutionType.takeover_request,
            active_type=ExecutionType.goal_execution,
            device_id="device-conflict-w",
        )
        assert result.resolution == ConflictResolution.accept_incoming
        assert result.conflict.incoming_wins is True

    # X. goal vs parallel (same priority → reject_incoming FIFO)
    def test_goal_vs_parallel_same_priority_fifo(self):
        result = resolve_execution_conflict(
            incoming_type=ExecutionType.goal_execution,
            active_type=ExecutionType.parallel_subtask,
            device_id="device-conflict-x",
        )
        # Same priority → active wins (FIFO)
        assert result.resolution == ConflictResolution.reject_incoming
        assert result.conflict.incoming_wins is False
        assert result.recommended_failure_semantic == FailureSemantic.wait_and_requeue

    # Y. goal incoming vs active takeover → reject_incoming
    def test_goal_incoming_vs_active_takeover_reject(self):
        result = resolve_execution_conflict(
            incoming_type=ExecutionType.goal_execution,
            active_type=ExecutionType.takeover_request,
            device_id="device-conflict-y",
        )
        assert result.resolution == ConflictResolution.reject_incoming
        assert result.conflict.incoming_wins is False
        assert result.recommended_failure_semantic == FailureSemantic.wait_and_requeue


# ---------------------------------------------------------------------------
# Z. Multi-type conflict scenario
# ---------------------------------------------------------------------------

class TestMultiTypeConflictScenario:
    """Z. Full multi-execution-type conflict sequence test."""

    def test_takeover_goal_parallel_sequence(self):
        device_id = "device-sequence-z"

        # 1) Accept takeover
        with _patch_mode_gate_pass():
            tkv = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-z-001",
                register_if_accepted=True,
            )
        assert tkv.accepted is True
        assert is_takeover_active(device_id)

        # 2) goal_execution blocked by active takeover
        with _patch_mode_gate_pass():
            goal = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-z-001",
                register_if_accepted=False,
            )
        assert goal.accepted is False
        assert goal.conflict is True
        assert goal.active_conflicting_type == ExecutionType.takeover_request

        # 3) parallel_subtask also blocked
        with _patch_mode_gate_pass():
            par = evaluate_execution_governance(
                ExecutionType.parallel_subtask,
                device_id,
                execution_id="par-z-001",
                register_if_accepted=False,
            )
        assert par.accepted is False
        assert par.conflict is True

        # 4) Takeover completes
        notify_execution_completed(device_id, ExecutionType.takeover_request, "tkv-z-001")
        assert not is_takeover_active(device_id)

        # 5) Now goal_execution is accepted
        with _patch_mode_gate_pass():
            goal2 = evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-z-002",
                register_if_accepted=True,
            )
        assert goal2.accepted is True

        # 6) And parallel_subtask is also accepted (separate device entry)
        with _patch_mode_gate_pass():
            par2 = evaluate_execution_governance(
                ExecutionType.parallel_subtask,
                device_id,
                execution_id="par-z-002",
                register_if_accepted=True,
            )
        assert par2.accepted is True


# ---------------------------------------------------------------------------
# AA. ExecutionConflict.to_dict()
# ---------------------------------------------------------------------------

class TestExecutionConflictToDict:
    def test_to_dict_all_fields(self):
        conflict = ExecutionConflict(
            incoming_type=ExecutionType.goal_execution,
            active_type=ExecutionType.takeover_request,
            device_id="device-aa",
            incoming_priority=2,
            active_priority=1,
            incoming_wins=False,
        )
        d = conflict.to_dict()
        assert d["incoming_type"] == "goal_execution"
        assert d["active_type"] == "takeover_request"
        assert d["device_id"] == "device-aa"
        assert d["incoming_priority"] == 2
        assert d["active_priority"] == 1
        assert d["incoming_wins"] is False
        assert "detected_at" in d


# ---------------------------------------------------------------------------
# AB. ConflictResolutionResult.to_dict()
# ---------------------------------------------------------------------------

class TestConflictResolutionResultToDict:
    def test_to_dict_all_fields(self):
        conflict = ExecutionConflict(
            incoming_type=ExecutionType.takeover_request,
            active_type=ExecutionType.goal_execution,
            device_id="device-ab",
            incoming_priority=1,
            active_priority=2,
            incoming_wins=True,
        )
        result = ConflictResolutionResult(
            conflict=conflict,
            resolution=ConflictResolution.accept_incoming,
            reason="takeover wins",
            recommended_failure_semantic=FailureSemantic.reject_with_reason,
        )
        d = result.to_dict()
        assert d["resolution"] == "accept_incoming"
        assert d["reason"] == "takeover wins"
        assert d["recommended_failure_semantic"] == "reject_with_reason"
        assert "_authority" in d
        assert "conflict" in d


# ---------------------------------------------------------------------------
# AC. evaluate_execution_governance() — unknown type → rejected
# ---------------------------------------------------------------------------

class TestUnknownTypeRejected:
    def test_unknown_execution_type_rejected(self):
        verdict = evaluate_execution_governance(
            ExecutionType.unknown,
            "device-unknown-ac",
            register_if_accepted=False,
        )
        assert verdict.accepted is False
        assert "No governance policy" in verdict.rejection_reason


# ---------------------------------------------------------------------------
# AD. Policy: blocks_lower_priority flags
# ---------------------------------------------------------------------------

class TestPolicyBlocksLowerPriority:
    def test_takeover_blocks_lower_priority_true(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy.blocks_lower_priority is True

    def test_goal_execution_blocks_lower_priority_false(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        assert policy.blocks_lower_priority is False

    def test_parallel_subtask_blocks_lower_priority_false(self):
        policy = get_execution_type_policy(ExecutionType.parallel_subtask)
        assert policy.blocks_lower_priority is False


# ---------------------------------------------------------------------------
# AE. Policy: max_concurrent_per_device
# ---------------------------------------------------------------------------

class TestPolicyMaxConcurrent:
    def test_takeover_max_concurrent_one(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy.max_concurrent_per_device == 1

    def test_goal_execution_max_concurrent_three(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        assert policy.max_concurrent_per_device == 3

    def test_parallel_subtask_max_concurrent_five(self):
        policy = get_execution_type_policy(ExecutionType.parallel_subtask)
        assert policy.max_concurrent_per_device == 5


# ---------------------------------------------------------------------------
# AF. Policy: rollback semantics
# ---------------------------------------------------------------------------

class TestPolicyRollbackSemantics:
    def test_takeover_rollback_on_cancel_required_undo(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy.rollback_on_cancel == RollbackPolicy.required_undo

    def test_takeover_rollback_on_failure_checkpoint_restore(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy.rollback_on_failure == RollbackPolicy.checkpoint_restore

    def test_goal_rollback_on_cancel_notify_only(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        assert policy.rollback_on_cancel == RollbackPolicy.notify_only

    def test_parallel_rollback_on_cancel_notify_only(self):
        policy = get_execution_type_policy(ExecutionType.parallel_subtask)
        assert policy.rollback_on_cancel == RollbackPolicy.notify_only


# ---------------------------------------------------------------------------
# AG. Policy: timeout semantics
# ---------------------------------------------------------------------------

class TestPolicyTimeoutSemantics:
    def test_all_types_have_hard_timeout(self):
        for et in (ExecutionType.goal_execution, ExecutionType.parallel_subtask, ExecutionType.takeover_request):
            policy = get_execution_type_policy(et)
            assert policy.timeout_policy == TimeoutPolicy.hard

    def test_takeover_has_longest_default_timeout(self):
        tkv = get_execution_type_policy(ExecutionType.takeover_request)
        goal = get_execution_type_policy(ExecutionType.goal_execution)
        par = get_execution_type_policy(ExecutionType.parallel_subtask)
        assert tkv.default_timeout_s > goal.default_timeout_s
        assert tkv.default_timeout_s > par.default_timeout_s

    def test_takeover_failure_semantic_escalate(self):
        policy = get_execution_type_policy(ExecutionType.takeover_request)
        assert policy.failure_semantic == FailureSemantic.escalate_to_operator

    def test_goal_failure_semantic_retry(self):
        policy = get_execution_type_policy(ExecutionType.goal_execution)
        assert policy.failure_semantic == FailureSemantic.retry


# ---------------------------------------------------------------------------
# AH. _clear_all_active_executions() test isolation
# ---------------------------------------------------------------------------

class TestClearActiveExecutions:
    def test_clear_all_removes_all_entries(self):
        device_id = "device-clear-ah"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                register_if_accepted=True,
            )
        assert get_active_execution_type(device_id) is not None
        _clear_all_active_executions()
        assert get_active_execution_type(device_id) is None

    def test_clear_device_removes_only_that_device(self):
        device_a = "device-clear-ah-a"
        device_b = "device-clear-ah-b"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(ExecutionType.goal_execution, device_a, register_if_accepted=True)
            evaluate_execution_governance(ExecutionType.goal_execution, device_b, register_if_accepted=True)
        _clear_active_executions_for_device(device_a)
        assert get_active_execution_type(device_a) is None
        assert get_active_execution_type(device_b) == ExecutionType.goal_execution


class TestExecutionRuntimeSnapshot:
    def test_snapshot_reports_active_execution_lifecycle_truth(self):
        device_id = "device-runtime-snapshot-1"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-snapshot-001",
                register_if_accepted=True,
            )
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="takeover-snapshot-001",
                register_if_accepted=True,
                skip_conflict_check=True,
            )

        snapshot = get_execution_runtime_snapshot(device_ids=[device_id])
        assert snapshot["active_execution_total_count"] == 2
        device_state = snapshot["devices"][0]
        assert device_state["device_id"] == device_id
        assert device_state["active_execution_count"] == 2
        assert device_state["highest_priority_execution_type"] == "takeover_request"
        assert device_state["takeover_active"] is True
        assert device_state["blocked_execution_types"] == ["goal_execution", "parallel_subtask"]

    def test_snapshot_includes_requested_devices_without_active_executions(self):
        snapshot = get_execution_runtime_snapshot(device_ids=["idle-device"])
        assert snapshot["active_execution_total_count"] == 0
        assert snapshot["active_device_count"] == 0
        assert snapshot["devices"][0]["device_id"] == "idle-device"
        assert snapshot["devices"][0]["active_execution_count"] == 0

    def test_snapshot_surfaces_busy_event_and_reconciliation_evidence(self):
        device_id = "device-runtime-evidence-1"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 4
        state_snapshot.current_fallback_tier = "center_delegated"
        state_snapshot.runtime_health_snapshot = {"status": "degraded"}
        state_snapshot.is_local_ai_ready = lambda: True

        recent_event = MagicMock()
        recent_event.phase = "execution"
        # With patched time.time()=200.0 this yields a deterministic age of 5.0 seconds.
        recent_event.absorbed_at = 195.0

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={
                "status": "out_of_order_rejected",
                "reason": "snapshot_seq_regression",
                "conflict": False,
                "ordering_basis": "snapshot_seq",
                "updated_at": 196.0,
                "applied": False,
            },
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[recent_event],
        ), patch(
            "core.unified_execution_governance.time.time",
            return_value=200.0,
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["execution_busy"] is True
        assert device_state["latest_execution_event_phase"] == "execution"
        assert device_state["latest_execution_event_absorbed_at"] == 195.0
        assert device_state["latest_execution_event_age_s"] == 5.0
        assert device_state["execution_busy_window_seconds"] == 60.0
        assert device_state["snapshot_reconciliation_status"] == "out_of_order_rejected"
        assert device_state["snapshot_reconciliation_applied"] is False
        assert device_state["snapshot_ordering_basis"] == "snapshot_seq"
        assert device_state["offline_queue_depth"] == 4

    def test_snapshot_prefers_android_reported_semantics_for_local_inference(self):
        device_id = "device-runtime-semantics-1"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value={
                "canonical_mode": "local",
                "reported_mode_state": "local_only",
                "mode_readiness_state": "degraded",
                "cross_device_eligibility": False,
                "goal_execution_eligibility": False,
                "parallel_execution_eligibility": False,
                "local_intelligence_status": "disabled",
                "local_inference_ready": False,
                "local_inference_available": True,
                "canonical_gate_metadata_state": "complete",
                "canonical_gate_metadata_complete": True,
                "missing_canonical_gate_metadata_keys": [],
                "malformed_canonical_gate_metadata_keys": [],
                "absorbed_at": 123.0,
                "reported_at": 120.0,
                "semantics_age_s": 3.0,
            },
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["local_inference_available"] is True
        assert device_state["android_reported_mode"] == "local"
        assert device_state["android_reported_mode_state"] == "local_only"
        assert device_state["android_reported_local_inference_available"] is True
        assert device_state["android_semantics_age_s"] == 3.0

    def test_snapshot_keeps_android_truth_authoritative_at_staleness_boundary(self):
        device_id = "device-runtime-semantics-boundary"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value={
                "canonical_mode": "cross_device",
                "reported_mode_state": "delegated",
                "local_inference_available": True,
                "canonical_gate_metadata_state": "complete",
                "canonical_gate_metadata_complete": True,
                "missing_canonical_gate_metadata_keys": [],
                "malformed_canonical_gate_metadata_keys": [],
                "absorbed_at": 123.0,
                "reported_at": 120.0,
                "semantics_age_s": ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS,
            },
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["local_inference_available"] is True
        assert device_state["android_reported_mode"] == "cross_device"
        assert (
            device_state["android_semantics_freshness_threshold_s"]
            == ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS
        )
        assert device_state["android_semantics_freshness_state"] == "fresh"
        assert device_state["android_semantics_freshness_reason"] == "android_semantics_age_within_threshold"
        assert device_state["android_runtime_truth_authority"] == "authoritative"
        assert device_state["android_runtime_truth_usable"] is True

    def test_snapshot_downgrades_stale_android_truth_to_unknown(self):
        device_id = "device-runtime-semantics-stale"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value={
                "canonical_mode": "cross_device",
                "reported_mode_state": "delegated",
                "local_inference_available": True,
                "local_inference_ready": True,
                "canonical_gate_metadata_state": "complete",
                "canonical_gate_metadata_complete": True,
                "missing_canonical_gate_metadata_keys": [],
                "malformed_canonical_gate_metadata_keys": [],
                "absorbed_at": 123.0,
                "reported_at": 120.0,
                "semantics_age_s": ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS + 0.1,
            },
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["local_inference_available"] is False
        assert device_state["android_reported_mode"] is None
        assert device_state["android_reported_local_inference_available"] is None
        assert device_state["android_semantics_age_s"] == pytest.approx(
            ANDROID_RUNTIME_SEMANTICS_STALE_AFTER_SECONDS + 0.1
        )
        assert device_state["android_semantics_freshness_state"] == "stale"
        assert device_state["android_semantics_freshness_reason"] == "android_semantics_age_exceeds_threshold"
        assert device_state["android_runtime_truth_authority"] == "downgraded_to_unknown"
        assert device_state["android_runtime_truth_usable"] is False

    def test_snapshot_downgrades_android_truth_when_freshness_is_unknown(self):
        device_id = "device-runtime-semantics-unknown"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value={
                "canonical_mode": "cross_device",
                "reported_mode_state": "delegated",
                "local_inference_available": True,
                "canonical_gate_metadata_state": "complete",
                "canonical_gate_metadata_complete": True,
                "missing_canonical_gate_metadata_keys": [],
                "malformed_canonical_gate_metadata_keys": [],
                "absorbed_at": None,
                "reported_at": 120.0,
                "semantics_age_s": None,
            },
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["local_inference_available"] is False
        assert device_state["android_reported_mode"] is None
        assert device_state["android_semantics_age_s"] is None
        assert device_state["android_semantics_freshness_state"] == "unknown"
        assert device_state["android_semantics_freshness_reason"] == "android_semantics_age_unavailable"
        assert device_state["android_runtime_truth_authority"] == "downgraded_to_unknown"
        assert device_state["android_runtime_truth_usable"] is False

    def test_snapshot_surfaces_android_semantics_contract_state(self):
        device_id = "device-runtime-semantics-contract"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value={
                "canonical_mode": None,
                "reported_mode_state": "not_a_real_mode",
                "canonical_gate_metadata_state": "malformed",
                "canonical_gate_metadata_complete": False,
                "missing_canonical_gate_metadata_keys": ["goal_execution_eligibility"],
                "malformed_canonical_gate_metadata_keys": ["mode_state"],
                "absorbed_at": 123.0,
                "reported_at": 120.0,
                "semantics_age_s": 3.0,
            },
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["android_semantics_contract_state"] == "malformed"
        assert device_state["android_semantics_contract_complete"] is False
        assert device_state["android_semantics_missing_keys"] == ["goal_execution_eligibility"]
        assert device_state["android_semantics_malformed_keys"] == ["mode_state"]

    @pytest.mark.parametrize(
        ("semantics_patch", "expected_contract_state"),
        [
            (
                {
                    "canonical_gate_metadata_state": "partial",
                    "canonical_gate_metadata_complete": False,
                    "missing_canonical_gate_metadata_keys": ["goal_execution_eligibility"],
                    "malformed_canonical_gate_metadata_keys": [],
                },
                "partial",
            ),
            (
                {
                    "canonical_gate_metadata_state": "malformed",
                    "canonical_gate_metadata_complete": False,
                    "missing_canonical_gate_metadata_keys": [],
                    "malformed_canonical_gate_metadata_keys": ["mode_state"],
                },
                "malformed",
            ),
            ({}, "missing"),
        ],
    )
    def test_snapshot_downgrades_incomplete_android_semantics_contract(
        self,
        semantics_patch,
        expected_contract_state,
    ):
        device_id = "device-runtime-semantics-contract-drift"
        state_snapshot = MagicMock()
        state_snapshot.offline_queue_depth = 0
        state_snapshot.current_fallback_tier = None
        state_snapshot.runtime_health_snapshot = {"status": "healthy"}
        state_snapshot.is_local_ai_ready = lambda: False

        semantics = {
            "canonical_mode": "cross_device",
            "reported_mode_state": "cross_device_active",
            "mode_readiness_state": "ready",
            "cross_device_eligibility": True,
            "goal_execution_eligibility": True,
            "parallel_execution_eligibility": True,
            "local_intelligence_status": "ready",
            "local_inference_ready": True,
            "local_inference_available": True,
            "absorbed_at": 123.0,
            "reported_at": 120.0,
            "semantics_age_s": 3.0,
        }
        semantics.update(semantics_patch)

        with patch(
            "core.android_device_state_store.get_device_state_snapshot",
            return_value=state_snapshot,
        ), patch(
            "core.android_device_state_store.get_device_capability_report_semantics",
            return_value=semantics,
        ), patch(
            "core.android_device_state_store.get_device_snapshot_reconciliation",
            return_value={"status": "accepted", "reason": "initial_snapshot", "applied": True},
        ), patch(
            "core.android_device_state_store.list_recent_execution_events",
            return_value=[],
        ):
            snapshot = get_execution_runtime_snapshot(device_ids=[device_id])

        device_state = snapshot["devices"][0]
        assert device_state["android_semantics_contract_state"] == expected_contract_state
        assert device_state["android_semantics_contract_complete"] is False
        assert device_state["android_reported_mode"] is None
        assert device_state["android_reported_local_inference_available"] is None
        assert device_state["local_inference_available"] is False
        assert device_state["android_semantics_freshness_state"] == "unknown"
        assert (
            device_state["android_semantics_freshness_reason"]
            == "android_semantics_contract_incomplete"
        )
        assert device_state["android_runtime_truth_authority"] == "downgraded_to_unknown"
        assert device_state["android_runtime_truth_usable"] is False
