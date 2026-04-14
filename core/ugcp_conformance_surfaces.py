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

import logging
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

_LOGGER = logging.getLogger(__name__)

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

UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL: str = (
    "UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL::package=10::"
    "profile=ugcp-enforcement-scaffold-v1::module=core.ugcp_conformance_surfaces"
)

UGCP_MIGRATION_READINESS_PR11_SENTINEL: str = (
    "UGCP_MIGRATION_READINESS_PR11_SENTINEL::package=11::"
    "profile=ugcp-migration-readiness-v1::module=core.ugcp_conformance_surfaces"
)

ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT: "
    "Canonical, transitional, and unknown semantics should map to explicit "
    "handling actions (accept/normalize-warn/tolerate-warn/reject)."
)

DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE: "
    "Deprecated alias and compatibility pathways should carry deprecation-stage "
    "markers to support progressive retirement planning."
)

PROGRESSIVE_STRICTNESS_IS_OPT_IN_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::PROGRESSIVE_STRICTNESS_IS_OPT_IN: "
    "Compatibility mode remains default; stricter reject behavior is surfaced as "
    "reviewable scaffold and activated only by explicit strict mode."
)

MIGRATION_READINESS_SURFACES_ARE_EXPLICIT_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::MIGRATION_READINESS_SURFACES_ARE_EXPLICIT: "
    "Canonical surfaces and transitional tolerance pathways should be exposed as "
    "reviewable migration-readiness data."
)

RETIREMENT_SEQUENCING_IS_STAGE_GATED_POLICY: str = (
    "UGCP_CONFORMANCE_POLICY::RETIREMENT_SEQUENCING_IS_STAGE_GATED: "
    "Retirement sequencing should remain stage-gated (observe/normalize, "
    "migrate-required aliases, strict-candidate gating) rather than abrupt "
    "global strict rollout."
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


class UGCPEnforcementMode(str, Enum):
    compatibility = "compatibility"
    review = "review"
    strict = "strict"


class UGCPEnforcementAction(str, Enum):
    accept = "accept"
    normalize_warn = "normalize_warn"
    tolerate_warn = "tolerate_warn"
    reject = "reject"


class UGCPDeprecationStage(str, Enum):
    not_deprecated = "not_deprecated"
    transitional_tolerated = "transitional_tolerated"
    migration_required = "migration_required"
    strict_reject_candidate = "strict_reject_candidate"


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


@dataclass(frozen=True)
class UGCPEnforcementDecision:
    surface: UGCPConformanceSurface
    input_value: Any
    normalized_value: str
    semantic_class: UGCPSemanticClass
    action: UGCPEnforcementAction
    deprecation_stage: UGCPDeprecationStage
    reject_in_mode: bool
    warning: str = ""
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

# Deprecation-stage rubric:
# - migration_required: normalize now, keep compatibility behavior, and migrate callers.
# - transitional_tolerated: allowed short-term while adjacent profile/state alignment lands.
# - strict_reject_candidate: compatibility is still present, but pathway is explicitly marked
#   as a candidate for future strict-mode rejection once rollout gates are ready.
_SURFACE_ALIAS_DEPRECATION_STAGE: Dict[UGCPConformanceSurface, Dict[str, UGCPDeprecationStage]] = {
    UGCPConformanceSurface.schema: {
        "message_interop_payload": UGCPDeprecationStage.migration_required,
        "legacy_message_payload": UGCPDeprecationStage.strict_reject_candidate,
    },
    UGCPConformanceSurface.lifecycle: {
        "done": UGCPDeprecationStage.migration_required,
        "ok": UGCPDeprecationStage.migration_required,
        "error": UGCPDeprecationStage.migration_required,
        "waiting": UGCPDeprecationStage.transitional_tolerated,
        "cancelled_by_policy": UGCPDeprecationStage.migration_required,
    },
    UGCPConformanceSurface.authority: {
        "projection": UGCPDeprecationStage.strict_reject_candidate,
        "interop": UGCPDeprecationStage.strict_reject_candidate,
        "legacy_bridge": UGCPDeprecationStage.strict_reject_candidate,
        "compat": UGCPDeprecationStage.strict_reject_candidate,
    },
    UGCPConformanceSurface.transfer: {
        "draft": UGCPDeprecationStage.migration_required,
        "sealed": UGCPDeprecationStage.migration_required,
        "pending": UGCPDeprecationStage.migration_required,
        "executing": UGCPDeprecationStage.migration_required,
        "succeeded": UGCPDeprecationStage.migration_required,
        "blocked": UGCPDeprecationStage.strict_reject_candidate,
    },
    UGCPConformanceSurface.coordination: {
        "waiting": UGCPDeprecationStage.migration_required,
        "cancelled_by_policy": UGCPDeprecationStage.migration_required,
    },
    UGCPConformanceSurface.truth_event: {
        "session_truth_written": UGCPDeprecationStage.migration_required,
        "runtime_state_transition": UGCPDeprecationStage.migration_required,
        "transfer_state_transition": UGCPDeprecationStage.migration_required,
        "mesh_coordination_transition": UGCPDeprecationStage.migration_required,
    },
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


def _resolve_alias_deprecation_stage(surface: UGCPConformanceSurface, raw_value: Any) -> UGCPDeprecationStage:
    """Map transitional aliases to deprecation stage.

    Empty/whitespace alias inputs (normalized by _normalize_text) are treated
    as migration-required so validation cleanup can be prioritized before
    strictness is increased.
    """
    normalized_input = _normalize_text(raw_value)
    if not normalized_input:
        # Empty alias inputs indicate unresolved caller migration and should
        # remain visible in migration-required review surfaces.
        return UGCPDeprecationStage.migration_required
    return _SURFACE_ALIAS_DEPRECATION_STAGE.get(surface, {}).get(
        normalized_input,
        UGCPDeprecationStage.migration_required,
    )


def _parse_enforcement_mode(mode: UGCPEnforcementMode | str) -> UGCPEnforcementMode:
    if isinstance(mode, UGCPEnforcementMode):
        return mode
    normalized_mode = str(mode).strip().lower()
    try:
        return UGCPEnforcementMode(normalized_mode)
    except ValueError:
        _LOGGER.warning(
            "Unknown UGCP enforcement mode '%s'; falling back to compatibility mode. "
            "Valid modes: compatibility, review, strict",
            mode,
        )
        return UGCPEnforcementMode.compatibility


def evaluate_surface_enforcement(
    surface: UGCPConformanceSurface | str,
    value: Any,
    mode: UGCPEnforcementMode | str = UGCPEnforcementMode.compatibility,
) -> UGCPEnforcementDecision:
    """Evaluate bounded enforcement action without forcing global strict breakage."""
    parsed_mode = _parse_enforcement_mode(mode)
    classified = classify_surface_semantics(surface, value)

    if classified.semantic_class == UGCPSemanticClass.canonical:
        return UGCPEnforcementDecision(
            surface=classified.surface,
            input_value=value,
            normalized_value=classified.normalized_value,
            semantic_class=classified.semantic_class,
            action=UGCPEnforcementAction.accept,
            deprecation_stage=UGCPDeprecationStage.not_deprecated,
            reject_in_mode=False,
        )

    if classified.semantic_class == UGCPSemanticClass.transitional:
        deprecation_stage = _resolve_alias_deprecation_stage(classified.surface, value)
        reject_in_mode = parsed_mode == UGCPEnforcementMode.strict and (
            deprecation_stage == UGCPDeprecationStage.strict_reject_candidate
        )
        action = UGCPEnforcementAction.reject if reject_in_mode else UGCPEnforcementAction.normalize_warn
        return UGCPEnforcementDecision(
            surface=classified.surface,
            input_value=value,
            normalized_value=classified.normalized_value,
            semantic_class=classified.semantic_class,
            action=action,
            deprecation_stage=deprecation_stage,
            reject_in_mode=reject_in_mode,
            warning=(
                f"{classified.surface.value} transitional alias normalized via "
                f"{classified.compatibility_pathway} ({deprecation_stage.value})"
            ),
            compatibility_pathway=classified.compatibility_pathway,
        )

    reject_in_mode = parsed_mode == UGCPEnforcementMode.strict
    action = UGCPEnforcementAction.reject if reject_in_mode else UGCPEnforcementAction.tolerate_warn
    return UGCPEnforcementDecision(
        surface=classified.surface,
        input_value=value,
        normalized_value=classified.normalized_value,
        semantic_class=classified.semantic_class,
        action=action,
        deprecation_stage=UGCPDeprecationStage.transitional_tolerated,
        reject_in_mode=reject_in_mode,
        warning=f"{classified.surface.value} value is unknown and currently tolerated for compatibility review",
        compatibility_pathway=classified.compatibility_pathway,
    )


def build_enforcement_scaffold(
    payload: Mapping[str, Any],
    mode: UGCPEnforcementMode | str = UGCPEnforcementMode.compatibility,
) -> Dict[str, Any]:
    """Build reviewable enforcement/deprecation scaffold for progressive hardening."""
    parsed_mode = _parse_enforcement_mode(mode)
    normalized = normalize_conformance_backbone(payload)
    surface_inputs = {
        "schema": payload.get("schema_kind"),
        "lifecycle": payload.get("lifecycle_state"),
        "authority": payload.get("authority_source"),
        "transfer": payload.get("transfer_state"),
        "coordination": payload.get("coordination_state"),
        "truth_event": payload.get("truth_event_type"),
    }
    decisions = {
        surface_key: evaluate_surface_enforcement(surface_key, raw_value, parsed_mode)
        for surface_key, raw_value in surface_inputs.items()
    }
    warnings = [decision.warning for decision in decisions.values() if decision.warning]
    rejected_surfaces_in_mode = [surface for surface, decision in decisions.items() if decision.reject_in_mode]
    strict_rejection_ready_pathways = [
        decision.compatibility_pathway
        for decision in decisions.values()
        if decision.deprecation_stage == UGCPDeprecationStage.strict_reject_candidate
        and decision.compatibility_pathway
    ]
    deprecation_markers = {
        surface: decision.deprecation_stage.value
        for surface, decision in decisions.items()
        if decision.deprecation_stage != UGCPDeprecationStage.not_deprecated
    }
    return {
        "mode": parsed_mode.value,
        "normalized": normalized,
        "warnings": warnings,
        "rejected_surfaces_in_mode": rejected_surfaces_in_mode,
        "strict_rejection_ready_pathways": strict_rejection_ready_pathways,
        "deprecation_markers": deprecation_markers,
        "decisions": {
            surface: {
                "action": decision.action.value,
                "semantic_class": decision.semantic_class.value,
                "normalized_value": decision.normalized_value,
                "compatibility_pathway": decision.compatibility_pathway,
                "deprecation_stage": decision.deprecation_stage.value,
                "reject_in_mode": decision.reject_in_mode,
            }
            for surface, decision in decisions.items()
        },
    }


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
    enforcement = build_enforcement_scaffold(payload or {}, mode=UGCPEnforcementMode.review)
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
        "enforcement_scaffold": enforcement,
    }


def get_ugcp_retirement_stage_catalog() -> Dict[str, Dict[str, List[str]]]:
    """Return alias retirement staging grouped by conformance surface.

    Returns:
        A dictionary keyed by `UGCPConformanceSurface.value`.  Each value is a
        dictionary with the following keys, each mapped to `List[str]`:
        - `migration_required_aliases`
        - `transitional_tolerated_aliases`
        - `strict_reject_candidate_aliases`
    """
    stage_catalog: Dict[str, Dict[str, List[str]]] = {}
    for surface in UGCPConformanceSurface:
        aliases = _SURFACE_ALIAS_DEPRECATION_STAGE.get(surface, {})
        migration_required_aliases = sorted(
            alias
            for alias, stage in aliases.items()
            if stage == UGCPDeprecationStage.migration_required
        )
        transitional_tolerated_aliases = sorted(
            alias
            for alias, stage in aliases.items()
            if stage == UGCPDeprecationStage.transitional_tolerated
        )
        strict_reject_candidate_aliases = sorted(
            alias
            for alias, stage in aliases.items()
            if stage == UGCPDeprecationStage.strict_reject_candidate
        )
        stage_catalog[surface.value] = {
            "migration_required_aliases": migration_required_aliases,
            "transitional_tolerated_aliases": transitional_tolerated_aliases,
            "strict_reject_candidate_aliases": strict_reject_candidate_aliases,
        }
    return stage_catalog


def build_migration_readiness_scaffold(
    payload: Optional[Mapping[str, Any]] = None,
    mode: UGCPEnforcementMode | str = UGCPEnforcementMode.compatibility,
) -> Dict[str, Any]:
    """Build PR-11 migration-readiness and retirement-sequencing scaffold.

    Args:
        payload: Optional mapping that may include conformance inputs such as
            `schema_kind`, `lifecycle_state`, `authority_source`,
            `transfer_state`, `coordination_state`, and `truth_event_type`.
        mode: Enforcement mode (`compatibility`, `review`, or `strict`).

    Returns:
        A dictionary containing:
        - `mode` (`str`): parsed enforcement mode.
        - `canonical_surfaces_ready_for_staged_enforcement` (`List[str]`):
          canonical UGCP surface names available for staged tightening review.
        - `retirement_stage_catalog` (`Dict[str, Dict[str, List[str]]]`):
          per-surface retirement alias stage grouping.
        - `transitional_surfaces_requiring_tolerance` (with `deprecation_stage`
          defaulting to `transitional_tolerated` if missing from a decision).
        - `retirement_sequence` (`List[Dict[str, Any]]`): stage-gated rollout
          phases and pathway focus.
        - `enforcement_scaffold` (`Dict[str, Any]`): bounded enforcement output
          from `build_enforcement_scaffold`.
    """
    source_payload = payload or {}
    parsed_mode = _parse_enforcement_mode(mode)
    stage_catalog = get_ugcp_retirement_stage_catalog()
    enforcement = build_enforcement_scaffold(source_payload, mode=parsed_mode)

    canonical_surfaces_ready_for_staged_enforcement = sorted(
        surface.value for surface in UGCPConformanceSurface
    )
    decisions = enforcement.get("decisions", {})
    transitional_surfaces_requiring_tolerance = [
        {
            "surface": surface,
            "semantic_class": decision.get("semantic_class", UGCPSemanticClass.unknown.value),
            "compatibility_pathway": decision.get("compatibility_pathway", ""),
            "deprecation_stage": decision.get(
                "deprecation_stage",
                UGCPDeprecationStage.transitional_tolerated.value,
            ),
        }
        for surface, decision in decisions.items()
        if decision.get("semantic_class") != UGCPSemanticClass.canonical.value
    ]
    migration_required_pathways = sorted(
        item["compatibility_pathway"]
        for item in transitional_surfaces_requiring_tolerance
        if item["deprecation_stage"] == UGCPDeprecationStage.migration_required.value
        and item["compatibility_pathway"]
    )
    strict_reject_candidate_pathways = sorted(
        item["compatibility_pathway"]
        for item in transitional_surfaces_requiring_tolerance
        if item["deprecation_stage"] == UGCPDeprecationStage.strict_reject_candidate.value
        and item["compatibility_pathway"]
    )
    retirement_sequence = [
        {
            "phase": "observe_and_normalize",
            "focus": "Retain compatibility defaults, collect warnings, and normalize pathways.",
            "pathways": sorted(
                item["compatibility_pathway"]
                for item in transitional_surfaces_requiring_tolerance
                if item["compatibility_pathway"]
            ),
        },
        {
            "phase": "migrate_required_pathways",
            "focus": "Prioritize migration-required aliases before strictness increase.",
            "pathways": migration_required_pathways,
        },
        {
            "phase": "gate_strict_reject_candidates",
            "focus": "Apply strict rejection only to explicitly marked strict candidates.",
            "pathways": strict_reject_candidate_pathways,
        },
    ]
    return {
        "mode": parsed_mode.value,
        "canonical_surfaces_ready_for_staged_enforcement": canonical_surfaces_ready_for_staged_enforcement,
        "retirement_stage_catalog": stage_catalog,
        "transitional_surfaces_requiring_tolerance": transitional_surfaces_requiring_tolerance,
        "retirement_sequence": retirement_sequence,
        "enforcement_scaffold": enforcement,
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
    "UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL",
    "UGCP_MIGRATION_READINESS_PR11_SENTINEL",
    "ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT_POLICY",
    "DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE_POLICY",
    "PROGRESSIVE_STRICTNESS_IS_OPT_IN_POLICY",
    "MIGRATION_READINESS_SURFACES_ARE_EXPLICIT_POLICY",
    "RETIREMENT_SEQUENCING_IS_STAGE_GATED_POLICY",
    "UGCPConformanceSurface",
    "UGCPSemanticClass",
    "UGCPEnforcementMode",
    "UGCPEnforcementAction",
    "UGCPDeprecationStage",
    "UGCPConformanceSurfaceDefinition",
    "UGCPConformanceClassification",
    "UGCPEnforcementDecision",
    "get_ugcp_conformance_surface_catalog",
    "classify_surface_semantics",
    "evaluate_surface_enforcement",
    "build_enforcement_scaffold",
    "normalize_conformance_payload",
    "normalize_conformance_backbone",
    "build_conformance_invariant_report",
    "get_ugcp_retirement_stage_catalog",
    "build_migration_readiness_scaffold",
]
