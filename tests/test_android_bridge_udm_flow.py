"""tests/test_android_bridge_udm_flow.py
=========================================
Tests for PR-2: AndroidBridge lifecycle normalisation into UDM canonical path.

Coverage:
  1. Android registration writes to UDM.
  2. Re-registration preserves identity and updates mutable fields.
  3. Heartbeat updates canonical runtime state / last_seen.
  4. Disconnect updates canonical runtime state without deleting identity.
  5. Reconnect does not create duplicate identities.
  6. Android-originated state can project into ``RegisteredRuntimeDevice``.
"""

from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_udm() -> None:
    """Reset the UnifiedDeviceManager singleton between tests."""
    from core.unified import device_manager as _udm_mod
    _udm_mod.UnifiedDeviceManager._instance = None


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_registration_message(device_id: str = "android_test_01", **overrides: Any) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "version": "3.0",
        "type": "device_register",
        "message_id": "msg-001",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "name": "Test Phone",
        "model": "Pixel 7",
        "os_version": "13",
        "sdk_version": 33,
        "platform": "android",
        "device_type": "android_phone",
        "capabilities": 0b111,  # small bitmask for test
        "app_version": "2.0.0",
        "screen_width": 1080,
        "screen_height": 2400,
    }
    msg.update(overrides)
    return msg


# ---------------------------------------------------------------------------
# 1. Registration writes to UDM
# ---------------------------------------------------------------------------

class TestRegistrationWritesToUDM:
    """Android device registration writes canonical state to UDM."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_registration_creates_device_in_udm(self):
        """After registration, UDM contains the device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("udm_reg_01")

        await bridge._handle_device_register(ws, msg)

        udm = UnifiedDeviceManager()
        device = udm.get_device("udm_reg_01")
        assert device is not None, "Device must be present in UDM after registration"
        assert device.device_id == "udm_reg_01"

    @pytest.mark.asyncio
    async def test_registration_sets_source_android_bridge(self):
        """UDM device entry is tagged with source='android_bridge'."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("udm_src_01")

        await bridge._handle_device_register(ws, msg)

        udm = UnifiedDeviceManager()
        device = udm.get_device("udm_src_01")
        assert device is not None
        assert device.source == "android_bridge"

    @pytest.mark.asyncio
    async def test_registration_persists_device_name(self):
        """UDM stores the human-readable device name from the registration payload."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("udm_name_01", name="My Galaxy S23")

        await bridge._handle_device_register(ws, msg)

        udm = UnifiedDeviceManager()
        device = udm.get_device("udm_name_01")
        assert device is not None
        assert device.device_name == "My Galaxy S23"

    @pytest.mark.asyncio
    async def test_registration_also_populates_local_cache(self):
        """Local _devices transport cache is also updated after UDM write."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("cache_01")

        await bridge._handle_device_register(ws, msg)

        assert "cache_01" in bridge._devices
        assert bridge._devices["cache_01"].connected is True

    @pytest.mark.asyncio
    async def test_registration_returns_ack_on_success(self):
        """A device_register_ack with success=True is returned."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("ack_01")

        response = await bridge._handle_device_register(ws, msg)

        assert response is not None
        assert response.get("success") is True
        assert response.get("device_id") == "ack_01"


# ---------------------------------------------------------------------------
# 2. Re-registration preserves identity and updates mutable fields
# ---------------------------------------------------------------------------

class TestReRegistrationPreservesIdentity:
    """Repeated registration with same device_id must not create duplicate UDM entries."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_reregistration_does_not_duplicate_udm_entry(self):
        """UDM holds exactly one entry after two registrations with the same device_id."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("rereg_01")

        await bridge._handle_device_register(ws, msg)
        await bridge._handle_device_register(ws, msg)

        udm = UnifiedDeviceManager()
        devices = [d for d in udm.list_devices() if d.device_id == "rereg_01"]
        assert len(devices) == 1, "UDM must hold exactly one entry for the device_id"

    @pytest.mark.asyncio
    async def test_reregistration_updates_device_name(self):
        """Second registration with updated name is reflected in UDM."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()

        first_msg = _make_registration_message("rereg_name_01", name="OldName")
        await bridge._handle_device_register(ws, first_msg)

        second_msg = _make_registration_message("rereg_name_01", name="NewName")
        await bridge._handle_device_register(ws, second_msg)

        udm = UnifiedDeviceManager()
        device = udm.get_device("rereg_name_01")
        assert device is not None
        assert device.device_name == "NewName"

    @pytest.mark.asyncio
    async def test_reregistration_preserves_registered_at(self):
        """registered_at timestamp is preserved from first registration (no identity drift)."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("rereg_ts_01")

        await bridge._handle_device_register(ws, msg)
        udm = UnifiedDeviceManager()
        dev_first = udm.get_device("rereg_ts_01")
        assert dev_first is not None, "Device must exist in UDM after first registration"
        first_registered_at = dev_first.registered_at

        # Short sleep to ensure timestamps differ if re-created.
        import asyncio
        await asyncio.sleep(0.05)

        await bridge._handle_device_register(ws, msg)
        dev_second = udm.get_device("rereg_ts_01")
        assert dev_second is not None, "Device must still exist in UDM after re-registration"
        second_registered_at = dev_second.registered_at

        assert first_registered_at == second_registered_at, (
            "registered_at must not change on re-registration"
        )


# ---------------------------------------------------------------------------
# 3. Heartbeat updates canonical runtime state / last_seen
# ---------------------------------------------------------------------------

class TestHeartbeatUpdatesUDM:
    """Heartbeat must patch UDM canonical state (last_heartbeat + keep ONLINE)."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_heartbeat_updates_last_heartbeat_in_udm(self):
        """UDM last_heartbeat is updated after heartbeat message."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()

        # Register first so UDM has the device
        await bridge._handle_device_register(ws, _make_registration_message("hb_01"))

        udm = UnifiedDeviceManager()
        dev_before = udm.get_device("hb_01")
        assert dev_before is not None, "Device must exist in UDM after registration"
        before = dev_before.last_heartbeat

        import asyncio
        await asyncio.sleep(0.05)

        hb_msg = {
            "version": "3.0", "type": "device_heartbeat",
            "message_id": "hb-msg-001", "device_id": "hb_01",
            "timestamp": int(time.time() * 1000),
        }
        await bridge._handle_heartbeat(ws, hb_msg)

        dev_after = udm.get_device("hb_01")
        assert dev_after is not None, "Device must still exist in UDM after heartbeat"
        after = dev_after.last_heartbeat
        assert after is not None
        # after must be >= before (or None if not set yet)
        if before is not None:
            assert after >= before

    @pytest.mark.asyncio
    async def test_heartbeat_returns_ack(self):
        """Heartbeat handler always returns a heartbeat_ack."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()
        hb_msg = {
            "version": "3.0", "type": "device_heartbeat",
            "message_id": "hb-ack-001", "device_id": "hb_ack_01",
            "timestamp": int(time.time() * 1000),
        }
        response = await bridge._handle_heartbeat(ws, hb_msg)
        assert response is not None
        assert "heartbeat" in response.get("type", "").lower()

    @pytest.mark.asyncio
    async def test_heartbeat_keeps_device_online_in_udm(self):
        """UDM device status remains ONLINE after heartbeat."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("hb_online_01"))

        hb_msg = {
            "version": "3.0", "type": "device_heartbeat",
            "message_id": "hb-online-001", "device_id": "hb_online_01",
            "timestamp": int(time.time() * 1000),
        }
        await bridge._handle_heartbeat(ws, hb_msg)

        udm = UnifiedDeviceManager()
        device = udm.get_device("hb_online_01")
        assert device is not None
        assert device.status in (UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value)


# ---------------------------------------------------------------------------
# 4. Disconnect updates canonical runtime state without deleting identity
# ---------------------------------------------------------------------------

class TestDisconnectUpdatesUDM:
    """Disconnect must mark device as DISCONNECTED in UDM without removing it."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_disconnect_marks_device_disconnected_in_udm(self):
        """UDM device status becomes DISCONNECTED after disconnect_device()."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("dc_01"))
        await bridge.disconnect_device("dc_01")

        udm = UnifiedDeviceManager()
        device = udm.get_device("dc_01")
        assert device is not None, "Identity must be preserved in UDM after disconnect"
        assert device.status in (
            UnifiedDeviceStatus.DISCONNECTED,
            UnifiedDeviceStatus.DISCONNECTED.value,
        ), f"Expected DISCONNECTED, got {device.status}"

    @pytest.mark.asyncio
    async def test_disconnect_preserves_device_identity_in_udm(self):
        """Canonical UDM entry still exists after disconnect (no identity deletion)."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("dc_id_01"))
        await bridge.disconnect_device("dc_id_01")

        udm = UnifiedDeviceManager()
        device = udm.get_device("dc_id_01")
        assert device is not None
        assert device.device_id == "dc_id_01"

    @pytest.mark.asyncio
    async def test_disconnect_clears_local_transport_cache_websocket(self):
        """Local _devices transport cache reflects disconnected state (no websocket)."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("dc_local_01"))
        await bridge.disconnect_device("dc_local_01")

        assert "dc_local_01" in bridge._devices
        assert bridge._devices["dc_local_01"].connected is False
        assert bridge._devices["dc_local_01"].websocket is None


# ---------------------------------------------------------------------------
# 5. Reconnect does not create duplicate identities
# ---------------------------------------------------------------------------

class TestReconnectNoDuplicate:
    """Reconnect must restore ONLINE state without creating duplicate UDM entries."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect_restores_online_status(self):
        """UDM status is ONLINE again after reconnect."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("rc_01"))
        await bridge.disconnect_device("rc_01")
        await bridge.reconnect_device("rc_01", ws)

        udm = UnifiedDeviceManager()
        device = udm.get_device("rc_01")
        assert device is not None
        assert device.status in (
            UnifiedDeviceStatus.ONLINE, UnifiedDeviceStatus.ONLINE.value,
        ), f"Expected ONLINE after reconnect, got {device.status}"

    @pytest.mark.asyncio
    async def test_reconnect_does_not_duplicate_udm_entry(self):
        """UDM still has exactly one entry after reconnect."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("rc_dup_01"))
        await bridge.disconnect_device("rc_dup_01")
        await bridge.reconnect_device("rc_dup_01", ws)

        udm = UnifiedDeviceManager()
        devices = [d for d in udm.list_devices() if d.device_id == "rc_dup_01"]
        assert len(devices) == 1, "Must have exactly one UDM entry after reconnect"

    @pytest.mark.asyncio
    async def test_reconnect_returns_true_for_known_device(self):
        """reconnect_device returns True when the device was previously registered."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("rc_ret_01"))
        result = await bridge.reconnect_device("rc_ret_01", ws)

        assert result is True

    @pytest.mark.asyncio
    async def test_reconnect_returns_false_for_unknown_device(self):
        """reconnect_device returns False for a device never registered in local cache."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        ws = _make_websocket()

        result = await bridge.reconnect_device("never_registered", ws)
        assert result is False


# ---------------------------------------------------------------------------
# 6. Android-originated state projects into RegisteredRuntimeDevice
# ---------------------------------------------------------------------------

class TestAndroidToRegisteredRuntimeDevice:
    """Android registration payload can be projected into canonical RegisteredRuntimeDevice."""

    def setup_method(self):
        _reset_udm()

    def test_from_android_registration_produces_valid_contract(self):
        """from_android_registration builds a valid RegisteredRuntimeDevice."""
        from contracts.registered_runtime_device import (
            from_android_registration,
            RegisteredRuntimeDevice,
            RuntimeDevicePlatform,
            RuntimeDeviceStatus,
        )

        data = _make_registration_message("proj_01")
        contract = from_android_registration(data)

        assert isinstance(contract, RegisteredRuntimeDevice)
        assert contract.device_id == "proj_01"
        assert contract.platform in (
            RuntimeDevicePlatform.ANDROID,
            RuntimeDevicePlatform.ANDROID.value,
        )
        assert contract.status in (
            RuntimeDeviceStatus.ONLINE,
            RuntimeDeviceStatus.ONLINE.value,
        )
        assert contract.online is True

    def test_from_android_registration_serialises_to_json(self):
        """Contract produced from Android data is JSON-serialisable."""
        import json
        from contracts.registered_runtime_device import from_android_registration

        data = _make_registration_message("proj_json_01")
        contract = from_android_registration(data)
        raw = contract.to_json()
        parsed = json.loads(raw)
        assert parsed["device_id"] == "proj_json_01"

    @pytest.mark.asyncio
    async def test_udm_device_projects_into_registered_runtime_device(self):
        """After registration, UDM device can be projected into RegisteredRuntimeDevice."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager
        from contracts.registered_runtime_device import (
            from_udm_device,
            RegisteredRuntimeDevice,
        )

        bridge = AndroidBridge()
        ws = _make_websocket()

        await bridge._handle_device_register(ws, _make_registration_message("udm_proj_01"))

        udm = UnifiedDeviceManager()
        udm_device = udm.get_device("udm_proj_01")
        assert udm_device is not None

        contract = from_udm_device(udm_device)
        assert isinstance(contract, RegisteredRuntimeDevice)
        assert contract.device_id == "udm_proj_01"

    def test_from_android_registration_capabilities_bitmask_decoded(self):
        """Capability bitmask in Android registration is decoded to string list."""
        from galaxy_gateway.android_bridge import DeviceCapability
        from contracts.registered_runtime_device import from_android_registration

        # Use a known bitmask
        bitmask = DeviceCapability.NETWORK | DeviceCapability.SENSOR_CAMERA
        data = _make_registration_message("proj_caps_01", capabilities=bitmask)
        contract = from_android_registration(data)

        caps = contract.capabilities.capabilities
        assert isinstance(caps, list)
        assert "network" in caps
        assert "sensor_camera" in caps

    def test_from_android_registration_metadata_contains_model(self):
        """Metadata block in the contract carries the device model string."""
        from contracts.registered_runtime_device import from_android_registration

        data = _make_registration_message("proj_meta_01", model="Samsung Galaxy S24")
        contract = from_android_registration(data)

        assert contract.metadata.get("model") == "Samsung Galaxy S24"

    def test_from_android_registration_graceful_on_empty_payload(self):
        """from_android_registration degrades gracefully on a minimal payload."""
        from contracts.registered_runtime_device import (
            from_android_registration,
            RegisteredRuntimeDevice,
        )

        # Only device_id provided — all else defaults.
        contract = from_android_registration({"device_id": "minimal_01"})
        assert isinstance(contract, RegisteredRuntimeDevice)
        assert contract.device_id == "minimal_01"


# ---------------------------------------------------------------------------
# 7. UDM helper isolation tests (internal helpers)
# ---------------------------------------------------------------------------

class TestUDMHelpers:
    """Unit tests for the internal UDM write/patch helpers."""

    def setup_method(self):
        _reset_udm()

    def test_write_registration_to_udm_creates_device(self):
        """_write_registration_to_udm creates a UDM entry for the device_id."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager

        bridge = AndroidBridge()
        msg = _make_registration_message("helper_reg_01")
        bridge._write_registration_to_udm("helper_reg_01", msg)

        udm = UnifiedDeviceManager()
        assert udm.get_device("helper_reg_01") is not None

    def test_patch_heartbeat_to_udm_does_not_raise_for_unknown_device(self):
        """_patch_heartbeat_to_udm is non-fatal for a device not yet in UDM."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        # Must not raise even when the device is unknown
        bridge._patch_heartbeat_to_udm("nonexistent_device")

    def test_patch_disconnect_to_udm_does_not_raise_for_unknown_device(self):
        """_patch_disconnect_to_udm is non-fatal for a device not in UDM."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        bridge._patch_disconnect_to_udm("nonexistent_device")

    def test_patch_reconnect_to_udm_does_not_raise_for_unknown_device(self):
        """_patch_reconnect_to_udm is non-fatal for a device not in UDM."""
        from galaxy_gateway.android_bridge import AndroidBridge

        bridge = AndroidBridge()
        bridge._patch_reconnect_to_udm("nonexistent_device")

    def test_patch_runtime_state_to_udm_updates_registered_device(self):
        """_patch_runtime_state_to_udm updates state for an already-registered device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.unified.device_manager import UnifiedDeviceManager
        from core.unified.models import UnifiedDeviceStatus

        bridge = AndroidBridge()
        msg = _make_registration_message("helper_patch_01")
        bridge._write_registration_to_udm("helper_patch_01", msg)

        bridge._patch_runtime_state_to_udm(
            "helper_patch_01",
            {"status": "disconnected"},
            source="test",
        )

        udm = UnifiedDeviceManager()
        device = udm.get_device("helper_patch_01")
        assert device is not None
        assert device.status in (
            UnifiedDeviceStatus.DISCONNECTED,
            UnifiedDeviceStatus.DISCONNECTED.value,
        )
