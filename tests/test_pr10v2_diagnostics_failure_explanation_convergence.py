#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr10v2_diagnostics_failure_explanation_convergence.py
====================================================================
PR-10V2: Diagnostics / Failure / Explanation Semantic Boundary Convergence —
regression tests.

Locks the following invariants:

1.  Module importable; authority and PR-10V2 sentinel are non-empty strings
    containing expected keywords.
2.  All five policy sentinels are non-empty strings containing expected
    keywords.
3.  DiagnosticsSemanticKind enum — all five expected kind values are present.
4.  DiagnosticsSemanticSurface dataclass — structure and to_dict() are correct.
5.  DiagnosticsFailureConvergenceSnapshot dataclass — structure and to_dict().
6.  Registry is non-empty and contains surfaces of every semantic kind.
7.  classify_diagnostics_semantic_kind() — known and unknown surface IDs.
8.  get_surfaces_by_semantic_kind() — filters correctly for each kind.
9.  build_diagnostics_failure_convergence_snapshot() — aggregate builder
    correctness (counts and android_diagnostics_uplink_surfaces).
10. AUTHORITY_EXECUTION_TRUTH surfaces — canonical runtime authority modules
    are classified as authority_execution_truth.
11. android_diagnostics_uplink flag — at least two surfaces have it True
    and include artifact ingress and failure signal ingress.
12. FAILURE_DIAGNOSTICS_TRUTH surfaces — all have
    may_not_redefine_authority_truth=True and are NOT authority kind.
13. ARTIFACT_EVIDENCE_TRUTH surfaces — all have
    may_not_redefine_authority_truth=True; none are closure/acceptance kind.
14. OPERATOR_SUMMARY_EXPLANATION surfaces — all have
    may_not_redefine_authority_truth=True.
15. AUDIT_POSTRUN_INTERPRETATION surfaces — all have
    may_not_redefine_authority_truth=True.
16. get_android_diagnostics_uplink_path() — returns a non-empty tuple
    containing key uplink steps.
17. Snapshot total_surfaces equals the sum of all kind counts.
18. Snapshot has exactly 5 policies.
19. authority_execution_truth surfaces do NOT have
    may_not_redefine_authority_truth=True (authority surfaces may define truth).
20. Every surface has a non-empty notes field.
21. No surface has both authority_execution_truth kind AND
    may_not_redefine_authority_truth=True simultaneously.
22. Summary/explanation policy sentinel explicitly references "MUST NOT
    redefine" semantics.
23. Diagnostics policy sentinel explicitly references "MUST NOT be read back"
    semantics.
24. Artifact policy sentinel explicitly references "not closure decision"
    semantics.
25. Audit policy sentinel explicitly references "retrospective" semantics.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from core.diagnostics_failure_explanation_convergence import (
    ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY,
    AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY,
    DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY,
    DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL,
    DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY,
    DIAGNOSTICS_SEMANTIC_SURFACE_REGISTRY,
    NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY,
    SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY,
    DiagnosticsFailureConvergenceSnapshot,
    DiagnosticsSemanticKind,
    DiagnosticsSemanticSurface,
    build_diagnostics_failure_convergence_snapshot,
    classify_diagnostics_semantic_kind,
    get_android_diagnostics_uplink_path,
    get_diagnostics_surface_registry,
    get_surfaces_by_semantic_kind,
)


# ---------------------------------------------------------------------------
# 1. Authority and sentinel non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty_and_keywords() -> None:
    assert isinstance(DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY, str)
    assert DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY
    assert "diagnostics_failure_explanation_convergence" in (
        DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY.lower()
    )
    assert "authority" in (
        DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY.lower()
    )


def test_pr10v2_sentinel_non_empty_and_keywords() -> None:
    assert isinstance(
        DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL, str
    )
    assert DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL
    assert "pr10v2" in (
        DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL.lower()
    )
    assert "boundary_locked" in (
        DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL.lower()
    )


# ---------------------------------------------------------------------------
# 2. All five policy sentinels are non-empty strings with expected keywords
# ---------------------------------------------------------------------------


def test_summary_policy_non_empty_and_keywords() -> None:
    assert isinstance(SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY, str)
    assert SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY
    assert "must not" in SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY.lower()
    assert "authority" in SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY.lower()


def test_diagnostics_policy_non_empty_and_keywords() -> None:
    assert isinstance(
        DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY, str
    )
    assert DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY
    assert "must not" in (
        DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY.lower()
    )
    assert "acceptance" in (
        DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY.lower()
    )


def test_artifact_policy_non_empty_and_keywords() -> None:
    assert isinstance(ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY, str)
    assert ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY
    assert "closure" in ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY.lower()
    assert "not" in ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY.lower()


def test_audit_policy_non_empty_and_keywords() -> None:
    assert isinstance(AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY, str)
    assert AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY
    assert "retrospective" in (
        AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY.lower()
    )


def test_no_parallel_platform_policy_non_empty_and_keywords() -> None:
    assert isinstance(NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY, str)
    assert NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY
    assert "parallel" in NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY.lower()
    assert "diagnostics" in NO_NEW_PARALLEL_DIAGNOSTICS_PLATFORM_POLICY.lower()


# ---------------------------------------------------------------------------
# 3. DiagnosticsSemanticKind enum — all five values present
# ---------------------------------------------------------------------------


def test_diagnostics_semantic_kind_all_five_values() -> None:
    values = {k.value for k in DiagnosticsSemanticKind}
    assert "authority_execution_truth" in values
    assert "failure_diagnostics_truth" in values
    assert "artifact_evidence_truth" in values
    assert "operator_summary_explanation" in values
    assert "audit_postrun_interpretation" in values
    assert len(values) == 5


# ---------------------------------------------------------------------------
# 4. DiagnosticsSemanticSurface dataclass structure and to_dict()
# ---------------------------------------------------------------------------


def test_diagnostics_semantic_surface_construction_and_to_dict() -> None:
    surface = DiagnosticsSemanticSurface(
        surface_id="test_surface",
        module_path="core.test_module",
        surface_name="Test Surface",
        semantic_kind=DiagnosticsSemanticKind.failure_diagnostics_truth,
        may_not_redefine_authority_truth=True,
        android_diagnostics_uplink=False,
        notes="Test notes.",
    )
    d = surface.to_dict()
    assert d["surface_id"] == "test_surface"
    assert d["module_path"] == "core.test_module"
    assert d["surface_name"] == "Test Surface"
    assert d["semantic_kind"] == "failure_diagnostics_truth"
    assert d["may_not_redefine_authority_truth"] is True
    assert d["android_diagnostics_uplink"] is False
    assert d["notes"] == "Test notes."


# ---------------------------------------------------------------------------
# 5. DiagnosticsFailureConvergenceSnapshot dataclass structure and to_dict()
# ---------------------------------------------------------------------------


def test_diagnostics_failure_convergence_snapshot_construction() -> None:
    snap = DiagnosticsFailureConvergenceSnapshot(
        authority="test_authority",
        sentinel="test_sentinel",
        policies=("policy_a", "policy_b"),
        total_surfaces=10,
        authority_execution_truth_count=3,
        failure_diagnostics_count=3,
        artifact_evidence_count=2,
        operator_summary_count=1,
        audit_postrun_count=1,
        android_diagnostics_uplink_surfaces=["surf_a"],
    )
    d = snap.to_dict()
    assert d["authority"] == "test_authority"
    assert d["sentinel"] == "test_sentinel"
    assert d["policies"] == ["policy_a", "policy_b"]
    assert d["total_surfaces"] == 10
    assert d["authority_execution_truth_count"] == 3
    assert d["failure_diagnostics_count"] == 3
    assert d["artifact_evidence_count"] == 2
    assert d["operator_summary_count"] == 1
    assert d["audit_postrun_count"] == 1
    assert d["android_diagnostics_uplink_surfaces"] == ["surf_a"]
    assert "generated_at" in d


# ---------------------------------------------------------------------------
# 6. Registry is non-empty and contains surfaces of every semantic kind
# ---------------------------------------------------------------------------


def test_registry_non_empty() -> None:
    registry = get_diagnostics_surface_registry()
    assert len(registry) >= 5, "Registry must have at least one surface per kind"


def test_registry_has_all_five_kinds() -> None:
    registry = get_diagnostics_surface_registry()
    present_kinds = {s.semantic_kind for s in registry}
    for kind in DiagnosticsSemanticKind:
        assert kind in present_kinds, (
            f"No surface registered for semantic kind: {kind.value}"
        )


# ---------------------------------------------------------------------------
# 7. classify_diagnostics_semantic_kind() — known and unknown IDs
# ---------------------------------------------------------------------------


def test_classify_known_surface_id() -> None:
    registry = get_diagnostics_surface_registry()
    first = registry[0]
    result = classify_diagnostics_semantic_kind(first.surface_id)
    assert result == first.semantic_kind.value


def test_classify_unknown_surface_id_returns_unknown() -> None:
    result = classify_diagnostics_semantic_kind("__nonexistent_surface_id__")
    assert result == "unknown"


# ---------------------------------------------------------------------------
# 8. get_surfaces_by_semantic_kind() — filters correctly
# ---------------------------------------------------------------------------


def test_get_surfaces_by_semantic_kind_authority() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.authority_execution_truth
    )
    assert len(surfaces) >= 1
    for s in surfaces:
        assert s.semantic_kind == DiagnosticsSemanticKind.authority_execution_truth


def test_get_surfaces_by_semantic_kind_failure_diagnostics() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.failure_diagnostics_truth
    )
    assert len(surfaces) >= 1
    for s in surfaces:
        assert s.semantic_kind == DiagnosticsSemanticKind.failure_diagnostics_truth


def test_get_surfaces_by_semantic_kind_artifact() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.artifact_evidence_truth
    )
    assert len(surfaces) >= 1
    for s in surfaces:
        assert s.semantic_kind == DiagnosticsSemanticKind.artifact_evidence_truth


def test_get_surfaces_by_semantic_kind_operator_summary() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.operator_summary_explanation
    )
    assert len(surfaces) >= 1
    for s in surfaces:
        assert s.semantic_kind == DiagnosticsSemanticKind.operator_summary_explanation


def test_get_surfaces_by_semantic_kind_audit_postrun() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.audit_postrun_interpretation
    )
    assert len(surfaces) >= 1
    for s in surfaces:
        assert s.semantic_kind == DiagnosticsSemanticKind.audit_postrun_interpretation


# ---------------------------------------------------------------------------
# 9. build_diagnostics_failure_convergence_snapshot() correctness
# ---------------------------------------------------------------------------


def test_snapshot_builder_returns_snapshot_type() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    assert isinstance(snap, DiagnosticsFailureConvergenceSnapshot)


def test_snapshot_authority_and_sentinel_populated() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    assert snap.authority == DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_AUTHORITY
    assert snap.sentinel == DIAGNOSTICS_FAILURE_EXPLANATION_CONVERGENCE_PR10V2_SENTINEL


def test_snapshot_total_surfaces_positive() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    assert snap.total_surfaces >= 5


def test_snapshot_android_uplink_surfaces_non_empty() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    assert len(snap.android_diagnostics_uplink_surfaces) >= 2


# ---------------------------------------------------------------------------
# 10. AUTHORITY_EXECUTION_TRUTH surfaces
# ---------------------------------------------------------------------------


def test_authority_execution_truth_surfaces_exist() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.authority_execution_truth
    )
    ids = {s.surface_id for s in surfaces}
    # At least one execution authority module is registered
    assert any(
        "runtime" in sid or "execution" in sid or "chain" in sid
        for sid in ids
    ), f"No execution-authority surface found; got: {ids}"


# ---------------------------------------------------------------------------
# 11. android_diagnostics_uplink — at least two surfaces flagged True
# ---------------------------------------------------------------------------


def test_android_diagnostics_uplink_surfaces_count() -> None:
    registry = get_diagnostics_surface_registry()
    uplink_surfaces = [s for s in registry if s.android_diagnostics_uplink]
    assert len(uplink_surfaces) >= 2, (
        f"Expected ≥2 android_diagnostics_uplink surfaces; "
        f"got {len(uplink_surfaces)}"
    )


def test_android_diagnostics_uplink_includes_artifact_ingress() -> None:
    registry = get_diagnostics_surface_registry()
    uplink_ids = {s.surface_id for s in registry if s.android_diagnostics_uplink}
    assert any("artifact" in sid or "evaluator" in sid for sid in uplink_ids), (
        f"No Android evaluator artifact surface in uplink chain; "
        f"uplink IDs: {uplink_ids}"
    )


def test_android_diagnostics_uplink_includes_failure_signal_ingress() -> None:
    registry = get_diagnostics_surface_registry()
    uplink_ids = {s.surface_id for s in registry if s.android_diagnostics_uplink}
    assert any("failure" in sid or "ingress" in sid or "android" in sid.lower()
               for sid in uplink_ids), (
        f"No Android failure signal ingress in uplink chain; "
        f"uplink IDs: {uplink_ids}"
    )


# ---------------------------------------------------------------------------
# 12. FAILURE_DIAGNOSTICS_TRUTH surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_failure_diagnostics_surfaces_may_not_redefine() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.failure_diagnostics_truth
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"failure_diagnostics_truth surface {s.surface_id!r} has "
            f"may_not_redefine_authority_truth=False — only authority "
            f"surfaces may redefine authority truth"
        )


# ---------------------------------------------------------------------------
# 13. ARTIFACT_EVIDENCE_TRUTH surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_artifact_evidence_surfaces_may_not_redefine() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.artifact_evidence_truth
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"artifact_evidence_truth surface {s.surface_id!r} has "
            f"may_not_redefine_authority_truth=False"
        )


# ---------------------------------------------------------------------------
# 14. OPERATOR_SUMMARY_EXPLANATION surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_operator_summary_surfaces_may_not_redefine() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.operator_summary_explanation
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"operator_summary_explanation surface {s.surface_id!r} has "
            f"may_not_redefine_authority_truth=False"
        )


# ---------------------------------------------------------------------------
# 15. AUDIT_POSTRUN_INTERPRETATION surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_audit_postrun_surfaces_may_not_redefine() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.audit_postrun_interpretation
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"audit_postrun_interpretation surface {s.surface_id!r} has "
            f"may_not_redefine_authority_truth=False"
        )


# ---------------------------------------------------------------------------
# 16. get_android_diagnostics_uplink_path() — non-empty tuple with key steps
# ---------------------------------------------------------------------------


def test_android_diagnostics_uplink_path_non_empty_tuple() -> None:
    path = get_android_diagnostics_uplink_path()
    assert isinstance(path, tuple)
    assert len(path) >= 4


def test_android_diagnostics_uplink_path_contains_ssot_step() -> None:
    path = get_android_diagnostics_uplink_path()
    combined = " ".join(path).lower()
    assert "v2_android_truth_ssot" in combined or "ssot" in combined, (
        f"Uplink path does not reference SSOT build step: {path}"
    )


def test_android_diagnostics_uplink_path_contains_projection_step() -> None:
    path = get_android_diagnostics_uplink_path()
    combined = " ".join(path).lower()
    assert "stage 3" in combined or "projection" in combined, (
        f"Uplink path does not reference Stage 3 projection: {path}"
    )


# ---------------------------------------------------------------------------
# 17. Snapshot total_surfaces == sum of all kind counts
# ---------------------------------------------------------------------------


def test_snapshot_total_surfaces_equals_sum_of_counts() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    computed_sum = (
        snap.authority_execution_truth_count
        + snap.failure_diagnostics_count
        + snap.artifact_evidence_count
        + snap.operator_summary_count
        + snap.audit_postrun_count
    )
    assert snap.total_surfaces == computed_sum, (
        f"total_surfaces ({snap.total_surfaces}) != sum of counts "
        f"({computed_sum})"
    )


# ---------------------------------------------------------------------------
# 18. Snapshot has exactly 5 policies
# ---------------------------------------------------------------------------


def test_snapshot_has_exactly_five_policies() -> None:
    snap = build_diagnostics_failure_convergence_snapshot()
    assert len(snap.policies) == 5, (
        f"Expected exactly 5 policies; got {len(snap.policies)}"
    )


# ---------------------------------------------------------------------------
# 19. authority_execution_truth surfaces may_not_redefine_authority_truth=False
# ---------------------------------------------------------------------------


def test_authority_execution_truth_surfaces_may_redefine() -> None:
    surfaces = get_surfaces_by_semantic_kind(
        DiagnosticsSemanticKind.authority_execution_truth
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is False, (
            f"authority_execution_truth surface {s.surface_id!r} has "
            f"may_not_redefine_authority_truth=True — authority surfaces "
            f"must be able to define authority truth"
        )


# ---------------------------------------------------------------------------
# 20. Every surface has a non-empty notes field
# ---------------------------------------------------------------------------


def test_every_surface_has_non_empty_notes() -> None:
    registry = get_diagnostics_surface_registry()
    for s in registry:
        assert s.notes, (
            f"Surface {s.surface_id!r} has an empty notes field"
        )


# ---------------------------------------------------------------------------
# 21. No surface has both authority_execution_truth AND
#     may_not_redefine_authority_truth=True
# ---------------------------------------------------------------------------


def test_no_authority_surface_with_may_not_redefine_true() -> None:
    registry = get_diagnostics_surface_registry()
    violations = [
        s.surface_id
        for s in registry
        if (
            s.semantic_kind == DiagnosticsSemanticKind.authority_execution_truth
            and s.may_not_redefine_authority_truth is True
        )
    ]
    assert not violations, (
        f"Surfaces with authority_execution_truth kind AND "
        f"may_not_redefine_authority_truth=True (contradiction): {violations}"
    )


# ---------------------------------------------------------------------------
# 22. Summary policy references "MUST NOT redefine"
# ---------------------------------------------------------------------------


def test_summary_policy_references_must_not_redefine() -> None:
    policy = SUMMARY_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY.lower()
    assert "must not" in policy
    assert "redefine" in policy or "reverse-inject" in policy


# ---------------------------------------------------------------------------
# 23. Diagnostics policy references "MUST NOT be read back"
# ---------------------------------------------------------------------------


def test_diagnostics_policy_references_must_not_be_read_back() -> None:
    policy = DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_ACCEPTANCE_INPUT_POLICY.lower()
    assert "must not" in policy
    assert "read back" in policy or "acceptance" in policy


# ---------------------------------------------------------------------------
# 24. Artifact policy references "not closure decision"
# ---------------------------------------------------------------------------


def test_artifact_policy_references_not_closure() -> None:
    policy = ARTIFACT_EVIDENCE_IS_NOT_CLOSURE_DECISION_POLICY.lower()
    assert "closure" in policy
    assert "not" in policy


# ---------------------------------------------------------------------------
# 25. Audit policy references "retrospective"
# ---------------------------------------------------------------------------


def test_audit_policy_references_retrospective() -> None:
    policy = AUDIT_POSTRUN_IS_RETROSPECTIVE_NOT_PRESCRIPTIVE_POLICY.lower()
    assert "retrospective" in policy
