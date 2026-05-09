"""tests/test_pr06_execution_governance_hardening.py
=====================================================
PR-06 — Execution Governance Hardening regression suite.

Coverage groups
---------------
A.  PR-06 sentinel and new authority constants importable.
B.  ``ExecutionType.delegated_execution`` enum value present and correct.
C.  ``ExecutionPriority.PRIORITY_2_DELEGATED`` defined and equal to PRIORITY_2_GOAL.
D.  New enums present: ``InterruptionReason``, ``ReplayReason``, ``UplinkKind``.
E.  ``ExecutionTypePolicy`` for delegated_execution has correct governance values.
F.  ``delegated_execution`` accepted when gates pass (no active takeover).
G.  ``delegated_execution`` rejected when mode gate fails.
H.  ``delegated_execution`` blocked by active takeover_request.
I.  ``delegated_execution`` NOT blocked by active goal_execution (same-priority FIFO).
J.  ``delegated_execution`` NOT blocked by active parallel_subtask (same-priority FIFO).
K.  takeover_request NOT blocked by active delegated_execution.
L.  ``delegated_execution`` concurrency limit (max 2 per device) enforced.
M.  ``delegated_execution`` unblocked after takeover completes.
N.  ``notify_execution_completed`` removes delegated_execution from registry.
O.  ``record_execution_lifecycle_event`` — failure event recorded correctly.
P.  ``record_execution_lifecycle_event`` — timeout event with InterruptionReason.
Q.  ``record_execution_lifecycle_event`` — retry event with ReplayReason.
R.  ``record_execution_lifecycle_event`` — interruption event recorded.
S.  ``record_execution_lifecycle_event`` — replay event recorded.
T.  ``get_execution_lifecycle_history`` returns events in order; empty when none.
U.  ``record_result_uplink`` — result_uplink recorded with correct canonical fields.
V.  ``record_result_uplink`` — state_uplink (intermediate) recorded.
W.  ``record_result_uplink`` — interruption_uplink recorded.
X.  ``get_uplink_truth_state`` returns most recent uplink; None when none.
Y.  ``get_all_uplink_records`` returns all uplinks in chronological order.
Z.  ``get_execution_lifecycle_matrix`` — structure and fields present.
AA. ``get_execution_lifecycle_matrix`` — all four execution types in matrix.
AB. ``get_execution_lifecycle_matrix`` — blocking_rules correct (takeover blocks 3).
AC. ``get_execution_lifecycle_matrix`` — timeout governance per type.
AD. ``get_execution_lifecycle_matrix`` — retry_governance per type.
AE. lifecycle event and uplink store cleared by ``_clear_all_active_executions``.
AF. Full PR-06 sequence: delegated accepted → state uplink → failure → retry → result.
AG. Takeover preempts delegated_execution; interruption_uplink + lifecycle events.
AH. Multi-mode governance stability: goal + parallel + delegated + takeover sequence.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.unified_execution_governance import (
    # PR-06 sentinels
    EXECUTION_GOVERNANCE_HARDENING_SENTINEL,
    LIFECYCLE_GOVERNANCE_HARDENING_POLICY,
    DELEGATED_EXECUTION_GOVERNANCE_POLICY,
    UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION,
    # Existing enums
    ExecutionType,
    ExecutionPriority,
    CancellationReason,
    RollbackPolicy,
    TimeoutPolicy,
    FailureSemantic,
    ConflictResolution,
    # PR-06 new enums
    InterruptionReason,
    ReplayReason,
    UplinkKind,
    # Dataclasses
    ExecutionLifecycleEvent,
    ExecutionUplinkRecord,
    # Functions
    get_execution_type_policy,
    evaluate_execution_governance,
    notify_execution_completed,
    is_takeover_active,
    get_active_execution_type,
    record_execution_lifecycle_event,
    get_execution_lifecycle_history,
    record_result_uplink,
    get_uplink_truth_state,
    get_all_uplink_records,
    get_execution_lifecycle_matrix,
    _clear_all_active_executions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_all():
    """Clean all registries before and after each test."""
    _clear_all_active_executions()
    yield
    _clear_all_active_executions()


def _patch_mode_gate_pass():
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(True, [], "all gates pass"),
    )


def _patch_mode_gate_fail(reason: str = "gate fail"):
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(False, ["android_cross_device_enabled"], reason),
    )


# ---------------------------------------------------------------------------
# A. PR-06 sentinel and authority constants
# ---------------------------------------------------------------------------


class TestPR06Sentinels:
    def test_hardening_sentinel_present(self):
        assert EXECUTION_GOVERNANCE_HARDENING_SENTINEL
        assert "PR-06" in EXECUTION_GOVERNANCE_HARDENING_SENTINEL

    def test_lifecycle_policy_present(self):
        assert LIFECYCLE_GOVERNANCE_HARDENING_POLICY
        assert "record_execution_lifecycle_event" in LIFECYCLE_GOVERNANCE_HARDENING_POLICY

    def test_delegated_execution_policy_constant_present(self):
        assert DELEGATED_EXECUTION_GOVERNANCE_POLICY
        assert "delegated_execution" in DELEGATED_EXECUTION_GOVERNANCE_POLICY

    def test_contract_version_updated(self):
        # PR-06 bumps the contract version to 1.1.0
        assert UNIFIED_EXECUTION_GOVERNANCE_CONTRACT_VERSION == "1.1.0"


# ---------------------------------------------------------------------------
# B. ExecutionType.delegated_execution
# ---------------------------------------------------------------------------


class TestDelegatedExecutionType:
    def test_delegated_execution_value(self):
        assert ExecutionType.delegated_execution.value == "delegated_execution"

    def test_all_four_types_present(self):
        values = {e.value for e in ExecutionType}
        assert "goal_execution" in values
        assert "parallel_subtask" in values
        assert "takeover_request" in values
        assert "delegated_execution" in values

    def test_from_string_delegated_execution(self):
        assert (
            ExecutionType.from_string("delegated_execution")
            == ExecutionType.delegated_execution
        )


# ---------------------------------------------------------------------------
# C. ExecutionPriority.PRIORITY_2_DELEGATED
# ---------------------------------------------------------------------------


class TestDelegatedPriority:
    def test_delegated_has_same_priority_as_goal(self):
        assert (
            ExecutionPriority.PRIORITY_2_DELEGATED == ExecutionPriority.PRIORITY_2_GOAL
        )

    def test_delegated_lower_priority_than_takeover(self):
        assert (
            ExecutionPriority.PRIORITY_2_DELEGATED > ExecutionPriority.PRIORITY_1_TAKEOVER
        )


# ---------------------------------------------------------------------------
# D. New enums: InterruptionReason, ReplayReason, UplinkKind
# ---------------------------------------------------------------------------


class TestNewEnums:
    def test_interruption_reason_values(self):
        values = {e.value for e in InterruptionReason}
        assert "timeout_hard" in values
        assert "timeout_soft" in values
        assert "device_disconnected" in values
        assert "mode_boundary_violated" in values
        assert "operator_interrupt" in values
        assert "higher_priority_preempted" in values
        assert "resource_exhaustion" in values
        assert "dependency_failure" in values
        assert "unknown" in values

    def test_replay_reason_values(self):
        values = {e.value for e in ReplayReason}
        assert "transient_failure_retry" in values
        assert "fallback_mode_retry" in values
        assert "operator_requested_replay" in values
        assert "timeout_retry" in values
        assert "interruption_recovery" in values
        assert "unknown" in values

    def test_uplink_kind_values(self):
        values = {e.value for e in UplinkKind}
        assert "result_uplink" in values
        assert "state_uplink" in values
        assert "interruption_uplink" in values
        assert "replay_uplink" in values


# ---------------------------------------------------------------------------
# E. delegated_execution policy governance values
# ---------------------------------------------------------------------------


class TestDelegatedExecutionPolicy:
    def test_policy_exists(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy is not None

    def test_execution_type_correct(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.execution_type == ExecutionType.delegated_execution

    def test_priority_tier(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.priority == ExecutionPriority.PRIORITY_2_DELEGATED

    def test_cancellable(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.cancellable is True

    def test_rollback_on_cancel_notify_only(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.rollback_on_cancel == RollbackPolicy.notify_only

    def test_rollback_on_failure_best_effort_undo(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.rollback_on_failure == RollbackPolicy.best_effort_undo

    def test_timeout_policy_hard(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.timeout_policy == TimeoutPolicy.hard

    def test_default_timeout_between_goal_and_takeover(self):
        delegated = get_execution_type_policy(ExecutionType.delegated_execution)
        goal = get_execution_type_policy(ExecutionType.goal_execution)
        takeover = get_execution_type_policy(ExecutionType.takeover_request)
        assert delegated.default_timeout_s > goal.default_timeout_s
        assert delegated.default_timeout_s < takeover.default_timeout_s

    def test_failure_semantic_fallback_local(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.failure_semantic == FailureSemantic.fallback_local

    def test_does_not_block_lower_priority(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.blocks_lower_priority is False

    def test_max_concurrent_per_device_two(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy.max_concurrent_per_device == 2

    def test_policy_to_dict_is_json_serialisable(self):
        import json
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert policy is not None
        json.dumps(policy.to_dict())  # must not raise

    def test_policy_has_delegated_gate(self):
        policy = get_execution_type_policy(ExecutionType.delegated_execution)
        assert "android_delegated_execution_gate" in policy.required_gates


# ---------------------------------------------------------------------------
# F. delegated_execution accepted when gates pass
# ---------------------------------------------------------------------------


class TestDelegatedExecutionAccepted:
    def test_accepted_when_gates_pass(self):
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                "device-delegated-f",
                register_if_accepted=False,
            )
        assert verdict.accepted is True
        assert verdict.execution_type == ExecutionType.delegated_execution

    def test_accepted_and_registered(self):
        device_id = "device-delegated-f2"
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-f2-001",
                register_if_accepted=True,
            )
        assert verdict.accepted is True
        assert get_active_execution_type(device_id) == ExecutionType.delegated_execution


# ---------------------------------------------------------------------------
# G. delegated_execution rejected when gate fails
# ---------------------------------------------------------------------------


class TestDelegatedExecutionGateFail:
    def test_rejected_when_gate_fails(self):
        with _patch_mode_gate_fail("android_delegated_execution_gate=OFF"):
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                "device-delegated-g",
                register_if_accepted=False,
            )
        assert verdict.accepted is False
        assert verdict.failure_semantic == FailureSemantic.fallback_local
        assert "android_cross_device_enabled" in verdict.blocking_gates


# ---------------------------------------------------------------------------
# H. delegated_execution blocked by active takeover_request
# ---------------------------------------------------------------------------


class TestDelegatedBlockedByTakeover:
    def test_delegated_blocked_by_active_takeover(self):
        device_id = "device-delegated-h"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-h-001",
                register_if_accepted=True,
            )

        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        assert verdict.accepted is False
        assert verdict.conflict is True
        assert verdict.active_conflicting_type == ExecutionType.takeover_request
        assert verdict.failure_semantic == FailureSemantic.wait_and_requeue


# ---------------------------------------------------------------------------
# I. delegated_execution NOT blocked by active goal_execution
# ---------------------------------------------------------------------------


class TestDelegatedNotBlockedByGoal:
    def test_delegated_not_blocked_by_goal(self):
        device_id = "device-delegated-i"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution,
                device_id,
                execution_id="goal-i-001",
                register_if_accepted=True,
            )

        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        # Same priority — no conflict check blocks it; gates decide
        assert verdict.accepted is True
        assert verdict.conflict is False


# ---------------------------------------------------------------------------
# J. delegated_execution NOT blocked by active parallel_subtask
# ---------------------------------------------------------------------------


class TestDelegatedNotBlockedByParallel:
    def test_delegated_not_blocked_by_parallel_subtask(self):
        device_id = "device-delegated-j"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.parallel_subtask,
                device_id,
                execution_id="par-j-001",
                register_if_accepted=True,
            )

        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        assert verdict.accepted is True
        assert verdict.conflict is False


# ---------------------------------------------------------------------------
# K. takeover_request NOT blocked by active delegated_execution
# ---------------------------------------------------------------------------


class TestTakeoverNotBlockedByDelegated:
    def test_takeover_not_blocked_by_delegated(self):
        device_id = "device-delegated-k"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-k-001",
                register_if_accepted=True,
            )

        with _patch_mode_gate_pass():
            tkv = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                register_if_accepted=False,
            )
        assert tkv.accepted is True
        assert not tkv.conflict


# ---------------------------------------------------------------------------
# L. delegated_execution concurrency limit = 2
# ---------------------------------------------------------------------------


class TestDelegatedConcurrencyLimit:
    def test_two_concurrent_delegated_accepted(self):
        device_id = "device-delegated-l"
        with _patch_mode_gate_pass():
            v1 = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-l-001",
                register_if_accepted=True,
            )
            v2 = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-l-002",
                register_if_accepted=True,
            )
        assert v1.accepted is True
        assert v2.accepted is True

    def test_third_delegated_rejected_at_limit(self):
        device_id = "device-delegated-l2"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-l2-001",
                register_if_accepted=True,
            )
            evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-l2-002",
                register_if_accepted=True,
            )
            v3 = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-l2-003",
                register_if_accepted=False,
                skip_conflict_check=True,
            )
        assert v3.accepted is False
        assert "concurrency limit" in v3.rejection_reason.lower()


# ---------------------------------------------------------------------------
# M. delegated_execution unblocked after takeover completes
# ---------------------------------------------------------------------------


class TestDelegatedUnblockedAfterTakeover:
    def test_delegated_unblocked_after_takeover_completes(self):
        device_id = "device-delegated-m"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id="tkv-m-001",
                register_if_accepted=True,
            )

        # Confirm blocked
        with _patch_mode_gate_pass():
            blocked = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        assert blocked.accepted is False

        # Takeover completes
        notify_execution_completed(device_id, ExecutionType.takeover_request, "tkv-m-001")

        # Now delegated_execution should be accepted
        with _patch_mode_gate_pass():
            unblocked = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        assert unblocked.accepted is True


# ---------------------------------------------------------------------------
# N. notify_execution_completed removes delegated_execution
# ---------------------------------------------------------------------------


class TestNotifyDelegatedCompleted:
    def test_notify_returns_true_when_found(self):
        device_id = "device-delegated-n"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id="del-n-001",
                register_if_accepted=True,
            )
        result = notify_execution_completed(
            device_id, ExecutionType.delegated_execution, "del-n-001"
        )
        assert result is True
        assert get_active_execution_type(device_id) is None

    def test_notify_returns_false_when_not_found(self):
        result = notify_execution_completed(
            "no-device", ExecutionType.delegated_execution, "nonexistent"
        )
        assert result is False


# ---------------------------------------------------------------------------
# O. record_execution_lifecycle_event — failure
# ---------------------------------------------------------------------------


class TestLifecycleEventFailure:
    def test_failure_event_recorded(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-o-001",
            device_id="device-o",
            execution_type=ExecutionType.goal_execution,
            event_kind="failure",
            detail="model timeout on step 3",
        )
        assert event.execution_id == "exec-o-001"
        assert event.event_kind == "failure"
        assert event.execution_type == ExecutionType.goal_execution

    def test_failure_event_in_history(self):
        record_execution_lifecycle_event(
            execution_id="exec-o-002",
            device_id="device-o",
            execution_type=ExecutionType.goal_execution,
            event_kind="failure",
        )
        history = get_execution_lifecycle_history("exec-o-002")
        assert len(history) == 1
        assert history[0].event_kind == "failure"

    def test_failure_event_to_dict_serialisable(self):
        import json
        event = record_execution_lifecycle_event(
            execution_id="exec-o-003",
            device_id="device-o",
            execution_type=ExecutionType.parallel_subtask,
            event_kind="failure",
        )
        d = event.to_dict()
        json.dumps(d)  # must not raise
        assert d["event_kind"] == "failure"
        assert "_authority" in d


# ---------------------------------------------------------------------------
# P. record_execution_lifecycle_event — timeout with InterruptionReason
# ---------------------------------------------------------------------------


class TestLifecycleEventTimeout:
    def test_timeout_event_with_hard_reason(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-p-001",
            device_id="device-p",
            execution_type=ExecutionType.takeover_request,
            event_kind="timeout",
            interruption_reason=InterruptionReason.timeout_hard,
            detail="300s hard deadline exceeded",
        )
        assert event.event_kind == "timeout"
        assert event.interruption_reason == InterruptionReason.timeout_hard

    def test_timeout_event_dict_has_interruption_reason(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-p-002",
            device_id="device-p",
            execution_type=ExecutionType.goal_execution,
            event_kind="timeout",
            interruption_reason=InterruptionReason.timeout_soft,
        )
        d = event.to_dict()
        assert d["interruption_reason"] == "timeout_soft"
        assert d["replay_reason"] is None


# ---------------------------------------------------------------------------
# Q. record_execution_lifecycle_event — retry with ReplayReason
# ---------------------------------------------------------------------------


class TestLifecycleEventRetry:
    def test_retry_event_with_replay_reason(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-q-001",
            device_id="device-q",
            execution_type=ExecutionType.goal_execution,
            event_kind="retry",
            replay_reason=ReplayReason.transient_failure_retry,
            detail="attempt 2/3",
        )
        assert event.event_kind == "retry"
        assert event.replay_reason == ReplayReason.transient_failure_retry

    def test_retry_event_dict_has_replay_reason(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-q-002",
            device_id="device-q",
            execution_type=ExecutionType.delegated_execution,
            event_kind="retry",
            replay_reason=ReplayReason.fallback_mode_retry,
        )
        d = event.to_dict()
        assert d["replay_reason"] == "fallback_mode_retry"
        assert d["interruption_reason"] is None


# ---------------------------------------------------------------------------
# R. record_execution_lifecycle_event — interruption
# ---------------------------------------------------------------------------


class TestLifecycleEventInterruption:
    def test_interruption_device_disconnected(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-r-001",
            device_id="device-r",
            execution_type=ExecutionType.parallel_subtask,
            event_kind="interruption",
            interruption_reason=InterruptionReason.device_disconnected,
        )
        assert event.event_kind == "interruption"
        assert event.interruption_reason == InterruptionReason.device_disconnected

    def test_interruption_higher_priority_preempted(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-r-002",
            device_id="device-r",
            execution_type=ExecutionType.goal_execution,
            event_kind="interruption",
            interruption_reason=InterruptionReason.higher_priority_preempted,
        )
        d = event.to_dict()
        assert d["interruption_reason"] == "higher_priority_preempted"


# ---------------------------------------------------------------------------
# S. record_execution_lifecycle_event — replay
# ---------------------------------------------------------------------------


class TestLifecycleEventReplay:
    def test_replay_operator_requested(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-s-001",
            device_id="device-s",
            execution_type=ExecutionType.goal_execution,
            event_kind="replay",
            replay_reason=ReplayReason.operator_requested_replay,
        )
        assert event.event_kind == "replay"
        assert event.replay_reason == ReplayReason.operator_requested_replay

    def test_replay_interruption_recovery(self):
        event = record_execution_lifecycle_event(
            execution_id="exec-s-002",
            device_id="device-s",
            execution_type=ExecutionType.delegated_execution,
            event_kind="replay",
            replay_reason=ReplayReason.interruption_recovery,
        )
        d = event.to_dict()
        assert d["replay_reason"] == "interruption_recovery"


# ---------------------------------------------------------------------------
# T. get_execution_lifecycle_history
# ---------------------------------------------------------------------------


class TestGetLifecycleHistory:
    def test_empty_when_no_events(self):
        history = get_execution_lifecycle_history("no-such-exec")
        assert history == []

    def test_returns_events_in_insertion_order(self):
        eid = "exec-t-001"
        record_execution_lifecycle_event(
            execution_id=eid, device_id="device-t",
            execution_type=ExecutionType.goal_execution, event_kind="failure",
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id="device-t",
            execution_type=ExecutionType.goal_execution, event_kind="retry",
            replay_reason=ReplayReason.transient_failure_retry,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id="device-t",
            execution_type=ExecutionType.goal_execution, event_kind="failure",
            detail="second attempt also failed",
        )
        history = get_execution_lifecycle_history(eid)
        assert len(history) == 3
        assert history[0].event_kind == "failure"
        assert history[1].event_kind == "retry"
        assert history[2].event_kind == "failure"

    def test_separate_executions_isolated(self):
        record_execution_lifecycle_event(
            execution_id="exec-t-a", device_id="device-t",
            execution_type=ExecutionType.goal_execution, event_kind="failure",
        )
        record_execution_lifecycle_event(
            execution_id="exec-t-b", device_id="device-t",
            execution_type=ExecutionType.parallel_subtask, event_kind="timeout",
        )
        assert len(get_execution_lifecycle_history("exec-t-a")) == 1
        assert len(get_execution_lifecycle_history("exec-t-b")) == 1


# ---------------------------------------------------------------------------
# U. record_result_uplink — result_uplink
# ---------------------------------------------------------------------------


class TestResultUplink:
    def test_result_uplink_recorded(self):
        rec = record_result_uplink(
            execution_id="exec-u-001",
            device_id="device-u",
            execution_type=ExecutionType.goal_execution,
            result_status="succeeded",
            success=True,
        )
        assert rec.execution_id == "exec-u-001"
        assert rec.uplink_kind == UplinkKind.result_uplink
        assert rec.result_status == "succeeded"
        assert rec.success is True

    def test_result_uplink_failure_fields(self):
        rec = record_result_uplink(
            execution_id="exec-u-002",
            device_id="device-u",
            execution_type=ExecutionType.goal_execution,
            result_status="failed",
            success=False,
            error_code="EXEC_TIMEOUT",
            failure_domain="transport",
        )
        assert rec.success is False
        assert rec.error_code == "EXEC_TIMEOUT"
        assert rec.failure_domain == "transport"

    def test_result_uplink_to_dict_serialisable(self):
        import json
        rec = record_result_uplink(
            execution_id="exec-u-003",
            device_id="device-u",
            execution_type=ExecutionType.delegated_execution,
            result_status="succeeded",
            success=True,
            payload={"steps_completed": 5},
        )
        d = rec.to_dict()
        json.dumps(d)  # must not raise
        assert d["uplink_kind"] == "result_uplink"
        assert d["payload"]["steps_completed"] == 5
        assert "_authority" in d


# ---------------------------------------------------------------------------
# V. record_result_uplink — state_uplink (intermediate)
# ---------------------------------------------------------------------------


class TestStateUplink:
    def test_state_uplink_non_terminal(self):
        rec = record_result_uplink(
            execution_id="exec-v-001",
            device_id="device-v",
            execution_type=ExecutionType.parallel_subtask,
            result_status="running",
            uplink_kind=UplinkKind.state_uplink,
            success=None,
        )
        assert rec.uplink_kind == UplinkKind.state_uplink
        assert rec.success is None
        assert rec.result_status == "running"


# ---------------------------------------------------------------------------
# W. record_result_uplink — interruption_uplink
# ---------------------------------------------------------------------------


class TestInterruptionUplink:
    def test_interruption_uplink_recorded(self):
        rec = record_result_uplink(
            execution_id="exec-w-001",
            device_id="device-w",
            execution_type=ExecutionType.takeover_request,
            result_status="interrupted",
            uplink_kind=UplinkKind.interruption_uplink,
            success=False,
            error_code="DEVICE_DISCONNECTED",
            failure_domain="device",
        )
        assert rec.uplink_kind == UplinkKind.interruption_uplink
        assert rec.result_status == "interrupted"


# ---------------------------------------------------------------------------
# X. get_uplink_truth_state — most recent record is canonical truth
# ---------------------------------------------------------------------------


class TestGetUplinkTruthState:
    def test_returns_none_when_no_uplinks(self):
        assert get_uplink_truth_state("no-exec") is None

    def test_returns_most_recent_uplink(self):
        eid = "exec-x-001"
        record_result_uplink(
            execution_id=eid, device_id="device-x",
            execution_type=ExecutionType.goal_execution,
            result_status="running", uplink_kind=UplinkKind.state_uplink, success=None,
        )
        record_result_uplink(
            execution_id=eid, device_id="device-x",
            execution_type=ExecutionType.goal_execution,
            result_status="succeeded", success=True,
        )
        truth = get_uplink_truth_state(eid)
        assert truth is not None
        assert truth.result_status == "succeeded"
        assert truth.success is True

    def test_intermediate_state_before_terminal(self):
        eid = "exec-x-002"
        record_result_uplink(
            execution_id=eid, device_id="device-x",
            execution_type=ExecutionType.delegated_execution,
            result_status="planning", uplink_kind=UplinkKind.state_uplink, success=None,
        )
        truth = get_uplink_truth_state(eid)
        assert truth.result_status == "planning"
        assert truth.uplink_kind == UplinkKind.state_uplink


# ---------------------------------------------------------------------------
# Y. get_all_uplink_records — chronological order
# ---------------------------------------------------------------------------


class TestGetAllUplinkRecords:
    def test_empty_when_no_uplinks(self):
        assert get_all_uplink_records("no-exec-y") == []

    def test_chronological_order(self):
        eid = "exec-y-001"
        record_result_uplink(
            execution_id=eid, device_id="device-y",
            execution_type=ExecutionType.goal_execution,
            result_status="planning", uplink_kind=UplinkKind.state_uplink, success=None,
        )
        record_result_uplink(
            execution_id=eid, device_id="device-y",
            execution_type=ExecutionType.goal_execution,
            result_status="running", uplink_kind=UplinkKind.state_uplink, success=None,
        )
        record_result_uplink(
            execution_id=eid, device_id="device-y",
            execution_type=ExecutionType.goal_execution,
            result_status="failed", success=False, error_code="ERR_001",
        )
        records = get_all_uplink_records(eid)
        assert len(records) == 3
        assert records[0].result_status == "planning"
        assert records[1].result_status == "running"
        assert records[2].result_status == "failed"


# ---------------------------------------------------------------------------
# Z. get_execution_lifecycle_matrix — structure
# ---------------------------------------------------------------------------


class TestLifecycleMatrix:
    def test_matrix_returns_dict(self):
        matrix = get_execution_lifecycle_matrix()
        assert isinstance(matrix, dict)

    def test_matrix_has_required_top_level_keys(self):
        matrix = get_execution_lifecycle_matrix()
        assert "execution_types" in matrix
        assert "priority_order" in matrix
        assert "blocking_rules" in matrix
        assert "_authority" in matrix
        assert "_contract_version" in matrix
        assert "_hardening_sentinel" in matrix

    def test_matrix_is_json_serialisable(self):
        import json
        matrix = get_execution_lifecycle_matrix()
        json.dumps(matrix)  # must not raise

    def test_hardening_sentinel_in_matrix(self):
        matrix = get_execution_lifecycle_matrix()
        assert EXECUTION_GOVERNANCE_HARDENING_SENTINEL in matrix["_hardening_sentinel"]


# ---------------------------------------------------------------------------
# AA. get_execution_lifecycle_matrix — all four types present
# ---------------------------------------------------------------------------


class TestLifecycleMatrixTypes:
    def test_all_four_types_in_matrix(self):
        matrix = get_execution_lifecycle_matrix()
        types = matrix["execution_types"]
        assert "goal_execution" in types
        assert "parallel_subtask" in types
        assert "takeover_request" in types
        assert "delegated_execution" in types

    def test_priority_order_has_four_types(self):
        matrix = get_execution_lifecycle_matrix()
        order = matrix["priority_order"]
        assert "goal_execution" in order
        assert "parallel_subtask" in order
        assert "takeover_request" in order
        assert "delegated_execution" in order

    def test_takeover_is_first_in_priority_order(self):
        matrix = get_execution_lifecycle_matrix()
        assert matrix["priority_order"][0] == "takeover_request"


# ---------------------------------------------------------------------------
# AB. get_execution_lifecycle_matrix — blocking_rules
# ---------------------------------------------------------------------------


class TestLifecycleMatrixBlockingRules:
    def test_blocking_rules_present(self):
        matrix = get_execution_lifecycle_matrix()
        rules = matrix["blocking_rules"]
        assert len(rules) >= 1

    def test_takeover_blocks_three_types(self):
        matrix = get_execution_lifecycle_matrix()
        takeover_rule = next(
            (r for r in matrix["blocking_rules"] if r["blocker"] == "takeover_request"),
            None,
        )
        assert takeover_rule is not None
        blocked = takeover_rule["blocks"]
        assert "goal_execution" in blocked
        assert "parallel_subtask" in blocked
        assert "delegated_execution" in blocked

    def test_blocking_rule_has_cancellation_reason(self):
        matrix = get_execution_lifecycle_matrix()
        takeover_rule = next(
            (r for r in matrix["blocking_rules"] if r["blocker"] == "takeover_request"),
            None,
        )
        assert takeover_rule is not None
        assert takeover_rule["cancellation_reason_for_blocked"] == (
            CancellationReason.higher_priority_execution.value
        )


# ---------------------------------------------------------------------------
# AC. get_execution_lifecycle_matrix — timeout governance per type
# ---------------------------------------------------------------------------


class TestLifecycleMatrixTimeout:
    def test_all_types_have_hard_timeout_in_matrix(self):
        matrix = get_execution_lifecycle_matrix()
        for type_name, type_info in matrix["execution_types"].items():
            tg = type_info["lifecycle_semantics"]["timeout_governance"]
            assert tg["policy"] == "hard", f"{type_name} should have hard timeout"
            assert tg["default_timeout_s"] is not None
            assert tg["hard_timeout_interruption_reason"] == "timeout_hard"

    def test_takeover_has_longest_timeout(self):
        matrix = get_execution_lifecycle_matrix()
        types = matrix["execution_types"]
        assert (
            types["takeover_request"]["lifecycle_semantics"]["timeout_governance"][
                "default_timeout_s"
            ]
            > types["goal_execution"]["lifecycle_semantics"]["timeout_governance"][
                "default_timeout_s"
            ]
        )


# ---------------------------------------------------------------------------
# AD. get_execution_lifecycle_matrix — retry_governance per type
# ---------------------------------------------------------------------------


class TestLifecycleMatrixRetryGovernance:
    def test_goal_has_transient_failure_retry(self):
        matrix = get_execution_lifecycle_matrix()
        rg = matrix["execution_types"]["goal_execution"]["lifecycle_semantics"][
            "retry_governance"
        ]
        assert rg["default_replay_reason"] == "transient_failure_retry"

    def test_delegated_has_fallback_mode_retry(self):
        matrix = get_execution_lifecycle_matrix()
        rg = matrix["execution_types"]["delegated_execution"]["lifecycle_semantics"][
            "retry_governance"
        ]
        assert rg["default_replay_reason"] == "fallback_mode_retry"

    def test_takeover_has_interruption_recovery(self):
        matrix = get_execution_lifecycle_matrix()
        rg = matrix["execution_types"]["takeover_request"]["lifecycle_semantics"][
            "retry_governance"
        ]
        assert rg["default_replay_reason"] == "interruption_recovery"


# ---------------------------------------------------------------------------
# AE. lifecycle event and uplink store cleared by _clear_all_active_executions
# ---------------------------------------------------------------------------


class TestStoreClearedOnReset:
    def test_lifecycle_events_cleared(self):
        record_execution_lifecycle_event(
            execution_id="exec-ae-001", device_id="device-ae",
            execution_type=ExecutionType.goal_execution, event_kind="failure",
        )
        assert len(get_execution_lifecycle_history("exec-ae-001")) == 1
        _clear_all_active_executions()
        assert len(get_execution_lifecycle_history("exec-ae-001")) == 0

    def test_uplink_records_cleared(self):
        record_result_uplink(
            execution_id="exec-ae-002", device_id="device-ae",
            execution_type=ExecutionType.goal_execution,
            result_status="succeeded", success=True,
        )
        assert get_uplink_truth_state("exec-ae-002") is not None
        _clear_all_active_executions()
        assert get_uplink_truth_state("exec-ae-002") is None


# ---------------------------------------------------------------------------
# AF. Full PR-06 sequence: delegated → state → failure → retry → result
# ---------------------------------------------------------------------------


class TestFullPR06Sequence:
    def test_delegated_full_lifecycle_sequence(self):
        device_id = "device-af"
        eid = "exec-af-001"

        # 1. Accept delegated_execution
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id=eid,
                register_if_accepted=True,
            )
        assert verdict.accepted is True

        # 2. State uplink: planning started
        record_result_uplink(
            execution_id=eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            result_status="planning", uplink_kind=UplinkKind.state_uplink, success=None,
        )

        # 3. Failure event
        record_execution_lifecycle_event(
            execution_id=eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            event_kind="failure", detail="transient network error",
        )

        # 4. Retry event
        record_execution_lifecycle_event(
            execution_id=eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            event_kind="retry",
            replay_reason=ReplayReason.transient_failure_retry,
        )

        # 5. Terminal result uplink: succeeded on retry
        record_result_uplink(
            execution_id=eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            result_status="succeeded", success=True,
        )

        # 6. Notify completed
        notify_execution_completed(device_id, ExecutionType.delegated_execution, eid)

        # Verify lifecycle history
        history = get_execution_lifecycle_history(eid)
        assert len(history) == 2
        assert history[0].event_kind == "failure"
        assert history[1].event_kind == "retry"
        assert history[1].replay_reason == ReplayReason.transient_failure_retry

        # Verify canonical uplink truth
        truth = get_uplink_truth_state(eid)
        assert truth.result_status == "succeeded"
        assert truth.success is True

        all_uplinks = get_all_uplink_records(eid)
        assert len(all_uplinks) == 2
        assert all_uplinks[0].uplink_kind == UplinkKind.state_uplink
        assert all_uplinks[1].uplink_kind == UplinkKind.result_uplink

        # Registry cleared
        assert get_active_execution_type(device_id) is None


# ---------------------------------------------------------------------------
# AG. Takeover preempts delegated_execution; interruption recorded
# ---------------------------------------------------------------------------


class TestTakeoverPreemptsDelegate:
    def test_takeover_preempts_and_interruption_recorded(self):
        device_id = "device-ag"
        del_eid = "exec-ag-del"
        tkv_eid = "exec-ag-tkv"

        # 1. Accept delegated_execution
        with _patch_mode_gate_pass():
            d_verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                execution_id=del_eid,
                register_if_accepted=True,
            )
        assert d_verdict.accepted is True

        # 2. Takeover arrives — accepted (higher priority, no conflict block on same-level)
        with _patch_mode_gate_pass():
            tkv_verdict = evaluate_execution_governance(
                ExecutionType.takeover_request,
                device_id,
                execution_id=tkv_eid,
                register_if_accepted=True,
            )
        assert tkv_verdict.accepted is True

        # 3. Record interruption for delegated_execution
        record_execution_lifecycle_event(
            execution_id=del_eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            event_kind="interruption",
            interruption_reason=InterruptionReason.higher_priority_preempted,
        )

        # 4. Record interruption_uplink
        record_result_uplink(
            execution_id=del_eid, device_id=device_id,
            execution_type=ExecutionType.delegated_execution,
            result_status="interrupted",
            uplink_kind=UplinkKind.interruption_uplink,
            success=False,
            error_code="PREEMPTED_BY_TAKEOVER",
        )

        # 5. Verify
        history = get_execution_lifecycle_history(del_eid)
        assert len(history) == 1
        assert history[0].interruption_reason == InterruptionReason.higher_priority_preempted

        truth = get_uplink_truth_state(del_eid)
        assert truth.uplink_kind == UplinkKind.interruption_uplink
        assert truth.error_code == "PREEMPTED_BY_TAKEOVER"

        # 6. New delegated blocked while takeover active
        with _patch_mode_gate_pass():
            new_del = evaluate_execution_governance(
                ExecutionType.delegated_execution,
                device_id,
                register_if_accepted=False,
            )
        assert new_del.accepted is False
        assert new_del.conflict is True


# ---------------------------------------------------------------------------
# AH. Multi-mode governance stability: all four types sequence
# ---------------------------------------------------------------------------


class TestMultiModeGovernanceStability:
    def test_all_four_types_lifecycle_sequence(self):
        device_id = "device-ah"

        # 1. goal_execution accepted
        with _patch_mode_gate_pass():
            g = evaluate_execution_governance(
                ExecutionType.goal_execution, device_id,
                execution_id="ah-goal-001", register_if_accepted=True,
            )
        assert g.accepted is True

        # 2. parallel_subtask accepted (same priority, different type)
        with _patch_mode_gate_pass():
            p = evaluate_execution_governance(
                ExecutionType.parallel_subtask, device_id,
                execution_id="ah-par-001", register_if_accepted=True,
            )
        assert p.accepted is True

        # 3. delegated_execution accepted
        with _patch_mode_gate_pass():
            d = evaluate_execution_governance(
                ExecutionType.delegated_execution, device_id,
                execution_id="ah-del-001", register_if_accepted=True,
            )
        assert d.accepted is True

        # 4. takeover arrives — blocks new goal/parallel/delegated
        with _patch_mode_gate_pass():
            tkv = evaluate_execution_governance(
                ExecutionType.takeover_request, device_id,
                execution_id="ah-tkv-001", register_if_accepted=True,
            )
        assert tkv.accepted is True
        assert is_takeover_active(device_id)

        # 5. New goal blocked
        with _patch_mode_gate_pass():
            g2 = evaluate_execution_governance(
                ExecutionType.goal_execution, device_id,
                register_if_accepted=False,
            )
        assert g2.accepted is False
        assert g2.conflict is True

        # 6. New parallel blocked
        with _patch_mode_gate_pass():
            p2 = evaluate_execution_governance(
                ExecutionType.parallel_subtask, device_id,
                register_if_accepted=False,
            )
        assert p2.accepted is False
        assert p2.conflict is True

        # 7. New delegated blocked
        with _patch_mode_gate_pass():
            d2 = evaluate_execution_governance(
                ExecutionType.delegated_execution, device_id,
                register_if_accepted=False,
            )
        assert d2.accepted is False
        assert d2.conflict is True

        # 8. Takeover completes — registry contains original goal/parallel/delegated
        notify_execution_completed(device_id, ExecutionType.takeover_request, "ah-tkv-001")
        assert not is_takeover_active(device_id)

        # 9. New delegated now accepted
        with _patch_mode_gate_pass():
            d3 = evaluate_execution_governance(
                ExecutionType.delegated_execution, device_id,
                register_if_accepted=False,
            )
        assert d3.accepted is True

        # 10. lifecycle matrix is stable throughout
        matrix = get_execution_lifecycle_matrix()
        assert "delegated_execution" in matrix["execution_types"]
        assert "goal_execution" in matrix["execution_types"]
        assert "parallel_subtask" in matrix["execution_types"]
        assert "takeover_request" in matrix["execution_types"]
