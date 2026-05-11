"""
tests/test_executable_lifecycle_hardening.py
==============================================
Test suite for core/executable_lifecycle_hardening.py

Validates the end-to-end executable lifecycle hardening module.

Sections:

A. Module import and public symbol accessibility.
B. Sentinel / version format.
C. LifecycleStage enum completeness and ordering.
D. AdmissionOutcome enum completeness.
E. ClosureOutcome enum completeness.
F. LifecycleGateResult dataclass and serialisation.
G. AdmissionDecision dataclass and serialisation.
H. TaskInitiationGateResult dataclass and serialisation.
I. ResultClosureState dataclass and serialisation.
J. ExecutableLifecycleState dataclass and serialisation.
K. build_executable_lifecycle_state — baseline (no Android, clean path).
L. build_executable_lifecycle_state — blocked path (FAIL validation).
M. build_executable_lifecycle_state — degraded path (WARN validation).
N. build_executable_lifecycle_state — Android attached, capabilities visible.
O. build_executable_lifecycle_state — Android attached, no capabilities.
P. build_executable_lifecycle_state — task initiated, closure incomplete.
Q. build_executable_lifecycle_state — result closure established (canonical).
R. build_executable_lifecycle_state — result closure established (recovery).
S. build_executable_lifecycle_state — result closure established (degraded).
T. build_executable_lifecycle_state — explicit failure outcome.
U. build_executable_lifecycle_state — recovery_active flag propagation.
V. build_executable_lifecycle_state — admission outcomes across variants.
W. build_executable_lifecycle_state — task initiation gate blocking cases.
X. build_executable_lifecycle_state — degraded_stages accumulation.
Y. V2UnifiedStateContract lifecycle_hardening integration.
Z. Contract version sentinel format.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import pytest

from core.executable_lifecycle_hardening import (
    EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY,
    EXECUTABLE_LIFECYCLE_HARDENING_VERSION,
    AdmissionDecision,
    AdmissionOutcome,
    ClosureOutcome,
    ExecutableLifecycleState,
    LifecycleGateResult,
    LifecycleStage,
    ResultClosureState,
    TaskInitiationGateResult,
    build_executable_lifecycle_state,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


class _FakeValidation:
    """Minimal OnboardingValidation shim for tests."""

    def __init__(self, status: str = "PASS") -> None:
        self.overall_status = _Attr(status)
        self.summary = f"Fake validation: {status}"

    @property
    def passed(self) -> bool:
        return self.overall_status.value != "FAIL"


class _Attr:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class _FakeKindState:
    def __init__(self, status: str = "ready") -> None:
        self.status = _Attr(status)


def _build_state(
    *,
    validation_status: str = "PASS",
    kind_statuses: List[str] = None,
    route_paths: List[str] = None,
    runtime_verdict: str = "ready",
    android_device_count: int = 0,
    snapshot_count: int = 0,
    capability_visible_count: int = 0,
    degraded_capability_device_count: int = 0,
    active_session_count: int = 0,
    total_session_count: int = 0,
    participant_total_count: int = 0,
    participant_terminal_count: int = 0,
    participant_terminal_success_count: int = 0,
    task_initiated: bool = False,
    result_closure_established: bool = False,
    recovery_active: bool = False,
    completion_notified: bool = False,
    android_device_ids: List[str] = None,
    admitted_device_ids: List[str] = None,
    is_fully_closed: bool = False,
    completion_ingress_confirmed: bool = False,
    explicit_failure: bool = False,
) -> ExecutableLifecycleState:
    default_routes = [
        "/api/v1/health",
        "/api/v1/chat",
        "/api/v1/projection/runtime",
        "/api/v1/projection/operational-readiness",
        "/api/v1/projection/clone-to-use-acceptance",
    ]
    return build_executable_lifecycle_state(
        validation=_FakeValidation(validation_status),
        kind_states=[_FakeKindState(s) for s in (kind_statuses or [])],
        route_paths=route_paths if route_paths is not None else default_routes,
        runtime_readiness={"verdict": runtime_verdict},
        device_evidence={
            "android_device_count": android_device_count,
            "android_device_ids": android_device_ids or [],
            "admitted_device_ids": admitted_device_ids or [],
        },
        android_evidence={
            "snapshot_count": snapshot_count,
            "capability_visible_count": capability_visible_count,
            "degraded_capability_device_count": degraded_capability_device_count,
        },
        session_evidence={
            "active_session_count": active_session_count,
            "total_session_count": total_session_count,
            "participant_total_count": participant_total_count,
            "participant_terminal_count": participant_terminal_count,
            "participant_terminal_success_count": participant_terminal_success_count,
            "task_initiated": task_initiated,
            "result_closure_established": result_closure_established,
            "recovery_active": recovery_active,
            "completion_notified": completion_notified,
        },
        result_ingress_evidence={
            "is_fully_closed": is_fully_closed,
            "completion_ingress_confirmed": completion_ingress_confirmed,
            "explicit_failure": explicit_failure,
        },
    )


# =============================================================================
# Section A — Module import and public symbol accessibility
# =============================================================================


class TestModuleImport:
    def test_authority_sentinel_importable(self) -> None:
        assert isinstance(EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY, str)
        assert len(EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY) > 0

    def test_version_importable(self) -> None:
        assert isinstance(EXECUTABLE_LIFECYCLE_HARDENING_VERSION, str)

    def test_lifecycle_stage_importable(self) -> None:
        assert LifecycleStage is not None

    def test_admission_outcome_importable(self) -> None:
        assert AdmissionOutcome is not None

    def test_closure_outcome_importable(self) -> None:
        assert ClosureOutcome is not None

    def test_dataclasses_importable(self) -> None:
        for cls in (
            LifecycleGateResult,
            AdmissionDecision,
            TaskInitiationGateResult,
            ResultClosureState,
            ExecutableLifecycleState,
        ):
            assert cls is not None

    def test_builder_importable(self) -> None:
        assert callable(build_executable_lifecycle_state)


# =============================================================================
# Section B — Sentinel / version format
# =============================================================================


class TestSentinels:
    def test_authority_contains_module_path(self) -> None:
        assert "executable_lifecycle_hardening" in EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY

    def test_version_is_semver(self) -> None:
        parts = EXECUTABLE_LIFECYCLE_HARDENING_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


# =============================================================================
# Section C — LifecycleStage enum completeness and ordering
# =============================================================================


class TestLifecycleStageEnum:
    def test_all_required_stages_present(self) -> None:
        required = {
            "registration",
            "capability_visibility",
            "admission",
            "operational_readiness",
            "task_initiation",
            "task_execution",
            "result_closure",
        }
        values = {s.value for s in LifecycleStage}
        assert required <= values

    def test_registration_is_first(self) -> None:
        stages = list(LifecycleStage)
        assert stages[0] == LifecycleStage.REGISTRATION

    def test_result_closure_is_last(self) -> None:
        stages = list(LifecycleStage)
        assert stages[-1] == LifecycleStage.RESULT_CLOSURE

    def test_admission_comes_after_capability_visibility(self) -> None:
        stages = list(LifecycleStage)
        idx_cap = stages.index(LifecycleStage.CAPABILITY_VISIBILITY)
        idx_adm = stages.index(LifecycleStage.ADMISSION)
        assert idx_adm > idx_cap

    def test_task_initiation_comes_after_operational_readiness(self) -> None:
        stages = list(LifecycleStage)
        idx_ops = stages.index(LifecycleStage.OPERATIONAL_READINESS)
        idx_task = stages.index(LifecycleStage.TASK_INITIATION)
        assert idx_task > idx_ops


# =============================================================================
# Section D — AdmissionOutcome enum
# =============================================================================


class TestAdmissionOutcomeEnum:
    def test_all_required_outcomes(self) -> None:
        values = {o.value for o in AdmissionOutcome}
        assert "admitted" in values
        assert "admitted_degraded" in values
        assert "denied" in values
        assert "pending" in values
        assert "blocked" in values


# =============================================================================
# Section E — ClosureOutcome enum
# =============================================================================


class TestClosureOutcomeEnum:
    def test_all_required_outcomes(self) -> None:
        values = {o.value for o in ClosureOutcome}
        assert "success_canonical" in values
        assert "success_degraded" in values
        assert "success_recovery" in values
        assert "incomplete_in_progress" in values
        assert "incomplete_blocked" in values
        assert "incomplete_waiting" in values
        assert "failed" in values
        assert "not_applicable" in values


# =============================================================================
# Section F — LifecycleGateResult
# =============================================================================


class TestLifecycleGateResult:
    def test_default_instance(self) -> None:
        gate = LifecycleGateResult()
        assert gate.stage == LifecycleStage.REGISTRATION
        assert gate.passed is False
        assert gate.blocked is False

    def test_to_dict_keys(self) -> None:
        gate = LifecycleGateResult(stage=LifecycleStage.ADMISSION, passed=True)
        d = gate.to_dict()
        assert d["stage"] == "admission"
        assert d["passed"] is True
        assert "blocked" in d
        assert "degraded" in d
        assert "evidence" in d

    def test_serialisable_to_json(self) -> None:
        gate = LifecycleGateResult(stage=LifecycleStage.TASK_INITIATION, passed=False, blocked=True)
        json.dumps(gate.to_dict())  # must not raise


# =============================================================================
# Section G — AdmissionDecision
# =============================================================================


class TestAdmissionDecision:
    def test_default_instance(self) -> None:
        dec = AdmissionDecision()
        assert dec.outcome == AdmissionOutcome.PENDING
        assert dec.is_admitted is False

    def test_is_admitted_for_admitted(self) -> None:
        dec = AdmissionDecision(outcome=AdmissionOutcome.ADMITTED)
        assert dec.is_admitted is True

    def test_is_admitted_for_admitted_degraded(self) -> None:
        dec = AdmissionDecision(outcome=AdmissionOutcome.ADMITTED_DEGRADED)
        assert dec.is_admitted is True

    def test_is_admitted_false_for_denied(self) -> None:
        dec = AdmissionDecision(outcome=AdmissionOutcome.DENIED)
        assert dec.is_admitted is False

    def test_to_dict_contains_is_admitted(self) -> None:
        dec = AdmissionDecision(outcome=AdmissionOutcome.ADMITTED)
        assert dec.to_dict()["is_admitted"] is True

    def test_serialisable_to_json(self) -> None:
        dec = AdmissionDecision(outcome=AdmissionOutcome.BLOCKED)
        json.dumps(dec.to_dict())


# =============================================================================
# Section H — TaskInitiationGateResult
# =============================================================================


class TestTaskInitiationGateResult:
    def test_default_instance(self) -> None:
        gate = TaskInitiationGateResult()
        assert gate.gate_passed is False
        assert gate.eligible is False
        assert gate.blocking_gates == []

    def test_to_dict_keys(self) -> None:
        gate = TaskInitiationGateResult(gate_passed=True, eligible=True)
        d = gate.to_dict()
        for key in (
            "gate_passed",
            "admission_gate_met",
            "capability_gate_met",
            "session_gate_met",
            "readiness_gate_met",
            "blocking_gates",
            "eligible",
        ):
            assert key in d

    def test_serialisable_to_json(self) -> None:
        gate = TaskInitiationGateResult(gate_passed=False, blocking_gates=["admission"])
        json.dumps(gate.to_dict())


# =============================================================================
# Section I — ResultClosureState
# =============================================================================


class TestResultClosureState:
    def test_default_instance(self) -> None:
        state = ResultClosureState()
        assert state.outcome == ClosureOutcome.NOT_APPLICABLE
        assert state.is_complete is False

    def test_is_complete_for_success_canonical(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.SUCCESS_CANONICAL)
        assert state.is_complete is True

    def test_is_complete_for_success_degraded(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.SUCCESS_DEGRADED)
        assert state.is_complete is True

    def test_is_complete_for_success_recovery(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.SUCCESS_RECOVERY)
        assert state.is_complete is True

    def test_is_complete_false_for_incomplete(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.INCOMPLETE_IN_PROGRESS)
        assert state.is_complete is False

    def test_to_dict_contains_is_complete(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.SUCCESS_CANONICAL)
        assert state.to_dict()["is_complete"] is True

    def test_serialisable_to_json(self) -> None:
        state = ResultClosureState(outcome=ClosureOutcome.FAILED)
        json.dumps(state.to_dict())


# =============================================================================
# Section J — ExecutableLifecycleState
# =============================================================================


class TestExecutableLifecycleState:
    def test_default_instance(self) -> None:
        els = ExecutableLifecycleState()
        assert els.authority == EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY
        assert els.contract_version == EXECUTABLE_LIFECYCLE_HARDENING_VERSION

    def test_to_dict_has_all_top_level_keys(self) -> None:
        els = ExecutableLifecycleState()
        d = els.to_dict()
        for key in (
            "authority",
            "contract_version",
            "stage_gates",
            "admission_decision",
            "task_initiation_gate",
            "result_closure",
            "current_stage",
            "lifecycle_blocked",
            "lifecycle_blocked_reason",
            "degraded_stages",
            "recovery_transition",
        ):
            assert key in d

    def test_to_json_is_valid_json(self) -> None:
        els = ExecutableLifecycleState()
        parsed = json.loads(els.to_json())
        assert isinstance(parsed, dict)


# =============================================================================
# Section K — build_executable_lifecycle_state baseline (no Android, clean)
# =============================================================================


class TestBaselineCleanPath:
    def test_returns_executable_lifecycle_state(self) -> None:
        state = _build_state()
        assert isinstance(state, ExecutableLifecycleState)

    def test_registration_gate_passes(self) -> None:
        state = _build_state()
        reg = state.stage_gates[LifecycleStage.REGISTRATION.value]
        assert reg.passed is True

    def test_capability_visibility_gate_passes_no_android(self) -> None:
        state = _build_state()
        cap = state.stage_gates[LifecycleStage.CAPABILITY_VISIBILITY.value]
        assert cap.passed is True  # not applicable for V2-only

    def test_admission_gate_passes_no_android(self) -> None:
        state = _build_state()
        adm = state.stage_gates[LifecycleStage.ADMISSION.value]
        assert adm.passed is True

    def test_admission_decision_admitted(self) -> None:
        state = _build_state()
        assert state.admission_decision.outcome == AdmissionOutcome.ADMITTED

    def test_operational_readiness_passes(self) -> None:
        state = _build_state()
        ops = state.stage_gates[LifecycleStage.OPERATIONAL_READINESS.value]
        assert ops.passed is True

    def test_task_initiation_gate_passed_no_android(self) -> None:
        state = _build_state()
        # Without Android, all gates should pass (not_applicable)
        assert state.task_initiation_gate.gate_passed is True

    def test_result_closure_not_applicable(self) -> None:
        state = _build_state()
        assert state.result_closure.outcome == ClosureOutcome.NOT_APPLICABLE

    def test_lifecycle_not_blocked(self) -> None:
        state = _build_state()
        assert state.lifecycle_blocked is False

    def test_no_degraded_stages(self) -> None:
        state = _build_state()
        assert state.degraded_stages == []

    def test_current_stage_at_least_operational_readiness(self) -> None:
        state = _build_state()
        ordered = [s.value for s in LifecycleStage]
        idx = ordered.index(state.current_stage.value)
        assert idx >= ordered.index(LifecycleStage.OPERATIONAL_READINESS.value)

    def test_serialisable_to_json(self) -> None:
        state = _build_state()
        json.loads(state.to_json())


# =============================================================================
# Section L — blocked path (FAIL validation)
# =============================================================================


class TestBlockedPath:
    def test_registration_gate_blocked_on_fail(self) -> None:
        state = _build_state(validation_status="FAIL")
        reg = state.stage_gates[LifecycleStage.REGISTRATION.value]
        assert reg.passed is False
        assert reg.blocked is True

    def test_lifecycle_blocked_on_fail(self) -> None:
        state = _build_state(validation_status="FAIL")
        assert state.lifecycle_blocked is True

    def test_admission_blocked_on_fail(self) -> None:
        state = _build_state(validation_status="FAIL")
        adm = state.stage_gates[LifecycleStage.ADMISSION.value]
        assert adm.passed is False
        assert adm.blocked is True

    def test_admission_decision_blocked_on_fail(self) -> None:
        state = _build_state(validation_status="FAIL")
        assert state.admission_decision.outcome == AdmissionOutcome.BLOCKED

    def test_current_stage_is_registration_on_fail(self) -> None:
        state = _build_state(validation_status="FAIL")
        assert state.current_stage == LifecycleStage.REGISTRATION

    def test_blocked_reason_is_set(self) -> None:
        state = _build_state(validation_status="FAIL")
        assert len(state.lifecycle_blocked_reason) > 0

    def test_runtime_blocked_also_blocks_lifecycle(self) -> None:
        state = _build_state(runtime_verdict="blocked")
        assert state.lifecycle_blocked is True

    def test_missing_routes_blocks_lifecycle(self) -> None:
        state = _build_state(route_paths=["/api/v1/health"])  # missing others
        assert state.lifecycle_blocked is True


# =============================================================================
# Section M — degraded path (WARN validation)
# =============================================================================


class TestDegradedPath:
    def test_registration_gate_passes_but_degraded(self) -> None:
        state = _build_state(validation_status="WARN")
        reg = state.stage_gates[LifecycleStage.REGISTRATION.value]
        assert reg.passed is True
        assert reg.degraded is True

    def test_lifecycle_not_blocked_on_warn(self) -> None:
        state = _build_state(validation_status="WARN")
        assert state.lifecycle_blocked is False

    def test_registration_in_degraded_stages(self) -> None:
        state = _build_state(validation_status="WARN")
        assert LifecycleStage.REGISTRATION.value in state.degraded_stages

    def test_admission_degraded_on_warn(self) -> None:
        state = _build_state(validation_status="WARN")
        adm = state.admission_decision
        assert adm.outcome == AdmissionOutcome.ADMITTED_DEGRADED

    def test_operational_readiness_degraded_on_warn(self) -> None:
        state = _build_state(validation_status="WARN")
        ops = state.stage_gates[LifecycleStage.OPERATIONAL_READINESS.value]
        assert ops.degraded is True


# =============================================================================
# Section N — Android attached, capabilities visible
# =============================================================================


class TestAndroidAttachedCapabilityVisible:
    def test_admission_admitted(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            android_device_ids=["device-1"],
            active_session_count=1,
        )
        assert state.admission_decision.outcome in (
            AdmissionOutcome.ADMITTED,
            AdmissionOutcome.ADMITTED_DEGRADED,
        )

    def test_capability_gate_passes(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
        )
        cap = state.stage_gates[LifecycleStage.CAPABILITY_VISIBILITY.value]
        assert cap.passed is True

    def test_admitted_device_ids_populated(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            android_device_ids=["device-42"],
        )
        assert "device-42" in state.admission_decision.admitted_device_ids

    def test_task_initiation_eligible_with_all_conditions(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
        )
        assert state.task_initiation_gate.gate_passed is True

    def test_minimum_access_met(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            android_device_ids=["device-1"],
        )
        assert state.admission_decision.minimum_access_met is True


# =============================================================================
# Section O — Android attached, no capabilities
# =============================================================================


class TestAndroidAttachedNoCapabilities:
    def test_capability_gate_fails(self) -> None:
        state = _build_state(android_device_count=1, capability_visible_count=0)
        cap = state.stage_gates[LifecycleStage.CAPABILITY_VISIBILITY.value]
        assert cap.passed is False

    def test_admission_pending_no_capabilities(self) -> None:
        state = _build_state(android_device_count=1, capability_visible_count=0)
        assert state.admission_decision.outcome == AdmissionOutcome.PENDING

    def test_task_initiation_blocked_no_capabilities(self) -> None:
        state = _build_state(android_device_count=1, capability_visible_count=0)
        assert state.task_initiation_gate.gate_passed is False
        assert "capability" in state.task_initiation_gate.blocking_gates


# =============================================================================
# Section P — task initiated, closure incomplete
# =============================================================================


class TestTaskInitiatedClosureIncomplete:
    def test_task_execution_gate_passes(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
            task_initiated=True,
        )
        exec_gate = state.stage_gates[LifecycleStage.TASK_EXECUTION.value]
        assert exec_gate.passed is True

    def test_closure_outcome_incomplete_in_progress(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
            task_initiated=True,
        )
        assert state.result_closure.outcome == ClosureOutcome.INCOMPLETE_IN_PROGRESS

    def test_result_closure_gate_not_passed(self) -> None:
        state = _build_state(task_initiated=True)
        closure_gate = state.stage_gates[LifecycleStage.RESULT_CLOSURE.value]
        assert closure_gate.passed is False

    def test_result_closure_not_complete(self) -> None:
        state = _build_state(task_initiated=True)
        assert state.result_closure.is_complete is False

    def test_task_closed_false(self) -> None:
        state = _build_state(task_initiated=True)
        assert state.result_closure.task_closed is False


# =============================================================================
# Section Q — result closure established (canonical)
# =============================================================================


class TestCanonicalClosure:
    def test_closure_outcome_success_canonical(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            task_initiated=True,
            result_closure_established=True,
            is_fully_closed=True,
            completion_ingress_confirmed=True,
            participant_terminal_count=1,
            participant_terminal_success_count=1,
        )
        assert state.result_closure.outcome == ClosureOutcome.SUCCESS_CANONICAL

    def test_closure_is_complete(self) -> None:
        state = _build_state(
            task_initiated=True,
            result_closure_established=True,
            is_fully_closed=True,
            completion_ingress_confirmed=True,
        )
        assert state.result_closure.is_complete is True

    def test_closure_authoritative(self) -> None:
        state = _build_state(
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
        )
        assert state.result_closure.authoritative is True

    def test_task_closed_true(self) -> None:
        state = _build_state(
            task_initiated=True,
            result_closure_established=True,
        )
        assert state.result_closure.task_closed is True

    def test_closure_gate_passed(self) -> None:
        state = _build_state(
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
        )
        closure_gate = state.stage_gates[LifecycleStage.RESULT_CLOSURE.value]
        assert closure_gate.passed is True

    def test_current_stage_is_result_closure(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
            participant_terminal_count=1,
            participant_terminal_success_count=1,
        )
        assert state.current_stage == LifecycleStage.RESULT_CLOSURE

    def test_closure_requires_terminal_continuity(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
            participant_terminal_count=0,
            participant_terminal_success_count=0,
        )
        assert state.result_closure.authoritative is False
        assert "session_continuity_unconfirmed" in state.result_closure.degraded_reasons
        assert state.stage_gates[LifecycleStage.RESULT_CLOSURE.value].passed is False


# =============================================================================
# Section R — result closure (recovery)
# =============================================================================


class TestRecoveryClosure:
    def test_closure_outcome_success_recovery(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            task_initiated=True,
            result_closure_established=True,
            recovery_active=True,
            completion_ingress_confirmed=True,
        )
        assert state.result_closure.outcome == ClosureOutcome.SUCCESS_RECOVERY

    def test_recovery_transition_flag_set(self) -> None:
        state = _build_state(recovery_active=True)
        assert state.recovery_transition is True

    def test_recovery_in_degraded_stages(self) -> None:
        # Recovery should cause OPERATIONAL_READINESS stage to be degraded
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["device-1"],
            recovery_active=True,
        )
        assert LifecycleStage.OPERATIONAL_READINESS.value in state.degraded_stages


# =============================================================================
# Section S — result closure (degraded)
# =============================================================================


class TestDegradedClosure:
    def test_closure_outcome_success_degraded(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            degraded_capability_device_count=1,
            active_session_count=1,
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
        )
        assert state.result_closure.outcome == ClosureOutcome.SUCCESS_DEGRADED

    def test_degraded_reasons_not_empty_on_degraded_closure(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            degraded_capability_device_count=1,
            task_initiated=True,
            result_closure_established=True,
            completion_ingress_confirmed=True,
        )
        assert len(state.result_closure.degraded_reasons) > 0


# =============================================================================
# Section T — explicit failure outcome
# =============================================================================


class TestExplicitFailureOutcome:
    def test_closure_outcome_failed_on_explicit_failure(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            task_initiated=True,
            explicit_failure=True,
        )
        assert state.result_closure.outcome == ClosureOutcome.FAILED

    def test_failed_is_not_complete(self) -> None:
        state = _build_state(
            task_initiated=True,
            explicit_failure=True,
        )
        assert state.result_closure.is_complete is False


# =============================================================================
# Section U — recovery_active flag propagation
# =============================================================================


class TestRecoveryActivePropagation:
    def test_recovery_transition_true(self) -> None:
        state = _build_state(recovery_active=True)
        assert state.recovery_transition is True

    def test_recovery_not_set_by_default(self) -> None:
        state = _build_state()
        assert state.recovery_transition is False

    def test_operational_readiness_degraded_on_recovery(self) -> None:
        state = _build_state(recovery_active=True)
        ops = state.stage_gates[LifecycleStage.OPERATIONAL_READINESS.value]
        assert ops.degraded is True


# =============================================================================
# Section V — admission outcomes across variants
# =============================================================================


class TestAdmissionOutcomeVariants:
    def test_blocked_when_main_chain_unavailable(self) -> None:
        state = _build_state(runtime_verdict="blocked")
        assert state.admission_decision.outcome == AdmissionOutcome.BLOCKED

    def test_pending_when_android_attached_no_capability(self) -> None:
        state = _build_state(android_device_count=1, capability_visible_count=0)
        assert state.admission_decision.outcome == AdmissionOutcome.PENDING

    def test_admitted_on_clean_no_android(self) -> None:
        state = _build_state()
        assert state.admission_decision.outcome == AdmissionOutcome.ADMITTED

    def test_admitted_degraded_on_warn_validation(self) -> None:
        state = _build_state(validation_status="WARN")
        assert state.admission_decision.outcome == AdmissionOutcome.ADMITTED_DEGRADED

    def test_minimum_access_gap_populated_when_blocked(self) -> None:
        state = _build_state(runtime_verdict="blocked")
        assert len(state.admission_decision.minimum_access_gap) > 0


# =============================================================================
# Section W — task initiation gate blocking cases
# =============================================================================


class TestTaskInitiationGateBlocking:
    def test_readiness_gate_fails_when_main_chain_blocked(self) -> None:
        state = _build_state(runtime_verdict="blocked")
        gate = state.task_initiation_gate
        assert gate.readiness_gate_met is False
        assert "readiness" in gate.blocking_gates

    def test_admission_gate_fails_when_blocked(self) -> None:
        state = _build_state(validation_status="FAIL")
        gate = state.task_initiation_gate
        assert gate.admission_gate_met is False
        assert "admission" in gate.blocking_gates

    def test_capability_gate_fails_without_capability(self) -> None:
        state = _build_state(android_device_count=1, capability_visible_count=0)
        gate = state.task_initiation_gate
        assert gate.capability_gate_met is False
        assert "capability" in gate.blocking_gates

    def test_session_gate_fails_without_active_session(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=0,
        )
        gate = state.task_initiation_gate
        assert gate.session_gate_met is False
        assert "session" in gate.blocking_gates

    def test_all_gates_met_for_full_android_path(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            active_session_count=1,
            android_device_ids=["d1"],
        )
        gate = state.task_initiation_gate
        assert gate.gate_passed is True
        assert gate.blocking_gates == []

    def test_incomplete_blocked_when_task_init_gate_blocked(self) -> None:
        # task_initiated=True but gate couldn't have legitimately passed
        state = _build_state(
            android_device_count=1,
            capability_visible_count=0,
            task_initiated=True,
        )
        # Closure should reflect blocked initiation path
        assert state.result_closure.outcome in (
            ClosureOutcome.INCOMPLETE_BLOCKED,
            ClosureOutcome.INCOMPLETE_IN_PROGRESS,
            ClosureOutcome.INCOMPLETE_WAITING,
        )


# =============================================================================
# Section X — degraded_stages accumulation
# =============================================================================


class TestDegradedStagesAccumulation:
    def test_no_degraded_stages_on_clean_path(self) -> None:
        state = _build_state()
        assert state.degraded_stages == []

    def test_registration_degraded_on_warn(self) -> None:
        state = _build_state(validation_status="WARN")
        assert LifecycleStage.REGISTRATION.value in state.degraded_stages

    def test_operational_readiness_degraded_on_warn(self) -> None:
        state = _build_state(validation_status="WARN")
        assert LifecycleStage.OPERATIONAL_READINESS.value in state.degraded_stages

    def test_capability_degraded_stage(self) -> None:
        state = _build_state(
            android_device_count=1,
            capability_visible_count=1,
            degraded_capability_device_count=1,
        )
        assert LifecycleStage.CAPABILITY_VISIBILITY.value in state.degraded_stages

    def test_degraded_stages_is_list(self) -> None:
        state = _build_state(validation_status="WARN")
        assert isinstance(state.degraded_stages, list)


# =============================================================================
# Section Y — V2UnifiedStateContract lifecycle_hardening integration
# =============================================================================


class TestV2UnifiedStateContractIntegration:
    """Verify lifecycle_hardening is populated in V2UnifiedStateContract."""

    def _build_contract(self) -> "V2UnifiedStateContract":
        from core.operational_registration_path import (
            OnboardingValidation,
            PrerequisiteCheck,
            ValidationStatus,
            build_operational_registration_path,
        )
        from core.v2_unified_state_contract import V2UnifiedStateContract, build_v2_unified_state_contract

        path = build_operational_registration_path()
        validation = OnboardingValidation(
            checks=[
                PrerequisiteCheck(
                    name="test",
                    status=ValidationStatus.PASS,
                    message="ok",
                )
            ],
            overall_status=ValidationStatus.PASS,
            summary="ok",
        )
        return build_v2_unified_state_contract(
            path=path,
            validation=validation,
            kind_states=[],
            route_paths=[
                "/api/v1/health",
                "/api/v1/chat",
                "/api/v1/projection/runtime",
                "/api/v1/projection/operational-readiness",
                "/api/v1/projection/clone-to-use-acceptance",
            ],
        )

    def test_lifecycle_hardening_is_populated(self) -> None:
        contract = self._build_contract()
        assert contract.lifecycle_hardening is not None

    def test_lifecycle_hardening_is_dict(self) -> None:
        contract = self._build_contract()
        assert isinstance(contract.lifecycle_hardening, dict)

    def test_lifecycle_hardening_has_authority(self) -> None:
        contract = self._build_contract()
        assert "authority" in contract.lifecycle_hardening

    def test_lifecycle_hardening_has_stage_gates(self) -> None:
        contract = self._build_contract()
        assert "stage_gates" in contract.lifecycle_hardening

    def test_lifecycle_hardening_has_admission_decision(self) -> None:
        contract = self._build_contract()
        assert "admission_decision" in contract.lifecycle_hardening

    def test_lifecycle_hardening_has_task_initiation_gate(self) -> None:
        contract = self._build_contract()
        assert "task_initiation_gate" in contract.lifecycle_hardening

    def test_lifecycle_hardening_has_result_closure(self) -> None:
        contract = self._build_contract()
        assert "result_closure" in contract.lifecycle_hardening

    def test_to_dict_includes_lifecycle_hardening(self) -> None:
        contract = self._build_contract()
        d = contract.to_dict()
        assert "lifecycle_hardening" in d

    def test_to_json_round_trip(self) -> None:
        contract = self._build_contract()
        parsed = json.loads(contract.to_json())
        assert "lifecycle_hardening" in parsed

    def test_contract_version_updated(self) -> None:
        from core.v2_unified_state_contract import V2_UNIFIED_STATE_CONTRACT_VERSION
        parts = V2_UNIFIED_STATE_CONTRACT_VERSION.split(".")
        assert len(parts) == 3


# =============================================================================
# Section Z — Contract version sentinel format
# =============================================================================


class TestContractVersionSentinel:
    def test_version_is_string(self) -> None:
        assert isinstance(EXECUTABLE_LIFECYCLE_HARDENING_VERSION, str)

    def test_version_semver_format(self) -> None:
        parts = EXECUTABLE_LIFECYCLE_HARDENING_VERSION.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_authority_is_non_empty_string(self) -> None:
        assert isinstance(EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY, str)
        assert len(EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY) > 10
