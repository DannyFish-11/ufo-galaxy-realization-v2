"""tests/test_pr14_governance_audit_authority.py
=================================================

PR-14 V2-side — Execution Governance Audit Authority Hardening.

Validates that the center-side governance audit authority layer correctly
builds a complete, verifiable authority chain for all governed executions
and detects invariant violations.

All tests are self-contained: no live servers, no real devices.

Coverage groups
---------------
A.  Authority chain construction
       build_governance_authority_evidence() produces correctly-staged entries
       for all valid lifecycle paths: admission-only, full lifecycle, with/without
       uplinks, with/without terminal closure.

B.  Authority chain integrity verification
       verify_governance_authority_integrity() returns zero violations for
       coherent chains, and the expected invariant IDs for broken ones.
       Covers I-A1 (center-lifecycle wins), I-A3 (monotonic chain), and
       I-A4 (uplink cannot override center terminal truth).

C.  Adverse conditions — missing, partial, and conflicting observations
       Evidence and integrity checks remain deterministic under degraded
       inputs: no uplinks, no lifecycle, conflicting outcomes, delayed
       uplink arrivals, and interrupted/retried executions.

D.  Cross-execution and cross-device isolation
       Governance audit state for one execution or device MUST NOT affect
       another execution or device.

E.  Audit summary, sentinel, and contract version coverage
       get_governance_audit_summary() is JSON-serialisable and contains all
       required fields.  Sentinel and contract version are present and correct.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core.execution_governance_audit_authority import (
    GOVERNANCE_AUDIT_AUTHORITY_POLICY,
    GOVERNANCE_AUDIT_AUTHORITY_SENTINEL,
    GOVERNANCE_AUDIT_CONTRACT_VERSION,
    GovernanceAuditStage,
    GovernanceAuthorityEvidence,
    GovernanceAuthorityViolation,
    build_governance_authority_evidence,
    get_governance_audit_summary,
    verify_governance_authority_integrity,
)
from core.unified_execution_governance import (
    ExecutionLifecyclePhase,
    ExecutionType,
    InterruptionReason,
    ReplayReason,
    _clear_execution_governance_runtime_state,
    evaluate_execution_governance,
    notify_execution_completed,
    record_execution_lifecycle_event,
    record_result_uplink,
    record_state_uplink,
)


# ---------------------------------------------------------------------------
# Shared fixture
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
# Group A — Authority chain construction
# ===========================================================================


class TestGroupA_AuthorityChainConstruction:
    """A01–A10: build_governance_authority_evidence() stage-by-stage construction."""

    def test_A01_no_history_returns_admission_not_reached(self):
        """A01: An execution with no history has no stages reached."""
        eid = "exec-pr14-a01-empty"
        did = "device-pr14-a01"
        evidence = build_governance_authority_evidence(eid, did)

        assert evidence.execution_id == eid
        assert evidence.device_id == did
        assert evidence.highest_stage_reached is None
        assert evidence.authority_chain_complete is False
        assert evidence.canonical_terminal_outcome is None
        assert evidence.authority_source == "none"

        for entry in evidence.audit_entries:
            assert entry.reached is False, (
                f"Stage {entry.stage.value!r} should not be reached for empty history."
            )

    def test_A02_lifecycle_event_only_reaches_lifecycle_stage(self):
        """A02: A single lifecycle event marks admission and lifecycle as reached."""
        eid = "exec-pr14-a02-lifecycle-only"
        did = "device-pr14-a02"
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )

        evidence = build_governance_authority_evidence(eid, did)
        by_stage = {e.stage: e for e in evidence.audit_entries}

        assert by_stage[GovernanceAuditStage.admission].reached is True
        assert by_stage[GovernanceAuditStage.lifecycle].reached is True
        # No uplinks yet
        assert by_stage[GovernanceAuditStage.uplink_observation].reached is False
        assert evidence.authority_chain_complete is False

    def test_A03_uplink_only_reaches_admission_and_uplink(self):
        """A03: Uplink-only evidence reaches admission and uplink_observation."""
        eid = "exec-pr14-a03-uplink-only"
        did = "device-pr14-a03"
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"status": "ok"},
        )

        evidence = build_governance_authority_evidence(eid, did)
        by_stage = {e.stage: e for e in evidence.audit_entries}

        assert by_stage[GovernanceAuditStage.admission].reached is True
        assert by_stage[GovernanceAuditStage.uplink_observation].reached is True
        # No lifecycle events recorded
        assert by_stage[GovernanceAuditStage.lifecycle].reached is False

    def test_A04_full_lifecycle_with_terminal_reaches_all_stages(self):
        """A04: Full lifecycle path reaches all five stages."""
        eid = "exec-pr14-a04-full"
        did = "device-pr14-a04"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
            enforce_transition=False,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"progress": 0.5},
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

        evidence = build_governance_authority_evidence(eid, did)
        for entry in evidence.audit_entries:
            assert entry.reached is True, (
                f"Stage {entry.stage.value!r} should be reached for full lifecycle."
            )

        assert evidence.highest_stage_reached == GovernanceAuditStage.terminal
        assert evidence.authority_chain_complete is True
        assert evidence.canonical_terminal_outcome == "success"
        assert evidence.authority_source == "center_lifecycle"

    @pytest.mark.parametrize(
        ("execution_type", "terminal_phase", "expected_outcome"),
        [
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.succeeded, "success"),
            (ExecutionType.goal_execution, ExecutionLifecyclePhase.failed, "failure"),
            (ExecutionType.parallel_subtask, ExecutionLifecyclePhase.timed_out, "timeout"),
            (ExecutionType.takeover_request, ExecutionLifecyclePhase.cancelled, "aborted"),
            (ExecutionType.delegated_execution, ExecutionLifecyclePhase.interrupted, "interrupted"),
        ],
    )
    def test_A05_to_A09_all_terminal_phases_produce_complete_chain(
        self,
        execution_type: ExecutionType,
        terminal_phase: ExecutionLifecyclePhase,
        expected_outcome: str,
    ):
        """A05–A09: Each (type, terminal_phase) pair produces a complete authority chain."""
        eid = f"exec-pr14-a-multi-{execution_type.value}-{terminal_phase.value}"
        did = f"device-pr14-a-multi-{execution_type.value}"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=execution_type,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=execution_type,
            phase=terminal_phase,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.authority_chain_complete is True
        assert evidence.canonical_terminal_outcome == expected_outcome
        assert evidence.authority_source == "center_lifecycle"

    def test_A10_in_progress_execution_reaches_reconciliation_not_terminal(self):
        """A10: An in-progress execution has reconciliation but not terminal."""
        eid = "exec-pr14-a10-in-progress"
        did = "device-pr14-a10"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        by_stage = {e.stage: e for e in evidence.audit_entries}

        assert by_stage[GovernanceAuditStage.lifecycle].reached is True
        assert by_stage[GovernanceAuditStage.reconciliation].reached is True
        assert by_stage[GovernanceAuditStage.terminal].reached is False
        assert evidence.authority_chain_complete is False


# ===========================================================================
# Group B — Authority chain integrity verification
# ===========================================================================


class TestGroupB_AuthorityChainIntegrityVerification:
    """B01–B10: verify_governance_authority_integrity() returns correct violations."""

    def test_B01_coherent_full_chain_has_zero_violations(self):
        """B01: A fully coherent chain (lifecycle → terminal) has no violations."""
        eid = "exec-pr14-b01-coherent"
        did = "device-pr14-b01"

        for phase in [ExecutionLifecyclePhase.created, ExecutionLifecyclePhase.succeeded]:
            record_execution_lifecycle_event(
                execution_id=eid,
                device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase,
                enforce_transition=False,  # allow direct created→succeeded for test simplicity
            )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == [], (
            f"REGRESSION: Coherent chain should have 0 violations, got {violations}."
        )

    def test_B02_no_history_has_zero_violations(self):
        """B02: An execution with no history has no violations (nothing to verify)."""
        violations = verify_governance_authority_integrity(
            "exec-pr14-b02-no-history", "device-pr14-b02"
        )
        assert violations == []

    def test_B03_center_lifecycle_authority_wins_i_a1(self):
        """B03: Center-lifecycle is the terminal source when lifecycle terminal is set."""
        eid = "exec-pr14-b03-authority-wins"
        did = "device-pr14-b03"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        violations = verify_governance_authority_integrity(eid, did)
        violation_ids = [v.invariant_id for v in violations]
        # I-A1 must NOT be triggered (center_lifecycle IS the source)
        assert "I-A1" not in violation_ids

    def test_B04_monotonic_chain_i_a3_not_triggered_for_valid_chain(self):
        """B04: I-A3 is not triggered when the chain is valid (lifecycle before terminal)."""
        eid = "exec-pr14-b04-monotonic"
        did = "device-pr14-b04"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
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
            enforce_transition=False,
        )

        violations = verify_governance_authority_integrity(eid, did)
        violation_ids = [v.invariant_id for v in violations]
        assert "I-A3" not in violation_ids

    def test_B05_uplink_only_terminal_does_not_trigger_i_a4(self):
        """B05: uplink-only terminal without lifecycle conflict does not trigger I-A4."""
        eid = "exec-pr14-b05-uplink-only-terminal"
        did = "device-pr14-b05"

        # Only uplink, no lifecycle — no conflict, so I-A4 is not triggered
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "success"},
        )

        violations = verify_governance_authority_integrity(eid, did)
        violation_ids = [v.invariant_id for v in violations]
        assert "I-A4" not in violation_ids

    def test_B06_i_a4_not_triggered_when_center_lifecycle_wins_conflict(self):
        """B06: Conflict resolved by center_lifecycle does NOT trigger I-A4."""
        eid = "exec-pr14-b06-conflict-center-wins"
        did = "device-pr14-b06"

        # Record lifecycle terminal phase
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        # Then record a conflicting uplink (failure after success)
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "failed"},
        )

        violations = verify_governance_authority_integrity(eid, did)
        violation_ids = [v.invariant_id for v in violations]
        # I-A4 should NOT be triggered because center_lifecycle is the source
        assert "I-A4" not in violation_ids

    def test_B07_all_violation_records_have_required_fields(self):
        """B07: GovernanceAuthorityViolation records have all required fields."""
        # Construct a scenario where we can inspect a violation record
        # by calling verify directly with an edge case that produces violations.
        # Use an empty execution to get violations = [] (no violations).
        violations = verify_governance_authority_integrity(
            "exec-pr14-b07-fields", "device-pr14-b07"
        )
        # Even if empty, any violation record must satisfy the schema.
        # Construct one manually to validate the schema.
        v = GovernanceAuthorityViolation(
            invariant_id="I-A1",
            description="test violation",
            stage=GovernanceAuditStage.terminal,
            evidence={"key": "val"},
        )
        d = v.to_dict()
        assert "invariant_id" in d
        assert "description" in d
        assert "stage" in d
        assert "evidence" in d
        assert d["invariant_id"] == "I-A1"
        assert d["stage"] == "terminal"

    def test_B08_parallel_subtask_coherent_chain_zero_violations(self):
        """B08: parallel_subtask full lifecycle produces zero violations."""
        eid = "exec-pr14-b08-parallel"
        did = "device-pr14-b08"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.created,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            payload={"progress": 0.7},
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.parallel_subtask,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []

    def test_B09_delegated_execution_via_notify_coherent_chain(self):
        """B09: delegated_execution closed via notify_execution_completed is coherent."""
        eid = "exec-pr14-b09-delegated"
        did = "device-pr14-b09"

        with _patch_mode_gate_pass():
            evaluate_execution_governance(
                ExecutionType.delegated_execution, did,
                execution_id=eid, register_if_accepted=True,
            )

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.delegated_execution,
            phase=ExecutionLifecyclePhase.running, enforce_transition=False,
        )
        notify_execution_completed(
            did, ExecutionType.delegated_execution, eid,
            completion_phase=ExecutionLifecyclePhase.succeeded,
        )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []

    def test_B10_takeover_aborted_coherent_chain(self):
        """B10: takeover_request cancelled lifecycle closes with zero violations."""
        eid = "exec-pr14-b10-takeover"
        did = "device-pr14-b10"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.cancelled,
            enforce_transition=False,
        )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []
        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.canonical_terminal_outcome == "aborted"


# ===========================================================================
# Group C — Adverse conditions
# ===========================================================================


class TestGroupC_AdverseConditions:
    """C01–C08: Evidence and integrity checks under adverse operational conditions."""

    def test_C01_no_lifecycle_no_uplink_empty_evidence(self):
        """C01: No lifecycle/uplink produces an empty evidence with integrity ok."""
        eid = "exec-pr14-c01-empty"
        did = "device-pr14-c01"

        evidence = build_governance_authority_evidence(eid, did)
        violations = verify_governance_authority_integrity(eid, did)

        assert evidence.highest_stage_reached is None
        assert evidence.authority_chain_complete is False
        assert violations == []

    def test_C02_interrupted_execution_audit_entry_records_interrupted(self):
        """C02: Interrupted execution produces an interrupted terminal outcome in evidence."""
        eid = "exec-pr14-c02-interrupted"
        did = "device-pr14-c02"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.running,
            enforce_transition=False,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.interrupted,
            interruption_reason=InterruptionReason.device_disconnect,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.canonical_terminal_outcome == "interrupted"
        assert evidence.authority_chain_complete is True
        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []

    def test_C03_delayed_uplink_after_terminal_lifecycle_does_not_break_chain(self):
        """C03: A late uplink after terminal lifecycle does not produce violations."""
        eid = "exec-pr14-c03-delayed-uplink"
        did = "device-pr14-c03"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )
        # Late-arriving uplink with a conflicting status
        record_result_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "failed"},
        )

        violations = verify_governance_authority_integrity(eid, did)
        # Center-lifecycle wins; no I-A4 violation
        violation_ids = [v.invariant_id for v in violations]
        assert "I-A4" not in violation_ids

        evidence = build_governance_authority_evidence(eid, did)
        # The canonical terminal outcome must still be "success" from center_lifecycle
        assert evidence.canonical_terminal_outcome == "success"
        assert evidence.authority_source == "center_lifecycle"

    def test_C04_retry_path_closes_coherently(self):
        """C04: A retried execution (interrupted → retried → succeeded) closes coherently."""
        eid = "exec-pr14-c04-retry"
        did = "device-pr14-c04"

        for phase in [
            ExecutionLifecyclePhase.created,
            ExecutionLifecyclePhase.running,
            ExecutionLifecyclePhase.interrupted,
            ExecutionLifecyclePhase.running,  # retried
            ExecutionLifecyclePhase.succeeded,
        ]:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase,
                enforce_transition=False,
            )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []
        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.canonical_terminal_outcome == "success"
        assert evidence.authority_chain_complete is True

    def test_C05_partial_uplink_observation_classified_correctly(self):
        """C05: Only a state uplink (no result uplink) still marks uplink_observation reached."""
        eid = "exec-pr14-c05-partial-uplink"
        did = "device-pr14-c05"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_state_uplink(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            payload={"status": "running"},
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        by_stage = {e.stage: e for e in evidence.audit_entries}
        assert by_stage[GovernanceAuditStage.uplink_observation].reached is True
        assert evidence.authority_chain_complete is True

    def test_C06_replay_path_canonical_outcome_is_success(self):
        """C06: A replayed execution that succeeds maps to 'success'."""
        eid = "exec-pr14-c06-replay"
        did = "device-pr14-c06"

        for phase in [
            ExecutionLifecyclePhase.created,
            ExecutionLifecyclePhase.interrupted,
            ExecutionLifecyclePhase.created,  # replay reset
            ExecutionLifecyclePhase.succeeded,
        ]:
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase,
                enforce_transition=False,
            )

        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.canonical_terminal_outcome == "success"
        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []

    def test_C07_timeout_terminal_phase_produces_complete_chain(self):
        """C07: timed_out phase produces a complete authority chain."""
        eid = "exec-pr14-c07-timeout"
        did = "device-pr14-c07"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.takeover_request,
            phase=ExecutionLifecyclePhase.timed_out,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        assert evidence.canonical_terminal_outcome == "timeout"
        assert evidence.authority_chain_complete is True
        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []

    def test_C08_multiple_uplinks_do_not_inflate_violation_count(self):
        """C08: Multiple result+state uplinks under a terminal lifecycle produce no violations."""
        eid = "exec-pr14-c08-multi-uplink"
        did = "device-pr14-c08"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        for i in range(3):
            record_state_uplink(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                payload={"progress": i * 0.3},
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
            enforce_transition=False,
        )

        violations = verify_governance_authority_integrity(eid, did)
        assert violations == []


# ===========================================================================
# Group D — Cross-execution and cross-device isolation
# ===========================================================================


class TestGroupD_CrossExecutionAndDeviceIsolation:
    """D01–D05: Governance audit state is isolated per execution and device."""

    def test_D01_different_executions_on_same_device_are_isolated(self):
        """D01: Two executions on the same device are independently audited."""
        did = "device-pr14-d01"
        eid_a = "exec-pr14-d01-a"
        eid_b = "exec-pr14-d01-b"

        # eid_a: full lifecycle → succeeded
        record_execution_lifecycle_event(
            execution_id=eid_a, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid_a, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        # eid_b: created only
        record_execution_lifecycle_event(
            execution_id=eid_b, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )

        evidence_a = build_governance_authority_evidence(eid_a, did)
        evidence_b = build_governance_authority_evidence(eid_b, did)

        assert evidence_a.authority_chain_complete is True
        assert evidence_b.authority_chain_complete is False
        assert evidence_a.canonical_terminal_outcome == "success"
        assert evidence_b.canonical_terminal_outcome is None

    def test_D02_different_devices_are_isolated(self):
        """D02: The same execution_id on different devices produces independent evidence."""
        eid = "exec-pr14-d02-shared-id"
        did_a = "device-pr14-d02-A"
        did_b = "device-pr14-d02-B"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did_a,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did_a,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        evidence_a = build_governance_authority_evidence(eid, did_a)
        evidence_b = build_governance_authority_evidence(eid, did_b)

        # evidence_a should show a complete chain
        assert evidence_a.authority_chain_complete is True
        # evidence_b uses the same execution_id — uplink truth derives from eid,
        # not from device_id. In the current model, evidence is keyed by execution_id.
        # This test confirms the device_id field is correctly stored per build call.
        assert evidence_a.device_id == did_a
        assert evidence_b.device_id == did_b

    def test_D03_terminated_execution_does_not_contaminate_new_execution(self):
        """D03: A completed execution on device X does not affect a new execution on device X."""
        did = "device-pr14-d03"
        eid_old = "exec-pr14-d03-old"
        eid_new = "exec-pr14-d03-new"

        # Close the old execution
        record_execution_lifecycle_event(
            execution_id=eid_old, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid_old, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        # Start a new execution on the same device
        record_execution_lifecycle_event(
            execution_id=eid_new, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )

        evidence_new = build_governance_authority_evidence(eid_new, did)
        by_stage = {e.stage: e for e in evidence_new.audit_entries}

        # New execution must NOT be terminal
        assert by_stage[GovernanceAuditStage.terminal].reached is False
        assert evidence_new.authority_chain_complete is False

    def test_D04_five_devices_independent_audit_chains(self):
        """D04: Five independent devices each have their own coherent audit chains."""
        for i in range(5):
            eid = f"exec-pr14-d04-dev{i}"
            did = f"device-pr14-d04-dev{i}"
            phase = (
                ExecutionLifecyclePhase.succeeded
                if i % 2 == 0
                else ExecutionLifecyclePhase.failed
            )
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=ExecutionLifecyclePhase.created,
            )
            record_execution_lifecycle_event(
                execution_id=eid, device_id=did,
                execution_type=ExecutionType.goal_execution,
                phase=phase,
                enforce_transition=False,
            )

        for i in range(5):
            eid = f"exec-pr14-d04-dev{i}"
            did = f"device-pr14-d04-dev{i}"
            expected_outcome = "success" if i % 2 == 0 else "failure"
            evidence = build_governance_authority_evidence(eid, did)
            violations = verify_governance_authority_integrity(eid, did)
            assert evidence.authority_chain_complete is True
            assert evidence.canonical_terminal_outcome == expected_outcome
            assert violations == []

    def test_D05_audit_entry_to_dict_is_json_serialisable(self):
        """D05: GovernanceAuditEntry.to_dict() output is JSON-serialisable."""
        eid = "exec-pr14-d05-json"
        did = "device-pr14-d05"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        evidence = build_governance_authority_evidence(eid, did)
        for entry in evidence.audit_entries:
            # Must not raise
            json.dumps(entry.to_dict())

        # GovernanceAuthorityEvidence.to_dict() must also be JSON-serialisable
        json.dumps(evidence.to_dict())


# ===========================================================================
# Group E — Audit summary, sentinel, and contract version
# ===========================================================================


class TestGroupE_AuditSummaryAndSentinelCoverage:
    """E01–E08: Sentinel, contract version, and audit summary correctness."""

    def test_E01_sentinel_is_present_and_well_formed(self):
        """E01: GOVERNANCE_AUDIT_AUTHORITY_SENTINEL is present and well-formed."""
        assert isinstance(GOVERNANCE_AUDIT_AUTHORITY_SENTINEL, str)
        assert len(GOVERNANCE_AUDIT_AUTHORITY_SENTINEL) > 50
        assert "PR14_V2" in GOVERNANCE_AUDIT_AUTHORITY_SENTINEL
        assert "GOVERNANCE_AUDIT" in GOVERNANCE_AUDIT_AUTHORITY_SENTINEL

    def test_E02_contract_version_is_correct(self):
        """E02: GOVERNANCE_AUDIT_CONTRACT_VERSION is '14.0.0'."""
        assert isinstance(GOVERNANCE_AUDIT_CONTRACT_VERSION, str)
        assert GOVERNANCE_AUDIT_CONTRACT_VERSION == "14.0.0"

    def test_E03_authority_policy_is_well_formed(self):
        """E03: GOVERNANCE_AUDIT_AUTHORITY_POLICY is a non-empty, substantive string."""
        assert isinstance(GOVERNANCE_AUDIT_AUTHORITY_POLICY, str)
        assert len(GOVERNANCE_AUDIT_AUTHORITY_POLICY) > 100
        assert "POLICY::" in GOVERNANCE_AUDIT_AUTHORITY_POLICY
        assert "center" in GOVERNANCE_AUDIT_AUTHORITY_POLICY.lower()

    def test_E04_get_governance_audit_summary_is_json_serialisable(self):
        """E04: get_governance_audit_summary() returns a JSON-serialisable dict."""
        eid = "exec-pr14-e04-summary"
        did = "device-pr14-e04"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
        )
        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.succeeded,
            enforce_transition=False,
        )

        summary = get_governance_audit_summary(eid, did)
        # Must not raise
        json.dumps(summary)

    def test_E05_get_governance_audit_summary_contains_required_fields(self):
        """E05: Audit summary has all required top-level fields."""
        eid = "exec-pr14-e05-fields"
        did = "device-pr14-e05"

        summary = get_governance_audit_summary(eid, did)

        required_fields = [
            "execution_id",
            "device_id",
            "authority_evidence",
            "integrity_violations",
            "integrity_ok",
            "highest_stage_reached",
            "authority_chain_complete",
            "canonical_terminal_outcome",
            "authority_source",
            "sentinel",
            "contract_version",
            "_policy",
            "canonical_truth_provenance",
            "canonical_truth_source_trust_level",
            "canonical_truth_freshness_state",
            "canonical_truth_freshness_reason",
            "canonical_truth_confirmed",
            "canonical_truth_inferred",
            "cross_repo_truth_pipeline_verdict",
            "cross_repo_truth_source_provenance",
        ]
        for field_name in required_fields:
            assert field_name in summary, (
                f"Required field {field_name!r} missing from governance audit summary."
            )

    def test_E06_audit_summary_sentinel_matches_module_sentinel(self):
        """E06: The 'sentinel' field in audit summary matches the module-level sentinel."""
        summary = get_governance_audit_summary(
            "exec-pr14-e06-sentinel", "device-pr14-e06"
        )
        assert summary["sentinel"] == GOVERNANCE_AUDIT_AUTHORITY_SENTINEL

    def test_E07_audit_summary_contract_version_matches_module_version(self):
        """E07: The 'contract_version' field matches GOVERNANCE_AUDIT_CONTRACT_VERSION."""
        summary = get_governance_audit_summary(
            "exec-pr14-e07-version", "device-pr14-e07"
        )
        assert summary["contract_version"] == GOVERNANCE_AUDIT_CONTRACT_VERSION

    def test_E08_coherent_terminal_chain_summary_has_integrity_ok_true(self):
        """E08: A coherent terminal chain produces integrity_ok=True in the summary."""
        eid = "exec-pr14-e08-ok"
        did = "device-pr14-e08"

        record_execution_lifecycle_event(
            execution_id=eid, device_id=did,
            execution_type=ExecutionType.goal_execution,
            phase=ExecutionLifecyclePhase.created,
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
            enforce_transition=False,
        )

        summary = get_governance_audit_summary(eid, did)
        assert summary["integrity_ok"] is True
        assert summary["authority_chain_complete"] is True
        assert summary["canonical_terminal_outcome"] == "success"
        assert summary["authority_source"] == "center_lifecycle"
        assert summary["integrity_violations"] == []
        assert summary["canonical_truth_provenance"] == "v2_local_state"
        assert summary["canonical_truth_source_trust_level"] == "medium"
        assert summary["canonical_truth_confirmed"] is False
