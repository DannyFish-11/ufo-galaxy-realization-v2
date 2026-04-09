#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr13_node_remaining_boundary_enforcement.py
=======================================================
PR-13: Finalize Node Boundary Enforcement — Explicit Classification of All
Remaining Node-Related Surfaces.

Verifies that:

A) Sentinel / policy strings
   - NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY is importable, non-empty,
     and contains expected keywords.
   - NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL is importable and
     contains machine-checkable boundary terms.
   - All four policy sentinels are importable and non-empty.

B) RemainingNodeSurfaceCategory enum
   - Has CANONICAL, COMPAT_ONLY, INTERNAL_ONLY, DEPRECATED members.
   - Values are stable strings.

C) NodeSurfaceBoundaryRecord dataclass
   - Instantiable with explicit args.
   - to_dict() returns all required keys.
   - Correct defaults for pr_classified and notes.

D) build_remaining_surface_boundary_catalog
   - Returns a non-empty list of NodeSurfaceBoundaryRecord instances.
   - Contains at least one COMPAT_ONLY record.
   - Contains at least one INTERNAL_ONLY record.
   - Contains at least one DEPRECATED record.
   - Contains at least one CANONICAL record.
   - Every record has a non-empty surface_id.
   - Every non-CANONICAL record has a non-empty canonical_replacement.

E) get_compat_only_surfaces / get_internal_only_surfaces / get_deprecated_surfaces
   - Each returns a non-empty list.
   - Each returns only records of the expected category.
   - get_canonical_surfaces() returns only CANONICAL records.

F) validate_no_compat_as_primary_canonical_authority
   - Returns True for the default catalog (all compat/deprecated have replacements).
   - Returns False when a compat record has an empty canonical_replacement.

G) build_boundary_enforcement_summary
   - Returns dict with all required keys.
   - Counts match the actual catalog breakdown.
   - no_compat_as_primary_authority is True for default catalog.
   - surfaces list is non-empty.
   - authority key is non-empty.

H) core/routes/system.py — PR-13 compat sentinel
   - SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL is importable
     and contains expected terms.

I) core/routes/projection.py sentinel
   - NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13 is importable and
     contains key terms.

J) Specific catalog entries verification
   - node_registry_compat_facade_pr13 is COMPAT_ONLY.
   - node_registry_json_scan is COMPAT_ONLY.
   - system_status_legacy_supplement is COMPAT_ONLY.
   - nodes_status_legacy_supplement is COMPAT_ONLY.
   - node_discovery_udp_service is INTERNAL_ONLY.
   - node_communication_internal is INTERNAL_ONLY.
   - node_protocol_internal is INTERNAL_ONLY.
   - node_factory_engine_internal is INTERNAL_ONLY.
   - nodes_dir_filesystem_scan is DEPRECATED.
   - node_status_cache_as_canonical_status is DEPRECATED.

K) BoundaryEnforcementSummary dataclass
   - to_dict() returns all required top-level keys.
   - Counts sum to total_surfaces.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest


# ===========================================================================
# A) Sentinel / policy strings
# ===========================================================================

class TestSentinelStrings:

    def test_authority_importable(self):
        from core.node_remaining_boundary_enforcement import (
            NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
        )
        assert isinstance(NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY, str)
        assert len(NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY) > 0
        assert "AUTHORITY" in NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY

    def test_authority_contains_expected_terms(self):
        from core.node_remaining_boundary_enforcement import (
            NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
        )
        assert "compat-only" in NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY
        assert "internal-only" in NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY
        assert "deprecated" in NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY

    def test_pr13_sentinel_importable(self):
        from core.node_remaining_boundary_enforcement import (
            NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL,
        )
        assert isinstance(NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL, str)
        assert "PR13_SENTINEL" in NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL

    def test_pr13_sentinel_contains_boundary_terms(self):
        from core.node_remaining_boundary_enforcement import (
            NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL,
        )
        sentinel = NODE_REMAINING_BOUNDARY_ENFORCEMENT_PR13_SENTINEL
        assert "compat" in sentinel.lower()
        assert "internal" in sentinel.lower()

    def test_compat_policy_importable(self):
        from core.node_remaining_boundary_enforcement import (
            COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY,
        )
        assert isinstance(COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY, str)
        assert len(COMPAT_SURFACES_MUST_NOT_BE_SOLE_CANONICAL_SOURCE_POLICY) > 0

    def test_internal_policy_importable(self):
        from core.node_remaining_boundary_enforcement import (
            INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY,
        )
        assert isinstance(
            INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY, str
        )
        assert len(INTERNAL_SURFACES_MUST_NOT_BE_USED_BY_EXTERNAL_CONSUMERS_POLICY) > 0

    def test_deprecated_policy_importable(self):
        from core.node_remaining_boundary_enforcement import (
            DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY,
        )
        assert isinstance(
            DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY, str
        )
        assert len(
            DEPRECATED_SURFACES_MUST_NOT_APPEAR_ON_ACTIVE_CANONICAL_PATHS_POLICY
        ) > 0

    def test_system_status_policy_importable(self):
        from core.node_remaining_boundary_enforcement import (
            SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY,
        )
        assert isinstance(
            SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY, str
        )
        assert "compat" in (
            SYSTEM_STATUS_COMPAT_SUPPLEMENT_MUST_BE_EXPLICITLY_LABELLED_POLICY.lower()
        )


# ===========================================================================
# B) RemainingNodeSurfaceCategory enum
# ===========================================================================

class TestRemainingNodeSurfaceCategory:

    def test_has_all_members(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        assert hasattr(RemainingNodeSurfaceCategory, "CANONICAL")
        assert hasattr(RemainingNodeSurfaceCategory, "COMPAT_ONLY")
        assert hasattr(RemainingNodeSurfaceCategory, "INTERNAL_ONLY")
        assert hasattr(RemainingNodeSurfaceCategory, "DEPRECATED")

    def test_value_strings(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        assert RemainingNodeSurfaceCategory.CANONICAL.value == "canonical"
        assert RemainingNodeSurfaceCategory.COMPAT_ONLY.value == "compat_only"
        assert RemainingNodeSurfaceCategory.INTERNAL_ONLY.value == "internal_only"
        assert RemainingNodeSurfaceCategory.DEPRECATED.value == "deprecated"

    def test_all_members_count(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        assert len(list(RemainingNodeSurfaceCategory)) == 4


# ===========================================================================
# C) NodeSurfaceBoundaryRecord dataclass
# ===========================================================================

class TestNodeSurfaceBoundaryRecord:

    def test_instantiable_with_required_args(self):
        from core.node_remaining_boundary_enforcement import (
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        rec = NodeSurfaceBoundaryRecord(
            surface_id="test_surface",
            display_name="Test Surface",
            category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
            canonical_replacement="Use canonical surface",
        )
        assert rec.surface_id == "test_surface"
        assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY
        assert rec.pr_classified == "PR-13"
        assert rec.notes == ""

    def test_to_dict_returns_all_keys(self):
        from core.node_remaining_boundary_enforcement import (
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        rec = NodeSurfaceBoundaryRecord(
            surface_id="test_surface",
            display_name="Test Surface",
            category=RemainingNodeSurfaceCategory.INTERNAL_ONLY,
            canonical_replacement="use canonical",
            notes="Test note",
        )
        d = rec.to_dict()
        required_keys = {
            "surface_id", "display_name", "category",
            "canonical_replacement", "pr_classified", "notes",
        }
        assert required_keys.issubset(set(d.keys()))
        assert d["category"] == "internal_only"

    def test_to_dict_category_is_string_value(self):
        from core.node_remaining_boundary_enforcement import (
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        rec = NodeSurfaceBoundaryRecord(
            surface_id="dep_surface",
            display_name="Deprecated Surface",
            category=RemainingNodeSurfaceCategory.DEPRECATED,
            canonical_replacement="use new surface",
        )
        d = rec.to_dict()
        assert isinstance(d["category"], str)
        assert d["category"] == "deprecated"


# ===========================================================================
# D) build_remaining_surface_boundary_catalog
# ===========================================================================

class TestBuildRemainingCatalog:

    def test_returns_non_empty_list(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
        )
        catalog = build_remaining_surface_boundary_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) > 0

    def test_contains_compat_only(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        compat = [r for r in catalog if r.category == RemainingNodeSurfaceCategory.COMPAT_ONLY]
        assert len(compat) > 0

    def test_contains_internal_only(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        internal = [r for r in catalog if r.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY]
        assert len(internal) > 0

    def test_contains_deprecated(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        deprecated = [r for r in catalog if r.category == RemainingNodeSurfaceCategory.DEPRECATED]
        assert len(deprecated) > 0

    def test_contains_canonical(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        canonical = [r for r in catalog if r.category == RemainingNodeSurfaceCategory.CANONICAL]
        assert len(canonical) > 0

    def test_all_records_have_non_empty_surface_id(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
        )
        catalog = build_remaining_surface_boundary_catalog()
        for rec in catalog:
            assert rec.surface_id.strip(), (
                f"surface_id must be non-empty; got empty for record {rec!r}"
            )

    def test_non_canonical_records_have_canonical_replacement(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        for rec in catalog:
            if rec.category != RemainingNodeSurfaceCategory.CANONICAL:
                assert rec.canonical_replacement.strip(), (
                    f"Non-canonical surface '{rec.surface_id}' must have a "
                    f"non-empty canonical_replacement"
                )

    def test_returns_new_list_each_call(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
        )
        c1 = build_remaining_surface_boundary_catalog()
        c2 = build_remaining_surface_boundary_catalog()
        assert c1 is not c2  # separate list objects


# ===========================================================================
# E) get_compat_only_surfaces / get_internal_only_surfaces /
#    get_deprecated_surfaces / get_canonical_surfaces
# ===========================================================================

class TestFilterHelpers:

    def test_get_compat_only_returns_only_compat(self):
        from core.node_remaining_boundary_enforcement import (
            get_compat_only_surfaces,
            RemainingNodeSurfaceCategory,
        )
        results = get_compat_only_surfaces()
        assert len(results) > 0
        for rec in results:
            assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY

    def test_get_internal_only_returns_only_internal(self):
        from core.node_remaining_boundary_enforcement import (
            get_internal_only_surfaces,
            RemainingNodeSurfaceCategory,
        )
        results = get_internal_only_surfaces()
        assert len(results) > 0
        for rec in results:
            assert rec.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY

    def test_get_deprecated_returns_only_deprecated(self):
        from core.node_remaining_boundary_enforcement import (
            get_deprecated_surfaces,
            RemainingNodeSurfaceCategory,
        )
        results = get_deprecated_surfaces()
        assert len(results) > 0
        for rec in results:
            assert rec.category == RemainingNodeSurfaceCategory.DEPRECATED

    def test_get_canonical_returns_only_canonical(self):
        from core.node_remaining_boundary_enforcement import (
            get_canonical_surfaces,
            RemainingNodeSurfaceCategory,
        )
        results = get_canonical_surfaces()
        assert len(results) > 0
        for rec in results:
            assert rec.category == RemainingNodeSurfaceCategory.CANONICAL

    def test_filter_helpers_are_consistent_with_catalog(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            get_compat_only_surfaces,
            get_internal_only_surfaces,
            get_deprecated_surfaces,
            get_canonical_surfaces,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        total = (
            len(get_compat_only_surfaces())
            + len(get_internal_only_surfaces())
            + len(get_deprecated_surfaces())
            + len(get_canonical_surfaces())
        )
        assert total == len(catalog)


# ===========================================================================
# F) validate_no_compat_as_primary_canonical_authority
# ===========================================================================

class TestValidateNoCompatAsPrimary:

    def test_returns_true_for_default_catalog(self):
        from core.node_remaining_boundary_enforcement import (
            validate_no_compat_as_primary_canonical_authority,
        )
        result = validate_no_compat_as_primary_canonical_authority()
        assert result is True

    def test_returns_false_when_compat_has_empty_replacement(self):
        from core.node_remaining_boundary_enforcement import (
            validate_no_compat_as_primary_canonical_authority,
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        import core.node_remaining_boundary_enforcement as _mod

        # Temporarily inject a bad record
        bad_record = NodeSurfaceBoundaryRecord(
            surface_id="bad_compat",
            display_name="Bad Compat",
            category=RemainingNodeSurfaceCategory.COMPAT_ONLY,
            canonical_replacement="",  # empty — violation
        )
        original = list(_mod._REMAINING_SURFACE_CATALOGUE)
        try:
            _mod._REMAINING_SURFACE_CATALOGUE.append(bad_record)
            result = validate_no_compat_as_primary_canonical_authority()
            assert result is False
        finally:
            _mod._REMAINING_SURFACE_CATALOGUE[:] = original

    def test_returns_false_when_deprecated_has_empty_replacement(self):
        from core.node_remaining_boundary_enforcement import (
            validate_no_compat_as_primary_canonical_authority,
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        import core.node_remaining_boundary_enforcement as _mod

        bad_record = NodeSurfaceBoundaryRecord(
            surface_id="bad_deprecated",
            display_name="Bad Deprecated",
            category=RemainingNodeSurfaceCategory.DEPRECATED,
            canonical_replacement="",  # empty — violation
        )
        original = list(_mod._REMAINING_SURFACE_CATALOGUE)
        try:
            _mod._REMAINING_SURFACE_CATALOGUE.append(bad_record)
            result = validate_no_compat_as_primary_canonical_authority()
            assert result is False
        finally:
            _mod._REMAINING_SURFACE_CATALOGUE[:] = original

    def test_canonical_records_with_empty_replacement_do_not_cause_failure(self):
        from core.node_remaining_boundary_enforcement import (
            validate_no_compat_as_primary_canonical_authority,
            NodeSurfaceBoundaryRecord,
            RemainingNodeSurfaceCategory,
        )
        import core.node_remaining_boundary_enforcement as _mod

        # CANONICAL records are allowed to have empty canonical_replacement
        extra_canonical = NodeSurfaceBoundaryRecord(
            surface_id="extra_canonical",
            display_name="Extra Canonical",
            category=RemainingNodeSurfaceCategory.CANONICAL,
            canonical_replacement="",  # fine for canonical records
        )
        original = list(_mod._REMAINING_SURFACE_CATALOGUE)
        try:
            _mod._REMAINING_SURFACE_CATALOGUE.append(extra_canonical)
            result = validate_no_compat_as_primary_canonical_authority()
            assert result is True
        finally:
            _mod._REMAINING_SURFACE_CATALOGUE[:] = original


# ===========================================================================
# G) build_boundary_enforcement_summary
# ===========================================================================

class TestBuildBoundaryEnforcementSummary:

    def test_returns_dict_with_required_keys(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        required = {
            "total_surfaces",
            "canonical_count",
            "compat_only_count",
            "internal_only_count",
            "deprecated_count",
            "no_compat_as_primary_authority",
            "surfaces",
            "authority",
        }
        assert required.issubset(set(summary.keys()))

    def test_counts_sum_to_total(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        computed = (
            summary["canonical_count"]
            + summary["compat_only_count"]
            + summary["internal_only_count"]
            + summary["deprecated_count"]
        )
        assert computed == summary["total_surfaces"]

    def test_no_compat_as_primary_is_true(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        assert summary["no_compat_as_primary_authority"] is True

    def test_surfaces_list_non_empty(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        assert isinstance(summary["surfaces"], list)
        assert len(summary["surfaces"]) > 0

    def test_authority_non_empty(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        assert isinstance(summary["authority"], str)
        assert len(summary["authority"]) > 0

    def test_counts_match_filter_helpers(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
            get_compat_only_surfaces,
            get_internal_only_surfaces,
            get_deprecated_surfaces,
            get_canonical_surfaces,
        )
        summary = build_boundary_enforcement_summary()
        assert summary["compat_only_count"] == len(get_compat_only_surfaces())
        assert summary["internal_only_count"] == len(get_internal_only_surfaces())
        assert summary["deprecated_count"] == len(get_deprecated_surfaces())
        assert summary["canonical_count"] == len(get_canonical_surfaces())

    def test_surfaces_list_contains_dicts_with_category_key(self):
        from core.node_remaining_boundary_enforcement import (
            build_boundary_enforcement_summary,
        )
        summary = build_boundary_enforcement_summary()
        for s in summary["surfaces"]:
            assert "category" in s
            assert isinstance(s["category"], str)


# ===========================================================================
# H) core/routes/system.py — PR-13 compat sentinel
# ===========================================================================

class TestSystemRoutesCompatSentinel:

    def test_sentinel_importable(self):
        try:
            from core.routes.system import (
                SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL,
            )
        except ImportError as e:
            pytest.skip(f"system routes not importable: {e}")
        assert isinstance(
            SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL, str
        )
        assert len(
            SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL
        ) > 0

    def test_sentinel_contains_compat_terms(self):
        try:
            from core.routes.system import (
                SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL,
            )
        except ImportError as e:
            pytest.skip(f"system routes not importable: {e}")
        sentinel = SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL
        assert "compat" in sentinel.lower() or "PR13" in sentinel

    def test_sentinel_not_unavailable(self):
        try:
            from core.routes.system import (
                SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL,
            )
        except ImportError as e:
            pytest.skip(f"system routes not importable: {e}")
        sentinel = SYSTEM_ROUTES_NODE_REGISTRY_COMPAT_SUPPLEMENT_PR13_SENTINEL
        assert "UNAVAILABLE" not in sentinel


# ===========================================================================
# I) core/routes/projection.py sentinel
# ===========================================================================

class TestProjectionSentinel:

    def test_sentinel_importable(self):
        try:
            from core.routes.projection import (
                NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13,
            )
        except ImportError as e:
            pytest.skip(f"projection routes not importable: {e}")
        assert isinstance(NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13, str)
        assert len(NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13) > 0

    def test_sentinel_contains_key_terms(self):
        try:
            from core.routes.projection import (
                NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13,
            )
        except ImportError as e:
            pytest.skip(f"projection routes not importable: {e}")
        sentinel = NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13
        assert "PR13" in sentinel or "PR-13" in sentinel

    def test_sentinel_not_unavailable(self):
        try:
            from core.routes.projection import (
                NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13,
            )
        except ImportError as e:
            pytest.skip(f"projection routes not importable: {e}")
        sentinel = NODE_REMAINING_BOUNDARY_ENFORCEMENT_ALIGNED_PR13
        assert "UNAVAILABLE" not in sentinel


# ===========================================================================
# J) Specific catalog entries verification
# ===========================================================================

class TestSpecificCatalogEntries:

    def _get_by_id(self, surface_id: str):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
        )
        catalog = build_remaining_surface_boundary_catalog()
        matches = [r for r in catalog if r.surface_id == surface_id]
        assert len(matches) == 1, (
            f"Expected exactly one record with surface_id='{surface_id}', "
            f"got {len(matches)}"
        )
        return matches[0]

    def test_node_registry_compat_facade_is_compat_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_registry_compat_facade_pr13")
        assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY

    def test_node_registry_json_scan_is_compat_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_registry_json_scan")
        assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY

    def test_system_status_legacy_supplement_is_compat_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("system_status_legacy_supplement")
        assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY

    def test_nodes_status_legacy_supplement_is_compat_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("nodes_status_legacy_supplement")
        assert rec.category == RemainingNodeSurfaceCategory.COMPAT_ONLY

    def test_node_discovery_udp_service_is_internal_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_discovery_udp_service")
        assert rec.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY

    def test_node_communication_internal_is_internal_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_communication_internal")
        assert rec.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY

    def test_node_protocol_internal_is_internal_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_protocol_internal")
        assert rec.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY

    def test_node_factory_engine_internal_is_internal_only(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_factory_engine_internal")
        assert rec.category == RemainingNodeSurfaceCategory.INTERNAL_ONLY

    def test_nodes_dir_filesystem_scan_is_deprecated(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("nodes_dir_filesystem_scan")
        assert rec.category == RemainingNodeSurfaceCategory.DEPRECATED

    def test_node_status_cache_as_canonical_is_deprecated(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_status_cache_as_canonical_status")
        assert rec.category == RemainingNodeSurfaceCategory.DEPRECATED

    def test_node_fabric_registry_is_canonical(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_fabric_registry_canonical")
        assert rec.category == RemainingNodeSurfaceCategory.CANONICAL

    def test_node_invocation_is_canonical(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_invocation_canonical")
        assert rec.category == RemainingNodeSurfaceCategory.CANONICAL

    def test_node_lifecycle_governor_is_canonical(self):
        from core.node_remaining_boundary_enforcement import RemainingNodeSurfaceCategory
        rec = self._get_by_id("node_lifecycle_governor_canonical")
        assert rec.category == RemainingNodeSurfaceCategory.CANONICAL

    def test_all_compat_and_deprecated_have_canonical_replacement(self):
        from core.node_remaining_boundary_enforcement import (
            build_remaining_surface_boundary_catalog,
            RemainingNodeSurfaceCategory,
        )
        catalog = build_remaining_surface_boundary_catalog()
        for rec in catalog:
            if rec.category in (
                RemainingNodeSurfaceCategory.COMPAT_ONLY,
                RemainingNodeSurfaceCategory.DEPRECATED,
            ):
                assert rec.canonical_replacement.strip(), (
                    f"surface '{rec.surface_id}' (category={rec.category.value}) "
                    "must have a non-empty canonical_replacement"
                )


# ===========================================================================
# K) BoundaryEnforcementSummary dataclass
# ===========================================================================

class TestBoundaryEnforcementSummary:

    def test_to_dict_returns_required_keys(self):
        from core.node_remaining_boundary_enforcement import BoundaryEnforcementSummary
        s = BoundaryEnforcementSummary(
            total_surfaces=5,
            canonical_count=2,
            compat_only_count=1,
            internal_only_count=1,
            deprecated_count=1,
        )
        d = s.to_dict()
        required = {
            "total_surfaces", "canonical_count", "compat_only_count",
            "internal_only_count", "deprecated_count",
            "no_compat_as_primary_authority", "surfaces", "authority",
        }
        assert required.issubset(set(d.keys()))

    def test_to_dict_surfaces_is_list(self):
        from core.node_remaining_boundary_enforcement import BoundaryEnforcementSummary
        s = BoundaryEnforcementSummary(total_surfaces=0)
        d = s.to_dict()
        assert isinstance(d["surfaces"], list)

    def test_default_no_compat_as_primary_is_true(self):
        from core.node_remaining_boundary_enforcement import BoundaryEnforcementSummary
        s = BoundaryEnforcementSummary()
        assert s.no_compat_as_primary_authority is True

    def test_authority_defaults_to_authority_sentinel(self):
        from core.node_remaining_boundary_enforcement import (
            BoundaryEnforcementSummary,
            NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY,
        )
        s = BoundaryEnforcementSummary()
        assert s.authority == NODE_REMAINING_BOUNDARY_ENFORCEMENT_IS_AUTHORITY
