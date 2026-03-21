"""contracts/mesh_membership.py
====================================
Mesh Membership Contract — PR-32.

This module defines the **canonical Mesh Membership contract**: a single,
serialisable schema that answers the question:

    *"How does a runtime-capable device belong to a mesh/body, and what is
    its formal role, authority, and routing intent within that mesh?"*

It is the mesh-participation counterpart to the earlier contract chain:

- **PR-29** — what a registered runtime-capable device *is*
- **PR-30** — what a local runtime host must *expose*
- **PR-31** — what a cross-device handoff *carries*
- **PR-32** (this module) — how a device *participates* in a mesh/body

This contract formalises mesh membership including:
- the device's role(s) within the mesh (source, primary, support, …);
- the device's authority scope within the mesh;
- the routing intent (local-preferred, remote-required, …);
- participation hints (online status, health score, multi-device requirements);
- all related device lists (fallback, support, observer, relay).

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Fully serialisable** — :meth:`MeshMembership.to_dict` and
  :meth:`MeshMembership.to_json` produce stable, round-trippable JSON.
- **Graceful defaults** — all fields beyond ``mesh_id`` and
  ``member_device_id`` are optional; adapters catch exceptions and degrade
  gracefully.
- **No UI-specific semantics** — suitable for runtime/projection/handoff/API
  use.
- **Stable field names** — downstream consumers can rely on the field names
  defined here without fear of silent renaming.
- **Tolerant of partial inputs** — adapters accept ``None`` and missing
  attributes without raising.

Usage::

    from contracts.mesh_membership import (
        MeshMembership,
        MeshMemberRole,
        MeshAuthorityScope,
        MeshRoutingIntent,
        MeshParticipationHints,
        from_body_mesh_entry,
        from_device_formation_summary,
        from_cross_device_routing_summary,
        build_mesh_membership,
    )

    # Build from a BodyEntry (core.mesh.body_mesh_registry)
    from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole
    registry = BodyMeshRegistry()
    registry.register("phone_001", roles=[DeviceRole.PERCEPTION, DeviceRole.ACTION])
    entry = registry.get("phone_001")
    membership = from_body_mesh_entry(entry, mesh_id="mesh_alpha")
    payload = membership.to_dict()

    # Build from a FormationSummary (core.device_formation)
    from core.device_formation import resolve_formation_summary
    summary = resolve_formation_summary()
    memberships = from_device_formation_summary(summary)

    # Build from a CrossDeviceAssignmentSummary (core.cross_device_policy)
    from core.cross_device_policy import build_assignment_summary
    routing = build_assignment_summary(policy)
    memberships = from_cross_device_routing_summary(routing)

    # Build from scratch
    membership = build_mesh_membership(
        mesh_id="mesh_beta",
        member_device_id="tablet_002",
        roles=[MeshMemberRole.PRIMARY],
        authority_scope=MeshAuthorityScope.MESH_AUTHORITY,
        routing_intent=MeshRoutingIntent.LOCAL_PREFERRED,
    )

See ``docs/MESH_MEMBERSHIP_CONTRACT.md`` for the full specification.
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


class MeshMemberRole(str, Enum):
    """Formal role a device plays as a mesh/body member.

    These roles are stable contract values.  A device may carry multiple roles
    simultaneously (e.g. both PRIMARY and MERGE_OWNER).

    Values intentionally align with FormationRole (PR-17) and
    DeviceRole assignment semantics (PR-13), but are defined independently
    here so this contract has no hard dependency on either package.
    """

    SOURCE = "source"
    """Device that originated the current request or task."""

    PRIMARY = "primary"
    """Primary execution device — anchors the current cognitive session."""

    SUPPORT = "support"
    """Support / co-execution device — assists the primary executor."""

    FALLBACK = "fallback"
    """Fallback device — promoted to primary if the primary fails."""

    OBSERVER = "observer"
    """Observer device — receives execution events but does not act."""

    RELAY = "relay"
    """Relay device — forwards tasks/results between other members."""

    MERGE_OWNER = "merge_owner"
    """Device responsible for merging distributed results."""

    UNASSIGNED = "unassigned"
    """Device is registered in the mesh but has not been assigned a role."""


class MeshAuthorityScope(str, Enum):
    """Authority a device holds within the mesh.

    Describes what decisions the device is authorised to make unilaterally
    within the membership context.
    """

    MESH_AUTHORITY = "mesh_authority"
    """Full authority — may initiate, coordinate, and commit mesh actions."""

    EXECUTION_AUTHORITY = "execution_authority"
    """May execute tasks assigned to it; may not coordinate other members."""

    OBSERVE_ONLY = "observe_only"
    """Read-only participation — no execution or coordination authority."""

    RELAY_ONLY = "relay_only"
    """May only relay tasks/results; no direct execution authority."""

    NONE = "none"
    """No authority — device is registered but not yet authorised."""


class MeshRoutingIntent(str, Enum):
    """Intended routing posture for this member's task dispatch.

    Aligns with ``RoutingPosture`` (PR-13) semantics but is expressed
    independently here for contract stability.
    """

    LOCAL_PREFERRED = "local_preferred"
    """Prefer executing tasks locally; cross-device only as needed."""

    LOCAL_THEN_EXPAND = "local_then_expand"
    """Start locally; expand cross-device when local capacity is exceeded."""

    REMOTE_REQUIRED = "remote_required"
    """Tasks must be dispatched to a remote/other device."""

    SPLIT_EXECUTION = "split_execution"
    """Task is split and executed across multiple devices in parallel."""

    MIRRORED_OBSERVATION = "mirrored_observation"
    """Device mirrors execution of another member for observability."""

    UNDECIDED = "undecided"
    """Routing intent has not yet been determined."""


# ---------------------------------------------------------------------------
# Sub-contract: participation hints
# ---------------------------------------------------------------------------


class MeshParticipationHints(BaseModel):
    """Compact, scalar hints about this member's participation posture.

    These hints are derived fields intended for quick downstream checks
    without requiring callers to inspect the full :class:`MeshMembership`
    object.  They are always consistent with the parent contract's fields.
    """

    is_primary: bool = Field(
        default=False,
        description="True if this member carries the PRIMARY role.",
    )
    is_source: bool = Field(
        default=False,
        description="True if this member is the originating source device.",
    )
    is_fallback: bool = Field(
        default=False,
        description="True if this member carries the FALLBACK role.",
    )
    is_relay: bool = Field(
        default=False,
        description="True if this member carries the RELAY role.",
    )
    is_observer: bool = Field(
        default=False,
        description="True if this member carries the OBSERVER role.",
    )
    has_execution_authority: bool = Field(
        default=False,
        description=(
            "True if the authority scope is MESH_AUTHORITY or "
            "EXECUTION_AUTHORITY."
        ),
    )
    multi_device_required: bool = Field(
        default=False,
        description=(
            "True if the mesh policy requires at least two devices for "
            "valid participation."
        ),
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description=(
            "True if result merge requires explicit confirmation before "
            "commit."
        ),
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


# ---------------------------------------------------------------------------
# Top-level contract
# ---------------------------------------------------------------------------


class MeshMembership(BaseModel):
    """Canonical Mesh Membership contract.

    Represents one device's formal participation record in a mesh/body.  Each
    device that participates in a mesh has exactly one :class:`MeshMembership`
    record per mesh.

    All fields beyond ``mesh_id`` and ``member_device_id`` are optional so
    that adapters from partial data sources can produce a valid contract.

    Fields
    ------
    membership_id:
        Stable unique identifier for this membership record.
        Auto-generated as a UUID-hex if not supplied.
    mesh_id:
        Stable identifier for the mesh/body this device belongs to.
    member_device_id:
        Stable identifier of the physical device that is the member.
    member_runtime_id:
        Optional identifier of the active runtime instance on the member
        device (e.g. a session or runtime UUID).
    roles:
        Ordered list of :class:`MeshMemberRole` values assigned to this
        member.  A device may carry multiple roles.
    authority_scope:
        The :class:`MeshAuthorityScope` this member holds within the mesh.
    routing_intent:
        The :class:`MeshRoutingIntent` for task dispatch to/from this member.
    source_device_id:
        Device that originated the current task/request associated with this
        mesh context.  May be the same as ``member_device_id``.
    primary_device_id:
        Device that is the primary executor in this mesh context.  May be the
        same as ``member_device_id``.
    fallback_device_ids:
        Ordered list of device IDs that serve as fallback for the primary.
    support_device_ids:
        List of device IDs providing support/co-execution.
    observer_device_ids:
        List of device IDs in observer (read-only) participation.
    relay_device_ids:
        List of device IDs acting as relay nodes.
    merge_owner_device_id:
        Device responsible for merging distributed results.
    barrier_posture:
        String value of the barrier/completion posture (e.g. ``"wait_all"``,
        ``"wait_primary"``, ``"best_effort"``, ``"wait_merge_owner"``).
    multi_device_required:
        Whether the mesh policy requires at least two devices.
    merge_confirmation_required:
        Whether result merge requires explicit confirmation before commit.
    member_online:
        Whether the member device is currently considered online.
    member_health_score:
        Health score of the member device (0.0–1.0).
    hints:
        Compact :class:`MeshParticipationHints` for quick downstream checks.
    metadata:
        Arbitrary extra fields (e.g. display names, tags).
    created_at:
        Unix timestamp when this membership record was created.
    """

    membership_id: str = Field(
        default_factory=lambda: uuid.uuid4().hex,
        description="Stable unique identifier for this membership record.",
    )
    mesh_id: str = Field(
        description="Stable identifier for the mesh/body this device belongs to.",
    )
    member_device_id: str = Field(
        description="Stable identifier of the physical device that is the member.",
    )
    member_runtime_id: Optional[str] = Field(
        default=None,
        description="Optional runtime instance identifier on the member device.",
    )
    roles: List[MeshMemberRole] = Field(
        default_factory=list,
        description="Roles this member carries in the mesh.",
    )
    authority_scope: MeshAuthorityScope = Field(
        default=MeshAuthorityScope.NONE,
        description="Authority this member holds within the mesh.",
    )
    routing_intent: MeshRoutingIntent = Field(
        default=MeshRoutingIntent.UNDECIDED,
        description="Intended routing posture for task dispatch.",
    )
    source_device_id: Optional[str] = Field(
        default=None,
        description="Device that originated the current task/request.",
    )
    primary_device_id: Optional[str] = Field(
        default=None,
        description="Primary executor device in this mesh context.",
    )
    fallback_device_ids: List[str] = Field(
        default_factory=list,
        description="Ordered list of fallback device IDs.",
    )
    support_device_ids: List[str] = Field(
        default_factory=list,
        description="Support/co-execution device IDs.",
    )
    observer_device_ids: List[str] = Field(
        default_factory=list,
        description="Observer device IDs.",
    )
    relay_device_ids: List[str] = Field(
        default_factory=list,
        description="Relay node device IDs.",
    )
    merge_owner_device_id: Optional[str] = Field(
        default=None,
        description="Device responsible for merging distributed results.",
    )
    barrier_posture: Optional[str] = Field(
        default=None,
        description=(
            "Barrier/completion posture string "
            "(e.g. 'wait_all', 'wait_primary', 'best_effort', "
            "'wait_merge_owner')."
        ),
    )
    multi_device_required: bool = Field(
        default=False,
        description="Whether the mesh policy requires at least two devices.",
    )
    merge_confirmation_required: bool = Field(
        default=False,
        description="Whether result merge requires explicit confirmation.",
    )
    member_online: Optional[bool] = Field(
        default=None,
        description="Whether the member device is currently online.",
    )
    member_health_score: Optional[float] = Field(
        default=None,
        description="Health score of the member device (0.0–1.0).",
    )
    hints: MeshParticipationHints = Field(
        default_factory=MeshParticipationHints,
        description="Compact participation hints for quick downstream checks.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary extra fields.",
    )
    created_at: float = Field(
        default_factory=time.time,
        description="Unix timestamp when this membership record was created.",
    )

    model_config = {"use_enum_values": True}

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return self.model_dump()

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return self.model_dump_json()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeshMembership":
        """Construct from a plain dict (reverse of :meth:`to_dict`)."""
        return cls.model_validate(data)

    def to_compact_summary(self) -> Dict[str, Any]:
        """Return a compact projection-safe summary dict."""
        return {
            "membership_id": self.membership_id,
            "mesh_id": self.mesh_id,
            "member_device_id": self.member_device_id,
            "roles": list(self.roles),
            "authority_scope": self.authority_scope,
            "routing_intent": self.routing_intent,
            "primary_device_id": self.primary_device_id,
            "source_device_id": self.source_device_id,
            "multi_device_required": self.multi_device_required,
            "member_online": self.member_online,
            "member_health_score": self.member_health_score,
            "hints": self.hints.to_dict(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _derive_hints(
    roles: List[str],
    authority_scope: str,
    multi_device_required: bool,
    merge_confirmation_required: bool,
) -> MeshParticipationHints:
    """Derive :class:`MeshParticipationHints` from membership fields."""
    role_set = set(roles)
    has_exec_auth = authority_scope in (
        MeshAuthorityScope.MESH_AUTHORITY.value,
        MeshAuthorityScope.EXECUTION_AUTHORITY.value,
    )
    return MeshParticipationHints(
        is_primary=MeshMemberRole.PRIMARY.value in role_set,
        is_source=MeshMemberRole.SOURCE.value in role_set,
        is_fallback=MeshMemberRole.FALLBACK.value in role_set,
        is_relay=MeshMemberRole.RELAY.value in role_set,
        is_observer=MeshMemberRole.OBSERVER.value in role_set,
        has_execution_authority=has_exec_auth,
        multi_device_required=multi_device_required,
        merge_confirmation_required=merge_confirmation_required,
    )


def _body_roles_to_mesh_roles(body_roles: Any) -> List[MeshMemberRole]:
    """Map BodyMeshRegistry DeviceRole values to MeshMemberRole values.

    DeviceRole (PERCEPTION / ACTION / PRESENCE) describes *capability* roles;
    they are mapped to the SUPPORT mesh role by default, since the Body mesh
    does not carry explicit primary/source semantics without assignment data.
    """
    if not body_roles:
        return [MeshMemberRole.UNASSIGNED]
    return [MeshMemberRole.SUPPORT]


def _body_authority_from_score(body_score: float) -> MeshAuthorityScope:
    """Derive a conservative authority scope from a body_score."""
    if body_score > 0.0:
        return MeshAuthorityScope.EXECUTION_AUTHORITY
    return MeshAuthorityScope.NONE


# ---------------------------------------------------------------------------
# Adapter: from BodyEntry (core.mesh.body_mesh_registry)
# ---------------------------------------------------------------------------


def from_body_mesh_entry(
    entry: Any,
    mesh_id: str = "default_mesh",
    primary_device_id: Optional[str] = None,
) -> MeshMembership:
    """Build a :class:`MeshMembership` from a
    :class:`~core.mesh.body_mesh_registry.BodyEntry`.

    Parameters
    ----------
    entry:
        A ``core.mesh.body_mesh_registry.BodyEntry`` instance (or any object
        with ``device_id``, ``roles``, ``session_id``, ``body_score``,
        ``metadata`` attributes).
    mesh_id:
        Identifier for the mesh this entry belongs to.  Defaults to
        ``"default_mesh"``; callers should supply the actual mesh/session ID.
    primary_device_id:
        Optional explicit primary device ID.  If not given, the member is
        not assumed to be primary unless its score logic suggests so.

    Returns
    -------
    MeshMembership
        Populated contract.  Fields that cannot be mapped are left at
        their defaults.
    """
    try:
        device_id = str(getattr(entry, "device_id", "") or "")
        if not device_id:
            device_id = f"dev_{uuid.uuid4().hex[:8]}"

        body_roles = getattr(entry, "roles", None)
        body_score = float(getattr(entry, "body_score", 0.0) or 0.0)
        session_id = getattr(entry, "session_id", None)
        metadata = dict(getattr(entry, "metadata", {}) or {})

        mesh_roles = _body_roles_to_mesh_roles(body_roles)
        authority = _body_authority_from_score(body_score)

        # Preserve original body mesh roles in metadata for traceability
        if body_roles:
            try:
                metadata.setdefault(
                    "body_mesh_roles",
                    sorted(r.value if hasattr(r, "value") else str(r) for r in body_roles),
                )
            except Exception:
                pass

        effective_mesh_id = session_id or mesh_id

        hints = _derive_hints(
            roles=[r.value for r in mesh_roles],
            authority_scope=authority.value,
            multi_device_required=False,
            merge_confirmation_required=False,
        )

        return MeshMembership(
            mesh_id=effective_mesh_id,
            member_device_id=device_id,
            roles=mesh_roles,
            authority_scope=authority,
            routing_intent=MeshRoutingIntent.UNDECIDED,
            primary_device_id=primary_device_id,
            member_health_score=body_score if body_score > 0.0 else None,
            hints=hints,
            metadata=metadata,
        )
    except Exception:
        device_id = str(getattr(entry, "device_id", f"dev_{uuid.uuid4().hex[:8]}"))
        return MeshMembership(
            mesh_id=mesh_id,
            member_device_id=device_id,
        )


# ---------------------------------------------------------------------------
# Adapter: from FormationSummary (core.device_formation)
# ---------------------------------------------------------------------------


def from_device_formation_summary(
    summary: Any,
    mesh_id: Optional[str] = None,
) -> List[MeshMembership]:
    """Build a list of :class:`MeshMembership` objects from a
    :class:`~core.device_formation.FormationSummary`.

    One :class:`MeshMembership` is created for every distinct device ID
    present in the summary (source, primary, support, observer, relay,
    fallback, merge_owner).

    Parameters
    ----------
    summary:
        A ``core.device_formation.FormationSummary`` instance (or any object
        with matching attributes).
    mesh_id:
        Optional mesh identifier to use.  Defaults to
        ``summary.formation_id`` when available.

    Returns
    -------
    list of MeshMembership
        One record per unique device.  Empty list if ``summary`` is ``None``
        or carries no device information.
    """
    if summary is None:
        return []

    try:
        formation_id = str(getattr(summary, "formation_id", "") or "")
        effective_mesh_id = mesh_id or formation_id or f"mesh_{uuid.uuid4().hex[:8]}"

        source_id = getattr(summary, "source_device_id", None)
        primary_id = getattr(summary, "primary_execution_device_id", None)
        merge_owner_id = getattr(summary, "merge_owner_device_id", None)
        barrier = getattr(summary, "barrier_posture", None)
        multi_req = bool(getattr(summary, "multi_device_required", False))
        merge_req = bool(getattr(summary, "merge_confirmation_required", False))

        fallback_ids: List[str] = list(getattr(summary, "fallback_device_ids", []) or [])
        support_ids: List[str] = list(getattr(summary, "support_device_ids", []) or [])
        observer_ids: List[str] = list(getattr(summary, "observer_device_ids", []) or [])
        relay_ids: List[str] = list(getattr(summary, "relay_device_ids", []) or [])

        # Collect all unique device IDs present
        all_ids: Dict[str, List[MeshMemberRole]] = {}

        def _add(did: Optional[str], role: MeshMemberRole) -> None:
            if did:
                all_ids.setdefault(did, [])
                if role not in all_ids[did]:
                    all_ids[did].append(role)

        _add(source_id, MeshMemberRole.SOURCE)
        _add(primary_id, MeshMemberRole.PRIMARY)
        _add(merge_owner_id, MeshMemberRole.MERGE_OWNER)
        for did in fallback_ids:
            _add(did, MeshMemberRole.FALLBACK)
        for did in support_ids:
            _add(did, MeshMemberRole.SUPPORT)
        for did in observer_ids:
            _add(did, MeshMemberRole.OBSERVER)
        for did in relay_ids:
            _add(did, MeshMemberRole.RELAY)

        if not all_ids:
            return []

        memberships: List[MeshMembership] = []
        for device_id, roles in all_ids.items():
            authority = (
                MeshAuthorityScope.MESH_AUTHORITY
                if device_id == primary_id
                else MeshAuthorityScope.EXECUTION_AUTHORITY
                if MeshMemberRole.SOURCE in roles
                else MeshAuthorityScope.OBSERVE_ONLY
                if set(roles) == {MeshMemberRole.OBSERVER}
                else MeshAuthorityScope.RELAY_ONLY
                if set(roles) == {MeshMemberRole.RELAY}
                else MeshAuthorityScope.EXECUTION_AUTHORITY
            )

            hints = _derive_hints(
                roles=[r.value for r in roles],
                authority_scope=authority.value,
                multi_device_required=multi_req,
                merge_confirmation_required=merge_req,
            )

            memberships.append(
                MeshMembership(
                    mesh_id=effective_mesh_id,
                    member_device_id=device_id,
                    roles=roles,
                    authority_scope=authority,
                    routing_intent=MeshRoutingIntent.UNDECIDED,
                    source_device_id=source_id,
                    primary_device_id=primary_id,
                    fallback_device_ids=fallback_ids,
                    support_device_ids=support_ids,
                    observer_device_ids=observer_ids,
                    relay_device_ids=relay_ids,
                    merge_owner_device_id=merge_owner_id,
                    barrier_posture=barrier,
                    multi_device_required=multi_req,
                    merge_confirmation_required=merge_req,
                    hints=hints,
                )
            )

        return memberships

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Adapter: from CrossDeviceAssignmentSummary (core.cross_device_policy)
# ---------------------------------------------------------------------------


def from_cross_device_routing_summary(
    summary: Any,
    mesh_id: Optional[str] = None,
) -> List[MeshMembership]:
    """Build a list of :class:`MeshMembership` objects from a
    :class:`~core.cross_device_policy.CrossDeviceAssignmentSummary`.

    One :class:`MeshMembership` is created for every distinct device ID
    present in the routing summary.

    Parameters
    ----------
    summary:
        A ``core.cross_device_policy.CrossDeviceAssignmentSummary`` instance
        (or any object with matching attributes).
    mesh_id:
        Optional mesh identifier.  Defaults to the summary's ``trace_id``
        when available.

    Returns
    -------
    list of MeshMembership
        One record per unique device.  Empty list if ``summary`` is ``None``
        or carries no device information.
    """
    if summary is None:
        return []

    try:
        trace_id = str(getattr(summary, "trace_id", "") or "")
        effective_mesh_id = mesh_id or trace_id or f"mesh_{uuid.uuid4().hex[:8]}"

        source_id = getattr(summary, "source_device_id", None)
        primary_id = getattr(summary, "primary_execution_device_id", None)
        posture = str(getattr(summary, "posture", "undecided") or "undecided")

        fallback_ids: List[str] = list(getattr(summary, "fallback_device_ids", []) or [])
        support_ids: List[str] = list(getattr(summary, "support_device_ids", []) or [])
        observer_ids: List[str] = list(getattr(summary, "observer_device_ids", []) or [])
        relay_ids: List[str] = list(getattr(summary, "relay_device_ids", []) or [])

        # Map routing posture string to MeshRoutingIntent
        _posture_map: Dict[str, MeshRoutingIntent] = {
            "local_preferred": MeshRoutingIntent.LOCAL_PREFERRED,
            "local_then_expand": MeshRoutingIntent.LOCAL_THEN_EXPAND,
            "remote_required": MeshRoutingIntent.REMOTE_REQUIRED,
            "split_execution": MeshRoutingIntent.SPLIT_EXECUTION,
            "mirrored_observation": MeshRoutingIntent.MIRRORED_OBSERVATION,
        }
        routing_intent = _posture_map.get(posture, MeshRoutingIntent.UNDECIDED)

        all_ids: Dict[str, List[MeshMemberRole]] = {}

        def _add(did: Optional[str], role: MeshMemberRole) -> None:
            if did:
                all_ids.setdefault(did, [])
                if role not in all_ids[did]:
                    all_ids[did].append(role)

        _add(source_id, MeshMemberRole.SOURCE)
        _add(primary_id, MeshMemberRole.PRIMARY)
        for did in fallback_ids:
            _add(did, MeshMemberRole.FALLBACK)
        for did in support_ids:
            _add(did, MeshMemberRole.SUPPORT)
        for did in observer_ids:
            _add(did, MeshMemberRole.OBSERVER)
        for did in relay_ids:
            _add(did, MeshMemberRole.RELAY)

        if not all_ids:
            return []

        memberships: List[MeshMembership] = []
        for device_id, roles in all_ids.items():
            authority = (
                MeshAuthorityScope.MESH_AUTHORITY
                if device_id == primary_id
                else MeshAuthorityScope.OBSERVE_ONLY
                if set(roles) == {MeshMemberRole.OBSERVER}
                else MeshAuthorityScope.RELAY_ONLY
                if set(roles) == {MeshMemberRole.RELAY}
                else MeshAuthorityScope.EXECUTION_AUTHORITY
            )

            hints = _derive_hints(
                roles=[r.value for r in roles],
                authority_scope=authority.value,
                multi_device_required=False,
                merge_confirmation_required=False,
            )

            memberships.append(
                MeshMembership(
                    mesh_id=effective_mesh_id,
                    member_device_id=device_id,
                    roles=roles,
                    authority_scope=authority,
                    routing_intent=routing_intent,
                    source_device_id=source_id,
                    primary_device_id=primary_id,
                    fallback_device_ids=fallback_ids,
                    support_device_ids=support_ids,
                    observer_device_ids=observer_ids,
                    relay_device_ids=relay_ids,
                    hints=hints,
                )
            )

        return memberships

    except Exception:
        return []


# ---------------------------------------------------------------------------
# Builder: generic convenience factory
# ---------------------------------------------------------------------------


def build_mesh_membership(
    mesh_id: str,
    member_device_id: str,
    membership_id: Optional[str] = None,
    member_runtime_id: Optional[str] = None,
    roles: Optional[List[MeshMemberRole]] = None,
    authority_scope: MeshAuthorityScope = MeshAuthorityScope.NONE,
    routing_intent: MeshRoutingIntent = MeshRoutingIntent.UNDECIDED,
    source_device_id: Optional[str] = None,
    primary_device_id: Optional[str] = None,
    fallback_device_ids: Optional[List[str]] = None,
    support_device_ids: Optional[List[str]] = None,
    observer_device_ids: Optional[List[str]] = None,
    relay_device_ids: Optional[List[str]] = None,
    merge_owner_device_id: Optional[str] = None,
    barrier_posture: Optional[str] = None,
    multi_device_required: bool = False,
    merge_confirmation_required: bool = False,
    member_online: Optional[bool] = None,
    member_health_score: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> MeshMembership:
    """Convenience factory for :class:`MeshMembership`.

    All parameters correspond directly to :class:`MeshMembership` fields.
    Only ``mesh_id`` and ``member_device_id`` are required; everything else
    is optional.

    Parameters
    ----------
    mesh_id:
        Stable identifier for the mesh/body this device belongs to.
    member_device_id:
        Stable identifier of the physical device that is the member.
    membership_id:
        Optional stable unique identifier.  Auto-generated if omitted.
    member_runtime_id:
        Optional runtime instance identifier on the member device.
    roles:
        List of :class:`MeshMemberRole` values.  Defaults to empty list.
    authority_scope:
        :class:`MeshAuthorityScope` for this member.
    routing_intent:
        :class:`MeshRoutingIntent` for task dispatch.
    source_device_id:
        Device that originated the current task/request.
    primary_device_id:
        Primary executor device in this mesh context.
    fallback_device_ids:
        Ordered list of fallback device IDs.
    support_device_ids:
        Support/co-execution device IDs.
    observer_device_ids:
        Observer device IDs.
    relay_device_ids:
        Relay node device IDs.
    merge_owner_device_id:
        Device responsible for merging distributed results.
    barrier_posture:
        Barrier/completion posture string.
    multi_device_required:
        Whether the mesh policy requires at least two devices.
    merge_confirmation_required:
        Whether result merge requires explicit confirmation.
    member_online:
        Whether the member device is currently online.
    member_health_score:
        Health score of the member device (0.0–1.0).
    metadata:
        Arbitrary extra fields.

    Returns
    -------
    MeshMembership
        Fully constructed membership contract.
    """
    effective_roles: List[MeshMemberRole] = roles or []
    effective_fallback = fallback_device_ids or []
    effective_support = support_device_ids or []
    effective_observer = observer_device_ids or []
    effective_relay = relay_device_ids or []
    effective_metadata = metadata or {}

    hints = _derive_hints(
        roles=[r.value if hasattr(r, "value") else str(r) for r in effective_roles],
        authority_scope=authority_scope.value if hasattr(authority_scope, "value") else str(authority_scope),
        multi_device_required=multi_device_required,
        merge_confirmation_required=merge_confirmation_required,
    )

    kwargs: Dict[str, Any] = dict(
        mesh_id=mesh_id,
        member_device_id=member_device_id,
        member_runtime_id=member_runtime_id,
        roles=effective_roles,
        authority_scope=authority_scope,
        routing_intent=routing_intent,
        source_device_id=source_device_id,
        primary_device_id=primary_device_id,
        fallback_device_ids=effective_fallback,
        support_device_ids=effective_support,
        observer_device_ids=effective_observer,
        relay_device_ids=effective_relay,
        merge_owner_device_id=merge_owner_device_id,
        barrier_posture=barrier_posture,
        multi_device_required=multi_device_required,
        merge_confirmation_required=merge_confirmation_required,
        member_online=member_online,
        member_health_score=member_health_score,
        hints=hints,
        metadata=effective_metadata,
    )
    if membership_id is not None:
        kwargs["membership_id"] = membership_id

    return MeshMembership(**kwargs)


# ---------------------------------------------------------------------------
# Public __all__
# ---------------------------------------------------------------------------

__all__ = [
    # Enumerations
    "MeshMemberRole",
    "MeshAuthorityScope",
    "MeshRoutingIntent",
    # Sub-contracts
    "MeshParticipationHints",
    # Top-level contract
    "MeshMembership",
    # Adapters / builders
    "from_body_mesh_entry",
    "from_device_formation_summary",
    "from_cross_device_routing_summary",
    "build_mesh_membership",
]
