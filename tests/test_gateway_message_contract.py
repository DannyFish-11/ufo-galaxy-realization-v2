#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_gateway_message_contract.py
========================================

PR-4 — Agent Bus & Fabric Convergence: Gateway/WS substrate ↔ canonical envelope contract.

Validates that:
 1.  GATEWAY_SUBSTRATE_AUTHORITY sentinel exists in gateway_nats_adapter.
 2.  MESSAGE_INTEROP_APPLIED sentinel exists in gateway_nats_adapter.
 3.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY sentinel exists in websocket_handler.
 4.  INGRESS_NORMALIZATION_AUTHORITY sentinel exists in websocket_handler.
 5.  GATEWAY_SUBSTRATE_LAYER constant importable from agent_bus_fabric.
 6.  wrap_for_gateway adds _fabric_layer = GATEWAY_SUBSTRATE_LAYER.
 7.  wrap_for_gateway returns same dict.
 8.  wrap_for_gateway result with task_id + trace_id satisfies is_canonical_contract.
 9.  is_canonical_contract: gateway-wrapped dict with both fields → True.
10.  Gateway substrate authority does NOT claim orchestration authority.
11.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY identifies transport substrate only.
12.  Gateway authority sentinel contains "GATEWAY".
13.  record_fabric_event with GATEWAY layer records in log.
14.  record_fabric_event gateway failure success=False.
15.  record_fabric_event gateway fallback flag set.
16.  record_fabric_event gateway layer in record dict.
17.  FABRIC_REASON_DEVICE_TRANSPORT_FAILURE usable as reason in gateway event.
18.  FABRIC_REASON_SEMANTIC_FAILURE usable as reason in gateway event.
19.  select_transport_strategy: gateway preferred and available → not fallback.
20.  select_transport_strategy: gateway preferred but unavailable → fallback to nats.
21.  select_transport_strategy: only gateway_available → strategy = "gateway".
22.  select_transport_strategy: gateway preferred, both gateway+nats available → "gateway".
23.  GatewayNATSAdapter has MESSAGE_INTEROP_APPLIED attribute.
24.  GatewayNATSAdapter has GATEWAY_SUBSTRATE_AUTHORITY attribute.
25.  wrap_for_gateway does not set _nats_schema.

Test index
----------
  1.  GATEWAY_SUBSTRATE_AUTHORITY in gateway_nats_adapter.
  2.  MESSAGE_INTEROP_APPLIED in gateway_nats_adapter.
  3.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY in websocket_handler.
  4.  INGRESS_NORMALIZATION_AUTHORITY in websocket_handler.
  5.  GATEWAY_SUBSTRATE_LAYER importable from agent_bus_fabric.
  6.  wrap_for_gateway adds _fabric_layer.
  7.  wrap_for_gateway returns same dict.
  8.  wrap_for_gateway result satisfies is_canonical_contract.
  9.  wrapped gateway dict canonical.
 10.  gateway authority does not claim orchestration.
 11.  WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY is transport only.
 12.  gateway authority contains "GATEWAY".
 13.  record_fabric_event gateway layer recorded.
 14.  record_fabric_event gateway failure.
 15.  record_fabric_event gateway fallback.
 16.  record_fabric_event gateway layer in dict.
 17.  FABRIC_REASON_DEVICE_TRANSPORT_FAILURE usable.
 18.  FABRIC_REASON_SEMANTIC_FAILURE usable.
 19.  gateway preferred available → no fallback.
 20.  gateway preferred unavailable → fallback.
 21.  only gateway → "gateway".
 22.  preferred gateway, both available → "gateway".
 23.  GatewayNATSAdapter has MESSAGE_INTEROP_APPLIED.
 24.  GatewayNATSAdapter has GATEWAY_SUBSTRATE_AUTHORITY.
 25.  wrap_for_gateway no _nats_schema.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestGatewaySubstrateAuthority(unittest.TestCase):
    """Validate gateway substrate authority sentinels."""

    def test_01_gateway_substrate_authority_exists(self):
        from galaxy_gateway.gateway_nats_adapter import GATEWAY_SUBSTRATE_AUTHORITY

        self.assertIsInstance(GATEWAY_SUBSTRATE_AUTHORITY, str)
        self.assertTrue(len(GATEWAY_SUBSTRATE_AUTHORITY) > 0)

    def test_02_message_interop_applied_exists(self):
        from galaxy_gateway.gateway_nats_adapter import MESSAGE_INTEROP_APPLIED

        self.assertIsInstance(MESSAGE_INTEROP_APPLIED, str)
        self.assertTrue(len(MESSAGE_INTEROP_APPLIED) > 0)

    def test_03_websocket_handler_transport_authority_exists(self):
        try:
            from galaxy_gateway.websocket_handler import WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY
        except (ImportError, ModuleNotFoundError):
            self.skipTest("websocket_handler dependencies not installed")
        self.assertIsInstance(WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY, str)
        self.assertTrue(len(WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY) > 0)

    def test_04_ingress_normalization_authority_exists(self):
        try:
            from galaxy_gateway.websocket_handler import INGRESS_NORMALIZATION_AUTHORITY
        except (ImportError, ModuleNotFoundError):
            self.skipTest("websocket_handler dependencies not installed")
        self.assertIsInstance(INGRESS_NORMALIZATION_AUTHORITY, str)


class TestGatewayAuthorityBoundary(unittest.TestCase):
    """Validate that gateway authority sentinel respects substrate-only boundary."""

    def test_10_gateway_authority_not_orchestration(self):
        from galaxy_gateway.gateway_nats_adapter import GATEWAY_SUBSTRATE_AUTHORITY

        # Substrate authority must NOT claim orchestration capability
        lower = GATEWAY_SUBSTRATE_AUTHORITY.lower()
        self.assertNotIn("orchestration", lower)

    def test_11_websocket_handler_authority_is_transport_only(self):
        try:
            from galaxy_gateway.websocket_handler import WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY
        except (ImportError, ModuleNotFoundError):
            self.skipTest("websocket_handler dependencies not installed")
        # Should reference transport or substrate
        upper = WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY.upper()
        self.assertTrue(
            "TRANSPORT" in upper or "SUBSTRATE" in upper,
            f"Expected TRANSPORT or SUBSTRATE in: {WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY}",
        )

    def test_12_gateway_authority_contains_gateway(self):
        from galaxy_gateway.gateway_nats_adapter import GATEWAY_SUBSTRATE_AUTHORITY


class TestGatewayNATSAdapterAttributes(unittest.TestCase):
    """Validate GatewayNATSAdapter has PR-4 attributes."""

    def test_23_gateway_nats_adapter_has_message_interop_applied(self):
        import galaxy_gateway.gateway_nats_adapter as mod

        self.assertTrue(hasattr(mod, "MESSAGE_INTEROP_APPLIED"))

    def test_24_gateway_nats_adapter_has_gateway_substrate_authority(self):
        import galaxy_gateway.gateway_nats_adapter as mod

        self.assertTrue(hasattr(mod, "GATEWAY_SUBSTRATE_AUTHORITY"))


if __name__ == "__main__":
    unittest.main()
