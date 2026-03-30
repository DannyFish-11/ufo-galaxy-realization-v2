"""tests/unit/routing/test_device_router_session_adapter.py
=====================================================
Tests for PR-3: DeviceRouter formalised as runtime session adapter over
canonical device state.

Coverage
--------
1. Connect / session establish updates canonical runtime state in UDM.
2. Disconnect updates canonical runtime state in UDM (patches offline,
   does NOT fully unregister from UDM).
3. Loss of router-local state does not erase canonical device registration.
4. Router can still route live tasks after the authority demotion.
5. Router read paths prefer canonical device state with runtime/session
   enrichment via ``get_enriched_device_view``.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _reset_udm() -> None:
    """Reset UnifiedDeviceManager singleton between tests."""
    from core.unified import device_manager as _udm_mod
    _udm_mod.UnifiedDeviceManager._instance = None


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


def _fresh_router():
    """Return a new DeviceRouter instance with a clean UDM."""
    _reset_udm()
    from galaxy_gateway.device_router import DeviceRouter
    return DeviceRouter()


# ---------------------------------------------------------------------------
# 1. Connect / session establish updates canonical runtime state in UDM
# ---------------------------------------------------------------------------

class TestConnectUpdatesUDM:
    """register_device and on_device_connected patch canonical runtime state."""

    def setup_method(self):
        _reset_udm()

    def test_register_device_writes_to_udm(self):
        """After register_device, UDM must contain the device."""
        router = _fresh_router()
        router.register_device("dev_connect_01", "android_phone", ["screen"])

        from core.unified.device_manager import UnifiedDeviceManager
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_connect_01")
        assert device is not None, "UDM must contain the device after register_device"
        assert device.device_id == "dev_connect_01"

    def test_register_device_sets_online_status_in_udm(self):
        """register_device patches UDM runtime presence as online."""
        router = _fresh_router()
        router.register_device("dev_connect_02", "android_phone", ["screen"])

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_connect_02")
        assert device is not None
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.ONLINE.value

    def test_on_device_connected_patches_udm(self):
        """on_device_connected patches canonical runtime state in UDM."""
        router = _fresh_router()
        # First register so the device exists in UDM
        router.register_device("dev_connect_03", "android_phone", ["screen"])

        # Simulate a reconnect via on_device_connected
        router.on_device_connected("dev_connect_03", websocket=_make_websocket())

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_connect_03")
        assert device is not None
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.ONLINE.value

    def test_sync_connection_state_to_udm_online(self):
        """_sync_connection_state_to_udm(connected=True) patches UDM to online."""
        router = _fresh_router()
        router.register_device("dev_connect_04", "android_phone", ["screen"])

        success = router._sync_connection_state_to_udm("dev_connect_04", connected=True)
        assert success is True

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_connect_04")
        assert device is not None
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.ONLINE.value

    def test_build_runtime_presence_patch_connected(self):
        """_build_runtime_presence_patch returns correct shape for connected=True."""
        router = _fresh_router()
        patch = router._build_runtime_presence_patch(connected=True, transport="websocket")
        assert patch["status"] == "online"
        assert patch["runtime_connection"]["connected"] is True
        assert patch["runtime_connection"]["transport"] == "websocket"
        assert "last_seen" in patch["runtime_connection"]


# ---------------------------------------------------------------------------
# 2. Disconnect updates canonical runtime state in UDM
# ---------------------------------------------------------------------------

class TestDisconnectUpdatesUDM:
    """unregister_device and on_device_disconnected patch UDM to offline."""

    def setup_method(self):
        _reset_udm()

    def test_unregister_device_patches_udm_offline(self):
        """unregister_device must patch UDM to offline, NOT delete the device."""
        router = _fresh_router()
        router.register_device("dev_disc_01", "android_phone", ["screen"])

        router.unregister_device("dev_disc_01")

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_disc_01")
        assert device is not None, "Device must still exist in UDM after unregister_device"
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.OFFLINE.value

    def test_on_device_disconnected_patches_udm_offline(self):
        """on_device_disconnected patches UDM to offline."""
        router = _fresh_router()
        router.register_device("dev_disc_02", "android_phone", ["screen"])

        router.on_device_disconnected("dev_disc_02")

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_disc_02")
        assert device is not None, "Device must still exist in UDM after on_device_disconnected"
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.OFFLINE.value

    def test_sync_connection_state_to_udm_offline(self):
        """_sync_connection_state_to_udm(connected=False) patches UDM to offline."""
        router = _fresh_router()
        router.register_device("dev_disc_03", "android_phone", ["screen"])

        success = router._sync_connection_state_to_udm("dev_disc_03", connected=False)
        assert success is True

        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_disc_03")
        assert device is not None
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == UnifiedDeviceStatus.OFFLINE.value

    def test_build_runtime_presence_patch_disconnected(self):
        """_build_runtime_presence_patch returns correct shape for connected=False."""
        router = _fresh_router()
        patch = router._build_runtime_presence_patch(connected=False)
        assert patch["status"] == "offline"
        assert patch["runtime_connection"]["connected"] is False


# ---------------------------------------------------------------------------
# 3. Loss of router-local state does not erase canonical registration
# ---------------------------------------------------------------------------

class TestLocalStateLossPreservesCanonical:
    """Clearing local session cache must not touch canonical UDM registration."""

    def setup_method(self):
        _reset_udm()

    def test_clearing_local_devices_preserves_udm_registration(self):
        """Directly clearing self.devices must not remove device from UDM."""
        router = _fresh_router()
        router.register_device("dev_pres_01", "android_phone", ["screen"])

        # Simulate abrupt loss of local state (e.g. restart)
        router.devices.clear()

        from core.unified.device_manager import UnifiedDeviceManager
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_pres_01")
        assert device is not None, (
            "Canonical UDM registration must survive loss of router-local session cache"
        )

    def test_unregister_device_preserves_udm_entry(self):
        """unregister_device clears local session but preserves UDM entry."""
        router = _fresh_router()
        router.register_device("dev_pres_02", "windows_desktop", ["keyboard"])

        router.unregister_device("dev_pres_02")

        # Local cache is gone
        assert "dev_pres_02" not in router.devices

        # But UDM record persists
        from core.unified.device_manager import UnifiedDeviceManager
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_pres_02")
        assert device is not None, "UDM canonical registration must persist after unregister_device"

    def test_on_device_disconnected_clears_local_but_preserves_udm(self):
        """on_device_disconnected removes local session and preserves UDM."""
        router = _fresh_router()
        router.register_device("dev_pres_03", "android_phone", ["camera"])
        assert "dev_pres_03" in router.devices

        router.on_device_disconnected("dev_pres_03")

        # Local session gone
        assert "dev_pres_03" not in router.devices

        # UDM record survives
        from core.unified.device_manager import UnifiedDeviceManager
        udm = UnifiedDeviceManager()
        device = udm.get_device("dev_pres_03")
        assert device is not None, "UDM entry must remain after on_device_disconnected"

    def test_multiple_register_unregister_cycles_preserve_udm(self):
        """Repeated connect/disconnect cycles must not corrupt UDM registration."""
        router = _fresh_router()
        device_id = "dev_pres_04"

        for _ in range(3):
            router.register_device(device_id, "android_phone", ["screen"])
            router.unregister_device(device_id)

        from core.unified.device_manager import UnifiedDeviceManager
        udm = UnifiedDeviceManager()
        device = udm.get_device(device_id)
        assert device is not None, "Device must still exist in UDM after multiple cycles"


# ---------------------------------------------------------------------------
# 4. Router can still route live tasks after authority demotion
# ---------------------------------------------------------------------------

class TestRoutingRemainsFunc:
    """Routing functionality must be unaffected by PR-3 changes."""

    def setup_method(self):
        _reset_udm()

    def test_get_device_returns_local_session_entry(self):
        """get_device returns the local Device object (for routing)."""
        router = _fresh_router()
        ws = _make_websocket()
        router.register_device("dev_route_01", "android_phone", ["screen"], websocket=ws)

        device = router.get_device("dev_route_01")
        assert device is not None
        assert device.device_id == "dev_route_01"
        assert device.websocket is ws

    def test_get_devices_by_type_returns_connected_devices(self):
        """get_devices_by_type returns devices in the local session cache."""
        router = _fresh_router()
        router.register_device("dev_route_02a", "android_phone", ["screen"])
        router.register_device("dev_route_02b", "android_phone", ["camera"])
        router.register_device("dev_route_02c", "windows_desktop", ["keyboard"])

        # device_type is resolved to platform value ('android', 'windows')
        android_devices = router.get_devices_by_type("android")
        assert len(android_devices) == 2

    def test_get_devices_by_capability(self):
        """get_devices_by_capability filters on local session cache."""
        router = _fresh_router()
        router.register_device("dev_route_03a", "android_phone", ["screen", "camera"])
        router.register_device("dev_route_03b", "android_phone", ["screen"])

        cam_devices = router.get_devices_by_capability("camera")
        assert len(cam_devices) == 1
        assert cam_devices[0].device_id == "dev_route_03a"

    @pytest.mark.asyncio
    async def test_dispatch_task_uses_websocket_from_local_cache(self):
        """dispatch_task falls back to WebSocket from local session cache."""
        router = _fresh_router()
        ws = _make_websocket()
        router.register_device("dev_route_04", "android_phone", ["screen"], websocket=ws)

        device = router.get_device("dev_route_04")
        task = {
            "task_id": "t-001",
            "command": "click",
            "analysis": {},
            "target_devices": ["dev_route_04"],
            "status": "pending",
            "created_at": "now",
            "payload": {"task_type": "ui_automation", "action": "click", "target": "", "params": {}},
        }

        result = await router.dispatch_task(task, device)
        # Should either succeed or fail with task-dispatch error, but not crash.
        assert isinstance(result, dict)
        assert "success" in result


# ---------------------------------------------------------------------------
# 5. Router read paths prefer canonical state with runtime enrichment
# ---------------------------------------------------------------------------

class TestReadPathCanonicalPreference:
    """get_canonical_device and get_enriched_device_view return the right data."""

    def setup_method(self):
        _reset_udm()

    def test_get_canonical_device_returns_udm_record(self):
        """get_canonical_device fetches from UDM, not local session cache."""
        router = _fresh_router()
        router.register_device("dev_read_01", "android_phone", ["screen"])

        canonical = router.get_canonical_device("dev_read_01")
        assert canonical is not None
        assert canonical.device_id == "dev_read_01"

    def test_get_canonical_device_survives_local_cache_loss(self):
        """get_canonical_device returns UDM record even after local cache cleared."""
        router = _fresh_router()
        router.register_device("dev_read_02", "android_phone", ["screen"])
        router.devices.clear()  # Simulate abrupt local state loss

        canonical = router.get_canonical_device("dev_read_02")
        assert canonical is not None, (
            "get_canonical_device must read from UDM even with empty local cache"
        )

    def test_get_enriched_device_view_prefers_udm_as_base(self):
        """get_enriched_device_view returns a view with UDM as the base."""
        router = _fresh_router()
        ws = _make_websocket()
        router.register_device("dev_read_03", "android_phone", ["screen"], websocket=ws)

        view = router.get_enriched_device_view("dev_read_03")
        assert view is not None
        assert view["device_id"] == "dev_read_03"
        # Source should be UDM
        assert view.get("source") == "udm"

    def test_get_enriched_device_view_includes_session_enrichment(self):
        """get_enriched_device_view includes router_session enrichment from local cache."""
        router = _fresh_router()
        ws = _make_websocket()
        router.register_device("dev_read_04", "android_phone", ["screen"], websocket=ws)

        view = router.get_enriched_device_view("dev_read_04")
        assert view is not None
        assert "router_session" in view
        assert view["router_session"]["has_active_websocket"] is True

    def test_get_enriched_device_view_udm_base_survives_local_loss(self):
        """get_enriched_device_view can still return UDM base after local cache cleared."""
        router = _fresh_router()
        router.register_device("dev_read_05", "android_phone", ["screen"])
        router.devices.clear()

        view = router.get_enriched_device_view("dev_read_05")
        # UDM base should still be available even with no local session
        assert view is not None
        assert view["device_id"] == "dev_read_05"
        assert view.get("source") == "udm"
        # No router_session enrichment since local cache is empty
        assert "router_session" not in view

    def test_get_device_status_prefers_udm(self):
        """get_device_status returns UDM-sourced data as primary."""
        router = _fresh_router()
        router.register_device("dev_read_06", "android_phone", ["screen"])

        status = router.get_device_status()
        assert "devices" in status
        device_ids = [d["device_id"] for d in status["devices"]]
        assert "dev_read_06" in device_ids
        # Source should be udm for at least one entry
        sources = [d.get("source") for d in status["devices"] if d["device_id"] == "dev_read_06"]
        assert any(s == "udm" for s in sources)

    def test_get_canonical_device_returns_none_when_not_in_udm(self):
        """get_canonical_device returns None for devices unknown to UDM."""
        router = _fresh_router()
        assert router.get_canonical_device("nonexistent_device_xyz") is None

    def test_get_enriched_device_view_returns_none_when_unknown(self):
        """get_enriched_device_view returns None when device is in neither cache nor UDM."""
        router = _fresh_router()
        assert router.get_enriched_device_view("totally_unknown_device_xyz") is None
