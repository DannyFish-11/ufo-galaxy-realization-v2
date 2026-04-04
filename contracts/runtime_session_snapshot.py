"""contracts/runtime_session_snapshot.py
=========================================
Durable Runtime Session Snapshot Contract — PR-40.

This module defines the **canonical Durable Runtime Session Snapshot**:
a single, fully serialisable, persistence-friendly contract that captures the
complete known state of a runtime session at a given point in time.

It answers the architectural question:

    *"If we need one stable snapshot of a runtime session that can be
    persisted, reloaded, projected, or inspected later, what is the
    canonical contract for that snapshot?"*

This is the stable durable read-model for a runtime session — distinct from:

- :class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`
  (live multi-device read-model; may change continuously)
- :class:`~contracts.mesh_session.MeshSession`
  (mesh-specific session membership and assignment state)
- :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
  (coordination event log and barrier state)
- :class:`~contracts.runtime_recovery_reconciliation.RuntimeReconciliationState`
  (recovery and reconciliation advisory posture)

A ``RuntimeSessionSnapshot`` is the canonical *durable* form: a single
stable object that can be persisted, reloaded, diffed, and replayed.

Contract chain consumed
-----------------------
- **PR-29** (:class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`)
- **PR-30** (:class:`~contracts.local_runtime_host.LocalRuntimeHost`)
- **PR-32** (:class:`~contracts.mesh_membership.MeshMembership`)
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`)
- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`)
- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchResult`)
- **PR-36** (:class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`)
- **PR-37** (:class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`)
- **PR-38** (:class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`)
- **PR-39** (:class:`~contracts.runtime_recovery_reconciliation.RuntimeReconciliationState`)
- **PR-27/28** — governance snapshot / policy alignment (optional summary dicts)

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — ``to_dict`` / ``to_json`` / ``from_dict`` produce
  stable, round-trippable output.
- **Persistence-friendly** — stable field names, no storage-backend semantics.
- **Graceful defaults** — all collection fields default to empty lists/dicts;
  all optional scalar fields default to ``None``.
- **Tolerant of partial/missing data** — all builders accept ``None`` gracefully.
- **No UI semantics** — purely a runtime/persistence contract.
- **No write/persist engine** — this PR defines the contract only.

Usage::

    from contracts.runtime_session_snapshot import (
        RuntimeSessionSnapshot,
        build_runtime_session_snapshot,
    )

    snapshot = build_runtime_session_snapshot(
        session_id="sess_abc123",
        source_device_id="phone_001",
    )
    print(snapshot.to_json(indent=2))

See ``docs/DURABLE_RUNTIME_SESSION_SNAPSHOT.md`` for the full specification.
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


class RuntimeSessionSnapshotStatus(str, Enum):
    """Overall lifecycle status of a durable runtime session snapshot.

    active
        The session is currently in progress; this snapshot reflects the
        last known live state.
    completed
        The session has completed successfully.  All result units are
        authoritative.
    failed
        The session ended in failure.  One or more critical components
        could not be resolved.
    partial
        The session completed partially; some participants succeeded while
        others failed or are still pending.
    interrupted
        The session was interrupted before completion (e.g. handoff not
        acknowledged, coordinator lost).
    recovering
        The session is in a recovery/reconciliation cycle.
    unknown
        Status cannot be determined from available context.
    """

    active = "active"
    completed = "completed"
    failed = "failed"
    partial = "partial"
    interrupted = "interrupted"
    recovering = "recovering"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# Sub-contracts (snapshot blocks)
# ---------------------------------------------------------------------------


class RuntimeSessionSnapshotIdentity(BaseModel):
    """Identity block for a durable runtime session snapshot.

    Captures the stable identifiers that link this snapshot to the wider
    execution lifecycle and mesh graph.

    Fields
    ------
    snapshot_id
        Unique, globally-stable identifier for this snapshot instance.
    session_id
        The runtime session this snapshot belongs to.
    trace_id
        Optional execution trace identifier (PR-25).
    task_id
        Optional task identifier.
    mesh_session_id
        Optional mesh session identifier (PR-33).
    source_device_id
        Optional device that originated this session.
    primary_device_id
        Optional device designated as primary for result authority.
    created_at
        Unix epoch seconds when the snapshot was first created.
    updated_at
        Unix epoch seconds when the snapshot was last updated.
    metadata
        Arbitrary extensibility bag.
    """

    snapshot_id: str = Field(
        default_factory=lambda: f"rsnap_{uuid.uuid4().hex[:12]}",
        description="Unique, globally-stable identifier for this snapshot instance.",
    )
    session_id: str = Field(
        description="The runtime session this snapshot belongs to.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional execution trace identifier (PR-25).",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Optional mesh session identifier (PR-33).",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Optional device that originated this session.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description="Optional device designated as primary for result authority.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture for this session. "
            "Must be 'control_only' or 'join_runtime'. "
            "PR-4, post-533 dual-repo runtime host unification track."
        ),
    )
    coordination_role: str = Field(
        default="",
        description=(
            "Multi-device coordination role of the source device "
            "(e.g. 'source_controller', 'joined_runtime_participant', "
            "'observer_only', 'target_only_executor').  Empty when not "
            "applicable.  PR-4 / PR-6, post-533 dual-repo runtime host "
            "unification track."
        ),
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when the snapshot was first created.",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when the snapshot was last updated.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotIdentity":
        return cls.model_validate(data)


class RuntimeSessionSnapshotDispatchState(BaseModel):
    """Snapshot of the source dispatch state for this session (PR-35).

    A compact, stable view of the last-known source dispatch result.

    Fields
    ------
    dispatch_id
        Stable identifier of the captured dispatch result.
    dispatch_mode
        Mode resolved by the source dispatch orchestrator.
    dispatch_status
        Last-known status of the dispatch.
    target_device_ids
        Device IDs that were selected as dispatch targets.
    plan_id
        Optional dispatch plan identifier.
    reason
        Human-readable dispatch outcome description.
    metadata
        Arbitrary extensibility bag.
    """

    dispatch_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the captured dispatch result.",
    )
    dispatch_mode: Optional[str] = Field(
        default=None,
        description="Mode resolved by the source dispatch orchestrator.",
    )
    dispatch_status: Optional[str] = Field(
        default=None,
        description="Last-known status of the dispatch.",
    )
    target_device_ids: List[str] = Field(
        default_factory=list,
        description="Device IDs that were selected as dispatch targets.",
    )
    plan_id: Optional[str] = Field(
        default=None,
        description="Optional dispatch plan identifier.",
    )
    reason: str = Field(
        default="",
        description="Human-readable dispatch outcome description.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture at dispatch time. "
            "Must be 'control_only' or 'join_runtime'. "
            "PR-4, post-533 dual-repo runtime host unification track."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotDispatchState":
        return cls.model_validate(data)


class RuntimeSessionSnapshotTakeoverState(BaseModel):
    """Snapshot of a single target-side takeover result for this session (PR-34).

    Fields
    ------
    takeover_id
        Stable identifier of the captured takeover result.
    target_device_id
        Device that attempted or completed the takeover.
    takeover_status
        Last-known status of the takeover on this device.
    session_context_id
        Optional runtime session context identifier on the target.
    reason
        Human-readable takeover outcome description.
    metadata
        Arbitrary extensibility bag.
    """

    takeover_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the captured takeover result.",
    )
    target_device_id: Optional[str] = Field(
        default=None,
        description="Device that attempted or completed the takeover.",
    )
    takeover_status: Optional[str] = Field(
        default=None,
        description="Last-known status of the takeover on this device.",
    )
    session_context_id: Optional[str] = Field(
        default=None,
        description="Optional runtime session context identifier on the target.",
    )
    reason: str = Field(
        default="",
        description="Human-readable takeover outcome description.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotTakeoverState":
        return cls.model_validate(data)


class RuntimeSessionSnapshotCoordinatorState(BaseModel):
    """Snapshot of the mesh session coordinator state for this session (PR-37).

    Fields
    ------
    coordinator_id
        Stable identifier of the captured coordinator state.
    coordinator_status
        Last-known status of the coordinator.
    participant_count
        Number of participants registered with the coordinator.
    assignment_count
        Number of subtask assignments tracked by the coordinator.
    barrier_active
        Whether a mesh barrier was active at snapshot time.
    event_count
        Number of coordination events recorded.
    metadata
        Arbitrary extensibility bag.
    """

    coordinator_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the captured coordinator state.",
    )
    coordinator_status: Optional[str] = Field(
        default=None,
        description="Last-known status of the coordinator.",
    )
    participant_count: int = Field(
        default=0,
        description="Number of participants registered with the coordinator.",
    )
    assignment_count: int = Field(
        default=0,
        description="Number of subtask assignments tracked by the coordinator.",
    )
    barrier_active: bool = Field(
        default=False,
        description="Whether a mesh barrier was active at snapshot time.",
    )
    event_count: int = Field(
        default=0,
        description="Number of coordination events recorded.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotCoordinatorState":
        return cls.model_validate(data)


class RuntimeSessionSnapshotResultState(BaseModel):
    """Snapshot of the cross-runtime merged result state for this session (PR-36).

    Fields
    ------
    merge_id
        Stable identifier of the captured merged result.
    merge_status
        Last-known merge status.
    authoritative_unit_ids
        IDs of result units confirmed as authoritative.
    stale_unit_ids
        IDs of result units that are stale.
    pending_unit_ids
        IDs of result units pending confirmation.
    result_unit_count
        Total number of result units in the merge.
    merge_policy
        Policy under which results were merged.
    metadata
        Arbitrary extensibility bag.
    """

    merge_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the captured merged result.",
    )
    merge_status: Optional[str] = Field(
        default=None,
        description="Last-known merge status.",
    )
    authoritative_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units confirmed as authoritative.",
    )
    stale_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units that are stale.",
    )
    pending_unit_ids: List[str] = Field(
        default_factory=list,
        description="IDs of result units pending confirmation.",
    )
    result_unit_count: int = Field(
        default=0,
        description="Total number of result units in the merge.",
    )
    merge_policy: Optional[str] = Field(
        default=None,
        description="Policy under which results were merged.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture at result merge time. "
            "Must be 'control_only' or 'join_runtime'. "
            "PR-4, post-533 dual-repo runtime host unification track."
        ),
    )
    coordination_role: str = Field(
        default="",
        description=(
            "Multi-device coordination role of the source device at result "
            "merge time.  Empty when not applicable.  "
            "PR-4 / PR-6, post-533 dual-repo runtime host unification track."
        ),
    )
    excluded_unit_ids: List[str] = Field(
        default_factory=list,
        description=(
            "IDs of result units excluded by posture-aware or "
            "coordination-role-aware filtering.  "
            "Includes units excluded because they were tagged as control_only "
            "source contributions or observer_only coordination role.  PR-4."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotResultState":
        return cls.model_validate(data)


class RuntimeSessionSnapshotRecoveryState(BaseModel):
    """Snapshot of the runtime recovery and reconciliation posture (PR-39).

    Fields
    ------
    reconciliation_id
        Stable identifier of the captured reconciliation state.
    recovery_status
        Overall recovery/reconciliation status at snapshot time.
    incident_count
        Total number of recovery incidents detected.
    replay_required
        Whether replay of any work was required.
    resume_allowed
        Whether local resume was a valid recovery path.
    merge_confirmation_required
        Whether merge confirmation was required.
    has_barrier
        Whether a recovery barrier was active.
    reason
        Human-readable recovery posture description.
    metadata
        Arbitrary extensibility bag.
    """

    reconciliation_id: Optional[str] = Field(
        default=None,
        description="Stable identifier of the captured reconciliation state.",
    )
    recovery_status: Optional[str] = Field(
        default=None,
        description="Overall recovery/reconciliation status at snapshot time.",
    )
    incident_count: int = Field(
        default=0,
        description="Total number of recovery incidents detected.",
    )
    replay_required: bool = Field(
        default=False,
        description="Whether replay of any work was required.",
    )
    resume_allowed: bool = Field(
        default=False,
        description="Whether local resume was a valid recovery path.",
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description="Whether merge confirmation was required.",
    )
    has_barrier: bool = Field(
        default=False,
        description="Whether a recovery barrier was active.",
    )
    reason: str = Field(
        default="",
        description="Human-readable recovery posture description.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotRecoveryState":
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Top-level snapshot contract
# ---------------------------------------------------------------------------


class RuntimeSessionSnapshot(BaseModel):
    """Canonical durable runtime session snapshot.

    The top-level contract that captures all known runtime session state
    in a single, stable, fully serialisable object.  This is the answer to:

        *"What is the stable, durable snapshot shape of a runtime session?"*

    It is suitable for persistence, rehydration, audit, diff, and replay.

    Fields
    ------
    snapshot_id
        Unique, globally-stable identifier for this snapshot instance.
    session_id
        The runtime session this snapshot belongs to.
    trace_id
        Optional execution trace identifier (PR-25).
    task_id
        Optional task identifier.
    mesh_session_id
        Optional mesh session identifier (PR-33).
    source_device_id
        Optional device that originated this session.
    primary_device_id
        Optional device designated as primary for result authority.
    created_at
        Unix epoch seconds when the snapshot was first created.
    updated_at
        Unix epoch seconds when the snapshot was last updated.
    status
        Overall lifecycle status of this session snapshot.
    runtime_devices
        Compact entries for all registered runtime devices in this session.
    runtime_hosts
        Compact entries for all local runtime hosts in this session.
    mesh_memberships
        Compact entries for mesh memberships in this session.
    mesh_session
        Optional snapshot of the mesh session state (PR-33).
    dispatch_state
        Optional snapshot of the source dispatch state (PR-35).
    takeover_states
        Snapshots of all target-side takeover results (PR-34).
    coordinator_state
        Optional snapshot of the mesh session coordinator state (PR-37).
    merged_result
        Optional snapshot of the cross-runtime merged result state (PR-36).
    recovery_state
        Optional snapshot of the recovery/reconciliation posture (PR-39).
    governance_snapshot
        Optional governance snapshot dict (PR-27).
    policy_alignment
        Optional policy alignment dict (PR-28).
    metadata
        Arbitrary extensibility bag.
    """

    # Identity
    snapshot_id: str = Field(
        default_factory=lambda: f"rsnap_{uuid.uuid4().hex[:12]}",
        description="Unique, globally-stable identifier for this snapshot instance.",
    )
    session_id: str = Field(
        default="",
        description="The runtime session this snapshot belongs to.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional execution trace identifier (PR-25).",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Optional mesh session identifier (PR-33).",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Optional device that originated this session.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description="Optional device designated as primary for result authority.",
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture for this session. "
            "Must be 'control_only' or 'join_runtime'. "
            "PR-4, post-533 dual-repo runtime host unification track."
        ),
    )

    # Timestamps
    created_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when the snapshot was first created.",
    )
    updated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when the snapshot was last updated.",
    )

    # Lifecycle status
    status: str = Field(
        default=RuntimeSessionSnapshotStatus.unknown.value,
        description="Overall lifecycle status of this session snapshot.",
    )

    # Device and host state
    runtime_devices: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Compact entries for all registered runtime devices in this session."
        ),
    )
    runtime_hosts: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Compact entries for all local runtime hosts in this session.",
    )
    mesh_memberships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Compact entries for mesh memberships in this session.",
    )

    # Mesh session
    mesh_session: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional snapshot of the mesh session state (PR-33).",
    )

    # Dispatch / takeover / coordinator / merged result / recovery
    dispatch_state: Optional[RuntimeSessionSnapshotDispatchState] = Field(
        default=None,
        description="Optional snapshot of the source dispatch state (PR-35).",
    )
    takeover_states: List[RuntimeSessionSnapshotTakeoverState] = Field(
        default_factory=list,
        description="Snapshots of all target-side takeover results (PR-34).",
    )
    coordinator_state: Optional[RuntimeSessionSnapshotCoordinatorState] = Field(
        default=None,
        description="Optional snapshot of the mesh session coordinator state (PR-37).",
    )
    merged_result: Optional[RuntimeSessionSnapshotResultState] = Field(
        default=None,
        description="Optional snapshot of the cross-runtime merged result state (PR-36).",
    )
    recovery_state: Optional[RuntimeSessionSnapshotRecoveryState] = Field(
        default=None,
        description="Optional snapshot of the recovery/reconciliation posture (PR-39).",
    )

    # Governance / policy
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional governance snapshot dict (PR-27).",
    )
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional policy alignment dict (PR-28).",
    )

    # Metadata
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    model_config = {"extra": "allow", "use_enum_values": True}

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshot":
        """Construct from a dict, ignoring unknown fields."""
        return cls.model_validate(data)

    def to_identity(self) -> RuntimeSessionSnapshotIdentity:
        """Return the identity block for this snapshot."""
        return RuntimeSessionSnapshotIdentity(
            snapshot_id=self.snapshot_id,
            session_id=self.session_id,
            trace_id=self.trace_id,
            task_id=self.task_id,
            mesh_session_id=self.mesh_session_id,
            source_device_id=self.source_device_id,
            primary_device_id=self.primary_device_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
            metadata=dict(self.metadata),
        )

    def __repr__(self) -> str:
        return (
            f"RuntimeSessionSnapshot("
            f"snapshot_id={self.snapshot_id!r}, "
            f"session_id={self.session_id!r}, "
            f"status={self.status!r})"
        )


class RuntimeSessionSnapshotSummary(BaseModel):
    """Lightweight read-only summary of a durable runtime session snapshot.

    Suitable for embedding in lists, dashboards, or API responses where the
    full snapshot would be too verbose.

    Fields
    ------
    summary_id
        Stable unique identifier for this summary instance.
    snapshot_id
        ID of the source snapshot.
    session_id
        The runtime session this summary belongs to.
    trace_id
        Optional execution trace identifier.
    task_id
        Optional task identifier.
    mesh_session_id
        Optional mesh session identifier.
    source_device_id
        Optional originating device identifier.
    primary_device_id
        Optional primary device identifier.
    status
        Overall lifecycle status.
    runtime_device_count
        Number of runtime devices in the snapshot.
    runtime_host_count
        Number of runtime hosts in the snapshot.
    mesh_membership_count
        Number of mesh memberships in the snapshot.
    takeover_count
        Number of takeover state entries in the snapshot.
    has_dispatch_state
        Whether a dispatch state block is present.
    has_coordinator_state
        Whether a coordinator state block is present.
    has_merged_result
        Whether a merged result block is present.
    has_recovery_state
        Whether a recovery state block is present.
    has_mesh_session
        Whether a mesh session block is present.
    has_governance_snapshot
        Whether a governance snapshot block is present.
    has_policy_alignment
        Whether a policy alignment block is present.
    created_at
        Unix epoch seconds when the source snapshot was created.
    updated_at
        Unix epoch seconds when the source snapshot was last updated.
    generated_at
        Unix epoch seconds when this summary was generated.
    metadata
        Arbitrary extensibility bag.
    """

    summary_id: str = Field(
        default_factory=lambda: f"rsnsum_{uuid.uuid4().hex[:10]}",
        description="Stable unique identifier for this summary instance.",
    )
    snapshot_id: Optional[str] = Field(
        default=None,
        description="ID of the source snapshot.",
    )
    session_id: str = Field(
        default="",
        description="The runtime session this summary belongs to.",
    )
    trace_id: Optional[str] = Field(
        default=None,
        description="Optional execution trace identifier.",
    )
    task_id: Optional[str] = Field(
        default=None,
        description="Optional task identifier.",
    )
    mesh_session_id: Optional[str] = Field(
        default=None,
        description="Optional mesh session identifier.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Optional originating device identifier.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description="Optional primary device identifier.",
    )
    status: str = Field(
        default=RuntimeSessionSnapshotStatus.unknown.value,
        description="Overall lifecycle status.",
    )
    runtime_device_count: int = Field(
        default=0,
        description="Number of runtime devices in the snapshot.",
    )
    runtime_host_count: int = Field(
        default=0,
        description="Number of runtime hosts in the snapshot.",
    )
    mesh_membership_count: int = Field(
        default=0,
        description="Number of mesh memberships in the snapshot.",
    )
    takeover_count: int = Field(
        default=0,
        description="Number of takeover state entries in the snapshot.",
    )
    has_dispatch_state: bool = Field(
        default=False,
        description="Whether a dispatch state block is present.",
    )
    has_coordinator_state: bool = Field(
        default=False,
        description="Whether a coordinator state block is present.",
    )
    has_merged_result: bool = Field(
        default=False,
        description="Whether a merged result block is present.",
    )
    has_recovery_state: bool = Field(
        default=False,
        description="Whether a recovery state block is present.",
    )
    has_mesh_session: bool = Field(
        default=False,
        description="Whether a mesh session block is present.",
    )
    has_governance_snapshot: bool = Field(
        default=False,
        description="Whether a governance snapshot block is present.",
    )
    has_policy_alignment: bool = Field(
        default=False,
        description="Whether a policy alignment block is present.",
    )
    created_at: Optional[float] = Field(
        default=None,
        description="Unix epoch seconds when the source snapshot was created.",
    )
    updated_at: Optional[float] = Field(
        default=None,
        description="Unix epoch seconds when the source snapshot was last updated.",
    )
    generated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this summary was generated.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )

    def to_dict(self) -> Dict[str, Any]:
        return json.loads(self.model_dump_json())

    def to_json(self, **kwargs: Any) -> str:
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeSessionSnapshotSummary":
        return cls.model_validate(data)

    def __repr__(self) -> str:
        return (
            f"RuntimeSessionSnapshotSummary("
            f"summary_id={self.summary_id!r}, "
            f"session_id={self.session_id!r}, "
            f"status={self.status!r})"
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""


def _safe_dict(v: Any) -> Dict[str, Any]:
    if v is None:
        return {}
    if isinstance(v, dict):
        return v
    try:
        if hasattr(v, "to_dict"):
            result = v.to_dict()
            return result if isinstance(result, dict) else {}
        if hasattr(v, "model_dump"):
            return v.model_dump()
    except Exception:
        pass
    return {}


def _safe_list(v: Any) -> List[Any]:
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return []


def _safe_int(v: Any, default: int = 0) -> int:
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _extract_unit_ids_by_status(
    units: List[Any],
    status_values: set,
) -> List[str]:
    """Extract unit IDs from a list of result unit dicts matching given status values."""
    result = []
    for u in units:
        uid = _safe_str(u.get("unit_id") or u.get("result_unit_id") or "")
        if uid and _safe_str(u.get("status") or "") in status_values:
            result.append(uid)
    return result


def _safe_bool(v: Any, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, bool):
        return v
    try:
        return bool(v)
    except Exception:
        return default


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_runtime_session_snapshot(
    *,
    session_id: str = "",
    snapshot_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    task_id: Optional[str] = None,
    mesh_session_id: Optional[str] = None,
    source_device_id: Optional[str] = None,
    primary_device_id: Optional[str] = None,
    status: Optional[str] = None,
    runtime_devices: Optional[List[Any]] = None,
    runtime_hosts: Optional[List[Any]] = None,
    mesh_memberships: Optional[List[Any]] = None,
    mesh_session: Optional[Any] = None,
    dispatch_state: Optional[Any] = None,
    takeover_states: Optional[List[Any]] = None,
    coordinator_state: Optional[Any] = None,
    merged_result: Optional[Any] = None,
    recovery_state: Optional[Any] = None,
    governance_snapshot: Optional[Any] = None,
    policy_alignment: Optional[Any] = None,
    created_at: Optional[float] = None,
    updated_at: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Build a :class:`RuntimeSessionSnapshot` from component inputs.

    All parameters are optional; missing values produce safe defaults.

    Parameters
    ----------
    session_id:
        The runtime session identifier.
    snapshot_id:
        Optional explicit snapshot ID; auto-generated if not provided.
    trace_id:
        Optional execution trace identifier (PR-25).
    task_id:
        Optional task identifier.
    mesh_session_id:
        Optional mesh session identifier (PR-33).
    source_device_id:
        Optional originating device identifier.
    primary_device_id:
        Optional primary device identifier.
    status:
        Optional lifecycle status string.
    runtime_devices:
        List of registered runtime device contracts or dicts (PR-29).
    runtime_hosts:
        List of local runtime host contracts or dicts (PR-30).
    mesh_memberships:
        List of mesh membership contracts or dicts (PR-32).
    mesh_session:
        Optional mesh session contract or dict (PR-33).
    dispatch_state:
        Optional source dispatch result contract or dict (PR-35).
    takeover_states:
        List of local takeover result contracts or dicts (PR-34).
    coordinator_state:
        Optional mesh session coordinator state contract or dict (PR-37).
    merged_result:
        Optional merged runtime result contract or dict (PR-36).
    recovery_state:
        Optional runtime reconciliation state contract or dict (PR-39).
    governance_snapshot:
        Optional governance snapshot contract or dict (PR-27).
    policy_alignment:
        Optional policy alignment contract or dict (PR-28).
    created_at:
        Optional creation timestamp; defaults to now.
    updated_at:
        Optional update timestamp; defaults to now.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A fully populated snapshot contract.  Never raises.
    """
    now = time.time()
    try:
        # Normalise device/host/membership lists to plain dicts
        def _to_dict_list(items: Optional[List[Any]]) -> List[Dict[str, Any]]:
            result: List[Dict[str, Any]] = []
            for item in _safe_list(items):
                d = _safe_dict(item)
                if d:
                    result.append(d)
            return result

        devices_list = _to_dict_list(runtime_devices)
        hosts_list = _to_dict_list(runtime_hosts)
        memberships_list = _to_dict_list(mesh_memberships)
        mesh_session_dict = _safe_dict(mesh_session) or None
        governance_dict = _safe_dict(governance_snapshot) or None
        policy_dict = _safe_dict(policy_alignment) or None

        # Build dispatch state block
        dispatch_block: Optional[RuntimeSessionSnapshotDispatchState] = None
        if dispatch_state is not None:
            try:
                d = _safe_dict(dispatch_state)
                dispatch_block = RuntimeSessionSnapshotDispatchState(
                    dispatch_id=_safe_str(d.get("result_id") or d.get("dispatch_id")),
                    dispatch_mode=_safe_str(d.get("mode") or d.get("dispatch_mode")) or None,
                    dispatch_status=_safe_str(d.get("status") or d.get("dispatch_status")) or None,
                    target_device_ids=[
                        _safe_str(t)
                        for t in _safe_list(
                            d.get("target_device_ids") or d.get("selected_target_device_ids") or []
                        )
                    ],
                    plan_id=_safe_str(d.get("plan_id")) or None,
                    reason=_safe_str(d.get("reason") or d.get("outcome_reason") or ""),
                    metadata=dict(d.get("metadata") or {}),
                )
            except Exception as exc:
                _logger.debug("build_runtime_session_snapshot: dispatch_state error: %s", exc)

        # Build takeover state blocks
        takeover_blocks: List[RuntimeSessionSnapshotTakeoverState] = []
        for tko in _safe_list(takeover_states):
            try:
                d = _safe_dict(tko)
                takeover_blocks.append(
                    RuntimeSessionSnapshotTakeoverState(
                        takeover_id=_safe_str(d.get("takeover_id") or d.get("result_id")) or None,
                        target_device_id=_safe_str(d.get("target_device_id") or d.get("device_id")) or None,
                        takeover_status=_safe_str(d.get("status") or d.get("takeover_status")) or None,
                        session_context_id=_safe_str(d.get("session_id") or d.get("session_context_id")) or None,
                        reason=_safe_str(d.get("reason") or ""),
                        metadata=dict(d.get("metadata") or {}),
                    )
                )
            except Exception as exc:
                _logger.debug("build_runtime_session_snapshot: takeover_state error: %s", exc)

        # Build coordinator state block
        coordinator_block: Optional[RuntimeSessionSnapshotCoordinatorState] = None
        if coordinator_state is not None:
            try:
                d = _safe_dict(coordinator_state)
                coordinator_block = RuntimeSessionSnapshotCoordinatorState(
                    coordinator_id=_safe_str(d.get("coordinator_id") or d.get("state_id")) or None,
                    coordinator_status=_safe_str(d.get("status") or d.get("coordinator_status")) or None,
                    participant_count=_safe_int(
                        len(_safe_list(d.get("participants") or [])) or d.get("participant_count")
                    ),
                    assignment_count=_safe_int(
                        len(_safe_list(d.get("assignments") or [])) or d.get("assignment_count")
                    ),
                    barrier_active=_safe_bool(
                        d.get("barrier_active")
                        or (d.get("barrier") is not None and _safe_bool(d.get("barrier", {}).get("blocking")))
                    ),
                    event_count=_safe_int(
                        len(_safe_list(d.get("events") or [])) or d.get("event_count")
                    ),
                    metadata=dict(d.get("metadata") or {}),
                )
            except Exception as exc:
                _logger.debug("build_runtime_session_snapshot: coordinator_state error: %s", exc)

        # Build merged result block
        result_block: Optional[RuntimeSessionSnapshotResultState] = None
        if merged_result is not None:
            try:
                d = _safe_dict(merged_result)
                units = _safe_list(d.get("result_units") or [])
                auth_ids = _extract_unit_ids_by_status(units, {"authoritative", "confirmed", "merged"})
                stale_ids = _extract_unit_ids_by_status(units, {"stale", "superseded", "rejected"})
                pending_ids = _extract_unit_ids_by_status(units, {"pending", "partial", "in_progress"})
                result_block = RuntimeSessionSnapshotResultState(
                    merge_id=_safe_str(d.get("merge_id") or d.get("result_id")) or None,
                    merge_status=_safe_str(d.get("status") or d.get("merge_status")) or None,
                    authoritative_unit_ids=auth_ids,
                    stale_unit_ids=stale_ids,
                    pending_unit_ids=pending_ids,
                    result_unit_count=len(units),
                    merge_policy=_safe_str(d.get("merge_policy") or "") or None,
                    metadata=dict(d.get("metadata") or {}),
                )
            except Exception as exc:
                _logger.debug("build_runtime_session_snapshot: merged_result error: %s", exc)

        # Build recovery state block
        recovery_block: Optional[RuntimeSessionSnapshotRecoveryState] = None
        if recovery_state is not None:
            try:
                d = _safe_dict(recovery_state)
                recovery_block = RuntimeSessionSnapshotRecoveryState(
                    reconciliation_id=_safe_str(d.get("reconciliation_id") or d.get("recovery_id")) or None,
                    recovery_status=_safe_str(d.get("status") or d.get("overall_status") or d.get("recovery_status")) or None,
                    incident_count=_safe_int(
                        d.get("incident_count") or len(_safe_list(d.get("incidents") or []))
                    ),
                    replay_required=_safe_bool(d.get("replay_required")),
                    resume_allowed=_safe_bool(d.get("resume_allowed")),
                    merge_confirmation_required=_safe_bool(d.get("merge_confirmation_required")),
                    has_barrier=_safe_bool(d.get("has_barrier")),
                    reason=_safe_str(d.get("reason") or ""),
                    metadata=dict(d.get("metadata") or {}),
                )
            except Exception as exc:
                _logger.debug("build_runtime_session_snapshot: recovery_state error: %s", exc)

        # Determine snapshot status if not explicitly provided
        resolved_status = RuntimeSessionSnapshotStatus.unknown.value
        if status is not None:
            resolved_status = _safe_str(status)
        elif recovery_block is not None and recovery_block.recovery_status:
            rs = recovery_block.recovery_status
            if rs in ("in_progress",):
                resolved_status = RuntimeSessionSnapshotStatus.recovering.value
            elif rs in ("needs_intervention",):
                resolved_status = RuntimeSessionSnapshotStatus.interrupted.value
            elif rs in ("resolved",):
                resolved_status = RuntimeSessionSnapshotStatus.completed.value
        elif result_block is not None and result_block.merge_status:
            ms = result_block.merge_status
            if ms in ("authoritative", "confirmed", "merged", "completed"):
                resolved_status = RuntimeSessionSnapshotStatus.completed.value
            elif ms in ("partial", "incomplete"):
                resolved_status = RuntimeSessionSnapshotStatus.partial.value
            elif ms in ("failed", "error"):
                resolved_status = RuntimeSessionSnapshotStatus.failed.value

        return RuntimeSessionSnapshot(
            snapshot_id=snapshot_id or f"rsnap_{uuid.uuid4().hex[:12]}",
            session_id=_safe_str(session_id),
            trace_id=_safe_str(trace_id) or None,
            task_id=_safe_str(task_id) or None,
            mesh_session_id=_safe_str(mesh_session_id) or None,
            source_device_id=_safe_str(source_device_id) or None,
            primary_device_id=_safe_str(primary_device_id) or None,
            created_at=created_at if created_at is not None else now,
            updated_at=updated_at if updated_at is not None else now,
            status=resolved_status,
            runtime_devices=devices_list,
            runtime_hosts=hosts_list,
            mesh_memberships=memberships_list,
            mesh_session=mesh_session_dict,
            dispatch_state=dispatch_block,
            takeover_states=takeover_blocks,
            coordinator_state=coordinator_block,
            merged_result=result_block,
            recovery_state=recovery_block,
            governance_snapshot=governance_dict,
            policy_alignment=policy_dict,
            metadata=dict(metadata or {}),
        )

    except Exception as exc:
        _logger.warning("build_runtime_session_snapshot: unexpected error: %s", exc)
        return RuntimeSessionSnapshot(
            snapshot_id=snapshot_id or f"rsnap_{uuid.uuid4().hex[:12]}",
            session_id=_safe_str(session_id),
            metadata={"build_error": str(exc)},
        )


def build_runtime_session_snapshot_summary(
    snapshot: Any,
) -> RuntimeSessionSnapshotSummary:
    """Build a :class:`RuntimeSessionSnapshotSummary` from a snapshot contract or dict.

    Parameters
    ----------
    snapshot:
        A :class:`RuntimeSessionSnapshot` instance or compatible dict.

    Returns
    -------
    RuntimeSessionSnapshotSummary
        A compact read-only summary.  Never raises.
    """
    try:
        d = _safe_dict(snapshot)
        return RuntimeSessionSnapshotSummary(
            snapshot_id=_safe_str(d.get("snapshot_id")) or None,
            session_id=_safe_str(d.get("session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("mesh_session_id")) or None,
            source_device_id=_safe_str(d.get("source_device_id")) or None,
            primary_device_id=_safe_str(d.get("primary_device_id")) or None,
            status=_safe_str(d.get("status") or RuntimeSessionSnapshotStatus.unknown.value),
            runtime_device_count=len(_safe_list(d.get("runtime_devices"))),
            runtime_host_count=len(_safe_list(d.get("runtime_hosts"))),
            mesh_membership_count=len(_safe_list(d.get("mesh_memberships"))),
            takeover_count=len(_safe_list(d.get("takeover_states"))),
            has_dispatch_state=d.get("dispatch_state") is not None,
            has_coordinator_state=d.get("coordinator_state") is not None,
            has_merged_result=d.get("merged_result") is not None,
            has_recovery_state=d.get("recovery_state") is not None,
            has_mesh_session=d.get("mesh_session") is not None,
            has_governance_snapshot=d.get("governance_snapshot") is not None,
            has_policy_alignment=d.get("policy_alignment") is not None,
            created_at=d.get("created_at"),
            updated_at=d.get("updated_at"),
            metadata=dict(d.get("metadata") or {}),
        )
    except Exception as exc:
        _logger.warning("build_runtime_session_snapshot_summary: error: %s", exc)
        return RuntimeSessionSnapshotSummary(
            metadata={"summary_error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Adapters — construct snapshots from upstream contracts
# ---------------------------------------------------------------------------


def from_mesh_session(
    mesh_session: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a mesh session contract (PR-33).

    Parameters
    ----------
    mesh_session:
        A :class:`~contracts.mesh_session.MeshSession` instance or dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the mesh session.  Never raises.
    """
    try:
        d = _safe_dict(mesh_session)
        participants = _safe_list(d.get("participants") or [])
        device_entries = []
        for p in participants:
            pd = _safe_dict(p)
            if pd:
                device_entries.append({"device_id": _safe_str(pd.get("device_id") or ""), **pd})

        return build_runtime_session_snapshot(
            session_id=_safe_str(d.get("session_id") or d.get("mesh_session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("session_id") or d.get("mesh_session_id")) or None,
            source_device_id=_safe_str(d.get("source_device_id")) or None,
            primary_device_id=_safe_str(d.get("primary_device_id")) or None,
            status=_safe_str(d.get("status")) or None,
            runtime_devices=device_entries,
            mesh_session=d,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_mesh_session: error: %s", exc)
        return build_runtime_session_snapshot(metadata={"adapter_error": str(exc)})


def from_source_dispatch_result(
    dispatch_result: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a source dispatch result (PR-35).

    Parameters
    ----------
    dispatch_result:
        A :class:`~contracts.source_dispatch.SourceDispatchResult` instance or dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the dispatch result.  Never raises.
    """
    try:
        d = _safe_dict(dispatch_result)
        return build_runtime_session_snapshot(
            session_id=_safe_str(d.get("session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("mesh_session_id")) or None,
            source_device_id=_safe_str(d.get("source_device_id")) or None,
            dispatch_state=d,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_source_dispatch_result: error: %s", exc)
        return build_runtime_session_snapshot(metadata={"adapter_error": str(exc)})


def from_target_takeover_result(
    takeover_result: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a target takeover result (PR-34).

    Parameters
    ----------
    takeover_result:
        A :class:`~contracts.local_takeover_result.LocalTakeoverResult` instance or dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the takeover result.  Never raises.
    """
    try:
        d = _safe_dict(takeover_result)
        return build_runtime_session_snapshot(
            session_id=_safe_str(d.get("session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("mesh_session_id")) or None,
            primary_device_id=_safe_str(d.get("target_device_id") or d.get("device_id")) or None,
            takeover_states=[d],
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_target_takeover_result: error: %s", exc)
        return build_runtime_session_snapshot(metadata={"adapter_error": str(exc)})


def from_result_merge(
    merged_result: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a cross-runtime merged result (PR-36).

    Parameters
    ----------
    merged_result:
        A :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult` instance or dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the merged result.  Never raises.
    """
    try:
        d = _safe_dict(merged_result)
        return build_runtime_session_snapshot(
            session_id=_safe_str(d.get("session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("mesh_session_id")) or None,
            source_device_id=_safe_str(d.get("source_device_id")) or None,
            primary_device_id=_safe_str(d.get("primary_device_id")) or None,
            merged_result=d,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_result_merge: error: %s", exc)
        return build_runtime_session_snapshot(metadata={"adapter_error": str(exc)})


def from_recovery_state(
    recovery_state: Any,
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a runtime reconciliation state (PR-39).

    Parameters
    ----------
    recovery_state:
        A :class:`~contracts.runtime_recovery_reconciliation.RuntimeReconciliationState`
        instance or dict.
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the recovery state.  Never raises.
    """
    try:
        d = _safe_dict(recovery_state)
        return build_runtime_session_snapshot(
            session_id=_safe_str(d.get("session_id") or ""),
            trace_id=_safe_str(d.get("trace_id")) or None,
            task_id=_safe_str(d.get("task_id")) or None,
            mesh_session_id=_safe_str(d.get("mesh_session_id")) or None,
            source_device_id=_safe_str(d.get("source_device_id")) or None,
            primary_device_id=_safe_str(d.get("primary_device_id")) or None,
            recovery_state=d,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_recovery_state: error: %s", exc)
        return build_runtime_session_snapshot(metadata={"adapter_error": str(exc)})


def from_multi_device_runtime_projection(
    projection: Any,
    *,
    session_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeSessionSnapshot:
    """Construct a :class:`RuntimeSessionSnapshot` from a unified multi-device projection (PR-38).

    Parameters
    ----------
    projection:
        A :class:`~contracts.multi_device_runtime_projection.MultiDeviceRuntimeProjection`
        instance or dict.
    session_id:
        Optional session ID override (the projection may not carry one directly).
    metadata:
        Arbitrary extensibility bag.

    Returns
    -------
    RuntimeSessionSnapshot
        A snapshot derived from the full multi-device projection.  Never raises.
    """
    try:
        d = _safe_dict(projection)

        # Extract component lists
        devices = _safe_list(d.get("runtime_devices") or [])
        hosts = _safe_list(d.get("runtime_hosts") or [])
        memberships = _safe_list(d.get("mesh_memberships") or [])
        mesh_sessions = _safe_list(d.get("mesh_sessions") or [])
        dispatches = _safe_list(d.get("source_dispatches") or [])
        takeovers = _safe_list(d.get("takeover_summaries") or [])
        coordinators = _safe_list(d.get("coordinator_summaries") or [])
        merged_results = _safe_list(d.get("merged_results") or [])
        recovery = d.get("runtime_recovery")

        # Derive mesh session (first entry)
        mesh_session_dict = _safe_dict(mesh_sessions[0]) if mesh_sessions else None

        # Derive mesh_session_id
        mesh_session_id: Optional[str] = None
        if mesh_session_dict:
            mesh_session_id = _safe_str(mesh_session_dict.get("session_id") or "") or None

        # Derive dispatch state (first entry)
        dispatch_dict = _safe_dict(dispatches[0]) if dispatches else None

        # Derive coordinator state (first entry)
        coordinator_dict = _safe_dict(coordinators[0]) if coordinators else None

        # Derive merged result (first entry)
        merged_dict = _safe_dict(merged_results[0]) if merged_results else None

        return build_runtime_session_snapshot(
            session_id=_safe_str(session_id) or _safe_str(d.get("projection_id") or ""),
            mesh_session_id=mesh_session_id,
            runtime_devices=devices,
            runtime_hosts=hosts,
            mesh_memberships=memberships,
            mesh_session=mesh_session_dict,
            dispatch_state=dispatch_dict,
            takeover_states=takeovers,
            coordinator_state=coordinator_dict,
            merged_result=merged_dict,
            recovery_state=recovery,
            metadata=dict(metadata or {}),
        )
    except Exception as exc:
        _logger.warning("from_multi_device_runtime_projection: error: %s", exc)
        return build_runtime_session_snapshot(
            session_id=_safe_str(session_id),
            metadata={"adapter_error": str(exc)},
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
    # Enums
    "RuntimeSessionSnapshotStatus",
    # Sub-contracts
    "RuntimeSessionSnapshotIdentity",
    "RuntimeSessionSnapshotDispatchState",
    "RuntimeSessionSnapshotTakeoverState",
    "RuntimeSessionSnapshotCoordinatorState",
    "RuntimeSessionSnapshotResultState",
    "RuntimeSessionSnapshotRecoveryState",
    # Top-level contracts
    "RuntimeSessionSnapshot",
    "RuntimeSessionSnapshotSummary",
    # Builders
    "build_runtime_session_snapshot",
    "build_runtime_session_snapshot_summary",
    # Adapters
    "from_mesh_session",
    "from_source_dispatch_result",
    "from_target_takeover_result",
    "from_result_merge",
    "from_recovery_state",
    "from_multi_device_runtime_projection",
]
