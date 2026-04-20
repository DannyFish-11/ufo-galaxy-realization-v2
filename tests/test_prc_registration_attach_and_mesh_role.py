"""tests/test_prc_registration_attach_and_mesh_role.py
=======================================================
PR-C: Registration chain auto-attach runtime session + BodyMeshRegistry role
assignment.

Coverage
--------
A  — Successful registration attaches device to AttachedRuntimeSessionRuntime.
B  — Registered device has attachment_state=attached (join_runtime posture).
C  — Successful registration assigns BodyMeshRegistry roles for the device.
D  — Repeated registration is idempotent (no duplicate pollution).
E  — capability_report triggers BodyMeshRegistry role update.
F  — capability_report role update is idempotent.
G  — capability_report with touch/screen/camera capabilities infers correct roles.
H  — Registration failure does NOT write attached session (UDM write raises).
I  — Device with only touch capability gets ACTION role after capability_report.
J  — Device with only camera capability gets PERCEPTION role after capability_report.
K  — Device with only screen capability gets PRESENCE role after capability_report.
L  — Registration attach uses 'join_runtime' posture (device is eligible for execution).
M  — After registration, get_attached_runtime_session returns the record.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bridge():
    """Return a minimal mock AndroidBridge."""
    bridge = MagicMock()
    bridge._lock = asyncio.Lock()
    bridge._devices = {}

    def _write_udm(device_id, message):
        pass  # success by default

    bridge._write_registration_to_udm.side_effect = _write_udm
    bridge._sync_device_router_session.return_value = None
    return bridge


def _make_websocket():
    ws = MagicMock()
    return ws


def _reg_message(
    device_id: str = "test-device-01",
    platform: str = "android",
    model: str = "Galaxy S24",
    capabilities: int = 0,
) -> Dict[str, Any]:
    return {
        "type": "device_register",
        "device_id": device_id,
        "platform": platform,
        "model": model,
        "capabilities": capabilities,
    }


def _cap_report_message(
    device_id: str = "test-device-01",
    platform: str = "android",
    supported_actions: Optional[list] = None,
) -> Dict[str, Any]:
    return {
        "type": "capability_report",
        "device_id": device_id,
        "platform": platform,
        "supported_actions": supported_actions or [],
    }


# ---------------------------------------------------------------------------
# Fixtures: isolated singletons
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Isolate all relevant singletons between tests."""
    from core.attached_runtime_session import reset_attached_runtime_session_runtime
    from core.mesh.body_mesh_registry import reset_body_mesh_registry
    from core.mesh.device_role_allocator import reset_device_role_allocator

    reset_attached_runtime_session_runtime()
    reset_body_mesh_registry()
    reset_device_role_allocator()
    yield
    reset_attached_runtime_session_runtime()
    reset_body_mesh_registry()
    reset_device_role_allocator()


# ---------------------------------------------------------------------------
# A — Successful registration attaches device to AttachedRuntimeSessionRuntime
# ---------------------------------------------------------------------------


class TestRegistrationAttach:
    def test_a_attach_runtime_session_called_on_registration(self):
        from core.attached_runtime_session import (
            get_attached_runtime_session,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        msg = _reg_message(device_id="dev-attach-01")

        asyncio.get_event_loop().run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        record = get_attached_runtime_session("dev-attach-01")
        assert record is not None, "Expected attached session record after registration"

    # B
    def test_b_registered_device_has_attached_state(self):
        from core.attached_runtime_session import (
            AttachmentState,
            get_attached_runtime_session,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        msg = _reg_message(device_id="dev-attach-02")

        asyncio.get_event_loop().run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        record = get_attached_runtime_session("dev-attach-02")
        assert record is not None
        assert record.attachment_state == AttachmentState.attached

    # C
    def test_c_registration_assigns_body_mesh_roles(self):
        from core.mesh.body_mesh_registry import get_body_mesh_registry, reset_body_mesh_registry
        from core.mesh.device_role_allocator import reset_device_role_allocator
        from galaxy_gateway.android.capabilities import DeviceCapability
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_body_mesh_registry()
        reset_device_role_allocator()
        bridge = _make_bridge()
        # capabilities that contain camera → PERCEPTION and touch → ACTION
        caps = DeviceCapability.SENSOR_CAMERA | DeviceCapability.INPUT_TOUCH
        msg = _reg_message(device_id="dev-roles-01", capabilities=caps)

        asyncio.get_event_loop().run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        entry = get_body_mesh_registry().get("dev-roles-01")
        assert entry is not None, "Expected BodyMeshRegistry entry after registration"
        from core.mesh.body_mesh_registry import DeviceRole
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.PERCEPTION.value in role_values
        assert DeviceRole.ACTION.value in role_values

    # D — Idempotency: repeated registration does not pollute
    def test_d_repeated_registration_is_idempotent(self):
        from core.attached_runtime_session import (
            list_active_attached_sessions,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        msg = _reg_message(device_id="dev-idempotent-01")

        loop = asyncio.get_event_loop()
        loop.run_until_complete(handle_device_register(bridge, _make_websocket(), msg))
        loop.run_until_complete(handle_device_register(bridge, _make_websocket(), msg))
        loop.run_until_complete(handle_device_register(bridge, _make_websocket(), msg))

        active = list_active_attached_sessions()
        device_records = [r for r in active if r.device_id == "dev-idempotent-01"]
        # idempotent: at most one active attached record for the device
        assert len(device_records) <= 1, (
            f"Expected at most 1 active record, got {len(device_records)}"
        )

    # H — Registration failure does NOT write attached session
    def test_h_registration_failure_no_attach(self):
        from core.attached_runtime_session import (
            get_attached_runtime_session,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        bridge._write_registration_to_udm.side_effect = RuntimeError("UDM unavailable")
        msg = _reg_message(device_id="dev-fail-01")

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        # Registration should have failed
        assert not result.get("success", True), "Expected registration failure response"
        # No session should have been attached
        record = get_attached_runtime_session("dev-fail-01")
        assert record is None, "No session should be attached when registration fails"

    # L — attach uses join_runtime posture
    def test_l_attach_uses_join_runtime_posture(self):
        from core.attached_runtime_session import (
            get_attached_runtime_session,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        msg = _reg_message(device_id="dev-posture-01")

        asyncio.get_event_loop().run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        record = get_attached_runtime_session("dev-posture-01")
        assert record is not None
        assert record.source_runtime_posture == "join_runtime"

    # M — get_attached_runtime_session returns record after registration
    def test_m_get_attached_runtime_session_returns_record(self):
        from core.attached_runtime_session import (
            get_attached_runtime_session,
            reset_attached_runtime_session_runtime,
        )
        from galaxy_gateway.android.handlers.registration import handle_device_register

        reset_attached_runtime_session_runtime()
        bridge = _make_bridge()
        msg = _reg_message(device_id="dev-query-01")

        asyncio.get_event_loop().run_until_complete(
            handle_device_register(bridge, _make_websocket(), msg)
        )

        record = get_attached_runtime_session("dev-query-01")
        assert record is not None
        assert record.device_id == "dev-query-01"


# ---------------------------------------------------------------------------
# E — capability_report triggers BodyMeshRegistry role update
# ---------------------------------------------------------------------------


class TestCapabilityReportMeshRoles:
    def test_e_capability_report_updates_mesh_roles(self):
        from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-caprep-01",
            supported_actions=["touch", "screen", "camera"],
        )

        asyncio.get_event_loop().run_until_complete(
            handle_capability_report(bridge, _make_websocket(), msg)
        )

        registry = get_body_mesh_registry()
        entry = registry.get("dev-caprep-01")
        assert entry is not None, "Expected entry in BodyMeshRegistry after capability_report"
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.ACTION.value in role_values   # touch → ACTION
        assert DeviceRole.PRESENCE.value in role_values  # screen → PRESENCE
        assert DeviceRole.PERCEPTION.value in role_values  # camera → PERCEPTION

    # F — idempotent
    def test_f_capability_report_role_update_is_idempotent(self):
        from core.mesh.body_mesh_registry import get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-caprep-idempotent",
            supported_actions=["touch", "camera"],
        )

        loop = asyncio.get_event_loop()
        loop.run_until_complete(handle_capability_report(bridge, _make_websocket(), msg))
        loop.run_until_complete(handle_capability_report(bridge, _make_websocket(), msg))
        loop.run_until_complete(handle_capability_report(bridge, _make_websocket(), msg))

        registry = get_body_mesh_registry()
        entry = registry.get("dev-caprep-idempotent")
        assert entry is not None
        # Roles should not be duplicated; set semantics ensure uniqueness
        from core.mesh.body_mesh_registry import DeviceRole
        role_values = list(entry.roles)
        assert len(role_values) == len(set(role_values)), "Roles must be deduplicated"

    # G — capability keywords infer correct roles
    def test_g_capability_keywords_infer_correct_roles(self):
        from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-roles-infer",
            supported_actions=["microphone", "keyboard", "notification"],
        )

        asyncio.get_event_loop().run_until_complete(
            handle_capability_report(bridge, _make_websocket(), msg)
        )

        registry = get_body_mesh_registry()
        entry = registry.get("dev-roles-infer")
        assert entry is not None
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.PERCEPTION.value in role_values  # microphone
        assert DeviceRole.ACTION.value in role_values      # keyboard
        assert DeviceRole.PRESENCE.value in role_values    # notification

    # I — only touch → ACTION
    def test_i_touch_only_gets_action_role(self):
        from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-touch-only",
            supported_actions=["touch"],
        )
        asyncio.get_event_loop().run_until_complete(
            handle_capability_report(bridge, _make_websocket(), msg)
        )
        entry = get_body_mesh_registry().get("dev-touch-only")
        assert entry is not None
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.ACTION.value in role_values

    # J — only camera → PERCEPTION
    def test_j_camera_only_gets_perception_role(self):
        from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-camera-only",
            supported_actions=["camera"],
        )
        asyncio.get_event_loop().run_until_complete(
            handle_capability_report(bridge, _make_websocket(), msg)
        )
        entry = get_body_mesh_registry().get("dev-camera-only")
        assert entry is not None
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.PERCEPTION.value in role_values

    # K — only screen → PRESENCE
    def test_k_screen_only_gets_presence_role(self):
        from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        bridge = _make_bridge()
        msg = _cap_report_message(
            device_id="dev-screen-only",
            supported_actions=["screen"],
        )
        asyncio.get_event_loop().run_until_complete(
            handle_capability_report(bridge, _make_websocket(), msg)
        )
        entry = get_body_mesh_registry().get("dev-screen-only")
        assert entry is not None
        role_values = {r.value for r in entry.roles}
        assert DeviceRole.PRESENCE.value in role_values
