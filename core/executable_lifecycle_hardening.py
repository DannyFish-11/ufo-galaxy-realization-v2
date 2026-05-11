"""
core/executable_lifecycle_hardening.py
=======================================
Executable end-to-end lifecycle hardening for the Galaxy V2 center-governed
distributed system.

Background
----------
Prior work (PR1114 / PR1115) established unified registration paths, state
aggregation, and observability. However the transition from *observation* to
*authoritative execution gating and closure* remained soft:

* Admission was inferred from the presence of lifecycle events rather than
  being an explicit, testable gate.
* Task-initiation eligibility was expressed as a set of conditions without a
  single hard pass/fail decision.
* Result closure could not distinguish ``blocked``, ``degraded_incomplete``,
  ``recovery_incomplete``, or genuine ``success`` outcomes — all falling into
  the same ``incomplete`` bucket.
* Degraded and recovery transitions were side observations in the derived
  state rather than first-class lifecycle stage transitions.
* Session/task continuity was not reflected in closure-relevant decisions.

This module closes those gaps by implementing:

1. **LifecycleStage** — ordered canonical stages every participant/device/session
   must traverse: REGISTRATION → CAPABILITY_VISIBILITY → ADMISSION →
   OPERATIONAL_READINESS → TASK_INITIATION → TASK_EXECUTION → RESULT_CLOSURE.

2. **AdmissionOutcome** / **AdmissionDecision** — an explicit, non-inferred
   admission gate that distinguishes ``admitted``, ``admitted_degraded``,
   ``denied``, ``pending``, and ``blocked``.  The minimum access standard is
   checked here.

3. **TaskInitiationGateResult** — a multi-gate hard check (admission gate,
   capability gate, session gate, readiness gate) whose composite ``gate_passed``
   is the single source of truth for task initiation eligibility.

4. **ClosureOutcome** / **ResultClosureState** — authoritative closure semantics
   that distinguish ``success_canonical``, ``success_degraded``,
   ``success_recovery``, ``incomplete_in_progress``, ``incomplete_blocked``,
   ``incomplete_waiting``, ``failed``, and ``not_applicable``.

5. **ExecutableLifecycleState** — the complete hardened lifecycle view that
   includes per-stage gate results, the admission decision, the task initiation
   gate, the result closure state, and explicit degraded/recovery transition
   annotations.

6. **build_executable_lifecycle_state()** — the single public function that
   produces ``ExecutableLifecycleState`` from the same evidence surfaces already
   consumed by ``core.v2_unified_state_contract``.

Design notes
------------
* **Additive only** — does not replace or bypass any existing canonical module.
* **Pure Python** — no fastapi, pydantic, or other heavy runtime dependencies.
* All public types are JSON-serialisable via ``to_dict()`` / ``to_json()``.
* All decisions are deterministic given the same input evidence.

Public API
----------
Authority sentinels::

    EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY
    EXECUTABLE_LIFECYCLE_HARDENING_VERSION

Enumerations::

    LifecycleStage
    AdmissionOutcome
    ClosureOutcome

Dataclasses::

    LifecycleGateResult
    AdmissionDecision
    TaskInitiationGateResult
    ResultClosureState
    ExecutableLifecycleState

Functions::

    build_executable_lifecycle_state(
        *,
        validation,
        kind_states,
        route_paths,
        runtime_readiness,
        device_evidence,
        android_evidence,
        session_evidence,
        system_acceptance,
        result_ingress_evidence,
    ) -> ExecutableLifecycleState
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("Galaxy.ExecutableLifecycleHardening")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY: str = (
    "core/executable_lifecycle_hardening.py:EXECUTABLE_LIFECYCLE_HARDENING "
    "— executable end-to-end lifecycle hardening for Galaxy V2 "
    "center-governed distributed intelligent agent system"
)

EXECUTABLE_LIFECYCLE_HARDENING_VERSION: str = "1.0.0"

# Minimum-access-standard: these conditions must ALL be met for a participant/
# device to be considered admitted at the canonical level.
_MINIMUM_ACCESS_STANDARD: tuple[str, ...] = (
    "main_chain_not_blocked",
    "required_routes_present",
    "runtime_verdict_not_blocked",
    "device_admitted",
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class LifecycleStage(str, Enum):
    """Ordered canonical stages of the Galaxy executable lifecycle.

    Every participant/device/session MUST traverse these stages in order for
    the system to consider the operational lifecycle complete.
    """

    REGISTRATION = "registration"
    """Device/participant is visible and identified in the registry."""

    CAPABILITY_VISIBILITY = "capability_visibility"
    """Device capabilities are reported and observable on V2."""

    ADMISSION = "admission"
    """Explicit admission gate: participant/device is authorised for the
    current session.  This stage is a hard gate — progress to later stages
    MUST NOT occur without an ``AdmissionOutcome`` of ``admitted`` or
    ``admitted_degraded``."""

    OPERATIONAL_READINESS = "operational_readiness"
    """System meets the minimum access standard for operation.  The active
    path (main_chain / cross_device / compat) and the runtime verdict are
    evaluated here."""

    TASK_INITIATION = "task_initiation"
    """Task initiation is gated: all four sub-gates (admission, capability,
    session, readiness) must pass before a task may be dispatched."""

    TASK_EXECUTION = "task_execution"
    """A task is actively executing.  This stage persists until the task
    produces a terminal outcome."""

    RESULT_CLOSURE = "result_closure"
    """Authoritative closure of the operational lifecycle: the result is
    accepted, stored, and communicated.  The ``ClosureOutcome`` distinguishes
    canonical success from degraded, recovery, blocked, or incomplete
    outcomes."""


class AdmissionOutcome(str, Enum):
    """Explicit admission decision outcome.

    Replaces the previous inference-based approach (admission was deemed to
    have occurred if any lifecycle event was recorded).
    """

    ADMITTED = "admitted"
    """Participant/device is fully admitted on the canonical path."""

    ADMITTED_DEGRADED = "admitted_degraded"
    """Admitted but on a degraded or compat path; capabilities may be
    reduced."""

    DENIED = "denied"
    """Admission explicitly denied due to capability, policy, or
    incompatibility failure."""

    PENDING = "pending"
    """Sufficient evidence is not yet available to decide."""

    BLOCKED = "blocked"
    """Admission is blocked because a hard prerequisite (e.g. main-chain
    routing, runtime) is not met."""


class ClosureOutcome(str, Enum):
    """Authoritative result-closure outcome.

    Replaces the previous binary ``complete`` / ``incomplete`` with a richer
    taxonomy that captures quality, degradation, and recovery context.
    """

    SUCCESS_CANONICAL = "success_canonical"
    """Task completed successfully on the canonical main-chain / cross-device
    path at full quality."""

    SUCCESS_DEGRADED = "success_degraded"
    """Task completed but via a degraded or compat path; quality below
    canonical."""

    SUCCESS_RECOVERY = "success_recovery"
    """Task completed after a recovery / reconnect transition."""

    INCOMPLETE_IN_PROGRESS = "incomplete_in_progress"
    """Task has been initiated but execution has not yet produced a terminal
    result."""

    INCOMPLETE_BLOCKED = "incomplete_blocked"
    """Task initiation started but was blocked before execution could
    complete."""

    INCOMPLETE_WAITING = "incomplete_waiting"
    """Result evidence has not yet arrived; waiting for uplink."""

    FAILED = "failed"
    """Task execution produced an explicit failure outcome."""

    NOT_APPLICABLE = "not_applicable"
    """No task was initiated; closure state is not applicable."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class LifecycleGateResult:
    """Result of evaluating a single lifecycle stage gate.

    Attributes
    ----------
    stage
        The :class:`LifecycleStage` this gate guards.
    passed
        ``True`` iff the stage gate is satisfied.
    blocked
        ``True`` iff a hard blocker prevents this stage from being reached.
    degraded
        ``True`` iff the stage is reachable but with degraded quality.
    blocked_reason
        Human-readable explanation when ``blocked`` is ``True``.
    degraded_reasons
        List of reasons why this stage is degraded (may be empty).
    evidence
        Key/value evidence backing this gate decision.
    """

    stage: LifecycleStage = LifecycleStage.REGISTRATION
    passed: bool = False
    blocked: bool = False
    degraded: bool = False
    blocked_reason: str = ""
    degraded_reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage.value,
            "passed": self.passed,
            "blocked": self.blocked,
            "degraded": self.degraded,
            "blocked_reason": self.blocked_reason,
            "degraded_reasons": list(self.degraded_reasons),
            "evidence": dict(self.evidence),
        }


@dataclass
class AdmissionDecision:
    """Explicit admission decision for the current participant/device.

    Attributes
    ----------
    outcome
        The :class:`AdmissionOutcome` of the admission gate evaluation.
    reason
        Human-readable explanation for the decision.
    minimum_access_met
        ``True`` iff all criteria in ``_MINIMUM_ACCESS_STANDARD`` are
        satisfied.
    minimum_access_gap
        List of unmet minimum-access-standard criteria.
    admitted_device_ids
        Device IDs that were admitted in this evaluation.
    denied_device_ids
        Device IDs that were denied in this evaluation.
    evidence
        Key/value evidence backing the admission decision.
    """

    outcome: AdmissionOutcome = AdmissionOutcome.PENDING
    reason: str = ""
    minimum_access_met: bool = False
    minimum_access_gap: List[str] = field(default_factory=list)
    admitted_device_ids: List[str] = field(default_factory=list)
    denied_device_ids: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_admitted(self) -> bool:
        return self.outcome in (AdmissionOutcome.ADMITTED, AdmissionOutcome.ADMITTED_DEGRADED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "reason": self.reason,
            "minimum_access_met": self.minimum_access_met,
            "minimum_access_gap": list(self.minimum_access_gap),
            "admitted_device_ids": list(self.admitted_device_ids),
            "denied_device_ids": list(self.denied_device_ids),
            "evidence": dict(self.evidence),
            "is_admitted": self.is_admitted,
        }


@dataclass
class TaskInitiationGateResult:
    """Hard multi-gate check for task initiation eligibility.

    Each sub-gate must pass for ``gate_passed`` to be ``True``.  The reason
    every gate is evaluated independently (even when a prior gate fails) is to
    give operators a complete picture of all blocking conditions.

    Attributes
    ----------
    gate_passed
        ``True`` iff ALL sub-gates pass.  This is the single authoritative
        signal used to permit task dispatch.
    admission_gate_met
        The participant/device was admitted (or admitted_degraded).
    capability_gate_met
        At least one capable device has visible capabilities on V2.
    session_gate_met
        An active session exists for the participant.
    readiness_gate_met
        Operational readiness is not blocked.
    blocking_gates
        Names of gates that are currently failing.
    eligible
        Alias for ``gate_passed`` (for backward compatibility with the
        previous eligibility surface).
    degraded
        ``True`` iff any gate is met but in a degraded state.
    evidence
        Key/value evidence backing the gate evaluation.
    """

    gate_passed: bool = False
    admission_gate_met: bool = False
    capability_gate_met: bool = False
    session_gate_met: bool = False
    readiness_gate_met: bool = False
    blocking_gates: List[str] = field(default_factory=list)
    eligible: bool = False
    degraded: bool = False
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_passed": self.gate_passed,
            "admission_gate_met": self.admission_gate_met,
            "capability_gate_met": self.capability_gate_met,
            "session_gate_met": self.session_gate_met,
            "readiness_gate_met": self.readiness_gate_met,
            "blocking_gates": list(self.blocking_gates),
            "eligible": self.eligible,
            "degraded": self.degraded,
            "evidence": dict(self.evidence),
        }


@dataclass
class ResultClosureState:
    """Authoritative result-closure state.

    Attributes
    ----------
    outcome
        The :class:`ClosureOutcome` of the result closure evaluation.
    authoritative
        ``True`` iff the closure was confirmed by the canonical completion
        ingress (not just inferred from uplink observation).
    session_closed
        ``True`` iff the participant session reached a terminal state.
    task_closed
        ``True`` iff the task lifecycle reached a terminal phase.
    completion_notified
        ``True`` iff the CanonicalCompletionIngress confirmed the
        notification was delivered.
    degraded_reasons
        List of reasons why the closure is degraded (empty for canonical
        success).
    evidence
        Key/value evidence backing the closure state.
    """

    outcome: ClosureOutcome = ClosureOutcome.NOT_APPLICABLE
    authoritative: bool = False
    session_closed: bool = False
    task_closed: bool = False
    completion_notified: bool = False
    degraded_reasons: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        return self.outcome in (
            ClosureOutcome.SUCCESS_CANONICAL,
            ClosureOutcome.SUCCESS_DEGRADED,
            ClosureOutcome.SUCCESS_RECOVERY,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "authoritative": self.authoritative,
            "session_closed": self.session_closed,
            "task_closed": self.task_closed,
            "completion_notified": self.completion_notified,
            "degraded_reasons": list(self.degraded_reasons),
            "evidence": dict(self.evidence),
            "is_complete": self.is_complete,
        }


@dataclass
class ExecutableLifecycleState:
    """Complete hardened executable lifecycle state.

    This is the top-level artifact produced by
    :func:`build_executable_lifecycle_state`.  It captures:

    * Per-stage gate results (``stage_gates``).
    * An explicit admission decision (``admission_decision``).
    * A hard multi-gate task-initiation check (``task_initiation_gate``).
    * An authoritative result-closure state (``result_closure``).
    * The current highest reached stage (``current_stage``).
    * Any blocking condition with its reason (``lifecycle_blocked``,
      ``lifecycle_blocked_reason``).
    * Which stages are degraded (``degraded_stages``).
    * Whether a recovery transition is active (``recovery_transition``).

    Attributes
    ----------
    authority
        Module authority sentinel.
    contract_version
        Contract version of this module.
    stage_gates
        Mapping of :class:`LifecycleStage` value to :class:`LifecycleGateResult`.
    admission_decision
        The explicit :class:`AdmissionDecision` for the current evaluation.
    task_initiation_gate
        The hard multi-gate :class:`TaskInitiationGateResult`.
    result_closure
        The authoritative :class:`ResultClosureState`.
    current_stage
        The highest lifecycle stage whose gate has passed.
    lifecycle_blocked
        ``True`` iff the lifecycle is blocked from advancing.
    lifecycle_blocked_reason
        Human-readable reason when ``lifecycle_blocked`` is ``True``.
    degraded_stages
        Names of lifecycle stages that are reached but degraded.
    recovery_transition
        ``True`` iff a recovery/reconnect transition is currently active
        and is part of the lifecycle progression.
    """

    authority: str = EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY
    contract_version: str = EXECUTABLE_LIFECYCLE_HARDENING_VERSION
    stage_gates: Dict[str, LifecycleGateResult] = field(default_factory=dict)
    admission_decision: AdmissionDecision = field(default_factory=AdmissionDecision)
    task_initiation_gate: TaskInitiationGateResult = field(default_factory=TaskInitiationGateResult)
    result_closure: ResultClosureState = field(default_factory=ResultClosureState)
    current_stage: LifecycleStage = LifecycleStage.REGISTRATION
    lifecycle_blocked: bool = False
    lifecycle_blocked_reason: str = ""
    degraded_stages: List[str] = field(default_factory=list)
    recovery_transition: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "authority": self.authority,
            "contract_version": self.contract_version,
            "stage_gates": {k: v.to_dict() for k, v in self.stage_gates.items()},
            "admission_decision": self.admission_decision.to_dict(),
            "task_initiation_gate": self.task_initiation_gate.to_dict(),
            "result_closure": self.result_closure.to_dict(),
            "current_stage": self.current_stage.value,
            "lifecycle_blocked": self.lifecycle_blocked,
            "lifecycle_blocked_reason": self.lifecycle_blocked_reason,
            "degraded_stages": list(self.degraded_stages),
            "recovery_transition": self.recovery_transition,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _str(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value) if value is not None else ""


def _evaluate_registration_gate(
    *,
    validation_status: str,
    main_chain_blocked: bool,
    android_device_count: int,
    route_paths_set: frozenset,
    required_routes: frozenset,
) -> LifecycleGateResult:
    """Registration gate: device is visible and registered."""
    missing_routes = sorted(r for r in required_routes if r not in route_paths_set)
    required_routes_missing = bool(missing_routes)
    blocked = validation_status == "FAIL" or required_routes_missing
    degraded = validation_status == "WARN"
    degraded_reasons: List[str] = []
    if degraded:
        degraded_reasons.append("validation_status_warn")
    if main_chain_blocked and not blocked:
        degraded = True
        degraded_reasons.append("main_chain_blocked")
    if blocked:
        if validation_status == "FAIL":
            blocked_reason = "Prerequisite validation failed (FAIL status)."
        else:
            blocked_reason = f"Required API route(s) not registered: {missing_routes}."
    else:
        blocked_reason = ""
    return LifecycleGateResult(
        stage=LifecycleStage.REGISTRATION,
        passed=not blocked,
        blocked=blocked,
        degraded=degraded,
        blocked_reason=blocked_reason,
        degraded_reasons=degraded_reasons,
        evidence={
            "validation_status": validation_status,
            "main_chain_blocked": main_chain_blocked,
            "android_device_count": android_device_count,
            "missing_required_routes": missing_routes,
        },
    )


def _evaluate_capability_visibility_gate(
    *,
    android_attached: bool,
    capability_visible: bool,
    capability_degraded: bool,
    registration_passed: bool,
) -> LifecycleGateResult:
    """Capability visibility gate: device capabilities are observable."""
    if not registration_passed:
        return LifecycleGateResult(
            stage=LifecycleStage.CAPABILITY_VISIBILITY,
            passed=False,
            blocked=True,
            blocked_reason="Registration gate has not passed.",
            evidence={"registration_passed": registration_passed},
        )
    if not android_attached:
        # For V2-only paths without Android, capability visibility is trivially
        # not required; the gate is treated as passed (not applicable).
        return LifecycleGateResult(
            stage=LifecycleStage.CAPABILITY_VISIBILITY,
            passed=True,
            blocked=False,
            degraded=False,
            evidence={"android_attached": android_attached, "not_applicable": True},
        )
    degraded_reasons: List[str] = []
    if capability_degraded:
        degraded_reasons.append("capability_degraded")
    return LifecycleGateResult(
        stage=LifecycleStage.CAPABILITY_VISIBILITY,
        passed=capability_visible,
        blocked=False,
        degraded=bool(degraded_reasons),
        blocked_reason=(
            ""
            if capability_visible
            else (
                "Android device is attached but capability reporting has not yet completed. "
                "Check that the Android app has completed its capability report handshake and "
                "that the gateway capability_report handler is receiving messages."
            )
        ),
        degraded_reasons=degraded_reasons,
        evidence={
            "android_attached": android_attached,
            "capability_visible": capability_visible,
            "capability_degraded": capability_degraded,
        },
    )


def _evaluate_admission_gate(
    *,
    main_chain_available: bool,
    runtime_verdict: str,
    android_attached: bool,
    capability_visible: bool,
    device_evidence: Dict[str, Any],
    degraded: bool,
    capability_gate_passed: bool,
    registration_gate_passed: bool,
) -> tuple[LifecycleGateResult, AdmissionDecision]:
    """Admission gate: explicit hard gate for participant/device admission.

    Returns both the gate result (for the stage_gates map) and the
    AdmissionDecision (top-level field).
    """
    admitted_device_ids: List[str] = list(device_evidence.get("admitted_device_ids", []))
    denied_device_ids: List[str] = list(device_evidence.get("denied_device_ids", []))
    android_device_ids: List[str] = list(device_evidence.get("android_device_ids", []))

    # --- Minimum access standard checks ---
    access_gap: List[str] = []
    if not main_chain_available:
        access_gap.append("main_chain_not_blocked")
    if runtime_verdict == "blocked":
        access_gap.append("runtime_verdict_not_blocked")
    if android_attached and not capability_visible:
        access_gap.append("device_admitted")
    minimum_access_met = len(access_gap) == 0

    # --- Derive outcome ---
    if not registration_gate_passed:
        outcome = AdmissionOutcome.BLOCKED
        reason = "Admission blocked: registration gate has not passed."
    elif not main_chain_available or runtime_verdict == "blocked":
        outcome = AdmissionOutcome.BLOCKED
        reason = "Admission blocked: main chain or runtime is not available."
    elif denied_device_ids and not admitted_device_ids and not android_attached:
        outcome = AdmissionOutcome.DENIED
        reason = "Admission denied: all candidate devices were explicitly rejected."
    elif not android_attached:
        # V2-only: admission is implicit if main chain and runtime are OK.
        if degraded:
            outcome = AdmissionOutcome.ADMITTED_DEGRADED
            reason = "Admitted (V2-only) on degraded path."
        else:
            outcome = AdmissionOutcome.ADMITTED
            reason = "Admitted (V2-only) on main chain."
    elif not capability_gate_passed:
        # Android is present but capabilities not visible yet.
        outcome = AdmissionOutcome.PENDING
        reason = "Admission pending: capability visibility not yet confirmed."
    elif android_device_ids or admitted_device_ids:
        if degraded:
            outcome = AdmissionOutcome.ADMITTED_DEGRADED
            reason = "Admitted with degraded capability evidence."
            if not admitted_device_ids:
                admitted_device_ids = list(android_device_ids)
        else:
            outcome = AdmissionOutcome.ADMITTED
            reason = "Admitted on canonical evidence."
            if not admitted_device_ids:
                admitted_device_ids = list(android_device_ids)
    else:
        outcome = AdmissionOutcome.PENDING
        reason = "No admitted device evidence available; admission pending."

    admission_decision = AdmissionDecision(
        outcome=outcome,
        reason=reason,
        minimum_access_met=minimum_access_met,
        minimum_access_gap=access_gap,
        admitted_device_ids=admitted_device_ids,
        denied_device_ids=denied_device_ids,
        evidence={
            "main_chain_available": main_chain_available,
            "runtime_verdict": runtime_verdict,
            "android_attached": android_attached,
            "capability_visible": capability_visible,
            "degraded": degraded,
            "android_device_count": len(android_device_ids),
        },
    )

    gate_passed = outcome in (AdmissionOutcome.ADMITTED, AdmissionOutcome.ADMITTED_DEGRADED)
    gate_result = LifecycleGateResult(
        stage=LifecycleStage.ADMISSION,
        passed=gate_passed,
        blocked=outcome == AdmissionOutcome.BLOCKED,
        degraded=outcome == AdmissionOutcome.ADMITTED_DEGRADED,
        blocked_reason=reason if outcome == AdmissionOutcome.BLOCKED else "",
        degraded_reasons=["admitted_degraded"] if outcome == AdmissionOutcome.ADMITTED_DEGRADED else [],
        evidence=admission_decision.evidence,
    )
    return gate_result, admission_decision


def _evaluate_operational_readiness_gate(
    *,
    main_chain_available: bool,
    degraded: bool,
    recovery_active: bool,
    runtime_verdict: str,
    admission_passed: bool,
) -> LifecycleGateResult:
    """Operational readiness gate: system meets minimum access standard."""
    if not admission_passed:
        return LifecycleGateResult(
            stage=LifecycleStage.OPERATIONAL_READINESS,
            passed=False,
            blocked=True,
            blocked_reason="Operational readiness blocked: admission gate has not passed.",
            evidence={"admission_passed": admission_passed},
        )
    degraded_reasons: List[str] = []
    if degraded:
        degraded_reasons.append("degraded_runtime_or_capabilities")
    if recovery_active:
        degraded_reasons.append("recovery_active")
    if runtime_verdict not in ("ready", "ok", "canonical", ""):
        if runtime_verdict != "blocked":
            degraded_reasons.append(f"runtime_verdict={runtime_verdict}")
    return LifecycleGateResult(
        stage=LifecycleStage.OPERATIONAL_READINESS,
        passed=main_chain_available,
        blocked=not main_chain_available,
        degraded=bool(degraded_reasons),
        blocked_reason="Main chain is not available." if not main_chain_available else "",
        degraded_reasons=degraded_reasons,
        evidence={
            "main_chain_available": main_chain_available,
            "degraded": degraded,
            "recovery_active": recovery_active,
            "runtime_verdict": runtime_verdict,
        },
    )


def _evaluate_task_initiation_gate(
    *,
    admission_decision: AdmissionDecision,
    capability_visible: bool,
    active_session_count: int,
    main_chain_available: bool,
    degraded: bool,
    android_attached: bool,
    task_initiated: bool,
) -> tuple[LifecycleGateResult, TaskInitiationGateResult]:
    """Task initiation gate: hard multi-gate check before dispatch is permitted."""
    # Sub-gate evaluations (all run regardless of prior failures).
    admission_gate_met = admission_decision.is_admitted
    capability_gate_met = capability_visible or not android_attached
    session_gate_met = active_session_count > 0 or not android_attached
    readiness_gate_met = main_chain_available

    blocking_gates: List[str] = []
    if not admission_gate_met:
        blocking_gates.append("admission")
    if not capability_gate_met:
        blocking_gates.append("capability")
    if not session_gate_met:
        blocking_gates.append("session")
    if not readiness_gate_met:
        blocking_gates.append("readiness")

    gate_passed = not blocking_gates
    gate_degraded = degraded and gate_passed

    gate_result_obj = TaskInitiationGateResult(
        gate_passed=gate_passed,
        admission_gate_met=admission_gate_met,
        capability_gate_met=capability_gate_met,
        session_gate_met=session_gate_met,
        readiness_gate_met=readiness_gate_met,
        blocking_gates=blocking_gates,
        eligible=gate_passed,
        degraded=gate_degraded,
        evidence={
            "active_session_count": active_session_count,
            "capability_visible": capability_visible,
            "main_chain_available": main_chain_available,
            "task_initiated": task_initiated,
            "admission_outcome": admission_decision.outcome.value,
        },
    )

    stage_gate = LifecycleGateResult(
        stage=LifecycleStage.TASK_INITIATION,
        passed=gate_passed,
        blocked=not gate_passed,
        degraded=gate_degraded,
        blocked_reason=(
            f"Task initiation blocked: gates not met: {blocking_gates}."
            if blocking_gates
            else ""
        ),
        degraded_reasons=["degraded_initiation"] if gate_degraded else [],
        evidence=gate_result_obj.evidence,
    )
    return stage_gate, gate_result_obj


def _evaluate_task_execution_gate(
    *,
    task_initiated: bool,
    task_initiation_gate_passed: bool,
    result_closure_established: bool,
) -> LifecycleGateResult:
    """Task execution gate: a task is actively executing."""
    active = task_initiated and not result_closure_established
    blocked = not task_initiation_gate_passed and not task_initiated
    return LifecycleGateResult(
        stage=LifecycleStage.TASK_EXECUTION,
        passed=task_initiated or result_closure_established,
        blocked=blocked,
        degraded=False,
        blocked_reason=(
            "Task execution blocked: task initiation gate has not passed."
            if blocked
            else ""
        ),
        evidence={
            "task_initiated": task_initiated,
            "result_closure_established": result_closure_established,
            "actively_executing": active,
        },
    )


def _evaluate_result_closure(
    *,
    task_initiated: bool,
    result_closure_established: bool,
    completion_notified: bool,
    participant_terminal_count: int,
    participant_terminal_success_count: int,
    task_initiated_gate_passed: bool,
    task_initiation_blocking_gates: List[str],
    recovery_active: bool,
    degraded: bool,
    android_attached: bool,
    result_ingress_evidence: Dict[str, Any],
) -> tuple[LifecycleGateResult, ResultClosureState]:
    """Result closure gate and state determination."""
    # Determine the ClosureOutcome.
    failed_explicitly = bool(result_ingress_evidence.get("explicit_failure", False))
    is_fully_closed = bool(result_ingress_evidence.get("is_fully_closed", False))
    completion_ingress_confirmed = bool(result_ingress_evidence.get("completion_ingress_confirmed", False))

    degraded_reasons: List[str] = []

    if not android_attached and not task_initiated:
        outcome = ClosureOutcome.NOT_APPLICABLE
    elif failed_explicitly:
        outcome = ClosureOutcome.FAILED
        degraded_reasons.append("explicit_failure")
    elif result_closure_established or is_fully_closed:
        if completion_ingress_confirmed or completion_notified:
            authoritative_closure = True
        else:
            authoritative_closure = False
            degraded_reasons.append("completion_ingress_not_confirmed")
        if recovery_active:
            outcome = ClosureOutcome.SUCCESS_RECOVERY
            degraded_reasons.append("recovery_path")
        elif degraded:
            outcome = ClosureOutcome.SUCCESS_DEGRADED
            degraded_reasons.append("degraded_path")
        else:
            outcome = ClosureOutcome.SUCCESS_CANONICAL
    elif task_initiated:
        if not task_initiated_gate_passed:
            outcome = ClosureOutcome.INCOMPLETE_BLOCKED
            degraded_reasons.append("task_initiation_gate_blocked")
        elif participant_terminal_count > 0 and not result_closure_established:
            outcome = ClosureOutcome.INCOMPLETE_WAITING
            degraded_reasons.append("result_uplink_not_yet_received")
        else:
            outcome = ClosureOutcome.INCOMPLETE_IN_PROGRESS
    else:
        outcome = ClosureOutcome.INCOMPLETE_WAITING
        degraded_reasons.append("awaiting_task_initiation")

    authoritative_closure = outcome in (
        ClosureOutcome.SUCCESS_CANONICAL,
        ClosureOutcome.SUCCESS_DEGRADED,
        ClosureOutcome.SUCCESS_RECOVERY,
    ) and (completion_ingress_confirmed or completion_notified)

    session_closed = participant_terminal_count > 0
    task_closed = result_closure_established or is_fully_closed

    closure_state = ResultClosureState(
        outcome=outcome,
        authoritative=authoritative_closure,
        session_closed=session_closed,
        task_closed=task_closed,
        completion_notified=completion_notified or completion_ingress_confirmed,
        degraded_reasons=degraded_reasons,
        evidence={
            "task_initiated": task_initiated,
            "result_closure_established": result_closure_established,
            "is_fully_closed": is_fully_closed,
            "completion_ingress_confirmed": completion_ingress_confirmed,
            "participant_terminal_count": participant_terminal_count,
            "participant_terminal_success_count": participant_terminal_success_count,
            "recovery_active": recovery_active,
            "failed_explicitly": failed_explicitly,
        },
    )

    closure_passed = outcome in (
        ClosureOutcome.SUCCESS_CANONICAL,
        ClosureOutcome.SUCCESS_DEGRADED,
        ClosureOutcome.SUCCESS_RECOVERY,
    )
    stage_gate = LifecycleGateResult(
        stage=LifecycleStage.RESULT_CLOSURE,
        passed=closure_passed,
        blocked=outcome == ClosureOutcome.INCOMPLETE_BLOCKED,
        degraded=bool(degraded_reasons) and closure_passed,
        blocked_reason=(
            f"Closure blocked: task initiation gate blocked before execution could complete "
            f"(blocking gates: {task_initiation_blocking_gates})."
            if outcome == ClosureOutcome.INCOMPLETE_BLOCKED
            else ""
        ),
        degraded_reasons=degraded_reasons if closure_passed else [],
        evidence=closure_state.evidence,
    )
    return stage_gate, closure_state


# ---------------------------------------------------------------------------
# Public builder
# ---------------------------------------------------------------------------


def build_executable_lifecycle_state(
    *,
    validation: Any,
    kind_states: Sequence[Any] = (),
    route_paths: Optional[Iterable[str]] = None,
    runtime_readiness: Optional[Dict[str, Any]] = None,
    device_evidence: Optional[Dict[str, Any]] = None,
    android_evidence: Optional[Dict[str, Any]] = None,
    session_evidence: Optional[Dict[str, Any]] = None,
    system_acceptance: Optional[Dict[str, Any]] = None,
    result_ingress_evidence: Optional[Dict[str, Any]] = None,
) -> ExecutableLifecycleState:
    """Build the hardened :class:`ExecutableLifecycleState` from V2 evidence.

    Parameters
    ----------
    validation
        :class:`~core.operational_registration_path.OnboardingValidation`
        result.  Uses ``.overall_status`` (``PASS`` / ``WARN`` / ``FAIL``).
    kind_states
        Sequence of registration kind state objects (used to detect blocked
        / degraded main-chain items).
    route_paths
        Iterable of API route paths currently registered on the server.
    runtime_readiness
        Dict with a ``"verdict"`` key from the runtime-readiness matrix.
    device_evidence
        Dict with device admission / cross-device readiness evidence.
    android_evidence
        Dict with Android capability / snapshot evidence.
    session_evidence
        Dict with session / participant continuity evidence.
    system_acceptance
        Dict with the overall system acceptance verdict.
    result_ingress_evidence
        Dict with result ingress and completion ingress evidence.

    Returns
    -------
    ExecutableLifecycleState
        The complete hardened lifecycle state.
    """
    route_paths_set = frozenset(route_paths or [])
    runtime_readiness = dict(runtime_readiness or {})
    device_evidence = dict(device_evidence or {})
    android_evidence = dict(android_evidence or {})
    session_evidence = dict(session_evidence or {})
    result_ingress_evidence = dict(result_ingress_evidence or {})

    validation_status = _str(getattr(validation, "overall_status", "PASS"))

    # --- Derived signals (mirrors v2_unified_state_contract logic) ---
    _REQUIRED_ROUTES: frozenset = frozenset({
        "/api/v1/health",
        "/api/v1/chat",
        "/api/v1/projection/runtime",
        "/api/v1/projection/operational-readiness",
        "/api/v1/projection/clone-to-use-acceptance",
    })
    api_missing = sorted(r for r in _REQUIRED_ROUTES if r not in route_paths_set)

    def _status_val(item: Any) -> str:
        return _str(getattr(item, "status", ""))

    # Single pass over kind_states to avoid iterating twice.
    main_chain_blocked = False
    registration_degraded = False
    for _ks in kind_states:
        _sv = _status_val(_ks)
        if _sv == "blocked":
            main_chain_blocked = True
        if _sv == "degraded":
            registration_degraded = True
        if main_chain_blocked and registration_degraded:
            break

    android_attached = (
        device_evidence.get("android_device_count", 0) > 0
        or android_evidence.get("snapshot_count", 0) > 0
        or session_evidence.get("participant_total_count", 0) > 0
    )
    capability_visible = android_evidence.get("capability_visible_count", 0) > 0
    capability_degraded = android_evidence.get("degraded_capability_device_count", 0) > 0
    runtime_verdict = str(runtime_readiness.get("verdict", "unknown"))
    main_chain_available = (
        validation_status != "FAIL"
        and not main_chain_blocked
        and runtime_verdict != "blocked"
        and not api_missing
    )
    recovery_active = bool(session_evidence.get("recovery_active"))
    degraded = (
        validation_status == "WARN"
        or runtime_verdict in {"degraded", "unknown"}
        or capability_degraded
        or registration_degraded
    )
    active_session_count = int(session_evidence.get("active_session_count", 0))
    task_initiated = bool(session_evidence.get("task_initiated", False))
    result_closure_established = bool(session_evidence.get("result_closure_established", False))
    participant_terminal_count = int(session_evidence.get("participant_terminal_count", 0))
    participant_terminal_success_count = int(session_evidence.get("participant_terminal_success_count", 0))
    completion_notified = bool(session_evidence.get("completion_notified", False))

    # --- Stage gate evaluations ---
    reg_gate = _evaluate_registration_gate(
        validation_status=validation_status,
        main_chain_blocked=main_chain_blocked,
        android_device_count=device_evidence.get("android_device_count", 0),
        route_paths_set=route_paths_set,
        required_routes=_REQUIRED_ROUTES,
    )

    cap_gate = _evaluate_capability_visibility_gate(
        android_attached=android_attached,
        capability_visible=capability_visible,
        capability_degraded=capability_degraded,
        registration_passed=reg_gate.passed,
    )

    adm_gate, admission_decision = _evaluate_admission_gate(
        main_chain_available=main_chain_available,
        runtime_verdict=runtime_verdict,
        android_attached=android_attached,
        capability_visible=capability_visible,
        device_evidence=device_evidence,
        degraded=degraded,
        capability_gate_passed=cap_gate.passed,
        registration_gate_passed=reg_gate.passed,
    )

    ops_gate = _evaluate_operational_readiness_gate(
        main_chain_available=main_chain_available,
        degraded=degraded,
        recovery_active=recovery_active,
        runtime_verdict=runtime_verdict,
        admission_passed=adm_gate.passed,
    )

    task_init_gate, task_init_gate_obj = _evaluate_task_initiation_gate(
        admission_decision=admission_decision,
        capability_visible=capability_visible,
        active_session_count=active_session_count,
        main_chain_available=main_chain_available,
        degraded=degraded,
        android_attached=android_attached,
        task_initiated=task_initiated,
    )

    exec_gate = _evaluate_task_execution_gate(
        task_initiated=task_initiated,
        task_initiation_gate_passed=task_init_gate.passed,
        result_closure_established=result_closure_established,
    )

    closure_gate, closure_state = _evaluate_result_closure(
        task_initiated=task_initiated,
        result_closure_established=result_closure_established,
        completion_notified=completion_notified,
        participant_terminal_count=participant_terminal_count,
        participant_terminal_success_count=participant_terminal_success_count,
        task_initiated_gate_passed=task_init_gate.passed,
        task_initiation_blocking_gates=task_init_gate_obj.blocking_gates,
        recovery_active=recovery_active,
        degraded=degraded,
        android_attached=android_attached,
        result_ingress_evidence=result_ingress_evidence,
    )

    # --- Assemble stage_gates map ---
    stage_gates: Dict[str, LifecycleGateResult] = {
        LifecycleStage.REGISTRATION.value: reg_gate,
        LifecycleStage.CAPABILITY_VISIBILITY.value: cap_gate,
        LifecycleStage.ADMISSION.value: adm_gate,
        LifecycleStage.OPERATIONAL_READINESS.value: ops_gate,
        LifecycleStage.TASK_INITIATION.value: task_init_gate,
        LifecycleStage.TASK_EXECUTION.value: exec_gate,
        LifecycleStage.RESULT_CLOSURE.value: closure_gate,
    }

    # --- Determine current stage (highest stage whose gate passed) ---
    _stage_order = [
        LifecycleStage.REGISTRATION,
        LifecycleStage.CAPABILITY_VISIBILITY,
        LifecycleStage.ADMISSION,
        LifecycleStage.OPERATIONAL_READINESS,
        LifecycleStage.TASK_INITIATION,
        LifecycleStage.TASK_EXECUTION,
        LifecycleStage.RESULT_CLOSURE,
    ]
    current_stage = LifecycleStage.REGISTRATION
    for stage in _stage_order:
        if stage_gates[stage.value].passed:
            current_stage = stage
        else:
            break

    # --- Lifecycle blocking ---
    first_blocking_gate: Optional[LifecycleGateResult] = None
    for stage in _stage_order:
        gate = stage_gates[stage.value]
        if gate.blocked:
            first_blocking_gate = gate
            break
    lifecycle_blocked = first_blocking_gate is not None
    lifecycle_blocked_reason = (
        f"Stage {first_blocking_gate.stage.value}: {first_blocking_gate.blocked_reason}"
        if first_blocking_gate
        else ""
    )

    # --- Degraded stages ---
    degraded_stages: List[str] = [
        stage.value
        for stage in _stage_order
        if stage_gates[stage.value].degraded
    ]

    return ExecutableLifecycleState(
        authority=EXECUTABLE_LIFECYCLE_HARDENING_AUTHORITY,
        contract_version=EXECUTABLE_LIFECYCLE_HARDENING_VERSION,
        stage_gates=stage_gates,
        admission_decision=admission_decision,
        task_initiation_gate=task_init_gate_obj,
        result_closure=closure_state,
        current_stage=current_stage,
        lifecycle_blocked=lifecycle_blocked,
        lifecycle_blocked_reason=lifecycle_blocked_reason,
        degraded_stages=degraded_stages,
        recovery_transition=recovery_active,
    )
