"""tests/test_pr6_authority_boundary_classification.py
======================================================
PR-6 (UGCP convergence plan, realization-v2 side): Authority boundary
classification — test suite.

Tests cover:
- Module authority sentinels and PR-6 sentinel
- Policy sentinels are non-empty strings and mention expected keywords
- AuthorityRole enum completeness (all expected roles present)
- AuthoritySurface dataclass structure and to_dict()
- AuthorityMatrixSummary dataclass structure and to_dict()
- get_authority_matrix() returns a non-empty list of AuthoritySurface entries
- classify_surface() lookup by surface_id (found and not-found cases)
- get_surfaces_by_role() filters correctly
- get_non_authoritative_surfaces() returns no authoritative entries
- get_transitional_surfaces() returns only transitional entries
- build_authority_matrix_summary() aggregate builder
- Specific surface classifications (UDM, UCM, NodeFabricRegistry, etc.)
- Projection alignment sentinel
- Authority invariants (compat facades are non-authoritative, etc.)
"""

from __future__ import annotations

import pytest

from core.authority_boundary_classification import (
    AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY,
    AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL,
    ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY,
    CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY,
    COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY,
    TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY,
    AuthorityMatrixSummary,
    AuthorityRole,
    AuthoritySurface,
    build_authority_matrix_summary,
    classify_surface,
    get_authority_matrix,
    get_non_authoritative_surfaces,
    get_surfaces_by_role,
    get_transitional_surfaces,
)


# ---------------------------------------------------------------------------
# Authority and policy sentinel tests
# ---------------------------------------------------------------------------


def test_authority_sentinel_format():
    assert AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY.startswith(
        "AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY::"
    )
    assert "core.authority_boundary_classification" in AUTHORITY_BOUNDARY_CLASSIFICATION_IS_AUTHORITY


def test_pr6_sentinel_format():
    assert AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL.startswith(
        "AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL::"
    )
    assert "PR6" in AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL
    assert "authority-boundary-classification-v1" in AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL
    assert "core.authority_boundary_classification" in AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL


def test_pr6_sentinel_mentions_authority_matrix():
    assert "authority matrix" in AUTHORITY_BOUNDARY_CLASSIFICATION_PR6_SENTINEL.lower()


def test_policy_sentinels_are_non_empty_strings():
    for sentinel in [
        COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY,
        CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY,
        ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY,
        TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY,
    ]:
        assert isinstance(sentinel, str) and len(sentinel) > 0


def test_compat_policy_mentions_non_authoritative():
    assert "non-authoritative" in COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY.lower()


def test_compat_policy_mentions_compat_facades():
    lower = COMPAT_SURFACES_ARE_NON_AUTHORITATIVE_POLICY.lower()
    assert "compat" in lower or "compatibility" in lower


def test_cache_policy_mentions_truth():
    assert "truth" in CACHE_INDEX_SURFACES_MUST_NOT_WRITE_TRUTH_POLICY.lower()


def test_adapter_policy_mentions_routing():
    lower = ADAPTER_SURFACES_ARE_ROUTING_ONLY_POLICY.lower()
    assert "routing" in lower or "adapter" in lower


def test_transitional_policy_mentions_canonical():
    assert "canonical" in TRANSITIONAL_SURFACES_MUST_NOT_BE_EXTENDED_POLICY.lower()


# ---------------------------------------------------------------------------
# AuthorityRole enum completeness
# ---------------------------------------------------------------------------


def test_authority_role_has_ssot_write():
    assert AuthorityRole.ssot_write.value == "ssot_write"


def test_authority_role_has_canonical_registry():
    assert AuthorityRole.canonical_registry.value == "canonical_registry"


def test_authority_role_has_truth_compilation():
    assert AuthorityRole.truth_compilation.value == "truth_compilation"


def test_authority_role_has_projection():
    assert AuthorityRole.projection.value == "projection"


def test_authority_role_has_cache_index():
    assert AuthorityRole.cache_index.value == "cache_index"


def test_authority_role_has_compat_facade():
    assert AuthorityRole.compat_facade.value == "compat_facade"


def test_authority_role_has_adapter_routing():
    assert AuthorityRole.adapter_routing.value == "adapter_routing"


def test_authority_role_has_transitional():
    assert AuthorityRole.transitional.value == "transitional"


def test_authority_role_all_expected_roles_present():
    expected = {
        "ssot_write",
        "canonical_registry",
        "truth_compilation",
        "projection",
        "cache_index",
        "compat_facade",
        "adapter_routing",
        "transitional",
    }
    actual = {role.value for role in AuthorityRole}
    assert expected.issubset(actual), f"Missing roles: {expected - actual}"


# ---------------------------------------------------------------------------
# AuthoritySurface dataclass
# ---------------------------------------------------------------------------


def test_authority_surface_to_dict_keys():
    surface = AuthoritySurface(
        surface_id="test_surface",
        module_path="core.test.TestSurface",
        surface_name="Test Surface",
        role=AuthorityRole.projection,
        is_authoritative=False,
        notes="Test notes.",
    )
    d = surface.to_dict()
    assert "surface_id" in d
    assert "module_path" in d
    assert "surface_name" in d
    assert "role" in d
    assert "is_authoritative" in d
    assert "is_transitional" in d
    assert "notes" in d
    assert "canonical_replacement" in d


def test_authority_surface_to_dict_values():
    surface = AuthoritySurface(
        surface_id="test_id",
        module_path="core.test.Module",
        surface_name="Test",
        role=AuthorityRole.cache_index,
        is_authoritative=False,
        notes="A cache.",
        is_transitional=True,
        canonical_replacement="core.canonical.Source",
    )
    d = surface.to_dict()
    assert d["surface_id"] == "test_id"
    assert d["role"] == "cache_index"
    assert d["is_authoritative"] is False
    assert d["is_transitional"] is True
    assert d["canonical_replacement"] == "core.canonical.Source"


def test_authority_surface_defaults():
    surface = AuthoritySurface(
        surface_id="s",
        module_path="m",
        surface_name="n",
        role=AuthorityRole.adapter_routing,
        is_authoritative=False,
        notes="notes",
    )
    assert surface.is_transitional is False
    assert surface.canonical_replacement is None


# ---------------------------------------------------------------------------
# AuthorityMatrixSummary dataclass
# ---------------------------------------------------------------------------


def test_authority_matrix_summary_to_dict_keys():
    summary = build_authority_matrix_summary()
    d = summary.to_dict()
    expected_keys = {
        "total_surfaces",
        "authoritative_count",
        "non_authoritative_count",
        "transitional_count",
        "by_role",
        "compat_facade_surfaces",
        "transitional_surface_ids",
        "generated_at",
    }
    assert expected_keys.issubset(d.keys())


# ---------------------------------------------------------------------------
# get_authority_matrix()
# ---------------------------------------------------------------------------


def test_get_authority_matrix_returns_list():
    matrix = get_authority_matrix()
    assert isinstance(matrix, list)
    assert len(matrix) > 0


def test_get_authority_matrix_all_entries_are_authority_surface():
    matrix = get_authority_matrix()
    for entry in matrix:
        assert isinstance(entry, AuthoritySurface)


def test_get_authority_matrix_all_entries_have_surface_id():
    matrix = get_authority_matrix()
    for entry in matrix:
        assert isinstance(entry.surface_id, str) and len(entry.surface_id) > 0


def test_get_authority_matrix_surface_ids_are_unique():
    matrix = get_authority_matrix()
    ids = [e.surface_id for e in matrix]
    assert len(ids) == len(set(ids)), "Duplicate surface_id values found in authority matrix"


def test_get_authority_matrix_returns_copy():
    """get_authority_matrix() should not return the internal list directly."""
    m1 = get_authority_matrix()
    m2 = get_authority_matrix()
    # Each call should return a distinct list object (a copy, not the same reference)
    assert m1 is not m2


# ---------------------------------------------------------------------------
# classify_surface()
# ---------------------------------------------------------------------------


def test_classify_surface_finds_udm():
    result = classify_surface("udm")
    assert result is not None
    assert result.surface_id == "udm"
    assert result.role == AuthorityRole.ssot_write
    assert result.is_authoritative is True


def test_classify_surface_finds_node_fabric_registry():
    result = classify_surface("node_fabric_registry")
    assert result is not None
    assert result.role == AuthorityRole.canonical_registry
    assert result.is_authoritative is True


def test_classify_surface_finds_compat_facade():
    result = classify_surface("node_registry_compat_facade")
    assert result is not None
    assert result.role == AuthorityRole.compat_facade
    assert result.is_authoritative is False


def test_classify_surface_returns_none_for_unknown():
    result = classify_surface("this_surface_does_not_exist_in_matrix")
    assert result is None


def test_classify_surface_returns_none_for_empty_string():
    result = classify_surface("")
    assert result is None


# ---------------------------------------------------------------------------
# get_surfaces_by_role()
# ---------------------------------------------------------------------------


def test_get_surfaces_by_role_ssot_write_not_empty():
    # The authority matrix must have at least UDM and UCM as ssot_write surfaces.
    surfaces = get_surfaces_by_role(AuthorityRole.ssot_write)
    ssot_ids = {s.surface_id for s in surfaces}
    assert "udm" in ssot_ids, "UDM must be an ssot_write surface"
    assert "ucm" in ssot_ids, "UCM must be an ssot_write surface"


def test_get_surfaces_by_role_ssot_write_all_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.ssot_write)
    for s in surfaces:
        assert s.is_authoritative is True, (
            f"ssot_write surface {s.surface_id!r} must be authoritative"
        )


def test_get_surfaces_by_role_compat_facade_not_empty():
    surfaces = get_surfaces_by_role(AuthorityRole.compat_facade)
    assert len(surfaces) >= 1


def test_get_surfaces_by_role_compat_facade_none_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.compat_facade)
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"compat_facade surface {s.surface_id!r} must not be authoritative"
        )


def test_get_surfaces_by_role_projection_none_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.projection)
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"projection surface {s.surface_id!r} must not be authoritative"
        )


def test_get_surfaces_by_role_cache_index_none_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.cache_index)
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"cache_index surface {s.surface_id!r} must not be authoritative"
        )


def test_get_surfaces_by_role_adapter_routing_none_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.adapter_routing)
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"adapter_routing surface {s.surface_id!r} must not be authoritative"
        )


def test_get_surfaces_by_role_transitional_none_authoritative():
    surfaces = get_surfaces_by_role(AuthorityRole.transitional)
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"transitional surface {s.surface_id!r} must not be authoritative"
        )


# ---------------------------------------------------------------------------
# get_non_authoritative_surfaces()
# ---------------------------------------------------------------------------


def test_get_non_authoritative_surfaces_not_empty():
    surfaces = get_non_authoritative_surfaces()
    assert len(surfaces) > 0


def test_get_non_authoritative_surfaces_none_is_authoritative():
    surfaces = get_non_authoritative_surfaces()
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"get_non_authoritative_surfaces() returned authoritative surface: {s.surface_id!r}"
        )


def test_get_non_authoritative_surfaces_complement_is_authoritative():
    """All authoritative surfaces should NOT appear in non_authoritative list."""
    matrix = get_authority_matrix()
    non_auth_ids = {s.surface_id for s in get_non_authoritative_surfaces()}
    auth_ids = {s.surface_id for s in matrix if s.is_authoritative}
    overlap = auth_ids & non_auth_ids
    assert not overlap, f"Surfaces appear in both authoritative and non-authoritative: {overlap}"


# ---------------------------------------------------------------------------
# get_transitional_surfaces()
# ---------------------------------------------------------------------------


def test_get_transitional_surfaces_not_empty():
    surfaces = get_transitional_surfaces()
    assert len(surfaces) > 0


def test_get_transitional_surfaces_all_marked_transitional():
    surfaces = get_transitional_surfaces()
    for s in surfaces:
        assert s.is_transitional is True, (
            f"get_transitional_surfaces() returned non-transitional surface: {s.surface_id!r}"
        )


def test_get_transitional_surfaces_none_is_authoritative():
    surfaces = get_transitional_surfaces()
    for s in surfaces:
        assert s.is_authoritative is False, (
            f"Transitional surface {s.surface_id!r} must not be authoritative"
        )


# ---------------------------------------------------------------------------
# build_authority_matrix_summary()
# ---------------------------------------------------------------------------


def test_build_authority_matrix_summary_returns_summary():
    summary = build_authority_matrix_summary()
    assert isinstance(summary, AuthorityMatrixSummary)


def test_build_authority_matrix_summary_total_matches_matrix():
    matrix = get_authority_matrix()
    summary = build_authority_matrix_summary()
    assert summary.total_surfaces == len(matrix)


def test_build_authority_matrix_summary_counts_add_up():
    summary = build_authority_matrix_summary()
    assert summary.authoritative_count + summary.non_authoritative_count == summary.total_surfaces


def test_build_authority_matrix_summary_transitional_count():
    transitional = get_transitional_surfaces()
    summary = build_authority_matrix_summary()
    assert summary.transitional_count == len(transitional)


def test_build_authority_matrix_summary_by_role_complete():
    summary = build_authority_matrix_summary()
    total_by_role = sum(summary.by_role.values())
    assert total_by_role == summary.total_surfaces


def test_build_authority_matrix_summary_compat_facade_ids():
    compat = get_surfaces_by_role(AuthorityRole.compat_facade)
    summary = build_authority_matrix_summary()
    compat_ids = {s.surface_id for s in compat}
    assert set(summary.compat_facade_surfaces) == compat_ids


def test_build_authority_matrix_summary_transitional_ids():
    transitional = get_transitional_surfaces()
    summary = build_authority_matrix_summary()
    t_ids = {s.surface_id for s in transitional}
    assert set(summary.transitional_surface_ids) == t_ids


def test_build_authority_matrix_summary_generated_at_is_positive():
    summary = build_authority_matrix_summary()
    assert summary.generated_at > 0


# ---------------------------------------------------------------------------
# Specific surface classification tests
# ---------------------------------------------------------------------------


def test_udm_is_ssot_write():
    udm = classify_surface("udm")
    assert udm is not None
    assert udm.role == AuthorityRole.ssot_write
    assert udm.is_authoritative is True
    assert "UnifiedDeviceManager" in udm.surface_name


def test_ucm_is_ssot_write():
    ucm = classify_surface("ucm")
    assert ucm is not None
    assert ucm.role == AuthorityRole.ssot_write
    assert ucm.is_authoritative is True
    assert "UCM" in ucm.surface_name or "UnifiedConnectionManager" in ucm.surface_name


def test_node_fabric_registry_is_canonical_registry():
    nfr = classify_surface("node_fabric_registry")
    assert nfr is not None
    assert nfr.role == AuthorityRole.canonical_registry
    assert nfr.is_authoritative is True


def test_registered_runtime_device_contract_is_canonical_registry():
    rrd = classify_surface("registered_runtime_device_contract")
    assert rrd is not None
    assert rrd.role == AuthorityRole.canonical_registry
    assert rrd.is_authoritative is True


def test_capability_registry_is_canonical_registry():
    cr = classify_surface("capability_registry")
    assert cr is not None
    assert cr.role == AuthorityRole.canonical_registry
    assert cr.is_authoritative is True


def test_projection_routes_is_projection():
    pr = classify_surface("projection_routes")
    assert pr is not None
    assert pr.role == AuthorityRole.projection
    assert pr.is_authoritative is False


def test_device_pool_manager_is_cache_index():
    dpm = classify_surface("device_pool_manager")
    assert dpm is not None
    assert dpm.role == AuthorityRole.cache_index
    assert dpm.is_authoritative is False


def test_node_registry_compat_facade_is_compat_facade():
    nrcf = classify_surface("node_registry_compat_facade")
    assert nrcf is not None
    assert nrcf.role == AuthorityRole.compat_facade
    assert nrcf.is_authoritative is False
    assert nrcf.is_transitional is True


def test_fusion_entry_adapter_is_adapter_routing():
    fea = classify_surface("fusion_entry_adapter")
    assert fea is not None
    assert fea.role == AuthorityRole.adapter_routing
    assert fea.is_authoritative is False


def test_legacy_node_registry_json_scan_is_transitional():
    t = classify_surface("legacy_node_registry_json_scan")
    assert t is not None
    assert t.role == AuthorityRole.transitional
    assert t.is_transitional is True
    assert t.is_authoritative is False


def test_registered_devices_compat_cache_is_cache_and_transitional():
    rdcc = classify_surface("registered_devices_compat_cache")
    assert rdcc is not None
    assert rdcc.role == AuthorityRole.cache_index
    assert rdcc.is_transitional is True
    assert rdcc.is_authoritative is False


# ---------------------------------------------------------------------------
# Authority invariants
# ---------------------------------------------------------------------------


def test_only_ssot_write_and_canonical_registry_are_authoritative():
    """Only ssot_write and canonical_registry roles may be authoritative."""
    authoritative_roles = {AuthorityRole.ssot_write, AuthorityRole.canonical_registry}
    matrix = get_authority_matrix()
    for entry in matrix:
        if entry.is_authoritative:
            assert entry.role in authoritative_roles, (
                f"Surface {entry.surface_id!r} has is_authoritative=True but role "
                f"{entry.role.value!r} is not ssot_write or canonical_registry"
            )


def test_projection_surfaces_are_not_authoritative():
    for surface in get_surfaces_by_role(AuthorityRole.projection):
        assert not surface.is_authoritative, (
            f"Projection surface {surface.surface_id!r} must not be authoritative"
        )


def test_cache_index_surfaces_have_canonical_replacement_or_notes():
    for surface in get_surfaces_by_role(AuthorityRole.cache_index):
        assert len(surface.notes) > 0, (
            f"Cache/index surface {surface.surface_id!r} must have governance notes"
        )


def test_compat_facade_surfaces_have_canonical_replacement():
    for surface in get_surfaces_by_role(AuthorityRole.compat_facade):
        assert surface.canonical_replacement is not None, (
            f"Compat facade surface {surface.surface_id!r} should specify canonical_replacement"
        )


def test_transitional_surfaces_have_canonical_replacement():
    for surface in get_transitional_surfaces():
        assert surface.canonical_replacement is not None, (
            f"Transitional surface {surface.surface_id!r} should specify canonical_replacement"
        )


def test_udm_notes_mention_ssot():
    udm = classify_surface("udm")
    assert udm is not None
    assert "ssot" in udm.notes.lower() or "single" in udm.notes.lower()


def test_node_registry_compat_facade_notes_mention_canonical_replacement():
    nrcf = classify_surface("node_registry_compat_facade")
    assert nrcf is not None
    assert "NodeFabricRegistry" in nrcf.notes or "canonical" in nrcf.notes.lower()


# ---------------------------------------------------------------------------
# Projection alignment sentinel
# ---------------------------------------------------------------------------


def test_projection_alignment_sentinel_is_set():
    """The projection routes module must have the PR-6 alignment sentinel."""
    try:
        from core.routes.projection import AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6
    except ImportError:
        pytest.skip("projection routes module not available")
    assert isinstance(AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6, str)
    assert len(AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6) > 0


def test_projection_alignment_sentinel_not_unavailable():
    """The sentinel should not fall back to the UNAVAILABLE value."""
    try:
        from core.routes.projection import AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6
    except ImportError:
        pytest.skip("projection routes module not available")
    assert "UNAVAILABLE" not in AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6, (
        "The authority boundary classification module import failed; sentinel shows UNAVAILABLE"
    )


def test_projection_alignment_sentinel_mentions_pr6():
    try:
        from core.routes.projection import AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6
    except ImportError:
        pytest.skip("projection routes module not available")
    assert "PR6" in AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6 or "PR-6" in AUTHORITY_BOUNDARY_CLASSIFICATION_ALIGNED_PR6
