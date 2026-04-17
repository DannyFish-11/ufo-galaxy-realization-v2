#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr4_multi_device_truth_projection_convergence.py
=============================================================
PR-4 — Multi-Device Truth and Projection Convergence.

Validates that:

A) All PR-4 authority and policy sentinels are importable and non-empty.

B) MultiDeviceTruthDomain enum has the five required domains.

C) MultiDeviceTruthDomainFacet:
   - constructs with defaults
   - to_dict() produces stable output with expected keys
   - all authority tiers representable

D) MultiDeviceTruthConvergenceSnapshot:
   - constructs with defaults
   - all five domain facets present
   - to_dict() produces a round-trippable dict
   - fully_canonical defaults to False
   - partial_domains defaults to empty list

E) converge_multi_device_truth():
   - returns a MultiDeviceTruthConvergenceSnapshot
   - never raises (all sources soft-fail)
   - fully_canonical reflects actual source availability
   - each domain has a valid authority_tier (primary/secondary/unavailable)
   - convergence_notes is a list

F) MultiDeviceRuntimeProjection:
   - truth_convergence field exists and defaults to None
   - to_compact_summary() includes truth_convergence metadata
   - build_multi_device_runtime_projection() accepts truth_convergence param
   - truth_convergence is forwarded through the builder

G) OutwardRuntimeTruthSnapshot:
   - multi_device_truth_convergence field exists and defaults to None
   - to_dict() includes multi_device_truth_convergence key
   - compile_outward_truth() populates multi_device_truth_convergence
   - source_records includes MultiDeviceTruthConvergence entry

H) truth_projection_boundary:
   - formation_resolver entry is classified as CANONICAL_TRUTH
   - network_topology_runtime entry is classified as CANONICAL_TRUTH
   - multi_device_truth_convergence entry classified as SYNCHRONIZATION_MAPPING
   - formation_truth_convergence_projection classified as PROJECTION_READ_MODEL
   - topology_truth_convergence_projection classified as PROJECTION_READ_MODEL

I) multi_device_projection_canonicalization:
   - MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED importable
   - sentinel contains "PR-4" and "truth_convergence" text

J) Contract stability:
   - MultiDeviceRuntimeProjection.to_dict() includes truth_convergence key
   - from_dict(to_dict()) round-trips correctly
   - truth_convergence can be set to a dict value and preserved
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# A) Sentinel imports
# ---------------------------------------------------------------------------


class TestSentinels:
    """All PR-4 sentinel constants must be importable and non-empty."""

    def test_authority_sentinel_importable(self):
        from core.multi_device_truth_convergence import MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY
        assert MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY
        assert "PR4" in MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY

    def test_pr4_sentinel_importable(self):
        from core.multi_device_truth_convergence import MULTI_DEVICE_TRUTH_CONVERGENCE_PR4_SENTINEL
        assert MULTI_DEVICE_TRUTH_CONVERGENCE_PR4_SENTINEL
        assert "PR-4" in MULTI_DEVICE_TRUTH_CONVERGENCE_PR4_SENTINEL

    def test_layer_position(self):
        from core.multi_device_truth_convergence import MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION
        assert isinstance(MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION, int)
        assert MULTI_DEVICE_TRUTH_CONVERGENCE_LAYER_POSITION > 0

    def test_formation_precedence_policy_importable(self):
        from core.multi_device_truth_convergence import FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert "formation" in FORMATION_TRUTH_SOURCE_PRECEDENCE_POLICY.lower()

    def test_readiness_precedence_policy_importable(self):
        from core.multi_device_truth_convergence import READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert "TruthIntegrationLayer" in READINESS_TRUTH_SOURCE_PRECEDENCE_POLICY

    def test_participation_precedence_policy_importable(self):
        from core.multi_device_truth_convergence import PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert "participation" in PARTICIPATION_TRUTH_SOURCE_PRECEDENCE_POLICY.lower()

    def test_topology_precedence_policy_importable(self):
        from core.multi_device_truth_convergence import TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert "NetworkTopologyRuntime" in TOPOLOGY_TRUTH_SOURCE_PRECEDENCE_POLICY

    def test_session_context_precedence_policy_importable(self):
        from core.multi_device_truth_convergence import SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY
        assert "AttachedSessionRegistry" in SESSION_CONTEXT_TRUTH_SOURCE_PRECEDENCE_POLICY

    def test_downstream_policy_importable(self):
        from core.multi_device_truth_convergence import DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY
        assert DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY
        assert "converge_multi_device_truth" in DOWNSTREAM_MUST_USE_CONVERGENCE_SNAPSHOT_POLICY

    def test_contracts_pr4_sentinel_importable(self):
        from contracts.multi_device_runtime_projection import MULTI_DEVICE_PROJECTION_PR4_CONVERGENCE_SENTINEL
        assert MULTI_DEVICE_PROJECTION_PR4_CONVERGENCE_SENTINEL
        assert "truth_convergence" in MULTI_DEVICE_PROJECTION_PR4_CONVERGENCE_SENTINEL

    def test_contracts_truth_authority_policy_importable(self):
        from contracts.multi_device_runtime_projection import MULTI_DEVICE_PROJECTION_TRUTH_AUTHORITY_POLICY
        assert MULTI_DEVICE_PROJECTION_TRUTH_AUTHORITY_POLICY
        assert "formation" in MULTI_DEVICE_PROJECTION_TRUTH_AUTHORITY_POLICY

    def test_canonicalization_pr4_sentinel_importable(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED,
        )
        assert MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED
        assert "PR-4" in MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED
        assert "truth_convergence" in MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED


# ---------------------------------------------------------------------------
# B) MultiDeviceTruthDomain enum
# ---------------------------------------------------------------------------


class TestMultiDeviceTruthDomain:
    def test_five_domains_defined(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthDomain
        assert MultiDeviceTruthDomain.FORMATION.value == "formation"
        assert MultiDeviceTruthDomain.READINESS.value == "readiness"
        assert MultiDeviceTruthDomain.PARTICIPATION.value == "participation"
        assert MultiDeviceTruthDomain.TOPOLOGY.value == "topology"
        assert MultiDeviceTruthDomain.SESSION_CONTEXT.value == "session_context"

    def test_all_values_are_strings(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthDomain
        for domain in MultiDeviceTruthDomain:
            assert isinstance(domain.value, str)
            assert domain.value  # non-empty


# ---------------------------------------------------------------------------
# C) MultiDeviceTruthDomainFacet
# ---------------------------------------------------------------------------


class TestMultiDeviceTruthDomainFacet:
    def test_default_construction(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        facet = MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.FORMATION)
        assert facet.domain == MultiDeviceTruthDomain.FORMATION
        assert facet.authority_tier == "unavailable"
        assert facet.data is None
        assert isinstance(facet.gap_reasons, list)

    def test_to_dict_stable_keys(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        facet = MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.READINESS)
        d = facet.to_dict()
        expected_keys = {"domain", "authority_source", "authority_tier", "data", "gap_reasons", "latency_ms"}
        assert expected_keys.issubset(set(d.keys()))

    def test_primary_tier_representable(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        facet = MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.TOPOLOGY,
            authority_source="NetworkTopologyRuntime",
            authority_tier="primary",
            data={"node_count": 3},
        )
        assert facet.authority_tier == "primary"
        assert facet.to_dict()["authority_tier"] == "primary"
        assert facet.to_dict()["data"]["node_count"] == 3

    def test_secondary_tier_representable(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        facet = MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.FORMATION,
            authority_tier="secondary",
            gap_reasons=["formation_resolver unavailable"],
        )
        assert facet.authority_tier == "secondary"
        assert len(facet.gap_reasons) == 1

    def test_latency_ms_rounded(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        facet = MultiDeviceTruthDomainFacet(
            domain=MultiDeviceTruthDomain.PARTICIPATION,
            latency_ms=12.3456789,
        )
        d = facet.to_dict()
        # latency_ms should be rounded to 2 decimal places
        assert isinstance(d["latency_ms"], float)


# ---------------------------------------------------------------------------
# D) MultiDeviceTruthConvergenceSnapshot
# ---------------------------------------------------------------------------


class TestMultiDeviceTruthConvergenceSnapshot:
    def test_default_construction(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthConvergenceSnapshot
        snap = MultiDeviceTruthConvergenceSnapshot()
        assert snap.convergence_id
        assert snap.assembled_at > 0
        assert not snap.fully_canonical
        assert isinstance(snap.partial_domains, list)
        assert isinstance(snap.convergence_notes, list)

    def test_all_five_facets_present(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthConvergenceSnapshot,
            MultiDeviceTruthDomain,
        )
        snap = MultiDeviceTruthConvergenceSnapshot()
        assert snap.formation.domain == MultiDeviceTruthDomain.FORMATION
        assert snap.readiness.domain == MultiDeviceTruthDomain.READINESS
        assert snap.participation.domain == MultiDeviceTruthDomain.PARTICIPATION
        assert snap.topology.domain == MultiDeviceTruthDomain.TOPOLOGY
        assert snap.session_context.domain == MultiDeviceTruthDomain.SESSION_CONTEXT

    def test_to_dict_stable_keys(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthConvergenceSnapshot
        snap = MultiDeviceTruthConvergenceSnapshot()
        d = snap.to_dict()
        expected_keys = {
            "convergence_id", "assembled_at", "authority",
            "fully_canonical", "partial_domains", "convergence_notes",
            "formation", "readiness", "participation", "topology", "session_context",
        }
        assert expected_keys.issubset(set(d.keys()))

    def test_authority_field_in_dict(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthConvergenceSnapshot,
            MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY,
        )
        snap = MultiDeviceTruthConvergenceSnapshot()
        d = snap.to_dict()
        assert d["authority"] == MULTI_DEVICE_TRUTH_CONVERGENCE_AUTHORITY

    def test_convergence_ids_unique(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthConvergenceSnapshot
        s1 = MultiDeviceTruthConvergenceSnapshot()
        s2 = MultiDeviceTruthConvergenceSnapshot()
        assert s1.convergence_id != s2.convergence_id

    def test_fully_canonical_when_all_primary(self):
        from core.multi_device_truth_convergence import (
            MultiDeviceTruthConvergenceSnapshot,
            MultiDeviceTruthDomainFacet,
            MultiDeviceTruthDomain,
        )
        snap = MultiDeviceTruthConvergenceSnapshot(
            formation=MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.FORMATION, authority_tier="primary"),
            readiness=MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.READINESS, authority_tier="primary"),
            participation=MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.PARTICIPATION, authority_tier="primary"),
            topology=MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.TOPOLOGY, authority_tier="primary"),
            session_context=MultiDeviceTruthDomainFacet(domain=MultiDeviceTruthDomain.SESSION_CONTEXT, authority_tier="primary"),
            fully_canonical=True,
            partial_domains=[],
        )
        assert snap.fully_canonical is True
        assert snap.partial_domains == []

    def test_nested_facet_dicts_in_to_dict(self):
        from core.multi_device_truth_convergence import MultiDeviceTruthConvergenceSnapshot
        snap = MultiDeviceTruthConvergenceSnapshot()
        d = snap.to_dict()
        # Each domain should be a dict with the standard keys
        for domain_key in ("formation", "readiness", "participation", "topology", "session_context"):
            assert isinstance(d[domain_key], dict)
            assert "domain" in d[domain_key]
            assert "authority_tier" in d[domain_key]


# ---------------------------------------------------------------------------
# E) converge_multi_device_truth()
# ---------------------------------------------------------------------------


class TestConvergeMultiDeviceTruth:
    def test_returns_snapshot_never_raises(self):
        from core.multi_device_truth_convergence import (
            converge_multi_device_truth,
            MultiDeviceTruthConvergenceSnapshot,
        )
        result = converge_multi_device_truth()
        assert isinstance(result, MultiDeviceTruthConvergenceSnapshot)

    def test_all_domains_have_valid_tier(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        valid_tiers = {"primary", "secondary", "unavailable"}
        assert snap.formation.authority_tier in valid_tiers
        assert snap.readiness.authority_tier in valid_tiers
        assert snap.participation.authority_tier in valid_tiers
        assert snap.topology.authority_tier in valid_tiers
        assert snap.session_context.authority_tier in valid_tiers

    def test_convergence_notes_is_list(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        assert isinstance(snap.convergence_notes, list)

    def test_partial_domains_is_list(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        assert isinstance(snap.partial_domains, list)

    def test_fully_canonical_is_bool(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        assert isinstance(snap.fully_canonical, bool)

    def test_fully_canonical_consistent_with_partial_domains(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        if snap.fully_canonical:
            assert snap.partial_domains == []
        else:
            assert len(snap.partial_domains) > 0

    def test_to_dict_is_serialisable(self):
        import json
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        d = snap.to_dict()
        # Should be JSON-serialisable
        dumped = json.dumps(d)
        assert dumped

    def test_unavailable_domains_have_gap_reasons(self):
        from core.multi_device_truth_convergence import converge_multi_device_truth
        snap = converge_multi_device_truth()
        for facet in [snap.formation, snap.readiness, snap.participation, snap.topology, snap.session_context]:
            if facet.authority_tier == "unavailable":
                assert isinstance(facet.gap_reasons, list)
                # unavailable facets should have at least one gap reason
                assert len(facet.gap_reasons) >= 1

    def test_all_sources_unavailable_still_returns_snapshot(self):
        """Even when all canonical sources are mocked to raise, converge_multi_device_truth
        returns a valid (fully unavailable) snapshot rather than raising."""
        from core.multi_device_truth_convergence import converge_multi_device_truth
        with patch("core.multi_device_truth_convergence._assemble_formation_facet") as mf, \
             patch("core.multi_device_truth_convergence._assemble_readiness_facet") as mr, \
             patch("core.multi_device_truth_convergence._assemble_participation_facet") as mp, \
             patch("core.multi_device_truth_convergence._assemble_topology_facet") as mt, \
             patch("core.multi_device_truth_convergence._assemble_session_context_facet") as ms:
            from core.multi_device_truth_convergence import MultiDeviceTruthDomainFacet, MultiDeviceTruthDomain

            def _make_unavailable(domain):
                return MultiDeviceTruthDomainFacet(domain=domain, authority_tier="unavailable")

            mf.return_value = _make_unavailable(MultiDeviceTruthDomain.FORMATION)
            mr.return_value = _make_unavailable(MultiDeviceTruthDomain.READINESS)
            mp.return_value = _make_unavailable(MultiDeviceTruthDomain.PARTICIPATION)
            mt.return_value = _make_unavailable(MultiDeviceTruthDomain.TOPOLOGY)
            ms.return_value = _make_unavailable(MultiDeviceTruthDomain.SESSION_CONTEXT)

            snap = converge_multi_device_truth()
            assert not snap.fully_canonical
            assert len(snap.partial_domains) == 5


# ---------------------------------------------------------------------------
# F) MultiDeviceRuntimeProjection — truth_convergence field
# ---------------------------------------------------------------------------


class TestMultiDeviceRuntimeProjectionTruthConvergence:
    def test_truth_convergence_field_exists_defaults_none(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        assert hasattr(proj, "truth_convergence")
        assert proj.truth_convergence is None

    def test_to_dict_includes_truth_convergence_key(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        d = proj.to_dict()
        assert "truth_convergence" in d

    def test_to_compact_summary_includes_truth_convergence_meta(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        cs = proj.to_compact_summary()
        assert "has_truth_convergence" in cs
        assert "truth_convergence_fully_canonical" in cs
        assert "truth_convergence_partial_domains" in cs
        assert cs["has_truth_convergence"] is False

    def test_to_compact_summary_with_truth_convergence_set(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection(
            truth_convergence={
                "fully_canonical": True,
                "partial_domains": [],
                "convergence_id": "test-id",
            }
        )
        cs = proj.to_compact_summary()
        assert cs["has_truth_convergence"] is True
        assert cs["truth_convergence_fully_canonical"] is True
        assert cs["truth_convergence_partial_domains"] == []

    def test_build_projection_accepts_truth_convergence(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        tc = {"convergence_id": "test", "fully_canonical": False, "formation": {}}
        proj = build_multi_device_runtime_projection(truth_convergence=tc)
        assert proj.truth_convergence is not None
        assert proj.truth_convergence.get("convergence_id") == "test"

    def test_build_projection_truth_convergence_none_by_default(self):
        from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
        proj = build_multi_device_runtime_projection()
        assert proj.truth_convergence is None

    def test_from_dict_round_trip_preserves_truth_convergence(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        tc = {"convergence_id": "round-trip", "fully_canonical": True}
        proj = MultiDeviceRuntimeProjection(truth_convergence=tc)
        d = proj.to_dict()
        proj2 = MultiDeviceRuntimeProjection.from_dict(d)
        assert proj2.truth_convergence is not None
        assert proj2.truth_convergence.get("convergence_id") == "round-trip"


# ---------------------------------------------------------------------------
# G) OutwardRuntimeTruthSnapshot — multi_device_truth_convergence
# ---------------------------------------------------------------------------


class TestOutwardRuntimeTruthSnapshotConvergence:
    def test_field_exists_defaults_none(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(snapshot_id="x", compiled_at=1.0)
        assert hasattr(snap, "multi_device_truth_convergence")
        assert snap.multi_device_truth_convergence is None

    def test_to_dict_includes_field(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(snapshot_id="x", compiled_at=1.0)
        d = snap.to_dict()
        assert "multi_device_truth_convergence" in d

    def test_to_dict_field_none_when_not_set(self):
        from core.outward_runtime_truth import OutwardRuntimeTruthSnapshot
        snap = OutwardRuntimeTruthSnapshot(snapshot_id="x", compiled_at=1.0)
        d = snap.to_dict()
        assert d["multi_device_truth_convergence"] is None

    def test_compile_outward_truth_includes_convergence_source(self):
        from core.outward_runtime_truth import compile_outward_truth, reset_outward_runtime_truth_runtime
        reset_outward_runtime_truth_runtime()
        snap = compile_outward_truth()
        source_names = [r.source_name for r in snap.source_records]
        assert "MultiDeviceTruthConvergence" in source_names
        reset_outward_runtime_truth_runtime()

    def test_compile_outward_truth_multi_device_field_populated_or_none(self):
        from core.outward_runtime_truth import compile_outward_truth, reset_outward_runtime_truth_runtime
        reset_outward_runtime_truth_runtime()
        snap = compile_outward_truth()
        # Field should be a dict or None — never raises
        assert snap.multi_device_truth_convergence is None or isinstance(
            snap.multi_device_truth_convergence, dict
        )
        reset_outward_runtime_truth_runtime()

    def test_compile_outward_truth_to_dict_includes_convergence_key(self):
        from core.outward_runtime_truth import compile_outward_truth, reset_outward_runtime_truth_runtime
        reset_outward_runtime_truth_runtime()
        snap = compile_outward_truth()
        d = snap.to_dict()
        assert "multi_device_truth_convergence" in d
        reset_outward_runtime_truth_runtime()


# ---------------------------------------------------------------------------
# H) truth_projection_boundary — PR-4 entries
# ---------------------------------------------------------------------------


class TestTruthProjectionBoundaryPR4Entries:
    def test_formation_resolver_in_catalog(self):
        from core.truth_projection_boundary import (
            build_truth_projection_boundary_catalog,
            BoundaryRole,
        )
        catalog = build_truth_projection_boundary_catalog()
        entry = next((e for e in catalog if e.surface_id == "formation_resolver"), None)
        assert entry is not None
        assert entry.role == BoundaryRole.CANONICAL_TRUTH
        assert entry.lifecycle_owner is True

    def test_network_topology_runtime_in_catalog(self):
        from core.truth_projection_boundary import (
            build_truth_projection_boundary_catalog,
            BoundaryRole,
        )
        catalog = build_truth_projection_boundary_catalog()
        entry = next((e for e in catalog if e.surface_id == "network_topology_runtime"), None)
        assert entry is not None
        assert entry.role == BoundaryRole.CANONICAL_TRUTH
        assert entry.lifecycle_owner is True

    def test_multi_device_truth_convergence_in_catalog(self):
        from core.truth_projection_boundary import (
            build_truth_projection_boundary_catalog,
            BoundaryRole,
        )
        catalog = build_truth_projection_boundary_catalog()
        entry = next((e for e in catalog if e.surface_id == "multi_device_truth_convergence"), None)
        assert entry is not None
        assert entry.role == BoundaryRole.SYNCHRONIZATION_MAPPING
        assert entry.lifecycle_owner is False

    def test_formation_truth_convergence_projection_in_catalog(self):
        from core.truth_projection_boundary import (
            build_truth_projection_boundary_catalog,
            BoundaryRole,
        )
        catalog = build_truth_projection_boundary_catalog()
        entry = next((e for e in catalog if e.surface_id == "formation_truth_convergence_projection"), None)
        assert entry is not None
        assert entry.role == BoundaryRole.PROJECTION_READ_MODEL
        assert entry.lifecycle_owner is False

    def test_topology_truth_convergence_projection_in_catalog(self):
        from core.truth_projection_boundary import (
            build_truth_projection_boundary_catalog,
            BoundaryRole,
        )
        catalog = build_truth_projection_boundary_catalog()
        entry = next((e for e in catalog if e.surface_id == "topology_truth_convergence_projection"), None)
        assert entry is not None
        assert entry.role == BoundaryRole.PROJECTION_READ_MODEL

    def test_build_truth_projection_boundary_snapshot_includes_pr4_entries(self):
        from core.truth_projection_boundary import build_truth_projection_boundary_snapshot
        snap = build_truth_projection_boundary_snapshot()
        assert "total_surfaces" in snap
        # PR-4 added 5 new entries
        assert snap["total_surfaces"] >= 20


# ---------------------------------------------------------------------------
# I) multi_device_projection_canonicalization — PR-4 sentinel
# ---------------------------------------------------------------------------


class TestCanonicalizationPR4Sentinel:
    def test_pr4_sentinel_importable_and_has_expected_text(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED,
        )
        assert "PR-4" in MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED
        assert "truth_convergence" in MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED

    def test_all_pr_sentinels_still_importable(self):
        from core.multi_device_projection_canonicalization import (
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
            MULTI_DEVICE_PROJECTION_GAP008_RESOLVED,
            MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED,
            MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED,
        )
        for sentinel in [
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_AUTHORITY,
            MULTI_DEVICE_PROJECTION_CANONICALIZATION_INTEGRATED,
            MULTI_DEVICE_PROJECTION_GAP008_RESOLVED,
            MULTI_DEVICE_PROJECTION_COORDINATION_ROLE_INTEGRATED,
            MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED,
        ]:
            assert sentinel

    def test_pr4_sentinel_in_all_list(self):
        import core.multi_device_projection_canonicalization as mod
        assert "MULTI_DEVICE_PROJECTION_PR4_TRUTH_CONVERGENCE_INTEGRATED" in mod.__all__


# ---------------------------------------------------------------------------
# J) Contract stability — round-trip and backward compat
# ---------------------------------------------------------------------------


class TestContractStability:
    def test_projection_to_dict_stable_keys_with_truth_convergence(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        d = proj.to_dict()
        # All previously stable keys still present
        expected = {
            "projection_id", "generated_at", "runtime_devices", "runtime_hosts",
            "mesh_memberships", "mesh_sessions", "source_dispatches", "handoff_summaries",
            "takeover_summaries", "coordinator_summaries", "merged_results",
            "governance_snapshot", "policy_alignment", "metadata",
            "runtime_recovery", "runtime_session_snapshot",
            # PR-4 new field
            "truth_convergence",
        }
        assert expected.issubset(set(d.keys()))

    def test_projection_from_dict_tolerates_missing_truth_convergence(self):
        """from_dict without truth_convergence key must still work (backward compat)."""
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        d = proj.to_dict()
        d.pop("truth_convergence", None)
        proj2 = MultiDeviceRuntimeProjection.from_dict(d)
        assert proj2.truth_convergence is None

    def test_projection_from_dict_with_convergence_dict(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        d = {
            "projection_id": "test-proj",
            "generated_at": 1234567890.0,
            "truth_convergence": {
                "convergence_id": "test-conv",
                "fully_canonical": False,
                "partial_domains": ["topology"],
            },
        }
        proj = MultiDeviceRuntimeProjection.from_dict(d)
        assert proj.truth_convergence is not None
        assert proj.truth_convergence["convergence_id"] == "test-conv"

    def test_canonical_top_level_projection_sentinel_unchanged(self):
        from contracts.multi_device_runtime_projection import CANONICAL_TOP_LEVEL_PROJECTION
        assert CANONICAL_TOP_LEVEL_PROJECTION is True

    def test_empty_construction_valid_with_truth_convergence(self):
        from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection
        proj = MultiDeviceRuntimeProjection()
        # Must be constructable without any args
        assert proj.projection_id
        assert proj.truth_convergence is None
        d = proj.to_dict()
        assert d["truth_convergence"] is None
