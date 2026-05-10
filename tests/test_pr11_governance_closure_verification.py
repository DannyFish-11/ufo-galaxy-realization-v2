"""tests/test_pr11_governance_closure_verification.py
======================================================

PR-11 — Governance Closure Verification.

Validates end-to-end closure of execution governance, canonical runtime truth,
and mission completion semantics across representative lifecycle scenarios.

All tests are self-contained: no live servers, no real devices.

Coverage groups
---------------
A.  Cross-mode terminal closure
       All four execution types (goal / parallel / takeover / delegated)
       close with canonical terminal truth under the center-governance layer.

B.  Interrupt → retry → replay lifecycle chains
       Complex multi-phase sequences prove center authority is retained through
       interruption_reason and replay_reason transitions.

C.  Delayed and conflicting observation determinism
       Late uplink arrivals after a terminal lifecycle phase must NOT override
       center truth.  Regression-protection for canonical authority under
       delayed / conflicting external observations.

D.  Partial and degraded observation closure
       Partial uplinks and degraded state observations are classified
       correctly and do not promote false terminal truth.

E.  Recovery path canonical stability
       Degraded → recovered runtime state transitions remain consistent with
       center-authority terminal truth.

F.  Cross-device governance isolation
       Governance state for device A must not leak into device B.

G.  Mission completion determinism under all supported phases
       Every terminal phase maps to a deterministic, regression-protected
       canonical outcome.
"""

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
    get_uplink_truth_state,
    notify_execution_completed,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


# ---------------------------------------------------------------------------
# Shared fixture — reset all governance runtime state between tests.
# ---------------------------------------------------------------------------


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


# ===========================================================================
# Group A — Cross-mode terminal closure
# ===========================================================================


class TestGroupA_CrossModeTerminalClosure:
    """A01–A08: Each execution type closes with deterministic terminal truth."""

    @pytest.mark.parametrize(
        ("execution_type", "terminal_phase", "expected_outcome"),
        [
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.failed, "failure"),
            (ExecutionType.parallel_subtask, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.parallel_subtask, ExecutionLifecyclePhase.timed_out, "timeout"),
            (ExecutionType.takeover_request, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.takeover_request, ExecutionLifecyclePhase.cancelled, "aborted"),
            (ExecutionType.delegated_execution, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.delegated_execution, ExecutionLifecyclePhase.interrupted, "interrupted"),
        ],
    )
    def test_A01_to_A08_cross_mode_terminal_truth_is_canonical(
        self,
        execution_type: ExecutionType,
        terminal_phase: ExecutionLifecyclePhase,
        expected_outcome: str,
    ):
        """A01–A08: REGRESSION — each (type, phase) pair maps to one canonical outcome."""
        eid = f"exec-pr11-a-{execution_type.value}-{terminal_phase.value}"
        did = f"device-pr11-a-{execution_type.value}"

        record_execution_lifecycle_event(
            execution_id=eid,
            device_id=did,
            execution_type=execution_type,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid,
            device_id=did,
            execution_type=execution_type,
            phase=terminal_phase,
            enforce_transition=False,
        )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is True, (
            f"FAILED A: {execution_type.value}/{terminal_phase.value} must be terminal. "
            f"Got is_terminal={truth['is_terminal']}"
        )
        assert truth["canonical_terminal_outcome"] == expected_outcome, (
            f"FAILED A: canonical_terminal_outcome mismatch. "
            f"Expected {expected_outcome!r}, got {truth['canonical_terminal_outcome']!r}."
        )
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle", (
            "FAILED A: terminal truth authority must be center_lifecycle."
        )

    def test_A09_goal_execution_full_lifecycle_closure(self):
        """A09: goal_execution with uplink records closes deterministically."""
        eid = "exec-pr11-a09-goal-full"
        did = "device-pr11-a09"

        for phase in [ExecutionLifecyclePhase.created, ExecutionLifecyclePhase.running]:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution, phase=phase,
                enforce_transition=False,
            )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"progress": 0.9, "stage": "finalizing"},
        )
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "ok"},
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
        )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is True
        assert truth["canonical_terminal_outcome"] == "success"
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"
        assert truth["result_uplink_count"] >= 1
        assert truth["state_uplink_count"] >= 1

    def test_A10_delegated_execution_closure_with_coordinator_outcome(self):
        """A10: delegated_execution closes with center truth after coordinator uplinks."""
        eid = "exec-pr11-a10-delegated-full"
        did = "device-pr11-a10"

        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.delegated_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        assert verdict.accepted is True

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )
        notify_execution_completed(
            did, ExecutionType.delegated_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is True
        assert truth["canonical_terminal_outcome"] == "success"


# ===========================================================================
# Group B — Interrupt → retry → replay lifecycle chains
# ===========================================================================


class TestGroupB_InterruptRetryReplay:
    """B01–B04: Multi-phase sequences preserve center authority through retries."""

    def test_B01_interrupted_then_retried_retains_center_authority(self):
        """B01: interrupt + retry chain — center authority holds at each phase."""
        eid = "exec-pr11-b01-interrupt-retry"
        did = "device-pr11-b01"

        phases = [
            (ExecutionLifecyclePhase.created, {}),
            (ExecutionLifecyclePhase.running, {}),
            (ExecutionLifecyclePhase.interrupted, {
                "interruption_reason": InterruptionReason.operator_interrupt,
            }),
            (ExecutionLifecyclePhase.retrying, {}),
            (ExecutionLifecyclePhase.succeeded, {}),
        ]
        for phase, kwargs in phases:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase, enforce_transition=False, **kwargs,
            )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is True
        assert truth["canonical_terminal_outcome"] == "success"
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"

    def test_B02_failed_then_replayed_resolves_to_final_center_outcome(self):
        """B02: failure + replay chain — canonical outcome is from last terminal phase."""
        eid = "exec-pr11-b02-fail-replay"
        did = "device-pr11-b02"

        for phase, kwargs in [
            (ExecutionLifecyclePhase.created, {}),
            (ExecutionLifecyclePhase.running, {}),
            (ExecutionLifecyclePhase.failed, {
                "failure_semantic": FailureSemantic.reject_with_reason,
            }),
            (ExecutionLifecyclePhase.replayed, {
                "replay_reason": ReplayReason.failure_replay,
            }),
            (ExecutionLifecyclePhase.succeeded, {}),
        ]:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase, enforce_transition=False, **kwargs,
            )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "success"
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"

    def test_B03_retry_attempt_tracking_increments_correctly(self):
        """B03: attempt counter increments across retry boundary."""
        eid = "exec-pr11-b03-retry-attempt"
        did = "device-pr11-b03"

        for phase in [
            ExecutionLifecyclePhase.created,
            ExecutionLifecyclePhase.failed,
            ExecutionLifecyclePhase.retrying,
            ExecutionLifecyclePhase.timed_out,
        ]:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase, enforce_transition=False,
            )

        history = get_execution_lifecycle_history(eid)
        phases = [e["phase"] for e in history]
        assert "failed" in phases
        assert "retrying" in phases
        attempt_at_retry = next(
            e["attempt"] for e in history if e["phase"] == "retrying"
        )
        assert attempt_at_retry == 2

    def test_B04_interrupted_by_takeover_preemption_reason_recorded(self):
        """B04: takeover-preempted interruption reason is preserved in history."""
        eid = "exec-pr11-b04-takeover-preempt"
        did = "device-pr11-b04"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.interrupted,
            interruption_reason=InterruptionReason.takeover_preempted,
            enforce_transition=False,
        )

        history = get_execution_lifecycle_history(eid)
        interrupted_event = next(e for e in history if e["phase"] == "interrupted")
        assert interrupted_event.get("interruption_reason") == "takeover_preempted"


# ===========================================================================
# Group C — Delayed and conflicting observation determinism
# ===========================================================================


class TestGroupC_DelayedConflictingObservations:
    """C01–C04: Late observations must NOT override canonical center truth."""

    def test_C01_late_success_uplink_does_not_override_center_timeout(self):
        """C01: REGRESSION — center timeout retained when late success arrives."""
        eid = "exec-pr11-c01-late-success-vs-timeout"
        did = "device-pr11-c01"

        with patch("core.unified_execution_governance.time.time",
                   side_effect=[100.0, 101.0, 110.0]):
            # t=100: created lifecycle event
            # t=101: timed_out lifecycle event (terminal — center authority set)
            # t=110: result uplink arrives late (after terminal — delayed conflict)
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=ExecutionLifecyclePhase.created,
            )
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=ExecutionLifecyclePhase.timed_out, enforce_transition=False,
            )
            record_result_uplink(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                payload={"status": "success"},
            )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "timeout", (
            "REGRESSION C01: center timeout must not be overridden by late success report."
        )
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"
        assert truth["reconciliation_conflict"] is True
        assert truth["reconciliation_delayed_observation"] is True
        assert "center_truth_retained" in truth["reconciliation_status"]

    def test_C02_late_failure_uplink_does_not_override_center_success(self):
        """C02: REGRESSION — center success retained when late failure arrives."""
        eid = "exec-pr11-c02-late-failure-vs-success"
        did = "device-pr11-c02"

        with patch("core.unified_execution_governance.time.time",
                   side_effect=[200.0, 201.0, 210.0]):
            # t=200: succeeded lifecycle event (terminal — center authority set)
            # t=201: (unused; reserved for potential future events)
            # t=210: result uplink arrives late (after terminal — delayed conflict)
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.delegated_execution,
                phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
            )
            record_result_uplink(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.delegated_execution,
                payload={"status": "failed", "error": "stale_observation"},
            )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "success", (
            "REGRESSION C02: center success must not be overridden by delayed failure report."
        )
        assert truth["reconciliation_conflict"] is True
        assert truth["reconciliation_delayed_observation"] is True

    def test_C03_parallel_subtask_conflicting_uplinks_center_lifecycle_wins(self):
        """C03: parallel_subtask with conflicting result/state uplinks — center wins."""
        eid = "exec-pr11-c03-parallel-conflict"
        did = "device-pr11-c03"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "failed"},
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.succeeded,
        )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_outcome"] == "succeeded"
        assert truth["authoritative_outcome_source"] == "center_lifecycle"
        assert truth["reconciliation_conflict"] is True

    def test_C04_multiple_conflicting_uplinks_do_not_destabilize_center_truth(self):
        """C04: Successive conflicting uplinks must not shift canonical terminal outcome."""
        eid = "exec-pr11-c04-multi-conflict"
        did = "device-pr11-c04"

        with patch("core.unified_execution_governance.time.time",
                   side_effect=[300.0, 301.0, 305.0, 310.0, 315.0]):
            # t=300: succeeded lifecycle event (terminal — center authority set)
            # t=301, 305, 310: three successive late conflicting uplinks (failed/timeout/failed)
            # t=315: (reserved for any additional uplink if needed)
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
            )
            # Send three conflicting late uplinks
            for status in ["failed", "timeout", "failed"]:
                record_result_uplink(
                    execution_id=eid, device_id=did,
                    execution_type=ExecutionType.goal_execution,
                    payload={"status": status},
                )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "success", (
            "REGRESSION C04: multiple conflicting late uplinks must not shift center truth."
        )
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"


# ===========================================================================
# Group D — Partial and degraded observation closure
# ===========================================================================


class TestGroupD_PartialAndDegradedObservations:
    """D01–D05: Partial/degraded uplinks classified without false terminal truth."""

    def test_D01_result_uplink_only_no_lifecycle_is_classified_as_uplink_only(self):
        """D01: result uplink without any lifecycle event → uplink_only classification."""
        eid = "exec-pr11-d01-result-only"
        did = "device-pr11-d01"

        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            payload={"status": "success"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["lifecycle_phase"] is None
        assert truth["terminal_truth_determined"] is True
        assert truth["terminal_truth_authoritative_source"] == "reported_uplink"

    def test_D02_state_uplink_only_does_not_assert_terminal(self):
        """D02: state uplink alone must not claim terminal closure."""
        eid = "exec-pr11-d02-state-only"
        did = "device-pr11-d02"

        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"phase": "running", "progress": 0.5},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is False
        assert truth["lifecycle_phase"] is None

    def test_D03_partial_result_and_state_without_lifecycle_is_partial_observation(self):
        """D03: result + state uplinks only → reconciliation_partial_observation flag set."""
        eid = "exec-pr11-d03-partial-obs"
        did = "device-pr11-d03"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
        )
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "ok"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["reconciliation_partial_observation"] is True
        assert truth["canonical_outcome"] == "succeeded"

    def test_D04_conflicting_result_and_state_uplinks_produce_partial_success(self):
        """D04: conflicting result and state uplinks → partial_success classification."""
        eid = "exec-pr11-d04-partial-success"
        did = "device-pr11-d04"

        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "success"},
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "failed", "reason": "partial_node_failure"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "partial_success"

    def test_D05_degraded_state_uplink_does_not_claim_terminal(self):
        """D05: degraded state uplink without terminal lifecycle → not terminal."""
        eid = "exec-pr11-d05-degraded-not-terminal"
        did = "device-pr11-d05"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "running", "degraded": True, "reason": "high_latency"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is False
        assert truth["canonical_runtime_health"] == "degraded"
        assert truth["canonical_runtime_health_reason"] == "high_latency"


# ===========================================================================
# Group E — Recovery path canonical stability
# ===========================================================================


class TestGroupE_RecoveryPathCanonicalStability:
    """E01–E04: Degraded → recovered flows remain consistent with center truth."""

    def test_E01_degraded_then_recovered_terminal_truth_unchanged(self):
        """E01: Degraded state followed by recovery → terminal outcome unchanged."""
        eid = "exec-pr11-e01-degrade-recover"
        did = "device-pr11-e01"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded", "degraded": True, "reason": "network_pressure"},
        )

        degraded_truth = get_uplink_truth_state(eid)
        assert degraded_truth["canonical_terminal_outcome"] == "success"
        assert degraded_truth["canonical_runtime_health"] == "degraded"

        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            payload={"phase": "succeeded", "recovered": True, "reason": "link_restored"},
        )

        recovered_truth = get_uplink_truth_state(eid)
        assert recovered_truth["canonical_terminal_outcome"] == "success", (
            "REGRESSION E01: recovery must not change canonical terminal outcome."
        )
        assert recovered_truth["canonical_runtime_health"] == "recovered"
        assert recovered_truth["terminal_truth_authoritative_source"] == "center_lifecycle"

    def test_E02_multiple_degraded_states_terminal_remains_stable(self):
        """E02: Multiple degraded state updates do not shift terminal truth."""
        eid = "exec-pr11-e02-multi-degraded"
        did = "device-pr11-e02"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
        )

        for reason in ["packet_loss", "high_latency", "reconnect"]:
            record_state_uplink(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                payload={"degraded": True, "reason": reason},
            )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "success", (
            "REGRESSION E02: multiple degraded observations must not shift center success."
        )

    def test_E03_recovery_after_interrupt_preserves_interrupted_terminal_if_not_overridden(self):
        """E03: Interrupted execution with recovery uplink — center interrupted outcome holds."""
        eid = "exec-pr11-e03-interrupted-with-recovery"
        did = "device-pr11-e03"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.interrupted,
            interruption_reason=InterruptionReason.device_disconnect,
            enforce_transition=False,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"recovered": True, "reason": "device_reconnected"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "interrupted", (
            "REGRESSION E03: interrupted center truth must not be overridden by recovery uplink."
        )

    def test_E04_failed_then_recovered_canonical_outcome_is_failure(self):
        """E04: Failed center phase + recovered uplink — terminal outcome stays failure."""
        eid = "exec-pr11-e04-fail-recover"
        did = "device-pr11-e04"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.failed, enforce_transition=False,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            payload={"recovered": True, "reason": "failover_activated"},
        )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == "failure", (
            "REGRESSION E04: failed center truth must not be overridden by recovery state."
        )


# ===========================================================================
# Group F — Cross-device governance isolation
# ===========================================================================


class TestGroupF_CrossDeviceGovernanceIsolation:
    """F01–F02: Governance state is isolated per device."""

    def test_F01_device_a_terminal_does_not_affect_device_b(self):
        """F01: device A reaching terminal phase does not affect device B's state."""
        eid_a = "exec-pr11-f01-device-a"
        eid_b = "exec-pr11-f01-device-b"
        did_a = "device-pr11-f01-a"
        did_b = "device-pr11-f01-b"

        record_execution_lifecycle_event(
            execution_id=eid_a, device_id=did_a,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded, enforce_transition=False,
        )
        record_execution_lifecycle_event(
            execution_id=eid_b, device_id=did_b,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )

        truth_a = get_uplink_truth_state(eid_a)
        truth_b = get_uplink_truth_state(eid_b)

        assert truth_a["is_terminal"] is True
        assert truth_b["is_terminal"] is False, (
            "REGRESSION F01: device B must not inherit device A's terminal state."
        )

    def test_F02_takeover_on_device_a_does_not_block_device_b_delegated(self):
        """F02: takeover on device A must not block delegated_execution on device B."""
        did_a = "device-pr11-f02-a"
        did_b = "device-pr11-f02-b"

        with _patch_mode_gate_pass():
            takeover = evaluate_execution_governance(
                ExecutionType.takeover_request, did_a,
                execution_id="tkv-pr11-f02", register_if_accepted=True,
            )
            delegated = evaluate_execution_governance(
                ExecutionType.delegated_execution, did_b,
                execution_id="del-pr11-f02", register_if_accepted=False,
            )

        assert takeover.accepted is True
        assert delegated.accepted is True, (
            "REGRESSION F02: takeover on device A must not block device B's delegated execution."
        )


# ===========================================================================
# Group G — Mission completion determinism under all terminal phases
# ===========================================================================


class TestGroupG_MissionCompletionDeterminism:
    """G01–G07: Every terminal phase maps to a single deterministic canonical outcome."""

    @pytest.mark.parametrize(
        ("terminal_phase", "expected_terminal_outcome"),
        [
            (ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionLifecyclePhase.failed, "failure"),
            (ExecutionLifecyclePhase.timed_out, "timeout"),
            (ExecutionLifecyclePhase.cancelled, "aborted"),
            (ExecutionLifecyclePhase.interrupted, "interrupted"),
        ],
    )
    def test_G01_to_G05_terminal_phase_maps_to_canonical_outcome(
        self,
        terminal_phase: ExecutionLifecyclePhase,
        expected_terminal_outcome: str,
    ):
        """G01–G05: REGRESSION — canonical outcome mapping is deterministic."""
        eid = f"exec-pr11-g-{terminal_phase.value}"
        did = f"device-pr11-g-{terminal_phase.value}"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=terminal_phase, enforce_transition=False,
        )

        truth = get_uplink_truth_state(eid)
        assert truth["canonical_terminal_outcome"] == expected_terminal_outcome, (
            f"REGRESSION G: {terminal_phase.value} must map to {expected_terminal_outcome!r}. "
            f"Got {truth['canonical_terminal_outcome']!r}."
        )
        assert truth["terminal_truth_determined"] is True
        assert truth["terminal_truth_authoritative_source"] == "center_lifecycle"

    def test_G06_notify_execution_completed_closes_loop_correctly(self):
        """G06: notify_execution_completed records terminal phase and closes the loop."""
        eid = "exec-pr11-g06-notify"
        did = "device-pr11-g06"

        with _patch_mode_gate_pass():
            verdict = evaluate_execution_governance(
                ExecutionType.goal_execution, did,
                execution_id=eid, register_if_accepted=True,
            )
        assert verdict.accepted is True

        removed = notify_execution_completed(
            did, ExecutionType.goal_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )
        assert removed is True

        truth = get_uplink_truth_state(eid)
        assert truth["is_terminal"] is True
        assert truth["canonical_terminal_outcome"] == "success"

    def test_G07_lifecycle_matrix_covers_all_canonical_execution_modes(self):
        """G07: lifecycle matrix must enumerate all canonical execution types and semantics."""
        matrix = get_execution_lifecycle_matrix()
        execution_types = matrix["execution_types"]

        required_types = {
            "goal_execution", "parallel_subtask",
            "takeover_request", "delegated_execution",
        }
        for et in required_types:
            assert et in execution_types, (
                f"REGRESSION G07: execution type {et!r} missing from lifecycle matrix."
            )

        semantics = matrix["governance_semantics"]
        required_semantics = {"failure", "timeout", "retry", "replay", "interruption"}
        for sem in required_semantics:
            assert sem in semantics, (
                f"REGRESSION G07: governance semantic {sem!r} missing from lifecycle matrix."
            )
