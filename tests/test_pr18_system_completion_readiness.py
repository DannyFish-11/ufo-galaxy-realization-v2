from __future__ import annotations

import pytest

from core.closed_loop_governance_consolidation import (
    ClosedLoopStage,
    query_closed_loop_governance_state,
)
from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    _clear_execution_governance_runtime_state,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


@pytest.fixture(autouse=True)
def _reset_governance_runtime():
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


def test_mature_closure_with_full_uplink():
    execution_id = "exec-pr18-mature-closure"
    device_id = "device-pr18-mature-closure"

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
        payload={"phase": "succeeded"},
    )

    view = query_closed_loop_governance_state(execution_id, device_id)
    assert view.stage == ClosedLoopStage.completion
    assert view.system_completion_ready is True
    assert view.system_completion_level == "mature_closed_loop"
    assert view.system_completion_gap_types == []


def test_partial_uplink_not_mature():
    execution_id = "exec-pr18-partial-uplink-gap"
    device_id = "device-pr18-partial-uplink-gap"

    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.succeeded,
        enforce_transition=False,
    )
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"status": "success"},
    )

    view = query_closed_loop_governance_state(execution_id, device_id)
    assert view.stage == ClosedLoopStage.completion
    assert view.system_completion_ready is False
    assert view.system_completion_level == "closed_with_gaps"
    assert set(view.system_completion_gap_types) == {
        "missing_state_uplink",
        "reconciliation_not_fully_accepted",
    }
    assert len(view.system_completion_gap_types) == 2


def test_conflicting_reports_not_mature():
    execution_id = "exec-pr18-conflict-gap"
    device_id = "device-pr18-conflict-gap"

    record_execution_lifecycle_event(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        phase=ExecutionLifecyclePhase.succeeded,
        enforce_transition=False,
    )
    record_result_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"status": "failed"},
    )
    record_state_uplink(
        execution_id=execution_id,
        device_id=device_id,
        execution_type=ExecutionType.goal_execution,
        payload={"phase": "succeeded"},
    )

    view = query_closed_loop_governance_state(execution_id, device_id)
    assert view.stage == ClosedLoopStage.completion
    assert view.system_completion_ready is False
    assert set(view.system_completion_gap_types) == {
        "reconciliation_conflict_present",
        "reconciliation_not_fully_accepted",
    }
    assert len(view.system_completion_gap_types) == 2


def test_recovered_runtime_not_mature():
    execution_id = "exec-pr18-recovered-runtime-gap"
    device_id = "device-pr18-recovered-runtime-gap"

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
        payload={"phase": "succeeded", "recovered": True, "reason": "post_outage"},
    )

    view = query_closed_loop_governance_state(execution_id, device_id)
    assert view.stage == ClosedLoopStage.completion
    assert view.system_completion_ready is False
    assert "runtime_health_not_stable" in view.system_completion_gap_types


def test_degraded_runtime_not_mature():
    execution_id = "exec-pr18-degraded-runtime-gap"
    device_id = "device-pr18-degraded-runtime-gap"

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
        payload={"phase": "succeeded", "degraded": True, "reason": "latency_spike"},
    )

    view = query_closed_loop_governance_state(execution_id, device_id)
    assert view.stage == ClosedLoopStage.completion
    assert view.system_completion_ready is False
    assert "runtime_health_not_stable" in view.system_completion_gap_types
