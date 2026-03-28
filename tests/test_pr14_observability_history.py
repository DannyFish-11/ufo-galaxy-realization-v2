#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr14_observability_history.py
=========================================

PR-14 — Observability and history layer.

Validates that the topology history module:
- is importable from the correct locations;
- produces a TOPOLOGY_HISTORY_AUTHORITY sentinel;
- can record history entries from InspectionReport / layout / view-model;
- can take point-in-time snapshots from InspectionReport / layout / view-model;
- produces correct canonical/degraded/partial/unavailable semantics in history;
- never re-promotes degraded/fallback history as authoritative;
- keeps OneAPI structurally distinct and lower-horizon only in all history views;
- builds on the PR-9 through PR-13 adapter/layout/inspector pipeline;
- handles None / minimal inputs gracefully without raising;
- compares snapshots correctly (readiness_changed, authority_changed, etc.);
- produces stability summaries over a TopologyHistoryBuffer;
- produces serialisable to_dict() / to_json() outputs.

Test index:
  1.  topology_history module importable from
      windows_client.status_board_v2.topology_history.
  2.  TopologyHistoryRecorder importable from
      windows_client.status_board_v2.topology_history.
  3.  TOPOLOGY_HISTORY_AUTHORITY importable from
      windows_client.status_board_v2.topology_history.
  4.  TopologyHistoryRecorder importable from
      windows_client.status_board_v2 __all__.
  5.  TOPOLOGY_HISTORY_AUTHORITY importable from
      windows_client.status_board_v2 __all__.
  6.  TopologyChangeKind importable from package __all__.
  7.  ReadinessTransitionRecord importable from package __all__.
  8.  AuthorityChangeRecord importable from package __all__.
  9.  RoutingChangeRecord importable from package __all__.
  10. OneAPIHistorySummary importable from package __all__.
  11. TopologyHistoryEntry importable from package __all__.
  12. TopologySnapshot importable from package __all__.
  13. TopologyHistoryBuffer importable from package __all__.
  14. TOPOLOGY_HISTORY_AUTHORITY is a non-empty string.
  15. TOPOLOGY_HISTORY_AUTHORITY contains "TopologyHistoryRecorder".
  16. TopologyHistoryRecorder() instantiates without error.
  17. TopologyHistoryRecorder has record_from_inspection_report method.
  18. TopologyHistoryRecorder has record_from_layout method.
  19. TopologyHistoryRecorder has record_from_view_model method.
  20. TopologyHistoryRecorder has snapshot_from_inspection_report method.
  21. TopologyHistoryRecorder has snapshot_from_layout method.
  22. TopologyHistoryRecorder has snapshot_from_view_model method.
  23. TopologyHistoryRecorder has compare_snapshots method.
  24. TopologyHistoryRecorder has stability_summary method.
  25. record_from_inspection_report(None) returns None (no exception).
  26. record_from_layout(None) returns None (no exception).
  27. record_from_view_model(None) returns None (no exception).
  28. snapshot_from_inspection_report(None) returns TopologySnapshot (no exception).
  29. snapshot_from_inspection_report(None) returns unavailable snapshot.
  30. snapshot_from_layout(None) returns unavailable snapshot.
  31. snapshot_from_view_model(None) returns unavailable snapshot.
  32. Unavailable snapshot: is_unavailable == True.
  33. Unavailable snapshot: is_authoritative == False.
  34. Unavailable snapshot: readiness_label == "unavailable".
  35. Unavailable snapshot: stability_indicator == "unavailable".
  36. Unavailable snapshot: oneapi_is_lower_horizon_only == True.
  37. Canonical report: record_from_inspection_report returns TopologyHistoryEntry.
  38. Canonical report: entry.readiness_label == "canonical".
  39. Canonical report: entry.is_authoritative == True.
  40. Canonical report: entry.is_degraded == False.
  41. Canonical report: entry.oneapi_summary.is_lower_horizon_only == True.
  42. Canonical report: entry.source_authority == TOPOLOGY_HISTORY_AUTHORITY.
  43. Canonical report: snapshot_from_inspection_report is_authoritative == True.
  44. Canonical report: snapshot readiness_label == "canonical".
  45. Canonical report: snapshot stability_indicator == "stable".
  46. Canonical report: snapshot oneapi_is_lower_horizon_only == True.
  47. Degraded report: record_from_inspection_report returns TopologyHistoryEntry.
  48. Degraded report: entry.readiness_label == "degraded".
  49. Degraded report: entry.is_authoritative == False.
  50. Degraded report: entry.is_degraded == True.
  51. Degraded report: entry.change_kind == "topology_degraded".
  52. Degraded report: snapshot stability_indicator == "degraded".
  53. Degraded report: snapshot is_authoritative == False.
  54. Degraded report: entry.oneapi_summary.is_lower_horizon_only == True.
  55. Partial report: entry.readiness_label == "partial".
  56. Partial report: entry.is_authoritative == False.
  57. Partial report: entry.is_partial == True.
  58. Partial report: snapshot stability_indicator == "partial".
  59. Unavailable report: entry.readiness_label == "unavailable".
  60. Unavailable report: entry.is_unavailable == True.
  61. Unavailable report: entry.is_authoritative == False.
  62. OneAPIHistorySummary.is_lower_horizon_only always True (canonical).
  63. OneAPIHistorySummary.is_lower_horizon_only always True (degraded).
  64. OneAPIHistorySummary.is_lower_horizon_only always True (unavailable/None).
  65. TopologyHistoryEntry has to_dict() method.
  66. TopologyHistoryEntry.to_dict() returns a dict.
  67. TopologyHistoryEntry.to_dict() contains "readiness_label" key.
  68. TopologyHistoryEntry.to_dict() contains "is_authoritative" key.
  69. TopologyHistoryEntry.to_dict() contains "change_kind" key.
  70. TopologyHistoryEntry.to_dict() contains "oneapi_summary" key.
  71. TopologyHistoryEntry.to_dict()["oneapi_summary"]["is_lower_horizon_only"] == True.
  72. TopologyHistoryEntry has to_json() method.
  73. TopologyHistoryEntry.to_json() returns a JSON string.
  74. TopologySnapshot has to_dict() method.
  75. TopologySnapshot.to_dict()["oneapi_is_lower_horizon_only"] == True.
  76. TopologySnapshot has to_json() method.
  77. TopologyHistoryBuffer default max_size == 100.
  78. TopologyHistoryBuffer starts empty.
  79. TopologyHistoryBuffer add_entry increases len by 1.
  80. TopologyHistoryBuffer.latest returns most recent entry.
  81. TopologyHistoryBuffer.oldest returns first entry.
  82. TopologyHistoryBuffer evicts oldest entry when full.
  83. TopologyHistoryBuffer.clear() empties the buffer.
  84. TopologyHistoryBuffer.to_list() returns list of dicts.
  85. compare_snapshots(None, None) returns dict with any_change=False.
  86. compare_snapshots: readiness_changed=True when labels differ.
  87. compare_snapshots: readiness_changed=False when labels same.
  88. compare_snapshots: authority_changed=True when authority flips.
  89. compare_snapshots: provider_changed=True when provider_id differs.
  90. compare_snapshots: readiness_transition record present when readiness changed.
  91. compare_snapshots: authority_change record present when authority changed.
  92. compare_snapshots: routing_change record present when provider changed.
  93. compare_snapshots: ReadinessTransitionRecord.became_authoritative=False
      when transitioning to degraded.
  94. compare_snapshots: ReadinessTransitionRecord.transition_note mentions NOT
      authoritative when transitioning into non-authoritative state.
  95. stability_summary on empty buffer: overall_stability == "unknown".
  96. stability_summary on all-canonical buffer: overall_stability == "stable".
  97. stability_summary on mixed buffer: stability_ratio < 1.0.
  98. stability_summary: non_authoritative_count counts correctly.
  99. stability_summary: source_authority == TOPOLOGY_HISTORY_AUTHORITY.
  100. Integration: full pipeline from view-model → layout → inspector → recorder.
"""

from __future__ import annotations

import json
import sys
import types
import importlib

import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal mock objects
# ---------------------------------------------------------------------------


def _make_readiness_detail(
    label="canonical",
    is_authoritative=True,
    is_degraded=False,
    is_partial=False,
    is_unavailable=False,
    degraded_reason=None,
):
    obj = types.SimpleNamespace()
    obj.readiness_label = label
    obj.is_authoritative = is_authoritative
    obj.is_degraded = is_degraded
    obj.is_partial = is_partial
    obj.is_unavailable = is_unavailable
    obj.degraded_reason = degraded_reason
    return obj


def _make_oneapi_detail(status_label="present"):
    obj = types.SimpleNamespace()
    obj.is_lower_horizon_only = True
    obj.oneapi_status_label = status_label
    return obj


def _make_routing_detail(provider_id="openai", routing_authority_source="TopologyRoutePlan"):
    obj = types.SimpleNamespace()
    obj.provider_id = provider_id
    obj.routing_authority_source = routing_authority_source
    return obj


def _make_node(node_id="n1", kind_value="primary_provider", is_authoritative=True, provider_id=None):
    obj = types.SimpleNamespace()
    obj.node_id = node_id
    obj.kind = types.SimpleNamespace(value=kind_value)
    obj.is_authoritative = is_authoritative
    obj.provider_id = provider_id
    return obj


def _make_layer(nodes=None):
    obj = types.SimpleNamespace()
    obj.nodes = nodes or []
    return obj


def _make_report(
    readiness_label="canonical",
    is_authoritative=True,
    is_degraded=False,
    is_partial=False,
    is_unavailable=False,
    with_oneapi=True,
    provider_id="openai",
    routing_source="TopologyRoutePlan",
    lower_horizon_nodes=None,
):
    obj = types.SimpleNamespace()
    obj.readiness = _make_readiness_detail(
        label=readiness_label,
        is_authoritative=is_authoritative,
        is_degraded=is_degraded,
        is_partial=is_partial,
        is_unavailable=is_unavailable,
    )
    obj.oneapi = _make_oneapi_detail() if with_oneapi else None
    obj.routing = _make_routing_detail(
        provider_id=provider_id,
        routing_authority_source=routing_source,
    )
    obj.lower_horizon_nodes = lower_horizon_nodes if lower_horizon_nodes is not None else (
        [_make_node("oneapi_node", "oneapi_horizon")] if with_oneapi else []
    )
    obj.nodes = []
    obj.relations = []
    obj.primary_nodes = []
    obj.support_nodes = []
    return obj


def _make_layout(
    readiness_label="canonical",
    is_authoritative=True,
    is_degraded=False,
    is_partial=False,
    is_unavailable=False,
    with_oneapi_node=True,
    provider_id="openai",
):
    obj = types.SimpleNamespace()
    obj.readiness_label = readiness_label
    obj.is_authoritative = is_authoritative
    obj.is_degraded = is_degraded
    obj.is_partial = is_partial
    obj.is_unavailable = is_unavailable

    primary_node = _make_node(
        node_id="primary_provider_node",
        kind_value="primary_provider",
        is_authoritative=is_authoritative,
        provider_id=provider_id,
    )
    obj.primary_layer = _make_layer(nodes=[primary_node])
    obj.support_layer = _make_layer(nodes=[])
    if with_oneapi_node:
        oneapi_node = _make_node("oneapi_node", "oneapi_horizon", False, None)
        obj.lower_horizon_layer = _make_layer(nodes=[oneapi_node])
    else:
        obj.lower_horizon_layer = _make_layer(nodes=[])
    obj.relations = []
    return obj


def _make_view_model(
    readiness_label="canonical",
    is_canonical=True,
    is_degraded=False,
    is_partial=False,
    is_unavailable=False,
    provider_id="openai",
    routing_authority_source="TopologyRoutePlan",
    with_oneapi=True,
):
    obj = types.SimpleNamespace()
    obj.readiness_label = readiness_label
    obj.is_canonical = is_canonical
    obj.is_degraded = is_degraded
    obj.is_partial = is_partial
    obj.is_unavailable = is_unavailable
    obj.provider_id = provider_id
    obj.routing_authority_source = routing_authority_source
    obj.oneapi_summary = types.SimpleNamespace() if with_oneapi else None
    obj.provider_routing = types.SimpleNamespace()
    return obj


# ---------------------------------------------------------------------------
# Imports
# ---------------------------------------------------------------------------

# Test 1: module importable
def test_01_module_importable():
    import windows_client.status_board_v2.topology_history as mod
    assert mod is not None


# Test 2: TopologyHistoryRecorder importable
def test_02_recorder_importable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert TopologyHistoryRecorder is not None


# Test 3: TOPOLOGY_HISTORY_AUTHORITY importable
def test_03_authority_sentinel_importable():
    from windows_client.status_board_v2.topology_history import TOPOLOGY_HISTORY_AUTHORITY
    assert TOPOLOGY_HISTORY_AUTHORITY is not None


# Test 4: TopologyHistoryRecorder importable from package __all__
def test_04_recorder_importable_from_package_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologyHistoryRecorder" in pkg.__all__
    assert hasattr(pkg, "TopologyHistoryRecorder")


# Test 5: TOPOLOGY_HISTORY_AUTHORITY importable from package __all__
def test_05_authority_in_package_all():
    import windows_client.status_board_v2 as pkg
    assert "TOPOLOGY_HISTORY_AUTHORITY" in pkg.__all__
    assert hasattr(pkg, "TOPOLOGY_HISTORY_AUTHORITY")


# Test 6: TopologyChangeKind in __all__
def test_06_change_kind_in_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologyChangeKind" in pkg.__all__
    assert hasattr(pkg, "TopologyChangeKind")


# Test 7: ReadinessTransitionRecord in __all__
def test_07_readiness_transition_record_in_all():
    import windows_client.status_board_v2 as pkg
    assert "ReadinessTransitionRecord" in pkg.__all__


# Test 8: AuthorityChangeRecord in __all__
def test_08_authority_change_record_in_all():
    import windows_client.status_board_v2 as pkg
    assert "AuthorityChangeRecord" in pkg.__all__


# Test 9: RoutingChangeRecord in __all__
def test_09_routing_change_record_in_all():
    import windows_client.status_board_v2 as pkg
    assert "RoutingChangeRecord" in pkg.__all__


# Test 10: OneAPIHistorySummary in __all__
def test_10_oneapi_history_summary_in_all():
    import windows_client.status_board_v2 as pkg
    assert "OneAPIHistorySummary" in pkg.__all__


# Test 11: TopologyHistoryEntry in __all__
def test_11_history_entry_in_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologyHistoryEntry" in pkg.__all__


# Test 12: TopologySnapshot in __all__
def test_12_snapshot_in_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologySnapshot" in pkg.__all__


# Test 13: TopologyHistoryBuffer in __all__
def test_13_buffer_in_all():
    import windows_client.status_board_v2 as pkg
    assert "TopologyHistoryBuffer" in pkg.__all__


# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

# Test 14: authority is non-empty string
def test_14_authority_nonempty_string():
    from windows_client.status_board_v2.topology_history import TOPOLOGY_HISTORY_AUTHORITY
    assert isinstance(TOPOLOGY_HISTORY_AUTHORITY, str)
    assert len(TOPOLOGY_HISTORY_AUTHORITY) > 0


# Test 15: authority contains "TopologyHistoryRecorder"
def test_15_authority_contains_recorder_name():
    from windows_client.status_board_v2.topology_history import TOPOLOGY_HISTORY_AUTHORITY
    assert "TopologyHistoryRecorder" in TOPOLOGY_HISTORY_AUTHORITY


# ---------------------------------------------------------------------------
# Instantiation
# ---------------------------------------------------------------------------

# Test 16: TopologyHistoryRecorder() instantiates without error
def test_16_recorder_instantiates():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    assert recorder is not None


# Test 17: has record_from_inspection_report
def test_17_has_record_from_inspection_report():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "record_from_inspection_report")


# Test 18: has record_from_layout
def test_18_has_record_from_layout():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "record_from_layout")


# Test 19: has record_from_view_model
def test_19_has_record_from_view_model():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "record_from_view_model")


# Test 20: has snapshot_from_inspection_report
def test_20_has_snapshot_from_inspection_report():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "snapshot_from_inspection_report")


# Test 21: has snapshot_from_layout
def test_21_has_snapshot_from_layout():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "snapshot_from_layout")


# Test 22: has snapshot_from_view_model
def test_22_has_snapshot_from_view_model():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "snapshot_from_view_model")


# Test 23: has compare_snapshots
def test_23_has_compare_snapshots():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "compare_snapshots")


# Test 24: has stability_summary
def test_24_has_stability_summary():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    assert hasattr(TopologyHistoryRecorder(), "stability_summary")


# ---------------------------------------------------------------------------
# None handling
# ---------------------------------------------------------------------------

# Test 25: record_from_inspection_report(None) returns None
def test_25_record_from_inspection_report_none():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    result = recorder.record_from_inspection_report(None)
    assert result is None


# Test 26: record_from_layout(None) returns None
def test_26_record_from_layout_none():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    result = recorder.record_from_layout(None)
    assert result is None


# Test 27: record_from_view_model(None) returns None
def test_27_record_from_view_model_none():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    result = recorder.record_from_view_model(None)
    assert result is None


# Test 28: snapshot_from_inspection_report(None) returns TopologySnapshot
def test_28_snapshot_from_inspection_report_none_returns_snapshot():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologySnapshot,
    )
    recorder = TopologyHistoryRecorder()
    snap = recorder.snapshot_from_inspection_report(None)
    assert isinstance(snap, TopologySnapshot)


# Test 29: snapshot_from_inspection_report(None) returns unavailable snapshot
def test_29_snapshot_from_inspection_report_none_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap = recorder.snapshot_from_inspection_report(None)
    assert snap.readiness_label == "unavailable"


# Test 30: snapshot_from_layout(None) returns unavailable
def test_30_snapshot_from_layout_none_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap = recorder.snapshot_from_layout(None)
    assert snap.readiness_label == "unavailable"
    assert snap.is_unavailable is True


# Test 31: snapshot_from_view_model(None) returns unavailable
def test_31_snapshot_from_view_model_none_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap = recorder.snapshot_from_view_model(None)
    assert snap.readiness_label == "unavailable"
    assert snap.is_unavailable is True


# Test 32: unavailable snapshot is_unavailable == True
def test_32_unavailable_snapshot_is_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.is_unavailable is True


# Test 33: unavailable snapshot is_authoritative == False
def test_33_unavailable_snapshot_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.is_authoritative is False


# Test 34: unavailable snapshot readiness_label == "unavailable"
def test_34_unavailable_snapshot_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.readiness_label == "unavailable"


# Test 35: unavailable snapshot stability_indicator == "unavailable"
def test_35_unavailable_snapshot_stability_indicator():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.stability_indicator == "unavailable"


# Test 36: unavailable snapshot oneapi_is_lower_horizon_only == True
def test_36_unavailable_snapshot_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(None)
    assert snap.oneapi_is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# Canonical report
# ---------------------------------------------------------------------------

# Test 37: canonical report → record is TopologyHistoryEntry
def test_37_canonical_record_from_report():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryEntry,
    )
    report = _make_report()
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert isinstance(entry, TopologyHistoryEntry)


# Test 38: canonical report → readiness_label == "canonical"
def test_38_canonical_entry_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert entry.readiness_label == "canonical"


# Test 39: canonical report → is_authoritative == True
def test_39_canonical_entry_is_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert entry.is_authoritative is True


# Test 40: canonical report → is_degraded == False
def test_40_canonical_entry_not_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert entry.is_degraded is False


# Test 41: canonical report → oneapi_summary.is_lower_horizon_only == True
def test_41_canonical_entry_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert entry.oneapi_summary is not None
    assert entry.oneapi_summary.is_lower_horizon_only is True


# Test 42: canonical report → source_authority is TOPOLOGY_HISTORY_AUTHORITY
def test_42_canonical_entry_source_authority():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TOPOLOGY_HISTORY_AUTHORITY,
    )
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert entry.source_authority == TOPOLOGY_HISTORY_AUTHORITY


# Test 43: canonical report → snapshot is_authoritative == True
def test_43_canonical_snapshot_is_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert snap.is_authoritative is True


# Test 44: canonical report → snapshot readiness_label == "canonical"
def test_44_canonical_snapshot_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert snap.readiness_label == "canonical"


# Test 45: canonical report → snapshot stability_indicator == "stable"
def test_45_canonical_snapshot_stability_stable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert snap.stability_indicator == "stable"


# Test 46: canonical report → snapshot oneapi_is_lower_horizon_only == True
def test_46_canonical_snapshot_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert snap.oneapi_is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# Degraded report
# ---------------------------------------------------------------------------

# Test 47: degraded report → record is TopologyHistoryEntry
def test_47_degraded_record_from_report():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryEntry,
    )
    report = _make_report(
        readiness_label="degraded",
        is_authoritative=False,
        is_degraded=True,
    )
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert isinstance(entry, TopologyHistoryEntry)


# Test 48: degraded report → entry.readiness_label == "degraded"
def test_48_degraded_entry_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.readiness_label == "degraded"


# Test 49: degraded report → entry.is_authoritative == False
def test_49_degraded_entry_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_authoritative is False


# Test 50: degraded report → entry.is_degraded == True
def test_50_degraded_entry_is_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_degraded is True


# Test 51: degraded report → change_kind == "topology_degraded"
def test_51_degraded_entry_change_kind():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyChangeKind,
    )
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.change_kind == TopologyChangeKind.topology_degraded


# Test 52: degraded snapshot → stability_indicator == "degraded"
def test_52_degraded_snapshot_stability():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.stability_indicator == "degraded"


# Test 53: degraded snapshot → is_authoritative == False
def test_53_degraded_snapshot_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.is_authoritative is False


# Test 54: degraded entry → oneapi_summary.is_lower_horizon_only == True
def test_54_degraded_entry_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary is not None
    assert entry.oneapi_summary.is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# Partial report
# ---------------------------------------------------------------------------

# Test 55: partial entry readiness_label == "partial"
def test_55_partial_entry_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="partial", is_authoritative=False, is_partial=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.readiness_label == "partial"


# Test 56: partial entry is_authoritative == False
def test_56_partial_entry_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="partial", is_authoritative=False, is_partial=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_authoritative is False


# Test 57: partial entry is_partial == True
def test_57_partial_entry_is_partial():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="partial", is_authoritative=False, is_partial=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_partial is True


# Test 58: partial snapshot → stability_indicator == "partial"
def test_58_partial_snapshot_stability():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="partial", is_authoritative=False, is_partial=True)
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(report)
    assert snap.stability_indicator == "partial"


# ---------------------------------------------------------------------------
# Unavailable report
# ---------------------------------------------------------------------------

# Test 59: unavailable entry readiness_label == "unavailable"
def test_59_unavailable_entry_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(
        readiness_label="unavailable",
        is_authoritative=False,
        is_unavailable=True,
    )
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.readiness_label == "unavailable"


# Test 60: unavailable entry is_unavailable == True
def test_60_unavailable_entry_is_unavailable():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(
        readiness_label="unavailable",
        is_authoritative=False,
        is_unavailable=True,
    )
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_unavailable is True


# Test 61: unavailable entry is_authoritative == False
def test_61_unavailable_entry_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(
        readiness_label="unavailable",
        is_authoritative=False,
        is_unavailable=True,
    )
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.is_authoritative is False


# ---------------------------------------------------------------------------
# OneAPIHistorySummary invariants
# ---------------------------------------------------------------------------

# Test 62: OneAPIHistorySummary is_lower_horizon_only always True (canonical)
def test_62_oneapi_summary_lower_horizon_canonical():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, OneAPIHistorySummary,
    )
    report = _make_report()
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary is not None
    assert isinstance(entry.oneapi_summary, OneAPIHistorySummary)
    assert entry.oneapi_summary.is_lower_horizon_only is True


# Test 63: OneAPIHistorySummary is_lower_horizon_only always True (degraded)
def test_63_oneapi_summary_lower_horizon_degraded():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary.is_lower_horizon_only is True


# Test 64: OneAPIHistorySummary is_lower_horizon_only always True (None oneapi)
def test_64_oneapi_summary_lower_horizon_no_oneapi():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    report = _make_report(with_oneapi=False)
    entry = TopologyHistoryRecorder().record_from_inspection_report(report)
    assert entry.oneapi_summary is not None
    assert entry.oneapi_summary.is_lower_horizon_only is True


# ---------------------------------------------------------------------------
# TopologyHistoryEntry serialisation
# ---------------------------------------------------------------------------

# Test 65: has to_dict()
def test_65_entry_has_to_dict():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert hasattr(entry, "to_dict")


# Test 66: to_dict() returns dict
def test_66_entry_to_dict_returns_dict():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    d = entry.to_dict()
    assert isinstance(d, dict)


# Test 67: to_dict() contains "readiness_label"
def test_67_entry_to_dict_has_readiness_label():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_dict()
    assert "readiness_label" in d


# Test 68: to_dict() contains "is_authoritative"
def test_68_entry_to_dict_has_is_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_dict()
    assert "is_authoritative" in d


# Test 69: to_dict() contains "change_kind"
def test_69_entry_to_dict_has_change_kind():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_dict()
    assert "change_kind" in d


# Test 70: to_dict() contains "oneapi_summary"
def test_70_entry_to_dict_has_oneapi_summary():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_dict()
    assert "oneapi_summary" in d


# Test 71: to_dict()["oneapi_summary"]["is_lower_horizon_only"] == True
def test_71_entry_to_dict_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_dict()
    assert d["oneapi_summary"]["is_lower_horizon_only"] is True


# Test 72: has to_json()
def test_72_entry_has_to_json():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    assert hasattr(entry, "to_json")


# Test 73: to_json() returns JSON string
def test_73_entry_to_json_is_string():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    j = TopologyHistoryRecorder().record_from_inspection_report(_make_report()).to_json()
    assert isinstance(j, str)
    parsed = json.loads(j)
    assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# TopologySnapshot serialisation
# ---------------------------------------------------------------------------

# Test 74: snapshot has to_dict()
def test_74_snapshot_has_to_dict():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert hasattr(snap, "to_dict")


# Test 75: snapshot to_dict()["oneapi_is_lower_horizon_only"] == True
def test_75_snapshot_to_dict_oneapi_lower_horizon():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    d = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report()).to_dict()
    assert d["oneapi_is_lower_horizon_only"] is True


# Test 76: snapshot has to_json()
def test_76_snapshot_has_to_json():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    snap = TopologyHistoryRecorder().snapshot_from_inspection_report(_make_report())
    assert hasattr(snap, "to_json")
    j = snap.to_json()
    assert isinstance(j, str)
    assert json.loads(j)["readiness_label"] == "canonical"


# ---------------------------------------------------------------------------
# TopologyHistoryBuffer
# ---------------------------------------------------------------------------

# Test 77: default max_size == 100
def test_77_buffer_default_max_size():
    from windows_client.status_board_v2.topology_history import TopologyHistoryBuffer
    buf = TopologyHistoryBuffer()
    assert buf.max_size == 100


# Test 78: buffer starts empty
def test_78_buffer_starts_empty():
    from windows_client.status_board_v2.topology_history import TopologyHistoryBuffer
    buf = TopologyHistoryBuffer()
    assert len(buf) == 0
    assert buf.latest is None


# Test 79: add_entry increases len by 1
def test_79_buffer_add_entry():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer()
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    buf.add_entry(entry)
    assert len(buf) == 1


# Test 80: latest returns most recent entry
def test_80_buffer_latest():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    e1 = recorder.record_from_inspection_report(_make_report())
    e2 = recorder.record_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    buf.add_entry(e1)
    buf.add_entry(e2)
    assert buf.latest is e2


# Test 81: oldest returns first entry
def test_81_buffer_oldest():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    e1 = recorder.record_from_inspection_report(_make_report())
    e2 = recorder.record_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    buf.add_entry(e1)
    buf.add_entry(e2)
    assert buf.oldest is e1


# Test 82: buffer evicts oldest when full
def test_82_buffer_eviction():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer(max_size=2)
    recorder = TopologyHistoryRecorder()
    e1 = recorder.record_from_inspection_report(_make_report())
    e2 = recorder.record_from_inspection_report(_make_report())
    e3 = recorder.record_from_inspection_report(_make_report())
    buf.add_entry(e1)
    buf.add_entry(e2)
    buf.add_entry(e3)
    assert len(buf) == 2
    assert buf.oldest is e2  # e1 was evicted
    assert buf.latest is e3


# Test 83: clear() empties the buffer
def test_83_buffer_clear():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer()
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    buf.add_entry(entry)
    buf.clear()
    assert len(buf) == 0
    assert buf.latest is None


# Test 84: to_list() returns list of dicts
def test_84_buffer_to_list():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryBuffer, TopologyHistoryRecorder,
    )
    buf = TopologyHistoryBuffer()
    entry = TopologyHistoryRecorder().record_from_inspection_report(_make_report())
    buf.add_entry(entry)
    lst = buf.to_list()
    assert isinstance(lst, list)
    assert len(lst) == 1
    assert isinstance(lst[0], dict)


# ---------------------------------------------------------------------------
# compare_snapshots
# ---------------------------------------------------------------------------

# Test 85: compare_snapshots(None, None) — no exception, any_change False
def test_85_compare_snapshots_none_none():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    result = TopologyHistoryRecorder().compare_snapshots(None, None)
    assert isinstance(result, dict)
    assert result["any_change"] is False


# Test 86: readiness_changed=True when labels differ
def test_86_compare_readiness_changed():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["readiness_changed"] is True


# Test 87: readiness_changed=False when labels same
def test_87_compare_readiness_unchanged():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(_make_report())
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["readiness_changed"] is False


# Test 88: authority_changed=True when authority flips
def test_88_compare_authority_changed():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["authority_changed"] is True


# Test 89: provider_changed=True when provider_id differs
def test_89_compare_provider_changed():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report(provider_id=None))
    snap_b = recorder.snapshot_from_inspection_report(_make_report())
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["provider_changed"] is True


# Test 90: readiness_transition record present when readiness changed
def test_90_compare_readiness_transition_present():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, ReadinessTransitionRecord,
    )
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["readiness_transition"] is not None
    assert isinstance(diff["readiness_transition"], ReadinessTransitionRecord)


# Test 91: authority_change record present when authority changed
def test_91_compare_authority_change_present():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, AuthorityChangeRecord,
    )
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["authority_change"] is not None
    assert isinstance(diff["authority_change"], AuthorityChangeRecord)


# Test 92: routing_change present when provider changes
def test_92_compare_routing_change_present():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, RoutingChangeRecord,
    )
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_view_model(_make_view_model(provider_id="openai"))
    snap_b = recorder.snapshot_from_view_model(_make_view_model(provider_id="anthropic"))
    diff = recorder.compare_snapshots(snap_a, snap_b)
    assert diff["provider_changed"] is True
    assert diff["routing_change"] is not None
    assert isinstance(diff["routing_change"], RoutingChangeRecord)


# Test 93: ReadinessTransitionRecord.became_authoritative=False
#          when transitioning to degraded
def test_93_transition_became_authoritative_false():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    tr = diff["readiness_transition"]
    assert tr.became_authoritative is False


# Test 94: ReadinessTransitionRecord.transition_note mentions NOT authoritative
def test_94_transition_note_mentions_not_authoritative():
    from windows_client.status_board_v2.topology_history import TopologyHistoryRecorder
    recorder = TopologyHistoryRecorder()
    snap_a = recorder.snapshot_from_inspection_report(_make_report())
    snap_b = recorder.snapshot_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    )
    diff = recorder.compare_snapshots(snap_a, snap_b)
    note = diff["readiness_transition"].transition_note
    assert "NOT" in note or "not" in note.lower() or "fallback" in note.lower()


# ---------------------------------------------------------------------------
# stability_summary
# ---------------------------------------------------------------------------

# Test 95: empty buffer → overall_stability == "unknown"
def test_95_stability_summary_empty():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    summary = TopologyHistoryRecorder().stability_summary(buf)
    assert summary["overall_stability"] == "unknown"
    assert summary["total_entries"] == 0


# Test 96: all-canonical buffer → overall_stability == "stable"
def test_96_stability_summary_all_canonical():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    for _ in range(5):
        buf.add_entry(recorder.record_from_inspection_report(_make_report()))
    summary = recorder.stability_summary(buf)
    assert summary["overall_stability"] == "stable"
    assert summary["stability_ratio"] == 1.0


# Test 97: mixed buffer → stability_ratio < 1.0
def test_97_stability_summary_mixed():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    buf.add_entry(recorder.record_from_inspection_report(_make_report()))
    buf.add_entry(recorder.record_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    ))
    summary = recorder.stability_summary(buf)
    assert summary["stability_ratio"] < 1.0


# Test 98: non_authoritative_count correct
def test_98_stability_summary_non_auth_count():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer,
    )
    buf = TopologyHistoryBuffer()
    recorder = TopologyHistoryRecorder()
    buf.add_entry(recorder.record_from_inspection_report(_make_report()))
    buf.add_entry(recorder.record_from_inspection_report(
        _make_report(readiness_label="degraded", is_authoritative=False, is_degraded=True)
    ))
    summary = recorder.stability_summary(buf)
    assert summary["non_authoritative_count"] == 1
    assert summary["authoritative_count"] == 1


# Test 99: stability_summary source_authority == TOPOLOGY_HISTORY_AUTHORITY
def test_99_stability_summary_source_authority():
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer, TOPOLOGY_HISTORY_AUTHORITY,
    )
    buf = TopologyHistoryBuffer()
    summary = TopologyHistoryRecorder().stability_summary(buf)
    assert summary["source_authority"] == TOPOLOGY_HISTORY_AUTHORITY


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

# Test 100: full pipeline view-model → layout → inspector → recorder
def test_100_integration_full_pipeline():
    """Integration: construct the full PR-9 → PR-11 → PR-13 → PR-14 pipeline."""
    import types as _types
    from windows_client.status_board_v2.topology_history import (
        TopologyHistoryRecorder, TopologyHistoryBuffer, TOPOLOGY_HISTORY_AUTHORITY,
        TopologyHistoryEntry, TopologySnapshot,
    )
    from windows_client.status_board_v2.topology_inspector import TopologyInspector
    from windows_client.status_board_v2.topology_layout import build_constellation_layout

    # Build a minimal view-model (simulates PR-9 adapter output)
    class _ProviderRouting:
        selected = "openai"
        vendor = "openai"
        legacy = False
        available = True
        reason = "primary_route"

    class _OneAPIHorizon:
        provider_id = "oneapi-provider"
        system_layer = "OneAPI"
        available = True

    class _ReadinessState:
        value = "canonical"
        def __str__(self):
            return self.value

    class _VM:
        readiness_state = _ReadinessState()
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
        provider_routing = _ProviderRouting()
        oneapi_horizon = _OneAPIHorizon()
        oneapi_summary = _types.SimpleNamespace()

    vm = _VM()

    # PR-11: build layout
    layout = build_constellation_layout(vm)
    assert layout is not None

    # PR-13: build inspection report
    inspector = TopologyInspector()
    report = inspector.inspect_layout(layout)
    assert report is not None
    assert report.readiness.readiness_label == "canonical"

    # PR-14: record history entry
    recorder = TopologyHistoryRecorder()
    entry = recorder.record_from_inspection_report(report)
    assert isinstance(entry, TopologyHistoryEntry)
    assert entry.readiness_label == "canonical"
    assert entry.is_authoritative is True
    assert entry.oneapi_summary.is_lower_horizon_only is True
    assert entry.source_authority == TOPOLOGY_HISTORY_AUTHORITY

    # PR-14: take snapshot
    snap = recorder.snapshot_from_inspection_report(report)
    assert isinstance(snap, TopologySnapshot)
    assert snap.readiness_label == "canonical"
    assert snap.stability_indicator == "stable"
    assert snap.oneapi_is_lower_horizon_only is True

    # PR-14: buffer
    buf = TopologyHistoryBuffer(max_size=20)
    buf.add_entry(entry)
    assert len(buf) == 1
    assert buf.latest is entry

    # PR-14: stability summary
    summary = recorder.stability_summary(buf)
    assert summary["overall_stability"] == "stable"
    assert summary["stability_ratio"] == 1.0
    assert summary["source_authority"] == TOPOLOGY_HISTORY_AUTHORITY
