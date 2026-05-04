"""
tests/test_routing_with_exec_mode.py
=====================================
Unit tests for exec_mode-aware device selection in DeviceRouter._select_devices.

Covers:
  - Prefer device whose capability matches exec_mode=local
  - Prefer device whose capability matches exec_mode=remote
  - exec_mode=both does not exclude any device
  - Legacy device (no capability_report yet) is included as fallback
  - Device with capabilities that don't match requested action is excluded
    (but legacy devices without any caps are kept)
  - Backward compat: analysis without exec_mode key works as before
"""

import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from galaxy_gateway.capability_registry import GatewayCapabilityRegistry
from galaxy_gateway.device_router import Device, DeviceRouter
from core.device_types import DeviceType

# ──────────────────────────────────────────────────────────────────────────────
# Test helpers
# ──────────────────────────────────────────────────────────────────────────────


def _make_device(device_id: str, device_type: str = "android_phone") -> Device:
    """Create a minimal Device whose status is always 'online'."""
    device = Device(device_id=device_id, device_type=device_type, capabilities=[])
    device.status = "online"
    return device


def _make_router_with_devices(devices: List[Device]) -> DeviceRouter:
    """Build a DeviceRouter pre-populated with the given devices."""
    router = DeviceRouter()
    for d in devices:
        router.devices[d.device_id] = d
    return router


def _make_registry(*entries) -> GatewayCapabilityRegistry:
    """Create a fresh registry and populate it with (device_id, action, schema_dict) tuples."""
    reg = GatewayCapabilityRegistry()
    for device_id, action, schema_dict in entries:
        reg.upsert(device_id, action, schema_dict)
    return reg


# ──────────────────────────────────────────────────────────────────────────────
# Base analysis fixture
# ──────────────────────────────────────────────────────────────────────────────


def _analysis(
    device_type=DeviceType.ANDROID,
    actions=None,
    exec_mode: Optional[str] = None,
    requires_cross_device: bool = False,
) -> Dict[str, Any]:
    return {
        "target_device_type": device_type,
        "task_type": "ui_automation",
        "actions": actions or [],
        "exec_mode": exec_mode,
        "requires_cross_device": requires_cross_device,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Routing tests
# ──────────────────────────────────────────────────────────────────────────────


class TestExecModeRouting(unittest.TestCase):
    """DeviceRouter._select_devices respects exec_mode from capability registry."""

    # ── exec_mode=local ───────────────────────────────────────────────────────

    def test_local_exec_mode_selects_local_capable_device(self):
        """When exec_mode=local, prefer device with exec_mode=local for the action."""
        dev_local = _make_device("dev-local")
        dev_remote = _make_device("dev-remote")
        router = _make_router_with_devices([dev_local, dev_remote])

        registry = _make_registry(
            ("dev-local", "tap", {"exec_mode": "local"}),
            ("dev-remote", "tap", {"exec_mode": "remote"}),
        )

        analysis = _analysis(actions=["tap"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-local")

    def test_local_exec_mode_includes_both_capable_device(self):
        """exec_mode=local should also select devices advertising exec_mode=both."""
        dev_both = _make_device("dev-both")
        dev_remote = _make_device("dev-remote")
        router = _make_router_with_devices([dev_both, dev_remote])

        registry = _make_registry(
            ("dev-both", "screenshot", {"exec_mode": "both"}),
            ("dev-remote", "screenshot", {"exec_mode": "remote"}),
        )

        analysis = _analysis(actions=["screenshot"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-both")

    # ── exec_mode=remote ──────────────────────────────────────────────────────

    def test_remote_exec_mode_selects_remote_capable_device(self):
        """When exec_mode=remote, prefer device with exec_mode=remote for the action."""
        dev_local = _make_device("dev-local")
        dev_remote = _make_device("dev-remote")
        router = _make_router_with_devices([dev_local, dev_remote])

        registry = _make_registry(
            ("dev-local", "swipe", {"exec_mode": "local"}),
            ("dev-remote", "swipe", {"exec_mode": "remote"}),
        )

        analysis = _analysis(actions=["swipe"], exec_mode="remote")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-remote")

    # ── exec_mode=both ────────────────────────────────────────────────────────

    def test_exec_mode_both_does_not_filter_devices(self):
        """exec_mode=both must not exclude any device."""
        dev1 = _make_device("dev-1")
        dev2 = _make_device("dev-2")
        router = _make_router_with_devices([dev1, dev2])

        registry = _make_registry(
            ("dev-1", "tap", {"exec_mode": "local"}),
            ("dev-2", "tap", {"exec_mode": "remote"}),
        )

        analysis = _analysis(actions=["tap"], exec_mode="both")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        # Both devices are valid candidates; router returns the first (deterministic)
        self.assertEqual(len(selected), 1)
        # Verify the selected device IS one of the two valid candidates
        self.assertIn(selected[0].device_id, {"dev-1", "dev-2"})

    # ── Legacy clients (no capability_report) ─────────────────────────────────

    def test_legacy_device_without_any_capabilities_is_kept(self):
        """Device that has never reported capabilities should be treated as legacy fallback."""
        dev_legacy = _make_device("dev-legacy")
        router = _make_router_with_devices([dev_legacy])

        # Registry is empty (device never sent capability_report)
        registry = _make_registry()

        analysis = _analysis(actions=["tap"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        # Legacy device should be kept
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-legacy")

    def test_device_with_capabilities_but_wrong_action_excluded(self):
        """Device that has reported capabilities but not the requested action is excluded."""
        dev_has_caps = _make_device("dev-has-caps")
        dev_legacy = _make_device("dev-legacy")
        router = _make_router_with_devices([dev_has_caps, dev_legacy])

        # dev-has-caps has caps, but not "tap"
        registry = _make_registry(
            ("dev-has-caps", "screenshot", {"exec_mode": "local"}),
        )
        # dev-legacy has no caps at all → fallback

        analysis = _analysis(actions=["tap"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        # dev-legacy (no caps) should be the fallback
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-legacy")

    # ── Backward compatibility: no exec_mode in analysis ──────────────────────

    def test_no_exec_mode_in_analysis_selects_first_online_device(self):
        """analysis without exec_mode key should use original logic."""
        dev1 = _make_device("dev-1")
        dev2 = _make_device("dev-2")
        router = _make_router_with_devices([dev1, dev2])

        registry = _make_registry()

        analysis = _analysis(actions=[], exec_mode=None)
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        self.assertEqual(len(selected), 1)

    def test_registry_unavailable_falls_back_gracefully(self):
        """If GatewayCapabilityRegistry raises, routing falls back to original logic."""
        dev1 = _make_device("dev-1")
        router = _make_router_with_devices([dev1])

        analysis = _analysis(actions=["tap"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                side_effect=RuntimeError("registry unavailable"),
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            # Should not raise; should still return the device
            selected = router._select_devices(analysis)

        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].device_id, "dev-1")

    # ── No matching devices ───────────────────────────────────────────────────

    def test_no_devices_registered_returns_empty(self):
        router = DeviceRouter()  # no devices
        registry = _make_registry()
        analysis = _analysis(actions=["tap"], exec_mode="local")
        with (
            patch(
                "galaxy_gateway.routing.device_selection.get_gateway_capability_projection_view",
                return_value=registry,
            ),
            patch(
                "galaxy_gateway.autonomous_filter.filter_autonomous_devices",
                side_effect=lambda devs, **kw: [d for d in devs if d.status == "online"],
            ),
        ):
            selected = router._select_devices(analysis)

        self.assertEqual(selected, [])


# ──────────────────────────────────────────────────────────────────────────────
# Registry cleanup on device disconnect
# ──────────────────────────────────────────────────────────────────────────────


class TestUnregisterPurgesCapabilities(unittest.TestCase):
    """DeviceRouter.unregister_device purges capabilities from registry."""

    def test_unregister_purges_gateway_capabilities(self):
        router = _make_router_with_devices([_make_device("dev-1")])

        with patch(
            "galaxy_gateway.device_router.purge_gateway_capabilities_for_device",
            return_value=2,
        ):
            result = router.unregister_device("dev-1")

        self.assertTrue(result)

    def test_unregister_nonexistent_device_returns_false(self):
        router = DeviceRouter()
        with patch(
            "galaxy_gateway.device_router.purge_gateway_capabilities_for_device",
            return_value=0,
        ):
            result = router.unregister_device("ghost-device")
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
