#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/multi_device_control_integrity.py
========================================
PR-517 — Cross-Device / Multi-Device Control Integrity Audit.

This module is the **multi-device control integrity layer** for the Galaxy
canonical runtime architecture.  It audits and strengthens the coherence of
multi-device control so that the system reliably supports:

* Many connected devices
* Entry from any valid device
* Local control of the originating device
* Cross-device dispatch / takeover to other participating devices
* Coherent result / state return through canonical runtime / operator /
  projection paths

Architecture role
-----------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │  OPERATOR INSPECTION / STATUS BOARD / PROJECTION SURFACE        │
    │  status_board_v2  ·  desktop_projection  ·  /api/v1/projection  │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  MULTI-DEVICE RESULT SURFACE
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  MULTI-DEVICE CONTROL INTEGRITY LAYER  (this module, Layer 17)  │
    │                                                                  │
    │  Audit areas:                                                    │
    │    1. ENTRY UNIFICATION — device-originated entry flows          │
    │       converge onto canonical CommandRouter → TaskEnvelope path  │
    │    2. DISPATCH AUTHORITY — CommandRouter is the sole canonical   │
    │       cross-device dispatcher; legacy/parallel paths demoted     │
    │    3. FORMATION TRUTH — formation group, participation, and      │
    │       readiness truth must be consistent and non-drifting        │
    │    4. CONTROL SEMANTICS — source device, target device, local    │
    │       execution, remote dispatch, and takeover are distinct       │
    │    5. RESULT SURFACE — cross-device results surface through      │
    │       OperatorSurface, projection, and audit layers              │
    │    6. RESIDUAL MAP — remaining gaps for follow-up work           │
    │                                                                  │
    │  Authority sentinels:                                            │
    │    • MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY                    │
    │    • SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY                      │
    │    • DEVICE_FORMATION_TRUTH_AUTHORITY                            │
    │    • CONTROL_SEMANTIC_SEPARATION_AUTHORITY                       │
    │    • RESULT_CANONICAL_SURFACE_AUTHORITY                          │
    │                                                                  │
    │  Policy sentinels:                                               │
    │    • ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY         │
    │    • NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY                    │
    │    • FORMATION_TRUTH_SINGLE_SOURCE_POLICY                        │
    │    • SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY                    │
    │    • CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY             │
    └────────────────────────────┬─────────────────────────────────────┘
                                 │  READS CANONICAL LAYERS
                                 ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  CANONICAL CROSS-DEVICE LAYERS                                  │
    │  CrossDeviceExecutionChain · CommandRouter · DeviceFormation    │
    │  CapabilityAssimilation · NetworkTopologyRuntime                │
    │  OperatorSurface · TaskGraphRuntime · ReplayFoundation          │
    └──────────────────────────────────────────────────────────────────┘

Governance invariants
---------------------
1.  **All device entry converges on CommandRouter.**
    Every device-originated entry point (REST routes, WebSocket bridges,
    scheduler, gateway orchestrators) MUST funnel requests through
    ``CommandRouter.route_envelope`` via the canonical ``TaskEnvelope``.
    Governed by :data:`ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY`.

2.  **No parallel cross-device dispatch paths.**
    ``CommandRouter`` is the sole canonical cross-device dispatcher.
    ``DeviceRouter._dispatch_cross_device_task``,
    ``CrossDeviceCoordinator.execute_cross_device_task``, and any
    other direct-dispatch paths that bypass ``CommandRouter`` are legacy/compat
    paths and must be demoted.
    Governed by :data:`NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY`.

3.  **Single source of formation truth.**
    ``DeviceFormationGroup`` (from :mod:`core.device_formation`) is the
    canonical formation descriptor.  Participation facts (registered,
    routable, orchestration_eligible) come exclusively from the admissibility
    chain (Layers 1–3: device_readiness → device_participation →
    target_device_validator).  No other module may assert conflicting
    formation truth.
    Governed by :data:`FORMATION_TRUTH_SINGLE_SOURCE_POLICY`.

4.  **Source and target device semantics are separated.**
    Every cross-device control flow MUST explicitly distinguish:
      * ``source_device_id`` — device that originated the request
      * ``target_device_id`` — device that will execute
      * ``is_local`` — whether execution is local to the originating device
      * ``is_remote_dispatch`` — whether execution is dispatched cross-device
      * ``is_takeover`` — whether the execution is a delegation/takeover
    Governed by :data:`SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY`.

5.  **Cross-device results surface canonically.**
    Results from cross-device execution MUST be returned through:
      * ``ResultEnvelope`` (canonical result container)
      * ``OperatorSurface`` (for inspection)
      * ``TaskGraphRuntime`` / ``ReplayFoundation`` (for audit)
      * Projection / status board (for display)
    Governed by :data:`CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY`.

Public API
----------
Authority sentinels:
    MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY
    MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION
    MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED

Audit sub-area authority sentinels:
    MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY
    SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY
    DEVICE_FORMATION_TRUTH_AUTHORITY
    CONTROL_SEMANTIC_SEPARATION_AUTHORITY
    RESULT_CANONICAL_SURFACE_AUTHORITY

Policy sentinels:
    ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY
    NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY
    FORMATION_TRUTH_SINGLE_SOURCE_POLICY
    SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY
    CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY

Enums:
    EntryUnificationKind
    DispatchPathKind
    FormationTruthConsistency
    ControlSemanticKind
    ResultSurfaceKind

Dataclasses:
    EntryUnificationRecord
    DispatchAuthorityRecord
    FormationTruthRecord
    ControlSemanticRecord
    ResultSurfaceRecord
    ResidualIntegrityGap
    MultiDeviceIntegritySnapshot

Runtime class:
    MultiDeviceControlIntegrityRuntime

Factory / helper functions:
    build_entry_unification_record(...)
    build_dispatch_authority_record(...)
    build_formation_truth_record(...)
    build_control_semantic_record(...)
    build_result_surface_record(...)
    record_integrity_event(...)
    build_integrity_snapshot()
    get_residual_integrity_gaps()
    get_multi_device_integrity_runtime()
    reset_multi_device_integrity_runtime()
"""

from __future__ import annotations

import dataclasses
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.MultiDeviceControlIntegrity")

# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Top-level authority sentinels
    "MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY",
    "MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION",
    "MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED",
    # Sub-area authority sentinels
    "MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY",
    "SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY",
    "DEVICE_FORMATION_TRUTH_AUTHORITY",
    "CONTROL_SEMANTIC_SEPARATION_AUTHORITY",
    "RESULT_CANONICAL_SURFACE_AUTHORITY",
    # Policy sentinels
    "ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY",
    "NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY",
    "FORMATION_TRUTH_SINGLE_SOURCE_POLICY",
    "SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY",
    "CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY",
    # Enums
    "EntryUnificationKind",
    "DispatchPathKind",
    "FormationTruthConsistency",
    "ControlSemanticKind",
    "ResultSurfaceKind",
    # Dataclasses
    "EntryUnificationRecord",
    "DispatchAuthorityRecord",
    "FormationTruthRecord",
    "ControlSemanticRecord",
    "ResultSurfaceRecord",
    "ResidualIntegrityGap",
    "MultiDeviceIntegritySnapshot",
    # Runtime
    "MultiDeviceControlIntegrityRuntime",
    # Factory / helpers
    "build_entry_unification_record",
    "build_dispatch_authority_record",
    "build_formation_truth_record",
    "build_control_semantic_record",
    "build_result_surface_record",
    "record_integrity_event",
    "build_integrity_snapshot",
    "get_residual_integrity_gaps",
    "get_multi_device_integrity_runtime",
    "reset_multi_device_integrity_runtime",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Top-level authority sentinel for this module (Layer 17).
MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY: str = (
    "MULTI_DEVICE_CONTROL_INTEGRITY::AUTHORITY_V1: "
    "Cross-device / multi-device control integrity audit layer. "
    "Establishes governance invariants for device entry unification, "
    "single dispatch authority, formation truth, control semantics, "
    "and canonical result surfaces."
)

#: Architectural layer position (above PR-516 / Layer 16, peer of acceptance matrix).
MULTI_DEVICE_CONTROL_INTEGRITY_LAYER_POSITION: int = 17

#: Integration sentinel — added to modules that have been wired into this layer.
MULTI_DEVICE_CONTROL_INTEGRITY_INTEGRATED: str = (
    "MULTI_DEVICE_CONTROL_INTEGRITY::INTEGRATED_V1: "
    "This module participates in the PR-517 multi-device control integrity audit."
)

# ---------------------------------------------------------------------------
# Sub-area authority sentinels
# ---------------------------------------------------------------------------

#: Authority for the device-entry unification sub-area (Audit area 1).
MULTI_DEVICE_ENTRY_UNIFICATION_AUTHORITY: str = (
    "ENTRY_UNIFICATION_AUTHORITY_V1: "
    "All device-originated entry flows converge onto "
    "CommandRouter → TaskEnvelope → canonical execution spine. "
    "Direct-dispatch routes that bypass this path are legacy paths."
)

#: Authority for the single cross-device dispatch sub-area (Audit area 2).
SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY: str = (
    "SINGLE_CROSS_DEVICE_DISPATCH_AUTHORITY_V1: "
    "CommandRouter.route_envelope() is the sole canonical cross-device "
    "dispatcher.  DeviceRouter._dispatch_cross_device_task and "
    "CrossDeviceCoordinator.execute_cross_device_task are demoted "
    "to internal execution substrate only."
)

#: Authority for the device formation truth sub-area (Audit area 3).
DEVICE_FORMATION_TRUTH_AUTHORITY: str = (
    "DEVICE_FORMATION_TRUTH_AUTHORITY_V1: "
    "DeviceFormationGroup is the canonical formation descriptor. "
    "Participation and readiness facts come exclusively from the "
    "admissibility chain (device_readiness → device_participation → "
    "target_device_validator).  No competing formation truth sources."
)

#: Authority for the control semantic separation sub-area (Audit area 4).
CONTROL_SEMANTIC_SEPARATION_AUTHORITY: str = (
    "CONTROL_SEMANTIC_SEPARATION_AUTHORITY_V1: "
    "Every cross-device control flow explicitly distinguishes "
    "source_device_id, target_device_id, is_local, is_remote_dispatch, "
    "and is_takeover.  Conflation of these semantics is prohibited."
)

#: Authority for the canonical result surface sub-area (Audit area 5).
RESULT_CANONICAL_SURFACE_AUTHORITY: str = (
    "RESULT_CANONICAL_SURFACE_AUTHORITY_V1: "
    "Cross-device execution results MUST surface through ResultEnvelope, "
    "OperatorSurface, TaskGraphRuntime / ReplayFoundation, and the "
    "projection / status board layers.  Results trapped in transport-local "
    "or coordinator-only layers are non-canonical."
)

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

#: Policy: all device entry routes converge onto CommandRouter.
ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY: str = (
    "ALL_DEVICE_ENTRY_CONVERGES_ON_COMMAND_ROUTER_POLICY_V1: "
    "Every device-originated entry point (REST API, WebSocket bridge, "
    "scheduler ingress, gateway orchestrator) MUST route through "
    "CommandRouter.route_envelope via a normalised TaskEnvelope.  "
    "Direct-dispatch to device executors without passing through "
    "CommandRouter is a legacy path."
)

#: Policy: no parallel cross-device dispatch paths.
NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY: str = (
    "NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY_V1: "
    "CommandRouter is the sole canonical cross-device dispatcher.  "
    "DeviceRouter._dispatch_cross_device_task and "
    "CrossDeviceCoordinator.execute_cross_device_task are internal "
    "gateway substrate (execution plumbing only) and must not be called "
    "as primary dispatch authorities from outside the gateway substrate."
)

#: Policy: single source of formation truth.
FORMATION_TRUTH_SINGLE_SOURCE_POLICY: str = (
    "FORMATION_TRUTH_SINGLE_SOURCE_POLICY_V1: "
    "DeviceFormationGroup is the canonical formation descriptor.  "
    "All formation members, roles, and merge ownership facts come from "
    "the device_formation package.  No other module may assert conflicting "
    "or duplicate formation truth.  Participation and readiness facts "
    "consumed by the formation resolver come exclusively from the "
    "admissibility chain (Layers 1–3)."
)

#: Policy: source and target device semantics are separated.
SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY: str = (
    "SOURCE_TARGET_SEMANTIC_SEPARATION_POLICY_V1: "
    "Every cross-device control flow MUST carry explicit source_device_id "
    "and target_device_id.  Execution type (local / remote_dispatch / "
    "takeover) must be declared, not inferred from context.  "
    "Conflating the originating device with the execution device is "
    "a semantic violation and a gap risk."
)

#: Policy: cross-device results surface through canonical layers.
CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY: str = (
    "CROSS_DEVICE_RESULT_SURFACES_CANONICALLY_POLICY_V1: "
    "All cross-device execution outcomes MUST be normalised into a "
    "ResultEnvelope and surfaced through OperatorSurface, "
    "TaskGraphRuntime / ReplayFoundation, and the projection / status "
    "board layers.  Outcomes that remain in transport-local state or "
    "coordinator-internal dicts without canonical surface exposure are "
    "non-canonical."
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class EntryUnificationKind(str, Enum):
    """Classification of a device-originated entry event.

    Used in :class:`EntryUnificationRecord` to mark whether the entry
    reached the canonical CommandRouter path or took a legacy path.
    """

    CANONICAL = "canonical"
    """Entry flowed through CommandRouter → TaskEnvelope → spine."""

    LEGACY_DIRECT_DISPATCH = "legacy_direct_dispatch"
    """Entry bypassed CommandRouter and dispatched directly to executor."""

    LEGACY_COORDINATOR_BYPASS = "legacy_coordinator_bypass"
    """Entry called CrossDeviceCoordinator or DeviceRouter directly."""

    LEGACY_ROUTE_BYPASS = "legacy_route_bypass"
    """Entry was dispatched from a REST/WebSocket route without going
    through CommandRouter."""

    UNKNOWN = "unknown"
    """Entry classification could not be determined."""


class DispatchPathKind(str, Enum):
    """Classification of a cross-device dispatch path.

    Used in :class:`DispatchAuthorityRecord` to distinguish canonical from
    legacy/parallel dispatch paths.
    """

    COMMAND_ROUTER_CANONICAL = "command_router_canonical"
    """Dispatch routed through CommandRouter.route_envelope (canonical)."""

    DEVICE_ROUTER_SUBSTRATE = "device_router_substrate"
    """Dispatch handled by DeviceRouter._dispatch_cross_device_task.
    This is acceptable ONLY when invoked by CommandRouter as internal
    execution substrate; NOT acceptable as an independent dispatch authority."""

    COORDINATOR_LEGACY = "coordinator_legacy"
    """Dispatch handled by CrossDeviceCoordinator.execute_cross_device_task
    directly, bypassing CommandRouter."""

    PARALLEL_LEGACY = "parallel_legacy"
    """Any other parallel/legacy dispatch path that bypasses CommandRouter."""

    UNKNOWN = "unknown"
    """Dispatch path could not be classified."""


class FormationTruthConsistency(str, Enum):
    """Consistency verdict for device formation / participation truth.

    Used in :class:`FormationTruthRecord` to capture how well the formation
    truth sources agree.
    """

    CONSISTENT = "consistent"
    """Formation group, participation, and readiness all agree."""

    PARTICIPATION_DRIFT = "participation_drift"
    """Formation group lists a device that participation layer deems
    ineligible."""

    READINESS_DRIFT = "readiness_drift"
    """Formation group lists a device that readiness layer marks as
    unavailable."""

    FORMATION_MISSING = "formation_missing"
    """No DeviceFormationGroup present; cross-device execution is proceeding
    without a canonical formation descriptor."""

    UNKNOWN = "unknown"
    """Consistency could not be assessed."""


class ControlSemanticKind(str, Enum):
    """Semantic classification of a device-control execution event.

    Used in :class:`ControlSemanticRecord` to explicitly mark the control
    type so callers can distinguish local from cross-device flows.
    """

    LOCAL_EXECUTION = "local_execution"
    """Execution is local — source device == target device, no remote
    dispatch."""

    REMOTE_DISPATCH = "remote_dispatch"
    """Execution is dispatched to a remote target device different from the
    source device."""

    TAKEOVER = "takeover"
    """A remote device has taken over execution; the source device is no
    longer the executor."""

    HYBRID = "hybrid"
    """Both local and remote execution are active (e.g. parallel
    multi-device execution)."""

    UNKNOWN = "unknown"
    """Execution semantics could not be determined."""


class ResultSurfaceKind(str, Enum):
    """Classification of where a cross-device result was surfaced.

    Used in :class:`ResultSurfaceRecord` to verify that results reach
    canonical surfaces.
    """

    CANONICAL_FULL = "canonical_full"
    """Result surfaced through all canonical layers: ResultEnvelope,
    OperatorSurface, TaskGraphRuntime, projection."""

    CANONICAL_PARTIAL = "canonical_partial"
    """Result surfaced through some (but not all) canonical layers."""

    TRANSPORT_LOCAL_ONLY = "transport_local_only"
    """Result remained in a transport-local dict; no canonical surface
    exposure."""

    COORDINATOR_ONLY = "coordinator_only"
    """Result was returned by CrossDeviceCoordinator but not propagated
    to canonical surfaces."""

    UNKNOWN = "unknown"
    """Result surface could not be assessed."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

_MAX_RECORDS: int = 256


@dataclasses.dataclass
class EntryUnificationRecord:
    """A record of one device-originated entry event and its classification.

    Attributes
    ----------
    record_id:
        Unique record identifier (UUID).
    task_id:
        The canonical task ID (if available at entry time).
    trace_id:
        Distributed trace ID.
    source_device_id:
        The device that originated the request.
    entry_kind:
        :class:`EntryUnificationKind` classification.
    is_canonical:
        ``True`` when the entry used the canonical CommandRouter path.
    entry_point:
        Human-readable name of the entry point (e.g. module or route name).
    reasons:
        Reasons explaining why this entry was classified as canonical or
        legacy.
    timestamp:
        Unix timestamp of recording.
    extra:
        Additional metadata.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    source_device_id: str = ""
    entry_kind: EntryUnificationKind = EntryUnificationKind.UNKNOWN
    is_canonical: bool = False
    entry_point: str = ""
    reasons: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "entry_kind": self.entry_kind.value,
            "is_canonical": self.is_canonical,
            "entry_point": self.entry_point,
            "reasons": list(self.reasons),
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EntryUnificationRecord":
        try:
            entry_kind = EntryUnificationKind(
                data.get("entry_kind", EntryUnificationKind.UNKNOWN.value)
            )
        except (ValueError, KeyError):
            entry_kind = EntryUnificationKind.UNKNOWN
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=str(data.get("task_id", "")),
            trace_id=data.get("trace_id"),
            source_device_id=str(data.get("source_device_id", "")),
            entry_kind=entry_kind,
            is_canonical=bool(data.get("is_canonical", False)),
            entry_point=str(data.get("entry_point", "")),
            reasons=list(data.get("reasons", [])),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


@dataclasses.dataclass
class DispatchAuthorityRecord:
    """A record of one cross-device dispatch event and its authority classification.

    Attributes
    ----------
    record_id:
        Unique record identifier (UUID).
    task_id:
        Canonical task ID.
    trace_id:
        Distributed trace ID.
    source_device_id:
        Device that originated the dispatch request.
    target_device_ids:
        Device IDs targeted for execution.
    dispatch_path:
        :class:`DispatchPathKind` classification.
    is_canonical:
        ``True`` when dispatched via CommandRouter (canonical).
    dispatcher_module:
        Module / class that performed dispatch (e.g.
        ``"core.command_router.CommandRouter"``).
    reasons:
        Reasons explaining the classification.
    timestamp:
        Unix timestamp of recording.
    extra:
        Additional metadata.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    source_device_id: str = ""
    target_device_ids: List[str] = dataclasses.field(default_factory=list)
    dispatch_path: DispatchPathKind = DispatchPathKind.UNKNOWN
    is_canonical: bool = False
    dispatcher_module: str = ""
    reasons: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "target_device_ids": list(self.target_device_ids),
            "dispatch_path": self.dispatch_path.value,
            "is_canonical": self.is_canonical,
            "dispatcher_module": self.dispatcher_module,
            "reasons": list(self.reasons),
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DispatchAuthorityRecord":
        try:
            dispatch_path = DispatchPathKind(
                data.get("dispatch_path", DispatchPathKind.UNKNOWN.value)
            )
        except (ValueError, KeyError):
            dispatch_path = DispatchPathKind.UNKNOWN
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=str(data.get("task_id", "")),
            trace_id=data.get("trace_id"),
            source_device_id=str(data.get("source_device_id", "")),
            target_device_ids=list(data.get("target_device_ids", [])),
            dispatch_path=dispatch_path,
            is_canonical=bool(data.get("is_canonical", False)),
            dispatcher_module=str(data.get("dispatcher_module", "")),
            reasons=list(data.get("reasons", [])),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


@dataclasses.dataclass
class FormationTruthRecord:
    """A record capturing device formation / participation truth consistency.

    Attributes
    ----------
    record_id:
        Unique record identifier (UUID).
    task_id:
        Canonical task ID.
    trace_id:
        Distributed trace ID.
    formation_id:
        DeviceFormationGroup formation_id, if available.
    consistency:
        :class:`FormationTruthConsistency` verdict.
    is_consistent:
        ``True`` when all formation truth sources agree.
    member_device_ids:
        All device IDs listed in the formation.
    ineligible_members:
        Device IDs that are in the formation but failed the participation
        or readiness gate.
    drift_reasons:
        Human-readable reasons explaining any drift.
    source_device_id:
        Device that originated the request (from formation SOURCE member).
    primary_device_id:
        Device designated as PRIMARY_EXECUTION in the formation.
    timestamp:
        Unix timestamp of recording.
    extra:
        Additional metadata.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    formation_id: str = ""
    consistency: FormationTruthConsistency = FormationTruthConsistency.UNKNOWN
    is_consistent: bool = False
    member_device_ids: List[str] = dataclasses.field(default_factory=list)
    ineligible_members: List[str] = dataclasses.field(default_factory=list)
    drift_reasons: List[str] = dataclasses.field(default_factory=list)
    source_device_id: str = ""
    primary_device_id: str = ""
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "formation_id": self.formation_id,
            "consistency": self.consistency.value,
            "is_consistent": self.is_consistent,
            "member_device_ids": list(self.member_device_ids),
            "ineligible_members": list(self.ineligible_members),
            "drift_reasons": list(self.drift_reasons),
            "source_device_id": self.source_device_id,
            "primary_device_id": self.primary_device_id,
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FormationTruthRecord":
        try:
            consistency = FormationTruthConsistency(
                data.get("consistency", FormationTruthConsistency.UNKNOWN.value)
            )
        except (ValueError, KeyError):
            consistency = FormationTruthConsistency.UNKNOWN
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=str(data.get("task_id", "")),
            trace_id=data.get("trace_id"),
            formation_id=str(data.get("formation_id", "")),
            consistency=consistency,
            is_consistent=bool(data.get("is_consistent", False)),
            member_device_ids=list(data.get("member_device_ids", [])),
            ineligible_members=list(data.get("ineligible_members", [])),
            drift_reasons=list(data.get("drift_reasons", [])),
            source_device_id=str(data.get("source_device_id", "")),
            primary_device_id=str(data.get("primary_device_id", "")),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


@dataclasses.dataclass
class ControlSemanticRecord:
    """A record of the control-semantic classification of one execution event.

    Attributes
    ----------
    record_id:
        Unique record identifier (UUID).
    task_id:
        Canonical task ID.
    trace_id:
        Distributed trace ID.
    source_device_id:
        Device that originated the request.
    target_device_id:
        Device that will (or did) execute the request.
    control_kind:
        :class:`ControlSemanticKind` classification.
    is_local:
        ``True`` when source and target are the same device.
    is_remote_dispatch:
        ``True`` when target differs from source and dispatch is outbound.
    is_takeover:
        ``True`` when a remote device took over execution from the source.
    is_semantically_clear:
        ``True`` when source, target, and kind are all explicitly set and
        non-ambiguous.
    ambiguity_reasons:
        Reasons explaining any semantic ambiguity.
    timestamp:
        Unix timestamp of recording.
    extra:
        Additional metadata.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    source_device_id: str = ""
    target_device_id: str = ""
    control_kind: ControlSemanticKind = ControlSemanticKind.UNKNOWN
    is_local: bool = False
    is_remote_dispatch: bool = False
    is_takeover: bool = False
    is_semantically_clear: bool = False
    ambiguity_reasons: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "control_kind": self.control_kind.value,
            "is_local": self.is_local,
            "is_remote_dispatch": self.is_remote_dispatch,
            "is_takeover": self.is_takeover,
            "is_semantically_clear": self.is_semantically_clear,
            "ambiguity_reasons": list(self.ambiguity_reasons),
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ControlSemanticRecord":
        try:
            control_kind = ControlSemanticKind(
                data.get("control_kind", ControlSemanticKind.UNKNOWN.value)
            )
        except (ValueError, KeyError):
            control_kind = ControlSemanticKind.UNKNOWN
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=str(data.get("task_id", "")),
            trace_id=data.get("trace_id"),
            source_device_id=str(data.get("source_device_id", "")),
            target_device_id=str(data.get("target_device_id", "")),
            control_kind=control_kind,
            is_local=bool(data.get("is_local", False)),
            is_remote_dispatch=bool(data.get("is_remote_dispatch", False)),
            is_takeover=bool(data.get("is_takeover", False)),
            is_semantically_clear=bool(data.get("is_semantically_clear", False)),
            ambiguity_reasons=list(data.get("ambiguity_reasons", [])),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


@dataclasses.dataclass
class ResultSurfaceRecord:
    """A record of how a cross-device execution result was surfaced.

    Attributes
    ----------
    record_id:
        Unique record identifier (UUID).
    task_id:
        Canonical task ID.
    trace_id:
        Distributed trace ID.
    source_device_id:
        Device that originated the request.
    target_device_ids:
        Devices that participated in execution.
    surface_kind:
        :class:`ResultSurfaceKind` classification.
    is_canonically_surfaced:
        ``True`` when result reached all required canonical surfaces.
    result_envelope_produced:
        ``True`` when a ``ResultEnvelope`` was produced.
    operator_surface_updated:
        ``True`` when ``OperatorSurface`` was updated with the result.
    task_graph_updated:
        ``True`` when ``TaskGraphRuntime`` was updated.
    replay_foundation_updated:
        ``True`` when ``ReplayFoundation`` was updated.
    projection_updated:
        ``True`` when the projection layer was updated.
    surface_gap_reasons:
        Reasons explaining any gaps in surface coverage.
    timestamp:
        Unix timestamp of recording.
    extra:
        Additional metadata.
    """

    record_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    trace_id: Optional[str] = None
    source_device_id: str = ""
    target_device_ids: List[str] = dataclasses.field(default_factory=list)
    surface_kind: ResultSurfaceKind = ResultSurfaceKind.UNKNOWN
    is_canonically_surfaced: bool = False
    result_envelope_produced: bool = False
    operator_surface_updated: bool = False
    task_graph_updated: bool = False
    replay_foundation_updated: bool = False
    projection_updated: bool = False
    surface_gap_reasons: List[str] = dataclasses.field(default_factory=list)
    timestamp: float = dataclasses.field(default_factory=time.time)
    extra: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "record_id": self.record_id,
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "source_device_id": self.source_device_id,
            "target_device_ids": list(self.target_device_ids),
            "surface_kind": self.surface_kind.value,
            "is_canonically_surfaced": self.is_canonically_surfaced,
            "result_envelope_produced": self.result_envelope_produced,
            "operator_surface_updated": self.operator_surface_updated,
            "task_graph_updated": self.task_graph_updated,
            "replay_foundation_updated": self.replay_foundation_updated,
            "projection_updated": self.projection_updated,
            "surface_gap_reasons": list(self.surface_gap_reasons),
            "timestamp": self.timestamp,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ResultSurfaceRecord":
        try:
            surface_kind = ResultSurfaceKind(
                data.get("surface_kind", ResultSurfaceKind.UNKNOWN.value)
            )
        except (ValueError, KeyError):
            surface_kind = ResultSurfaceKind.UNKNOWN
        return cls(
            record_id=data.get("record_id", str(uuid.uuid4())),
            task_id=str(data.get("task_id", "")),
            trace_id=data.get("trace_id"),
            source_device_id=str(data.get("source_device_id", "")),
            target_device_ids=list(data.get("target_device_ids", [])),
            surface_kind=surface_kind,
            is_canonically_surfaced=bool(data.get("is_canonically_surfaced", False)),
            result_envelope_produced=bool(data.get("result_envelope_produced", False)),
            operator_surface_updated=bool(data.get("operator_surface_updated", False)),
            task_graph_updated=bool(data.get("task_graph_updated", False)),
            replay_foundation_updated=bool(data.get("replay_foundation_updated", False)),
            projection_updated=bool(data.get("projection_updated", False)),
            surface_gap_reasons=list(data.get("surface_gap_reasons", [])),
            timestamp=float(data.get("timestamp", time.time())),
            extra=dict(data.get("extra", {})),
        )


@dataclasses.dataclass
class ResidualIntegrityGap:
    """A single remaining multi-device integrity gap left for follow-up work.

    Attributes
    ----------
    gap_id:
        Stable, machine-readable gap identifier (e.g. ``"GAP-517-001"``).
    area:
        Audit area (``"entry_unification"`` | ``"dispatch_authority"`` |
        ``"formation_truth"`` | ``"control_semantics"`` |
        ``"result_surface"``).
    severity:
        ``"HIGH"`` | ``"MEDIUM"`` | ``"LOW"``.
    description:
        Human-readable description of the gap.
    affected_modules:
        List of module/file paths that have this gap.
    recommended_action:
        Recommended follow-up action.
    is_resolved:
        ``True`` when the gap has been closed (for tracking resolved items).
    resolution_note:
        If resolved, a note explaining how.
    """

    gap_id: str = ""
    area: str = ""
    severity: str = "MEDIUM"
    description: str = ""
    affected_modules: List[str] = dataclasses.field(default_factory=list)
    recommended_action: str = ""
    is_resolved: bool = False
    resolution_note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "area": self.area,
            "severity": self.severity,
            "description": self.description,
            "affected_modules": list(self.affected_modules),
            "recommended_action": self.recommended_action,
            "is_resolved": self.is_resolved,
            "resolution_note": self.resolution_note,
        }


@dataclasses.dataclass
class MultiDeviceIntegritySnapshot:
    """Snapshot of the multi-device control integrity runtime state.

    Attributes
    ----------
    snapshot_id:
        Unique snapshot identifier.
    recent_entry_records:
        Recent :class:`EntryUnificationRecord` entries.
    recent_dispatch_records:
        Recent :class:`DispatchAuthorityRecord` entries.
    recent_formation_records:
        Recent :class:`FormationTruthRecord` entries.
    recent_control_semantic_records:
        Recent :class:`ControlSemanticRecord` entries.
    recent_result_surface_records:
        Recent :class:`ResultSurfaceRecord` entries.
    residual_gaps:
        All :class:`ResidualIntegrityGap` entries (open and closed).
    canonical_entry_count:
        Number of canonical entry events recorded.
    legacy_entry_count:
        Number of legacy entry events recorded.
    canonical_dispatch_count:
        Number of canonical dispatch events recorded.
    legacy_dispatch_count:
        Number of legacy dispatch events recorded.
    timestamp:
        Unix timestamp of snapshot creation.
    """

    snapshot_id: str = dataclasses.field(default_factory=lambda: str(uuid.uuid4()))
    recent_entry_records: List[EntryUnificationRecord] = dataclasses.field(
        default_factory=list
    )
    recent_dispatch_records: List[DispatchAuthorityRecord] = dataclasses.field(
        default_factory=list
    )
    recent_formation_records: List[FormationTruthRecord] = dataclasses.field(
        default_factory=list
    )
    recent_control_semantic_records: List[ControlSemanticRecord] = dataclasses.field(
        default_factory=list
    )
    recent_result_surface_records: List[ResultSurfaceRecord] = dataclasses.field(
        default_factory=list
    )
    residual_gaps: List[ResidualIntegrityGap] = dataclasses.field(
        default_factory=list
    )
    canonical_entry_count: int = 0
    legacy_entry_count: int = 0
    canonical_dispatch_count: int = 0
    legacy_dispatch_count: int = 0
    timestamp: float = dataclasses.field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "recent_entry_records": [r.to_dict() for r in self.recent_entry_records],
            "recent_dispatch_records": [r.to_dict() for r in self.recent_dispatch_records],
            "recent_formation_records": [r.to_dict() for r in self.recent_formation_records],
            "recent_control_semantic_records": [
                r.to_dict() for r in self.recent_control_semantic_records
            ],
            "recent_result_surface_records": [
                r.to_dict() for r in self.recent_result_surface_records
            ],
            "residual_gaps": [g.to_dict() for g in self.residual_gaps],
            "canonical_entry_count": self.canonical_entry_count,
            "legacy_entry_count": self.legacy_entry_count,
            "canonical_dispatch_count": self.canonical_dispatch_count,
            "legacy_dispatch_count": self.legacy_dispatch_count,
            "timestamp": self.timestamp,
            "authority": MULTI_DEVICE_CONTROL_INTEGRITY_AUTHORITY,
        }

    def open_gaps(self) -> List[ResidualIntegrityGap]:
        """Return only unresolved gaps."""
        return [g for g in self.residual_gaps if not g.is_resolved]

    def gaps_by_area(self, area: str) -> List[ResidualIntegrityGap]:
        """Return gaps for a specific audit area."""
        return [g for g in self.residual_gaps if g.area == area]


# ---------------------------------------------------------------------------
# Residual integrity gap catalog
# ---------------------------------------------------------------------------

#: Static residual integrity gap catalog for PR-517.
#: Entries with ``is_resolved=True`` document gaps that have been closed.
#: Entries with ``is_resolved=False`` are open and require follow-up.
_RESIDUAL_GAPS: List[Dict[str, Any]] = [
    # -----------------------------------------------------------------------
    # Audit area 1: Entry unification
    # -----------------------------------------------------------------------
    {
        "gap_id": "GAP-517-001",
        "area": "entry_unification",
        "severity": "HIGH",
        "description": (
            "The /api/v1/devices/cross-device REST endpoint "
            "(core/routes/devices.py) calls CrossDeviceCoordinator."
            "execute_cross_device_task() directly, bypassing CommandRouter "
            "and TaskEnvelope normalisation.  This is a legacy path that "
            "should be demoted: calls should be routed through CommandRouter "
            "to produce a canonical TaskEnvelope before reaching the "
            "coordinator substrate."
        ),
        "affected_modules": [
            "core/routes/devices.py",
            "galaxy_gateway/cross_device_coordinator.py",
        ],
        "recommended_action": (
            "In core/routes/devices.py cross_device_task(), normalise the "
            "incoming request to a TaskEnvelope and route through "
            "CommandRouter.route_envelope() instead of calling the coordinator "
            "directly.  The coordinator remains valid as internal substrate "
            "invoked by CommandRouter; it must not be a primary entry target."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    {
        "gap_id": "GAP-517-002",
        "area": "entry_unification",
        "severity": "MEDIUM",
        "description": (
            "The /api/v1/devices/parallel REST endpoint "
            "(core/routes/devices.py) dispatches individual device commands "
            "in parallel without going through the canonical TaskEnvelope / "
            "CommandRouter admission path.  Each parallel command needs its "
            "own TaskEnvelope and CommandRouter admission before reaching the "
            "device substrate."
        ),
        "affected_modules": [
            "core/routes/devices.py",
        ],
        "recommended_action": (
            "Refactor parallel_device_commands() to create a TaskEnvelope for "
            "the top-level parallel request and use CommandRouter to fan out "
            "sub-envelopes, rather than dispatching individual device commands "
            "as raw dicts."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    # -----------------------------------------------------------------------
    # Audit area 2: Dispatch authority
    # -----------------------------------------------------------------------
    {
        "gap_id": "GAP-517-003",
        "area": "dispatch_authority",
        "severity": "HIGH",
        "description": (
            "DeviceRouter._dispatch_cross_device_task() and "
            "CrossDeviceCoordinator.execute_cross_device_task() are currently "
            "callable as independent dispatch authorities from outside the "
            "gateway substrate (e.g. directly from REST routes).  "
            "These must be restricted to internal substrate use only, "
            "reachable exclusively via CommandRouter."
        ),
        "affected_modules": [
            "galaxy_gateway/device_router.py",
            "galaxy_gateway/cross_device_coordinator.py",
            "core/routes/devices.py",
        ],
        "recommended_action": (
            "Add an access-control sentinel or assertion to "
            "_dispatch_cross_device_task() and execute_cross_device_task() "
            "that records/warns when they are called without being invoked "
            "through CommandRouter.  Gate the canonical path so that direct "
            "callers log a LEGACY_DISPATCH warning."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    # -----------------------------------------------------------------------
    # Audit area 3: Formation truth
    # -----------------------------------------------------------------------
    {
        "gap_id": "GAP-517-004",
        "area": "formation_truth",
        "severity": "MEDIUM",
        "description": (
            "The cross-device execution path in DeviceRouter and "
            "CrossDeviceCoordinator does not produce or attach a "
            "DeviceFormationGroup before executing.  This means the formation "
            "descriptor (source device, primary execution device, role "
            "assignments, merge ownership) is implicit rather than explicit, "
            "making the participation/readiness truth hard to inspect or audit."
        ),
        "affected_modules": [
            "galaxy_gateway/device_router.py",
            "galaxy_gateway/cross_device_coordinator.py",
        ],
        "recommended_action": (
            "At the start of cross-device execution in DeviceRouter and "
            "CrossDeviceCoordinator, call resolve_formation() from "
            "core.device_formation to produce a DeviceFormationGroup, then "
            "attach it to the execution context and include it in the "
            "result envelope / audit record."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    {
        "gap_id": "GAP-517-005",
        "area": "formation_truth",
        "severity": "MEDIUM",
        "description": (
            "ConstellationRuntime._is_orchestration_ready() uses a permissive "
            "fallback (returns True) when device_participation is unavailable.  "
            "This can allow devices that have not passed the canonical "
            "admissibility chain to participate in constellation orchestration, "
            "leading to formation truth drift."
        ),
        "affected_modules": [
            "core/constellation_runtime.py",
        ],
        "recommended_action": (
            "Change the fallback in _is_orchestration_ready() to return False "
            "(deny-by-default) when the participation layer is unavailable, "
            "and emit a structured warning that the device was excluded due to "
            "participation-layer unavailability.  Log at WARNING level so "
            "operators can see when the gate is not functioning."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    # -----------------------------------------------------------------------
    # Audit area 4: Control semantics
    # -----------------------------------------------------------------------
    {
        "gap_id": "GAP-517-006",
        "area": "control_semantics",
        "severity": "MEDIUM",
        "description": (
            "The cross-device task context in DeviceRouter.route_task() does "
            "not explicitly label the source_device_id (the device that "
            "originated the request).  The 'device_id' field is overloaded to "
            "mean both 'originating device' and 'target device' depending on "
            "context, causing semantic ambiguity."
        ),
        "affected_modules": [
            "galaxy_gateway/device_router.py",
        ],
        "recommended_action": (
            "Add explicit source_device_id and target_device_id fields to the "
            "task context in route_task().  Populate source_device_id from the "
            "request context (e.g. the device that sent the command) and "
            "target_device_id from the routing decision.  Include both in the "
            "TaskEnvelope metadata and in cross-device audit records."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    # -----------------------------------------------------------------------
    # Audit area 5: Result surface
    # -----------------------------------------------------------------------
    {
        "gap_id": "GAP-517-007",
        "area": "result_surface",
        "severity": "HIGH",
        "description": (
            "Cross-device task results from CrossDeviceCoordinator and "
            "DeviceRouter are returned as raw dicts and are not always "
            "normalised into ResultEnvelope / ChainExecutionRecord before "
            "being returned to the caller.  This means cross-device outcomes "
            "can remain in transport-local state without surfacing through "
            "OperatorSurface, TaskGraphRuntime, or ReplayFoundation."
        ),
        "affected_modules": [
            "galaxy_gateway/cross_device_coordinator.py",
            "galaxy_gateway/device_router.py",
            "core/cross_device_execution_chain.py",
        ],
        "recommended_action": (
            "At the end of every cross-device execution path in "
            "CrossDeviceCoordinator and DeviceRouter, call "
            "build_result_envelope() + record_chain_execution() from "
            "core.cross_device_execution_chain.  Then call "
            "TaskGraphRuntime.complete_from_result_envelope() and "
            "ReplayFoundation.record_task_execution() to ensure the result "
            "is fully surfaced through the canonical layers."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
    {
        "gap_id": "GAP-517-008",
        "area": "result_surface",
        "severity": "MEDIUM",
        "description": (
            "The multi-device runtime projection endpoint "
            "(/api/v1/projection/runtime/multi-device) produces a projection "
            "based on raw registry/session data rather than consuming results "
            "from the canonical CrossDeviceChainSingleton or TaskGraphRuntime.  "
            "This means the projection can reflect an inconsistent state when "
            "some results have only partially surfaced."
        ),
        "affected_modules": [
            "core/routes/projection.py",
            "contracts/multi_device_runtime_projection.py",
        ],
        "recommended_action": (
            "Enrich the multi-device runtime projection with data from "
            "CrossDeviceChainSingleton.snapshot() and "
            "TaskGraphRuntime.snapshot() so that the projection reflects "
            "canonical result state rather than only raw transport-layer "
            "registry data."
        ),
        "is_resolved": False,
        "resolution_note": "",
    },
]


def get_residual_integrity_gaps() -> List[ResidualIntegrityGap]:
    """Return the static residual integrity gap catalog for PR-517.

    Returns
    -------
    List[ResidualIntegrityGap]
        All known gaps (open and closed) for this PR.
    """
    return [ResidualIntegrityGap(**gap) for gap in _RESIDUAL_GAPS]


# ---------------------------------------------------------------------------
# MultiDeviceControlIntegrityRuntime
# ---------------------------------------------------------------------------


class MultiDeviceControlIntegrityRuntime:
    """Bounded in-memory runtime for multi-device control integrity tracking.

    Maintains ring buffers of the five record types and provides a snapshot
    helper.  This class is **read-only with respect to canonical layers** —
    it records observations; it does not modify any existing module.

    Singleton pattern: use :func:`get_multi_device_integrity_runtime` and
    :func:`reset_multi_device_integrity_runtime`.
    """

    def __init__(self, max_records: int = _MAX_RECORDS) -> None:
        self._max = max_records
        self._entry: List[EntryUnificationRecord] = []
        self._dispatch: List[DispatchAuthorityRecord] = []
        self._formation: List[FormationTruthRecord] = []
        self._control: List[ControlSemanticRecord] = []
        self._result: List[ResultSurfaceRecord] = []
        self._canonical_entry = 0
        self._legacy_entry = 0
        self._canonical_dispatch = 0
        self._legacy_dispatch = 0

    # ------------------------------------------------------------------
    # Append helpers
    # ------------------------------------------------------------------

    def append_entry(self, record: EntryUnificationRecord) -> None:
        """Append an :class:`EntryUnificationRecord` to the ring buffer."""
        if len(self._entry) >= self._max:
            self._entry.pop(0)
        self._entry.append(record)
        if record.is_canonical:
            self._canonical_entry += 1
        else:
            self._legacy_entry += 1

    def append_dispatch(self, record: DispatchAuthorityRecord) -> None:
        """Append a :class:`DispatchAuthorityRecord` to the ring buffer."""
        if len(self._dispatch) >= self._max:
            self._dispatch.pop(0)
        self._dispatch.append(record)
        if record.is_canonical:
            self._canonical_dispatch += 1
        else:
            self._legacy_dispatch += 1

    def append_formation(self, record: FormationTruthRecord) -> None:
        """Append a :class:`FormationTruthRecord` to the ring buffer."""
        if len(self._formation) >= self._max:
            self._formation.pop(0)
        self._formation.append(record)

    def append_control(self, record: ControlSemanticRecord) -> None:
        """Append a :class:`ControlSemanticRecord` to the ring buffer."""
        if len(self._control) >= self._max:
            self._control.pop(0)
        self._control.append(record)

    def append_result(self, record: ResultSurfaceRecord) -> None:
        """Append a :class:`ResultSurfaceRecord` to the ring buffer."""
        if len(self._result) >= self._max:
            self._result.pop(0)
        self._result.append(record)

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def snapshot(self, max_recent: int = 20) -> MultiDeviceIntegritySnapshot:
        """Build and return a :class:`MultiDeviceIntegritySnapshot`."""
        return MultiDeviceIntegritySnapshot(
            recent_entry_records=list(self._entry[-max_recent:]),
            recent_dispatch_records=list(self._dispatch[-max_recent:]),
            recent_formation_records=list(self._formation[-max_recent:]),
            recent_control_semantic_records=list(self._control[-max_recent:]),
            recent_result_surface_records=list(self._result[-max_recent:]),
            residual_gaps=get_residual_integrity_gaps(),
            canonical_entry_count=self._canonical_entry,
            legacy_entry_count=self._legacy_entry,
            canonical_dispatch_count=self._canonical_dispatch,
            legacy_dispatch_count=self._legacy_dispatch,
        )

    def clear(self) -> None:
        """Clear all ring buffers (for testing)."""
        self._entry.clear()
        self._dispatch.clear()
        self._formation.clear()
        self._control.clear()
        self._result.clear()
        self._canonical_entry = 0
        self._legacy_entry = 0
        self._canonical_dispatch = 0
        self._legacy_dispatch = 0


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_runtime_singleton: Optional[MultiDeviceControlIntegrityRuntime] = None


def get_multi_device_integrity_runtime() -> MultiDeviceControlIntegrityRuntime:
    """Return the global :class:`MultiDeviceControlIntegrityRuntime`, creating it if needed."""
    global _runtime_singleton
    if _runtime_singleton is None:
        _runtime_singleton = MultiDeviceControlIntegrityRuntime()
    return _runtime_singleton


def reset_multi_device_integrity_runtime() -> None:
    """Reset the global singleton (for testing / re-initialisation)."""
    global _runtime_singleton
    if _runtime_singleton is not None:
        _runtime_singleton.clear()
    _runtime_singleton = None


# ---------------------------------------------------------------------------
# Factory / helper functions
# ---------------------------------------------------------------------------


def build_entry_unification_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    entry_kind: EntryUnificationKind = EntryUnificationKind.UNKNOWN,
    entry_point: str = "",
    reasons: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> EntryUnificationRecord:
    """Construct an :class:`EntryUnificationRecord`.

    ``is_canonical`` is derived automatically: ``True`` only when
    *entry_kind* is :attr:`EntryUnificationKind.CANONICAL`.
    """
    is_canonical = entry_kind == EntryUnificationKind.CANONICAL
    return EntryUnificationRecord(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        entry_kind=entry_kind,
        is_canonical=is_canonical,
        entry_point=entry_point,
        reasons=list(reasons or []),
        extra=dict(extra or {}),
    )


def build_dispatch_authority_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    target_device_ids: Optional[List[str]] = None,
    dispatch_path: DispatchPathKind = DispatchPathKind.UNKNOWN,
    dispatcher_module: str = "",
    reasons: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> DispatchAuthorityRecord:
    """Construct a :class:`DispatchAuthorityRecord`.

    ``is_canonical`` is derived automatically: ``True`` only when
    *dispatch_path* is :attr:`DispatchPathKind.COMMAND_ROUTER_CANONICAL`.
    """
    is_canonical = dispatch_path == DispatchPathKind.COMMAND_ROUTER_CANONICAL
    return DispatchAuthorityRecord(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        target_device_ids=list(target_device_ids or []),
        dispatch_path=dispatch_path,
        is_canonical=is_canonical,
        dispatcher_module=dispatcher_module,
        reasons=list(reasons or []),
        extra=dict(extra or {}),
    )


def build_formation_truth_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    formation_id: str = "",
    consistency: FormationTruthConsistency = FormationTruthConsistency.UNKNOWN,
    member_device_ids: Optional[List[str]] = None,
    ineligible_members: Optional[List[str]] = None,
    drift_reasons: Optional[List[str]] = None,
    source_device_id: str = "",
    primary_device_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> FormationTruthRecord:
    """Construct a :class:`FormationTruthRecord`.

    ``is_consistent`` is derived automatically: ``True`` only when
    *consistency* is :attr:`FormationTruthConsistency.CONSISTENT`.
    """
    is_consistent = consistency == FormationTruthConsistency.CONSISTENT
    return FormationTruthRecord(
        task_id=task_id,
        trace_id=trace_id,
        formation_id=formation_id,
        consistency=consistency,
        is_consistent=is_consistent,
        member_device_ids=list(member_device_ids or []),
        ineligible_members=list(ineligible_members or []),
        drift_reasons=list(drift_reasons or []),
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        extra=dict(extra or {}),
    )


def build_control_semantic_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    target_device_id: str = "",
    control_kind: ControlSemanticKind = ControlSemanticKind.UNKNOWN,
    is_takeover: bool = False,
    ambiguity_reasons: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ControlSemanticRecord:
    """Construct a :class:`ControlSemanticRecord`.

    ``is_local``, ``is_remote_dispatch``, and ``is_semantically_clear`` are
    derived automatically from *source_device_id*, *target_device_id*, and
    *control_kind*.
    """
    # Derive local / remote flags
    is_local = bool(
        source_device_id
        and target_device_id
        and source_device_id == target_device_id
        and control_kind == ControlSemanticKind.LOCAL_EXECUTION
    )
    is_remote_dispatch = control_kind == ControlSemanticKind.REMOTE_DISPATCH

    # A record is semantically clear when source, target, and kind are all set
    # and non-ambiguous.
    is_semantically_clear = bool(
        source_device_id
        and target_device_id
        and control_kind not in (ControlSemanticKind.UNKNOWN,)
        and not (ambiguity_reasons)
    )

    return ControlSemanticRecord(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        control_kind=control_kind,
        is_local=is_local,
        is_remote_dispatch=is_remote_dispatch,
        is_takeover=is_takeover,
        is_semantically_clear=is_semantically_clear,
        ambiguity_reasons=list(ambiguity_reasons or []),
        extra=dict(extra or {}),
    )


def build_result_surface_record(
    *,
    task_id: str = "",
    trace_id: Optional[str] = None,
    source_device_id: str = "",
    target_device_ids: Optional[List[str]] = None,
    result_envelope_produced: bool = False,
    operator_surface_updated: bool = False,
    task_graph_updated: bool = False,
    replay_foundation_updated: bool = False,
    projection_updated: bool = False,
    surface_gap_reasons: Optional[List[str]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ResultSurfaceRecord:
    """Construct a :class:`ResultSurfaceRecord`.

    ``surface_kind`` and ``is_canonically_surfaced`` are derived automatically
    from the individual surface flags.
    """
    # Determine surface kind from flags
    all_surfaces = (
        result_envelope_produced
        and operator_surface_updated
        and task_graph_updated
        and replay_foundation_updated
    )
    any_surface = any(
        [
            result_envelope_produced,
            operator_surface_updated,
            task_graph_updated,
            replay_foundation_updated,
            projection_updated,
        ]
    )

    if all_surfaces:
        surface_kind = ResultSurfaceKind.CANONICAL_FULL
        is_canonical = True
    elif any_surface:
        surface_kind = ResultSurfaceKind.CANONICAL_PARTIAL
        is_canonical = False
    else:
        surface_kind = ResultSurfaceKind.TRANSPORT_LOCAL_ONLY
        is_canonical = False

    return ResultSurfaceRecord(
        task_id=task_id,
        trace_id=trace_id,
        source_device_id=source_device_id,
        target_device_ids=list(target_device_ids or []),
        surface_kind=surface_kind,
        is_canonically_surfaced=is_canonical,
        result_envelope_produced=result_envelope_produced,
        operator_surface_updated=operator_surface_updated,
        task_graph_updated=task_graph_updated,
        replay_foundation_updated=replay_foundation_updated,
        projection_updated=projection_updated,
        surface_gap_reasons=list(surface_gap_reasons or []),
        extra=dict(extra or {}),
    )


def record_integrity_event(
    *,
    entry_record: Optional[EntryUnificationRecord] = None,
    dispatch_record: Optional[DispatchAuthorityRecord] = None,
    formation_record: Optional[FormationTruthRecord] = None,
    control_record: Optional[ControlSemanticRecord] = None,
    result_record: Optional[ResultSurfaceRecord] = None,
) -> None:
    """Append one or more integrity records to the global singleton.

    All parameters are optional — supply only the records that apply to the
    current event.  This is the primary way for callers to emit integrity
    observations.
    """
    rt = get_multi_device_integrity_runtime()
    if entry_record is not None:
        rt.append_entry(entry_record)
        if not entry_record.is_canonical:
            logger.warning(
                "ENTRY_UNIFICATION_LEGACY | task_id=%s source=%s entry_point=%s "
                "entry_kind=%s | Route through CommandRouter → TaskEnvelope instead.",
                entry_record.task_id,
                entry_record.source_device_id,
                entry_record.entry_point,
                entry_record.entry_kind.value,
            )
    if dispatch_record is not None:
        rt.append_dispatch(dispatch_record)
        if not dispatch_record.is_canonical:
            logger.warning(
                "DISPATCH_AUTHORITY_LEGACY | task_id=%s source=%s dispatcher=%s "
                "dispatch_path=%s | Route through CommandRouter instead.",
                dispatch_record.task_id,
                dispatch_record.source_device_id,
                dispatch_record.dispatcher_module,
                dispatch_record.dispatch_path.value,
            )
    if formation_record is not None:
        rt.append_formation(formation_record)
        if not formation_record.is_consistent:
            logger.warning(
                "FORMATION_TRUTH_DRIFT | task_id=%s formation=%s "
                "consistency=%s ineligible=%s drift=%s",
                formation_record.task_id,
                formation_record.formation_id,
                formation_record.consistency.value,
                formation_record.ineligible_members,
                formation_record.drift_reasons,
            )
    if control_record is not None:
        rt.append_control(control_record)
        if not control_record.is_semantically_clear:
            logger.info(
                "CONTROL_SEMANTIC_AMBIGUITY | task_id=%s source=%s target=%s "
                "kind=%s ambiguity=%s",
                control_record.task_id,
                control_record.source_device_id,
                control_record.target_device_id,
                control_record.control_kind.value,
                control_record.ambiguity_reasons,
            )
    if result_record is not None:
        rt.append_result(result_record)
        if not result_record.is_canonically_surfaced:
            logger.warning(
                "RESULT_SURFACE_INCOMPLETE | task_id=%s source=%s "
                "surface_kind=%s envelope=%s operator=%s graph=%s replay=%s",
                result_record.task_id,
                result_record.source_device_id,
                result_record.surface_kind.value,
                result_record.result_envelope_produced,
                result_record.operator_surface_updated,
                result_record.task_graph_updated,
                result_record.replay_foundation_updated,
            )


def build_integrity_snapshot(max_recent: int = 20) -> MultiDeviceIntegritySnapshot:
    """Build a :class:`MultiDeviceIntegritySnapshot` from the global singleton.

    Suitable for embedding in operator inspection payloads, projection
    responses, and audit logs.
    """
    return get_multi_device_integrity_runtime().snapshot(max_recent=max_recent)
