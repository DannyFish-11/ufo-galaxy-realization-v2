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

PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED: "
    "Adjacent lifecycle/transfer/coordination semantics should compose into one "
    "stable canonical lifecycle backbone without forcing broad strict breakage."
)

UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL: str = (
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL::package=8::"
    "profile=ugcp-conformance-surfaces-v1::module=core.ugcp_conformance_surfaces"
)

UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL: str = (
    "UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL::package=9::"
    "profile=ugcp-conformance-backbone-v1::module=core.ugcp_conformance_surfaces"
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

_SURFACE_CANONICAL_VALUES: Dict[UGCPConformanceSurface, Optional[set[str]]] = {
    UGCPConformanceSurface.schema: _SCHEMA_CANONICAL_VALUES,
    UGCPConformanceSurface.lifecycle: _LIFECYCLE_CANONICAL_VALUES,
    UGCPConformanceSurface.authority: _AUTHORITY_CANONICAL_VALUES,
    UGCPConformanceSurface.transfer: _TRANSFER_CANONICAL_VALUES,
    UGCPConformanceSurface.coordination: _COORDINATION_CANONICAL_VALUES,
    # truth-event canonical values are sourced from truth/event authority at runtime
    UGCPConformanceSurface.truth_event: None,
}

_SURFACE_TRANSITIONAL_ALIASES: Dict[UGCPConformanceSurface, Dict[str, str]] = {
    UGCPConformanceSurface.schema: _SCHEMA_TRANSITIONAL_ALIASES,
    UGCPConformanceSurface.lifecycle: _LIFECYCLE_TRANSITIONAL_ALIASES,
    UGCPConformanceSurface.authority: _AUTHORITY_TRANSITIONAL_ALIASES,
    UGCPConformanceSurface.transfer: _TRANSFER_TRANSITIONAL_ALIASES,
    UGCPConformanceSurface.coordination: _COORDINATION_TRANSITIONAL_ALIASES,
    UGCPConformanceSurface.truth_event: _TRUTH_EVENT_TRANSITIONAL_ALIASES,
}

_LIFECYCLE_COMPOSITION_ORDER = (
    ("lifecycle", "lifecycle_state"),
    ("transfer", "transfer_state"),
    ("coordination", "coordination_state"),
)

_HARDENING_PATHWAY_SUFFIX = "_transitional_pathway"


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    return ""


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

    canonical_values = _SURFACE_CANONICAL_VALUES.get(parsed_surface)
    if canonical_values is None and parsed_surface == UGCPConformanceSurface.truth_event:
        canonical_values = get_canonical_transition_event_types()

    if canonical_values and normalized_input in canonical_values:
        return UGCPConformanceClassification(parsed_surface, value, normalized_input, UGCPSemanticClass.canonical)

    mapped = _SURFACE_TRANSITIONAL_ALIASES.get(parsed_surface, {}).get(normalized_input)
    if mapped:
        return UGCPConformanceClassification(
            parsed_surface,
            value,
            mapped,
            UGCPSemanticClass.transitional,
            compatibility_pathway=f"{parsed_surface.value}_alias:{normalized_input}->{mapped}",
        )

    return UGCPConformanceClassification(
        surface=parsed_surface,
        raw_value=value,
        normalized_value="unknown",
        semantic_class=UGCPSemanticClass.unknown,
    )


def normalize_conformance_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a mixed canonical/compat payload into canonical PR-8 surfaces."""
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


def normalize_conformance_backbone(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize conformance payload and compose a stable cross-profile backbone."""
    normalized = normalize_conformance_payload(payload)
    semantic_classes = normalized["semantic_classes"]

    composed_lifecycle_state = "unknown"
    lifecycle_source_surface = "none"
    for source_surface, field_name in _LIFECYCLE_COMPOSITION_ORDER:
        candidate_state = str(normalized.get(field_name, "unknown"))
        if candidate_state and candidate_state != "unknown":
            composed_lifecycle_state = candidate_state
            lifecycle_source_surface = source_surface
            break

    semantic_drift_signals: List[str] = []
    lifecycle_state = str(normalized.get("lifecycle_state", "unknown"))
    transfer_state = str(normalized.get("transfer_state", "unknown"))
    coordination_state = str(normalized.get("coordination_state", "unknown"))

    if (
        lifecycle_state not in {"", "unknown"}
        and transfer_state not in {"", "unknown"}
        and lifecycle_state != transfer_state
    ):
        semantic_drift_signals.append("lifecycle_transfer_divergence")
    if (
        lifecycle_state not in {"", "unknown"}
        and coordination_state not in {"", "unknown"}
        and lifecycle_state != coordination_state
    ):
        semantic_drift_signals.append("lifecycle_coordination_divergence")

    hardening_pathways = [
        f"{surface}{_HARDENING_PATHWAY_SUFFIX}"
        for surface, semantic_class in semantic_classes.items()
        if semantic_class == UGCPSemanticClass.transitional.value
    ]

    return {
        **normalized,
        "composed_lifecycle_state": composed_lifecycle_state,
        "lifecycle_source_surface": lifecycle_source_surface,
        "semantic_drift_signals": semantic_drift_signals,
        "hardening_pathways": hardening_pathways,
    }


def build_conformance_invariant_report(payload: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """Build reviewable cross-profile conformance invariants."""
    normalized = normalize_conformance_backbone(payload or {})
    semantic_classes = normalized["semantic_classes"]
    invariants = {
        "truth_event_is_canonical": semantic_classes["truth_event"] == UGCPSemanticClass.canonical.value,
        "authority_source_not_compat_alias": semantic_classes["authority"] != UGCPSemanticClass.transitional.value,
        "transfer_state_known": semantic_classes["transfer"] != UGCPSemanticClass.unknown.value,
        "coordination_state_known": semantic_classes["coordination"] != UGCPSemanticClass.unknown.value,
        "lifecycle_state_known": semantic_classes["lifecycle"] != UGCPSemanticClass.unknown.value,
        "composed_lifecycle_state_known": normalized["composed_lifecycle_state"] != "unknown",
        "semantic_drift_signals_empty": not normalized["semantic_drift_signals"],
    }
    violations: List[str] = [
        name for name, passed in invariants.items() if not passed
    ]
    return {
        "conforms": not violations,
        "invariants": invariants,
        "violations": violations,
        "normalized": normalized,
    }


__all__ = [
    "UGCP_CONFORMANCE_SURFACES_AUTHORITY",
    "CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY",
    "NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY",
    "CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY",
    "COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY",
    "PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED_POLICY",
    "UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL",
    "UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL",
    "UGCPConformanceSurface",
    "UGCPSemanticClass",
    "UGCPConformanceSurfaceDefinition",
    "UGCPConformanceClassification",
    "get_ugcp_conformance_surface_catalog",
    "classify_surface_semantics",
    "normalize_conformance_payload",
    "normalize_conformance_backbone",
    "build_conformance_invariant_report",
]
