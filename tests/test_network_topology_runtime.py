#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_network_topology_runtime.py
========================================
PR-8: Network Topology Runtime — core governance tests.

Coverage
--------
A) Module structure
   - NETWORK_TOPOLOGY_RUNTIME_AUTHORITY sentinel importable
   - NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION is 8
   - NETWORK_TOPOLOGY_CONTRACT_VERSION importable
   - TOPOLOGY_CONSUMER_POLICY importable
   - TRANSPORT_HIERARCHY_ASSIMILATION_POLICY importable
   - All public names in __all__ importable

B) TopologyNodeKind enum
   - DEVICE value
   - GATEWAY value
   - RELAY value
   - MESH_PARTICIPANT value
   - NATS_FABRIC_ENDPOINT value
   - RUNTIME_PROVIDER_NODE value
   - UNKNOWN value

C) TopologyEdgeKind enum
   - DIRECT value
   - GATEWAY value
   - RELAY value
   - MESH value
   - FABRIC value
   - PROJECTED_SEMANTIC value

D) TopologyConnectionState enum
   - REACHABLE value
   - CONNECTED value
   - DEGRADED value
   - PREFERRED value
   - FALLBACK value
   - LATENT value
   - UNAVAILABLE value

E) TopologyNode dataclass
   - construction with only node_id
   - to_dict() contains all expected keys
   - to_dict() kind and state are strings
   - to_dict() is JSON-serialisable

F) TopologyEdge dataclass
   - construction with required fields
   - to_dict() contains all expected keys
   - to_dict() kind and state are strings
   - to_dict() is JSON-serialisable

G) TopologyRecord dataclass
   - construction
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

H) TransportPathInfo dataclass
   - construction
   - to_dict() contains all expected keys

I) TopologySnapshot dataclass
   - construction
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

J) NetworkTopologyRuntime — node management
   - register_node() returns TopologyNode
   - register_node() empty node_id raises ValueError
   - registered node is retrievable via get_node()
   - get_node() returns None for unknown node
   - all_nodes() returns list
   - register_node() idempotent (updates in place)
   - idempotent re-registration preserves registered_at
   - update_node_state() returns updated node
   - update_node_state() returns None for unknown node
   - remove_node() returns True for known node
   - remove_node() returns False for unknown node
   - remove_node() removes node from all_nodes()
   - nodes_by_kind() filters by kind
   - nodes_by_state() filters by state

K) NetworkTopologyRuntime — edge management
   - register_edge() returns TopologyEdge
   - register_edge() empty edge_id raises ValueError
   - all_edges() returns list
   - edges_from() returns edges for known source
   - edges_to() returns edges for known target
   - update_edge_state() returns updated edge
   - update_edge_state() returns None for unknown edge
   - remove_edge() returns True for known edge
   - remove_edge() returns False for unknown edge
   - preferred_edges() returns only preferred edges

L) NetworkTopologyRuntime — observability
   - get_topology_log() returns a deque
   - registration emits a record
   - state change emits a record
   - removal emits a record
   - snapshot() returns TopologySnapshot
   - snapshot() total_nodes is correct
   - snapshot() nodes_by_kind is populated
   - snapshot() nodes_by_state is populated
   - snapshot() edges_by_kind is populated
   - snapshot() preferred_edges is populated

M) Singleton behaviour
   - get_network_topology_runtime() returns same instance
   - reset_network_topology_runtime() creates new instance

N) NATS_BUS integration sentinel
   - NETWORK_TOPOLOGY_RUNTIME_INTEGRATED importable from nats_bus

O) Gateway adapter integration sentinel
   - NETWORK_TOPOLOGY_RUNTIME_INTEGRATED importable from gateway_nats_adapter
"""

from __future__ import annotations

import json
from collections import deque

import pytest

import core.network_topology_runtime as _mod
from core.network_topology_runtime import (
    NETWORK_TOPOLOGY_RUNTIME_AUTHORITY,
    NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION,
    NETWORK_TOPOLOGY_CONTRACT_VERSION,
    TOPOLOGY_CONSUMER_POLICY,
    TRANSPORT_HIERARCHY_ASSIMILATION_POLICY,
    TopologyNodeKind,
    TopologyEdgeKind,
    TopologyConnectionState,
    TopologyNode,
    TopologyEdge,
    TopologyRecord,
    TransportPathInfo,
    TopologySnapshot,
    NetworkTopologyRuntime,
    get_network_topology_runtime,
    reset_network_topology_runtime,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_network_topology_runtime()
    yield
    reset_network_topology_runtime()


# ===========================================================================
# A) Module structure
# ===========================================================================


def test_a01_authority_sentinel_importable():
    assert isinstance(NETWORK_TOPOLOGY_RUNTIME_AUTHORITY, str)
    assert "PR-8" in NETWORK_TOPOLOGY_RUNTIME_AUTHORITY


def test_a02_layer_position_is_8():
    assert NETWORK_TOPOLOGY_RUNTIME_LAYER_POSITION == 8


def test_a03_contract_version_importable():
    assert isinstance(NETWORK_TOPOLOGY_CONTRACT_VERSION, str)
    assert NETWORK_TOPOLOGY_CONTRACT_VERSION


def test_a04_topology_consumer_policy_importable():
    assert isinstance(TOPOLOGY_CONSUMER_POLICY, str)
    assert "NETWORK_TOPOLOGY_RUNTIME" in TOPOLOGY_CONSUMER_POLICY


def test_a05_transport_hierarchy_policy_importable():
    assert isinstance(TRANSPORT_HIERARCHY_ASSIMILATION_POLICY, str)
    assert "ABSORBED" in TRANSPORT_HIERARCHY_ASSIMILATION_POLICY


def test_a06_all_public_names_importable():
    for name in _mod.__all__:
        assert hasattr(_mod, name), f"{name!r} missing from module"


# ===========================================================================
# B) TopologyNodeKind enum
# ===========================================================================


def test_b01_device_value():
    assert TopologyNodeKind.DEVICE.value == "device"


def test_b02_gateway_value():
    assert TopologyNodeKind.GATEWAY.value == "gateway"


def test_b03_relay_value():
    assert TopologyNodeKind.RELAY.value == "relay"


def test_b04_mesh_participant_value():
    assert TopologyNodeKind.MESH_PARTICIPANT.value == "mesh_participant"


def test_b05_nats_fabric_endpoint_value():
    assert TopologyNodeKind.NATS_FABRIC_ENDPOINT.value == "nats_fabric_endpoint"


def test_b06_runtime_provider_node_value():
    assert TopologyNodeKind.RUNTIME_PROVIDER_NODE.value == "runtime_provider_node"


def test_b07_unknown_value():
    assert TopologyNodeKind.UNKNOWN.value == "unknown"


# ===========================================================================
# C) TopologyEdgeKind enum
# ===========================================================================


def test_c01_direct_value():
    assert TopologyEdgeKind.DIRECT.value == "direct"


def test_c02_gateway_value():
    assert TopologyEdgeKind.GATEWAY.value == "gateway"


def test_c03_relay_value():
    assert TopologyEdgeKind.RELAY.value == "relay"


def test_c04_mesh_value():
    assert TopologyEdgeKind.MESH.value == "mesh"


def test_c05_fabric_value():
    assert TopologyEdgeKind.FABRIC.value == "fabric"


def test_c06_projected_semantic_value():
    assert TopologyEdgeKind.PROJECTED_SEMANTIC.value == "projected_semantic"


# ===========================================================================
# D) TopologyConnectionState enum
# ===========================================================================


def test_d01_reachable_value():
    assert TopologyConnectionState.REACHABLE.value == "reachable"


def test_d02_connected_value():
    assert TopologyConnectionState.CONNECTED.value == "connected"


def test_d03_degraded_value():
    assert TopologyConnectionState.DEGRADED.value == "degraded"


def test_d04_preferred_value():
    assert TopologyConnectionState.PREFERRED.value == "preferred"


def test_d05_fallback_value():
    assert TopologyConnectionState.FALLBACK.value == "fallback"


def test_d06_latent_value():
    assert TopologyConnectionState.LATENT.value == "latent"


def test_d07_unavailable_value():
    assert TopologyConnectionState.UNAVAILABLE.value == "unavailable"


# ===========================================================================
# E) TopologyNode dataclass
# ===========================================================================


def test_e01_topology_node_construction_minimal():
    n = TopologyNode(node_id="dev-1")
    assert n.node_id == "dev-1"
    assert n.kind == TopologyNodeKind.UNKNOWN
    assert n.state == TopologyConnectionState.LATENT


def test_e02_to_dict_expected_keys():
    n = TopologyNode(node_id="dev-1", kind=TopologyNodeKind.DEVICE)
    d = n.to_dict()
    for key in ("node_id", "kind", "state", "host", "port", "transport_hints",
                "tags", "metadata", "registered_at", "last_updated_at",
                "contract_version"):
        assert key in d, f"key {key!r} missing from TopologyNode.to_dict()"


def test_e03_to_dict_kind_is_string():
    n = TopologyNode(node_id="dev-1", kind=TopologyNodeKind.DEVICE)
    assert isinstance(n.to_dict()["kind"], str)


def test_e04_to_dict_state_is_string():
    n = TopologyNode(node_id="dev-1", state=TopologyConnectionState.CONNECTED)
    assert isinstance(n.to_dict()["state"], str)


def test_e05_to_dict_json_serialisable():
    n = TopologyNode(node_id="dev-1")
    json.dumps(n.to_dict())  # must not raise


# ===========================================================================
# F) TopologyEdge dataclass
# ===========================================================================


def test_f01_topology_edge_construction():
    e = TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    assert e.edge_id == "e1"
    assert e.kind == TopologyEdgeKind.DIRECT
    assert e.state == TopologyConnectionState.LATENT


def test_f02_to_dict_expected_keys():
    e = TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    d = e.to_dict()
    for key in ("edge_id", "source_node_id", "target_node_id", "kind", "state",
                "preferred", "latency_hint_ms", "metadata", "created_at",
                "last_updated_at", "contract_version"):
        assert key in d, f"key {key!r} missing from TopologyEdge.to_dict()"


def test_f03_to_dict_kind_is_string():
    e = TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b",
                     kind=TopologyEdgeKind.RELAY)
    assert isinstance(e.to_dict()["kind"], str)


def test_f04_to_dict_json_serialisable():
    e = TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    json.dumps(e.to_dict())  # must not raise


# ===========================================================================
# G) TopologyRecord dataclass
# ===========================================================================


def test_g01_topology_record_construction():
    r = TopologyRecord(record_id="r1", event_kind="node_registered", node_id="n1")
    assert r.record_id == "r1"
    assert r.event_kind == "node_registered"


def test_g02_to_dict_expected_keys():
    r = TopologyRecord(record_id="r1", event_kind="test", node_id="n1")
    d = r.to_dict()
    for key in ("record_id", "event_kind", "node_id", "kind", "state",
                "timestamp", "details", "contract_version"):
        assert key in d, f"key {key!r} missing from TopologyRecord.to_dict()"


def test_g03_to_dict_json_serialisable():
    r = TopologyRecord(record_id="r1", event_kind="test", node_id="n1")
    json.dumps(r.to_dict())  # must not raise


# ===========================================================================
# H) TransportPathInfo dataclass
# ===========================================================================


def test_h01_transport_path_info_construction():
    t = TransportPathInfo(source_id="src", target_id="tgt")
    assert t.source_id == "src"
    assert t.target_id == "tgt"


def test_h02_to_dict_expected_keys():
    t = TransportPathInfo(source_id="src", target_id="tgt")
    d = t.to_dict()
    for key in ("source_id", "target_id", "effective_path", "fallback_path",
                "available_paths", "transport_strategy", "preferred_edge_id",
                "contract_version"):
        assert key in d, f"key {key!r} missing from TransportPathInfo.to_dict()"


# ===========================================================================
# I) TopologySnapshot dataclass
# ===========================================================================


def test_i01_snapshot_construction():
    s = TopologySnapshot()
    assert s.total_nodes == 0
    assert s.authority == NETWORK_TOPOLOGY_RUNTIME_AUTHORITY


def test_i02_to_dict_expected_keys():
    s = TopologySnapshot()
    d = s.to_dict()
    for key in ("authority", "total_nodes", "total_edges", "nodes_by_kind",
                "nodes_by_state", "edges_by_kind", "preferred_edges",
                "recent_records", "contract_version"):
        assert key in d, f"key {key!r} missing from TopologySnapshot.to_dict()"


def test_i03_to_dict_json_serialisable():
    s = TopologySnapshot()
    json.dumps(s.to_dict())  # must not raise


# ===========================================================================
# J) NetworkTopologyRuntime — node management
# ===========================================================================


def test_j01_register_node_returns_node():
    rt = get_network_topology_runtime()
    n = rt.register_node(TopologyNode(node_id="n1"))
    assert isinstance(n, TopologyNode)


def test_j02_register_node_empty_id_raises():
    rt = get_network_topology_runtime()
    with pytest.raises(ValueError):
        rt.register_node(TopologyNode(node_id=""))


def test_j03_registered_node_retrievable():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="n2", kind=TopologyNodeKind.DEVICE))
    assert rt.get_node("n2") is not None


def test_j04_get_node_returns_none_for_unknown():
    rt = get_network_topology_runtime()
    assert rt.get_node("ghost") is None


def test_j05_all_nodes_returns_list():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="n3"))
    assert isinstance(rt.all_nodes(), list)


def test_j06_register_node_idempotent():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="dup"))
    rt.register_node(TopologyNode(node_id="dup"))
    assert len([n for n in rt.all_nodes() if n.node_id == "dup"]) == 1


def test_j07_re_registration_preserves_registered_at():
    rt = get_network_topology_runtime()
    n = TopologyNode(node_id="dup2")
    rt.register_node(n)
    ts = rt.get_node("dup2").registered_at
    rt.register_node(TopologyNode(node_id="dup2"))
    assert rt.get_node("dup2").registered_at == ts


def test_j08_update_node_state_returns_node():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="ns1"))
    result = rt.update_node_state("ns1", TopologyConnectionState.CONNECTED)
    assert result is not None
    assert result.state == TopologyConnectionState.CONNECTED


def test_j09_update_node_state_none_for_unknown():
    rt = get_network_topology_runtime()
    assert rt.update_node_state("ghost", TopologyConnectionState.CONNECTED) is None


def test_j10_remove_node_returns_true():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="rem1"))
    assert rt.remove_node("rem1") is True


def test_j11_remove_node_returns_false_for_unknown():
    rt = get_network_topology_runtime()
    assert rt.remove_node("ghost") is False


def test_j12_remove_node_removes_from_all_nodes():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="rem2"))
    rt.remove_node("rem2")
    assert rt.get_node("rem2") is None


def test_j13_nodes_by_kind_filters():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="gw1", kind=TopologyNodeKind.GATEWAY))
    rt.register_node(TopologyNode(node_id="dev1", kind=TopologyNodeKind.DEVICE))
    gateways = rt.nodes_by_kind(TopologyNodeKind.GATEWAY)
    assert any(n.node_id == "gw1" for n in gateways)
    assert all(n.kind == TopologyNodeKind.GATEWAY for n in gateways)


def test_j14_nodes_by_state_filters():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="cn1", state=TopologyConnectionState.CONNECTED))
    rt.register_node(TopologyNode(node_id="un1", state=TopologyConnectionState.UNAVAILABLE))
    connected = rt.nodes_by_state(TopologyConnectionState.CONNECTED)
    assert any(n.node_id == "cn1" for n in connected)
    assert all(n.state == TopologyConnectionState.CONNECTED for n in connected)


# ===========================================================================
# K) NetworkTopologyRuntime — edge management
# ===========================================================================


def test_k01_register_edge_returns_edge():
    rt = get_network_topology_runtime()
    e = rt.register_edge(TopologyEdge(edge_id="e1", source_node_id="a", target_node_id="b"))
    assert isinstance(e, TopologyEdge)


def test_k02_register_edge_empty_id_raises():
    rt = get_network_topology_runtime()
    with pytest.raises(ValueError):
        rt.register_edge(TopologyEdge(edge_id="", source_node_id="a", target_node_id="b"))


def test_k03_all_edges_returns_list():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(edge_id="e2", source_node_id="a", target_node_id="b"))
    assert isinstance(rt.all_edges(), list)


def test_k04_edges_from_returns_edges():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(edge_id="ef1", source_node_id="src1", target_node_id="tgt1"))
    result = rt.edges_from("src1")
    assert any(e.edge_id == "ef1" for e in result)


def test_k05_edges_to_returns_edges():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(edge_id="et1", source_node_id="src2", target_node_id="tgt2"))
    result = rt.edges_to("tgt2")
    assert any(e.edge_id == "et1" for e in result)


def test_k06_update_edge_state_returns_edge():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(edge_id="eu1", source_node_id="a", target_node_id="b"))
    result = rt.update_edge_state("eu1", TopologyConnectionState.PREFERRED, preferred=True)
    assert result is not None
    assert result.state == TopologyConnectionState.PREFERRED
    assert result.preferred is True


def test_k07_update_edge_state_none_for_unknown():
    rt = get_network_topology_runtime()
    assert rt.update_edge_state("ghost", TopologyConnectionState.CONNECTED) is None


def test_k08_remove_edge_returns_true():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(edge_id="er1", source_node_id="a", target_node_id="b"))
    assert rt.remove_edge("er1") is True


def test_k09_remove_edge_returns_false_for_unknown():
    rt = get_network_topology_runtime()
    assert rt.remove_edge("ghost") is False


def test_k10_preferred_edges_returns_only_preferred():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="pref1", source_node_id="a", target_node_id="b", preferred=True))
    rt.register_edge(TopologyEdge(
        edge_id="notpref1", source_node_id="a", target_node_id="c", preferred=False))
    preferred = rt.preferred_edges()
    assert any(e.edge_id == "pref1" for e in preferred)
    assert all(e.preferred for e in preferred)


# ===========================================================================
# L) NetworkTopologyRuntime — observability
# ===========================================================================


def test_l01_topology_log_returns_deque():
    rt = get_network_topology_runtime()
    assert isinstance(rt.get_topology_log(), deque)


def test_l02_registration_emits_record():
    rt = get_network_topology_runtime()
    before = len(rt.get_topology_log())
    rt.register_node(TopologyNode(node_id="obs1"))
    after = len(rt.get_topology_log())
    assert after > before


def test_l03_state_change_emits_record():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="obs2"))
    before = len(rt.get_topology_log())
    rt.update_node_state("obs2", TopologyConnectionState.CONNECTED)
    after = len(rt.get_topology_log())
    assert after > before


def test_l04_removal_emits_record():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="obs3"))
    before = len(rt.get_topology_log())
    rt.remove_node("obs3")
    after = len(rt.get_topology_log())
    assert after > before


def test_l05_snapshot_returns_snapshot():
    rt = get_network_topology_runtime()
    s = rt.snapshot()
    assert isinstance(s, TopologySnapshot)


def test_l06_snapshot_total_nodes_correct():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="cnt1"))
    rt.register_node(TopologyNode(node_id="cnt2"))
    s = rt.snapshot()
    assert s.total_nodes >= 2


def test_l07_snapshot_nodes_by_kind_populated():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="gw2", kind=TopologyNodeKind.GATEWAY))
    s = rt.snapshot()
    assert "gateway" in s.nodes_by_kind


def test_l08_snapshot_nodes_by_state_populated():
    rt = get_network_topology_runtime()
    rt.register_node(TopologyNode(node_id="cn2", state=TopologyConnectionState.CONNECTED))
    s = rt.snapshot()
    assert "connected" in s.nodes_by_state


def test_l09_snapshot_edges_by_kind_populated():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="snap_e1", source_node_id="a", target_node_id="b",
        kind=TopologyEdgeKind.RELAY))
    s = rt.snapshot()
    assert "relay" in s.edges_by_kind


def test_l10_snapshot_preferred_edges_populated():
    rt = get_network_topology_runtime()
    rt.register_edge(TopologyEdge(
        edge_id="snap_pref", source_node_id="a", target_node_id="b", preferred=True))
    s = rt.snapshot()
    assert "snap_pref" in s.preferred_edges


# ===========================================================================
# M) Singleton behaviour
# ===========================================================================


def test_m01_get_returns_same_instance():
    a = get_network_topology_runtime()
    b = get_network_topology_runtime()
    assert a is b


def test_m02_reset_creates_new_instance():
    a = get_network_topology_runtime()
    reset_network_topology_runtime()
    b = get_network_topology_runtime()
    assert a is not b


# ===========================================================================
# N) NATS_BUS integration sentinel
# ===========================================================================


def test_n01_nats_bus_integration_sentinel():
    pytest.importorskip("pydantic", reason="pydantic not installed")
    from core.nats_bus import NETWORK_TOPOLOGY_RUNTIME_INTEGRATED
    assert isinstance(NETWORK_TOPOLOGY_RUNTIME_INTEGRATED, str)
    assert "NETWORK_TOPOLOGY_RUNTIME" in NETWORK_TOPOLOGY_RUNTIME_INTEGRATED


# ===========================================================================
# O) Gateway adapter integration sentinel
# ===========================================================================


def test_o01_gateway_adapter_integration_sentinel():
    pytest.importorskip("pydantic", reason="pydantic not installed")
    from galaxy_gateway.gateway_nats_adapter import NETWORK_TOPOLOGY_RUNTIME_INTEGRATED
    assert isinstance(NETWORK_TOPOLOGY_RUNTIME_INTEGRATED, str)
    assert "NETWORK_TOPOLOGY_RUNTIME" in NETWORK_TOPOLOGY_RUNTIME_INTEGRATED
