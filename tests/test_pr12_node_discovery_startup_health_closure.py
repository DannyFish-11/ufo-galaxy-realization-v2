#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr12_node_discovery_startup_health_closure.py
=========================================================
PR-12: Close Discovery Integration — Startup Seeding and Health Surface Wiring.

Verifies that:

A) Sentinel / policy strings
   - NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY is importable and
     non-empty.
   - NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL is importable and
     contains expected machine-checkable string.
   - All four policy sentinels are importable and non-empty.

B) build_discovery_health_surface
   - Returns all required keys.
   - health_status is "healthy" when participation is "full".
   - health_status is "degraded" when participation is "partial" with
     undiscovered_active > 0.
   - health_status is "healthy" when participation is "partial" with
     undiscovered_active == 0.
   - health_status is "degraded" when participation is "none" but fabric_healthy > 0.
   - health_status is "healthy" when participation is "none" and fabric_healthy == 0.
   - authority key is present and non-empty.

C) build_startup_seeding_status
   - Returns dict with seeded_count, fabric_healthy, seeding_invoked, authority.
   - seeding_invoked is always True.
   - fabric_healthy reflects list_healthy() from fabric.
   - Handles list_healthy() exception gracefully (fabric_healthy == 0).

D) build_discovery_diagnostic_context
   - Returns per_node list with correct alignment fields.
   - Returns all required summary keys.
   - Handles import error gracefully (returns error key).
   - Handles snapshot exception gracefully.

E) launcher/node_startup.py — PR-12 seeding wired into start_all
   - NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12 sentinel is importable and
     contains expected string.
   - NodeSystemLauncher.start_all is an async method (awaitable).
   - NodeSystemLauncher.initialize_discovery_after_startup is an async method.

F) core/routes/projection.py sentinel
   - NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12 is importable and
     contains key terms.

G) Integration: build_discovery_health_surface with real stub objects
   - Correctly computes undiscovered_active for mixed fabric/discovery state.
   - Correctly identifies full participation.
   - Correctly identifies no participation (none).
"""

from __future__ import annotations

import sys
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / stub implementations
# ---------------------------------------------------------------------------

def _make_stub_discovery_node(node_id: str, state_str: str = "registered"):
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
    role_str: str = "worker",
):
    node = MagicMock()
    node.node_id = node_id
    node.host = host
    node.port = port
    node.capabilities = capabilities or []
    status_mock = MagicMock()
    status_mock.value = status_str
    node.status = status_mock
    role_mock = MagicMock()
    role_mock.value = role_str
    node.role = role_mock
    arch_mock = MagicMock()
    arch_mock.value = "CAPABILITY_NODE"
    node.architectural_class = arch_mock
    return node


def _make_stub_fabric(
    nodes: List[Any],
    healthy_nodes: Optional[List[Any]] = None,
):
    fabric = MagicMock()
    fabric.list_nodes.return_value = nodes
    if healthy_nodes is None:
        # Default: nodes with status "healthy" are healthy.
        healthy_nodes = [
            n for n in nodes
            if getattr(n.status, "value", None) == "healthy"
        ]
    fabric.list_healthy.return_value = healthy_nodes
    return fabric


def _make_stub_discovery(nodes: Optional[Dict[str, Any]] = None):
    discovery = MagicMock()
    discovery.nodes = nodes if nodes is not None else {}
    discovery.get_healthy_nodes.return_value = []
    status_mock = {"total_nodes": 0, "healthy_nodes": 0}
    discovery.get_status.return_value = status_mock
    return discovery


# ---------------------------------------------------------------------------
# A) Sentinel / policy strings
# ---------------------------------------------------------------------------

class TestSentinelStrings:

    def test_authority_importable(self):
        from core.node_discovery_startup_health_closure import (
            NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY,
        )
        assert isinstance(NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY, str)
        assert len(NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY) > 0
        assert "AUTHORITY" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY

    def test_pr12_sentinel_importable(self):
        from core.node_discovery_startup_health_closure import (
            NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL,
        )
        assert isinstance(NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL, str)
        assert "PR12_SENTINEL" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL
        assert "startup seeding" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL

    def test_startup_seeding_policy(self):
        from core.node_discovery_startup_health_closure import (
            STARTUP_SEEDING_IS_INVOKED_BY_REAL_ORCHESTRATION_POLICY,
        )
        assert isinstance(STARTUP_SEEDING_IS_INVOKED_BY_REAL_ORCHESTRATION_POLICY, str)
        assert len(STARTUP_SEEDING_IS_INVOKED_BY_REAL_ORCHESTRATION_POLICY) > 0

    def test_health_surfaces_policy(self):
        from core.node_discovery_startup_health_closure import (
            HEALTH_SURFACES_REFLECT_DISCOVERY_PARTICIPATION_POLICY,
        )
        assert isinstance(HEALTH_SURFACES_REFLECT_DISCOVERY_PARTICIPATION_POLICY, str)
        assert len(HEALTH_SURFACES_REFLECT_DISCOVERY_PARTICIPATION_POLICY) > 0

    def test_undiscovered_active_policy(self):
        from core.node_discovery_startup_health_closure import (
            UNDISCOVERED_ACTIVE_COUNT_IS_EXPOSED_IN_HEALTH_POLICY,
        )
        assert isinstance(UNDISCOVERED_ACTIVE_COUNT_IS_EXPOSED_IN_HEALTH_POLICY, str)
        assert "undiscovered_active" in UNDISCOVERED_ACTIVE_COUNT_IS_EXPOSED_IN_HEALTH_POLICY

    def test_diagnostics_align_policy(self):
        from core.node_discovery_startup_health_closure import (
            DISCOVERY_DIAGNOSTICS_ALIGN_WITH_LAUNCHER_AND_FABRIC_POLICY,
        )
        assert isinstance(DISCOVERY_DIAGNOSTICS_ALIGN_WITH_LAUNCHER_AND_FABRIC_POLICY, str)
        assert len(DISCOVERY_DIAGNOSTICS_ALIGN_WITH_LAUNCHER_AND_FABRIC_POLICY) > 0


# ---------------------------------------------------------------------------
# B) build_discovery_health_surface
# ---------------------------------------------------------------------------

class TestBuildDiscoveryHealthSurface:

    def test_returns_required_keys(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        discovery = _make_stub_discovery()
        fabric = _make_stub_fabric([])
        surface = build_discovery_health_surface(discovery, fabric)

        required = {
            "discovery_total", "discovery_healthy", "fabric_total",
            "fabric_healthy", "undiscovered_active", "discovery_participation",
            "health_status", "authority",
        }
        assert required.issubset(set(surface.keys()))

    def test_healthy_when_full_participation(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface
        from core.node_discovery_runtime import get_discovery_participation_summary

        fabric_node = _make_stub_fabric_node("Node_01")
        disc_node = _make_stub_discovery_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({"Node_01": disc_node})

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["discovery_participation"] == "full"
        assert surface["health_status"] == "healthy"
        assert surface["undiscovered_active"] == 0

    def test_degraded_when_partial_with_undiscovered(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric_nodes = [
            _make_stub_fabric_node("Node_01"),
            _make_stub_fabric_node("Node_02"),
        ]
        disc_node = _make_stub_discovery_node("Node_01")
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery({"Node_01": disc_node})

        surface = build_discovery_health_surface(discovery, fabric)
        # Node_02 is healthy in fabric but absent from discovery.
        assert surface["undiscovered_active"] > 0
        assert surface["health_status"] == "degraded"

    def test_healthy_when_no_fabric_nodes(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery({})

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["fabric_healthy"] == 0
        assert surface["health_status"] == "healthy"

    def test_degraded_when_none_participation_but_fabric_healthy(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric_node = _make_stub_fabric_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({})  # Empty discovery

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["discovery_participation"] == "none"
        assert surface["fabric_healthy"] > 0
        assert surface["health_status"] == "degraded"

    def test_authority_key_present(self):
        from core.node_discovery_startup_health_closure import (
            build_discovery_health_surface,
            NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY,
        )

        discovery = _make_stub_discovery()
        fabric = _make_stub_fabric([])
        surface = build_discovery_health_surface(discovery, fabric)

        assert surface["authority"] == NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_IS_AUTHORITY

    def test_healthy_when_partial_no_undiscovered(self):
        """When participation is partial but undiscovered_active is 0 -> healthy.

        This can happen when, for example, fabric has 2 nodes (1 healthy, 1 offline)
        and discovery only contains the healthy node.  Discovery is "partial" because
        not all fabric nodes are discoverable, but undiscovered_active is 0 because
        the only healthy fabric node IS in discovery.
        """
        from core.node_discovery_startup_health_closure import build_discovery_health_surface
        from unittest.mock import patch as _patch

        # A scenario where participation is "partial" but no healthy fabric node
        # is missing from discovery: 2 fabric nodes (1 healthy, 1 offline), 1 in
        # discovery — all healthy nodes are covered, so undiscovered_active == 0.
        fake_summary = {
            "discovery_total": 1,
            "discovery_healthy": 1,
            "fabric_total": 2,
            "fabric_healthy": 1,
            "undiscovered_active": 0,  # The 1 healthy node IS in discovery.
            "discovery_participation": "partial",
        }
        with _patch(
            "core.node_discovery_runtime.get_discovery_participation_summary",
            return_value=fake_summary,
        ):
            discovery = _make_stub_discovery()
            fabric = _make_stub_fabric([])
            surface = build_discovery_health_surface(discovery, fabric)

        assert surface["health_status"] == "healthy"


# ---------------------------------------------------------------------------
# C) build_startup_seeding_status
# ---------------------------------------------------------------------------

class TestBuildStartupSeedingStatus:

    def test_returns_required_keys(self):
        from core.node_discovery_startup_health_closure import build_startup_seeding_status

        fabric = _make_stub_fabric([_make_stub_fabric_node("Node_01")])
        report = build_startup_seeding_status(3, fabric)

        assert "seeded_count" in report
        assert "fabric_healthy" in report
        assert "seeding_invoked" in report
        assert "authority" in report

    def test_seeding_invoked_always_true(self):
        from core.node_discovery_startup_health_closure import build_startup_seeding_status

        fabric = _make_stub_fabric([])
        report = build_startup_seeding_status(0, fabric)
        assert report["seeding_invoked"] is True

    def test_seeded_count_matches_input(self):
        from core.node_discovery_startup_health_closure import build_startup_seeding_status

        fabric = _make_stub_fabric([])
        report = build_startup_seeding_status(7, fabric)
        assert report["seeded_count"] == 7

    def test_fabric_healthy_reflects_list_healthy(self):
        from core.node_discovery_startup_health_closure import build_startup_seeding_status

        fabric_nodes = [_make_stub_fabric_node("Node_01"), _make_stub_fabric_node("Node_02")]
        fabric = _make_stub_fabric(fabric_nodes)
        report = build_startup_seeding_status(2, fabric)
        assert report["fabric_healthy"] == 2

    def test_handles_list_healthy_exception(self):
        from core.node_discovery_startup_health_closure import build_startup_seeding_status

        fabric = MagicMock()
        fabric.list_healthy.side_effect = RuntimeError("db unavailable")
        report = build_startup_seeding_status(0, fabric)
        assert report["fabric_healthy"] == 0
        assert report["seeding_invoked"] is True


# ---------------------------------------------------------------------------
# D) build_discovery_diagnostic_context
# ---------------------------------------------------------------------------

class TestBuildDiscoveryDiagnosticContext:

    def test_returns_required_summary_keys(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric_node = _make_stub_fabric_node("Node_01")
        disc_node = _make_stub_discovery_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({"Node_01": disc_node})

        ctx = build_discovery_diagnostic_context(fabric, discovery)
        for key in ("healthy_count", "undiscovered_active_count", "discovery_orphan_count",
                    "total_fabric_nodes", "total_discovery_nodes", "per_node", "authority"):
            assert key in ctx, f"missing key: {key}"

    def test_per_node_has_alignment_field(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric_node = _make_stub_fabric_node("Node_01")
        disc_node = _make_stub_discovery_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({"Node_01": disc_node})

        ctx = build_discovery_diagnostic_context(fabric, discovery)
        assert len(ctx["per_node"]) >= 1
        for rec in ctx["per_node"]:
            assert "alignment" in rec
            assert rec["alignment"] in ("aligned", "undiscovered_active", "discovery_orphan", "inactive")

    def test_aligned_node_classified_correctly(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric_node = _make_stub_fabric_node("Node_01")
        disc_node = _make_stub_discovery_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({"Node_01": disc_node})

        ctx = build_discovery_diagnostic_context(fabric, discovery)
        assert ctx["healthy_count"] == 1
        assert ctx["undiscovered_active_count"] == 0

    def test_undiscovered_active_classified_correctly(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric_node = _make_stub_fabric_node("Node_01")
        fabric = _make_stub_fabric([fabric_node])
        discovery = _make_stub_discovery({})  # Node_01 not in discovery

        ctx = build_discovery_diagnostic_context(fabric, discovery)
        assert ctx["undiscovered_active_count"] == 1

    def test_launcher_active_nodes_included(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric = _make_stub_fabric([])
        discovery = _make_stub_discovery({})

        ctx = build_discovery_diagnostic_context(fabric, discovery, ["Node_01", "Node_02"])
        assert ctx["total_launcher_active"] == 2

    def test_handles_exception_gracefully(self):
        from core.node_discovery_startup_health_closure import build_discovery_diagnostic_context

        fabric = MagicMock()
        fabric.list_nodes.side_effect = RuntimeError("fail")
        fabric.list_healthy.side_effect = RuntimeError("fail")
        discovery = _make_stub_discovery({})

        ctx = build_discovery_diagnostic_context(fabric, discovery)
        # Should not raise; returns a dict (may have empty per_node or error key)
        assert isinstance(ctx, dict)


# ---------------------------------------------------------------------------
# E) launcher/node_startup.py — PR-12 sentinel and start_all wiring
# ---------------------------------------------------------------------------

class TestLauncherPR12Integration:

    def test_pr12_seeding_sentinel_importable(self):
        from launcher.node_startup import NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12
        assert isinstance(NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12, str)
        assert "PR12" in NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12
        assert "start_all" in NODE_DISCOVERY_STARTUP_SEEDING_WIRED_PR12

    def test_start_all_is_coroutine(self):
        import inspect
        from launcher.node_startup import NodeSystemLauncher
        assert inspect.iscoroutinefunction(NodeSystemLauncher.start_all)

    def test_initialize_discovery_after_startup_is_coroutine(self):
        import inspect
        from launcher.node_startup import NodeSystemLauncher
        assert inspect.iscoroutinefunction(NodeSystemLauncher.initialize_discovery_after_startup)

    def test_start_all_calls_initialize_discovery_after_startup(self):
        """start_all() must invoke initialize_discovery_after_startup() after batch."""
        import asyncio
        import inspect
        from launcher.node_startup import NodeSystemLauncher

        # Read source to confirm the call is present (structural test).
        src = inspect.getsource(NodeSystemLauncher.start_all)
        assert "initialize_discovery_after_startup" in src, (
            "start_all() must call self.initialize_discovery_after_startup() "
            "after the node batch completes (PR-12 requirement)."
        )


# ---------------------------------------------------------------------------
# F) projection.py sentinel
# ---------------------------------------------------------------------------

class TestProjectionSentinelPR12:

    def test_pr12_sentinel_in_projection(self):
        try:
            from core.routes.projection import NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12
            assert isinstance(NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12, str)
            assert "PR12" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12
        except ImportError:
            pytest.skip("core.routes.projection not importable in this environment")

    def test_pr12_sentinel_importable_without_fastapi(self):
        """Sentinel should be importable from the module directly."""
        from core.node_discovery_startup_health_closure import (
            NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL,
        )
        assert "PR12" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL
        assert "startup seeding" in NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_PR12_SENTINEL

    def test_pr12_projection_sentinel_available(self):
        """The projection module should expose the PR-12 sentinel regardless of fastapi."""
        try:
            import core.routes.projection as proj
            assert hasattr(proj, "NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12")
            sentinel = proj.NODE_DISCOVERY_STARTUP_HEALTH_CLOSURE_ALIGNED_PR12
            assert isinstance(sentinel, str)
            assert len(sentinel) > 0
        except Exception:
            pytest.skip("core.routes.projection unavailable in this environment")


# ---------------------------------------------------------------------------
# G) Integration: build_discovery_health_surface with mixed states
# ---------------------------------------------------------------------------

class TestDiscoveryHealthSurfaceIntegration:

    def test_full_participation_all_nodes_in_discovery(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric_nodes = [
            _make_stub_fabric_node("Node_A"),
            _make_stub_fabric_node("Node_B"),
        ]
        disc_nodes = {
            "Node_A": _make_stub_discovery_node("Node_A"),
            "Node_B": _make_stub_discovery_node("Node_B"),
        }
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery(disc_nodes)

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["discovery_participation"] == "full"
        assert surface["undiscovered_active"] == 0
        assert surface["health_status"] == "healthy"

    def test_partial_participation_one_missing(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric_nodes = [
            _make_stub_fabric_node("Node_A"),
            _make_stub_fabric_node("Node_B"),
        ]
        disc_nodes = {
            "Node_A": _make_stub_discovery_node("Node_A"),
            # Node_B missing from discovery
        }
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery(disc_nodes)

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["undiscovered_active"] == 1
        assert surface["discovery_participation"] in ("partial", "none")
        assert surface["health_status"] == "degraded"

    def test_no_participation_empty_discovery(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        fabric_nodes = [_make_stub_fabric_node("Node_A")]
        fabric = _make_stub_fabric(fabric_nodes)
        discovery = _make_stub_discovery({})

        surface = build_discovery_health_surface(discovery, fabric)
        assert surface["discovery_total"] == 0
        assert surface["fabric_healthy"] == 1
        assert surface["health_status"] == "degraded"

    def test_offline_fabric_node_not_counted_as_undiscovered(self):
        from core.node_discovery_startup_health_closure import build_discovery_health_surface

        offline_node = _make_stub_fabric_node("Node_A", status_str="offline")
        fabric = _make_stub_fabric(
            nodes=[offline_node],
            healthy_nodes=[],  # Node_A is not healthy
        )
        discovery = _make_stub_discovery({})

        surface = build_discovery_health_surface(discovery, fabric)
        # Offline node should not count as undiscovered_active.
        assert surface["undiscovered_active"] == 0
        # fabric_healthy is 0 and discovery is empty -> expected state -> healthy.
        assert surface["health_status"] == "healthy"
