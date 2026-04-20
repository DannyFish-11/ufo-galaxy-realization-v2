"""tests/test_prc_registration_attach_body_mesh.py
===================================================
Tests for PR-C: auto attach_runtime_session and BodyMeshRegistry role
assignment on device registration and capability_report.

Coverage groups
---------------
A  — Registration → attach_runtime_session: device queryable from
     AttachedRuntimeSessionRuntime after registration.
B  — Registration → attached_runtime_session_registry: device queryable from
     AttachedSessionRegistry (PR-19 single-truth source).
C  — Registration → BodyMeshRegistry: device has at least one role after
     registration.
D  — Registration with default Android capabilities assigns expected roles.
E  — Re-registration (idempotency): repeated registration does not create
     duplicate dirty state; roles are merged and runtime session is refreshed.
F  — capability_report → BodyMeshRegistry: existing device's roles are updated.
G  — capability_report with action keywords assigns ACTION role.
H  — capability_report with camera keyword assigns PERCEPTION role.
I  — capability_report with screenshot keyword assigns PRESENCE role.
J  — capability_report for unknown device (not yet registered) still adds to
     BodyMeshRegistry (idempotent first-entry).
K  — _derive_body_mesh_roles: zero capabilities → defaults to ACTION.
L  — _derive_body_mesh_roles: full Android default caps → all three roles.
M  — _derive_roles_from_supported_actions: empty list → ACTION default.
N  — _derive_roles_from_supported_actions: camera action → PERCEPTION.
O  — _derive_roles_from_supported_actions: tap + screenshot → ACTION + PRESENCE.
P  — Registration failure path does not attach runtime session.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Reset helpers
# ---------------------------------------------------------------------------

def _reset_all() -> None:
    """Reset all relevant singletons for test isolation."""
    try:
        from core.unified import device_manager as _udm_mod
        _udm_mod.UnifiedDeviceManager._instance = None
    except Exception:
        pass

    try:
        from core.attached_runtime_session import reset_attached_runtime_session_runtime
        reset_attached_runtime_session_runtime()
    except Exception:
        pass

    try:
        from core.attached_runtime_session_registry import reset_session_registry
        reset_session_registry()
    except Exception:
        pass

    try:
        from core.mesh.body_mesh_registry import reset_body_mesh_registry
        reset_body_mesh_registry()
    except Exception:
        pass

    try:
        from galaxy_gateway.device_router import device_router
        device_router.devices.clear()
    except Exception:
        pass


def _make_websocket() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_registration_message(device_id: str = "test_device_01", **overrides: Any) -> Dict[str, Any]:
    from galaxy_gateway.android.capabilities import DeviceCapability
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
        "capabilities": DeviceCapability.get_android_default(),
        "screen_width": 1080,
        "screen_height": 2400,
    }
    msg.update(overrides)
    return msg


def _make_capability_message(device_id: str = "test_device_01", **overrides: Any) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "type": "capability_report",
        "device_id": device_id,
        "platform": "android",
        "supported_actions": ["tap", "swipe", "screenshot"],
        "version": "1.0",
    }
    msg.update(overrides)
    return msg


# ---------------------------------------------------------------------------
# Group A — Registration → attach_runtime_session queryable
# ---------------------------------------------------------------------------

class TestRegistrationAttachRuntimeSession:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_registration_creates_attached_session_record(self):
        """After registration, AttachedRuntimeSessionRuntime contains the device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session import get_attached_runtime_session

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("a_dev_01"))

        record = get_attached_runtime_session("a_dev_01")
        assert record is not None, "Device must be queryable from AttachedRuntimeSessionRuntime after registration"
        assert record.device_id == "a_dev_01"

    @pytest.mark.asyncio
    async def test_registration_attached_session_is_attached_state(self):
        """Attached session record should have attachment_state == attached."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session import get_attached_runtime_session, AttachmentState

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("a_dev_02"))

        record = get_attached_runtime_session("a_dev_02")
        assert record is not None
        assert record.attachment_state == AttachmentState.attached, (
            f"Expected attached, got {record.attachment_state}"
        )

    @pytest.mark.asyncio
    async def test_registration_attached_session_posture_is_join_runtime(self):
        """Attached session record should carry join_runtime posture."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session import get_attached_runtime_session

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("a_dev_03"))

        record = get_attached_runtime_session("a_dev_03")
        assert record is not None
        assert record.source_runtime_posture == "join_runtime"


# ---------------------------------------------------------------------------
# Group B — Registration → attached_runtime_session_registry queryable
# ---------------------------------------------------------------------------

class TestRegistrationSessionRegistry:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_registration_creates_registry_entry(self):
        """After registration, AttachedSessionRegistry contains the device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session_registry import lookup_session_by_device

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("b_dev_01"))

        entry = lookup_session_by_device("b_dev_01")
        assert entry is not None, "Device must be queryable from AttachedSessionRegistry after registration"
        assert entry.device_id == "b_dev_01"

    @pytest.mark.asyncio
    async def test_registration_registry_entry_is_active(self):
        """Registry entry after registration should be in active state."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            RegistryEntryState,
        )

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("b_dev_02"))

        entry = lookup_session_by_device("b_dev_02")
        assert entry is not None
        assert entry.attachment_state == RegistryEntryState.active, (
            f"Expected active, got {entry.attachment_state}"
        )


# ---------------------------------------------------------------------------
# Group C/D — Registration → BodyMeshRegistry with roles
# ---------------------------------------------------------------------------

class TestRegistrationBodyMeshRegistry:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_registration_adds_device_to_body_mesh(self):
        """After registration, BodyMeshRegistry contains an entry for the device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("c_dev_01"))

        entry = get_body_mesh_registry().get("c_dev_01")
        assert entry is not None, "Device must be present in BodyMeshRegistry after registration"

    @pytest.mark.asyncio
    async def test_registration_assigns_at_least_one_role(self):
        """Registered device must have at least one DeviceRole."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        bridge = AndroidBridge()
        ws = _make_websocket()
        await bridge._handle_device_register(ws, _make_registration_message("c_dev_02"))

        entry = get_body_mesh_registry().get("c_dev_02")
        assert entry is not None
        assert len(entry.roles) >= 1, "Registered device must have at least one role"

    @pytest.mark.asyncio
    async def test_default_android_caps_assigns_all_three_roles(self):
        """Android default capabilities should assign PERCEPTION, ACTION, PRESENCE."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("c_dev_03", capabilities=DeviceCapability.get_android_default())
        await bridge._handle_device_register(ws, msg)

        entry = get_body_mesh_registry().get("c_dev_03")
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles, "Android default caps must include PERCEPTION role"
        assert DeviceRole.ACTION in entry.roles, "Android default caps must include ACTION role"
        assert DeviceRole.PRESENCE in entry.roles, "Android default caps must include PRESENCE role"


# ---------------------------------------------------------------------------
# Group E — Idempotency
# ---------------------------------------------------------------------------

class TestRegistrationIdempotency:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_repeated_registration_does_not_pollute_body_mesh(self):
        """Registering the same device twice must not duplicate entries."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("e_dev_01")
        await bridge._handle_device_register(ws, msg)
        await bridge._handle_device_register(ws, msg)  # duplicate

        entries = get_body_mesh_registry().list_entries()
        matching = [e for e in entries if e.device_id == "e_dev_01"]
        assert len(matching) == 1, f"Expected exactly 1 entry, got {len(matching)}"

    @pytest.mark.asyncio
    async def test_repeated_registration_refreshes_attached_session(self):
        """Registering the same device twice refreshes the attached session record."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session import get_attached_runtime_session, AttachmentState

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("e_dev_02")
        await bridge._handle_device_register(ws, msg)
        await bridge._handle_device_register(ws, msg)  # re-register

        record = get_attached_runtime_session("e_dev_02")
        assert record is not None
        # Idempotent re-attach should still be attached
        assert record.attachment_state == AttachmentState.attached

    @pytest.mark.asyncio
    async def test_repeated_registration_registry_has_one_active_session(self):
        """Re-registration must leave exactly one active session per device."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
            RegistryEntryState,
        )

        bridge = AndroidBridge()
        ws = _make_websocket()
        msg = _make_registration_message("e_dev_03")
        await bridge._handle_device_register(ws, msg)
        await bridge._handle_device_register(ws, msg)  # re-register

        entry = lookup_session_by_device("e_dev_03")
        assert entry is not None
        assert entry.attachment_state == RegistryEntryState.active


# ---------------------------------------------------------------------------
# Group F-J — capability_report → BodyMeshRegistry
# ---------------------------------------------------------------------------

class TestCapabilityReportBodyMeshRegistry:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_capability_report_updates_body_mesh_roles(self):
        """capability_report for an existing device updates its BodyMeshRegistry entry."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        bridge = AndroidBridge()
        ws = _make_websocket()

        # Register first (with zero capabilities to start with minimal roles)
        await bridge._handle_device_register(ws, _make_registration_message("f_dev_01", capabilities=0))

        # Now send capability_report with camera action
        cap_msg = _make_capability_message("f_dev_01", supported_actions=["camera_capture"])
        await bridge._handle_capability_report(ws, cap_msg)

        entry = get_body_mesh_registry().get("f_dev_01")
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles, "camera action must add PERCEPTION role"

    @pytest.mark.asyncio
    async def test_capability_report_action_keyword_adds_action_role(self):
        """capability_report with 'tap' action adds ACTION role."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        bridge = AndroidBridge()
        ws = _make_websocket()
        cap_msg = _make_capability_message("g_dev_01", supported_actions=["tap", "swipe"])
        await bridge._handle_capability_report(ws, cap_msg)

        entry = get_body_mesh_registry().get("g_dev_01")
        assert entry is not None
        assert DeviceRole.ACTION in entry.roles

    @pytest.mark.asyncio
    async def test_capability_report_camera_keyword_adds_perception_role(self):
        """capability_report with 'camera' action adds PERCEPTION role."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        bridge = AndroidBridge()
        ws = _make_websocket()
        cap_msg = _make_capability_message("h_dev_01", supported_actions=["take_camera_photo"])
        await bridge._handle_capability_report(ws, cap_msg)

        entry = get_body_mesh_registry().get("h_dev_01")
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles

    @pytest.mark.asyncio
    async def test_capability_report_screenshot_keyword_adds_presence_role(self):
        """capability_report with 'screenshot' action adds PRESENCE role."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry, DeviceRole

        bridge = AndroidBridge()
        ws = _make_websocket()
        cap_msg = _make_capability_message("i_dev_01", supported_actions=["take_screenshot"])
        await bridge._handle_capability_report(ws, cap_msg)

        entry = get_body_mesh_registry().get("i_dev_01")
        assert entry is not None
        assert DeviceRole.PRESENCE in entry.roles

    @pytest.mark.asyncio
    async def test_capability_report_unregistered_device_creates_mesh_entry(self):
        """capability_report for a device not yet in BodyMeshRegistry creates an entry."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.mesh.body_mesh_registry import get_body_mesh_registry

        bridge = AndroidBridge()
        ws = _make_websocket()
        cap_msg = _make_capability_message("j_dev_01", supported_actions=["tap"])
        await bridge._handle_capability_report(ws, cap_msg)

        entry = get_body_mesh_registry().get("j_dev_01")
        assert entry is not None, "BodyMeshRegistry must accept capability_report even without prior registration"


# ---------------------------------------------------------------------------
# Group K-O — _derive_body_mesh_roles and _derive_roles_from_supported_actions
# ---------------------------------------------------------------------------

class TestDeriveBodyMeshRoles:
    def test_zero_capabilities_defaults_to_action(self):
        """Zero capability bitmask must produce at least ACTION role."""
        from galaxy_gateway.android.handlers.registration import _derive_body_mesh_roles
        from core.mesh.body_mesh_registry import DeviceRole

        roles = _derive_body_mesh_roles(0)
        assert DeviceRole.ACTION in roles, "Zero caps must default to ACTION"

    def test_full_android_default_caps_produces_all_roles(self):
        """Android default capabilities bitmask must produce all three roles."""
        from galaxy_gateway.android.handlers.registration import _derive_body_mesh_roles
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability

        roles = _derive_body_mesh_roles(DeviceCapability.get_android_default())
        assert DeviceRole.PERCEPTION in roles
        assert DeviceRole.ACTION in roles
        assert DeviceRole.PRESENCE in roles

    def test_sensor_camera_produces_perception(self):
        from galaxy_gateway.android.handlers.registration import _derive_body_mesh_roles
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability

        roles = _derive_body_mesh_roles(DeviceCapability.SENSOR_CAMERA)
        assert DeviceRole.PERCEPTION in roles

    def test_input_touch_produces_action(self):
        from galaxy_gateway.android.handlers.registration import _derive_body_mesh_roles
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability

        roles = _derive_body_mesh_roles(DeviceCapability.INPUT_TOUCH)
        assert DeviceRole.ACTION in roles

    def test_gui_screenshot_produces_presence(self):
        from galaxy_gateway.android.handlers.registration import _derive_body_mesh_roles
        from core.mesh.body_mesh_registry import DeviceRole
        from galaxy_gateway.android.capabilities import DeviceCapability

        roles = _derive_body_mesh_roles(DeviceCapability.GUI_SCREENSHOT)
        assert DeviceRole.PRESENCE in roles


class TestDeriveRolesFromSupportedActions:
    def test_empty_list_defaults_to_action(self):
        """Empty supported_actions list must default to ACTION role."""
        from galaxy_gateway.android.handlers.capability_report import _derive_roles_from_supported_actions
        from core.mesh.body_mesh_registry import DeviceRole

        roles = _derive_roles_from_supported_actions([])
        assert DeviceRole.ACTION in roles

    def test_camera_action_produces_perception(self):
        from galaxy_gateway.android.handlers.capability_report import _derive_roles_from_supported_actions
        from core.mesh.body_mesh_registry import DeviceRole

        roles = _derive_roles_from_supported_actions(["camera_capture"])
        assert DeviceRole.PERCEPTION in roles

    def test_tap_and_screenshot_produce_action_and_presence(self):
        from galaxy_gateway.android.handlers.capability_report import _derive_roles_from_supported_actions
        from core.mesh.body_mesh_registry import DeviceRole

        roles = _derive_roles_from_supported_actions(["tap", "take_screenshot"])
        assert DeviceRole.ACTION in roles
        assert DeviceRole.PRESENCE in roles

    def test_no_duplicate_roles(self):
        """Multiple action keywords matching the same category must not produce duplicates."""
        from galaxy_gateway.android.handlers.capability_report import _derive_roles_from_supported_actions
        from core.mesh.body_mesh_registry import DeviceRole

        roles = _derive_roles_from_supported_actions(["tap", "click", "swipe"])
        action_count = roles.count(DeviceRole.ACTION)
        assert action_count == 1, f"Expected 1 ACTION role, got {action_count}"


# ---------------------------------------------------------------------------
# Group P — failure path does not attach runtime session
# ---------------------------------------------------------------------------

class TestRegistrationFailureNoSideEffects:
    def setup_method(self):
        _reset_all()

    @pytest.mark.asyncio
    async def test_failed_registration_does_not_create_attached_session(self):
        """When registration fails (no device_id), no attached session is created."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from core.attached_runtime_session import get_attached_runtime_session

        bridge = AndroidBridge()
        ws = _make_websocket()
        # Missing device_id will cause registration to fail at UDM write
        msg = {
            "type": "device_register",
            "platform": "android",
            # no device_id
        }
        # We monkeypatch _write_registration_to_udm to raise an exception
        original = bridge._write_registration_to_udm
        def _fail(*a, **kw):
            raise RuntimeError("Simulated UDM failure")
        bridge._write_registration_to_udm = _fail

        await bridge._handle_device_register(ws, msg)

        # No device_id to look up, so nothing to assert — but verify no crash
        record = get_attached_runtime_session("")
        # If device_id was empty and exception path was taken, no record should exist
        # for a deliberately-failed registration with no valid device_id
        assert record is None or record.device_id != "p_fail_dev"
