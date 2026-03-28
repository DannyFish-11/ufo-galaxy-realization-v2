#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr11_topology_constellation_layout.py
=================================================

PR-11 — Topology / constellation layout foundation after PR-10 merge.

Validates that the topology/constellation layout module:
- is importable from the correct locations;
- builds structurally-correct layouts from DesktopClientViewModel;
- produces canonical / degraded / partial / unavailable-aware layouts;
- always places OneAPI in a lower-horizon layer;
- never marks degraded/fallback nodes as authoritative;
- produces correct relations between nodes;
- handles None / minimal view-models gracefully;
- never bypasses the adapter-driven view-model surface.

Test index:
  1.  topology_layout module importable from windows_client.status_board_v2.topology_layout.
  2.  build_constellation_layout importable from windows_client.status_board_v2.topology_layout.
  3.  TOPOLOGY_LAYOUT_AUTHORITY importable from windows_client.status_board_v2.topology_layout.
  4.  TopologyConstellationLayout importable from windows_client.status_board_v2.topology_layout.
  5.  TopologyLayoutNode importable from windows_client.status_board_v2.topology_layout.
  6.  TopologyLayoutRelation importable from windows_client.status_board_v2.topology_layout.
  7.  TopologyLayoutLayer importable from windows_client.status_board_v2.topology_layout.
  8.  TopologyNodeKind importable from windows_client.status_board_v2.topology_layout.
  9.  TopologyRelationKind importable from windows_client.status_board_v2.topology_layout.
  10. TopologyLayerKind importable from windows_client.status_board_v2.topology_layout.
  11. build_constellation_layout importable from windows_client.status_board_v2 package __all__.
  12. TopologyConstellationLayout importable from windows_client.status_board_v2 package __all__.
  13. TOPOLOGY_LAYOUT_AUTHORITY importable from windows_client.status_board_v2 package __all__.
  14. TopologyNodeKind has primary_provider, routing_peer, support_node, oneapi_horizon values.
  15. TopologyRelationKind has canonical_route, support_path, fallback_path, lower_horizon_link.
  16. TopologyLayerKind has primary, support, lower_horizon values.
  17. build_constellation_layout(None) returns TopologyConstellationLayout.
  18. build_constellation_layout(None) returns readiness_label == "unavailable".
  19. build_constellation_layout(None) returns is_unavailable=True.
  20. build_constellation_layout(None) returns is_authoritative=False.
  21. build_constellation_layout(None) primary_layer is empty.
  22. build_constellation_layout(None) lower_horizon_layer has exactly one node.
  23. build_constellation_layout(None) lower_horizon_layer node kind is oneapi_horizon.
  24. build_constellation_layout(None) lower_horizon_layer.is_lower_horizon is True.
  25. build_constellation_layout(None) does not raise.
  26. Canonical layout: readiness_label == "canonical".
  27. Canonical layout: is_authoritative == True.
  28. Canonical layout: is_degraded == False.
  29. Canonical layout: is_partial == False.
  30. Canonical layout: is_unavailable == False.
  31. Canonical layout: primary_layer has exactly one node.
  32. Canonical layout: primary_layer node kind is primary_provider.
  33. Canonical layout: primary_layer node is_authoritative == True.
  34. Canonical layout: primary_layer node provider_id matches vm.
  35. Canonical layout: primary_layer node model_id matches vm.
  36. Canonical layout: primary_layer node readiness_label == "canonical".
  37. Canonical layout: support_layer has at least one node.
  38. Canonical layout: support_layer node kind is routing_peer.
  39. Canonical layout: lower_horizon_layer.is_lower_horizon == True.
  40. Canonical layout: lower_horizon_layer has exactly one node.
  41. Canonical layout: lower_horizon_layer node kind == oneapi_horizon.
  42. Canonical layout: lower_horizon_layer node is_authoritative == False (never a routing peer).
  43. Canonical layout: layout_authority == TOPOLOGY_LAYOUT_AUTHORITY.
  44. Canonical layout: relations list is non-empty.
  45. Canonical layout: has a canonical_route relation.
  46. Canonical layout: has a lower_horizon_link relation to oneapi node.
  47. Canonical layout: lower_horizon_link relation is_authoritative == False.
  48. Degraded layout: readiness_label == "degraded".
  49. Degraded layout: is_authoritative == False.
  50. Degraded layout: is_degraded == True.
  51. Degraded layout: primary_layer node is_authoritative == False.
  52. Degraded layout: relations use fallback_path (not canonical_route).
  53. Degraded layout: lower_horizon_layer still present with oneapi_horizon node.
  54. Partial layout: readiness_label == "partial".
  55. Partial layout: is_partial == True.
  56. Partial layout: primary node is_authoritative == False.
  57. Unavailable layout from dict: readiness_label == "unavailable".
  58. Unavailable layout: is_unavailable == True.
  59. Unavailable layout: primary_layer is empty.
  60. Dict-based view-model: build_constellation_layout works with plain dict.
  61. Dict-based view-model: canonical dict produces canonical layout.
  62. Dict-based view-model: degraded dict produces degraded layout.
  63. to_dict() returns a dict.
  64. to_dict() contains layout_id key.
  65. to_dict() contains layout_authority key.
  66. to_dict() contains readiness_label key.
  67. to_dict() primary_layer key is a dict.
  68. to_dict() lower_horizon_layer.is_lower_horizon == True.
  69. to_json() returns a string.
  70. to_json() is valid JSON.
  71. layers property returns list of length 3.
  72. layers[0] is primary_layer.
  73. layers[1] is support_layer.
  74. layers[2] is lower_horizon_layer.
  75. all_nodes returns every node across all layers.
  76. OneAPI lower-horizon node is_authoritative is always False regardless of readiness.
  77. OneAPI lower-horizon layer never promotes node to primary layer.
  78. TopologyLayoutNode to_dict() is JSON-serialisable.
  79. TopologyLayoutRelation to_dict() is JSON-serialisable.
  80. TopologyLayoutLayer to_dict() is JSON-serialisable.
"""

import sys
import os
import json

import pytest

# ---------------------------------------------------------------------------
# Ensure repository root is on sys.path.
# ---------------------------------------------------------------------------
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from windows_client.status_board_v2.topology_layout import (
    build_constellation_layout,
    TopologyConstellationLayout,
    TopologyLayoutLayer,
    TopologyLayoutNode,
    TopologyLayoutRelation,
    TopologyNodeKind,
    TopologyRelationKind,
    TopologyLayerKind,
    TOPOLOGY_LAYOUT_AUTHORITY,
)


# ---------------------------------------------------------------------------
# Helpers — minimal mock view-models
# ---------------------------------------------------------------------------

class _MockProviderRouting:
    def __init__(self, selected=None, vendor=None, legacy=False, available=True, reason=None):
        self.selected_provider = selected
        self.vendor_source = vendor
        self.legacy_routing_fallback_active = legacy
        self.provider_available = available
        self.route_reason = reason

    def to_dict(self):
        return {
            "selected_provider": self.selected_provider,
            "vendor_source": self.vendor_source,
            "legacy_routing_fallback_active": self.legacy_routing_fallback_active,
            "provider_available": self.provider_available,
            "route_reason": self.route_reason,
        }


class _MockOneAPIHorizon:
    def __init__(self, provider_id=None, system_layer=None, available=False):
        self.provider_id = provider_id
        self.system_layer = system_layer
        self.available = available
        self.is_lower_horizon_only = True

    def to_dict(self):
        return {
            "provider_id": self.provider_id,
            "system_layer": self.system_layer,
            "available": self.available,
            "is_lower_horizon_only": self.is_lower_horizon_only,
        }


class _MockReadinessState:
    def __init__(self, value: str):
        self.value = value

    def __str__(self):
        return self.value


def _make_canonical_vm():
    class _VM:
        readiness_state = _MockReadinessState("canonical")
        is_canonical = True
        is_degraded = False
        is_partial = False
        is_unavailable = False
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = "openai"
        topology_primary_model_id = "gpt-4o"
        topology_route_reason = "primary_route"
        routing_authority_source = "TopologyRoutePlan"
        integration_health = "ok"
        provider_routing = _MockProviderRouting(
            selected="openai",
            vendor="openai",
            legacy=False,
            available=True,
            reason="primary_route",
        )
        oneapi_horizon = _MockOneAPIHorizon(
            provider_id="oneapi-provider",
            system_layer="OneAPI",
            available=True,
        )
    return _VM()


def _make_degraded_vm():
    class _VM:
        readiness_state = _MockReadinessState("degraded")
        is_canonical = False
        is_degraded = True
        is_partial = False
        is_unavailable = False
        topology_legacy_fallback_active = True
        routing_legacy_fallback_active = True
        topology_provider_id = "legacy-provider"
        topology_primary_model_id = "legacy-model"
        topology_route_reason = "legacy_fallback"
        routing_authority_source = "LegacyRouter"
        integration_health = "degraded"
        provider_routing = _MockProviderRouting(
            selected="legacy-provider",
            vendor="legacy",
            legacy=True,
            available=True,
            reason="legacy_fallback",
        )
        oneapi_horizon = _MockOneAPIHorizon(
            provider_id=None,
            system_layer="OneAPI",
            available=False,
        )
    return _VM()


def _make_partial_vm():
    class _VM:
        readiness_state = _MockReadinessState("partial")
        is_canonical = False
        is_degraded = False
        is_partial = True
        is_unavailable = False
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = "openai"
        topology_primary_model_id = None
        topology_route_reason = None
        routing_authority_source = None
        integration_health = "partial"
        provider_routing = _MockProviderRouting(
            selected=None,
            vendor=None,
            legacy=False,
            available=False,
        )
        oneapi_horizon = _MockOneAPIHorizon()
    return _VM()


def _make_unavailable_vm():
    class _VM:
        readiness_state = _MockReadinessState("unavailable")
        is_canonical = False
        is_degraded = False
        is_partial = False
        is_unavailable = True
        topology_legacy_fallback_active = False
        routing_legacy_fallback_active = False
        topology_provider_id = None
        topology_primary_model_id = None
        topology_route_reason = None
        routing_authority_source = None
        integration_health = "unavailable"
        provider_routing = _MockProviderRouting()
        oneapi_horizon = None
    return _VM()


# ---------------------------------------------------------------------------
# Test 1-13: importability
# ---------------------------------------------------------------------------

def test_01_topology_layout_module_importable():
    import windows_client.status_board_v2.topology_layout as _m
    assert _m is not None


def test_02_build_constellation_layout_importable():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    assert callable(build_constellation_layout)


def test_03_authority_importable():
    from windows_client.status_board_v2.topology_layout import TOPOLOGY_LAYOUT_AUTHORITY
    assert isinstance(TOPOLOGY_LAYOUT_AUTHORITY, str)
    assert len(TOPOLOGY_LAYOUT_AUTHORITY) > 0


def test_04_TopologyConstellationLayout_importable():
    from windows_client.status_board_v2.topology_layout import TopologyConstellationLayout
    assert TopologyConstellationLayout is not None


def test_05_TopologyLayoutNode_importable():
    from windows_client.status_board_v2.topology_layout import TopologyLayoutNode
    assert TopologyLayoutNode is not None


def test_06_TopologyLayoutRelation_importable():
    from windows_client.status_board_v2.topology_layout import TopologyLayoutRelation
    assert TopologyLayoutRelation is not None


def test_07_TopologyLayoutLayer_importable():
    from windows_client.status_board_v2.topology_layout import TopologyLayoutLayer
    assert TopologyLayoutLayer is not None


def test_08_TopologyNodeKind_importable():
    from windows_client.status_board_v2.topology_layout import TopologyNodeKind
    assert TopologyNodeKind is not None


def test_09_TopologyRelationKind_importable():
    from windows_client.status_board_v2.topology_layout import TopologyRelationKind
    assert TopologyRelationKind is not None


def test_10_TopologyLayerKind_importable():
    from windows_client.status_board_v2.topology_layout import TopologyLayerKind
    assert TopologyLayerKind is not None


def test_11_build_constellation_layout_importable_from_package():
    from windows_client.status_board_v2 import build_constellation_layout
    assert callable(build_constellation_layout)


def test_12_TopologyConstellationLayout_importable_from_package():
    from windows_client.status_board_v2 import TopologyConstellationLayout
    assert TopologyConstellationLayout is not None


def test_13_authority_importable_from_package():
    from windows_client.status_board_v2 import TOPOLOGY_LAYOUT_AUTHORITY
    assert isinstance(TOPOLOGY_LAYOUT_AUTHORITY, str)


# ---------------------------------------------------------------------------
# Test 14-16: enumerations
# ---------------------------------------------------------------------------

def test_14_TopologyNodeKind_values():
    assert TopologyNodeKind.primary_provider.value == "primary_provider"
    assert TopologyNodeKind.routing_peer.value == "routing_peer"
    assert TopologyNodeKind.support_node.value == "support_node"
    assert TopologyNodeKind.oneapi_horizon.value == "oneapi_horizon"


def test_15_TopologyRelationKind_values():
    assert TopologyRelationKind.canonical_route.value == "canonical_route"
    assert TopologyRelationKind.support_path.value == "support_path"
    assert TopologyRelationKind.fallback_path.value == "fallback_path"
    assert TopologyRelationKind.lower_horizon_link.value == "lower_horizon_link"


def test_16_TopologyLayerKind_values():
    assert TopologyLayerKind.primary.value == "primary"
    assert TopologyLayerKind.support.value == "support"
    assert TopologyLayerKind.lower_horizon.value == "lower_horizon"


# ---------------------------------------------------------------------------
# Test 17-25: None view-model (unavailable layout)
# ---------------------------------------------------------------------------

def test_17_build_from_none_returns_layout():
    layout = build_constellation_layout(None)
    assert isinstance(layout, TopologyConstellationLayout)


def test_18_build_from_none_readiness_unavailable():
    layout = build_constellation_layout(None)
    assert layout.readiness_label == "unavailable"


def test_19_build_from_none_is_unavailable():
    layout = build_constellation_layout(None)
    assert layout.is_unavailable is True


def test_20_build_from_none_not_authoritative():
    layout = build_constellation_layout(None)
    assert layout.is_authoritative is False


def test_21_build_from_none_primary_layer_empty():
    layout = build_constellation_layout(None)
    assert len(layout.primary_layer.nodes) == 0


def test_22_build_from_none_lower_horizon_has_one_node():
    layout = build_constellation_layout(None)
    assert len(layout.lower_horizon_layer.nodes) == 1


def test_23_build_from_none_lower_horizon_node_kind():
    layout = build_constellation_layout(None)
    node = layout.lower_horizon_layer.nodes[0]
    assert node.kind == TopologyNodeKind.oneapi_horizon


def test_24_build_from_none_lower_horizon_is_lower_horizon():
    layout = build_constellation_layout(None)
    assert layout.lower_horizon_layer.is_lower_horizon is True


def test_25_build_from_none_does_not_raise():
    try:
        build_constellation_layout(None)
    except Exception as exc:
        pytest.fail(f"build_constellation_layout(None) raised: {exc}")


# ---------------------------------------------------------------------------
# Test 26-47: Canonical layout
# ---------------------------------------------------------------------------

def test_26_canonical_readiness_label():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.readiness_label == "canonical"


def test_27_canonical_is_authoritative():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.is_authoritative is True


def test_28_canonical_not_degraded():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.is_degraded is False


def test_29_canonical_not_partial():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.is_partial is False


def test_30_canonical_not_unavailable():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.is_unavailable is False


def test_31_canonical_primary_layer_has_one_node():
    layout = build_constellation_layout(_make_canonical_vm())
    assert len(layout.primary_layer.nodes) == 1


def test_32_canonical_primary_node_kind():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.primary_layer.nodes[0]
    assert node.kind == TopologyNodeKind.primary_provider


def test_33_canonical_primary_node_is_authoritative():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.primary_layer.nodes[0]
    assert node.is_authoritative is True


def test_34_canonical_primary_node_provider_id():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.primary_layer.nodes[0]
    assert node.provider_id == "openai"


def test_35_canonical_primary_node_model_id():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.primary_layer.nodes[0]
    assert node.model_id == "gpt-4o"


def test_36_canonical_primary_node_readiness_label():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.primary_layer.nodes[0]
    assert node.readiness_label == "canonical"


def test_37_canonical_support_layer_not_empty():
    layout = build_constellation_layout(_make_canonical_vm())
    assert len(layout.support_layer.nodes) >= 1


def test_38_canonical_support_node_kind():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.support_layer.nodes[0]
    assert node.kind == TopologyNodeKind.routing_peer


def test_39_canonical_lower_horizon_is_lower_horizon():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.lower_horizon_layer.is_lower_horizon is True


def test_40_canonical_lower_horizon_has_one_node():
    layout = build_constellation_layout(_make_canonical_vm())
    assert len(layout.lower_horizon_layer.nodes) == 1


def test_41_canonical_lower_horizon_node_kind():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.lower_horizon_layer.nodes[0]
    assert node.kind == TopologyNodeKind.oneapi_horizon


def test_42_canonical_oneapi_node_never_authoritative():
    layout = build_constellation_layout(_make_canonical_vm())
    node = layout.lower_horizon_layer.nodes[0]
    assert node.is_authoritative is False


def test_43_canonical_layout_authority():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.layout_authority == TOPOLOGY_LAYOUT_AUTHORITY


def test_44_canonical_relations_non_empty():
    layout = build_constellation_layout(_make_canonical_vm())
    assert len(layout.relations) > 0


def test_45_canonical_has_canonical_route_relation():
    layout = build_constellation_layout(_make_canonical_vm())
    kinds = [r.kind for r in layout.relations]
    assert TopologyRelationKind.canonical_route in kinds


def test_46_canonical_has_lower_horizon_link():
    layout = build_constellation_layout(_make_canonical_vm())
    kinds = [r.kind for r in layout.relations]
    assert TopologyRelationKind.lower_horizon_link in kinds


def test_47_canonical_lower_horizon_link_not_authoritative():
    layout = build_constellation_layout(_make_canonical_vm())
    for rel in layout.relations:
        if rel.kind == TopologyRelationKind.lower_horizon_link:
            assert rel.is_authoritative is False
            return
    pytest.fail("No lower_horizon_link relation found")


# ---------------------------------------------------------------------------
# Test 48-53: Degraded layout
# ---------------------------------------------------------------------------

def test_48_degraded_readiness_label():
    layout = build_constellation_layout(_make_degraded_vm())
    assert layout.readiness_label == "degraded"


def test_49_degraded_not_authoritative():
    layout = build_constellation_layout(_make_degraded_vm())
    assert layout.is_authoritative is False


def test_50_degraded_is_degraded():
    layout = build_constellation_layout(_make_degraded_vm())
    assert layout.is_degraded is True


def test_51_degraded_primary_node_not_authoritative():
    layout = build_constellation_layout(_make_degraded_vm())
    for node in layout.primary_layer.nodes:
        assert node.is_authoritative is False


def test_52_degraded_relations_use_fallback_path():
    layout = build_constellation_layout(_make_degraded_vm())
    kinds = [r.kind for r in layout.relations]
    assert TopologyRelationKind.fallback_path in kinds
    assert TopologyRelationKind.canonical_route not in kinds


def test_53_degraded_lower_horizon_still_present():
    layout = build_constellation_layout(_make_degraded_vm())
    assert layout.lower_horizon_layer.is_lower_horizon is True
    assert len(layout.lower_horizon_layer.nodes) == 1
    assert layout.lower_horizon_layer.nodes[0].kind == TopologyNodeKind.oneapi_horizon


# ---------------------------------------------------------------------------
# Test 54-59: Partial and unavailable
# ---------------------------------------------------------------------------

def test_54_partial_readiness_label():
    layout = build_constellation_layout(_make_partial_vm())
    assert layout.readiness_label == "partial"


def test_55_partial_is_partial():
    layout = build_constellation_layout(_make_partial_vm())
    assert layout.is_partial is True


def test_56_partial_primary_node_not_authoritative():
    layout = build_constellation_layout(_make_partial_vm())
    for node in layout.primary_layer.nodes:
        assert node.is_authoritative is False


def test_57_unavailable_from_vm_readiness_label():
    layout = build_constellation_layout(_make_unavailable_vm())
    assert layout.readiness_label == "unavailable"


def test_58_unavailable_is_unavailable():
    layout = build_constellation_layout(_make_unavailable_vm())
    assert layout.is_unavailable is True


def test_59_unavailable_primary_layer_empty():
    layout = build_constellation_layout(_make_unavailable_vm())
    assert len(layout.primary_layer.nodes) == 0


# ---------------------------------------------------------------------------
# Test 60-62: Dict-based view-model
# ---------------------------------------------------------------------------

def test_60_dict_based_vm_works():
    d = {
        "readiness_state": "canonical",
        "is_canonical": True,
        "is_degraded": False,
        "is_partial": False,
        "is_unavailable": False,
        "topology_legacy_fallback_active": False,
        "routing_legacy_fallback_active": False,
        "topology_provider_id": "anthropic",
        "topology_primary_model_id": "claude-3",
        "topology_route_reason": "primary",
        "routing_authority_source": "TopologyRoutePlan",
        "provider_routing": {
            "selected_provider": "anthropic",
            "vendor_source": "anthropic",
            "legacy_routing_fallback_active": False,
            "provider_available": True,
            "route_reason": "primary",
        },
        "oneapi_horizon": {
            "provider_id": None,
            "system_layer": "OneAPI",
            "available": False,
            "is_lower_horizon_only": True,
        },
    }
    layout = build_constellation_layout(d)
    assert isinstance(layout, TopologyConstellationLayout)


def test_61_dict_canonical_produces_canonical_layout():
    d = {
        "readiness_state": "canonical",
        "is_canonical": True,
        "is_degraded": False,
        "is_partial": False,
        "is_unavailable": False,
        "topology_legacy_fallback_active": False,
        "topology_provider_id": "anthropic",
        "topology_primary_model_id": "claude-3",
    }
    layout = build_constellation_layout(d)
    assert layout.readiness_label == "canonical"
    assert layout.is_authoritative is True


def test_62_dict_degraded_produces_degraded_layout():
    d = {
        "readiness_state": "degraded",
        "is_canonical": False,
        "is_degraded": True,
        "is_partial": False,
        "is_unavailable": False,
        "topology_legacy_fallback_active": True,
        "topology_provider_id": "legacy",
    }
    layout = build_constellation_layout(d)
    assert layout.readiness_label == "degraded"
    assert layout.is_degraded is True


# ---------------------------------------------------------------------------
# Test 63-70: to_dict / to_json
# ---------------------------------------------------------------------------

def test_63_to_dict_returns_dict():
    layout = build_constellation_layout(_make_canonical_vm())
    assert isinstance(layout.to_dict(), dict)


def test_64_to_dict_has_layout_id():
    layout = build_constellation_layout(_make_canonical_vm())
    assert "layout_id" in layout.to_dict()


def test_65_to_dict_has_layout_authority():
    layout = build_constellation_layout(_make_canonical_vm())
    d = layout.to_dict()
    assert "layout_authority" in d
    assert d["layout_authority"] == TOPOLOGY_LAYOUT_AUTHORITY


def test_66_to_dict_has_readiness_label():
    layout = build_constellation_layout(_make_canonical_vm())
    assert "readiness_label" in layout.to_dict()


def test_67_to_dict_primary_layer_is_dict():
    layout = build_constellation_layout(_make_canonical_vm())
    assert isinstance(layout.to_dict()["primary_layer"], dict)


def test_68_to_dict_lower_horizon_layer_is_lower_horizon():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.to_dict()["lower_horizon_layer"]["is_lower_horizon"] is True


def test_69_to_json_returns_str():
    layout = build_constellation_layout(_make_canonical_vm())
    assert isinstance(layout.to_json(), str)


def test_70_to_json_is_valid_json():
    layout = build_constellation_layout(_make_canonical_vm())
    try:
        json.loads(layout.to_json())
    except Exception as exc:
        pytest.fail(f"to_json() produced invalid JSON: {exc}")


# ---------------------------------------------------------------------------
# Test 71-80: layers / nodes helpers and extra invariants
# ---------------------------------------------------------------------------

def test_71_layers_length_three():
    layout = build_constellation_layout(_make_canonical_vm())
    assert len(layout.layers) == 3


def test_72_layers_first_is_primary():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.layers[0].layer_kind == TopologyLayerKind.primary


def test_73_layers_second_is_support():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.layers[1].layer_kind == TopologyLayerKind.support


def test_74_layers_third_is_lower_horizon():
    layout = build_constellation_layout(_make_canonical_vm())
    assert layout.layers[2].layer_kind == TopologyLayerKind.lower_horizon


def test_75_all_nodes_covers_all_layers():
    layout = build_constellation_layout(_make_canonical_vm())
    total = (
        len(layout.primary_layer.nodes)
        + len(layout.support_layer.nodes)
        + len(layout.lower_horizon_layer.nodes)
    )
    assert len(layout.all_nodes) == total


def test_76_oneapi_node_never_authoritative_any_readiness():
    for vm in [
        _make_canonical_vm(),
        _make_degraded_vm(),
        _make_partial_vm(),
        _make_unavailable_vm(),
        None,
    ]:
        layout = build_constellation_layout(vm)
        for node in layout.lower_horizon_layer.nodes:
            assert node.is_authoritative is False, (
                f"OneAPI node marked authoritative in {layout.readiness_label} layout"
            )


def test_77_oneapi_never_in_primary_layer():
    for vm in [
        _make_canonical_vm(),
        _make_degraded_vm(),
        _make_partial_vm(),
        _make_unavailable_vm(),
        None,
    ]:
        layout = build_constellation_layout(vm)
        for node in layout.primary_layer.nodes:
            assert node.kind != TopologyNodeKind.oneapi_horizon, (
                f"OneAPI node appeared in primary layer for {layout.readiness_label}"
            )


def test_78_node_to_dict_json_serialisable():
    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    node = layout.primary_layer.nodes[0]
    d = node.to_dict()
    try:
        json.dumps(d)
    except Exception as exc:
        pytest.fail(f"TopologyLayoutNode.to_dict() not JSON-serialisable: {exc}")


def test_79_relation_to_dict_json_serialisable():
    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    for rel in layout.relations:
        d = rel.to_dict()
        try:
            json.dumps(d)
        except Exception as exc:
            pytest.fail(f"TopologyLayoutRelation.to_dict() not JSON-serialisable: {exc}")


def test_80_layer_to_dict_json_serialisable():
    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    for layer in layout.layers:
        d = layer.to_dict()
        try:
            json.dumps(d)
        except Exception as exc:
            pytest.fail(f"TopologyLayoutLayer.to_dict() not JSON-serialisable: {exc}")
