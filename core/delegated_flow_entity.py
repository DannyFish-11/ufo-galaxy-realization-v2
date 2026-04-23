"""core/delegated_flow_entity.py
================================
PR package 50 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Unified Delegated Flow Entity — Cross-Device First-Class Citizen.

This module is the **canonical authority** for the unified *delegated flow*
concept that spans the V2 orchestration side and the Android execution side.
It introduces a stable, typed flow entity that explicitly captures the
relationship between:

- a V2-side canonical orchestration intent (``CanonicalTask``,
  ``DelegatedRuntimeDispatchIntent``, ``DelegatedHandoffContractRecord``,
  ``AndroidRuntimeDispatchBindingRecord``), and
- an Android-side local execution chain
  (``DelegatedRuntimeUnit`` / ``DelegatedActivationRecord`` /
  ``AutonomousExecutionPipeline`` / ``LoopController`` etc.)

so that "the same delegated flow" can be unambiguously identified, tracked,
and reasoned about from both sides of the cross-device boundary.

Background
----------
The system already contains a real cross-device execution chain:

* V2 side: ``CanonicalTask`` → ``CommandRouter`` →
  ``DelegatedRuntimeDispatchIntent`` → ``DelegatedHandoffContractRecord`` →
  ``AndroidRuntimeDispatchBindingRecord`` — routing, delegation, binding, and
  dispatch.
* Android side: ``DelegatedRuntimeUnit`` / ``DelegatedActivationRecord`` /
  ``AutonomousExecutionPipeline`` / ``LoopController`` /
  ``LocalCollaborationAgent`` / ``DelegatedTakeoverExecutor`` — device-side
  local agent flow.

However, these two sub-chains live in separate models and are never united
under a single, system-level *flow* object.  As a result the system cannot
stably answer:

- Which object is the single canonical representation of "the same flow" as
  seen from both sides?
- What is the current unified phase of the flow?
- What is the flow's lineage (its ancestry across task_assign,
  goal_execution, parallel_subtask, and takeover_request origins)?
- Who is the *truth owner* — the V2 orchestration layer (canonical flow
  truth) or the Android side (execution truth)?
- Around which object should continuity / replay / result merge / operator
  visibility be built?

PR-50 closes this gap by introducing a single, stable, typed
:class:`DelegatedFlowEntity` that is the **system-level first-class citizen**
for any work delegated from the V2 central network to a device-side Android
runtime surface.

Design
------
The design follows four principles that align with the existing PR chain:

1. **Flow identity is immutable**: ``delegated_flow_id``, ``flow_lineage_id``,
   and ``flow_segment_id`` are set at creation time and never change.
2. **Flow phase is monotonically advancing**: :class:`DelegatedFlowPhase`
   advances via :class:`DelegatedFlowSignal` through the canonical
   transition table.  Regression is rejected.
3. **Flow truth is dual-owned**: V2 holds the *canonical flow truth*
   (orchestration authority); Android holds the *execution truth*
   (device-scope execution state).  Neither side unilaterally overrides the
   other for its respective scope.
4. **Flow family is unified**: ``task_assign``, ``goal_execution``,
   ``parallel_subtask``, and ``takeover_request`` are all modelled as
   distinct :class:`DelegatedFlowKind` values, so any delegated work — no
   matter its origin type — belongs to the delegated flow family and is
   captured in the same ring-buffer.

PR-50 introduces
----------------
1. :class:`DelegatedFlowKind` — canonical enum classifying the origin type
   of a delegated flow (``task_assign``, ``goal_execution``,
   ``parallel_subtask``, ``takeover_request``).
2. :class:`DelegatedFlowPhase` — canonical enum for the unified flow-level
   state machine (``created`` → ``dispatched`` → ``executing`` →
   ``reconciling`` → ``completed`` / ``failed`` / ``cancelled`` /
   ``suspended``).
3. :class:`DelegatedFlowSignal` — canonical enum for the signals that drive
   flow phase transitions.
4. :class:`DelegatedFlowOwnerKind` — canonical enum for the two truth-owner
   roles (``v2_canonical`` / ``android_execution``).
5. :class:`DelegatedFlowIdentity` — stable, serialisable identity record
   carrying ``delegated_flow_id``, ``flow_lineage_id``, ``flow_segment_id``,
   ``trace_id``, and ``flow_kind``.
6. :class:`DelegatedFlowOwnership` — record describing who holds canonical
   flow truth vs. execution truth, and the rationale.
7. :class:`DelegatedFlowObjectMapping` — explicit mapping from a
   :class:`DelegatedFlowEntity` to the four existing objects that represent
   the same flow in the current system: ``canonical_task_id``,
   ``dispatch_record_id``, ``contract_id``, ``binding_id``.
8. :class:`DelegatedFlowExtensionPoints` — forward-compatible placeholder
   for continuity, replay, result convergence, and operator visibility hooks
   that will be established by subsequent PRs.
9. :class:`DelegatedFlowEntity` — the unified, canonical top-level flow
   record aggregating identity, phase, ownership, object mapping, and
   extension points.
10. :class:`DelegatedFlowEntityRecord` — ring-buffer entry (phase + timestamp
    + entity snapshot) for audit and observability.
11. :class:`DelegatedFlowEntitySnapshot` — point-in-time snapshot of all
    active flow entities.
12. :class:`DelegatedFlowEntityRuntime` — in-process ring-buffer singleton
    (128 entries) accumulating flow entities across the process lifetime.
13. :func:`create_delegated_flow_entity` — creates a canonical
    :class:`DelegatedFlowEntity` from identity and object-mapping inputs.
14. :func:`advance_flow_phase` — returns a new entity with the flow phase
    advanced according to the given :class:`DelegatedFlowSignal`.
15. :func:`attach_object_mapping` — returns a new entity with an updated
    :class:`DelegatedFlowObjectMapping` (non-destructive).
16. :func:`record_delegated_flow` — persists an entity to the ring-buffer.
17. :func:`get_delegated_flow` — retrieves the most recent entity for a
    given ``delegated_flow_id``.
18. :func:`get_delegated_flow_by_lineage` — retrieves all entities sharing
    a ``flow_lineage_id``.
19. :func:`get_delegated_flow_by_contract` — retrieves the most recent
    entity whose object mapping carries a given ``contract_id``.
20. :func:`list_active_delegated_flows` — returns all non-terminal entities,
    newest-first.
21. :func:`build_delegated_flow_snapshot` — assembles a
    :class:`DelegatedFlowEntitySnapshot`.
22. :func:`get_delegated_flow_entity_runtime` /
    :func:`reset_delegated_flow_entity_runtime` — singleton accessor and
    test-isolation helper.
23. Fourteen policy sentinels documenting canonical delegated-flow rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Flow-first** — the :class:`DelegatedFlowEntity` is the system-level
  first-class citizen; all existing objects (CanonicalTask, dispatch records,
  contracts, bindings) are mapped *into* it, not replaced by it.
- **Kind-unified** — ``task_assign``, ``goal_execution``,
  ``parallel_subtask``, and ``takeover_request`` are all members of the same
  :class:`DelegatedFlowKind` family.
- **Phase-monotonic** — :class:`DelegatedFlowPhase` advances predictably
  via the signal-driven transition table; illegal transitions leave the
  state unchanged rather than raising.
- **Dual-truth** — V2 holds canonical flow truth (orchestration authority);
  Android holds execution truth (device scope).  This is encoded in
  :class:`DelegatedFlowOwnership` and enforced by policy sentinels.
- **Lineage-trackable** — ``flow_lineage_id`` lets operators trace the full
  ancestry of a flow across task_assign → goal_execution → parallel_subtask
  chains.
- **Extension-ready** — :class:`DelegatedFlowExtensionPoints` provides a
  stable forward-compatible hook surface for continuity, replay, result
  convergence, and operator visibility, without embedding these concerns in
  the core entity.
- **Fully serialisable** — all dataclasses expose ``to_dict()`` /
  ``to_json()`` and ``from_dict()`` for stable, round-trippable wire
  representations.

Relationship to other PR packages
----------------------------------
* PR-7  (``core.attached_runtime_session``) — the session identity that
  anchors the dispatch is propagated into the ``DelegatedFlowObjectMapping``
  via the dispatch record.
* PR-8  (``core.delegated_runtime_dispatch_intent``) — the dispatch record
  id feeds into ``DelegatedFlowObjectMapping.dispatch_record_id``.
* PR-9  (``core.delegated_runtime_handoff_contract``) — the contract id
  feeds into ``DelegatedFlowObjectMapping.contract_id``.
* PR-10 (``core.delegated_runtime_execution_tracker``) — the tracker id
  feeds into ``DelegatedFlowObjectMapping.tracker_id``.
* PR-11 (``core.android_runtime_dispatch_binding``) — the binding id feeds
  into ``DelegatedFlowObjectMapping.binding_id``.
* PR-13 (``core.android_execution_signal_reconciler``) — signal reconcile
  outcomes are associated with a flow via ``contract_id``; the flow entity
  provides the lineage context for reconcile records.
* PR-16 (``core.android_delegated_signal_ingress``) — inbound delegated
  execution signals carry ``contract_id`` and ``task_id``; the flow entity
  lookup-by-contract surfaces the unified flow for those signals.
* PR-21 (``core.delegated_execution_ingress_reconciliation_closure``) —
  ingress reconciliation closure uses contract/session identity; the flow
  entity is the stable parent for those lookups.
* PR-A  (``core.canonical_task``) — the ``CanonicalTask.task_id`` feeds into
  ``DelegatedFlowObjectMapping.canonical_task_id``.

Public API
----------
Sentinels::

    DELEGATED_FLOW_ENTITY_AUTHORITY
    DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY
    FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY
    FLOW_PHASE_IS_MONOTONIC_POLICY
    FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY
    V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY
    ANDROID_HOLDS_EXECUTION_TRUTH_POLICY
    FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY
    FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY
    TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY
    FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY
    EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY
    FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY
    DELEGATED_FLOW_ENTITY_PR50_SENTINEL

Enums::

    DelegatedFlowKind
    DelegatedFlowPhase
    DelegatedFlowSignal
    DelegatedFlowOwnerKind

Dataclasses::

    DelegatedFlowIdentity
    DelegatedFlowOwnership
    DelegatedFlowObjectMapping
    DelegatedFlowExtensionPoints
    DelegatedFlowEntity
    DelegatedFlowEntityRecord
    DelegatedFlowEntitySnapshot

Runtime / ring-buffer::

    DelegatedFlowEntityRuntime

Functions::

    create_delegated_flow_entity
    advance_flow_phase
    attach_object_mapping
    record_delegated_flow
    get_delegated_flow
    get_delegated_flow_by_lineage
    get_delegated_flow_by_contract
    list_active_delegated_flows
    build_delegated_flow_snapshot
    get_delegated_flow_entity_runtime
    reset_delegated_flow_entity_runtime
"""

from __future__ import annotations

import json
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

DELEGATED_FLOW_ENTITY_AUTHORITY: str = (
    "DELEGATED_FLOW_ENTITY_AUTHORITY::"
    "core.delegated_flow_entity is the canonical authority for the unified "
    "delegated flow entity that spans the V2 orchestration side and the "
    "Android execution side.  Any work delegated from the V2 central network "
    "to a device-side Android runtime surface MUST be represented as a "
    "DelegatedFlowEntity so that cross-device flow identity, lineage, phase, "
    "and truth ownership are unambiguous from creation through completion."
)

DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY: str = (
    "POLICY::DELEGATED_FLOW_ID_IS_IMMUTABLE: the delegated_flow_id, "
    "flow_lineage_id, and flow_segment_id fields of a DelegatedFlowIdentity "
    "are set at creation time and MUST NOT change across phase transitions or "
    "object mapping updates.  Any operation that needs a new flow id must "
    "create a new DelegatedFlowEntity via create_delegated_flow_entity()."
)

FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY: str = (
    "POLICY::FLOW_LINEAGE_ID_SPANS_BOTH_SIDES: the flow_lineage_id MUST be "
    "the same value on both the V2 side (DelegatedFlowEntity) and the Android "
    "side (DelegatedRuntimeUnit/DelegatedActivationRecord).  It is the "
    "stable shared key that lets operators correlate a V2 canonical flow "
    "record with its Android-side execution record without resolving through "
    "contract_id or session_id indirection."
)

FLOW_PHASE_IS_MONOTONIC_POLICY: str = (
    "POLICY::FLOW_PHASE_IS_MONOTONIC: DelegatedFlowPhase advances "
    "predictably via DelegatedFlowSignal through the canonical transition "
    "table defined in this module.  Attempts to advance from a terminal "
    "phase (completed, failed, cancelled) are silently rejected and the "
    "phase remains unchanged.  Callers must not construct entities with "
    "arbitrary phase values outside the transition table."
)

FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY: str = (
    "POLICY::FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK: task_assign, "
    "goal_execution, parallel_subtask, and takeover_request are all valid "
    "DelegatedFlowKind values and MUST be modelled as DelegatedFlowEntity "
    "instances in the ring-buffer.  No delegated work origin type is exempt "
    "from the unified flow model."
)

V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY: str = (
    "POLICY::V2_HOLDS_CANONICAL_FLOW_TRUTH: the V2 orchestration layer is "
    "the canonical authority for flow identity, lineage, phase transitions, "
    "and object mappings (CanonicalTask / dispatch / contract / binding ids).  "
    "Android-side state is advisory for the device scope only; it does not "
    "supersede V2 canonical flow truth."
)

ANDROID_HOLDS_EXECUTION_TRUTH_POLICY: str = (
    "POLICY::ANDROID_HOLDS_EXECUTION_TRUTH: the Android runtime holds "
    "execution truth for the device-scope portion of a delegated flow.  "
    "Android-originated signals (ack, progress, result, error) are the "
    "authoritative source for execution phase events within the device "
    "scope, and V2 MUST reconcile them into the canonical flow phase "
    "rather than ignoring or overwriting them."
)

FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY: str = (
    "POLICY::FLOW_OBJECT_MAPPING_IS_ADDITIVE: DelegatedFlowObjectMapping "
    "fields are populated incrementally as each downstream object is "
    "created (dispatch record → contract → binding → tracker).  A mapping "
    "field being empty-string does not invalidate the flow entity; it "
    "simply means that downstream object has not yet been created.  "
    "attach_object_mapping() is the non-destructive update path."
)

FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY: str = (
    "POLICY::FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN: DelegatedFlowEntity "
    "is NOT a wrapper or alias for CanonicalTask, dispatch records, "
    "contracts, or bindings.  It is a system-level first-class citizen that "
    "maps to those objects.  Tracking, signal reconciliation, truth ingress, "
    "and operator visibility SHOULD reference the delegated_flow_id as the "
    "primary key, falling back to contract_id / session_id only when "
    "flow_id is unavailable."
)

TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY: str = (
    "POLICY::TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT: once a "
    "DelegatedFlowEntity reaches a terminal phase (completed, failed, "
    "cancelled) no further DelegatedFlowSignal may advance its phase.  "
    "Callers that need to retry or restart a flow must create a new "
    "DelegatedFlowEntity — possibly with the same flow_lineage_id to "
    "preserve lineage continuity."
)

FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY: str = (
    "POLICY::FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY: a "
    "flow_lineage_id may span multiple DelegatedFlowKind values within "
    "the same logical work unit (e.g. a task_assign that spawns a "
    "parallel_subtask that transitions to a takeover_request all share "
    "the same flow_lineage_id).  flow_segment_id distinguishes individual "
    "segments within the lineage."
)

EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY: str = (
    "POLICY::EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE: "
    "DelegatedFlowExtensionPoints is a stable, forward-compatible surface "
    "reserved for continuity, replay, result convergence, and operator "
    "visibility hooks.  Fields added to this class in subsequent PRs MUST "
    "default to None or empty so that existing serialised entities remain "
    "fully round-trippable."
)

FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY: str = (
    "POLICY::FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED: V2 canonical flow "
    "truth and Android execution truth are scope-separated.  V2 does not "
    "claim authority over device-local execution details; Android does not "
    "claim authority over flow identity or orchestration decisions.  "
    "DelegatedFlowOwnership.canonical_owner is always v2_canonical; "
    "DelegatedFlowOwnership.execution_owner is always android_execution "
    "once dispatch has occurred."
)

DELEGATED_FLOW_ENTITY_PR50_SENTINEL: str = (
    "DELEGATED_FLOW_ENTITY_PR50_SENTINEL::package=50 "
    "track=post-533-dual-repo-runtime-unification "
    "repo=main "
    "module=core.delegated_flow_entity "
    "title=unified-delegated-flow-entity-cross-device-first-class-citizen"
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ALL_POLICY_SENTINELS = (
    DELEGATED_FLOW_ENTITY_AUTHORITY,
    DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY,
    FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY,
    FLOW_PHASE_IS_MONOTONIC_POLICY,
    FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY,
    V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY,
    ANDROID_HOLDS_EXECUTION_TRUTH_POLICY,
    FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY,
    FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY,
    TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY,
    FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY,
    EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY,
    FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY,
    DELEGATED_FLOW_ENTITY_PR50_SENTINEL,
)

_RING_BUFFER_SIZE: int = 128

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class DelegatedFlowKind(str, Enum):
    """Canonical enum classifying the origin type of a delegated flow.

    Each value corresponds to one of the delegated work origin types that
    the V2 central network can dispatch to an Android runtime surface.

    Values
    ------
    task_assign
        A standard task-assign delegation.  The Android device is assigned
        to execute a well-scoped task.  Corresponds to AIP TASK_ASSIGN
        message type.
    goal_execution
        A goal-level execution delegation.  The Android device is asked
        to drive a multi-step goal-execution pipeline autonomously.
    parallel_subtask
        A parallel subtask within a broader orchestration plan.  Multiple
        parallel_subtask flows may share the same flow_lineage_id.
    takeover_request
        A takeover delegation.  The Android device takes over an in-flight
        session or work unit that was previously handled by another surface
        or has been escalated.
    unknown
        Origin type is not yet determined or not representable by the
        canonical values above.  Used as a safe default.
    """

    task_assign = "task_assign"
    goal_execution = "goal_execution"
    parallel_subtask = "parallel_subtask"
    takeover_request = "takeover_request"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedFlowKind":
        """Return the enum member matching *value*, defaulting to ``unknown``."""
        if not isinstance(value, str):
            return cls.unknown
        normalised = value.lower().strip()
        try:
            return cls(normalised)
        except ValueError:
            return cls.unknown


class DelegatedFlowPhase(str, Enum):
    """Canonical flow-level state machine for a delegated flow entity.

    The canonical phase sequence for a successfully executing flow is::

        created → dispatched → executing → reconciling → completed

    Terminal phases (``completed``, ``failed``, ``cancelled``) block any
    further phase advancement.  ``suspended`` is a transient hold state
    from which the flow may resume to ``executing`` or be cancelled.

    Values
    ------
    created
        The DelegatedFlowEntity has been created on the V2 side.  The flow
        has not yet been dispatched to the Android runtime.  Object mapping
        fields may be partially populated (e.g. canonical_task_id only).
    dispatched
        The delegated payload (handoff contract + binding) has been sent to
        the Android runtime surface.  V2 is awaiting an acknowledgment.
    executing
        The Android runtime has acknowledged the flow and is executing it.
        Execution-truth is now held by the Android side.
    reconciling
        The Android runtime has produced a result (success or failure) and
        V2 is in the process of reconciling it into canonical flow state.
        This corresponds to the PR-13/PR-16/PR-21 signal reconcile path.
    completed
        The flow completed successfully and its result has been reconciled
        into V2 canonical state.  Terminal.
    failed
        The flow encountered an unrecoverable error.  Terminal.
    cancelled
        The flow was explicitly cancelled before or during execution.
        Terminal.
    suspended
        The flow is temporarily suspended (e.g. the Android session became
        unavailable).  May resume to ``executing`` when connectivity is
        re-established, or be cancelled.
    """

    created = "created"
    dispatched = "dispatched"
    executing = "executing"
    reconciling = "reconciling"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    suspended = "suspended"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "DelegatedFlowPhase" = None,
    ) -> "DelegatedFlowPhase":
        """Return the enum member matching *value*, or *default* / ``created``."""
        if default is None:
            default = cls.created
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default

    def is_terminal(self) -> bool:
        """Return True if the phase is a terminal state."""
        return self in (
            DelegatedFlowPhase.completed,
            DelegatedFlowPhase.failed,
            DelegatedFlowPhase.cancelled,
        )

    def is_active(self) -> bool:
        """Return True if the flow is in an active (non-terminal) phase."""
        return not self.is_terminal()

    def is_executing_or_later(self) -> bool:
        """Return True if Android execution has begun (executing, reconciling, or terminal)."""
        return self in (
            DelegatedFlowPhase.executing,
            DelegatedFlowPhase.reconciling,
            DelegatedFlowPhase.completed,
            DelegatedFlowPhase.failed,
            DelegatedFlowPhase.cancelled,
            DelegatedFlowPhase.suspended,
        )


class DelegatedFlowSignal(str, Enum):
    """Canonical signals that drive delegated flow phase transitions.

    Values
    ------
    dispatch
        V2 has sent the delegated payload to the Android runtime.
        ``created`` → ``dispatched``.
    ack
        Android runtime has acknowledged receipt of the delegated payload.
        ``dispatched`` → ``executing``.
    result_inbound
        Android runtime has emitted a result signal (progress/success/failure)
        that is now being reconciled on the V2 side.
        ``executing`` → ``reconciling``.
    reconcile_complete
        V2 has finished reconciling the Android result into canonical state.
        ``reconciling`` → ``completed`` (success) or ``failed`` (failure).
    fail
        An unrecoverable error occurred at any non-terminal phase.
        Any non-terminal → ``failed``.
    cancel
        The flow was explicitly cancelled.
        Any non-terminal → ``cancelled``.
    suspend
        The Android session became temporarily unavailable.
        ``dispatched`` / ``executing`` → ``suspended``.
    resume
        Connectivity to the Android session was re-established.
        ``suspended`` → ``executing``.
    result_success
        Shortcut signal: Android reported successful completion and
        reconciliation is trivially complete.
        ``reconciling`` → ``completed``.
    result_failure
        Shortcut signal: Android reported a failure and reconciliation
        confirmed it.
        ``reconciling`` → ``failed``.
    """

    dispatch = "dispatch"
    ack = "ack"
    result_inbound = "result_inbound"
    reconcile_complete = "reconcile_complete"
    fail = "fail"
    cancel = "cancel"
    suspend = "suspend"
    resume = "resume"
    result_success = "result_success"
    result_failure = "result_failure"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "DelegatedFlowSignal" = None,
    ) -> "DelegatedFlowSignal":
        """Return the enum member matching *value*, or *default* / ``fail``."""
        if default is None:
            default = cls.fail
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


class DelegatedFlowOwnerKind(str, Enum):
    """Canonical enum for the two truth-owner roles in a delegated flow.

    Values
    ------
    v2_canonical
        The V2 orchestration layer.  Holds canonical flow truth: flow
        identity, lineage, phase transitions, and object mappings.
    android_execution
        The Android runtime surface.  Holds execution truth: device-scope
        execution state, local loop progress, and result signals.
    none
        No owner has been assigned (pre-dispatch state).
    """

    v2_canonical = "v2_canonical"
    android_execution = "android_execution"
    none = "none"

    @classmethod
    def from_string(cls, value: str) -> "DelegatedFlowOwnerKind":
        """Return the enum member matching *value*, defaulting to ``none``."""
        if not isinstance(value, str):
            return cls.none
        try:
            return cls(value.lower().strip())
        except ValueError:
            return cls.none


# ---------------------------------------------------------------------------
# Phase transition table
# ---------------------------------------------------------------------------

_PHASE_TRANSITION_TABLE: Dict[Tuple[DelegatedFlowPhase, DelegatedFlowSignal], DelegatedFlowPhase] = {
    # dispatch signal: created → dispatched
    (DelegatedFlowPhase.created, DelegatedFlowSignal.dispatch): DelegatedFlowPhase.dispatched,
    # ack signal: dispatched → executing
    (DelegatedFlowPhase.dispatched, DelegatedFlowSignal.ack): DelegatedFlowPhase.executing,
    # result_inbound: executing → reconciling
    (DelegatedFlowPhase.executing, DelegatedFlowSignal.result_inbound): DelegatedFlowPhase.reconciling,
    # reconcile_complete: reconciling → completed
    (DelegatedFlowPhase.reconciling, DelegatedFlowSignal.reconcile_complete): DelegatedFlowPhase.completed,
    # result_success shortcut: reconciling → completed
    (DelegatedFlowPhase.reconciling, DelegatedFlowSignal.result_success): DelegatedFlowPhase.completed,
    # result_failure shortcut: reconciling → failed
    (DelegatedFlowPhase.reconciling, DelegatedFlowSignal.result_failure): DelegatedFlowPhase.failed,
    # fail from any non-terminal
    (DelegatedFlowPhase.created, DelegatedFlowSignal.fail): DelegatedFlowPhase.failed,
    (DelegatedFlowPhase.dispatched, DelegatedFlowSignal.fail): DelegatedFlowPhase.failed,
    (DelegatedFlowPhase.executing, DelegatedFlowSignal.fail): DelegatedFlowPhase.failed,
    (DelegatedFlowPhase.reconciling, DelegatedFlowSignal.fail): DelegatedFlowPhase.failed,
    (DelegatedFlowPhase.suspended, DelegatedFlowSignal.fail): DelegatedFlowPhase.failed,
    # cancel from any non-terminal
    (DelegatedFlowPhase.created, DelegatedFlowSignal.cancel): DelegatedFlowPhase.cancelled,
    (DelegatedFlowPhase.dispatched, DelegatedFlowSignal.cancel): DelegatedFlowPhase.cancelled,
    (DelegatedFlowPhase.executing, DelegatedFlowSignal.cancel): DelegatedFlowPhase.cancelled,
    (DelegatedFlowPhase.reconciling, DelegatedFlowSignal.cancel): DelegatedFlowPhase.cancelled,
    (DelegatedFlowPhase.suspended, DelegatedFlowSignal.cancel): DelegatedFlowPhase.cancelled,
    # suspend: dispatched or executing → suspended
    (DelegatedFlowPhase.dispatched, DelegatedFlowSignal.suspend): DelegatedFlowPhase.suspended,
    (DelegatedFlowPhase.executing, DelegatedFlowSignal.suspend): DelegatedFlowPhase.suspended,
    # resume: suspended → executing
    (DelegatedFlowPhase.suspended, DelegatedFlowSignal.resume): DelegatedFlowPhase.executing,
    # Idempotent transitions
    (DelegatedFlowPhase.dispatched, DelegatedFlowSignal.dispatch): DelegatedFlowPhase.dispatched,
    (DelegatedFlowPhase.executing, DelegatedFlowSignal.ack): DelegatedFlowPhase.executing,
}


def _apply_signal(
    current_phase: DelegatedFlowPhase,
    signal: DelegatedFlowSignal,
) -> DelegatedFlowPhase:
    """Return the next phase for *current_phase* + *signal*.

    Returns *current_phase* unchanged if:
    - the current phase is terminal, or
    - no transition is defined for the (phase, signal) pair.
    """
    if current_phase.is_terminal():
        return current_phase
    return _PHASE_TRANSITION_TABLE.get((current_phase, signal), current_phase)


# ---------------------------------------------------------------------------
# DelegatedFlowIdentity
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowIdentity:
    """Stable, serialisable identity record for a unified delegated flow.

    All fields are set at creation time and MUST NOT be mutated afterwards.

    Attributes
    ----------
    delegated_flow_id
        Unique, stable identifier for this specific delegated flow instance.
        Auto-generated UUID if not provided.
    flow_lineage_id
        Lineage identifier shared across all flow segments that belong to the
        same logical work unit (e.g. task_assign → parallel_subtask →
        takeover_request within one orchestration plan).  Auto-generated UUID
        if not provided; callers should supply the parent flow's
        ``flow_lineage_id`` when creating a child segment.
    flow_segment_id
        Optional segment discriminator within a lineage.  Empty string if the
        flow is a standalone or root segment.
    trace_id
        Distributed trace id propagated from the originating V2 request.
        Auto-generated UUID if not provided.
    flow_kind
        The :class:`DelegatedFlowKind` classifying the origin type of this
        flow (task_assign, goal_execution, parallel_subtask, takeover_request).
    """

    delegated_flow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flow_lineage_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flow_segment_id: str = ""
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    flow_kind: DelegatedFlowKind = DelegatedFlowKind.task_assign

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "delegated_flow_id": self.delegated_flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "flow_segment_id": self.flow_segment_id,
            "trace_id": self.trace_id,
            "flow_kind": self.flow_kind.value,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowIdentity":
        """Construct from a dict.  Raises ValueError if *data* is not a dict."""
        if not isinstance(data, dict):
            raise ValueError(
                "DelegatedFlowIdentity.from_dict expects a dict"
            )
        return cls(
            delegated_flow_id=data.get("delegated_flow_id") or str(uuid.uuid4()),
            flow_lineage_id=data.get("flow_lineage_id") or str(uuid.uuid4()),
            flow_segment_id=data.get("flow_segment_id", ""),
            trace_id=data.get("trace_id") or str(uuid.uuid4()),
            flow_kind=DelegatedFlowKind.from_string(
                data.get("flow_kind", DelegatedFlowKind.task_assign.value)
            ),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowOwnership
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowOwnership:
    """Record describing truth-ownership for a delegated flow.

    Ownership is scope-separated:

    * ``canonical_owner`` is always :attr:`DelegatedFlowOwnerKind.v2_canonical`
      once the entity is created.  V2 never relinquishes canonical flow
      truth (identity, lineage, phase, object mapping).
    * ``execution_owner`` is :attr:`DelegatedFlowOwnerKind.none` until
      dispatch occurs, then transitions to
      :attr:`DelegatedFlowOwnerKind.android_execution`.

    Attributes
    ----------
    canonical_owner
        Role that holds canonical flow truth (identity, lineage, phase,
        object mapping).  Always ``v2_canonical``.
    execution_owner
        Role that holds execution truth (device-scope execution state,
        local loop progress, result signals).  ``none`` until dispatch,
        then ``android_execution``.
    canonical_owner_rationale
        Human-readable explanation of why V2 holds canonical flow truth.
    execution_owner_rationale
        Human-readable explanation of the current execution-truth state.
    """

    canonical_owner: DelegatedFlowOwnerKind = DelegatedFlowOwnerKind.v2_canonical
    execution_owner: DelegatedFlowOwnerKind = DelegatedFlowOwnerKind.none
    canonical_owner_rationale: str = (
        "V2 orchestration layer is the canonical authority for flow identity, "
        "lineage, phase, and object mappings per FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY."
    )
    execution_owner_rationale: str = (
        "No execution owner assigned; flow has not been dispatched to Android yet."
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "canonical_owner": self.canonical_owner.value,
            "execution_owner": self.execution_owner.value,
            "canonical_owner_rationale": self.canonical_owner_rationale,
            "execution_owner_rationale": self.execution_owner_rationale,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowOwnership":
        """Construct from a dict."""
        if not isinstance(data, dict):
            raise ValueError("DelegatedFlowOwnership.from_dict expects a dict")
        return cls(
            canonical_owner=DelegatedFlowOwnerKind.from_string(
                data.get("canonical_owner", DelegatedFlowOwnerKind.v2_canonical.value)
            ),
            execution_owner=DelegatedFlowOwnerKind.from_string(
                data.get("execution_owner", DelegatedFlowOwnerKind.none.value)
            ),
            canonical_owner_rationale=data.get("canonical_owner_rationale", ""),
            execution_owner_rationale=data.get("execution_owner_rationale", ""),
        )

    def with_execution_owner_assigned(
        self,
        rationale: str = "",
    ) -> "DelegatedFlowOwnership":
        """Return a new ownership record with execution_owner set to android_execution."""
        return DelegatedFlowOwnership(
            canonical_owner=self.canonical_owner,
            execution_owner=DelegatedFlowOwnerKind.android_execution,
            canonical_owner_rationale=self.canonical_owner_rationale,
            execution_owner_rationale=rationale or (
                "Android execution side has acknowledged the delegated flow; "
                "execution truth transferred per ANDROID_HOLDS_EXECUTION_TRUTH_POLICY."
            ),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowObjectMapping
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowObjectMapping:
    """Explicit mapping from a DelegatedFlowEntity to the existing system objects.

    Fields are populated incrementally as each downstream object is created.
    Empty-string fields indicate that the corresponding object has not yet
    been created or associated with the flow.

    Attributes
    ----------
    canonical_task_id
        Id of the ``CanonicalTask`` (PR-A) that originated this flow.
    dispatch_record_id
        Id of the ``DelegatedRuntimeDispatchRecord`` (PR-8) for this flow.
    contract_id
        Id of the ``DelegatedHandoffContractRecord`` (PR-9) for this flow.
    binding_id
        Id of the ``AndroidRuntimeDispatchBindingRecord`` (PR-11) for this
        flow.
    tracker_id
        Id of the execution tracking record (PR-10) for this flow.
    session_id
        Id of the attached-runtime session (PR-7) carrying this flow.
    device_id
        Id of the target Android device / runtime host.
    android_flow_id
        Optional Android-side flow/activation id assigned by the Android
        runtime once execution begins.  Empty until the Android side
        emits a flow id in its ack or first progress signal.
    """

    canonical_task_id: str = ""
    dispatch_record_id: str = ""
    contract_id: str = ""
    binding_id: str = ""
    tracker_id: str = ""
    session_id: str = ""
    device_id: str = ""
    android_flow_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "canonical_task_id": self.canonical_task_id,
            "dispatch_record_id": self.dispatch_record_id,
            "contract_id": self.contract_id,
            "binding_id": self.binding_id,
            "tracker_id": self.tracker_id,
            "session_id": self.session_id,
            "device_id": self.device_id,
            "android_flow_id": self.android_flow_id,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowObjectMapping":
        """Construct from a dict."""
        if not isinstance(data, dict):
            raise ValueError("DelegatedFlowObjectMapping.from_dict expects a dict")
        return cls(
            canonical_task_id=data.get("canonical_task_id", ""),
            dispatch_record_id=data.get("dispatch_record_id", ""),
            contract_id=data.get("contract_id", ""),
            binding_id=data.get("binding_id", ""),
            tracker_id=data.get("tracker_id", ""),
            session_id=data.get("session_id", ""),
            device_id=data.get("device_id", ""),
            android_flow_id=data.get("android_flow_id", ""),
        )

    def merge_with(self, other: "DelegatedFlowObjectMapping") -> "DelegatedFlowObjectMapping":
        """Return a new mapping with non-empty fields from *other* overlaid on self.

        Fields in *self* that are already non-empty are NOT overwritten by an
        empty *other* field; non-empty *other* fields always win.
        """
        def _pick(a: str, b: str) -> str:
            return b if b else a

        return DelegatedFlowObjectMapping(
            canonical_task_id=_pick(self.canonical_task_id, other.canonical_task_id),
            dispatch_record_id=_pick(self.dispatch_record_id, other.dispatch_record_id),
            contract_id=_pick(self.contract_id, other.contract_id),
            binding_id=_pick(self.binding_id, other.binding_id),
            tracker_id=_pick(self.tracker_id, other.tracker_id),
            session_id=_pick(self.session_id, other.session_id),
            device_id=_pick(self.device_id, other.device_id),
            android_flow_id=_pick(self.android_flow_id, other.android_flow_id),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowExtensionPoints
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowExtensionPoints:
    """Forward-compatible extension surface for future PR series.

    This dataclass is a stable placeholder for hooks that will be established
    by subsequent PRs.  All fields default to None or empty string so that
    existing serialised flow entities remain fully round-trippable as new
    fields are added.

    Reserved fields
    ---------------
    continuity_token
        Opaque token assigned by the continuity subsystem (future PR).
        Reserved for replay / resume / handoff-continuation scenarios.
    replay_anchor_id
        Id of the replay anchor record (future PR) linked to this flow.
    result_convergence_key
        Key used by the result-convergence subsystem (future PR) to merge
        partial results from multiple execution segments.
    operator_visibility_tag
        Tag used by the operator visibility surface (future PR) to surface
        this flow in the operator dashboard.
    """

    continuity_token: Optional[str] = None
    replay_anchor_id: Optional[str] = None
    result_convergence_key: Optional[str] = None
    operator_visibility_tag: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "continuity_token": self.continuity_token,
            "replay_anchor_id": self.replay_anchor_id,
            "result_convergence_key": self.result_convergence_key,
            "operator_visibility_tag": self.operator_visibility_tag,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowExtensionPoints":
        """Construct from a dict."""
        if not isinstance(data, dict):
            raise ValueError("DelegatedFlowExtensionPoints.from_dict expects a dict")
        return cls(
            continuity_token=data.get("continuity_token"),
            replay_anchor_id=data.get("replay_anchor_id"),
            result_convergence_key=data.get("result_convergence_key"),
            operator_visibility_tag=data.get("operator_visibility_tag"),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowEntity
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowEntity:
    """Unified, canonical top-level record for a delegated flow.

    This is the **system-level first-class citizen** for any work delegated
    from the V2 central network to a device-side Android runtime surface.
    It aggregates identity, phase, ownership, object mapping, and extension
    points into a single coherent record.

    Attributes
    ----------
    identity
        Immutable identity block: ``delegated_flow_id``, ``flow_lineage_id``,
        ``flow_segment_id``, ``trace_id``, ``flow_kind``.
    phase
        Current unified flow-level phase.  Advances via
        :func:`advance_flow_phase`.
    ownership
        Truth-ownership record: who holds canonical flow truth (always V2)
        and who holds execution truth (Android once dispatched).
    object_mapping
        Mapping to the existing system objects that represent this flow.
        Populated incrementally via :func:`attach_object_mapping`.
    extension_points
        Forward-compatible hooks for continuity, replay, result
        convergence, and operator visibility.
    created_at
        Unix timestamp when this entity was created.
    last_updated_at
        Unix timestamp when this entity was last updated (phase or mapping
        change).
    metadata
        Arbitrary key-value metadata for observability.
    """

    identity: DelegatedFlowIdentity = field(default_factory=DelegatedFlowIdentity)
    phase: DelegatedFlowPhase = DelegatedFlowPhase.created
    ownership: DelegatedFlowOwnership = field(default_factory=DelegatedFlowOwnership)
    object_mapping: DelegatedFlowObjectMapping = field(
        default_factory=DelegatedFlowObjectMapping
    )
    extension_points: DelegatedFlowExtensionPoints = field(
        default_factory=DelegatedFlowExtensionPoints
    )
    created_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience accessors
    # ------------------------------------------------------------------

    @property
    def delegated_flow_id(self) -> str:
        """Shortcut to ``identity.delegated_flow_id``."""
        return self.identity.delegated_flow_id

    @property
    def flow_lineage_id(self) -> str:
        """Shortcut to ``identity.flow_lineage_id``."""
        return self.identity.flow_lineage_id

    @property
    def flow_segment_id(self) -> str:
        """Shortcut to ``identity.flow_segment_id``."""
        return self.identity.flow_segment_id

    @property
    def flow_kind(self) -> DelegatedFlowKind:
        """Shortcut to ``identity.flow_kind``."""
        return self.identity.flow_kind

    @property
    def contract_id(self) -> str:
        """Shortcut to ``object_mapping.contract_id``."""
        return self.object_mapping.contract_id

    @property
    def canonical_task_id(self) -> str:
        """Shortcut to ``object_mapping.canonical_task_id``."""
        return self.object_mapping.canonical_task_id

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "identity": self.identity.to_dict(),
            "phase": self.phase.value,
            "ownership": self.ownership.to_dict(),
            "object_mapping": self.object_mapping.to_dict(),
            "extension_points": self.extension_points.to_dict(),
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DelegatedFlowEntity":
        """Construct from a dict."""
        if not isinstance(data, dict):
            raise ValueError("DelegatedFlowEntity.from_dict expects a dict")
        return cls(
            identity=DelegatedFlowIdentity.from_dict(data.get("identity") or {}),
            phase=DelegatedFlowPhase.from_string(
                data.get("phase", DelegatedFlowPhase.created.value)
            ),
            ownership=DelegatedFlowOwnership.from_dict(data.get("ownership") or {}),
            object_mapping=DelegatedFlowObjectMapping.from_dict(
                data.get("object_mapping") or {}
            ),
            extension_points=DelegatedFlowExtensionPoints.from_dict(
                data.get("extension_points") or {}
            ),
            created_at=float(data.get("created_at") or time.time()),
            last_updated_at=float(data.get("last_updated_at") or time.time()),
            metadata=dict(data.get("metadata") or {}),
        )


# ---------------------------------------------------------------------------
# DelegatedFlowEntityRecord (ring-buffer entry)
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowEntityRecord:
    """Ring-buffer entry capturing a single phase transition or update event.

    Attributes
    ----------
    record_id
        Unique id for this record.
    delegated_flow_id
        Id of the flow entity this record belongs to.
    flow_lineage_id
        Lineage id of the flow entity.
    phase_before
        Phase before the event.
    phase_after
        Phase after the event (may equal phase_before for non-phase events).
    signal
        Signal that caused the phase transition, or empty string for
        non-signal events (e.g. object mapping updates).
    recorded_at
        Unix timestamp when this record was created.
    entity_snapshot
        Full entity state at the time of recording.
    """

    delegated_flow_id: str
    flow_lineage_id: str
    phase_before: DelegatedFlowPhase
    phase_after: DelegatedFlowPhase
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    signal: str = ""
    recorded_at: float = field(default_factory=time.time)
    entity_snapshot: Optional["DelegatedFlowEntity"] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "record_id": self.record_id,
            "delegated_flow_id": self.delegated_flow_id,
            "flow_lineage_id": self.flow_lineage_id,
            "phase_before": self.phase_before.value,
            "phase_after": self.phase_after.value,
            "signal": self.signal,
            "recorded_at": self.recorded_at,
            "entity_snapshot": (
                self.entity_snapshot.to_dict() if self.entity_snapshot else None
            ),
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# DelegatedFlowEntitySnapshot
# ---------------------------------------------------------------------------


@dataclass
class DelegatedFlowEntitySnapshot:
    """Point-in-time snapshot of delegated flow entities in the ring-buffer.

    Attributes
    ----------
    active_flows
        All non-terminal flow entities, newest-first.
    terminal_flows
        All terminal flow entities in the ring-buffer, newest-first.
    total_seen
        Total number of entity records ever written to the ring-buffer in
        this process lifetime.
    snapshot_at
        Unix timestamp when this snapshot was taken.
    """

    active_flows: List["DelegatedFlowEntity"] = field(default_factory=list)
    terminal_flows: List["DelegatedFlowEntity"] = field(default_factory=list)
    total_seen: int = 0
    snapshot_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-safe dict representation."""
        return {
            "active_flows": [f.to_dict() for f in self.active_flows],
            "terminal_flows": [f.to_dict() for f in self.terminal_flows],
            "total_seen": self.total_seen,
            "snapshot_at": self.snapshot_at,
        }

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict())


# ---------------------------------------------------------------------------
# DelegatedFlowEntityRuntime (ring-buffer singleton)
# ---------------------------------------------------------------------------


class DelegatedFlowEntityRuntime:
    """In-process ring-buffer singleton accumulating delegated flow entities.

    Maintains up to :data:`_RING_BUFFER_SIZE` (128) entities indexed by
    ``delegated_flow_id``.  Oldest entries are evicted when the buffer is
    full.  Provides lookup by ``delegated_flow_id``, ``flow_lineage_id``,
    and ``contract_id``.

    This class is NOT thread-safe.  It is designed for use in a
    single-threaded or cooperative async context (Galaxy's standard runtime
    model).  External callers that need thread safety should add their own
    locking on top.
    """

    def __init__(self, maxsize: int = _RING_BUFFER_SIZE) -> None:
        self._maxsize: int = maxsize
        self._entries: Deque[DelegatedFlowEntity] = deque(maxlen=maxsize)
        self._total_seen: int = 0

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def put(self, entity: DelegatedFlowEntity) -> None:
        """Persist *entity* to the ring-buffer.

        If an entity with the same ``delegated_flow_id`` already exists, it
        is replaced in-place (maintaining insertion order relative to others).
        """
        existing_ids = [e.delegated_flow_id for e in self._entries]
        if entity.delegated_flow_id in existing_ids:
            updated: Deque[DelegatedFlowEntity] = deque(maxlen=self._maxsize)
            for e in self._entries:
                if e.delegated_flow_id == entity.delegated_flow_id:
                    updated.append(entity)
                else:
                    updated.append(e)
            self._entries = updated
        else:
            self._entries.append(entity)
            self._total_seen += 1

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_by_flow_id(
        self, delegated_flow_id: str
    ) -> Optional[DelegatedFlowEntity]:
        """Return the entity for *delegated_flow_id*, or None."""
        for entity in reversed(self._entries):
            if entity.delegated_flow_id == delegated_flow_id:
                return entity
        return None

    def get_by_lineage(self, flow_lineage_id: str) -> List[DelegatedFlowEntity]:
        """Return all entities sharing *flow_lineage_id*, newest-first."""
        return [
            e
            for e in reversed(self._entries)
            if e.flow_lineage_id == flow_lineage_id
        ]

    def get_by_contract(self, contract_id: str) -> Optional[DelegatedFlowEntity]:
        """Return the most recent entity whose object_mapping.contract_id matches."""
        for entity in reversed(self._entries):
            if entity.object_mapping.contract_id == contract_id:
                return entity
        return None

    def list_active(self) -> List[DelegatedFlowEntity]:
        """Return all non-terminal flow entities, newest-first."""
        return [e for e in reversed(self._entries) if e.phase.is_active()]

    def list_all(self) -> List[DelegatedFlowEntity]:
        """Return all flow entities, newest-first."""
        return list(reversed(self._entries))

    @property
    def total_seen(self) -> int:
        """Total number of distinct flow entities ever added to this runtime."""
        return self._total_seen


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_DELEGATED_FLOW_RUNTIME: Optional[DelegatedFlowEntityRuntime] = None


def get_delegated_flow_entity_runtime() -> DelegatedFlowEntityRuntime:
    """Return the process-level singleton DelegatedFlowEntityRuntime."""
    global _DELEGATED_FLOW_RUNTIME
    if _DELEGATED_FLOW_RUNTIME is None:
        _DELEGATED_FLOW_RUNTIME = DelegatedFlowEntityRuntime()
    return _DELEGATED_FLOW_RUNTIME


def reset_delegated_flow_entity_runtime() -> None:
    """Reset the process-level singleton (for test isolation only)."""
    global _DELEGATED_FLOW_RUNTIME
    _DELEGATED_FLOW_RUNTIME = None


# ---------------------------------------------------------------------------
# Factory and mutation functions
# ---------------------------------------------------------------------------


def create_delegated_flow_entity(
    *,
    flow_kind: DelegatedFlowKind = DelegatedFlowKind.task_assign,
    flow_lineage_id: Optional[str] = None,
    flow_segment_id: str = "",
    trace_id: Optional[str] = None,
    delegated_flow_id: Optional[str] = None,
    canonical_task_id: str = "",
    dispatch_record_id: str = "",
    contract_id: str = "",
    binding_id: str = "",
    tracker_id: str = "",
    session_id: str = "",
    device_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> DelegatedFlowEntity:
    """Create and persist a canonical :class:`DelegatedFlowEntity`.

    Parameters
    ----------
    flow_kind:
        Origin type of the delegated flow.  Defaults to ``task_assign``.
    flow_lineage_id:
        Shared lineage id.  If not provided a new UUID is generated,
        meaning this flow starts a new lineage.  Supply the parent flow's
        ``flow_lineage_id`` to continue an existing lineage.
    flow_segment_id:
        Optional segment discriminator within the lineage.
    trace_id:
        Distributed trace id from the originating request.
    delegated_flow_id:
        Explicit flow id.  Auto-generated if not provided.
    canonical_task_id:
        CanonicalTask id for the initial object mapping.
    dispatch_record_id:
        DelegatedRuntimeDispatchRecord id for the initial object mapping.
    contract_id:
        DelegatedHandoffContractRecord id for the initial object mapping.
    binding_id:
        AndroidRuntimeDispatchBindingRecord id for the initial object mapping.
    tracker_id:
        Execution tracker record id for the initial object mapping.
    session_id:
        Attached-runtime session id.
    device_id:
        Target Android device id.
    metadata:
        Optional arbitrary metadata dict.
    runtime:
        Explicit runtime instance for test isolation.  Uses the process
        singleton if not provided.

    Returns
    -------
    DelegatedFlowEntity
        The newly created and persisted entity.
    """
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()

    identity = DelegatedFlowIdentity(
        delegated_flow_id=delegated_flow_id or str(uuid.uuid4()),
        flow_lineage_id=flow_lineage_id or str(uuid.uuid4()),
        flow_segment_id=flow_segment_id,
        trace_id=trace_id or str(uuid.uuid4()),
        flow_kind=flow_kind,
    )

    object_mapping = DelegatedFlowObjectMapping(
        canonical_task_id=canonical_task_id,
        dispatch_record_id=dispatch_record_id,
        contract_id=contract_id,
        binding_id=binding_id,
        tracker_id=tracker_id,
        session_id=session_id,
        device_id=device_id,
    )

    now = time.time()
    entity = DelegatedFlowEntity(
        identity=identity,
        phase=DelegatedFlowPhase.created,
        ownership=DelegatedFlowOwnership(),
        object_mapping=object_mapping,
        extension_points=DelegatedFlowExtensionPoints(),
        created_at=now,
        last_updated_at=now,
        metadata=dict(metadata or {}),
    )

    _runtime.put(entity)
    return entity


def advance_flow_phase(
    entity: DelegatedFlowEntity,
    signal: DelegatedFlowSignal,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
    signal_metadata: Optional[Dict[str, Any]] = None,
) -> DelegatedFlowEntity:
    """Return a new entity with the phase advanced by *signal*.

    The original *entity* is not mutated.  The new entity replaces the
    original in the ring-buffer.

    When the signal is :attr:`DelegatedFlowSignal.ack` or
    :attr:`DelegatedFlowSignal.dispatch`, the ownership record's
    ``execution_owner`` is automatically set to
    :attr:`DelegatedFlowOwnerKind.android_execution` once the flow
    enters the ``executing`` phase.

    Parameters
    ----------
    entity:
        The current entity.
    signal:
        The signal to apply.
    runtime:
        Explicit runtime instance for test isolation.
    signal_metadata:
        Optional metadata to merge into the entity's metadata dict.

    Returns
    -------
    DelegatedFlowEntity
        New entity with updated phase, ownership, and timestamp.
    """
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()

    new_phase = _apply_signal(entity.phase, signal)

    new_ownership = entity.ownership
    if (
        new_phase == DelegatedFlowPhase.executing
        and entity.ownership.execution_owner != DelegatedFlowOwnerKind.android_execution
    ):
        new_ownership = entity.ownership.with_execution_owner_assigned()

    merged_meta = dict(entity.metadata)
    if signal_metadata:
        merged_meta.update(signal_metadata)

    new_entity = DelegatedFlowEntity(
        identity=entity.identity,
        phase=new_phase,
        ownership=new_ownership,
        object_mapping=entity.object_mapping,
        extension_points=entity.extension_points,
        created_at=entity.created_at,
        last_updated_at=time.time(),
        metadata=merged_meta,
    )

    _runtime.put(new_entity)
    return new_entity


def attach_object_mapping(
    entity: DelegatedFlowEntity,
    mapping_update: DelegatedFlowObjectMapping,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> DelegatedFlowEntity:
    """Return a new entity with *mapping_update* merged into its object mapping.

    Non-empty fields in *mapping_update* overwrite the corresponding fields
    in the existing mapping.  Empty fields in *mapping_update* leave the
    existing values unchanged.

    Parameters
    ----------
    entity:
        The current entity.
    mapping_update:
        Mapping fragment to merge.
    runtime:
        Explicit runtime instance for test isolation.

    Returns
    -------
    DelegatedFlowEntity
        New entity with updated object mapping and timestamp.
    """
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()

    new_mapping = entity.object_mapping.merge_with(mapping_update)

    new_entity = DelegatedFlowEntity(
        identity=entity.identity,
        phase=entity.phase,
        ownership=entity.ownership,
        object_mapping=new_mapping,
        extension_points=entity.extension_points,
        created_at=entity.created_at,
        last_updated_at=time.time(),
        metadata=entity.metadata,
    )

    _runtime.put(new_entity)
    return new_entity


def record_delegated_flow(
    entity: DelegatedFlowEntity,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> None:
    """Persist *entity* to the ring-buffer singleton (or *runtime* if provided)."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    _runtime.put(entity)


def get_delegated_flow(
    delegated_flow_id: str,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> Optional[DelegatedFlowEntity]:
    """Return the entity for *delegated_flow_id*, or None."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    return _runtime.get_by_flow_id(delegated_flow_id)


def get_delegated_flow_by_lineage(
    flow_lineage_id: str,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> List[DelegatedFlowEntity]:
    """Return all entities sharing *flow_lineage_id*, newest-first."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    return _runtime.get_by_lineage(flow_lineage_id)


def get_delegated_flow_by_contract(
    contract_id: str,
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> Optional[DelegatedFlowEntity]:
    """Return the most recent entity whose object mapping carries *contract_id*."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    return _runtime.get_by_contract(contract_id)


def list_active_delegated_flows(
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> List[DelegatedFlowEntity]:
    """Return all non-terminal flow entities, newest-first."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    return _runtime.list_active()


def build_delegated_flow_snapshot(
    *,
    runtime: Optional[DelegatedFlowEntityRuntime] = None,
) -> DelegatedFlowEntitySnapshot:
    """Assemble a :class:`DelegatedFlowEntitySnapshot` from the ring-buffer."""
    _runtime = runtime if runtime is not None else get_delegated_flow_entity_runtime()
    all_entities = _runtime.list_all()
    return DelegatedFlowEntitySnapshot(
        active_flows=[e for e in all_entities if e.phase.is_active()],
        terminal_flows=[e for e in all_entities if not e.phase.is_active()],
        total_seen=_runtime.total_seen,
        snapshot_at=time.time(),
    )


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Sentinels
    "DELEGATED_FLOW_ENTITY_AUTHORITY",
    "DELEGATED_FLOW_ID_IS_IMMUTABLE_POLICY",
    "FLOW_LINEAGE_ID_SPANS_BOTH_SIDES_POLICY",
    "FLOW_PHASE_IS_MONOTONIC_POLICY",
    "FLOW_KIND_UNIFIES_ALL_DELEGATED_WORK_POLICY",
    "V2_HOLDS_CANONICAL_FLOW_TRUTH_POLICY",
    "ANDROID_HOLDS_EXECUTION_TRUTH_POLICY",
    "FLOW_OBJECT_MAPPING_IS_ADDITIVE_POLICY",
    "FLOW_ENTITY_IS_SYSTEM_FIRST_CLASS_CITIZEN_POLICY",
    "TERMINAL_FLOW_PHASE_BLOCKS_ADVANCEMENT_POLICY",
    "FLOW_LINEAGE_IS_TRACEABLE_ACROSS_KIND_BOUNDARY_POLICY",
    "EXTENSION_POINTS_ARE_FORWARD_COMPATIBLE_POLICY",
    "FLOW_TRUTH_AUTHORITY_IS_SCOPE_SEPARATED_POLICY",
    "DELEGATED_FLOW_ENTITY_PR50_SENTINEL",
    # Enums
    "DelegatedFlowKind",
    "DelegatedFlowPhase",
    "DelegatedFlowSignal",
    "DelegatedFlowOwnerKind",
    # Dataclasses
    "DelegatedFlowIdentity",
    "DelegatedFlowOwnership",
    "DelegatedFlowObjectMapping",
    "DelegatedFlowExtensionPoints",
    "DelegatedFlowEntity",
    "DelegatedFlowEntityRecord",
    "DelegatedFlowEntitySnapshot",
    # Runtime
    "DelegatedFlowEntityRuntime",
    # Functions
    "create_delegated_flow_entity",
    "advance_flow_phase",
    "attach_object_mapping",
    "record_delegated_flow",
    "get_delegated_flow",
    "get_delegated_flow_by_lineage",
    "get_delegated_flow_by_contract",
    "list_active_delegated_flows",
    "build_delegated_flow_snapshot",
    "get_delegated_flow_entity_runtime",
    "reset_delegated_flow_entity_runtime",
]
