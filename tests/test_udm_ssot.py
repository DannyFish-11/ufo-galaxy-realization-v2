"""
tests/test_udm_ssot.py
======================

PR-2: Verify UnifiedDeviceManager (UDM) is the single source of truth (SSOT)
for device state across all registration/management paths.

Covers:
  A  DeviceRegistry writes to UDM first on register/unregister/heartbeat/update_status
  B  DeviceRegistry.get() and list_devices() prefer UDM data
  C  DeviceRouter writes to UDM on register_device/unregister_device
  D  DeviceRouter.get_device_status() reads from UDM (not local self.devices)
  E  DeviceAgentManager is strict: rolls back local agent when UDM write fails
  F  core/routes/devices.py heartbeat/delete check UDM for device existence
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_udm():
    """Reset UDM singleton for test isolation."""
    from core.unified import device_manager as _mod
    _mod.UnifiedDeviceManager._instance = None


def _fresh_udm():
    _reset_udm()
    from core.unified.device_manager import get_unified_device_manager
    return get_unified_device_manager()


# ===========================================================================
# A  DeviceRegistry writes to UDM first
# ===========================================================================

class TestDeviceRegistryWritesToUDM:
    """DeviceRegistry.register / unregister / heartbeat / update_status write to UDM."""

    def test_register_writes_to_udm(self):
        udm = _fresh_udm()
        from core.device_registry import DeviceRegistry
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        asyncio.get_event_loop().run_until_complete(
            reg.register(device_id="dr_test_001", device_type="android", name="Test")
        )

        assert udm.get_device("dr_test_001") is not None, "UDM must contain the registered device"

    def test_unregister_writes_to_udm(self):
        udm = _fresh_udm()
        from core.device_registry import DeviceRegistry
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        asyncio.get_event_loop().run_until_complete(
            reg.register(device_id="dr_test_002", device_type="android", name="Test")
        )
        asyncio.get_event_loop().run_until_complete(reg.unregister("dr_test_002"))

        assert udm.get_device("dr_test_002") is None, "UDM must NOT contain the unregistered device"

    def test_heartbeat_writes_to_udm(self):
        udm = _fresh_udm()
        from core.device_registry import DeviceRegistry
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        asyncio.get_event_loop().run_until_complete(
            reg.register(device_id="dr_test_003", device_type="android", name="Test")
        )
        asyncio.get_event_loop().run_until_complete(reg.heartbeat("dr_test_003"))

        dev = udm.get_device("dr_test_003")
        assert dev is not None
        assert dev.last_heartbeat is not None

    def test_update_status_writes_to_udm(self):
        udm = _fresh_udm()
        from core.device_registry import DeviceRegistry, DeviceStatus
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        asyncio.get_event_loop().run_until_complete(
            reg.register(device_id="dr_test_004", device_type="android", name="Test")
        )
        asyncio.get_event_loop().run_until_complete(
            reg.update_status("dr_test_004", status=DeviceStatus.OFFLINE)
        )

        dev = udm.get_device("dr_test_004")
        assert dev is not None
        status_val = dev.status.value if hasattr(dev.status, "value") else str(dev.status)
        assert status_val == "offline", f"Expected 'offline', got {status_val!r}"


# ===========================================================================
# B  DeviceRegistry.get() and list_devices() prefer UDM
# ===========================================================================

class TestDeviceRegistryReadsFromUDM:
    """DeviceRegistry.get() returns local entry when UDM confirms the device exists."""

    def test_get_falls_back_to_local_when_not_in_udm(self):
        _reset_udm()
        from core.device_registry import DeviceRegistry
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        # Manually add to local cache without going through UDM
        from core.schemas.device import DeviceModel, DeviceCapabilityModel
        from core.device_types import DeviceType, DeviceStatus
        import time
        now = time.time()
        dev = DeviceModel(
            device_id="local_only_001",
            device_type=DeviceType.ANDROID,
            name="LocalOnly",
            status=DeviceStatus.ONLINE,
            registered_at=now,
            last_seen=now,
            last_heartbeat=now,
        )
        reg.devices["local_only_001"] = dev

        # get() should still find it (fallback to local cache)
        result = reg.get("local_only_001")
        assert result is not None

    def test_list_devices_reflects_udm_online_status(self):
        udm = _fresh_udm()
        from core.device_registry import DeviceRegistry, DeviceStatus
        DeviceRegistry._instance = None
        reg = DeviceRegistry()

        asyncio.get_event_loop().run_until_complete(
            reg.register(device_id="dr_list_001", device_type="android", name="Test")
        )

        # Mark OFFLINE via UDM
        from core.unified.models import UnifiedDeviceStatus
        udm.update_device_status("dr_list_001", UnifiedDeviceStatus.OFFLINE)

        # list_devices() should reflect the UDM status
        devices = reg.list_devices()
        found = next((d for d in devices if d.device_id == "dr_list_001"), None)
        assert found is not None
        assert found.status == DeviceStatus.OFFLINE, (
            f"Expected OFFLINE in local list_devices after UDM update, got {found.status}"
        )


# ===========================================================================
# C  DeviceRouter writes to UDM on register/unregister
# ===========================================================================

class TestDeviceRouterWritesToUDM:
    """DeviceRouter.register_device / unregister_device write to UDM."""

    def test_register_device_writes_to_udm(self):
        udm = _fresh_udm()
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()

        router.register_device("gw_dev_001", "android", ["screen"])

        assert udm.get_device("gw_dev_001") is not None, "UDM must contain the gateway-registered device"

    def test_unregister_device_writes_to_udm(self):
        """DeviceRouter.unregister_device marks device OFFLINE in UDM.

        PR-3 / PR-E design intent: ``DeviceRouter.unregister_device`` handles
        *session teardown*, not full device deregistration.  The device
        registration record is preserved in UDM so the system retains history
        and the device can re-attach without a full re-registration cycle.
        Only the runtime connection state is patched to OFFLINE.

        Full deregistration (physical removal from UDM) is the responsibility of
        the ``DELETE /api/v1/devices/{device_id}`` REST endpoint, which calls
        ``UnifiedDeviceManager.unregister_device`` explicitly.
        """
        udm = _fresh_udm()
        from galaxy_gateway.device_router import DeviceRouter
        from core.unified.models import UnifiedDeviceStatus
        router = DeviceRouter()

        router.register_device("gw_dev_002", "android", ["screen"])
        router.unregister_device("gw_dev_002")

        device = udm.get_device("gw_dev_002")
        assert device is not None, (
            "UDM must still contain the device after DeviceRouter.unregister_device: "
            "session teardown must not erase canonical device registration."
        )
        assert device.status == UnifiedDeviceStatus.OFFLINE, (
            f"UDM device must be OFFLINE after DeviceRouter.unregister_device, got {device.status}"
        )


# ===========================================================================
# D  DeviceRouter.get_device_status() reads from UDM
# ===========================================================================

class TestDeviceRouterStatusFromUDM:
    """get_device_status() uses UDM as authoritative source, not self.devices."""

    def test_status_includes_udm_only_device(self):
        """A device registered directly in UDM (not in local self.devices) appears in status."""
        udm = _fresh_udm()
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        router.devices.clear()  # empty local table

        # Register directly in UDM
        udm.register_device_from_dict("udm_only_dev", {"device_type": "windows", "device_name": "UDMOnly"})

        status = router.get_device_status()
        device_ids = [d["device_id"] for d in status["devices"]]
        assert "udm_only_dev" in device_ids, (
            "get_device_status() must include UDM-registered devices even if not in local table"
        )

    def test_status_online_count_reflects_udm(self):
        """Online count comes from UDM, not local self.devices."""
        udm = _fresh_udm()
        from galaxy_gateway.device_router import DeviceRouter
        from core.unified.models import UnifiedDeviceStatus
        router = DeviceRouter()
        router.devices.clear()

        router.register_device("gw_cnt_001", "android", [])
        router.register_device("gw_cnt_002", "android", [])
        # Mark one device offline in UDM
        udm.update_device_status("gw_cnt_002", UnifiedDeviceStatus.OFFLINE)

        status = router.get_device_status()
        assert status["online_devices"] == 1, (
            f"Expected 1 online device (after UDM update), got {status['online_devices']}"
        )


# ===========================================================================
# E  DeviceAgentManager strict UDM sync
# ===========================================================================

class TestDeviceAgentManagerStrictUDM:
    """DeviceAgentManager.register_device rolls back local agent if UDM fails."""

    def _make_manager(self):
        from core.device_agent_manager import DeviceAgentManager
        DeviceAgentManager._instance = None
        mgr = DeviceAgentManager()
        return mgr

    def _make_device_info(self, device_id: str):
        from core.device_agent_manager import DeviceInfo
        from core.device_types import DeviceType
        return DeviceInfo(
            device_id=device_id,
            device_type=DeviceType.ANDROID,
            device_name="Test Device",
        )

    def test_udm_failure_rolls_back_local_agent(self):
        _reset_udm()
        mgr = self._make_manager()
        device_info = self._make_device_info("dam_strict_001")

        with patch.object(mgr, "_unified") as mock_udm_fn:
            mock_udm = MagicMock()
            mock_udm.register_device.side_effect = RuntimeError("UDM unavailable")
            mock_udm_fn.return_value = mock_udm

            result = asyncio.get_event_loop().run_until_complete(
                mgr.register_device(device_info)
            )

        assert result is None, "register_device must return None when UDM write fails (strict mode)"
        assert "dam_strict_001" not in mgr._agents, (
            "Local agent must be rolled back when UDM write fails (strict mode)"
        )

    def test_ignore_udm_failure_keeps_local_agent(self):
        _reset_udm()
        mgr = self._make_manager()
        device_info = self._make_device_info("dam_ignore_001")

        with patch.object(mgr, "_unified") as mock_udm_fn:
            mock_udm = MagicMock()
            mock_udm.register_device.side_effect = RuntimeError("UDM unavailable")
            mock_udm_fn.return_value = mock_udm

            result = asyncio.get_event_loop().run_until_complete(
                mgr.register_device(device_info, ignore_udm_failure=True)
            )

        assert result is not None, "register_device must succeed when ignore_udm_failure=True"
        assert "dam_ignore_001" in mgr._agents

    def test_unregister_logs_error_on_udm_failure(self):
        """unregister_device logs error on UDM failure but still removes local agent."""
        _reset_udm()
        mgr = self._make_manager()
        device_info = self._make_device_info("dam_unreg_001")

        # First register successfully (ignore UDM to bypass init)
        asyncio.get_event_loop().run_until_complete(
            mgr.register_device(device_info, ignore_udm_failure=True)
        )
        assert "dam_unreg_001" in mgr._agents

        # Now unregister with UDM failure
        with patch.object(mgr, "_unified") as mock_udm_fn:
            mock_udm = MagicMock()
            mock_udm.unregister_device.side_effect = RuntimeError("UDM unavailable")
            mock_udm_fn.return_value = mock_udm

            result = asyncio.get_event_loop().run_until_complete(
                mgr.unregister_device("dam_unreg_001")
            )

        assert result is True
        assert "dam_unreg_001" not in mgr._agents, "Local agent must be removed even if UDM fails"


# ===========================================================================
# F  REST routes: heartbeat/delete check UDM for device existence
# ===========================================================================

class TestRESTRoutesCheckUDM:
    """Heartbeat and delete endpoints accept UDM-registered devices even if not in legacy cache."""

    def _make_router(self):
        from core.routes.devices import create_router
        return create_router()

    def test_heartbeat_accepts_udm_only_device(self):
        """POST /api/v1/devices/{id}/heartbeat succeeds for device known only to UDM."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import core.routes._shared as _shared

        udm = _fresh_udm()
        udm.register_device_from_dict("udm_hb_001", {"device_type": "android", "device_name": "HBTest"})

        # Ensure NOT in legacy cache
        _shared.registered_devices.pop("udm_hb_001", None)

        app = FastAPI()
        router = self._make_router()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post("/api/v1/devices/udm_hb_001/heartbeat")
        assert resp.status_code == 200, (
            f"Heartbeat must succeed for UDM-registered device; got {resp.status_code}: {resp.text}"
        )

    def test_delete_accepts_udm_only_device(self):
        """DELETE /api/v1/devices/{id} succeeds for device known only to UDM."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import core.routes._shared as _shared

        udm = _fresh_udm()
        udm.register_device_from_dict("udm_del_001", {"device_type": "android", "device_name": "DelTest"})

        # Ensure NOT in legacy cache
        _shared.registered_devices.pop("udm_del_001", None)

        app = FastAPI()
        router = self._make_router()
        app.include_router(router)
        client = TestClient(app)

        resp = client.delete("/api/v1/devices/udm_del_001")
        assert resp.status_code == 200, (
            f"Delete must succeed for UDM-registered device; got {resp.status_code}: {resp.text}"
        )
        # Confirm UDM entry is gone
        assert udm.get_device("udm_del_001") is None

    def test_heartbeat_returns_404_for_completely_unknown_device(self):
        """POST /api/v1/devices/{id}/heartbeat returns 404 when device is unknown to both UDM and legacy cache."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import core.routes._shared as _shared

        _reset_udm()
        _shared.registered_devices.pop("ghost_device_xyz", None)

        app = FastAPI()
        router = self._make_router()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post("/api/v1/devices/ghost_device_xyz/heartbeat")
        assert resp.status_code == 404
