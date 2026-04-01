#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_transport_strategy_fallback.py
==========================================

PR-4 — Agent Bus & Fabric Convergence: transport strategy selection and fallback.

Validates that:
 1.  select_transport_strategy: nothing available → strategy = "unknown".
 2.  select_transport_strategy: direct only → "direct".
 3.  select_transport_strategy: direct beats gateway when both available.
 4.  select_transport_strategy: gateway beats nats when both available (no direct).
 5.  select_transport_strategy: nats beats relay when both available (no direct/gateway).
 6.  select_transport_strategy: relay beats mesh when both available.
 7.  select_transport_strategy: mesh only → "mesh".
 8.  select_transport_strategy: preferred "direct" available → no fallback.
 9.  select_transport_strategy: preferred "direct" unavailable, gateway available → fallback.
10.  select_transport_strategy: preferred "gateway" unavailable, only relay → relay + fallback.
11.  select_transport_strategy: preferred "nats" unavailable, nothing else → "unknown".
12.  select_transport_strategy: preferred "mesh" available → "mesh", no fallback.
13.  select_transport_strategy: preferred "relay" unavailable, nats available → fallback.
14.  FabricTransportStrategyRecord layer == COMMAND_ROUTER_STRATEGY_LAYER.
15.  FabricTransportStrategyRecord preferred_strategy reflects caller preference.
16.  FabricTransportStrategyRecord.to_dict() includes fallback_used field.
17.  record_fabric_event fallback_triggered=True captured in record.
18.  record_fabric_event fallback_triggered=False captured in record.
19.  Fabric event ring buffer maxlen prevents unbounded growth.
20.  record_fabric_event appended to ring buffer.
21.  FabricTransportStrategyRecord selected_at is a float.
22.  FabricObservabilityRecord event_id is non-empty string.
23.  select_transport_strategy: task_id + trace_id propagated to record.
24.  select_transport_strategy: no preference, all available → "direct".
25.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED in core.command_router.

Test index
----------
  1.  nothing available → "unknown".
  2.  direct only → "direct".
  3.  direct beats gateway.
  4.  gateway beats nats.
  5.  nats beats relay.
  6.  relay beats mesh.
  7.  mesh only → "mesh".
  8.  preferred direct available → no fallback.
  9.  preferred direct unavailable → fallback.
 10.  preferred gateway unavailable → relay + fallback.
 11.  preferred nats unavailable, nothing else → "unknown".
 12.  preferred mesh available → "mesh", no fallback.
 13.  preferred relay unavailable → fallback.
 14.  FabricTransportStrategyRecord layer == COMMAND_ROUTER_STRATEGY_LAYER.
 15.  preferred_strategy reflects caller preference.
 16.  to_dict() includes fallback_used.
 17.  record_fabric_event fallback_triggered=True.
 18.  record_fabric_event fallback_triggered=False.
 19.  ring buffer maxlen prevents growth.
 20.  record_fabric_event appended.
 21.  selected_at is float.
 22.  event_id is non-empty string.
 23.  task_id + trace_id propagated.
 24.  no preference, all available → "direct".
 25.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED in command_router.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestTransportStrategySelection(unittest.TestCase):
    """Validate select_transport_strategy priority and fallback rules."""

    def test_01_nothing_available_returns_unknown(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_UNKNOWN
        rec = select_transport_strategy()
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_UNKNOWN)

    def test_02_direct_only_returns_direct(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_DIRECT
        rec = select_transport_strategy(direct_available=True)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_DIRECT)

    def test_03_direct_beats_gateway_when_both_available(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_DIRECT
        rec = select_transport_strategy(direct_available=True, gateway_available=True)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_DIRECT)

    def test_04_gateway_beats_nats_when_direct_unavailable(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_GATEWAY
        rec = select_transport_strategy(
            direct_available=False,
            gateway_available=True,
            nats_available=True,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_GATEWAY)

    def test_05_nats_beats_relay_when_direct_and_gateway_unavailable(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_NATS
        rec = select_transport_strategy(
            direct_available=False,
            gateway_available=False,
            nats_available=True,
            relay_available=True,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_NATS)

    def test_06_relay_beats_mesh(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_RELAY
        rec = select_transport_strategy(
            direct_available=False,
            gateway_available=False,
            nats_available=False,
            relay_available=True,
            mesh_available=True,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_RELAY)

    def test_07_mesh_only_returns_mesh(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_MESH
        rec = select_transport_strategy(mesh_available=True)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_MESH)

    def test_08_preferred_direct_available_no_fallback(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_DIRECT
        rec = select_transport_strategy(
            direct_available=True,
            preferred=TRANSPORT_STRATEGY_DIRECT,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_DIRECT)
        self.assertFalse(rec.fallback_used)

    def test_09_preferred_direct_unavailable_gateway_available_fallback(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            TRANSPORT_STRATEGY_DIRECT,
            TRANSPORT_STRATEGY_GATEWAY,
        )
        rec = select_transport_strategy(
            direct_available=False,
            gateway_available=True,
            preferred=TRANSPORT_STRATEGY_DIRECT,
        )
        self.assertNotEqual(rec.strategy, TRANSPORT_STRATEGY_DIRECT)
        self.assertTrue(rec.fallback_used)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_GATEWAY)

    def test_10_preferred_gateway_unavailable_only_relay(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            TRANSPORT_STRATEGY_GATEWAY,
            TRANSPORT_STRATEGY_RELAY,
        )
        rec = select_transport_strategy(
            gateway_available=False,
            nats_available=False,
            relay_available=True,
            preferred=TRANSPORT_STRATEGY_GATEWAY,
        )
        self.assertTrue(rec.fallback_used)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_RELAY)

    def test_11_preferred_nats_unavailable_nothing_else_unknown(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            TRANSPORT_STRATEGY_NATS,
            TRANSPORT_STRATEGY_UNKNOWN,
        )
        rec = select_transport_strategy(
            nats_available=False,
            preferred=TRANSPORT_STRATEGY_NATS,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_UNKNOWN)

    def test_12_preferred_mesh_available_no_fallback(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_MESH
        rec = select_transport_strategy(
            mesh_available=True,
            preferred=TRANSPORT_STRATEGY_MESH,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_MESH)
        self.assertFalse(rec.fallback_used)

    def test_13_preferred_relay_unavailable_nats_available_fallback(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            TRANSPORT_STRATEGY_RELAY,
            TRANSPORT_STRATEGY_NATS,
        )
        rec = select_transport_strategy(
            relay_available=False,
            nats_available=True,
            preferred=TRANSPORT_STRATEGY_RELAY,
        )
        self.assertTrue(rec.fallback_used)
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_NATS)

    def test_24_no_preference_all_available_selects_direct(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_DIRECT
        rec = select_transport_strategy(
            direct_available=True,
            gateway_available=True,
            nats_available=True,
            relay_available=True,
            mesh_available=True,
        )
        self.assertEqual(rec.strategy, TRANSPORT_STRATEGY_DIRECT)
        self.assertFalse(rec.fallback_used)


class TestFabricTransportStrategyRecord(unittest.TestCase):
    """Validate FabricTransportStrategyRecord fields and output."""

    def test_14_record_layer_is_command_router_strategy_layer(self):
        from core.agent_bus_fabric import (
            select_transport_strategy,
            COMMAND_ROUTER_STRATEGY_LAYER,
        )
        rec = select_transport_strategy(direct_available=True)
        self.assertEqual(rec.layer, COMMAND_ROUTER_STRATEGY_LAYER)

    def test_15_preferred_strategy_reflects_caller_preference(self):
        from core.agent_bus_fabric import select_transport_strategy, TRANSPORT_STRATEGY_GATEWAY
        rec = select_transport_strategy(
            gateway_available=True,
            preferred=TRANSPORT_STRATEGY_GATEWAY,
        )
        self.assertEqual(rec.preferred_strategy, TRANSPORT_STRATEGY_GATEWAY)

    def test_16_to_dict_includes_fallback_used(self):
        from core.agent_bus_fabric import select_transport_strategy
        rec = select_transport_strategy(direct_available=True)
        d = rec.to_dict()
        self.assertIn("fallback_used", d)
        self.assertIsInstance(d["fallback_used"], bool)

    def test_21_selected_at_is_float(self):
        from core.agent_bus_fabric import select_transport_strategy
        rec = select_transport_strategy(nats_available=True)
        self.assertIsInstance(rec.selected_at, float)
        self.assertGreater(rec.selected_at, 0)

    def test_23_task_id_and_trace_id_propagated(self):
        from core.agent_bus_fabric import select_transport_strategy
        rec = select_transport_strategy(
            nats_available=True,
            task_id="my-task-123",
            trace_id="my-trace-456",
        )
        self.assertEqual(rec.task_id, "my-task-123")
        self.assertEqual(rec.trace_id, "my-trace-456")


class TestFabricObservabilityRingBuffer(unittest.TestCase):
    """Validate FabricObservabilityRecord and ring buffer behaviour."""

    def test_17_record_fabric_event_fallback_triggered_true(self):
        from core.agent_bus_fabric import record_fabric_event
        rec = record_fabric_event(fallback_triggered=True)
        self.assertTrue(rec.fallback_triggered)

    def test_18_record_fabric_event_fallback_triggered_false(self):
        from core.agent_bus_fabric import record_fabric_event
        rec = record_fabric_event(fallback_triggered=False)
        self.assertFalse(rec.fallback_triggered)

    def test_19_ring_buffer_maxlen_prevents_unbounded_growth(self):
        from core.agent_bus_fabric import record_fabric_event, get_fabric_event_log
        log = get_fabric_event_log()
        for _ in range(300):
            record_fabric_event(task_id="overflow-test")
        self.assertLessEqual(len(log), 256)

    def test_20_record_fabric_event_appended_to_log(self):
        from core.agent_bus_fabric import record_fabric_event, get_fabric_event_log
        log = get_fabric_event_log()
        before = len(log)
        marker = f"append-test-{id(self)}"
        record_fabric_event(task_id=marker, detail="ring buffer append")
        # When the buffer is full (256) appending maintains maxlen.
        # When not full it grows by 1.  Either way the marker must be present.
        last = log[-1]
        self.assertEqual(last.task_id, marker)

    def test_22_event_id_is_non_empty_string(self):
        from core.agent_bus_fabric import record_fabric_event
        rec = record_fabric_event(task_id="event-id-test")
        self.assertIsInstance(rec.event_id, str)
        self.assertTrue(len(rec.event_id) > 0)


class TestCommandRouterTransportStrategyApplied(unittest.TestCase):
    """Validate COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED sentinel in command_router."""

    def test_25_command_router_transport_strategy_applied_importable(self):
        from core.command_router import COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED
        self.assertIsInstance(COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED, str)
        self.assertIn("COMMAND_ROUTER", COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED)


if __name__ == "__main__":
    unittest.main()
