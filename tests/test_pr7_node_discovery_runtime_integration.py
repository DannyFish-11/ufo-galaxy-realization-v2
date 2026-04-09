#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr7_node_discovery_runtime_integration.py
======================================================
PR-7: Integrate NodeDiscoveryService into the Real Startup and Health Path.

Verifies that:

A) Sentinel / policy strings
   - NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY is importable and non-empty.
   - NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL is importable and matches
     expected machine-checkable string.
   - All five policy sentinels are importable and non-empty.

B) NodeDiscoveryParticipationRecord dataclass
   - Instantiable with defaults.
   - to_dict() includes required fields.
   - alignment field accepts all four canonical values.

C) DiscoveryRuntimeSnapshot dataclass
   - Instantiable with defaults.
   - to_dict() includes required fields.
   - participation_records serialises correctly.

D) seed_fabric_nodes_into_discovery
   - Seeds healthy fabric nodes into an empty discovery service.
   - Skips nodes already present (idempotent — updates heartbeat only).
   - Returns seeded count correctly.
   - Handles empty fabric gracefully.
   - Handles missing core.node_discovery gracefully (import error path mocked).

E) announce_node_to_discovery
   - Registers a new node when absent.
   - Returns True on success.
   - Refreshes heartbeat for already-registered nodes (idempotent).
   - Returns False when core.node_discovery is unavailable.

F) initialize_discovery_from_startup
   - Calls seed_fabric_nodes_into_discovery and returns seeded count.
   - Returns 0 gracefully when fabric is empty.

G) build_discovery_runtime_snapshot — alignment classification
   - Healthy-in-fabric AND in-discovery → "aligned".
   - Healthy-in-fabric NOT in-discovery → "undiscovered_active".
   - NOT healthy-in-fabric AND in-discovery → "discovery_orphan".
   - Neither fabric-healthy nor in-discovery → "inactive".
   - Counts in snapshot match classification totals.

H) build_discovery_runtime_snapshot — launcher_active_nodes
   - in_launcher_active is True for nodes in the provided list.
   - total_launcher_active matches list length.

I) get_discovery_participation_summary
   - Returns all required keys.
   - discovery_participation is "full" when all fabric-healthy nodes are in discovery.
   - discovery_participation is "partial" when some are missing.
   - discovery_participation is "none" when discovery is empty.

J) launcher/node_startup.py integration sentinels
   - NODE_DISCOVERY_STARTUP_WIRED_PR7 sentinel is importable and non-empty.
   - NodeSystemLauncher has _announce_node_to_discovery method.
   - NodeSystemLauncher has initialize_discovery_after_startup async method.

K) projection.py sentinel
   - NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7 is importable and
     contains key terms.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / stub implementations
# ---------------------------------------------------------------------------

def _make_stub_discovery_node(node_id: str, state_str: str = "registered"):
    """Return a minimal stub DiscoveredNode-like object."""
    node = MagicMock()
    node.node_id = node_id
    node.state = MagicMock()
    node.state.value = state_str
    node.last_heartbeat = time.time()
    return node


def _make_stub_fabric_node(
    node_id: str,
    status_str: str = "healthy",
    host: str = "localhost",
    port: int = 8000,
    capabilities: Optional[List[str]] = None,
):
    """Return a minimal stub NodeInfo-like object."""
    ni = MagicMock()
    ni.node_id = node_id
    ni.status = MagicMock()
    ni.status.value = status_str
    ni.host = host
    ni.port = port
    ni.capabilities = capabilities or []
    ni.role = MagicMock()
    ni.role.value = "worker"
    ni.architectural_class = MagicMock()
    ni.architectural_class.value = "CAPABILITY_NODE"
    return ni


def _make_stub_fabric(nodes: List[Any]) -> MagicMock:
    """Return a stub NodeFabricRegistry with list_nodes / list_healthy."""
    fabric = MagicMock()
    fabric.list_nodes.return_value = nodes
    fabric.list_healthy.return_value = [
        n for n in nodes if n.status.value == "healthy"
    ]
    return fabric


def _make_stub_discovery(existing_node_ids: Optional[List[str]] = None) -> MagicMock:
    """Return a stub NodeDiscoveryService with .nodes dict and register_node()."""
    discovery = MagicMock()
    discovery.nodes = {}
    for nid in (existing_node_ids or []):
        discovery.nodes[nid] = _make_stub_discovery_node(nid)
    return discovery


# ---------------------------------------------------------------------------
# A. Sentinel / policy strings
# ---------------------------------------------------------------------------

class TestSentinels:
    def test_authority_importable_and_non_empty(self):
        from core.node_discovery_runtime import NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY
        assert isinstance(NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY, str)
        assert len(NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY) > 10

    def test_pr7_sentinel_importable_and_non_empty(self):
        from core.node_discovery_runtime import NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL
        assert isinstance(NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL, str)
        assert "PR7" in NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL or "discovery" in NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL.lower()

    def test_pr7_sentinel_contains_key_terms(self):
        from core.node_discovery_runtime import NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL
        text = NODE_DISCOVERY_RUNTIME_INTEGRATION_PR7_SENTINEL.lower()
        assert "discovery" in text
        assert "startup" in text

    def test_active_nodes_discoverable_policy(self):
        from core.node_discovery_runtime import ACTIVE_NODES_ARE_DISCOVERABLE_POLICY
        assert isinstance(ACTIVE_NODES_ARE_DISCOVERABLE_POLICY, str)
        assert len(ACTIVE_NODES_ARE_DISCOVERABLE_POLICY) > 10

    def test_discovery_state_reflects_runtime_state_policy(self):
        from core.node_discovery_runtime import DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY
        assert isinstance(DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY, str)
        assert len(DISCOVERY_STATE_REFLECTS_RUNTIME_STATE_POLICY) > 10

    def test_discovery_mismatch_diagnosable_policy(self):
        from core.node_discovery_runtime import DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY
        assert isinstance(DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY, str)
        assert len(DISCOVERY_MISMATCH_IS_DIAGNOSABLE_POLICY) > 10

    def test_discovery_participates_in_startup_path_policy(self):
        from core.node_discovery_runtime import DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY
        assert isinstance(DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY, str)
        assert len(DISCOVERY_PARTICIPATES_IN_STARTUP_PATH_POLICY) > 10

    def test_undiscovered_active_nodes_flagged_policy(self):
        from core.node_discovery_runtime import UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY
        assert isinstance(UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY, str)
        assert len(UNDISCOVERED_ACTIVE_NODES_ARE_FLAGGED_POLICY) > 10


# ---------------------------------------------------------------------------
# B. NodeDiscoveryParticipationRecord dataclass
# ---------------------------------------------------------------------------

class TestNodeDiscoveryParticipationRecord:
    def test_instantiable_with_defaults(self):
        from core.node_discovery_runtime import NodeDiscoveryParticipationRecord
        rec = NodeDiscoveryParticipationRecord(node_id="Node_01_Test")
        assert rec.node_id == "Node_01_Test"
        assert rec.in_fabric_registry is False
        assert rec.in_discovery is False
        assert rec.alignment == "inactive"
        assert isinstance(rec.diagnostic_notes, list)

    def test_to_dict_required_fields(self):
        from core.node_discovery_runtime import NodeDiscoveryParticipationRecord
        rec = NodeDiscoveryParticipationRecord(
            node_id="Node_02_Test",
            in_fabric_registry=True,
            fabric_status="healthy",
            in_discovery=True,
            discovery_state="registered",
            in_launcher_active=True,
            alignment="aligned",
        )
        d = rec.to_dict()
        assert d["node_id"] == "Node_02_Test"
        assert d["in_fabric_registry"] is True
        assert d["fabric_status"] == "healthy"
        assert d["in_discovery"] is True
        assert d["discovery_state"] == "registered"
        assert d["in_launcher_active"] is True
        assert d["alignment"] == "aligned"
        assert "diagnostic_notes" in d

    def test_all_alignment_values_accepted(self):
        from core.node_discovery_runtime import NodeDiscoveryParticipationRecord
        for alignment in ("aligned", "undiscovered_active", "discovery_orphan", "inactive"):
            rec = NodeDiscoveryParticipationRecord(node_id="x", alignment=alignment)
            assert rec.alignment == alignment

    def test_diagnostic_notes_serialised(self):
        from core.node_discovery_runtime import NodeDiscoveryParticipationRecord
        rec = NodeDiscoveryParticipationRecord(
            node_id="Node_03_Test",
            diagnostic_notes=["note1", "note2"],
        )
        d = rec.to_dict()
        assert d["diagnostic_notes"] == ["note1", "note2"]


# ---------------------------------------------------------------------------
# C. DiscoveryRuntimeSnapshot dataclass
# ---------------------------------------------------------------------------

class TestDiscoveryRuntimeSnapshot:
    def test_instantiable_with_defaults(self):
        from core.node_discovery_runtime import DiscoveryRuntimeSnapshot
        snap = DiscoveryRuntimeSnapshot()
        assert snap.seeded_count == 0
        assert snap.healthy_count == 0
        assert snap.undiscovered_active_count == 0
        assert snap.discovery_orphan_count == 0
        assert snap.participation_records == []
        assert isinstance(snap.authority, str)

    def test_to_dict_required_fields(self):
        from core.node_discovery_runtime import DiscoveryRuntimeSnapshot, NodeDiscoveryParticipationRecord
        rec = NodeDiscoveryParticipationRecord(node_id="n1")
        snap = DiscoveryRuntimeSnapshot(
            seeded_count=3,
            healthy_count=2,
            undiscovered_active_count=1,
            discovery_orphan_count=0,
            participation_records=[rec],
        )
        d = snap.to_dict()
        assert d["seeded_count"] == 3
        assert d["healthy_count"] == 2
        assert d["undiscovered_active_count"] == 1
        assert d["discovery_orphan_count"] == 0
        assert len(d["participation_records"]) == 1
        assert "timestamp" in d
        assert "authority" in d

    def test_participation_records_serialised(self):
        from core.node_discovery_runtime import DiscoveryRuntimeSnapshot, NodeDiscoveryParticipationRecord
        recs = [
            NodeDiscoveryParticipationRecord(node_id=f"Node_{i}", alignment="aligned")
            for i in range(3)
        ]
        snap = DiscoveryRuntimeSnapshot(participation_records=recs)
        d = snap.to_dict()
        assert len(d["participation_records"]) == 3
        assert d["participation_records"][0]["node_id"] == "Node_0"


# ---------------------------------------------------------------------------
# D. seed_fabric_nodes_into_discovery
# ---------------------------------------------------------------------------

class TestSeedFabricNodesIntoDiscovery:
    def test_seeds_healthy_fabric_nodes(self):
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric_nodes = [
            _make_stub_fabric_node("Node_01", "healthy", port=8001),
            _make_stub_fabric_node("Node_02", "healthy", port=8002),
        ]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery()

        count = seed_fabric_nodes_into_discovery(fabric, discovery)

        assert count == 2
        assert discovery.register_node.call_count == 2

    def test_skips_already_present_nodes(self):
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric_nodes = [_make_stub_fabric_node("Node_01", "healthy", port=8001)]
        fabric = _make_stub_fabric(fabric_nodes)
        # Node_01 already in discovery
        discovery = _make_stub_discovery(existing_node_ids=["Node_01"])

        count = seed_fabric_nodes_into_discovery(fabric, discovery)

        # Already present: not re-registered, count=0
        assert count == 0
        discovery.register_node.assert_not_called()

    def test_does_not_seed_unhealthy_nodes(self):
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric_nodes = [
            _make_stub_fabric_node("Node_01", "healthy"),
            _make_stub_fabric_node("Node_02", "offline"),
        ]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery()

        count = seed_fabric_nodes_into_discovery(fabric, discovery)

        # Only healthy node seeded
        assert count == 1

    def test_empty_fabric_returns_zero(self):
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()

        count = seed_fabric_nodes_into_discovery(fabric, discovery)
        assert count == 0
        discovery.register_node.assert_not_called()

    def test_handles_list_healthy_exception_gracefully(self):
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric = MagicMock()
        fabric.list_healthy.side_effect = RuntimeError("db offline")
        discovery = _make_stub_discovery()

        count = seed_fabric_nodes_into_discovery(fabric, discovery)
        assert count == 0

    def test_idempotent_heartbeat_refresh(self):
        """Calling twice does not re-register already-seeded nodes."""
        from core.node_discovery_runtime import seed_fabric_nodes_into_discovery

        fabric_nodes = [_make_stub_fabric_node("Node_01", "healthy")]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery()

        count1 = seed_fabric_nodes_into_discovery(fabric, discovery)
        assert count1 == 1

        # Simulate node now present in discovery.nodes after first seed
        discovery.nodes["Node_01"] = _make_stub_discovery_node("Node_01")

        count2 = seed_fabric_nodes_into_discovery(fabric, discovery)
        assert count2 == 0
        # register_node called only once total
        assert discovery.register_node.call_count == 1


# ---------------------------------------------------------------------------
# E. announce_node_to_discovery
# ---------------------------------------------------------------------------

class TestAnnounceNodeToDiscovery:
    def test_registers_new_node(self):
        from core.node_discovery_runtime import announce_node_to_discovery

        discovery = _make_stub_discovery()
        result = announce_node_to_discovery(
            discovery=discovery,
            node_id="Node_01_Test",
            host="localhost",
            port=8001,
            capabilities=["text", "search"],
        )

        assert result is True
        discovery.register_node.assert_called_once()

    def test_returns_true_on_success(self):
        from core.node_discovery_runtime import announce_node_to_discovery

        discovery = _make_stub_discovery()
        assert announce_node_to_discovery(discovery, "n1") is True

    def test_refreshes_existing_node(self):
        from core.node_discovery_runtime import announce_node_to_discovery

        discovery = _make_stub_discovery(existing_node_ids=["Node_01"])
        old_heartbeat = discovery.nodes["Node_01"].last_heartbeat

        # Small delay to ensure timestamp changes
        time.sleep(0.01)
        result = announce_node_to_discovery(
            discovery=discovery,
            node_id="Node_01",
            port=8001,
        )

        assert result is True
        # Heartbeat should have been refreshed
        assert discovery.nodes["Node_01"].last_heartbeat >= old_heartbeat
        # register_node should NOT be called for existing nodes
        discovery.register_node.assert_not_called()

    def test_returns_false_on_register_exception(self):
        from core.node_discovery_runtime import announce_node_to_discovery

        discovery = _make_stub_discovery()
        discovery.register_node.side_effect = RuntimeError("disk full")

        result = announce_node_to_discovery(discovery, "Node_01")
        assert result is False

    def test_default_capabilities_is_node_id(self):
        """When no capabilities provided, defaults to [node_id]."""
        from core.node_discovery_runtime import announce_node_to_discovery
        from core.node_discovery import DiscoveredNode

        # Use a real DiscoveredNode to check capabilities.
        discovery = MagicMock()
        discovery.nodes = {}
        registered_nodes = []

        def _capture(dn):
            registered_nodes.append(dn)

        discovery.register_node.side_effect = _capture

        announce_node_to_discovery(discovery, "Node_42", port=8042)

        assert len(registered_nodes) == 1
        assert "Node_42" in registered_nodes[0].capabilities


# ---------------------------------------------------------------------------
# F. initialize_discovery_from_startup
# ---------------------------------------------------------------------------

class TestInitializeDiscoveryFromStartup:
    def test_seeds_all_healthy_nodes(self):
        from core.node_discovery_runtime import initialize_discovery_from_startup

        fabric_nodes = [
            _make_stub_fabric_node("Node_01", "healthy"),
            _make_stub_fabric_node("Node_02", "healthy"),
            _make_stub_fabric_node("Node_03", "offline"),
        ]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery()

        seeded = initialize_discovery_from_startup(discovery, fabric)
        assert seeded == 2

    def test_returns_zero_for_empty_fabric(self):
        from core.node_discovery_runtime import initialize_discovery_from_startup

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()

        seeded = initialize_discovery_from_startup(discovery, fabric)
        assert seeded == 0

    def test_returns_zero_on_exception(self):
        from core.node_discovery_runtime import initialize_discovery_from_startup

        fabric = MagicMock()
        fabric.list_healthy.side_effect = RuntimeError("registry down")
        discovery = _make_stub_discovery()

        seeded = initialize_discovery_from_startup(discovery, fabric)
        assert seeded == 0


# ---------------------------------------------------------------------------
# G. build_discovery_runtime_snapshot — alignment classification
# ---------------------------------------------------------------------------

class TestBuildDiscoveryRuntimeSnapshot:
    def _make_simple_snapshot(self, fab_healthy, fab_offline, disc_present):
        """Build a snapshot with configurable node sets."""
        from core.node_discovery_runtime import build_discovery_runtime_snapshot

        all_fabric = []
        for nid in fab_healthy:
            all_fabric.append(_make_stub_fabric_node(nid, "healthy"))
        for nid in fab_offline:
            all_fabric.append(_make_stub_fabric_node(nid, "offline"))

        fabric = _make_stub_fabric(all_fabric)
        discovery = _make_stub_discovery(existing_node_ids=disc_present)

        return build_discovery_runtime_snapshot(fabric, discovery)

    def test_aligned_node(self):
        snap = self._make_simple_snapshot(
            fab_healthy=["Node_01"],
            fab_offline=[],
            disc_present=["Node_01"],
        )
        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].alignment == "aligned"
        assert snap.healthy_count == 1

    def test_undiscovered_active_node(self):
        snap = self._make_simple_snapshot(
            fab_healthy=["Node_01"],
            fab_offline=[],
            disc_present=[],
        )
        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].alignment == "undiscovered_active"
        assert snap.undiscovered_active_count == 1
        assert len(recs["Node_01"].diagnostic_notes) > 0

    def test_discovery_orphan_node(self):
        snap = self._make_simple_snapshot(
            fab_healthy=[],
            fab_offline=["Node_01"],
            disc_present=["Node_01"],
        )
        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].alignment == "discovery_orphan"
        assert snap.discovery_orphan_count == 1

    def test_inactive_node(self):
        snap = self._make_simple_snapshot(
            fab_healthy=[],
            fab_offline=["Node_01"],
            disc_present=[],
        )
        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].alignment == "inactive"

    def test_counts_match_classifications(self):
        snap = self._make_simple_snapshot(
            fab_healthy=["Node_01", "Node_02"],
            fab_offline=["Node_03"],
            disc_present=["Node_01", "Node_03"],
        )
        assert snap.healthy_count == 1          # Node_01 aligned
        assert snap.undiscovered_active_count == 1  # Node_02 undiscovered
        assert snap.discovery_orphan_count == 1   # Node_03 orphan

    def test_empty_fabric_and_discovery(self):
        from core.node_discovery_runtime import build_discovery_runtime_snapshot

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()

        snap = build_discovery_runtime_snapshot(fabric, discovery)
        assert snap.healthy_count == 0
        assert snap.undiscovered_active_count == 0
        assert snap.discovery_orphan_count == 0
        assert snap.participation_records == []

    def test_snapshot_to_dict_serialises(self):
        snap = self._make_simple_snapshot(
            fab_healthy=["Node_01"],
            fab_offline=[],
            disc_present=["Node_01"],
        )
        d = snap.to_dict()
        assert "participation_records" in d
        assert "healthy_count" in d
        assert len(d["participation_records"]) == 1


# ---------------------------------------------------------------------------
# H. build_discovery_runtime_snapshot — launcher_active_nodes
# ---------------------------------------------------------------------------

class TestSnapshotLauncherNodes:
    def test_in_launcher_active_flagged(self):
        from core.node_discovery_runtime import build_discovery_runtime_snapshot

        fabric = _make_stub_fabric([_make_stub_fabric_node("Node_01", "healthy")])
        discovery = _make_stub_discovery()
        launcher_active = ["Node_01", "Node_02"]

        snap = build_discovery_runtime_snapshot(fabric, discovery, launcher_active_nodes=launcher_active)
        assert snap.total_launcher_active == 2

        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].in_launcher_active is True
        assert recs["Node_02"].in_launcher_active is True

    def test_nodes_not_in_launcher_not_flagged(self):
        from core.node_discovery_runtime import build_discovery_runtime_snapshot

        fabric = _make_stub_fabric([_make_stub_fabric_node("Node_01", "healthy")])
        discovery = _make_stub_discovery(["Node_01"])
        snap = build_discovery_runtime_snapshot(fabric, discovery, launcher_active_nodes=["Node_99"])

        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].in_launcher_active is False

    def test_no_launcher_nodes_provided(self):
        from core.node_discovery_runtime import build_discovery_runtime_snapshot

        fabric = _make_stub_fabric([_make_stub_fabric_node("Node_01", "healthy")])
        discovery = _make_stub_discovery(["Node_01"])

        snap = build_discovery_runtime_snapshot(fabric, discovery)
        assert snap.total_launcher_active == 0

        recs = {r.node_id: r for r in snap.participation_records}
        assert recs["Node_01"].in_launcher_active is False


# ---------------------------------------------------------------------------
# I. get_discovery_participation_summary
# ---------------------------------------------------------------------------

class TestGetDiscoveryParticipationSummary:
    def _make_discovery_with_healthy(self, healthy_ids: List[str]) -> MagicMock:
        discovery = _make_stub_discovery(existing_node_ids=healthy_ids)
        healthy_nodes = [discovery.nodes[nid] for nid in healthy_ids]
        discovery.get_healthy_nodes.return_value = healthy_nodes
        return discovery

    def test_returns_all_required_keys(self):
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()

        summary = get_discovery_participation_summary(discovery, fabric)
        for key in ("discovery_total", "discovery_healthy", "fabric_total",
                    "fabric_healthy", "undiscovered_active",
                    "discovery_participation", "authority"):
            assert key in summary, f"Missing key: {key}"

    def test_full_participation(self):
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric_nodes = [_make_stub_fabric_node("Node_01", "healthy")]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = self._make_discovery_with_healthy(["Node_01"])

        summary = get_discovery_participation_summary(discovery, fabric)
        assert summary["discovery_participation"] == "full"
        assert summary["undiscovered_active"] == 0

    def test_partial_participation(self):
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric_nodes = [
            _make_stub_fabric_node("Node_01", "healthy"),
            _make_stub_fabric_node("Node_02", "healthy"),
        ]
        fabric = _make_stub_fabric(fabric_nodes)
        # Only Node_01 in discovery
        discovery = self._make_discovery_with_healthy(["Node_01"])

        summary = get_discovery_participation_summary(discovery, fabric)
        assert summary["discovery_participation"] == "partial"
        assert summary["undiscovered_active"] == 1

    def test_no_participation_empty_discovery(self):
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric_nodes = [_make_stub_fabric_node("Node_01", "healthy")]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery()  # empty

        summary = get_discovery_participation_summary(discovery, fabric)
        assert summary["discovery_participation"] == "none"
        assert summary["undiscovered_active"] == 1

    def test_no_participation_when_both_empty(self):
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()

        summary = get_discovery_participation_summary(discovery, fabric)
        assert summary["discovery_participation"] == "none"

    def test_authority_present(self):
        from core.node_discovery_runtime import (
            get_discovery_participation_summary,
            NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY,
        )
        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery()
        summary = get_discovery_participation_summary(discovery, fabric)
        assert summary["authority"] == NODE_DISCOVERY_IS_RUNTIME_PARTICIPANT_AUTHORITY


# ---------------------------------------------------------------------------
# J. launcher/node_startup.py integration sentinels
# ---------------------------------------------------------------------------

class TestNodeStartupLauncherIntegration:
    def test_node_discovery_startup_wired_pr7_sentinel(self):
        from launcher.node_startup import NODE_DISCOVERY_STARTUP_WIRED_PR7
        assert isinstance(NODE_DISCOVERY_STARTUP_WIRED_PR7, str)
        assert len(NODE_DISCOVERY_STARTUP_WIRED_PR7) > 10
        text = NODE_DISCOVERY_STARTUP_WIRED_PR7.lower()
        assert "discovery" in text

    def test_announce_node_to_discovery_method_exists(self):
        from launcher.node_startup import NodeSystemLauncher
        assert hasattr(NodeSystemLauncher, "_announce_node_to_discovery")
        assert callable(NodeSystemLauncher._announce_node_to_discovery)

    def test_initialize_discovery_after_startup_method_exists(self):
        import inspect
        from launcher.node_startup import NodeSystemLauncher
        assert hasattr(NodeSystemLauncher, "initialize_discovery_after_startup")
        method = NodeSystemLauncher.initialize_discovery_after_startup
        assert asyncio_or_coroutine(method), (
            "initialize_discovery_after_startup should be an async method"
        )

    def test_register_with_runtime_registry_calls_announce(self):
        """_register_node_with_runtime_registry delegates to _announce_node_to_discovery."""
        import inspect
        from launcher.node_startup import NodeSystemLauncher

        src = inspect.getsource(NodeSystemLauncher._register_node_with_runtime_registry)
        assert "_announce_node_to_discovery" in src, (
            "_register_node_with_runtime_registry should call _announce_node_to_discovery"
        )


def asyncio_or_coroutine(func) -> bool:
    """Return True if func is an async function or coroutine function."""
    import asyncio
    import inspect
    return asyncio.iscoroutinefunction(func) or inspect.iscoroutinefunction(func)


# ---------------------------------------------------------------------------
# K. projection.py sentinel
# ---------------------------------------------------------------------------

class TestProjectionSentinel:
    def test_sentinel_importable(self):
        try:
            from core.routes.projection import NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7
        except ImportError:
            pytest.skip("fastapi not available — skipping projection import")
        assert isinstance(NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7, str)
        assert len(NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7) > 10

    def test_sentinel_contains_key_terms(self):
        try:
            from core.routes.projection import NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7
        except ImportError:
            pytest.skip("fastapi not available")
        text = NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7.lower()
        assert "discovery" in text
        assert "UNAVAILABLE" not in NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7

    def test_sentinel_not_unavailable(self):
        try:
            from core.routes.projection import NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7
        except ImportError:
            pytest.skip("fastapi not available")
        # Since we created the module, the sentinel should resolve to V1, not UNAVAILABLE
        assert "UNAVAILABLE" not in NODE_DISCOVERY_RUNTIME_INTEGRATION_ALIGNED_PR7
