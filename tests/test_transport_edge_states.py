#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_transport_edge_states.py
=====================================
PR-8: Network Topology Runtime — transport edge state tests.

Validates that:
  1.  Direct edge has DIRECT kind.
  2.  Gateway edge has GATEWAY kind.
  3.  Relay edge has RELAY kind.
  4.  Mesh edge has MESH kind.
  5.  Fabric edge has FABRIC kind.
  6.  Projected semantic edge has PROJECTED_SEMANTIC kind.
  7.  project_transport_path() returns TransportPathInfo.
  8.  project_transport_path() effective_path is set for preferred edge.
  9.  project_transport_path() fallback_path is set for FALLBACK edge.
 10.  project_transport_path() available_paths includes all active edges.
 11.  project_transport_path() uses transport_strategy hint when no preferred edge.
 12.  assimilate_transport_hierarchy_record() returns None when target_id is empty.
 13.  assimilate_transport_hierarchy_record() registers edge when target_id is set.
 14.  assimilate_transport_hierarchy_record() fallback_used=False → PREFERRED state.
 15.  assimilate_transport_hierarchy_record() fallback_used=True → FALLBACK state.
 16.  assimilate_transport_hierarchy_record() "direct" strategy → DIRECT edge kind.
 17.  assimilate_transport_hierarchy_record() "relay" strategy → RELAY edge kind.
 18.  assimilate_transport_hierarchy_record() "nats" strategy → FABRIC edge kind.
 19.  assimilate_transport_hierarchy_record() "mesh" strategy → MESH edge kind.
 20.  assimilate_transport_hierarchy_record() "gateway" strategy → GATEWAY edge kind.
 21.  update_edge_state() to PREFERRED marks preferred=True.
 22.  update_edge_state() to FALLBACK does not change preferred flag.
 23.  Edge with LATENT state not in available_paths.
 24.  Edge with UNAVAILABLE state not in available_paths.
 25.  Edge with CONNECTED state in available_paths.
 26.  Multiple edges for same source-target pair all included in available_paths.
 27.  removing an edge clears it from edges_from().
 28.  preferred_edges() is empty when no edges are preferred.
 29.  project_transport_path() preferred_edge_id matches preferred edge.
 30.  TopologyEdge.to_dict() contains contract_version.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.network_topology_runtime import (
    TopologyNodeKind,
    TopologyEdgeKind,
    TopologyConnectionState,
    TopologyNode,
    TopologyEdge,
    TransportPathInfo,
    assimilate_transport_hierarchy_record,
    project_transport_path,
    get_network_topology_runtime,
    reset_network_topology_runtime,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_network_topology_runtime()
    yield
    reset_network_topology_runtime()


def _make_strategy_record(strategy: str, fallback_used: bool = False) -> MagicMock:
    """Build a minimal mock FabricTransportStrategyRecord."""
    rec = MagicMock()
    rec.strategy = strategy
    rec.fallback_used = fallback_used
    return rec


def test_01_direct_edge_kind():
    e = TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.DIRECT)
    assert e.kind == TopologyEdgeKind.DIRECT
    assert e.to_dict()["kind"] == "direct"


def test_02_gateway_edge_kind():
    e = TopologyEdge(edge_id="e2", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.GATEWAY)
    assert e.to_dict()["kind"] == "gateway"


def test_03_relay_edge_kind():
    e = TopologyEdge(edge_id="e3", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.RELAY)
    assert e.to_dict()["kind"] == "relay"


def test_04_mesh_edge_kind():
    e = TopologyEdge(edge_id="e4", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.MESH)
    assert e.to_dict()["kind"] == "mesh"


def test_05_fabric_edge_kind():
    e = TopologyEdge(edge_id="e5", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.FABRIC)
    assert e.to_dict()["kind"] == "fabric"


def test_06_projected_semantic_edge_kind():
    e = TopologyEdge(edge_id="e6", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.PROJECTED_SEMANTIC)
    assert e.to_dict()["kind"] == "projected_semantic"


def test_07_project_transport_path_returns_info():
    rt = get_network_topology_runtime()
    result = rt.project_transport_path("src", "tgt")
    assert isinstance(result, TransportPathInfo)


def test_08_project_transport_path_effective_path_set():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="pref1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.DIRECT,
        state=TopologyConnectionState.PREFERRED,
        preferred=True,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert info.effective_path == "direct"
    assert info.preferred_edge_id == "pref1"


def test_09_project_transport_path_fallback_path_set():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="fb1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.RELAY,
        state=TopologyConnectionState.FALLBACK,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert info.fallback_path == "relay"


def test_10_project_transport_path_available_paths():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="avail1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.DIRECT,
        state=TopologyConnectionState.CONNECTED,
    ))
    rt.register_edge(TopologyEdge(
        edge_id="avail2", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.RELAY,
        state=TopologyConnectionState.FALLBACK,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert "direct" in info.available_paths
    assert "relay" in info.available_paths


def test_11_project_uses_strategy_hint_when_no_preferred():
    rt = get_network_topology_runtime()
    info = rt.project_transport_path("src", "tgt", transport_strategy="relay")
    assert info.effective_path == "relay"
    assert info.transport_strategy == "relay"


def test_12_assimilate_record_returns_none_when_no_target():
    rec = _make_strategy_record("direct")
    result = assimilate_transport_hierarchy_record(rec, target_id="")
    assert result is None


def test_13_assimilate_record_registers_edge_with_target():
    rec = _make_strategy_record("direct")
    edge = assimilate_transport_hierarchy_record(rec, source_id="src", target_id="tgt")
    assert edge is not None
    assert edge.target_node_id == "tgt"


def test_14_assimilate_record_no_fallback_is_preferred():
    rec = _make_strategy_record("direct", fallback_used=False)
    edge = assimilate_transport_hierarchy_record(rec, source_id="src", target_id="tgt")
    assert edge.preferred is True
    assert edge.state == TopologyConnectionState.PREFERRED


def test_15_assimilate_record_fallback_used_is_fallback():
    rec = _make_strategy_record("relay", fallback_used=True)
    edge = assimilate_transport_hierarchy_record(rec, source_id="src", target_id="tgt2")
    assert edge.preferred is False
    assert edge.state == TopologyConnectionState.FALLBACK


def test_16_direct_strategy_gives_direct_edge():
    rec = _make_strategy_record("direct")
    edge = assimilate_transport_hierarchy_record(rec, target_id="tgt")
    assert edge.kind == TopologyEdgeKind.DIRECT


def test_17_relay_strategy_gives_relay_edge():
    rec = _make_strategy_record("relay")
    edge = assimilate_transport_hierarchy_record(rec, target_id="tgt")
    assert edge.kind == TopologyEdgeKind.RELAY


def test_18_nats_strategy_gives_fabric_edge():
    rec = _make_strategy_record("nats")
    edge = assimilate_transport_hierarchy_record(rec, target_id="tgt")
    assert edge.kind == TopologyEdgeKind.FABRIC


def test_19_mesh_strategy_gives_mesh_edge():
    rec = _make_strategy_record("mesh")
    edge = assimilate_transport_hierarchy_record(rec, target_id="tgt")
    assert edge.kind == TopologyEdgeKind.MESH


def test_20_gateway_strategy_gives_gateway_edge():
    rec = _make_strategy_record("gateway")
    edge = assimilate_transport_hierarchy_record(rec, target_id="tgt")
    assert edge.kind == TopologyEdgeKind.GATEWAY


def test_21_update_to_preferred_sets_preferred_flag():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="upd1", source_node_id="a", target_node_id="b"))
    rt.update_edge_state("upd1", TopologyConnectionState.PREFERRED, preferred=True)
    assert rt.all_edges()[0].preferred is True


def test_22_update_to_fallback_does_not_change_preferred():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="upd2", source_node_id="a", target_node_id="b", preferred=False))
    rt.update_edge_state("upd2", TopologyConnectionState.FALLBACK)
    assert rt.all_edges()[0].preferred is False


def test_23_latent_edge_not_in_available_paths():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="lat1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.MESH,
        state=TopologyConnectionState.LATENT,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert "mesh" not in info.available_paths


def test_24_unavailable_edge_not_in_available_paths():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="unav1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.DIRECT,
        state=TopologyConnectionState.UNAVAILABLE,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert "direct" not in info.available_paths


def test_25_connected_edge_in_available_paths():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="conn1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.DIRECT,
        state=TopologyConnectionState.CONNECTED,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert "direct" in info.available_paths


def test_26_multiple_edges_all_in_available():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="multi1", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.DIRECT,
        state=TopologyConnectionState.PREFERRED,
        preferred=True,
    ))
    rt.register_edge(TopologyEdge(
        edge_id="multi2", source_node_id="src", target_node_id="tgt",
        kind=TopologyEdgeKind.RELAY,
        state=TopologyConnectionState.FALLBACK,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert "direct" in info.available_paths
    assert "relay" in info.available_paths


def test_27_removed_edge_not_in_edges_from():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="rem1", source_node_id="src", target_node_id="tgt"))
    rt.remove_edge("rem1")
    assert not any(e.edge_id == "rem1" for e in rt.edges_from("src"))


def test_28_no_preferred_edges_when_none_preferred():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="np1", source_node_id="a", target_node_id="b", preferred=False))
    assert rt.preferred_edges() == []


def test_29_project_preferred_edge_id_matches():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="pid1", source_node_id="src", target_node_id="tgt",
        state=TopologyConnectionState.PREFERRED,
        preferred=True,
    ))
    info = rt.project_transport_path("src", "tgt")
    assert info.preferred_edge_id == "pid1"


def test_30_topology_edge_to_dict_has_contract_version():
    e = TopologyEdge(edge_id="cv1", source_node_id="a", target_node_id="b")
    assert "contract_version" in e.to_dict()
