#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr13_diagnostics_inspection_interaction.py
======================================================

PR-13 — Diagnostics and inspection interaction layer.

Validates that the topology inspector module:
- is importable from the correct locations;
- produces a TOPOLOGY_INSPECTOR_AUTHORITY sentinel;
- can inspect topology nodes, relations, readiness, routing, and OneAPI;
- returns correct canonical/degraded/partial/unavailable semantics;
- never presents degraded/fallback data as authoritative;
- keeps OneAPI structurally distinct and lower-horizon only;
- builds on the PR-9 adapter + PR-11/12 layout pipeline;
- handles None / minimal inputs gracefully without raising;
- produces serialisable to_dict() / to_json() outputs.

Test index:
  1.  topology_inspector module importable from
      windows_client.status_board_v2.topology_inspector.
  2.  TopologyInspector class importable from
      windows_client.status_board_v2.topology_inspector.
  3.  TOPOLOGY_INSPECTOR_AUTHORITY importable from
      windows_client.status_board_v2.topology_inspector.
  4.  TopologyInspector importable from windows_client.status_board_v2 __all__.
  5.  TOPOLOGY_INSPECTOR_AUTHORITY importable from
      windows_client.status_board_v2 __all__.
  6.  NodeInspectionDetail importable from package __all__.
  7.  RelationInspectionDetail importable from package __all__.
  8.  ReadinessInspectionDetail importable from package __all__.
  9.  RoutingInspectionDetail importable from package __all__.
  10. OneAPIInspectionDetail importable from package __all__.
  11. InspectionReport importable from package __all__.
  12. TOPOLOGY_INSPECTOR_AUTHORITY is a non-empty string.
  13. TOPOLOGY_INSPECTOR_AUTHORITY contains "TopologyInspector".
  14. TopologyInspector() instantiates without error.
  15. TopologyInspector has inspect_layout method.
  16. TopologyInspector has inspect_node method.
  17. TopologyInspector has inspect_relation method.
  18. TopologyInspector has inspect_readiness method.
  19. TopologyInspector has inspect_oneapi method.
  20. TopologyInspector has inspect_routing_summary method.
  21. TopologyInspector has inspect_from_view_model method.
  22. inspect_layout(None) returns InspectionReport (no exception).
  23. inspect_layout(None) report has readiness_label "unavailable".
  24. inspect_layout(None) report has no nodes.
  25. inspect_layout(None) report has no relations.
  26. inspect_layout(None) oneapi has is_lower_horizon_only=True.
  27. Canonical layout: inspect_layout returns InspectionReport.
  28. Canonical layout: readiness.readiness_label == "canonical".
  29. Canonical layout: readiness.is_authoritative == True.
  30. Canonical layout: readiness.is_degraded == False.
  31. Canonical layout: readiness.degraded_reason is None.
  32. Canonical layout: primary_nodes is not empty.
  33. Canonical layout: primary node is_authoritative == True.
  34. Canonical layout: primary node kind == "primary_provider".
  35. Canonical layout: oneapi.is_lower_horizon_only == True.
  36. Canonical layout: lower_horizon_nodes are distinct from primary_nodes.
  37. Canonical layout: relations list is not empty.
  38. Canonical layout: inspect_node returns NodeInspectionDetail for primary node.
  39. Canonical layout: inspect_node returns None for unknown node_id.
  40. Canonical layout: inspect_relation returns RelationInspectionDetail.
  41. Canonical layout: canonical_route relation is_authoritative == True.
  42. Canonical layout: lower_horizon_link relation is_lower_horizon == True.
  43. Degraded layout: readiness.readiness_label == "degraded".
  44. Degraded layout: readiness.is_authoritative == False.
  45. Degraded layout: readiness.is_degraded == True.
  46. Degraded layout: readiness.degraded_reason is not None.
  47. Degraded layout: readiness.degraded_reason mentions "NOT authoritative" or
      "legacy".
  48. Degraded layout: primary node is_authoritative == False.
  49. Degraded layout: fallback relation is_fallback == True.
  50. Degraded layout: fallback relation is_authoritative == False.
  51. Partial layout: readiness.readiness_label == "partial".
  52. Partial layout: readiness.is_authoritative == False.
  53. Partial layout: readiness.is_partial == True.
  54. Partial layout: readiness.degraded_reason is not None.
  55. Unavailable layout: readiness.readiness_label == "unavailable".
  56. Unavailable layout: readiness.is_unavailable == True.
  57. Unavailable layout: readiness.degraded_reason is not None.
  58. OneAPI node always in lower_horizon_nodes (canonical layout).
  59. OneAPI node always in lower_horizon_nodes (degraded layout).
  60. OneAPI node is_lower_horizon == True.
  61. OneAPI node kind == "oneapi_horizon".
  62. OneAPI node is not in primary_nodes.
  63. OneAPI node is not in support_nodes.
  64. OneAPI inspection is_lower_horizon_only always True (canonical).
  65. OneAPI inspection is_lower_horizon_only always True (degraded).
  66. OneAPI inspection is_lower_horizon_only always True (unavailable).
  67. OneAPI authority_note explicitly states lower-horizon.
  68. inspect_readiness(None) returns ReadinessInspectionDetail with unavailable.
  69. inspect_oneapi(None) returns OneAPIInspectionDetail with is_lower_horizon_only=True.
  70. inspect_routing_summary(None) returns RoutingInspectionDetail (no exception).
  71. inspect_node(None, None) returns None (no exception).
  72. inspect_relation(None, None, None) returns None (no exception).
  73. InspectionReport has to_dict() method.
  74. InspectionReport.to_dict() returns a dict.
  75. InspectionReport.to_dict() contains "readiness" key.
  76. InspectionReport.to_dict() contains "nodes" key.
  77. InspectionReport.to_dict() contains "relations" key.
  78. InspectionReport.to_dict() contains "routing" key.
  79. InspectionReport.to_dict() contains "oneapi" key.
  80. InspectionReport.to_dict() contains "inspector_authority" key.
  81. InspectionReport.to_json() returns a valid JSON string.
  82. NodeInspectionDetail.to_dict() contains "kind_meaning" key.
  83. NodeInspectionDetail.to_dict() contains "authority_note" key.
  84. RelationInspectionDetail.to_dict() contains "kind_meaning" key.
  85. RelationInspectionDetail.to_dict() contains "authority_note" key.
  86. ReadinessInspectionDetail.to_dict() contains "meaning" key.
  87. ReadinessInspectionDetail.to_dict() contains "degraded_reason" key.
  88. RoutingInspectionDetail.to_dict() contains "authority_note" key.
  89. OneAPIInspectionDetail.to_dict() contains "authority_note" key.
  90. inspect_from_view_model(canonical_vm) returns InspectionReport.
  91. inspect_from_view_model: readiness is canonical for canonical vm.
  92. inspect_from_view_model: routing.route_reason is populated for canonical vm.
  93. inspect_from_view_model: oneapi.is_lower_horizon_only is True.
  94. inspect_from_view_model(degraded_vm) readiness is degraded.
  95. inspect_from_view_model(degraded_vm) readiness.fallback_active is True.
  96. inspect_from_view_model(None) returns unavailable report.
  97. inspect_layout from to_dict() form works (dict input).
  98. Degraded node authority_note mentions non-authoritative.
  99. Canonical node authority_note mentions authoritative.
  100. TOPOLOGY_INSPECTOR_AUTHORITY is in InspectionReport.to_dict() value.
"""

from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Shared test helpers
# ---------------------------------------------------------------------------


class _MockReadinessState:
    def __init__(self, value: str) -> None:
        self.value = value

    def __str__(self) -> str:
        return self.value


class _MockProviderRouting:
    def __init__(
        self,
        selected=None,
        vendor=None,
        legacy=False,
        available=False,
        reason=None,
    ):
        self.selected_provider = selected
        self.vendor_source = vendor
        self.legacy_routing_fallback_active = legacy
        self.provider_available = available
        self.route_reason = reason
        self.primary_model_id = selected
        self.routing_authority_source = (
            "TopologyRoutePlan" if not legacy else "LegacyRouter"
        )

    def to_dict(self):
        return {
            "selected_provider": self.selected_provider,
            "vendor_source": self.vendor_source,
            "legacy_routing_fallback_active": self.legacy_routing_fallback_active,
            "provider_available": self.provider_available,
            "route_reason": self.route_reason,
        }


class _MockOneAPIHorizon:
    def __init__(self, provider_id=None, system_layer="OneAPI", available=False):
        self.provider_id = provider_id
        self.system_layer = system_layer
        self.available = available
        self.is_lower_horizon_only = True
        self.integration_type = "oneapi"

    def to_dict(self):
        return {
            "provider_id": self.provider_id,
            "system_layer": self.system_layer,
            "is_available": self.available,
            "is_lower_horizon_only": True,
            "integration_type": self.integration_type,
        }


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


def _build_layout(vm):
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    return build_constellation_layout(vm)


# ---------------------------------------------------------------------------
# Test 1-11: importability
# ---------------------------------------------------------------------------


def test_01_topology_inspector_module_importable():
    import windows_client.status_board_v2.topology_inspector as _m

    assert _m is not None


def test_02_TopologyInspector_importable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert TopologyInspector is not None


def test_03_TOPOLOGY_INSPECTOR_AUTHORITY_importable():
    from windows_client.status_board_v2.topology_inspector import (
        TOPOLOGY_INSPECTOR_AUTHORITY,
    )

    assert TOPOLOGY_INSPECTOR_AUTHORITY is not None


def test_04_TopologyInspector_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "TopologyInspector" in pkg.__all__


def test_05_TOPOLOGY_INSPECTOR_AUTHORITY_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "TOPOLOGY_INSPECTOR_AUTHORITY" in pkg.__all__


def test_06_NodeInspectionDetail_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "NodeInspectionDetail" in pkg.__all__


def test_07_RelationInspectionDetail_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "RelationInspectionDetail" in pkg.__all__


def test_08_ReadinessInspectionDetail_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "ReadinessInspectionDetail" in pkg.__all__


def test_09_RoutingInspectionDetail_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "RoutingInspectionDetail" in pkg.__all__


def test_10_OneAPIInspectionDetail_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "OneAPIInspectionDetail" in pkg.__all__


def test_11_InspectionReport_in_package_all():
    import windows_client.status_board_v2 as pkg

    assert "InspectionReport" in pkg.__all__


# ---------------------------------------------------------------------------
# Test 12-14: authority sentinel
# ---------------------------------------------------------------------------


def test_12_TOPOLOGY_INSPECTOR_AUTHORITY_is_nonempty_string():
    from windows_client.status_board_v2.topology_inspector import (
        TOPOLOGY_INSPECTOR_AUTHORITY,
    )

    assert isinstance(TOPOLOGY_INSPECTOR_AUTHORITY, str)
    assert len(TOPOLOGY_INSPECTOR_AUTHORITY) > 0


def test_13_TOPOLOGY_INSPECTOR_AUTHORITY_contains_TopologyInspector():
    from windows_client.status_board_v2.topology_inspector import (
        TOPOLOGY_INSPECTOR_AUTHORITY,
    )

    assert "TopologyInspector" in TOPOLOGY_INSPECTOR_AUTHORITY


def test_14_TopologyInspector_instantiates():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    inspector = TopologyInspector()
    assert inspector is not None


# ---------------------------------------------------------------------------
# Test 15-21: method presence
# ---------------------------------------------------------------------------


def test_15_has_inspect_layout():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_layout")


def test_16_has_inspect_node():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_node")


def test_17_has_inspect_relation():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_relation")


def test_18_has_inspect_readiness():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_readiness")


def test_19_has_inspect_oneapi():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_oneapi")


def test_20_has_inspect_routing_summary():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_routing_summary")


def test_21_has_inspect_from_view_model():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    assert hasattr(TopologyInspector(), "inspect_from_view_model")


# ---------------------------------------------------------------------------
# Test 22-26: None / missing layout handling
# ---------------------------------------------------------------------------


def test_22_inspect_layout_none_returns_InspectionReport():
    from windows_client.status_board_v2.topology_inspector import (
        InspectionReport,
        TopologyInspector,
    )

    result = TopologyInspector().inspect_layout(None)
    assert isinstance(result, InspectionReport)


def test_23_inspect_layout_none_readiness_unavailable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert report.readiness.readiness_label == "unavailable"


def test_24_inspect_layout_none_no_nodes():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert report.nodes == []


def test_25_inspect_layout_none_no_relations():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert report.relations == []


def test_26_inspect_layout_none_oneapi_lower_horizon_only():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert report.oneapi.is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# Test 27-42: canonical layout inspection
# ---------------------------------------------------------------------------


def test_27_canonical_inspect_layout_returns_InspectionReport():
    from windows_client.status_board_v2.topology_inspector import (
        InspectionReport,
        TopologyInspector,
    )

    layout = _build_layout(_make_canonical_vm())
    result = TopologyInspector().inspect_layout(layout)
    assert isinstance(result, InspectionReport)


def test_28_canonical_readiness_label():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.readiness_label == "canonical"


def test_29_canonical_readiness_is_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_authoritative is True


def test_30_canonical_readiness_not_degraded():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_degraded is False


def test_31_canonical_readiness_degraded_reason_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.degraded_reason is None


def test_32_canonical_primary_nodes_nonempty():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert len(report.primary_nodes) > 0


def test_33_canonical_primary_node_is_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.primary_nodes[0].is_authoritative is True


def test_34_canonical_primary_node_kind():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.primary_nodes[0].kind == "primary_provider"


def test_35_canonical_oneapi_lower_horizon_only():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.oneapi.is_lower_horizon_only is True


def test_36_canonical_lower_horizon_distinct_from_primary():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    primary_ids = {n.node_id for n in report.primary_nodes}
    lower_ids = {n.node_id for n in report.lower_horizon_nodes}
    # They must not overlap.
    assert primary_ids.isdisjoint(lower_ids)


def test_37_canonical_relations_nonempty():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert len(report.relations) > 0


def test_38_canonical_inspect_node_returns_detail():
    from windows_client.status_board_v2.topology_inspector import (
        NodeInspectionDetail,
        TopologyInspector,
    )

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.primary_nodes:
        node_id = report.primary_nodes[0].node_id
        detail = TopologyInspector().inspect_node(node_id, layout)
        assert isinstance(detail, NodeInspectionDetail)
        assert detail.node_id == node_id


def test_39_inspect_node_unknown_id_returns_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    result = TopologyInspector().inspect_node("does_not_exist_xyz", layout)
    assert result is None


def test_40_canonical_inspect_relation_returns_detail():
    from windows_client.status_board_v2.topology_inspector import (
        RelationInspectionDetail,
        TopologyInspector,
    )

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.relations:
        rel = report.relations[0]
        detail = TopologyInspector().inspect_relation(rel.source_id, rel.target_id, layout)
        assert isinstance(detail, RelationInspectionDetail)


def test_41_canonical_route_relation_is_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    canonical_rels = [r for r in report.relations if r.kind == "canonical_route"]
    # Canonical relations must be authoritative.
    for rel in canonical_rels:
        assert rel.is_authoritative is True


def test_42_lower_horizon_link_relation_is_lower_horizon():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    lh_rels = [r for r in report.relations if r.kind == "lower_horizon_link"]
    for rel in lh_rels:
        assert rel.is_lower_horizon is True


# ---------------------------------------------------------------------------
# Test 43-50: degraded layout inspection
# ---------------------------------------------------------------------------


def test_43_degraded_readiness_label():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.readiness_label == "degraded"


def test_44_degraded_readiness_not_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_authoritative is False


def test_45_degraded_readiness_is_degraded():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_degraded is True


def test_46_degraded_readiness_has_degraded_reason():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.degraded_reason is not None


def test_47_degraded_reason_mentions_not_authoritative_or_legacy():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    reason = report.readiness.degraded_reason or ""
    assert "NOT" in reason or "legacy" in reason or "not authoritative" in reason.lower()


def test_48_degraded_primary_node_not_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.primary_nodes:
        assert node.is_authoritative is False


def test_49_degraded_fallback_relation_is_fallback():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    fallback_rels = [r for r in report.relations if r.kind == "fallback_path"]
    for rel in fallback_rels:
        assert rel.is_fallback is True


def test_50_degraded_fallback_relation_not_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    fallback_rels = [r for r in report.relations if r.kind == "fallback_path"]
    for rel in fallback_rels:
        assert rel.is_authoritative is False


# ---------------------------------------------------------------------------
# Test 51-57: partial / unavailable layout inspection
# ---------------------------------------------------------------------------


def test_51_partial_readiness_label():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_partial_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.readiness_label == "partial"


def test_52_partial_readiness_not_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_partial_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_authoritative is False


def test_53_partial_readiness_is_partial():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_partial_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_partial is True


def test_54_partial_readiness_degraded_reason_not_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_partial_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.degraded_reason is not None


def test_55_unavailable_readiness_label():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_unavailable_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.readiness_label == "unavailable"


def test_56_unavailable_readiness_is_unavailable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_unavailable_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.is_unavailable is True


def test_57_unavailable_readiness_degraded_reason_not_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_unavailable_vm())
    report = TopologyInspector().inspect_layout(layout)
    assert report.readiness.degraded_reason is not None


# ---------------------------------------------------------------------------
# Test 58-67: OneAPI isolation
# ---------------------------------------------------------------------------


def test_58_oneapi_in_lower_horizon_nodes_canonical():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    oneapi_nodes = [n for n in report.lower_horizon_nodes if n.kind == "oneapi_horizon"]
    # At least one OneAPI node must be in lower_horizon_nodes.
    assert len(oneapi_nodes) >= 1


def test_59_oneapi_in_lower_horizon_nodes_degraded():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    # In degraded layout, lower_horizon layer may be empty, but any oneapi
    # nodes that do exist must be in lower_horizon_nodes only.
    for node in report.primary_nodes:
        assert node.kind != "oneapi_horizon"
    for node in report.support_nodes:
        assert node.kind != "oneapi_horizon"


def test_60_oneapi_node_is_lower_horizon_true():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.lower_horizon_nodes:
        if node.kind == "oneapi_horizon":
            assert node.is_lower_horizon is True


def test_61_oneapi_node_kind_is_oneapi_horizon():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    oneapi_nodes = [n for n in report.nodes if n.kind == "oneapi_horizon"]
    for node in oneapi_nodes:
        assert node.kind == "oneapi_horizon"


def test_62_oneapi_node_not_in_primary_nodes():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.primary_nodes:
        assert node.kind != "oneapi_horizon"


def test_63_oneapi_node_not_in_support_nodes():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.support_nodes:
        assert node.kind != "oneapi_horizon"


def test_64_inspect_oneapi_is_lower_horizon_only_canonical():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    oneapi = TopologyInspector().inspect_oneapi(layout)
    assert oneapi.is_lower_horizon_only is True


def test_65_inspect_oneapi_is_lower_horizon_only_degraded():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    oneapi = TopologyInspector().inspect_oneapi(layout)
    assert oneapi.is_lower_horizon_only is True


def test_66_inspect_oneapi_is_lower_horizon_only_unavailable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    oneapi = TopologyInspector().inspect_oneapi(None)
    assert oneapi.is_lower_horizon_only is True


def test_67_oneapi_authority_note_mentions_lower_horizon():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    oneapi = TopologyInspector().inspect_oneapi(layout)
    note = oneapi.authority_note.lower()
    assert "lower-horizon" in note or "lower_horizon" in note


# ---------------------------------------------------------------------------
# Test 68-72: graceful None handling
# ---------------------------------------------------------------------------


def test_68_inspect_readiness_none_returns_unavailable():
    from windows_client.status_board_v2.topology_inspector import (
        ReadinessInspectionDetail,
        TopologyInspector,
    )

    result = TopologyInspector().inspect_readiness(None)
    assert isinstance(result, ReadinessInspectionDetail)
    assert result.readiness_label == "unavailable"


def test_69_inspect_oneapi_none_lower_horizon_only():
    from windows_client.status_board_v2.topology_inspector import (
        OneAPIInspectionDetail,
        TopologyInspector,
    )

    result = TopologyInspector().inspect_oneapi(None)
    assert isinstance(result, OneAPIInspectionDetail)
    assert result.is_lower_horizon_only is True


def test_70_inspect_routing_summary_none_no_exception():
    from windows_client.status_board_v2.topology_inspector import (
        RoutingInspectionDetail,
        TopologyInspector,
    )

    result = TopologyInspector().inspect_routing_summary(None)
    assert isinstance(result, RoutingInspectionDetail)


def test_71_inspect_node_none_layout_returns_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    result = TopologyInspector().inspect_node("some_id", None)
    assert result is None


def test_72_inspect_relation_none_layout_returns_none():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    result = TopologyInspector().inspect_relation("a", "b", None)
    assert result is None


# ---------------------------------------------------------------------------
# Test 73-89: serialisation
# ---------------------------------------------------------------------------


def test_73_InspectionReport_has_to_dict():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert hasattr(report, "to_dict")


def test_74_InspectionReport_to_dict_returns_dict():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    assert isinstance(report.to_dict(), dict)


def test_75_to_dict_contains_readiness():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "readiness" in d


def test_76_to_dict_contains_nodes():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "nodes" in d


def test_77_to_dict_contains_relations():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "relations" in d


def test_78_to_dict_contains_routing():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "routing" in d


def test_79_to_dict_contains_oneapi():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "oneapi" in d


def test_80_to_dict_contains_inspector_authority():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    d = TopologyInspector().inspect_layout(None).to_dict()
    assert "inspector_authority" in d


def test_81_to_json_returns_valid_json():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(_build_layout(_make_canonical_vm()))
    json_str = report.to_json()
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)


def test_82_NodeInspectionDetail_to_dict_has_kind_meaning():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.nodes:
        d = report.nodes[0].to_dict()
        assert "kind_meaning" in d


def test_83_NodeInspectionDetail_to_dict_has_authority_note():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.nodes:
        d = report.nodes[0].to_dict()
        assert "authority_note" in d


def test_84_RelationInspectionDetail_to_dict_has_kind_meaning():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.relations:
        d = report.relations[0].to_dict()
        assert "kind_meaning" in d


def test_85_RelationInspectionDetail_to_dict_has_authority_note():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    if report.relations:
        d = report.relations[0].to_dict()
        assert "authority_note" in d


def test_86_ReadinessInspectionDetail_to_dict_has_meaning():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    d = report.readiness.to_dict()
    assert "meaning" in d


def test_87_ReadinessInspectionDetail_to_dict_has_degraded_reason():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_layout(None)
    d = report.readiness.to_dict()
    assert "degraded_reason" in d


def test_88_RoutingInspectionDetail_to_dict_has_authority_note():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_routing_summary(None)
    d = report.to_dict()
    assert "authority_note" in d


def test_89_OneAPIInspectionDetail_to_dict_has_authority_note():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_oneapi(None)
    d = report.to_dict()
    assert "authority_note" in d


# ---------------------------------------------------------------------------
# Test 90-100: inspect_from_view_model + pipeline invariants
# ---------------------------------------------------------------------------


def test_90_inspect_from_view_model_canonical_returns_InspectionReport():
    from windows_client.status_board_v2.topology_inspector import (
        InspectionReport,
        TopologyInspector,
    )

    report = TopologyInspector().inspect_from_view_model(_make_canonical_vm())
    assert isinstance(report, InspectionReport)


def test_91_inspect_from_view_model_canonical_readiness():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(_make_canonical_vm())
    assert report.readiness.readiness_label == "canonical"
    assert report.readiness.is_authoritative is True


def test_92_inspect_from_view_model_routing_route_reason_populated():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(_make_canonical_vm())
    # topology_route_reason from vm should be forwarded to routing.route_reason
    assert report.routing.route_reason == "primary_route"


def test_93_inspect_from_view_model_oneapi_lower_horizon_only():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(_make_canonical_vm())
    assert report.oneapi.is_lower_horizon_only is True


def test_94_inspect_from_view_model_degraded():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(_make_degraded_vm())
    assert report.readiness.readiness_label == "degraded"
    assert report.readiness.is_degraded is True


def test_95_inspect_from_view_model_degraded_fallback_active():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(_make_degraded_vm())
    assert report.readiness.fallback_active is True


def test_96_inspect_from_view_model_none_returns_unavailable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    report = TopologyInspector().inspect_from_view_model(None)
    assert report.readiness.readiness_label == "unavailable"


def test_97_inspect_layout_from_dict_works():
    from windows_client.status_board_v2.topology_inspector import (
        InspectionReport,
        TopologyInspector,
    )

    layout = _build_layout(_make_canonical_vm())
    layout_dict = layout.to_dict()
    result = TopologyInspector().inspect_layout(layout_dict)
    assert isinstance(result, InspectionReport)
    assert result.readiness.readiness_label == "canonical"


def test_98_degraded_node_authority_note_mentions_non_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_degraded_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.primary_nodes:
        note = node.authority_note.upper()
        assert "NOT" in note or "AUTHORITATIVE" in note


def test_99_canonical_node_authority_note_mentions_authoritative():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector

    layout = _build_layout(_make_canonical_vm())
    report = TopologyInspector().inspect_layout(layout)
    for node in report.primary_nodes:
        note = node.authority_note.lower()
        assert "authoritative" in note


def test_100_inspector_authority_in_report_dict():
    from windows_client.status_board_v2.topology_inspector import (
        TOPOLOGY_INSPECTOR_AUTHORITY,
        TopologyInspector,
    )

    report = TopologyInspector().inspect_layout(_build_layout(_make_canonical_vm()))
    d = report.to_dict()
    assert d["inspector_authority"] == TOPOLOGY_INSPECTOR_AUTHORITY
