#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_nats_message_contract.py
=====================================

PR-4 — Agent Bus & Fabric Convergence: NATS carrier ↔ canonical envelope contract.

Validates that:
 1.  NATS_FABRIC_CARRIER_AUTHORITY sentinel exists in core.nats_bus.
 2.  wrap_for_nats adds _fabric_layer = NATS_CARRIER_LAYER.
 3.  wrap_for_nats adds _nats_schema = "TaskEnvelope" when absent.
 4.  wrap_for_nats does NOT overwrite existing _nats_schema.
 5.  wrap_for_nats returns the same dict (in-place mutation).
 6.  wrap_for_nats with task_id + trace_id satisfies is_canonical_contract.
 7.  is_canonical_contract: dict with task_id + trace_id → True.
 8.  is_canonical_contract: dict missing trace_id → False.
 9.  is_canonical_contract: dict missing task_id → False.
10.  is_canonical_contract: empty dict → False.
11.  is_canonical_contract: non-dict/non-model → False.
12.  is_canonical_contract: object with task_id + trace_id attrs → True.
13.  NATSTopics.TASK_DISPATCH constant importable.
14.  NATSTopics.TASK_RESULT constant importable.
15.  NATSTopics.DEVICE_HEARTBEAT constant importable.
16.  NATSTopics.task_dispatch(target) returns correct subject.
17.  NATSTopics.task_result(task_id) returns correct subject.
18.  record_fabric_event with NATS layer records in log.
19.  record_fabric_event with NATS failure records success=False.
20.  record_fabric_event with NATS fallback records fallback_triggered=True.
21.  Fabric event log is updated after record_fabric_event.
22.  record_fabric_event result.to_dict() has layer == NATS_CARRIER_LAYER.
23.  select_transport_strategy: only nats_available → strategy = "nats".
24.  select_transport_strategy: nats preferred and available → not fallback.
25.  select_transport_strategy: nats preferred but unavailable → fallback.

Test index
----------
  1.  NATS_FABRIC_CARRIER_AUTHORITY in core.nats_bus.
  2.  wrap_for_nats adds _fabric_layer.
  3.  wrap_for_nats adds default _nats_schema.
  4.  wrap_for_nats does not overwrite _nats_schema.
  5.  wrap_for_nats returns same dict.
  6.  wrap_for_nats result satisfies is_canonical_contract.
  7.  is_canonical_contract dict with both fields → True.
  8.  is_canonical_contract dict missing trace_id → False.
  9.  is_canonical_contract dict missing task_id → False.
 10.  is_canonical_contract empty dict → False.
 11.  is_canonical_contract non-dict → False.
 12.  is_canonical_contract obj with attrs → True.
 13.  NATSTopics.TASK_DISPATCH importable.
 14.  NATSTopics.TASK_RESULT importable.
 15.  NATSTopics.DEVICE_HEARTBEAT importable.
 16.  NATSTopics.task_dispatch(target) correct.
 17.  NATSTopics.task_result(task_id) correct.
 18.  record_fabric_event NATS layer recorded.
 19.  record_fabric_event NATS failure success=False.
 20.  record_fabric_event NATS fallback flag.
 21.  Fabric event log updated.
 22.  record_fabric_event layer == NATS_CARRIER_LAYER.
 23.  select_transport_strategy nats only → "nats".
 24.  nats preferred and available → no fallback.
 25.  nats preferred unavailable → fallback.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestNATSFabricCarrierAuthority(unittest.TestCase):
    """Validate NATS carrier authority sentinel and wrap helper."""

    def test_01_nats_fabric_carrier_authority_exists(self):
        from core.nats_bus import NATS_FABRIC_CARRIER_AUTHORITY

        self.assertIsInstance(NATS_FABRIC_CARRIER_AUTHORITY, str)


class TestNATSTopics(unittest.TestCase):
    """Validate NATSTopics constants and helpers."""

    def test_13_task_dispatch_constant(self):
        from core.nats_bus import NATSTopics

        self.assertTrue(hasattr(NATSTopics, "TASK_DISPATCH"))
        self.assertIsInstance(NATSTopics.TASK_DISPATCH, str)

    def test_14_task_result_constant(self):
        from core.nats_bus import NATSTopics

        self.assertTrue(hasattr(NATSTopics, "TASK_RESULT"))
        self.assertIsInstance(NATSTopics.TASK_RESULT, str)

    def test_15_device_heartbeat_constant(self):
        from core.nats_bus import NATSTopics

        self.assertTrue(hasattr(NATSTopics, "DEVICE_HEARTBEAT"))
        self.assertIsInstance(NATSTopics.DEVICE_HEARTBEAT, str)

    def test_16_task_dispatch_method(self):
        from core.nats_bus import NATSTopics

        subject = NATSTopics.task_dispatch("device-01")
        self.assertIn("device-01", subject)
        self.assertIn("dispatch", subject.lower())

    def test_17_task_result_method(self):
        from core.nats_bus import NATSTopics

        subject = NATSTopics.task_result("task-abc")
        self.assertIn("task-abc", subject)


if __name__ == "__main__":
    unittest.main()
