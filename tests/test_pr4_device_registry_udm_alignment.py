"""tests/test_pr4_device_registry_udm_alignment.py
===================================================
Tests for PR-4: DeviceRegistry repositioned as compatibility/indexing/discovery
layer over UDM canonical authority.

Coverage
--------
1. Registration aligns with UDM identity semantics — registry write always
   delegates to UDM first; UDM holds the canonical record.
2. Duplicate registration does not create divergent canonical identity — a
   second ``register()`` call reuses the existing UDM record and the existing
   local entry rather than spawning a second identity.
3. Persistence restore does not incorrectly recreate authoritative online state
   — devices loaded from the snapshot are always OFFLINE.
4. Group / tag / capability indexing still works after the demotion.
5. Registry-derived views can be projected into ``RegisteredRuntimeDevice``
   via ``project_to_contract()``.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_udm() -> None:
    """Reset the UnifiedDeviceManager singleton between tests."""
    from core.unified import device_manager as _udm_mod
    _udm_mod.UnifiedDeviceManager._instance = None


def _fresh_registry():
    """Return a fresh DeviceRegistry instance backed by a temp dir snapshot."""
    _reset_udm()
    from core.device_registry import DeviceRegistry
    reg = DeviceRegistry.__new__(DeviceRegistry)
    reg.devices = {}
    reg.groups = {}
    reg.tag_index = {}
    reg.capability_index = {}
    # Point persistence at a temp file so tests don't interfere with real data.
    _fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(_fd)
    reg.storage_path = Path(tmp)
    reg._on_device_registered = []
    reg._on_device_offline = []
    reg._on_device_online = []
    return reg


# ---------------------------------------------------------------------------
# 1. Registration aligns with UDM identity semantics
# ---------------------------------------------------------------------------


class TestRegistrationAlignsWithUDM:
    """Registry registration writes canonical state to UDM first."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_registration_writes_to_udm(self):
        """After register(), UDM must contain a record for the device."""
        from core.unified.device_manager import UnifiedDeviceManager

        reg = _fresh_registry()
        await reg.register(
            device_id="udm_align_01",
            device_type="android",
            name="Test Phone",
            capabilities=["screen", "camera"],
        )

        udm = UnifiedDeviceManager()
        device = udm.get_device("udm_align_01")
        assert device is not None, "UDM must hold canonical record after registry.register()"
        assert device.device_id == "udm_align_01"

    @pytest.mark.asyncio
    async def test_registration_source_tagged_as_device_registry(self):
        """UDM record must carry source='device_registry'."""
        from core.unified.device_manager import UnifiedDeviceManager

        reg = _fresh_registry()
        await reg.register(
            device_id="udm_src_01",
            device_type="windows",
            name="Test PC",
        )

        udm = UnifiedDeviceManager()
        device = udm.get_device("udm_src_01")
        assert device is not None
        meta = getattr(device, "metadata", {}) or {}
        assert meta.get("source") == "device_registry", (
            "UDM record must carry source='device_registry'"
        )

    @pytest.mark.asyncio
    async def test_registry_local_record_created(self):
        """A local compatibility record is also created in the registry index."""
        reg = _fresh_registry()
        await reg.register(
            device_id="local_rec_01",
            device_type="android",
            capabilities=["screen"],
        )

        assert "local_rec_01" in reg.devices, "Local compatibility record must exist after register()"

    @pytest.mark.asyncio
    async def test_registry_role_constant_documents_layer(self):
        """The _REGISTRY_ROLE constant correctly declares the demotion."""
        from core.device_registry import _REGISTRY_ROLE

        assert "compatibility" in _REGISTRY_ROLE, "_REGISTRY_ROLE must mention compatibility layer"
        assert "UDM" in _REGISTRY_ROLE or "UnifiedDeviceManager" in _REGISTRY_ROLE, (
            "_REGISTRY_ROLE must reference UDM as canonical authority"
        )


# ---------------------------------------------------------------------------
# 2. Duplicate registration does not create divergent canonical identity
# ---------------------------------------------------------------------------


class TestDuplicateRegistrationNoDivergence:
    """A second register() call does not fork UDM identity."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_double_register_udm_single_record(self):
        """Two register() calls for the same device_id produce one UDM record."""
        from core.unified.device_manager import UnifiedDeviceManager

        reg = _fresh_registry()
        await reg.register(
            device_id="dup_01",
            device_type="android",
            name="Phone 1",
        )
        await reg.register(
            device_id="dup_01",
            device_type="android",
            name="Phone 1 (re-register)",
        )

        udm = UnifiedDeviceManager()
        all_devices = udm.list_devices()
        ids = [d.device_id for d in all_devices]
        assert ids.count("dup_01") == 1, (
            "Duplicate registration must not create two UDM records"
        )

    @pytest.mark.asyncio
    async def test_double_register_local_single_record(self):
        """Two register() calls for the same device_id produce one local record."""
        reg = _fresh_registry()
        await reg.register(device_id="dup_local_01", device_type="android")
        await reg.register(device_id="dup_local_01", device_type="android")

        assert list(reg.devices.keys()).count("dup_local_01") == 1, (
            "Duplicate registration must not create two local records"
        )

    @pytest.mark.asyncio
    async def test_second_register_returns_same_object(self):
        """The second register() call returns the existing local record, not a new one."""
        reg = _fresh_registry()
        first = await reg.register(device_id="dup_obj_01", device_type="android")
        second = await reg.register(device_id="dup_obj_01", device_type="android")

        assert first is second, "Second register() must return the same local object"

    @pytest.mark.asyncio
    async def test_duplicate_register_merges_new_groups(self):
        """A re-registration with new groups merges them into the existing record."""
        reg = _fresh_registry()
        await reg.register(
            device_id="dup_grp_01",
            device_type="android",
            groups=["mobile"],
        )
        await reg.register(
            device_id="dup_grp_01",
            device_type="android",
            groups=["mobile", "vip"],
        )

        device = reg.devices.get("dup_grp_01")
        assert device is not None
        assert "mobile" in device.groups
        assert "vip" in device.groups, "New groups must be merged on re-registration"


# ---------------------------------------------------------------------------
# 3. Persistence restore does not recreate authoritative online state
# ---------------------------------------------------------------------------


class TestPersistenceSnapshotSemantics:
    """Snapshot restore forces devices to OFFLINE — no authoritative online status."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_loaded_devices_are_offline(self):
        """Devices restored from the snapshot file are always OFFLINE."""
        from core.device_registry import DeviceRegistry
        from core.device_types import DeviceStatus

        # Write a snapshot with an ONLINE device.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            tmp_path = f.name
            json.dump(
                {
                    "devices": {
                        "snap_01": {
                            "device_id": "snap_01",
                            "device_type": "android",
                            "name": "Snap Device",
                            "status": "online",  # Snapshot records ONLINE status
                            "capabilities": [],
                            "groups": [],
                            "tags": [],
                            "metadata": {},
                            "registered_at": time.time(),
                            "last_seen": time.time(),
                            "last_heartbeat": time.time(),
                        }
                    },
                    "groups": {},
                    "tag_index": {},
                    "capability_index": {},
                    "saved_at": time.time(),
                },
                f,
            )

        # Load a fresh registry from that snapshot.
        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg.devices = {}
        reg.groups = {}
        reg.tag_index = {}
        reg.capability_index = {}
        reg.storage_path = Path(tmp_path)
        reg._on_device_registered = []
        reg._on_device_offline = []
        reg._on_device_online = []
        reg._load()

        os.unlink(tmp_path)

        device = reg.devices.get("snap_01")
        assert device is not None, "Device should be loaded from snapshot"
        status_val = device.status.value if hasattr(device.status, "value") else str(device.status)
        assert status_val == DeviceStatus.OFFLINE.value, (
            "Snapshot restore must force device to OFFLINE — "
            "authoritative online state must come from re-registration"
        )

    @pytest.mark.asyncio
    async def test_snapshot_does_not_populate_udm(self):
        """Loading from snapshot does not push any records into UDM."""
        from core.unified.device_manager import UnifiedDeviceManager
        from core.device_registry import DeviceRegistry

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            tmp_path = f.name
            json.dump(
                {
                    "devices": {
                        "snap_udm_01": {
                            "device_id": "snap_udm_01",
                            "device_type": "android",
                            "name": "Ghost Device",
                            "status": "online",
                            "capabilities": [],
                            "groups": [],
                            "tags": [],
                            "metadata": {},
                            "registered_at": time.time(),
                            "last_seen": time.time(),
                            "last_heartbeat": time.time(),
                        }
                    },
                    "groups": {},
                    "tag_index": {},
                    "capability_index": {},
                    "saved_at": time.time(),
                },
                f,
            )

        reg = DeviceRegistry.__new__(DeviceRegistry)
        reg.devices = {}
        reg.groups = {}
        reg.tag_index = {}
        reg.capability_index = {}
        reg.storage_path = Path(tmp_path)
        reg._on_device_registered = []
        reg._on_device_offline = []
        reg._on_device_online = []
        reg._load()

        os.unlink(tmp_path)

        udm = UnifiedDeviceManager()
        ghost = udm.get_device("snap_udm_01")
        assert ghost is None, (
            "Snapshot restore must NOT push devices into UDM — "
            "UDM canonical state is populated only via register()"
        )


# ---------------------------------------------------------------------------
# 4. Group / tag / capability indexing still works
# ---------------------------------------------------------------------------


class TestIndexingPreserved:
    """Compatibility indexing features remain functional after demotion."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_group_index_populated(self):
        """groups index is populated after registration with groups."""
        reg = _fresh_registry()
        await reg.register(
            device_id="grp_01",
            device_type="android",
            groups=["mobile", "vip"],
        )

        assert "mobile" in reg.groups
        assert "grp_01" in reg.groups["mobile"]
        assert "vip" in reg.groups
        assert "grp_01" in reg.groups["vip"]

    @pytest.mark.asyncio
    async def test_tag_index_populated(self):
        """tag_index is populated after registration with tags."""
        reg = _fresh_registry()
        await reg.register(
            device_id="tag_01",
            device_type="android",
            tags=["test", "demo"],
        )

        assert "test" in reg.tag_index
        assert "tag_01" in reg.tag_index["test"]
        assert "demo" in reg.tag_index
        assert "tag_01" in reg.tag_index["demo"]

    @pytest.mark.asyncio
    async def test_capability_index_populated(self):
        """capability_index is populated after registration with capabilities."""
        reg = _fresh_registry()
        await reg.register(
            device_id="cap_01",
            device_type="android",
            capabilities=["screen", "camera"],
        )

        assert "screen" in reg.capability_index
        assert "cap_01" in reg.capability_index["screen"]
        assert "camera" in reg.capability_index
        assert "cap_01" in reg.capability_index["camera"]

    @pytest.mark.asyncio
    async def test_discover_by_capability(self):
        """discover() filters by capability index."""
        reg = _fresh_registry()
        await reg.register(
            device_id="disc_cap_01",
            device_type="android",
            capabilities=["camera"],
        )
        await reg.register(
            device_id="disc_cap_02",
            device_type="windows",
            capabilities=["keyboard"],
        )

        camera_devices = await reg.discover(capability="camera")
        ids = [d.device_id for d in camera_devices]
        assert "disc_cap_01" in ids
        assert "disc_cap_02" not in ids

    @pytest.mark.asyncio
    async def test_discover_by_group(self):
        """discover() filters by group index."""
        reg = _fresh_registry()
        await reg.register(
            device_id="disc_grp_01",
            device_type="android",
            groups=["mobile"],
        )
        await reg.register(
            device_id="disc_grp_02",
            device_type="windows",
            groups=["desktop"],
        )

        mobile_devices = await reg.discover(group="mobile")
        ids = [d.device_id for d in mobile_devices]
        assert "disc_grp_01" in ids
        assert "disc_grp_02" not in ids

    @pytest.mark.asyncio
    async def test_negotiate_capability_returns_capable_device(self):
        """negotiate_capability() returns a device with the requested capability."""
        reg = _fresh_registry()
        await reg.register(
            device_id="neg_01",
            device_type="android",
            capabilities=["camera"],
        )

        result = reg.negotiate_capability("camera")
        assert result is not None
        assert result.device_id == "neg_01"

    @pytest.mark.asyncio
    async def test_get_devices_by_group(self):
        """get_devices_by_group() returns devices in the requested group."""
        reg = _fresh_registry()
        await reg.register(device_id="bygrp_01", device_type="android", groups=["alpha"])
        await reg.register(device_id="bygrp_02", device_type="android", groups=["beta"])

        alpha = reg.get_devices_by_group("alpha")
        ids = [d.device_id for d in alpha]
        assert "bygrp_01" in ids
        assert "bygrp_02" not in ids

    @pytest.mark.asyncio
    async def test_get_devices_by_tag(self):
        """get_devices_by_tag() returns devices with the requested tag."""
        reg = _fresh_registry()
        await reg.register(device_id="bytag_01", device_type="android", tags=["prod"])
        await reg.register(device_id="bytag_02", device_type="android", tags=["dev"])

        prod_devices = reg.get_devices_by_tag("prod")
        ids = [d.device_id for d in prod_devices]
        assert "bytag_01" in ids
        assert "bytag_02" not in ids


# ---------------------------------------------------------------------------
# 5. Registry-derived views can be projected into RegisteredRuntimeDevice
# ---------------------------------------------------------------------------


class TestProjectionToContract:
    """project_to_contract() produces a valid RegisteredRuntimeDevice."""

    def setup_method(self):
        _reset_udm()

    @pytest.mark.asyncio
    async def test_project_returns_registered_runtime_device(self):
        """project_to_contract() returns a RegisteredRuntimeDevice instance."""
        from contracts.registered_runtime_device import RegisteredRuntimeDevice

        reg = _fresh_registry()
        await reg.register(
            device_id="proj_01",
            device_type="android",
            name="Projection Phone",
            capabilities=["screen", "camera"],
            groups=["mobile"],
            tags=["test"],
        )

        contract = reg.project_to_contract("proj_01")
        assert contract is not None, "project_to_contract() must not return None for known device"
        assert isinstance(contract, RegisteredRuntimeDevice)

    @pytest.mark.asyncio
    async def test_projected_device_id_matches(self):
        """Projected contract carries the correct device_id."""
        reg = _fresh_registry()
        await reg.register(device_id="proj_id_01", device_type="android")

        contract = reg.project_to_contract("proj_id_01")
        assert contract is not None
        assert contract.device_id == "proj_id_01"

    @pytest.mark.asyncio
    async def test_projected_capabilities_match(self):
        """Projected contract carries the capabilities from the registry record."""
        reg = _fresh_registry()
        await reg.register(
            device_id="proj_cap_01",
            device_type="android",
            capabilities=["screen", "microphone"],
        )

        contract = reg.project_to_contract("proj_cap_01")
        assert contract is not None
        cap_names = contract.capabilities.capabilities
        assert "screen" in cap_names
        assert "microphone" in cap_names

    @pytest.mark.asyncio
    async def test_projected_groups_in_participation_hints(self):
        """Projected contract carries groups in participation_hints."""
        reg = _fresh_registry()
        await reg.register(
            device_id="proj_grp_01",
            device_type="android",
            groups=["fleet", "vip"],
        )

        contract = reg.project_to_contract("proj_grp_01")
        assert contract is not None
        assert "fleet" in contract.participation_hints.groups
        assert "vip" in contract.participation_hints.groups

    @pytest.mark.asyncio
    async def test_project_unknown_device_returns_none(self):
        """project_to_contract() returns None for an unknown device_id."""
        reg = _fresh_registry()

        contract = reg.project_to_contract("does_not_exist_xyz")
        assert contract is None

    @pytest.mark.asyncio
    async def test_projected_contract_is_serialisable(self):
        """Projected contract can be serialised to a dict and round-tripped."""
        from contracts.registered_runtime_device import RegisteredRuntimeDevice

        reg = _fresh_registry()
        await reg.register(
            device_id="proj_ser_01",
            device_type="android",
            capabilities=["screen"],
        )

        contract = reg.project_to_contract("proj_ser_01")
        assert contract is not None
        d = contract.to_dict()
        assert isinstance(d, dict)
        assert d["device_id"] == "proj_ser_01"

        # Round-trip via from_dict
        restored = RegisteredRuntimeDevice.from_dict(d)
        assert restored.device_id == "proj_ser_01"
