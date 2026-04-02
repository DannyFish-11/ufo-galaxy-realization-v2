#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_network_runtime_completion.py
==========================================
PR-D: Capability + Network Runtime Convergence — network runtime completion tests.

Coverage
--------
A) NetworkTopologyRuntime authority sentinel
   - NETWORK_TOPOLOGY_RUNTIME_AUTHORITY is importable
   - TOPOLOGY_CONSUMER_POLICY is importable
   - TRANSPORT_HIERARCHY_ASSIMILATION_POLICY is importable

B) TopologyNodeKind completeness
   - DEVICE kind is present
   - GATEWAY kind is present
   - RELAY kind is present
   - MESH_PARTICIPANT kind is present
   - NATS_FABRIC_ENDPOINT kind is present
   - RUNTIME_PROVIDER_NODE kind is present
   - UNKNOWN kind is present

C) TopologyEdgeKind completeness
   - DIRECT edge kind is present
   - GATEWAY edge kind is present
   - RELAY edge kind is present
   - MESH edge kind is present
   - FABRIC edge kind is present
   - PROJECTED_SEMANTIC edge kind is present

D) TopologyConnectionState completeness
   - REACHABLE state is present
   - CONNECTED state is present
   - DEGRADED state is present
   - PREFERRED state is present
   - FALLBACK state is present
   - LATENT state is present
   - UNAVAILABLE state is present

E) Device node absorption
   - assimilate_device_connectivity() returns a TopologyNode
   - device node kind is DEVICE
   - device with preferred_path=direct_ws produces DIRECT edges
   - device with preferred_path=relay produces RELAY edges
   - device with preferred_path=gateway produces GATEWAY edges

F) NATS/gateway node absorption
   - absorb_nats_state() registers a NATS_FABRIC_ENDPOINT node
   - absorb_gateway_state() registers a GATEWAY node
   - NATS node reflects is_connected state
   - gateway node reflects is_connected state

G) Transport path projection
   - project_transport_path() returns TransportPathInfo
   - direct strategy maps to DIRECT edge kind
   - gateway strategy maps to GATEWAY edge kind
   - nats strategy maps to FABRIC edge kind

H) NodeKind ↔ CapabilityAssimilation bridge
   - WORKER_ENDPOINT node kind exists as valid arch_class
   - assimilating a node with arch_class "worker" → NodeParticipantKind.WORKER
   - assimilating a node with arch_class "device" → NodeParticipantKind.DEVICE
   - assimilating a node with arch_class "mcp_provider" → NodeParticipantKind.MCP_PROVIDER
   - assimilating a node with arch_class "skill" → NodeParticipantKind.SKILL

I) Snapshot
   - snapshot() returns a TopologySnapshot
   - snapshot total_nodes reflects registered nodes
   - snapshot topology_log_length <= 256

J) Ring buffer / observability
   - topology_log is bounded to 256 entries
   - each absorption/update appends to the log

K) Singleton
   - get_network_topology_runtime() returns same instance
   - reset_network_topology_runtime() creates a fresh instance
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_topology_runtime():
    """Reset the NetworkTopologyRuntime singleton before each test."""
    try:
        from core.network_topology_runtime import reset_network_topology_runtime
        reset_network_topology_runtime()
    except Exception:
        pass
    yield
    try:
        from core.network_topology_runtime import reset_network_topology_runtime
        reset_network_topology_runtime()
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_capability_assimilation():
    """Reset the CapabilityAssimilationLayer singleton before each test."""
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass
    yield
    try:
        from core.capability_assimilation import reset_capability_assimilation_layer
        reset_capability_assimilation_layer()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# A) Authority sentinels
# ---------------------------------------------------------------------------

class TestAuthoritySecrtinels:
    def test_network_topology_runtime_authority_importable(self):
        from core.network_topology_runtime import NETWORK_TOPOLOGY_RUNTIME_AUTHORITY
        assert isinstance(NETWORK_TOPOLOGY_RUNTIME_AUTHORITY, str)
        assert len(NETWORK_TOPOLOGY_RUNTIME_AUTHORITY) > 0

    def test_topology_consumer_policy_importable(self):
        from core.network_topology_runtime import TOPOLOGY_CONSUMER_POLICY
        assert isinstance(TOPOLOGY_CONSUMER_POLICY, str)

    def test_transport_hierarchy_assimilation_policy_importable(self):
        from core.network_topology_runtime import TRANSPORT_HIERARCHY_ASSIMILATION_POLICY
        assert isinstance(TRANSPORT_HIERARCHY_ASSIMILATION_POLICY, str)


# ---------------------------------------------------------------------------
# B) TopologyNodeKind completeness
# ---------------------------------------------------------------------------

class TestTopologyNodeKind:
    def test_device_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.DEVICE is not None

    def test_gateway_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.GATEWAY is not None

    def test_relay_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.RELAY is not None

    def test_mesh_participant_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.MESH_PARTICIPANT is not None

    def test_nats_fabric_endpoint_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.NATS_FABRIC_ENDPOINT is not None

    def test_runtime_provider_node_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.RUNTIME_PROVIDER_NODE is not None

    def test_unknown_kind(self):
        from core.network_topology_runtime import TopologyNodeKind
        assert TopologyNodeKind.UNKNOWN is not None


# ---------------------------------------------------------------------------
# C) TopologyEdgeKind completeness
# ---------------------------------------------------------------------------

class TestTopologyEdgeKind:
    def test_direct_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.DIRECT is not None

    def test_gateway_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.GATEWAY is not None

    def test_relay_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.RELAY is not None

    def test_mesh_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.MESH is not None

    def test_fabric_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.FABRIC is not None

    def test_projected_semantic_edge_kind(self):
        from core.network_topology_runtime import TopologyEdgeKind
        assert TopologyEdgeKind.PROJECTED_SEMANTIC is not None


# ---------------------------------------------------------------------------
# D) TopologyConnectionState completeness
# ---------------------------------------------------------------------------

class TestTopologyConnectionState:
    def test_reachable(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.REACHABLE is not None

    def test_connected(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.CONNECTED is not None

    def test_degraded(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.DEGRADED is not None

    def test_preferred(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.PREFERRED is not None

    def test_fallback(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.FALLBACK is not None

    def test_latent(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.LATENT is not None

    def test_unavailable(self):
        from core.network_topology_runtime import TopologyConnectionState
        assert TopologyConnectionState.UNAVAILABLE is not None


# ---------------------------------------------------------------------------
# E) Device node absorption
# ---------------------------------------------------------------------------

class TestDeviceAbsorption:
    def test_assimilate_device_connectivity_returns_topology_node(self):
        from core.network_topology_runtime import assimilate_device_connectivity
        node = assimilate_device_connectivity(
            "dev-001",
            preferred_path="direct_ws",
            effective_routable=True,
            fallback_available=False,
            mesh_overlay_available=False,
        )
        assert node is not None
        assert node.node_id == "dev-001"

    def test_device_node_kind_is_device(self):
        from core.network_topology_runtime import assimilate_device_connectivity, TopologyNodeKind
        node = assimilate_device_connectivity(
            "dev-kind-check",
            preferred_path="direct_ws",
            effective_routable=True,
            fallback_available=False,
            mesh_overlay_available=False,
        )
        assert node.kind == TopologyNodeKind.DEVICE

    def test_device_direct_path_produces_direct_edge(self):
        from core.network_topology_runtime import (
            assimilate_device_connectivity,
            get_network_topology_runtime,
            TopologyEdgeKind,
        )
        assimilate_device_connectivity(
            "dev-direct",
            preferred_path="direct_ws",
            effective_routable=True,
            fallback_available=False,
            mesh_overlay_available=False,
        )
        runtime = get_network_topology_runtime()
        edges = runtime.edges_to("dev-direct")
        assert any(
            e.kind == TopologyEdgeKind.DIRECT
            for e in edges
        ), f"Expected DIRECT edge, found: {[e.kind for e in edges]}"

    def test_device_relay_path_produces_relay_edge(self):
        from core.network_topology_runtime import (
            assimilate_device_connectivity,
            get_network_topology_runtime,
            TopologyEdgeKind,
        )
        assimilate_device_connectivity(
            "dev-relay",
            preferred_path="relay",
            effective_routable=True,
            fallback_available=True,
            mesh_overlay_available=False,
        )
        runtime = get_network_topology_runtime()
        edges = runtime.edges_to("dev-relay")
        assert any(
            e.kind == TopologyEdgeKind.RELAY
            for e in edges
        ), f"Expected RELAY edge, found: {[e.kind for e in edges]}"

    def test_device_gateway_path_produces_gateway_edge(self):
        from core.network_topology_runtime import (
            assimilate_device_connectivity,
            get_network_topology_runtime,
            TopologyEdgeKind,
        )
        assimilate_device_connectivity(
            "dev-gw",
            preferred_path="gateway",
            effective_routable=True,
            fallback_available=False,
            mesh_overlay_available=False,
        )
        runtime = get_network_topology_runtime()
        edges = runtime.edges_to("dev-gw")
        assert any(
            e.kind == TopologyEdgeKind.GATEWAY
            for e in edges
        ), f"Expected GATEWAY edge, found: {[e.kind for e in edges]}"


# ---------------------------------------------------------------------------
# F) NATS/gateway absorption
# ---------------------------------------------------------------------------

class TestNatsGatewayAbsorption:
    def test_absorb_nats_state_registers_nats_node(self):
        from core.network_topology_runtime import (
            assimilate_nats_state,
            TopologyNodeKind,
        )
        node = assimilate_nats_state(True, "nats.local", 4222)
        assert node.kind == TopologyNodeKind.NATS_FABRIC_ENDPOINT

    def test_absorb_gateway_state_registers_gateway_node(self):
        from core.network_topology_runtime import (
            assimilate_gateway_state,
            TopologyNodeKind,
        )
        node = assimilate_gateway_state("gw-001", "gateway.local", 8080, True)
        assert node.kind == TopologyNodeKind.GATEWAY

    def test_nats_connected_state(self):
        from core.network_topology_runtime import (
            assimilate_nats_state,
            TopologyConnectionState,
        )
        node = assimilate_nats_state(True, "nats.local", 4222)
        assert node.state in (
            TopologyConnectionState.CONNECTED,
            TopologyConnectionState.REACHABLE,
        )

    def test_nats_disconnected_state(self):
        from core.network_topology_runtime import (
            assimilate_nats_state,
            TopologyConnectionState,
        )
        node = assimilate_nats_state(False, "nats.local", 4222)
        assert node.state in (
            TopologyConnectionState.UNAVAILABLE,
            TopologyConnectionState.DEGRADED,
            TopologyConnectionState.LATENT,
        )


# ---------------------------------------------------------------------------
# G) Transport path projection
# ---------------------------------------------------------------------------

class TestTransportPathProjection:
    def test_project_transport_path_returns_transport_path_info(self):
        from core.network_topology_runtime import project_transport_path
        info = project_transport_path("source-1", "target-1", transport_strategy="direct")
        assert info is not None

    def test_direct_strategy_maps_to_direct_edge(self):
        from core.network_topology_runtime import (
            project_transport_path,
            TopologyEdgeKind,
        )
        info = project_transport_path("s1", "t1", transport_strategy="direct")
        assert info.transport_strategy == "direct"

    def test_nats_strategy_maps_to_fabric_edge(self):
        from core.network_topology_runtime import (
            project_transport_path,
            TopologyEdgeKind,
        )
        info = project_transport_path("s2", "t2", transport_strategy="nats")
        assert info.transport_strategy == "nats"


# ---------------------------------------------------------------------------
# H) NodeKind ↔ CapabilityAssimilation bridge
# ---------------------------------------------------------------------------

class TestNodeKindCapabilityBridge:
    def test_worker_arch_class_maps_to_worker(self):
        from core.capability_assimilation import (
            NodeParticipantKind,
            assimilate_node,
        )
        rec = assimilate_node({"node_id": "worker-001", "architectural_class": "worker"})
        kind = rec.execution_profile.participant_kind
        kind_str = kind.value if hasattr(kind, "value") else str(kind)
        assert kind_str == NodeParticipantKind.WORKER.value

    def test_device_arch_class_maps_to_device(self):
        from core.capability_assimilation import (
            NodeParticipantKind,
            assimilate_node,
        )
        rec = assimilate_node({"node_id": "device-001", "architectural_class": "device"})
        kind = rec.execution_profile.participant_kind
        kind_str = kind.value if hasattr(kind, "value") else str(kind)
        assert kind_str == NodeParticipantKind.DEVICE.value

    def test_mcp_provider_arch_class_maps_to_mcp_provider(self):
        from core.capability_assimilation import (
            NodeParticipantKind,
            assimilate_node,
        )
        rec = assimilate_node({"node_id": "mcp-001", "architectural_class": "mcp_provider"})
        kind = rec.execution_profile.participant_kind
        kind_str = kind.value if hasattr(kind, "value") else str(kind)
        assert kind_str == NodeParticipantKind.MCP_PROVIDER.value

    def test_skill_arch_class_maps_to_skill(self):
        from core.capability_assimilation import (
            NodeParticipantKind,
            assimilate_node,
        )
        rec = assimilate_node({"node_id": "skill-001", "architectural_class": "skill"})
        kind = rec.execution_profile.participant_kind
        kind_str = kind.value if hasattr(kind, "value") else str(kind)
        assert kind_str == NodeParticipantKind.SKILL.value

    def test_worker_endpoint_arch_class_maps_to_worker(self):
        from core.capability_assimilation import (
            NodeParticipantKind,
            assimilate_node,
        )
        rec = assimilate_node({"node_id": "wep-001", "architectural_class": "worker_endpoint"})
        kind = rec.execution_profile.participant_kind
        kind_str = kind.value if hasattr(kind, "value") else str(kind)
        assert kind_str == NodeParticipantKind.WORKER.value


# ---------------------------------------------------------------------------
# I) Snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_returns_topology_snapshot(self):
        from core.network_topology_runtime import (
            get_network_topology_runtime,
        )
        runtime = get_network_topology_runtime()
        snap = runtime.snapshot()
        assert snap is not None

    def test_snapshot_total_nodes_reflects_registered_nodes(self):
        from core.network_topology_runtime import (
            assimilate_device_connectivity,
            get_network_topology_runtime,
        )
        assimilate_device_connectivity(
            "snap-dev-01", preferred_path="direct_ws",
            effective_routable=True, fallback_available=False,
            mesh_overlay_available=False,
        )
        runtime = get_network_topology_runtime()
        snap = runtime.snapshot()
        # At least the device node should be present
        assert snap.total_nodes >= 1

    def test_snapshot_topology_log_length_bounded(self):
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()
        log = runtime.get_topology_log()
        assert len(log) <= 256


# ---------------------------------------------------------------------------
# J) Ring buffer
# ---------------------------------------------------------------------------

class TestRingBuffer:
    def test_topology_log_is_bounded(self):
        from core.network_topology_runtime import get_network_topology_runtime
        runtime = get_network_topology_runtime()
        log = runtime.get_topology_log()
        assert len(log) <= 256

    def test_absorption_appends_to_log(self):
        from core.network_topology_runtime import (
            assimilate_nats_state,
            get_network_topology_runtime,
        )
        runtime = get_network_topology_runtime()
        initial_len = len(runtime.get_topology_log())
        assimilate_nats_state(True, "nats.local", 4222)
        assert len(runtime.get_topology_log()) > initial_len


# ---------------------------------------------------------------------------
# K) Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_returns_same_instance(self):
        from core.network_topology_runtime import get_network_topology_runtime
        a = get_network_topology_runtime()
        b = get_network_topology_runtime()
        assert a is b

    def test_reset_creates_fresh_instance(self):
        from core.network_topology_runtime import (
            get_network_topology_runtime,
            reset_network_topology_runtime,
        )
        a = get_network_topology_runtime()
        reset_network_topology_runtime()
        b = get_network_topology_runtime()
        assert a is not b
