from __future__ import annotations

from unittest.mock import patch

import pytest

from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    FailureSemantic,
    InterruptionReason,
    ReplayReason,
    _clear_execution_governance_runtime_state,
    evaluate_execution_governance,
    get_execution_lifecycle_history,
    get_execution_lifecycle_matrix,
    get_execution_type_policy,
    get_uplink_truth_state,
    notify_execution_completed,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


@pytest.fixture(autouse=True)
def _reset_governance_runtime():
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


def _patch_mode_gate_pass():
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(True, [], "all gates pass"),
    )


def test_delegated_execution_policy_is_canonicalized():
    policy = get_execution_type_policy(ExecutionType.delegated_execution)
    assert policy is not None
    assert policy.failure_semantic == FailureSemantic.fallback_local
    assert policy.default_timeout_s == 240.0
    assert policy.max_concurrent_per_device == 2


def test_takeover_blocks_delegated_execution():
    device_id = "device-pr06-takeover-blocks-delegated"
    with _patch_mode_gate_pass():
        takeover = evaluate_execution_governance(
            ExecutionType.takeover_request,
            device_id,
            execution_id="tkv-pr06-001",
            register_if_accepted=True,
        )
        delegated = evaluate_execution_governance(
            ExecutionType.delegated_execution,
            device_id,
            execution_id="delegated-pr06-001",
            register_if_accepted=False,
        )
    assert takeover.accepted is True
    assert delegated.accepted is False
    assert delegated.conflict is True
    assert delegated.active_conflicting_type == ExecutionType.takeover_request


def test_execution_lifecycle_matrix_contains_all_modes_and_semantic_axes():
    matrix = get_execution_lifecycle_matrix()
    execution_types = matrix["execution_types"]
    assert "goal_execution" in execution_types
    assert "parallel_subtask" in execution_types
    assert "takeover_request" in execution_types
    assert "delegated_execution" in execution_types
    assert matrix["governance_semantics"]["failure"] == "failed"
    assert matrix["governance_semantics"]["timeout"] == "timed_out"
    assert matrix["governance_semantics"]["retry"] == "retrying"
    assert matrix["governance_semantics"]["replay"] == "replayed"
    assert matrix["governance_semantics"]["interruption"] == "interrupted"


def test_lifecycle_transition_rejects_invalid_jump():
    execution_id = "exec-pr06-invalid-jump"
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id="device-pr06",
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.created,
    )
    assert not record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id="device-pr06",
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.replayed,
    )
    history = get_execution_lifecycle_history(execution_id)
    assert [event["phase"] for event in history] == ["created"]


def test_failure_timeout_retry_replay_and_interruption_are_recorded():
    execution_id = "exec-pr06-ftrri"
    device_id = "device-pr06-ftrri"

    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.created,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.admitted,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.running,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.failed,
        failure_semantic=FailureSemantic.fallback_local,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.retrying,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.running,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.timed_out,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.replayed,
        replay_reason=ReplayReason.timeout_replay,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.running,
    )
    assert record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.delegated_execution,
        phase=ExecutionLifecyclePhase.interrupted,
        interruption_reason=InterruptionReason.operator_interrupt,
    )

    history = get_execution_lifecycle_history(execution_id)
    phases = [event["phase"] for event in history]
    assert phases == [
        "created",
        "admitted",
        "running",
        "failed",
        "retrying",
        "running",
        "timed_out",
        "replayed",
        "running",
        "interrupted",
    ]
    assert history[phases.index("created")]["attempt"] == 1
    assert history[phases.index("failed")]["attempt"] == 1
    assert history[phases.index("retrying")]["attempt"] == 2
    assert history[phases.index("timed_out")]["attempt"] == 2
    assert history[phases.index("replayed")]["attempt"] == 3


def test_result_and_state_uplink_are_mapped_into_canonical_truth():
    execution_id = "exec-pr06-uplink-truth"
    device_id = "device-pr06-uplink"
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
        phase=ExecutionLifecyclePhase.running,
        enforce_transition=False,
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"progress": 0.8, "stage": "executing"},
    )
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"status": "ok", "result_id": "res-001"},
    )
    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.succeeded,
    )

    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["lifecycle_phase"] == "succeeded"
    assert truth_state["is_terminal"] is True
    assert truth_state["state_uplink"]["stage"] == "executing"
    assert truth_state["result_uplink"]["status"] == "ok"
    assert truth_state["result_uplink_count"] == 1
    assert truth_state["state_uplink_count"] == 1


@pytest.mark.parametrize(
    "execution_type",
    [
        ExecutionType.goal_execution,
        ExecutionType.parallel_subtask,
        ExecutionType.takeover_request,
        ExecutionType.delegated_execution,
    ],
)
def test_governance_runtime_authority_is_stable_across_execution_modes(execution_type: ExecutionType):
    device_id = f"device-pr06-authority-{execution_type.value}"
    execution_id = f"exec-pr06-authority-{execution_type.value}"
    with _patch_mode_gate_pass():
        verdict = evaluate_execution_governance(
            execution_type,
            device_id,
            execution_id=execution_id,
            register_if_accepted=True,
        )
    assert verdict.accepted is True

    notify_execution_completed(
        device_id,
        execution_type,
        execution_id,
        completion_phase=ExecutionLifecyclePhase.succeeded,
    )
    truth_state = get_uplink_truth_state(execution_id)
    assert truth_state["lifecycle_phase"] == "succeeded"
    assert truth_state["is_terminal"] is True
