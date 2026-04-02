#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr509_capability_network_runtime_assimilation.py
============================================================
PR-509 — Capability + Network Runtime Assimilation: Tests.

Validates that:
* Canonical runtime layers are populated by representative runtime events.
* Capability assimilation absorbs executor/provider/device state changes.
* Planner/router/policy helpers read canonical runtime truth.
* Topology semantics sentinels clarify device/network vs model/provider domains.

Test groups
-----------
 A)  Module structure — authority sentinels importable and correct.
 B)  Topology semantics sentinels — DEVICE_NETWORK vs MODEL_PROVIDER domains.
 C)  NATS connectivity event → NetworkTopologyRuntime populated.
 D)  Gateway connectivity event → NetworkTopologyRuntime populated.
 E)  Device presence event → NetworkTopologyRuntime + CapabilityAssimilation.
 F)  Heartbeat event → CapabilityAssimilationLayer updated.
 G)  Capability change event → CapabilityAssimilationLayer updated.
 H)  Path change event → NetworkTopologyRuntime edge updated.
 I)  query_routable_executors — returns online executor list.
 J)  query_routable_executors — filters by required capabilities.
 K)  query_routable_executors — excludes offline nodes.
 L)  query_network_path — returns path from topology runtime.
 M)  query_network_path — unknown path returns is_reachable=False.
 N)  snapshot_canonical_runtime — returns unified snapshot.
 O)  nats_bus sentinel — CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable.
 P)  gateway_nats_adapter sentinel — CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable.
 Q)  capability_assimilation sentinel — CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable.
 R)  RoutableExecutor dataclass structure.
 S)  NetworkPathResult dataclass structure.
 T)  CanonicalRuntimeSnapshot dataclass structure.
 U)  Absorption is failure-isolated — topology errors do not propagate.
 V)  Integration — NATS absorb then query path shows live node.
 W)  Integration — device presence then query_routable_executors returns executor.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_topology():
    """Reset NetworkTopologyRuntime singleton for test isolation."""
    from core.network_topology_runtime import reset_network_topology_runtime
    reset_network_topology_runtime()


def _reset_capability():
    """Reset CapabilityAssimilationLayer singleton for test isolation."""
    from core.capability_assimilation import reset_capability_assimilation_layer
    reset_capability_assimilation_layer()


def _reset_all():
    _reset_topology()
    _reset_capability()


# ===========================================================================
# A)  Module structure
# ===========================================================================

class TestA_ModuleStructure(unittest.TestCase):
    """A) Authority sentinels importable and correct."""

    def test_A01_authority_importable(self) -> None:
        from core.capability_network_runtime_policy import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY,
        )
        self.assertIsInstance(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY, str)
        self.assertGreater(len(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY), 0)

    def test_A02_layer_position_is_9(self) -> None:
        from core.capability_network_runtime_policy import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_LAYER_POSITION,
        )
        self.assertEqual(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_LAYER_POSITION, 9)

    def test_A03_canonical_consumption_policy_importable(self) -> None:
        from core.capability_network_runtime_policy import CANONICAL_RUNTIME_CONSUMPTION_POLICY
        self.assertIsInstance(CANONICAL_RUNTIME_CONSUMPTION_POLICY, str)
        self.assertIn("CANONICAL_RUNTIME_CONSUMPTION_REQUIRED", CANONICAL_RUNTIME_CONSUMPTION_POLICY)

    def test_A04_all_symbols_importable(self) -> None:
        import core.capability_network_runtime_policy as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ member {name!r} not found in module",
            )

    def test_A05_sentinel_value_contains_pr509(self) -> None:
        from core.capability_network_runtime_policy import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY,
        )
        self.assertIn("PR-509", CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_AUTHORITY)


# ===========================================================================
# B)  Topology semantics sentinels
# ===========================================================================

class TestB_TopologySemantics(unittest.TestCase):
    """B) DEVICE_NETWORK vs MODEL_PROVIDER topology domains."""

    def test_B01_topology_semantics_disambiguation_importable(self) -> None:
        from core.capability_network_runtime_policy import TOPOLOGY_SEMANTICS_DISAMBIGUATION
        self.assertIsInstance(TOPOLOGY_SEMANTICS_DISAMBIGUATION, str)
        self.assertIn("TOPOLOGY_SEMANTICS_DISAMBIGUATION_V1", TOPOLOGY_SEMANTICS_DISAMBIGUATION)

    def test_B02_device_network_boundary_importable(self) -> None:
        from core.capability_network_runtime_policy import DEVICE_NETWORK_TOPOLOGY_BOUNDARY
        self.assertIsInstance(DEVICE_NETWORK_TOPOLOGY_BOUNDARY, str)
        self.assertIn("DEVICE_NETWORK_TOPOLOGY_DOMAIN", DEVICE_NETWORK_TOPOLOGY_BOUNDARY)

    def test_B03_model_provider_boundary_importable(self) -> None:
        from core.capability_network_runtime_policy import MODEL_PROVIDER_TOPOLOGY_BOUNDARY
        self.assertIsInstance(MODEL_PROVIDER_TOPOLOGY_BOUNDARY, str)
        self.assertIn("MODEL_PROVIDER_TOPOLOGY_DOMAIN", MODEL_PROVIDER_TOPOLOGY_BOUNDARY)

    def test_B04_device_network_boundary_covers_nats(self) -> None:
        from core.capability_network_runtime_policy import DEVICE_NETWORK_TOPOLOGY_BOUNDARY
        self.assertIn("NATS", DEVICE_NETWORK_TOPOLOGY_BOUNDARY)

    def test_B05_model_provider_not_redesigned_in_pr509(self) -> None:
        from core.capability_network_runtime_policy import MODEL_PROVIDER_TOPOLOGY_BOUNDARY
        self.assertIn("NOT redesigned in PR-509", MODEL_PROVIDER_TOPOLOGY_BOUNDARY)

    def test_B06_disambiguation_mentions_both_domains(self) -> None:
        from core.capability_network_runtime_policy import TOPOLOGY_SEMANTICS_DISAMBIGUATION
        self.assertIn("DEVICE/NETWORK", TOPOLOGY_SEMANTICS_DISAMBIGUATION)
        self.assertIn("MODEL/PROVIDER", TOPOLOGY_SEMANTICS_DISAMBIGUATION)


# ===========================================================================
# C)  NATS connectivity event → NetworkTopologyRuntime
# ===========================================================================

class TestC_NATSConnectivityEvent(unittest.TestCase):
    """C) absorb_nats_connectivity_event populates NetworkTopologyRuntime."""

    def setUp(self) -> None:
        _reset_all()

    def test_C01_absorb_nats_connected(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_nats_connectivity_event(is_connected=True, host="localhost", port=4222)
        rt = get_network_topology_runtime()
        snap = rt.snapshot()
        self.assertGreater(snap.total_nodes, 0)

    def test_C02_nats_node_kind_is_fabric_endpoint(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_nats_connectivity_event(is_connected=True, host="127.0.0.1", port=4222)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("nats_fabric")
        self.assertIsNotNone(node)
        self.assertEqual(node.kind.value, "nats_fabric_endpoint")

    def test_C03_nats_node_state_connected(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_nats_connectivity_event(is_connected=True, host="localhost", port=4222)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("nats_fabric")
        self.assertIsNotNone(node)
        self.assertEqual(node.state.value, "connected")

    def test_C04_nats_node_state_unavailable_on_disconnect(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_nats_connectivity_event(is_connected=True)
        absorb_nats_connectivity_event(is_connected=False)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("nats_fabric")
        self.assertIsNotNone(node)
        self.assertEqual(node.state.value, "unavailable")

    def test_C05_nats_absorption_non_blocking(self) -> None:
        """Absorption should not raise even with invalid arguments."""
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        # Should not raise
        absorb_nats_connectivity_event(is_connected=True, host="", port=0)

    def test_C06_nats_topology_record_created(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_nats_connectivity_event(is_connected=True, host="localhost", port=4222)
        rt = get_network_topology_runtime()
        snap = rt.snapshot()
        self.assertGreater(len(snap.recent_records), 0)


# ===========================================================================
# D)  Gateway connectivity event → NetworkTopologyRuntime
# ===========================================================================

class TestD_GatewayConnectivityEvent(unittest.TestCase):
    """D) absorb_gateway_connectivity_event populates NetworkTopologyRuntime."""

    def setUp(self) -> None:
        _reset_all()

    def test_D01_absorb_gateway_connected(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_gateway_connectivity_event(
            gateway_id="gw-001", host="10.0.0.1", port=8080, is_connected=True
        )
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("gw-001")
        self.assertIsNotNone(node)

    def test_D02_gateway_node_kind_is_gateway(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_gateway_connectivity_event(gateway_id="gw-test", is_connected=True)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("gw-test")
        self.assertIsNotNone(node)
        self.assertEqual(node.kind.value, "gateway")

    def test_D03_gateway_node_state_connected(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_gateway_connectivity_event(gateway_id="gw-live", is_connected=True)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("gw-live")
        self.assertEqual(node.state.value, "connected")

    def test_D04_gateway_node_state_unavailable_when_stopped(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_gateway_connectivity_event(gateway_id="gw-stop", is_connected=True)
        absorb_gateway_connectivity_event(gateway_id="gw-stop", is_connected=False)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("gw-stop")
        self.assertEqual(node.state.value, "unavailable")

    def test_D05_gateway_absorption_non_blocking(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        absorb_gateway_connectivity_event(gateway_id="gw-noop", is_connected=False)


# ===========================================================================
# E)  Device presence event → NetworkTopologyRuntime + CapabilityAssimilation
# ===========================================================================

class TestE_DevicePresenceEvent(unittest.TestCase):
    """E) absorb_device_presence_event populates both runtime layers."""

    def setUp(self) -> None:
        _reset_all()

    def test_E01_device_topology_node_created(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_device_presence_event(
            "device-pixel-001",
            is_online=True,
            preferred_path="direct_ws",
            effective_routable=True,
        )
        rt = get_network_topology_runtime()
        snap = rt.snapshot()
        self.assertGreater(snap.total_nodes, 0)

    def test_E02_device_capability_record_created(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        from core.capability_assimilation import get_capability_assimilation_layer
        absorb_device_presence_event(
            "device-e02",
            is_online=True,
            capabilities=["screen", "camera"],
        )
        layer = get_capability_assimilation_layer()
        record = layer.get_record("device-e02")
        self.assertIsNotNone(record)

    def test_E03_device_capabilities_stored(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        from core.capability_assimilation import get_capability_assimilation_layer
        absorb_device_presence_event(
            "device-e03",
            is_online=True,
            capabilities=["screen", "touch", "camera"],
        )
        layer = get_capability_assimilation_layer()
        record = layer.get_record("device-e03")
        self.assertIsNotNone(record)
        self.assertIn("screen", record.capability_descriptor.capabilities)
        self.assertIn("camera", record.capability_descriptor.capabilities)

    def test_E04_device_offline_marks_offline(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
        absorb_device_presence_event("device-e04", is_online=True, capabilities=["screen"])
        absorb_device_presence_event("device-e04", is_online=False)
        layer = get_capability_assimilation_layer()
        record = layer.get_record("device-e04")
        self.assertIsNotNone(record)
        self.assertEqual(
            record.fabric_presence.presence_state,
            AssimilationPresenceState.OFFLINE,
        )

    def test_E05_device_topology_state_reflects_routable(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_device_presence_event(
            "device-e05",
            is_online=True,
            preferred_path="direct_ws",
            effective_routable=True,
            host="10.0.1.50",
            port=8765,
        )
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            node = rt._nodes.get("device-e05")
        self.assertIsNotNone(node)
        self.assertNotEqual(node.state.value, "unavailable")


# ===========================================================================
# F)  Heartbeat event → CapabilityAssimilationLayer
# ===========================================================================

class TestF_HeartbeatEvent(unittest.TestCase):
    """F) absorb_heartbeat_event updates CapabilityAssimilationLayer."""

    def setUp(self) -> None:
        _reset_all()

    def _register_node(self, node_id: str) -> None:
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate(node_id, capabilities=["compute"])

    def test_F01_heartbeat_updates_known_node(self) -> None:
        from core.capability_network_runtime_policy import absorb_heartbeat_event
        from core.capability_assimilation import get_capability_assimilation_layer
        self._register_node("node-f01")
        result_before = get_capability_assimilation_layer().get_record("node-f01")
        count_before = result_before.fabric_presence.heartbeat_count
        absorb_heartbeat_event("node-f01", health_score=1.0)
        result_after = get_capability_assimilation_layer().get_record("node-f01")
        self.assertGreater(result_after.fabric_presence.heartbeat_count, count_before)

    def test_F02_heartbeat_low_score_sets_degraded(self) -> None:
        from core.capability_network_runtime_policy import absorb_heartbeat_event
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            AssimilationPresenceState,
        )
        self._register_node("node-f02")
        absorb_heartbeat_event("node-f02", health_score=0.2)
        record = get_capability_assimilation_layer().get_record("node-f02")
        self.assertEqual(
            record.fabric_presence.presence_state,
            AssimilationPresenceState.DEGRADED,
        )

    def test_F03_heartbeat_unknown_node_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_heartbeat_event
        # Should not raise for an unknown node
        absorb_heartbeat_event("node-not-registered", health_score=1.0)

    def test_F04_heartbeat_details_accepted(self) -> None:
        from core.capability_network_runtime_policy import absorb_heartbeat_event
        self._register_node("node-f04")
        absorb_heartbeat_event("node-f04", health_score=0.9, details={"cpu": 0.3})


# ===========================================================================
# G)  Capability change event → CapabilityAssimilationLayer
# ===========================================================================

class TestG_CapabilityChangeEvent(unittest.TestCase):
    """G) absorb_capability_change_event updates CapabilityAssimilationLayer."""

    def setUp(self) -> None:
        _reset_all()

    def test_G01_new_node_created_on_capability_change(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        from core.capability_assimilation import get_capability_assimilation_layer
        absorb_capability_change_event("exec-g01", capabilities=["llm", "vision"])
        record = get_capability_assimilation_layer().get_record("exec-g01")
        self.assertIsNotNone(record)

    def test_G02_capabilities_stored(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        from core.capability_assimilation import get_capability_assimilation_layer
        absorb_capability_change_event("exec-g02", capabilities=["llm", "code"])
        record = get_capability_assimilation_layer().get_record("exec-g02")
        self.assertIn("llm", record.capability_descriptor.capabilities)
        self.assertIn("code", record.capability_descriptor.capabilities)

    def test_G03_participant_kind_set(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        from core.capability_assimilation import get_capability_assimilation_layer, NodeParticipantKind
        absorb_capability_change_event(
            "exec-g03",
            capabilities=["mcp_tool"],
            participant_kind="mcp_provider",
        )
        record = get_capability_assimilation_layer().get_record("exec-g03")
        self.assertEqual(record.execution_profile.participant_kind, NodeParticipantKind.MCP_PROVIDER)

    def test_G04_invalid_participant_kind_falls_back_to_worker(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        from core.capability_assimilation import get_capability_assimilation_layer, NodeParticipantKind
        absorb_capability_change_event(
            "exec-g04",
            capabilities=["compute"],
            participant_kind="not_a_real_kind",
        )
        record = get_capability_assimilation_layer().get_record("exec-g04")
        self.assertEqual(record.execution_profile.participant_kind, NodeParticipantKind.WORKER)

    def test_G05_capability_change_is_failure_isolated(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        # Empty node_id — should not raise
        absorb_capability_change_event("", capabilities=["x"])


# ===========================================================================
# H)  Path change event → NetworkTopologyRuntime edge
# ===========================================================================

class TestH_PathChangeEvent(unittest.TestCase):
    """H) absorb_path_change_event updates NetworkTopologyRuntime edge."""

    def setUp(self) -> None:
        _reset_all()

    def test_H01_edge_created_on_path_change(self) -> None:
        from core.capability_network_runtime_policy import absorb_path_change_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_path_change_event("src-001", "tgt-001", transport_strategy="direct_ws")
        rt = get_network_topology_runtime()
        snap = rt.snapshot()
        self.assertGreater(snap.total_edges, 0)

    def test_H02_path_change_edge_has_strategy(self) -> None:
        from core.capability_network_runtime_policy import absorb_path_change_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_path_change_event("src-h02", "tgt-h02", transport_strategy="relay")
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            edges = [
                e for e in rt._edges.values()
                if e.source_node_id == "src-h02" and e.target_node_id == "tgt-h02"
            ]
        self.assertGreater(len(edges), 0)
        edge = edges[0]
        self.assertIn("relay", str(edge.metadata.get("transport_strategy", "")))

    def test_H03_fallback_flag_stored(self) -> None:
        from core.capability_network_runtime_policy import absorb_path_change_event
        from core.network_topology_runtime import get_network_topology_runtime
        absorb_path_change_event("src-h03", "tgt-h03", transport_strategy="relay", fallback_used=True)
        rt = get_network_topology_runtime()
        with rt._rw_lock:
            edges = [
                e for e in rt._edges.values()
                if e.source_node_id == "src-h03" and e.target_node_id == "tgt-h03"
            ]
        self.assertGreater(len(edges), 0)
        edge = edges[0]
        self.assertTrue(edge.metadata.get("fallback_used", False))

    def test_H04_path_change_non_blocking(self) -> None:
        from core.capability_network_runtime_policy import absorb_path_change_event
        absorb_path_change_event("", "", transport_strategy="noop")


# ===========================================================================
# I)  query_routable_executors — returns online executor list
# ===========================================================================

class TestI_QueryRoutableExecutors(unittest.TestCase):
    """I) query_routable_executors reads canonical runtime truth."""

    def setUp(self) -> None:
        _reset_all()

    def _add_online_executor(self, node_id: str, caps: list) -> None:
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate(node_id, capabilities=caps)

    def test_I01_returns_list(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        result = query_routable_executors()
        self.assertIsInstance(result, list)

    def test_I02_online_executor_returned(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        self._add_online_executor("exec-i02", ["llm"])
        results = query_routable_executors()
        node_ids = [r.node_id for r in results]
        self.assertIn("exec-i02", node_ids)

    def test_I03_result_items_are_routable_executor(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors, RoutableExecutor
        self._add_online_executor("exec-i03", ["compute"])
        results = query_routable_executors()
        self.assertTrue(all(isinstance(r, RoutableExecutor) for r in results))

    def test_I04_executor_has_capabilities(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        self._add_online_executor("exec-i04", ["vision", "ocr"])
        results = query_routable_executors()
        matching = [r for r in results if r.node_id == "exec-i04"]
        self.assertEqual(len(matching), 1)
        self.assertIn("vision", matching[0].capabilities)

    def test_I05_sorted_by_health_score_descending(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-i05a", capabilities=["x"])
        layer.assimilate("exec-i05b", capabilities=["y"])
        layer.heartbeat("exec-i05b", health_score=0.3)  # degraded
        results = query_routable_executors()
        scores = [r.health_score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))


# ===========================================================================
# J)  query_routable_executors — filters by required capabilities
# ===========================================================================

class TestJ_QueryRoutableByCapability(unittest.TestCase):
    """J) query_routable_executors filters by required_capabilities."""

    def setUp(self) -> None:
        _reset_all()

    def test_J01_filter_exact_match(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-j01-llm", capabilities=["llm"])
        layer.assimilate("exec-j01-ocr", capabilities=["ocr"])
        results = query_routable_executors(["llm"])
        node_ids = [r.node_id for r in results]
        self.assertIn("exec-j01-llm", node_ids)
        self.assertNotIn("exec-j01-ocr", node_ids)

    def test_J02_filter_multi_capability(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-j02-full", capabilities=["llm", "vision", "code"])
        layer.assimilate("exec-j02-partial", capabilities=["llm"])
        results = query_routable_executors(["llm", "vision"])
        node_ids = [r.node_id for r in results]
        self.assertIn("exec-j02-full", node_ids)
        self.assertNotIn("exec-j02-partial", node_ids)

    def test_J03_empty_capabilities_returns_all_online(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-j03-a", capabilities=["llm"])
        layer.assimilate("exec-j03-b", capabilities=["ocr"])
        results = query_routable_executors([])
        node_ids = [r.node_id for r in results]
        self.assertIn("exec-j03-a", node_ids)
        self.assertIn("exec-j03-b", node_ids)


# ===========================================================================
# K)  query_routable_executors — excludes offline nodes
# ===========================================================================

class TestK_QueryExcludesOffline(unittest.TestCase):
    """K) query_routable_executors excludes OFFLINE nodes."""

    def setUp(self) -> None:
        _reset_all()

    def test_K01_offline_node_excluded(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-k01", capabilities=["compute"])
        layer.mark_offline("exec-k01", reason="test")
        results = query_routable_executors()
        node_ids = [r.node_id for r in results]
        self.assertNotIn("exec-k01", node_ids)

    def test_K02_online_node_included(self) -> None:
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import get_capability_assimilation_layer
        layer = get_capability_assimilation_layer()
        layer.assimilate("exec-k02", capabilities=["compute"])
        results = query_routable_executors()
        node_ids = [r.node_id for r in results]
        self.assertIn("exec-k02", node_ids)


# ===========================================================================
# L)  query_network_path — returns path from topology runtime
# ===========================================================================

class TestL_QueryNetworkPath(unittest.TestCase):
    """L) query_network_path reads canonical network topology truth."""

    def setUp(self) -> None:
        _reset_all()

    def test_L01_returns_network_path_result(self) -> None:
        from core.capability_network_runtime_policy import query_network_path, NetworkPathResult
        result = query_network_path("src", "tgt")
        self.assertIsInstance(result, NetworkPathResult)

    def test_L02_source_target_ids_in_result(self) -> None:
        from core.capability_network_runtime_policy import query_network_path
        result = query_network_path("src-l02", "tgt-l02")
        self.assertEqual(result.source_id, "src-l02")
        self.assertEqual(result.target_id, "tgt-l02")

    def test_L03_path_found_after_absorb(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_path_change_event,
            query_network_path,
        )
        absorb_path_change_event("src-l03", "tgt-l03", transport_strategy="direct_ws")
        result = query_network_path("src-l03", "tgt-l03")
        self.assertEqual(result.source_id, "src-l03")
        self.assertEqual(result.target_id, "tgt-l03")

    def test_L04_reachable_when_connected_node(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_nats_connectivity_event,
            query_network_path,
        )
        absorb_nats_connectivity_event(is_connected=True, host="localhost", port=4222)
        result = query_network_path("local", "nats_fabric")
        # nats_fabric node exists in connected state → should be reachable
        self.assertTrue(result.is_reachable)


# ===========================================================================
# M)  query_network_path — unknown path returns is_reachable=False
# ===========================================================================

class TestM_QueryUnknownPath(unittest.TestCase):
    """M) query_network_path for unknown nodes returns is_reachable=False."""

    def setUp(self) -> None:
        _reset_all()

    def test_M01_unknown_source_and_target(self) -> None:
        from core.capability_network_runtime_policy import query_network_path
        result = query_network_path("ghost-src", "ghost-tgt")
        self.assertFalse(result.is_reachable)

    def test_M02_result_is_not_none(self) -> None:
        from core.capability_network_runtime_policy import query_network_path
        result = query_network_path("x", "y")
        self.assertIsNotNone(result)

    def test_M03_path_state_is_unknown(self) -> None:
        from core.capability_network_runtime_policy import query_network_path
        result = query_network_path("nobody", "nobody2")
        self.assertEqual(result.path_state, "unknown")


# ===========================================================================
# N)  snapshot_canonical_runtime — returns unified snapshot
# ===========================================================================

class TestN_SnapshotCanonicalRuntime(unittest.TestCase):
    """N) snapshot_canonical_runtime returns a CanonicalRuntimeSnapshot."""

    def setUp(self) -> None:
        _reset_all()

    def test_N01_returns_canonical_runtime_snapshot(self) -> None:
        from core.capability_network_runtime_policy import (
            snapshot_canonical_runtime,
            CanonicalRuntimeSnapshot,
        )
        snap = snapshot_canonical_runtime()
        self.assertIsInstance(snap, CanonicalRuntimeSnapshot)

    def test_N02_to_dict_is_serialisable(self) -> None:
        import json
        from core.capability_network_runtime_policy import snapshot_canonical_runtime
        snap = snapshot_canonical_runtime()
        d = snap.to_dict()
        # Should be JSON-serialisable
        json.dumps(d)

    def test_N03_executor_count_reflects_assimilation(self) -> None:
        from core.capability_assimilation import get_capability_assimilation_layer
        from core.capability_network_runtime_policy import snapshot_canonical_runtime
        layer = get_capability_assimilation_layer()
        layer.assimilate("snap-exec-1", capabilities=["llm"])
        layer.assimilate("snap-exec-2", capabilities=["vision"])
        snap = snapshot_canonical_runtime()
        self.assertGreaterEqual(snap.total_executors, 2)

    def test_N04_topology_node_count_reflects_nats(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_nats_connectivity_event,
            snapshot_canonical_runtime,
        )
        absorb_nats_connectivity_event(is_connected=True)
        snap = snapshot_canonical_runtime()
        self.assertGreater(snap.total_topology_nodes, 0)

    def test_N05_topology_domain_is_device_network(self) -> None:
        from core.capability_network_runtime_policy import (
            snapshot_canonical_runtime,
            DEVICE_NETWORK_TOPOLOGY_BOUNDARY,
        )
        snap = snapshot_canonical_runtime()
        self.assertEqual(snap.topology_domain, DEVICE_NETWORK_TOPOLOGY_BOUNDARY)

    def test_N06_routable_executors_is_list(self) -> None:
        from core.capability_network_runtime_policy import snapshot_canonical_runtime
        snap = snapshot_canonical_runtime()
        self.assertIsInstance(snap.routable_executors, list)


# ===========================================================================
# O)  nats_bus sentinel importable
# ===========================================================================

class TestO_NatsBusSentinel(unittest.TestCase):
    """O) CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable from nats_bus."""

    def test_O01_sentinel_importable(self) -> None:
        from core.nats_bus import CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED
        self.assertIsInstance(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED, str)

    def test_O02_sentinel_contains_nats_bus(self) -> None:
        from core.nats_bus import CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED
        self.assertIn("NATS_BUS", CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED)

    def test_O03_sentinel_version_tag(self) -> None:
        from core.nats_bus import CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED
        self.assertIn("V1", CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED)


# ===========================================================================
# P)  gateway_nats_adapter sentinel importable
# ===========================================================================

class TestP_GatewayAdapterSentinel(unittest.TestCase):
    """P) CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable from gateway_nats_adapter."""

    def test_P01_sentinel_importable(self) -> None:
        from galaxy_gateway.gateway_nats_adapter import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )
        self.assertIsInstance(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED, str)

    def test_P02_sentinel_contains_gateway_nats_adapter(self) -> None:
        from galaxy_gateway.gateway_nats_adapter import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )
        self.assertIn(
            "GATEWAY_NATS_ADAPTER",
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )

    def test_P03_sentinel_version_tag(self) -> None:
        from galaxy_gateway.gateway_nats_adapter import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )
        self.assertIn("V1", CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED)


# ===========================================================================
# Q)  capability_assimilation sentinel importable
# ===========================================================================

class TestQ_CapabilityAssimilationSentinel(unittest.TestCase):
    """Q) CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED importable from capability_assimilation."""

    def test_Q01_sentinel_importable(self) -> None:
        from core.capability_assimilation import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )
        self.assertIsInstance(CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED, str)

    def test_Q02_sentinel_value(self) -> None:
        from core.capability_assimilation import (
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )
        self.assertIn(
            "CAPABILITY_ASSIMILATION",
            CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED,
        )

    def test_Q03_sentinel_in_all(self) -> None:
        from core.capability_assimilation import __all__
        self.assertIn("CAPABILITY_NETWORK_RUNTIME_ASSIMILATION_INTEGRATED", __all__)


# ===========================================================================
# R)  RoutableExecutor dataclass structure
# ===========================================================================

class TestR_RoutableExecutorDataclass(unittest.TestCase):
    """R) RoutableExecutor dataclass structure and methods."""

    def test_R01_construction_with_defaults(self) -> None:
        from core.capability_network_runtime_policy import RoutableExecutor
        ex = RoutableExecutor(node_id="n1")
        self.assertEqual(ex.node_id, "n1")
        self.assertEqual(ex.participant_kind, "worker")
        self.assertEqual(ex.capabilities, [])
        self.assertEqual(ex.presence_state, "unknown")
        self.assertEqual(ex.network_state, "unknown")
        self.assertEqual(ex.health_score, 1.0)

    def test_R02_to_dict_contains_required_keys(self) -> None:
        from core.capability_network_runtime_policy import RoutableExecutor
        ex = RoutableExecutor(node_id="n2", capabilities=["llm"])
        d = ex.to_dict()
        for key in ("node_id", "participant_kind", "capabilities", "presence_state",
                    "network_state", "health_score", "host", "port"):
            self.assertIn(key, d)

    def test_R03_to_dict_is_json_serialisable(self) -> None:
        import json
        from core.capability_network_runtime_policy import RoutableExecutor
        ex = RoutableExecutor(node_id="n3", capabilities=["a", "b"])
        json.dumps(ex.to_dict())


# ===========================================================================
# S)  NetworkPathResult dataclass structure
# ===========================================================================

class TestS_NetworkPathResultDataclass(unittest.TestCase):
    """S) NetworkPathResult dataclass structure and methods."""

    def test_S01_construction_with_defaults(self) -> None:
        from core.capability_network_runtime_policy import NetworkPathResult
        r = NetworkPathResult(source_id="s", target_id="t")
        self.assertEqual(r.source_id, "s")
        self.assertEqual(r.target_id, "t")
        self.assertFalse(r.is_reachable)
        self.assertFalse(r.fallback_used)
        self.assertEqual(r.path_state, "unknown")

    def test_S02_to_dict_contains_required_keys(self) -> None:
        from core.capability_network_runtime_policy import NetworkPathResult
        r = NetworkPathResult(source_id="a", target_id="b")
        d = r.to_dict()
        for key in ("source_id", "target_id", "transport_strategy", "is_reachable",
                    "fallback_used", "edge_kind", "path_state", "latency_hint_ms"):
            self.assertIn(key, d)

    def test_S03_to_dict_is_json_serialisable(self) -> None:
        import json
        from core.capability_network_runtime_policy import NetworkPathResult
        r = NetworkPathResult(source_id="src", target_id="tgt", is_reachable=True)
        json.dumps(r.to_dict())


# ===========================================================================
# T)  CanonicalRuntimeSnapshot dataclass structure
# ===========================================================================

class TestT_CanonicalRuntimeSnapshotDataclass(unittest.TestCase):
    """T) CanonicalRuntimeSnapshot dataclass structure and methods."""

    def test_T01_construction_with_defaults(self) -> None:
        from core.capability_network_runtime_policy import CanonicalRuntimeSnapshot
        snap = CanonicalRuntimeSnapshot()
        self.assertEqual(snap.total_executors, 0)
        self.assertEqual(snap.total_topology_nodes, 0)
        self.assertIsInstance(snap.routable_executors, list)

    def test_T02_to_dict_contains_required_keys(self) -> None:
        from core.capability_network_runtime_policy import CanonicalRuntimeSnapshot
        snap = CanonicalRuntimeSnapshot()
        d = snap.to_dict()
        for key in ("timestamp", "total_executors", "online_executors",
                    "total_topology_nodes", "total_topology_edges",
                    "routable_executors", "topology_domain"):
            self.assertIn(key, d)

    def test_T03_to_dict_is_json_serialisable(self) -> None:
        import json
        from core.capability_network_runtime_policy import CanonicalRuntimeSnapshot
        snap = CanonicalRuntimeSnapshot()
        json.dumps(snap.to_dict())

    def test_T04_timestamp_is_positive_float(self) -> None:
        from core.capability_network_runtime_policy import CanonicalRuntimeSnapshot
        snap = CanonicalRuntimeSnapshot()
        self.assertGreater(snap.timestamp, 0)


# ===========================================================================
# U)  Absorption is failure-isolated
# ===========================================================================

class TestU_FailureIsolation(unittest.TestCase):
    """U) All absorption helpers are non-blocking — errors do not propagate."""

    def setUp(self) -> None:
        _reset_all()

    def test_U01_nats_absorb_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_nats_connectivity_event
        absorb_nats_connectivity_event(is_connected=True)
        absorb_nats_connectivity_event(is_connected=False)

    def test_U02_gateway_absorb_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_gateway_connectivity_event
        absorb_gateway_connectivity_event(gateway_id="gw", is_connected=True)
        absorb_gateway_connectivity_event(gateway_id="gw", is_connected=False)

    def test_U03_device_presence_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_device_presence_event
        absorb_device_presence_event("dev-u03", is_online=True)

    def test_U04_heartbeat_does_not_raise_for_unknown(self) -> None:
        from core.capability_network_runtime_policy import absorb_heartbeat_event
        absorb_heartbeat_event("nonexistent-node", health_score=0.9)

    def test_U05_capability_change_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_capability_change_event
        absorb_capability_change_event("exec-u05", capabilities=["x"])

    def test_U06_path_change_does_not_raise(self) -> None:
        from core.capability_network_runtime_policy import absorb_path_change_event
        absorb_path_change_event("a", "b")

    def test_U07_query_does_not_raise_on_empty_runtime(self) -> None:
        from core.capability_network_runtime_policy import (
            query_routable_executors,
            query_network_path,
            snapshot_canonical_runtime,
        )
        query_routable_executors()
        query_network_path("x", "y")
        snapshot_canonical_runtime()


# ===========================================================================
# V)  Integration — NATS absorb then query shows live node
# ===========================================================================

class TestV_IntegrationNATSLive(unittest.TestCase):
    """V) Integration: NATS connected → topology shows live NATS node."""

    def setUp(self) -> None:
        _reset_all()

    def test_V01_nats_node_visible_in_snapshot(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_nats_connectivity_event,
            snapshot_canonical_runtime,
        )
        absorb_nats_connectivity_event(is_connected=True, host="localhost", port=4222)
        snap = snapshot_canonical_runtime()
        self.assertGreater(snap.total_topology_nodes, 0)

    def test_V02_nats_node_queryable_via_path(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_nats_connectivity_event,
            query_network_path,
        )
        absorb_nats_connectivity_event(is_connected=True)
        result = query_network_path("local", "nats_fabric")
        self.assertTrue(result.is_reachable)

    def test_V03_nats_disconnect_makes_unavailable(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_nats_connectivity_event,
            query_network_path,
        )
        absorb_nats_connectivity_event(is_connected=True)
        absorb_nats_connectivity_event(is_connected=False)
        result = query_network_path("local", "nats_fabric")
        self.assertFalse(result.is_reachable)


# ===========================================================================
# W)  Integration — device presence then query returns executor
# ===========================================================================

class TestW_IntegrationDevicePresence(unittest.TestCase):
    """W) Integration: device presence event → query_routable_executors returns executor."""

    def setUp(self) -> None:
        _reset_all()

    def test_W01_device_appears_in_routable_executors(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_device_presence_event,
            query_routable_executors,
        )
        absorb_device_presence_event(
            "device-w01",
            is_online=True,
            capabilities=["screen", "camera"],
        )
        results = query_routable_executors()
        node_ids = [r.node_id for r in results]
        self.assertIn("device-w01", node_ids)

    def test_W02_device_offline_does_not_appear(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_device_presence_event,
            query_routable_executors,
        )
        absorb_device_presence_event(
            "device-w02",
            is_online=True,
            capabilities=["screen"],
        )
        absorb_device_presence_event("device-w02", is_online=False)
        results = query_routable_executors()
        node_ids = [r.node_id for r in results]
        self.assertNotIn("device-w02", node_ids)

    def test_W03_capability_filter_matches_device(self) -> None:
        from core.capability_network_runtime_policy import (
            absorb_device_presence_event,
            query_routable_executors,
        )
        absorb_device_presence_event(
            "device-w03-cam",
            is_online=True,
            capabilities=["camera", "screen"],
        )
        absorb_device_presence_event(
            "device-w03-no-cam",
            is_online=True,
            capabilities=["screen"],
        )
        results = query_routable_executors(["camera"])
        node_ids = [r.node_id for r in results]
        self.assertIn("device-w03-cam", node_ids)
        self.assertNotIn("device-w03-no-cam", node_ids)


if __name__ == "__main__":
    unittest.main()
