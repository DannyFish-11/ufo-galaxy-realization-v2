#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_fabric_governance.py
================================

PR-4 — Agent Bus & Fabric Convergence: layering model and authority sentinel tests.

Validates that:
 1.  AGENT_BUS_FABRIC_AUTHORITY importable and correct value.
 2.  AGENT_BUS_LAYER importable and contains "AGENT_BUS".
 3.  NATS_CARRIER_LAYER importable and contains "NATS".
 4.  GATEWAY_SUBSTRATE_LAYER importable and contains "GATEWAY".
 5.  COMMAND_ROUTER_STRATEGY_LAYER importable and contains "COMMAND_ROUTER".
 6.  CANONICAL_CONTRACT_POLICY importable and contains "TaskEnvelope".
 7.  TRANSPORT_STRATEGY_DIRECT == "direct".
 8.  TRANSPORT_STRATEGY_GATEWAY == "gateway".
 9.  TRANSPORT_STRATEGY_NATS == "nats".
10.  TRANSPORT_STRATEGY_RELAY == "relay".
11.  TRANSPORT_STRATEGY_MESH == "mesh".
12.  TRANSPORT_STRATEGY_UNKNOWN == "unknown".
13.  FABRIC_REASON_NATS_UNAVAILABLE contains "nats_unavailable".
14.  FABRIC_REASON_GATEWAY_UNAVAILABLE contains "gateway_unavailable".
15.  FABRIC_REASON_STRATEGY_FALLBACK contains "strategy_fallback".
16.  FABRIC_REASON_SEMANTIC_FAILURE contains "semantic_failure".
17.  FABRIC_REASON_DEVICE_TRANSPORT_FAILURE contains "device_transport_failure".
18.  FABRIC_REASON_FABRIC_FAILURE contains "fabric_failure".
19.  NATS_FABRIC_CARRIER_AUTHORITY importable from core.nats_bus.
20.  NATS_FABRIC_CARRIER_AUTHORITY contains "NATS".
21.  GATEWAY_SUBSTRATE_AUTHORITY importable from galaxy_gateway.gateway_nats_adapter.
22.  GATEWAY_SUBSTRATE_AUTHORITY contains "GATEWAY".
23.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED importable from core.command_router.
24.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED contains "COMMAND_ROUTER".
25.  FabricTransportStrategyRecord importable.
26.  FabricTransportStrategyRecord has expected fields.
27.  FabricTransportStrategyRecord.to_dict() returns dict with all fields.
28.  FabricObservabilityRecord importable.
29.  FabricObservabilityRecord has expected fields.
30.  FabricObservabilityRecord.to_dict() returns dict with all fields.
31.  get_fabric_event_log returns deque with maxlen 256.
32.  select_transport_strategy importable.
33.  record_fabric_event importable.
34.  wrap_for_nats importable.
35.  wrap_for_gateway importable.
36.  is_canonical_contract importable.
37.  layer constants are mutually distinct.
38.  strategy constants are mutually distinct.
39.  AGENT_BUS_FABRIC_AUTHORITY starts with "AGENT_BUS_FABRIC".
40.  All public names appear in __all__.

Test index
----------
  1.  AGENT_BUS_FABRIC_AUTHORITY importable.
  2.  AGENT_BUS_LAYER importable.
  3.  NATS_CARRIER_LAYER importable.
  4.  GATEWAY_SUBSTRATE_LAYER importable.
  5.  COMMAND_ROUTER_STRATEGY_LAYER importable.
  6.  CANONICAL_CONTRACT_POLICY importable.
  7.  TRANSPORT_STRATEGY_DIRECT == "direct".
  8.  TRANSPORT_STRATEGY_GATEWAY == "gateway".
  9.  TRANSPORT_STRATEGY_NATS == "nats".
 10.  TRANSPORT_STRATEGY_RELAY == "relay".
 11.  TRANSPORT_STRATEGY_MESH == "mesh".
 12.  TRANSPORT_STRATEGY_UNKNOWN == "unknown".
 13.  FABRIC_REASON_NATS_UNAVAILABLE contains "nats_unavailable".
 14.  FABRIC_REASON_GATEWAY_UNAVAILABLE contains "gateway_unavailable".
 15.  FABRIC_REASON_STRATEGY_FALLBACK contains "strategy_fallback".
 16.  FABRIC_REASON_SEMANTIC_FAILURE contains "semantic_failure".
 17.  FABRIC_REASON_DEVICE_TRANSPORT_FAILURE contains "device_transport_failure".
 18.  FABRIC_REASON_FABRIC_FAILURE contains "fabric_failure".
 19.  NATS_FABRIC_CARRIER_AUTHORITY importable from core.nats_bus.
 20.  NATS_FABRIC_CARRIER_AUTHORITY contains "NATS".
 21.  GATEWAY_SUBSTRATE_AUTHORITY importable from gateway_nats_adapter.
 22.  GATEWAY_SUBSTRATE_AUTHORITY contains "GATEWAY".
 23.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED importable from command_router.
 24.  COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED contains "COMMAND_ROUTER".
 25.  FabricTransportStrategyRecord instantiable.
 26.  FabricTransportStrategyRecord has all expected fields.
 27.  FabricTransportStrategyRecord.to_dict() has all keys.
 28.  FabricObservabilityRecord instantiable.
 29.  FabricObservabilityRecord has all expected fields.
 30.  FabricObservabilityRecord.to_dict() has all keys.
 31.  get_fabric_event_log returns deque maxlen=256.
 32.  select_transport_strategy importable.
 33.  record_fabric_event importable.
 34.  wrap_for_nats importable.
 35.  wrap_for_gateway importable.
 36.  is_canonical_contract importable.
 37.  layer constants mutually distinct.
 38.  strategy constants mutually distinct.
 39.  AGENT_BUS_FABRIC_AUTHORITY starts with "AGENT_BUS_FABRIC".
 40.  All names in __all__ importable.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestAgentBusFabricSentinels(unittest.TestCase):
    """Validate authority sentinels and constants in core.agent_bus_fabric."""

    def test_01_agent_bus_fabric_authority_importable(self):
        from core.agent_bus_fabric import AGENT_BUS_FABRIC_AUTHORITY
        self.assertIsInstance(AGENT_BUS_FABRIC_AUTHORITY, str)
        self.assertTrue(len(AGENT_BUS_FABRIC_AUTHORITY) > 0)

    def test_02_agent_bus_layer_importable(self):
        from core.agent_bus_fabric import AGENT_BUS_LAYER
        self.assertIn("AGENT_BUS", AGENT_BUS_LAYER)

    def test_03_nats_carrier_layer_importable(self):
        from core.agent_bus_fabric import NATS_CARRIER_LAYER
        self.assertIn("NATS", NATS_CARRIER_LAYER)

    def test_04_gateway_substrate_layer_importable(self):
        from core.agent_bus_fabric import GATEWAY_SUBSTRATE_LAYER
        self.assertIn("GATEWAY", GATEWAY_SUBSTRATE_LAYER)

    def test_05_command_router_strategy_layer_importable(self):
        from core.agent_bus_fabric import COMMAND_ROUTER_STRATEGY_LAYER
        self.assertIn("COMMAND_ROUTER", COMMAND_ROUTER_STRATEGY_LAYER)

    def test_06_canonical_contract_policy_importable(self):
        from core.agent_bus_fabric import CANONICAL_CONTRACT_POLICY
        self.assertIn("TaskEnvelope", CANONICAL_CONTRACT_POLICY)

    def test_07_transport_strategy_direct(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_DIRECT
        self.assertEqual(TRANSPORT_STRATEGY_DIRECT, "direct")

    def test_08_transport_strategy_gateway(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_GATEWAY
        self.assertEqual(TRANSPORT_STRATEGY_GATEWAY, "gateway")

    def test_09_transport_strategy_nats(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_NATS
        self.assertEqual(TRANSPORT_STRATEGY_NATS, "nats")

    def test_10_transport_strategy_relay(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_RELAY
        self.assertEqual(TRANSPORT_STRATEGY_RELAY, "relay")

    def test_11_transport_strategy_mesh(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_MESH
        self.assertEqual(TRANSPORT_STRATEGY_MESH, "mesh")

    def test_12_transport_strategy_unknown(self):
        from core.agent_bus_fabric import TRANSPORT_STRATEGY_UNKNOWN
        self.assertEqual(TRANSPORT_STRATEGY_UNKNOWN, "unknown")

    def test_13_fabric_reason_nats_unavailable(self):
        from core.agent_bus_fabric import FABRIC_REASON_NATS_UNAVAILABLE
        self.assertIn("nats_unavailable", FABRIC_REASON_NATS_UNAVAILABLE)

    def test_14_fabric_reason_gateway_unavailable(self):
        from core.agent_bus_fabric import FABRIC_REASON_GATEWAY_UNAVAILABLE
        self.assertIn("gateway_unavailable", FABRIC_REASON_GATEWAY_UNAVAILABLE)

    def test_15_fabric_reason_strategy_fallback(self):
        from core.agent_bus_fabric import FABRIC_REASON_STRATEGY_FALLBACK
        self.assertIn("strategy_fallback", FABRIC_REASON_STRATEGY_FALLBACK)

    def test_16_fabric_reason_semantic_failure(self):
        from core.agent_bus_fabric import FABRIC_REASON_SEMANTIC_FAILURE
        self.assertIn("semantic_failure", FABRIC_REASON_SEMANTIC_FAILURE)

    def test_17_fabric_reason_device_transport_failure(self):
        from core.agent_bus_fabric import FABRIC_REASON_DEVICE_TRANSPORT_FAILURE
        self.assertIn("device_transport_failure", FABRIC_REASON_DEVICE_TRANSPORT_FAILURE)

    def test_18_fabric_reason_fabric_failure(self):
        from core.agent_bus_fabric import FABRIC_REASON_FABRIC_FAILURE
        self.assertIn("fabric_failure", FABRIC_REASON_FABRIC_FAILURE)

    def test_19_nats_fabric_carrier_authority_importable(self):
        from core.nats_bus import NATS_FABRIC_CARRIER_AUTHORITY
        self.assertIsInstance(NATS_FABRIC_CARRIER_AUTHORITY, str)

    def test_20_nats_fabric_carrier_authority_contains_nats(self):
        from core.nats_bus import NATS_FABRIC_CARRIER_AUTHORITY
        self.assertIn("NATS", NATS_FABRIC_CARRIER_AUTHORITY)

    def test_21_gateway_substrate_authority_importable(self):
        from galaxy_gateway.gateway_nats_adapter import GATEWAY_SUBSTRATE_AUTHORITY
        self.assertIsInstance(GATEWAY_SUBSTRATE_AUTHORITY, str)

    def test_22_gateway_substrate_authority_contains_gateway(self):
        from galaxy_gateway.gateway_nats_adapter import GATEWAY_SUBSTRATE_AUTHORITY
        self.assertIn("GATEWAY", GATEWAY_SUBSTRATE_AUTHORITY)

    def test_23_command_router_transport_strategy_applied_importable(self):
        from core.command_router import COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED
        self.assertIsInstance(COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED, str)

    def test_24_command_router_transport_strategy_applied_contains_command_router(self):
        from core.command_router import COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED
        self.assertIn("COMMAND_ROUTER", COMMAND_ROUTER_TRANSPORT_STRATEGY_APPLIED)

    def test_25_fabric_transport_strategy_record_instantiable(self):
        from core.agent_bus_fabric import FabricTransportStrategyRecord
        rec = FabricTransportStrategyRecord()
        self.assertIsNotNone(rec)

    def test_26_fabric_transport_strategy_record_has_fields(self):
        from core.agent_bus_fabric import FabricTransportStrategyRecord
        rec = FabricTransportStrategyRecord(
            strategy="nats",
            fallback_used=False,
            preferred_strategy="nats",
            reason="test",
            task_id="task-1",
            trace_id="trace-1",
        )
        self.assertEqual(rec.strategy, "nats")
        self.assertFalse(rec.fallback_used)
        self.assertEqual(rec.task_id, "task-1")
        self.assertEqual(rec.trace_id, "trace-1")

    def test_27_fabric_transport_strategy_record_to_dict(self):
        from core.agent_bus_fabric import FabricTransportStrategyRecord
        rec = FabricTransportStrategyRecord(strategy="gateway", task_id="t-x")
        d = rec.to_dict()
        self.assertIn("strategy", d)
        self.assertIn("fallback_used", d)
        self.assertIn("preferred_strategy", d)
        self.assertIn("reason", d)
        self.assertIn("task_id", d)
        self.assertIn("trace_id", d)
        self.assertIn("selected_at", d)
        self.assertIn("layer", d)

    def test_28_fabric_observability_record_instantiable(self):
        from core.agent_bus_fabric import FabricObservabilityRecord
        rec = FabricObservabilityRecord()
        self.assertIsNotNone(rec)

    def test_29_fabric_observability_record_has_fields(self):
        from core.agent_bus_fabric import FabricObservabilityRecord
        rec = FabricObservabilityRecord(
            task_id="t-1",
            trace_id="tr-1",
            strategy="nats",
            layer="NATS::CARRIER_FABRIC_LAYER",
            reason="test_reason",
            detail="detail info",
            success=True,
            fallback_triggered=False,
        )
        self.assertEqual(rec.task_id, "t-1")
        self.assertEqual(rec.strategy, "nats")
        self.assertTrue(rec.success)

    def test_30_fabric_observability_record_to_dict(self):
        from core.agent_bus_fabric import FabricObservabilityRecord
        rec = FabricObservabilityRecord(task_id="t-2")
        d = rec.to_dict()
        self.assertIn("event_id", d)
        self.assertIn("task_id", d)
        self.assertIn("trace_id", d)
        self.assertIn("strategy", d)
        self.assertIn("layer", d)
        self.assertIn("reason", d)
        self.assertIn("detail", d)
        self.assertIn("success", d)
        self.assertIn("fallback_triggered", d)
        self.assertIn("recorded_at", d)

    def test_31_get_fabric_event_log_returns_deque_maxlen_256(self):
        from collections import deque
        from core.agent_bus_fabric import get_fabric_event_log
        log = get_fabric_event_log()
        self.assertIsInstance(log, deque)
        self.assertEqual(log.maxlen, 256)

    def test_32_select_transport_strategy_importable(self):
        from core.agent_bus_fabric import select_transport_strategy
        self.assertTrue(callable(select_transport_strategy))

    def test_33_record_fabric_event_importable(self):
        from core.agent_bus_fabric import record_fabric_event
        self.assertTrue(callable(record_fabric_event))

    def test_34_wrap_for_nats_importable(self):
        from core.agent_bus_fabric import wrap_for_nats
        self.assertTrue(callable(wrap_for_nats))

    def test_35_wrap_for_gateway_importable(self):
        from core.agent_bus_fabric import wrap_for_gateway
        self.assertTrue(callable(wrap_for_gateway))

    def test_36_is_canonical_contract_importable(self):
        from core.agent_bus_fabric import is_canonical_contract
        self.assertTrue(callable(is_canonical_contract))

    def test_37_layer_constants_mutually_distinct(self):
        from core.agent_bus_fabric import (
            AGENT_BUS_LAYER,
            NATS_CARRIER_LAYER,
            GATEWAY_SUBSTRATE_LAYER,
            COMMAND_ROUTER_STRATEGY_LAYER,
        )
        layers = {AGENT_BUS_LAYER, NATS_CARRIER_LAYER, GATEWAY_SUBSTRATE_LAYER, COMMAND_ROUTER_STRATEGY_LAYER}
        self.assertEqual(len(layers), 4)

    def test_38_strategy_constants_mutually_distinct(self):
        from core.agent_bus_fabric import (
            TRANSPORT_STRATEGY_DIRECT,
            TRANSPORT_STRATEGY_GATEWAY,
            TRANSPORT_STRATEGY_NATS,
            TRANSPORT_STRATEGY_RELAY,
            TRANSPORT_STRATEGY_MESH,
            TRANSPORT_STRATEGY_UNKNOWN,
        )
        strategies = {
            TRANSPORT_STRATEGY_DIRECT,
            TRANSPORT_STRATEGY_GATEWAY,
            TRANSPORT_STRATEGY_NATS,
            TRANSPORT_STRATEGY_RELAY,
            TRANSPORT_STRATEGY_MESH,
            TRANSPORT_STRATEGY_UNKNOWN,
        }
        self.assertEqual(len(strategies), 6)

    def test_39_agent_bus_fabric_authority_starts_with_prefix(self):
        from core.agent_bus_fabric import AGENT_BUS_FABRIC_AUTHORITY
        self.assertTrue(AGENT_BUS_FABRIC_AUTHORITY.startswith("AGENT_BUS_FABRIC"))

    def test_40_all_names_in_dunder_all_importable(self):
        import core.agent_bus_fabric as mod
        for name in mod.__all__:
            self.assertTrue(
                hasattr(mod, name),
                f"__all__ entry '{name}' not found in module",
            )


if __name__ == "__main__":
    unittest.main()
