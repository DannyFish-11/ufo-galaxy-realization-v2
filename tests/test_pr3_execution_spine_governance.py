#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_execution_spine_governance.py
=============================================
PR-3 — Execution Spine Integration: Governance Tests.

Validates:
 1.  EXECUTION_SPINE_AUTHORITY importable from core.execution_spine.
 2.  EXECUTION_SPINE_AUTHORITY contains 'EXECUTION_SPINE'.
 3.  EXECUTION_SPINE_INGRESS_POLICY is a non-empty string.
 4.  EXECUTION_SPINE_INGRESS_POLICY mentions CommandRouter.
 5.  ExecutionIngressSource importable from core.execution_spine.
 6.  ExecutionIngressSource.SCHEDULER value is 'scheduler'.
 7.  ExecutionIngressSource.BRIDGE value is 'bridge'.
 8.  ExecutionIngressSource.GALAXY_ORCHESTRATOR value is 'galaxy_orchestrator'.
 9.  ExecutionIngressSource.DEVICE_ORCHESTRATOR value is 'device_orchestrator'.
10.  ExecutionIngressSource.UNIFIED_ORCHESTRATOR value is 'unified_orchestrator'.
11.  ExecutionIngressSource.CANONICAL value is 'canonical'.
12.  IngressRecord importable from core.execution_spine.
13.  IngressRecord.to_dict() returns a dict with expected keys.
14.  normalize_ingress_to_envelope importable from core.execution_spine.
15.  route_via_spine importable from core.execution_spine.
16.  record_legacy_ingress importable from core.execution_spine.
17.  get_ingress_log importable from core.execution_spine.
18.  reset_ingress_log importable from core.execution_spine.
19.  record_legacy_ingress appends to ingress log.
20.  reset_ingress_log clears the ingress log.
21.  get_ingress_log returns a list.
22.  IngressRecord.source defaults to ExecutionIngressSource.UNKNOWN.
23.  IngressRecord.was_normalized defaults to False.
24.  record_legacy_ingress returns an IngressRecord.
25.  record_legacy_ingress sets was_normalized=True.
26.  record_legacy_ingress preserves legacy_reason.
27.  normalize_ingress_to_envelope with dict uses message_interop or fallback.
28.  normalize_ingress_to_envelope with TaskEnvelope uses fast path.
29.  normalize_ingress_to_envelope produces object with task_id attribute.
30.  normalize_ingress_to_envelope produces object with trace_id attribute.
31.  COMMAND_ROUTER_LEGACY_INGRESS_POLICY importable from core.command_router.
32.  COMMAND_ROUTER_LEGACY_INGRESS_POLICY mentions normalize.
33.  CommandRouter has normalize_legacy_ingress method.
34.  CommandRouter.normalize_legacy_ingress returns an object (not raises).
35.  DEVICE_ORCHESTRATOR_FACADE_AUTHORITY importable from core.device_orchestrator.
36.  DEVICE_ORCHESTRATOR_FACADE_AUTHORITY contains 'FACADE'.
37.  GALAXY_ORCHESTRATOR_FACADE_AUTHORITY importable from galaxy_gateway.orchestrator.galaxy_orchestrator.
38.  GALAXY_ORCHESTRATOR_FACADE_AUTHORITY contains 'FACADE'.
39.  UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY importable from fusion.unified_orchestrator (with warning).
40.  UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY contains 'FACADE'.
"""

from __future__ import annotations

import sys
import os
import unittest
import warnings
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestExecutionSpineAuthority(unittest.TestCase):
    """Tests 1–4: Authority sentinels and policy constants."""

    def test_01_authority_importable(self):
        from core.execution_spine import EXECUTION_SPINE_AUTHORITY
        self.assertIsNotNone(EXECUTION_SPINE_AUTHORITY)

    def test_02_authority_contains_execution_spine(self):
        from core.execution_spine import EXECUTION_SPINE_AUTHORITY
        self.assertIn("EXECUTION_SPINE", EXECUTION_SPINE_AUTHORITY)

    def test_03_ingress_policy_non_empty(self):
        from core.execution_spine import EXECUTION_SPINE_INGRESS_POLICY
        self.assertIsInstance(EXECUTION_SPINE_INGRESS_POLICY, str)
        self.assertTrue(len(EXECUTION_SPINE_INGRESS_POLICY) > 0)

    def test_04_ingress_policy_mentions_command_router(self):
        from core.execution_spine import EXECUTION_SPINE_INGRESS_POLICY
        self.assertIn("CommandRouter", EXECUTION_SPINE_INGRESS_POLICY)


class TestExecutionIngressSource(unittest.TestCase):
    """Tests 5–11: ExecutionIngressSource enum values."""

    def test_05_source_importable(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertIsNotNone(ExecutionIngressSource)

    def test_06_scheduler_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.SCHEDULER.value, "scheduler")

    def test_07_bridge_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.BRIDGE.value, "bridge")

    def test_08_galaxy_orchestrator_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.GALAXY_ORCHESTRATOR.value, "galaxy_orchestrator")

    def test_09_device_orchestrator_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.DEVICE_ORCHESTRATOR.value, "device_orchestrator")

    def test_10_unified_orchestrator_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.UNIFIED_ORCHESTRATOR.value, "unified_orchestrator")

    def test_11_canonical_value(self):
        from core.execution_spine import ExecutionIngressSource
        self.assertEqual(ExecutionIngressSource.CANONICAL.value, "canonical")


class TestIngressRecord(unittest.TestCase):
    """Tests 12–13: IngressRecord dataclass."""

    def test_12_ingress_record_importable(self):
        from core.execution_spine import IngressRecord
        self.assertIsNotNone(IngressRecord)

    def test_13_to_dict_has_expected_keys(self):
        from core.execution_spine import IngressRecord
        rec = IngressRecord()
        d = rec.to_dict()
        self.assertIn("record_id", d)
        self.assertIn("source", d)
        self.assertIn("task_id", d)
        self.assertIn("trace_id", d)
        self.assertIn("tool_name", d)
        self.assertIn("targets", d)
        self.assertIn("was_normalized", d)
        self.assertIn("legacy_reason", d)


class TestExecutionSpineImports(unittest.TestCase):
    """Tests 14–18: Public API imports."""

    def test_14_normalize_ingress_importable(self):
        from core.execution_spine import normalize_ingress_to_envelope
        self.assertTrue(callable(normalize_ingress_to_envelope))

    def test_15_route_via_spine_importable(self):
        from core.execution_spine import route_via_spine
        self.assertTrue(callable(route_via_spine))

    def test_16_record_legacy_ingress_importable(self):
        from core.execution_spine import record_legacy_ingress
        self.assertTrue(callable(record_legacy_ingress))

    def test_17_get_ingress_log_importable(self):
        from core.execution_spine import get_ingress_log
        self.assertTrue(callable(get_ingress_log))

    def test_18_reset_ingress_log_importable(self):
        from core.execution_spine import reset_ingress_log
        self.assertTrue(callable(reset_ingress_log))


class TestIngressLog(unittest.TestCase):
    """Tests 19–26: Ingress log operations."""

    def setUp(self):
        from core.execution_spine import reset_ingress_log
        reset_ingress_log()

    def test_19_record_legacy_ingress_appends(self):
        from core.execution_spine import (
            ExecutionIngressSource,
            record_legacy_ingress,
            get_ingress_log,
        )
        record_legacy_ingress(ExecutionIngressSource.SCHEDULER, {}, reason="test")
        log = get_ingress_log()
        self.assertEqual(len(log), 1)

    def test_20_reset_clears_log(self):
        from core.execution_spine import (
            ExecutionIngressSource,
            record_legacy_ingress,
            get_ingress_log,
            reset_ingress_log,
        )
        record_legacy_ingress(ExecutionIngressSource.SCHEDULER, {}, reason="test")
        reset_ingress_log()
        self.assertEqual(len(get_ingress_log()), 0)

    def test_21_get_ingress_log_returns_list(self):
        from core.execution_spine import get_ingress_log
        log = get_ingress_log()
        self.assertIsInstance(log, list)

    def test_22_ingress_record_default_source_unknown(self):
        from core.execution_spine import IngressRecord, ExecutionIngressSource
        rec = IngressRecord()
        self.assertEqual(rec.source, ExecutionIngressSource.UNKNOWN)

    def test_23_ingress_record_default_was_normalized_false(self):
        from core.execution_spine import IngressRecord
        rec = IngressRecord()
        self.assertFalse(rec.was_normalized)

    def test_24_record_legacy_ingress_returns_record(self):
        from core.execution_spine import ExecutionIngressSource, record_legacy_ingress, IngressRecord
        rec = record_legacy_ingress(ExecutionIngressSource.BRIDGE, {}, reason="test-reason")
        self.assertIsInstance(rec, IngressRecord)

    def test_25_record_legacy_ingress_was_normalized_true(self):
        from core.execution_spine import ExecutionIngressSource, record_legacy_ingress
        rec = record_legacy_ingress(ExecutionIngressSource.SCHEDULER, {}, reason="r")
        self.assertTrue(rec.was_normalized)

    def test_26_record_legacy_ingress_preserves_reason(self):
        from core.execution_spine import ExecutionIngressSource, record_legacy_ingress
        rec = record_legacy_ingress(ExecutionIngressSource.DEVICE_ORCHESTRATOR, {}, reason="custom-reason")
        self.assertIn("custom-reason", rec.legacy_reason)


class TestNormalizeIngressToEnvelope(unittest.TestCase):
    """Tests 27–30: normalize_ingress_to_envelope behavior."""

    def setUp(self):
        from core.execution_spine import reset_ingress_log
        reset_ingress_log()

    def test_27_normalize_dict_produces_result(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"task_type": "screenshot", "device_id": "dev_001"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.SCHEDULER)
        self.assertIsNotNone(result)

    def test_28_normalize_task_envelope_fast_path(self):
        try:
            from core.schemas.task_envelope import TaskEnvelope
            from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
            env = TaskEnvelope(task_id="t1", trace_id="tr1", source="test", tool_name="foo")
            result = normalize_ingress_to_envelope(env, source=ExecutionIngressSource.CANONICAL)
            self.assertIs(result, env)
        except ImportError:
            self.skipTest("TaskEnvelope not available")

    def test_29_normalize_produces_task_id(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"task_type": "screenshot", "device_id": "dev_001"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.SCHEDULER)
        self.assertTrue(hasattr(result, "task_id"))
        self.assertTrue(len(str(result.task_id)) > 0)

    def test_30_normalize_produces_trace_id(self):
        from core.execution_spine import ExecutionIngressSource, normalize_ingress_to_envelope
        payload = {"task_type": "screenshot", "device_id": "dev_001"}
        result = normalize_ingress_to_envelope(payload, source=ExecutionIngressSource.SCHEDULER)
        self.assertTrue(hasattr(result, "trace_id"))
        self.assertTrue(len(str(result.trace_id)) > 0)


class TestCommandRouterLegacyIngressPolicy(unittest.TestCase):
    """Tests 31–34: CommandRouter legacy ingress governance."""

    def test_31_policy_importable(self):
        from core.command_router import COMMAND_ROUTER_LEGACY_INGRESS_POLICY
        self.assertIsNotNone(COMMAND_ROUTER_LEGACY_INGRESS_POLICY)

    def test_32_policy_mentions_normalize(self):
        from core.command_router import COMMAND_ROUTER_LEGACY_INGRESS_POLICY
        self.assertIn("normalize", COMMAND_ROUTER_LEGACY_INGRESS_POLICY.lower())

    def test_33_command_router_has_normalize_legacy_ingress(self):
        from core.command_router import CommandRouter
        self.assertTrue(hasattr(CommandRouter, "normalize_legacy_ingress"))
        self.assertTrue(callable(CommandRouter.normalize_legacy_ingress))

    def test_34_normalize_legacy_ingress_does_not_raise(self):
        from core.command_router import CommandRouter
        router = CommandRouter.__new__(CommandRouter)
        # Minimal stub — bypass __init__
        result = router.normalize_legacy_ingress(
            {"task_type": "screenshot", "device_id": "dev_001"},
            source="scheduler",
        )
        # Should return something (envelope or unchanged payload) without raising
        self.assertIsNotNone(result)


class TestOrchestratorFacadeAuthority(unittest.TestCase):
    """Tests 35–40: Facade authority sentinels on legacy orchestrators."""

    def test_35_device_orchestrator_facade_importable(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_FACADE_AUTHORITY
        self.assertIsNotNone(DEVICE_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_36_device_orchestrator_facade_contains_facade(self):
        from core.device_orchestrator import DEVICE_ORCHESTRATOR_FACADE_AUTHORITY
        self.assertIn("FACADE", DEVICE_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_37_galaxy_orchestrator_facade_importable(self):
        try:
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_FACADE_AUTHORITY
        except ImportError as e:
            self.skipTest(f"galaxy_orchestrator import unavailable (missing dependency): {e}")
        self.assertIsNotNone(GALAXY_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_38_galaxy_orchestrator_facade_contains_facade(self):
        try:
            from galaxy_gateway.orchestrator.galaxy_orchestrator import GALAXY_ORCHESTRATOR_FACADE_AUTHORITY
        except ImportError as e:
            self.skipTest(f"galaxy_orchestrator import unavailable (missing dependency): {e}")
        self.assertIn("FACADE", GALAXY_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_39_unified_orchestrator_facade_importable(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY
        except (ImportError, AttributeError) as e:
            self.skipTest(f"unified_orchestrator import unavailable (missing dependency): {e}")
        self.assertIsNotNone(UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY)

    def test_40_unified_orchestrator_facade_contains_facade(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                from fusion.unified_orchestrator import UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY
        except (ImportError, AttributeError) as e:
            self.skipTest(f"unified_orchestrator import unavailable (missing dependency): {e}")
        self.assertIn("FACADE", UNIFIED_ORCHESTRATOR_FACADE_AUTHORITY)


if __name__ == "__main__":
    unittest.main()
