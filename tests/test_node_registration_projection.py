#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_node_registration_projection.py
==========================================
PR-7: Capability & Node Assimilation — tests for node registration
projection into the three canonical system graphs.

Coverage
--------
A) Network Graph Runtime — module structure
   - NETWORK_GRAPH_RUNTIME_AUTHORITY sentinel importable
   - NETWORK_GRAPH_RUNTIME_LAYER_POSITION is 7
   - NETWORK_GRAPH_CONTRACT_VERSION importable
   - All public names in __all__ importable

B) NetworkNodeRole enum
   - FABRIC_PARTICIPANT value
   - REACHABLE_ENDPOINT value
   - ROUTE_PARTICIPANT value
   - UNKNOWN value

C) NetworkEdgeKind enum
   - FABRIC_LINK value
   - ROUTE_HINT value
   - DEPENDENCY value

D) NetworkNode dataclass
   - construction with only node_id
   - to_dict() contains all expected keys
   - to_dict() role is a string
   - to_dict() is JSON-serialisable

E) NetworkEdge dataclass
   - construction with required fields
   - to_dict() contains all expected keys
   - to_dict() is JSON-serialisable

F) NetworkGraphRecord dataclass
   - construction
   - to_dict() contains all expected keys

G) NetworkGraphSnapshot dataclass
   - construction
   - to_dict() is JSON-serialisable
   - to_dict() contains expected keys

H) NetworkGraphRuntime — node management
   - register_node() returns NetworkNode
   - register_node() empty node_id raises ValueError
   - registered node is retrievable via get_node()
   - get_node() returns None for unknown node
   - all_nodes() returns list
   - register_node() idempotent (updates in place)
   - idempotent re-registration preserves registered_at
   - remove_node() returns True for known node
   - remove_node() returns False for unknown node
   - remove_node() removes node from all_nodes()

I) NetworkGraphRuntime — edge management
   - register_edge() returns NetworkEdge
   - register_edge() empty edge_id raises ValueError
   - all_edges() returns list
   - edges_from() returns edges for known node
   - edges_to() returns edges pointing to known node

J) NetworkGraphRuntime — observability
   - get_topology_log() returns a deque
   - registration emits a record
   - removal emits a record
   - snapshot() returns NetworkGraphSnapshot
   - snapshot() total_nodes is correct
   - snapshot() nodes_by_role is populated

K) Assimilation → network graph projection
   - assimilating a node projects it into network graph
   - projected_to_network_graph is True in record
   - network graph runtime contains the projected node
   - host/port are preserved in network node

L) Assimilation → task graph projection
   - assimilating a WORKER node projects to task graph runtime
   - projected_to_task_graph is True in record
   - LEGACY_FACADE nodes are NOT projected to task graph
   - FABRIC_PARTICIPANT nodes are NOT projected to task graph

M) Singleton behaviour
   - get_network_graph_runtime() returns same instance
   - reset_network_graph_runtime() creates new instance
"""

from __future__ import annotations

import json
from collections import deque

import pytest

import core.network_graph_runtime as _nmod
from core.network_graph_runtime import (
    NETWORK_GRAPH_CONTRACT_VERSION,
    NETWORK_GRAPH_RUNTIME_AUTHORITY,
    NETWORK_GRAPH_RUNTIME_LAYER_POSITION,
    NetworkEdge,
    NetworkEdgeKind,
    NetworkGraphRecord,
    NetworkGraphRuntime,
    NetworkGraphSnapshot,
    NetworkNode,
    NetworkNodeRole,
    get_network_graph_runtime,
    reset_network_graph_runtime,
)
from core.capability_assimilation import (
    NodeParticipantKind,
    get_capability_assimilation_layer,
    reset_capability_assimilation_layer,
)
from core.task_graph_runtime import (
    get_task_graph_runtime,
    reset_task_graph_runtime,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    reset_network_graph_runtime()
    reset_capability_assimilation_layer()
    reset_task_graph_runtime()
    yield
    reset_network_graph_runtime()
    reset_capability_assimilation_layer()
    reset_task_graph_runtime()


# ===========================================================================
# A) Module structure
# ===========================================================================


def test_a01_authority_sentinel_importable():
    assert NETWORK_GRAPH_RUNTIME_AUTHORITY


def test_a02_layer_position_is_7():
    assert NETWORK_GRAPH_RUNTIME_LAYER_POSITION == 7


def test_a03_contract_version_importable():
    assert NETWORK_GRAPH_CONTRACT_VERSION


def test_a04_all_public_names_importable():
    for name in _nmod.__all__:
        assert hasattr(_nmod, name), f"Missing: {name}"


# ===========================================================================
# B) NetworkNodeRole enum
# ===========================================================================


def test_b01_role_fabric_participant():
    assert NetworkNodeRole.FABRIC_PARTICIPANT.value == "fabric_participant"


def test_b02_role_reachable_endpoint():
    assert NetworkNodeRole.REACHABLE_ENDPOINT.value == "reachable_endpoint"


def test_b03_role_route_participant():
    assert NetworkNodeRole.ROUTE_PARTICIPANT.value == "route_participant"


def test_b04_role_unknown():
    assert NetworkNodeRole.UNKNOWN.value == "unknown"


# ===========================================================================
# C) NetworkEdgeKind enum
# ===========================================================================


def test_c01_edge_kind_fabric_link():
    assert NetworkEdgeKind.FABRIC_LINK.value == "fabric_link"


def test_c02_edge_kind_route_hint():
    assert NetworkEdgeKind.ROUTE_HINT.value == "route_hint"


def test_c03_edge_kind_dependency():
    assert NetworkEdgeKind.DEPENDENCY.value == "dependency"


# ===========================================================================
# D) NetworkNode dataclass
# ===========================================================================


def test_d01_network_node_minimal_construction():
    n = NetworkNode(node_id="n1")
    assert n.node_id == "n1"


def test_d02_network_node_to_dict_keys():
    n = NetworkNode(node_id="n1")
    d = n.to_dict()
    for key in ("node_id", "role", "host", "port", "transport_hints", "tags",
                "metadata", "registered_at", "last_updated_at"):
        assert key in d, f"Missing key: {key}"


def test_d03_network_node_to_dict_role_is_string():
    n = NetworkNode(node_id="n1", role=NetworkNodeRole.FABRIC_PARTICIPANT)
    assert isinstance(n.to_dict()["role"], str)


def test_d04_network_node_to_dict_json_serialisable():
    n = NetworkNode(node_id="n1")
    json.dumps(n.to_dict())  # should not raise


# ===========================================================================
# E) NetworkEdge dataclass
# ===========================================================================


def test_e01_network_edge_construction():
    e = NetworkEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    assert e.edge_id == "e1"


def test_e02_network_edge_to_dict_keys():
    e = NetworkEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    d = e.to_dict()
    for key in ("edge_id", "source_node_id", "target_node_id", "kind", "metadata", "created_at"):
        assert key in d, f"Missing key: {key}"


def test_e03_network_edge_to_dict_json_serialisable():
    e = NetworkEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    json.dumps(e.to_dict())  # should not raise


# ===========================================================================
# F) NetworkGraphRecord dataclass
# ===========================================================================


def test_f01_network_graph_record_construction():
    rec = NetworkGraphRecord(
        record_id="r1", event_kind="node_registered", node_id="n1"
    )
    assert rec.record_id == "r1"


def test_f02_network_graph_record_to_dict_keys():
    rec = NetworkGraphRecord(
        record_id="r1", event_kind="node_registered", node_id="n1"
    )
    d = rec.to_dict()
    for key in ("record_id", "event_kind", "node_id", "role", "timestamp", "details"):
        assert key in d, f"Missing key: {key}"


# ===========================================================================
# G) NetworkGraphSnapshot dataclass
# ===========================================================================


def test_g01_network_graph_snapshot_construction():
    snap = NetworkGraphSnapshot()
    assert snap.total_nodes == 0


def test_g02_network_graph_snapshot_to_dict_json_serialisable():
    snap = NetworkGraphSnapshot()
    json.dumps(snap.to_dict())  # should not raise


def test_g03_network_graph_snapshot_to_dict_keys():
    snap = NetworkGraphSnapshot()
    d = snap.to_dict()
    for key in ("authority", "total_nodes", "total_edges", "nodes_by_role", "recent_records"):
        assert key in d, f"Missing key: {key}"


# ===========================================================================
# H) NetworkGraphRuntime — node management
# ===========================================================================


def test_h01_register_node_returns_node():
    runtime = get_network_graph_runtime()
    n = NetworkNode(node_id="reg-1")
    result = runtime.register_node(n)
    assert isinstance(result, NetworkNode)


def test_h02_register_node_empty_id_raises():
    runtime = get_network_graph_runtime()
    with pytest.raises(ValueError):
        runtime.register_node(NetworkNode(node_id=""))


def test_h03_registered_node_retrievable():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="reg-2"))
    assert runtime.get_node("reg-2") is not None


def test_h04_get_node_returns_none_for_unknown():
    runtime = get_network_graph_runtime()
    assert runtime.get_node("ghost") is None


def test_h05_all_nodes_returns_list():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="list-1"))
    assert isinstance(runtime.all_nodes(), list)


def test_h06_re_registration_idempotent():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="dup-1"))
    runtime.register_node(NetworkNode(node_id="dup-1"))
    nodes = [n for n in runtime.all_nodes() if n.node_id == "dup-1"]
    assert len(nodes) == 1


def test_h07_re_registration_preserves_registered_at():
    runtime = get_network_graph_runtime()
    n = NetworkNode(node_id="dup-2")
    runtime.register_node(n)
    ts = runtime.get_node("dup-2").registered_at
    runtime.register_node(NetworkNode(node_id="dup-2"))
    assert runtime.get_node("dup-2").registered_at == ts


def test_h08_remove_node_returns_true():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="rem-1"))
    assert runtime.remove_node("rem-1") is True


def test_h09_remove_node_returns_false_for_unknown():
    runtime = get_network_graph_runtime()
    assert runtime.remove_node("ghost") is False


def test_h10_remove_node_removes_from_all_nodes():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="rem-2"))
    runtime.remove_node("rem-2")
    assert runtime.get_node("rem-2") is None


# ===========================================================================
# I) NetworkGraphRuntime — edge management
# ===========================================================================


def test_i01_register_edge_returns_edge():
    runtime = get_network_graph_runtime()
    e = NetworkEdge(edge_id="e1", source_node_id="a", target_node_id="b")
    result = runtime.register_edge(e)
    assert isinstance(result, NetworkEdge)


def test_i02_register_edge_empty_id_raises():
    runtime = get_network_graph_runtime()
    with pytest.raises(ValueError):
        runtime.register_edge(
            NetworkEdge(edge_id="", source_node_id="a", target_node_id="b")
        )


def test_i03_all_edges_returns_list():
    runtime = get_network_graph_runtime()
    runtime.register_edge(NetworkEdge(edge_id="e2", source_node_id="x", target_node_id="y"))
    assert isinstance(runtime.all_edges(), list)


def test_i04_edges_from_returns_edges():
    runtime = get_network_graph_runtime()
    runtime.register_edge(NetworkEdge(edge_id="ef1", source_node_id="src", target_node_id="tgt"))
    edges = runtime.edges_from("src")
    assert any(e.edge_id == "ef1" for e in edges)


def test_i05_edges_to_returns_edges():
    runtime = get_network_graph_runtime()
    runtime.register_edge(NetworkEdge(edge_id="et1", source_node_id="src2", target_node_id="tgt2"))
    edges = runtime.edges_to("tgt2")
    assert any(e.edge_id == "et1" for e in edges)


# ===========================================================================
# J) NetworkGraphRuntime — observability
# ===========================================================================


def test_j01_get_topology_log_returns_deque():
    runtime = get_network_graph_runtime()
    assert isinstance(runtime.get_topology_log(), deque)


def test_j02_registration_emits_record():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="obs-1"))
    log = list(runtime.get_topology_log())
    assert any(r.node_id == "obs-1" for r in log)


def test_j03_removal_emits_record():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="obs-2"))
    runtime.remove_node("obs-2")
    log = list(runtime.get_topology_log())
    removed_events = [r for r in log if r.event_kind == "node_removed"]
    assert len(removed_events) >= 1


def test_j04_snapshot_returns_snapshot():
    runtime = get_network_graph_runtime()
    snap = runtime.snapshot()
    assert isinstance(snap, NetworkGraphSnapshot)


def test_j05_snapshot_total_nodes_correct():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="snap-1"))
    runtime.register_node(NetworkNode(node_id="snap-2"))
    snap = runtime.snapshot()
    assert snap.total_nodes >= 2


def test_j06_snapshot_nodes_by_role_populated():
    runtime = get_network_graph_runtime()
    runtime.register_node(NetworkNode(node_id="role-1", role=NetworkNodeRole.FABRIC_PARTICIPANT))
    snap = runtime.snapshot()
    assert "fabric_participant" in snap.nodes_by_role


# ===========================================================================
# K) Assimilation → network graph projection
# ===========================================================================


def test_k01_assimilation_projects_to_network_graph():
    layer = get_capability_assimilation_layer()
    layer.assimilate("proj-net-1", host="10.0.0.1", port=8080)
    runtime = get_network_graph_runtime()
    node = runtime.get_node("proj-net-1")
    assert node is not None


def test_k02_projected_to_network_graph_true():
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate("proj-net-2")
    assert rec.projected_to_network_graph is True


def test_k03_network_node_has_correct_host_port():
    layer = get_capability_assimilation_layer()
    layer.assimilate("proj-net-3", host="192.168.1.1", port=9000)
    runtime = get_network_graph_runtime()
    node = runtime.get_node("proj-net-3")
    assert node.host == "192.168.1.1"
    assert node.port == 9000


# ===========================================================================
# L) Assimilation → task graph projection
# ===========================================================================


def test_l01_worker_node_projects_to_task_graph():
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate("worker-task-1", participant_kind=NodeParticipantKind.WORKER)
    assert rec.projected_to_task_graph is True


def test_l02_legacy_facade_not_projected_to_task_graph():
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate(
        "legacy-facade-1", participant_kind=NodeParticipantKind.LEGACY_FACADE
    )
    assert rec.projected_to_task_graph is False


def test_l03_fabric_participant_not_projected_to_task_graph():
    layer = get_capability_assimilation_layer()
    rec = layer.assimilate(
        "fabric-only-1", participant_kind=NodeParticipantKind.FABRIC_PARTICIPANT
    )
    assert rec.projected_to_task_graph is False


# ===========================================================================
# M) Singleton behaviour
# ===========================================================================


def test_m01_get_runtime_returns_same_instance():
    a = get_network_graph_runtime()
    b = get_network_graph_runtime()
    assert a is b


def test_m02_reset_creates_new_instance():
    a = get_network_graph_runtime()
    reset_network_graph_runtime()
    b = get_network_graph_runtime()
    assert a is not b
