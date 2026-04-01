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
        self.assertIn("NATS", NATS_FABRIC_CARRIER_AUTHORITY)

    def test_02_wrap_for_nats_adds_fabric_layer(self):
        from core.agent_bus_fabric import wrap_for_nats, NATS_CARRIER_LAYER
        payload = {"task_id": "t-1", "trace_id": "tr-1"}
        result = wrap_for_nats(payload)
        self.assertEqual(result["_fabric_layer"], NATS_CARRIER_LAYER)

    def test_03_wrap_for_nats_adds_default_nats_schema(self):
        from core.agent_bus_fabric import wrap_for_nats
        payload = {"task_id": "t-1", "trace_id": "tr-1"}
        result = wrap_for_nats(payload)
        self.assertEqual(result["_nats_schema"], "TaskEnvelope")

    def test_04_wrap_for_nats_does_not_overwrite_existing_nats_schema(self):
        from core.agent_bus_fabric import wrap_for_nats
        payload = {
            "task_id": "t-1",
            "trace_id": "tr-1",
            "_nats_schema": "ResultEnvelope",
        }
        result = wrap_for_nats(payload)
        self.assertEqual(result["_nats_schema"], "ResultEnvelope")

    def test_05_wrap_for_nats_returns_same_dict(self):
        from core.agent_bus_fabric import wrap_for_nats
        payload = {"task_id": "t-1", "trace_id": "tr-1"}
        result = wrap_for_nats(payload)
        self.assertIs(result, payload)

    def test_06_wrap_for_nats_result_satisfies_canonical_contract(self):
        from core.agent_bus_fabric import wrap_for_nats, is_canonical_contract
        payload = {"task_id": "t-1", "trace_id": "tr-1"}
        result = wrap_for_nats(payload)
        self.assertTrue(is_canonical_contract(result))


class TestIsCanonicalContract(unittest.TestCase):
    """Validate is_canonical_contract predicate."""

    def test_07_dict_with_both_fields_true(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertTrue(is_canonical_contract({"task_id": "t", "trace_id": "tr"}))

    def test_08_dict_missing_trace_id_false(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertFalse(is_canonical_contract({"task_id": "t"}))

    def test_09_dict_missing_task_id_false(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertFalse(is_canonical_contract({"trace_id": "tr"}))

    def test_10_empty_dict_false(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertFalse(is_canonical_contract({}))

    def test_11_non_dict_false(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertFalse(is_canonical_contract("not a dict"))
        self.assertFalse(is_canonical_contract(42))
        self.assertFalse(is_canonical_contract(None))

    def test_12_object_with_task_and_trace_attrs_true(self):
        from core.agent_bus_fabric import is_canonical_contract

        class _FakeEnvelope:
            task_id = "t-1"
            trace_id = "tr-1"

        self.assertTrue(is_canonical_contract(_FakeEnvelope()))


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
        self.assertIn("result", subject.lower())


class TestNATSFabricObservability(unittest.TestCase):
    """Validate fabric observability records for the NATS layer."""

    def test_18_record_fabric_event_nats_layer_recorded(self):
        from core.agent_bus_fabric import record_fabric_event, NATS_CARRIER_LAYER, get_fabric_event_log
        log = get_fabric_event_log()
        initial_count = len(log)
        record_fabric_event(
            task_id="t-obs-1",
            trace_id="tr-obs-1",
            strategy="nats",
            layer=NATS_CARRIER_LAYER,
            reason="test_recorded",
            success=True,
        )
        self.assertGreater(len(log), initial_count)
        last = log[-1]
        self.assertEqual(last.task_id, "t-obs-1")
        self.assertEqual(last.layer, NATS_CARRIER_LAYER)

    def test_19_record_fabric_event_nats_failure(self):
        from core.agent_bus_fabric import (
            record_fabric_event,
            NATS_CARRIER_LAYER,
            FABRIC_REASON_NATS_UNAVAILABLE,
        )
        rec = record_fabric_event(
            task_id="t-fail",
            strategy="nats",
            layer=NATS_CARRIER_LAYER,
            reason=FABRIC_REASON_NATS_UNAVAILABLE,
            success=False,
        )
        self.assertFalse(rec.success)
        self.assertEqual(rec.reason, FABRIC_REASON_NATS_UNAVAILABLE)

    def test_20_record_fabric_event_nats_fallback_flag(self):
        from core.agent_bus_fabric import (
            record_fabric_event,
            NATS_CARRIER_LAYER,
            FABRIC_REASON_STRATEGY_FALLBACK,
        )
        rec = record_fabric_event(
            task_id="t-fb",
            strategy="relay",
            layer=NATS_CARRIER_LAYER,
            reason=FABRIC_REASON_STRATEGY_FALLBACK,
            fallback_triggered=True,
        )
        self.assertTrue(rec.fallback_triggered)

    def test_21_fabric_event_log_updated_after_record(self):
        from core.agent_bus_fabric import record_fabric_event, NATS_CARRIER_LAYER, get_fabric_event_log
        log = get_fabric_event_log()
        marker = f"t-log-{id(self)}"
        record_fabric_event(task_id=marker, layer=NATS_CARRIER_LAYER)
        # Ring buffer may be at maxlen; verify the marker is at the tail
        self.assertEqual(log[-1].task_id, marker)

    def test_22_record_fabric_event_layer_is_nats(self):
        from core.agent_bus_fabric import record_fabric_event, NATS_CARRIER_LAYER
        rec = record_fabric_event(
            task_id="t-layer",
            layer=NATS_CARRIER_LAYER,
        )
        self.assertEqual(rec.layer, NATS_CARRIER_LAYER)


class TestNATSTransportStrategy(unittest.TestCase):
    """Validate transport strategy selection for NATS paths."""

    def test_23_only_nats_available_selects_nats(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_NATS
        rec = select_transport_strategy(nats_available=True)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_NATS)

    def test_24_nats_preferred_and_available_no_fallback(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_NATS
        rec = select_transport_strategy(
            nats_available=True,
            preferred=TRANSPORT_STRATEGY_NATS,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_NATS)
        self.assertFalse(rec.fallback_used)

    def test_25_nats_preferred_but_unavailable_triggers_fallback(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            TRANSPORT_STRATEGY_NATS,
            TRANSPORT_STRATEGY_GATEWAY,
        )
        rec = select_transport_strategy(
            nats_available=False,
            gateway_available=True,
            preferred=TRANSPORT_STRATEGY_NATS,
        )
        self.assertNotEqual(rec.strategy, TRANSPORT_STRATEGY_NATS)
        self.assertTrue(rec.fallback_used)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_GATEWAY)


if __name__ == "__main__":
    unittest.main()
