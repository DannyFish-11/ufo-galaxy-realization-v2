#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr10_architecture_stabilization_baseline.py
===========================================================
PR-10 (realization-v2 convergence plan): Architecture Stabilization Baseline
tests.

Coverage groups
---------------
A  — Authority / PR-10 sentinel presence and correctness.
B  — Policy sentinels: all four present, non-empty, contain expected keywords.
C  — StabilizationTier enum: all four values present; from_string() round-trip
     and error path.
D  — SurfaceCategory enum: all expected values present.
E  — StabilizationSurfaceRecord: construction, to_dict() shape and values.
F  — StabilizationBaselineSnapshot: construction, to_dict() shape.
G  — get_baseline_catalog(): returns non-empty list of
     StabilizationSurfaceRecord objects; all surface_ids are unique.
H  — get_canonical_stable_surfaces(): returns only CANONICAL_STABLE records;
     count >= 1; is_extension_ready True for all.
I  — get_transitional_surfaces(): returns only TRANSITIONAL_CONVERGING records;
     is_extension_ready False for all; all have canonical_replacement set.
J  — get_extension_surfaces(): returns only EXTENSION_SURFACE records;
     is_extension_ready True for all.
K  — get_compat_bridge_surfaces(): returns only COMPATIBILITY_BRIDGE records;
     is_extension_ready False for all; all have canonical_replacement set.
L  — classify_surface_tier(): returns correct tier for known surface_ids.
M  — classify_surface_tier(): returns None for unknown surface_id.
N  — build_stabilization_baseline_snapshot(): returns populated
     StabilizationBaselineSnapshot; counts are consistent with catalog.
O  — Snapshot: total_surface_count equals sum of all tier counts.
P  — Snapshot: extension_ready_count equals count of surfaces with
     is_extension_ready=True.
Q  — Snapshot: policy_sentinels list contains all four policy strings.
R  — Snapshot: snapshotted_at is a recent timestamp.
S  — Snapshot to_dict(): includes all expected top-level keys.
T  — Snapshot to_dict(): 'surfaces' list length equals total_surface_count.
U  — Each surface record to_dict() includes all required keys.
V  — Projection alignment sentinel: importable and not UNAVAILABLE (fastapi
     guard).
W  — Sentinel strings contain expected PR-10 keywords.
X  — Key canonical-stable surfaces are present in catalog by surface_id.
Y  — Key transitional surfaces are present in catalog with correct fields.
Z  — Key compat-bridge surfaces are present in catalog.
AA — Catalog: no surface has is_extension_ready=True if tier is
     TRANSITIONAL_CONVERGING or COMPATIBILITY_BRIDGE.
AB — Catalog: all CANONICAL_STABLE and EXTENSION_SURFACE surfaces have
     canonical_replacement=None.
AC — StabilizationTier.from_string(): unknown value raises ValueError.
AD — StabilizationBaselineSnapshot: defaults produce a valid object with
     empty lists and zero counts.
AE — build_stabilization_baseline_snapshot() called twice returns independent
     snapshot objects with the same structure.
"""

from __future__ import annotations

import importlib.util
import time
from typing import Any, Dict

import pytest

from core.architecture_stabilization_baseline import (
    ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY,
    ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL,
    CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY,
    COMPAT_BRIDGES_MUST_NOT_GROW_POLICY,
    EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY,
    TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY,
    StabilizationBaselineSnapshot,
    StabilizationSurfaceRecord,
    StabilizationTier,
    SurfaceCategory,
    build_stabilization_baseline_snapshot,
    classify_surface_tier,
    get_baseline_catalog,
    get_canonical_stable_surfaces,
    get_compat_bridge_surfaces,
    get_extension_surfaces,
    get_transitional_surfaces,
)

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


# ---------------------------------------------------------------------------
# A. Authority / PR-10 sentinel presence and correctness
# ---------------------------------------------------------------------------


def test_a01_authority_sentinel_is_non_empty_string() -> None:
    assert isinstance(ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY, str)
    assert ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY


def test_a02_pr10_sentinel_is_non_empty_string() -> None:
    assert isinstance(ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL, str)
    assert ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL


def test_a03_authority_sentinel_contains_module_reference() -> None:
    assert "core.architecture_stabilization_baseline" in ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY


def test_a04_pr10_sentinel_contains_pr10_keyword() -> None:
    assert "PR-10" in ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL


# ---------------------------------------------------------------------------
# B. Policy sentinels
# ---------------------------------------------------------------------------


def test_b01_canonical_stable_extension_points_policy_present() -> None:
    assert isinstance(CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY, str)
    assert "CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS" in CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY


def test_b02_transitional_must_converge_policy_present() -> None:
    assert isinstance(TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY, str)
    assert "TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND" in TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY


def test_b03_extension_must_use_canonical_policy_present() -> None:
    assert isinstance(EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY, str)
    assert "EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY" in EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY


def test_b04_compat_bridges_must_not_grow_policy_present() -> None:
    assert isinstance(COMPAT_BRIDGES_MUST_NOT_GROW_POLICY, str)
    assert "COMPAT_BRIDGES_MUST_NOT_GROW" in COMPAT_BRIDGES_MUST_NOT_GROW_POLICY


def test_b05_all_four_policies_non_empty() -> None:
    for policy in (
        CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS_POLICY,
        TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND_POLICY,
        EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY_POLICY,
        COMPAT_BRIDGES_MUST_NOT_GROW_POLICY,
    ):
        assert policy, f"Policy sentinel unexpectedly empty: {policy!r}"


# ---------------------------------------------------------------------------
# C. StabilizationTier enum
# ---------------------------------------------------------------------------


def test_c01_all_four_tier_values_present() -> None:
    values = {t.value for t in StabilizationTier}
    assert "canonical_stable" in values
    assert "transitional_converging" in values
    assert "extension_surface" in values
    assert "compatibility_bridge" in values


def test_c02_from_string_canonical_stable() -> None:
    tier = StabilizationTier.from_string("canonical_stable")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_c03_from_string_transitional_converging() -> None:
    tier = StabilizationTier.from_string("transitional_converging")
    assert tier == StabilizationTier.TRANSITIONAL_CONVERGING


def test_c04_from_string_extension_surface() -> None:
    tier = StabilizationTier.from_string("extension_surface")
    assert tier == StabilizationTier.EXTENSION_SURFACE


def test_c05_from_string_compatibility_bridge() -> None:
    tier = StabilizationTier.from_string("compatibility_bridge")
    assert tier == StabilizationTier.COMPATIBILITY_BRIDGE


# D. SurfaceCategory enum


def test_d01_surface_category_has_governance_authority() -> None:
    assert SurfaceCategory.GOVERNANCE_AUTHORITY.value == "governance_authority"


def test_d02_surface_category_has_truth_owner() -> None:
    assert SurfaceCategory.TRUTH_OWNER.value == "truth_owner"


def test_d03_surface_category_has_truth_compilation() -> None:
    assert SurfaceCategory.TRUTH_COMPILATION.value == "truth_compilation"


def test_d04_surface_category_has_projection_output() -> None:
    assert SurfaceCategory.PROJECTION_OUTPUT.value == "projection_output"


def test_d05_surface_category_has_dispatch_orchestration() -> None:
    assert SurfaceCategory.DISPATCH_ORCHESTRATION.value == "dispatch_orchestration"


def test_d06_surface_category_has_session_lifecycle() -> None:
    assert SurfaceCategory.SESSION_LIFECYCLE.value == "session_lifecycle"


def test_d07_surface_category_has_capability_scheduling() -> None:
    assert SurfaceCategory.CAPABILITY_SCHEDULING.value == "capability_scheduling"


def test_d08_surface_category_has_node_registry() -> None:
    assert SurfaceCategory.NODE_REGISTRY.value == "node_registry"


def test_d09_surface_category_has_node_invocation() -> None:
    assert SurfaceCategory.NODE_INVOCATION.value == "node_invocation"


def test_d10_surface_category_has_long_tail_compat() -> None:
    assert SurfaceCategory.LONG_TAIL_COMPAT.value == "long_tail_compat"


def test_d11_surface_category_has_compatibility_layer() -> None:
    assert SurfaceCategory.COMPATIBILITY_LAYER.value == "compatibility_layer"


# ---------------------------------------------------------------------------
# E. StabilizationSurfaceRecord dataclass
# ---------------------------------------------------------------------------


def test_e01_surface_record_construction() -> None:
    record = StabilizationSurfaceRecord(
        surface_id="test_surface",
        surface_name="Test Surface",
        module_path="core.test_module",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.GOVERNANCE_AUTHORITY,
        is_extension_ready=True,
        pr_introduced="PR-10",
        rationale="Test rationale.",
    )
    assert record.surface_id == "test_surface"
    assert record.tier == StabilizationTier.CANONICAL_STABLE
    assert record.is_extension_ready is True
    assert record.canonical_replacement is None


def test_e02_surface_record_to_dict_shape() -> None:
    record = StabilizationSurfaceRecord(
        surface_id="test_surface",
        surface_name="Test Surface",
        module_path="core.test_module",
        tier=StabilizationTier.TRANSITIONAL_CONVERGING,
        category=SurfaceCategory.COMPATIBILITY_LAYER,
        is_extension_ready=False,
        pr_introduced="PR-10",
        rationale="Test rationale.",
        canonical_replacement="core.canonical_module",
    )
    d = record.to_dict()
    expected_keys = {
        "surface_id", "surface_name", "module_path", "tier", "category",
        "is_extension_ready", "pr_introduced", "rationale", "canonical_replacement",
    }
    assert expected_keys.issubset(d.keys())


def test_e03_surface_record_to_dict_tier_is_string() -> None:
    record = StabilizationSurfaceRecord(
        surface_id="ts",
        surface_name="T",
        module_path="core.t",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.TRUTH_COMPILATION,
        is_extension_ready=True,
        pr_introduced="PR-10",
        rationale="R",
    )
    d = record.to_dict()
    assert isinstance(d["tier"], str)
    assert d["tier"] == "canonical_stable"


def test_e04_surface_record_to_dict_category_is_string() -> None:
    record = StabilizationSurfaceRecord(
        surface_id="ts",
        surface_name="T",
        module_path="core.t",
        tier=StabilizationTier.CANONICAL_STABLE,
        category=SurfaceCategory.DISPATCH_ORCHESTRATION,
        is_extension_ready=True,
        pr_introduced="PR-10",
        rationale="R",
    )
    d = record.to_dict()
    assert isinstance(d["category"], str)
    assert d["category"] == "dispatch_orchestration"


# ---------------------------------------------------------------------------
# F. StabilizationBaselineSnapshot dataclass
# ---------------------------------------------------------------------------


def test_f01_snapshot_default_construction() -> None:
    snap = StabilizationBaselineSnapshot()
    assert snap.total_surface_count == 0
    assert snap.canonical_stable_count == 0
    assert snap.transitional_converging_count == 0
    assert snap.extension_surface_count == 0
    assert snap.compat_bridge_count == 0
    assert snap.extension_ready_count == 0
    assert snap.policy_sentinels == []
    assert snap.surfaces == []


def test_f02_snapshot_to_dict_shape() -> None:
    snap = StabilizationBaselineSnapshot(
        total_surface_count=5,
        canonical_stable_count=3,
        policy_sentinels=["POLICY_A"],
    )
    d = snap.to_dict()
    expected_keys = {
        "snapshotted_at", "total_surface_count", "canonical_stable_count",
        "transitional_converging_count", "extension_surface_count",
        "compat_bridge_count", "extension_ready_count",
        "policy_sentinels", "surfaces",
    }
    assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# G. get_baseline_catalog()
# ---------------------------------------------------------------------------


def test_g01_catalog_is_non_empty() -> None:
    catalog = get_baseline_catalog()
    assert len(catalog) >= 1


def test_g02_catalog_contains_surface_record_instances() -> None:
    catalog = get_baseline_catalog()
    for record in catalog:
        assert isinstance(record, StabilizationSurfaceRecord)


def test_g03_catalog_surface_ids_are_unique() -> None:
    catalog = get_baseline_catalog()
    ids = [r.surface_id for r in catalog]
    assert len(ids) == len(set(ids)), "Duplicate surface_id found in catalog"


def test_g04_catalog_all_surface_ids_non_empty() -> None:
    catalog = get_baseline_catalog()
    for record in catalog:
        assert record.surface_id, f"Empty surface_id for record: {record}"


def test_g05_catalog_all_rationales_non_empty() -> None:
    catalog = get_baseline_catalog()
    for record in catalog:
        assert record.rationale, f"Empty rationale for surface_id={record.surface_id}"


# ---------------------------------------------------------------------------
# H. get_canonical_stable_surfaces()
# ---------------------------------------------------------------------------


def test_h01_canonical_stable_returns_only_canonical_stable() -> None:
    surfaces = get_canonical_stable_surfaces()
    for s in surfaces:
        assert s.tier == StabilizationTier.CANONICAL_STABLE


def test_h02_canonical_stable_is_non_empty() -> None:
    surfaces = get_canonical_stable_surfaces()
    assert len(surfaces) >= 1


def test_h03_canonical_stable_all_are_extension_ready() -> None:
    surfaces = get_canonical_stable_surfaces()
    for s in surfaces:
        assert s.is_extension_ready is True, (
            f"CANONICAL_STABLE surface {s.surface_id!r} has is_extension_ready=False"
        )


# ---------------------------------------------------------------------------
# I. get_transitional_surfaces()
# ---------------------------------------------------------------------------


def test_i01_transitional_returns_only_transitional_converging() -> None:
    surfaces = get_transitional_surfaces()
    for s in surfaces:
        assert s.tier == StabilizationTier.TRANSITIONAL_CONVERGING


def test_i02_transitional_all_not_extension_ready() -> None:
    surfaces = get_transitional_surfaces()
    for s in surfaces:
        assert s.is_extension_ready is False, (
            f"TRANSITIONAL_CONVERGING surface {s.surface_id!r} has is_extension_ready=True"
        )


def test_i03_transitional_all_have_canonical_replacement() -> None:
    surfaces = get_transitional_surfaces()
    for s in surfaces:
        assert s.canonical_replacement, (
            f"TRANSITIONAL_CONVERGING surface {s.surface_id!r} has no canonical_replacement"
        )


# ---------------------------------------------------------------------------
# J. get_extension_surfaces()
# ---------------------------------------------------------------------------


def test_j01_extension_surfaces_returns_only_extension_surface_tier() -> None:
    surfaces = get_extension_surfaces()
    for s in surfaces:
        assert s.tier == StabilizationTier.EXTENSION_SURFACE


def test_j02_extension_surfaces_all_extension_ready() -> None:
    surfaces = get_extension_surfaces()
    for s in surfaces:
        assert s.is_extension_ready is True, (
            f"EXTENSION_SURFACE {s.surface_id!r} has is_extension_ready=False"
        )


# ---------------------------------------------------------------------------
# K. get_compat_bridge_surfaces()
# ---------------------------------------------------------------------------


def test_k01_compat_bridge_returns_only_compat_bridge_tier() -> None:
    surfaces = get_compat_bridge_surfaces()
    for s in surfaces:
        assert s.tier == StabilizationTier.COMPATIBILITY_BRIDGE


def test_k02_compat_bridge_all_not_extension_ready() -> None:
    surfaces = get_compat_bridge_surfaces()
    for s in surfaces:
        assert s.is_extension_ready is False, (
            f"COMPATIBILITY_BRIDGE surface {s.surface_id!r} has is_extension_ready=True"
        )


def test_k03_compat_bridge_all_have_canonical_replacement() -> None:
    surfaces = get_compat_bridge_surfaces()
    for s in surfaces:
        assert s.canonical_replacement, (
            f"COMPATIBILITY_BRIDGE surface {s.surface_id!r} has no canonical_replacement"
        )


# ---------------------------------------------------------------------------
# L. classify_surface_tier() — known surface_ids
# ---------------------------------------------------------------------------


def test_l01_classify_authority_boundary_classification() -> None:
    tier = classify_surface_tier("authority_boundary_classification")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_l02_classify_truth_projection_boundary() -> None:
    tier = classify_surface_tier("truth_projection_boundary")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_l03_classify_runtime_truth_output_chain() -> None:
    tier = classify_surface_tier("runtime_truth_output_chain")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_l04_classify_node_fabric_registry() -> None:
    tier = classify_surface_tier("node_fabric_registry")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_l05_classify_source_dispatch_orchestrator() -> None:
    tier = classify_surface_tier("source_dispatch_orchestrator")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_l06_classify_projection_routes_extension_surface() -> None:
    tier = classify_surface_tier("projection_routes")
    assert tier == StabilizationTier.EXTENSION_SURFACE


def test_l07_classify_node_registry_compat_facade_transitional() -> None:
    tier = classify_surface_tier("node_registry_compat_facade")
    assert tier == StabilizationTier.TRANSITIONAL_CONVERGING


def test_l08_classify_node_status_cache_compat_bridge() -> None:
    tier = classify_surface_tier("node_status_cache")
    assert tier == StabilizationTier.COMPATIBILITY_BRIDGE


# ---------------------------------------------------------------------------
# M. classify_surface_tier() — unknown surface_id
# ---------------------------------------------------------------------------


def test_m01_classify_unknown_surface_returns_none() -> None:
    result = classify_surface_tier("this_surface_does_not_exist_xyz")
    assert result is None


def test_m02_classify_empty_string_returns_none() -> None:
    result = classify_surface_tier("")
    assert result is None


# ---------------------------------------------------------------------------
# N. build_stabilization_baseline_snapshot()
# ---------------------------------------------------------------------------


def test_n01_snapshot_returns_stabilization_baseline_snapshot() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert isinstance(snap, StabilizationBaselineSnapshot)


def test_n02_snapshot_total_count_positive() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert snap.total_surface_count >= 1


def test_n03_snapshot_canonical_stable_count_positive() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert snap.canonical_stable_count >= 1


def test_n04_snapshot_policy_sentinels_has_four_entries() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert len(snap.policy_sentinels) == 4


def test_n05_snapshot_surfaces_length_matches_total_count() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert len(snap.surfaces) == snap.total_surface_count


# ---------------------------------------------------------------------------
# O. Total count equals sum of all tier counts
# ---------------------------------------------------------------------------


def test_o01_total_count_equals_tier_count_sum() -> None:
    snap = build_stabilization_baseline_snapshot()
    tier_sum = (
        snap.canonical_stable_count
        + snap.transitional_converging_count
        + snap.extension_surface_count
        + snap.compat_bridge_count
    )
    assert snap.total_surface_count == tier_sum, (
        f"total_surface_count={snap.total_surface_count} != "
        f"sum of tier counts={tier_sum}"
    )


# ---------------------------------------------------------------------------
# P. Extension-ready count
# ---------------------------------------------------------------------------


def test_p01_extension_ready_count_consistent_with_catalog() -> None:
    snap = build_stabilization_baseline_snapshot()
    actual_ready = sum(1 for s in snap.surfaces if s.is_extension_ready)
    assert snap.extension_ready_count == actual_ready


# ---------------------------------------------------------------------------
# Q. Snapshot policy_sentinels list
# ---------------------------------------------------------------------------


def test_q01_policy_sentinels_contains_canonical_stable_policy() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert any(
        "CANONICAL_SURFACES_ARE_STABLE_EXTENSION_POINTS" in p
        for p in snap.policy_sentinels
    )


def test_q02_policy_sentinels_contains_transitional_policy() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert any(
        "TRANSITIONAL_SURFACES_MUST_CONVERGE_NOT_EXTEND" in p
        for p in snap.policy_sentinels
    )


def test_q03_policy_sentinels_contains_extension_path_policy() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert any(
        "EXTENSION_MUST_USE_CANONICAL_PATHS_ONLY" in p
        for p in snap.policy_sentinels
    )


def test_q04_policy_sentinels_contains_compat_bridge_policy() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert any(
        "COMPAT_BRIDGES_MUST_NOT_GROW" in p
        for p in snap.policy_sentinels
    )


# ---------------------------------------------------------------------------
# R. Snapshot timestamp
# ---------------------------------------------------------------------------


def test_r01_snapshotted_at_is_recent() -> None:
    before = time.time()
    snap = build_stabilization_baseline_snapshot()
    after = time.time()
    assert before <= snap.snapshotted_at <= after


# ---------------------------------------------------------------------------
# S. Snapshot to_dict() keys
# ---------------------------------------------------------------------------


def test_s01_snapshot_to_dict_has_expected_top_level_keys() -> None:
    snap = build_stabilization_baseline_snapshot()
    d = snap.to_dict()
    expected_keys = {
        "snapshotted_at",
        "total_surface_count",
        "canonical_stable_count",
        "transitional_converging_count",
        "extension_surface_count",
        "compat_bridge_count",
        "extension_ready_count",
        "policy_sentinels",
        "surfaces",
    }
    for key in expected_keys:
        assert key in d, f"Missing key {key!r} in snapshot.to_dict()"


# ---------------------------------------------------------------------------
# T. Snapshot to_dict() surfaces length
# ---------------------------------------------------------------------------


def test_t01_snapshot_to_dict_surfaces_length_matches() -> None:
    snap = build_stabilization_baseline_snapshot()
    d = snap.to_dict()
    assert len(d["surfaces"]) == d["total_surface_count"]


# ---------------------------------------------------------------------------
# U. Surface record to_dict() keys
# ---------------------------------------------------------------------------


def test_u01_each_surface_to_dict_has_required_keys() -> None:
    snap = build_stabilization_baseline_snapshot()
    required_keys = {
        "surface_id", "surface_name", "module_path", "tier",
        "category", "is_extension_ready", "pr_introduced", "rationale",
        "canonical_replacement",
    }
    for surface_dict in snap.to_dict()["surfaces"]:
        for key in required_keys:
            assert key in surface_dict, (
                f"Key {key!r} missing from surface record: "
                f"{surface_dict.get('surface_id', '<unknown>')}"
            )


# ---------------------------------------------------------------------------
# V. Projection alignment sentinel (fastapi guard)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_v01_projection_alignment_sentinel_present() -> None:
    import core.routes.projection as proj_mod
    assert hasattr(proj_mod, "ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10")
    val = proj_mod.ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10
    assert isinstance(val, str)
    assert val


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_v02_projection_alignment_sentinel_not_unavailable() -> None:
    import core.routes.projection as proj_mod
    val = proj_mod.ARCHITECTURE_STABILIZATION_BASELINE_ALIGNED_PR10
    assert "UNAVAILABLE" not in val, (
        f"Projection alignment sentinel is UNAVAILABLE: {val!r}"
    )


# ---------------------------------------------------------------------------
# W. Sentinel strings contain expected keywords
# ---------------------------------------------------------------------------


def test_w01_authority_sentinel_contains_stabilization_keyword() -> None:
    assert "stabilization" in ARCHITECTURE_STABILIZATION_BASELINE_IS_AUTHORITY.lower()


def test_w02_pr10_sentinel_contains_convergence_plan_keyword() -> None:
    assert "convergence" in ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL.lower()


def test_w03_pr10_sentinel_contains_canonical_keyword() -> None:
    assert "canonical" in ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL.lower()


def test_w04_pr10_sentinel_contains_transitional_keyword() -> None:
    assert "transitional" in ARCHITECTURE_STABILIZATION_BASELINE_PR10_SENTINEL.lower()


# ---------------------------------------------------------------------------
# X. Key canonical-stable surfaces present in catalog
# ---------------------------------------------------------------------------


def test_x01_authority_boundary_classification_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "authority_boundary_classification" in ids


def test_x02_truth_projection_boundary_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "truth_projection_boundary" in ids


def test_x03_runtime_truth_output_chain_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "runtime_truth_output_chain" in ids


def test_x04_node_fabric_registry_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "node_fabric_registry" in ids


def test_x05_source_dispatch_orchestrator_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "source_dispatch_orchestrator" in ids


def test_x06_attached_runtime_session_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "attached_runtime_session" in ids


def test_x07_long_tail_compat_surface_in_catalog() -> None:
    catalog = get_baseline_catalog()
    ids = {r.surface_id for r in catalog}
    assert "long_tail_compat_surface" in ids


# ---------------------------------------------------------------------------
# Y. Key transitional surfaces present with correct fields
# ---------------------------------------------------------------------------


def test_y01_node_registry_compat_facade_is_transitional() -> None:
    catalog = get_baseline_catalog()
    entry = next((r for r in catalog if r.surface_id == "node_registry_compat_facade"), None)
    assert entry is not None, "node_registry_compat_facade not found in catalog"
    assert entry.tier == StabilizationTier.TRANSITIONAL_CONVERGING
    assert entry.is_extension_ready is False
    assert entry.canonical_replacement


def test_y02_generic_forward_handlers_is_transitional() -> None:
    catalog = get_baseline_catalog()
    entry = next((r for r in catalog if r.surface_id == "generic_forward_handlers"), None)
    assert entry is not None, "generic_forward_handlers not found in catalog"
    assert entry.tier == StabilizationTier.TRANSITIONAL_CONVERGING
    assert entry.is_extension_ready is False


# ---------------------------------------------------------------------------
# Z. Key compat-bridge surfaces present
# ---------------------------------------------------------------------------


def test_z01_node_status_cache_is_compat_bridge() -> None:
    catalog = get_baseline_catalog()
    entry = next((r for r in catalog if r.surface_id == "node_status_cache"), None)
    assert entry is not None, "node_status_cache not found in catalog"
    assert entry.tier == StabilizationTier.COMPATIBILITY_BRIDGE
    assert entry.is_extension_ready is False
    assert entry.canonical_replacement


def test_z02_node_registry_json_scan_is_compat_bridge() -> None:
    catalog = get_baseline_catalog()
    entry = next((r for r in catalog if r.surface_id == "node_registry_json_scan"), None)
    assert entry is not None, "node_registry_json_scan not found in catalog"
    assert entry.tier == StabilizationTier.COMPATIBILITY_BRIDGE
    assert entry.is_extension_ready is False


# ---------------------------------------------------------------------------
# AA. Catalog: no transitional/compat surface has is_extension_ready=True
# ---------------------------------------------------------------------------


def test_aa01_no_transitional_surface_is_extension_ready() -> None:
    for record in get_baseline_catalog():
        if record.tier in (
            StabilizationTier.TRANSITIONAL_CONVERGING,
            StabilizationTier.COMPATIBILITY_BRIDGE,
        ):
            assert record.is_extension_ready is False, (
                f"Surface {record.surface_id!r} has tier={record.tier.value} "
                f"but is_extension_ready=True"
            )


# ---------------------------------------------------------------------------
# AB. Catalog: canonical/extension surfaces have canonical_replacement=None
# ---------------------------------------------------------------------------


def test_ab01_canonical_stable_no_canonical_replacement() -> None:
    for record in get_canonical_stable_surfaces():
        assert record.canonical_replacement is None, (
            f"CANONICAL_STABLE surface {record.surface_id!r} has a "
            f"canonical_replacement set: {record.canonical_replacement!r}"
        )


def test_ab02_extension_surfaces_no_canonical_replacement() -> None:
    for record in get_extension_surfaces():
        assert record.canonical_replacement is None, (
            f"EXTENSION_SURFACE {record.surface_id!r} has a "
            f"canonical_replacement set: {record.canonical_replacement!r}"
        )


# ---------------------------------------------------------------------------
# AC. StabilizationTier.from_string() raises ValueError for unknown value
# ---------------------------------------------------------------------------


def test_ac01_from_string_unknown_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown StabilizationTier"):
        StabilizationTier.from_string("not_a_valid_tier")


# ---------------------------------------------------------------------------
# AD. StabilizationBaselineSnapshot defaults
# ---------------------------------------------------------------------------


def test_ad01_snapshot_default_has_empty_surfaces_list() -> None:
    snap = StabilizationBaselineSnapshot()
    assert snap.surfaces == []


def test_ad02_snapshot_default_has_empty_policy_sentinels() -> None:
    snap = StabilizationBaselineSnapshot()
    assert snap.policy_sentinels == []


def test_ad03_snapshot_default_to_dict_has_surfaces_key() -> None:
    snap = StabilizationBaselineSnapshot()
    d = snap.to_dict()
    assert "surfaces" in d
    assert d["surfaces"] == []


# ---------------------------------------------------------------------------
# AE. Two snapshot builds produce independent objects
# ---------------------------------------------------------------------------


def test_ae01_two_snapshot_builds_are_independent_objects() -> None:
    snap1 = build_stabilization_baseline_snapshot()
    snap2 = build_stabilization_baseline_snapshot()
    assert snap1 is not snap2


def test_ae02_two_snapshot_builds_have_same_total_count() -> None:
    snap1 = build_stabilization_baseline_snapshot()
    snap2 = build_stabilization_baseline_snapshot()
    assert snap1.total_surface_count == snap2.total_surface_count


def test_ae03_two_snapshot_builds_have_same_canonical_stable_count() -> None:
    snap1 = build_stabilization_baseline_snapshot()
    snap2 = build_stabilization_baseline_snapshot()
    assert snap1.canonical_stable_count == snap2.canonical_stable_count
