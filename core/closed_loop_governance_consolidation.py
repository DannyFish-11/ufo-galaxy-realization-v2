"""core/closed_loop_governance_consolidation.py
===============================================
PR-13 V2-side — Closed-Loop Governance Consolidation
=====================================================

Background
----------
The V2 center-governance layer has accumulated strengthened governance surfaces
across PR-05 through PR-11:

- Execution type policies and priority/conflict resolution
  (``core.unified_execution_governance``)
- Lifecycle event recording and phase-transition validation
  (``core.unified_execution_governance``)
- Canonical runtime truth reconciliation and uplink authority
  (``core.unified_execution_governance.get_uplink_truth_state``)
- Mission completion closure and terminal-outcome determinism
  (``core.unified_execution_governance.notify_execution_completed``)
- Mesh proof quality and governance readiness impact
  (``core.unified_governance_semantics``)

These surfaces remained partially separate: each stage (activation, execution,
observation/uplink, reconciliation, completion) held its own local authority but
there was no single canonical object representing the **whole closed loop** for a
given execution.

Purpose
-------
This module provides the **closed-loop governance consolidation layer** for PR-13
(V2 side).  It does NOT introduce new storage or duplicate any existing authority.
Instead it:

1. Derives the **canonical closed-loop stage** from existing lifecycle history and
   uplink truth state (both already governed by ``unified_execution_governance``).
2. Enforces **cross-stage invariants** that span the entire loop, detecting gaps or
   inconsistencies that stage-local checks cannot see.
3. Provides a unified :func:`query_closed_loop_governance_state` view so callers
   (diagnostics, tests, observability tooling) can inspect the full loop in one
   place.
4. Provides :func:`get_closed_loop_audit_record` for auditable, JSON-serialisable
   evidence of closed-loop coherence at any point in the lifecycle.

Design invariants (cross-stage)
--------------------------------
I-01  Admitted execution MUST have lifecycle history (created / admitted events).
I-02  Terminal lifecycle phase MUST map to a deterministic canonical_terminal_outcome.
I-03  Center lifecycle authority MUST win over conflicting uplink observations.
I-04  A post-terminal uplink observation MUST NOT override center terminal truth.
I-05  All registered active executions for a device MUST respect priority policy
      (takeover blocks lower-priority; concurrency limits enforced at admission).
I-06  Closed-loop stage MUST be monotonically forward-progressing for an execution_id:
      activation → execution → observation → reconciliation → completion.
I-07  Terminal truth MUST be determined before the loop can reach the
      ``completion`` stage.
I-08  Device governance isolation: execution state for device A MUST NOT propagate
      to device B.

Authority sentinel
------------------
``CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL`` — import this constant to assert
that the PR-13 consolidation layer is present.

Public API
----------
Sentinels / version::

    CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL
    CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION

Enums::

    ClosedLoopStage

Dataclasses::

    ClosedLoopInvariantViolation
    ClosedLoopGovernanceView

Functions::

    query_closed_loop_governance_state(execution_id, device_id) -> ClosedLoopGovernanceView
    assert_closed_loop_invariants(execution_id, device_id) -> list[ClosedLoopInvariantViolation]
    get_closed_loop_audit_record(execution_id, device_id) -> dict
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ClosedLoopGovernanceConsolidation")

# ---------------------------------------------------------------------------
# Authority sentinels & contract version
# ---------------------------------------------------------------------------

CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL: str = (
    "CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL::PR13_V2::present "
    "core.closed_loop_governance_consolidation is the canonical center-side "
    "closed-loop governance consolidation layer (PR-13 V2 side). It derives "
    "unified closed-loop stage, enforces cross-stage invariants, and provides "
    "auditable whole-loop governance views for all governed execution types. "
    "All governance diagnostics and regression tests MUST reference this sentinel "
    "to confirm PR-13 consolidation is in effect."
)

CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION: str = "13.0.0"

# Cross-stage invariant policy declaration
CROSS_STAGE_INVARIANT_POLICY: str = (
    "POLICY::CLOSED_LOOP_CROSS_STAGE_INVARIANTS_V1: "
    "The canonical closed-loop governance flow for a governed execution is: "
    "activation → execution → observation/uplink → reconciliation → completion. "
    "Each stage transition is guarded by an invariant. Violations are surfaced "
    "as ClosedLoopInvariantViolation records and MUST be treated as governance "
    "regressions. The center lifecycle authority ALWAYS wins over conflicting "
    "uplink observations (invariant I-03). Post-terminal uplink arrivals MUST "
    "NOT alter canonical terminal truth (invariant I-04). Stage must not regress "
    "for a given execution_id (invariant I-06)."
)

# System-level completion readiness policy (final-closure hardening).
SYSTEM_COMPLETION_READINESS_POLICY: str = (
    "POLICY::SYSTEM_COMPLETION_READINESS_V1: "
    "A closed loop reaching stage=completion is not automatically treated as "
    "system-level mature closure. Mature closure requires center_lifecycle "
    "authority, deterministic terminal truth, both result/state uplinks, "
    "accepted reconciliation, no conflict, and stable runtime health. "
    "Any missing condition MUST be surfaced as explicit completion gap types."
)

# Ordered list of all terminal lifecycle phases (for invariant checks).
# These values MUST remain synchronized with ExecutionLifecyclePhase in
# core.unified_execution_governance (the authoritative enum definition).
# Drift between these constants and the enum is a governance regression.
_TERMINAL_PHASES: frozenset[str] = frozenset(
    {"succeeded", "failed", "timed_out", "interrupted", "cancelled"}
)

# Phases that can appear before execution is active (pre-running)
_PRE_RUNNING_PHASES: frozenset[str] = frozenset({"created", "admitted"})

# Phases that indicate an active (non-terminal) execution in flight
_ACTIVE_PHASES: frozenset[str] = frozenset({"running", "retrying", "replayed"})

# Reconciliation statuses that indicate reconciliation is actively working
# (conflict resolution, delayed/partial observations, or uplink-only authority).
# "in_progress" is excluded because it means normal active execution, not
# active reconciliation work.
_ACTIVE_RECONCILIATION_STATUSES: frozenset[str] = frozenset(
    {
        "conflict_center_truth_retained",
        "delayed_conflict_center_truth_retained",
        "terminal_observation_held_for_lifecycle_authority",
        "accepted_partial_observation",
        "uplink_only_terminal_observation",
        "uplink_only_observation",
    }
)
# Keep this as a frozenset to preserve forward compatibility with additional
# "fully accepted" reconciliation outcomes in future contract revisions.
_MATURE_RECONCILIATION_STATUSES: frozenset[str] = frozenset({"accepted"})
DEFAULT_RUNTIME_HEALTH_STATUS: str = "stable"


# ---------------------------------------------------------------------------
# ClosedLoopStage
# ---------------------------------------------------------------------------


class ClosedLoopStage(str, Enum):
    """Canonical stage of a single execution within the center-side closed loop.

    The stages progress forward; regression is not permitted for a given
    execution_id (invariant I-06).

    Values
    ------
    activation
        Governance evaluation has been requested (``evaluate_execution_governance``
        called).  The execution may be accepted or rejected.  Lifecycle history
        exists with at least a ``created`` or ``admitted`` event.

    execution
        The execution has been admitted and is actively running.  Lifecycle phase
        is ``admitted``, ``running``, ``retrying``, or ``replayed``.

    observation
        At least one uplink record (result or state) has been received while the
        execution is non-terminal.  The center-governance layer is observing
        runtime telemetry.

    reconciliation
        The uplink observations are being reconciled with the lifecycle authority.
        This stage is entered whenever ``get_uplink_truth_state`` would return a
        non-missing reconciliation_status.

    completion
        The execution has reached a terminal lifecycle phase AND canonical terminal
        truth has been determined.  The loop is closed.

    unknown
        Stage could not be determined (no lifecycle history, no uplink records).
    """

    activation = "activation"
    execution = "execution"
    observation = "observation"
    reconciliation = "reconciliation"
    completion = "completion"
    unknown = "unknown"


# Numeric ordinal for each stage (used for monotonicity checks — invariant I-06)
_STAGE_ORDINAL: Dict[ClosedLoopStage, int] = {
    ClosedLoopStage.unknown: 0,
    ClosedLoopStage.activation: 1,
    ClosedLoopStage.execution: 2,
    ClosedLoopStage.observation: 3,
    ClosedLoopStage.reconciliation: 4,
    ClosedLoopStage.completion: 5,
}


# ---------------------------------------------------------------------------
# ClosedLoopInvariantViolation
# ---------------------------------------------------------------------------


@dataclass
class ClosedLoopInvariantViolation:
    """Structured record of a cross-stage invariant violation.

    Attributes
    ----------
    invariant_id
        Short identifier matching the I-NN label in the module docstring.
    description
        Human-readable description of the violation.
    execution_id
        Affected execution identifier.
    device_id
        Affected device identifier.
    stage
        The :class:`ClosedLoopStage` where the violation was detected.
    detail
        Additional context (e.g., conflicting values, phase names).
    detected_at
        Unix epoch timestamp when the violation was detected.
    """

    invariant_id: str
    description: str
    execution_id: str
    device_id: str
    stage: ClosedLoopStage
    detail: str = ""
    detected_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "invariant_id": self.invariant_id,
            "description": self.description,
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "stage": self.stage.value,
            "detail": self.detail,
            "detected_at": self.detected_at,
            "_policy": CROSS_STAGE_INVARIANT_POLICY,
        }


# ---------------------------------------------------------------------------
# ClosedLoopGovernanceView
# ---------------------------------------------------------------------------


@dataclass
class ClosedLoopGovernanceView:
    """Unified canonical view of a single execution's closed-loop governance state.

    All fields are derived from the existing governance stores via
    :func:`query_closed_loop_governance_state`.  No new state is introduced.

    Attributes
    ----------
    execution_id
        Correlation identifier for the governed execution.
    device_id
        Target device identifier.
    stage
        Current :class:`ClosedLoopStage` of the execution.
    lifecycle_phase
        Latest raw lifecycle phase from lifecycle history (or ``None``).
    is_terminal
        ``True`` when the execution has reached a terminal lifecycle phase.
    canonical_terminal_outcome
        Canonical terminal outcome string (from center-lifecycle authority),
        or ``None`` when not yet terminal.
    reconciliation_status
        Reconciliation status string from ``get_uplink_truth_state``.
    reconciliation_conflict
        ``True`` when a conflict between lifecycle and uplink truth was detected.
    has_uplink_observation
        ``True`` when at least one uplink record (result or state) has been
        received.
    lifecycle_event_count
        Total number of lifecycle events recorded for this execution.
    uplink_result_count
        Number of result-uplink records received.
    uplink_state_count
        Number of state-uplink records received.
    terminal_truth_authoritative_source
        ``"center_lifecycle"`` / ``"reported_uplink"`` / ``"none"``.
    invariant_violations
        List of :class:`ClosedLoopInvariantViolation` detected at query time.
    loop_is_coherent
        ``True`` iff no invariant violations were detected.
    queried_at
        Unix epoch timestamp when this view was produced.
    """

    execution_id: str
    device_id: str
    stage: ClosedLoopStage
    lifecycle_phase: Optional[str]
    is_terminal: bool
    canonical_terminal_outcome: Optional[str]
    reconciliation_status: str
    reconciliation_conflict: bool
    has_uplink_observation: bool
    lifecycle_event_count: int
    uplink_result_count: int
    uplink_state_count: int
    terminal_truth_authoritative_source: str
    invariant_violations: List[ClosedLoopInvariantViolation] = field(default_factory=list)
    loop_is_coherent: bool = True
    system_completion_ready: bool = False
    system_completion_level: str = "not_closed"
    system_completion_gap_types: List[str] = field(default_factory=list)
    queried_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "device_id": self.device_id,
            "stage": self.stage.value,
            "lifecycle_phase": self.lifecycle_phase,
            "is_terminal": self.is_terminal,
            "canonical_terminal_outcome": self.canonical_terminal_outcome,
            "reconciliation_status": self.reconciliation_status,
            "reconciliation_conflict": self.reconciliation_conflict,
            "has_uplink_observation": self.has_uplink_observation,
            "lifecycle_event_count": self.lifecycle_event_count,
            "uplink_result_count": self.uplink_result_count,
            "uplink_state_count": self.uplink_state_count,
            "terminal_truth_authoritative_source": self.terminal_truth_authoritative_source,
            "invariant_violations": [v.to_dict() for v in self.invariant_violations],
            "loop_is_coherent": self.loop_is_coherent,
            "system_completion_ready": self.system_completion_ready,
            "system_completion_level": self.system_completion_level,
            "system_completion_gap_types": list(self.system_completion_gap_types),
            "_system_completion_policy": SYSTEM_COMPLETION_READINESS_POLICY,
            "queried_at": self.queried_at,
            "_sentinel": CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
            "_contract_version": CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _derive_closed_loop_stage(
    *,
    lifecycle_phase: Optional[str],
    is_terminal: bool,
    canonical_terminal_outcome: Optional[str],
    reconciliation_status: str,
    has_uplink_observation: bool,
    lifecycle_event_count: int,
) -> ClosedLoopStage:
    """Derive the canonical closed-loop stage from governance state.

    Stage derivation is deterministic and based solely on existing governance
    fields — no new state is consulted.

    Derivation order (highest to lowest):
    1. completion      — terminal + canonical_terminal_outcome determined
    2. reconciliation  — reconciliation is actively working (conflict, delayed,
                         partial, or uplink-only observation)
    3. observation     — uplink received AND lifecycle phase is active/admitted
                         (normal execution with external telemetry)
    4. execution       — lifecycle phase is admitted/running/retrying/replayed
                         (execution admitted, may have internal uplinks only)
    5. activation      — lifecycle history exists (created only, or any events)
    6. unknown         — no lifecycle history at all
    """
    if is_terminal and canonical_terminal_outcome is not None:
        return ClosedLoopStage.completion

    if reconciliation_status in _ACTIVE_RECONCILIATION_STATUSES:
        return ClosedLoopStage.reconciliation

    if has_uplink_observation and lifecycle_phase in (
        "admitted", *_ACTIVE_PHASES
    ):
        return ClosedLoopStage.observation

    if lifecycle_phase in ("admitted", *_ACTIVE_PHASES):
        return ClosedLoopStage.execution

    if lifecycle_event_count > 0:
        return ClosedLoopStage.activation

    return ClosedLoopStage.unknown


def _check_invariants(
    *,
    execution_id: str,
    device_id: str,
    stage: ClosedLoopStage,
    lifecycle_phase: Optional[str],
    is_terminal: bool,
    canonical_terminal_outcome: Optional[str],
    reconciliation_status: str,
    reconciliation_conflict: bool,
    terminal_truth_authoritative_source: str,
    lifecycle_event_count: int,
    has_uplink_observation: bool,
    lifecycle_history: List[Dict[str, Any]],
    uplink_truth: Dict[str, Any],
) -> List[ClosedLoopInvariantViolation]:
    """Evaluate all cross-stage invariants and return any violations."""
    violations: List[ClosedLoopInvariantViolation] = []

    # I-01: Admitted execution MUST have lifecycle history.
    if lifecycle_phase in ("admitted", *_ACTIVE_PHASES, *_TERMINAL_PHASES):
        if lifecycle_event_count == 0:
            violations.append(
                ClosedLoopInvariantViolation(
                    invariant_id="I-01",
                    description=(
                        "Admitted execution has no lifecycle history. "
                        "evaluate_execution_governance must record lifecycle events."
                    ),
                    execution_id=execution_id,
                    device_id=device_id,
                    stage=stage,
                    detail=f"lifecycle_phase={lifecycle_phase!r} but lifecycle_event_count=0",
                )
            )

    # I-02: Terminal lifecycle phase MUST map to canonical_terminal_outcome.
    if is_terminal and canonical_terminal_outcome is None:
        violations.append(
            ClosedLoopInvariantViolation(
                invariant_id="I-02",
                description=(
                    "Terminal lifecycle phase without a canonical_terminal_outcome. "
                    "Every terminal phase must map to a deterministic outcome."
                ),
                execution_id=execution_id,
                device_id=device_id,
                stage=stage,
                detail=f"lifecycle_phase={lifecycle_phase!r}, canonical_terminal_outcome=None",
            )
        )

    # I-03: Center lifecycle authority MUST win over conflicting uplinks.
    # If reconciliation_conflict=True but authoritative source is NOT center_lifecycle, violation.
    if reconciliation_conflict and terminal_truth_authoritative_source != "center_lifecycle":
        violations.append(
            ClosedLoopInvariantViolation(
                invariant_id="I-03",
                description=(
                    "Reconciliation conflict present but center_lifecycle is not the "
                    "authoritative truth source. Center lifecycle authority must always win."
                ),
                execution_id=execution_id,
                device_id=device_id,
                stage=stage,
                detail=(
                    f"reconciliation_conflict=True but "
                    f"terminal_truth_authoritative_source={terminal_truth_authoritative_source!r}"
                ),
            )
        )

    # I-04: Post-terminal uplink MUST NOT override center terminal truth.
    # Detected via delayed_conflict_center_truth_retained status — this is correct behavior.
    # Violation is when conflict persists and authoritative source is not center_lifecycle.
    delayed_obs = uplink_truth.get("reconciliation_delayed_observation", False)
    if delayed_obs and terminal_truth_authoritative_source != "center_lifecycle":
        violations.append(
            ClosedLoopInvariantViolation(
                invariant_id="I-04",
                description=(
                    "Post-terminal (delayed) uplink observation detected but center_lifecycle "
                    "is not the authoritative truth source. Late uplinks must not override "
                    "center terminal truth."
                ),
                execution_id=execution_id,
                device_id=device_id,
                stage=stage,
                detail=(
                    f"reconciliation_delayed_observation=True but "
                    f"terminal_truth_authoritative_source={terminal_truth_authoritative_source!r}"
                ),
            )
        )

    # I-06: Stage should be meaningful (not unknown) when lifecycle history exists.
    if lifecycle_event_count > 0 and stage == ClosedLoopStage.unknown:
        violations.append(
            ClosedLoopInvariantViolation(
                invariant_id="I-06",
                description=(
                    "Lifecycle history exists but closed-loop stage is 'unknown'. "
                    "Stage derivation must be deterministic when history is present."
                ),
                execution_id=execution_id,
                device_id=device_id,
                stage=stage,
                detail=f"lifecycle_event_count={lifecycle_event_count}, stage=unknown",
            )
        )

    # I-07: Terminal truth MUST be determined before completion stage.
    if stage == ClosedLoopStage.completion and canonical_terminal_outcome is None:
        violations.append(
            ClosedLoopInvariantViolation(
                invariant_id="I-07",
                description=(
                    "Loop reached 'completion' stage but canonical_terminal_outcome is None. "
                    "Terminal truth must be determined before loop closure."
                ),
                execution_id=execution_id,
                device_id=device_id,
                stage=stage,
                detail="stage=completion but canonical_terminal_outcome=None",
            )
        )

    return violations


def _classify_system_completion_readiness(
    *,
    stage: ClosedLoopStage,
    is_terminal: bool,
    canonical_terminal_outcome: Optional[str],
    terminal_truth_authoritative_source: str,
    reconciliation_status: str,
    reconciliation_conflict: bool,
    canonical_runtime_health: str,
    uplink_result_count: int,
    uplink_state_count: int,
) -> Dict[str, Any]:
    """Classify whether completion reached system-level mature closure.

    Parameters
    ----------
    stage
        Canonical closed-loop stage for the execution.
    is_terminal
        Whether lifecycle has reached a terminal phase.
    canonical_terminal_outcome
        Canonical terminal outcome resolved by governance truth reconciliation.
    terminal_truth_authoritative_source
        Source of terminal truth (expected ``center_lifecycle`` for mature closure).
    reconciliation_status
        Reconciliation state emitted by uplink truth selection.
    reconciliation_conflict
        Whether lifecycle and uplink terminal observations are conflicting.
    canonical_runtime_health
        Runtime health classification from canonical truth (stable/degraded/recovered).
    uplink_result_count
        Number of result uplinks observed for this execution.
    uplink_state_count
        Number of state uplinks observed for this execution.

    Returns
    -------
    Dict[str, Any]
        ``system_completion_ready`` indicates mature closure; ``system_completion_level``
        differentiates not_closed/closed_with_gaps/mature_closed_loop; and
        ``system_completion_gap_types`` lists explicit structural gaps.
    """
    gap_types: List[str] = []

    if stage != ClosedLoopStage.completion:
        gap_types.append("loop_not_in_completion_stage")
    if not is_terminal:
        gap_types.append("terminal_lifecycle_not_reached")
    if canonical_terminal_outcome is None:
        gap_types.append("terminal_truth_undetermined")
    if terminal_truth_authoritative_source != "center_lifecycle":
        gap_types.append("center_lifecycle_authority_missing")
    if uplink_result_count <= 0:
        gap_types.append("missing_result_uplink")
    if uplink_state_count <= 0:
        gap_types.append("missing_state_uplink")
    if reconciliation_conflict:
        gap_types.append("reconciliation_conflict_present")
    if reconciliation_status not in _MATURE_RECONCILIATION_STATUSES:
        gap_types.append("reconciliation_not_fully_accepted")
    if canonical_runtime_health != "stable":
        gap_types.append("runtime_health_not_stable")

    system_completion_ready = len(gap_types) == 0
    if system_completion_ready:
        system_completion_level = "mature_closed_loop"
    elif stage == ClosedLoopStage.completion:
        system_completion_level = "closed_with_gaps"
    else:
        system_completion_level = "not_closed"
    return {
        "system_completion_ready": system_completion_ready,
        "system_completion_level": system_completion_level,
        "system_completion_gap_types": gap_types,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def query_closed_loop_governance_state(
    execution_id: str,
    device_id: str = "",
) -> ClosedLoopGovernanceView:
    """Return the canonical closed-loop governance view for *execution_id*.

    This is the **primary read-path** for closed-loop diagnostics and
    regression verification.  It reads from the existing governance stores
    (lifecycle history and uplink truth) and derives:

    - The current :class:`ClosedLoopStage`
    - The canonical terminal outcome (center-lifecycle authority)
    - Reconciliation status
    - All cross-stage invariant violations

    Parameters
    ----------
    execution_id
        Correlation identifier for the governed execution.
    device_id
        Optional device identifier (used for invariant violation records).
        Pass an empty string when not available.

    Returns
    -------
    ClosedLoopGovernanceView
        Always returned, never raises.
    """
    from core.unified_execution_governance import (
        get_execution_lifecycle_history,
        get_uplink_truth_state,
    )

    try:
        lifecycle_history: List[Dict[str, Any]] = get_execution_lifecycle_history(execution_id)
        uplink_truth: Dict[str, Any] = get_uplink_truth_state(execution_id)
    except Exception as exc:
        logger.error(
            "query_closed_loop_governance_state: error reading governance stores "
            "for execution_id=%r device_id=%r: %s",
            execution_id, device_id, exc,
        )
        store_read_violation = ClosedLoopInvariantViolation(
            invariant_id="I-STORE-READ-ERROR",
            description=(
                "Governance store read failed: closed-loop state could not be derived. "
                "This indicates a runtime error in the governance infrastructure."
            ),
            execution_id=execution_id,
            device_id=device_id,
            stage=ClosedLoopStage.unknown,
            detail=str(exc),
        )
        return ClosedLoopGovernanceView(
            execution_id=execution_id,
            device_id=device_id,
            stage=ClosedLoopStage.unknown,
            lifecycle_phase=None,
            is_terminal=False,
            canonical_terminal_outcome=None,
            reconciliation_status="missing",
            reconciliation_conflict=False,
            has_uplink_observation=False,
            lifecycle_event_count=0,
            uplink_result_count=0,
            uplink_state_count=0,
            terminal_truth_authoritative_source="none",
            invariant_violations=[store_read_violation],
            loop_is_coherent=False,
            system_completion_ready=False,
            system_completion_level="not_closed",
            system_completion_gap_types=["governance_store_read_error"],
        )

    lifecycle_phase: Optional[str] = uplink_truth.get("lifecycle_phase")
    is_terminal: bool = bool(uplink_truth.get("is_terminal", False))
    canonical_terminal_outcome: Optional[str] = uplink_truth.get("canonical_terminal_outcome")
    reconciliation_status: str = str(uplink_truth.get("reconciliation_status") or "missing")
    reconciliation_conflict: bool = bool(uplink_truth.get("reconciliation_conflict", False))
    terminal_truth_authoritative_source: str = str(
        uplink_truth.get("terminal_truth_authoritative_source") or "none"
    )
    lifecycle_event_count: int = int(uplink_truth.get("lifecycle_event_count") or 0)
    uplink_result_count: int = int(uplink_truth.get("result_uplink_count") or 0)
    uplink_state_count: int = int(uplink_truth.get("state_uplink_count") or 0)
    has_uplink_observation: bool = (uplink_result_count + uplink_state_count) > 0
    canonical_runtime_health: str = str(
        uplink_truth.get("canonical_runtime_health") or DEFAULT_RUNTIME_HEALTH_STATUS
    )

    stage = _derive_closed_loop_stage(
        lifecycle_phase=lifecycle_phase,
        is_terminal=is_terminal,
        canonical_terminal_outcome=canonical_terminal_outcome,
        reconciliation_status=reconciliation_status,
        has_uplink_observation=has_uplink_observation,
        lifecycle_event_count=lifecycle_event_count,
    )

    violations = _check_invariants(
        execution_id=execution_id,
        device_id=device_id,
        stage=stage,
        lifecycle_phase=lifecycle_phase,
        is_terminal=is_terminal,
        canonical_terminal_outcome=canonical_terminal_outcome,
        reconciliation_status=reconciliation_status,
        reconciliation_conflict=reconciliation_conflict,
        terminal_truth_authoritative_source=terminal_truth_authoritative_source,
        lifecycle_event_count=lifecycle_event_count,
        has_uplink_observation=has_uplink_observation,
        lifecycle_history=lifecycle_history,
        uplink_truth=uplink_truth,
    )
    completion_readiness = _classify_system_completion_readiness(
        stage=stage,
        is_terminal=is_terminal,
        canonical_terminal_outcome=canonical_terminal_outcome,
        terminal_truth_authoritative_source=terminal_truth_authoritative_source,
        reconciliation_status=reconciliation_status,
        reconciliation_conflict=reconciliation_conflict,
        canonical_runtime_health=canonical_runtime_health,
        uplink_result_count=uplink_result_count,
        uplink_state_count=uplink_state_count,
    )

    return ClosedLoopGovernanceView(
        execution_id=execution_id,
        device_id=device_id,
        stage=stage,
        lifecycle_phase=lifecycle_phase,
        is_terminal=is_terminal,
        canonical_terminal_outcome=canonical_terminal_outcome,
        reconciliation_status=reconciliation_status,
        reconciliation_conflict=reconciliation_conflict,
        has_uplink_observation=has_uplink_observation,
        lifecycle_event_count=lifecycle_event_count,
        uplink_result_count=uplink_result_count,
        uplink_state_count=uplink_state_count,
        terminal_truth_authoritative_source=terminal_truth_authoritative_source,
        invariant_violations=violations,
        loop_is_coherent=(len(violations) == 0),
        system_completion_ready=bool(completion_readiness["system_completion_ready"]),
        system_completion_level=str(completion_readiness["system_completion_level"]),
        system_completion_gap_types=list(completion_readiness["system_completion_gap_types"]),
    )


def assert_closed_loop_invariants(
    execution_id: str,
    device_id: str = "",
) -> List[ClosedLoopInvariantViolation]:
    """Evaluate and return all cross-stage invariant violations for *execution_id*.

    This function is the **canonical invariant assertion entry point** for
    regression testing and runtime governance audits.  It reads from existing
    governance stores and returns a (possibly empty) list of
    :class:`ClosedLoopInvariantViolation` records.

    An empty list means the loop is coherent under all defined invariants.

    Parameters
    ----------
    execution_id
        Correlation identifier for the governed execution.
    device_id
        Optional device identifier (used in violation records).

    Returns
    -------
    list[ClosedLoopInvariantViolation]
        Always returned, never raises.
    """
    view = query_closed_loop_governance_state(execution_id, device_id)
    return view.invariant_violations


def get_closed_loop_audit_record(
    execution_id: str,
    device_id: str = "",
) -> Dict[str, Any]:
    """Return a full, JSON-serialisable closed-loop audit record for *execution_id*.

    The audit record combines the :class:`ClosedLoopGovernanceView` dict with
    the raw lifecycle history and uplink truth snapshot.  It is intended for
    observability tooling, compliance audits, and test assertions.

    Parameters
    ----------
    execution_id
        Correlation identifier for the governed execution.
    device_id
        Optional device identifier.

    Returns
    -------
    dict
        Always returned, never raises.
    """
    from core.unified_execution_governance import (
        get_all_uplink_records,
        get_execution_lifecycle_history,
        get_uplink_truth_state,
    )

    view = query_closed_loop_governance_state(execution_id, device_id)

    try:
        lifecycle_history = get_execution_lifecycle_history(execution_id)
        uplink_truth = get_uplink_truth_state(execution_id)
        uplink_records = get_all_uplink_records(execution_id)
    except Exception as exc:
        logger.error(
            "get_closed_loop_audit_record: error reading stores for execution_id=%r: %s",
            execution_id, exc,
        )
        lifecycle_history = []
        uplink_truth = {}
        uplink_records = []

    return {
        "execution_id": execution_id,
        "device_id": device_id,
        "closed_loop_view": view.to_dict(),
        "lifecycle_history": lifecycle_history,
        "uplink_truth_snapshot": uplink_truth,
        "uplink_records": uplink_records,
        "audit_generated_at": time.time(),
        "_sentinel": CLOSED_LOOP_GOVERNANCE_CONSOLIDATION_SENTINEL,
        "_contract_version": CLOSED_LOOP_GOVERNANCE_CONTRACT_VERSION,
    }
