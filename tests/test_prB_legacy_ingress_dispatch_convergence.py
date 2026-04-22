#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_prB_legacy_ingress_dispatch_convergence.py
======================================================
PR-B — Legacy Ingress/Dispatch Convergence onto Execution Spine.

Validates that the three legacy dispatch paths identified as bypassing the
execution spine (CommandRouter.route_envelope) have been converged:

  1. ``core.device_orchestrator.DeviceOrchestrator.send_command``
     Previously: recorded ingress, then dispatched directly to NodeRegistry.
     Now: attempts CommandRouter.route_envelope() first; NodeRegistry fallback.

  2. ``core.scheduler.Scheduler._exec_relay`` (relay_to_device)
     Previously: recorded ingress, then dispatched directly to ProxyRelay.
     Now: attempts CommandRouter.route_envelope() first; ProxyRelay fallback.

  3. ``core.scheduler.Scheduler._exec_mesh_send`` (mesh_send)
     Previously: recorded ingress, then dispatched directly to MeshCoordinator.
     Now: attempts CommandRouter.route_envelope() first; MeshCoordinator fallback.

Convergence criteria
--------------------
A. Each path exposes a sentinel constant confirming the convergence.
B. When a CommandRouter is present, route_envelope() is called (spine path).
C. When CommandRouter raises / is absent, the legacy fallback executes.
D. The LegacyDispatchRegistry contains PR-B entries for each path.
E. LEGACY_PATH_REGISTRY in legacy_paths contains PR-B entries for each path.
F. The ingress log records an entry for each path (record_legacy_ingress).

All tests are self-contained (no live servers, no real devices).
"""

from __future__ import annotations

import asyncio
import sys
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ===========================================================================
# A. Sentinel constants
# ===========================================================================

class TestPRBSentinels(unittest.TestCase):
    """Sentinel constants confirm each path has been converged."""

    def test_01_device_orchestrator_convergence_sentinel_importable(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE
        self.assertIsNotNone(DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE)

    def test_02_device_orchestrator_convergence_sentinel_mentions_spine(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE
        self.assertIn("CONVERGENCE", DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE)

    def test_03_device_orchestrator_convergence_sentinel_mentions_route_envelope(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE
        self.assertIn("route_envelope", DEVICE_ORCHESTRATOR_SPINE_CONVERGENCE)

    def test_04_scheduler_relay_mesh_convergence_sentinel_importable(self):
        from core.scheduler import SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE
        self.assertIsNotNone(SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE)

    def test_05_scheduler_relay_mesh_convergence_sentinel_mentions_spine(self):
        from core.scheduler import SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE
        self.assertIn("CONVERGENCE", SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE)

    def test_06_scheduler_relay_mesh_convergence_sentinel_mentions_route_envelope(self):
        from core.scheduler import SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE
        self.assertIn("route_envelope", SCHEDULER_RELAY_MESH_SPINE_CONVERGENCE)

    def test_07_device_orchestrator_facade_authority_still_present(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_FACADE_AUTHORITY
        self.assertIn("FACADE", DEVICE_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_08_scheduler_routes_command_router_still_present(self):
        from core.scheduler import SCHEDULER_ROUTES_COMMAND_ROUTER
        self.assertIn("COMMAND_ROUTER", SCHEDULER_ROUTES_COMMAND_ROUTER)


# ===========================================================================
# B. DeviceOrchestrator.send_command — spine routing path
# ===========================================================================

class TestDeviceOrchestratorSpineRouting(unittest.TestCase):
    """send_command calls CommandRouter.route_envelope when router available."""

    def _make_orchestrator(self):
        from core.device_orchestrator import DeviceOrchestrator
        orch = DeviceOrchestrator.__new__(DeviceOrchestrator)
        return orch

    def test_09_send_command_calls_route_envelope_when_router_available(self):
        """When CommandRouter is available, route_envelope is called."""
        orch = self._make_orchestrator()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(
            return_value={"success": True, "via": "route_envelope"}
        )

        with patch("core.command_router.get_command_router", return_value=mock_router):
            result_raw = _run(orch.send_command("dev_1", "tap", {"x": 100}))

        mock_router.route_envelope.assert_called_once()
        self.assertIn("command_id", result_raw)

    def test_10_send_command_returns_success_when_spine_succeeds(self):
        """route_envelope success → status 'success' in result dict."""
        orch = self._make_orchestrator()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(
            return_value={"success": True, "data": "ok"}
        )

        with patch("core.command_router.get_command_router", return_value=mock_router):
            result = _run(orch.send_command("dev_1", "screenshot", {}))

        self.assertEqual(result.get("status"), "success")
        self.assertEqual(result.get("device_id"), "dev_1")

    def test_11_send_command_falls_back_to_node_registry_when_spine_fails(self):
        """spine raises → NodeRegistry fallback is attempted."""
        orch = self._make_orchestrator()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(side_effect=RuntimeError("spine down"))

        mock_node_reg = MagicMock()
        mock_node_reg.call_node = AsyncMock(return_value={"success": True, "data": "fallback"})

        with patch("core.command_router.get_command_router", return_value=mock_router):
            with patch("core.device_orchestrator._get_node_registry", return_value=mock_node_reg):
                result = _run(orch.send_command("dev_1", "tap", {}))

        # NodeRegistry fallback should have been used
        mock_node_reg.call_node.assert_called_once()
        self.assertEqual(result.get("status"), "success")

    def test_12_send_command_uses_node_registry_when_router_unavailable(self):
        """When CommandRouter is unavailable, falls back directly to NodeRegistry."""
        orch = self._make_orchestrator()

        mock_node_reg = MagicMock()
        mock_node_reg.call_node = AsyncMock(return_value={"success": True, "data": "direct"})

        with patch("core.command_router.get_command_router", side_effect=ImportError("no router")):
            with patch("core.device_orchestrator._get_node_registry", return_value=mock_node_reg):
                result = _run(orch.send_command("dev_1", "shell", {"cmd": "ls"}))

        mock_node_reg.call_node.assert_called_once()
        self.assertEqual(result.get("status"), "success")

    def test_13_send_command_records_ingress_before_routing(self):
        """record_legacy_ingress is called regardless of spine availability."""
        from core.execution_spine import reset_ingress_log, get_ingress_log

        reset_ingress_log()
        orch = self._make_orchestrator()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(
            return_value={"success": True}
        )

        with patch("core.command_router.get_command_router", return_value=mock_router):
            _run(orch.send_command("dev_1", "tap", {"x": 10}))

        log = get_ingress_log()
        sources = [r.source.value if hasattr(r.source, "value") else str(r.source) for r in log]
        self.assertIn("device_orchestrator", sources)


# ===========================================================================
# C. Scheduler._exec_relay — spine routing path
# ===========================================================================

class TestSchedulerRelaySpineRouting(unittest.TestCase):
    """_exec_relay calls CommandRouter.route_envelope when router available."""

    def _make_scheduler(self):
        try:
            from core.scheduler import AutonomousScheduler
        except Exception:
            self.skipTest("AutonomousScheduler unavailable")
        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        return sched

    def test_14_exec_relay_calls_route_envelope_when_router_available(self):
        """When CommandRouter is available, route_envelope is called."""
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(
            return_value={"success": True, "via": "route_envelope"}
        )
        context = {"command_router": mock_router}

        result_raw = _run(sched._exec_relay(
            {"source_device": "src", "target_device": "tgt", "payload": {}},
            context,
        ))

        mock_router.route_envelope.assert_called_once()
        import json
        result = json.loads(result_raw)
        self.assertTrue(result.get("success"))

    def test_15_exec_relay_uses_context_router(self):
        """_exec_relay prefers the router from context over get_command_router."""
        sched = self._make_scheduler()

        ctx_router = MagicMock()
        ctx_router.route_envelope = AsyncMock(return_value={"success": True, "ctx": True})
        context = {"command_router": ctx_router}

        with patch("core.command_router.get_command_router") as mock_get:
            _run(sched._exec_relay({"target_device": "tgt"}, context))

        # get_command_router should NOT have been called when context provides router
        mock_get.assert_not_called()
        ctx_router.route_envelope.assert_called_once()

    def test_16_exec_relay_falls_back_to_proxy_relay_when_spine_fails(self):
        """When route_envelope raises, ProxyRelay fallback is attempted."""
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(side_effect=RuntimeError("spine down"))

        mock_relay_result = MagicMock()
        mock_relay_result.to_dict.return_value = {"relayed": True}

        mock_proxy_relay = MagicMock()
        mock_proxy_relay.relay = AsyncMock(return_value=mock_relay_result)

        context = {"command_router": mock_router}

        with patch("core.proxy_relay.get_proxy_relay", return_value=mock_proxy_relay):
            with patch("core.proxy_relay.RelayRequest", MagicMock()):
                result_raw = _run(sched._exec_relay(
                    {"source_device": "s", "target_device": "t", "payload": {}},
                    context,
                ))

        mock_proxy_relay.relay.assert_called_once()
        import json
        result = json.loads(result_raw)
        self.assertTrue(result.get("relayed"))

    def test_17_exec_relay_uses_get_command_router_when_no_context_router(self):
        """_exec_relay calls get_command_router() when context has no router."""
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"success": True})
        context = {}  # no command_router in context

        with patch("core.command_router.get_command_router", return_value=mock_router):
            _run(sched._exec_relay({"target_device": "tgt"}, context))

        mock_router.route_envelope.assert_called_once()

    def test_18_exec_relay_records_ingress(self):
        """record_legacy_ingress is called with SCHEDULER source."""
        from core.execution_spine import reset_ingress_log, get_ingress_log

        reset_ingress_log()
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"success": True})
        context = {"command_router": mock_router}

        _run(sched._exec_relay({"source_device": "s", "target_device": "t"}, context))

        log = get_ingress_log()
        sources = [r.source.value if hasattr(r.source, "value") else str(r.source) for r in log]
        self.assertIn("scheduler", sources)


# ===========================================================================
# D. Scheduler._exec_mesh_send — spine routing path
# ===========================================================================

class TestSchedulerMeshSendSpineRouting(unittest.TestCase):
    """_exec_mesh_send calls CommandRouter.route_envelope when router available."""

    def _make_scheduler(self):
        try:
            from core.scheduler import AutonomousScheduler
        except Exception:
            self.skipTest("AutonomousScheduler unavailable")
        sched = AutonomousScheduler.__new__(AutonomousScheduler)
        return sched

    def test_19_exec_mesh_send_calls_route_envelope_when_router_available(self):
        """When CommandRouter is available, route_envelope is called."""
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(
            return_value={"success": True, "via": "route_envelope"}
        )

        with patch("core.command_router.get_command_router", return_value=mock_router):
            result_raw = _run(sched._exec_mesh_send(
                {"target_device": "tgt", "payload": {"data": 1}}
            ))

        mock_router.route_envelope.assert_called_once()
        import json
        result = json.loads(result_raw)
        self.assertTrue(result.get("success"))

    def test_20_exec_mesh_send_falls_back_to_mesh_coordinator_when_spine_fails(self):
        """When route_envelope raises, MeshCoordinator fallback is attempted."""
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(side_effect=RuntimeError("spine down"))

        mock_mesh_result = MagicMock()
        mock_mesh_result.to_dict.return_value = {"mesh_sent": True}

        mock_mesh_coord = MagicMock()
        mock_mesh_coord.send = AsyncMock(return_value=mock_mesh_result)

        with patch("core.command_router.get_command_router", return_value=mock_router):
            with patch("core.mesh_coordinator.get_mesh_coordinator", return_value=mock_mesh_coord):
                result_raw = _run(sched._exec_mesh_send({"target_device": "tgt"}))

        mock_mesh_coord.send.assert_called_once()
        import json
        result = json.loads(result_raw)
        self.assertTrue(result.get("mesh_sent"))

    def test_21_exec_mesh_send_uses_node_registry_when_router_unavailable(self):
        """When CommandRouter is unavailable, falls back to MeshCoordinator."""
        sched = self._make_scheduler()

        mock_mesh_result = MagicMock()
        mock_mesh_result.to_dict.return_value = {"mesh_sent": True, "direct": True}

        mock_mesh_coord = MagicMock()
        mock_mesh_coord.send = AsyncMock(return_value=mock_mesh_result)

        with patch("core.command_router.get_command_router", side_effect=ImportError("no router")):
            with patch("core.mesh_coordinator.get_mesh_coordinator", return_value=mock_mesh_coord):
                result_raw = _run(sched._exec_mesh_send({"target_device": "tgt"}))

        mock_mesh_coord.send.assert_called_once()

    def test_22_exec_mesh_send_records_ingress(self):
        """record_legacy_ingress is called with SCHEDULER source."""
        from core.execution_spine import reset_ingress_log, get_ingress_log

        reset_ingress_log()
        sched = self._make_scheduler()

        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"success": True})

        with patch("core.command_router.get_command_router", return_value=mock_router):
            _run(sched._exec_mesh_send({"target_device": "tgt"}))

        log = get_ingress_log()
        sources = [r.source.value if hasattr(r.source, "value") else str(r.source) for r in log]
        self.assertIn("scheduler", sources)


# ===========================================================================
# E. LegacyDispatchRegistry — PR-B entries present
# ===========================================================================

class TestPRBLegacyDispatchRegistryEntries(unittest.TestCase):
    """PR-B entries are present in the LegacyDispatchRegistry."""

    def setUp(self):
        # Reset and re-bootstrap so PR-B entries are loaded.
        from core.legacy_dispatch_registry import reset_registry
        reset_registry()

    def test_23_device_orchestrator_send_command_registered(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        self.assertTrue(
            reg.is_registered("core.device_orchestrator.DeviceOrchestrator.send_command")
        )

    def test_24_scheduler_exec_relay_registered(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        self.assertTrue(reg.is_registered("core.scheduler.Scheduler._exec_relay"))

    def test_25_scheduler_exec_mesh_send_registered(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        self.assertTrue(reg.is_registered("core.scheduler.Scheduler._exec_mesh_send"))

    def test_26_device_orchestrator_pr_origin_is_prb(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        entry = reg.get("core.device_orchestrator.DeviceOrchestrator.send_command")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.pr_origin, "PR-B")

    def test_27_scheduler_relay_pr_origin_is_prb(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        entry = reg.get("core.scheduler.Scheduler._exec_relay")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.pr_origin, "PR-B")

    def test_28_scheduler_mesh_pr_origin_is_prb(self):
        from core.legacy_dispatch_registry import get_legacy_dispatch_registry
        reg = get_legacy_dispatch_registry()
        entry = reg.get("core.scheduler.Scheduler._exec_mesh_send")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.pr_origin, "PR-B")

    def test_29_all_prb_entries_are_compat_only(self):
        from core.legacy_dispatch_registry import (
            get_legacy_dispatch_registry,
            LegacyDispatchClassification,
        )
        reg = get_legacy_dispatch_registry()
        prb_modules = [
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            "core.scheduler.Scheduler._exec_relay",
            "core.scheduler.Scheduler._exec_mesh_send",
        ]
        for mod in prb_modules:
            with self.subTest(module=mod):
                entry = reg.get(mod)
                self.assertIsNotNone(entry, f"Missing entry for {mod}")
                self.assertEqual(
                    entry.classification,
                    LegacyDispatchClassification.COMPAT_ONLY,
                    f"Expected COMPAT_ONLY for {mod}, got {entry.classification}",
                )

    def test_30_snapshot_includes_prb_entries(self):
        from core.legacy_dispatch_registry import snapshot_registry
        snap = snapshot_registry()
        modules_in_snap = [e["module"] for e in snap.entries]
        self.assertIn(
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            modules_in_snap,
        )
        self.assertIn("core.scheduler.Scheduler._exec_relay", modules_in_snap)
        self.assertIn("core.scheduler.Scheduler._exec_mesh_send", modules_in_snap)


# ===========================================================================
# F. LEGACY_PATH_REGISTRY — PR-B entries present
# ===========================================================================

class TestPRBLegacyPathRegistryEntries(unittest.TestCase):
    """PR-B entries are present in the orchestration_authority LEGACY_PATH_REGISTRY."""

    def test_31_device_orchestrator_send_command_in_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn(
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            LEGACY_PATH_REGISTRY,
        )

    def test_32_scheduler_exec_relay_in_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn("core.scheduler.Scheduler._exec_relay", LEGACY_PATH_REGISTRY)

    def test_33_scheduler_exec_mesh_send_in_registry(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        self.assertIn("core.scheduler.Scheduler._exec_mesh_send", LEGACY_PATH_REGISTRY)

    def test_34_device_orchestrator_guardrail_is_prb(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY[
            "core.device_orchestrator.DeviceOrchestrator.send_command"
        ]
        self.assertEqual(entry.pr_guardrail_added, "PR-B")

    def test_35_scheduler_relay_guardrail_is_prb(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["core.scheduler.Scheduler._exec_relay"]
        self.assertEqual(entry.pr_guardrail_added, "PR-B")

    def test_36_scheduler_mesh_guardrail_is_prb(self):
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        entry = LEGACY_PATH_REGISTRY["core.scheduler.Scheduler._exec_mesh_send"]
        self.assertEqual(entry.pr_guardrail_added, "PR-B")

    def test_37_all_prb_paths_are_legacy_compatibility(self):
        from core.orchestration_authority.legacy_paths import (
            LEGACY_PATH_REGISTRY,
            LegacyPathStatus,
        )
        prb_paths = [
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            "core.scheduler.Scheduler._exec_relay",
            "core.scheduler.Scheduler._exec_mesh_send",
        ]
        for path in prb_paths:
            with self.subTest(path=path):
                entry = LEGACY_PATH_REGISTRY[path]
                self.assertIs(
                    entry.status,
                    LegacyPathStatus.LEGACY_COMPATIBILITY,
                    f"Expected LEGACY_COMPATIBILITY for {path}",
                )

    def test_38_prb_paths_in_legacy_orchestrator_paths_shim(self):
        """PR-B paths appear in the LEGACY_ORCHESTRATOR_PATHS compatibility shim."""
        from core.orchestration_authority.legacy_paths import LEGACY_ORCHESTRATOR_PATHS
        self.assertIn(
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            LEGACY_ORCHESTRATOR_PATHS,
        )
        self.assertIn("core.scheduler.Scheduler._exec_relay", LEGACY_ORCHESTRATOR_PATHS)
        self.assertIn("core.scheduler.Scheduler._exec_mesh_send", LEGACY_ORCHESTRATOR_PATHS)

    def test_39_prb_recommendation_mentions_route_envelope(self):
        """Each PR-B entry's recommendation references CommandRouter.route_envelope()."""
        from core.orchestration_authority.legacy_paths import LEGACY_PATH_REGISTRY
        prb_paths = [
            "core.device_orchestrator.DeviceOrchestrator.send_command",
            "core.scheduler.Scheduler._exec_relay",
            "core.scheduler.Scheduler._exec_mesh_send",
        ]
        for path in prb_paths:
            with self.subTest(path=path):
                entry = LEGACY_PATH_REGISTRY[path]
                self.assertIn(
                    "route_envelope",
                    entry.recommendation,
                    f"Recommendation for {path} should mention route_envelope()",
                )


# ===========================================================================
# G. Regression — existing spine functionality unbroken
# ===========================================================================

class TestExistingSpineFunctionalityUnbroken(unittest.TestCase):
    """Regression: PR-3 spine authority and ingress source enumeration still intact."""

    def test_40_execution_spine_authority_still_importable(self):
        from core.execution_spine import EXECUTION_SPINE_AUTHORITY
        self.assertIn("EXECUTION_SPINE", EXECUTION_SPINE_AUTHORITY)

    def test_41_device_orchestrator_source_is_device_orchestrator(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.DEVICE_ORCHESTRATOR.value, "device_orchestrator")

    def test_42_scheduler_source_is_scheduler(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.SCHEDULER.value, "scheduler")

    def test_43_record_legacy_ingress_still_works(self):
        from core.execution_spine import (
            reset_ingress_log,
            record_legacy_ingress,
            get_ingress_log,
            ExecutionIngressSource,
        )
        reset_ingress_log()
        record_legacy_ingress(
            ExecutionIngressSource.DEVICE_ORCHESTRATOR,
            {"device_id": "x", "command": "tap"},
            reason="regression test",
        )
        log = get_ingress_log()
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0].source, ExecutionIngressSource.DEVICE_ORCHESTRATOR)
        self.assertTrue(log[0].was_normalized)

    def test_44_command_router_dispatch_spine_authority_unchanged(self):
        try:
            from core.command_router import COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY
        except ImportError as e:
            self.skipTest(f"command_router unavailable: {e}")
        self.assertIn("DISPATCH_SPINE", COMMAND_ROUTER_DISPATCH_SPINE_AUTHORITY)

    def test_45_legacy_dispatch_registry_pre_existing_entries_unchanged(self):
        """Pre-existing PR-3 entries are still present after PR-B additions."""
        from core.legacy_dispatch_registry import reset_registry, get_legacy_dispatch_registry
        reset_registry()
        reg = get_legacy_dispatch_registry()
        # PR-3 entries
        self.assertTrue(reg.is_registered("core.device_orchestrator"))
        self.assertTrue(reg.is_registered("galaxy_gateway.orchestrator.galaxy_orchestrator"))
        self.assertTrue(reg.is_registered("fusion.unified_orchestrator"))


if __name__ == "__main__":
    unittest.main()
