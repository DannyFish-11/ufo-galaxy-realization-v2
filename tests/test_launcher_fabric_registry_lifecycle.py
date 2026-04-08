#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_launcher_fabric_registry_lifecycle.py
=================================================
Canonical NodeFabricRegistry lifecycle hooks — launcher integration tests.

Verifies that:

A) Sentinel
   - CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS is importable and non-empty.
   - Sentinel contains key terms confirming lifecycle hooks are wired.

B) _register_node_in_canonical_registry — happy path (HEALTHY)
   - Calling with status "healthy" registers the node in NodeFabricRegistry.
   - Registered node has status HEALTHY.
   - Registered node stores port correctly.
   - Registered node has launcher_managed=True in metadata.
   - Re-calling with status "healthy" updates (idempotent) without error.

C) _register_node_in_canonical_registry — failure path (OFFLINE)
   - Calling with status "offline" registers the node with OFFLINE status.
   - Already-registered node status updated to OFFLINE on re-call.

D) _register_node_in_canonical_registry — node_configs metadata
   - Dependencies from node_configs are stored in NodeInfo.dependencies.
   - Group metadata is stored in NodeInfo.metadata.

E) _register_node_in_canonical_registry — graceful import failure
   - If NodeFabricRegistry is unavailable, method does not raise.

F) stop_node — canonical registry update
   - stop_node() marks the node OFFLINE in NodeFabricRegistry.
   - stop_node() calls service_manager.stop_service().
   - stop_node() returns True when service was stopped.
   - stop_node() returns False when service was not found.

G) start_node failure → canonical registry
   - When service_manager.start_service returns False, node is registered
     as OFFLINE in NodeFabricRegistry.

H) Health-check timeout → canonical registry
   - Simulated health-check timeout registers node as OFFLINE.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from typing import Optional

import pytest

from core.nodes.node_fabric_registry import (
    get_node_fabric_registry,
    reset_node_fabric_registry,
    NodeStatus,
    NodeRole,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_launcher(node_configs=None):
    """Return a NodeSystemLauncher with mocked service_manager and config."""
    from launcher.node_startup import NodeSystemLauncher

    launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
    launcher.service_manager = MagicMock()
    launcher.service_manager.stop_service = MagicMock(return_value=True)
    launcher.config = MagicMock()
    launcher.config.web_ui_port = 9000
    from pathlib import Path
    launcher.nodes_dir = Path("/tmp/nonexistent_nodes_dir")
    launcher.node_configs = node_configs or {}
    return launcher


@pytest.fixture(autouse=True)
def _reset_fabric():
    """Reset NodeFabricRegistry singleton between tests."""
    reset_node_fabric_registry()
    yield
    reset_node_fabric_registry()


# ---------------------------------------------------------------------------
# A) Sentinel
# ---------------------------------------------------------------------------

class TestSentinel:
    def test_sentinel_importable(self):
        from launcher.node_startup import CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS
        assert isinstance(CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS, str)

    def test_sentinel_non_empty(self):
        from launcher.node_startup import CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS
        assert len(CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS) > 0

    def test_sentinel_contains_canonical_registry(self):
        from launcher.node_startup import CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS
        assert "NodeFabricRegistry" in CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS

    def test_sentinel_contains_lifecycle_hooks(self):
        from launcher.node_startup import CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS
        assert "lifecycle" in CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS.lower()

    def test_sentinel_v1_marker(self):
        from launcher.node_startup import CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS
        assert "V1" in CANONICAL_FABRIC_REGISTRY_LIFECYCLE_HOOKS


# ---------------------------------------------------------------------------
# B) _register_node_in_canonical_registry — happy path (HEALTHY)
# ---------------------------------------------------------------------------

class TestRegisterNodeHappyPath:
    def test_healthy_status_registers_node(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_A", 8080, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_A")
        assert node is not None

    def test_healthy_status_is_healthy(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_B", 8081, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_B")
        assert node.status == NodeStatus.HEALTHY

    def test_healthy_port_stored(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_C", 8082, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_C")
        assert node.port == 8082

    def test_healthy_launcher_managed_metadata(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_D", 8083, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_D")
        assert node.metadata.get("launcher_managed") is True

    def test_healthy_idempotent_no_error(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_E", 8084, "healthy")
        # Re-call should not raise
        launcher._register_node_in_canonical_registry("Node_Test_E", 8084, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_E")
        assert node is not None
        assert node.status == NodeStatus.HEALTHY

    def test_none_port_stored_as_zero(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Test_F", None, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Test_F")
        assert node.port == 0


# ---------------------------------------------------------------------------
# C) _register_node_in_canonical_registry — failure path (OFFLINE)
# ---------------------------------------------------------------------------

class TestRegisterNodeFailurePath:
    def test_offline_status_registers_node(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Fail_A", 8090, "offline")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Fail_A")
        assert node is not None

    def test_offline_status_is_offline(self):
        launcher = _make_launcher()
        launcher._register_node_in_canonical_registry("Node_Fail_B", 8091, "offline")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Fail_B")
        assert node.status == NodeStatus.OFFLINE

    def test_already_registered_updated_to_offline(self):
        launcher = _make_launcher()
        # First register as healthy
        launcher._register_node_in_canonical_registry("Node_Fail_C", 8092, "healthy")
        fabric = get_node_fabric_registry()
        assert fabric.get("Node_Fail_C").status == NodeStatus.HEALTHY
        # Then mark offline
        launcher._register_node_in_canonical_registry("Node_Fail_C", 8092, "offline")
        assert fabric.get("Node_Fail_C").status == NodeStatus.OFFLINE


# ---------------------------------------------------------------------------
# D) node_configs metadata
# ---------------------------------------------------------------------------

class TestNodeConfigsMetadata:
    def test_dependencies_stored(self):
        node_configs = {
            "Node_Meta_A": {
                "port": 8100,
                "group": "core",
                "dependencies": ["Node_Meta_B", "Node_Meta_C"],
                "description": "Test node",
                "startup_policy": "active",
            }
        }
        launcher = _make_launcher(node_configs)
        launcher._register_node_in_canonical_registry("Node_Meta_A", 8100, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Meta_A")
        assert "Node_Meta_B" in node.dependencies
        assert "Node_Meta_C" in node.dependencies

    def test_group_stored_in_metadata(self):
        node_configs = {
            "Node_Meta_D": {
                "port": 8101,
                "group": "development",
                "dependencies": [],
                "description": "Dev node",
                "startup_policy": "active",
            }
        }
        launcher = _make_launcher(node_configs)
        launcher._register_node_in_canonical_registry("Node_Meta_D", 8101, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Meta_D")
        assert node.metadata.get("group") == "development"

    def test_core_group_maps_to_worker_role(self):
        node_configs = {
            "Node_Meta_E": {
                "port": 8102,
                "group": "core",
                "dependencies": [],
                "description": "",
                "startup_policy": "active",
            }
        }
        launcher = _make_launcher(node_configs)
        launcher._register_node_in_canonical_registry("Node_Meta_E", 8102, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Meta_E")
        assert node.role == NodeRole.WORKER

    def test_development_group_maps_to_tool_role(self):
        node_configs = {
            "Node_Meta_F": {
                "port": 8103,
                "group": "development",
                "dependencies": [],
                "description": "",
                "startup_policy": "active",
            }
        }
        launcher = _make_launcher(node_configs)
        launcher._register_node_in_canonical_registry("Node_Meta_F", 8103, "healthy")
        fabric = get_node_fabric_registry()
        node = fabric.get("Node_Meta_F")
        assert node.role == NodeRole.TOOL


# ---------------------------------------------------------------------------
# E) Graceful import failure
# ---------------------------------------------------------------------------

class TestGracefulImportFailure:
    def test_no_raise_on_import_error(self):
        launcher = _make_launcher()
        with patch.dict("sys.modules", {"core.nodes.node_fabric_registry": None}):
            # Should not raise even if module is unavailable
            try:
                launcher._register_node_in_canonical_registry(
                    "Node_Import_A", 8110, "healthy"
                )
            except Exception as exc:
                pytest.fail(f"Unexpected exception: {exc}")


# ---------------------------------------------------------------------------
# F) stop_node
# ---------------------------------------------------------------------------

class TestStopNode:
    def test_stop_node_marks_offline_in_registry(self):
        launcher = _make_launcher()
        # First register as healthy
        launcher._register_node_in_canonical_registry("Node_Stop_A", 8120, "healthy")
        fabric = get_node_fabric_registry()
        assert fabric.get("Node_Stop_A").status == NodeStatus.HEALTHY
        # stop_node should mark OFFLINE
        launcher.stop_node("Node_Stop_A")
        assert fabric.get("Node_Stop_A").status == NodeStatus.OFFLINE

    def test_stop_node_calls_stop_service(self):
        launcher = _make_launcher()
        launcher.stop_node("Node_Stop_B")
        launcher.service_manager.stop_service.assert_called_once_with("Node_Stop_B")

    def test_stop_node_returns_true_when_stopped(self):
        launcher = _make_launcher()
        launcher.service_manager.stop_service.return_value = True
        result = launcher.stop_node("Node_Stop_C")
        assert result is True

    def test_stop_node_returns_false_when_not_found(self):
        launcher = _make_launcher()
        launcher.service_manager.stop_service.return_value = False
        result = launcher.stop_node("Node_Stop_D")
        assert result is False


# ---------------------------------------------------------------------------
# G) start_node process failure → canonical registry
# ---------------------------------------------------------------------------

class TestStartNodeProcessFailure:
    def test_process_start_failure_registers_offline(self):
        """When service_manager.start_service returns False, node is OFFLINE."""
        from launcher.node_startup import NodeSystemLauncher
        from pathlib import Path
        import sys
        import types
        import tempfile

        # Create a real node dir with main.py for the launcher to find
        with tempfile.TemporaryDirectory() as tmpdir:
            node_name = "Node_ProcFail_A"
            node_dir = Path(tmpdir) / node_name
            node_dir.mkdir()
            (node_dir / "main.py").write_text("# stub")

            launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
            launcher.service_manager = MagicMock()
            launcher.service_manager.register_service = MagicMock()
            launcher.service_manager.start_service = AsyncMock(return_value=False)
            launcher.config = MagicMock()
            launcher.config.web_ui_port = 9000
            launcher.nodes_dir = Path(tmpdir)
            launcher.node_configs = {
                node_name: {"port": 8130, "group": "core", "dependencies": [],
                            "startup_policy": "active"}
            }

            # Stub aiohttp if not installed
            _aiohttp_stub = types.ModuleType("aiohttp")
            _aiohttp_stub.ClientSession = MagicMock
            _aiohttp_stub.ClientTimeout = MagicMock
            _orig = sys.modules.get("aiohttp")
            if _orig is None:
                sys.modules["aiohttp"] = _aiohttp_stub

            try:
                result = asyncio.run(launcher.start_node(node_name))
            finally:
                if _orig is None:
                    sys.modules.pop("aiohttp", None)

        assert result is False
        fabric = get_node_fabric_registry()
        node = fabric.get(node_name)
        assert node is not None, "Node should be in registry after start failure"
        assert node.status == NodeStatus.OFFLINE


# ---------------------------------------------------------------------------
# H) Health-check timeout → canonical registry
# ---------------------------------------------------------------------------

class TestHealthCheckTimeout:
    def test_health_check_timeout_registers_offline(self):
        """After health-check timeout, node is registered as OFFLINE."""
        from launcher.node_startup import NodeSystemLauncher
        from pathlib import Path
        import sys
        import types
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            node_name = "Node_HCTimeout_A"
            node_dir = Path(tmpdir) / node_name
            node_dir.mkdir()
            (node_dir / "main.py").write_text("# stub")

            launcher = NodeSystemLauncher.__new__(NodeSystemLauncher)
            launcher.service_manager = MagicMock()
            launcher.service_manager.register_service = MagicMock()
            launcher.service_manager.start_service = AsyncMock(return_value=True)
            launcher.service_manager.services = {}
            launcher.config = MagicMock()
            launcher.config.web_ui_port = 9000
            launcher.nodes_dir = Path(tmpdir)
            launcher.node_configs = {
                node_name: {"port": 8140, "group": "core", "dependencies": [],
                            "startup_policy": "active"}
            }

            # Build a minimal aiohttp stub that makes all health requests fail
            class _FakeGetCtx:
                async def __aenter__(self):
                    raise Exception("connection refused")
                async def __aexit__(self, *a):
                    pass

            class _FakeSession:
                def __init__(self, *a, **kw):
                    pass
                async def __aenter__(self):
                    return self
                async def __aexit__(self, *a):
                    pass
                def get(self, *a, **kw):
                    return _FakeGetCtx()

            _aiohttp_stub = types.ModuleType("aiohttp")
            _aiohttp_stub.ClientSession = _FakeSession
            _aiohttp_stub.ClientTimeout = MagicMock(return_value=None)
            _orig = sys.modules.get("aiohttp")
            sys.modules["aiohttp"] = _aiohttp_stub

            try:
                with patch("launcher.node_startup.asyncio.sleep", new=AsyncMock()):
                    result = asyncio.run(launcher.start_node(node_name))
            finally:
                if _orig is None:
                    sys.modules.pop("aiohttp", None)
                else:
                    sys.modules["aiohttp"] = _orig

        assert result is False
        fabric = get_node_fabric_registry()
        node = fabric.get(node_name)
        assert node is not None, "Node should be in registry after health-check timeout"
        assert node.status == NodeStatus.OFFLINE
