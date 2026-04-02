#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_topology_projection.py
===================================
PR-8: Network Topology Runtime — topology projection tests.

Validates that:
  1. NATS fabric state is correctly projected into a NATS_FABRIC_ENDPOINT node.
  2. Gateway substrate state is correctly projected into a GATEWAY node.
  3. Device connectivity is correctly projected into a DEVICE node + edges.
  4. Device with direct_ws path gets a DIRECT edge in PREFERRED state.
  5. Device with relay path gets a RELAY edge in PREFERRED state.
  6. Device with relay fallback gets a RELAY edge in FALLBACK state.
  7. Device with mesh overlay gets a MESH edge in LATENT state.
  8. Device with no path has UNAVAILABLE state.
  9. absorb_nats_state (connected) → node state = CONNECTED.
 10. absorb_nats_state (disconnected) → node state = UNAVAILABLE.
 11. absorb_gateway_state (connected) → node state = CONNECTED.
 12. absorb_gateway_state (disconnected) → node state = UNAVAILABLE.
 13. Multiple devices are independently tracked.
 14. NATS node is tagged with "nats" and "fabric".
 15. Gateway node is tagged with "gateway" and "substrate".
 16. Device node metadata contains preferred_path.
 17. assimilate_nats_state() convenience wrapper works.
 18. assimilate_gateway_state() convenience wrapper works.
 19. assimilate_device_connectivity() convenience wrapper works.
 20. Removing a device node cascades to remove its edges.
 21. nats_assimilated event appears in topology log.
 22. gateway_assimilated event appears in topology log.
 23. device_assimilated event appears in topology log.
 24. Snapshot reflects absorbed nodes from all sources.
 25. absorb_nats_state() preserves host and port.
 26. absorb_gateway_state() preserves host and port.
 27. absorb_device_connectivity() preserves host and port.
 28. Re-absorbing NATS state updates existing node.
 29. Re-absorbing gateway state updates existing node.
"""

from __future__ import annotations

import pytest

from core.network_topology_runtime import (
    TopologyNodeKind,
    TopologyEdgeKind,
    TopologyConnectionState,
    TopologyNode,
    TopologyEdge,
    assimilate_nats_state,
    assimilate_gateway_state,
    assimilate_device_connectivity,
    get_network_topology_runtime,
    reset_network_topology_runtime,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_network_topology_runtime()
    yield
    reset_network_topology_runtime()


def test_01_nats_connected_projects_connected_node():
    rt = get_network_topology_runtime()
    node = rt.absorb_nats_state(is_connected=True, host="localhost", port=4222)
    assert node.kind == TopologyNodeKind.NATS_FABRIC_ENDPOINT
    assert node.state == TopologyConnectionState.CONNECTED


def test_02_nats_disconnected_projects_unavailable_node():
    rt = get_network_topology_runtime()
    node = rt.absorb_nats_state(is_connected=False)
    assert node.state == TopologyConnectionState.UNAVAILABLE


def test_03_gateway_connected_projects_connected_node():
    rt = get_network_topology_runtime()
    node = rt.absorb_gateway_state(gateway_id="gw1", is_connected=True)
    assert node.kind == TopologyNodeKind.GATEWAY
    assert node.state == TopologyConnectionState.CONNECTED


def test_04_gateway_disconnected_projects_unavailable_node():
    rt = get_network_topology_runtime()
    node = rt.absorb_gateway_state(gateway_id="gw2", is_connected=False)
    assert node.state == TopologyConnectionState.UNAVAILABLE


def test_05_device_direct_ws_gets_preferred_edge():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev1",
        preferred_path="direct_ws",
        effective_routable=True,
    )
    edges = rt.edges_to("dev1")
    direct_edges = [e for e in edges if e.kind == TopologyEdgeKind.DIRECT]
    assert direct_edges, "Expected a DIRECT edge for direct_ws path"
    assert any(e.preferred for e in direct_edges)


def test_06_device_relay_path_gets_preferred_relay_edge():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev2",
        preferred_path="relay",
        effective_routable=True,
    )
    edges = rt.edges_to("dev2")
    relay_edges = [e for e in edges if e.kind == TopologyEdgeKind.RELAY]
    assert relay_edges, "Expected a RELAY edge for relay path"
    assert any(e.preferred for e in relay_edges)


def test_07_device_fallback_available_gets_fallback_relay_edge():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev3",
        preferred_path="direct_ws",
        effective_routable=True,
        fallback_available=True,
    )
    edges = rt.edges_to("dev3")
    relay_edges = [e for e in edges if e.kind == TopologyEdgeKind.RELAY]
    assert relay_edges, "Expected a RELAY edge when fallback is available"
    assert any(e.state == TopologyConnectionState.FALLBACK for e in relay_edges)


def test_08_device_mesh_overlay_gets_latent_mesh_edge():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev4",
        preferred_path="direct_ws",
        effective_routable=True,
        mesh_overlay_available=True,
    )
    edges = rt.edges_to("dev4")
    mesh_edges = [e for e in edges if e.kind == TopologyEdgeKind.MESH]
    assert mesh_edges, "Expected a MESH edge when mesh overlay is available"
    assert all(e.state == TopologyConnectionState.LATENT for e in mesh_edges)


def test_09_device_no_path_is_unavailable():
    rt = get_network_topology_runtime()
    node = rt.absorb_device_connectivity(
        device_id="dev5",
        preferred_path="",
        effective_routable=False,
    )
    assert node.state == TopologyConnectionState.UNAVAILABLE


def test_10_multiple_devices_tracked_independently():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="devA", preferred_path="direct_ws", effective_routable=True)
    rt.absorb_device_connectivity(
        device_id="devB", preferred_path="relay", effective_routable=True)
    assert rt.get_node("devA") is not None
    assert rt.get_node("devB") is not None


def test_11_nats_node_tagged():
    rt = get_network_topology_runtime()
    node = rt.absorb_nats_state(is_connected=True)
    assert "nats" in node.tags
    assert "fabric" in node.tags


def test_12_gateway_node_tagged():
    rt = get_network_topology_runtime()
    node = rt.absorb_gateway_state(gateway_id="gwT", is_connected=True)
    assert "gateway" in node.tags
    assert "substrate" in node.tags


def test_13_device_metadata_contains_preferred_path():
    rt = get_network_topology_runtime()
    node = rt.absorb_device_connectivity(
        device_id="dev6", preferred_path="direct_ws", effective_routable=True)
    assert node.metadata.get("preferred_path") == "direct_ws"


def test_14_assimilate_nats_state_wrapper_works():
    node = assimilate_nats_state(True, host="nats.local", port=4222)
    assert node.kind == TopologyNodeKind.NATS_FABRIC_ENDPOINT


def test_15_assimilate_gateway_state_wrapper_works():
    node = assimilate_gateway_state("gw-wrap", host="gw.local", port=8080,
                                    is_connected=True)
    assert node.kind == TopologyNodeKind.GATEWAY


def test_16_assimilate_device_connectivity_wrapper_works():
    node = assimilate_device_connectivity(
        "dev-wrap", preferred_path="direct_ws", effective_routable=True)
    assert node.kind == TopologyNodeKind.DEVICE


def test_17_removing_device_cascades_to_edges():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev7", preferred_path="direct_ws", effective_routable=True,
        fallback_available=True)
    before = len(rt.edges_to("dev7"))
    assert before > 0
    rt.remove_node("dev7")
    assert rt.edges_to("dev7") == []


def test_18_nats_assimilated_event_in_log():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    log = list(rt.get_topology_log())
    assert any(r.event_kind == "nats_assimilated" for r in log)


def test_19_gateway_assimilated_event_in_log():
    rt = get_network_topology_runtime()
    rt.absorb_gateway_state(gateway_id="gw-log", is_connected=True)
    log = list(rt.get_topology_log())
    assert any(r.event_kind == "gateway_assimilated" for r in log)


def test_20_device_assimilated_event_in_log():
    rt = get_network_topology_runtime()
    rt.absorb_device_connectivity(
        device_id="dev8", preferred_path="direct_ws", effective_routable=True)
    log = list(rt.get_topology_log())
    assert any(r.event_kind == "device_assimilated" for r in log)


def test_21_snapshot_reflects_all_absorbed_nodes():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    rt.absorb_gateway_state(gateway_id="gw-snap", is_connected=True)
    rt.absorb_device_connectivity(
        device_id="dev-snap", preferred_path="direct_ws", effective_routable=True)
    s = rt.snapshot()
    assert s.total_nodes >= 3
    assert "nats_fabric_endpoint" in s.nodes_by_kind
    assert "gateway" in s.nodes_by_kind
    assert "device" in s.nodes_by_kind


def test_22_absorb_nats_preserves_host_port():
    rt = get_network_topology_runtime()
    node = rt.absorb_nats_state(is_connected=True, host="natshost", port=9999)
    assert rt.get_node(node.node_id).host == "natshost"
    assert rt.get_node(node.node_id).port == 9999


def test_23_absorb_gateway_preserves_host_port():
    rt = get_network_topology_runtime()
    node = rt.absorb_gateway_state(
        gateway_id="gw-hp", host="gwhost", port=7777, is_connected=True)
    assert rt.get_node("gw-hp").host == "gwhost"
    assert rt.get_node("gw-hp").port == 7777


def test_24_absorb_device_preserves_host_port():
    rt = get_network_topology_runtime()
    node = rt.absorb_device_connectivity(
        device_id="dev-hp", effective_routable=True, host="devhost", port=5555)
    assert rt.get_node("dev-hp").host == "devhost"
    assert rt.get_node("dev-hp").port == 5555


def test_25_re_absorbing_nats_updates_node():
    rt = get_network_topology_runtime()
    rt.absorb_nats_state(is_connected=True)
    rt.absorb_nats_state(is_connected=False)
    node = rt.get_node("nats_fabric")
    assert node.state == TopologyConnectionState.UNAVAILABLE


def test_26_re_absorbing_gateway_updates_node():
    rt = get_network_topology_runtime()
    rt.absorb_gateway_state(gateway_id="gw-reabs", is_connected=True)
    rt.absorb_gateway_state(gateway_id="gw-reabs", is_connected=False)
    node = rt.get_node("gw-reabs")
    assert node.state == TopologyConnectionState.UNAVAILABLE


def test_27_device_fallback_only_state_is_fallback():
    rt = get_network_topology_runtime()
    node = rt.absorb_device_connectivity(
        device_id="dev-fb",
        preferred_path="relay",
        effective_routable=False,
        fallback_available=True,
    )
    assert node.state == TopologyConnectionState.FALLBACK


def test_28_device_mesh_only_state_is_latent():
    rt = get_network_topology_runtime()
    node = rt.absorb_device_connectivity(
        device_id="dev-mesh-only",
        preferred_path="",
        effective_routable=False,
        fallback_available=False,
        mesh_overlay_available=True,
    )
    assert node.state == TopologyConnectionState.LATENT
