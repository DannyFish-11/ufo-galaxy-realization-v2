#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PR-7 truth-vs-projection boundary checks (additive, low-risk)."""

from __future__ import annotations

import pytest

from core.truth_projection_boundary import (
    AuthorityPlane,
    BoundaryRole,
    COMPAT_REGISTRIES_ARE_NOT_AUTHORITY_POLICY,
    PROJECTIONS_ARE_NOT_LIFECYCLE_OWNERS_POLICY,
    SYNC_LAYERS_MUST_NOT_SELF_PROMOTE_POLICY,
    TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY,
    TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL,
    build_plane_boundary_contracts,
    build_truth_projection_boundary_catalog,
    build_truth_projection_boundary_snapshot,
    classify_surface_boundary,
    find_non_canonical_lifecycle_owners,
    get_plane_boundary_contract,
)

try:
    import fastapi  # noqa: F401

    _HAS_FASTAPI = True
except Exception:
    _HAS_FASTAPI = False


def test_authority_and_pr7_sentinel_present() -> None:
    assert "canonical authority" in TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY.lower()
    assert "participant/device/session/capability/execution" in TRUTH_PROJECTION_BOUNDARY_IS_AUTHORITY
    assert "PR-7" in TRUTH_PROJECTION_BOUNDARY_PR7_SENTINEL


def test_policy_strings_are_non_empty() -> None:
    assert "projection/read-model" in PROJECTIONS_ARE_NOT_LIFECYCLE_OWNERS_POLICY
    assert "compatibility registries" in COMPAT_REGISTRIES_ARE_NOT_AUTHORITY_POLICY
    assert "mapping/synchronization" in SYNC_LAYERS_MUST_NOT_SELF_PROMOTE_POLICY


def test_catalog_covers_all_planes_and_has_canonical_truth_entry_each() -> None:
    entries = build_truth_projection_boundary_catalog()
    planes_seen = {entry.plane for entry in entries}
    assert planes_seen == set(AuthorityPlane)
    for plane in AuthorityPlane:
        plane_entries = [entry for entry in entries if entry.plane is plane]
        assert any(entry.role is BoundaryRole.CANONICAL_TRUTH for entry in plane_entries)
        assert any(
            entry.role
            in {
                BoundaryRole.PROJECTION_READ_MODEL,
                BoundaryRole.SYNCHRONIZATION_MAPPING,
                BoundaryRole.COMPATIBILITY_SURFACE,
            }
            for entry in plane_entries
        )


def test_non_canonical_surfaces_do_not_own_lifecycle() -> None:
    violations = find_non_canonical_lifecycle_owners()
    assert violations == []


def test_known_compat_and_projection_surfaces_not_classified_as_truth() -> None:
    assert classify_surface_boundary("device_registry_compat_index") == BoundaryRole.COMPATIBILITY_SURFACE.value
    assert classify_surface_boundary("capability_manager_compat") == BoundaryRole.COMPATIBILITY_SURFACE.value
    assert (
        classify_surface_boundary("runtime_decision_observability_projection")
        == BoundaryRole.PROJECTION_READ_MODEL.value
    )
    assert classify_surface_boundary("core.device_registry.DeviceRegistry") == BoundaryRole.COMPATIBILITY_SURFACE.value


def test_snapshot_has_plane_counts_and_no_lifecycle_violations() -> None:
    snapshot = build_truth_projection_boundary_snapshot()
    assert snapshot["total_surfaces"] >= 15
    assert set(snapshot["planes"].keys()) == {plane.value for plane in AuthorityPlane}
    assert len(snapshot["plane_boundary_contracts"]) == len(AuthorityPlane)
    assert snapshot["non_canonical_lifecycle_owner_violations"] == []


def test_plane_boundary_contracts_make_responsibilities_explicit() -> None:
    contracts = build_plane_boundary_contracts()
    assert {contract.plane for contract in contracts} == set(AuthorityPlane)
    for contract in contracts:
        assert contract.responsibility_summary
        assert len(contract.canonical_truth_surface_ids) >= 1


def test_get_plane_boundary_contract_for_execution_plane() -> None:
    contract = get_plane_boundary_contract(AuthorityPlane.EXECUTION)
    assert "execution lifecycle" in contract.responsibility_summary
    assert "canonical_execution_chain" in contract.canonical_truth_surface_ids
    assert "runtime_decision_observability_projection" in contract.projection_surface_ids
    assert "dispatch_target_selection_mapping" in contract.synchronization_surface_ids


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_present() -> None:
    from core.routes import projection

    sentinel = projection.TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7
    assert "TRUTH_PROJECTION_BOUNDARY_ALIGNED_PR7" in sentinel
    assert "UNAVAILABLE" not in sentinel
