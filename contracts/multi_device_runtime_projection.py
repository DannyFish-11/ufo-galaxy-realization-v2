"""contracts/multi_device_runtime_projection.py
=================================================
Unified Multi-Device Runtime Projection Contract — PR-38 / PR-8 consolidation.

**PR-8 canonical closure:** This module is the **sole canonical top-level
multi-device runtime read projection** for the Galaxy / OpenClawd system.  No
new top-level multi-device read model should be introduced outside this module.
Device entries are explicitly anchored on
:class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice` (the
canonical single-device read contract) via the
:func:`from_registered_runtime_device` adapter introduced in PR-8.

This module defines the **canonical Unified Multi-Device Runtime Projection**:
a single, fully serialisable, read-only contract that aggregates the multi-device
runtime state across all device, host, mesh, session, dispatch, handoff, coordination,
and result contracts introduced in PR-29 through PR-37.

It answers the architectural question:

    *"What is the canonical read-only projection of the current multi-device
    runtime state across devices, runtimes, sessions, dispatch decisions,
    handoffs, coordination, and merged results?"*

This module is the **top-level read model** — the single projection that
downstream consumers (observability, debugging, dashboard) read instead of
piecing together multiple route payloads or contract modules.

Contract chain consumed
-----------------------
- **PR-29** (:class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`)
  — runtime-capable devices
- **PR-30** (:class:`~contracts.local_runtime_host.LocalRuntimeHost`)
  — local runtime hosts
- **PR-31** (:class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2`)
  — handoff envelopes / summaries
- **PR-32** (:class:`~contracts.mesh_membership.MeshMembership`)
  — mesh memberships
- **PR-33** (:class:`~contracts.mesh_session.MeshSession`)
  — mesh sessions
- **PR-34** (:class:`~contracts.local_takeover_result.LocalTakeoverResult`)
  — target-side takeover summaries
- **PR-35** (:class:`~contracts.source_dispatch.SourceDispatchSummary`)
  — source dispatch summaries
- **PR-36** (:class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`)
  — merged result summaries
- **PR-37** (:class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`)
  — coordinator summaries
- **PR-27/28** — governance snapshot / policy alignment (optional summary dict)

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — ``to_dict`` / ``to_json`` / ``from_dict`` produce
  stable, round-trippable output.
- **Graceful defaults** — all collection fields default to empty lists/dicts;
  all optional scalar fields default to ``None``.  A valid projection is always
  constructable from no inputs.
- **Stable field names** — downstream consumers can rely on every field name.
- **Read-only semantics** — no write, command, or control surface.
- **No UI semantics** — purely for runtime state projection / observability.
- **Tolerant of partial/missing data** — all builders accept ``None`` gracefully.

Usage::

    from contracts.multi_device_runtime_projection import (
        MultiDeviceRuntimeProjection,
        build_multi_device_runtime_projection,
    )

    projection = build_multi_device_runtime_projection(
        runtime_devices=[device_contract, ...],
        runtime_hosts=[host_contract, ...],
        mesh_sessions=[session_contract, ...],
    )
    print(projection.to_json(indent=2))
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# PR-8 canonical authority markers
# ---------------------------------------------------------------------------

#: True-valued sentinel that lets downstream code and audit tooling assert that
#: this module is the canonical top-level multi-device runtime read projection.
CANONICAL_TOP_LEVEL_PROJECTION: bool = True

#: Human-readable authority declaration consumed by anti-drift audit scripts.
__canonical_authority__: str = (
    "MultiDeviceRuntimeProjection is the sole canonical top-level multi-device "
    "runtime read projection.  All downstream consumers must read this projection "
    "rather than assembling cross-runtime state from individual contract modules. "
    "Device entries are anchored on RegisteredRuntimeDevice (canonical single-device "
    "read contract).  No parallel top-level multi-device read model should be "
    "introduced outside this module.  — PR-8 consolidation."
)

# ---------------------------------------------------------------------------
# Sub-projection entry contracts
# ---------------------------------------------------------------------------


class RuntimeProjectionDeviceEntry(BaseModel):
    """Read-only projection entry for a registered runtime-capable device (PR-29).

    A compact, stable view of a
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`.
    """

    device_id: str = Field(description="Unique device identifier.")
    platform: Optional[str] = Field(
        default=None, description="Device platform (e.g. 'android', 'windows', 'macos')."
    )
    form_factor: Optional[str] = Field(
        default=None, description="Device form factor (e.g. 'phone', 'tablet', 'desktop')."
    )
    status: Optional[str] = Field(
        default=None, description="Current device status (e.g. 'online', 'offline')."
    )
    connection_state: Optional[str] = Field(
        default=None,
        description="Current connection state (e.g. 'connected', 'disconnected').",
    )
    runtime_capable: bool = Field(
        default=True, description="Whether the device is capable of hosting a runtime."
    )
    health_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Health score [0, 1]."
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture (PR-5 / post-533). "
            "Canonical values: 'control_only' or 'join_runtime'."
        ),
    )
    is_runtime_host: bool = Field(
        default=False,
        description=(
            "Whether this device is classified as a first-class runtime host (PR-5). "
            "Distinguishes host-capable devices from connected-device-only presences."
        ),
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionHostEntry(BaseModel):
    """Read-only projection entry for a local runtime host (PR-30).

    A compact, stable view of a
    :class:`~contracts.local_runtime_host.LocalRuntimeHost`.
    """

    host_id: str = Field(description="Unique identifier for this runtime host.")
    device_id: Optional[str] = Field(
        default=None, description="Underlying device ID."
    )
    status: Optional[str] = Field(
        default=None, description="Host lifecycle status."
    )
    execution_mode: Optional[str] = Field(
        default=None, description="Current execution mode."
    )
    accepts_handoff: bool = Field(
        default=False, description="Whether the host accepts incoming handoffs."
    )
    can_delegate: bool = Field(
        default=False, description="Whether the host can delegate to other runtimes."
    )
    source_runtime_posture: str = Field(
        default="control_only",
        description=(
            "Source-device runtime participation posture propagated from the "
            "originating LocalRuntimeHost (PR-5 / post-533)."
        ),
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionMeshSessionEntry(BaseModel):
    """Read-only projection entry for an active mesh session (PR-33).

    A compact, stable view of a
    :class:`~contracts.mesh_session.MeshSession`.
    """

    session_id: str = Field(description="Unique mesh session identifier.")
    mesh_id: Optional[str] = Field(default=None, description="Mesh/body identifier.")
    status: Optional[str] = Field(default=None, description="Session lifecycle status.")
    source_device_id: Optional[str] = Field(
        default=None, description="Device that initiated the session."
    )
    primary_device_id: Optional[str] = Field(
        default=None, description="Device executing primarily."
    )
    participant_count: int = Field(
        default=0, description="Number of participants in this session."
    )
    multi_device_required: bool = Field(
        default=False, description="Whether multi-device is required."
    )
    merge_policy: Optional[str] = Field(
        default=None, description="Result merge policy."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionDispatchEntry(BaseModel):
    """Read-only projection entry for a source dispatch decision (PR-35).

    A compact, stable view of a
    :class:`~contracts.source_dispatch.SourceDispatchSummary`.
    """

    dispatch_id: str = Field(description="Unique dispatch identifier.")
    mode: Optional[str] = Field(
        default=None, description="Dispatch mode (e.g. 'local', 'remote_handoff', 'staged_mesh')."
    )
    status: Optional[str] = Field(default=None, description="Dispatch result status.")
    source_device_id: Optional[str] = Field(
        default=None, description="Originating device ID."
    )
    target_device_id: Optional[str] = Field(
        default=None, description="Target device ID, if applicable."
    )
    mesh_session_id: Optional[str] = Field(
        default=None, description="Associated mesh session ID."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionHandoffEntry(BaseModel):
    """Read-only projection entry for a handoff envelope (PR-31).

    A compact, stable view of a
    :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` or handoff summary.
    """

    handoff_id: str = Field(description="Unique handoff envelope identifier.")
    source_device_id: Optional[str] = Field(
        default=None, description="Source device ID."
    )
    target_device_id: Optional[str] = Field(
        default=None, description="Target device ID."
    )
    task_id: Optional[str] = Field(default=None, description="Associated task ID.")
    session_id: Optional[str] = Field(default=None, description="Associated session ID.")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionTakeoverEntry(BaseModel):
    """Read-only projection entry for a local takeover result (PR-34).

    A compact, stable view of a
    :class:`~contracts.local_takeover_result.LocalTakeoverResult`.
    """

    result_id: str = Field(description="Unique takeover result identifier.")
    status: Optional[str] = Field(
        default=None, description="Takeover execution status."
    )
    device_id: Optional[str] = Field(default=None, description="Target device ID.")
    handoff_id: Optional[str] = Field(
        default=None, description="Associated handoff envelope ID."
    )
    session_id: Optional[str] = Field(default=None, description="Associated session ID.")
    task_id: Optional[str] = Field(default=None, description="Associated task ID.")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionCoordinatorEntry(BaseModel):
    """Read-only projection entry for a mesh session coordinator summary (PR-37).

    A compact, stable view of a
    :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`.
    """

    coordinator_id: Optional[str] = Field(
        default=None, description="Coordinator instance identifier."
    )
    session_id: Optional[str] = Field(
        default=None, description="Session being coordinated."
    )
    mesh_id: Optional[str] = Field(default=None, description="Mesh identifier.")
    status: Optional[str] = Field(default=None, description="Coordinator status.")
    participant_count: int = Field(default=0)
    pending_count: int = Field(default=0)
    completed_count: int = Field(default=0)
    failed_count: int = Field(default=0)
    has_result_merge_summary: bool = Field(default=False)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


class RuntimeProjectionResultEntry(BaseModel):
    """Read-only projection entry for a cross-runtime merged result summary (PR-36).

    A compact, stable view of a
    :class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`.
    """

    merge_id: str = Field(description="Unique result merge identifier.")
    status: Optional[str] = Field(default=None, description="Overall merge status.")
    result_unit_count: int = Field(default=0, description="Number of result units merged.")
    merge_policy: Optional[str] = Field(default=None, description="Merge policy applied.")
    session_id: Optional[str] = Field(
        default=None, description="Associated mesh session ID."
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Top-level unified projection
# ---------------------------------------------------------------------------


class MultiDeviceRuntimeProjection(BaseModel):
    """Canonical read-only projection of the current multi-device runtime state.

    This is the **top-level read model** that answers:

        *"What is the canonical read-only projection of the current multi-device
        runtime state across devices, runtimes, sessions, dispatch decisions,
        handoffs, coordination, and merged results?"*

    It aggregates all state surfaces introduced in PR-29 through PR-37 into a
    single serialisable object.

    All collection fields default to empty lists.  All optional scalar fields
    default to ``None``.  A valid projection is always constructable — even with
    no input — making it safe to produce incremental or partial projections.

    Fields
    ------
    projection_id
        Stable, globally-unique identifier for this projection snapshot.
    generated_at
        Unix epoch seconds when this projection was assembled.
    runtime_devices
        Projection entries for all known runtime-capable devices (PR-29).
    runtime_hosts
        Projection entries for all local runtime hosts (PR-30).
    mesh_memberships
        Raw serialised mesh membership summaries (PR-32).
    mesh_sessions
        Projection entries for all known/active mesh sessions (PR-33).
    source_dispatches
        Projection entries for active/recent source dispatch decisions (PR-35).
    handoff_summaries
        Projection entries for recent handoff envelopes (PR-31).
    takeover_summaries
        Projection entries for recent local takeover results (PR-34).
    coordinator_summaries
        Projection entries for active mesh session coordinators (PR-37).
    merged_results
        Projection entries for cross-runtime merged result summaries (PR-36).
    governance_snapshot
        Optional compact dict from the runtime governance snapshot (PR-27).
    policy_alignment
        Optional compact dict from the execution policy alignment surface (PR-28).
    metadata
        Arbitrary extensibility bag.
    """

    projection_id: str = Field(
        default_factory=lambda: f"mdrt_proj_{uuid.uuid4().hex[:12]}",
        description="Stable, globally-unique identifier for this projection snapshot.",
    )
    generated_at: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this projection was assembled.",
    )
    # PR-29
    runtime_devices: List[RuntimeProjectionDeviceEntry] = Field(
        default_factory=list,
        description="Projection entries for all known runtime-capable devices (PR-29).",
    )
    # PR-30
    runtime_hosts: List[RuntimeProjectionHostEntry] = Field(
        default_factory=list,
        description="Projection entries for all local runtime hosts (PR-30).",
    )
    # PR-32
    mesh_memberships: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Compact mesh membership summaries (PR-32).  "
            "Each element is a serialised MeshMembership or its compact summary dict."
        ),
    )
    # PR-33
    mesh_sessions: List[RuntimeProjectionMeshSessionEntry] = Field(
        default_factory=list,
        description="Projection entries for all known/active mesh sessions (PR-33).",
    )
    # PR-35
    source_dispatches: List[RuntimeProjectionDispatchEntry] = Field(
        default_factory=list,
        description=(
            "Projection entries for active/recent source dispatch decisions (PR-35)."
        ),
    )
    # PR-31
    handoff_summaries: List[RuntimeProjectionHandoffEntry] = Field(
        default_factory=list,
        description="Projection entries for recent handoff envelopes (PR-31).",
    )
    # PR-34
    takeover_summaries: List[RuntimeProjectionTakeoverEntry] = Field(
        default_factory=list,
        description=(
            "Projection entries for recent local takeover results (PR-34)."
        ),
    )
    # PR-37
    coordinator_summaries: List[RuntimeProjectionCoordinatorEntry] = Field(
        default_factory=list,
        description=(
            "Projection entries for active mesh session coordinators (PR-37)."
        ),
    )
    # PR-36
    merged_results: List[RuntimeProjectionResultEntry] = Field(
        default_factory=list,
        description=(
            "Projection entries for cross-runtime merged result summaries (PR-36)."
        ),
    )
    # PR-27 (optional)
    governance_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional compact dict from the runtime governance snapshot (PR-27).  "
            "None when governance snapshot is unavailable."
        ),
    )
    # PR-28 (optional)
    policy_alignment: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional compact dict from the execution policy alignment surface (PR-28).  "
            "None when policy alignment is unavailable."
        ),
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value metadata for extensibility.",
    )
    # PR-39 (optional)
    runtime_recovery: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional compact recovery/reconciliation summary (PR-39).  "
            "None when no recovery incidents are detected or the recovery "
            "contract is unavailable."
        ),
    )
    # PR-40 (optional)
    runtime_session_snapshot: Optional[Dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional durable runtime session snapshot summary (PR-40).  "
            "None when no session snapshot has been attached to this projection."
        ),
    )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a stable, JSON-safe dictionary representation."""
        return self.model_dump(mode="json")

    def to_json(self, *, indent: Optional[int] = None) -> str:
        """Return a stable JSON string.

        Args:
            indent: Optional indentation level for pretty-printing.

        Returns:
            A stable JSON string.
        """
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MultiDeviceRuntimeProjection":
        """Construct from a dictionary, tolerating unknown extra fields."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a lightweight summary dict suitable for log lines and quick consumers."""
        return {
            "projection_id": self.projection_id,
            "generated_at": self.generated_at,
            "device_count": len(self.runtime_devices),
            "host_count": len(self.runtime_hosts),
            "mesh_membership_count": len(self.mesh_memberships),
            "mesh_session_count": len(self.mesh_sessions),
            "source_dispatch_count": len(self.source_dispatches),
            "handoff_count": len(self.handoff_summaries),
            "takeover_count": len(self.takeover_summaries),
            "coordinator_count": len(self.coordinator_summaries),
            "merged_result_count": len(self.merged_results),
            "has_governance_snapshot": self.governance_snapshot is not None,
            "has_policy_alignment": self.policy_alignment is not None,
        }

    def __repr__(self) -> str:
        return (
            f"<MultiDeviceRuntimeProjection "
            f"id={self.projection_id!r} "
            f"devices={len(self.runtime_devices)} "
            f"sessions={len(self.mesh_sessions)}>"
        )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    """Return ``str(value)`` or *default* if *value* is falsy."""
    if value is None:
        return default
    try:
        return str(value)
    except Exception:
        return default


def _safe_dict(value: Any) -> Dict[str, Any]:
    """Return *value* if it is a dict, else ``{}``."""
    if isinstance(value, dict):
        return value
    try:
        if hasattr(value, "to_dict"):
            return value.to_dict()
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
    except Exception:
        pass
    return {}


def _safe_list(value: Any) -> list:
    """Return *value* if it is a list, else ``[]``."""
    if isinstance(value, list):
        return value
    return []


# ---------------------------------------------------------------------------
# Sub-projection builders / adapters
# ---------------------------------------------------------------------------


def project_runtime_devices(
    runtime_devices: Optional[List[Any]] = None,
) -> List[RuntimeProjectionDeviceEntry]:
    """Build :class:`RuntimeProjectionDeviceEntry` list from registered device contracts.

    Parameters
    ----------
    runtime_devices:
        List of :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
        objects, compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionDeviceEntry]
        Always returns a list (empty when input is ``None`` or empty).
    """
    result: List[RuntimeProjectionDeviceEntry] = []
    for item in _safe_list(runtime_devices):
        try:
            d = _safe_dict(item)
            entry = RuntimeProjectionDeviceEntry(
                device_id=_safe_str(d.get("device_id") or d.get("id"), default=f"dev_{uuid.uuid4().hex[:8]}"),
                platform=d.get("platform"),
                form_factor=d.get("form_factor"),
                status=d.get("status"),
                connection_state=d.get("connection_state")
                or (_safe_dict(d.get("connection_summary", {})).get("state")),
                runtime_capable=bool(d.get("runtime_capable", True)),
                health_score=d.get("health_score"),
                source_runtime_posture=str(
                    d.get("source_runtime_posture", "control_only") or "control_only"
                ),
                is_runtime_host=bool(d.get("is_runtime_host", False)),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def from_registered_runtime_device(device: Any) -> RuntimeProjectionDeviceEntry:
    """Build a :class:`RuntimeProjectionDeviceEntry` explicitly from a canonical
    :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`.

    This is the **PR-8 canonical adapter**.  It makes the anchoring of device
    entries on the canonical single-device read contract explicit and auditable.
    Downstream code that populates projection device entries should prefer this
    function over raw dict construction.

    The function is intentionally tolerant: it also accepts a ``dict`` with the
    same field names as ``RegisteredRuntimeDevice``, so callers can pass either
    a live contract object or a previously serialised ``to_dict()`` payload.

    Parameters
    ----------
    device:
        A :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
        instance, or a compatible dict produced by
        ``RegisteredRuntimeDevice.to_dict()``.

    Returns
    -------
    RuntimeProjectionDeviceEntry
        A compact, stable read projection entry anchored on the canonical
        single-device contract.

    Raises
    ------
    ValueError
        If *device* is ``None`` or cannot be coerced to a valid entry.
    """
    if device is None:
        raise ValueError("device must not be None")
    d = _safe_dict(device)
    if not d:
        raise ValueError(f"Cannot build RuntimeProjectionDeviceEntry from {device!r}")

    # Extract connection state from the canonical connection_summary sub-contract
    # (RegisteredRuntimeDevice.connection.state) or a flat connection_state field.
    connection_state = d.get("connection_state")
    if not connection_state:
        conn = _safe_dict(d.get("connection") or d.get("connection_summary") or {})
        connection_state = conn.get("state") or conn.get("connection_state")

    # Extract health_score — RegisteredRuntimeDevice carries this at the top level.
    health_score = d.get("health_score")
    if health_score is not None:
        try:
            health_score = float(health_score)
        except (TypeError, ValueError):
            health_score = None

    return RuntimeProjectionDeviceEntry(
        device_id=_safe_str(
            d.get("device_id") or d.get("id"),
            default=f"dev_{uuid.uuid4().hex[:8]}",
        ),
        platform=d.get("platform"),
        form_factor=d.get("form_factor"),
        status=d.get("status"),
        connection_state=connection_state,
        runtime_capable=bool(d.get("runtime_capable", True)),
        health_score=health_score,
        source_runtime_posture=str(d.get("source_runtime_posture", "control_only") or "control_only"),
        is_runtime_host=bool(d.get("is_runtime_host", False)),
        metadata=_safe_dict(d.get("metadata", {})),
    )


def project_runtime_hosts(
    runtime_hosts: Optional[List[Any]] = None,
) -> List[RuntimeProjectionHostEntry]:
    """Build :class:`RuntimeProjectionHostEntry` list from local runtime host contracts.

    Parameters
    ----------
    runtime_hosts:
        List of :class:`~contracts.local_runtime_host.LocalRuntimeHost` objects,
        compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionHostEntry]
    """
    result: List[RuntimeProjectionHostEntry] = []
    for item in _safe_list(runtime_hosts):
        try:
            d = _safe_dict(item)
            caps = _safe_dict(d.get("capabilities", {}))
            host_id = _safe_str(
                d.get("host_id") or d.get("id"),
                default=f"host_{uuid.uuid4().hex[:8]}",
            )
            entry = RuntimeProjectionHostEntry(
                host_id=host_id,
                device_id=d.get("device_id"),
                status=d.get("status"),
                execution_mode=d.get("execution_mode"),
                accepts_handoff=bool(caps.get("accepts_handoff", d.get("accepts_handoff", False))),
                can_delegate=bool(caps.get("can_delegate", d.get("can_delegate", False))),
                source_runtime_posture=str(
                    d.get("source_runtime_posture", "control_only") or "control_only"
                ),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_mesh_sessions(
    mesh_sessions: Optional[List[Any]] = None,
) -> List[RuntimeProjectionMeshSessionEntry]:
    """Build :class:`RuntimeProjectionMeshSessionEntry` list from mesh session contracts.

    Parameters
    ----------
    mesh_sessions:
        List of :class:`~contracts.mesh_session.MeshSession` objects, compatible
        dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionMeshSessionEntry]
    """
    result: List[RuntimeProjectionMeshSessionEntry] = []
    for item in _safe_list(mesh_sessions):
        try:
            d = _safe_dict(item)
            session_id = _safe_str(
                d.get("session_id"),
                default=f"msess_{uuid.uuid4().hex[:8]}",
            )
            participants = _safe_list(d.get("participants", []))
            entry = RuntimeProjectionMeshSessionEntry(
                session_id=session_id,
                mesh_id=d.get("mesh_id"),
                status=d.get("status"),
                source_device_id=d.get("source_device_id"),
                primary_device_id=d.get("primary_device_id"),
                participant_count=len(participants),
                multi_device_required=bool(d.get("multi_device_required", False)),
                merge_policy=d.get("merge_policy"),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_source_dispatches(
    source_dispatches: Optional[List[Any]] = None,
) -> List[RuntimeProjectionDispatchEntry]:
    """Build :class:`RuntimeProjectionDispatchEntry` list from source dispatch summaries.

    Parameters
    ----------
    source_dispatches:
        List of :class:`~contracts.source_dispatch.SourceDispatchSummary` objects,
        :class:`~contracts.source_dispatch.SourceDispatchResult` objects,
        compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionDispatchEntry]
    """
    result: List[RuntimeProjectionDispatchEntry] = []
    for item in _safe_list(source_dispatches):
        try:
            d = _safe_dict(item)
            dispatch_id = _safe_str(
                d.get("dispatch_id") or d.get("result_id") or d.get("summary_id"),
                default=f"disp_{uuid.uuid4().hex[:8]}",
            )
            # target may be a nested dict
            target = _safe_dict(d.get("target", {}))
            entry = RuntimeProjectionDispatchEntry(
                dispatch_id=dispatch_id,
                mode=d.get("mode"),
                status=d.get("status"),
                source_device_id=d.get("source_device_id"),
                target_device_id=target.get("target_device_id") or d.get("target_device_id"),
                mesh_session_id=target.get("mesh_session_id") or d.get("mesh_session_id"),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_handoffs(
    handoff_summaries: Optional[List[Any]] = None,
) -> List[RuntimeProjectionHandoffEntry]:
    """Build :class:`RuntimeProjectionHandoffEntry` list from handoff envelope contracts.

    Parameters
    ----------
    handoff_summaries:
        List of :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` objects,
        compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionHandoffEntry]
    """
    result: List[RuntimeProjectionHandoffEntry] = []
    for item in _safe_list(handoff_summaries):
        try:
            d = _safe_dict(item)
            handoff_id = _safe_str(
                d.get("handoff_id") or d.get("envelope_id") or d.get("id"),
                default=f"hoff_{uuid.uuid4().hex[:8]}",
            )
            source = _safe_dict(d.get("source", {}))
            target = _safe_dict(d.get("target", {}))
            entry = RuntimeProjectionHandoffEntry(
                handoff_id=handoff_id,
                source_device_id=source.get("device_id") or d.get("source_device_id"),
                target_device_id=target.get("device_id") or d.get("target_device_id"),
                task_id=d.get("task_id") or _safe_dict(d.get("task", {})).get("task_id"),
                session_id=d.get("session_id")
                or _safe_dict(d.get("session_context", {})).get("session_id"),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_takeovers(
    takeover_summaries: Optional[List[Any]] = None,
) -> List[RuntimeProjectionTakeoverEntry]:
    """Build :class:`RuntimeProjectionTakeoverEntry` list from local takeover result contracts.

    Parameters
    ----------
    takeover_summaries:
        List of :class:`~contracts.local_takeover_result.LocalTakeoverResult` objects,
        compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionTakeoverEntry]
    """
    result: List[RuntimeProjectionTakeoverEntry] = []
    for item in _safe_list(takeover_summaries):
        try:
            d = _safe_dict(item)
            result_id = _safe_str(
                d.get("result_id") or d.get("takeover_id") or d.get("id"),
                default=f"tkov_{uuid.uuid4().hex[:8]}",
            )
            ctx = _safe_dict(d.get("session_context", {}))
            entry = RuntimeProjectionTakeoverEntry(
                result_id=result_id,
                status=d.get("status"),
                device_id=ctx.get("device_id") or d.get("device_id"),
                handoff_id=ctx.get("handoff_id") or d.get("handoff_id"),
                session_id=ctx.get("session_id") or d.get("session_id"),
                task_id=ctx.get("task_id") or d.get("task_id"),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_coordinator_state(
    coordinator_summaries: Optional[List[Any]] = None,
) -> List[RuntimeProjectionCoordinatorEntry]:
    """Build :class:`RuntimeProjectionCoordinatorEntry` list from coordinator summaries.

    Parameters
    ----------
    coordinator_summaries:
        List of :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`
        objects, :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        objects, compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionCoordinatorEntry]
    """
    result: List[RuntimeProjectionCoordinatorEntry] = []
    for item in _safe_list(coordinator_summaries):
        try:
            d = _safe_dict(item)
            entry = RuntimeProjectionCoordinatorEntry(
                coordinator_id=d.get("coordinator_id"),
                session_id=d.get("session_id"),
                mesh_id=d.get("mesh_id"),
                status=d.get("status"),
                participant_count=int(d.get("participant_count", 0)),
                pending_count=int(d.get("pending_count", len(_safe_list(d.get("pending_device_ids", []))))),
                completed_count=int(d.get("completed_count", len(_safe_list(d.get("completed_device_ids", []))))),
                failed_count=int(d.get("failed_count", len(_safe_list(d.get("failed_device_ids", []))))),
                has_result_merge_summary=bool(
                    d.get("has_result_merge_summary", d.get("result_merge_summary") is not None)
                ),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


def project_merged_results(
    merged_results: Optional[List[Any]] = None,
) -> List[RuntimeProjectionResultEntry]:
    """Build :class:`RuntimeProjectionResultEntry` list from result merge summaries.

    Parameters
    ----------
    merged_results:
        List of :class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`
        or :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`
        objects, compatible dicts, or ``None``.

    Returns
    -------
    List[RuntimeProjectionResultEntry]
    """
    result: List[RuntimeProjectionResultEntry] = []
    for item in _safe_list(merged_results):
        try:
            d = _safe_dict(item)
            merge_id = _safe_str(
                d.get("merge_id") or d.get("summary_id") or d.get("id"),
                default=f"mrg_{uuid.uuid4().hex[:8]}",
            )
            units = _safe_list(d.get("result_units", d.get("units", [])))
            entry = RuntimeProjectionResultEntry(
                merge_id=merge_id,
                status=d.get("status") or d.get("overall_status"),
                result_unit_count=int(d.get("result_unit_count", len(units))),
                merge_policy=d.get("merge_policy"),
                session_id=d.get("session_id"),
                metadata=_safe_dict(d.get("metadata", {})),
            )
            result.append(entry)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Top-level projection builder
# ---------------------------------------------------------------------------


def build_multi_device_runtime_projection(
    *,
    runtime_devices: Optional[List[Any]] = None,
    runtime_hosts: Optional[List[Any]] = None,
    mesh_memberships: Optional[List[Any]] = None,
    mesh_sessions: Optional[List[Any]] = None,
    source_dispatches: Optional[List[Any]] = None,
    handoff_summaries: Optional[List[Any]] = None,
    takeover_summaries: Optional[List[Any]] = None,
    coordinator_summaries: Optional[List[Any]] = None,
    merged_results: Optional[List[Any]] = None,
    governance_snapshot: Optional[Any] = None,
    policy_alignment: Optional[Any] = None,
    runtime_recovery: Optional[Any] = None,
    runtime_session_snapshot: Optional[Any] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MultiDeviceRuntimeProjection:
    """Build a :class:`MultiDeviceRuntimeProjection` from the current contract inputs.

    This is the **canonical projection builder**.  Downstream consumers should
    call this function instead of assembling cross-runtime state by piecing together
    multiple unrelated route payloads.

    All parameters are optional.  Missing or ``None`` values produce empty
    lists / ``None`` sub-projections.  The function never raises — any per-item
    error is silently skipped.

    Parameters
    ----------
    runtime_devices:
        List of :class:`~contracts.registered_runtime_device.RegisteredRuntimeDevice`
        objects or dicts (PR-29).
    runtime_hosts:
        List of :class:`~contracts.local_runtime_host.LocalRuntimeHost`
        objects or dicts (PR-30).
    mesh_memberships:
        List of :class:`~contracts.mesh_membership.MeshMembership` objects or
        dicts (PR-32).  Stored as raw compact dicts.
    mesh_sessions:
        List of :class:`~contracts.mesh_session.MeshSession` objects or dicts
        (PR-33).
    source_dispatches:
        List of :class:`~contracts.source_dispatch.SourceDispatchSummary` or
        :class:`~contracts.source_dispatch.SourceDispatchResult` objects or
        dicts (PR-35).
    handoff_summaries:
        List of :class:`~contracts.handoff_envelope_v2.HandoffEnvelopeV2` objects
        or dicts (PR-31).
    takeover_summaries:
        List of :class:`~contracts.local_takeover_result.LocalTakeoverResult`
        objects or dicts (PR-34).
    coordinator_summaries:
        List of :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorSummary`
        or :class:`~contracts.mesh_session_coordinator.MeshSessionCoordinatorState`
        objects or dicts (PR-37).
    merged_results:
        List of :class:`~contracts.cross_runtime_result_merge.ResultMergeSummary`
        or :class:`~contracts.cross_runtime_result_merge.MergedRuntimeResult`
        objects or dicts (PR-36).
    governance_snapshot:
        Optional governance snapshot (PR-27) — object or dict.
    policy_alignment:
        Optional policy alignment surface (PR-28) — object or dict.
    metadata:
        Arbitrary key-value metadata.

    Returns
    -------
    MultiDeviceRuntimeProjection
        A fully serialisable, read-only projection of the multi-device runtime
        state.  Never raises.
    """
    # normalise mesh_memberships: convert each item to a compact dict
    normalised_memberships: List[Dict[str, Any]] = []
    for item in _safe_list(mesh_memberships):
        try:
            normalised_memberships.append(_safe_dict(item))
        except Exception:
            pass

    gov_dict: Optional[Dict[str, Any]] = None
    if governance_snapshot is not None:
        try:
            gov_dict = _safe_dict(governance_snapshot) or None
        except Exception:
            pass

    pol_dict: Optional[Dict[str, Any]] = None
    if policy_alignment is not None:
        try:
            pol_dict = _safe_dict(policy_alignment) or None
        except Exception:
            pass

    recovery_dict: Optional[Dict[str, Any]] = None
    if runtime_recovery is not None:
        try:
            recovery_dict = _safe_dict(runtime_recovery) or None
        except Exception:
            pass

    snapshot_dict: Optional[Dict[str, Any]] = None
    if runtime_session_snapshot is not None:
        try:
            snapshot_dict = _safe_dict(runtime_session_snapshot) or None
        except Exception:
            pass

    return MultiDeviceRuntimeProjection(
        runtime_devices=project_runtime_devices(runtime_devices),
        runtime_hosts=project_runtime_hosts(runtime_hosts),
        mesh_memberships=normalised_memberships,
        mesh_sessions=project_mesh_sessions(mesh_sessions),
        source_dispatches=project_source_dispatches(source_dispatches),
        handoff_summaries=project_handoffs(handoff_summaries),
        takeover_summaries=project_takeovers(takeover_summaries),
        coordinator_summaries=project_coordinator_state(coordinator_summaries),
        merged_results=project_merged_results(merged_results),
        governance_snapshot=gov_dict,
        policy_alignment=pol_dict,
        runtime_recovery=recovery_dict,
        runtime_session_snapshot=snapshot_dict,
        metadata=metadata or {},
    )
