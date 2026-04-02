#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_renderer_consumes_network_runtime.py
================================================
PR-8: Network Topology Runtime — renderer consumer tests.

Validates the governance contract that renderer, layout, and status-board
surfaces consume topology from NetworkTopologyRuntime rather than from
scattered partial state sources.

Coverage
--------
A) Governance policy declarations
   - TOPOLOGY_CONSUMER_POLICY is importable and non-empty
   - TOPOLOGY_CONSUMER_POLICY references NETWORK_TOPOLOGY_RUNTIME
   - NETWORK_TOPOLOGY_RUNTIME_AUTHORITY is importable

B) Snapshot consumption
   - snapshot() to_dict() is JSON-serialisable
   - snapshot() total_nodes reflects registered nodes
   - snapshot() total_edges reflects registered edges
   - snapshot() recent_records is a list
   - snapshot() authority matches NETWORK_TOPOLOGY_RUNTIME_AUTHORITY
   - snapshot() nodes_by_kind reflects all node kinds
   - snapshot() edges_by_kind reflects all edge kinds

C) Renderer reads from runtime (canonical source)
   - Consumer can read GATEWAY nodes for renderer
   - Consumer can read DEVICE nodes for renderer
   - Consumer can read NATS_FABRIC_ENDPOINT nodes for renderer
   - Consumer can read RELAY nodes for renderer
   - Consumer can read MESH_PARTICIPANT nodes for renderer
   - Consumer can read all preferred edges for renderer
   - Consumer sees correct state after state update

D) Topology change propagation
   - Absorbing NATS state is visible in subsequent snapshot
   - Absorbing gateway state is visible in subsequent snapshot
   - Absorbing device connectivity is visible in subsequent snapshot
   - State change is visible in subsequent snapshot
   - Edge removal is visible in subsequent snapshot

E) Ring buffer governance
   - Topology log is capped at 256 entries
   - Log entries have required fields
   - Log entries have contract_version

F) Multi-source single-view
   - Nodes from different absorption sources coexist in same snapshot
   - snapshot() nodes_by_kind reflects multiple sources
   - Single call to snapshot() returns all topology across sources
"""

from __future__ import annotations

import json

import pytest

from core.network_topology_runtime import (
    NETWORK_TOPOLOGY_RUNTIME_AUTHORITY,
    TOPOLOGY_CONSUMER_POLICY,
    TopologyNodeKind,
    TopologyEdgeKind,
    TopologyConnectionState,
    TopologyNode,
    TopologyEdge,
    get_network_topology_runtime,
    reset_network_topology_runtime,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_network_topology_runtime()
    yield
    reset_network_topology_runtime()


# ===========================================================================
# A) Governance policy declarations
# ===========================================================================


def test_a01_topology_consumer_policy_importable():
    assert isinstance(TOPOLOGY_CONSUMER_POLICY, str)
    assert TOPOLOGY_CONSUMER_POLICY


def test_a02_consumer_policy_references_runtime():
    assert "NETWORK_TOPOLOGY_RUNTIME" in TOPOLOGY_CONSUMER_POLICY


def test_a03_authority_importable():
    assert isinstance(NETWORK_TOPOLOGY_RUNTIME_AUTHORITY, str)
    assert "PR-8" in NETWORK_TOPOLOGY_RUNTIME_AUTHORITY


# ===========================================================================
# B) Snapshot consumption
# ===========================================================================


def test_b01_snapshot_json_serialisable():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="snap1"))
    snap = rt.snapshot()
    json.dumps(snap.to_dict())  # must not raise


def test_b02_snapshot_total_nodes_reflects_registered():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="sn1"))
    rt.register_node(TopologyNode(node_id="sn2"))
    snap = rt.snapshot()
    assert snap.total_nodes >= 2


def test_b03_snapshot_total_edges_reflects_registered():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="se1", source_node_id="a", target_node_id="b"))
    rt.register_edge(TopologyEdge(
        edge_id="se2", source_node_id="c", target_node_id="d"))
    snap = rt.snapshot()
    assert snap.total_edges >= 2


def test_b04_snapshot_recent_records_is_list():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="sn3"))
    snap = rt.snapshot()
    assert isinstance(snap.recent_records, list)


def test_b05_snapshot_authority_matches():
    rt = get_network_topology_runtime()
    snap = rt.snapshot()
    assert snap.authority == NETWORK_TOPOLOGY_RUNTIME_AUTHORITY


def test_b06_snapshot_nodes_by_kind_reflects_kinds():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="gw1", kind=TopologyNodeKind.GATEWAY))
    rt.register_node(TopologyNode(node_id="dev1", kind=TopologyNodeKind.DEVICE))
    snap = rt.snapshot()
    assert "gateway" in snap.nodes_by_kind
    assert "device" in snap.nodes_by_kind


def test_b07_snapshot_edges_by_kind_reflects_kinds():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="ek1", source_node_id="a", target_node_id="b",
        kind=TopologyEdgeKind.DIRECT))
    rt.register_edge(TopologyEdge(
        edge_id="ek2", source_node_id="c", target_node_id="d",
        kind=TopologyEdgeKind.RELAY))
    snap = rt.snapshot()
    assert "direct" in snap.edges_by_kind
    assert "relay" in snap.edges_by_kind


# ===========================================================================
# C) Renderer reads from runtime (canonical source)
# ===========================================================================


def test_c01_renderer_reads_gateway_nodes():
    rt = get_network_topology_runtime()
    rt.absorb_gateway_state(gateway_id="gw-r", is_connected=True)
    gateways = rt.nodes_by_kind(TopologyNodeKind.GATEWAY)
    assert any(n.node_id == "gw-r" for n in gateways)


def test_c02_renderer_reads_device_nodes():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev-r", preferred_path="direct_ws", effective_routable=True)
    devices = rt.nodes_by_kind(TopologyNodeKind.DEVICE)
    assert any(n.node_id == "dev-r" for n in devices)


def test_c03_renderer_reads_nats_nodes():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    nats_nodes = rt.nodes_by_kind(TopologyNodeKind.NATS_FABRIC_ENDPOINT)
    assert len(nats_nodes) >= 1


def test_c04_renderer_reads_relay_nodes():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="relay-r", kind=TopologyNodeKind.RELAY))
    relays = rt.nodes_by_kind(TopologyNodeKind.RELAY)
    assert any(n.node_id == "relay-r" for n in relays)


def test_c05_renderer_reads_mesh_participant_nodes():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="mesh-r", kind=TopologyNodeKind.MESH_PARTICIPANT))
    mesh_nodes = rt.nodes_by_kind(TopologyNodeKind.MESH_PARTICIPANT)
    assert any(n.node_id == "mesh-r" for n in mesh_nodes)


def test_c06_renderer_reads_preferred_edges():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="pref-r", source_node_id="a", target_node_id="b",
        preferred=True, state=TopologyConnectionState.PREFERRED))
    preferred = rt.preferred_edges()
    assert any(e.edge_id == "pref-r" for e in preferred)


def test_c07_renderer_sees_state_after_update():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="state-n", state=TopologyConnectionState.LATENT))
    rt.update_node_state("state-n", TopologyConnectionState.CONNECTED)
    node = rt.get_node("state-n")
    assert node.state == TopologyConnectionState.CONNECTED


# ===========================================================================
# D) Topology change propagation
# ===========================================================================


def test_d01_nats_absorption_visible_in_snapshot():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    snap = rt.snapshot()
    assert "nats_fabric_endpoint" in snap.nodes_by_kind


def test_d02_gateway_absorption_visible_in_snapshot():
    rt = get_network_topology_runtime()
    rt.absorb_gateway_state(gateway_id="gw-vis", is_connected=True)
    snap = rt.snapshot()
    assert "gateway" in snap.nodes_by_kind


def test_d03_device_absorption_visible_in_snapshot():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev-vis", preferred_path="direct_ws", effective_routable=True)
    snap = rt.snapshot()
    assert "device" in snap.nodes_by_kind


def test_d04_state_change_visible_in_snapshot():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(
        node_id="chg1", state=TopologyConnectionState.LATENT))
    rt.update_node_state("chg1", TopologyConnectionState.DEGRADED)
    snap = rt.snapshot()
    assert "degraded" in snap.nodes_by_state


def test_d05_edge_removal_visible_in_snapshot():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="er-vis", source_node_id="a", target_node_id="b"))
    before = rt.snapshot().total_edges
    rt.remove_edge("er-vis")
    after = rt.snapshot().total_edges
    assert after == before - 1


# ===========================================================================
# E) Ring buffer governance
# ===========================================================================


def test_e01_topology_log_max_256():
    rt = get_network_topology_runtime()
    # Register > 256 nodes to overflow the ring buffer
    for i in range(260):
        rt.register_node(TopologyNode(node_id=f"flood-{i}"))
    assert len(rt.get_topology_log()) <= 256


def test_e02_log_entries_have_required_fields():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="log-check"))
    log = list(rt.get_topology_log())
    assert log, "Expected at least one log entry"
    last = log[-1]
    assert hasattr(last, "record_id")
    assert hasattr(last, "event_kind")
    assert hasattr(last, "node_id")


def test_e03_log_entries_have_contract_version():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="log-cv"))
    log = list(rt.get_topology_log())
    assert log
    assert "contract_version" in log[-1].to_dict()


# ===========================================================================
# F) Multi-source single-view
# ===========================================================================


def test_f01_nodes_from_multiple_sources_coexist():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    rt.absorb_gateway_state(gateway_id="gw-ms", is_connected=True)
    rt.absorb_device_connectivity(
        device_id="dev-ms", preferred_path="direct_ws", effective_routable=True)
    nodes = rt.all_nodes()
    kinds = {n.kind for n in nodes}
    assert TopologyNodeKind.NATS_FABRIC_ENDPOINT in kinds
    assert TopologyNodeKind.GATEWAY in kinds
    assert TopologyNodeKind.DEVICE in kinds


def test_f02_snapshot_nodes_by_kind_reflects_multiple_sources():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    rt.absorb_gateway_state(gateway_id="gw-m2", is_connected=True)
    rt.absorb_device_connectivity(
        device_id="dev-m2", preferred_path="relay", effective_routable=True)
    snap = rt.snapshot()
    assert "nats_fabric_endpoint" in snap.nodes_by_kind
    assert "gateway" in snap.nodes_by_kind
    assert "device" in snap.nodes_by_kind


def test_f03_single_snapshot_covers_all_sources():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    rt.absorb_gateway_state(gateway_id="gw-all", is_connected=False)
    rt.absorb_device_connectivity(
        device_id="dev-all", preferred_path="", effective_routable=False)
    snap = rt.snapshot()
    # All three node kinds should be present in one snapshot
    assert snap.total_nodes >= 3
    assert len(snap.nodes_by_kind) >= 3
