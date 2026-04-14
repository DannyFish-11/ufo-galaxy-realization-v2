"""Tests for PR-8 UGCP conformance surfaces and compatibility scaffolding."""

from __future__ import annotations

import importlib.util

import pytest

from core.ugcp_conformance_surfaces import (
    CANONICAL_VS_TRANSITIONAL_CLASSIFICATION_POLICY,
    COMPATIBILITY_RETIREMENT_IS_PROGRESSIVE_POLICY,
    CROSS_PROFILE_INVARIANTS_ARE_REVIEWABLE_POLICY,
    NORMALIZATION_BOUNDARY_IS_EXPLICIT_POLICY,
    UGCP_CONFORMANCE_SURFACES_AUTHORITY,
    UGCP_CONFORMANCE_SURFACES_PR8_SENTINEL,
    UGCPConformanceSurface,
    UGCPSemanticClass,
    build_conformance_invariant_report,
    classify_surface_semantics,
    get_ugcp_conformance_surface_catalog,
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


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8
    assert "UGCP_CONFORMANCE_SURFACES_ALIGNED_PR8" in sentinel
    assert "UNAVAILABLE" not in sentinel
    assert callable(getattr(projection, "_classify_surface_semantics", None))
    assert callable(getattr(projection, "_normalize_conformance_payload", None))
    assert callable(getattr(projection, "_build_conformance_invariant_report", None))
