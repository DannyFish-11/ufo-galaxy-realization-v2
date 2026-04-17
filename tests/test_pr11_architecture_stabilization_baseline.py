#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_pr11_architecture_stabilization_baseline.py
===========================================================
PR-11 (realization-v2 convergence plan): Architecture Stabilization Baseline
extension tests.

Coverage groups
---------------
A  — PR-11 sentinel: present, non-empty, contains expected keywords.
B  — New CANONICAL_STABLE surfaces added by PR-11 are present in catalog.
C  — New session-axis surface has correct tier and fields.
D  — New session-truth surface has correct tier and fields.
E  — New session-registry surface has correct tier and fields.
F  — All three new PR-11 surfaces are CANONICAL_STABLE and extension-ready.
G  — No new PR-11 surface has canonical_replacement set.
H  — Catalog uniqueness still holds after PR-11 additions.
I  — get_canonical_stable_surfaces() includes all three new PR-11 surfaces.
J  — Snapshot total_surface_count increased by at least 3 vs. pre-PR-11 floor.
K  — Snapshot canonical_stable_count includes all new PR-11 surfaces.
L  — PR-11 sentinel importable from __all__.
M  — PR-11 sentinel contains "session" keyword.
N  — PR-11 sentinel contains "canonical" keyword.
O  — PR-11 sentinel contains "PR-11" keyword.
"""

from __future__ import annotations

import pytest

from core.architecture_stabilization_baseline import (
    ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL,
    StabilizationTier,
    SurfaceCategory,
    build_stabilization_baseline_snapshot,
    classify_surface_tier,
    get_baseline_catalog,
    get_canonical_stable_surfaces,
)

# ---------------------------------------------------------------------------
# A. PR-11 sentinel
# ---------------------------------------------------------------------------


def test_a01_pr11_sentinel_is_non_empty_string() -> None:
    assert isinstance(ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL, str)
    assert ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL


def test_a02_pr11_sentinel_contains_pr11_keyword() -> None:
    assert "PR-11" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL


def test_a03_pr11_sentinel_contains_stabilization_keyword() -> None:
    assert "stabilization" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL.lower()


def test_a04_pr11_sentinel_contains_canonical_keyword() -> None:
    assert "canonical" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL.lower()


def test_a05_pr11_sentinel_contains_session_keyword() -> None:
    assert "session" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL.lower()


# ---------------------------------------------------------------------------
# B. New surfaces present in catalog
# ---------------------------------------------------------------------------

_PR11_NEW_SURFACE_IDS = {
    "canonical_session_axis",
    "canonical_session_truth",
    "attached_runtime_session_registry",
}


def test_b01_canonical_session_axis_in_catalog() -> None:
    ids = {r.surface_id for r in get_baseline_catalog()}
    assert "canonical_session_axis" in ids


def test_b02_canonical_session_truth_in_catalog() -> None:
    ids = {r.surface_id for r in get_baseline_catalog()}
    assert "canonical_session_truth" in ids


def test_b03_attached_runtime_session_registry_in_catalog() -> None:
    ids = {r.surface_id for r in get_baseline_catalog()}
    assert "attached_runtime_session_registry" in ids


def test_b04_all_three_pr11_surfaces_in_catalog() -> None:
    ids = {r.surface_id for r in get_baseline_catalog()}
    for sid in _PR11_NEW_SURFACE_IDS:
        assert sid in ids, f"PR-11 surface {sid!r} not found in catalog"


# ---------------------------------------------------------------------------
# C. canonical_session_axis surface fields
# ---------------------------------------------------------------------------


def _get_surface(surface_id: str):
    catalog = get_baseline_catalog()
    return next((r for r in catalog if r.surface_id == surface_id), None)


def test_c01_canonical_session_axis_is_canonical_stable() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.tier == StabilizationTier.CANONICAL_STABLE


def test_c02_canonical_session_axis_is_extension_ready() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.is_extension_ready is True


def test_c03_canonical_session_axis_has_no_canonical_replacement() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.canonical_replacement is None


def test_c04_canonical_session_axis_rationale_non_empty() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.rationale


def test_c05_canonical_session_axis_module_path_correct() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.module_path == "core.canonical_session_axis"


def test_c06_canonical_session_axis_category_is_governance_authority() -> None:
    record = _get_surface("canonical_session_axis")
    assert record is not None
    assert record.category == SurfaceCategory.GOVERNANCE_AUTHORITY


# ---------------------------------------------------------------------------
# D. canonical_session_truth surface fields
# ---------------------------------------------------------------------------


def test_d01_canonical_session_truth_is_canonical_stable() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.tier == StabilizationTier.CANONICAL_STABLE


def test_d02_canonical_session_truth_is_extension_ready() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.is_extension_ready is True


def test_d03_canonical_session_truth_has_no_canonical_replacement() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.canonical_replacement is None


def test_d04_canonical_session_truth_rationale_non_empty() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.rationale


def test_d05_canonical_session_truth_module_path_correct() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.module_path == "core.canonical_session_truth"


def test_d06_canonical_session_truth_category_is_session_lifecycle() -> None:
    record = _get_surface("canonical_session_truth")
    assert record is not None
    assert record.category == SurfaceCategory.SESSION_LIFECYCLE


# ---------------------------------------------------------------------------
# E. attached_runtime_session_registry surface fields
# ---------------------------------------------------------------------------


def test_e01_attached_runtime_session_registry_is_canonical_stable() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.tier == StabilizationTier.CANONICAL_STABLE


def test_e02_attached_runtime_session_registry_is_extension_ready() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.is_extension_ready is True


def test_e03_attached_runtime_session_registry_has_no_canonical_replacement() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.canonical_replacement is None


def test_e04_attached_runtime_session_registry_rationale_non_empty() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.rationale


def test_e05_attached_runtime_session_registry_module_path_correct() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.module_path == "core.attached_runtime_session_registry"


def test_e06_attached_runtime_session_registry_category_is_session_lifecycle() -> None:
    record = _get_surface("attached_runtime_session_registry")
    assert record is not None
    assert record.category == SurfaceCategory.SESSION_LIFECYCLE


# ---------------------------------------------------------------------------
# F. All three new PR-11 surfaces are CANONICAL_STABLE and extension-ready
# ---------------------------------------------------------------------------


def test_f01_all_pr11_surfaces_are_canonical_stable() -> None:
    for sid in _PR11_NEW_SURFACE_IDS:
        record = _get_surface(sid)
        assert record is not None, f"Surface {sid!r} not in catalog"
        assert record.tier == StabilizationTier.CANONICAL_STABLE, (
            f"Surface {sid!r} expected CANONICAL_STABLE, got {record.tier.value!r}"
        )


def test_f02_all_pr11_surfaces_are_extension_ready() -> None:
    for sid in _PR11_NEW_SURFACE_IDS:
        record = _get_surface(sid)
        assert record is not None, f"Surface {sid!r} not in catalog"
        assert record.is_extension_ready is True, (
            f"Surface {sid!r} is not extension_ready"
        )


# ---------------------------------------------------------------------------
# G. No new PR-11 surface has canonical_replacement set
# ---------------------------------------------------------------------------


def test_g01_no_pr11_surface_has_canonical_replacement() -> None:
    for sid in _PR11_NEW_SURFACE_IDS:
        record = _get_surface(sid)
        assert record is not None, f"Surface {sid!r} not in catalog"
        assert record.canonical_replacement is None, (
            f"CANONICAL_STABLE PR-11 surface {sid!r} unexpectedly has "
            f"canonical_replacement={record.canonical_replacement!r}"
        )


# ---------------------------------------------------------------------------
# H. Catalog uniqueness still holds after PR-11 additions
# ---------------------------------------------------------------------------


def test_h01_catalog_surface_ids_still_unique() -> None:
    catalog = get_baseline_catalog()
    ids = [r.surface_id for r in catalog]
    assert len(ids) == len(set(ids)), "Duplicate surface_id found in catalog after PR-11"


# ---------------------------------------------------------------------------
# I. get_canonical_stable_surfaces() includes all three new PR-11 surfaces
# ---------------------------------------------------------------------------


def test_i01_canonical_stable_surfaces_includes_session_axis() -> None:
    stable = get_canonical_stable_surfaces()
    ids = {s.surface_id for s in stable}
    assert "canonical_session_axis" in ids


def test_i02_canonical_stable_surfaces_includes_session_truth() -> None:
    stable = get_canonical_stable_surfaces()
    ids = {s.surface_id for s in stable}
    assert "canonical_session_truth" in ids


def test_i03_canonical_stable_surfaces_includes_session_registry() -> None:
    stable = get_canonical_stable_surfaces()
    ids = {s.surface_id for s in stable}
    assert "attached_runtime_session_registry" in ids


# ---------------------------------------------------------------------------
# J. Snapshot total_surface_count floor
# ---------------------------------------------------------------------------

# PR-10 catalog had 22 surfaces; PR-11 adds 3 more → minimum 25.
_PR11_MINIMUM_SURFACE_COUNT = 25


def test_j01_snapshot_total_surface_count_at_least_pr11_floor() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert snap.total_surface_count >= _PR11_MINIMUM_SURFACE_COUNT, (
        f"Expected at least {_PR11_MINIMUM_SURFACE_COUNT} surfaces after PR-11, "
        f"got {snap.total_surface_count}"
    )


# ---------------------------------------------------------------------------
# K. Snapshot canonical_stable_count includes new PR-11 surfaces
# ---------------------------------------------------------------------------

# PR-10 had 13 CANONICAL_STABLE surfaces; PR-11 adds 3 more → minimum 16.
_PR11_MINIMUM_CANONICAL_STABLE_COUNT = 16


def test_k01_snapshot_canonical_stable_count_at_least_pr11_floor() -> None:
    snap = build_stabilization_baseline_snapshot()
    assert snap.canonical_stable_count >= _PR11_MINIMUM_CANONICAL_STABLE_COUNT, (
        f"Expected at least {_PR11_MINIMUM_CANONICAL_STABLE_COUNT} "
        f"CANONICAL_STABLE surfaces after PR-11, got {snap.canonical_stable_count}"
    )


# ---------------------------------------------------------------------------
# L. PR-11 sentinel importable from __all__
# ---------------------------------------------------------------------------


def test_l01_pr11_sentinel_in_module_all() -> None:
    import core.architecture_stabilization_baseline as mod
    assert "ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL" in mod.__all__


# ---------------------------------------------------------------------------
# M/N/O. Sentinel keyword content (aliased to A above, but explicit checks)
# ---------------------------------------------------------------------------


def test_m01_pr11_sentinel_contains_session_axis() -> None:
    assert "session" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL.lower()


def test_n01_pr11_sentinel_contains_canonical() -> None:
    assert "canonical" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL.lower()


def test_o01_pr11_sentinel_contains_pr11() -> None:
    assert "PR-11" in ARCHITECTURE_STABILIZATION_BASELINE_PR11_SENTINEL


# ---------------------------------------------------------------------------
# classify_surface_tier() spot-checks for new surfaces
# ---------------------------------------------------------------------------


def test_p01_classify_canonical_session_axis_is_canonical_stable() -> None:
    tier = classify_surface_tier("canonical_session_axis")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_p02_classify_canonical_session_truth_is_canonical_stable() -> None:
    tier = classify_surface_tier("canonical_session_truth")
    assert tier == StabilizationTier.CANONICAL_STABLE


def test_p03_classify_attached_runtime_session_registry_is_canonical_stable() -> None:
    tier = classify_surface_tier("attached_runtime_session_registry")
    assert tier == StabilizationTier.CANONICAL_STABLE
