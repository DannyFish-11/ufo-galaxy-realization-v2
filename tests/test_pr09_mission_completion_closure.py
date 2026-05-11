from __future__ import annotations

from unittest.mock import patch

import pytest

from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    _clear_execution_governance_runtime_state,
    get_uplink_truth_state,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


@pytest.fixture(autouse=True)
def _reset_governance_runtime():
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


@pytest.mark.parametrize(
    ("phase", "expected_terminal_outcome"),
    [
        (ExecutionLifecyclePhase.succeeded, "success"),
        (ExecutionLifecyclePhase.failed, "failure"),
        (ExecutionLifecyclePhase.timed_out, "timeout"),
        (ExecutionLifecyclePhase.cancelled, "aborted"),
        (ExecutionLifecyclePhase.interrupted, "interrupted"),
    ],
)
def test_center_terminal_truth_distinguishes_terminal_families(
    phase: ExecutionLifecyclePhase,
    expected_terminal_outcome: str,
):
    execution_id = f"exec-pr09-terminal-{phase.value}"
    device_id = f"device-pr09-terminal-{phase.value}"
    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.created,
    )
    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=phase,
        enforce_transition=False,
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["is_terminal"] is True
    assert truth_state["canonical_terminal_outcome"] == expected_terminal_outcome
    assert truth_state["terminal_truth_authoritative_source"] == "center_lifecycle"
    assert truth_state["terminal_truth_determined"] is True


def test_uplink_only_partial_success_is_canonically_classified():
    execution_id = "exec-pr09-uplink-only-partial-success"
    device_id = "device-pr09-uplink-only-partial-success"
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "success", "result_id": "r1"},
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "failed", "reason": "device_b_timeout"},
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["lifecycle_phase"] is None
    assert truth_state["canonical_terminal_outcome"] == "partial_success"
    assert truth_state["terminal_truth_authoritative_source"] == "reported_uplink"
    assert truth_state["reconciliation_status"] == "uplink_only_terminal_observation"


def test_uplink_only_dual_confirmed_terminal_outcome_can_be_authoritative():
    execution_id = "exec-pr09-uplink-only-dual-confirmed"
    device_id = "device-pr09-uplink-only-dual-confirmed"
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "success"},
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "success"},
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["lifecycle_phase"] is None
    assert truth_state["terminal_truth_determined"] is True
    assert truth_state["canonical_terminal_outcome"] == "success"
    assert truth_state["terminal_truth_authoritative_source"] == "reported_uplink"
    assert truth_state["reconciliation_uplink_terminal_confirmation"] == "cross_uplink_confirmed"


def test_uplink_only_conflicting_terminal_outcomes_require_reconciliation():
    execution_id = "exec-pr09-uplink-only-terminal-conflict"
    device_id = "device-pr09-uplink-only-terminal-conflict"
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "timeout"},
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.parallel_subtask,
        payload={"status": "failed", "reason": "executor_crash"},
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["lifecycle_phase"] is None
    assert truth_state["terminal_truth_determined"] is False
    assert truth_state["canonical_terminal_outcome"] is None
    assert truth_state["terminal_truth_authoritative_source"] == "none"
    assert truth_state["reconciliation_status"] == "uplink_terminal_observation_requires_reconciliation"
    assert truth_state["reconciliation_uplink_terminal_confirmation"] == "conflicting_terminal_unresolved"


def test_holds_terminal_report_during_non_terminal_lifecycle():
    execution_id = "exec-pr09-terminal-held"
    device_id = "device-pr09-terminal-held"
    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.running,
        enforce_transition=False,
    )
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"status": "failed"},
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["is_terminal"] is False
    assert truth_state["canonical_terminal_outcome"] is None
    assert truth_state["reconciliation_status"] == "terminal_observation_held_for_lifecycle_authority"
    assert truth_state["reconciliation_terminal_observation_held"] is True


def test_delayed_conflicting_terminal_outcome_retains_center_authority():
    execution_id = "exec-pr09-delayed-timeout-conflict"
    device_id = "device-pr09-delayed-timeout-conflict"
    with patch("core.unified_execution_governance.time.time", side_effect=[100.0, 101.0, 105.0]):
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.timed_out,
            enforce_transition=False,
        )
        record_result_uplink(
            execution_id=execution_id,
            device_id=device_id,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "success"},
        )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["canonical_terminal_outcome"] == "timeout"
    assert truth_state["reported_terminal_outcome"] == "success"
    assert truth_state["reconciliation_conflict"] is True
    assert truth_state["reconciliation_delayed_observation"] is True
    assert truth_state["reconciliation_status"] == "delayed_conflict_center_truth_retained"


def test_terminal_truth_remains_stable_during_degraded_recovery_observations():
    execution_id = "exec-pr09-terminal-degraded-recovery"
    device_id = "device-pr09-terminal-degraded-recovery"
    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.succeeded,
        enforce_transition=False,
    )
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        payload={"status": "ok"},
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        payload={"phase": "succeeded", "degraded": True, "reason": "network_pressure"},
    )
    degraded_truth = get_uplink_truth_state(execution_id)
    assert degraded_truth["canonical_terminal_outcome"] == "success"
    assert degraded_truth["canonical_runtime_health"] == "degraded"

    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        payload={"phase": "succeeded", "recovered": True, "reason": "link_restored"},
    )
    recovered_truth = get_uplink_truth_state(execution_id)
    assert recovered_truth["canonical_terminal_outcome"] == "success"
    assert recovered_truth["canonical_runtime_health"] == "recovered"
    assert recovered_truth["terminal_truth_authoritative_source"] == "center_lifecycle"
