"""core/participant_authority_interfaces.py
==========================================
PR-8: Participant-Generic Authority Interfaces — the contract layer above
Android-specific participant implementations.

Background and motivation
-------------------------
The Galaxy V2 distributed runtime has long expressed Android-specific authority
concepts at layers that are semantically *participant-generic*.  The Android
runtime is the current concrete participant implementation, but the authority
contracts it exposes — session lifecycle phases, dispatch binding states,
result ingress kinds, availability/health semantics, and orchestration-facing
boundaries — describe concepts that belong to *any* participant, not only
Android.

Exposing these contracts exclusively through Android-named types means:

* Architecture-level documentation conflates the participant contract with the
  Android implementation artifact.
* Any future participant platform would require reading Android-specific code
  to understand the participation authority model.
* The orchestration layer's contract vocabulary is unnecessarily coupled to a
  single concrete participant technology.

This module establishes the **participant-generic authority contract layer**
above the concrete Android implementations.  It does NOT duplicate logic,
remove Android support, or create empty wrappers.  Instead it:

1. Names and documents the authority surfaces that are semantically participant-
   generic (session lifecycle, dispatch binding, result ingress, availability).
2. Provides typed generic enumerations whose values map 1-to-1 with the
   Android concrete counterparts, making the generic contract explicit.
3. Declares policy sentinels that constrain how participant authority may be
   expressed at different architectural layers.
4. Provides a registry-style mapping from each generic interface to its
   current concrete Android implementation, so the architecture record is
   consistent even when Android is the only active platform.

Android as the concrete implementation
---------------------------------------
All generic interfaces in this module are currently backed by:

* :mod:`core.android_participant_session_state` — concrete Android session
  lifecycle state machine.
* :mod:`core.android_runtime_dispatch_binding` — concrete Android dispatch
  binding records and state machine.
* :mod:`core.android_participant_truth_ingress` — concrete Android participant
  truth ingress and V2 reconciliation.
* :mod:`core.android_participant_evidence_ingress` — concrete Android
  participant evidence (health/availability) ingestion.

These Android modules are NOT removed or changed in behavior.  They implement
the generic contract defined here.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **No fake abstraction** — every generic concept reflects a real authority
  surface already present in the system.
- **Android-preserving** — the generic layer sits *above* Android; Android
  concrete modules remain the working implementations.
- **Policy-sentinel-first** — authority boundaries are expressed as named,
  importable string sentinels, not implicit conventions.
- **No runtime dependencies** — this module is pure-Python with no imports
  from the Android concrete modules; concrete implementations reference this
  module, not the other way around.

Public API
----------
Authority sentinels::

    PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL
    PARTICIPANT_AUTHORITY_PR8_SENTINEL
    ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL

Policy sentinels::

    PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY
    ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY
    PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY
    PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY
    PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY
    PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY
    PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY
    WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY

Enumerations::

    ParticipantSessionPhase
    ParticipantSessionSignal
    ParticipantDispatchBindingState
    ParticipantDispatchBindingSignal
    ParticipantAvailabilityStatus
    ParticipantResultKind

Concrete implementation registry::

    PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY
    get_concrete_implementation_for(interface_name) -> dict
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Module-level authority sentinels
# ---------------------------------------------------------------------------

PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL: str = (
    "PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL::"
    "core.participant_authority_interfaces::PR-8::"
    "participant-generic-authority-contract-layer-above-android-concrete::"
    "defines-session-lifecycle+dispatch-binding+result-ingress+"
    "availability+orchestration-boundary-contracts::"
    "android-remains-working-concrete-implementation"
)
"""Module identity sentinel.

Import this sentinel to assert that the participant-generic authority
interface layer (PR-8) is present and addressable.
"""

PARTICIPANT_AUTHORITY_PR8_SENTINEL: str = (
    "participant_authority_interfaces::package=PR-8::"
    "pr=generalize-participant-authority-interfaces-above-android::"
    "authority=PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL"
)
"""PR-8 package identity sentinel."""

ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL: str = (
    "ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION::"
    "core.android_participant_session_state+core.android_runtime_dispatch_binding+"
    "core.android_participant_truth_ingress+core.android_participant_evidence_ingress::"
    "android-implements-participant-generic-authority-interfaces-defined-in-PR-8::"
    "android-runtime-support-is-preserved-and-required::"
    "no-other-participant-platform-is-added-or-required-by-this-PR"
)
"""Sentinel documenting that Android is the current concrete participant
implementation beneath the participant-generic interface layer.

The existence of this sentinel as an importable name means the architecture
record explicitly acknowledges Android as the concrete backend rather than
silently treating Android-specific names as the only valid contract.
"""

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY: str = (
    "POLICY::PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE: "
    "The participant authority interface layer (core.participant_authority_interfaces) "
    "sits ABOVE the Android concrete participant modules.  Orchestration-layer code "
    "that reasons about participants SHOULD use the generic types and sentinels "
    "defined here rather than Android-specific names when the concept being "
    "expressed is semantically participant-generic.  Android concrete modules "
    "(core.android_participant_session_state, core.android_runtime_dispatch_binding, "
    "etc.) remain the live implementations and MUST NOT be removed."
)

ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY: str = (
    "POLICY::ANDROID_CONCRETE_MUST_NOT_BE_REMOVED: "
    "The introduction of participant-generic authority interfaces does NOT remove, "
    "destabilize, or deprecate the Android concrete participant modules.  The "
    "Android runtime MUST remain the working concrete participant implementation. "
    "This policy prohibits removing or breaking any Android-backed module as a "
    "consequence of the participant-generic interface lift."
)

PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY: str = (
    "POLICY::PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC: "
    "Participant dispatch authority — the contract deciding which participant "
    "receives a delegated execution task — is semantically participant-generic. "
    "The dispatching layer MUST reason in terms of ParticipantDispatchBindingState "
    "and ParticipantDispatchBindingSignal at the authority contract level, even "
    "though the current concrete implementation is Android-specific via "
    "core.android_runtime_dispatch_binding."
)

PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY: str = (
    "POLICY::PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC: "
    "Participant result ingress — the authority contract for receiving and "
    "reconciling execution results from a remote participant — is semantically "
    "participant-generic.  The result kind taxonomy (ParticipantResultKind) "
    "is the canonical participant-generic contract.  The current concrete "
    "implementation is Android-specific via core.android_participant_truth_ingress, "
    "whose AndroidParticipantTruthKind maps 1-to-1 onto ParticipantResultKind."
)

PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY: str = (
    "POLICY::PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC: "
    "Participant execution slot and session legality — the contract governing "
    "whether a participant session is in a legal state to accept or continue "
    "delegated execution — is semantically participant-generic.  "
    "ParticipantSessionPhase and ParticipantSessionSignal are the canonical "
    "generic lifecycle contracts.  The current concrete implementation is "
    "core.android_participant_session_state, whose AndroidParticipantSessionPhase "
    "and AndroidParticipantSessionSignal map 1-to-1 onto the generic equivalents."
)

PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY: str = (
    "POLICY::PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC: "
    "Participant availability, wake, and health semantics — the contract "
    "expressing whether a participant is reachable, awake, and healthy enough "
    "to accept delegated work — is semantically participant-generic.  "
    "ParticipantAvailabilityStatus is the canonical generic taxonomy.  The "
    "current concrete implementation is core.android_participant_evidence_ingress, "
    "whose AndroidParticipantStatus maps 1-to-1 onto ParticipantAvailabilityStatus."
)

PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY: str = (
    "POLICY::PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC: "
    "The orchestration-facing boundary that separates the V2 orchestration "
    "authority from participant-local execution truth is semantically "
    "participant-generic.  The V2 canonical orchestration authority always "
    "wins conflict resolution against participant-local truth, regardless of "
    "which concrete participant platform (currently Android) is on the "
    "other side of that boundary."
)

WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY: str = (
    "POLICY::WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED: "
    "Authority interfaces, sentinels, docstrings, and architectural comments "
    "that hard-code Android-specific naming at a layer whose semantics are "
    "participant-generic MUST be updated to use participant-generic language.  "
    "Android-specific naming is appropriate at the concrete implementation "
    "layer (core.android_*) and MUST NOT appear in the participant-generic "
    "authority contract layer (this module and modules that import it for "
    "generic contract purposes)."
)

# ---------------------------------------------------------------------------
# ParticipantSessionPhase — generic participant session lifecycle
# ---------------------------------------------------------------------------


class ParticipantSessionPhase(str, Enum):
    """Canonical participant-generic lifecycle phases for a delegated participant
    session as observed from the V2 orchestration host.

    This enum is the participant-generic contract above the concrete
    :class:`~core.android_participant_session_state.AndroidParticipantSessionPhase`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    Phases
    ------
    pre_dispatch
        Session record created; the execution contract has not yet been
        dispatched to the participant.
    contract_dispatched
        The V2 host has dispatched the execution contract to the participant.
        Waiting for acknowledgment or negotiation to begin.
    negotiation_pending
        V2 has issued a takeover / execution-assignment request to the
        participant.  Waiting for the participant's response.
    negotiation_accepted
        The participant accepted the execution-assignment request.
        Execution handover is in progress.
    execution
        Active delegated execution is underway at the participant.
    reconciling
        Terminal signal received (or imminent); reconciliation of V2 canonical
        state with participant-reported truth is in progress.
    terminal_success
        Delegated execution completed successfully and V2 canonical state is
        fully reconciled.  Terminal phase.
    terminal_failure
        Delegated execution failed and V2 canonical state reflects the failure.
        Terminal phase.
    terminal_cancelled
        Delegated execution was cancelled and cancellation is recorded in V2
        canonical state.  Terminal phase.

    Android mapping
    ---------------
    ``pre_dispatch``          ↔ ``AndroidParticipantSessionPhase.pre_dispatch``
    ``contract_dispatched``   ↔ ``AndroidParticipantSessionPhase.handoff_dispatched``
    ``negotiation_pending``   ↔ ``AndroidParticipantSessionPhase.takeover_pending``
    ``negotiation_accepted``  ↔ ``AndroidParticipantSessionPhase.takeover_accepted``
    ``execution``             ↔ ``AndroidParticipantSessionPhase.execution``
    ``reconciling``           ↔ ``AndroidParticipantSessionPhase.reconciling``
    ``terminal_success``      ↔ ``AndroidParticipantSessionPhase.terminal_success``
    ``terminal_failure``      ↔ ``AndroidParticipantSessionPhase.terminal_failure``
    ``terminal_cancelled``    ↔ ``AndroidParticipantSessionPhase.terminal_cancelled``
    """

    pre_dispatch = "pre_dispatch"
    contract_dispatched = "contract_dispatched"
    negotiation_pending = "negotiation_pending"
    negotiation_accepted = "negotiation_accepted"
    execution = "execution"
    reconciling = "reconciling"
    terminal_success = "terminal_success"
    terminal_failure = "terminal_failure"
    terminal_cancelled = "terminal_cancelled"

    def is_terminal(self) -> bool:
        """Return True if this is a terminal (absorbing) phase."""
        return self in (
            ParticipantSessionPhase.terminal_success,
            ParticipantSessionPhase.terminal_failure,
            ParticipantSessionPhase.terminal_cancelled,
        )

    def is_active(self) -> bool:
        """Return True if the session is in an active (non-terminal) phase."""
        return not self.is_terminal()

    @classmethod
    def from_string(cls, value: str) -> "ParticipantSessionPhase":
        """Return the enum member matching *value*, defaulting to
        ``pre_dispatch`` for unrecognised values."""
        if not isinstance(value, str):
            return cls.pre_dispatch
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.pre_dispatch


# ---------------------------------------------------------------------------
# ParticipantSessionSignal — generic session lifecycle signals
# ---------------------------------------------------------------------------


class ParticipantSessionSignal(str, Enum):
    """Canonical participant-generic signals that drive participant session
    phase transitions.

    This enum is the participant-generic contract above the concrete
    :class:`~core.android_participant_session_state.AndroidParticipantSessionSignal`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    Signals
    -------
    contract_dispatched
        The V2 host dispatched the execution contract to the participant.
    negotiation_requested
        The V2 host issued an execution-assignment (takeover) request to the
        participant.
    negotiation_accepted
        The participant accepted the execution-assignment request.
    negotiation_rejected
        The participant rejected the execution-assignment request.
    execution_started
        The participant reported that active execution has begun.
    execution_progressed
        The participant reported in-flight execution progress.
    reconciliation_started
        A terminal signal was received; reconciliation is underway.
    result_success
        Execution completed successfully; reconciliation is finished.
    result_failure
        Execution failed; failure is recorded in V2 canonical state.
    result_cancelled
        Execution was cancelled; cancellation is recorded.

    Android mapping
    ---------------
    ``contract_dispatched``    ↔ ``AndroidParticipantSessionSignal.handoff_dispatched``
    ``negotiation_requested``  ↔ ``AndroidParticipantSessionSignal.takeover_requested``
    ``negotiation_accepted``   ↔ ``AndroidParticipantSessionSignal.takeover_accepted``
    ``negotiation_rejected``   ↔ ``AndroidParticipantSessionSignal.takeover_rejected``
    ``execution_started``      ↔ ``AndroidParticipantSessionSignal.execution_started``
    ``execution_progressed``   ↔ ``AndroidParticipantSessionSignal.execution_progressed``
    ``reconciliation_started`` ↔ ``AndroidParticipantSessionSignal.reconciliation_started``
    ``result_success``         ↔ ``AndroidParticipantSessionSignal.result_success``
    ``result_failure``         ↔ ``AndroidParticipantSessionSignal.result_failure``
    ``result_cancelled``       ↔ ``AndroidParticipantSessionSignal.result_cancelled``
    """

    contract_dispatched = "contract_dispatched"
    negotiation_requested = "negotiation_requested"
    negotiation_accepted = "negotiation_accepted"
    negotiation_rejected = "negotiation_rejected"
    execution_started = "execution_started"
    execution_progressed = "execution_progressed"
    reconciliation_started = "reconciliation_started"
    result_success = "result_success"
    result_failure = "result_failure"
    result_cancelled = "result_cancelled"

    @classmethod
    def from_string(cls, value: str) -> "ParticipantSessionSignal":
        """Return the enum member matching *value*, defaulting to
        ``execution_progressed`` for unrecognised values."""
        if not isinstance(value, str):
            return cls.execution_progressed
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.execution_progressed


# ---------------------------------------------------------------------------
# ParticipantDispatchBindingState — generic dispatch binding lifecycle
# ---------------------------------------------------------------------------


class ParticipantDispatchBindingState(str, Enum):
    """Canonical participant-generic lifecycle states for a participant dispatch
    binding record.

    A dispatch binding record represents the relationship between a V2
    orchestration session, a target participant, and an execution contract.
    This enum is the participant-generic contract above the concrete
    :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeBindingState`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    States
    ------
    unbound
        Identity fields recorded; binding not yet confirmed.
    binding
        Confirmation in progress (e.g. transport handshake).
    bound
        Binding confirmed and ready for dispatch.
    dispatching
        An execution task has been dispatched via this binding.
    suspended
        Binding temporarily suspended (e.g. participant unreachable).
    released
        Binding released; terminal state.  A new binding must be created for
        the next dispatch cycle.

    Android mapping
    ---------------
    ``unbound``     ↔ ``AndroidRuntimeBindingState.unbound``
    ``binding``     ↔ ``AndroidRuntimeBindingState.binding``
    ``bound``       ↔ ``AndroidRuntimeBindingState.bound``
    ``dispatching`` ↔ ``AndroidRuntimeBindingState.dispatching``
    ``suspended``   ↔ ``AndroidRuntimeBindingState.suspended``
    ``released``    ↔ ``AndroidRuntimeBindingState.released``
    """

    unbound = "unbound"
    binding = "binding"
    bound = "bound"
    dispatching = "dispatching"
    suspended = "suspended"
    released = "released"

    def is_terminal(self) -> bool:
        """Return True if this is a terminal (released) state."""
        return self == ParticipantDispatchBindingState.released

    def is_active(self) -> bool:
        """Return True if the binding is in an active (non-released) state."""
        return not self.is_terminal()

    @classmethod
    def from_string(cls, value: str) -> "ParticipantDispatchBindingState":
        """Return the enum member matching *value*, defaulting to ``unbound``."""
        if not isinstance(value, str):
            return cls.unbound
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unbound


# ---------------------------------------------------------------------------
# ParticipantDispatchBindingSignal — generic dispatch binding signals
# ---------------------------------------------------------------------------


class ParticipantDispatchBindingSignal(str, Enum):
    """Canonical participant-generic signals that drive participant dispatch
    binding state transitions.

    This enum is the participant-generic contract above the concrete
    :class:`~core.android_runtime_dispatch_binding.AndroidRuntimeBindingSignal`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    Signals
    -------
    bind
        Initiate binding for the identified participant target.
    confirm
        Confirm the binding (transport / registration confirmed).
    dispatch
        Mark the binding as actively dispatching a task.
    suspend
        Temporarily suspend the binding.
    resume
        Resume a suspended binding.
    release
        Release the binding permanently.

    Android mapping
    ---------------
    ``bind``    ↔ ``AndroidRuntimeBindingSignal.bind``
    ``confirm`` ↔ ``AndroidRuntimeBindingSignal.confirm``
    ``dispatch`` ↔ ``AndroidRuntimeBindingSignal.dispatch``
    ``suspend`` ↔ ``AndroidRuntimeBindingSignal.suspend``
    ``resume``  ↔ ``AndroidRuntimeBindingSignal.resume``
    ``release`` ↔ ``AndroidRuntimeBindingSignal.release``
    """

    bind = "bind"
    confirm = "confirm"
    dispatch = "dispatch"
    suspend = "suspend"
    resume = "resume"
    release = "release"

    @classmethod
    def from_string(cls, value: str) -> "ParticipantDispatchBindingSignal":
        """Return the enum member matching *value*, defaulting to ``bind``."""
        if not isinstance(value, str):
            return cls.bind
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.bind


# ---------------------------------------------------------------------------
# ParticipantAvailabilityStatus — generic participant health/availability
# ---------------------------------------------------------------------------


class ParticipantAvailabilityStatus(str, Enum):
    """Canonical participant-generic availability and health status taxonomy.

    Expresses whether a participant is reachable, awake, and healthy enough
    to accept delegated work.  This enum is the participant-generic contract
    above the concrete
    :class:`~core.android_participant_evidence_ingress.AndroidParticipantStatus`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    Values
    ------
    ready
        Participant is present, operational, and evidence-backed.
    degraded
        Participant is present but reports reduced operational capacity.
    unavailable
        Participant is present but non-operational and cannot accept work.
    recovered
        Participant was previously degraded/unavailable and has recovered.
    missing_evidence
        No readiness evidence was found for this participant.
    malformed_evidence
        Readiness evidence was found but is structurally invalid.
    stale_evidence
        Readiness evidence is present but too old to be trustworthy.
    unverified
        Evidence is present but insufficient to reach a definitive status.

    Android mapping
    ---------------
    ``ready``             ↔ ``AndroidParticipantStatus.ready``
    ``degraded``          ↔ ``AndroidParticipantStatus.degraded``
    ``unavailable``       ↔ ``AndroidParticipantStatus.unavailable``
    ``recovered``         ↔ ``AndroidParticipantStatus.recovered``
    ``missing_evidence``  ↔ ``AndroidParticipantStatus.missing_evidence``
    ``malformed_evidence``↔ ``AndroidParticipantStatus.malformed_evidence``
    ``stale_evidence``    ↔ ``AndroidParticipantStatus.stale_evidence``
    ``unverified``        ↔ ``AndroidParticipantStatus.unverified``
    """

    ready = "ready"
    degraded = "degraded"
    unavailable = "unavailable"
    recovered = "recovered"
    missing_evidence = "missing_evidence"
    malformed_evidence = "malformed_evidence"
    stale_evidence = "stale_evidence"
    unverified = "unverified"

    def is_operational(self) -> bool:
        """Return True iff the participant is considered operational
        (ready or recovered)."""
        return self in (
            ParticipantAvailabilityStatus.ready,
            ParticipantAvailabilityStatus.recovered,
        )

    def is_evidence_gap(self) -> bool:
        """Return True iff the status reflects an evidence gap rather than
        a participant-reported condition."""
        return self in (
            ParticipantAvailabilityStatus.missing_evidence,
            ParticipantAvailabilityStatus.malformed_evidence,
            ParticipantAvailabilityStatus.stale_evidence,
            ParticipantAvailabilityStatus.unverified,
        )

    @classmethod
    def from_string(cls, value: str) -> "ParticipantAvailabilityStatus":
        """Return the enum member matching *value*, defaulting to
        ``missing_evidence`` (fail-conservative) for unrecognised values."""
        if not isinstance(value, str):
            return cls.missing_evidence
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.missing_evidence


# ---------------------------------------------------------------------------
# ParticipantResultKind — generic participant result/truth ingress kinds
# ---------------------------------------------------------------------------


class ParticipantResultKind(str, Enum):
    """Canonical participant-generic taxonomy for the kind of inbound
    participant truth / result being ingested.

    This enum is the participant-generic contract above the concrete
    :class:`~core.android_participant_truth_ingress.AndroidParticipantTruthKind`
    implementation.  Every value maps 1-to-1 to the Android concrete enum.

    Values
    ------
    session_snapshot
        Participant-side local session state snapshot.
    readiness_assessment
        Participant-side per-device readiness assessment.
    task_phase
        Participant-side current task lifecycle phase.
    runtime_state
        Participant-side execution runtime state.
    cancel
        Explicit cancel signal originating from the participant.
    status
        Task status update from the participant (maps to a progress signal).
    failure
        Explicit failure/error report from the participant.
    result
        Final task result from the participant (success or failure with
        payload).
    reconciliation_signal
        Explicit state-reconciliation push from the participant's runtime
        controller.
    governance_artifact
        Participant-originated evaluator artifact (governance, readiness,
        acceptance, strategy).
    unknown
        Unrecognised truth kind; handled as advisory/audit-only.

    Android mapping
    ---------------
    ``session_snapshot``     ↔ ``AndroidParticipantTruthKind.session_snapshot``
    ``readiness_assessment`` ↔ ``AndroidParticipantTruthKind.readiness_assessment``
    ``task_phase``           ↔ ``AndroidParticipantTruthKind.task_phase``
    ``runtime_state``        ↔ ``AndroidParticipantTruthKind.runtime_state``
    ``cancel``               ↔ ``AndroidParticipantTruthKind.cancel``
    ``status``               ↔ ``AndroidParticipantTruthKind.status``
    ``failure``              ↔ ``AndroidParticipantTruthKind.failure``
    ``result``               ↔ ``AndroidParticipantTruthKind.result``
    ``reconciliation_signal``↔ ``AndroidParticipantTruthKind.reconciliation_signal``
    ``governance_artifact``  ↔ ``AndroidParticipantTruthKind.governance_artifact``
    ``unknown``              ↔ ``AndroidParticipantTruthKind.unknown``
    """

    session_snapshot = "session_snapshot"
    readiness_assessment = "readiness_assessment"
    task_phase = "task_phase"
    runtime_state = "runtime_state"
    cancel = "cancel"
    status = "status"
    failure = "failure"
    result = "result"
    reconciliation_signal = "reconciliation_signal"
    governance_artifact = "governance_artifact"
    unknown = "unknown"

    def is_terminal_signal(self) -> bool:
        """Return True iff this kind carries a terminal execution outcome."""
        return self in (
            ParticipantResultKind.cancel,
            ParticipantResultKind.failure,
            ParticipantResultKind.result,
            ParticipantResultKind.reconciliation_signal,
        )

    def affects_canonical_state(self) -> bool:
        """Return True iff this kind materially updates V2 canonical
        orchestration state."""
        return self in (
            ParticipantResultKind.cancel,
            ParticipantResultKind.failure,
            ParticipantResultKind.result,
            ParticipantResultKind.status,
            ParticipantResultKind.task_phase,
            ParticipantResultKind.reconciliation_signal,
            ParticipantResultKind.governance_artifact,
        )

    @classmethod
    def from_string(cls, value: str) -> "ParticipantResultKind":
        """Return the enum member matching *value*, defaulting to
        ``unknown`` for unrecognised values."""
        if not isinstance(value, str):
            return cls.unknown
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.unknown


# ---------------------------------------------------------------------------
# Concrete implementation registry
# ---------------------------------------------------------------------------

PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY: Dict[str, Dict[str, Any]] = {
    "session_lifecycle": {
        "generic_interface": "ParticipantSessionPhase + ParticipantSessionSignal",
        "concrete_module": "core.android_participant_session_state",
        "concrete_phase_class": "AndroidParticipantSessionPhase",
        "concrete_signal_class": "AndroidParticipantSessionSignal",
        "concrete_record_class": "AndroidParticipantSessionRecord",
        "concrete_runtime_class": "AndroidParticipantSessionRuntime",
        "platform": "android",
        "pr": "PR-11-V2",
        "notes": (
            "Android session lifecycle state machine.  AndroidParticipantSessionPhase "
            "maps 1-to-1 onto ParticipantSessionPhase; note that "
            "'contract_dispatched' is 'handoff_dispatched' in the Android concrete "
            "and 'negotiation_pending/accepted' are 'takeover_pending/accepted'."
        ),
    },
    "dispatch_binding": {
        "generic_interface": (
            "ParticipantDispatchBindingState + ParticipantDispatchBindingSignal"
        ),
        "concrete_module": "core.android_runtime_dispatch_binding",
        "concrete_state_class": "AndroidRuntimeBindingState",
        "concrete_signal_class": "AndroidRuntimeBindingSignal",
        "concrete_record_class": "AndroidRuntimeDispatchBindingRecord",
        "concrete_runtime_class": "AndroidRuntimeDispatchBindingRuntime",
        "platform": "android",
        "pr": "PR-11",
        "notes": (
            "Android dispatch binding record and state machine.  "
            "AndroidRuntimeBindingState maps 1-to-1 onto "
            "ParticipantDispatchBindingState."
        ),
    },
    "result_ingress": {
        "generic_interface": "ParticipantResultKind",
        "concrete_module": "core.android_participant_truth_ingress",
        "concrete_kind_class": "AndroidParticipantTruthKind",
        "concrete_envelope_class": "AndroidParticipantTruthEnvelope",
        "concrete_outcome_class": "AndroidParticipantReconcileOutcome",
        "platform": "android",
        "pr": "PR-4V2",
        "notes": (
            "Android participant truth ingress and V2 canonical reconciliation.  "
            "AndroidParticipantTruthKind maps 1-to-1 onto ParticipantResultKind."
        ),
    },
    "availability": {
        "generic_interface": "ParticipantAvailabilityStatus",
        "concrete_module": "core.android_participant_evidence_ingress",
        "concrete_status_class": "AndroidParticipantStatus",
        "concrete_result_class": "AndroidParticipantEvidenceResult",
        "platform": "android",
        "pr": "PR-evidence-ingress",
        "notes": (
            "Android participant evidence ingestion and health/availability "
            "normalization.  AndroidParticipantStatus maps 1-to-1 onto "
            "ParticipantAvailabilityStatus."
        ),
    },
}
"""Registry mapping each participant-generic authority interface to its
current concrete Android implementation module and classes.

This registry is the canonical architecture record documenting that:

* The participant-generic authority interfaces are real architectural
  boundaries, not empty wrappers.
* The current concrete implementation for every interface is Android-backed.
* The Android modules are the expected, working implementations.

Orchestration layers and release gates MAY consult this registry to
assert implementation completeness.
"""


def get_concrete_implementation_for(interface_name: str) -> Optional[Dict[str, Any]]:
    """Return the concrete implementation registry entry for *interface_name*.

    Parameters
    ----------
    interface_name:
        One of ``"session_lifecycle"``, ``"dispatch_binding"``,
        ``"result_ingress"``, ``"availability"``.

    Returns
    -------
    dict or None
        Registry dict if found, otherwise None.
    """
    return PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY.get(interface_name)


# ---------------------------------------------------------------------------
# Aggregate policy sentinel tuple (for test introspection)
# ---------------------------------------------------------------------------

_ALL_POLICY_SENTINELS: tuple = (
    PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY,
    ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY,
    PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY,
    PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY,
    WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY,
)

__all__ = [
    # Authority sentinels
    "PARTICIPANT_AUTHORITY_INTERFACES_SENTINEL",
    "PARTICIPANT_AUTHORITY_PR8_SENTINEL",
    "ANDROID_IS_CONCRETE_PARTICIPANT_IMPLEMENTATION_SENTINEL",
    # Policy sentinels
    "PARTICIPANT_GENERIC_LAYER_IS_ABOVE_ANDROID_CONCRETE_POLICY",
    "ANDROID_CONCRETE_MUST_NOT_BE_REMOVED_POLICY",
    "PARTICIPANT_DISPATCH_AUTHORITY_IS_PARTICIPANT_GENERIC_POLICY",
    "PARTICIPANT_RESULT_INGRESS_IS_PARTICIPANT_GENERIC_POLICY",
    "PARTICIPANT_SESSION_LEGALITY_IS_PARTICIPANT_GENERIC_POLICY",
    "PARTICIPANT_AVAILABILITY_IS_PARTICIPANT_GENERIC_POLICY",
    "PARTICIPANT_ORCHESTRATION_BOUNDARY_IS_PARTICIPANT_GENERIC_POLICY",
    "WRONG_LAYER_ANDROID_NAMING_MUST_BE_LIFTED_POLICY",
    # Enumerations
    "ParticipantSessionPhase",
    "ParticipantSessionSignal",
    "ParticipantDispatchBindingState",
    "ParticipantDispatchBindingSignal",
    "ParticipantAvailabilityStatus",
    "ParticipantResultKind",
    # Concrete implementation registry
    "PARTICIPANT_CONCRETE_IMPLEMENTATION_REGISTRY",
    "get_concrete_implementation_for",
]
