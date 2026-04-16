"""core/canonical_session_axis.py
=====================================
PR-3 (Canonical session axis — main repository side).

This module is the **canonical authority** for the cross-layer, cross-repository
session axis model.  It explicitly defines:

1. The five session families and their role boundaries.
2. Which identifiers are canonical for each family.
3. Which identifiers are aliases or transitional mirrors.
4. How Android-side session structures map to center-side session structures.
5. How session continuity should be reasoned about across control, runtime,
   attached, and transfer layers.

Background
----------
The system already contains meaningful session-related structures across
multiple modules and layers:

* ``core.session_manager`` — conversation/history continuity (``Session``)
* ``core.attached_runtime_session`` — persistent attached-runtime lifecycle
* ``core.attached_runtime_session_registry`` — runtime attachment session
  registry with stable ``runtime_session_id``
* ``core.canonical_session_truth`` — posture-aware result-merge truth record
* ``core.ugcp_control_transfer_profile`` — control-transfer lifecycle with
  ``control_session_id`` / ``runtime_session_id`` anchors
* ``core.ugcp_coordination_profile`` — mesh/coordination lifecycle with
  ``control_session_id`` / ``runtime_session_id`` / ``mesh_session_id``
* ``contracts.mesh_session`` — mesh-specific membership and assignment state
* ``contracts.runtime_session_snapshot`` — durable point-in-time snapshot
  spanning all session families

However, the cross-layer and cross-repository relationship between these
structures is expressed implicitly through aliases, mapping helpers, and
documentation-local conventions.  This module makes that relationship
explicit and inspectable without altering runtime behaviour.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Inspectable** — every relationship is expressed as a named record or
  constant, not just a comment.
- **Behaviour-preserving** — existing reconnect, recovery, and transfer
  semantics are documented here but remain governed by their existing
  authority modules.
- **Android-explicit** — Android-side session identifiers are explicitly
  mapped to their center-side counterparts.
- **Policy-sentinel anchored** — every policy documented here is referenced
  by a named string sentinel for audit and observability.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CANONICAL_SESSION_AXIS_AUTHORITY`
:data:`CANONICAL_SESSION_AXIS_PR3_SENTINEL`
:data:`SESSION_FAMILIES_ARE_DISJOINT_POLICY`
:data:`BARE_SESSION_IS_NOT_CANONICAL_POLICY`
:data:`CENTER_IS_SESSION_RESOLUTION_AUTHORITY_POLICY`
:data:`RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY`
:data:`TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY`
:data:`MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY`
:data:`ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY`
:data:`ALIAS_RESOLUTION_ORDER_IS_CANONICAL_POLICY`

Enums
~~~~~
:class:`SessionFamily`
:class:`SessionIdentifierRole`
:class:`SessionContinuityClass`

Data classes
~~~~~~~~~~~~
:class:`SessionFamilyRecord`
:class:`SessionIdentifierRecord`
:class:`AndroidSessionMapping`
:class:`SessionAxisSnapshot`

Functions
~~~~~~~~~
:func:`get_session_family_catalogue`
:func:`get_session_identifier_catalogue`
:func:`get_android_session_mapping_catalogue`
:func:`classify_identifier_role`
:func:`resolve_session_family_for_identifier`
:func:`build_session_axis_snapshot`
"""

from __future__ import annotations

import dataclasses
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    # Authority / policy sentinels
    "CANONICAL_SESSION_AXIS_AUTHORITY",
    "CANONICAL_SESSION_AXIS_PR3_SENTINEL",
    "SESSION_FAMILIES_ARE_DISJOINT_POLICY",
    "BARE_SESSION_IS_NOT_CANONICAL_POLICY",
    "CENTER_IS_SESSION_RESOLUTION_AUTHORITY_POLICY",
    "RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY",
    "TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY",
    "MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY",
    "ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY",
    "ALIAS_RESOLUTION_ORDER_IS_CANONICAL_POLICY",
    # Enums
    "SessionFamily",
    "SessionIdentifierRole",
    "SessionContinuityClass",
    # Data classes
    "SessionFamilyRecord",
    "SessionIdentifierRecord",
    "AndroidSessionMapping",
    "SessionAxisSnapshot",
    # Functions
    "get_session_family_catalogue",
    "get_session_identifier_catalogue",
    "get_android_session_mapping_catalogue",
    "classify_identifier_role",
    "resolve_session_family_for_identifier",
    "build_session_axis_snapshot",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_SESSION_AXIS_AUTHORITY: str = (
    "CANONICAL_SESSION_AXIS_AUTHORITY::core.canonical_session_axis is the "
    "canonical authority for the cross-layer, cross-repository session axis "
    "model on the main-repository side (PR-3, establish canonical session axis)."
)

CANONICAL_SESSION_AXIS_PR3_SENTINEL: str = (
    "CANONICAL_SESSION_AXIS_PR3_SENTINEL::package=PR3::"
    "profile=canonical-session-axis-v1::module=core.canonical_session_axis"
)

SESSION_FAMILIES_ARE_DISJOINT_POLICY: str = (
    "POLICY::SESSION_FAMILIES_ARE_DISJOINT: the five session families "
    "(conversation, control, runtime_attachment, delegation_transfer, mesh) "
    "are semantically disjoint and must not be conflated.  A single request "
    "or execution may span multiple families simultaneously, each carrying its "
    "own lifecycle, identifiers, and continuity semantics."
)

BARE_SESSION_IS_NOT_CANONICAL_POLICY: str = (
    "POLICY::BARE_SESSION_IS_NOT_CANONICAL: bare 'session' or 'session_id' "
    "fields are not canonical on new surfaces.  New surfaces must use one of "
    "the explicit canonical identifier names: conversation_session_id, "
    "control_session_id, runtime_attachment_session_id, "
    "delegation_transfer_session_id, or mesh_session_id.  Bare 'session_id' "
    "is a compatibility alias whose target family is resolved by context."
)

CENTER_IS_SESSION_RESOLUTION_AUTHORITY_POLICY: str = (
    "POLICY::CENTER_IS_SESSION_RESOLUTION_AUTHORITY: the center runtime is "
    "the authoritative resolver for all session identities across all families.  "
    "Android-side session identifiers are treated as claims and normalised "
    "into canonical center-side identifiers during ingress.  Android must not "
    "act as an independent session authority."
)

RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY: str = (
    "POLICY::RECONNECT_PRESERVES_RUNTIME_SESSION_ID: a reconnect signal on "
    "a disconnected or detaching runtime attachment session must preserve the "
    "stable runtime_session_id.  Only an explicit reattach creates a new "
    "runtime_session_id.  This is enforced by "
    "core.attached_runtime_session_registry.REGISTRY_RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY."
)

TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE_POLICY: str = (
    "POLICY::TRANSFER_SESSION_TERMINAL_IS_NON_RECOVERABLE: a completed, "
    "rejected, cancelled, or expired delegation transfer session is terminal "
    "and non-recoverable.  A new transfer handshake is required for any "
    "subsequent delegation.  This is governed by "
    "core.ugcp_control_transfer_profile.TRANSFER_TERMINAL_REASON_IS_CANONICAL_POLICY."
)

MESH_SESSION_IS_OPTIONAL_OVERLAY_POLICY: str = (
    "POLICY::MESH_SESSION_IS_OPTIONAL_OVERLAY: the mesh session family is an "
    "optional overlay that is only active when multi-participant staged "
    "coordination is required.  Its mesh_session_id is distinct from "
    "runtime_session_id and does not replace it.  Absence of a mesh session "
    "does not affect the other four session families."
)

ANDROID_SESSION_IDS_ARE_CLAIMS_POLICY: str = (
    "POLICY::ANDROID_SESSION_IDS_ARE_CLAIMS: session identifiers supplied by "
    "the Android participant (device_id, session_id, runtime_session_id, "
    "attached_session_id, transfer_session_id, mesh_session_id) are treated "
    "as claims at ingress.  The center-side normalisation/mapping helpers in "
    "core.schemas.ugcp.shared resolve them to canonical identifiers before "
    "they are used in truth, registry, or dispatch surfaces."
)

ALIAS_RESOLUTION_ORDER_IS_CANONICAL_POLICY: str = (
    "POLICY::ALIAS_RESOLUTION_ORDER_IS_CANONICAL: when multiple identifier "
    "fields are present in a payload, canonical fields take precedence over "
    "transitional aliases.  The resolution order for each session family is "
    "defined in the SessionIdentifierRecord catalogue and the normalisation "
    "helpers in core.schemas.ugcp.shared."
)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SessionFamily(str, Enum):
    """The five canonical session families.

    conversation
        Conversation / history continuity context.  Bound to a ``user_id``
        and shared across all devices for that user.  Governed by
        ``core.session_manager.Session``.

    control
        Control-plane continuity session.  Scoped to a single request or
        command lifecycle.  Carries a ``control_session_id`` that associates
        control ingress, dispatch, and outward truth compilation.

    runtime_attachment
        Runtime attachment continuity context.  Tracks the persistent
        attach / reconnect relationship between the center runtime and a
        cross-device participant.  Governed by
        ``core.attached_runtime_session`` and
        ``core.attached_runtime_session_registry``.

    delegation_transfer
        Delegation / handoff / transfer lifecycle context.  Tracks the
        transfer of execution ownership across participants or devices.
        Governed by ``core.ugcp_control_transfer_profile`` and
        ``core.delegated_runtime_handoff_contract``.

    mesh
        Mesh / staged coordination session.  Optional overlay that is only
        active when multi-participant staged coordination is required.
        Governed by ``contracts.mesh_session`` and
        ``contracts.mesh_session_coordinator``.
    """

    conversation = "conversation"
    control = "control"
    runtime_attachment = "runtime_attachment"
    delegation_transfer = "delegation_transfer"
    mesh = "mesh"

    @classmethod
    def from_string(
        cls,
        value: str,
        default: "Optional[SessionFamily]" = None,
    ) -> "Optional[SessionFamily]":
        """Return the enum member matching *value*, or *default*."""
        if not isinstance(value, str):
            return default
        try:
            return cls(value.lower().strip())
        except ValueError:
            return default


class SessionIdentifierRole(str, Enum):
    """The role of an identifier within its session family.

    canonical
        This is the canonical identifier name for the session family.
        New surfaces must use this name.  This is the authoritative key
        used by truth, registry, and dispatch surfaces.

    alias
        This is a transitional alias that is explicitly recognised and
        normalised to the canonical identifier at ingress.  Alias fields
        remain valid in existing contracts during convergence but must not
        be introduced in new surfaces.

    transitional_mirror
        This field mirrors the canonical identifier value for backward
        compatibility with consumers that have not yet migrated to the
        canonical name.  It must not be treated as a separate identity.

    legacy_bare
        A bare ``session_id`` or ``runtime_session_id`` field that is
        context-dependent.  Its session family is resolved by the
        normalisation helpers in ``core.schemas.ugcp.shared``.  Must not
        be introduced in new surfaces.
    """

    canonical = "canonical"
    alias = "alias"
    transitional_mirror = "transitional_mirror"
    legacy_bare = "legacy_bare"


class SessionContinuityClass(str, Enum):
    """How session continuity should be reasoned about after interruption.

    persistent
        The session persists across individual requests and across transport
        reconnections until an explicit signal terminates it.  A reconnect
        does not create a new session.

    request_scoped
        The session is scoped to a single request lifecycle.  A new request
        typically begins a new session.

    transfer_scoped
        The session is scoped to one transfer / handoff lifecycle.  It is
        terminal and non-recoverable once a terminal state is reached.

    overlay
        The session is an optional overlay that may begin and end
        independently of the other families.  Its lifecycle does not
        constrain the lifecycle of underlying sessions.
    """

    persistent = "persistent"
    request_scoped = "request_scoped"
    transfer_scoped = "transfer_scoped"
    overlay = "overlay"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SessionFamilyRecord:
    """Description of one canonical session family.

    Attributes
    ----------
    family
        The session family enum value.
    canonical_identifier
        The canonical identifier field name for this session family.
    continuity_class
        How continuity should be reasoned about after interruption.
    authority_module
        The primary Python module that governs this session family.
    recovery_allowed
        Whether the session can be recovered (reconnect / reattach)
        after a non-terminal interruption.
    terminal_requires_new_handshake
        Whether reaching a terminal state requires a new handshake
        rather than a reconnect signal.
    description
        Human-readable description of the session family.
    """

    family: SessionFamily
    canonical_identifier: str
    continuity_class: SessionContinuityClass
    authority_module: str
    recovery_allowed: bool
    terminal_requires_new_handshake: bool
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "family": self.family.value,
            "canonical_identifier": self.canonical_identifier,
            "continuity_class": self.continuity_class.value,
            "authority_module": self.authority_module,
            "recovery_allowed": self.recovery_allowed,
            "terminal_requires_new_handshake": self.terminal_requires_new_handshake,
            "description": self.description,
        }


@dataclass
class SessionIdentifierRecord:
    """Description of one session identifier field.

    Attributes
    ----------
    field_name
        The field name as it appears in payloads or data classes.
    family
        The session family this identifier belongs to.
    role
        The identifier's role (canonical, alias, transitional_mirror,
        legacy_bare).
    canonical_name
        The canonical field name this identifier resolves to.  Equal to
        ``field_name`` when ``role == canonical``.
    resolution_priority
        Lower numbers are resolved first when multiple aliased fields are
        present in a payload (1 = highest priority, i.e. canonical first).
    android_side_name
        The corresponding field name used on the Android side, or ``""``
        if this identifier is center-only.
    notes
        Additional convergence or usage notes.
    """

    field_name: str
    family: SessionFamily
    role: SessionIdentifierRole
    canonical_name: str
    resolution_priority: int
    android_side_name: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field_name": self.field_name,
            "family": self.family.value,
            "role": self.role.value,
            "canonical_name": self.canonical_name,
            "resolution_priority": self.resolution_priority,
            "android_side_name": self.android_side_name,
            "notes": self.notes,
        }


@dataclass
class AndroidSessionMapping:
    """Explicit mapping from an Android-side session field to its center-side counterpart.

    Attributes
    ----------
    android_field
        Field name used on the Android side.
    center_canonical_field
        Canonical center-side field name that the Android field maps to.
    family
        The session family this mapping belongs to.
    classification
        Mapping classification:
        - ``CANONICAL_MATCH`` — exact semantic equivalence, same name.
        - ``TRANSITIONAL_ALIAS`` — Android name differs; normalised to
          canonical at ingress.
        - ``PARTIAL_MATCH`` — semantically related but not equivalent.
        - ``UNRESOLVED_DIVERGENCE`` — not yet formally aligned.
    notes
        Convergence notes.
    """

    android_field: str
    center_canonical_field: str
    family: SessionFamily
    classification: str
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "android_field": self.android_field,
            "center_canonical_field": self.center_canonical_field,
            "family": self.family.value,
            "classification": self.classification,
            "notes": self.notes,
        }


@dataclass
class SessionAxisSnapshot:
    """Point-in-time snapshot of the canonical session axis model.

    Attributes
    ----------
    snapshot_id
        Stable unique identifier for this snapshot.
    created_at
        Unix epoch seconds when this snapshot was created.
    family_count
        Number of session families in the catalogue.
    identifier_count
        Number of identifier records in the catalogue.
    android_mapping_count
        Number of Android session mapping records.
    family_records
        Serialised session family catalogue.
    identifier_records
        Serialised session identifier catalogue.
    android_mappings
        Serialised Android session mapping catalogue.
    """

    snapshot_id: str
    created_at: float
    family_count: int
    identifier_count: int
    android_mapping_count: int
    family_records: List[Dict[str, Any]] = field(default_factory=list)
    identifier_records: List[Dict[str, Any]] = field(default_factory=list)
    android_mappings: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)


# ---------------------------------------------------------------------------
# Session family catalogue
# ---------------------------------------------------------------------------

_SESSION_FAMILY_CATALOGUE: Tuple[SessionFamilyRecord, ...] = (
    SessionFamilyRecord(
        family=SessionFamily.conversation,
        canonical_identifier="conversation_session_id",
        continuity_class=SessionContinuityClass.persistent,
        authority_module="core.session_manager",
        recovery_allowed=True,
        terminal_requires_new_handshake=False,
        description=(
            "Conversation / history continuity context.  Bound to a user_id "
            "and shared across all devices for that user.  Persists across "
            "individual requests until explicitly closed.  Governs "
            "conversation history and context for LLM/agent turns."
        ),
    ),
    SessionFamilyRecord(
        family=SessionFamily.control,
        canonical_identifier="control_session_id",
        continuity_class=SessionContinuityClass.request_scoped,
        authority_module="core.schemas.ugcp.shared",
        recovery_allowed=False,
        terminal_requires_new_handshake=False,
        description=(
            "Control-plane continuity session.  Scoped to a single request "
            "or command lifecycle.  Associates control ingress, dispatch, and "
            "outward truth compilation.  Not persistent across requests; a "
            "new control_session_id is generated for each new request."
        ),
    ),
    SessionFamilyRecord(
        family=SessionFamily.runtime_attachment,
        canonical_identifier="runtime_attachment_session_id",
        continuity_class=SessionContinuityClass.persistent,
        authority_module="core.attached_runtime_session_registry",
        recovery_allowed=True,
        terminal_requires_new_handshake=True,
        description=(
            "Runtime attachment continuity context.  Tracks the persistent "
            "attach / reconnect relationship between the center runtime and "
            "a cross-device participant.  Persists across individual requests "
            "and transport reconnections.  A disconnected session is "
            "recoverable via a reconnect signal; an invalidated or detached "
            "session requires a new attach handshake."
        ),
    ),
    SessionFamilyRecord(
        family=SessionFamily.delegation_transfer,
        canonical_identifier="delegation_transfer_session_id",
        continuity_class=SessionContinuityClass.transfer_scoped,
        authority_module="core.ugcp_control_transfer_profile",
        recovery_allowed=False,
        terminal_requires_new_handshake=True,
        description=(
            "Delegation / handoff / transfer lifecycle context.  Tracks the "
            "transfer of execution ownership across participants or devices.  "
            "Scoped to one transfer lifecycle; terminal states (completed, "
            "rejected, cancelled, expired) are non-recoverable.  A new "
            "transfer handshake is required for any subsequent delegation."
        ),
    ),
    SessionFamilyRecord(
        family=SessionFamily.mesh,
        canonical_identifier="mesh_session_id",
        continuity_class=SessionContinuityClass.overlay,
        authority_module="contracts.mesh_session",
        recovery_allowed=True,
        terminal_requires_new_handshake=True,
        description=(
            "Mesh / staged coordination session.  An optional overlay that is "
            "only active when multi-participant staged coordination is required.  "
            "Governs membership, assignment, and barrier semantics for staged "
            "multi-device execution.  Absent when single-device or simple "
            "delegated execution is used."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Session identifier catalogue
# ---------------------------------------------------------------------------

_SESSION_IDENTIFIER_CATALOGUE: Tuple[SessionIdentifierRecord, ...] = (
    # --- Conversation session family ---
    SessionIdentifierRecord(
        field_name="conversation_session_id",
        family=SessionFamily.conversation,
        role=SessionIdentifierRole.canonical,
        canonical_name="conversation_session_id",
        resolution_priority=1,
        android_side_name="conversation_session_id",
        notes=(
            "Canonical identifier for conversation/history continuity.  "
            "Introduced as a canonical name in core.schemas.ugcp.shared."
        ),
    ),
    SessionIdentifierRecord(
        field_name="session_id",
        family=SessionFamily.conversation,
        role=SessionIdentifierRole.legacy_bare,
        canonical_name="conversation_session_id",
        resolution_priority=3,
        android_side_name="session_id",
        notes=(
            "Legacy bare session identifier.  Context-dependent; in "
            "chat/conversation payloads this resolves to "
            "conversation_session_id.  Must not be used on new surfaces."
        ),
    ),
    # --- Control session family ---
    SessionIdentifierRecord(
        field_name="control_session_id",
        family=SessionFamily.control,
        role=SessionIdentifierRole.canonical,
        canonical_name="control_session_id",
        resolution_priority=1,
        android_side_name="session_id",
        notes=(
            "Canonical identifier for control-plane continuity.  "
            "Scoped to a single request lifecycle.  "
            "In compatibility payloads, normalize_conversation_session_id() "
            "treats control_session_id as a fallback alias for "
            "conversation_session_id when conversation_session_id is absent; "
            "this is a compatibility accommodation and does not change the "
            "canonical role of control_session_id in the control family."
        ),
    ),
    # --- Runtime attachment session family ---
    SessionIdentifierRecord(
        field_name="runtime_attachment_session_id",
        family=SessionFamily.runtime_attachment,
        role=SessionIdentifierRole.canonical,
        canonical_name="runtime_attachment_session_id",
        resolution_priority=1,
        android_side_name="runtime_attachment_session_id",
        notes=(
            "Canonical identifier for runtime attachment continuity.  "
            "Introduced as a canonical name in core.schemas.ugcp.shared and "
            "core.attached_runtime_session."
        ),
    ),
    SessionIdentifierRecord(
        field_name="runtime_session_id",
        family=SessionFamily.runtime_attachment,
        role=SessionIdentifierRole.alias,
        canonical_name="runtime_attachment_session_id",
        resolution_priority=2,
        android_side_name="runtime_session_id",
        notes=(
            "Stable opaque runtime session identity used by the "
            "AttachedSessionRegistry.  Pre-dates the canonical name.  "
            "Normalised to runtime_attachment_session_id by "
            "normalize_runtime_attachment_session_id().  Preserved across "
            "reconnects per RECONNECT_PRESERVES_RUNTIME_SESSION_ID_POLICY."
        ),
    ),
    SessionIdentifierRecord(
        field_name="attached_session_id",
        family=SessionFamily.runtime_attachment,
        role=SessionIdentifierRole.alias,
        canonical_name="runtime_attachment_session_id",
        resolution_priority=3,
        android_side_name="attached_session_id",
        notes=(
            "Android-side transitional alias for runtime_session_id / "
            "runtime_attachment_session_id.  Normalised to "
            "runtime_attachment_session_id at ingress."
        ),
    ),
    SessionIdentifierRecord(
        field_name="session_id",
        family=SessionFamily.runtime_attachment,
        role=SessionIdentifierRole.legacy_bare,
        canonical_name="runtime_attachment_session_id",
        resolution_priority=4,
        android_side_name="session_id",
        notes=(
            "Legacy bare session_id used in attached-runtime payloads.  "
            "Stored as the internal session_id field in "
            "AttachedRuntimeSessionRecord when runtime_attachment_session_id "
            "is absent.  Not to be introduced on new surfaces."
        ),
    ),
    # --- Delegation transfer session family ---
    SessionIdentifierRecord(
        field_name="delegation_transfer_session_id",
        family=SessionFamily.delegation_transfer,
        role=SessionIdentifierRole.canonical,
        canonical_name="delegation_transfer_session_id",
        resolution_priority=1,
        android_side_name="delegation_transfer_session_id",
        notes=(
            "Canonical identifier for delegation/transfer lifecycle.  "
            "Introduced as a canonical name in core.schemas.ugcp.shared and "
            "core.delegated_runtime_handoff_contract."
        ),
    ),
    SessionIdentifierRecord(
        field_name="transfer_session_id",
        family=SessionFamily.delegation_transfer,
        role=SessionIdentifierRole.alias,
        canonical_name="delegation_transfer_session_id",
        resolution_priority=2,
        android_side_name="transfer_session_id",
        notes=(
            "Transitional alias for delegation_transfer_session_id.  "
            "Normalised by normalize_delegation_transfer_session_id()."
        ),
    ),
    SessionIdentifierRecord(
        field_name="handoff_session_id",
        family=SessionFamily.delegation_transfer,
        role=SessionIdentifierRole.alias,
        canonical_name="delegation_transfer_session_id",
        resolution_priority=3,
        android_side_name="handoff_session_id",
        notes=(
            "Transitional alias for delegation_transfer_session_id.  "
            "Normalised by normalize_delegation_transfer_session_id()."
        ),
    ),
    # --- Mesh session family ---
    SessionIdentifierRecord(
        field_name="mesh_session_id",
        family=SessionFamily.mesh,
        role=SessionIdentifierRole.canonical,
        canonical_name="mesh_session_id",
        resolution_priority=1,
        android_side_name="mesh_session_id",
        notes=(
            "Canonical identifier for mesh/staged coordination.  Same name "
            "is used on both center and Android sides.  Only present when "
            "mesh coordination is active."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Android session mapping catalogue
# ---------------------------------------------------------------------------

_ANDROID_SESSION_MAPPING_CATALOGUE: Tuple[AndroidSessionMapping, ...] = (
    AndroidSessionMapping(
        android_field="session_id",
        center_canonical_field="control_session_id",
        family=SessionFamily.control,
        classification="TRANSITIONAL_ALIAS",
        notes=(
            "Android primary session field maps to control_session_id.  "
            "Normalised at ingress by normalize_conversation_session_id().  "
            "Android side should adopt conversation_session_id for new "
            "conversation-continuity surfaces."
        ),
    ),
    AndroidSessionMapping(
        android_field="runtime_session_id",
        center_canonical_field="runtime_attachment_session_id",
        family=SessionFamily.runtime_attachment,
        classification="TRANSITIONAL_ALIAS",
        notes=(
            "Normalised at ingress by normalize_runtime_attachment_session_id().  "
            "Center registry (core.attached_runtime_session_registry) is the "
            "authoritative resolver for active/non-active state."
        ),
    ),
    AndroidSessionMapping(
        android_field="attached_session_id",
        center_canonical_field="runtime_attachment_session_id",
        family=SessionFamily.runtime_attachment,
        classification="TRANSITIONAL_ALIAS",
        notes=(
            "Android-side alias for runtime_session_id.  Normalised to "
            "runtime_attachment_session_id at ingress.  Center registry is "
            "the authority."
        ),
    ),
    AndroidSessionMapping(
        android_field="transfer_session_id",
        center_canonical_field="delegation_transfer_session_id",
        family=SessionFamily.delegation_transfer,
        classification="TRANSITIONAL_ALIAS",
        notes=(
            "Normalised at ingress by normalize_delegation_transfer_session_id().  "
            "Transfer/delegation semantics are governed by "
            "core.ugcp_control_transfer_profile on the center side."
        ),
    ),
    AndroidSessionMapping(
        android_field="handoff_session_id",
        center_canonical_field="delegation_transfer_session_id",
        family=SessionFamily.delegation_transfer,
        classification="TRANSITIONAL_ALIAS",
        notes=(
            "Normalised at ingress by normalize_delegation_transfer_session_id()."
        ),
    ),
    AndroidSessionMapping(
        android_field="mesh_session_id",
        center_canonical_field="mesh_session_id",
        family=SessionFamily.mesh,
        classification="CANONICAL_MATCH",
        notes=(
            "Same name in both repositories.  Preserved end-to-end when mesh "
            "coordination is active."
        ),
    ),
    AndroidSessionMapping(
        android_field="conversation_session_id",
        center_canonical_field="conversation_session_id",
        family=SessionFamily.conversation,
        classification="PARTIAL_MATCH",
        notes=(
            "Both repos use the concept but local models are not yet unified "
            "at the protocol level.  Semantically related; not yet required "
            "to be structurally identical."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Public API — catalogue accessors
# ---------------------------------------------------------------------------


def get_session_family_catalogue() -> List[SessionFamilyRecord]:
    """Return the complete session family catalogue.

    Returns
    -------
    list[SessionFamilyRecord]
        One record per canonical session family.
    """
    return list(_SESSION_FAMILY_CATALOGUE)


def get_session_identifier_catalogue() -> List[SessionIdentifierRecord]:
    """Return the complete session identifier catalogue.

    Returns
    -------
    list[SessionIdentifierRecord]
        One record per known session identifier field.
    """
    return list(_SESSION_IDENTIFIER_CATALOGUE)


def get_android_session_mapping_catalogue() -> List[AndroidSessionMapping]:
    """Return the complete Android-to-center session mapping catalogue.

    Returns
    -------
    list[AndroidSessionMapping]
        One record per Android-side session field.
    """
    return list(_ANDROID_SESSION_MAPPING_CATALOGUE)


# ---------------------------------------------------------------------------
# Public API — classification helpers
# ---------------------------------------------------------------------------


def classify_identifier_role(field_name: str) -> Optional[SessionIdentifierRecord]:
    """Return the identifier record for *field_name*, or ``None`` if unknown.

    Parameters
    ----------
    field_name
        The session identifier field name to classify.

    Returns
    -------
    SessionIdentifierRecord | None
        The matching record, or ``None`` if the field name is not catalogued.
    """
    name = (field_name or "").lower().strip()
    for record in _SESSION_IDENTIFIER_CATALOGUE:
        if record.field_name == name:
            return record
    return None


def resolve_session_family_for_identifier(
    field_name: str,
) -> Optional[SessionFamilyRecord]:
    """Return the session family record for the family that owns *field_name*.

    Parameters
    ----------
    field_name
        A session identifier field name (canonical or alias).

    Returns
    -------
    SessionFamilyRecord | None
        The session family record, or ``None`` if the field is not catalogued.
    """
    id_record = classify_identifier_role(field_name)
    if id_record is None:
        return None
    for family_record in _SESSION_FAMILY_CATALOGUE:
        if family_record.family == id_record.family:
            return family_record
    return None


# ---------------------------------------------------------------------------
# Public API — snapshot builder
# ---------------------------------------------------------------------------


def build_session_axis_snapshot() -> SessionAxisSnapshot:
    """Build a point-in-time snapshot of the canonical session axis model.

    Returns
    -------
    SessionAxisSnapshot
        Snapshot containing all catalogues and summary counts.
    """
    import uuid

    families = get_session_family_catalogue()
    identifiers = get_session_identifier_catalogue()
    mappings = get_android_session_mapping_catalogue()

    return SessionAxisSnapshot(
        snapshot_id=f"sax_{uuid.uuid4().hex[:12]}",
        created_at=time.time(),
        family_count=len(families),
        identifier_count=len(identifiers),
        android_mapping_count=len(mappings),
        family_records=[f.to_dict() for f in families],
        identifier_records=[i.to_dict() for i in identifiers],
        android_mappings=[m.to_dict() for m in mappings],
    )
