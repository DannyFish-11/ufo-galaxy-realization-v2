"""contracts/mesh_session_coordinator.py
==========================================
Mesh Session Coordinator Contract — PR-37.

This module defines the **canonical Mesh Session Coordinator Contract**: the
structured, serialisable representation of the coordinator layer that manages
a mesh session across multiple devices/runtimes, assigns or confirms
participant roles, tracks subtask lifecycle, monitors barriers/merge posture,
and emits a stable coordination summary.

It answers the architectural question:

    *"Once a mesh session exists, what canonical coordinator manages
    participation, assignment, status, and merge/barrier posture across the
    session?"*

These contracts build directly on:

- **PR-32** (:class:`~contracts.mesh_membership.MeshMembership`) — mesh
  membership and participant roles.
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`) — the mesh session
  being coordinated.
- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`) —
  target-side takeover result.
- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchResult`) —
  source-side dispatch result.
- **PR-36** (:class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`)
  — cross-runtime merged results.

This module formalises:
- the coordinator status enum (``MeshCoordinatorStatus``);
- the participant status enum (``MeshParticipantStatus``);
- the assignment status enum (``MeshAssignmentStatus``);
- the barrier status enum (``MeshBarrierStatus``);
- the coordination event kind enum (``MeshCoordinationEventKind``);
- per-participant coordination state (``MeshParticipantCoordinationState``);
- per-assignment state (``MeshAssignmentState``);
- barrier state (``MeshBarrierState``);
- coordination events (``MeshCoordinationEvent``);
- the top-level coordinator state (``MeshSessionCoordinatorState``);
- a lightweight read-only summary (``MeshSessionCoordinatorSummary``);
- builder / adapter functions for all contracts.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — all contracts produce stable, round-trippable JSON
  via ``to_dict`` / ``to_json``.
- **Graceful defaults** — all fields beyond ``coordinator_id`` are optional;
  callers with partial context always produce a valid contract.
- **Stable field names** — downstream consumers can rely on all field names.
- **No UI semantics** — purely runtime/projection/coordinator use.
- **No command-heavy control surface** — read-only/state-capturing only.

Usage::

    from contracts.mesh_session_coordinator import (
        MeshSessionCoordinatorState,
        build_mesh_session_coordinator,
        from_mesh_session,
    )

    from contracts.mesh_session import build_mesh_session

    session = build_mesh_session(
        source_device_id="phone_001",
        primary_device_id="tablet_002",
        mesh_id="mesh_alpha",
    )
    coordinator = from_mesh_session(session)
    print(coordinator.to_json(indent=2))

See ``docs/MESH_SESSION_COORDINATOR.md`` for the full specification.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MeshCoordinatorStatus(str, Enum):
    """Lifecycle status of the :class:`MeshSessionCoordinatorState`.

    pending
        Coordinator has been initialised but has not yet confirmed all
        participants or started dispatching work.
    active
        Coordination is in progress; some participants are working.
    awaiting_barrier
        All active participants are blocked at a synchronisation barrier.
    merging
        Work has completed on participating devices; merge is in progress.
    completed
        All subtasks have completed and the merge (if required) is done.
    failed
        Coordination has failed unrecoverably.
    partial
        Coordination completed with partial results.
    unknown
        Status cannot be determined.
    """

    pending = "pending"
    active = "active"
    awaiting_barrier = "awaiting_barrier"
    merging = "merging"
    completed = "completed"
    failed = "failed"
    partial = "partial"
    unknown = "unknown"


class MeshParticipantStatus(str, Enum):
    """Coordination status of a single participant device.

    pending
        Device has been registered but has not confirmed readiness.
    ready
        Device has confirmed readiness for work.
    working
        Device is actively executing its assigned subtask.
    waiting
        Device is waiting at a synchronisation barrier.
    completed
        Device has completed its assigned subtask.
    failed
        Device execution failed.
    offline
        Device is not reachable.
    unknown
        Status cannot be determined.
    """

    pending = "pending"
    ready = "ready"
    working = "working"
    waiting = "waiting"
    completed = "completed"
    failed = "failed"
    offline = "offline"
    unknown = "unknown"


class MeshAssignmentStatus(str, Enum):
    """Lifecycle status of a single subtask assignment.

    pending
        Assignment created but not yet dispatched.
    dispatched
        Assignment has been sent to the target device.
    accepted
        Target device has acknowledged the assignment.
    in_progress
        Target device is executing the subtask.
    completed
        Subtask completed successfully.
    failed
        Subtask execution failed.
    cancelled
        Assignment was cancelled before or during execution.
    unknown
        Status cannot be determined.
    """

    pending = "pending"
    dispatched = "dispatched"
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    unknown = "unknown"


class MeshBarrierStatus(str, Enum):
    """Current state of the synchronisation barrier.

    not_required
        No barrier synchronisation is required for this session.
    open
        Barrier is open; devices may proceed without waiting.
    waiting
        One or more devices are blocking at the barrier.
    released
        Barrier has been released; all devices may proceed.
    failed
        Barrier coordination failed.
    unknown
        Barrier status cannot be determined.
    """

    not_required = "not_required"
    open = "open"
    waiting = "waiting"
    released = "released"
    failed = "failed"
    unknown = "unknown"


class MeshCoordinationEventKind(str, Enum):
    """Kind of a :class:`MeshCoordinationEvent`.

    participant_joined
        A new participant has joined the coordination session.
    participant_ready
        A participant has confirmed readiness.
    assignment_created
        A new subtask assignment has been created.
    assignment_dispatched
        An assignment has been dispatched to a device.
    assignment_completed
        An assignment has completed.
    assignment_failed
        An assignment has failed.
    barrier_reached
        A device has reached the synchronisation barrier.
    barrier_released
        The synchronisation barrier has been released.
    merge_started
        Result merge has started.
    merge_completed
        Result merge has completed.
    coordinator_status_changed
        The overall coordinator status has changed.
    error
        A coordination error was recorded.
    """

    participant_joined = "participant_joined"
    participant_ready = "participant_ready"
    assignment_created = "assignment_created"
    assignment_dispatched = "assignment_dispatched"
    assignment_completed = "assignment_completed"
    assignment_failed = "assignment_failed"
    barrier_reached = "barrier_reached"
    barrier_released = "barrier_released"
    merge_started = "merge_started"
    merge_completed = "merge_completed"
    coordinator_status_changed = "coordinator_status_changed"
    error = "error"


# ---------------------------------------------------------------------------
# Sub-contract: participant coordination state
# ---------------------------------------------------------------------------


class MeshParticipantCoordinationState(BaseModel):
    """Coordination state for a single participant device.

    Represents what the coordinator knows about one device's readiness,
    assignment progress, and liveness within the session.
    """

    device_id: str = Field(
        default="",
        description="Stable identifier for this participant device.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description="Optional runtime/session identifier on this device.",
    )
    roles: List[str] = Field(
        default_factory=list,
        description=(
            "Roles assigned to this participant (e.g. 'primary', 'support', "
            "'fallback', 'relay', 'observer').  Mirrors MeshMemberRole values "
            "but stored as plain strings for forward compatibility."
        ),
    )
    online: Optional[bool] = Field(
        default=None,
        description="Whether the device is currently reachable.  None = unknown.",
    )
    ready: Optional[bool] = Field(
        default=None,
        description=(
            "Whether the device has confirmed readiness for its assignment.  "
            "None = not yet confirmed."
        ),
    )
    status: MeshParticipantStatus = Field(
        default=MeshParticipantStatus.unknown,
        description="Current coordination lifecycle status for this participant.",
    )
    last_seen: Optional[float] = Field(
        default=None,
        description="Unix timestamp of the most recent signal from this device.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Sub-contract: assignment state
# ---------------------------------------------------------------------------


class MeshAssignmentState(BaseModel):
    """State of a single subtask assignment within the coordinator.

    Captures the per-assignment lifecycle as tracked by the coordinator.
    """

    subtask_id: str = Field(
        default_factory=lambda: f"subtask_{uuid.uuid4().hex[:10]}",
        description="Stable identifier for this subtask assignment.",
    )
    device_id: str = Field(
        default="",
        description="Device to which this subtask is assigned.",
    )
    status: MeshAssignmentStatus = Field(
        default=MeshAssignmentStatus.pending,
        description="Current lifecycle status of this assignment.",
    )
    capability_required: Optional[str] = Field(
        default=None,
        description=(
            "Optional capability key required to execute this subtask "
            "(e.g. 'screen', 'camera', 'microphone')."
        ),
    )
    handoff_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional handoff envelope ID (PR-31) used to transmit this "
            "assignment to the target device."
        ),
    )
    result_unit_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional result unit ID (PR-36) produced after this assignment "
            "completes.  Links to :class:`~contracts.cross_runtime_result_merge"
            ".RuntimeResultUnit`."
        ),
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this assignment was created.",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp of the most recent assignment update.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Sub-contract: barrier state
# ---------------------------------------------------------------------------


class MeshBarrierState(BaseModel):
    """State of the synchronisation barrier for the coordinator session.

    Tracks which devices have reached the barrier and whether it has been
    released.
    """

    status: MeshBarrierStatus = Field(
        default=MeshBarrierStatus.unknown,
        description="Current barrier synchronisation status.",
    )
    waiting_device_ids: List[str] = Field(
        default_factory=list,
        description="Device IDs that have reached the barrier and are waiting.",
    )
    released: bool = Field(
        default=False,
        description="True once the barrier has been released for all waiters.",
    )
    barrier_reason: Optional[str] = Field(
        default=None,
        description="Optional human-readable explanation for the current barrier state.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp of the most recent barrier state update.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Sub-contract: coordination event
# ---------------------------------------------------------------------------


class MeshCoordinationEvent(BaseModel):
    """A single lightweight coordination event record.

    Events are advisory — they capture what the coordinator observed without
    requiring a full event-sourcing infrastructure.
    """

    event_id: str = Field(
        default_factory=lambda: f"mce_{uuid.uuid4().hex[:10]}",
        description="Stable identifier for this event.",
    )
    kind: MeshCoordinationEventKind = Field(
        default=MeshCoordinationEventKind.coordinator_status_changed,
        description="Kind of coordination event.",
    )
    device_id: Optional[str] = Field(
        default=None,
        description="Device associated with this event, if applicable.",
    )
    subtask_id: Optional[str] = Field(
        default=None,
        description="Subtask associated with this event, if applicable.",
    )
    message: Optional[str] = Field(
        default=None,
        description="Optional human-readable event message.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this event occurred.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Top-level contract: MeshSessionCoordinatorState
# ---------------------------------------------------------------------------


class MeshSessionCoordinatorState(BaseModel):
    """Canonical coordinator state for a multi-device mesh session.

    This is the central contract that answers:
    - *Who is coordinating?* — ``coordinator_id``
    - *Which session is being coordinated?* — ``session_id``
    - *Who participates?* — ``participants``
    - *What subtasks are assigned and to whom?* — ``assignments``
    - *What is the synchronisation barrier state?* — ``barrier_state``
    - *Who is merging results?* — ``merge_owner_device_id``
    - *Which devices are pending / completed / failed?* — ``pending_device_ids``,
      ``completed_device_ids``, ``failed_device_ids``
    - *What is the overall coordination status?* — ``status``

    All fields beyond ``coordinator_id`` are optional so that instances can
    be constructed incrementally from partial data sources.
    """

    coordinator_id: str = Field(
        default_factory=lambda: f"mcoord_{uuid.uuid4().hex[:12]}",
        description="Stable, globally-unique identifier for this coordinator instance.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "Identifier of the :class:`~contracts.mesh_session.MeshSession` "
            "being coordinated."
        ),
    )
    mesh_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional mesh/body identifier linking this coordinator to a "
            "specific device formation or mesh membership."
        ),
    )
    trace_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional execution trace identifier (PR-25) linking this "
            "coordinator to a trace chain."
        ),
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier correlating with an originating task.",
    )
    status: MeshCoordinatorStatus = Field(
        default=MeshCoordinatorStatus.pending,
        description="Overall lifecycle status of the coordinator.",
    )
    participants: List[MeshParticipantCoordinationState] = Field(
        default_factory=list,
        description="Per-participant coordination state records.",
    )
    assignments: List[MeshAssignmentState] = Field(
        default_factory=list,
        description="Per-subtask assignment state records.",
    )
    barrier_state: MeshBarrierState = Field(
        default_factory=MeshBarrierState,
        description="Current synchronisation barrier state.",
    )
    merge_owner_device_id: Optional[str] = Field(
        default=None,
        description=(
            "Device ID responsible for aggregating and merging distributed "
            "subtask results."
        ),
    )
    pending_device_ids: List[str] = Field(
        default_factory=list,
        description="Device IDs whose assignments are still pending or in-progress.",
    )
    completed_device_ids: List[str] = Field(
        default_factory=list,
        description="Device IDs whose assignments have completed successfully.",
    )
    failed_device_ids: List[str] = Field(
        default_factory=list,
        description="Device IDs whose assignments have failed.",
    )
    coordination_events: List[MeshCoordinationEvent] = Field(
        default_factory=list,
        description=(
            "Lightweight log of coordination events.  Advisory only — "
            "consumers should not depend on completeness."
        ),
    )
    result_merge_summary: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional read-only summary of the cross-runtime result merge "
            "(PR-36) once merge is complete or in progress."
        ),
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds) when this coordinator state was created.",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds) of the most recent coordinator update.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshSessionCoordinatorState":
        """Construct from a dictionary, tolerating unknown extra fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> "MeshSessionCoordinatorSummary":
        """Return a lightweight :class:`MeshSessionCoordinatorSummary`."""
        return build_coordinator_summary(coordinator=self)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Lightweight read-only summary
# ---------------------------------------------------------------------------


class MeshSessionCoordinatorSummary(BaseModel):
    """Lightweight read-only summary of coordinator state.

    Suitable for projection endpoints, dashboards, and lightweight consumers
    that do not need the full coordinator state.
    """

    summary_id: str = Field(
        default_factory=lambda: f"mcoord_sum_{uuid.uuid4().hex[:10]}",
        description="Stable identifier for this summary snapshot.",
    )
    coordinator_id: Optional[str] = Field(
        default=None,
        description="Coordinator ID from the source coordinator state.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Session ID being coordinated.",
    )
    mesh_id: Optional[str] = Field(
        default=None,
        description="Optional mesh ID.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional trace ID.",
    )
    status: MeshCoordinatorStatus = Field(
        default=MeshCoordinatorStatus.unknown,
        description="Overall coordinator status.",
    )
    participant_count: int = Field(
        default=0,
        description="Total number of registered participants.",
    )
    assignment_count: int = Field(
        default=0,
        description="Total number of subtask assignments.",
    )
    pending_count: int = Field(
        default=0,
        description="Number of devices still pending.",
    )
    completed_count: int = Field(
        default=0,
        description="Number of devices that have completed.",
    )
    failed_count: int = Field(
        default=0,
        description="Number of devices that have failed.",
    )
    barrier_status: MeshBarrierStatus = Field(
        default=MeshBarrierStatus.unknown,
        description="Current barrier synchronisation status.",
    )
    merge_owner_device_id: Optional[str] = Field(
        default=None,
        description="Device responsible for result merging.",
    )
    has_result_merge_summary: bool = Field(
        default=False,
        description="True if a result merge summary is available.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this summary was generated.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshSessionCoordinatorSummary":
        return cls.model_validate(data)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    """Coerce *value* to ``str``, returning *default* on failure."""
    if value is None:
        return default
    try:
        if hasattr(value, "value"):
            return str(value.value)
        return str(value)
    except Exception:
        return default


def _safe_list(value: Any) -> list:
    """Return *value* if it is a list, else an empty list."""
    if isinstance(value, list):
        return value
    return []


def _safe_dict(value: Any) -> dict:
    """Return *value* if it is a dict, else an empty dict."""
    if isinstance(value, dict):
        return value
    return {}


# ---------------------------------------------------------------------------
# Builders / adapters
# ---------------------------------------------------------------------------


def build_mesh_session_coordinator(
    *,
    session_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    status: MeshCoordinatorStatus = MeshCoordinatorStatus.pending,
    participants: Optional[List[MeshParticipantCoordinationState]] = None,
    assignments: Optional[List[MeshAssignmentState]] = None,
    barrier_state: Optional[MeshBarrierState] = None,
    merge_owner_device_id: Optional[str] = None,
    pending_device_ids: Optional[List[str]] = None,
    completed_device_ids: Optional[List[str]] = None,
    failed_device_ids: Optional[List[str]] = None,
    coordination_events: Optional[List[MeshCoordinationEvent]] = None,
    result_merge_summary: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MeshSessionCoordinatorState:
    """Convenience factory for :class:`MeshSessionCoordinatorState`.

    All parameters are optional; callers may supply as little or as much
    context as is available.

    Returns
    -------
    MeshSessionCoordinatorState
        A fully populated coordinator state.  Never raises.
    """
    try:
        return MeshSessionCoordinatorState(
            session_id=session_id,
            mesh_id=mesh_id,
            trace_id=trace_id,
            task_id=task_id,
            status=status,
            participants=participants or [],
            assignments=assignments or [],
            barrier_state=barrier_state or MeshBarrierState(),
            merge_owner_device_id=merge_owner_device_id,
            pending_device_ids=pending_device_ids or [],
            completed_device_ids=completed_device_ids or [],
            failed_device_ids=failed_device_ids or [],
            coordination_events=coordination_events or [],
            result_merge_summary=result_merge_summary,
            metadata=metadata or {},
        )
    except Exception as exc:
        _logger.warning(
            "build_mesh_session_coordinator: construction error, returning minimal state: %s",
            exc,
        )
        return MeshSessionCoordinatorState(session_id=session_id, mesh_id=mesh_id)


def from_mesh_session(
    mesh_session: Any,
    *,
    trace_id: Optional[str] = None,
    status: MeshCoordinatorStatus = MeshCoordinatorStatus.pending,
) -> MeshSessionCoordinatorState:
    """Build a :class:`MeshSessionCoordinatorState` from a
    :class:`~contracts.mesh_session.MeshSession`.

    This is the primary adapter for PR-33 mesh session contracts.  It
    normalises participants and subtask assignments from the session into
    coordinator-native state objects.

    Parameters
    ----------
    mesh_session:
        A :class:`~contracts.mesh_session.MeshSession` instance or a
        compatible dictionary.  ``None`` is tolerated and returns a minimal
        coordinator state.
    trace_id:
        Optional trace ID override (uses session value if not supplied).
    status:
        Initial coordinator status.

    Returns
    -------
    MeshSessionCoordinatorState
        Never raises.
    """
    if mesh_session is None:
        return MeshSessionCoordinatorState()

    try:
        # Normalise to dict for safe attribute access
        if hasattr(mesh_session, "to_dict"):
            session_data = mesh_session.to_dict()
        elif isinstance(mesh_session, dict):
            session_data = mesh_session
        else:
            session_data = {}

        session_id = _safe_str(session_data.get("session_id"))
        mesh_id = _safe_str(session_data.get("mesh_id")) or None
        effective_trace_id = trace_id or _safe_str(session_data.get("trace_id")) or None
        task_id = _safe_str(session_data.get("task_id")) or None
        merge_owner_device_id = _safe_str(session_data.get("merge_owner_device_id")) or None

        # Build participant states
        raw_participants = _safe_list(session_data.get("participants", []))
        participants: List[MeshParticipantCoordinationState] = []
        pending_device_ids: List[str] = []
        for p in raw_participants:
            if not isinstance(p, dict):
                p = p if hasattr(p, "items") else {}
            device_id = _safe_str(p.get("device_id") if isinstance(p, dict) else getattr(p, "device_id", ""))
            roles = _safe_list(p.get("roles", []) if isinstance(p, dict) else getattr(p, "roles", []))
            if isinstance(roles[0] if roles else None, str):
                pass  # already strings
            else:
                roles = [_safe_str(r) for r in roles]
            p_state = MeshParticipantCoordinationState(
                device_id=device_id,
                roles=roles,
                status=MeshParticipantStatus.pending,
            )
            participants.append(p_state)
            if device_id:
                pending_device_ids.append(device_id)

        # Build assignment states from subtask_assignments
        raw_assignments = _safe_list(session_data.get("subtask_assignments", []))
        assignments: List[MeshAssignmentState] = []
        for a in raw_assignments:
            if not isinstance(a, dict):
                a = a if hasattr(a, "items") else {}
            subtask_id = _safe_str(a.get("subtask_id", "") if isinstance(a, dict) else getattr(a, "subtask_id", ""))
            device_id_a = _safe_str(a.get("device_id", "") if isinstance(a, dict) else getattr(a, "device_id", ""))
            capability = _safe_str(a.get("capability_required", "") if isinstance(a, dict) else getattr(a, "capability_required", "")) or None
            a_state = MeshAssignmentState(
                subtask_id=subtask_id or f"subtask_{uuid.uuid4().hex[:10]}",
                device_id=device_id_a,
                status=MeshAssignmentStatus.pending,
                capability_required=capability,
            )
            assignments.append(a_state)

        # Determine barrier state from session barrier_posture
        barrier_posture = _safe_str(session_data.get("barrier_posture", ""))
        barrier_status = MeshBarrierStatus.unknown
        if "hard" in barrier_posture or "soft" in barrier_posture:
            barrier_status = MeshBarrierStatus.open
        elif "none" in barrier_posture:
            barrier_status = MeshBarrierStatus.not_required
        barrier_state = MeshBarrierState(status=barrier_status)

        return MeshSessionCoordinatorState(
            session_id=session_id or None,
            mesh_id=mesh_id,
            trace_id=effective_trace_id,
            task_id=task_id,
            status=status,
            participants=participants,
            assignments=assignments,
            barrier_state=barrier_state,
            merge_owner_device_id=merge_owner_device_id,
            pending_device_ids=pending_device_ids,
            completed_device_ids=[],
            failed_device_ids=[],
        )
    except Exception as exc:
        _logger.warning(
            "from_mesh_session: failed to build coordinator from session, "
            "returning minimal state: %s",
            exc,
        )
        try:
            session_id_fallback = (
                mesh_session.session_id
                if hasattr(mesh_session, "session_id")
                else None
            )
        except Exception:
            session_id_fallback = None
        return MeshSessionCoordinatorState(session_id=session_id_fallback)


def update_coordinator_with_dispatch_result(
    coordinator: MeshSessionCoordinatorState,
    dispatch_result: Any,
) -> MeshSessionCoordinatorState:
    """Return an updated coordinator incorporating a source dispatch result.

    Consumes a :class:`~contracts.source_dispatch.SourceDispatchResult`
    (PR-35) and evolves the coordinator state to reflect the dispatch outcome.

    Parameters
    ----------
    coordinator:
        The existing coordinator state to evolve.
    dispatch_result:
        A :class:`~contracts.source_dispatch.SourceDispatchResult` instance
        or compatible dict.  ``None`` is tolerated.

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    if dispatch_result is None:
        return coordinator
    try:
        if hasattr(dispatch_result, "to_dict"):
            result_data = dispatch_result.to_dict()
        elif isinstance(dispatch_result, dict):
            result_data = dispatch_result
        else:
            return coordinator

        success = result_data.get("success", False)
        mode = _safe_str(result_data.get("mode", ""))
        target_device_id = None
        target = result_data.get("target")
        if isinstance(target, dict):
            target_device_id = _safe_str(target.get("device_id", "")) or None

        updated = coordinator.model_copy(deep=True)
        updated.updated_at = time.time()

        # Emit a coordination event
        event = MeshCoordinationEvent(
            kind=MeshCoordinationEventKind.assignment_dispatched,
            device_id=target_device_id,
            message=f"Source dispatch completed: mode={mode}, success={success}",
        )
        updated.coordination_events = list(updated.coordination_events) + [event]

        # Update status
        if success:
            if mode in ("local", "local_only"):
                updated.status = MeshCoordinatorStatus.active
            else:
                updated.status = MeshCoordinatorStatus.active
        else:
            updated.status = MeshCoordinatorStatus.failed

        # Update trace_id if richer
        if not updated.trace_id:
            updated.trace_id = _safe_str(result_data.get("trace_id", "")) or None

        return updated
    except Exception as exc:
        _logger.warning(
            "update_coordinator_with_dispatch_result: error, returning unchanged coordinator: %s",
            exc,
        )
        return coordinator


def update_coordinator_with_takeover_result(
    coordinator: MeshSessionCoordinatorState,
    takeover_result: Any,
    *,
    device_id: Optional[str] = None,
) -> MeshSessionCoordinatorState:
    """Return an updated coordinator incorporating a target takeover result.

    Consumes a :class:`~contracts.local_takeover_result.LocalTakeoverResult`
    (PR-34) and evolves the coordinator state to reflect the target-side
    execution outcome.

    Parameters
    ----------
    coordinator:
        The existing coordinator state to evolve.
    takeover_result:
        A :class:`~contracts.local_takeover_result.LocalTakeoverResult`
        instance or compatible dict.  ``None`` is tolerated.
    device_id:
        Optional override for the device that executed the takeover; used when
        the result itself does not carry a reliable device identifier.

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    if takeover_result is None:
        return coordinator
    try:
        if hasattr(takeover_result, "to_dict"):
            result_data = takeover_result.to_dict()
        elif isinstance(takeover_result, dict):
            result_data = takeover_result
        else:
            return coordinator

        success = result_data.get("success", False)
        status_str = _safe_str(result_data.get("status", ""))

        # Resolve device ID
        if not device_id:
            context = result_data.get("session_context", {}) or {}
            device_id = _safe_str(context.get("device_id", "")) or None

        updated = coordinator.model_copy(deep=True)
        updated.updated_at = time.time()

        # Update per-participant status
        if device_id:
            new_status = (
                MeshParticipantStatus.completed if success else MeshParticipantStatus.failed
            )
            new_participants = []
            for p in updated.participants:
                if p.device_id == device_id:
                    p = p.model_copy(update={"status": new_status})
                new_participants.append(p)
            updated.participants = new_participants

            # Update device tracking lists
            pending = list(updated.pending_device_ids)
            completed = list(updated.completed_device_ids)
            failed = list(updated.failed_device_ids)
            if device_id in pending:
                pending.remove(device_id)
            if success:
                if device_id not in completed:
                    completed.append(device_id)
            else:
                if device_id not in failed:
                    failed.append(device_id)
            updated.pending_device_ids = pending
            updated.completed_device_ids = completed
            updated.failed_device_ids = failed

        # Update assignment status
        new_assignments = []
        for a in updated.assignments:
            if a.device_id == device_id:
                new_a_status = (
                    MeshAssignmentStatus.completed if success else MeshAssignmentStatus.failed
                )
                a = a.model_copy(update={"status": new_a_status, "updated_at": time.time()})
            new_assignments.append(a)
        updated.assignments = new_assignments

        # Emit event
        event = MeshCoordinationEvent(
            kind=(
                MeshCoordinationEventKind.assignment_completed
                if success
                else MeshCoordinationEventKind.assignment_failed
            ),
            device_id=device_id,
            message=f"Target takeover result: status={status_str}, success={success}",
        )
        updated.coordination_events = list(updated.coordination_events) + [event]

        # Update overall coordinator status
        if not updated.pending_device_ids and not updated.failed_device_ids:
            if updated.completed_device_ids:
                updated.status = MeshCoordinatorStatus.merging
        elif updated.failed_device_ids:
            if not updated.pending_device_ids:
                updated.status = MeshCoordinatorStatus.partial
            else:
                pass  # still some in progress

        return updated
    except Exception as exc:
        _logger.warning(
            "update_coordinator_with_takeover_result: error, returning unchanged coordinator: %s",
            exc,
        )
        return coordinator


def update_coordinator_with_merged_result(
    coordinator: MeshSessionCoordinatorState,
    merged_result: Any,
) -> MeshSessionCoordinatorState:
    """Return an updated coordinator incorporating a cross-runtime merged result.

    Consumes a :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`
    (PR-36) and evolves the coordinator state to reflect merge completion.

    Parameters
    ----------
    coordinator:
        The existing coordinator state to evolve.
    merged_result:
        A :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`
        instance or compatible dict.  ``None`` is tolerated.

    Returns
    -------
    MeshSessionCoordinatorState
        Updated coordinator state.  Never raises.
    """
    if merged_result is None:
        return coordinator
    try:
        if hasattr(merged_result, "to_dict"):
            result_data = merged_result.to_dict()
        elif isinstance(merged_result, dict):
            result_data = merged_result
        else:
            return coordinator

        success = result_data.get("success", False)

        updated = coordinator.model_copy(deep=True)
        updated.updated_at = time.time()
        updated.result_merge_summary = result_data

        # Determine new status
        if success:
            updated.status = MeshCoordinatorStatus.completed
        elif result_data.get("partial", False):
            updated.status = MeshCoordinatorStatus.partial
        else:
            updated.status = MeshCoordinatorStatus.failed

        # Emit event
        event = MeshCoordinationEvent(
            kind=MeshCoordinationEventKind.merge_completed,
            message=f"Result merge completed: success={success}",
        )
        updated.coordination_events = list(updated.coordination_events) + [event]

        return updated
    except Exception as exc:
        _logger.warning(
            "update_coordinator_with_merged_result: error, returning unchanged coordinator: %s",
            exc,
        )
        return coordinator


def build_coordinator_summary(
    *,
    coordinator: Optional[MeshSessionCoordinatorState] = None,
    coordinator_id: Optional[str] = None,
    session_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: MeshCoordinatorStatus = MeshCoordinatorStatus.unknown,
    participant_count: int = 0,
    assignment_count: int = 0,
    pending_count: int = 0,
    completed_count: int = 0,
    failed_count: int = 0,
    barrier_status: MeshBarrierStatus = MeshBarrierStatus.unknown,
    merge_owner_device_id: Optional[str] = None,
    has_result_merge_summary: bool = False,
    metadata: Optional[Dict[str, Any]] = None,
) -> MeshSessionCoordinatorSummary:
    """Build a :class:`MeshSessionCoordinatorSummary` from a coordinator or kwargs.

    When *coordinator* is provided, all other keyword arguments are ignored
    and the summary is derived from the coordinator state.  When *coordinator*
    is ``None``, the keyword arguments are used directly.

    Returns
    -------
    MeshSessionCoordinatorSummary
        Never raises.
    """
    try:
        if coordinator is not None:
            return MeshSessionCoordinatorSummary(
                coordinator_id=coordinator.coordinator_id,
                session_id=coordinator.session_id,
                mesh_id=coordinator.mesh_id,
                trace_id=coordinator.trace_id,
                status=coordinator.status,
                participant_count=len(coordinator.participants),
                assignment_count=len(coordinator.assignments),
                pending_count=len(coordinator.pending_device_ids),
                completed_count=len(coordinator.completed_device_ids),
                failed_count=len(coordinator.failed_device_ids),
                barrier_status=coordinator.barrier_state.status,
                merge_owner_device_id=coordinator.merge_owner_device_id,
                has_result_merge_summary=coordinator.result_merge_summary is not None,
                metadata=coordinator.metadata or {},
            )
        return MeshSessionCoordinatorSummary(
            coordinator_id=coordinator_id,
            session_id=session_id,
            mesh_id=mesh_id,
            trace_id=trace_id,
            status=status,
            participant_count=participant_count,
            assignment_count=assignment_count,
            pending_count=pending_count,
            completed_count=completed_count,
            failed_count=failed_count,
            barrier_status=barrier_status,
            merge_owner_device_id=merge_owner_device_id,
            has_result_merge_summary=has_result_merge_summary,
            metadata=metadata or {},
        )
    except Exception as exc:
        _logger.warning(
            "build_coordinator_summary: construction error, returning minimal summary: %s",
            exc,
        )
        return MeshSessionCoordinatorSummary(status=MeshCoordinatorStatus.unknown)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Enumerations
    "MeshCoordinatorStatus",
    "MeshParticipantStatus",
    "MeshAssignmentStatus",
    "MeshBarrierStatus",
    "MeshCoordinationEventKind",
    # Sub-contracts
    "MeshParticipantCoordinationState",
    "MeshAssignmentState",
    "MeshBarrierState",
    "MeshCoordinationEvent",
    # Top-level contracts
    "MeshSessionCoordinatorState",
    "MeshSessionCoordinatorSummary",
    # Builders / adapters
    "build_mesh_session_coordinator",
    "from_mesh_session",
    "update_coordinator_with_dispatch_result",
    "update_coordinator_with_takeover_result",
    "update_coordinator_with_merged_result",
    "build_coordinator_summary",
]
