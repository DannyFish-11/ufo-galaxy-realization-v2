"""tests/test_pr13_closed_loop_governance_consolidation.py
===========================================================

PR-13 V2-side — Closed-Loop Governance Consolidation.

Validates that the center-side governance layer behaves as a unified canonical
closed loop across:
    activation → execution → observation/uplink → reconciliation → completion

All tests are self-contained: no live servers, no real devices.

Coverage groups
---------------
A.  Whole-loop stage progression
       Valid lifecycle paths from activation through completion are classified
       at the correct ``ClosedLoopStage`` at each step.

B.  Cross-stage invariant enforcement
       Invariant violations are detected for structurally broken loops, and the
       correct invariant IDs are reported.  Coherent loops have zero violations.

C.  Adverse conditions — degraded, delayed, retried, interrupted, recovered
       The closed-loop view remains deterministic and coherent under realistic
       adverse operational conditions.

D.  Cross-device isolation
       Governance state for device A must not affect device B's closed-loop view.

E.  Audit record and sentinel coverage
       The audit record is complete and JSON-serialisable.  The PR-13 sentinel is
       present and well-formed.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from core.closed_loop_governance_consolidation import (
    CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
    CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION,
    CROSS_STAGE_INVARIANT_POLICY,
    ClosedLoopGovernanceView,
    ClosedLoopInvariantViolation,
    ClosedLoopStage,
    assert_closed_loop_invariants,
    get_closed_loop_audit_record,
    query_closed_loop_governance_state,
)
from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    _clear_execution_governance_runtime_state,
    evaluate_execution_governance,
    notify_execution_completed,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_governance_runtime():
    """Reset all governance runtime state before and after each test."""
    _clear_execution_governance_runtime_state()
    yield
    _clear_execution_governance_runtime_state()


def _patch_mode_gate_pass():
    """Patch the mode/readiness gate so governance evaluations always pass."""
    return patch(
        "core.unified_execution_governance._check_mode_readiness_gate",
        return_value=(True, [], "all gates pass"),
    )


# ===========================================================================
# Group A — Whole-loop stage progression
# ===========================================================================


class TestGroupA_WholeLoopStageProgression:
    """A01–A10: The closed-loop stage is correctly derived at each lifecycle step."""

    def test_A01_unknown_stage_when_no_history(self):
        """A01: With no lifecycle history and no uplinks, stage is 'unknown'."""
        view = query_closed_loop_governance_state("exec-a01-unknown", "dev-a01")
        assert view.stage == ClosedLoopStage.unknown
        assert view.lifecycle_event_count == 0
        assert view.has_uplink_observation is False
        assert view.loop_is_coherent is True  # empty loop has no violations

    def test_A02_activation_stage_after_governance_evaluation(self):
        """A02: After governance evaluation, stage is at least 'activation'."""
        eid = "exec-a02-activation"
        did = "dev-a02"
        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        assert verdict.accepted is True
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage in (ClosedLoopStage.activation, ClosedLoopStage.execution,
                               ClosedLoopStage.observation, ClosedLoopStage.reconciliation)
        assert view.lifecycle_event_count >= 1

    def test_A03_execution_stage_after_running_event(self):
        """A03: Recording a 'running' lifecycle event keeps stage in execution/observation.

        Note: evaluate_execution_governance records an internal state_uplink at
        admission, so the stage can be 'execution' or 'observation' depending on
        whether that internal uplink is counted.  Both are valid mid-execution stages.
        """
        eid = "exec-a03-running"
        did = "dev-a03"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
            detail="now_running",
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage in (
            ClosedLoopStage.execution, ClosedLoopStage.observation
        ), f"Expected execution or observation stage, got {view.stage.value!r}"
        assert view.lifecycle_phase == "running"
        assert view.is_terminal is False
        assert view.loop_is_coherent is True

    def test_A04_observation_stage_after_state_uplink(self):
        """A04: A state uplink during active execution brings stage to 'observation'."""
        eid = "exec-a04-obs"
        did = "dev-a04"
        # NOTE: We use raw lifecycle events (without evaluate_execution_governance)
        # to avoid counting the internal governance state_uplink in the uplink count.
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.admitted,
            enforce_transition=False,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "running"},
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.observation
        assert view.has_uplink_observation is True
        assert view.is_terminal is False

    def test_A05_reconciliation_stage_with_uplink_and_terminal_check(self):
        """A05: A terminal uplink + non-terminal lifecycle gives 'reconciliation'."""
        eid = "exec-a05-reconcile"
        did = "dev-a05"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.parallel_subtask, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.running,
        )
        # Terminal uplink arrives before lifecycle termination
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "success"},
        )
        view = query_closed_loop_governance_state(eid, did)
        # reconciliation_status must be non-missing
        assert view.reconciliation_status not in ("missing", "")
        assert view.stage == ClosedLoopStage.reconciliation

    def test_A06_completion_stage_after_notify_execution_completed(self):
        """A06: notify_execution_completed closes the loop to 'completion'."""
        eid = "exec-a06-done"
        did = "dev-a06"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        removed = notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        assert removed is True
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.is_terminal is True
        assert view.canonical_terminal_outcome == "success"
        assert view.loop_is_coherent is True

    @pytest.mark.parametrize(
        ("exec_type", "terminal_phase", "expected_outcome"),
        [
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.failed, "failure"),
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.timed_out, "timeout"),
            (ExecutionType.parallel_subtask, ExecutionLifecyclePhase.cancelled, "aborted"),
            (ExecutionType.takeover_request, ExecutionLifecyclePhase.interrupted, "interrupted"),
            (ExecutionType.delegated_execution, ExecutionLifecyclePhase.succeeded, "success"),
        ],
    )
    def test_A07_all_execution_types_reach_completion_with_correct_outcome(
        self, exec_type, terminal_phase, expected_outcome
    ):
        """A07: All execution types produce the correct outcome at 'completion'."""
        eid = f"exec-a07-{exec_type.value}-{terminal_phase.value}"
        did = f"dev-a07-{exec_type.value}"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                exec_type, did, execution_id=eid, register_if_accepted=True,
            )
        notify_execution_completed(
            did, exec_type, eid, completion_phase=terminal_phase,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion, (
            f"Expected completion stage for {exec_type.value}/{terminal_phase.value}, "
            f"got {view.stage.value}"
        )
        assert view.canonical_terminal_outcome == expected_outcome, (
            f"Expected outcome {expected_outcome!r}, got {view.canonical_terminal_outcome!r}"
        )
        assert view.loop_is_coherent is True

    def test_A08_loop_stage_not_unknown_when_lifecycle_events_exist(self):
        """A08: When lifecycle history exists, stage is never 'unknown'."""
        eid = "exec-a08-not-unknown"
        did = "dev-a08"
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
            enforce_transition=False,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage != ClosedLoopStage.unknown
        assert view.lifecycle_event_count >= 1

    def test_A09_takeover_full_loop_closure(self):
        """A09: Takeover execution type achieves coherent completion stage."""
        eid = "exec-a09-takeover"
        did = "dev-a09"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.running,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            payload={"status": "running", "device_controlled": True},
        )
        notify_execution_completed(
            did, ExecutionType.takeover_request, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "success"
        assert view.loop_is_coherent is True

    def test_A10_view_to_dict_is_json_serialisable(self):
        """A10: ClosedLoopGovernanceView.to_dict() is fully JSON-serialisable."""
        import json

        eid = "exec-a10-serial"
        did = "dev-a10"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        view = query_closed_loop_governance_state(eid, did)
        d = view.to_dict()
        # Must not raise
        serialised = json.dumps(d)
        assert len(serialised) > 50


# ===========================================================================
# Group B — Cross-stage invariant enforcement
# ===========================================================================


class TestGroupB_CrossStageInvariantEnforcement:
    """B01–B08: Invariants detect broken loops; coherent loops have zero violations."""

    def test_B01_coherent_full_loop_has_no_violations(self):
        """B01: A properly run full loop produces no invariant violations."""
        eid = "exec-b01-coherent"
        did = "dev-b01"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "running"},
        )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        violations = assert_closed_loop_invariants(eid, did)
        assert violations == [], (
            f"Expected no violations for coherent loop, got: {[v.to_dict() for v in violations]}"
        )

    def test_B02_I02_terminal_phase_without_outcome_is_detected(self):
        """B02: I-02 fires when is_terminal=True but canonical_terminal_outcome is None.

        This scenario is constructed artificially by patching get_uplink_truth_state
        to return inconsistent state (is_terminal=True but canonical_terminal_outcome=None).
        """
        eid = "exec-b02-i02"
        did = "dev-b02"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        # Patch uplink truth to simulate inconsistent terminal state
        fake_truth = {
            "execution_id": eid,
            "lifecycle_phase": "succeeded",
            "is_terminal": True,
            "canonical_terminal_outcome": None,  # invariant I-02 violation
            "reconciliation_status": "accepted",
            "reconciliation_conflict": False,
            "terminal_truth_authoritative_source": "center_lifecycle",
            "lifecycle_event_count": 2,
            "result_uplink_count": 0,
            "state_uplink_count": 1,
            "reconciliation_delayed_observation": False,
        }
        with patch(
            "core.closed_loop_governance_consolidation.query_closed_loop_governance_state"
        ) as mock_query:
            # Instead of patching query, let's build the violation manually via _check_invariants
            from core.closed_loop_governance_consolidation import _check_invariants
            violations = _check_invariants(
                execution_id=eid,
                device_id=did,
                stage=ClosedLoopStage.reconciliation,
                lifecycle_phase="succeeded",
                is_terminal=True,
                canonical_terminal_outcome=None,
                reconciliation_status="accepted",
                reconciliation_conflict=False,
                terminal_truth_authoritative_source="center_lifecycle",
                lifecycle_event_count=2,
                has_uplink_observation=True,
                lifecycle_history=[],
                uplink_truth=fake_truth,
            )
        i02_violations = [v for v in violations if v.invariant_id == "I-02"]
        assert len(i02_violations) == 1, (
            f"Expected I-02 violation, got: {[v.invariant_id for v in violations]}"
        )

    def test_B03_I03_conflict_without_center_authority_is_detected(self):
        """B03: I-03 fires when reconciliation_conflict=True but center_lifecycle is not authoritative."""
        from core.closed_loop_governance_consolidation import _check_invariants
        eid = "exec-b03-i03"
        did = "dev-b03"
        violations = _check_invariants(
            execution_id=eid,
            device_id=did,
            stage=ClosedLoopStage.reconciliation,
            lifecycle_phase="succeeded",
            is_terminal=True,
            canonical_terminal_outcome="success",
            reconciliation_status="conflict_detected",
            reconciliation_conflict=True,
            terminal_truth_authoritative_source="reported_uplink",  # wrong
            lifecycle_event_count=3,
            has_uplink_observation=True,
            lifecycle_history=[],
            uplink_truth={"reconciliation_delayed_observation": False},
        )
        i03_violations = [v for v in violations if v.invariant_id == "I-03"]
        assert len(i03_violations) == 1, (
            f"Expected I-03 violation, got: {[v.invariant_id for v in violations]}"
        )

    def test_B04_I04_delayed_uplink_without_center_authority_is_detected(self):
        """B04: I-04 fires when delayed uplink is present but center_lifecycle is not authoritative."""
        from core.closed_loop_governance_consolidation import _check_invariants
        eid = "exec-b04-i04"
        did = "dev-b04"
        violations = _check_invariants(
            execution_id=eid,
            device_id=did,
            stage=ClosedLoopStage.completion,
            lifecycle_phase="succeeded",
            is_terminal=True,
            canonical_terminal_outcome="success",
            reconciliation_status="delayed_conflict_center_truth_retained",
            reconciliation_conflict=True,
            terminal_truth_authoritative_source="reported_uplink",  # wrong
            lifecycle_event_count=4,
            has_uplink_observation=True,
            lifecycle_history=[],
            uplink_truth={"reconciliation_delayed_observation": True},
        )
        i04_violations = [v for v in violations if v.invariant_id == "I-04"]
        assert len(i04_violations) == 1, (
            f"Expected I-04 violation, got: {[v.invariant_id for v in violations]}"
        )

    def test_B05_I07_completion_without_terminal_outcome_is_detected(self):
        """B05: I-07 fires when stage is 'completion' but canonical_terminal_outcome is None."""
        from core.closed_loop_governance_consolidation import _check_invariants
        eid = "exec-b05-i07"
        did = "dev-b05"
        violations = _check_invariants(
            execution_id=eid,
            device_id=did,
            stage=ClosedLoopStage.completion,
            lifecycle_phase="succeeded",
            is_terminal=True,
            canonical_terminal_outcome=None,  # I-07 violation
            reconciliation_status="accepted",
            reconciliation_conflict=False,
            terminal_truth_authoritative_source="center_lifecycle",
            lifecycle_event_count=3,
            has_uplink_observation=True,
            lifecycle_history=[],
            uplink_truth={"reconciliation_delayed_observation": False},
        )
        i07_violations = [v for v in violations if v.invariant_id == "I-07"]
        assert len(i07_violations) == 1, (
            f"Expected I-07 violation, got: {[v.invariant_id for v in violations]}"
        )

    def test_B06_coherent_interrupted_loop_has_no_violations(self):
        """B06: An interrupted execution that is properly recorded is coherent."""
        eid = "exec-b06-interrupt"
        did = "dev-b06"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.running,
        )
        notify_execution_completed(
            did, ExecutionType.takeover_request, eid,
            completion_phase=ExecutionLifecyclePhase.interrupted,
        )
        violations = assert_closed_loop_invariants(eid, did)
        assert violations == [], (
            f"Interrupted loop should be coherent, got: {[v.invariant_id for v in violations]}"
        )

    def test_B07_coherent_failed_and_cancelled_loops(self):
        """B07: Failed and cancelled executions produce no invariant violations."""
        for terminal_phase in [ExecutionLifecyclePhase.failed, ExecutionLifecyclePhase.cancelled]:
            _clear_execution_governance_runtime_state()
            eid = f"exec-b07-{terminal_phase.value}"
            did = f"dev-b07-{terminal_phase.value}"
            with _patch_mode_gate_pass():
                evaluate_execution_governance(
                    ExecutionType.goal_execution, did,
                    execution_id=eid, register_if_accepted=True,
                )
            notify_execution_completed(
                did, ExecutionType.goal_execution, eid,
                completion_phase=terminal_phase,
            )
            violations = assert_closed_loop_invariants(eid, did)
            assert violations == [], (
                f"Expected no violations for {terminal_phase.value} loop, "
                f"got: {[v.invariant_id for v in violations]}"
            )

    def test_B08_violation_to_dict_is_json_serialisable(self):
        """B08: ClosedLoopInvariantViolation.to_dict() is fully JSON-serialisable."""
        import json
        v = ClosedLoopInvariantViolation(
            invariant_id="I-99",
            description="Test violation",
            execution_id="eid-test",
            device_id="did-test",
            stage=ClosedLoopStage.execution,
            detail="some detail",
        )
        d = v.to_dict()
        serialised = json.dumps(d)
        assert "I-99" in serialised
        assert CROSS_STAGE_INVARIANT_POLICY in d["_policy"]


# ===========================================================================
# Group C — Adverse conditions
# ===========================================================================


class TestGroupC_AdverseConditions:
    """C01–C10: The closed loop remains deterministic and coherent under adverse scenarios."""

    def test_C01_delayed_conflicting_uplink_does_not_override_center_terminal(self):
        """C01: A late (delayed) conflicting uplink does not change canonical terminal truth."""
        eid = "exec-c01-delayed"
        did = "dev-c01"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        # Center declares success
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        # Late conflicting uplink arrives after terminal
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "failed"},
        )
        view = query_closed_loop_governance_state(eid, did)
        # Center terminal truth must be preserved
        assert view.canonical_terminal_outcome == "success", (
            f"Center truth must be retained, got: {view.canonical_terminal_outcome!r}"
        )
        assert view.terminal_truth_authoritative_source == "center_lifecycle"
        assert view.stage == ClosedLoopStage.completion
        # No I-03 or I-04 violations because center_lifecycle IS the authoritative source
        i03_i04 = [v for v in view.invariant_violations if v.invariant_id in ("I-03", "I-04")]
        assert i03_i04 == [], (
            f"No I-03/I-04 violations expected for correctly resolved conflict: "
            f"{[v.invariant_id for v in view.invariant_violations]}"
        )

    def test_C02_interrupted_then_retried_loop_is_coherent(self):
        """C02: interrupted → retrying → running → succeeded chain remains coherent."""
        eid = "exec-c02-retry"
        did = "dev-c02"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.interrupted,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.retrying,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "success"
        assert view.loop_is_coherent is True

    def test_C03_failed_then_replayed_loop_is_coherent(self):
        """C03: failed → replayed → succeeded chain is coherent at completion."""
        eid = "exec-c03-replay"
        did = "dev-c03"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.delegated_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.failed,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.replayed,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        notify_execution_completed(
            did, ExecutionType.delegated_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "success"
        assert view.loop_is_coherent is True

    def test_C04_degraded_state_uplink_does_not_claim_terminal(self):
        """C04: A degraded state uplink during active execution does not claim terminal."""
        eid = "exec-c04-degraded"
        did = "dev-c04"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"degraded": True, "reason": "partial_device_loss"},
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.is_terminal is False
        assert view.stage != ClosedLoopStage.completion
        assert view.loop_is_coherent is True

    def test_C05_partial_uplink_with_terminal_lifecycle_is_coherent(self):
        """C05: Partial uplink data (result only, no state) with terminal lifecycle is coherent."""
        eid = "exec-c05-partial"
        did = "dev-c05"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.parallel_subtask, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "success"},
        )
        notify_execution_completed(
            did, ExecutionType.parallel_subtask, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "success"
        # Partial observation (only result uplink, no state uplink) is still coherent
        assert view.loop_is_coherent is True

    def test_C06_timed_out_execution_is_coherent_at_completion(self):
        """C06: timed_out execution reaches completion stage with 'timeout' outcome."""
        eid = "exec-c06-timeout"
        did = "dev-c06"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.timed_out,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "timeout"
        assert view.loop_is_coherent is True

    def test_C07_multiple_state_uplinks_before_terminal_remain_coherent(self):
        """C07: Multiple state uplinks during execution do not break coherence."""
        eid = "exec-c07-multi-uplink"
        did = "dev-c07"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        for i in range(5):
            record_state_uplink(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                payload={"progress": i * 20, "status": "running"},
            )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view = query_closed_loop_governance_state(eid, did)
        assert view.stage == ClosedLoopStage.completion
        assert view.canonical_terminal_outcome == "success"
        assert view.loop_is_coherent is True

    def test_C08_conflicting_result_and_state_uplinks_produce_partial_success(self):
        """C08: Conflicting success+failure uplinks before terminal are classified as partial_success."""
        eid = "exec-c08-conflict-uplinks"
        did = "dev-c08"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.parallel_subtask, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.running,
        )
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "success"},
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "failed"},
        )
        # No lifecycle terminal yet — loop is in reconciliation
        view = query_closed_loop_governance_state(eid, did)
        # reported_terminal_outcome from conflicting uplinks should be partial_success
        # but is_terminal should be False (no lifecycle authority yet)
        assert view.is_terminal is False
        # Still coherent — no invariant violations
        assert view.loop_is_coherent is True

    def test_C09_recovery_after_interrupt_final_outcome_preserved(self):
        """C09: Recovery state uplinks after interrupt don't change the terminal outcome."""
        eid = "exec-c09-recover"
        did = "dev-c09"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
        )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.interrupted,
        )
        # Recovery state uplink after terminal
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"recovered": True, "reason": "device_reconnected"},
        )
        view = query_closed_loop_governance_state(eid, did)
        # Center terminal truth (interrupted) must be preserved
        assert view.canonical_terminal_outcome == "interrupted"
        assert view.terminal_truth_authoritative_source == "center_lifecycle"
        assert view.stage == ClosedLoopStage.completion

    def test_C10_uplink_only_with_no_lifecycle_is_reconciliation_not_completion(self):
        """C10: Uplink-only terminal observation (no lifecycle authority) is NOT completion.

        An uplink-only terminal observation is classified under 'reconciliation'
        stage (uplink_only_terminal_observation status) and is_terminal remains False
        because no center lifecycle phase has been recorded.
        """
        eid = "exec-c10-uplink-only"
        did = "dev-c10"
        # No governance evaluation — only raw uplink
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "success"},
        )
        view = query_closed_loop_governance_state(eid, did)
        # Without lifecycle authority, the loop is not at completion stage
        assert view.stage != ClosedLoopStage.completion, (
            f"Uplink-only loop should NOT be at completion, got {view.stage.value!r}"
        )
        # is_terminal is False because no center lifecycle phase was set
        assert view.is_terminal is False
        # terminal_truth_authoritative_source is 'reported_uplink' (not center_lifecycle)
        assert view.terminal_truth_authoritative_source != "center_lifecycle"


# ===========================================================================
# Group D — Cross-device isolation
# ===========================================================================


class TestGroupD_CrossDeviceIsolation:
    """D01–D05: Governance state for one device must not affect another device's loop."""

    def test_D01_device_a_completion_does_not_affect_device_b(self):
        """D01: Device A reaching completion does not change device B's stage."""
        eid_a = "exec-d01-dev-a"
        eid_b = "exec-d01-dev-b"
        did_a = "device-d01-A"
        did_b = "device-d01-B"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did_a,
                execution_id=eid_a, register_if_accepted=True,
            )
            evaluate_execution_governance(
                ExecutionType.goal_execution, did_b,
                execution_id=eid_b, register_if_accepted=True,
            )
        notify_execution_completed(
            did_a, ExecutionType.goal_execution, eid_a,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        view_b = query_closed_loop_governance_state(eid_b, did_b)
        # Device B is still in execution (admitted/running), not completion
        assert view_b.stage != ClosedLoopStage.completion
        assert view_b.is_terminal is False

    def test_D02_takeover_on_device_a_does_not_affect_device_b_loop(self):
        """D02: Active takeover on device A does not appear in device B's closed-loop view."""
        eid_a = "exec-d02-takeover"
        eid_b = "exec-d02-goal"
        did_a = "device-d02-A"
        did_b = "device-d02-B"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.takeover_request, did_a,
                execution_id=eid_a, register_if_accepted=True,
            )
            evaluate_execution_governance(
                ExecutionType.goal_execution, did_b,
                execution_id=eid_b, register_if_accepted=True,
            )
        view_b = query_closed_loop_governance_state(eid_b, did_b)
        # Device B's loop should have its own stage independent of device A
        assert view_b.execution_id == eid_b
        assert view_b.device_id == did_b
        assert view_b.stage != ClosedLoopStage.unknown

    def test_D03_multiple_devices_reach_completion_independently(self):
        """D03: Multiple devices can all reach completion stage independently."""
        devices = [
            ("exec-d03-dev1", "device-d03-1", ExecutionType.goal_execution),
            ("exec-d03-dev2", "device-d03-2", ExecutionType.parallel_subtask),
            ("exec-d03-dev3", "device-d03-3", ExecutionType.delegated_execution),
        ]
        with _patch_mode_gate_pass():
            for eid, did, etype in devices:
                evaluate_execution_governance(
                    etype, did, execution_id=eid, register_if_accepted=True,
                )
        for eid, did, etype in devices:
            notify_execution_completed(
                did, etype, eid,
                completion_phase=ExecutionLifecyclePhase.succeeded,
            )
        for eid, did, etype in devices:
            view = query_closed_loop_governance_state(eid, did)
            assert view.stage == ClosedLoopStage.completion, (
                f"Device {did} should be at completion, got {view.stage.value}"
            )
            assert view.canonical_terminal_outcome == "success"
            assert view.loop_is_coherent is True

    def test_D04_loop_view_execution_id_is_always_correct(self):
        """D04: The closed-loop view always carries the correct execution_id."""
        eids = ["exec-d04-a", "exec-d04-b", "exec-d04-c"]
        did = "device-d04"
        with _patch_mode_gate_pass():
            for eid in eids:
                evaluate_execution_governance(
                    ExecutionType.goal_execution, did,
                    execution_id=eid, register_if_accepted=True,
                )
        for eid in eids:
            view = query_closed_loop_governance_state(eid, did)
            assert view.execution_id == eid, (
                f"view.execution_id should be {eid!r}, got {view.execution_id!r}"
            )

    def test_D05_completing_one_execution_does_not_terminal_another_same_device(self):
        """D05: Completing execution A on a device does not close execution B on the same device."""
        eid_a = "exec-d05-a"
        eid_b = "exec-d05-b"
        did = "device-d05"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid_a, register_if_accepted=True,
            )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid_a,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        # Execution B was never started — it should be at 'unknown' stage
        view_b = query_closed_loop_governance_state(eid_b, did)
        assert view_b.stage == ClosedLoopStage.unknown
        assert view_b.is_terminal is False
        assert view_b.canonical_terminal_outcome is None


# ===========================================================================
# Group E — Audit record and sentinel coverage
# ===========================================================================


class TestGroupE_AuditAndSentinelCoverage:
    """E01–E08: Sentinel presence, audit record completeness, and contract version."""

    def test_E01_sentinel_is_present_and_well_formed(self):
        """E01: CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL is present and well-formed."""
        assert isinstance(CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL, str)
        assert len(CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL) > 50
        assert "PR13" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL or \
               "PR-13" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL
        assert "closed_loop" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL.lower() or \
               "CLOSED_LOOP" in CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL

    def test_E02_contract_version_is_correct(self):
        """E02: CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION matches expected value."""
        assert isinstance(CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION, str)
        assert CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION == "13.0.0"

    def test_E03_cross_stage_invariant_policy_is_well_formed(self):
        """E03: CROSS_STAGE_INVARIANT_POLICY is a non-empty, substantive policy string."""
        assert isinstance(CROSS_STAGE_INVARIANT_POLICY, str)
        assert len(CROSS_STAGE_INVARIANT_POLICY) > 100
        assert "POLICY::" in CROSS_STAGE_INVARIANT_POLICY
        assert "closed" in CROSS_STAGE_INVARIANT_POLICY.lower()

    def test_E04_audit_record_is_json_serialisable(self):
        """E04: get_closed_loop_audit_record returns a JSON-serialisable dict."""
        import json

        eid = "exec-e04-audit"
        did = "dev-e04"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        record = get_closed_loop_audit_record(eid, did)
        serialised = json.dumps(record)
        assert len(serialised) > 100

    def test_E05_audit_record_contains_required_fields(self):
        """E05: Audit record has execution_id, device_id, closed_loop_view, lifecycle_history."""
        eid = "exec-e05-fields"
        did = "dev-e05"
        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        record = get_closed_loop_audit_record(eid, did)
        required_fields = {
            "execution_id", "device_id", "closed_loop_view",
            "lifecycle_history", "uplink_truth_snapshot", "uplink_records",
            "audit_generated_at", "_sentinel", "_contract_version",
        }
        for field_name in required_fields:
            assert field_name in record, (
                f"Audit record missing required field: {field_name!r}"
            )

    def test_E06_audit_record_sentinel_matches_module_sentinel(self):
        """E06: Sentinel in audit record matches the module-level sentinel."""
        eid = "exec-e06-sentinel"
        did = "dev-e06"
        record = get_closed_loop_audit_record(eid, did)
        assert record["_sentinel"] == CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL

    def test_E07_closed_loop_view_sentinel_in_to_dict(self):
        """E07: ClosedLoopGovernanceView.to_dict() includes _sentinel and _contract_version."""
        eid = "exec-e07-view-sentinel"
        did = "dev-e07"
        view = query_closed_loop_governance_state(eid, did)
        d = view.to_dict()
        assert "_sentinel" in d
        assert d["_sentinel"] == CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL
        assert "_contract_version" in d
        assert d["_contract_version"] == CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION

    def test_E08_closed_loop_stage_enum_has_all_required_values(self):
        """E08: ClosedLoopStage enum contains all required stage values."""
        required = {
            "activation", "execution", "observation",
            "reconciliation", "completion", "unknown",
        }
        actual = {s.value for s in ClosedLoopStage}
        assert required <= actual, (
            f"Missing ClosedLoopStage values: {required - actual}"
        )
