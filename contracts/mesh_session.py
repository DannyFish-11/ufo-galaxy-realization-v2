"""contracts/mesh_session.py
====================================
Mesh Session Contract — PR-33.

This module defines the **canonical Mesh Session contract**: a single,
serialisable schema that answers the architectural question:

    *"When multiple devices cooperate on one task flow, what is the
    canonical session object that represents that cooperation?"*

It is the multi-device session counterpart to the earlier contract chain:

- **PR-29** — what a registered runtime-capable device *is*
- **PR-30** — what a local runtime host must *expose*
- **PR-31** — what a cross-device handoff *carries*
- **PR-32** — how a device *participates* in a mesh/body
- **PR-33** (this module) — what the cooperative multi-device *session* is

This contract formalises:
- the mesh session ID and lifecycle (``session_id``, ``status``,
  ``created_at``, ``updated_at``);
- who participates and in what role (``participants``);
- who initiated vs who executes primarily (``source_device_id``,
  ``primary_device_id``);
- how distributed subtasks are assigned (``subtask_assignments``);
- how and when results are merged (``merge_policy``, ``merge_owner_device_id``);
- synchronisation/barrier semantics (``barrier_posture``);
- cross-device coordination flags (``multi_device_required``,
  ``merge_confirmation_required``).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`MeshSession.to_dict` and
  :meth:`MeshSession.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond ``session_id`` are optional;
  adapters catch exceptions and degrade gracefully.
- **No UI-specific semantics** — suitable for runtime/projection/coordinator
  use.
- **Stable field names** — downstream consumers can rely on the field names
  defined here without fear of silent renaming.
- **Tolerant of partial inputs** — adapters accept ``None`` and missing
  attributes without raising.

Usage::

    from contracts.mesh_session import (
        MeshSession,
        MeshSessionParticipant,
        MeshSubtaskAssignment,
        MeshMergePolicy,
        MeshBarrierPosture,
        MeshSessionStatus,
        from_device_formation_summary,
        from_cross_device_routing_summary,
        from_constellation_decomposition,
        build_mesh_session,
    )

    # Build from a FormationSummary (core.device_formation)
    from core.device_formation import resolve_formation_summary
    summary = resolve_formation_summary()
    session = from_device_formation_summary(summary)

    # Build from a CrossDeviceAssignmentSummary (core.cross_device_policy)
    from core.cross_device_policy import build_assignment_summary
    routing = build_assignment_summary(policy)
    session = from_cross_device_routing_summary(routing)

    # Build from a TaskDecomposition (core.schemas.orchestration)
    from core.schemas.orchestration import TaskDecomposition
    session = from_constellation_decomposition(
        decomposition=decomp,
        session_id="sess_abc",
        source_device_id="phone_001",
    )

    # Build from scratch
    session = build_mesh_session(
        source_device_id="phone_001",
        primary_device_id="tablet_002",
        mesh_id="mesh_beta",
    )

See ``docs/MESH_SESSION_CONTRACT.md`` for the full specification.
"""

from __future__ import annotations

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class MeshSessionStatus(str, Enum):
    """Lifecycle status of a :class:`MeshSession`.

    Values are stable contract identifiers.  Downstream consumers must
    treat unknown values gracefully (forward-compatible).

    Full explicit lifecycle:
      PENDING → ACTIVE → MERGING → COMPLETED
      ACTIVE → SUSPENDED → RESTORING → ACTIVE
      Any non-terminal → CANCELLED / FAILED
    """

    PENDING = "pending"
    """Session has been created but participants have not yet been confirmed."""

    ACTIVE = "active"
    """Session is active and execution is in progress."""

    MERGING = "merging"
    """Subtask execution is complete; merge/aggregation is in progress."""

    SUSPENDED = "suspended"
    """Session has been temporarily paused; participants have been notified.
    A suspended session retains its identity, topology, and durable state and
    is eligible for restoration.  This state bridges runtime interruption with
    later :attr:`RESTORING` / :attr:`ACTIVE` re-entry."""

    RESTORING = "restoring"
    """Session is in the process of being restored from durable state.
    The lifecycle coordinator transitions through this state when re-hydrating
    a previously :attr:`SUSPENDED` session before returning it to
    :attr:`ACTIVE`."""

    COMPLETED = "completed"
    """Session completed successfully — all subtasks done, merge finished."""

    CANCELLED = "cancelled"
    """Session was cancelled before completion."""

    FAILED = "failed"
    """Session ended due to an unrecoverable failure."""

    UNKNOWN = "unknown"
    """Status could not be determined from available sources."""


# ---------------------------------------------------------------------------
# Lifecycle helpers — terminal / restorable sets and transition table
# ---------------------------------------------------------------------------

#: Statuses from which no further lifecycle transition is permitted.
MESH_SESSION_TERMINAL_STATUSES: frozenset = frozenset({
    MeshSessionStatus.COMPLETED,
    MeshSessionStatus.CANCELLED,
    MeshSessionStatus.FAILED,
})

#: Statuses from which a session is eligible for restoration.
MESH_SESSION_RESTORABLE_STATUSES: frozenset = frozenset({
    MeshSessionStatus.SUSPENDED,
})

#: Valid lifecycle transitions.  Only transitions listed here are permitted.
#: Enforcement is advisory by default; callers may choose to raise on violation.
MESH_SESSION_VALID_TRANSITIONS: dict = {
    MeshSessionStatus.PENDING:    {MeshSessionStatus.ACTIVE,
                                    MeshSessionStatus.CANCELLED,
                                    MeshSessionStatus.FAILED},
    MeshSessionStatus.ACTIVE:     {MeshSessionStatus.MERGING,
                                    MeshSessionStatus.SUSPENDED,
                                    MeshSessionStatus.COMPLETED,
                                    MeshSessionStatus.CANCELLED,
                                    MeshSessionStatus.FAILED},
    MeshSessionStatus.MERGING:    {MeshSessionStatus.COMPLETED,
                                    MeshSessionStatus.FAILED,
                                    MeshSessionStatus.CANCELLED},
    MeshSessionStatus.SUSPENDED:  {MeshSessionStatus.RESTORING,
                                    MeshSessionStatus.CANCELLED,
                                    MeshSessionStatus.FAILED},
    MeshSessionStatus.RESTORING:  {MeshSessionStatus.ACTIVE,
                                    MeshSessionStatus.FAILED},
    MeshSessionStatus.COMPLETED:  set(),
    MeshSessionStatus.CANCELLED:  set(),
    MeshSessionStatus.FAILED:     set(),
    MeshSessionStatus.UNKNOWN:    {MeshSessionStatus.PENDING,
                                    MeshSessionStatus.ACTIVE,
                                    MeshSessionStatus.SUSPENDED,
                                    MeshSessionStatus.RESTORING},
}

#: Sentinel — affirms that MeshSession lifecycle semantics are explicit and
#: stable, forming a durable foundation for restore/roaming/rebalance work.
MESH_SESSION_LIFECYCLE_IS_EXPLICIT: str = (
    "MESH_SESSION_LIFECYCLE_IS_EXPLICIT: "
    "contracts/mesh_session.py defines an explicit, stable lifecycle model "
    "(PENDING→ACTIVE→MERGING→COMPLETED; ACTIVE→SUSPENDED→RESTORING→ACTIVE) "
    "with machine-checkable transition rules (MESH_SESSION_VALID_TRANSITIONS). "
    "PR-1 durable mesh session runtime foundation."
)


def is_valid_lifecycle_transition(
    from_status: MeshSessionStatus,
    to_status: MeshSessionStatus,
) -> bool:
    """Return ``True`` if transitioning *from_status* → *to_status* is valid.

    Parameters
    ----------
    from_status:
        Current :class:`MeshSessionStatus`.
    to_status:
        Desired target :class:`MeshSessionStatus`.

    Returns
    -------
    bool
        ``True`` when the transition is listed in
        :data:`MESH_SESSION_VALID_TRANSITIONS`.
    """
    allowed = MESH_SESSION_VALID_TRANSITIONS.get(from_status, set())
    return to_status in allowed


class MeshMergePolicy(str, Enum):
    """Policy governing how distributed subtask results are merged.

    Aligns with merge-owner semantics from PR-31 (HandoffEnvelopeV2) but
    is expressed independently here for contract stability.
    """

    NO_MERGE = "no_merge"
    """Results are independent — no merge step required."""

    SEQUENTIAL = "sequential"
    """Results must be merged in subtask completion order."""

    PARALLEL = "parallel"
    """Results may be merged in any order once all subtasks complete."""

    BARRIER = "barrier"
    """A synchronisation barrier must be reached before merge begins."""

    OWNER_DECIDES = "owner_decides"
    """The designated ``merge_owner_device_id`` determines merge strategy."""

    UNKNOWN = "unknown"
    """Merge policy has not yet been determined."""


class MeshBarrierPosture(str, Enum):
    """Synchronisation barrier posture for the session.

    Describes how devices synchronise before progressing to the next
    execution phase or initiating the merge step.
    """

    NO_BARRIER = "no_barrier"
    """No synchronisation barrier — devices proceed independently."""

    WAIT_PRIMARY = "wait_primary"
    """All participants wait for the primary device to signal readiness."""

    WAIT_ALL = "wait_all"
    """All participants must signal readiness before any proceeds."""

    WAIT_MERGE_OWNER = "wait_merge_owner"
    """Participants wait for the merge-owner device to signal."""

    SOFT_BARRIER = "soft_barrier"
    """Best-effort barrier — non-fatal if a participant fails to signal."""

    UNKNOWN = "unknown"
    """Barrier posture has not yet been determined."""


# ---------------------------------------------------------------------------
# Sub-contract: session participant
# ---------------------------------------------------------------------------


class MeshSessionParticipant(BaseModel):
    """A single device's participation record within a :class:`MeshSession`.

    Participation records are derived from membership contracts (PR-32) and
    device formation summaries (PR-17), but are expressed as a lightweight
    snapshot scoped to this specific session.

    All fields beyond ``device_id`` are optional so that records can be
    populated incrementally as the session progresses.
    """

    device_id: str = Field(
        default="",
        description="Unique identifier of the participating device.",
    )
    runtime_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional runtime/host identifier if the device exposes a "
            "LocalRuntimeHost (PR-30) within this session."
        ),
    )
    roles: List[str] = Field(
        default_factory=list,
        description=(
            "Roles this device carries within the session "
            "(e.g. 'primary', 'support', 'merge_owner', 'observer')."
        ),
    )
    authority_scope: Optional[str] = Field(
        default=None,
        description=(
            "Authority scope derived from the device's MeshMembership (PR-32) "
            "or formation hints (e.g. 'mesh_authority', 'execution_authority')."
        ),
    )
    online: Optional[bool] = Field(
        default=None,
        description="True if the device was observed to be online at session creation.",
    )
    health_score: Optional[float] = Field(
        default=None,
        description=(
            "Numeric health score at session creation time [0.0, 1.0]. "
            "Higher is healthier."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Sub-contract: subtask assignment
# ---------------------------------------------------------------------------


class MeshSubtaskAssignment(BaseModel):
    """A single subtask assignment within a :class:`MeshSession`.

    Subtask assignments capture which device was assigned a given subtask,
    what capability was required, and the outcome.  They are derived from
    ``TaskDecomposition.subtasks`` (core.schemas.orchestration) and related
    orchestration artefacts.

    All fields beyond ``subtask_id`` are optional.
    """

    subtask_id: str = Field(
        default_factory=lambda: f"sub_{uuid.uuid4().hex[:8]}",
        description="Unique identifier of the subtask.",
    )
    device_id: str = Field(
        default="",
        description="Device assigned to execute this subtask.",
    )
    capability_required: Optional[str] = Field(
        default=None,
        description=(
            "Capability or device type required for this subtask "
            "(e.g. 'camera', 'gpu', 'phone')."
        ),
    )
    status: str = Field(
        default="pending",
        description=(
            "Execution status of this subtask assignment "
            "('pending', 'running', 'success', 'failed', 'skipped', 'cancelled')."
        ),
    )
    result_ref: Optional[str] = Field(
        default=None,
        description=(
            "Optional reference or key pointing to the subtask's result "
            "artefact (e.g. a task-ledger key or storage path)."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string."""
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Top-level contract: MeshSession
# ---------------------------------------------------------------------------


class MeshSession(BaseModel):
    """Canonical multi-device cooperative session contract.

    A ``MeshSession`` is the single object that represents an active
    cooperation between two or more runtime-capable devices on one task flow.

    It answers:
    - *Who participates?* — ``participants``
    - *Who initiated?* — ``source_device_id``
    - *Who executes primarily?* — ``primary_device_id``
    - *How are subtasks assigned?* — ``subtask_assignments``
    - *How and when are results merged?* — ``merge_policy``, ``merge_owner_device_id``
    - *How do devices synchronise?* — ``barrier_posture``
    - *What is the session lifecycle state?* — ``status``

    This contract is the foundation for PR-34 (Target Runtime Local Takeover
    Path), PR-35 (Source Runtime Dispatch Orchestrator), and PR-37 (Mesh
    Session Coordinator).  It is intentionally read-only and does not include
    write-capable command or control surfaces.

    All fields beyond ``session_id`` are optional so that instances can be
    constructed incrementally from partial data sources.
    """

    session_id: str = Field(
        default_factory=lambda: f"msess_{uuid.uuid4().hex[:12]}",
        description="Stable, globally-unique identifier for this mesh session.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional execution trace identifier (PR-25 ExecutionTraceEnvelope) "
            "linking this session to a trace chain."
        ),
    )
    task_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional task identifier correlating this session to an "
            "originating task request."
        ),
    )
    mesh_id: Optional[str] = Field(
        default=None,
        description=(
            "Optional mesh/body identifier associating this session with a "
            "specific device formation (PR-17) or mesh membership (PR-32)."
        ),
    )
    source_device_id: str = Field(
        default="",
        description="Device ID that originated/initiated this mesh session.",
    )
    primary_device_id: str = Field(
        default="",
        description=(
            "Device ID of the primary executor — the device anchoring the "
            "cognitive session and responsible for the overall task outcome."
        ),
    )
    merge_owner_device_id: Optional[str] = Field(
        default=None,
        description=(
            "Device ID responsible for aggregating and merging distributed "
            "subtask results.  May be the same as ``primary_device_id``."
        ),
    )
    participants: List[MeshSessionParticipant] = Field(
        default_factory=list,
        description=(
            "All devices participating in this session, including their "
            "roles, authority scopes, and health hints."
        ),
    )
    subtask_assignments: List[MeshSubtaskAssignment] = Field(
        default_factory=list,
        description=(
            "Per-device subtask assignment records derived from the task "
            "decomposition and orchestration artefacts."
        ),
    )
    barrier_posture: MeshBarrierPosture = Field(
        default=MeshBarrierPosture.UNKNOWN,
        description="Synchronisation barrier posture governing cross-device coordination.",
    )
    merge_policy: MeshMergePolicy = Field(
        default=MeshMergePolicy.UNKNOWN,
        description="Policy governing how distributed subtask results are merged.",
    )
    multi_device_required: bool = Field(
        default=False,
        description=(
            "True if this session *requires* multiple devices to complete "
            "successfully.  False if multi-device is opportunistic."
        ),
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description=(
            "True if a human or coordinator confirmation is required before "
            "the merge step can proceed."
        ),
    )
    status: MeshSessionStatus = Field(
        default=MeshSessionStatus.PENDING,
        description="Lifecycle status of the session.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds) when this contract was created.",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp (seconds) of the most recent update.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation.

        All enum values are serialised as their string values.  Nested
        sub-contracts (participants, subtask_assignments) are recursively
        expanded.
        """
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string.

        Parameters
        ----------
        indent:
            Optional indentation level for pretty-printing.
        """
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshSession":
        """Construct a :class:`MeshSession` from a dictionary.

        Tolerates unknown extra fields; missing optional fields fall back to
        their defaults.
        """
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact human-readable summary dict.

        Suitable for logging, dashboard tiles, and trace metadata.
        """
        return {
            "session_id": self.session_id,
            "status": self.status.value if isinstance(self.status, MeshSessionStatus) else str(self.status),
            "source_device_id": self.source_device_id,
            "primary_device_id": self.primary_device_id,
            "merge_owner_device_id": self.merge_owner_device_id,
            "participant_count": len(self.participants),
            "subtask_count": len(self.subtask_assignments),
            "multi_device_required": self.multi_device_required,
            "merge_policy": self.merge_policy.value if isinstance(self.merge_policy, MeshMergePolicy) else str(self.merge_policy),
            "barrier_posture": self.barrier_posture.value if isinstance(self.barrier_posture, MeshBarrierPosture) else str(self.barrier_posture),
            "mesh_id": self.mesh_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
        }

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    """Safely convert *value* to str, returning *default* on None/empty."""
    if value is None:
        return default
    result = str(value).strip()
    return result if result else default


def _safe_list(value: Any) -> List[str]:
    """Safely convert *value* to a list of non-empty strings."""
    if value is None:
        return []
    try:
        return [str(v) for v in value if v is not None and str(v).strip()]
    except Exception:
        return []


def _map_barrier_posture(raw: Any) -> MeshBarrierPosture:
    """Map a raw barrier_posture value to :class:`MeshBarrierPosture`."""
    if raw is None:
        return MeshBarrierPosture.UNKNOWN
    raw_str = raw.value if hasattr(raw, "value") else str(raw).lower().strip()
    mapping = {
        "no_barrier": MeshBarrierPosture.NO_BARRIER,
        "wait_primary": MeshBarrierPosture.WAIT_PRIMARY,
        "wait_all": MeshBarrierPosture.WAIT_ALL,
        "wait_merge_owner": MeshBarrierPosture.WAIT_MERGE_OWNER,
        "soft_barrier": MeshBarrierPosture.SOFT_BARRIER,
        "unknown": MeshBarrierPosture.UNKNOWN,
    }
    return mapping.get(raw_str, MeshBarrierPosture.UNKNOWN)


def _map_merge_policy(raw: Any) -> MeshMergePolicy:
    """Map a raw merge_policy value to :class:`MeshMergePolicy`."""
    if raw is None:
        return MeshMergePolicy.UNKNOWN
    raw_str = raw.value if hasattr(raw, "value") else str(raw).lower().strip()
    mapping = {
        "no_merge": MeshMergePolicy.NO_MERGE,
        "sequential": MeshMergePolicy.SEQUENTIAL,
        "parallel": MeshMergePolicy.PARALLEL,
        "barrier": MeshMergePolicy.BARRIER,
        "owner_decides": MeshMergePolicy.OWNER_DECIDES,
        "unknown": MeshMergePolicy.UNKNOWN,
    }
    return mapping.get(raw_str, MeshMergePolicy.UNKNOWN)


def _map_session_status(raw: Any) -> MeshSessionStatus:
    """Map a raw status value to :class:`MeshSessionStatus`."""
    if raw is None:
        return MeshSessionStatus.UNKNOWN
    raw_str = raw.value if hasattr(raw, "value") else str(raw).lower().strip()
    mapping = {
        "pending": MeshSessionStatus.PENDING,
        "active": MeshSessionStatus.ACTIVE,
        "merging": MeshSessionStatus.MERGING,
        "suspended": MeshSessionStatus.SUSPENDED,
        "restoring": MeshSessionStatus.RESTORING,
        "completed": MeshSessionStatus.COMPLETED,
        "cancelled": MeshSessionStatus.CANCELLED,
        "failed": MeshSessionStatus.FAILED,
        "unknown": MeshSessionStatus.UNKNOWN,
    }
    return mapping.get(raw_str, MeshSessionStatus.UNKNOWN)


def _subtask_status_to_assignment_status(raw: Any) -> str:
    """Normalise a SubTaskStatus value to an assignment status string."""
    if raw is None:
        return "pending"
    raw_str = raw.value if hasattr(raw, "value") else str(raw).lower().strip()
    valid = {"pending", "running", "success", "failed", "skipped", "cancelled"}
    return raw_str if raw_str in valid else "pending"


# ---------------------------------------------------------------------------
# Adapter: from FormationSummary (core.device_formation)
# ---------------------------------------------------------------------------


def from_device_formation_summary(
    summary: Any,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: Optional[MeshSessionStatus] = None,
) -> "MeshSession":
    """Build a :class:`MeshSession` from a ``FormationSummary``
    (``core.device_formation``).

    Parameters
    ----------
    summary:
        A ``core.device_formation.FormationSummary`` instance (or any object
        with the expected attributes).
    session_id:
        Optional explicit session ID.  Defaults to a fresh UUID.
    task_id:
        Optional task ID to embed in the session.
    trace_id:
        Optional trace ID (PR-25) to embed in the session.
    status:
        Optional explicit lifecycle status.  Defaults to ``PENDING``.

    Returns
    -------
    MeshSession
        Populated contract.  Returns a minimal stub when ``summary`` is
        ``None`` or has no device information.
    """
    if summary is None:
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            status=status or MeshSessionStatus.UNKNOWN,
            metadata={"adapter_source": "from_device_formation_summary", "empty": True},
        )

    try:
        formation_id = _safe_str(getattr(summary, "formation_id", None))
        source_id = _safe_str(getattr(summary, "source_device_id", None))
        primary_id = _safe_str(getattr(summary, "primary_execution_device_id", None))
        merge_owner = _safe_str(getattr(summary, "merge_owner_device_id", None)) or None

        fallback_ids = _safe_list(getattr(summary, "fallback_device_ids", None))
        support_ids = _safe_list(getattr(summary, "support_device_ids", None))
        observer_ids = _safe_list(getattr(summary, "observer_device_ids", None))
        relay_ids = _safe_list(getattr(summary, "relay_device_ids", None))

        barrier_posture = _map_barrier_posture(getattr(summary, "barrier_posture", None))
        merge_policy = _map_merge_policy(getattr(summary, "merge_policy", None))
        multi_req = bool(getattr(summary, "multi_device_required", False))
        merge_req = bool(getattr(summary, "merge_confirmation_required", False))

        # Build participants from known device IDs
        seen: set = set()
        participants: List[MeshSessionParticipant] = []

        def _add_participant(did: str, roles: List[str]) -> None:
            if not did or did in seen:
                return
            seen.add(did)
            participants.append(
                MeshSessionParticipant(device_id=did, roles=roles)
            )

        _add_participant(source_id, ["source"])
        if primary_id and primary_id != source_id:
            _add_participant(primary_id, ["primary"])
        elif primary_id == source_id and source_id:
            # source is also primary — update roles
            for p in participants:
                if p.device_id == source_id and "primary" not in p.roles:
                    p.roles.append("primary")

        for did in fallback_ids:
            _add_participant(did, ["fallback"])
        for did in support_ids:
            _add_participant(did, ["support"])
        for did in observer_ids:
            _add_participant(did, ["observer"])
        for did in relay_ids:
            _add_participant(did, ["relay"])
        if merge_owner:
            _add_participant(merge_owner, ["merge_owner"])

        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            mesh_id=formation_id or None,
            source_device_id=source_id,
            primary_device_id=primary_id,
            merge_owner_device_id=merge_owner or None,
            participants=participants,
            subtask_assignments=[],
            barrier_posture=barrier_posture,
            merge_policy=merge_policy,
            multi_device_required=multi_req,
            merge_confirmation_required=merge_req,
            status=status or MeshSessionStatus.PENDING,
            metadata={
                "adapter_source": "from_device_formation_summary",
                "formation_id": formation_id,
            },
        )

    except Exception as exc:  # pragma: no cover — defensive
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            status=MeshSessionStatus.UNKNOWN,
            metadata={
                "adapter_source": "from_device_formation_summary",
                "error": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Adapter: from CrossDeviceAssignmentSummary (core.cross_device_policy)
# ---------------------------------------------------------------------------


def from_cross_device_routing_summary(
    summary: Any,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status: Optional[MeshSessionStatus] = None,
) -> "MeshSession":
    """Build a :class:`MeshSession` from a ``CrossDeviceAssignmentSummary``
    (``core.cross_device_policy``).

    Parameters
    ----------
    summary:
        A ``core.cross_device_policy.CrossDeviceAssignmentSummary`` instance
        (or any object with the expected attributes).
    session_id:
        Optional explicit session ID.
    task_id:
        Optional task ID to embed.
    trace_id:
        Optional trace ID (PR-25) to embed.
    status:
        Optional explicit lifecycle status.

    Returns
    -------
    MeshSession
        Populated contract.  Returns a minimal stub when ``summary`` is
        ``None``.
    """
    if summary is None:
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            status=status or MeshSessionStatus.UNKNOWN,
            metadata={"adapter_source": "from_cross_device_routing_summary", "empty": True},
        )

    try:
        source_id = _safe_str(getattr(summary, "source_device_id", None))
        primary_id = _safe_str(getattr(summary, "primary_device_id", None))
        mesh_id = _safe_str(getattr(summary, "mesh_id", None)) or _safe_str(
            getattr(summary, "session_id", None)
        ) or None
        multi_req = bool(getattr(summary, "multi_device_required", False))
        merge_req = bool(getattr(summary, "merge_confirmation_required", False))
        merge_owner = _safe_str(getattr(summary, "merge_owner_device_id", None)) or None

        # Derive barrier/merge from routing posture
        routing_posture = getattr(summary, "routing_posture", None)
        posture_str = (
            routing_posture.value
            if hasattr(routing_posture, "value")
            else str(routing_posture).lower()
            if routing_posture is not None
            else ""
        )

        if "split" in posture_str or "parallel" in posture_str:
            merge_policy = MeshMergePolicy.PARALLEL
            barrier_posture = MeshBarrierPosture.WAIT_ALL
        elif "sequential" in posture_str:
            merge_policy = MeshMergePolicy.SEQUENTIAL
            barrier_posture = MeshBarrierPosture.WAIT_PRIMARY
        elif "remote" in posture_str:
            merge_policy = MeshMergePolicy.NO_MERGE
            barrier_posture = MeshBarrierPosture.NO_BARRIER
        else:
            merge_policy = _map_merge_policy(getattr(summary, "merge_policy", None))
            barrier_posture = _map_barrier_posture(getattr(summary, "barrier_posture", None))

        # Build participants from device lists
        seen: set = set()
        participants: List[MeshSessionParticipant] = []

        def _add_participant(did: str, roles: List[str]) -> None:
            if not did or did in seen:
                return
            seen.add(did)
            participants.append(
                MeshSessionParticipant(device_id=did, roles=roles)
            )

        _add_participant(source_id, ["source"])
        if primary_id and primary_id != source_id:
            _add_participant(primary_id, ["primary"])
        elif primary_id == source_id and source_id:
            for p in participants:
                if p.device_id == source_id and "primary" not in p.roles:
                    p.roles.append("primary")

        for did in _safe_list(getattr(summary, "assigned_device_ids", None)):
            _add_participant(did, ["support"])
        for did in _safe_list(getattr(summary, "fallback_device_ids", None)):
            _add_participant(did, ["fallback"])
        if merge_owner:
            _add_participant(merge_owner, ["merge_owner"])

        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            mesh_id=mesh_id,
            source_device_id=source_id,
            primary_device_id=primary_id,
            merge_owner_device_id=merge_owner,
            participants=participants,
            subtask_assignments=[],
            barrier_posture=barrier_posture,
            merge_policy=merge_policy,
            multi_device_required=multi_req,
            merge_confirmation_required=merge_req,
            status=status or MeshSessionStatus.PENDING,
            metadata={
                "adapter_source": "from_cross_device_routing_summary",
                "routing_posture": posture_str or None,
            },
        )

    except Exception as exc:  # pragma: no cover — defensive
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            status=MeshSessionStatus.UNKNOWN,
            metadata={
                "adapter_source": "from_cross_device_routing_summary",
                "error": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Adapter: from TaskDecomposition (core.schemas.orchestration)
# ---------------------------------------------------------------------------


def from_constellation_decomposition(
    decomposition: Any,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    primary_device_id: str = "",
    mesh_id: Optional[str] = None,
    status: Optional[MeshSessionStatus] = None,
) -> "MeshSession":
    """Build a :class:`MeshSession` from a ``TaskDecomposition``
    (``core.schemas.orchestration``).

    This adapter materialises subtask assignment records from the
    decomposition's ``subtasks`` list.

    Parameters
    ----------
    decomposition:
        A ``core.schemas.orchestration.TaskDecomposition`` instance (or any
        object with a ``subtasks`` iterable of objects with ``task_id``,
        ``device_id``, ``device_type``, ``status``, and ``result``
        attributes).
    session_id:
        Optional explicit session ID.
    task_id:
        Optional task ID to embed.
    trace_id:
        Optional trace ID (PR-25) to embed.
    source_device_id:
        Device ID of the session initiator.
    primary_device_id:
        Device ID of the primary executor.
    mesh_id:
        Optional mesh ID.
    status:
        Optional explicit lifecycle status.

    Returns
    -------
    MeshSession
        Populated contract with ``subtask_assignments`` derived from the
        decomposition.  Returns a minimal stub when ``decomposition`` is
        ``None``.
    """
    if decomposition is None:
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            source_device_id=source_device_id,
            primary_device_id=primary_device_id,
            mesh_id=mesh_id,
            status=status or MeshSessionStatus.UNKNOWN,
            metadata={"adapter_source": "from_constellation_decomposition", "empty": True},
        )

    try:
        subtask_list = getattr(decomposition, "subtasks", None) or []
        assignments: List[MeshSubtaskAssignment] = []
        device_ids_seen: set = set()

        for subtask in subtask_list:
            try:
                st_id = _safe_str(getattr(subtask, "task_id", None)) or f"sub_{uuid.uuid4().hex[:8]}"
                st_device = _safe_str(getattr(subtask, "device_id", None))
                st_cap = _safe_str(getattr(subtask, "device_type", None)) or None
                st_status = _subtask_status_to_assignment_status(
                    getattr(subtask, "status", None)
                )
                st_result = getattr(subtask, "result", None)
                result_ref: Optional[str] = None
                if st_result is not None:
                    try:
                        result_ref = json.dumps(st_result)
                    except Exception:
                        result_ref = str(st_result)

                assignments.append(
                    MeshSubtaskAssignment(
                        subtask_id=st_id,
                        device_id=st_device,
                        capability_required=st_cap,
                        status=st_status,
                        result_ref=result_ref,
                        metadata={
                            "name": _safe_str(getattr(subtask, "name", None)),
                            "action": _safe_str(getattr(subtask, "action", None)),
                        },
                    )
                )
                if st_device:
                    device_ids_seen.add(st_device)
            except Exception:
                continue

        # Build participants from involved device IDs
        seen: set = set()
        participants: List[MeshSessionParticipant] = []

        def _add_participant(did: str, roles: List[str]) -> None:
            if not did or did in seen:
                return
            seen.add(did)
            participants.append(
                MeshSessionParticipant(device_id=did, roles=roles)
            )

        _add_participant(source_device_id, ["source"])
        if primary_device_id and primary_device_id != source_device_id:
            _add_participant(primary_device_id, ["primary"])
        elif primary_device_id == source_device_id and source_device_id:
            for p in participants:
                if p.device_id == source_device_id and "primary" not in p.roles:
                    p.roles.append("primary")

        for did in device_ids_seen:
            if did not in seen:
                _add_participant(did, ["support"])

        # Infer status from subtask statuses when not given
        effective_status = status
        if effective_status is None:
            statuses = {a.status for a in assignments}
            if not statuses:
                effective_status = MeshSessionStatus.PENDING
            elif "failed" in statuses:
                effective_status = MeshSessionStatus.FAILED
            elif all(s == "success" for s in statuses):
                effective_status = MeshSessionStatus.COMPLETED
            elif "running" in statuses:
                effective_status = MeshSessionStatus.ACTIVE
            else:
                effective_status = MeshSessionStatus.PENDING

        multi_req = len(device_ids_seen) > 1

        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            mesh_id=mesh_id,
            source_device_id=source_device_id,
            primary_device_id=primary_device_id,
            participants=participants,
            subtask_assignments=assignments,
            multi_device_required=multi_req,
            status=effective_status,
            metadata={
                "adapter_source": "from_constellation_decomposition",
                "goal": _safe_str(getattr(decomposition, "goal", None)),
            },
        )

    except Exception as exc:  # pragma: no cover — defensive
        return MeshSession(
            session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            trace_id=trace_id,
            source_device_id=source_device_id,
            primary_device_id=primary_device_id,
            mesh_id=mesh_id,
            status=MeshSessionStatus.UNKNOWN,
            metadata={
                "adapter_source": "from_constellation_decomposition",
                "error": str(exc),
            },
        )


# ---------------------------------------------------------------------------
# Builder: generic convenience factory
# ---------------------------------------------------------------------------


def build_mesh_session(
    source_device_id: str = "",
    primary_device_id: str = "",
    *,
    session_id: Optional[str] = None,
    task_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    mesh_id: Optional[str] = None,
    merge_owner_device_id: Optional[str] = None,
    participants: Optional[List[MeshSessionParticipant]] = None,
    subtask_assignments: Optional[List[MeshSubtaskAssignment]] = None,
    barrier_posture: MeshBarrierPosture = MeshBarrierPosture.UNKNOWN,
    merge_policy: MeshMergePolicy = MeshMergePolicy.UNKNOWN,
    multi_device_required: bool = False,
    merge_confirmation_required: bool = False,
    status: MeshSessionStatus = MeshSessionStatus.PENDING,
    metadata: Optional[Dict[str, Any]] = None,
) -> MeshSession:
    """Convenience factory for constructing a :class:`MeshSession` from
    scratch.

    All parameters are keyword-safe.  At minimum, supply
    ``source_device_id`` and ``primary_device_id`` for a meaningful session.

    Parameters
    ----------
    source_device_id:
        Device ID of the session initiator.
    primary_device_id:
        Device ID of the primary executor.
    session_id:
        Optional explicit session ID.  Auto-generated if not supplied.
    task_id:
        Optional task ID.
    trace_id:
        Optional trace ID (PR-25).
    mesh_id:
        Optional mesh/formation ID.
    merge_owner_device_id:
        Optional merge-owner device ID.
    participants:
        Optional pre-built participant list.
    subtask_assignments:
        Optional pre-built subtask assignment list.
    barrier_posture:
        Synchronisation barrier posture.
    merge_policy:
        Merge policy.
    multi_device_required:
        Whether the session requires multiple devices.
    merge_confirmation_required:
        Whether a human confirmation is needed before merge.
    status:
        Lifecycle status.
    metadata:
        Optional metadata dict.

    Returns
    -------
    MeshSession
    """
    return MeshSession(
        session_id=session_id or f"msess_{uuid.uuid4().hex[:12]}",
        task_id=task_id,
        trace_id=trace_id,
        mesh_id=mesh_id,
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        merge_owner_device_id=merge_owner_device_id,
        participants=participants or [],
        subtask_assignments=subtask_assignments or [],
        barrier_posture=barrier_posture,
        merge_policy=merge_policy,
        multi_device_required=multi_device_required,
        merge_confirmation_required=merge_confirmation_required,
        status=status,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Public __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Enumerations
    "MeshSessionStatus",
    "MeshMergePolicy",
    "MeshBarrierPosture",
    # Lifecycle helpers
    "MESH_SESSION_TERMINAL_STATUSES",
    "MESH_SESSION_RESTORABLE_STATUSES",
    "MESH_SESSION_VALID_TRANSITIONS",
    "MESH_SESSION_LIFECYCLE_IS_EXPLICIT",
    "is_valid_lifecycle_transition",
    # Sub-contracts
    "MeshSessionParticipant",
    "MeshSubtaskAssignment",
    # Top-level contract
    "MeshSession",
    # Adapters / builders
    "from_device_formation_summary",
    "from_cross_device_routing_summary",
    "from_constellation_decomposition",
    "build_mesh_session",
]
