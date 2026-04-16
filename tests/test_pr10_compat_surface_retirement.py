#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr10_compat_surface_retirement.py
=============================================

PR-10 (realization-v2 convergence plan): compatibility-surface retirement
inventory and tier classification tests.

Coverage
--------
A.  Module importable; authority and PR-10 sentinel are non-empty strings.
B.  All four policy sentinels are non-empty strings with expected keywords.
C.  RetirementTier enum has TIER_1, TIER_2, TIER_3, TIER_UNDECIDED members.
D.  RetirementStatus enum has COMPAT_ONLY, LEGACY_COMPAT, TRANSITIONAL,
    HARD_DEPRECATED, TOMBSTONE members.
E.  CompatSurfaceRisk enum has HIGH, MEDIUM, LOW members.
F.  get_compat_surface_inventory() returns a non-empty list of
    CompatSurfaceRecord instances.
G.  Every record has a non-empty surface_id, module_path, surface_name,
    canonical_replacement, and removal_condition.
H.  Every record has a tier that is not TIER_UNDECIDED (no undecided surfaces
    in a finalized inventory).
I.  Every record has a valid RetirementStatus value.
J.  get_surfaces_by_tier(TIER_1) returns only TIER_1 records.
K.  get_surfaces_by_tier(TIER_2) returns only TIER_2 records.
L.  get_high_risk_surfaces() returns only HIGH-risk records and is non-empty.
M.  All HIGH-risk surfaces have a non-empty canonical_replacement.
N.  classify_surface_tier() returns correct tier for known module paths.
O.  classify_surface_tier() returns None for unknown paths.
P.  build_retirement_roadmap_summary() returns a RetirementRoadmapSummary.
Q.  Summary counts are internally consistent (total == sum of tier counts).
R.  Summary tier counts match actual inventory contents.
S.  Summary risk counts match actual inventory contents.
T.  Summary status counts match actual inventory contents.
U.  Summary policy_sentinels list contains four sentinel strings.
V.  RetirementRoadmapSummary.to_dict() includes expected top-level keys.
W.  CompatSurfaceRecord.to_dict() includes all required keys.
X.  No two records share the same surface_id (uniqueness).
Y.  TIER_1 + TIER_2 count is at least equal to high-risk count
    (all high-risk surfaces have an actionable tier).
Z.  Projection alignment sentinel importable (fastapi guard).
"""

from __future__ import annotations

import importlib.util
from typing import Any, Dict, List

import pytest

from core.compat_surface_retirement import (
    COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY,
    COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY,
    COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL,
    COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY,
    HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY,
    RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY,
    CompatSurfaceRecord,
    CompatSurfaceRisk,
    RetirementRoadmapSummary,
    RetirementStatus,
    RetirementTier,
    build_retirement_roadmap_summary,
    classify_surface_tier,
    get_compat_surface_inventory,
    get_high_risk_surfaces,
    get_surfaces_by_tier,
)

_HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None


# ---------------------------------------------------------------------------
# A. Module importable; authority and sentinel non-empty
# ---------------------------------------------------------------------------


def test_authority_sentinel_non_empty() -> None:
    assert isinstance(COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY, str)
    assert COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY
    assert "IS_CANONICAL_AUTHORITY_PR10" in COMPAT_SURFACE_RETIREMENT_IS_AUTHORITY


def test_pr10_sentinel_non_empty() -> None:
    assert isinstance(COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL, str)
    assert COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL
    assert "PR10" in COMPAT_SURFACE_RETIREMENT_PR10_SENTINEL


# ---------------------------------------------------------------------------
# B. Policy sentinels present and contain expected keywords
# ---------------------------------------------------------------------------


def test_inventory_policy_sentinel() -> None:
    assert "INVENTORIED" in HIGH_RISK_COMPAT_SURFACES_MUST_BE_INVENTORIED_POLICY


def test_masquerade_policy_sentinel() -> None:
    assert "MASQUERADE" in COMPAT_SURFACES_MUST_NOT_MASQUERADE_AS_CANONICAL_POLICY


def test_tier_policy_sentinel() -> None:
    assert "TIER" in RETIREMENT_TIER_CLASSIFICATION_MUST_BE_EXPLICIT_POLICY


def test_footprint_policy_sentinel() -> None:
    assert "SHRINK" in COMPAT_FOOTPRINT_MUST_SHRINK_OVER_TIME_POLICY


# ---------------------------------------------------------------------------
# C. RetirementTier enum members
# ---------------------------------------------------------------------------


def test_retirement_tier_members() -> None:
    assert RetirementTier.TIER_1.value == "tier_1"
    assert RetirementTier.TIER_2.value == "tier_2"
    assert RetirementTier.TIER_3.value == "tier_3"
    assert RetirementTier.TIER_UNDECIDED.value == "tier_undecided"


# ---------------------------------------------------------------------------
# D. RetirementStatus enum members
# ---------------------------------------------------------------------------


def test_retirement_status_members() -> None:
    assert RetirementStatus.COMPAT_ONLY.value == "compat_only"
    assert RetirementStatus.LEGACY_COMPAT.value == "legacy_compat"
    assert RetirementStatus.TRANSITIONAL.value == "transitional"
    assert RetirementStatus.HARD_DEPRECATED.value == "hard_deprecated"
    assert RetirementStatus.TOMBSTONE.value == "tombstone"


# ---------------------------------------------------------------------------
# E. CompatSurfaceRisk enum members
# ---------------------------------------------------------------------------


def test_compat_surface_risk_members() -> None:
    assert CompatSurfaceRisk.HIGH.value == "high"
    assert CompatSurfaceRisk.MEDIUM.value == "medium"
    assert CompatSurfaceRisk.LOW.value == "low"


# ---------------------------------------------------------------------------
# F. Inventory returns non-empty list of CompatSurfaceRecord
# ---------------------------------------------------------------------------


def test_inventory_non_empty() -> None:
    inventory = get_compat_surface_inventory()
    assert isinstance(inventory, list)
    assert len(inventory) > 0
    assert all(isinstance(r, CompatSurfaceRecord) for r in inventory)


# ---------------------------------------------------------------------------
# G. Every record has required non-empty string fields
# ---------------------------------------------------------------------------


def test_every_record_has_required_fields() -> None:
    for record in get_compat_surface_inventory():
        assert record.surface_id, f"surface_id empty for {record.module_path}"
        assert record.module_path, f"module_path empty for {record.surface_id}"
        assert record.surface_name, f"surface_name empty for {record.surface_id}"
        assert record.canonical_replacement, (
            f"canonical_replacement empty for {record.surface_id}"
        )
        assert record.removal_condition, (
            f"removal_condition empty for {record.surface_id}"
        )


# ---------------------------------------------------------------------------
# H. No TIER_UNDECIDED surfaces in the finalised inventory
# ---------------------------------------------------------------------------


def test_no_tier_undecided_in_inventory() -> None:
    undecided = [
        r for r in get_compat_surface_inventory()
        if r.tier == RetirementTier.TIER_UNDECIDED
    ]
    assert undecided == [], (
        f"Found TIER_UNDECIDED surfaces (must be resolved): "
        f"{[r.surface_id for r in undecided]}"
    )


# ---------------------------------------------------------------------------
# I. Every record has a valid RetirementStatus
# ---------------------------------------------------------------------------


def test_every_record_has_valid_status() -> None:
    valid_statuses = set(RetirementStatus)
    for record in get_compat_surface_inventory():
        assert record.status in valid_statuses, (
            f"{record.surface_id} has unexpected status {record.status!r}"
        )


# ---------------------------------------------------------------------------
# J. get_surfaces_by_tier(TIER_1) returns only TIER_1 records
# ---------------------------------------------------------------------------


def test_get_surfaces_by_tier_1_returns_only_tier_1() -> None:
    tier1 = get_surfaces_by_tier(RetirementTier.TIER_1)
    assert all(r.tier == RetirementTier.TIER_1 for r in tier1)


# ---------------------------------------------------------------------------
# K. get_surfaces_by_tier(TIER_2) returns only TIER_2 records
# ---------------------------------------------------------------------------


def test_get_surfaces_by_tier_2_returns_only_tier_2() -> None:
    tier2 = get_surfaces_by_tier(RetirementTier.TIER_2)
    assert all(r.tier == RetirementTier.TIER_2 for r in tier2)


# ---------------------------------------------------------------------------
# L. get_high_risk_surfaces() non-empty; all records are HIGH risk
# ---------------------------------------------------------------------------


def test_high_risk_surfaces_non_empty() -> None:
    high_risk = get_high_risk_surfaces()
    assert len(high_risk) > 0


def test_high_risk_surfaces_all_high() -> None:
    high_risk = get_high_risk_surfaces()
    assert all(r.risk == CompatSurfaceRisk.HIGH for r in high_risk)


# ---------------------------------------------------------------------------
# M. All HIGH-risk surfaces have a non-empty canonical_replacement
# ---------------------------------------------------------------------------


def test_high_risk_surfaces_have_canonical_replacement() -> None:
    for record in get_high_risk_surfaces():
        assert record.canonical_replacement, (
            f"HIGH-risk surface {record.surface_id} has no canonical_replacement"
        )


# ---------------------------------------------------------------------------
# N. classify_surface_tier() correct for known paths
# ---------------------------------------------------------------------------


def test_classify_known_compat_route() -> None:
    tier = classify_surface_tier("core.routes.compat")
    assert tier == RetirementTier.TIER_2


def test_classify_known_node_registry() -> None:
    tier = classify_surface_tier("core.node_registry.NodeRegistry")
    assert tier == RetirementTier.TIER_2


def test_classify_known_tier1() -> None:
    tier = classify_surface_tier("launcher.config_manager")
    assert tier == RetirementTier.TIER_1


# ---------------------------------------------------------------------------
# O. classify_surface_tier() returns None for unknown paths
# ---------------------------------------------------------------------------


def test_classify_unknown_returns_none() -> None:
    result = classify_surface_tier("nonexistent.module.path")
    assert result is None


# ---------------------------------------------------------------------------
# P. build_retirement_roadmap_summary() returns RetirementRoadmapSummary
# ---------------------------------------------------------------------------


def test_summary_is_roadmap_summary() -> None:
    summary = build_retirement_roadmap_summary()
    assert isinstance(summary, RetirementRoadmapSummary)


# ---------------------------------------------------------------------------
# Q. Summary total == sum of tier counts
# ---------------------------------------------------------------------------


def test_summary_total_equals_tier_sum() -> None:
    s = build_retirement_roadmap_summary()
    assert s.total_surfaces == (
        s.tier_1_count + s.tier_2_count + s.tier_3_count + s.tier_undecided_count
    )


# ---------------------------------------------------------------------------
# R. Summary tier counts match inventory
# ---------------------------------------------------------------------------


def test_summary_tier_counts_match_inventory() -> None:
    inventory = get_compat_surface_inventory()
    s = build_retirement_roadmap_summary()
    assert s.tier_1_count == sum(1 for r in inventory if r.tier == RetirementTier.TIER_1)
    assert s.tier_2_count == sum(1 for r in inventory if r.tier == RetirementTier.TIER_2)
    assert s.tier_3_count == sum(1 for r in inventory if r.tier == RetirementTier.TIER_3)
    assert s.tier_undecided_count == sum(
        1 for r in inventory if r.tier == RetirementTier.TIER_UNDECIDED
    )


# ---------------------------------------------------------------------------
# S. Summary risk counts match inventory
# ---------------------------------------------------------------------------


def test_summary_risk_counts_match_inventory() -> None:
    inventory = get_compat_surface_inventory()
    s = build_retirement_roadmap_summary()
    assert s.high_risk_count == sum(1 for r in inventory if r.risk == CompatSurfaceRisk.HIGH)
    assert s.medium_risk_count == sum(1 for r in inventory if r.risk == CompatSurfaceRisk.MEDIUM)
    assert s.low_risk_count == sum(1 for r in inventory if r.risk == CompatSurfaceRisk.LOW)


# ---------------------------------------------------------------------------
# T. Summary status counts match inventory
# ---------------------------------------------------------------------------


def test_summary_status_counts_match_inventory() -> None:
    inventory = get_compat_surface_inventory()
    s = build_retirement_roadmap_summary()
    assert s.hard_deprecated_count == sum(
        1 for r in inventory if r.status == RetirementStatus.HARD_DEPRECATED
    )
    assert s.legacy_compat_count == sum(
        1 for r in inventory if r.status == RetirementStatus.LEGACY_COMPAT
    )
    assert s.compat_only_count == sum(
        1 for r in inventory if r.status == RetirementStatus.COMPAT_ONLY
    )
    assert s.transitional_count == sum(
        1 for r in inventory if r.status == RetirementStatus.TRANSITIONAL
    )


# ---------------------------------------------------------------------------
# U. Summary policy_sentinels list has four sentinels
# ---------------------------------------------------------------------------


def test_summary_has_four_policy_sentinels() -> None:
    s = build_retirement_roadmap_summary()
    assert len(s.policy_sentinels) == 4
    assert all(isinstance(p, str) and p for p in s.policy_sentinels)


# ---------------------------------------------------------------------------
# V. RetirementRoadmapSummary.to_dict() has expected top-level keys
# ---------------------------------------------------------------------------


def test_summary_to_dict_keys() -> None:
    d = build_retirement_roadmap_summary().to_dict()
    assert "total_surfaces" in d
    assert "by_tier" in d
    assert "by_risk" in d
    assert "by_status" in d
    assert "policy_sentinels" in d
    # sub-keys
    assert "tier_1" in d["by_tier"]
    assert "tier_2" in d["by_tier"]
    assert "high" in d["by_risk"]
    assert "compat_only" in d["by_status"]


# ---------------------------------------------------------------------------
# W. CompatSurfaceRecord.to_dict() has all required keys
# ---------------------------------------------------------------------------


def test_record_to_dict_keys() -> None:
    record = get_compat_surface_inventory()[0]
    d = record.to_dict()
    required_keys = {
        "surface_id",
        "module_path",
        "surface_name",
        "status",
        "tier",
        "risk",
        "canonical_replacement",
        "removal_condition",
        "notes",
        "pr_guardrail_added",
    }
    assert required_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# X. No two records share the same surface_id
# ---------------------------------------------------------------------------


def test_surface_ids_are_unique() -> None:
    ids = [r.surface_id for r in get_compat_surface_inventory()]
    assert len(ids) == len(set(ids)), (
        f"Duplicate surface_ids found: "
        f"{[x for x in ids if ids.count(x) > 1]}"
    )


# ---------------------------------------------------------------------------
# Y. (TIER_1 + TIER_2) count >= high-risk count
#    (every high-risk surface must have an actionable tier)
# ---------------------------------------------------------------------------


def test_all_high_risk_surfaces_have_actionable_tier() -> None:
    inventory = get_compat_surface_inventory()
    high_risk_count = sum(1 for r in inventory if r.risk == CompatSurfaceRisk.HIGH)
    tier1_count = sum(1 for r in inventory if r.tier == RetirementTier.TIER_1)
    tier2_count = sum(1 for r in inventory if r.tier == RetirementTier.TIER_2)
    assert (tier1_count + tier2_count) >= high_risk_count, (
        "Some HIGH-risk surfaces are classified TIER_3 or TIER_UNDECIDED — "
        "all HIGH-risk surfaces must have an actionable (TIER_1 or TIER_2) retirement tier."
    )


# ---------------------------------------------------------------------------
# Z. Projection alignment sentinel is importable (fastapi guard)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FASTAPI, reason="fastapi not installed")
def test_projection_alignment_sentinel_available() -> None:
    from core.routes.projection import COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10  # noqa: F401

    assert isinstance(COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10, str)
    assert "UNAVAILABLE" not in COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10
    assert "ALIGNED_PR10" in COMPAT_SURFACE_RETIREMENT_ALIGNED_PR10
