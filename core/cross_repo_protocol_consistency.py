"""core/cross_repo_protocol_consistency.py
===========================================
PR-4 (Canonical cross-repository protocol consistency rules — main repository
side).

This module is the **canonical authority** for cross-repository protocol
consistency rules on the most load-bearing shared protocol surfaces between
``DannyFish-11/ufo-galaxy-realization-v2`` (center) and
``DannyFish-11/ufo-galaxy-android`` (android).

It explicitly defines:

1. The critical shared protocol surfaces and their consistency classification.
2. Which surfaces are canonical vs transitional (compat-only).
3. The canonical terminal state set and any known mismatches across modules.
4. Delegated execution result/status semantics.
5. Key session and runtime identifier consistency rules (referencing PR-3).
6. Runtime profile and capability descriptor consistency.
7. Truth-event payload structure consistency rules.
8. Explicit transitional compatibility allowances to prevent silent drift.

Background
----------
The system has meaningful protocol governance infrastructure built across
PR-1 through PR-3:

* ``docs/ugcp/UGCP_CONSTITUTION_V1.md`` — constitutional rules
* ``docs/ugcp/CROSS_REPO_HOMOMORPHIC_MAPPING_V1.md`` — mapping baseline
* ``core.canonical_session_axis`` — session identifier consistency (PR-3)
* ``core.schemas.ugcp.shared`` — shared canonical schema vocabulary
* ``core.ugcp_truth_event_model`` — truth/event backbone (PR-7)
* ``core.delegated_runtime_execution_tracker`` — delegated execution tracking
* ``core.delegated_runtime_handoff_contract`` — handoff contract lifecycle

However, cross-repository protocol alignment still depends too heavily on
incremental convergence, transitional compatibility families, alias
normalisation, and documentation-based discipline rather than explicit
consistency rules.

This module makes those rules explicit and inspectable, stopping uncontrolled
drift on the most important shared protocol surfaces.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Inspectable** — every rule is expressed as a named record or constant,
  not just a comment.
- **Behaviour-preserving** — existing runtime semantics are documented here
  but remain governed by their existing authority modules.
- **Drift-resistant** — explicit classification prevents silent divergence
  between repositories.
- **CI-suitable** — the catalogue and snapshot builder are designed to be
  queried by CI consistency checks.

Public surface
--------------
Sentinels
~~~~~~~~~
:data:`CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY`
:data:`CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL`
:data:`CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY`
:data:`TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY`
:data:`TERMINAL_STATE_SET_IS_CLOSED_POLICY`
:data:`DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY`
:data:`TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY`
:data:`CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY`

Enums
~~~~~
:class:`ProtocolSurfaceClass`
:class:`ProtocolConsistencyCategory`
:class:`CanonicalTerminalState`
:class:`TransitionalAllowanceKind`

Data classes
~~~~~~~~~~~~
:class:`ProtocolSurfaceRecord`
:class:`TerminalStateConsistencyRecord`
:class:`DelegatedExecutionStatusRecord`
:class:`TruthEventSurfaceRecord`
:class:`TransitionalAllowanceRecord`
:class:`ProtocolConsistencySnapshot`

Functions
~~~~~~~~~
:func:`get_protocol_surface_catalogue`
:func:`get_terminal_state_consistency_catalogue`
:func:`get_delegated_execution_status_catalogue`
:func:`get_truth_event_surface_catalogue`
:func:`get_transitional_allowance_catalogue`
:func:`classify_protocol_surface`
:func:`is_canonical_surface`
:func:`build_protocol_consistency_snapshot`
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

__all__ = [
    # Authority / policy sentinels
    "CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY",
    "CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL",
    "CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY",
    "TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY",
    "TERMINAL_STATE_SET_IS_CLOSED_POLICY",
    "DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY",
    "TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY",
    "CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY",
    # Enums
    "ProtocolSurfaceClass",
    "ProtocolConsistencyCategory",
    "CanonicalTerminalState",
    "TransitionalAllowanceKind",
    # Data classes
    "ProtocolSurfaceRecord",
    "TerminalStateConsistencyRecord",
    "DelegatedExecutionStatusRecord",
    "TruthEventSurfaceRecord",
    "TransitionalAllowanceRecord",
    "ProtocolConsistencySnapshot",
    # Functions
    "get_protocol_surface_catalogue",
    "get_terminal_state_consistency_catalogue",
    "get_delegated_execution_status_catalogue",
    "get_truth_event_surface_catalogue",
    "get_transitional_allowance_catalogue",
    "classify_protocol_surface",
    "is_canonical_surface",
    "build_protocol_consistency_snapshot",
]

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY: str = (
    "CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY::"
    "core.cross_repo_protocol_consistency is the canonical authority for "
    "cross-repository protocol consistency rules on the most load-bearing "
    "shared protocol surfaces (PR-4, establish canonical cross-repo protocol "
    "consistency rules)."
)

CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL: str = (
    "CROSS_REPO_PROTOCOL_CONSISTENCY_PR4_SENTINEL::package=PR4::"
    "profile=cross-repo-protocol-consistency-v1::"
    "module=core.cross_repo_protocol_consistency"
)

CANONICAL_SURFACES_ARE_DRIFT_PROTECTED_POLICY: str = (
    "POLICY::CANONICAL_SURFACES_ARE_DRIFT_PROTECTED: surfaces classified as "
    "'canonical' in the protocol surface catalogue represent the authoritative "
    "cross-repository contract.  Their vocabulary (enum values, field names, "
    "payload structure) must not change without a coordinated dual-repository "
    "update and an explicit consistency-rule revision.  Unilateral changes to "
    "canonical surfaces constitute protocol drift and are prohibited."
)

TRANSITIONAL_SURFACES_MUST_NOT_EXPAND_POLICY: str = (
    "POLICY::TRANSITIONAL_SURFACES_MUST_NOT_EXPAND: surfaces classified as "
    "'transitional' are explicitly bounded compatibility allowances.  Their "
    "scope must not be extended and no new transitional allowances may be "
    "introduced without explicit PR-level justification.  Each transitional "
    "allowance must carry a retirement pathway."
)

TERMINAL_STATE_SET_IS_CLOSED_POLICY: str = (
    "POLICY::TERMINAL_STATE_SET_IS_CLOSED: the canonical terminal state "
    "vocabulary (completed, failed, partial, cancelled, timed_out) is the "
    "closed set for all shared protocol surfaces.  No new terminal state "
    "values may be introduced on cross-repository surfaces without a "
    "coordinated dual-repository update that revises this catalogue."
)

DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY_POLICY: str = (
    "POLICY::DELEGATED_EXECUTION_STATUS_IS_CENTER_AUTHORITY: the center "
    "repository (realization-v2) is the authoritative resolver for delegated "
    "execution lifecycle status.  Android-side execution signals are evidence "
    "inputs that are normalised into canonical DelegatedExecutionPhase values "
    "at center ingress.  Android must not act as an independent execution "
    "lifecycle authority."
)

TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY: str = (
    "POLICY::TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN: the CanonicalTruthEventType "
    "vocabulary in core.ugcp_truth_event_model is frozen.  New truth-event "
    "types must not be introduced without explicit PR-level review and addition "
    "to the truth-event surface catalogue maintained in this module."
)

CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL_POLICY: str = (
    "POLICY::CAPABILITY_DESCRIPTOR_FIELDS_ARE_CANONICAL: the capability and "
    "runtime-profile descriptor fields (capabilities, capability_flags, "
    "supported_actions, source_runtime_posture, coordination_role) are "
    "canonical cross-repository fields.  Android-side capability reports must "
    "use these field names.  Undocumented extra fields are tolerated but must "
    "not replace canonical fields."
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ProtocolSurfaceClass(str, Enum):
    """Classification of a protocol surface's consistency status.

    canonical
        This surface has stable, explicitly agreed vocabulary and semantics
        across both repositories.  Changes require a coordinated update.

    transitional
        This surface is a bounded compatibility allowance.  The Android-side
        or center-side name/value differs but is explicitly normalised at
        ingress.  Must carry a retirement pathway.

    deprecated
        This surface is marked for retirement.  New code must not consume or
        produce it.

    unresolved
        This surface has a known inconsistency that has not yet been resolved.
        It is explicitly catalogued here so that drift is visible.
    """

    canonical = "canonical"
    transitional = "transitional"
    deprecated = "deprecated"
    unresolved = "unresolved"


class ProtocolConsistencyCategory(str, Enum):
    """The high-level category of a protocol surface.

    shared_vocabulary
        Shared UGCP schema/enum vocabulary (types, field names, enum values).

    terminal_state
        Terminal lifecycle state vocabulary across all shared protocol surfaces.

    session_identifier
        Session and runtime identifier consistency (see also PR-3).

    delegated_execution
        Delegated execution lifecycle status and result semantics.

    runtime_profile
        Runtime profile and capability descriptor fields.

    truth_event
        Truth-event payload structure and canonical event type vocabulary.

    compatibility_alias
        Explicit alias normalisation allowances (Android→center field renames).
    """

    shared_vocabulary = "shared_vocabulary"
    terminal_state = "terminal_state"
    session_identifier = "session_identifier"
    delegated_execution = "delegated_execution"
    runtime_profile = "runtime_profile"
    truth_event = "truth_event"
    compatibility_alias = "compatibility_alias"


class CanonicalTerminalState(str, Enum):
    """Canonical cross-repository terminal state vocabulary.

    This is the **closed** set of terminal state values for all shared
    protocol surfaces.  See TERMINAL_STATE_SET_IS_CLOSED_POLICY.

    completed
        The operation completed successfully.

    failed
        The operation ended in an unrecoverable error.

    partial
        The operation completed but with degraded / incomplete results.

    cancelled
        The operation was explicitly cancelled before completion.

    timed_out
        The operation did not complete within the allowed time window.
    """

    completed = "completed"
    failed = "failed"
    partial = "partial"
    cancelled = "cancelled"
    timed_out = "timed_out"


class TransitionalAllowanceKind(str, Enum):
    """The kind of transitional compatibility allowance.

    field_rename
        Android-side field name differs; normalised to canonical at ingress.

    enum_variant
        Android-side enum value differs; normalised to canonical at ingress.

    semantic_approximation
        Semantically related but not yet structurally unified; partial match.

    legacy_default
        Center-side legacy default preserved for backward compatibility.
    """

    field_rename = "field_rename"
    enum_variant = "enum_variant"
    semantic_approximation = "semantic_approximation"
    legacy_default = "legacy_default"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProtocolSurfaceRecord:
    """Description of one cross-repository protocol surface.

    Attributes
    ----------
    surface_id
        Short machine-readable identifier for the surface.
    category
        The consistency category this surface belongs to.
    surface_class
        Canonical, transitional, deprecated, or unresolved.
    center_authority
        The module or constant that governs this surface on the center side.
    android_counterpart
        The corresponding surface on the Android side, or ``""`` if
        center-only.
    description
        Human-readable description of the surface and its consistency status.
    retirement_pathway
        For transitional/deprecated surfaces: the target canonical surface
        and migration path.  Empty for canonical surfaces.
    """

    surface_id: str
    category: ProtocolConsistencyCategory
    surface_class: ProtocolSurfaceClass
    center_authority: str
    android_counterpart: str = ""
    description: str = ""
    retirement_pathway: str = ""


@dataclass(frozen=True)
class TerminalStateConsistencyRecord:
    """Cross-module terminal state consistency record.

    Attributes
    ----------
    state_value
        The canonical terminal state value.
    present_in_shared_schema
        Whether this value is present in ``core.schemas.ugcp.shared._VALID_TERMINAL_STATES``.
    present_in_execution_phase
        Whether this value appears as a terminal ``DelegatedExecutionPhase``.
    present_in_handoff_contract
        Whether an equivalent terminal value appears in ``HandoffContractStatus``.
    android_variant
        The corresponding Android-side value, or ``""`` if identical.
    consistency_note
        Explanation of any cross-module inconsistency.
    """

    state_value: str
    present_in_shared_schema: bool
    present_in_execution_phase: bool
    present_in_handoff_contract: bool
    android_variant: str = ""
    consistency_note: str = ""

    @property
    def is_fully_consistent(self) -> bool:
        """Return True iff the state is present in all three authority surfaces."""
        return (
            self.present_in_shared_schema
            and self.present_in_execution_phase
            and self.present_in_handoff_contract
        )


@dataclass(frozen=True)
class DelegatedExecutionStatusRecord:
    """Canonical record for one delegated execution lifecycle status.

    Attributes
    ----------
    phase_value
        The ``DelegatedExecutionPhase`` enum value string.
    is_terminal
        Whether this phase is a terminal state.
    android_signal_kind
        The Android-side signal that maps to this phase, or ``""`` if none.
    center_authority
        The center-side module that defines/governs this status.
    notes
        Additional cross-repo alignment notes.
    """

    phase_value: str
    is_terminal: bool
    android_signal_kind: str = ""
    center_authority: str = "core.delegated_runtime_execution_tracker"
    notes: str = ""


@dataclass(frozen=True)
class TruthEventSurfaceRecord:
    """Canonical record for one truth-event type and its payload structure.

    Attributes
    ----------
    event_type
        The canonical ``CanonicalTruthEventType`` value string.
    surface_class
        Canonical or transitional.
    required_payload_fields
        Tuple of field names that must be present in the event payload.
    optional_payload_fields
        Tuple of field names that may optionally be present.
    android_visible
        Whether the Android side consumes or produces events of this type.
    notes
        Additional cross-repo alignment notes.
    """

    event_type: str
    surface_class: ProtocolSurfaceClass
    required_payload_fields: Tuple[str, ...] = field(default_factory=tuple)
    optional_payload_fields: Tuple[str, ...] = field(default_factory=tuple)
    android_visible: bool = False
    notes: str = ""


@dataclass(frozen=True)
class TransitionalAllowanceRecord:
    """Explicit transitional compatibility allowance between the two repositories.

    Attributes
    ----------
    allowance_id
        Short machine-readable identifier.
    kind
        The kind of allowance (field_rename, enum_variant, etc.).
    android_side_value
        The value as it appears on the Android side.
    center_canonical_value
        The value as it appears on the center (canonical) side.
    normalisation_location
        The module/function responsible for normalising this allowance.
    retirement_condition
        The condition under which this allowance can be retired.
    """

    allowance_id: str
    kind: TransitionalAllowanceKind
    android_side_value: str
    center_canonical_value: str
    normalisation_location: str
    retirement_condition: str = ""


@dataclass
class ProtocolConsistencySnapshot:
    """Point-in-time snapshot of the cross-repository protocol consistency state.

    Attributes
    ----------
    generated_at
        Unix timestamp when the snapshot was assembled.
    protocol_surface_count
        Total number of protocol surfaces in the catalogue.
    canonical_surface_count
        Number of surfaces classified as canonical.
    transitional_surface_count
        Number of surfaces classified as transitional.
    deprecated_surface_count
        Number of surfaces classified as deprecated.
    unresolved_surface_count
        Number of surfaces classified as unresolved.
    terminal_state_count
        Total number of canonical terminal states.
    fully_consistent_terminal_states
        Number of terminal states consistent across all three authority surfaces.
    delegated_execution_phase_count
        Total number of delegated execution phases.
    terminal_execution_phase_count
        Number of delegated execution phases that are terminal.
    truth_event_type_count
        Total number of truth-event types in the catalogue.
    transitional_allowance_count
        Total number of explicit transitional compatibility allowances.
    authority
        Authority sentinel for this snapshot.
    """

    generated_at: float = field(default_factory=time.time)
    protocol_surface_count: int = 0
    canonical_surface_count: int = 0
    transitional_surface_count: int = 0
    deprecated_surface_count: int = 0
    unresolved_surface_count: int = 0
    terminal_state_count: int = 0
    fully_consistent_terminal_states: int = 0
    delegated_execution_phase_count: int = 0
    terminal_execution_phase_count: int = 0
    truth_event_type_count: int = 0
    transitional_allowance_count: int = 0
    authority: str = CROSS_REPO_PROTOCOL_CONSISTENCY_AUTHORITY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "protocol_surface_count": self.protocol_surface_count,
            "canonical_surface_count": self.canonical_surface_count,
            "transitional_surface_count": self.transitional_surface_count,
            "deprecated_surface_count": self.deprecated_surface_count,
            "unresolved_surface_count": self.unresolved_surface_count,
            "terminal_state_count": self.terminal_state_count,
            "fully_consistent_terminal_states": self.fully_consistent_terminal_states,
            "delegated_execution_phase_count": self.delegated_execution_phase_count,
            "terminal_execution_phase_count": self.terminal_execution_phase_count,
            "truth_event_type_count": self.truth_event_type_count,
            "transitional_allowance_count": self.transitional_allowance_count,
            "authority": self.authority,
        }


# ---------------------------------------------------------------------------
# Protocol surface catalogue
# ---------------------------------------------------------------------------

_PROTOCOL_SURFACE_CATALOGUE: Tuple[ProtocolSurfaceRecord, ...] = (
    # ------------------------------------------------------------------
    # Shared UGCP vocabulary
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="ugcp_shared_schema_vocabulary",
        category=ProtocolConsistencyCategory.shared_vocabulary,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.schemas.ugcp.shared.UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY",
        android_counterpart="UGCP-aligned schema vocabulary (alignment target)",
        description=(
            "The core.schemas.ugcp.shared module defines the canonical UGCP "
            "schema vocabulary for identity, session, control, runtime, "
            "coordination, and truth objects.  Both repositories target this "
            "vocabulary.  Changes require coordinated dual-repository update."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="ugcp_participant_model",
        category=ProtocolConsistencyCategory.shared_vocabulary,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.schemas.ugcp.shared.ParticipantModel",
        android_counterpart="UGCP-aligned participant concept (alignment target)",
        description=(
            "ParticipantModel is the canonical participant identity model.  "
            "Both repositories target this vocabulary.  Android aligns to the "
            "UGCP ParticipantModel concept as its convergence target."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="ugcp_task_envelope",
        category=ProtocolConsistencyCategory.shared_vocabulary,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority="core.schemas.ugcp.shared.TaskEnvelope",
        android_counterpart="Task envelope / task payload (android)",
        description=(
            "Center has a canonical TaskEnvelope schema type.  Android aligns "
            "via UGCP vocabulary but not yet fully unified at the wire level."
        ),
        retirement_pathway=(
            "Full wire-level unification of TaskEnvelope between repositories.  "
            "Android must adopt the canonical TaskEnvelope field structure."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="ugcp_dispatch_decision",
        category=ProtocolConsistencyCategory.shared_vocabulary,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority="core.schemas.ugcp.shared.DispatchDecision",
        android_counterpart="Android dispatch intent record",
        description=(
            "Center uses DispatchDecision with a mapping shim from "
            "DelegatedRuntimeDispatchRecord.  Android-side is partially "
            "aligned.  Not yet fully unified at wire level."
        ),
        retirement_pathway=(
            "Android-side adoption of canonical DispatchDecision field "
            "structure, retiring the mapping shim."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="ugcp_handoff_request",
        category=ProtocolConsistencyCategory.shared_vocabulary,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority="core.schemas.ugcp.shared.HandoffRequest",
        android_counterpart="Android handoff event",
        description=(
            "Center uses HandoffRequest with a mapping shim from "
            "DelegatedHandoffContractRecord.  Android-side is partially "
            "aligned.  Not yet fully unified at wire level."
        ),
        retirement_pathway=(
            "Android-side adoption of canonical HandoffRequest field "
            "structure, retiring the mapping shim."
        ),
    ),
    # ------------------------------------------------------------------
    # Terminal state surfaces
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="terminal_state_vocabulary",
        category=ProtocolConsistencyCategory.terminal_state,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.schemas.ugcp.shared._VALID_TERMINAL_STATES",
        android_counterpart="Android completion/failure/cancel outcomes",
        description=(
            "The canonical terminal state vocabulary (completed, failed, "
            "partial, cancelled, timed_out) is the closed set for all shared "
            "protocol surfaces.  Android final outcomes are normalised into "
            "this vocabulary at center ingress."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="terminal_state_timed_out_alignment",
        category=ProtocolConsistencyCategory.terminal_state,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority=(
            "core.delegated_runtime_execution_tracker.DelegatedExecutionPhase.timed_out"
        ),
        android_counterpart="Android timeout variant",
        description=(
            "The execution tracker uses 'timed_out' while "
            "CROSS_RUNTIME_RESULT_MERGE_CONTRACT uses 'timeout'.  "
            "This is a known variant that is normalised at the result-merge "
            "boundary.  Both map to CanonicalTerminalState.timed_out."
        ),
        retirement_pathway=(
            "Unify 'timeout' variant in CROSS_RUNTIME_RESULT_MERGE_CONTRACT "
            "to 'timed_out' to eliminate this normalisation requirement."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="terminal_state_interrupted_legacy",
        category=ProtocolConsistencyCategory.terminal_state,
        surface_class=ProtocolSurfaceClass.deprecated,
        center_authority="core.schemas.ugcp.shared._VALID_TERMINAL_STATES",
        android_counterpart="",
        description=(
            "'interrupted' is present in the shared schema _VALID_TERMINAL_STATES "
            "but does not appear in DelegatedExecutionPhase terminal set.  "
            "It is a legacy value that should not be used on new surfaces."
        ),
        retirement_pathway=(
            "Remove 'interrupted' from _VALID_TERMINAL_STATES once all "
            "existing usages have been migrated to 'failed' or 'cancelled'."
        ),
    ),
    # ------------------------------------------------------------------
    # Session identifier surfaces (see also PR-3 canonical_session_axis)
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="session_axis_model",
        category=ProtocolConsistencyCategory.session_identifier,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.canonical_session_axis.CANONICAL_SESSION_AXIS_AUTHORITY",
        android_counterpart="Android session identifier claims",
        description=(
            "The session axis model (PR-3) defines five session families, "
            "canonical identifiers, alias resolution order, and Android "
            "mapping catalogue.  This is the authoritative cross-repo session "
            "identifier model."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="runtime_attachment_session_id",
        category=ProtocolConsistencyCategory.session_identifier,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.canonical_session_axis.SessionFamily.runtime_attachment"
        ),
        android_counterpart="runtime_session_id / attached_session_id",
        description=(
            "runtime_attachment_session_id is the canonical name for runtime "
            "attachment session identity on the center side.  Android-side "
            "aliases (runtime_session_id, attached_session_id) are normalised "
            "at ingress by normalize_runtime_attachment_session_id()."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="delegation_transfer_session_id",
        category=ProtocolConsistencyCategory.session_identifier,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.canonical_session_axis.SessionFamily.delegation_transfer"
        ),
        android_counterpart="transfer_session_id / handoff_session_id",
        description=(
            "delegation_transfer_session_id is the canonical name for "
            "delegation transfer session identity.  Android-side aliases "
            "(transfer_session_id, handoff_session_id) are normalised at "
            "ingress by normalize_delegation_transfer_session_id()."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="mesh_session_id",
        category=ProtocolConsistencyCategory.session_identifier,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.canonical_session_axis.SessionFamily.mesh",
        android_counterpart="mesh_session_id",
        description=(
            "mesh_session_id is a canonical match across both repositories.  "
            "Same name and semantics; preserved end-to-end when mesh is active."
        ),
    ),
    # ------------------------------------------------------------------
    # Delegated execution surfaces
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="delegated_execution_phase",
        category=ProtocolConsistencyCategory.delegated_execution,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.delegated_runtime_execution_tracker.DelegatedExecutionPhase"
        ),
        android_counterpart="Android delegated execution signal kinds",
        description=(
            "DelegatedExecutionPhase is the canonical execution lifecycle "
            "model for delegated work.  Android-side signals are normalised "
            "into this vocabulary at center ingress.  Center is the authority."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="handoff_contract_status",
        category=ProtocolConsistencyCategory.delegated_execution,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.delegated_runtime_handoff_contract.HandoffContractStatus"
        ),
        android_counterpart="Android handoff receipt/execution signals",
        description=(
            "HandoffContractStatus governs the lifecycle of a handoff contract "
            "(draft → sealed → dispatched; expired/cancelled are terminal).  "
            "This is distinct from DelegatedExecutionPhase which governs the "
            "post-dispatch execution lifecycle."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="delegated_execution_result",
        category=ProtocolConsistencyCategory.delegated_execution,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.delegated_runtime_execution_tracker.DelegatedExecutionResult"
        ),
        android_counterpart="Android execution result payload",
        description=(
            "DelegatedExecutionResult is the canonical result structure "
            "(success, result_payload, error_detail, completed_at, metadata).  "
            "Android-side result payloads are reconciled into this structure "
            "at center ingress."
        ),
    ),
    # ------------------------------------------------------------------
    # Runtime profile and capability descriptor surfaces
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="runtime_capability_profile",
        category=ProtocolConsistencyCategory.runtime_profile,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "contracts.registered_runtime_device.RuntimeCapabilityProfile"
        ),
        android_counterpart="Android capability_report message",
        description=(
            "RuntimeCapabilityProfile defines the canonical capability surface "
            "(capabilities, capability_flags, supported_actions).  Android "
            "reports capabilities via the 'capability_report' message which "
            "maps to this profile.  Canonical field names are authoritative."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="capability_scheduling_basis",
        category=ProtocolConsistencyCategory.runtime_profile,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.canonical_capability_scheduling_basis.RuntimeCapabilityProfile"
        ),
        android_counterpart="Android runtime host role and posture",
        description=(
            "The canonical capability scheduling basis (PR-6 post-533) defines "
            "CapabilityTier, ExecutionSurface, and RuntimeCapabilityProfile for "
            "center-side scheduling decisions.  Android host role and posture "
            "is classified into this model."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="source_runtime_posture_field",
        category=ProtocolConsistencyCategory.runtime_profile,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.canonical_session_truth.CanonicalSessionTruthRecord.source_runtime_posture"
        ),
        android_counterpart="Android posture field in registration/status",
        description=(
            "source_runtime_posture is a canonical cross-repo field identifying "
            "the runtime execution posture (control_only, runtime_host, etc.).  "
            "Both repositories use this field name."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="coordination_role_field",
        category=ProtocolConsistencyCategory.runtime_profile,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority="core.schemas.ugcp.shared.CoordinationRole",
        android_counterpart="Android participant role (registration metadata)",
        description=(
            "coordination_role is the canonical name on the center side.  "
            "Android reports roles as registration metadata using the same "
            "conceptual vocabulary but not yet unified at enum level."
        ),
        retirement_pathway=(
            "Full enum-level unification of coordination_role between "
            "repositories, so Android uses the same enum values as center."
        ),
    ),
    # ------------------------------------------------------------------
    # Truth-event payload surfaces
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="canonical_truth_event_envelope",
        category=ProtocolConsistencyCategory.truth_event,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.ugcp_truth_event_model.CanonicalTruthEventEnvelope"
        ),
        android_counterpart="Android truth event surface (center authority)",
        description=(
            "CanonicalTruthEventEnvelope is the canonical wrapper for all "
            "authoritative truth transition events.  The center is the "
            "truth authority; Android-side runtime truth is an input to "
            "center authority, not an independent truth source."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="truth_event_type_vocabulary",
        category=ProtocolConsistencyCategory.truth_event,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority=(
            "core.ugcp_truth_event_model.CanonicalTruthEventType"
        ),
        android_counterpart="Android runtime truth surface",
        description=(
            "The CanonicalTruthEventType vocabulary is frozen (PR-7).  "
            "No new event types may be introduced without explicit review.  "
            "See TRUTH_EVENT_TYPE_VOCABULARY_IS_FROZEN_POLICY."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="truth_event_base_payload_fields",
        category=ProtocolConsistencyCategory.truth_event,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="core.schemas.ugcp.shared.TruthEvent",
        android_counterpart="Android truth event payload",
        description=(
            "The base TruthEvent payload fields (event_type, trace_id, "
            "task_id, control_session_id, runtime_session_id, payload) are "
            "canonical.  All truth events must carry these fields."
        ),
    ),
    # ------------------------------------------------------------------
    # Wire-level protocol surfaces
    # ------------------------------------------------------------------
    ProtocolSurfaceRecord(
        surface_id="device_register_message",
        category=ProtocolConsistencyCategory.compatibility_alias,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="galaxy_gateway.android_bridge (device_register handler)",
        android_counterpart="Android device_register WS message",
        description=(
            "device_register is handled canonically: Android WS message "
            "routes through android_bridge registration handler to UDM "
            "registration write.  Same semantics and structure in both repos."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="heartbeat_status_aliases",
        category=ProtocolConsistencyCategory.compatibility_alias,
        surface_class=ProtocolSurfaceClass.transitional,
        center_authority="galaxy_gateway.android.runtime_ws_profile",
        android_counterpart="heartbeat / device_status / agent_status",
        description=(
            "Android variants 'device_status' and 'agent_status' are "
            "transitional aliases for the canonical 'heartbeat' / status "
            "semantics.  All three normalise to center-side heartbeat/status "
            "semantics at ingress."
        ),
        retirement_pathway=(
            "Android side migrates to canonical 'heartbeat' message type, "
            "retiring 'device_status' and 'agent_status' aliases."
        ),
    ),
    ProtocolSurfaceRecord(
        surface_id="delegated_execution_signal_message",
        category=ProtocolConsistencyCategory.compatibility_alias,
        surface_class=ProtocolSurfaceClass.canonical,
        center_authority="galaxy_gateway.android.runtime_ws_profile",
        android_counterpart="Android delegated_execution_signal WS message",
        description=(
            "delegated_execution_signal is canonically handled: Android WS "
            "message routes through android_bridge delegated_signal_ingress "
            "to core.android_delegated_signal_ingress.  Canonical handling "
            "level in both repos."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Terminal state consistency catalogue
# ---------------------------------------------------------------------------

_TERMINAL_STATE_CONSISTENCY_CATALOGUE: Tuple[TerminalStateConsistencyRecord, ...] = (
    TerminalStateConsistencyRecord(
        state_value=CanonicalTerminalState.completed.value,
        present_in_shared_schema=True,
        present_in_execution_phase=True,
        present_in_handoff_contract=False,
        android_variant="completed / success",
        consistency_note=(
            "Fully consistent across shared_schema and execution_phase.  "
            "HandoffContractStatus uses 'dispatched' as its closest terminal "
            "for successful dispatch (not 'completed'), which is intentional: "
            "handoff contract terminal states govern contract lifecycle, not "
            "execution outcome."
        ),
    ),
    TerminalStateConsistencyRecord(
        state_value=CanonicalTerminalState.failed.value,
        present_in_shared_schema=True,
        present_in_execution_phase=True,
        present_in_handoff_contract=False,
        android_variant="failed / error",
        consistency_note=(
            "Consistent across shared_schema and execution_phase.  "
            "HandoffContractStatus uses 'expired' for contract-level failure "
            "(not 'failed').  The distinction is intentional."
        ),
    ),
    TerminalStateConsistencyRecord(
        state_value=CanonicalTerminalState.partial.value,
        present_in_shared_schema=True,
        present_in_execution_phase=False,
        present_in_handoff_contract=False,
        android_variant="partial",
        consistency_note=(
            "Present in shared_schema but not in DelegatedExecutionPhase.  "
            "'partial' is used for degraded result outcomes in the result-merge "
            "layer (RuntimeResultStatus) but not as a phase terminal state.  "
            "This is intentional: partial results are still surfaced through "
            "the completed phase with success=False."
        ),
    ),
    TerminalStateConsistencyRecord(
        state_value=CanonicalTerminalState.cancelled.value,
        present_in_shared_schema=False,
        present_in_execution_phase=True,
        present_in_handoff_contract=True,
        android_variant="cancelled",
        consistency_note=(
            "Present in DelegatedExecutionPhase and HandoffContractStatus "
            "but NOT in shared_schema._VALID_TERMINAL_STATES.  This is a "
            "known inconsistency: 'cancelled' should be added to the shared "
            "schema vocabulary to avoid silent rejections at TerminalState "
            "validation."
        ),
    ),
    TerminalStateConsistencyRecord(
        state_value=CanonicalTerminalState.timed_out.value,
        present_in_shared_schema=False,
        present_in_execution_phase=True,
        present_in_handoff_contract=False,
        android_variant="timeout / timed_out",
        consistency_note=(
            "Present in DelegatedExecutionPhase but NOT in "
            "shared_schema._VALID_TERMINAL_STATES.  The result-merge layer "
            "uses 'timeout' (without underscore) as a variant.  This is a "
            "known inconsistency: 'timed_out' should be added to the shared "
            "schema vocabulary."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Delegated execution status catalogue
# ---------------------------------------------------------------------------

_DELEGATED_EXECUTION_STATUS_CATALOGUE: Tuple[DelegatedExecutionStatusRecord, ...] = (
    DelegatedExecutionStatusRecord(
        phase_value="pending_ack",
        is_terminal=False,
        android_signal_kind="",
        notes="Initial phase after handoff dispatch; no Android signal yet received.",
    ),
    DelegatedExecutionStatusRecord(
        phase_value="acknowledged",
        is_terminal=False,
        android_signal_kind="ack",
        notes="Android surface confirmed receipt; advances from pending_ack.",
    ),
    DelegatedExecutionStatusRecord(
        phase_value="in_progress",
        is_terminal=False,
        android_signal_kind="progress / partial_result",
        notes="Android surface reported execution is underway.",
    ),
    DelegatedExecutionStatusRecord(
        phase_value="completed",
        is_terminal=True,
        android_signal_kind="final_result",
        notes=(
            "Android surface reported successful completion.  Final result "
            "reconciled into DelegatedExecutionResult with success=True."
        ),
    ),
    DelegatedExecutionStatusRecord(
        phase_value="failed",
        is_terminal=True,
        android_signal_kind="error",
        notes=(
            "Android surface reported error or host detected failure.  "
            "DelegatedExecutionResult has success=False."
        ),
    ),
    DelegatedExecutionStatusRecord(
        phase_value="timed_out",
        is_terminal=True,
        android_signal_kind="timeout",
        notes=(
            "No acknowledgment or progress within allowed window.  "
            "Android-side 'timeout' signal maps to this terminal phase."
        ),
    ),
    DelegatedExecutionStatusRecord(
        phase_value="cancelled",
        is_terminal=True,
        android_signal_kind="cancelled",
        notes=(
            "Explicitly cancelled by host or Android surface.  "
            "Both sides use 'cancelled' value."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Truth-event surface catalogue
# ---------------------------------------------------------------------------

_TRUTH_EVENT_SURFACE_CATALOGUE: Tuple[TruthEventSurfaceRecord, ...] = (
    TruthEventSurfaceRecord(
        event_type="ugcp.truth.session.recorded.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=("event_type", "trace_id", "task_id"),
        optional_payload_fields=(
            "control_session_id",
            "runtime_session_id",
            "payload",
        ),
        android_visible=False,
        notes=(
            "Session truth recorded event.  Center-side authority only; "
            "Android does not produce this event type."
        ),
    ),
    TruthEventSurfaceRecord(
        event_type="ugcp.truth.session.snapshot.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=("event_type",),
        optional_payload_fields=("trace_id", "task_id", "payload"),
        android_visible=False,
        notes="Session truth snapshot event.  Center-side authority only.",
    ),
    TruthEventSurfaceRecord(
        event_type="ugcp.task.lifecycle.transition.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=("event_type", "task_id"),
        optional_payload_fields=(
            "trace_id",
            "control_session_id",
            "runtime_session_id",
            "payload",
        ),
        android_visible=True,
        notes=(
            "Task lifecycle transition.  Android-visible: Android receives "
            "task state updates via this event type when participating in "
            "delegated execution."
        ),
    ),
    TruthEventSurfaceRecord(
        event_type="ugcp.runtime.lifecycle.transition.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=("event_type",),
        optional_payload_fields=(
            "trace_id",
            "task_id",
            "runtime_session_id",
            "payload",
        ),
        android_visible=True,
        notes=(
            "Runtime lifecycle transition.  Android-visible: Android runtime "
            "host receives runtime lifecycle events."
        ),
    ),
    TruthEventSurfaceRecord(
        event_type="ugcp.control_transfer.transition.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=(
            "event_type",
            "profile",
            "family",
            "current_state",
        ),
        optional_payload_fields=(
            "trace_id",
            "task_id",
            "control_session_id",
            "runtime_session_id",
            "previous_state",
            "is_terminal",
            "terminal_reason",
            "source_contract",
            "metadata",
        ),
        android_visible=True,
        notes=(
            "Control transfer transition.  Android-visible: Android receives "
            "handoff/takeover/delegated state transitions."
        ),
    ),
    TruthEventSurfaceRecord(
        event_type="ugcp.coordination.transition.v1",
        surface_class=ProtocolSurfaceClass.canonical,
        required_payload_fields=("event_type",),
        optional_payload_fields=(
            "trace_id",
            "task_id",
            "runtime_session_id",
            "mesh_session_id",
            "payload",
        ),
        android_visible=True,
        notes=(
            "Coordination transition.  Android-visible: Android mesh "
            "participants receive coordination state events."
        ),
    ),
)

# ---------------------------------------------------------------------------
# Transitional allowance catalogue
# ---------------------------------------------------------------------------

_TRANSITIONAL_ALLOWANCE_CATALOGUE: Tuple[TransitionalAllowanceRecord, ...] = (
    TransitionalAllowanceRecord(
        allowance_id="session_id_to_control_session_id",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="session_id",
        center_canonical_value="control_session_id",
        normalisation_location=(
            "core.schemas.ugcp.shared.normalize_conversation_session_id"
        ),
        retirement_condition=(
            "Android side migrates to explicit control_session_id field, "
            "retiring bare session_id usage."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="runtime_session_id_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="runtime_session_id",
        center_canonical_value="runtime_attachment_session_id",
        normalisation_location=(
            "core.schemas.ugcp.shared.normalize_runtime_attachment_session_id"
        ),
        retirement_condition=(
            "Android side migrates to explicit runtime_attachment_session_id "
            "field, retiring runtime_session_id alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="attached_session_id_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="attached_session_id",
        center_canonical_value="runtime_attachment_session_id",
        normalisation_location=(
            "core.schemas.ugcp.shared.normalize_runtime_attachment_session_id"
        ),
        retirement_condition=(
            "Android side migrates to explicit runtime_attachment_session_id "
            "field, retiring attached_session_id alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="transfer_session_id_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="transfer_session_id",
        center_canonical_value="delegation_transfer_session_id",
        normalisation_location=(
            "core.schemas.ugcp.shared.normalize_delegation_transfer_session_id"
        ),
        retirement_condition=(
            "Android side migrates to explicit delegation_transfer_session_id "
            "field, retiring transfer_session_id alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="handoff_session_id_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="handoff_session_id",
        center_canonical_value="delegation_transfer_session_id",
        normalisation_location=(
            "core.schemas.ugcp.shared.normalize_delegation_transfer_session_id"
        ),
        retirement_condition=(
            "Android side migrates to explicit delegation_transfer_session_id "
            "field, retiring handoff_session_id alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="device_status_message_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="device_status",
        center_canonical_value="heartbeat",
        normalisation_location="galaxy_gateway.android.runtime_ws_profile",
        retirement_condition=(
            "Android side migrates to canonical 'heartbeat' message type, "
            "retiring device_status alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="agent_status_message_alias",
        kind=TransitionalAllowanceKind.field_rename,
        android_side_value="agent_status",
        center_canonical_value="heartbeat",
        normalisation_location="galaxy_gateway.android.runtime_ws_profile",
        retirement_condition=(
            "Android side migrates to canonical 'heartbeat' message type, "
            "retiring agent_status alias."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="timeout_to_timed_out",
        kind=TransitionalAllowanceKind.enum_variant,
        android_side_value="timeout",
        center_canonical_value="timed_out",
        normalisation_location="cross-runtime result merge boundary",
        retirement_condition=(
            "Unify 'timeout' variant in result-merge layer to 'timed_out' "
            "to eliminate this normalisation requirement."
        ),
    ),
    TransitionalAllowanceRecord(
        allowance_id="coordination_role_semantic_approximation",
        kind=TransitionalAllowanceKind.semantic_approximation,
        android_side_value="Android participant role (registration metadata)",
        center_canonical_value="core.schemas.ugcp.shared.CoordinationRole",
        normalisation_location="android_bridge.registration_handler",
        retirement_condition=(
            "Full enum-level unification of coordination_role between "
            "repositories."
        ),
    ),
)


# ---------------------------------------------------------------------------
# Public catalogue accessors
# ---------------------------------------------------------------------------


def get_protocol_surface_catalogue() -> Sequence[ProtocolSurfaceRecord]:
    """Return the full cross-repository protocol surface catalogue."""
    return _PROTOCOL_SURFACE_CATALOGUE


def get_terminal_state_consistency_catalogue() -> (
    Sequence[TerminalStateConsistencyRecord]
):
    """Return the terminal state cross-module consistency catalogue."""
    return _TERMINAL_STATE_CONSISTENCY_CATALOGUE


def get_delegated_execution_status_catalogue() -> (
    Sequence[DelegatedExecutionStatusRecord]
):
    """Return the delegated execution lifecycle status catalogue."""
    return _DELEGATED_EXECUTION_STATUS_CATALOGUE


def get_truth_event_surface_catalogue() -> Sequence[TruthEventSurfaceRecord]:
    """Return the truth-event surface catalogue."""
    return _TRUTH_EVENT_SURFACE_CATALOGUE


def get_transitional_allowance_catalogue() -> Sequence[TransitionalAllowanceRecord]:
    """Return the explicit transitional compatibility allowance catalogue."""
    return _TRANSITIONAL_ALLOWANCE_CATALOGUE


def classify_protocol_surface(
    surface_id: str,
) -> Optional[ProtocolSurfaceRecord]:
    """Return the ProtocolSurfaceRecord for *surface_id*, or None if not found."""
    for record in _PROTOCOL_SURFACE_CATALOGUE:
        if record.surface_id == surface_id:
            return record
    return None


def is_canonical_surface(surface_id: str) -> bool:
    """Return True iff the surface with *surface_id* is classified as canonical."""
    record = classify_protocol_surface(surface_id)
    return record is not None and record.surface_class == ProtocolSurfaceClass.canonical


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def build_protocol_consistency_snapshot() -> ProtocolConsistencySnapshot:
    """Assemble a point-in-time ProtocolConsistencySnapshot.

    The snapshot is a machine-readable summary of the cross-repository
    protocol consistency catalogue, suitable for use in CI checks or
    observability dashboards.

    Returns
    -------
    ProtocolConsistencySnapshot
        Snapshot with counts and metadata.
    """
    surfaces = _PROTOCOL_SURFACE_CATALOGUE
    terminal_states = _TERMINAL_STATE_CONSISTENCY_CATALOGUE
    exec_statuses = _DELEGATED_EXECUTION_STATUS_CATALOGUE
    truth_events = _TRUTH_EVENT_SURFACE_CATALOGUE
    allowances = _TRANSITIONAL_ALLOWANCE_CATALOGUE

    canonical_count = sum(
        1 for s in surfaces if s.surface_class == ProtocolSurfaceClass.canonical
    )
    transitional_count = sum(
        1 for s in surfaces if s.surface_class == ProtocolSurfaceClass.transitional
    )
    deprecated_count = sum(
        1 for s in surfaces if s.surface_class == ProtocolSurfaceClass.deprecated
    )
    unresolved_count = sum(
        1 for s in surfaces if s.surface_class == ProtocolSurfaceClass.unresolved
    )
    fully_consistent = sum(1 for t in terminal_states if t.is_fully_consistent)
    terminal_phases = sum(1 for e in exec_statuses if e.is_terminal)

    return ProtocolConsistencySnapshot(
        generated_at=time.time(),
        protocol_surface_count=len(surfaces),
        canonical_surface_count=canonical_count,
        transitional_surface_count=transitional_count,
        deprecated_surface_count=deprecated_count,
        unresolved_surface_count=unresolved_count,
        terminal_state_count=len(terminal_states),
        fully_consistent_terminal_states=fully_consistent,
        delegated_execution_phase_count=len(exec_statuses),
        terminal_execution_phase_count=terminal_phases,
        truth_event_type_count=len(truth_events),
        transitional_allowance_count=len(allowances),
    )
