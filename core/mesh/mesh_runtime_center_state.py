"""core/mesh/mesh_runtime_center_state.py
==========================================
Center-Side Mesh Runtime State Machine — PR-03.

This module defines the **canonical center-side mesh runtime state machine**:
the explicit, enforceable contract that governs how the V2 center tracks and
transitions through the full mesh coordination lifecycle.

Problem addressed
-----------------
Previously, ``build_mesh_runtime_state()`` in ``unified_governance_semantics``
was purely a sentinel-presence check that returned a descriptive snapshot.  It
did not express a real center-side runtime state machine and could not enforce
the critical distinction between:

    *"Participation-ready"*  — participants are registered, eligible, and
    capable of participating in a mesh session; the center has confirmed their
    eligibility but has not yet driven a full coordination cycle to completion.

    *"Runtime-closed"*  — the center has driven a full mesh coordination cycle
    to completion: all active participants have reached and passed the barrier,
    results have been merged, and the session has been closed.

This module:

1. Defines :class:`MeshRuntimeCenterStatus` — the canonical state machine
   enum for center-side mesh runtime.
2. Defines :data:`MESH_RUNTIME_CENTER_VALID_TRANSITIONS` — the explicit set of
   allowed state transitions.
3. Defines :class:`MeshParticipantCenterEligibility` — center-side per-participant
   eligibility/readiness/degraded/constrained semantics.
4. Defines :class:`MeshRuntimeCenterState` — the top-level center runtime state
   object that the center maintains throughout a mesh coordination cycle.
5. Provides :func:`evaluate_center_runtime_status` — the canonical function
   that derives the center-side runtime status from real coordinator state.
6. Provides :func:`build_mesh_runtime_center_state` — the operator/panel-safe
   surface that replaces the old sentinel-based projection.

State machine transitions
-------------------------
::

    pending_participants
        ├── → participation_ready   (≥1 participant registered + eligible)
        └── → failed               (no participants, terminal)

    participation_ready
        ├── → runtime_active       (coordinator promoted to active; runtime running)
        ├── → degraded             (participants registered but not all healthy)
        └── → constrained          (only partial participants eligible)

    runtime_active
        ├── → barrier_active       (barrier coordination begins)
        ├── → degraded             (participant failures during active execution)
        ├── → constrained          (partial participants mid-execution)
        └── → failed               (critical runtime failure)

    barrier_active
        ├── → barrier_released     (all active participants arrived at barrier)
        ├── → degraded             (some participants failed at barrier; others OK)
        └── → failed               (barrier timeout; no participants arrived)

    barrier_released
        ├── → runtime_closed       (merge complete; full success)
        └── → degraded             (merge complete; partial results)

    degraded
        └── → runtime_closed       (degraded but completed)

    constrained
        └── → runtime_closed       (constrained but completed)

    failed / runtime_closed / unknown
        (terminal states — no further transitions)

Design
------
- **Additive only** — does not modify any existing module.
- **Grounded in real runtime state** — transitions are derived from
  :mod:`contracts.mesh_session_coordinator` coordinator state, not sentinels.
- **Participation-ready ≠ runtime-closed** — the distinction is explicit and
  enforced in transition validation.
- **Graceful defaults** — all functions return valid objects even on partial
  failures.

Sentinels
---------
:data:`MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL`
    Asserts this module is the center-side mesh runtime state machine (PR-03).
:data:`PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY`
    Policy: participation-ready and runtime-closed MUST be distinct states.
:data:`BARRIER_LIFECYCLE_CENTER_PR03_POLICY`
    Policy: barrier lifecycle MUST be explicitly tracked through all transitions.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# PR-03 authority sentinels
# ---------------------------------------------------------------------------

MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL: str = (
    "SENTINEL::MESH_RUNTIME_CENTER_STATE_PR03: "
    "center-side mesh runtime state machine making full-mesh coordination "
    "explicit and enforceable; "
    "package=PR-03::mesh-runtime-center-closure"
)

PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY: str = (
    "POLICY::PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03: "
    "The center MUST distinguish between 'participation_ready' (participants "
    "registered and eligible but no full coordination cycle completed) and "
    "'runtime_closed' (a full mesh coordination cycle has been driven to "
    "completion: barrier reached, results merged, session closed).  These are "
    "NOT equivalent and MUST NOT be treated as synonymous."
)

BARRIER_LIFECYCLE_CENTER_PR03_POLICY: str = (
    "POLICY::BARRIER_LIFECYCLE_CENTER_PR03: "
    "The center MUST explicitly track barrier state through the full lifecycle: "
    "pending_participants → participation_ready → runtime_active → barrier_active "
    "→ barrier_released → runtime_closed.  Skipping barrier_active is only "
    "permitted when barrier_posture is 'not_required'.  A barrier timeout MUST "
    "result in 'failed', not silent degradation."
)

PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY: str = (
    "POLICY::PARTICIPANT_ELIGIBILITY_CENTER_PR03: "
    "The center MUST separately track participant 'eligibility' (can participate "
    "by governance policy) vs 'readiness' (has confirmed readiness for this "
    "session).  A participant may be eligible but not ready (still pending), "
    "ready but degraded (online but not at full capacity), or constrained "
    "(eligible with limited capability).  These distinctions affect center-side "
    "runtime status and outcome computation."
)

DEGRADED_CONSTRAINED_CENTER_PR03_POLICY: str = (
    "POLICY::DEGRADED_CONSTRAINED_CENTER_PR03: "
    "A 'degraded' runtime means at least one participant is not at full capacity "
    "but execution continues.  A 'constrained' runtime means the center is "
    "executing with fewer participants than originally planned.  Both are valid "
    "non-failure outcomes.  A 'failed' runtime means the coordination cycle "
    "cannot complete even partially."
)

_COORDINATION_ACTIVATED_COORDINATOR_STATUSES = (
    "active",
    "awaiting_barrier",
    "merging",
    "completed",
    "partial",
    "failed",
)
_COMPLETION_OBSERVED_COORDINATOR_STATUSES = (
    "completed",
    "partial",
    "failed",
)
_LIFECYCLE_CLOSURE_RUNTIME_CLOSED = "runtime_closed"
_LIFECYCLE_CLOSURE_PARTICIPATION_READY_NOT_CLOSED = "participation_ready_not_closed"
_LIFECYCLE_CLOSURE_NOT_PARTICIPATION_READY = "not_participation_ready"


# ---------------------------------------------------------------------------
# State machine enum
# ---------------------------------------------------------------------------


class MeshRuntimeCenterStatus(str, Enum):
    """Canonical center-side mesh runtime state machine.

    pending_participants
        No participants have been registered; the center cannot advance to any
        active coordination state.  This is the initial state.

    participation_ready
        At least one participant is registered and eligible to participate.
        The center has confirmed participant eligibility but has NOT yet driven
        a full coordination cycle to completion.

        **Critical distinction**: ``participation_ready`` ≠ ``runtime_closed``.
        Being participation-ready means the mesh *can* run; it does not mean a
        coordination cycle has completed.

    runtime_active
        The coordinator has been promoted to active and participant execution
        is in progress.  The barrier has not yet been reached.

    barrier_active
        The coordinator is in barrier coordination: one or more participants
        have reached the barrier and the center is waiting for remaining
        participants to arrive.

    barrier_released
        All active participants have arrived at the barrier; the barrier has
        been released.  The center is in the merge/aggregation phase.

    runtime_closed
        A full mesh coordination cycle has been driven to successful completion:
        barrier reached (or bypassed), results merged, coordinator finalised.
        This is the only terminal success state.

    degraded
        The runtime is executing or has completed, but one or more participants
        are operating below full capacity.  The coordination cycle may still
        complete with partial results.

    constrained
        The runtime is executing with fewer participants than originally planned
        (some participants dropped or were excluded).  Execution continues on
        the available participants.

    failed
        The mesh runtime coordination has failed.  No meaningful completion
        can be expected without restarting the session.

    unknown
        The center-side runtime status cannot be determined from available
        runtime state.
    """

    pending_participants = "pending_participants"
    participation_ready = "participation_ready"
    runtime_active = "runtime_active"
    barrier_active = "barrier_active"
    barrier_released = "barrier_released"
    runtime_closed = "runtime_closed"
    degraded = "degraded"
    constrained = "constrained"
    failed = "failed"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

MESH_RUNTIME_CENTER_VALID_TRANSITIONS: Dict[MeshRuntimeCenterStatus, Set[MeshRuntimeCenterStatus]] = {
    MeshRuntimeCenterStatus.pending_participants: {
        MeshRuntimeCenterStatus.participation_ready,
        MeshRuntimeCenterStatus.failed,
    },
    MeshRuntimeCenterStatus.participation_ready: {
        MeshRuntimeCenterStatus.runtime_active,
        MeshRuntimeCenterStatus.degraded,
        MeshRuntimeCenterStatus.constrained,
        MeshRuntimeCenterStatus.failed,
    },
    MeshRuntimeCenterStatus.runtime_active: {
        MeshRuntimeCenterStatus.barrier_active,
        MeshRuntimeCenterStatus.degraded,
        MeshRuntimeCenterStatus.constrained,
        MeshRuntimeCenterStatus.runtime_closed,
        MeshRuntimeCenterStatus.failed,
    },
    MeshRuntimeCenterStatus.barrier_active: {
        MeshRuntimeCenterStatus.barrier_released,
        MeshRuntimeCenterStatus.degraded,
        MeshRuntimeCenterStatus.failed,
    },
    MeshRuntimeCenterStatus.barrier_released: {
        MeshRuntimeCenterStatus.runtime_closed,
        MeshRuntimeCenterStatus.degraded,
    },
    MeshRuntimeCenterStatus.degraded: {
        MeshRuntimeCenterStatus.runtime_closed,
        MeshRuntimeCenterStatus.failed,
    },
    MeshRuntimeCenterStatus.constrained: {
        MeshRuntimeCenterStatus.runtime_closed,
        MeshRuntimeCenterStatus.failed,
    },
    # Terminal states — no further transitions
    MeshRuntimeCenterStatus.runtime_closed: set(),
    MeshRuntimeCenterStatus.failed: set(),
    MeshRuntimeCenterStatus.unknown: {
        MeshRuntimeCenterStatus.pending_participants,
        MeshRuntimeCenterStatus.failed,
    },
}

# States from which the session is considered actively progressing
MESH_RUNTIME_CENTER_ACTIVE_STATUSES: Set[MeshRuntimeCenterStatus] = {
    MeshRuntimeCenterStatus.runtime_active,
    MeshRuntimeCenterStatus.barrier_active,
    MeshRuntimeCenterStatus.barrier_released,
    MeshRuntimeCenterStatus.degraded,
    MeshRuntimeCenterStatus.constrained,
}

# Terminal states
MESH_RUNTIME_CENTER_TERMINAL_STATUSES: Set[MeshRuntimeCenterStatus] = {
    MeshRuntimeCenterStatus.runtime_closed,
    MeshRuntimeCenterStatus.failed,
}


def is_valid_center_transition(
    from_status: MeshRuntimeCenterStatus,
    to_status: MeshRuntimeCenterStatus,
) -> bool:
    """Return True when *from_status* → *to_status* is a valid transition.

    Parameters
    ----------
    from_status:
        Current center runtime status.
    to_status:
        Proposed next center runtime status.

    Returns
    -------
    bool
        ``True`` if the transition is valid; ``False`` otherwise.
    """
    allowed = MESH_RUNTIME_CENTER_VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


# ---------------------------------------------------------------------------
# Per-participant center eligibility
# ---------------------------------------------------------------------------


class MeshParticipantEligibilityStatus(str, Enum):
    """Center-side per-participant eligibility classification.

    eligible
        Participant has passed all governance gates and is eligible to
        participate in a full mesh coordination cycle.

    ready
        Participant is eligible AND has confirmed readiness for this session.
        A participant may be eligible but not yet ready (still pending
        confirmation).

    degraded
        Participant is eligible and connected but operating below full capacity
        (e.g. limited resources, partial capability, reduced throughput).

    constrained
        Participant is eligible with restricted capability — it can participate
        but only in a subset of roles or with limited subtask scope.

    pending_eligibility
        Participant has been registered but eligibility has not yet been
        confirmed by the center.

    ineligible
        Participant has been explicitly excluded by governance policy.

    offline
        Participant is not reachable; cannot participate.

    unknown
        Eligibility cannot be determined from available runtime state.
    """

    eligible = "eligible"
    ready = "ready"
    degraded = "degraded"
    constrained = "constrained"
    pending_eligibility = "pending_eligibility"
    ineligible = "ineligible"
    offline = "offline"
    unknown = "unknown"

    def can_participate(self) -> bool:
        """Return True when this participant can meaningfully participate."""
        return self in (
            MeshParticipantEligibilityStatus.eligible,
            MeshParticipantEligibilityStatus.ready,
            MeshParticipantEligibilityStatus.degraded,
            MeshParticipantEligibilityStatus.constrained,
        )

    def is_participation_ready(self) -> bool:
        """Return True when this participant is participation-ready.

        A participant is participation-ready if the center has registered them
        (``eligible``), they have explicitly confirmed readiness (``ready``), or
        they are still participating in a degraded/constrained capacity.

        Note: ``eligible`` alone (registered in the coordinator) counts as
        participation-ready because registration means the center has decided
        this participant should be in the session.
        """
        return self in (
            MeshParticipantEligibilityStatus.eligible,
            MeshParticipantEligibilityStatus.ready,
            MeshParticipantEligibilityStatus.degraded,
            MeshParticipantEligibilityStatus.constrained,
        )


@dataclass
class MeshParticipantCenterEligibility:
    """Center-side eligibility record for a single mesh participant.

    Attributes
    ----------
    device_id:
        Stable identifier for this participant.
    eligibility:
        Center-side eligibility classification.
    participation_ready:
        Whether this participant is participation-ready (eligible + confirmed
        readiness).
    runtime_closed:
        Whether this participant has completed a full runtime coordination
        cycle (barrier reached + result contributed).
    participant_status:
        The coordinator-level participant status (from
        :class:`~contracts.mesh_session_coordinator.MeshParticipantStatus`).
    roles:
        Roles assigned to this participant.
    degraded_reason:
        Optional reason for degraded eligibility.
    constrained_reason:
        Optional reason for constrained eligibility.
    metadata:
        Arbitrary extension metadata.
    """

    device_id: str
    eligibility: MeshParticipantEligibilityStatus = MeshParticipantEligibilityStatus.unknown
    participation_ready: bool = False
    runtime_closed: bool = False
    participant_status: str = "unknown"
    roles: List[str] = field(default_factory=list)
    degraded_reason: Optional[str] = None
    constrained_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "eligibility": self.eligibility.value,
            "participation_ready": self.participation_ready,
            "runtime_closed": self.runtime_closed,
            "participant_status": self.participant_status,
            "roles": self.roles,
            "degraded_reason": self.degraded_reason,
            "constrained_reason": self.constrained_reason,
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# Center runtime state contract
# ---------------------------------------------------------------------------


@dataclass
class MeshRuntimeCenterState:
    """Center-side mesh runtime state machine contract.

    This is the canonical runtime object the center maintains throughout a
    mesh coordination cycle.  It is the authoritative answer to:

        *"What is the center's runtime view of the current mesh session?"*

    Attributes
    ----------
    status:
        Current center-side state machine status.
    session_id:
        Mesh session identifier, if known.
    coordinator_status:
        Underlying coordinator status (from
        :class:`~contracts.mesh_session_coordinator.MeshCoordinatorStatus`).
    barrier_status:
        Current barrier synchronisation status (from
        :class:`~contracts.mesh_session_coordinator.MeshBarrierStatus`).
    participant_eligibilities:
        Per-participant center eligibility records.
    participation_ready_count:
        Number of participants that are participation-ready.
    runtime_closed_count:
        Number of participants that have completed a full runtime cycle.
    degraded_count:
        Number of participants in degraded state.
    constrained_count:
        Number of participants in constrained state.
    ineligible_count:
        Number of participants that are ineligible to participate.
    total_participant_count:
        Total number of registered participants.
    is_participation_ready:
        True when the center considers the mesh session participation-ready
        (≥1 eligible participant confirmed; runtime may start).
    is_runtime_closed:
        True ONLY when a full coordination cycle has been driven to
        completion.  Critically: ``is_runtime_closed ≠ is_participation_ready``.
    deferred_or_constrained:
        Human-readable list of deferred or constrained items that prevent
        full runtime closure.
    transition_history:
        Ordered list of ``(from_status, to_status, timestamp)`` tuples
        recording state transitions for observability.
    errors:
        List of error strings accumulated during state evaluation.
    evaluated_at:
        Unix timestamp when this state was last evaluated.
    metadata:
        Arbitrary extension metadata.
    """

    status: MeshRuntimeCenterStatus = MeshRuntimeCenterStatus.unknown
    session_id: Optional[str] = None
    coordinator_status: str = "unknown"
    barrier_status: str = "unknown"
    participant_eligibilities: List[MeshParticipantCenterEligibility] = field(default_factory=list)
    participation_ready_count: int = 0
    runtime_closed_count: int = 0
    degraded_count: int = 0
    constrained_count: int = 0
    ineligible_count: int = 0
    total_participant_count: int = 0
    is_participation_ready: bool = False
    is_runtime_closed: bool = False
    deferred_or_constrained: List[str] = field(default_factory=list)
    transition_history: List[Dict[str, Any]] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    evaluated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def build_lifecycle_proof(self) -> Dict[str, Any]:
        """Build an explicit proof surface for mesh runtime lifecycle closure."""
        has_active_or_terminal_center_status = (
            self.status in MESH_RUNTIME_CENTER_ACTIVE_STATUSES
            or self.status in MESH_RUNTIME_CENTER_TERMINAL_STATUSES
        )
        coordination_activated = (
            self.coordinator_status in _COORDINATION_ACTIVATED_COORDINATOR_STATUSES
            or has_active_or_terminal_center_status
        )
        barrier_wait_observed = (
            self.barrier_status == "waiting"
            or self.coordinator_status == "awaiting_barrier"
            or self.status == MeshRuntimeCenterStatus.barrier_active
        )
        barrier_release_observed = (
            self.barrier_status == "released"
            or self.status in (
                MeshRuntimeCenterStatus.barrier_released,
                MeshRuntimeCenterStatus.runtime_closed,
            )
        )
        completion_observed = (
            self.coordinator_status in _COMPLETION_OBSERVED_COORDINATOR_STATUSES
            or self.runtime_closed_count > 0
            or self.status in MESH_RUNTIME_CENTER_TERMINAL_STATUSES
        )
        partial_or_degraded_path = (
            self.status in (
                MeshRuntimeCenterStatus.degraded,
                MeshRuntimeCenterStatus.constrained,
                MeshRuntimeCenterStatus.failed,
            )
            or self.degraded_count > 0
            or self.constrained_count > 0
            or self.ineligible_count > 0
            or (
                # Some participants have closed while others have not: partial completion.
                self.total_participant_count > 0
                and self.runtime_closed_count < self.total_participant_count
                and completion_observed
            )
        )

        if self.is_runtime_closed:
            closure_classification = _LIFECYCLE_CLOSURE_RUNTIME_CLOSED
        elif self.is_participation_ready:
            closure_classification = _LIFECYCLE_CLOSURE_PARTICIPATION_READY_NOT_CLOSED
        else:
            closure_classification = _LIFECYCLE_CLOSURE_NOT_PARTICIPATION_READY

        return {
            "participation_registered": self.total_participant_count > 0,
            "participation_ready": self.is_participation_ready,
            "coordination_activated": coordination_activated,
            "barrier_wait_observed": barrier_wait_observed,
            "barrier_release_observed": barrier_release_observed,
            "completion_observed": completion_observed,
            "runtime_closed": self.is_runtime_closed,
            "closure_classification": closure_classification,
            "partial_or_degraded_path": partial_or_degraded_path,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return {
            "status": self.status.value,
            "session_id": self.session_id,
            "coordinator_status": self.coordinator_status,
            "barrier_status": self.barrier_status,
            "participant_eligibilities": [p.to_dict() for p in self.participant_eligibilities],
            "participation_ready_count": self.participation_ready_count,
            "runtime_closed_count": self.runtime_closed_count,
            "degraded_count": self.degraded_count,
            "constrained_count": self.constrained_count,
            "ineligible_count": self.ineligible_count,
            "total_participant_count": self.total_participant_count,
            "is_participation_ready": self.is_participation_ready,
            "is_runtime_closed": self.is_runtime_closed,
            "deferred_or_constrained": self.deferred_or_constrained,
            "transition_history": self.transition_history,
            "errors": self.errors,
            "evaluated_at": self.evaluated_at,
            "metadata": self.metadata,
            "lifecycle_proof": self.build_lifecycle_proof(),
            "_policy_participation_ready_vs_closed": PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY,
            "_sentinel": MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _participant_status_to_eligibility(
    participant_status: str,
    coordinator_status: str,
) -> MeshParticipantEligibilityStatus:
    """Derive center-side eligibility from coordinator participant status.

    Note: A participant that has been registered in the coordinator (even in
    ``pending`` status) is treated as ``eligible`` by the center — the act of
    registration confirms the center has included them in the mesh session.
    Being ``eligible`` is distinct from being ``ready`` (which requires the
    participant to have explicitly confirmed readiness via a runtime event).

    Parameters
    ----------
    participant_status:
        String value of MeshParticipantStatus.
    coordinator_status:
        String value of the overall coordinator status.

    Returns
    -------
    MeshParticipantEligibilityStatus
    """
    if participant_status in ("offline",):
        return MeshParticipantEligibilityStatus.offline
    if participant_status in ("failed",):
        return MeshParticipantEligibilityStatus.ineligible
    if participant_status in ("completed",):
        return MeshParticipantEligibilityStatus.ready
    if participant_status in ("ready", "working", "waiting"):
        return MeshParticipantEligibilityStatus.ready
    if participant_status in ("pending", "unknown"):
        # Registered in coordinator = eligible (center has included them)
        return MeshParticipantEligibilityStatus.eligible
    return MeshParticipantEligibilityStatus.unknown


def _compute_center_status_from_coordinator(
    coordinator_status: str,
    barrier_status: str,
    total_participants: int,
    participation_ready_count: int,
    runtime_closed_count: int,
    degraded_count: int,
    constrained_count: int,
) -> MeshRuntimeCenterStatus:
    """Derive the center-side MeshRuntimeCenterStatus from coordinator state.

    This is the canonical function that translates coordinator-level state
    into center-side state machine status.

    Parameters
    ----------
    coordinator_status:
        String value of MeshCoordinatorStatus.
    barrier_status:
        String value of MeshBarrierStatus.
    total_participants:
        Total number of registered participants.
    participation_ready_count:
        Number of participation-ready participants.
    runtime_closed_count:
        Number of participants that completed a full runtime cycle.
    degraded_count:
        Number of degraded participants.
    constrained_count:
        Number of constrained participants.

    Returns
    -------
    MeshRuntimeCenterStatus
    """
    if total_participants == 0:
        return MeshRuntimeCenterStatus.pending_participants

    # Terminal states map directly
    if coordinator_status in ("failed",) and participation_ready_count == 0:
        return MeshRuntimeCenterStatus.failed

    if coordinator_status in ("completed",) and runtime_closed_count == total_participants:
        return MeshRuntimeCenterStatus.runtime_closed

    if coordinator_status in ("completed",) and runtime_closed_count > 0:
        # Some completed but not all — degraded completion
        return MeshRuntimeCenterStatus.degraded

    if coordinator_status in ("partial",):
        return MeshRuntimeCenterStatus.degraded

    # Map barrier states
    if barrier_status in ("waiting",) or coordinator_status in ("awaiting_barrier",):
        return MeshRuntimeCenterStatus.barrier_active

    if barrier_status in ("released",) and coordinator_status in ("merging", "completed", "partial"):
        # Barrier released but merge may not be done yet
        if coordinator_status in ("completed",):
            if runtime_closed_count == total_participants:
                return MeshRuntimeCenterStatus.runtime_closed
            return MeshRuntimeCenterStatus.degraded
        return MeshRuntimeCenterStatus.barrier_released

    if barrier_status in ("failed",):
        return MeshRuntimeCenterStatus.failed

    # Map active coordinator states
    if coordinator_status in ("active", "merging"):
        if degraded_count > 0:
            return MeshRuntimeCenterStatus.degraded
        if constrained_count > 0:
            return MeshRuntimeCenterStatus.constrained
        return MeshRuntimeCenterStatus.runtime_active

    if coordinator_status in ("pending", "unknown"):
        if participation_ready_count > 0:
            return MeshRuntimeCenterStatus.participation_ready
        if total_participants > 0:
            return MeshRuntimeCenterStatus.pending_participants

    return MeshRuntimeCenterStatus.unknown


# ---------------------------------------------------------------------------
# Public API: evaluate from coordinator state
# ---------------------------------------------------------------------------


def evaluate_center_runtime_status(
    coordinator_state: Any,
) -> MeshRuntimeCenterState:
    """Derive the center-side mesh runtime state from a coordinator state object.

    This function reads real coordinator state (from
    :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`)
    and produces a :class:`MeshRuntimeCenterState` that reflects the actual
    center-side runtime status.

    Parameters
    ----------
    coordinator_state:
        A :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        or compatible object.  May be ``None``.

    Returns
    -------
    MeshRuntimeCenterState
        Never raises.
    """
    errors: List[str] = []
    deferred: List[str] = []

    try:
        if coordinator_state is None:
            return MeshRuntimeCenterState(
                status=MeshRuntimeCenterStatus.pending_participants,
                errors=["coordinator_state_is_none"],
                deferred_or_constrained=["no coordinator state provided"],
            )

        session_id: Optional[str] = getattr(coordinator_state, "session_id", None)
        participants = list(getattr(coordinator_state, "participants", []) or [])
        barrier_state = getattr(coordinator_state, "barrier_state", None)
        coord_status_obj = getattr(coordinator_state, "status", None)
        coord_status = (
            coord_status_obj.value if hasattr(coord_status_obj, "value") else str(coord_status_obj or "unknown")
        )

        barrier_status_obj = getattr(barrier_state, "status", None) if barrier_state else None
        barrier_status = (
            barrier_status_obj.value if hasattr(barrier_status_obj, "value") else str(barrier_status_obj or "unknown")
        )

        # Build per-participant eligibility records
        participant_eligibilities: List[MeshParticipantCenterEligibility] = []
        participation_ready_count = 0
        runtime_closed_count = 0
        degraded_count = 0
        constrained_count = 0
        ineligible_count = 0
        total_participant_count = len(participants)

        for p in participants:
            did = getattr(p, "device_id", "")
            p_status_obj = getattr(p, "status", None)
            p_status = (
                p_status_obj.value if hasattr(p_status_obj, "value") else str(p_status_obj or "unknown")
            )
            roles = list(getattr(p, "roles", []) or [])
            online = getattr(p, "online", None)

            eligibility = _participant_status_to_eligibility(p_status, coord_status)

            # A participant is participation_ready if they are ready/working/waiting/completed
            is_part_ready = eligibility.is_participation_ready()
            # A participant has contributed to runtime_closed if completed
            is_rt_closed = p_status in ("completed",)

            # Check for degraded signals
            degraded_reason: Optional[str] = None
            constrained_reason: Optional[str] = None
            if online is False and p_status not in ("offline", "failed"):
                eligibility = MeshParticipantEligibilityStatus.degraded
                degraded_reason = "participant_offline_but_not_marked"
                is_part_ready = True  # still attempted participation
            elif p_status in ("waiting",) and online is False:
                eligibility = MeshParticipantEligibilityStatus.degraded
                degraded_reason = "participant_offline_while_waiting_at_barrier"

            if eligibility == MeshParticipantEligibilityStatus.degraded:
                degraded_count += 1
            elif eligibility == MeshParticipantEligibilityStatus.constrained:
                constrained_count += 1
            elif eligibility == MeshParticipantEligibilityStatus.ineligible:
                ineligible_count += 1

            if is_part_ready:
                participation_ready_count += 1
            if is_rt_closed:
                runtime_closed_count += 1

            participant_eligibilities.append(
                MeshParticipantCenterEligibility(
                    device_id=did,
                    eligibility=eligibility,
                    participation_ready=is_part_ready,
                    runtime_closed=is_rt_closed,
                    participant_status=p_status,
                    roles=roles,
                    degraded_reason=degraded_reason,
                    constrained_reason=constrained_reason,
                )
            )

        # Compute center-side status
        center_status = _compute_center_status_from_coordinator(
            coordinator_status=coord_status,
            barrier_status=barrier_status,
            total_participants=total_participant_count,
            participation_ready_count=participation_ready_count,
            runtime_closed_count=runtime_closed_count,
            degraded_count=degraded_count,
            constrained_count=constrained_count,
        )

        # is_participation_ready: True iff ≥1 participant is participation-ready
        # and coordinator is not failed
        is_participation_ready = (
            participation_ready_count > 0
            and coord_status not in ("failed",)
        )

        # is_runtime_closed: True ONLY when the full coordination cycle completed
        is_runtime_closed = center_status == MeshRuntimeCenterStatus.runtime_closed

        # Build deferred/constrained notes
        if ineligible_count > 0:
            deferred.append(
                f"{ineligible_count}/{total_participant_count} participants ineligible to participate"
            )
        if degraded_count > 0:
            deferred.append(
                f"{degraded_count}/{total_participant_count} participants in degraded state"
            )
        if constrained_count > 0:
            deferred.append(
                f"{constrained_count}/{total_participant_count} participants constrained"
            )
        if not is_runtime_closed and total_participant_count > 0:
            deferred.append(
                "runtime not yet closed — full coordination cycle has not completed"
            )
        # Add the participation_ready vs runtime_closed distinction note only when
        # the state is explicitly participation_ready (i.e. participants registered and
        # eligible but coordinator has not yet started active execution).  In
        # runtime_active / barrier_active / barrier_released states the runtime is
        # already progressing, so the note would be redundant noise.
        if center_status == MeshRuntimeCenterStatus.participation_ready:
            deferred.append(
                "participation_ready but not runtime_closed: "
                "participants eligible but no full coordination cycle completed yet"
            )

        return MeshRuntimeCenterState(
            status=center_status,
            session_id=session_id,
            coordinator_status=coord_status,
            barrier_status=barrier_status,
            participant_eligibilities=participant_eligibilities,
            participation_ready_count=participation_ready_count,
            runtime_closed_count=runtime_closed_count,
            degraded_count=degraded_count,
            constrained_count=constrained_count,
            ineligible_count=ineligible_count,
            total_participant_count=total_participant_count,
            is_participation_ready=is_participation_ready,
            is_runtime_closed=is_runtime_closed,
            deferred_or_constrained=deferred,
            errors=errors,
        )

    except Exception as exc:
        errors.append(f"evaluate_center_runtime_status_error:{exc}")
        _logger.warning("evaluate_center_runtime_status: error: %s", exc)
        return MeshRuntimeCenterState(
            status=MeshRuntimeCenterStatus.unknown,
            errors=errors,
            deferred_or_constrained=["evaluation failed due to unexpected error"],
        )


# ---------------------------------------------------------------------------
# Public API: build operator/panel-safe snapshot
# ---------------------------------------------------------------------------


def build_mesh_runtime_center_state(
    coordinator_state: Any = None,
) -> Dict[str, Any]:
    """Build an operator/panel-safe center-side mesh runtime state snapshot.

    This replaces the old sentinel-based ``build_mesh_runtime_state()``
    projection with a real center-side state machine output.

    Parameters
    ----------
    coordinator_state:
        Optional coordinator state to evaluate.  If ``None``, the function
        attempts to derive state from the runtime module (best-effort).

    Returns
    -------
    dict
        A stable, JSON-safe dictionary containing the full center-side mesh
        runtime state.  Always returns a valid dict; never raises.
    """
    try:
        effective_coordinator = coordinator_state

        # If no coordinator state provided, try to derive from runtime
        if effective_coordinator is None:
            try:
                from core.mesh.live_mesh_session_coordinator import (
                    LIVE_MESH_SESSION_COORDINATOR_PR_J_SENTINEL,
                )
                # Runtime modules are present; coordinator state not provided
                # Return a valid "participation_ready" snapshot based on sentinel presence
                center_state = MeshRuntimeCenterState(
                    status=MeshRuntimeCenterStatus.participation_ready,
                    deferred_or_constrained=[
                        "coordinator state not provided — cannot determine runtime_closed",
                        "participation_ready but not runtime_closed: "
                        "live runtime modules present but no active session context",
                    ],
                    metadata={"source": "sentinel_presence_only"},
                )
            except ImportError:
                center_state = MeshRuntimeCenterState(
                    status=MeshRuntimeCenterStatus.pending_participants,
                    deferred_or_constrained=[
                        "live mesh runtime modules not available",
                    ],
                    errors=["live_mesh_runtime_engine_not_available"],
                    metadata={"source": "sentinel_absent"},
                )
        else:
            center_state = evaluate_center_runtime_status(effective_coordinator)

        result = center_state.to_dict()
        result["_policy_barrier_lifecycle"] = BARRIER_LIFECYCLE_CENTER_PR03_POLICY
        result["_policy_eligibility"] = PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY
        result["_policy_degraded_constrained"] = DEGRADED_CONSTRAINED_CENTER_PR03_POLICY
        return result

    except Exception as exc:
        _logger.warning("build_mesh_runtime_center_state: error: %s", exc)
        return {
            "status": MeshRuntimeCenterStatus.unknown.value,
            "errors": [f"build_error:{exc}"],
            "_sentinel": MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "MESH_RUNTIME_CENTER_STATE_PR03_SENTINEL",
    "PARTICIPATION_READY_VS_RUNTIME_CLOSED_PR03_POLICY",
    "BARRIER_LIFECYCLE_CENTER_PR03_POLICY",
    "PARTICIPANT_ELIGIBILITY_CENTER_PR03_POLICY",
    "DEGRADED_CONSTRAINED_CENTER_PR03_POLICY",
    # State machine
    "MeshRuntimeCenterStatus",
    "MESH_RUNTIME_CENTER_VALID_TRANSITIONS",
    "MESH_RUNTIME_CENTER_ACTIVE_STATUSES",
    "MESH_RUNTIME_CENTER_TERMINAL_STATUSES",
    "is_valid_center_transition",
    # Participant eligibility
    "MeshParticipantEligibilityStatus",
    "MeshParticipantCenterEligibility",
    # Center state
    "MeshRuntimeCenterState",
    # Evaluation
    "evaluate_center_runtime_status",
    # Builder
    "build_mesh_runtime_center_state",
]
