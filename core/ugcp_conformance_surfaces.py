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

UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL: str = (
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL::package=8::"
    "profile=ugcp-conformance-surfaces-v1::module=core.ugcp_conformance_surfaces"
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


def _normalize_text(value: Any) -> str:
    """Lowercase and strip leading/trailing whitespace for classification.

    Non-string values intentionally normalize to an empty string so this module
    can remain non-breaking for mixed payloads while still classifying such
    values as unknown later in the pipeline.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return ""


def get_ugcp_conformance_surface_catalog() -> Dict[str, Dict[str, Any]]:
    """Return a machine-reviewable conformance surface catalog."""
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
    """Classify one conformance surface value.

    Args:
        surface: Conformance surface enum or surface name string.
        value: Raw incoming semantic value for the surface.

    Returns:
        UGCPConformanceClassification with normalized canonical value when
        possible, semantic class, and optional compatibility pathway metadata.

    Notes:
        Invalid/unknown surface names are treated as unknown and marked with
        ``compatibility_pathway="invalid_surface"``.
    """
    raw_surface = surface.value if isinstance(surface, UGCPConformanceSurface) else str(surface).strip().lower()
    normalized_input = _normalize_text(value)
    try:
        parsed_surface = UGCPConformanceSurface(raw_surface)
    except ValueError:
        # Keep this fallback non-breaking by preserving the enum type while
        # explicitly marking the classification with invalid_surface pathway.
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
    """Normalize a mixed canonical/compat payload into PR-8 conformance surfaces.

    Recognized keys:
      - schema_kind
      - lifecycle_state
      - authority_source
      - transfer_state
      - coordination_state
      - truth_event_type

    Returns:
      - normalized canonical values for the six keys above
      - semantic_classes: per-surface canonical/transitional/unknown class
      - compatibility_pathways: only populated for transitional mappings
    """
    schema = classify_surface_semantics(UGCPConformanceSurface.schema, payload.get("schema_kind"))
    lifecycle = classify_surface_semantics(UGCPConformanceSurface.lifecycle, payload.get("lifecycle_state"))
    authority = classify_surface_semantics(UGCPConformanceSurface.authority, payload.get("authority_source"))
    transfer = classify_surface_semantics(UGCPConformanceSurface.transfer, payload.get("transfer_state"))
    coordination = classify_surface_semantics(UGCPConformanceSurface.coordination, payload.get("coordination_state"))
    truth_event = classify_surface_semantics(UGCPConformanceSurface.truth_event, payload.get("truth_event_type"))

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
    }


def build_conformance_invariant_report(payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build reviewable cross-profile conformance invariants."""
    normalized = normalize_conformance_payload(payload or {})
    semantic_classes = normalized["semantic_classes"]
    invariants = {
        "truth_event_is_canonical": semantic_classes["truth_event"] == UGCPSemanticClass.canonical.value,
        "authority_source_not_compat_alias": semantic_classes["authority"] != UGCPSemanticClass.transitional.value,
        "transfer_state_known": semantic_classes["transfer"] != UGCPSemanticClass.unknown.value,
        "coordination_state_known": semantic_classes["coordination"] != UGCPSemanticClass.unknown.value,
        "lifecycle_state_known": semantic_classes["lifecycle"] != UGCPSemanticClass.unknown.value,
    }
    failed_invariants: List[str] = [
        name for name, passed in invariants.items() if not passed
    ]
    return {
        "conforms": not failed_invariants,
        "invariants": invariants,
        "violations": failed_invariants,
        "normalized": normalized,
    }


__all__ = [
    "UGCP_CONFORMANCE_SURFACES_AUTHORITY",
    "CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY",
    "NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY",
    "CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY",
    "COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY",
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL",
    "UGCPConformanceSurface",
    "UGCPSemanticClass",
    "UGCPConformanceSurfaceDefinition",
    "UGCPConformanceClassification",
    "get_ugcp_conformance_surface_catalog",
    "classify_surface_semantics",
    "normalize_conformance_payload",
    "build_conformance_invariant_report",
]
