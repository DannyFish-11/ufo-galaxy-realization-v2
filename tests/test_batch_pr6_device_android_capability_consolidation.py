#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_batch_pr6_device_android_capability_consolidation.py
================================================================

Batch PR-6 — Device routing, Android bridge, and Capability subsystem
consolidation.

Validates:
  ── Device routing ──────────────────────────────────────────────────────────
  1.  galaxy_gateway/device_router.py exists.
  2.  galaxy_gateway/device_router.py defines CANONICAL_DISPATCH_AUTHORITY.
  3.  CANONICAL_DISPATCH_AUTHORITY value is correct.
  4.  galaxy_gateway/device_router.py defines DEVICE_ROUTING_CANONICAL_PATH.
  5.  DEVICE_ROUTING_CANONICAL_PATH == CANONICAL_DISPATCH_AUTHORITY.
  6.  galaxy_gateway/routing/__init__.py exists.
  7.  galaxy_gateway/routing/__init__.py exports DEVICE_HEALTH_POLICY_AUTHORITY.
  8.  galaxy_gateway/routing/__init__.py exports DEVICE_SELECTION_AUTHORITY.
  9.  galaxy_gateway/routing/__init__.py exports ROUTING_POLICY_AUTHORITY.
 10.  galaxy_gateway/routing/__init__.py exports DISPATCH_AUTHORITY.
 11.  galaxy_gateway/routing/router.py exports ROUTING_ORCHESTRATION_AUTHORITY.
 12.  galaxy_gateway/task_router.py is classified as legacy in SIDE_PATH_MODULE_REGISTRY.
 13.  galaxy_gateway/routing/dispatch.py defines DISPATCH_AUTHORITY sentinel.
 14.  galaxy_gateway/routing/policy.py defines ROUTING_POLICY_AUTHORITY sentinel.
 15.  galaxy_gateway/routing/device_selection.py defines DEVICE_SELECTION_AUTHORITY.
 16.  galaxy_gateway/routing/health_policy.py defines DEVICE_HEALTH_POLICY_AUTHORITY.
 17.  DEVICE_ROUTER_DISPATCH_AUTHORITY in canonical_execution_chain matches device_router.
 18.  DeviceRouter.send_command_to_device is callable.
 19.  galaxy_gateway/routing/router.py defines RoutingOrchestrator class.
 20.  RoutingOrchestrator exposes DISPATCH_AUTHORITY class constant.

  ── Android bridge ───────────────────────────────────────────────────────────
 21.  galaxy_gateway/android_bridge.py exists.
 22.  galaxy_gateway/android_bridge.py defines ANDROID_BRIDGE_IMPL_AUTHORITY.
 23.  ANDROID_BRIDGE_IMPL_AUTHORITY value is correct.
 24.  galaxy_gateway/android_bridge.py defines ANDROID_BRIDGE_CANONICAL_PATH.
 25.  ANDROID_BRIDGE_CANONICAL_PATH == ANDROID_BRIDGE_IMPL_AUTHORITY.
 26.  galaxy_gateway/android/__init__.py exists.
 27.  galaxy_gateway/android/__init__.py defines ANDROID_BRIDGE_PACKAGE_AUTHORITY.
 28.  ANDROID_BRIDGE_PACKAGE_AUTHORITY == "galaxy_gateway.android".
 29.  galaxy_gateway/android/__init__.py exports DeviceCapability.
 30.  galaxy_gateway/android/__init__.py exports AndroidDevice.
 31.  galaxy_gateway/android/__init__.py exports MessageBuilder.
 32.  galaxy_gateway/android/bridge.py exists.
 33.  galaxy_gateway/android/bridge.py exports AndroidBridge.
 34.  galaxy_gateway/android/bridge.py exports ANDROID_BRIDGE_IMPL_AUTHORITY.
 35.  galaxy_gateway/android/bridge.py exports ANDROID_BRIDGE_CANONICAL_PATH.
 36.  galaxy_gateway/android/bridge.py defines ANDROID_BRIDGE_REEXPORT_SURFACE.
 37.  ANDROID_BRIDGE_REEXPORT_SURFACE == "galaxy_gateway.android.bridge".
 38.  AndroidBridge class exists and is importable from android_bridge.
 39.  AndroidBridge has handle_message method.
 40.  AndroidBridge has disconnect_device method.

  ── Capability subsystem ─────────────────────────────────────────────────────
 41.  core/capability/__init__.py exists.
 42.  core/capability/__init__.py defines CAPABILITY_PACKAGE_AUTHORITY.
 43.  CAPABILITY_PACKAGE_AUTHORITY == "core.capability".
 44.  core/capability/__init__.py re-exports CAPABILITY_REGISTRY_AUTHORITY.
 45.  core/capability/__init__.py re-exports CAPABILITY_BUS_AUTHORITY.
 46.  core/capability/__init__.py re-exports CAPABILITY_CONTRACT_AUTHORITY.
 47.  core/capability/__init__.py re-exports CAPABILITY_RESOLVER_AUTHORITY.
 48.  core/capability/__init__.py re-exports CAPABILITY_MANAGER_LEGACY_SURFACE.
 49.  core/capability/__init__.py re-exports CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE.
 50.  core/agent/capability_registry.py defines CAPABILITY_REGISTRY_AUTHORITY.
 51.  CAPABILITY_REGISTRY_AUTHORITY value is correct.
 52.  CapabilityRegistry class exists and is importable.
 53.  get_capability_registry() callable returns CapabilityRegistry instance.
 54.  core/capability_bus.py defines CAPABILITY_BUS_AUTHORITY.
 55.  CAPABILITY_BUS_AUTHORITY value is correct.
 56.  CapabilityBus class exists and is importable.
 57.  get_capability_bus() callable returns CapabilityBus instance.
 58.  core/capability_manager.py defines CAPABILITY_MANAGER_LEGACY_SURFACE.
 59.  CAPABILITY_MANAGER_LEGACY_SURFACE contains "legacy" or "LEGACY".
 60.  core/capability_orchestrator.py defines CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE.
 61.  CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE contains "legacy" or "LEGACY".
 62.  core/capability_runtime/capability_registry_runtime.py defines
      CAPABILITY_RUNTIME_REGISTRY_AUTHORITY.
 63.  CAPABILITY_RUNTIME_REGISTRY_AUTHORITY value is correct.
 64.  core/unified/capability_contract.py defines CAPABILITY_CONTRACT_AUTHORITY.
 65.  CAPABILITY_CONTRACT_AUTHORITY value is correct.
 66.  core/unified/capability_resolver.py defines CAPABILITY_RESOLVER_AUTHORITY.
 67.  CAPABILITY_RESOLVER_AUTHORITY value is correct.
 68.  core/capability/__init__.py exports CapabilityRegistry.
 69.  core/capability/__init__.py exports CapabilityBus.
 70.  core/capability/__init__.py exports get_capability_bus.
 71.  core/capability/__init__.py exports get_capability_registry.
 72.  core/capability/__init__.py exports CapabilityContract.
 73.  core/capability/__init__.py exports get_capability_resolver.
 74.  capability_manager docstring contains "legacy" reference.
 75.  capability_orchestrator docstring contains "legacy" reference.
 76.  CapabilityBus.get_capability_bus() returns singleton.
 77.  CapabilityRegistry.get_instance() returns singleton.
 78.  CAPABILITY_REGISTRY_AUTHORITY is not equal to CAPABILITY_BUS_AUTHORITY.
 79.  CAPABILITY_RESOLVER_AUTHORITY is not equal to CAPABILITY_REGISTRY_AUTHORITY.
 80.  CAPABILITY_RUNTIME_REGISTRY_AUTHORITY is not equal to CAPABILITY_REGISTRY_AUTHORITY.
"""

from __future__ import annotations

import importlib
import sys
import warnings
from pathlib import Path
import unittest

# ── project root ─────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# =============================================================================
# Device routing tests (1-20)
# =============================================================================

class TestDeviceRoutingCanonicalPath(unittest.TestCase):
    """Tests 1-20: Device routing consolidation."""

    def test_01_device_router_module_exists(self):
        """galaxy_gateway/device_router.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "galaxy_gateway" / "device_router.py").exists()
        )

    def test_02_device_router_has_canonical_dispatch_authority(self):
        """galaxy_gateway/device_router.py defines CANONICAL_DISPATCH_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.device_router")
        self.assertTrue(
            hasattr(mod, "CANONICAL_DISPATCH_AUTHORITY"),
            "CANONICAL_DISPATCH_AUTHORITY not found in device_router",
        )

    def test_03_canonical_dispatch_authority_value(self):
        """CANONICAL_DISPATCH_AUTHORITY value is correct."""
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        self.assertIn("device_router", CANONICAL_DISPATCH_AUTHORITY)
        self.assertIn("DeviceRouter", CANONICAL_DISPATCH_AUTHORITY)

    def test_04_device_router_has_device_routing_canonical_path(self):
        """galaxy_gateway/device_router.py defines DEVICE_ROUTING_CANONICAL_PATH."""
        mod = importlib.import_module("galaxy_gateway.device_router")
        self.assertTrue(
            hasattr(mod, "DEVICE_ROUTING_CANONICAL_PATH"),
            "DEVICE_ROUTING_CANONICAL_PATH not found in device_router",
        )

    def test_05_device_routing_canonical_path_matches_dispatch_authority(self):
        """DEVICE_ROUTING_CANONICAL_PATH == CANONICAL_DISPATCH_AUTHORITY."""
        from galaxy_gateway.device_router import (
            DEVICE_ROUTING_CANONICAL_PATH,
            CANONICAL_DISPATCH_AUTHORITY,
        )
        self.assertEqual(DEVICE_ROUTING_CANONICAL_PATH, CANONICAL_DISPATCH_AUTHORITY)

    def test_06_routing_package_exists(self):
        """galaxy_gateway/routing/__init__.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "galaxy_gateway" / "routing" / "__init__.py").exists()
        )

    def test_07_routing_package_exports_health_policy_authority(self):
        """galaxy_gateway/routing/__init__.py exports DEVICE_HEALTH_POLICY_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing")
        self.assertTrue(
            hasattr(mod, "DEVICE_HEALTH_POLICY_AUTHORITY"),
        )

    def test_08_routing_package_exports_device_selection_authority(self):
        """galaxy_gateway/routing/__init__.py exports DEVICE_SELECTION_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing")
        self.assertTrue(hasattr(mod, "DEVICE_SELECTION_AUTHORITY"))

    def test_09_routing_package_exports_routing_policy_authority(self):
        """galaxy_gateway/routing/__init__.py exports ROUTING_POLICY_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing")
        self.assertTrue(hasattr(mod, "ROUTING_POLICY_AUTHORITY"))

    def test_10_routing_package_exports_dispatch_authority(self):
        """galaxy_gateway/routing/__init__.py exports DISPATCH_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing")
        self.assertTrue(hasattr(mod, "DISPATCH_AUTHORITY"))

    def test_11_routing_router_exports_orchestration_authority(self):
        """galaxy_gateway/routing/router.py exports ROUTING_ORCHESTRATION_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing.router")
        self.assertTrue(hasattr(mod, "ROUTING_ORCHESTRATION_AUTHORITY"))

    def test_12_task_router_classified_as_legacy(self):
        """galaxy_gateway/task_router.py is classified as legacy in SIDE_PATH_MODULE_REGISTRY."""
        from core.canonical_execution_chain import SIDE_PATH_MODULE_REGISTRY
        self.assertIn(
            "galaxy_gateway.task_router",
            SIDE_PATH_MODULE_REGISTRY,
            "galaxy_gateway.task_router not in SIDE_PATH_MODULE_REGISTRY",
        )
        role = SIDE_PATH_MODULE_REGISTRY["galaxy_gateway.task_router"]
        self.assertIn("legacy", role.lower(), f"task_router role should be legacy, got {role!r}")

    def test_13_dispatch_module_defines_dispatch_authority(self):
        """galaxy_gateway/routing/dispatch.py defines DISPATCH_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing.dispatch")
        self.assertTrue(hasattr(mod, "DISPATCH_AUTHORITY"))
        self.assertIn("dispatch", mod.DISPATCH_AUTHORITY.lower())

    def test_14_policy_module_defines_routing_policy_authority(self):
        """galaxy_gateway/routing/policy.py defines ROUTING_POLICY_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing.policy")
        self.assertTrue(hasattr(mod, "ROUTING_POLICY_AUTHORITY"))

    def test_15_device_selection_defines_authority(self):
        """galaxy_gateway/routing/device_selection.py defines DEVICE_SELECTION_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing.device_selection")
        self.assertTrue(hasattr(mod, "DEVICE_SELECTION_AUTHORITY"))

    def test_16_health_policy_defines_authority(self):
        """galaxy_gateway/routing/health_policy.py defines DEVICE_HEALTH_POLICY_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.routing.health_policy")
        self.assertTrue(hasattr(mod, "DEVICE_HEALTH_POLICY_AUTHORITY"))

    def test_17_canonical_chain_device_authority_matches_device_router(self):
        """DEVICE_ROUTER_DISPATCH_AUTHORITY in canonical_execution_chain matches device_router."""
        from core.canonical_execution_chain import DEVICE_ROUTER_DISPATCH_AUTHORITY
        from galaxy_gateway.device_router import CANONICAL_DISPATCH_AUTHORITY
        self.assertEqual(DEVICE_ROUTER_DISPATCH_AUTHORITY, CANONICAL_DISPATCH_AUTHORITY)

    def test_18_device_router_has_send_command_method(self):
        """DeviceRouter.send_command_to_device is callable."""
        mod = importlib.import_module("galaxy_gateway.device_router")
        self.assertTrue(hasattr(mod, "DeviceRouter"))
        router_cls = mod.DeviceRouter
        self.assertTrue(callable(getattr(router_cls, "send_command_to_device", None)))

    def test_19_routing_router_defines_routing_orchestrator(self):
        """galaxy_gateway/routing/router.py defines RoutingOrchestrator class."""
        mod = importlib.import_module("galaxy_gateway.routing.router")
        self.assertTrue(hasattr(mod, "RoutingOrchestrator"))
        self.assertTrue(isinstance(mod.RoutingOrchestrator, type))

    def test_20_routing_orchestrator_exposes_dispatch_authority_constant(self):
        """RoutingOrchestrator exposes DISPATCH_AUTHORITY class constant."""
        from galaxy_gateway.routing.router import RoutingOrchestrator
        self.assertTrue(hasattr(RoutingOrchestrator, "DISPATCH_AUTHORITY"))


# =============================================================================
# Android bridge tests (21-40)
# =============================================================================

class TestAndroidBridgeConsolidation(unittest.TestCase):
    """Tests 21-40: Android bridge consolidation."""

    def test_21_android_bridge_module_exists(self):
        """galaxy_gateway/android_bridge.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "galaxy_gateway" / "android_bridge.py").exists()
        )

    def test_22_android_bridge_defines_impl_authority(self):
        """galaxy_gateway/android_bridge.py defines ANDROID_BRIDGE_IMPL_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.android_bridge")
        self.assertTrue(
            hasattr(mod, "ANDROID_BRIDGE_IMPL_AUTHORITY"),
            "ANDROID_BRIDGE_IMPL_AUTHORITY not found in android_bridge",
        )

    def test_23_android_bridge_impl_authority_value(self):
        """ANDROID_BRIDGE_IMPL_AUTHORITY value is correct."""
        from galaxy_gateway.android_bridge import ANDROID_BRIDGE_IMPL_AUTHORITY
        self.assertIn("android_bridge", ANDROID_BRIDGE_IMPL_AUTHORITY)
        self.assertIn("AndroidBridge", ANDROID_BRIDGE_IMPL_AUTHORITY)

    def test_24_android_bridge_defines_canonical_path(self):
        """galaxy_gateway/android_bridge.py defines ANDROID_BRIDGE_CANONICAL_PATH."""
        mod = importlib.import_module("galaxy_gateway.android_bridge")
        self.assertTrue(
            hasattr(mod, "ANDROID_BRIDGE_CANONICAL_PATH"),
            "ANDROID_BRIDGE_CANONICAL_PATH not found in android_bridge",
        )

    def test_25_canonical_path_matches_impl_authority(self):
        """ANDROID_BRIDGE_CANONICAL_PATH == ANDROID_BRIDGE_IMPL_AUTHORITY."""
        from galaxy_gateway.android_bridge import (
            ANDROID_BRIDGE_CANONICAL_PATH,
            ANDROID_BRIDGE_IMPL_AUTHORITY,
        )
        self.assertEqual(ANDROID_BRIDGE_CANONICAL_PATH, ANDROID_BRIDGE_IMPL_AUTHORITY)

    def test_26_android_package_init_exists(self):
        """galaxy_gateway/android/__init__.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "galaxy_gateway" / "android" / "__init__.py").exists()
        )

    def test_27_android_package_defines_package_authority(self):
        """galaxy_gateway/android/__init__.py defines ANDROID_BRIDGE_PACKAGE_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.android")
        self.assertTrue(
            hasattr(mod, "ANDROID_BRIDGE_PACKAGE_AUTHORITY"),
            "ANDROID_BRIDGE_PACKAGE_AUTHORITY not found in galaxy_gateway.android",
        )

    def test_28_android_package_authority_value(self):
        """ANDROID_BRIDGE_PACKAGE_AUTHORITY == 'galaxy_gateway.android'."""
        from galaxy_gateway.android import ANDROID_BRIDGE_PACKAGE_AUTHORITY
        self.assertEqual(ANDROID_BRIDGE_PACKAGE_AUTHORITY, "galaxy_gateway.android")

    def test_29_android_package_exports_device_capability(self):
        """galaxy_gateway/android/__init__.py exports DeviceCapability."""
        mod = importlib.import_module("galaxy_gateway.android")
        self.assertTrue(hasattr(mod, "DeviceCapability"))

    def test_30_android_package_exports_android_device(self):
        """galaxy_gateway/android/__init__.py exports AndroidDevice."""
        mod = importlib.import_module("galaxy_gateway.android")
        self.assertTrue(hasattr(mod, "AndroidDevice"))

    def test_31_android_package_exports_message_builder(self):
        """galaxy_gateway/android/__init__.py exports MessageBuilder."""
        mod = importlib.import_module("galaxy_gateway.android")
        self.assertTrue(hasattr(mod, "MessageBuilder"))

    def test_32_android_bridge_module_in_package_exists(self):
        """galaxy_gateway/android/bridge.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "galaxy_gateway" / "android" / "bridge.py").exists()
        )

    def test_33_android_bridge_package_exports_android_bridge_class(self):
        """galaxy_gateway/android/bridge.py exports AndroidBridge."""
        mod = importlib.import_module("galaxy_gateway.android.bridge")
        self.assertTrue(
            hasattr(mod, "AndroidBridge"),
            "AndroidBridge not exported from galaxy_gateway.android.bridge",
        )

    def test_34_android_bridge_package_exports_impl_authority(self):
        """galaxy_gateway/android/bridge.py exports ANDROID_BRIDGE_IMPL_AUTHORITY."""
        mod = importlib.import_module("galaxy_gateway.android.bridge")
        self.assertTrue(hasattr(mod, "ANDROID_BRIDGE_IMPL_AUTHORITY"))

    def test_35_android_bridge_package_exports_canonical_path(self):
        """galaxy_gateway/android/bridge.py exports ANDROID_BRIDGE_CANONICAL_PATH."""
        mod = importlib.import_module("galaxy_gateway.android.bridge")
        self.assertTrue(hasattr(mod, "ANDROID_BRIDGE_CANONICAL_PATH"))

    def test_36_android_bridge_package_defines_reexport_surface(self):
        """galaxy_gateway/android/bridge.py defines ANDROID_BRIDGE_REEXPORT_SURFACE."""
        mod = importlib.import_module("galaxy_gateway.android.bridge")
        self.assertTrue(
            hasattr(mod, "ANDROID_BRIDGE_REEXPORT_SURFACE"),
            "ANDROID_BRIDGE_REEXPORT_SURFACE not found in android.bridge",
        )

    def test_37_reexport_surface_value(self):
        """ANDROID_BRIDGE_REEXPORT_SURFACE == 'galaxy_gateway.android.bridge'."""
        from galaxy_gateway.android.bridge import ANDROID_BRIDGE_REEXPORT_SURFACE
        self.assertEqual(ANDROID_BRIDGE_REEXPORT_SURFACE, "galaxy_gateway.android.bridge")

    def test_38_android_bridge_class_importable(self):
        """AndroidBridge class exists and is importable from android_bridge."""
        from galaxy_gateway.android_bridge import AndroidBridge
        self.assertTrue(isinstance(AndroidBridge, type))

    def test_39_android_bridge_has_handle_message(self):
        """AndroidBridge has handle_message method."""
        from galaxy_gateway.android_bridge import AndroidBridge
        self.assertTrue(callable(getattr(AndroidBridge, "handle_message", None)))

    def test_40_android_bridge_has_disconnect_device(self):
        """AndroidBridge has disconnect_device method."""
        from galaxy_gateway.android_bridge import AndroidBridge
        self.assertTrue(callable(getattr(AndroidBridge, "disconnect_device", None)))


# =============================================================================
# Capability subsystem tests (41-80)
# =============================================================================

class TestCapabilitySubsystemConsolidation(unittest.TestCase):
    """Tests 41-80: Capability subsystem separation and consolidation."""

    def test_41_capability_package_init_exists(self):
        """core/capability/__init__.py exists."""
        self.assertTrue(
            (PROJECT_ROOT / "core" / "capability" / "__init__.py").exists()
        )

    def test_42_capability_package_defines_package_authority(self):
        """core/capability/__init__.py defines CAPABILITY_PACKAGE_AUTHORITY."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_PACKAGE_AUTHORITY"),
            "CAPABILITY_PACKAGE_AUTHORITY not found in core.capability",
        )

    def test_43_capability_package_authority_value(self):
        """CAPABILITY_PACKAGE_AUTHORITY == 'core.capability'."""
        from core.capability import CAPABILITY_PACKAGE_AUTHORITY
        self.assertEqual(CAPABILITY_PACKAGE_AUTHORITY, "core.capability")

    def test_44_capability_package_exports_registry_authority(self):
        """core/capability/__init__.py re-exports CAPABILITY_REGISTRY_AUTHORITY."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_REGISTRY_AUTHORITY"))

    def test_45_capability_package_exports_bus_authority(self):
        """core/capability/__init__.py re-exports CAPABILITY_BUS_AUTHORITY."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_BUS_AUTHORITY"))

    def test_46_capability_package_exports_contract_authority(self):
        """core/capability/__init__.py re-exports CAPABILITY_CONTRACT_AUTHORITY."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_CONTRACT_AUTHORITY"))

    def test_47_capability_package_exports_resolver_authority(self):
        """core/capability/__init__.py re-exports CAPABILITY_RESOLVER_AUTHORITY."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_RESOLVER_AUTHORITY"))

    def test_48_capability_package_exports_manager_legacy_surface(self):
        """core/capability/__init__.py re-exports CAPABILITY_MANAGER_LEGACY_SURFACE."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_MANAGER_LEGACY_SURFACE"))

    def test_49_capability_package_exports_orchestrator_legacy_surface(self):
        """core/capability/__init__.py re-exports CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE."""
        mod = importlib.import_module("core.capability")
        self.assertTrue(hasattr(mod, "CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE"))

    def test_50_capability_registry_defines_authority(self):
        """core/agent/capability_registry.py defines CAPABILITY_REGISTRY_AUTHORITY."""
        mod = importlib.import_module("core.agent.capability_registry")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_REGISTRY_AUTHORITY"),
            "CAPABILITY_REGISTRY_AUTHORITY not found in core.agent.capability_registry",
        )

    def test_51_capability_registry_authority_value(self):
        """CAPABILITY_REGISTRY_AUTHORITY value is correct."""
        from core.agent.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        self.assertIn("capability_registry", CAPABILITY_REGISTRY_AUTHORITY)
        self.assertIn("CapabilityRegistry", CAPABILITY_REGISTRY_AUTHORITY)

    def test_52_capability_registry_class_exists(self):
        """CapabilityRegistry class exists and is importable."""
        from core.agent.capability_registry import CapabilityRegistry
        self.assertTrue(isinstance(CapabilityRegistry, type))

    def test_53_get_capability_registry_returns_instance(self):
        """get_capability_registry() callable returns CapabilityRegistry instance."""
        from core.agent.capability_registry import get_capability_registry, CapabilityRegistry
        reg = get_capability_registry()
        self.assertIsInstance(reg, CapabilityRegistry)

    def test_54_capability_bus_defines_authority(self):
        """core/capability_bus.py defines CAPABILITY_BUS_AUTHORITY."""
        mod = importlib.import_module("core.capability_bus")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_BUS_AUTHORITY"),
            "CAPABILITY_BUS_AUTHORITY not found in core.capability_bus",
        )

    def test_55_capability_bus_authority_value(self):
        """CAPABILITY_BUS_AUTHORITY value is correct."""
        from core.capability_bus import CAPABILITY_BUS_AUTHORITY
        self.assertIn("capability_bus", CAPABILITY_BUS_AUTHORITY)
        self.assertIn("CapabilityBus", CAPABILITY_BUS_AUTHORITY)

    def test_56_capability_bus_class_exists(self):
        """CapabilityBus class exists and is importable."""
        from core.capability_bus import CapabilityBus
        self.assertTrue(isinstance(CapabilityBus, type))

    def test_57_get_capability_bus_returns_instance(self):
        """get_capability_bus() callable returns CapabilityBus instance."""
        from core.capability_bus import get_capability_bus, CapabilityBus
        bus = get_capability_bus()
        self.assertIsInstance(bus, CapabilityBus)

    def test_58_capability_manager_defines_legacy_surface(self):
        """core/capability_manager.py defines CAPABILITY_MANAGER_LEGACY_SURFACE."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("core.capability_manager")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_MANAGER_LEGACY_SURFACE"),
            "CAPABILITY_MANAGER_LEGACY_SURFACE not found in core.capability_manager",
        )

    def test_59_capability_manager_legacy_surface_contains_legacy(self):
        """CAPABILITY_MANAGER_LEGACY_SURFACE contains 'legacy' or 'LEGACY'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from core.capability_manager import CAPABILITY_MANAGER_LEGACY_SURFACE
        self.assertIn(
            "legacy",
            CAPABILITY_MANAGER_LEGACY_SURFACE.lower(),
            f"Expected 'legacy' in {CAPABILITY_MANAGER_LEGACY_SURFACE!r}",
        )

    def test_60_capability_orchestrator_defines_legacy_surface(self):
        """core/capability_orchestrator.py defines CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("core.capability_orchestrator")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE"),
            "CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE not found in core.capability_orchestrator",
        )

    def test_61_capability_orchestrator_legacy_surface_contains_legacy(self):
        """CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE contains 'legacy' or 'LEGACY'."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from core.capability_orchestrator import CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE
        self.assertIn(
            "legacy",
            CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE.lower(),
            f"Expected 'legacy' in {CAPABILITY_ORCHESTRATOR_LEGACY_SURFACE!r}",
        )

    def test_62_capability_runtime_registry_defines_authority(self):
        """core/capability_runtime/capability_registry_runtime.py defines CAPABILITY_RUNTIME_REGISTRY_AUTHORITY."""
        mod = importlib.import_module(
            "core.capability_runtime.capability_registry_runtime"
        )
        self.assertTrue(
            hasattr(mod, "CAPABILITY_RUNTIME_REGISTRY_AUTHORITY"),
            "CAPABILITY_RUNTIME_REGISTRY_AUTHORITY not found",
        )

    def test_63_capability_runtime_registry_authority_value(self):
        """CAPABILITY_RUNTIME_REGISTRY_AUTHORITY value is correct."""
        from core.capability_runtime.capability_registry_runtime import (
            CAPABILITY_RUNTIME_REGISTRY_AUTHORITY,
        )
        self.assertIn("capability_runtime", CAPABILITY_RUNTIME_REGISTRY_AUTHORITY)
        self.assertIn("CapabilityRuntimeRegistry", CAPABILITY_RUNTIME_REGISTRY_AUTHORITY)

    def test_64_capability_contract_defines_authority(self):
        """core/unified/capability_contract.py defines CAPABILITY_CONTRACT_AUTHORITY."""
        mod = importlib.import_module("core.unified.capability_contract")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_CONTRACT_AUTHORITY"),
            "CAPABILITY_CONTRACT_AUTHORITY not found in core.unified.capability_contract",
        )

    def test_65_capability_contract_authority_value(self):
        """CAPABILITY_CONTRACT_AUTHORITY value is correct."""
        from core.unified.capability_contract import CAPABILITY_CONTRACT_AUTHORITY
        self.assertIn("capability_contract", CAPABILITY_CONTRACT_AUTHORITY)
        self.assertIn("CapabilityContract", CAPABILITY_CONTRACT_AUTHORITY)

    def test_66_capability_resolver_defines_authority(self):
        """core/unified/capability_resolver.py defines CAPABILITY_RESOLVER_AUTHORITY."""
        mod = importlib.import_module("core.unified.capability_resolver")
        self.assertTrue(
            hasattr(mod, "CAPABILITY_RESOLVER_AUTHORITY"),
            "CAPABILITY_RESOLVER_AUTHORITY not found in core.unified.capability_resolver",
        )

    def test_67_capability_resolver_authority_value(self):
        """CAPABILITY_RESOLVER_AUTHORITY value is correct."""
        from core.unified.capability_resolver import CAPABILITY_RESOLVER_AUTHORITY
        self.assertIn("capability_resolver", CAPABILITY_RESOLVER_AUTHORITY)
        self.assertIn("CapabilityResolver", CAPABILITY_RESOLVER_AUTHORITY)

    def test_68_capability_package_exports_capability_registry_class(self):
        """core/capability/__init__.py exports CapabilityRegistry."""
        from core.capability import CapabilityRegistry
        self.assertTrue(isinstance(CapabilityRegistry, type))

    def test_69_capability_package_exports_capability_bus_class(self):
        """core/capability/__init__.py exports CapabilityBus."""
        from core.capability import CapabilityBus
        self.assertTrue(isinstance(CapabilityBus, type))

    def test_70_capability_package_exports_get_capability_bus(self):
        """core/capability/__init__.py exports get_capability_bus."""
        from core.capability import get_capability_bus
        self.assertTrue(callable(get_capability_bus))

    def test_71_capability_package_exports_get_capability_registry(self):
        """core/capability/__init__.py exports get_capability_registry."""
        from core.capability import get_capability_registry
        self.assertTrue(callable(get_capability_registry))

    def test_72_capability_package_exports_capability_contract_class(self):
        """core/capability/__init__.py exports CapabilityContract."""
        from core.capability import CapabilityContract
        self.assertTrue(isinstance(CapabilityContract, type))

    def test_73_capability_package_exports_get_capability_resolver(self):
        """core/capability/__init__.py exports get_capability_resolver."""
        from core.capability import get_capability_resolver
        self.assertTrue(callable(get_capability_resolver))

    def test_74_capability_manager_module_has_legacy_docstring(self):
        """capability_manager docstring contains 'legacy' reference."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("core.capability_manager")
        doc = (mod.__doc__ or "").lower()
        self.assertIn("legacy", doc, "capability_manager docstring should contain 'legacy'")

    def test_75_capability_orchestrator_module_has_legacy_docstring(self):
        """capability_orchestrator docstring contains 'legacy' reference."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            mod = importlib.import_module("core.capability_orchestrator")
        doc = (mod.__doc__ or "").lower()
        self.assertIn("legacy", doc, "capability_orchestrator docstring should contain 'legacy'")

    def test_76_get_capability_bus_singleton(self):
        """CapabilityBus.get_capability_bus() returns singleton."""
        from core.capability_bus import get_capability_bus
        bus1 = get_capability_bus()
        bus2 = get_capability_bus()
        self.assertIs(bus1, bus2)

    def test_77_get_capability_registry_singleton(self):
        """CapabilityRegistry.get_instance() returns singleton."""
        from core.agent.capability_registry import CapabilityRegistry
        reg1 = CapabilityRegistry.get_instance()
        reg2 = CapabilityRegistry.get_instance()
        self.assertIs(reg1, reg2)

    def test_78_registry_authority_not_equal_to_bus_authority(self):
        """CAPABILITY_REGISTRY_AUTHORITY is not equal to CAPABILITY_BUS_AUTHORITY."""
        from core.agent.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        from core.capability_bus import CAPABILITY_BUS_AUTHORITY
        self.assertNotEqual(
            CAPABILITY_REGISTRY_AUTHORITY,
            CAPABILITY_BUS_AUTHORITY,
            "Registry and Bus must have distinct authority sentinels",
        )

    def test_79_resolver_authority_not_equal_to_registry_authority(self):
        """CAPABILITY_RESOLVER_AUTHORITY is not equal to CAPABILITY_REGISTRY_AUTHORITY."""
        from core.unified.capability_resolver import CAPABILITY_RESOLVER_AUTHORITY
        from core.agent.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        self.assertNotEqual(CAPABILITY_RESOLVER_AUTHORITY, CAPABILITY_REGISTRY_AUTHORITY)

    def test_80_runtime_registry_authority_not_equal_to_registry_authority(self):
        """CAPABILITY_RUNTIME_REGISTRY_AUTHORITY is not equal to CAPABILITY_REGISTRY_AUTHORITY."""
        from core.capability_runtime.capability_registry_runtime import (
            CAPABILITY_RUNTIME_REGISTRY_AUTHORITY,
        )
        from core.agent.capability_registry import CAPABILITY_REGISTRY_AUTHORITY
        self.assertNotEqual(
            CAPABILITY_RUNTIME_REGISTRY_AUTHORITY,
            CAPABILITY_REGISTRY_AUTHORITY,
        )


if __name__ == "__main__":
    unittest.main()
