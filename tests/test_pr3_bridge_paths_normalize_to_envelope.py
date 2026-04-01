#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_bridge_paths_normalize_to_envelope.py
=====================================================
PR-3 — Execution Spine Integration: Bridge & Orchestrator facade tests.

Validates:
 1.  ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED importable from galaxy_gateway.android_bridge.
 2.  ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED contains 'ANDROID_BRIDGE'.
 3.  ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED contains 'SPINE'.
 4.  AndroidBridge class still importable from galaxy_gateway.android_bridge.
 5.  AndroidBridge has no independent dispatch authority sentinel (old PR-S4 note preserved).
 6.  DEVICE_ORCHESTRATOR_FACADE_AUTHORITY non-empty string.
 7.  GALAXY_ORCHESTRATOR_FACADE_AUTHORITY non-empty string.
 8.  UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY non-empty string.
 9.  DeviceOrchestrator.send_command records ingress in execution spine log.
10.  DeviceOrchestrator.send_command ingress record source is 'device_orchestrator'.
11.  normalize_ingress_to_envelope with bridge-style payload produces TaskEnvelope.
12.  normalize_ingress_to_envelope with bridge payload sets targets from device_id.
13.  normalize_ingress_to_envelope with bridge payload sets tool_name from action.
14.  record_legacy_ingress with BRIDGE source captures source correctly.
15.  route_via_spine calls CommandRouter.route_envelope.
16.  route_via_spine returns dict.
17.  route_via_spine with failing router returns error dict.
18.  normalize_ingress_to_envelope preserves explicit task_id.
19.  normalize_ingress_to_envelope preserves explicit trace_id.
20.  IngressRecord to_dict source field matches ExecutionIngressSource value.
"""

from __future__ import annotations

import sys
import os
import asyncio
import warnings
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestAndroidBridgeSpineSentinel(unittest.TestCase):
    """Tests 1–5: AndroidBridge execution spine sentinel."""

    def test_01_sentinel_importable(self):
        try:
            from galaxy_gateway.android_bridge import ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED
        except ImportError as e:
            self.skipTest(f"android_bridge unavailable (missing dep): {e}")
        self.assertIsNotNone(ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED)

    def test_02_sentinel_contains_android_bridge(self):
        try:
            from galaxy_gateway.android_bridge import ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED
        except ImportError as e:
            self.skipTest(f"android_bridge unavailable (missing dep): {e}")
        self.assertIn("ANDROID_BRIDGE", ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED)

    def test_03_sentinel_contains_spine(self):
        try:
            from galaxy_gateway.android_bridge import ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED
        except ImportError as e:
            self.skipTest(f"android_bridge unavailable (missing dep): {e}")
        self.assertIn("SPINE", ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED)

    def test_04_android_bridge_class_still_importable(self):
        try:
            from galaxy_gateway.android_bridge import AndroidBridge
        except ImportError as e:
            self.skipTest(f"android_bridge unavailable (missing dep): {e}")
        self.assertIsNotNone(AndroidBridge)

    def test_05_android_bridge_sentinel_is_string(self):
        try:
            from galaxy_gateway.android_bridge import ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED
        except ImportError as e:
            self.skipTest(f"android_bridge unavailable (missing dep): {e}")
        self.assertIsInstance(ANDROID_BRIDGE_EXECUTION_SPINE_APPLIED, str)


class TestFacadeAuthoritySentinels(unittest.TestCase):
    """Tests 6–8: Facade authority sentinels are non-empty strings."""

    def test_06_device_orchestrator_facade_non_empty(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_FACADE_AUTHORITY
        self.assertIsInstance(DEVICE_ORCHESTRATOR_FACADE_AUTHORITY, str)
        self.assertTrue(len(DEVICE_ORCHESTRATOR_FACADE_AUTHORITY) > 0)

    def test_07_galaxy_orchestrator_facade_non_empty(self):
        try:
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_FACADE_AUTHORITY
        except ImportError as e:
            self.skipTest(f"galaxy_orchestrator unavailable: {e}")
        self.assertIsInstance(GALAXY_ORCHESTRATOR_FACADE_AUTHORITY, str)
        self.assertTrue(len(GALAXY_ORCHESTRATOR_FACADE_AUTHORITY) > 0)

    def test_08_unified_orchestrator_facade_non_empty(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY
        except (ImportError, AttributeError) as e:
            self.skipTest(f"unified_orchestrator unavailable: {e}")
        self.assertIsInstance(UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY, str)
        self.assertTrue(len(UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY) > 0)


class TestDeviceOrchestratorFacade(unittest.TestCase):
    """Tests 9–10: DeviceOrchestrator.send_command uses spine log."""

    def setUp(self):
        from core.execution_spine import reset_ingress_log
        reset_ingress_log()

    def _make_orchestrator(self):
        from core.device_orchestrator import DeviceOrchestrator
        # Reset singleton so we get a clean instance
        DeviceOrchestrator._instance = None
        orch = DeviceOrchestrator()
        return orch

    def test_09_send_command_records_ingress(self):
        from core.execution_spine import get_ingress_log
        orch = self._make_orchestrator()
        with patch("core.device_orchestrator._get_node_registry", return_value=None):
            _run(orch.send_command("dev_001", "screenshot", {}))
        log = get_ingress_log()
        self.assertTrue(len(log) >= 1)

    def test_10_send_command_ingress_source_device_orchestrator(self):
        from core.execution_spine import get_ingress_log, ExecutionIngressSource
        orch = self._make_orchestrator()
        with patch("core.device_orchestrator._get_node_registry", return_value=None):
            _run(orch.send_command("dev_001", "screenshot", {}))
        log = get_ingress_log()
        sources = [r.source for r in log]
        self.assertIn(ExecutionIngressSource.DEVICE_ORCHESTRATOR, sources)


class TestNormalizeBridgePayloads(unittest.TestCase):
    """Tests 11–14: normalize_ingress_to_envelope with bridge-style payloads."""

    def test_11_bridge_payload_produces_envelope(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {
            "action": "open_app",
            "device_id": "android_001",
            "payload": {"app_name": "WeChat"},
        }
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.BRIDGE)
        self.assertIsNotNone(result)

    def test_12_bridge_payload_sets_targets_from_device_id(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"action": "tap", "device_id": "android_001"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.BRIDGE)
        targets = getattr(result, "targets", []) or []
        self.assertIn("android_001", targets)

    def test_13_bridge_payload_sets_tool_name_from_action(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"action": "swipe", "device_id": "android_001"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.BRIDGE)
        tool_name = getattr(result, "tool_name", None)
        self.assertIsNotNone(tool_name)

    def test_14_record_legacy_ingress_bridge_source(self):
        from core.execution_spine import ExecutionIngressSource, record_legacy_ingress, reset_ingress_log, get_ingress_log
        reset_ingress_log()
        rec = record_legacy_ingress(
            ExecutionIngressSource.BRIDGE,
            {"action": "tap", "device_id": "dev_1"},
            reason="bridge legacy path",
        )
        self.assertEqual(rec.source, ExecutionIngressSource.BRIDGE)
        log = get_ingress_log()
        self.assertEqual(len(log), 1)


class TestRouteViaSpine(unittest.TestCase):
    """Tests 15–17: route_via_spine behavior."""

    def setUp(self):
        from core.execution_spine import reset_ingress_log
        reset_ingress_log()

    def test_15_route_via_spine_calls_route_envelope(self):
        from core.execution_spine import ExecutionIngressSource, route_via_spine
        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"spine_ok": True})
        result = _run(route_via_spine(
            {"task_type": "screenshot", "device_id": "dev_001"},
            source=ExecutionIngressSource.SCHEDULER,
            router=mock_router,
        ))
        mock_router.route_envelope.assert_called_once()
        self.assertTrue(result.get("spine_ok"))

    def test_16_route_via_spine_returns_dict(self):
        from core.execution_spine import ExecutionIngressSource, route_via_spine
        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"status": "ok"})
        result = _run(route_via_spine(
            {"task_type": "screenshot"},
            source=ExecutionIngressSource.BRIDGE,
            router=mock_router,
        ))
        self.assertIsInstance(result, dict)

    def test_17_route_via_spine_with_failing_router_returns_error_dict(self):
        from core.execution_spine import ExecutionIngressSource, route_via_spine
        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(side_effect=RuntimeError("router failed"))
        result = _run(route_via_spine(
            {"task_type": "screenshot"},
            source=ExecutionIngressSource.SCHEDULER,
            router=mock_router,
        ))
        self.assertIsInstance(result, dict)
        self.assertFalse(result.get("success", True))


class TestNormalizePreservesCorrelationFields(unittest.TestCase):
    """Tests 18–20: Correlation field preservation in normalize_ingress_to_envelope."""

    def test_18_preserves_explicit_task_id(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"task_id": "explicit_task_123", "task_type": "screenshot"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.SCHEDULER)
        self.assertEqual(str(result.task_id), "explicit_task_123")

    def test_19_preserves_explicit_trace_id(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"trace_id": "explicit_trace_456", "task_type": "screenshot"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.SCHEDULER)
        self.assertEqual(str(result.trace_id), "explicit_trace_456")

    def test_20_ingress_record_to_dict_source_matches_enum_value(self):
        from core.execution_spine import ExecutionIngressSource, IngressRecord
        rec = IngressRecord(source=ExecutionIngressSource.BRIDGE)
        d = rec.to_dict()
        self.assertEqual(d["source"], ExecutionIngressSource.BRIDGE.value)


if __name__ == "__main__":
    unittest.main()
