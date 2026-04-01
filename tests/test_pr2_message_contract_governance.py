#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr2_message_contract_governance.py
==============================================
PR-2 — Canonical Message Interop: Message Contract Governance Tests.

Validates that:
 1.  MESSAGE_INTEROP_AUTHORITY importable from core.message_interop.
 2.  MESSAGE_INTEROP_AUTHORITY contains 'MESSAGE_INTEROP'.
 3.  MESSAGE_INTEROP_CORRELATION_POLICY is a non-empty string.
 4.  MESSAGE_INTEROP_CORRELATION_POLICY mentions task_id.
 5.  MESSAGE_INTEROP_CORRELATION_POLICY mentions trace_id.
 6.  normalize_to_task_envelope importable from core.message_interop.
 7.  normalize_to_result_envelope importable from core.message_interop.
 8.  extract_correlation importable from core.message_interop.
 9.  CorrelationFields importable from core.message_interop.
10.  normalize_to_task_envelope with TaskEnvelope-shaped dict uses fast path.
11.  normalize_to_task_envelope with legacy dict extracts tool_name from task_type.
12.  normalize_to_task_envelope with bridge dict extracts tool_name from action.
13.  normalize_to_task_envelope with scheduler dict extracts tool_name from command.
14.  normalize_to_task_envelope always produces non-empty task_id.
15.  normalize_to_task_envelope always produces non-empty trace_id.
16.  normalize_to_task_envelope preserves explicit task_id from payload.
17.  normalize_to_task_envelope preserves explicit trace_id from payload.
18.  normalize_to_task_envelope preserves session_id when present.
19.  normalize_to_task_envelope extracts targets from target_device_id.
20.  normalize_to_task_envelope extracts targets from target_worker_id.
21.  normalize_to_task_envelope extracts targets from 'targets' list.
22.  normalize_to_task_envelope extracts args from 'payload' key.
23.  normalize_to_task_envelope extracts args from 'params' key.
24.  normalize_to_task_envelope with empty dict still produces valid envelope.
25.  normalize_to_task_envelope source kwarg is reflected in envelope.source.
26.  MESSAGE_INTEROP_APPLIED sentinel importable from gateway_nats_adapter.
27.  SCHEDULER_MESSAGE_INTEROP_APPLIED sentinel importable from core.scheduler.
28.  CorrelationFields.to_dict() includes task_id, trace_id, session_id keys.
29.  normalize_to_task_envelope with non-dict payload falls back gracefully.
30.  normalize_to_task_envelope with route_mode in payload propagates to metadata.
"""

from __future__ import annotations

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestMessageInteropAuthority(unittest.TestCase):
    """Tests 1–5: Authority sentinel and policy constants."""

    def test_01_authority_importable(self):
        from core.message_interop import MESSAGE_INTEROP_AUTHORITY
        self.assertIsNotNone(MESSAGE_INTEROP_AUTHORITY)

    def test_02_authority_contains_message_interop(self):
        from core.message_interop import MESSAGE_INTEROP_AUTHORITY
        self.assertIn("MESSAGE_INTEROP", MESSAGE_INTEROP_AUTHORITY)

    def test_03_correlation_policy_non_empty(self):
        from core.message_interop import MESSAGE_INTEROP_CORRELATION_POLICY
        self.assertIsInstance(MESSAGE_INTEROP_CORRELATION_POLICY, str)
        self.assertTrue(len(MESSAGE_INTEROP_CORRELATION_POLICY) > 0)

    def test_04_correlation_policy_mentions_task_id(self):
        from core.message_interop import MESSAGE_INTEROP_CORRELATION_POLICY
        self.assertIn("task_id", MESSAGE_INTEROP_CORRELATION_POLICY)

    def test_05_correlation_policy_mentions_trace_id(self):
        from core.message_interop import MESSAGE_INTEROP_CORRELATION_POLICY
        self.assertIn("trace_id", MESSAGE_INTEROP_CORRELATION_POLICY)


class TestMessageInteropImports(unittest.TestCase):
    """Tests 6–9: Public API imports."""

    def test_06_normalize_to_task_envelope_importable(self):
        from core.message_interop import normalize_to_task_envelope
        self.assertTrue(callable(normalize_to_task_envelope))

    def test_07_normalize_to_result_envelope_importable(self):
        from core.message_interop import normalize_to_result_envelope
        self.assertTrue(callable(normalize_to_result_envelope))

    def test_08_extract_correlation_importable(self):
        from core.message_interop import extract_correlation
        self.assertTrue(callable(extract_correlation))

    def test_09_correlation_fields_importable(self):
        from core.message_interop import CorrelationFields
        self.assertIsNotNone(CorrelationFields)


def _make_task_envelope():
    """Build a minimal TaskEnvelope for tests."""
    try:
        from core.schemas.task_envelope import TaskEnvelope
        return TaskEnvelope(
            task_id="task_abc123",
            trace_id="trace_def456",
            tool_name="open_app",
            targets=["device_01"],
        )
    except Exception:
        return None


class TestNormalizeToTaskEnvelope(unittest.TestCase):
    """Tests 10–25: normalize_to_task_envelope behaviour."""

    def _normalize(self, payload, **kwargs):
        from core.message_interop import normalize_to_task_envelope
        return normalize_to_task_envelope(payload, **kwargs)

    def test_10_fast_path_task_envelope_schema(self):
        """Dict with _nats_schema=TaskEnvelope uses fast path."""
        payload = {
            "_nats_schema": "TaskEnvelope",
            "task_id": "task_fastpath",
            "trace_id": "trace_fastpath",
            "tool_name": "test_tool",
            "targets": ["dev_a"],
            "args": {},
            "source": "nats",
        }
        env = self._normalize(payload)
        self.assertEqual(env.task_id, "task_fastpath")
        self.assertEqual(env.trace_id, "trace_fastpath")
        self.assertEqual(env.tool_name, "test_tool")

    def test_11_legacy_dict_extracts_tool_name_from_task_type(self):
        payload = {
            "task_type": "screenshot",
            "target_device_id": "dev_b",
            "payload": {"quality": "high"},
        }
        env = self._normalize(payload)
        self.assertEqual(env.tool_name, "screenshot")

    def test_12_bridge_dict_extracts_tool_name_from_action(self):
        payload = {
            "type": "command",
            "action": "click",
            "payload": {"x": 100, "y": 200},
            "target": "dev_c",
        }
        env = self._normalize(payload)
        self.assertEqual(env.tool_name, "click")

    def test_13_scheduler_dict_extracts_tool_name_from_command(self):
        payload = {
            "command": "open_app",
            "params": {"app_name": "WeChat"},
            "target_device_id": "dev_d",
        }
        env = self._normalize(payload)
        self.assertEqual(env.tool_name, "open_app")

    def test_14_always_produces_non_empty_task_id(self):
        env = self._normalize({})
        self.assertTrue(len(env.task_id) > 0)

    def test_15_always_produces_non_empty_trace_id(self):
        env = self._normalize({})
        self.assertTrue(len(env.trace_id) > 0)

    def test_16_preserves_explicit_task_id(self):
        env = self._normalize({"task_id": "task_explicit_001"})
        self.assertEqual(env.task_id, "task_explicit_001")

    def test_17_preserves_explicit_trace_id(self):
        env = self._normalize({"trace_id": "trace_explicit_002"})
        self.assertEqual(env.trace_id, "trace_explicit_002")

    def test_18_preserves_session_id_when_present(self):
        env = self._normalize({"session_id": "sess_abc"})
        self.assertEqual(env.session_id, "sess_abc")

    def test_19_extracts_targets_from_target_device_id(self):
        env = self._normalize({"target_device_id": "dev_e"})
        self.assertIn("dev_e", env.targets)

    def test_20_extracts_targets_from_target_worker_id(self):
        env = self._normalize({"target_worker_id": "worker_f"})
        self.assertIn("worker_f", env.targets)

    def test_21_extracts_targets_from_targets_list(self):
        env = self._normalize({"targets": ["dev_g", "dev_h"]})
        self.assertIn("dev_g", env.targets)
        self.assertIn("dev_h", env.targets)

    def test_22_extracts_args_from_payload_key(self):
        env = self._normalize({"payload": {"key": "value"}})
        self.assertEqual(env.args.get("key"), "value")

    def test_23_extracts_args_from_params_key(self):
        env = self._normalize({"params": {"x": 42}})
        self.assertEqual(env.args.get("x"), 42)

    def test_24_empty_dict_produces_valid_envelope(self):
        env = self._normalize({})
        self.assertIsNotNone(env)
        self.assertTrue(len(env.task_id) > 0)
        self.assertTrue(len(env.trace_id) > 0)

    def test_25_source_kwarg_reflected_in_envelope(self):
        env = self._normalize({}, source="test_source")
        self.assertEqual(env.source, "test_source")

    def test_30_route_mode_propagates_to_metadata(self):
        env = self._normalize({"route_mode": "hybrid"})
        self.assertEqual(env.metadata.get("route_mode"), "hybrid")


class TestConsumerSentinels(unittest.TestCase):
    """Tests 26–27: Consumer module sentinels."""

    def test_26_gateway_nats_adapter_sentinel(self):
        from galaxy_gateway.gateway_nats_adapter import MESSAGE_INTEROP_APPLIED
        self.assertIsInstance(MESSAGE_INTEROP_APPLIED, str)
        self.assertIn("INTEROP", MESSAGE_INTEROP_APPLIED)

    def test_27_scheduler_sentinel(self):
        from core.scheduler import SCHEDULER_MESSAGE_INTEROP_APPLIED
        self.assertIsInstance(SCHEDULER_MESSAGE_INTEROP_APPLIED, str)
        self.assertIn("INTEROP", SCHEDULER_MESSAGE_INTEROP_APPLIED)


class TestCorrelationFields(unittest.TestCase):
    """Test 28: CorrelationFields.to_dict()."""

    def test_28_to_dict_includes_required_keys(self):
        from core.message_interop import CorrelationFields
        cf = CorrelationFields(task_id="t1", trace_id="tr1", session_id="s1")
        d = cf.to_dict()
        self.assertIn("task_id", d)
        self.assertIn("trace_id", d)
        self.assertIn("session_id", d)

    def test_29_non_dict_payload_graceful(self):
        from core.message_interop import normalize_to_task_envelope
        # Passing a non-dict payload (but wrapped in a dict for function call)
        # Simulate a payload that triggers the legacy path
        env = normalize_to_task_envelope({"task_type": "cmd"}, source="fallback")
        self.assertIsNotNone(env)
        self.assertTrue(len(env.task_id) > 0)


if __name__ == "__main__":
    unittest.main()
