"""Tests for PR-8 UGCP conformance surfaces and compatibility scaffolding."""

from __future__ import annotations

import importlib.util

import pytest

from core.ugcp_conformance_surfaces import (
    CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY,
    COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY,
    CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY,
    DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE_POLICY,
    ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT_POLICY,
    MIGRATION_READINESS_SURFACES_ARE_EXPLICIT_POLICY,
    NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY,
    PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED_POLICY,
    PROGRESSIVE_STRICTNESS_IS_OPT_IN_POLICY,
    RETIREMENT_SEQUENCING_IS_STAGE_GATED_POLICY,
    UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL,
    UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL,
    UGCP_MIGRATION_READINESS_PR11_SENTINEL,
    UGCPDeprecationStage,
    UGCPEnforcementAction,
    UGCPEnforcementMode,
    UGCP_CONFORMANCE_SURFACES_AUTHORITY,
    UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL,
    UGCPConformanceSurface,
    UGCPSemanticClass,
    build_enforcement_scaffold,
    build_conformance_invariant_report,
    classify_surface_semantics,
    build_migration_readiness_scaffold,
    evaluate_surface_enforcement,
    get_ugcp_retirement_stage_catalog,
    get_ugcp_conformance_surface_catalog,
    normalize_conformance_backbone,
    normalize_conformance_payload,
)
from core.ugcp_truth_event_model import CanonicalTruthEventType

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


def test_sentinels_present() -> None:
    assert UGCP_CONFORMANCE_SURFACES_AUTHORITY.startswith("UGCP_CONFORMANCE_SURFACES_AUTHORITY::")
    assert "canonical conformance scaffold authority" in UGCP_CONFORMANCE_SURFACES_AUTHORITY
    assert "package=8" in UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL
    assert "CANONICAL_VS_TRANSITIONAL_CLASSIFICATION" in CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY
    assert "NORMALIZATION_BOUNDARY_IS_EXPLICIT" in NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY
    assert "CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE" in CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY
    assert "COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE" in COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY
    assert "PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED" in PROFILE_COMPOSITION_BACKBONE_IS_NORMALIZED_POLICY
    assert "ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT" in ENFORCEMENT_HANDLING_CLASSIFICATION_IS_EXPLICIT_POLICY
    assert "DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE" in DEPRECATION_EXECUTION_PATHWAY_IS_REVIEWABLE_POLICY
    assert "PROGRESSIVE_STRICTNESS_IS_OPT_IN" in PROGRESSIVE_STRICTNESS_IS_OPT_IN_POLICY
    assert "MIGRATION_READINESS_SURFACES_ARE_EXPLICIT" in MIGRATION_READINESS_SURFACES_ARE_EXPLICIT_POLICY
    assert "RETIREMENT_SEQUENCING_IS_STAGE_GATED" in RETIREMENT_SEQUENCING_IS_STAGE_GATED_POLICY
    assert UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL == (
        "UGCP_CONFORMANCE_BACKBONE_CONSOLIDATION_PR9_SENTINEL::package=9::"
        "profile=ugcp-conformance-backbone-v1::module=core.ugcp_conformance_surfaces"
    )
    assert UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL == (
        "UGCP_ENFORCEMENT_SCAFFOLDING_PR10_SENTINEL::package=10::"
        "profile=ugcp-enforcement-scaffold-v1::module=core.ugcp_conformance_surfaces"
    )
    assert UGCP_MIGRATION_READINESS_PR11_SENTINEL == (
        "UGCP_MIGRATION_READINESS_PR11_SENTINEL::package=11::"
        "profile=ugcp-migration-readiness-v1::module=core.ugcp_conformance_surfaces"
    )


def test_surface_catalog_has_expected_authority_mappings() -> None:
    catalog = get_ugcp_conformance_surface_catalog()
    assert set(catalog) == {"schema", "lifecycle", "authority", "transfer", "coordination", "truth_event"}
    assert "core.schemas.ugcp.shared" in catalog["schema"]["canonical_authority"]
    assert "core.ugcp_control_transfer_profile" in catalog["transfer"]["canonical_authority"]
    assert "core.ugcp_coordination_profile" in catalog["coordination"]["canonical_authority"]
    assert "core.ugcp_truth_event_model" in catalog["truth_event"]["canonical_authority"]


def test_classification_distinguishes_canonical_and_transitional_values() -> None:
    canonical = classify_surface_semantics(UGCPConformanceSurface.transfer, "ready")
    transitional = classify_surface_semantics(UGCPConformanceSurface.transfer, "sealed")
    unknown = classify_surface_semantics(UGCPConformanceSurface.transfer, "not_a_state")

    assert canonical.semantic_class == UGCPSemanticClass.canonical
    assert canonical.normalized_value == "ready"
    assert transitional.semantic_class == UGCPSemanticClass.transitional
    assert transitional.normalized_value == "ready"
    assert transitional.compatibility_pathway == "transfer_alias:sealed->ready"
    assert unknown.semantic_class == UGCPSemanticClass.unknown
    assert unknown.normalized_value == "unknown"


def test_truth_event_aliases_are_normalized_to_canonical_vocabulary() -> None:
    truth_event = classify_surface_semantics(UGCPConformanceSurface.truth_event, "session_truth_written")
    assert truth_event.semantic_class == UGCPSemanticClass.transitional
    assert truth_event.normalized_value == CanonicalTruthEventType.session_truth_recorded.value


def test_normalize_payload_marks_compatibility_pathways() -> None:
    normalized = normalize_conformance_payload(
        {
            "schema_kind": "legacy_message_payload",
            "lifecycle_state": "done",
            "authority_source": "projection",
            "transfer_state": "sealed",
            "coordination_state": "waiting",
            "truth_event_type": "mesh_coordination_transition",
        }
    )

    assert normalized["schema_kind"] == "task_envelope"
    assert normalized["lifecycle_state"] == "completed"
    assert normalized["authority_source"] == "unknown"
    assert normalized["transfer_state"] == "ready"
    assert normalized["coordination_state"] == "awaiting_barrier"
    assert normalized["truth_event_type"] == CanonicalTruthEventType.coordination_transition.value
    assert normalized["semantic_classes"]["truth_event"] == UGCPSemanticClass.transitional.value
    assert "authority" in normalized["compatibility_pathways"]


def test_invariant_report_surfaces_nonconformance_without_hard_break() -> None:
    report = build_conformance_invariant_report(
        {
            "lifecycle_state": "done",
            "authority_source": "projection",
            "transfer_state": "unknown_transfer_value",
            "coordination_state": "active",
            "truth_event_type": "legacy_event_name",
        }
    )

    assert report["conforms"] is False
    assert report["invariants"]["authority_source_not_compat_alias"] is False
    assert report["invariants"]["transfer_state_known"] is False
    assert report["invariants"]["truth_event_is_canonical"] is False
    assert "transfer_state_known" in report["violations"]
    assert report["normalized"]["lifecycle_state"] == "completed"


def test_backbone_normalization_composes_lifecycle_from_adjacent_profile_state() -> None:
    normalized = normalize_conformance_backbone(
        {
            "lifecycle_state": "unknown_state",
            "transfer_state": "executing",
            "coordination_state": "waiting",
            "truth_event_type": CanonicalTruthEventType.control_transfer_transition.value,
        }
    )

    assert normalized["lifecycle_state"] == "unknown"
    assert normalized["transfer_state"] == "in_progress"
    assert normalized["coordination_state"] == "awaiting_barrier"
    assert normalized["composed_lifecycle_state"] == "in_progress"
    assert normalized["lifecycle_source_surface"] == "transfer"
    assert "transfer_transitional_pathway" in normalized["hardening_pathways"]
    assert "coordination_transitional_pathway" in normalized["hardening_pathways"]


def test_invariant_report_flags_cross_profile_lifecycle_drift() -> None:
    report = build_conformance_invariant_report(
        {
            "lifecycle_state": "completed",
            "transfer_state": "in_progress",
            "coordination_state": "active",
            "truth_event_type": CanonicalTruthEventType.runtime_lifecycle_transition.value,
            "authority_source": "ugcp_truth_event_model",
        }
    )

    assert report["invariants"]["composed_lifecycle_state_known"] is True
    assert report["invariants"]["semantic_drift_signals_empty"] is False
    assert "lifecycle_transfer_divergence" in report["normalized"]["semantic_drift_signals"]
    assert "semantic_drift_signals_empty" in report["violations"]
    assert report["enforcement_scaffold"]["mode"] == UGCPEnforcementMode.review.value


def test_enforcement_decision_strict_mode_reject_candidates() -> None:
    review_decision = evaluate_surface_enforcement(
        UGCPConformanceSurface.authority,
        "projection",
        mode=UGCPEnforcementMode.review,
    )
    strict_decision = evaluate_surface_enforcement(
        UGCPConformanceSurface.authority,
        "projection",
        mode=UGCPEnforcementMode.strict,
    )

    assert review_decision.action == UGCPEnforcementAction.normalize_warn
    assert review_decision.reject_in_mode is False
    assert review_decision.deprecation_stage == UGCPDeprecationStage.strict_reject_candidate
    assert strict_decision.action == UGCPEnforcementAction.reject
    assert strict_decision.reject_in_mode is True


@pytest.mark.parametrize(
    ("surface", "raw_value"),
    [
        (UGCPConformanceSurface.schema, "legacy_message_payload"),
        (UGCPConformanceSurface.authority, "projection"),
        (UGCPConformanceSurface.transfer, "blocked"),
    ],
)
def test_strict_reject_candidates_cover_multiple_surfaces(
    surface: UGCPConformanceSurface,
    raw_value: str,
) -> None:
    decision = evaluate_surface_enforcement(surface, raw_value, mode=UGCPEnforcementMode.strict)
    assert decision.deprecation_stage == UGCPDeprecationStage.strict_reject_candidate
    assert decision.action == UGCPEnforcementAction.reject
    assert decision.reject_in_mode is True


def test_enforcement_scaffold_marks_warnings_and_rejection_candidates() -> None:
    scaffold = build_enforcement_scaffold(
        {
            "schema_kind": "legacy_message_payload",
            "lifecycle_state": "done",
            "authority_source": "projection",
            "transfer_state": "blocked",
            "coordination_state": "waiting",
            "truth_event_type": "runtime_state_transition",
        },
        mode=UGCPEnforcementMode.strict,
    )

    assert scaffold["mode"] == UGCPEnforcementMode.strict.value
    assert "authority" in scaffold["rejected_surfaces_in_mode"]
    assert "transfer" in scaffold["rejected_surfaces_in_mode"]
    assert scaffold["deprecation_markers"]["schema"] == UGCPDeprecationStage.strict_reject_candidate.value
    assert scaffold["decisions"]["coordination"]["action"] == UGCPEnforcementAction.normalize_warn.value
    assert scaffold["warnings"]
    assert scaffold["strict_rejection_ready_pathways"] == [
        "schema_alias:legacy_message_payload->task_envelope",
        "authority_alias:projection->unknown",
        "transfer_alias:blocked->rejected",
    ]


def test_retirement_stage_catalog_is_surface_scoped_and_stage_grouped() -> None:
    catalog = get_ugcp_retirement_stage_catalog()
    assert set(catalog) == {"schema", "lifecycle", "authority", "transfer", "coordination", "truth_event"}
    assert catalog["schema"]["strict_reject_candidate_aliases"] == ["legacy_message_payload"]
    assert "waiting" in catalog["lifecycle"]["transitional_tolerated_aliases"]
    assert "projection" in catalog["authority"]["strict_reject_candidate_aliases"]
    assert "blocked" in catalog["transfer"]["strict_reject_candidate_aliases"]
    assert "session_truth_written" in catalog["truth_event"]["migration_required_aliases"]


def test_migration_readiness_scaffold_preserves_compat_defaults_and_sequences_retirement() -> None:
    scaffold = build_migration_readiness_scaffold(
        {
            "schema_kind": "legacy_message_payload",
            "lifecycle_state": "waiting",
            "authority_source": "projection",
            "transfer_state": "blocked",
            "coordination_state": "waiting",
            "truth_event_type": "runtime_state_transition",
        },
        mode=UGCPEnforcementMode.compatibility,
    )

    assert scaffold["mode"] == UGCPEnforcementMode.compatibility.value
    assert scaffold["canonical_surfaces_ready_for_staged_enforcement"] == [
        "authority",
        "coordination",
        "lifecycle",
        "schema",
        "transfer",
        "truth_event",
    ]
    assert scaffold["transitional_surfaces_requiring_tolerance"]
    assert scaffold["retirement_sequence"][0]["phase"] == "observe_and_normalize"
    assert scaffold["retirement_sequence"][1]["phase"] == "migrate_required_pathways"
    assert scaffold["retirement_sequence"][2]["phase"] == "gate_strict_reject_candidates"
    assert "transfer_alias:blocked->rejected" in scaffold["retirement_sequence"][2]["pathways"]
    assert scaffold["enforcement_scaffold"]["rejected_surfaces_in_mode"] == []


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8
    assert "UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8" in sentinel
    assert "UNAVAILABLE" not in sentinel
    enforcement_sentinel = projection.UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10
    migration_sentinel = projection.UGCP_MIGRATION_READINESS_ALIGNED_PR11
    assert "UGCP_ENFORCEMENT_SCAFFOLDING_ALIGNED_PR10" in enforcement_sentinel
    assert "UGCP_MIGRATION_READINESS_ALIGNED_PR11" in migration_sentinel
    assert "UNAVAILABLE" not in enforcement_sentinel
    assert "UNAVAILABLE" not in migration_sentinel
    assert callable(getattr(projection, "_classify_surface_semantics", None))
    assert callable(getattr(projection, "_evaluate_surface_enforcement", None))
    assert callable(getattr(projection, "_build_enforcement_scaffold", None))
    assert callable(getattr(projection, "_build_migration_readiness_scaffold", None))
    assert callable(getattr(projection, "_get_ugcp_retirement_stage_catalog", None))
    assert callable(getattr(projection, "_normalize_conformance_payload", None))
    assert callable(getattr(projection, "_normalize_conformance_backbone", None))
    assert callable(getattr(projection, "_build_conformance_invariant_report", None))
