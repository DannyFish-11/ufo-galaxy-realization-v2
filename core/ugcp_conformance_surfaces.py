"""core/ugcp_conformance_surfaces.py
=====================================
UGCP Conformance Surfaces v1 (realization-v2 side, PR-8 scope).

This module adds bounded conformance scaffolding for distinguishing canonical
vs transitional semantics across schema, lifecycle, authority, transfer,
coordination, and truth/event surfaces.

It is intentionally incremental: compatibility pathways are still tolerated and
normalized, but are explicitly classified to support safer retirement later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Sequence

from core.schemas.ugcp.shared import UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY
from core.ugcp_control_transfer_profile import UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY
from core.ugcp_coordination_profile import UGCP_COORDINATION_PROFILE_AUTHORITY
from core.ugcp_truth_event_model import (
    UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
    CanonicalTruthEventType,
    get_canonical_transition_event_types,
)

UGCP_CONFORMANCE_SURFACES_AUTHORITY: str = (
    "UGCP_CONFORMANCE_SURFACES_AUTHORITY::"
    "core.ugcp_conformance_surfaces is the canonical conformance scaffold "
    "authority for classifying canonical vs transitional UGCP semantics in "
    "realization-v2."
)

CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::CANONICAL_VS_TRANSITIONAL_CLASSIFICATION: "
    "Conformance surfaces must classify semantics explicitly as canonical, "
    "transitional, or unknown before downstream enforcement or retirement."
)

NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::NORMALIZATION_BOUNDARY_IS_EXPLICIT: "
    "Legacy/transitional inputs may be normalized to canonical values, but "
    "normalization must annotate compatibility pathways."
)

CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE: "
    "Schema/lifecycle/authority/transfer/coordination/truth-event conformance "
    "checks should produce explicit invariant reports."
)

COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE: "
    "Compatibility pathways remain tolerated by default in PR-8 but are "
    "explicitly identified for staged retirement."
)

PROFILE_NORMALIZATION_BOUNDARY_ALIGNMENT_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::PROFILE_NORMALIZATION_BOUNDARY_ALIGNMENT: "
    "Conformance normalization should absorb profile-adjacent transitional input "
    "keys into canonical surface fields while retaining source-path visibility."
)

PROTOCOL_HARDENING_WITHOUT_STRICT_BREAKAGE_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::PROTOCOL_HARDENING_WITHOUT_STRICT_BREAKAGE: "
    "Cross-profile hardening adds reviewable invariants and seam diagnostics "
    "without forcing unsafe strict-mode breakage."
)

UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL: str = (
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL::package=8::"
    "profile=ugcp-conformance-surfaces-v1::module=core.ugcp_conformance_surfaces"
)

UGCP_CONFORMANCE_HARDENING_PR9_SENTINEL: str = (
    "UGCP_CONFORMANCE_HARDENING_PR9_SENTINEL::package=9::"
    "profile=ugcp-protocol-hardening-profile-normalization-v1::"
    "module=core.ugcp_conformance_surfaces"
)


class UGCPConformanceSurface(str, Enum):
    schema = "schema"
    lifecycle = "lifecycle"
    authority = "authority"
    transfer = "transfer"
    coordination = "coordination"
    truth_event = "truth_event"


class UGCPSemanticClass(str, Enum):
    canonical = "canonical"
    transitional = "transitional"
    unknown = "unknown"


@dataclass(frozen=True)
class UGCPConformanceSurfaceDefinition:
    surface: UGCPConformanceSurface
    canonical_authority: str
    canonical_contract: str
    tolerated_transitional_aliases: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class UGCPConformanceClassification:
    surface: UGCPConformanceSurface
    raw_value: Any
    normalized_value: str
    semantic_class: UGCPSemanticClass
    compatibility_pathway: str = ""


_SURFACE_DEFINITIONS: Dict[UGCPConformanceSurface, UGCPConformanceSurfaceDefinition] = {
    UGCPConformanceSurface.schema: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.schema,
        canonical_authority=UGCP_SHARED_SCHEMA_FAMILY_AUTHORITY,
        canonical_contract="core.schemas.ugcp.shared canonical objects",
        tolerated_transitional_aliases=("message_interop_payload", "legacy_message_payload"),
    ),
    UGCPConformanceSurface.lifecycle: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.lifecycle,
        canonical_authority=UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
        canonical_contract="shared terminal/lifecycle semantics used by UGCP profiles",
        tolerated_transitional_aliases=("done", "ok", "error", "cancelled_by_policy", "waiting"),
    ),
    UGCPConformanceSurface.authority: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.authority,
        canonical_authority=UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
        canonical_contract="canonical authority chain truth source labels",
        tolerated_transitional_aliases=("projection", "interop", "legacy_bridge", "compat"),
    ),
    UGCPConformanceSurface.transfer: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.transfer,
        canonical_authority=UGCP_CONTROL_TRANSFER_PROFILE_AUTHORITY,
        canonical_contract="ControlTransferState canonical lifecycle",
        tolerated_transitional_aliases=("draft", "sealed", "pending", "executing", "succeeded", "blocked"),
    ),
    UGCPConformanceSurface.coordination: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.coordination,
        canonical_authority=UGCP_COORDINATION_PROFILE_AUTHORITY,
        canonical_contract="CoordinationLifecycleState canonical lifecycle",
        tolerated_transitional_aliases=("waiting", "cancelled_by_policy"),
    ),
    UGCPConformanceSurface.truth_event: UGCPConformanceSurfaceDefinition(
        surface=UGCPConformanceSurface.truth_event,
        canonical_authority=UGCP_TRUTH_EVENT_MODEL_AUTHORITY,
        canonical_contract="CanonicalTruthEventType transition vocabulary",
        tolerated_transitional_aliases=(
            "session_truth_written",
            "runtime_state_transition",
            "transfer_state_transition",
            "mesh_coordination_transition",
        ),
    ),
}

_SCHEMA_CANONICAL_VALUES = {
    "task_envelope",
    "dispatch_decision",
    "handoff_request",
    "runtime_truth",
    "session_truth",
    "truth_event",
}
_SCHEMA_TRANSITIONAL_ALIASES = {
    "message_interop_payload": "task_envelope",
    "legacy_message_payload": "task_envelope",
}

_LIFECYCLE_CANONICAL_VALUES = {
    "completed",
    "failed",
    "partial",
    "interrupted",
    "pending",
    "active",
    "awaiting_barrier",
    "merging",
    "cancelled",
    "timed_out",
    "not_started",
    "preparing",
    "ready",
    "dispatched",
    "adopting",
    "resumed",
    "in_progress",
    "rejected",
    "expired",
    "unknown",
}
_LIFECYCLE_TRANSITIONAL_ALIASES = {
    "done": "completed",
    "ok": "completed",
    "error": "failed",
    "waiting": "awaiting_barrier",
    "cancelled_by_policy": "cancelled",
}

_AUTHORITY_CANONICAL_VALUES = {
    "canonical_session_truth",
    "ugcp_truth_event_model",
    "ugcp_control_transfer_profile",
    "ugcp_coordination_profile",
    "ugcp_shared_schema_family",
    "unknown",
}
_AUTHORITY_TRANSITIONAL_ALIASES = {
    "projection": "unknown",
    "interop": "unknown",
    "legacy_bridge": "unknown",
    "compat": "unknown",
}

_TRANSFER_CANONICAL_VALUES = {
    "not_started",
    "preparing",
    "ready",
    "dispatched",
    "adopting",
    "resumed",
    "in_progress",
    "completed",
    "rejected",
    "cancelled",
    "expired",
    "failed",
    "timed_out",
    "unknown",
}
_TRANSFER_TRANSITIONAL_ALIASES = {
    "draft": "preparing",
    "sealed": "ready",
    "pending": "adopting",
    "executing": "in_progress",
    "succeeded": "completed",
    "blocked": "rejected",
}

_COORDINATION_CANONICAL_VALUES = {
    "pending",
    "active",
    "awaiting_barrier",
    "merging",
    "completed",
    "partial",
    "failed",
    "cancelled",
    "timed_out",
    "unknown",
}
_COORDINATION_TRANSITIONAL_ALIASES = {
    "waiting": "awaiting_barrier",
    "cancelled_by_policy": "cancelled",
}

_TRUTH_EVENT_TRANSITIONAL_ALIASES = {
    "session_truth_written": CanonicalTruthEventType.session_truth_recorded.value,
    "runtime_state_transition": CanonicalTruthEventType.runtime_lifecycle_transition.value,
    "transfer_state_transition": CanonicalTruthEventType.control_transfer_transition.value,
    "mesh_coordination_transition": CanonicalTruthEventType.coordination_transition.value,
}

_SURFACE_INPUT_KEY_ALIASES: Dict[UGCPConformanceSurface, Sequence[str]] = {
    UGCPConformanceSurface.schema: ("schema_kind", "schema", "schema_type", "message_schema"),
    UGCPConformanceSurface.lifecycle: ("lifecycle_state", "state", "runtime_state", "status"),
    UGCPConformanceSurface.authority: ("authority_source", "truth_source", "authority", "source"),
    UGCPConformanceSurface.transfer: (
        "transfer_state",
        "control_transfer_state",
        "handoff_state",
        "transfer_status",
    ),
    UGCPConformanceSurface.coordination: ("coordination_state", "mesh_state", "coordination_status"),
    UGCPConformanceSurface.truth_event: ("truth_event_type", "truth_event", "event_type", "event_name"),
}

_TERMINAL_LIFECYCLE_STATES = {"completed", "failed", "partial", "interrupted", "cancelled", "timed_out"}
_TERMINAL_TRANSFER_STATES = {"completed", "rejected", "cancelled", "expired", "failed", "timed_out"}
_TERMINAL_COORDINATION_STATES = {"completed", "partial", "failed", "cancelled", "timed_out"}
_LIFECYCLE_TRANSFER_CONFLICTS = {
    ("completed", "failed"),
    ("completed", "cancelled"),
    ("completed", "rejected"),
    ("failed", "completed"),
    ("cancelled", "completed"),
    ("timed_out", "completed"),
}
_LIFECYCLE_COORDINATION_CONFLICTS = {
    ("completed", "failed"),
    ("completed", "cancelled"),
    ("failed", "completed"),
    ("cancelled", "completed"),
    ("timed_out", "completed"),
}


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    return ""


def _pick_surface_input(
    payload: Mapping[str, Any],
    surface: UGCPConformanceSurface,
) -> tuple[Any, str]:
    keys = _SURFACE_INPUT_KEY_ALIASES[surface]
    canonical_key = keys[0]
    for key in keys:
        if key in payload:
            return payload.get(key), key
    return None, canonical_key


def get_ugcp_conformance_surface_catalog() -> Dict[str, Dict[str, Any]]:
    """Return a machine-reviewable conformance surface catalogue."""
    return {
        surface.value: {
            "surface": definition.surface.value,
            "canonical_authority": definition.canonical_authority,
            "canonical_contract": definition.canonical_contract,
            "tolerated_transitional_aliases": list(definition.tolerated_transitional_aliases),
        }
        for surface, definition in _SURFACE_DEFINITIONS.items()
    }


def classify_surface_semantics(
    surface: UGCPConformanceSurface | str,
    value: Any,
) -> UGCPConformanceClassification:
    """Classify a surface value as canonical/transitional/unknown."""
    raw_surface = surface.value if isinstance(surface, UGCPConformanceSurface) else str(surface).strip().lower()
    normalized_input = _normalize_text(value)
    try:
        parsed_surface = UGCPConformanceSurface(raw_surface)
    except ValueError:
        return UGCPConformanceClassification(
            surface=UGCPConformanceSurface.schema,
            raw_value=value,
            normalized_value=normalized_input or "unknown",
            semantic_class=UGCPSemanticClass.unknown,
            compatibility_pathway="invalid_surface",
        )

    if parsed_surface == UGCPConformanceSurface.schema:
        if normalized_input in _SCHEMA_CANONICAL_VALUES:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _SCHEMA_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"schema_alias:{normalized_input}->{mapped}",
            )

    elif parsed_surface == UGCPConformanceSurface.lifecycle:
        if normalized_input in _LIFECYCLE_CANONICAL_VALUES:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _LIFECYCLE_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"lifecycle_alias:{normalized_input}->{mapped}",
            )

    elif parsed_surface == UGCPConformanceSurface.authority:
        if normalized_input in _AUTHORITY_CANONICAL_VALUES:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _AUTHORITY_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"authority_alias:{normalized_input}->{mapped}",
            )

    elif parsed_surface == UGCPConformanceSurface.transfer:
        if normalized_input in _TRANSFER_CANONICAL_VALUES:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _TRANSFER_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"transfer_alias:{normalized_input}->{mapped}",
            )

    elif parsed_surface == UGCPConformanceSurface.coordination:
        if normalized_input in _COORDINATION_CANONICAL_VALUES:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _COORDINATION_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"coordination_alias:{normalized_input}->{mapped}",
            )

    elif parsed_surface == UGCPConformanceSurface.truth_event:
        canonical_event_types = get_canonical_transition_event_types()
        if normalized_input in canonical_event_types:
            return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)
        mapped = _TRUTH_EVENT_TRANSITIONAL_ALIASES.get(normalized_input)
        if mapped:
            return UGCPConformanceClassification(
                parsed_surface,
                value,
                mapped,
                UGCPSemanticClass.transitional,
                compatibility_pathway=f"truth_event_alias:{normalized_input}->{mapped}",
            )

    return UGCPConformanceClassification(
        surface=parsed_surface,
        raw_value=value,
        normalized_value="unknown",
        semantic_class=UGCPSemanticClass.unknown,
    )


def normalize_conformance_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a mixed canonical/compat payload into canonical PR-8 surfaces."""
    schema_input, schema_source_key = _pick_surface_input(payload, UGCPConformanceSurface.schema)
    lifecycle_input, lifecycle_source_key = _pick_surface_input(payload, UGCPConformanceSurface.lifecycle)
    authority_input, authority_source_key = _pick_surface_input(payload, UGCPConformanceSurface.authority)
    transfer_input, transfer_source_key = _pick_surface_input(payload, UGCPConformanceSurface.transfer)
    coordination_input, coordination_source_key = _pick_surface_input(payload, UGCPConformanceSurface.coordination)
    truth_event_input, truth_event_source_key = _pick_surface_input(payload, UGCPConformanceSurface.truth_event)

    schema = classify_surface_semantics(UGCPConformanceSurface.schema, schema_input)
    lifecycle = classify_surface_semantics(UGCPConformanceSurface.lifecycle, lifecycle_input)
    authority = classify_surface_semantics(UGCPConformanceSurface.authority, authority_input)
    transfer = classify_surface_semantics(UGCPConformanceSurface.transfer, transfer_input)
    coordination = classify_surface_semantics(UGCPConformanceSurface.coordination, coordination_input)
    truth_event = classify_surface_semantics(UGCPConformanceSurface.truth_event, truth_event_input)

    classifications = {
        "schema": schema,
        "lifecycle": lifecycle,
        "authority": authority,
        "transfer": transfer,
        "coordination": coordination,
        "truth_event": truth_event,
    }
    return {
        "schema_kind": schema.normalized_value,
        "lifecycle_state": lifecycle.normalized_value,
        "authority_source": authority.normalized_value,
        "transfer_state": transfer.normalized_value,
        "coordination_state": coordination.normalized_value,
        "truth_event_type": truth_event.normalized_value,
        "semantic_classes": {key: item.semantic_class.value for key, item in classifications.items()},
        "compatibility_pathways": {
            key: item.compatibility_pathway
            for key, item in classifications.items()
            if item.compatibility_pathway
        },
        "normalization_input_sources": {
            "schema": schema_source_key,
            "lifecycle": lifecycle_source_key,
            "authority": authority_source_key,
            "transfer": transfer_source_key,
            "coordination": coordination_source_key,
            "truth_event": truth_event_source_key,
        },
    }


def build_conformance_invariant_report(payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build reviewable cross-profile conformance invariants."""
    normalized = normalize_conformance_payload(payload or {})
    semantic_classes = normalized["semantic_classes"]
    lifecycle_state = normalized["lifecycle_state"]
    transfer_state = normalized["transfer_state"]
    coordination_state = normalized["coordination_state"]
    truth_event_type = normalized["truth_event_type"]
    lifecycle_transfer_conflict = (lifecycle_state, transfer_state) in _LIFECYCLE_TRANSFER_CONFLICTS
    lifecycle_coordination_conflict = (lifecycle_state, coordination_state) in _LIFECYCLE_COORDINATION_CONFLICTS
    transfer_terminal_requires_terminal_lifecycle = (
        transfer_state not in _TERMINAL_TRANSFER_STATES
        or lifecycle_state in _TERMINAL_LIFECYCLE_STATES
        or transfer_state == "unknown"
        or lifecycle_state == "unknown"
    )
    coordination_terminal_requires_terminal_lifecycle = (
        coordination_state not in _TERMINAL_COORDINATION_STATES
        or lifecycle_state in _TERMINAL_LIFECYCLE_STATES
        or coordination_state == "unknown"
        or lifecycle_state == "unknown"
    )
    truth_event_transfer_alignment = (
        truth_event_type != CanonicalTruthEventType.control_transfer_transition.value
        or semantic_classes["transfer"] != UGCPSemanticClass.unknown.value
    )
    truth_event_coordination_alignment = (
        truth_event_type != CanonicalTruthEventType.coordination_transition.value
        or semantic_classes["coordination"] != UGCPSemanticClass.unknown.value
    )
    invariants = {
        "truth_event_is_canonical": semantic_classes["truth_event"] == UGCPSemanticClass.canonical.value,
        "authority_source_not_compat_alias": semantic_classes["authority"] != UGCPSemanticClass.transitional.value,
        "transfer_state_known": semantic_classes["transfer"] != UGCPSemanticClass.unknown.value,
        "coordination_state_known": semantic_classes["coordination"] != UGCPSemanticClass.unknown.value,
        "lifecycle_state_known": semantic_classes["lifecycle"] != UGCPSemanticClass.unknown.value,
        "lifecycle_transfer_not_conflicting": not lifecycle_transfer_conflict,
        "lifecycle_coordination_not_conflicting": not lifecycle_coordination_conflict,
        "transfer_terminal_requires_terminal_lifecycle": transfer_terminal_requires_terminal_lifecycle,
        "coordination_terminal_requires_terminal_lifecycle": coordination_terminal_requires_terminal_lifecycle,
        "truth_event_transfer_alignment": truth_event_transfer_alignment,
        "truth_event_coordination_alignment": truth_event_coordination_alignment,
    }
    violations: List[str] = [
        name for name, passed in invariants.items() if not passed
    ]
    transitional_seams: List[str] = [
        key
        for key, semantic_class in semantic_classes.items()
        if semantic_class in {UGCPSemanticClass.transitional.value, UGCPSemanticClass.unknown.value}
    ]
    return {
        "conforms": not violations,
        "invariants": invariants,
        "violations": violations,
        "transitional_seams": transitional_seams,
        "normalized": normalized,
    }


__all__ = [
    "UGCP_CONFORMANCE_SURFACES_AUTHORITY",
    "CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY",
    "NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY",
    "CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY",
    "COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY",
    "PROFILE_NORMALIZATION_BOUNDARY_ALIGNMENT_POLICY",
    "PROTOCOL_HARDENING_WITHOUT_STRICT_BREAKAGE_POLICY",
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL",
    "UGCP_CONFORMANCE_HARDENING_PR9_SENTINEL",
    "UGCPConformanceSurface",
    "UGCPSemanticClass",
    "UGCPConformanceSurfaceDefinition",
    "UGCPConformanceClassification",
    "get_ugcp_conformance_surface_catalog",
    "classify_surface_semantics",
    "normalize_conformance_payload",
    "build_conformance_invariant_report",
]
