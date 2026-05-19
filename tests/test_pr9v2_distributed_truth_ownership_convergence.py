#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr9v2_distributed_truth_ownership_convergence.py
================================================================
PR-9V2: Distributed Truth / Ownership Semantic Convergence — regression tests.

Locks the following invariants:

1.  Module importable; authority and PR-9V2 sentinel are non-empty strings
    containing expected keywords.
2.  All five policy sentinels are non-empty strings containing expected
    keywords.
3.  OwnershipTruthDomainKind enum — all four expected domain values are present.
4.  OwnershipTruthSurface dataclass — structure and to_dict() are correct.
5.  OwnershipTruthConvergenceSnapshot dataclass — structure and to_dict().
6.  Registry is non-empty and contains surfaces of every domain kind.
7.  classify_ownership_truth_domain() — known and unknown surface IDs.
8.  get_surfaces_by_truth_domain() — filters correctly for each domain.
9.  build_ownership_truth_convergence_snapshot() — aggregate builder
    correctness (counts and android_uplink_canonical_entries).
10. AUTHORITY_TRUTH surfaces — v2_android_truth_ssot and
    android_participant_truth_ingress are classified as authority_truth.
11. android_uplink_canonical_entry flag — at least two surfaces have it True
    and all are classified as authority_truth.
12. ACCEPTANCE_CLOSURE_READINESS_TRUTH surfaces — takeover_tracking and
    canonical_handoff_path are evidence, not authority_truth.
13. OUTWARD_PROJECTION_OPERATOR_TRUTH surfaces — all have
    may_not_redefine_authority_truth=True.
14. DIAGNOSTICS_AUDIT_ARTIFACT surfaces — all have
    may_not_redefine_authority_truth=True.
15. get_android_uplink_canonical_chain_path() — returns a non-empty tuple
    with the SSOT and canonical_session_truth steps present.
16. Snapshot total_surfaces equals the sum of all domain counts.
17. Snapshot has exactly 5 policies.
18. v2_android_truth_ssot.ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY sentinel
    is importable, non-empty, and contains expected keywords.
19. No surface has truth_domain authority_truth AND
    may_not_redefine_authority_truth=True simultaneously (authority surfaces
    may redefine authority truth by definition).
20. Every surface has a non-empty notes field.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from core.distributed_truth_ownership_convergence import (
    ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY,
    DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY,
    DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY,
    DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL,
    NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY,
    OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY,
    OWNERSHIP_TRUTH_SURFACE_REGISTRY,
    PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY,
    OwnershipTruthConvergenceSnapshot,
    OwnershipTruthDomainKind,
    OwnershipTruthSurface,
    build_ownership_truth_convergence_snapshot,
    classify_ownership_truth_domain,
    get_android_uplink_canonical_chain_path,
    get_ownership_truth_registry,
    get_surfaces_by_truth_domain,
)


# ---------------------------------------------------------------------------
# 1. Authority and sentinel non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty_and_keywords() -> None:
    assert isinstance(DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY, str)
    assert DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY
    assert "distributed_truth_ownership_convergence" in (
        DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY.lower()
    )
    assert "authority" in DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_AUTHORITY.lower()


def test_pr9v2_sentinel_non_empty_and_keywords() -> None:
    assert isinstance(DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL, str)
    assert DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL
    assert "pr9v2" in DISTRIBUTED_TRUTH_OWNERSHIP_CONVERGENCE_PR9V2_SENTINEL.lower()


# ---------------------------------------------------------------------------
# 2. Policy sentinels non-empty with expected keywords
# ---------------------------------------------------------------------------


def test_projection_must_not_redefine_policy_present() -> None:
    assert PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY
    assert "PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH" in (
        PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY
    )
    assert "compile_outward_truth" in PROJECTION_MUST_NOT_REDEFINE_AUTHORITY_TRUTH_POLICY


def test_android_uplink_ssot_policy_present() -> None:
    assert ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY
    assert "ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT" in (
        ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY
    )
    assert "build_v2_android_truth_block" in (
        ANDROID_UPLINK_ENTERS_V2_CANONICAL_CHAIN_VIA_SSOT_POLICY
    )


def test_ownership_prototype_evidence_policy_present() -> None:
    assert OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY
    assert "OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE" in (
        OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY
    )
    assert "TakeoverTracking" in OWNERSHIP_PROTOTYPE_IS_EVIDENCE_NOT_CONTROL_PLANE_POLICY


def test_no_new_parallel_truth_fabric_policy_present() -> None:
    assert NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY
    assert "NO_NEW_PARALLEL_TRUTH_FABRIC" in NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY
    assert "v2_android_truth_ssot" in NO_NEW_PARALLEL_TRUTH_FABRIC_POLICY


def test_diagnostics_not_read_back_policy_present() -> None:
    assert DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY
    assert "DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY" in (
        DIAGNOSTICS_MUST_NOT_BE_READ_BACK_AS_AUTHORITY_POLICY
    )


# ---------------------------------------------------------------------------
# 3. OwnershipTruthDomainKind enum — all four expected values
# ---------------------------------------------------------------------------


def test_domain_kind_enum_has_all_four_members() -> None:
    expected = {
        "authority_truth",
        "acceptance_closure_readiness_truth",
        "outward_projection_operator_truth",
        "diagnostics_audit_artifact",
    }
    actual = {member.value for member in OwnershipTruthDomainKind}
    assert actual == expected


# ---------------------------------------------------------------------------
# 4. OwnershipTruthSurface dataclass structure and to_dict()
# ---------------------------------------------------------------------------


def test_ownership_truth_surface_to_dict() -> None:
    surface = OwnershipTruthSurface(
        surface_id="test_surface",
        module_path="core.test_module",
        surface_name="Test Surface",
        truth_domain=OwnershipTruthDomainKind.authority_truth,
        may_not_redefine_authority_truth=False,
        android_uplink_canonical_entry=True,
        notes="Test notes.",
    )
    d = surface.to_dict()
    assert d["surface_id"] == "test_surface"
    assert d["module_path"] == "core.test_module"
    assert d["surface_name"] == "Test Surface"
    assert d["truth_domain"] == "authority_truth"
    assert d["may_not_redefine_authority_truth"] is False
    assert d["android_uplink_canonical_entry"] is True
    assert d["notes"] == "Test notes."


# ---------------------------------------------------------------------------
# 5. OwnershipTruthConvergenceSnapshot dataclass and to_dict()
# ---------------------------------------------------------------------------


def test_convergence_snapshot_to_dict_keys() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    d = snapshot.to_dict()
    required_keys = {
        "authority",
        "sentinel",
        "policies",
        "total_surfaces",
        "authority_truth_count",
        "acceptance_closure_count",
        "outward_projection_count",
        "diagnostics_audit_count",
        "android_uplink_canonical_entries",
        "generated_at",
    }
    assert required_keys.issubset(set(d.keys()))


# ---------------------------------------------------------------------------
# 6. Registry non-empty and all domain kinds represented
# ---------------------------------------------------------------------------


def test_registry_is_non_empty() -> None:
    registry = get_ownership_truth_registry()
    assert len(registry) > 0


def test_registry_contains_all_domain_kinds() -> None:
    registry = get_ownership_truth_registry()
    present_domains = {s.truth_domain for s in registry}
    for kind in OwnershipTruthDomainKind:
        assert kind in present_domains, (
            f"Domain kind {kind!r} has no surfaces in the registry"
        )


# ---------------------------------------------------------------------------
# 7. classify_ownership_truth_domain() — known and unknown
# ---------------------------------------------------------------------------


def test_classify_known_surface_id() -> None:
    result = classify_ownership_truth_domain("canonical_session_truth_authority")
    assert result == OwnershipTruthDomainKind.authority_truth.value


def test_classify_known_module_path() -> None:
    result = classify_ownership_truth_domain(
        "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )
    assert result == OwnershipTruthDomainKind.authority_truth.value


def test_classify_unknown_surface_returns_unknown() -> None:
    result = classify_ownership_truth_domain("nonexistent_surface_xyz")
    assert result == "unknown"


def test_classify_empty_string_returns_unknown() -> None:
    result = classify_ownership_truth_domain("")
    assert result == "unknown"


# ---------------------------------------------------------------------------
# 8. get_surfaces_by_truth_domain() — filters correctly for each domain
# ---------------------------------------------------------------------------


def test_get_surfaces_authority_truth_non_empty() -> None:
    surfaces = get_surfaces_by_truth_domain(OwnershipTruthDomainKind.authority_truth)
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.truth_domain is OwnershipTruthDomainKind.authority_truth


def test_get_surfaces_acceptance_closure_non_empty() -> None:
    surfaces = get_surfaces_by_truth_domain(
        OwnershipTruthDomainKind.acceptance_closure_readiness_truth
    )
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.truth_domain is (
            OwnershipTruthDomainKind.acceptance_closure_readiness_truth
        )


def test_get_surfaces_outward_projection_non_empty() -> None:
    surfaces = get_surfaces_by_truth_domain(
        OwnershipTruthDomainKind.outward_projection_operator_truth
    )
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.truth_domain is (
            OwnershipTruthDomainKind.outward_projection_operator_truth
        )


def test_get_surfaces_diagnostics_audit_non_empty() -> None:
    surfaces = get_surfaces_by_truth_domain(
        OwnershipTruthDomainKind.diagnostics_audit_artifact
    )
    assert len(surfaces) > 0
    for s in surfaces:
        assert s.truth_domain is OwnershipTruthDomainKind.diagnostics_audit_artifact


# ---------------------------------------------------------------------------
# 9. build_ownership_truth_convergence_snapshot() — aggregate correctness
# ---------------------------------------------------------------------------


def test_snapshot_counts_are_consistent() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    expected_total = (
        snapshot.authority_truth_count
        + snapshot.acceptance_closure_count
        + snapshot.outward_projection_count
        + snapshot.diagnostics_audit_count
    )
    assert snapshot.total_surfaces == expected_total
    assert snapshot.total_surfaces > 0


def test_snapshot_has_five_policies() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    assert len(snapshot.policies) == 5


def test_snapshot_android_uplink_entries_non_empty() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    assert len(snapshot.android_uplink_canonical_entries) >= 2


# ---------------------------------------------------------------------------
# 10. AUTHORITY_TRUTH surfaces — SSOT and participant ingress are classified
# ---------------------------------------------------------------------------


def test_v2_android_truth_ssot_is_authority_truth() -> None:
    result = classify_ownership_truth_domain(
        "core.v2_android_truth_ssot.build_v2_android_truth_block"
    )
    assert result == "authority_truth"


def test_android_participant_truth_ingress_is_authority_truth() -> None:
    result = classify_ownership_truth_domain("core.android_participant_truth_ingress")
    assert result == "authority_truth"


def test_canonical_session_truth_is_authority_truth() -> None:
    result = classify_ownership_truth_domain("canonical_session_truth_authority")
    assert result == "authority_truth"


# ---------------------------------------------------------------------------
# 11. android_uplink_canonical_entry flag — at least two, all authority_truth
# ---------------------------------------------------------------------------


def test_android_uplink_canonical_entries_are_authority_truth() -> None:
    registry = get_ownership_truth_registry()
    uplink_entries = [s for s in registry if s.android_uplink_canonical_entry]
    assert len(uplink_entries) >= 2
    for s in uplink_entries:
        assert s.truth_domain is OwnershipTruthDomainKind.authority_truth, (
            f"Surface {s.surface_id!r} has android_uplink_canonical_entry=True "
            f"but is not classified as authority_truth (got {s.truth_domain!r})"
        )


# ---------------------------------------------------------------------------
# 12. Ownership/handoff prototypes are evidence, not authority_truth
# ---------------------------------------------------------------------------


def test_takeover_tracking_is_acceptance_closure_not_authority() -> None:
    result = classify_ownership_truth_domain("takeover_tracking_evidence")
    assert result == "acceptance_closure_readiness_truth"


def test_canonical_handoff_path_is_acceptance_closure_not_authority() -> None:
    result = classify_ownership_truth_domain("canonical_handoff_path_evidence")
    assert result == "acceptance_closure_readiness_truth"


def test_android_delegated_lifecycle_coordinator_is_evidence() -> None:
    result = classify_ownership_truth_domain(
        "android_delegated_lifecycle_coordinator_evidence"
    )
    assert result == "acceptance_closure_readiness_truth"


def test_no_handoff_prototype_is_authority_truth() -> None:
    registry = get_ownership_truth_registry()
    prototype_module_fragments = {
        "takeover_tracking",
        "canonical_handoff_path",
        "android_handoff_v2_response_ingress",
        "android_delegated_runtime_lifecycle_coordinator",
    }
    for s in registry:
        for fragment in prototype_module_fragments:
            if fragment in s.module_path:
                assert s.truth_domain is not OwnershipTruthDomainKind.authority_truth, (
                    f"Handoff/prototype surface {s.surface_id!r} must not be "
                    f"classified as authority_truth"
                )


# ---------------------------------------------------------------------------
# 13. Outward projection surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_outward_projection_surfaces_may_not_redefine_authority() -> None:
    surfaces = get_surfaces_by_truth_domain(
        OwnershipTruthDomainKind.outward_projection_operator_truth
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"Outward projection surface {s.surface_id!r} must have "
            f"may_not_redefine_authority_truth=True"
        )


# ---------------------------------------------------------------------------
# 14. Diagnostics audit surfaces — all have may_not_redefine=True
# ---------------------------------------------------------------------------


def test_diagnostics_audit_surfaces_may_not_redefine_authority() -> None:
    surfaces = get_surfaces_by_truth_domain(
        OwnershipTruthDomainKind.diagnostics_audit_artifact
    )
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is True, (
            f"Diagnostics surface {s.surface_id!r} must have "
            f"may_not_redefine_authority_truth=True"
        )


# ---------------------------------------------------------------------------
# 15. get_android_uplink_canonical_chain_path() — non-empty with SSOT step
# ---------------------------------------------------------------------------


def test_android_uplink_chain_path_non_empty() -> None:
    path = get_android_uplink_canonical_chain_path()
    assert isinstance(path, tuple)
    assert len(path) >= 4


def test_android_uplink_chain_path_contains_ssot() -> None:
    path = get_android_uplink_canonical_chain_path()
    assert any("v2_android_truth_ssot" in step for step in path), (
        "Canonical Android uplink chain must include v2_android_truth_ssot step"
    )


def test_android_uplink_chain_path_contains_canonical_session_truth() -> None:
    path = get_android_uplink_canonical_chain_path()
    assert any("canonical_session_truth" in step for step in path), (
        "Canonical Android uplink chain must include canonical_session_truth step"
    )


def test_android_uplink_chain_path_contains_android_handlers() -> None:
    path = get_android_uplink_canonical_chain_path()
    assert any("android" in step.lower() for step in path), (
        "Canonical Android uplink chain must include an android gateway step"
    )


# ---------------------------------------------------------------------------
# 16. Snapshot total_surfaces == sum of domain counts
# ---------------------------------------------------------------------------


def test_snapshot_total_equals_sum_of_domain_counts() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    total = (
        snapshot.authority_truth_count
        + snapshot.acceptance_closure_count
        + snapshot.outward_projection_count
        + snapshot.diagnostics_audit_count
    )
    assert snapshot.total_surfaces == total


# ---------------------------------------------------------------------------
# 17. Snapshot to_dict() policies is a list of 5 non-empty strings
# ---------------------------------------------------------------------------


def test_snapshot_to_dict_policies_are_five_non_empty_strings() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    d = snapshot.to_dict()
    policies = d["policies"]
    assert isinstance(policies, list)
    assert len(policies) == 5
    for p in policies:
        assert isinstance(p, str) and p


# ---------------------------------------------------------------------------
# 18. v2_android_truth_ssot.ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY
# ---------------------------------------------------------------------------


def test_android_uplink_canonical_truth_entry_sentinel_importable() -> None:
    from core.v2_android_truth_ssot import ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY

    assert isinstance(ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY, str)
    assert ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY


def test_android_uplink_canonical_truth_entry_contains_keywords() -> None:
    from core.v2_android_truth_ssot import ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY

    assert "ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY" in ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY
    assert "build_v2_android_truth_block" in ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY
    assert "PR9V2" in ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY


def test_android_uplink_canonical_truth_entry_mentions_chain() -> None:
    from core.v2_android_truth_ssot import ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY

    assert "canonical_session_truth" in ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY
    assert "compile_outward_truth" in ANDROID_UPLINK_CANONICAL_TRUTH_ENTRY


# ---------------------------------------------------------------------------
# 19. Authority surfaces may_not_redefine_authority_truth consistency
# ---------------------------------------------------------------------------


def test_no_authority_truth_surface_has_may_not_redefine_true() -> None:
    """Authority truth surfaces by definition may set authority truth.

    They must NOT have may_not_redefine_authority_truth=True.
    """
    surfaces = get_surfaces_by_truth_domain(OwnershipTruthDomainKind.authority_truth)
    for s in surfaces:
        assert s.may_not_redefine_authority_truth is False, (
            f"Authority truth surface {s.surface_id!r} must have "
            f"may_not_redefine_authority_truth=False (they are the authority)"
        )


# ---------------------------------------------------------------------------
# 20. Every surface has a non-empty notes field
# ---------------------------------------------------------------------------


def test_every_surface_has_non_empty_notes() -> None:
    registry = get_ownership_truth_registry()
    for s in registry:
        assert s.notes and s.notes.strip(), (
            f"Surface {s.surface_id!r} has an empty notes field"
        )


# ---------------------------------------------------------------------------
# Bonus: snapshot generated_at is a positive float
# ---------------------------------------------------------------------------


def test_snapshot_generated_at_is_positive_float() -> None:
    snapshot = build_ownership_truth_convergence_snapshot()
    assert isinstance(snapshot.generated_at, float)
    assert snapshot.generated_at > 0
