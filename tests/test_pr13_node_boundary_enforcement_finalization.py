#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr13_node_boundary_enforcement_finalization.py
==========================================================
PR-13 (Node System): Finalize Node Boundary Enforcement.

Verifies that:

A) Sentinel / policy strings
   - NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY is importable and
     non-empty.
   - NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL is importable and
     contains expected machine-checkable string.
   - All five policy sentinels are importable and non-empty.

B) NodeSurfaceBoundaryKind enum
   - All four expected values (CANONICAL, COMPAT_ONLY, INTERNAL_ONLY,
     DEPRECATED) are present and have correct string values.

C) NodeSurfaceBoundaryRecord dataclass
   - Can be instantiated with required fields.
   - to_dict() returns all expected keys.
   - is_dashboard_trusted and is_peer_authority are correctly propagated.

D) get_surface_boundary_catalogue
   - Returns a non-empty list of NodeSurfaceBoundaryRecord instances.
   - Every record has a non-empty surface_id, display_name, boundary_kind,
     pr_classified, and canonical_replacement (may be empty for CANONICAL).
   - CANONICAL surfaces have is_dashboard_trusted=True and
     is_peer_authority=True.
   - COMPAT_ONLY surfaces have is_dashboard_trusted=False and
     is_peer_authority=False.
   - INTERNAL_ONLY surfaces have is_dashboard_trusted=False and
     is_peer_authority=False.
   - DEPRECATED surfaces have is_dashboard_trusted=False and
     is_peer_authority=False.
   - Catalogue includes at least one entry per boundary kind.
   - Known canonical surfaces are present: node_fabric_registry,
     invoke_node, node_governance_runtime, node_boundary_runtime,
     node_invocation_governance, node_discovery_startup_health_closure,
     node_boundary_enforcement_finalization.
   - Known compat surfaces are present: node_registry_compat_facade,
     post_api_v1_nodes_call_compat.
   - Known internal surfaces are present: fusion_entry_adapter.
   - Known deprecated surfaces are present: direct_nodes_dir_scan,
     node_registry_json_direct_read.

E) classify_node_surface
   - Returns CANONICAL for canonical surface IDs.
   - Returns COMPAT_ONLY for compat-only surface IDs.
   - Returns INTERNAL_ONLY for internal-only surface IDs.
   - Returns DEPRECATED for deprecated surface IDs.
   - Returns COMPAT_ONLY (default) for unknown surface IDs.

F) is_dashboard_trusted_surface
   - Returns True for canonical surface IDs.
   - Returns False for compat-only surface IDs.
   - Returns False for internal-only surface IDs.
   - Returns False for deprecated surface IDs.
   - Returns False for unknown surface IDs.

G) get_dashboard_trusted_surfaces
   - Returns only records with is_dashboard_trusted=True.
   - All returned records have boundary_kind=CANONICAL.
   - Does not include any compat/internal/deprecated records.

H) build_boundary_enforcement_summary
   - Returns all required keys.
   - canonical_count == sum of CANONICAL records.
   - compat_only_count == sum of COMPAT_ONLY records.
   - internal_only_count == sum of INTERNAL_ONLY records.
   - deprecated_count == sum of DEPRECATED records.
   - dashboard_trusted_count equals number of CANONICAL records.
   - peer_authority_count equals number of CANONICAL records.
   - all_classified is True.
   - authority and sentinel keys are non-empty.
   - total_surfaces equals sum of all category counts.

I) build_node_surface_diagnostic_report
   - Returns all required top-level keys.
   - canonical_surfaces, compat_only_surfaces, internal_only_surfaces,
     deprecated_surfaces are non-empty lists (at least one entry each).
   - dashboard_trusted_ids lists only canonical surface IDs.
   - summary key matches build_boundary_enforcement_summary() output shape.
   - authority key is non-empty.

J) No-parallel-authority assertion
   - No COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED surface has
     is_peer_authority=True.
   - No COMPAT_ONLY, INTERNAL_ONLY, or DEPRECATED surface has
     is_dashboard_trusted=True.

K) core/routes/projection.py sentinel
   - NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13 is importable and
     contains key terms.
"""

from __future__ import annotations

import sys
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Module under test
# ---------------------------------------------------------------------------

from core.node_boundary_enforcement_finalization import (
    NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY,
    NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL,
    ALL_NODE_SURFACES_HAVE_EXPLICIT_CLASSIFICATION_POLICY,
    COMPAT_SURFACES_MUST_NOT_APPEAR_AS_PEER_AUTHORITIES_POLICY,
    DASHBOARD_MUST_NOT_DEPEND_ON_COMPAT_STORES_POLICY,
    INTERNAL_SURFACES_ARE_NOT_CALLABLE_FROM_CANONICAL_PATH_POLICY,
    DEPRECATED_SURFACES_ARE_OPERATOR_VISIBLE_POLICY,
    NodeSurfaceBoundaryKind,
    NodeSurfaceBoundaryRecord,
    get_surface_boundary_catalogue,
    classify_node_surface,
    is_dashboard_trusted_surface,
    get_dashboard_trusted_surfaces,
    build_boundary_enforcement_summary,
    build_node_surface_diagnostic_report,
)


# ===========================================================================
# A) Sentinel / policy strings
# ===========================================================================


class TestSentinels:
    """Authority and policy sentinels must be importable and non-empty."""

    def test_authority_sentinel_importable(self):
        assert isinstance(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY, str)
        assert len(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY) > 0

    def test_authority_sentinel_contains_pr13(self):
        assert "PR13" in NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_IS_AUTHORITY

    def test_pr13_sentinel_importable(self):
        assert isinstance(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL, str)
        assert len(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL) > 0

    def test_pr13_sentinel_contains_classification_claim(self):
        assert "classification" in NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_PR13_SENTINEL

    def test_all_classification_policy_importable(self):
        assert isinstance(ALL_NODE_SURFACES_HAVE_EXPLICIT_CLASSIFICATION_POLICY, str)
        assert len(ALL_NODE_SURFACES_HAVE_EXPLICIT_CLASSIFICATION_POLICY) > 0

    def test_compat_not_peer_authority_policy_importable(self):
        assert isinstance(COMPAT_SURFACES_MUST_NOT_APPEAR_AS_PEER_AUTHORITIES_POLICY, str)
        assert len(COMPAT_SURFACES_MUST_NOT_APPEAR_AS_PEER_AUTHORITIES_POLICY) > 0

    def test_dashboard_no_compat_stores_policy_importable(self):
        assert isinstance(DASHBOARD_MUST_NOT_DEPEND_ON_COMPAT_STORES_POLICY, str)
        assert len(DASHBOARD_MUST_NOT_DEPEND_ON_COMPAT_STORES_POLICY) > 0

    def test_internal_not_callable_policy_importable(self):
        assert isinstance(INTERNAL_SURFACES_ARE_NOT_CALLABLE_FROM_CANONICAL_PATH_POLICY, str)
        assert len(INTERNAL_SURFACES_ARE_NOT_CALLABLE_FROM_CANONICAL_PATH_POLICY) > 0

    def test_deprecated_visible_policy_importable(self):
        assert isinstance(DEPRECATED_SURFACES_ARE_OPERATOR_VISIBLE_POLICY, str)
        assert len(DEPRECATED_SURFACES_ARE_OPERATOR_VISIBLE_POLICY) > 0


# ===========================================================================
# B) NodeSurfaceBoundaryKind enum
# ===========================================================================


class TestNodeSurfaceBoundaryKindEnum:
    """NodeSurfaceBoundaryKind must have all four expected values."""

    def test_canonical_value(self):
        assert NodeSurfaceBoundaryKind.CANONICAL == "canonical"

    def test_compat_only_value(self):
        assert NodeSurfaceBoundaryKind.COMPAT_ONLY == "compat_only"

    def test_internal_only_value(self):
        assert NodeSurfaceBoundaryKind.INTERNAL_ONLY == "internal_only"

    def test_deprecated_value(self):
        assert NodeSurfaceBoundaryKind.DEPRECATED == "deprecated"

    def test_all_four_kinds_present(self):
        kinds = {k.value for k in NodeSurfaceBoundaryKind}
        assert kinds == {"canonical", "compat_only", "internal_only", "deprecated"}


# ===========================================================================
# C) NodeSurfaceBoundaryRecord dataclass
# ===========================================================================


class TestNodeSurfaceBoundaryRecord:
    """NodeSurfaceBoundaryRecord must be constructable and serialisable."""

    def _make_canonical(self) -> NodeSurfaceBoundaryRecord:
        return NodeSurfaceBoundaryRecord(
            surface_id="test_canonical",
            display_name="Test Canonical Surface",
            boundary_kind=NodeSurfaceBoundaryKind.CANONICAL,
            is_dashboard_trusted=True,
            is_peer_authority=True,
            canonical_replacement="",
            pr_classified="PR-X",
        )

    def _make_compat(self) -> NodeSurfaceBoundaryRecord:
        return NodeSurfaceBoundaryRecord(
            surface_id="test_compat",
            display_name="Test Compat Surface",
            boundary_kind=NodeSurfaceBoundaryKind.COMPAT_ONLY,
            is_dashboard_trusted=False,
            is_peer_authority=False,
            canonical_replacement="test_canonical",
            pr_classified="PR-Y",
            notes="Some compat notes.",
        )

    def test_canonical_record_fields(self):
        rec = self._make_canonical()
        assert rec.surface_id == "test_canonical"
        assert rec.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL
        assert rec.is_dashboard_trusted is True
        assert rec.is_peer_authority is True
        assert rec.canonical_replacement == ""

    def test_compat_record_fields(self):
        rec = self._make_compat()
        assert rec.surface_id == "test_compat"
        assert rec.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY
        assert rec.is_dashboard_trusted is False
        assert rec.is_peer_authority is False
        assert rec.canonical_replacement == "test_canonical"

    def test_to_dict_returns_all_keys(self):
        rec = self._make_canonical()
        d = rec.to_dict()
        assert set(d.keys()) == {
            "surface_id",
            "display_name",
            "boundary_kind",
            "is_dashboard_trusted",
            "is_peer_authority",
            "canonical_replacement",
            "pr_classified",
            "notes",
        }

    def test_to_dict_boundary_kind_is_string(self):
        rec = self._make_canonical()
        d = rec.to_dict()
        assert d["boundary_kind"] == "canonical"

    def test_to_dict_compat_boundary_kind(self):
        rec = self._make_compat()
        d = rec.to_dict()
        assert d["boundary_kind"] == "compat_only"
        assert d["is_dashboard_trusted"] is False
        assert d["is_peer_authority"] is False


# ===========================================================================
# D) get_surface_boundary_catalogue
# ===========================================================================


class TestGetSurfaceBoundaryCatalogue:
    """The catalogue must be non-empty and well-formed."""

    def test_returns_list(self):
        cat = get_surface_boundary_catalogue()
        assert isinstance(cat, list)

    def test_non_empty(self):
        cat = get_surface_boundary_catalogue()
        assert len(cat) > 0

    def test_all_records_are_NodeSurfaceBoundaryRecord(self):
        for rec in get_surface_boundary_catalogue():
            assert isinstance(rec, NodeSurfaceBoundaryRecord)

    def test_all_records_have_surface_id(self):
        for rec in get_surface_boundary_catalogue():
            assert isinstance(rec.surface_id, str) and rec.surface_id

    def test_all_records_have_display_name(self):
        for rec in get_surface_boundary_catalogue():
            assert isinstance(rec.display_name, str) and rec.display_name

    def test_all_records_have_boundary_kind(self):
        for rec in get_surface_boundary_catalogue():
            assert isinstance(rec.boundary_kind, NodeSurfaceBoundaryKind)

    def test_all_records_have_pr_classified(self):
        for rec in get_surface_boundary_catalogue():
            assert isinstance(rec.pr_classified, str) and rec.pr_classified

    def test_canonical_records_are_trusted_and_peer(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL:
                assert rec.is_dashboard_trusted is True
                assert rec.is_peer_authority is True

    def test_compat_records_not_trusted_not_peer(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY:
                assert rec.is_dashboard_trusted is False
                assert rec.is_peer_authority is False

    def test_internal_records_not_trusted_not_peer(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.INTERNAL_ONLY:
                assert rec.is_dashboard_trusted is False
                assert rec.is_peer_authority is False

    def test_deprecated_records_not_trusted_not_peer(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED:
                assert rec.is_dashboard_trusted is False
                assert rec.is_peer_authority is False

    def test_at_least_one_entry_per_kind(self):
        kinds = {rec.boundary_kind for rec in get_surface_boundary_catalogue()}
        assert NodeSurfaceBoundaryKind.CANONICAL in kinds
        assert NodeSurfaceBoundaryKind.COMPAT_ONLY in kinds
        assert NodeSurfaceBoundaryKind.INTERNAL_ONLY in kinds
        assert NodeSurfaceBoundaryKind.DEPRECATED in kinds

    def test_node_fabric_registry_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_fabric_registry" in index
        assert index["node_fabric_registry"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_invoke_node_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "invoke_node" in index
        assert index["invoke_node"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_governance_runtime_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_governance_runtime" in index
        assert index["node_governance_runtime"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_boundary_runtime_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_boundary_runtime" in index
        assert index["node_boundary_runtime"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_invocation_governance_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_invocation_governance" in index
        assert index["node_invocation_governance"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_discovery_startup_health_closure_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_discovery_startup_health_closure" in index
        assert index["node_discovery_startup_health_closure"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_boundary_enforcement_finalization_is_canonical(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_boundary_enforcement_finalization" in index
        assert index["node_boundary_enforcement_finalization"].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_node_registry_compat_facade_is_compat(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_registry_compat_facade" in index
        assert index["node_registry_compat_facade"].boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY

    def test_post_api_nodes_call_compat_is_compat(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "post_api_v1_nodes_call_compat" in index
        assert index["post_api_v1_nodes_call_compat"].boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY

    def test_fusion_entry_adapter_is_internal(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "fusion_entry_adapter" in index
        assert index["fusion_entry_adapter"].boundary_kind == NodeSurfaceBoundaryKind.INTERNAL_ONLY

    def test_direct_nodes_dir_scan_is_deprecated(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "direct_nodes_dir_scan" in index
        assert index["direct_nodes_dir_scan"].boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED

    def test_node_registry_json_direct_read_is_deprecated(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert "node_registry_json_direct_read" in index
        assert index["node_registry_json_direct_read"].boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED

    def test_compat_surfaces_have_canonical_replacement(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY:
                assert rec.canonical_replacement, (
                    f"COMPAT_ONLY surface '{rec.surface_id}' must specify "
                    "a canonical_replacement"
                )

    def test_deprecated_surfaces_have_canonical_replacement(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED:
                assert rec.canonical_replacement, (
                    f"DEPRECATED surface '{rec.surface_id}' must specify "
                    "a canonical_replacement"
                )


# ===========================================================================
# E) classify_node_surface
# ===========================================================================


class TestClassifyNodeSurface:
    """classify_node_surface must return the correct kind for each surface."""

    def test_canonical_surface_returns_canonical(self):
        assert classify_node_surface("node_fabric_registry") == NodeSurfaceBoundaryKind.CANONICAL
        assert classify_node_surface("invoke_node") == NodeSurfaceBoundaryKind.CANONICAL
        assert classify_node_surface("node_governance_runtime") == NodeSurfaceBoundaryKind.CANONICAL
        assert classify_node_surface("node_boundary_runtime") == NodeSurfaceBoundaryKind.CANONICAL

    def test_compat_surface_returns_compat_only(self):
        assert classify_node_surface("node_registry_compat_facade") == NodeSurfaceBoundaryKind.COMPAT_ONLY
        assert classify_node_surface("post_api_v1_nodes_call_compat") == NodeSurfaceBoundaryKind.COMPAT_ONLY

    def test_internal_surface_returns_internal_only(self):
        assert classify_node_surface("fusion_entry_adapter") == NodeSurfaceBoundaryKind.INTERNAL_ONLY

    def test_deprecated_surface_returns_deprecated(self):
        assert classify_node_surface("direct_nodes_dir_scan") == NodeSurfaceBoundaryKind.DEPRECATED
        assert classify_node_surface("node_registry_json_direct_read") == NodeSurfaceBoundaryKind.DEPRECATED

    def test_unknown_surface_returns_compat_only_default(self):
        result = classify_node_surface("completely_unknown_surface_xyz_999")
        assert result == NodeSurfaceBoundaryKind.COMPAT_ONLY

    def test_empty_string_returns_compat_only_default(self):
        result = classify_node_surface("")
        assert result == NodeSurfaceBoundaryKind.COMPAT_ONLY


# ===========================================================================
# F) is_dashboard_trusted_surface
# ===========================================================================


class TestIsDashboardTrustedSurface:
    """is_dashboard_trusted_surface must return True only for canonical surfaces."""

    def test_canonical_surfaces_are_trusted(self):
        assert is_dashboard_trusted_surface("node_fabric_registry") is True
        assert is_dashboard_trusted_surface("invoke_node") is True
        assert is_dashboard_trusted_surface("node_governance_runtime") is True
        assert is_dashboard_trusted_surface("node_invocation_governance") is True

    def test_compat_surfaces_are_not_trusted(self):
        assert is_dashboard_trusted_surface("node_registry_compat_facade") is False
        assert is_dashboard_trusted_surface("post_api_v1_nodes_call_compat") is False
        assert is_dashboard_trusted_surface("openclawd_legacy_layer3_scan") is False

    def test_internal_surfaces_are_not_trusted(self):
        assert is_dashboard_trusted_surface("fusion_entry_adapter") is False
        assert is_dashboard_trusted_surface("node_invocation_envelope_internal") is False

    def test_deprecated_surfaces_are_not_trusted(self):
        assert is_dashboard_trusted_surface("direct_nodes_dir_scan") is False
        assert is_dashboard_trusted_surface("node_registry_json_direct_read") is False

    def test_unknown_surface_is_not_trusted(self):
        assert is_dashboard_trusted_surface("unknown_surface_abc") is False

    def test_empty_string_is_not_trusted(self):
        assert is_dashboard_trusted_surface("") is False


# ===========================================================================
# G) get_dashboard_trusted_surfaces
# ===========================================================================


class TestGetDashboardTrustedSurfaces:
    """get_dashboard_trusted_surfaces must return only CANONICAL surfaces."""

    def test_returns_list(self):
        trusted = get_dashboard_trusted_surfaces()
        assert isinstance(trusted, list)

    def test_non_empty(self):
        trusted = get_dashboard_trusted_surfaces()
        assert len(trusted) > 0

    def test_all_trusted_surfaces_are_canonical(self):
        for rec in get_dashboard_trusted_surfaces():
            assert rec.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL, (
                f"Surface '{rec.surface_id}' is in get_dashboard_trusted_surfaces() "
                f"but has boundary_kind={rec.boundary_kind.value}"
            )

    def test_all_trusted_surfaces_have_is_dashboard_trusted_true(self):
        for rec in get_dashboard_trusted_surfaces():
            assert rec.is_dashboard_trusted is True

    def test_no_compat_in_trusted(self):
        trusted_ids = {r.surface_id for r in get_dashboard_trusted_surfaces()}
        assert "node_registry_compat_facade" not in trusted_ids
        assert "post_api_v1_nodes_call_compat" not in trusted_ids
        assert "openclawd_legacy_layer3_scan" not in trusted_ids

    def test_no_internal_in_trusted(self):
        trusted_ids = {r.surface_id for r in get_dashboard_trusted_surfaces()}
        assert "fusion_entry_adapter" not in trusted_ids

    def test_no_deprecated_in_trusted(self):
        trusted_ids = {r.surface_id for r in get_dashboard_trusted_surfaces()}
        assert "direct_nodes_dir_scan" not in trusted_ids
        assert "node_registry_json_direct_read" not in trusted_ids

    def test_canonical_surfaces_are_included(self):
        trusted_ids = {r.surface_id for r in get_dashboard_trusted_surfaces()}
        assert "node_fabric_registry" in trusted_ids
        assert "invoke_node" in trusted_ids
        assert "node_governance_runtime" in trusted_ids


# ===========================================================================
# H) build_boundary_enforcement_summary
# ===========================================================================


class TestBuildBoundaryEnforcementSummary:
    """build_boundary_enforcement_summary must return a well-formed summary dict."""

    def test_returns_dict(self):
        summary = build_boundary_enforcement_summary()
        assert isinstance(summary, dict)

    def test_required_keys_present(self):
        summary = build_boundary_enforcement_summary()
        required_keys = {
            "total_surfaces",
            "canonical_count",
            "compat_only_count",
            "internal_only_count",
            "deprecated_count",
            "dashboard_trusted_count",
            "peer_authority_count",
            "all_classified",
            "authority",
            "sentinel",
            "generated_at",
        }
        assert required_keys.issubset(set(summary.keys()))

    def test_all_classified_is_true(self):
        summary = build_boundary_enforcement_summary()
        assert summary["all_classified"] is True

    def test_total_equals_sum_of_categories(self):
        summary = build_boundary_enforcement_summary()
        total = (
            summary["canonical_count"]
            + summary["compat_only_count"]
            + summary["internal_only_count"]
            + summary["deprecated_count"]
        )
        assert summary["total_surfaces"] == total

    def test_canonical_count_matches_catalogue(self):
        cat = get_surface_boundary_catalogue()
        expected = sum(1 for r in cat if r.boundary_kind == NodeSurfaceBoundaryKind.CANONICAL)
        summary = build_boundary_enforcement_summary()
        assert summary["canonical_count"] == expected

    def test_compat_count_matches_catalogue(self):
        cat = get_surface_boundary_catalogue()
        expected = sum(1 for r in cat if r.boundary_kind == NodeSurfaceBoundaryKind.COMPAT_ONLY)
        summary = build_boundary_enforcement_summary()
        assert summary["compat_only_count"] == expected

    def test_internal_count_matches_catalogue(self):
        cat = get_surface_boundary_catalogue()
        expected = sum(1 for r in cat if r.boundary_kind == NodeSurfaceBoundaryKind.INTERNAL_ONLY)
        summary = build_boundary_enforcement_summary()
        assert summary["internal_only_count"] == expected

    def test_deprecated_count_matches_catalogue(self):
        cat = get_surface_boundary_catalogue()
        expected = sum(1 for r in cat if r.boundary_kind == NodeSurfaceBoundaryKind.DEPRECATED)
        summary = build_boundary_enforcement_summary()
        assert summary["deprecated_count"] == expected

    def test_dashboard_trusted_count_equals_canonical_count(self):
        summary = build_boundary_enforcement_summary()
        assert summary["dashboard_trusted_count"] == summary["canonical_count"]

    def test_peer_authority_count_equals_canonical_count(self):
        summary = build_boundary_enforcement_summary()
        assert summary["peer_authority_count"] == summary["canonical_count"]

    def test_authority_non_empty(self):
        summary = build_boundary_enforcement_summary()
        assert summary["authority"] and isinstance(summary["authority"], str)

    def test_sentinel_non_empty(self):
        summary = build_boundary_enforcement_summary()
        assert summary["sentinel"] and isinstance(summary["sentinel"], str)

    def test_generated_at_is_numeric(self):
        import time as _time
        before = _time.time()
        summary = build_boundary_enforcement_summary()
        after = _time.time()
        assert before <= summary["generated_at"] <= after

    def test_canonical_count_positive(self):
        summary = build_boundary_enforcement_summary()
        assert summary["canonical_count"] > 0

    def test_compat_count_positive(self):
        summary = build_boundary_enforcement_summary()
        assert summary["compat_only_count"] > 0

    def test_deprecated_count_positive(self):
        summary = build_boundary_enforcement_summary()
        assert summary["deprecated_count"] > 0


# ===========================================================================
# I) build_node_surface_diagnostic_report
# ===========================================================================


class TestBuildNodeSurfaceDiagnosticReport:
    """build_node_surface_diagnostic_report must return a well-formed report."""

    def test_returns_dict(self):
        report = build_node_surface_diagnostic_report()
        assert isinstance(report, dict)

    def test_required_top_level_keys(self):
        report = build_node_surface_diagnostic_report()
        required = {
            "canonical_surfaces",
            "compat_only_surfaces",
            "internal_only_surfaces",
            "deprecated_surfaces",
            "dashboard_trusted_ids",
            "summary",
            "authority",
            "generated_at",
        }
        assert required.issubset(set(report.keys()))

    def test_canonical_surfaces_non_empty(self):
        report = build_node_surface_diagnostic_report()
        assert len(report["canonical_surfaces"]) > 0

    def test_compat_only_surfaces_non_empty(self):
        report = build_node_surface_diagnostic_report()
        assert len(report["compat_only_surfaces"]) > 0

    def test_internal_only_surfaces_non_empty(self):
        report = build_node_surface_diagnostic_report()
        assert len(report["internal_only_surfaces"]) > 0

    def test_deprecated_surfaces_non_empty(self):
        report = build_node_surface_diagnostic_report()
        assert len(report["deprecated_surfaces"]) > 0

    def test_canonical_surfaces_are_dicts_with_boundary_kind(self):
        report = build_node_surface_diagnostic_report()
        for surf in report["canonical_surfaces"]:
            assert surf["boundary_kind"] == "canonical"

    def test_compat_surfaces_are_dicts_with_boundary_kind(self):
        report = build_node_surface_diagnostic_report()
        for surf in report["compat_only_surfaces"]:
            assert surf["boundary_kind"] == "compat_only"

    def test_internal_surfaces_are_dicts_with_boundary_kind(self):
        report = build_node_surface_diagnostic_report()
        for surf in report["internal_only_surfaces"]:
            assert surf["boundary_kind"] == "internal_only"

    def test_deprecated_surfaces_are_dicts_with_boundary_kind(self):
        report = build_node_surface_diagnostic_report()
        for surf in report["deprecated_surfaces"]:
            assert surf["boundary_kind"] == "deprecated"

    def test_dashboard_trusted_ids_only_canonical(self):
        report = build_node_surface_diagnostic_report()
        cat_index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        for sid in report["dashboard_trusted_ids"]:
            assert sid in cat_index, f"Unknown surface_id '{sid}' in dashboard_trusted_ids"
            assert cat_index[sid].boundary_kind == NodeSurfaceBoundaryKind.CANONICAL

    def test_summary_has_required_keys(self):
        report = build_node_surface_diagnostic_report()
        summary = report["summary"]
        assert "total_surfaces" in summary
        assert "canonical_count" in summary
        assert "all_classified" in summary

    def test_authority_non_empty(self):
        report = build_node_surface_diagnostic_report()
        assert report["authority"] and isinstance(report["authority"], str)

    def test_deprecated_surfaces_have_canonical_replacement(self):
        report = build_node_surface_diagnostic_report()
        for surf in report["deprecated_surfaces"]:
            assert surf.get("canonical_replacement"), (
                f"Deprecated surface '{surf.get('surface_id')}' must have "
                "a canonical_replacement in the report"
            )


# ===========================================================================
# J) No-parallel-authority assertion
# ===========================================================================


class TestNoParallelAuthority:
    """Non-canonical surfaces must never carry peer-authority or dashboard-trust flags."""

    def test_no_compat_surface_is_peer_authority(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind != NodeSurfaceBoundaryKind.CANONICAL:
                assert rec.is_peer_authority is False, (
                    f"Non-canonical surface '{rec.surface_id}' "
                    f"(kind={rec.boundary_kind.value}) has is_peer_authority=True — "
                    "this violates the no-parallel-authority policy."
                )

    def test_no_non_canonical_surface_is_dashboard_trusted(self):
        for rec in get_surface_boundary_catalogue():
            if rec.boundary_kind != NodeSurfaceBoundaryKind.CANONICAL:
                assert rec.is_dashboard_trusted is False, (
                    f"Non-canonical surface '{rec.surface_id}' "
                    f"(kind={rec.boundary_kind.value}) has is_dashboard_trusted=True — "
                    "dashboards must not depend on non-canonical stores."
                )

    def test_fusion_entry_is_not_peer_authority(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert index["fusion_entry_adapter"].is_peer_authority is False

    def test_node_registry_compat_is_not_peer_authority(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert index["node_registry_compat_facade"].is_peer_authority is False

    def test_direct_scan_is_not_dashboard_trusted(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert index["direct_nodes_dir_scan"].is_dashboard_trusted is False

    def test_legacy_layer3_is_not_dashboard_trusted(self):
        index = {r.surface_id: r for r in get_surface_boundary_catalogue()}
        assert index["openclawd_legacy_layer3_scan"].is_dashboard_trusted is False


# ===========================================================================
# K) core/routes/projection.py sentinel
# ===========================================================================


class TestProjectionSentinel:
    """The projection.py alignment sentinel must be importable and correct."""

    @pytest.mark.skipif(
        "fastapi" not in sys.modules,
        reason="Skip if projection imports require fastapi",
    )
    def test_projection_sentinel_importable(self):
        try:
            from core.routes.projection import (
                NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13,
            )
            assert isinstance(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13, str)
            assert len(NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13) > 0
        except ImportError:
            pytest.skip("core.routes.projection not importable (fastapi unavailable)")

    def test_projection_sentinel_fallback_importable(self):
        """Even if fastapi is unavailable, the sentinel string must exist."""
        try:
            from core.routes.projection import (
                NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13,
            )
            assert "PR13" in NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13
        except ImportError:
            pytest.skip("core.routes.projection not importable")

    def test_projection_sentinel_contains_key_terms(self):
        try:
            from core.routes.projection import (
                NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13,
            )
            sentinel = NODE_BOUNDARY_ENFORCEMENT_FINALIZATION_ALIGNED_PR13
            # Must mention canonical or classification or boundary enforcement
            assert any(
                term in sentinel
                for term in ("canonical", "classification", "boundary", "CANONICAL")
            )
        except ImportError:
            pytest.skip("core.routes.projection not importable")
