"""
tests/test_prc_registration_attach_runtime_and_body_mesh.py
=============================================================
Tests for PR-C: Auto attach_runtime_session + BodyMeshRegistry role assignment
on Android device registration and capability_report.

Coverage groups
---------------
A — registration handler calls attach_runtime_session → device visible in registry.
B — registration handler assigns body mesh roles via DeviceRoleAllocator.
C — repeated registration (idempotent re-attach) does not produce duplicates.
D — capability_report handler updates body mesh roles (role refresh).
E — capability_report with no prior registration still assigns roles.
F — attach posture propagated from registration message when present.
G — attach defaults to join_runtime when posture absent in registration message.
H — BodyMeshRegistry entry queryable after registration.
I — existing UDM/durable-session registration chain is not broken by PR-C additions.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.attached_runtime_session import (
    AttachmentState,
    get_attached_runtime_session,
    get_attached_runtime_session_runtime,
    reset_attached_runtime_session_runtime,
)
from core.mesh.body_mesh_registry import (
    get_body_mesh_registry,
    reset_body_mesh_registry,
)
from core.mesh.device_role_allocator import (
    get_device_role_allocator,
    reset_device_role_allocator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def _make_reg_msg(device_id: str = "prc-dev-001", **overrides) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "version": "3.0",
        "type": "device_register",
        "message_id": "msg-prc-001",
        "device_id": device_id,
        "timestamp": int(time.time() * 1000),
        "name": "PR-C Test Phone",
        "model": "Pixel 9",
        "platform": "android",
        "capabilities": 0,
    }
    msg.update(overrides)
    return msg


def _make_cap_report_msg(device_id: str, actions: list, **overrides) -> Dict[str, Any]:
    msg: Dict[str, Any] = {
        "version": "3.0",
        "type": "capability_report",
        "device_id": device_id,
        "platform": "android",
        "supported_actions": actions,
    }
    msg.update(overrides)
    return msg


def _make_bridge() -> MagicMock:
    """Return a minimal mock AndroidBridge."""
    bridge = MagicMock()
    bridge._lock = asyncio.Lock()
    bridge._devices = {}
    bridge._write_registration_to_udm = MagicMock()
    bridge._sync_device_router_session = MagicMock()
    return bridge


@pytest.fixture(autouse=True)
def _isolate_singletons():
    """Reset all relevant singletons before each test for isolation."""
    reset_attached_runtime_session_runtime()
    reset_body_mesh_registry()
    reset_device_role_allocator()
    yield
    reset_attached_runtime_session_runtime()
    reset_body_mesh_registry()
    reset_device_role_allocator()


# ---------------------------------------------------------------------------
# A — registration attaches the device to the runtime session registry
# ---------------------------------------------------------------------------

class TestRegistrationAttachRuntimeSession:
    """Group A: attach_runtime_session is called during handle_device_register."""

    @pytest.mark.asyncio
    async def test_device_queryable_after_registration(self):
        """After handle_device_register, get_attached_runtime_session returns a record."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-attach-a01"
        msg = _make_reg_msg(device_id=device_id)
        bridge = _make_bridge()
        ws = _make_ws()

        await handle_device_register(bridge, ws, msg)

        record = get_attached_runtime_session(device_id)
        assert record is not None, "Expected a session record after registration"
        assert record.device_id == device_id

    @pytest.mark.asyncio
    async def test_record_is_attached_state(self):
        """Default join_runtime posture → attachment_state == attached."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-attach-a02"
        msg = _make_reg_msg(device_id=device_id)
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        record = get_attached_runtime_session(device_id)
        assert record is not None
        assert record.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# B — registration assigns body mesh roles
# ---------------------------------------------------------------------------

class TestRegistrationBodyMeshRoles:
    """Group B: DeviceRoleAllocator.allocate is called during handle_device_register."""

    @pytest.mark.asyncio
    async def test_body_mesh_entry_created_after_registration(self):
        """BodyMeshRegistry has an entry for the device after registration."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-mesh-b01"
        msg = _make_reg_msg(device_id=device_id)
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        registry = get_body_mesh_registry()
        entry = registry.get(device_id)
        assert entry is not None, "Expected a BodyMeshRegistry entry after registration"
        assert entry.device_id == device_id

    @pytest.mark.asyncio
    async def test_capability_based_role_assigned(self):
        """Capabilities in the registration message are reflected as roles."""
        from galaxy_gateway.android_bridge import DeviceCapability
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from core.mesh.body_mesh_registry import DeviceRole

        device_id = "prc-mesh-b02"
        # Use SENSOR_CAMERA capability bitmask → should map to PERCEPTION role via
        # DeviceCapability.to_list which returns "sensor_camera" string containing "camera".
        caps_bitmask = DeviceCapability.SENSOR_CAMERA
        msg = _make_reg_msg(device_id=device_id, capabilities=caps_bitmask)
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        registry = get_body_mesh_registry()
        entry = registry.get(device_id)
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles

    @pytest.mark.asyncio
    async def test_capability_list_format_assigns_roles(self):
        """Capabilities provided as a list of strings are correctly mapped to roles."""
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from core.mesh.body_mesh_registry import DeviceRole

        device_id = "prc-mesh-b03"
        # Pass capabilities as a list of strings (non-bitmask format)
        msg = _make_reg_msg(device_id=device_id, capabilities=["camera", "touch", "screen"])
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        registry = get_body_mesh_registry()
        entry = registry.get(device_id)
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles  # camera
        assert DeviceRole.ACTION in entry.roles       # touch
        assert DeviceRole.PRESENCE in entry.roles     # screen

    @pytest.mark.asyncio
    async def test_zero_capabilities_still_registers_device(self):
        """A device with capabilities=0 (no bitmask) still gets a BodyMeshRegistry entry."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-mesh-b04"
        msg = _make_reg_msg(device_id=device_id, capabilities=0)
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        # Entry should exist even with no inferred roles
        entry = get_body_mesh_registry().get(device_id)
        assert entry is not None
        assert entry.device_id == device_id


# ---------------------------------------------------------------------------
# C — idempotency: repeated registration does not produce duplicates
# ---------------------------------------------------------------------------

class TestRegistrationIdempotency:
    """Group C: repeated registration/reconnect is idempotent."""

    @pytest.mark.asyncio
    async def test_no_duplicate_registry_entries_on_repeated_registration(self):
        """Registering the same device twice produces exactly 1 session record (idempotent re-attach replaces in-place)."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-idem-c01"
        msg = _make_reg_msg(device_id=device_id)
        bridge = _make_bridge()
        ws = _make_ws()

        await handle_device_register(bridge, ws, msg)
        await handle_device_register(bridge, ws, msg)

        runtime = get_attached_runtime_session_runtime()
        records = [r for r in runtime.list_all() if r.device_id == device_id]
        # Idempotent re-attach uses replace_latest_for_device to update in-place,
        # so there should be exactly 1 record for the device.
        assert len(records) == 1, (
            f"Expected exactly 1 record after idempotent re-attach, got {len(records)}"
        )

    @pytest.mark.asyncio
    async def test_body_mesh_roles_stable_on_repeated_registration(self):
        """Registering the same device twice does not corrupt the body mesh entry."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-idem-c02"
        msg = _make_reg_msg(device_id=device_id)
        bridge = _make_bridge()
        ws = _make_ws()

        await handle_device_register(bridge, ws, msg)
        await handle_device_register(bridge, ws, msg)

        registry = get_body_mesh_registry()
        entries = [e for e in registry.list_entries() if e.device_id == device_id]
        assert len(entries) == 1, "BodyMeshRegistry should have exactly one entry per device"


# ---------------------------------------------------------------------------
# D — capability_report updates body mesh roles
# ---------------------------------------------------------------------------

class TestCapabilityReportUpdatesRoles:
    """Group D: handle_capability_report refreshes BodyMeshRegistry roles."""

    @pytest.mark.asyncio
    async def test_roles_updated_after_capability_report(self):
        """capability_report with new actions updates existing body mesh entry."""
        from galaxy_gateway.android.handlers.registration import handle_device_register
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report
        from core.mesh.body_mesh_registry import DeviceRole

        device_id = "prc-cap-d01"
        bridge = _make_bridge()
        ws = _make_ws()

        # Register without camera capability first
        await handle_device_register(bridge, ws, _make_reg_msg(device_id=device_id))

        # Report camera capability → should add PERCEPTION role
        cap_msg = _make_cap_report_msg(device_id, ["camera", "touch"])
        await handle_capability_report(bridge, ws, cap_msg)

        registry = get_body_mesh_registry()
        entry = registry.get(device_id)
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles
        assert DeviceRole.ACTION in entry.roles

    @pytest.mark.asyncio
    async def test_capability_report_is_idempotent(self):
        """Sending the same capability_report twice does not produce duplicates."""
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report

        device_id = "prc-cap-d02"
        bridge = _make_bridge()
        ws = _make_ws()
        cap_msg = _make_cap_report_msg(device_id, ["screen"])

        await handle_capability_report(bridge, ws, cap_msg)
        await handle_capability_report(bridge, ws, cap_msg)

        registry = get_body_mesh_registry()
        entries = [e for e in registry.list_entries() if e.device_id == device_id]
        assert len(entries) == 1


# ---------------------------------------------------------------------------
# E — capability_report without prior registration assigns roles
# ---------------------------------------------------------------------------

class TestCapabilityReportWithoutPriorRegistration:
    """Group E: capability_report on an unregistered device still assigns mesh roles."""

    @pytest.mark.asyncio
    async def test_body_mesh_entry_created_by_capability_report(self):
        """Even without a prior registration, capability_report writes a mesh entry."""
        from galaxy_gateway.android.handlers.capability_report import handle_capability_report
        from core.mesh.body_mesh_registry import DeviceRole

        device_id = "prc-newdev-e01"
        bridge = _make_bridge()
        ws = _make_ws()

        cap_msg = _make_cap_report_msg(device_id, ["microphone", "speaker"])
        await handle_capability_report(bridge, ws, cap_msg)

        registry = get_body_mesh_registry()
        entry = registry.get(device_id)
        assert entry is not None
        assert DeviceRole.PERCEPTION in entry.roles  # microphone
        assert DeviceRole.PRESENCE in entry.roles    # speaker


# ---------------------------------------------------------------------------
# F/G — posture propagation
# ---------------------------------------------------------------------------

class TestPosturePropagation:
    """Groups F/G: source_runtime_posture is correctly propagated."""

    @pytest.mark.asyncio
    async def test_explicit_join_runtime_posture_attaches(self):
        """Explicit join_runtime posture results in attached state."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-posture-f01"
        msg = _make_reg_msg(device_id=device_id, source_runtime_posture="join_runtime")
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        record = get_attached_runtime_session(device_id)
        assert record is not None
        assert record.attachment_state == AttachmentState.attached

    @pytest.mark.asyncio
    async def test_missing_posture_defaults_to_join_runtime(self):
        """When source_runtime_posture is absent, defaults to join_runtime → attached."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-posture-g01"
        msg = _make_reg_msg(device_id=device_id)  # no source_runtime_posture key
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), msg)

        record = get_attached_runtime_session(device_id)
        assert record is not None
        assert record.attachment_state == AttachmentState.attached


# ---------------------------------------------------------------------------
# H — BodyMeshRegistry queryable after registration
# ---------------------------------------------------------------------------

class TestBodyMeshQueryable:
    """Group H: BodyMeshRegistry.get returns the device entry after registration."""

    @pytest.mark.asyncio
    async def test_get_by_device_id_after_registration(self):
        """registry.get(device_id) returns a valid BodyEntry."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-query-h01"
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), _make_reg_msg(device_id=device_id))

        entry = get_body_mesh_registry().get(device_id)
        assert entry is not None
        assert entry.device_id == device_id

    @pytest.mark.asyncio
    async def test_list_entries_includes_registered_device(self):
        """registry.list_entries() contains the newly registered device."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-query-h02"
        bridge = _make_bridge()

        await handle_device_register(bridge, _make_ws(), _make_reg_msg(device_id=device_id))

        ids = [e.device_id for e in get_body_mesh_registry().list_entries()]
        assert device_id in ids


# ---------------------------------------------------------------------------
# I — existing UDM registration chain is not broken
# ---------------------------------------------------------------------------

class TestExistingRegistrationChainNotBroken:
    """Group I: the UDM/durable-session chain is still called after PR-C additions."""

    @pytest.mark.asyncio
    async def test_write_registration_to_udm_still_called(self):
        """bridge._write_registration_to_udm is called during handle_device_register."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-chain-i01"
        bridge = _make_bridge()
        msg = _make_reg_msg(device_id=device_id)

        await handle_device_register(bridge, _make_ws(), msg)

        bridge._write_registration_to_udm.assert_called_once_with(device_id, msg)

    @pytest.mark.asyncio
    async def test_registration_returns_success_ack(self):
        """handle_device_register returns a device_register_ack with type='device_register_ack' and success=True."""
        from galaxy_gateway.android.handlers.registration import handle_device_register

        device_id = "prc-chain-i02"
        bridge = _make_bridge()

        result = await handle_device_register(
            bridge, _make_ws(), _make_reg_msg(device_id=device_id)
        )

        assert result.get("type") == "device_register_ack", (
            f"Expected type='device_register_ack', got: {result.get('type')!r}"
        )
        assert result.get("success") is True, (
            f"Expected success=True, got: {result.get('success')!r}"
        )

