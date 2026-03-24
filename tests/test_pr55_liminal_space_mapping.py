#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr55_liminal_space_mapping.py
=========================================
PR-5 — Formalize Liminal Space as Execution/Simulation Field

Validates:
  1.  LocalChainView: default construction succeeds.
  2.  LocalChainView: to_dict produces expected keys.
  3.  LocalChainView: to_dict keys do not include prohibited status-board fields.
  4.  LocalChainView: is_active False for zero executions.
  5.  LocalChainView: is_active True for positive total_executions.
  6.  LocalChainView: to_dict round-trip is stable.
  7.  CrossDeviceChainView: default construction succeeds.
  8.  CrossDeviceChainView: to_dict produces expected keys.
  9.  CrossDeviceChainView: to_dict keys do not include prohibited status-board fields.
 10.  CrossDeviceChainView: is_active False for zero executions.
 11.  CrossDeviceChainView: is_active True for positive total_executions.
 12.  CrossDeviceChainView: to_dict round-trip is stable.
 13.  SimulationSummary: default construction succeeds.
 14.  SimulationSummary: to_dict produces expected keys.
 15.  SimulationSummary: to_dict keys do not include prohibited status-board fields.
 16.  SimulationSummary: is_active False by default.
 17.  SimulationSummary: simulation_kind defaults to "none".
 18.  SimulationSummary: summary_id is a non-empty string.
 19.  SimulationSummary: to_dict round-trip is stable.
 20.  LiminalSpaceMap: default construction succeeds.
 21.  LiminalSpaceMap: to_dict contains "local_chain", "cross_device_chain", "simulation_summary".
 22.  LiminalSpaceMap: to_dict does NOT contain prohibited provider/model keys.
 23.  LiminalSpaceMap: map_id is a non-empty string.
 24.  LiminalSpaceMap: to_dict round-trip is stable.
 25.  build_local_chain_view: None input returns zero-state view.
 26.  build_local_chain_view: empty dict returns zero-state view.
 27.  build_local_chain_view: snapshot dict sets total_executions.
 28.  build_local_chain_view: snapshot dict sets canonical_executions.
 29.  build_local_chain_view: snapshot dict sets legacy_executions.
 30.  build_local_chain_view: snapshot dict sets canonical_chain_order.
 31.  build_local_chain_view: is_active True when total > 0.
 32.  build_local_chain_view: is_active False when total == 0.
 33.  build_local_chain_view: extracts last_step from most recent record.
 34.  build_local_chain_view: extracts last_task_id from most recent record.
 35.  build_cross_device_chain_view: None input returns zero-state view.
 36.  build_cross_device_chain_view: empty dict returns zero-state view.
 37.  build_cross_device_chain_view: snapshot dict sets total_executions.
 38.  build_cross_device_chain_view: snapshot dict sets canonical_executions.
 39.  build_cross_device_chain_view: snapshot dict sets legacy_executions.
 40.  build_cross_device_chain_view: snapshot dict sets canonical_chain_order.
 41.  build_cross_device_chain_view: is_active True when total > 0.
 42.  build_cross_device_chain_view: is_active False when total == 0.
 43.  build_cross_device_chain_view: extracts last_step from most recent record.
 44.  build_cross_device_chain_view: extracts last_device_id from most recent record.
 45.  build_simulation_summary: default is inactive / kind=none.
 46.  build_simulation_summary: is_active sets field correctly.
 47.  build_simulation_summary: simulation_kind="speculative" accepted.
 48.  build_simulation_summary: simulation_kind="sandbox" accepted.
 49.  build_simulation_summary: unknown kind coerces to "none".
 50.  build_simulation_summary: candidate_paths preserved.
 51.  build_simulation_summary: committed_path sets is_committed=True.
 52.  build_simulation_summary: None committed_path → is_committed=False.
 53.  build_simulation_summary: step_count stored correctly.
 54.  build_simulation_summary: scenario_label stored correctly.
 55.  build_liminal_space_map: None inputs produce empty views.
 56.  build_liminal_space_map: local_snapshot_dict wires to local_chain.
 57.  build_liminal_space_map: cross_device_snapshot_dict wires to cross_device_chain.
 58.  build_liminal_space_map: simulation_summary wires to simulation_summary field.
 59.  build_liminal_space_map: None simulation_summary produces inactive SimulationSummary.
 60.  get_liminal_space_map: returns a LiminalSpaceMap.
 61.  get_liminal_space_map: local_chain is a LocalChainView.
 62.  get_liminal_space_map: cross_device_chain is a CrossDeviceChainView.
 63.  get_liminal_space_map: simulation_summary is a SimulationSummary.
 64.  Boundary: LocalChainView.to_dict has no "primary_model_id".
 65.  Boundary: LocalChainView.to_dict has no "support_model_ids".
 66.  Boundary: LocalChainView.to_dict has no "active_weights".
 67.  Boundary: CrossDeviceChainView.to_dict has no "route_reason".
 68.  Boundary: CrossDeviceChainView.to_dict has no "routing_authority".
 69.  Boundary: CrossDeviceChainView.to_dict has no "vendor_source".
 70.  Boundary: SimulationSummary.to_dict has no "primary_model_id".
 71.  Boundary: SimulationSummary.to_dict has no "presence_intensity".
 72.  Boundary: SimulationSummary.to_dict has no "topology_role".
 73.  Boundary: LiminalSpaceMap.to_dict has no "primary_model_id".
 74.  Boundary: LiminalSpaceMap.to_dict has no "support_model_ids".
 75.  Boundary: LiminalSpaceMap.to_dict has no "routing_authority".
 76.  Boundary: LiminalSpaceMap.to_dict has no "presence_intensity".
 77.  Boundary: LiminalSpaceMap.to_dict has no "coherence".
 78.  Boundary: LiminalSpaceMap.to_dict has no "oneapi_source".
 79.  LiminalSurface: render returns non-empty string.
 80.  LiminalSurface: render output does not contain "provider_list".
 81.  LiminalSurface: render output does not contain "primary_model_id".
 82.  LiminalSurface: render output contains local/cross_device/simulation panel headers.
 83.  LiminalSurface: _render_unavailable returns non-empty string.
 84.  LiminalSurface: _render_unavailable does not contain "primary_model_id".
 85.  docs/LIMINAL_SPACE_MAPPING.md exists.
 86.  docs/SANDBOX_SIMULATION_PROJECTION.md exists.
 87.  docs/LIMINAL_SPACE_MAPPING.md mentions three allowed content classes.
 88.  docs/SANDBOX_SIMULATION_PROJECTION.md mentions SimulationSummary.
 89.  core/liminal_space_mapping.py module docstring mentions three content classes.
 90.  LiminalSpaceMap frozen=True (immutable).
 91.  LocalChainView frozen=True (immutable).
 92.  CrossDeviceChainView frozen=True (immutable).
 93.  SimulationSummary frozen=True (immutable).
 94.  build_liminal_space_map: to_dict is JSON-serialisable.
 95.  get_liminal_space_map: returns consistent map_id per call (different instances).
"""

from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Dict

import pytest

from core.liminal_space_mapping import (
    CrossDeviceChainView,
    LiminalSpaceMap,
    LocalChainView,
    SimulationSummary,
    build_cross_device_chain_view,
    build_liminal_space_map,
    build_local_chain_view,
    build_simulation_summary,
    get_liminal_space_map,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")

_LOCAL_SNAPSHOT_DICT: Dict[str, Any] = {
    "total_executions": 5,
    "canonical_executions": 4,
    "legacy_executions": 1,
    "canonical_chain_order": [
        "openclawd_dispatch",
        "agent_kernel_plan",
        "command_router_local",
        "local_executor",
        "result_capture",
        "openclawd_feedback",
    ],
    "recent_records": [
        {
            "task_id": "task-abc",
            "steps_completed": [
                "openclawd_dispatch",
                "agent_kernel_plan",
                "command_router_local",
                "local_executor",
                "result_capture",
                "openclawd_feedback",
            ],
            "is_canonical": True,
        }
    ],
    "snapshot_id": "snap-001",
    "timestamp": 1711533600.0,
}

_CD_SNAPSHOT_DICT: Dict[str, Any] = {
    "total_executions": 3,
    "canonical_executions": 2,
    "legacy_executions": 1,
    "canonical_chain_order": [
        "openclawd_dispatch",
        "command_router_cross_device",
        "task_envelope_serialisation",
        "gateway_substrate",
        "remote_executor",
        "result_envelope_merge",
        "openclawd_feedback",
    ],
    "recent_records": [
        {
            "device_id": "device-42",
            "steps_completed": [
                "openclawd_dispatch",
                "command_router_cross_device",
            ],
            "is_canonical": True,
        }
    ],
    "snapshot_id": "snap-002",
    "timestamp": 1711533600.0,
}

_PROHIBITED_FIELDS = [
    "primary_model_id",
    "support_model_ids",
    "active_weights",
    "route_reason",
    "routing_authority",
    "oneapi_source",
    "vendor_source",
    "topology_role",
    "presence_intensity",
    "coherence",
    "collapse_tendency",
    "retreat_tendency",
    "provider_list",
]

# ---------------------------------------------------------------------------
# 1–6: LocalChainView
# ---------------------------------------------------------------------------


class TestLocalChainView:
    def test_default_construction(self):
        v = LocalChainView()
        assert v.total_executions == 0

    def test_to_dict_expected_keys(self):
        v = LocalChainView()
        d = v.to_dict()
        for k in ("total_executions", "canonical_executions", "legacy_executions",
                   "canonical_chain_order", "last_task_id", "last_step",
                   "is_active", "timestamp"):
            assert k in d, f"expected key '{k}' in LocalChainView.to_dict()"

    def test_to_dict_no_prohibited_fields(self):
        v = LocalChainView()
        d = v.to_dict()
        for field in _PROHIBITED_FIELDS:
            assert field not in d, f"prohibited field '{field}' found in LocalChainView.to_dict()"

    def test_is_active_false_default(self):
        v = LocalChainView()
        assert v.is_active is False

    def test_is_active_true_when_executions(self):
        v = LocalChainView(total_executions=1, is_active=True)
        assert v.is_active is True

    def test_to_dict_round_trip_stable(self):
        v = LocalChainView(
            total_executions=3,
            canonical_executions=2,
            legacy_executions=1,
            canonical_chain_order=["a", "b"],
            last_task_id="t1",
            last_step="result_capture",
            is_active=True,
        )
        d = v.to_dict()
        assert d["total_executions"] == 3
        assert d["canonical_executions"] == 2
        assert d["legacy_executions"] == 1
        assert d["canonical_chain_order"] == ["a", "b"]
        assert d["last_task_id"] == "t1"
        assert d["last_step"] == "result_capture"
        assert d["is_active"] is True


# ---------------------------------------------------------------------------
# 7–12: CrossDeviceChainView
# ---------------------------------------------------------------------------


class TestCrossDeviceChainView:
    def test_default_construction(self):
        v = CrossDeviceChainView()
        assert v.total_executions == 0

    def test_to_dict_expected_keys(self):
        v = CrossDeviceChainView()
        d = v.to_dict()
        for k in ("total_executions", "canonical_executions", "legacy_executions",
                   "canonical_chain_order", "last_device_id", "last_step",
                   "is_active", "timestamp"):
            assert k in d, f"expected key '{k}' in CrossDeviceChainView.to_dict()"

    def test_to_dict_no_prohibited_fields(self):
        v = CrossDeviceChainView()
        d = v.to_dict()
        for field in _PROHIBITED_FIELDS:
            assert field not in d, f"prohibited field '{field}' in CrossDeviceChainView.to_dict()"

    def test_is_active_false_default(self):
        v = CrossDeviceChainView()
        assert v.is_active is False

    def test_is_active_true_when_executions(self):
        v = CrossDeviceChainView(total_executions=2, is_active=True)
        assert v.is_active is True

    def test_to_dict_round_trip_stable(self):
        v = CrossDeviceChainView(
            total_executions=5,
            canonical_executions=3,
            legacy_executions=2,
            last_device_id="dev-9",
            last_step="gateway_substrate",
            is_active=True,
        )
        d = v.to_dict()
        assert d["total_executions"] == 5
        assert d["last_device_id"] == "dev-9"
        assert d["last_step"] == "gateway_substrate"
        assert d["is_active"] is True


# ---------------------------------------------------------------------------
# 13–19: SimulationSummary
# ---------------------------------------------------------------------------


class TestSimulationSummary:
    def test_default_construction(self):
        s = SimulationSummary()
        assert s.is_active is False

    def test_to_dict_expected_keys(self):
        s = SimulationSummary()
        d = s.to_dict()
        for k in ("summary_id", "is_active", "simulation_kind", "candidate_paths",
                   "committed_path", "scenario_label", "step_count",
                   "is_committed", "timestamp"):
            assert k in d, f"expected key '{k}' in SimulationSummary.to_dict()"

    def test_to_dict_no_prohibited_fields(self):
        s = SimulationSummary()
        d = s.to_dict()
        for field in _PROHIBITED_FIELDS:
            assert field not in d, f"prohibited field '{field}' in SimulationSummary.to_dict()"

    def test_is_active_false_default(self):
        s = SimulationSummary()
        assert s.is_active is False

    def test_simulation_kind_default_none(self):
        s = SimulationSummary()
        assert s.simulation_kind == "none"

    def test_summary_id_non_empty(self):
        s = SimulationSummary()
        assert isinstance(s.summary_id, str) and len(s.summary_id) > 0

    def test_to_dict_round_trip_stable(self):
        s = SimulationSummary(
            is_active=True,
            simulation_kind="speculative",
            candidate_paths=["local", "cross_device"],
            committed_path=None,
            step_count=3,
            is_committed=False,
        )
        d = s.to_dict()
        assert d["is_active"] is True
        assert d["simulation_kind"] == "speculative"
        assert d["candidate_paths"] == ["local", "cross_device"]
        assert d["committed_path"] is None
        assert d["step_count"] == 3
        assert d["is_committed"] is False


# ---------------------------------------------------------------------------
# 20–24: LiminalSpaceMap
# ---------------------------------------------------------------------------


class TestLiminalSpaceMap:
    def test_default_construction(self):
        m = LiminalSpaceMap()
        assert isinstance(m.local_chain, LocalChainView)
        assert isinstance(m.cross_device_chain, CrossDeviceChainView)
        assert isinstance(m.simulation_summary, SimulationSummary)

    def test_to_dict_contains_three_classes(self):
        m = LiminalSpaceMap()
        d = m.to_dict()
        assert "local_chain" in d
        assert "cross_device_chain" in d
        assert "simulation_summary" in d

    def test_to_dict_no_prohibited_keys_at_top_level(self):
        m = LiminalSpaceMap()
        d = m.to_dict()
        for field in _PROHIBITED_FIELDS:
            assert field not in d, f"prohibited key '{field}' at top-level of LiminalSpaceMap.to_dict()"

    def test_map_id_non_empty(self):
        m = LiminalSpaceMap()
        assert isinstance(m.map_id, str) and len(m.map_id) > 0

    def test_to_dict_round_trip_stable(self):
        m = LiminalSpaceMap()
        d = m.to_dict()
        assert "map_id" in d
        assert "timestamp" in d
        assert isinstance(d["local_chain"], dict)
        assert isinstance(d["cross_device_chain"], dict)
        assert isinstance(d["simulation_summary"], dict)


# ---------------------------------------------------------------------------
# 25–34: build_local_chain_view
# ---------------------------------------------------------------------------


class TestBuildLocalChainView:
    def test_none_returns_zero_state(self):
        v = build_local_chain_view(None)
        assert v.total_executions == 0
        assert v.is_active is False

    def test_empty_dict_returns_zero_state(self):
        v = build_local_chain_view({})
        assert v.total_executions == 0

    def test_sets_total_executions(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.total_executions == 5

    def test_sets_canonical_executions(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.canonical_executions == 4

    def test_sets_legacy_executions(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.legacy_executions == 1

    def test_sets_canonical_chain_order(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.canonical_chain_order[0] == "openclawd_dispatch"
        assert v.canonical_chain_order[-1] == "openclawd_feedback"

    def test_is_active_true_when_total_gt_zero(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.is_active is True

    def test_is_active_false_when_total_zero(self):
        v = build_local_chain_view({"total_executions": 0})
        assert v.is_active is False

    def test_extracts_last_step(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.last_step == "openclawd_feedback"

    def test_extracts_last_task_id(self):
        v = build_local_chain_view(_LOCAL_SNAPSHOT_DICT)
        assert v.last_task_id == "task-abc"


# ---------------------------------------------------------------------------
# 35–44: build_cross_device_chain_view
# ---------------------------------------------------------------------------


class TestBuildCrossDeviceChainView:
    def test_none_returns_zero_state(self):
        v = build_cross_device_chain_view(None)
        assert v.total_executions == 0
        assert v.is_active is False

    def test_empty_dict_returns_zero_state(self):
        v = build_cross_device_chain_view({})
        assert v.total_executions == 0

    def test_sets_total_executions(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.total_executions == 3

    def test_sets_canonical_executions(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.canonical_executions == 2

    def test_sets_legacy_executions(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.legacy_executions == 1

    def test_sets_canonical_chain_order(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.canonical_chain_order[0] == "openclawd_dispatch"
        assert v.canonical_chain_order[-1] == "openclawd_feedback"

    def test_is_active_true_when_total_gt_zero(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.is_active is True

    def test_is_active_false_when_total_zero(self):
        v = build_cross_device_chain_view({"total_executions": 0})
        assert v.is_active is False

    def test_extracts_last_step(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.last_step == "command_router_cross_device"

    def test_extracts_last_device_id(self):
        v = build_cross_device_chain_view(_CD_SNAPSHOT_DICT)
        assert v.last_device_id == "device-42"


# ---------------------------------------------------------------------------
# 45–54: build_simulation_summary
# ---------------------------------------------------------------------------


class TestBuildSimulationSummary:
    def test_default_inactive_kind_none(self):
        s = build_simulation_summary()
        assert s.is_active is False
        assert s.simulation_kind == "none"

    def test_is_active_set(self):
        s = build_simulation_summary(is_active=True)
        assert s.is_active is True

    def test_speculative_kind_accepted(self):
        s = build_simulation_summary(simulation_kind="speculative")
        assert s.simulation_kind == "speculative"

    def test_sandbox_kind_accepted(self):
        s = build_simulation_summary(simulation_kind="sandbox")
        assert s.simulation_kind == "sandbox"

    def test_unknown_kind_coerces_to_none(self):
        s = build_simulation_summary(simulation_kind="unknown_kind")
        assert s.simulation_kind == "none"

    def test_candidate_paths_preserved(self):
        s = build_simulation_summary(candidate_paths=["local", "cross_device"])
        assert s.candidate_paths == ["local", "cross_device"]

    def test_committed_path_sets_is_committed(self):
        s = build_simulation_summary(committed_path="local")
        assert s.is_committed is True
        assert s.committed_path == "local"

    def test_none_committed_path_not_committed(self):
        s = build_simulation_summary(committed_path=None)
        assert s.is_committed is False

    def test_step_count_stored(self):
        s = build_simulation_summary(step_count=7)
        assert s.step_count == 7

    def test_scenario_label_stored(self):
        s = build_simulation_summary(scenario_label="test-scenario")
        assert s.scenario_label == "test-scenario"


# ---------------------------------------------------------------------------
# 55–59: build_liminal_space_map
# ---------------------------------------------------------------------------


class TestBuildLiminalSpaceMap:
    def test_none_inputs_empty_views(self):
        m = build_liminal_space_map()
        assert m.local_chain.total_executions == 0
        assert m.cross_device_chain.total_executions == 0
        assert m.simulation_summary.is_active is False

    def test_local_snapshot_dict_wires_to_local_chain(self):
        m = build_liminal_space_map(local_snapshot_dict=_LOCAL_SNAPSHOT_DICT)
        assert m.local_chain.total_executions == 5

    def test_cd_snapshot_dict_wires_to_cross_device_chain(self):
        m = build_liminal_space_map(cross_device_snapshot_dict=_CD_SNAPSHOT_DICT)
        assert m.cross_device_chain.total_executions == 3

    def test_simulation_summary_wires_to_field(self):
        sim = build_simulation_summary(is_active=True, simulation_kind="sandbox")
        m = build_liminal_space_map(simulation_summary=sim)
        assert m.simulation_summary.is_active is True
        assert m.simulation_summary.simulation_kind == "sandbox"

    def test_none_simulation_summary_produces_inactive(self):
        m = build_liminal_space_map(simulation_summary=None)
        assert m.simulation_summary.is_active is False
        assert m.simulation_summary.simulation_kind == "none"


# ---------------------------------------------------------------------------
# 60–63: get_liminal_space_map
# ---------------------------------------------------------------------------


class TestGetLiminalSpaceMap:
    def test_returns_liminal_space_map(self):
        m = get_liminal_space_map()
        assert isinstance(m, LiminalSpaceMap)

    def test_local_chain_is_local_chain_view(self):
        m = get_liminal_space_map()
        assert isinstance(m.local_chain, LocalChainView)

    def test_cross_device_chain_is_cross_device_chain_view(self):
        m = get_liminal_space_map()
        assert isinstance(m.cross_device_chain, CrossDeviceChainView)

    def test_simulation_summary_is_simulation_summary(self):
        m = get_liminal_space_map()
        assert isinstance(m.simulation_summary, SimulationSummary)


# ---------------------------------------------------------------------------
# 64–78: Boundary — prohibited fields
# ---------------------------------------------------------------------------


class TestBoundaryProhibitedFields:
    def test_local_chain_view_no_primary_model_id(self):
        d = LocalChainView().to_dict()
        assert "primary_model_id" not in d

    def test_local_chain_view_no_support_model_ids(self):
        d = LocalChainView().to_dict()
        assert "support_model_ids" not in d

    def test_local_chain_view_no_active_weights(self):
        d = LocalChainView().to_dict()
        assert "active_weights" not in d

    def test_cross_device_chain_view_no_route_reason(self):
        d = CrossDeviceChainView().to_dict()
        assert "route_reason" not in d

    def test_cross_device_chain_view_no_routing_authority(self):
        d = CrossDeviceChainView().to_dict()
        assert "routing_authority" not in d

    def test_cross_device_chain_view_no_vendor_source(self):
        d = CrossDeviceChainView().to_dict()
        assert "vendor_source" not in d

    def test_simulation_summary_no_primary_model_id(self):
        d = SimulationSummary().to_dict()
        assert "primary_model_id" not in d

    def test_simulation_summary_no_presence_intensity(self):
        d = SimulationSummary().to_dict()
        assert "presence_intensity" not in d

    def test_simulation_summary_no_topology_role(self):
        d = SimulationSummary().to_dict()
        assert "topology_role" not in d

    def test_liminal_space_map_no_primary_model_id(self):
        d = LiminalSpaceMap().to_dict()
        assert "primary_model_id" not in d

    def test_liminal_space_map_no_support_model_ids(self):
        d = LiminalSpaceMap().to_dict()
        assert "support_model_ids" not in d

    def test_liminal_space_map_no_routing_authority(self):
        d = LiminalSpaceMap().to_dict()
        assert "routing_authority" not in d

    def test_liminal_space_map_no_presence_intensity(self):
        d = LiminalSpaceMap().to_dict()
        assert "presence_intensity" not in d

    def test_liminal_space_map_no_coherence(self):
        d = LiminalSpaceMap().to_dict()
        assert "coherence" not in d

    def test_liminal_space_map_no_oneapi_source(self):
        d = LiminalSpaceMap().to_dict()
        assert "oneapi_source" not in d


# ---------------------------------------------------------------------------
# 79–84: LiminalSurface rendering
# ---------------------------------------------------------------------------


class TestLiminalSurface:
    def setup_method(self):
        from windows_client.status_board_v2.liminal_surface import LiminalSurface
        self.surface = LiminalSurface()
        self.projection = {
            "tri_state_phase": "liminal",
            "runtime_domain": "local",
            "presence_intensity": 0.6,
            "coherence": 0.75,
        }

    def test_render_returns_non_empty_string(self):
        result = self.surface.render(self.projection)
        assert isinstance(result, str) and len(result) > 0

    def test_render_no_provider_list_label(self):
        result = self.surface.render(self.projection)
        assert "provider_list" not in result

    def test_render_no_primary_model_id_label(self):
        result = self.surface.render(self.projection)
        assert "primary_model_id" not in result

    def test_render_contains_local_chain_panel(self):
        result = self.surface.render(self.projection)
        assert "Local" in result or "local" in result.lower()

    def test_render_unavailable_non_empty(self):
        result = self.surface._render_unavailable()
        assert isinstance(result, str) and len(result) > 0

    def test_render_unavailable_no_primary_model_id(self):
        result = self.surface._render_unavailable()
        assert "primary_model_id" not in result


# ---------------------------------------------------------------------------
# 85–89: Documentation and module guardrails
# ---------------------------------------------------------------------------


class TestDocumentationGuardrails:
    def test_liminal_space_mapping_md_exists(self):
        path = os.path.join(_REPO_ROOT, "docs", "LIMINAL_SPACE_MAPPING.md")
        assert os.path.isfile(path), "docs/LIMINAL_SPACE_MAPPING.md must exist"

    def test_sandbox_simulation_projection_md_exists(self):
        path = os.path.join(_REPO_ROOT, "docs", "SANDBOX_SIMULATION_PROJECTION.md")
        assert os.path.isfile(path), "docs/SANDBOX_SIMULATION_PROJECTION.md must exist"

    def test_liminal_space_mapping_md_mentions_three_content_classes(self):
        path = os.path.join(_REPO_ROOT, "docs", "LIMINAL_SPACE_MAPPING.md")
        content = open(path).read().lower()
        assert "local execution chain" in content
        assert "cross-device execution chain" in content or "cross device execution chain" in content
        assert "sandbox simulation" in content or "speculative" in content

    def test_sandbox_simulation_md_mentions_simulation_summary(self):
        path = os.path.join(_REPO_ROOT, "docs", "SANDBOX_SIMULATION_PROJECTION.md")
        content = open(path).read()
        assert "SimulationSummary" in content

    def test_module_docstring_mentions_three_content_classes(self):
        import core.liminal_space_mapping as mod
        doc = mod.__doc__ or ""
        assert "Local execution chain" in doc
        assert "Cross-device execution chain" in doc
        assert "Sandbox simulation" in doc or "speculative" in doc.lower()


# ---------------------------------------------------------------------------
# 90–95: Immutability and JSON serialisability
# ---------------------------------------------------------------------------


class TestImmutabilityAndSerialisation:
    def test_liminal_space_map_is_frozen(self):
        m = LiminalSpaceMap()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            m.map_id = "mutated"  # type: ignore[misc]

    def test_local_chain_view_is_frozen(self):
        v = LocalChainView()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            v.total_executions = 99  # type: ignore[misc]

    def test_cross_device_chain_view_is_frozen(self):
        v = CrossDeviceChainView()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            v.total_executions = 99  # type: ignore[misc]

    def test_simulation_summary_is_frozen(self):
        s = SimulationSummary()
        with pytest.raises((dataclasses.FrozenInstanceError, AttributeError, TypeError)):
            s.is_active = True  # type: ignore[misc]

    def test_to_dict_is_json_serialisable(self):
        m = build_liminal_space_map(
            local_snapshot_dict=_LOCAL_SNAPSHOT_DICT,
            cross_device_snapshot_dict=_CD_SNAPSHOT_DICT,
        )
        payload = json.dumps(m.to_dict())
        assert len(payload) > 0

    def test_get_liminal_space_map_returns_different_instances(self):
        m1 = get_liminal_space_map()
        m2 = get_liminal_space_map()
        # Each call produces a new instance with a unique map_id.
        assert m1.map_id != m2.map_id
