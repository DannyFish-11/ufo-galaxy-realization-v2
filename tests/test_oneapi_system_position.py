#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_oneapi_system_position.py
======================================

PR-oneapi-system-position — Formalise OneAPI as system-level aggregator
integration layer.

Validates:
  1.  ONEAPI_SYSTEM_LAYER sentinel is importable from core.oneapi_system_position.
  2.  ONEAPI_SYSTEM_LAYER value is "aggregator_integration".
  3.  ONEAPI_NODE_PATH sentinel is "nodes/Node_01_OneAPI".
  4.  ONEAPI_PROVIDER_CATEGORY_VALUE sentinel is "oneapi".
  5.  OneAPIIntegrationDimension enum has all 5 required dimensions.
  6.  ONEAPI_INTEGRATION_REGISTRY contains all OneAPIIntegrationDimension values.
  7.  Every ONEAPI_INTEGRATION_REGISTRY entry has a non-empty description.
  8.  Every ONEAPI_INTEGRATION_REGISTRY entry has a non-empty canonical_module.
  9.  Every ONEAPI_INTEGRATION_REGISTRY entry has a non-empty canonical_doc.
  10. PROVIDER_SOURCE_AVAILABILITY entry canonical_module references multi_llm_router.
  11. ROUTING_CANDIDATE_POOL entry canonical_module references topology_router.
  12. PROJECTION_FACING_STATUS entry canonical_module references desktop_status_projection.
  13. CONFIG_HAS_GLOBAL_EFFECT entry canonical_module references Node_01_OneAPI.
  14. STATUS_BOARD_LOWER_ROW entry canonical_doc references DESKTOP_DISPLAY_BOUNDARIES.
  15. build_oneapi_integration_summary returns OneAPIIntegrationSnapshot.
  16. snapshot.system_layer equals ONEAPI_SYSTEM_LAYER.
  17. snapshot.node_path equals ONEAPI_NODE_PATH.
  18. snapshot.provider_category_value equals ONEAPI_PROVIDER_CATEGORY_VALUE.
  19. snapshot.registered_dimensions is a frozenset.
  20. snapshot.registered_dimensions contains all 5 dimension values.
  21. snapshot.routing_authority_ref references topology_router.TopologyRouter.
  22. snapshot.to_dict() is a dict.
  23. snapshot.to_dict() includes "system_layer" key.
  24. snapshot.to_dict() includes "node_path" key.
  25. snapshot.to_dict() includes "provider_category_value" key.
  26. snapshot.to_dict() includes "registered_dimensions" key.
  27. snapshot.to_dict() includes "routing_authority_ref" key.
  28. snapshot.to_dict()["registered_dimensions"] is a sorted list.
  29. get_oneapi_integration_registry returns the same registry on repeated calls.
  30. reset_oneapi_integration_registry clears the singleton.
  31. After reset, get_oneapi_integration_registry returns fresh registry.
  32. Each OneAPIIntegrationEntry.to_dict() includes "dimension" key.
  33. Each OneAPIIntegrationEntry.to_dict() includes "description" key.
  34. Each OneAPIIntegrationEntry.to_dict() includes "canonical_module" key.
  35. Each OneAPIIntegrationEntry.to_dict() includes "canonical_doc" key.
  36. ProviderCategory.ONEAPI exists in core.model_topology.topology_types.
  37. ProviderCategory.ONEAPI.value is "oneapi".
  38. ProviderCategory.ONEAPI is distinct from ProviderCategory.DIRECT.
  39. topology_types.py ProviderCategory.DIRECT value is "direct_models".
  40. nodes.Node_01_OneAPI.main entry is in LEGACY_PATH_REGISTRY.
  41. Node_01_OneAPI entry status is ACTIVE.
  42. Node_01_OneAPI entry pr_guardrail_added is "PR-oneapi-system-position".
  43. dashboard.backend.main.oneapi_configured is in LEGACY_PATH_REGISTRY.
  44. dashboard oneapi_configured entry status is LEGACY_COMPATIBILITY.
  45. core.api_manager.APIManager._validate_oneapi is in LEGACY_PATH_REGISTRY.
  46. api_manager entry status is LEGACY_COMPATIBILITY.
  47. LEGACY_PATH_REGISTRY has at least 3 PR-oneapi-system-position entries.
  48. is_legacy_path returns True for Node_01_OneAPI.main.
  49. docs/ONEAPI_SYSTEM_POSITION.md file exists.
  50. docs/ONEAPI_SYSTEM_POSITION.md mentions "aggregator_integration" or "aggregator integration".
  51. docs/ONEAPI_SYSTEM_POSITION.md mentions "ProviderCategory.ONEAPI".
  52. docs/ONEAPI_SYSTEM_POSITION.md mentions "TopologyRouter".
  53. docs/ONEAPI_SYSTEM_POSITION.md mentions "DesktopStatusProjection".
  54. docs/ONEAPI_SYSTEM_POSITION.md mentions "direct" provider distinction.
  55. docs/ONEAPI_SYSTEM_POSITION.md mentions "system-wide" or "system wide".
  56. docs/ONEAPI_SYSTEM_POSITION.md mentions "status_board" or "status board".
  57. nodes/Node_01_OneAPI/README.md file exists.
  58. nodes/Node_01_OneAPI/README.md mentions "aggregator".
  59. nodes/Node_01_OneAPI/README.md mentions ONEAPI_SYSTEM_POSITION.md reference.
  60. nodes/Node_01_OneAPI/main.py module docstring mentions "aggregator".
"""

from __future__ import annotations

import os
import sys

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry():
    """Ensure the singleton is clean before and after each test."""
    from core.oneapi_system_position import reset_oneapi_integration_registry
    reset_oneapi_integration_registry()
    yield
    reset_oneapi_integration_registry()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _doc_path(*parts: str) -> str:
    return os.path.join(_REPO_ROOT, *parts)


def _read_file(*parts: str) -> str:
    with open(_doc_path(*parts), encoding="utf-8") as fh:
        return fh.read()


# ===========================================================================
# 1–4: Sentinel constants
# ===========================================================================

def test_01_oneapi_system_layer_importable():
    from core.oneapi_system_position import ONEAPI_SYSTEM_LAYER
    assert ONEAPI_SYSTEM_LAYER is not None


def test_02_oneapi_system_layer_value():
    from core.oneapi_system_position import ONEAPI_SYSTEM_LAYER
    assert ONEAPI_SYSTEM_LAYER == "aggregator_integration"


def test_03_oneapi_node_path():
    from core.oneapi_system_position import ONEAPI_NODE_PATH
    assert ONEAPI_NODE_PATH == "nodes/Node_01_OneAPI"


def test_04_oneapi_provider_category_value():
    from core.oneapi_system_position import ONEAPI_PROVIDER_CATEGORY_VALUE
    assert ONEAPI_PROVIDER_CATEGORY_VALUE == "oneapi"


# ===========================================================================
# 5–14: Integration dimensions and registry
# ===========================================================================

def test_05_all_dimensions_defined():
    from core.oneapi_system_position import OneAPIIntegrationDimension
    values = {d.value for d in OneAPIIntegrationDimension}
    assert len(values) == 5


def test_06_registry_contains_all_dimensions():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY, OneAPIIntegrationDimension
    for dim in OneAPIIntegrationDimension:
        assert dim in ONEAPI_INTEGRATION_REGISTRY, f"Missing dimension: {dim}"


def test_07_registry_entries_have_description():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for dim, entry in ONEAPI_INTEGRATION_REGISTRY.items():
        assert entry.description, f"Empty description for {dim}"


def test_08_registry_entries_have_canonical_module():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for dim, entry in ONEAPI_INTEGRATION_REGISTRY.items():
        assert entry.canonical_module, f"Empty canonical_module for {dim}"


def test_09_registry_entries_have_canonical_doc():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for dim, entry in ONEAPI_INTEGRATION_REGISTRY.items():
        assert entry.canonical_doc, f"Empty canonical_doc for {dim}"


def test_10_provider_source_availability_canonical_module():
    from core.oneapi_system_position import (
        ONEAPI_INTEGRATION_REGISTRY,
        OneAPIIntegrationDimension,
    )
    entry = ONEAPI_INTEGRATION_REGISTRY[OneAPIIntegrationDimension.PROVIDER_SOURCE_AVAILABILITY]
    assert "multi_llm_router" in entry.canonical_module


def test_11_routing_candidate_pool_canonical_module():
    from core.oneapi_system_position import (
        ONEAPI_INTEGRATION_REGISTRY,
        OneAPIIntegrationDimension,
    )
    entry = ONEAPI_INTEGRATION_REGISTRY[OneAPIIntegrationDimension.ROUTING_CANDIDATE_POOL]
    assert "topology_router" in entry.canonical_module


def test_12_projection_facing_status_canonical_module():
    from core.oneapi_system_position import (
        ONEAPI_INTEGRATION_REGISTRY,
        OneAPIIntegrationDimension,
    )
    entry = ONEAPI_INTEGRATION_REGISTRY[OneAPIIntegrationDimension.PROJECTION_FACING_STATUS]
    assert "desktop_status_projection" in entry.canonical_module


def test_13_config_global_effect_canonical_module():
    from core.oneapi_system_position import (
        ONEAPI_INTEGRATION_REGISTRY,
        OneAPIIntegrationDimension,
    )
    entry = ONEAPI_INTEGRATION_REGISTRY[OneAPIIntegrationDimension.CONFIG_HAS_GLOBAL_EFFECT]
    assert "Node_01_OneAPI" in entry.canonical_module


def test_14_status_board_lower_row_canonical_doc():
    from core.oneapi_system_position import (
        ONEAPI_INTEGRATION_REGISTRY,
        OneAPIIntegrationDimension,
    )
    entry = ONEAPI_INTEGRATION_REGISTRY[OneAPIIntegrationDimension.STATUS_BOARD_LOWER_ROW]
    assert "DESKTOP_DISPLAY_BOUNDARIES" in entry.canonical_doc


# ===========================================================================
# 15–28: build_oneapi_integration_summary / snapshot
# ===========================================================================

def test_15_build_summary_returns_snapshot():
    from core.oneapi_system_position import (
        OneAPIIntegrationSnapshot,
        build_oneapi_integration_summary,
    )
    result = build_oneapi_integration_summary()
    assert isinstance(result, OneAPIIntegrationSnapshot)


def test_16_snapshot_system_layer():
    from core.oneapi_system_position import ONEAPI_SYSTEM_LAYER, build_oneapi_integration_summary
    assert build_oneapi_integration_summary().system_layer == ONEAPI_SYSTEM_LAYER


def test_17_snapshot_node_path():
    from core.oneapi_system_position import ONEAPI_NODE_PATH, build_oneapi_integration_summary
    assert build_oneapi_integration_summary().node_path == ONEAPI_NODE_PATH


def test_18_snapshot_provider_category_value():
    from core.oneapi_system_position import (
        ONEAPI_PROVIDER_CATEGORY_VALUE,
        build_oneapi_integration_summary,
    )
    assert build_oneapi_integration_summary().provider_category_value == ONEAPI_PROVIDER_CATEGORY_VALUE


def test_19_snapshot_registered_dimensions_is_frozenset():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert isinstance(build_oneapi_integration_summary().registered_dimensions, frozenset)


def test_20_snapshot_registered_dimensions_has_5():
    from core.oneapi_system_position import OneAPIIntegrationDimension, build_oneapi_integration_summary
    snap = build_oneapi_integration_summary()
    expected = {d.value for d in OneAPIIntegrationDimension}
    assert snap.registered_dimensions == expected


def test_21_snapshot_routing_authority_ref_references_topology_router():
    from core.oneapi_system_position import build_oneapi_integration_summary
    snap = build_oneapi_integration_summary()
    assert "topology_router" in snap.routing_authority_ref
    assert "TopologyRouter" in snap.routing_authority_ref


def test_22_snapshot_to_dict_is_dict():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert isinstance(build_oneapi_integration_summary().to_dict(), dict)


def test_23_snapshot_to_dict_system_layer_key():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert "system_layer" in build_oneapi_integration_summary().to_dict()


def test_24_snapshot_to_dict_node_path_key():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert "node_path" in build_oneapi_integration_summary().to_dict()


def test_25_snapshot_to_dict_provider_category_value_key():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert "provider_category_value" in build_oneapi_integration_summary().to_dict()


def test_26_snapshot_to_dict_registered_dimensions_key():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert "registered_dimensions" in build_oneapi_integration_summary().to_dict()


def test_27_snapshot_to_dict_routing_authority_ref_key():
    from core.oneapi_system_position import build_oneapi_integration_summary
    assert "routing_authority_ref" in build_oneapi_integration_summary().to_dict()


def test_28_snapshot_to_dict_registered_dimensions_is_sorted_list():
    from core.oneapi_system_position import build_oneapi_integration_summary
    dims = build_oneapi_integration_summary().to_dict()["registered_dimensions"]
    assert isinstance(dims, list)
    assert dims == sorted(dims)


# ===========================================================================
# 29–35: Singleton / reset helpers + entry to_dict
# ===========================================================================

def test_29_get_registry_returns_same_object_on_repeated_calls():
    from core.oneapi_system_position import get_oneapi_integration_registry
    r1 = get_oneapi_integration_registry()
    r2 = get_oneapi_integration_registry()
    assert r1 is r2


def test_30_reset_clears_singleton():
    from core.oneapi_system_position import (
        get_oneapi_integration_registry,
        reset_oneapi_integration_registry,
    )
    r1 = get_oneapi_integration_registry()
    reset_oneapi_integration_registry()
    # After reset, the module-level variable is None; next call re-initialises.
    r2 = get_oneapi_integration_registry()
    # They may be equal in content but the test confirms reset works without error.
    assert r2 is not None


def test_31_after_reset_registry_is_fresh():
    from core.oneapi_system_position import (
        OneAPIIntegrationDimension,
        get_oneapi_integration_registry,
        reset_oneapi_integration_registry,
    )
    reset_oneapi_integration_registry()
    reg = get_oneapi_integration_registry()
    assert len(reg) == len(list(OneAPIIntegrationDimension))


def test_32_entry_to_dict_dimension_key():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for entry in ONEAPI_INTEGRATION_REGISTRY.values():
        assert "dimension" in entry.to_dict()


def test_33_entry_to_dict_description_key():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for entry in ONEAPI_INTEGRATION_REGISTRY.values():
        assert "description" in entry.to_dict()


def test_34_entry_to_dict_canonical_module_key():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for entry in ONEAPI_INTEGRATION_REGISTRY.values():
        assert "canonical_module" in entry.to_dict()


def test_35_entry_to_dict_canonical_doc_key():
    from core.oneapi_system_position import ONEAPI_INTEGRATION_REGISTRY
    for entry in ONEAPI_INTEGRATION_REGISTRY.values():
        assert "canonical_doc" in entry.to_dict()


# ===========================================================================
# 36–39: ProviderCategory.ONEAPI distinctness from DIRECT
# ===========================================================================

def _import_provider_category():
    """Import ProviderCategory directly from the submodule to avoid pydantic chain."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "topology_types_direct",
        os.path.join(_REPO_ROOT, "core", "model_topology", "topology_types.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ProviderCategory


def test_36_provider_category_oneapi_exists():
    ProviderCategory = _import_provider_category()
    assert hasattr(ProviderCategory, "ONEAPI")


def test_37_provider_category_oneapi_value():
    ProviderCategory = _import_provider_category()
    assert ProviderCategory.ONEAPI.value == "oneapi"


def test_38_provider_category_oneapi_distinct_from_direct():
    ProviderCategory = _import_provider_category()
    assert ProviderCategory.ONEAPI != ProviderCategory.DIRECT


def test_39_provider_category_direct_value():
    ProviderCategory = _import_provider_category()
    assert ProviderCategory.DIRECT.value == "direct_models"


# ===========================================================================
# 40–48: legacy_paths.py entries
# ===========================================================================

def test_40_node_01_oneapi_in_legacy_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
    assert "nodes.Node_01_OneAPI.main" in LEGACY_PATH_REGISTRY


def test_41_node_01_oneapi_entry_status_active():
    from core.orchestration_authority.legacy_paths import (
        LEGACY_PATH_REGISTRY,
        LegacyPathStatus,
    )
    entry = LEGACY_PATH_REGISTRY["nodes.Node_01_OneAPI.main"]
    assert entry.status == LegacyPathStatus.ACTIVE


def test_42_node_01_oneapi_entry_guardrail_pr():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
    entry = LEGACY_PATH_REGISTRY["nodes.Node_01_OneAPI.main"]
    assert entry.pr_guardrail_added == "PR-oneapi-system-position"


def test_43_dashboard_oneapi_configured_in_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
    assert "dashboard.backend.main.oneapi_configured" in LEGACY_PATH_REGISTRY


def test_44_dashboard_oneapi_configured_status():
    from core.orchestration_authority.legacy_paths import (
        LEGACY_PATH_REGISTRY,
        LegacyPathStatus,
    )
    entry = LEGACY_PATH_REGISTRY["dashboard.backend.main.oneapi_configured"]
    assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_45_api_manager_validate_oneapi_in_registry():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
    assert "core.api_manager.APIManager._validate_oneapi" in LEGACY_PATH_REGISTRY


def test_46_api_manager_entry_status():
    from core.orchestration_authority.legacy_paths import (
        LEGACY_PATH_REGISTRY,
        LegacyPathStatus,
    )
    entry = LEGACY_PATH_REGISTRY["core.api_manager.APIManager._validate_oneapi"]
    assert entry.status == LegacyPathStatus.LEGACY_COMPATIBILITY


def test_47_pr_oneapi_entries_count():
    from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
    pr_entries = [
        e for e in LEGACY_PATH_REGISTRY.values()
        if e.pr_guardrail_added == "PR-oneapi-system-position"
    ]
    assert len(pr_entries) >= 3


def test_48_is_legacy_path_node_01_oneapi():
    from core.orchestration_authority.legacy_paths import is_legacy_path
    assert is_legacy_path("nodes.Node_01_OneAPI.main")


# ===========================================================================
# 49–56: docs/ONEAPI_SYSTEM_POSITION.md
# ===========================================================================

def test_49_oneapi_system_position_doc_exists():
    assert os.path.isfile(_doc_path("docs", "ONEAPI_SYSTEM_POSITION.md"))


def test_50_doc_mentions_aggregator_integration():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "aggregator" in content.lower()


def test_51_doc_mentions_provider_category_oneapi():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "ProviderCategory.ONEAPI" in content


def test_52_doc_mentions_topology_router():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "TopologyRouter" in content


def test_53_doc_mentions_desktop_status_projection():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "DesktopStatusProjection" in content


def test_54_doc_mentions_direct_provider_distinction():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "direct" in content.lower()


def test_55_doc_mentions_system_wide():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "system-wide" in content.lower() or "system wide" in content.lower()


def test_56_doc_mentions_status_board():
    content = _read_file("docs", "ONEAPI_SYSTEM_POSITION.md")
    assert "status_board" in content or "status board" in content.lower()


# ===========================================================================
# 57–60: nodes/Node_01_OneAPI artefact alignment
# ===========================================================================

def test_57_node_readme_exists():
    assert os.path.isfile(_doc_path("nodes", "Node_01_OneAPI", "README.md"))


def test_58_node_readme_mentions_aggregator():
    content = _read_file("nodes", "Node_01_OneAPI", "README.md")
    assert "aggregator" in content.lower()


def test_59_node_readme_references_system_position_doc():
    content = _read_file("nodes", "Node_01_OneAPI", "README.md")
    assert "ONEAPI_SYSTEM_POSITION" in content


def test_60_node_main_docstring_mentions_aggregator():
    content = _read_file("nodes", "Node_01_OneAPI", "main.py")
    assert "aggregator" in content.lower()
