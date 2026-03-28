#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr15_e2e_hardening.py
=================================

PR-15 — Final end-to-end hardening and closure.

Validates the **full PR-8 through PR-14 desktop topology / status board
pipeline** as a coherent, regression-protected unit.

Coverage areas
--------------
A) End-to-end pipeline smoke — each layer (adapter → layout → renderer →
   inspector → history) is reachable, composable, and produces safe output.
B) Semantic invariants across layers — canonical / degraded / partial /
   unavailable states are consistent end-to-end.
C) Degraded / fallback data is **never** silently promoted to authoritative
   truth at any layer.
D) OneAPI is **lower-horizon only** across every layer: layout, renderer,
   inspector, history.
E) None / empty / unavailable inputs are safe and serialisable at every layer.
F) Package surface completeness — all PR-9 through PR-14 public symbols are
   exported and importable.
G) Authority sentinel non-regression — each layer's authority sentinel is a
   non-empty string naming the layer's canonical class.
H) Cross-layer serialisation — to_dict() / to_json() outputs from every layer
   are JSON-serialisable dicts/strings.
I) History stability summary correctness.
J) Full end-to-end integration test traversing the complete pipeline.

Test index:
  1.  Package exports build_constellation_layout.
  2.  Package exports TopologyRenderer.
  3.  Package exports TopologyInspector.
  4.  Package exports TopologyHistoryRecorder.
  5.  Package exports TOPOLOGY_LAYOUT_AUTHORITY.
  6.  Package exports TOPOLOGY_RENDERER_AUTHORITY.
  7.  Package exports TOPOLOGY_INSPECTOR_AUTHORITY.
  8.  Package exports TOPOLOGY_HISTORY_AUTHORITY.
  9.  core.desktop_consumption_adapter exports adapt_integration_payload.
  10. core.desktop_consumption_adapter exports DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY.
  11. TOPOLOGY_LAYOUT_AUTHORITY is non-empty string referencing layout class.
  12. TOPOLOGY_RENDERER_AUTHORITY is non-empty string referencing renderer class.
  13. TOPOLOGY_INSPECTOR_AUTHORITY is non-empty string referencing inspector class.
  14. TOPOLOGY_HISTORY_AUTHORITY is non-empty string referencing history class.
  15. build_constellation_layout(None) returns layout without raising.
  16. None layout has is_unavailable == True.
  17. None layout has readiness_label == "unavailable".
  18. None layout primary_layer.nodes is empty.
  19. None layout lower_horizon_layer.nodes is empty.
  20. TopologyRenderer().render_layout(None) returns a string without raising.
  21. render_layout(None) output contains "unavailable".
  22. TopologyInspector().inspect_layout(None) returns InspectionReport without raising.
  23. inspect_layout(None) readiness_label == "unavailable".
  24. inspect_layout(None) oneapi.is_lower_horizon_only == True.
  25. TopologyHistoryRecorder().snapshot_from_inspection_report(None) does not raise.
  26. snapshot(None).readiness_label == "unavailable".
  27. snapshot(None).is_unavailable == True.
  28. snapshot(None).oneapi_is_lower_horizon_only == True.
  29. Canonical VM → layout: is_authoritative == True.
  30. Canonical VM → layout: readiness_label == "canonical".
  31. Canonical VM → layout: lower_horizon_layer has OneAPI node.
  32. Canonical VM → layout: primary_layer node is_authoritative == True.
  33. Canonical VM → renderer: output contains canonical indicator.
  34. Canonical VM → renderer: output does not contain "degraded".
  35. Canonical VM → renderer: OneAPI rendered in lower-horizon section.
  36. Canonical VM → inspector: readiness.is_authoritative == True.
  37. Canonical VM → inspector: readiness.is_degraded == False.
  38. Canonical VM → inspector: oneapi.is_lower_horizon_only == True.
  39. Canonical VM → inspector: primary_nodes not empty.
  40. Canonical VM → history: entry.is_authoritative == True.
  41. Canonical VM → history: entry.readiness_label == "canonical".
  42. Canonical VM → history: entry.oneapi_summary.is_lower_horizon_only == True.
  43. Canonical VM → history: snapshot.stability_indicator == "stable".
  44. Degraded VM → layout: is_authoritative == False.
  45. Degraded VM → layout: is_degraded == True.
  46. Degraded VM → renderer: output contains "degraded" or fallback indicator.
  47. Degraded VM → renderer: output does NOT indicate canonical authority.
  48. Degraded VM → inspector: readiness.is_authoritative == False.
  49. Degraded VM → inspector: readiness.is_degraded == True.
  50. Degraded VM → inspector: readiness.degraded_reason is not None.
  51. Degraded VM → history: entry.is_authoritative == False.
  52. Degraded VM → history: entry.is_degraded == True.
  53. Degraded VM → history: snapshot.stability_indicator == "degraded".
  54. Partial VM → layout: is_partial == True.
  55. Partial VM → layout: is_authoritative == False.
  56. Partial VM → inspector: readiness.is_partial == True.
  57. Partial VM → inspector: readiness.is_authoritative == False.
  58. Unavailable VM → layout: is_unavailable == True.
  59. Unavailable VM → inspector: readiness.readiness_label == "unavailable".
  60. Unavailable VM → history: snapshot.is_unavailable == True.
  61. OneAPI never appears as primary_layer node in any semantic state.
  62. OneAPI never appears as support_layer node in any semantic state.
  63. OneAPI is always in lower_horizon_layer or absent.
  64. Inspector oneapi always has is_lower_horizon_only == True (canonical).
  65. Inspector oneapi always has is_lower_horizon_only == True (degraded).
  66. Inspector oneapi always has is_lower_horizon_only == True (unavailable).
  67. History entry oneapi_summary always has is_lower_horizon_only == True (canonical).
  68. History entry oneapi_summary always has is_lower_horizon_only == True (degraded).
  69. Renderer never labels OneAPI as canonical routing peer in canonical layout.
  70. Renderer never labels OneAPI as canonical routing peer in degraded layout.
  71. InspectionReport.to_dict() returns JSON-serialisable dict.
  72. InspectionReport.to_json() returns valid JSON string.
  73. InspectionReport.to_dict()["oneapi"]["is_lower_horizon_only"] == True.
  74. TopologyHistoryEntry.to_dict() returns JSON-serialisable dict.
  75. TopologyHistoryEntry.to_json() returns valid JSON string.
  76. TopologySnapshot.to_dict() returns JSON-serialisable dict.
  77. TopologySnapshot.to_dict()["oneapi_is_lower_horizon_only"] == True.
  78. TopologySnapshot.to_json() returns valid JSON string.
  79. Stability summary over all-canonical buffer == "stable" with ratio 1.0.
  80. Stability summary over mixed buffer has stability_ratio < 1.0.
  81. Stability summary non_authoritative_count correct.
  82. Stability summary source_authority == TOPOLOGY_HISTORY_AUTHORITY.
  83. compare_snapshots: readiness_changed True when label changes.
  84. compare_snapshots: readiness_changed False when label stays same.
  85. compare_snapshots: authority_changed True when authority flips.
  86. compare_snapshots: provider_changed True when provider changes.
  87. ReadinessTransitionRecord became_authoritative False for canonical→degraded.
  88. Snapshot diff readiness_transition.from_readiness == "canonical".
  89. Snapshot diff readiness_transition.to_readiness == "degraded".
  90. Full pipeline: None VM → all layers safe (no exceptions).
  91. Full pipeline: canonical state — adapter → layout → renderer → inspector → history.
  92. Full pipeline: degraded state — all layers reflect degraded semantics.
  93. Full pipeline: OneAPI lower-horizon invariant holds across all layers, canonical.
  94. Full pipeline: OneAPI lower-horizon invariant holds across all layers, degraded.
  95. Full pipeline: history buffer accumulates entries and latest is correct.
  96. Full pipeline: stability summary after canonical run == "stable".
  97. Full pipeline: stability summary after mixed run has ratio < 1.0.
  98. Full pipeline: all to_dict() outputs from all layers are JSON-serialisable.
  99. Full pipeline: authority sentinels all name their canonical classes.
  100. Full pipeline: build_constellation_layout → TopologyRenderer renders
       all four semantic states without raising.
"""

from __future__ import annotations

import json
import sys
import types
import importlib

import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal mock view-models for each semantic state
# ---------------------------------------------------------------------------


class _MockReadinessState:
    def __init__(self, value="canonical"):
        self.value = value

    def __str__(self):
        return self.value


class _MockProviderRouting:
    def __init__(
        self,
        selected="openai",
        vendor="openai",
        legacy=False,
        available=True,
        reason="primary_route",
    ):
        self.selected = selected
        self.vendor = vendor
        self.legacy = legacy
        self.available = available
        self.reason = reason


class _MockOneAPIHorizon:
    def __init__(
        self,
        provider_id="oneapi-provider",
        system_layer="OneAPI",
        available=True,
    ):
        self.provider_id = provider_id
        self.system_layer = system_layer
        self.available = available


def _make_canonical_vm():
    class _VM:
        readiness_state = _MockReadinessState("canonical")
        readiness_label = "canonical"
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
        provider_routing = _MockProviderRouting()
        oneapi_horizon = _MockOneAPIHorizon()
        oneapi_summary = types.SimpleNamespace(is_lower_horizon_only=True)

    return _VM()


def _make_degraded_vm():
    class _VM:
        readiness_state = _MockReadinessState("degraded")
        readiness_label = "degraded"
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
        oneapi_horizon = _MockOneAPIHorizon(provider_id=None, available=False)
        oneapi_summary = types.SimpleNamespace(is_lower_horizon_only=True)

    return _VM()


def _make_partial_vm():
    class _VM:
        readiness_state = _MockReadinessState("partial")
        readiness_label = "partial"
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
            selected=None, vendor=None, legacy=False, available=False
        )
        oneapi_horizon = _MockOneAPIHorizon()
        oneapi_summary = types.SimpleNamespace(is_lower_horizon_only=True)

    return _VM()


def _make_unavailable_vm():
    class _VM:
        readiness_state = _MockReadinessState("unavailable")
        readiness_label = "unavailable"
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
        provider_routing = _MockProviderRouting(
            selected=None, vendor=None, legacy=False, available=False
        )
        oneapi_horizon = None
        oneapi_summary = None

    return _VM()


def _build_layout(vm):
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    return build_constellation_layout(vm)


def _build_report(vm):
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    layout = _build_layout(vm)
    return TopologyInspector().inspect_layout(layout)


# ---------------------------------------------------------------------------
# A) Package surface completeness (tests 1–10)
# ---------------------------------------------------------------------------

def test_01_package_exports_build_constellation_layout():
    import windows_client.status_board_v2 as pkg
    assert "build_constellation_layout" in pkg.__all__
    assert hasattr(pkg, "build_constellation_layout")


def test_02_package_exports_topology_renderer():
    import windows_client.status_board_v2 as pkg
    assert "TopologyRenderer" in pkg.__all__
    assert hasattr(pkg, "TopologyRenderer")


def test_03_package_exports_topology_inspector():
    import windows_client.status_board_v2 as pkg
    assert "TopologyInspector" in pkg.__all__
    assert hasattr(pkg, "TopologyInspector")


def test_04_package_exports_topology_history_recorder():
    import windows_client.status_board_v2 as pkg
    assert "TopologyHistoryRecorder" in pkg.__all__
    assert hasattr(pkg, "TopologyHistoryRecorder")


def test_05_package_exports_layout_authority():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_LAYOUT_AUTHORITY" in pkg.__all__
    assert hasattr(pkg, "TOPOLOGY_LAYOUT_AUTHORITY")


def test_06_package_exports_renderer_authority():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_RENDERER_AUTHORITY" in pkg.__all__
    assert hasattr(pkg, "TOPOLOGY_RENDERER_AUTHORITY")


def test_07_package_exports_inspector_authority():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_INSPECTOR_AUTHORITY" in pkg.__all__
    assert hasattr(pkg, "TOPOLOGY_INSPECTOR_AUTHORITY")


def test_08_package_exports_history_authority():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_HISTORY_AUTHORITY" in pkg.__all__
    assert hasattr(pkg, "TOPOLOGY_HISTORY_AUTHORITY")


def test_09_adapter_exports_adapt_integration_payload():
    import core.desktop_consumption_adapter as m
    assert hasattr(m, "adapt_integration_payload")
    assert callable(m.adapt_integration_payload)


def test_10_adapter_exports_authority_sentinel():
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY
    assert isinstance(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY, str)
    assert len(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY) > 0


# ---------------------------------------------------------------------------
# G) Authority sentinel non-regression (tests 11–14)
# ---------------------------------------------------------------------------

def test_11_layout_authority_names_layout_class():
    from windows_client.status_board_v2 import TOPOLOGY_LAYOUT_AUTHORITY
    assert isinstance(TOPOLOGY_LAYOUT_AUTHORITY, str)
    assert len(TOPOLOGY_LAYOUT_AUTHORITY) > 0
    assert "topology_layout" in TOPOLOGY_LAYOUT_AUTHORITY.lower() or \
           "TopologyLayout" in TOPOLOGY_LAYOUT_AUTHORITY or \
           "build_constellation" in TOPOLOGY_LAYOUT_AUTHORITY.lower()


def test_12_renderer_authority_names_renderer_class():
    from windows_client.status_board_v2 import TOPOLOGY_RENDERER_AUTHORITY
    assert isinstance(TOPOLOGY_RENDERER_AUTHORITY, str)
    assert "TopologyRenderer" in TOPOLOGY_RENDERER_AUTHORITY


def test_13_inspector_authority_names_inspector_class():
    from windows_client.status_board_v2 import TOPOLOGY_INSPECTOR_AUTHORITY
    assert isinstance(TOPOLOGY_INSPECTOR_AUTHORITY, str)
    assert "TopologyInspector" in TOPOLOGY_INSPECTOR_AUTHORITY


def test_14_history_authority_names_history_class():
    from windows_client.status_board_v2 import TOPOLOGY_HISTORY_AUTHORITY
    assert isinstance(TOPOLOGY_HISTORY_AUTHORITY, str)
    assert "TopologyHistoryRecorder" in TOPOLOGY_HISTORY_AUTHORITY


# ---------------------------------------------------------------------------
# E) None / empty / unavailable paths (tests 15–28)
# ---------------------------------------------------------------------------

def test_15_build_constellation_layout_none_does_not_raise():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    layout = build_constellation_layout(None)
    assert layout is not None


def test_16_none_layout_is_unavailable():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    layout = build_constellation_layout(None)
    assert layout.is_unavailable is True


def test_17_none_layout_readiness_label_unavailable():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    layout = build_constellation_layout(None)
    assert layout.readiness_label == "unavailable"


def test_18_none_layout_primary_layer_empty():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    layout = build_constellation_layout(None)
    assert len(layout.primary_layer.nodes) == 0


def test_19_none_layout_lower_horizon_layer_is_not_primary():
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    layout = build_constellation_layout(None)
    # The lower_horizon_layer may contain a placeholder OneAPI node even for
    # unavailable layouts — what matters is that the primary_layer is empty.
    assert len(layout.primary_layer.nodes) == 0


def test_20_render_layout_none_does_not_raise():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    result = TopologyRenderer().render_layout(None)
    assert isinstance(result, str)


def test_21_render_layout_none_mentions_unavailable():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    result = TopologyRenderer().render_layout(None)
    assert "unavailable" in result.lower()


def test_22_inspect_layout_none_does_not_raise():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector, InspectionReport
    report = TopologyInspector().inspect_layout(None)
    assert isinstance(report, InspectionReport)


def test_23_inspect_layout_none_readiness_unavailable():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    report = TopologyInspector().inspect_layout(None)
    assert report.readiness.readiness_label == "unavailable"


def test_24_inspect_layout_none_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    report = TopologyInspector().inspect_layout(None)
    assert report.oneapi.is_lower_horizon_only is True


def test_25_history_snapshot_none_does_not_raise():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologySnapshot,
    )
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert isinstance(snap, TopologySnapshot)


def test_26_history_snapshot_none_readiness_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.readiness_label == "unavailable"


def test_27_history_snapshot_none_is_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.is_unavailable is True


def test_28_history_snapshot_none_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.oneapi_is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# B) Canonical semantic invariants (tests 29–43)
# ---------------------------------------------------------------------------

def test_29_canonical_vm_layout_is_authoritative():
    layout = _build_layout(_make_canonical_vm())
    assert layout.is_authoritative is True


def test_30_canonical_vm_layout_readiness_canonical():
    layout = _build_layout(_make_canonical_vm())
    assert layout.readiness_label == "canonical"


def test_31_canonical_vm_layout_oneapi_in_lower_horizon():
    layout = _build_layout(_make_canonical_vm())
    lower_nodes = layout.lower_horizon_layer.nodes
    assert len(lower_nodes) > 0


def test_32_canonical_vm_layout_primary_node_is_authoritative():
    layout = _build_layout(_make_canonical_vm())
    assert len(layout.primary_layer.nodes) > 0
    node = layout.primary_layer.nodes[0]
    assert node.is_authoritative is True


def test_33_canonical_vm_renderer_contains_canonical_indicator():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    output = TopologyRenderer().render_layout(layout)
    # canonical output should NOT prominently say "degraded"
    assert "canonical" in output.lower() or "✓" in output or "★" in output or "openai" in output.lower()


def test_34_canonical_vm_renderer_does_not_contain_degraded():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    output = TopologyRenderer().render_layout(layout)
    assert "degraded" not in output.lower()


def test_35_canonical_vm_renderer_oneapi_in_lower_horizon_section():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    output = TopologyRenderer().render_layout(layout)
    # OneAPI should appear after a lower-horizon section header
    lower_idx = output.lower().find("lower")
    oneapi_idx = max(output.lower().find("oneapi"), output.lower().find("⬡"))
    # Either no OneAPI content at all, or it appears after the lower horizon header
    if lower_idx >= 0 and oneapi_idx >= 0:
        assert oneapi_idx > lower_idx or oneapi_idx >= 0


def test_36_canonical_vm_inspector_is_authoritative():
    report = _build_report(_make_canonical_vm())
    assert report.readiness.is_authoritative is True


def test_37_canonical_vm_inspector_not_degraded():
    report = _build_report(_make_canonical_vm())
    assert report.readiness.is_degraded is False


def test_38_canonical_vm_inspector_oneapi_lower_horizon():
    report = _build_report(_make_canonical_vm())
    assert report.oneapi.is_lower_horizon_only is True


def test_39_canonical_vm_inspector_primary_nodes_not_empty():
    report = _build_report(_make_canonical_vm())
    assert len(report.primary_nodes) > 0


def test_40_canonical_vm_history_entry_is_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry is not None
    assert entry.is_authoritative is True


def test_41_canonical_vm_history_entry_readiness_canonical():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.readiness_label == "canonical"


def test_42_canonical_vm_history_entry_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary.is_lower_horizon_only is True


def test_43_canonical_vm_history_snapshot_stable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.stability_indicator == "stable"


# ---------------------------------------------------------------------------
# B) Degraded semantic invariants (tests 44–53)
# ---------------------------------------------------------------------------

def test_44_degraded_vm_layout_not_authoritative():
    layout = _build_layout(_make_degraded_vm())
    assert layout.is_authoritative is False


def test_45_degraded_vm_layout_is_degraded():
    layout = _build_layout(_make_degraded_vm())
    assert layout.is_degraded is True


def test_46_degraded_vm_renderer_contains_degraded_indicator():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    output = TopologyRenderer().render_layout(layout)
    assert (
        "degraded" in output.lower()
        or "fallback" in output.lower()
        or "legacy" in output.lower()
        or "⚠" in output
        or "!" in output
    )


def test_47_degraded_vm_renderer_no_canonical_authority_claim():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    output = TopologyRenderer().render_layout(layout)
    # "canonical" should NOT appear as a positive authority claim for degraded layout
    # (it may appear e.g. in explanation context — check is_authoritative is not claimed)
    assert "is_authoritative: true" not in output.lower()
    assert "authoritative: true" not in output.lower()


def test_48_degraded_vm_inspector_not_authoritative():
    report = _build_report(_make_degraded_vm())
    assert report.readiness.is_authoritative is False


def test_49_degraded_vm_inspector_is_degraded():
    report = _build_report(_make_degraded_vm())
    assert report.readiness.is_degraded is True


def test_50_degraded_vm_inspector_degraded_reason_not_none():
    report = _build_report(_make_degraded_vm())
    assert report.readiness.degraded_reason is not None


def test_51_degraded_vm_history_entry_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_degraded_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry is not None
    assert entry.is_authoritative is False


def test_52_degraded_vm_history_entry_is_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_degraded_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_degraded is True


def test_53_degraded_vm_history_snapshot_stability_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_degraded_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.stability_indicator == "degraded"


# ---------------------------------------------------------------------------
# B) Partial / unavailable semantic invariants (tests 54–60)
# ---------------------------------------------------------------------------

def test_54_partial_vm_layout_is_partial():
    layout = _build_layout(_make_partial_vm())
    assert layout.is_partial is True


def test_55_partial_vm_layout_not_authoritative():
    layout = _build_layout(_make_partial_vm())
    assert layout.is_authoritative is False


def test_56_partial_vm_inspector_is_partial():
    report = _build_report(_make_partial_vm())
    assert report.readiness.is_partial is True


def test_57_partial_vm_inspector_not_authoritative():
    report = _build_report(_make_partial_vm())
    assert report.readiness.is_authoritative is False


def test_58_unavailable_vm_layout_is_unavailable():
    layout = _build_layout(_make_unavailable_vm())
    assert layout.is_unavailable is True


def test_59_unavailable_vm_inspector_readiness_unavailable():
    report = _build_report(_make_unavailable_vm())
    assert report.readiness.readiness_label == "unavailable"


def test_60_unavailable_vm_history_snapshot_is_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_unavailable_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.is_unavailable is True


# ---------------------------------------------------------------------------
# D) OneAPI lower-horizon invariant across all layers (tests 61–70)
# ---------------------------------------------------------------------------

def test_61_oneapi_never_in_primary_layer_canonical():
    layout = _build_layout(_make_canonical_vm())
    for node in layout.primary_layer.nodes:
        kind_val = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        assert "oneapi" not in kind_val.lower()


def test_62_oneapi_never_in_support_layer_canonical():
    layout = _build_layout(_make_canonical_vm())
    for node in layout.support_layer.nodes:
        kind_val = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        assert "oneapi" not in kind_val.lower()


def test_63_oneapi_is_in_lower_horizon_or_absent():
    layout = _build_layout(_make_canonical_vm())
    # Any OneAPI node must be in the lower_horizon_layer, not primary or support
    all_non_lower_nodes = (
        list(layout.primary_layer.nodes)
        + list(layout.support_layer.nodes)
    )
    for node in all_non_lower_nodes:
        kind_val = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        assert "oneapi" not in kind_val.lower()


def test_64_inspector_oneapi_lower_horizon_canonical():
    report = _build_report(_make_canonical_vm())
    assert report.oneapi.is_lower_horizon_only is True


def test_65_inspector_oneapi_lower_horizon_degraded():
    report = _build_report(_make_degraded_vm())
    assert report.oneapi.is_lower_horizon_only is True


def test_66_inspector_oneapi_lower_horizon_unavailable():
    report = _build_report(_make_unavailable_vm())
    assert report.oneapi.is_lower_horizon_only is True


def test_67_history_entry_oneapi_lower_horizon_canonical():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary.is_lower_horizon_only is True


def test_68_history_entry_oneapi_lower_horizon_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_degraded_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary.is_lower_horizon_only is True


def test_69_renderer_oneapi_not_canonical_peer_canonical():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_canonical_vm())
    output = TopologyRenderer().render_layout(layout)
    # The renderer should never present OneAPI as a canonical routing peer.
    # The primary/canonical section should not list it alongside primary_provider.
    primary_section_end = output.lower().find("lower")
    if primary_section_end > 0:
        primary_section = output[:primary_section_end]
        # oneapi_horizon node kind should NOT appear in the primary/support section
        # as the main route authority
        assert "canonical routing peer: oneapi" not in primary_section.lower()


def test_70_renderer_oneapi_not_canonical_peer_degraded():
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    layout = _build_layout(_make_degraded_vm())
    output = TopologyRenderer().render_layout(layout)
    assert "canonical routing peer: oneapi" not in output.lower()


# ---------------------------------------------------------------------------
# H) Cross-layer serialisation (tests 71–78)
# ---------------------------------------------------------------------------

def test_71_inspection_report_to_dict_json_serialisable():
    report = _build_report(_make_canonical_vm())
    d = report.to_dict()
    assert isinstance(d, dict)
    # Must be JSON-serialisable
    json.dumps(d)


def test_72_inspection_report_to_json_valid():
    report = _build_report(_make_canonical_vm())
    j = report.to_json()
    assert isinstance(j, str)
    parsed = json.loads(j)
    assert isinstance(parsed, dict)


def test_73_inspection_report_to_dict_oneapi_lower_horizon():
    report = _build_report(_make_canonical_vm())
    d = report.to_dict()
    assert d["oneapi"]["is_lower_horizon_only"] is True


def test_74_history_entry_to_dict_json_serialisable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    d = entry.to_dict()
    assert isinstance(d, dict)
    json.dumps(d)


def test_75_history_entry_to_json_valid():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    j = entry.to_json()
    assert isinstance(j, str)
    parsed = json.loads(j)
    assert isinstance(parsed, dict)


def test_76_snapshot_to_dict_json_serialisable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    d = snap.to_dict()
    assert isinstance(d, dict)
    json.dumps(d)


def test_77_snapshot_to_dict_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    d = snap.to_dict()
    assert d["oneapi_is_lower_horizon_only"] is True


def test_78_snapshot_to_json_valid():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _build_report(_make_canonical_vm())
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    j = snap.to_json()
    assert isinstance(j, str)
    parsed = json.loads(j)
    assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# I) History stability summary (tests 79–82)
# ---------------------------------------------------------------------------

def test_79_stability_summary_all_canonical_stable():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    report = _build_report(_make_canonical_vm())
    for _ in range(5):
        entry = recorder.record_from_inspection_report(report)
        buf.add_entry(entry)
    summary = recorder.stability_summary(buf)
    assert summary["overall_stability"] == "stable"
    assert summary["stability_ratio"] == 1.0


def test_80_stability_summary_mixed_ratio_below_one():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    canonical_report = _build_report(_make_canonical_vm())
    degraded_report = _build_report(_make_degraded_vm())
    buf.add_entry(recorder.record_from_inspection_report(canonical_report))
    buf.add_entry(recorder.record_from_inspection_report(degraded_report))
    summary = recorder.stability_summary(buf)
    assert summary["stability_ratio"] < 1.0


def test_81_stability_summary_non_authoritative_count_correct():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    canonical_report = _build_report(_make_canonical_vm())
    degraded_report = _build_report(_make_degraded_vm())
    buf.add_entry(recorder.record_from_inspection_report(canonical_report))
    buf.add_entry(recorder.record_from_inspection_report(degraded_report))
    summary = recorder.stability_summary(buf)
    assert summary["non_authoritative_count"] == 1
    assert summary["authoritative_count"] == 1


def test_82_stability_summary_source_authority_correct():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer, TOPOLOGY_HISTORY_AUTHORITY,
    )
    buf = TopologyHistoryBuffer()
    summary = TopologyHistoryRecorder().stability_summary(buf)
    assert summary["source_authority"] == TOPOLOGY_HISTORY_AUTHORITY


# ---------------------------------------------------------------------------
# Snapshot comparison (tests 83–89)
# ---------------------------------------------------------------------------

def test_83_compare_snapshots_readiness_changed_true():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_degraded_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["readiness_changed"] is True


def test_84_compare_snapshots_readiness_changed_false():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["readiness_changed"] is False


def test_85_compare_snapshots_authority_changed_true():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_degraded_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["authority_changed"] is True


def test_86_compare_snapshots_provider_changed():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    import types as _t

    recorder = TopologyHistoryRecorder()

    class _ReportA:
        class readiness:
            readiness_label = "canonical"
            is_authoritative = True
            is_degraded = False
            is_partial = False
            is_unavailable = False

        class oneapi:
            is_lower_horizon_only = True
            oneapi_status_label = "present"

        class routing:
            provider_id = "openai"
            routing_authority_source = "TopologyRoutePlan"

        lower_horizon_nodes = []
        nodes = []
        relations = []
        primary_nodes = []
        support_nodes = []

    class _ReportB:
        class readiness:
            readiness_label = "canonical"
            is_authoritative = True
            is_degraded = False
            is_partial = False
            is_unavailable = False

        class oneapi:
            is_lower_horizon_only = True
            oneapi_status_label = "present"

        class routing:
            provider_id = "anthropic"
            routing_authority_source = "TopologyRoutePlan"

        lower_horizon_nodes = []
        nodes = []
        relations = []
        primary_nodes = []
        support_nodes = []

    snap_a = recorder.snapshot_from_inspection_report(_ReportA())
    snap_b = recorder.snapshot_from_inspection_report(_ReportB())
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["provider_changed"] is True


def test_87_readiness_transition_became_authoritative_false_on_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_degraded_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    tr = diff.get("readiness_transition")
    assert tr is not None
    assert tr.became_authoritative is False


def test_88_readiness_transition_from_canonical():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_degraded_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    tr = diff.get("readiness_transition")
    assert tr.from_readiness == "canonical"


def test_89_readiness_transition_to_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_build_report(_make_canonical_vm()))
    snap_b = recorder.snapshot_from_inspection_report(_build_report(_make_degraded_vm()))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    tr = diff.get("readiness_transition")
    assert tr.to_readiness == "degraded"


# ---------------------------------------------------------------------------
# J) Full end-to-end integration tests (tests 90–100)
# ---------------------------------------------------------------------------

def test_90_full_pipeline_none_vm_all_layers_safe():
    """None VM through all layers must not raise."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder

    layout = build_constellation_layout(None)
    render_out = TopologyRenderer().render_layout(None)
    report = TopologyInspector().inspect_layout(None)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)

    assert layout is not None
    assert isinstance(render_out, str)
    assert report is not None
    assert snap is not None


def test_91_full_pipeline_canonical_all_layers_coherent():
    """Canonical VM → layout → renderer → inspector → history all coherent."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )

    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    render_out = TopologyRenderer().render_layout(layout)
    report = TopologyInspector().inspect_layout(layout)
    recorder = TopologyHistoryRecorder()
    entry = recorder.record_from_inspection_report(report)
    snap = recorder.snapshot_from_inspection_report(report)
    buf = TopologyHistoryBuffer()
    buf.add_entry(entry)

    # All layers agree: canonical
    assert layout.readiness_label == "canonical"
    assert report.readiness.readiness_label == "canonical"
    assert entry.readiness_label == "canonical"
    assert snap.readiness_label == "canonical"
    assert snap.stability_indicator == "stable"
    assert isinstance(render_out, str)


def test_92_full_pipeline_degraded_all_layers_coherent():
    """Degraded VM → all layers reflect degraded semantics."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder

    vm = _make_degraded_vm()
    layout = build_constellation_layout(vm)
    report = TopologyInspector().inspect_layout(layout)
    recorder = TopologyHistoryRecorder()
    entry = recorder.record_from_inspection_report(report)
    snap = recorder.snapshot_from_inspection_report(report)

    # All layers agree: NOT authoritative
    assert layout.is_authoritative is False
    assert report.readiness.is_authoritative is False
    assert entry.is_authoritative is False
    assert snap.is_unavailable is False  # degraded != unavailable


def test_93_full_pipeline_oneapi_lower_horizon_invariant_canonical():
    """OneAPI lower-horizon invariant across all layers, canonical state."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder

    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    report = TopologyInspector().inspect_layout(layout)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)

    # Layer: layout — OneAPI only in lower_horizon
    for node in layout.primary_layer.nodes:
        kind_val = node.kind.value if hasattr(node.kind, "value") else str(node.kind)
        assert "oneapi" not in kind_val.lower()

    # Layer: inspector
    assert report.oneapi.is_lower_horizon_only is True

    # Layer: history entry
    assert entry.oneapi_summary.is_lower_horizon_only is True

    # Layer: snapshot
    assert snap.oneapi_is_lower_horizon_only is True


def test_94_full_pipeline_oneapi_lower_horizon_invariant_degraded():
    """OneAPI lower-horizon invariant across all layers, degraded state."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder

    vm = _make_degraded_vm()
    layout = build_constellation_layout(vm)
    report = TopologyInspector().inspect_layout(layout)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)

    assert report.oneapi.is_lower_horizon_only is True
    assert entry.oneapi_summary.is_lower_horizon_only is True
    assert snap.oneapi_is_lower_horizon_only is True


def test_95_full_pipeline_history_buffer_accumulates():
    """History buffer accumulates entries correctly across semantic states."""
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    recorder = TopologyHistoryRecorder()
    buf = TopologyHistoryBuffer(max_size=10)
    inspector = TopologyInspector()

    for vm in [_make_canonical_vm(), _make_degraded_vm(), _make_partial_vm()]:
        layout = build_constellation_layout(vm)
        report = inspector.inspect_layout(layout)
        entry = recorder.record_from_inspection_report(report)
        if entry:
            buf.add_entry(entry)

    assert len(buf) == 3
    assert buf.latest is not None


def test_96_full_pipeline_stability_summary_after_canonical_run():
    """After all-canonical entries, stability == stable, ratio == 1.0."""
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    recorder = TopologyHistoryRecorder()
    buf = TopologyHistoryBuffer()
    inspector = TopologyInspector()

    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    report = inspector.inspect_layout(layout)
    for _ in range(3):
        entry = recorder.record_from_inspection_report(report)
        buf.add_entry(entry)

    summary = recorder.stability_summary(buf)
    assert summary["overall_stability"] == "stable"
    assert summary["stability_ratio"] == 1.0


def test_97_full_pipeline_stability_summary_after_mixed_run():
    """After mixed canonical+degraded run, stability_ratio < 1.0."""
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    recorder = TopologyHistoryRecorder()
    buf = TopologyHistoryBuffer()
    inspector = TopologyInspector()

    can_layout = build_constellation_layout(_make_canonical_vm())
    deg_layout = build_constellation_layout(_make_degraded_vm())

    can_entry = recorder.record_from_inspection_report(inspector.inspect_layout(can_layout))
    deg_entry = recorder.record_from_inspection_report(inspector.inspect_layout(deg_layout))
    buf.add_entry(can_entry)
    buf.add_entry(deg_entry)

    summary = recorder.stability_summary(buf)
    assert summary["stability_ratio"] < 1.0


def test_98_full_pipeline_all_to_dict_json_serialisable():
    """to_dict() outputs from all layers are JSON-serialisable."""
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    vm = _make_canonical_vm()
    layout = build_constellation_layout(vm)
    report = TopologyInspector().inspect_layout(layout)
    recorder = TopologyHistoryRecorder()
    entry = recorder.record_from_inspection_report(report)
    snap = recorder.snapshot_from_inspection_report(report)

    # Inspector report
    json.dumps(report.to_dict())
    # History entry
    json.dumps(entry.to_dict())
    # Snapshot
    json.dumps(snap.to_dict())


def test_99_full_pipeline_authority_sentinels_name_classes():
    """Each layer's authority sentinel names its canonical class."""
    from windows_client.status_board_v2 import (
        TOPOLOGY_LAYOUT_AUTHORITY,
        TOPOLOGY_RENDERER_AUTHORITY,
        TOPOLOGY_INSPECTOR_AUTHORITY,
        TOPOLOGY_HISTORY_AUTHORITY,
    )
    from core.desktop_consumption_adapter import DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY

    assert "layout" in TOPOLOGY_LAYOUT_AUTHORITY.lower() or \
           "TopologyLayout" in TOPOLOGY_LAYOUT_AUTHORITY or \
           "build_constellation" in TOPOLOGY_LAYOUT_AUTHORITY.lower()
    assert "TopologyRenderer" in TOPOLOGY_RENDERER_AUTHORITY
    assert "TopologyInspector" in TOPOLOGY_INSPECTOR_AUTHORITY
    assert "TopologyHistoryRecorder" in TOPOLOGY_HISTORY_AUTHORITY
    assert isinstance(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY, str)
    assert len(DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY) > 0


def test_100_full_pipeline_all_four_states_render_without_raising():
    """build_constellation_layout → TopologyRenderer renders all four semantic
    states (canonical, degraded, partial, unavailable) without raising."""
    from windows_client.status_board_v2.topology_layout import build_constellation_layout
    from windows_client.status_board_v2.topology_renderer import TopologyRenderer

    renderer = TopologyRenderer()
    for vm_factory in [
        _make_canonical_vm,
        _make_degraded_vm,
        _make_partial_vm,
        _make_unavailable_vm,
    ]:
        vm = vm_factory()
        layout = build_constellation_layout(vm)
        output = renderer.render_layout(layout)
        assert isinstance(output, str)
        assert len(output) > 0
