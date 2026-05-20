"""contracts/participant_lifecycle_schema.py
=============================================
Participant Lifecycle Schema — PR-Task3.

This module defines the **canonical participant lifecycle schema**: the
formal, serialisable state machine and role lifecycle that governs how
a participant's lifecycle state is managed by V2 canonical governance.

This schema answers:

    *"What lifecycle states can a participant be in, what roles can it hold,
    and how do state transitions affect dispatch, truth convergence, and
    closure?"*

Key design decisions
--------------------
- **Center authority**: V2 canonical governance is the sole authority for
  participant lifecycle state transitions.  A bounded relative subject
  (e.g. Android) may signal intent but cannot self-transition.
- **Role × State orthogonality**: A participant has both a *role* (what it
  is responsible for) and a *state* (what its current lifecycle status is).
  These are orthogonal dimensions.
- **Transition triggers**: Every transition has explicit trigger conditions,
  truth implications, and closure implications.
- **Evidence policy**: Bounded subject signals (readiness, posture, busy,
  capability) are input evidence; V2 governance decides transitions.

Participant roles
-----------------
``primary``
    The participant that anchors the cognitive session and holds primary
    execution responsibility for the overall task outcome.

``assistant``
    A participant contributing supplementary execution capacity to the
    primary participant's flow.

``fallback``
    A participant pre-registered as a degraded-completion alternative if
    the primary fails.

``suspended``
    A participant that has been explicitly suspended from active execution
    (e.g. due to resource pressure or operator directive).

``takeover_candidate``
    A participant that has been pre-qualified by V2 governance to take over
    execution from another participant.

``degraded``
    A participant that is still active but has been downgraded to a reduced
    execution model (e.g. due to capability degradation).

Participant lifecycle states
----------------------------
``unregistered``
    Device exists in the system but has not yet attached a runtime session.

``attaching``
    Device is in the process of initial attachment.  A failed attachment
    returns to ``unregistered``.

``attached``
    Device has a live runtime attachment session.  Ready to receive dispatch.

``dispatched``
    V2 has dispatched a task to this participant; execution is in progress.

``executing``
    Participant is actively executing the dispatched task.

``waiting_result``
    Participant has signalled execution completion but V2 has not yet
    accepted the result into the canonical truth chain.

``result_accepted``
    V2 has accepted the participant's execution result.  Closure may follow.

``suspended``
    Participant has been explicitly suspended from active execution.

``takeover_candidate``
    Participant has been pre-qualified as a takeover candidate.

``taking_over``
    Participant is in the process of taking over execution from another.

``degraded``
    Participant is active but operating in a degraded execution model.

``recovering``
    Participant is in a recovery/replay cycle after an interruption.

``detached``
    Transport connection has been lost; awaiting reconnect or replacement.

``terminal``
    Participant has completed all lifecycle phases and is no longer active.

Sentinels
---------
:data:`PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL`
    Canonical module-level sentinel.

:data:`PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER`
    V2 assigns participant roles; subjects may not self-assign.

:data:`PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE`
    V2 is the sole authority for participant state transitions.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Sentinels
# ---------------------------------------------------------------------------

PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL: str = (
    "PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL: "
    "contracts/participant_lifecycle_schema.py is the canonical schema for "
    "participant roles and lifecycle states in the Galaxy distributed subject "
    "system.  It is governed by V2 canonical governance and must not be "
    "self-administered by bounded relative subjects."
)

PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER: str = (
    "PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER: "
    "Participant roles (primary, assistant, fallback, suspended, "
    "takeover_candidate, degraded) are assigned by V2 canonical governance. "
    "A bounded relative subject may signal capability and readiness, but "
    "role assignment is a V2 dispatch-arbitration decision."
)

PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE: str = (
    "PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE: "
    "Participant lifecycle state transitions are authoritative only when "
    "issued by V2 canonical governance.  Bounded subject signals (readiness, "
    "posture, busy, capability) are input evidence for transitions, not "
    "self-transition commands."
)


# ---------------------------------------------------------------------------
# Participant role enum
# ---------------------------------------------------------------------------


class ParticipantRole(str, Enum):
    """Canonical participant role within a task flow.

    Roles are assigned by V2 canonical governance during dispatch arbitration.
    """

    PRIMARY = "primary"
    """Primary executor; anchors the cognitive session."""

    ASSISTANT = "assistant"
    """Supplementary executor contributing to the primary flow."""

    FALLBACK = "fallback"
    """Pre-registered degraded-completion alternative."""

    SUSPENDED = "suspended"
    """Explicitly suspended from active execution."""

    TAKEOVER_CANDIDATE = "takeover_candidate"
    """Pre-qualified by V2 to take over execution."""

    DEGRADED = "degraded"
    """Active but operating in a reduced execution model."""


# ---------------------------------------------------------------------------
# Participant lifecycle state enum
# ---------------------------------------------------------------------------


class ParticipantLifecycleState(str, Enum):
    """Canonical participant lifecycle state.

    States are maintained by V2 canonical governance.  Bounded subjects
    may signal readiness/posture/busy but cannot self-transition.
    """

    UNREGISTERED = "unregistered"
    """Device exists but has no active runtime attachment session."""

    ATTACHING = "attaching"
    """Device is in the process of initial attachment."""

    ATTACHED = "attached"
    """Device has a live runtime attachment session; ready for dispatch."""

    DISPATCHED = "dispatched"
    """V2 has dispatched a task to this participant."""

    EXECUTING = "executing"
    """Participant is actively executing the dispatched task."""

    WAITING_RESULT = "waiting_result"
    """Execution signalled complete; awaiting V2 canonical result acceptance."""

    RESULT_ACCEPTED = "result_accepted"
    """V2 has accepted the participant's execution result."""

    SUSPENDED_STATE = "suspended_state"
    """Participant explicitly suspended from active execution."""

    TAKEOVER_CANDIDATE_STATE = "takeover_candidate_state"
    """Participant pre-qualified as a takeover candidate."""

    TAKING_OVER = "taking_over"
    """Participant is taking over execution from another participant."""

    DEGRADED_STATE = "degraded_state"
    """Participant active but operating in a degraded execution model."""

    RECOVERING = "recovering"
    """Participant is in a recovery/replay cycle after interruption."""

    DETACHED = "detached"
    """Transport connection lost; awaiting reconnect or replacement."""

    TERMINAL = "terminal"
    """Participant has completed all lifecycle phases; no longer active."""


# ---------------------------------------------------------------------------
# State transition trigger enum
# ---------------------------------------------------------------------------


class ParticipantTransitionTrigger(str, Enum):
    """Canonical triggers that cause participant lifecycle state transitions.

    Triggers arrive as evidence from bounded subjects or as V2-internal
    governance decisions.  V2 canonical governance is the sole authority
    for accepting a trigger as valid.
    """

    ATTACH_SUCCESS = "attach_success"
    """Initial attachment completed successfully."""

    ATTACH_FAILURE = "attach_failure"
    """Initial attachment failed."""

    DISPATCH_ISSUED = "dispatch_issued"
    """V2 has issued a dispatch to the participant."""

    EXECUTION_STARTED = "execution_started"
    """Participant has signalled execution start."""

    EXECUTION_COMPLETED = "execution_completed"
    """Participant has signalled execution completion."""

    RESULT_ACCEPTED_BY_CENTER = "result_accepted_by_center"
    """V2 canonical truth chain has accepted the result."""

    SUSPENSION_ORDERED = "suspension_ordered"
    """V2 or operator has ordered participant suspension."""

    SUSPENSION_LIFTED = "suspension_lifted"
    """V2 has lifted the suspension; participant may resume."""

    TAKEOVER_CANDIDATE_NOMINATED = "takeover_candidate_nominated"
    """V2 has nominated the participant as a takeover candidate."""

    TAKEOVER_INITIATED = "takeover_initiated"
    """Takeover execution has been initiated."""

    TAKEOVER_COMPLETED = "takeover_completed"
    """Takeover has completed; participant holds primary execution."""

    CAPABILITY_DEGRADED = "capability_degraded"
    """Participant capability has been classified as degraded by V2."""

    CAPABILITY_RESTORED = "capability_restored"
    """Participant capability has been restored to acceptable level."""

    RECOVERY_INITIATED = "recovery_initiated"
    """Recovery/replay cycle has been initiated for this participant."""

    RECOVERY_COMPLETED = "recovery_completed"
    """Recovery/replay cycle has completed successfully."""

    TRANSPORT_DISCONNECTED = "transport_disconnected"
    """Transport connection to participant has been lost."""

    RECONNECT_SUCCEEDED = "reconnect_succeeded"
    """Transport connection has been re-established."""

    TERMINAL_LOSS = "terminal_loss"
    """Participant has reached a terminal loss state; no recovery possible."""

    TASK_CLOSURE = "task_closure"
    """The task/session has been canonically closed by V2."""


# ---------------------------------------------------------------------------
# State transition descriptor
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParticipantStateTransition:
    """Descriptor for a single allowed participant lifecycle state transition.

    Parameters
    ----------
    from_state:
        Source lifecycle state.
    to_state:
        Target lifecycle state.
    trigger:
        The canonical trigger that causes this transition.
    truth_implication:
        How this transition affects V2 canonical truth (e.g. participant
        truth update required, dispatch slot released, closure eligible).
    closure_implication:
        Whether this transition has a direct implication for task/session
        closure.
    notes:
        Free-text guidance for implementers.
    """

    from_state: ParticipantLifecycleState
    to_state: ParticipantLifecycleState
    trigger: ParticipantTransitionTrigger
    truth_implication: str = ""
    closure_implication: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "trigger": self.trigger.value,
            "truth_implication": self.truth_implication,
            "closure_implication": self.closure_implication,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# Canonical state transition table
# ---------------------------------------------------------------------------

#: Canonical allowed state transitions.  Any transition not in this table
#: is disallowed by V2 canonical governance.
PARTICIPANT_STATE_TRANSITIONS: List[ParticipantStateTransition] = [

    # ── Attach ───────────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.UNREGISTERED,
        to_state=ParticipantLifecycleState.ATTACHING,
        trigger=ParticipantTransitionTrigger.ATTACH_SUCCESS,
        truth_implication="AttachedSessionRegistry entry created; participant truth initialised.",
        notes="Triggered by handle_device_registration in galaxy_gateway.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHING,
        to_state=ParticipantLifecycleState.ATTACHED,
        trigger=ParticipantTransitionTrigger.ATTACH_SUCCESS,
        truth_implication="Participant is now eligible for dispatch slot arbitration.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHING,
        to_state=ParticipantLifecycleState.UNREGISTERED,
        trigger=ParticipantTransitionTrigger.ATTACH_FAILURE,
        truth_implication="No participant truth entry created; dispatch slot not issued.",
        notes="A failed attach must not be silently promoted to attached.",
    ),

    # ── Dispatch ─────────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHED,
        to_state=ParticipantLifecycleState.DISPATCHED,
        trigger=ParticipantTransitionTrigger.DISPATCH_ISSUED,
        truth_implication=(
            "Canonical dispatch slot issued.  Participant truth reflects "
            "pending execution.  Dispatch arbitration record created."
        ),
        notes="Only V2 CanonicalDispatchSlotAuthority may trigger this.",
    ),

    # ── Execution ────────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.DISPATCHED,
        to_state=ParticipantLifecycleState.EXECUTING,
        trigger=ParticipantTransitionTrigger.EXECUTION_STARTED,
        truth_implication=(
            "V2 lifecycle truth binding updated: android_remote_confirmed path "
            "active.  Participant execution phase recorded."
        ),
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.EXECUTING,
        to_state=ParticipantLifecycleState.WAITING_RESULT,
        trigger=ParticipantTransitionTrigger.EXECUTION_COMPLETED,
        truth_implication=(
            "Android execution result uplinked via android_participant_truth_ingress "
            "or unified_result_ingress.  V2 result acceptance pending."
        ),
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.TAKING_OVER,
        to_state=ParticipantLifecycleState.EXECUTING,
        trigger=ParticipantTransitionTrigger.TAKEOVER_COMPLETED,
        truth_implication="Primary execution authority transferred; prior primary demoted.",
        closure_implication="Prior primary's execution result discarded; takeover result is authoritative.",
    ),

    # ── Result acceptance ────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.WAITING_RESULT,
        to_state=ParticipantLifecycleState.RESULT_ACCEPTED,
        trigger=ParticipantTransitionTrigger.RESULT_ACCEPTED_BY_CENTER,
        truth_implication=(
            "V2 task_result_canonical_truth_chain accepted the result.  "
            "Participant truth finalised."
        ),
        closure_implication="Participant eligible for canonical closure after this state.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.RESULT_ACCEPTED,
        to_state=ParticipantLifecycleState.TERMINAL,
        trigger=ParticipantTransitionTrigger.TASK_CLOSURE,
        truth_implication="Canonical closure issued by V2.  Participant lifecycle ends.",
        closure_implication="Task/session closure complete for this participant.",
    ),

    # ── Suspension ───────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHED,
        to_state=ParticipantLifecycleState.SUSPENDED_STATE,
        trigger=ParticipantTransitionTrigger.SUSPENSION_ORDERED,
        truth_implication="Participant removed from dispatch eligibility; truth updated.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.DISPATCHED,
        to_state=ParticipantLifecycleState.SUSPENDED_STATE,
        trigger=ParticipantTransitionTrigger.SUSPENSION_ORDERED,
        truth_implication="Pending dispatch revoked.  Dispatch slot returned.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.SUSPENDED_STATE,
        to_state=ParticipantLifecycleState.ATTACHED,
        trigger=ParticipantTransitionTrigger.SUSPENSION_LIFTED,
        truth_implication="Participant restored to dispatch eligibility.",
    ),

    # ── Takeover ─────────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHED,
        to_state=ParticipantLifecycleState.TAKEOVER_CANDIDATE_STATE,
        trigger=ParticipantTransitionTrigger.TAKEOVER_CANDIDATE_NOMINATED,
        truth_implication="Participant pre-qualified in truth record for takeover.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.TAKEOVER_CANDIDATE_STATE,
        to_state=ParticipantLifecycleState.TAKING_OVER,
        trigger=ParticipantTransitionTrigger.TAKEOVER_INITIATED,
        truth_implication="V2 initiates takeover; LocalTakeoverResult path active.",
    ),

    # ── Degradation ──────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.EXECUTING,
        to_state=ParticipantLifecycleState.DEGRADED_STATE,
        trigger=ParticipantTransitionTrigger.CAPABILITY_DEGRADED,
        truth_implication=(
            "V2 classify_canonical_proof_input_diagnosis returned degraded. "
            "Participant truth updated with degradation reason."
        ),
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.DEGRADED_STATE,
        to_state=ParticipantLifecycleState.EXECUTING,
        trigger=ParticipantTransitionTrigger.CAPABILITY_RESTORED,
        truth_implication="Capability classification restored; participant truth updated.",
    ),

    # ── Recovery ─────────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.DETACHED,
        to_state=ParticipantLifecycleState.RECOVERING,
        trigger=ParticipantTransitionTrigger.RECOVERY_INITIATED,
        truth_implication=(
            "DispatchContinuityContext active; V2 continuity legality gate "
            "evaluating replay eligibility."
        ),
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.RECOVERING,
        to_state=ParticipantLifecycleState.ATTACHED,
        trigger=ParticipantTransitionTrigger.RECOVERY_COMPLETED,
        truth_implication="Recovery complete; participant truth restored and dispatch eligible.",
        closure_implication="Prior interrupted task may be replayed if continuity gate passes.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.RECOVERING,
        to_state=ParticipantLifecycleState.TERMINAL,
        trigger=ParticipantTransitionTrigger.TERMINAL_LOSS,
        truth_implication="Terminal loss; participant truth marked as unrecoverable.",
        closure_implication="Prior task must be rescheduled or closed as terminal.",
    ),

    # ── Disconnect ───────────────────────────────────────────────────────────

    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.ATTACHED,
        to_state=ParticipantLifecycleState.DETACHED,
        trigger=ParticipantTransitionTrigger.TRANSPORT_DISCONNECTED,
        truth_implication="Participant truth marked detached; in-flight execution continuity context preserved.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.EXECUTING,
        to_state=ParticipantLifecycleState.DETACHED,
        trigger=ParticipantTransitionTrigger.TRANSPORT_DISCONNECTED,
        truth_implication=(
            "Participant truth marked detached.  ExecutionInterruptionRecord "
            "created.  Continuity context preserved for recovery."
        ),
        closure_implication="Closure blocked until recovery or terminal loss determination.",
    ),
    ParticipantStateTransition(
        from_state=ParticipantLifecycleState.DETACHED,
        to_state=ParticipantLifecycleState.ATTACHED,
        trigger=ParticipantTransitionTrigger.RECONNECT_SUCCEEDED,
        truth_implication=(
            "handle_device_reconnect classified as continuity_resume.  "
            "runtime_attachment_session_id preserved.  Reconnect count incremented."
        ),
    ),
]


# ---------------------------------------------------------------------------
# Participant record
# ---------------------------------------------------------------------------


@dataclass
class ParticipantRecord:
    """Serialisable record representing a single participant's current state.

    This is a lightweight runtime record for tracking participant state.
    V2 canonical governance maintains the authoritative copy; bounded
    subjects may receive read-only projections.

    Parameters
    ----------
    participant_id:
        Logical participant identifier.
    device_id:
        Underlying device identifier.
    role:
        Current role assigned by V2 governance.
    state:
        Current lifecycle state.
    runtime_attachment_session_id:
        Stable attachment session identity.
    last_transition_trigger:
        The trigger that caused the most recent state transition.
    last_updated:
        Unix timestamp of the most recent state update.
    diagnostics_visible:
        Whether diagnostics for this participant are operator-visible.
    metadata:
        Extension metadata (must not carry canonical truth).
    """

    participant_id: str
    device_id: str
    role: ParticipantRole = ParticipantRole.PRIMARY
    state: ParticipantLifecycleState = ParticipantLifecycleState.UNREGISTERED
    runtime_attachment_session_id: Optional[str] = None
    last_transition_trigger: Optional[ParticipantTransitionTrigger] = None
    last_updated: float = field(default_factory=time.time)
    diagnostics_visible: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "participant_id": self.participant_id,
            "device_id": self.device_id,
            "role": self.role.value,
            "state": self.state.value,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "last_transition_trigger": (
                self.last_transition_trigger.value
                if self.last_transition_trigger
                else None
            ),
            "last_updated": self.last_updated,
            "diagnostics_visible": self.diagnostics_visible,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    def apply_transition(
        self,
        trigger: ParticipantTransitionTrigger,
    ) -> "ParticipantRecord":
        """Return a new ParticipantRecord with the state transitioned by the
        given trigger.

        Raises :class:`ValueError` if the transition is not allowed from the
        current state.  Does not mutate the current record (frozen-safe).

        Parameters
        ----------
        trigger:
            The canonical trigger to apply.

        Returns
        -------
        ParticipantRecord
            New record with updated state and last_transition_trigger.

        Raises
        ------
        ValueError
            If no allowed transition from the current state matches the trigger.
        """
        for t in PARTICIPANT_STATE_TRANSITIONS:
            if t.from_state == self.state and t.trigger == trigger:
                return ParticipantRecord(
                    participant_id=self.participant_id,
                    device_id=self.device_id,
                    role=self.role,
                    state=t.to_state,
                    runtime_attachment_session_id=self.runtime_attachment_session_id,
                    last_transition_trigger=trigger,
                    last_updated=time.time(),
                    diagnostics_visible=self.diagnostics_visible,
                    metadata=dict(self.metadata),
                )
        raise ValueError(
            f"No allowed transition from state={self.state.value!r} "
            f"via trigger={trigger.value!r}"
        )


# ---------------------------------------------------------------------------
# Helper: build participant record
# ---------------------------------------------------------------------------


def build_participant_record(
    participant_id: str,
    device_id: str,
    role: ParticipantRole = ParticipantRole.PRIMARY,
    state: ParticipantLifecycleState = ParticipantLifecycleState.UNREGISTERED,
    runtime_attachment_session_id: Optional[str] = None,
    **metadata: Any,
) -> ParticipantRecord:
    """Convenience factory for building a :class:`ParticipantRecord`."""
    return ParticipantRecord(
        participant_id=participant_id,
        device_id=device_id,
        role=role,
        state=state,
        runtime_attachment_session_id=runtime_attachment_session_id,
        metadata=dict(metadata),
    )


# ---------------------------------------------------------------------------
# Helper: allowed transitions from a given state
# ---------------------------------------------------------------------------


def get_allowed_transitions(
    state: ParticipantLifecycleState,
) -> List[ParticipantStateTransition]:
    """Return all transitions allowed from the given lifecycle state."""
    return [t for t in PARTICIPANT_STATE_TRANSITIONS if t.from_state == state]


# ---------------------------------------------------------------------------
# Schema manifest
# ---------------------------------------------------------------------------


def build_lifecycle_schema_manifest() -> Dict[str, Any]:
    """Return a full serialisable manifest of the participant lifecycle schema."""
    return {
        "sentinel": PARTICIPANT_LIFECYCLE_SCHEMA_SENTINEL,
        "policies": {
            "role_assignment": PARTICIPANT_ROLE_IS_ASSIGNED_BY_CENTER,
            "state_transitions": PARTICIPANT_STATE_TRANSITIONS_ARE_AUTHORITATIVE,
        },
        "roles": [r.value for r in ParticipantRole],
        "states": [s.value for s in ParticipantLifecycleState],
        "triggers": [t.value for t in ParticipantTransitionTrigger],
        "transitions": [t.to_dict() for t in PARTICIPANT_STATE_TRANSITIONS],
    }
