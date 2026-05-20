#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr12v2_cross_subject_observability_contract.py
=============================================================
PR-12V2: Unified Cross-Subject Observability / Diagnostics / Evidence
Contract — regression tests.

Locks the following invariants:

 1.  Module importable; authority and PR-12V2 sentinel are non-empty strings
     containing expected keywords.
 2.  All six policy sentinels are non-empty and contain expected keywords.
 3.  VisibilityLevel enum — all four expected level values are present.
 4.  EvidenceContractKind enum — all five expected kind values are present.
 5.  ObservabilitySurface dataclass — structure and to_dict() are correct.
 6.  CrossSubjectObservabilitySnapshot dataclass — structure and to_dict().
 7.  Registry is non-empty and contains surfaces of every visibility level.
 8.  Every registry surface has a non-empty notes field.
 9.  classify_surface_visibility() — known and unknown surface IDs.
10.  get_surfaces_by_visibility() — filters correctly for each level.
11.  build_cross_subject_observability_snapshot() — aggregate builder
     correctness (counts and uplink_path_surfaces).
12.  Snapshot total_surfaces equals the sum of all level counts.
13.  Snapshot has exactly 6 policies.
14.  LOCAL_VISIBLE surfaces all have may_not_write_canonical_truth=True.
15.  OPERATOR_VISIBLE surfaces all have may_not_write_canonical_truth=True.
16.  PRODUCT_VISIBLE surfaces all have may_not_write_canonical_truth=True
     except canonical center authority modules (runtime_truth kind,
     may_not_write_canonical_truth=False).
17.  RUNTIME_VISIBLE uplink path surfaces include android_participant_truth
     and android_evaluator_artifact_ingress.
18.  get_canonical_evidence_uplink_path() — returns non-empty tuple with
     expected uplink steps.
19.  LOCAL_VISIBLE policy explicitly references "MUST NOT" uplink semantics.
20.  OPERATOR_VISIBLE policy explicitly references "read-only" semantics.
21.  PRODUCT_VISIBLE policy explicitly references "canonical" consumption.
22.  NO_PARALLEL_OBSERVABILITY_CENTER policy explicitly references
     "parallel" and "authority".
23.  RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY policy explicitly references
     "V2 canonical" semantics.
24.  At least one surface per visibility level is present in the registry.
25.  participant_diagnostics_uplink surfaces in registry reference the
     declared canonical uplink path (not the old TRANSITIONAL path).
26.  distributed_subject_contract_v1_field is set on key boundary surfaces.
27.  Snapshot to_dict() includes all expected keys.
28.  Local-visible Android surfaces include RuntimeController and
     LocalLoopExecutor.
29.  Operator-visible surfaces include operator_surface and routes/operator.
30.  Product-visible surfaces include outward_runtime_truth.
31.  No surface claiming runtime_truth evidence kind is in the local_visible
     level (local subjects cannot produce canonical runtime truth).
32.  Uplink path surfaces are all in runtime_visible level (uplink is a
     runtime-infrastructure concern).
33.  Snapshot uplink_path_surfaces matches surfaces with is_uplink_path=True.
34.  Evidence kind counts in snapshot sum to total_surfaces.
35.  Contract authority sentinel includes "PR-12V2" reference keywords.
"""

from __future__ import annotations

import pytest

from core.cross_subject_observability_contract import (
    CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY,
    CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL,
    LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY,
    NO_PARALLEL_OBSERVABILITY_CENTER_POLICY,
    OBSERVABILITY_SURFACE_REGISTRY,
    OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY,
    PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY,
    RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY,
    RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY,
    CrossSubjectObservabilitySnapshot,
    EvidenceContractKind,
    ObservabilitySurface,
    VisibilityLevel,
    build_cross_subject_observability_snapshot,
    classify_surface_visibility,
    get_canonical_evidence_uplink_path,
    get_observability_surface_registry,
    get_surfaces_by_visibility,
)


# ---------------------------------------------------------------------------
# 1. Authority and PR-12V2 sentinel — non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_authority_sentinel_is_non_empty_and_contains_expected_keywords():
    assert CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY
    assert isinstance(CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY, str)
    assert "AUTHORITY" in CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY
    assert "cross_subject_observability_contract" in (
        CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY
    )
    assert "visibility" in CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY.lower()


def test_pr12v2_sentinel_is_non_empty_and_contains_expected_keywords():
    assert CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL
    assert isinstance(CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL, str)
    assert "pr12v2" in CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL.lower()
    assert "locked" in CROSS_SUBJECT_OBSERVABILITY_CONTRACT_PR12V2_SENTINEL.lower()


# ---------------------------------------------------------------------------
# 2. All six policy sentinels — non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_local_visible_policy_is_non_empty_and_references_uplink():
    assert LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY
    upper = LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY.upper()
    assert "MUST NOT" in upper or "MUST_NOT" in upper


def test_runtime_visible_policy_is_non_empty_and_references_ingress():
    assert RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY
    assert "ingress" in RUNTIME_VISIBLE_MUST_USE_DECLARED_INGRESS_POLICY.lower()


def test_operator_visible_policy_is_non_empty_and_references_read_only():
    assert OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY
    text = OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY.lower()
    assert "read-only" in text or "read_only" in text or "read only" in text


def test_product_visible_policy_is_non_empty_and_references_canonical():
    assert PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY
    assert "canonical" in PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY.lower()


def test_no_parallel_observability_policy_references_parallel_and_authority():
    assert NO_PARALLEL_OBSERVABILITY_CENTER_POLICY
    lower = NO_PARALLEL_OBSERVABILITY_CENTER_POLICY.lower()
    assert "parallel" in lower
    assert "authority" in lower


def test_runtime_truth_v2_only_policy_references_v2_canonical():
    assert RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY
    lower = RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY.lower()
    assert "canonical" in lower


# ---------------------------------------------------------------------------
# 3. VisibilityLevel enum — all four levels present
# ---------------------------------------------------------------------------


def test_visibility_level_enum_has_all_four_levels():
    values = {e.value for e in VisibilityLevel}
    assert "local_visible" in values
    assert "runtime_visible" in values
    assert "operator_visible" in values
    assert "product_visible" in values


def test_visibility_level_enum_has_exactly_four_members():
    assert len(VisibilityLevel) == 4


# ---------------------------------------------------------------------------
# 4. EvidenceContractKind enum — all five kinds present
# ---------------------------------------------------------------------------


def test_evidence_contract_kind_has_all_five_kinds():
    values = {e.value for e in EvidenceContractKind}
    assert "participant_evidence" in values
    assert "diagnostics_evidence" in values
    assert "execution_artifact" in values
    assert "continuity_evidence" in values
    assert "runtime_truth" in values


def test_evidence_contract_kind_has_exactly_five_members():
    assert len(EvidenceContractKind) == 5


# ---------------------------------------------------------------------------
# 5. ObservabilitySurface dataclass — structure and to_dict()
# ---------------------------------------------------------------------------


def test_observability_surface_to_dict_has_all_required_keys():
    surface = ObservabilitySurface(
        surface_id="test_surface",
        module_path="test.module",
        surface_name="Test Surface",
        visibility_level=VisibilityLevel.operator_visible,
        evidence_kind=EvidenceContractKind.diagnostics_evidence,
        notes="Test notes.",
    )
    d = surface.to_dict()
    expected_keys = {
        "surface_id",
        "module_path",
        "surface_name",
        "visibility_level",
        "evidence_kind",
        "is_uplink_path",
        "may_not_write_canonical_truth",
        "distributed_subject_contract_v1_field",
        "notes",
    }
    assert expected_keys <= set(d.keys())


def test_observability_surface_to_dict_values_are_correct():
    surface = ObservabilitySurface(
        surface_id="test_id",
        module_path="core.test_module",
        surface_name="Test Name",
        visibility_level=VisibilityLevel.local_visible,
        evidence_kind=EvidenceContractKind.participant_evidence,
        is_uplink_path=True,
        may_not_write_canonical_truth=True,
        distributed_subject_contract_v1_field="local_visible_diagnostics",
        notes="Test notes for verification.",
    )
    d = surface.to_dict()
    assert d["surface_id"] == "test_id"
    assert d["visibility_level"] == "local_visible"
    assert d["evidence_kind"] == "participant_evidence"
    assert d["is_uplink_path"] is True
    assert d["may_not_write_canonical_truth"] is True
    assert d["distributed_subject_contract_v1_field"] == "local_visible_diagnostics"


# ---------------------------------------------------------------------------
# 6. CrossSubjectObservabilitySnapshot — structure and to_dict()
# ---------------------------------------------------------------------------


def test_cross_subject_observability_snapshot_to_dict_has_all_keys():
    snap = CrossSubjectObservabilitySnapshot()
    d = snap.to_dict()
    expected_keys = {
        "authority",
        "sentinel",
        "policies",
        "total_surfaces",
        "local_visible_count",
        "runtime_visible_count",
        "operator_visible_count",
        "product_visible_count",
        "uplink_path_surfaces",
        "participant_evidence_count",
        "diagnostics_evidence_count",
        "execution_artifact_count",
        "continuity_evidence_count",
        "runtime_truth_count",
        "generated_at",
    }
    assert expected_keys <= set(d.keys())


# ---------------------------------------------------------------------------
# 7. Registry — non-empty and has surfaces of every visibility level
# ---------------------------------------------------------------------------


def test_registry_is_non_empty():
    registry = get_observability_surface_registry()
    assert len(registry) > 0


def test_registry_contains_local_visible_surfaces():
    local = [s for s in get_observability_surface_registry()
             if s.visibility_level == VisibilityLevel.local_visible]
    assert len(local) >= 1


def test_registry_contains_runtime_visible_surfaces():
    runtime = [s for s in get_observability_surface_registry()
               if s.visibility_level == VisibilityLevel.runtime_visible]
    assert len(runtime) >= 1


def test_registry_contains_operator_visible_surfaces():
    operator = [s for s in get_observability_surface_registry()
                if s.visibility_level == VisibilityLevel.operator_visible]
    assert len(operator) >= 1


def test_registry_contains_product_visible_surfaces():
    product = [s for s in get_observability_surface_registry()
               if s.visibility_level == VisibilityLevel.product_visible]
    assert len(product) >= 1


# ---------------------------------------------------------------------------
# 8. Every registry surface has a non-empty notes field
# ---------------------------------------------------------------------------


def test_every_surface_has_non_empty_notes():
    registry = get_observability_surface_registry()
    for surface in registry:
        assert surface.notes.strip(), (
            f"Surface '{surface.surface_id}' has an empty notes field."
        )


# ---------------------------------------------------------------------------
# 9. classify_surface_visibility() — known and unknown surface IDs
# ---------------------------------------------------------------------------


def test_classify_surface_visibility_returns_correct_level_for_known_id():
    # android_runtime_controller_local is LOCAL_VISIBLE
    result = classify_surface_visibility("android_runtime_controller_local")
    assert result == VisibilityLevel.local_visible.value


def test_classify_surface_visibility_returns_unknown_for_unregistered_id():
    result = classify_surface_visibility("nonexistent_surface_xyz")
    assert result == "unknown"


def test_classify_surface_visibility_operator_surface():
    result = classify_surface_visibility("operator_surface_projections")
    assert result == VisibilityLevel.operator_visible.value


def test_classify_surface_visibility_outward_runtime_truth():
    result = classify_surface_visibility("outward_runtime_truth_compile")
    assert result == VisibilityLevel.product_visible.value


# ---------------------------------------------------------------------------
# 10. get_surfaces_by_visibility() — filters correctly for each level
# ---------------------------------------------------------------------------


def test_get_surfaces_by_visibility_local_returns_only_local():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    assert all(s.visibility_level == VisibilityLevel.local_visible for s in surfaces)


def test_get_surfaces_by_visibility_operator_returns_only_operator():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.operator_visible)
    assert all(s.visibility_level == VisibilityLevel.operator_visible for s in surfaces)


def test_get_surfaces_by_visibility_product_returns_only_product():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.product_visible)
    assert all(s.visibility_level == VisibilityLevel.product_visible for s in surfaces)


def test_get_surfaces_by_visibility_runtime_returns_only_runtime():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.runtime_visible)
    assert all(s.visibility_level == VisibilityLevel.runtime_visible for s in surfaces)


# ---------------------------------------------------------------------------
# 11. build_cross_subject_observability_snapshot() — aggregate builder
# ---------------------------------------------------------------------------


def test_build_snapshot_returns_non_empty_snapshot():
    snap = build_cross_subject_observability_snapshot()
    assert snap.total_surfaces > 0
    assert snap.authority
    assert snap.sentinel


def test_build_snapshot_counts_are_correct():
    snap = build_cross_subject_observability_snapshot()
    assert snap.local_visible_count >= 1
    assert snap.runtime_visible_count >= 1
    assert snap.operator_visible_count >= 1
    assert snap.product_visible_count >= 1


# ---------------------------------------------------------------------------
# 12. Snapshot total_surfaces equals sum of all level counts
# ---------------------------------------------------------------------------


def test_snapshot_total_equals_sum_of_level_counts():
    snap = build_cross_subject_observability_snapshot()
    level_sum = (
        snap.local_visible_count
        + snap.runtime_visible_count
        + snap.operator_visible_count
        + snap.product_visible_count
    )
    assert snap.total_surfaces == level_sum, (
        f"total_surfaces={snap.total_surfaces} != "
        f"sum of level counts={level_sum}"
    )


# ---------------------------------------------------------------------------
# 13. Snapshot has exactly 6 policies
# ---------------------------------------------------------------------------


def test_snapshot_has_exactly_six_policies():
    snap = build_cross_subject_observability_snapshot()
    assert len(snap.policies) == 6


# ---------------------------------------------------------------------------
# 14. LOCAL_VISIBLE surfaces all have may_not_write_canonical_truth=True
# ---------------------------------------------------------------------------


def test_local_visible_surfaces_cannot_write_canonical_truth():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    for surface in surfaces:
        assert surface.may_not_write_canonical_truth is True, (
            f"LOCAL_VISIBLE surface '{surface.surface_id}' has "
            f"may_not_write_canonical_truth=False, which is a boundary violation."
        )


# ---------------------------------------------------------------------------
# 15. OPERATOR_VISIBLE surfaces all have may_not_write_canonical_truth=True
# ---------------------------------------------------------------------------


def test_operator_visible_surfaces_cannot_write_canonical_truth():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.operator_visible)
    for surface in surfaces:
        assert surface.may_not_write_canonical_truth is True, (
            f"OPERATOR_VISIBLE surface '{surface.surface_id}' has "
            f"may_not_write_canonical_truth=False — operator surfaces are "
            f"read-only projections and must not write canonical truth."
        )


# ---------------------------------------------------------------------------
# 16. PRODUCT_VISIBLE: authority modules (runtime_truth kind) may write;
#     non-authority product surfaces may not write canonical truth
# ---------------------------------------------------------------------------


def test_product_visible_non_authority_surfaces_cannot_write_canonical_truth():
    surfaces = get_surfaces_by_visibility(VisibilityLevel.product_visible)
    for surface in surfaces:
        if surface.evidence_kind != EvidenceContractKind.runtime_truth:
            assert surface.may_not_write_canonical_truth is True, (
                f"PRODUCT_VISIBLE non-runtime-truth surface "
                f"'{surface.surface_id}' has "
                f"may_not_write_canonical_truth=False — only canonical center "
                f"authority modules may write canonical truth."
            )


# ---------------------------------------------------------------------------
# 17. RUNTIME_VISIBLE uplink path surfaces include expected ingress modules
# ---------------------------------------------------------------------------


def test_runtime_visible_uplink_includes_android_participant_truth_ingress():
    uplink_surfaces = [
        s for s in get_observability_surface_registry()
        if s.is_uplink_path
    ]
    surface_ids = {s.surface_id for s in uplink_surfaces}
    assert "android_participant_truth_ingress" in surface_ids, (
        "android_participant_truth_ingress must be in the declared "
        "uplink path surfaces."
    )


def test_runtime_visible_uplink_includes_android_evaluator_artifact_ingress():
    uplink_surfaces = [
        s for s in get_observability_surface_registry()
        if s.is_uplink_path
    ]
    surface_ids = {s.surface_id for s in uplink_surfaces}
    assert "android_evaluator_artifact_ingress_runtime" in surface_ids, (
        "android_evaluator_artifact_ingress must be in the declared "
        "uplink path surfaces."
    )


def test_runtime_visible_uplink_includes_gateway_handlers():
    uplink_surfaces = [
        s for s in get_observability_surface_registry()
        if s.is_uplink_path
    ]
    surface_ids = {s.surface_id for s in uplink_surfaces}
    assert "galaxy_gateway_android_handlers" in surface_ids, (
        "galaxy_gateway.android.handlers must be in the uplink path."
    )


# ---------------------------------------------------------------------------
# 18. get_canonical_evidence_uplink_path() — non-empty tuple with key steps
# ---------------------------------------------------------------------------


def test_get_canonical_evidence_uplink_path_returns_non_empty_tuple():
    path = get_canonical_evidence_uplink_path()
    assert isinstance(path, tuple)
    assert len(path) > 0


def test_get_canonical_evidence_uplink_path_includes_android_entry():
    path = get_canonical_evidence_uplink_path()
    combined = " ".join(path).lower()
    assert "android" in combined or "galaxyconnectionservice" in combined.lower()


def test_get_canonical_evidence_uplink_path_includes_v2_ssot():
    path = get_canonical_evidence_uplink_path()
    combined = " ".join(path).lower()
    assert "ssot" in combined or "build_v2_android_truth_block" in combined


def test_get_canonical_evidence_uplink_path_includes_outward_truth():
    path = get_canonical_evidence_uplink_path()
    combined = " ".join(path).lower()
    assert "outward" in combined or "product_visible" in combined


# ---------------------------------------------------------------------------
# 19. LOCAL_VISIBLE policy references "MUST NOT"
# ---------------------------------------------------------------------------


def test_local_visible_policy_references_must_not():
    text = LOCAL_VISIBLE_MUST_NOT_SKIP_UPLINK_POLICY.upper()
    assert "MUST NOT" in text


# ---------------------------------------------------------------------------
# 20. OPERATOR_VISIBLE policy references "read-only"
# ---------------------------------------------------------------------------


def test_operator_visible_policy_references_read_only():
    lower = OPERATOR_VISIBLE_IS_READ_ONLY_PROJECTION_POLICY.lower()
    assert "read-only" in lower or "read_only" in lower or "read only" in lower


# ---------------------------------------------------------------------------
# 21. PRODUCT_VISIBLE policy references "canonical"
# ---------------------------------------------------------------------------


def test_product_visible_policy_references_canonical():
    lower = PRODUCT_VISIBLE_CONSUMES_CANONICAL_OUTPUTS_ONLY_POLICY.lower()
    assert "canonical" in lower


# ---------------------------------------------------------------------------
# 22. NO_PARALLEL_OBSERVABILITY_CENTER policy references "parallel" / "authority"
# ---------------------------------------------------------------------------


def test_no_parallel_policy_references_parallel_and_authority():
    lower = NO_PARALLEL_OBSERVABILITY_CENTER_POLICY.lower()
    assert "parallel" in lower
    assert "authority" in lower


# ---------------------------------------------------------------------------
# 23. RUNTIME_TRUTH_IS_V2_CANONICAL policy references "V2 canonical"
# ---------------------------------------------------------------------------


def test_runtime_truth_policy_references_v2_canonical():
    lower = RUNTIME_TRUTH_IS_V2_CANONICAL_CENTER_ONLY_POLICY.lower()
    assert "canonical" in lower
    assert "v2" in lower


# ---------------------------------------------------------------------------
# 24. At least one surface per visibility level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level", list(VisibilityLevel))
def test_at_least_one_surface_per_visibility_level(level):
    surfaces = get_surfaces_by_visibility(level)
    assert len(surfaces) >= 1, (
        f"No surfaces registered for visibility level '{level.value}'."
    )


# ---------------------------------------------------------------------------
# 25. participant_diagnostics_uplink surfaces reference canonical (not TRANSITIONAL)
# ---------------------------------------------------------------------------


def test_uplink_path_surfaces_are_canonical_not_transitional():
    """The declared uplink surfaces supersede the old TRANSITIONAL contract field."""
    uplink_surfaces = [
        s for s in get_observability_surface_registry()
        if s.distributed_subject_contract_v1_field == "participant_diagnostics_uplink"
    ]
    # There must be at least one surface that maps to this field
    assert len(uplink_surfaces) >= 1, (
        "At least one surface must map to participant_diagnostics_uplink to "
        "confirm the TRANSITIONAL field has been superseded."
    )
    # All such surfaces should be uplink path members or canonical authority
    for s in uplink_surfaces:
        # They should be is_uplink_path=True (formal uplink surfaces)
        # OR be the SSOT build step (runtime_truth kind)
        assert s.is_uplink_path or s.evidence_kind == EvidenceContractKind.runtime_truth, (
            f"Surface '{s.surface_id}' maps to participant_diagnostics_uplink "
            f"but is neither an uplink path surface nor the SSOT step."
        )


# ---------------------------------------------------------------------------
# 26. distributed_subject_contract_v1_field is set on key boundary surfaces
# ---------------------------------------------------------------------------


def test_local_visible_diagnostics_field_is_set_on_android_runtime_controller():
    registry = get_observability_surface_registry()
    android_rc = next(
        (s for s in registry if s.surface_id == "android_runtime_controller_local"),
        None,
    )
    assert android_rc is not None
    assert android_rc.distributed_subject_contract_v1_field == "local_visible_diagnostics"


def test_operator_visible_diagnostics_field_is_set_on_operator_surface():
    registry = get_observability_surface_registry()
    op_surface = next(
        (s for s in registry if s.surface_id == "operator_surface_projections"),
        None,
    )
    assert op_surface is not None
    assert op_surface.distributed_subject_contract_v1_field == "operator_visible_diagnostics"


# ---------------------------------------------------------------------------
# 27. Snapshot to_dict() includes all expected keys
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_includes_all_expected_keys():
    snap = build_cross_subject_observability_snapshot()
    d = snap.to_dict()
    expected_keys = {
        "authority",
        "sentinel",
        "policies",
        "total_surfaces",
        "local_visible_count",
        "runtime_visible_count",
        "operator_visible_count",
        "product_visible_count",
        "uplink_path_surfaces",
        "participant_evidence_count",
        "diagnostics_evidence_count",
        "execution_artifact_count",
        "continuity_evidence_count",
        "runtime_truth_count",
        "generated_at",
    }
    assert expected_keys <= set(d.keys())


# ---------------------------------------------------------------------------
# 28. Local-visible Android surfaces include RuntimeController and LocalLoopExecutor
# ---------------------------------------------------------------------------


def test_local_visible_includes_android_runtime_controller():
    local = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    ids = {s.surface_id for s in local}
    assert "android_runtime_controller_local" in ids, (
        "android_runtime_controller_local must be registered as a "
        "local_visible Android diagnostics surface."
    )


def test_local_visible_includes_android_local_loop_executor():
    local = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    ids = {s.surface_id for s in local}
    assert "android_local_loop_executor" in ids, (
        "android_local_loop_executor must be registered as a "
        "local_visible Android diagnostics surface."
    )


# ---------------------------------------------------------------------------
# 29. Operator-visible surfaces include operator_surface and routes/operator
# ---------------------------------------------------------------------------


def test_operator_visible_includes_operator_surface_projections():
    operator = get_surfaces_by_visibility(VisibilityLevel.operator_visible)
    ids = {s.surface_id for s in operator}
    assert "operator_surface_projections" in ids


def test_operator_visible_includes_routes_operator_endpoints():
    operator = get_surfaces_by_visibility(VisibilityLevel.operator_visible)
    ids = {s.surface_id for s in operator}
    assert "routes_operator_endpoints" in ids


# ---------------------------------------------------------------------------
# 30. Product-visible surfaces include outward_runtime_truth
# ---------------------------------------------------------------------------


def test_product_visible_includes_outward_runtime_truth_compile():
    product = get_surfaces_by_visibility(VisibilityLevel.product_visible)
    ids = {s.surface_id for s in product}
    assert "outward_runtime_truth_compile" in ids, (
        "outward_runtime_truth_compile must be registered as a product_visible "
        "surface (Stage 2 canonical output)."
    )


# ---------------------------------------------------------------------------
# 31. No local_visible surface produces runtime_truth evidence
# ---------------------------------------------------------------------------


def test_no_local_visible_surface_claims_runtime_truth():
    local = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    for surface in local:
        assert surface.evidence_kind != EvidenceContractKind.runtime_truth, (
            f"LOCAL_VISIBLE surface '{surface.surface_id}' claims "
            f"evidence_kind=runtime_truth — bounded subjects cannot produce "
            f"canonical runtime truth."
        )


# ---------------------------------------------------------------------------
# 32. Uplink path surfaces are all in runtime_visible level
# ---------------------------------------------------------------------------


def test_all_uplink_path_surfaces_are_runtime_visible():
    uplink_surfaces = [
        s for s in get_observability_surface_registry()
        if s.is_uplink_path
    ]
    for surface in uplink_surfaces:
        assert surface.visibility_level == VisibilityLevel.runtime_visible, (
            f"Uplink path surface '{surface.surface_id}' has visibility "
            f"level '{surface.visibility_level.value}' instead of "
            f"'runtime_visible'.  Uplink surfaces are runtime infrastructure."
        )


# ---------------------------------------------------------------------------
# 33. Snapshot uplink_path_surfaces matches is_uplink_path=True surfaces
# ---------------------------------------------------------------------------


def test_snapshot_uplink_path_surfaces_matches_registry():
    snap = build_cross_subject_observability_snapshot()
    expected_uplink = {
        s.surface_id
        for s in get_observability_surface_registry()
        if s.is_uplink_path
    }
    assert set(snap.uplink_path_surfaces) == expected_uplink


# ---------------------------------------------------------------------------
# 34. Evidence kind counts in snapshot sum to total_surfaces
# ---------------------------------------------------------------------------


def test_evidence_kind_counts_sum_to_total_surfaces():
    snap = build_cross_subject_observability_snapshot()
    kind_sum = (
        snap.participant_evidence_count
        + snap.diagnostics_evidence_count
        + snap.execution_artifact_count
        + snap.continuity_evidence_count
        + snap.runtime_truth_count
    )
    assert snap.total_surfaces == kind_sum, (
        f"total_surfaces={snap.total_surfaces} != "
        f"sum of evidence kind counts={kind_sum}"
    )


# ---------------------------------------------------------------------------
# 35. Contract authority sentinel includes "PR-12V2" reference keywords
# ---------------------------------------------------------------------------


def test_contract_authority_sentinel_references_pr12v2_semantics():
    """The authority sentinel must reference the formalised uplink contract
    to confirm this module supersedes the TRANSITIONAL field."""
    auth = CROSS_SUBJECT_OBSERVABILITY_CONTRACT_AUTHORITY.lower()
    # Must reference the superseding of the transitional field
    assert "supersedes" in auth or "transitional" in auth, (
        "Authority sentinel must reference superseding the TRANSITIONAL "
        "participant_diagnostics_uplink field."
    )
    # Must reference the 4-level visibility taxonomy
    assert "4-level" in auth or "four" in auth or "local-visible" in auth or "local_visible" in auth


# ---------------------------------------------------------------------------
# Boundary invariant: visibility level ordering is respected
# ---------------------------------------------------------------------------


def test_local_visible_surfaces_have_no_uplink_responsibility():
    """Local-visible surfaces must not be declared as uplink path entries.
    The uplink path is a runtime_visible responsibility."""
    local = get_surfaces_by_visibility(VisibilityLevel.local_visible)
    for surface in local:
        assert surface.is_uplink_path is False, (
            f"LOCAL_VISIBLE surface '{surface.surface_id}' is marked as an "
            f"uplink path surface — local surfaces do not own the uplink; "
            f"the uplink is handled by runtime_visible ingress modules."
        )


def test_operator_visible_surfaces_have_no_uplink_responsibility():
    """Operator-visible surfaces are downstream projections; they must not
    be declared as uplink path entries."""
    operator = get_surfaces_by_visibility(VisibilityLevel.operator_visible)
    for surface in operator:
        assert surface.is_uplink_path is False, (
            f"OPERATOR_VISIBLE surface '{surface.surface_id}' is marked as "
            f"an uplink path surface — operator surfaces are read-only "
            f"projection consumers, not uplink participants."
        )


def test_product_visible_surfaces_have_no_uplink_responsibility():
    """Product-visible surfaces are the outermost consumers; they must not
    be declared as uplink path entries."""
    product = get_surfaces_by_visibility(VisibilityLevel.product_visible)
    for surface in product:
        assert surface.is_uplink_path is False, (
            f"PRODUCT_VISIBLE surface '{surface.surface_id}' is marked as "
            f"an uplink path surface — product-visible surfaces are the "
            f"outermost consumers and have no uplink role."
        )
